"""
CyberClean — Declarative cleaning rules
════════════════════════════════════════════════════════════════
Luật dọn rác nằm trong file TOML (rules/*.toml) thay vì hàng nghìn dòng code
riêng lẻ: dễ thêm app, dễ review an toàn, người khác đóng góp bằng một PR nhỏ.

Hai loại bản ghi:

    [[target]]   thứ hiện trong UI: id, name, desc, tier (auto|review), safety...
    [[rule]]     nơi cần dọn: paths / mode / min_age_days / closed / keep ...
                 thuộc về một target qua `target = "<id>"`.

Rule không chứa lệnh, chỉ mô tả dữ liệu; mọi quyết định xóa vẫn đi qua
core/engine.py (tuổi, tiến trình đang chạy, file đang mở, symlink, mount...).

mode:
    tree      mỗi path khớp là MỘT mục, xóa cả cây (kể cả thư mục gốc)
    contents  giữ thư mục gốc, xóa bên trong (một mục cho mỗi gốc)
    children  mỗi con trực tiếp của gốc là một mục riêng (dùng cho Review)
    old_files chỉ xóa FILE đã quá tuổi bên dưới gốc (giữ cấu trúc thư mục)

kind (khám phá phức tạp hơn 'paths'):
    chromium  Chrome/Brave/Edge/Vivaldi/Opera + mọi app Electron: chỉ các thư mục
              cache (Cache, Code Cache, GPUCache...) của MỌI profile; không bao giờ
              đụng Cookies / Local Storage / IndexedDB.
    firefox   cache2, startupCache... của mọi profile Firefox (cả Flatpak/Snap).

Luật của người dùng (~/.config/cyber-clean/rules.d/*.toml) bị ép: tier = review,
chỉ kind = paths, mode = tree|children, đường dẫn phải nằm trong home, và CHỈ
được gắn vào target Review hợp lệ do chính user định nghĩa.
"""
from __future__ import annotations

import fnmatch
import glob as _glob
import ntpath
import os
import re
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import engine as E
from .engine import DAY, Guards, Plan, PlanItem, Policy

try:                                                       # Python ≥ 3.11
    import tomllib as _toml
except ModuleNotFoundError:                                # pragma: no cover
    try:
        import tomli as _toml                              # type: ignore
    except ModuleNotFoundError:
        _toml = None

SCHEMA = 1
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_TIERS = ("auto", "review")
_SAFETY = ("safe", "caution", "danger")
_MODES = ("tree", "contents", "children", "old_files")
_KINDS = ("paths", "chromium", "firefox")
_OSES = ("linux", "windows")

_TARGET_KEYS = {"id", "name", "desc", "tier", "safety", "os", "distro", "requires_any",
                "needs_root", "scheduled"}
_RULE_KEYS = {"id", "target", "kind", "mode", "paths", "os", "distro", "requires_any", "basis",
              "min_age_days", "sched_min_age_days", "closed", "keep", "skip_names", "skip_claimed",
              "note", "risk", "disk_only", "user_data", "discover", "subpaths", "profile_globs",
              "never", "closed_by_path", "cache_roots", "sandbox_check"}


class RuleError(ValueError):
    pass


# ══════════════════════════════════════════════════════════════
# Context (mở rộng đường dẫn)
# ══════════════════════════════════════════════════════════════

_VAR_RE = re.compile(r"\$\{(\w+)\}|\$(\w+)|%(\w+)%")


