"""Hồi quy cho đợt sửa lỗi sau audit (DWM/HKCU, nhật ký xóa, nhãn quyền, i18n, thẻ boost, đóng gói)."""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ── 1. DWM bypass: ghi HKCU, không nối trùng token ───────────────────────────────────────────────
def test_dx_settings_adds_token_and_is_idempotent():
    from core.booster import _dx_settings_disable_swap_upgrade as f
    new, changed = f(None)
    assert new == "SwapEffectUpgradeEnable=0;" and changed
    again, changed2 = f(new)
    assert again == new and changed2 is False


def test_dx_settings_replaces_existing_and_keeps_others():
    from core.booster import _dx_settings_disable_swap_upgrade as f
    new, changed = f("VRROptimizeEnable=1;SwapEffectUpgradeEnable=1;")
    assert changed
    assert new == "VRROptimizeEnable=1;SwapEffectUpgradeEnable=0;"
    assert new.count("SwapEffectUpgradeEnable") == 1


def test_dx_settings_no_duplicate_when_repeated_without_trailing_semicolon():
    from core.booster import _dx_settings_disable_swap_upgrade as f
    new, _ = f("A=1")
    assert new == "A=1;SwapEffectUpgradeEnable=0;"
    assert f(new)[0].count("SwapEffectUpgradeEnable") == 1


class _FakeKey:
    pass


def _fake_winreg(store, hives):
    m = types.ModuleType("winreg")
    m.HKEY_CURRENT_USER, m.HKEY_LOCAL_MACHINE = "HKCU", "HKLM"
    m.KEY_READ, m.KEY_SET_VALUE, m.REG_SZ = 1, 2, 1

    def create(hive, sub, *_):
        hives.append((hive, sub))
        if hive != "HKCU":
            raise PermissionError("denied")
        return _FakeKey()

    def query(key, name):
        if name not in store:
            raise FileNotFoundError(name)
        return store[name], 1

    def setv(key, name, _r, _t, val):
        store[name] = val

    m.CreateKeyEx, m.OpenKey = create, create
    m.QueryValueEx, m.SetValueEx, m.CloseKey = query, setv, lambda k: None
    m.DeleteValue = lambda k, n: store.pop(n, None)
    return m


def test_dwm_bypass_uses_hkcu_and_restores(monkeypatch):
    from core import booster
    store, hives, logs = {}, [], []
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(store, hives))
    monkeypatch.setattr(booster, "IS_WINDOWS", True)
    monkeypatch.setattr(booster, "IS_LINUX", False)
    saved = {}
    booster._bypass_compositor_on(lambda m, l="ok": logs.append(m), saved)
    assert hives and all(h == "HKCU" for h, _ in hives), "không được ghi vào HKLM"
    assert store["DirectXUserGlobalSettings"] == "SwapEffectUpgradeEnable=0;"
    assert not any("needs admin" in m for m in logs), "không được kết luận sai là thiếu quyền admin"
    # bật lần 2: không đổi gì, không nối trùng
    saved2 = {}
    booster._bypass_compositor_on(lambda m, l="ok": logs.append(m), saved2)
    assert store["DirectXUserGlobalSettings"].count("SwapEffectUpgradeEnable") == 1
    assert not saved2.get("compositor_bypassed")
    # hoàn nguyên: giá trị gốc là None -> xóa value
    assert booster._bypass_compositor_off(saved, lambda *a, **k: None) is True
    assert "DirectXUserGlobalSettings" not in store


def test_dwm_bypass_failure_reports_real_error(monkeypatch):
    from core import booster
    logs = []
    m = _fake_winreg({}, [])
    m.CreateKeyEx = lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied"))
    monkeypatch.setitem(sys.modules, "winreg", m)
    monkeypatch.setattr(booster, "IS_WINDOWS", True)
    monkeypatch.setattr(booster, "IS_LINUX", False)
    saved = {}
    booster._bypass_compositor_on(lambda msg, l="ok": logs.append(msg), saved)
    assert any("PermissionError" in x for x in logs), "phải nêu lỗi thật"
    assert not saved.get("compositor_bypassed")


# ── 2. Nhật ký xóa: 300 dòng MỚI nhất ─────────────────────────────────────────────────────────────
def test_load_rollback_shows_newest_300(tmp_path, monkeypatch):
    import json
    from PyQt6.QtWidgets import QApplication, QTableWidget
    import main as M
    app = QApplication.instance() or QApplication([])
    f = tmp_path / "rollback.jsonl"
    f.write_text("\n".join(json.dumps({"time": "2026-10-31T08:00:00", "type": "t", "size": 1, "path": f"p{i}"})
                           for i in range(350)), encoding="utf-8")
    monkeypatch.setattr(M, "ROLLBACK_FILE", f)
    fake = types.SimpleNamespace(rollback_table=QTableWidget(0, 4))
    M.CyberCleanApp._load_rollback(fake)
    t = fake.rollback_table
    assert t.rowCount() == 300
    assert t.item(0, 3).text() == "p349", "dòng đầu phải là mục mới nhất"
    assert t.item(299, 3).text() == "p50", "50 mục cũ nhất bị lược bỏ, không phải 50 mục mới nhất"
    del app


# ── 3. Nhãn quyền theo hệ điều hành ───────────────────────────────────────────────────────────────
def test_priv_tag_per_os(monkeypatch):
    import ui_widgets as W
    monkeypatch.setattr(W, "IS_WINDOWS", True)
    assert W.priv_tag(True) == " [ADMIN]" and W.priv_tag(False) == ""
    monkeypatch.setattr(W, "IS_WINDOWS", False)
    assert W.priv_tag(True) == " [ROOT]" and W.priv_tag(False) == ""


