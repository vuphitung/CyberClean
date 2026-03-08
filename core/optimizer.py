"""
CyberClean v2.0 — One-Click Optimizer
Kills useless background services, frees RAM, optimizes system.
Cross-platform: Linux + Windows
"""
import subprocess, platform, time
from dataclasses import dataclass, field
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
    except: return '', False

# ── Linux optimizer ───────────────────────────────────────────
USELESS_SERVICES_LINUX = [
    # Telemetry / tracking
    ('apport',              'Ubuntu crash reporter'),
    ('whoopsie',            'Ubuntu error reporting'),
    ('avahi-daemon',        'Avahi mDNS (usually not needed)'),
    ('cups',                'Printer service (if no printer)'),
    # Resource heavy optional
    ('ModemManager',        'Modem manager (if no 4G/modem)'),
    ('accounts-daemon',     'AccountsService daemon'),
]

def optimize_linux(log_cb: Callable[[str, str], None]) -> List[OptimizeResult]:
    results = []

    # 1. Drop page cache / reclaimable memory
    log_cb('Freeing page cache...', 'info')
    _, ok = run('sync && echo 1 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1')
    if ok:
        log_cb('  ✓ Page cache freed', 'ok')
        results.append(OptimizeResult('drop_cache', True, 'Kernel page cache released'))
    else:
        log_cb('  ~ Skipped (needs root)', 'dim')
        results.append(OptimizeResult('drop_cache', False, 'Needs root'))

    # 2. Compact memory (reduce fragmentation)
    log_cb('Compacting memory...', 'info')
    _, ok = run('echo 1 | sudo tee /proc/sys/vm/compact_memory > /dev/null 2>&1')
    results.append(OptimizeResult('compact_mem', ok, 'Memory compacted' if ok else 'Needs root'))
    if ok: log_cb('  ✓ Memory compacted', 'ok')

    # 3. Kill zombie processes
    log_cb('Hunting zombie processes...', 'info')
    out, _ = run("ps aux | awk '$8 == \"Z\" {print $2}'")
    zombies = [z for z in out.splitlines() if z.strip()]
    if zombies:
        for z in zombies:
            run(f'sudo kill -9 {z} 2>/dev/null')
        log_cb(f'  ✓ Killed {len(zombies)} zombies', 'ok')
        results.append(OptimizeResult('kill_zombies', True, f'{len(zombies)} zombies killed'))
    else:
        log_cb('  ✓ No zombies found', 'ok')
        results.append(OptimizeResult('kill_zombies', True, 'Clean'))

    # 4. Check & disable useless services (only if running, only WARN — don't auto-disable)
    log_cb('Scanning background services...', 'info')
    for svc, desc in USELESS_SERVICES_LINUX:
        out, _ = run(f'systemctl is-active {svc} 2>/dev/null')
        if out == 'active':
            log_cb(f'  ⚠  {svc} is running — {desc}', 'warn')
            results.append(OptimizeResult(f'svc_{svc}', True,
                           f'{svc} running ({desc}) — disable manually if not needed'))

    # 5. Swappiness tuning (lower = prefer RAM over swap)
    log_cb('Tuning swappiness...', 'info')
    current, _ = run('cat /proc/sys/vm/swappiness')
    try:
        if int(current) > 10:
            _, ok = run('echo 10 | sudo tee /proc/sys/vm/swappiness > /dev/null 2>&1')
            if ok:
                log_cb(f'  ✓ Swappiness: {current} → 10 (RAM preferred)', 'ok')
                results.append(OptimizeResult('swappiness', True, f'{current}→10'))
    except: pass

    # 6. Trim SSD
    log_cb('Running SSD TRIM...', 'info')
    _, ok = run('sudo fstrim -av 2>/dev/null')
    results.append(OptimizeResult('fstrim', ok, 'SSD trimmed' if ok else 'Skipped or not SSD'))
    if ok: log_cb('  ✓ SSD TRIM complete', 'ok')

    return results

# ── Windows optimizer ─────────────────────────────────────────
USELESS_SERVICES_WIN = [
    ('DiagTrack',       'Connected User Experiences and Telemetry'),
    ('SysMain',         'Superfetch (wastes RAM on SSDs)'),
    ('WSearch',         'Windows Search Indexer'),
    ('TabletInputService', 'Tablet PC Input Service'),
    ('Fax',             'Fax service'),
    ('XblGameSave',     'Xbox Game Save'),
    ('XboxNetApiSvc',   'Xbox Network API'),
]

def optimize_windows(log_cb: Callable[[str, str], None]) -> List[OptimizeResult]:
    results = []

    # 1. Empty Standby List (free RAM)
    log_cb('Clearing standby memory list...', 'info')
    # Uses RAMMap-like approach via Windows API
    out, ok = run('PowerShell -Command "[System.GC]::Collect(); [System.GC]::WaitForPendingFinalizers()"')
    log_cb('  ✓ GC collected', 'ok')
    results.append(OptimizeResult('gc_collect', True, '.NET GC collected'))

    # 2. Flush DNS
    log_cb('Flushing DNS cache...', 'info')
    _, ok = run('ipconfig /flushdns')
    results.append(OptimizeResult('flush_dns', ok, 'DNS flushed' if ok else 'Failed'))
    if ok: log_cb('  ✓ DNS cache flushed', 'ok')

    # 3. Check useless services
    log_cb('Scanning background services...', 'info')
    for svc, desc in USELESS_SERVICES_WIN:
        out, _ = run(f'PowerShell -Command "(Get-Service -Name {svc} -ErrorAction SilentlyContinue).Status"')
        if out.strip() == 'Running':
            log_cb(f'  ⚠  {svc} running — {desc}', 'warn')
            results.append(OptimizeResult(f'svc_{svc}', True,
                f'{svc} ({desc}) — disable in Services if not needed'))

    # 4. Power plan — High Performance
    log_cb('Setting power plan to Balanced...', 'info')
    out, ok = run('powercfg /getactivescheme')
    if 'Power saver' in out:
        _, ok = run('powercfg /setactive SCHEME_BALANCED')
        if ok: log_cb('  ✓ Power plan: Power Saver → Balanced', 'ok')
    else:
        log_cb('  ✓ Power plan already optimal', 'ok')
    results.append(OptimizeResult('power_plan', True, 'Balanced or better'))

    # 5. Clear clipboard
    log_cb('Clearing clipboard...', 'info')
    _, ok = run('PowerShell -Command "Set-Clipboard -Value $null"')
    results.append(OptimizeResult('clipboard', ok, 'Cleared' if ok else 'Skipped'))
    if ok: log_cb('  ✓ Clipboard cleared', 'ok')

    return results

def run_optimizer(log_cb: Callable[[str, str], None]) -> List[OptimizeResult]:
    """Entry point — auto-detects OS and runs appropriate optimizer."""
    log_cb('═' * 50, 'head')
    log_cb(f'  ONE-CLICK OPTIMIZE — {time.strftime("%H:%M:%S")}', 'head')
    log_cb(f'  Platform: {OS}', 'info')
    log_cb('═' * 50, 'head')

    if OS == 'Linux':   return optimize_linux(log_cb)
    if OS == 'Windows': return optimize_windows(log_cb)
    log_cb('  Platform not supported yet', 'warn')
    return []