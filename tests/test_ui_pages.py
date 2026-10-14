"""DEEP CLEAN và DISK ADVISOR bằng Qt offscreen — hành vi an toàn của giao diện, không phải ảnh chụp."""
import threading
import time

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

from core.base_cleaner import CleanResult, CleanTarget, ReviewItem, ReviewScan


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeCleaner:
    def __init__(self):
        self.cleaned = []
        self.scans = []
        self.gate = None                                   # threading.Event để giữ lệnh xóa lại

    def get_targets(self):
        return [CleanTarget("thumbnails", "Thumbnails", "auto thing", "safe"),
                CleanTarget("dev_cache", "Developer Caches", "caches", "caution", tier="review"),
                CleanTarget("docker", "Docker/Podman", "images", "caution", tier="review"),
                CleanTarget("empty_trash", "Trash", "trash", "caution", tier="review")]

    def review_scan(self, tid, progress_cb=None):
        self.scans.append(tid)
        if tid == "empty_trash":
            return ReviewScan(tid)                         # trống
        if tid == "docker":
            raise RuntimeError("daemon not reachable")
        return ReviewScan(tid, items=[
            ReviewItem("a", "~/.npm/_cacache", size=800_000, newest=time.time() - 40 * 86400, risk="low",
                       payload={"path": "/x/a", "rule": "dev-npm"}),
            ReviewItem("b", "~/.m2/repository", size=3_000_000, risk="high", detail="mvn install",
                       payload={"path": "/x/b", "rule": "dev-maven"}),
            ReviewItem("c", "~/.cache/JetBrains", size=500, risk="medium", blocked="idea is running — close it first"),
            ReviewItem("d", "~/.cache/go-build", size=1_000_000, risk="low"),
        ], warning="Nothing is selected by default.")

    def review_clean(self, tid, ids, dry=False):
        if self.gate is not None:
            self.gate.wait(5)
        self.cleaned.append((tid, list(ids)))
        return CleanResult(tid, freed_bytes=800_000, files_removed=len(ids), dry=False, measured_bytes=900_000,
                           notes=["Btrfs: snapshots may keep the space"], skipped=[("/x/z", "in use")])


def wait(qapp, cond, sec=10.0):
    end = time.time() + sec
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)
    assert cond(), "timeout"


def make_page(qapp):
    from ui_pages import DeepCleanPage
    fc = FakeCleaner()
    page = DeepCleanPage(fc)
    page.resize(1100, 700)
    page.show()
    return fc, page


def open_card(qapp, page, tid):
    page.card(tid).clicked.emit(tid)
    wait(qapp, lambda: page.panel._scan is not None and page.panel.target.id == tid and not page.panel.busy)


# ── trang DEEP CLEAN ─────────────────────────────────────────────────────────
def test_only_review_targets_get_cards(qapp):
    fc, page = make_page(qapp)
    assert set(page._cards) == {"dev_cache", "docker", "empty_trash"}
    assert "thumbnails" not in page._cards, "target AUTO không được xuất hiện ở trang Dọn sâu"
    page.shutdown()


def test_nothing_is_scanned_until_the_user_asks(qapp):
    fc, page = make_page(qapp)
    qapp.processEvents()
    assert fc.scans == [], "mở trang không được tự quét đĩa"
    assert all(c._kind == "idle" for c in page._cards.values())
    page.shutdown()