@dataclass
class RuleContext:
    os_name: str = "linux"                     # 'linux' | 'windows'
    home: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    distro_ids: Tuple[str, ...] = ()
    which: Callable[[str], Optional[str]] = shutil.which

    @classmethod
    def detect(cls) -> "RuleContext":
        from . import os_detect as od
        osn = "windows" if od.IS_WINDOWS else "linux"
        return cls(os_name=osn, home=str(od.real_home()), env=dict(os.environ),
                   distro_ids=tuple(x for x in [od.DISTRO, *od.DISTRO_LIKE] if x))

    # ── biến ──
    def _var(self, name: str) -> str:
        env = self.env
        if self.os_name == "windows":
            for k in (name, name.upper()):
                if env.get(k):
                    return env[k]
            if name.upper() == "USERPROFILE":
                return self.home
            raise KeyError(name)
        if name == "HOME":
            return self.home
        if name == "XDG_CACHE_HOME":
            return env.get(name) or os.path.join(self.home, ".cache")
        if name == "XDG_CONFIG_HOME":
            return env.get(name) or os.path.join(self.home, ".config")
        if name == "XDG_DATA_HOME":
            return env.get(name) or os.path.join(self.home, ".local", "share")
        if env.get(name):
            return env[name]
        raise KeyError(name)

    def expand(self, pattern: str) -> Optional[str]:
        """'~/x', '$XDG_CACHE_HOME/x', '%LOCALAPPDATA%\\x' → đường dẫn tuyệt đối; None nếu thiếu biến."""
        p = pattern
        if p == "~" or p.startswith("~/") or p.startswith("~\\"):
            p = self.home + p[1:]
        try:
            def rep(m):
                name = m.group(1) or m.group(2) or m.group(3)
                if m.group(3) and self.os_name != "windows":
                    return m.group(0)
                return self._var(name)
            p = _VAR_RE.sub(rep, p)
        except KeyError:
            return None
        if self.os_name == "windows":
            p = p.replace("/", "\\")
            return p if ntpath.isabs(p) else None
        return p if os.path.isabs(p) else None

    def glob(self, pattern: str) -> List[str]:
        p = self.expand(pattern)
        if not p:
            return []
        if not any(c in p for c in "*?["):
            return [p] if os.path.lexists(p) else []
        try:
            return sorted(_glob.glob(p))
        except Exception:
            return []

    def glob_all(self, patterns: Iterable[str]) -> List[str]:
        seen, out = set(), []
        for pat in patterns:
            for p in self.glob(pat):
                key = os.path.realpath(p) if os.path.islink(p) is False else p
                if key not in seen:
                    seen.add(key)
                    out.append(p)
        return out

    def tilde(self, path: str) -> str:
        h = self.home.rstrip("/\\")
        if h and (path == h or path.startswith(h + os.sep)):
            return "~" + path[len(h):]
        return path

    def distro_ok(self, wanted: Sequence[str]) -> bool:
        return not wanted or any(w in self.distro_ids for w in wanted)

    def os_ok(self, wanted: Sequence[str]) -> bool:
        return not wanted or self.os_name in wanted


# ══════════════════════════════════════════════════════════════
# Data model
# ══════════════════════════════════════════════════════════════

@dataclass
class TargetDef:
    id: str
    name: str
    desc: str = ""
    tier: str = "auto"
    safety: str = "safe"
    os: Tuple[str, ...] = ()
    distro: Tuple[str, ...] = ()
    requires_any: Tuple[str, ...] = ()
    needs_root: bool = False
    scheduled: bool = True
    source: str = "builtin"


@dataclass
class Rule:
    id: str
    target: str
    kind: str = "paths"
    mode: str = "tree"
    paths: Tuple[str, ...] = ()
    os: Tuple[str, ...] = ()
    distro: Tuple[str, ...] = ()
    requires_any: Tuple[str, ...] = ()
    basis: str = "mtime"
    min_age_days: float = 0.0
    sched_min_age_days: Optional[float] = None
    closed: Tuple[str, ...] = ()
    keep: Tuple[str, ...] = ()
    skip_names: Tuple[str, ...] = ()
    skip_claimed: bool = False
    note: str = ""
    risk: str = "low"
    disk_only: bool = False
    user_data: Tuple[str, ...] = ()
    discover: Tuple[str, ...] = ()
    subpaths: Tuple[str, ...] = ()
    profile_globs: Tuple[str, ...] = ("Default", "Profile *", "Guest Profile", "System Profile")
    never: Tuple[str, ...] = ()
    closed_by_path: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    cache_roots: Tuple[str, ...] = ()
    sandbox_check: bool = False     # app Flatpak: kiểm tra bwrap có đang bind thư mục này không
    source: str = "builtin"

    def policy(self, unattended: bool) -> Policy:
        if unattended:
            days = self.sched_min_age_days if self.sched_min_age_days is not None else max(self.min_age_days, 1.0)
            days = max(days, self.min_age_days)
        else:
            days = self.min_age_days
        return Policy(min_age_sec=days * DAY, basis=self.basis, closed=tuple(self.closed))


# ══════════════════════════════════════════════════════════════
# Parsing + validation
# ══════════════════════════════════════════════════════════════

def _tup(d: dict, key: str, where: str) -> Tuple[str, ...]:
    v = d.get(key, ())
    if v in ((), None):
        return ()
    if not isinstance(v, (list, tuple)) or not all(isinstance(x, str) and x for x in v):
        raise RuleError(f"{where}: '{key}' must be a list of non-empty strings")
    return tuple(v)


def _num(d: dict, key: str, where: str, default=None):
    if key not in d:
        return default
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v > 3650:
        raise RuleError(f"{where}: '{key}' must be a number between 0 and 3650")
    return float(v)


def _check_pattern(pat: str, where: str, user: bool) -> None:
    if "\x00" in pat:
        raise RuleError(f"{where}: NUL in path")
    parts = re.split(r"[\\/]+", pat)
    if ".." in parts:
        raise RuleError(f"{where}: '..' is not allowed in paths ({pat!r})")
    if user:
        ok_prefix = ("~/", "$XDG_CACHE_HOME/", "${XDG_CACHE_HOME}/", "$XDG_DATA_HOME/",
                     "${XDG_DATA_HOME}/", "$XDG_CONFIG_HOME/", "${XDG_CONFIG_HOME}/",
                     "%LOCALAPPDATA%\\", "%APPDATA%\\", "%USERPROFILE%\\")
        if not pat.startswith(ok_prefix):
            raise RuleError(f"{where}: user rules may only use paths inside your home ({pat!r})")