def test_no_hardcoded_root_label_left():
    for name in ("main.py", "ui_pages.py"):
        assert "' [ROOT]'" not in (ROOT / name).read_text(encoding="utf-8"), name


# ── 4. i18n log tăng tốc: khớp nguyên dòng, không làm sai nghĩa ──────────────────────────────────
@pytest.fixture()
def vi():
    from utils import i18n
    old = i18n.T.lang
    i18n.T.lang = "vi"
    yield i18n
    i18n.T.lang = old


def test_boost_log_translates_known_lines_and_keeps_prefix(vi):
    t = vi.translate_boost_log_line
    assert t("│  i no game yet — background priority left untouched until launch").startswith("│  i chưa có game")
    assert t("└─ BOOST ACTIVE ───────────────────────────") == "└─ TĂNG TỐC ĐANG BẬT ───────────────────────────"
    out = t("  i RAM pressure is healthy (72%) — skipping forced working-set flush to prevent page-fault stutter")
    assert "72%" in out and "RAM pressure" not in out
    assert "+2 MB" in t("  i Observed system available RAM delta: +2 MB (all workloads; not attributable to Boost)")


def test_boost_log_never_rewrites_unknown_or_safety_lines(vi):
    t = vi.translate_boost_log_line
    for line in ("⚠ GAME MODE OFF — partial restore (some settings could not be restored)",
                 "✓ GAME MODE ON — 3 apps jailed",
                 "GPU: Intel(R) HD Graphics 520",
                 "  ~ some line nobody translated yet"):
        assert t(line) == line


def test_boost_log_english_unchanged():
    from utils import i18n
    old = i18n.T.lang
    i18n.T.lang = "en"
    try:
        s = "│  i no game yet — background priority left untouched until launch"
        assert i18n.translate_boost_log_line(s) == s
    finally:
        i18n.T.lang = old


def test_new_i18n_keys_exist_in_both_languages():
    from utils.i18n import TRANSLATIONS
    keys = ["boost_mc_ram_delta", "boost_mc_ram_observed", "boost_mc_ram_tip", "adv_note_win_totals",
            "lbl_free_used_fmt", "boost_standby"] + [k for k in TRANSLATIONS["en"] if k.startswith("bl_")]
    for k in keys:
        assert TRANSLATIONS["en"].get(k) and TRANSLATIONS["vi"].get(k), k
    assert {k for k in TRANSLATIONS["en"] if k.startswith("bl_")} == {k for k in TRANSLATIONS["vi"] if k.startswith("bl_")}


def test_advisor_note_translated_in_vi(vi):
    import ui_pages
    note = "Totals count each Windows path once; folder and file rows can overlap. Sizes are logical bytes, x."
    assert ui_pages._adv_note_t(note) != note
    assert ui_pages._adv_note_t("something else") == "something else"


def test_free_used_label_fits_column(vi):
    from utils.i18n import _t
    assert "65.5" in _t("lbl_free_used_fmt", "").format(pct=65.5)


# ── 5. Đóng gói ───────────────────────────────────────────────────────────────────────────────────
def test_no_stale_root_dll_and_vendor_present():
    assert not (ROOT / "LibreHardwareMonitorLib.dll").exists(), "DLL cũ (0.9.4) ở thư mục gốc không còn được dùng"
    assert (ROOT / "vendor/lhm/LibreHardwareMonitorLib.dll").exists()


def test_build_py_has_no_bom():
    assert not (ROOT / "build.py").read_bytes().startswith(b"\xef\xbb\xbf")


# ── 6. Bổ sung: làm tươi đĩa tức thì trên Windows + cố định nhãn Boost + UTF-8 log ────────────────
def test_windows_telemetry_refresh_disks_bypasses_5s_cache():
    from utils.windows_telemetry import WindowsTelemetry
    calls = [0]

    class FakePart:
        device = "C:\\"
        mountpoint = "C:\\"

    class FakeUsage:
        def __init__(self, pct, free):
            self.total = 1000
            self.used = int(pct * 10)
            self.free = free
            self.percent = pct

    class FakeApi:
        NoSuchProcess = ProcessLookupError
        AccessDenied = PermissionError
        def cpu_count(self): return 4
        def disk_partitions(self, all=False): return [FakePart()]
        def disk_usage(self, mp):
            calls[0] += 1
            return FakeUsage(67.5 if calls[0] == 1 else 65.0, 325 if calls[0] == 1 else 350)

    tel = WindowsTelemetry(api=FakeApi(), clock=lambda: 100.0)
    tel._slow()
    assert tel.snapshot().disks[0].percent == 67.5
    # Ngay sau khi dọn Thùng rác / gỡ app, refresh_disks() phải cập nhật ngay mà không chờ chu kỳ 5s
    snap_after = tel.refresh_disks()
    assert snap_after.disks[0].percent == 65.0
    assert snap_after.disks[0].free == 350


def test_boost_widget_init_and_standby_i18n_consistency():
    src = (ROOT / "core/game_boost_widget.py").read_text(encoding="utf-8")
    assert 'MetricCard(_t("boost_mc_ram_delta", "RAM Δ AVAILABLE") if IS_WINDOWS else _t("boost_mc_ram", "RAM FREED"))' in src
    assert "'0 procs', 'standby'" not in src
    assert '"0 procs", "standby"' not in src


def test_history_and_rollback_utf8_encoding_in_main():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "open(LOG_FILE, 'a', encoding='utf-8')" in src
    assert "open(ROLLBACK_FILE, 'a', encoding='utf-8')" in src
    assert "ROLLBACK_FILE.read_text(encoding='utf-8', errors='replace')" in src
    assert "LOG_FILE.read_text(encoding='utf-8', errors='replace')" in src
