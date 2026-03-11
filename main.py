"""
CyberClean v2.0 — Main GUI
Cross-platform: Linux (all distros) + Windows
Tabs: Dashboard · Clean · Optimize · Startup · History · Rollback
"""
import sys, os, json, time, platform, threading
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError

# ── Dependency check ──────────────────────────────────────────
_missing = []
try:    import psutil
except: _missing.append('psutil')
try:    from PyQt6.QtWidgets import QApplication
except: _missing.append('PyQt6')

if _missing:
    print(f"[CyberClean] Missing dependencies: {', '.join(_missing)}")
    print("Install with:")
    print("  Arch:   sudo pacman -S python-psutil python-pyqt6")
    print("  Ubuntu: pip install psutil PyQt6")
    print("  Win:    pip install psutil PyQt6")
    sys.exit(1)


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QStackedWidget, QScrollArea,
    QTableWidget, QTableWidgetItem, QCheckBox, QProgressBar,
    QTextEdit, QHeaderView, QMessageBox, QSystemTrayIcon, QMenu,
    QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPointF, QRectF
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QTextCursor, QPainter, QBrush,
    QPen, QLinearGradient, QIcon, QAction, QPolygonF
)

# ── Internal imports ──────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from core.os_detect  import (IS_LINUX, IS_WINDOWS, PKG_MANAGER, platform_info,
                                HAS_POLKIT, HAS_POLKIT_AGENT, HAS_FLATPAK, HAS_DOCKER,
                                HAS_SEND2TRASH, request_windows_admin, is_windows_admin)
from utils.sysinfo   import get_snapshot, get_startup_items, toggle_startup_linux, fmt_size
from core.scanner    import SecurityScanner
from core.uninstaller import get_installed_apps, uninstall_app, InstalledApp

# ── Windows: request UAC elevation on startup ─────────────────
if IS_WINDOWS and not is_windows_admin():
    request_windows_admin()   # re-launches with admin, exits current process

if IS_LINUX:
    from core.linux_cleaner import LinuxCleaner
    CLEANER = LinuxCleaner()
elif IS_WINDOWS:
    from core.windows_cleaner import WindowsCleaner
    CLEANER = WindowsCleaner()
else:
    CLEANER = None

# ── Config ────────────────────────────────────────────────────
LOG_DIR       = Path.home() / '.local/share/cyber-clean'
LOG_FILE      = LOG_DIR / 'history.jsonl'
ROLLBACK_FILE = LOG_DIR / 'rollback.jsonl'
LOG_DIR.mkdir(parents=True, exist_ok=True)

OS = platform.system()

# ── Colors ────────────────────────────────────────────────────
C = {
    'bg':     '#05090e', 'bg2': '#0a1520', 'bg3': '#0d1f2e',
    'cyan':   '#00e5ff', 'red': '#ff1744', 'yellow': '#ffd600',
    'green':  '#69ff47', 'dim': '#3a6070', 'text': '#b0d4e0',
    'border': '#0d2535', 'purple': '#e040fb',
}

# ═════════════════════════════════════════════════════════════
# REALTIME CHART WIDGET
# ═════════════════════════════════════════════════════════════
class SparklineChart(QWidget):
    """Mini realtime line chart — cyberpunk style."""

    def __init__(self, color='#00e5ff', max_points=60, parent=None):
        super().__init__(parent)
        self.color     = QColor(color)
        self.max_pts   = max_points
        self.data      = []
        self.setMinimumHeight(60)
        self.setMaximumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet('background:transparent;')

    def push(self, value: float):
        self.data.append(max(0.0, min(100.0, value)))
        if len(self.data) > self.max_pts:
            self.data.pop(0)
        self.update()

    def paintEvent(self, _):
        if len(self.data) < 2: return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad  = 4

        # Background grid lines
        grid_pen = QPen(QColor(C['border']))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        for pct in [25, 50, 75]:
            y = h - pad - (pct / 100) * (h - pad*2)
            p.drawLine(0, int(y), w, int(y))

        # Build points
        pts = []
        for i, v in enumerate(self.data):
            x = pad + (i / (self.max_pts - 1)) * (w - pad*2)
            y = h - pad - (v / 100.0) * (h - pad*2)
            pts.append(QPointF(x, y))

        # Fill under curve
        fill_pts = [QPointF(pts[0].x(), h)] + pts + [QPointF(pts[-1].x(), h)]
        grad = QLinearGradient(0, 0, 0, h)
        fill_c = QColor(self.color)
        fill_c.setAlphaF(0.25)
        grad.setColorAt(0, fill_c)
        fill_c2 = QColor(self.color)
        fill_c2.setAlphaF(0.02)
        grad.setColorAt(1, fill_c2)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        poly = QPolygonF(fill_pts)
        p.drawPolygon(poly)

        # Line
        line_pen = QPen(self.color)
        line_pen.setWidth(2)
        p.setPen(line_pen)
        for i in range(len(pts)-1):
            p.drawLine(pts[i], pts[i+1])

        # Current value dot
        if pts:
            dot_pen = QPen(self.color)
            dot_pen.setWidth(3)
            p.setPen(dot_pen)
            p.setBrush(QBrush(self.color))
            p.drawEllipse(pts[-1], 4, 4)

        p.end()

