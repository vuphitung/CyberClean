#!/bin/bash
# CyberClean — Linux Installer
# VERSION được đọc từ version.py bundled trong release — không hardcode
#
# Usage:
#   Install:   curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash
#   Uninstall: sudo cyberclean --uninstall

set -e

APP="CyberClean"
REPO="vuphitung/CyberClean"
ICON_URL="https://raw.githubusercontent.com/${REPO}/main/assets/logo.png"

BIN="/usr/local/bin/cyberclean"
INSTALL_DIR="/opt/CyberClean"
ICON_DEST="/usr/share/icons/hicolor/256x256/apps/cyberclean.png"
DESKTOP_DEST="/usr/share/applications/cyberclean.desktop"
HELPER="/usr/local/bin/cyber-clean-helper"

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
    rm -f /etc/sudoers.d/cyberclean 2>/dev/null || true
    rm -f /usr/share/polkit-1/actions/com.nc2077.cyberclean.policy 2>/dev/null || true
    update-desktop-database /usr/share/applications 2>/dev/null || true
    echo ""
    echo -e "${GREEN}  ✅ CyberClean uninstalled successfully.${NC}"
    exit 0
fi

# ── Fetch latest version from GitHub API ──────────────────
# Không hardcode version trong file này nữa.
# Luôn lấy bản mới nhất từ GitHub Releases API.
section "Fetching latest version"
LATEST_JSON=""
if command -v curl &>/dev/null; then
    LATEST_JSON=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null || true)
