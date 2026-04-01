"""
CyberClean v2.2 — Smart Analyzer
NEW FEATURES:
  1. Duplicate File Finder  — hash-based, shows groups to keep/delete
  2. Startup Impact Score   — systemd-analyze / registry timing + 🔴🟡🟢 rating
  3. Idle-Based Auto-Clean  — triggers only when CPU+net are quiet
  4. Disk Health Monitor    — S.M.A.R.T. via smartctl
  5. Clean Report Export    — HTML report after each session
  6. Process Network Monitor — map process → outbound connections
"""
import os, platform, subprocess, hashlib, time, re, json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from collections import defaultdict

OS = platform.system()
IS_LINUX   = OS == 'Linux'
IS_WINDOWS = OS == 'Windows'

_NO_WIN = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout,
                           creationflags=_NO_WIN if IS_WINDOWS else 0)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1


# ══════════════════════════════════════════════════════════════
# 1. DUPLICATE FILE FINDER
# ══════════════════════════════════════════════════════════════

@dataclass
class DuplicateGroup:
    hash:        str
    size_each:   int
    total_waste: int       # (len(files) - 1) * size_each
    files:       List[Path] = field(default_factory=list)

    def keep(self) -> Path:
        """Return the file we'd keep (oldest = original)."""
        return min(self.files, key=lambda f: f.stat().st_mtime)

    def to_delete(self) -> List[Path]:
        """Files safe to delete (all except oldest)."""
        keep = self.keep()
        return [f for f in self.files if f != keep]


def find_duplicates(
    scan_paths: List[Path],
    min_size_bytes: int = 1024 * 1024,   # 1 MB default
    max_size_bytes: int = 5 * 1024**3,   # 5 GB — skip huge ISOs etc.
    progress_cb: Optional[Callable] = None,
) -> List[DuplicateGroup]:
    """
    Find duplicate files via two-pass hash (size bucket → SHA-256).
    Only hashes files in same-size bucket to avoid hashing everything.

    FIX (v2.3): Upgraded from MD5 to SHA-256.
    MD5 has known collision vulnerabilities — two different files can produce
    the same hash, causing app to incorrectly flag them as duplicates and
    potentially recommend deleting a file that is NOT actually a copy.
    SHA-256 has no practical collision risk, making duplicate detection safe.

    min_size_bytes: skip tiny files (0-byte, icons, cache manifests)
    max_size_bytes: skip giant files that would take too long to hash
    progress_cb(pct: int, msg: str): optional progress callback
    """
    # Pass 1 — bucket by size
    size_map: dict = defaultdict(list)
    scanned = 0

    # FIX: use os.walk(followlinks=False) instead of rglob to prevent infinite loops
    # from circular symlinks (e.g. ~/.config/app -> /tmp -> ~/.config).
    # rglob descends into symlinked directories — os.walk stops at the boundary.
    all_files = []
    for root in scan_paths:
        try:
            for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
                # Skip symlinked subdirectories entirely
                dirnames[:] = [
                    d for d in dirnames
                    if not os.path.islink(os.path.join(dirpath, d))
                ]
                for fname in filenames:
                    fpath = Path(dirpath) / fname
                    if fpath.is_symlink() or not fpath.is_file():
                        continue
                    all_files.append(fpath)
        except (PermissionError, OSError):
            pass

    total = len(all_files)
    for i, f in enumerate(all_files):
        try:
            sz = f.stat().st_size
            if min_size_bytes <= sz <= max_size_bytes:
                size_map[sz].append(f)
            scanned += 1
        except (OSError, PermissionError):
            pass
        if progress_cb and i % 200 == 0:
            progress_cb(int(i / max(total, 1) * 40), f'Scanning... {scanned} files')

    # Pass 2 — hash only candidates (same size ≥ 2) using SHA-256
    candidates = {sz: files for sz, files in size_map.items() if len(files) >= 2}
    hash_map: dict = defaultdict(list)

    done = 0
    candidate_files = [(sz, f) for sz, files in candidates.items() for f in files]
    total_c = len(candidate_files)

    for i, (sz, f) in enumerate(candidate_files):
        try:
            # FIX: SHA-256 replaces MD5 — no collision risk, safe for file dedup
            # Read in chunks — avoid loading huge files into memory
            sha256 = hashlib.sha256()
            with open(f, 'rb') as fh:
                for chunk in iter(lambda: fh.read(65536), b''):
                    sha256.update(chunk)
            hash_map[sha256.hexdigest()].append((sz, f))
            done += 1
        except (OSError, PermissionError):
            pass
        if progress_cb and i % 50 == 0:
            pct = 40 + int(i / max(total_c, 1) * 55)
            progress_cb(pct, f'Hashing... {done} files')

    # Build result groups
    groups = []
    for h, entries in hash_map.items():
        if len(entries) < 2:
            continue
        sz = entries[0][0]
        files = [e[1] for e in entries]
        waste = (len(files) - 1) * sz
        groups.append(DuplicateGroup(
            hash=h, size_each=sz,
            total_waste=waste, files=files
        ))

    # Sort by most waste first
    groups.sort(key=lambda g: g.total_waste, reverse=True)

    if progress_cb:
        progress_cb(100, f'Done — {len(groups)} duplicate groups found')

    return groups