def parse_target(d: dict, source: str, src_name: str) -> TargetDef:
    where = f"{src_name} target {d.get('id', '?')!r}"
    unknown = set(d) - _TARGET_KEYS
    if unknown:
        raise RuleError(f"{where}: unknown key(s) {sorted(unknown)}")
    tid = d.get("id", "")
    if not isinstance(tid, str) or not _ID_RE.match(tid):
        raise RuleError(f"{where}: invalid id")
    tier = d.get("tier", "auto")
    if tier not in _TIERS:
        raise RuleError(f"{where}: tier must be one of {_TIERS}")
    if source == "user":
        tier = "review"
    safety = d.get("safety", "safe" if tier == "auto" else "caution")
    if safety not in _SAFETY:
        raise RuleError(f"{where}: safety must be one of {_SAFETY}")
    if tier == "auto" and safety != "safe":
        raise RuleError(f"{where}: an 'auto' target must have safety = 'safe'")
    oses = _tup(d, "os", where)
    if any(o not in _OSES for o in oses):
        raise RuleError(f"{where}: os must be in {_OSES}")
    return TargetDef(id=tid, name=str(d.get("name") or tid), desc=str(d.get("desc", "")), tier=tier,
                     safety=safety, os=oses, distro=_tup(d, "distro", where),
                     requires_any=_tup(d, "requires_any", where), needs_root=bool(d.get("needs_root", False)),
                     scheduled=bool(d.get("scheduled", tier == "auto")) and tier == "auto", source=source)


def parse_rule(d: dict, source: str, src_name: str) -> Rule:
    where = f"{src_name} rule {d.get('id', '?')!r}"
    unknown = set(d) - _RULE_KEYS
    if unknown:
        raise RuleError(f"{where}: unknown key(s) {sorted(unknown)}")
    rid, target = d.get("id", ""), d.get("target", "")
    if not isinstance(rid, str) or not _ID_RE.match(rid):
        raise RuleError(f"{where}: invalid id")
    if not isinstance(target, str) or not _ID_RE.match(target):
        raise RuleError(f"{where}: invalid target")
    kind = d.get("kind", "paths")
    if kind not in _KINDS:
        raise RuleError(f"{where}: kind must be one of {_KINDS}")
    mode = d.get("mode", "tree")
    if mode not in _MODES:
        raise RuleError(f"{where}: mode must be one of {_MODES}")
    user = source == "user"
    if user and (kind != "paths" or mode not in ("tree", "children")):
        raise RuleError(f"{where}: user rules may only use kind='paths' with mode 'tree' or 'children'")
    basis = d.get("basis", "mtime")
    if basis not in ("mtime", "atime"):
        raise RuleError(f"{where}: basis must be 'mtime' or 'atime'")
    risk = d.get("risk", "medium" if user else "low")
    if risk not in ("low", "medium", "high"):
        raise RuleError(f"{where}: risk must be low|medium|high")
    paths = _tup(d, "paths", where)
    user_data, discover = _tup(d, "user_data", where), _tup(d, "discover", where)
    cache_roots = _tup(d, "cache_roots", where)
    for pat in (*paths, *user_data, *discover, *cache_roots):
        _check_pattern(pat, where, user)
    if kind == "paths" and not paths:
        raise RuleError(f"{where}: 'paths' is required")
    if kind == "chromium" and not (user_data or discover):
        raise RuleError(f"{where}: chromium rule needs 'user_data' or 'discover'")
    if kind in ("chromium", "firefox") and not _tup(d, "subpaths", where):
        raise RuleError(f"{where}: 'subpaths' is required for kind={kind}")
    if kind == "firefox" and not cache_roots:
        raise RuleError(f"{where}: firefox rule needs 'cache_roots'")
    for sp in _tup(d, "subpaths", where):
        if ".." in re.split(r"[\\/]+", sp) or os.path.isabs(sp):
            raise RuleError(f"{where}: subpaths must be relative and without '..' ({sp!r})")
    cbp = d.get("closed_by_path", {}) or {}
    if not isinstance(cbp, dict) or not all(isinstance(v, list) for v in cbp.values()):
        raise RuleError(f"{where}: closed_by_path must map a path fragment to a list of process names")
    oses = _tup(d, "os", where)
    if any(o not in _OSES for o in oses):
        raise RuleError(f"{where}: os must be in {_OSES}")
    return Rule(
        id=rid, target=target, kind=kind, mode=mode, paths=paths, os=oses,
        distro=_tup(d, "distro", where), requires_any=_tup(d, "requires_any", where), basis=basis,
        min_age_days=_num(d, "min_age_days", where, 0.0) or 0.0,
        sched_min_age_days=_num(d, "sched_min_age_days", where, None),
        closed=_tup(d, "closed", where), keep=_tup(d, "keep", where),
        skip_names=_tup(d, "skip_names", where), skip_claimed=bool(d.get("skip_claimed", False)),
        note=str(d.get("note", "")), risk=risk, disk_only=bool(d.get("disk_only", False)),
        user_data=user_data, discover=discover, subpaths=_tup(d, "subpaths", where),
        profile_globs=_tup(d, "profile_globs", where) or Rule.__dataclass_fields__["profile_globs"].default,
        never=_tup(d, "never", where), closed_by_path={k: tuple(v) for k, v in cbp.items()},
        cache_roots=cache_roots, sandbox_check=bool(d.get("sandbox_check", False)), source=source)


