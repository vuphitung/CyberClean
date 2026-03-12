<div align="center">

```
  ██████╗██╗   ██╗██████╗ ███████╗██████╗      ██████╗██╗     ███████╗ █████╗ ███╗
 ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║     ██╔════╝██╔══██╗████╗
 ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝    ██║     ██║     █████╗  ███████║██╔██╗
 ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗    ██║     ██║     ██╔══╝  ██╔══██║██║╚██
 ╚██████╗   ██║   ██████╔╝███████╗██║  ██║    ╚██████╗███████╗███████╗██║  ██║██║ ╚█
  ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝
```

**Smart Disk Cleaner · v2.0 · Windows + Linux**

[![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-green?style=flat-square)](https://pypi.org/project/PyQt6/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-cyan?style=flat-square)]()
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

</div>

---

## ✨ Features

- **Dashboard** — Real-time CPU, RAM, Temperature, Disk usage with sparkline charts
- **Smart Clean** — Safe/caution targets with dry-run preview before deleting anything
- **Security Scanner** — SUID files, world-writable paths, suspicious crontabs, open ports
- **App Uninstaller** — Registry-based (Windows) or package-manager (Linux), no `wmic`
- **History & Rollback** — Every clean logged, files trackable
- **Browser Turbo** — Kill tracker scripts, DNS prefetch, history
- **Auto-clean** — Runs safe targets every 6h while hidden in system tray
- **Cross-platform** — Full feature parity on Windows 10/11 and Linux (Arch/Debian/Fedora/openSUSE)

---

## 🚀 Quick Start

### Linux
```bash
git clone https://github.com/vuphitung/CyberClean
cd CyberClean
bash install.sh        # installs deps + sets up polkit + systemd timer
python3 main.py
```

### Windows
```powershell
git clone https://github.com/vuphitung/CyberClean
cd CyberClean
pip install -r requirements.txt
# Right-click → Run as Administrator
python main.py
```

---

## 📦 Requirements

```
PyQt6 >= 6.4.0
psutil >= 5.9.0
```

Install manually:
```bash
pip install PyQt6 psutil
```

---

## 🗂 Project Structure

```
CyberClean/
├── main.py                 # GUI — PyQt6, all tabs
├── core/
│   ├── base_cleaner.py     # Abstract cleaner interface
│   ├── windows_cleaner.py  # Windows targets (wevtutil, registry, etc.)
│   ├── linux_cleaner.py    # Linux targets (pacman/apt/dnf/flatpak)
│   ├── uninstaller.py      # App uninstaller (Registry on Win, pkg mgr on Linux)
│   ├── scanner.py          # Security scanner
│   └── os_detect.py        # OS/distro/privilege detection
├── utils/
│   └── sysinfo.py          # psutil snapshot, multi-source temperature
├── install.sh              # Linux installer (polkit + systemd timer)
├── build.py                # PyInstaller build script
├── CyberClean.spec         # PyInstaller spec
└── requirements.txt
```

---

## 🔧 Build

### Windows `.exe`
```powershell
pip install pyinstaller
python build.py --windows
# Output: dist/CyberClean.exe
```

### Linux AppImage
```bash
pip install pyinstaller
python3 build.py --linux
# Output: dist/CyberClean-2.0.0-x86_64.AppImage
```

---

## 🛡 Permissions

**Linux:** `install.sh` sets up a NOPASSWD sudoers rule scoped **only** to
`/usr/local/bin/cyber-clean-helper` — the app never gets blanket sudo access.

**Windows:** Requires Administrator (UAC prompt on first launch).

---

## 🌐 Supported Platforms

| OS | Distros / Versions |
|----|--------------------|
| **Linux** | Arch, Manjaro, Ubuntu, Debian, Fedora, openSUSE, and derivatives |
| **Windows** | Windows 10, Windows 11 |

Package managers: `pacman` · `apt` · `dnf` · `zypper`  
Extras: `flatpak` · `docker/podman` · `yay/paru`

---

## 📄 License

MIT — see [LICENSE](LICENSE)
