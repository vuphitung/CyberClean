"""
CyberClean — Cleaning Engine
════════════════════════════════════════════════════════════════
Mọi thao tác xóa file (Linux + Windows) đi qua module này theo đúng 3 bước:

    1. PLAN     quét một lần → danh sách PlanItem cụ thể (đường dẫn, kích thước
                thật, thời điểm sửa gần nhất, inode...). Không đổi gì trên đĩa.
    2. PREVIEW  người dùng / dry-run xem chính danh sách đó.
    3. EXECUTE  chạy đúng danh sách đó, nhưng KIỂM TRA LẠI từng mục ngay trước khi
                xóa (inode đổi? vừa bị sửa? app vừa mở lại? file đang mở?) —
                nên dry-run và chạy thật khớp nhau, và không bao giờ xóa nhầm thứ
                đã thay đổi giữa hai bước.

Các "guard" thay cho deny-list theo tên:
    • tuổi        — chỉ xóa thứ đã không đụng tới ≥ N ngày (+ luôn bỏ qua thứ vừa
                    sửa trong 10 phút gần đây)
    • tiến trình  — app sở hữu cache phải đã tắt (psutil)
    • file mở     — thư mục/file đang được tiến trình nào đó mở hoặc làm cwd
    • symlink     — không bao giờ đi theo symlink / junction / reparse point
    • mount       — không băng qua điểm mount khác (st_dev)
    • socket/FIFO — cây thư mục chứa socket/FIFO/device = runtime IPC đang sống
    • chủ sở hữu  — không đụng file của user khác
    • hardlink    — chỉ tính dung lượng khi MỌI link nằm trong phần sẽ xóa

Đo dung lượng thật bằng shutil.disk_usage trước/sau (FreeSpaceMeter) và cảnh báo
khi Btrfs/ZFS có snapshot (xóa xong chưa chắc giải phóng ngay).
"""
from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

IS_WINDOWS = sys.platform == "win32"
RECENT_GUARD_SEC = 600          # không bao giờ đụng thứ vừa sửa trong 10 phút
_REPARSE_POINT = 0x400          # FILE_ATTRIBUTE_REPARSE_POINT (junction, OneDrive placeholder...)
DAY = 86400.0


# ══════════════════════════════════════════════════════════════
# Low-level helpers
# ══════════════════════════════════════════════════════════════

def is_link_like(st) -> bool:
    """symlink hoặc reparse point (junction/mount point trên NTFS)."""
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def is_special(mode: int) -> bool:
    return (stat.S_ISSOCK(mode) or stat.S_ISFIFO(mode)
            or stat.S_ISBLK(mode) or stat.S_ISCHR(mode))


def _stamp(st, basis: str) -> float:
    """Thời điểm 'dùng gần nhất' của một file."""
    if basis == "atime":
        return max(st.st_mtime, st.st_atime)
    return st.st_mtime


_OWNER_UID: Optional[int] = None


def set_owner_uid(uid: Optional[int]) -> None:
    """Chạy với euid=0 qua sudo: chỉ đụng file thuộc user THẬT, không phải của root."""
    global _OWNER_UID
    _OWNER_UID = uid


def _euid() -> Optional[int]:
    if _OWNER_UID is not None:
        return _OWNER_UID
    return os.geteuid() if hasattr(os, "geteuid") else None


def fmt_age(newest: float, now: Optional[float] = None) -> str:
    if not newest:
        return "—"
    d = ((now or time.time()) - newest) / DAY
    if d < 1:
        return "<1d"
    if d < 60:
        return f"{int(d)}d"
    if d < 730:
        return f"{int(d // 30)}mo"
    return f"{int(d // 365)}y"


# ══════════════════════════════════════════════════════════════
# Tree statistics
# ══════════════════════════════════════════════════════════════

@dataclass
class TreeStats:
    size: int = 0                 # byte sẽ được giải phóng nếu xóa cây này
    shared: int = 0               # byte của file hardlink còn link ngoài cây → KHÔNG giải phóng
    files: int = 0
    newest: float = 0.0           # mốc sửa/dùng mới nhất trong cây (cả thư mục)
    has_special: bool = False     # socket / FIFO / device bên trong
    crosses_mount: bool = False   # có thư mục con nằm trên thiết bị khác
    foreign_owner: bool = False   # có file thuộc user khác
    errors: int = 0
    exists: bool = True
    truncated: bool = False       # dừng sớm vì deadline


