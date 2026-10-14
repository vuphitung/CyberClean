"""
CyberClean — Advisor (tier 3: REPORT ONLY)
════════════════════════════════════════════════════════════════
Nơi "dọn sâu" thật sự nằm: máy ảo, /opt, gói nặng, file lớn, Downloads, thư mục
build của dự án cũ, game, WSL... App KHÔNG xóa thay người dùng — chỉ chỉ ra chỗ nào
đang ngốn dung lượng, tuổi của nó và cách xử lý, để người dùng tự quyết.

Module này không import Qt và không có bất kỳ lệnh xóa/ghi nào (có test kiểm tra
bằng AST). Mọi collector đều có hạn thời gian và có thể hủy giữa chừng.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import engine as E

IS_WINDOWS = sys.platform == "win32"
MB, GB = 1024 ** 2, 1024 ** 3

VM_EXT = {".qcow2", ".qcow", ".vdi", ".vmdk", ".vhd", ".vhdx", ".ova", ".ovf", ".vbox", ".img", ".raw"}
ISO_EXT = {".iso"}
ARCHIVE_EXT = {".zip", ".tar", ".gz", ".xz", ".zst", ".7z", ".rar", ".bz2", ".tgz"}
CATEGORY_ORDER = ["vm", "games", "containers", "wsl", "windows", "projects", "packages", "opt",
                  "downloads", "large", "info"]
CATEGORY_TITLES = {
    "vm": "Virtual machines & disk images", "games": "Games & compatibility layers",
    "containers": "Containers", "wsl": "WSL / Docker Desktop disks", "windows": "Windows leftovers",
    "projects": "Old project build folders", "packages": "Heaviest installed packages",
    "opt": "/opt", "downloads": "Downloads folder", "large": "Large files", "info": "Notes",
}


@dataclass
class Finding:
    category: str
    title: str
    path: str = ""
    size: int = 0
    age_days: Optional[int] = None
    advice: str = ""
    open_path: str = ""          # thư mục để mở trong trình quản lý file
    advice_key: str = ""         # khóa dịch ở tầng UI (adv_<key>); advice là bản tiếng Anh mặc định
    advice_args: dict = field(default_factory=dict)
    title_key: str = ""
    title_args: dict = field(default_factory=dict)


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    truncated: bool = False
    seconds: float = 0.0

    def by_category(self) -> Dict[str, List[Finding]]:
        out: Dict[str, List[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.category, []).append(f)
        for lst in out.values():
            lst.sort(key=lambda x: -x.size)
        return {c: out[c] for c in CATEGORY_ORDER if c in out}

    @property
    def total(self) -> int:
        return sum(f.size for f in self.findings if f.category != "info")


def human(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{n} B"


def _age(mtime: float, now: float) -> Optional[int]:
    return int((now - mtime) / 86400) if mtime else None


class _Budget:
    def __init__(self, seconds: float, stop: Optional[Callable[[], bool]] = None):
        self.end = time.monotonic() + seconds
        self.stop = stop or (lambda: False)
        self.hit = False

    def expired(self) -> bool:
        if self.stop() or time.monotonic() > self.end:
            self.hit = True
            return True
        return False

    def sub(self, fraction: float) -> "_Budget":
        b = _Budget(0, self.stop)
        b.end = time.monotonic() + max(1.0, (self.end - time.monotonic()) * fraction)
        return b


# ══════════════════════════════════════════════════════════════
# Shared walker (một lượt duyệt home cho cả file lớn + project artifacts)
# ══════════════════════════════════════════════════════════════

_SKIP_DIRS_LINUX = {".cache", ".Trash", ".gvfs", ".ccache", ".npm", ".gradle", ".m2", ".cargo", ".rustup",
                    "proc", "sys", "dev", "lost+found"}
_SKIP_DIRS_WIN = {"appdata", "$recycle.bin", "windows", "program files", "program files (x86)", "programdata",
                  "onedrive"}


@dataclass
class WalkResult:
    big: List[Tuple[str, int, float]] = field(default_factory=list)       # (path, size, mtime)
    artifacts: List[Tuple[str, str]] = field(default_factory=list)        # (path, kind)
    entries: int = 0


def walk_home(root: str, *, big_min: int, budget: _Budget, max_depth: int = 14,
              want_artifacts: bool = True, max_entries: int = 2_500_000) -> WalkResult:
    res = WalkResult()
    try:
        dev = os.lstat(root).st_dev
    except OSError:
        return res
    skip = _SKIP_DIRS_WIN if IS_WINDOWS else _SKIP_DIRS_LINUX
    stack: List[Tuple[str, int]] = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for e in it:
                res.entries += 1
                if (res.entries & 0x3FF) == 0 and budget.expired():
                    return res
                if res.entries > max_entries:
                    budget.hit = True
                    return res
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if E.is_link_like(st):
                    continue
                if e.is_dir(follow_symlinks=False):
                    name = e.name
                    if st.st_dev != dev:
                        continue
                    if name.lower() in skip:
                        continue
                    if want_artifacts:
                        if name == "node_modules":
                            res.artifacts.append((e.path, "node_modules"))
                            continue
                        if name == "target" and os.path.exists(os.path.join(cur, "Cargo.toml")):
                            res.artifacts.append((e.path, "cargo target"))
                            continue
                        if name in (".venv", "venv", "env") and os.path.exists(os.path.join(e.path, "pyvenv.cfg")):
                            res.artifacts.append((e.path, "python venv"))
                            continue
                    if depth < max_depth:
                        stack.append((e.path, depth + 1))
                elif E.is_special(st.st_mode):
                    continue
                elif st.st_size >= big_min:
                    res.big.append((e.path, st.st_size, st.st_mtime))
    return res


def _project_age(artifact_path: str, now: float) -> Optional[int]:
    """Tuổi của DỰ ÁN (không phải của thư mục build): mốc sửa mới nhất ở cấp trên cùng của thư mục chứa nó."""
    parent = os.path.dirname(artifact_path)
    newest = 0.0
    for e in E.iter_dir(parent):
        if e.name in ("node_modules", "target", ".venv", "venv", "env", "dist", "build", ".next", "__pycache__"):
            continue
        try:
            newest = max(newest, e.stat(follow_symlinks=False).st_mtime)
        except OSError:
            pass
    return _age(newest, now) if newest else None


# ══════════════════════════════════════════════════════════════
# Collectors
# ══════════════════════════════════════════════════════════════

def _xdg_dir(name: str, home: str, default: str) -> str:
    cfg = os.path.join(home, ".config", "user-dirs.dirs")
    try:
        with open(cfg, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(rf'^\s*XDG_{name}_DIR="?([^"\n]+)"?', line)
                if m:
                    return m.group(1).replace("$HOME", home)
    except OSError:
        pass
    return os.path.join(home, default)


def collect_downloads(home: str, now: float, budget: _Budget, *, old_days: int = 90,
                      exclude: Optional[set] = None) -> List[Finding]:
    d = _xdg_dir("DOWNLOAD", home, "Downloads") if not IS_WINDOWS else os.path.join(home, "Downloads")
    if not os.path.isdir(d):
        return []
    files: List[Tuple[str, int, float]] = []
    for e in E.iter_dir(d):
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if E.is_link_like(st):
            continue
        if e.is_dir(follow_symlinks=False):
            ts = E.tree_stats(e.path, deadline=time.monotonic() + 5)
            files.append((e.path, ts.size, ts.newest))
        else:
            files.append((e.path, st.st_size, st.st_mtime))
        if budget.expired():
            break
    total = sum(s for _, s, _ in files)
    stale = [(p, s, m) for p, s, m in files if _age(m, now) is not None and _age(m, now) >= old_days]
    out: List[Finding] = []
    if files:
        out.append(Finding("downloads", f"Downloads folder — {len(files)} item{'s' if len(files) != 1 else ''}", d, total,
                           advice=f"{len(stale)} item{'s' if len(stale) != 1 else ''} ({human(sum(s for _, s, _ in stale))}) are older than "
                                  f"{old_days} days. Sort by size and delete installers / ISOs you no longer need.",
                           open_path=d, advice_key="dl_summary",
                           advice_args={"n": len(stale), "size": human(sum(s for _, s, _ in stale)), "days": old_days},
                           title_key="dl_title", title_args={"n": len(files)}))
    for p, s, m in sorted(files, key=lambda x: -x[1])[:15]:
        if s < 50 * MB:
            break
        if exclude and p in exclude:
            continue                      # đã được báo ở mục chuyên biệt hơn (VM / game / file lớn)
        ext = os.path.splitext(p)[1].lower()
        if ext in ISO_EXT:
            key, what = "dl_iso", "ISO image — keep only if you still need it to install"
        elif ext in ARCHIVE_EXT:
            key, what = "dl_archive", "archive — already extracted? then it can go"
        elif ext in (".exe", ".msi", ".deb", ".rpm", ".appimage", ".dmg", ".pkg"):
            key, what = "dl_installer", "installer/package — usually safe to delete after installing"
        else:
            key, what = "dl_large", "large download"
        out.append(Finding("downloads", os.path.basename(p), p, s, _age(m, now), what, os.path.dirname(p),
                           advice_key=key))
    return out


def collect_big_files(walk: WalkResult, now: float) -> List[Finding]:
    out: List[Finding] = []
    for path, size, mtime in sorted(walk.big, key=lambda x: -x[1]):
        low = path.lower().replace("\\", "/")
        ext = os.path.splitext(low)[1]
        if ext in VM_EXT or ext in ISO_EXT:
            cat = "vm"
            key, advice = (("big_vm", "VM / disk image — shut the VM down and delete it (or compact the disk) if you no longer use it")
                           if ext not in ISO_EXT else ("big_iso", "ISO image — delete after the installation it was for"))
        elif "/steamapps/" in low or "/heroic/" in low or "/lutris/" in low or "/.wine" in low or "/games/" in low:
            cat = "games"
            key, advice = "big_game", "game data — uninstall from the launcher (Steam/Heroic/Lutris) rather than deleting by hand"
        else:
            cat = "large"
            key, advice = "big_large", "large file — check whether you still need it"
        out.append(Finding(cat, os.path.basename(path), path, size, _age(mtime, now), advice, os.path.dirname(path),
                           advice_key=key))
        if len(out) >= 60:
            break
    return out


def collect_project_artifacts(walk: WalkResult, now: float, budget: _Budget, *, min_mb: int = 50,
                              min_age_days: int = 60) -> List[Finding]:
    out: List[Finding] = []
    for path, kind in walk.artifacts:
        if budget.expired():
            break
        ts = E.tree_stats(path, deadline=time.monotonic() + 8)
        size = ts.size + ts.shared
        if size < min_mb * MB:
            continue
        age = _project_age(path, now)
        if age is not None and age < min_age_days:
            continue
        regen = {"node_modules": "`npm install` / `pnpm install` rebuilds it",
                 "cargo target": "`cargo build` rebuilds it (or `cargo clean`)",
                 "python venv": "recreate with `python -m venv` + `pip install -r requirements.txt`"}[kind]
        key = {"node_modules": "proj_node", "cargo target": "proj_cargo", "python venv": "proj_venv"}[kind]
        out.append(Finding("projects", f"{kind} — {os.path.basename(os.path.dirname(path))}", path, size, age,
                           f"Project untouched for {age} days; {regen}." if age is not None else regen,
                           os.path.dirname(path), advice_key=key if age is not None else key + "_noage",
                           advice_args={"age": age if age is not None else 0}))
    out.sort(key=lambda f: -f.size)
    return out[:25]


def collect_opt(budget: _Budget) -> List[Finding]:
    out: List[Finding] = []
    if IS_WINDOWS or not os.path.isdir("/opt"):
        return out
    for e in E.iter_dir("/opt"):
        if budget.expired():
            break
        if not e.is_dir(follow_symlinks=False):
            continue
        ts = E.tree_stats(e.path, deadline=time.monotonic() + 6)
        size = ts.size + ts.shared
        if size >= 100 * MB:
            out.append(Finding("opt", e.name, e.path, size,
                               advice="Installed outside the package manager — remove it with the vendor's "
                                      "uninstaller or by deleting the folder if you no longer use it.",
                               open_path=e.path, advice_key="opt_dir"))
    return sorted(out, key=lambda f: -f.size)[:15]


def _run(argv: List[str], timeout: int = 25) -> str:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "LC_ALL": "C"})
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def collect_heavy_packages(pm: str, top: int = 15) -> List[Finding]:
    sizes: List[Tuple[str, int]] = []
    if pm == "pacman":
        name = ""
        for line in _run(["pacman", "-Qi"], 60).splitlines():
            if line.startswith("Name"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("Installed Size") and name:
                m = re.search(r"([\d.,]+)\s*(KiB|MiB|GiB|B)", line)
                if m:
                    mult = {"B": 1, "KiB": 1024, "MiB": MB, "GiB": GB}[m.group(2)]
                    sizes.append((name, int(float(m.group(1).replace(",", ".")) * mult)))
    elif pm == "apt":
        for line in _run(["dpkg-query", "-W", "-f=${Package} ${Installed-Size}\n"], 30).splitlines():
            p = line.split()
            if len(p) == 2 and p[1].isdigit():
                sizes.append((p[0], int(p[1]) * 1024))
    elif pm in ("dnf", "zypper", "rpm-ostree"):
        for line in _run(["rpm", "-qa", "--qf", "%{NAME} %{SIZE}\n"], 30).splitlines():
            p = line.split()
            if len(p) == 2 and p[1].isdigit():
                sizes.append((p[0], int(p[1])))
    out = []
    for name, size in sorted(sizes, key=lambda x: -x[1])[:top]:
        if size < 100 * MB:
            break
        out.append(Finding("packages", name, "", size,
                           advice="Installed package — if you do not use it, remove it with your package manager "
                                  "(Uninstaller tab).", advice_key="pkg_remove"))
    return out


def collect_flatpak_snap(home: str) -> List[Finding]:
    out: List[Finding] = []
    if shutil.which("flatpak"):
        txt = _run(["flatpak", "list", "--app", "--columns=application,size"], 20)
        rows = []
        for line in txt.splitlines():
            p = re.split(r"\t|\s{2,}", line.strip())
            if len(p) >= 2:
                m = re.match(r"([\d.,]+)\s*([KMG]?B)", p[1])
                if m:
                    mult = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3}[m.group(2)]
                    rows.append((p[0], int(float(m.group(1).replace(",", ".")) * mult)))
        for app, size in sorted(rows, key=lambda x: -x[1])[:6]:
            if size >= 300 * MB:
                out.append(Finding("packages", f"flatpak: {app}", "", size,
                                   advice="`flatpak uninstall --delete-data <app>` removes the app and its data.",
                                   advice_key="flatpak_remove"))
    return out


def collect_containers() -> List[Finding]:
    out: List[Finding] = []
    for tool in ("docker", "podman"):
        if not shutil.which(tool):
            continue
        txt = _run([tool, "system", "df", "--format", "{{.Type}}\t{{.Size}}\t{{.Reclaimable}}"], 20)
        for line in txt.splitlines():
            p = line.split("\t")
            if len(p) == 3:
                m = re.match(r"([\d.,]+)\s*([KMGT]?B)", p[1])
                if m:
                    mult = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}[m.group(2)]
                    size = int(float(m.group(1).replace(",", ".")) * mult)
                    if size >= 200 * MB:
                        out.append(Finding("containers", f"{tool}: {p[0]}", "", size,
                                           advice=f"{p[2].strip()} reclaimable. Use Deep Clean → Docker/Podman "
                                                  f"to choose what to remove.",
                                           advice_key="container", advice_args={"reclaim": p[2].strip()}))
    return out


def collect_games(home: str, budget: _Budget) -> List[Finding]:
    out: List[Finding] = []
    roots = [os.path.join(home, ".local/share/Steam/steamapps/common"),
             os.path.join(home, ".steam/steam/steamapps/common"),
             os.path.join(home, ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common"),
             os.path.join(home, "Games"), os.path.join(home, ".wine"),
             os.path.join(home, ".local/share/lutris"), os.path.join(home, "Games/Heroic")]
    seen = set()
    for root in roots:
        real = os.path.realpath(root)
        if real in seen or not os.path.isdir(root):
            continue
        seen.add(real)
        children = [e for e in E.iter_dir(root) if e.is_dir(follow_symlinks=False)] if "common" in root or root.endswith("Games") else []
        if children:
            for e in children:
                if budget.expired():
                    break
                ts = E.tree_stats(e.path, deadline=time.monotonic() + 6)
                size = ts.size + ts.shared
                if size >= 2 * GB:
                    out.append(Finding("games", e.name, e.path, size, _age(ts.newest, time.time()),
                                       "Installed game — uninstall it from the launcher if you no longer play it.",
                                       e.path, advice_key="game_uninstall"))
        else:
            ts = E.tree_stats(root, deadline=time.monotonic() + 8)
            if ts.size + ts.shared >= 2 * GB:
                out.append(Finding("games", os.path.basename(root), root, ts.size + ts.shared, _age(ts.newest, time.time()),
                                   "Wine prefix / launcher data — delete a prefix only if no game uses it.", root,
                                   advice_key="wine_prefix"))
    return sorted(out, key=lambda f: -f.size)[:12]


def collect_windows(home: str, budget: _Budget) -> List[Finding]:
    out: List[Finding] = []
    sysroot = os.environ.get("SystemRoot", "C:\\Windows")
    drive = os.path.splitdrive(sysroot)[0] or "C:"
    wold = drive + "\\Windows.old"
    if os.path.isdir(wold):
        ts = E.tree_stats(wold, deadline=time.monotonic() + 20)
        out.append(Finding("windows", "Windows.old", wold, ts.size + ts.shared, _age(ts.newest, time.time()),
                           "Previous Windows installation. Remove it with Settings → System → Storage → "
                           "Temporary files (\"Previous Windows installation\"), not by hand.", wold,
                           advice_key="win_old"))
    for name, advice, akey in (("hiberfil.sys", "Hibernation file. `powercfg /h off` (admin) removes it if you never hibernate "
                                                "or use Fast Startup.", "hiberfil"),
                               ("pagefile.sys", "Virtual-memory file — resize it in System Properties → Advanced → "
                                               "Performance; do not delete it.", "pagefile"),
                               ("swapfile.sys", "UWP swap file — managed by Windows.", "swapfile")):
        p = os.path.join(drive + "\\", name)
        try:
            size = os.stat(p).st_size
        except OSError:
            size = 0
        if size >= 500 * MB:
            out.append(Finding("windows", name, p, size, advice=advice, open_path=drive + "\\", advice_key=akey))
    for p, advice, akey in ((os.path.join(drive + "\\", "ProgramData", "Package Cache"),
                             "Installer caches needed to repair/uninstall programs — leave unless you know which are orphaned.",
                             "pkg_cache"),
                            (os.path.join(drive + "\\", "Windows", "Installer"),
                             "Windows Installer patch cache — NEVER delete by hand (breaks uninstall/repair).",
                             "installer_cache")):
        if os.path.isdir(p) and not budget.expired():
            ts = E.tree_stats(p, deadline=time.monotonic() + 10)
            if ts.size + ts.shared >= 500 * MB:
                out.append(Finding("windows", os.path.basename(p), p, ts.size + ts.shared, advice=advice, open_path=p,
                                   advice_key=akey))
    return sorted(out, key=lambda f: -f.size)


def collect_wsl_docker_desktop(home: str, budget: _Budget) -> List[Finding]:
    out: List[Finding] = []
    local = os.environ.get("LOCALAPPDATA", "")
    cands: List[Tuple[str, str]] = []
    if local:
        pk = os.path.join(local, "Packages")
        for e in E.iter_dir(pk):
            vhd = os.path.join(e.path, "LocalState", "ext4.vhdx")
            if os.path.isfile(vhd):
                cands.append((vhd, "WSL distro disk"))
        for rel in ("Docker\\wsl\\data\\ext4.vhdx", "Docker\\wsl\\disk\\docker_data.vhdx"):
            vhd = os.path.join(local, rel)
            if os.path.isfile(vhd):
                cands.append((vhd, "Docker Desktop disk"))
    for vhd, label in cands:
        try:
            st = os.stat(vhd)
        except OSError:
            continue
        out.append(Finding("wsl", f"{label} — {os.path.basename(os.path.dirname(os.path.dirname(vhd)))}", vhd,
                           st.st_size, _age(st.st_mtime, time.time()),
                           "This virtual disk only grows. Free space inside the distro first, then shrink it: "
                           "`wsl --shutdown` and `wsl --manage <distro> --set-sparse true`, or Optimize-VHD.",
                           os.path.dirname(vhd), advice_key="wsl_disk"))
    return sorted(out, key=lambda f: -f.size)


def collect_btrfs_note() -> List[Finding]:
    note = E.snapshot_note("/") if not IS_WINDOWS else ""
    return [Finding("info", "Snapshots may hold deleted space", "", 0, advice=note)] if note else []


def report_to_text(rep: Report, home: str = "", cat_title=None, advice=None, title=None) -> str:
    """
    Báo cáo dạng chữ thuần (để dán vào issue / ghi chú). Chỉ đọc, không chạm đĩa.
    `cat_title(cat)`, `advice(finding)`, `title(finding)` là hàm dịch tùy chọn do tầng UI truyền vào.
    """
    lines = ["CyberClean — Disk Advisor report", "=" * 34]
    if rep.truncated:
        lines.append("(partial: the scan hit its time limit)")
    for cat, findings in rep.by_category().items():
        total = sum(f.size for f in findings)
        head = cat_title(cat) if cat_title else CATEGORY_TITLES.get(cat, cat)
        lines += ["", f"{head}" + (f" — {human(total)}" if cat != "info" and total else "")]
        for f in findings:
            path = f.path.replace(home, "~", 1) if home and f.path.startswith(home) else f.path
            age = f" · {f.age_days} d" if f.age_days is not None else ""
            size = f"{human(f.size):>9}" if f.size else " " * 9
            lines.append(f"  {size}  {title(f) if title else f.title}{age}")
            if path:
                lines.append(f"             {path}")
            text = advice(f) if advice else f.advice
            if text:
                lines.append(f"             → {text}")
    lines += ["", f"Accounted for: {human(rep.total)} · scanned in {rep.seconds:.0f}s"]
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════

def scan(home: str, pm: str = "", *, seconds: float = 60.0, stop: Optional[Callable[[], bool]] = None,
         progress: Optional[Callable[[str], None]] = None, big_min_mb: int = 500) -> Report:
    t0 = time.monotonic()
    now = time.time()
    budget = _Budget(seconds, stop)
    rep = Report()

    def step(msg: str) -> None:
        if progress:
            progress(msg)

    def safe(label: str, fn, *a):
        if budget.expired():
            return []
        step(label)
        try:
            return fn(*a)
        except Exception as e:                                   # một collector hỏng không làm hỏng báo cáo
            rep.notes.append(f"{label}: {e}")
            return []

    step("Walking your home folder")
    walk = walk_home(home, big_min=big_min_mb * MB, budget=budget.sub(0.55), want_artifacts=True)
    big_findings = collect_big_files(walk, now)
    rep.findings += big_findings
    rep.findings += safe("Old project build folders", collect_project_artifacts, walk, now, budget.sub(0.5))
    already = {f.path for f in big_findings}
    rep.findings += safe("Downloads", lambda: collect_downloads(home, now, budget, exclude=already))
    if IS_WINDOWS:
        rep.findings += safe("Windows leftovers", collect_windows, home, budget)
        rep.findings += safe("WSL / Docker Desktop disks", collect_wsl_docker_desktop, home, budget)
    else:
        rep.findings += safe("/opt", collect_opt, budget)
        rep.findings += safe("Games", collect_games, home, budget)
        rep.findings += safe("Installed packages", collect_heavy_packages, pm)
        rep.findings += safe("Flatpak apps", collect_flatpak_snap, home)
        rep.findings += safe("Containers", collect_containers)
    rep.findings += collect_btrfs_note()
    rep.truncated = budget.hit
    if rep.truncated:
        rep.notes.append("The scan hit its time limit — results are partial (largest items first).")
    rep.seconds = time.monotonic() - t0
    return rep