def delete_duplicates(groups: List[DuplicateGroup], dry: bool = True) -> dict:
    """
    Delete duplicate copies (keeps oldest in each group).
    Returns {'deleted': int, 'freed_bytes': int, 'errors': List[str]}
    """
    deleted = 0
    freed   = 0
    errors  = []
    for g in groups:
        for f in g.to_delete():
            try:
                sz = f.stat().st_size
                if not dry:
                    f.unlink()
                deleted += 1
                freed   += sz
            except Exception as e:
                errors.append(f'{f}: {e}')
    return {'deleted': deleted, 'freed_bytes': freed, 'errors': errors}


# ══════════════════════════════════════════════════════════════
# 2. STARTUP IMPACT SCORE
# ══════════════════════════════════════════════════════════════

@dataclass
class StartupItem:
    name:        str
    display:     str         # human-readable name
    time_ms:     int         # 0 if unknown
    impact:      str         # 'high' | 'medium' | 'low' | 'unknown'
    source:      str         # 'systemd' | 'xdg' | 'registry'
    enabled:     bool = True
    path:        str  = ''

    @property
    def impact_emoji(self) -> str:
        return {'high': '🔴', 'medium': '🟡', 'low': '🟢', 'unknown': '⚪'}.get(self.impact, '⚪')

    @property
    def time_display(self) -> str:
        if self.time_ms <= 0: return '—'
        if self.time_ms >= 1000: return f'{self.time_ms/1000:.1f}s'
        return f'{self.time_ms}ms'


def _classify_impact(ms: int) -> str:
    if ms <= 0:    return 'unknown'
    if ms >= 800:  return 'high'
    if ms >= 200:  return 'medium'
    return 'low'


def get_startup_items() -> List[StartupItem]:
    """Get startup items with timing on both platforms."""
    if IS_LINUX:
        return _startup_linux()
    if IS_WINDOWS:
        return _startup_windows()
    return []


def _parse_systemd_time(s: str) -> int:
    """Convert '1.234s' or '456ms' or '1min 2.3s' to milliseconds."""
    s = s.strip()
    ms = 0
    m = re.search(r'(\d+)min', s)
    if m: ms += int(m.group(1)) * 60000
    m = re.search(r'([\d.]+)s', s)
    if m: ms += int(float(m.group(1)) * 1000)
    m = re.search(r'(\d+)ms', s)
    if m: ms += int(m.group(1))
    return ms


