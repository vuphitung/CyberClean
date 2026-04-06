"""
CyberClean — Main GUI
All nav icons replaced with QPainter-drawn code icons.
No SVG file dependency — icons always render sharp at any DPI.
Sidebar redesigned: wider, icon+label layout with active indicator bar.
Header: hex logo drawn in code, tighter spacing.
"""
import sys, os, json, time, platform, threading

# ── Version (single source of truth: version.py) ──────────────
try:
    from version import __version__, version_is_newer
except ImportError:
    __version__ = "0.0.0"

    def version_is_newer(remote: str, current: str) -> bool:
        return remote != current
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError
os.environ["QT_LOGGING_RULES"] = "qt.qpa.wayland*=false"
# GIO: skip GVFS remote volume monitors — avoids noisy DBus errors when related
# user systemd units are masked (common on minimal/Zen setups). Local disks still work.
os.environ.setdefault("GIO_USE_VFS", "local")
# FIX: Disable Qt thread watchdog that falsely fires on Python 3.14
# when time.sleep() releases GIL in a QThread (seen on Arch+KDE+Wayland).
# This does NOT disable real crash detection — only the GIL-release false alarm.
os.environ.setdefault("QT_FATAL_WARNINGS", "0")
os.environ.setdefault("PYTHONFAULTHANDLER", "1")

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
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPointF, QRectF, QSize, QSettings, QUrl
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QTextCursor, QPainter, QBrush,
    QPen, QLinearGradient, QIcon, QAction, QPolygonF, QPixmap,
    QTransform, QDesktopServices,
)

# ── SVG kept for compatibility but never used for nav icons ──
try:
    from PyQt6.QtSvg import QSvgRenderer
    HAS_SVG = True
except ImportError:
    HAS_SVG = False

sys.path.insert(0, str(Path(__file__).parent))
from core.os_detect  import (IS_LINUX, IS_WINDOWS, IS_WSL, PKG_MANAGER, platform_info,
                                HAS_POLKIT, HAS_POLKIT_AGENT, HAS_FLATPAK, HAS_DOCKER,
                                HAS_SEND2TRASH, request_windows_admin, is_windows_admin)
from utils.sysinfo   import get_snapshot, get_startup_items, toggle_startup_linux, fmt_size
from core.scanner    import SecurityScanner
from core.uninstaller import get_installed_apps, uninstall_app, InstalledApp
from utils.i18n import _t, T, SUPPORTED_LANGS
from utils.updater import UpdateDialog, UpdateBadge
from core.analyzer import get_network_processes, IdleScheduler
from core.booster import (free_ram, memory_tune, memory_tune_restore,
                          clear_disk_cache, kill_bloat,
                          game_mode_on, game_mode_off, eco_mode_on, eco_mode_off,
                          smart_boost_on, smart_boost_off, detect_pc_tier)

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

# ── CRITICAL #3 FIX: block unsupported OS before any CLEANER.* call ──────────
# macOS / BSD / etc. — CLEANER = None, show a clear message and exit
# instead of crashing later with AttributeError deep inside the app.
if CLEANER is None:
    import platform as _plat
    _app_tmp = QApplication.instance() or QApplication(sys.argv)
    _msg = QMessageBox()
    _msg.setWindowTitle('CyberClean — Unsupported OS')
    _msg.setIcon(QMessageBox.Icon.Critical)
    _msg.setText(
        f'CyberClean does not support {_plat.system()} yet.\n\n'
        'Supported platforms: Windows 10/11 · Linux (all major distros)\n\n'
        'macOS support is planned — track progress:\n'
        'https://github.com/vuphitung/CyberClean/issues'
    )
    _msg.exec()
    sys.exit(1)

# ── CRITICAL #2 FIX: guard LOG_DIR creation — crash if not writeable ─────────
# Environments like containers, chroot, or read-only /home will raise OSError.
# Silently fall back to /tmp so the app still launches; logs just won't persist.
LOG_DIR       = Path.home() / '.local/share/cyber-clean'
LOG_FILE      = LOG_DIR / 'history.jsonl'
ROLLBACK_FILE = LOG_DIR / 'rollback.jsonl'
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    import tempfile as _tmp
    LOG_DIR       = Path(_tmp.gettempdir()) / 'cyber-clean'
    LOG_FILE      = LOG_DIR / 'history.jsonl'
    ROLLBACK_FILE = LOG_DIR / 'rollback.jsonl'
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass   # absolute last resort — app runs but no logging
OS = platform.system()

# ═════════════════════════════════════════════════════════════
# DESIGN TOKENS
# ═════════════════════════════════════════════════════════════
C = {
    'bg':      '#050a0f',
    'bg2':     '#09121a',
    'bg3':     '#0d1a26',
    'bg4':     '#112032',
    'cyan':    '#00e5ff',
    'cyan2':   '#00bcd4',
    'cyan_dim':'#004d5c',
    'red':     '#ff3d5a',
    'red_dim': '#3d0010',
    'yellow':  '#ffd740',
    'yel_dim': '#3d2d00',
    'green':   '#00e676',
    'grn_dim': '#00280f',
    'purple':  '#d050ff',
    'text':    '#def0f8',
    'text2':   '#7eb8cc',
    'text3':   '#3d6678',
    'dim':     '#2a4a5a',
    'border':  '#0a1e2d',
    'border2': '#0f2a3d',
    'border3': '#1a3a52',
    'accent':  '#00e5ff',
}

MONO    = "'Cascadia Code','JetBrains Mono','Fira Code','Consolas','Share Tech Mono',monospace"
DISPLAY = "'Orbitron','Rajdhani','Oxanium','Exo 2','Share Tech Mono',monospace"


# ═════════════════════════════════════════════════════════════
# PURE-CODE NAV ICONS — drawn with QPainter, zero file deps
# Each function returns a QIcon by painting onto a QPixmap.
# ═════════════════════════════════════════════════════════════

def _make_icon(draw_fn, size=20, color='#00e5ff') -> QIcon:
    """
    Generic icon factory.
    draw_fn(p: QPainter, col: QColor, s: int) — draws into a size×size canvas.
    Returns a QIcon with transparent background.
    """
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(color)
    draw_fn(p, col, size)
    p.end()
    return QIcon(pix)


def _icon_dashboard(p: QPainter, col: QColor, s: int):
    """Four equal squares — dashboard/grid layout."""
    pen = QPen(col, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    g = s * 0.12   # gap
    h = (s - 3 * g) / 2
    # top-left, top-right, bottom-left, bottom-right
    for rx, ry in [(g, g), (g*2+h, g), (g, g*2+h), (g*2+h, g*2+h)]:
        p.drawRoundedRect(QRectF(rx, ry, h, h), 1.5, 1.5)


def _icon_clean(p: QPainter, col: QColor, s: int):
    """Broom/sweep — angled handle + bristle fan."""
    pen = QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    # Handle — diagonal line top-right to center
    p.drawLine(QPointF(s*0.72, s*0.08), QPointF(s*0.38, s*0.58))
    # Bristle head — 5 lines fanning down-left
    cx, cy = s*0.32, s*0.65
    offsets = [(-0.14, 0.22), (-0.07, 0.24), (0.0, 0.25), (0.07, 0.24), (0.14, 0.22)]
    for dx, dy in offsets:
        p.drawLine(QPointF(cx, cy), QPointF(cx + dx*s, cy + dy*s))
    # Horizontal base line under bristles
    p.drawLine(QPointF(s*0.12, s*0.62), QPointF(s*0.52, s*0.62))


def _icon_scanner(p: QPainter, col: QColor, s: int):
    """Magnifying glass with a crosshair inside."""
    pen = QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    cx, cy, r = s*0.42, s*0.42, s*0.26
    p.drawEllipse(QPointF(cx, cy), r, r)
    # Handle
    p.drawLine(QPointF(cx + r*0.72, cy + r*0.72), QPointF(s*0.92, s*0.92))
    # Crosshair inside lens
    pen2 = QPen(col, 0.9)
    pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen2)
    p.drawLine(QPointF(cx, cy - r*0.55), QPointF(cx, cy + r*0.55))
    p.drawLine(QPointF(cx - r*0.55, cy), QPointF(cx + r*0.55, cy))


def _icon_uninstall(p: QPainter, col: QColor, s: int):
    """Trash bin — body, lid, three vertical lines inside."""
    pen = QPen(col, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    lx, rx = s*0.22, s*0.78
    ty, by  = s*0.30, s*0.88
    # Body
    p.drawRoundedRect(QRectF(lx, ty, rx-lx, by-ty), 2, 2)
    # Lid
    p.drawLine(QPointF(s*0.14, s*0.28), QPointF(s*0.86, s*0.28))
    # Handle on lid
    p.drawLine(QPointF(s*0.38, s*0.18), QPointF(s*0.62, s*0.18))
    p.drawArc(QRectF(s*0.33, s*0.18, s*0.34, s*0.12), 0, 180*16)
    # Three vertical stripes inside body
    for xf in [0.36, 0.50, 0.64]:
        p.drawLine(QPointF(s*xf, s*0.40), QPointF(s*xf, s*0.78))


def _icon_history(p: QPainter, col: QColor, s: int):
    """Clock face — circle, hour/minute hands, notch at 12."""
    pen = QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    cx, cy, r = s*0.50, s*0.50, s*0.36
    p.drawEllipse(QPointF(cx, cy), r, r)
    # Hour hand (pointing ~10 o'clock)
    p.drawLine(QPointF(cx, cy), QPointF(cx - r*0.45, cy - r*0.55))
    # Minute hand (pointing ~12 o'clock)
    p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r*0.72))
    # Tick at 12
    p.drawLine(QPointF(cx, cy - r*0.85), QPointF(cx, cy - r*1.0))


def _icon_rollback(p: QPainter, col: QColor, s: int):
    """Counter-clockwise circular arrow — undo/rollback."""
    pen = QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    cx, cy, r = s*0.50, s*0.52, s*0.30
    # Arc: 210° arc counter-clockwise from ~right
    p.drawArc(QRectF(cx-r, cy-r, r*2, r*2), 30*16, 270*16)
    # Arrowhead at end of arc (top-left area)
    import math
    angle = math.radians(30)   # start of arc
    ax = cx + r * math.cos(angle)
    ay = cy - r * math.sin(angle)
    # Two short lines forming arrowhead
    p.drawLine(QPointF(ax, ay), QPointF(ax - s*0.08, ay - s*0.14))
    p.drawLine(QPointF(ax, ay), QPointF(ax + s*0.14, ay - s*0.05))


def _icon_booster(p: QPainter, col: QColor, s: int):
    """Lightning bolt — performance / power."""
    pen = QPen(col, 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    # Fill the bolt solid
    accent = QColor(col)
    accent.setAlphaF(0.18)
    p.setBrush(QBrush(accent))
    pts = QPolygonF([
        QPointF(s*0.62, s*0.06),
        QPointF(s*0.32, s*0.50),
        QPointF(s*0.52, s*0.50),
        QPointF(s*0.38, s*0.94),
        QPointF(s*0.68, s*0.46),
        QPointF(s*0.48, s*0.46),
    ])
    p.drawPolygon(pts)


# Map icon name → draw function
_ICON_FN = {
    'dashboard': _icon_dashboard,
    'smart_clean': _icon_clean,
    'scanner':   _icon_scanner,
    'uninstaller': _icon_uninstall,
    'history':   _icon_history,   # used for 'log' tab
    'rollback':  _icon_rollback,
    'booster':   _icon_booster,
}

def _nav_icon(name: str, active=False, size=18) -> QIcon:
    """Return a code-drawn nav icon. Active = full cyan, inactive = dimmer."""
    fn = _ICON_FN.get(name, _icon_dashboard)
    color = C['cyan'] if active else C['text3']
    return _make_icon(fn, size=size, color=color)


# ═════════════════════════════════════════════════════════════
# SPARKLINE CHART
# ═════════════════════════════════════════════════════════════
class SparklineChart(QWidget):
    def __init__(self, color='#00e5ff', max_points=50, parent=None):
        super().__init__(parent)
        self.color   = QColor(color)
        self.max_pts = max_points
        self.data    = []
        self.setMinimumHeight(56)
        self.setMaximumHeight(56)
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
        pad  = 3

        grid_pen = QPen(QColor(C['border2']))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        for pct in [25, 50, 75]:
            y = h - pad - (pct / 100) * (h - pad * 2)
            p.drawLine(0, int(y), w, int(y))

        pts = []
        for i, v in enumerate(self.data):
            x = pad + (i / (self.max_pts - 1)) * (w - pad * 2)
            y = h - pad - (v / 100.0) * (h - pad * 2)
            pts.append(QPointF(x, y))

        fill_pts = [QPointF(pts[0].x(), h)] + pts + [QPointF(pts[-1].x(), h)]
        grad = QLinearGradient(0, 0, 0, h)
        fc = QColor(self.color); fc.setAlphaF(0.22)
        fc2 = QColor(self.color); fc2.setAlphaF(0.01)
        grad.setColorAt(0, fc); grad.setColorAt(1, fc2)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF(fill_pts))

        lp = QPen(self.color); lp.setWidth(2)
        lp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(lp)
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])

        if pts:
            halo_col = QColor(self.color); halo_col.setAlphaF(0.18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(halo_col))
            p.drawEllipse(pts[-1], 6, 6)
            p.setBrush(QBrush(self.color))
            p.drawEllipse(pts[-1], 3, 3)
        p.end()


