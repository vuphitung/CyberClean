# ─────────────────────────────────────────────────────────────
# CyberClean — Version Definition (SINGLE SOURCE OF TRUTH)
# ─────────────────────────────────────────────────────────────
# CHỈ SỬA FILE NÀY khi release version mới.
# Mọi file khác (main.py, build.py, install.sh) đều đọc từ đây.
# ─────────────────────────────────────────────────────────────

__version__ = "2.2.1"
__build__   = "stable"   # "stable" | "beta" | "nightly"

# Tuple để so sánh đúng: (2, 10, 0) > (2, 9, 0)
# String compare sẽ sai: "2.10.0" < "2.9.0" theo lexicographic
VERSION_TUPLE = tuple(int(x) for x in __version__.split("."))
