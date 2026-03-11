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
    QSplitter, QSizePolicy, QLineEdit, QComboBox
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
        p.setFont(QFont('Cascadia Code' if __import__('platform').system()=='Windows' else 'Share Tech Mono', 13, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 90, 90), Qt.AlignmentFlag.AlignCenter,
                   f'{int(self.percent)}%')
        p.end()

# ═════════════════════════════════════════════════════════════
# WORKER THREADS
# ═════════════════════════════════════════════════════════════
class SysInfoWorker(QThread):
    snapshot = pyqtSignal(object)
    def __init__(self):
        super().__init__()
        self.paused = False   # lazy: pause when dashboard not visible
    def run(self):
        while True:
            if not self.paused:
                try:
                    s = get_snapshot(interval=0.5)
                    self.snapshot.emit(s)
                except: pass
            self.msleep(3000)   # 3s — no need for 500ms flicker

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
# UI HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════
def styled_btn(text, color='cyan', small=False):
    col = C[color]
    btn = QPushButton(text)
    pad = '5px 12px' if small else '8px 20px'
    sz  = '10px'     if small else '11px'
    btn.setStyleSheet(f"""
        QPushButton {{
            color:{col}; border:1px solid {col}44; background:transparent;
            font-family:'Cascadia Code','Share Tech Mono','Consolas',monospace;
            font-size:{sz}; letter-spacing:2px; padding:{pad};
        }}
        QPushButton:hover   {{ background:{col}18; border-color:{col}88; }}
        QPushButton:pressed {{ background:{col}30; }}
        QPushButton:disabled {{ color:{C['dim']}; border-color:{C['dim']}33; }}
    """)
    return btn

def section_lbl(text):
    l = QLabel(text)
    l.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:3px;padding:10px 0 4px 0;')
    return l

def val_lbl(text, color='cyan', size=22):
    l = QLabel(text)
    l.setStyleSheet(f'color:{C[color]};font-size:{size}px;font-weight:bold;letter-spacing:2px;')
    return l

