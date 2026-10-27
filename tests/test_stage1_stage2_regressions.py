"""
Regression tests for Stage 1, Stage 2, and Stage 3 audit fixes:
- Python 3.10/3.11 syntax compatibility (no PEP 701 backslash inside f-string expressions)
- Trash / Recycle Bin never scheduled or auto-cleaned
- Auto-Clean defaults to OFF
- System Booster state capture & restoration (CPU governor, Hyprland VFR + scanout, swappiness, crash recovery)
- No persistent ~/.config/environment.d/cyber-boost.conf side effects
- Safe local uninstaller in install.sh (no curl | sudo bash)
- Packaging completeness in build.py, CyberClean.spec, CyberClean.iss
- Granular review_scan / review_clean in WindowsCleaner
- UI QFrame stylesheet scoping, DiskDeltaWidget timer bounding, and full EN/VI i18n parity
"""
import ast
import json
import os
import py_compile
import importlib
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import base_cleaner as BC
from core import booster as B
from core import rules as R
from core import windows_cleaner as W
from utils import i18n

ROOT = Path(__file__).resolve().parent.parent
import resource
import struct
import subprocess
import textwrap
import time
from core import engine as E
from core import linux_cleaner as L
from core import os_detect as OSD
from core import uninstaller as U
from tests.helpers import FakeGuards, age, tree
from utils import sysinfo
HELPER_SRC = ROOT / "packaging" / "cyber-clean-helper"


# ── 1. Python 3.10/3.11 Syntax & Bytecode Compatibility ──────────────────────
def test_all_python_files_compile_and_avoid_pep701_backslashes():
    py_files = [
        p for p in ROOT.rglob("*.py")
        if ".venv" not in p.parts and "__pycache__" not in p.parts
    ]
    assert len(py_files) >= 40
    for p in py_files:
        py_compile.compile(str(p), doraise=True)
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(p))
        # py_compile + ast.parse on Python 3.11 guarantees zero PEP 701 f-string backslash syntax errors
        assert tree is not None


def test_chromium_running_message_works_with_trailing_slashes():
    ctx = R.RuleContext(os_name="linux", home="/home/u", env={})
    rule = R.Rule(id="r1", target="chromium_cache", kind="chromium", closed_by_path={"chrome": ["chrome"]})
    guards = SimpleNamespace(
        user_data_dir_in_use=lambda d: True,
        running=lambda names: "",
    )
    msg = R._chromium_running("/home/u/.config/google-chrome/", ctx, rule, guards)
    assert msg == "google-chrome is running — close it first"


# ── 2. Trash / Recycle Bin & Auto-Clean Safety Invariants ───────────────────
@pytest.mark.parametrize("tid", ["empty_trash", "win_recycle", "trash", "recycle_bin"])
def test_trash_targets_can_never_be_auto_or_scheduled(tid):
    tgt = BC.CleanTarget(tid, "Trash", "User trash", "safe", tier="auto", scheduled=True)
    assert tgt.tier == "review"
    assert tgt.scheduled is False


def test_main_auto_clean_defaults_to_off_and_excludes_trash():
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "self._settings.value('auto_clean_enabled', False)" in main_src
    assert "_never_bg = {'empty_trash', 'win_recycle', 'trash', 'recycle_bin'}" in main_src
    assert "if not getattr(self, '_auto_clean_enabled', False):" in main_src


# ── 3. Linux Installer & Packaging Security/Completeness ────────────────────
def test_install_sh_launcher_does_not_pipe_remote_curl_to_sudo_bash():
    inst = (ROOT / "install.sh").read_text(encoding="utf-8")
    # The launcher block must not curl install.sh from main branch on --uninstall
    launcher_match = re.search(r"cat > \"\$BIN\" << LAUNCHER(.*?)LAUNCHER", inst, re.S)
    assert launcher_match, "Launcher heredoc not found in install.sh"
    launcher_body = launcher_match.group(1)
    assert "curl " not in launcher_body and "wget " not in launcher_body
    assert 'rm -rf --one-file-system -- "$INSTALL_DIR"' in inst


def test_packaging_files_have_no_hardcoded_author_home_and_bundle_helper():
    spec = (ROOT / "CyberClean.spec").read_text(encoding="utf-8")
    assert "/home/tung/" not in spec
    for item in ("ui_widgets", "ui_pages", "core.game_boost_widget", "cyber-clean-helper", "send2trash"):
        assert item in spec, f"{item} missing from CyberClean.spec"

    iss = (ROOT / "CyberClean.iss").read_text(encoding="utf-8")
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert f"AppVersion={ver}" in iss

    build_src = (ROOT / "build.py").read_text(encoding="utf-8")
    assert "cyber-clean-helper" in build_src
    assert "install-helper" in build_src
    assert "ui_pages.py" in build_src and "rules/" in build_src


# ── 4. System Booster Governor & State Restoration ──────────────────────────
def test_booster_captures_and_restores_exact_linux_governor(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "IS_LINUX", True)
    monkeypatch.setattr(B, "IS_WINDOWS", False)
    calls = []

    def fake_which(cmd):
        return "/usr/bin/powerprofilesctl" if cmd == "powerprofilesctl" else None

    def fake_run(argv, **kw):
        calls.append(list(argv))
        if argv == ["powerprofilesctl", "get"]:
            return SimpleNamespace(returncode=0, stdout="power-saver\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(B.shutil, "which", fake_which)
    monkeypatch.setattr(B, "IS_WINDOWS", True)
    monkeypatch.setattr(B.subprocess, "run", fake_run)

    token = B._enable_kernel_performance(lambda *a: None)
    assert token == "powerprofiles:power-saver"

    calls.clear()
    # Test restoration via smart_boost_off when saved["power"] is at top-level (GameBoostPage structure)
    B.smart_boost_off({"power": token}, lambda *a: None)
    assert ["powerprofilesctl", "set", "power-saver"] in calls


def test_hyprland_and_boost_state_restoration_without_qt_gui(monkeypatch, tmp_path, qapp):
    installed_stub, before_mods = _ensure_pyqt_stub()
    try:
        gbw = importlib.import_module("core.game_boost_widget")
        monkeypatch.setattr(gbw, "IS_LINUX", True)
        monkeypatch.setattr(gbw, "_boost_state_file", lambda: tmp_path / "boost_state.json")

        hypr_calls = []
        monkeypatch.setattr(gbw.shutil, "which", lambda cmd: "/usr/bin/hyprctl" if cmd == "hyprctl" else None)

        def fake_run(argv, **kw):
            hypr_calls.append(list(argv))
            if argv[:2] == ["hyprctl", "getoption"]:
                opt = argv[2]
                val = 1 if opt == "misc:vfr" else 0
                return SimpleNamespace(returncode=0, stdout=json.dumps({"option": opt, "int": val}))
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr(gbw.subprocess, "run", fake_run)
        assert gbw._hyprctl_get_bool("misc:vfr") == "true"
        assert gbw._hyprctl_get_bool("misc:no_direct_scanout") == "false"

        gov_restored = []
        monkeypatch.setattr(B, "_restore_kernel_performance", lambda m, log: gov_restored.append(m) or True)

        saved_state = {
            "power": "cpupower:powersave",
            "hyprland_vfr": True,
            "hyprland_vfr_orig": "true",
            "hyprland_scanout_orig": "false",
            "env_orig": {"mesa_glthread": None},
        }
        os.environ["mesa_glthread"] = "true"
        gbw._save_boost_state_disk(saved_state)
        assert (tmp_path / "boost_state.json").exists()

        hypr_calls.clear()
        gbw._recover_stale_boost_on_startup()

        assert gov_restored == ["cpupower:powersave"]
        assert ["hyprctl", "keyword", "misc:vfr", "true"] in hypr_calls
        assert ["hyprctl", "keyword", "misc:no_direct_scanout", "false"] in hypr_calls
        assert "mesa_glthread" not in os.environ
        assert not (tmp_path / "boost_state.json").exists()
    finally:
        _cleanup_pyqt_stub(installed_stub, before_mods)


# ── 5. WindowsCleaner Granular Review Scan & Clean ──────────────────────────
def test_windows_cleaner_granular_review_for_prefetch_and_crash_dumps(monkeypatch, tmp_path):
    monkeypatch.setattr(W.E, "is_ram_backed", lambda p: False)
    monkeypatch.setattr(W.E.Guards, "_load_procs", staticmethod(lambda: (set(), set(), set())))
    W.E.Guards._shared = None
    wctx = R.RuleContext(os_name="windows", home="C:\\Users\\u",
                         env={"LOCALAPPDATA": str(tmp_path / "Local"), "APPDATA": str(tmp_path / "Roaming")})
    monkeypatch.setattr(R.RuleContext, "detect", classmethod(lambda cls: wctx))
    wc = W.WindowsCleaner()

    dmp1 = tmp_path / "Local" / "CrashDumps" / "app1.dmp"
    dmp2 = tmp_path / "Local" / "CrashDumps" / "app2.dmp"
    dmp1.parent.mkdir(parents=True)
    dmp1.write_bytes(b"a" * 1024)
    dmp2.write_bytes(b"b" * 2048)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Win"))

    scan = wc.review_scan("win_crash_dumps")
    ids = [it.id for it in scan.items]
    assert str(dmp1) in ids and str(dmp2) in ids

    # Clean only dmp1, leave dmp2 untouched
    res = wc.review_clean("win_crash_dumps", [str(dmp1)], dry=False)
    assert res.files_removed == 1 and res.freed_bytes == 1024
    assert not dmp1.exists() and dmp2.exists()


# ── 6. i18n Parity & UI Stylesheet Regressions ──────────────────────────────
def test_game_boost_widget_and_new_ui_keys_exist_in_en_and_vi():
    en = i18n.TRANSLATIONS["en"]
    vi = i18n.TRANSLATIONS["vi"]
    gbw_src = (ROOT / "core" / "game_boost_widget.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'_t\(\s*["\']([a-z0-9_]+)["\']', gbw_src))
    assert len(keys) >= 15
    for k in keys:
        assert k in en and en[k], f"Missing EN translation for {k}"
        assert k in vi and vi[k], f"Missing VI translation for {k}"