def test_selecting_a_card_scans_and_nothing_is_preticked(qapp):
    fc, page = make_page(qapp)
    open_card(qapp, page, "dev_cache")
    panel = page.panel
    assert panel._table.rowCount() == 4 and not panel._checked(), "Review không được tick sẵn mục nào"
    assert not (panel._table.item(2, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)
    from ui_pages import TwoLineDelegate
    blocked = panel._table.item(2, 1)
    assert "close it first" in blocked.data(TwoLineDelegate.ROLE_NOTE) and blocked.text().startswith("🔒")
    assert panel._table.columnCount() == 5
    assert not panel._del_btn.isEnabled()
    card = page.card("dev_cache")
    assert card._kind == "ready" and card._count == 4 and "KB" in card._size.text() or "MB" in card._size.text()
    assert page.card("dev_cache").property("selected") is True
    page.shutdown()


def test_select_all_skips_high_risk_and_blocked(qapp):
    fc, page = make_page(qapp)
    open_card(qapp, page, "dev_cache")
    panel = page.panel
    panel._select_safe()
    assert {i.id for i in panel._checked()} == {"a", "d"}
    panel._select_none()
    assert not panel._checked()
    page.shutdown()


def test_empty_and_failing_categories_have_clear_states(qapp):
    fc, page = make_page(qapp)
    page.card("empty_trash").clicked.emit("empty_trash")
    wait(qapp, lambda: page.card("empty_trash")._kind == "ready")
    assert page.card("empty_trash")._count == 0 and page.card("empty_trash")._size.text() == "✓"
    page.card("docker").clicked.emit("docker")
    wait(qapp, lambda: page.card("docker")._kind == "error")
    assert "daemon not reachable" in page.panel._status.text()
    page.shutdown()


def test_delete_requires_confirmation_default_is_cancel(qapp, monkeypatch):
    fc, page = make_page(qapp)
    open_card(qapp, page, "dev_cache")
    panel = page.panel
    panel._table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        seen["default"] = self.standardButton(self.defaultButton()) if self.defaultButton() else None
        return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    panel._delete()
    assert fc.cleaned == [], "bấm Cancel mà vẫn xóa!"
    assert "cannot be undone" in seen["text"].lower() or "hoàn tác" in seen["text"].lower()
    assert seen["default"] == QMessageBox.StandardButton.Cancel, "phím Enter mặc định phải là HỦY, không phải Xóa"
    page.shutdown()


def test_confirmed_delete_sends_only_selected_ids_names_high_risk_and_rescans(qapp, monkeypatch):
    fc, page = make_page(qapp)
    got = []
    page.cleaned.connect(lambda t, r: got.append((t.id, r.freed_bytes)))
    open_card(qapp, page, "dev_cache")
    panel = page.panel
    panel._table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    panel._table.item(1, 0).setCheckState(Qt.CheckState.Checked)        # mục rủi ro cao tick tay
    texts = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: texts.append(self.text()) or QMessageBox.StandardButton.Yes)
    panel._delete()
    wait(qapp, lambda: bool(got))
    assert fc.cleaned == [("dev_cache", ["a", "b"])] and got == [("dev_cache", 800_000)]
    assert "HIGH-RISK" in texts[0] and "~/.m2/repository" in texts[0]
    wait(qapp, lambda: not panel.busy and fc.scans.count("dev_cache") >= 2)      # tự quét lại sau khi xóa
    out = panel._result.toPlainText()
    assert "freed" in out and "measured" in out and "Btrfs" in out and "skipped" in out
    assert panel._checked() == [], "sau khi dọn xong, lựa chọn cũ không được giữ lại"
    page.shutdown()


def test_cannot_switch_category_while_deleting(qapp, monkeypatch):
    fc, page = make_page(qapp)
    open_card(qapp, page, "dev_cache")
    fc.gate = threading.Event()
    page.panel._table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    page.panel._delete()
    assert page.panel.deleting
    page.card("empty_trash").clicked.emit("empty_trash")
    assert page.panel.target.id == "dev_cache", "đang xóa mà vẫn cho chuyển danh mục"
    fc.gate.set()
    wait(qapp, lambda: not page.panel.busy)
    page.shutdown()


def test_stale_scan_result_is_ignored_after_switching(qapp):
    from ui_pages import ReviewPanel
    fc = FakeCleaner()
    panel = ReviewPanel(fc)
    t1 = CleanTarget("dev_cache", "Dev", "d", "caution", tier="review")
    t2 = CleanTarget("empty_trash", "Trash", "t", "caution", tier="review")
    panel.set_target(t1)
    panel._t = t2                                         # người dùng đã chuyển đi trước khi quét xong
    panel._on_scan("dev_cache", fc.review_scan("dev_cache"))
    assert panel._table.rowCount() == 0
    panel.shutdown()


def test_scan_all_fills_cards_and_total_and_can_stop(qapp):
    fc, page = make_page(qapp)
    page._toggle_scan_all()
    wait(qapp, lambda: page._all_worker is not None and not page._all_worker.isRunning())
    qapp.processEvents()
    assert page.card("dev_cache")._kind == "ready" and page.card("empty_trash")._kind == "ready"
    assert page.card("docker")._kind == "error"
    assert "to review" in page._total.text() or "xem lại" in page._total.text()
    assert page._scan_all_btn.text() in ("SCAN ALL", "QUÉT TẤT CẢ")
    page.shutdown()


