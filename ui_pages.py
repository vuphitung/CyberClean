"""
CyberClean — DEEP CLEAN and DISK ADVISOR pages (tier 2 and tier 3)
════════════════════════════════════════════════════════════════
Hai trang RIÊNG trên sidebar, không còn nhét vào trang Dọn rác:

DeepCleanPage   (tier REVIEW)  Danh mục ở bên trái, chi tiết ở bên phải. Chọn một danh mục → liệt kê
                TỪNG MỤC; không mục nào được tick sẵn; "chọn hết" bỏ qua mục rủi ro cao; mục đang bị chặn
                (app đang chạy) không chọn được; mọi lần xóa đều hỏi lại và mặc định là Hủy.
AdvisorPage     (tier ADVISOR) Báo cáo CHỈ ĐỌC: dung lượng thật sự đi đâu (VM, game, /opt, gói nặng, file
                lớn, dự án cũ, Downloads…). Không có bất kỳ nút xóa nào.

Không import main.py (tránh vòng lặp). Mọi việc nặng chạy trong QThread.
"""
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime

from PyQt6.QtCore import QPointF, QRectF, QSize, QStandardPaths, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QDesktopServices, QFont, QFontMetrics, QPainter, QPainterPath, QPen,
                         QPixmap, QPolygonF)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedLayout,
    QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from ui_widgets import (
    C, MONO, UI, _btn, _t, is_dark_theme,
    EmptyStateBinder, ElevatedCard, apply_elevation_shadow, _global_check_icon_path,
)
from utils.sysinfo import fmt_size
from core.engine import fmt_age

RISK_COLOR = {'low': 'green', 'medium': 'yellow', 'high': 'red'}

# Màu theo danh mục của Advisor (đủ khác nhau để thanh tỷ lệ đọc được)
CAT_COLORS = {
    'vm': C['purple'], 'games': '#10B981', 'containers': C['cyan'], 'wsl': C['cyan2'],
    'windows': C['yellow'], 'projects': '#F59E0B', 'packages': '#3B82F6', 'opt': '#EC4899',
    'downloads': '#84CC16', 'large': '#F43F5E', 'info': C['dim'],
}


def cat_title(cat: str) -> str:
    from core import advisor
    return _t(f'adv_cat_{cat}', advisor.CATEGORY_TITLES.get(cat, cat))


def advice_text(f) -> str:
    """Lời khuyên đã dịch (nếu có bản dịch cho ngôn ngữ hiện tại); không có → bản tiếng Anh trong core."""
    if not f.advice_key:
        return f.advice
    tpl = _t(f'adv_{f.advice_key}', '')
    if not tpl:
        return f.advice
    try:
        return tpl.format(**f.advice_args)
    except (KeyError, IndexError, ValueError):
        return f.advice


def finding_title(f) -> str:
    if not f.title_key:
        return f.title
    tpl = _t(f'adv_{f.title_key}', '')
    if not tpl:
        return f.title
    try:
        return tpl.format(**f.title_args)
    except (KeyError, IndexError, ValueError):
        return f.title


def _risk_text(risk: str) -> str:
    return {'low': _t('risk_low', 'LOW'), 'medium': _t('risk_medium', 'MEDIUM'),
            'high': _t('risk_high', 'HIGH')}.get(risk, risk.upper())


def _rgba(hexcolor: str, alpha: float) -> str:
    """'#RRGGBB' + độ trong suốt → 'rgba(r,g,b,a)'."""
    h = hexcolor.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f'rgba({r},{g},{b},{alpha:.2f})'


def _plain(extra: str = '') -> str:
    """QSS cho nhãn nằm trong thẻ: QLabel kế thừa QFrame nên nếu không reset sẽ bị vẽ viền/nền của thẻ."""
    return f'border:none;background:transparent;{extra}'


_CHECK_ICON = None


def _check_icon() -> str:
    """PNG dấu tick theo theme hiện tại cho ô chọn trong bảng."""
    global _CHECK_ICON
    _CHECK_ICON = _global_check_icon_path()
    return _CHECK_ICON


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


class TwoLineDelegate(QStyledItemDelegate):
    """Ô MỤC: tên (đậm) + ghi chú / lý do bị chặn (mờ) trên dòng thứ hai — không còn cột GHI CHÚ bị cắt cụt."""
    ROLE_NOTE = Qt.ItemDataRole.UserRole + 1
    ROLE_TCOL = Qt.ItemDataRole.UserRole + 2
    ROLE_NCOL = Qt.ItemDataRole.UserRole + 3
    ROLE_WRAP = Qt.ItemDataRole.UserRole + 4          # True → ghi chú được xuống dòng (mục rủi ro cao / bị chặn)

    def paint(self, p, option, index):
        p.save()
        r = option.rect
        p.setPen(QColor(C['border']))
        p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
        title = index.data(Qt.ItemDataRole.DisplayRole) or ''
        note = index.data(self.ROLE_NOTE) or ''
        tcol = QColor(index.data(self.ROLE_TCOL) or C['text'])
        ncol = QColor(index.data(self.ROLE_NCOL) or C['text3'])
        f1 = QFont(option.font)
        f1.setPixelSize(13)
        f1.setBold(True)
        f2 = QFont(option.font)
        f2.setPixelSize(11)
        f2.setBold(False)
        fm1, fm2 = QFontMetrics(f1), QFontMetrics(f2)
        left, width = r.left() + 8, max(40, r.width() - 16)
        wrap = bool(note and index.data(self.ROLE_WRAP))
        total = fm1.height() + ((fm2.height() * 2 + 4) if wrap else (fm2.height() + 2 if note else 0))
        y = r.top() + max(4, (r.height() - total) // 2)
        p.setFont(f1)
        p.setPen(tcol)
        p.drawText(left, y + fm1.ascent(), fm1.elidedText(title, Qt.TextElideMode.ElideMiddle, width))
        if note and index.data(self.ROLE_WRAP):
            p.setClipRect(r)
            p.setFont(f2)
            p.setPen(ncol)
            box = QRectF(left, y + fm1.height() + 2, width, fm2.height() * 2 + 2)
            p.drawText(box, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap), note)
        elif note:
            p.setFont(f2)
            p.setPen(ncol)
            p.drawText(left, y + fm1.height() + 2 + fm2.ascent(), fm2.elidedText(note, Qt.TextElideMode.ElideRight, width))
        p.restore()

    def sizeHint(self, option, index):
        return QSize(220, 46)


class ElidedLabel(QLabel):
    """Nhãn một dòng tự cắt bớt giữa chuỗi (đường dẫn dài) và có tooltip đầy đủ."""

    def __init__(self, text='', mode=Qt.TextElideMode.ElideMiddle, parent=None):
        super().__init__(parent)
        self._full, self._mode = text, mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full = text or ''
        self.setToolTip(self._full)
        self._apply()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._apply()

    def _apply(self):
        fm = self.fontMetrics()
        QLabel.setText(self, fm.elidedText(self._full, self._mode, max(24, self.width() - 2)))