# ══════════════════════════════════════════════════════════════
# RuleSet
# ══════════════════════════════════════════════════════════════

_SYSTEM_DIRS = {"/", "/usr", "/etc", "/boot", "/bin", "/sbin", "/lib", "/lib64", "/opt", "/proc",
                "/sys", "/dev", "/run", "/srv", "/mnt", "/media", "/root", "/var", "/home"}


def forbidden_root(path: str, ctx: RuleContext, *, require_inside_home: bool = False) -> str:
    """
    Lý do KHÔNG bao giờ được dùng path làm gốc dọn dẹp ('' nếu ổn).
    Kiểm tra cả đường dẫn chuẩn hóa, đường dẫn thực (realpath), và các thư mục cha
    để ngăn symlink/junction ở thư mục cha trỏ ra ngoài phạm vi cho phép.
    """
    p = os.path.normpath(path)
    if ctx.os_name == "windows":
        low = p.lower().rstrip("\\")
        sysroot = (ctx.env.get("SystemRoot") or "C:\\Windows").lower().rstrip("\\")
        home_low = (ctx.home or "").lower().rstrip("\\")
        bad = {sysroot, sysroot + "\\system32", "c:\\users", "c:\\program files", "c:\\program files (x86)",
               "c:\\programdata", home_low}
        if re.fullmatch(r"[a-z]:", low) or low in bad:
            return "protected system location"
        if require_inside_home and home_low:
            if not low.startswith(home_low + "\\"):
                return "escapes home directory"
        return ""

    home_norm = os.path.normpath(ctx.home) if ctx.home else ""
    if p in _SYSTEM_DIRS or (home_norm and (p == home_norm or home_norm.startswith(p.rstrip("/") + "/"))):
        return "protected system location"

    try:
        real_p = os.path.normpath(os.path.realpath(p))
        real_home = os.path.normpath(os.path.realpath(home_norm)) if home_norm else ""
        if real_p in _SYSTEM_DIRS or (real_home and (real_p == real_home or real_home.startswith(real_p.rstrip("/") + "/"))):
            return "protected system location"
    except OSError:
        pass

    if require_inside_home and home_norm:
        why_anc, _ = E.check_ancestor_chain(p, home_norm)
        if why_anc:
            return why_anc
    else:
        why_anc, _ = E.check_ancestor_chain(p, None)
        if why_anc:
            return why_anc

    return ""


def _allowed_root_for_rule(rule: Rule, root: str, ctx: RuleContext) -> Optional[str]:
    """
    Xác định phạm vi gốc được phép của một rule:
    - Mọi user rule đều bắt buộc nằm trong ctx.home.
    - Builtin rule có pattern bắt đầu bằng ~, $HOME, $XDG_*, %LOCALAPPDATA%, %APPDATA%, %USERPROFILE%
      cũng phải nằm trong ctx.home (nếu các biến XDG không bị cấu hình ra ngoài home).
    """
    if rule.source == "user":
        return ctx.home or None
    if ctx.home:
        h = os.path.normpath(ctx.home)
        r = os.path.normpath(root)
        sep = "\\" if ctx.os_name == "windows" else "/"
        h_cmp = h.lower() if ctx.os_name == "windows" else h
        r_cmp = r.lower() if ctx.os_name == "windows" else r
        if r_cmp == h_cmp or r_cmp.startswith(h_cmp.rstrip("/\\") + sep):
            return h
    return None


def _cls(rule_id: str, kind: str) -> str:
    return f"{kind}:{rule_id}"