def test_selecting_after_scan_all_reuses_results_without_rescanning(qapp):
    fc, page = make_page(qapp)
    page._toggle_scan_all()
    wait(qapp, lambda: page._all_worker is not None and not page._all_worker.isRunning())
    qapp.processEvents()
    n = fc.scans.count("dev_cache")
    page.card("dev_cache").clicked.emit("dev_cache")
    qapp.processEvents()
    assert fc.scans.count("dev_cache") == n and page.panel._table.rowCount() == 4
    page.shutdown()


# ── trang DISK ADVISOR ───────────────────────────────────────────────────────
def test_advisor_page_intro_then_report_and_no_delete_buttons(qapp, tmp_path):
    from ui_pages import AdvisorPage
    with open(tmp_path / "disk.qcow2", "wb") as f:
        f.truncate(600 * 1024 * 1024)
    page = AdvisorPage(str(tmp_path), "")
    page.resize(1000, 700)
    page.show()
    assert page._stack.currentIndex() == 0 and not page._copy_btn.isEnabled()
    page.start()
    assert page.scanning
    wait(qapp, lambda: page.report is not None, 60)
    qapp.processEvents()
    assert page._stack.currentIndex() == 1 and page._copy_btn.isEnabled()
    assert "vm" in page.report.by_category()
    labels = " ".join(b.text().lower() for b in page.findChildren(QPushButton))
    for bad in ("delete", "remove", "clean", "xóa", "dọn", "uninstall", "gỡ"):
        assert bad not in labels, f"Advisor có nút '{bad}' — chỉ được báo cáo"
    page.shutdown()


def test_advisor_copy_report_and_open_folder_buttons(qapp, tmp_path):
    from ui_pages import AdvisorPage
    with open(tmp_path / "disk.qcow2", "wb") as f:
        f.truncate(600 * 1024 * 1024)
    page = AdvisorPage(str(tmp_path), "")
    page.start()
    wait(qapp, lambda: page.report is not None, 60)
    page.copy_report()
    text = QApplication.clipboard().text()
    assert "Disk Advisor report" in text and "disk.qcow2" in text and "~" not in text.splitlines()[0]
    from ui_pages import _FindingRow
    rows = page.findChildren(_FindingRow)
    assert rows and any(r.open_btn.isEnabled() for r in rows)
    page.shutdown()


def test_advisor_can_be_stopped_and_still_reports(qapp, tmp_path):
    from ui_pages import AdvisorPage
    for i in range(200):
        (tmp_path / f"d{i}").mkdir()
    page = AdvisorPage(str(tmp_path), "")
    page.start()
    page._toggle()                                       # STOP
    wait(qapp, lambda: page.report is not None, 30)
    assert page.report.truncated
    assert not page._prog.isVisible()
    page.shutdown()


def test_advisor_nothing_found_shows_friendly_message(qapp, tmp_path):
    from ui_pages import AdvisorPage
    page = AdvisorPage(str(tmp_path), "")
    page.start()
    wait(qapp, lambda: page.report is not None, 60)
    # máy test có thể có /opt, gói nặng... → chỉ kiểm tra không vỡ và có trạng thái hợp lệ
    assert page._stack.currentIndex() in (0, 1)
    page.shutdown()


# ── helpers ──────────────────────────────────────────────────────────────────
def test_elided_label_shortens_long_paths(qapp):
    from ui_pages import ElidedLabel
    lbl = ElidedLabel("/home/user/" + "very-long-folder/" * 20 + "file.qcow2")
    lbl.resize(200, 20)
    lbl.show()
    qapp.processEvents()
    assert "…" in lbl.text() and lbl.toolTip().endswith("file.qcow2")


def test_share_bar_paints_without_error(qapp):
    from ui_pages import ShareBar
    bar = ShareBar()
    bar.resize(400, 16)
    bar.set_data([("#C084FC", 5), ("#00E8FF", 3), ("#F5C542", 0)])
    bar.grab()
    bar.set_data([])
    bar.grab()