# ═════════════════════════════════════════════════════════════
# DISK RING
# ═════════════════════════════════════════════════════════════
class DiskRing(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.percent = 0.0
        self.setFixedSize(88, 88)

    def set_percent(self, v):
        self.percent = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect  = QRectF(9, 9, 70, 70)
        color = C['red'] if self.percent > 90 else C['yellow'] if self.percent > 75 else C['cyan']

        bg_pen = QPen(QColor(C['bg3'])); bg_pen.setWidth(8)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(bg_pen); p.drawArc(rect, 0, 360 * 16)

        inner_pen = QPen(QColor(C['border2'])); inner_pen.setWidth(1)
        p.setPen(inner_pen); p.drawArc(QRectF(13, 13, 62, 62), 0, 360 * 16)

        fill_pen = QPen(QColor(color)); fill_pen.setWidth(8)
        fill_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(fill_pen)
        span = int((self.percent / 100.0) * 360 * 16)
        p.drawArc(rect, 90 * 16, -span)

        p.setPen(QPen(QColor(color)))
        p.setFont(QFont('Cascadia Code' if IS_WINDOWS else 'Share Tech Mono', 13, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 88, 88), Qt.AlignmentFlag.AlignCenter, f'{int(self.percent)}%')
        p.end()


# ═════════════════════════════════════════════════════════════
# HEX LOGO WIDGET — drawn entirely in QPainter, no file needed
# ═════════════════════════════════════════════════════════════
class HexLogoWidget(QWidget):
    """Draws a hexagon outline + inner hex + 'CL' text — pure QPainter."""
    def __init__(self, size=32, parent=None):
        super().__init__(parent)
        self.s = size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, s = self.s / 2, self.s / 2, self.s / 2 - 2

        def hex_pts(cx, cy, r):
            return [QPointF(cx + r * math.cos(math.radians(60*i - 30)),
                            cy + r * math.sin(math.radians(60*i - 30)))
                    for i in range(6)]

        # Outer hex
        outer_col = QColor(C['cyan'])
        outer_col.setAlphaF(0.9)
        pen = QPen(outer_col, 1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(QPolygonF(hex_pts(cx, cy, s)))

        # Inner hex — filled dim
        inner_col = QColor(C['cyan'])
        inner_col.setAlphaF(0.07)
        p.setBrush(QBrush(inner_col))
        border_col = QColor(C['cyan'])
        border_col.setAlphaF(0.25)
        p.setPen(QPen(border_col, 0.7))
        p.drawPolygon(QPolygonF(hex_pts(cx, cy, s * 0.65)))

        # "CL" text
        p.setPen(QPen(QColor(C['cyan'])))
        font_sz = max(6, int(self.s * 0.28))
        p.setFont(QFont('Share Tech Mono', font_sz, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, self.s, self.s), Qt.AlignmentFlag.AlignCenter, 'CL')
        p.end()


# ═════════════════════════════════════════════════════════════
# WORKER THREADS (unchanged)
# ═════════════════════════════════════════════════════════════
class SysInfoWorker(QThread):
    snapshot = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.paused   = False
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
            self.msleep(4000)


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
            # ── Real progress: each target owns an equal slice of 0–95% ──────
            # Within each target's slice, we emit three sub-steps so the bar
            # moves visibly instead of jumping in large discrete chunks:
            #   step 0% → starting (label shows target name)
            #   step 50% → working
            #   step 100% → done (moves to next target's start)
            # The final 95→100% jump happens only after ALL targets finish.
            slice_start = int((i / steps) * 95)
            slice_mid   = int(((i + 0.5) / steps) * 95)
            slice_end   = int(((i + 1) / steps) * 95)

            label = tid.replace('_', ' ').upper()
            self.progress.emit(slice_start, f'{label}...')
            self.log.emit(f'\n  ▸ {label}', 'head')

            self.progress.emit(slice_mid, f'{label} — working...')
            result = CLEANER.clean(tid, dry=self.dry)
            self.progress.emit(slice_end, f'{label} — done')

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
    col     = C[color]
    col_dim = C.get(color + '_dim', C['bg3'])
    pad = '5px 12px' if small else '8px 22px'
    sz  = '10px' if small else '11px'
    btn = QPushButton(text)
    btn.setStyleSheet(f"""
        QPushButton {{
            color:{col};
            border:1px solid {col}40;
            background:{col_dim if col_dim else col + '08'};
            font-family:{MONO}; font-size:{sz};
            letter-spacing:1.5px; padding:{pad};
            border-radius:2px; font-weight:600;
        }}
        QPushButton:hover {{
            background:{col}20; border-color:{col}80; color:{col};
        }}
        QPushButton:pressed {{
            background:{col}35; border-color:{col};
        }}
        QPushButton:checked {{
            background:{col}25; border-color:{col}; color:{col};
        }}
        QPushButton:disabled {{
            color:{C['dim']}; border-color:{C['dim']}30; background:transparent;
        }}
    """)
    return btn


def _lbl_section(text):
    l = QLabel(text)
    l.setStyleSheet(
        f'color:{C["text3"]};font-size:10px;letter-spacing:3px;'
        f'font-family:{MONO};padding:10px 0 5px 0;font-weight:700;'
    )
    return l


def _lbl_val(text, color='cyan', size=20):
    l = QLabel(text)
    l.setStyleSheet(
        f'color:{C[color]};font-size:{size}px;font-weight:700;'
        f'font-family:{MONO};letter-spacing:1px;'
    )
    return l


def _card(border_color=None, accent_color=None):
    f  = QFrame()
    bc = border_color or C['border2']
    if accent_color:
        f.setStyleSheet(
            f'QFrame{{'
            f'background:{C["bg2"]};'
            f'border-top:1px solid {bc};'
            f'border-right:1px solid {bc};'
            f'border-bottom:1px solid {bc};'
            f'border-left:3px solid {accent_color};'
            f'border-radius:3px;}}'
        )
    else:
        f.setStyleSheet(
            f'QFrame{{background:{C["bg2"]};border:1px solid {bc};border-radius:3px;}}'
        )
    return f


def _divider():
    l = QFrame()
    l.setFrameShape(QFrame.Shape.HLine)
    l.setStyleSheet(
        f'color:{C["border2"]};background:{C["border2"]};border:none;max-height:1px;'
    )
    return l


# ═════════════════════════════════════════════════════════════
# STAT CARD
# ═════════════════════════════════════════════════════════════
class StatCard(QFrame):
    def __init__(self, label, init_val, color='cyan', parent=None):
        super().__init__(parent)
        self.color = color
        col = C[color]
        self.setStyleSheet(
            f'QFrame{{background:{C["bg2"]};border:1px solid {C["border2"]};border-radius:3px;}}'
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        self.lbl_name = QLabel(label)
        self.lbl_name.setStyleSheet(
            f'color:{C["text3"]};font-size:10px;letter-spacing:3px;'
            f'font-family:{MONO};font-weight:700;'
        )
        self.lbl_val = QLabel(init_val)
        self.lbl_val.setStyleSheet(
            f'color:{col};font-size:24px;font-weight:700;'
            f'font-family:{MONO};letter-spacing:1px;'
        )
        lay.addWidget(self.lbl_name)
        lay.addWidget(self.lbl_val)

    def set_val(self, text, color=None):
        self.lbl_val.setText(text)
        col = C.get(color or self.color, C[self.color])
        self.lbl_val.setStyleSheet(
            f'color:{col};font-size:24px;font-weight:700;'
            f'font-family:{MONO};letter-spacing:1px;'
        )


# ═════════════════════════════════════════════════════════════
# REDESIGNED NAV BUTTON — icon widget + label + active bar
# ═════════════════════════════════════════════════════════════
class NavButton(QWidget):
    """
    Custom nav item:
    ┌─[active bar 2px]─[icon 18px]─[label text]─[stretch]─┐
    Active state: cyan bar on left + cyan icon + cyan text
    Inactive: no bar + dim icon + dim text
    Hover: slightly brighter text
    """
    clicked = pyqtSignal()

    def __init__(self, label: str, icon_name: str, parent=None):
        super().__init__(parent)
        self._active    = False
        self._icon_name = icon_name
        self._label_str = label
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)

        self._bar = QFrame(self)
        self._bar.setFixedWidth(2)
        self._bar.setStyleSheet('background:transparent;border:none;')

        self._icon_lbl = QLabel(self)
        self._icon_lbl.setFixedSize(18, 18)
        self._icon_lbl.setStyleSheet('background:transparent;border:none;')

        self._text_lbl = QLabel(label, self)
        self._text_lbl.setStyleSheet(
            f'color:{C["text3"]};font-family:{MONO};font-size:10px;'
            f'letter-spacing:1.5px;font-weight:600;background:transparent;border:none;'
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._bar)
        lay.addSpacing(12)
        lay.addWidget(self._icon_lbl)
        lay.addSpacing(10)
        lay.addWidget(self._text_lbl)
        lay.addStretch()

        self._update_icon()

    def _update_icon(self):
        ico = _nav_icon(self._icon_name, active=self._active, size=18)
        self._icon_lbl.setPixmap(ico.pixmap(18, 18))

    def set_active(self, active: bool):
        self._active = active
        if active:
            self._bar.setStyleSheet(
                f'background:{C["cyan"]};border:none;border-radius:1px;'
            )
            self._text_lbl.setStyleSheet(
                f'color:{C["cyan"]};font-family:{MONO};font-size:10px;'
                f'letter-spacing:1.5px;font-weight:700;background:transparent;border:none;'
            )
            self.setStyleSheet(f'QWidget{{background:{C["cyan"]}0e;}}')
        else:
            self._bar.setStyleSheet('background:transparent;border:none;')
            self._text_lbl.setStyleSheet(
                f'color:{C["text3"]};font-family:{MONO};font-size:10px;'
                f'letter-spacing:1.5px;font-weight:600;background:transparent;border:none;'
            )
            self.setStyleSheet('QWidget{background:transparent;}')
        self._update_icon()

    def set_label(self, text: str):
        self._label_str = text
        self._text_lbl.setText(text)

    def enterEvent(self, _):
        if not self._active:
            self._text_lbl.setStyleSheet(
                f'color:{C["text2"]};font-family:{MONO};font-size:10px;'
                f'letter-spacing:1.5px;font-weight:600;background:transparent;border:none;'
            )
            self.setStyleSheet(f'QWidget{{background:{C["cyan"]}08;}}')

    def leaveEvent(self, _):
        if not self._active:
            self._text_lbl.setStyleSheet(
                f'color:{C["text3"]};font-family:{MONO};font-size:10px;'
                f'letter-spacing:1.5px;font-weight:600;background:transparent;border:none;'
            )
            self.setStyleSheet('QWidget{background:transparent;}')

    def mousePressEvent(self, _):
        self.clicked.emit()



# ═════════════════════════════════════════════════════════════
# MODULE-LEVEL QTHREAD WORKERS
# MUST be defined at module scope, NOT nested inside methods.
# Reason: PyQt6 + SIP + Python 3.14 on KDE/Wayland crashes
# when pyqtSignal is defined inside a locally-scoped class
# (SIP cannot resolve the metaclass at binding time → Qt fatal).
# FIX: All QThread subclasses with pyqtSignal moved here.
# ═════════════════════════════════════════════════════════════

class _SmartOnWorker(QThread):
    """Smart Boost ON — runs smart_boost_on() in background thread."""
    log_signal = pyqtSignal(str, str)
    done       = pyqtSignal(object)

    def run(self):
        try:
            saved = smart_boost_on(lambda m, l='text': self.log_signal.emit(m, l))
            self.done.emit(saved)
        except Exception as e:
            self.log_signal.emit(f"  x Smart Boost error: {e}", "err")
            self.done.emit({})


class _SmartOffWorker(QThread):
    """Smart Boost OFF — runs smart_boost_off() in background thread."""
    log_signal = pyqtSignal(str, str)
    done       = pyqtSignal(object)

    def __init__(self, saved_state):
        super().__init__()
        self._saved_state = saved_state

    def run(self):
        try:
            smart_boost_off(self._saved_state, lambda m, l='text': self.log_signal.emit(m, l))
        except Exception as e:
            self.log_signal.emit(f"  x Smart Boost restore error: {e}", "err")
        self.done.emit(None)


class _OneClickWorker(QThread):
    """One-Click Optimize — runs platform-specific quick fixes."""
    done = pyqtSignal(str, bool)

    def run(self):
        import subprocess as _sp
        HELPER  = '/usr/local/bin/cyber-clean-helper'
        results = []
        if IS_LINUX:
            for action, label in [
                ('swappiness',  'Swappiness→10'),
                ('fstrim',      'SSD TRIM'),
                ('journal',     'Journal'),
                ('paccache',    'Paccache'),
                ('compact-memory', 'Compact RAM'),
            ]:
                import shutil as _sh
                if action == 'paccache' and not _sh.which('paccache'):
                    continue
                r = _sp.run(f'sudo -n {HELPER} {action}', shell=True,
                            capture_output=True, text=True, timeout=60)
                results.append((label, r.returncode == 0))
            # Free RAM without drop_caches (no lag)
            try:
                from core.booster import free_ram
                free_ram(lambda m, l='text': None)
                results.append(('Smart RAM Free', True))
            except Exception:
                pass
        elif IS_WINDOWS:
            for cmd, label in [
                ('ipconfig /flushdns', 'Flush DNS'),
                ('del /q /f /s "%TEMP%\\*" 2>nul', 'Clear TEMP'),
            ]:
                r = _sp.run(cmd, shell=True, capture_output=True,
                            text=True, timeout=30, creationflags=0x08000000)
                results.append((label, r.returncode == 0))
            try:
                from core.booster import free_ram
                free_ram(lambda m, l='text': None)
                results.append(('Smart RAM Free', True))
            except Exception:
                pass
        ok_count = sum(1 for _, ok in results if ok)
        summary  = (f'✓ {ok_count}/{len(results)}  ' +
                    '  ·  '.join(f'{"✓" if ok else "~"}{n}' for n, ok in results))
        self.done.emit(summary, ok_count > 0)


class _ScanWorker(QThread):
    """Security Scanner — runs full deep scan in background."""
    log  = pyqtSignal(str, str)
    done = pyqtSignal(list, list)

    def run(self):
        try:
            sc      = SecurityScanner()
            results = sc.scan(lambda m, l: self.log.emit(m, l))
        except Exception as e:
            self.log.emit(f"  x Scanner error: {e}", "err")
            results = []
        try:
            self.log.emit("  ⟳  Scanning active network processes...", "head")
            net_results = get_network_processes()
        except Exception:
            net_results = []
        self.done.emit(results, net_results)


class _UninstallWorker(QThread):
    """App Uninstaller — enumerates installed apps in background."""
    finished = pyqtSignal(list)

    def run(self):
        try:
            apps = get_installed_apps()
            self.finished.emit(apps)
        except Exception:
            self.finished.emit([])


class _AutoCleanWorker(QThread):
    """Auto-clean — runs safe targets silently from tray."""
    done = pyqtSignal(int, int)

    def __init__(self, safe_targets):
        super().__init__()
        self._safe_targets = safe_targets

    def run(self):
        total_freed = 0
        cleaned     = 0
        for tid in self._safe_targets:
            try:
                result       = CLEANER.clean(tid, dry=False)
                total_freed += result.freed_bytes
                cleaned     += 1
            except Exception:
                pass
        self.done.emit(total_freed, cleaned)


# ═════════════════════════════════════════════════════════════
# MAIN APP
# ═════════════════════════════════════════════════════════════
class CyberCleanApp(QMainWindow):

    update_found = pyqtSignal(str, str)  # version, release_body (markdown)

    # Icon name per tab — maps to _ICON_FN keys
    _TAB_ICONS = {
        'dashboard': 'dashboard',
        'clean':     'smart_clean',
        'scanner':   'scanner',
        'uninstall': 'uninstaller',
        'log':       'history',
        'rollback':  'rollback',
        'browser':   'booster',
    }

    @property
    def NAV_ITEMS(self):
        return [
            ('dashboard', 'dashboard',   _t('nav_dashboard', 'TỔNG QUAN')),
            ('clean',     'smart_clean', _t('nav_clean',     'DỌN RÁC')),
            ('scanner',   'scanner',     _t('nav_scanner',   'QUÉT BẢO MẬT')),
            ('uninstall', 'uninstaller', _t('nav_uninstall', 'GỠ ỨNG DỤNG')),
            ('log',       'history',     _t('nav_history',   'LỊCH SỬ')),
            ('rollback',  'rollback',    _t('nav_rollback',  'KHÔI PHỤC')),
            ('browser',   'booster',     _t('nav_booster',   'TĂNG TỐC')),
        ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'CyberClean v{__version__}')
        self.setMinimumSize(1060, 680)
        self.resize(1200, 760)
        self.worker   = None
        self.selected = set()
        self._charts  = {}
        self._snap    = None
        self._last_refresh_time = 0.0
        self._settings = QSettings()
        self._pending_update_ver = ""
        self._pending_update_body = ""

        self._init_palette()
        self._build_ui()
        self._start_sysinfo()
        self._start_clock()
        self._nav('dashboard')
        self._setup_tray()
        self.update_found.connect(self._show_update_notice)
        self._start_auto_clean()
        self._check_update_async()

    # ── Global Palette & Stylesheet ──────────────────────────
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
                background:{C['bg']}; width:5px; border:none; margin:0;
            }}
            QScrollBar::handle:vertical {{
                background:{C['border3']}; border-radius:2px; min-height:24px;
            }}
            QScrollBar::handle:vertical:hover {{ background:{C['cyan']}60; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar:horizontal {{
                background:{C['bg']}; height:5px; border:none;
            }}
            QScrollBar::handle:horizontal {{
                background:{C['border3']}; border-radius:2px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
            QTableWidget {{
                background:{C['bg2']}; border:1px solid {C['border2']};
                gridline-color:{C['border']}; font-size:11px; border-radius:3px;
                selection-background-color:transparent;
            }}
            QTableWidget::item {{
                padding:6px 10px; border:none; background:transparent;
                color:{C['text2']};
            }}
            QTableWidget::item:alternate {{ background:{C['bg3']}; }}
            QTableWidget::item:hover {{
                background:{C['cyan']}0d; color:{C['text']};
            }}
            QTableWidget::item:selected {{
                background:{C['cyan']}18; color:{C['text']};
                border-left:2px solid {C['cyan']}90;
            }}
            QHeaderView::section {{
                background:{C['bg']}; color:{C['text3']};
                border:none;
                border-bottom:1px solid {C['border2']};
                border-right:1px solid {C['border']};
                padding:6px 10px; font-size:10px; letter-spacing:2.5px;
                font-weight:700;
            }}
            QHeaderView::section:last {{ border-right:none; }}
            QCheckBox {{ color:{C['text2']}; spacing:8px; font-size:11px; }}
            QCheckBox::indicator {{
                width:13px; height:13px;
                border:1px solid {C['border3']}; background:transparent;
                border-radius:2px;
            }}
            QCheckBox::indicator:hover {{ border-color:{C['cyan']}60; }}
            QCheckBox::indicator:checked {{
                background:{C['cyan']}25; border-color:{C['cyan']};
            }}
            QProgressBar {{
                background:{C['bg3']}; border:none; height:2px; border-radius:1px;
            }}
            QProgressBar::chunk {{
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['cyan']}, stop:1 {C['green']});
                border-radius:1px;
            }}
            QTextEdit {{
                background:#020810; color:{C['text2']};
                border:1px solid {C['border2']}; border-radius:3px;
                font-family:{MONO}; font-size:11px; padding:10px;
                selection-background-color:{C['cyan']}30;
            }}
            QLineEdit {{
                background:{C['bg3']}; color:{C['text']};
                border:1px solid {C['border2']}; border-radius:3px;
                padding:6px 12px; font-size:11px; font-family:{MONO};
            }}
            QLineEdit:hover {{ border-color:{C['border3']}; }}
            QLineEdit:focus {{ border-color:{C['cyan']}70; background:{C['bg4']}; }}
            QComboBox {{
                background:{C['bg3']}; color:{C['text2']};
                border:1px solid {C['border2']}; border-radius:3px;
                padding:5px 10px; font-size:11px; font-family:{MONO};
            }}
            QComboBox:hover {{ border-color:{C['border3']}; }}
            QComboBox::drop-down {{ border:none; width:16px; }}
            QComboBox QAbstractItemView {{
                background:{C['bg2']}; color:{C['text']};
                selection-background-color:{C['cyan']}20;
                border:1px solid {C['border2']}; outline:none;
            }}
            QMenu {{
                background:{C['bg2']}; color:{C['text']};
                border:1px solid {C['border2']}; padding:4px;
            }}
            QMenu::item {{ padding:7px 20px; border-radius:2px; }}
            QMenu::item:selected {{ background:{C['cyan']}18; color:{C['cyan']}; }}
            QMenu::separator {{ background:{C['border2']}; height:1px; margin:4px 8px; }}
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
        h.setFixedHeight(48)
        h.setStyleSheet(f"""
            QFrame {{
                background:{C['bg']};
                border-bottom:1px solid {C['border2']};
            }}
        """)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(0)

        # Hex logo widget — pure QPainter, no file
        hex_logo = HexLogoWidget(size=28)
        lay.addWidget(hex_logo)
        lay.addSpacing(10)

        logo_text = QLabel('CYBER')
        logo_text.setStyleSheet(
            f'color:{C["cyan"]};font-size:14px;font-weight:900;'
            f'letter-spacing:5px;font-family:{MONO};'
        )
        sep_dot = QLabel('·')
        sep_dot.setStyleSheet(f'color:{C["border3"]};font-size:13px;padding:0 5px;')
        clean_text = QLabel('CLEAN')
        clean_text.setStyleSheet(
            f'color:{C["text2"]};font-size:14px;font-weight:700;'
            f'letter-spacing:5px;font-family:{MONO};'
        )
        ver = QLabel(f'v{__version__}')
        ver.setStyleSheet(
            f'color:{C["text3"]};font-size:9px;letter-spacing:1px;'
            f'padding-left:10px;padding-top:5px;font-family:{MONO};'
        )
        for w in [logo_text, sep_dot, clean_text, ver]:
            lay.addWidget(w)

        # OS info separator
        os_sep = QLabel('│')
        os_sep.setStyleSheet(f'color:{C["border3"]};padding:0 18px;font-size:15px;')
        lay.addWidget(os_sep)

        self._os_info_lbl = QLabel(
            f'{OS.upper()}  ·  '
            f"{PKG_MANAGER.upper() if PKG_MANAGER else _t('header_cross','CROSS-PLATFORM')}"
            f'  ·  {_t("header_subtitle","SMART DISK MANAGER")}'
        )
        self._os_info_lbl.setStyleSheet(
            f'color:{C["text3"]};font-size:10px;letter-spacing:2px;font-family:{MONO};'
        )
        lay.addWidget(self._os_info_lbl)
        lay.addStretch()

        # Update badge (hidden until GitHub release > current version)
        self._upd_lbl = UpdateBadge()
        self._upd_lbl.setStyleSheet(
            f'color:{C["yellow"]};font-size:10px;letter-spacing:1.5px;'
            f'font-family:{MONO};border:1px solid {C["yellow"]}50;'
            f'padding:3px 8px;border-radius:2px;'
        )
        self._upd_lbl.setVisible(False)
        self._upd_lbl.clicked.connect(self._open_update_dialog)

        # Status dot
        status_frame = QFrame()
        status_frame.setStyleSheet('QFrame{background:transparent;border:none;}')
        sf_lay = QHBoxLayout(status_frame)
        sf_lay.setContentsMargins(0, 0, 0, 0)
        sf_lay.setSpacing(5)
        dot = QLabel('●')
        dot.setStyleSheet(f'color:{C["green"]};font-size:7px;')
        status_lbl = QLabel('ACTIVE')
        status_lbl.setStyleSheet(
            f'color:{C["text3"]};font-size:10px;letter-spacing:2px;font-family:{MONO};'
        )
        sf_lay.addWidget(dot)
        sf_lay.addWidget(status_lbl)

        self.clock_lbl = QLabel('--:--:--')
        self.clock_lbl.setStyleSheet(
            f'color:{C["cyan"]};font-size:11px;letter-spacing:2px;'
            f'font-family:{MONO};padding-left:14px;font-weight:700;'
        )

        self._lang_cb = QComboBox()
        for code, name in SUPPORTED_LANGS.items():
            self._lang_cb.addItem(name, code)
        cur_idx = list(SUPPORTED_LANGS.keys()).index(T.lang) if T.lang in SUPPORTED_LANGS else 0
        self._lang_cb.setCurrentIndex(cur_idx)
        self._lang_cb.setFixedWidth(110)
        self._lang_cb.currentIndexChanged.connect(self._change_language)

        lay.addWidget(self._upd_lbl)
        lay.addSpacing(10)
        lay.addWidget(self._lang_cb)
        lay.addSpacing(14)
        lay.addWidget(status_frame)
        lay.addWidget(self.clock_lbl)
        return h

    # ── REDESIGNED SIDEBAR ───────────────────────────────────
    def _build_sidebar(self):
        side = QFrame()
        side.setFixedWidth(200)
        side.setStyleSheet(f"""
            QFrame {{
                background:{C['bg']};
                border-right:1px solid {C['border2']};
            }}
        """)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 14, 0, 14)
        lay.setSpacing(0)

        # Navigation label
        nav_label = QLabel('NAVIGATION')
        nav_label.setStyleSheet(
            f'color:{C["dim"]};font-size:9px;letter-spacing:3px;'
            f'font-family:{MONO};padding:0 16px 8px 16px;font-weight:700;'
        )
        lay.addWidget(nav_label)

        # Nav buttons — using new NavButton widget (pure QPainter icons)
        self.nav_btns = {}
        for pid, icon_name, label in self.NAV_ITEMS:
            btn = NavButton(label, icon_name)
            btn.clicked.connect(lambda p=pid: self._nav(p))
            self.nav_btns[pid] = btn
            lay.addWidget(btn)

        lay.addSpacing(14)
        lay.addWidget(_divider())
        lay.addSpacing(14)

        # Disk ring panel
        disk_panel = QFrame()
        disk_panel.setStyleSheet(f"""
            QFrame {{
                background:{C['bg2']};
                border:1px solid {C['border2']};
                border-radius:3px;
                margin:0 12px;
            }}
        """)
        dp_lay = QVBoxLayout(disk_panel)
        dp_lay.setContentsMargins(12, 12, 12, 12)
        dp_lay.setSpacing(6)

        disk_header = QLabel('DISK USAGE')
        disk_header.setStyleSheet(
            f'color:{C["text3"]};font-size:9px;letter-spacing:3px;'
            f'font-family:{MONO};font-weight:700;'
        )
        dp_lay.addWidget(disk_header)

        ring_row = QHBoxLayout()
        ring_row.addStretch()
        self.disk_ring = DiskRing()
        ring_row.addWidget(self.disk_ring)
        ring_row.addStretch()
        dp_lay.addLayout(ring_row)

        self.disk_detail_lbl = QLabel('— / —')
        self.disk_detail_lbl.setStyleSheet(
            f'color:{C["text3"]};font-size:10px;font-family:{MONO};'
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
            if info.get('is_wsl'):
                pi_text += (
                    '\n\nWSL: Some features are limited (TRIM, drop_cache,'
                    '\n     full booster) — use on bare metal for best results.'
                )
        pi_lbl = QLabel(pi_text)
        pi_lbl.setStyleSheet(
            f'color:{C["text3"]};font-size:10px;letter-spacing:1px;'
            f'padding:0 14px;line-height:2;font-family:{MONO};'
        )
        lay.addWidget(pi_lbl)
        lay.addSpacing(8)

        # Status pills
        pills = []
        if IS_LINUX:
            pills.append(('POLKIT', C['green'] if HAS_POLKIT else C['red']))
            if HAS_FLATPAK: pills.append(('FLATPAK', C['cyan']))
            if HAS_DOCKER:  pills.append(('DOCKER',  C['cyan']))
        elif IS_WINDOWS:
            pills.append(('ADMIN', C['green'] if is_windows_admin() else C['yellow']))

        if pills:
            pill_row = QHBoxLayout()
            pill_row.setContentsMargins(12, 0, 12, 0)
            pill_row.setSpacing(5)
            for label, col in pills:
                pl = QLabel(label)
                pl.setStyleSheet(
                    f'color:{col};font-size:9px;letter-spacing:1.5px;'
                    f'border:1px solid {col}50;padding:2px 6px;'
                    f'font-family:{MONO};font-weight:700;border-radius:2px;'
                )
                pill_row.addWidget(pl)
            pill_row.addStretch()
            lay.addLayout(pill_row)
            lay.addSpacing(6)

        return side

    # ── MAIN STACK ───────────────────────────────────────────
    def _build_main(self):
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f'background:{C["bg"]};border:none;')
        self.stack.addWidget(self._build_dashboard())
        self.stack.addWidget(self._build_clean())
        self.stack.addWidget(self._build_scanner())
        self.stack.addWidget(self._build_uninstall())
        self.stack.addWidget(self._build_log())
        self.stack.addWidget(self._build_rollback())
        self.stack.addWidget(self._build_browser_turbo())
        return self.stack

    # ── Page header helper ───────────────────────────────────
    def _page_header(self, title, subtitle=None, store_key=None):
        if not hasattr(self, '_page_hdr_lbls'):
            self._page_hdr_lbls = {}
        frame = QWidget()
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 14)
        fl.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(
            f'color:{C["text"]};font-size:13px;font-weight:700;'
            f'letter-spacing:5px;font-family:{MONO};'
        )
        fl.addWidget(t)
        s = None
        if subtitle:
            s = QLabel(subtitle)
            s.setStyleSheet(f'color:{C["text3"]};font-size:11px;font-family:{MONO};')
            s.setWordWrap(True)
            fl.addWidget(s)
        sep = _divider()
        fl.addSpacing(8)
        fl.addWidget(sep)
        if store_key:
            self._page_hdr_lbls[store_key] = (t, s)
        return frame

    # ── NAV logic — updated for NavButton ────────────────────
    def _nav(self, pid):
        pages = [item[0] for item in self.NAV_ITEMS]
        if pid not in pages:
            return
        self._active_tab = pid
        self.stack.setCurrentIndex(pages.index(pid))
        for k, btn in self.nav_btns.items():
            btn.set_active(k == pid)
        if hasattr(self, '_si_worker'):
            self._si_worker.paused = (pid != 'dashboard')
        if pid == 'log':       self._load_log()
        if pid == 'rollback':  self._load_rollback()
        if pid == 'uninstall': self._load_uninstall()
        if pid == 'clean' and IS_LINUX and not HAS_POLKIT_AGENT:
            self._show_polkit_warning()

    # ─────────────────────────────────────────────────────────
    # REDESIGNED DASHBOARD
    # ─────────────────────────────────────────────────────────
    def _build_dashboard(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(14)

        # Header row
        hdr = QHBoxLayout()
        self._lbl_sys_overview = QLabel(_t('sys_overview', 'SYSTEM OVERVIEW'))
        self._lbl_sys_overview.setStyleSheet(
            f'color:{C["text"]};font-size:12px;font-weight:700;'
            f'letter-spacing:5px;font-family:{MONO};'
        )
        self._ref_btn = _btn(f"↻  {_t('btn_refresh','REFRESH')}", 'cyan', small=True)
        self._ref_btn.clicked.connect(self._refresh_now)
        hdr.addWidget(self._lbl_sys_overview)
        hdr.addStretch()
        hdr.addWidget(self._ref_btn)
        lay.addLayout(hdr)
        lay.addWidget(_divider())

        # ── Health + One-Click row ─────────────────────
        top = QHBoxLayout(); top.setSpacing(12)

        # Health card
        hc = _card(accent_color=C['green'])
        hc.setMinimumWidth(150)
        hc.setMaximumWidth(200)
        hcl = QVBoxLayout(hc); hcl.setContentsMargins(16, 14, 16, 14); hcl.setSpacing(4)
        self._lbl_health_sec = _lbl_section(_t('lbl_health', 'HEALTH SCORE'))
        hcl.addWidget(self._lbl_health_sec)
        self.health_lbl = QLabel('—')
        self.health_lbl.setStyleSheet(
            f'color:{C["green"]};font-size:34px;font-weight:700;font-family:{MONO};'
        )
        self.health_sub = QLabel(_t('lbl_calculating', 'Calculating...'))
        self.health_sub.setStyleSheet(
            f'color:{C["text3"]};font-size:11px;font-family:{MONO};'
        )
        self.health_sub.setWordWrap(True)
        hcl.addWidget(self.health_lbl)
        hcl.addWidget(self.health_sub)
        top.addWidget(hc)

        # One-click card
        oc = _card(accent_color=C['cyan'])
        ocl = QVBoxLayout(oc); ocl.setContentsMargins(16, 14, 16, 14); ocl.setSpacing(6)
        self._lbl_oneclick_sec = _lbl_section(_t('lbl_oneclick', 'ONE-CLICK OPTIMIZE'))
        ocl.addWidget(self._lbl_oneclick_sec)
        self._lbl_oc_desc = QLabel(
            'Flush DNS  ·  Clear TEMP  ·  Drop cache  ·  TRIM SSD'
            if IS_WINDOWS else
            'Drop cache  ·  Tune swap  ·  TRIM SSD  ·  Clean journal'
        )
        self._lbl_oc_desc.setStyleSheet(f'color:{C["text3"]};font-size:11px;font-family:{MONO};')
        self._lbl_oc_desc.setWordWrap(True)
        oc_row = QHBoxLayout()
        self.oneclick_btn = _btn(f"⚡  {_t('btn_optimize','OPTIMIZE NOW')}", 'cyan')
        self.oneclick_btn.clicked.connect(self._one_click_fix)
        self.oneclick_log = QLabel('')
        self.oneclick_log.setStyleSheet(
            f'color:{C["green"]};font-size:11px;font-family:{MONO};'
        )
        oc_row.addWidget(self.oneclick_btn)
        oc_row.addStretch()
        ocl.addWidget(self._lbl_oc_desc)
        ocl.addLayout(oc_row)
        ocl.addWidget(self.oneclick_log)
        top.addWidget(oc, 1)
        lay.addLayout(top)

        # ── Stat cards row ─────────────────────────────
        sc_row = QHBoxLayout(); sc_row.setSpacing(10)
        self._stat_cards = {}
        for sid, label, init, col in [
            ('cpu',  'CPU',                                      '—%',  'red'),
            ('ram',  'RAM',                                      '—%',  'cyan'),
            ('temp', _t('lbl_temperature', 'TEMPERATURE'),       '—°C', 'green'),
            ('swap', _t('lbl_swap', 'SWAP'),                     '—',   'yellow'),
        ]:
            card_w = StatCard(label, init, col)
            self._stat_cards[sid] = card_w
            sc_row.addWidget(card_w)
        lay.addLayout(sc_row)

        # ── Charts row ─────────────────────────────────
        ch_row = QHBoxLayout(); ch_row.setSpacing(10)
        for label, sid, col in [
            (_t('lbl_cpu_chart', 'CPU %'), 'cpu', C['red']),
            (_t('lbl_ram_chart', 'RAM %'), 'ram', C['cyan'])
        ]:
            cf = _card()
            cf.setMinimumHeight(90)
            cl = QVBoxLayout(cf); cl.setContentsMargins(14, 10, 14, 10); cl.setSpacing(4)
            hl_row = QHBoxLayout()
            hl = QLabel(label)
            hl.setStyleSheet(
                f'color:{C["text3"]};font-size:10px;letter-spacing:2.5px;'
                f'font-family:{MONO};font-weight:700;'
            )
            hl_row.addWidget(hl)
            hl_row.addStretch()
            chart = SparklineChart(color=col)
            self._charts[sid] = chart
            cl.addLayout(hl_row)
            cl.addWidget(chart)
            ch_row.addWidget(cf)
        lay.addLayout(ch_row)

        # ── Process + Disk tables ─────────────────────
        bot = QHBoxLayout(); bot.setSpacing(12)

        # Processes
        proc_frame = _card()
        pfl = QVBoxLayout(proc_frame); pfl.setContentsMargins(14, 12, 14, 12); pfl.setSpacing(8)
        ph = QHBoxLayout()
        self._lbl_top_proc_sec = _lbl_section(_t('lbl_top_proc', 'TOP PROCESSES'))
        ph.addWidget(self._lbl_top_proc_sec)
        kill_btn = _btn(f"✕ {_t('btn_kill','KILL')}", 'red', small=True)
        kill_btn.clicked.connect(self._kill_selected_proc)
        ph.addStretch(); ph.addWidget(kill_btn)
        pfl.addLayout(ph)
        self.proc_table = QTableWidget(0, 4)
        self.proc_table.setHorizontalHeaderLabels([
            _t('col_pid','PID'), _t('col_name','NAME'),
            _t('col_cpu','CPU %'), _t('col_mem','MEM %')
        ])
        self.proc_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.proc_table.verticalHeader().setVisible(False)
        self.proc_table.setMinimumHeight(100)
        self.proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.proc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.proc_table.setAlternatingRowColors(True)
        pfl.addWidget(self.proc_table, 1)
        bot.addWidget(proc_frame, 3)

        # Disk usage
        disk_frame = _card()
        dfl = QVBoxLayout(disk_frame); dfl.setContentsMargins(14, 12, 14, 12); dfl.setSpacing(8)
        self._lbl_disk_sec = _lbl_section(_t('lbl_disk', 'DISK USAGE'))
        dfl.addWidget(self._lbl_disk_sec)
        self.disk_table = QTableWidget(0, 4)
        self.disk_table.setHorizontalHeaderLabels([
            _t('col_drive', 'DRIVE'), '▲ USED', '▽ FREE', '%'
        ])
        _dh = self.disk_table.horizontalHeader()
        _dh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        _dh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        _dh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        _dh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.disk_table.setColumnWidth(1, 76)
        self.disk_table.setColumnWidth(2, 76)
        self.disk_table.setColumnWidth(3, 88)
        self.disk_table.verticalHeader().setVisible(False)
        self.disk_table.setMinimumHeight(100)
        self.disk_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.disk_table.setAlternatingRowColors(True)
        dfl.addWidget(self.disk_table, 1)
        bot.addWidget(disk_frame, 2)

        lay.addLayout(bot, 1)
        return w

    # ─────────────────────────────────────────────────────────
    # REDESIGNED CLEAN
    # ─────────────────────────────────────────────────────────
    def _build_clean(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(0)

        lay.addWidget(self._page_header(
            _t('clean_targets', 'CLEAN TARGETS'),
            _t('clean_subtitle', 'Select targets · Dry-run to preview · Clean to execute'),
            store_key='clean'
        ))

        # Action bar FIRST (moved to top for discoverability)
        ar = QHBoxLayout(); ar.setSpacing(8)
        self._dry_btn   = _btn(f"⬡  {_t('btn_dryrun','DRY-RUN')}", 'cyan')
        self._clean_btn = _btn(f"⚡  {_t('btn_clean_now','CLEAN NOW')}", 'red')
        self._all_btn   = _btn(f"☑  {_t('btn_all','ALL')}",  small=True)
        self._none_btn  = _btn(f"☐  {_t('btn_none','NONE')}", small=True)
        self._dry_btn.clicked.connect(lambda: self._run_clean(dry=True))
        self._clean_btn.clicked.connect(self._confirm_clean)
        self._all_btn.clicked.connect(self._sel_all)
        self._none_btn.clicked.connect(self._sel_none)
        for b in [self._dry_btn, self._clean_btn, self._all_btn, self._none_btn]:
            ar.addWidget(b)
        ar.addStretch()
        lay.addLayout(ar)
        lay.addSpacing(12)

        # Progress
        self.clean_prog = QProgressBar()
        self.clean_prog.setTextVisible(False)
        self.clean_prog.setFixedHeight(2)
        self.clean_prog.setVisible(False)
        self.clean_prog_lbl = QLabel('')
        self.clean_prog_lbl.setStyleSheet(
            f'color:{C["text3"]};font-size:11px;font-family:{MONO};'
        )
        self.clean_prog_lbl.setVisible(False)
        lay.addWidget(self.clean_prog)
        lay.addWidget(self.clean_prog_lbl)
        lay.addSpacing(8)

        # Target list
        self._lbl_clean_targets_sec = _lbl_section(_t('clean_targets', 'TARGETS'))
        lay.addWidget(self._lbl_clean_targets_sec)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('border:none;background:transparent;')
        scroll.setMinimumHeight(160)
        scroll.setMaximumHeight(300)
        sw = QWidget()
        sl = QVBoxLayout(sw); sl.setContentsMargins(0, 0, 4, 0); sl.setSpacing(4)

        self.target_checks = {}
        self._target_lbls  = {}   # {tid: (nm_label, dc_label, badge_label, target_obj)}
        targets = CLEANER.get_targets() if CLEANER else []
        for t in targets:
            row = QFrame()
            sc = C['green'] if t.safety == 'safe' else C['yellow'] if t.safety == 'caution' else C['red']
            row.setStyleSheet(
                f'QFrame{{background:{C["bg2"]};'
                f'border-top:1px solid {C["border2"]};'
                f'border-right:1px solid {C["border2"]};'
                f'border-bottom:1px solid {C["border2"]};'
                f'border-left:3px solid {sc}60;'
                f'border-radius:2px;}}'
                f'QFrame:hover{{background:{C["bg3"]};}}'
            )
            rl = QHBoxLayout(row); rl.setContentsMargins(14, 8, 14, 8); rl.setSpacing(12)

            chk = QCheckBox()
            chk.setChecked(t.safety == 'safe')
            if chk.isChecked():
                self.selected.add(t.id)
            chk.stateChanged.connect(lambda s, tid=t.id: self._toggle(tid, s))
            self.target_checks[t.id] = chk

            nc = QVBoxLayout(); nc.setSpacing(2)
            nm = QLabel(_t(f'tgt_{t.id}_name', t.name) + (' [ROOT]' if t.needs_root else ''))
            nm.setStyleSheet(
                f'color:{C["text"]};font-size:11px;font-family:{MONO};font-weight:600;'
            )
            dc = QLabel(_t(f'tgt_{t.id}_desc', t.desc))
            dc.setStyleSheet(
                f'color:{C["text3"]};font-size:10px;font-family:{MONO};'
            )
            nc.addWidget(nm); nc.addWidget(dc)

            badge_map = {
                'safe':    _t('badge_safe',    'SAFE'),
                'caution': _t('badge_caution', 'CAUTION'),
                'danger':  _t('badge_danger',  'DANGER')
            }
            badge = QLabel(badge_map.get(t.safety, t.safety.upper()))
            badge.setStyleSheet(
                f'color:{sc};font-size:9px;letter-spacing:1.5px;font-weight:700;'
                f'border:1px solid {sc}50;padding:3px 8px;font-family:{MONO};'
                f'border-radius:2px;'
            )
            self._target_lbls[t.id] = (nm, dc, badge, t)  # lưu để retranslate live
            rl.addWidget(chk); rl.addLayout(nc, 1); rl.addWidget(badge)
            sl.addWidget(row)

        sl.addStretch()
        scroll.setWidget(sw)
        lay.addWidget(scroll)
        lay.addSpacing(12)

        # Output
        self._lbl_clean_output_sec = _lbl_section(_t('lbl_output', 'OUTPUT LOG'))
        lay.addWidget(self._lbl_clean_output_sec)
        self.clean_terminal = QTextEdit()
        self.clean_terminal.setReadOnly(True)
        self.clean_terminal.setPlaceholderText(
            _t('placeholder_clean', '  → Select targets and click DRY-RUN to preview...')
        )
        lay.addWidget(self.clean_terminal, 1)
        return w

    # ─────────────────────────────────────────────────────────
    # REDESIGNED SCANNER
    # ─────────────────────────────────────────────────────────
    def _build_scanner(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(0)

        lay.addWidget(self._page_header(
            _t('scanner_title', 'SECURITY SCANNER'),
            'malware · reverse shells · crypto miners · SUID · cron backdoors · world-writable · hosts hijack · open ports',
            store_key='scanner'
        ))

        # Read-only badge
        badge = QFrame()
        badge.setStyleSheet(
            f'QFrame{{background:{C["cyan_dim"]};'
            f'border:1px solid {C["cyan"]}25;border-radius:3px;}}'
        )
        bl = QHBoxLayout(badge); bl.setContentsMargins(12, 7, 12, 7)
        self._scan_readonly_lbl = QLabel(
            f'<span style="color:{C["cyan"]};font-family:{MONO};font-size:11px;">'
            f'{_t("scanner_readonly_badge","⬡  Read-only scan — nothing deleted automatically")}'
            f'</span>'
        )
        bl.addWidget(self._scan_readonly_lbl)
        bl.addStretch()
        lay.addWidget(badge)
        lay.addSpacing(16)

        # Action row
        br = QHBoxLayout(); br.setSpacing(10)
        self.scan_btn = _btn(f"⬡  {_t('btn_run_scan','RUN DEEP SCAN')}", 'cyan')
        self.scan_btn.setMinimumHeight(40)
        self.scan_btn.setStyleSheet(
            f'QPushButton{{background:{C["cyan"]}20;color:{C["cyan"]};'
            f'border:1px solid {C["cyan"]}70;'
            f'font-size:12px;font-weight:700;letter-spacing:3px;font-family:{MONO};'
            f'padding:10px 28px;border-radius:3px;}}'
            f'QPushButton:hover{{background:{C["cyan"]}35;border-color:{C["cyan"]};border-width:2px;}}'
            f'QPushButton:pressed{{background:{C["cyan"]}50;}}'
        )
        self.scan_btn.clicked.connect(self._run_scanner)
        self.fix_btn = _btn(f"⚡  {_t('btn_autofix','AUTO-FIX SELECTED')}", 'yellow', small=True)
        self.fix_btn.setToolTip(_t('scan_tooltip', 'Run scan first, then select findings to fix'))
        self.fix_btn.clicked.connect(self._fix_scan_results)
        self.fix_btn.setEnabled(False)
        br.addWidget(self.scan_btn)
        br.addWidget(self.fix_btn)
        br.addStretch()
        lay.addLayout(br)
        lay.addSpacing(14)

        # Output
        self._lbl_scan_output_sec = _lbl_section(_t('lbl_scan_output', 'SCAN OUTPUT'))
        lay.addWidget(self._lbl_scan_output_sec)
        self.opt_terminal = QTextEdit()
        self.opt_terminal.setReadOnly(True)
        self.opt_terminal.setPlaceholderText(
            _t('placeholder_scan', '  ◈  Click  RUN DEEP SCAN  to start...')
        )
        lay.addWidget(self.opt_terminal, 1)
        lay.addSpacing(10)

        # Findings table
        self._lbl_findings_sec = _lbl_section(_t('lbl_findings', 'FINDINGS'))
        lay.addWidget(self._lbl_findings_sec)
        self.scan_table = QTableWidget(0, 4)
        self.scan_table.setHorizontalHeaderLabels([
            _t('col_sev','SEV'), _t('col_category','CATEGORY'),
            _t('col_path','PATH'), _t('col_detail','DETAIL')
        ])
        self.scan_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.scan_table.verticalHeader().setVisible(False)
        self.scan_table.setMinimumHeight(120)
        self.scan_table.setMaximumHeight(220)
        self.scan_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.scan_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.scan_table.setAlternatingRowColors(True)
        self.scan_table.itemSelectionChanged.connect(self._on_scan_select)
        lay.addWidget(self.scan_table)
        return w

    # ─────────────────────────────────────────────────────────
    # REDESIGNED UNINSTALL
    # ─────────────────────────────────────────────────────────
    def _build_uninstall(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(0)

        hdr_row = QHBoxLayout()
        self._lbl_uninst_title = QLabel(_t('uninstall_title', 'APP UNINSTALLER'))
        page_t = self._lbl_uninst_title
        page_t.setStyleSheet(
            f'color:{C["text"]};font-size:12px;font-weight:700;'
            f'letter-spacing:5px;font-family:{MONO};'
        )
        self._uninst_ref_btn = _btn(f"↻ {_t('btn_refresh','REFRESH')}", 'cyan', small=True)
        self._uninst_ref_btn.clicked.connect(self._load_uninstall)
        hdr_row.addWidget(page_t)
        hdr_row.addStretch()
        hdr_row.addWidget(self._uninst_ref_btn)
        lay.addLayout(hdr_row)
        lay.addWidget(_divider())
        lay.addSpacing(10)

        self._lbl_uninst_hint = QLabel(_t('uninstall_hint', 'Select one or more apps  →  Uninstall'))
        self._lbl_uninst_hint.setStyleSheet(f'color:{C["text3"]};font-size:11px;font-family:{MONO};')
        lay.addWidget(self._lbl_uninst_hint)
        lay.addSpacing(10)

        self.uninstall_search = QLineEdit()
        self.uninstall_search.setPlaceholderText(_t('placeholder_filter', 'Filter apps...'))
        self.uninstall_search.textChanged.connect(self._filter_uninstall)
        lay.addWidget(self.uninstall_search)
        lay.addSpacing(8)

        self.uninstall_table = QTableWidget(0, 4)
        self.uninstall_table.setHorizontalHeaderLabels([
            _t('col_name','NAME'), _t('col_version','VERSION'),
            _t('col_size','SIZE'), _t('col_source','SOURCE')
        ])
        self.uninstall_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.uninstall_table.verticalHeader().setVisible(False)
        self.uninstall_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.uninstall_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.uninstall_table.setAlternatingRowColors(True)
        lay.addWidget(self.uninstall_table, 1)

        btn_row = QHBoxLayout()
        un_btn = _btn(f"✕  {_t('btn_uninstall','UNINSTALL SELECTED')}", 'red')
        un_btn.clicked.connect(self._do_uninstall)
        btn_row.addWidget(un_btn)
        btn_row.addStretch()
        lay.addSpacing(10)
        lay.addLayout(btn_row)

        self.uninstall_log = QTextEdit()
        self.uninstall_log.setReadOnly(True)
        self.uninstall_log.setMinimumHeight(60)
        self.uninstall_log.setMaximumHeight(110)
        self.uninstall_log.setPlaceholderText('  → Select an app and click Uninstall...')
        lay.addWidget(self.uninstall_log)
        return w

    # ─────────────────────────────────────────────────────────
    # REDESIGNED HISTORY LOG
    # ─────────────────────────────────────────────────────────
    def _build_log(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(0)

        hdr = QHBoxLayout()
        self._lbl_history_title = QLabel(_t('history_title', 'HISTORY LOG'))
        self._lbl_history_title.setStyleSheet(
            f'color:{C["text"]};font-size:12px;font-weight:700;'
            f'letter-spacing:5px;font-family:{MONO};'
        )
        self._history_clr_btn = _btn(f"✕ {_t('btn_clear','CLEAR')}", 'red', small=True)
        self._history_clr_btn.clicked.connect(self._clear_log)
        hdr.addWidget(self._lbl_history_title); hdr.addStretch(); hdr.addWidget(self._history_clr_btn)
        lay.addLayout(hdr)
        lay.addWidget(_divider())
        lay.addSpacing(14)

        self.log_table = QTableWidget(0, 5)
        self.log_table.setHorizontalHeaderLabels([
            _t('col_time','TIME'), _t('col_disk_before','BEFORE'),
            _t('col_disk_after','AFTER'), _t('col_freed','FREED'),
            _t('col_detail','DETAIL')
        ])
        hdr2 = self.log_table.horizontalHeader()
        hdr2.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr2.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr2.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr2.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr2.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setWordWrap(True)
        lay.addWidget(self.log_table, 1)
        return w

    # ─────────────────────────────────────────────────────────
    # REDESIGNED ROLLBACK
    # ─────────────────────────────────────────────────────────
    def _build_rollback(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(0)

        hdr = QHBoxLayout()
        self._lbl_rollback_title = QLabel(_t('rollback_title', 'ROLLBACK LIST'))
        self._lbl_rollback_title.setStyleSheet(
            f'color:{C["text"]};font-size:12px;font-weight:700;'
            f'letter-spacing:5px;font-family:{MONO};'
        )
        self._rollback_clr_btn = _btn(f"✕ {_t('btn_clear','CLEAR')}", 'red', small=True)
        self._rollback_clr_btn.clicked.connect(self._clear_rollback)
        self._rollback_folder_btn = _btn(
            f"📁 {_t('rollback_open_folder', 'OPEN LOG FOLDER')}", 'cyan', small=True
        )
        self._rollback_folder_btn.clicked.connect(self._open_logs_folder)
        hdr.addWidget(self._lbl_rollback_title)
        hdr.addStretch()
        hdr.addWidget(self._rollback_folder_btn)
        hdr.addWidget(self._rollback_clr_btn)
        lay.addLayout(hdr)
        lay.addWidget(_divider())
        lay.addSpacing(8)

        self._lbl_rollback_hint = QLabel(_t(
            'rollback_hint',
            'These entries are a record of what was removed — files are not kept for restore.',
        ))
        self._lbl_rollback_hint.setStyleSheet(f'color:{C["text3"]};font-size:11px;font-family:{MONO};')
        self._lbl_rollback_hint.setWordWrap(True)
        lay.addWidget(self._lbl_rollback_hint)
        lay.addSpacing(12)

        self.rollback_table = QTableWidget(0, 4)
        self.rollback_table.setHorizontalHeaderLabels([
            _t('col_time','TIME'), _t('col_type','TYPE'),
            _t('col_size','SIZE'), _t('col_path_note','PATH / NOTE')
        ])
        self.rollback_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.rollback_table.verticalHeader().setVisible(False)
        self.rollback_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rollback_table.setAlternatingRowColors(True)
        lay.addWidget(self.rollback_table, 1)
        return w

    # ─────────────────────────────────────────────────────────
    # REDESIGNED SYSTEM BOOSTER
    # ─────────────────────────────────────────────────────────
    def _build_browser_turbo(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(0)

        outer.addWidget(self._page_header(
            _t('booster_title', 'SYSTEM BOOSTER'),
            _t('booster_sub', 'Free RAM · optimize CPU · clear disk cache · tune system'),
            store_key='booster'
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('border:none;background:transparent;')
        sw = QWidget()
        lay = QVBoxLayout(sw)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(10)

        if not hasattr(self, '_boost_lbls'): self._boost_lbls = {}
        def _boost_card(title, color, desc, btn_label, btn_color, slot):
            f = QFrame()
            f.setStyleSheet(
                f'QFrame{{background:{C["bg2"]};'
                f'border-top:1px solid {C["border2"]};'
                f'border-right:1px solid {C["border2"]};'
                f'border-bottom:1px solid {C["border2"]};'
                f'border-left:3px solid {color}60;'
                f'border-radius:3px;}}'
                f'QFrame:hover{{background:{C["bg3"]};}}'
            )
            hl = QHBoxLayout(f); hl.setContentsMargins(18, 16, 18, 16); hl.setSpacing(18)
            vl = QVBoxLayout(); vl.setSpacing(5)
            t = QLabel(title)
            t.setStyleSheet(
                f'color:{color};font-size:11px;letter-spacing:3px;'
                f'font-family:{MONO};font-weight:700;'
            )
            d = QLabel(desc)
            d.setStyleSheet(f'color:{C["text3"]};font-size:11px;')
            d.setWordWrap(True)
            vl.addWidget(t); vl.addWidget(d)
            b = _btn(btn_label, btn_color, small=True)
            b.clicked.connect(slot)
            _key = getattr(slot, '__name__', str(id(slot)))
            self._boost_lbls[_key] = (t, d, b)  # lưu cả button để retranslate
            hl.addLayout(vl, 1); hl.addWidget(b)
            return f

        lay.addWidget(_boost_card(
            f"⬡  {_t('booster_free_ram','FREE RAM')}", C['cyan'],
            _t('ram_desc','Drop page cache, reclaim unused memory. Instant RAM boost without rebooting.'),
            f"▶  {_t('btn_free_now','FREE NOW')}", 'cyan', self._boost_free_ram
        ))

        # CPU Priority card (complex — built manually)
        f_cpu = QFrame()
        f_cpu.setStyleSheet(
            f'QFrame{{background:{C["bg2"]};'
            f'border-top:1px solid {C["border2"]};'
            f'border-right:1px solid {C["border2"]};'
            f'border-bottom:1px solid {C["border2"]};'
            f'border-left:3px solid {C["yellow"]}60;'
            f'border-radius:3px;}}'
            f'QFrame:hover{{background:{C["bg3"]};}}'
        )
        hl_cpu = QHBoxLayout(f_cpu); hl_cpu.setContentsMargins(18, 16, 18, 16); hl_cpu.setSpacing(18)
        vl_cpu = QVBoxLayout(); vl_cpu.setSpacing(5)
        self._lbl_t_cpu = QLabel(f"⚡  {_t('booster_cpu','CPU PRIORITY MODE')}")
        self._lbl_t_cpu.setStyleSheet(
            f'color:{C["yellow"]};font-size:11px;letter-spacing:3px;'
            f'font-family:{MONO};font-weight:700;'
        )
        self._lbl_d_cpu = QLabel(_t('cpu_desc','Freeze or throttle background bloat. Give foreground app 100% CPU resources.'))
        self._lbl_d_cpu.setStyleSheet(f'color:{C["text3"]};font-size:11px;')
        self._lbl_d_cpu.setWordWrap(True)
        vl_cpu.addWidget(self._lbl_t_cpu); vl_cpu.addWidget(self._lbl_d_cpu)
        btn_row_cpu = QHBoxLayout(); btn_row_cpu.setSpacing(8)
        self._game_btn = _btn(f"  {_t('btn_game_mode','GAME MODE')}", 'red', small=True)
        self._game_btn.setIcon(_make_icon(_icon_booster, size=18, color=C["red"]))
        self._game_btn.setIconSize(QSize(20, 20))
        self._game_btn.setCheckable(True)
        self._game_btn.setToolTip(_t('game_tooltip','Throttle background bloat — no suspend, no deadlock'))
        self._game_btn.clicked.connect(self._toggle_game_mode)
        self._eco_btn = _btn(f"  {_t('btn_eco_mode','ECO MODE')}", 'green', small=True)
        self._eco_btn.setIcon(_make_icon(_icon_booster, size=18, color=C["green"]))
        self._eco_btn.setIconSize(QSize(20, 20))
        self._eco_btn.setCheckable(True)
        self._eco_btn.setToolTip(_t('eco_tooltip','Lower all background task priority to IDLE'))
        self._eco_btn.clicked.connect(self._toggle_eco_mode)
        btn_row_cpu.addWidget(self._game_btn)
        btn_row_cpu.addWidget(self._eco_btn)
        self._smart_btn = _btn(f"  {_t('btn_smart_boost','SMART BOOST')}", 'purple', small=True)
        self._smart_btn.setIcon(_make_icon(_icon_booster, size=18, color=C["purple"]))
        self._smart_btn.setIconSize(QSize(20, 20))
        self._smart_btn.setCheckable(True)
        self._smart_btn.setToolTip(_t('smart_tooltip','Auto-detect PC tier and apply optimal boost'))
        self._smart_btn.clicked.connect(self._toggle_smart_boost)
        btn_row_cpu.addWidget(self._smart_btn)
        btn_row_cpu.addStretch()
        hl_cpu.addLayout(vl_cpu, 1); hl_cpu.addLayout(btn_row_cpu)
        lay.addWidget(f_cpu)

        lay.addWidget(_boost_card(
            f"◈  {_t('booster_disk','DISK CACHE CLEAR')}", C['cyan'],
            _t('disk_desc','Clear GPU/shader cache, temp files. Frees VRAM, fixes video stutter & WebGL glitches.'),
            f"◈  {_t('btn_clear_cache','CLEAR CACHE')}", 'cyan', self._clear_gpu_cache
        ))

        lay.addWidget(_boost_card(
            f"⬡  {_t('booster_mem_tune','MEMORY TUNE')}", C['green'],
            _t('mem_tune_desc','Linux: set swappiness=10 + compact memory. Windows: flush standby list & optimize VM.'),
            f"▶  {_t('btn_tune_now','TUNE NOW')}", 'green', self._boost_memory_tune
        ))

        lay.addWidget(_boost_card(
            f"✕  {_t('booster_kill_bloat','KILL BACKGROUND BLOAT')}", C['red'],
            _t('kill_desc','Find and kill zombie, sleeping & high-memory idle processes safely.'),
            f"✕  {_t('btn_kill_bloat','KILL BLOAT')}", 'red', self._boost_kill_bloat
        ))

        lay.addStretch()
        scroll.setWidget(sw)
        outer.addWidget(scroll, 1)
        outer.addSpacing(10)

        self._lbl_booster_output_sec = _lbl_section(_t('lbl_output', 'OUTPUT LOG'))
        outer.addWidget(self._lbl_booster_output_sec)
        self._browser_log = QTextEdit()
        self._browser_log.setReadOnly(True)
        self._browser_log.setMinimumHeight(110)
        self._browser_log.setMaximumHeight(210)
        self._browser_log.setPlaceholderText(_t('lbl_output', 'OUTPUT'))
        outer.addWidget(self._browser_log)
        return w

    # ═══════════════════════════════════════════════════════════
    # ALL LOGIC BELOW IS UNCHANGED FROM ORIGINAL
    # ═══════════════════════════════════════════════════════════


    def _start_sysinfo(self):
        self._si_worker = SysInfoWorker()
        self._si_worker.snapshot.connect(self._on_snapshot)
        self._si_worker.start()

    def _refresh_now(self):
        import time as _time
        now = _time.time()
        # Debounce: chặn spam, cooldown 2 giây
        if now - self._last_refresh_time < 2.0:
            return
        self._last_refresh_time = now

        # Khóa nút trong lúc đang refresh
        if hasattr(self, '_ref_btn'):
            self._ref_btn.setEnabled(False)
            self._ref_btn.setText('...')

        try:
            s = get_snapshot(interval=0.1)
            self._on_snapshot(s)
        except:
            pass
        finally:
            # Mở khóa lại sau 2s (khớp với cooldown)
            if hasattr(self, '_ref_btn'):
                QTimer.singleShot(2000, lambda: (
                    self._ref_btn.setEnabled(True),
                    self._ref_btn.setText(f"↻  {_t('btn_refresh','REFRESH')}")
                ))

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
            f'color:{C[col]};font-size:34px;font-weight:700;font-family:{MONO};'
        )
        self.health_sub.setText(' · '.join(issues) if issues else '✓ System healthy')
        self.health_sub.setStyleSheet(
            f'color:{C[col] if issues else C["green"]};font-size:11px;font-family:{MONO};'
        )

        self._charts['cpu'].push(s.cpu_percent)
        self._charts['ram'].push(s.ram_percent)

        if s.disks:
            d = s.disks[0]
            self.disk_ring.set_percent(d.percent)
            self.disk_detail_lbl.setText(f'{fmt_size(d.used)} / {fmt_size(d.total)}')

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
                    item.setForeground(QColor(C['text3']))
                self.proc_table.setItem(row, col_i, item)

        self.disk_table.setRowCount(0)
        for disk in s.disks:
            row = self.disk_table.rowCount()
            self.disk_table.insertRow(row)
            self.disk_table.setRowHeight(row, 32)
            pct     = disk.percent
            col_pct = C['red'] if pct > 90 else C['yellow'] if pct > 75 else C['cyan']

            full_path = disk.path
            if len(full_path) > 14 and full_path.startswith('/'):
                parts = [p for p in full_path.split('/') if p]
                disp  = '/' + '/'.join(parts[-2:]) if len(parts) >= 2 else full_path
            else:
                disp = full_path

            it0 = QTableWidgetItem(disp)
            it0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            it0.setToolTip(full_path)
            self.disk_table.setItem(row, 0, it0)

            for ci, val in enumerate([fmt_size(disk.used), fmt_size(disk.free)], 1):
                it = QTableWidgetItem(val)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.disk_table.setItem(row, ci, it)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(pct))
            bar.setTextVisible(True)
            bar.setFormat(f'{pct:.0f}%')
            bar.setFixedHeight(14)
            bar.setStyleSheet(
                f'QProgressBar {{'
                f'  background:{C["bg3"]}; border:none; border-radius:2px;'
                f'  color:{col_pct}; font-size:10px; font-weight:700;'
                f'  font-family:{MONO}; text-align:center;'
                f'}}'
                f'QProgressBar::chunk {{'
                f'  background:qlineargradient(x1:0,y1:0,x2:1,y2:0,'
                f'    stop:0 {col_pct}80, stop:1 {col_pct}cc);'
                f'  border-radius:2px;'
                f'}}'
            )
            cw = QWidget()
            cl = QHBoxLayout(cw)
            cl.setContentsMargins(6, 7, 6, 7)
            cl.addWidget(bar)
            self.disk_table.setCellWidget(row, 3, cw)

    def _start_clock(self):
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(
            lambda: self.clock_lbl.setText(datetime.now().strftime('%H:%M:%S'))
        )
        self._clock_timer.start(1000)

    def _one_click_fix(self):
        self.oneclick_btn.setEnabled(False)
        self.oneclick_log.setText('Running...')
        import subprocess as _sp

        self._oneclick_worker = _OneClickWorker()
        self._oneclick_worker.done.connect(self._on_oneclick_done)
        self._oneclick_worker.start()

    def _on_oneclick_done(self, summary, success):
        self.oneclick_btn.setEnabled(True)
        col = C['green'] if success else C['yellow']
        self.oneclick_log.setText(summary)
        self.oneclick_log.setStyleSheet(f'color:{col};font-size:11px;font-family:{MONO};')
        QTimer.singleShot(3000, self._refresh_now)

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
                QMessageBox.warning(self, _t('kill_failed','Kill failed'), str(e))
        if killed:
            QMessageBox.information(self, 'Done', f'Terminated: {", ".join(killed)}')
            QTimer.singleShot(2000, self._refresh_now)

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
        msg.setWindowTitle(_t('confirm_clean','Confirm Clean'))
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

    def _run_scanner(self):
        if hasattr(self, '_scan_running') and self._scan_running:
            return
        self._scan_running = True
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(f"⟳  {_t('btn_run_scan','SCANNING...')}")
        self.fix_btn.setEnabled(False)
        self.opt_terminal.clear()
        self.scan_table.setRowCount(0)
        self._scan_results = []

        self._scan_worker = _ScanWorker()
        self._scan_worker.log.connect(self._on_opt_log)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.start()

    def _on_scan_done(self, results, net_results):
        self._scan_running = False
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText(f"⬡  {_t('btn_run_scan','RUN DEEP SCAN')}")
        self._scan_results = results
        sev_col = {'critical': C['red'], 'high': C['yellow'], 'medium': C['cyan'], 'info': C['text3']}

        # Kết quả quét file cũ
        for r in results:
            row = self.scan_table.rowCount()
            self.scan_table.insertRow(row)
            for i, val in enumerate([r.severity.upper(), r.category, r.path, r.detail]):
                ti = QTableWidgetItem(val)
                if i == 0:
                    ti.setForeground(QColor(sev_col.get(r.severity, C['text'])))
                self.scan_table.setItem(row, i, ti)
            self.scan_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)

        # Kết quả quét mạng (MỚI)
        for net in net_results:
            if net.suspicious:
                row = self.scan_table.rowCount()
                self.scan_table.insertRow(row)
                ti_sev = QTableWidgetItem('WARNING')
                ti_sev.setForeground(QColor(C['yellow']))
                self.scan_table.setItem(row, 0, ti_sev)
                self.scan_table.setItem(row, 1, QTableWidgetItem('NETWORK'))
                self.scan_table.setItem(row, 2, QTableWidgetItem(f"{net.name} (PID: {net.pid})"))
                self.scan_table.setItem(row, 3, QTableWidgetItem(
                    f"Kết nối tới: {net.remote_ip}:{net.remote_port} — {net.reason}"))

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
        msg.setWindowTitle(_t('confirm_autofix','Auto-Fix'))
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
        cols = {'ok': C['green'], 'warn': C['yellow'], 'err': C['red'], 'head': C['cyan'], 'info': C['text3']}
        col = cols.get(level, C['text'])
        self.opt_terminal.append(f'<span style="color:{col};font-family:monospace;">{msg}</span>')
        self.opt_terminal.moveCursor(QTextCursor.MoveOperation.End)

    def _load_uninstall(self):
        # Đã có guard isRunning() — thêm button lock để user biết đang chạy
        if getattr(self, '_uninstall_worker', None) and self._uninstall_worker.isRunning():
            return
        if hasattr(self, '_uninst_ref_btn'):
            self._uninst_ref_btn.setEnabled(False)
            self._uninst_ref_btn.setText('...')
        self.uninstall_table.setRowCount(0)
        self.uninstall_log.clear()
        self.uninstall_log.append(
            f'<span style="color:{C["cyan"]}">  ⟳  Scanning installed apps...</span>'
        )

        self._uninstall_worker = _UninstallWorker()
        self._uninstall_worker.finished.connect(self._on_uninstall_loaded)
        self._uninstall_worker.start()

    def _on_uninstall_loaded(self, apps):
        self._all_apps = apps
        self._populate_uninstall(apps)
        self.uninstall_log.clear()
        self.uninstall_log.append(
            f'<span style="color:{C["text3"]}">  Found {len(apps)} apps</span>'
        )
        # Mở khóa nút refresh
        if hasattr(self, '_uninst_ref_btn'):
            self._uninst_ref_btn.setEnabled(True)
            self._uninst_ref_btn.setText(f"↻ {_t('btn_refresh','REFRESH')}")

    def _populate_uninstall(self, apps):
        self.uninstall_table.setRowCount(0)
        for app in apps:
            row = self.uninstall_table.rowCount()
            self.uninstall_table.insertRow(row)
            sz = f'{app.size_mb:.1f} MB' if app.size_mb > 0 else '—'
            src_col = {
                'pacman': C['cyan'], 'apt': C['yellow'], 'dnf': C['green'],
                'flatpak': C['purple'], 'winget': C['cyan'],
                'registry': C['text3'], 'wmic': C['text3'],
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
        msg.setWindowTitle(_t('confirm_uninstall','Uninstall'))
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(f'Uninstall {len(apps)} app(s)?\n' + '\n'.join(f'• {a.name}' for a in apps))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() != QMessageBox.StandardButton.Yes: return
        self.uninstall_log.clear()
        ui_opened = False
        for app in apps:
            _col_map = {'ok': C['green'], 'err': C['red']}
            def _log_u(m, l, _cm=_col_map):
                col = _cm.get(l, C['text3'])
                self.uninstall_log.append(f'<span style="color:{col};">{m}</span>')
            result = uninstall_app(app, _log_u)
            if result == 'UI_OPENED':
                ui_opened = True
        if not ui_opened:
            QTimer.singleShot(1500, self._load_uninstall)

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

    def _open_logs_folder(self):
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR.resolve())))

    def _hide_to_tray(self, event, notify=True):
        event.ignore()
        self.hide()
        if hasattr(self, '_si_worker'):
            self._si_worker.paused = True
        if hasattr(self, '_clock_timer'):
            self._clock_timer.stop()
        if notify and hasattr(self, 'tray'):
            self.tray.showMessage(
                'CyberClean',
                _t('tray_running_bg', 'Running in background. Auto-clean every 6h.'),
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def _reset_close_preference(self):
        self._settings.remove('autoclean_close_behavior')
        self._settings.sync()
        QMessageBox.information(
            self,
            _t('close_pref_reset_title', 'Preference reset'),
            _t('close_pref_reset_body', 'You will be asked again the next time you close the window.'),
        )

    class BoosterWorker(QThread):
        log_signal  = pyqtSignal(str, str)
        done_signal = pyqtSignal(object)
        def __init__(self, action_func):
            super().__init__()
            self.action_func = action_func
        def run(self):
            result = self.action_func(lambda msg, level='text': self.log_signal.emit(msg, level))
            self.done_signal.emit(result)

    def _run_booster_action(self, func, on_done=None):
        if getattr(self, '_booster_worker', None) and self._booster_worker.isRunning():
            self._blog('  ! Please wait for the current task to finish...', 'warn')
            return
        self._booster_worker = self.BoosterWorker(func)
        self._booster_worker.log_signal.connect(self._blog)
        if on_done:
            self._booster_worker.done_signal.connect(on_done)
        self._booster_worker.start()

    def _blog(self, msg, col='text'):
        colors = {
            'ok': C['green'], 'err': C['red'], 'warn': C['yellow'],
            'head': C['cyan'], 'text': C['text']
        }
        self._browser_log.append(f'<span style="color:{colors.get(col, C["text"])}">{msg}</span>')

    def _clear_gpu_cache(self):
        self._run_booster_action(clear_disk_cache)

    def _toggle_game_mode(self):
        if not hasattr(self, '_game_frozen_pids'):   self._game_frozen_pids   = {}
        if not hasattr(self, '_game_active'):        self._game_active        = False
        if not hasattr(self, '_game_transitioning'): self._game_transitioning = False

        if self._game_transitioning:
            self._game_btn.setChecked(self._game_active)
            return

        self._game_transitioning = True

        if self._game_btn.isChecked():
            self._game_btn.setText(f"■  {_t('btn_active_restore','ACTIVE — CLICK TO RESTORE')}")
            self._eco_btn.setEnabled(False)
            self._game_btn.setEnabled(False)
            self._game_active = True

            # Dừng polling CPU/RAM khi đang game — giảm overhead, tránh giật chuột
            if hasattr(self, '_si_worker'):
                self._si_worker.paused = True

            def _on_game_on(saved):
                self._game_frozen_pids   = saved or {}
                self._game_transitioning = False
                self._game_btn.setEnabled(True)

            self._run_booster_action(game_mode_on, on_done=_on_game_on)
        else:
            self._game_btn.setText(f"▶  {_t('btn_activate','ACTIVATE')}")
            self._eco_btn.setEnabled(True)
            self._game_btn.setEnabled(False)
            self._game_active = False

            # Resume polling khi thoát Game Mode (chỉ active nếu đang ở dashboard)
            if hasattr(self, '_si_worker'):
                self._si_worker.paused = (self.stack.currentIndex() != 0)

            saved = self._game_frozen_pids
            def _do_off(log): game_mode_off(saved, log)
            def _on_game_off(_):
                self._game_frozen_pids   = {}
                self._game_transitioning = False
                self._game_btn.setEnabled(True)

            self._run_booster_action(_do_off, on_done=_on_game_off)

    def _toggle_eco_mode(self):
        if not hasattr(self, '_eco_saved'):        self._eco_saved        = {}
        if not hasattr(self, '_eco_active'):       self._eco_active       = False
        if not hasattr(self, '_eco_transitioning'): self._eco_transitioning = False

        if self._eco_transitioning:
            self._eco_btn.setChecked(self._eco_active)
            return

        self._eco_transitioning = True

        if self._eco_btn.isChecked():
            self._eco_btn.setText(f"■  {_t('btn_active_restore','ACTIVE — CLICK TO RESTORE')}")
            self._game_btn.setEnabled(False)
            self._eco_btn.setEnabled(False)
            self._eco_active = True

            def _on_eco_on(saved):
                self._eco_saved        = saved or {}
                self._eco_transitioning = False
                self._eco_btn.setEnabled(True)
                if not saved:
                    self._blog("  ~ Eco Mode: Linux non-root — CPU affinity only, nice() skipped", "warn")

            self._run_booster_action(eco_mode_on, on_done=_on_eco_on)
        else:
            self._eco_btn.setText(f"▶  {_t('btn_activate','ACTIVATE')}")
            self._game_btn.setEnabled(True)
            self._eco_btn.setEnabled(False)
            self._eco_active = False

            saved = self._eco_saved
            def _do_off(log): eco_mode_off(saved, log)
            def _on_eco_off(_):
                self._eco_saved        = {}
                self._eco_transitioning = False
                self._eco_btn.setEnabled(True)

            self._run_booster_action(_do_off, on_done=_on_eco_off)

    def _boost_free_ram(self):
        self._run_booster_action(free_ram)

    def _boost_memory_tune(self):
        def _on_tune_done(result):
            if result and result.rollback:
                orig = result.rollback[0].get("originals", {})
                if orig:
                    self._mem_tune_originals = orig
                    self._blog("  i Kernel params will be restored on app exit", "ok")
        self._run_booster_action(memory_tune, on_done=_on_tune_done)

    def _boost_kill_bloat(self):
        self._run_booster_action(kill_bloat)

    def _show_polkit_warning(self):
        if hasattr(self, '_polkit_warned'): return
        self._polkit_warned = True
        if not HAS_POLKIT:
            msg = QMessageBox(self)
            msg.setWindowTitle(_t('setup_required','Setup Required'))
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(
                'Polkit not configured. Root-level cleaning needs setup.\n'
                'Option 1: bash ~/CyberClean/install.sh\n'
                'Option 2: sudo python3 ~/CyberClean/main.py'
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.setStyleSheet(f'background:{C["bg2"]};color:{C["text"]};font-family:monospace;')
            msg.exec()

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        _base = getattr(sys, '_MEIPASS', Path(__file__).parent)
        _icon_file = Path(_base) / 'assets' / 'logo.png'
        if _icon_file.exists():
            self.tray.setIcon(QIcon(str(_icon_file)))
        else:
            px = QPixmap(16, 16); px.fill(QColor(C['cyan']))
            self.tray.setIcon(QIcon(px))
        self.tray.setToolTip(f'CyberClean v{__version__}')

        self.tray_menu = QMenu(self)
        self.tray_menu.setStyleSheet(
            f'QMenu{{background:{C["bg2"]};color:{C["text"]};border:1px solid {C["border2"]};'
            f'font-family:monospace;font-size:11px;padding:4px;}}'
            f'QMenu::item{{padding:7px 20px;border-radius:2px;}}'
            f'QMenu::item:selected{{background:{C["cyan"]}20;color:{C["cyan"]};}}'
        )
        show_act  = QAction('◈  Show CyberClean', self)
        show_act.triggered.connect(self._show_from_tray)
        clean_act = QAction('⚡  Quick Clean', self)
        clean_act.triggered.connect(lambda: (self._show_from_tray(), self._nav('clean')))
        self._tray_update_act = QAction(_t('tray_view_update', '⬆  View update…'), self)
        self._tray_update_act.setVisible(False)
        self._tray_update_act.triggered.connect(
            lambda: (self._show_from_tray(), self._open_update_dialog())
        )
        self._tray_reset_close_act = QAction(
            _t('tray_reset_close_pref', 'Reset close-window preference…'), self
        )
        self._tray_reset_close_act.triggered.connect(self._reset_close_preference)

        quit_act  = QAction('✕  Quit', self)

        def _quit():
            self._shutdown()
            QApplication.quit()
        quit_act.triggered.connect(_quit)

        self.tray_menu.addAction(show_act)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(clean_act)
        self.tray_menu.addAction(self._tray_update_act)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self._tray_reset_close_act)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(quit_act)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def closeEvent(self, event):
        if not event.spontaneous():
            self._shutdown(); event.accept(); return

        tray_ok = QSystemTrayIcon.isSystemTrayAvailable() and hasattr(self, 'tray')
        is_auto = hasattr(self, '_auto_clean_timer') and self._auto_clean_timer.isActive()

        if not is_auto or not tray_ok:
            self._shutdown(); event.accept(); return

        import platform as _plat
        default_behavior = 'tray' if _plat.system() == 'Windows' else 'ask'
        behavior = self._settings.value('autoclean_close_behavior', default_behavior)

        # Windows UX: never show close dialog, behave like cleaner apps.
        # Users can still fully quit from tray menu (Quit).
        if _plat.system() == 'Windows':
            if behavior == 'quit':
                self._shutdown(); event.accept(); return
            self._hide_to_tray(event, notify=False)
            return

        if behavior == 'tray':
            self._hide_to_tray(event, notify=True); return
        if behavior == 'quit':
            self._shutdown(); event.accept(); return

        # ── Custom styled close dialog ─────────────────────────────────
        dlg = QDialog(self)
        dlg.setWindowTitle(_t('confirm_close_title', 'Background Mode'))
        dlg.setMinimumWidth(420)
        dlg.setModal(True)
        dlg.setStyleSheet(
            f"QDialog{{background:{C['bg2']};color:{C['text']};}}"
            f"QLabel{{color:{C['text']};font-family:{MONO};font-size:12px;}}"
            f"QCheckBox{{color:{C['text3']};font-family:{MONO};font-size:11px;}}"
            f"QCheckBox::indicator{{width:13px;height:13px;border:1px solid {C['border3']};"
            f"border-radius:2px;background:{C['bg3']};}}"
            f"QCheckBox::indicator:checked{{background:{C['cyan']};border-color:{C['cyan']};}}"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        # Icon + title row
        title_row = QHBoxLayout()
        icon_lbl = QLabel('◈')
        icon_lbl.setStyleSheet(f'color:{C["cyan"]};font-size:22px;font-family:{MONO};')
        title_row.addWidget(icon_lbl)
        title_lbl = QLabel(_t('confirm_close_title', 'Background Mode').upper())
        title_lbl.setStyleSheet(
            f'color:{C["cyan"]};font-size:13px;letter-spacing:2px;font-family:{MONO};font-weight:bold;'
        )
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        lay.addLayout(title_row)

        # Divider
        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f'background:{C["border3"]};max-height:1px;border:none;')
        lay.addWidget(div)

        # Message
        msg_text = _t('confirm_close_msg',
            'Auto-clean (6h) is enabled.\n\n'
            '\u2022 YES: Hide to system tray and keep running\n'
            '\u2022 NO: Quit completely (stops background auto-clean)')
        msg_lbl = QLabel(msg_text)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(f'color:{C["text2"]};font-size:12px;font-family:{MONO};line-height:1.6;')
        lay.addWidget(msg_lbl)

        # Remember checkbox
        cb = QCheckBox(_t('remember_close_choice', 'Remember — skip this dialog next time'))
        cb.setChecked(True)
        lay.addWidget(cb)

        lay.addSpacing(4)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_quit = QPushButton(_t('close_btn_quit', 'QUIT'))
        btn_quit.setStyleSheet(
            f'background:transparent;color:{C["text3"]};border:1px solid {C["border3"]};'
            f'padding:7px 18px;font-family:{MONO};font-size:11px;border-radius:3px;'
        )
        btn_tray = QPushButton(_t('close_btn_tray', 'HIDE TO TRAY'))
        btn_tray.setStyleSheet(
            f'background:{C["cyan"]}22;color:{C["cyan"]};border:1px solid {C["cyan"]};'
            f'padding:7px 22px;font-family:{MONO};font-size:11px;font-weight:bold;border-radius:3px;'
        )
        btn_row.addWidget(btn_quit)
        btn_row.addWidget(btn_tray)
        lay.addLayout(btn_row)

        _choice = ['tray']

        def _go_tray():
            _choice[0] = 'tray'; dlg.accept()

        def _go_quit():
            _choice[0] = 'quit'; dlg.accept()

        btn_tray.clicked.connect(_go_tray)
        btn_quit.clicked.connect(_go_quit)
        btn_tray.setDefault(True)

        dlg.exec()

        choice = _choice[0]
        if cb.isChecked():
            self._settings.setValue('autoclean_close_behavior', choice)
            self._settings.sync()

        if choice == 'tray':
            self._hide_to_tray(event, notify=True)
        else:
            self._shutdown(); event.accept()

    def _show_from_tray(self):
        self.show(); self.raise_(); self.activateWindow()
        if hasattr(self, '_si_worker'):
            self._si_worker.paused = (self.stack.currentIndex() != 0)
        if hasattr(self, '_clock_timer'):
            self._clock_timer.start(1000)

    def _change_language(self, index):
        code = list(SUPPORTED_LANGS.keys())[index]
        if code == T.lang:
            return
        T.set_lang(code)
        self._retranslate_ui()

    def _retranslate_ui(self):
        """Cập nhật TẤT CẢ text theo ngôn ngữ hiện tại — không cần restart."""
        # ── Sidebar nav buttons ──────────────────────────────
        for (pid, icon_name, label), btn in zip(self.NAV_ITEMS, self.nav_btns.values()):
            btn.set_label(label)

        # ── Header ───────────────────────────────────────────
        if hasattr(self, '_os_info_lbl'):
            self._os_info_lbl.setText(
                f'{OS.upper()}  ·  '
                f"{PKG_MANAGER.upper() if PKG_MANAGER else _t('header_cross','CROSS-PLATFORM')}"
                f"  ·  {_t('header_subtitle','SMART DISK MANAGER')}"
            )

        # ── Page headers (title + subtitle) ──────────────────
        if hasattr(self, '_page_hdr_lbls'):
            _ph = self._page_hdr_lbls
            if 'clean' in _ph:
                _ph['clean'][0].setText(_t('clean_targets', 'CLEAN TARGETS'))
                if _ph['clean'][1]: _ph['clean'][1].setText(_t('clean_subtitle', 'Select targets · Dry-run to preview · Clean to execute'))
            if 'scanner' in _ph:
                _ph['scanner'][0].setText(_t('scanner_title', 'SECURITY SCANNER'))
            if 'booster' in _ph:
                _ph['booster'][0].setText(_t('booster_title', 'SYSTEM BOOSTER'))
                if _ph['booster'][1]: _ph['booster'][1].setText(_t('booster_sub', 'Free RAM · optimize CPU · clear disk cache · tune system'))

        # ── Dashboard ─────────────────────────────────────────
        if hasattr(self, '_lbl_sys_overview'):
            self._lbl_sys_overview.setText(_t('sys_overview', 'SYSTEM OVERVIEW'))
        if hasattr(self, '_ref_btn'):
            self._ref_btn.setText(f"↻  {_t('btn_refresh','REFRESH')}")
        if hasattr(self, '_lbl_health_sec'):
            self._lbl_health_sec.setText(_t('lbl_health', 'HEALTH SCORE'))
        if hasattr(self, '_lbl_oneclick_sec'):
            self._lbl_oneclick_sec.setText(_t('lbl_oneclick', 'ONE-CLICK OPTIMIZE'))
        if hasattr(self, '_lbl_oc_desc'):
            self._lbl_oc_desc.setText(
                'Flush DNS  ·  Clear TEMP  ·  Drop cache  ·  TRIM SSD'
                if IS_WINDOWS else
                'Drop cache  ·  Tune swap  ·  TRIM SSD  ·  Clean journal'
            )
        if hasattr(self, 'oneclick_btn'):
            self.oneclick_btn.setText(f"⚡  {_t('btn_optimize','OPTIMIZE NOW')}")
        if hasattr(self, '_lbl_top_proc_sec'):
            self._lbl_top_proc_sec.setText(_t('lbl_top_proc', 'TOP PROCESSES'))
        if hasattr(self, '_lbl_disk_sec'):
            self._lbl_disk_sec.setText(_t('lbl_disk', 'DISK USAGE'))
        for sid, key, default in [('temp','lbl_temperature','TEMPERATURE'),('swap','lbl_swap','SWAP')]:
            if hasattr(self, '_stat_cards') and sid in self._stat_cards:
                self._stat_cards[sid].lbl_name.setText(_t(key, default))
        if hasattr(self, 'proc_table'):
            self.proc_table.setHorizontalHeaderLabels([
                _t('col_pid','PID'), _t('col_name','NAME'),
                _t('col_cpu','CPU %'), _t('col_mem','MEM %')
            ])
        if hasattr(self, 'disk_table'):
            self.disk_table.setHorizontalHeaderLabels([
                _t('col_drive','Drive'), '▲ Used', '▽ Free', '%'
            ])

        # ── Clean tab ─────────────────────────────────────────
        if hasattr(self, '_dry_btn'):
            self._dry_btn.setText(f"⬡  {_t('btn_dryrun','DRY-RUN')}")
        if hasattr(self, '_clean_btn'):
            self._clean_btn.setText(f"⚡  {_t('btn_clean_now','CLEAN NOW')}")
        if hasattr(self, '_all_btn'):
            self._all_btn.setText(f"☑  {_t('btn_all','ALL')}")
        if hasattr(self, '_none_btn'):
            self._none_btn.setText(f"☐  {_t('btn_none','NONE')}")
        if hasattr(self, '_lbl_clean_targets_sec'):
            self._lbl_clean_targets_sec.setText(_t('clean_targets', 'TARGETS'))
        if hasattr(self, '_lbl_clean_output_sec'):
            self._lbl_clean_output_sec.setText(_t('lbl_output', 'OUTPUT LOG'))
        if hasattr(self, 'clean_terminal'):
            self.clean_terminal.setPlaceholderText(_t('placeholder_clean', '  → Select targets and click DRY-RUN to preview...'))

        # ── Scanner tab ───────────────────────────────────────
        if hasattr(self, '_scan_readonly_lbl'):
            self._scan_readonly_lbl.setText(
                f'<span style="color:{C["cyan"]};font-family:{MONO};font-size:11px;">'
                f'{_t("scanner_readonly_badge","⬡  Read-only scan — nothing deleted automatically")}'
                f'</span>'
            )
        if hasattr(self, 'scan_btn'):
            self.scan_btn.setText(f"⬡  {_t('btn_run_scan','RUN DEEP SCAN')}")
        if hasattr(self, 'fix_btn'):
            self.fix_btn.setText(f"⚡  {_t('btn_autofix','AUTO-FIX SELECTED')}")
            self.fix_btn.setToolTip(_t('scan_tooltip', ''))
        if hasattr(self, '_lbl_scan_output_sec'):
            self._lbl_scan_output_sec.setText(_t('lbl_scan_output', 'SCAN OUTPUT'))
        if hasattr(self, '_lbl_findings_sec'):
            self._lbl_findings_sec.setText(_t('lbl_findings', 'FINDINGS'))
        if hasattr(self, 'opt_terminal'):
            self.opt_terminal.setPlaceholderText(_t('placeholder_scan', '  ◈  Click  RUN DEEP SCAN  to start...'))
        if hasattr(self, 'scan_table'):
            self.scan_table.setHorizontalHeaderLabels([
                _t('col_sev','SEV'), _t('col_category','CATEGORY'),
                _t('col_path','PATH'), _t('col_detail','DETAIL')
            ])

        # ── Uninstall tab ─────────────────────────────────────
        if hasattr(self, '_lbl_uninst_title'):
            self._lbl_uninst_title.setText(_t('uninstall_title', 'APP UNINSTALLER'))
        if hasattr(self, '_uninst_ref_btn') and self._uninst_ref_btn.isEnabled():
            self._uninst_ref_btn.setText(f"↻ {_t('btn_refresh','REFRESH')}")
        if hasattr(self, '_lbl_uninst_hint'):
            self._lbl_uninst_hint.setText(_t('uninstall_hint', 'Select one or more apps  →  Uninstall'))
        if hasattr(self, 'uninstall_search'):
            self.uninstall_search.setPlaceholderText(_t('placeholder_filter','Filter apps...'))
        if hasattr(self, 'uninstall_table'):
            self.uninstall_table.setHorizontalHeaderLabels([
                _t('col_name','NAME'), _t('col_version','VERSION'),
                _t('col_size','SIZE'), _t('col_source','SOURCE')
            ])

        # ── History tab ───────────────────────────────────────
        if hasattr(self, '_lbl_history_title'):
            self._lbl_history_title.setText(_t('history_title', 'HISTORY LOG'))
        if hasattr(self, '_history_clr_btn'):
            self._history_clr_btn.setText(f"✕ {_t('btn_clear','CLEAR')}")
        if hasattr(self, 'log_table'):
            self.log_table.setHorizontalHeaderLabels([
                _t('col_time','TIME'), _t('col_disk_before','BEFORE'),
                _t('col_disk_after','AFTER'), _t('col_freed','FREED'),
                _t('col_detail','DETAIL')
            ])

        # ── Rollback tab ──────────────────────────────────────
        if hasattr(self, '_lbl_rollback_title'):
            self._lbl_rollback_title.setText(_t('rollback_title', 'ROLLBACK LIST'))
        if hasattr(self, '_rollback_clr_btn'):
            self._rollback_clr_btn.setText(f"✕ {_t('btn_clear','CLEAR')}")
        if hasattr(self, '_rollback_folder_btn'):
            self._rollback_folder_btn.setText(f"📁 {_t('rollback_open_folder', 'OPEN LOG FOLDER')}")
        if hasattr(self, '_lbl_rollback_hint'):
            self._lbl_rollback_hint.setText(_t(
                'rollback_hint',
                'These entries are a record of what was removed — files are not kept for restore.',
            ))
        if hasattr(self, '_tray_reset_close_act'):
            self._tray_reset_close_act.setText(
                _t('tray_reset_close_pref', 'Reset close-window preference…')
            )
        if hasattr(self, '_tray_update_act'):
            self._tray_update_act.setText(_t('tray_view_update', '⬆  View update…'))
        if hasattr(self, '_upd_lbl') and self._upd_lbl.isVisible():
            ver = getattr(self, '_pending_update_ver', '')
            if ver:
                self._upd_lbl.setText(_t('upd_badge', '⬆ v{ver} UPDATE', ver=ver))
        if hasattr(self, 'rollback_table'):
            self.rollback_table.setHorizontalHeaderLabels([
                _t('col_time','TIME'), _t('col_type','TYPE'),
                _t('col_size','SIZE'), _t('col_path_note','PATH / NOTE')
            ])
        if hasattr(self, '_lbl_t_cpu'):
            self._lbl_t_cpu.setText(f"\u26a1  {_t('booster_cpu','CPU PRIORITY MODE')}")
        if hasattr(self, '_lbl_d_cpu'):
            self._lbl_d_cpu.setText(_t('cpu_desc', ''))
        if hasattr(self, '_boost_lbls'):
            _cmap = {
                '_boost_free_ram':    (f"\u2b21  {_t('booster_free_ram','FREE RAM')}",
                                       _t('ram_desc','Drop page cache, reclaim unused memory. Instant RAM boost without rebooting.'),
                                       f"\u25b6  {_t('btn_free_now','FREE NOW')}"),
                '_clear_gpu_cache':   (f"\u25c8  {_t('booster_disk','DISK CACHE CLEAR')}",
                                       _t('disk_desc','Clear GPU/shader cache, temp files. Frees VRAM, fixes video stutter & WebGL glitches.'),
                                       f"\u25c8  {_t('btn_clear_cache','CLEAR CACHE')}"),
                '_boost_memory_tune': (f"\u2b21  {_t('booster_mem_tune','MEMORY TUNE')}",
                                       _t('mem_tune_desc','Linux: set swappiness=10 + compact memory. Windows: flush standby list & optimize VM.'),
                                       f"\u25b6  {_t('btn_tune_now','TUNE NOW')}"),
                '_boost_kill_bloat':  (f"\u2715  {_t('booster_kill_bloat','KILL BACKGROUND BLOAT')}",
                                       _t('kill_desc','Find and kill zombie, sleeping & high-memory idle processes safely.'),
                                       f"\u2715  {_t('btn_kill_bloat','KILL BLOAT')}"),
            }
            for slot_name, (title, desc, btn_text) in _cmap.items():
                if slot_name in self._boost_lbls:
                    entry = self._boost_lbls[slot_name]
                    entry[0].setText(title)
                    entry[1].setText(desc)
                    if len(entry) > 2:
                        entry[2].setText(btn_text)
        # --- Cập nhật Clean Targets labels ---
        if hasattr(self, '_target_lbls'):
            badge_map = {
                'safe':    _t('badge_safe',    'SAFE'),
                'caution': _t('badge_caution', 'CAUTION'),
                'danger':  _t('badge_danger',  'DANGER'),
            }
            for tid, (nm, dc, badge, t_obj) in self._target_lbls.items():
                nm.setText(_t(f'tgt_{tid}_name', t_obj.name) + (' [ROOT]' if t_obj.needs_root else ''))
                dc.setText(_t(f'tgt_{tid}_desc', t_obj.desc))
                badge.setText(badge_map.get(t_obj.safety, t_obj.safety.upper()))
        if hasattr(self, '_game_btn') and not getattr(self, '_game_active', False):
            self._game_btn.setText(f"  {_t('btn_game_mode','GAME MODE')}")
            self._game_btn.setToolTip(_t('game_tooltip', ''))
        if hasattr(self, '_eco_btn') and not getattr(self, '_eco_active', False):
            self._eco_btn.setText(f"  {_t('btn_eco_mode','ECO MODE')}")
            self._eco_btn.setToolTip(_t('eco_tooltip', ''))
        if hasattr(self, '_smart_btn') and not getattr(self, '_smart_active', False):
            self._smart_btn.setText(f"  {_t('btn_smart_boost','SMART BOOST')}")
            self._smart_btn.setToolTip(_t('smart_tooltip', ''))
        if hasattr(self, '_lbl_booster_output_sec'):
            self._lbl_booster_output_sec.setText(_t('lbl_output', 'OUTPUT LOG'))
        if hasattr(self, '_browser_log'):
            self._browser_log.setPlaceholderText(_t('lbl_output', 'OUTPUT'))

    def _toggle_smart_boost(self):
        """Smart Boost — thread-safe theo chuẩn Qt signal/slot."""
        if not hasattr(self, '_smart_saved'):  self._smart_saved  = {}
        if not hasattr(self, '_smart_active'): self._smart_active = False
        if not hasattr(self, '_smart_trans'):  self._smart_trans  = False

        if self._smart_trans:
            self._smart_btn.setChecked(self._smart_active)
            return
        self._smart_trans = True

        if self._smart_btn.isChecked():
            tier     = detect_pc_tier()
            tier_lbl = {'high':'👑 HIGH-END','mid':'💪 MID','low':'🥔 LOW-END'}.get(tier, tier)
            self._smart_btn.setText(f'■  {tier_lbl} — ACTIVE')
            self._game_btn.setEnabled(False)
            self._eco_btn.setEnabled(False)
            self._smart_btn.setEnabled(False)
            self._smart_active = True

            def _on_done(saved):
                self._smart_saved = saved or {}
                self._smart_trans = False
                self._smart_btn.setEnabled(True)

            self._smart_worker = _SmartOnWorker()
            self._smart_worker.log_signal.connect(self._blog)
            self._smart_worker.done.connect(_on_done)
            self._smart_worker.start()

        else:
            self._smart_btn.setText(f"  {_t('btn_smart_boost','SMART BOOST')}")
            self._game_btn.setEnabled(True)
            self._eco_btn.setEnabled(True)
            self._smart_btn.setEnabled(False)
            self._smart_active = False
            saved = self._smart_saved

            def _on_off_done(_):
                self._smart_saved = {}
                self._smart_trans = False
                self._smart_btn.setEnabled(True)

            self._smart_off_worker = _SmartOffWorker(saved)
            self._smart_off_worker.log_signal.connect(self._blog)
            self._smart_off_worker.done.connect(_on_off_done)
            self._smart_off_worker.start()


    def _shutdown(self):
        if getattr(self, '_game_active', False):
            try:
                saved = getattr(self, '_game_frozen_pids', {})
                game_mode_off(saved, lambda m, l='text': None)
                self._game_active = False
            except: pass

        if getattr(self, '_eco_active', False):
            try:
                saved = getattr(self, '_eco_saved', {})
                eco_mode_off(saved, lambda m, l='text': None)
                self._eco_active = False
            except: pass

        if hasattr(self, '_mem_tune_originals') and self._mem_tune_originals:
            try:
                memory_tune_restore(self._mem_tune_originals, lambda m, l='text': None)
            except: pass

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

    def _start_auto_clean(self):
        # Bộ lập lịch thông minh: chỉ chạy khi máy RẢNH
        self._scheduler = IdleScheduler(
            min_interval_hours=6,
            cpu_threshold=20.0,
            net_threshold_kb=500
        )
        self._auto_clean_timer = QTimer(self)
        self._auto_clean_timer.timeout.connect(self._run_auto_clean)
        # Check mỗi 5 phút xem máy có rảnh không
        self._auto_clean_timer.start(5 * 60 * 1000)

    def _run_auto_clean(self):
        if self.isVisible() or getattr(self, '_game_active', False):
            return
        # Chỉ dọn khi máy thực sự rảnh và đã hết cooldown
        if self._scheduler.should_run():
            self._do_background_clean(notify=True)
            self._scheduler.mark_completed()

    def _do_background_clean(self, notify=True):
        safe_targets = [
            t.id for t in CLEANER.get_targets()
            if t.safety == 'safe'
        ]
        if not safe_targets:
            return

        if getattr(self, '_auto_worker', None) and self._auto_worker.isRunning():
            if hasattr(self, 'tray'):
                self.tray.showMessage('CyberClean',
                                      'Already cleaning, please wait...',
                                      QSystemTrayIcon.MessageIcon.Warning, 2000)
            return

        self._auto_worker = _AutoCleanWorker(safe_targets)
        self._auto_worker.done.connect(
            lambda freed, n: self._on_auto_clean_done(freed, n, notify)
        )
        self._auto_worker.start()

    def _on_auto_clean_done(self, freed_bytes, num_targets, notify=True):
        if hasattr(self, 'tray'):
            self.tray.setToolTip(f'CyberClean v{__version__}')
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

    GITHUB_LATEST = 'https://api.github.com/repos/vuphitung/CyberClean/releases/latest'
    CURRENT_VER   = __version__

    def _check_update_async(self):
        threading.Thread(target=self._fetch_update, daemon=True).start()

    def _fetch_update(self):
        try:
            req = urlopen(self.GITHUB_LATEST, timeout=8)
            data = json.loads(req.read().decode())
            latest = data.get("tag_name", "").lstrip("v")
            body = data.get("body") or ""
            if latest and version_is_newer(latest, self.CURRENT_VER):
                self.update_found.emit(latest, body)
        except Exception:
            pass

    def _show_update_notice(self, ver: str, body: str):
        self._pending_update_ver = ver
        self._pending_update_body = body
        self._upd_lbl.setText(_t("upd_badge", "⬆ v{ver} UPDATE", ver=ver))
        self._upd_lbl.setStyleSheet(
            f'color:{C["yellow"]};font-size:10px;letter-spacing:1.5px;'
            f'font-family:{MONO};border:1px solid {C["yellow"]}50;'
            f'padding:3px 8px;border-radius:2px;'
        )
        self._upd_lbl.setVisible(True)
        if hasattr(self, "_tray_update_act"):
            self._tray_update_act.setVisible(True)
            self._tray_update_act.setText(_t('tray_view_update', '⬆  View update…'))
        if hasattr(self, "tray"):
            self.tray.showMessage(
                "CyberClean — Update available",
                _t("tray_upd_msg", f"v{ver}: click the header badge or tray → View update…", ver=ver),
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )

    def _open_update_dialog(self):
        ver = getattr(self, "_pending_update_ver", "") or ""
        body = getattr(self, "_pending_update_body", "") or ""
        if not ver:
            return
        dlg = UpdateDialog(self, version=ver, body=body)
        dlg.exec()


# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    from PyQt6.QtCore import QSharedMemory
    app = QApplication(sys.argv)
    _lock = QSharedMemory("CyberClean_Single_Instance_Lock")
    if not _lock.create(1):
        try: _lock.attach(); _lock.detach()
        except: pass
        if not _lock.create(1):
            _dark = f'background:{C["bg2"]};color:{C["text"]};font-family:monospace;'
            msg = QMessageBox()
            msg.setWindowTitle(_t('zombie_title', 'Background Process Detected'))
            msg.setText(_t('zombie_msg', 'CyberClean is running in the background but cannot be shown.\n\nForce kill the old process and open safely?'))
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setDefaultButton(QMessageBox.StandardButton.Yes)
            msg.setStyleSheet(_dark)
            if msg.exec() == QMessageBox.StandardButton.Yes:
                import psutil as _ps, os as _os, time as _time
                _cur = _os.getpid()
                _my_path = _os.path.abspath(__file__).lower()
                for _p in _ps.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        _nm = (_p.info['name'] or '').lower()
                        _cmd = ' '.join(_p.info['cmdline'] or []).lower()
                        if _p.pid != _cur and ('cyberclean' in _nm or _my_path in _cmd):
                            _p.kill()
                    except: pass
                _time.sleep(0.5)
                try: _lock.attach(); _lock.detach()
                except: pass
                if not _lock.create(1):
                    err = QMessageBox()
                    err.setWindowTitle('CyberClean')
                    err.setText(_t('zombie_err', 'Could not kill old process. Please restart your computer.'))
                    err.setStyleSheet(_dark)
                    err.exec()
                    sys.exit(1)
            else:
                sys.exit(0)

    app.setOrganizationName('CyberClean')
    app.setApplicationName('CyberClean')
    app.setApplicationVersion(__version__)

    def _res(rel):
        base = getattr(sys, '_MEIPASS', Path(__file__).parent)
        return str(Path(base) / rel)

    _icon_path = _res('assets/logo.ico')
    if Path(_icon_path).exists():
        app.setWindowIcon(QIcon(_icon_path))

    win = CyberCleanApp()

    if hasattr(win, 'tray'):
        _tray_icon = _res('assets/logo.png')
        if Path(_tray_icon).exists():
            win.tray.setIcon(QIcon(_tray_icon))

    win.show()
    sys.exit(app.exec())
