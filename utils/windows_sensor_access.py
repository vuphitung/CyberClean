"""PawnIO driver detection, SHA-256 verification, and installation for Windows CPU temperature."""
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

PAWNIO_VERSION = '2.2.0'
PAWNIO_FILENAME = 'PawnIO_setup.exe'
PAWNIO_URL = 'https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe'
PAWNIO_HOMEPAGE = 'https://pawnio.eu/'
PAWNIO_SHA256 = '1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032'
PAWNIO_SILENT_ARGS = ('-install', '-silent')
ERROR_SUCCESS_REBOOT_REQUIRED = 3010
_MAX_INSTALLER_BYTES = 16 * 1024 * 1024
_VERSION_RE = re.compile(r'^\d+\.\d+(?:\.\d+){0,2}$')
_WINDOWS_EPOCH_OFFSET_100NS = 116444736000000000


class PawnIOInstallStatus(str, Enum):
    INSTALLED = 'installed'
    REBOOT_REQUIRED = 'reboot_required'


@dataclass(frozen=True)
class PawnIOInstallResult:
    status: PawnIOInstallStatus
    exit_code: int
    installer_path: Path

    @property
    def reboot_required(self) -> bool:
        return self.status == PawnIOInstallStatus.REBOOT_REQUIRED

    def __bool__(self) -> bool:
        return self.status in (
            PawnIOInstallStatus.INSTALLED,
            PawnIOInstallStatus.REBOOT_REQUIRED,
        )


class PawnIOStatus(str, Enum):
    NOT_INSTALLED = 'not_installed'
    REBOOT_REQUIRED = 'reboot_required'
    DRIVER_UNAVAILABLE = 'driver_unavailable'
    ACCESS_DENIED = 'access_denied'
    READY = 'ready'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class PawnIOState:
    status: PawnIOStatus
    installed: bool
    version: str | None = None
    access_error: int | None = None

    @property
    def reboot_required(self) -> bool:
        return self.status == PawnIOStatus.REBOOT_REQUIRED


def _is_current_process_admin() -> bool:
    if sys.platform != 'win32':
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _program_files_roots() -> list[Path]:
    roots = []
    for key in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)'):
        val = os.environ.get(key)
        if val:
            p = Path(val)
            if p not in roots:
                roots.append(p)
    return roots


def parse_pawnio_version(raw_version: str | None) -> str | None:
    """Validate DisplayVersion using the same Version semantics as LibreHardwareMonitor's PawnIo.cs."""
    if not raw_version or not isinstance(raw_version, str):
        return None
    cleaned = raw_version.strip()
    if not _VERSION_RE.match(cleaned):
        return None
    parts = cleaned.split('.')
    try:
        nums = [int(part) for part in parts]
    except ValueError:
        return None
    if any(n < 0 for n in nums) or len(nums) < 2 or len(nums) > 4:
        return None
    return '.'.join(str(n) for n in nums)


def read_pawnio_version() -> str | None:
    """Read and validate PawnIO's DisplayVersion from HKLM Uninstall registry (64-bit & default view)."""
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        subkey = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO'
        views = (
            getattr(winreg, 'KEY_READ', 0x20019) | getattr(winreg, 'KEY_WOW64_64KEY', 0x0100),
            getattr(winreg, 'KEY_READ', 0x20019),
        )
        for flags in views:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0, flags) as key:
                    raw, _ = winreg.QueryValueEx(key, 'DisplayVersion')
                    parsed = parse_pawnio_version(raw if isinstance(raw, str) else str(raw))
                    if parsed is not None:
                        return parsed
            except OSError:
                continue
    except ImportError:
        pass
    return None


def _read_pawnio_key_write_time_epoch() -> float | None:
    """Return the last-modified Unix timestamp of the PawnIO Uninstall registry key, if available."""
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        query_info = getattr(winreg, 'QueryInfoKey', None)
        if query_info is None:
            return None
        subkey = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO'
        views = (
            getattr(winreg, 'KEY_READ', 0x20019) | getattr(winreg, 'KEY_WOW64_64KEY', 0x0100),
            getattr(winreg, 'KEY_READ', 0x20019),
        )
        for flags in views:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0, flags) as key:
                    info = query_info(key)
                    if isinstance(info, tuple) and len(info) >= 3 and isinstance(info[2], int) and info[2] > 0:
                        return (info[2] - _WINDOWS_EPOCH_OFFSET_100NS) / 10_000_000.0
            except OSError:
                continue
    except Exception:
        pass
    return None


def _system_boot_time_epoch() -> float | None:
    """Return the system boot Unix timestamp in seconds, if available."""
    if os.name == 'nt':
        try:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            get_tick = kernel.GetTickCount64
            get_tick.argtypes = []
            get_tick.restype = ctypes.c_uint64
            uptime_sec = float(get_tick()) / 1000.0
            if uptime_sec > 0:
                return time.time() - uptime_sec
        except Exception:
            pass
    try:
        import psutil
        return float(psutil.boot_time())
    except Exception:
        return None


