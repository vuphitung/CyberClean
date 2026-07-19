# ─────────────────────────────────────────────────────────────
# CyberClean — Version Definition (SINGLE SOURCE OF TRUTH)
# ─────────────────────────────────────────────────────────────
# CHỈ SỬA FILE NÀY khi release version mới.
# Mọi file khác (main.py, build.py, install.sh) đều đọc từ đây.
# ─────────────────────────────────────────────────────────────

__version__ = "3.0.2"
__build__   = "stable"   # "stable" | "beta" | "nightly"


def parse_version_tuple(ver: str) -> tuple:
    """
    Parse tag or version string to a numeric tuple for ordering.
    Strips leading 'v', ignores pre-release suffix on first non-digit run
    (e.g. '2.3.0-beta' -> (2, 3, 0)).
    """
    s = (ver or "").strip().lstrip("v")
    parts: list = []
    for segment in s.split("."):
        num = ""
        for c in segment:
            if c.isdigit():
                num += c
            else:
                break
        if num:
            parts.append(int(num))
        else:
            break
    return tuple(parts) if parts else (0,)


def version_is_newer(remote: str, current: str) -> bool:
    """True if remote version is strictly greater than current (semver-style tuple compare)."""
    return parse_version_tuple(remote) > parse_version_tuple(current)


# Tuple để so sánh đúng — dùng cùng parser với GitHub tag
VERSION_TUPLE = parse_version_tuple(__version__)
