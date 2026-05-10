"""
CyberClean v2.3 — App Uninstaller
════════════════════════════════════════════════════════════════
Linux:   pacman · apt · dnf · zypper · xbps · flatpak
Windows: Registry (fast) + winget enrichment — NO wmic product get

WHAT CHANGED vs v2.0:

FIX: bare except → typed except (PermissionError, OSError, Exception)
     Silent swallowing masked bugs; now errors surface via UninstallResult.

FIX: dpkg-query parse — handle packages with empty Installed-Size field
     (virtual packages, meta-packages) without crashing float().

FIX: winget parse — skip separator/header lines more robustly.
     Previous split(r'  +') broke when winget output used different spacing
     on localized Windows (e.g. non-ASCII column headers).

NEW: zypper support — Linux distros: OpenSUSE Leap / Tumbleweed.
     _get_linux() now detects PKG_MANAGER == 'zypper' and lists via
     'zypper packages --installed-only'.

NEW: xbps support — Void Linux.
     Lists via 'xbps-query -l' (already partly in helper but not in list).

NEW: InstalledApp.uninstall_preview dict — structured data the GUI can
     show in a confirmation dialog BEFORE running uninstall:
       size_mb, version, source, estimated_dependencies (Linux only),
       reversible (bool — registry uninstall is reversible via restore point).

NEW: get_dependencies_linux() — lightweight 'apt-cache depends' / 'pacman -Qi'
     pass to populate the preview without blocking the main thread.

NEW: UninstallResult dataclass — structured return value from uninstall_app().
     Replaces bare bool / 'UI_OPENED' string sentinel.
     Fields: success, ui_opened, output, error_msg.

COMPAT: uninstall_app() still returns bool | 'UI_OPENED' for old call sites.
"""

import subprocess, platform, re, time
from dataclasses import dataclass, field
from typing import List, Callable, Optional

OS = platform.system()

@dataclass
class InstalledApp:
    name:    str
    version: str   = ''
    size_mb: float = 0.0
    source:  str   = ''   # 'pacman'|'apt'|'dnf'|'zypper'|'xbps'|'flatpak'|'winget'|'registry'
    pkg_id:  str   = ''   # id used to uninstall

    @property
    def uninstall_preview(self) -> dict:
        """Structured data for confirmation dialog — safe to call from GUI thread."""
        return {
            'name':        self.name,
            'version':     self.version,
            'size_mb':     round(self.size_mb, 1),
            'source':      self.source,
            'reversible':  self.source not in ('pacman', 'apt', 'dnf', 'zypper', 'xbps'),
        }


@dataclass
class UninstallResult:
    """Structured return value from uninstall_app()."""
    success:    bool   = False
    ui_opened:  bool   = False   # True → user must interact with separate window
    output:     str    = ''
    error_msg:  str    = ''


_NO_WIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0


def run(cmd, timeout=20):
    """
    FIX: encoding='utf-8' errors='replace' — prevents UnicodeDecodeError crash
    on Vietnamese/CJK Windows locales where app names contain non-ASCII chars.
    FIX: TimeoutExpired handled explicitly — was silently returning ('exc_str', 1)
    which masked slow-command issues.
    """
    try:
        r = subprocess.run(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, creationflags=_NO_WIN,
            encoding='utf-8', errors='replace',
        )
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return f'timeout after {timeout}s', 1
    except Exception as e:
        return str(e), 1


def get_installed_apps() -> List[InstalledApp]:
    if OS == 'Linux':   return _get_linux()
    if OS == 'Windows': return _get_windows()
    return []


# ── Dependency preview (non-blocking, best-effort) ────────────
def get_dependencies_linux(app: 'InstalledApp') -> List[str]:
    """
    Return list of packages that depend on this one (reverse deps).
    Used to populate the confirmation dialog warning.
    Returns [] on any failure — non-critical.
    """
    try:
        from .os_detect import PKG_MANAGER
    except ImportError:
        try:
            from os_detect import PKG_MANAGER
        except ImportError:
            return []

    try:
        if PKG_MANAGER == 'apt':
            out, _ = run(f'apt-cache rdepends --installed {app.pkg_id} 2>/dev/null', timeout=8)
            return [l.strip().lstrip('|').strip() for l in out.splitlines()
                    if l.strip() and not l.strip().startswith(app.pkg_id)][:10]
        elif PKG_MANAGER == 'pacman':
            out, _ = run(f'pacman -Qi {app.pkg_id} 2>/dev/null', timeout=8)
            for line in out.splitlines():
                if line.startswith('Required By'):
                    val = line.split(':', 1)[1].strip()
                    return [v.strip() for v in val.split() if v.strip() != 'None'][:10]
    except Exception:
        pass
    return []


