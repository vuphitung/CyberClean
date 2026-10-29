# CyberClean

**Tiện ích desktop viết bằng Python/PyQt6 để xem số liệu máy, rà soát dữ liệu có thể dọn và chạy một số thao tác bảo trì trên Windows/Linux.**

[English](README.md) · Tiếng Việt

> **Trạng thái:** source đang được kiểm chứng. Windows đã được chạy trực tiếp trên một máy Windows 10; bản source sau các thay đổi Windows **chưa được chạy lại trên Linux**. Bộ test toàn dự án chưa xanh. Chưa coi đây là bản phát hành đã xác nhận ổn định trên mọi máy.

## CyberClean làm gì

- **Bảng điều khiển:** CPU, RAM, bộ nhớ commit, lưu lượng mạng, dung lượng từng ổ/volume và tiến trình. Chỉ số *tải/health* là ước tính từ dữ liệu hệ thống; không phải phần trăm tải CPU, không phải SMART và không chẩn đoán sức khỏe ổ đĩa.
- **Dọn rác:** các mục được chia thành `AUTO` (cache có thể tạo lại), `REVIEW` (phải chọn/xác nhận từng nội dung) và `ADVISOR` (chỉ báo cáo). Engine lập kế hoạch, cho xem trước rồi kiểm tra lại điều kiện trước khi xóa. Xóa cache là xóa thật; không có bảo đảm khôi phục.
- **Tư vấn ổ đĩa:** tìm nhóm thư mục/file chiếm chỗ để báo cáo; không xóa dữ liệu.
- **Booster:** cung cấp các thao tác Windows/Linux như trim working set, quản lý một số ưu tiên tiến trình và chế độ game. Kết quả phụ thuộc máy, quyền và workload; ứng dụng chưa chứng minh tăng FPS hay tốc độ tổng thể.
- **Gỡ ứng dụng, lịch sử và khay hệ thống:** đọc danh sách ứng dụng từ Windows Registry hoặc package manager Linux; lưu lịch sử cục bộ. Lịch dọn chỉ chạy khi app còn mở/đang ở khay, không phải Windows service.
- **Cập nhật:** updater kiểm tra GitHub Releases. Không có analytics/telemetry; việc kiểm tra phiên bản vẫn tạo kết nối mạng tới GitHub.

## Công nghệ

- Python 3.10+ và PyQt6 cho giao diện, QThread cho công việc nền.
- `psutil` và API hệ điều hành để lấy số liệu. Trên Windows có gọi Win32 qua `ctypes` (CPU time, RAM, commit, dung lượng volume, tiến trình); trên Linux dùng các API/tiện ích của distro.
- Luật dọn theo TOML trong `rules/`; phần lớn mục dọn dùng chung engine trong `core/`, còn thao tác riêng theo OS nằm trong cleaner tương ứng.
- Đọc nhiệt độ CPU trên Windows là đường dẫn tùy chọn qua LibreHardwareMonitor .NET (`LibreHardwareMonitorLib.dll`), `pythonnet` và backend PawnIO trong helper đọc cảm biến. Cảm biến phụ thuộc BIOS/firmware và quyền driver. **Trên máy Windows dùng để rà soát, app vẫn hiển thị `N/A`; helper tích hợp chưa trả được mẫu end-to-end.** Chạy `main.py` từ source cũng không có helper đã cài để xin quyền phần cứng. Vì vậy không coi tính năng nhiệt độ là đã hoạt động trên mọi máy.

## Tương thích và bằng chứng hiện có

| Môi trường | Đã kiểm tra | Chưa nên suy ra |
|---|---|---|
| Windows 10 build 19044, Python 3.12.10, Intel i7-6600U | GUI source và bản onedir mở được; CPU/RAM/commit/ổ C,D đối chiếu với API Windows trong các lượt lấy mẫu; đã duyệt 8 trang, refresh, minimize/restore | Mọi phiên bản Windows, driver, DPI, ARM64; cảm biến CPU trong app; hiệu quả tăng FPS |
| Linux | Có mã cho nhiều package manager/distro; bộ test cũ từng chạy trên Linux | Bản source sau các thay đổi Windows chưa được tải xuống chạy lại trên Linux; cần làm trước khi phát hành |

Một lượt đo GUI 90 giây trên máy Windows đó ghi CPU CyberClean + helper trung bình **3,09% toàn máy** (2,73% khi dashboard để yên sau giây 45), working set cộng các tiến trình cao nhất **197,48 MiB**, event-loop p95 **25 ms**. Đây là một mẫu trên một máy, không phải cam kết mức dùng tài nguyên hay benchmark so sánh.

