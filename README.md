<div align="center">

```
 ██████╗██╗   ██╗██████╗ ███████╗██████╗      ██████╗██╗     ███████╗ █████╗ ███╗   ██╗
██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║     ██╔════╝██╔══██╗████╗  ██║
██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝    ██║     ██║     █████╗  ███████║██╔██╗ ██║
██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗    ██║     ██║     ██╔══╝  ██╔══██║██║╚██╗██║
╚██████╗   ██║   ██████╔╝███████╗██║  ██║    ╚██████╗███████╗███████╗██║  ██║██║ ╚████║
 ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝
```

**Smart System Cleaner & Performance Optimizer**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-41CD52?style=flat-square&logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![Platform](https://img.shields.io/badge/Windows%20%7C%20Linux-supported-00c8e0?style=flat-square)](https://github.com/vuphitung/CyberClean/releases/latest)
[![License](https://img.shields.io/badge/License-MIT-f0c040?style=flat-square)](LICENSE)
[![Release](https://img.shields.io/github/v/release/vuphitung/CyberClean?style=flat-square&color=c060f0)](https://github.com/vuphitung/CyberClean/releases/latest)

🌐 **Ngôn ngữ / Language:** **English** · [Tiếng Việt](README_vi.md)

</div>

## Installation

### Linux

```bash
curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash
```

Installs to `/opt/CyberClean` · registers `cyberclean` command · sets up scoped privilege helper.

**Uninstall:**
```bash
sudo cyberclean --uninstall
```

### Windows

**[⬇ Download CyberClean Setup v3.0.0 (.exe)](https://github.com/vuphitung/CyberClean/releases/latest)**

UAC prompt on first install only. Uninstall via `Settings → Apps → CyberClean`.

---

## Screenshots
---

<p align="center">
  <img src="screenshots/dashboard.png" width="100%">
</p>
---

<p align="center">
  <img src="screenshots/clean.png" width="100%">
</p>
---

<p align="center">
  <img src="screenshots/scanner.png" width="100%">
</p>
---

<p align="center">
  <img src="screenshots/uninstaller.png" width="100%">
</p>
---

<p align="center">
  <img src="screenshots/history.png" width="100%">
</p>
---

<p align="center">
  <img src="screenshots/booster.png" width="100%">
</p>
---

## Features

### [◈] Dashboard
Live system stats, auto-refreshes every 4 seconds.

- CPU / RAM / Swap / Temperature / Network I/O
- Top processes with one-click kill
- Disk usage per mount point
- System uptime · Startup items manager

---

### [✦] Smart Clean
Dry-run preview before touching anything. Every deletion is logged. Targets are labelled **Safe / Caution / Danger**.

**Linux** — package cache (pacman / apt / dnf / zypper / xbps), orphaned packages, AUR build cache, Flatpak runtimes, Docker/Podman images, Snap old revisions, journal logs, browser cache, pip cache, thumbnail cache, temp files.

**Windows** — Temp & `%TEMP%`, Prefetch, Recycle Bin, Windows Update cache, Delivery Optimization, Thumbnail DB, Font Cache, GPU Shader Cache, WinSxS, DNS flush, Event logs, WER crash dumps, browser cache (Chrome / Edge / Brave / Firefox / Vivaldi / Cốc Cốc).

---

### [⚡] System Booster
Performance tweaks without crashes. Every change is fully reversible.

- **Free RAM** — compact memory without evicting page cache
- **Memory Tune** — swappiness / vm params (Linux) · trim idle process working sets (Windows)
- **Kill Bloat** — zombie + idle high-RAM processes
- **Clear GPU / Shader Cache** — mesa, NVIDIA, Chrome, Edge
- **[◈] Game Mode** — 3-tier activity-aware CPU jail, gives foreground app full resources
- **[~] Eco Mode** — cgroups v2 (Linux) · EcoQoS + memory priority (Windows 11)
- **[★] Smart Boost** — auto-detects PC tier (High / Mid / Low) by RAM + cores + GPU VRAM
- **TCP Nagle Disable** — lower online game latency (Windows)
- **Timer Resolution 1ms** — smoother frames (Windows)

---

### [◉] Security Scanner
Read-only deep scan — nothing deleted automatically. You decide what to fix.

Scans: running processes · outbound TCP connections · SUID/SGID binaries · world-writable system files · cron backdoors · suspicious scripts in temp dirs · LD_PRELOAD hijacks · SSH authorized_keys · hosts file tampering · Windows autoruns.

Each process goes through a multi-dimensional threat scoring matrix (+/− points per signal). Score ≥ 70 → critical. Score 40–69 → watchlist, re-checked every 5 minutes.

> Cannot detect Ring-0 rootkits or UEFI implants. Good at: miners, reverse shells, cron backdoors, hosts hijacks, scripts running from `/tmp`.

---

### [≡] App Uninstaller
- **Windows** — reads from Add/Remove Programs registry (no `wmic`)
- **Linux** — pacman / apt / dnf integration
- Shows installed size, version, source
- Background uninstall with live progress log

---

### [↺] History & Deletion Log
- Every session logged to `~/.local/share/cyber-clean/history.jsonl`
- Full audit trail: path, size, type of every deleted item
- View freed space per session

---

### [↑] Auto-Updater
Checks GitHub Releases on startup (background thread, non-blocking). One-click download → replace → restart.

---

### [♪] System Tray & Auto-clean
Minimize to tray. Auto-clean runs safe targets every 6 hours when idle (CPU < 20%, network < 500 KB/s). Pauses automatically when Game Mode is active.

---

## Compatibility

| OS | Version | Notes |
|----|---------|-------|
| Linux | Arch · Manjaro · EndeavourOS · CachyOS | pacman |
| Linux | Ubuntu · Debian · Pop!_OS · Mint · Kali | apt |
| Linux | Fedora · CentOS · Rocky · Nobara | dnf |
| Linux | openSUSE Leap / Tumbleweed | zypper |
| Linux | Void Linux | xbps |
| Windows | 10 (1903+) | Full support |
| Windows | 11 | Full support + EcoQoS |
| Windows | ARM64 (Surface Pro X, Snapdragon) | Supported |

---

## Security & Privacy

- **No telemetry** — zero data collection, zero network calls during normal operation
- **No background service** — only runs when you open it
- **Scoped privilege** — Linux sudoers rule grants access only to `/usr/local/bin/cyber-clean-helper`, not blanket sudo. The helper is a readable shell script you can audit.
- **send2trash** — deleted files go to system Trash when available, not permanent delete

---

## Build from source

```bash
git clone https://github.com/vuphitung/CyberClean.git
cd CyberClean
pip install -r requirements.txt

# Run directly
python main.py

# Build Linux binary
python3 build.py --linux

# Build Windows installer
python build.py --inno
```

**Requirements:** Python 3.10+ · PyQt6 · psutil · PyInstaller

---

## Project Structure

```
CyberClean/
├── main.py                 # Main GUI (PyQt6)
├── version.py              # Single source of truth for version
├── core/
│   ├── base_cleaner.py     # Abstract cleaner interface
│   ├── linux_cleaner.py    # Linux clean targets
│   ├── windows_cleaner.py  # Windows clean targets
│   ├── scanner.py          # Security scanner
│   ├── booster.py          # RAM / CPU / Game Mode / Smart Boost
│   ├── analyzer.py         # Idle scheduler · network view
│   ├── uninstaller.py      # App uninstaller
│   └── os_detect.py        # OS / distro / package manager detection
├── utils/
│   ├── sysinfo.py          # psutil system snapshot
│   ├── i18n.py             # 11-language translations
│   └── updater.py          # In-app OTA updater
├── assets/
│   └── logo.png
├── LibreHardwareMonitorLib.dll  # Windows temperature sensor
└── install.sh              # Linux one-line installer
```

---

## Languages

English · Tiếng Việt 

---

## License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

Made with ☕ by [vuphitung](https://github.com/vuphitung) — a Vietnamese student 🇻🇳

*If CyberClean helped you, consider giving it a ⭐*

🌐 [Xem README tiếng Việt](README_vi.md)

</div>
