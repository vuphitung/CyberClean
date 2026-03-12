"""
CyberClean v2.0 — App Uninstaller
Linux: pacman / apt / dnf / flatpak
Windows: Registry (fast) + winget fallback — NO wmic product get (kills CPU)
"""
import subprocess, platform, re
from dataclasses import dataclass, field
from typing import List, Callable

OS = platform.system()

@dataclass
class InstalledApp:
    name:    str
    version: str   = ''
    size_mb: float = 0.0
    source:  str   = ''   # 'pacman'|'apt'|'flatpak'|'winget'|'registry'
    pkg_id:  str   = ''   # id used to uninstall

_NO_WIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, creationflags=_NO_WIN)
        return r.stdout.strip(), r.returncode
    except:
        return '', 1

def get_installed_apps() -> List[InstalledApp]:
    if OS == 'Linux':   return _get_linux()
    if OS == 'Windows': return _get_windows()
    return []

# ── LINUX ─────────────────────────────────────────────────────
def _get_linux() -> List[InstalledApp]:
    apps = []
    from .os_detect import PKG_MANAGER

    if PKG_MANAGER == 'pacman':
        out, _ = run('pacman -Qi 2>/dev/null')
        current = {}
        for line in out.splitlines():
            if line.startswith('Name '):
                current['name'] = line.split(':', 1)[1].strip()
            elif line.startswith('Version '):
                current['version'] = line.split(':', 1)[1].strip()
            elif line.startswith('Installed Size '):
                sz_str = line.split(':', 1)[1].strip()
                try:
                    val, unit = sz_str.split()[:2]
                    mult = {'B':1/1024/1024,'KiB':1/1024,'MiB':1,'GiB':1024}.get(unit, 0)
                    current['size_mb'] = float(val) * mult
                except: current['size_mb'] = 0.0
            elif line.strip() == '' and current.get('name'):
                apps.append(InstalledApp(name=current['name'],
                    version=current.get('version',''), size_mb=current.get('size_mb',0.0),
                    source='pacman', pkg_id=current['name']))
                current = {}
        if current.get('name'):
            apps.append(InstalledApp(name=current['name'],
                version=current.get('version',''), size_mb=current.get('size_mb',0.0),
                source='pacman', pkg_id=current['name']))

    elif PKG_MANAGER == 'apt':
        out, _ = run('dpkg-query -W -f="${Package}\t${Version}\t${Installed-Size}\n" 2>/dev/null')
        for line in out.splitlines():
            parts = line.split('\t')
            if len(parts) >= 2:
                try: sz = float(parts[2]) / 1024 if len(parts) > 2 else 0.0
                except: sz = 0.0
                apps.append(InstalledApp(name=parts[0], version=parts[1],
                    size_mb=sz, source='apt', pkg_id=parts[0]))

    elif PKG_MANAGER == 'dnf':
        out, _ = run('rpm -qa --queryformat "%{NAME}\t%{VERSION}\t%{SIZE}\n" 2>/dev/null')
        for line in out.splitlines():
            parts = line.split('\t')
            if len(parts) >= 1:
                try: sz = float(parts[2]) / 1024 / 1024 if len(parts) > 2 else 0.0
                except: sz = 0.0
                apps.append(InstalledApp(name=parts[0], version=parts[1] if len(parts)>1 else '',
                    size_mb=sz, source='dnf', pkg_id=parts[0]))

    from .os_detect import HAS_FLATPAK
    if HAS_FLATPAK:
        out, _ = run('flatpak list --app --columns=application,name,version,size 2>/dev/null')
        for line in out.splitlines():
            parts = line.split('\t')
            if len(parts) < 2: continue
            app_id = parts[0].strip()
            # Skip the header line (app_id column header is literally "Application ID")
            if not app_id or app_id.lower() in ('application id', 'application', 'app id'):
                continue
            name   = parts[1].strip() if len(parts) > 1 else app_id
            ver    = parts[2].strip() if len(parts) > 2 else ''
            sz_str = parts[3].strip() if len(parts) > 3 else '0'
            try:
                m = re.match(r'([\d.]+)\s*(MB|GB|KB)', sz_str)
                mult = {'MB':1,'GB':1024,'KB':1/1024}.get(m.group(2), 1) if m else 1
                sz = float(m.group(1)) * mult if m else 0.0
            except: sz = 0.0
            apps.append(InstalledApp(name=name, version=ver,
                size_mb=sz, source='flatpak', pkg_id=app_id))

    return sorted(apps, key=lambda a: a.size_mb, reverse=True)

