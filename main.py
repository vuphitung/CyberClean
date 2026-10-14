"""
CyberClean — Main GUI  (v2.3 refactor)
═══════════════════════════════════════
All widgets, workers, and design tokens are now in ui_widgets.py.
This file only contains:
  • bootstrap / imports / OS detection
  • CyberCleanApp (QMainWindow subclass — pure logic, no widget code)
  • __main__ entry point

Refactor goals achieved:
  • main.py: 3409 → ~1640 lines  (–52%)
  • ui_widgets.py owns all QPainter icons, SparklineChart, DiskRing,
    HexLogoWidget, StatCard, NavButton, all QThread workers, UI helpers
  • CleanWorker and _AutoCleanWorker receive CLEANER via constructor param
    (no global reference inside worker thread — eliminates a class of race)
"""
import sys, os, json, time, platform

# ── Version (single source of truth: version.py) ──────────────
try:
    from version import __version__
except ImportError:
    __version__ = "0.0.0"
from pathlib import Path
from datetime import datetime
os.environ["QT_LOGGING_RULES"] = "qt.qpa.wayland*=false"
# HiDPI: Qt6 handles DPI scaling natively. PassThrough = let Qt scale correctly
# on all platforms (Windows 4K, mixed-DPI setups, Wayland HiDPI).
# Must be set before QApplication is created.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
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
except ImportError: _missing.append('psutil')
try:    from PyQt6.QtWidgets import QApplication
except ImportError: _missing.append('PyQt6')

if _missing:
    print(f"[CyberClean] Missing: {', '.join(_missing)}")
    print("Install: pip install psutil PyQt6")
    sys.exit(1)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QStackedWidget, QScrollArea,
    QTableWidget, QTableWidgetItem, QCheckBox, QProgressBar,
    QTextEdit, QHeaderView, QMessageBox, QSystemTrayIcon, QMenu,
    QSizePolicy, QLineEdit, QComboBox, QFileDialog, QDialog
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
from utils.sysinfo   import get_snapshot, fmt_size, fmt_speed, fmt_uptime
from core.uninstaller import get_installed_apps, InstalledApp
from utils.i18n import _t, T, SUPPORTED_LANGS
from utils.updater import UpdateDialog, UpdateBadge, UpdateCheckThread
from core.analyzer import IdleScheduler
from core import privileged as PRIV
from ui_pages import DeepCleanPage, AdvisorPage
from core.booster import (free_ram, memory_tune, memory_tune_restore,
                          clear_disk_cache, kill_bloat,
                          game_mode_on, game_mode_off, eco_mode_on, eco_mode_off,
                          smart_boost_on, smart_boost_off, detect_pc_tier)

# ── GameBoostPage (new 1-button cyber UI) ───────────────────────
try:
    from core.game_boost_widget import GameBoostPage as _GameBoostPage
    _HAS_GAME_BOOST_PAGE = True
except ImportError:
    _HAS_GAME_BOOST_PAGE = False
    _GameBoostPage = None


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

# ─────────────────────────────────────────────────────────────
# UI widgets, workers, design tokens — all in one place
# ─────────────────────────────────────────────────────────────
from ui_widgets import (
    C, MONO, DISPLAY, UI,
    # Icons
    _make_icon, _nav_icon,
    _icon_dashboard, _icon_clean,
    _icon_uninstall, _icon_history, _icon_rollback, _icon_booster,
    # Widgets
    SparklineChart, DiskRing, HexLogoWidget, StatCard, NavButton, CyberTerminal,
    DiskDeltaWidget, EmptyStateBinder,
    # UI helpers
    _btn, _lbl_section, _lbl_val, _card, _divider,
    # Workers
    SysInfoWorker, CleanWorker,
    _SmartOnWorker, _SmartOffWorker, _OneClickWorker,
    _UninstallWorker, _DoUninstallWorker, _AutoCleanWorker,
)

def _real_home():
    from core.os_detect import real_home
    return real_home()


class _HelperProbe(QThread):
    result = pyqtSignal(object)

    def run(self):
        try:
            self.result.emit(PRIV.helper_info(refresh=True))
        except Exception:
            pass


class _HelperUpgrade(QThread):
    result = pyqtSignal(bool, str)

    def run(self):
        r = PRIV.upgrade_helper_with_pkexec()
        self.result.emit(r.ok, r.message or r.err)


class _KillWorker(QThread):
    """psutil.terminate() nền. Kết quả về main thread bằng signal — QTimer.singleShot từ thread Python
    thường KHÔNG BAO GIỜ chạy (thread không có event loop) nên dialog kết quả cũ không bao giờ hiện
    và nút Kill bị khóa vĩnh viễn."""
    finished_with = pyqtSignal(list, list)

    def __init__(self, to_kill):
        super().__init__()
        self._to_kill = to_kill

    def run(self):
        killed, errors = [], []
        for pid_str, name in self._to_kill:
            try:
                psutil.Process(int(pid_str)).terminate()
                killed.append(name)
            except Exception as e:
                errors.append(f'{name}: {e}')
        self.finished_with.emit(killed, errors)


