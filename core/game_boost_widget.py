"""
core/game_boost_widget.py — CyberClean Game Boost UI
══════════════════════════════════════════════════════
1 nút orbit tròn, 4 giai đoạn, neon cyber.
Dùng đúng design tokens C/MONO từ ui_widgets.py.

Tích hợp: xem patch_booster_page.py
"""
import os, time, threading, platform, shutil, subprocess
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGridLayout, QScrollBar,
)
from PyQt6.QtCore  import Qt, QTimer, QThread, pyqtSignal, QRectF
from PyQt6.QtGui   import (
    QPainter, QColor, QPen, QBrush, QFont,
    QTextCursor, QTextCharFormat, QPainterPath,
)
from PyQt6.QtWidgets import QTextEdit

IS_LINUX   = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"

# ── Dùng design tokens từ ui_widgets ─────────────────────────
try:
    from ui_widgets import C, MONO
except ImportError:
    C = {
        'bg': '#050a0f', 'bg2': '#09121a', 'bg3': '#0d1a26', 'bg4': '#112032',
        'cyan': '#00e5ff', 'cyan2': '#00bcd4', 'cyan_dim': '#004d5c',
        'red': '#ff3d5a', 'red_dim': '#3d0010',
        'yellow': '#ffd740', 'yel_dim': '#3d2d00',
        'green': '#00e676', 'grn_dim': '#00280f',
        'purple': '#d050ff',
        'text': '#def0f8', 'text2': '#7eb8cc', 'text3': '#3d6678',
        'dim': '#2a4a5a', 'border': '#0a1e2d', 'border2': '#0f2a3d', 'border3': '#1a3a52',
    }
    MONO = "'JetBrains Mono','Fira Code','Consolas',monospace"