def tree_stats(path, basis: str = "mtime", *, deadline: Optional[float] = None) -> TreeStats:
    """
    Quét một file / cây thư mục bằng os.scandir, KHÔNG đi theo symlink.
    Hardlink (st_nlink>1) được gom theo (dev, ino): chỉ tính là 'giải phóng' khi
    mọi link của inode đó đều nằm trong cây.
    """
    ts = TreeStats()
    p = os.fspath(path)
    try:
        st0 = os.lstat(p)
    except FileNotFoundError:
        ts.exists = False
        return ts
    except OSError:
        ts.errors += 1
        return ts

    me = _euid()
    if is_link_like(st0):
        ts.newest = st0.st_mtime
        return ts
    if not stat.S_ISDIR(st0.st_mode):
        ts.newest = _stamp(st0, basis)
        if is_special(st0.st_mode):
            ts.has_special = True
        else:
            ts.files = 1
            if st0.st_nlink > 1:
                ts.shared = st0.st_size
            else:
                ts.size = st0.st_size
        if me is not None and st0.st_uid != me:
            ts.foreign_owner = True
        return ts

    dev = st0.st_dev
    ts.newest = st0.st_mtime
    if me is not None and st0.st_uid != me:
        ts.foreign_owner = True
    stack = [p]
    inodes: Dict[Tuple[int, int], List[int]] = {}   # (dev, ino) → [size, seen, nlink]
    n = 0
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            ts.errors += 1
            continue
        with it:
            for e in it:
                n += 1
                if deadline and (n & 0x3FF) == 0 and time.monotonic() > deadline:
                    ts.truncated = True
                    stack.clear()
                    break
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    ts.errors += 1
                    continue
                if is_link_like(st):
                    continue
                mode = st.st_mode
                if stat.S_ISDIR(mode):
                    if st.st_dev != dev:
                        ts.crosses_mount = True
                        continue
                    if st.st_mtime > ts.newest:
                        ts.newest = st.st_mtime
                    if me is not None and st.st_uid != me:
                        ts.foreign_owner = True
                    stack.append(e.path)
                elif is_special(mode):
                    ts.has_special = True
                else:
                    ts.files += 1
                    s = _stamp(st, basis)
                    if s > ts.newest:
                        ts.newest = s
                    if me is not None and st.st_uid != me:
                        ts.foreign_owner = True
                    if st.st_nlink > 1:
                        rec = inodes.setdefault((st.st_dev, st.st_ino), [st.st_size, 0, st.st_nlink])
                        rec[1] += 1
                    else:
                        ts.size += st.st_size
    for size, seen, nlink in inodes.values():
        if seen >= nlink:
            ts.size += size
        else:
            ts.shared += size
    return ts


# ══════════════════════════════════════════════════════════════
# Plan data model
# ══════════════════════════════════════════════════════════════

@dataclass
class PlanItem:
    path: str
    kind: str = "dir"             # 'file' | 'dir' | 'files' (danh sách file lẻ trong meta['files'])
    size: int = 0
    shared: int = 0
    files: int = 0
    newest: float = 0.0
    dev: int = 0
    ino: int = 0
    mtime_ns: int = 0
    ctime_ns: int = 0          # inode có thể bị tái sử dụng → ctime phân biệt 'cùng tên, đã thay mới'
    label: str = ""
    group: str = ""               # rule / provider id
    note: str = ""
    risk: str = "low"             # low | medium | high
    blocked: str = ""             # khác rỗng → không xóa được lúc này (lý do)
    keep_root: bool = False       # chỉ xóa phần BÊN TRONG, giữ lại thư mục gốc
    basis: str = "mtime"
    closed: Tuple[str, ...] = ()  # tiến trình phải tắt (kiểm tra lại lúc xóa)
    meta: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        # id ổn định theo đường dẫn (không dùng cho bảo mật) — blake2b, 12 ký tự hex
        return hashlib.blake2b(self.path.encode("utf-8", "surrogateescape"), digest_size=6).hexdigest()

    @property
    def display(self) -> str:
        return self.label or self.path