def _was_pawnio_installed_before_boot() -> bool:
    """Return True if PawnIO's registry key last-write timestamp predates the current OS boot."""
    key_mtime = _read_pawnio_key_write_time_epoch()
    boot_time = _system_boot_time_epoch()
    if key_mtime is None or boot_time is None:
        return False
    return key_mtime < (boot_time - 5.0)


def _probe_pawnio_device_error() -> int | None:
    """Attempt to open `\\\\?\\GLOBALROOT\\Device\\PawnIO` and return 0 on success or Win32 error code."""
    if os.name != 'nt':
        return None
    try:
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = create(r'\\?\GLOBALROOT\Device\PawnIO', 0xC0000000, 3, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            return int(ctypes.get_last_error())
        kernel.CloseHandle(handle)
        return 0
    except Exception:
        return None


def probe_pawnio_state() -> PawnIOState:
    """Return a structured state diagnosis of PawnIO matching LibreHardwareMonitor's PawnIo.cs."""
    version = read_pawnio_version()
    if version is None:
        return PawnIOState(
            status=PawnIOStatus.NOT_INSTALLED,
            installed=False,
            version=None,
            access_error=None,
        )
    err = _probe_pawnio_device_error()
    if err is None:
        return PawnIOState(
            status=PawnIOStatus.UNKNOWN,
            installed=True,
            version=version,
            access_error=None,
        )
    if err == 0:
        return PawnIOState(
            status=PawnIOStatus.READY,
            installed=True,
            version=version,
            access_error=None,
        )
    if err == 5:
        return PawnIOState(
            status=PawnIOStatus.ACCESS_DENIED,
            installed=True,
            version=version,
            access_error=5,
        )
    if err in (2, 3):
        if _was_pawnio_installed_before_boot():
            return PawnIOState(
                status=PawnIOStatus.DRIVER_UNAVAILABLE,
                installed=True,
                version=version,
                access_error=err,
            )
        return PawnIOState(
            status=PawnIOStatus.REBOOT_REQUIRED,
            installed=True,
            version=version,
            access_error=err,
        )
    return PawnIOState(
        status=PawnIOStatus.DRIVER_UNAVAILABLE,
        installed=True,
        version=version,
        access_error=err,
    )


def is_pawnio_installed() -> bool:
    """Return True iff PawnIO has a valid DisplayVersion in HKLM, matching LHM's PawnIo.IsInstalled."""
    return read_pawnio_version() is not None


def verify_file_sha256(path: Path, expected_sha256: str = PAWNIO_SHA256) -> bool:
    """Return True iff `path` exists as a regular file matching `expected_sha256`."""
    if not expected_sha256:
        return False
    try:
        p = Path(path)
        if p.is_symlink() or not p.is_file():
            return False
        digest = hashlib.sha256()
        with p.open('rb') as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
        return hmac.compare_digest(digest.hexdigest().lower(), expected_sha256.lower())
    except OSError:
        return False


@contextmanager
def _lock_verified_executable(path: Path, expected_sha256: str = PAWNIO_SHA256):
    """Hold a read-only lock on `path` while verifying SHA-256 and launching."""
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise ValueError('Verified PawnIO_setup.exe installer is unavailable or failed SHA-256 check')

    win_handle = None
    kernel = None
    py_file = None
    try:
        if os.name == 'nt':
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
            ]
            create.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = create(str(p), 0x80000000, 0x00000001, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            win_handle = handle

        py_file = p.open('rb')
        digest = hashlib.sha256()
        while True:
            chunk = py_file.read(65536)
            if not chunk:
                break
            digest.update(chunk)
        if not hmac.compare_digest(digest.hexdigest().lower(), expected_sha256.lower()):
            raise ValueError('Verified PawnIO_setup.exe installer is unavailable or failed SHA-256 check')
        yield p.resolve()
    finally:
        if py_file is not None:
            try:
                py_file.close()
            except OSError:
                pass
        if win_handle is not None and kernel is not None:
            try:
                kernel.CloseHandle(win_handle)
            except Exception:
                pass


def find_pawnio_installer(expected_sha256: str = PAWNIO_SHA256) -> Path | None:
    """Locate a bundled PawnIO_setup.exe and verify its SHA-256 hash."""
    candidates = []
    if getattr(sys, 'frozen', False) and getattr(sys, 'executable', None):
        exe_parent = Path(sys.executable).parent
        candidates.append(exe_parent / PAWNIO_FILENAME)
        candidates.append(exe_parent / 'vendor' / 'lhm' / PAWNIO_FILENAME)
        candidates.append(exe_parent / '_internal' / 'vendor' / 'lhm' / PAWNIO_FILENAME)
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(Path(meipass) / 'vendor' / 'lhm' / PAWNIO_FILENAME)
    repo_root = Path(__file__).resolve().parents[1]
    candidates.append(repo_root / 'vendor' / 'lhm' / PAWNIO_FILENAME)
    for pf_root in _program_files_roots():
        candidates.append(pf_root / 'CyberClean' / PAWNIO_FILENAME)
        candidates.append(pf_root / 'CyberClean' / 'vendor' / 'lhm' / PAWNIO_FILENAME)

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if verify_file_sha256(candidate, expected_sha256):
            return candidate.resolve()
    return None


def download_pawnio_installer(
    dest_path: Path | None = None,
    *,
    url: str = PAWNIO_URL,
    expected_sha256: str = PAWNIO_SHA256,
    timeout: float = 30.0,
) -> Path:
    """Download the official PawnIO_setup.exe and verify its pinned SHA-256."""
    created_temp_dir = None
    if dest_path is None:
        created_temp_dir = Path(tempfile.mkdtemp(prefix='cyberclean-pawnio-'))
        target = created_temp_dir / PAWNIO_FILENAME
    else:
        target = Path(dest_path)
        target.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    total = 0
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'CyberClean-SensorSetup/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp, target.open('wb') as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_INSTALLER_BYTES:
                    raise ValueError('PawnIO installer download exceeded maximum size')
                digest.update(chunk)
                out.write(chunk)
        if not hmac.compare_digest(digest.hexdigest().lower(), expected_sha256.lower()):
            raise ValueError('PawnIO installer SHA-256 verification failed')
        return target.resolve()
    except BaseException:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        if created_temp_dir is not None:
            shutil.rmtree(created_temp_dir, ignore_errors=True)
        raise


class _WindowsProcess:
    def __init__(self, handle):
        from ctypes import wintypes
        self.handle = handle
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetExitCodeProcess.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def poll(self):
        from ctypes import wintypes
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return None if code.value == 259 else int(code.value)

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            code = self.poll()
            if code is not None:
                return code
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(PAWNIO_FILENAME, timeout)
            time.sleep(.05)

    def close_handle(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _shell_execute(command):
    """Run an installer command with UAC elevation (`runas`) when the parent is not already Admin."""
    from ctypes import wintypes

    class ExecuteInfo(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
            ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR),
            ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR),
            ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
            ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR),
            ('hkeyClass', wintypes.HKEY), ('dwHotKey', wintypes.DWORD),
            ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE),
        ]

    request = ExecuteInfo()
    request.cbSize = ctypes.sizeof(request)
    request.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS
    request.lpVerb = 'runas'
    request.lpFile = command[0]
    request.lpParameters = subprocess.list2cmdline(command[1:])
    request.lpDirectory = str(Path(command[0]).parent)
    request.nShow = 1
    shell = ctypes.WinDLL('shell32', use_last_error=True).ShellExecuteExW
    shell.argtypes = [ctypes.POINTER(ExecuteInfo)]
    shell.restype = wintypes.BOOL
    if not shell(ctypes.byref(request)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not request.hProcess:
        raise OSError('Windows returned no installer process handle')
    return _WindowsProcess(request.hProcess)


def install_pawnio_driver(
    *,
    installer_path: Path | None = None,
    allow_download: bool = True,
    silent: bool = True,
    launch=None,
    timeout: float = 120.0,
) -> PawnIOInstallResult:
    """Verify and run the official PawnIO installer.

    Handles both `0` (`INSTALLED`) and `3010` (`ERROR_SUCCESS_REBOOT_REQUIRED`),
    locks the installer against concurrent modification during launch, and
    always cleans up any temporary downloaded installer in `finally`.
    """
    if sys.platform != 'win32':
        raise OSError('PawnIO driver installation is only supported on Windows')

    downloaded_temp: Path | None = None
    proc = None
    try:
        if installer_path is not None:
            installer = Path(installer_path)
        else:
            installer = find_pawnio_installer(PAWNIO_SHA256)
            if installer is None and allow_download:
                downloaded_temp = download_pawnio_installer(expected_sha256=PAWNIO_SHA256)
                installer = downloaded_temp
        if installer is None:
            raise ValueError('Verified PawnIO_setup.exe installer is unavailable or failed SHA-256 check')

        with _lock_verified_executable(installer, PAWNIO_SHA256) as locked_installer:
            args = list(PAWNIO_SILENT_ARGS) if silent else ['-install']
            command = [str(locked_installer), *args]
            if launch is not None:
                proc = launch(command)
            elif _is_current_process_admin():
                proc = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
            else:
                proc = _shell_execute(command)

            try:
                exit_code = int(proc.wait(timeout=timeout))
            finally:
                if hasattr(proc, 'close_handle'):
                    try:
                        proc.close_handle()
                    except Exception:
                        pass

        if exit_code == 0:
            return PawnIOInstallResult(PawnIOInstallStatus.INSTALLED, 0, locked_installer)
        if exit_code == ERROR_SUCCESS_REBOOT_REQUIRED:
            return PawnIOInstallResult(
                PawnIOInstallStatus.REBOOT_REQUIRED,
                ERROR_SUCCESS_REBOOT_REQUIRED,
                locked_installer,
            )
        raise RuntimeError(f'PawnIO installer exited with code {exit_code}')
    finally:
        if downloaded_temp is not None:
            try:
                downloaded_temp.unlink(missing_ok=True)
            except OSError:
                pass
            if downloaded_temp.parent.name.startswith('cyberclean-pawnio-'):
                shutil.rmtree(downloaded_temp.parent, ignore_errors=True)
