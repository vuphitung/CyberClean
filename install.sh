#!/bin/bash
# CyberClean — Linux Installer
# VERSION được đọc từ version.py bundled trong release — không hardcode
#
# Usage:
#   Install:   curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash
#   Uninstall: sudo cyberclean --uninstall

set -e
set -o pipefail
umask 022

APP="CyberClean"
REPO="vuphitung/CyberClean"
ICON_URL="https://raw.githubusercontent.com/${REPO}/main/assets/logo.png"

BIN="/usr/local/bin/cyberclean"
INSTALL_DIR="/opt/CyberClean"
ICON_DEST="/usr/share/icons/hicolor/256x256/apps/cyberclean.png"
DESKTOP_DEST="/usr/share/applications/cyberclean.desktop"
HELPER="/usr/local/bin/cyber-clean-helper"
SUDOERS_FILE="/etc/sudoers.d/cyberclean"

# Khóa công khai Ed25519 của release — PHẢI khớp CYBERCLEAN_PUBLIC_KEY_B64 trong utils/updater.py
# và RELEASE_PUBKEY_PEM trong packaging/cyber-clean-helper (tests/test_helper.py kiểm tra cả ba).
read -r -d '' RELEASE_PUBKEY_PEM <<'PEM' || true
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA0HIxLhJ7mZ31Bv7p6t1DK8gGC4/eyS6myJNYz9LYms0=
-----END PUBLIC KEY-----
PEM

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RED='\033[0;31m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "  ${RED}✗${NC}  $1"; exit 1; }
section() { echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }

if [[ $EUID -ne 0 ]]; then
    err "Run with sudo:  curl -sSL https://raw.githubusercontent.com/${REPO}/main/install.sh | sudo bash"
fi

# ── Uninstall ─────────────────────────────────────────────
if [[ "$1" == "--uninstall" ]]; then
    section "Uninstalling CyberClean"
    rm -f "$BIN"           && ok "Removed $BIN"
    rm -rf /opt/CyberClean && ok "Removed /opt/CyberClean"
    rm -f "$ICON_DEST"     2>/dev/null || true
    rm -f "$DESKTOP_DEST"  && ok "Removed desktop entry"
    rm -f "$HELPER"        2>/dev/null || true
    rm -f "$SUDOERS_FILE" 2>/dev/null || true
    rm -f /usr/share/polkit-1/actions/com.nc2077.cyberclean.policy 2>/dev/null || true
    update-desktop-database /usr/share/applications 2>/dev/null || true
    echo ""
    echo -e "${GREEN}  ✅ CyberClean uninstalled successfully.${NC}"
    exit 0
fi

# ── Fetch latest version from GitHub API ──────────────────
# Không hardcode version. Có thể ghim bản cụ thể:  CYBERCLEAN_VERSION=3.1.0 ... | sudo -E bash
section "Fetching latest version"
VERSION="${CYBERCLEAN_VERSION:-}"
if [[ -z "$VERSION" ]]; then
    LATEST_JSON=""
    if command -v curl &>/dev/null; then
        LATEST_JSON=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null || true)
    elif command -v wget &>/dev/null; then
        LATEST_JSON=$(wget -qO- "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null || true)
    fi
    if [[ -n "$LATEST_JSON" ]]; then
        VERSION=$(echo "$LATEST_JSON" | grep -o '"tag_name": *"[^"]*"' | head -1 | grep -o '[0-9][^"]*' || true)
    fi
fi
# Chỉ nhận dạng x.y.z[-suffix] — giá trị này được ghép vào URL và đường dẫn
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)?$ ]]; then
    err "Could not determine the latest version (GitHub API unavailable or rate-limited). Retry later, or pin one: CYBERCLEAN_VERSION=x.y.z"
fi
ok "Version: v${VERSION}"

TARGZ_URL="https://github.com/${REPO}/releases/download/v${VERSION}/CyberClean-${VERSION}-linux-x86_64.tar.gz"