@dataclass
class Plan:
    target_id: str
    items: List[PlanItem] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)   # (path, lý do) — minh bạch
    notes: List[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)

    @property
    def deletable(self) -> List[PlanItem]:
        return [i for i in self.items if not i.blocked]

    @property
    def total_bytes(self) -> int:
        return sum(i.size for i in self.deletable)

    @property
    def total_files(self) -> int:
        return sum(i.files for i in self.deletable)

    def extend(self, other: "Plan") -> None:
        self.items += other.items
        self.skipped += other.skipped
        for n in other.notes:
            if n not in self.notes:
                self.notes.append(n)


@dataclass
class Policy:
    """Điều kiện để một mục được phép vào plan."""
    min_age_sec: float = 0.0
    recent_sec: float = RECENT_GUARD_SEC
    basis: str = "mtime"
    require_owner: bool = True
    allow_special: bool = False
    allow_cross_mount: bool = False
    closed: Tuple[str, ...] = ()


# ══════════════════════════════════════════════════════════════
# Guards (process / open files / filesystem)
# ══════════════════════════════════════════════════════════════

def _norm_name(n: str) -> str:
    n = (n or "").lower()
    return n[:-4] if n.endswith(".exe") else n


class Guards:
    """
    Snapshot tiến trình + chỉ mục file đang mở. Snapshot được dùng chung giữa các
    Guards trong `max_age` giây (nhiều target quét song song không phải quét lại
    /proc N lần); khi THỰC THI dùng max_age=0 để luôn có dữ liệu mới nhất.
    """
    _lock = threading.Lock()
    _shared: Optional[Tuple[float, Set[str], Set[str], Set[str], Set[str]]] = None   # (time, procs, user_data_dirs, open_anc, sandbox_args)

    def __init__(self, *, max_age: float = 5.0, open_files_deadline: float = 4.0):
        self._max_age = max_age
        self._deadline = open_files_deadline
        self._snap: Optional[Tuple[Set[str], Set[str], Set[str]]] = None
        self._open_anc: Optional[Set[str]] = None

    # ── tiến trình ───────────────────────────────────────────
    @staticmethod
    def psutil_available() -> bool:
        try:
            import psutil  # noqa: F401
            return True
        except ImportError:                                  # pragma: no cover
            return False

    @staticmethod
    def _load_procs() -> Tuple[Set[str], Set[str], Set[str]]:
        names: Set[str] = set()
        udd: Set[str] = set()
        sandbox: Set[str] = set()
        try:
            import psutil
        except ImportError:                                  # pragma: no cover
            return names, udd, sandbox
        for p in psutil.process_iter(["name", "exe", "cmdline"]):
            try:
                info = p.info
                if info.get("name"):
                    names.add(_norm_name(info["name"]))
                if info.get("exe"):
                    names.add(_norm_name(os.path.basename(info["exe"])))
                cl = info.get("cmdline") or []
                if cl:
                    names.add(_norm_name(os.path.basename(cl[0])))
                for a in cl:
                    if a.startswith("--user-data-dir="):
                        udd.add(_norm_path(a.split("=", 1)[1]))
                if _norm_name(info.get("name") or "") in ("bwrap", "flatpak-bwrap"):
                    sandbox.update(a for a in cl if a.startswith("/"))   # --bind <host> <dest>
            except Exception:
                continue
        return names, udd, sandbox

    def _procs_snapshot(self) -> Tuple[Set[str], Set[str], Set[str]]:
        if self._snap is not None:
            return self._snap
        with Guards._lock:
            sh = Guards._shared
            if sh and self._max_age > 0 and (time.monotonic() - sh[0]) <= self._max_age:
                self._snap = (sh[1], sh[2], sh[4])
                return self._snap
            names, udd, sandbox = self._load_procs()
            Guards._shared = (time.monotonic(), names, udd, set(), sandbox)
            self._snap = (names, udd, sandbox)
            return self._snap

    def processes(self) -> Set[str]:
        return self._procs_snapshot()[0]

    def running(self, names: Iterable[str]) -> str:
        """
        Trả về tên đầu tiên đang chạy ('' nếu không có).
        Không có psutil = không biết app đã tắt chưa → coi như ĐANG CHẠY (fail closed): thà bỏ qua một lần
        dọn còn hơn xóa cache của app đang mở.
        """
        names = list(names or ())
        if names and not self.psutil_available():
            return names[0] + " (cannot verify: psutil is not installed)"
        procs = self.processes()
        for n in names:
            if _norm_name(n) in procs:
                return n
        return ""

    def sandboxed(self, path: str) -> bool:
        """Flatpak đang chạy app có bind-mount thư mục này (bwrap --bind <path> ...)?"""
        p = os.fspath(path)
        for arg in self._procs_snapshot()[2]:
            if p == arg or p.startswith(arg.rstrip("/") + "/") or arg.startswith(p.rstrip("/") + "/"):
                return True
        return False

    def user_data_dir_in_use(self, path: str) -> bool:
        """Có tiến trình Chromium/Electron nào chạy với --user-data-dir=<path>?"""
        return _norm_path(path) in self._procs_snapshot()[1]

    # ── file đang mở ─────────────────────────────────────────
    def _load_open(self) -> Set[str]:
        anc: Set[str] = set()
        try:
            import psutil
        except ImportError:                                  # pragma: no cover
            return anc
        end = time.monotonic() + self._deadline

        def add(path: str):
            if not path or not os.path.isabs(path):
                return
            if path.endswith(" (deleted)"):
                path = path[:-10]
            while path and path not in anc:
                anc.add(path)
                parent = os.path.dirname(path)
                if parent == path:
                    break
                path = parent

        for p in psutil.process_iter():
            if time.monotonic() > end:
                break
            try:
                for f in p.open_files():
                    add(f.path)
                add(p.cwd())
            except Exception:
                continue
        return anc

    def in_use(self, path: str) -> bool:
        """path (hoặc bất kỳ thứ gì bên trong nó) đang được tiến trình nào đó mở / làm cwd."""
        if IS_WINDOWS:
            return False            # psutil.open_files() trên Windows chậm/treo; file đang mở tự chặn việc xóa
        if self._open_anc is None:
            with Guards._lock:
                sh = Guards._shared
                if sh and self._max_age > 0 and sh[3] and (time.monotonic() - sh[0]) <= self._max_age:
                    self._open_anc = sh[3]
                else:
                    anc = self._load_open()
                    if sh:
                        Guards._shared = (sh[0], sh[1], sh[2], anc, sh[4])
                    self._open_anc = anc
        return os.fspath(path) in self._open_anc