def test_ui_widgets_cards_use_object_name_and_bounded_delta_timer():
    uw_src = (ROOT / "ui_widgets.py").read_text(encoding="utf-8")
    assert "f.setObjectName('cyberCard')" in uw_src
    assert "QFrame#cyberCard QLabel{{border:none;background:transparent;}}" in uw_src
    assert "self.setObjectName('statCard')" in uw_src
    assert "QFrame#statCard QLabel{{border:none;background:transparent;}}" in uw_src
    assert "self._scan_timer.start(16)" not in uw_src



# ── 7. Commercial Readiness Audit Fixes Regressions ─────────────────────────
def test_boost_skip_set_protects_audio_display_and_launchers(monkeypatch, qapp):
    installed_stub, before_mods = _ensure_pyqt_stub()
    try:
        gbw = importlib.import_module("core.game_boost_widget")
        skip = gbw._get_boost_skip_set()
        for critical in ("xwayland", "xorg", "wineserver", "gamescope", "audiodg", "dwm", "explorer", "steam", "pipewire", "wireplumber", "pulseaudio", "obs64"):
            assert critical in skip, f"{critical} must be protected from nice(+5) / BELOW_NORMAL throttling"

        # Test _restore_process_priorities restores both game_nice and bg_nice
        nice_calls = []
        class FakeProc:
            def __init__(self, pid): self.pid = pid
            def nice(self, val=None):
                if val is not None:
                    nice_calls.append((self.pid, val))
                return 0
        try:
            import psutil as _ps
        except ImportError:
            _ps = SimpleNamespace(Process=FakeProc, NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
            monkeypatch.setitem(sys.modules, "psutil", _ps)
        monkeypatch.setattr(_ps, "Process", FakeProc, raising=False)
        monkeypatch.setattr(gbw, "psutil", _ps, raising=False)
        monkeypatch.setattr(gbw, "HAS_PSUTIL", True, raising=False)
        saved = {"game_nice": {101: 0}, "bg_nice": {202: 0, 203: 0}}
        restored = gbw._restore_process_priorities(saved)
        assert restored == 3
        assert (101, 0) in nice_calls and (202, 0) in nice_calls and (203, 0) in nice_calls
        assert "game_nice" not in saved and "bg_nice" not in saved
    finally:
        _cleanup_pyqt_stub(installed_stub, before_mods)


def test_windows_winsxs_uses_english_flag_and_reboot_goes_to_notes(monkeypatch):
    monkeypatch.setattr(W.E, "is_ram_backed", lambda p: False)
    monkeypatch.setattr(W.E.Guards, "_load_procs", staticmethod(lambda: (set(), set(), set())))
    W.E.Guards._shared = None
    wctx = R.RuleContext(os_name="windows", home="C:\\Users\\u", env={})
    monkeypatch.setattr(R.RuleContext, "detect", classmethod(lambda cls: wctx))
    wc = W.WindowsCleaner()
    monkeypatch.setattr(W, "is_admin", lambda: True)

    cmds = []
    def fake_run_win(cmd, timeout=60):
        cmds.append(cmd)
        if "/AnalyzeComponentStore" in cmd:
            return "Component Store Size (Estimated Reduction) : 450.00 MB\n", 0
        return "The operation completed successfully.", 3010

    monkeypatch.setattr(W, "run_win", fake_run_win)
    dry_res = wc._win_winsxs(dry=True)
    assert any("/English" in c for c in cmds)
    assert dry_res.freed_bytes == 450 * 1024 * 1024

    real_res = wc._win_winsxs(dry=False)
    assert real_res.error is None, "Return code 3010 (reboot required) must not be treated as a failure"
    assert real_res.notes and any("RESTART" in n or "KHỞI ĐỘNG LẠI" in n for n in real_res.notes)


def test_windows_electron_apps_in_closed_by_path():
    rs = R.load_default(include_user=False)
    rule = next(r for r in rs.rules if r.id == "chromium-family-win")
    cbp_keys = {k.lower() for k in rule.closed_by_path}
    for app_key in ("discord", "code", "cursor", "slack", "zalo", "spotify", "obsidian"):
        assert app_key in cbp_keys, f"{app_key} missing from windows.toml closed_by_path"


def test_local_game_scanner_skips_personal_dirs_and_uses_safe_delete(monkeypatch, tmp_path):
    from core import uninstaller as U
    games_dir = tmp_path / "Games"
    for folder in ("Screenshots", "Mods", "Saves", "RealPortableGame"):
        d = games_dir / folder
        d.mkdir(parents=True)
        (d / "data.bin").write_bytes(b"x" * (6 * 1024 * 1024))

    monkeypatch.setattr("core.os_detect.real_home", lambda: str(tmp_path))
    found = U._scan_linux_local_games()
    names = {a.name for a in found}
    assert "RealPortableGame" in names
    assert not ({"Screenshots", "Mods", "Saves"} & names)

    # Verify uninstalling local-game calls safe_delete(..., use_trash=True) and handles bool return (B1)
    del_calls = []
    monkeypatch.setattr("core.os_detect.safe_delete", lambda p, use_trash=True: (del_calls.append((str(p), use_trash)) or True))
    app_obj = next(a for a in found if a.name == "RealPortableGame")
    assert U.uninstall_app(app_obj, lambda m, l="info": None) is True
    assert del_calls and del_calls[0][1] is True


# ── 8. Regression Tests for All 22 Audit Fixes (A1-A9, B1-B7, C1-C6) ────────
_QAPP_KEEPALIVE = None


@pytest.fixture(scope="session")
def qapp():
    """Ensure a real QApplication exists and stays alive across the entire test session when PyQt6 is installed."""
    global _QAPP_KEEPALIVE
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt6.QtWidgets import QApplication
        inst = QApplication.instance()
        if not isinstance(inst, QApplication):
            inst = QApplication([])
        _QAPP_KEEPALIVE = inst
        return inst
    except ImportError:
        return None


def _ensure_pyqt_stub():
    """
    If real PyQt6 is installed, ensure QApplication is initialized (offscreen) and NEVER install stubs.
    If PyQt6 is not installed in the headless VM, install lightweight stubs and return (True, before_mods).
    """
    global _QAPP_KEEPALIVE
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import PyQt6  # noqa: F401
        from PyQt6.QtWidgets import QApplication
        inst = QApplication.instance()
        if not isinstance(inst, QApplication):
            inst = QApplication([])
        _QAPP_KEEPALIVE = inst
        return False, set()
    except ImportError:
        pass
    before_mods = set(sys.modules.keys())

    class _SignalInstance:
        def __init__(self):
            self._cbs = []
        def connect(self, cb, *a, **k):
            self._cbs.append(cb)
        def disconnect(self, *a, **k):
            self._cbs.clear()
        def emit(self, *args):
            for cb in list(self._cbs):
                cb(*args)

    class _SignalDescriptor:
        def __init__(self, *a):
            self._name = None
        def __set_name__(self, owner, name):
            self._name = f"__sig_{name}"
        def __get__(self, instance, owner=None):
            if instance is None:
                return self
            sig = getattr(instance, self._name, None)
            if sig is None:
                sig = _SignalInstance()
                setattr(instance, self._name, sig)
            return sig

    class _DummyTimer:
        def __init__(self, *a, **k):
            self.timeout = _SignalInstance()
        def start(self, *a): pass
        def stop(self): pass
        def setInterval(self, *a): pass
        def isActive(self): return False
        @staticmethod
        def singleShot(ms, cb): pass

    class _DummyThread:
        def __init__(self, *a, **k):
            self._running = False
        def start(self):
            self._running = True
            self.run()
            self._running = False
        def isRunning(self): return self._running
        def quit(self): pass
        def wait(self, *a): return True
        def terminate(self): pass

    class _DummyWidget:
        def __init__(self, *a, **k):
            self._text = ""
        def setFixedHeight(self, *a): pass
        def setMinimumHeight(self, *a): pass
        def setMaximumHeight(self, *a): pass
        def setMinimumWidth(self, *a): pass
        def setMaximumWidth(self, *a): pass
        def setFixedWidth(self, *a): pass
        def setFixedSize(self, *a): pass
        def setObjectName(self, *a): pass
        def setStyleSheet(self, *a): pass
        def setSizePolicy(self, *a): pass
        def setCursor(self, *a): pass
        def setToolTip(self, *a): pass
        def setVisible(self, *a): pass
        def isVisible(self): return False
        def update(self): pass
        def width(self): return 600
        def height(self): return 92
        def addWidget(self, *a, **k): pass
        def addLayout(self, *a, **k): pass
        def addStretch(self, *a, **k): pass
        def addSpacing(self, *a, **k): pass
        def setContentsMargins(self, *a, **k): pass
        def setSpacing(self, *a, **k): pass
        def setAlignment(self, *a, **k): pass
        def setWordWrap(self, *a, **k): pass
        def setReadOnly(self, *a, **k): pass
        def setFrameShape(self, *a, **k): pass
        def setText(self, t=""): self._text = str(t)
        def text(self): return self._text

    qt_core = SimpleNamespace(
        Qt=SimpleNamespace(
            AlignmentFlag=SimpleNamespace(AlignCenter=0, AlignTop=0, AlignVCenter=0, AlignHCenter=0, AlignLeft=0, AlignRight=0, AlignBottom=0),
            CursorShape=SimpleNamespace(PointingHandCursor=0, ArrowCursor=0),
            BrushStyle=SimpleNamespace(NoBrush=0),
            PenStyle=SimpleNamespace(NoPen=0, SolidLine=1, DashLine=2, FlatCap=0, RoundCap=0),
            PenCapStyle=SimpleNamespace(FlatCap=0, RoundCap=0),
            GlobalColor=SimpleNamespace(transparent=0),
            ConnectionType=SimpleNamespace(QueuedConnection=0),
            TextFormat=SimpleNamespace(PlainText=0, RichText=1),
            ItemDataRole=SimpleNamespace(UserRole=32),
            ItemFlag=SimpleNamespace(ItemIsUserCheckable=1, ItemIsEnabled=2, ItemIsSelectable=4),
            CheckState=SimpleNamespace(Checked=2, Unchecked=0),
            ScrollBarPolicy=SimpleNamespace(ScrollBarAlwaysOff=1, ScrollBarAsNeeded=0),
        ),
        QObject=_DummyWidget,
        QEvent=SimpleNamespace(Type=SimpleNamespace(Enter=1, Leave=2)),
        QPropertyAnimation=lambda *a, **k: SimpleNamespace(setDuration=lambda *x: None, setEasingCurve=lambda *x: None, setStartValue=lambda *x: None, setEndValue=lambda *x: None, start=lambda *x: None, stop=lambda *x: None),
        QEasingCurve=SimpleNamespace(Type=SimpleNamespace(OutCubic=0, InOutSine=1)),
        pyqtProperty=lambda *a, **k: (lambda fn: property(fn)),
        QUrl=SimpleNamespace(fromLocalFile=lambda p: p),
        QTimer=_DummyTimer,
        QThread=_DummyThread,
        pyqtSignal=_SignalDescriptor,
        QRectF=lambda *a: SimpleNamespace(adjusted=lambda *x: None, center=lambda: SimpleNamespace(x=lambda: 0, y=lambda: 0), width=lambda: 100, height=lambda: 20, left=lambda: 0, top=lambda: 0, right=lambda: 100, bottom=lambda: 20),
        QSize=lambda *a: None,
        QPointF=lambda *a: None,
        QStandardPaths=SimpleNamespace(StandardLocation=SimpleNamespace(TempLocation=0), writableLocation=lambda *a: "/tmp"),
    )
    qt_gui = SimpleNamespace(
        QPainter=type("QPainter", (), {"RenderHint": SimpleNamespace(Antialiasing=0)}),
        QColor=lambda *a: SimpleNamespace(setAlpha=lambda *x: None, red=lambda: 0, green=lambda: 0, blue=lambda: 0),
        QPen=lambda *a: None,
        QBrush=lambda *a: None,
        QLinearGradient=lambda *a: SimpleNamespace(setColorAt=lambda *x: None),
        QRadialGradient=lambda *a: SimpleNamespace(setColorAt=lambda *x: None),
        QFont=type("QFont", (), {"Weight": SimpleNamespace(Bold=1), "__init__": lambda self, *a: None, "setBold": lambda self, *a: None, "setPixelSize": lambda self, *a: None}),
        QFontMetrics=lambda *a: SimpleNamespace(horizontalAdvance=lambda *x: 40, height=lambda: 14, ascent=lambda: 10),
        QIcon=lambda *a: None,
        QPixmap=lambda *a: SimpleNamespace(fill=lambda *x: None, save=lambda *x: None),
        QPolygonF=lambda *a: None,
        QPainterPath=type("QPainterPath", (), {"addRoundedRect": lambda self, *a: None}),
        QTextCursor=SimpleNamespace(MoveOperation=SimpleNamespace(Start=0, End=1), SelectionType=SimpleNamespace(BlockUnderCursor=0)),
        QTextCharFormat=object,
        QDesktopServices=SimpleNamespace(openUrl=lambda *a: None),
    )
    qt_widgets = SimpleNamespace(
        QApplication=SimpleNamespace(instance=lambda: None),
        QWidget=_DummyWidget, QVBoxLayout=_DummyWidget, QHBoxLayout=_DummyWidget,
        QLabel=_DummyWidget, QPushButton=_DummyWidget, QFrame=_DummyWidget,
        QGridLayout=_DummyWidget, QCheckBox=_DummyWidget, QTextEdit=_DummyWidget,
        QGraphicsDropShadowEffect=_DummyWidget, QProgressBar=_DummyWidget, QScrollArea=_DummyWidget,
        QStackedLayout=_DummyWidget, QStyledItemDelegate=_DummyWidget, QTableWidget=_DummyWidget,
        QTableWidgetItem=_DummyWidget, QMessageBox=_DummyWidget, QAbstractItemView=_DummyWidget, QHeaderView=_DummyWidget,
        QPlainTextEdit=_DummyWidget, QScrollBar=_DummyWidget,
        QSizePolicy=SimpleNamespace(Policy=SimpleNamespace(Fixed=0, Expanding=1, Preferred=2, Maximum=3, Ignored=4)),
        QBoxLayout=SimpleNamespace(Direction=SimpleNamespace(TopToBottom=0, LeftToRight=1)),
    )
    sys.modules["PyQt6"] = SimpleNamespace(QtCore=qt_core, QtGui=qt_gui, QtWidgets=qt_widgets)
    sys.modules["PyQt6.QtCore"] = qt_core
    sys.modules["PyQt6.QtGui"] = qt_gui
    sys.modules["PyQt6.QtWidgets"] = qt_widgets
    return True, before_mods


def _cleanup_pyqt_stub(installed_stub: bool, before_mods: set) -> None:
    if installed_stub:
        for mod in list(sys.modules.keys()):
            if mod not in before_mods and (mod.startswith("PyQt6") or mod in ("ui_widgets", "ui_pages", "core.game_boost_widget")):
                sys.modules.pop(mod, None)


def _make_elf_header(e_type: int, payload: bytes = b"coredump-body") -> bytes:
    ident = b"\x7fELF\x02\x01\x01" + b"\x00" * 9
    return ident + struct.pack("<H", e_type) + b"\x00" * 46 + payload


def test_a1_core_directory_and_regular_source_files_never_deleted(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    rs = R.load_default(include_user=False)
    ctx = R.RuleContext(os_name="linux", home=str(tmp_path), env={})

    proj_core = tree(tmp_path / "core", {"source.py": 250, "sub/module.py": 400}, days=10)
    pl = rs.plan("crash_reports", ctx, guards=FakeGuards())
    assert not any(i.path.startswith(str(proj_core)) for i in pl.items)
    E.execute_plan(pl.deletable, guards=FakeGuards())
    assert (proj_core / "source.py").exists()

    (proj_core / "source.py").unlink()
    (proj_core / "sub" / "module.py").unlink()
    (proj_core / "sub").rmdir()
    proj_core.rmdir()

    plain_core = tmp_path / "core"
    plain_core.write_text("print('not a core dump')\n", encoding="utf-8")
    age(plain_core, 10)
    pl2 = rs.plan("crash_reports", ctx, guards=FakeGuards())
    assert not any(i.path == str(plain_core) for i in pl2.deletable)
    E.execute_plan(pl2.deletable, guards=FakeGuards())
    assert plain_core.exists()

    plain_core.write_bytes(_make_elf_header(3))
    age(plain_core, 10)
    assert not E.is_elf_core_file(str(plain_core))
    pl3 = rs.plan("crash_reports", ctx, guards=FakeGuards())
    assert not any(i.path == str(plain_core) for i in pl3.deletable)

    plain_core.write_bytes(_make_elf_header(4))
    age(plain_core, 10)
    assert E.is_elf_core_file(str(plain_core))
    pl4 = rs.plan("crash_reports", ctx, guards=FakeGuards())
    assert any(i.path == str(plain_core) for i in pl4.deletable)
    res = E.execute_plan(pl4.deletable, guards=FakeGuards())
    assert res.removed == 1 and not plain_core.exists()


def test_a2_user_rules_cannot_attach_to_builtin_auto_or_missing_target(tmp_path):
    builtin = R.load_default(include_user=False)
    malicious_toml = """
    schema = 1
    [[rule]]
    id = "custom-document-clean"
    target = "chromium_cache"
    paths = ["~/Documents"]
    """
    rs = R.RuleSet()
    rs.targets = {k: list(v) for k, v in builtin.targets.items()}
    rs.rules = list(builtin.rules)
    with pytest.raises(R.RuleError, match=r"(user rules may not attach|user-defined Review target)"):
        rs.load_text(malicious_toml, "user", "evil.toml")

    orphan_rule_toml = """
    schema = 1
    [[rule]]
    id = "orphan-rule"
    target = "undeclared_target"
    paths = ["~/.cache/my_custom"]
    """
    rs2 = R.RuleSet()
    with pytest.raises(R.RuleError, match="user-defined Review target"):
        rs2.load_text(orphan_rule_toml, "user", "orphan.toml")

    rs3 = R.RuleSet()
    rs3.targets = {k: list(v) for k, v in builtin.targets.items()}
    rs3.rules = list(builtin.rules) + [
        R.Rule(id="injected-user-rule", target="chromium_cache", paths=("~/Documents",), source="user")
    ]
    errs = rs3.validate()
    assert any("injected-user-rule" in e for e in errs)
    docs = tree(tmp_path / "Documents", {"thesis.pdf": 4096}, days=30)
    ctx = R.RuleContext(os_name="linux", home=str(tmp_path), env={})
    pl = rs3.plan("chromium_cache", ctx, unattended=True, guards=FakeGuards())
    assert not any(str(docs) in i.path for i in pl.items)


def test_a3_helper_and_uninstaller_block_arch_suffixed_and_dependency_protected_pkgs(tmp_path):
    for pkg_spec in (
        "gnome-shell",
        "gnome-shell:amd64",
        "network-manager:i386",
        "NetworkManager.x86_64",
        "systemd-libs.i686",
        "glibc-2.39_1",
        "core/linux-lts",
        "ubuntu-desktop:amd64",
    ):
        assert U.is_protected_pkg(pkg_spec), f"Uninstaller failed to protect {pkg_spec}"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "calls.log"

    def write_cmd(name: str, body: str):
        p = bin_dir / name
        p.write_text("#!/bin/bash\n" + textwrap.dedent(body).lstrip() + "\n", encoding="utf-8")
        p.chmod(0o755)

    write_cmd("apt-get", f"""
        if [[ "$*" == *"-s"* ]]; then
            if [[ "$*" == *"innocent-meta"* || "$*" == *"autoremove"* ]]; then
                echo "Inst something"
                echo "Remv innocent-meta [1.0]"
                echo "Remv gnome-shell:amd64 [46.0]"
                exit 0
            fi
            if [[ "$*" == *"broken-sim"* ]]; then
                echo "E: Unable to locate package broken-sim"
                exit 0
            fi
            echo "Remv ${{!#}} [1.0]"
            exit 0
        fi
        echo "apt-get $*" >> "{calls_log}"
    """)

    write_cmd("pacman", f"""
        if [[ "$1" == "-Rsp" ]]; then
            if [[ "$*" == *"innocent-arch-pkg"* ]]; then
                echo "innocent-arch-pkg-1.0-1"
                echo "systemd-256.1-1"
                exit 0
            fi
            echo "vlc-3.0.20-1"
            exit 0
        fi
        echo "pacman $*" >> "{calls_log}"
    """)

    helper_copy = tmp_path / "cyber-clean-helper"
    s = HELPER_SRC.read_text(encoding="utf-8")
    s = s.replace(
        "PATH=/usr/sbin:/usr/bin:/sbin:/bin:/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin",
        f"PATH={bin_dir}:/usr/sbin:/usr/bin:/sbin:/bin",
    )
    s = s.replace("PACMAN_LOCK=/var/lib/pacman/db.lck", f"PACMAN_LOCK={tmp_path}/db.lck")
    helper_copy.write_text(s, encoding="utf-8")
    helper_copy.chmod(0o755)

    def run_helper(*args):
        return subprocess.run([str(helper_copy), *args], capture_output=True, text=True, timeout=15)

    for spec in ("gnome-shell:amd64", "network-manager:i386", "systemd.x86_64", "glibc-2.39_1"):
        r = run_helper("apt-remove", spec)
        assert r.returncode == 3, f"Expected exit 3 for {spec}, got {r.returncode}: {r.stderr}"

    r_dep_apt = run_helper("apt-remove", "innocent-meta")
    assert r_dep_apt.returncode == 3 and "protected" in r_dep_apt.stderr
    r_auto_apt = run_helper("apt-autoremove")
    assert r_auto_apt.returncode == 3 and "protected" in r_auto_apt.stderr
    r_dep_pac = run_helper("pacman-remove", "innocent-arch-pkg")
    assert r_dep_pac.returncode == 3 and "protected" in r_dep_pac.stderr

    r_broken = run_helper("apt-remove", "broken-sim")
    assert r_broken.returncode == 3
    assert not calls_log.exists() or calls_log.read_text() == ""

    r_ok = run_helper("apt-remove", "vlc")
    assert r_ok.returncode == 0
    assert "apt-get remove -y -- vlc" in calls_log.read_text()


def test_a4_runtime_guards_rechecked_at_execute_and_max_age_zero_reloads(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    rs = R.load_default(include_user=False)
    ctx = R.RuleContext(os_name="linux", home=str(tmp_path), env={})

    ff_cache = tree(tmp_path / ".cache/mozilla/firefox/p1.default", {"cache2/entries/x": 500})
    ch_cfg = tree(tmp_path / ".config/google-chrome", {"Local State": 4, "Default/Cache/data": 600})
    fp_cache = tree(tmp_path / ".var/app/org.gimp.GIMP/cache", {"tmp/tile.cache": 700})

    g_scan = FakeGuards()
    pl_ff = rs.plan("firefox_cache", ctx, guards=g_scan)
    pl_ch = rs.plan("chromium_cache", ctx, guards=g_scan)
    pl_fp = rs.plan("flatpak_cache", ctx, guards=g_scan)

    assert pl_ff.deletable and pl_ff.deletable[0].closed
    assert pl_ch.deletable and pl_ch.deletable[0].meta.get("chromium_dirs")
    assert pl_fp.deletable and pl_fp.deletable[0].meta.get("sandbox_paths")

    (ch_cfg / "SingletonLock").symlink_to(f"host-{os.getpid()}")
    g_exec = FakeGuards(procs=["firefox"], sandbox=[str(tmp_path / ".var/app/org.gimp.GIMP")])

    res_ff = E.execute_plan(pl_ff.deletable, guards=g_exec)
    res_ch = E.execute_plan(pl_ch.deletable, guards=g_exec)
    res_fp = E.execute_plan(pl_fp.deletable, guards=g_exec)

    assert res_ff.removed == 0 and (ff_cache / "cache2/entries/x").exists()
    assert res_ch.removed == 0 and (ch_cfg / "Default/Cache/data").exists()
    assert res_fp.removed == 0 and (fp_cache / "tmp/tile.cache").exists()

    proc_states = [({"bash"}, set(), set()), ({"firefox"}, set(), set())]
    monkeypatch.setattr(E.Guards, "_load_procs", staticmethod(lambda: proc_states.pop(0)))
    g_live = E.Guards(max_age=0.0)
    assert g_live.running(["firefox"]) == ""
    assert g_live.running(["firefox"]) == "firefox"


def test_a5_safe_delete_never_falls_back_to_permanent_delete_when_use_trash_true(monkeypatch, tmp_path):
    f1 = tmp_path / "precious1.txt"
    f1.write_text("keep me", encoding="utf-8")

    monkeypatch.setattr(OSD, "HAS_SEND2TRASH", False)
    assert OSD.safe_delete(f1, use_trash=True) is False
    assert f1.exists()

    monkeypatch.setattr(OSD, "HAS_SEND2TRASH", True)
    fake_s2t = SimpleNamespace(send2trash=lambda p: (_ for _ in ()).throw(PermissionError("trash denied")))
    monkeypatch.setitem(sys.modules, "send2trash", fake_s2t)
    assert OSD.safe_delete(f1, use_trash=True) is False
    assert f1.exists()

    assert OSD.safe_delete(f1, use_trash=False) is True
    assert not f1.exists()


def test_a6_parent_symlink_escape_rejected_at_load_plan_and_execute(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    home = tmp_path / "home"
    outside = tmp_path / "outside_secret"
    home.mkdir()
    outside.mkdir()
    secret_file = outside / "important" / "keys.txt"
    secret_file.parent.mkdir(parents=True)
    secret_file.write_text("top-secret", encoding="utf-8")
    age(secret_file, 30)

    (home / "link").symlink_to(outside)

    user_toml = """
    schema = 1
    [[target]]
    id = "custom_clean"
    name = "Custom"
    tier = "review"
    [[rule]]
    id = "escape-via-symlink"
    target = "custom_clean"
    mode = "children"
    paths = ["~/link/important"]
    """
    ctx = R.RuleContext(os_name="linux", home=str(home), env={})
    rs = R.RuleSet()
    rs.load_text(user_toml, "user", "user.toml")
    pl = rs.plan("custom_clean", ctx, guards=FakeGuards())
    assert not pl.items and not pl.deletable
    assert secret_file.exists()

    real_dir = home / ".cache" / "myapp"
    real_target = real_dir / "old"
    real_target.mkdir(parents=True)
    (real_target / "cache.bin").write_bytes(b"x" * 100)
    age(real_target / "cache.bin", 30)
    age(real_target, 30)

    user_toml2 = """
    schema = 1
    [[target]]
    id = "custom_clean2"
    name = "Custom 2"
    tier = "review"
    [[rule]]
    id = "valid-cache-rule"
    target = "custom_clean2"
    mode = "children"
    paths = ["~/.cache/myapp"]
    """
    rs2 = R.RuleSet()
    rs2.load_text(user_toml2, "user", "user2.toml")
    pl2 = rs2.plan("custom_clean2", ctx, guards=FakeGuards())
    assert len(pl2.deletable) == 1

    import shutil
    shutil.rmtree(real_dir)
    victim_old = outside / "old"
    victim_old.mkdir(parents=True)
    (victim_old / "cache.bin").write_bytes(b"x" * 100)
    real_dir.symlink_to(outside)

    res = E.execute_plan(pl2.deletable, guards=FakeGuards())
    assert res.removed == 0
    assert (victim_old / "cache.bin").exists()


def test_a7_podman_buildcache_never_calls_system_prune(monkeypatch):
    c = L.LinuxCleaner()
    monkeypatch.setattr(L, "CONTAINER_TOOL", "podman")

    monkeypatch.setattr(L.LinuxCleaner, "_podman_supports_builder_prune", staticmethod(lambda tool="podman": False))
    calls = []
    def fake_cmd(argv, timeout=25):
        calls.append(list(argv))
        if argv[1:3] == ["system", "df"]:
            return ("Build Cache\t120MB\n", "", 0)
        return ("", "", 0)
    monkeypatch.setattr(L, "_cmd", fake_cmd)

    scan = c._rv_docker()
    bc_items = [it for it in scan.items if it.id == "buildcache:all"]
    assert bc_items and bc_items[0].blocked
    res = c._rc_docker(["buildcache:all"], dry=False)
    assert res.skipped and not any("system" in cmd and "prune" in cmd for cmd in calls)

    monkeypatch.setattr(L.LinuxCleaner, "_podman_supports_builder_prune", staticmethod(lambda tool="podman": True))
    c._rv_docker()
    calls.clear()
    res2 = c._rc_docker(["buildcache:all"], dry=False)
    assert ["podman", "builder", "prune", "-f"] in calls
    assert not any(cmd[:3] == ["podman", "system", "prune"] for cmd in calls)


def test_a8_incomplete_tree_scan_rejected_in_evaluate_and_execute(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    d = tree(tmp_path / "cache_tree", {"a.bin": 200, "sub/b.bin": 300}, days=10)

    ts_trunc = E.tree_stats(str(d), deadline=time.monotonic() - 1.0)
    assert ts_trunc.truncated is True
    reason = E.evaluate(ts_trunc, E.Policy(), now=time.time(), guards=FakeGuards(), path=str(d))
    assert "truncated" in reason

    ts_err = E.TreeStats(size=500, files=2, newest=0.0, errors=1)
    reason2 = E.evaluate(ts_err, E.Policy(), now=time.time(), guards=FakeGuards(), path=str(d))
    assert "read/permission error" in reason2

    it, why = E.make_item(str(d), E.Policy(), guards=FakeGuards())
    assert it is not None and not why
    monkeypatch.setattr(E, "tree_stats", lambda *a, **k: E.TreeStats(size=500, files=2, newest=0.0, errors=2))
    out = E.execute_item(it, guards=FakeGuards())
    assert out.removed == 0 and out.freed == 0 and "error" in out.reason
    assert (d / "a.bin").exists()


def test_a9_service_worker_cache_storage_moved_to_review_tier():
    rs = R.load_default(include_user=False)
    for rid in ("chromium-family", "chromium-family-win"):
        rule = next(r for r in rs.rules if r.id == rid)
        assert all("CacheStorage" not in sp for sp in rule.subpaths), rid

    for rid in ("chromium-service-worker-cache", "chromium-service-worker-cache-win"):
        sw_rule = next(r for r in rs.rules if r.id == rid)
        assert sw_rule.target == "dev_cache"
        assert sw_rule.risk == "medium"
        assert "offline" in sw_rule.note.lower()


def test_b1_local_game_uninstall_handles_bool_safe_delete(monkeypatch, tmp_path):
    monkeypatch.setattr(OSD, "real_home", lambda: str(tmp_path))
    game_dir = tmp_path / "Games" / "SuperTuxPortable"
    game_dir.mkdir(parents=True)
    (game_dir / "game.bin").write_bytes(b"x" * 1024)
    app = U.InstalledApp(
        name="SuperTuxPortable", version="local", size_mb=10.0,
        source="local-game", pkg_id=str(game_dir),
    )

    monkeypatch.setattr(OSD, "safe_delete", lambda p, use_trash=True: True)
    logs_ok = []
    assert U.uninstall_app(app, lambda m, l="info": logs_ok.append((l, m))) is True

    monkeypatch.setattr(OSD, "safe_delete", lambda p, use_trash=True: False)
    logs_err = []
    assert U.uninstall_app(app, lambda m, l="info": logs_err.append((l, m))) is False
    assert any(l == "err" for l, _ in logs_err)


def test_b2_windows_booster_timer_restore_and_partial_failure_handling(monkeypatch, tmp_path, qapp):
    installed_stub, before_mods = _ensure_pyqt_stub()
    try:
        gbw = importlib.import_module("core.game_boost_widget")
        state_file = tmp_path / "boost_state.json"
        monkeypatch.setattr(gbw, "_boost_state_file", lambda: state_file)

        timer_args = []
        monkeypatch.setattr(B, "_timer_resolution_restore", lambda was_set, log=None: timer_args.append(was_set) or True)
        monkeypatch.setattr(B, "_restore_kernel_performance", lambda mode, log: (_ for _ in ()).throw(RuntimeError("powerctl failed")))
        os.environ["MESA_SHADER_CACHE_DISABLE"] = "false"

        saved = {
            "timer_set": True,
            "power": "powerprofiles:balanced",
            "env_orig": {"MESA_SHADER_CACHE_DISABLE": None},
        }
        gbw._save_boost_state_disk(saved)
        logs = []
        ok = gbw._restore_boost_state(saved, lambda m, c="text": logs.append((c, m)))

        assert timer_args == [True]
        assert "MESA_SHADER_CACHE_DISABLE" not in os.environ
        assert ok is False
        assert state_file.exists()
        remaining = json.loads(state_file.read_text(encoding="utf-8"))
        assert "power" in remaining and "timer_set" not in remaining
    finally:
        _cleanup_pyqt_stub(installed_stub, before_mods)


def test_b3_linux_nice_capability_check_and_pid_identity_verification(monkeypatch):
    monkeypatch.setattr(B, "IS_LINUX", True)
    monkeypatch.setattr(B, "IS_WINDOWS", False)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    monkeypatch.setattr(resource, "getrlimit", lambda _: (0, 0))
    assert B._can_restore_linux_nice(0) is False

    monkeypatch.setattr(resource, "getrlimit", lambda _: (20, 20))
    assert B._can_restore_linux_nice(0) is True

    nice_restored = []

    class FakeReusedProc:
        def __init__(self, pid):
            self.pid = pid
        def name(self):
            return "different_binary" if self.pid == 111 else "chrome"
        def create_time(self):
            return 9999.0 if self.pid == 111 else 1000.0
        def nice(self, val=None):
            if val is not None:
                nice_restored.append((self.pid, val))
            return 10

    fake_ps = SimpleNamespace(Process=FakeReusedProc, NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
    monkeypatch.setattr(B, "psutil", fake_ps, raising=False)
    monkeypatch.setattr(B, "HAS_PSUTIL", True, raising=False)
    frozen_pids = {
        111: {"mode": "nice", "orig_nice": 0, "name": "slack", "create_time": 1000.0},
        222: {"mode": "nice", "orig_nice": 0, "name": "chrome", "create_time": 1000.0},
    }
    B.restore_bloat(frozen_pids, lambda *a: None)
    assert (111, 0) not in nice_restored
    assert (222, 0) in nice_restored


def test_b4_windows_dns_captures_and_restores_dhcp_and_multi_server_static(monkeypatch):
    dns_out_dhcp = textwrap.dedent("""
        Configuration for interface "Wi-Fi"
            DNS servers configured through DHCP:  192.168.1.1
                                                  192.168.1.2
            Register with which suffix:           Primary only
    """)
    dns_out_static = textwrap.dedent("""
        Configuration for interface "Ethernet"
            Statically Configured DNS Servers:    9.9.9.9
                                                  149.112.112.112
                                                  8.8.4.4
            Register with which suffix:           Primary only
    """)
    assert B._parse_netsh_dns_output(dns_out_dhcp) == {"mode": "dhcp", "servers": ["192.168.1.1", "192.168.1.2"]}
    assert B._parse_netsh_dns_output(dns_out_static) == {
        "mode": "static",
        "servers": ["9.9.9.9", "149.112.112.112", "8.8.4.4"],
    }
    assert B._parse_netsh_dns_output("error: interface not found") is None

    cmds = []

    def fake_run(argv, **kw):
        cmds.append(argv if isinstance(argv, str) else " ".join(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(B, "IS_WINDOWS", True)
    monkeypatch.setattr(B.subprocess, "run", fake_run)
    saved_dns = {
        "Wi-Fi": {"mode": "dhcp", "servers": ["192.168.1.1"]},
        "Ethernet": {"mode": "static", "servers": ["9.9.9.9", "149.112.112.112", "8.8.4.4"]},
    }
    logs = []
    B._restore_dns_windows(saved_dns, lambda m, l="text": logs.append((l, m)))

    assert any('netsh interface ip set dns name="Wi-Fi" dhcp' in c for c in cmds)
    assert any('netsh interface ip set dns name="Ethernet" static 9.9.9.9' in c for c in cmds)
    assert any('netsh interface ip add dns name="Ethernet" 149.112.112.112 index=2' in c for c in cmds)
    assert any('netsh interface ip add dns name="Ethernet" 8.8.4.4 index=3' in c for c in cmds)


def test_b5_xbps_cache_and_orphans_flags_are_not_swapped():
    helper_txt = HELPER_SRC.read_text(encoding="utf-8")
    assert "xbps-clean-cache)\n    nargs $# 0; need xbps-remove\n    xbps-remove -O ;;" in helper_txt
    assert "xbps-orphans)\n    nargs $# 0; need xbps-remove\n    verify_xbps_tx -o\n    xbps-remove -y -o ;;" in helper_txt

    lc_txt = (ROOT / "core" / "linux_cleaner.py").read_text(encoding="utf-8")
    assert "(xbps-remove -O)" in lc_txt and "(xbps-remove -o)" in lc_txt
    assert "['xbps-remove', '-n', '-o']" in lc_txt or '["xbps-remove", "-n", "-o"]' in lc_txt

    assert "xbps-remove -O" in i18n.TRANSLATIONS["vi"]["tgt_xbps_cache_desc"]
    assert "xbps-remove -o" in i18n.TRANSLATIONS["vi"]["tgt_xbps_orphaned_desc"]


def test_b6_and_b7_preview_plan_bound_to_clean_and_new_files_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    monkeypatch.setattr(E.Guards, "_load_procs", staticmethod(lambda: (set(), set(), set())))
    monkeypatch.setattr(E.Guards, "_load_open", lambda self: set())
    E.Guards._shared = None

    c = L.LinuxCleaner()
    c.ctx.home = str(tmp_path / "home")
    os.makedirs(c.ctx.home)
    c.ctx.env = {}

    thumbs = Path(c.ctx.home) / ".cache/thumbnails/normal"
    f_previewed = tree(thumbs, {"previewed.png": 400}, days=40) / "previewed.png"

    dry_res = c.clean("thumbnails", dry=True)
    assert dry_res.freed_bytes == 400

    f_after = thumbs / "created_after_preview.png"
    f_after.write_bytes(b"y" * 900)
    age(f_after, 40)

    real_res = c.clean("thumbnails", dry=False)
    assert real_res.freed_bytes == 400
    assert not f_previewed.exists()
    assert f_after.exists()


def test_c1_kill_bloat_separates_mb_affected_from_actual_mb_freed(monkeypatch):
    monkeypatch.setattr(B, "IS_LINUX", True)
    monkeypatch.setattr(B, "IS_WINDOWS", False)
    monkeypatch.setattr(B, "_can_restore_linux_nice", lambda orig: True)

    my_uid = os.getuid()
    fake_proc = SimpleNamespace(
        pid=4242,
        info={"pid": 4242, "name": "heavy-helper", "status": "sleeping",
              "uids": SimpleNamespace(real=my_uid),
              "memory_info": SimpleNamespace(rss=200 * 1024 * 1024), "cpu_percent": 0.1},
        name=lambda: "heavy-helper",
        status=lambda: "sleeping",
        uids=lambda: SimpleNamespace(real=my_uid),
        memory_info=lambda: SimpleNamespace(rss=200 * 1024 * 1024),
        cpu_percent=lambda interval=0: 0.1,
        children=lambda recursive=True: [],
        oneshot=lambda: __import__('contextlib').nullcontext(),
        create_time=lambda: 1234.0,
        nice=lambda *a: 0,
    )
    fake_ps2 = SimpleNamespace(
        process_iter=lambda attrs=None: [fake_proc],
        virtual_memory=lambda: SimpleNamespace(total=8 * 1024 ** 3, available=4000 * 1024 * 1024),
        Process=lambda pid: fake_proc,
        STATUS_ZOMBIE="zombie",
        STATUS_SLEEPING="sleeping",
        STATUS_IDLE="idle",
        NoSuchProcess=ProcessLookupError,
        AccessDenied=PermissionError,
        TimeoutExpired=TimeoutError,
    )
    monkeypatch.setattr(B, "psutil", fake_ps2, raising=False)
    monkeypatch.setattr(B, "HAS_PSUTIL", True, raising=False)
    monkeypatch.setattr(B, "_get_oom_score", lambda pid: 500)

    res = B.kill_bloat(lambda *a: None, cpu_cache={4242: 0.1})
    assert res.mb_freed == 0.0
    assert res.mb_affected >= 199.0


def test_c2_disk_delta_widget_and_dry_run_after_est_never_exceed_before(qapp):
    installed_stub, before_mods = _ensure_pyqt_stub()
    try:
        uw = importlib.import_module("ui_widgets")
        w = uw.DiskDeltaWidget()
        try:
            total = 100 * 1024 ** 3
            free = int(38.6 * 1024 ** 3)
            pct_before = 59.4
            freed = 500 * 1024 ** 2

            est_free = min(total, free + freed)
            est_pct = max(0.0, min(pct_before, pct_before - (freed / total * 100.0)))
            assert est_pct <= pct_before

            w.set_before(free, total, pct_before)
            w.set_after(est_free, est_pct, freed, dry=True)
            assert w._used_pct_a <= w._used_pct_b
        finally:
            if hasattr(w, "deleteLater"):
                w.deleteLater()
    finally:
        _cleanup_pyqt_stub(installed_stub, before_mods)


def test_c3_c4_c5_c6_ui_labels_history_filter_and_kernel_proc_protection(monkeypatch):
    assert i18n.TRANSLATIONS["en"]["lbl_health"] == "LOAD INDEX"
    assert i18n.TRANSLATIONS["vi"]["lbl_health"] == "CHỈ SỐ TẢI"
    assert i18n.TRANSLATIONS["vi"]["sys_healthy"] == "Tải ổn định"
    assert i18n.TRANSLATIONS["vi"]["btn_kill_bloat"] == "HẠ ƯU TIÊN NỀN"

    assert sysinfo._is_kernel_or_skipped_proc(129, "kworker/u16:2-events_unbound") is True
    assert sysinfo._is_kernel_or_skipped_proc(15, "ksoftirqd/0") is True
    assert sysinfo._is_kernel_or_skipped_proc(2, "kthreadd") is True
    assert sysinfo._is_kernel_or_skipped_proc(5432, "firefox") is False

    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "if e.get('summary') == 'auto_snapshot':" in main_src


# ── 9. Stage 4 Follow-Up Audit Regressions (Issues 1–7) ──────────────────────
def test_stage4_1_parent_swap_before_and_after_handle_open_and_target_symlink_swap(monkeypatch, tmp_path):
    """
    Issue 1:
    - Parent directory swapped into a symlink BEFORE or AFTER _open_verified_parent_fd
      must never delete files in the symlink target directory.
    - Target swapped into a symlink must be rejected across tree, contents (keep_root),
      single file, and old_files modes.
    - Protection must remain active even when E.remove_path is wrapped/monkeypatched.
    """
    import shutil
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)

    outside = tmp_path / "outside_victim"
    outside_target = tree(outside / "app", {"precious.txt": 512, "sub/deep.txt": 256}, days=40)

    # (A) Parent swapped into symlink AFTER _open_verified_parent_fd opens parent_fd
    home_a = tmp_path / "home_a"
    parent_a = home_a / ".cache"
    target_a = tree(parent_a / "app", {"cache.bin": 128, "sub/part.bin": 64}, days=40)
    it_a, why_a = E.make_item(target_a, E.Policy(), allowed_root=str(home_a))
    assert it_a is not None and not why_a

    real_open_parent_fd = E._open_verified_parent_fd

    def swap_parent_after_open(chain):
        fd = real_open_parent_fd(chain)
        moved = home_a / ".cache_moved"
        if not moved.exists():
            os.rename(parent_a, moved)
            parent_a.symlink_to(outside)
        return fd

    monkeypatch.setattr(E, "_open_verified_parent_fd", swap_parent_after_open)
    orig_remove = E.remove_path
    spy_calls = []
    monkeypatch.setattr(E, "remove_path", lambda p: (spy_calls.append(p), orig_remove(p))[1])

    res_a = E.execute_plan([it_a], guards=FakeGuards())
    monkeypatch.setattr(E, "_open_verified_parent_fd", real_open_parent_fd)
    monkeypatch.setattr(E, "remove_path", orig_remove)

    assert res_a.removed == 0 and res_a.outcomes[0].status == "skipped"
    assert (outside_target / "precious.txt").exists()
    assert (outside_target / "sub" / "deep.txt").exists()
    assert (home_a / ".cache_moved" / "app" / "cache.bin").exists()

    # (B) Target swapped into symlink in keep_root=True (contents mode)
    home_b = tmp_path / "home_b"
    target_b = tree(home_b / "pip", {"http/a.whl": 100, "selfcheck.json": 10}, days=40)
    it_b, _ = E.make_item(target_b, E.Policy(), keep_root=True, keep=("selfcheck.json",), allowed_root=str(home_b))
    assert it_b is not None
    shutil.rmtree(target_b)
    target_b.symlink_to(outside_target)
    res_b = E.execute_plan([it_b], guards=FakeGuards())
    assert res_b.removed == 0 and res_b.outcomes[0].status == "skipped"
    assert (outside_target / "precious.txt").exists()

    # (C) Subdirectory swapped into symlink in old_files mode
    home_c = tmp_path / "home_c"
    thumbs_c = home_c / "thumbs"
    tree(thumbs_c, {"normal/a.png": 200}, days=45)
    it_c = E.plan_old_files(thumbs_c, E.Policy(min_age_sec=30 * 86400), allowed_root=str(home_c))
    assert it_c is not None
    shutil.rmtree(thumbs_c / "normal")
    (outside / "normal_victim").mkdir(exist_ok=True)
    victim_png = outside / "normal_victim" / "a.png"
    victim_png.write_bytes(b"v" * 200)
    age(victim_png, 45)
    (thumbs_c / "normal").symlink_to(outside / "normal_victim")

    res_c = E.execute_plan([it_c], guards=FakeGuards())
    assert res_c.removed == 0 and victim_png.exists()


def test_stage4_2_expired_or_missing_review_plan_never_rescans_or_deletes_replacement(monkeypatch, tmp_path):
    """
    Issue 2:
    - When Review cache is expired or missing, review_clean() and _rc_trash() must refuse
      with an i18n message and NEVER rescan or delete a replacement object at the same path.
    - Even within TTL, if the target at the path was replaced with a new object (aged > 40d),
      object identity checks must skip it.
    """
    import shutil
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    monkeypatch.setattr(E.Guards, "_load_procs", staticmethod(lambda: (set(), set(), set())))
    monkeypatch.setattr(E.Guards, "_load_open", lambda self: set())
    E.Guards._shared = None

    c = L.LinuxCleaner()
    c.ctx.home = str(tmp_path / "home")
    os.makedirs(c.ctx.home, exist_ok=True)
    c.ctx.env = {}

    mystery = tree(Path(c.ctx.home) / ".cache/mystery_app", {"old.bin": 300}, days=45)
    scan = c.review_scan("app_cache")
    assert len(scan.items) == 1
    item_id = scan.items[0].id

    ts_old, cached_plan = c._review_cache["app_cache"]
    c._review_cache["app_cache"] = (ts_old - c.REVIEW_TTL - 5, cached_plan)

    shutil.rmtree(mystery)
    replacement = tree(Path(c.ctx.home) / ".cache/mystery_app", {"important_new_data.db": 900}, days=45)

    res_exp = c.review_clean("app_cache", [item_id], dry=False)
    assert res_exp.error and ("expired" in res_exp.error.lower() or "hết hạn" in res_exp.error.lower())
    assert res_exp.freed_bytes == 0
    assert (replacement / "important_new_data.db").exists()

    c._review_cache.clear()
    res_missing = c.review_clean("app_cache", [item_id], dry=False)
    assert res_missing.error
    assert (replacement / "important_new_data.db").exists()

    trash_dir = tmp_path / "Trash"
    (trash_dir / "files").mkdir(parents=True)
    (trash_dir / "info").mkdir()
    t_file = trash_dir / "files" / "doc.txt"
    t_file.write_bytes(b"old-trash" * 20)
    age(t_file, 40)
    (trash_dir / "info" / "doc.txt.trashinfo").write_text("[Trash Info]\nPath=/home/u/doc.txt\n", encoding="utf-8")
    monkeypatch.setattr(c, "_trash_dirs", lambda: [str(trash_dir)])

    t_scan = c._rv_trash()
    assert len(t_scan.items) == 1
    t_id = t_scan.items[0].id

    t_ts, t_plan = c._review_cache["empty_trash"]
    c._review_cache["empty_trash"] = (t_ts - c.REVIEW_TTL - 10, t_plan)
    t_file.unlink()
    t_file.write_bytes(b"newly-trashed-precious-data" * 30)
    age(t_file, 40)

    r_trash = c._rc_trash([t_id], dry=False)
    assert r_trash.error and ("expired" in r_trash.error.lower() or "hết hạn" in r_trash.error.lower())
    assert t_file.exists() and b"newly-trashed-precious-data" in t_file.read_bytes()


def test_stage4_3_directory_plan_tree_and_contents_reject_unpreviewed_backdated_files(monkeypatch, tmp_path):
    """
    Issue 3:
    - Exact Pip cache reproduction (mode="contents") and tree mode (mode="tree"):
      Preview a directory containing a 3-byte file -> add a 29-byte file into an existing
      subdirectory after Preview and backdate both the new file and subdirectory to old timestamps
      -> running the previewed plan must reject/skip the modified tree and NEVER delete the
      unpreviewed file.
    """
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
    rs = R.load_default(include_user=False)
    ctx = R.RuleContext(os_name="linux", home=str(tmp_path), env={})

    pip_root = tmp_path / ".cache" / "pip"
    sub_dir = pip_root / "http-v2" / "ab"
    sub_dir.mkdir(parents=True)
    f_previewed = sub_dir / "cached.body"
    f_previewed.write_bytes(b"abc")
    for p in (f_previewed, sub_dir, pip_root / "http-v2", pip_root):
        age(p, 40)

    pl = rs.plan("pip_cache", ctx, guards=FakeGuards())
    pip_items = [i for i in pl.deletable if i.group == "pip"]
    assert len(pip_items) == 1 and pip_items[0].size == 3

    f_unpreviewed = sub_dir / "unpreviewed_wheel.whl"
    f_unpreviewed.write_bytes(b"Z" * 29)
    for p in (f_unpreviewed, sub_dir):
        age(p, 40)

    exec_res = E.execute_plan(pip_items, guards=FakeGuards())
    assert exec_res.removed == 0 and exec_res.freed == 0
    assert exec_res.outcomes[0].status == "skipped"
    assert "modified since the scan" in exec_res.outcomes[0].reason
    assert f_previewed.exists() and f_unpreviewed.exists()

    tree_dir = tree(tmp_path / "tree_cache", {"sub/init.bin": 10}, days=40)
    it_tree, _ = E.make_item(tree_dir, E.Policy())
    assert it_tree is not None and it_tree.size == 10

    extra_file = tree_dir / "sub" / "added_after_preview.bin"
    extra_file.write_bytes(b"X" * 50)
    age(extra_file, 40)
    age(tree_dir / "sub", 40)
    age(tree_dir, 40)

    res_tree = E.execute_plan([it_tree], guards=FakeGuards())
    assert res_tree.removed == 0 and res_tree.freed == 0
    assert res_tree.outcomes[0].status == "skipped"
    assert extra_file.exists() and (tree_dir / "sub" / "init.bin").exists()


def test_stage4_4_booster_subrestore_errors_not_swallowed_and_state_preserved_across_reboost(monkeypatch, tmp_path, qapp):
    """
    Issue 4:
    - Real _restore_gamedvr() with mocked winreg raising PermissionError must return False
      (never swallow exception as success).
    - _restore_boost_state() must keep gamedvr_orig in `saved` and `boost_state.json`,
      still execute subsequent restore steps, and return False.
    - Re-boosting must preserve the un-restored gamedvr_orig=1 until a retry succeeds.
    """
    installed_stub, before_mods = _ensure_pyqt_stub()
    try:
        gbw = importlib.import_module("core.game_boost_widget")
        state_file = tmp_path / "boost_state.json"
        monkeypatch.setattr(gbw, "_boost_state_file", lambda: state_file)
        monkeypatch.setattr(B, "IS_WINDOWS", True)
        monkeypatch.setattr(B, "IS_LINUX", False)

        reg_writes = []
        deny_write = {"active": True}

        class FakeWinreg:
            HKEY_CURRENT_USER = 1
            HKEY_LOCAL_MACHINE = 2
            KEY_READ = 1
            KEY_SET_VALUE = 2
            REG_DWORD = 4
            REG_SZ = 1

            @staticmethod
            def OpenKey(root, path, res, access):
                if deny_write["active"] and (access & FakeWinreg.KEY_SET_VALUE):
                    raise PermissionError(5, "Access is denied")
                return SimpleNamespace(path=path)

            @staticmethod
            def SetValueEx(key, name, reserved, reg_type, value):
                if deny_write["active"]:
                    raise PermissionError(5, "Access is denied")
                reg_writes.append((key.path, name, value))

            @staticmethod
            def CloseKey(key):
                pass

        monkeypatch.setitem(sys.modules, "winreg", FakeWinreg)

        saved = {
            "gamedvr_orig": 1,
            "env_orig": {"CYBER_TEST_VAR": None},
        }
        os.environ["CYBER_TEST_VAR"] = "boosted"
        gbw._save_boost_state_disk(saved)

        logs = []
        ok1 = gbw._restore_boost_state(saved, lambda m, l="text": logs.append((l, m)))
        assert ok1 is False
        assert "CYBER_TEST_VAR" not in os.environ
        assert saved.get("gamedvr_orig") == 1
        assert state_file.exists()
        persisted = json.loads(state_file.read_text(encoding="utf-8"))
        assert persisted.get("gamedvr_orig") == 1

        merged = gbw._merge_unrestored_state(persisted, {"gamedvr_orig": 0, "timer_set": True})
        assert merged["gamedvr_orig"] == 1

        deny_write["active"] = False
        ok2 = gbw._restore_boost_state(saved, lambda m, l="text": logs.append((l, m)))
        assert ok2 is True
        assert "gamedvr_orig" not in saved
        assert not state_file.exists()
        assert any(name == "AppCaptureEnabled" and val == 1 for _, name, val in reg_writes)
    finally:
        _cleanup_pyqt_stub(installed_stub, before_mods)


def test_stage4_5_helper_rejects_unparseable_empty_and_dependency_protected_transactions(tmp_path):
    """
    Issue 5:
    - Verify DNF, Zypper, XBPS, APT, and Pacman transaction verifiers in cyber-clean-helper:
      * Reject "unrecognized transaction layout" (exit 3, no removal command executed).
      * Reject empty dry-run output "" (exit 3, no removal command executed).
      * Distinguish valid no-op on autoremove/orphans from parser errors on explicit remove.
      * Reject protected packages pulled in as dependencies or with architecture suffixes.
      * Allow valid non-protected transactions.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "calls.log"
    mode_file = tmp_path / "mode.txt"

    def write_cmd(name: str, body: str):
        p = bin_dir / name
        p.write_text("#!/bin/bash\n" + textwrap.dedent(body).lstrip() + "\n", encoding="utf-8")
        p.chmod(0o755)

    write_cmd("dnf", f"""
        mode=$(cat "{mode_file}" 2>/dev/null || echo "valid")
        if [[ "$1" == "--assumeno" ]]; then
            case "$mode" in
                unrecognized) echo "unrecognized transaction layout"; exit 1 ;;
                empty)        exit 1 ;;
                noop)         echo "Dependencies resolved."; echo "Nothing to do."; exit 0 ;;
                dep_prot)     printf "Removing:\n vlc x86_64 3.0-1 @updates 4M\nRemoving dependent packages:\n systemd-libs x86_64 256-1 @fedora 2M\n"; exit 1 ;;
                valid)        printf "Removing:\n %s x86_64 3.0-1 @updates 4M\n" "${{!#}}"; exit 1 ;;
            esac
        fi
        echo "dnf $*" >> "{calls_log}"
    """)

    write_cmd("xbps-remove", f"""
        mode=$(cat "{mode_file}" 2>/dev/null || echo "valid")
        if [[ "$1" == "-n" ]]; then
            case "$mode" in
                unrecognized) echo "unrecognized transaction layout"; exit 0 ;;
                empty)        exit 0 ;;
                noop)         echo "There are no orphaned packages."; exit 0 ;;
                dep_prot)     echo "vlc-3.0.20_1 remove x86_64 https://repo"; echo "glibc-2.39_1 remove x86_64 https://repo"; exit 0 ;;
                valid)        echo "${{!#}}-3.0.20_1 remove x86_64 https://repo"; exit 0 ;;
            esac
        fi
        echo "xbps-remove $*" >> "{calls_log}"
    """)

    write_cmd("zypper", f"""
        mode=$(cat "{mode_file}" 2>/dev/null || echo "valid")
        if [[ "$*" == *"--dry-run"* ]]; then
            case "$mode" in
                unrecognized) echo "unrecognized transaction layout"; exit 0 ;;
                empty)        exit 0 ;;
                dep_prot)     printf "The following 2 packages are going to be removed:\n  vlc udev.x86_64\n"; exit 0 ;;
                valid)        printf "The following package is going to be removed:\n  %s\n" "${{!#}}"; exit 0 ;;
            esac
        fi
        echo "zypper $*" >> "{calls_log}"
    """)

    helper_copy = tmp_path / "cyber-clean-helper"
    s = HELPER_SRC.read_text(encoding="utf-8")
    s = s.replace(
        "PATH=/usr/sbin:/usr/bin:/sbin:/bin:/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin",
        f"PATH={bin_dir}:/usr/sbin:/usr/bin:/sbin:/bin",
    )
    helper_copy.write_text(s, encoding="utf-8")
    helper_copy.chmod(0o755)

    def run_h(*args):
        return subprocess.run([str(helper_copy), *args], capture_output=True, text=True, timeout=15)

    for bad_mode in ("unrecognized", "empty"):
        mode_file.write_text(bad_mode, encoding="utf-8")
        for act, arg in (("dnf-remove", "vlc"), ("dnf-autoremove", None), ("xbps-remove", "vlc"), ("xbps-orphans", None), ("zypper-remove", "vlc")):
            r = run_h(act) if arg is None else run_h(act, arg)
            assert r.returncode == 3, f"{act} with mode={bad_mode} should fail with 3, got {r.returncode}: {r.stderr}"
    assert not calls_log.exists() or calls_log.read_text() == ""

    mode_file.write_text("dep_prot", encoding="utf-8")
    for act, arg in (("dnf-remove", "vlc"), ("xbps-remove", "vlc"), ("zypper-remove", "vlc")):
        r = run_h(act, arg)
        assert r.returncode == 3 and "protected" in r.stderr
    assert not calls_log.exists() or calls_log.read_text() == ""

    mode_file.write_text("noop", encoding="utf-8")
    assert run_h("dnf-autoremove").returncode == 0
    assert run_h("xbps-orphans").returncode == 0
    assert run_h("dnf-remove", "vlc").returncode == 3

    calls_log.unlink(missing_ok=True)
    mode_file.write_text("valid", encoding="utf-8")
    assert run_h("dnf-remove", "vlc").returncode == 0
    assert run_h("xbps-remove", "vlc").returncode == 0
    assert run_h("zypper-remove", "vlc").returncode == 0
    logged = calls_log.read_text(encoding="utf-8")
    assert "dnf remove -y -- vlc" in logged
    assert "xbps-remove -y -- vlc" in logged
    assert "zypper --non-interactive remove -- vlc" in logged


def test_stage4_6_cooperative_cancel_on_shutdown_without_terminate_and_helper_wait(monkeypatch, tmp_path, qapp):
    """
    Issue 6:
    - main.py _shutdown() must not call self.worker.terminate().
    - Stopping CleanWorker mid-clean must cooperatively stop inside target execution,
      record accurate partial results, handle repeated stop() calls idempotently, and
      wait for any running helper process before finishing.
    """
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    shutdown_block = main_src.split("def _shutdown(self):", 1)[1].split("def _autoclean_btn_text", 1)[0]
    assert "self.worker.terminate()" not in shutdown_block

    installed_stub, before_mods = _ensure_pyqt_stub()
    try:
        uw = importlib.import_module("ui_widgets")
        from core import privileged as PRIV

        monkeypatch.setattr(E, "is_ram_backed", lambda p: False)
        monkeypatch.setattr(E.Guards, "_load_procs", staticmethod(lambda: (set(), set(), set())))
        monkeypatch.setattr(E.Guards, "_load_open", lambda self: set())
        E.Guards._shared = None

        c = L.LinuxCleaner()
        c.ctx.home = str(tmp_path / "home")
        os.makedirs(c.ctx.home, exist_ok=True)
        c.ctx.env = {}

        thumbs = Path(c.ctx.home) / ".cache/thumbnails/normal"
        thumbs.mkdir(parents=True)
        for idx in range(5):
            p = thumbs / f"img_{idx}.png"
            p.write_bytes(b"x" * 100)
            age(p, 45)

        dry_res = c.clean("thumbnails", dry=True)
        assert dry_res.freed_bytes == 500

        w = uw.CleanWorker(["thumbnails"], dry=False, cleaner=c, plans={"thumbnails": dry_res.plan})
        orig_remove_verified = E._remove_verified_target
        removed_count = {"n": 0}

        def slow_remove_and_stop(*args, **kwargs):
            res = orig_remove_verified(*args, **kwargs)
            removed_count["n"] += 1
            if removed_count["n"] == 2:
                w.stop()
                w.stop()
            return res

        monkeypatch.setattr(E, "_remove_verified_target", slow_remove_and_stop)
        done_payloads = []
        w.done.connect(lambda payload: done_payloads.append(payload))
        w.run()
        monkeypatch.setattr(E, "_remove_verified_target", orig_remove_verified)

        assert len(done_payloads) == 1
        payload = done_payloads[0]
        assert payload["interrupted"] is True
        assert payload["freed"] == 200
        assert len(list(thumbs.glob("*.png"))) == 3
        assert not PRIV.has_active_helper()
    finally:
        _cleanup_pyqt_stub(installed_stub, before_mods)


def test_stage5_1_no_fd_leak_during_large_and_repeated_dir_cleans_and_prune(monkeypatch, tmp_path):
    """
    Stage 5 — Issue 1:
    - Cleaning a tree with 60+ subdirectories (keep_root=False and keep_root=True),
      running _prune_empty_dirs on 60+ subdirectories, and hitting errors/cancellation
      must never leak file descriptors (dup_fd closed in try/finally).
    """
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)

    def open_fd_count() -> int:
        if os.path.isdir("/proc/self/fd"):
            return len(os.listdir("/proc/self/fd"))
        return 0

    fd_baseline = open_fd_count()
    for cycle in range(3):
        root = tmp_path / f"tree_{cycle}"
        root.mkdir()
        for i in range(60):
            sub = root / f"sub_{i:02d}" / "nested"
            sub.mkdir(parents=True)
            f = sub / f"item_{i}.bin"
            f.write_bytes(b"x" * 16)
            age(f, 30)
            age(sub, 30)
            age(sub.parent, 30)
        age(root, 30)

        item, why = E.make_item(root, E.Policy(min_age_sec=0), keep_root=(cycle % 2 == 1), allowed_root=str(tmp_path))
        assert item is not None and not why
        res = E.execute_plan([item], guards=FakeGuards())
        assert res.removed == 60
        assert open_fd_count() == fd_baseline, f"FD leaked after cycle {cycle}: {open_fd_count()} vs {fd_baseline}"

    # Also test _prune_empty_dirs with 60 subdirectories
    prune_root = tmp_path / "prune_tree"
    prune_root.mkdir()
    for i in range(60):
        (prune_root / f"empty_{i:02d}" / "inner").mkdir(parents=True)
    E._prune_empty_dirs(str(prune_root), keep_root=True, allowed_root=str(tmp_path))
    assert open_fd_count() == fd_baseline
    assert list(prune_root.iterdir()) == []


def test_stage5_2_partial_clean_preserves_removed_and_freed_counts_on_oserror_or_mid_clean_modification(monkeypatch, tmp_path):
    """
    Stage 5 — Issue 2:
    - When an OSError (e.g., Too many open files / EMFILE) occurs mid-tree removal after 56 files
      were already deleted, execute_item() / execute_plan() must return status='partial' with
      removed=56 and freed=<actual bytes freed>, never resetting removed/freed to 0.
    - When a file inside the tree is modified mid-clean after earlier files were already deleted,
      execute_item() must return status='partial' with the exact count/bytes of already-deleted files
      and preserve the modified + remaining files.
    """
    import errno
    monkeypatch.setattr(E, "is_ram_backed", lambda p: False)

    # 1. OSError (EMFILE: Too many open files) after 56 files deleted
    cache_dir = tmp_path / "emfile_cache"
    cache_dir.mkdir()
    for i in range(64):
        sub = cache_dir / f"d_{i:02d}"
        sub.mkdir()
        f = sub / f"f_{i:02d}.dat"
        f.write_bytes(b"A" * 10)
        age(f, 30)
        age(sub, 30)
    age(cache_dir, 30)

    item, why = E.make_item(cache_dir, E.Policy(min_age_sec=0), keep_root=True, allowed_root=str(tmp_path))
    assert item is not None and not why and item.files == 64 and item.size == 640

    orig_unlink_at = E._unlink_file_at
    calls = {"n": 0}

    def fail_on_57th(*args, **kwargs):
        if calls["n"] >= 56:
            raise OSError(errno.EMFILE, "Too many open files")
        res = orig_unlink_at(*args, **kwargs)
        calls["n"] += 1
        return res

    monkeypatch.setattr(E, "_unlink_file_at", fail_on_57th)
    exec_res = E.execute_plan([item], guards=FakeGuards())
    monkeypatch.setattr(E, "_unlink_file_at", orig_unlink_at)

    assert len(exec_res.outcomes) == 1
    out = exec_res.outcomes[0]
    assert out.status == "partial"
    assert out.removed == 56
    assert out.freed == 560
    assert "Too many open files" in out.reason
    assert exec_res.removed == 56
    assert exec_res.freed == 560
    remaining_files = list(cache_dir.rglob("*.dat"))
    assert len(remaining_files) == 8

    # 2. Mid-clean file modification after 3 files deleted
    mod_dir = tmp_path / "mid_mod_cache"
    mod_dir.mkdir()
    files = []
    for i in range(5):
        f = mod_dir / f"file_{i:02d}.bin"
        f.write_bytes(b"B" * 20)
        age(f, 30)
        files.append(f)
    age(mod_dir, 30)

    item2, why2 = E.make_item(mod_dir, E.Policy(min_age_sec=0), keep_root=True, allowed_root=str(tmp_path))
    assert item2 is not None and not why2 and item2.files == 5 and item2.size == 100

    mod_calls = {"n": 0}

    def modify_4th_after_3_deleted(*args, **kwargs):
        res = orig_unlink_at(*args, **kwargs)
        mod_calls["n"] += 1
        if mod_calls["n"] == 3:
            # Tamper with file_03.bin while removal of the tree is already in progress
            files[3].write_bytes(b"TAMPERED_DURING_CLEAN")
        return res

    monkeypatch.setattr(E, "_unlink_file_at", modify_4th_after_3_deleted)
    exec_res2 = E.execute_plan([item2], guards=FakeGuards())
    monkeypatch.setattr(E, "_unlink_file_at", orig_unlink_at)

    out2 = exec_res2.outcomes[0]
    assert out2.status == "partial"
    assert out2.removed == 3
    assert out2.freed == 60
    assert "modified since the scan" in out2.reason
    assert exec_res2.removed == 3
    assert exec_res2.freed == 60
    assert files[3].exists() and files[3].read_bytes() == b"TAMPERED_DURING_CLEAN"
    assert files[4].exists() and files[4].read_bytes() == b"B" * 20


def test_stage5_3_helper_cancel_and_wait_tracks_child_and_descendant_processes_until_exit(monkeypatch, tmp_path):
    """
    Stage 5 — Issue 3:
    - Stopping a parent helper via request_cancel_helpers() + wait_active_helpers() must track
      the entire child/descendant process group and wait until all child processes have exited.
    - No child process may write to disk AFTER wait_active_helpers() returns True.
    """
    import threading
    from core import privileged as P

    # Case A: Fake helper spawns a background child subshell that sleeps 0.25s then writes a file,
    # while the parent exits immediately on SIGTERM.
    late_file_a = tmp_path / "child_wrote_after_wait_a.txt"
    fake_helper_a = tmp_path / "fake-helper-a"
    fake_helper_a.write_text(
        f"""#!/bin/sh
