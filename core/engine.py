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
import struct
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


def is_elf_core_file(path: str) -> bool:
    """
    Xác minh file thực sự là ELF core dump (ET_CORE, e_type == 4).
    - Chỉ chấp nhận file thường (stat.S_ISREG), KHÔNG theo symlink (O_NOFOLLOW),
      KHÔNG chấp nhận thư mục.
    - Kiểm tra header ELF:
      • magic 4 byte: b'\\x7fELF'
      • ei_class (byte 4) in (1, 2)  [32-bit hoặc 64-bit]
      • ei_data  (byte 5) in (1, 2)  [little-endian hoặc big-endian]
      • ei_version (byte 6) == 1
      • e_type   (bytes 16..18) == 4 (ET_CORE)
    """
    p = os.fspath(path)
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if is_link_like(st) or not stat.S_ISREG(st.st_mode) or st.st_size < 52:
        return False
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = -1
    try:
        fd = os.open(p, flags)
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino) or not stat.S_ISREG(fst.st_mode):
            return False
        hdr = os.read(fd, 20)
    except OSError:
        return False
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
    if len(hdr) < 18 or hdr[:4] != b"\x7fELF":
        return False
    ei_class = hdr[4]
    ei_data = hdr[5]
    ei_version = hdr[6]
    if ei_class not in (1, 2) or ei_data not in (1, 2) or ei_version != 1:
        return False
    fmt = "<H" if ei_data == 1 else ">H"
    e_type = struct.unpack(fmt, hdr[16:18])[0]
    return e_type == 4


def _norm_cmp_path(p: str) -> str:
    n = os.path.normpath(p)
    return n.lower() if IS_WINDOWS else n


def check_ancestor_chain(path: str, allowed_root: Optional[str] = None) -> Tuple[str, List[Tuple[str, int, int]]]:
    """
    Kiểm tra chuỗi thư mục cha của `path` (chống symlink/junction ở thư mục cha
    vượt ra ngoài phạm vi cho phép và chụp lại (path, st_dev, st_ino) để xác minh
    lại trước khi xóa).
    Trả về (reason, chain):
      - reason == '' nếu an toàn, kèm danh sách [(dir_path, dev, ino), ...] từ gốc xuống cha trực tiếp.
      - reason != '' nếu có thành phần cha là symlink/reparse point hoặc thoát khỏi allowed_root.
    """
    p = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(p)
    root_abs = os.path.abspath(os.fspath(allowed_root)) if allowed_root else None

    if root_abs is not None:
        p_cmp = _norm_cmp_path(p)
        r_cmp = _norm_cmp_path(root_abs).rstrip("/\\")
        sep = "\\" if IS_WINDOWS else "/"
        if p_cmp != r_cmp and not p_cmp.startswith(r_cmp + sep):
            return f"escapes allowed boundary ({allowed_root})", []
        try:
            real_parent = os.path.realpath(parent)
            real_root = os.path.realpath(root_abs)
            rp_cmp = _norm_cmp_path(real_parent)
            rr_cmp = _norm_cmp_path(real_root).rstrip("/\\")
            if rp_cmp != rr_cmp and not rp_cmp.startswith(rr_cmp + sep):
                return f"parent resolves outside allowed boundary ({allowed_root})", []
        except OSError as e:
            return f"cannot resolve parent path: {e}", []

    # Thu thập các thư mục cha cần kiểm tra:
    # - Nếu có allowed_root: kiểm tra mọi thành phần từ allowed_root tới parent (và kiểm tra
    #   không có symlink trên allowed_root nếu có thể).
    # - Nếu không có allowed_root: kiểm tra từ gốc filesystem tới parent.
    parts_to_check: List[str] = []
    cur = parent
    stop_cmp = _norm_cmp_path(root_abs) if root_abs else None
    while True:
        parts_to_check.append(cur)
        if stop_cmp is not None and _norm_cmp_path(cur) == stop_cmp:
            break
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    parts_to_check.reverse()

    chain: List[Tuple[str, int, int]] = []
    for d in parts_to_check:
        try:
            st = os.lstat(d)
        except FileNotFoundError:
            # Thư mục cha chưa tồn tại → bỏ qua ở đây, caller sẽ thấy gone
            continue
        except OSError as e:
            return f"cannot stat parent {d}: {e}", []
        if is_link_like(st):
            return f"parent directory is a symlink / reparse point ({d})", []
        if not stat.S_ISDIR(st.st_mode):
            return f"parent is not a directory ({d})", []
        chain.append((d, st.st_dev, st.st_ino))

    return "", chain


def verify_parent_chain(chain: Sequence[Tuple[str, int, int]], allowed_root: Optional[str] = None) -> str:
    """
    Xác minh lại toàn bộ chuỗi thư mục cha ngay trước khi xóa:
    - Không thành phần nào bị biến thành symlink/junction.
    - (st_dev, st_ino) của từng thành phần cha vẫn khớp lúc lập plan.
    - realpath vẫn nằm trong allowed_root (nếu có).
    """
    if not chain:
        return ""
    for d, exp_dev, exp_ino in chain:
        try:
            st = os.lstat(d)
        except OSError:
            return "parent directory disappeared or is inaccessible since the scan"
        if is_link_like(st):
            return f"parent directory became a symlink / reparse point ({d})"
        if not stat.S_ISDIR(st.st_mode):
            return f"parent path is no longer a directory ({d})"
        if (st.st_dev, st.st_ino) != (exp_dev, exp_ino):
            return f"parent directory was replaced since the scan ({d})"
    if allowed_root:
        last_dir = chain[-1][0]
        why, _ = check_ancestor_chain(os.path.join(last_dir, "__leaf__"), allowed_root)
        if why:
            return why
    return ""


def _open_verified_parent_fd(chain: Sequence[Tuple[str, int, int]]) -> int:
    """
    POSIX: mở từng bước theo `chain` bằng O_RDONLY | O_DIRECTORY | O_NOFOLLOW và
    kiểm tra fstat(fd) khớp (st_dev, st_ino) đã ghi nhận lúc scan.
    Trả về fd của thư mục cha cuối cùng (caller phải os.close(fd)).
    Ném OSError nếu bất kỳ bước nào bị thay thế hoặc là symlink.
    """
    if IS_WINDOWS or not chain or not hasattr(os, "O_NOFOLLOW"):
        return -1
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    cur_fd = -1
    try:
        for idx, (d, exp_dev, exp_ino) in enumerate(chain):
            if idx == 0:
                fd = os.open(d, flags)
            else:
                name = os.path.basename(d)
                fd = os.open(name, flags, dir_fd=cur_fd)
                os.close(cur_fd)
                cur_fd = -1
            cur_fd = fd
            fst = os.fstat(cur_fd)
            if is_link_like(fst) or not stat.S_ISDIR(fst.st_mode):
                raise PermissionError(f"parent {d} is not a real directory")
            if (fst.st_dev, fst.st_ino) != (exp_dev, exp_ino):
                raise PermissionError(f"parent {d} changed since the scan")
        return cur_fd
    except Exception:
        if cur_fd >= 0:
            try:
                os.close(cur_fd)
            except OSError:
                pass
        raise


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

