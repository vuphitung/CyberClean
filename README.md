<div align="center">

```
  ██████╗██╗   ██╗██████╗ ███████╗██████╗      ██████╗██╗     ███████╗ █████╗ ███╗
 ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║     ██╔════╝██╔══██╗████╗
 ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝    ██║     ██║     █████╗  ███████║██╔██╗
 ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗    ██║     ██║     ██╔══╝  ██╔══██║██║╚██
 ╚██████╗   ██║   ██████╔╝███████╗██║  ██║    ╚██████╗███████╗███████╗██║  ██║██║ ╚█
  ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝
```

**Smart System Cleaner & Performance Optimizer**
**Windows · Linux · Cross-platform · v3.0.0**

<br/>

> 🌐 **Language:** **English** · [Tiếng Việt](README_vi.md)

<br/>

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![Platform](https://img.shields.io/badge/Windows%20%7C%20Linux-supported-00c8e0?style=for-the-badge&logo=linux&logoColor=white)]()
[![License](https://img.shields.io/badge/License-MIT-f0c040?style=for-the-badge)](LICENSE)
[![Release](https://img.shields.io/github/v/release/vuphitung/CyberClean?style=for-the-badge&color=c060f0)](https://github.com/vuphitung/CyberClean/releases/latest)

<br/>

---

<!-- Security Badge -->
<table>
<tr>
<td align="center" width="560">

```
╔══════════════════════════════════════════════╗
║  ✔  MICROSOFT DEFENDER SCAN — NO THREAT      ║
║─────────────────────────────────────────────║
║  Result  :  No malicious code detected       ║
║  Engine  :  Microsoft Security Intelligence  ║
║  Sub ID  :  b632c14c-aff3-4ef6-97ab-...cd   ║
║  Status  :  Completed ✓                      ║
╚══════════════════════════════════════════════╝
```

**CyberClean passed an independent malware scan by Microsoft Defender.**
This is a self-submitted scan result — not a Microsoft partnership or endorsement.
No malicious code · No telemetry · No hidden behavior.

[![Scan Result](https://img.shields.io/badge/Microsoft%20Defender-No%20Threat%20Detected-0078D4?style=for-the-badge&logo=microsoftdefender&logoColor=white)](https://www.microsoft.com/en-us/wdsi/filesubmission)

<img src="screenshots/Microsoft-Security.png" width="580"/>

</td>
</tr>
</table>

<br/>

---

<table>
<tr>
<td><img src="screenshots/dashboard.png" width="480"/></td>
<td><img src="screenshots/clean.png" width="480"/></td>
<td><img src="screenshots/scanner.png" width="480"/></td>
</tr>
<tr>
<td align="center"><b>📊 Dashboard</b></td>
<td align="center"><b>🧹 Smart Clean</b></td>
<td align="center"><b>🔍 Security Scanner</b></td>
</tr>
</table>

</div>

---

## 📥 Installation

### 🐧 Linux — One-line install

```bash
curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash
```

> Installs to `/opt/CyberClean` · Creates `cyberclean` command · Registers app in launcher · Sets up NOPASSWD helper for safe privilege escalation

**Uninstall:**
```bash
sudo cyberclean --uninstall
```

### 🪟 Windows — Installer

**[⬇ Download CyberClean Setup v3.0.0 (.exe)](https://github.com/vuphitung/CyberClean/releases/latest)**

> UAC elevation on **first install only** · No background services · Uninstall via `Settings → Apps → CyberClean`

---

## ✨ Features

### 📊 Real-time Dashboard

Live system monitoring, auto-refreshes every 4 seconds.

- CPU usage per core with sparkline history chart
- RAM / Swap usage and available memory readout
- Disk usage rings per mount point
- Temperature monitoring — multi-source fallback (psutil → `/sys/thermal` → WMI → PowerShell → LibreHardwareMonitor)
- Top CPU and Memory processes with one-click kill
- Network I/O counters (sent / received)
- System uptime display
- Startup items manager (XDG autostart + systemd on Linux · Registry on Windows)

---

### 🧹 Smart Clean

Safe, reversible disk cleanup with dry-run preview before touching anything.
Every deletion is logged for manual rollback. Each target is labelled **Safe / Caution / Danger**.

#### Linux targets

| Target | Notes |
|--------|-------|
| Package manager cache (pacman / apt / dnf / zypper / xbps) | Keeps latest version(s) only |
| Orphaned packages | pacman / xbps |
| AUR build cache (yay / paru) | `~/.cache/yay` and `~/.cache/paru` |
| Flatpak unused runtimes | Requires Flatpak ≥ 1.9.0 for dry-run |
| Docker / Podman dangling images & stopped containers | Auto-detects podman or docker |
| Snap old revisions | Disabled revisions only — current install kept |
| systemd journal logs (> 7 days) | `journalctl --vacuum-time=7d` |
| User cache `~/.cache` — 3-layer smart guard | See guard details below |
| Browser cache — Chrome / Chromium / Firefox / Brave / Opera | All profiles (Default + Profile N) |
| Thumbnail cache | `~/.cache/thumbnails` |
| pip wheel cache | `~/.cache/pip` |
| Temp files (> 3 days, not in use) | Skip symlinks, sockets, FIFOs |

#### Windows targets

| Target | Notes |
|--------|-------|
| Windows Temp & `%TEMP%` — lock-probe guard | Files older than 24 h, skips locked files |
| Prefetch cache (> 7 days unused) | `.pf` files |
| Recycle Bin | All items |
| Windows Update cache | `SoftwareDistribution\Download` |
| Delivery Optimization cache | P2P update cache |
| Thumbnail cache DB | `thumbcache_*.db` — auto-rebuilds |
| Font Cache | `FontCache*.dat` — service stopped before delete, restarted after |
| GPU Shader Cache | DirectX / per-user shader cache — rebuilt on next launch |
| WinSxS Cleanup | DISM `/StartComponentCleanup` — removes superseded components only, never touches live ones |
| DNS cache flush | `ipconfig /flushdns` |
| Event logs | `wevtutil cl` all channels |
| Windows Error Reports & crash dumps | `%LOCALAPPDATA%\Microsoft\Windows\WER` |
| Browser cache — Chrome / Edge / Brave / Firefox / Vivaldi / Cốc Cốc | All profiles (Default + Profile N) |

**Smart guard system:**
- **3-layer Linux cache guard** — name whitelist → socket/FIFO/device type detection → recent-activity check (< 30 s). Unknown wallpaper daemons, compositors, and IPC tools are automatically protected without needing a name update.
- **Lock-probe Windows temp guard** — probes each file for an exclusive open before deleting. Locked files (held by a running process) are skipped silently instead of causing cascade errors.
- **WinSxS safety** — estimate via `DISM /AnalyzeComponentStore`, cleanup via `DISM /StartComponentCleanup`. CyberClean never deletes WinSxS entries directly.
- **Font Cache service guard** — stops `FontCache` service before delete, restarts after. Without this, files are locked and deletion fails silently.
- **send2trash integration** — deleted files go to the system Trash instead of permanent deletion when available, making every clean session fully recoverable.

---

### ⚡ System Booster

Performance optimization without crashing or freezing your system. Every feature is fully reversible — turning off restores the exact original state.

| Feature | Linux | Windows |
|---------|:-----:|:-------:|
| **Free RAM** — compact memory without evicting page cache | ✅ | ✅ |
| **Memory Tune** — swappiness / dirty_ratio / vm params | ✅ | — |
| **Memory Tune (Windows)** — `SetProcessWorkingSetSizeEx` trims idle process working sets | — | ✅ |
| **Kill Bloat** — zombie + idle high-RAM processes (dynamic OOM threshold by RAM size) | ✅ | ✅ |
| **Clear GPU / Shader Cache** — mesa, NVIDIA, Chrome, Edge + Flatpak / Snap paths | ✅ | ✅ |
| **🎮 Game Mode** — 3-tier activity-aware CPU jail + performance governor | ✅ | ✅ |
| **🌿 Eco Mode** — cgroups v2 on Linux · EcoQoS + memory priority on Windows 11 | ✅ | ✅ |
| **⚡ Smart Boost** — auto-detects PC tier (High / Mid / Low) with GPU VRAM scoring | ✅ | ✅ |
| **PSI Memory Monitor** — Linux kernel pressure stall info, auto kill-bloat on spike | ✅ | — |
| **Timer Resolution 1ms** — scheduler tick 1 ms (vs default 15.6 ms) for smoother frames | — | ✅ |
| **TCP Nagle Disable** — `TcpAckFrequency` + `TCPNoDelay` for lower online game latency | — | ✅ |
| **Game Process Priority Boost** — foreground game gets `ABOVE_NORMAL_PRIORITY_CLASS` | — | ✅ |
| **Windows Transparency Disable** — auto on low-end tier for extra perf headroom | — | ✅ |
| **Feral GameMode integration** — defers CPU governor to `gamemoded` if running | ✅ | — |

#### 🎮 Game Mode — 3-tier Activity-Aware CPU Jail

Background apps are classified into three tiers based on real-time CPU sampling:

| Tier | Condition | Action |
|------|-----------|--------|
| **Active** | > 2% CPU | Soft-throttle only — lower priority but keep all cores. Discord screen share, YouTube music: stays smooth. |
| **Idle comms/media** | ≤ 2% CPU | Restrict to upper half of cores — still responsive, just smaller domain. |
| **Known bloat** | OneDrive, telemetry, update services | Hard-jail onto last core + idle priority. These should never burst. |

> Inspired by Process Lasso, Razer Cortex, and Feral GameMode — but open source and cross-platform.

#### ⚡ Smart Boost — PC Tier Detection

Classifies your machine using RAM, physical core count, **and GPU VRAM** (via Linux sysfs / Windows WMI):

| Tier | Criteria | Strategy |
|------|----------|----------|
| **HIGH** | > 16 GB RAM + > 6 cores, or > 8 GB + VRAM ≥ 6 GB | Game Mode only |
| **MID** | > 8 GB RAM + > 4 cores, or > 4 GB + VRAM ≥ 6 GB | Game Mode + Eco Mode |
| **LOW** | Everything else | Game Mode + Eco Mode + Free RAM + disable transparency |

---

### 🔍 Security Scanner — Threat Scoring Engine

Read-only deep scan — nothing is deleted automatically. You decide what to fix.

#### How it works — Threat Scoring Matrix

Every process goes through 5 stages instead of being flagged on a single rule:

1. **Evidence Gathering** — exe path, cmdline, CPU%, established TCP connections
2. **Whitelist bypass** — Chromium gpu-process, AppImage mounts, PyInstaller bundles, Docker, user custom whitelist all get a free pass
3. **Threat scoring** — additive multi-dimensional matrix (below)
4. **Watchlist** — score 40–69 → saved to `watchlist.json`, re-checked every 5 minutes
5. **Verdict** — < 40 ignore, 40–69 warn, ≥ 70 critical + offer kill

| Score delta | Reason |
|:-----------:|--------|
| +60 | Known crypto miner process name |
| +50 | Fake system process name (e.g. `svchost.exe` not in System32) |
| +40 | Executable inside `/tmp`, `/dev/shm`, `%TEMP%` (not AppImage/PyInstaller) |
| +40 | Cmdline pattern: reverse shell, `curl\|bash`, `base64 eval`, `LD_PRELOAD` |
| +35 | Known C2 / miner / RAT port (4444, 1337, 31337, 3333, …) |
| +30 | CPU > 80% sustained (miner behaviour) |
| +20 | High ephemeral port > 49151 + not localhost |
| +20 | Multiple outbound connections from same process (botnet behaviour) |
| −15 | Python / Node / Java / Ruby runtime interpreter |
| −20 | Executable in `/usr`, `/bin`, `/opt`, `Program Files` |
| −30 | Windows: valid digital signature |
| −40 | AppImage mount `/tmp/.mount_*` |
| −40 | PyInstaller bundle `/tmp/_MEI*` |
| −50 | Path matches `user_whitelist.json` |

#### Persistent intelligence

- **Watchlist** (`watchlist.json`) — processes scoring 40–69 are tracked with timestamp + score + reasons. Auto-escalates to critical if score rises on re-check.
- **User whitelist** (`user_whitelist.json`) — click "Mark as safe" on a false positive. Grants −50 on all future scans. Teach the scanner about your environment.
- **Hash cache** (`exe_hash_cache.json`) — SHA-256 of each binary after first scan. Re-scans only changed binaries on next run — ~3× faster. Also detects patched/replaced binaries between scans.

#### What it scans

- **Running processes** — crypto miners, reverse shells, processes spawned from `/tmp` / temp dirs
- **Outbound network connections** — maps established TCP connections to owning process, flags suspicious ports
- **SUID/SGID binaries** — flags unexpected setuid files outside the known-safe whitelist
- **World-writable system files** — `/etc`, `/usr/local/bin`, `/usr/bin`
- **Cron backdoors** — all cron directories + user crontab for shell injection patterns
- **Suspicious files** — `.sh/.py/.ps1/.bat/.vbs` in temp/user dirs with malicious patterns
- **LD_PRELOAD hijacks** — `/etc/ld.so.preload` and `$LD_PRELOAD` env check
- **SSH authorized_keys** — flags forced-command keys and unrecognised key formats
- **Hosts file tampering** — detects redirects of trusted domains (Google, GitHub, PayPal, …)
- **Windows autoruns** — HKCU/HKLM Run keys with suspicious keywords (`powershell -enc`, `mshta`, `wscript`, …)
- **One-click fix** — SUID strip, world-writable chmod, suspicious file removal, all via scoped helper

> **Honest limits:** CyberClean cannot detect Ring-0 rootkits, UEFI implants, or kernel driver exploits — those operate below Python/psutil. What it does well: miners, scripts in `/tmp`, cron backdoors, hosts hijacks, processes running from temp dirs — the threats that are common and practical.

---

### 🗑️ App Uninstaller

Remove installed applications cleanly, no leftovers.

- **Windows** — reads from Add/Remove Programs registry (no `wmic` dependency)
- **Linux** — native package manager integration (pacman / apt / dnf)
- Displays installed size, version, and install date
- Background uninstall with live progress log

---

### 📜 History & Rollback

- Every clean session is logged to `~/.local/share/cyber-clean/history.jsonl`
- Rollback log stores path, size, and type of every deleted item
- View full history with timestamps and freed space per session
- Fallback to `/tmp` in read-only environments (containers, chroot) — app still launches

---

### 🔄 In-App Auto-Updater

- Checks GitHub Releases on startup (non-blocking QThread — never freezes the UI)
- Header badge + tray notification when a new version is available
- One-click download → replace → restart with live progress bar
- Linux: replaces binary in-place and re-exec's. Windows: runs Inno Setup installer silently.
- Single-instance lock — detects stale background processes, offers force-kill before relaunching
- ARM64 guard — timer resolution and winmm calls safely skipped on Snapdragon / Surface Pro X

---

### 🌐 Multi-language (i18n)

Built-in translations: **English · Tiếng Việt · 中文 · Español · Français · Deutsch · 日本語 · 한국어 · Русский · Português · Italiano**

All UI strings, tray messages, and update dialogs are fully translated.

---

### 🔔 System Tray & Auto-clean

- Minimize to system tray — stays out of your way
- **Auto-clean** runs `safe` targets every 6 hours while hidden in tray, only when the system is idle (CPU < 20%, network < 500 KB/s)
- Idle check runs every 5 minutes — cleans only if *both* CPU and network are quiet
- Auto-clean pauses automatically when Game Mode is active — no FPS drops
- Tray notification on completion with freed space summary

---

## 🌐 Compatibility

| OS | Distro / Version | Notes |
|----|-----------------|-------|
| **Linux** | Arch · Manjaro · EndeavourOS · Garuda · CachyOS | pacman + AUR |
| **Linux** | Ubuntu · Debian · Pop!_OS · Mint · Kali · Parrot | apt |
| **Linux** | Fedora · CentOS · Rocky · AlmaLinux · Nobara | dnf |
| **Linux** | openSUSE Leap / Tumbleweed | zypper |
| **Linux** | Void Linux | xbps |
| **Windows** | Windows 10 (1903+) | Full support |
| **Windows** | Windows 11 | Full support + EcoQoS |
| **Windows** | ARM64 (Surface Pro X, Snapdragon) | Supported — winmm/timer skipped safely |

---

## 🛡️ Security & Privacy

- **No telemetry** — zero data collection, zero network calls during operation
- **No background service** — only runs when you open it (or auto-clean from tray)
- **Scoped privilege** — Linux sudoers rule grants access only to `/usr/local/bin/cyber-clean-helper`, not blanket sudo
- **Transparent helper** — all privileged operations go through a shell script you can read and audit. Supported ops: package cache, journal, orphan removal, drop-cache, fstrim, fix-suid, fix-writable, kill-pid, package removal, OTA update-replace.
- **Windows UAC — ask once, never again** — installer creates a hidden Task Scheduler entry (`CyberClean_AutoAdmin`) at install time. Every subsequent launch via Desktop/Start Menu shortcut runs silently with no UAC prompt, even after reboot. The task is fully removed on uninstall.
- **Independent malware scan** — the `.exe` was self-submitted to Microsoft Defender's online scanner and returned clean. Submission ID: `b632c14c-aff3-4ef6-97ab-4058309bc4cd`
- **atexit + SIGTERM cleanup** — cgroup and nice() state are restored even if the app crashes mid-boost

> ⚠️ **Taskbar pin note:** Right-clicking the running app and choosing "Pin to taskbar" pins the `.exe` directly — this bypasses the Auto-Admin task and UAC will reappear. Use the **Desktop or Start Menu shortcut** instead. This is a Windows limitation also seen in MSI Afterburner and Rufus.

---
## 🔧 Build from source

**Requirements:** Python 3.10+ · PyQt6 · psutil · PyInstaller

```bash
git clone https://github.com/vuphitung/CyberClean.git
cd CyberClean
pip install -r requirements.txt

# Run directly
python main.py

# Build Linux AppImage
python3 build.py --linux

# Build Windows .exe + Inno Setup installer
python build.py --inno
```

---

## 📁 Project Structure

```
CyberClean/
├── main.py                 # Main GUI (PyQt6) — QPainter-drawn icons, no SVG deps
├── version.py              # Single source of truth for version number
├── core/
│   ├── base_cleaner.py     # Abstract cleaner interface + shared helpers
│   ├── linux_cleaner.py    # Linux clean targets — 3-layer smart guard
│   ├── windows_cleaner.py  # Windows clean targets — lock-probe + WinSxS + Font Cache
│   ├── scanner.py          # Security scanner — threat scoring engine + watchlist + hash cache
│   ├── booster.py          # RAM / CPU / Game Mode / Smart Boost / PSI monitor
│   ├── analyzer.py         # Idle scheduler · Network connection view
│   ├── uninstaller.py      # App uninstaller (registry / package manager)
│   └── os_detect.py        # OS / distro / package manager / Wayland detection
├── utils/
│   ├── sysinfo.py          # psutil system snapshot (thread-safe cache)
│   ├── i18n.py             # 11-language translations
│   └── updater.py          # In-app OTA updater (QThread, GitHub Releases API)
├── assets/
│   ├── logo.png            # App icon
│   ├── logo.ico            # Windows icon
│   └── icons/              # QPainter-drawn nav icons (no SVG files)
├── LibreHardwareMonitorLib.dll  # Windows temperature (MSR kernel driver)
└── install.sh              # Linux one-line installer (auto-detects latest version)
```

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

Made with ☕ by [vuphitung](https://github.com/vuphitung) — a Vietnamese student 🇻🇳

*If CyberClean helped you reclaim disk space or boost performance, consider giving it a ⭐*

🌐 [Xem README tiếng Việt](README_vi.md)

</div>
