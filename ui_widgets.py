"""
CyberClean — UI Widgets
═══════════════════════
Tách từ main.py để giảm kích thước file (145 KB → ~80 KB).

Contains:
  • Design tokens (C, MONO, DISPLAY)
  • QPainter-drawn nav icons (_make_icon, _icon_*, _nav_icon)
  • Custom widgets  (SparklineChart, DiskRing, HexLogoWidget, StatCard, NavButton)
  • QThread workers (SysInfoWorker, CleanWorker, _SmartOnWorker, _SmartOffWorker,
                     _OneClickWorker, _ScanWorker, _UninstallWorker, _AutoCleanWorker)
  • UI helper functions (_btn, _lbl_section, _lbl_val, _card, _divider)

main.py imports everything from here:
  from ui_widgets import *

IMPORTANT: Do NOT import anything from main.py back into this file
           (circular import). Workers that need CLEANER, fmt_size,
           get_snapshot, etc. receive them via lazy imports inside run().
"""

import math
import platform
from datetime import datetime

from PyQt6.QtCore  import Qt, QThread, QRectF, QPointF, QSize, pyqtSignal
from PyQt6.QtGui   import (
    QFont, QColor, QBrush, QPen, QPainter, QLinearGradient,
    QPolygonF, QPixmap, QIcon,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QSizePolicy,
)

IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX   = platform.system() == 'Linux'

# ═════════════════════════════════════════════════════════════
# DESIGN TOKENS
# ═════════════════════════════════════════════════════════════
C = {
    'bg':       '#050a0f',
    'bg2':      '#09121a',
    'bg3':      '#0d1a26',
    'bg4':      '#112032',
    'cyan':     '#00e5ff',
    'cyan2':    '#00bcd4',
    'cyan_dim': '#004d5c',
    'red':      '#ff3d5a',
    'red_dim':  '#3d0010',
    'yellow':   '#ffd740',
    'yel_dim':  '#3d2d00',
    'green':    '#00e676',
    'grn_dim':  '#00280f',
    'purple':   '#d050ff',
    'text':     '#def0f8',
    'text2':    '#7eb8cc',
    'text3':    '#3d6678',
    'dim':      '#2a4a5a',
    'border':   '#0a1e2d',
    'border2':  '#0f2a3d',
    'border3':  '#1a3a52',
    'accent':   '#00e5ff',
}

MONO    = "'Cascadia Code','JetBrains Mono','Fira Code','Consolas','Share Tech Mono',monospace"
DISPLAY = "'Orbitron','Rajdhani','Oxanium','Exo 2','Share Tech Mono',monospace"


# ═════════════════════════════════════════════════════════════
# PURE-CODE NAV ICONS — drawn with QPainter, zero file deps
# ═════════════════════════════════════════════════════════════

def _make_icon(draw_fn, size=20, color='#00e5ff') -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_fn(p, QColor(color), size)
    p.end()
    return QIcon(pix)


def _icon_dashboard(p: QPainter, col: QColor, s: int):
    pen = QPen(col, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
    g = s * 0.12; h = (s - 3 * g) / 2
    for rx, ry in [(g, g), (g*2+h, g), (g, g*2+h), (g*2+h, g*2+h)]:
        p.drawRoundedRect(QRectF(rx, ry, h, h), 1.5, 1.5)


def _icon_clean(p: QPainter, col: QColor, s: int):
    pen = QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(s*0.72, s*0.08), QPointF(s*0.38, s*0.58))
    cx, cy = s*0.32, s*0.65
    for dx, dy in [(-0.14, 0.22), (-0.07, 0.24), (0.0, 0.25), (0.07, 0.24), (0.14, 0.22)]:
        p.drawLine(QPointF(cx, cy), QPointF(cx + dx*s, cy + dy*s))
    p.drawLine(QPointF(s*0.12, s*0.62), QPointF(s*0.52, s*0.62))


def _icon_scanner(p: QPainter, col: QColor, s: int):
    pen = QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    cx, cy, r = s*0.42, s*0.42, s*0.26
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.drawLine(QPointF(cx + r*0.72, cy + r*0.72), QPointF(s*0.92, s*0.92))
    pen2 = QPen(col, 0.9); pen2.setCapStyle(Qt.PenCapStyle.RoundCap); p.setPen(pen2)
    p.drawLine(QPointF(cx, cy - r*0.55), QPointF(cx, cy + r*0.55))
    p.drawLine(QPointF(cx - r*0.55, cy), QPointF(cx + r*0.55, cy))


