"""
CyberClean — Commercial-Grade UI Widgets & 3D Dual-Theme Engine (v4.0)
══════════════════════════════════════════════════════════════════════
100% Pure Python / PyQt6 — Zero external icon/image dependencies.
Inspired by Linear, Raycast, Apple macOS, Stripe, and Vercel Geist Design Systems:
  • Multi-Tier Surface Hierarchy & Specular Rim Lighting (ElevatedCard)
  • True Tonal Light Mode (Cool Slate Canvas #EAEEF5 + Recessed Sidebar #F3F6FA +
    Elevated Pure White Cards #FFFFFF with soft ambient shadows & rich semantic pills)
  • Deep Obsidian Cyber Dark Mode (#060911 Canvas + #0B101C Sidebar + #0F172A Cards
    with top 1px specular highlight & neon telemetry accents)
  • Collision-Free 3D Perspective Hologram Core (Cyber3DDiskCore) & Sleek Sidebar Gauge (DiskRing)
  • Crisp Procedural Checkmark Generator (_global_check_icon_path)
"""

import math
import os
import platform
import tempfile
from datetime import datetime
from typing import List, Tuple

from PyQt6.QtCore import (
    Qt, QThread, QRectF, QPointF, QSize, pyqtSignal, QObject, QEvent,
    QPropertyAnimation, QEasingCurve, QTimer, pyqtProperty, QStandardPaths,
)
from PyQt6.QtGui import (
    QFont, QColor, QBrush, QPen, QPainter, QLinearGradient, QRadialGradient,
    QPolygonF, QPixmap, QIcon, QTextCursor, QTextCharFormat, QPainterPath,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QSizePolicy, QTableWidget,
    QPlainTextEdit, QScrollBar, QGraphicsDropShadowEffect,
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

# ═════════════════════════════════════════════════════════════════════════
# MULTI-TIER DESIGN TOKENS (Linear/Raycast Dark vs Apple/Stripe Daylight)
# ═════════════════════════════════════════════════════════════════════════

THEME_DARK = {
    'mode':        'dark',
    # 5-Tier Surface Ladder
    'bg':          '#060911',   # Deepest obsidian canvas (Linear #010102 / Raycast #07080a inspired)
    'sidebar_bg':  '#090E1A',   # Recessed navigation shell
    'header_bg':   '#0A101D',   # Top bar surface
    'bg2':         '#0E1626',   # Primary elevated card surface
    'bg2_grad':    '#0B111E',   # Card bottom gradient stop for subtle 3D depth
    'bg3':         '#152036',   # Hover / secondary interactive surface
    'bg4':         '#1E2D4A',   # Active / pressed surface
    'well_bg':     '#05080F',   # Recessed inset well for tables & terminals
    # Specular & Hairline Borders
    'specular':    'rgba(255, 255, 255, 0.09)',
    'border':      '#152033',
    'border2':     '#1E2D47',
    'border3':     '#2E446B',
    # Chromatic Accents
    'cyan':        '#00E5FF',
    'cyan2':       '#38BDF8',
    'cyan_dim':    '#062838',
    'red':         '#FF2E63',
    'red_dim':     '#3B0A19',
    'yellow':      '#FFB300',
    'yel_dim':     '#382405',
    'green':       '#00E676',
    'grn_dim':     '#05331E',
    'purple':      '#A855F7',
    'pur_dim':     '#261042',
    'magenta':     '#EC4899',
    # Typography Hierarchy
    'text':        '#F8FAFC',
    'text2':       '#CBD5E1',
    'text3':       '#94A3B8',
    'dim':         '#64748B',
    'accent':      '#00E5FF',
    'ring':        '#00E5FF',
    'radius':      '10px',
}

THEME_LIGHT = {
    'mode':        'light',
    # 5-Tier Daylight Surface Ladder (Apple macOS / Stripe / Vercel Geist)
    # Canvas is a cool architectural slate-alabaster (#EAEEF5) so #FFFFFF cards pop with real depth!
    'bg':          '#EAEEF5',   # Cool architectural canvas (never glaring flat white)
    'sidebar_bg':  '#F2F5FA',   # Soft frosted pearl sidebar
    'header_bg':   '#F7F9FC',   # Crisp top bar
    'bg2':         '#FFFFFF',   # Pure elevated card surface
    'bg2_grad':    '#F9FBFF',   # Subtle bottom card tint
    'bg3':         '#EDF2F9',   # Hover / secondary surface / table header
    'bg4':         '#E2E8F3',   # Active / pressed control surface
    'well_bg':     '#F4F7FB',   # Recessed inset well for logs & tables
    # Specular & Hairline Borders
    'specular':    'rgba(255, 255, 255, 0.95)',
    'border':      '#E2E8F0',
    'border2':     '#CBD5E1',
    'border3':     '#94A3B8',
    # Deep High-Contrast Chromatic Accents (WCAG AAA/AA on white/tinted pills)
    'cyan':        '#0284C7',   # Deep Ocean Blue
    'cyan2':       '#0369A1',
    'cyan_dim':    '#E0F2FE',   # Soft sky pill fill
    'red':         '#E11D48',   # Crimson Rose
    'red_dim':     '#FFE4E6',   # Soft rose pill fill
    'yellow':      '#D97706',   # Rich Amber
    'yel_dim':     '#FEF3C7',   # Warm amber pill fill
    'green':       '#059669',   # Deep Emerald
    'grn_dim':     '#D1FAE5',   # Mint pill fill
    'purple':      '#6D28D9',   # Stripe Indigo/Violet
    'pur_dim':     '#EDE9FE',   # Lavender pill fill
    'magenta':     '#DB2777',
    # Typography Hierarchy (Deep Navy-Slate Ink like Stripe #0d253d)
    'text':        '#0F172A',
    'text2':       '#1E293B',
    'text3':       '#475569',
    'dim':         '#64748B',
    'accent':      '#0284C7',
    'ring':        '#0284C7',
    'radius':      '10px',
}

# Active token dictionary mutated in-place so all importing modules stay synced
C = dict(THEME_DARK)


def is_dark_theme() -> bool:
    return C.get('mode', 'dark') == 'dark'


def _rgba(hexcolor: str, alpha: float) -> str:
    """Convert '#RRGGBB' + float alpha (0.0..1.0) into Qt-safe 'rgba(r,g,b,a)' (avoids Qt #AARRGGBB bug)."""
    h = str(hexcolor).lstrip('#')
    if len(h) >= 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    else:
        c = QColor(hexcolor)
        r, g, b = c.red(), c.green(), c.blue()
    a = max(0.0, min(1.0, float(alpha)))
    return f'rgba({r},{g},{b},{a:.2f})'


def set_theme_mode(mode: str) -> dict:
    """Switch global design tokens between 'dark' (Cyber) and 'light' (Harmonious)."""
    target = THEME_LIGHT if str(mode).lower() == 'light' else THEME_DARK
    C.clear()
    C.update(target)
    return C


UI      = "'Inter','Noto Sans','Segoe UI','Ubuntu','Cantarell',sans-serif"
MONO    = "'JetBrains Mono','Cascadia Code','Fira Code','Consolas','Share Tech Mono',monospace"
DISPLAY = "'Orbitron','Rajdhani','Oxanium','Exo 2','Inter',sans-serif"


def _global_check_icon_path() -> str:
    """Generate a crisp theme-aware checkmark PNG for QCheckBox and QTableWidget indicators."""
    fg_hex = '#060911' if is_dark_theme() else '#FFFFFF'
    tag = fg_hex.lstrip('#')
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation) or tempfile.gettempdir()
    d = os.path.join(base, 'cyberclean-ui')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = tempfile.gettempdir()
    path = os.path.join(d, f'chk-v4-{tag}.png')
    if not os.path.exists(path):
        pm = QPixmap(28, 28)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(fg_hex), 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(6.5, 14.5), QPointF(12.0, 20.0), QPointF(21.5, 8.5)]))
        p.end()
        pm.save(path, 'PNG')
    return path.replace('\\', '/')


def apply_elevation_shadow(widget: QWidget, blur: int = 20, y_offset: int = 4, alpha: int = -1):
    """Attach a subtle commercial drop shadow (soft ambient shadow in Light Mode, deep shadow in Dark Mode)."""
    try:
        eff = QGraphicsDropShadowEffect(widget)
        dark = is_dark_theme()
        eff.setBlurRadius(blur if not dark else max(14, blur - 2))
        eff.setOffset(0, y_offset)
        a = alpha if alpha >= 0 else (95 if dark else 22)
        eff.setColor(QColor(2, 6, 23, a) if dark else QColor(15, 23, 42, a))
        widget.setGraphicsEffect(eff)
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════
# PURE-CODE PROCEDURAL VECTOR ICONS — QPainter, zero file deps
# ═════════════════════════════════════════════════════════════

def _make_icon(draw_fn, size=22, color=None, active=False) -> QIcon:
    if color is None:
        color = C['cyan']
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(color)
    if active:
        glow = QRadialGradient(size / 2.0, size / 2.0, size * 0.48)
        gc = QColor(col)
        gc.setAlphaF(0.24 if is_dark_theme() else 0.15)
        gc0 = QColor(col)
        gc0.setAlphaF(0.0)
        glow.setColorAt(0.0, gc)
        glow.setColorAt(1.0, gc0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(0, 0, size, size))
    draw_fn(p, col, size)
    p.end()
    return QIcon(pix)


def _icon_dashboard(p: QPainter, col: QColor, s: int):
    """Asymmetric Bento HUD grid with glowing telemetry node."""
    pen = QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    fill = QColor(col); fill.setAlphaF(0.18)
    p.setBrush(QBrush(fill))
    pad = s * 0.12
    gap = s * 0.10
    w = (s - 2 * pad - gap) / 2.0
    h1 = (s - 2 * pad - gap) * 0.58
    h2 = (s - 2 * pad - gap) * 0.42
    p.drawRoundedRect(QRectF(pad, pad, w, h1), 2.2, 2.2)
    p.drawRoundedRect(QRectF(pad + w + gap, pad, w, h2), 2.2, 2.2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(pad, pad + h1 + gap, w, h2), 2.2, 2.2)
    p.setBrush(QBrush(fill))
    p.drawRoundedRect(QRectF(pad + w + gap, pad + h2 + gap, w, h1), 2.2, 2.2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(col))
    p.drawEllipse(QPointF(pad + w + gap + w * 0.5, pad + h2 + gap + h1 * 0.5), 1.6, 1.6)