# ── WINDOWS — Registry (fast) ─────────────────────────────────
def _get_windows() -> List[InstalledApp]:
    """
    Read from Registry directly — ~100x faster than 'wmic product get'
    which triggers MSI repair/verification on every call and kills CPU.
    """
    apps = []
    seen = set()

    try:
        import winreg

        reg_paths = [
            # 64-bit apps
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
            # 32-bit apps on 64-bit Windows
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
            # Per-user installs
            (winreg.HKEY_CURRENT_USER,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
        ]

        for hive, path in reg_paths:
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                continue
            num_subkeys, _, _ = winreg.QueryInfoKey(key)
            for i in range(num_subkeys):
                try:
                    sub_name = winreg.EnumKey(key, i)
                    sub_key  = winreg.OpenKey(key, sub_name)

                    def _val(k, default=''):
                        try: return winreg.QueryValueEx(sub_key, k)[0]
                        except: return default

                    name = _val('DisplayName')
                    if not name or name in seen:
                        continue
                    # Skip Windows system components and updates
                    if _val('SystemComponent', 0) == 1:
                        continue
                    if sub_name.startswith('KB') and len(sub_name) < 15:
                        continue  # skip hotfix entries like KB1234567

                    version         = _val('DisplayVersion')
                    uninstall_str   = _val('UninstallString', '').strip()
                    quiet_str       = _val('QuietUninstallString', '').strip()

                    # Size: EstimatedSize is in KB
                    try:
                        sz_kb   = winreg.QueryValueEx(sub_key, 'EstimatedSize')[0]
                        size_mb = sz_kb / 1024
                    except:
                        size_mb = 0.0

                    seen.add(name)
                    apps.append(InstalledApp(
                        name=name, version=version,
                        size_mb=size_mb, source='registry',
                        # pkg_id encodes: "regkey|||uninstall_str|||quiet_str"
                        # uninstall_app() splits these back out
                        pkg_id=f'{sub_name}|||{uninstall_str}|||{quiet_str}',
                    ))
                except OSError:
                    continue
    except ImportError:
        pass   # not on Windows, winreg unavailable

    # Also try winget for apps it knows about (adds pkg_id for cleaner uninstall)
    _enrich_with_winget(apps)

    return sorted(apps, key=lambda a: a.name.lower())


def _enrich_with_winget(apps: List[InstalledApp]):
    """
    Run 'winget list' to get proper winget IDs — Windows only.
    Skipped entirely on Linux. Checks winget exists before calling.
    """
    if OS != 'Windows':
        return
    import shutil
    if not shutil.which('winget'):
        return
    try:
        out, code = run('winget list 2>nul', timeout=15)
        if code != 0:
            return
        winget_map = {}
        for line in out.splitlines()[2:]:
            if not line.strip() or line.startswith('-'):
                continue
            parts = re.split(r'  +', line.strip())
            if len(parts) >= 2:
                wname = parts[0].strip().lower()
                wid   = parts[1].strip()
                winget_map[wname] = wid

        for app in apps:
            wid = winget_map.get(app.name.lower())
            if wid:
                app.source = 'winget'
                app.pkg_id = wid
    except:
        pass


def _clean_path(s: str) -> str:
    """Strip surrounding quotes from a path string."""
    return s.strip().strip('"').strip("'")

def _run_win_uninstall(app_name: str, reg_key: str, uninstall_str: str,
                       quiet_str: str, log_cb: Callable):
    """
    Smart Windows uninstall — tries multiple strategies in order.
    Handles: MSI GUIDs, EXE silent flags, QuietUninstallString, Inno Setup, NSIS, etc.
    """
    _NO_WIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

    def _run(cmd, timeout=120):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               timeout=timeout, creationflags=_NO_WIN)
            return r.stdout.strip() + r.stderr.strip(), r.returncode
        except Exception as e:
            return str(e), 1

    # ── Strategy 1: QuietUninstallString (cleanest — app provides this) ──
    if quiet_str:
        log_cb(f'  → Trying QuietUninstallString...', 'info')
        out, code = _run(quiet_str)
        if code == 0: return out, code

    # ── Strategy 2: MSI-based (msiexec) ──────────────────────────────────
    # Extract GUID from uninstall_str OR reg_key
    guid_src = uninstall_str or reg_key
    guid_match = re.search(r'\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}',
                           guid_src, re.IGNORECASE)
    if guid_match or (uninstall_str.upper().startswith('MSIEXEC')):
        guid = guid_match.group(0) if guid_match else ''
        if guid:
            log_cb(f'  → MSI uninstall {guid}...', 'info')
            # /qb- = progress bar, no cancel button (more compatible than /qn)
            out, code = _run(f'msiexec /x "{guid}" /qb- REBOOT=ReallySuppress 2>nul')
            if code in (0, 3010):   # 3010 = success, restart required
                return out, 0
            # Retry with /qn (fully silent) — some apps need this
            out, code = _run(f'msiexec /x "{guid}" /qn REBOOT=ReallySuppress 2>nul')
            if code in (0, 3010):
                return out, 0
            log_cb(f'  ✗ msiexec failed (code {code}) — trying EXE fallback', 'warn')

    # ── Strategy 3: EXE-based uninstall_str ──────────────────────────────
    if uninstall_str and not uninstall_str.upper().startswith('MSIEXEC'):
        # Parse: separate executable from its arguments
        # Handles: "C:\path\unins000.exe" /arg   OR   C:\path\unins000.exe /arg
        exe_match = re.match(r'^"([^"]+)"(.*)$', uninstall_str)
        if exe_match:
            exe  = exe_match.group(1).strip()
            args = exe_match.group(2).strip()
        else:
            # No quotes — split on first .exe
            m = re.match(r'^(.*?\.exe)\s*(.*)$', uninstall_str, re.IGNORECASE)
            if m:
                exe  = m.group(1).strip()
                args = m.group(2).strip()
            else:
                exe, args = uninstall_str, ''

        from pathlib import Path as _Path
        if not _Path(exe).exists():
            log_cb(f'  ✗ Uninstaller not found: {exe}', 'err')
            return '', 1

        # Detect installer type from filename / existing args
        fname = _Path(exe).name.lower()
        existing_args_lower = args.lower()

        # Already has silent flag — run as-is first
        if any(flag in existing_args_lower for flag in ('/s', '/silent', '/quiet', '/q', '--quiet')):
            log_cb(f'  → Running with existing silent flags...', 'info')
            out, code = _run(f'"{exe}" {args}')
            if code == 0: return out, code

        # Inno Setup (unins000.exe or contains /VERYSILENT in registry)
        if 'unins' in fname or 'inno' in fname:
            log_cb(f'  → Inno Setup silent uninstall...', 'info')
            out, code = _run(f'"{exe}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART {args}')
            if code == 0: return out, code
            out, code = _run(f'"{exe}" /SILENT /NORESTART {args}')
            if code == 0: return out, code

        # NSIS (makensis) — common flag is /S
        if 'nsis' in fname or fname.endswith('uninst.exe') or fname.endswith('uninstall.exe'):
            log_cb(f'  → NSIS silent uninstall...', 'info')
            out, code = _run(f'"{exe}" /S {args}')
            if code == 0: return out, code

        # Generic silent flag attempts
        for flag in ['/S', '/silent', '/quiet', '/Q', '--quiet', '/VERYSILENT']:
            log_cb(f'  → Trying {flag}...', 'info')
            out, code = _run(f'"{exe}" {flag} {args}'.strip())
            if code == 0: return out, code

        # Last resort: run with original args (may show UI — user can interact)
        log_cb(f'  → Running uninstaller (may show UI)...', 'warn')
        out, code = _run(f'"{exe}" {args}'.strip())
        return out, code

    return '', 1


