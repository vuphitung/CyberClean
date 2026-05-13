"""
CyberClean — UI Widgets
═══════════════════════
Tách từ main.py để giảm kích thước file (145 KB → ~80 KB).

Contains:
  • Design tokens (C, MONO, DISPLAY)
  • QPainter-drawn nav icons (_make_icon, _icon_*, _nav_icon)
  • Custom widgets  (SparklineChart, DiskRing, HexLogoWidget, StatCard, NavButton,
                     CyberTerminal)
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

from PyQt6.QtCore  import (
    Qt, QThread, QRectF, QPointF, QSize, pyqtSignal,
    QPropertyAnimation, QEasingCurve, QTimer, pyqtProperty,
)
from PyQt6.QtGui   import (
    QFont, QColor, QBrush, QPen, QPainter, QLinearGradient,
    QPolygonF, QPixmap, QIcon, QTextCursor, QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QSizePolicy,
)

# i18n runtime log translator (lazy import to avoid circular)
def _tlog(msg: str) -> str:
    """Translate a hardcoded English log line to current UI language."""
    try:
        from utils.i18n import translate_log_line
        return translate_log_line(msg)
    except Exception:
        return msg

def _t(key: str, default: str = '') -> str:
    """Lazy-import _t from i18n to avoid circular imports."""
    try:
        from utils.i18n import _t as _t_real
        return _t_real(key, default)
    except Exception:
        return default or key

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
# CYBER TERMINAL  — custom log output cho clean / scan pages
# ═════════════════════════════════════════════════════════════
from PyQt6.QtWidgets import QPlainTextEdit, QScrollBar
from PyQt6.QtGui     import QTextCursor, QTextCharFormat


class CyberTerminal(QWidget):
    """
    Cyberpunk-styled terminal log widget.
    Thay thế QTextEdit thông thường trong trang Dọn Rác.

    Usage:
        t = CyberTerminal()
        t.append_log("message", level)   # level: ok/err/dry/head/info/warn/text
        t.clear()
        t.set_placeholder("text")
    """

    # Level → (hex_color, prefix_icon)
    _LEVEL = {
        'ok':   ('#00e676', '  ✓  '),
        'err':  ('#ff3d5a', '  ✗  '),
        'dry':  ('#ffd740', '  ~  '),
        'head': ('#00e5ff', ''),
        'info': ('#3d6678', ''),
        'warn': ('#ffd740', '  ⚠  '),
        'text': ('#7eb8cc', ''),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── header bar ──────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(26)
        hdr.setStyleSheet(
            f'QFrame{{background:{C["bg3"]};'
            f'border-top:1px solid {C["border2"]};'
            f'border-left:1px solid {C["border2"]};'
            f'border-right:1px solid {C["border2"]};'
            f'border-bottom:1px solid {C["border3"]};'
            f'border-top-left-radius:3px;border-top-right-radius:3px;}}'
        )
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(10, 0, 10, 0); hdr_lay.setSpacing(6)
        for col in ('#ff3d5a', '#ffd740', '#00e676'):
            dot = QFrame(); dot.setFixedSize(9, 9)
            dot.setStyleSheet(
                f'QFrame{{background:{col}30;border:1px solid {col}60;'
                f'border-radius:4px;}}'
            )
            hdr_lay.addWidget(dot)
        hdr_lay.addStretch()
        self._hdr_lbl = QLabel('TERMINAL OUTPUT')
        self._hdr_lbl.setStyleSheet(
            f'color:{C["text3"]};font-size:8px;letter-spacing:3px;font-family:{MONO};'
        )
        hdr_lay.addWidget(self._hdr_lbl)
        hdr_lay.addStretch()
        root.addWidget(hdr)

        # ── text area ────────────────────────────────────────────────────
        self._te = QPlainTextEdit()
        self._te.setReadOnly(True)
        self._te.setMaximumBlockCount(600)
        self._te.document().setMaximumBlockCount(600)
        self._te.setStyleSheet(f'''
            QPlainTextEdit {{
                background: {C["bg"]};
                color: {C["text2"]};
                border-left: 1px solid {C["border2"]};
                border-right: 1px solid {C["border2"]};
                border-bottom: 1px solid {C["border2"]};
                border-bottom-left-radius: 3px;
                border-bottom-right-radius: 3px;
                border-top: none;
                font-family: {MONO};
                font-size: 11px;
                padding: 10px 14px;
                selection-background-color: {C["cyan"]}25;
                line-height: 1.5;
            }}
            QScrollBar:vertical {{
                background: {C["bg2"]};
                width: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C["border3"]};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C["cyan"]}60;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        ''')
        root.addWidget(self._te, 1)

    # ── Public API ───────────────────────────────────────────────────────
    def append_log(self, msg: str, level: str = 'text'):
        """Append một dòng log có màu theo level."""
        col, _prefix = self._LEVEL.get(level, ('#7eb8cc', ''))
        cursor = self._te.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(col))
        cursor.setCharFormat(fmt)
        cursor.insertText(msg + '\n')
        self._te.setTextCursor(cursor)
        sb = self._te.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear(self):
        self._te.clear()

    def set_placeholder(self, text: str):
        self._te.setPlaceholderText(text)

    def set_header(self, text: str):
        self._hdr_lbl.setText(text.upper())

    def to_html(self) -> str:
        return self._te.toHtml()


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
        self._stop_requested = False

    def stop(self):
        """Request graceful stop — current target finishes, then loop exits."""
        self._stop_requested = True

    def run(self):
        from utils.sysinfo import fmt_size
        CLEANER = self._cleaner
        total_freed = 0; rollback = []; summary = []
        steps = len(self.targets)

        # FIX v2.5: outer try/except guarantees done is ALWAYS emitted.
        # Without this, an unexpected exception (e.g. fmt_size crash, import error)
        # would leave _dry_btn/_clean_btn permanently disabled.
        try:
            self.log.emit('─' * 44, 'head')
            mode = 'DRY-RUN' if self.dry else 'CLEAN'
            self.log.emit(f'  {_tlog(mode)}  ·  {datetime.now().strftime("%H:%M:%S")}', 'head')
            self.log.emit('─' * 44, 'head')

            # ── FAST PATH: dry-run uses parallel estimate if available ────────
            # estimate_parallel() scans all dirs concurrently → 3-5x faster.
            if self.dry and hasattr(CLEANER, 'estimate_parallel'):
                self.progress.emit(5, 'Scanning...')
                try:
                    estimates = CLEANER.estimate_parallel(self.targets)
                except Exception:
                    estimates = {}
                for i, tid in enumerate(self.targets):
                    if self._stop_requested:
                        self.log.emit('  ⚠  Interrupted', 'warn')
                        break
                    label = tid.replace('_', ' ').upper()
                    pct = int(5 + ((i + 1) / steps) * 90)
                    self.progress.emit(pct, label)
                    freed = estimates.get(tid, 0)
                    # Still call clean(dry=True) for CleanResult + error reporting
                    # but check cache first to avoid redundant disk scan
                    if hasattr(CLEANER, '_cache_get'):
                        cached = CLEANER._cache_get(tid)
                        result = cached if cached is not None else CLEANER.clean(tid, dry=True)
                        if cached is None:
                            CLEANER._cache_set(tid, result)
                    else:
                        result = CLEANER.clean(tid, dry=True)
                    total_freed += result.freed_bytes
                    rollback    += result.rollback
                    self.log.emit(f'\n  ▸ {_tlog(label)}', 'head')
                    if result.error:
                        self.log.emit(f'  ✗  {result.error}', 'err')
                    else:
                        self.log.emit(f'  ~  ~{fmt_size(result.freed_bytes)}', 'dry')
                        if result.files_removed:
                            self.log.emit(_tlog(f'     {result.files_removed} items'), 'dry')
                    if result.freed_bytes > 0:
                        summary.append(f'{tid}:{fmt_size(result.freed_bytes)}')
            else:
                # ── SERIAL PATH: real clean, or cleaner without estimate_parallel ─
                for i, tid in enumerate(self.targets):
                    if self._stop_requested:
                        self.log.emit('  ⚠  Interrupted — partial results below', 'warn')
                        break

                    slice_start = int((i / steps) * 95)
                    slice_mid   = int(((i + 0.5) / steps) * 95)
                    slice_end   = int(((i + 1) / steps) * 95)
                    label = tid.replace('_', ' ').upper()
                    self.progress.emit(slice_start, f'{label}...')
                    self.log.emit(f'\n  ▸ {_tlog(label)}', 'head')
                    self.progress.emit(slice_mid, f'{label}...')

                    # ── Estimate cache (dry-run only) ─────────────────────
                    # Avoid re-scanning the same dirs within 60s — huge win on
                    # Windows where WinSxS and large caches are slow to walk.
                    if self.dry and hasattr(CLEANER, '_cache_get'):
                        cached = CLEANER._cache_get(tid)
                        if cached is not None:
                            result = cached
                            self.log.emit(_tlog('  ⚡  (cached)'), 'dry')
                        else:
                            result = CLEANER.clean(tid, dry=True)
                            CLEANER._cache_set(tid, result)
                    else:
                        result = CLEANER.clean(tid, dry=self.dry)
                        # Invalidate cache after a real clean so next dry-run rescans
                        if not self.dry and hasattr(CLEANER, '_cache_invalidate'):
                            CLEANER._cache_invalidate(tid)

                    self.progress.emit(slice_end, f'{label}')

                    if result.error:
                        self.log.emit(f'  ✗  {result.error}', 'err')
                    elif self.dry:
                        self.log.emit(f'  ~  ~{fmt_size(result.freed_bytes)}', 'dry')
                        if result.files_removed:
                            self.log.emit(_tlog(f'     {result.files_removed} items'), 'dry')
                    else:
                        self.log.emit(_tlog(f'  ✓  {fmt_size(result.freed_bytes)} freed'), 'ok')
                        if result.files_removed:
                            self.log.emit(_tlog(f'     {result.files_removed} removed'), 'ok')

                    total_freed += result.freed_bytes
                    rollback    += result.rollback
                    if result.freed_bytes > 0:
                        summary.append(f'{tid}:{fmt_size(result.freed_bytes)}')

        except Exception as _e:
            self.log.emit(f'  ✗  Internal worker error: {_e}', 'err')

        self.progress.emit(100, 'done')
        self.log.emit('\n' + '─' * 44, 'head')
        label = 'ESTIMATED' if self.dry else 'FREED'
        self.log.emit(_tlog(f'TOTAL {label}: {fmt_size(total_freed)}'), 'ok')
        self.done.emit({'freed': total_freed, 'dry': self.dry,
                        'summary': ' | '.join(summary), 'rollback': rollback})


class _SmartOnWorker(QThread):
    log_signal = pyqtSignal(str, str)
    done       = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            from core.booster import smart_boost_on
            saved = smart_boost_on(lambda m, l='text': self.log_signal.emit(_tlog(m), l))
            self.done.emit(saved)
        except Exception as e:
            self.log_signal.emit(f'  x Smart Boost error: {e}', 'err')
            self.done.emit({})


class _SmartOffWorker(QThread):
    log_signal = pyqtSignal(str, str)
    done       = pyqtSignal(object)

    def __init__(self, saved_state):
        super().__init__()
        self._stop_requested = False
        self._saved_state = saved_state

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            from core.booster import smart_boost_off
            smart_boost_off(self._saved_state, lambda m, l='text': self.log_signal.emit(_tlog(m), l))
        except Exception as e:
            self.log_signal.emit(f'  x Smart Boost restore error: {e}', 'err')
        self.done.emit(None)


class _OneClickWorker(QThread):
    done = pyqtSignal(str, bool)

    def __init__(self):
        super().__init__()
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

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

    def __init__(self):
        super().__init__()
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            from core.scanner import SecurityScanner
            sc      = SecurityScanner()
            results = sc.scan(lambda m, l: self.log.emit(_tlog(m), l))
        except Exception as e:
            self.log.emit(f'  ✗  Scanner error: {e}', 'err')
            results = []
        try:
            from core.analyzer import get_network_processes
            self.log.emit('  ⟳  ' + _tlog('Scanning active network processes...'), 'head')
            net_results = get_network_processes()
        except Exception:
            net_results = []
        self.done.emit(results, net_results)


class _UninstallWorker(QThread):
    """
    Loads installed apps list in background.
    Emits progress(str) during slow phases (winget enrichment can take 30s+).
    Falls back gracefully if any backend fails — never crashes the UI.
    """
    finished = pyqtSignal(list)
    progress = pyqtSignal(str)   # status text for hint label

    def __init__(self):
        super().__init__()
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            self.progress.emit('⟳  Reading installed apps...')
            from core.uninstaller import get_installed_apps
            apps = get_installed_apps()
            self.finished.emit(apps)
        except Exception:
            self.finished.emit([])


class _DoUninstallWorker(QThread):
    """
    Runs uninstall_app() for each selected app in a background thread.
    Main thread stays 100% responsive — no freeze, no blank window.

    Signals:
      log_line(msg, level)      — append to uninstall_log (thread-safe via signal)
      one_done(app, result)     — fires after each app finishes
      all_done(had_ui_opened)   — fires when all apps processed
    """
    log_line = pyqtSignal(str, str)
    one_done = pyqtSignal(object, object)
    all_done = pyqtSignal(bool)

    def __init__(self, apps):
        super().__init__()
        self._apps = apps
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            from core.uninstaller import uninstall_app
        except Exception as e:
            self.log_line.emit(f'  ✗  Import error: {e}', 'err')
            self.all_done.emit(False)
            return

        ui_opened = False
        for app in self._apps:
            if self._stop_requested:
                self.log_line.emit('  ⚠  Interrupted by user', 'warn')
                break
            try:
                self.log_line.emit(f'  ▸  Uninstalling {app.name}...', 'info')
                result = uninstall_app(
                    app,
                    lambda m, l='info': self.log_line.emit(m, l),
                )
                self.one_done.emit(app, result)
                if result == 'UI_OPENED':
                    ui_opened = True
            except Exception as e:
                self.log_line.emit(f'  ✗  {app.name}: {e}', 'err')
                self.one_done.emit(app, False)

        self.all_done.emit(ui_opened)



# ═══════════════════════════════════════════════════════════════════════════
# DiskDeltaWidget  — "Tape-bar" disk before/after visualiser
# ═══════════════════════════════════════════════════════════════════════════
class DiskDeltaWidget(QWidget):
    """
    Custom-painted widget that shows disk state as a horizontal tape bar.

    Layout (top → bottom):
      ┌────────────── full width = total disk ──────────────┐
      │░░░░░░░░░░ USED (before) ░░░░│▓▓▓ FREED ▓▓▓│        │  ← tape bar
      └──────────────────────────────────────────────────────┘
      TRƯỚC  14.5 GB free          ▼ 228 MB freed       SAU  14.8 GB free

    States:
      • IDLE  — bar shows current disk state, AFTER column hidden
      • READY — AFTER column populates, freed segment revealed via animation
    """

    _ANIM_MS   = 700           # animation duration ms
    _BAR_H     = 10            # tape bar height px
    _SCAN_W    = 3             # animated scan-line width
    _COL_W     = 110           # left/right label column width
    _PAD_X     = 20
    _PAD_Y_TOP = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # state
        self._total      = 0
        self._free_bef   = 0
        self._used_pct_b = 0.0
        self._free_aft   = 0
        self._used_pct_a = 0.0
        self._freed      = 0
        self._has_after  = False
        self._is_dry     = True

        # animated freed-width ratio 0.0 → actual
        self.__freed_ratio = 0.0
        self._anim = QPropertyAnimation(self, b'_freed_ratio', self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(self._ANIM_MS)

        # scan-line pulse position (0.0 → 1.0 across freed segment)
        self.__scan_pos = 0.0
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._tick_scan)
        self._scan_timer.start(16)   # ~60 fps

    # ── pyqtProperty for animation ────────────────────────────────────
    def _get_freed_ratio(self): return self.__freed_ratio
    def _set_freed_ratio(self, v):
        self.__freed_ratio = v
        self.update()
    _freed_ratio = pyqtProperty(float, _get_freed_ratio, _set_freed_ratio)

    def _tick_scan(self):
        self.__scan_pos = (self.__scan_pos + 0.012) % 1.0
        if self._has_after:
            self.update()

    # ── Public API ────────────────────────────────────────────────────
    def set_before(self, free_bytes: int, total_bytes: int, used_pct: float):
        self._free_bef   = free_bytes
        self._total      = max(total_bytes, 1)
        self._used_pct_b = used_pct
        self._has_after  = False
        self.__freed_ratio = 0.0
        self._anim.stop()
        self.update()

    def set_after(self, free_bytes: int, used_pct: float,
                  freed_bytes: int, dry: bool = True):
        self._free_aft   = free_bytes
        self._used_pct_a = used_pct
        self._freed      = freed_bytes
        self._is_dry     = dry
        self._has_after  = True
        target = freed_bytes / self._total if self._total > 0 else 0.0
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(min(target, 1.0))
        self._anim.start()

    def reset(self):
        self._has_after  = False
        self.__freed_ratio = 0.0
        self._anim.stop()
        self.update()

    # ── Helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _fmt(b: int) -> str:
        if b <= 0:        return '—'
        if b >= 1 << 30:  return f'{b/(1<<30):.1f} GB'
        if b >= 1 << 20:  return f'{b/(1<<20):.0f} MB'
        return f'{b >> 10} KB'

    # ── Paint ─────────────────────────────────────────────────────────
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # ── colours ──────────────────────────────────────────────────
        col_bg      = QColor(C['bg2'])
        col_used    = QColor('#0d3a52')          # dark teal
        col_used_hi = QColor('#00bcd4')          # cyan edge
        col_free    = QColor('#081820')          # near-black
        col_freed   = QColor(C['green'])         # bright green
        col_freed_d = QColor('#005522')          # freed dim
        col_cyan    = QColor(C['cyan'])
        col_text    = QColor(C['text'])
        col_text2   = QColor(C['text2'])
        col_text3   = QColor(C['text3'])
        col_green   = QColor(C['green'])
        col_border  = QColor(C['border3'])

        # background
        p.fillRect(0, 0, W, H, col_bg)

        # ── geometry ─────────────────────────────────────────────────
        pw = self._PAD_X
        bar_x = pw + self._COL_W + 16
        bar_w = W - bar_x - pw - self._COL_W - 16
        bar_y = self._PAD_Y_TOP + 2
        bh    = self._BAR_H

        used_ratio  = 1.0 - (self._free_bef / self._total) if self._total > 0 else 0.0
        used_ratio  = max(0.0, min(1.0, used_ratio))
        freed_ratio = max(0.0, min(1.0 - used_ratio, self.__freed_ratio))

        used_px   = int(bar_w * used_ratio)
        freed_px  = int(bar_w * freed_ratio)
        free_px   = bar_w - used_px - freed_px

        # ── tape bar background (total free) ─────────────────────────
        p.fillRect(bar_x, bar_y, bar_w, bh, col_free)

        # ── used segment ─────────────────────────────────────────────
        if used_px > 0:
            g = QLinearGradient(bar_x, bar_y, bar_x + used_px, bar_y)
            g.setColorAt(0.0, QColor('#082535'))
            g.setColorAt(0.85, col_used)
            g.setColorAt(1.0, col_used_hi)
            p.fillRect(bar_x, bar_y, used_px, bh, QBrush(g))

        # ── freed segment ─────────────────────────────────────────────
        if freed_px > 0:
            fx = bar_x + used_px
            g2 = QLinearGradient(fx, bar_y, fx + freed_px, bar_y)
            g2.setColorAt(0.0, col_freed_d)
            g2.setColorAt(1.0, col_freed)
            p.fillRect(fx, bar_y, freed_px, bh, QBrush(g2))

            # scan-line shimmer across freed segment
            sp = int(self.__scan_pos * (freed_px + self._SCAN_W * 4)) - self._SCAN_W * 2
            sx = fx + sp
            if fx <= sx <= fx + freed_px + self._SCAN_W:
                sg = QLinearGradient(sx, bar_y, sx + self._SCAN_W * 4, bar_y)
                sg.setColorAt(0.0, QColor(0, 230, 118, 0))
                sg.setColorAt(0.5, QColor(0, 230, 118, 180))
                sg.setColorAt(1.0, QColor(0, 230, 118, 0))
                p.fillRect(sx, bar_y, self._SCAN_W * 4, bh, QBrush(sg))

        # ── bar top highlight line ────────────────────────────────────
        p.setPen(QPen(QColor(C['cyan'] + '30'), 1))
        p.drawLine(bar_x, bar_y, bar_x + bar_w, bar_y)

        # ── tick marks at 25% intervals ───────────────────────────────
        p.setPen(QPen(col_border, 1))
        for frac in (0.25, 0.50, 0.75):
            tx = bar_x + int(bar_w * frac)
            p.drawLine(tx, bar_y + bh, tx, bar_y + bh + 4)

        # ── % label above bar ─────────────────────────────────────────
        font_tiny = QFont()
        font_tiny.setPixelSize(9)
        font_tiny.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(font_tiny)

        if used_px > 20:
            p.setPen(col_text3)
            p.drawText(bar_x + 4, bar_y - 3, f'{self._used_pct_b:.0f}% {_t("lbl_pct_used","used")}')

        if freed_px > 40 and self._has_after:
            p.setPen(col_freed)
            label = ('~' if self._is_dry else '') + self._fmt(self._freed) + ' freed'
            p.drawText(bar_x + used_px + 4, bar_y - 3, label)

        # ── ruler line below bar ─────────────────────────────────────
        p.setPen(QPen(col_border, 1))
        p.drawLine(bar_x, bar_y + bh + 5, bar_x + bar_w, bar_y + bh + 5)

        # ── LEFT COLUMN — BEFORE ─────────────────────────────────────────
        lx = pw
        self._draw_stat_col(
            p, lx, bar_y - 2, self._COL_W,
            _t('lbl_before', 'BEFORE'),
            self._fmt(self._free_bef),
            f'{self._used_pct_b:.1f}% {_t("lbl_pct_used","used")}',
            col_cyan, col_text, col_text3,
            align_right=False,
        )

        # ── RIGHT COLUMN — SAU ────────────────────────────────────────
        rx = W - pw - self._COL_W
        if self._has_after:
            self._draw_stat_col(
                p, rx, bar_y - 2, self._COL_W,
                _t('lbl_after_est', 'AFTER (EST)') if self._is_dry else _t('lbl_after', 'AFTER'),
                self._fmt(self._free_aft),
                f'{self._used_pct_a:.1f}% {_t("lbl_pct_used","used")}',
                col_green, col_text, col_text3,
                align_right=True,
            )
        else:
            self._draw_stat_col(
                p, rx, bar_y - 2, self._COL_W,
                _t('lbl_after', 'AFTER'),
                '—',
                '',
                col_text3, col_text3, col_text3,
                align_right=True,
            )

        # ── CENTRE badge: freed amount (only when visible) ────────────
        if self._has_after and freed_px > 0:
            mid_x = bar_x + used_px + freed_px // 2
            badge_y = bar_y + bh + 10
            freed_str = ('~' if self._is_dry else '') + self._fmt(self._freed)

            font_badge = QFont()
            font_badge.setPixelSize(13)
            font_badge.setBold(True)
            p.setFont(font_badge)
            fm = p.fontMetrics()
            bw = fm.horizontalAdvance(freed_str) + 20
            bh2 = fm.height() + 8
            bx = mid_x - bw // 2
            by = badge_y

            # badge bg
            p.setBrush(QBrush(QColor('#002a14')))
            p.setPen(QPen(col_freed.darker(130), 1))
            p.drawRoundedRect(bx, by, bw, bh2, 3, 3)

            # badge text
            p.setPen(col_freed)
            p.drawText(
                QRectF(bx, by, bw, bh2),
                Qt.AlignmentFlag.AlignCenter,
                freed_str,
            )

            # downward arrow from bar to badge
            ax = mid_x
            p.setPen(QPen(col_freed.darker(150), 1))
            p.drawLine(ax, bar_y + bh + 5, ax, badge_y - 1)

        p.end()

    def _draw_stat_col(self, p, x, y, w,
                       tag, val, sub,
                       col_tag, col_val, col_sub,
                       align_right=False):
        flag = Qt.AlignmentFlag.AlignRight if align_right else Qt.AlignmentFlag.AlignLeft

        font_tag = QFont()
        font_tag.setPixelSize(8)
        font_tag.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        font_tag.setBold(True)
        p.setFont(font_tag)
        p.setPen(QColor(col_tag).darker(130) if col_tag != QColor(C['text3']) else col_sub)
        p.drawText(QRectF(x, y, w, 14), flag | Qt.AlignmentFlag.AlignTop, tag)

        font_val = QFont()
        font_val.setPixelSize(20)
        font_val.setBold(True)
        p.setFont(font_val)
        p.setPen(col_val)
        p.drawText(QRectF(x, y + 13, w, 26), flag, val)

        font_sub = QFont()
        font_sub.setPixelSize(10)
        p.setFont(font_sub)
        p.setPen(col_sub)
        p.drawText(QRectF(x, y + 38, w, 14), flag, sub)


class _AutoCleanWorker(QThread):
    done = pyqtSignal(int, int)

    def __init__(self, safe_targets, cleaner):
        super().__init__()
        self._safe_targets = safe_targets
        self._cleaner      = cleaner
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        total_freed = 0; cleaned = 0
        for tid in self._safe_targets:
            if self._stop_requested:
                break
            try:
                result       = self._cleaner.clean(tid, dry=False)
                total_freed += result.freed_bytes
                cleaned     += 1
            except Exception:
                pass
        self.done.emit(total_freed, cleaned)

