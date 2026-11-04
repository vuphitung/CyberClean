"""Guards against untranslated UI strings (raw keys such as 'adv_win_old' showing up in the English UI)."""
import glob
import re
from pathlib import Path

from utils.i18n import TRANSLATIONS

ROOT = Path(__file__).resolve().parent.parent
# tgt_<id>_name/_desc and rn_<rule> intentionally fall back to the English text in rules/*.toml.
# upd_err_hash is dynamic: its "translation" is the verifier's own message.
FALLBACK_PREFIXES = ("tgt_", "rn_")
DYNAMIC = {"rn_", "upd_err_hash"}


def _placeholders(text):
    return set(re.findall(r"\{(\w+)\}", text))


def test_advisor_keys_exist_in_english():
    en = TRANSLATIONS["en"]
    missing = [k for k in TRANSLATIONS["vi"] if k.startswith("adv_") and k not in en]
    assert not missing, f"adv_ keys present in vi but missing in en: {missing}"


def test_every_non_fallback_vi_key_has_english():
    en = TRANSLATIONS["en"]
    missing = [k for k in TRANSLATIONS["vi"]
               if not k.startswith(FALLBACK_PREFIXES) and k not in en]
    assert not missing, f"keys missing in en: {missing}"


def test_placeholders_match_between_languages():
    en, vi = TRANSLATIONS["en"], TRANSLATIONS["vi"]
    bad = [k for k in en if k in vi and _placeholders(en[k]) != _placeholders(vi[k])]
    assert not bad, f"placeholder mismatch between en and vi: {bad}"


def test_literal_keys_used_in_code_exist_in_both_languages():
    pat = re.compile(r"""\b_?t\(\s*(['"])([A-Za-z0-9_.\-]+)\1""")
    files = ["main.py", "ui_widgets.py", "ui_pages.py"] + glob.glob("core/*.py") + glob.glob("utils/*.py")
    used = set()
    for f in files:
        used |= {m.group(2) for m in pat.finditer((ROOT / f).read_text(encoding="utf-8"))}
    used = {k for k in used if k not in DYNAMIC and not k.startswith(FALLBACK_PREFIXES)}
    for lang in ("en", "vi"):
        missing = sorted(k for k in used if k not in TRANSLATIONS[lang])
        assert not missing, f"keys used in code but missing in {lang}: {missing}"
