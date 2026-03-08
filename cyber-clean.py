#!/usr/bin/env python3
# ╔══════════════════════════════════════════════════════════════╗
# ║  NC2077 // CYBER-CLEAN — Smart Auto Disk Cleaner            ║
# ║  Chỉ xóa những thứ 100% an toàn                            ║
# ║  Có dry-run, log lịch sử, rollback list                    ║
# ╚══════════════════════════════════════════════════════════════╝
#
# Usage:
#   python3 cyber-clean.py          → auto clean nếu disk >75%
#   python3 cyber-clean.py --dry    → xem sẽ xóa gì, không xóa thật
#   python3 cyber-clean.py --force  → clean dù disk chưa đến 75%
#   python3 cyber-clean.py --log    → xem lịch sử đã xóa
#   python3 cyber-clean.py --rollback → xem danh sách file đã xóa

import subprocess, os, sys, shutil, json, time, re
from pathlib import Path
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────
DISK_THRESHOLD  = 75       # % disk → trigger auto clean
LOG_DIR         = Path.home() / ".local/share/cyber-clean"
LOG_FILE        = LOG_DIR / "history.jsonl"
ROLLBACK_FILE   = LOG_DIR / "rollback.jsonl"
PACMAN_KEEP     = 1        # giữ lại N version cũ của mỗi package
JOURNAL_DAYS    = 7        # xóa journal cũ hơn N ngày
TMP_DAYS        = 3        # xóa /tmp file cũ hơn N ngày

# ── ANSI ────────────────────────────────────────────────────────
R='\033[38;5;196m'; Y='\033[38;5;220m'; G='\033[38;5;82m'
C='\033[38;5;51m';  DIM='\033[38;5;240m'; B='\033[1m'; NC='\033[0m'

# ── Sudo check cho các lệnh cần quyền root ─────────────────────
IS_ROOT = os.geteuid() == 0
SUDO    = "sudo " if not IS_ROOT else ""

DRY  = '--dry'   in sys.argv
FORCE= '--force' in sys.argv

LOG_DIR.mkdir(parents=True, exist_ok=True)

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

def hr(): print(f"{C}{'━'*62}{NC}")
def ok(m):   print(f"  {G}✓{NC}  {m}")
def warn(m): print(f"  {Y}⚠{NC}  {m}")
def info(m): print(f"  {DIM}·{NC}  {m}")
def action(m): print(f"  {C}▶{NC}  {m}")

def fmt_size(n):
    for u in ['B','KB','MB','GB','TB']:
        if n < 1024 or u == 'TB':
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"

def disk_pct(path="/"):
    s = shutil.disk_usage(path)
    return int(s.used / s.total * 100), s.free

def dir_size(p):
    total = 0
    try:
        for f in Path(p).rglob('*'):
            if f.is_file() and not f.is_symlink():
                try: total += f.stat().st_size
                except: pass
    except: pass
    return total

def write_log(session):
    with open(LOG_FILE, 'a') as f:
        f.write(json.dumps(session) + '\n')

def write_rollback(entries):
    with open(ROLLBACK_FILE, 'a') as f:
        for e in entries:
            f.write(json.dumps(e) + '\n')

# ══════════════════════════════════════════════════════════════
# SHOW LOG
# ══════════════════════════════════════════════════════════════
if '--log' in sys.argv:
    print(f"\n{C}{B}  NC2077 // CLEAN HISTORY{NC}\n")
    if not LOG_FILE.exists():
        print("  No history yet.")
    else:
        lines = LOG_FILE.read_text().strip().splitlines()
        for line in lines[-20:]:  # 20 sessions gần nhất
            s = json.loads(line)
            t = datetime.fromisoformat(s['time']).strftime('%Y-%m-%d %H:%M')
            freed = fmt_size(s.get('freed_bytes', 0))
            print(f"  {DIM}{t}{NC}  freed {G}{freed}{NC}  —  {s.get('summary','')}")
    print()
    sys.exit(0)