# ── Banner ────────────────────────────────────────────────
echo -e "${CYAN}"
echo "  ██████╗██╗   ██╗██████╗ ███████╗██████╗      ██████╗██╗     ███████╗ █████╗ ███╗"
echo " ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║     ██╔════╝██╔══██╗████╗"
echo " ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝    ██║     ██║     █████╗  ███████║██╔██╗"
echo " ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗    ██║     ██║     ██╔══╝  ██╔══██║██║╚██"
echo " ╚██████╗   ██║   ██████╔╝███████╗██║  ██║    ╚██████╗███████╗███████╗██║  ██║██║ ╚█"
echo "  ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝"
echo -e "${NC}"
echo -e "${CYAN}  Smart Disk Cleaner v${VERSION} — Installing...${NC}\n"


# ── Download (thư mục tạm riêng, root-owned, tên ngẫu nhiên — không dùng đường dẫn cố định trong /tmp) ──
section "Downloading v${VERSION}"
WORK=$(mktemp -d /var/tmp/cyberclean-install.XXXXXXXX) || err "Cannot create a temporary directory"
trap 'rm -rf --one-file-system -- "$WORK"' EXIT
TARGZ_TMP="$WORK/CyberClean.tar.gz"
SIG_TMP="$WORK/CyberClean.tar.gz.sig"
SIG_URL="${TARGZ_URL}.sig"

fetch() {  # fetch URL DEST
    if command -v curl &>/dev/null; then
        curl -fsSL --proto '=https' --tlsv1.2 --retry 2 -o "$2" "$1"
    elif command -v wget &>/dev/null; then
        wget -q --https-only -O "$2" "$1"
    else
        err "curl or wget required"
    fi
}
fetch "$TARGZ_URL" "$TARGZ_TMP" || err "Download failed — check your connection, or release v${VERSION} may not exist"

ACTUAL_SIZE=$(stat -c%s "$TARGZ_TMP" 2>/dev/null || echo 0)
if [[ "$ACTUAL_SIZE" -lt 100000 ]]; then
    err "Downloaded file too small (${ACTUAL_SIZE} bytes) — release v${VERSION} may not exist yet"
fi

# ── Verify signature (Ed25519) — trước khi giải nén bất cứ thứ gì ─────────────────────
section "Verifying signature"
verified=0
if fetch "$SIG_URL" "$SIG_TMP" 2>/dev/null; then
    if command -v openssl &>/dev/null && openssl pkeyutl -help 2>&1 | grep -q -- '-rawin'; then
        printf '%s\n' "$RELEASE_PUBKEY_PEM" > "$WORK/pub.pem"
        tr -d ' \t\r\n' < "$SIG_TMP" | base64 -d > "$WORK/sig.bin" 2>/dev/null || err "Malformed signature file"
        [[ $(stat -c %s "$WORK/sig.bin") -eq 64 ]] || err "Signature must be 64 bytes"
        if openssl pkeyutl -verify -pubin -inkey "$WORK/pub.pem" -rawin -in "$TARGZ_TMP" \
               -sigfile "$WORK/sig.bin" >/dev/null 2>&1; then
            verified=1
            ok "Signature OK"
        else
            err "SIGNATURE INVALID — refusing to install (the download was corrupted or tampered with)"
        fi
    else
        warn "OpenSSL >= 3.0 is not available here, so the signature cannot be checked."
    fi
else
    warn "No signature published for v${VERSION}."
fi
if [[ $verified -ne 1 ]]; then
    if [[ "${CYBERCLEAN_INSECURE_SKIP_VERIFY:-}" == "1" ]]; then
        warn "CYBERCLEAN_INSECURE_SKIP_VERIFY=1 — installing an UNVERIFIED package."
    else
        err "Refusing to install an unverified package. Update OpenSSL (>= 3.0), or set CYBERCLEAN_INSECURE_SKIP_VERIFY=1 to override at your own risk."
    fi
fi

# ── Extract + validate + atomic swap ─────────────────────────────────────────────────
section "Installing"
mkdir -p "$WORK/x"
tar -xzf "$TARGZ_TMP" -C "$WORK/x" --no-same-owner || err "Cannot extract the archive"
NEW="$WORK/x/CyberClean"
[[ -d "$NEW" && ! -L "$NEW" && -f "$NEW/CyberClean" ]] || err "Unexpected archive layout"
[[ -f "$NEW/cyber-clean-helper" && ! -L "$NEW/cyber-clean-helper" ]] \
    || err "This release does not ship the privileged helper — use v3.1.0 or newer"
