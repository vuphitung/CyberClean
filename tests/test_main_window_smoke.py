"""
Cửa sổ chính thật (Qt offscreen) chạy trong TIẾN TRÌNH RIÊNG: có nhiều QThread nền nên dùng os._exit để thoát
sạch, và để một lỗi của GUI không kéo sập cả bộ test.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r'''
import json, os, sys, time
sys.path.insert(0, ROOT)
from PyQt6.QtWidgets import QApplication, QPushButton, QCheckBox
app = QApplication([])
import main as M
win = M.CyberCleanApp()
win.resize(1280, 800); win.show()
def pump(n=10):
    for _ in range(n): app.processEvents(); time.sleep(0.02)
pump()
out = {}
out["nav"] = [pid for pid, _, _ in win.NAV_ITEMS]
out["stack_count"] = win.stack.count()
out["pages"] = [win.stack.widget(i).__class__.__name__ for i in range(win.stack.count())]
win._nav("clean"); pump()
clean_page = win.stack.currentWidget()
out["clean_checkboxes"] = sorted(win.target_checks)
out["clean_selected"] = sorted(win.selected)
out["clean_has_review_button"] = any(b.text().strip().startswith(("REVIEW", "XEM LẠI")) for b in clean_page.findChildren(QPushButton))
out["clean_more_ways_buttons"] = [win._more_deep_btn.text(), win._more_adv_btn.text()]
win._more_deep_btn.click(); pump()
out["deep_via_hint"] = win.stack.currentWidget().__class__.__name__
win._nav("advisor"); pump()
out["advisor_page"] = win.stack.currentWidget().__class__.__name__
win._nav("deep"); pump()
dp = win.deep_page
out["deep_cards"] = sorted(dp._cards)
out["deep_preticked"] = [i for i in range(dp.panel._table.rowCount())]
out["deep_scanned_on_open"] = any(c._kind != "idle" for c in dp._cards.values())
win._nav("uninstall"); pump(); win._nav("log"); pump(); win._nav("dashboard"); pump()
out["ok"] = True
print("RESULT:" + json.dumps(out))
sys.stdout.flush()
os._exit(0)
'''


def test_main_window_has_three_tier_pages_and_clean_is_auto_only(tmp_path):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1",
           "XDG_CONFIG_HOME": str(tmp_path / ".config"), "XDG_CACHE_HOME": str(tmp_path / ".cache")}
    r = subprocess.run([sys.executable, "-c", SCRIPT.replace("ROOT", repr(str(ROOT)), 1)], capture_output=True, text=True,
                       env=env, timeout=180)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT:")), None)
    assert line, f"cửa sổ chính không khởi động được:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}"
    d = json.loads(line[7:])
    assert d["ok"]
    assert d["nav"][:4] == ["dashboard", "clean", "deep", "advisor"]
    assert d["stack_count"] == len(d["nav"]), "mỗi mục sidebar phải có đúng một trang"
    assert d["pages"][2:4] == ["DeepCleanPage", "AdvisorPage"]
    # trang Dọn rác chỉ còn tầng AUTO: không có REVIEW (mục review không có checkbox, không có nút REVIEW)
    assert not {"empty_trash", "dev_cache", "app_cache", "docker", "flatpak", "orphaned_pkgs"} & set(d["clean_checkboxes"])
    assert d["clean_selected"] == d["clean_checkboxes"]
    assert d["clean_has_review_button"] is False
    assert len(d["clean_more_ways_buttons"]) == 2
    assert d["deep_via_hint"] == "DeepCleanPage" and d["advisor_page"] == "AdvisorPage"
    assert "empty_trash" in d["deep_cards"] and "dev_cache" in d["deep_cards"]
    assert d["deep_scanned_on_open"] is False, "mở trang Dọn sâu không được tự quét đĩa"
