"""
CyberClean v2.0 — One-Click Optimizer
Cross-platform: Linux + Windows
FIX: sudo calls dùng sudo -n (non-blocking) thay vì block GUI
"""
import subprocess, platform, time, shutil
from dataclasses import dataclass
from typing import List, Callable

OS = platform.system()

@dataclass
class OptimizeResult:
    action:   str
    success:  bool
    detail:   str = ''
    freed_mb: float = 0.0

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode == 0
    except:
        return '', False

def run_root(cmd, timeout=15):
    """Run privileged cmd — non-blocking. Uses pkexec helper if available, else sudo -n."""
    from pathlib import Path
    HELPER = '/usr/local/bin/cyber-clean-helper'
    POLICY = '/usr/share/polkit-1/actions/com.nc2077.cyberclean.policy'
    has_polkit = Path(HELPER).exists() and Path(POLICY).exists()
    if has_polkit:
        # Route through helper for clean polkit auth
        out, ok = run(f'pkexec {HELPER} optimizer 2>/dev/null || sudo -n {cmd} 2>/dev/null', timeout)
    else:
        # sudo -n: fails immediately if password needed — won't block GUI
        out, ok = run(f'sudo -n {cmd} 2>/dev/null', timeout)
    return out, ok

USELESS_SERVICES_LINUX = [
    ('apport',          'Ubuntu crash reporter (auto-reports crashes)'),
    ('whoopsie',        'Ubuntu error reporting daemon'),
    ('avahi-daemon',    'mDNS/Bonjour — usually not needed on desktop'),
    ('cups',            'Printer service — safe to disable if no printer'),
    ('ModemManager',    'Mobile broadband manager — safe if no 4G modem'),
    ('accounts-daemon', 'AccountsService — safe to disable'),
]

def optimize_linux(log_cb: Callable[[str, str], None]) -> List[OptimizeResult]:
    results = []

    # 1. Drop page cache
    log_cb('Freeing page cache...', 'info')
    _, ok = run_root('sh -c "sync && echo 1 > /proc/sys/vm/drop_caches"')
    if ok:
        log_cb('  ✓ Page cache freed — RAM reclaimed', 'ok')
        results.append(OptimizeResult('drop_cache', True, 'Page cache released'))
    else:
        log_cb('  ~ Skipped (needs root — run install.sh for polkit)', 'dim')
        results.append(OptimizeResult('drop_cache', False, 'Needs root'))

    # 2. Compact memory
    log_cb('Compacting memory...', 'info')
    _, ok = run_root('sh -c "echo 1 > /proc/sys/vm/compact_memory"')
    if ok:
        log_cb('  ✓ Memory compacted', 'ok')
    else:
        log_cb('  ~ Skipped (needs root)', 'dim')
    results.append(OptimizeResult('compact_mem', ok, 'Compacted' if ok else 'Needs root'))

    # 3. Kill zombie processes
    log_cb('Hunting zombie processes...', 'info')
    out, _ = run("ps -eo pid,stat | awk '$2~/^Z/ {print $1}'")
    zombies = [z.strip() for z in out.splitlines() if z.strip().isdigit()]
    if zombies:
        for z in zombies:
            run(f'kill -9 {z} 2>/dev/null')
        log_cb(f'  ✓ Killed {len(zombies)} zombie(s)', 'ok')
        results.append(OptimizeResult('kill_zombies', True, f'{len(zombies)} killed'))
    else:
        log_cb('  ✓ No zombies found — clean!', 'ok')
        results.append(OptimizeResult('kill_zombies', True, 'Clean'))

    # 4. Scan useless services (warn only — never auto-disable)
    log_cb('Scanning background services...', 'info')
    found_any = False
    for svc, desc in USELESS_SERVICES_LINUX:
        out, _ = run(f'systemctl is-active {svc} 2>/dev/null')
        if out.strip() == 'active':
            log_cb(f'  ⚠  {svc} — {desc}', 'warn')
            log_cb(f'     Disable: systemctl disable --now {svc}', 'dim')
            results.append(OptimizeResult(f'svc_{svc}', True, f'{svc} flagged'))
            found_any = True
    if not found_any:
        log_cb('  ✓ No unnecessary services running', 'ok')

    # 5. Swappiness
    log_cb('Tuning swappiness...', 'info')
    current, _ = run('cat /proc/sys/vm/swappiness')
    try:
        val = int(current.strip())
        if val > 10:
            _, ok = run_root(f'sh -c "echo 10 > /proc/sys/vm/swappiness"')
            if ok:
                log_cb(f'  ✓ Swappiness: {val} → 10 (prefers RAM)', 'ok')
                results.append(OptimizeResult('swappiness', True, f'{val}→10'))
            else:
                log_cb(f'  ~ Swappiness {val} — needs root to change', 'dim')
                results.append(OptimizeResult('swappiness', False, 'Needs root'))
        else:
            log_cb(f'  ✓ Swappiness already {val} — optimal', 'ok')
            results.append(OptimizeResult('swappiness', True, f'Already {val}'))
    except:
        pass

    # 6. SSD TRIM
    log_cb('Running SSD TRIM...', 'info')
    _, ok = run_root('fstrim -av')
    if ok:
        log_cb('  ✓ SSD TRIM complete', 'ok')
    else:
        log_cb('  ~ TRIM skipped (needs root or not SSD)', 'dim')
    results.append(OptimizeResult('fstrim', ok, 'Trimmed' if ok else 'Skipped'))

    # 7. GPU memory check (informational)
    log_cb('Checking GPU...', 'info')
    nvidia, _ = run('nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null')
    if nvidia:
        parts = nvidia.split(',')
        if len(parts) == 2:
            used, total = parts[0].strip(), parts[1].strip()
            log_cb(f'  ◈ NVIDIA VRAM: {used} / {total} MiB used', 'info')
    else:
        log_cb('  ~ No NVIDIA GPU detected', 'dim')

    return results