Lượt test Windows được ghi trong [báo cáo native](docs/WINDOWS_NATIVE_REPORT_VI.md): nhóm Windows **113 đạt, 1 bỏ qua, 0 lỗi**; toàn bộ suite trên lượt đó **373 đạt, 49 lỗi, 180 bỏ qua**. 49 lỗi được phân loại là giả định fixture/quyền POSIX/Linux; điều đó **không biến toàn suite thành xanh**. Các con số này là của lượt ghi trong báo cáo, không phải kết quả chạy lại sau mọi chỉnh sửa gần đây.

## Chạy từ mã nguồn

Từ Linux hoặc Windows PowerShell:

```bash
git clone https://github.com/vuphitung/CyberClean.git
cd CyberClean
python -m venv .venv
```

Kích hoạt môi trường ảo:

```bash
# Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Cài gói và mở giao diện:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -X utf8 main.py
```

Python 3.10 dùng `tomli` theo điều kiện trong requirements; Windows cài thêm `pythonnet` theo marker của pip. Không cần chạy toàn bộ app bằng quyền Administrator/root để xem dashboard. Một số thao tác bảo trì sẽ yêu cầu quyền riêng hoặc bị từ chối nếu thiếu quyền.

### Chạy kiểm tra khi phát triển

`requirements-dev.txt` cài thêm pytest và pyflakes:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m pyflakes main.py ui_widgets.py ui_pages.py core utils
```

Trên Windows có thể chạy riêng các bài kiểm tra cảm biến/native quan trọng:

```powershell
python -m pytest -q tests/test_windows_native.py tests/test_windows_temperature.py tests/test_windows_sensor_access.py tests/test_engine_windows_native.py
```

Để kiểm tra thủ công: mở app từ source, so sánh CPU/RAM/dung lượng với Windows Task Manager hoặc công cụ hệ thống, refresh vài lần, rồi xem trước kế hoạch dọn. Dùng thư mục thử nghiệm riêng nếu cần kiểm tra xóa; đừng bấm thực thi trên dữ liệu cá nhân để “test cho nhanh”. Phép đo hệ thống có thể lệch nhẹ do thời điểm lấy mẫu và workload nền.

**Riêng Linux trước khi phát hành:** clone đúng branch source, cài `requirements-dev.txt`, chạy toàn suite, mở app trực tiếp và kiểm tra preview/dry-run trên distro mục tiêu. Chỉ sau đó mới build artifact; kết quả test trên Windows không thay thế được bước này.

## Build

PyInstaller cần cài riêng:

```bash
python -m pip install pyinstaller

# Linux: gói tar.gz
python build.py --linux

# Windows: thư mục onedir trong dist\CyberClean
python build.py --windows

# Windows: build onedir và tạo script Inno Setup; mở script trong Inno Setup Compiler để compile installer
python build.py --inno
```

`--windows` tạo thư mục ứng dụng, không phải một file EXE độc lập. `--inno` tạo thêm script cài đặt; cần Inno Setup Compiler để xuất installer. Đừng đẩy binary/installer lên release trước khi test trên Linux và kiểm tra lại số phiên bản/chữ ký.

## Cây source

```text
CyberClean/                  # gốc repo bình thường: main.py nằm ngay đây
├── main.py                  # khởi động, điều phối giao diện
├── ui_widgets.py, ui_pages.py
├── core/                    # cleaner, engine, booster, advisor
├── utils/                   # telemetry, bản dịch, updater, Windows helpers
├── rules/                   # luật dọn TOML theo hệ điều hành
├── tests/                   # pytest
├── packaging/               # helper Linux có phạm vi quyền giới hạn
├── vendor/lhm/              # thư viện cảm biến Windows và manifest hash
├── build.py                 # đóng gói PyInstaller
└── install.sh               # cài Linux
```

Nếu bro đang xem gói bàn giao `CyberClean-Windows-Review/`, thư mục ngoài là vỏ review chứa Git bundle, patch, checksum và báo cáo; `CyberClean/` bên trong mới là source. Vỏ review không thuộc cấu trúc repo phát hành. Khi clone repo GitHub bình thường, các file như `main.py` nằm trực tiếp ở gốc checkout.

## Giới hạn và an toàn

- AUTO xóa cache vĩnh viễn; REVIEW có thể chứa dữ liệu người dùng, cần đọc từng mục trước khi xác nhận.
- Ước tính log/WinSxS và số byte thu hồi có thể khác theo volume, quyền, snapshot hoặc mount point.
- Booster thay đổi trạng thái hệ thống; dùng đúng chức năng và kiểm tra quyền. Không có cam kết làm máy nhanh hơn.
- Nhiệt độ CPU trên Windows hiện chưa xác nhận end-to-end trong app ở máy kiểm tra; `N/A` là trạng thái trung thực khi không có mẫu.
- Xem thêm [báo cáo Windows và các giới hạn còn lại](docs/WINDOWS_NATIVE_REPORT_VI.md).

## Giấy phép

MIT — xem [LICENSE](LICENSE).
