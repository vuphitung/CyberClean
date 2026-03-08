#!/bin/bash
# ============================================================
# CyberClean — Installer
# Smart Disk Cleaner for Arch Linux
# Usage: bash install.sh
# ============================================================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

echo -e "${CYAN}"
echo -e "  ██████╗██╗   ██╗██████╗ ███████╗██████╗      ██████╗██╗     ███████╗ █████╗ ███╗  "
echo -e " ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║     ██╔════╝██╔══██╗████╗ "
echo -e " ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝    ██║     ██║     █████╗  ███████║██╔██╗"
echo -e " ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗    ██║     ██║     ██╔══╝  ██╔══██║██║╚██"
echo -e " ╚██████╗   ██║   ██████╔╝███████╗██║  ██║    ╚██████╗███████╗███████╗██║  ██║██║ ╚█"
echo -e "  ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  "
echo -e "${NC}"
echo -e "${BLUE}  Smart Disk Cleaner for Arch Linux${NC}"
echo -e "${BLUE}  Source: $APP_DIR${NC}"
echo ""

# ── 1. Dependencies ────────────────────────────────────────
echo -e "${BLUE}━━━ Installing dependencies ━━━━━━━━━━━━━━━━━${NC}"
sudo pacman -S --needed --noconfirm python-pyqt6 polkit pacman-contrib 2>/dev/null \
    && echo -e "  ${GREEN}✅ python-pyqt6, polkit, pacman-contrib${NC}" \
    || echo -e "  ${RED}❌ Some packages failed — install manually${NC}"

# ── 2. Privileged helper ───────────────────────────────────
echo ""
echo -e "${BLUE}━━━ Setting up privileged helper ━━━━━━━━━━━━${NC}"
sudo tee /usr/local/bin/cyber-clean-helper > /dev/null << 'HELPER'
#!/bin/bash
# CyberClean privileged helper — called via pkexec
case "$1" in
  paccache)
    paccache -rk1 2>/dev/null
    ;;
  pacman-orphans)
    pkgs=$(cat)
    [[ -n "$pkgs" ]] && pacman -Rns --noconfirm $pkgs 2>/dev/null
    ;;
  journal)
    journalctl --vacuum-time=7d 2>/dev/null
    ;;
  broken-downloads)
    find /var/cache/pacman/pkg -name "download-*" -delete 2>/dev/null
    ;;
esac
HELPER
sudo chmod +x /usr/local/bin/cyber-clean-helper
echo -e "  ${GREEN}✅ /usr/local/bin/cyber-clean-helper${NC}"

# ── 3. Polkit policy ───────────────────────────────────────
echo ""
echo -e "${BLUE}━━━ Registering polkit policy ━━━━━━━━━━━━━━━${NC}"
sudo tee /usr/share/polkit-1/actions/com.nc2077.cyberclean.policy > /dev/null << 'POLICY'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <vendor>CyberClean</vendor>
  <vendor_url>https://github.com/vuphitung/CyberClean</vendor_url>
  <action id="com.nc2077.cyberclean.run">
    <description>CyberClean System Maintenance</description>
    <message>CyberClean needs administrator privileges to clean package cache and journal logs.</message>
    <icon_name>system-software-update</icon_name>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/local/bin/cyber-clean-helper</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
POLICY
echo -e "  ${GREEN}✅ Polkit policy registered${NC}"

# ── 4. Desktop entry ───────────────────────────────────────
echo ""
echo -e "${BLUE}━━━ Creating desktop entry ━━━━━━━━━━━━━━━━━━${NC}"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/cyber-clean.desktop" << DESKTOP
[Desktop Entry]
Name=Cyber-Clean
GenericName=Disk Cleaner
Comment=Smart Disk Cleaner for Arch Linux
Exec=python3 $APP_DIR/cyber-clean-app.py
Icon=system-software-update
Terminal=false
Type=Application
Categories=System;Utility;
Keywords=disk;clean;cache;pacman;arch;
StartupNotify=true
DESKTOP
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo -e "  ${GREEN}✅ Desktop entry: Cyber-Clean${NC}"

# ── 5. systemd auto-clean timer ────────────────────────────
echo ""
echo -e "${BLUE}━━━ Setting up auto-clean timer ━━━━━━━━━━━━━${NC}"
SYSTEMD_USER="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER"
cp "$APP_DIR/eww-clean.service" "$SYSTEMD_USER/" 2>/dev/null
cp "$APP_DIR/eww-clean.timer"   "$SYSTEMD_USER/" 2>/dev/null
systemctl --user daemon-reload 2>/dev/null
systemctl --user enable --now eww-clean.timer 2>/dev/null \
    && echo -e "  ${GREEN}✅ Timer active — runs every 6h (disk > 75% only)${NC}" \
    || echo -e "  ${YELLOW}⚠️  Timer setup skipped (no systemd user session?)${NC}"

# ── Done ───────────────────────────────────────────────────
echo ""
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ CyberClean installed successfully!${NC}"
echo ""
echo -e "${BLUE}  Run the app:${NC}"
echo -e "     python3 $APP_DIR/cyber-clean-app.py"
echo -e ""
echo -e "${BLUE}  Or find 'Cyber-Clean' in your app launcher${NC}"
echo -e ""
echo -e "${BLUE}  Suggested keybind (Hyprland):${NC}"
echo -e "     bind = \$mainMod, X, exec, python3 $APP_DIR/cyber-clean-app.py"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