chown -R root:root "$WORK/x"
chmod -R go-w "$WORK/x"
find "$WORK/x" -perm /6000 -exec chmod u-s,g-s {} + 2>/dev/null || true
chmod +x "$NEW/CyberClean" "$NEW/cyber-clean-helper"

install -d -m 0755 -o root -g root "$INSTALL_DIR"
if [[ -e "$INSTALL_DIR/CyberClean" ]]; then
    rm -rf --one-file-system -- "$INSTALL_DIR/_old"
    mv -T -- "$INSTALL_DIR/CyberClean" "$INSTALL_DIR/_old"       # không trộn file cũ với file mới
fi
if ! mv -T -- "$NEW" "$INSTALL_DIR/CyberClean"; then
    [[ -e "$INSTALL_DIR/_old" ]] && mv -T -- "$INSTALL_DIR/_old" "$INSTALL_DIR/CyberClean"
    err "Install failed — previous version restored"
fi
rm -rf --one-file-system -- "$INSTALL_DIR/_old"
ok "Installed → $INSTALL_DIR"

# ── Create launcher command ───────────────────────────────
section "Creating command"
cat > "$BIN" << LAUNCHER
#!/bin/bash
if [[ "\$1" == "--uninstall" ]]; then
    curl -sSL https://raw.githubusercontent.com/${REPO}/main/install.sh | sudo bash -s -- --uninstall
else
    exec "$INSTALL_DIR/CyberClean/CyberClean" "\$@"
fi
LAUNCHER
chmod +x "$BIN"
ok "Command → cyberclean"

# ── Icon ──────────────────────────────────────────────────
section "Installing icon"
mkdir -p "$(dirname "$ICON_DEST")"
if command -v curl &>/dev/null; then
    curl -fsSL -o "$ICON_DEST" "$ICON_URL" 2>/dev/null && ok "Icon installed" || warn "Icon skipped (non-critical)"
else
    wget -q -O "$ICON_DEST" "$ICON_URL" 2>/dev/null && ok "Icon installed" || warn "Icon skipped (non-critical)"
fi
gtk-update-icon-cache /usr/share/icons/hicolor 2>/dev/null || true

# ── Desktop entry ─────────────────────────────────────────
section "Registering app"
cat > "$DESKTOP_DEST" << DESKTOP
[Desktop Entry]
Name=CyberClean
GenericName=Disk Cleaner
Comment=Smart Disk Cleaner v${VERSION}
Exec=${INSTALL_DIR}/CyberClean/CyberClean
Icon=cyberclean
Terminal=false
Type=Application
Categories=System;Utility;
Keywords=disk;clean;cache;optimizer;
StartupNotify=true
DESKTOP
update-desktop-database /usr/share/applications 2>/dev/null || true
ok "App registered in launcher"

# ── System helper + sudoers ───────────────────────────────
# Nguồn DUY NHẤT của helper là file nằm trong gói đã được ký (packaging/cyber-clean-helper).
# `install-helper` chỉ chạy được bằng root VÀ khi script nằm đúng trong $INSTALL_DIR/CyberClean
# (root-owned); nó cài helper vào $HELPER và ghi rule sudoers qua file tạm + `visudo -c`
# (rule hỏng không bao giờ được ghi vào /etc/sudoers.d — trước đây vẫn ghi rồi mới cảnh báo).
section "Setting up system helper"
if "$INSTALL_DIR/CyberClean/cyber-clean-helper" install-helper; then
    ok "System helper → $HELPER"
else
    warn "Could not set up the privileged helper — system targets (logs, package caches) will be unavailable."
fi
# Dọn polkit policy cũ (không còn dùng)
rm -f /usr/share/polkit-1/actions/com.nc2077.cyberclean.policy 2>/dev/null || true

# ── Done ──────────────────────────────────────────────────
echo ""
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ CyberClean v${VERSION} installed!${NC}"
echo ""
echo -e "  ${CYAN}Launch:${NC}    cyberclean"
echo -e "  ${CYAN}Or find:${NC}   'CyberClean' in your app launcher"
echo -e "  ${CYAN}Uninstall:${NC} sudo cyberclean --uninstall"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo ""