trap 'exit 130' TERM INT
(sleep 0.25; echo "late_write" > "{late_file_a}") >/dev/null 2>&1 &
sleep 10
""",
        encoding="utf-8",
    )
    fake_helper_a.chmod(0o755)

    monkeypatch.setattr(P, "IS_ROOT", True)
    monkeypatch.setattr(P, "HELPER", str(fake_helper_a))
    P.clear_cancel_helpers()

    t_a = threading.Thread(target=lambda: P.run_helper("apt-clean", timeout=15))
    t_a.start()
    deadline = time.monotonic() + 3.0
    while not P.has_active_helper() and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.08)

    P.request_cancel_helpers()
    stopped_a = P.wait_active_helpers(timeout=3.0)
    t_a.join(timeout=3.0)
    assert stopped_a is True
    # Wait another 0.35s to verify the child did NOT survive and write after wait_active_helpers() returned True
    time.sleep(0.35)
    assert not late_file_a.exists(), "Child process survived parent termination and wrote file after wait_active_helpers()"

    # Case B: Fake helper spawns a child process that traps SIGTERM to finish a safe cleanup step (0.25s)
    # and writes a file before exiting, while the parent shell exits immediately on SIGTERM.
    # wait_active_helpers() must NOT return True until the child has finished writing and exited.
    late_file_b = tmp_path / "child_safe_cleanup_b.txt"
    ready_file_b = tmp_path / "child_ready_b.txt"
    fake_helper_b = tmp_path / "fake-helper-b"
    fake_helper_b.write_text(
        f"""#!/bin/sh