# ══════════════════════════════════════════════════════════════
# OrbitButton — nút tròn pulsing khi active
# ══════════════════════════════════════════════════════════════
class OrbitButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active   = False
        self._phase    = 0.0
        self._dir      = 1
        self._timer    = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(170, 170)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet("background:transparent;border:none;")

    def set_active(self, v: bool):
        self._active = v
        if v:
            self._timer.start(25)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def _tick(self):
        self._phase += self._dir * 0.025
        if self._phase >= 1.0:   self._dir = -1
        elif self._phase <= 0.0: self._dir =  1
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy   = self.width() // 2, self.height() // 2
        cyan     = QColor(C['cyan'])
        dim      = QColor(C['dim'])
        border2  = QColor(C['border2'])

        if self._active:
            # Outer glow ring
            a_outer = int(15 + self._phase * 25)
            rc = QColor(C['cyan']); rc.setAlpha(a_outer)
            p.setPen(QPen(rc, 1.0)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cx-92, cy-92, 184, 184)

            # Mid ring
            a_mid = int(55 + self._phase * 100)
            mc = QColor(C['cyan']); mc.setAlpha(a_mid)
            p.setPen(QPen(mc, 1.5))
            p.drawEllipse(cx-74, cy-74, 148, 148)

            # Inner fill
            fill = QColor(C['cyan']); fill.setAlpha(10)
            p.setBrush(QBrush(fill))
            p.setPen(QPen(QColor(C['cyan']), 1.5))
            p.drawEllipse(cx-52, cy-52, 104, 104)

            # Bolt icon
            self._bolt(p, cx, cy, 17, QColor(C['cyan']))

            # "ACTIVE" label
            p.setFont(QFont("JetBrains Mono", 7))
            p.setPen(QColor(C['cyan']))
            p.drawText(QRectF(cx-35, cy+30, 70, 14),
                       Qt.AlignmentFlag.AlignCenter, "ACTIVE")
        else:
            # Idle rings
            p.setPen(QPen(border2, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cx-66, cy-66, 132, 132)
            c2 = QColor(C['border']); c2.setAlpha(80)
            p.setPen(QPen(c2, 1))
            p.drawEllipse(cx-82, cy-82, 164, 164)
            # Button circle
            p.setPen(QPen(QColor(C['border2']), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cx-48, cy-48, 96, 96)
            # Dim bolt
            self._bolt(p, cx, cy, 17, QColor(C['text3']))
            # "BOOST" label
            p.setFont(QFont("JetBrains Mono", 7))
            p.setPen(QColor(C['dim']))
            p.drawText(QRectF(cx-35, cy+30, 70, 14),
                       Qt.AlignmentFlag.AlignCenter, "BOOST")

        # Corner tags
        tag_col = QColor(C['cyan']) if self._active else QColor(C['border3'])
        p.setFont(QFont("JetBrains Mono", 7))
        p.setPen(tag_col)
        p.drawText(QRectF(cx-14, cy-80, 28, 12), Qt.AlignmentFlag.AlignCenter, "GPU")
        p.drawText(QRectF(cx+62, cy-6,  28, 12), Qt.AlignmentFlag.AlignCenter, "CPU")
        p.drawText(QRectF(cx-14, cy+68, 28, 12), Qt.AlignmentFlag.AlignCenter, "RAM")
        p.drawText(QRectF(cx-90, cy-6,  28, 12), Qt.AlignmentFlag.AlignCenter, "NET")

    def _bolt(self, p, cx, cy, s, color):
        path = QPainterPath()
        path.moveTo(cx+4,  cy-s)
        path.lineTo(cx-2,  cy-2)
        path.lineTo(cx+6,  cy-2)
        path.lineTo(cx-4,  cy+s)
        path.lineTo(cx+2,  cy+2)
        path.lineTo(cx-6,  cy+2)
        path.closeSubpath()
        p.fillPath(path, QBrush(color))


# ══════════════════════════════════════════════════════════════
# MetricCard
# ══════════════════════════════════════════════════════════════
class MetricCard(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._bar_max = 200
        self._apply_style(False)
        self.setMinimumHeight(58)
        self.setMaximumHeight(72)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(3)

        self._lbl = QLabel(label.upper())
        self._lbl.setStyleSheet(
            f"color:{C['text3']};font-size:8px;letter-spacing:2px;"
            f"font-family:{MONO};border:none;background:transparent;"
        )
        self._val   = QLabel("—")
        self._val.setStyleSheet(
            f"color:{C['text']};font-size:15px;font-weight:500;"
            f"font-family:{MONO};border:none;background:transparent;"
        )
        self._delta = QLabel("")
        self._delta.setStyleSheet(
            f"color:{C['cyan']};font-size:10px;font-family:{MONO};"
            "border:none;background:transparent;"
        )
        row = QHBoxLayout(); row.setSpacing(6); row.setContentsMargins(0,0,0,0)
        row.addWidget(self._val); row.addWidget(self._delta); row.addStretch()

        # Mini bar
        self._bar_bg   = QFrame(self)
        self._bar_bg.setFixedHeight(2)
        self._bar_bg.setStyleSheet(
            f"background:{C['border2']};border:none;border-radius:1px;"
        )
        self._bar_fill = QFrame(self._bar_bg)
        self._bar_fill.setFixedHeight(2)
        self._bar_fill.setStyleSheet(
            f"background:{C['cyan']};border:none;border-radius:1px;"
        )
        self._bar_fill.setFixedWidth(0)

        lay.addWidget(self._lbl)
        lay.addLayout(row)
        lay.addWidget(self._bar_bg)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bar_bg.setFixedWidth(self.width() - 24)
        self._bar_max = max(1, self.width() - 24)

    def _apply_style(self, lit: bool):
        border = C['border3'] if lit else C['border2']
        self.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border:1px solid {border};"
            f"border-radius:8px;}}"
        )

    def set_value(self, val: str, delta: str = "",
                  pct: float = 0, delta_color: str = None):
        self._val.setText(val)
        self._delta.setText(delta)
        col = delta_color or C['cyan']
        self._delta.setStyleSheet(
            f"color:{col};font-size:10px;font-family:{MONO};"
            "border:none;background:transparent;"
        )
        w = int(self._bar_max * min(1.0, max(0.0, pct / 100)))
        self._bar_fill.setFixedWidth(w)
        self._bar_fill.setStyleSheet(
            f"background:{col};border:none;border-radius:1px;"
        )

    def set_lit(self, lit: bool):
        self._apply_style(lit)


# ══════════════════════════════════════════════════════════════
# PhaseBar
# ══════════════════════════════════════════════════════════════
class PhaseBar(QWidget):
    LABELS = ["SCAN", "APPLY", "MONITOR"]

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        self._pills = []
        for i, name in enumerate(self.LABELS):
            pill = QLabel(name)
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setFixedHeight(20)
            pill.setStyleSheet(self._style(False, False))
            self._pills.append(pill)
            lay.addWidget(pill)
            if i < len(self.LABELS)-1:
                sep = QLabel("·")
                sep.setStyleSheet(
                    f"color:{C['border3']};font-size:8px;border:none;"
                )
                lay.addWidget(sep)
        lay.addStretch()

    def _style(self, active: bool, done: bool) -> str:
        if active:
            return (f"color:{C['yellow']};font-size:8px;letter-spacing:2px;"
                    f"font-family:{MONO};border:1px solid {C['yellow']}40;"
                    f"border-radius:10px;padding:0 10px;"
                    f"background:{C['yel_dim']};")
        if done:
            return (f"color:{C['dim']};font-size:8px;letter-spacing:2px;"
                    f"font-family:{MONO};border:1px solid {C['border2']};"
                    f"border-radius:10px;padding:0 10px;background:transparent;")
        return (f"color:{C['border3']};font-size:8px;letter-spacing:2px;"
                f"font-family:{MONO};border:1px solid {C['border']};"
                f"border-radius:10px;padding:0 10px;background:transparent;")

    def set_phase(self, n: int):
        for i, pill in enumerate(self._pills):
            pill.setStyleSheet(
                self._style(i == n, i < n)
            )


# ══════════════════════════════════════════════════════════════
# CyberLog
# ══════════════════════════════════════════════════════════════
class CyberLog(QTextEdit):
    MAX_LINES = 300
    COLORS = {
        "ok":   "#00e676",
        "warn": "#ffd740",
        "head": "#00e5ff",
        "err":  "#ff3d5a",
        "text": "#def0f8",
        "mute": "#3d6678",
    }
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMinimumHeight(120)
        self.setMaximumHeight(200)
        self.setStyleSheet(f"""
            QTextEdit {{
                background:{C['bg2']};
                border:1px solid {C['border2']};
                border-radius:8px;
                color:{C['text']};
                font-family:{MONO};
                font-size:10px;
                padding:8px 10px;
            }}
            QScrollBar:vertical {{
                background:{C['bg']};width:4px;border-radius:2px;
            }}
            QScrollBar::handle:vertical {{
                background:{C['border3']};border-radius:2px;
            }}
        """)

    def append_line(self, msg: str, level: str = "text"):
        if self.document().blockCount() > self.MAX_LINES:
            cur = self.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.Start)
            for _ in range(50):
                cur.select(QTextCursor.SelectionType.BlockUnderCursor)
                cur.removeSelectedText()
                try: cur.deleteChar()
                except Exception: break
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.COLORS.get(level, C['text'])))
        cur.setCharFormat(fmt)
        cur.insertText(msg + "\n")
        self.setTextCursor(cur)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ══════════════════════════════════════════════════════════════
