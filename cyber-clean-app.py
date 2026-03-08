#!/usr/bin/env python3
# ╔══════════════════════════════════════════════════════════════╗
# ║  NC2077 // CYBER-CLEAN  —  Desktop App                      ║
# ║  Requires: python-pyqt6                                      ║
# ║  Install:  sudo pacman -S python-pyqt6                       ║
# ╚══════════════════════════════════════════════════════════════╝

import sys, os, subprocess, shutil, json, time, re
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QStackedWidget, QScrollArea,
    QTableWidget, QTableWidgetItem, QCheckBox, QProgressBar,
    QTextEdit, QSplitter, QMessageBox, QHeaderView, QSizePolicy
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation,
    QEasingCurve, QSize, QRect
)
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QTextCursor, QPainter,
    QLinearGradient, QBrush, QPen, QFontDatabase, QIcon
)

# ── Config ──────────────────────────────────────────────────────
DISK_THRESHOLD = 75
PACMAN_KEEP    = 1
JOURNAL_DAYS   = 7
TMP_DAYS       = 3
LOG_DIR        = Path.home() / ".local/share/cyber-clean"
LOG_FILE       = LOG_DIR / "history.jsonl"
ROLLBACK_FILE  = LOG_DIR / "rollback.jsonl"
LOG_DIR.mkdir(parents=True, exist_ok=True)

IS_ROOT = os.geteuid() == 0

def run_privileged(action, stdin_data=None):
    """Gọi helper qua pkexec — hiện cửa sổ polkit hỏi password nếu cần"""
    try:
        cmd = ['pkexec', '/usr/local/bin/cyber-clean-helper', action]
        r = subprocess.run(cmd, input=stdin_data, capture_output=True,
                          text=True, timeout=60)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

# ── Colors ───────────────────────────────────────────────────────
C = {
    'bg':     '#05090e',
    'bg2':    '#0a1520',
    'bg3':    '#0d1f2e',
    'cyan':   '#00e5ff',
    'red':    '#ff1744',
    'yellow': '#ffd600',
    'green':  '#69ff47',
    'dim':    '#3a6070',
    'text':   '#b0d4e0',
    'border': '#0d2535',
}

# ── Utilities ────────────────────────────────────────────────────
def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

def fmt_size(n):
    for u in ['B','KB','MB','GB','TB']:
        if n < 1024 or u == 'TB':
            return f"{n:.1f} {u}"
        n /= 1024

def disk_info():
    s = shutil.disk_usage('/')
    pct = int(s.used / s.total * 100)
    return pct, s.used, s.total, s.free

def dir_size(p):
    total = 0
    try:
        for f in Path(p).rglob('*'):
            if f.is_file() and not f.is_symlink():
                try: total += f.stat().st_size
                except: pass
    except: pass
    return total

# ── Clean targets definition ─────────────────────────────────────
TARGETS = [
    {'id':'pacman',  'name':'PACMAN CACHE',      'desc':'Package versions cũ — giữ 1 version mới nhất', 'safety':'safe',    'sudo':True},
    {'id':'broken',  'name':'BROKEN DOWNLOADS',  'desc':'File download bị interrupt trong cache',        'safety':'safe',    'sudo':True},
    {'id':'journal', 'name':'JOURNAL LOGS',       'desc':f'Systemd logs cũ hơn {JOURNAL_DAYS} ngày',    'safety':'safe',    'sudo':False},
    {'id':'chrome',  'name':'CHROME CACHE',       'desc':'Browser cache — tự rebuild khi cần',           'safety':'safe',    'sudo':False},
    {'id':'firefox', 'name':'FIREFOX CACHE',      'desc':'Browser cache — tự rebuild khi cần',           'safety':'safe',    'sudo':False},
    {'id':'thumbs',  'name':'THUMBNAILS',          'desc':'Image thumbnail cache — tự rebuild',           'safety':'safe',    'sudo':False},
    {'id':'yay',     'name':'YAY BUILD CACHE',    'desc':'AUR build files — xóa khi app đóng',           'safety':'caution', 'sudo':False},
    {'id':'pip',     'name':'PIP CACHE',           'desc':'Python pip download cache',                    'safety':'safe',    'sudo':False},
    {'id':'tmp',     'name':'TMP FILES',           'desc':f'/tmp files cũ hơn {TMP_DAYS} ngày',          'safety':'safe',    'sudo':False},
    {'id':'orphans', 'name':'ORPHANED PACKAGES',  'desc':'Packages không còn dependency nào cần',        'safety':'caution', 'sudo':True},
]

CACHE_PATHS = {
    'chrome':  Path.home()/'.cache/google-chrome',
    'firefox': Path.home()/'.cache/mozilla',
    'thumbs':  Path.home()/'.cache/thumbnails',
    'yay':     Path.home()/'.cache/yay',
    'pip':     Path.home()/'.cache/pip',
}