_tls_exec = threading.local()


def set_stop_requested(stop_fn: Optional[Callable[[], bool]]) -> None:
    """Đăng ký hàm kiểm tra yêu cầu dừng hợp tác (cooperative cancellation) cho luồng hiện tại."""
    _tls_exec.stop_fn = stop_fn


def is_stop_requested(stop: Optional[Callable[[], bool]] = None) -> bool:
    if stop is not None and stop():
        return True
    fn = getattr(_tls_exec, "stop_fn", None)
    return bool(fn and fn())


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
    entries: Dict[str, Tuple[str, int, int, int, int, int]] = field(default_factory=dict)


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

    if deadline is not None and time.monotonic() > deadline:
        ts.truncated = True
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
        if deadline is not None and time.monotonic() > deadline:
            ts.truncated = True
            stack.clear()
            break
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            ts.errors += 1
            continue
        with it:
            for e in it:
                n += 1
                if deadline is not None and (n & 0x3F) == 0 and time.monotonic() > deadline:
                    ts.truncated = True
                    stack.clear()
                    break
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    ts.errors += 1
                    continue
                rel = os.path.relpath(e.path, p).replace("\\", "/")
                if is_link_like(st):
                    ts.entries[rel] = ("l", st.st_dev, st.st_ino, 0, st.st_mtime_ns, st.st_ctime_ns)
                    continue
                mode = st.st_mode
                if stat.S_ISDIR(mode):
                    if st.st_dev != dev:
                        ts.crosses_mount = True
                        continue
                    ts.entries[rel] = ("d", st.st_dev, st.st_ino, 0, st.st_mtime_ns, st.st_ctime_ns)
                    if st.st_mtime > ts.newest:
                        ts.newest = st.st_mtime
                    if me is not None and st.st_uid != me:
                        ts.foreign_owner = True
                    stack.append(e.path)
                elif is_special(mode):
                    ts.has_special = True
                else:
                    ts.entries[rel] = ("f", st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
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
    /proc N lần); khi THỰC THI dùng max_age=0 để luôn lấy dữ liệu mới nhất ở mỗi
    lần kiểm tra (không giữ snapshot cũ trong instance).
    """
    _lock = threading.Lock()
    _shared: Optional[Tuple[float, Set[str], Set[str], Optional[Set[str]], Set[str]]] = None

    def __init__(self, *, max_age: float = 5.0, open_files_deadline: float = 4.0):
        self._max_age = max_age
        self._deadline = open_files_deadline
        self._snap: Optional[Tuple[Set[str], Set[str], Set[str]]] = None
        self._snap_ts: float = 0.0
        self._open_anc: Optional[Set[str]] = None
        self._open_ts: float = 0.0

    # ── tiến trình ───────────────────────────────────────────
    _DEFAULT_LOAD_PROCS = None

    @classmethod
    def psutil_available(cls) -> bool:
        if cls._load_procs is not cls._DEFAULT_LOAD_PROCS:
            return True
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
        # Hỗ trợ FakeGuards trong bộ test: FakeGuards gán trực tiếp self._snap trong __init__
        # mà không đặt _snap_ts (== 0.0). Với Guards thật: chỉ dùng lại self._snap khi
        # self._max_age > 0 và chưa quá hạn; khi max_age <= 0 luôn đọc lại dữ liệu mới.
        now_m = time.monotonic()
        if self._snap is not None:
            if self._snap_ts == 0.0:
                return self._snap
            if self._max_age > 0 and (now_m - self._snap_ts) <= self._max_age:
                return self._snap
        with Guards._lock:
            sh = Guards._shared
            now_m = time.monotonic()
            if sh and self._max_age > 0 and (now_m - sh[0]) <= self._max_age:
                self._snap = (sh[1], sh[2], sh[4])
                self._snap_ts = sh[0]
                return self._snap
            names, udd, sandbox = self._load_procs()
            prev_anc = sh[3] if (sh and self._max_age > 0 and (now_m - sh[0]) <= self._max_age) else None
            Guards._shared = (now_m, names, udd, prev_anc, sandbox)
            if self._max_age > 0:
                self._snap = (names, udd, sandbox)
                self._snap_ts = now_m
            else:
                self._snap = None
                self._snap_ts = 0.0
            return (names, udd, sandbox)

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

        my_uid = _euid() if not IS_WINDOWS else None
        for p in psutil.process_iter():
            if time.monotonic() > end:
                break
            try:
                if my_uid is not None and my_uid != 0:
                    try:
                        if p.uids().real != my_uid:
                            continue
                    except Exception:
                        continue
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
        now_m = time.monotonic()
        if self._open_anc is not None:
            if self._open_ts == 0.0:
                return os.fspath(path) in self._open_anc
            if self._max_age > 0 and (now_m - self._open_ts) <= self._max_age:
                return os.fspath(path) in self._open_anc
        with Guards._lock:
            sh = Guards._shared
            now_m = time.monotonic()
            if sh and self._max_age > 0 and sh[3] is not None and (now_m - sh[0]) <= self._max_age:
                anc = sh[3]
                self._open_anc = anc
                self._open_ts = sh[0]
            else:
                anc = self._load_open()
                if sh:
                    Guards._shared = (now_m, sh[1], sh[2], anc, sh[4])
                else:
                    names, udd, sandbox = self._load_procs()
                    Guards._shared = (now_m, names, udd, anc, sandbox)
                if self._max_age > 0:
                    self._open_anc = anc
                    self._open_ts = now_m
                else:
                    self._open_anc = None
                    self._open_ts = 0.0
        return os.fspath(path) in anc


Guards._DEFAULT_LOAD_PROCS = Guards._load_procs


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
    if ts.truncated:
        return "scan truncated (deadline exceeded — incomplete tree)"
    if ts.errors > 0:
        return f"scan incomplete ({ts.errors} read/permission error(s) inside tree)"
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
              ts: Optional[TreeStats] = None,
              allowed_root: Optional[str] = None,
              keep: Sequence[str] = ()) -> Tuple[Optional[PlanItem], str]:
    """
    lstat + tree_stats + guard → (PlanItem, '') nếu đủ điều kiện,
    (None, lý do) nếu bị bỏ qua, (PlanItem(blocked=...), lý do) cho mục 'bị chặn có điều kiện'
    (ví dụ app đang chạy) — để UI vẫn hiển thị và nói rõ lý do.
    """
    now = now or time.time()
    p = os.fspath(path)
    why_anc, parent_chain = check_ancestor_chain(p, allowed_root)
    if why_anc:
        return None, why_anc
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
    meta: dict = {"parent_chain": tuple(parent_chain), "recent_sec": policy.recent_sec}
    if allowed_root:
        meta["allowed_root"] = os.path.abspath(os.fspath(allowed_root))
    if kind == "dir":
        meta["tree_manifest"] = dict(ts.entries)
    if keep:
        meta["keep"] = tuple(keep)
    eff_size = ts.size
    eff_files = ts.files
    if kind == "dir" and keep_root and keep:
        keep_set = set(keep)
        for rel, rec in ts.entries.items():
            if rel.split("/", 1)[0] in keep_set and rec[0] == "f":
                eff_size = max(0, eff_size - rec[3])
                eff_files = max(0, eff_files - 1)
    item = PlanItem(path=p, kind=kind, size=eff_size, shared=ts.shared, files=eff_files,
                    newest=ts.newest, dev=st.st_dev, ino=st.st_ino, mtime_ns=st.st_mtime_ns,
                    ctime_ns=st.st_ctime_ns,
                    label=label or os.path.basename(p) or p, group=group, note=note, risk=risk,
                    keep_root=keep_root, basis=policy.basis, closed=tuple(policy.closed),
                    meta=meta)
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
                   keep: Sequence[str] = (),
                   allowed_root: Optional[str] = None) -> Optional[PlanItem]:
    """Quét đệ quy, gom các FILE đã quá tuổi dưới root thành MỘT mục 'files'."""
    now = now or time.time()
    r = os.fspath(root)
    why_anc, parent_chain = check_ancestor_chain(r, allowed_root)
    if why_anc:
        return None
    try:
        st0 = os.lstat(r)
    except OSError:
        return None
    if not stat.S_ISDIR(st0.st_mode) or is_link_like(st0):
        return None
    dev = st0.st_dev
    files: List[Tuple[str, int, int, int, int]] = []
    file_chains: Dict[str, Tuple[Tuple[str, int, int], ...]] = {}
    file_devs: Dict[str, int] = {}
    root_chain = list(parent_chain) + [(os.path.abspath(r), st0.st_dev, st0.st_ino)]
    shared_skipped = 0
    stack: List[Tuple[str, List[Tuple[str, int, int]]]] = [(r, root_chain)]
    while stack:
        cur, cur_chain = stack.pop()
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
                        stack.append((e.path, cur_chain + [(os.path.abspath(e.path), st.st_dev, st.st_ino)]))
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
                file_chains[e.path] = tuple(cur_chain)
                file_devs[e.path] = st.st_dev
    if not files:
        return None
    item = make_files_item(r, files, label=label or os.path.basename(r), group=group, note=note,
                           basis=policy.basis)
    item.dev, item.ino = st0.st_dev, st0.st_ino
    item.closed = tuple(policy.closed)
    item.newest = now - policy.min_age_sec if policy.min_age_sec else now
    item.meta["keep"] = tuple(keep)
    item.meta["parent_chain"] = tuple(root_chain)
    item.meta["file_chains"] = file_chains
    item.meta["file_devs"] = file_devs
    if allowed_root:
        item.meta["allowed_root"] = os.path.abspath(os.fspath(allowed_root))
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
        if is_link_like(st):
            return
        os.chmod(path, (st.st_mode | stat.S_IWRITE | (stat.S_IRUSR | stat.S_IXUSR if stat.S_ISDIR(st.st_mode) else 0)))
    except OSError:
        pass


def _fchmod_writable(fd: int, is_dir: bool) -> None:
    try:
        st = os.fstat(fd)
        if is_link_like(st):
            return
        mode = st.st_mode | stat.S_IWUSR | (stat.S_IRUSR | stat.S_IXUSR if is_dir else 0)
        os.fchmod(fd, mode)
    except (OSError, AttributeError):
        pass


def _unlink_file_at(parent_fd: int, name: str, *,
                    exp_dev: Optional[int] = None, exp_ino: Optional[int] = None,
                    exp_size: Optional[int] = None, exp_mtime_ns: Optional[int] = None,
                    exp_ctime_ns: Optional[int] = None,
                    parent_chain: Sequence[Tuple[str, int, int]] = (),
                    allowed_root: Optional[str] = None) -> int:
    """POSIX: xóa 1 file hoặc symlink qua parent_fd sau khi xác minh fstat/stat(follow_symlinks=False)."""
    if parent_chain or allowed_root:
        why = verify_parent_chain(parent_chain, allowed_root)
        if why:
            raise PermissionError(why)
    st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if exp_dev is not None and exp_ino is not None:
        if is_link_like(st):
            raise PermissionError("target became a symlink / reparse point before removal")
        if not stat.S_ISREG(st.st_mode):
            raise PermissionError("target is no longer a regular file")
        if (st.st_dev, st.st_ino) != (exp_dev, exp_ino):
            raise PermissionError("target replaced since the scan")
        if exp_size is not None and st.st_size != exp_size:
            raise PermissionError("target modified since the scan")
        if exp_mtime_ns is not None and st.st_mtime_ns != exp_mtime_ns:
            raise PermissionError("target modified since the scan")
        if exp_ctime_ns is not None and exp_ctime_ns and st.st_ctime_ns != exp_ctime_ns:
            raise PermissionError("target changed since the scan")
    else:
        if stat.S_ISDIR(st.st_mode) and not is_link_like(st):
            raise PermissionError("unexpected directory where file or symlink expected")
    try:
        os.unlink(name, dir_fd=parent_fd)
    except PermissionError:
        _fchmod_writable(parent_fd, is_dir=True)
        if not is_link_like(st):
            try:
                ffd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
                try:
                    fst = os.fstat(ffd)
                    if (fst.st_dev, fst.st_ino) == (st.st_dev, st.st_ino):
                        _fchmod_writable(ffd, is_dir=False)
                finally:
                    os.close(ffd)
            except OSError:
                pass
        os.unlink(name, dir_fd=parent_fd)
    return st.st_size if (not is_link_like(st) and st.st_nlink <= 1) else 0


def _clear_dir_fd(dir_fd: int, rel_prefix: str, root_dev: int, *,
                  keep_names: Set[str],
                  manifest: Optional[Dict[str, Tuple[str, int, int, int, int, int]]],
                  parent_chain: Sequence[Tuple[str, int, int]],
                  allowed_root: Optional[str],
                  stop: Optional[Callable[[], bool]],
                  stats: Dict[str, int]) -> None:
    """
    POSIX: xóa đệ quy nội dung thư mục gắn chặt vào `dir_fd` (O_RDONLY | O_DIRECTORY | O_NOFOLLOW).
    Tuyệt đối không dùng đường dẫn chuỗi tuyệt đối sau khi mở handle.
    """
    if is_stop_requested(stop):
        stats["interrupted"] = 1
        return
    if parent_chain or allowed_root:
        why = verify_parent_chain(parent_chain, allowed_root)
        if why:
            raise PermissionError(why)

    raw_names: List[str] = []
    for attempt in range(2):
        dup_fd = os.dup(dir_fd)
        try:
            with os.scandir(dup_fd) as it:
                for e in it:
                    if not rel_prefix and e.name in keep_names:
                        continue
                    raw_names.append(e.name)
            break
        except PermissionError:
            if attempt == 0:
                _fchmod_writable(dir_fd, is_dir=True)
                raw_names.clear()
                continue
            raise
        finally:
            try:
                os.close(dup_fd)
            except OSError:
                pass
    raw_names.sort()

    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for ename in raw_names:
        if is_stop_requested(stop):
            stats["interrupted"] = 1
            return
        if parent_chain or allowed_root:
            why = verify_parent_chain(parent_chain, allowed_root)
            if why:
                raise PermissionError(why)
        rel = ename if not rel_prefix else f"{rel_prefix}/{ename}"
        est = os.stat(ename, dir_fd=dir_fd, follow_symlinks=False)
        exp_dev = est.st_dev
        exp_ino = est.st_ino
        exp_size = est.st_size
        exp_mtime_ns = est.st_mtime_ns
        exp_ctime_ns = est.st_ctime_ns
        if manifest is not None:
            if rel not in manifest:
                raise PermissionError(f"modified since the scan (unpreviewed entry {rel})")
            e_kind, e_dev, e_ino, e_size, e_mtime_ns, e_ctime_ns = manifest[rel]
            c_kind = "l" if is_link_like(est) else ("d" if stat.S_ISDIR(est.st_mode) else "f")
            if c_kind != e_kind or (est.st_dev, est.st_ino) != (e_dev, e_ino):
                raise PermissionError(f"modified since the scan ({rel} replaced)")
            if c_kind != "d" and (est.st_size != e_size or est.st_mtime_ns != e_mtime_ns or est.st_ctime_ns != e_ctime_ns):
                raise PermissionError(f"modified since the scan ({rel} modified)")
            exp_dev, exp_ino, exp_size, exp_mtime_ns, exp_ctime_ns = e_dev, e_ino, e_size, e_mtime_ns, e_ctime_ns

        if stat.S_ISDIR(est.st_mode) and not is_link_like(est):
            if est.st_dev != root_dev:
                raise PermissionError(f"crosses a mount point ({rel})")
            try:
                child_fd = os.open(ename, dir_flags, dir_fd=dir_fd)
            except PermissionError:
                _fchmod_writable(dir_fd, is_dir=True)
                try:
                    tmp_fd = os.open(ename, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
                    try:
                        _fchmod_writable(tmp_fd, is_dir=True)
                    finally:
                        os.close(tmp_fd)
                except OSError:
                    pass
                child_fd = os.open(ename, dir_flags, dir_fd=dir_fd)
            try:
                cfst = os.fstat(child_fd)
                if is_link_like(cfst) or not stat.S_ISDIR(cfst.st_mode) or (cfst.st_dev, cfst.st_ino) != (exp_dev, exp_ino):
                    raise PermissionError(f"subdirectory {rel} changed or became a symlink during removal")
                _clear_dir_fd(
                    child_fd, rel, root_dev,
                    keep_names=set(), manifest=manifest,
                    parent_chain=parent_chain, allowed_root=allowed_root,
                    stop=stop, stats=stats,
                )
            finally:
                os.close(child_fd)
            if stats.get("interrupted"):
                return
            try:
                os.rmdir(ename, dir_fd=dir_fd)
            except PermissionError:
                _fchmod_writable(dir_fd, is_dir=True)
                os.rmdir(ename, dir_fd=dir_fd)
        else:
            is_lnk = is_link_like(est)
            freed_b = _unlink_file_at(
                dir_fd, ename,
                exp_dev=None if is_lnk else exp_dev,
                exp_ino=None if is_lnk else exp_ino,
                exp_size=None if is_lnk else exp_size,
                exp_mtime_ns=None if is_lnk else exp_mtime_ns,
                exp_ctime_ns=None if is_lnk else exp_ctime_ns,
                parent_chain=parent_chain, allowed_root=allowed_root,
            )
            if not is_lnk:
                stats["removed"] += 1
                stats["freed"] += freed_b


def _remove_tree_windows_verified(path: str, *,
                                  parent_chain: Sequence[Tuple[str, int, int]] = (),
                                  allowed_root: Optional[str] = None,
                                  exp_dev: Optional[int] = None,
                                  exp_ino: Optional[int] = None,
                                  is_dir: bool = False,
                                  keep_root: bool = False,
                                  keep_names: Set[str] = frozenset(),
                                  manifest: Optional[Dict[str, Tuple[str, int, int, int, int, int]]] = None,
                                  stop: Optional[Callable[[], bool]] = None,
                                  stats: Optional[Dict[str, int]] = None) -> None:
    """
    Windows / fallback không có dir_fd: kiểm tra lại chuỗi cha và thuộc tính reparse point/junction
    ở từng bước trước khi xóa; từ chối ngay nếu phát hiện symlink/junction hoặc thay đổi ngoài plan.
    """
    if stats is None:
        stats = {"removed": 0, "freed": 0, "interrupted": 0}
    if parent_chain or allowed_root:
        why = verify_parent_chain(parent_chain, allowed_root)
        if why:
            raise PermissionError(why)
    st0 = os.lstat(path)
    if is_link_like(st0):
        raise PermissionError("target is a symlink / reparse point")
    if exp_dev is not None and exp_ino is not None and (st0.st_dev, st0.st_ino) != (exp_dev, exp_ino):
        raise PermissionError("target replaced since the scan")
    if not is_dir:
        try:
            os.unlink(path)
        except PermissionError:
            _chmod_writable(path)
            os.unlink(path)
        stats["removed"] += 1
        if st0.st_nlink <= 1:
            stats["freed"] += st0.st_size
        return

    root_dev = st0.st_dev

    def _walk_win(cur_path: str, rel_prefix: str, exp_dir_dev: int, exp_dir_ino: int) -> None:
        if is_stop_requested(stop):
            stats["interrupted"] = 1
            return
        if parent_chain or allowed_root:
            why_p = verify_parent_chain(parent_chain, allowed_root)
            if why_p:
                raise PermissionError(why_p)
        cst = os.lstat(cur_path)
        if is_link_like(cst) or not stat.S_ISDIR(cst.st_mode):
            raise PermissionError(f"directory became a symlink / reparse point ({cur_path})")
        if exp_dir_ino and (cst.st_dev, cst.st_ino) != (exp_dir_dev, exp_dir_ino):
            raise PermissionError(f"directory was replaced during removal ({cur_path})")
        with os.scandir(cur_path) as it:
            entries = sorted(list(it), key=lambda x: x.name)
        for e in entries:
            if is_stop_requested(stop):
                stats["interrupted"] = 1
                return
            if not rel_prefix and e.name in keep_names:
                continue
            rel = e.name if not rel_prefix else f"{rel_prefix}/{e.name}"
            est = os.lstat(e.path)
            if manifest is not None:
                if rel not in manifest:
                    raise PermissionError(f"modified since the scan (unpreviewed entry {rel})")
                e_kind, e_dev, e_ino, e_size, e_mtime_ns, e_ctime_ns = manifest[rel]
                c_kind = "l" if is_link_like(est) else ("d" if stat.S_ISDIR(est.st_mode) else "f")
                if c_kind != e_kind or (est.st_dev, est.st_ino) != (e_dev, e_ino):
                    raise PermissionError(f"modified since the scan ({rel} replaced)")
                if c_kind != "d" and (est.st_size != e_size or est.st_mtime_ns != e_mtime_ns or est.st_ctime_ns != e_ctime_ns):
                    raise PermissionError(f"modified since the scan ({rel} modified)")
            if stat.S_ISDIR(est.st_mode) and not is_link_like(est):
                if est.st_dev != root_dev:
                    raise PermissionError(f"crosses a mount point ({rel})")
                _walk_win(e.path, rel, est.st_dev, est.st_ino)
                if stats.get("interrupted"):
                    return
                try:
                    os.rmdir(e.path)
                except PermissionError:
                    _chmod_writable(cur_path)
                    _chmod_writable(e.path)
                    os.rmdir(e.path)
            else:
                try:
                    os.unlink(e.path)
                except PermissionError:
                    _chmod_writable(cur_path)
                    if not is_link_like(est):
                        _chmod_writable(e.path)
                    os.unlink(e.path)
                if not is_link_like(est):
                    stats["removed"] += 1
                    if est.st_nlink <= 1:
                        stats["freed"] += est.st_size

    _walk_win(path, "", st0.st_dev, st0.st_ino)
    if not keep_root and not stats.get("interrupted"):
        if parent_chain or allowed_root:
            why_p = verify_parent_chain(parent_chain, allowed_root)
            if why_p:
                raise PermissionError(why_p)
        cst_end = os.lstat(path)
        if is_link_like(cst_end) or (exp_ino and (cst_end.st_dev, cst_end.st_ino) != (exp_dev, exp_ino)):
            raise PermissionError("target directory changed during removal")
        try:
            os.rmdir(path)
        except PermissionError:
            _chmod_writable(os.path.dirname(path))
            _chmod_writable(path)
            os.rmdir(path)


def remove_path(path: str) -> None:
    """
    Xóa file hoặc cây thư mục, không theo symlink; tự xử lý read-only.
    Trên POSIX luôn thực thi qua descriptor thư mục cha đã xác minh (dir_fd + O_NOFOLLOW).
    """
    ctx = getattr(_tls_exec, "verified_removal", None)
    if ctx is not None and ctx.get("path") == path:
        parent_fd = ctx["parent_fd"]
        name = ctx["name"]
        if parent_fd >= 0:
            if not ctx["is_dir"]:
                freed_b = _unlink_file_at(
                    parent_fd, name,
                    exp_dev=ctx["exp_dev"], exp_ino=ctx["exp_ino"],
                    exp_size=ctx.get("exp_size"),
                    exp_mtime_ns=ctx.get("exp_mtime_ns"),
                    exp_ctime_ns=ctx.get("exp_ctime_ns"),
                    parent_chain=ctx.get("parent_chain") or (),
                    allowed_root=ctx.get("allowed_root"),
                )
                ctx["stats"]["removed"] += 1
                ctx["stats"]["freed"] += freed_b
                return
            dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                target_fd = os.open(name, dir_flags, dir_fd=parent_fd)
            except PermissionError:
                _fchmod_writable(parent_fd, is_dir=True)
                try:
                    tmp_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
                    try:
                        _fchmod_writable(tmp_fd, is_dir=True)
                    finally:
                        os.close(tmp_fd)
                except OSError:
                    pass
                target_fd = os.open(name, dir_flags, dir_fd=parent_fd)
            try:
                tfst = os.fstat(target_fd)
                if is_link_like(tfst) or not stat.S_ISDIR(tfst.st_mode) or (tfst.st_dev, tfst.st_ino) != (ctx["exp_dev"], ctx["exp_ino"]):
                    raise PermissionError("target directory changed or became a symlink before removal")
                _clear_dir_fd(
                    target_fd, "", ctx["exp_dev"],
                    keep_names=set(ctx.get("keep_names") or ()),
                    manifest=ctx.get("manifest"),
                    parent_chain=ctx.get("parent_chain") or (),
                    allowed_root=ctx.get("allowed_root"),
                    stop=ctx.get("stop"),
                    stats=ctx["stats"],
                )
            finally:
                os.close(target_fd)
            if not ctx.get("keep_root") and not ctx["stats"].get("interrupted"):
                if ctx.get("parent_chain") or ctx.get("allowed_root"):
                    why = verify_parent_chain(ctx.get("parent_chain") or (), ctx.get("allowed_root"))
                    if why:
                        raise PermissionError(why)
                st_end = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if is_link_like(st_end) or (st_end.st_dev, st_end.st_ino) != (ctx["exp_dev"], ctx["exp_ino"]):
                    raise PermissionError("target directory changed during removal")
                try:
                    os.rmdir(name, dir_fd=parent_fd)
                except PermissionError:
                    _fchmod_writable(parent_fd, is_dir=True)
                    os.rmdir(name, dir_fd=parent_fd)
            return
        _remove_tree_windows_verified(
            path,
            parent_chain=ctx.get("parent_chain") or (),
            allowed_root=ctx.get("allowed_root"),
            exp_dev=ctx["exp_dev"],
            exp_ino=ctx["exp_ino"],
            is_dir=ctx["is_dir"],
            keep_root=bool(ctx.get("keep_root")),
            keep_names=set(ctx.get("keep_names") or ()),
            manifest=ctx.get("manifest"),
            stop=ctx.get("stop"),
            stats=ctx["stats"],
        )
        return

    # Standalone call to remove_path(path):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    why_anc, p_chain = check_ancestor_chain(path, None)
    if why_anc:
        raise PermissionError(why_anc)
    is_dir = stat.S_ISDIR(st.st_mode) and not is_link_like(st)
    if not IS_WINDOWS and p_chain and hasattr(os, "O_NOFOLLOW"):
        parent_fd = _open_verified_parent_fd(p_chain)
        name = os.path.basename(os.path.abspath(path))
        stats = {"removed": 0, "freed": 0, "interrupted": 0}
        try:
            why_after = verify_parent_chain(p_chain, None)
            if why_after:
                raise PermissionError(why_after)
            st_cur = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (st_cur.st_dev, st_cur.st_ino) != (st.st_dev, st.st_ino):
                raise PermissionError("target changed before removal")
            if not is_dir:
                is_lnk = is_link_like(st_cur)
                _unlink_file_at(
                    parent_fd, name,
                    exp_dev=None if is_lnk else st.st_dev,
                    exp_ino=None if is_lnk else st.st_ino,
                    parent_chain=p_chain,
                )
            else:
                dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                try:
                    t_fd = os.open(name, dir_flags, dir_fd=parent_fd)
                except PermissionError:
                    _fchmod_writable(parent_fd, is_dir=True)
                    t_fd = os.open(name, dir_flags, dir_fd=parent_fd)
                try:
                    _clear_dir_fd(
                        t_fd, "", st.st_dev,
                        keep_names=set(), manifest=None,
                        parent_chain=p_chain, allowed_root=None,
                        stop=None, stats=stats,
                    )
                finally:
                    os.close(t_fd)
                if not stats.get("interrupted"):
                    try:
                        os.rmdir(name, dir_fd=parent_fd)
                    except PermissionError:
                        _fchmod_writable(parent_fd, is_dir=True)
                        os.rmdir(name, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
        return
    if is_link_like(st):
        os.unlink(path)
        return
    _remove_tree_windows_verified(
        path, parent_chain=p_chain, exp_dev=st.st_dev, exp_ino=st.st_ino, is_dir=is_dir
    )


def _remove_verified_target(path: str, parent_chain: Sequence[Tuple[str, int, int]],
                            exp_dev: int, exp_ino: int, is_dir: bool, *,
                            keep_root: bool = False,
                            keep_names: Sequence[str] = (),
                            manifest: Optional[Dict[str, Tuple[str, int, int, int, int, int]]] = None,
                            allowed_root: Optional[str] = None,
                            exp_size: Optional[int] = None,
                            exp_mtime_ns: Optional[int] = None,
                            exp_ctime_ns: Optional[int] = None,
                            stop: Optional[Callable[[], bool]] = None,
                            stats: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    """
    Xóa mục gắn chặt vào thư mục cha đã xác minh (trên POSIX dùng dir_fd + O_NOFOLLOW xuyên suốt
    từ lúc mở cho tới khi hoàn tất toàn bộ cây/file/keep_root).
    """
    if stats is None:
        stats = {"removed": 0, "freed": 0, "interrupted": 0}
    else:
        stats.setdefault("removed", 0)
        stats.setdefault("freed", 0)
        stats.setdefault("interrupted", 0)
    eff_chain = list(parent_chain)
    if not eff_chain:
        why_anc, eff_chain = check_ancestor_chain(path, allowed_root)
        if why_anc:
            raise PermissionError(why_anc)
    why_before = verify_parent_chain(eff_chain, allowed_root)
    if why_before:
        raise PermissionError(why_before)
    parent_fd = -1
    if not IS_WINDOWS and eff_chain and hasattr(os, "O_NOFOLLOW"):
        parent_fd = _open_verified_parent_fd(eff_chain)
    try:
        # Kiểm tra lại chuỗi cha ngay sau khi mở parent_fd để bắt trường hợp hoán đổi
        # thư mục cha ngay sau bước mở handle.
        why_after = verify_parent_chain(eff_chain, allowed_root)
        if why_after:
            raise PermissionError(why_after)
        name = os.path.basename(os.path.abspath(path))
        if parent_fd >= 0:
            st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if is_link_like(st) or (st.st_dev, st.st_ino) != (exp_dev, exp_ino):
                raise PermissionError("target changed or became a symlink before removal")
            if is_dir and not stat.S_ISDIR(st.st_mode):
                raise PermissionError("target is no longer a directory")
            if not is_dir and not stat.S_ISREG(st.st_mode):
                raise PermissionError("target is no longer a regular file")
        prev_ctx = getattr(_tls_exec, "verified_removal", None)
        _tls_exec.verified_removal = {
            "path": path,
            "parent_fd": parent_fd,
            "name": name,
            "exp_dev": exp_dev,
            "exp_ino": exp_ino,
            "is_dir": is_dir,
            "keep_root": keep_root,
            "keep_names": tuple(keep_names),
            "manifest": manifest,
            "parent_chain": tuple(eff_chain),
            "allowed_root": allowed_root,
            "exp_size": exp_size,
            "exp_mtime_ns": exp_mtime_ns,
            "exp_ctime_ns": exp_ctime_ns,
            "stop": stop,
            "stats": stats,
        }
        try:
            remove_path(path)
        finally:
            _tls_exec.verified_removal = prev_ctx
    finally:
        if parent_fd >= 0:
            try:
                os.close(parent_fd)
            except OSError:
                pass
    return stats


def _prune_empty_dirs_fd(dir_fd: int, root_dev: int) -> bool:
    """POSIX: dọn các thư mục con rỗng từ dưới lên qua dir_fd + O_NOFOLLOW; trả về True nếu dir_fd đã rỗng."""
    empty = True
    dup_fd = os.dup(dir_fd)
    entries = []
    try:
        with os.scandir(dup_fd) as it:
            for e in it:
                try:
                    st = os.stat(e.name, dir_fd=dir_fd, follow_symlinks=False)
                except OSError:
                    empty = False
                    continue
                entries.append((e.name, st))
    finally:
        try:
            os.close(dup_fd)
        except OSError:
            pass
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for ename, st in entries:
        if stat.S_ISDIR(st.st_mode) and not is_link_like(st) and st.st_dev == root_dev:
            try:
                cfd = os.open(ename, dir_flags, dir_fd=dir_fd)
            except OSError:
                empty = False
                continue
            try:
                cfst = os.fstat(cfd)
                if (cfst.st_dev, cfst.st_ino) == (st.st_dev, st.st_ino) and not is_link_like(cfst):
                    sub_empty = _prune_empty_dirs_fd(cfd, root_dev)
                else:
                    sub_empty = False
            finally:
                os.close(cfd)
            if sub_empty:
                try:
                    os.rmdir(ename, dir_fd=dir_fd)
                except OSError:
                    empty = False
            else:
                empty = False
        else:
            empty = False
    return empty


def _prune_empty_dirs(root: str, keep_root: bool = True, *,
                      parent_chain: Sequence[Tuple[str, int, int]] = (),
                      allowed_root: Optional[str] = None) -> None:
    eff_chain = list(parent_chain)
    if not eff_chain:
        why_anc, eff_chain = check_ancestor_chain(os.path.join(os.path.abspath(root), "__leaf__"), allowed_root)
        if why_anc:
            return
    else:
        why_p = verify_parent_chain(eff_chain, allowed_root)
        if why_p:
            return
    if not IS_WINDOWS and eff_chain and hasattr(os, "O_NOFOLLOW"):
        try:
            root_fd = _open_verified_parent_fd(eff_chain)
        except OSError:
            return
        try:
            if verify_parent_chain(eff_chain, allowed_root):
                return
            all_empty = _prune_empty_dirs_fd(root_fd, os.fstat(root_fd).st_dev)
        finally:
            os.close(root_fd)
        if not keep_root and all_empty and len(eff_chain) >= 2:
            try:
                p_fd = _open_verified_parent_fd(eff_chain[:-1])
                try:
                    os.rmdir(os.path.basename(os.path.abspath(root)), dir_fd=p_fd)
                finally:
                    os.close(p_fd)
            except OSError:
                pass
        return

    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        if keep_root and dirpath == root:
            continue
        try:
            st = os.lstat(dirpath)
            if is_link_like(st):
                continue
            os.rmdir(dirpath)       # chỉ thành công nếu rỗng
        except OSError:
            pass


def _recheck_runtime_guards(item: PlanItem, guards: Optional[Guards]) -> str:
    """
    Kiểm tra lại mọi điều kiện runtime đã gắn vào PlanItem (browser process,
    Chromium SingletonLock / lockfile / --user-data-dir, Flatpak bwrap sandbox).
    """
    if item.closed and guards is not None:
        hit = guards.running(item.closed)
        if hit:
            return f"{hit} is running — close it first"
    chromium_dirs = item.meta.get("chromium_dirs") or ()
    for d in chromium_dirs:
        if chromium_profile_in_use(d) or (guards is not None and guards.user_data_dir_in_use(d)):
            cleaned_d = str(d).rstrip("/\\")
            return f"{os.path.basename(cleaned_d)} is running — close it first"
    sandbox_paths = item.meta.get("sandbox_paths") or ()
    if sandbox_paths and guards is not None:
        for sp in sandbox_paths:
            if guards.sandboxed(sp):
                return "the Flatpak app is running — close it first"
    return ""


def _verify_tree_manifest(item: PlanItem, cur: TreeStats) -> str:
    """
    Đối chiếu manifest các thành phần của cây tại thời điểm thực thi với thời điểm lập plan.
    Ngăn chặn việc xóa các file/thư mục mới phát sinh hoặc bị thay thế sau bước Preview/Review
    ngay cả khi mtime của chúng hoặc của thư mục con bị đặt lùi về quá khứ.
    """
    manifest = item.meta.get("tree_manifest")
    keep_names = set(item.meta.get("keep", ())) if item.keep_root else set()

    def _is_kept(rel: str) -> bool:
        if not keep_names:
            return False
        return rel.split("/", 1)[0] in keep_names

    if manifest is None:
        if not item.keep_root and (cur.files != item.files or cur.size != item.size):
            return "modified since the scan"
        return ""

    exp_map = {k: v for k, v in manifest.items() if not _is_kept(k)}
    cur_map = {k: v for k, v in cur.entries.items() if not _is_kept(k)}

    if set(cur_map.keys()) != set(exp_map.keys()):
        return "modified since the scan (tree entries added or removed)"

    for rel, cur_rec in cur_map.items():
        exp_rec = exp_map[rel]
        c_kind, c_dev, c_ino, c_size, c_mtime_ns, c_ctime_ns = cur_rec
        e_kind, e_dev, e_ino, e_size, e_mtime_ns, e_ctime_ns = exp_rec
        if c_kind != e_kind or (c_dev, c_ino) != (e_dev, e_ino):
            return f"modified since the scan ({rel} replaced)"
        if c_kind != "d" and (c_size != e_size or c_mtime_ns != e_mtime_ns or c_ctime_ns != e_ctime_ns):
            return f"modified since the scan ({rel} modified)"
    return ""


def execute_item(item: PlanItem, guards: Optional[Guards] = None, *, now: Optional[float] = None,
                 dry: bool = False, deadline: Optional[float] = None,
                 stop: Optional[Callable[[], bool]] = None) -> Outcome:
    """Kiểm tra lại rồi xóa MỘT mục của plan."""
    now = now or time.time()
    if is_stop_requested(stop):
        return Outcome(item, "skipped", reason="Interrupted by user")
    if item.blocked:
        return Outcome(item, "skipped", reason=item.blocked)

    why_runtime = _recheck_runtime_guards(item, guards)
    if why_runtime:
        return Outcome(item, "skipped", reason=why_runtime)

    parent_chain = item.meta.get("parent_chain") or ()
    allowed_root = item.meta.get("allowed_root")
    if not parent_chain:
        why_anc, parent_chain = check_ancestor_chain(item.path, allowed_root)
        if why_anc:
            return Outcome(item, "skipped", reason=why_anc)
    else:
        why_parent = verify_parent_chain(parent_chain, allowed_root)
        if why_parent:
            return Outcome(item, "skipped", reason=why_parent)

    if item.kind == "files":
        return _execute_files(item, guards, now, dry, stop=stop)

    p = item.path
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return Outcome(item, "gone", reason="already gone")
    except OSError as e:
        return Outcome(item, "failed", reason=str(e))
    if is_link_like(st):
        return Outcome(item, "skipped", reason="is a symlink / reparse point")
    if (st.st_dev, st.st_ino) != (item.dev, item.ino):
        return Outcome(item, "skipped", reason="replaced since the scan")
    if item.ctime_ns and st.st_ctime_ns != item.ctime_ns:
        # inode có thể được tái sử dụng cho một thư mục mới cùng tên; ctime thì không
        return Outcome(item, "skipped", reason="changed since the scan")

    if item.meta.get("require_core_dump"):
        if not stat.S_ISREG(st.st_mode) or not is_elf_core_file(p):
            return Outcome(item, "skipped", reason="not a verified ELF core dump file")

    if item.kind == "file":
        if not stat.S_ISREG(st.st_mode):
            return Outcome(item, "skipped", reason="no longer a regular file")
        if is_special(st.st_mode):
            return Outcome(item, "skipped", reason="socket/FIFO")
        if st.st_mtime_ns != item.mtime_ns or (item.size and st.st_size != item.size):
            return Outcome(item, "skipped", reason="modified since the scan")
        recent_sec = item.meta.get("recent_sec", RECENT_GUARD_SEC)
        if recent_sec and (now - st.st_mtime < recent_sec):
            return Outcome(item, "skipped", reason="modified in the last 10 minutes")
        if guards is not None and guards.in_use(p):
            return Outcome(item, "skipped", reason="in use by a running process")
        freed = st.st_size if st.st_nlink <= 1 else 0
        if dry:
            return Outcome(item, "removed", freed, 1)
        try:
            _remove_verified_target(
                p, parent_chain, item.dev, item.ino, is_dir=False,
                allowed_root=allowed_root, exp_size=st.st_size,
                exp_mtime_ns=item.mtime_ns, exp_ctime_ns=item.ctime_ns,
                stop=stop,
            )
        except PermissionError as e:
            msg = str(e)
            if any(k in msg for k in ("symlink", "reparse", "changed", "replaced", "parent", "boundary", "modified")):
                return Outcome(item, "skipped", reason=msg)
            return Outcome(item, "skipped", reason="locked / in use (cannot be deleted right now)")
        except OSError as e:
            return Outcome(item, "failed", reason=str(e))
        return Outcome(item, "removed", freed, 1)

    # ── thư mục ──
    cur = tree_stats(p, item.basis, deadline=deadline)
    if not cur.exists:
        return Outcome(item, "gone", reason="already gone")
    if cur.truncated:
        return Outcome(item, "skipped", reason="scan truncated (deadline exceeded — incomplete tree)")
    if cur.errors > 0:
        return Outcome(item, "skipped", reason=f"scan incomplete ({cur.errors} read/permission error(s) inside tree)")
    if cur.has_special:
        return Outcome(item, "skipped", reason="contains a socket/FIFO (live runtime state)")
    if cur.crosses_mount:
        return Outcome(item, "skipped", reason="crosses a mount point")
    if cur.foreign_owner:
        return Outcome(item, "skipped", reason="owned by another user")
    recent_sec = item.meta.get("recent_sec", RECENT_GUARD_SEC)
    if cur.newest > item.newest + 1.0 or (recent_sec and cur.newest and now - cur.newest < recent_sec):
        return Outcome(item, "skipped", reason="modified since the scan")
    why_manifest = _verify_tree_manifest(item, cur)
    if why_manifest:
        return Outcome(item, "skipped", reason=why_manifest)
    if guards is not None and guards.in_use(p):
        return Outcome(item, "skipped", reason="in use by a running process")

    # Kiểm tra lại lần cuối chuỗi cha ngay sát nút xóa
    if parent_chain or allowed_root:
        why_parent = verify_parent_chain(parent_chain, allowed_root)
        if why_parent:
            return Outcome(item, "skipped", reason=why_parent)

    keep_names = tuple(item.meta.get("keep", ())) if item.keep_root else ()
    keep_set = set(keep_names)
    kept_size = 0
    kept_files = 0
    if keep_set:
        for rel, rec in cur.entries.items():
            if rel.split("/", 1)[0] in keep_set and rec[0] == "f":
                kept_size += rec[3]
                kept_files += 1
    expected_size = max(0, cur.size - kept_size)
    expected_files = max(0, cur.files - kept_files)
    if dry:
        return Outcome(item, "removed", expected_size, expected_files)

    manifest = item.meta.get("tree_manifest")
    if manifest is not None and keep_set:
        manifest = {k: v for k, v in manifest.items() if k.split("/", 1)[0] not in keep_set}

    stats: Dict[str, int] = {"removed": 0, "freed": 0, "interrupted": 0}
    try:
        _remove_verified_target(
            p, parent_chain, item.dev, item.ino, is_dir=True,
            keep_root=item.keep_root, keep_names=keep_names,
            manifest=manifest, allowed_root=allowed_root,
            stop=stop, stats=stats,
        )
    except PermissionError as e:
        msg = str(e)
        removed_cnt = stats.get("removed", 0)
        freed_cnt = min(expected_size, stats.get("freed", 0)) if cur.shared > 0 else stats.get("freed", 0)
        if any(k in msg for k in ("symlink", "reparse", "changed", "replaced", "parent", "boundary", "modified", "unpreviewed", "mount")):
            reason = msg
        else:
            reason = "locked / in use (cannot be deleted right now)"
        if removed_cnt > 0:
            return Outcome(item, "partial", freed_cnt, removed_cnt, reason=reason)
        return Outcome(item, "skipped", 0, 0, reason=reason)
    except OSError as e:
        removed_cnt = stats.get("removed", 0)
        freed_cnt = min(expected_size, stats.get("freed", 0)) if cur.shared > 0 else stats.get("freed", 0)
        return Outcome(item, "partial", freed_cnt, removed_cnt, reason=str(e))

    removed_cnt = stats.get("removed", 0)
    freed_cnt = min(expected_size, stats.get("freed", 0)) if cur.shared > 0 else stats.get("freed", 0)
    if stats.get("interrupted"):
        if removed_cnt == 0:
            return Outcome(item, "skipped", 0, 0, reason="Interrupted by user")
        return Outcome(item, "partial", freed_cnt, removed_cnt, reason="Interrupted by user")
    if removed_cnt >= expected_files:
        return Outcome(item, "removed", expected_size, expected_files)
    return Outcome(item, "partial", freed_cnt, removed_cnt, reason="some files could not be removed")


def _execute_files(item: PlanItem, guards: Optional[Guards], now: float, dry: bool,
                   stop: Optional[Callable[[], bool]] = None) -> Outcome:
    files = item.meta.get("files", [])
    allowed_root = item.meta.get("allowed_root") or item.meta.get("root") or item.path
    file_chains: Dict[str, Tuple[Tuple[str, int, int], ...]] = item.meta.get("file_chains") or {}
    file_devs: Dict[str, int] = item.meta.get("file_devs") or {}
    root_chain = item.meta.get("parent_chain") or ()
    freed = removed = skipped = 0
    interrupted = False
    for path, mtime_ns, ino, size, ctime_ns in files:
        if is_stop_requested(stop):
            interrupted = True
            break
        f_chain = file_chains.get(path)
        if f_chain:
            why_anc = verify_parent_chain(f_chain, allowed_root)
        else:
            why_anc, f_chain = check_ancestor_chain(path, allowed_root)
        if why_anc:
            skipped += 1
            continue
        try:
            st = os.lstat(path)
        except OSError:
            continue
        exp_dev = file_devs.get(path, st.st_dev)
        if ((st.st_dev, st.st_ino) != (exp_dev, ino)
                or st.st_mtime_ns != mtime_ns
                or st.st_ctime_ns != ctime_ns
                or st.st_size != size
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
                _remove_verified_target(
                    path, f_chain, exp_dev, ino, is_dir=False,
                    allowed_root=allowed_root, exp_size=size,
                    exp_mtime_ns=mtime_ns, exp_ctime_ns=ctime_ns,
                    stop=stop,
                )
            except OSError:
                skipped += 1
                continue
        freed += size
        removed += 1
    if not dry and removed:
        _prune_empty_dirs(
            item.meta.get("root", item.path), keep_root=True,
            parent_chain=root_chain, allowed_root=allowed_root,
        )
    if interrupted:
        if removed == 0:
            return Outcome(item, "skipped", 0, 0, reason="Interrupted by user")
        return Outcome(item, "partial", freed, removed, reason="Interrupted by user")
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
                 stop: Optional[Callable[[], bool]] = None,
                 deadline: Optional[float] = None) -> ExecResult:
    guards = guards or Guards(max_age=0)
    res = ExecResult()
    meter = None
    if not dry:
        meter = FreeSpaceMeter([i.path for i in plan_items])
        meter.begin()
    now = time.time()
    total = len(plan_items)
    for n, item in enumerate(plan_items, 1):
        if is_stop_requested(stop):
            res.notes.append("Interrupted")
            break
        if deadline is not None and time.monotonic() > deadline:
            res.notes.append("Timeout exceeded — remaining items skipped")
            break
        out = execute_item(item, guards, now=now, dry=dry, deadline=deadline, stop=stop)
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
        if out.reason == "Interrupted by user" or is_stop_requested(stop):
            if "Interrupted" not in res.notes:
                res.notes.append("Interrupted")
            break
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

def _win_file_is_locked(path: str) -> bool:
    """Windows: kiểm tra file (như Chromium 'lockfile') có đang bị giữ khóa độc quyền bởi tiến trình đang chạy không."""
    if not os.path.exists(path):
        return False
    if IS_WINDOWS:
        try:
            import ctypes
            GENERIC_READ = 0x80000000
            GENERIC_WRITE = 0x40000000
            OPEN_EXISTING = 3
            FILE_ATTRIBUTE_NORMAL = 0x80
            INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
            h = ctypes.windll.kernel32.CreateFileW(
                str(path), GENERIC_READ | GENERIC_WRITE, 0, None,
                OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None
            )
            if h == INVALID_HANDLE_VALUE or h == -1 or h == 0:
                err = ctypes.windll.kernel32.GetLastError()
                # ERROR_SHARING_VIOLATION (32) or ERROR_LOCK_VIOLATION (33) or ACCESS_DENIED (5)
                if err in (5, 32, 33):
                    return True
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return False
        except Exception:
            return False
    return False


def chromium_profile_in_use(user_data_dir: str) -> bool:
    """
    Linux: Chromium/Electron tạo symlink 'SingletonLock' → 'host-pid' khi đang chạy.
    Windows: Chromium/Electron tạo và giữ khóa OS trên file 'lockfile' trong user_data_dir.
    Lock còn nhưng pid đã chết (crash) = lock cũ → không tính là đang chạy.
    """
    lock = os.path.join(user_data_dir, "SingletonLock")
    try:
        target = os.readlink(lock)
    except OSError:
        target = None

    if target is not None:
        try:
            pid = int(target.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            return True            # không đọc được pid → coi như đang chạy (an toàn)
        try:
            import psutil
            if not psutil.pid_exists(pid):
                return False
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except ImportError:
            if pid <= 0:
                return False
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
        except Exception:
            return True

    win_lockfile = os.path.join(user_data_dir, "lockfile")
    if _win_file_is_locked(win_lockfile):
        return True
    return False


def iter_dir(path) -> List[os.DirEntry]:
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        return []
