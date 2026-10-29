"""Disk-core animation contracts, without telemetry or machine mutations."""
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap
import ui_widgets as U


@pytest.fixture
def core(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(U, 'IS_WINDOWS', True)
    widget=U.Cyber3DDiskCore()
    widget.resize(196,184)
    widget.show(); app.processEvents(); widget._timer.stop()
    yield widget
    widget.close(); app.processEvents()


def paint(widget):
    canvas=QPixmap(widget.size())
    widget.render(canvas)


def test_idle_is_continuous_30fps_not_one_frame_per_second(core,monkeypatch):
    monkeypatch.setattr(U.time,'monotonic',lambda:10.)
    core._frame_time=9.96
    core._intro_ticks=100
    core._hover=False
    angle=core._rot_y
    core._tick()
    assert core._timer.interval()==33
    assert core._rot_y-angle==pytest.approx(1.28)


def test_motion_and_tilt_use_elapsed_time_instead_of_frame_count(core,monkeypatch):
    clock=[20.]
    monkeypatch.setattr(U.time,'monotonic',lambda:clock[0])
    core._hover=False;core._target_rot_x=40.
    core._frame_time=19.96;core._rot_y=0.;core._rot_x=24.
    core._tick()
    expected=(core._rot_y,core._rot_x)
    core._frame_time=19.96;core._rot_y=0.;core._rot_x=24.
    clock[0]=19.98;core._tick()
    clock[0]=20.;core._tick()
    assert (core._rot_y,core._rot_x)==pytest.approx(expected)


def test_static_readout_and_glow_are_reused_while_rings_rotate(core):
    core.set_usage_detail(65.8,'60.7 GB / 92.3 GB','92.3 GB')
    paint(core)
    generation=core._static_builds
    glow,readout=core._glow_layer,core._readout_layer
    core._rot_y+=20.;paint(core)
    assert core._static_builds==generation
    assert core._glow_layer is glow and core._readout_layer is readout
    core.set_usage_detail(66.,'61.0 GB / 92.3 GB','92.3 GB');paint(core)
    assert core._static_builds==generation+1
    core.resize(220,184);paint(core)
    assert core._static_builds==generation+2


def test_hidden_and_minimized_stop_work(core):
    core._timer.start(40)
    core.hide()
    assert not core._timer.isActive()
    core.show();QApplication.processEvents()
    core.showMinimized();QApplication.processEvents()
    core._tick()
    assert not core._timer.isActive()


def test_stationary_hover_returns_to_idle_cadence(core,monkeypatch):
    monkeypatch.setattr(U.time,'monotonic',lambda:20.)
    core._hover=True;core._frame_time=19.96
    core._last_motion=18.
    core._tick()
    assert core._timer.interval()==33
    core._last_motion=19.9;core._tick()
    assert core._timer.interval()==33