# ══════════════════════════════════════════════════════════════════
# WORKER THREAD — chạy clean/scan không block UI
# ══════════════════════════════════════════════════════════════════
class CleanWorker(QThread):
    log     = pyqtSignal(str, str)   # (message, level)
    progress= pyqtSignal(int, str)   # (pct, label)
    done    = pyqtSignal(dict)       # result dict

    def __init__(self, targets, dry=True):
        super().__init__()
        self.targets = targets
        self.dry = dry

    def run(self):
        total_freed = 0
        rollback = []
        summary  = []
        steps = len(self.targets)

        self.log.emit('═'*50, 'head')
        mode = 'DRY-RUN' if self.dry else 'LIVE CLEAN'
        self.log.emit(f'  {mode} — {datetime.now().strftime("%H:%M:%S")}', 'head')
        self.log.emit('═'*50, 'head')

        for i, tid in enumerate(self.targets):
            pct = int((i / steps) * 90)
            t = next((x for x in TARGETS if x['id']==tid), None)
            if not t: continue

            self.progress.emit(pct, f'SCANNING {t["name"]}...')
            self.log.emit(f'\n  ▶ {t["name"]}', 'head')

            freed = 0

            # ── pacman cache
            if tid == 'pacman':
                out, _ = run(f'paccache -dk{PACMAN_KEEP} 2>/dev/null')  # dry check không cần sudo
                m = re.search(r'([\d.]+)\s*(MiB|GiB|KiB)', out)
                sz = 0
                if m:
                    v,u = float(m.group(1)), m.group(2)
                    sz = int(v*(1024**2 if u=='MiB' else 1024**3 if u=='GiB' else 1024))
                if not self.dry:
                    run_privileged('paccache')
                    freed = sz
                    self.log.emit(f'  ✓  Freed {fmt_size(sz)}', 'ok')
                else:
                    self.log.emit(f'  ~  Would free ~{fmt_size(sz)}', 'dry')
                    freed = sz

            # ── broken downloads
            elif tid == 'broken':
                broken = list(Path('/var/cache/pacman/pkg').glob('download-*')) if IS_ROOT or True else []
                sz = sum(f.stat().st_size for f in broken if f.exists())
                if not self.dry:
                    run_privileged('broken-downloads')
                    rollback.append({'time':datetime.now().isoformat(),'type':'pacman_broken','path':'/var/cache/pacman/pkg/download-*','size':sz,'note':'tmp file'})
                    freed = sz
                    self.log.emit(f'  ✓  Removed {len(broken)} broken files ({fmt_size(sz)})', 'ok')
                else:
                    self.log.emit(f'  ~  Found {len(broken)} files ({fmt_size(sz)})', 'dry')
                    freed = sz

            # ── journal
            elif tid == 'journal':
                out, _ = run('journalctl --disk-usage 2>/dev/null')
                m = re.search(r'([\d.]+)\s*(M|G|K)', out)
                before = 0
                if m:
                    v,u = float(m.group(1)),m.group(2)
                    before = int(v*(1024**2 if u=='M' else 1024**3 if u=='G' else 1024))
                self.log.emit(f'  ·  Journal size: {fmt_size(before)}', 'info')
                if not self.dry:
                    run_privileged('journal')
                    out2,_ = run('journalctl --disk-usage 2>/dev/null')
                    m2 = re.search(r'([\d.]+)\s*(M|G|K)', out2)
                    after = 0
                    if m2:
                        v,u = float(m2.group(1)),m2.group(2)
                        after = int(v*(1024**2 if u=='M' else 1024**3 if u=='G' else 1024))
                    freed = max(before - after, 0)
                    self.log.emit(f'  ✓  Freed {fmt_size(freed)}', 'ok')
                else:
                    freed = max(before - 50*1024*1024, 0)
                    self.log.emit(f'  ~  Would free ~{fmt_size(freed)}', 'dry')

            # ── browser/cache dirs
            elif tid in CACHE_PATHS:
                path = CACHE_PATHS[tid]
                if not path.exists():
                    self.log.emit(f'  ·  Not found, skip', 'info')
                    continue
                sz = dir_size(path)
                self.log.emit(f'  ·  Size: {fmt_size(sz)}', 'info')
                if not self.dry:
                    for item in path.iterdir():
                        try:
                            rollback.append({'time':datetime.now().isoformat(),'type':f'cache_{tid}','path':str(item),'size':0,'note':'auto-rebuilds'})
                            if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                            else: item.unlink(missing_ok=True)
                        except: pass
                    freed = sz
                    self.log.emit(f'  ✓  Cleared {fmt_size(sz)}', 'ok')
                else:
                    freed = sz
                    self.log.emit(f'  ~  Would clear {fmt_size(sz)}', 'dry')

            # ── orphaned packages
            elif tid == 'orphans':
                out, _ = run('pacman -Qdtq 2>/dev/null')
                pkgs = [l.strip() for l in out.splitlines() if l.strip()]
                if not pkgs:
                    self.log.emit('  ✓  No orphans found', 'ok')
                    continue
                for p in pkgs:
                    self.log.emit(f'  ·  {p}', 'info')
                if not self.dry:
                    rollback.append({'time':datetime.now().isoformat(),'type':'orphaned_packages','path':' '.join(pkgs),'size':0,'note':f'sudo pacman -S {" ".join(pkgs)}'})
                    run_privileged('pacman-orphans', stdin_data=' '.join(pkgs))
                    self.log.emit(f'  ✓  Removed {len(pkgs)} orphaned packages', 'ok')
                    summary.append(f'orphans:{len(pkgs)}pkgs')
                else:
                    self.log.emit(f'  ~  Would remove {len(pkgs)} packages', 'dry')

            # ── /tmp old files
            elif tid == 'tmp':
                now = time.time()
                count, sz = 0, 0
                for f in Path('/tmp').iterdir():
                    try:
                        if (now - f.stat().st_mtime)/86400 < TMP_DAYS: continue
                        if f.is_socket() or f.is_block_device(): continue
                        lsof,_ = run(f'lsof +D {f} 2>/dev/null | wc -l')
                        if int(lsof or 0) > 0: continue
                        fsz = dir_size(f) if f.is_dir() else f.stat().st_size
                        sz += fsz; count += 1
                        if not self.dry:
                            rollback.append({'time':datetime.now().isoformat(),'type':'tmp','path':str(f),'size':fsz,'note':'tmp — cannot restore'})
                            if f.is_dir(): shutil.rmtree(f,ignore_errors=True)
                            else: f.unlink(missing_ok=True)
                    except: pass
                if count:
                    msg = f'  ✓  Removed {count} files ({fmt_size(sz)})' if not self.dry else f'  ~  Would remove {count} files ({fmt_size(sz)})'
                    self.log.emit(msg, 'ok' if not self.dry else 'dry')
                    freed = sz
                else:
                    self.log.emit('  ✓  Nothing to clean', 'ok')

            total_freed += freed
            if freed > 0:
                summary.append(f'{tid}:{fmt_size(freed)}')

        self.progress.emit(100, 'DONE')
        self.log.emit('\n' + '═'*50, 'head')
        label = 'ESTIMATED' if self.dry else 'FREED'
        self.log.emit(f'  TOTAL {label}: {fmt_size(total_freed)}', 'ok')

        pct_after, *_ = disk_info()
        result = {
            'freed': total_freed,
            'dry': self.dry,
            'summary': ' | '.join(summary),
            'rollback': rollback,
            'disk_after': pct_after,
        }
        self.done.emit(result)