class Callout(QFrame):
    """Dải thông tin có viền màu — dùng cho lời nhắc an toàn / cảnh báo."""

    def __init__(self, text: str, color: str = 'cyan', glyph: str = '◈', parent=None):
        super().__init__(parent)
        self.setObjectName('callout')
        col = C[color]
        bg_fill = C.get(color + '_dim', _rgba(col, 0.08))
        if is_dark_theme():
            bg_fill = _rgba(col, 0.09)
        self.setStyleSheet(
            f'QFrame#callout{{background:{bg_fill};border:1px solid {_rgba(col, 0.35)};border-radius:{C["radius"]};}}')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(10)
        self._glyph = QLabel(glyph)
        self._glyph.setStyleSheet(_plain(f'color:{col};font-size:15px;font-weight:700;'))
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(_plain(f'color:{C["text2"]};font-size:12px;font-family:{UI};'))
        lay.addWidget(self._glyph, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.label, 1)

    def setText(self, text: str):
        self.label.setText(text)


# ══════════════════════════════════════════════════════════════
# Workers
# ══════════════════════════════════════════════════════════════

class _ScanWorker(QThread):
    done = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, cleaner, target_id):
        super().__init__()
        self._cl, self._tid = cleaner, target_id

    def run(self):
        try:
            self.done.emit(self._tid, self._cl.review_scan(self._tid))
        except Exception as e:                                   # noqa: BLE001
            self.failed.emit(self._tid, str(e))


class _ScanAllWorker(QThread):
    """Quét lần lượt mọi danh mục để hiện dung lượng trên từng thẻ (chỉ đọc)."""
    one = pyqtSignal(str, object, str)          # tid, ReviewScan | None, lỗi
    started_one = pyqtSignal(str)
    finished_all = pyqtSignal()

    def __init__(self, cleaner, tids):
        super().__init__()
        self._cl, self._tids = cleaner, list(tids)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        for tid in self._tids:
            if self._stop.is_set():
                break
            self.started_one.emit(tid)
            try:
                self.one.emit(tid, self._cl.review_scan(tid), '')
            except Exception as e:                               # noqa: BLE001
                self.one.emit(tid, None, str(e))
        self.finished_all.emit()


class _CleanWorker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, cleaner, target_id, ids):
        super().__init__()
        self._cl, self._tid, self._ids = cleaner, target_id, list(ids)

    def run(self):
        try:
            if sys.platform.startswith('linux'):
                from core import privileged as P
                P.ensure_session()
            self.done.emit(self._cl.review_clean(self._tid, self._ids, dry=False))
        except Exception as e:                                   # noqa: BLE001
            self.failed.emit(str(e))


class _AdvisorWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(object)

    def __init__(self, home, pm, seconds=75.0):
        super().__init__()
        self._home, self._pm, self._seconds = home, pm, seconds
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        from core import advisor
        try:
            rep = advisor.scan(self._home, self._pm, seconds=self._seconds, stop=self._stop.is_set,
                               progress=lambda m: self.progress.emit(m))
        except Exception as e:                                   # noqa: BLE001
            rep = advisor.Report(notes=[f'Advisor failed: {e}'])
        self.done.emit(rep)


# ══════════════════════════════════════════════════════════════
# DEEP CLEAN — danh mục bên trái
# ══════════════════════════════════════════════════════════════

class TargetCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.tid = target.id
        self.target = target
        self.setObjectName('tcard')
        self.setProperty('selected', False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        accent = C['red'] if target.safety == 'danger' else C['yellow']
        sel_bg = _rgba(C['cyan'], 0.10) if is_dark_theme() else C['cyan_dim']
        self.setStyleSheet(
            f'QFrame#tcard{{background:{C["bg2"]};border:1px solid {C["border2"]};'
            f'border-left:3.5px solid {_rgba(accent, 0.78)};border-radius:{C["radius"]};}}'
            f'QFrame#tcard:hover{{background:{C["bg3"]};border-color:{C["border3"]};'
            f'border-left:3.5px solid {accent};}}'
            f'QFrame#tcard[selected="true"]{{background:{sel_bg};border:1px solid {_rgba(C["cyan"], 0.65)};'
            f'border-left:3.5px solid {C["cyan"]};}}')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 10, 13, 10)
        lay.setSpacing(10)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        self._name = QLabel(_t(f'tgt_{target.id}_name', target.name) + (' [ROOT]' if target.needs_root else ''))
        self._name.setWordWrap(True)
        self._name.setStyleSheet(_plain(f'color:{C["text"]};font-size:13px;font-weight:700;font-family:{UI};'))
        self._desc = QLabel(_t(f'tgt_{target.id}_desc', target.desc))
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet(_plain(f'color:{C["text3"]};font-size:11px;font-family:{UI};'))
        txt.addWidget(self._name)
        txt.addWidget(self._desc)
        lay.addLayout(txt, 1)
        side = QVBoxLayout()
        side.setSpacing(1)
        self._size = QLabel('—')
        self._size.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._state = QLabel('')
        self._state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        side.addStretch()
        side.addWidget(self._size)
        side.addWidget(self._state)
        side.addStretch()
        lay.addLayout(side)
        self.set_state('idle')

    def retranslate(self):
        t = self.target
        self._name.setText(_t(f'tgt_{t.id}_name', t.name) + (' [ROOT]' if t.needs_root else ''))
        self._desc.setText(_t(f'tgt_{t.id}_desc', t.desc))
        self.set_state(self._kind, self._total, self._count)

    def set_selected(self, on: bool):
        self.setProperty('selected', bool(on))
        _repolish(self)

    def set_state(self, kind: str, total: int = 0, count: int = 0):
        self._kind, self._total, self._count = kind, total, count
        size_css = f'font-size:14px;font-weight:700;font-family:{MONO};'
        if kind == 'scanning':
            txt, col, st = '…', C['cyan'], _t('state_scanning', 'SCANNING')
        elif kind == 'ready' and count:
            txt, col, st = fmt_size(total) if total else '—', C['yellow'], f'{count} ' + _t('state_items', 'ITEMS')
        elif kind == 'ready':
            txt, col, st = '✓', C['green'], _t('state_clean', 'NOTHING TO REVIEW')
        elif kind == 'error':
            txt, col, st = '!', C['red'], _t('state_error', 'ERROR')
        else:
            txt, col, st = '—', C['dim'], _t('state_idle', 'NOT SCANNED')
        self._size.setText(txt)
        self._size.setStyleSheet(_plain(f'color:{col};' + size_css))
        self._state.setText(st)
        self._state.setStyleSheet(_plain(f'color:{C["dim"]};font-size:9px;letter-spacing:0.8px;font-weight:700;'
                                         f'font-family:{UI};'))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.tid)
        super().mousePressEvent(ev)