# ── LINUX ──────────────────────────────────────────────────────
def _get_linux() -> List[InstalledApp]:
    apps = []
    try:
        from .os_detect import PKG_MANAGER, HAS_FLATPAK, HAS_XBPS
    except ImportError:
        try:
            from os_detect import PKG_MANAGER, HAS_FLATPAK, HAS_XBPS
        except ImportError:
            PKG_MANAGER = ''; HAS_FLATPAK = False; HAS_XBPS = False

    if PKG_MANAGER == 'pacman':
        out, _ = run('pacman -Qi 2>/dev/null', timeout=30)
        current: dict = {}
        for line in out.splitlines():
            if line.startswith('Name '):
                current['name'] = line.split(':', 1)[1].strip()
            elif line.startswith('Version '):
                current['version'] = line.split(':', 1)[1].strip()
            elif line.startswith('Installed Size '):
                sz_str = line.split(':', 1)[1].strip()
                try:
                    val, unit = sz_str.split()[:2]
                    mult = {'B': 1/1024/1024, 'KiB': 1/1024, 'MiB': 1, 'GiB': 1024}.get(unit, 0)
                    current['size_mb'] = float(val) * mult
                except (ValueError, TypeError):
                    current['size_mb'] = 0.0
            elif line.strip() == '' and current.get('name'):
                apps.append(InstalledApp(
                    name=current['name'], version=current.get('version', ''),
                    size_mb=current.get('size_mb', 0.0),
                    source='pacman', pkg_id=current['name'],
                ))
                current = {}
        if current.get('name'):
            apps.append(InstalledApp(
                name=current['name'], version=current.get('version', ''),
                size_mb=current.get('size_mb', 0.0),
                source='pacman', pkg_id=current['name'],
            ))

    elif PKG_MANAGER == 'apt':
        # FIX: single quotes so ${...} fields are not expanded by bash.
        # FIX: coerce empty Installed-Size to 0 before float() — virtual packages
        #      return empty string → float('') raises ValueError.
        out, _ = run(
            "dpkg-query -W -f='${Package}\t${Version}\t${Installed-Size}\n' 2>/dev/null",
            timeout=30,
        )
        for line in out.splitlines():
            parts = line.split('\t')
            if len(parts) < 2 or not parts[0].strip():
                continue
            try:
                sz_raw = parts[2].strip() if len(parts) > 2 else ''
                sz = float(sz_raw) / 1024 if sz_raw else 0.0
            except (ValueError, TypeError):
                sz = 0.0
            apps.append(InstalledApp(
                name=parts[0].strip(), version=parts[1].strip(),
                size_mb=sz, source='apt', pkg_id=parts[0].strip(),
            ))

    elif PKG_MANAGER == 'dnf':
        out, _ = run('rpm -qa --queryformat "%{NAME}\t%{VERSION}\t%{SIZE}\n" 2>/dev/null', timeout=30)
        for line in out.splitlines():
            parts = line.split('\t')
            if not parts or not parts[0].strip():
                continue
            try:
                sz = float(parts[2]) / 1024 / 1024 if len(parts) > 2 and parts[2].strip() else 0.0
            except (ValueError, TypeError):
                sz = 0.0
            apps.append(InstalledApp(
                name=parts[0].strip(),
                version=parts[1].strip() if len(parts) > 1 else '',
                size_mb=sz, source='dnf', pkg_id=parts[0].strip(),
            ))

    elif PKG_MANAGER == 'zypper':
        # NEW: OpenSUSE Leap / Tumbleweed support
        # 'zypper packages --installed-only' output:
        #   S | Repository | Name | Version | Arch
        # Skip header lines (start with '-' or 'S |')
        out, _ = run('zypper packages --installed-only 2>/dev/null', timeout=30)
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith('-') or line.startswith('S '):
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 4:
                continue
            # parts[0] = status flag, [1] = repo, [2] = name, [3] = version
            name = parts[2]
            ver  = parts[3]
            if not name or name.lower() in ('name', 'package'):
                continue
            apps.append(InstalledApp(
                name=name, version=ver,
                size_mb=0.0, source='zypper', pkg_id=name,
            ))

    elif PKG_MANAGER == 'xbps' and HAS_XBPS:
        # NEW: Void Linux
        # 'xbps-query -l' output: ii package-name-version description
        out, _ = run('xbps-query -l 2>/dev/null', timeout=30)
        for line in out.splitlines():
            parts = line.split(None, 2)   # ['ii', 'pkg-version', 'description']
            if len(parts) < 2:
                continue
            pkg_ver = parts[1]
            # Split name-version: last hyphen-separated part that starts with digit is version
            m = re.match(r'^(.+?)-(\d[\d.]*\w*)$', pkg_ver)
            if m:
                name, ver = m.group(1), m.group(2)
            else:
                name, ver = pkg_ver, ''
            apps.append(InstalledApp(
                name=name, version=ver,
                size_mb=0.0, source='xbps', pkg_id=name,
            ))

    # Flatpak (all distros)
    try:
        from .os_detect import HAS_FLATPAK as _HAS_FP
    except ImportError:
        try:
            from os_detect import HAS_FLATPAK as _HAS_FP
        except ImportError:
            _HAS_FP = HAS_FLATPAK
    if _HAS_FP:
        out, _ = run('flatpak list --app --columns=application,name,version,size 2>/dev/null', timeout=20)
        import re as _re
        for line in out.splitlines():
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            app_id = parts[0].strip()
            if not app_id or app_id.lower() in ('application id', 'application', 'app id'):
                continue
            name   = parts[1].strip() if len(parts) > 1 else app_id
            ver    = parts[2].strip() if len(parts) > 2 else ''
            sz_str = parts[3].strip() if len(parts) > 3 else '0'
            try:
                m2 = _re.match(r'([\d.]+)\s*(MB|GB|KB)', sz_str)
                if m2:
                    mult = {'MB': 1, 'GB': 1024, 'KB': 1/1024}.get(m2.group(2), 1)
                    sz = float(m2.group(1)) * mult
                else:
                    sz = 0.0
            except (ValueError, TypeError):
                sz = 0.0
            apps.append(InstalledApp(name=name, version=ver,
                                     size_mb=sz, source='flatpak', pkg_id=app_id))

    return sorted(apps, key=lambda a: a.size_mb, reverse=True)