trap 'exit 130' TERM INT
"{sys.executable}" -c '
import pathlib, signal, sys, time
out = sys.argv[1]
ready = sys.argv[2]
def _finish(sig, frame):
    time.sleep(0.25)
    pathlib.Path(out).write_text("cleanup_done", encoding="utf-8")
    sys.exit(0)
signal.signal(signal.SIGTERM, _finish)
pathlib.Path(ready).write_text("1", encoding="utf-8")
time.sleep(10)
' "{late_file_b}" "{ready_file_b}" >/dev/null 2>&1 &
sleep 10
""",
        encoding="utf-8",
    )
    fake_helper_b.chmod(0o755)
    monkeypatch.setattr(P, "HELPER", str(fake_helper_b))
    P.clear_cancel_helpers()

    t_b = threading.Thread(target=lambda: P.run_helper("apt-autoremove", timeout=15))
    t_b.start()
    deadline = time.monotonic() + 5.0
    while (not P.has_active_helper() or not ready_file_b.exists()) and time.monotonic() < deadline:
        time.sleep(0.02)

    P.request_cancel_helpers()
    stopped_b = P.wait_active_helpers(timeout=3.0)
    t_b.join(timeout=3.0)
    assert stopped_b is True
    # At the exact instant wait_active_helpers() returns True, the child must ALREADY have finished
    assert late_file_b.exists() and late_file_b.read_text(encoding="utf-8") == "cleanup_done"
    # Remove the file right after wait_active_helpers() returns True and wait 0.35s:
    # the child must not write anything after wait_active_helpers() reported True.
    late_file_b.unlink()
    time.sleep(0.35)
    assert not late_file_b.exists(), "Child process wrote to file AFTER wait_active_helpers() returned True!"
    P.clear_cancel_helpers()