@dataclass
class RuleSet:
    # Một target id có thể được định nghĩa riêng cho từng hệ điều hành (rules/linux.toml và
    # rules/windows.toml cùng có "chromium_cache") → lưu danh sách, chọn theo ngữ cảnh.
    targets: Dict[str, List[TargetDef]] = field(default_factory=dict)
    rules: List[Rule] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def _is_valid_user_target(self, target_id: str) -> bool:
        defs = self.targets.get(target_id, [])
        if not defs:
            return False
        return all(t.source == "user" and t.tier == "review" and not t.scheduled for t in defs)

    # ── nạp ──
    def load_text(self, text: str, source: str = "builtin", name: str = "<memory>") -> None:
        if _toml is None:
            raise RuleError("TOML parser unavailable (Python < 3.11 needs the 'tomli' package)")
        try:
            data = _toml.loads(text)
        except Exception as e:
            raise RuleError(f"{name}: invalid TOML: {e}")
        if data.get("schema") != SCHEMA:
            raise RuleError(f"{name}: unsupported schema {data.get('schema')!r} (expected {SCHEMA})")

        new_targets: Dict[str, List[TargetDef]] = {}
        for td in data.get("target", []):
            t = parse_target(td, source, name)
            if t.id in self.targets and source == "user":
                raise RuleError(f"{name}: user rules may not redefine target {t.id!r}")
            for other in (*self.targets.get(t.id, []), *new_targets.get(t.id, [])):
                if not t.os or not other.os or set(t.os) & set(other.os):
                    raise RuleError(f"{name}: target {t.id!r} is defined twice for the same OS")
            new_targets.setdefault(t.id, []).append(t)

        new_rules: List[Rule] = []
        seen_ids = {x.id for x in self.rules}
        for rd in data.get("rule", []):
            r = parse_rule(rd, source, name)
            if r.id in seen_ids:
                raise RuleError(f"{name}: duplicate rule id {r.id!r}")
            if source == "user":
                cand_defs = new_targets.get(r.target) or self.targets.get(r.target) or []
                if not cand_defs:
                    raise RuleError(
                        f"{name} rule {r.id!r}: user rule must reference a user-defined Review target "
                        f"(target {r.target!r} is not defined)"
                    )
                if any(t.source != "user" or t.tier != "review" or t.scheduled for t in cand_defs):
                    raise RuleError(
                        f"{name} rule {r.id!r}: user rules may not attach to builtin or auto target {r.target!r}"
                    )
            seen_ids.add(r.id)
            new_rules.append(r)

        for tid, tlist in new_targets.items():
            self.targets.setdefault(tid, []).extend(tlist)
        self.rules.extend(new_rules)

    def load_file(self, path: Path, source: str = "builtin") -> None:
        try:
            self.load_text(Path(path).read_text(encoding="utf-8"), source, Path(path).name)
        except RuleError as e:
            if source == "builtin":
                raise
            self.errors.append(str(e))          # luật người dùng hỏng → bỏ qua, không làm app chết

    def validate(self) -> List[str]:
        """Kiểm tra chéo: rule phải trỏ tới target tồn tại; user rule chỉ được trỏ tới user Review target."""
        problems = []
        for r in self.rules:
            if r.target not in self.targets:
                problems.append(f"rule {r.id!r} refers to unknown target {r.target!r}")
                continue
            if r.source == "user" and not self._is_valid_user_target(r.target):
                problems.append(
                    f"user rule {r.id!r} may only reference a user-defined review target (got {r.target!r})"
                )
        return problems

    # ── truy vấn ──
    def target_defs(self, ctx: RuleContext) -> List[TargetDef]:
        out = []
        for defs in self.targets.values():
            for t in defs:
                if not ctx.os_ok(t.os) or not ctx.distro_ok(t.distro):
                    continue
                if t.requires_any and not any(ctx.which(c) for c in t.requires_any):
                    continue
                out.append(t)
                break
        return out

    def target_def(self, target_id: str, ctx: RuleContext) -> Optional[TargetDef]:
        for t in self.targets.get(target_id, []):
            if ctx.os_ok(t.os) and ctx.distro_ok(t.distro):
                return t
        return None

    def rules_for(self, target_id: str, ctx: RuleContext) -> List[Rule]:
        tdef = self.target_def(target_id, ctx)
        out = []
        for r in self.rules:
            if r.target != target_id or not ctx.os_ok(r.os) or not ctx.distro_ok(r.distro):
                continue
            if r.source == "user":
                if tdef is None or tdef.source != "user" or tdef.tier != "review" or tdef.scheduled:
                    continue
                if not self._is_valid_user_target(target_id):
                    continue
            if r.requires_any and not any(ctx.which(c) for c in r.requires_any):
                continue
            out.append(r)
        return out

    def claimed_cache_names(self, ctx: RuleContext, exclude: str = "") -> set:
        """Tên thư mục cấp 1 trong ~/.cache đã được rule khác quản lý (để Review không liệt kê lại)."""
        cache = ctx.expand("$XDG_CACHE_HOME") if ctx.os_name == "linux" else None
        names: set = set()
        if not cache:
            return names
        prefix = cache.rstrip("/") + "/"
        for r in self.rules:
            if r.id == exclude or not ctx.os_ok(r.os):
                continue
            for pat in (*r.paths, *r.user_data, *r.discover, *r.cache_roots):
                exp = ctx.expand(pat)
                if exp and exp.startswith(prefix):
                    first = exp[len(prefix):].split("/")[0]
                    if first and not any(c in first for c in "*?["):
                        names.add(first)
        return names

    # ── dựng plan ──
    def plan(self, target_id: str, ctx: RuleContext, *, unattended: bool = False,
             guards: Optional[Guards] = None, deadline: Optional[float] = None) -> Plan:
        plan = Plan(target_id)
        tdef = self.target_def(target_id, ctx)
        if unattended and tdef is not None and (tdef.tier != "auto" or not tdef.scheduled or tdef.source == "user"):
            plan.notes.append(f"Target {target_id!r} is not eligible for unattended execution")
            return plan
        guards = guards or Guards()
        for rule in self.rules_for(target_id, ctx):
            if unattended and rule.source == "user":
                continue
            builder = _BUILDERS[rule.kind]
            builder(self, rule, ctx, rule.policy(unattended), guards, plan, deadline)
        _summarise_blocked(plan, ctx)
        return plan