# MAIN APP
# ═════════════════════════════════════════════════════════════
class CyberCleanApp(QMainWindow):

    # Icon name per tab — maps to _ICON_FN keys
    _TAB_ICONS = {
        'dashboard': 'dashboard',
        'clean':     'smart_clean',
        'deep':      'deep_clean',
        'advisor':   'advisor',
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
            ('deep',      'deep_clean',  _t('nav_deep',      'DEEP CLEAN')),
            ('advisor',   'advisor',     _t('nav_advisor',   'DISK ADVISOR')),
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
        self._startup_snapshot_logged = False   # log disk snapshot once per day

        self._init_palette()
        self._build_ui()
        self._start_sysinfo()
        self._start_clock()
        self._nav('dashboard')
        self._setup_tray()
        self._start_auto_clean()
        self._check_update_async()
        self._check_helper_async()

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
                font-family:{UI};
            }}
            QScrollBar:vertical {{
                background:{C['bg']}; width:8px; border:none; margin:0;
            }}
            QScrollBar::handle:vertical {{
                background:{C['border3']}; border-radius:4px; min-height:28px;
            }}
            QScrollBar::handle:vertical:hover {{ background:{C['cyan']}70; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar:horizontal {{
                background:{C['bg']}; height:8px; border:none;
            }}
            QScrollBar::handle:horizontal {{
                background:{C['border3']}; border-radius:4px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
            QTableWidget {{
                background:{C['bg2']}; border:1px solid {C['border2']};
                gridline-color:{C['border']}; font-size:13px; border-radius:{C['radius']};
                selection-background-color:transparent;
                font-family:{UI};
            }}
            QTableWidget::item {{
                padding:8px 12px; border:none; background:transparent;
                color:{C['text2']};
            }}
            QTableWidget::item:alternate {{ background:{C['bg3']}; }}
            QTableWidget::item:hover {{
                background:{C['cyan']}12; color:{C['text']};
            }}
            QTableWidget::item:selected {{
                background:{C['cyan']}1c; color:{C['text']};
                border-left:2px solid {C['cyan']};
            }}
            QTableWidget:focus {{
                border:1px solid {C['ring']}80;
            }}
            QHeaderView::section {{
                background:{C['bg3']}; color:{C['text3']};
                border:none;
                border-bottom:1px solid {C['border2']};
                border-right:1px solid {C['border']};
                padding:10px 12px; font-size:11px; letter-spacing:1.2px;
                font-weight:700; font-family:{UI};
            }}
            QHeaderView::section:last {{ border-right:none; }}
            QCheckBox {{ color:{C['text2']}; spacing:10px; font-size:13px; }}
            QCheckBox::indicator {{
                width:16px; height:16px;
                border:1px solid {C['border3']}; background:transparent;
                border-radius:4px;
            }}
            QCheckBox::indicator:hover {{ border-color:{C['cyan']}80; }}
            QCheckBox::indicator:checked {{
                background:{C['cyan']}30; border-color:{C['cyan']};
            }}
            QCheckBox:focus {{ color:{C['text']}; }}
            QProgressBar {{
                background:{C['bg3']}; border:none; height:4px; border-radius:2px;
            }}
            QProgressBar::chunk {{
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['cyan']}, stop:1 {C['green']});
                border-radius:2px;
            }}
            QTextEdit {{
                background:{C['bg']}; color:{C['text2']};
                border:1px solid {C['border2']}; border-radius:{C['radius']};
                font-family:{MONO}; font-size:12px; padding:12px;
                selection-background-color:{C['cyan']}30;
            }}
            QLineEdit {{
                background:{C['bg3']}; color:{C['text']};
                border:1px solid {C['border2']}; border-radius:{C['radius']};
                padding:8px 14px; font-size:13px; font-family:{UI};
                min-height:20px;
            }}
            QLineEdit:hover {{ border-color:{C['border3']}; }}
            QLineEdit:focus {{ border:2px solid {C['ring']}; background:{C['bg4']}; }}
            QComboBox {{
                background:{C['bg3']}; color:{C['text2']};
                border:1px solid {C['border2']}; border-radius:{C['radius']};
                padding:6px 12px; font-size:13px; font-family:{UI};
                min-height:28px;
            }}
            QComboBox:hover {{ border-color:{C['border3']}; }}
            QComboBox:focus {{ border:2px solid {C['ring']}; }}
            QComboBox::drop-down {{ border:none; width:18px; }}
            QComboBox QAbstractItemView {{
                background:{C['bg2']}; color:{C['text']};
                selection-background-color:{C['cyan']}24;
                border:1px solid {C['border2']}; outline:none;
            }}
            QMenu {{
                background:{C['bg2']}; color:{C['text']};
                border:1px solid {C['border2']}; padding:6px;
                border-radius:{C['radius']};
            }}
            QMenu::item {{ padding:8px 18px; border-radius:6px; }}
            QMenu::item:selected {{ background:{C['cyan']}18; color:{C['cyan']}; }}
            QMenu::separator {{ background:{C['border2']}; height:1px; margin:4px 8px; }}
            QPushButton:focus {{ outline: none; }}
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
        h.setFixedHeight(52)
        h.setStyleSheet(f"""
            QFrame {{
                background:{C['bg2']};
                border-bottom:1px solid {C['border2']};
            }}
        """)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(0)

        # Hex logo widget — pure QPainter, no file
        hex_logo = HexLogoWidget(size=30)
        lay.addWidget(hex_logo)
        lay.addSpacing(10)

        logo_text = QLabel('CYBER')
        logo_text.setStyleSheet(
            f'color:{C["cyan"]};font-size:15px;font-weight:800;'
            f'letter-spacing:3px;font-family:{DISPLAY};'
        )
        sep_dot = QLabel('·')
        sep_dot.setStyleSheet(f'color:{C["border3"]};font-size:14px;padding:0 6px;')
        clean_text = QLabel('CLEAN')
        clean_text.setStyleSheet(
            f'color:{C["text"]};font-size:15px;font-weight:700;'
            f'letter-spacing:3px;font-family:{DISPLAY};'
        )
        ver = QLabel(f'v{__version__}')
        ver.setStyleSheet(
            f'color:{C["text3"]};font-size:11px;letter-spacing:0.4px;'
            f'padding-left:10px;padding-top:4px;font-family:{UI};'
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
            f'color:{C["text3"]};font-size:12px;letter-spacing:0.8px;font-family:{UI};'
        )
        lay.addWidget(self._os_info_lbl)
        lay.addStretch()

        # Update badge (hidden until GitHub release > current version)
        self._upd_lbl = UpdateBadge()
        self._upd_lbl.setStyleSheet(
            f'color:{C["yellow"]};font-size:11px;letter-spacing:0.6px;'
            f'font-family:{UI};border:1px solid {C["yellow"]}55;'
            f'padding:5px 10px;border-radius:{C["radius"]};'
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
        status_lbl = QLabel(_t('lbl_active', 'ACTIVE'))
        status_lbl.setStyleSheet(
            f'color:{C["text3"]};font-size:11px;letter-spacing:1px;font-family:{UI};'
        )
        self._lbl_status_active = status_lbl  # kept for retranslation
        sf_lay.addWidget(dot)
        sf_lay.addWidget(status_lbl)

        self.clock_lbl = QLabel('--:--:--')
        self.clock_lbl.setStyleSheet(
            f'color:{C["cyan"]};font-size:13px;letter-spacing:1px;'
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
        side.setFixedWidth(216)
        side.setStyleSheet(f"""
            QFrame {{
                background:{C['bg2']};
                border-right:1px solid {C['border2']};
            }}
        """)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 16, 0, 16)
        lay.setSpacing(2)

        # Navigation label
        nav_label = QLabel(_t('lbl_navigation', 'NAVIGATION'))
        nav_label.setStyleSheet(
            f'color:{C["dim"]};font-size:10px;letter-spacing:1.8px;'
            f'font-family:{UI};padding:0 16px 10px 16px;font-weight:700;'
        )
        self._lbl_navigation = nav_label  # kept for retranslation
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
                border-radius:{C['radius']};
                margin:0 12px;
            }}
        """)
        dp_lay = QVBoxLayout(disk_panel)
        dp_lay.setContentsMargins(12, 12, 12, 12)
        dp_lay.setSpacing(6)

        disk_header = QLabel('DISK USAGE')
        disk_header.setStyleSheet(
            f'color:{C["text3"]};font-size:10px;letter-spacing:1.6px;'
            f'font-family:{UI};font-weight:700;'
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
            f'color:{C["text3"]};font-size:12px;font-family:{UI};'
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
            f'color:{C["text3"]};font-size:11px;letter-spacing:0.2px;'
            f'padding:0 14px;line-height:1.6;font-family:{MONO};'
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
                    f'color:{col};font-size:10px;letter-spacing:0.8px;'
                    f'border:1px solid {col}55;padding:4px 8px;'
                    f'font-family:{UI};font-weight:700;border-radius:6px;'
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
        self.stack.addWidget(self._build_deep())
        self.stack.addWidget(self._build_advisor())
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
            f'color:{C["text"]};font-size:18px;font-weight:700;'
            f'letter-spacing:1.2px;font-family:{UI};'
        )
        fl.addWidget(t)
        s = None
        if subtitle:
            s = QLabel(subtitle)
            s.setStyleSheet(f'color:{C["text3"]};font-size:13px;font-family:{UI};')
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
        if pid == 'clean' and hasattr(self, '_disk_delta') \
                and self._snap and self._snap.disks:
            _d = self._snap.disks[0]
            self._disk_delta.set_before(_d.free, _d.total, _d.percent)
        if pid == 'clean' and IS_LINUX and not HAS_POLKIT_AGENT:
            self._show_polkit_warning()

    # ─────────────────────────────────────────────────────────
    # REDESIGNED DASHBOARD
    # ─────────────────────────────────────────────────────────
    def _build_dashboard(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        # Header row
        hdr = QHBoxLayout()
        self._lbl_sys_overview = QLabel(_t('sys_overview', 'SYSTEM OVERVIEW'))
        self._lbl_sys_overview.setStyleSheet(
            f'color:{C["text"]};font-size:18px;font-weight:700;'
            f'letter-spacing:1.2px;font-family:{UI};'
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
            f'color:{C["green"]};font-size:36px;font-weight:700;font-family:{MONO};'
        )
        self.health_sub = QLabel(_t('lbl_calculating', 'Calculating...'))
        self.health_sub.setStyleSheet(
            f'color:{C["text3"]};font-size:12px;font-family:{UI};'
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
            ('net',  'NET  ↓—',                                  '↑—',  'cyan'),
        ]:
            card_w = StatCard(label, init, col)
            self._stat_cards[sid] = card_w
            sc_row.addWidget(card_w)

        # Uptime label (small, sits under stat cards)
        self._lbl_uptime = QLabel('')
        self._lbl_uptime.setStyleSheet(
            f'color:{C["text3"]};font-size:12px;font-family:{UI};'
            f'letter-spacing:1px;padding-top:2px;'
        )
        uptime_row = QVBoxLayout()
        uptime_row.addLayout(sc_row)
        uptime_row.addWidget(self._lbl_uptime)
        lay.addLayout(uptime_row)

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
                f'color:{C["text3"]};font-size:11px;letter-spacing:1.4px;'
                f'font-family:{UI};font-weight:700;'
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
        self._kill_btn = _btn(f"✕ {_t('btn_kill','KILL')}", 'red', small=True)
        self._kill_btn.clicked.connect(self._kill_selected_proc)
        ph.addStretch(); ph.addWidget(self._kill_btn)
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
        self.proc_table.verticalHeader().setDefaultSectionSize(34)
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
        self.disk_table.verticalHeader().setDefaultSectionSize(34)
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
        self._preview_btn = _btn(f"⊡  {_t('btn_preview','PREVIEW FILES')}", 'yellow', small=True)
        self._preview_btn.clicked.connect(self._show_preview_files)
        # PREVIEW FILES chỉ có nghĩa trên Linux — trên Windows WinSxS và các
        # target hệ thống không enumerate được file list, gây đứng app.
        if IS_WINDOWS:
            self._preview_btn.setVisible(False)
        for b in [self._dry_btn, self._clean_btn, self._preview_btn, self._all_btn, self._none_btn]:
            ar.addWidget(b)
        ar.addStretch()
        lay.addLayout(ar)
        lay.addSpacing(12)

        # ── Progress bar (animated, glowing — hard to miss) ──────────────
        self._prog_container = QFrame()
        self._prog_container.setFixedHeight(44)
        self._prog_container.setStyleSheet('background:transparent;')
        self._prog_container.setVisible(False)
        prog_cl = QVBoxLayout(self._prog_container)
        prog_cl.setContentsMargins(0, 4, 0, 4); prog_cl.setSpacing(3)

        # Label row: status text left, % right
        prog_lbl_row = QHBoxLayout()
        self.clean_prog_lbl = QLabel('')
        self.clean_prog_lbl.setStyleSheet(
            f'color:{C["cyan"]};font-size:11px;font-family:{MONO};font-weight:600;'
            f'letter-spacing:1px;'
        )
        self._clean_prog_pct = QLabel('0%')
        self._clean_prog_pct.setStyleSheet(
            f'color:{C["text3"]};font-size:10px;font-family:{MONO};'
        )
        prog_lbl_row.addWidget(self.clean_prog_lbl)
        prog_lbl_row.addStretch()
        prog_lbl_row.addWidget(self._clean_prog_pct)
        prog_cl.addLayout(prog_lbl_row)

        # The actual bar — taller + styled with gradient + glow
        self.clean_prog = QProgressBar()
        self.clean_prog.setTextVisible(False)
        self.clean_prog.setFixedHeight(5)
        self.clean_prog.setStyleSheet(f'''
            QProgressBar {{
                background: {C["bg3"]};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {C["cyan"]}99,
                    stop:0.6 {C["cyan"]},
                    stop:1.0 #ffffff
                );
                border-radius: 2px;
            }}
        ''')
        prog_cl.addWidget(self.clean_prog)
        lay.addWidget(self._prog_container)
        lay.addSpacing(4)

        # ── Helper-status banner (hidden unless the privileged helper is missing/outdated) ──
        self._helper_banner = QFrame()
        self._helper_banner.setVisible(False)
        self._helper_banner.setStyleSheet(
            f'QFrame{{background:{C["yel_dim"]};border:1px solid {C["yellow"]}55;border-radius:{C["radius"]};}}'
            f'QLabel{{border:none;background:transparent;color:{C["yellow"]};font-size:12px;}}')
        hb = QHBoxLayout(self._helper_banner); hb.setContentsMargins(12, 8, 12, 8)
        self._helper_lbl = QLabel('')
        self._helper_lbl.setWordWrap(True)
        self._helper_btn = _btn(_t('btn_update_helper', 'UPDATE HELPER'), 'yellow', small=True)
        self._helper_btn.clicked.connect(self._upgrade_helper)
        hb.addWidget(self._helper_lbl, 1); hb.addWidget(self._helper_btn)
        lay.addWidget(self._helper_banner)
        lay.addSpacing(6)

        # ── Danh sách target — CHỈ tầng AUTO (tái tạo được, tick sẵn, được phép chạy nền) ──────────────
        # Tầng REVIEW (chọn từng mục) và ADVISOR (chỉ báo cáo) có trang riêng: DEEP CLEAN và DISK ADVISOR.
        self._lbl_clean_targets_sec = _lbl_section(_t('clean_targets', 'TARGETS'))
        lay.addWidget(self._lbl_clean_targets_sec)
        self._auto_caption = QLabel(_t('tier_auto_desc', 'Always regenerable · ticked by default · the only '
                                                          'targets the background scheduler may run.'))
        self._auto_caption.setWordWrap(True)
        self._auto_caption.setStyleSheet(f'color:{C["text3"]};font-size:11px;padding-bottom:6px;')
        lay.addWidget(self._auto_caption)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('border:none;background:transparent;')
        scroll.setMinimumHeight(220)
        sw = QWidget()
        sl = QVBoxLayout(sw); sl.setContentsMargins(0, 0, 4, 0); sl.setSpacing(4)

        self.target_checks = {}
        self._target_lbls  = {}   # {tid: (nm_label, dc_label, badge_label, target_obj)}
        targets = CLEANER.get_targets() if CLEANER else []

        def _make_row(t):
            row = QFrame()
            row.setObjectName('trow')        # chỉ áp style cho CHÍNH hàng này — QLabel con kế thừa QFrame nên
            sc = C['green'] if t.safety == 'safe' else C['yellow'] if t.safety == 'caution' else C['red']
            row.setStyleSheet(               # nếu không giới hạn bằng #trow, nhãn con cũng bị vẽ viền/nền của hàng
                f'QFrame#trow{{background:{C["bg2"]};'
                f'border-top:1px solid {C["border2"]};'
                f'border-right:1px solid {C["border2"]};'
                f'border-bottom:1px solid {C["border2"]};'
                f'border-left:3px solid {sc}90;'
                f'border-radius:{C["radius"]};}}'
                f'QFrame#trow:hover{{background:{C["bg3"]};border-color:{C["border3"]};}}'
                f'QFrame#trow QLabel{{border:none;background:transparent;}}'
            )
            rl = QHBoxLayout(row); rl.setContentsMargins(14, 8, 14, 8); rl.setSpacing(12)
            chk = QCheckBox()
            chk.setChecked(True)                              # tầng AUTO tick sẵn
            self.selected.add(t.id)
            chk.stateChanged.connect(lambda s_, tid=t.id: self._toggle(tid, s_))
            self.target_checks[t.id] = chk
            rl.addWidget(chk)
            nc = QVBoxLayout(); nc.setSpacing(2)
            nm = QLabel(_t(f'tgt_{t.id}_name', t.name) + (' [ROOT]' if t.needs_root else ''))
            nm.setStyleSheet(f'color:{C["text"]};font-size:13px;font-family:{UI};font-weight:600;')
            dc = QLabel(_t(f'tgt_{t.id}_desc', t.desc))
            dc.setWordWrap(True)
            dc.setStyleSheet(f'color:{C["text3"]};font-size:12px;font-family:{UI};')
            nc.addWidget(nm); nc.addWidget(dc)
            badge_map = {'safe': _t('badge_safe', 'SAFE'), 'caution': _t('badge_caution', 'CAUTION'),
                         'danger': _t('badge_danger', 'DANGER')}
            badge = QLabel(badge_map.get(t.safety, t.safety.upper()))
            badge.setStyleSheet(
                f'color:{sc};font-size:10px;letter-spacing:1px;font-weight:700;'
                f'border:1px solid {sc}55;padding:4px 10px;font-family:{UI};border-radius:6px;')
            self._target_lbls[t.id] = (nm, dc, badge, t)
            rl.addLayout(nc, 1)
            rl.addWidget(badge)
            sl.addWidget(row)

        for t in (t for t in targets if t.tier == 'auto'):
            _make_row(t)
        sl.addStretch()
        scroll.setWidget(sw)
        lay.addWidget(scroll, 3)          # stretch 3 : terminal 2
        lay.addSpacing(8)

        # ── Gợi ý (một dòng, không chiếm chỗ): hai chức năng còn lại có trang riêng ──────────────────
        hint = QFrame()
        hint.setObjectName('moreways')
        hint.setStyleSheet(f'QFrame#moreways{{background:transparent;border:1px dashed {C["border3"]};'
                           f'border-radius:{C["radius"]};}}'
                           f'QFrame#moreways QLabel{{border:none;background:transparent;}}')
        hl = QHBoxLayout(hint); hl.setContentsMargins(14, 6, 10, 6); hl.setSpacing(10)
        self._more_lbl = QLabel(_t('more_ways', 'Packages, Docker, dev caches, Trash — or find the biggest space hogs:'))
        self._more_lbl.setStyleSheet(f'color:{C["text3"]};font-size:12px;font-family:{UI};')
        self._more_deep_btn = _btn(f"{_t('nav_deep', 'DEEP CLEAN')} ›", 'yellow', small=True)
        self._more_deep_btn.clicked.connect(lambda: self._nav('deep'))
        self._more_adv_btn = _btn(f"{_t('nav_advisor', 'DISK ADVISOR')} ›", 'purple', small=True)
        self._more_adv_btn.clicked.connect(lambda: self._nav('advisor'))
        hl.addWidget(self._more_lbl, 1); hl.addWidget(self._more_deep_btn); hl.addWidget(self._more_adv_btn)
        lay.addWidget(hint)
        lay.addSpacing(10)

        # ── Disk Delta Widget (Before → Freed → After) ───────────────────
        # Wrapper frame keeps it always visible — labeled so user knows what it is
        delta_frame = QFrame()
        delta_frame.setObjectName('delta_frame')
        delta_frame.setStyleSheet(
            f'QFrame#delta_frame{{'
            f'background:{C["bg2"]};'
            f'border:1px solid {C["border2"]};'
            f'border-left:3px solid {C["cyan"]}60;'
            f'border-radius:{C["radius"]};'
            f'}}'
        )
        delta_fl = QVBoxLayout(delta_frame)
        delta_fl.setContentsMargins(0, 0, 0, 0); delta_fl.setSpacing(0)
        self._disk_delta = DiskDeltaWidget()
        self._disk_delta.setMinimumHeight(92)
        delta_fl.addWidget(self._disk_delta)
        lay.addWidget(delta_frame)

        # ── Cyber Terminal log ────────────────────────────────────────────
        self.clean_terminal = CyberTerminal()
        self.clean_terminal.set_placeholder(
            _t('placeholder_clean', '  →  Select targets and click DRY-RUN to preview...')
        )
        lay.addWidget(self.clean_terminal, 2)
        return w


    def _log_startup_disk_snapshot(self, disk_pct: float):
        """Log one disk-usage data point per day so the 30-day trend always has data."""
        today = datetime.now().date().isoformat()
        try:
            # Skip if we already logged a snapshot today
            if LOG_FILE.exists():
                lines = LOG_FILE.read_text().strip().splitlines()
                for line in reversed(lines[-20:]):
                    try:
                        e = json.loads(line)
                        if (e.get('summary') == 'auto_snapshot' and
                                e.get('time', '')[:10] == today):
                            return   # already logged today
                    except Exception:
                        pass
            entry = {
                'time':        datetime.now().isoformat(),
                'disk_before': round(disk_pct, 1),
                'disk_after':  round(disk_pct, 1),
                'freed_bytes': 0,
                'summary':     'auto_snapshot',
            }
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception:
            pass

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
            f'color:{C["text"]};font-size:18px;font-weight:700;'
            f'letter-spacing:1.2px;font-family:{UI};'
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
        self.uninstall_table.verticalHeader().setDefaultSectionSize(36)
        self._uninstall_empty = EmptyStateBinder(
            self.uninstall_table,
            _t('empty_apps_title', 'Không tìm thấy ứng dụng'),
            _t('empty_apps_body', 'Thử đổi bộ lọc, hoặc bấm Refresh để quét lại danh sách cài đặt.'),
        )
        lay.addWidget(self.uninstall_table, 1)

        btn_row = QHBoxLayout()
        un_btn = _btn(f"✕  {_t('btn_uninstall','UNINSTALL SELECTED')}", 'red')
        un_btn.clicked.connect(self._do_uninstall)
        self._uninst_btn = un_btn   # keep ref so _do_uninstall can lock/unlock it
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
            f'color:{C["text"]};font-size:18px;font-weight:700;'
            f'letter-spacing:1.2px;font-family:{UI};'
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
        self.log_table.verticalHeader().setDefaultSectionSize(36)
        self._log_empty = EmptyStateBinder(
            self.log_table,
            _t('empty_history_title', 'Chưa có lịch sử dọn'),
            _t('empty_history_body', 'Chạy DRY-RUN hoặc CLEAN trên tab Dọn rác — kết quả sẽ hiện ở đây.'),
        )
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
            f'color:{C["text"]};font-size:18px;font-weight:700;'
            f'letter-spacing:1.2px;font-family:{UI};'
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
        self.rollback_table.verticalHeader().setDefaultSectionSize(36)
        self._rollback_empty = EmptyStateBinder(
            self.rollback_table,
            _t('empty_rollback_title', 'Chưa có mục đã xóa'),
            _t('empty_rollback_body', 'Các thao tác gỡ/xóa sẽ được ghi lại tại đây để bạn đối chiếu sau này.'),
        )
        lay.addWidget(self.rollback_table, 1)
        return w

    # ─────────────────────────────────────────────────────────
    # REDESIGNED SYSTEM BOOSTER
    # ─────────────────────────────────────────────────────────
    def _build_browser_turbo(self):
        """
        NEW: GameBoostPage — 1 nút cyber, 4 giai đoạn, GPU busy metric.
        Thay thế hoàn toàn trang SYS BOOSTER cũ với 7 nút riêng lẻ.

        Logic:
          Phase 0 SCAN    — detect GPU, game PIDs, baseline GPU busy %
          Phase 1 APPLY   — free RAM → governor → mesa env → VFR → nice
          Phase 2 MONITOR — GPU busy % live từ sysfs mỗi 4s
          Phase 3 RESTORE — undo tất cả khi tắt
        """
        w = QWidget()
        w.setStyleSheet(f'background:{C.get("bg", "#0d1117")};')
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if _HAS_GAME_BOOST_PAGE and _GameBoostPage is not None:
            # ── New cyber UI ───────────────────────────────────
            self._game_boost_page = _GameBoostPage(w)
            outer.addWidget(self._game_boost_page)
        else:
            # ── Fallback: plain label nếu import thất bại ─────
            fallback = QLabel(
                "⚠  game_boost_widget.py not found\n"
                "Copy core/game_boost_widget.py vào project và restart."
            )
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setStyleSheet("color:#f0a500;font-size:13px;padding:40px;")
            outer.addWidget(fallback)

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
        except Exception:
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

        # Network speed (NEW: uses net_up_bps / net_down_bps from sysinfo v2.3)
        if hasattr(self, '_stat_cards') and 'net' in self._stat_cards:
            up_s   = fmt_speed(s.net_up_bps)   if s.net_up_bps   else '—'
            down_s = fmt_speed(s.net_down_bps) if s.net_down_bps else '—'
            self._stat_cards['net'].set_val(f'↑{up_s}', 'cyan')
            self._stat_cards['net'].lbl_name.setText(f'NET  ↓{down_s}')

        # Uptime (NEW: fmt_uptime from sysinfo v2.3)
        if hasattr(self, '_lbl_uptime') and s.uptime_seconds:
            self._lbl_uptime.setText(s.uptime_str)

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
            f'color:{C[col]};font-size:36px;font-weight:700;font-family:{MONO};'
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
            # Log daily disk snapshot for the 30-day trend (first snapshot each day)
            if not self._startup_snapshot_logged:
                self._startup_snapshot_logged = True
                QTimer.singleShot(500, lambda pct=d.percent: self._log_startup_disk_snapshot(pct))

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

        self._oneclick_worker = _OneClickWorker(cleaner=CLEANER)
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

        # Disable button while killing to prevent double-click
        if hasattr(self, '_kill_btn'):
            self._kill_btn.setEnabled(False)

        to_kill = []
        for row in rows:
            pid_item  = self.proc_table.item(row, 0)
            name_item = self.proc_table.item(row, 1)
            if pid_item:
                to_kill.append((pid_item.text(), name_item.text() if name_item else pid_item.text()))

        def _on_kill_done(killed, errors):
            if hasattr(self, '_kill_btn'):
                self._kill_btn.setEnabled(True)
            if errors:
                QMessageBox.warning(self, _t('kill_failed', 'Kill failed'), '\n'.join(errors))
            if killed:
                QMessageBox.information(
                    self, _t('lbl_done', 'Done'),
                    f"{_t('kill_failed','Terminated')}: {', '.join(killed)}"
                )
                QTimer.singleShot(1500, self._refresh_now)

        self._kill_worker = _KillWorker(to_kill)
        self._kill_worker.finished_with.connect(_on_kill_done, Qt.ConnectionType.QueuedConnection)
        self._kill_worker.start()

    def _toggle(self, tid, state):
        if state: self.selected.add(tid)
        else:     self.selected.discard(tid)

    def _sel_all(self):
        # Chỉ tầng AUTO có checkbox; REVIEW không bao giờ nằm trong "ALL"
        self.selected = set(self.target_checks)
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
        msg.setText(f'Clean {len(self.selected)} target(s)?\n\n' + '\n'.join(f'  • {n}' for n in names)
                    + '\n\n' + _t('confirm_perm_note', 'Files are deleted permanently — they do not go to the Trash.'))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.button(QMessageBox.StandardButton.Yes).setText('⚡ CLEAN NOW')
        msg.setStyleSheet(f'background:{C["bg2"]};color:{C["text"]};font-family:monospace;')
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._run_clean(dry=False)

    def _show_preview_files(self):
        """Open a dialog listing files that would be deleted for selected targets."""
        if not CLEANER or not self.selected:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(_t('preview_title', 'Preview — Files to be Deleted'))
        dlg.resize(700, 480)
        dlg.setStyleSheet(
            f'background:{C["bg"]};color:{C["text"]};font-family:{MONO};'
        )
        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(16, 16, 16, 16); vl.setSpacing(8)
        hdr = QLabel(f"  {_t('preview_desc', 'Files that would be deleted (up to 200 per target):')}")
        hdr.setStyleSheet(f'color:{C["text3"]};font-size:11px;')
        vl.addWidget(hdr)
        te = QTextEdit(); te.setReadOnly(True)
        te.setStyleSheet(
            f'background:{C["bg"]};color:{C["text2"]};border:1px solid {C["border2"]};'
            f'border-radius:{C["radius"]};font-size:12px;padding:10px;'
        )
        vl.addWidget(te, 1)
        total_lbl = QLabel('  Scanning…')
        total_lbl.setStyleSheet(f'color:{C["green"]};font-size:11px;font-family:{MONO};')
        vl.addWidget(total_lbl)
        btn_row = QHBoxLayout(); btn_row.addStretch()
        cb = _btn(_t('btn_close', 'CLOSE'), 'cyan', small=True)
        cb.clicked.connect(dlg.accept)
        btn_row.addWidget(cb)
        vl.addLayout(btn_row)

        # ── QThread + pyqtSignal — safe cross-thread UI update ──────────
        class _PrevWorker(QThread):
            result_ready = pyqtSignal(str, str)   # html, summary

            def __init__(self, selected, cleaner):
                super().__init__()
                self._sel = selected
                self._cl  = cleaner

            def run(self):
                total_b = 0; total_f = 0
                parts   = []
                for tid in sorted(self._sel):
                    try:
                        res   = self._cl.clean(tid, dry=True)
                        label = tid.replace('_', ' ').upper()
                        files = [(rb.get('path',''), rb.get('size',0))
                                 for rb in res.rollback]
                        if not files:
                            parts.append(
                                f'<span style="color:{C["text3"]}"><br>&nbsp;&nbsp;'
                                f'▸ {label}: ~{fmt_size(res.freed_bytes)} '
                                f'(file list unavailable)</span>'
                            )
                        else:
                            parts.append(
                                f'<span style="color:{C["cyan"]}"><br>&nbsp;&nbsp;'
                                f'▸ {label}&nbsp;&nbsp;({len(files)} files, '
                                f'{fmt_size(res.freed_bytes)})</span>'
                            )
                            for fpath, sz in files[:200]:
                                safe = fpath.replace('<','&lt;').replace('>','&gt;')
                                parts.append(
                                    f'<span style="color:{C["text3"]}">&nbsp;&nbsp;&nbsp;&nbsp;'
                                    f'{safe}&nbsp;'
                                    f'<span style="color:{C["text3"]}60">({fmt_size(sz)})</span>'
                                    f'</span><br>'
                                )
                            if len(files) > 200:
                                parts.append(
                                    f'<span style="color:{C["text3"]}">&nbsp;&nbsp;&nbsp;&nbsp;'
                                    f'… and {len(files)-200} more</span><br>'
                                )
                            total_b += res.freed_bytes
                            total_f += len(files)
                    except Exception as ex:
                        parts.append(
                            f'<span style="color:{C["red"]}"><br>&nbsp;&nbsp;'
                            f'✗ {tid}: {ex}</span>'
                        )
                html    = ''.join(parts) or f'<span style="color:{C["text3"]}">No files to preview.</span>'
                summary = f"  {total_f} files  ·  ~{fmt_size(total_b)}"
                self.result_ready.emit(html, summary)

        # FIX v2.5: Clean up previous _prev_worker before creating a new one.
        # Without this, opening the preview dialog multiple times accumulates
        # orphaned workers and their signals fire multiple times.
        if hasattr(self, '_prev_worker') and self._prev_worker is not None:
            try: self._prev_worker.result_ready.disconnect()
            except Exception: pass
            if not self._prev_worker.isRunning():
                self._prev_worker.deleteLater()
            self._prev_worker = None

        self._prev_worker = _PrevWorker(list(self.selected), CLEANER)

        def _apply(html, summary):
            te.setHtml(html)
            total_lbl.setText(summary)
            total_lbl.setStyleSheet(
                f'color:{C["green"]};font-size:11px;font-family:{MONO};'
            )

        self._prev_worker.result_ready.connect(_apply)
        self._prev_worker.start()
        dlg.exec()
        # Clean up worker after dialog closes
        if self._prev_worker.isRunning():
            self._prev_worker.quit()
            self._prev_worker.wait(2000)

    def _run_clean(self, dry=True):
        if not CLEANER or not self.selected: return
        # ── Properly tear down old worker before creating a new one ──────
        # This prevents the double-signal crash (emit from dead Python object)
        # that causes the app to crash on the 2nd clean run.
        if self.worker is not None:
            if self.worker.isRunning():
                return   # still running — ignore button press
            # Worker finished but still allocated: disconnect all signals to
            # prevent them firing again when we assign a new worker below.
            try:
                self.worker.log.disconnect()
                self.worker.progress.disconnect()
                self.worker.done.disconnect()
            except Exception:
                pass
            self.worker.deleteLater()
            self.worker = None
        # Snapshot disk BEFORE for visualization
        self._disk_pct_before = self._snap.disks[0].percent if self._snap and self._snap.disks else 0
        self._free_before     = self._snap.disks[0].free   if self._snap and self._snap.disks else 0
        # Reset viz panel
        if hasattr(self, '_disk_delta') and self._snap and self._snap.disks:
            d = self._snap.disks[0]
            self._disk_delta.set_before(d.free, d.total, d.percent)
        elif hasattr(self, '_disk_delta'):
            self._disk_delta.reset()
        self.clean_terminal.clear()
        self.clean_terminal.set_header(
            _t('btn_dryrun','DRY-RUN') if dry else _t('btn_clean_now','CLEAN NOW')
        )
        self.clean_prog_lbl.setText(f'⟳  {_t("btn_dryrun","DRY-RUN") if dry else _t("btn_clean_now","CLEAN NOW")}  ...')
        self._clean_prog_pct.setText('0%')
        self._prog_container.setVisible(True)
        self.clean_prog.setValue(0)
        self.worker = CleanWorker(list(self.selected), dry=dry, cleaner=CLEANER)
        self.worker.log.connect(self._on_clean_log)
        def _on_progress(p, l):
            self.clean_prog.setValue(p)
            self._clean_prog_pct.setText(f'{p}%')
            # Show target name, strip trailing '...' noise
            lbl = l.replace('— working...', '').replace('— done', '✓').strip()
            self.clean_prog_lbl.setText(f'⟳  {lbl}' if p < 100 else f'✓  {_t("lbl_done","Done")}')
        self.worker.progress.connect(_on_progress)
        # Lock action buttons so user knows cleaning is in progress
        self._dry_btn.setEnabled(False)
        self._clean_btn.setEnabled(False)
        self._dry_btn.setText(f'⟳  {_t("btn_dryrun","DRY-RUN")}')
        self.worker.done.connect(self._on_clean_done)
        self.worker.start()

    def _on_clean_log(self, msg, level):
        self.clean_terminal.append_log(msg, level)

    def _on_clean_done(self, result):
        self._prog_container.setVisible(False)
        # Restore action buttons
        self._dry_btn.setEnabled(True)
        self._clean_btn.setEnabled(True)
        self._dry_btn.setText(f"⬡  {_t('btn_dryrun','DRY-RUN')}")
        self._clean_btn.setText(f"⚡  {_t('btn_clean_now','CLEAN NOW')}")
        if not result['dry']:
            free_before = getattr(self, '_free_before', 0)
            pct_before = self._disk_pct_before

            def _deferred_snapshot():
                """Đo lại sau khi hệ thống kịp cập nhật số liệu; ghi lịch sử MỘT lần với số đo thật."""
                measured, pct_after = None, pct_before
                try:
                    snap_after = get_snapshot(interval=0.2)
                    if snap_after.disks:
                        d = snap_after.disks[0]
                        pct_after = d.percent
                        measured = d.free - free_before if free_before else None
                        self._snap = snap_after
                        self.disk_ring.set_percent(d.percent)
                        self.disk_detail_lbl.setText(f'{fmt_size(d.used)} / {fmt_size(d.total)}')
                    try:
                        self._on_snapshot(snap_after)
                    except Exception:
                        pass
                except Exception:
                    pass
                freed = result['freed']
                if measured is not None and hasattr(self, '_disk_delta') and snap_after.disks:
                    shown = max(measured, 0) if measured > 0 or freed == 0 else freed
                    self._disk_delta.set_after(snap_after.disks[0].free, pct_after, shown, dry=False)
                    if freed > 0 and measured < freed * 0.5:
                        self.clean_terminal.append_log(
                            f'  ⚠  Disk free space changed by {fmt_size(max(measured, 0))} while the plan removed '
                            f'{fmt_size(freed)}. Snapshots (Btrfs/ZFS), hardlinks or files still held open by a '
                            f'running app keep space allocated until they are released.', 'warn')
                self._record_session(freed=freed, summary=result['summary'], rollback=result['rollback'],
                                     disk_before=pct_before, disk_after=pct_after, measured=measured,
                                     planned=result.get('planned', freed))
            QTimer.singleShot(800, _deferred_snapshot)

        # ── Update AFTER viz panel (dry-run only — real handled in _deferred_snapshot) ─
        if hasattr(self, '_disk_delta') and result['freed'] > 0 and result['dry']:
            try:
                disk = self._snap.disks[0] if self._snap and self._snap.disks else None
                if disk and disk.total > 0:
                    est_free = disk.free + result['freed']
                    est_pct  = max(0.0, min(100.0,
                        (disk.total - est_free) / disk.total * 100))
                    self._disk_delta.set_before(disk.free, disk.total, disk.percent)
                    self._disk_delta.set_after(est_free, est_pct, result['freed'], dry=True)
            except Exception:
                pass

    def _record_session(self, *, freed, summary, rollback, disk_before, disk_after, measured=None, planned=None):
        """
        History + rollback log. `disk_after` là số ĐO sau khi dọn (trước đây luôn bằng disk_before vì
        chưa bao giờ được cập nhật) và `measured_bytes` là chênh lệch dung lượng trống thật.
        """
        try:
            session = {
                'time': datetime.now().isoformat(),
                'disk_before': round(disk_before, 1),
                'disk_after': round(disk_after, 1),
                'freed_bytes': freed,
                'planned_bytes': planned if planned is not None else freed,
                'measured_bytes': measured,
                'summary': summary,
            }
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, 'a') as f:
                f.write(json.dumps(session) + '\n')
            if rollback:
                with open(ROLLBACK_FILE, 'a') as f:
                    for e in rollback:
                        f.write(json.dumps(e) + '\n')
        except OSError:
            pass

    # ── Deep Clean (tầng REVIEW) / Disk Advisor (tầng ADVISOR) — hai trang riêng ─────────────
    def _build_deep(self):
        self.deep_page = DeepCleanPage(CLEANER)
        self.deep_page.cleaned.connect(self._on_review_cleaned)
        return self.deep_page

    def _build_advisor(self):
        self.advisor_page = AdvisorPage(str(_real_home()), PKG_MANAGER)
        return self.advisor_page

    def _on_review_cleaned(self, t, res):
        disk_pct = self._snap.disks[0].percent if self._snap and self._snap.disks else 0
        self._record_session(freed=res.freed_bytes,
                             summary=_t('review_logged', 'Review clean: {name}').format(name=t.name)
                             + f' | {t.id}:{fmt_size(res.freed_bytes)}',
                             rollback=res.rollback, disk_before=disk_pct, disk_after=disk_pct,
                             measured=res.measured_bytes, planned=res.planned_bytes)
        QTimer.singleShot(1500, self._refresh_now)

    def _check_helper_async(self):
        """Linux: kiểm tra helper đặc quyền (thiếu / bản cũ) và hiện banner — chạy nền, không chặn UI."""
        if not IS_LINUX or PRIV.IS_ROOT:
            return
        self._helper_worker = _HelperProbe()
        self._helper_worker.result.connect(self._on_helper_status, Qt.ConnectionType.QueuedConnection)
        self._helper_worker.start()

    def _on_helper_status(self, info):
        if info.outdated and PRIV.packaged_helper_in_app():
            self._helper_lbl.setText(_t('helper_outdated', '⚠ The privileged helper is out of date — a security fix is available.'))
            self._helper_btn.setVisible(True)
            self._helper_banner.setVisible(True)
        elif not info.installed:
            self._helper_lbl.setText(_t('helper_missing', 'ℹ Privileged helper not installed — re-run install.sh.'))
            self._helper_btn.setVisible(False)
            self._helper_banner.setVisible(True)
        else:
            self._helper_banner.setVisible(False)

    def _upgrade_helper(self):
        self._helper_btn.setEnabled(False)
        self._helper_upg = _HelperUpgrade()
        self._helper_upg.result.connect(self._on_helper_upgraded, Qt.ConnectionType.QueuedConnection)
        self._helper_upg.start()

    def _on_helper_upgraded(self, ok, msg):
        self._helper_btn.setEnabled(True)
        if ok:
            self._helper_banner.setVisible(False)
            QMessageBox.information(self, 'CyberClean', 'Helper updated.')
        else:
            QMessageBox.warning(self, 'CyberClean', f'Could not update the helper:\n{msg}')

    def _load_uninstall(self):
        # Guard: don't start a second scan while one is running
        if getattr(self, '_uninstall_worker', None) and self._uninstall_worker.isRunning():
            return
        # Lock UI during scan so user knows something is happening
        if hasattr(self, '_uninst_ref_btn'):
            self._uninst_ref_btn.setEnabled(False)
            self._uninst_ref_btn.setText('⟳ ...')
        if hasattr(self, '_lbl_uninst_hint'):
            self._lbl_uninst_hint.setText(
                f'<span style="color:{C["cyan"]}">⟳  Scanning installed apps...</span>'
            )
        self.uninstall_table.setRowCount(0)
        self.uninstall_log.clear()
        self.uninstall_log.append(
            f'<span style="color:{C["cyan"]}">  ⟳  Reading app registry — please wait...</span>'
        )

        self._uninstall_worker = _UninstallWorker()
        # Wire progress signal so hint label stays live during long winget scans
        self._uninstall_worker.progress.connect(
            lambda msg: self._lbl_uninst_hint.setText(
                f'<span style="color:{C["cyan"]}">{msg}</span>'
            ) if hasattr(self, '_lbl_uninst_hint') else None
        )
        self._uninstall_worker.finished.connect(self._on_uninstall_loaded)
        self._uninstall_worker.start()

    def _on_uninstall_loaded(self, apps):
        self._all_apps = apps
        self._populate_uninstall(apps)
        self.uninstall_log.clear()
        self.uninstall_log.append(
            f'<span style="color:{C["text3"]}">  ✓  {_t("uninstall_found","Found {n} apps — select one or more, then click Uninstall").replace("{n}", str(len(apps)))}</span>'
        )
        # Restore hint label and unlock refresh button
        if hasattr(self, '_lbl_uninst_hint'):
            self._lbl_uninst_hint.setText(
                _t('uninstall_hint', 'Select one or more apps  →  Uninstall')
            )
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
                'zypper': C['green'], 'xbps': C['cyan'],
                'flatpak': C['purple'], 'winget': C['cyan'],
                'registry': C['text3'], 'wmic': C['text3'],
            }.get(app.source, C['text'])
            src_lbl = 'winget' if app.source == 'winget' else \
                      'reg'    if app.source == 'registry' else app.source
            protected = bool(getattr(app, 'protected', False))
            for i, val in enumerate([('🔒 ' + app.name) if protected else app.name,
                                     app.version, sz, src_lbl]):
                ti = QTableWidgetItem(val)
                if i == 3: ti.setForeground(QColor(src_col))
                if i == 2 and app.size_mb > 200:
                    ti.setForeground(QColor(C['red']))
                if protected:
                    ti.setForeground(QColor(C['dim']))
                    ti.setToolTip('System package (kernel / bootloader / init / sudo / network …) — '
                                  'protected: CyberClean will not remove it.')
                self.uninstall_table.setItem(row, i, ti)
            self.uninstall_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, app)
        if hasattr(self, '_uninstall_empty'):
            self._uninstall_empty.sync()

    def _filter_uninstall(self, text):
        if not hasattr(self, '_all_apps'): return
        filtered = [a for a in self._all_apps if text.lower() in a.name.lower()]
        self._populate_uninstall(filtered)

    def _do_uninstall(self):
        # Guard: don't start another uninstall while one is running
        if getattr(self, '_do_uninst_worker', None) and self._do_uninst_worker.isRunning():
            QMessageBox.information(self, 'Busy', 'An uninstall is already in progress.')
            return

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

        # Gói lõi (kernel, bootloader, init, sudo, mạng...) không bao giờ được gỡ từ đây.
        blocked = [a for a in apps if getattr(a, 'protected', False)]
        if blocked:
            QMessageBox.warning(
                self, _t('confirm_uninstall', 'Uninstall'),
                'These are protected system packages and will NOT be removed:\n\n'
                + '\n'.join(f'  🔒 {a.name}' for a in blocked[:12])
                + '\n\nRemoving a kernel, bootloader, init system, sudo or the network manager can leave '
                  'the machine unable to boot or connect.')
            apps = [a for a in apps if a not in blocked]
            if not apps:
                return

        # Build richer confirmation text using uninstall_preview (NEW in uninstaller v2.3)
        total_mb = sum(a.size_mb for a in apps)
        lines = []
        for a in apps:
            try:
                p = a.uninstall_preview
                sz = f'{p["size_mb"]:.0f} MB' if p['size_mb'] > 0 else '—'
                rev = '' if p['reversible'] else '  ⚠ not reversible'
                lines.append(f'  • {a.name}  [{sz}]{rev}')
            except Exception:
                lines.append(f'  • {a.name}')

        detail = '\n'.join(lines[:10])
        if len(apps) > 10:
            detail += f'\n  … and {len(apps) - 10} more'
        size_str = f'\n\nTotal: ~{total_mb:.0f} MB' if total_mb > 0 else ''

        msg = QMessageBox(self)
        msg.setWindowTitle(_t('confirm_uninstall', 'Uninstall'))
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            f'Uninstall {len(apps)} app(s)?{size_str}\n\n{detail}'
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        msg.button(QMessageBox.StandardButton.Yes).setText('✕  UNINSTALL')
        msg.setStyleSheet(
            f'background:{C["bg2"]};color:{C["text"]};font-family:monospace;'
        )
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        # ── Lock UI so user sees progress, not a frozen window ──────
        self.uninstall_log.clear()
        self.uninstall_log.append(
            f'<span style="color:{C["cyan"]}">  ▸  Starting uninstall ({len(apps)} app(s))...</span>'
        )
        # Disable uninstall + refresh buttons during operation
        if hasattr(self, '_uninst_btn'):
            self._uninst_btn.setEnabled(False)
            self._uninst_btn.setText('⟳  UNINSTALLING...')
        if hasattr(self, '_uninst_ref_btn'):
            self._uninst_ref_btn.setEnabled(False)

        _col_map = {
            'ok': C['green'], 'err': C['red'],
            'info': C['text3'], 'warn': C['yellow'],
        }

        def _append_log(msg, level='info'):
            col = _col_map.get(level, C['text3'])
            self.uninstall_log.append(f'<span style="color:{col};">{msg}</span>')
            self.uninstall_log.verticalScrollBar().setValue(
                self.uninstall_log.verticalScrollBar().maximum()
            )

        def _on_one_done(app, result):
            """Remove successfully uninstalled app row immediately for instant feedback."""
            if result is True or result == 'UI_OPENED':
                for row in range(self.uninstall_table.rowCount()):
                    item = self.uninstall_table.item(row, 0)
                    if item and item.data(Qt.ItemDataRole.UserRole) == app:
                        self.uninstall_table.removeRow(row)
                        if hasattr(self, '_all_apps'):
                            try: self._all_apps.remove(app)
                            except ValueError: pass
                        break

        def _on_all_done(had_ui):
            """Re-enable UI after all apps processed."""
            if hasattr(self, '_uninst_btn'):
                self._uninst_btn.setEnabled(True)
                self._uninst_btn.setText(f"✕  {_t('btn_uninstall','UNINSTALL SELECTED')}")
            if hasattr(self, '_uninst_ref_btn'):
                self._uninst_ref_btn.setEnabled(True)
            _append_log('  ─────────────────────────────────────', 'info')
            if had_ui:
                _append_log(
                    f'  ℹ  {_t("lbl_installer_open","Installer window opened — complete it, then click REFRESH")}.',
                    'warn',
                )
            else:
                _append_log('  ✓  Done — refreshing list...', 'ok')
                QTimer.singleShot(1200, self._load_uninstall)

        # ── Launch in background thread — UI stays fully responsive ─
        self._do_uninst_worker = _DoUninstallWorker(apps)
        self._do_uninst_worker.log_line.connect(_append_log)
        self._do_uninst_worker.one_done.connect(_on_one_done)
        self._do_uninst_worker.all_done.connect(_on_all_done)
        self._do_uninst_worker.start()

    def _load_log(self):
        self.log_table.setRowCount(0)
        if LOG_FILE.exists():
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
                except Exception:
                    pass
        if hasattr(self, '_log_empty'):
            self._log_empty.sync()

    def _clear_log(self):
        if QMessageBox.question(self, 'Clear', 'Delete all history?') == QMessageBox.StandardButton.Yes:
            LOG_FILE.unlink(missing_ok=True)
            self.log_table.setRowCount(0)
            if hasattr(self, '_log_empty'):
                self._log_empty.sync()

    def _load_rollback(self):
        self.rollback_table.setRowCount(0)
        if ROLLBACK_FILE.exists():
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
                except Exception:
                    pass
        if hasattr(self, '_rollback_empty'):
            self._rollback_empty.sync()

    def _clear_rollback(self):
        if QMessageBox.question(self, 'Clear', 'Delete rollback history?') == QMessageBox.StandardButton.Yes:
            ROLLBACK_FILE.unlink(missing_ok=True)
            self.rollback_table.setRowCount(0)
            if hasattr(self, '_rollback_empty'):
                self._rollback_empty.sync()

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
                'The privileged helper is not installed, so root-level cleaning (system logs, package caches, '
                'journal) is unavailable.\n\n'
                'Fix: re-run the installer\n'
                '  curl -fsSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash\n\n'
                'Please do NOT start the whole app with sudo: the GUI loses access to your desktop session '
                '(Wayland/DBus) and may treat /root as your home folder.'
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

        # If OTA update is running, never minimize-to-tray; always shut down.
        try:
            upd_until = int(self._settings.value("upd_in_progress_until", 0) or 0)
        except Exception:
            upd_until = 0
        if upd_until > int(time.time()):
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
        # Sidebar static labels (NAVIGATION / ACTIVE)
        if hasattr(self, '_lbl_navigation'):
            self._lbl_navigation.setText(_t('lbl_navigation', 'NAVIGATION'))
        if hasattr(self, '_lbl_status_active'):
            self._lbl_status_active.setText(_t('lbl_active', 'ACTIVE'))

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
        if hasattr(self, '_kill_btn'):
            self._kill_btn.setText(f"✕ {_t('btn_kill','KILL')}")
        if hasattr(self, '_lbl_disk_sec'):
            self._lbl_disk_sec.setText(_t('lbl_disk', 'DISK USAGE'))
        for sid, key, default in [('temp','lbl_temperature','TEMPERATURE'),('swap','lbl_swap','SWAP')]:
            if hasattr(self, '_stat_cards') and sid in self._stat_cards:
                self._stat_cards[sid].lbl_name.setText(_t(key, default))
        # Reset NET card label on language change (speed suffix updated on next snapshot)
        if hasattr(self, '_stat_cards') and 'net' in self._stat_cards:
            self._stat_cards['net'].lbl_name.setText('NET  ↓—')
        if hasattr(self, 'proc_table'):
            self.proc_table.setHorizontalHeaderLabels([
                _t('col_pid','PID'), _t('col_name','NAME'),
                _t('col_cpu','CPU %'), _t('col_mem','MEM %')
            ])
        if hasattr(self, 'disk_table'):
            self.disk_table.setHorizontalHeaderLabels([
                _t('col_drive','Drive'),
                f"▲ {_t('col_used','Used')}",
                f"▽ {_t('col_free','Free')}",
                '%'
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
            self.clean_terminal.set_placeholder(_t('placeholder_clean', '  →  Select targets and click DRY-RUN to preview...'))

        # ── Clean tab — new widgets ───────────────────────────
        if hasattr(self, '_preview_btn'):
            self._preview_btn.setText(f"⊡  {_t('btn_preview','PREVIEW FILES')}")
        if hasattr(self, '_disk_delta') and self._snap and self._snap.disks:
            _d = self._snap.disks[0]
            self._disk_delta.set_before(_d.free, _d.total, _d.percent)

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
        if hasattr(self, '_log_empty'):
            self._log_empty.set_copy(
                _t('empty_history_title', 'Chưa có lịch sử dọn'),
                _t('empty_history_body', 'Chạy DRY-RUN hoặc CLEAN trên tab Dọn rác — kết quả sẽ hiện ở đây.'),
            )

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
        if hasattr(self, '_rollback_empty'):
            self._rollback_empty.set_copy(
                _t('empty_rollback_title', 'Chưa có mục đã xóa'),
                _t('empty_rollback_body', 'Các thao tác gỡ/xóa sẽ được ghi lại tại đây để bạn đối chiếu sau này.'),
            )
        if hasattr(self, '_uninstall_empty'):
            self._uninstall_empty.set_copy(
                _t('empty_apps_title', 'Không tìm thấy ứng dụng'),
                _t('empty_apps_body', 'Thử đổi bộ lọc, hoặc bấm Refresh để quét lại danh sách cài đặt.'),
            )
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
        if hasattr(self, '_auto_caption'):
            self._auto_caption.setText(_t('tier_auto_desc', 'Always regenerable · ticked by default · the only '
                                                             'targets the background scheduler may run.'))
            self._more_lbl.setText(_t('more_ways', 'Packages, Docker, dev caches, Trash — or find the biggest space hogs:'))
            self._more_deep_btn.setText(f"{_t('nav_deep', 'DEEP CLEAN')} ›")
            self._more_adv_btn.setText(f"{_t('nav_advisor', 'DISK ADVISOR')} ›")
        for _pg in (getattr(self, 'deep_page', None), getattr(self, 'advisor_page', None)):
            if _pg is not None:
                _pg.retranslate()
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
            self._smart_btn.setText(f'■  {tier_lbl} — {_t("lbl_smart_active","ACTIVE")}')
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
            except Exception: pass

        if getattr(self, '_eco_active', False):
            try:
                saved = getattr(self, '_eco_saved', {})
                eco_mode_off(saved, lambda m, l='text': None)
                self._eco_active = False
            except Exception: pass

        if hasattr(self, '_mem_tune_originals') and self._mem_tune_originals:
            try:
                memory_tune_restore(self._mem_tune_originals, lambda m, l='text': None)
            except Exception: pass

        if hasattr(self, '_si_worker'):
            self._si_worker.stop()
            self._si_worker.quit()
            self._si_worker.wait(2000)
        if hasattr(self, '_clock_timer'):
            self._clock_timer.stop()
        if hasattr(self, '_auto_clean_timer'):
            self._auto_clean_timer.stop()
        # Deep Clean / Disk Advisor: một lần xóa đang chạy phải được chờ xong, không bị cắt giữa chừng
        for _pg in (getattr(self, 'deep_page', None), getattr(self, 'advisor_page', None)):
            try:
                if _pg is not None:
                    _pg.shutdown()
            except Exception:
                pass
        # ── Stop all running workers gracefully ─────────────────────────────
        # CleanWorker — most critical: may be deleting files mid-operation
        if getattr(self, 'worker', None) and self.worker.isRunning():
            self.worker.stop()       # request graceful stop
            self.worker.quit()       # interrupt event loop
            if not self.worker.wait(4000):   # wait up to 4s for current target
                self.worker.terminate()      # force kill only if stuck
                self.worker.wait(1000)

        # Smart boost workers
        if getattr(self, '_smart_worker', None) and self._smart_worker.isRunning():
            self._smart_worker.stop()
            self._smart_worker.quit()
            self._smart_worker.wait(2000)
        if getattr(self, '_smart_off_worker', None) and self._smart_off_worker.isRunning():
            self._smart_off_worker.stop()
            self._smart_off_worker.quit()
            self._smart_off_worker.wait(2000)

        # Booster / one-click workers
        if getattr(self, '_booster_worker', None) and self._booster_worker.isRunning():
            self._booster_worker.quit()
            self._booster_worker.wait(1000)
        if getattr(self, '_oneclick_worker', None) and self._oneclick_worker.isRunning():
            self._oneclick_worker.stop()
            self._oneclick_worker.quit()
            self._oneclick_worker.wait(1000)

        # Uninstall worker
        if getattr(self, '_uninstall_worker', None) and self._uninstall_worker.isRunning():
            self._uninstall_worker.stop()
            self._uninstall_worker.quit()
            self._uninstall_worker.wait(1000)

        # Update check thread
        if getattr(self, '_upd_check_thread', None) and self._upd_check_thread.isRunning():
            self._upd_check_thread.wait(3000)

        # Auto-clean worker
        if getattr(self, '_auto_worker', None) and self._auto_worker.isRunning():
            self._auto_worker.stop()
            self._auto_worker.quit()
            self._auto_worker.wait(1000)

    def _start_auto_clean(self):
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
        # Nền chỉ chạy tầng AUTO có cờ `scheduled` (xem rules/*.toml + CleanTarget). Không còn danh sách
        # "bỏ qua" tên-theo-tên: tầng REVIEW (thùng rác, orphan, dev cache, Docker...) không bao giờ
        # được tự chạy, và cleaner tự từ chối lần nữa ở clean(..., unattended=True).
        safe_targets = [
            t.id for t in CLEANER.get_targets()
            if t.tier == 'auto' and t.scheduled and t.enabled
        ]
        if not safe_targets:
            return

        if getattr(self, '_auto_worker', None) and self._auto_worker.isRunning():
            if hasattr(self, 'tray'):
                self.tray.showMessage('CyberClean',
                                      'Already cleaning, please wait...',
                                      QSystemTrayIcon.MessageIcon.Warning, 2000)
            return

        self._auto_worker = _AutoCleanWorker(safe_targets, cleaner=CLEANER)
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

    CURRENT_VER = __version__

    def _check_update_async(self):
        # QThread (not threading.Thread): emitting from std threads can crash Qt on some Linux setups.
        self._upd_check_thread = UpdateCheckThread(self.CURRENT_VER, parent=self)
        self._upd_check_thread.found.connect(
            self._show_update_notice,
            Qt.ConnectionType.QueuedConnection,
        )
        self._upd_check_thread.start()

    def _show_update_notice(self, ver: str, body: str):
        self._pending_update_ver = ver
        self._pending_update_body = body
        self._upd_lbl.setText(_t("upd_badge", "⬆ v{ver} UPDATE", ver=ver))
        self._upd_lbl.setStyleSheet(
            f'color:{C["yellow"]};font-size:11px;letter-spacing:0.6px;'
            f'font-family:{UI};border:1px solid {C["yellow"]}55;'
            f'padding:5px 10px;border-radius:{C["radius"]};'
        )
        self._upd_lbl.setVisible(True)
        self._upd_lbl.raise_()
        if hasattr(self, "_tray_update_act"):
            self._tray_update_act.setVisible(True)
            self._tray_update_act.setText(_t('tray_view_update', '⬆  View update…'))
        try:
            if hasattr(self, "tray"):
                self.tray.showMessage(
                    "CyberClean — Update available",
                    _t("tray_upd_msg", f"v{ver}: click the header badge or tray → View update…", ver=ver),
                    QSystemTrayIcon.MessageIcon.Information,
                    6000,
                )
        except Exception:
            pass

    def _open_update_dialog(self):
        ver = getattr(self, "_pending_update_ver", "") or ""
        body = getattr(self, "_pending_update_body", "") or ""
        if not ver:
            return
        dlg = UpdateDialog(self, version=ver, body=body)
        dlg.exec()


# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # HiDPI rounding policy — set before QApplication for crisp rendering on 4K
    from PyQt6.QtCore import Qt as _Qt
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            _Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass
    app = QApplication(sys.argv)
    # Set QSettings identity early so the single-instance conflict branch can
    # detect "update in progress" and avoid the kill prompt.
    app.setOrganizationName('CyberClean')
    app.setApplicationName('CyberClean')
    app.setApplicationVersion(__version__)
    
    # Windows OTA: if update is in progress, don't ask the user to kill.
    # The update itself will restart the app after installation.
    try:
        upd_until = int(QSettings().value("upd_in_progress_until", 0) or 0)
    except Exception:
        upd_until = 0
    if upd_until > int(time.time()):
        msg = QMessageBox()
        msg.setWindowTitle('CyberClean - Updating')
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            'CyberClean đang cập nhật phiên bản mới. Vui lòng đợi vài phút rồi mở lại sau.'
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        sys.exit(0)

    # If we successfully acquired the single-instance lock, it's safe to clear
    # the "update in progress" flag (fresh start after OTA restart).
    try:
        QSettings().remove("upd_in_progress_until")
        QSettings().sync()
    except Exception:
        pass
    # Belt+suspenders: also clear via winreg directly on Windows
    # (QSettings may not flush if it was set by a dying process)
    if sys.platform == 'win32':
        try:
            import winreg as _wr
            _k = _wr.OpenKey(_wr.HKEY_CURRENT_USER,
                             r'Software\CyberClean\CyberClean',
                             0, _wr.KEY_SET_VALUE)
            try: _wr.DeleteValue(_k, 'upd_in_progress_until')
            except FileNotFoundError: pass
            _wr.CloseKey(_k)
        except Exception:
            pass

    # ── Single-instance lock (QLockFile — cross-platform, stale-lock safe) ──
    from PyQt6.QtCore import QLockFile
    import tempfile as _tmp2
    _lock_path = str(Path(_tmp2.gettempdir()) / 'CyberClean.lock')
    _lock_file  = QLockFile(_lock_path)
    _lock_file.setStaleLockTime(5000)   # 5s — treats stale locks as dead
    if not _lock_file.tryLock(200):     # wait 200ms in case of brief race
        err = QMessageBox()
        err.setWindowTitle('CyberClean')
        err.setIcon(QMessageBox.Icon.Warning)
        owner_pid, owner_host, owner_app = 0, '', ''
        try:
            owner_pid, owner_host, owner_app = _lock_file.getLockInfo()
        except Exception:
            pass
        msg = 'CyberClean is already running.'
        if owner_pid:
            msg += f'\n(PID {owner_pid} on {owner_host})'
        msg += '\n\nIf this is wrong, delete:\n' + _lock_path
        err.setText(msg)
        err.setStandardButtons(QMessageBox.StandardButton.Ok)
        err.exec()
        sys.exit(1)
    # Keep _lock_file alive for the process lifetime
    app._cc_lock = _lock_file

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