def _norm_path(p: str) -> str:
    p = os.path.normpath(p)
    return p.lower() if IS_WINDOWS else p


# ── filesystem info ─────────────────────────────────────────

_MOUNTS_CACHE: Optional[List[Tuple[str, str]]] = None


def _unescape_mount(s: str) -> str:
    return s.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def _read_mounts() -> List[Tuple[str, str]]:
    global _MOUNTS_CACHE
    if _MOUNTS_CACHE is not None:
        return _MOUNTS_CACHE
    out: List[Tuple[str, str]] = []
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                left, sep, right = line.partition(" - ")
                if not sep:
                    continue
                lp, rp = left.split(), right.split()
                if len(lp) >= 5 and rp:
                    out.append((_unescape_mount(lp[4]), rp[0]))
    except OSError:
        pass
    _MOUNTS_CACHE = out
    return out


def fs_type(path) -> str:
    """Loại filesystem chứa path ('ext4', 'btrfs', 'tmpfs'...). '' nếu không biết (Windows...)."""
    if IS_WINDOWS:
        return ""
    try:
        real = os.path.realpath(os.fspath(path))
    except OSError:
        return ""
    best, typ = "", ""
    for mp, ft in _read_mounts():
        if (real == mp or real.startswith(mp.rstrip("/") + "/") or mp == "/") and len(mp) >= len(best):
            best, typ = mp, ft
    return typ


def is_ram_backed(path) -> bool:
    return fs_type(path) in ("tmpfs", "ramfs")