# GPU Monitor Thread
# ══════════════════════════════════════════════════════════════
class GpuMonitorThread(QThread):
    update = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._stop = threading.Event()

    def stop(self): self._stop.set()

    def run(self):
        while not self._stop.wait(4.0):
            self.update.emit(self._read())

    def _read(self) -> int:
        if IS_LINUX:
            # Method 1: sysfs gpu_busy_percent (Intel Gen9+, AMD)
            for p in sorted(Path("/sys/class/drm").glob(
                    "card*/device/gpu_busy_percent")):
                try: return int(p.read_text().strip())
                except: pass

            # Method 2: Intel RC6 residency (Skylake/Broadwell iGPU)
            # RC6 = render C6 sleep state — khi GPU bận thì RC6 giảm
            # Đọc rc6_residency_ms delta để tính % busy
            for p in sorted(Path("/sys/class/drm").glob(
                    "card*/gt/gt0/rc6_residency_ms")):
                try:
                    import time as _t
                    v1 = int(p.read_text().strip())
                    _t.sleep(0.5)
                    v2 = int(p.read_text().strip())
                    # RC6 tăng ít = GPU bận nhiều
                    delta_rc6 = v2 - v1  # ms trong 500ms
                    busy_pct  = max(0, min(100, 100 - int(delta_rc6 / 5)))
                    return busy_pct
                except: pass

            # Method 3: CPU iowait + user% làm proxy khi không có GPU metric
            # Khi game chạy, CPU user% tăng = game đang dùng CPU nhiều hơn
            try:
                import psutil as _psu
                cpu = _psu.cpu_percent(interval=0.3)
                return int(min(100, cpu))
            except ImportError: pass

        if IS_WINDOWS:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine"
                     " | Measure-Object -Property UtilizationPercentage -Sum).Sum"],
                    capture_output=True, text=True, timeout=3,
                    creationflags=0x08000000)  # CREATE_NO_WINDOW — tránh nháy cửa sổ PowerShell mỗi 4s
                if r.returncode == 0:
                    return int(float(r.stdout.strip() or 0))
            except: pass
        return -1


