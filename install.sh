#!/bin/bash
# CyberClean v2.0 — Installer
# Usage:
#   Install:   curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash
#   Uninstall: sudo cyberclean --uninstall

set -e

VERSION="2.0.0"
APP="CyberClean"
REPO="vuphitung/CyberClean"
TARGZ_URL="https://github.com/${REPO}/releases/download/v${VERSION}/CyberClean-${VERSION}-linux-x86_64.tar.gz"
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
head() { echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }

if [[ $EUID -ne 0 ]]; then
    err "Run with sudo:  curl -sSL https://raw.githubusercontent.com/${REPO}/main/install.sh | sudo bash"
fi

if [[ "$1" == "--uninstall" ]]; then
    head "Uninstalling CyberClean"
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

echo -e "${CYAN}"
echo "  ██████╗██╗   ██╗██████╗ ███████╗██████╗      ██████╗██╗     ███████╗ █████╗ ███╗"
echo " ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║     ██╔════╝██╔══██╗████╗"
echo " ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝    ██║     ██║     █████╗  ███████║██╔██╗"
echo " ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗    ██║     ██║     ██╔══╝  ██╔══██║██║╚██"
echo " ╚██████╗   ██║   ██████╔╝███████╗██║  ██║    ╚██████╗███████╗███████╗██║  ██║██║ ╚█"
echo "  ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝"
echo -e "${NC}"
echo -e "${CYAN}  Smart Disk Cleaner v${VERSION} — Installing...${NC}\n"

head "Downloading"
mkdir -p /opt/CyberClean
TARGZ_TMP="/tmp/CyberClean.tar.gz"
if command -v curl &>/dev/null; then
    curl -fsSL --progress-bar -o "$TARGZ_TMP" "$TARGZ_URL" || err "Download failed — check internet connection"
elif command -v wget &>/dev/null; then
    wget -q --show-progress -O "$TARGZ_TMP" "$TARGZ_URL" || err "Download failed — check internet connection"
else
    err "curl or wget required"
fi
tar -xzf "$TARGZ_TMP" -C "$INSTALL_DIR"
rm -f "$TARGZ_TMP"
chmod +x "$INSTALL_DIR/CyberClean/CyberClean"
ok "Installed → $INSTALL_DIR"

head "Creating command"
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

head "Installing icon"
mkdir -p "$(dirname $ICON_DEST)"
if command -v curl &>/dev/null; then
    curl -fsSL -o "$ICON_DEST" "$ICON_URL" 2>/dev/null && ok "Icon installed" || warn "Icon skipped"
else
    wget -q -O "$ICON_DEST" "$ICON_URL" 2>/dev/null && ok "Icon installed" || warn "Icon skipped"
fi
gtk-update-icon-cache /usr/share/icons/hicolor 2>/dev/null || true

head "Registering app"
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
Keywords=disk;clean;cache;
StartupNotify=true
DESKTOP
update-desktop-database /usr/share/applications 2>/dev/null || true
ok "App registered in launcher"

head "Setting up system helper"
cat > "$HELPER" << 'HELPER_CONTENT'
#!/bin/bash
case "$1" in
  paccache)         paccache -rk1 2>/dev/null ;;
  pacman-orphans)   pkgs=$(cat); [[ -n "$pkgs" ]] && pacman -Rns --noconfirm $pkgs 2>/dev/null ;;
  journal)          journalctl --vacuum-time=7d 2>/dev/null ;;
  broken-downloads) find /var/cache/pacman/pkg -name "download-*" -delete 2>/dev/null ;;
  apt-clean)        apt-get clean 2>/dev/null ;;
  apt-autoremove)   apt-get autoremove -y 2>/dev/null ;;
  dnf-clean)        dnf clean all 2>/dev/null ;;
  zypper-clean)     zypper clean --all 2>/dev/null ;;
  fstrim)           fstrim -av 2>/dev/null ;;
  drop-cache)       sync && echo 1 > /proc/sys/vm/drop_caches ;;
  compact-memory)   echo 1 > /proc/sys/vm/compact_memory ;;
  swappiness)       echo 10 > /proc/sys/vm/swappiness ;;
  optimizer)
    sync && echo 1 > /proc/sys/vm/drop_caches 2>/dev/null
    echo 10 > /proc/sys/vm/swappiness 2>/dev/null
    fstrim -av 2>/dev/null ;;
  fix-suid)         [[ -z "$2" ]] && exit 1; chmod u-s "$2" 2>/dev/null ;;
  fix-writable)     [[ -z "$2" ]] && exit 1; chmod o-w "$2" 2>/dev/null ;;
  remove-file)      [[ -z "$2" ]] && exit 1; rm -f "$2" 2>/dev/null ;;
  kill-pid)         [[ -z "$2" ]] && exit 1; kill -9 "$2" 2>/dev/null ;;
  stop-service)     [[ -z "$2" ]] && exit 1; systemctl stop "$2" 2>/dev/null ;;
  pacman-remove)    [[ -z "$2" ]] && exit 1; pacman -Rns --noconfirm "${@:2}" 2>/dev/null ;;
  apt-remove)       [[ -z "$2" ]] && exit 1; apt-get remove -y "$2" 2>/dev/null ;;
  dnf-remove)       [[ -z "$2" ]] && exit 1; dnf remove -y "$2" 2>/dev/null ;;
  one-click-fix)
    sync && echo 1 > /proc/sys/vm/drop_caches 2>/dev/null
    echo 10 > /proc/sys/vm/swappiness 2>/dev/null
    fstrim -av 2>/dev/null
    journalctl --vacuum-time=7d 2>/dev/null
    command -v paccache &>/dev/null && paccache -rk1 2>/dev/null ;;
  *)  echo "Unknown: $1" >&2; exit 1 ;;
esac
HELPER_CONTENT
chmod +x "$HELPER"
ok "System helper → $HELPER"

echo "ALL ALL=(root) NOPASSWD: $HELPER" > /etc/sudoers.d/cyberclean
chmod 440 /etc/sudoers.d/cyberclean
ok "Sudoers rule configured"

echo ""
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ CyberClean v${VERSION} installed!${NC}"
echo ""
echo -e "  ${CYAN}Launch:${NC}    cyberclean"
echo -e "  ${CYAN}Or find:${NC}   'CyberClean' in your app launcher"
echo -e "  ${CYAN}Uninstall:${NC} sudo cyberclean --uninstall"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo ""