# ══════════════════════════════════════════════════════════════
# DEEP CLEAN — panel chi tiết bên phải
# ══════════════════════════════════════════════════════════════

class ReviewPanel(ElevatedCard):
    scanned = pyqtSignal(str, object, str)       # tid, ReviewScan | None, lỗi
    cleaned = pyqtSignal(object, object)         # target, CleanResult
    busyChanged = pyqtSignal(bool)

    def __init__(self, cleaner, parent=None):
        super().__init__(shadow=True, parent=parent)
        self._cl = cleaner
        self._t = None
        self._scan = None
        self._worker = None
        self._busy = False
        self._deleting = False
        self._updating = False
        self.setObjectName('panel')
        outer = QStackedLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── trang 0: chưa chọn danh mục ──
        empty = QWidget()
        empty.setStyleSheet('background:transparent;')
        el = QVBoxLayout(empty)
        el.addStretch()
        self._empty_icon = QLabel('◈')
        self._empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_icon.setStyleSheet(_plain(f'color:{C["cyan"]};font-size:38px;'))
        self._empty_title = QLabel(_t('deep_pick', 'Pick a category on the left'))
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_title.setStyleSheet(_plain(f'color:{C["text"]};font-size:16px;font-weight:700;font-family:{UI};'))
        self._empty_hint = QLabel(_t('deep_pick_hint', 'CyberClean lists every item inside it — you tick exactly what should go.'))
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet(_plain(f'color:{C["text3"]};font-size:12px;font-family:{UI};'))
        for w in (self._empty_icon, self._empty_title, self._empty_hint):
            el.addWidget(w)
        el.addStretch()
        outer.addWidget(empty)

        # ── trang 1: nội dung ──
        body = QWidget()
        body.setStyleSheet('background:transparent;')
        vl = QVBoxLayout(body)
        vl.setContentsMargins(18, 16, 18, 14)
        vl.setSpacing(8)

        self._title = QLabel('')
        self._title.setStyleSheet(_plain(f'color:{C["text"]};font-size:17px;font-weight:700;font-family:{UI};'))
        self._desc = QLabel('')
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet(_plain(f'color:{C["text3"]};font-size:12px;font-family:{UI};'))
        vl.addWidget(self._title)
        vl.addWidget(self._desc)

        self._warn = Callout('', 'yellow', '⚠')
        self._warn.setVisible(False)
        vl.addWidget(self._warn)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(3)
        self._bar.setStyleSheet(f'QProgressBar{{background:{C["bg3"]};border:none;border-radius:1px;}}'
                                f'QProgressBar::chunk{{background:{C["cyan"]};border-radius:1px;}}')
        vl.addWidget(self._bar)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self._sel_safe_btn = _btn(_t('btn_select_safe', 'SELECT ALL (not high-risk)'), 'cyan', small=True)
        self._sel_none_btn = _btn(_t('btn_none', 'NONE'), small=True)
        self._sel_safe_btn.clicked.connect(self._select_safe)
        self._sel_none_btn.clicked.connect(self._select_none)
        self._summary = QLabel('')
        self._summary.setStyleSheet(_plain(f'color:{C["green"]};font-size:12px;font-family:{MONO};font-weight:700;'))
        tools.addWidget(self._sel_safe_btn)
        tools.addWidget(self._sel_none_btn)
        tools.addStretch()
        tools.addWidget(self._summary)
        vl.addLayout(tools)

        well_bg = C.get('well_bg', C['bg'])
        self._table = QTableWidget(0, 5)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(46)
        self._table.setItemDelegateForColumn(1, TwoLineDelegate(self._table))
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setStyleSheet(
            f'QTableWidget{{background:{well_bg};color:{C["text"]};border:1px solid {C["border2"]};'
            f'border-radius:{C["radius"]};font-family:{UI};font-size:12px;}}'
            f'QTableWidget::item{{padding:4px 8px;border-bottom:1px solid {C["border"]};}}'
            f'QHeaderView::section{{background:{C["bg3"]};color:{C["text3"]};border:none;'
            f'border-bottom:1px solid {C["border2"]};padding:8px 10px;font-family:{MONO};'
            f'font-size:10px;letter-spacing:1px;font-weight:700;}}'
            f'QTableCornerButton::section{{background:{C["bg3"]};border:none;}}'
            f'QTableWidget::indicator{{width:16px;height:16px;border:2px solid {_rgba(C["cyan"], 0.60)};'
            f'border-radius:4px;background:transparent;}}'
            f'QTableWidget::indicator:hover{{border-color:{C["cyan"]};}}'
            f'QTableWidget::indicator:checked{{background:{C["cyan"]};border-color:{C["cyan"]};'
            f'image:url("{_check_icon()}");}}')
        hh = self._table.horizontalHeader()
        for col, mode in enumerate((QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                    QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.ResizeToContents,
                                    QHeaderView.ResizeMode.ResizeToContents)):
            hh.setSectionResizeMode(col, mode)
        self._table.itemChanged.connect(self._on_item_changed)
        # Centered Empty State Overlay so 0-item categories (like empty Trash) never show a giant empty black box!
        self._table_empty = EmptyStateBinder(
            self._table,
            _t('state_clean', 'Danh mục này đã sạch'),
            _t('review_nothing', 'Không có mục nào cần xem lại ở đây.'),
            icon_char='✓',
        )
        vl.addWidget(self._table, 1)
        self._retitle_columns()

        self._result = QTextEdit()
        self._result.setReadOnly(True)
        self._result.setMaximumHeight(92)
        self._result.setVisible(False)
        self._result.setStyleSheet(
            f'QTextEdit{{background:{well_bg};color:{C["text2"]};border:1px solid {C["border2"]};'
            f'border-radius:{C["radius"]};font-family:{MONO};font-size:11px;padding:6px;}}')
        vl.addWidget(self._result)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self._status = QLabel('')
        self._status.setWordWrap(True)
        self._status.setStyleSheet(_plain(f'color:{C["text3"]};font-size:11px;font-family:{MONO};'))
        self._rescan_btn = _btn(_t('btn_rescan', 'RESCAN'), small=True)
        self._rescan_btn.clicked.connect(self.rescan)
        self._del_btn = _btn(f"✕  {_t('btn_delete_selected', 'DELETE SELECTED')}", 'red')
        self._del_btn.clicked.connect(self._delete)
        foot.addWidget(self._status, 1)
        foot.addWidget(self._rescan_btn)
        foot.addWidget(self._del_btn)
        vl.addLayout(foot)
        outer.addWidget(body)
        self._stack = outer
        outer.setCurrentIndex(0)

    # ── public ──────────────────────────────────────────────
    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def deleting(self) -> bool:
        return self._deleting

    @property
    def target(self):
        return self._t

    def retranslate(self):
        self._empty_title.setText(_t('deep_pick', 'Pick a category on the left'))
        self._empty_hint.setText(_t('deep_pick_hint', 'CyberClean lists every item inside it — you tick exactly what should go.'))
        self._sel_safe_btn.setText(_t('btn_select_safe', 'SELECT ALL (not high-risk)'))
        self._sel_none_btn.setText(_t('btn_none', 'NONE'))
        self._rescan_btn.setText(_t('btn_rescan', 'RESCAN'))
        self._del_btn.setText(f"✕  {_t('btn_delete_selected', 'DELETE SELECTED')}")
        self._retitle_columns()
        if hasattr(self, '_table_empty'):
            self._table_empty.set_copy(
                _t('state_clean', 'Danh mục này đã sạch'),
                _t('review_nothing', 'Không có mục nào cần xem lại ở đây.'),
            )
        if self._t is not None:
            self._title.setText(_t(f'tgt_{self._t.id}_name', self._t.name) + (' [ROOT]' if self._t.needs_root else ''))
            self._desc.setText(_t(f'tgt_{self._t.id}_desc', self._t.desc))
            if self._scan is not None and not self._busy:
                if self._scan.target_id in ('empty_trash', 'win_recycle') and self._scan.warning:
                    self._warn.setText(_t('warn_trash', self._scan.warning))
                checked_ids = {i.id for i in self._checked()}
                notes = '  ·  '.join(self._scan.notes)
                self._status.setText(notes if notes else ('' if self._scan.items else _t('review_nothing', 'Nothing to review here.')))
                self._fill(self._scan)
                if checked_ids:
                    self._set_all(lambda it: it.id in checked_ids)
            self._update_summary()

    def _retitle_columns(self):
        self._table.setHorizontalHeaderLabels([
            '', _t('col_item', 'ITEM'), _t('col_size', 'SIZE'), _t('col_last_used', 'LAST USED'),
            _t('col_risk', 'RISK')])

    def set_target(self, target, scan=None):
        """Chuyển sang một danh mục. `scan` (nếu có) là kết quả quét còn mới → hiện ngay, khỏi quét lại."""
        self._t = target
        self._scan = None
        self._result.setVisible(False)
        self._warn.setVisible(False)
        self._table.setRowCount(0)
        self._title.setText(_t(f'tgt_{target.id}_name', target.name) + (' [ROOT]' if target.needs_root else ''))
        self._desc.setText(_t(f'tgt_{target.id}_desc', target.desc))
        self._stack.setCurrentIndex(1)
        if scan is not None:
            self._show_scan(scan)
        else:
            self.rescan()

    def rescan(self):
        if self._t is None or self._deleting:
            return
        self._set_busy(True, _t('review_scanning', 'Scanning…'))
        self._worker = _ScanWorker(self._cl, self._t.id)
        self._worker.done.connect(self._on_scan)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def shutdown(self):
        w = self._worker
        if w is not None and w.isRunning():
            w.wait(20000 if self._deleting else 5000)

    # ── internals ───────────────────────────────────────────
    def _set_busy(self, busy: bool, msg: str = ''):
        was = self._busy
        self._busy = busy
        self._bar.setVisible(busy)
        for b in (self._sel_safe_btn, self._sel_none_btn, self._rescan_btn, self._del_btn):
            b.setEnabled(not busy)
        self._status.setStyleSheet(_plain(f'color:{C["cyan"] if busy else C["text3"]};font-size:11px;font-family:{MONO};'))
        if msg or busy:
            self._status.setText(msg)
        if busy != was:
            self.busyChanged.emit(busy)
        if not busy:
            self._update_summary()

    def _on_failed(self, tid: str, msg: str):
        if self._t is None or tid != self._t.id:
            return
        self._deleting = False
        self._set_busy(False, f'✗ {msg}')
        self._status.setStyleSheet(_plain(f'color:{C["red"]};font-size:11px;font-family:{MONO};'))
        self.scanned.emit(tid, None, msg)

    def _on_scan(self, tid: str, scan):
        if self._t is None or tid != self._t.id:
            return
        self._show_scan(scan)

    def _show_scan(self, scan):
        self._scan = scan
        self._deleting = False
        self._set_busy(False)
        if scan.warning:
            warn_txt = _t('warn_trash', scan.warning) if scan.target_id in ('empty_trash', 'win_recycle') else scan.warning
            self._warn.setText(warn_txt)
            self._warn.setVisible(True)
        else:
            self._warn.setVisible(False)
        notes = '  ·  '.join(scan.notes)
        self._status.setText(notes if notes else ('' if scan.items else _t('review_nothing', 'Nothing to review here.')))
        self._fill(scan)
        self.scanned.emit(scan.target_id, scan, '')

    def _fill(self, scan):
        self._updating = True
        try:
            self._table.setRowCount(0)
            now = datetime.now().timestamp()
            for it in scan.items:
                r = self._table.rowCount()
                self._table.insertRow(r)
                chk = QTableWidgetItem()
                if it.blocked:
                    chk.setFlags(Qt.ItemFlag.NoItemFlags)
                else:
                    chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                    chk.setCheckState(Qt.CheckState.Unchecked)
                chk.setData(Qt.ItemDataRole.UserRole, it.id)
                self._table.setItem(r, 0, chk)
                shown = it.blocked or (_t('rn_' + it.payload['rule'], it.detail) if it.payload.get('rule') else it.detail)
                prefix = '🔒 ' if it.blocked else ('🗑 ' if scan.target_id == 'empty_trash' else '')
                name = QTableWidgetItem(prefix + it.label)
                name.setToolTip((it.payload.get('path') or it.label) + (f'\n{shown}' if shown else ''))
                name.setData(TwoLineDelegate.ROLE_NOTE, shown)
                name.setData(TwoLineDelegate.ROLE_TCOL, C['dim'] if it.blocked else C['text'])
                name.setData(TwoLineDelegate.ROLE_NCOL, C['yellow'] if it.blocked else
                             (C['red'] if it.risk == 'high' else C['text3']))
                wrap = bool(it.blocked or it.risk == 'high')
                name.setData(TwoLineDelegate.ROLE_WRAP, wrap)
                self._table.setRowHeight(r, 64 if wrap else 46)
                size_txt = fmt_size(it.size) if (it.size or scan.target_id == 'empty_trash') else '—'
                size = QTableWidgetItem(size_txt)
                size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                age = QTableWidgetItem(fmt_age(it.newest, now) if it.newest else '—')
                risk = QTableWidgetItem(_risk_text(it.risk))
                risk.setForeground(QColor(C[RISK_COLOR.get(it.risk, 'yellow')]))
                f = QFont()
                f.setBold(True)
                risk.setFont(f)
                if it.blocked:
                    for cell in (size, age):
                        cell.setForeground(QColor(C['dim']))
                for col, cell in enumerate((name, size, age, risk), start=1):
                    self._table.setItem(r, col, cell)
        finally:
            self._updating = False
        if hasattr(self, '_table_empty'):
            self._table_empty.sync()
        self._update_summary()

    # ── lựa chọn ────────────────────────────────────────────
    def _rows(self):
        items = {i.id: i for i in (self._scan.items if self._scan else [])}
        for r in range(self._table.rowCount()):
            c = self._table.item(r, 0)
            if c is not None:
                yield r, c, items.get(c.data(Qt.ItemDataRole.UserRole))

    def _checked(self):
        return [it for _, c, it in self._rows()
                if it is not None and c.checkState() == Qt.CheckState.Checked]

    def _on_item_changed(self, _item):
        if not self._updating:
            self._update_summary()

    def _update_summary(self):
        sel = self._checked()
        total = sum(i.size for i in sel)
        n_all = len(self._scan.items) if self._scan else 0
        self._summary.setText(_t('review_selected', '{n} of {m} selected  ·  {size}').format(
            n=len(sel), m=n_all, size=fmt_size(total)))
        self._del_btn.setEnabled(bool(sel) and not self._busy)

    def _set_all(self, pred):
        self._updating = True
        try:
            for _, c, it in self._rows():
                if it is None or it.blocked:
                    continue
                c.setCheckState(Qt.CheckState.Checked if pred(it) else Qt.CheckState.Unchecked)
        finally:
            self._updating = False
        self._update_summary()

    def _select_safe(self):
        self._set_all(lambda it: it.risk != 'high')

    def _select_none(self):
        self._set_all(lambda it: False)

    # ── xóa ─────────────────────────────────────────────────
    def _confirm(self, sel) -> bool:
        total = fmt_size(sum(i.size for i in sel))
        perm = self._scan.permanent if self._scan else True
        lines = [_t('review_confirm_perm', 'Permanently delete {n} item(s) ({size})?').format(n=len(sel), size=total)]
        if perm:
            lines.append(_t('review_cannot_undo', 'This cannot be undone — nothing goes to the Trash.'))
        high = [i for i in sel if i.risk == 'high']
        if high:
            lines += ['', _t('review_high_risk', 'HIGH-RISK items you selected:')]
            lines += [f'  ⚠ {i.label}' for i in high[:8]]
        lines += ['', *[f'  • {i.label}' for i in sel[:12]]] + ([f'  … +{len(sel) - 12}'] if len(sel) > 12 else [])
        box = QMessageBox(self)
        box.setWindowTitle(_t('confirm_clean', 'Confirm'))
        box.setText('\n'.join(lines))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Yes).setText(f"✕ {_t('btn_delete_selected', 'DELETE SELECTED')}")
        box.setStyleSheet(f'background:{C["bg2"]};color:{C["text"]};font-family:{MONO};')
        return box.exec() == QMessageBox.StandardButton.Yes

    def _delete(self):
        sel = self._checked()
        if not sel or self._busy or self._t is None:
            return
        if not self._confirm(sel):
            return
        self._deleting = True
        self._set_busy(True, _t('review_deleting', 'Deleting…'))
        self._worker = _CleanWorker(self._cl, self._t.id, [i.id for i in sel])
        tgt = self._t
        self._worker.done.connect(lambda res, t=tgt: self._on_cleaned(t, res))
        self._worker.failed.connect(lambda msg, t=tgt: self._on_failed(t.id, msg))
        self._worker.start()

    def _on_cleaned(self, target, res):
        lines = [f'✓ {fmt_size(res.freed_bytes)} freed · {res.files_removed} item(s)']
        if res.measured_bytes is not None:
            lines.append(f'  disk free space changed by {fmt_size(max(res.measured_bytes, 0))} (measured)')
        lines += [f'  ⚠ {n}' for n in res.notes]
        lines += [f'  – skipped {p}: {why}' for p, why in res.skipped[:8]]
        if res.error:
            lines.append(f'  ✗ {res.error}')
        self._result.setPlainText('\n'.join(lines))
        self._result.setVisible(True)
        self._deleting = False
        self.cleaned.emit(target, res)
        if self._t is not None and self._t.id == target.id:
            self.rescan()
        else:
            self._set_busy(False)