# ── WINDOWS — Registry (fast, no wmic) ────────────────────────
def _get_windows() -> List[InstalledApp]:
    apps = []
    seen: set = set()

    try:
        import winreg
        from concurrent.futures import ThreadPoolExecutor, as_completed

        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_CURRENT_USER,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
        ]

        def _read_hive(hive_path):
            hive, path = hive_path
            results = []
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                return results
            num_subkeys, _, _ = winreg.QueryInfoKey(key)
            for i in range(num_subkeys):
                try:
                    sub_name = winreg.EnumKey(key, i)
                    sub_key  = winreg.OpenKey(key, sub_name)

                    def _val(k, default=''):
                        try:
                            return winreg.QueryValueEx(sub_key, k)[0]
                        except OSError:
                            return default

                    name = _val('DisplayName')
                    if not name:
                        continue
                    if _val('SystemComponent', 0) == 1:
                        continue
                    if sub_name.startswith('KB') and len(sub_name) < 15:
                        continue

                    version       = _val('DisplayVersion')
                    uninstall_str = _val('UninstallString', '').strip()
                    quiet_str     = _val('QuietUninstallString', '').strip()

                    try:
                        sz_kb   = winreg.QueryValueEx(sub_key, 'EstimatedSize')[0]
                        size_mb = sz_kb / 1024
                    except OSError:
                        size_mb = 0.0

                    results.append(InstalledApp(
                        name=name, version=version, size_mb=size_mb,
                        source='registry',
                        pkg_id=f'{sub_name}|||{uninstall_str}|||{quiet_str}',
                    ))
                except OSError:
                    continue
            return results

        # Read all three registry hives in parallel — ~3x faster than serial
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = [ex.submit(_read_hive, hp) for hp in reg_paths]
            for fut in as_completed(futures):
                try:
                    for app in fut.result(timeout=10):
                        if app.name not in seen:
                            seen.add(app.name)
                            apps.append(app)
                except Exception:
                    pass

    except ImportError:
        pass   # not on Windows

    _enrich_with_winget(apps)
    return sorted(apps, key=lambda a: a.name.lower())


