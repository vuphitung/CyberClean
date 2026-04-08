<div align="center">

```
  ██████╗██╗   ██╗██████╗ ███████╗██████╗      ██████╗██╗     ███████╗ █████╗ ███╗
 ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║     ██╔════╝██╔══██╗████╗
 ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝    ██║     ██║     █████╗  ███████║██╔██╗
 ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗    ██║     ██║     ██╔══╝  ██╔══██║██║╚██
 ╚██████╗   ██║   ██████╔╝███████╗██║  ██║    ╚██████╗███████╗███████╗██║  ██║██║ ╚█
  ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝     ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝
```

**Công cụ Dọn dẹp & Tối ưu Hiệu năng Hệ thống**
**Windows · Linux · Đa nền tảng · v2.2.4**

<br/>

> 🌐 **Ngôn ngữ:** [English](README.md) · **Tiếng Việt**

<br/>

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![Platform](https://img.shields.io/badge/Windows%20%7C%20Linux-Hỗ%20trợ-00c8e0?style=for-the-badge&logo=linux&logoColor=white)]()
[![License](https://img.shields.io/badge/Giấy%20phép-MIT-f0c040?style=for-the-badge)](LICENSE)
[![Release](https://img.shields.io/github/v/release/vuphitung/CyberClean?style=for-the-badge&color=c060f0)](https://github.com/vuphitung/CyberClean/releases/latest)

<br/>

---

<!-- Security Badge -->
<table>
<tr>
<td align="center" width="560">

```
╔══════════════════════════════════════════════╗
║  ✔  MICROSOFT DEFENDER SCAN — SẠCH          ║
║─────────────────────────────────────────────║
║  Kết quả  :  Không phát hiện mã độc         ║
║  Engine   :  Microsoft Security Intelligence ║
║  Sub ID   :  b632c14c-aff3-4ef6-97ab-...cd  ║
║  Trạng thái:  Hoàn tất ✓                    ║
╚══════════════════════════════════════════════╝
```

**CyberClean đã được quét độc lập bởi Microsoft Defender và không có mối đe dọa nào được phát hiện.**
Đây là kết quả tự nộp file để quét — không phải hợp tác hay chứng nhận từ Microsoft.
Không mã độc · Không thu thập dữ liệu · Không hành vi ẩn.

[![Scan Result](https://img.shields.io/badge/Microsoft%20Defender-Không%20Phát%20Hiện%20Mối%20Đe%20Dọa-0078D4?style=for-the-badge&logo=microsoftdefender&logoColor=white)](https://www.microsoft.com/en-us/wdsi/filesubmission)

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
<td align="center"><b>📊 Bảng điều khiển</b></td>
<td align="center"><b>🧹 Dọn dẹp Thông minh</b></td>
<td align="center"><b>🔍 Quét Bảo mật</b></td>
</tr>
</table>

</div>

---

## 📥 Cài đặt

### 🐧 Linux — Cài một lệnh

```bash
curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash
```

> Cài vào `/opt/CyberClean` · Tạo lệnh `cyberclean` · Đăng ký app vào launcher · Thiết lập helper NOPASSWD để leo quyền an toàn

**Gỡ cài đặt:**
```bash
sudo cyberclean --uninstall
```

### 🪟 Windows — Trình cài đặt

**[⬇ Tải CyberClean Setup v2.2.4 (.exe)](https://github.com/vuphitung/CyberClean/releases/latest)**

> UAC chỉ yêu cầu lần **đầu cài đặt** · Không có service chạy nền · Gỡ qua `Cài đặt → Ứng dụng → CyberClean`

> 💡 **Mẹo:** Luôn mở CyberClean từ **shortcut Desktop hoặc Start Menu** để tránh UAC. Ghim app đang chạy vào Taskbar sẽ bỏ qua rule Auto-Admin và UAC sẽ xuất hiện lại ở lần mở tiếp theo — đây là giới hạn của Windows, cũng xảy ra với MSI Afterburner và Rufus.

---

## ✨ Tính năng

### 📊 Bảng điều khiển Thời gian thực

Theo dõi hệ thống trực tiếp, tự động làm mới mỗi 4 giây.

- Mức dùng CPU từng nhân với biểu đồ lịch sử sparkline
- Mức dùng RAM / Swap và dung lượng khả dụng
- Vòng tròn dung lượng đĩa theo từng điểm mount
- Theo dõi nhiệt độ — nhiều nguồn dự phòng (psutil → `/sys/thermal` → WMI → PowerShell → LibreHardwareMonitor)
- Top tiến trình ngốn CPU và RAM với nút kill một chạm
- Đếm lưu lượng mạng I/O (đã gửi / đã nhận)
- Hiển thị thời gian hoạt động hệ thống
- Quản lý mục khởi động (XDG autostart + systemd trên Linux · Registry trên Windows)

---

### 🧹 Dọn dẹp Thông minh

Dọn dẹp đĩa an toàn, có thể hoàn tác với chế độ xem trước dry-run trước khi thực hiện bất kỳ thay đổi nào. Mỗi lần xóa đều được ghi log để hoàn tác thủ công. Mỗi mục tiêu được gắn nhãn **An toàn / Cẩn thận / Nguy hiểm**.

| Mục tiêu | Linux | Windows |
|----------|:-----:|:-------:|
| Cache trình quản lý gói (pacman / apt / dnf / zypper) | ✅ | — |
| Gói mồ côi | ✅ | — |
| Cache build AUR (yay / paru) | ✅ | — |
| Runtime Flatpak không dùng | ✅ | — |
| Ảnh Docker / Podman rác | ✅ | — |
| Log systemd journal (>7 ngày) | ✅ | — |
| Cache người dùng `~/.cache` — bảo vệ 3 lớp | ✅ | — |
| Cache trình duyệt (Chrome / Chromium / Firefox / Edge / Brave / Opera) | ✅ | ✅ |
| Cache thumbnail | ✅ | ✅ |
| Cache pip wheel | ✅ | — |
| File tạm (>3 ngày, không đang dùng) | ✅ | — |
| Windows Temp & `%TEMP%` — bảo vệ lock-probe | — | ✅ |
| Cache Prefetch (không dùng >7 ngày) | — | ✅ |
| Thùng rác | — | ✅ |
| Cache Windows Update | — | ✅ |
| Cache Delivery Optimization | — | ✅ |
| Database cache thumbnail | — | ✅ |
| Xóa DNS cache | — | ✅ |
| Log sự kiện (wevtutil) | — | ✅ |
| Báo cáo lỗi & crash dump Windows | — | ✅ |

**Hệ thống bảo vệ thông minh (v2.2.4):**
- **Bảo vệ cache Linux 3 lớp** — whitelist tên → phát hiện loại socket/FIFO → kiểm tra hoạt động gần đây. Các wallpaper daemon, compositor và công cụ IPC không rõ tên được tự động bảo vệ mà không cần cập nhật tên.
- **Bảo vệ temp Windows lock-probe** — kiểm tra từng file bằng exclusive open trước khi xóa. File bị khóa (đang được tiến trình dùng) bị bỏ qua im lặng thay vì gây lỗi dây chuyền.
- **Tích hợp send2trash** — file xóa đi vào Thùng rác hệ thống thay vì xóa vĩnh viễn khi có thể, mọi phiên dọn đều hoàn toàn có thể khôi phục.

---

### ⚡ Tăng tốc Hệ thống

Tối ưu hiệu năng không làm crash hay đơ máy. Mọi tính năng đều có thể hoàn tác hoàn toàn — tắt đi sẽ khôi phục trạng thái ban đầu chính xác.

| Tính năng | Linux | Windows |
|-----------|:-----:|:-------:|
| **Giải phóng RAM** — compact bộ nhớ không xóa page cache | ✅ | ✅ |
| **Tinh chỉnh bộ nhớ** — swappiness / dirty_ratio / vm params | ✅ | — |
| **Tinh chỉnh bộ nhớ (Windows)** — SetProcessWorkingSetSizeEx giải phóng trang RAM nhàn rỗi | — | ✅ |
| **Diệt Bloat** — tiến trình zombie + RAM cao nhàn rỗi (ngưỡng OOM động theo RAM) | ✅ | ✅ |
| **Xóa Cache GPU / Shader** — mesa, NVIDIA, Chrome, Edge + Flatpak / Snap | ✅ | ✅ |
| **🎮 Chế độ Game** — CPU jail 3 tầng theo hoạt động + governor hiệu năng | ✅ | ✅ |
| **🌿 Chế độ Eco** — cgroups v2 trên Linux · EcoQoS + memory priority trên Windows 11 | ✅ | ✅ |
| **⚡ Smart Boost** — tự phát hiện tier máy (Cao / Trung / Thấp) có tính VRAM GPU | ✅ | ✅ |
| **Monitor PSI Memory** — theo dõi áp lực RAM kernel Linux, tự diệt bloat khi tăng đột biến | ✅ | — |
| **Timer Resolution 1ms** — tick scheduler 1ms (mặc định 15.6ms) cho frame mượt hơn | — | ✅ |
| **Tắt TCP Nagle** — TcpAckFrequency + TCPNoDelay giảm độ trễ game online | — | ✅ |
| **Boost ưu tiên tiến trình Game** — game foreground được ABOVE_NORMAL_PRIORITY_CLASS | — | ✅ |
| **Tắt hiệu ứng trong suốt Windows** — tự động trên máy low-end để tiết kiệm tài nguyên | — | ✅ |
| **Tích hợp Feral GameMode** — nhường CPU governor cho `gamemoded` nếu đang chạy | ✅ | — |

#### 🎮 Chế độ Game — CPU Jail 3 Tầng Theo Hoạt Động

Ứng dụng nền được phân loại thành 3 tầng dựa trên CPU sampling thời gian thực:

| Tầng | Điều kiện | Hành động |
|------|-----------|-----------|
| **Đang hoạt động** | > 2% CPU | Chỉ giảm ưu tiên nhẹ — giữ tất cả nhân CPU. Discord đang call, YouTube nhạc: vẫn mượt. |
| **Comms/media nhàn rỗi** | ≤ 2% CPU | Giới hạn nửa nhân trên — vẫn phản hồi, domain nhỏ hơn. |
| **Bloat rõ ràng** | OneDrive, telemetry, update services | Nhốt vào nhân cuối + ưu tiên idle. Những thứ này không cần burst. |

> Lấy cảm hứng từ Process Lasso, Razer Cortex và Feral GameMode — nhưng mã nguồn mở và đa nền tảng.

#### ⚡ Smart Boost — Phát hiện Tier Máy

Phân loại máy dựa trên RAM, số nhân vật lý **và VRAM GPU** (qua Linux sysfs / Windows WMI):

| Tier | Tiêu chí | Chiến lược |
|------|----------|-----------|
| **CAO** | >16 GB RAM + >6 nhân, hoặc >8 GB + VRAM ≥ 6 GB | Chỉ Game Mode |
| **TRUNG** | >8 GB RAM + >4 nhân, hoặc >4 GB + VRAM ≥ 6 GB | Game Mode + Eco Mode |
| **THẤP** | Còn lại | Game Mode + Eco Mode + Giải phóng RAM + Tắt transparency |

---

### 🔍 Quét Bảo mật

Quét chỉ đọc — không tự động xóa gì. Bạn quyết định sửa cái gì.

- **Tiến trình đang chạy** — phát hiện crypto miner, reverse shell, tiến trình chạy từ `/tmp`
- **Kết nối mạng ra ngoài** — map kết nối TCP đã thiết lập đến tiến trình chủ sở hữu, gắn cờ cổng đáng ngờ (4444, 1337, 31337 và cổng RAT phổ biến), file thực thi từ thư mục temp
- **File SUID/SGID** — gắn cờ file setuid nằm ngoài whitelist an toàn
- **File hệ thống world-writable** — `/etc`, `/usr/local/bin`, `/usr/bin`
- **Cửa hậu cron** — quét tất cả thư mục cron + crontab người dùng tìm mẫu shell injection
- **File đáng ngờ** — `.sh/.py/.ps1/.bat/.vbs` trong thư mục temp/người dùng với mẫu độc hại
- **LD_PRELOAD hijack** — kiểm tra `/etc/ld.so.preload` và biến môi trường `$LD_PRELOAD`
- **SSH authorized_keys** — gắn cờ key forced-command và định dạng key không nhận ra
- **Giả mạo file hosts** — phát hiện redirect các domain uy tín (Google, GitHub, PayPal...)
- **Autorun Windows** — khóa registry HKCU/HKLM Run với từ khóa đáng ngờ (powershell -enc, mshta, wscript...)
- **Sửa một chạm** — strip SUID, chmod world-writable, xóa file đáng ngờ, tất cả qua helper có phạm vi

---

### 🗑️ Gỡ cài đặt Ứng dụng

Xóa ứng dụng đã cài sạch sẽ, không để lại rác.

- **Windows** — đọc từ registry Add/Remove Programs (không cần `wmic`)
- **Linux** — tích hợp trình quản lý gói gốc (pacman / apt / dnf)
- Hiển thị kích thước đã cài, phiên bản và ngày cài đặt
- Gỡ nền với log tiến trình trực tiếp

---

### 📜 Lịch sử & Hoàn tác

- Mỗi phiên dọn được ghi vào `~/.local/share/cyber-clean/history.jsonl`
- Log hoàn tác lưu đường dẫn, kích thước và loại của mỗi mục đã xóa
- Xem toàn bộ lịch sử với timestamp và dung lượng đã giải phóng mỗi phiên
- Fallback về `/tmp` trong môi trường read-only (container, chroot) — app vẫn chạy bình thường

---

### 🔄 Tự cập nhật Trong ứng dụng

- Kiểm tra GitHub Releases khi khởi động (QThread không chặn — không bao giờ đơ UI)
- Badge header + thông báo tray khi có phiên bản mới
- Tải xuống → thay thế → khởi động lại với thanh tiến trình trực tiếp
- Linux: thay binary tại chỗ và re-exec. Windows: chạy Inno Setup installer im lặng.
- Khóa single-instance — phát hiện tiến trình nền cũ, đề nghị force-kill trước khi khởi động lại
- Bảo vệ ARM64 — timer resolution và winmm được bỏ qua an toàn trên Snapdragon / Surface Pro X

---

### 🌐 Đa ngôn ngữ (i18n)

Bản dịch tích hợp sẵn: **English · Tiếng Việt · 中文 · Español · Français · Deutsch · 日本語 · 한국어 · Русский · Português · Italiano**

Tất cả chuỗi UI, thông báo tray và hộp thoại cập nhật đều được dịch đầy đủ.

---

### 🔔 System Tray & Tự dọn

- Thu nhỏ vào system tray — không cản trở bạn
- **Tự dọn** chạy các mục `safe` mỗi 6 giờ khi ẩn trong tray, chỉ khi hệ thống nhàn rỗi (CPU < 20%, mạng < 500 KB/s)
- Kiểm tra idle mỗi 5 phút — dọn khi cả CPU lẫn mạng đều yên tĩnh
- Tự dọn tự tạm dừng khi Game Mode đang hoạt động — không giảm FPS
- Thông báo tray khi hoàn thành kèm tóm tắt dung lượng đã giải phóng

---

## 🌐 Tương thích

| Hệ điều hành | Bản phân phối / Phiên bản | Ghi chú |
|--------------|--------------------------|---------|
| **Linux** | Arch · Manjaro · EndeavourOS · Garuda · CachyOS | pacman + AUR |
| **Linux** | Ubuntu · Debian · Pop!_OS · Mint · Kali | apt |
| **Linux** | Fedora · CentOS · Rocky · AlmaLinux | dnf |
| **Linux** | openSUSE Leap / Tumbleweed | zypper |
| **Linux** | Void Linux | xbps |
| **Windows** | Windows 10 (1903+) | Hỗ trợ đầy đủ |
| **Windows** | Windows 11 | Hỗ trợ đầy đủ + EcoQoS |
| **Windows** | ARM64 (Surface Pro X, Snapdragon) | Hỗ trợ — winmm/timer bỏ qua an toàn |

---

## 🛡️ Bảo mật & Quyền riêng tư

- **Không telemetry** — không thu thập dữ liệu, không gọi mạng trong quá trình hoạt động
- **Không service nền** — chỉ chạy khi bạn mở (hoặc tự dọn từ tray)
- **Đặc quyền có phạm vi** — quy tắc sudoers Linux chỉ cho phép truy cập `/usr/local/bin/cyber-clean-helper`, không phải sudo toàn bộ
- **Helper minh bạch** — tất cả thao tác đặc quyền đi qua shell script bạn có thể đọc và kiểm tra. Các thao tác được hỗ trợ: cache gói, journal, xóa gói mồ côi, drop-cache, fstrim, fix-suid, fix-writable, kill-pid, xóa gói, cập nhật OTA.
- **UAC Windows — hỏi một lần, không bao giờ hỏi lại** — trình cài đặt tạo Task Scheduler ẩn (`CyberClean_AutoAdmin`) lúc cài. Mỗi lần khởi động qua shortcut Desktop/Start Menu sau đó đều chạy im lặng không cần UAC, kể cả sau khi khởi động lại. Task bị xóa hoàn toàn khi gỡ cài đặt.
- **Quét malware độc lập** — file `.exe` đã được tự nộp lên Microsoft Defender online và trả về kết quả sạch. Submission ID: `b632c14c-aff3-4ef6-97ab-4058309bc4cd`
- **atexit + SIGTERM cleanup** — trạng thái cgroup và nice() được khôi phục ngay cả khi app crash giữa chừng

> ⚠️ **Lưu ý ghim Taskbar:** Click chuột phải vào app đang chạy và chọn "Pin to taskbar" ghim trực tiếp file `.exe` — cách này bỏ qua task Auto-Admin và UAC sẽ xuất hiện lại. Dùng **shortcut Desktop hoặc Start Menu** thay vào đó. Đây là giới hạn của Windows, cũng xảy ra với MSI Afterburner và Rufus.

---

## 🆚 So sánh CyberClean với đối thủ

| | CyberClean | BleachBit | CCleaner | Stacer | Process Lasso |
|--|:-:|:-:|:-:|:-:|:-:|
| **Dọn dẹp đĩa** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Quét bảo mật** | ✅ | ❌ | ❌ | Một phần | ❌ |
| **Game Mode / CPU jail** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Eco Mode (cgroups v2 / EcoQoS)** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Smart Boost (phát hiện tier)** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Timer resolution 1ms** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Tắt TCP Nagle (độ trễ game)** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Monitor PSI memory** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Linux + Windows** | ✅ | ✅ | ❌ | Chỉ Linux | ❌ |
| **Mã nguồn mở** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Không telemetry** | ✅ | ✅ | ❌ | ✅ | — |
| **Tự cập nhật trong app** | ✅ | ❌ | ✅ | ❌ | ✅ |
| **i18n 11 ngôn ngữ** | ✅ | Một phần | ✅ | Một phần | ❌ |

---

## 🔧 Build từ mã nguồn

**Yêu cầu:** Python 3.10+ · PyQt6 · psutil · PyInstaller

```bash
git clone https://github.com/vuphitung/CyberClean.git
cd CyberClean
pip install -r requirements.txt

# Chạy trực tiếp
python main.py

# Build Linux AppImage
python3 build.py --linux

# Build Windows .exe + Inno Setup installer
python build.py --inno
```

---

## 📁 Cấu trúc Dự án

```
CyberClean/
├── main.py                 # GUI chính (PyQt6) — icon QPainter-drawn, không cần SVG
├── version.py              # Nguồn sự thật duy nhất cho số phiên bản
├── core/
│   ├── base_cleaner.py     # Interface cleaner trừu tượng
│   ├── linux_cleaner.py    # Mục tiêu dọn Linux — bảo vệ 3 lớp thông minh
│   ├── windows_cleaner.py  # Mục tiêu dọn Windows — bảo vệ lock-probe
│   ├── scanner.py          # Quét bảo mật + mapper kết nối mạng
│   ├── booster.py          # RAM / CPU / Game Mode / Smart Boost / PSI monitor
│   ├── analyzer.py         # Lập lịch idle · Xem kết nối mạng
│   ├── uninstaller.py      # Gỡ ứng dụng (registry / trình quản lý gói)
│   └── os_detect.py        # Phát hiện OS / distro / trình quản lý gói / Wayland
├── utils/
│   ├── sysinfo.py          # Snapshot hệ thống psutil (cache thread-safe)
│   ├── i18n.py             # Dịch 11 ngôn ngữ
│   └── updater.py          # Cập nhật OTA trong app (QThread, GitHub Releases API)
├── assets/
│   ├── logo.png            # Icon app
│   ├── logo.ico            # Icon Windows
│   └── icons/              # Icon nav QPainter-drawn (không có file SVG)
├── LibreHardwareMonitorLib.dll  # Nhiệt độ Windows (MSR kernel driver)
└── install.sh              # Trình cài Linux một lệnh (tự phát hiện phiên bản mới nhất)
```

---

## 📄 Giấy phép

MIT — xem [LICENSE](LICENSE)

---

<div align="center">

Làm bằng ☕ bởi [vuphitung](https://github.com/vuphitung) — sinh viên Việt Nam 🇻🇳

*Nếu CyberClean giúp bạn lấy lại dung lượng đĩa hoặc cải thiện hiệu năng, hãy cho nó một ⭐ nhé*

🌐 [View English README](README.md)

</div>