# ══════════════════════════════════════════════════════════════
# DEEP CLEAN — trang
# ══════════════════════════════════════════════════════════════

class DeepCleanPage(QWidget):
    cleaned = pyqtSignal(object, object)           # target, CleanResult

    def __init__(self, cleaner, parent=None):
        super().__init__(parent)
        self._cl = cleaner
        self._targets = [t for t in cleaner.get_targets() if t.tier == 'review']
        self._cards = {}
        self._scans = {}
        self._current = None
        self._all_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(10)

        self._title = QLabel(_t('deep_title', 'DEEP CLEAN'))
        self._title.setStyleSheet(f'color:{C["text"]};font-size:18px;font-weight:700;letter-spacing:1.2px;font-family:{UI};')
        self._sub = QLabel(_t('deep_sub', 'Things that might matter — you choose every item.'))
        self._sub.setStyleSheet(f'color:{C["text3"]};font-size:13px;font-family:{UI};')
        root.addWidget(self._title)
        root.addWidget(self._sub)
        self._callout = Callout(_t(
            'deep_callout',
            'Nothing here is ticked for you and nothing runs in the background. High-risk rows must be ticked '
            'by hand, deletions are permanent, and every delete asks first (default answer: Cancel).'), 'cyan')
        root.addWidget(self._callout)

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        # ── trái: danh mục ──
        left = QVBoxLayout()
        left.setSpacing(8)
        head = QHBoxLayout()
        self._cat_lbl = QLabel(_t('deep_categories', 'CATEGORIES'))
        self._cat_lbl.setStyleSheet(f'color:{C["text3"]};font-size:11px;letter-spacing:1.6px;font-weight:700;font-family:{UI};')
        self._scan_all_btn = _btn(_t('btn_scan_all', 'SCAN ALL'), 'cyan', small=True)
        self._scan_all_btn.clicked.connect(self._toggle_scan_all)
        head.addWidget(self._cat_lbl)
        head.addStretch()
        head.addWidget(self._scan_all_btn)
        left.addLayout(head)
        self._total = QLabel('')
        self._total.setWordWrap(True)
        self._total.setStyleSheet(f'color:{C["yellow"]};font-size:12px;font-family:{MONO};font-weight:700;')
        left.addWidget(self._total)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea{background:transparent;border:none;}')
        inner = QWidget()
        inner.setStyleSheet('background:transparent;')
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)
        il.setSpacing(6)
        for t in self._targets:
            card = TargetCard(t)
            card.clicked.connect(self._select)
            self._cards[t.id] = card
            il.addWidget(card)
        il.addStretch()
        scroll.setWidget(inner)
        left.addWidget(scroll, 1)
        self._left_col = QWidget()
        self._left_col.setLayout(left)
        self._left_col.setMinimumWidth(240)
        self._left_col.setMaximumWidth(340)
        self._left_col.setFixedWidth(320)
        body.addWidget(self._left_col)

        # ── phải: chi tiết ──
        self._panel = ReviewPanel(cleaner)
        self._panel.scanned.connect(self._on_panel_scanned)
        self._panel.cleaned.connect(self.cleaned.emit)
        body.addWidget(self._panel, 1)

        if not self._targets:
            self._total.setText(_t('deep_none', 'No review categories are available on this system.'))
            self._scan_all_btn.setEnabled(False)

    # ── chọn / quét ─────────────────────────────────────────
    @property
    def panel(self) -> ReviewPanel:
        return self._panel

    def card(self, tid: str) -> TargetCard:
        return self._cards[tid]

    def _select(self, tid: str):
        if self._panel.deleting or tid == self._current and self._panel.busy:
            return
        target = next((t for t in self._targets if t.id == tid), None)
        if target is None:
            return
        self._current = tid
        for k, c in self._cards.items():
            c.set_selected(k == tid)
        cached = self._scans.get(tid)
        fresh = cached is not None and (time.monotonic() - cached[0]) < 120
        self._cards[tid].set_state('scanning')
        self._panel.set_target(target, cached[1] if fresh else None)

    def _on_panel_scanned(self, tid: str, scan, err: str):
        card = self._cards.get(tid)
        if scan is None:
            if card:
                card.set_state('error')
            return
        self._record(tid, scan)

    def _record(self, tid: str, scan):
        self._scans[tid] = (time.monotonic(), scan)
        usable = [i for i in scan.items if not i.blocked]
        card = self._cards.get(tid)
        if card:
            card.set_state('ready', sum(i.size for i in usable), len(scan.items))
        self._refresh_total()

    def _refresh_total(self):
        if not self._scans:
            self._total.setText('')
            return
        total = sum(sum(i.size for i in s.items if not i.blocked) for _, s in self._scans.values())
        n = sum(1 for _, s in self._scans.values() if s.items)
        self._total.setText(_t('deep_total', '{size} to review across {n} categories').format(size=fmt_size(total), n=n))

    def _toggle_scan_all(self):
        w = self._all_worker
        if w is not None and w.isRunning():
            w.stop()
            return
        if self._panel.deleting:
            return
        for tid, card in self._cards.items():
            card.set_state('idle')
        self._scans.clear()
        self._refresh_total()
        self._scan_all_btn.setText(_t('btn_stop', 'STOP'))
        w = _ScanAllWorker(self._cl, [t.id for t in self._targets])
        w.started_one.connect(lambda tid: self._cards[tid].set_state('scanning'))
        w.one.connect(self._on_one_scanned)
        w.finished_all.connect(self._on_scan_all_done)
        self._all_worker = w
        w.start()

    def _on_one_scanned(self, tid: str, scan, err: str):
        if scan is None:
            self._cards[tid].set_state('error')
            return
        self._record(tid, scan)

    def _on_scan_all_done(self):
        self._scan_all_btn.setText(_t('btn_scan_all', 'SCAN ALL'))
        for tid, card in self._cards.items():
            if tid not in self._scans and card._kind == 'scanning':
                card.set_state('idle')
        if self._current and self._current in self._scans and not self._panel.busy:
            self._panel.set_target(self._cards[self._current].target, self._scans[self._current][1])

    def retranslate(self):
        self._title.setText(_t('deep_title', 'DEEP CLEAN'))
        self._sub.setText(_t('deep_sub', 'Things that might matter — you choose every item.'))
        self._callout.setText(_t(
            'deep_callout',
            'Nothing here is ticked for you and nothing runs in the background. High-risk rows must be ticked '
            'by hand, deletions are permanent, and every delete asks first (default answer: Cancel).'))
        self._cat_lbl.setText(_t('deep_categories', 'CATEGORIES'))
        running = self._all_worker is not None and self._all_worker.isRunning()
        self._scan_all_btn.setText(_t('btn_stop', 'STOP') if running else _t('btn_scan_all', 'SCAN ALL'))
        for c in self._cards.values():
            c.retranslate()
        self._panel.retranslate()
        self._refresh_total()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, '_left_col'):
            w = self.width()
            self._left_col.setFixedWidth(250 if w < 860 else (290 if w < 1020 else 330))

    def shutdown(self):
        if self._all_worker is not None and self._all_worker.isRunning():
            self._all_worker.stop()
            self._all_worker.wait(8000)
        self._panel.shutdown()