def _record(plan: Plan, path: str, item: Optional[PlanItem], why: str) -> None:
    if item is not None:
        plan.items.append(item)
    elif why and why != "gone":
        plan.skipped.append((path, why))


def _summarise_blocked(plan: Plan, ctx: RuleContext) -> None:
    reasons: Dict[str, int] = {}
    for it in plan.items:
        if it.blocked:
            reasons[it.blocked] = reasons.get(it.blocked, 0) + 1
    for why, n in sorted(reasons.items()):
        plan.notes.append(f"{why} ({n} location{'s' if n != 1 else ''} skipped)")


# ── kind = paths ────────────────────────────────────────────────────────────
def _build_paths(rs: RuleSet, rule: Rule, ctx: RuleContext, policy: Policy, guards: Guards,
                 plan: Plan, deadline) -> None:
    claimed = rs.claimed_cache_names(ctx, exclude=rule.id) if rule.skip_claimed else set()
    cache_home = ctx.expand("$XDG_CACHE_HOME") if ctx.os_name == "linux" else None
    is_core_rule = rule.id == "crash-core-files"

    for root in ctx.glob_all(rule.paths):
        allowed_root = _allowed_root_for_rule(rule, root, ctx)
        bad = forbidden_root(root, ctx, require_inside_home=(rule.source == "user"))
        if bad:
            plan.skipped.append((root, bad))
            continue
        if allowed_root:
            why_anc, _ = E.check_ancestor_chain(root, allowed_root)
            if why_anc:
                plan.skipped.append((root, why_anc))
                continue
        if rule.disk_only and E.is_ram_backed(root):
            msg = f"{ctx.tilde(root)} is RAM-backed (tmpfs) — cleaning it would free memory, not disk"
            if msg not in plan.notes:
                plan.notes.append(msg)
            continue

        # A1: crash-core-files chỉ được dọn FILE THƯỜNG đã xác minh đúng định dạng ELF core dump (ET_CORE).
        # Tuyệt đối không xóa thư mục ~/core hoặc thư mục khớp /tmp/core.*, cũng không xóa file thường trùng tên.
        if is_core_rule:
            try:
                st_core = os.lstat(root)
            except OSError:
                continue
            if E.is_link_like(st_core):
                plan.skipped.append((root, "symlink / reparse point (never followed)"))
                continue
            if stat.S_ISDIR(st_core.st_mode):
                plan.skipped.append((root, "directory named core — not a core dump"))
                continue
            if not stat.S_ISREG(st_core.st_mode) or not E.is_elf_core_file(root):
                plan.skipped.append((root, "not a verified ELF core dump file"))
                continue

        if rule.mode == "old_files":
            item = E.plan_old_files(root, policy, guards=guards, label=ctx.tilde(root), group=rule.id,
                                    note=rule.note, keep=rule.keep, allowed_root=allowed_root)
            if item:
                item.risk = rule.risk
                if rule.sandbox_check:
                    item.meta["sandbox_paths"] = (root,)
                    if guards.sandboxed(root):
                        item.blocked = "the Flatpak app is running — close it first"
                if policy.closed:
                    hit = guards.running(policy.closed)
                    if hit:
                        item.blocked = f"{hit} is running — close it first"
                plan.items.append(item)
        elif rule.mode in ("tree", "contents"):
            item, why = E.make_item(root, policy, guards=guards, label=ctx.tilde(root), group=rule.id,
                                    note=rule.note, risk=rule.risk, keep_root=rule.mode == "contents",
                                    deadline=deadline, allowed_root=allowed_root,
                                    keep=rule.keep if rule.mode == "contents" else ())
            if item is not None:
                if rule.mode == "contents":
                    item.meta["keep"] = tuple(rule.keep)
                if is_core_rule:
                    item.meta["require_core_dump"] = True
                if rule.sandbox_check:
                    item.meta["sandbox_paths"] = (root,)
                    if guards.sandboxed(root):
                        item.blocked = "the Flatpak app is running — close it first"
                        why = item.blocked
            _record(plan, root, item, why)
        else:                                                   # children
            try:
                st_root = os.lstat(root)
            except OSError:
                continue
            if E.is_link_like(st_root) or not stat.S_ISDIR(st_root.st_mode):
                plan.skipped.append((root, "root is a symlink / reparse point or not a directory"))
                continue
            child_allowed = allowed_root or os.path.abspath(root)
            for e in E.iter_dir(root):
                name = e.name
                if any(fnmatch.fnmatchcase(name, pat) for pat in rule.skip_names):
                    continue
                if root == cache_home and name in claimed:
                    continue
                item, why = E.make_item(e.path, policy, guards=guards, label=ctx.tilde(e.path),
                                        group=rule.id, note=rule.note, risk=rule.risk, deadline=deadline,
                                        allowed_root=child_allowed)
                if item is not None and rule.sandbox_check:
                    item.meta["sandbox_paths"] = (root, e.path)
                    if guards.sandboxed(root) or guards.sandboxed(e.path):
                        item.blocked = "the Flatpak app is running — close it first"
                        why = item.blocked
                _record(plan, e.path, item, why)


