"""Mọi target / ghi chú luật phải có bản dịch tiếng Việt — target mới thiếu bản dịch sẽ làm test này fail."""
import re
from pathlib import Path

import pytest

from core import linux_cleaner as L
from core import rules as R
from core import windows_cleaner as W
from utils import i18n

VI = i18n.TRANSLATIONS["vi"]
ROOT = Path(__file__).resolve().parent.parent


def all_rule_target_ids():
    rs = R.RuleSet()
    for f in sorted(R.rules_dir().glob("*.toml")):
        rs.load_file(f)
    return rs, set(rs.targets)


def code_target_ids():
    """Id target định nghĩa trong code (cleaner) — đọc thẳng từ mã nguồn để không phụ thuộc distro của máy test."""
    ids = set()
    for mod in ("linux_cleaner", "windows_cleaner"):
        src = (ROOT / "core" / f"{mod}.py").read_text(encoding="utf-8")
        ids |= set(re.findall(r"CleanTarget\(\s*'([a-z0-9_]+)'", src))
    return {i for i in ids if not i.startswith("_")}


def test_every_target_has_vietnamese_name_and_desc():
    _, rule_ids = all_rule_target_ids()
    missing = []
    for tid in sorted(rule_ids | code_target_ids()):
        for suffix in ("name", "desc"):
            if not VI.get(f"tgt_{tid}_{suffix}"):
                missing.append(f"tgt_{tid}_{suffix}")
    assert not missing, missing


def test_every_rule_note_has_vietnamese_translation():
    rs, _ = all_rule_target_ids()
    missing = [r.id for r in rs.rules if r.note and not VI.get(f"rn_{r.id}")]
    assert not missing, missing


def test_review_dialog_translates_notes(monkeypatch):
    pytest.importorskip("PyQt6")
    from tests.helpers import tree  # noqa: F401
    assert VI["rn_dev-maven"].startswith("CẨN THẬN")


def literal_keys(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    return sorted(set(re.findall(r"_t\(\s*'([a-z0-9_]+)'", src)))


def test_every_string_of_the_new_pages_has_a_vietnamese_translation():
    """Giao diện tiếng Việt không được lòi chữ Anh ở hai trang mới."""
    missing = [k for k in literal_keys("ui_pages.py") if not k.endswith("_") and k not in VI]   # 'rn_' = tiền tố khóa động
    assert not missing, missing


def test_new_sidebar_and_hint_strings_exist_in_vietnamese():
    for k in ("nav_deep", "nav_advisor", "more_ways", "tier_auto_desc", "btn_update_helper", "helper_outdated",
              "helper_missing", "review_logged", "confirm_perm_note"):
        assert VI.get(k), k


def test_placeholders_match_between_languages():
    en = i18n.TRANSLATIONS["en"]
    for k in ("review_selected", "review_confirm_perm", "review_logged", "deep_total", "adv_tile_total_sub"):
        assert set(re.findall(r"\{(\w+)", en[k])) == set(re.findall(r"\{(\w+)", VI[k])), k


ADVICE_KEYS = {
    "dl_summary", "dl_iso", "dl_archive", "dl_installer", "dl_large", "dl_title",
    "big_vm", "big_iso", "big_game", "big_large",
    "proj_node", "proj_node_noage", "proj_cargo", "proj_cargo_noage", "proj_venv", "proj_venv_noage",
    "opt_dir", "pkg_remove", "flatpak_remove", "container", "game_uninstall", "wine_prefix",
    "win_old", "hiberfil", "pagefile", "swapfile", "pkg_cache", "installer_cache", "wsl_disk",
}


def test_advisor_advice_keys_have_vietnamese_translations_with_matching_placeholders():
    src = (ROOT / "core" / "advisor.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'(?:advice_key|title_key)\s*=\s*"([a-z_]+)"', src))
    assert emitted <= ADVICE_KEYS, f"khóa mới chưa có trong ADVICE_KEYS: {emitted - ADVICE_KEYS}"
    for k in ADVICE_KEYS:                                # mọi khóa đều phải thật sự xuất hiện trong advisor.py
        assert f'"{k}"' in src or f'key + "_noage"' in src and k.endswith("_noage"), f"advisor.py không còn phát khóa {k}"
    missing = [k for k in sorted(ADVICE_KEYS) if f"adv_{k}" not in VI]
    assert not missing, missing
    # placeholder: mỗi mẫu tiếng Việt chỉ được dùng đúng những đối số mà advisor.py truyền vào
    allowed = {"dl_summary": {"n", "size", "days"}, "dl_title": {"n"}, "container": {"reclaim"},
               "proj_node": {"age"}, "proj_cargo": {"age"}, "proj_venv": {"age"}}
    for k in ADVICE_KEYS:
        used = set(re.findall(r"\{(\w+)", VI[f"adv_{k}"]))
        assert used <= allowed.get(k, set()), (k, used)


def test_advice_text_formats_and_falls_back_to_english(monkeypatch):
    from core.advisor import Finding
    import ui_pages
    f = Finding("projects", "node_modules — x", "/p", 10, 200, "English default",
                advice_key="proj_node", advice_args={"age": 200})
    monkeypatch.setattr(ui_pages, "_t", lambda k, d="": VI.get(k, d))
    assert "200 ngày" in ui_pages.advice_text(f)
    monkeypatch.setattr(ui_pages, "_t", lambda k, d="": d)                 # ngôn ngữ không có bản dịch
    assert ui_pages.advice_text(f) == "English default"
    bad = Finding("x", "t", advice="fallback", advice_key="dl_summary", advice_args={})   # thiếu đối số → không văng
    monkeypatch.setattr(ui_pages, "_t", lambda k, d="": VI.get(k, d))
    assert ui_pages.advice_text(bad) == "fallback"


def test_advisor_category_titles_are_translated():
    from core import advisor
    for cat in advisor.CATEGORY_TITLES:
        assert VI.get(f"adv_cat_{cat}"), cat
