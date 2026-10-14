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

**[⬇ Download CyberClean for Windows (.exe)](https://github.com/vuphitung/CyberClean/releases/latest)**

UAC prompt on first install only. Uninstall via `Settings → Apps → CyberClean`.

---

## Screenshots

<p align="center">
  <img src="screenshots/dashboard.png" width="100%">
</p>
---

<p align="center">
  <img src="screenshots/clean.png" width="100%">
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
- System uptime

---

### [✦] Smart Clean — three tiers, three pages
CyberClean never guesses what is safe to delete. Every target belongs to one of three tiers, and each tier has **its own page** in the sidebar:

| Tier | Page | What | Behaviour |
|------|------|------|-----------|
| **AUTO** | **CLEAN** | Always regenerable: browser & Electron caches, thumbnails, rotated logs, package-manager caches, journal, old temp files, crash dumps | Ticked by default · the only tier the idle scheduler may run |
| **REVIEW** | **DEEP CLEAN** | Things that *might* matter: orphaned packages, dev caches, Docker images/volumes, Flatpak/Snap leftovers, other `~/.cache` folders, the Trash | Categories on the left, every item on the right — **nothing is pre-ticked**, "select all" skips high-risk rows (their full warning is shown), every delete asks first (default: Cancel) · never runs in the background |
| **ADVISOR** | **DISK ADVISOR** | Where the space *really* went: VMs, game libraries, `/opt`, heaviest packages, large files, old `node_modules`/`target`/venvs, Downloads, WSL disks | **Report only** — summary tiles, a share-of-disk bar, per-category cards, "open folder" and "copy report"; there is no delete button |

How a clean works (Linux + Windows share the same engine, `core/engine.py`):

1. **Plan** — one scan produces a concrete list of items (real sizes, hard-links counted correctly).
2. **Preview** — Dry-run shows exactly that plan.
3. **Execute** — runs *that* plan, but re-checks every item right before deleting it: replaced? modified since the scan? the owning app started again? Anything that changed is skipped, never deleted.

Guards applied to everything: age (untouched for N days + never anything modified in the last 10 min) · owning app must be closed (process list, Chromium `SingletonLock`, `--user-data-dir`) · file/dir not open by any process · symlinks and junctions never followed · mount points never crossed · directories containing sockets/FIFOs (live runtime state like `/tmp/.X11-unix`, `tmux-*`, `ssh-*`) are skipped · files of other users are skipped.

Free space is measured with `shutil.disk_usage` before/after. If the filesystem is Btrfs/ZFS the app warns that snapshots may keep the space allocated.

**Linux** — pacman / apt / dnf / zypper / xbps / apk / rpm-ostree (Fedora Atomic, Bazzite) / Nix · AUR build cache · Flatpak (user + system) · Docker/Podman · Snap · journal · browsers (every Chromium-based browser and Electron app via one rule — Chrome, Brave, Edge, Vivaldi, Opera, VS Code, Cursor, Discord, Slack…; Firefox incl. Snap/Flatpak) · pip · thumbnails · temp files.

**Windows** — Temp, Thumbnail DB, WER reports, DNS flush (auto) · Recycle Bin, Prefetch, Windows Update / Delivery Optimization, Font & GPU shader cache, WinSxS, Event logs, crash dumps (review, one explicit item each) · browser caches via the same Chromium/Firefox rules · developer caches (npm, NuGet, Gradle, Maven, Cargo, Go, JetBrains…).

> **Windows note** — this build's Windows-only calls (DISM, services, `wevtutil`) were not changed and could not be run in the CI sandbox; the engine, tiers, rules and guards are unit-tested.

#### Rules, not code
Path-based targets live in [`rules/linux.toml`](rules/linux.toml) and [`rules/windows.toml`](rules/windows.toml). A rule is data (`paths`, `mode`, `min_age_days`, `closed`, `keep`, `tier`…) — adding an app is a 6-line pull request that is easy to review. Personal rules go in `~/.config/cyber-clean/rules.d/*.toml`; they are forced into the **REVIEW** tier, limited to paths inside your home, and can never run unattended.

```toml
[[rule]]
id     = "my-app-cache"
target = "my_stuff"          # a target defined in the same file
mode   = "children"          # each sub-folder becomes one item you can tick
paths  = ["~/.cache/myapp"]
```

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
Checks GitHub Releases on startup (background thread, non-blocking) — only shows a badge, never downloads or installs without you clicking. Update requires an explicit click; download is verified against an Ed25519 signature baked into the app before anything is installed.

---

### [♪] System Tray & Auto-clean
Minimize to tray. Auto-clean runs **only AUTO-tier targets flagged `scheduled`** every 6 hours when idle (CPU < 20%, network < 500 KB/s) and uses a stricter age policy than a manual clean (e.g. browser caches only if the browser has not been used for 7 days). It never touches the Trash, orphaned packages, dev caches, Docker or anything in the REVIEW tier, never shows a password prompt, and pauses automatically when Game Mode is active.

---

## Compatibility

| OS | Version | Notes |
|----|---------|-------|
| Linux | Arch · Manjaro · EndeavourOS · CachyOS | pacman |
| Linux | Ubuntu · Debian · Pop!_OS · Mint · Kali | apt |
| Linux | Fedora · CentOS · Rocky · Nobara | dnf |
| Linux | openSUSE Leap / Tumbleweed | zypper |
| Linux | Void Linux | xbps |
| Linux | Alpine | apk (source install) |
| Linux | Fedora Atomic · Silverblue · Kinoite · Bazzite | rpm-ostree |
| Linux | NixOS | nix-collect-garbage (user profile) |
| Linux | Any derivative (Zorin, MX, Nobara, Garuda, KDE neon…) | detected through `ID_LIKE` in `/etc/os-release` |
| Windows | 10 (1903+) | Full support |
| Windows | 11 | Full support + EcoQoS |
| Windows | ARM64 (Surface Pro X, Snapdragon) | Supported |

---

## Security & Privacy

- **No telemetry** — zero data collection, zero network calls during normal operation
- **No background service** — only runs when you open it
- **Signed releases** — since v3.0.2, every release is signed with Ed25519; the public key ships inside the app, the private key never touches this repo. The updater refuses to install anything that isn't validly signed.
- **Scoped privilege** — Linux sudoers rule grants access only to `/usr/local/bin/cyber-clean-helper`, not blanket sudo. The helper is a readable shell script ([`packaging/cyber-clean-helper`](packaging/cyber-clean-helper)) you can audit. Because the rule is `NOPASSWD`, **every** argument is treated as hostile: package names must match a strict pattern and can never become an option (`--`), core packages (kernel, bootloader, init, sudo, network…) are refused, deletion paths must be canonical, symlink-free, inside `/var/log` / `/var/crash` / coredump and under root-owned directories, and the helper offers no arbitrary copy/move/delete/stop-service primitive.
- **Updates are verified twice** — the app checks the Ed25519 signature, then the root helper (`update-apply`) copies the package into a root-owned directory, **verifies the signature again**, rejects symlinks that escape the archive, requires a newer `VERSION` than the installed one (no downgrade/replay) and swaps the install atomically with rollback. `install.sh` verifies the same signature before unpacking.
- **What is deleted permanently** — AUTO-tier caches are regenerable and are removed permanently (the confirmation says so). Anything that could be your data (Trash, packages, Docker volumes…) is only removed from the REVIEW dialog, item by item.

---

## Build from source

```bash
git clone https://github.com/vuphitung/CyberClean.git
cd CyberClean

# Arch/Debian 12+/other PEP 668 distros block system-wide pip installs —
# use a venv (works everywhere, doesn't touch system Python):
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller

# Run directly
python main.py

# Build Linux binary
python3 build.py --linux

# Build Windows installer
python build.py --inno
```

**Requirements:** Python 3.10+ · PyQt6 · psutil · cryptography · PyInstaller

## Project Structure

```
CyberClean/
├── main.py                 # Main GUI (PyQt6)
├── ui_widgets.py           # Custom widgets, icons, background QThread workers
├── ui_pages.py             # DEEP CLEAN page (tier 2: review item by item) + DISK ADVISOR page (tier 3: report only)
├── version.py              # Single source of truth for version
├── rules/
│   ├── linux.toml          # Declarative clean rules (paths · age · closed-app · tier)
│   └── windows.toml
├── packaging/
│   └── cyber-clean-helper  # Privileged helper (root) — shipped inside the signed release
├── tests/                  # pytest: helper, engine, rules, cleaners, installer, UI
├── core/
│   ├── engine.py           # plan → preview → guarded execute (age / process / open files / symlink / mount)
│   ├── rules.py            # TOML rule loader + validator + plan builders (chromium / firefox / paths)
│   ├── privileged.py       # the only door to the root helper (argv, error classification)
│   ├── advisor.py          # report-only scanners (VMs, /opt, big files, old projects…)
│   ├── base_cleaner.py     # Cleaner interface, tiers, Review types, plan mixin
│   ├── linux_cleaner.py    # Linux code-driven targets (package managers, journal, Docker…)
│   ├── windows_cleaner.py  # Windows code-driven targets
│   ├── booster.py          # RAM / CPU / Game Mode / Smart Boost
│   ├── game_boost_widget.py # Game Mode UI panel (GPU/game-process monitor threads)
│   ├── analyzer.py         # Idle scheduler for auto-clean
│   ├── uninstaller.py      # App uninstaller
│   └── os_detect.py        # OS / distro / package manager detection
├── utils/
│   ├── sysinfo.py          # psutil system snapshot
│   ├── i18n.py             # English / Tiếng Việt translations
│   └── updater.py          # In-app OTA updater
├── assets/
│   ├── logo.png
│   └── logo.ico
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