def _icon_clean(p: QPainter, col: QColor, s: int):
    """Cyber Plasma Sweeper with energy sparkles."""
    pen = QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(s * 0.78, s * 0.14), QPointF(s * 0.42, s * 0.50))
    fill = QColor(col); fill.setAlphaF(0.20)
    p.setBrush(QBrush(fill))
    head = QPolygonF([
        QPointF(s * 0.34, s * 0.42),
        QPointF(s * 0.50, s * 0.58),
        QPointF(s * 0.30, s * 0.84),
        QPointF(s * 0.12, s * 0.66),
    ])
    p.drawPolygon(head)
    p.drawLine(QPointF(s * 0.22, s * 0.74), QPointF(s * 0.34, s * 0.60))
    p.drawLine(QPointF(s * 0.72, s * 0.58), QPointF(s * 0.86, s * 0.58))
    p.drawLine(QPointF(s * 0.79, s * 0.51), QPointF(s * 0.79, s * 0.65))
    p.drawLine(QPointF(s * 0.22, s * 0.24), QPointF(s * 0.32, s * 0.24))
    p.drawLine(QPointF(s * 0.27, s * 0.19), QPointF(s * 0.27, s * 0.29))


def _icon_deep_clean(p: QPainter, col: QColor, s: int):
    """Concentric Radar Target Scanner with sweep sector & crosshairs."""
    pen = QPen(col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    cx, cy = s * 0.50, s * 0.50
    r1, r2 = s * 0.38, s * 0.20
    sweep_col = QColor(col); sweep_col.setAlphaF(0.24)
    p.setBrush(QBrush(sweep_col))
    p.drawPie(QRectF(cx - r1, cy - r1, r1 * 2, r1 * 2), 15 * 16, 70 * 16)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r1, r1)
    p.drawEllipse(QPointF(cx, cy), r2, r2)
    p.drawLine(QPointF(cx - r1 * 1.15, cy), QPointF(cx - r2 * 0.7, cy))
    p.drawLine(QPointF(cx + r2 * 0.7, cy), QPointF(cx + r1 * 1.15, cy))
    p.drawLine(QPointF(cx, cy - r1 * 1.15), QPointF(cx, cy - r2 * 0.7))
    p.drawLine(QPointF(cx, cy + r2 * 0.7), QPointF(cx, cy + r1 * 1.15))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(col))
    p.drawEllipse(QPointF(cx + r1 * 0.42, cy - r1 * 0.42), 1.8, 1.8)


def _icon_advisor(p: QPainter, col: QColor, s: int):
    """3D Isometric Storage Cylinder + Exploded Sector."""
    pen = QPen(col, 1.45, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    cx, cy = s * 0.50, s * 0.50
    rx, ry = s * 0.36, s * 0.16
    top_y = cy - s * 0.16
    bot_y = cy + s * 0.18
    fill = QColor(col); fill.setAlphaF(0.18)
    p.setBrush(QBrush(fill))
    p.drawEllipse(QPointF(cx, top_y), rx, ry)
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(cx - rx, top_y)
    path.lineTo(cx - rx, bot_y)
    path.arcTo(QRectF(cx - rx, bot_y - ry, rx * 2, ry * 2), 180, 180)
    path.lineTo(cx + rx, top_y)
    p.drawPath(path)
    mid_y = (top_y + bot_y) * 0.5
    p.drawArc(QRectF(cx - rx, mid_y - ry, rx * 2, ry * 2), 180 * 16, 180 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(col))
    p.drawEllipse(QPointF(cx, top_y), 1.8, 1.2)


def _icon_uninstall(p: QPainter, col: QColor, s: int):
    """Modular App Cube with upward Eject/Purge vector arrow."""
    pen = QPen(col, 1.45, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    fill = QColor(col); fill.setAlphaF(0.15)
    p.setBrush(QBrush(fill))
    p.drawRoundedRect(QRectF(s * 0.18, s * 0.36, s * 0.64, s * 0.48), 2.5, 2.5)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx = s * 0.50
    p.drawLine(QPointF(cx, s * 0.66), QPointF(cx, s * 0.14))
    p.drawLine(QPointF(cx - s * 0.16, s * 0.28), QPointF(cx, s * 0.14))
    p.drawLine(QPointF(cx + s * 0.16, s * 0.28), QPointF(cx, s * 0.14))


def _icon_history(p: QPainter, col: QColor, s: int):
    """Chrono-Telemetry Dial with orbital arc and clock hands."""
    pen = QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy, r = s * 0.50, s * 0.52, s * 0.36
    p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 35 * 16, 290 * 16)
    ax, ay = cx + r * math.cos(math.radians(35)), cy - r * math.sin(math.radians(35))
    p.drawLine(QPointF(ax, ay), QPointF(ax - s * 0.14, ay - s * 0.04))
    p.drawLine(QPointF(ax, ay), QPointF(ax + s * 0.02, ay - s * 0.15))
    p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.58))
    p.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.46, cy + r * 0.18))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(col))
    p.drawEllipse(QPointF(cx, cy), 1.6, 1.6)


def _icon_rollback(p: QPainter, col: QColor, s: int):
    """Quantum Shield + Audit Restore emblem."""
    pen = QPen(col, 1.45, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    fill = QColor(col); fill.setAlphaF(0.16)
    p.setBrush(QBrush(fill))
    cx = s * 0.50
    shield = QPainterPath()
    shield.moveTo(cx, s * 0.12)
    shield.lineTo(s * 0.82, s * 0.24)
    shield.lineTo(s * 0.82, s * 0.50)
    shield.quadTo(s * 0.82, s * 0.78, cx, s * 0.88)
    shield.quadTo(s * 0.18, s * 0.78, s * 0.18, s * 0.50)
    shield.lineTo(s * 0.18, s * 0.24)
    shield.closeSubpath()
    p.drawPath(shield)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(s * 0.36, s * 0.50), QPointF(s * 0.46, s * 0.60))
    p.drawLine(QPointF(s * 0.46, s * 0.60), QPointF(s * 0.66, s * 0.38))


def _icon_booster(p: QPainter, col: QColor, s: int):
    """Aerodynamic Cyber Rocket + High-Voltage Core."""
    pen = QPen(col, 1.45, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    fill = QColor(col); fill.setAlphaF(0.22)
    p.setBrush(QBrush(fill))
    cx = s * 0.50
    body = QPainterPath()
    body.moveTo(cx, s * 0.10)
    body.quadTo(s * 0.72, s * 0.38, s * 0.66, s * 0.68)
    body.lineTo(s * 0.34, s * 0.68)
    body.quadTo(s * 0.28, s * 0.38, cx, s * 0.10)
    p.drawPath(body)
    p.drawLine(QPointF(s * 0.34, s * 0.56), QPointF(s * 0.20, s * 0.72))
    p.drawLine(QPointF(s * 0.20, s * 0.72), QPointF(s * 0.34, s * 0.68))
    p.drawLine(QPointF(s * 0.66, s * 0.56), QPointF(s * 0.80, s * 0.72))
    p.drawLine(QPointF(s * 0.80, s * 0.72), QPointF(s * 0.66, s * 0.68))
    p.drawLine(QPointF(s * 0.42, s * 0.72), QPointF(cx, s * 0.90))
    p.drawLine(QPointF(s * 0.58, s * 0.72), QPointF(cx, s * 0.90))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(col))
    p.drawEllipse(QPointF(cx, s * 0.42), 2.0, 2.0)


def _icon_sun(p: QPainter, col: QColor, s: int):
    """Procedural Sun icon for Light Mode switch."""
    pen = QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    fill = QColor(col); fill.setAlphaF(0.25)
    p.setBrush(QBrush(fill))
    cx, cy = s * 0.50, s * 0.50
    r = s * 0.22
    p.drawEllipse(QPointF(cx, cy), r, r)
    for i in range(8):
        ang = i * (math.pi / 4.0)
        p.drawLine(
            QPointF(cx + math.cos(ang) * (r * 1.35), cy + math.sin(ang) * (r * 1.35)),
            QPointF(cx + math.cos(ang) * (r * 1.85), cy + math.sin(ang) * (r * 1.85)),
        )


def _icon_moon(p: QPainter, col: QColor, s: int):
    """Procedural Crescent Moon + Cyber Star for Dark Mode switch."""
    pen = QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    fill = QColor(col); fill.setAlphaF(0.22)
    p.setBrush(QBrush(fill))
    cx, cy, r = s * 0.48, s * 0.52, s * 0.34
    path = QPainterPath()
    path.arcMoveTo(QRectF(cx - r, cy - r, r * 2, r * 2), 55)
    path.arcTo(QRectF(cx - r, cy - r, r * 2, r * 2), 55, 250)
    path.arcTo(QRectF(cx - r * 0.25, cy - r * 0.92, r * 1.65, r * 1.65), 245, -185)
    path.closeSubpath()
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(col))
    p.drawEllipse(QPointF(s * 0.76, s * 0.26), 1.5, 1.5)


_ICON_FN = {
    'deep_clean':  _icon_deep_clean,
    'advisor':     _icon_advisor,
    'dashboard':   _icon_dashboard,
    'smart_clean': _icon_clean,
    'uninstaller': _icon_uninstall,
    'history':     _icon_history,
    'rollback':    _icon_rollback,
    'booster':     _icon_booster,
    'sun':         _icon_sun,
    'moon':        _icon_moon,
}


def _nav_icon(name: str, active=False, size=20) -> QIcon:
    fn    = _ICON_FN.get(name, _icon_dashboard)
    color = C['cyan'] if active else C['text3']
    return _make_icon(fn, size=size, color=color, active=active)