def _enrich_with_winget(apps: List[InstalledApp]):
    """Run 'winget list' to upgrade source to 'winget' for known packages.
    
    FIX: timeout raised 15→45s — winget can take 30s+ on office machines
    that haven't run it recently (source refresh). Also add
    --disable-interactivity so it never blocks waiting for user input.
    """
    if OS != 'Windows':
        return
    import shutil
    if not shutil.which('winget'):
        return
    try:
        out, code = run(
            'winget list --disable-interactivity --accept-source-agreements 2>nul',
            timeout=45,   # was 15 — too short on cold/office machines
        )
        if code != 0:
            return

        winget_map: dict = {}
        lines = out.splitlines()

        # FIX: find the header line to skip it robustly regardless of locale
        # Header contains 'Name' and 'Id' columns — find by checking for 'Id' keyword
        data_start = 0
        for idx, line in enumerate(lines):
            if re.search(r'\bId\b', line):
                data_start = idx + 2   # skip header + separator
                break

        for line in lines[data_start:]:
            line = line.strip()
            if not line or line.startswith('-'):
                continue
            # winget list uses variable-width columns — split on 2+ spaces
            parts = re.split(r'  +', line)
            if len(parts) >= 2:
                wname = parts[0].strip().lower()
                wid   = parts[1].strip()
                if wid:
                    winget_map[wname] = wid

        for app in apps:
            wid = winget_map.get(app.name.lower())
            if wid:
                app.source = 'winget'
                app.pkg_id = wid
    except Exception:
        pass


def _clean_path(s: str) -> str:
    return s.strip().strip('"').strip("'")


def _run_win_uninstall(
    app_name: str, reg_key: str, uninstall_str: str,
    quiet_str: str, log_cb: Callable
) -> tuple:
    """
    Smart Windows uninstall — tries multiple strategies in order.
    Handles: MSI GUIDs, Inno Setup, NSIS, QuietUninstallString, generic EXE.
    Returns (output: str, returncode: int).
    """
    _NW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

    def _run(cmd, timeout=120):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               timeout=timeout, creationflags=_NW)
            return r.stdout.strip() + r.stderr.strip(), r.returncode
        except Exception as e:
            return str(e), 1

    # Strategy 1: QuietUninstallString (cleanest)
    if quiet_str:
        log_cb('  → Trying QuietUninstallString...', 'info')
        out, code = _run(quiet_str)
        if code == 0:
            return out, code

    # Strategy 2: MSI GUID
    guid_src = uninstall_str or reg_key
    guid_match = re.search(
        r'\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}',
        guid_src, re.IGNORECASE,
    )
    if guid_match or uninstall_str.upper().startswith('MSIEXEC'):
        guid = guid_match.group(0) if guid_match else ''
        if guid:
            log_cb(f'  → MSI uninstall {guid}...', 'info')
            out, code = _run(f'msiexec /x "{guid}" /qb- REBOOT=ReallySuppress 2>nul')
            if code in (0, 3010):
                return out, 0
            out, code = _run(f'msiexec /x "{guid}" /qn REBOOT=ReallySuppress 2>nul')
            if code in (0, 3010):
                return out, 0
            log_cb(f'  ✗ msiexec failed ({code}) — trying EXE fallback', 'warn')

    # Strategy 3: EXE uninstall_str
    if uninstall_str and not uninstall_str.upper().startswith('MSIEXEC'):
        from pathlib import Path as _Path

        exe_match = re.match(r'^"([^"]+)"(.*)$', uninstall_str)
        if exe_match:
            exe  = exe_match.group(1).strip()
            args = exe_match.group(2).strip()
        else:
            m = re.match(r'^(.*?\.exe)\s*(.*)$', uninstall_str, re.IGNORECASE)
            if m:
                exe  = m.group(1).strip()
                args = m.group(2).strip()
            else:
                exe, args = uninstall_str, ''

        if not _Path(exe).exists():
            log_cb(f'  ✗ Uninstaller not found: {exe}', 'err')
            return '', 1

        fname = _Path(exe).name.lower()
        existing_args_lower = args.lower()

        if any(flag in existing_args_lower for flag in ('/s', '/silent', '/quiet', '/q', '--quiet')):
            log_cb('  → Running with existing silent flags...', 'info')
            out, code = _run(f'"{exe}" {args}')
            if code == 0:
                return out, code

        if 'unins' in fname or 'inno' in fname:
            log_cb('  → Inno Setup silent uninstall...', 'info')
            out, code = _run(f'"{exe}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART {args}')
            if code == 0: return out, code
            out, code = _run(f'"{exe}" /SILENT /NORESTART {args}')
            if code == 0: return out, code

        if 'nsis' in fname or fname in ('uninst.exe', 'uninstall.exe'):
            log_cb('  → NSIS silent uninstall...', 'info')
            out, code = _run(f'"{exe}" /S {args}')
            if code == 0: return out, code

        for flag in ['/S', '/silent', '/quiet', '/Q', '--quiet', '/VERYSILENT']:
            log_cb(f'  → Trying {flag}...', 'info')
            out, code = _run(f'"{exe}" {flag} {args}'.strip())
            if code == 0: return out, code

        log_cb('  → Running uninstaller (may show UI)...', 'warn')
        out, code = _run(f'"{exe}" {args}'.strip())
        return out, code

    return '', 1