# ── UNINSTALL ─────────────────────────────────────────────────
def uninstall_app(app: InstalledApp, log_cb: Callable) -> bool:
    log_cb(f'Uninstalling {app.name}...', 'info')

    if app.source == 'pacman':
        out, code = run(f'sudo -n /usr/local/bin/cyber-clean-helper pacman-remove {app.pkg_id} 2>/dev/null', timeout=60)
        if code != 0:
            out, code = run(f'sudo pacman -Rns --noconfirm {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'apt':
        out, code = run(f'sudo -n apt-get remove -y {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'dnf':
        out, code = run(f'sudo -n dnf remove -y {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'flatpak':
        out, code = run(f'flatpak uninstall -y {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'winget':
        out, code = run(f'winget uninstall --id "{app.pkg_id}" --silent 2>nul', timeout=120)

    elif app.source == 'registry':
        # pkg_id format: "regkey|||uninstall_str|||quiet_str"
        parts = app.pkg_id.split('|||', 2)
        reg_key      = parts[0].strip() if len(parts) > 0 else ''
        uninstall_str = parts[1].strip() if len(parts) > 1 else ''
        quiet_str     = parts[2].strip() if len(parts) > 2 else ''

        out, code = _run_win_uninstall(app.name, reg_key, uninstall_str, quiet_str, log_cb)
    else:
        log_cb(f'  ✗ Unknown source: {app.source}', 'err')
        return False

    if code == 0:
        log_cb(f'  ✓ Uninstalled {app.name}', 'ok')
        return True
    else:
        log_cb(f'  ✗ Failed ({code}): {out[:200]}', 'err')
        return False