# ══════════════════════════════════════════════════════════════
# SHOW ROLLBACK
# ══════════════════════════════════════════════════════════════
if '--rollback' in sys.argv:
    print(f"\n{C}{B}  NC2077 // ROLLBACK LIST (50 entries mới nhất){NC}\n")
    if not ROLLBACK_FILE.exists():
        print("  No rollback data yet.")
    else:
        lines = ROLLBACK_FILE.read_text().strip().splitlines()
        for line in lines[-50:]:
            e = json.loads(line)
            t = datetime.fromisoformat(e['time']).strftime('%m-%d %H:%M')
            sz = fmt_size(e.get('size', 0))
            print(f"  {DIM}{t}{NC}  {sz:>8}  {e['type']:<20}  {e['path']}")
    print()
    sys.exit(0)

# ══════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════
print(f"\n{C}{B}")
print("  ╔═╗╦ ╦╔╗ ╔═╗╦═╗  ╔═╗╦  ╔═╗╔═╗╔╗╔")
print("  ║  ╚╦╝╠╩╗║╣ ╠╦╝  ║  ║  ║╣ ╠═╣║║║")
print("  ╚═╝ ╩ ╚═╝╚═╝╩╚═  ╚═╝╩═╝╚═╝╩ ╩╝╚╝")
print(f"{NC}")
mode_txt = f"{Y}DRY-RUN{NC}" if DRY else f"{G}LIVE{NC}"
print(f"  {DIM}NC2077 // SMART DISK CLEANER  [{mode_txt}{DIM}]{NC}")
print(f"  {DIM}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{NC}\n")

# ══════════════════════════════════════════════════════════════
# CHECK DISK
# ══════════════════════════════════════════════════════════════
hr()
print(f"{C}  ◈ DISK CHECK{NC}")
hr()

pct, free = disk_pct()
color = R if pct > 90 else Y if pct > 75 else G
print(f"  Disk usage: {color}{pct}%{NC}  |  Free: {fmt_size(free)}")
print(f"  Threshold:  {DISK_THRESHOLD}%")

if pct < DISK_THRESHOLD and not FORCE:
    print(f"\n  {G}✓  Disk OK ({pct}%) — không cần clean{NC}")
    print(f"  {DIM}Dùng --force để clean dù chưa đến threshold{NC}\n")
    sys.exit(0)

if not IS_ROOT and not DRY:
    warn("Không chạy với sudo — các lệnh pacman/paccache sẽ bị skip")
    warn("Chạy: sudo python3 cyber-clean.py để clean toàn bộ")
if DRY:
    warn("DRY-RUN mode — không xóa thật, chỉ hiện sẽ xóa gì")
else:
    action(f"Disk {pct}% — bắt đầu clean...")

# ══════════════════════════════════════════════════════════════
# DEFINE CLEAN TARGETS
# ══════════════════════════════════════════════════════════════
# Mỗi target: (tên, mô tả, hàm get_size, hàm do_clean, an_toàn?)
total_freed = 0
rollback_entries = []
summary_parts = []

def clean_section(name):
    hr()
    print(f"{C}  ◈ {name}{NC}")
    hr()

# ══ 1. PACMAN CACHE ════════════════════════════════════════════
clean_section("PACMAN CACHE")

# paccache giữ lại PACMAN_KEEP version, xóa phần còn lại
cache_dry, _ = run(f"{SUDO}paccache -dk{PACMAN_KEEP} 2>/dev/null")
# Parse size từ output
size_m = re.search(r'([\d.]+)\s*(MiB|GiB|KiB)', cache_dry)
pac_size = 0
if size_m:
    v, u = float(size_m.group(1)), size_m.group(2)
    pac_size = int(v * (1024**2 if u=='MiB' else 1024**3 if u=='GiB' else 1024))

# Xóa file download-* rác (bị interrupt)
broken = list(Path("/var/cache/pacman/pkg").glob("download-*"))
broken_size = sum(f.stat().st_size for f in broken if f.exists())

info(f"Package cache cũ: ~{fmt_size(pac_size)}")
info(f"Broken downloads: {len(broken)} files ({fmt_size(broken_size)})")

if not DRY:
    run(f"{SUDO}paccache -rk{PACMAN_KEEP} 2>/dev/null")
    for f in broken:
        try:
            rollback_entries.append({
                'time': datetime.now().isoformat(),
                'type': 'pacman_broken',
                'path': str(f),
                'size': f.stat().st_size if f.exists() else 0
            })
            f.unlink()
        except: pass
    ok(f"Pacman cache cleaned — freed ~{fmt_size(pac_size + broken_size)}")