def snapshot_note(path) -> str:
    """Cảnh báo nếu filesystem có thể giữ lại dữ liệu đã xóa (snapshot)."""
    ft = fs_type(path)
    if ft == "btrfs":
        snaps = any(os.path.exists(p) for p in ("/.snapshots", "/timeshift-btrfs", "/run/timeshift"))
        extra = " (snapper/Timeshift snapshots detected)" if snaps else ""
        return ("Btrfs" + extra + ": space held by snapshots is not freed until those snapshots are "
                "deleted — free space may not increase right away.")
    if ft == "zfs":
        return ("ZFS: space held by snapshots is not freed until those snapshots are destroyed — "
                "free space may not increase right away.")
    return ""


class FreeSpaceMeter:
    """Đo dung lượng trống thật trước/sau trên các filesystem liên quan."""

    def __init__(self, paths: Iterable[str]):
        self._anchors: Dict[int, str] = {}
        for p in paths:
            q = os.fspath(p)
            while q and not os.path.exists(q):
                nq = os.path.dirname(q)
                if nq == q:
                    break
                q = nq
            try:
                self._anchors.setdefault(os.stat(q).st_dev, q)
            except OSError:
                continue
        self._before: Dict[int, int] = {}

    def _free(self) -> Dict[int, int]:
        out = {}
        for dev, p in self._anchors.items():
            try:
                out[dev] = shutil.disk_usage(p).free
            except OSError:
                pass
        return out

    def begin(self) -> None:
        self._before = self._free()

    def end(self) -> Optional[int]:
        after = self._free()
        common = set(self._before) & set(after)
        if not common:
            return None
        return sum(after[d] - self._before[d] for d in common)


# ══════════════════════════════════════════════════════════════
# Plan building
# ══════════════════════════════════════════════════════════════

def evaluate(ts: TreeStats, policy: Policy, *, now: float, guards: Optional[Guards] = None,
             path: str = "") -> str:
    """Trả về lý do KHÔNG xóa ('' nếu đạt mọi guard)."""
    if not ts.exists:
        return "gone"
    if ts.has_special and not policy.allow_special:
        return "contains a socket/FIFO (live runtime state)"
    if ts.crosses_mount and not policy.allow_cross_mount:
        return "crosses a mount point"
    if ts.foreign_owner and policy.require_owner:
        return "owned by another user"
    if ts.newest and (now - ts.newest) < policy.recent_sec:
        return "modified in the last 10 minutes"
    if policy.min_age_sec and ts.newest and (now - ts.newest) < policy.min_age_sec:
        days = (now - ts.newest) / DAY
        return f"used {days:.1f} days ago (< {policy.min_age_sec / DAY:g} d)"
    if policy.closed and guards is not None:
        hit = guards.running(policy.closed)
        if hit:
            return f"{hit} is running — close it first"
    if guards is not None and path and guards.in_use(path):
        return "in use by a running process"
    return ""


def make_item(path, policy: Policy, *, now: Optional[float] = None, guards: Optional[Guards] = None,
              label: str = "", group: str = "", note: str = "", risk: str = "low",
              keep_root: bool = False, deadline: Optional[float] = None,
              ts: Optional[TreeStats] = None) -> Tuple[Optional[PlanItem], str]:
    """
    lstat + tree_stats + guard → (PlanItem, '') nếu đủ điều kiện,
    (None, lý do) nếu bị bỏ qua, (PlanItem(blocked=...), lý do) cho mục 'bị chặn có điều kiện'
    (ví dụ app đang chạy) — để UI vẫn hiển thị và nói rõ lý do.
    """
    now = now or time.time()
    p = os.fspath(path)
    try:
        st = os.lstat(p)
    except OSError:
        return None, "gone"
    if is_link_like(st):
        return None, "symlink / reparse point (never followed)"
    ts = ts or tree_stats(p, policy.basis, deadline=deadline)
    why = evaluate(ts, policy, now=now, guards=guards, path=p)
    if why == "gone":
        return None, why
    kind = "dir" if stat.S_ISDIR(st.st_mode) else "file"
    item = PlanItem(path=p, kind=kind, size=ts.size, shared=ts.shared, files=ts.files,
                    newest=ts.newest, dev=st.st_dev, ino=st.st_ino, mtime_ns=st.st_mtime_ns,
                    ctime_ns=st.st_ctime_ns,
                    label=label or os.path.basename(p) or p, group=group, note=note, risk=risk,
                    keep_root=keep_root, basis=policy.basis, closed=tuple(policy.closed))
    if why:
        # app đang chạy / file đang mở → hiển thị nhưng chặn; còn lại → bỏ qua hẳn
        if "running" in why or "in use" in why:
            item.blocked = why
            return item, why
        return None, why
    return item, ""