# ═════════════════════════════════════════════════════════════
# DISK RING WIDGET
# ═════════════════════════════════════════════════════════════
class DiskRing(QWidget):
    """Circular disk usage indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.percent = 0.0
        self.setFixedSize(90, 90)

    def set_percent(self, v):
        self.percent = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect  = QRectF(8, 8, 74, 74)
        color = C['red'] if self.percent>90 else C['yellow'] if self.percent>75 else C['cyan']

        # Background ring
        bg_pen = QPen(QColor(C['bg3']))
        bg_pen.setWidth(8)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(bg_pen)
        p.drawArc(rect, 0, 360*16)

        # Fill ring
        fill_pen = QPen(QColor(color))
        fill_pen.setWidth(8)
        fill_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(fill_pen)
        span = int((self.percent / 100.0) * 360 * 16)
        p.drawArc(rect, 90*16, -span)

        # Center text
        p.setPen(QPen(QColor(color)))
        p.setFont(QFont('Share Tech Mono', 13, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 90, 90), Qt.AlignmentFlag.AlignCenter,
                   f'{int(self.percent)}%')
        p.end()

# ═════════════════════════════════════════════════════════════
# WORKER THREADS
# ═════════════════════════════════════════════════════════════
class SysInfoWorker(QThread):
    snapshot = pyqtSignal(object)
    def run(self):
        while True:
            try:
                s = get_snapshot(interval=0.3)
                self.snapshot.emit(s)
            except: pass
            self.msleep(2000)

class CleanWorker(QThread):
    log      = pyqtSignal(str, str)
    progress = pyqtSignal(int, str)
    done     = pyqtSignal(dict)

    def __init__(self, targets, dry=True):
        super().__init__()
        self.targets = targets
        self.dry = dry

    def run(self):
        total_freed = 0
        rollback    = []
        summary     = []
        steps = len(self.targets)

        self.log.emit('═'*50, 'head')
        mode = 'DRY-RUN' if self.dry else 'LIVE CLEAN'
        self.log.emit(f'  {mode} — {datetime.now().strftime("%H:%M:%S")}', 'head')
        self.log.emit(f'  OS: {OS} | PKG: {PKG_MANAGER or "n/a"}', 'info')
        self.log.emit('═'*50, 'head')

        for i, tid in enumerate(self.targets):
            pct = int((i / steps) * 90)
            self.progress.emit(pct, f'Scanning {tid}...')
            self.log.emit(f'\n  ▶ {tid.upper().replace("_"," ")}', 'head')

            result = CLEANER.clean(tid, dry=self.dry)

            if result.error:
                self.log.emit(f'  ✗  Error: {result.error}', 'err')
            elif self.dry:
                self.log.emit(f'  ~  Would free ~{fmt_size(result.freed_bytes)}', 'dry')
                if result.files_removed:
                    self.log.emit(f'  ~  {result.files_removed} items', 'dry')
            else:
                self.log.emit(f'  ✓  Freed {fmt_size(result.freed_bytes)}', 'ok')
                if result.files_removed:
                    self.log.emit(f'  ✓  {result.files_removed} items removed', 'ok')

            total_freed += result.freed_bytes
            rollback    += result.rollback
            if result.freed_bytes > 0:
                summary.append(f'{tid}:{fmt_size(result.freed_bytes)}')

        self.progress.emit(100, 'DONE')
        self.log.emit('\n' + '═'*50, 'head')
        label = 'ESTIMATED' if self.dry else 'FREED'
        self.log.emit(f'  TOTAL {label}: {fmt_size(total_freed)}', 'ok')

        self.done.emit({
            'freed': total_freed, 'dry': self.dry,
            'summary': ' | '.join(summary), 'rollback': rollback,
        })

# ═════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════
def styled_btn(text, color='cyan', small=False):
    col = C[color]
    btn = QPushButton(text)
    pad = '5px 12px' if small else '8px 20px'
    sz  = '10px'     if small else '11px'
    btn.setStyleSheet(f"""
        QPushButton {{
            color:{col}; border:1px solid {col}44; background:transparent;
            font-family:'Share Tech Mono',monospace; font-size:{sz};
            letter-spacing:2px; padding:{pad};
        }}
        QPushButton:hover  {{ background:{col}18; border-color:{col}88; }}
        QPushButton:pressed {{ background:{col}30; }}
        QPushButton:disabled {{ color:{C['dim']}; border-color:{C['dim']}33; }}
    """)
    return btn

def section_lbl(text):
    l = QLabel(text)
    l.setStyleSheet(f'color:{C["dim"]};font-family:monospace;font-size:9px;letter-spacing:3px;padding:10px 0 4px 0;')
    return l

def val_lbl(text, color='cyan', size=22):
    l = QLabel(text)
    l.setStyleSheet(f'color:{C[color]};font-size:{size}px;font-weight:bold;letter-spacing:2px;')
    return l

def card():
    f = QFrame()
    f.setStyleSheet(f'QFrame{{background:{C["bg2"]};border:1px solid {C["border"]};}}')
    return f

# ═════════════════════════════════════════════════════════════
# MAIN WINDOW
# ═════════════════════════════════════════════════════════════
class CyberCleanApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('CyberClean v2.0')
        self.setMinimumSize(1100, 700)
        self.resize(1200, 760)
        self.worker    = None
        self.selected  = set()
        self._charts   = {}
        self._snap     = None

        self._init_style()
        self._build_ui()
        self._start_sysinfo()
        self._start_clock()
        self._nav('dashboard')
        self._setup_tray()
        self._check_update_async()

    def _init_style(self):
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window,     QColor(C['bg']))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(C['text']))
        pal.setColor(QPalette.ColorRole.Base,       QColor(C['bg2']))
        pal.setColor(QPalette.ColorRole.Text,       QColor(C['text']))
        QApplication.setPalette(pal)
        self.setStyleSheet(f"""
            QMainWindow,QWidget{{background:{C['bg']};color:{C['text']};font-family:'Share Tech Mono',monospace;}}
            QScrollBar:vertical{{background:{C['bg2']};width:5px;border:none;}}
            QScrollBar::handle:vertical{{background:{C['dim']};border-radius:2px;}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
            QTableWidget{{background:{C['bg2']};border:1px solid {C['border']};gridline-color:{C['border']};font-size:11px;}}
            QTableWidget::item{{padding:5px 8px;border:none;}}
            QTableWidget::item:selected{{background:{C['cyan']}18;color:{C['cyan']};}}
            QHeaderView::section{{background:{C['bg']};color:{C['dim']};border:none;border-bottom:1px solid {C['border']};padding:5px 8px;font-size:9px;letter-spacing:2px;}}
            QCheckBox{{color:{C['text']};spacing:6px;}}
            QCheckBox::indicator{{width:13px;height:13px;border:1px solid {C['dim']};background:transparent;}}
            QCheckBox::indicator:checked{{background:{C['cyan']}28;border-color:{C['cyan']};}}
            QProgressBar{{background:{C['bg3']};border:none;height:2px;}}
            QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {C['cyan']},stop:1 {C['green']});}}
            QTextEdit{{background:#020609;color:{C['text']};border:1px solid {C['border']};font-family:'Share Tech Mono',monospace;font-size:11px;padding:10px;}}
            QMenu{{background:{C['bg2']};color:{C['text']};border:1px solid {C['border']};}}
            QMenu::item:selected{{background:{C['cyan']}22;}}
        """)

    # ── Build UI ──────────────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(0)
        lay.addWidget(self._build_header())
        body = QWidget()
        bl   = QHBoxLayout(body)
        bl.setContentsMargins(0,0,0,0)
        bl.setSpacing(0)
        bl.addWidget(self._build_sidebar(), 0)
        bl.addWidget(self._build_main(),    1)
        lay.addWidget(body, 1)

    def _build_header(self):
        h = QFrame()
        h.setFixedHeight(56)
        h.setStyleSheet(f'QFrame{{background:{C["bg"]};border-bottom:1px solid {C["border"]};}}')
        lay = QHBoxLayout(h)
        lay.setContentsMargins(24,0,24,0)

        title = QLabel('CYBER-CLEAN')
        title.setStyleSheet(f'color:{C["cyan"]};font-size:17px;font-weight:900;letter-spacing:4px;')
        ver   = QLabel('v2.0')
        ver.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;padding-left:8px;')
        sub   = QLabel(f'// {OS.upper()} · {PKG_MANAGER.upper() if PKG_MANAGER else "CROSS-PLATFORM"} · SMART DISK MANAGER')
        sub.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;')

        col = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(title)
        row.addWidget(ver)
        row.addStretch()
        col.addLayout(row)
        col.addWidget(sub)
        col.setSpacing(2)
        lay.addLayout(col)
        lay.addStretch()

        self.clock_lbl = QLabel('--:--:--')
        self.clock_lbl.setStyleSheet(f'color:{C["dim"]};font-size:10px;letter-spacing:2px;')
        dot = QLabel('● ACTIVE')
        dot.setStyleSheet(f'color:{C["green"]};font-size:9px;letter-spacing:2px;')
        for w in [dot, self.clock_lbl]:
            lay.addWidget(w)
            lay.addSpacing(20)
        return h

    def _build_sidebar(self):
        side = QFrame()
        side.setFixedWidth(210)
        side.setStyleSheet(f'QFrame{{background:{C["bg"]};border-right:1px solid {C["border"]};}}')
        lay  = QVBoxLayout(side)
        lay.setContentsMargins(0,16,0,16)
        lay.setSpacing(2)

        self.nav_btns = {}
        nav = [
            ('dashboard',  '◈  DASHBOARD'),
            ('clean',      '⚡  CLEAN'),
            ('scanner',    '🛡  SCANNER'),
            ('uninstall',  '✕  UNINSTALL'),
            ('startup',    '▷  PROCESSES'),
            ('log',        '◎  HISTORY'),
            ('rollback',   '↺  ROLLBACK'),
        ]
        for pid, label in nav:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton{{color:{C['dim']};background:transparent;border:none;
                  border-left:2px solid transparent;text-align:left;
                  padding:10px 18px;font-family:'Share Tech Mono',monospace;
                  font-size:11px;letter-spacing:1px;}}
                QPushButton:hover{{color:{C['text']};background:{C['cyan']}08;}}
                QPushButton:checked{{color:{C['cyan']};background:{C['cyan']}0e;
                  border-left:2px solid {C['cyan']};}}
            """)
            btn.clicked.connect(lambda _, p=pid: self._nav(p))
            self.nav_btns[pid] = btn
            lay.addWidget(btn)

        lay.addSpacing(16)

        # Disk ring
        dc = card()
        dl = QVBoxLayout(dc)
        dl.setContentsMargins(12,10,12,10)
        self.disk_ring = DiskRing()
        self.disk_detail_lbl = QLabel('-- / --')
        self.disk_detail_lbl.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        self.disk_detail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ring_row = QHBoxLayout()
        ring_row.addStretch()
        ring_row.addWidget(self.disk_ring)
        ring_row.addStretch()
        dl.addLayout(ring_row)
        dl.addWidget(self.disk_detail_lbl)
        dc.setStyleSheet(f'QFrame{{background:{C["bg2"]};border:1px solid {C["border"]};margin:0 14px;}}')
        lay.addWidget(dc)
        lay.addStretch()

        # Platform info
        info = platform_info()
        pi_lbl = QLabel(f'OS: {info["os"]}\nDISTRO: {info["distro"] or "n/a"}\nPKG: {info["pkg_manager"] or "n/a"}\nPY: {info["python"]}')
        pi_lbl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:1px;padding:0 18px;line-height:1.8;')
        lay.addWidget(pi_lbl)
        lay.addSpacing(8)
        # Status pills
        pills = []
        if IS_LINUX:
            pills.append(('POLKIT', C['green'] if HAS_POLKIT else C['red']))
            pills.append(('AGENT',  C['green'] if HAS_POLKIT_AGENT else C['yellow']))
            if HAS_FLATPAK: pills.append(('FLATPAK', C['cyan']))
            if HAS_DOCKER:  pills.append(('DOCKER',  C['cyan']))
            if HAS_SEND2TRASH: pills.append(('TRASH', C['green']))
        elif IS_WINDOWS:
            pills.append(('ADMIN', C['green'] if is_windows_admin() else C['yellow']))
        pill_row = QHBoxLayout()
        pill_row.setContentsMargins(12,0,12,0)
        pill_row.setSpacing(4)
        for label, col in pills:
            pl = QLabel(label)
            pl.setStyleSheet(f'color:{col};font-size:8px;letter-spacing:1px;'
                             f'border:1px solid {col}55;padding:1px 5px;')
            pill_row.addWidget(pl)
        pill_row.addStretch()
        lay.addLayout(pill_row)
        return side

    def _build_main(self):
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f'background:{C["bg"]};')
        self.stack.addWidget(self._build_dashboard())   # 0
        self.stack.addWidget(self._build_clean())        # 1
        self.stack.addWidget(self._build_scanner())      # 2
        self.stack.addWidget(self._build_uninstall())    # 3
        self.stack.addWidget(self._build_startup())    # 4
        self.stack.addWidget(self._build_log())          # 5
        self.stack.addWidget(self._build_rollback())     # 6
        return self.stack

    # ── DASHBOARD ─────────────────────────────────────────
    def _build_dashboard(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,22,28,22)
        lay.setSpacing(0)

        tr = QHBoxLayout()
        t  = QLabel('SYSTEM OVERVIEW')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        ref = styled_btn('↻ REFRESH', small=True)
        ref.clicked.connect(self._refresh_now)
        tr.addWidget(t); tr.addStretch(); tr.addWidget(ref)
        lay.addLayout(tr)
        lay.addSpacing(12)

        # ── Health Score + One-Click Fix row ──────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        # Health score card
        health_card = card()
        health_card.setFixedWidth(160)
        hcl = QVBoxLayout(health_card)
        hcl.setContentsMargins(14,12,14,12)
        hcl.setSpacing(4)
        hl = QLabel('HEALTH SCORE')
        hl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;')
        self.health_score_lbl = QLabel('—')
        self.health_score_lbl.setStyleSheet(f'color:{C["green"]};font-size:28px;font-weight:bold;letter-spacing:2px;')
        self.health_status_lbl = QLabel('Calculating...')
        self.health_status_lbl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:1px;')
        self.health_status_lbl.setWordWrap(True)
        hcl.addWidget(hl)
        hcl.addWidget(self.health_score_lbl)
        hcl.addWidget(self.health_status_lbl)
        top_row.addWidget(health_card)

        # One-Click Fix card
        fix_card = card()
        fcl = QVBoxLayout(fix_card)
        fcl.setContentsMargins(16,12,16,12)
        fcl.setSpacing(6)
        fl = QLabel('ONE-CLICK FIX')
        fl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;')
        fd = QLabel('Drop cache · Tune swap · TRIM SSD · Clean journal')
        fd.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        fd.setWordWrap(True)
        self.oneclick_btn = styled_btn('⚡  OPTIMIZE NOW', 'cyan')
        self.oneclick_btn.clicked.connect(self._one_click_fix)
        self.oneclick_log = QLabel('')
        self.oneclick_log.setStyleSheet(f'color:{C["green"]};font-size:9px;letter-spacing:1px;')
        fcl.addWidget(fl); fcl.addWidget(fd)
        fcl.addWidget(self.oneclick_btn)
        fcl.addWidget(self.oneclick_log)
        top_row.addWidget(fix_card, 1)
        lay.addLayout(top_row)
        lay.addSpacing(12)

        # Stat cards row
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        self.stat_vals = {}
        stats = [
            ('cpu',  'CPU',         '–%',  'red'),
            ('ram',  'RAM',         '–%',  'cyan'),
            ('temp', 'TEMPERATURE', '–°C', 'green'),
            ('swap', 'SWAP',        '–%',  'yellow'),
        ]
        for sid, name, init, col in stats:
            c = card()
            cl = QVBoxLayout(c)
            cl.setContentsMargins(14,12,14,12)
            nl = QLabel(name)
            nl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;')
            vl = val_lbl(init, col)
            cl.addWidget(nl); cl.addWidget(vl)
            self.stat_vals[sid] = vl
            cards_row.addWidget(c)
        lay.addLayout(cards_row)
        lay.addSpacing(16)

        # Charts row
        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        for label, sid, col in [('CPU %','cpu',C['red']),('RAM %','ram',C['cyan'])]:
            cf = card()
            cl = QVBoxLayout(cf)
            cl.setContentsMargins(12,10,12,8)
            hl = QLabel(label)
            hl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;')
            chart = SparklineChart(color=col)
            self._charts[sid] = chart
            cl.addWidget(hl)
            cl.addWidget(chart)
            charts_row.addWidget(cf)
        lay.addLayout(charts_row)
        lay.addSpacing(16)

        # Top processes
        proc_hdr = QHBoxLayout()
        proc_hdr.addWidget(section_lbl('TOP PROCESSES — CPU'))
        kill_btn = styled_btn('✕ KILL SELECTED', 'red', small=True)
        kill_btn.clicked.connect(self._kill_selected_proc)
        proc_hdr.addStretch()
        proc_hdr.addWidget(kill_btn)
        lay.addLayout(proc_hdr)
        self.proc_table = QTableWidget(0, 4)
        self.proc_table.setHorizontalHeaderLabels(['PID','NAME','CPU %','MEM %'])
        self.proc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.proc_table.verticalHeader().setVisible(False)
        self.proc_table.setMaximumHeight(180)
        self.proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.proc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(self.proc_table)

        # Disk list
        lay.addWidget(section_lbl('DISK USAGE'))
        self.disk_table = QTableWidget(0, 4)
        self.disk_table.setHorizontalHeaderLabels(['MOUNT','USED','FREE','%'])
        self.disk_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.disk_table.verticalHeader().setVisible(False)
        self.disk_table.setMaximumHeight(130)
        self.disk_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.disk_table, 1)
        return w

    # ── CLEAN ─────────────────────────────────────────────
    def _build_clean(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,22,28,22)
        lay.setSpacing(0)

        tr = QHBoxLayout()
        t  = QLabel('CLEAN TARGETS')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        tr.addWidget(t); tr.addStretch()
        lay.addLayout(tr)
        lay.addSpacing(14)

        # Target list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('border:none;background:transparent;')
        scroll.setMaximumHeight(260)
        sw  = QWidget()
        sl  = QVBoxLayout(sw)
        sl.setContentsMargins(0,0,0,0)
        sl.setSpacing(5)

        self.target_checks = {}
        targets = CLEANER.get_targets() if CLEANER else []
        for t in targets:
            row = QFrame()
            sc  = C['green'] if t.safety=='safe' else C['yellow'] if t.safety=='caution' else C['red']
            row.setStyleSheet(f'QFrame{{background:{C["bg2"]};border:1px solid {C["border"]};border-left:2px solid {sc};}}')
            rl  = QHBoxLayout(row)
            rl.setContentsMargins(12,7,12,7)
            chk = QCheckBox()
            chk.setChecked(t.safety == 'safe')
            if chk.isChecked(): self.selected.add(t.id)
            chk.stateChanged.connect(lambda s, tid=t.id: self._toggle(tid, s))
            self.target_checks[t.id] = chk
            nc  = QVBoxLayout()
            nc.setSpacing(1)
            nm  = QLabel(t.name + (' [ROOT]' if t.needs_root else ''))
            nm.setStyleSheet(f'color:{C["text"]};font-size:11px;')
            dc  = QLabel(t.desc)
            dc.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
            nc.addWidget(nm); nc.addWidget(dc)
            badge = QLabel(t.safety.upper())
            badge.setStyleSheet(f'color:{sc};font-size:9px;letter-spacing:1px;border:1px solid {sc}44;padding:2px 6px;')
            rl.addWidget(chk)
            rl.addSpacing(8)
            rl.addLayout(nc, 1)
            rl.addWidget(badge)
            sl.addWidget(row)
        sl.addStretch()
        scroll.setWidget(sw)
        lay.addWidget(scroll)
        lay.addSpacing(10)

        # Buttons
        br = QHBoxLayout()
        br.setSpacing(8)
        dry_btn   = styled_btn('🔍  DRY-RUN',   'cyan')
        clean_btn = styled_btn('⚡  CLEAN NOW', 'red')
        all_btn   = styled_btn('☑ ALL',  small=True)
        none_btn  = styled_btn('☐ NONE', small=True)
        dry_btn.clicked.connect(lambda: self._run_clean(dry=True))
        clean_btn.clicked.connect(self._confirm_clean)
        all_btn.clicked.connect(self._sel_all)
        none_btn.clicked.connect(self._sel_none)
        for b in [dry_btn, clean_btn, all_btn, none_btn]:
            br.addWidget(b)
        br.addStretch()
        lay.addLayout(br)
        lay.addSpacing(8)

        self.clean_prog = QProgressBar()
        self.clean_prog.setTextVisible(False)
        self.clean_prog.setFixedHeight(2)
        self.clean_prog.setVisible(False)
        self.clean_prog_lbl = QLabel('')
        self.clean_prog_lbl.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        self.clean_prog_lbl.setVisible(False)
        lay.addWidget(self.clean_prog)
        lay.addWidget(self.clean_prog_lbl)

        lay.addWidget(section_lbl('TERMINAL OUTPUT'))
        self.clean_terminal = QTextEdit()
        self.clean_terminal.setReadOnly(True)
        self.clean_terminal.setPlaceholderText('  → Select targets and click DRY-RUN to preview...')
        lay.addWidget(self.clean_terminal, 1)
        return w

    # ── SCANNER ─────────────────────────────────────────────
    def _build_scanner(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,22,28,22)
        lay.setSpacing(0)

        t = QLabel('🛡  SECURITY SCANNER')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        lay.addWidget(t)
        lay.addSpacing(6)

        desc = QLabel(
            'Deep scan: malware · reverse shells · crypto miners · SUID · cron backdoors\n'
            'World-writable files · suspicious autoruns · hosts hijack · network ports'
        )
        desc.setStyleSheet(f'color:{C["dim"]};font-size:10px;line-height:1.8;')
        lay.addWidget(desc)
        lay.addSpacing(16)

        # Warning boxes
        warns = [
            ('🛡', C['cyan'],   'Read-only scan — nothing is deleted automatically.'),
            ('⚠', C['yellow'], 'Review all findings before taking action.'),
            ('◆', C['green'],  'Checks: miners · shells · SUID · cron · hosts · ports · autoruns'),
        ]
        for icon, col, msg in warns:
            wf = QFrame()
            wf.setStyleSheet(f'QFrame{{background:{col}08;border:none;border-left:2px solid {col}44;}}')
            wl = QHBoxLayout(wf)
            wl.setContentsMargins(12,6,12,6)
            wl.addWidget(QLabel(f'<span style="color:{col}">{icon}</span>  <span style="color:{C["dim"]};font-size:10px;">{msg}</span>'))
            lay.addWidget(wf)
            lay.addSpacing(4)

        lay.addSpacing(10)
        br2 = QHBoxLayout()
        run_btn = styled_btn('🛡  RUN DEEP SCAN', 'cyan')
        run_btn.setFixedWidth(220)
        run_btn.clicked.connect(self._run_scanner)
        self.scan_btn = run_btn
        self.fix_btn  = styled_btn('⚡ AUTO-FIX SELECTED', 'red', small=True)
        self.fix_btn.clicked.connect(self._fix_scan_results)
        self.fix_btn.setEnabled(False)
        br2.addWidget(run_btn); br2.addWidget(self.fix_btn); br2.addStretch()
        lay.addLayout(br2)
        lay.addSpacing(12)

        lay.addWidget(section_lbl('SCAN OUTPUT'))
        self.opt_terminal = QTextEdit()
        self.opt_terminal.setReadOnly(True)
        self.opt_terminal.setPlaceholderText('  → Click RUN DEEP SCAN to start...')
        lay.addWidget(self.opt_terminal, 1)

        # Results table
        lay.addWidget(section_lbl('FINDINGS'))
        self.scan_table = QTableWidget(0, 4)
        self.scan_table.setHorizontalHeaderLabels(['SEV','CATEGORY','PATH','DETAIL'])
        self.scan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.scan_table.verticalHeader().setVisible(False)
        self.scan_table.setMaximumHeight(160)
        self.scan_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.scan_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.scan_table.itemSelectionChanged.connect(self._on_scan_select)
        lay.addWidget(self.scan_table)
        return w

    # ── UNINSTALL ───────────────────────────────────────────
    def _build_uninstall(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,22,28,22)
        lay.setSpacing(0)

        tr  = QHBoxLayout()
        t   = QLabel('APP UNINSTALLER')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        ref = styled_btn('↻ REFRESH', small=True)
        ref.clicked.connect(self._load_uninstall)
        tr.addWidget(t); tr.addStretch(); tr.addWidget(ref)
        lay.addLayout(tr)
        lay.addSpacing(6)

        info = QLabel('All installed apps. Select one or more → Uninstall.')
        info.setStyleSheet(f'color:{C["dim"]};font-size:10px;')
        lay.addWidget(info)
        lay.addSpacing(6)

        search_row = QHBoxLayout()
        from PyQt6.QtWidgets import QLineEdit
        self.uninstall_search = QLineEdit()
        self.uninstall_search.setPlaceholderText('Filter apps...')
        self.uninstall_search.setStyleSheet(f'background:{C["bg2"]};color:{C["text"]};border:1px solid {C["border"]};padding:5px 10px;font-family:monospace;font-size:11px;')
        self.uninstall_search.textChanged.connect(self._filter_uninstall)
        search_row.addWidget(self.uninstall_search)
        lay.addLayout(search_row)
        lay.addSpacing(8)

        self.uninstall_table = QTableWidget(0, 4)
        self.uninstall_table.setHorizontalHeaderLabels(['NAME','VERSION','SIZE','SOURCE'])
        self.uninstall_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.uninstall_table.verticalHeader().setVisible(False)
        self.uninstall_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.uninstall_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(self.uninstall_table, 1)

        btn_row = QHBoxLayout()
        un_btn = styled_btn('✕  UNINSTALL SELECTED', 'red')
        un_btn.clicked.connect(self._do_uninstall)
        btn_row.addWidget(un_btn); btn_row.addStretch()
        lay.addSpacing(8)
        lay.addLayout(btn_row)

        self.uninstall_log = QTextEdit()
        self.uninstall_log.setReadOnly(True)
        self.uninstall_log.setMaximumHeight(80)
        self.uninstall_log.setPlaceholderText('  → Select app and click Uninstall...')
        lay.addWidget(self.uninstall_log)
        return w

    # ── STARTUP MANAGER → PROCESS MANAGER ───────────────────────────────────
    def _build_startup(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,22,28,22)
        lay.setSpacing(0)

        tr  = QHBoxLayout()
        t   = QLabel('PROCESS & STARTUP MANAGER')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        ref = styled_btn('↻ SCAN', small=True)
        ref.clicked.connect(self._load_startup)
        tr.addWidget(t); tr.addStretch(); tr.addWidget(ref)
        lay.addLayout(tr)
        lay.addSpacing(6)

        info = QLabel('Running processes + startup items. Kill or disable as needed.')
        info.setStyleSheet(f'color:{C["dim"]};font-size:10px;')
        lay.addWidget(info)
        lay.addSpacing(14)

        self.startup_table = QTableWidget(0, 4)
        self.startup_table.setHorizontalHeaderLabels(['NAME','TYPE','ENABLED','PATH'])
        self.startup_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.startup_table.verticalHeader().setVisible(False)
        self.startup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.startup_table, 1)

        btn_row = QHBoxLayout()
        kill_btn2 = styled_btn('✕ KILL PROCESS',    'red',    small=True)
        dis_btn   = styled_btn('⏸ DISABLE STARTUP', 'yellow', small=True)
        en_btn    = styled_btn('▷ ENABLE STARTUP',  'green',  small=True)
        kill_btn2.clicked.connect(self._kill_from_startup)
        dis_btn.clicked.connect(lambda: self._toggle_startup(False))
        en_btn.clicked.connect(lambda:  self._toggle_startup(True))
        for b in [kill_btn2, dis_btn, en_btn]: btn_row.addWidget(b)
        btn_row.addStretch()
        lay.addSpacing(8)
        lay.addLayout(btn_row)
        return w

    # ── LOG ───────────────────────────────────────────────
    def _build_log(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,22,28,22)
        lay.setSpacing(0)
        tr  = QHBoxLayout()
        t   = QLabel('HISTORY LOG')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        clr = styled_btn('✕ CLEAR', 'red', small=True)
        clr.clicked.connect(self._clear_log)
        tr.addWidget(t); tr.addStretch(); tr.addWidget(clr)
        lay.addLayout(tr)
        lay.addSpacing(14)
        self.log_table = QTableWidget(0, 5)
        self.log_table.setHorizontalHeaderLabels(['TIME','DISK BEFORE','DISK AFTER','FREED','DETAIL'])
        self.log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.log_table, 1)
        return w

    # ── ROLLBACK ──────────────────────────────────────────
    def _build_rollback(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,22,28,22)
        lay.setSpacing(0)

        tr  = QHBoxLayout()
        t   = QLabel('ROLLBACK LIST')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        clr = styled_btn('✕  CLEAR LIST', 'red', small=True)
        clr.clicked.connect(self._clear_rollback)
        tr.addWidget(t); tr.addStretch(); tr.addWidget(clr)
        lay.addLayout(tr)
        lay.addSpacing(6)

        info = QLabel('Everything deleted. Cache files auto-rebuild. Packages: use command in NOTE column to restore.')
        info.setStyleSheet(f'color:{C["dim"]};font-size:10px;')
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addSpacing(14)
        self.rollback_table = QTableWidget(0, 4)
        self.rollback_table.setHorizontalHeaderLabels(['TIME','TYPE','SIZE','PATH / NOTE'])
        self.rollback_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.rollback_table.verticalHeader().setVisible(False)
        self.rollback_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.rollback_table, 1)
        return w

    def _clear_rollback(self):
        if QMessageBox.question(self, 'Clear', 'Delete rollback history?') == QMessageBox.StandardButton.Yes:
            ROLLBACK_FILE.unlink(missing_ok=True)
            self.rollback_table.setRowCount(0)

    # ── NAVIGATION ────────────────────────────────────────
    def _nav(self, pid):
        pages = ['dashboard','clean','scanner','uninstall','startup','log','rollback']
        self.stack.setCurrentIndex(pages.index(pid))
        for k, b in self.nav_btns.items():
            b.setChecked(k == pid)
        if pid == 'log':        self._load_log()
        if pid == 'rollback':   self._load_rollback()
        if pid == 'startup':    self._load_processes()
        if pid == 'uninstall':  self._load_uninstall()
        if pid == 'clean' and IS_LINUX and not HAS_POLKIT_AGENT:
            self._show_polkit_warning()

    # ── ONE-CLICK FIX ─────────────────────────────────────
    def _one_click_fix(self):
        self.oneclick_btn.setEnabled(False)
        self.oneclick_log.setText('Running...')
        import subprocess as _sp

        class OneClickWorker(QThread):
            done = pyqtSignal(str, bool)
            def run(self_w):
                HELPER = '/usr/local/bin/cyber-clean-helper'
                results = []
                # 1. Drop page cache (root)
                r = _sp.run(f'sudo -n {HELPER} drop-cache', shell=True,
                            capture_output=True, text=True, timeout=15)
                results.append(('Drop cache', r.returncode == 0))
                # 2. Tune swappiness
                r = _sp.run(f'sudo -n {HELPER} swappiness', shell=True,
                            capture_output=True, text=True, timeout=10)
                results.append(('Swappiness→10', r.returncode == 0))
                # 3. SSD TRIM
                r = _sp.run(f'sudo -n {HELPER} fstrim', shell=True,
                            capture_output=True, text=True, timeout=30)
                results.append(('SSD TRIM', r.returncode == 0))
                # 4. Journal vacuum
                r = _sp.run(f'sudo -n {HELPER} journal', shell=True,
                            capture_output=True, text=True, timeout=20)
                results.append(('Journal', r.returncode == 0))
                # 5. Pacman cache (if applicable)
                import shutil
                if shutil.which('paccache'):
                    r = _sp.run(f'sudo -n {HELPER} paccache', shell=True,
                                capture_output=True, text=True, timeout=60)
                    results.append(('Pacman cache', r.returncode == 0))
                ok_count = sum(1 for _, ok in results if ok)
                summary = f'✓ {ok_count}/{len(results)} done: ' + \
                          ' · '.join(f'{"✓" if ok else "~"}{n}' for n, ok in results)
                self_w.done.emit(summary, ok_count > 0)

        self._oneclick_worker = OneClickWorker()
        self._oneclick_worker.done.connect(self._on_oneclick_done)
        self._oneclick_worker.start()

    def _on_oneclick_done(self, summary, success):
        self.oneclick_btn.setEnabled(True)
        col = C['green'] if success else C['yellow']
        self.oneclick_log.setText(summary)
        self.oneclick_log.setStyleSheet(f'color:{col};font-size:9px;letter-spacing:1px;')
        QTimer.singleShot(3000, self._refresh_now)

    # ── KILL PROCESS (Dashboard) ─────────────────────────────
    def _kill_selected_proc(self):
        rows = set(i.row() for i in self.proc_table.selectedItems())
        if not rows:
            return
        killed = []
        for row in rows:
            pid_item = self.proc_table.item(row, 0)
            name_item = self.proc_table.item(row, 1)
            if not pid_item: continue
            pid  = pid_item.text()
            name = name_item.text() if name_item else pid
            try:
                import psutil
                p = psutil.Process(int(pid))
                p.terminate()
                killed.append(name)
            except Exception as e:
                QMessageBox.warning(self, 'Kill failed', f'Cannot kill {name}: {e}')
        if killed:
            QMessageBox.information(self, 'Done',
                f'Terminated: {", ".join(killed)}\nRefreshing in 2s...')
            QTimer.singleShot(2000, self._refresh_now)

    # ── KILL PROCESS (Process tab) ────────────────────────────
    def _kill_from_startup(self):
        rows = set(i.row() for i in self.startup_table.selectedItems())
        for row in rows:
            item = self.startup_table.item(row, 0)
            if not item: continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get('pid'):
                try:
                    import psutil; psutil.Process(data['pid']).terminate()
                except: pass
        self._load_processes()

    # ── SCANNER ───────────────────────────────────────────────
    def _run_scanner(self):
        if hasattr(self, '_scan_running') and self._scan_running: return
        self._scan_running = True
        self.scan_btn.setEnabled(False)
        self.fix_btn.setEnabled(False)
        self.opt_terminal.clear()
        self.scan_table.setRowCount(0)
        self._scan_results = []

        class ScanWorker(QThread):
            log  = pyqtSignal(str, str)
            done = pyqtSignal(list)
            def run(self_w):
                sc = SecurityScanner()
                results = sc.scan(lambda m, l: self_w.log.emit(m, l))
                self_w.done.emit(results)

        self._scan_worker = ScanWorker()
        self._scan_worker.log.connect(self._on_opt_log)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.start()

    def _on_scan_done(self, results):
        self._scan_running = False
        self.scan_btn.setEnabled(True)
        self._scan_results = results
        # Populate table
        sev_col = {'critical': C['red'], 'high': C['yellow'],
                   'medium': C['cyan'], 'info': C['dim']}
        for r in results:
            row = self.scan_table.rowCount()
            self.scan_table.insertRow(row)
            for i, val in enumerate([r.severity.upper(), r.category, r.path, r.detail]):
                ti = QTableWidgetItem(val)
                if i == 0: ti.setForeground(QColor(sev_col.get(r.severity, C['text'])))
                self.scan_table.setItem(row, i, ti)
            self.scan_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)
        fixable = [r for r in results if r.can_fix]
        if fixable: self.fix_btn.setEnabled(True)

    def _on_scan_select(self):
        rows = set(i.row() for i in self.scan_table.selectedItems())
        fixable = any(
            self.scan_table.item(r, 0) and
            self.scan_table.item(r, 0).data(Qt.ItemDataRole.UserRole) and
            self.scan_table.item(r, 0).data(Qt.ItemDataRole.UserRole).can_fix
            for r in rows
        )
        self.fix_btn.setEnabled(fixable)

    def _fix_scan_results(self):
        rows = set(i.row() for i in self.scan_table.selectedItems())
        if not rows:
            rows = set(range(self.scan_table.rowCount()))
        to_fix = []
        for row in rows:
            item = self.scan_table.item(row, 0)
            if item:
                r = item.data(Qt.ItemDataRole.UserRole)
                if r and r.can_fix:
                    to_fix.append(r)
        if not to_fix: return
        msg = QMessageBox(self)
        msg.setWindowTitle('Auto-Fix')
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(f'Apply {len(to_fix)} auto-fix(es)?\n\n' +
                    '\n'.join(f'• {r.path}: {r.detail[:60]}' for r in to_fix[:5]))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() != QMessageBox.StandardButton.Yes: return
        import subprocess as _sp
        for r in to_fix:
            try:
                result = _sp.run(r.fix_cmd, shell=True, capture_output=True, text=True, timeout=10)
                self._on_opt_log(
                    f'  {"✓" if result.returncode==0 else "✗"}  {r.path}: {r.fix_cmd}',
                    'ok' if result.returncode==0 else 'err'
                )
            except Exception as e:
                self._on_opt_log(f'  ✗  {r.fix_cmd}: {e}', 'err')
        self._run_scanner()  # re-scan after fixes

    # ── UNINSTALL ─────────────────────────────────────────────
    def _load_uninstall(self):
        self.uninstall_table.setRowCount(0)
        self.uninstall_log.append('  Loading installed apps...')
        self._all_apps = get_installed_apps()
        self._populate_uninstall(self._all_apps)
        self.uninstall_log.append(f'  Found {len(self._all_apps)} apps')

    def _populate_uninstall(self, apps):
        self.uninstall_table.setRowCount(0)
        for app in apps:
            row = self.uninstall_table.rowCount()
            self.uninstall_table.insertRow(row)
            sz = f'{app.size_mb:.1f} MB' if app.size_mb > 0 else '—'
            src_col = {'pacman':C['cyan'],'apt':C['yellow'],'dnf':C['green'],
                       'flatpak':C['purple'],'winget':C['cyan'],'wmic':C['dim']}.get(app.source, C['text'])
            for i, val in enumerate([app.name, app.version, sz, app.source]):
                ti = QTableWidgetItem(val)
                if i == 3: ti.setForeground(QColor(src_col))
                if i == 2 and app.size_mb > 200:
                    ti.setForeground(QColor(C['red']))
                self.uninstall_table.setItem(row, i, ti)
            self.uninstall_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, app)

    def _filter_uninstall(self, text):
        if not hasattr(self, '_all_apps'): return
        filtered = [a for a in self._all_apps if text.lower() in a.name.lower()]
        self._populate_uninstall(filtered)

    def _do_uninstall(self):
        rows = set(i.row() for i in self.uninstall_table.selectedItems())
        if not rows:
            QMessageBox.information(self, 'Select', 'Select at least one app first.')
            return
        apps = []
        for row in rows:
            item = self.uninstall_table.item(row, 0)
            if item:
                app = item.data(Qt.ItemDataRole.UserRole)
                if app: apps.append(app)
        if not apps: return
        msg = QMessageBox(self)
        msg.setWindowTitle('Uninstall')
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(f'Uninstall {len(apps)} app(s)?\n' +
                    '\n'.join(f'• {a.name}' for a in apps))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() != QMessageBox.StandardButton.Yes: return
        self.uninstall_log.clear()
        for app in apps:
            _col_map = {'ok': C['green'], 'err': C['red']}
            def _log_uninstall(m, l, _cm=_col_map):
                col = _cm.get(l, C['dim'])
                self.uninstall_log.append(f'<span style="color:{col};">{m}</span>')
            uninstall_app(app, _log_uninstall)
        QTimer.singleShot(1500, self._load_uninstall)

    # ── PROCESS MANAGER (new _load_processes) ─────────────────
    def _load_processes(self):
        """Load both running processes + startup items into startup_table."""
        self.startup_table.setRowCount(0)
        # Section 1: Running processes
        try:
            import psutil
            procs = []
            for p in psutil.process_iter(['pid','name','cpu_percent','memory_percent','status']):
                try:
                    procs.append({
                        'name': p.info['name'], 'pid': p.info['pid'],
                        'type': f'PID {p.info["pid"]}',
                        'enabled': p.info['status'] == 'running',
                        'path': f'CPU:{p.info["cpu_percent"]:.1f}%  MEM:{p.info["memory_percent"]:.1f}%',
                        'platform': 'process'
                    })
                except: pass
            procs.sort(key=lambda x: x.get('cpu_percent', 0) if isinstance(x.get('cpu_percent'), (int,float)) else 0, reverse=True)
            for item in procs[:40]:  # top 40
                row = self.startup_table.rowCount()
                self.startup_table.insertRow(row)
                col = C['green'] if item['enabled'] else C['dim']
                for i, val in enumerate([item['name'], item['type'],
                                          'RUNNING' if item['enabled'] else item['enabled'],
                                          item.get('path','')]):
                    ti = QTableWidgetItem(str(val))
                    if i == 2: ti.setForeground(QColor(col))
                    self.startup_table.setItem(row, i, ti)
                self.startup_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)
        except ImportError: pass

        # Section 2: Startup items
        from utils.sysinfo import get_startup_items
        for item in get_startup_items():
            row = self.startup_table.rowCount()
            self.startup_table.insertRow(row)
            en_col = C['cyan'] if item['enabled'] else C['red']
            for i, val in enumerate([item['name'], item['type'],
                                      'AUTOSTART' if item['enabled'] else 'DISABLED',
                                      item.get('path','')]):
                ti = QTableWidgetItem(val)
                if i == 2: ti.setForeground(QColor(en_col))
                self.startup_table.setItem(row, i, ti)
            self.startup_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)

    # ── POLKIT WARNING ─────────────────────────────────────────
    def _show_polkit_warning(self):
        if hasattr(self, '_polkit_warned'): return
        self._polkit_warned = True
        if not HAS_POLKIT:
            msg = QMessageBox(self)
            msg.setWindowTitle('Setup Required')
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(
                'Polkit not configured.'
                ' Root-level cleaning needs setup.'
                '<br>Option 1: bash ~/CyberClean/install.sh'
                '<br>Option 2: sudo python3 ~/CyberClean/main.py'
                '<br>User-level targets (browser cache, thumbnails) still work.'
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.setStyleSheet(f'background:{C["bg2"]};color:{C["text"]};font-family:monospace;')
            msg.exec()
            self._on_clean_log('  ⚠  Polkit not set up — run install.sh for full functionality', 'warn')
        elif not HAS_POLKIT_AGENT:
            self._on_clean_log('  ⚠  Polkit policy OK but no agent running', 'warn')
            self._on_clean_log('     Password dialog may not appear on Wayland', 'warn')
            self._on_clean_log('     Fix: sudo pacman -S polkit-gnome  →  re-login', 'warn')

    # ── SYSINFO REALTIME ──────────────────────────────────
    def _start_sysinfo(self):
        self._si_worker = SysInfoWorker()
        self._si_worker.snapshot.connect(self._on_snapshot)
        self._si_worker.start()

    def _refresh_now(self):
        try:
            s = get_snapshot(interval=0.1)
            self._on_snapshot(s)
        except: pass

    def _on_snapshot(self, s):
        self._snap = s

        def color_pct(v):
            return 'red' if v>85 else 'yellow' if v>70 else 'cyan'

        # Stat cards
        self.stat_vals['cpu'].setText(f'{s.cpu_percent:.0f}%')
        self.stat_vals['cpu'].setStyleSheet(f'color:{C[color_pct(s.cpu_percent)]};font-size:22px;font-weight:bold;letter-spacing:2px;')
        self.stat_vals['ram'].setText(f'{s.ram_percent:.0f}%')
        self.stat_vals['ram'].setStyleSheet(f'color:{C[color_pct(s.ram_percent)]};font-size:22px;font-weight:bold;letter-spacing:2px;')

        # Swap — hiện GB/MB thay vì %
        if s.swap_total == 0:
            self.stat_vals['swap'].setText('N/A')
            self.stat_vals['swap'].setStyleSheet(f'color:{C["dim"]};font-size:18px;font-weight:bold;letter-spacing:2px;')
            if hasattr(self, '_swap_sub'): self._swap_sub.setText('no swap')
        else:
            used_gb = s.swap_used / 1024**3; total_gb = s.swap_total / 1024**3
            if total_gb >= 1:
                self.stat_vals['swap'].setText(f'{used_gb:.1f} GB')
                if hasattr(self, '_swap_sub'): self._swap_sub.setText(f'/ {total_gb:.1f} GB total')
            else:
                self.stat_vals['swap'].setText(f'{s.swap_used//1024//1024:.0f} MB')
                if hasattr(self, '_swap_sub'): self._swap_sub.setText(f'/ {s.swap_total//1024//1024:.0f} MB total')
            sc = 'red' if s.swap_percent>80 else 'yellow' if s.swap_percent>40 else 'cyan'
            self.stat_vals['swap'].setStyleSheet(f'color:{C[sc]};font-size:22px;font-weight:bold;letter-spacing:2px;')

        if s.temp_max:
            tc = 'red' if s.temp_max>85 else 'yellow' if s.temp_max>75 else 'green'
            self.stat_vals['temp'].setText(f'{s.temp_max:.0f}°C')
            self.stat_vals['temp'].setStyleSheet(f'color:{C[tc]};font-size:22px;font-weight:bold;letter-spacing:2px;')

        # ── Health Score ──────────────────────────────────
        if hasattr(self, 'health_score_lbl'):
            score = 100
            issues = []
            if s.cpu_percent > 85:  score -= 20; issues.append(f'CPU {s.cpu_percent:.0f}%')
            elif s.cpu_percent > 70: score -= 10; issues.append(f'CPU high')
            if s.ram_percent > 85:  score -= 20; issues.append(f'RAM {s.ram_percent:.0f}%')
            elif s.ram_percent > 70: score -= 10
            if s.disks:
                worst = max(s.disks, key=lambda d: d.percent)
                if worst.percent > 90:  score -= 25; issues.append(f'Disk {worst.percent:.0f}%')
                elif worst.percent > 75: score -= 15; issues.append(f'Disk {worst.percent:.0f}%')
            if s.temp_max and s.temp_max > 85: score -= 15; issues.append(f'Temp {s.temp_max:.0f}°C')
            if s.swap_total > 0 and s.swap_percent > 60: score -= 10; issues.append('Swap heavy')
            score = max(0, score)
            col = 'green' if score >= 80 else 'yellow' if score >= 50 else 'red'
            self.health_score_lbl.setText(f'{score}%')
            self.health_score_lbl.setStyleSheet(f'color:{C[col]};font-size:28px;font-weight:bold;letter-spacing:2px;')
            status = ' · '.join(issues) if issues else '✓ System healthy'
            self.health_status_lbl.setText(status)
            self.health_status_lbl.setStyleSheet(f'color:{C[col] if issues else C["green"]};font-size:9px;')

        # Charts
        self._charts['cpu'].push(s.cpu_percent)
        self._charts['ram'].push(s.ram_percent)

        # Disk ring (first disk)
        if s.disks:
            d = s.disks[0]
            self.disk_ring.set_percent(d.percent)
            self.disk_detail_lbl.setText(f'{fmt_size(d.used)} / {fmt_size(d.total)}')

        # Top processes table
        self.proc_table.setRowCount(0)
        for proc in s.top_cpu_procs[:6]:
            row = self.proc_table.rowCount()
            self.proc_table.insertRow(row)
            vals = [str(proc.pid), proc.name, f'{proc.cpu:.1f}', f'{proc.mem:.1f}']
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col == 2 and float(val) > 15:
                    item.setForeground(QColor(C['red']))
                self.proc_table.setItem(row, col, item)

        # Disk table
        self.disk_table.setRowCount(0)
        for disk in s.disks:
            row = self.disk_table.rowCount()
            self.disk_table.insertRow(row)
            col_pct = C['red'] if disk.percent>90 else C['yellow'] if disk.percent>75 else C['cyan']
            vals = [disk.path, fmt_size(disk.used), fmt_size(disk.free), f'{disk.percent:.0f}%']
            for i, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if i == 3: item.setForeground(QColor(col_pct))
                self.disk_table.setItem(row, i, item)

    # ── CLOCK ─────────────────────────────────────────────
    def _start_clock(self):
        t = QTimer(self)
        t.timeout.connect(lambda: self.clock_lbl.setText(datetime.now().strftime('%H:%M:%S')))
        t.start(1000)

    # ── CLEAN ACTIONS ─────────────────────────────────────
    def _toggle(self, tid, state):
        if state: self.selected.add(tid)
        else:     self.selected.discard(tid)

    def _sel_all(self):
        targets = CLEANER.get_targets() if CLEANER else []
        self.selected = set(t.id for t in targets)
        for chk in self.target_checks.values(): chk.setChecked(True)

    def _sel_none(self):
        self.selected.clear()
        for chk in self.target_checks.values(): chk.setChecked(False)

    def _confirm_clean(self):
        if not self.selected:
            QMessageBox.warning(self, 'No targets', 'Select at least one target first.')
            return
        targets = CLEANER.get_targets() if CLEANER else []
        names   = [t.name for t in targets if t.id in self.selected]
        msg = QMessageBox(self)
        msg.setWindowTitle('Confirm Clean')
        msg.setText(f'Clean {len(self.selected)} target(s)?\n\n' + '\n'.join(f'  • {n}' for n in names))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.button(QMessageBox.StandardButton.Yes).setText('⚡ CLEAN NOW')
        msg.setStyleSheet(f'background:{C["bg2"]};color:{C["text"]};font-family:monospace;')
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._run_clean(dry=False)

    def _run_clean(self, dry=True):
        if not CLEANER or not self.selected: return
        if self.worker and self.worker.isRunning(): return
        # Snapshot disk % BEFORE clean for accurate before/after comparison
        self._disk_pct_before = self._snap.disks[0].percent if self._snap and self._snap.disks else 0
        self.clean_terminal.clear()
        self.clean_prog.setVisible(True)
        self.clean_prog_lbl.setVisible(True)
        self.worker = CleanWorker(list(self.selected), dry=dry)
        self.worker.log.connect(self._on_clean_log)
        self.worker.progress.connect(lambda p, l: (self.clean_prog.setValue(p), self.clean_prog_lbl.setText(l)))
        self.worker.done.connect(self._on_clean_done)
        self.worker.start()

    def _on_clean_log(self, msg, level):
        cols = {'ok':C['green'],'dry':C['yellow'],'err':C['red'],'head':C['cyan'],'info':C['dim'],'warn':C['yellow']}
        col  = cols.get(level, C['text'])
        self.clean_terminal.append(f'<span style="color:{col};font-family:monospace;">{msg}</span>')
        self.clean_terminal.moveCursor(QTextCursor.MoveOperation.End)

    def _on_clean_done(self, result):
        self.clean_prog.setVisible(False)
        self.clean_prog_lbl.setVisible(False)
        if not result['dry']:
            disk_before = self._disk_pct_before
            # Re-snapshot disk after clean to get real "after" value
            try:
                from utils.sysinfo import get_snapshot
                snap_after = get_snapshot(interval=0.1)
                disk_after = snap_after.disks[0].percent if snap_after.disks else disk_before
            except:
                disk_after = disk_before
            session  = {
                'time': datetime.now().isoformat(),
                'disk_before': disk_before,
                'disk_after':  round(disk_after, 1),
                'freed_bytes': result['freed'],
                'summary':     result['summary'],
            }
            with open(LOG_FILE, 'a') as f: f.write(json.dumps(session)+'\n')
            if result['rollback']:
                with open(ROLLBACK_FILE, 'a') as f:
                    for e in result['rollback']: f.write(json.dumps(e)+'\n')

    # ── OPTIMIZER ─────────────────────────────────────────
    def _on_opt_log(self, msg, level):
        cols = {'ok':C['green'],'warn':C['yellow'],'err':C['red'],'head':C['cyan'],'info':C['dim']}
        col  = cols.get(level, C['text'])
        self.opt_terminal.append(f'<span style="color:{col};font-family:monospace;">{msg}</span>')
        self.opt_terminal.moveCursor(QTextCursor.MoveOperation.End)

    # ── STARTUP ───────────────────────────────────────────
    def _load_startup(self):
        self._load_processes()

    def _load_startup_only(self):
        items = get_startup_items()
        for item in items:
            row = self.startup_table.rowCount()
            self.startup_table.insertRow(row)
            en_col = C['green'] if item['enabled'] else C['red']
            vals   = [item['name'], item['type'],
                      'YES' if item['enabled'] else 'NO',
                      item.get('path','')]
            for i, val in enumerate(vals):
                ti = QTableWidgetItem(val)
                if i == 2: ti.setForeground(QColor(en_col))
                self.startup_table.setItem(row, i, ti)
            # Store item data for toggle
            self.startup_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)

    def _toggle_startup(self, enable: bool):
        if not IS_LINUX: return   # Windows impl TBD
        rows = set(i.row() for i in self.startup_table.selectedItems())
        for row in rows:
            item = self.startup_table.item(row, 0)
            if not item: continue
            data = item.data(Qt.ItemDataRole.UserRole)
            toggle_startup_linux(data['name'], data['type'], enable, data.get('path',''))
        self._load_startup()

    # ── LOG / ROLLBACK ────────────────────────────────────
    def _load_log(self):
        self.log_table.setRowCount(0)
        if not LOG_FILE.exists(): return
        for line in reversed(LOG_FILE.read_text().strip().splitlines()):
            try:
                e   = json.loads(line)
                row = self.log_table.rowCount()
                self.log_table.insertRow(row)
                t   = datetime.fromisoformat(e['time']).strftime('%Y-%m-%d %H:%M')
                for i, val in enumerate([t, f'{e.get("disk_before","?")}%',
                                          f'{e.get("disk_after","?")}%',
                                          fmt_size(e.get('freed_bytes',0)),
                                          e.get('summary','')]):
                    item = QTableWidgetItem(val)
                    if i == 3: item.setForeground(QColor(C['green']))
                    self.log_table.setItem(row, i, item)
            except: pass

    def _clear_log(self):
        if QMessageBox.question(self,'Clear','Delete all history?') == QMessageBox.StandardButton.Yes:
            LOG_FILE.unlink(missing_ok=True)
            self.log_table.setRowCount(0)

    def _load_rollback(self):
        self.rollback_table.setRowCount(0)
        if not ROLLBACK_FILE.exists(): return
        lines = ROLLBACK_FILE.read_text().strip().splitlines()
        for line in reversed(lines[:300]):
            try:
                e   = json.loads(line)
                row = self.rollback_table.rowCount()
                self.rollback_table.insertRow(row)
                t   = datetime.fromisoformat(e['time']).strftime('%m-%d %H:%M')
                for i, val in enumerate([t, e.get('type',''),
                                          fmt_size(e.get('size',0)),
                                          e.get('note') or e.get('path','')]):
                    item = QTableWidgetItem(val)
                    if i == 1: item.setForeground(QColor(C['cyan']))
                    if i == 2: item.setForeground(QColor(C['yellow']))
                    self.rollback_table.setItem(row, i, item)
            except: pass

    # ── SYSTEM TRAY ───────────────────────────────────────
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        # Use built-in icon (no external file needed)
        from PyQt6.QtGui import QPixmap
        px = QPixmap(16, 16)
        px.fill(QColor(C['cyan']))
        self.tray.setIcon(QIcon(px))
        self.tray.setToolTip('CyberClean v2.0')

        menu = QMenu()
        menu.setStyleSheet(f'''
            QMenu{{background:{C["bg2"]};color:{C["text"]};border:1px solid {C["border"]};
                  font-family:monospace;font-size:11px;padding:4px;}}
            QMenu::item{{padding:6px 20px;}}
            QMenu::item:selected{{background:{C["cyan"]}22;color:{C["cyan"]};}}
        ''')
        show_act = QAction('◈  Show CyberClean', self)
        show_act.triggered.connect(self._show_from_tray)
        dash_act = QAction('◈  Dashboard', self)
        dash_act.triggered.connect(lambda: (self._show_from_tray(), self._nav('dashboard')))
        clean_act = QAction('⚡  Quick Clean', self)
        clean_act.triggered.connect(lambda: (self._show_from_tray(), self._nav('clean')))
        quit_act = QAction('✕  Quit', self)
        quit_act.triggered.connect(QApplication.quit)

        menu.addAction(show_act)
        menu.addSeparator()
        menu.addAction(dash_act)
        menu.addAction(clean_act)
        menu.addSeparator()
        menu.addAction(quit_act)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        """Minimize to tray instead of quitting."""
        if hasattr(self, 'tray') and self.tray.isVisible():
            self.hide()
            self.tray.showMessage(
                'CyberClean',
                'Running in background. Double-click tray icon to restore.',
                QSystemTrayIcon.MessageIcon.Information, 2000
            )
            event.ignore()
        else:
            event.accept()

    # ── AUTO UPDATE CHECK ─────────────────────────────────
    GITHUB_LATEST = 'https://api.github.com/repos/vuphitung/CyberClean/releases/latest'
    CURRENT_VER   = '2.0.0'

    def _check_update_async(self):
        threading.Thread(target=self._fetch_update, daemon=True).start()

    def _fetch_update(self):
        try:
            req = urlopen(self.GITHUB_LATEST, timeout=5)
            data = json.loads(req.read().decode())
            latest = data.get('tag_name','').lstrip('v')
            if latest and latest != self.CURRENT_VER:
                # Signal back to UI thread via timer
                self._pending_update = latest
                QTimer.singleShot(100, self._show_update_notice)
        except: pass

    def _show_update_notice(self):
        ver = getattr(self, '_pending_update', None)
        if not ver: return
        if hasattr(self, 'tray'):
            self.tray.showMessage(
                'CyberClean — Update Available',
                f'v{ver} is available! Visit github.com/vuphitung/CyberClean',
                QSystemTrayIcon.MessageIcon.Information, 5000
            )
        # Also show banner in header
        if hasattr(self, 'clock_lbl'):
            self.clock_lbl.setText(f'UPDATE v{ver} AVAILABLE')
            self.clock_lbl.setStyleSheet(f'color:{C["yellow"]};font-size:10px;letter-spacing:1px;')


# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName('CyberClean')
    app.setApplicationVersion('2.0')
    win = CyberCleanApp()
    win.show()
    sys.exit(app.exec())