else:
    warn(f"[DRY] Sẽ xóa ~{fmt_size(pac_size + broken_size)}")

total_freed += pac_size + broken_size
summary_parts.append(f"pacman:{fmt_size(pac_size+broken_size)}")

# ══ 2. JOURNAL LOGS ════════════════════════════════════════════
clean_section("SYSTEMD JOURNAL")

j_dry, _ = run(f"journalctl --disk-usage 2>/dev/null")
j_size_m = re.search(r'([\d.]+)\s*(M|G|K)', j_dry)
j_before = 0
if j_size_m:
    v, u = float(j_size_m.group(1)), j_size_m.group(2)
    j_before = int(v * (1024**2 if u=='M' else 1024**3 if u=='G' else 1024))

info(f"Journal hiện tại: {fmt_size(j_before)}")
info(f"Sẽ giữ lại: {JOURNAL_DAYS} ngày gần nhất")

if not DRY:
    run(f"journalctl --vacuum-time={JOURNAL_DAYS}d 2>/dev/null")
    j_after_raw, _ = run("journalctl --disk-usage 2>/dev/null")
    j_size_m2 = re.search(r'([\d.]+)\s*(M|G|K)', j_after_raw)
    j_after = 0
    if j_size_m2:
        v, u = float(j_size_m2.group(1)), j_size_m2.group(2)
        j_after = int(v * (1024**2 if u=='M' else 1024**3 if u=='G' else 1024))
    j_freed = max(j_before - j_after, 0)
    ok(f"Journal cleaned — freed {fmt_size(j_freed)}")
    total_freed += j_freed
    summary_parts.append(f"journal:{fmt_size(j_freed)}")
else:
    estimated = max(j_before - 50*1024*1024, 0)  # estimate giữ ~50MB
    warn(f"[DRY] Sẽ giữ lại ~50MB, xóa ~{fmt_size(estimated)}")
    total_freed += estimated

# ══ 3. USER CACHE ══════════════════════════════════════════════
clean_section("USER CACHE (~/.cache)")

SAFE_CACHE_DIRS = [
    ("thumbnails",        Path.home()/".cache/thumbnails",        "Thumbnail ảnh (tự rebuild)"),
    ("google-chrome",     Path.home()/".cache/google-chrome",     "Chrome cache"),
    ("chromium",          Path.home()/".cache/chromium",          "Chromium cache"),
    ("mozilla",           Path.home()/".cache/mozilla",           "Firefox cache"),
    ("yay",               Path.home()/".cache/yay",               "Yay AUR build cache"),
    ("paru",              Path.home()/".cache/paru",              "Paru AUR build cache"),
    ("pip",               Path.home()/".cache/pip",               "Pip download cache"),
    ("go",                Path.home()/"go/pkg/mod/cache",         "Go module cache"),
]

cache_freed = 0
for key, path, desc in SAFE_CACHE_DIRS:
    if not path.exists(): continue
    sz = dir_size(path)
    if sz < 1024*1024:  # bỏ qua nếu <1MB
        continue
    info(f"{desc}: {fmt_size(sz)}")
    if not DRY:
        try:
            rollback_entries.append({
                'time': datetime.now().isoformat(),
                'type': f'cache_{key}',
                'path': str(path),
                'size': sz,
                'note': 'directory — cannot restore, auto-rebuilds'
            })
            # Xóa nội dung BÊN TRONG, giữ folder gốc
            # → app đang mở không bị crash vì mất thư mục
            for item in path.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                except: pass
            cache_freed += sz
        except: pass
    else:
        warn(f"[DRY] Sẽ xóa {fmt_size(sz)}")
        cache_freed += sz

if cache_freed > 0:
    if not DRY: ok(f"Cache cleaned — freed {fmt_size(cache_freed)}")
    total_freed += cache_freed
    summary_parts.append(f"cache:{fmt_size(cache_freed)}")
else:
    info("Cache dirs clean hoặc không đáng kể")

# ══ 4. ORPHANED PACKAGES ═══════════════════════════════════════
clean_section("ORPHANED PACKAGES")

