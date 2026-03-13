"""
CyberClean v2.0 — Main GUI (Redesigned)
Tabs: Dashboard · Clean · Scanner · Uninstall · History · Rollback · Browser Turbo
CPU fix: 4s refresh interval, paused when not on Dashboard
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
    print(f"[CyberClean] Missing: {', '.join(_missing)}")
    print("Install: pip install psutil PyQt6")
    sys.exit(1)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QStackedWidget, QScrollArea,
    QTableWidget, QTableWidgetItem, QCheckBox, QProgressBar,
    QTextEdit, QHeaderView, QMessageBox, QSystemTrayIcon, QMenu,
    QSizePolicy, QLineEdit, QComboBox, QFileDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPointF, QRectF
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QTextCursor, QPainter, QBrush,
    QPen, QLinearGradient, QIcon, QAction, QPolygonF, QPixmap
)

sys.path.insert(0, str(Path(__file__).parent))
from core.os_detect  import (IS_LINUX, IS_WINDOWS, PKG_MANAGER, platform_info,
                                HAS_POLKIT, HAS_POLKIT_AGENT, HAS_FLATPAK, HAS_DOCKER,
                                HAS_SEND2TRASH, request_windows_admin, is_windows_admin)
from utils.sysinfo   import get_snapshot, get_startup_items, toggle_startup_linux, fmt_size
from core.scanner    import SecurityScanner
from core.uninstaller import get_installed_apps, uninstall_app, InstalledApp

if IS_WINDOWS and not is_windows_admin():
    request_windows_admin()

if IS_LINUX:
    from core.linux_cleaner import LinuxCleaner
    CLEANER = LinuxCleaner()
elif IS_WINDOWS:
    from core.windows_cleaner import WindowsCleaner
    CLEANER = WindowsCleaner()
else:
    CLEANER = None

LOG_DIR       = Path.home() / '.local/share/cyber-clean'
LOG_FILE      = LOG_DIR / 'history.jsonl'
ROLLBACK_FILE = LOG_DIR / 'rollback.jsonl'
LOG_DIR.mkdir(parents=True, exist_ok=True)
OS = platform.system()

# ── Design Tokens ────────────────────────────────────────────
C = {
    'bg':      '#070d12',
    'bg2':     '#0c1620',
    'bg3':     '#111e2c',
    'bg4':     '#162333',
    'cyan':    '#00c8e0',
    'cyan2':   '#00a8bc',
    'red':     '#f03050',
    'yellow':  '#f0c040',
    'green':   '#40d080',
    'purple':  '#c060f0',
    'dim':     '#3a5565',
    'dim2':    '#2a404f',
    'text':    '#a8ccd8',
    'text2':   '#7099a8',
    'border':  '#0e2030',
    'border2': '#163040',
    'accent':  '#00c8e0',
}

MONO = "'Cascadia Code','JetBrains Mono','Consolas','Share Tech Mono',monospace"

# ═════════════════════════════════════════════════════════════
# SPARKLINE CHART
# ═════════════════════════════════════════════════════════════
class SparklineChart(QWidget):
    def __init__(self, color='#00c8e0', max_points=50, parent=None):
        super().__init__(parent)
        self.color    = QColor(color)
        self.max_pts  = max_points
        self.data     = []
        self.setMinimumHeight(52)
        self.setMaximumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet('background:transparent;')

    def push(self, value: float):
        self.data.append(max(0.0, min(100.0, value)))
        if len(self.data) > self.max_pts:
            self.data.pop(0)
        self.update()

    def paintEvent(self, _):
        if len(self.data) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad  = 2

        # Subtle grid
        grid_pen = QPen(QColor(C['border']))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        for pct in [50]:
            y = h - pad - (pct / 100) * (h - pad * 2)
            p.drawLine(0, int(y), w, int(y))

        pts = []
        for i, v in enumerate(self.data):
            x = pad + (i / (self.max_pts - 1)) * (w - pad * 2)
            y = h - pad - (v / 100.0) * (h - pad * 2)
            pts.append(QPointF(x, y))

        fill_pts = [QPointF(pts[0].x(), h)] + pts + [QPointF(pts[-1].x(), h)]
        grad = QLinearGradient(0, 0, 0, h)
        fc = QColor(self.color); fc.setAlphaF(0.18)
        fc2 = QColor(self.color); fc2.setAlphaF(0.02)
        grad.setColorAt(0, fc); grad.setColorAt(1, fc2)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF(fill_pts))

        lp = QPen(self.color); lp.setWidth(2)
        p.setPen(lp)
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])

        if pts:
            dp = QPen(self.color); dp.setWidth(2)
            p.setPen(dp); p.setBrush(QBrush(self.color))
            p.drawEllipse(pts[-1], 3, 3)
        p.end()


# ═════════════════════════════════════════════════════════════
# DISK RING
# ═════════════════════════════════════════════════════════════
class DiskRing(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.percent = 0.0
        self.setFixedSize(80, 80)

    def set_percent(self, v):
        self.percent = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect  = QRectF(7, 7, 66, 66)
        color = C['red'] if self.percent > 90 else C['yellow'] if self.percent > 75 else C['cyan']

        bg_pen = QPen(QColor(C['bg3'])); bg_pen.setWidth(7)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(bg_pen); p.drawArc(rect, 0, 360 * 16)

        fill_pen = QPen(QColor(color)); fill_pen.setWidth(7)
        fill_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(fill_pen)
        span = int((self.percent / 100.0) * 360 * 16)
        p.drawArc(rect, 90 * 16, -span)

        p.setPen(QPen(QColor(color)))
        p.setFont(QFont('Cascadia Code' if IS_WINDOWS else 'Share Tech Mono', 12, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 80, 80), Qt.AlignmentFlag.AlignCenter, f'{int(self.percent)}%')
        p.end()


# ═════════════════════════════════════════════════════════════
# WORKER THREADS
# ═════════════════════════════════════════════════════════════
class SysInfoWorker(QThread):
    snapshot = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.paused  = False
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        while not self._stopped:
            if not self.paused:
                try:
                    s = get_snapshot(interval=0.3)
                    self.snapshot.emit(s)
                except:
                    pass
            self.msleep(4000)   # 4s — CPU-friendly


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

        self.log.emit('─' * 44, 'head')
        mode = 'DRY-RUN' if self.dry else 'CLEAN'
        self.log.emit(f'  {mode}  ·  {datetime.now().strftime("%H:%M:%S")}', 'head')
        self.log.emit('─' * 44, 'head')

        for i, tid in enumerate(self.targets):
            pct = int((i / steps) * 90)
            self.progress.emit(pct, f'{tid}...')
            self.log.emit(f'\n  ▸ {tid.upper().replace("_", " ")}', 'head')
            result = CLEANER.clean(tid, dry=self.dry)

            if result.error:
                self.log.emit(f'  ✗  {result.error}', 'err')
            elif self.dry:
                self.log.emit(f'  ~  ~{fmt_size(result.freed_bytes)}', 'dry')
                if result.files_removed:
                    self.log.emit(f'     {result.files_removed} items', 'dry')
            else:
                self.log.emit(f'  ✓  {fmt_size(result.freed_bytes)} freed', 'ok')
                if result.files_removed:
                    self.log.emit(f'     {result.files_removed} removed', 'ok')

            total_freed += result.freed_bytes
            rollback    += result.rollback
            if result.freed_bytes > 0:
                summary.append(f'{tid}:{fmt_size(result.freed_bytes)}')

        self.progress.emit(100, 'done')
        self.log.emit('\n' + '─' * 44, 'head')
        label = 'ESTIMATED' if self.dry else 'FREED'
        self.log.emit(f'  TOTAL {label}: {fmt_size(total_freed)}', 'ok')
        self.done.emit({'freed': total_freed, 'dry': self.dry,
                        'summary': ' | '.join(summary), 'rollback': rollback})


# ═════════════════════════════════════════════════════════════
# UI HELPERS
# ═════════════════════════════════════════════════════════════
def _btn(text, color='cyan', small=False, icon_only=False):
    col = C[color]
    btn = QPushButton(text)
    pad = '4px 10px' if small else '7px 18px'
    sz  = '10px' if small else '11px'
    btn.setStyleSheet(f"""
        QPushButton {{
            color:{col}; border:1px solid {col}33;
            background:{col}08;
            font-family:{MONO}; font-size:{sz};
            letter-spacing:1px; padding:{pad};
            border-radius:2px;
        }}
        QPushButton:hover   {{ background:{col}18; border-color:{col}66; }}
        QPushButton:pressed {{ background:{col}28; }}
        QPushButton:checked {{ background:{col}20; border-color:{col}; color:{col}; }}
        QPushButton:disabled {{ color:{C['dim']}; border-color:{C['dim']}22;
                                background:transparent; }}
    """)
    return btn


def _lbl_small(text):
    l = QLabel(text)
    l.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;'
                    f'font-family:{MONO};padding:8px 0 3px 0;')
    return l


def _lbl_val(text, color='cyan', size=20):
    l = QLabel(text)
    l.setStyleSheet(f'color:{C[color]};font-size:{size}px;font-weight:700;'
                    f'font-family:{MONO};letter-spacing:1px;')
    return l


def _card(border_color=None):
    f = QFrame()
    bc = border_color or C['border']
    f.setStyleSheet(f'QFrame{{background:{C["bg2"]};border:1px solid {bc};border-radius:3px;}}')
    return f


def _divider():
    l = QFrame()
    l.setFrameShape(QFrame.Shape.HLine)
    l.setStyleSheet(f'color:{C["border2"]};background:{C["border2"]};border:none;max-height:1px;')
    return l


# ═════════════════════════════════════════════════════════════
# STAT CARD WIDGET  (reusable)
# ═════════════════════════════════════════════════════════════
class StatCard(QFrame):
    def __init__(self, label, init_val, color='cyan', parent=None):
        super().__init__(parent)
        self.color = color
        self.setStyleSheet(
            f'QFrame{{background:{C["bg2"]};border:1px solid {C["border"]};border-radius:3px;}}'
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)

        self.lbl_name = QLabel(label)
        self.lbl_name.setStyleSheet(
            f'color:{C["dim"]};font-size:9px;letter-spacing:2px;font-family:{MONO};'
        )
        self.lbl_val = QLabel(init_val)
        self.lbl_val.setStyleSheet(
            f'color:{C[color]};font-size:22px;font-weight:700;'
            f'font-family:{MONO};letter-spacing:1px;'
        )
        lay.addWidget(self.lbl_name)
        lay.addWidget(self.lbl_val)

    def set_val(self, text, color=None):
        self.lbl_val.setText(text)
        col = C.get(color or self.color, C[self.color])
        self.lbl_val.setStyleSheet(
            f'color:{col};font-size:22px;font-weight:700;'
            f'font-family:{MONO};letter-spacing:1px;'
        )


# ═════════════════════════════════════════════════════════════
# MAIN APP
# ═════════════════════════════════════════════════════════════
class CyberCleanApp(QMainWindow):

    NAV_ITEMS = [
        ('dashboard', '◈', 'DASHBOARD'),
        ('clean',     '⚡', 'CLEAN'),
        ('scanner',   '⬡', 'SCANNER'),
        ('uninstall', '✕', 'UNINSTALL'),
        ('log',       '▤', 'HISTORY'),
        ('rollback',  '↺', 'ROLLBACK'),
        ('browser',   '⊕', 'BROWSER TURBO'),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle('CyberClean v2.0')
        self.setMinimumSize(1060, 680)
        self.resize(1180, 740)
        self.worker   = None
        self.selected = set()
        self._charts  = {}
        self._snap    = None

        self._init_palette()
        self._build_ui()
        self._start_sysinfo()
        self._start_clock()
        self._nav('dashboard')
        self._setup_tray()
        self._start_auto_clean()
        self._check_update_async()

    # ── Palette ─────────────────────────────────────────────
    def _init_palette(self):
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window,        QColor(C['bg']))
        pal.setColor(QPalette.ColorRole.WindowText,    QColor(C['text']))
        pal.setColor(QPalette.ColorRole.Base,          QColor(C['bg2']))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(C['bg3']))
        pal.setColor(QPalette.ColorRole.Text,          QColor(C['text']))
        QApplication.setPalette(pal)
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background:{C['bg']}; color:{C['text']};
                font-family:{MONO};
            }}
            QScrollBar:vertical {{
                background:{C['bg2']}; width:4px; border:none;
            }}
            QScrollBar::handle:vertical {{
                background:{C['dim2']}; border-radius:2px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar:horizontal {{
                background:{C['bg2']}; height:4px; border:none;
            }}
            QScrollBar::handle:horizontal {{
                background:{C['dim2']}; border-radius:2px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
            QTableWidget {{
                background:{C['bg2']}; border:1px solid {C['border']};
                gridline-color:{C['border']}; font-size:11px; border-radius:2px;
            }}
            QTableWidget::item {{ padding:5px 8px; border:none; background:transparent; }}
            QTableWidget::item:alternate {{ background:{C['bg3']}; }}
            QTableWidget::item:selected {{
                background:{C['cyan']}16; color:{C['cyan']};
            }}
            QHeaderView::section {{
                background:{C['bg']};color:{C['dim']};border:none;
                border-bottom:1px solid {C['border2']};
                padding:5px 8px;font-size:9px;letter-spacing:2px;
            }}
            QCheckBox {{ color:{C['text']}; spacing:6px; }}
            QCheckBox::indicator {{
                width:12px; height:12px;
                border:1px solid {C['dim']}; background:transparent;
                border-radius:1px;
            }}
            QCheckBox::indicator:checked {{
                background:{C['cyan']}22; border-color:{C['cyan']};
            }}
            QProgressBar {{
                background:{C['bg3']}; border:none; height:2px; border-radius:1px;
            }}
            QProgressBar::chunk {{
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['cyan']},stop:1 {C['green']});
            }}
            QTextEdit {{
                background:#030810; color:{C['text']};
                border:1px solid {C['border']}; border-radius:2px;
                font-family:{MONO}; font-size:11px; padding:8px;
            }}
            QLineEdit {{
                background:{C['bg3']}; color:{C['text']};
                border:1px solid {C['border']}; border-radius:2px;
                padding:5px 10px; font-size:11px; font-family:{MONO};
            }}
            QLineEdit:focus {{ border-color:{C['cyan']}66; }}
            QComboBox {{
                background:{C['bg3']}; color:{C['text']};
                border:1px solid {C['border']}; border-radius:2px;
                padding:5px 8px; font-size:11px;
            }}
            QMenu {{
                background:{C['bg2']}; color:{C['text']};
                border:1px solid {C['border']};
            }}
            QMenu::item:selected {{ background:{C['cyan']}1a; }}
        """)

    # ── Build UI ─────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_header())
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(self._build_sidebar(), 0)
        bl.addWidget(self._build_main(), 1)
        lay.addWidget(body, 1)

    # ── HEADER ───────────────────────────────────────────────
    def _build_header(self):
        h = QFrame()
        h.setFixedHeight(50)
        h.setStyleSheet(
            f'QFrame{{background:{C["bg"]};'
            f'border-bottom:1px solid {C["border2"]};}}'
        )
        lay = QHBoxLayout(h)
        lay.setContentsMargins(22, 0, 22, 0)

        # Logo
        logo = QLabel('CYBER')
        logo.setStyleSheet(
            f'color:{C["cyan"]};font-size:16px;font-weight:900;'
            f'letter-spacing:5px;font-family:{MONO};'
        )
        dash = QLabel('—')
        dash.setStyleSheet(f'color:{C["dim"]};font-size:14px;padding:0 4px;')
        clean = QLabel('CLEAN')
        clean.setStyleSheet(
            f'color:{C["text2"]};font-size:16px;font-weight:700;'
            f'letter-spacing:5px;font-family:{MONO};'
        )
        ver = QLabel('v2.0')
        ver.setStyleSheet(
            f'color:{C["dim"]};font-size:9px;letter-spacing:1px;'
            f'padding-left:10px;padding-top:5px;font-family:{MONO};'
        )

        sep = QLabel('·')
        sep.setStyleSheet(f'color:{C["dim2"]};padding:0 10px;')

        sub = QLabel(
            f'{OS.upper()}  ·  '
            f'{PKG_MANAGER.upper() if PKG_MANAGER else "CROSS-PLATFORM"}  ·  SMART DISK MANAGER'
        )
        sub.setStyleSheet(
            f'color:{C["dim"]};font-size:9px;letter-spacing:2px;font-family:{MONO};'
        )

        lay.addWidget(logo)
        lay.addWidget(dash)
        lay.addWidget(clean)
        lay.addWidget(ver)
        lay.addWidget(sep)
        lay.addWidget(sub)
        lay.addStretch()

        # Status indicators
        self._upd_lbl = QLabel('')
        self._upd_lbl.setStyleSheet(f'color:{C["yellow"]};font-size:9px;letter-spacing:1px;')

        dot_container = QFrame()
        dot_container.setStyleSheet('QFrame{background:transparent;border:none;}')
        dc_lay = QHBoxLayout(dot_container)
        dc_lay.setContentsMargins(0, 0, 0, 0)
        dc_lay.setSpacing(6)
        dot = QLabel('●')
        dot.setStyleSheet(f'color:{C["green"]};font-size:10px;')
        status = QLabel('ACTIVE')
        status.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;')
        dc_lay.addWidget(dot)
        dc_lay.addWidget(status)

        self.clock_lbl = QLabel('--:--:--')
        self.clock_lbl.setStyleSheet(
            f'color:{C["dim"]};font-size:10px;letter-spacing:2px;'
            f'font-family:{MONO};padding-left:16px;'
        )

        lay.addWidget(self._upd_lbl)
        lay.addSpacing(16)
        lay.addWidget(dot_container)
        lay.addWidget(self.clock_lbl)
        return h

    # ── SIDEBAR ──────────────────────────────────────────────
    def _build_sidebar(self):
        side = QFrame()
        side.setFixedWidth(200)
        side.setStyleSheet(
            f'QFrame{{background:{C["bg"]};border-right:1px solid {C["border2"]};}}'
        )
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(1)

        self.nav_btns = {}
        for pid, icon, label in self.NAV_ITEMS:
            btn = QPushButton(f'  {icon}  {label}')
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    color:{C['dim']}; background:transparent;
                    border:none; border-left:2px solid transparent;
                    text-align:left; padding:9px 16px;
                    font-family:{MONO}; font-size:10px; letter-spacing:1px;
                }}
                QPushButton:hover {{
                    color:{C['text']}; background:{C['cyan']}07;
                }}
                QPushButton:checked {{
                    color:{C['cyan']}; background:{C['cyan']}0d;
                    border-left:2px solid {C['cyan']};
                }}
            """)
            btn.clicked.connect(lambda _, p=pid: self._nav(p))
            self.nav_btns[pid] = btn
            lay.addWidget(btn)

        lay.addSpacing(14)
        lay.addWidget(_divider())
        lay.addSpacing(10)

        # Disk ring panel
        disk_panel = QFrame()
        disk_panel.setStyleSheet(
            f'QFrame{{background:{C["bg2"]};border:1px solid {C["border"]};'
            f'border-radius:3px;margin:0 12px;}}'
        )
        dp_lay = QVBoxLayout(disk_panel)
        dp_lay.setContentsMargins(10, 10, 10, 10)
        dp_lay.setSpacing(4)

        ring_row = QHBoxLayout()
        ring_row.addStretch()
        self.disk_ring = DiskRing()
        ring_row.addWidget(self.disk_ring)
        ring_row.addStretch()
        dp_lay.addLayout(ring_row)

        self.disk_detail_lbl = QLabel('— / —')
        self.disk_detail_lbl.setStyleSheet(
            f'color:{C["dim"]};font-size:9px;font-family:{MONO};'
        )
        self.disk_detail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dp_lay.addWidget(self.disk_detail_lbl)
        lay.addWidget(disk_panel)
        lay.addStretch()

        # Platform info
        info = platform_info()
        if IS_WINDOWS:
            import platform as _pf
            pi_text = (
                f'OS: Windows {_pf.release()}\n'
                f'VER: {_pf.version()[:16]}\n'
                f'PY: {info["python"]}'
            )
        else:
            pi_text = (
                f'OS: {info["os"]}\n'
                f'DISTRO: {info["distro"] or "n/a"}\n'
                f'PKG: {info["pkg_manager"] or "n/a"}\n'
                f'PY: {info["python"]}'
            )
        pi_lbl = QLabel(pi_text)
        pi_lbl.setStyleSheet(
            f'color:{C["dim"]};font-size:9px;letter-spacing:1px;'
            f'padding:0 14px;line-height:1.9;font-family:{MONO};'
        )
        lay.addWidget(pi_lbl)
        lay.addSpacing(6)

        # Status pills
        pills = []
        if IS_LINUX:
            pills.append(('POLKIT', C['green'] if HAS_POLKIT else C['red']))
            if HAS_FLATPAK: pills.append(('FLATPAK', C['cyan']))
            if HAS_DOCKER:  pills.append(('DOCKER', C['cyan']))
        elif IS_WINDOWS:
            pills.append(('ADMIN', C['green'] if is_windows_admin() else C['yellow']))

        if pills:
            pill_row = QHBoxLayout()
            pill_row.setContentsMargins(12, 0, 12, 0)
            pill_row.setSpacing(4)
            for label, col in pills:
                pl = QLabel(label)
                pl.setStyleSheet(
                    f'color:{col};font-size:8px;letter-spacing:1px;'
                    f'border:1px solid {col}44;padding:1px 5px;font-family:{MONO};'
                )
                pill_row.addWidget(pl)
            pill_row.addStretch()
            lay.addLayout(pill_row)
            lay.addSpacing(4)

        return side

    # ── MAIN STACK ───────────────────────────────────────────
    def _build_main(self):
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f'background:{C["bg"]};border:none;')
        # Order must match NAV_ITEMS
        self.stack.addWidget(self._build_dashboard())   # 0
        self.stack.addWidget(self._build_clean())        # 1
        self.stack.addWidget(self._build_scanner())      # 2
        self.stack.addWidget(self._build_uninstall())    # 3
        self.stack.addWidget(self._build_log())          # 4
        self.stack.addWidget(self._build_rollback())     # 5
        self.stack.addWidget(self._build_browser_turbo()) # 6
        return self.stack

    # ─────────────────────────────────────────────────────────
    # DASHBOARD
    # ─────────────────────────────────────────────────────────
    def _build_dashboard(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        # Header row
        hdr = QHBoxLayout()
        t = QLabel('SYSTEM OVERVIEW')
        t.setStyleSheet(
            f'color:{C["text2"]};font-size:11px;letter-spacing:4px;font-family:{MONO};'
        )
        ref_btn = _btn('↻  REFRESH', 'cyan', small=True)
        ref_btn.clicked.connect(self._refresh_now)
        hdr.addWidget(t); hdr.addStretch(); hdr.addWidget(ref_btn)
        lay.addLayout(hdr)

        # ── Health + One-Click row ─────────────────────
        top = QHBoxLayout(); top.setSpacing(10)

        # Health card
        hc = _card()
        hc.setMinimumWidth(140)
        hc.setMaximumWidth(200)
        hcl = QVBoxLayout(hc); hcl.setContentsMargins(14, 12, 14, 12); hcl.setSpacing(4)
        hcl.addWidget(_lbl_small('HEALTH'))
        self.health_lbl = QLabel('—')
        self.health_lbl.setStyleSheet(
            f'color:{C["green"]};font-size:32px;font-weight:700;font-family:{MONO};'
        )
        self.health_sub = QLabel('Calculating...')
        self.health_sub.setStyleSheet(f'color:{C["dim"]};font-size:9px;font-family:{MONO};')
        self.health_sub.setWordWrap(True)
        hcl.addWidget(self.health_lbl); hcl.addWidget(self.health_sub)
        top.addWidget(hc)

        # One-click card
        oc = _card()
        ocl = QVBoxLayout(oc); ocl.setContentsMargins(14, 12, 14, 12); ocl.setSpacing(6)
        ocl.addWidget(_lbl_small('ONE-CLICK OPTIMIZE'))
        oc_desc = QLabel(
            'Flush DNS  ·  Clear TEMP  ·  Drop cache  ·  TRIM SSD'
            if IS_WINDOWS else
            'Drop cache  ·  Tune swap  ·  TRIM SSD  ·  Clean journal'
        )
        oc_desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        oc_desc.setWordWrap(True)
        oc_row = QHBoxLayout()
        self.oneclick_btn = _btn('⚡  OPTIMIZE NOW', 'cyan')
        self.oneclick_btn.clicked.connect(self._one_click_fix)
        self.oneclick_log = QLabel('')
        self.oneclick_log.setStyleSheet(f'color:{C["green"]};font-size:9px;font-family:{MONO};')
        oc_row.addWidget(self.oneclick_btn); oc_row.addStretch()
        ocl.addWidget(oc_desc); ocl.addLayout(oc_row); ocl.addWidget(self.oneclick_log)
        top.addWidget(oc, 1)
        lay.addLayout(top)

        # ── Stat cards row ─────────────────────────────
        sc_row = QHBoxLayout(); sc_row.setSpacing(10)
        self._stat_cards = {}
        for sid, label, init, col in [
            ('cpu',  'CPU',         '—%',  'red'),
            ('ram',  'RAM',         '—%',  'cyan'),
            ('temp', 'TEMPERATURE', '—°C', 'green'),
            ('swap', 'SWAP',        '—',   'yellow'),
        ]:
            card_w = StatCard(label, init, col)
            self._stat_cards[sid] = card_w
            sc_row.addWidget(card_w)
        lay.addLayout(sc_row)

        # ── Charts row ─────────────────────────────────
        ch_row = QHBoxLayout(); ch_row.setSpacing(10)
        for label, sid, col in [('CPU %', 'cpu', C['red']), ('RAM %', 'ram', C['cyan'])]:
            cf = _card()
            cl = QVBoxLayout(cf); cl.setContentsMargins(12, 8, 12, 8); cl.setSpacing(4)
            hl = QLabel(label)
            hl.setStyleSheet(f'color:{C["dim"]};font-size:9px;letter-spacing:2px;font-family:{MONO};')
            chart = SparklineChart(color=col)
            self._charts[sid] = chart
            cl.addWidget(hl); cl.addWidget(chart)
            ch_row.addWidget(cf)
        lay.addLayout(ch_row)

        # ── Process + Disk tables in splits ────────────
        bot = QHBoxLayout(); bot.setSpacing(10)

        # Processes (left)
        proc_frame = _card()
        pfl = QVBoxLayout(proc_frame); pfl.setContentsMargins(12, 10, 12, 10); pfl.setSpacing(6)
        ph = QHBoxLayout()
        ph.addWidget(_lbl_small('TOP PROCESSES'))
        kill_btn = _btn('✕ KILL', 'red', small=True)
        kill_btn.clicked.connect(self._kill_selected_proc)
        ph.addStretch(); ph.addWidget(kill_btn)
        pfl.addLayout(ph)
        self.proc_table = QTableWidget(0, 4)
        self.proc_table.setHorizontalHeaderLabels(['PID', 'NAME', 'CPU %', 'MEM %'])
        self.proc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.proc_table.verticalHeader().setVisible(False)
        self.proc_table.setMinimumHeight(100)
        self.proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.proc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        pfl.addWidget(self.proc_table, 1)
        bot.addWidget(proc_frame, 3)

        # Disk (right)
        disk_frame = _card()
        dfl = QVBoxLayout(disk_frame); dfl.setContentsMargins(12, 10, 12, 10); dfl.setSpacing(6)
        dfl.addWidget(_lbl_small('DISK USAGE'))
        self.disk_table = QTableWidget(0, 4)
        self.disk_table.setHorizontalHeaderLabels(['MOUNT', 'USED', 'FREE', '%'])
        self.disk_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.disk_table.verticalHeader().setVisible(False)
        self.disk_table.setMinimumHeight(100)
        self.disk_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        dfl.addWidget(self.disk_table, 1)
        bot.addWidget(disk_frame, 2)

        lay.addLayout(bot, 1)
        return w

    # ─────────────────────────────────────────────────────────
    # CLEAN
    # ─────────────────────────────────────────────────────────
    def _build_clean(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(0)

        hdr = QHBoxLayout()
        t = QLabel('CLEAN TARGETS')
        t.setStyleSheet(f'color:{C["text2"]};font-size:11px;letter-spacing:4px;font-family:{MONO};')
        hdr.addWidget(t); hdr.addStretch()
        lay.addLayout(hdr)
        lay.addSpacing(12)

        # Target list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('border:none;background:transparent;')
        scroll.setMinimumHeight(180)
        scroll.setMaximumHeight(320)
        sw = QWidget()
        sl = QVBoxLayout(sw); sl.setContentsMargins(0, 0, 4, 0); sl.setSpacing(4)

        self.target_checks = {}
        targets = CLEANER.get_targets() if CLEANER else []
        for t in targets:
            row = QFrame()
            sc = C['green'] if t.safety == 'safe' else C['yellow'] if t.safety == 'caution' else C['red']
            row.setStyleSheet(
                f'QFrame{{background:{C["bg2"]};border:1px solid {C["border"]}; '
                f'border-left:2px solid {sc};border-radius:2px;}}'
                f'QFrame:hover{{background:{C["bg3"]};}}'
            )
            rl = QHBoxLayout(row); rl.setContentsMargins(12, 6, 12, 6); rl.setSpacing(10)

            chk = QCheckBox()
            chk.setChecked(t.safety == 'safe')
            if chk.isChecked():
                self.selected.add(t.id)
            chk.stateChanged.connect(lambda s, tid=t.id: self._toggle(tid, s))
            self.target_checks[t.id] = chk

            nc = QVBoxLayout(); nc.setSpacing(1)
            nm = QLabel(t.name + (' [ROOT]' if t.needs_root else ''))
            nm.setStyleSheet(f'color:{C["text"]};font-size:11px;font-family:{MONO};')
            dc = QLabel(t.desc)
            dc.setStyleSheet(f'color:{C["dim"]};font-size:9px;font-family:{MONO};')
            nc.addWidget(nm); nc.addWidget(dc)

            badge = QLabel(t.safety.upper())
            badge.setStyleSheet(
                f'color:{sc};font-size:8px;letter-spacing:1px;'
                f'border:1px solid {sc}33;padding:2px 7px;font-family:{MONO};'
            )
            rl.addWidget(chk); rl.addLayout(nc, 1); rl.addWidget(badge)
            sl.addWidget(row)

        sl.addStretch()
        scroll.setWidget(sw)
        lay.addWidget(scroll)
        lay.addSpacing(10)

        # Action bar
        ar = QHBoxLayout(); ar.setSpacing(6)
        dry_btn   = _btn('⬡  DRY-RUN',    'cyan')
        clean_btn = _btn('⚡  CLEAN NOW',  'red')
        all_btn   = _btn('☑ ALL',          small=True)
        none_btn  = _btn('☐ NONE',         small=True)
        dry_btn.clicked.connect(lambda: self._run_clean(dry=True))
        clean_btn.clicked.connect(self._confirm_clean)
        all_btn.clicked.connect(self._sel_all)
        none_btn.clicked.connect(self._sel_none)
        for b in [dry_btn, clean_btn, all_btn, none_btn]:
            ar.addWidget(b)
        ar.addStretch()
        lay.addLayout(ar)
        lay.addSpacing(8)

        self.clean_prog = QProgressBar()
        self.clean_prog.setTextVisible(False)
        self.clean_prog.setFixedHeight(2)
        self.clean_prog.setVisible(False)
        self.clean_prog_lbl = QLabel('')
        self.clean_prog_lbl.setStyleSheet(f'color:{C["dim"]};font-size:9px;font-family:{MONO};')
        self.clean_prog_lbl.setVisible(False)
        lay.addWidget(self.clean_prog)
        lay.addWidget(self.clean_prog_lbl)

        lay.addWidget(_lbl_small('OUTPUT'))
        self.clean_terminal = QTextEdit()
        self.clean_terminal.setReadOnly(True)
        self.clean_terminal.setPlaceholderText('  → Select targets and click DRY-RUN to preview...')
        lay.addWidget(self.clean_terminal, 1)
        return w

    # ─────────────────────────────────────────────────────────
    # SCANNER
    # ─────────────────────────────────────────────────────────
    def _build_scanner(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(0)

        hdr_row = QHBoxLayout()
        t = QLabel('SECURITY SCANNER')
        t.setStyleSheet(f'color:{C["text2"]};font-size:11px;letter-spacing:4px;font-family:{MONO};')
        hdr_row.addWidget(t); hdr_row.addStretch()
        lay.addLayout(hdr_row)
        lay.addSpacing(6)

        desc = QLabel(
            'malware  ·  reverse shells  ·  crypto miners  ·  SUID  ·  cron backdoors\n'
            'world-writable files  ·  suspicious autoruns  ·  hosts hijack  ·  network ports'
        )
        desc.setStyleSheet(f'color:{C["dim"]};font-size:9px;line-height:1.8;font-family:{MONO};')
        lay.addWidget(desc)
        lay.addSpacing(12)

        # Info strip
        info_strip = QFrame()
        info_strip.setStyleSheet(
            f'QFrame{{background:{C["cyan"]}08;border:none;border-left:2px solid {C["cyan"]}33;border-radius:0;}}'
        )
        isl = QHBoxLayout(info_strip); isl.setContentsMargins(12, 6, 12, 6)
        isl.addWidget(QLabel(
            f'<span style="color:{C["cyan"]}">⬡</span>'
            f'<span style="color:{C["dim"]};font-size:10px;">  Read-only scan — nothing deleted automatically</span>'
        ))
        lay.addWidget(info_strip)
        lay.addSpacing(2)

        warn_strip = QFrame()
        warn_strip.setStyleSheet(
            f'QFrame{{background:{C["yellow"]}06;border:none;border-left:2px solid {C["yellow"]}33;}}'
        )
        wsl = QHBoxLayout(warn_strip); wsl.setContentsMargins(12, 6, 12, 6)
        wsl.addWidget(QLabel(
            f'<span style="color:{C["yellow"]}">⚠</span>'
            f'<span style="color:{C["dim"]};font-size:10px;">  Review all findings before taking action</span>'
        ))
        lay.addWidget(warn_strip)
        lay.addSpacing(12)

        # Buttons
        br = QHBoxLayout(); br.setSpacing(8)
        self.scan_btn = _btn('⬡  RUN DEEP SCAN', 'cyan')
        self.scan_btn.clicked.connect(self._run_scanner)
        self.fix_btn = _btn('⚡ AUTO-FIX SELECTED', 'red', small=True)
        self.fix_btn.clicked.connect(self._fix_scan_results)
        self.fix_btn.setEnabled(False)
        br.addWidget(self.scan_btn); br.addWidget(self.fix_btn); br.addStretch()
        lay.addLayout(br)
        lay.addSpacing(10)

        lay.addWidget(_lbl_small('SCAN OUTPUT'))
        self.opt_terminal = QTextEdit()
        self.opt_terminal.setReadOnly(True)
        self.opt_terminal.setPlaceholderText('  → Click RUN DEEP SCAN to start...')
        lay.addWidget(self.opt_terminal, 1)

        lay.addWidget(_lbl_small('FINDINGS'))
        self.scan_table = QTableWidget(0, 4)
        self.scan_table.setHorizontalHeaderLabels(['SEV', 'CATEGORY', 'PATH', 'DETAIL'])
        self.scan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.scan_table.verticalHeader().setVisible(False)
        self.scan_table.setMinimumHeight(120)
        self.scan_table.setMaximumHeight(220)
        self.scan_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.scan_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.scan_table.itemSelectionChanged.connect(self._on_scan_select)
        lay.addWidget(self.scan_table)
        return w

    # ─────────────────────────────────────────────────────────
    # UNINSTALL
    # ─────────────────────────────────────────────────────────
    def _build_uninstall(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(0)

        hdr = QHBoxLayout()
        t = QLabel('APP UNINSTALLER')
        t.setStyleSheet(f'color:{C["text2"]};font-size:11px;letter-spacing:4px;font-family:{MONO};')
        ref = _btn('↻ REFRESH', 'cyan', small=True)
        ref.clicked.connect(self._load_uninstall)
        hdr.addWidget(t); hdr.addStretch(); hdr.addWidget(ref)
        lay.addLayout(hdr)
        lay.addSpacing(6)

        info = QLabel('Select one or more apps  →  Uninstall')
        info.setStyleSheet(f'color:{C["dim"]};font-size:10px;font-family:{MONO};')
        lay.addWidget(info)
        lay.addSpacing(8)

        self.uninstall_search = QLineEdit()
        self.uninstall_search.setPlaceholderText('Filter apps...')
        self.uninstall_search.textChanged.connect(self._filter_uninstall)
        lay.addWidget(self.uninstall_search)
        lay.addSpacing(6)

        self.uninstall_table = QTableWidget(0, 4)
        self.uninstall_table.setHorizontalHeaderLabels(['NAME', 'VERSION', 'SIZE', 'SOURCE'])
        self.uninstall_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.uninstall_table.verticalHeader().setVisible(False)
        self.uninstall_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.uninstall_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(self.uninstall_table, 1)

        btn_row = QHBoxLayout()
        un_btn = _btn('✕  UNINSTALL SELECTED', 'red')
        un_btn.clicked.connect(self._do_uninstall)
        btn_row.addWidget(un_btn); btn_row.addStretch()
        lay.addSpacing(8)
        lay.addLayout(btn_row)

        self.uninstall_log = QTextEdit()
        self.uninstall_log.setReadOnly(True)
        self.uninstall_log.setMinimumHeight(55)
        self.uninstall_log.setMaximumHeight(100)
        self.uninstall_log.setPlaceholderText('  → Select an app and click Uninstall...')
        lay.addWidget(self.uninstall_log)
        return w

    # ─────────────────────────────────────────────────────────
    # HISTORY LOG
    # ─────────────────────────────────────────────────────────
    def _build_log(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(0)

        hdr = QHBoxLayout()
        t = QLabel('HISTORY LOG')
        t.setStyleSheet(f'color:{C["text2"]};font-size:11px;letter-spacing:4px;font-family:{MONO};')
        clr = _btn('✕ CLEAR', 'red', small=True)
        clr.clicked.connect(self._clear_log)
        hdr.addWidget(t); hdr.addStretch(); hdr.addWidget(clr)
        lay.addLayout(hdr)
        lay.addSpacing(14)

        self.log_table = QTableWidget(0, 5)
        self.log_table.setHorizontalHeaderLabels(['TIME', 'DISK BEFORE', 'DISK AFTER', 'FREED', 'DETAIL'])
        self.log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        lay.addWidget(self.log_table, 1)
        return w

    # ─────────────────────────────────────────────────────────
    # ROLLBACK
    # ─────────────────────────────────────────────────────────
    def _build_rollback(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(0)

        hdr = QHBoxLayout()
        t = QLabel('ROLLBACK LIST')
        t.setStyleSheet(f'color:{C["text2"]};font-size:11px;letter-spacing:4px;font-family:{MONO};')
        clr = _btn('✕ CLEAR LIST', 'red', small=True)
        clr.clicked.connect(self._clear_rollback)
        hdr.addWidget(t); hdr.addStretch(); hdr.addWidget(clr)
        lay.addLayout(hdr)
        lay.addSpacing(6)

        info = QLabel('Cache files auto-rebuild. Package restores: use the command in the NOTE column.')
        info.setStyleSheet(f'color:{C["dim"]};font-size:9px;font-family:{MONO};')
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addSpacing(14)

        self.rollback_table = QTableWidget(0, 4)
        self.rollback_table.setHorizontalHeaderLabels(['TIME', 'TYPE', 'SIZE', 'PATH / NOTE'])
        self.rollback_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.rollback_table.verticalHeader().setVisible(False)
        self.rollback_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rollback_table.setAlternatingRowColors(True)
        lay.addWidget(self.rollback_table, 1)
        return w

    # ─────────────────────────────────────────────────────────
    # BROWSER TURBO
    # ─────────────────────────────────────────────────────────
    def _build_browser_turbo(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(0)

        hdr = QLabel('BROWSER TURBO')
        hdr.setStyleSheet(f'color:{C["text2"]};font-size:11px;letter-spacing:4px;font-family:{MONO};')
        outer.addWidget(hdr)
        outer.addSpacing(4)
        sub = QLabel('Speed up Chrome / Firefox / Edge — priority boost, database compact, cache wipe')
        sub.setStyleSheet(f'color:{C["dim"]};font-size:9px;font-family:{MONO};')
        outer.addWidget(sub)
        outer.addSpacing(14)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('border:none;background:transparent;')
        sw = QWidget()
        lay = QVBoxLayout(sw)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(8)

        # Priority Boost card
        pc = _card()
        pl = QVBoxLayout(pc); pl.setContentsMargins(14, 12, 14, 12); pl.setSpacing(8)
        pt = QLabel('⚡  PRIORITY BOOST')
        pt.setStyleSheet(f'color:{C["cyan"]};font-size:10px;letter-spacing:2px;font-family:{MONO};font-weight:700;')
        pd = QLabel('Raise Chrome / Firefox / Edge to HIGH CPU priority.\nBrowser tabs, video and scrolling feel instantly smoother.')
        pd.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); pd.setWordWrap(True)
        pr = QHBoxLayout()
        self._boost_btn   = _btn('⚡  BOOST BROWSERS', 'cyan')
        self._restore_btn = _btn('↺  RESTORE NORMAL',  'yellow')
        self._boost_btn.clicked.connect(self._browser_priority_boost)
        self._restore_btn.clicked.connect(self._browser_priority_restore)
        pr.addWidget(self._boost_btn); pr.addWidget(self._restore_btn); pr.addStretch()
        pl.addWidget(pt); pl.addWidget(pd); pl.addLayout(pr)
        lay.addWidget(pc)

        # SQLite Vacuum card
        vc = _card()
        vl = QVBoxLayout(vc); vl.setContentsMargins(14, 12, 14, 12); vl.setSpacing(8)
        vt2 = QLabel('⊕  DATABASE VACUUM')
        vt2.setStyleSheet(f'color:{C["green"]};font-size:10px;letter-spacing:2px;font-family:{MONO};font-weight:700;')
        vd = QLabel('Compact browser SQLite databases (history, cookies, bookmarks).\nReduces DB size 20–50% — browser launches faster after reboot.')
        vd.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); vd.setWordWrap(True)
        vr = QHBoxLayout(); vr.setSpacing(6)
        for name, cb in [
            ('Chrome',  lambda: self._vacuum_browser_async('chrome')),
            ('Firefox', lambda: self._vacuum_browser_async('firefox')),
            ('Edge',    lambda: self._vacuum_browser_async('edge')),
            ('All',     lambda: self._vacuum_browser_async('all')),
        ]:
            b = _btn(name, 'green', small=True); b.clicked.connect(cb); vr.addWidget(b)
        vr.addStretch()
        vl.addWidget(vt2); vl.addWidget(vd); vl.addLayout(vr)
        lay.addWidget(vc)

        # GPU Cache card
        gc = _card()
        gl = QVBoxLayout(gc); gl.setContentsMargins(14, 12, 14, 12); gl.setSpacing(8)
        gt = QLabel('◈  GPU CACHE CLEAR')
        gt.setStyleSheet(f'color:{C["purple"]};font-size:10px;letter-spacing:2px;font-family:{MONO};font-weight:700;')
        gd = QLabel('Wipe browser GPU / shader cache files.\nFixes 4K video stutter, WebGL glitches, and high VRAM usage.')
        gd.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); gd.setWordWrap(True)
        gpu_btn = _btn('◈  CLEAR GPU CACHE', 'purple')
        gpu_btn.clicked.connect(self._clear_gpu_cache)
        gl.addWidget(gt); gl.addWidget(gd); gl.addWidget(gpu_btn)
        lay.addWidget(gc)

        # Focus Modes card
        fc2 = _card()
        fl = QVBoxLayout(fc2); fl.setContentsMargins(14, 12, 14, 12); fl.setSpacing(8)
        ft = QLabel('⬡  FOCUS MODES')
        ft.setStyleSheet(f'color:{C["yellow"]};font-size:10px;letter-spacing:2px;font-family:{MONO};font-weight:700;')
        fd = QLabel('Freeze background bloat — give 100% resources to what matters now.')
        fd.setStyleSheet(f'color:{C["dim"]};font-size:9px;')
        mode_row = QHBoxLayout(); mode_row.setSpacing(8)

        game_c = _card(C['red'] + '33')
        gml = QVBoxLayout(game_c); gml.setContentsMargins(12, 10, 12, 10); gml.setSpacing(6)
        gml.addWidget(QLabel('<span style="color:#f03050;font-weight:700;letter-spacing:2px;">🎮 GAME MODE</span>'))
        gmd = QLabel('Suspends: OneDrive · Teams · Search\nPrint Spooler · Office updater')
        gmd.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); gmd.setWordWrap(True)
        self._game_btn = _btn('▶  ACTIVATE', 'red'); self._game_btn.setCheckable(True)
        self._game_btn.clicked.connect(self._toggle_game_mode)
        gml.addWidget(gmd); gml.addWidget(self._game_btn)
        mode_row.addWidget(game_c)

        eco_c = _card(C['green'] + '33')
        ecl = QVBoxLayout(eco_c); ecl.setContentsMargins(12, 10, 12, 10); ecl.setSpacing(6)
        ecl.addWidget(QLabel('<span style="color:#40d080;font-weight:700;letter-spacing:2px;">🌿 ECO MODE</span>'))
        ecd = QLabel('Lowers background task priority to IDLE.\nCPU stays cool, fan stays quiet.')
        ecd.setStyleSheet(f'color:{C["dim"]};font-size:9px;'); ecd.setWordWrap(True)
        self._eco_btn = _btn('▶  ACTIVATE', 'green'); self._eco_btn.setCheckable(True)
        self._eco_btn.clicked.connect(self._toggle_eco_mode)
        ecl.addWidget(ecd); ecl.addWidget(self._eco_btn)
        mode_row.addWidget(eco_c)

        fl.addWidget(ft); fl.addWidget(fd); fl.addLayout(mode_row)
        lay.addWidget(fc2)

        lay.addStretch()
        scroll.setWidget(sw)
        outer.addWidget(scroll, 1)
        outer.addSpacing(8)

        self._browser_log = QTextEdit()
        self._browser_log.setReadOnly(True)
        self._browser_log.setMinimumHeight(90)
        self._browser_log.setMaximumHeight(180)
        self._browser_log.setPlaceholderText('  → Output will appear here...')
        outer.addWidget(self._browser_log)
        return w

    # ─────────────────────────────────────────────────────────
    # NAVIGATION
    # ─────────────────────────────────────────────────────────
    def _nav(self, pid):
        pages = [item[0] for item in self.NAV_ITEMS]
        if pid not in pages:
            return
        self._active_tab = pid
        self.stack.setCurrentIndex(pages.index(pid))
        for k, b in self.nav_btns.items():
            b.setChecked(k == pid)
        # Pause heavy sysinfo polling when not on dashboard
        if hasattr(self, '_si_worker'):
            self._si_worker.paused = (pid != 'dashboard')
        if pid == 'log':       self._load_log()
        if pid == 'rollback':  self._load_rollback()
        if pid == 'uninstall': self._load_uninstall()
        if pid == 'clean' and IS_LINUX and not HAS_POLKIT_AGENT:
            self._show_polkit_warning()

    # ─────────────────────────────────────────────────────────
    # SYSINFO / REALTIME
    # ─────────────────────────────────────────────────────────
    def _start_sysinfo(self):
        self._si_worker = SysInfoWorker()
        self._si_worker.snapshot.connect(self._on_snapshot)
        self._si_worker.start()

    def _refresh_now(self):
        try:
            s = get_snapshot(interval=0.1)
            self._on_snapshot(s)
        except:
            pass

    def _on_snapshot(self, s):
        self._snap = s

        def color_pct(v):
            return 'red' if v > 85 else 'yellow' if v > 70 else 'cyan'

        self._stat_cards['cpu'].set_val(f'{s.cpu_percent:.0f}%', color_pct(s.cpu_percent))
        self._stat_cards['ram'].set_val(f'{s.ram_percent:.0f}%', color_pct(s.ram_percent))

        if s.swap_total == 0:
            self._stat_cards['swap'].set_val('N/A', 'dim')
        else:
            gb = s.swap_used / 1024 ** 3
            self._stat_cards['swap'].set_val(
                f'{gb:.1f} GB',
                'red' if s.swap_percent > 80 else 'yellow' if s.swap_percent > 40 else 'cyan'
            )

        if s.temp_max:
            tc = 'red' if s.temp_max > 85 else 'yellow' if s.temp_max > 75 else 'green'
            self._stat_cards['temp'].set_val(f'{s.temp_max:.0f}°C', tc)

        # Health score
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
        if s.swap_total > 0 and s.swap_percent > 60: score -= 10
        score = max(0, score)
        col = 'green' if score >= 80 else 'yellow' if score >= 50 else 'red'
        self.health_lbl.setText(f'{score}%')
        self.health_lbl.setStyleSheet(
            f'color:{C[col]};font-size:32px;font-weight:700;font-family:{MONO};'
        )
        self.health_sub.setText(' · '.join(issues) if issues else '✓ System healthy')
        self.health_sub.setStyleSheet(
            f'color:{C[col] if issues else C["green"]};font-size:9px;font-family:{MONO};'
        )

        # Charts
        self._charts['cpu'].push(s.cpu_percent)
        self._charts['ram'].push(s.ram_percent)

        # Disk ring
        if s.disks:
            d = s.disks[0]
            self.disk_ring.set_percent(d.percent)
            self.disk_detail_lbl.setText(f'{fmt_size(d.used)} / {fmt_size(d.total)}')

        # Process table
        self.proc_table.setRowCount(0)
        for proc in s.top_cpu_procs[:6]:
            row = self.proc_table.rowCount()
            self.proc_table.insertRow(row)
            vals = [str(proc.pid), proc.name, f'{proc.cpu:.1f}', f'{proc.mem:.1f}']
            for col_i, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col_i == 2 and float(val) > 15:
                    item.setForeground(QColor(C['red']))
                elif col_i == 2:
                    item.setForeground(QColor(C['dim']))
                self.proc_table.setItem(row, col_i, item)

        # Disk table
        self.disk_table.setRowCount(0)
        for disk in s.disks:
            row = self.disk_table.rowCount()
            self.disk_table.insertRow(row)
            col_pct = C['red'] if disk.percent > 90 else C['yellow'] if disk.percent > 75 else C['cyan']
            vals = [disk.path, fmt_size(disk.used), fmt_size(disk.free), f'{disk.percent:.0f}%']
            for i, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if i == 3:
                    item.setForeground(QColor(col_pct))
                self.disk_table.setItem(row, i, item)

    # ─────────────────────────────────────────────────────────
    # CLOCK
    # ─────────────────────────────────────────────────────────
    def _start_clock(self):
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(
            lambda: self.clock_lbl.setText(datetime.now().strftime('%H:%M:%S'))
        )
        self._clock_timer.start(1000)

    # ─────────────────────────────────────────────────────────
    # ONE-CLICK FIX
    # ─────────────────────────────────────────────────────────
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
                        ('drop-cache', 'Drop cache'),
                        ('swappiness', 'Swappiness→10'),
                        ('fstrim', 'SSD TRIM'),
                        ('journal', 'Journal'),
                        ('paccache', 'Paccache'),
                    ]:
                        import shutil as _sh
                        if action == 'paccache' and not _sh.which('paccache'):
                            continue
                        r = _sp.run(f'sudo -n {HELPER} {action}', shell=True,
                                    capture_output=True, text=True, timeout=60)
                        results.append((label, r.returncode == 0))
                elif IS_WINDOWS:
                    for cmd, label in [
                        ('ipconfig /flushdns', 'Flush DNS'),
                        ('del /q /f /s "%TEMP%\\*" 2>nul', 'Clear TEMP'),
                    ]:
                        r = _sp.run(cmd, shell=True, capture_output=True,
                                    text=True, timeout=30, creationflags=0x08000000)
                        results.append((label, r.returncode == 0))
                ok_count = sum(1 for _, ok in results if ok)
                summary = f'✓ {ok_count}/{len(results)}  ' + \
                          '  ·  '.join(f'{"✓" if ok else "~"}{n}' for n, ok in results)
                self_w.done.emit(summary, ok_count > 0)

        self._oneclick_worker = OneClickWorker()
        self._oneclick_worker.done.connect(self._on_oneclick_done)
        self._oneclick_worker.start()

    def _on_oneclick_done(self, summary, success):
        self.oneclick_btn.setEnabled(True)
        col = C['green'] if success else C['yellow']
        self.oneclick_log.setText(summary)
        self.oneclick_log.setStyleSheet(f'color:{col};font-size:9px;font-family:{MONO};')
        QTimer.singleShot(3000, self._refresh_now)

    # ─────────────────────────────────────────────────────────
    # KILL PROCESS (dashboard)
    # ─────────────────────────────────────────────────────────
    def _kill_selected_proc(self):
        rows = set(i.row() for i in self.proc_table.selectedItems())
        if not rows:
            return
        killed = []
        for row in rows:
            pid_item = self.proc_table.item(row, 0)
            name_item = self.proc_table.item(row, 1)
            if not pid_item:
                continue
            try:
                p = psutil.Process(int(pid_item.text()))
                p.terminate()
                killed.append(name_item.text() if name_item else str(pid_item.text()))
            except Exception as e:
                QMessageBox.warning(self, 'Kill failed', str(e))
        if killed:
            QMessageBox.information(self, 'Done', f'Terminated: {", ".join(killed)}')
            QTimer.singleShot(2000, self._refresh_now)

    # ─────────────────────────────────────────────────────────
    # CLEAN ACTIONS
    # ─────────────────────────────────────────────────────────
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
        self._disk_pct_before = self._snap.disks[0].percent if self._snap and self._snap.disks else 0
        self.clean_terminal.clear()
        self.clean_prog.setVisible(True)
        self.clean_prog_lbl.setVisible(True)
        self.worker = CleanWorker(list(self.selected), dry=dry)
        self.worker.log.connect(self._on_clean_log)
        self.worker.progress.connect(
            lambda p, l: (self.clean_prog.setValue(p), self.clean_prog_lbl.setText(l))
        )
        self.worker.done.connect(self._on_clean_done)
        self.worker.start()

    def _on_clean_log(self, msg, level):
        cols = {
            'ok': C['green'], 'dry': C['yellow'], 'err': C['red'],
            'head': C['cyan'], 'info': C['dim'], 'warn': C['yellow']
        }
        col = cols.get(level, C['text'])
        self.clean_terminal.append(f'<span style="color:{col};font-family:monospace;">{msg}</span>')
        self.clean_terminal.moveCursor(QTextCursor.MoveOperation.End)

    def _on_clean_done(self, result):
        self.clean_prog.setVisible(False)
        self.clean_prog_lbl.setVisible(False)
        if not result['dry']:
            try:
                snap_after = get_snapshot(interval=0.1)
                disk_after = snap_after.disks[0].percent if snap_after.disks else self._disk_pct_before
            except:
                disk_after = self._disk_pct_before
            session = {
                'time': datetime.now().isoformat(),
                'disk_before': self._disk_pct_before,
                'disk_after': round(disk_after, 1),
                'freed_bytes': result['freed'],
                'summary': result['summary'],
            }
            with open(LOG_FILE, 'a') as f:
                f.write(json.dumps(session) + '\n')
            if result['rollback']:
                with open(ROLLBACK_FILE, 'a') as f:
                    for e in result['rollback']:
                        f.write(json.dumps(e) + '\n')

    # ─────────────────────────────────────────────────────────
    # SCANNER
    # ─────────────────────────────────────────────────────────
    def _run_scanner(self):
        if hasattr(self, '_scan_running') and self._scan_running:
            return
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
        sev_col = {'critical': C['red'], 'high': C['yellow'], 'medium': C['cyan'], 'info': C['dim']}
        for r in results:
            row = self.scan_table.rowCount()
            self.scan_table.insertRow(row)
            for i, val in enumerate([r.severity.upper(), r.category, r.path, r.detail]):
                ti = QTableWidgetItem(val)
                if i == 0:
                    ti.setForeground(QColor(sev_col.get(r.severity, C['text'])))
                self.scan_table.setItem(row, i, ti)
            self.scan_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)
        fixable = [r for r in results if r.can_fix]
        if fixable:
            self.fix_btn.setEnabled(True)

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
        if not to_fix:
            return
        msg = QMessageBox(self)
        msg.setWindowTitle('Auto-Fix')
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(f'Apply {len(to_fix)} auto-fix(es)?\n\n' +
                    '\n'.join(f'• {r.path}: {r.detail[:60]}' for r in to_fix[:5]))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        import subprocess as _sp
        for r in to_fix:
            try:
                result = _sp.run(r.fix_cmd, shell=True, capture_output=True, text=True, timeout=10)
                self._on_opt_log(
                    f'  {"✓" if result.returncode == 0 else "✗"}  {r.path}: {r.fix_cmd}',
                    'ok' if result.returncode == 0 else 'err'
                )
            except Exception as e:
                self._on_opt_log(f'  ✗  {r.fix_cmd}: {e}', 'err')
        self._run_scanner()

    def _on_opt_log(self, msg, level):
        cols = {'ok': C['green'], 'warn': C['yellow'], 'err': C['red'], 'head': C['cyan'], 'info': C['dim']}
        col = cols.get(level, C['text'])
        self.opt_terminal.append(f'<span style="color:{col};font-family:monospace;">{msg}</span>')
        self.opt_terminal.moveCursor(QTextCursor.MoveOperation.End)

    # ─────────────────────────────────────────────────────────
    # UNINSTALL
    # ─────────────────────────────────────────────────────────
    def _load_uninstall(self):
        self.uninstall_table.setRowCount(0)
        self.uninstall_log.clear()
        self.uninstall_log.append(
            f'<span style="color:{C["cyan"]}">  ⟳  Scanning installed apps...</span>'
        )

        # Gemini fix: run get_installed_apps() on a background thread
        # so it never blocks the UI (wmic/winget can take 5-30s)
        class _UninstallWorker(QThread):
            finished = pyqtSignal(list)
            def run(self_w):
                try:
                    apps = get_installed_apps()
                    self_w.finished.emit(apps)
                except Exception as e:
                    self_w.finished.emit([])

        self._uninstall_worker = _UninstallWorker()
        self._uninstall_worker.finished.connect(self._on_uninstall_loaded)
        self._uninstall_worker.start()

    def _on_uninstall_loaded(self, apps):
        self._all_apps = apps
        self._populate_uninstall(apps)
        self.uninstall_log.clear()
        self.uninstall_log.append(
            f'<span style="color:{C["dim"]}">  Found {len(apps)} apps</span>'
        )

    def _populate_uninstall(self, apps):
        self.uninstall_table.setRowCount(0)
        for app in apps:
            row = self.uninstall_table.rowCount()
            self.uninstall_table.insertRow(row)
            sz = f'{app.size_mb:.1f} MB' if app.size_mb > 0 else '—'
            src_col = {
                'pacman': C['cyan'], 'apt': C['yellow'], 'dnf': C['green'],
                'flatpak': C['purple'], 'winget': C['cyan'],
                'registry': C['dim'], 'wmic': C['dim'],
            }.get(app.source, C['text'])
            src_lbl = 'winget' if app.source == 'winget' else \
                      'reg'    if app.source == 'registry' else app.source
            for i, val in enumerate([app.name, app.version, sz, src_lbl]):
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
        msg.setText(f'Uninstall {len(apps)} app(s)?\n' + '\n'.join(f'• {a.name}' for a in apps))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() != QMessageBox.StandardButton.Yes: return
        self.uninstall_log.clear()
        for app in apps:
            _col_map = {'ok': C['green'], 'err': C['red']}
            def _log_u(m, l, _cm=_col_map):
                col = _cm.get(l, C['dim'])
                self.uninstall_log.append(f'<span style="color:{col};">{m}</span>')
            uninstall_app(app, _log_u)
        QTimer.singleShot(1500, self._load_uninstall)

    # ─────────────────────────────────────────────────────────
    # LOG / ROLLBACK
    # ─────────────────────────────────────────────────────────
    def _load_log(self):
        self.log_table.setRowCount(0)
        if not LOG_FILE.exists(): return
        for line in reversed(LOG_FILE.read_text().strip().splitlines()):
            try:
                e = json.loads(line)
                row = self.log_table.rowCount()
                self.log_table.insertRow(row)
                t = datetime.fromisoformat(e['time']).strftime('%Y-%m-%d %H:%M')
                for i, val in enumerate([
                    t,
                    f'{e.get("disk_before", "?")}%',
                    f'{e.get("disk_after", "?")}%',
                    fmt_size(e.get('freed_bytes', 0)),
                    e.get('summary', '')
                ]):
                    item = QTableWidgetItem(val)
                    if i == 3: item.setForeground(QColor(C['green']))
                    self.log_table.setItem(row, i, item)
            except:
                pass

    def _clear_log(self):
        if QMessageBox.question(self, 'Clear', 'Delete all history?') == QMessageBox.StandardButton.Yes:
            LOG_FILE.unlink(missing_ok=True)
            self.log_table.setRowCount(0)

    def _load_rollback(self):
        self.rollback_table.setRowCount(0)
        if not ROLLBACK_FILE.exists(): return
        lines = ROLLBACK_FILE.read_text().strip().splitlines()
        for line in reversed(lines[:300]):
            try:
                e = json.loads(line)
                row = self.rollback_table.rowCount()
                self.rollback_table.insertRow(row)
                t = datetime.fromisoformat(e['time']).strftime('%m-%d %H:%M')
                for i, val in enumerate([
                    t, e.get('type', ''),
                    fmt_size(e.get('size', 0)),
                    e.get('note') or e.get('path', '')
                ]):
                    item = QTableWidgetItem(val)
                    if i == 1: item.setForeground(QColor(C['cyan']))
                    if i == 2: item.setForeground(QColor(C['yellow']))
                    self.rollback_table.setItem(row, i, item)
            except:
                pass

    def _clear_rollback(self):
        if QMessageBox.question(self, 'Clear', 'Delete rollback history?') == QMessageBox.StandardButton.Yes:
            ROLLBACK_FILE.unlink(missing_ok=True)
            self.rollback_table.setRowCount(0)

    # ─────────────────────────────────────────────────────────
    # BROWSER TURBO ACTIONS
    # ─────────────────────────────────────────────────────────
    def _blog(self, msg, col='text'):
        colors = {
            'ok': '#40d080', 'err': '#f03050', 'warn': '#f0c040',
            'head': '#00c8e0', 'text': C['text']
        }
        self._browser_log.append(f'<span style="color:{colors.get(col, C["text"])}">{msg}</span>')

    def _browser_priority_boost(self):
        import os
        BROWSERS = {
            'chrome', 'google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
            'firefox', 'firefox-bin', 'firefox-esr',
            'msedge', 'microsoft-edge', 'microsoft-edge-stable', 'edge',
            'brave', 'brave-browser', 'opera', 'vivaldi',
        }
        boosted = []
        for p in psutil.process_iter():
            try:
                with p.oneshot():
                    nm = p.name().lower().replace('.exe', '').replace(' ', '_')
                    if nm in BROWSERS or any(b in nm for b in ('chrome', 'firefox', 'edge', 'brave')):
                        if IS_WINDOWS: p.nice(psutil.HIGH_PRIORITY_CLASS)
                        else:          p.nice(-10)
                        boosted.append(p.name())
            except:
                pass
        if boosted:
            self._blog(f'⚡ Boosted {len(boosted)} browser process(es): {", ".join(set(boosted))}', 'ok')
            self._boost_btn.setText('✓  BOOSTED')
            self._boost_btn.setEnabled(False)
        else:
            self._blog('⚠ No browser processes found — launch your browser first', 'warn')

    def _browser_priority_restore(self):
        for p in psutil.process_iter():
            try:
                with p.oneshot():
                    nm = p.name().lower().replace('.exe', '')
                    if any(b in nm for b in ('chrome', 'firefox', 'edge', 'brave', 'opera', 'chromium')):
                        if IS_WINDOWS: p.nice(psutil.NORMAL_PRIORITY_CLASS)
                        else:          p.nice(0)
            except:
                pass
        self._blog('↺ Browser priority restored to Normal', 'warn')
        self._boost_btn.setText('⚡  BOOST BROWSERS')
        self._boost_btn.setEnabled(True)

    def _vacuum_browser_async(self, target):
        """Run vacuum on background thread so UI never freezes/crashes."""
        class _VacuumWorker(QThread):
            log_line = pyqtSignal(str, str)
            def __init__(self, fn, t):
                super().__init__(); self._fn = fn; self._t = t
            def run(self):
                self._fn(self._t)

        worker = _VacuumWorker(self._vacuum_browser, target)
        worker.finished.connect(lambda: None)
        self._vacuum_worker = worker  # keep reference
        worker.start()

    def _vacuum_browser(self, target):
        import sqlite3, glob, os
        self._blog(f'⟳ Vacuuming {target} databases...', 'head')

        def vacuum_db(path):
            try:
                size_before = os.path.getsize(path)
                conn = sqlite3.connect(path, timeout=2)
                conn.execute('PRAGMA locking_mode=EXCLUSIVE')
                conn.execute('VACUUM')
                conn.execute('PRAGMA locking_mode=NORMAL')
                conn.close()
                saved = size_before - os.path.getsize(path)
                if saved > 0:
                    self._blog(f'  ✓ {os.path.basename(path)} — saved {saved // 1024} KB', 'ok')
                return max(0, saved)
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower():
                    self._blog(f'  ⏭ {os.path.basename(path)}: locked (close browser first)', 'warn')
                return 0
            except Exception as e:
                self._blog(f'  ~ {os.path.basename(path)}: {e}', 'warn')
                return 0

        PROFILES = {}
        if IS_WINDOWS:
            local = os.environ.get('LOCALAPPDATA', '')
            roaming = os.environ.get('APPDATA', '')
            PROFILES = {
                'chrome':  [f'{local}/Google/Chrome/User Data/Default'],
                'firefox': glob.glob(f'{roaming}/Mozilla/Firefox/Profiles/*.default*'),
                'edge':    [f'{local}/Microsoft/Edge/User Data/Default'],
            }
        else:
            home = str(Path.home())
            PROFILES = {
                'chrome':  [f'{home}/.config/google-chrome/Default'],
                'firefox': glob.glob(f'{home}/.mozilla/firefox/*.default*') +
                           glob.glob(f'{home}/.mozilla/firefox/*.default-release*'),
                'edge':    [f'{home}/.config/microsoft-edge/Default'],
            }

        targets = list(PROFILES.keys()) if target == 'all' else [target]
        total = 0
        DB_NAMES = ['History', 'Cookies', 'Web Data', 'Favicons',
                    'places.sqlite', 'cookies.sqlite', 'formhistory.sqlite']
        for br in targets:
            for profile_dir in PROFILES.get(br, []):
                if not os.path.isdir(profile_dir): continue
                for db in DB_NAMES:
                    db_path = os.path.join(profile_dir, db)
                    if os.path.exists(db_path):
                        total += vacuum_db(db_path)
        self._blog(f'✓ Done — {total // 1024 // 1024} MB saved', 'ok')

    def _clear_gpu_cache(self):
        import shutil, os
        self._blog('⟳ Clearing GPU/shader cache...', 'head')
        cleared = 0
        GPU_PATHS = []
        if IS_WINDOWS:
            local = os.environ.get('LOCALAPPDATA', '')
            GPU_PATHS = [
                f'{local}/Google/Chrome/User Data/Default/GPUCache',
                f'{local}/Google/Chrome/User Data/Default/ShaderCache',
                f'{local}/Microsoft/Edge/User Data/Default/GPUCache',
                f'{local}/Microsoft/Edge/User Data/Default/ShaderCache',
            ]
        else:
            home = str(Path.home())
            GPU_PATHS = [
                f'{home}/.config/google-chrome/Default/GPUCache',
                f'{home}/.config/google-chrome/Default/ShaderCache',
                f'{home}/.cache/mesa_shader_cache',
                f'{home}/.cache/nvidia',
            ]
        for p in GPU_PATHS:
            if os.path.isdir(p):
                try:
                    sz = sum(f.stat().st_size for f in Path(p).rglob('*') if f.is_file())
                    shutil.rmtree(p, ignore_errors=True)
                    cleared += sz
                    self._blog(f'  ✓ {os.path.basename(p)} — {sz // 1024} KB', 'ok')
                except:
                    pass
        self._blog(f'✓ GPU cache cleared: {cleared // 1024 // 1024} MB freed', 'ok')

    _GAME_MODE_TARGETS_WIN = [
        'OneDrive', 'Dropbox', 'Teams', 'WINWORD', 'EXCEL', 'POWERPNT',
        'spoolsv', 'SearchIndexer', 'MsMpEng', 'SgrmBroker',
        'OfficeClickToRun', 'MicrosoftEdgeUpdate', 'GoogleUpdate',
    ]
    _GAME_MODE_TARGETS_LX = [
        'dropbox', 'onedrive', 'teams', 'libreoffice',
        'cups-browsed', 'tracker-miner', 'zeitgeist-daemon',
        'gvfs-udisks2', 'evolution-source', 'baloo_file',
    ]

    def _toggle_game_mode(self):
        if not hasattr(self, '_game_frozen_pids'): self._game_frozen_pids = []
        active = self._game_btn.isChecked()
        targets = self._GAME_MODE_TARGETS_WIN if IS_WINDOWS else self._GAME_MODE_TARGETS_LX
        if active:
            self._game_btn.setText('■  ACTIVE — CLICK TO RESTORE')
            self._eco_btn.setEnabled(False)
            frozen = []
            for p in psutil.process_iter():
                try:
                    with p.oneshot():
                        nm = p.name().replace('.exe', '')
                        if any(t.lower() in nm.lower() for t in targets):
                            p.suspend(); frozen.append(p.pid)
                            self._blog(f'  ❄ Froze: {p.name()} (PID {p.pid})', 'warn')
                except:
                    pass
            self._game_frozen_pids = frozen
            self._blog(f'🎮 GAME MODE ON — {len(frozen)} background processes frozen', 'ok')
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
        import os
        if not hasattr(self, '_eco_saved'): self._eco_saved = {}
        active = self._eco_btn.isChecked()
        SKIP_NAMES = {
            'python', 'python3', 'cyberclean', 'systemd', 'kwin', 'hyprland',
            'plasmashell', 'gnome-shell', 'Xorg', 'Xwayland', 'pipewire',
        }
        SKIP_CONTAINS = ('chrome', 'firefox', 'edge', 'brave', 'chromium')
        if active:
            self._eco_btn.setText('■  ACTIVE — CLICK TO RESTORE')
            self._game_btn.setEnabled(False)
            saved = {}
            for p in psutil.process_iter():
                try:
                    with p.oneshot():
                        nm = p.name().lower().replace('.exe', '')
                        if nm in SKIP_NAMES: continue
                        if any(s in nm for s in SKIP_CONTAINS): continue
                        cur_nice = p.nice()
                        if IS_WINDOWS:
                            if cur_nice not in (psutil.IDLE_PRIORITY_CLASS, psutil.BELOW_NORMAL_PRIORITY_CLASS):
                                saved[p.pid] = cur_nice
                                try: p.nice(psutil.IDLE_PRIORITY_CLASS)
                                except: pass
                        else:
                            if cur_nice <= 5:
                                saved[p.pid] = cur_nice
                                try: p.nice(15)
                                except: pass
                except: pass
            self._eco_saved = saved
            self._blog(f'🌿 ECO MODE ON — {len(saved)} processes set to low priority', 'ok')
        else:
            self._eco_btn.setText('▶  ACTIVATE')
            self._game_btn.setEnabled(True)
            snapshot = dict(self._eco_saved)
            self._eco_saved = {}
            restored = 0
            for pid, orig_nice in snapshot.items():
                try:
                    psutil.Process(pid).nice(orig_nice); restored += 1
                except: pass
            self._blog(f'↺ ECO MODE OFF — {restored} processes restored', 'ok')

    # ─────────────────────────────────────────────────────────
    # POLKIT WARNING
    # ─────────────────────────────────────────────────────────
    def _show_polkit_warning(self):
        if hasattr(self, '_polkit_warned'): return
        self._polkit_warned = True
        if not HAS_POLKIT:
            msg = QMessageBox(self)
            msg.setWindowTitle('Setup Required')
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(
                'Polkit not configured. Root-level cleaning needs setup.\n'
                'Option 1: bash ~/CyberClean/install.sh\n'
                'Option 2: sudo python3 ~/CyberClean/main.py'
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.setStyleSheet(f'background:{C["bg2"]};color:{C["text"]};font-family:monospace;')
            msg.exec()

    # ─────────────────────────────────────────────────────────
    # SYSTEM TRAY
    # ─────────────────────────────────────────────────────────
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        # Use real logo — works both in dev and PyInstaller
        _base = getattr(sys, '_MEIPASS', Path(__file__).parent)
        _icon_file = Path(_base) / 'assets' / 'logo.png'
        if _icon_file.exists():
            self.tray.setIcon(QIcon(str(_icon_file)))
        else:
            px = QPixmap(16, 16); px.fill(QColor(C['cyan']))
            self.tray.setIcon(QIcon(px))
        self.tray.setToolTip('CyberClean v2.0')

        menu = QMenu()
        menu.setStyleSheet(
            f'QMenu{{background:{C["bg2"]};color:{C["text"]};border:1px solid {C["border"]};'
            f'font-family:monospace;font-size:11px;padding:4px;}}'
            f'QMenu::item{{padding:6px 20px;}}'
            f'QMenu::item:selected{{background:{C["cyan"]}22;color:{C["cyan"]};}}'
        )
        show_act  = QAction('◈  Show CyberClean', self)
        show_act.triggered.connect(self._show_from_tray)
        clean_act = QAction('⚡  Quick Clean', self)
        clean_act.triggered.connect(lambda: (self._show_from_tray(), self._nav('clean')))
        quit_act  = QAction('✕  Quit', self)

        def _quit():
            self._shutdown()
            QApplication.quit()
        quit_act.triggered.connect(_quit)

        menu.addAction(show_act)
        menu.addSeparator()
        menu.addAction(clean_act)
        menu.addSeparator()
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def closeEvent(self, event):
        if hasattr(self, 'tray') and self.tray.isVisible():
            self.hide()
            self.tray.showMessage('CyberClean', 'Running in background. Auto-clean every 6h.',
                                  QSystemTrayIcon.MessageIcon.Information, 2000)
            # Pause all polling — zero CPU while hidden
            if hasattr(self, '_si_worker'):
                self._si_worker.paused = True
            if hasattr(self, '_clock_timer'):
                self._clock_timer.stop()
            event.ignore()
        else:
            self._shutdown()
            event.accept()

    def _show_from_tray(self):
        self.show(); self.raise_(); self.activateWindow()
        # Resume workers
        if hasattr(self, '_si_worker'):
            self._si_worker.paused = (self.stack.currentIndex() != 0)
        if hasattr(self, '_clock_timer'):
            self._clock_timer.start(1000)

    def _shutdown(self):
        """Clean shutdown — stop all background threads and timers."""
        if hasattr(self, '_si_worker'):
            self._si_worker.stop()
            self._si_worker.quit()
            self._si_worker.wait(2000)
        if hasattr(self, '_clock_timer'):
            self._clock_timer.stop()
        if hasattr(self, '_auto_clean_timer'):
            self._auto_clean_timer.stop()
        if getattr(self, '_auto_worker', None) and self._auto_worker.isRunning():
            self._auto_worker.quit()
            self._auto_worker.wait(1000)

    # ─────────────────────────────────────────────────────────
    # AUTO-CLEAN SCHEDULER (every 6 hours while in tray)
    # ─────────────────────────────────────────────────────────
    def _start_auto_clean(self):
        """Start the 6-hour background auto-clean timer."""
        self._auto_clean_timer = QTimer(self)
        self._auto_clean_timer.timeout.connect(self._run_auto_clean)
        self._auto_clean_timer.start(6 * 60 * 60 * 1000)  # 6 hours in ms

    def _run_auto_clean(self):
        """Called by 6h timer — only runs when app is hidden in tray."""
        if self.isVisible():
            return   # user has app open, skip silent auto-clean
        self._do_background_clean(notify=True)

    def _do_background_clean(self, notify=True):
        """Run safe targets in a background thread. Works hidden or visible."""
        safe_targets = [
            t.id for t in CLEANER.get_targets()
            if t.safety == 'safe'
        ]
        if not safe_targets:
            return

        # Prevent double-run if already cleaning
        if getattr(self, '_auto_worker', None) and self._auto_worker.isRunning():
            if hasattr(self, 'tray'):
                self.tray.showMessage('CyberClean',
                                      'Already cleaning, please wait...',
                                      QSystemTrayIcon.MessageIcon.Warning, 2000)
            return

        class _AutoCleanWorker(QThread):
            done = pyqtSignal(int, int)

            def run(self_w):
                total_freed = 0
                cleaned = 0
                for tid in safe_targets:
                    try:
                        result = CLEANER.clean(tid, dry=False)
                        total_freed += result.freed_bytes
                        cleaned += 1
                    except:
                        pass
                self_w.done.emit(total_freed, cleaned)

        self._auto_worker = _AutoCleanWorker()
        self._auto_worker.done.connect(
            lambda freed, n: self._on_auto_clean_done(freed, n, notify)
        )
        self._auto_worker.start()

    def _on_auto_clean_done(self, freed_bytes, num_targets, notify=True):
        """Show tray notification when background clean finishes."""
        if hasattr(self, 'tray'):
            self.tray.setToolTip('CyberClean v2.0')   # restore tooltip
        if notify and hasattr(self, 'tray'):
            if freed_bytes > 0:
                self.tray.showMessage(
                    'CyberClean — Clean Done',
                    f'✓ Freed {fmt_size(freed_bytes)} across {num_targets} targets',
                    QSystemTrayIcon.MessageIcon.Information, 4000,
                )
            else:
                self.tray.showMessage(
                    'CyberClean — Clean Done',
                    '✓ Nothing to clean — system is already tidy',
                    QSystemTrayIcon.MessageIcon.Information, 3000,
                )

    # ─────────────────────────────────────────────────────────
    # AUTO UPDATE
    # ─────────────────────────────────────────────────────────
    GITHUB_LATEST = 'https://api.github.com/repos/vuphitung/CyberClean/releases/latest'
    CURRENT_VER   = '2.0.0'

    def _check_update_async(self):
        threading.Thread(target=self._fetch_update, daemon=True).start()

    def _fetch_update(self):
        try:
            req  = urlopen(self.GITHUB_LATEST, timeout=5)
            data = json.loads(req.read().decode())
            latest = data.get('tag_name', '').lstrip('v')
            if latest and latest != self.CURRENT_VER:
                self._pending_update = latest
                QTimer.singleShot(100, self._show_update_notice)
        except:
            pass

    def _show_update_notice(self):
        ver = getattr(self, '_pending_update', None)
        if not ver: return
        self._upd_lbl.setText(f'⬆ v{ver} AVAILABLE')
        if hasattr(self, 'tray'):
            self.tray.showMessage('CyberClean — Update Available',
                                  f'v{ver} is available! github.com/vuphitung/CyberClean',
                                  QSystemTrayIcon.MessageIcon.Information, 5000)


# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # ── Single instance lock ──────────────────────────────
    import socket as _sock
    _lock = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    try:
        _lock.bind(('127.0.0.1', 47291))  # unique port = lock
    except OSError:
        # Already running — bring existing window to front via tray
        app = QApplication(sys.argv)
        QMessageBox.information(None, 'CyberClean',
            'CyberClean is already running.\nCheck the system tray.')
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setApplicationName('CyberClean')
    app.setApplicationVersion('2.0')

    # ── Resource path helper (works both dev and PyInstaller .exe) ──
    def _res(rel):
        base = getattr(sys, '_MEIPASS', Path(__file__).parent)
        return str(Path(base) / rel)

    # Set app icon from bundled assets
    _icon_path = _res('assets/logo.ico')
    if Path(_icon_path).exists():
        app.setWindowIcon(QIcon(_icon_path))

    win = CyberCleanApp()

    # Fix tray icon to use real logo
    if hasattr(win, 'tray'):
        _tray_icon = _res('assets/logo.png')
        if Path(_tray_icon).exists():
            win.tray.setIcon(QIcon(_tray_icon))

    win.show()
    sys.exit(app.exec())