# ── kind = chromium ─────────────────────────────────────────────────────────
def _is_dir(p: str) -> bool:
    return os.path.isdir(p) and not os.path.islink(p)


def _looks_chromium(ud: str, rule: Rule) -> bool:
    """Dấu hiệu 'user-data dir' của Chromium/Electron (tránh dọn nhầm thư mục có tên 'Cache' của app khác)."""
    has = lambda n: os.path.lexists(os.path.join(ud, n))          # noqa: E731
    finger = (has("Local State") or has("Local Storage")
              or (has("Preferences") and (has("Cookies") or has("Network"))))
    if finger:
        return True
    # cây ~/.cache: chỉ chứa cache nên nhận diện theo cấu trúc profile/<subpath>
    for e in E.iter_dir(ud):
        if e.is_dir(follow_symlinks=False) and any(fnmatch.fnmatchcase(e.name, g) for g in rule.profile_globs):
            if any(_is_dir(os.path.join(e.path, *sp.split("/"))) for sp in rule.subpaths):
                return True
    return False


def _chromium_guard_spec(ud: str, rule: Rule) -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]:
    """
    Trả về (chromium_dirs, closed_procs, sandbox_paths) cho một thư mục user-data `ud`
    để lưu vào PlanItem và kiểm tra lại lúc execute.
    """
    dirs = [ud]
    for a, b in (("/.cache/", "/.config/"), ("/cache/", "/config/")):
        if a in ud:
            dirs.append(ud.replace(a, b, 1))
        elif b in ud:
            dirs.append(ud.replace(b, a, 1))
    # dedup giữ thứ tự
    seen_d = set()
    uniq_dirs = []
    for d in dirs:
        if d not in seen_d:
            seen_d.add(d)
            uniq_dirs.append(d)

    procs: List[str] = list(rule.closed)
    norm = ud.replace("\\", "/").lower()
    for frag, names in rule.closed_by_path.items():
        if frag.replace("\\", "/").lower() in norm:
            for n in names:
                if n not in procs:
                    procs.append(n)

    sandbox_paths: List[str] = []
    if "/.var/app/" in ud.replace("\\", "/"):
        sandbox_paths.extend(uniq_dirs)

    return tuple(uniq_dirs), tuple(procs), tuple(sandbox_paths)


def _chromium_running(ud: str, ctx: RuleContext, rule: Rule, guards: Guards) -> str:
    dirs, procs, sandbox_paths = _chromium_guard_spec(ud, rule)
    for d in dirs:
        if E.chromium_profile_in_use(d) or guards.user_data_dir_in_use(d):
            cleaned_ud = ud.rstrip('/\\')
            return f"{os.path.basename(cleaned_ud)} is running — close it first"
    if procs:
        hit = guards.running(procs)
        if hit:
            return f"{hit} is running — close it first"
    for sp in sandbox_paths:
        if guards.sandboxed(sp):
            return "the Flatpak app is running — close it first"
    return ""


