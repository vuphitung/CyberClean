<div align="center">

```
 ██████╗██╗   ██╗██████╗ ███████╗██████╗      ██████╗██╗     ███████╗ █████╗ ███╗   ██╗
██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║     ██╔════╝██╔══██╗████╗  ██║
██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝    ██║     ██║     █████╗  ███████║██╔██╗ ██║
██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗    ██║     ██║     ██╔══╝  ██╔══██║██║╚██╗██║
╚██████╗   ██║   ██████╔╝███████╗██║  ██║    ╚██████╗███████╗███████╗██║  ██║██║ ╚████║
 ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝
```

**Smart Disk Cleaner for Arch Linux**

*Cyberpunk-themed disk management — auto-clean, GUI app, dry-run, history, rollback.*

[![Arch](https://img.shields.io/badge/Arch_Linux-1793D1?style=for-the-badge&logo=arch-linux&logoColor=white)](https://archlinux.org)
[![Python](https://img.shields.io/badge/Python_3-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://riverbankcomputing.com/software/pyqt)
[![License](https://img.shields.io/badge/License-MIT-00e5ff?style=for-the-badge)](LICENSE)

</div>

---

## ◈ What is this?

**Cyber-Clean** is a smart disk cleaner built for Arch Linux. It only removes things that are **100% safe to delete** — package cache, broken downloads, old journal logs, browser cache, orphaned packages, and stale tmp files.

It never touches your apps, configs, documents, or anything important.

---

## ◈ Preview

> *Screenshot coming soon — GUI app with Dashboard, Clean, History, Rollback tabs*

---

## ◈ Features

```
◆ GUI App          Cyberpunk PyQt6 desktop app — 4 tabs, live system stats
◆ Dry-Run          Preview exactly what will be deleted before touching anything
◆ Auto-Clean       systemd timer — runs every 6h, only triggers when disk > 75%
◆ Polkit Auth      Password prompt via polkit — asked once per session, never again
◆ History Log      Full log of every clean session — how much freed, disk before/after
◆ Rollback List    Complete list of deleted files — restore commands included
◆ CLI Mode         Terminal interface with --dry, --force, --log, --rollback flags
◆ Zero False-Clean Never deletes apps, configs, documents, or anything user-created
```

---

## ◈ Requirements

- Arch Linux (or any pacman-based distro)
- Python 3.8+
- Hyprland / any Wayland compositor (for GUI)

---

## ◈ Installation

```bash
# Clone
git clone https://github.com/vuphitung/CyberClean.git ~/CyberClean
cd ~/CyberClean

# Run installer — installs deps + polkit policy + desktop entry
bash install.sh
```

That's it. The installer handles everything:
- Installs `python-pyqt6`, `polkit`, `pacman-contrib`
- Creates `/usr/local/bin/cyber-clean-helper` (privileged helper)
- Registers polkit policy (password prompt instead of sudo)
- Creates desktop entry → app appears as **Cyber-Clean** in your launcher
- Sets up systemd auto-clean timer

---

## ◈ Usage

### Open the App

```bash
# From terminal
python3 ~/CyberClean/cyber-clean-app.py

# Or find "Cyber-Clean" in your app launcher (Rofi / wofi / etc.)
```

Add a keybind in your compositor config:
```bash
# Hyprland example
bind = $mainMod, X, exec, python3 ~/CyberClean/cyber-clean-app.py
```

### GUI — 4 Tabs

#### DASHBOARD
Live system monitor — Disk %, RAM, CPU Load, Temperature. Reads directly from `/proc` and `/sys`.

#### CLEAN
```
1. Check ✓ the targets you want to clean
2. Click [DRY-RUN]   → see exactly what will be deleted, how many MB
3. Click [CLEAN NOW] → confirm dialog → polkit asks password (first time only) → done
```

> `DRY-RUN` always just scans, never deletes.  
> `CLEAN NOW` always runs live — ignores the dry-run checkbox.

#### HISTORY
Table of every clean session — timestamp, disk before/after, MB freed, which targets were cleaned.

#### ROLLBACK
List of everything deleted. Cache files auto-rebuild. For orphaned packages, the restore command is shown:
```bash
sudo pacman -S <package-name>
```

### CLI Mode

```bash
# Preview what would be deleted (safe, no changes)
python3 ~/CyberClean/cyber-clean.py --dry

# Run actual clean (needs sudo for pacman/paccache)
sudo python3 ~/CyberClean/cyber-clean.py

# Force clean even if disk < 75%
sudo python3 ~/CyberClean/cyber-clean.py --force

# View clean history
python3 ~/CyberClean/cyber-clean.py --log

# View deleted files list
python3 ~/CyberClean/cyber-clean.py --rollback
```

### Auto-Clean Timer

The systemd timer runs every 6 hours. If disk usage is below 75%, it exits immediately without doing anything.

```bash
# Check timer status
systemctl --user status eww-clean.timer

# View timer logs
journalctl --user -u eww-clean.service -n 20
```

---

## ◈ What Gets Cleaned

| Target | Description | Restore? |
|--------|-------------|----------|
| Pacman cache | Old package versions — keeps latest 1 | Re-download when needed |
| Broken downloads | Interrupted `download-*` files in cache | Not needed |
| Journal logs | Systemd logs older than 7 days | Not needed |
| Chrome cache | Browser cache — auto-rebuilds | Auto-rebuilds |
| Firefox cache | Browser cache — auto-rebuilds | Auto-rebuilds |
| Thumbnails | File manager previews — auto-rebuilds | Auto-rebuilds |
| Yay build cache | AUR build artifacts | Re-download when needed |
| Pip cache | Python package downloads | Re-download when needed |
| Tmp files | `/tmp` files older than 3 days, not in use | Not needed |
| Orphaned packages | Packages with no dependents | `sudo pacman -S <pkg>` |

---

## ◈ What is NEVER Touched

| Category | Examples |
|----------|---------|
| Installed apps | `/usr/bin`, `/usr/lib`, `/usr/share` |
| User config | `~/.config`, `~/.local/share` |
| User files | `~/Documents`, `~/Pictures`, `~/Downloads` |
| Pacman database | `/var/lib/pacman` |
| Active tmp files | Any file currently open by a process |

The script checks `lsof` before touching any `/tmp` file. It also keeps the **folder structure** of cache directories intact — only the contents are removed — so apps running with open file handles don't crash.

---

## ◈ How Polkit Works

Instead of running the whole app as root (which breaks Wayland), Cyber-Clean uses a small privileged helper:

```
App (runs as user)
  └─→ pkexec /usr/local/bin/cyber-clean-helper <action>
          └─→ polkit checks policy
                └─→ password prompt (first time per session)
                      └─→ helper runs paccache / pacman / journalctl as root
```

After the first password prompt in a session, polkit remembers — you won't be asked again until next login.

---

## ◈ File Structure

```
CyberClean/
├── install.sh              ← Run this first
├── cyber-clean-app.py      GUI app (PyQt6)
├── cyber-clean.py          CLI / systemd timer backend
├── eww-clean.service       systemd user service
├── eww-clean.timer         systemd user timer (6h interval)
└── README.md
```

Log and rollback data is stored in `~/.local/share/cyber-clean/`.

---

## ◈ Uninstall

```bash
# Remove polkit policy and helper
sudo rm /usr/share/polkit-1/actions/com.nc2077.cyberclean.policy
sudo rm /usr/local/bin/cyber-clean-helper

# Remove desktop entry
rm ~/.local/share/applications/cyber-clean.desktop

# Disable timer
systemctl --user disable --now eww-clean.timer
rm ~/.config/systemd/user/eww-clean.*

# Remove logs (optional)
rm -rf ~/.local/share/cyber-clean

# Remove the app itself
rm -rf ~/CyberClean
```

---

## ◈ Part of CyberDotfiles

Cyber-Clean is extracted from [CyberDotfiles](https://github.com/vuphitung/CyberDotfiles) — a full Arch Linux + Hyprland + EWW setup with cyberpunk aesthetics.

---

<div align="center">

*Clean fast. Stay sharp.*

**[⭐ Star if it helped you](https://github.com/vuphitung/CyberClean)**

</div>
