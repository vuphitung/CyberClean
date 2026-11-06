<div align="center">

<!-- Animated Cyber Wave Banner -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:060911,50:00c8e0,100:c060f0&height=120&section=header&animation=fadeIn" width="100%" alt="header" />

<a href="https://github.com/vuphitung/CyberClean">
  <img src="assets/banner.svg" width="100%" alt="CyberClean — Smart System Cleaner &amp; Disk Manager" />
</a>

**Desktop utility for Windows and Linux: system monitoring, disk cleanup, disk-usage report, app uninstaller and an optional performance booster.**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-41CD52?style=flat-square&logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![Platform](https://img.shields.io/badge/Windows%20%7C%20Linux-supported-00c8e0?style=flat-square&logo=linux&logoColor=white)](#platform-support)
[![License](https://img.shields.io/badge/License-GPL--3.0-f0c040?style=flat-square&logo=gnu&logoColor=white)](LICENSE)
[![Release](https://img.shields.io/github/v/release/vuphitung/CyberClean?style=flat-square&color=c060f0&logo=github)](https://github.com/vuphitung/CyberClean/releases/latest)
[![Version](https://img.shields.io/badge/version-3.1.0-A47DFF?style=flat-square)](CHANGELOG.md)

<br>

<a href="README.md"><img src="https://img.shields.io/badge/LANG-ENGLISH-00E5FF?style=for-the-badge&labelColor=0E1626" alt="English"></a>&nbsp;&nbsp;<a href="README_vi.md"><img src="https://img.shields.io/badge/LANG-TI%E1%BA%BENG_VI%E1%BB%86T-334155?style=for-the-badge&labelColor=0E1626" alt="Tiếng Việt"></a>

</div>

## Quick Installation

Choose your platform and follow the steps below.

### <img src="https://cdn.simpleicons.org/linux/00E5FF" width="18" height="18" align="absmiddle" /> &nbsp;Linux

<p>
  <img src="https://img.shields.io/badge/Arch-1793D1?style=flat-square&logo=archlinux&logoColor=white" alt="Arch">
  <img src="https://img.shields.io/badge/Ubuntu-E95420?style=flat-square&logo=ubuntu&logoColor=white" alt="Ubuntu">
  <img src="https://img.shields.io/badge/Debian-A81D33?style=flat-square&logo=debian&logoColor=white" alt="Debian">
  <img src="https://img.shields.io/badge/Fedora-51A2DA?style=flat-square&logo=fedora&logoColor=white" alt="Fedora">
  <img src="https://img.shields.io/badge/openSUSE-73BA25?style=flat-square&logo=opensuse&logoColor=white" alt="openSUSE">
</p>

Install with one command:

```bash
curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash
```

Installs to `/opt/CyberClean`, registers the `cyberclean` command, and sets up a scoped privilege helper.

<details>
<summary>Uninstall CyberClean</summary>

```bash
sudo cyberclean --uninstall
```
</details>

---

### <img src="https://img.shields.io/badge/-Windows_10_%2F_11-0078D6?style=flat-square&logo=windows&logoColor=white" height="22" align="absmiddle" />

<p>
  <a href="https://github.com/vuphitung/CyberClean/releases/latest">
    <img src="https://img.shields.io/badge/DOWNLOAD_INSTALLER-(.EXE)-00E5FF?style=for-the-badge&logo=windows&logoColor=060911&labelColor=0E1626" alt="Download CyberClean for Windows" />
  </a>
</p>

**[Download CyberClean for Windows (.exe)](https://github.com/vuphitung/CyberClean/releases/latest)**

CyberClean requests Administrator privileges (UAC) on launch to perform system-level cleanup, SSD TRIM, and CPU temperature sensor access. Uninstall via **Settings → Apps → CyberClean**.

## Overview

CyberClean shows live system metrics, finds files that can be cleaned, reports where disk space went, uninstalls applications, and can apply a reversible set of performance tweaks while you play or work. It is a PyQt6 application with a dark and a light theme and an English and a Vietnamese interface.

Cleanup targets are files and caches only. CyberClean is not an antivirus and does not clean the registry. Performance results depend on the machine and workload; the app does not promise a speed-up.

## Screenshots

*Windows 10, dark theme.*

**Dashboard** — live metrics, one-click maintenance, top processes, per-volume usage
<img src="screenshots/dashboard.png" alt="Dashboard" width="100%">

**Clean** — regenerable caches, dry-run preview, estimated free space
<img src="screenshots/clean.png" alt="Clean" width="100%">

**Deep Clean** — items you choose one by one
<img src="screenshots/deep-clean.png" alt="Deep Clean" width="100%">

**Disk Advisor** — where the space went (report only)
<img src="screenshots/disk-advisor.png" alt="Disk Advisor" width="100%">

**Uninstaller**
<img src="screenshots/uninstaller.png" alt="Uninstaller" width="100%">

**History** and **Audit log**
<img src="screenshots/history.png" alt="History" width="100%">
<img src="screenshots/audit-log.png" alt="Audit log" width="100%">

**System Booster**
<img src="screenshots/booster.png" alt="System Booster" width="100%">

<img src="https://user-images.githubusercontent.com/73097560/115834477-dbab4500-a447-11eb-908a-139a6edaec5c.gif" width="100%">

## Features

### Dashboard
- CPU, RAM, temperature (when a sensor is available), commit memory (Windows) or swap (Linux), network throughput, CPU/RAM history graphs and uptime; refreshed every few seconds.
- Top processes with a Kill button, and used/free space for every mounted volume.
- **One-click optimize** — Windows: flush DNS cache, clear temp files, trim working sets, TRIM SSD. Linux: drop caches, tune `vm.swappiness`, `fstrim`, vacuum old journal logs.
- *Load index* is a heuristic built from CPU, RAM, disk, temperature and swap. It is not CPU usage, SMART data or a disk-health diagnosis.

### Clean
Targets that can be regenerated, ticked by default. *Dry-run* shows exactly what would be removed before you run *Clean now*.

| OS | Targets |
|---|---|
| Windows | Windows Temp, Chromium-based browser and Electron app caches (Chrome, Edge, Brave, Opera, Vivaldi, Cốc Cốc, VS Code, Discord, Slack…), Firefox cache, thumbnail cache, Windows Error Reports, DNS cache |
| Linux | Package-manager caches (apt, pacman, dnf, zypper, xbps, apk, rpm-ostree), journal and old system logs, crash reports, browser and Electron caches, thumbnails, pip cache, temp files |

Browser caches are skipped, with a note, while the browser is running.

### Deep Clean
Items that might matter. **Nothing is pre-selected**, "select all" skips high-risk rows, and every delete asks for confirmation (default answer: Cancel). Deep Clean never runs in the background.

- Windows: Recycle Bin, Prefetch, Windows Update cache, Delivery Optimization, font cache, GPU shader cache, WinSxS cleanup, Event Logs, crash dumps, developer caches (npm, yarn, pnpm, pip, NuGet, Gradle, Maven, Cargo, Go, JetBrains…).
- Linux: orphaned/unused packages (apt, pacman, dnf, xbps), Nix garbage collection, developer caches, other `~/.cache` folders, Trash, and — when installed — Docker/Podman, Flatpak unused runtimes, Snap old revisions.

### Disk Advisor
Report only — there is no delete button. Groups the largest consumers: Windows system files (`Windows.old`, `pagefile.sys`, `hiberfil.sys`, Installer cache), Downloads, large files, virtual machines and WSL disks, game libraries, old `node_modules` / `target` / virtualenv folders, containers, `/opt`, heaviest packages. Rows can be opened in the file manager and the report can be copied.

### Uninstaller
- Windows: installed programs from the Registry, enriched with `winget` data.
- Linux: pacman, apt, dnf, zypper, xbps and Flatpak; core system packages are protected.
- Multi-select with live progress log. On Windows the list is not filtered, so check entries (drivers, runtimes) before removing them.

### History and Audit log
*History* records each session's disk usage before/after and the space freed. *Audit log* records what was removed (path, type, size). Both are local files; removed files are not kept for restore.

### System Booster
Applies tweaks on demand and **captures the original state first**. The state is restored when you turn Boost off or close the app, and recovered on the next start if the app was killed.

- Windows: 1 ms timer-resolution request, GameDVR off, DirectX/DWM fullscreen setting, priority for a detected game, background-process throttling (EcoQoS on Windows 11), browser GPU-cache cleanup.
- Linux: CPU governor / power profile, memory tuning, process priority, Hyprland options when it is running.
- A game watcher raises priority only while a game is running. The log states when a benefit has not been measured.

### Tray and Auto-clean
Auto-clean is **off by default**. When enabled it runs only `AUTO` targets flagged as scheduled, only when the machine is idle, at most every 6 hours, and only while the app is open or in the tray. It never touches the Recycle Bin or Trash. If Auto-clean is off, closing the window quits the app.

### Updates and privacy
The app checks GitHub Releases for a new version and installs nothing without your click. Downloads are verified against an Ed25519 signature built into the app. There is no telemetry or analytics; the update check is the only network access.

## How cleaning stays predictable

| Tier | Page | Behaviour |
|---|---|---|
| `AUTO` | Clean | Regenerable caches. Ticked by default. The only tier the scheduler may run. |
| `REVIEW` | Deep Clean | Needs an explicit choice for every item. |
| `ADVISOR` | Disk Advisor | Report only. |

A clean is **planned, previewed, then executed**. Immediately before each deletion the engine re-checks the item and skips it if it changed since the scan, is in use, or its owning app started again. Symlinks and junctions are not followed and mount points are not crossed. **Deletion is permanent** — nothing is moved to the Recycle Bin.

## Platform support

| Environment | Status |
|---|---|
| Windows 10 (build 19044), Python 3.12 | Run and used on a real machine: all pages, metric comparison against Windows counters, Windows-specific tests pass. |
| Windows 11 | Code paths exist (for example EcoQoS); not verified on hardware. |
| Linux, apt-based (Ubuntu / Debian family) | Automated tests pass headless on Ubuntu with Python 3.12 (628 passed, 17 skipped). |
| Other Linux distributions | Package-manager detection for pacman, dnf, zypper, xbps, apk, rpm-ostree and Nix; not individually tested. |

### Hardware Monitoring Credits (Windows CPU Temperature)

Windows does not expose a standard user-mode API for reading CPU package and core thermal registers. To support accurate **CPU Temperature** monitoring on the Dashboard, CyberClean uses and credits the following projects:

- **[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)** *(MPL-2.0)*: the hardware sensor library used by CyberClean to query CPU and GPU thermal sensors on Windows (`vendor/lhm/LibreHardwareMonitorLib.dll`).
- **[PawnIO](https://github.com/namazso/PawnIO)** by **[namazso](https://github.com/namazso)** ([pawnio.eu](https://pawnio.eu/)): the signed low-level hardware access driver used by CyberClean as LibreHardwareMonitor's kernel backend to support the **CPU Temperature** feature safely on Windows 10/11 without relying on legacy drivers blocked by Windows Defender/HVCI.
- When PawnIO is not installed or no compatible sensor is available, the dashboard card shows `N/A`; you can click the **Temperature** card directly in the app (or select the driver task in the CyberClean installer) to verify its SHA-256 hash and install PawnIO.

## Installation

**Requirements:** Python 3.10+ (PyQt6, psutil, cryptography, send2trash; `tomli` on Python 3.10; `pythonnet` on Windows).

### Run from source (Windows and Linux)

```bash
git clone https://github.com/vuphitung/CyberClean.git
cd CyberClean
python -m venv .venv

# Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
python -X utf8 main.py
```

<details>
<summary><b>Step-by-step setup guide for a brand-new machine (without Git / Python pre-installed)</b></summary>

#### 1. Prepare a fresh system

- **On Windows 10 / 11:**
  1. Open **PowerShell** and install Git and Python 3.12 via `winget` (or download them from [python.org](https://www.python.org/downloads/) and [git-scm.com](https://git-scm.com/download/win) — make sure to tick **"Add Python to PATH"** during installation):
     ```powershell
     winget install -e --id Git.Git
     winget install -e --id Python.Python.3.12
     ```
  2. Reopen PowerShell (preferably **Run as Administrator** for CPU temperature sensor access and system-level cleanup targets).
  3. If PowerShell blocks `.venv\Scripts\Activate.ps1` due to script execution policy, allow scripts for the current session:
     ```powershell
     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
     ```

- **On Linux:**
  ```bash
  # Ubuntu / Debian / Linux Mint / Pop!_OS
  sudo apt update && sudo apt install -y git python3 python3-venv python3-pip libegl1 libxcb-cursor0

  # Arch Linux / Manjaro / EndeavourOS / CachyOS
  sudo pacman -S --needed git python python-pip

  # Fedora
  sudo dnf install -y git python3 python3-pip

  # openSUSE
  sudo zypper install -y git python3 python3-pip
  ```

#### 2. Clone, install dependencies, and run

```bash
# 1. Clone the repository
git clone https://github.com/vuphitung/CyberClean.git
cd CyberClean

# 2. Create an isolated virtual environment (.venv)
python -m venv .venv          # On some Linux distros use: python3 -m venv .venv

# 3. Activate the virtual environment
source .venv/bin/activate     # Linux
.venv\Scripts\Activate.ps1    # Windows PowerShell (or .venv\Scripts\activate.bat on CMD)

# 4. Upgrade pip and install all required dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 5. Launch CyberClean
python -X utf8 main.py
```

> **Windows tip:** To enable CPU temperature readings when running from source on a machine without the sensor driver, simply click the **TEMPERATURE** card on the Dashboard to verify and install [PawnIO](https://pawnio.eu/).

</details>

### Linux installer (from a published release)

```bash
curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash
```

Verifies the release signature, installs to `/opt/CyberClean`, registers the `cyberclean` command and a desktop entry, and sets up a restricted privilege helper. Uninstall with `sudo cyberclean --uninstall`.

### Windows package

Build it yourself (below). Packaged builds are attached to [GitHub Releases](https://github.com/vuphitung/CyberClean/releases) when a release is published.

## Build

```bash
python -m pip install pyinstaller
python build.py --linux      # Linux tar.gz
python build.py --windows    # Windows onedir folder in dist/CyberClean
python build.py --inno       # Windows onedir + Inno Setup script (compile it with Inno Setup)
```

<details>
<summary><b>Full step-by-step Build &amp; Packaging guide for Windows (.exe / Setup.exe) and Linux (.tar.gz / AppImage / .deb)</b></summary>

#### 1. Verify build dependencies

Make sure your `.venv` is active and has both `requirements.txt` and `pyinstaller` installed:

```bash
python -m pip install -r requirements.txt pyinstaller
python build.py --check
```

#### 2. Build on Windows (`.exe` and `Setup.exe` installer)

1. Build the `onedir` application bundle and generate the Inno Setup script:
   ```powershell
   python build.py --inno
   ```
   - `build.py` verifies the SHA-256 hashes of all bundled `vendor/lhm` DLLs, downloads/verifies the official `PawnIO_setup.exe`, builds `dist\CyberClean\CyberClean.exe` (with the `--uac-admin` manifest), and generates `CyberClean.iss`.
2. Compile the standalone Windows installer using [Inno Setup 6](https://jrsoftware.org/isinfo.php):
   - **GUI:** Open `CyberClean.iss` in **Inno Setup Compiler** and press **Compile (`F9`)**.
   - **CLI:**
     ```powershell
     & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" CyberClean.iss
     ```
   - The finished installer is written to `dist\CyberClean_Setup_v3.1.0.exe`.

#### 3. Build on Linux (`.tar.gz`, `AppImage`, `.deb`)

```bash
# Build standard .tar.gz archive (used by install.sh / GitHub Releases)
python build.py --linux

# Build standalone portable AppImage
python build.py --appimage

# Build .deb package (on Debian / Ubuntu / Linux Mint)
python build.py --deb
```

All build artifacts are placed in the `dist/` directory.

</details>

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m pyflakes main.py ui_widgets.py ui_pages.py core utils
```

On Windows the full suite currently reports 49 failures that come from POSIX-only fixtures (symlinks that need a privilege, Unix sockets, Linux-only targets); the Windows-specific tests pass. Details: [Windows report](docs/WINDOWS_NATIVE_REPORT_VI.md) (Vietnamese). Use a dedicated test folder when you try deletion.

```text
CyberClean/
├── main.py                 # application entry, window and tray
├── ui_widgets.py, ui_pages.py
├── core/                   # engine, cleaners, booster, advisor, uninstaller
├── utils/                  # telemetry, translations, updater
├── rules/                  # per-OS cleanup rules (TOML)
├── packaging/              # Linux privilege helper
├── vendor/lhm/             # Windows sensor library
├── tests/                  # pytest
├── build.py, install.sh
└── assets/, screenshots/
```

## Known limitations

- Interactive testing on real Linux desktops is limited; please report distribution-specific problems.
- Windows 11, ARM64 and other DPI/driver combinations have not been verified.
- Booster effects are not benchmarked by the app.
- Size estimates for logs and WinSxS can differ from the space actually freed (volume, permissions, snapshots).

## Contributing and issues

Open an issue with your OS and version, the CyberClean version, what you did, and the text shown in the app.

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:c060f0,50:00c8e0,100:060911&height=100&section=footer" width="100%" alt="footer" />