def make_files_item(root, files: List[Tuple[str, int, int, int, int]], *, label: str, group: str,
                    note: str = "", basis: str = "atime", risk: str = "low") -> PlanItem:
    """Mục dạng 'danh sách file lẻ' (thumbnails, pip...) — files = [(path, mtime_ns, ino, size, ctime_ns)]."""
    total = sum(f[3] for f in files)
    newest = 0.0
    return PlanItem(path=os.fspath(root), kind="files", size=total, files=len(files),
                    newest=newest, label=label, group=group, note=note, basis=basis, risk=risk,
                    meta={"files": files, "root": os.fspath(root)})


def plan_old_files(root, policy: Policy, *, guards: Optional[Guards] = None, now: Optional[float] = None,
                   label: str = "", group: str = "", note: str = "",
                   keep: Sequence[str] = ()) -> Optional[PlanItem]:
    """Quét đệ quy, gom các FILE đã quá tuổi dưới root thành MỘT mục 'files'."""
    now = now or time.time()
    r = os.fspath(root)
    try:
        st0 = os.lstat(r)
    except OSError:
        return None
    if not stat.S_ISDIR(st0.st_mode) or is_link_like(st0):
        return None
    dev = st0.st_dev
    files: List[Tuple[str, int, int, int]] = []
    shared_skipped = 0
    stack = [r]
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_link_like(st):
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if st.st_dev == dev:
                        stack.append(e.path)
                    continue
                if is_special(st.st_mode):
                    continue
                if cur == r and e.name in keep:
                    continue
                if st.st_nlink > 1:
                    shared_skipped += 1
                    continue
                s = _stamp(st, policy.basis)
                age = now - s
                if age < policy.recent_sec or (policy.min_age_sec and age < policy.min_age_sec):
                    continue
                files.append((e.path, st.st_mtime_ns, st.st_ino, st.st_size, st.st_ctime_ns))
    if not files:
        return None
    item = make_files_item(r, files, label=label or os.path.basename(r), group=group, note=note,
                           basis=policy.basis)
    item.dev, item.ino = st0.st_dev, 0
    item.newest = now - policy.min_age_sec if policy.min_age_sec else now
    item.meta["keep"] = tuple(keep)
    return item


# ══════════════════════════════════════════════════════════════
# Execution
# ══════════════════════════════════════════════════════════════

@dataclass
class Outcome:
    item: PlanItem
    status: str                   # 'removed' | 'partial' | 'skipped' | 'failed' | 'gone'
    freed: int = 0
    removed: int = 0              # số file đã xóa
    reason: str = ""


def _chmod_writable(path: str) -> None:
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode):
            return
        os.chmod(path, (st.st_mode | stat.S_IWRITE | (stat.S_IRUSR | stat.S_IXUSR if stat.S_ISDIR(st.st_mode) else 0)))
    except OSError:
        pass


def _rmtree_handler(func, path, exc):
    """Xử lý thư mục/file read-only (Go module cache 0555, thuộc tính read-only của Windows)."""
    err = exc[1] if isinstance(exc, tuple) else exc
    if isinstance(err, FileNotFoundError):
        return
    if isinstance(err, PermissionError) or getattr(err, "errno", None) in (errno.EACCES, errno.EPERM):
        _chmod_writable(os.path.dirname(path))
        _chmod_writable(path)
        try:
            func(path)
        except OSError:
            pass


def _rmtree(path: str) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_rmtree_handler)
    else:                                                    # pragma: no cover
        shutil.rmtree(path, onerror=_rmtree_handler)


