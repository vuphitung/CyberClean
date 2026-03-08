#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  CyberClean v2.0 — Installer                                ║
# ║  Smart Disk Cleaner — Linux (all distros) + Windows         ║
# ║  Usage: bash install.sh                                     ║
# ╚══════════════════════════════════════════════════════════════╝

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RED='\033[0;31m'; NC='\033[0m'

APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

echo -e "${CYAN}"
echo "  ██████╗██╗   ██╗██████╗ ███████╗██████╗      ██████╗██╗     ███████╗ █████╗ ███╗"
echo " ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║     ██╔════╝██╔══██╗████╗"
echo " ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝    ██║     ██║     █████╗  ███████║██╔██╗"
echo " ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗    ██║     ██║     ██╔══╝  ██╔══██║██║╚██"
echo " ╚██████╗   ██║   ██████╔╝███████╗██║  ██║    ╚██████╗███████╗███████╗██║  ██║██║ ╚█"
echo "  ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝"
echo -e "${NC}"
echo -e "${CYAN}  Smart Disk Cleaner v2.0${NC}"
echo -e "${CYAN}  Source: $APP_DIR${NC}"
echo ""

ok()   { echo -e "  ${GREEN}✓${NC}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "  ${RED}✗${NC}  $1"; }
head() { echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }

# ── 1. Xóa phiên bản cũ nếu có ───────────────────────────────
head "Cleaning old versions"
if [ -f /usr/local/bin/cyber-clean-helper ]; then
    sudo rm -f /usr/local/bin/cyber-clean-helper
    ok "Removed old helper"
fi
if [ -f /usr/share/polkit-1/actions/com.nc2077.cyberclean.policy ]; then
    sudo rm -f /usr/share/polkit-1/actions/com.nc2077.cyberclean.policy
    ok "Removed old polkit policy"
fi

# ── 2. Cài dependencies ───────────────────────────────────────
head "Installing dependencies"

# Detect package manager
if command -v pacman &>/dev/null; then
    sudo pacman -S --needed --noconfirm python-pyqt6 python-psutil polkit pacman-contrib python-send2trash 2>/dev/null \
        && ok "python-pyqt6, python-psutil, polkit, pacman-contrib" \
        || warn "Some packages may have failed — check manually"

elif command -v apt &>/dev/null; then
    sudo apt-get install -y python3-pyqt6 python3-psutil policykit-1 2>/dev/null \
        && ok "python3-pyqt6, python3-psutil, policykit-1" \
        || warn "Some packages may have failed"
    # pip fallback
    pip install PyQt6 psutil --break-system-packages 2>/dev/null || true

elif command -v dnf &>/dev/null; then
    sudo dnf install -y python3-PyQt6 python3-psutil polkit 2>/dev/null \
        && ok "python3-PyQt6, python3-psutil, polkit" \
        || warn "Some packages may have failed"

else
    warn "Unknown package manager — install manually: PyQt6, psutil, polkit"
    warn "  pip install PyQt6 psutil"
fi

# ── 3. Privileged helper ──────────────────────────────────────
head "Setting up privileged helper"
sudo tee /usr/local/bin/cyber-clean-helper > /dev/null << 'HELPER'
#!/bin/bash
# CyberClean v2.0 — Privileged helper
# Called via pkexec only — runs as root
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
  apt-clean)
    apt-get clean 2>/dev/null
    ;;
  apt-autoremove)
    apt-get autoremove -y 2>/dev/null
    ;;
  dnf-clean)
    dnf clean all 2>/dev/null
    ;;
  zypper-clean)
    zypper clean --all 2>/dev/null
    ;;
  fstrim)
    fstrim -av 2>/dev/null
    ;;
  drop-cache)
    sync && echo 1 > /proc/sys/vm/drop_caches
    ;;
  compact-memory)
    echo 1 > /proc/sys/vm/compact_memory
    ;;
  swappiness)
    echo 10 > /proc/sys/vm/swappiness
    ;;
  optimizer)
    # Batch optimizer actions — called from optimizer.py
    sync && echo 1 > /proc/sys/vm/drop_caches 2>/dev/null
    echo 10 > /proc/sys/vm/swappiness 2>/dev/null
    fstrim -av 2>/dev/null
    ;;
  *)
    echo "Unknown action: $1" >&2
    exit 1
    ;;
esac
HELPER
sudo chmod +x /usr/local/bin/cyber-clean-helper
ok "/usr/local/bin/cyber-clean-helper"

# ── 4. Polkit policy ──────────────────────────────────────────
head "Registering polkit policy"
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
ok "Polkit policy: com.nc2077.cyberclean"

# ── 5. Desktop entry ──────────────────────────────────────────
head "Creating desktop entry"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/cyber-clean.desktop" << DESKTOP
[Desktop Entry]
Name=CyberClean
GenericName=Disk Cleaner
Comment=Smart Disk Cleaner v2.0
Exec=python3 $APP_DIR/main.py
Icon=system-software-update
Terminal=false
Type=Application
Categories=System;Utility;
Keywords=disk;clean;cache;pacman;arch;
StartupNotify=true
DESKTOP
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
ok "Desktop entry: CyberClean"

# ── 6. Systemd auto-clean timer ───────────────────────────────
head "Setting up auto-clean timer"
SYSTEMD_USER="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER"

# Tạo service file — dùng python inline thay vì cli script riêng
cat > "$SYSTEMD_USER/cyber-clean.service" << SERVICE
[Unit]
Description=CyberClean Auto Disk Cleaner
After=graphical-session.target

[Service]
Type=oneshot
# Auto-clean safe targets khi disk > 75%
ExecStart=/bin/bash -c 'python3 -c "
import sys, os
sys.path.insert(0, os.path.expanduser('"'"'$APP_DIR'"'"'))
import psutil
disk = psutil.disk_usage('"'"'/'"'"').percent
if disk < 75: sys.exit(0)
from core.linux_cleaner import LinuxCleaner
c = LinuxCleaner()
safe = [t.id for t in c.get_targets() if t.safety=='"'"'safe'"'"' and not t.needs_root]
[c.clean(tid, dry=False) for tid in safe]
print(f'"'"'CyberClean auto: {disk:.0f}%% disk, cleaned safe targets'"'"')
"'
SERVICE

# Tạo timer file
cat > "$SYSTEMD_USER/cyber-clean.timer" << TIMER
[Unit]
Description=CyberClean Auto Timer — every 6h

[Timer]
OnBootSec=5min
OnUnitActiveSec=6h
Persistent=true

[Install]
WantedBy=timers.target
TIMER

systemctl --user daemon-reload 2>/dev/null
systemctl --user enable --now cyber-clean.timer 2>/dev/null \
    && ok "Auto-clean timer active (every 6h, disk > 75% only)" \
    || warn "Timer setup skipped (no systemd user session?)"

# ── 7. Keybind hint ───────────────────────────────────────────
head "Optional: Add keybind"
echo -e "  ${CYAN}Add to hyprland.conf:${NC}"
echo -e "  bind = \$mainMod, X, exec, python3 $APP_DIR/main.py"

# ── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ CyberClean v2.0 installed!${NC}"
echo ""
echo -e "${CYAN}  Run:${NC}  python3 $APP_DIR/main.py"
echo -e "${CYAN}  Or find 'CyberClean' in your app launcher${NC}"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
