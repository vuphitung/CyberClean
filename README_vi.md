<div align="center">

<!-- Animated Cyber Wave Banner --> <img src="https://capsule-render.vercel.app/api?type=waving&color=0:060911,50:00c8e0,100:c060f0&height=120&section=header&animation=fadeIn" width="100%" alt="header" />

<a href="https://github.com/vuphitung/CyberClean"> <img src="assets/banner.svg" width="100%" alt="CyberClean — Smart System Cleaner &amp; Disk Manager" /> </a>

**Tiện ích desktop cho Windows và Linux: giám sát hệ thống, dọn dẹp ổ đĩa, báo cáo dung lượng, gỡ ứng dụng và bộ tăng tốc tùy chọn.**

<a href="README.md"><img src="https://img.shields.io/badge/LANG-ENGLISH-334155?style=for-the-badge&labelColor=0E1626" alt="English"></a>  <a href="README_vi.md"><img src="https://img.shields.io/badge/LANG-TI%E1%BA%BENG_VI%E1%BB%86T-00E5FF?style=for-the-badge&labelColor=0E1626" alt="Tiếng Việt"></a>

</div>

## Cài đặt nhanh (Quick Installation)

Chọn hệ điều hành của bạn và làm theo hướng dẫn bên dưới.

### <img src="https://cdn.simpleicons.org/linux/00E5FF" width="18" height="18" align="absmiddle" />  Linux

<p> <img src="https://img.shields.io/badge/Arch-1793D1?style=flat-square&logo=archlinux&logoColor=white" alt="Arch"> <img src="https://img.shields.io/badge/Ubuntu-E95420?style=flat-square&logo=ubuntu&logoColor=white" alt="Ubuntu"> <img src="https://img.shields.io/badge/Debian-A81D33?style=flat-square&logo=debian&logoColor=white" alt="Debian"> <img src="https://img.shields.io/badge/Fedora-51A2DA?style=flat-square&logo=fedora&logoColor=white" alt="Fedora"> <img src="https://img.shields.io/badge/openSUSE-73BA25?style=flat-square&logo=opensuse&logoColor=white" alt="openSUSE"> </p>

Cài đặt bằng một lệnh:

```
curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash

```

Ứng dụng được cài vào `/opt/CyberClean`, đăng ký lệnh `cyberclean` và thiết lập helper đặc quyền có phạm vi giới hạn.

<details> <summary>Gỡ cài đặt CyberClean</summary>

```
sudo cyberclean --uninstall

```

</details>

### <img src="https://img.shields.io/badge/-Windows_10\_%2F_11-0078D6?style=flat-square&logo=windows&logoColor=white" height="22" align="absmiddle" />

<p> <a href="https://github.com/vuphitung/CyberClean/releases/latest"> <img src="https://img.shields.io/badge/T%E1%BA%A2I_B%E1%BB%98_C%C3%80I_WINDOWS-(.EXE)-00E5FF?style=for-the-badge&logo=windows&logoColor=060911&labelColor=0E1626" alt="Tải CyberClean cho Windows" /> </a> </p>