def _icon_uninstall(p: QPainter, col: QColor, s: int):
    pen = QPen(col, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    lx, rx, ty, by = s*0.22, s*0.78, s*0.30, s*0.88
    p.drawRoundedRect(QRectF(lx, ty, rx-lx, by-ty), 2, 2)
    p.drawLine(QPointF(s*0.14, s*0.28), QPointF(s*0.86, s*0.28))
    p.drawLine(QPointF(s*0.38, s*0.18), QPointF(s*0.62, s*0.18))
    p.drawArc(QRectF(s*0.33, s*0.18, s*0.34, s*0.12), 0, 180*16)
    for xf in [0.36, 0.50, 0.64]:
        p.drawLine(QPointF(s*xf, s*0.40), QPointF(s*xf, s*0.78))


def _icon_history(p: QPainter, col: QColor, s: int):
    pen = QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    cx, cy, r = s*0.50, s*0.50, s*0.36
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.drawLine(QPointF(cx, cy), QPointF(cx - r*0.45, cy - r*0.55))
    p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r*0.72))
    p.drawLine(QPointF(cx, cy - r*0.85), QPointF(cx, cy - r*1.0))


def _icon_rollback(p: QPainter, col: QColor, s: int):
    pen = QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    cx, cy, r = s*0.50, s*0.52, s*0.30
    p.drawArc(QRectF(cx-r, cy-r, r*2, r*2), 30*16, 270*16)
    angle = math.radians(30)
    ax = cx + r * math.cos(angle); ay = cy - r * math.sin(angle)
    p.drawLine(QPointF(ax, ay), QPointF(ax - s*0.08, ay - s*0.14))
    p.drawLine(QPointF(ax, ay), QPointF(ax + s*0.14, ay - s*0.05))


def _icon_booster(p: QPainter, col: QColor, s: int):
    pen = QPen(col, 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    accent = QColor(col); accent.setAlphaF(0.18)
    p.setBrush(QBrush(accent))
    p.drawPolygon(QPolygonF([
        QPointF(s*0.62, s*0.06), QPointF(s*0.32, s*0.50), QPointF(s*0.52, s*0.50),
        QPointF(s*0.38, s*0.94), QPointF(s*0.68, s*0.46), QPointF(s*0.48, s*0.46),
    ]))


_ICON_FN = {
    'dashboard':   _icon_dashboard,
    'smart_clean': _icon_clean,
    'scanner':     _icon_scanner,
    'uninstaller': _icon_uninstall,
    'history':     _icon_history,
    'rollback':    _icon_rollback,
    'booster':     _icon_booster,
}


def _nav_icon(name: str, active=False, size=18) -> QIcon:
    fn    = _ICON_FN.get(name, _icon_dashboard)
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
        w, h, pad = self.width(), self.height(), 3

        grid_pen = QPen(QColor(C['border2'])); grid_pen.setWidth(1); p.setPen(grid_pen)
        for pct in [25, 50, 75]:
            y = h - pad - (pct / 100) * (h - pad * 2)
            p.drawLine(0, int(y), w, int(y))

        pts = [
            QPointF(pad + (i / (self.max_pts - 1)) * (w - pad * 2),
                    h - pad - (v / 100.0) * (h - pad * 2))
            for i, v in enumerate(self.data)
        ]

        fill_pts = [QPointF(pts[0].x(), h)] + pts + [QPointF(pts[-1].x(), h)]
        grad = QLinearGradient(0, 0, 0, h)
        fc = QColor(self.color); fc.setAlphaF(0.22)
        fc2 = QColor(self.color); fc2.setAlphaF(0.01)
        grad.setColorAt(0, fc); grad.setColorAt(1, fc2)
        p.setBrush(QBrush(grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF(fill_pts))

        lp = QPen(self.color); lp.setWidth(2); lp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(lp)
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])

        if pts:
            halo = QColor(self.color); halo.setAlphaF(0.18)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(halo))
            p.drawEllipse(pts[-1], 6, 6)
            p.setBrush(QBrush(self.color)); p.drawEllipse(pts[-1], 3, 3)
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
        self.percent = v; self.update()

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
        p.drawArc(rect, 90 * 16, -int((self.percent / 100.0) * 360 * 16))

        p.setPen(QPen(QColor(color)))
        p.setFont(QFont('Cascadia Code' if IS_WINDOWS else 'Share Tech Mono', 13, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 88, 88), Qt.AlignmentFlag.AlignCenter, f'{int(self.percent)}%')
        p.end()