orphans_raw, _ = run("pacman -Qdtq 2>/dev/null")
orphans = [l.strip() for l in orphans_raw.splitlines() if l.strip()]

if orphans:
    warn(f"Tìm thấy {len(orphans)} orphaned packages:")
    for p in orphans:
        print(f"    {DIM}{p}{NC}")
    if not DRY:
        # Ghi rollback
        rollback_entries.append({
            'time': datetime.now().isoformat(),
            'type': 'orphaned_packages',
            'path': ', '.join(orphans),
            'size': 0,
            'note': f'Restore: sudo pacman -S {" ".join(orphans)}'
        })
        run(f"{SUDO}pacman -Rns --noconfirm {' '.join(orphans)} 2>/dev/null")
        ok(f"Removed {len(orphans)} orphaned packages")
        summary_parts.append(f"orphans:{len(orphans)}pkgs")
    else:
        warn(f"[DRY] Sẽ xóa: {', '.join(orphans)}")
else:
    ok("Không có orphaned packages")

# ══ 5. TEMP FILES ══════════════════════════════════════════════
clean_section(f"/tmp FILES CŨ HƠN {TMP_DAYS} NGÀY")

now = time.time()
tmp_freed = 0
tmp_count = 0
tmp_path = Path("/tmp")

for f in tmp_path.iterdir():
    try:
        age_days = (now - f.stat().st_mtime) / 86400
        if age_days < TMP_DAYS: continue
        # Không xóa socket, pipe, device
        if f.is_socket() or f.is_block_device() or f.is_char_device(): continue
        # Không xóa nếu đang được process nào dùng
        lsof_out, _ = run(f"lsof +D {f} 2>/dev/null | wc -l")
        if int(lsof_out or 0) > 0: continue

        sz = dir_size(f) if f.is_dir() else (f.stat().st_size if f.is_file() else 0)
        if sz == 0: continue

        tmp_freed += sz
        tmp_count += 1

        if not DRY:
            rollback_entries.append({
                'time': datetime.now().isoformat(),
                'type': 'tmp_file',
                'path': str(f),
                'size': sz,
                'note': f'age={age_days:.0f}d — tmp files cannot be restored'
            })
            if f.is_dir(): shutil.rmtree(f, ignore_errors=True)
            else: f.unlink(missing_ok=True)
    except: pass

if tmp_count > 0:
    if not DRY: ok(f"Cleaned {tmp_count} tmp entries — freed {fmt_size(tmp_freed)}")
    else: warn(f"[DRY] Sẽ xóa {tmp_count} entries ({fmt_size(tmp_freed)})")
    total_freed += tmp_freed
    summary_parts.append(f"tmp:{fmt_size(tmp_freed)}")
else:
    ok("Không có tmp file cũ đáng kể")

# ══════════════════════════════════════════════════════════════
# RESULT
# ══════════════════════════════════════════════════════════════
hr()
print(f"{C}  ◈ KẾT QUẢ{NC}")
hr()

pct_after, free_after = disk_pct()
saved_pct = pct - pct_after if not DRY else 0

if DRY:
    print(f"\n  {Y}{B}[DRY-RUN] Nếu clean thật sẽ giải phóng:{NC}")
    print(f"  {Y}  ~{fmt_size(total_freed)}{NC}")
    print(f"  {DIM}  Disk: {pct}% → ~{max(pct-2,0)}%+ (ước tính){NC}")
else:
    print(f"\n  {G}{B}✓ CLEAN HOÀN TẤT{NC}")
    print(f"  Freed:  {G}{fmt_size(total_freed)}{NC}")
    print(f"  Disk:   {pct}% → {pct_after}%  (free: {fmt_size(free_after)})")
    if summary_parts:
        print(f"  Detail: {DIM}{' | '.join(summary_parts)}{NC}")

    # Ghi log
    session = {
        'time': datetime.now().isoformat(),
        'disk_before': pct,
        'disk_after': pct_after,
        'freed_bytes': total_freed,
        'summary': ' | '.join(summary_parts)
    }
    write_log(session)
    if rollback_entries:
        write_rollback(rollback_entries)
        print(f"\n  {DIM}Rollback list: {ROLLBACK_FILE}{NC}")

print(f"\n{C}{'━'*62}{NC}\n")
