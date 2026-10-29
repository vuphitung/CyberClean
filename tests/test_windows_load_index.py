from types import SimpleNamespace as NS

from PyQt6.QtWidgets import QApplication, QLabel


def test_missing_temperature_keeps_percentage_and_vietnamese_explanation(monkeypatch):
    import main as M
    from utils.i18n import T
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(T, 'lang', 'vi')
    owner = NS(health_lbl=QLabel(), health_sub=QLabel())
    snapshot = NS(cpu_percent=5., ram_percent=74., disks=[object()], temp_max=None,
                  swap_percent=50., swap_total=100)
    M.CyberCleanApp._update_windows_load_index(owner, snapshot, 90, [])
    assert owner.health_lbl.text() == '90%'
    assert owner.health_sub.text() == 'Ước tính · thiếu nhiệt độ'
    assert 'không phải % CPU' in owner.health_sub.toolTip()
    snapshot.temp_max = 55
    M.CyberCleanApp._update_windows_load_index(owner, snapshot, 90, ['Disk 91%'])
    assert owner.health_sub.text() == 'Ổ đĩa 91%'
    assert 'Số liệu còn thiếu: không có' in owner.health_sub.toolTip()


def test_missing_required_counters_does_not_invent_100_percent(monkeypatch):
    import main as M
    from utils.i18n import T
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(T, 'lang', 'vi')
    owner = NS(health_lbl=QLabel('100%'), health_sub=QLabel())
    snapshot = NS(cpu_percent=None, ram_percent=50., disks=[object()], temp_max=55,
                  swap_percent=30., swap_total=100)
    M.CyberCleanApp._update_windows_load_index(owner, snapshot, 100, [])
    assert owner.health_lbl.text() == '—'
    assert owner.health_sub.text() == 'Đang chờ số liệu hệ thống'