# ═════════════════════════════════════════════════════════════
# HEX LOGO WIDGET
# ═════════════════════════════════════════════════════════════
class HexLogoWidget(QWidget):
    def __init__(self, size=32, parent=None):
        super().__init__(parent)
        self.s = size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, s = self.s / 2, self.s / 2, self.s / 2 - 2

        def hex_pts(cx, cy, r):
            return [QPointF(cx + r * math.cos(math.radians(60*i - 30)),
                            cy + r * math.sin(math.radians(60*i - 30)))
                    for i in range(6)]

        outer_col = QColor(C['cyan']); outer_col.setAlphaF(0.9)
        p.setPen(QPen(outer_col, 1.2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(QPolygonF(hex_pts(cx, cy, s)))

        inner_col = QColor(C['cyan']); inner_col.setAlphaF(0.07)
        border_col = QColor(C['cyan']); border_col.setAlphaF(0.25)
        p.setBrush(QBrush(inner_col)); p.setPen(QPen(border_col, 0.7))
        p.drawPolygon(QPolygonF(hex_pts(cx, cy, s * 0.65)))

        p.setPen(QPen(QColor(C['cyan'])))
        p.setFont(QFont('Share Tech Mono', max(6, int(self.s * 0.28)), QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, self.s, self.s), Qt.AlignmentFlag.AlignCenter, 'CL')
        p.end()


# ═════════════════════════════════════════════════════════════
# UI HELPERS
# ═════════════════════════════════════════════════════════════

def _btn(text, color='cyan', small=False, icon_only=False):
    col     = C[color]
    col_dim = C.get(color + '_dim', C['bg3'])
    pad     = '5px 12px' if small else '8px 22px'
    sz      = '10px'     if small else '11px'
    btn = QPushButton(text)
    btn.setStyleSheet(f"""
        QPushButton {{
            color:{col};
            border:1px solid {col}40;
            background:{col_dim};
            font-family:{MONO}; font-size:{sz};
            letter-spacing:1.5px; padding:{pad};
            border-radius:2px; font-weight:600;
        }}
        QPushButton:hover   {{ background:{col}20; border-color:{col}80; color:{col}; }}
        QPushButton:pressed {{ background:{col}35; border-color:{col}; }}
        QPushButton:checked {{ background:{col}25; border-color:{col}; color:{col}; }}
        QPushButton:disabled {{ color:{C['dim']}; border-color:{C['dim']}30; background:transparent; }}
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
            f'QFrame{{background:{C["bg2"]};'
            f'border-top:1px solid {bc};border-right:1px solid {bc};'
            f'border-bottom:1px solid {bc};border-left:3px solid {accent_color};'
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
# NAV BUTTON
# ═════════════════════════════════════════════════════════════
class NavButton(QWidget):
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
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(self._bar); lay.addSpacing(12)
        lay.addWidget(self._icon_lbl); lay.addSpacing(10)
        lay.addWidget(self._text_lbl); lay.addStretch()
        self._update_icon()

    def _update_icon(self):
        ico = _nav_icon(self._icon_name, active=self._active, size=18)
        self._icon_lbl.setPixmap(ico.pixmap(18, 18))

    def set_active(self, active: bool):
        self._active = active
        if active:
            self._bar.setStyleSheet(f'background:{C["cyan"]};border:none;border-radius:1px;')
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
        self._label_str = text; self._text_lbl.setText(text)

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
# WORKER THREADS
# All QThread subclasses with pyqtSignal MUST be at module scope.
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
        from utils.sysinfo import get_snapshot
        while not self._stopped:
            if not self.paused:
                try:
                    self.snapshot.emit(get_snapshot(interval=0.3))
                except Exception:
                    pass
            self.msleep(4000)


class CleanWorker(QThread):
    log      = pyqtSignal(str, str)
    progress = pyqtSignal(int, str)
    done     = pyqtSignal(dict)

    def __init__(self, targets, dry=True, cleaner=None):
        super().__init__()
        self.targets = targets
        self.dry     = dry
        self._cleaner = cleaner   # passed in from main.py (avoids import cycle)

    def run(self):
        from utils.sysinfo import fmt_size
        CLEANER = self._cleaner
        total_freed = 0; rollback = []; summary = []
        steps = len(self.targets)

        self.log.emit('─' * 44, 'head')
        mode = 'DRY-RUN' if self.dry else 'CLEAN'
        self.log.emit(f'  {mode}  ·  {datetime.now().strftime("%H:%M:%S")}', 'head')
        self.log.emit('─' * 44, 'head')

        for i, tid in enumerate(self.targets):
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


class _SmartOnWorker(QThread):
    log_signal = pyqtSignal(str, str)
    done       = pyqtSignal(object)

    def run(self):
        try:
            from core.booster import smart_boost_on
            saved = smart_boost_on(lambda m, l='text': self.log_signal.emit(m, l))
            self.done.emit(saved)
        except Exception as e:
            self.log_signal.emit(f'  x Smart Boost error: {e}', 'err')
            self.done.emit({})


class _SmartOffWorker(QThread):
    log_signal = pyqtSignal(str, str)
    done       = pyqtSignal(object)

    def __init__(self, saved_state):
        super().__init__()
        self._saved_state = saved_state

    def run(self):
        try:
            from core.booster import smart_boost_off
            smart_boost_off(self._saved_state, lambda m, l='text': self.log_signal.emit(m, l))
        except Exception as e:
            self.log_signal.emit(f'  x Smart Boost restore error: {e}', 'err')
        self.done.emit(None)


class _OneClickWorker(QThread):
    done = pyqtSignal(str, bool)

    def run(self):
        import subprocess as _sp, shutil as _sh
        HELPER  = '/usr/local/bin/cyber-clean-helper'
        results = []
        if IS_LINUX:
            for action, label in [
                ('swappiness',    'Swappiness→10'),
                ('fstrim',        'SSD TRIM'),
                ('journal',       'Journal'),
                ('paccache',      'Paccache'),
                ('compact-memory','Compact RAM'),
            ]:
                if action == 'paccache' and not _sh.which('paccache'):
                    continue
                r = _sp.run(f'sudo -n {HELPER} {action}', shell=True,
                            capture_output=True, text=True, timeout=60)
                results.append((label, r.returncode == 0))
            try:
                from core.booster import free_ram
                free_ram(lambda m, l='text': None)
                results.append(('Smart RAM Free', True))
            except Exception:
                pass
        elif platform.system() == 'Windows':
            for cmd, label in [
                ('ipconfig /flushdns', 'Flush DNS'),
                ('del /q /f /s "%TEMP%\\*" 2>nul', 'Clear TEMP'),
            ]:
                r = _sp.run(cmd, shell=True, capture_output=True, text=True,
                            timeout=30, creationflags=0x08000000)
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
    log  = pyqtSignal(str, str)
    done = pyqtSignal(list, list)

    def run(self):
        try:
            from core.scanner import SecurityScanner
            sc      = SecurityScanner()
            results = sc.scan(lambda m, l: self.log.emit(m, l))
        except Exception as e:
            self.log.emit(f'  x Scanner error: {e}', 'err')
            results = []
        try:
            from core.analyzer import get_network_processes
            self.log.emit('  ⟳  Scanning active network processes...', 'head')
            net_results = get_network_processes()
        except Exception:
            net_results = []
        self.done.emit(results, net_results)


class _UninstallWorker(QThread):
    finished = pyqtSignal(list)

    def run(self):
        try:
            from core.uninstaller import get_installed_apps
            self.finished.emit(get_installed_apps())
        except Exception:
            self.finished.emit([])


class _AutoCleanWorker(QThread):
    done = pyqtSignal(int, int)

    def __init__(self, safe_targets, cleaner):
        super().__init__()
        self._safe_targets = safe_targets
        self._cleaner      = cleaner

    def run(self):
        total_freed = 0; cleaned = 0
        for tid in self._safe_targets:
            try:
                result       = self._cleaner.clean(tid, dry=False)
                total_freed += result.freed_bytes
                cleaned     += 1
            except Exception:
                pass
        self.done.emit(total_freed, cleaned)