# ══════════════════════════════════════════════════════════════
# Game Watcher Thread — detect game AFTER boost is active
# ══════════════════════════════════════════════════════════════
class GameWatcherThread(QThread):
    """
    Poll mỗi 4s sau khi boost active.
    Khi game thật (kể cả Roblox/Sober qua bwrap, hoặc bất kỳ game không
    có tên trong danh sách cứng) spawn → apply nice(-10) ngay lập tức.
    Giải quyết vấn đề: boost bật trước game → game_pids rỗng lúc SCAN.

    Từ v3.0: _detect_running_games() không còn báo "game" mỗi khi có
    process bwrap/wine/proton mới xuất hiện (trước đây mọi Flatpak app
    khác cũng bị tính nhầm thành "game detected" dù không liên quan).
    Watcher giờ chỉ emit khi có process NẶNG THẬT (CPU > threshold)
    được tìm thấy bên trong sandbox/wrapper, hoặc khi một game có tên
    đã biết khởi chạy.

    Từ v3.2: watcher trước đây chỉ theo dõi một chiều — phát hiện PID
    MỚI xuất hiện, nhưng không bao giờ kiểm tra PID CŨ đã chết hay
    chưa. Hậu quả thật (phát hiện qua test thủ công): khi tắt game
    (Ctrl+C một tiến trình test, hoặc đóng game thật), self._known vẫn
    giữ PID cũ mãi mãi, và không có cách nào để UI biết "game đã dừng"
    để chuyển trạng thái về tăng tốc máy tính thông thường. Giờ mỗi
    vòng poll còn kiểm tra xem các PID đang theo dõi có còn sống không
    (psutil.pid_exists) — nếu toàn bộ PID của một lượt detect đã chết,
    phát signal game_lost để UI cập nhật lại đúng trạng thái.
    """
    game_found = pyqtSignal(list, str)   # (pids, game_name)
    game_lost  = pyqtSignal()            # tất cả PID đã theo dõi đều đã chết
    log_sig    = pyqtSignal(str, str)

    def __init__(self, saved: dict):
        super().__init__()
        self._saved  = saved
        self._stop   = threading.Event()
        self._known  = set(saved.get("game_pids") or [])
        self._had_game = bool(self._known)

    def stop(self): self._stop.set()

    def run(self):
        import psutil as _psu
        while not self._stop.wait(4.0):
            try:
                from core.booster import _detect_running_games
                running, _ = _detect_running_games()

                # ── Kiểm tra PID cũ còn sống không (chiều "game dừng") ──
                if self._known:
                    alive = {pid for pid in self._known if _psu.pid_exists(pid)}
                    if not alive and self._had_game:
                        # Mọi PID đã theo dõi đều đã chết — game đã dừng
                        self._known = set()
                        self._had_game = False
                        self.game_lost.emit()
                    else:
                        self._known = alive

                if not running:
                    continue
                # Build full tree
                seen, pids = set(), []
                for pid, name in running:
                    if pid in seen: continue
                    seen.add(pid); pids.append(pid)
                    try:
                        for c in _psu.Process(pid).children(recursive=True):
                            if c.pid not in seen:
                                seen.add(c.pid); pids.append(c.pid)
                    except: pass
                # Only emit if new PIDs appeared
                new = set(pids) - self._known
                if new:
                    self._known |= set(pids)
                    self._had_game = True
                    name = running[0][1] if running else "game"
                    self.game_found.emit(pids, name)
            except Exception as e:
                self.log_sig.emit(f"  ~ watcher: {e}", "warn")


# ══════════════════════════════════════════════════════════════
# Boost Worker
# ══════════════════════════════════════════════════════════════
class BoostWorker(QThread):
    log_sig    = pyqtSignal(str, str)
    phase_sig  = pyqtSignal(int)
    metric_sig = pyqtSignal(str, object)
    done_sig   = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        result = self._fn(
            lambda m, l="text": self.log_sig.emit(m, l),
            self.phase_sig,
            self.metric_sig
        )
        self.done_sig.emit(result)


