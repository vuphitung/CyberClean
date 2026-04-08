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
**Windows · Linux · Cross-platform · v2.2.4**

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

**[⬇ Download CyberClean Setup v2.2.4 (.exe)](https://github.com/vuphitung/CyberClean/releases/latest)**

> UAC elevation on **first install only** · No background services · Uninstall via `Settings → Apps → CyberClean`

> 💡 **Tip:** Always launch CyberClean from the **Desktop or Start Menu shortcut** to avoid UAC prompts. Pinning the running app directly to the Taskbar bypasses the Auto-Admin rule and will trigger UAC on next launch — this is a Windows limitation shared by apps like MSI Afterburner and Rufus.

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

| Target | Linux | Windows |
|--------|:-----:|:-------:|
| Package manager cache (pacman / apt / dnf / zypper) | ✅ | — |
| Orphaned packages | ✅ | — |
| AUR build cache (yay / paru) | ✅ | — |
| Flatpak unused runtimes | ✅ | — |
| Docker / Podman dangling images | ✅ | — |
| systemd journal logs (>7 days) | ✅ | — |
| User cache `~/.cache` — 3-layer smart guard | ✅ | — |
| Browser cache (Chrome / Chromium / Firefox / Edge / Brave / Opera) | ✅ | ✅ |
| Thumbnail cache | ✅ | ✅ |
| pip wheel cache | ✅ | — |
| Temp files (>3 days, not in use) | ✅ | — |
| Windows Temp & `%TEMP%` — lock-probe guard | — | ✅ |
| Prefetch cache (unused >7 days) | — | ✅ |
| Recycle Bin | — | ✅ |
| Windows Update cache | — | ✅ |
| Delivery Optimization cache | — | ✅ |
| Thumbnail cache DB | — | ✅ |
| DNS cache flush | — | ✅ |
| Event logs (wevtutil) | — | ✅ |
| Windows Error Reports & crash dumps | — | ✅ |

**Smart guard system (v2.2.4):**
- **3-layer Linux cache guard** — name whitelist → socket/FIFO type detection → recent-activity check. Unknown wallpaper daemons, compositors, and IPC tools are automatically protected without needing a name update.
- **Lock-probe Windows temp guard** — probes each file for an exclusive open before deleting. Locked files (held by a running process) are skipped silently instead of causing cascade errors.
- **send2trash integration** — deleted files go to the system Trash instead of permanent deletion when available, making every clean session fully recoverable.

---

### ⚡ System Booster

Performance optimization without crashing or freezing your system. Every feature is fully reversible — turning off restores the exact original state.

| Feature | Linux | Windows |
|---------|:-----:|:-------:|
| **Free RAM** — compact memory without evicting page cache | ✅ | ✅ |
| **Memory Tune** — swappiness / dirty_ratio / vm params | ✅ | — |
| **Memory Tune (Windows)** — SetProcessWorkingSetSizeEx trims idle process pages | — | ✅ |
| **Kill Bloat** — zombie + idle high-RAM processes (dynamic OOM threshold by RAM size) | ✅ | ✅ |
| **Clear GPU / Shader Cache** — mesa, NVIDIA, Chrome, Edge + Flatpak / Snap paths | ✅ | ✅ |
| **🎮 Game Mode** — 3-tier activity-aware CPU jail + performance governor | ✅ | ✅ |
| **🌿 Eco Mode** — cgroups v2 on Linux · EcoQoS + memory priority on Windows 11 | ✅ | ✅ |
| **⚡ Smart Boost** — auto-detects PC tier (High / Mid / Low) with GPU VRAM scoring | ✅ | ✅ |
| **PSI Memory Monitor** — Linux kernel pressure stall info, auto kill-bloat on spike | ✅ | — |
| **Timer Resolution** — 1ms scheduler tick (vs default 15.6ms) for smoother frames | — | ✅ |
| **TCP Nagle Disable** — TcpAckFrequency + TCPNoDelay for lower online game latency | — | ✅ |
| **Game Process Priority Boost** — foreground game gets ABOVE_NORMAL_PRIORITY_CLASS | — | ✅ |
| **Windows Transparency Disable** — auto on low-end tier for extra perf headroom | — | ✅ |
| **Feral GameMode integration** — defers CPU governor to `gamemoded` if present | ✅ | — |

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
| **HIGH** | >16 GB RAM + >6 cores, or >8 GB + VRAM ≥ 6 GB | Game Mode only |
| **MID** | >8 GB RAM + >4 cores, or >4 GB + VRAM ≥ 6 GB | Game Mode + Eco Mode |
| **LOW** | Everything else | Game Mode + Eco Mode + Free RAM + disable transparency |

---

### 🔍 Security Scanner

Read-only deep scan — nothing is deleted automatically. You decide what to fix.

- **Running processes** — detect crypto miners, reverse shells, processes spawned from `/tmp`
- **Outbound network connections** — map established TCP connections to owning process, flag suspicious ports (4444, 1337, 31337 and common RAT ports), executables running from temp dirs
- **SUID/SGID binaries** — flag unexpected setuid files outside the known-safe whitelist
- **World-writable system files** — `/etc`, `/usr/local/bin`, `/usr/bin`
- **Cron backdoors** — scan all cron directories + user crontab for shell injection patterns
- **Suspicious files** — `.sh/.py/.ps1/.bat/.vbs` in temp/user dirs with malicious patterns
- **LD_PRELOAD hijacks** — `/etc/ld.so.preload` and `$LD_PRELOAD` env check
- **SSH authorized_keys** — flag forced-command keys and unrecognised key formats
- **Hosts file tampering** — detect redirects of trusted domains (Google, GitHub, PayPal...)
- **Windows autoruns** — HKCU/HKLM Run keys with suspicious keywords (powershell -enc, mshta, wscript...)
- **One-click fix** — SUID strip, world-writable chmod, suspicious file removal, all via scoped helper

---

### 🗑️ App Uninstaller

Remove installed applications cleanly, no leftovers.

- **Windows** — reads from Add/Remove Programs registry (no `wmic` dependency)
- **Linux** — native package manager (pacman / apt / dnf) integration
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
| **Linux** | Ubuntu · Debian · Pop!_OS · Mint · Kali | apt |
| **Linux** | Fedora · CentOS · Rocky · AlmaLinux | dnf |
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

## 🆚 How CyberClean Compares

| | CyberClean | BleachBit | CCleaner | Stacer | Process Lasso |
|--|:-:|:-:|:-:|:-:|:-:|
| **Disk cleaner** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Security scanner** | ✅ | ❌ | ❌ | Partial | ❌ |
| **Game Mode / CPU jail** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Eco Mode (cgroups v2 / EcoQoS)** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Smart Boost (tier detection)** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Timer resolution 1ms** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **TCP Nagle disable (game latency)** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **PSI memory pressure monitor** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Linux + Windows** | ✅ | ✅ | ❌ | Linux only | ❌ |
| **Open source** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **No telemetry** | ✅ | ✅ | ❌ | ✅ | — |
| **In-app auto-update** | ✅ | ❌ | ✅ | ❌ | ✅ |
| **11-language i18n** | ✅ | Partial | ✅ | Partial | ❌ |

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
│   ├── base_cleaner.py     # Abstract cleaner interface
│   ├── linux_cleaner.py    # Linux clean targets — 3-layer smart guard
│   ├── windows_cleaner.py  # Windows clean targets — lock-probe guard
│   ├── scanner.py          # Security scanner + network process mapper
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