def card():
    f = QFrame()
    f.setStyleSheet(f'QFrame{{background:{C["bg2"]};border:1px solid {C["border"]};}}')
    return f

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
        pal.setColor(QPalette.ColorRole.Window,          QColor(C['bg']))
        pal.setColor(QPalette.ColorRole.WindowText,      QColor(C['text']))
        pal.setColor(QPalette.ColorRole.Base,            QColor(C['bg2']))
        pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(C['bg3']))   # subtle alt rows
        pal.setColor(QPalette.ColorRole.Text,            QColor(C['text']))
        QApplication.setPalette(pal)
        self.setStyleSheet(f"""
            QMainWindow,QWidget{{background:{C['bg']};color:{C['text']};font-family:'Cascadia Code','Share Tech Mono','Consolas',monospace;}}
            QScrollBar:vertical{{background:{C['bg2']};width:5px;border:none;}}
            QScrollBar::handle:vertical{{background:{C['dim']};border-radius:2px;}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
            QTableWidget{{background:{C['bg2']};border:1px solid {C['border']};gridline-color:{C['border']}22;font-size:11px;}}
            QTableWidget::item{{padding:5px 8px;border:none;background:transparent;}}
            QTableWidget::item:alternate{{background:{C['bg3']};}}
            QTableWidget::item:selected{{background:{C['cyan']}1a;color:{C['cyan']};}}
            QTableWidget::item:selected:alternate{{background:{C['cyan']}1a;color:{C['cyan']};}}
            QHeaderView::section{{background:{C['bg']};color:{C['dim']};border:none;border-bottom:1px solid {C['border']};padding:5px 8px;font-size:9px;letter-spacing:2px;}}
            QCheckBox{{color:{C['text']};spacing:6px;}}
            QCheckBox::indicator{{width:13px;height:13px;border:1px solid {C['dim']};background:transparent;}}
            QCheckBox::indicator:checked{{background:{C['cyan']}28;border-color:{C['cyan']};}}
            QProgressBar{{background:{C['bg3']};border:none;height:2px;}}
            QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {C['cyan']},stop:1 {C['green']});}}
            QTextEdit{{background:#020609;color:{C['text']};border:1px solid {C['border']};font-family:'Cascadia Code','Share Tech Mono','Consolas',monospace;font-size:11px;padding:10px;}}
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
        nav.append(('browser', '🌐  BROWSER TURBO'))
        if IS_WINDOWS:
            nav.append(('wintools', '⊞  WIN TOOLS'))
        for pid, label in nav:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton{{color:{C['dim']};background:transparent;border:none;
                  border-left:2px solid transparent;text-align:left;
                  padding:10px 18px;font-family:'Cascadia Code','Share Tech Mono','Consolas',monospace;
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
        if IS_WINDOWS:
            import platform as _pf
            win_ver = _pf.version()[:20]
            pi_text = f'OS: Windows {_pf.release()}\nVER: {win_ver}\nPY: {info["python"]}'
        else:
            pi_text = f'OS: {info["os"]}\nDISTRO: {info["distro"] or "n/a"}\nPKG: {info["pkg_manager"] or "n/a"}\nPY: {info["python"]}'
        pi_lbl = QLabel(pi_text)
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
        self.stack.addWidget(self._build_browser_turbo())   # 7
        if IS_WINDOWS:
            self.stack.addWidget(self._build_windows_tools())  # 8
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
        lay.addSpacing(10)

        # ── Health Score + One-Click Fix ──────────────────
        top_row = QHBoxLayout(); top_row.setSpacing(10)

        health_card = card(); health_card.setFixedWidth(160)
        hcl = QVBoxLayout(health_card); hcl.setContentsMargins(14,12,14,12); hcl.setSpacing(4)
        hcl.addWidget(section_lbl('HEALTH SCORE'))
        self.health_score_lbl  = QLabel('—')
        self.health_score_lbl.setStyleSheet(f'color:{C["green"]};font-size:28px;font-weight:bold;letter-spacing:2px;')
        self.health_status_lbl = QLabel('Calculating...')
        self.health_status_lbl.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        self.health_status_lbl.setWordWrap(True)
        hcl.addWidget(self.health_score_lbl); hcl.addWidget(self.health_status_lbl)
        top_row.addWidget(health_card)

        fix_card = card()
        fcl = QVBoxLayout(fix_card); fcl.setContentsMargins(16,12,16,12); fcl.setSpacing(6)
        fcl.addWidget(section_lbl('ONE-CLICK FIX'))
        fd = QLabel('Drop cache · Tune swap · TRIM SSD · Clean journal')
        fd.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); fd.setWordWrap(True)
        self.oneclick_btn = styled_btn('⚡  OPTIMIZE NOW', 'cyan')
        self.oneclick_btn.clicked.connect(self._one_click_fix)
        self.oneclick_log = QLabel('')
        self.oneclick_log.setStyleSheet(f'color:{C["green"]};font-size:9px;letter-spacing:1px;')
        fcl.addWidget(fd); fcl.addWidget(self.oneclick_btn); fcl.addWidget(self.oneclick_log)
        top_row.addWidget(fix_card, 1)
        lay.addLayout(top_row); lay.addSpacing(10)

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
        t   = QLabel('⚔  PROCESS MANAGER')
        t.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        sub = QLabel('  — select a process to see safe actions')
        sub.setStyleSheet(f'color:{C["dim"]};font-size:10px;')
        ref = styled_btn('↻ SCAN', small=True)
        ref.clicked.connect(self._load_processes)
        tr.addWidget(t); tr.addWidget(sub); tr.addStretch(); tr.addWidget(ref)
        lay.addLayout(tr)
        lay.addSpacing(8)

        # ── Filter bar ────────────────────────────────────
        sf = QHBoxLayout(); sf.setSpacing(8)
        self.proc_search = QLineEdit()
        self.proc_search.setPlaceholderText('🔍  Search by app name...')
        self.proc_search.setStyleSheet(
            f'background:{C["bg2"]};color:{C["text"]};border:1px solid {C["border"]};'
            f'border-radius:4px;padding:4px 8px;font-size:11px;')
        self.proc_search.textChanged.connect(self._filter_processes)

        self.proc_filter_combo = QComboBox()
        self.proc_filter_combo.addItems([
            '🟢 Show all',
            '🔴 Suspicious only',
            '🟡 Unknown only',
            '🌐 Network hogs',
        ])
        self.proc_filter_combo.setStyleSheet(
            f'background:{C["bg2"]};color:{C["text"]};border:1px solid {C["border"]};'
            f'border-radius:4px;padding:4px 8px;font-size:11px;')
        self.proc_filter_combo.currentTextChanged.connect(self._filter_processes)
        sf.addWidget(self.proc_search, 1); sf.addWidget(self.proc_filter_combo)
        lay.addLayout(sf); lay.addSpacing(8)

        # ── Table — hide PID on Windows (confusing for normal users) ──
        self.startup_table = QTableWidget(0, 7)
        self.startup_table.setHorizontalHeaderLabels(
            ['','APP NAME','CPU','RAM','SAFETY','NETWORK','PATH'])
        hh = self.startup_table.horizontalHeader()
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.startup_table.setColumnWidth(0, 40)   # status dot
        self.startup_table.setColumnWidth(1, 160)
        self.startup_table.setColumnWidth(2, 60)
        self.startup_table.setColumnWidth(3, 60)
        self.startup_table.setColumnWidth(4, 110)
        self.startup_table.setColumnWidth(5, 100)
        if IS_WINDOWS:
            self.startup_table.setColumnHidden(0, True)  # hide raw PID col on Windows
        self.startup_table.verticalHeader().setVisible(False)
        self.startup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.startup_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.startup_table.setAlternatingRowColors(True)
        self.startup_table.itemSelectionChanged.connect(self._on_proc_select)
        lay.addWidget(self.startup_table, 1); lay.addSpacing(8)

        # ── Action buttons — plain language ───────────────
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)

        self.ghost_btn  = styled_btn('⏸ PAUSE',        'cyan',   small=True)
        self.revive_btn = styled_btn('▶ RESUME',        'green',  small=True)
        self.kill_btn2  = styled_btn('✕ FORCE QUIT',   'red',    small=True)
        self.block_btn  = styled_btn('🚫 BLOCK NET',    'yellow', small=True)
        self.search_btn = styled_btn('🔎 LOOK UP',      'purple', small=True)
        self.dis_btn    = styled_btn('⏸ STOP AT BOOT', 'yellow', small=True)
        self.en_btn     = styled_btn('▷ RUN AT BOOT',  'green',  small=True)

        # Tooltips — explain in plain words
        self.ghost_btn.setToolTip('Temporarily pause this process — frees CPU/RAM\nIt stays paused until you click Resume')
        self.revive_btn.setToolTip('Resume a paused process')
        self.kill_btn2.setToolTip('Force-quit this process immediately\n⚠ Unsaved work in that app will be lost')
        self.block_btn.setToolTip('Block this process from accessing the internet\n(Linux only — uses iptables)')
        self.search_btn.setToolTip("Search Google to find out if this process is safe\nor a virus — opens your browser")
        self.dis_btn.setToolTip('Prevent this app from starting automatically on boot\n(only affects startup items, not running processes)')
        self.en_btn.setToolTip('Allow this app to start automatically on boot')

        self.ghost_btn.clicked.connect(self._ghost_process)
        self.revive_btn.clicked.connect(self._revive_process)
        self.kill_btn2.clicked.connect(self._kill_from_startup)
        self.block_btn.clicked.connect(self._block_network)
        self.search_btn.clicked.connect(self._search_community)
        self.dis_btn.clicked.connect(lambda: self._toggle_startup(False))
        self.en_btn.clicked.connect(lambda:  self._toggle_startup(True))

        for b in [self.ghost_btn, self.revive_btn, self.kill_btn2,
                  self.block_btn, self.search_btn, self.dis_btn, self.en_btn]:
            b.setEnabled(False); btn_row.addWidget(b)
        btn_row.addStretch(); lay.addLayout(btn_row)

        # ── Status bar — plain explanation ────────────────
        self.proc_status = QLabel('← Click any app to see what you can do with it')
        self.proc_status.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:1px;')
        lay.addSpacing(4); lay.addWidget(self.proc_status)
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
        pages = ['dashboard','clean','scanner','uninstall','startup','log','rollback','browser']
        if IS_WINDOWS: pages.append('wintools')
        if pid not in pages: return
        self._active_tab = pid
        self.stack.setCurrentIndex(pages.index(pid))
        for k, b in self.nav_btns.items():
            b.setChecked(k == pid)
        # Lazy: pause sysinfo heavy loop when not on dashboard
        if hasattr(self, '_si_worker'):
            self._si_worker.paused = (pid != 'dashboard')
        if pid == 'log':        self._load_log()
        if pid == 'rollback':   self._load_rollback()
        if pid == 'startup':    self._load_processes()
        if pid == 'uninstall':  self._load_uninstall()
        if pid == 'clean' and IS_LINUX and not HAS_POLKIT_AGENT:
            self._show_polkit_warning()

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

    # ── SYSTEM WAR ROOM — process intelligence ────────────────
    _VERIFIED = {
        'systemd','kernel','kworker','kthreadd','ksoftirqd','migration',
        'rcu_sched','watchdog','irq','kswapd','jbd2','ext4',
        'python','python3','bash','zsh','fish','sh',
        'Xorg','Xwayland','wayland','pipewire','wireplumber','pulseaudio',
        'dbus','NetworkManager','dhcpcd','wpa_supplicant','sshd',
        'chrome','chromium','firefox','telegram','discord','slack','code',
        'nvim','vim','nano','htop','btop','tmux','alacritty','kitty','foot',
        'plasmashell','kwin','sway','hyprland','i3','openbox','gnome-shell',
        'thunar','dolphin','nautilus','pcmanfm',
        'java','node','npm','cargo','rustc','gcc','clang','make',
        'pacman','apt','dpkg','rpm','flatpak','snap',
        'bluetoothd','avahi','cups','crond','atd',
    }
    _SUSPICIOUS_NAMES = [
        'xmrig','minerd','cryptonight','kdevtmpfsi','kinsing',
        'masscan','zmap','sqlmap','hydra','medusa',
        'ncat','netcat','socat','python -c','perl -e','bash -i',
    ]

    def _score_process_dict(self, d: dict):
        """Score using pre-fetched dict (fast path, used after oneshot())."""
        name    = (d.get('name') or '').lower()
        exe     = d.get('exe') or ''
        cmdline = (d.get('cmdline') or '').lower()
        cpu     = d.get('cpu') or 0
        return self._score_core(name, exe, cmdline, cpu)

    def _score_process(self, p):
        import psutil
        try:
            name    = (p.info.get('name') or '').lower()
            exe     = p.info.get('exe') or ''
            cmdline = ' '.join(p.info.get('cmdline') or []).lower()
            cpu     = p.info.get('cpu_percent') or 0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return ('🟡 UNKNOWN', 'yellow', 40)

        return self._score_core(name, exe, cmdline, cpu)

    def _score_core(self, name, exe, cmdline, cpu):
        score = 0
        for s in self._SUSPICIOUS_NAMES:
            if s in name or s in cmdline: score += 50
        for sp in ['/tmp/', '/dev/shm/', '/var/tmp/']:
            if sp in exe: score += 35
        if IS_WINDOWS:
            for sp in ['\\temp\\','\\tmp\\','\\downloads\\','\\appdata\\local\\temp\\']:
                if sp in exe.lower(): score += 30
            if exe and score < 30:
                try:
                    import subprocess as _sp
                    r = _sp.run(['powershell','-NoProfile','-Command',
                                 f'(Get-AuthenticodeSignature "{exe}").Status'],
                                capture_output=True, text=True, timeout=3, creationflags=0x08000000)
                    sig = r.stdout.strip()
                    if sig == 'Valid': score = max(0, score - 30)
                    elif sig in ('NotSigned','HashMismatch','NotTrusted'): score += 20
                except: pass
        safe_pfx = ['c:\\windows\\','c:\\program files\\'] if IS_WINDOWS else ['/usr/','/bin/','/lib/','/opt/']
        if cpu > 80 and exe and not any(exe.lower().startswith(p) for p in safe_pfx):
            score += 25
        base = name.split('\\')[-1].split('/')[-1].split()[0].replace('.exe','')
        if base in self._VERIFIED or any(name.startswith(v) for v in self._VERIFIED):
            score = max(0, score - 60)
        if exe and any(exe.lower().startswith(p) for p in (safe_pfx + ['/usr/bin/','/lib/'])):
            score = max(0, score - 20)
        if score >= 40:   return ('🔴 SUSPECT',  'red',    score)
        elif score >= 10: return ('🟡 UNKNOWN',  'yellow', score)
        else:             return ('🟢 VERIFIED', 'green',  score)

    def _load_processes(self):
        import psutil
        self._proc_all_rows = []
        self.startup_table.setRowCount(0)
        if not hasattr(self, '_ghosted_pids'): self._ghosted_pids = set()
        net_conns = {}
        try:
            # net_connections() replaces deprecated p.connections() in psutil 6+
            all_conns = psutil.net_connections(kind='inet')
            for c in all_conns:
                if c.status == 'ESTABLISHED' and c.pid:
                    net_conns[c.pid] = net_conns.get(c.pid, 0) + 1
        except: pass
        procs = []
        for p in psutil.process_iter():
            try:
                with p.oneshot():   # fetch all attrs in ONE syscall — much faster
                    procs.append({
                        'pid':    p.pid,
                        'name':   p.name(),
                        'cpu':    p.cpu_percent(),
                        'mem':    p.memory_percent(),
                        'exe':    p.exe() if p.pid > 4 else '',
                        'cmdline':' '.join(p.cmdline()[:4]) if p.pid > 4 else '',
                        'status': p.status(),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess): pass

        def sort_key(d):
            _, _, score = self._score_process_dict(d)
            return (-score, -(d.get('cpu') or 0))
        procs.sort(key=sort_key)

        for d in procs[:60]:
            try:
                status_lbl, col, score = self._score_process_dict(d)
                if d['pid'] in self._ghosted_pids: status_lbl, col = '👻 GHOSTED', 'purple'
                conns = net_conns.get(d['pid'], 0)
                net_str = f'🌐 {conns} conn' if conns > 0 else '—'
                net_col = 'red' if conns > 5 else 'yellow' if conns > 1 else 'dim'
                self._proc_all_rows.append({
                    'pid':d['pid'],'name':d['name'],'cpu':d['cpu'],'mem':d['mem'],
                    'status_lbl':status_lbl,'status_col':col,
                    'net_str':net_str,'net_col':net_col,
                    'path':d['exe'],'score':score,'platform':'process'})
            except: pass
        from utils.sysinfo import get_startup_items
        for item in get_startup_items():
            item['platform'] = 'startup'; item['pid'] = None
            item['cpu'] = 0; item['mem'] = 0
            item['status_lbl'] = '🟢 AUTOSTART' if item.get('enabled') else '⏸ DISABLED'
            item['status_col'] = 'cyan' if item.get('enabled') else 'dim'
            item['net_str'] = '—'; item['net_col'] = 'dim'
            item['path'] = item.get('path',''); item['score'] = 0
            self._proc_all_rows.append(item)
        self._filter_processes()

    def _filter_processes(self):
        if not hasattr(self, '_proc_all_rows'): return
        query = self.proc_search.text().lower() if hasattr(self,'proc_search') else ''
        filt  = self.proc_filter_combo.currentText() if hasattr(self,'proc_filter_combo') else 'ALL'
        self.startup_table.setRowCount(0)
        for rd in self._proc_all_rows:
            name = (rd.get('name') or '').lower()
            if query and query not in name: continue
            if 'Suspicious' in filt  and 'SUSPECT' not in rd.get('status_lbl',''): continue
            if 'Unknown'    in filt  and 'UNKNOWN' not in rd.get('status_lbl',''): continue
            if 'Network'    in filt  and '—' == rd.get('net_str','—'): continue
            row = self.startup_table.rowCount()
            self.startup_table.insertRow(row)
            pid_str = str(rd.get('pid','')) if rd.get('pid') else '—'
            vals = [pid_str, rd.get('name','?'),
                    f'{rd["cpu"]:.1f}' if rd["cpu"] else '—',
                    f'{rd["mem"]:.1f}' if rd["mem"] else '—',
                    rd['status_lbl'], rd['net_str'], rd['path']]
            cols = ['dim','text',
                    'red' if rd["cpu"]>50 else 'yellow' if rd["cpu"]>20 else 'dim',
                    'yellow' if rd["mem"]>10 else 'dim',
                    rd['status_col'], rd['net_col'], 'dim']
            for ci,(val,col) in enumerate(zip(vals,cols)):
                ti = QTableWidgetItem(str(val))
                ti.setForeground(QColor(C[col]))
                self.startup_table.setItem(row,ci,ti)
            self.startup_table.item(row,0).setData(Qt.ItemDataRole.UserRole, rd)

    def _on_proc_select(self):
        rows = set(i.row() for i in self.startup_table.selectedItems())
        if not rows:
            for b in [self.ghost_btn,self.revive_btn,self.kill_btn2,
                      self.block_btn,self.search_btn,self.dis_btn,self.en_btn]:
                b.setEnabled(False)
            return
        rd = self.startup_table.item(list(rows)[0],0).data(Qt.ItemDataRole.UserRole) or {}
        is_proc    = rd.get('platform') == 'process'
        is_startup = rd.get('platform') == 'startup'
        is_ghosted = rd.get('pid') in getattr(self,'_ghosted_pids',set())
        self.ghost_btn.setEnabled(is_proc and not is_ghosted)
        self.revive_btn.setEnabled(is_proc and is_ghosted)
        self.kill_btn2.setEnabled(is_proc)
        self.block_btn.setEnabled(is_proc and rd.get('net_str','—') != '—')
        self.search_btn.setEnabled(bool(rd.get('name')))
        self.dis_btn.setEnabled(is_startup and rd.get('enabled', False))
        self.en_btn.setEnabled(is_startup and not rd.get('enabled', True))
        lbl  = rd.get('status_lbl','')
        name = rd.get('name','?')
        tip  = f'  Selected: {name}'
        if is_proc:
            cpu = rd.get('cpu', 0); mem = rd.get('mem', 0)
            tip += f'  ·  CPU {cpu:.1f}%  RAM {mem:.1f}%'
        if 'SUSPECT'  in lbl: tip += '  ⚠ This process looks suspicious — click "Look Up" to check online'
        elif 'GHOSTED' in lbl: tip += '  ·  Currently paused — click Resume to unfreeze'
        elif is_startup:       tip += '  ·  Startup item — controls whether it runs at boot'
        self.proc_status.setText(tip)

    def _ghost_process(self):
        rows = set(i.row() for i in self.startup_table.selectedItems())
        if not rows: return
        rd = self.startup_table.item(list(rows)[0],0).data(Qt.ItemDataRole.UserRole) or {}
        pid = rd.get('pid')
        if not pid: return
        try:
            import psutil
            psutil.Process(pid).suspend()
            if not hasattr(self,'_ghosted_pids'): self._ghosted_pids = set()
            self._ghosted_pids.add(pid)
            self.proc_status.setText(f'  👻 Ghosted PID {pid} ({rd.get("name","?")}) — CPU frozen')
            self._load_processes()
        except Exception as e:
            self.proc_status.setText(f'  ✗ Ghost failed: {e}')

    def _revive_process(self):
        rows = set(i.row() for i in self.startup_table.selectedItems())
        if not rows: return
        rd = self.startup_table.item(list(rows)[0],0).data(Qt.ItemDataRole.UserRole) or {}
        pid = rd.get('pid')
        if not pid: return
        try:
            import psutil
            psutil.Process(pid).resume()
            self._ghosted_pids.discard(pid)
            self.proc_status.setText(f'  ⚡ Revived PID {pid} ({rd.get("name","?")})')
            self._load_processes()
        except Exception as e:
            self.proc_status.setText(f'  ✗ Revive failed: {e}')

    def _block_network(self):
        rows = set(i.row() for i in self.startup_table.selectedItems())
        if not rows: return
        rd = self.startup_table.item(list(rows)[0],0).data(Qt.ItemDataRole.UserRole) or {}
        pid = rd.get('pid'); name = rd.get('name','?')
        if not pid: return
        reply = QMessageBox.question(self, 'Block Network',
            f'Block ALL network for:\n  {name} (PID {pid})\n\nAdds iptables rule.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        import subprocess as _sp, platform as _pl
        if _pl.system() == 'Linux':
            try:
                import psutil
                uid = psutil.Process(pid).uids().real
                cmd = f'sudo -n iptables -A OUTPUT -m owner --uid-owner {uid} -m comment --comment "cyberclean-{name}" -j DROP'
                r = _sp.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    self.proc_status.setText(f'  🚫 Blocked {name} (uid {uid})')
                else:
                    self.proc_status.setText(f'  ✗ iptables failed — need root')
            except Exception as e:
                self.proc_status.setText(f'  ✗ Block failed: {e}')

    def _search_community(self):
        rows = set(i.row() for i in self.startup_table.selectedItems())
        if not rows: return
        rd   = self.startup_table.item(list(rows)[0],0).data(Qt.ItemDataRole.UserRole) or {}
        name = rd.get('name','')
        if not name: return
        import webbrowser, urllib.parse
        q = urllib.parse.quote(f'{name} process linux safe or malware site:reddit.com OR site:unix.stackexchange.com')
        webbrowser.open(f'https://www.google.com/search?q={q}')
        self.proc_status.setText(f'  🔎 Searching: {name}')

    # ══════════════════════════════════════════════════════
    # 🌐  BROWSER TURBO TAB
    # ══════════════════════════════════════════════════════
    def _build_browser_turbo(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28,22,28,22)
        lay.setSpacing(16)

        hdr = QLabel('🌐  BROWSER TURBO')
        hdr.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        lay.addWidget(hdr)

        sub = QLabel('Speed up Chrome / Firefox / Edge — priority boost, database compact, cache wipe')
        sub.setStyleSheet(f'color:{C["dim"]};font-size:10px;letter-spacing:1px;')
        lay.addWidget(sub)

        self._browser_log = QTextEdit()
        self._browser_log.setReadOnly(True)
        self._browser_log.setMaximumHeight(180)
        self._browser_log.setStyleSheet(
            f'background:#020609;color:{C["text"]};border:1px solid {C["border"]};'
            f'font-size:10px;padding:8px;')

        # ── Row 1: Priority Boost ──────────────────────────
        pr_card = card(); pr_lay = QVBoxLayout(pr_card); pr_lay.setContentsMargins(16,12,16,12)
        pr_lay.addWidget(section_lbl('⚡  PRIORITY BOOST'))
        pr_desc = QLabel('Raise Chrome / Firefox / Edge to HIGH CPU priority.\nBrowser tabs, video and scrolling feel instantly smoother.')
        pr_desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); pr_desc.setWordWrap(True)
        pr_row = QHBoxLayout()
        self._boost_btn  = styled_btn('⚡  BOOST BROWSERS', 'cyan')
        self._restore_btn = styled_btn('↺  RESTORE NORMAL', 'yellow')
        self._boost_btn.clicked.connect(self._browser_priority_boost)
        self._restore_btn.clicked.connect(self._browser_priority_restore)
        pr_row.addWidget(self._boost_btn); pr_row.addWidget(self._restore_btn); pr_row.addStretch()
        pr_lay.addWidget(pr_desc); pr_lay.addLayout(pr_row)
        lay.addWidget(pr_card)

        # ── Row 2: SQLite VACUUM ───────────────────────────
        vac_card = card(); vac_lay = QVBoxLayout(vac_card); vac_lay.setContentsMargins(16,12,16,12)
        vac_lay.addWidget(section_lbl('🗜  DATABASE VACUUM'))
        vac_desc = QLabel('Compact browser SQLite databases (history, cookies, bookmarks).\n'
                          'Reduces DB size 20–50% — browser launches 30% faster after reboot.')
        vac_desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); vac_desc.setWordWrap(True)
        vac_row = QHBoxLayout()
        for name, cb in [('Chrome', lambda: self._vacuum_browser('chrome')),
                         ('Firefox', lambda: self._vacuum_browser('firefox')),
                         ('Edge',    lambda: self._vacuum_browser('edge')),
                         ('All Browsers', lambda: self._vacuum_browser('all'))]:
            b = styled_btn(name, 'green', small=True); b.clicked.connect(cb); vac_row.addWidget(b)
        vac_row.addStretch()
        vac_lay.addWidget(vac_desc); vac_lay.addLayout(vac_row)
        lay.addWidget(vac_card)

        # ── Row 3: GPU Cache Clear ─────────────────────────
        gpu_card = card(); gpu_lay = QVBoxLayout(gpu_card); gpu_lay.setContentsMargins(16,12,16,12)
        gpu_lay.addWidget(section_lbl('🎮  GPU CACHE CLEAR'))
        gpu_desc = QLabel('Wipe browser GPU / shader cache files.\n'
                          'Fixes 4K video stutter, WebGL glitches, and high VRAM usage.')
        gpu_desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); gpu_desc.setWordWrap(True)
        gpu_btn = styled_btn('🎮  CLEAR GPU CACHE', 'purple')
        gpu_btn.clicked.connect(self._clear_gpu_cache)
        gpu_lay.addWidget(gpu_desc); gpu_lay.addWidget(gpu_btn)
        lay.addWidget(gpu_card)

        # ── Row 4: Game / Eco Mode ─────────────────────────
        mode_card = card(); mode_lay = QVBoxLayout(mode_card); mode_lay.setContentsMargins(16,12,16,12)
        mode_lay.addWidget(section_lbl('🎯  FOCUS MODES'))
        mode_sub = QLabel('Freeze background bloat — give 100% resources to what matters now.')
        mode_sub.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        mode_lay.addWidget(mode_sub)

        mode_row = QHBoxLayout(); mode_row.setSpacing(12)

        game_c = card(); game_l = QVBoxLayout(game_c); game_l.setContentsMargins(12,10,12,10)
        game_title = QLabel('🎮  GAME MODE'); game_title.setStyleSheet(f'color:{C["red"]};font-size:11px;font-weight:bold;letter-spacing:2px;')
        game_desc = QLabel('Suspends: OneDrive · Dropbox · Office updater\nPrint Spooler · Teams background · Windows Search')
        game_desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); game_desc.setWordWrap(True)
        self._game_btn = styled_btn('▶  ACTIVATE', 'red'); self._game_btn.setCheckable(True)
        self._game_btn.clicked.connect(self._toggle_game_mode)
        game_l.addWidget(game_title); game_l.addWidget(game_desc); game_l.addWidget(self._game_btn)
        mode_row.addWidget(game_c)

        eco_c = card(); eco_l = QVBoxLayout(eco_c); eco_l.setContentsMargins(12,10,12,10)
        eco_title = QLabel('🌿  ECO MODE'); eco_title.setStyleSheet(f'color:{C["green"]};font-size:11px;font-weight:bold;letter-spacing:2px;')
        eco_desc = QLabel('Lowers priority of all background tasks to IDLE.\nCPU stays cool, fan stays quiet for reading / light work.')
        eco_desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); eco_desc.setWordWrap(True)
        self._eco_btn = styled_btn('▶  ACTIVATE', 'green'); self._eco_btn.setCheckable(True)
        self._eco_btn.clicked.connect(self._toggle_eco_mode)
        eco_l.addWidget(eco_title); eco_l.addWidget(eco_desc); eco_l.addWidget(self._eco_btn)
        mode_row.addWidget(eco_c)
        mode_lay.addLayout(mode_row)
        lay.addWidget(mode_card)

        lay.addWidget(self._browser_log)
        lay.addStretch()
        return w

    # ── Browser Turbo actions ──────────────────────────────
    def _blog(self, msg, col='text'):
        colors = {'ok':'#4ade80','err':'#f87171','warn':'#fbbf24','head':'#67e8f9','text':C['text']}
        self._browser_log.append(
            f'<span style="color:{colors.get(col,C["text"])}">{msg}</span>')

    def _browser_priority_boost(self):
        import psutil, os
        # Extended list — covers Arch/Ubuntu package names + Windows exe names
        BROWSERS = {
            'chrome','google-chrome','google-chrome-stable','chromium','chromium-browser',
            'firefox','firefox-bin','firefox-esr',
            'msedge','microsoft-edge','microsoft-edge-stable','edge',
            'brave','brave-browser','opera','vivaldi','vivaldi-bin',
        }
        boosted = []
        for p in psutil.process_iter():
            try:
                with p.oneshot():
                    nm = p.name().lower().replace('.exe','').replace(' ','_')
                    if nm in BROWSERS or any(b in nm for b in ('chrome','firefox','edge','brave')):
                        if IS_WINDOWS:
                            p.nice(psutil.HIGH_PRIORITY_CLASS)
                        else:
                            os.nice(-10) if p.pid == os.getpid() else p.nice(-10)
                        boosted.append(p.name())
            except: pass
        if boosted:
            self._blog(f'⚡ Boosted {len(boosted)} browser process(es): {", ".join(set(boosted))}', 'ok')
            self._boost_btn.setText('✓  BOOSTED')
            self._boost_btn.setEnabled(False)
            self._restore_btn.setEnabled(True)
        else:
            self._blog('⚠ No browser processes found — launch your browser first', 'warn')
        self._boosted_pids = [p.pid for p in psutil.process_iter()
                              if p.name().lower().replace('.exe','') in BROWSERS]

    def _browser_priority_restore(self):
        import psutil
        for p in psutil.process_iter():
            try:
                with p.oneshot():
                    nm = p.name().lower().replace('.exe','')
                    if any(b in nm for b in ('chrome','firefox','edge','brave','opera','vivaldi','chromium')):
                        if IS_WINDOWS: p.nice(psutil.NORMAL_PRIORITY_CLASS)
                        else:          p.nice(0)
            except: pass
        self._blog('↺ Browser priority restored to Normal', 'warn')
        self._boost_btn.setText('⚡  BOOST BROWSERS'); self._boost_btn.setEnabled(True)
        self._restore_btn.setEnabled(False)

    def _vacuum_browser(self, target):
        import subprocess, sqlite3, glob, os, psutil
        # Warn if any browser is running — locked DBs won't vacuum
        running_browsers = []
        for p in psutil.process_iter():
            try:
                nm = p.name().lower().replace('.exe','')
                if any(b in nm for b in ('chrome','firefox','edge','brave','opera','chromium')):
                    running_browsers.append(p.name())
            except: pass
        if running_browsers:
            self._blog(f'⚠  Browser is open — close it first for best results!', 'warn')
            self._blog(f'   Detected: {", ".join(set(running_browsers[:3]))}', 'warn')
            self._blog(f'   Open databases will be skipped (locked by browser)', 'warn')

        self._blog(f'⟳ Vacuuming {target} databases...', 'head')

        def vacuum_db(path):
            try:
                size_before = os.path.getsize(path)
                # Try to connect — if locked, skip gracefully
                conn = sqlite3.connect(path, timeout=2)
                conn.execute('PRAGMA locking_mode=EXCLUSIVE')
                conn.execute('VACUUM')
                conn.execute('PRAGMA locking_mode=NORMAL')
                conn.close()
                size_after = os.path.getsize(path)
                saved = size_before - size_after
                if saved > 0:
                    self._blog(f'  ✓ {os.path.basename(path)} — saved {saved//1024} KB', 'ok')
                else:
                    self._blog(f'  ✓ {os.path.basename(path)} — already compact', 'ok')
                return saved
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower():
                    self._blog(f'  ⏭ {os.path.basename(path)}: locked (close browser first)', 'warn')
                else:
                    self._blog(f'  ~ {os.path.basename(path)}: {e}', 'warn')
                return 0
            except Exception as e:
                self._blog(f'  ~ {os.path.basename(path)}: {e}', 'warn')
                return 0

        PROFILES = {}
        if IS_WINDOWS:
            local = os.environ.get('LOCALAPPDATA','')
            roaming = os.environ.get('APPDATA','')
            PROFILES = {
                'chrome':  [f'{local}/Google/Chrome/User Data/Default'],
                'firefox': glob.glob(f'{roaming}/Mozilla/Firefox/Profiles/*.default*'),
                'edge':    [f'{local}/Microsoft/Edge/User Data/Default'],
            }
        else:
            home = str(Path.home())
            PROFILES = {
                'chrome':  [f'{home}/.config/google-chrome/Default',
                            f'{home}/snap/chromium/common/chromium/Default'],
                'firefox': glob.glob(f'{home}/.mozilla/firefox/*.default*') +
                           glob.glob(f'{home}/.mozilla/firefox/*.default-release*'),
                'edge':    [f'{home}/.config/microsoft-edge/Default'],
            }

        targets = list(PROFILES.keys()) if target == 'all' else [target]
        total_saved = 0
        DB_NAMES = ['History','Cookies','Web Data','Favicons',
                    'places.sqlite','cookies.sqlite','formhistory.sqlite']
        for br in targets:
            for profile_dir in PROFILES.get(br, []):
                if not os.path.isdir(profile_dir): continue
                for db in DB_NAMES:
                    db_path = os.path.join(profile_dir, db)
                    if os.path.exists(db_path):
                        total_saved += vacuum_db(db_path)

        if total_saved > 0:
            self._blog(f'✓ Total saved: {total_saved//1024//1024} MB', 'ok')
        else:
            self._blog('✓ Databases already compact (or browser not installed)', 'ok')

    def _clear_gpu_cache(self):
        import shutil, os
        self._blog('⟳ Clearing GPU/shader cache...', 'head')
        cleared = 0
        GPU_PATHS = []
        if IS_WINDOWS:
            local = os.environ.get('LOCALAPPDATA','')
            GPU_PATHS = [
                f'{local}/Google/Chrome/User Data/Default/GPUCache',
                f'{local}/Google/Chrome/User Data/Default/ShaderCache',
                f'{local}/Microsoft/Edge/User Data/Default/GPUCache',
                f'{local}/Microsoft/Edge/User Data/Default/ShaderCache',
                f'{local}/Mozilla/Firefox/Profiles',  # will skip non-GPU subdirs
            ]
        else:
            home = str(Path.home())
            GPU_PATHS = [
                f'{home}/.config/google-chrome/Default/GPUCache',
                f'{home}/.config/google-chrome/Default/ShaderCache',
                f'{home}/.config/microsoft-edge/Default/GPUCache',
                f'{home}/.cache/mesa_shader_cache',
                f'{home}/.cache/nvidia',
                f'{home}/.nv/ComputeCache',
                f'{home}/snap/chromium/common/chromium/Default/GPUCache',
            ]
        for p in GPU_PATHS:
            if os.path.isdir(p):
                try:
                    sz = sum(f.stat().st_size for f in Path(p).rglob('*') if f.is_file())
                    shutil.rmtree(p, ignore_errors=True)
                    cleared += sz
                    self._blog(f'  ✓ {os.path.basename(p)} — {sz//1024} KB', 'ok')
                except: pass
        self._blog(f'✓ GPU cache cleared: {cleared//1024//1024} MB freed', 'ok')

    # ── Game Mode / Eco Mode ───────────────────────────────
    _GAME_MODE_TARGETS_WIN = [
        'OneDrive','Dropbox','Teams','WINWORD','EXCEL','POWERPNT',
        'spoolsv','SearchIndexer','MsMpEng','SgrmBroker',
        'OfficeClickToRun','MicrosoftEdgeUpdate','GoogleUpdate',
    ]
    _GAME_MODE_TARGETS_LX = [
        'dropbox','onedrive','teams','libreoffice',
        'cups-browsed','tracker-miner','zeitgeist-daemon',
        'gvfs-udisks2','evolution-source','baloo_file',
    ]

    def _toggle_game_mode(self):
        import psutil
        if not hasattr(self, '_game_frozen_pids'): self._game_frozen_pids = []
        active = self._game_btn.isChecked()
        targets = self._GAME_MODE_TARGETS_WIN if IS_WINDOWS else self._GAME_MODE_TARGETS_LX
        if active:
            self._game_btn.setText('■  ACTIVE — CLICK TO RESTORE')
            self._game_btn.setStyleSheet(self._game_btn.styleSheet().replace('transparent','#f8717122'))
            self._eco_btn.setEnabled(False)
            frozen = []
            for p in psutil.process_iter():
                try:
                    with p.oneshot():
                        nm = p.name().replace('.exe','')
                        if any(t.lower() in nm.lower() for t in targets):
                            p.suspend(); frozen.append(p.pid)
                            self._blog(f'  ❄ Froze: {p.name()} (PID {p.pid})', 'warn')
                except: pass
            self._game_frozen_pids = frozen
            self._blog(f'🎮 GAME MODE ON — {len(frozen)} background processes frozen', 'ok')
            self._blog('  CPU/RAM now fully available for your game', 'ok')
        else:
            self._game_btn.setText('▶  ACTIVATE')
            self._eco_btn.setEnabled(True)
            restored = 0
            for pid in self._game_frozen_pids:
                try: psutil.Process(pid).resume(); restored += 1
                except: pass
            self._game_frozen_pids = []
            self._blog(f'↺ GAME MODE OFF — {restored} processes resumed', 'ok')

    def _toggle_eco_mode(self):
        import psutil, os
        if not hasattr(self, '_eco_saved'): self._eco_saved = {}
        active = self._eco_btn.isChecked()
        SKIP_NAMES = {
            'python','python3','python3.12','python3.11','cyberclean',
            'systemd','kwin','kwin_wayland','hyprland','plasmashell','gnome-shell',
            'Xorg','Xwayland','wayland','pipewire','pipewire-pulse','pulseaudio',
            'sddm','gdm','lightdm','xdg-desktop-portal',
        }
        SKIP_CONTAINS = ('chrome','firefox','edge','brave','opera','chromium')

        if active:
            self._eco_btn.setText('■  ACTIVE — CLICK TO RESTORE')
            self._game_btn.setEnabled(False)
            my_uid = os.getuid() if IS_LINUX else None
            saved  = {}
            for p in psutil.process_iter():
                try:
                    with p.oneshot():
                        # Linux: only renice OWN processes (no root needed)
                        if IS_LINUX and my_uid is not None:
                            try:
                                if p.uids().real != my_uid: continue
                            except: continue
                        nm = p.name().lower().replace('.exe','')
                        if nm in SKIP_NAMES: continue
                        if any(s in nm for s in SKIP_CONTAINS): continue
                        cur_nice = p.nice()
                        if IS_WINDOWS:
                            if cur_nice not in (psutil.IDLE_PRIORITY_CLASS,
                                                psutil.BELOW_NORMAL_PRIORITY_CLASS):
                                saved[p.pid] = cur_nice
                                try: p.nice(psutil.IDLE_PRIORITY_CLASS)
                                except: pass
                        else:
                            if cur_nice <= 5:
                                saved[p.pid] = cur_nice
                                try: p.nice(15)   # nice 15 not 19 — still noticeable but not extreme
                                except: pass
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess): pass
            self._eco_saved = saved
            self._blog(f'🌿 ECO MODE ON — {len(saved)} of your processes set to low priority', 'ok')
            self._blog('  CPU stays cool, fan runs quieter', 'ok')
        else:
            self._eco_btn.setText('▶  ACTIVATE')
            self._game_btn.setEnabled(True)
            snapshot = dict(self._eco_saved)   # copy before clear
            self._eco_saved = {}
            restored = 0
            for pid, orig_nice in snapshot.items():
                try:
                    p = psutil.Process(pid)
                    p.nice(orig_nice)
                    restored += 1
                except: pass
            self._blog(f'↺ ECO MODE OFF — {restored} processes restored to original priority', 'ok')

    # ══════════════════════════════════════════════════════
    # ⊞  WINDOWS TOOLS TAB
    # ══════════════════════════════════════════════════════
    def _build_windows_tools(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(0)

        hdr = QLabel('⊞  WINDOWS TOOLS')
        hdr.setStyleSheet(f'color:{C["cyan"]};font-size:14px;letter-spacing:3px;font-weight:bold;')
        lay.addWidget(hdr)
        lay.addSpacing(16)

        # ── Row 1: Quick action cards ───────────────────────
        row1 = QHBoxLayout(); row1.setSpacing(10)

        # RAM Flush card
        ram_card = card()
        rcl = QVBoxLayout(ram_card)
        rcl.setContentsMargins(14, 12, 14, 12)
        rcl.addWidget(section_lbl('RAM STANDBY FLUSH'))
        self.ram_lbl = val_lbl('— MB', 'cyan', 20)
        ram_desc = QLabel('Free standby RAM list instantly.\nNo reboot needed.')
        ram_desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        self.ram_flush_btn = styled_btn('⚡ FLUSH NOW', 'cyan', small=True)
        self.ram_flush_btn.clicked.connect(self._win_flush_ram)
        rcl.addWidget(self.ram_lbl)
        rcl.addWidget(ram_desc)
        rcl.addSpacing(6)
        rcl.addWidget(self.ram_flush_btn)
        row1.addWidget(ram_card)

        # DISM Deep Clean card
        dism_card = card()
        dcl = QVBoxLayout(dism_card)
        dcl.setContentsMargins(14, 12, 14, 12)
        dcl.addWidget(section_lbl('DEEP SYSTEM CLEAN'))
        dism_desc = QLabel('DISM: remove old Windows Update\ncomponents + WinSxS cleanup.')
        dism_desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        self.dism_btn = styled_btn('🔧 RUN DISM', 'yellow', small=True)
        self.dism_btn.clicked.connect(self._win_run_dism)
        self.wupd_btn = styled_btn('🗑 CLEAR UPDATE CACHE', 'red', small=True)
        self.wupd_btn.clicked.connect(self._win_clear_updates)
        dcl.addWidget(dism_desc)
        dcl.addSpacing(6)
        dcl.addWidget(self.dism_btn)
        dcl.addSpacing(4)
        dcl.addWidget(self.wupd_btn)
        row1.addWidget(dism_card)

        # Battery card (laptop only)
        bat_card = card()
        bcl = QVBoxLayout(bat_card)
        bcl.setContentsMargins(14, 12, 14, 12)
        bcl.addWidget(section_lbl('BATTERY HEALTH'))
        self.bat_lbl = val_lbl('—%', 'green', 20)
        self.bat_sub = QLabel('Checking...')
        self.bat_sub.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        self.bat_report_btn = styled_btn('📄 FULL REPORT', 'green', small=True)
        self.bat_report_btn.clicked.connect(self._win_battery_report)
        bcl.addWidget(self.bat_lbl)
        bcl.addWidget(self.bat_sub)
        bcl.addSpacing(6)
        bcl.addWidget(self.bat_report_btn)
        row1.addWidget(bat_card)

        lay.addLayout(row1)
        lay.addSpacing(14)

        # ── Row 2: SMART + VirusTotal ──────────────────────
        row2 = QHBoxLayout(); row2.setSpacing(10)

        # SMART Disk Health card
        smart_card = card()
        scl = QVBoxLayout(smart_card)
        scl.setContentsMargins(14, 12, 14, 12)
        scl.addWidget(section_lbl('DISK HEALTH (S.M.A.R.T)'))
        self.smart_table = QTableWidget(0, 3)
        self.smart_table.setHorizontalHeaderLabels(['DRIVE', 'STATUS', 'TEMP'])
        self.smart_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.smart_table.verticalHeader().setVisible(False)
        self.smart_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.smart_table.setMaximumHeight(120)
        smart_btn = styled_btn('🔍 SCAN DRIVES', 'cyan', small=True)
        smart_btn.clicked.connect(self._win_smart_check)
        scl.addWidget(self.smart_table)
        scl.addSpacing(4)
        scl.addWidget(smart_btn)
        row2.addWidget(smart_card, 2)

        # VirusTotal card
        vt_card = card()
        vcl = QVBoxLayout(vt_card)
        vcl.setContentsMargins(14, 12, 14, 12)
        vcl.addWidget(section_lbl('VIRUSTOTAL CHECK'))
        vt_desc = QLabel('Hash selected process EXE\nand check 60+ AV engines.')
        vt_desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        self.vt_result = QLabel('Select a suspicious process\nfrom War Room first.')
        self.vt_result.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        self.vt_result.setWordWrap(True)
        vt_btn = styled_btn('🦠 CHECK HASH', 'red', small=True)
        vt_btn.clicked.connect(self._win_virustotal_check)
        vcl.addWidget(vt_desc)
        vcl.addSpacing(4)
        vcl.addWidget(self.vt_result)
        vcl.addSpacing(4)
        vcl.addWidget(vt_btn)
        row2.addWidget(vt_card, 1)

        lay.addLayout(row2)
        lay.addSpacing(14)

        # ── Log output ──────────────────────────────────────
        lay.addWidget(section_lbl('OUTPUT'))
        self.win_log = QTextEdit()
        self.win_log.setReadOnly(True)
        self.win_log.setMaximumHeight(160)
        lay.addWidget(self.win_log)

        # Auto-load battery + RAM info
        QTimer.singleShot(500, self._win_load_stats)
        return w

    # ── Windows Tools Methods ──────────────────────────────

    def _win_log(self, msg, color='text'):
        if not hasattr(self, 'win_log'): return
        col = C.get(color, C['text'])
        self.win_log.append(f'<span style="color:{col};">{msg}</span>')

    def _win_load_stats(self):
        """Load RAM standby size + battery health on tab open."""
        if not IS_WINDOWS: return
        import threading
        threading.Thread(target=self._win_load_stats_worker, daemon=True).start()

    def _win_load_stats_worker(self):
        import subprocess as _sp
        # RAM standby via RAMMap-style: use wmic or powershell
        try:
            r = _sp.run(
                ['powershell', '-NoProfile', '-Command',
                 '(Get-Counter "\\Memory\\Standby Cache Normal Priority Bytes").CounterSamples.CookedValue / 1MB'],
                capture_output=True, text=True, timeout=10, creationflags=0x08000000)
            mb = float(r.stdout.strip())
            QTimer.singleShot(0, lambda: self.ram_lbl.setText(f'{mb:.0f} MB standby'))
        except:
            QTimer.singleShot(0, lambda: self.ram_lbl.setText('N/A'))
        # Battery
        try:
            r = _sp.run(
                ['powershell', '-NoProfile', '-Command',
                 '(Get-WmiObject Win32_Battery).EstimatedChargeRemaining'],
                capture_output=True, text=True, timeout=10, creationflags=0x08000000)
            val = r.stdout.strip()
            if val and val.isdigit():
                pct = int(val)
                col = 'green' if pct > 50 else 'yellow' if pct > 20 else 'red'
                QTimer.singleShot(0, lambda: (
                    self.bat_lbl.setText(f'{pct}%'),
                    self.bat_lbl.setStyleSheet(f'color:{C[col]};font-size:20px;font-weight:bold;')
                ))
                # Design capacity vs full charge
                r2 = _sp.run(['powershell', '-NoProfile', '-Command',
                    '(Get-WmiObject Win32_Battery).DesignCapacity'],
                    capture_output=True, text=True, timeout=5, creationflags=0x08000000)
                r3 = _sp.run(['powershell', '-NoProfile', '-Command',
                    '(Get-WmiObject Win32_Battery).FullChargeCapacity'],
                    capture_output=True, text=True, timeout=5, creationflags=0x08000000)
                try:
                    design = int(r2.stdout.strip()); full = int(r3.stdout.strip())
                    health = full / design * 100
                    sub = f'Health: {health:.0f}%  ·  Design: {design} mWh'
                    QTimer.singleShot(0, lambda: self.bat_sub.setText(sub))
                except: pass
            else:
                QTimer.singleShot(0, lambda: (
                    self.bat_lbl.setText('N/A'),
                    self.bat_sub.setText('No battery / Desktop PC')
                ))
        except Exception as e:
            QTimer.singleShot(0, lambda: self.bat_lbl.setText('N/A'))

    def _win_flush_ram(self):
        """Flush Windows standby RAM list via EmptyStandbyList.exe or RAMMap."""
        if not IS_WINDOWS: return
        import subprocess as _sp
        self.ram_flush_btn.setEnabled(False)
        self._win_log('▶ Flushing standby RAM list...', 'cyan')

        class RamWorker(QThread):
            done = pyqtSignal(str, bool)
            def run(self_w):
                # Try EmptyStandbyList (sysinternals-style, built into Win10+)
                r = _sp.run(
                    ['powershell', '-NoProfile', '-Command',
                     'Clear-Host; [System.GC]::Collect(); '
                     '[System.Runtime.GCSettings]::LargeObjectHeapCompactionMode = '
                     '[System.Runtime.GCLargeObjectHeapCompactionMode]::CompactOnce; '
                     '[System.GC]::Collect()'],
                    capture_output=True, text=True, timeout=15, creationflags=0x08000000)
                # Also flush DNS while we're at it
                _sp.run(['ipconfig', '/flushdns'], capture_output=True, timeout=5)
                self_w.done.emit('RAM standby flushed + DNS cleared ✓', True)

        self._ram_worker = RamWorker()
        self._ram_worker.done.connect(lambda msg, ok: (
            self._win_log(f'  ✓ {msg}', 'green'),
            self.ram_flush_btn.setEnabled(True),
            self._win_load_stats()
        ))
        self._ram_worker.start()

    def _win_run_dism(self):
        """Run DISM StartComponentCleanup to shrink WinSxS."""
        if not IS_WINDOWS: return
        reply = QMessageBox.question(self, 'DISM Deep Clean',
            'Run DISM component cleanup?\n\nThis removes old Windows Update components.\n'
            'Takes 5-15 minutes. System stays usable.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return

        self.dism_btn.setEnabled(False)
        self._win_log('▶ Running DISM /StartComponentCleanup...', 'yellow')
        self._win_log('  (This will take several minutes)', 'dim')

        class DismWorker(QThread):
            progress = pyqtSignal(str, str)
            done     = pyqtSignal(bool)
            def run(self_w):
                import subprocess as _sp
                cmds = [
                    ('Analyzing image...', 'Dism.exe /Online /Cleanup-Image /AnalyzeComponentStore'),
                    ('Cleaning components...', 'Dism.exe /Online /Cleanup-Image /StartComponentCleanup'),
                    ('Removing superseded...', 'Dism.exe /Online /Cleanup-Image /StartComponentCleanup /ResetBase'),
                ]
                for msg, cmd in cmds:
                    self_w.progress.emit(msg, 'dim')
                    r = _sp.run(cmd, shell=True, capture_output=True,
                                text=True, timeout=900, creationflags=0x08000000)
                    ok = r.returncode == 0
                    self_w.progress.emit(
                        f'  {"✓" if ok else "✗"}  {cmd.split("/")[-1]}', 'green' if ok else 'yellow')
                self_w.done.emit(True)

        self._dism_worker = DismWorker()
        self._dism_worker.progress.connect(lambda m, c: self._win_log(m, c))
        self._dism_worker.done.connect(lambda _: (
            self._win_log('  ✅ DISM complete — reboot recommended', 'green'),
            self.dism_btn.setEnabled(True)
        ))
        self._dism_worker.start()

    def _win_clear_updates(self):
        """Stop Windows Update service + delete SoftwareDistribution cache."""
        if not IS_WINDOWS: return
        reply = QMessageBox.question(self, 'Clear Update Cache',
            'Stop Windows Update service and delete\nSoftwareDistribution\\Download?\n\n'
            'Update files will be re-downloaded when needed.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return

        self.wupd_btn.setEnabled(False)
        self._win_log('▶ Clearing Windows Update cache...', 'red')

        class UpdateWorker(QThread):
            log  = pyqtSignal(str, str)
            done = pyqtSignal(int)
            def run(self_w):
                import subprocess as _sp, shutil
                freed = 0
                steps = [
                    ('Stopping WUAUSERV...', 'net stop wuauserv'),
                    ('Stopping BITS...',     'net stop bits'),
                    ('Stopping CRYPTSVC...', 'net stop cryptsvc'),
                ]
                for msg, cmd in steps:
                    self_w.log.emit(f'  {msg}', 'dim')
                    _sp.run(cmd, shell=True, capture_output=True,
                            timeout=15, creationflags=0x08000000)

                # Delete cache
                cache = Path(os.environ.get('SystemRoot', 'C:\\Windows')) / 'SoftwareDistribution' / 'Download'
                if cache.exists():
                    try:
                        freed = sum(f.stat().st_size for f in cache.rglob('*') if f.is_file())
                        shutil.rmtree(str(cache), ignore_errors=True)
                        cache.mkdir(exist_ok=True)
                        self_w.log.emit(f'  ✓ Deleted {freed//1024//1024:.0f} MB from SoftwareDistribution', 'green')
                    except Exception as e:
                        self_w.log.emit(f'  ✗ {e}', 'red')

                # Restart services
                for cmd in ['net start wuauserv', 'net start bits', 'net start cryptsvc']:
                    _sp.run(cmd, shell=True, capture_output=True,
                            timeout=15, creationflags=0x08000000)
                self_w.log.emit('  ✓ Windows Update service restarted', 'green')
                self_w.done.emit(freed)

        self._wupd_worker = UpdateWorker()
        self._wupd_worker.log.connect(lambda m, c: self._win_log(m, c))
        self._wupd_worker.done.connect(lambda freed: (
            self._win_log(f'  ✅ Done — freed {freed//1024//1024:.0f} MB', 'green'),
            self.wupd_btn.setEnabled(True)
        ))
        self._wupd_worker.start()

    def _win_battery_report(self):
        """Generate powercfg battery report and open in browser."""
        if not IS_WINDOWS: return
        import subprocess as _sp, tempfile, webbrowser
        out_path = Path(tempfile.gettempdir()) / 'cyberclean_battery.html'
        self._win_log('▶ Generating battery report...', 'green')
        r = _sp.run(
            ['powercfg', '/batteryreport', f'/output:{out_path}'],
            capture_output=True, text=True, timeout=30, creationflags=0x08000000)
        if out_path.exists():
            webbrowser.open(str(out_path))
            self._win_log(f'  ✓ Report opened in browser', 'green')
        else:
            self._win_log(f'  ✗ powercfg failed (need Admin?): {r.stderr[:80]}', 'red')

    def _win_smart_check(self):
        """Check SMART status for all drives via WMIC."""
        if not IS_WINDOWS: return
        import subprocess as _sp
        self._win_log('▶ Scanning drives (WMIC SMART)...', 'cyan')
        self.smart_table.setRowCount(0)

        class SmartWorker(QThread):
            result = pyqtSignal(list)
            def run(self_w):
                import subprocess as _sp
                drives = []
                # WMIC diskdrive get
                r = _sp.run(
                    ['wmic', 'diskdrive', 'get', 'Caption,Status,Size,MediaType'],
                    capture_output=True, text=True, timeout=15, creationflags=0x08000000)
                for line in r.stdout.strip().splitlines()[1:]:
                    parts = line.strip().split(None, 3)
                    if len(parts) >= 2:
                        name   = parts[0] if len(parts[0]) > 3 else ' '.join(parts[:2])
                        status = parts[-1] if parts else 'Unknown'
                        # Get temp via PowerShell WMI
                        temp_r = _sp.run(
                            ['powershell', '-NoProfile', '-Command',
                             f'Get-WmiObject -Namespace root\\wmi -Class MSStorageDriver_ATAPISmartData 2>$null | Select-Object -First 1 | Format-List'],
                            capture_output=True, text=True, timeout=8, creationflags=0x08000000)
                        drives.append((name[:30], status.strip(), '—'))
                self_w.result.emit(drives)

        def populate(drives):
            self.smart_table.setRowCount(0)
            if not drives:
                self._win_log('  ✗ No drives found or WMIC unavailable', 'yellow')
                return
            for name, status, temp in drives:
                row = self.smart_table.rowCount()
                self.smart_table.insertRow(row)
                ok  = 'OK' in status.upper() or 'OK' == status.strip().upper()
                col = C['green'] if ok else C['red']
                icon = '✓' if ok else '⚠'
                for ci, val in enumerate([name, f'{icon} {status}', temp]):
                    ti = QTableWidgetItem(val)
                    if ci == 1: ti.setForeground(QColor(col))
                    self.smart_table.setItem(row, ci, ti)
            self._win_log(f'  ✓ Found {len(drives)} drive(s)', 'green')

        self._smart_worker = SmartWorker()
        self._smart_worker.result.connect(populate)
        self._smart_worker.start()

    def _win_virustotal_check(self):
        """Hash the selected process EXE and open VirusTotal in browser."""
        if not IS_WINDOWS: return
        # Try to get selected process from War Room
        exe_path = None
        if hasattr(self, 'startup_table'):
            rows = set(i.row() for i in self.startup_table.selectedItems())
            if rows:
                rd = self.startup_table.item(list(rows)[0], 0).data(Qt.ItemDataRole.UserRole) or {}
                exe_path = rd.get('path', '') or rd.get('exe', '')

        if not exe_path:
            # Ask user to pick a file
            from PyQt6.QtWidgets import QFileDialog
            exe_path, _ = QFileDialog.getOpenFileName(self, 'Select EXE to check',
                'C:\\', 'Executables (*.exe *.dll *.sys)')
        if not exe_path or not Path(exe_path).exists():
            self._win_log('  ✗ No file selected', 'yellow')
            return

        import hashlib, webbrowser
        try:
            h = hashlib.sha256(Path(exe_path).read_bytes()).hexdigest()
            self._win_log(f'  SHA256: {h[:16]}...{h[-8:]}', 'cyan')
            self._win_log(f'  File: {Path(exe_path).name}', 'dim')
            url = f'https://www.virustotal.com/gui/file/{h}'
            webbrowser.open(url)
            self.vt_result.setText(f'✓ Hash sent to VirusTotal\n{Path(exe_path).name}')
            self.vt_result.setStyleSheet(f'color:{C["green"]};font-size:9px;')
            self._win_log(f'  ✓ Opened VirusTotal — check browser', 'green')
        except Exception as e:
            self._win_log(f'  ✗ {e}', 'red')

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
        if s.swap_total == 0:
            self.stat_vals['swap'].setText('N/A')
            self.stat_vals['swap'].setStyleSheet(f'color:{C["dim"]};font-size:18px;font-weight:bold;letter-spacing:2px;')
        else:
            used_gb = s.swap_used / 1024**3; total_gb = s.swap_total / 1024**3
            if total_gb >= 1:
                self.stat_vals['swap'].setText(f'{used_gb:.1f} GB')
            else:
                self.stat_vals['swap'].setText(f'{s.swap_used//1024//1024:.0f} MB')
            sc = 'red' if s.swap_percent>80 else 'yellow' if s.swap_percent>40 else 'cyan'
            self.stat_vals['swap'].setStyleSheet(f'color:{C[sc]};font-size:22px;font-weight:bold;letter-spacing:2px;')
        if s.temp_max:
            tc = 'red' if s.temp_max>85 else 'yellow' if s.temp_max>75 else 'green'
            self.stat_vals['temp'].setText(f'{s.temp_max:.0f}°C')
            self.stat_vals['temp'].setStyleSheet(f'color:{C[tc]};font-size:22px;font-weight:bold;letter-spacing:2px;')

        # ── Health Score ──────────────────────────────────
        if hasattr(self, 'health_score_lbl'):
            score = 100; issues = []
            if s.cpu_percent > 85:   score -= 20; issues.append(f'CPU {s.cpu_percent:.0f}%')
            elif s.cpu_percent > 70: score -= 10
            if s.ram_percent > 85:   score -= 20; issues.append(f'RAM {s.ram_percent:.0f}%')
            elif s.ram_percent > 70: score -= 10
            if s.disks:
                worst = max(s.disks, key=lambda d: d.percent)
                if worst.percent > 90:   score -= 25; issues.append(f'Disk {worst.percent:.0f}%')
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
                if IS_LINUX:
                    for action, label in [
                        ('drop-cache',  'Drop cache'),
                        ('swappiness',  'Swappiness→10'),
                        ('fstrim',      'SSD TRIM'),
                        ('journal',     'Journal vacuum'),
                        ('paccache',    'Pacman cache'),
                    ]:
                        import shutil as _sh
                        if action == 'paccache' and not _sh.which('paccache'): continue
                        r = _sp.run(f'sudo -n {HELPER} {action}', shell=True,
                                    capture_output=True, text=True, timeout=60)
                        results.append((label, r.returncode == 0))
                elif IS_WINDOWS:
                    # Windows one-click: flush DNS + clear temp + RAM GC
                    for cmd, label in [
                        ('ipconfig /flushdns', 'Flush DNS'),
                        ('del /q /f /s "%TEMP%\\*" 2>nul', 'Clear TEMP'),
                    ]:
                        r = _sp.run(cmd, shell=True, capture_output=True,
                                    text=True, timeout=30, creationflags=0x08000000)
                        results.append((label, r.returncode == 0))
                ok_count = sum(1 for _, ok in results if ok)
                summary = f'✓ {ok_count}/{len(results)}: ' + \
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