# ══════════════════════════════════════════════════════════════
# GameBoostPage
# ══════════════════════════════════════════════════════════════
class GameBoostPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active         = False
        self._transitioning  = False
        self._saved_state    = None
        self._worker         = None
        self._gpu_thread     = None
        self._gpu_baseline   = -1
        self._watcher        = None
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(f"background:{C['bg']};")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("SYS BOOSTER")
        title.setStyleSheet(
            f"color:{C['text3']};font-size:9px;letter-spacing:4px;"
            f"font-family:{MONO};border:none;"
        )
        self._sdot = QLabel("●")
        self._stxt = QLabel("standby")
        for w in (self._sdot, self._stxt):
            w.setStyleSheet(
                f"color:{C['dim']};font-size:9px;letter-spacing:2px;"
                f"font-family:{MONO};border:none;"
            )
        hdr.addWidget(title); hdr.addStretch()
        hdr.addWidget(self._sdot); hdr.addSpacing(4)
        hdr.addWidget(self._stxt)
        root.addLayout(hdr)

        # Orbit button
        self._btn = OrbitButton()
        self._btn.clicked.connect(self._toggle)
        root.addWidget(self._btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Phase bar
        self._phases = PhaseBar()
        root.addWidget(self._phases, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Metrics
        grid = QGridLayout(); grid.setSpacing(8)
        self._mc_gpu  = MetricCard("GPU busy")
        self._mc_ram  = MetricCard("RAM freed")
        self._mc_bg   = MetricCard("Background")
        self._mc_game = MetricCard("Game detect")
        grid.addWidget(self._mc_gpu,  0, 0)
        grid.addWidget(self._mc_ram,  0, 1)
        grid.addWidget(self._mc_bg,   1, 0)
        grid.addWidget(self._mc_game, 1, 1)
        root.addLayout(grid)

        # Log
        self._log = CyberLog()
        self._log.append_line("[ ready — press boost ]", "mute")
        root.addWidget(self._log)
        root.addStretch()

    def _set_status(self, txt: str, color: str):
        s = (f"color:{color};font-size:9px;letter-spacing:2px;"
             f"font-family:{MONO};border:none;")
        self._sdot.setStyleSheet(s); self._stxt.setStyleSheet(s)
        self._stxt.setText(txt)

    def _toggle(self):
        if self._transitioning: return
        self._transitioning = True
        self._btn.setEnabled(False)
        if not self._active: self._start()
        else:                self._stop()

    # ── START ──────────────────────────────────────────────────
    def _start(self):
        self._active = True
        self._btn.set_active(True)
        self._phases.set_phase(0)
        self._set_status("scanning", C['yellow'])
        # Xoá log của phiên boost trước — tránh dòng "Game detected" cũ
        # còn sót lại trên màn hình, gây hiểu lầm là watcher vẫn đang
        # nhận diện một game đã dừng từ lâu.
        self._log.clear()
        self._log.append_line("┌─ GAME BOOST ─────────────────────────────", "head")

        self._worker = BoostWorker(self._boost_logic)
        self._worker.log_sig.connect(lambda m, l: self._log.append_line(m, l))
        self._worker.phase_sig.connect(self._phases.set_phase)
        self._worker.metric_sig.connect(self._on_metric)
        self._worker.done_sig.connect(self._on_done)
        self._worker.start()

    def _on_done(self, saved):
        self._saved_state   = saved
        self._transitioning = False
        self._btn.setEnabled(True)
        self._set_status("monitoring", C['cyan'])
        # Start GPU monitor
        self._gpu_baseline = -1
        self._gpu_thread   = GpuMonitorThread()
        self._gpu_thread.update.connect(self._on_gpu)
        self._gpu_thread.start()

        # Start game watcher — detect game launched AFTER boost
        saved = self._saved_state or {}
        self._watcher = GameWatcherThread(saved)
        self._watcher.game_found.connect(self._on_game_found)
        self._watcher.game_lost.connect(self._on_game_lost)
        self._watcher.log_sig.connect(lambda m, l: self._log.append_line(m, l))
        self._watcher.start()

    # ── STOP ───────────────────────────────────────────────────
    def _stop(self):
        self._set_status("restoring", C['yellow'])
        self._log.append_line("├─ RESTORE ────────────────────────────────", "warn")
        if self._gpu_thread:
            self._gpu_thread.stop(); self._gpu_thread = None
        saved = self._saved_state

        def _restore(log, *_):
            try:
                from core.booster import smart_boost_off
                if saved:
                    smart_boost_off(saved, log)
                # Remove mesa env file
                env_file = Path.home() / ".config/environment.d/cyber-boost.conf"
                try: env_file.unlink(missing_ok=True)
                except: pass
                # Restore swappiness
                sw = saved.get("swappiness_orig") if saved else None
                if sw and IS_LINUX:
                    try: Path("/proc/sys/vm/swappiness").write_text(sw)
                    except: pass
                # Restore VFR
                if saved and saved.get("hyprland_vfr") and shutil.which("hyprctl"):
                    try:
                        subprocess.run(
                            ["hyprctl", "keyword", "misc:vfr", "true"],
                            capture_output=True, timeout=3)
                    except: pass
                # Restore nice
                try:
                    import psutil
                    for pid, orig in (saved or {}).get("game_nice", {}).items():
                        try: psutil.Process(pid).nice(orig)
                        except: pass
                    for pid, orig in (saved or {}).get("bg_nice", {}).items():
                        try: psutil.Process(pid).nice(orig)
                        except: pass
                except ImportError:
                    pass
                log("└─ DONE ───────────────────────────────────", "head")
            except Exception as e:
                log(f"  ~ restore: {e}", "warn")
            return None

        self._worker = BoostWorker(_restore)
        self._worker.log_sig.connect(lambda m, l: self._log.append_line(m, l))
        self._worker.done_sig.connect(self._on_restore_done)
        self._worker.start()

    def _on_restore_done(self, _):
        self._active        = False
        self._saved_state   = None
        self._transitioning = False
        self._btn.set_active(False)
        self._btn.setEnabled(True)
        self._phases.set_phase(-1)
        self._set_status("standby", C['dim'])
        for mc in (self._mc_gpu, self._mc_ram, self._mc_bg, self._mc_game):
            mc.set_value("—"); mc.set_lit(False)
        # Stop watcher
        if self._watcher:
            self._watcher.stop(); self._watcher = None

    # ── Game found handler ────────────────────────────────────
    def _on_game_found(self, pids: list, name: str):
        """Gọi khi watcher detect game sau khi boost đã bật."""
        # Update metric card
        self._mc_game.set_value(f"{len(pids)} PIDs", name[:12], 80, C['purple'])
        self._mc_game.set_lit(True)
        # Apply nice(-10) cho game processes ngay lập tức (best-effort —
        # không cần quyền root, chỉ cố gắng và bỏ qua nếu hệ thống không
        # cho phép; CyberClean không nâng quyền chỉ để renice).
        boosted = 0
        try:
            import psutil as _psu
            for pid in pids[:8]:
                try:
                    p = _psu.Process(pid)
                    if p.nice() > -10:
                        p.nice(-10)
                        boosted += 1
                except (PermissionError, _psu.NoSuchProcess, _psu.AccessDenied):
                    pass
        except ImportError:
            pass

        if boosted:
            self._log.append_line(
                f"  ★ Game detected: {name} ({len(pids)} PIDs) — applying priority boost",
                "head"
            )
            self._log.append_line(f"  + {boosted} game threads → nice(-10)", "ok")
        else:
            self._log.append_line(
                f"  ◈ Game detected: {name} ({len(pids)} PIDs)", "ok"
            )

    # ── Game lost handler ─────────────────────────────────────
    def _on_game_lost(self):
        """
        Gọi khi watcher xác nhận toàn bộ PID game đã theo dõi đều đã
        chết (process không còn tồn tại). Báo rõ cho người dùng biết
        game đã dừng, và đưa UI/metric card về trạng thái "chỉ tăng
        tốc máy tính" — không còn ưu tiên cho một process không còn
        tồn tại nữa.
        """
        self._log.append_line(
            "  ○ Game ended — switching back to system-only boost", "mute"
        )
        self._mc_game.set_value("0 PIDs", "no game", 0, C['text3'])
        self._mc_game.set_lit(False)

    # ── Metrics / GPU ──────────────────────────────────────────
    def _on_metric(self, key, value):
        if key == "ram_freed_mb":
            mb = int(value)
            if mb > 0:
                self._mc_ram.set_value(f"{mb} MB", f"+{mb} MB",
                                       min(100, mb/5), C['cyan'])
            else:
                # -1 = compacted but no freed bytes
                self._mc_ram.set_value("compact", "✓ done", 40, C['cyan'])
            self._mc_ram.set_lit(True)
        elif key == "bg_count":
            n = int(value)
            self._mc_bg.set_value(f"{n} procs", "nice +5",
                                  min(100, n*4), C['yellow'])
            self._mc_bg.set_lit(True)
        elif key == "game_pids":
            pids = value
            if pids:
                self._mc_game.set_value(f"{len(pids)} PIDs", "",
                                        80, C['purple'])
                self._mc_game.set_lit(True)

    def _on_gpu(self, pct: int):
        if pct < 0: return
        if self._gpu_baseline < 0:
            self._gpu_baseline = pct
            # Detect nếu đang dùng CPU proxy (không có gpu_busy_percent)
            import platform
            from pathlib import Path as _P
            has_gpu_sysfs = any(
                True for _ in _P("/sys/class/drm").glob(
                    "card*/device/gpu_busy_percent")
            ) if platform.system() == "Linux" else False
            self._using_cpu_proxy = not has_gpu_sysfs

        delta = pct - self._gpu_baseline
        col   = C['green'] if delta >= 0 else C['red']
        dstr  = f"+{delta}%" if delta >= 0 else f"{delta}%"
        # Label khác nhau tùy source metric
        lbl   = C['cyan']
        self._mc_gpu.set_value(f"{pct}%", dstr, pct, col)
        # Đổi label card nếu dùng CPU proxy
        if getattr(self, '_using_cpu_proxy', False):
            self._mc_gpu._lbl.setText("CPU LOAD")
            self._mc_gpu._lbl.setToolTip(
                "Intel HD 520: no gpu_busy_percent sysfs.\n"
                "Showing CPU load % as proxy — higher = game using more CPU."
            )
        self._mc_gpu.set_lit(True)

    # ══════════════════════════════════════════════════════════
    # BOOST LOGIC
    # ══════════════════════════════════════════════════════════
    def _boost_logic(self, log, phase_sig, metric_sig) -> dict:
        saved = {}

        # ── PHASE 0: SCAN ──────────────────────────────────────
        phase_sig.emit(0)
        log("│", "mute")
        log("├─ [1/3] SCAN ─────────────────────────────", "head")

        # Detect GPU name
        gpu_name = "unknown"
        if IS_LINUX:
            for pn in Path("/sys/class/drm").glob("card*/device/product_name"):
                try: gpu_name = pn.read_text().strip()[:45]; break
                except: pass
            if gpu_name == "unknown":
                try:
                    r = subprocess.run(["lspci"], capture_output=True,
                                       text=True, timeout=3)
                    for ln in r.stdout.splitlines():
                        if "VGA" in ln or "3D" in ln:
                            gpu_name = ln.split(":")[-1].strip()[:45]; break
                except: pass
        log(f"│  ◈ GPU: {gpu_name}", "mute")

        # Detect game PIDs — dùng _detect_running_games() từ booster.py (v3.0)
        # KHÔNG tự detect bằng heuristic CPU/RAM (gây false positive với gcc/ffmpeg)
        # _detect_running_games() v3.0 đã có:
        #   Tier 1 — _KNOWN_GAME_PROCS (tên game cụ thể, tin theo tên)
        #   Tier 2 — _WRAPPER_PROCS (bwrap/wine/proton/sober) KHÔNG tin theo tên
        #            nữa — chỉ báo "game" nếu tìm được descendant nặng CPU thật
        #            bên trong (dò cả theo session id, vượt qua PID-namespace
        #            reparenting của bwrap --unshare-pid). Sửa lỗi:
        #              - "Game detected: bwrap" dù không mở game gì (mọi
        #                Flatpak app khác cũng spawn bwrap)
        #              - Boost không tới được process game thật bên trong
        #                sandbox (trước đây chỉ boost cái vỏ bwrap rảnh CPU)
        #   Tier 3 — Child-of-launcher + CPU > threshold (Steam, Epic, Lutris...)
        #   _KNOWN_HEAVY_NON_GAMES blacklist (gcc, ffmpeg, webpack...) vẫn giữ
        # Detect game PIDs — gọi thẳng _detect_running_games() từ booster.py
        game_pids   = []
        _cpu_samples = {}
        _running_games = []
        try:
            from core.booster import _detect_running_games
            _running_games, _cpu_samples = _detect_running_games()

            # Build full PID tree cho mỗi game. Lưu ý: với game qua sandbox
            # (Tier 2), game_pid ở đây ĐÃ LÀ process nặng thật tìm được bên
            # trong bwrap/wine, không phải cái vỏ — children() dưới đây chỉ
            # mở rộng thêm nếu chính process đó có spawn thêm con riêng.
            import psutil as _psu
            _seen = set()
            for game_pid, game_name in _running_games:
                if game_pid in _seen:
                    continue
                _seen.add(game_pid)
                game_pids.append(game_pid)
                try:
                    for child in _psu.Process(game_pid).children(recursive=True):
                        if child.pid not in _seen:
                            _seen.add(child.pid)
                            game_pids.append(child.pid)
                except (_psu.NoSuchProcess, _psu.AccessDenied):
                    pass

        except Exception as e:
            log(f"│  ~ detect: {e}", "warn")

        if game_pids:
            log(f"│  ◈ game: {len(game_pids)} PIDs detected", "ok")
            metric_sig.emit("game_pids", game_pids)
            # Game đã chạy từ trước khi bấm Boost — apply nice(-10) ngay tại
            # đây (best-effort, không nâng quyền). Watcher (khởi tạo sau, ở
            # dưới) chỉ còn lo phần game mở SAU khi Boost đã bật.
            boosted = 0
            try:
                import psutil as _psu
                for pid in game_pids[:8]:
                    try:
                        p = _psu.Process(pid)
                        if p.nice() > -10:
                            p.nice(-10)
                            boosted += 1
                    except (PermissionError, _psu.NoSuchProcess, _psu.AccessDenied):
                        pass
            except ImportError:
                pass

            game_name_for_log = _running_games[0][1] if _running_games else "game"
            if boosted:
                log(
                    f"│  ★ Game detected: {game_name_for_log} ({len(game_pids)} PIDs) — applying priority boost",
                    "head"
                )
                log(f"│  + {boosted} game threads → nice(-10)", "ok")
            else:
                log(f"│  ◈ game: {game_name_for_log} detected", "mute")
        else:
            log("│  ◈ no game — watcher applies boost on launch", "mute")

        mesa_ok = os.environ.get("mesa_glthread") == "true"
        log(f"│  ◈ mesa_glthread: {'SET' if mesa_ok else 'NOT SET → will apply'}", 
            "ok" if mesa_ok else "warn")
        time.sleep(0.4)

        # ── PHASE 1: APPLY ─────────────────────────────────────
        phase_sig.emit(1)
        log("│", "mute")
        log("├─ [2/3] APPLY ────────────────────────────", "head")

        # 1. Free RAM (TRƯỚC TIÊN)
        try:
            from core.booster import free_ram
            res = free_ram(log)  # free_ram() already logs its own result line
            mb  = getattr(res, "mb_freed", 0) or 0
            # Emit cho UI card hiển thị, nhưng KHÔNG log lại — free_ram() đã
            # log đầy đủ rồi (kèm cả "now X MB available"). Log thêm ở đây
            # từng tạo ra 2 dòng trùng nhau cho cùng 1 sự kiện.
            # Ngưỡng > 10 phải khớp với ngưỡng trong free_ram() (booster.py),
            # nếu không terminal log và card UI sẽ disagree với nhau khi
            # freed nằm trong khoảng 6-10 MB.
            metric_sig.emit("ram_freed_mb", mb if mb > 10 else -1)
        except Exception as e:
            log(f"│  ~ free_ram: {e}", "warn")

        # 2. CPU governor
        if IS_LINUX:
            try:
                from core.booster import _enable_kernel_performance
                saved["power"] = _enable_kernel_performance(log)
            except Exception: pass

        # 3. Mesa GL threading (tác động lớn nhất với iGPU)
        if IS_LINUX:
            env_vars = {
                "mesa_glthread":               "true",
                "MESA_NO_ERROR":               "1",
                "RADV_PERFTEST":               "nosam,rt",
                "__GL_THREADED_OPTIMIZATIONS": "1",
                "MESA_DEBUG":                  "0",
            }
            for k, v in env_vars.items():
                os.environ[k] = v
            env_f = Path.home() / ".config/environment.d/cyber-boost.conf"
            try:
                env_f.parent.mkdir(parents=True, exist_ok=True)
                env_f.write_text(
                    "# CyberClean gaming env\n" +
                    "\n".join(f"{k}={v}" for k, v in env_vars.items()) + "\n"
                )
                saved["mesa_env_file"] = str(env_f)
            except OSError: pass
            log("│  + mesa_glthread=true MESA_NO_ERROR=1", "ok")
            log("│  i relaunch Sober for GL threading to take effect", "mute")

        # 4. Compositor VFR unlock
        if IS_LINUX and shutil.which("hyprctl"):
            try:
                subprocess.run(["hyprctl","keyword","misc:vfr","false"],
                               capture_output=True, timeout=3)
                subprocess.run(["hyprctl","keyword","misc:no_direct_scanout","false"],
                               capture_output=True, timeout=3)
                saved["hyprland_vfr"] = True
                log("│  + Hyprland: VFR disabled, direct scanout on", "ok")
            except: pass

        # 5. vm.swappiness = 1
        if IS_LINUX:
            sw = Path("/proc/sys/vm/swappiness")
            try:
                saved["swappiness_orig"] = sw.read_text().strip()
                sw.write_text("1")
                log("│  + vm.swappiness → 1 (game pages stay in RAM)", "ok")
            except (PermissionError, OSError):
                try:
                    r = subprocess.run(
                        ["sudo","-n","/usr/local/bin/cyber-clean-helper","swappiness"],
                        capture_output=True, timeout=5)
                    if r.returncode == 0:
                        saved["swappiness_orig"] = "60"
                        log("│  + vm.swappiness → 10 (via helper)", "ok")
                except: pass

        # 6. nice(-10) game, nice(+5) background
        bg_count = 0
        try:
            import psutil as _psu
            uid = os.getuid() if IS_LINUX else -1
            SKIP = {"kwin_wayland","kwin","hyprland","sway","pipewire","wireplumber",
                    "dbus-daemon","systemd","fcitx","fcitx5","ibus","discord",
                    "firefox","chrome","cyberclean","python","python3"}

            for pid in game_pids[:8]:
                try:
                    p = _psu.Process(pid)
                    o = p.nice()
                    if o > -10:
                        p.nice(-10)
                        saved.setdefault("game_nice", {})[pid] = o
                except (PermissionError, _psu.NoSuchProcess, _psu.AccessDenied): pass

            for p in _psu.process_iter(["pid","name"]):
                try:
                    nm = (p.info["name"] or "").lower().replace(".exe","")
                    if nm in SKIP or p.pid in game_pids:
                        continue
                    # uid check — bỏ qua nếu không lấy được uid
                    if IS_LINUX and uid >= 0:
                        try:
                            if p.uids().real != uid: continue
                        except (_psu.NoSuchProcess, _psu.AccessDenied):
                            continue
                    o = p.nice()
                    if o < 5:
                        p.nice(5)
                        saved.setdefault("bg_nice", {})[p.pid] = o
                        bg_count += 1
                except: pass

            log(f"│  + {bg_count} background → nice(+5)", "ok")
            metric_sig.emit("bg_count", bg_count)


        except ImportError: pass

        saved["game_pids"] = game_pids
        log("│", "mute")
        log("└─ BOOST ACTIVE ───────────────────────────", "head")

        # ── PHASE 2: MONITOR (GpuMonitorThread handles this) ──
        phase_sig.emit(2)
        return saved