def _theme_icon(is_dark: bool, size=18) -> QIcon:
    fn  = _icon_sun if is_dark else _icon_moon
    col = C['yellow'] if is_dark else C['purple']
    return _make_icon(fn, size=size, color=col, active=True)


# ═════════════════════════════════════════════════════════════════════════
# ELEVATED CARD — Linear/Raycast Specular Rim + Apple/Stripe Surface Depth
# ═════════════════════════════════════════════════════════════════════════

class ElevatedCard(QFrame):
    """
    Commercial-grade surface card with:
      • Multi-stop vertical surface gradient (bg2 -> bg2_grad)
      • Top 1px specular rim highlight (Linear/Raycast glass edge in Dark Mode;
        crisp inner sheen in Light Mode)
      • Optional left or top chromatic accent bar with soft glow
      • Soft ambient drop shadow in Light Mode & deep elevation in Dark Mode
    """

    def __init__(self, border_color=None, accent_color=None, top_accent=None, shadow=True, parent=None):
        super().__init__(parent)
        self.setObjectName('cyberCard')
        self._border_color = border_color
        self._accent_color = accent_color
        self._top_accent   = top_accent
        self._hovered      = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet(f'QFrame#cyberCard QLabel{{border:none;background:transparent;}}')
        if shadow:
            apply_elevation_shadow(self, blur=18, y_offset=3)

    def enterEvent(self, ev):
        self._hovered = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hovered = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        r = 10.0
        dark = is_dark_theme()

        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)

        # 1. Multi-stop vertical surface gradient
        grad = QLinearGradient(0, 0, 0, h)
        if dark:
            top_c = QColor('#131E35' if self._hovered else C['bg2'])
            bot_c = QColor('#0D1526' if self._hovered else C.get('bg2_grad', '#0A101D'))
        else:
            top_c = QColor('#FFFFFF')
            bot_c = QColor('#F8FAFF' if self._hovered else C.get('bg2_grad', '#F9FBFF'))
        grad.setColorAt(0.0, top_c)
        grad.setColorAt(1.0, bot_c)
        p.fillPath(path, QBrush(grad))

        # 2. Subtle radial top-left ambient sheen when accent is present
        accent_hex = self._accent_color or self._top_accent
        if accent_hex:
            ac = QColor(accent_hex)
            sheen = QRadialGradient(w * 0.15, 0, max(w, h) * 0.65)
            ac_start = QColor(ac)
            ac_start.setAlphaF(0.09 if dark else 0.05)
            ac_end = QColor(ac)
            ac_end.setAlphaF(0.0)
            sheen.setColorAt(0.0, ac_start)
            sheen.setColorAt(1.0, ac_end)
            p.fillPath(path, QBrush(sheen))

        # 3. Crisp outer border
        bc_hex = self._border_color or (C['border3'] if self._hovered else C['border2'])
        p.setPen(QPen(QColor(bc_hex), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # 4. Top 1px Specular Highlight (Linear/Raycast signature depth cue)
        spec_col = QColor(255, 255, 255, 26 if dark else 220)
        p.setPen(QPen(spec_col, 1.0))
        p.drawLine(QPointF(r, 1.5), QPointF(w - r, 1.5))

        # 5. Left or Top Accent Bar (clipped cleanly inside the rounded rect)
        if self._accent_color:
            p.save()
            p.setClipPath(path)
            ac = QColor(self._accent_color)
            p.fillRect(QRectF(0, 0, 3.5, h), QBrush(ac))
            p.restore()
        elif self._top_accent:
            p.save()
            p.setClipPath(path)
            ac = QColor(self._top_accent)
            tgrad = QLinearGradient(0, 0, w, 0)
            tgrad.setColorAt(0.0, ac)
            ac2 = QColor(ac); ac2.setAlphaF(0.35)
            tgrad.setColorAt(1.0, ac2)
            p.fillRect(QRectF(0, 0, w, 2.5), QBrush(tgrad))
            p.restore()

        p.end()


# ═════════════════════════════════════════════════════════════
# SPARKLINE CHART (Cubic Bézier + Neon Glow + Live Beacon)
# ═════════════════════════════════════════════════════════════
class SparklineChart(QWidget):
    def __init__(self, color=None, max_points=50, parent=None):
        super().__init__(parent)
        self._color_key = color if color in C else None
        self.color   = QColor(C.get(color, color) if color else C['cyan'])
        self.max_pts = max_points
        self.data    = []
        self.setMinimumHeight(76)
        self.setMaximumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet('background:transparent;')

    def push(self, value: float):
        self.data.append(max(0.0, min(100.0, value)))
        if len(self.data) > self.max_pts:
            self.data.pop(0)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, pad = self.width(), self.height(), 6

        grid_pen = QPen(QColor(C['border2'] if not is_dark_theme() else C['border']), 1, Qt.PenStyle.DotLine)
        p.setPen(grid_pen)
        for pct in (25, 50, 75):
            y = h - pad - (pct / 100.0) * (h - pad * 2)
            p.drawLine(0, int(y), w, int(y))

        if len(self.data) < 2:
            p.end()
            return

        pts = [
            QPointF(pad + (i / max(1, self.max_pts - 1)) * (w - pad * 2),
                    h - pad - (v / 100.0) * (h - pad * 2))
            for i, v in enumerate(self.data)
        ]

        curve = QPainterPath()
        curve.moveTo(pts[0])
        for i in range(len(pts) - 1):
            p0, p1 = pts[i], pts[i + 1]
            cx = (p0.x() + p1.x()) / 2.0
            curve.cubicTo(QPointF(cx, p0.y()), QPointF(cx, p1.y()), p1)

        fill_path = QPainterPath(curve)
        fill_path.lineTo(pts[-1].x(), h)
        fill_path.lineTo(pts[0].x(), h)
        fill_path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        fc = QColor(self.color); fc.setAlphaF(0.28 if is_dark_theme() else 0.20)
        fc2 = QColor(self.color); fc2.setAlphaF(0.01)
        grad.setColorAt(0.0, fc)
        grad.setColorAt(1.0, fc2)
        p.fillPath(fill_path, QBrush(grad))

        glow_col = QColor(self.color)
        glow_col.setAlphaF(0.25 if is_dark_theme() else 0.14)
        p.setPen(QPen(glow_col, 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(curve)

        p.setPen(QPen(self.color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(curve)

        last = pts[-1]
        halo = QColor(self.color); halo.setAlphaF(0.26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(last, 6.5, 6.5)
        p.setBrush(QBrush(self.color))
        p.drawEllipse(last, 3.2, 3.2)
        p.end()


# ═════════════════════════════════════════════════════════════
# 3D PERSPECTIVE PROJECTION ENGINE & HOLOGRAPHIC DISK CORES
# ═════════════════════════════════════════════════════════════

class Point3D:
    """Lightweight 3D vector with affine rotation and perspective projection."""
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x: float, y: float, z: float):
        self.x, self.y, self.z = x, y, z

    def rotate_x(self, deg: float) -> 'Point3D':
        rad = math.radians(deg)
        c, s = math.cos(rad), math.sin(rad)
        return Point3D(self.x, self.y * c - self.z * s, self.y * s + self.z * c)

    def rotate_y(self, deg: float) -> 'Point3D':
        rad = math.radians(deg)
        c, s = math.cos(rad), math.sin(rad)
        return Point3D(self.x * c + self.z * s, self.y, -self.x * s + self.z * c)

    def rotate_z(self, deg: float) -> 'Point3D':
        rad = math.radians(deg)
        c, s = math.cos(rad), math.sin(rad)
        return Point3D(self.x * c - self.y * s, self.x * s + self.y * c, self.z)

    def project(self, cx: float, cy: float, fov: float = 220.0, dist: float = 260.0) -> Tuple[float, float, float]:
        denom = dist + self.z
        factor = fov / denom if denom > 1.0 else 1.0
        return self.x * factor + cx, self.y * factor + cy, factor


class Cyber3DDiskCore(QWidget):
    """
    Interactive 3D Holographic Disk Core (Dashboard Hero):
      • 3D perspective-projected orbital gyroscope rings
      • Depth-occluded stroke shading (near segments thicker & brighter)
      • 3D floating quantum particle field
      • Interactive mouse-tilt (tilts in 3D toward cursor)
      • COLLISION-FREE READOUT: Percentage sits inside the 3D sphere, while
        the "Used / Total GB" badge sits in a sleek HUD pill BELOW the 3D sphere
        so text NEVER collides with the sphere rim or rotating 3D rings!
    """

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self.percent = 0.0
        self.used_str = ''
        self.total_str = ''
        self._compact = compact
        if compact:
            self.setFixedSize(112, 112)
        else:
            self.setMinimumSize(196, 152)
            self.setMaximumHeight(184)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)

        self._rot_x = 24.0
        self._rot_y = 0.0
        self._target_rot_x = 24.0
        self._target_rot_y = 0.0
        self._pulse = 0.0

        radius = 38.0 if compact else 47.0
        self._ring1: List[Point3D] = []
        self._ring2: List[Point3D] = []
        self._ring3: List[Point3D] = []
        n_seg = 44
        for i in range(n_seg):
            a = (i / n_seg) * math.pi * 2.0
            self._ring1.append(Point3D(radius * math.cos(a), 0.0, radius * math.sin(a)))
            self._ring2.append(Point3D(0.0, (radius * 0.86) * math.cos(a), (radius * 0.86) * math.sin(a)))
            self._ring3.append(Point3D((radius * 1.06) * math.cos(a), (radius * 1.06) * math.sin(a), 0.0))

        self._particles: List[Point3D] = []
        p_count = 16 if compact else 26
        for i in range(p_count):
            theta = (i / p_count) * math.pi * 2.0
            pr = radius * (1.10 + (i % 3) * 0.07)
            py = ((i % 5) - 2) * (4.0 if compact else 5.5)
            self._particles.append(Point3D(pr * math.cos(theta), py, pr * math.sin(theta)))

        self._hover = False
        self._intro_ticks = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # Adaptive: 33ms (~30 FPS) on intro/hover, throttles to 120ms (~8 FPS) when idle

    def set_percent(self, v: float):
        self.percent = float(v)
        self.update()

    def set_usage_detail(self, pct: float, used_str: str = '', total_str: str = ''):
        self.percent = float(pct)
        self.used_str = used_str
        self.total_str = total_str
        self.update()

    def showEvent(self, ev):
        self._intro_ticks = 0
        self._timer.start(33)
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def enterEvent(self, event):
        self._hover = True
        if self.isVisible():
            self._timer.setInterval(33)
        super().enterEvent(event)

    def mouseMoveEvent(self, event):
        w, h = max(1.0, float(self.width())), max(1.0, float(self.height()))
        rx = (event.position().x() - w / 2.0) / (w / 2.0)
        ry = (event.position().y() - h / 2.0) / (h / 2.0)
        self._target_rot_y = rx * 28.0
        self._target_rot_x = 24.0 - ry * 22.0
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._target_rot_x = 24.0
        self._target_rot_y = 0.0
        if self._timer.isActive():
            self._timer.setInterval(120)
        super().leaveEvent(event)

    def _tick(self):
        if not self.isVisible():
            self._timer.stop()
            return
        win = self.window()
        if win is not None and win.isMinimized():
            self._timer.stop()
            return
        self._intro_ticks += 1
        if self._intro_ticks > 60 and not self._hover and self._timer.interval() != 120:
            self._timer.setInterval(120)
        step = 1.35 if self._timer.interval() <= 40 else 2.2
        self._rot_y = (self._rot_y + step) % 360.0
        self._rot_x += (self._target_rot_x - self._rot_x) * 0.16
        self._pulse = (self._pulse + 0.07) % (math.pi * 2.0)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        has_pill = bool(self.used_str and not self._compact)
        # Shift 3D sphere center slightly up when bottom capacity pill is visible so there is zero overlap
        cx = w / 2.0
        cy = (h - 24.0) / 2.0 if has_pill else h / 2.0
        dark = is_dark_theme()

        primary_hex = C['red'] if self.percent > 90 else C['yellow'] if self.percent > 75 else C['cyan']
        col_primary = QColor(primary_hex)
        col_secondary = QColor(C.get('purple', '#A855F7'))

        # Ambient radial glow
        glow_r = min(w, h) * 0.44
        glow = QRadialGradient(cx, cy, glow_r)
        g1 = QColor(col_primary); g1.setAlphaF(0.20 if dark else 0.12)
        g2 = QColor(col_secondary); g2.setAlphaF(0.07 if dark else 0.04)
        g3 = QColor(col_primary); g3.setAlphaF(0.0)
        glow.setColorAt(0.0, g1)
        glow.setColorAt(0.65, g2)
        glow.setColorAt(1.0, g3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        def draw_3d_ring(pts: List[Point3D], y_off: float, z_tilt: float, col: QColor, ratio: float = 1.0, base_w: float = 2.2):
            proj = []
            for pt in pts:
                r_pt = pt.rotate_z(z_tilt).rotate_y(self._rot_y + y_off).rotate_x(self._rot_x + self._target_rot_y * 0.15)
                px, py, f = r_pt.project(cx, cy, fov=215.0, dist=255.0)
                proj.append((px, py, r_pt.z, f))

            n_total = len(proj)
            n_active = max(1, int(n_total * min(1.0, max(0.02, ratio))))
            for i in range(n_total):
                p1 = proj[i]
                p2 = proj[(i + 1) % n_total]
                avg_z = (p1[2] + p2[2]) * 0.5
                if i < n_active:
                    alpha = int(max(50, min(255, (175 if dark else 200) - avg_z * 1.6)))
                    thick = max(1.1, min(3.6, base_w - avg_z * 0.02))
                    sc = QColor(col.red(), col.green(), col.blue(), alpha)
                else:
                    track_c = QColor(C['border3'])
                    track_c.setAlpha(60 if dark else 85)
                    sc = track_c
                    thick = 1.0
                p.setPen(QPen(sc, thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        usage_ratio = min(1.0, max(0.0, self.percent / 100.0))
        draw_3d_ring(self._ring3, -self._rot_y * 1.4, 32.0, QColor(C['cyan2']), ratio=1.0, base_w=1.2)
        draw_3d_ring(self._ring2, 55.0, -18.0, col_secondary, ratio=0.82, base_w=1.6)
        draw_3d_ring(self._ring1, 0.0, 8.0, col_primary, ratio=usage_ratio, base_w=2.6)

        for pt in self._particles:
            r_pt = pt.rotate_y(self._rot_y * 1.4).rotate_x(self._rot_x)
            px, py, f = r_pt.project(cx, cy, fov=215.0, dist=255.0)
            p_alpha = int(max(30, min(210, 130 - r_pt.z * 1.5)))
            p_sz = max(1.0, min(2.8, 1.8 * f))
            pc = QColor(col_primary.red(), col_primary.green(), col_primary.blue(), p_alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(pc))
            p.drawEllipse(QPointF(px, py), p_sz, p_sz)

        # Central 3D Hologram Core Sphere
        pulse_s = 1.0 + 0.022 * math.sin(self._pulse)
        core_r = (24.0 if self._compact else 31.0) * pulse_s
        sphere = QRadialGradient(cx - core_r * 0.25, cy - core_r * 0.25, core_r * 1.2)
        if dark:
            sphere.setColorAt(0.0, QColor(24, 38, 64, 242))
            sphere.setColorAt(0.72, QColor(9, 14, 26, 248))
            rim = QColor(col_primary); rim.setAlpha(165)
            sphere.setColorAt(1.0, rim)
        else:
            sphere.setColorAt(0.0, QColor(255, 255, 255, 252))
            sphere.setColorAt(0.75, QColor(238, 244, 252, 250))
            rim = QColor(col_primary); rim.setAlpha(135)
            sphere.setColorAt(1.0, rim)

        p.setBrush(QBrush(sphere))
        p.setPen(QPen(col_primary, 1.6))
        p.drawEllipse(QPointF(cx, cy), core_r, core_r)

        # Crisp Percentage Readout centered inside the sphere (NEVER collides with used_str!)
        pct_txt = f'{self.percent:.1f}%' if self.percent < 99.95 else f'{round(self.percent)}%'
        font_sz = 10 if self._compact else 12
        p.setFont(QFont('JetBrains Mono' if not IS_WINDOWS else 'Cascadia Code', font_sz, QFont.Weight.Bold))
        p.setPen(QColor(C['text']))
        p.drawText(QRectF(cx - core_r, cy - 10, core_r * 2.0, 20), Qt.AlignmentFlag.AlignCenter, pct_txt)

        # External HUD Pill at the bottom of the widget for "30.2 GB / 47.3 GB"
        if has_pill:
            pill_w = min(w - 12.0, 146.0)
            pill_h = 20.0
            pill_x = cx - pill_w / 2.0
            pill_y = h - pill_h - 2.0
            pill_rect = QRectF(pill_x, pill_y, pill_w, pill_h)
            pill_bg = QColor(C['cyan_dim'] if self.percent <= 75 else (C['yel_dim'] if self.percent <= 90 else C['red_dim']))
            if dark:
                pill_bg.setAlpha(190)
            p.setBrush(QBrush(pill_bg))
            b_col = QColor(col_primary); b_col.setAlpha(110)
            p.setPen(QPen(b_col, 1.0))
            p.drawRoundedRect(pill_rect, 6.0, 6.0)

            f_pill = QFont('JetBrains Mono' if not IS_WINDOWS else 'Cascadia Code')
            f_pill.setPixelSize(10)
            f_pill.setBold(True)
            p.setFont(f_pill)
            p.setPen(col_primary if dark else QColor(C['text']))
            p.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, self.used_str)

        p.end()


class DiskRing(QWidget):
    """
    Sidebar Precision 2.5D Segmented Telemetry Gauge:
    Replaces the duplicate 3D gyroscope in the sidebar with a clean, ultra-crisp
    precision segmented arc meter (Raycast / macOS Activity Monitor style) so the
    Sidebar and Dashboard complement each other rather than duplicating the 3D sphere.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.percent = 0.0
        self.setFixedSize(112, 86)

    def set_percent(self, v: float):
        self.percent = max(0.0, min(100.0, float(v)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2.0, h * 0.56
        r = 34.0
        dark = is_dark_theme()

        primary_hex = C['red'] if self.percent > 90 else C['yellow'] if self.percent > 75 else C['cyan']
        col = QColor(primary_hex)
        track = QColor(C['border2'] if not dark else C['bg3'])

        # 240-degree precision arc gauge (from 210 deg to -30 deg)
        rect = QRectF(cx - r, cy - r, r * 2.0, r * 2.0)
        start_deg = 210
        span_deg  = -240

        # Background track arc
        p.setPen(QPen(track, 6.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, start_deg * 16, span_deg * 16)

        # Soft glow arc
        active_span = int(span_deg * (self.percent / 100.0) * 16)
        if abs(active_span) > 0:
            glow_c = QColor(col)
            glow_c.setAlphaF(0.28 if dark else 0.16)
            p.setPen(QPen(glow_c, 11.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, start_deg * 16, active_span)

            p.setPen(QPen(col, 6.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, start_deg * 16, active_span)

        # Inner tick marks
        p.setPen(QPen(QColor(C['border3']), 1.0))
        for i in range(9):
            ang = math.radians(210 - i * 30)
            r_in, r_out = r - 9.0, r - 6.5
            p.drawLine(
                QPointF(cx + r_in * math.cos(ang), cy - r_in * math.sin(ang)),
                QPointF(cx + r_out * math.cos(ang), cy - r_out * math.sin(ang)),
            )

        # Center percentage text
        pct_txt = f'{self.percent:.1f}%' if self.percent < 99.95 else f'{round(self.percent)}%'
        f_val = QFont('JetBrains Mono' if not IS_WINDOWS else 'Cascadia Code')
        f_val.setPixelSize(13)
        f_val.setBold(True)
        p.setFont(f_val)
        p.setPen(QColor(C['text']))
        p.drawText(QRectF(cx - 34, cy - 11, 68, 20), Qt.AlignmentFlag.AlignCenter, pct_txt)

        # Sub-caption "USED"
        f_sub = QFont('Inter')
        f_sub.setPixelSize(8)
        f_sub.setBold(True)
        p.setFont(f_sub)
        p.setPen(col)
        p.drawText(QRectF(cx - 28, cy + 8, 56, 12), Qt.AlignmentFlag.AlignCenter, 'STORAGE')
        p.end()


# ═════════════════════════════════════════════════════════════
# HEX LOGO WIDGET (Animated 3D Cyber Hex Emblem)
# ═════════════════════════════════════════════════════════════
class HexLogoWidget(QWidget):
    def __init__(self, size=32, parent=None):
        super().__init__(parent)
        self.s = size
        self._angle = 0.0
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, s = self.s / 2.0, self.s / 2.0, self.s / 2.0 - 2.0

        def hex_pts(cx_, cy_, r_, offset_deg=0.0):
            return [
                QPointF(cx_ + r_ * math.cos(math.radians(60 * i - 30 + offset_deg)),
                        cy_ + r_ * math.sin(math.radians(60 * i - 30 + offset_deg)))
                for i in range(6)
            ]

        outer_col = QColor(C['cyan']); outer_col.setAlphaF(0.92)
        p.setPen(QPen(outer_col, 1.6))
        grad = QRadialGradient(cx, cy, s)
        g0 = QColor(C['cyan']); g0.setAlphaF(0.24 if is_dark_theme() else 0.16)
        g1 = QColor(C['cyan']); g1.setAlphaF(0.02)
        grad.setColorAt(0.0, g0)
        grad.setColorAt(1.0, g1)
        p.setBrush(QBrush(grad))
        p.drawPolygon(QPolygonF(hex_pts(cx, cy, s)))

        border_col = QColor(C.get('purple', '#A855F7')); border_col.setAlphaF(0.55)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(border_col, 1.0))
        p.drawPolygon(QPolygonF(hex_pts(cx, cy, s * 0.68, offset_deg=30.0)))

        p.setPen(QPen(QColor(C['cyan'])))
        p.setFont(QFont('Share Tech Mono', max(7, int(self.s * 0.28)), QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, self.s, self.s), Qt.AlignmentFlag.AlignCenter, 'CC')
        p.end()


# ═════════════════════════════════════════════════════════════
# UI HELPERS
# ═════════════════════════════════════════════════════════════

def _btn(text, color='cyan', small=False, icon_only=False):
    col     = C.get(color, C['cyan'])
    col_dim = C.get(color + '_dim', C['bg3'])
    pad     = '6px 14px' if small else '8px 18px'
    sz      = '12px'     if small else '13px'
    minh    = '30px'     if small else '36px'
    dark    = is_dark_theme()
    border_col   = _rgba(col, 0.42 if dark else 0.55)
    hover_bg     = _rgba(col, 0.16 if dark else 0.13)
    press_bg     = _rgba(col, 0.25 if dark else 0.22)

    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setMinimumHeight(30 if small else 36)
    btn.setStyleSheet(f"""
        QPushButton {{
            color:{col};
            border:1px solid {border_col};
            background:{col_dim};
            font-family:{UI}; font-size:{sz};
            letter-spacing:0.5px; padding:{pad};
            border-radius:8px; font-weight:700;
            min-height:{minh};
        }}
        QPushButton:hover   {{ background:{hover_bg}; border-color:{col}; color:{col}; }}
        QPushButton:pressed {{ background:{press_bg}; border-color:{col}; }}
        QPushButton:checked {{ background:{hover_bg}; border-color:{col}; color:{col}; }}
        QPushButton:focus   {{ border:2px solid {C['ring']}; }}
        QPushButton:disabled {{ color:{C['dim']}; border-color:{C['border2']}; background:transparent; }}
    """)
    return btn


def _lbl_section(text):
    l = QLabel(text)
    l.setStyleSheet(
        f'color:{C["text3"]};font-size:11px;letter-spacing:1.5px;'
        f'font-family:{UI};padding:4px 0 2px 0;font-weight:700;border:none;background:transparent;'
    )
    return l


def _lbl_val(text, color='cyan', size=20):
    l = QLabel(text)
    l.setStyleSheet(
        f'color:{C.get(color, C["cyan"])};font-size:{size}px;font-weight:700;'
        f'font-family:{MONO};letter-spacing:0.5px;border:none;background:transparent;'
    )
    return l


def _card(border_color=None, accent_color=None, top_accent=None, shadow=True):
    """Return an ElevatedCard with multi-stop surface gradient, specular rim, and elevation shadow."""
    f = ElevatedCard(
        border_color=border_color,
        accent_color=accent_color,
        top_accent=top_accent,
        shadow=shadow,
    )
    f.setObjectName('cyberCard')
    return f


def _divider():
    l = QFrame()
    l.setFrameShape(QFrame.Shape.HLine)
    l.setStyleSheet(
        f'color:{C["border2"]};background:{C["border2"]};border:none;max-height:1px;'
    )
    return l


# ═════════════════════════════════════════════════════════════
# STAT CARD (With Specular Rim, Micro Progress Bar & Depth)
# ═════════════════════════════════════════════════════════════
class StatCard(ElevatedCard):
    def __init__(self, label, init_val, color='cyan', parent=None):
        col = C.get(color, C['cyan'])
        super().__init__(top_accent=col, shadow=True, parent=parent)
        self.setObjectName('statCard')
        self.setStyleSheet(f'QFrame#statCard QLabel{{border:none;background:transparent;}}')
        self.color = color
        self.setMinimumHeight(76)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        self.lbl_name = QLabel(label)
        self.lbl_name.setStyleSheet(
            f'color:{C["text3"]};font-size:11px;letter-spacing:1.3px;'
            f'font-family:{UI};font-weight:700;border:none;background:transparent;'
        )
        self._dot = QLabel('●')
        self._dot.setStyleSheet(f'color:{col};font-size:8px;border:none;background:transparent;')
        top_row.addWidget(self.lbl_name)
        top_row.addStretch()
        top_row.addWidget(self._dot)

        self.lbl_val = QLabel(init_val)
        self.lbl_val.setStyleSheet(
            f'color:{C["text"] if not is_dark_theme() else col};font-size:22px;font-weight:700;'
            f'font-family:{MONO};letter-spacing:0.4px;border:none;background:transparent;'
        )
        lay.addLayout(top_row)
        lay.addWidget(self.lbl_val)

    def set_val(self, text, color=None):
        self.lbl_val.setText(text)
        col = C.get(color or self.color, C.get(self.color, C['cyan']))
        self._top_accent = col
        self._dot.setStyleSheet(f'color:{col};font-size:8px;border:none;background:transparent;')
        val_col = col if is_dark_theme() else (col if color in ('red', 'yellow') else C['text'])
        self.lbl_val.setStyleSheet(
            f'color:{val_col};font-size:22px;font-weight:700;'
            f'font-family:{MONO};letter-spacing:0.4px;border:none;background:transparent;'
        )
        self.update()


# ═════════════════════════════════════════════════════════════
# EMPTY TABLE OVERLAY (Centered Card Badge inside Table Viewport)
# ═════════════════════════════════════════════════════════════
class EmptyStateBinder(QObject):
    """Shows a rich centered empty state inside a QTableWidget viewport when it has 0 rows."""

    def __init__(self, table: QTableWidget, title: str, body: str, icon_char: str = '✓', parent=None):
        super().__init__(parent or table)
        self._table = table
        self._icon_char = icon_char
        overlay = QLabel(table.viewport())
        overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay.setWordWrap(True)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.setStyleSheet(
            f'QLabel{{background:transparent;color:{C["text2"]};'
            f'font-family:{UI};padding:28px;}}'
        )
        self._overlay = overlay
        self.set_copy(title, body)
        table.viewport().installEventFilter(self)
        model = table.model()
        if model is not None:
            model.rowsInserted.connect(self.sync)
            model.rowsRemoved.connect(self.sync)
            model.modelReset.connect(self.sync)
        self.sync()

    def set_copy(self, title: str, body: str):
        badge_bg = C['cyan_dim']
        badge_fg = C['cyan']
        self._overlay.setText(
            f'<div style="margin-bottom:10px;">'
            f'<span style="background:{badge_bg};color:{badge_fg};font-size:18px;'
            f'font-weight:700;padding:6px 14px;border-radius:12px;">{self._icon_char}</span>'
            f'</div>'
            f'<div style="font-size:15px;font-weight:700;color:{C["text"]};'
            f'margin-bottom:6px;">{title}</div>'
            f'<div style="font-size:12px;line-height:1.5;color:{C["text3"]};'
            f'max-width:420px;">{body}</div>'
        )
        self.sync()

    def eventFilter(self, obj, event):
        try:
            if obj is self._table.viewport() and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Show
            ):
                self.sync()
        except RuntimeError:
            return False
        return False

    def sync(self, *args):
        try:
            vp = self._table.viewport()
            self._overlay.setGeometry(vp.rect())
            empty = self._table.rowCount() == 0
            self._overlay.setVisible(empty)
            if empty:
                self._overlay.raise_()
        except RuntimeError:
            return


# ═════════════════════════════════════════════════════════════
# NAV BUTTON (Fluid Pill Hover & Procedural Vector Icon)
# ═════════════════════════════════════════════════════════════
class NavButton(QWidget):
    """
    Sidebar Navigation Item rendered 100% via native QPainter.
    Immune to QSS child-widget margin cascading and HiDPI pixmap clipping,
    guaranteeing full, razor-sharp 20x20 procedural vector icons in both Dark & Light modes.
    """
    clicked = pyqtSignal()

    def __init__(self, label: str, icon_name: str, parent=None):
        super().__init__(parent)
        self._active    = False
        self._hovered   = False
        self._compact   = False
        self._icon_name = icon_name
        self._label_str = label
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setToolTip(label)

    def set_active(self, active: bool):
        self._active = bool(active)
        self.update()

    def set_label(self, text: str):
        self._label_str = text
        self.setToolTip(text)
        self.update()

    def set_compact(self, compact: bool):
        if self._compact == compact:
            return
        self._compact = bool(compact)
        self.update()

    def enterEvent(self, ev):
        self._hovered = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hovered = False
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, _):
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        dark = is_dark_theme()

        # 1. Outer rounded pill container (inset 8px horizontally, 2px vertically)
        pill_rect = QRectF(8.0, 2.0, max(10.0, w - 16.0), max(10.0, h - 4.0))
        if self._active:
            if dark:
                bg_c = QColor(C['cyan']); bg_c.setAlphaF(0.13)
                bd_c = QColor(C['cyan']); bd_c.setAlphaF(0.38)
            else:
                bg_c = QColor(C['cyan_dim'])
                bd_c = QColor(C['cyan']); bd_c.setAlphaF(0.45)
            p.setBrush(QBrush(bg_c))
            p.setPen(QPen(bd_c, 1.0))
            p.drawRoundedRect(pill_rect, 8.0, 8.0)

            # Left active indicator bar
            bar_h = 20.0
            bar_rect = QRectF(12.0, (h - bar_h) / 2.0, 3.2, bar_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(C['cyan'])))
            p.drawRoundedRect(bar_rect, 1.6, 1.6)
        elif self._hovered:
            if dark:
                bg_c = QColor(C['cyan']); bg_c.setAlphaF(0.07)
            else:
                bg_c = QColor(C['bg3'])
            p.setBrush(QBrush(bg_c))
            p.setPen(QPen(QColor(C['border2']), 1.0))
            p.drawRoundedRect(pill_rect, 8.0, 8.0)

        # 2. Full 20x20 Procedural Vector Icon (drawn directly on QPainter at native DPI)
        ico_s = 20.0
        ix = (w - ico_s) / 2.0 if self._compact else 22.0
        iy = (h - ico_s) / 2.0

        if self._active:
            icon_col = QColor(C['cyan'])
            glow = QRadialGradient(ix + ico_s * 0.5, iy + ico_s * 0.5, ico_s * 0.62)
            gc = QColor(C['cyan']); gc.setAlphaF(0.22 if dark else 0.14)
            gc0 = QColor(C['cyan']); gc0.setAlphaF(0.0)
            glow.setColorAt(0.0, gc)
            glow.setColorAt(1.0, gc0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QRectF(ix - 2.0, iy - 2.0, ico_s + 4.0, ico_s + 4.0))
        elif self._hovered:
            icon_col = QColor(C['text'])
        else:
            # Use text2 in Light Mode so inactive sidebar icons are crisp and clearly legible
            icon_col = QColor(C['text3'] if dark else C['text2'])

        draw_fn = _ICON_FN.get(self._icon_name, _icon_dashboard)
        p.save()
        p.translate(ix, iy)
        draw_fn(p, icon_col, int(ico_s))
        p.restore()

        # 3. Navigation Label
        if not self._compact:
            if self._active:
                txt_col = QColor(C['cyan'] if dark else C['text'])
            elif self._hovered:
                txt_col = QColor(C['text'])
            else:
                txt_col = QColor(C['text3'] if dark else C['text2'])

            f = QFont('Inter' if not IS_WINDOWS else 'Segoe UI')
            f.setPixelSize(12)
            f.setWeight(QFont.Weight.Bold if self._active else QFont.Weight.DemiBold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
            p.setFont(f)
            p.setPen(txt_col)
            txt_rect = QRectF(50.0, 0.0, max(10.0, w - 58.0), h)
            p.drawText(txt_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._label_str)

        p.end()


# ═════════════════════════════════════════════════════════════
# CYBER TERMINAL — custom log output cho clean / scan pages
# ═════════════════════════════════════════════════════════════

class CyberTerminal(QWidget):
    """Cyberpunk / Harmonious Light terminal log widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    @property
    def _LEVEL(self):
        return {
            'ok':   (C['green'],  '  ✓  '),
            'err':  (C['red'],    '  ✗  '),
            'dry':  (C['yellow'], '  ~  '),
            'head': (C['cyan'],   ''),
            'info': (C['text3'],  ''),
            'warn': (C['yellow'], '  !  '),
            'text': (C['text2'],  ''),
            'dim':  (C['text3'],  ''),
        }

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QFrame()
        hdr.setObjectName('termHdr')
        hdr.setFixedHeight(32)
        hdr.setStyleSheet(
            f'QFrame#termHdr{{background:{C["bg3"]};'
            f'border-top:1px solid {C["border2"]};'
            f'border-left:1px solid {C["border2"]};'
            f'border-right:1px solid {C["border2"]};'
            f'border-bottom:1px solid {C["border2"]};'
            f'border-top-left-radius:{C["radius"]};border-top-right-radius:{C["radius"]};}}'
            f'QFrame#termHdr QLabel{{border:none;background:transparent;}}'
        )
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(12, 0, 12, 0)
        hdr_lay.setSpacing(6)
        for col in (C['red'], C['yellow'], C['green']):
            dot = QFrame()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(
                f'QFrame{{background:{_rgba(col, 0.35)};border:1px solid {col};'
                f'border-radius:4px;}}'
            )
            hdr_lay.addWidget(dot)
        hdr_lay.addStretch()
        self._hdr_lbl = QLabel('TERMINAL OUTPUT')
        self._hdr_lbl.setStyleSheet(
            f'color:{C["text3"]};font-size:10px;letter-spacing:2px;font-family:{UI};font-weight:700;'
        )
        hdr_lay.addWidget(self._hdr_lbl)
        hdr_lay.addStretch()
        root.addWidget(hdr)

        self._te = QPlainTextEdit()
        self._te.setReadOnly(True)
        self._te.setMaximumBlockCount(600)
        self._te.document().setMaximumBlockCount(600)
        term_bg = C.get('well_bg', C['bg'])
        self._te.setStyleSheet(f'''
            QPlainTextEdit {{
                background: {term_bg};
                color: {C["text2"]};
                border-left: 1px solid {C["border2"]};
                border-right: 1px solid {C["border2"]};
                border-bottom: 1px solid {C["border2"]};
                border-bottom-left-radius: {C["radius"]};
                border-bottom-right-radius: {C["radius"]};
                border-top: none;
                font-family: {MONO};
                font-size: 12px;
                padding: 12px 16px;
                selection-background-color: {_rgba(C["cyan"], 0.18)};
                line-height: 1.55;
            }}
            QScrollBar:vertical {{
                background: {term_bg};
                width: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C["border3"]};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {_rgba(C["cyan"], 0.55)};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        ''')
        root.addWidget(self._te, 1)

    _MAX_LOG_LINES = 500

    def append_log(self, msg: str, level: str = 'text'):
        col, _prefix = self._LEVEL.get(level, (C['text2'], ''))
        doc = self._te.document()
        if doc.blockCount() > self._MAX_LOG_LINES:
            cursor = self._te.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            for _ in range(100):
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()

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
# ═════════════════════════════════════════════════════════════

class SysInfoWorker(QThread):
    snapshot = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        import threading as _th
        self.paused   = False
        self._stopped = False
        self._force_refresh = False
        self._wake = _th.Event()

    def stop(self):
        self._stopped = True
        self._wake.set()

    def force_refresh(self):
        """Trigger an immediate non-blocking snapshot on the worker thread."""
        self._force_refresh = True
        self._wake.set()

    def run(self):
        from utils.sysinfo import get_snapshot
        while not self._stopped:
            if not self.paused or self._force_refresh:
                iv = 0.15 if self._force_refresh else 0.3
                self._force_refresh = False
                try:
                    self.snapshot.emit(get_snapshot(interval=iv))
                except Exception:
                    pass
            self._wake.wait(4.0)
            self._wake.clear()


class CleanWorker(QThread):
    log           = pyqtSignal(str, str)
    progress      = pyqtSignal(int, str)
    done          = pyqtSignal(dict)
    target_status = pyqtSignal(str, int, str)

    _TARGET_TIMEOUT = 120

    def __init__(self, targets, dry=True, cleaner=None, plans=None):
        super().__init__()
        self.targets = targets
        self.dry     = dry
        self._cleaner = cleaner
        self._plans   = dict(plans) if isinstance(plans, dict) else {}
        self._stop_requested = False
        import threading as _th
        self._finished_event = _th.Event()

    def stop(self):
        self._stop_requested = True
        try:
            from core import privileged as _PRIV
            _PRIV.request_cancel_helpers()
        except Exception:
            pass

    def run(self):
        from utils.sysinfo import fmt_size
        self._finished_event.clear()
        try:
            from core import engine as _E
            _E.set_stop_requested(lambda: self._stop_requested)
        except Exception:
            _E = None
        try:
            from core import privileged as _PRIV
            if not self._stop_requested:
                _PRIV.clear_cancel_helpers()
        except Exception:
            _PRIV = None
        CLEANER = self._cleaner
        total_freed = 0; rollback = []; summary = []
        total_planned = 0; measured_sum = 0; has_measured = False
        steps = max(len(self.targets), 1)
        out_plans = {}

        def _report_extras(result):
            notes = getattr(result, 'notes', []) or []
            for n in notes:
                self.log.emit(_tlog(f'  ⚠  {n}'), 'warn')
            sk = getattr(result, 'skipped', []) or []
            if sk and not self.dry:
                self.log.emit(_tlog(f'  –  {len(sk)} item(s) skipped (in use / changed since the scan)'), 'dry')
            blk = int(getattr(result, 'blocked', 0) or 0)
            lock_note = next((n for n in notes if 'running' in n.lower() or 'close' in n.lower()), '')
            if blk > 0 or lock_note:
                self.target_status.emit(result.target_id, max(blk, 1), lock_note or (notes[0] if notes else ''))
            else:
                self.target_status.emit(result.target_id, 0, '')

        try:
            self.log.emit('─' * 44, 'head')
            mode = 'DRY-RUN' if self.dry else 'CLEAN'
            self.log.emit(f'  {_tlog(mode)}  ·  {datetime.now().strftime("%H:%M:%S")}', 'head')
            self.log.emit('─' * 44, 'head')

            if self.dry and hasattr(CLEANER, 'estimate_parallel'):
                self.progress.emit(5, _t('review_scanning', 'Scanning...'))

                def _on_scan_progress(pct, label):
                    self.progress.emit(5 + int(pct * 0.90), f'{_t("review_scanning", "Scanning…")} {label}')

                try:
                    results_map = CLEANER.estimate_parallel(
                        self.targets, progress_cb=_on_scan_progress
                    )
                except Exception:
                    results_map = {}

                for i, tid in enumerate(self.targets):
                    if self._stop_requested:
                        self.log.emit('  ⚠  Interrupted', 'warn')
                        break
                    label = tid.replace('_', ' ').upper()
                    result = results_map.get(tid)
                    if result is None:
                        result = CLEANER.clean(tid, dry=True)
                    if getattr(result, 'plan', None) is not None:
                        out_plans[tid] = result.plan
                        if hasattr(CLEANER, 'bind_approved_plan'):
                            CLEANER.bind_approved_plan(tid, result.plan)
                    total_freed += result.freed_bytes
                    rollback    += result.rollback
                    self.log.emit(f'\n  ▸ {_tlog(label)}', 'head')
                    if result.error:
                        self.log.emit(f'  ✗  {result.error}', 'err')
                    else:
                        self.log.emit(f'  ~  ~{fmt_size(result.freed_bytes)}', 'dry')
                        if result.files_removed:
                            self.log.emit(_tlog(f'     {result.files_removed} items'), 'dry')
                    _report_extras(result)
                    total_planned += result.freed_bytes
                    if result.freed_bytes > 0:
                        summary.append(f'{tid}:{fmt_size(result.freed_bytes)}')
            else:
                if not self.dry and IS_LINUX:
                    try:
                        from core.linux_cleaner import ensure_privileged_session
                        ensure_privileged_session(
                            log_cb=lambda m, l: self.log.emit(m, l)
                        )
                    except ImportError:
                        pass

                for i, tid in enumerate(self.targets):
                    if self._stop_requested:
                        self.log.emit('  ⚠  Interrupted — partial results below', 'warn')
                        break

                    slice_start = int((i / steps) * 95)
                    slice_mid   = int(((i + 0.5) / steps) * 95)
                    slice_end   = int(((i + 1) / steps) * 95)
                    label = tid.replace('_', ' ').upper()

                    self.log.emit(f'\n  ▸ {_tlog(label)}', 'head')
                    self.progress.emit(slice_start, f'{_t("review_scanning", "Scanning…")} {label}')

                    import concurrent.futures as _cf
                    _timeout_s = self._TARGET_TIMEOUT

                    def _run_target(tid=tid):
                        if self.dry and hasattr(CLEANER, '_cache_get'):
                            cached = CLEANER._cache_get(tid)
                            if cached is not None:
                                return cached, True
                            res = CLEANER.clean(tid, dry=True)
                            CLEANER._cache_set(tid, res)
                            return res, False
                        else:
                            prev_plan = self._plans.get(tid)
                            if prev_plan is None and not self.dry:
                                if hasattr(CLEANER, 'get_approved_plan'):
                                    bound, expired = CLEANER.get_approved_plan(tid)
                                    if expired:
                                        from core.base_cleaner import CleanResult as _CR
                                        r_exp = _CR(tid, dry=False)
                                        r_exp.error = "Previewed plan expired — please run DRY-RUN or PREVIEW FILES again before cleaning"
                                        return r_exp, False
                                    prev_plan = bound
                                elif hasattr(CLEANER, '_cache_get'):
                                    cached = CLEANER._cache_get(tid)
                                    prev_plan = getattr(cached, 'plan', None) if cached is not None else None
                            res = CLEANER.clean(tid, dry=self.dry, plan=prev_plan)
                            if not self.dry and hasattr(CLEANER, '_cache_invalidate'):
                                CLEANER._cache_invalidate(tid)
                            return res, False

                    try:
                        if self.dry:
                            # Read-only scan: use non-blocking shutdown(wait=False) so a timed-out
                            # read-only probe never stalls the worker thread via context-manager exit.
                            _ex = _cf.ThreadPoolExecutor(max_workers=1)
                            try:
                                _fut = _ex.submit(_run_target)
                                try:
                                    result, from_cache = _fut.result(timeout=_timeout_s)
                                    if from_cache:
                                        self.log.emit(_tlog('  ⚡  (cached)'), 'dry')
                                except _cf.TimeoutError:
                                    _fut.cancel()
                                    from core.base_cleaner import CleanResult as _CR
                                    result = _CR(tid)
                                    result.error = f'Timeout ({_timeout_s}s) — scan took too long'
                                    self.log.emit(f'  ⚠ {label}: scan timed out ({_timeout_s}s)', 'warn')
                            finally:
                                _ex.shutdown(wait=False, cancel_futures=True)
                        else:
                            # Destructive clean: run synchronously on this QThread so we NEVER
                            # report a target as "skipped" while a background thread continues deleting files.
                            result, _ = _run_target()
                    except Exception as _te:
                        from core.base_cleaner import CleanResult as _CR
                        result = _CR(tid)
                        result.error = str(_te)

                    if self.dry and getattr(result, 'plan', None) is not None:
                        out_plans[tid] = result.plan
                        if hasattr(CLEANER, 'bind_approved_plan'):
                            CLEANER.bind_approved_plan(tid, result.plan)

                    self.progress.emit(slice_mid, f'{label}...')
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

                    _report_extras(result)
                    total_freed += result.freed_bytes
                    total_planned += getattr(result, 'planned_bytes', 0) or result.freed_bytes
                    if getattr(result, 'measured_bytes', None) is not None:
                        measured_sum += max(result.measured_bytes, 0)
                        has_measured = True
                    rollback    += result.rollback
                    if result.freed_bytes > 0:
                        summary.append(f'{tid}:{fmt_size(result.freed_bytes)}')
                    if self._stop_requested:
                        self.log.emit('  ⚠  Interrupted — partial results below', 'warn')
                        break

        except Exception as _e:
            self.log.emit(f'  ✗  Internal worker error: {_e}', 'err')
        finally:
            if _PRIV is not None:
                try:
                    _PRIV.wait_active_helpers(timeout=10.0)
                    _PRIV.clear_cancel_helpers()
                except Exception:
                    pass
            if _E is not None:
                try:
                    _E.set_stop_requested(None)
                except Exception:
                    pass

        self.progress.emit(100, 'done')
        self.log.emit('\n' + '─' * 44, 'head')
        label = 'ESTIMATED' if self.dry else 'FREED'
        self.log.emit(_tlog(f'TOTAL {label}: {fmt_size(total_freed)}'), 'ok')
        self.done.emit({'freed': total_freed, 'dry': self.dry,
                        'interrupted': bool(self._stop_requested),
                        'summary': ' | '.join(summary), 'rollback': rollback,
                        'planned': total_planned,
                        'measured': measured_sum if has_measured else None,
                        'plans': out_plans})
        self._finished_event.set()


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

    def __init__(self, cleaner=None):
        super().__init__()
        self._stop_requested = False
        self._cleaner = cleaner

    def stop(self):
        self._stop_requested = True

    def run(self):
        import shutil as _sh, subprocess as _sp
        results = []
        if IS_LINUX:
            from core import privileged as P
            for action, label in [
                ('swappiness',     'Swappiness→10'),
                ('fstrim',         'SSD TRIM'),
                ('journal',        'Journal'),
                ('paccache',       'Paccache'),
                ('compact-memory', 'Compact RAM'),
            ]:
                if action == 'paccache' and not _sh.which('paccache'):
                    continue
                r = P.run_helper(action, timeout=120, use_pkexec=False)
                results.append((label, r.ok))
            try:
                from core.booster import free_ram
                free_ram(lambda m, l='text': None)
                results.append(('Smart RAM Free', True))
            except Exception:
                pass
        elif platform.system() == 'Windows':
            try:
                r = _sp.run(['ipconfig', '/flushdns'], capture_output=True, text=True, timeout=30,
                            creationflags=0x08000000)
                results.append(('Flush DNS', r.returncode == 0))
            except Exception:
                results.append(('Flush DNS', False))
            if self._cleaner is not None:
                try:
                    res = self._cleaner.clean('win_temp', dry=False)
                    results.append(('Clear TEMP', res.error is None))
                except Exception:
                    results.append(('Clear TEMP', False))
            try:
                from core.booster import free_ram
                free_ram(lambda m, l='text': None)
                results.append(('Smart RAM Free', True))
            except Exception:
                pass
            try:
                r_trim = _sp.run(
                    ['powershell', '-NoProfile', '-NonInteractive', '-Command',
                     'Optimize-Volume -DriveLetter C -ReTrim -ErrorAction SilentlyContinue'],
                    capture_output=True, text=True, timeout=60, creationflags=0x08000000,
                )
                results.append(('SSD TRIM', r_trim.returncode == 0))
            except Exception:
                results.append(('SSD TRIM', False))
        ok_count = sum(1 for _, ok in results if ok)
        summary  = (f'✓ {ok_count}/{len(results)}  ' +
                    '  ·  '.join(f'{"✓" if ok else "~"}{n}' for n, ok in results))
        self.done.emit(summary, ok_count > 0)


class _UninstallWorker(QThread):
    finished = pyqtSignal(list)
    progress = pyqtSignal(str)

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
# DiskDeltaWidget — Collision-Free Rounded Glass Tape-Bar Before/After Meter
# ═══════════════════════════════════════════════════════════════════════════
class DiskDeltaWidget(QWidget):
    _ANIM_MS   = 700
    _BAR_H     = 14
    _SCAN_W    = 3
    _COL_W     = 118
    _PAD_X     = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(86)
        self.setMaximumHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._total      = 0
        self._free_bef   = 0
        self._used_pct_b = 0.0
        self._free_aft   = 0
        self._used_pct_a = 0.0
        self._freed      = 0
        self._has_after  = False
        self._is_dry     = True

        self.__freed_ratio = 0.0
        self._anim = QPropertyAnimation(self, b'_freed_ratio', self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(self._ANIM_MS)

        self.__scan_pos = 0.0
        self._scan_ticks = 0
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._tick_scan)

    def _get_freed_ratio(self): return self.__freed_ratio
    def _set_freed_ratio(self, v):
        self.__freed_ratio = v
        self.update()
    _freed_ratio = pyqtProperty(float, _get_freed_ratio, _set_freed_ratio)

    def _tick_scan(self):
        self._scan_ticks += 1
        self.__scan_pos = (self.__scan_pos + 0.025) % 1.0
        if self._scan_ticks >= 60 or not self._has_after:
            self._scan_timer.stop()
            self.__scan_pos = 0.5
        self.update()

    def hideEvent(self, ev):
        self._scan_timer.stop()
        super().hideEvent(ev)

    def set_before(self, free_bytes: int, total_bytes: int, used_pct: float):
        self._free_bef   = free_bytes
        self._total      = max(total_bytes, 1)
        self._used_pct_b = used_pct
        self._has_after  = False
        self.__freed_ratio = 0.0
        self._scan_timer.stop()
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
        self._scan_ticks = 0
        if freed_bytes > 0 and self.isVisible():
            self._scan_timer.start(24)

    def reset(self):
        self._has_after  = False
        self.__freed_ratio = 0.0
        self._scan_timer.stop()
        self._anim.stop()
        self.update()

    @staticmethod
    def _fmt(b: int) -> str:
        if b <= 0:        return '—'
        if b >= 1 << 30:  return f'{b/(1<<30):.1f} GB'
        if b >= 1 << 20:  return f'{b/(1<<20):.0f} MB'
        return f'{b >> 10} KB'

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        col_used    = QColor(C['cyan_dim'])
        col_used_hi = QColor(C['cyan'])
        col_free    = QColor(C['bg3'])
        col_freed   = QColor(C['green'])
        col_freed_d = QColor(C['grn_dim'])
        col_cyan    = QColor(C['cyan'])
        col_text    = QColor(C['text'])
        col_text3   = QColor(C['text3'])
        col_green   = QColor(C['green'])
        col_border  = QColor(C['border2'])

        pw = self._PAD_X
        bar_x = pw + self._COL_W + 18
        bar_w = max(80, W - bar_x - pw - self._COL_W - 18)
        bh    = self._BAR_H
        # Position bar cleanly at vertical center (y=36) so top label at y=14..28 NEVER overlaps!
        bar_y = 34

        if self._used_pct_b > 0:
            used_ratio = self._used_pct_b / 100.0
        else:
            used_ratio = 1.0 - (self._free_bef / self._total) if self._total > 0 else 0.0
        used_ratio  = max(0.0, min(1.0, used_ratio))
        freed_ratio = max(0.0, min(1.0 - used_ratio, self.__freed_ratio))

        used_px   = int(bar_w * used_ratio)
        freed_px  = int(bar_w * freed_ratio)

        # Rounded pill bar clip path
        bar_rect = QRectF(bar_x, bar_y, bar_w, bh)
        clip = QPainterPath()
        clip.addRoundedRect(bar_rect, bh / 2.0, bh / 2.0)

        p.save()
        p.setClipPath(clip)
        p.fillRect(bar_rect, col_free)

        if used_px > 0:
            g = QLinearGradient(bar_x, bar_y, bar_x + used_px, bar_y)
            c_lt = QColor(C['cyan']); c_lt.setAlpha(95)
            g.setColorAt(0.0, col_used if is_dark_theme() else c_lt)
            g.setColorAt(1.0, col_used_hi)
            p.fillRect(QRectF(bar_x, bar_y, used_px, bh), QBrush(g))

        if freed_px > 0:
            fx = bar_x + used_px
            g2 = QLinearGradient(fx, bar_y, fx + freed_px, bar_y)
            g2.setColorAt(0.0, col_freed_d)
            g2.setColorAt(1.0, col_freed)
            p.fillRect(QRectF(fx, bar_y, freed_px, bh), QBrush(g2))

            sp = int(self.__scan_pos * (freed_px + self._SCAN_W * 4)) - self._SCAN_W * 2
            sx = fx + sp
            if fx <= sx <= fx + freed_px + self._SCAN_W:
                sg = QLinearGradient(sx, bar_y, sx + self._SCAN_W * 4, bar_y)
                sg.setColorAt(0.0, QColor(16, 185, 129, 0))
                sg.setColorAt(0.5, QColor(16, 185, 129, 190))
                sg.setColorAt(1.0, QColor(16, 185, 129, 0))
                p.fillRect(QRectF(sx, bar_y, self._SCAN_W * 4, bh), QBrush(sg))
        p.restore()

        # Subtle border around the pill bar
        p.setPen(QPen(col_border, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(bar_rect, bh / 2.0, bh / 2.0)

        # Tick marks below bar
        p.setPen(QPen(col_border, 1))
        for frac in (0.25, 0.50, 0.75):
            tx = bar_x + int(bar_w * frac)
            p.drawLine(tx, bar_y + bh + 2, tx, bar_y + bh + 6)

        # Top caption above bar (with generous 8px clearance above bar_y!)
        font_tiny = QFont()
        font_tiny.setPixelSize(10)
        font_tiny.setBold(True)
        p.setFont(font_tiny)

        if used_px > 20:
            p.setPen(col_text3)
            p.drawText(QRectF(bar_x + 2, bar_y - 20, 180, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f'{self._used_pct_b:.0f}% {_t("lbl_pct_used","used")}')

        if freed_px > 20 and self._has_after:
            p.setPen(col_freed)
            label = ('~' if self._is_dry else '') + self._fmt(self._freed) + ' freed'
            p.drawText(QRectF(bar_x + bar_w - 180, bar_y - 20, 180, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       label)

        lx = pw
        self._draw_stat_col(
            p, lx, 12, self._COL_W,
            _t('lbl_before', 'BEFORE'),
            self._fmt(self._free_bef),
            f'{self._used_pct_b:.1f}% {_t("lbl_pct_used","used")}',
            col_cyan, col_text, col_text3,
            align_right=False,
        )

        rx = W - pw - self._COL_W
        if self._has_after:
            self._draw_stat_col(
                p, rx, 12, self._COL_W,
                _t('lbl_after_est', 'AFTER (EST)') if self._is_dry else _t('lbl_after', 'AFTER'),
                self._fmt(self._free_aft),
                f'{self._used_pct_a:.1f}% {_t("lbl_pct_used","used")}',
                col_green, col_text, col_text3,
                align_right=True,
            )
        else:
            self._draw_stat_col(
                p, rx, 12, self._COL_W,
                _t('lbl_after', 'AFTER'),
                '—',
                '',
                col_text3, col_text3, col_text3,
                align_right=True,
            )

        if self._has_after and freed_px > 0:
            mid_x = bar_x + used_px + max(12, freed_px // 2)
            badge_y = bar_y + bh + 8
            freed_str = ('~' if self._is_dry else '+') + self._fmt(self._freed)

            font_badge = QFont()
            font_badge.setPixelSize(11)
            font_badge.setBold(True)
            p.setFont(font_badge)
            fm = p.fontMetrics()
            bw = fm.horizontalAdvance(freed_str) + 18
            bh2 = fm.height() + 6
            bx = max(bar_x, min(bar_x + bar_w - bw, mid_x - bw // 2))
            by = badge_y

            p.setBrush(QBrush(QColor(C['grn_dim'])))
            p.setPen(QPen(col_freed, 1))
            p.drawRoundedRect(QRectF(bx, by, bw, bh2), 5, 5)

            p.setPen(col_freed)
            p.drawText(
                QRectF(bx, by, bw, bh2),
                Qt.AlignmentFlag.AlignCenter,
                freed_str,
            )

        p.end()

    def _draw_stat_col(self, p, x, y, w,
                       tag, val, sub,
                       col_tag, col_val, col_sub,
                       align_right=False):
        flag = Qt.AlignmentFlag.AlignRight if align_right else Qt.AlignmentFlag.AlignLeft

        font_tag = QFont()
        font_tag.setPixelSize(9)
        font_tag.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.8)
        font_tag.setBold(True)
        p.setFont(font_tag)
        p.setPen(col_tag)
        p.drawText(QRectF(x, y, w, 14), flag | Qt.AlignmentFlag.AlignTop, tag)

        font_val = QFont('JetBrains Mono' if not IS_WINDOWS else 'Cascadia Code')
        font_val.setPixelSize(19)
        font_val.setBold(True)
        p.setFont(font_val)
        p.setPen(col_val)
        p.drawText(QRectF(x, y + 15, w, 26), flag | Qt.AlignmentFlag.AlignVCenter, val)

        font_sub = QFont()
        font_sub.setPixelSize(10)
        p.setFont(font_sub)
        p.setPen(col_sub)
        p.drawText(QRectF(x, y + 42, w, 15), flag | Qt.AlignmentFlag.AlignVCenter, sub)


class _AutoCleanWorker(QThread):
    done = pyqtSignal(int, int)

    def __init__(self, safe_targets, cleaner, scheduler=None):
        super().__init__()
        self._safe_targets = safe_targets
        self._cleaner      = cleaner
        self._scheduler    = scheduler
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        # Run 2s CPU/network idle check inside worker QThread so the Qt main GUI thread never blocks!
        if self._scheduler is not None:
            try:
                if not self._scheduler.should_run():
                    self.done.emit(-1, 0)
                    return
            except Exception:
                pass
        total_freed = 0; cleaned = 0
        try:
            from core import privileged as P
            P.set_unattended(True)
        except Exception:
            P = None
        try:
            for tid in self._safe_targets:
                if self._stop_requested:
                    break
                try:
                    result       = self._cleaner.clean(tid, dry=False, unattended=True)
                    if result.error is None:
                        total_freed += result.freed_bytes
                        cleaned     += 1
                except Exception:
                    pass
            if self._scheduler is not None and not self._stop_requested:
                try:
                    self._scheduler.mark_completed()
                except Exception:
                    pass
        finally:
            if P is not None:
                P.set_unattended(False)
        self.done.emit(total_freed, cleaned)