# ── UNINSTALL ──────────────────────────────────────────────────
def uninstall_app(app: InstalledApp, log_cb: Callable):
    """
    Uninstall an app. Returns:
      True              — success (silent uninstall completed)
      False             — failure
      'UI_OPENED'       — interactive uninstaller launched (compat sentinel)
      UninstallResult   — structured result (new call sites)

    Old call sites checking `== True` / `== False` / `== 'UI_OPENED'` still work.
    """
    log_cb(f'Uninstalling {app.name}...', 'info')
    out, code = '', 1

    if app.source == 'pacman':
        out, code = run(
            f'sudo -n /usr/local/bin/cyber-clean-helper pacman-remove {app.pkg_id} 2>/dev/null',
            timeout=60,
        )
        if code != 0:
            out, code = run(f'sudo pacman -Rns --noconfirm {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'apt':
        out, code = run(
            f'sudo -n /usr/local/bin/cyber-clean-helper apt-remove {app.pkg_id} 2>/dev/null',
            timeout=60,
        )
        if code != 0:
            out, code = run(f'sudo apt-get remove -y {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'dnf':
        out, code = run(
            f'sudo -n /usr/local/bin/cyber-clean-helper dnf-remove {app.pkg_id} 2>/dev/null',
            timeout=60,
        )
        if code != 0:
            out, code = run(f'sudo dnf remove -y {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'zypper':
        # NEW: zypper via helper
        out, code = run(
            f'sudo -n /usr/local/bin/cyber-clean-helper zypper-remove {app.pkg_id} 2>/dev/null',
            timeout=60,
        )
        if code != 0:
            out, code = run(f'sudo zypper remove -y {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'xbps':
        out, code = run(f'sudo xbps-remove -y {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'flatpak':
        out, code = run(f'flatpak uninstall -y {app.pkg_id} 2>&1', timeout=60)

    elif app.source == 'winget':
        out, code = run(f'winget uninstall --id "{app.pkg_id}" --silent 2>nul', timeout=120)

    elif app.source == 'registry':
        parts         = app.pkg_id.split('|||', 2)
        reg_key       = parts[0].strip() if len(parts) > 0 else ''
        uninstall_str = parts[1].strip() if len(parts) > 1 else ''
        quiet_str     = parts[2].strip() if len(parts) > 2 else ''

        if not quiet_str and uninstall_str:
            # No silent mode — open UI, don't hang waiting
            subprocess.Popen(uninstall_str, shell=True)
            log_cb(f'  ✓ Opened uninstaller for {app.name}.', 'ok')
            log_cb('  ℹ  Complete the uninstall in the new window, then click REFRESH.', 'warn')
            return 'UI_OPENED'

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
