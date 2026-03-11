"""
CyberClean v2.0 — App Uninstaller
Linux: pacman / apt / dnf / flatpak / snap
Windows: winget / wmic uninstall
"""
import subprocess, platform, re
from dataclasses import dataclass, field
from typing import List, Callable

OS = platform.system()

@dataclass
class InstalledApp:
    name:     str
    version:  str  = ''
    size_mb:  float = 0.0
    source:   str  = ''   # 'pacman' | 'apt' | 'flatpak' | 'snap' | 'winget'
    pkg_id:   str  = ''   # actual package id used to uninstall

def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except: return '', 1

def get_installed_apps() -> List[InstalledApp]:
    if OS == 'Linux':   return _get_linux()
    if OS == 'Windows': return _get_windows()
    return []

def _get_linux() -> List[InstalledApp]:
    apps = []
    from .os_detect import PKG_MANAGER

    if PKG_MANAGER == 'pacman':
        out, _ = run('pacman -Qi 2>/dev/null')
        # Parse pacman -Qi blocks
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
                    mult = {'B':1/1024/1024,'KiB':1/1024,'MiB':1,'GiB':1024}.get(unit, 1/1024/1024)
                    current['size_mb'] = float(val) * mult
                except: current['size_mb'] = 0.0
            elif line.strip() == '' and current.get('name'):
                apps.append(InstalledApp(
                    name=current['name'], version=current.get('version',''),
                    size_mb=current.get('size_mb',0.0),
                    source='pacman', pkg_id=current['name']))
                current = {}
        if current.get('name'):
            apps.append(InstalledApp(name=current['name'], version=current.get('version',''),
                size_mb=current.get('size_mb',0.0), source='pacman', pkg_id=current['name']))

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

    # Flatpak
    from .os_detect import HAS_FLATPAK
    if HAS_FLATPAK:
        out, _ = run('flatpak list --app --columns=application,name,version,size 2>/dev/null')
        for line in out.splitlines()[1:]:  # skip header
            parts = line.split('\t')
            if len(parts) >= 2:
                app_id = parts[0].strip()
                name   = parts[1].strip() if len(parts) > 1 else app_id
                ver    = parts[2].strip() if len(parts) > 2 else ''
                sz_str = parts[3].strip() if len(parts) > 3 else '0'
                try:
                    m = re.match(r'([\d.]+)\s*(MB|GB|KB)', sz_str)
                    mult = {'MB':1,'GB':1024,'KB':1/1024}.get(m.group(2),1) if m else 1
                    sz   = float(m.group(1)) * mult if m else 0.0
                except: sz = 0.0
                apps.append(InstalledApp(name=name, version=ver,
                    size_mb=sz, source='flatpak', pkg_id=app_id))

    return sorted(apps, key=lambda a: a.size_mb, reverse=True)

def _get_windows() -> List[InstalledApp]:
    apps = []
    # winget list
    out, code = run('winget list 2>nul', timeout=30)
    if code == 0:
        for line in out.splitlines()[2:]:  # skip headers
            if not line.strip() or line.startswith('-'): continue
            # winget columns: Name  Id  Version  Available  Source
            # Use regex to split on 2+ spaces
            parts = re.split(r'  +', line.strip())
            if len(parts) >= 2:
                apps.append(InstalledApp(name=parts[0], version=parts[2] if len(parts)>2 else '',
                    source='winget', pkg_id=parts[1] if len(parts)>1 else parts[0]))
    else:
        # Fallback: wmic
        out, _ = run('wmic product get Name,Version /format:csv 2>nul', timeout=30)
        for line in out.splitlines():
            parts = line.split(',')
            if len(parts) >= 3 and parts[1].strip():
                apps.append(InstalledApp(name=parts[1].strip(),
                    version=parts[2].strip() if len(parts)>2 else '',
                    source='wmic', pkg_id=parts[1].strip()))
    return sorted(apps, key=lambda a: a.name.lower())

def uninstall_app(app: InstalledApp, log_cb: Callable) -> bool:
    """Uninstall an app. Returns True on success."""
    log_cb(f'Uninstalling {app.name}...', 'info')
    if app.source == 'pacman':
        cmd = f'sudo -n /usr/local/bin/cyber-clean-helper pacman-remove {app.pkg_id} 2>/dev/null'
        # Fallback: normal sudo
        out, code = run(cmd, timeout=60)
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
    elif app.source == 'wmic':
        out, code = run(f'wmic product where name="{app.pkg_id}" call uninstall /nointeractive 2>nul', timeout=120)
    else:
        log_cb(f'  ✗ Unknown source: {app.source}', 'err')
        return False

    if code == 0:
        log_cb(f'  ✓ Uninstalled {app.name}', 'ok')
        return True
    else:
        log_cb(f'  ✗ Failed: {out[:200]}', 'err')
        return False