[**Tải CyberClean cho Windows (.exe)**](https://github.com/vuphitung/CyberClean/releases/latest)

Ứng dụng yêu cầu quyền quản trị (UAC) khi mở để thực hiện các tác vụ dọn rác cấp hệ thống, tối ưu SSD TRIM và đọc cảm biến nhiệt độ CPU. Gỡ qua **Settings → Apps → CyberClean**.

## Giới thiệu

CyberClean hiển thị số liệu hệ thống theo thời gian thực, tìm các tệp có thể dọn, báo cáo dung lượng đã đi đâu, gỡ ứng dụng, và có thể áp dụng một bộ tinh chỉnh hiệu năng có thể hoàn tác khi bạn chơi game hoặc làm việc. Ứng dụng viết bằng PyQt6, có giao diện tối và sáng, ngôn ngữ tiếng Anh và tiếng Việt.

Mục dọn chỉ gồm tệp và cache. CyberClean không phải phần mềm diệt virus và không dọn registry. Hiệu năng phụ thuộc vào máy và khối lượng công việc; ứng dụng không hứa hẹn mức tăng tốc cụ thể.

## Ảnh chụp màn hình

*Windows 10, giao diện tối.*

**Dashboard** — số liệu trực tiếp, bảo trì một chạm, tiến trình nặng nhất, dung lượng từng ổ <img src="screenshots/dashboard.png" alt="Dashboard" width="100%">

**Clean** — cache có thể tạo lại, xem trước (dry-run), ước tính dung lượng giải phóng <img src="screenshots/clean.png" alt="Clean" width="100%">

**Deep Clean** — từng mục do bạn tự chọn <img src="screenshots/deep-clean.png" alt="Deep Clean" width="100%">

**Disk Advisor** — dung lượng đã đi đâu (chỉ báo cáo) <img src="screenshots/disk-advisor.png" alt="Disk Advisor" width="100%">

**Uninstaller** <img src="screenshots/uninstaller.png" alt="Uninstaller" width="100%">

**History** và **Audit log** <img src="screenshots/history.png" alt="History" width="100%"> <img src="screenshots/audit-log.png" alt="Audit log" width="100%">

**System Booster** <img src="screenshots/booster.png" alt="System Booster" width="100%">

<img src="https://user-images.githubusercontent.com/73097560/115834477-dbab4500-a447-11eb-908a-139a6edaec5c.gif" width="100%">

## Tính năng

### Dashboard

* CPU, RAM, nhiệt độ (khi có cảm biến), bộ nhớ commit (Windows) hoặc swap (Linux), lưu lượng mạng, biểu đồ lịch sử CPU/RAM và thời gian chạy; làm mới sau vài giây.

* Danh sách tiến trình nặng nhất kèm nút Kill, dung lượng đã dùng/còn trống của từng ổ.

* **Tối ưu một chạm** — Windows: xóa cache DNS, xóa tệp tạm, thu gọn working set, TRIM SSD. Linux: giải phóng cache, chỉnh `vm.swappiness`, `fstrim`, dọn journal cũ.

* *Load index* là chỉ số ước tính từ CPU, RAM, ổ đĩa, nhiệt độ và swap. Đó không phải phần trăm CPU, không phải dữ liệu SMART và không chẩn đoán sức khỏe ổ đĩa.

### Clean

Các mục có thể tự tạo lại, được tích sẵn. *Dry-run* cho xem chính xác những gì sẽ bị xóa trước khi bấm *Clean now*.

| Hệ điều hành | Mục dọn | 
| ----- | ----- | 
| Windows | Windows Temp, cache trình duyệt Chromium và ứng dụng Electron (Chrome, Edge, Brave, Opera, Vivaldi, Cốc Cốc, VS Code, Discord, Slack…), cache Firefox, cache ảnh thu nhỏ, Windows Error Reports, cache DNS | 
| Linux | Cache trình quản lý gói (apt, pacman, dnf, zypper, xbps, apk, rpm-ostree), journal và log hệ thống cũ, báo cáo crash, cache trình duyệt và Electron, ảnh thu nhỏ, cache pip, tệp tạm | 

Cache trình duyệt được bỏ qua kèm ghi chú nếu trình duyệt đang chạy.

### Deep Clean

Những mục có thể quan trọng. **Không có mục nào được chọn sẵn**, "select all" bỏ qua các dòng rủi ro cao, và mỗi lần xóa đều hỏi xác nhận (mặc định: Cancel). Deep Clean không bao giờ chạy nền.

* Windows: Recycle Bin, Prefetch, cache Windows Update, Delivery Optimization, cache font, cache shader GPU, dọn WinSxS, Event Logs, crash dump, cache lập trình (npm, yarn, pnpm, pip, NuGet, Gradle, Maven, Cargo, Go, JetBrains…).

* Linux: gói mồ côi/không còn dùng (apt, pacman, dnf, xbps), Nix garbage collection, cache lập trình, các thư mục `~/.cache` khác, Thùng rác, và — nếu đã cài — Docker/Podman, runtime Flatpak không dùng, bản cũ của Snap.

### Disk Advisor

Chỉ báo cáo — không có nút xóa. Gom nhóm những nơi chiếm nhiều dung lượng nhất: tệp hệ thống Windows (`Windows.old`, `pagefile.sys`, `hiberfil.sys`, cache Installer), Downloads, tệp lớn, máy ảo và ổ WSL, thư viện game, thư mục `node_modules` / `target` / virtualenv cũ, container, `/opt`, các gói nặng nhất. Có thể mở dòng trong trình quản lý tệp và sao chép báo cáo.

### Uninstaller

* Windows: chương trình đã cài đọc từ Registry, bổ sung thông tin từ `winget`.

* Linux: pacman, apt, dnf, zypper, xbps và Flatpak; các gói lõi của hệ thống được bảo vệ.

* Chọn nhiều ứng dụng, có log tiến trình trực tiếp. Trên Windows danh sách không bị lọc, nên hãy kiểm tra kỹ (driver, runtime) trước khi gỡ.

### History và Audit log

*History* ghi lại dung lượng ổ trước/sau mỗi phiên và dung lượng đã giải phóng. *Audit log* ghi lại những gì đã bị xóa (đường dẫn, loại, size). Cả hai là tệp cục bộ; tệp đã xóa không được giữ để khôi phục.

### System Booster

Áp dụng tinh chỉnh khi bạn yêu cầu và **lưu trạng thái gốc trước**. Trạng thái được khôi phục khi bạn tắt Boost hoặc đóng ứng dụng, và được phục hồi ở lần mở kế tiếp nếu ứng dụng bị tắt đột ngột.

* Windows: yêu cầu độ phân giải timer 1 ms, tắt GameDVR, thiết lập fullscreen DirectX/DWM, ưu tiên cho game được phát hiện, giảm ưu tiên tiến trình nền (EcoQoS trên Windows 11), dọn cache GPU của trình duyệt.

* Linux: CPU governor / power profile, tinh chỉnh bộ nhớ, ưu tiên tiến trình, tùy chọn Hyprland khi đang chạy Hyprland.

* Bộ dò game chỉ nâng ưu tiên khi game đang chạy. Log ghi rõ khi một lợi ích chưa được đo.

### Khay hệ thống và Auto-clean

Auto-clean **tắt theo mặc định**. Khi bật, chỉ chạy các mục `AUTO` được đánh dấu cho phép chạy định kỳ, chỉ khi máy rảnh, tối đa 6 giờ một lần, và chỉ khi ứng dụng đang mở hoặc nằm ở khay. Không bao giờ đụng tới Recycle Bin hoặc Thùng rác. Nếu Auto-clean tắt, đóng cửa sổ là thoát ứng dụng.

### Cập nhật và quyền riêng tư

Ứng dụng kiểm tra GitHub Releases để biết bản mới và không cài gì nếu bạn chưa bấm. Bản tải về được xác minh bằng chữ ký Ed25519 tích hợp trong ứng dụng. Không có telemetry hay analytics; kiểm tra cập nhật là kết nối mạng duy nhất.

## Cách việc dọn dẹp được giữ có kiểm soát

| Tầng | Trang | Hành vi | 
| ----- | ----- | ----- | 
| `AUTO` | Clean | Cache có thể tạo lại. Tích sẵn. Là tầng duy nhất bộ lập lịch được phép chạy. | 
| `REVIEW` | Deep Clean | Mỗi mục phải được chọn rõ ràng. | 
| `ADVISOR` | Disk Advisor | Chỉ báo cáo. | 

Một lần dọn được **lập kế hoạch, xem trước, rồi mới thực thi**. Ngay trước khi xóa từng mục, engine kiểm tra lại và bỏ qua nếu mục đó đã thay đổi từ lúc quét, đang được dùng, hoặc ứng dụng sở hữu nó đã chạy lại. Symlink và junction không được đi theo, điểm mount không bị vượt qua. **Xóa là vĩnh viễn** — không có gì được chuyển vào Recycle Bin.

## Hỗ trợ nền tảng

| Môi trường | Trạng thái | 
| ----- | ----- | 
| Windows 10 (build 19044), Python 3.12 | Đã chạy và sử dụng trên máy thật: tất cả các trang, đối chiếu số liệu với bộ đếm Windows, nhóm test riêng của Windows đạt. | 
| Windows 11 | Có mã xử lý (ví dụ EcoQoS); chưa kiểm chứng trên phần cứng. | 
| Linux nền apt (họ Ubuntu / Debian) | Test tự động đạt ở chế độ headless trên Ubuntu với Python 3.12 (628 đạt, 17 bỏ qua). | 
| Các bản phân phối Linux khác | Có nhận diện trình quản lý gói pacman, dnf, zypper, xbps, apk, rpm-ostree và Nix; chưa test riêng từng bản. | 

### Ghi nhận công cụ đo nhiệt độ (Windows CPU Temperature)

Windows không cung cấp API chuẩn ở tầng người dùng để đọc trực tiếp thanh ghi nhiệt độ của CPU. Để hiển thị thông số **CPU Temperature** chính xác trên bảng điều khiển, CyberClean tích hợp và ghi nhận các dự án mã nguồn mở sau:

* [**LibreHardwareMonitor**](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) *(MPL-2.0)*: thư viện được CyberClean sử dụng để truy cập cảm biến phần cứng và đọc nhiệt độ thực tế của CPU/GPU trên Windows (`vendor/lhm/LibreHardwareMonitorLib.dll`).

* [**PawnIO**](https://github.com/namazso/PawnIO) của tác giả [**namazso**](https://github.com/namazso) ([pawnio.eu](https://pawnio.eu/)): công cụ và kernel driver có chữ ký số được CyberClean sử dụng làm driver truy cập phần cứng cấp thấp (MSR/SMU) cho LibreHardwareMonitor, giúp hỗ trợ chức năng đo nhiệt độ CPU (**CPU Temperature**) an toàn trên Windows 10/11 mà không dùng các driver cũ dễ bị chặn bởi Windows Defender/HVCI.

* Khi máy chưa cài driver PawnIO hoặc phần cứng không hỗ trợ cảm biến, thẻ nhiệt độ hiển thị `N/A`; bạn có thể nhấp trực tiếp vào thẻ **Temperature** ngay trong ứng dụng (hoặc chọn trong lúc cài đặt CyberClean) để xác thực mã băm SHA-256 và cài đặt PawnIO chính thức.

## Cài đặt

**Yêu cầu:** Python 3.10+ (PyQt6, psutil, cryptography, send2trash; `tomli` trên Python 3.10; `pythonnet` trên Windows).

### Chạy từ mã nguồn (Windows và Linux)

```
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
<summary><b>Hướng dẫn chi tiết từ A–Z cho máy mới hoàn toàn (chưa cài Git / Python)</b></summary>

#### 1. Chuẩn bị môi trường trên máy mới

* **Trên Windows 10 / 11:**

  1. Mở **PowerShell** và cài đặt Git cùng Python 3.12 qua `winget` (hoặc tải trực tiếp từ [python.org](https://www.python.org/downloads/) và [git-scm.com](https://git-scm.com/download/win) — nhớ tích chọn **"Add Python to PATH"** khi cài):

     ```
     winget install -e --id Git.Git
     winget install -e --id Python.Python.3.12
     
     ```

  2. Đóng và mở lại cửa sổ PowerShell (ưu tiên chọn **Run as Administrator** để đọc cảm biến nhiệt độ CPU và dọn các mục hệ thống).

  3. Nếu PowerShell báo lỗi chặn chạy script khi kích hoạt `.venv`, chạy lệnh sau cho phiên hiện tại:

     ```
     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
     
     ```

* **Trên Linux:**

  ```
  # Ubuntu / Debian / Linux Mint / Pop!_OS
  sudo apt update && sudo apt install -y git python3 python3-venv python3-pip libegl1 libxcb-cursor0
  
  # Arch Linux / Manjaro / EndeavourOS / CachyOS
  sudo pacman -S --needed git python python-pip
  
  # Fedora
  sudo dnf install -y git python3 python3-pip
  
  # openSUSE
  sudo zypper install -y git python3 python3-pip
  
  ```

#### 2. Tải mã nguồn, cài đặt thư viện và khởi chạy

```
# 1. Tải mã nguồn dự án về máy
git clone https://github.com/vuphitung/CyberClean.git
cd CyberClean

# 2. Tạo môi trường ảo cô lập (.venv)
python -m venv .venv          # Trên một số bản Linux dùng: python3 -m venv .venv

# 3. Kích hoạt môi trường ảo
source .venv/bin/activate     # Trên Linux
.venv\Scripts\Activate.ps1    # Trên Windows PowerShell (hoặc .venv\Scripts\activate.bat trên CMD)

# 4. Nâng cấp pip và cài đặt đầy đủ thư viện phụ thuộc
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 5. Chạy ứng dụng
python -X utf8 main.py

```

> **Mẹo cho Windows:** Nếu bạn muốn hiển thị nhiệt độ CPU khi chạy trực tiếp từ mã nguồn mà máy chưa có driver cảm biến, chỉ cần bấm vào thẻ **TEMPERATURE** trên giao diện Dashboard để ứng dụng tự tải, kiểm tra SHA-256 và cài đặt [PawnIO](https://pawnio.eu/).

</details>

### Trình cài đặt Linux (từ bản phát hành đã công bố)

```
curl -sSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash

```

Xác minh chữ ký bản phát hành, cài vào `/opt/CyberClean`, đăng ký lệnh `cyberclean` và mục desktop, đồng thời thiết lập một helper đặc quyền có phạm vi giới hạn. Gỡ cài đặt bằng `sudo cyberclean --uninstall`.

### Gói Windows

Tự build theo phần bên dưới. Gói đã build sẵn được đính kèm trên [GitHub Releases](https://github.com/vuphitung/CyberClean/releases) khi có bản phát hành.

## Build

```
python -m pip install pyinstaller
python build.py --linux      # tar.gz cho Linux
python build.py --windows    # thư mục onedir cho Windows trong dist/CyberClean
python build.py --inno       # onedir Windows + script Inno Setup (biên dịch bằng Inno Setup)

```

<details>
<summary><b>Hướng dẫn đóng gói (Build) chi tiết cho Windows (.exe / Setup.exe) và Linux (.tar.gz / AppImage / .deb)</b></summary>

#### 1. Kiểm tra phụ thuộc trước khi đóng gói

Đảm bảo bạn đang đứng trong môi trường ảo `.venv` đã cài đủ `requirements.txt` và `pyinstaller`:

```
python -m pip install -r requirements.txt pyinstaller
python build.py --check

```

#### 2. Đóng gói trên Windows (`.exe` và bộ cài `Setup.exe`)

1. Chạy lệnh tạo bản build `onedir` và sinh kịch bản Inno Setup:

   ```
   python build.py --inno
   
   ```

   * Kịch bản `build.py` sẽ tự động kiểm tra mã băm SHA-256 của toàn bộ DLL trong `vendor/lhm`, tải hoặc xác thực `PawnIO_setup.exe` chính thức, đóng gói `dist\CyberClean\CyberClean.exe` (tích hợp sẵn manifest quyền Admin `--uac-admin`), và xuất tệp cấu hình `CyberClean.iss`.

2. Tạo bộ cài đặt `.exe` hoàn chỉnh bằng [Inno Setup 6](https://jrsoftware.org/isinfo.php):

   * **Cách 1 (Giao diện):** Mở tệp `CyberClean.iss` bằng **Inno Setup Compiler** và nhấn **Compile (`F9`)**.

   * **Cách 2 (Dòng lệnh):**

     ```
     & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" CyberClean.iss
     
     ```

   * File bộ cài hoàn chỉnh sẽ nằm tại `dist\CyberClean_Setup_v3.1.0.exe`.

#### 3. Đóng gói trên Linux (`.tar.gz`, `AppImage`, `.deb`)

```
# Đóng gói bản tar.gz tiêu chuẩn (dùng cho install.sh / GitHub Releases)
python build.py --linux

# Đóng gói bản AppImage chạy độc lập
python build.py --appimage

# Đóng gói gói .deb (trên Debian / Ubuntu / Linux Mint)
python build.py --deb

```

Tất cả các tệp kết quả sau khi build đều được xuất vào thư mục `dist/`.

</details>

## Phát triển

```
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m pyflakes main.py ui_widgets.py ui_pages.py core utils

```

Trên Windows, bộ test đầy đủ hiện báo 49 lỗi xuất phát từ các fixture chỉ dành cho POSIX (symlink cần đặc quyền, Unix socket, mục chỉ có trên Linux); nhóm test riêng của Windows đạt. Chi tiết: [báo cáo Windows](https://www.google.com/search?q=docs/WINDOWS_NATIVE_REPORT_VI.md). Hãy dùng thư mục thử riêng khi thử chức năng xóa.

```
CyberClean/
├── main.py                 # điểm vào, cửa sổ chính và khay hệ thống
├── ui_widgets.py, ui_pages.py
├── core/                   # engine, cleaner, booster, advisor, uninstaller
├── utils/                  # số liệu hệ thống, bản dịch, cập nhật
├── rules/                  # luật dọn theo hệ điều hành (TOML)
├── packaging/              # helper đặc quyền cho Linux
├── vendor/lhm/             # thư viện cảm biến Windows
├── tests/                  # pytest
├── build.py, install.sh
└── assets/, screenshots/

```

## Giới hạn đã biết

* Việc thử tương tác trên máy Linux thật còn hạn chế; vui lòng báo lỗi riêng của từng bản phân phối.

* Windows 11, ARM64 và các tổ hợp DPI/driver khác chưa được kiểm chứng.

* Ứng dụng không đo (benchmark) hiệu quả của Booster.

* Ước tính dung lượng log và WinSxS có thể khác với dung lượng thực sự giải phóng (volume, quyền, snapshot).

## Đóng góp và báo lỗi

Mở issue kèm hệ điều hành và phiên bản, phiên bản CyberClean, các bước bạn đã làm và nội dung hiển thị trong ứng dụng.

## Giấy phép

GNU General Public License v3.0 — see [LICENSE](https://www.google.com/search?q=LICENSE).

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:c060f0,50:00c8e0,100:060911&height=100&section=footer" width="100%" alt="footer" />