# ══════════════════════════════════════════════════════════════
# DISK ADVISOR
# ══════════════════════════════════════════════════════════════

class ShareBar(QWidget):
    """Thanh ngang chia theo tỷ lệ dung lượng của từng danh mục."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._segs = []
        self.setFixedHeight(16)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, segs):
        self._segs = [(QColor(c), s) for c, s in segs if s > 0]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 6, 6)
        p.setClipPath(clip)
        p.fillRect(0, 0, w, h, QColor(C['bg3']))
        total = sum(s for _, s in self._segs)
        if total <= 0:
            return
        gap, x = 2, 0.0
        avail = w - gap * (len(self._segs) - 1)
        for col, size in self._segs:
            seg = max(3.0, avail * size / total)
            p.fillRect(QRectF(x, 0, seg, h), QBrush(col))
            x += seg + gap


class _Tile(ElevatedCard):
    def __init__(self, label: str, color: str = 'cyan', parent=None):
        super().__init__(top_accent=C[color], shadow=True, parent=parent)
        self.setObjectName('tile')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        self._lbl = QLabel(label)
        self._lbl.setStyleSheet(_plain(f'color:{C["dim"]};font-size:10px;letter-spacing:1.6px;font-weight:700;font-family:{UI};'))
        self._val = QLabel('—')
        self._val.setStyleSheet(_plain(f'color:{C[color]};font-size:22px;font-weight:700;font-family:{MONO};'))
        self._sub = QLabel('')
        self._sub.setStyleSheet(_plain(f'color:{C["text3"]};font-size:11px;font-family:{UI};'))
        for w in (self._lbl, self._val, self._sub):
            lay.addWidget(w)

    def set(self, value: str, sub: str = ''):
        self._val.setText(value)
        self._sub.setText(sub)

    def set_label(self, text: str):
        self._lbl.setText(text)


class _FindingRow(QFrame):
    def __init__(self, f, max_size: int, color: str, home: str, parent=None):
        super().__init__(parent)
        self.finding = f
        self.setObjectName('frow')
        self.setStyleSheet(f'QFrame#frow{{background:transparent;border:none;border-top:1px solid {C["border"]};}}')
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 9, 14, 9)
        v.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(10)
        name = QLabel(finding_title(f))
        name.setStyleSheet(_plain(f'color:{C["text"]};font-size:13px;font-weight:600;font-family:{UI};'))
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(name, 1)
        if f.size:
            size = QLabel(fmt_size(f.size))
            size.setStyleSheet(_plain(f'color:{color};font-size:13px;font-weight:700;font-family:{MONO};'))
            top.addWidget(size)
        if f.age_days is not None:
            age = QLabel(f'{f.age_days} d')
            age.setStyleSheet(
                f'color:{C["text3"]};font-size:10px;font-family:{MONO};padding:1px 7px;'
                f'border:1px solid {C["border3"]};border-radius:8px;background:transparent;')
            age.setToolTip(_t('adv_age_tip', 'Days since this was last modified'))
            top.addWidget(age)
        self.open_btn = QPushButton('⊡')
        self.open_btn.setFixedSize(26, 24)
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.setToolTip(_t('btn_open_folder', 'OPEN FOLDER'))
        self.open_btn.setStyleSheet(
            f'QPushButton{{color:{C["cyan"]};border:1px solid {_rgba(C["cyan"], 0.35)};border-radius:6px;background:transparent;}}'
            f'QPushButton:hover{{background:{_rgba(C["cyan"], 0.14)};}}'
            f'QPushButton:disabled{{color:{C["dim"]};border-color:{C["border2"]};}}')
        self._folder = f.open_path or (os.path.dirname(f.path) if f.path else '')
        self.open_btn.setEnabled(bool(self._folder) and os.path.isdir(self._folder))
        self.open_btn.clicked.connect(self.open_folder)
        top.addWidget(self.open_btn)
        v.addLayout(top)
        if f.path:
            shown = f.path.replace(home, '~', 1) if home and f.path.startswith(home) else f.path
            path = ElidedLabel(shown)
            path.setStyleSheet(_plain(f'color:{C["dim"]};font-size:11px;font-family:{MONO};'))
            v.addWidget(path)
        if f.advice:
            adv = QLabel(advice_text(f))
            adv.setWordWrap(True)
            adv.setStyleSheet(_plain(f'color:{C["text3"]};font-size:12px;font-family:{UI};'))
            v.addWidget(adv)
        if f.size and max_size:
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(max(8, int(1000 * f.size / max_size)))
            bar.setTextVisible(False)
            bar.setFixedHeight(3)
            bar.setStyleSheet(f'QProgressBar{{background:{C["bg3"]};border:none;border-radius:1px;}}'
                              f'QProgressBar::chunk{{background:{color};border-radius:1px;}}')
            v.addWidget(bar)

    def open_folder(self):
        if self._folder and os.path.isdir(self._folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._folder))


class AdvisorPage(QWidget):
    def __init__(self, home: str, pm: str = '', parent=None):
        super().__init__(parent)
        self._home, self._pm = home, pm
        self._worker = None
        self.report = None
        self._last_scan = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(10)
        self._title = QLabel(_t('adv_title', 'DISK ADVISOR'))
        self._title.setStyleSheet(f'color:{C["text"]};font-size:18px;font-weight:700;letter-spacing:1.2px;font-family:{UI};')
        self._sub = QLabel(_t('adv_sub', 'Where your disk space really went.'))
        self._sub.setStyleSheet(f'color:{C["text3"]};font-size:13px;font-family:{UI};')
        root.addWidget(self._title)
        root.addWidget(self._sub)
        self._callout = Callout(_t(
            'adv_callout', 'Read-only. This page only reads names and sizes — CyberClean never changes or deletes '
                           'anything here. You decide what to do with what it finds.'), 'purple')
        root.addWidget(self._callout)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._scan_btn = _btn(f"◎  {_t('btn_scan_disk', 'SCAN DISK')}", 'cyan')
        self._scan_btn.clicked.connect(self._toggle)
        self._copy_btn = _btn(_t('btn_copy_report', 'COPY REPORT'), small=True)
        self._copy_btn.clicked.connect(self.copy_report)
        self._copy_btn.setEnabled(False)
        self._status = QLabel('')
        self._status.setStyleSheet(f'color:{C["cyan"]};font-size:11px;font-family:{MONO};')
        bar.addWidget(self._scan_btn)
        bar.addWidget(self._copy_btn)
        bar.addSpacing(8)
        bar.addWidget(self._status, 1)
        root.addLayout(bar)
        self._prog = QProgressBar()
        self._prog.setRange(0, 0)
        self._prog.setTextVisible(False)
        self._prog.setFixedHeight(3)
        self._prog.setVisible(False)
        self._prog.setStyleSheet(f'QProgressBar{{background:{C["bg3"]};border:none;}}'
                                 f'QProgressBar::chunk{{background:{C["purple"]};}}')
        root.addWidget(self._prog)

        self._stack = QStackedLayout()
        root.addLayout(self._stack, 1)

        # ── 0: giới thiệu (chưa quét) ──
        intro = QWidget()
        il = QVBoxLayout(intro)
        il.addStretch()
        box = ElevatedCard(accent_color=C['purple'], shadow=True)
        box.setObjectName('intro')
        box.setMaximumWidth(620)
        bl = QVBoxLayout(box)
        bl.setContentsMargins(30, 26, 30, 26)
        bl.setSpacing(8)
        self._intro_icon = QLabel('◎')
        self._intro_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._intro_icon.setStyleSheet(_plain(f'color:{C["purple"]};font-size:38px;'))
        self._intro_title = QLabel(_t('adv_intro_title', 'See what is eating your disk'))
        self._intro_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._intro_title.setStyleSheet(_plain(f'color:{C["text"]};font-size:17px;font-weight:700;font-family:{UI};'))
        self._intro_body = QLabel(_t(
            'adv_intro_body',
            'Finds virtual machines, game libraries, /opt, the heaviest packages, forgotten node_modules / target / '
            'venv folders, big files and your Downloads. Takes about a minute.'))
        self._intro_body.setWordWrap(True)
        self._intro_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._intro_body.setStyleSheet(_plain(f'color:{C["text3"]};font-size:13px;font-family:{UI};'))
        for w in (self._intro_icon, self._intro_title, self._intro_body):
            bl.addWidget(w)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(box)
        row.addStretch()
        il.addLayout(row)
        il.addStretch()
        self._stack.addWidget(intro)

        # ── 1: kết quả ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet('QScrollArea{background:transparent;border:none;}')
        self._results = QWidget()
        self._results.setStyleSheet('background:transparent;')
        self._rl = QVBoxLayout(self._results)
        self._rl.setContentsMargins(0, 0, 6, 0)
        self._rl.setSpacing(12)
        self._scroll.setWidget(self._results)
        self._stack.addWidget(self._scroll)
        self._stack.setCurrentIndex(0)

    # ── điều khiển ──────────────────────────────────────────
    @property
    def scanning(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _toggle(self):
        if self.scanning:
            self._worker.stop()
            self._status.setText(_t('adv_stopping', 'Stopping…'))
        else:
            self.start()

    def start(self):
        if self.scanning:
            return
        self._scan_btn.setText(f"■  {_t('btn_stop', 'STOP')}")
        self._prog.setVisible(True)
        self._copy_btn.setEnabled(False)
        self._status.setStyleSheet(f'color:{C["cyan"]};font-size:11px;font-family:{MONO};')
        self._status.setText(_t('advisor_scanning', 'Scanning your disk…'))
        self._worker = _AdvisorWorker(self._home, self._pm)
        self._worker.progress.connect(lambda m: self._status.setText(f'⟳  {m}'))
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def shutdown(self):
        if self.scanning:
            self._worker.stop()
            self._worker.wait(5000)

    def retranslate(self):
        self._title.setText(_t('adv_title', 'DISK ADVISOR'))
        self._sub.setText(_t('adv_sub', 'Where your disk space really went.'))
        self._callout.setText(_t(
            'adv_callout', 'Read-only. This page only reads names and sizes — CyberClean never changes or deletes '
                           'anything here. You decide what to do with what it finds.'))
        self._scan_btn.setText(f"■  {_t('btn_stop', 'STOP')}" if self.scanning
                               else f"◎  {_t('btn_scan_disk', 'SCAN DISK')}")
        self._copy_btn.setText(_t('btn_copy_report', 'COPY REPORT'))
        self._intro_title.setText(_t('adv_intro_title', 'See what is eating your disk'))
        self._intro_body.setText(_t(
            'adv_intro_body',
            'Finds virtual machines, game libraries, /opt, the heaviest packages, forgotten node_modules / target / '
            'venv folders, big files and your Downloads. Takes about a minute.'))
        if self.report is not None:
            self._render(self.report)

    # ── kết quả ─────────────────────────────────────────────
    def _clear_results(self):
        while self._rl.count():
            item = self._rl.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _on_done(self, rep):
        self.report = rep
        self._last_scan = datetime.now()
        self._prog.setVisible(False)
        self._scan_btn.setText(f"◎  {_t('btn_rescan', 'RESCAN')}")
        self._status.setStyleSheet(f'color:{C["text3"]};font-size:11px;font-family:{MONO};')
        self._status.setText('  ·  '.join(rep.notes))
        self._copy_btn.setEnabled(bool(rep.findings))
        self._render(rep)

    def _render(self, rep):
        from core import advisor
        self._clear_results()
        groups = rep.by_category()
        if not rep.findings:
            self._status.setText(_t('advisor_nothing', 'Nothing large found — your disk looks tidy.'))
            self._stack.setCurrentIndex(0)
            return
        self._stack.setCurrentIndex(1)

        cats = [(c, sum(f.size for f in fs), fs) for c, fs in groups.items() if c != 'info']
        cats.sort(key=lambda x: -x[1])
        n_items = sum(len(fs) for _, _, fs in cats)

        # ── tổng quan ──
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        t1 = _Tile(_t('adv_tile_total', 'ACCOUNTED FOR'), 'cyan')
        t1.set(fmt_size(rep.total), _t('adv_tile_total_sub', 'across {n} findings').format(n=n_items))
        t2 = _Tile(_t('adv_tile_big', 'BIGGEST CATEGORY'), 'purple')
        if cats:
            c0, s0, _ = cats[0]
            share = int(100 * s0 / rep.total) if rep.total else 0
            t2.set(re.split(r'\s(?:&|và)\s', cat_title(c0))[0], f'{fmt_size(s0)} · {share}%')
        t3 = _Tile(_t('adv_tile_scan', 'SCAN'), 'green' if not rep.truncated else 'yellow')
        t3.set(('<1 s' if rep.seconds < 1 else f'{rep.seconds:.0f} s'), _t('adv_tile_partial', 'partial — hit the time limit') if rep.truncated
               else (self._last_scan.strftime('%H:%M') if self._last_scan else ''))
        for t in (t1, t2, t3):
            tiles.addWidget(t, 1)
        wrap = QWidget()
        wrap.setLayout(tiles)
        self._rl.addWidget(wrap)

        # ── thanh tỷ lệ + chú thích ──
        if cats:
            share_card = ElevatedCard(shadow=True)
            share_card.setObjectName('share')
            sl = QVBoxLayout(share_card)
            sl.setContentsMargins(16, 14, 16, 14)
            sl.setSpacing(10)
            bar = ShareBar()
            bar.set_data([(CAT_COLORS.get(c, C['text3']), s) for c, s, _ in cats])
            sl.addWidget(bar)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(5)
            for i, (c, s, _) in enumerate(cats):
                lab = QLabel(f'<span style="color:{CAT_COLORS.get(c, C["text3"])}">●</span>&nbsp; '
                             f'{cat_title(c)} <b style="color:{C["text"]}">{fmt_size(s)}</b>')
                lab.setTextFormat(Qt.TextFormat.RichText)
                lab.setStyleSheet(_plain(f'color:{C["text3"]};font-size:11px;font-family:{UI};'))
                grid.addWidget(lab, i // 3, i % 3)
            sl.addLayout(grid)
            self._rl.addWidget(share_card)

        # ── thẻ danh mục ──
        for cat, total, findings in [(c, sum(f.size for f in fs), fs) for c, fs in groups.items()]:
            color = CAT_COLORS.get(cat, C['text3'])
            card = ElevatedCard(accent_color=color, shadow=False)
            card.setObjectName('cat')
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 0, 0, 4)
            cl.setSpacing(0)
            head = QHBoxLayout()
            head.setContentsMargins(14, 12, 14, 10)
            ttl = QLabel(cat_title(cat))
            ttl.setStyleSheet(_plain(f'color:{color};font-size:13px;font-weight:700;letter-spacing:0.6px;font-family:{UI};'))
            head.addWidget(ttl)
            head.addStretch()
            if cat != 'info' and total:
                tot = QLabel(fmt_size(total))
                tot.setStyleSheet(_plain(f'color:{C["text"]};font-size:14px;font-weight:700;font-family:{MONO};'))
                head.addWidget(tot)
            cl.addLayout(head)
            biggest = max((f.size for f in findings), default=0)
            for f in findings:
                cl.addWidget(_FindingRow(f, biggest, color, self._home))
            self._rl.addWidget(card)
        self._rl.addStretch()
        self._scroll.verticalScrollBar().setValue(0)

    def copy_report(self):
        if self.report is None:
            return
        from core import advisor
        QApplication.clipboard().setText(advisor.report_to_text(self.report, self._home, cat_title=cat_title,
                                                                  advice=advice_text, title=finding_title))
        self._status.setStyleSheet(f'color:{C["green"]};font-size:11px;font-family:{MONO};')
        self._status.setText('✓ ' + _t('adv_copied', 'Report copied to the clipboard'))
        QTimer.singleShot(2500, lambda: self._status.setText('  ·  '.join(self.report.notes) if self.report else ''))