# ══════════════════════════════════════════════════════════════════
# STYLED WIDGETS
# ══════════════════════════════════════════════════════════════════
def styled_btn(text, color='cyan', small=False):
    col = C[color]
    btn = QPushButton(text)
    size = '10px' if small else '11px'
    pad  = '6px 14px' if small else '8px 20px'
    btn.setStyleSheet(f"""
        QPushButton {{
            color: {col};
            border: 1px solid {col}44;
            background: transparent;
            font-family: 'Share Tech Mono', monospace;
            font-size: {size};
            letter-spacing: 2px;
            padding: {pad};
        }}
        QPushButton:hover {{
            background: {col}18;
            border-color: {col}88;
        }}
        QPushButton:pressed {{
            background: {col}30;
        }}
        QPushButton:disabled {{
            opacity: 0.3;
            color: {C['dim']};
            border-color: {C['dim']}44;
        }}
    """)
    return btn

def section_label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {C['dim']};
        font-family: 'Share Tech Mono', monospace;
        font-size: 9px;
        letter-spacing: 3px;
        padding: 12px 0 4px 0;
    """)
    return lbl

def card_frame():
    f = QFrame()
    f.setStyleSheet(f"""
        QFrame {{
            background: {C['bg2']};
            border: 1px solid {C['border']};
        }}
    """)
    return f

# ══════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════════
class CyberClean(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('NC2077 // CYBER-CLEAN')
        self.setMinimumSize(1000, 680)
        self.resize(1100, 720)
        self.worker = None
        self.selected = set(['pacman','broken','journal','chrome','thumbs'])
        self._setup_fonts()
        self._setup_palette()
        self._build_ui()
        self._start_clock()
        self._refresh_disk()

    def _setup_fonts(self):
        QFontDatabase.addApplicationFont('/usr/share/fonts/TTF/ShareTechMono-Regular.ttf')

    def _setup_palette(self):
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window,     QColor(C['bg']))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(C['text']))
        pal.setColor(QPalette.ColorRole.Base,       QColor(C['bg2']))
        pal.setColor(QPalette.ColorRole.Text,       QColor(C['text']))
        QApplication.setPalette(pal)

    # ── UI BUILD ──────────────────────────────────────────────────
    def _build_ui(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {C['bg']};
                color: {C['text']};
                font-family: 'Share Tech Mono', monospace;
            }}
            QScrollBar:vertical {{
                background: {C['bg2']}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C['dim']}; border-radius: 3px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QTableWidget {{
                background: {C['bg2']};
                border: 1px solid {C['border']};
                gridline-color: {C['border']};
                font-size: 11px;
            }}
            QTableWidget::item {{ padding: 6px 10px; border: none; }}
            QTableWidget::item:selected {{
                background: {C['cyan']}18;
                color: {C['cyan']};
            }}
            QHeaderView::section {{
                background: {C['bg']};
                color: {C['dim']};
                border: none;
                border-bottom: 1px solid {C['border']};
                padding: 6px 10px;
                font-size: 9px;
                letter-spacing: 2px;
            }}
            QCheckBox {{ color: {C['text']}; spacing: 6px; }}
            QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {C['dim']};
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                background: {C['cyan']}30;
                border-color: {C['cyan']};
                image: none;
            }}
            QProgressBar {{
                background: {C['bg3']};
                border: none;
                height: 3px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['cyan']}, stop:1 {C['green']});
            }}
        """)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0,0,0,0)
        root_layout.setSpacing(0)

        # Header
        root_layout.addWidget(self._build_header())

        # Body
        body = QHBoxLayout()
        body.setContentsMargins(0,0,0,0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar(), 0)
        body.addWidget(self._build_main(),    1)
        body_w = QWidget()
        body_w.setLayout(body)
        root_layout.addWidget(body_w, 1)

    def _build_header(self):
        h = QFrame()
        h.setFixedHeight(60)
        h.setStyleSheet(f"""
            QFrame {{
                background: {C['bg']};
                border-bottom: 1px solid {C['border']};
            }}
        """)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(24,0,24,0)

        # Logo
        logo_col = QVBoxLayout()
        logo_col.setSpacing(2)
        title = QLabel('CYBER-CLEAN')
        title.setStyleSheet(f"""
            color: {C['cyan']};
            font-family: 'Orbitron', 'Share Tech Mono', monospace;
            font-size: 18px;
            font-weight: 900;
            letter-spacing: 4px;
        """)
        sub = QLabel('NC2077 // DISK MANAGEMENT SYSTEM')
        sub.setStyleSheet(f'color: {C["dim"]}; font-size: 9px; letter-spacing: 3px;')
        logo_col.addWidget(title)
        logo_col.addWidget(sub)
        lay.addLayout(logo_col)
        lay.addStretch()

        # Status
        self.clock_lbl = QLabel('--:--:--')
        self.clock_lbl.setStyleSheet(f'color: {C["dim"]}; font-size: 10px; letter-spacing: 2px;')

        dot_lbl = QLabel('● SYSTEM ACTIVE')
        dot_lbl.setStyleSheet(f'color: {C["green"]}; font-size: 9px; letter-spacing: 2px;')

        polkit_ok = Path('/usr/share/polkit-1/actions/com.nc2077.cyberclean.policy').exists()
        self.sudo_lbl = QLabel('POLKIT: OK' if polkit_ok else '⚠ RUN INSTALLER')
        color = C['green'] if polkit_ok else C['yellow']
        self.sudo_lbl.setStyleSheet(f'color: {color}; font-size: 9px; letter-spacing: 2px;')

        for w in [dot_lbl, self.sudo_lbl, self.clock_lbl]:
            lay.addWidget(w)
            lay.addSpacing(20)

        return h

    def _build_sidebar(self):
        side = QFrame()
        side.setFixedWidth(220)
        side.setStyleSheet(f"""
            QFrame {{
                background: {C['bg']};
                border-right: 1px solid {C['border']};
            }}
        """)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 20, 0, 20)
        lay.setSpacing(2)

        self.nav_btns = {}
        nav_items = [
            ('dashboard', '◈  DASHBOARD'),
            ('clean',     '⚡  CLEAN'),
            ('log',       '◎  HISTORY'),
            ('rollback',  '↺  ROLLBACK'),
        ]
        for page_id, label in nav_items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: {C['dim']};
                    background: transparent;
                    border: none;
                    border-left: 2px solid transparent;
                    text-align: left;
                    padding: 10px 20px;
                    font-family: 'Share Tech Mono', monospace;
                    font-size: 11px;
                    letter-spacing: 1px;
                }}
                QPushButton:hover {{
                    color: {C['text']};
                    background: {C['cyan']}08;
                }}
                QPushButton:checked {{
                    color: {C['cyan']};
                    background: {C['cyan']}0f;
                    border-left: 2px solid {C['cyan']};
                }}
            """)
            btn.clicked.connect(lambda _, pid=page_id: self._nav(pid))
            self.nav_btns[page_id] = btn
            lay.addWidget(btn)

        lay.addSpacing(20)

        # Disk meter
        disk_frame = QFrame()
        disk_frame.setStyleSheet(f"""
            QFrame {{
                background: {C['bg2']};
                border: 1px solid {C['border']};
                margin: 0 16px;
            }}
        """)
        df_lay = QVBoxLayout(disk_frame)
        df_lay.setContentsMargins(12,10,12,10)
        df_lay.setSpacing(6)

        disk_header = QHBoxLayout()
        disk_lbl = QLabel('ROOT /')
        disk_lbl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;')
        self.disk_pct_lbl = QLabel('78%')
        self.disk_pct_lbl.setStyleSheet(f'color:{C["cyan"]};font-size:9px;letter-spacing:1px;')
        disk_header.addWidget(disk_lbl)
        disk_header.addStretch()
        disk_header.addWidget(self.disk_pct_lbl)
        df_lay.addLayout(disk_header)

        self.disk_bar = QProgressBar()
        self.disk_bar.setRange(0,100)
        self.disk_bar.setValue(78)
        self.disk_bar.setTextVisible(False)
        self.disk_bar.setFixedHeight(3)
        df_lay.addWidget(self.disk_bar)

        self.disk_detail = QLabel('35.0 GB / 48.0 GB')
        self.disk_detail.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:1px;')
        df_lay.addWidget(self.disk_detail)

        lay.addWidget(disk_frame)
        lay.addStretch()

        # Config info
        cfg = QLabel(f'THRESHOLD: {DISK_THRESHOLD}%\nINTERVAL: 6H\nAUTO: ENABLED')
        cfg.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:1px;padding:0 20px;line-height:2;')
        lay.addWidget(cfg)

        return side

    def _build_main(self):
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f'background:{C["bg"]};')
        self.stack.addWidget(self._build_dashboard())  # 0
        self.stack.addWidget(self._build_clean())       # 1
        self.stack.addWidget(self._build_log())         # 2
        self.stack.addWidget(self._build_rollback())    # 3
        return self.stack

    # ── DASHBOARD ────────────────────────────────────────────────
    def _build_dashboard(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,24,28,24)
        lay.setSpacing(0)

        # Title row
        title_row = QHBoxLayout()
        t = QLabel('SYSTEM OVERVIEW')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:15px;letter-spacing:3px;font-weight:bold;')
        ref = styled_btn('↻  REFRESH', small=True)
        ref.clicked.connect(self._refresh_disk)
        title_row.addWidget(t)
        title_row.addStretch()
        title_row.addWidget(ref)
        lay.addLayout(title_row)
        lay.addSpacing(20)

        # Stat cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.stat_cards = {}
        stats = [
            ('disk',  'DISK',        '78%',  C['yellow']),
            ('ram',   'RAM',         '32%',  C['cyan']),
            ('cpu',   'CPU LOAD',    '46%',  C['cyan']),
            ('temp',  'TEMPERATURE', '58°C', C['green']),
        ]
        for sid, name, val, col in stats:
            card = card_frame()
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16,14,16,14)
            cl.setSpacing(4)
            nlbl = QLabel(name)
            nlbl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;')
            vlbl = QLabel(val)
            vlbl.setStyleSheet(f'color:{col};font-size:24px;font-weight:bold;letter-spacing:2px;')
            cl.addWidget(nlbl)
            cl.addWidget(vlbl)
            self.stat_cards[sid] = vlbl
            cards_row.addWidget(card)
        lay.addLayout(cards_row)
        lay.addSpacing(20)

        # Polkit status
        polkit_ok = Path('/usr/share/polkit-1/actions/com.nc2077.cyberclean.policy').exists()
        if not polkit_ok:
            warn_frame = QFrame()
            warn_frame.setStyleSheet(f"""
                QFrame {{
                    background: {C['yellow']}08;
                    border: 1px solid {C['yellow']}30;
                    border-left: 3px solid {C['yellow']};
                }}
            """)
            wl = QHBoxLayout(warn_frame)
            wl.setContentsMargins(12,8,12,8)
            wlbl = QLabel('⚠  Chưa cài polkit policy. Chạy install-cyber-clean.sh để setup.')
            wlbl.setStyleSheet(f'color:{C["dim"]};font-size:10px;')
            wl.addWidget(wlbl)
            lay.addWidget(warn_frame)
            lay.addSpacing(16)

        # Quick targets preview
        lay.addWidget(section_label('SAFE CLEAN TARGETS — OVERVIEW'))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('border:none;background:transparent;')
        scroll_w = QWidget()
        scroll_lay = QVBoxLayout(scroll_w)
        scroll_lay.setContentsMargins(0,0,0,0)
        scroll_lay.setSpacing(6)

        for t in TARGETS:
            row = QFrame()
            safety_color = C['green'] if t['safety']=='safe' else C['yellow']
            row.setStyleSheet(f"""
                QFrame {{
                    background: {C['bg2']};
                    border: 1px solid {C['border']};
                    border-left: 2px solid {safety_color};
                }}
                QFrame:hover {{ background: {C['bg3']}; }}
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14,10,14,10)

            name_col = QVBoxLayout()
            name_col.setSpacing(2)
            nl = QLabel(t['name'])
            nl.setStyleSheet(f'color:{C["text"]};font-size:11px;letter-spacing:1px;')
            dl = QLabel(t['desc'])
            dl.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
            name_col.addWidget(nl)
            name_col.addWidget(dl)

            badge = QLabel(t['safety'].upper())
            badge_col = safety_color
            badge.setStyleSheet(f"""
                color:{badge_col};
                border:1px solid {badge_col}44;
                font-size:9px;letter-spacing:2px;
                padding:2px 8px;
            """)

            sudo_lbl = QLabel('[SUDO]') if t['sudo'] else QLabel('')
            sudo_lbl.setStyleSheet(f'color:{C["yellow"]};font-size:9px;')

            rl.addLayout(name_col, 1)
            rl.addWidget(sudo_lbl)
            rl.addSpacing(12)
            rl.addWidget(badge)
            scroll_lay.addWidget(row)

        scroll_lay.addStretch()
        scroll.setWidget(scroll_w)
        lay.addWidget(scroll, 1)
        return w

    # ── CLEAN PAGE ────────────────────────────────────────────────
    def _build_clean(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,24,28,24)
        lay.setSpacing(0)

        # Title
        title_row = QHBoxLayout()
        t = QLabel('CLEAN TARGETS')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:15px;letter-spacing:3px;font-weight:bold;')
        self.dry_chk = QCheckBox('DRY-RUN MODE')
        self.dry_chk.setChecked(True)
        self.dry_chk.setStyleSheet(f'color:{C["yellow"]};font-size:10px;letter-spacing:1px;')
        title_row.addWidget(t)
        title_row.addStretch()
        title_row.addWidget(self.dry_chk)
        lay.addLayout(title_row)
        lay.addSpacing(16)

        # Targets scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('border:none;background:transparent;')
        scroll.setMaximumHeight(280)
        scroll_w = QWidget()
        scroll_lay = QVBoxLayout(scroll_w)
        scroll_lay.setContentsMargins(0,0,0,0)
        scroll_lay.setSpacing(5)

        self.target_checks = {}
        for t in TARGETS:
            row = QFrame()
            safety_color = C['green'] if t['safety']=='safe' else C['yellow']
            row.setStyleSheet(f"""
                QFrame {{
                    background: {C['bg2']};
                    border: 1px solid {C['border']};
                    border-left: 2px solid {safety_color};
                }}
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14,8,14,8)

            chk = QCheckBox()
            chk.setChecked(t['id'] in self.selected)
            chk.stateChanged.connect(lambda s, tid=t['id']: self._toggle_target(tid, s))
            self.target_checks[t['id']] = chk

            name_col = QVBoxLayout()
            name_col.setSpacing(1)
            nl = QLabel(f'{t["name"]}' + (' [SUDO]' if t['sudo'] else ''))
            nl.setStyleSheet(f'color:{C["text"]};font-size:11px;')
            dl = QLabel(t['desc'])
            dl.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
            name_col.addWidget(nl)
            name_col.addWidget(dl)

            badge = QLabel(t['safety'].upper())
            badge_col = safety_color
            badge.setStyleSheet(f'color:{badge_col};font-size:9px;letter-spacing:1px;border:1px solid {badge_col}44;padding:2px 6px;')

            rl.addWidget(chk)
            rl.addSpacing(8)
            rl.addLayout(name_col, 1)
            rl.addWidget(badge)
            scroll_lay.addWidget(row)

        scroll.setWidget(scroll_w)
        lay.addWidget(scroll)
        lay.addSpacing(12)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        dry_btn   = styled_btn('🔍  DRY-RUN', 'cyan')
        clean_btn = styled_btn('⚡  CLEAN NOW', 'red')
        all_btn   = styled_btn('☑  ALL', small=True)
        none_btn  = styled_btn('☐  NONE', small=True)
        dry_btn.clicked.connect(self._run_dry)
        clean_btn.clicked.connect(self._run_clean)
        all_btn.clicked.connect(self._select_all)
        none_btn.clicked.connect(self._select_none)
        for b in [dry_btn, clean_btn, all_btn, none_btn]:
            btn_row.addWidget(b)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        lay.addSpacing(12)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setVisible(False)
        self.progress_lbl = QLabel('')
        self.progress_lbl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:1px;')
        self.progress_lbl.setVisible(False)
        lay.addWidget(self.progress_bar)
        lay.addWidget(self.progress_lbl)
        lay.addSpacing(8)

        # Terminal output
        lbl = section_label('TERMINAL OUTPUT')
        lay.addWidget(lbl)
        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setStyleSheet(f"""
            QTextEdit {{
                background: #020609;
                color: {C['text']};
                border: 1px solid {C['border']};
                font-family: 'Share Tech Mono', monospace;
                font-size: 11px;
                line-height: 1.6;
                padding: 12px;
            }}
        """)
        self.terminal.setPlaceholderText('  → Chọn targets và nhấn DRY-RUN để xem trước...')
        lay.addWidget(self.terminal, 1)
        return w

    # ── LOG PAGE ──────────────────────────────────────────────────
    def _build_log(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,24,28,24)
        lay.setSpacing(0)

        title_row = QHBoxLayout()
        t = QLabel('HISTORY LOG')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:15px;letter-spacing:3px;font-weight:bold;')
        clr = styled_btn('✕  CLEAR', 'red', small=True)
        clr.clicked.connect(self._clear_log)
        title_row.addWidget(t)
        title_row.addStretch()
        title_row.addWidget(clr)
        lay.addLayout(title_row)
        lay.addSpacing(16)

        self.log_table = QTableWidget(0, 5)
        self.log_table.setHorizontalHeaderLabels(['TIME','DISK BEFORE','DISK AFTER','FREED','DETAIL'])
        self.log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(self.log_table, 1)
        return w

    # ── ROLLBACK PAGE ─────────────────────────────────────────────
    def _build_rollback(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,24,28,24)
        lay.setSpacing(0)

        t = QLabel('ROLLBACK LIST')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:15px;letter-spacing:3px;font-weight:bold;')
        lay.addWidget(t)
        lay.addSpacing(6)

        info = QLabel('Danh sách file đã xóa. Cache tự rebuild. Packages: dùng lệnh ở cột NOTE để restore.')
        info.setStyleSheet(f'color:{C["dim"]};font-size:10px;')
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addSpacing(16)

        self.rollback_table = QTableWidget(0, 4)
        self.rollback_table.setHorizontalHeaderLabels(['TIME','TYPE','SIZE','PATH / NOTE'])
        self.rollback_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.rollback_table.verticalHeader().setVisible(False)
        self.rollback_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.rollback_table, 1)
        return w

    # ── NAVIGATION ────────────────────────────────────────────────
    def _nav(self, page_id):
        pages = ['dashboard','clean','log','rollback']
        idx   = pages.index(page_id)
        self.stack.setCurrentIndex(idx)
        for k,b in self.nav_btns.items():
            b.setChecked(k == page_id)
        if page_id == 'log':      self._load_log()
        if page_id == 'rollback': self._load_rollback()

    # ── CLOCK ─────────────────────────────────────────────────────
    def _start_clock(self):
        self._nav('dashboard')
        self.nav_btns['dashboard'].setChecked(True)
        timer = QTimer(self)
        timer.timeout.connect(lambda: self.clock_lbl.setText(
            datetime.now().strftime('%H:%M:%S')))
        timer.start(1000)

    # ── DISK REFRESH ─────────────────────────────────────────────
    def _refresh_disk(self):
        pct, used, total, free = disk_info()
        color = C['red'] if pct>90 else C['yellow'] if pct>75 else C['cyan']
        self.disk_pct_lbl.setText(f'{pct}%')
        self.disk_pct_lbl.setStyleSheet(f'color:{color};font-size:9px;letter-spacing:1px;')
        self.disk_bar.setValue(pct)
        self.disk_detail.setText(f'{fmt_size(used)} / {fmt_size(total)}')
        if 'disk' in self.stat_cards:
            c = C['red'] if pct>90 else C['yellow'] if pct>75 else C['cyan']
            self.stat_cards['disk'].setText(f'{pct}%')
            self.stat_cards['disk'].setStyleSheet(f'color:{c};font-size:24px;font-weight:bold;letter-spacing:2px;')
        # RAM
        try:
            ram_pct = int(subprocess.check_output("awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{printf \"%d\",((t-a)/t)*100}' /proc/meminfo", shell=True).decode().strip())
            c = C['red'] if ram_pct>85 else C['yellow'] if ram_pct>70 else C['cyan']
            self.stat_cards['ram'].setText(f'{ram_pct}%')
            self.stat_cards['ram'].setStyleSheet(f'color:{c};font-size:24px;font-weight:bold;letter-spacing:2px;')
        except: pass
        # Temp
        try:
            best = 0
            for f in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
                try: best = max(best, int(f.read_text())//1000)
                except: pass
            if best:
                c = C['red'] if best>85 else C['yellow'] if best>75 else C['green']
                self.stat_cards['temp'].setText(f'{best}°C')
                self.stat_cards['temp'].setStyleSheet(f'color:{c};font-size:24px;font-weight:bold;letter-spacing:2px;')
        except: pass

    # ── TARGET SELECTION ─────────────────────────────────────────
    def _toggle_target(self, tid, state):
        if state: self.selected.add(tid)
        else: self.selected.discard(tid)

    def _select_all(self):
        self.selected = set(t['id'] for t in TARGETS)
        for tid, chk in self.target_checks.items():
            chk.setChecked(True)

    def _select_none(self):
        self.selected.clear()
        for chk in self.target_checks.values():
            chk.setChecked(False)

    # ── RUN CLEAN ────────────────────────────────────────────────
    def _run_dry(self):
        self.dry_chk.setChecked(True)
        self._start_worker(dry=True)

    def _run_clean(self):
        if not self.selected:
            QMessageBox.warning(self, 'No targets', 'Chưa chọn target nào!')
            return
        # CLEAN NOW luôn chạy thật — không quan tâm checkbox dry-run
        targets_txt = '\n'.join(f'  • {t["name"]}' for t in TARGETS if t['id'] in self.selected)
        msg = QMessageBox(self)
        msg.setWindowTitle('Confirm Clean')
        msg.setText(f'Sẽ xóa {len(self.selected)} targets:\n\n{targets_txt}\n\nKhông thể hoàn tác với cache files.')
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setStyleSheet(f'background:{C["bg2"]};color:{C["text"]};font-family:monospace;')
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        self._start_worker(dry=False)  # luôn clean thật

    def _start_worker(self, dry):
        if self.worker and self.worker.isRunning():
            return
        self.terminal.clear()
        self.progress_bar.setVisible(True)
        self.progress_lbl.setVisible(True)
        self.progress_bar.setValue(0)
        self.worker = CleanWorker(list(self.selected), dry=dry)
        self.worker.log.connect(self._on_log)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_log(self, msg, level):
        colors = {
            'ok':   C['green'],
            'dry':  C['yellow'],
            'warn': C['yellow'],
            'err':  C['red'],
            'head': C['cyan'],
            'info': C['dim'],
        }
        color = colors.get(level, C['text'])
        self.terminal.append(f'<span style="color:{color};font-family:monospace">{msg}</span>')
        self.terminal.moveCursor(QTextCursor.MoveOperation.End)

    def _on_progress(self, pct, label):
        self.progress_bar.setValue(pct)
        self.progress_lbl.setText(label)

    def _on_done(self, result):
        self.progress_bar.setVisible(False)
        self.progress_lbl.setVisible(False)
        if not result['dry']:
            # Save log
            session = {
                'time':         datetime.now().isoformat(),
                'disk_before':  self.disk_bar.value(),
                'disk_after':   result['disk_after'],
                'freed_bytes':  result['freed'],
                'summary':      result['summary'],
            }
            with open(LOG_FILE, 'a') as f:
                f.write(json.dumps(session)+'\n')
            if result['rollback']:
                with open(ROLLBACK_FILE, 'a') as f:
                    for e in result['rollback']:
                        f.write(json.dumps(e)+'\n')
            self._refresh_disk()

    # ── LOG/ROLLBACK LOAD ────────────────────────────────────────
    def _load_log(self):
        self.log_table.setRowCount(0)
        if not LOG_FILE.exists(): return
        entries = [json.loads(l) for l in LOG_FILE.read_text().strip().splitlines() if l]
        for e in reversed(entries):
            row = self.log_table.rowCount()
            self.log_table.insertRow(row)
            t   = datetime.fromisoformat(e['time']).strftime('%Y-%m-%d %H:%M')
            freed = fmt_size(e.get('freed_bytes',0))
            vals = [t, f"{e.get('disk_before','?')}%", f"{e.get('disk_after','?')}%", freed, e.get('summary','')]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col == 3:
                    item.setForeground(QColor(C['green']))
                self.log_table.setItem(row, col, item)

    def _clear_log(self):
        if QMessageBox.question(self,'Clear Log','Xóa toàn bộ history?') == QMessageBox.StandardButton.Yes:
            LOG_FILE.unlink(missing_ok=True)
            self.log_table.setRowCount(0)

    def _load_rollback(self):
        self.rollback_table.setRowCount(0)
        if not ROLLBACK_FILE.exists(): return
        entries = [json.loads(l) for l in ROLLBACK_FILE.read_text().strip().splitlines() if l]
        for e in reversed(entries[:200]):
            row = self.rollback_table.rowCount()
            self.rollback_table.insertRow(row)
            t    = datetime.fromisoformat(e['time']).strftime('%m-%d %H:%M')
            sz   = fmt_size(e.get('size',0))
            vals = [t, e.get('type',''), sz, e.get('note') or e.get('path','')]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col == 1: item.setForeground(QColor(C['cyan']))
                if col == 2: item.setForeground(QColor(C['yellow']))
                self.rollback_table.setItem(row, col, item)


# ── MAIN ────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName('NC2077 Cyber-Clean')
    win = CyberClean()
    win.show()
    sys.exit(app.exec())