def _startup_linux() -> List[StartupItem]:
    items = []

    # Source 1: systemd-analyze blame (most accurate — actual measured boot times)
    out, code = _run('systemd-analyze blame --no-pager 2>/dev/null', timeout=10)
    systemd_times = {}
    if code == 0:
        for line in out.splitlines()[:30]:
            parts = line.strip().split()
            if len(parts) >= 2:
                time_str = parts[0]
                unit = parts[-1]
                ms = _parse_systemd_time(time_str)
                systemd_times[unit] = ms

    for unit, ms in systemd_times.items():
        # Only user-relevant units (skip kernel internals)
        if any(skip in unit for skip in ('@', 'systemd-', 'dbus', 'udev', 'mount')):
            continue
        display = unit.replace('.service', '').replace('.target', '').replace('-', ' ').title()
        items.append(StartupItem(
            name=unit, display=display,
            time_ms=ms, impact=_classify_impact(ms),
            source='systemd', enabled=True
        ))

    # Source 2: XDG autostart (~/.config/autostart + /etc/xdg/autostart)
    autostart_dirs = [
        Path.home() / '.config/autostart',
        Path('/etc/xdg/autostart'),
    ]
    for d in autostart_dirs:
        if not d.exists():
            continue
        for f in d.glob('*.desktop'):
            try:
                content = f.read_text(errors='ignore')
                name = ''
                hidden = False
                exec_cmd = ''
                for line in content.splitlines():
                    if line.startswith('Name='): name = line.split('=', 1)[1].strip()
                    if line.startswith('Hidden=true'): hidden = True
                    if line.startswith('Exec='): exec_cmd = line.split('=', 1)[1].strip()
                if hidden: continue
                # Not in systemd list → unknown timing
                items.append(StartupItem(
                    name=f.stem, display=name or f.stem,
                    time_ms=0, impact='unknown',
                    source='xdg', enabled=True, path=exec_cmd
                ))
            except: pass

    items.sort(key=lambda x: x.time_ms, reverse=True)
    return items


def _startup_windows() -> List[StartupItem]:
    items = []
    try:
        import winreg
        run_keys = [
            (winreg.HKEY_CURRENT_USER,  r'Software\Microsoft\Windows\CurrentVersion\Run'),
            (winreg.HKEY_LOCAL_MACHINE, r'Software\Microsoft\Windows\CurrentVersion\Run'),
        ]
        approved_key_path = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'

        # Read timing from StartupApproved (only exists on Win10+)
        approved = {}
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, approved_key_path)
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(k, i)
                    # data[0]: 02 = enabled, 03 = disabled
                    approved[name] = data[0] == 2
                    i += 1
                except OSError: break
            winreg.CloseKey(k)
        except: pass

        for hive, key_path in run_keys:
            try:
                key = winreg.OpenKey(hive, key_path)
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, i)
                        enabled = approved.get(name, True)
                        items.append(StartupItem(
                            name=name, display=name,
                            time_ms=0, impact='unknown',
                            source='registry', enabled=enabled, path=val
                        ))
                        i += 1
                    except OSError: break
                winreg.CloseKey(key)
            except: pass
    except ImportError:
        pass

    return items


def toggle_startup_item(item: StartupItem, enable: bool) -> bool:
    """Enable or disable a startup item."""
    if item.source == 'systemd':
        action = 'enable' if enable else 'disable'
        _, code = _run(f'systemctl --user {action} {item.name} 2>/dev/null')
        return code == 0
    elif item.source == 'xdg':
        desktop = Path.home() / f'.config/autostart/{item.name}.desktop'
        if not desktop.exists(): return False
        try:
            content = desktop.read_text(errors='ignore')
            lines = content.splitlines()
            new_lines = [l for l in lines if not l.startswith('Hidden=')]
            if not enable:
                new_lines.append('Hidden=true')
            desktop.write_text('\n'.join(new_lines))
            return True
        except: return False
    elif item.source == 'registry' and IS_WINDOWS:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run',
                0, winreg.KEY_SET_VALUE)
            # 02 00 00 00 00 00 00 00 00 00 00 00 = enabled
            # 03 00 00 00 00 00 00 00 00 00 00 00 = disabled
            data = bytes([2 if enable else 3] + [0]*11)
            winreg.SetValueEx(key, item.name, 0, winreg.REG_BINARY, data)
            winreg.CloseKey(key)
            return True
        except: return False
    return False


# ══════════════════════════════════════════════════════════════
# 3. IDLE-BASED AUTO-CLEAN SCHEDULER
# ══════════════════════════════════════════════════════════════