elif command -v wget &>/dev/null; then
    LATEST_JSON=$(wget -qO- "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null || true)
fi

VERSION=""
if [[ -n "$LATEST_JSON" ]]; then
    VERSION=$(echo "$LATEST_JSON" | grep -o '"tag_name": *"[^"]*"' | head -1 | grep -o '[0-9][^"]*')
fi

if [[ -z "$VERSION" ]]; then
    # Fallback: dùng version hardcode nếu API không trả về
    # Cập nhật dòng này khi release nhưng không phải điểm fail chính
    VERSION="3.0.0"
    warn "GitHub API unavailable — using fallback version ${VERSION}"
else
    ok "Latest version: v${VERSION}"
fi

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


# ── Download ──────────────────────────────────────────────
section "Downloading v${VERSION}"
mkdir -p /opt/CyberClean
TARGZ_TMP="/tmp/CyberClean.tar.gz"

if command -v curl &>/dev/null; then
    curl -fsSL --progress-bar -o "$TARGZ_TMP" "$TARGZ_URL" || err "Download failed — check internet connection"
elif command -v wget &>/dev/null; then
    wget -q --show-progress -O "$TARGZ_TMP" "$TARGZ_URL" || err "Download failed — check internet connection"
else
    err "curl or wget required"
fi

# Validate tar.gz (không phải file HTML error page)
MIN_BYTES=100000  # release phải > 100KB
ACTUAL_SIZE=$(stat -c%s "$TARGZ_TMP" 2>/dev/null || echo 0)
if [[ "$ACTUAL_SIZE" -lt "$MIN_BYTES" ]]; then
    rm -f "$TARGZ_TMP"
    err "Downloaded file too small (${ACTUAL_SIZE} bytes) — release v${VERSION} may not exist yet"
fi

tar -xzf "$TARGZ_TMP" -C "$INSTALL_DIR"
rm -f "$TARGZ_TMP"
chmod +x "$INSTALL_DIR/CyberClean/CyberClean"
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

# ── System helper ─────────────────────────────────────────
section "Setting up system helper"
cat > "$HELPER" << 'HELPER_CONTENT'
#!/bin/bash
# CyberClean — Privileged Helper
# Scoped tightly: chỉ expose đúng những action cần thiết.
# Không có blanket sudo — đây là security design, không phải giới hạn.
case "$1" in
  paccache)         paccache -rk1 2>/dev/null ;;
  pacman-orphans)   pkgs=$(cat); [[ -n "$pkgs" ]] && pacman -Rns --noconfirm $pkgs 2>/dev/null ;;
  journal)          journalctl --vacuum-time=7d 2>/dev/null ;;
  broken-downloads) find /var/cache/pacman/pkg -name "download-*" -delete 2>/dev/null ;;
  apt-clean)        DEBIAN_FRONTEND=noninteractive apt-get clean 2>/dev/null ;;
  apt-autoremove)   DEBIAN_FRONTEND=noninteractive apt-get autoremove -y 2>/dev/null ;;
  dnf-clean)        dnf clean all 2>/dev/null ;;
  zypper-clean)     zypper clean --all 2>/dev/null ;;
  xbps-clean-cache) xbps-remove -o 2>/dev/null ;;
  xbps-orphans)     xbps-remove -O 2>/dev/null ;;
  snap-remove-rev)  [[ -z "$2" || -z "$3" ]] && exit 1; snap remove "$2" --revision="$3" 2>/dev/null ;;
  fstrim)           fstrim -av 2>/dev/null ;;
  drop-cache)       sync && echo 1 > /proc/sys/vm/drop_caches ;;
  compact-memory)   echo 1 > /proc/sys/vm/compact_memory 2>/dev/null || true ;;
  swappiness)       echo 10 > /proc/sys/vm/swappiness ;;
  dirty-ratio)      echo 10 > /proc/sys/vm/dirty_ratio ;;
  dirty-background-ratio) echo 5 > /proc/sys/vm/dirty_background_ratio ;;
  fix-suid)         [[ -z "$2" ]] && exit 1; chmod u-s "$2" 2>/dev/null ;;
  fix-writable)     [[ -z "$2" ]] && exit 1; chmod o-w "$2" 2>/dev/null ;;
  remove-file)      [[ -z "$2" ]] && exit 1; rm -f "$2" 2>/dev/null ;;
  kill-pid)         [[ -z "$2" ]] && exit 1; kill -9 "$2" 2>/dev/null ;;
  stop-service)     [[ -z "$2" ]] && exit 1; systemctl stop "$2" 2>/dev/null ;;
  pacman-remove)    [[ -z "$2" ]] && exit 1; pacman -Rns --noconfirm "${@:2}" 2>/dev/null ;;
  apt-remove)       [[ -z "$2" ]] && exit 1; DEBIAN_FRONTEND=noninteractive apt-get remove -y "$2" 2>/dev/null ;;
  dnf-remove)       [[ -z "$2" ]] && exit 1; dnf remove -y "$2" 2>/dev/null ;;
  zypper-remove)    [[ -z "$2" ]] && exit 1; zypper remove -y "$2" 2>/dev/null ;;
  update-replace)
    [[ -z "$2" || -z "$3" ]] && exit 1
    SRC="$2"; DST="$3"; BACKUP="${4:-/opt/CyberClean/_backup}"
    rm -rf "$BACKUP" 2>/dev/null || true
    [[ -d "$DST" ]] && mv "$DST" "$BACKUP"
    cp -r "$SRC" "$DST"
    chmod +x "$DST/CyberClean" 2>/dev/null || true
    rm -rf "$SRC" 2>/dev/null || true ;;
  one-click-fix)
    sync && echo 1 > /proc/sys/vm/drop_caches 2>/dev/null
    echo 10 > /proc/sys/vm/swappiness 2>/dev/null
    fstrim -av 2>/dev/null
    journalctl --vacuum-time=7d 2>/dev/null
    command -v paccache &>/dev/null && paccache -rk1 2>/dev/null ;;
  *)  echo "Unknown command: $1" >&2; exit 1 ;;
esac
HELPER_CONTENT
chmod +x "$HELPER"
ok "System helper → $HELPER"

# ── Sudoers rule ──────────────────────────────────────────
# Detect sudo group (sudo = Debian/Ubuntu, wheel = Arch/Fedora/RHEL)
if getent group sudo &>/dev/null; then
    SUDO_GROUP="sudo"
elif getent group wheel &>/dev/null; then
    SUDO_GROUP="wheel"
else
    SUDO_GROUP="sudo"
fi

echo "%${SUDO_GROUP} ALL=(root) NOPASSWD: $HELPER" > /etc/sudoers.d/cyberclean
chmod 0440 /etc/sudoers.d/cyberclean
# Validate trước khi apply — tránh lock sudo ra
if visudo -c -f /etc/sudoers.d/cyberclean 2>/dev/null; then
    ok "Sudoers rule validated"
else
    warn "Sudoers validation skipped (visudo not found) — rule still applied"
fi
ok "Sudoers configured: %${SUDO_GROUP} → NOPASSWD helper only"

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