def _make_tree_writable(path: str) -> None:
    for dirpath, dirnames, _ in os.walk(path, topdown=True, followlinks=False):
        _chmod_writable(dirpath)


def remove_path(path: str) -> None:
    """Xóa file hoặc cây thư mục, không theo symlink; tự xử lý read-only."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(st.st_mode) and not is_link_like(st):
        _rmtree(path)
        if os.path.lexists(path):
            _make_tree_writable(path)
            _rmtree(path)
    else:
        try:
            os.unlink(path)
        except PermissionError:
            _chmod_writable(path)
            os.unlink(path)


def _prune_empty_dirs(root: str, keep_root: bool = True) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        if keep_root and dirpath == root:
            continue
        try:
            os.rmdir(dirpath)       # chỉ thành công nếu rỗng
        except OSError:
            pass


def execute_item(item: PlanItem, guards: Optional[Guards] = None, *, now: Optional[float] = None,
                 dry: bool = False) -> Outcome:
    """Kiểm tra lại rồi xóa MỘT mục của plan."""
    now = now or time.time()
    if item.blocked:
        return Outcome(item, "skipped", reason=item.blocked)
    if item.kind == "files":
        return _execute_files(item, guards, now, dry)

    p = item.path
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return Outcome(item, "gone", reason="already gone")
    except OSError as e:
        return Outcome(item, "failed", reason=str(e))
    if (st.st_dev, st.st_ino) != (item.dev, item.ino):
        return Outcome(item, "skipped", reason="replaced since the scan")
    if item.ctime_ns and st.st_ctime_ns != item.ctime_ns:
        # inode có thể được tái sử dụng cho một thư mục mới cùng tên; ctime thì không
        return Outcome(item, "skipped", reason="changed since the scan")
    if is_link_like(st):
        return Outcome(item, "skipped", reason="is a symlink / reparse point")
    if item.closed and guards is not None:
        hit = guards.running(item.closed)
        if hit:
            return Outcome(item, "skipped", reason=f"{hit} is running — close it first")

    if item.kind == "file":
        if is_special(st.st_mode):
            return Outcome(item, "skipped", reason="socket/FIFO")
        if st.st_mtime_ns != item.mtime_ns:
            return Outcome(item, "skipped", reason="modified since the scan")
        if now - st.st_mtime < RECENT_GUARD_SEC:
            return Outcome(item, "skipped", reason="modified in the last 10 minutes")
        if guards is not None and guards.in_use(p):
            return Outcome(item, "skipped", reason="in use by a running process")
        freed = st.st_size if st.st_nlink <= 1 else 0
        if dry:
            return Outcome(item, "removed", freed, 1)
        try:
            remove_path(p)
        except PermissionError:
            return Outcome(item, "skipped", reason="locked / in use (cannot be deleted right now)")
        except OSError as e:
            return Outcome(item, "failed", reason=str(e))
        return Outcome(item, "removed", freed, 1)

    # ── thư mục ──
    cur = tree_stats(p, item.basis)
    if not cur.exists:
        return Outcome(item, "gone", reason="already gone")
    if cur.has_special:
        return Outcome(item, "skipped", reason="contains a socket/FIFO (live runtime state)")
    if cur.crosses_mount:
        return Outcome(item, "skipped", reason="crosses a mount point")
    if cur.foreign_owner:
        return Outcome(item, "skipped", reason="owned by another user")
    if cur.newest > item.newest + 1.0 or (cur.newest and now - cur.newest < RECENT_GUARD_SEC):
        return Outcome(item, "skipped", reason="modified since the scan")
    if guards is not None and guards.in_use(p):
        return Outcome(item, "skipped", reason="in use by a running process")
    keep_names = tuple(item.meta.get("keep", ())) if item.keep_root else ()
    kept = 0
    if keep_names:
        for e in iter_dir(p):
            if e.name in keep_names:
                kept += tree_stats(e.path, item.basis).size
    expected = max(0, cur.size - kept)
    if dry:
        return Outcome(item, "removed", expected, cur.files)

    errors = ""
    try:
        if item.keep_root:
            for e in iter_dir(p):
                if e.name in keep_names:
                    continue
                remove_path(e.path)
        else:
            remove_path(p)
    except OSError as e:
        errors = str(e)

    if item.keep_root:
        leftover = sum(tree_stats(e.path, item.basis).size for e in iter_dir(p) if e.name not in keep_names)
        freed, done = max(0, expected - leftover), leftover == 0
    else:
        left = tree_stats(p, item.basis) if os.path.lexists(p) else TreeStats(exists=False)
        freed = max(0, cur.size - (left.size if left.exists else 0))
        done = not left.exists
    if done:
        return Outcome(item, "removed", freed, cur.files)
    return Outcome(item, "partial", freed, cur.files, reason=errors or "some files could not be removed")


def _execute_files(item: PlanItem, guards: Optional[Guards], now: float, dry: bool) -> Outcome:
    files = item.meta.get("files", [])
    freed = removed = skipped = 0
    for path, mtime_ns, ino, size, ctime_ns in files:
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if (st.st_ino != ino or st.st_mtime_ns != mtime_ns or st.st_ctime_ns != ctime_ns
                or is_link_like(st)
                or is_special(st.st_mode) or st.st_nlink > 1
                or now - st.st_mtime < RECENT_GUARD_SEC):
            skipped += 1
            continue
        if guards is not None and guards.in_use(path):
            skipped += 1
            continue
        if not dry:
            try:
                remove_path(path)
            except OSError:
                skipped += 1
                continue
        freed += size
        removed += 1
    if not dry and removed:
        _prune_empty_dirs(item.meta.get("root", item.path), keep_root=True)
    if removed == 0 and skipped:
        return Outcome(item, "skipped", reason=f"{skipped} files changed or in use")
    status = "removed" if skipped == 0 else "partial"
    return Outcome(item, status, freed, removed, reason=f"{skipped} skipped" if skipped else "")


@dataclass
class ExecResult:
    freed: int = 0
    removed: int = 0
    outcomes: List[Outcome] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    measured: Optional[int] = None          # chênh lệch dung lượng trống đo thật
    notes: List[str] = field(default_factory=list)


def execute_plan(plan_items: Sequence[PlanItem], *, dry: bool = False, guards: Optional[Guards] = None,
                 progress: Optional[Callable[[int, int, PlanItem], None]] = None,
                 stop: Optional[Callable[[], bool]] = None) -> ExecResult:
    guards = guards or Guards(max_age=0)
    res = ExecResult()
    meter = None
    if not dry:
        meter = FreeSpaceMeter([i.path for i in plan_items])
        meter.begin()
    now = time.time()
    total = len(plan_items)
    for n, item in enumerate(plan_items, 1):
        if stop and stop():
            res.notes.append("Interrupted")
            break
        out = execute_item(item, guards, now=now, dry=dry)
        res.outcomes.append(out)
        if out.status in ("removed", "partial"):
            res.freed += out.freed
            res.removed += out.removed
        if out.status in ("skipped", "partial") and out.reason:
            res.skipped.append((item.path, out.reason))
        if out.status == "failed":
            res.errors.append(f"{item.path}: {out.reason}")
        if progress:
            progress(n, total, item)
    if meter is not None:
        res.measured = meter.end()
        for p in {i.path for i in plan_items[:1]}:
            note = snapshot_note(p)
            if note:
                res.notes.append(note)
    return res


# ══════════════════════════════════════════════════════════════
# Helpers for providers
# ══════════════════════════════════════════════════════════════

def chromium_profile_in_use(user_data_dir: str) -> bool:
    """
    Linux: Chromium/Electron tạo symlink 'SingletonLock' → 'host-pid' khi đang chạy.
    Lock còn nhưng pid đã chết (crash) = lock cũ → không tính là đang chạy.
    """
    lock = os.path.join(user_data_dir, "SingletonLock")
    try:
        target = os.readlink(lock)
    except OSError:
        return False
    try:
        pid = int(target.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return True            # không đọc được pid → coi như đang chạy (an toàn)
    try:
        import psutil
        if not psutil.pid_exists(pid):
            return False
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:
        return True


def iter_dir(path) -> List[os.DirEntry]:
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        return []