class IdleScheduler:
    """
    Runs auto-clean only when machine is idle.
    Idle = CPU < threshold AND network throughput < threshold
    AND at least min_interval seconds since last clean.
    """

    def __init__(
        self,
        cpu_threshold: float = 15.0,
        net_threshold_kb: float = 100.0,
        min_interval_hours: float = 4.0,
        sample_seconds: float = 3.0,
    ):
        self.cpu_threshold     = cpu_threshold
        self.net_threshold_kb  = net_threshold_kb
        self.min_interval_sec  = min_interval_hours * 3600
        self.sample_seconds    = sample_seconds
        self._last_clean_ts    = 0.0
        self._history_file     = Path.home() / '.local/share/cyber-clean/last_auto_clean'

        # Load last clean timestamp from disk
        try:
            if self._history_file.exists():
                self._last_clean_ts = float(self._history_file.read_text().strip())
        except: pass

    def is_idle(self) -> bool:
        """Non-blocking idle check using psutil."""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=self.sample_seconds)
            net1 = psutil.net_io_counters()
            time.sleep(1)
            net2 = psutil.net_io_counters()
            net_kbps = ((net2.bytes_sent + net2.bytes_recv) -
                        (net1.bytes_sent + net1.bytes_recv)) / 1024
            return cpu < self.cpu_threshold and net_kbps < self.net_threshold_kb
        except ImportError:
            return False

    def should_run(self) -> bool:
        """True if idle AND enough time has passed since last clean."""
        elapsed = time.time() - self._last_clean_ts
        if elapsed < self.min_interval_sec:
            return False
        return self.is_idle()

    def mark_completed(self):
        """Call after auto-clean finishes."""
        self._last_clean_ts = time.time()
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            self._history_file.write_text(str(self._last_clean_ts))
        except: pass

    def time_until_eligible(self) -> float:
        """Seconds until min_interval is satisfied (0 if already eligible)."""
        return max(0.0, self.min_interval_sec - (time.time() - self._last_clean_ts))

    def status_str(self) -> str:
        remaining = self.time_until_eligible()
        if remaining > 0:
            h = int(remaining // 3600)
            m = int((remaining % 3600) // 60)
            return f'Next eligible in {h}h {m}m'
        return 'Ready — waiting for idle window'


# ══════════════════════════════════════════════════════════════
# 4. DISK HEALTH MONITOR (S.M.A.R.T.)
# ══════════════════════════════════════════════════════════════

@dataclass
class DiskHealth:
    device:      str
    model:       str = ''
    status:      str = 'unknown'    # 'healthy' | 'warning' | 'failing' | 'unknown'
    temperature: Optional[int] = None
    reallocated: int = 0            # Reallocated_Sector_Ct — early warning of failure
    pending:     int = 0            # Current_Pending_Sector — unreadable sectors
    uncorrectable: int = 0          # Offline_Uncorrectable
    hours:       int = 0            # Power_On_Hours
    details:     str = ''

    @property
    def status_emoji(self) -> str:
        return {'healthy': '💚', 'warning': '🟡', 'failing': '🔴', 'unknown': '⚪'}.get(self.status, '⚪')

    @property
    def short_summary(self) -> str:
        parts = []
        if self.temperature: parts.append(f'{self.temperature}°C')
        if self.hours:       parts.append(f'{self.hours:,}h uptime')
        if self.reallocated: parts.append(f'⚠ {self.reallocated} reallocated sectors')
        if self.pending:     parts.append(f'⚠ {self.pending} pending sectors')
        return ' · '.join(parts) if parts else 'No data'


def _parse_smart_attribute(text: str, attr_name: str) -> int:
    """Parse a specific attribute from smartctl -A output."""
    pattern = rf'{re.escape(attr_name)}\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\d+)'
    m = re.search(pattern, text, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def get_disk_health() -> List[DiskHealth]:
    """
    Query S.M.A.R.T. data for all detected disks.
    Requires smartmontools (smartctl). Gracefully returns empty list if not installed.
    On Linux: usually needs root or sg group.
    On Windows: smartctl.exe must be in PATH.
    """
    results = []

    # Check if smartctl is available
    smartctl = 'smartctl'
    if IS_WINDOWS:
        # Common install paths for smartmontools on Windows
        for candidate in [
            r'C:\Program Files\smartmontools\bin\smartctl.exe',
            r'C:\Program Files (x86)\smartmontools\bin\smartctl.exe',
            'smartctl',
        ]:
            out, code = _run(f'"{candidate}" --version 2>nul' if IS_WINDOWS else f'{candidate} --version', timeout=5)
            if code == 0:
                smartctl = f'"{candidate}"' if ' ' in candidate else candidate
                break
        else:
            return []
    else:
        out, code = _run('smartctl --version 2>/dev/null', timeout=5)
        if code != 0:
            return []

    # Scan for devices
    scan_out, _ = _run(f'{smartctl} --scan 2>/dev/null', timeout=10)
    if not scan_out:
        # Fallback: try common device paths on Linux
        if IS_LINUX:
            devices = [str(p) for p in Path('/dev').glob('sd?')]
            devices += [str(p) for p in Path('/dev').glob('nvme?')]
        else:
            devices = []
    else:
        devices = [line.split()[0] for line in scan_out.splitlines() if line.strip()]

    for dev in devices[:8]:    # cap at 8 disks
        try:
            health = DiskHealth(device=dev)

            # Overall health check
            h_out, _ = _run(f'{smartctl} -H {dev} 2>/dev/null', timeout=10)
            if 'PASSED' in h_out:
                health.status = 'healthy'
            elif 'FAILED' in h_out:
                health.status = 'failing'
            else:
                health.status = 'unknown'

            # Detailed attributes
            a_out, _ = _run(f'{smartctl} -A {dev} 2>/dev/null', timeout=10)
            health.reallocated  = _parse_smart_attribute(a_out, 'Reallocated_Sector_Ct')
            health.pending      = _parse_smart_attribute(a_out, 'Current_Pending_Sector')
            health.uncorrectable = _parse_smart_attribute(a_out, 'Offline_Uncorrectable')
            health.hours        = _parse_smart_attribute(a_out, 'Power_On_Hours')

            # Temperature
            m = re.search(r'Temperature.*?(\d{2,3})', a_out)
            if m:
                health.temperature = int(m.group(1))

            # Model string
            i_out, _ = _run(f'{smartctl} -i {dev} 2>/dev/null', timeout=8)
            m = re.search(r'Device Model:\s+(.+)', i_out)
            if m: health.model = m.group(1).strip()

            # Upgrade status if sectors are bad
            if health.reallocated > 0 or health.pending > 0 or health.uncorrectable > 0:
                if health.status == 'healthy':
                    health.status = 'warning'

            results.append(health)
        except Exception:
            pass

    return results


def smartctl_available() -> bool:
    """Quick check if smartmontools is installed."""
    _, code = _run('smartctl --version 2>/dev/null', timeout=5)
    return code == 0


# ══════════════════════════════════════════════════════════════
# 5. CLEAN REPORT EXPORT
# ══════════════════════════════════════════════════════════════

def generate_html_report(results: list, output_path: Path = None) -> Path:
    """
    Generate a standalone HTML clean report.
    results: list of CleanResult objects from a clean session.
    Returns the output path.
    """
    if output_path is None:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_path = Path.home() / f'CyberClean_Report_{ts}.html'

    total_freed  = sum(getattr(r, 'freed_bytes', 0) for r in results)
    total_files  = sum(getattr(r, 'files_removed', 0) for r in results)
    success_cnt  = sum(1 for r in results if getattr(r, 'error', None) is None)
    fail_cnt     = len(results) - success_cnt
    ts_display   = time.strftime('%B %d, %Y at %H:%M')

    def fmt_bytes(n):
        for u in ['B', 'KB', 'MB', 'GB']:
            if n < 1024 or u == 'GB': return f'{n:.1f} {u}'
            n /= 1024

    rows_html = ''
    for r in results:
        tid    = getattr(r, 'target_id', '?')
        freed  = getattr(r, 'freed_bytes', 0)
        files  = getattr(r, 'files_removed', 0)
        err    = getattr(r, 'error', None)
        status = '✓' if not err else '✗'
        css    = 'row-ok' if not err else 'row-err'
        err_td = f'<td class="err-msg">{err}</td>' if err else '<td></td>'
        rows_html += f'''
        <tr class="{css}">
          <td class="status">{status}</td>
          <td class="target">{tid.replace("_", " ").title()}</td>
          <td class="size">{fmt_bytes(freed) if freed else "—"}</td>
          <td class="files">{files if files else "—"}</td>
          {err_td}
        </tr>'''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CyberClean Report — {ts_display}</title>
<style>
  :root {{
    --bg: #0a0d14; --surface: #111520; --surface2: #181d2e;
    --border: #1e2540; --accent: #00e5ff; --accent2: #7c3aed;
    --green: #00ff88; --red: #ff4444; --text: #e2e8f0; --muted: #64748b;
    --font: 'Courier New', monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg); color: var(--text); font-family: var(--font);
    min-height: 100vh; padding: 40px 20px;
  }}
  .container {{ max-width: 900px; margin: 0 auto; }}

  /* Header */
  .header {{ border-left: 3px solid var(--accent); padding: 0 0 0 20px; margin-bottom: 40px; }}
  .header .logo {{ font-size: 11px; color: var(--accent); letter-spacing: 4px; margin-bottom: 8px; }}
  .header h1 {{ font-size: 28px; font-weight: 400; color: #fff; }}
  .header .ts {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}

  /* Stats grid */
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }}
  .stat {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 20px 16px; text-align: center;
  }}
  .stat .val {{ font-size: 28px; font-weight: 700; color: var(--accent); }}
  .stat .label {{ font-size: 11px; color: var(--muted); letter-spacing: 2px; margin-top: 4px; }}
  .stat.green .val {{ color: var(--green); }}
  .stat.red .val   {{ color: var(--red); }}

  /* Table */
  .table-wrap {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; overflow: hidden;
  }}
  .table-header {{
    background: var(--surface2); padding: 12px 20px;
    font-size: 11px; letter-spacing: 3px; color: var(--muted);
    border-bottom: 1px solid var(--border);
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{
    padding: 10px 16px; text-align: left; font-size: 10px;
    letter-spacing: 2px; color: var(--muted);
    border-bottom: 1px solid var(--border);
  }}
  td {{ padding: 10px 16px; font-size: 13px; border-bottom: 1px solid rgba(30,37,64,0.5); }}
  tr:last-child td {{ border-bottom: none; }}
  .row-ok:hover td {{ background: rgba(0,229,255,0.03); }}
  .row-err:hover td {{ background: rgba(255,68,68,0.04); }}
  .status {{ text-align: center; width: 40px; }}
  .row-ok .status {{ color: var(--green); }}
  .row-err .status {{ color: var(--red); }}
  .size {{ color: var(--accent); font-weight: 700; }}
  .err-msg {{ color: var(--red); font-size: 11px; }}

  /* Footer */
  .footer {{
    margin-top: 32px; text-align: center; font-size: 11px;
    color: var(--muted); letter-spacing: 2px;
  }}
  .footer span {{ color: var(--accent); }}

  @media (max-width: 600px) {{
    .stats {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <div class="logo">CYBERCLEAN // CLEAN REPORT</div>
    <h1>System Clean Session</h1>
    <div class="ts">{ts_display} · {OS} · CyberClean v2.2</div>
  </div>

  <div class="stats">
    <div class="stat green">
      <div class="val">{fmt_bytes(total_freed)}</div>
      <div class="label">FREED</div>
    </div>
    <div class="stat">
      <div class="val">{total_files:,}</div>
      <div class="label">FILES REMOVED</div>
    </div>
    <div class="stat green">
      <div class="val">{success_cnt}</div>
      <div class="label">TASKS OK</div>
    </div>
    <div class="stat {'red' if fail_cnt else ''}">
      <div class="val">{fail_cnt}</div>
      <div class="label">TASKS FAILED</div>
    </div>
  </div>

  <div class="table-wrap">
    <div class="table-header">CLEAN TARGETS // DETAILED RESULTS</div>
    <table>
      <thead>
        <tr>
          <th>ST</th>
          <th>TARGET</th>
          <th>FREED</th>
          <th>FILES</th>
          <th>NOTE</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>

  <div class="footer">
    Generated by <span>CyberClean v2.2</span> · github.com/vuphitung/CyberClean
  </div>

</div>
</body>
</html>'''

    output_path.write_text(html, encoding='utf-8')
    return output_path


# ══════════════════════════════════════════════════════════════
# 6. PROCESS NETWORK MONITOR
# ══════════════════════════════════════════════════════════════

@dataclass
class NetworkProcess:
    pid:        int
    name:       str
    exe:        str
    remote_ip:  str
    remote_port: int
    protocol:   str    # 'TCP' | 'UDP'
    suspicious: bool = False
    reason:     str  = ''

    @property
    def remote_display(self) -> str:
        return f'{self.remote_ip}:{self.remote_port}'

    @property
    def flag(self) -> str:
        return '🔴' if self.suspicious else '🟢'


# Known safe CDN/service IP ranges (very rough — just to reduce noise)
_PRIVATE_PREFIXES = (
    '127.', '::1', '0.0.0.0',
    '10.', '172.16.', '172.17.', '172.18.', '172.19.',
    '172.20.', '172.21.', '172.22.', '172.23.', '172.24.',
    '172.25.', '172.26.', '172.27.', '172.28.', '172.29.',
    '172.30.', '172.31.', '192.168.',
    'fe80:', 'fc', 'fd',
)

# Ports that are unusual for established outbound connections
_SUSPICIOUS_PORTS = {4444, 1337, 31337, 12345, 54321, 9001, 6666, 6667, 31338, 2222}

# Process names that should NEVER be making outbound connections
_NEVER_NETWORK = {'explorer', 'winlogon', 'csrss', 'smss', 'lsass', 'dwm', 'taskeng'}


def get_network_processes(include_private: bool = False) -> List[NetworkProcess]:
    """
    Map all established TCP connections to their owning process.
    Filters out localhost/private ranges by default.
    Flags suspicious connections (unusual ports, unexpected processes).
    """
    results = []
    try:
        import psutil
        for conn in psutil.net_connections(kind='inet'):
            if conn.status != psutil.CONN_ESTABLISHED:
                continue
            if not conn.raddr:
                continue

            remote_ip = conn.raddr.ip
            remote_port = conn.raddr.port

            # Filter private/localhost
            if not include_private:
                if any(remote_ip.startswith(p) for p in _PRIVATE_PREFIXES):
                    continue

            try:
                proc = psutil.Process(conn.pid)
                name = proc.name()
                exe  = proc.exe()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                name = f'PID {conn.pid}'
                exe  = ''

            suspicious = False
            reason     = ''

            # Check suspicious port
            if remote_port in _SUSPICIOUS_PORTS:
                suspicious = True
                reason = f'Suspicious port {remote_port}'

            # Check process that should never be networking
            name_lower = name.lower().replace('.exe', '')
            if name_lower in _NEVER_NETWORK:
                suspicious = True
                reason = f'{name} should not make outbound connections'

            # Executable running from temp dir
            if exe and any(exe.lower().startswith(t) for t in
                           ['/tmp', '/var/tmp', os.environ.get('TEMP','').lower()]):
                suspicious = True
                reason = f'Process executable in temp dir'

            results.append(NetworkProcess(
                pid=conn.pid, name=name, exe=exe,
                remote_ip=remote_ip, remote_port=remote_port,
                protocol='TCP',
                suspicious=suspicious, reason=reason
            ))

    except ImportError:
        pass

    # Sort: suspicious first, then by process name
    results.sort(key=lambda x: (not x.suspicious, x.name.lower()))
    return results


def kill_network_process(pid: int) -> bool:
    """Kill a process by PID. Returns True on success."""
    try:
        import psutil
        p = psutil.Process(pid)
        p.kill()
        return True
    except Exception:
        return False