def _build_chromium(rs: RuleSet, rule: Rule, ctx: RuleContext, policy: Policy, guards: Guards,
                    plan: Plan, deadline) -> None:
    cands: Dict[str, str] = {}
    for pat in rule.user_data:
        for p in ctx.glob(pat):
            if _is_dir(p):
                cands.setdefault(os.path.realpath(p), p)
    for pat in rule.discover:
        for p in ctx.glob(pat):
            if _is_dir(p) and os.path.realpath(p) not in cands and _looks_chromium(p, rule):
                cands[os.path.realpath(p)] = p
    for ud in cands.values():
        allowed_root = _allowed_root_for_rule(rule, ud, ctx)
        if allowed_root:
            why_anc, _ = E.check_ancestor_chain(ud, allowed_root)
            if why_anc:
                plan.skipped.append((ud, why_anc))
                continue
        c_dirs, c_procs, c_sandbox = _chromium_guard_spec(ud, rule)
        pol = Policy(min_age_sec=policy.min_age_sec, basis=policy.basis, closed=c_procs)
        why_running = _chromium_running(ud, ctx, rule, guards)
        bases = [ud] + [e.path for e in E.iter_dir(ud)
                        if e.is_dir(follow_symlinks=False)
                        and any(fnmatch.fnmatchcase(e.name, g) for g in rule.profile_globs)]
        for base in bases:
            for sub in rule.subpaths:
                parts = [seg for seg in re.split(r"[\\/]+", sub) if seg]
                tgt = os.path.join(base, *parts)
                if not _is_dir(tgt):
                    continue
                item, why = E.make_item(tgt, pol, guards=guards, group=rule.id, note=rule.note,
                                        risk=rule.risk, label=ctx.tilde(tgt), deadline=deadline,
                                        allowed_root=allowed_root)
                if item is not None:
                    item.closed = c_procs
                    item.meta["chromium_dirs"] = c_dirs
                    if c_sandbox:
                        item.meta["sandbox_paths"] = c_sandbox
                    if why_running:
                        item.blocked = why_running
                        why = why_running
                _record(plan, tgt, item, why)


# ── kind = firefox ──────────────────────────────────────────────────────────
def _build_firefox(rs: RuleSet, rule: Rule, ctx: RuleContext, policy: Policy, guards: Guards,
                   plan: Plan, deadline) -> None:
    running = guards.running(rule.closed) if rule.closed else ""
    why_running = f"{running} is running — close it first" if running else ""
    pol = Policy(min_age_sec=policy.min_age_sec, basis=policy.basis, closed=tuple(rule.closed))
    for root in ctx.glob_all(rule.cache_roots):
        if not _is_dir(root):
            continue
        allowed_root = _allowed_root_for_rule(rule, root, ctx)
        if allowed_root:
            why_anc, _ = E.check_ancestor_chain(root, allowed_root)
            if why_anc:
                plan.skipped.append((root, why_anc))
                continue
        is_flatpak_root = "/.var/app/" in root.replace("\\", "/")
        why_root_sandbox = "the Flatpak app is running — close it first" if (is_flatpak_root and guards.sandboxed(root)) else ""
        for prof in E.iter_dir(root):
            if not prof.is_dir(follow_symlinks=False):
                continue
            for sub in rule.subpaths:
                parts = [seg for seg in re.split(r"[\\/]+", sub) if seg]
                tgt = os.path.join(prof.path, *parts)
                if not _is_dir(tgt):
                    continue
                item, why = E.make_item(tgt, pol, guards=guards, group=rule.id, note=rule.note,
                                        risk=rule.risk, label=ctx.tilde(tgt), deadline=deadline,
                                        allowed_root=allowed_root)
                if item is not None:
                    item.closed = tuple(rule.closed)
                    if is_flatpak_root:
                        item.meta["sandbox_paths"] = (root, prof.path)
                    block_reason = why_running or why_root_sandbox
                    if block_reason:
                        item.blocked = block_reason
                        why = block_reason
                _record(plan, tgt, item, why)


_BUILDERS = {"paths": _build_paths, "chromium": _build_chromium, "firefox": _build_firefox}


# ══════════════════════════════════════════════════════════════
# Loading helpers
# ══════════════════════════════════════════════════════════════

def rules_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        for cand in (Path(base) / "rules", Path(base) / "_internal" / "rules"):
            if cand.is_dir():
                return cand
    return Path(__file__).resolve().parent.parent / "rules"


def user_rules_dir(ctx: RuleContext) -> Path:
    if ctx.os_name == "windows":
        return Path(ctx.env.get("APPDATA") or ctx.home) / "CyberClean" / "rules.d"
    return Path(ctx.env.get("XDG_CONFIG_HOME") or os.path.join(ctx.home, ".config")) / "cyber-clean" / "rules.d"


def load_default(ctx: Optional[RuleContext] = None, *, include_user: bool = True) -> RuleSet:
    ctx = ctx or RuleContext.detect()
    rs = RuleSet()
    d = rules_dir()
    for f in sorted(d.glob("*.toml")):
        rs.load_file(f, "builtin")
    if include_user:
        ud = user_rules_dir(ctx)
        if ud.is_dir():
            for f in sorted(ud.glob("*.toml")):
                rs.load_file(f, "user")
    problems = rs.validate()
    if problems:
        raise RuleError("; ".join(problems))
    return rs


def now() -> float:                                         # nơi duy nhất test có thể patch
    return time.time()