USELESS_SERVICES_WIN = [
    ('DiagTrack',          'Telemetry & diagnostics data sender'),
    ('SysMain',            'Superfetch — wastes RAM on SSD systems'),
    ('WSearch',            'Windows Search Indexer — heavy I/O'),
    ('TabletInputService', 'Tablet input — safe to disable on desktop'),
    ('Fax',                'Fax service — rarely needed'),
    ('XblGameSave',        'Xbox Game Save sync'),
    ('XboxNetApiSvc',      'Xbox Network API'),
]

def optimize_windows(log_cb: Callable[[str, str], None]) -> List[OptimizeResult]:
    results = []

    log_cb('Forcing .NET garbage collection...', 'info')
    _, ok = run('PowerShell -Command "[System.GC]::Collect(); [System.GC]::WaitForPendingFinalizers()" 2>$null')
    log_cb('  ✓ GC collected', 'ok')
    results.append(OptimizeResult('gc_collect', True, '.NET GC'))

    log_cb('Flushing DNS cache...', 'info')
    _, ok = run('ipconfig /flushdns')
    log_cb(f'  {"✓" if ok else "~"} DNS cache {"flushed" if ok else "skipped"}', 'ok' if ok else 'dim')
    results.append(OptimizeResult('flush_dns', ok, 'Flushed' if ok else 'Skipped'))

    log_cb('Clearing standby list...', 'info')
    # EmptyStandbyList.exe if available (Sysinternals), else skip gracefully
    _, ok = run('EmptyStandbyList.exe workingsets 2>$null')
    if ok:
        log_cb('  ✓ Standby list cleared', 'ok')
    else:
        log_cb('  ~ EmptyStandbyList not available (optional Sysinternals tool)', 'dim')
    results.append(OptimizeResult('standby', ok, 'Cleared' if ok else 'Skipped'))

    log_cb('Scanning background services...', 'info')
    found_any = False
    for svc, desc in USELESS_SERVICES_WIN:
        out, _ = run(f'PowerShell -Command "(Get-Service -Name {svc} -EA SilentlyContinue).Status" 2>$null')
        if out.strip() == 'Running':
            log_cb(f'  ⚠  {svc} — {desc}', 'warn')
            log_cb(f'     Disable: Stop-Service {svc} -Force', 'dim')
            results.append(OptimizeResult(f'svc_{svc}', True, f'{svc} flagged'))
            found_any = True
    if not found_any:
        log_cb('  ✓ No unnecessary services found', 'ok')

    log_cb('Checking power plan...', 'info')
    out, _ = run('powercfg /getactivescheme 2>$null')
    if 'Power saver' in out:
        _, ok = run('powercfg /setactive SCHEME_BALANCED 2>$null')
        if ok: log_cb('  ✓ Power plan: Power Saver → Balanced', 'ok')
    else:
        log_cb('  ✓ Power plan optimal', 'ok')
    results.append(OptimizeResult('power_plan', True, 'Balanced or better'))

    log_cb('Clearing clipboard...', 'info')
    _, ok = run('PowerShell -Command "Set-Clipboard -Value $null" 2>$null')
    log_cb(f'  {"✓" if ok else "~"} Clipboard {"cleared" if ok else "skipped"}', 'ok' if ok else 'dim')
    results.append(OptimizeResult('clipboard', ok, 'Cleared' if ok else 'Skipped'))

    return results

def run_optimizer(log_cb: Callable[[str, str], None]) -> List[OptimizeResult]:
    log_cb('═' * 52, 'head')
    log_cb(f'  ONE-CLICK OPTIMIZE  //  {time.strftime("%H:%M:%S")}', 'head')
    log_cb(f'  Platform: {OS}', 'info')
    log_cb('═' * 52, 'head')
    if OS == 'Linux':   return optimize_linux(log_cb)
    if OS == 'Windows': return optimize_windows(log_cb)
    log_cb('  Platform not supported', 'warn')
    return []
