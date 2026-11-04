# CyberClean — bản sửa Windows có kiểm chứng theo nhóm

Ngày: 29/10/2026. Đây là bản phát triển đã có kiểm chứng bổ sung trên Windows thật,
**chưa phải bản Windows đã xác nhận ổn định toàn diện**.

Các lỗi mô tả trong yêu cầu là lỗi người dùng đã quan sát trên Windows thật.
Việc kiểm chứng trong lượt sửa này diễn ra trên Linux/Python 3.12/Qt offscreen và API giả;
không được thay thế cho kết quả trên Dell Latitude E7470/Windows 10/Python 3.12.10.

## Baseline và lịch sử

ZIP đầu vào giữ nguyên. Dấu mốc Git của ZIP:
`123cdacbb7d1d6ad77a93763082ef748f65878d3`.
ZIP không chứa cơ sở dữ liệu Git, nên tạo commit baseline cục bộ từ đúng source,
rồi nhánh `fix/windows-stability`. Không clone/khẳng định đã xác minh lịch sử Git upstream;
không push lên GitHub. Không chồng source từ ZIP cũ khác.

Mỗi nhóm có commit và patch riêng; xem `WINDOWS_CHANGELOG.md` và `patches/` trong bộ bàn giao.
Chỉ thay nhánh hành vi Windows trong code dùng chung. Không sửa `core/linux_cleaner.py`,
`rules/linux.toml`, helper Linux hay `install.sh`.

## Đã thay đổi và giới hạn

| Nhóm | Đã sửa trong source | Chưa thể khẳng định |
|---|---|---|
| Khởi động | Bỏ UAC khi import; log sớm, Python/thread traceback, native faulthandler, Qt, startup/tray/shutdown/exit reason; UAC lỗi không làm process cũ thoát | Nguyên nhân chính xác của lần tự tắt trên máy người dùng; crash native/CLR thực tế |
| CPU | Một owner Windows; cache không blocking; total/per-core cùng boundary; process luôn chia số logical CPUs; prime và PID/create_time | Khớp Task Manager trên máy thật; đây là thang CPU time, không cam kết khớp tuyệt đối cách Windows tính utility |
| RAM | Ghi rõ used/available/total/working set/commit; chênh lệch available có dấu là biến động toàn hệ thống | Không chứng minh Boost giải phóng một lượng RAM riêng; không có số đo trước/sau Windows trong lượt này |
| Mạng | Counters theo interface, monotonic, reset/reconnect/adapter mất, zero thật khác unavailable | ALL NICs gồm virtual adapters, có thể đếm lại traffic qua tunnel; chưa chọn riêng Wi-Fi, chưa có SSID/RSSI |
| Nhiệt độ | Một host lâu dài; helper EXE riêng chỉ đọc đã cài trong Program Files; IPC loopback xác thực; freshness; thẻ bấm xin quyền Windows | Luồng UAC từ cửa sổ app chưa hoàn tất; chưa so cùng sensor với HWiNFO |
| Dependency | LHM 0.9.6 net472 + PawnIO 2.2.0; PyInstaller GUI onedir 173.4 MB và helper đều đã build; helper đã cài, smoke-test | Chưa tạo installer Inno Setup và chưa chạy GUI EXE mới |
| UI | Dashboard reflow theo viewport, 1024/1366 offscreen, scale 100/125/150/200; reuse process cells; pause animation minimize; không hiện điểm khi thiếu dữ liệu | Các trang còn lại, font/DPI/màn hình thật; scale test là logical width, không phải mô phỏng chính xác mọi độ phân giải vật lý |
| Boost | Capture originals trước mutation; applied/verified/pending; đủ masks và memory priority; retry restore; PID reuse; sửa enum ProcessMemoryPriority; không tự tăng power plan; verify GUID restore; không hứa lợi ích FPS từ timer request | Callback game-found vẫn còn thao tác priority blocking trên GUI; race/lifetime của mọi worker và crash persistence cho mọi standalone action chưa hoàn tất |
| Dọn rác | Whole-operation volume delta có dấu, không cộng chồng theo mục; logical/planned/observed riêng; DNS là operation; browser name rõ; lý do skip | Coverage volume phát hiện ngoài kế hoạch, drive aliases/mount point; native locking/permission; chưa audit toàn bộ special cleaners |
| Test | Guard resource/geteuid khi collection; test Windows riêng; mock host không chạm backend thật; native smoke/hardware test có cờ rõ | Chưa chạy suite trên Windows; một số test Linux filesystem cần skip/điều chỉnh riêng khi thực thi native Windows |

**Chưa hoàn tất toàn bộ yêu cầu trong prompt:** cần Windows thật để chẩn đoán crash, integration,
hardware, benchmark, đóng gói; đồng thời callback Boost và toàn bộ worker lifecycle cần thêm nhóm sửa.
Không coi bản này đã giải quyết mọi lỗi.

## Test và số đo

- Baseline đầy đủ, môi trường Linux này: **477 passed, 17 failed, 4 skipped**.
- Lượt sau các nhóm 1–6: **505 passed, 17 failed, 4 skipped**. 17 tên test lỗi giống baseline.
- Kết quả cuối sau nhóm 7: **506 passed, 17 failed, 6 skipped**; xem `validation-final.log`.
- Windows tập trung mới: **38 passed**; gồm cảm biến, IPC, chỉ số tải, localization, 3D và dashboard offscreen.
- Helper EXE từ Program Files smoke trên Windows: IPC xác thực, LHM `READY`, CPU heartbeat và thoát bằng `STOP` thành công. Chạy thường báo `cpu_access_denied`, đúng với quyền Windows.
- GUI Windows EXE onedir vừa build thành công tại `dist/CyberClean`; chưa mở GUI EXE mới để kiểm tra tương tác.
- Cài helper: 92 file trong `C:\Program Files\CyberClean\sensor-host`; SHA-256 EXE đã xác minh sau chép. Luồng UAC qua supervisor chưa trả mẫu; phép đo 70°C ở trên là probe nâng quyền riêng đã chạy trước đó.
- Probe cảm biến chỉ đọc đã duyệt quyền quản trị: Intel Core i7-6600U, CPU Package **70°C**, Core Max **70°C**, Core Average **68.5°C**. Đây là số đo tức thời; chưa đối chiếu đồng thời với HWiNFO.
- Tích hợp UAC ngay từ app và toàn bộ GUI/installer: chưa xác nhận ở lượt này.
- Không xóa dữ liệu người dùng thật; cleanup test dùng cây dữ liệu giả.
- Không có số đo Windows trước/sau CPU/RAM/startup/UI lag/handles; **chưa đo được**.
  Không có kết luận CPU dưới 1%, giảm RAM hay hết lỗi nhiệt độ.
- Có script read-only `tools/windows_benchmark.py` đo app và descendants:
  CPU toàn máy, tổng working sets (có thể cộng trùng shared pages), threads, handles, processes.
  Script này không đo startup/UI lag và không thay priority/power/cleanup.

Các lỗi baseline chủ yếu ở kiểm tra POSIX socket/chown, Chromium lock và helper cancellation trong
môi trường này. Không quy toàn bộ lỗi đó cho Windows và không sửa logic Linux để làm test xanh.
So sánh tên test lỗi nằm ở `baseline-failures.txt` và `final-failures.txt`.

## Định nghĩa để kiểm tra số liệu

- CPU tiến trình: Δ(user+system process time) / Δmonotonic / logical CPUs × 100.
  4 luồng: 80% một-core-scale → 20% toàn máy; 120% → 30%. Mẫu đầu là chưa đo được.
- CPU tổng/per-core: delta các counters user/system/idle trên cùng boundary khoảng 1 s.
  Process inventory dùng khoảng 5 s; không so từng hàng với total như cùng một cửa sổ.
- RAM UI: `psutil.virtual_memory()`; available riêng used. MEM% tiến trình là working set / RAM vật lý.
  `swap_memory` trên Windows mô tả commit, không phải số byte pagefile nằm trên đĩa.
- Mạng: B/s = delta byte / delta monotonic cho từng interface đang kết nối.
  ALL NICs cộng interface (loại loopback); tooltip nêu từng interface/link Mb/s.
  Không gọi tổng đó là Wi-Fi. 0 B/s là phép đo idle hợp lệ.
- CPU nhiệt: Package ưu tiên, rồi Core Max, rồi maximum các core còn fresh.
  Identifier/label/kind/age/reason trong tooltip. GPU/ACPI không thay CPU.
- Chỉ số tải: vẫn giữ điểm % quen thuộc khi chỉ thiếu cảm biến nhiệt tùy chọn; tooltip ghi rõ đây là điểm ước tính, không phải CPU% hay độ khỏe phần cứng.
- 3D: hình cầu/glow và phần đọc số được cache; ring dùng hình học dựng sẵn; 30 FPS trên Windows, dừng khi widget bị ẩn/thu nhỏ.
- Dọn rác: planned ≠ logical removed ≠ observed volume free-space delta.
  Các hoạt động nền và filesystem allocation ảnh hưởng số cuối; delta nhỏ hoặc skip file đang dùng
  tự nó không chứng minh bug.

## Nguồn chính thức dùng trong sửa

- psutil API: https://psutil.readthedocs.io/stable/ và https://psutil.io/api/
- LHM release đã lấy: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/tag/v0.9.6
- DLL SHA-256 và URL archive: `vendor/lhm/manifest.json`. Giữ DLL gốc ở root để đối chiếu;
  host Windows dùng cặp DLL trong `vendor/lhm`, không dùng root DLL.
- LHM tích hợp trực tiếp làm backend cảm biến; Python chỉ điều phối host/IPC. README chính thức ghi rõ
  thư viện dùng để nhúng vào ứng dụng khác và một số cảm biến cần quyền quản trị.
  Probe thường trên Windows 10 nhận diện CPU và 7 cảm biến nhưng PawnIO trả lỗi quyền 5. Sau khi
  cài PawnIO 2.2.0, probe chỉ đọc đã duyệt quyền quản trị nhận số thật: CPU Package/Core Max 70°C,
  Core Average 68.5°C trên Intel Core i7-6600U. Helper đã được cài và smoke-test ở quyền thường;
  luồng elevated qua supervisor cần duyệt UAC thủ công để hoàn tất. Chỉ helper đọc cảm biến xin UAC;
  app dọn dẹp vẫn chạy quyền thường. Không thay nhiệt CPU bằng GPU hay số ước tính.
- Nguồn LHM chính thức: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor
- PawnIO là backend driver riêng của LHM: https://github.com/namazso/PawnIO
- Windows process information: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ne-processthreadsapi-process_information_class
- Timer scope: https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod

## PowerShell — chuẩn bị và chạy test

Giải nén source thành một thư mục riêng, giữ ZIP/source cũ. Thay đúng đường dẫn dưới đây.
Không chạy cleanup/Boost trên dữ liệu thật để kiểm chứng unit test.

```powershell
Set-Location -LiteralPath 'C:\Users\YOUR_NAME\Downloads\CyberClean-Windows-Review\CyberClean'
if (-not (Test-Path -LiteralPath '.\main.py')) { throw 'Sai thư mục: không có main.py' }
python --version
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
New-Item -ItemType Directory -Force -Path .\validation | Out-Null

# Dùng offscreen CHỈ khi chạy test.
$env:QT_QPA_PLATFORM = 'offscreen'
& .\.venv\Scripts\python.exe -m pytest -q .\tests\test_windows_startup.py .\tests\test_windows_telemetry.py .\tests\test_windows_temperature.py .\tests\test_windows_boost_state.py .\tests\test_windows_cleanup_measurement.py .\tests\test_windows_ui.py .\tests\test_windows_cleaner.py .\tests\test_windows_native.py *>&1 | Tee-Object -FilePath .\validation\windows-focused.log
$focusedExit = $LASTEXITCODE
"Windows focused exit code: $focusedExit" | Tee-Object -FilePath .\validation\windows-focused-exit.txt

& .\.venv\Scripts\python.exe -m pytest -q *>&1 | Tee-Object -FilePath .\validation\pytest-all.log
$pytestExit = $LASTEXITCODE
"All pytest exit code: $pytestExit" | Tee-Object -FilePath .\validation\pytest-all-exit.txt

# Chạy riêng khi chủ động muốn test cảm biến CPU thật; không mock.
# FAIL nếu không có mẫu CPU fresh; đọc reason/log thay vì tăng timeout để test xanh.
$env:CYBERCLEAN_REQUIRE_CPU_SENSOR = '1'
& .\.venv\Scripts\python.exe -m pytest -q .\tests\test_windows_native.py -k temperature -rA *>&1 | Tee-Object -FilePath .\validation\native-cpu-sensor.log
$sensorExit = $LASTEXITCODE
"Native CPU sensor exit code: $sensorExit"
Remove-Item Env:\CYBERCLEAN_REQUIRE_CPU_SENSOR -ErrorAction SilentlyContinue
```

## PowerShell — mở app và lấy log khi tự tắt

```powershell
# Bắt buộc bỏ offscreen trước khi mở cửa sổ thật.
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
Remove-Item Env:\QT_SCALE_FACTOR -ErrorAction SilentlyContinue

# Chạy thường: không cần activate venv và không tự UAC.
& .\.venv\Scripts\python.exe .\main.py
$appExit = $LASTEXITCODE
"App exit code: $appExit"

# Chạy chẩn đoán: giữ terminal mở đến khi app thoát.
$env:PYTHONFAULTHANDLER = '1'
& .\.venv\Scripts\python.exe -X faulthandler .\main.py *>&1 | Tee-Object -FilePath .\validation\app-console.log
$appExit = $LASTEXITCODE
"App exit code: $appExit" | Tee-Object -FilePath .\validation\app-exit.txt

# GUI và host có PID riêng, log riêng.
Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\CyberClean\logs" | Sort-Object LastWriteTime -Descending
Get-Content -Path "$env:LOCALAPPDATA\CyberClean\logs\runtime-*.log" -Tail 80
Get-Content -Path "$env:LOCALAPPDATA\CyberClean\logs\native-crash-*.log" -Tail 80
```

Nếu app tự đóng sau 2–3 giây, giữ `app-console.log`, `app-exit.txt`, tất cả `runtime-PID.log`
và `native-crash-PID.log` mới nhất. Có stage cuối/traceback thì mới kết luận nguồn lỗi.
Mã 0 với stage hide/tray khác crash; chỉ mã thoát không đủ kết luận.

## PowerShell — đo trước/sau trên Windows thật

Mở app baseline hoặc app mới rồi lấy đúng PID từ Task Manager, Details; dùng cửa sổ PowerShell thứ hai.
Chạy cùng thời lượng, nguồn điện, power plan, tải nền và kịch bản: idle dashboard, đổi tab,
refresh, minimize/restore. Giữ Balanced, không tắt DPTF/bảo vệ nhiệt.

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|CyberClean' } | Select-Object ProcessId,ParentProcessId,Name,CommandLine
$appPid = 12345 # thay đúng PID GUI; KHÔNG dùng $PID là PID PowerShell
& .\.venv\Scripts\python.exe .\tools\windows_benchmark.py --pid $appPid --seconds 60 --output .\validation\after-dashboard.json
# Đo baseline bằng cùng script, đúng PID baseline, cùng kịch bản:
# & .\.venv\Scripts\python.exe .\tools\windows_benchmark.py --pid $baselinePid --seconds 60 --output .\validation\before-dashboard.json
```

Mở Task Manager và theo dõi cùng khoảng đo; chấp nhận các cửa sổ cập nhật khác nhau.
Đối chiếu RAM đúng cột (working set/available/commit). Kiểm tra NIC cụ thể trong tooltip và
Task Manager Performance; B/s × 8 / 1,000,000 = Mb/s throughput, không phải link speed.
Nhiệt độ phải so **cùng sensor CPU Package/Core Max/Core, cùng cột Current** trong HWiNFO,
không so CPU Package với GPU/ACPI hay Maximum từ lúc mở máy. Nếu host không đọc được,
báo unavailable và gửi reason; không tự tải DLL lạ, reset WMI hoặc tắt bảo vệ nhiệt.

## PowerShell — kiểm tra bản đóng gói

Build ngay trên Windows bằng venv của dự án; chưa có EXE đã kiểm chứng trong gói này.
Không đổi ExecutionPolicy.

```powershell
& .\.venv\Scripts\python.exe -m pip install pyinstaller
& .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm .\CyberClean.spec *>&1 | Tee-Object -FilePath .\validation\build.log
$buildExit = $LASTEXITCODE
"Build exit code: $buildExit"

Get-ChildItem -LiteralPath .\dist\CyberClean -Recurse -Filter HidSharp.dll
Get-ChildItem -LiteralPath .\dist\CyberClean -Recurse -Filter LibreHardwareMonitorLib.dll
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$exe = (Resolve-Path -LiteralPath '.\dist\CyberClean\CyberClean.exe').Path
$proc = Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -PassThru
$proc.WaitForExit()
$proc.Refresh()
"Packaged exit code: $($proc.ExitCode)" | Tee-Object -FilePath .\validation\packaged-exit.txt
```

Trong bản source và EXE: mở, chờ số liệu, refresh nhiều lần, đổi tab, minimize/restore, đóng.
Nếu cửa sổ ẩn xuống tray, chọn **Quit** trong menu tray để thoát hoàn toàn.
Xác nhận PID GUI và host đều kết thúc. Đọc log trong cùng thư mục `%LOCALAPPDATA%\CyberClean\logs`.
Kiểm tra 1024×768, 1366×768 và scale Windows 100/125/150/200%; không suy ra kiểm tra offscreen
đã chứng minh mọi màn hình vật lý. Nếu build hoặc test fail, giữ nguyên log thay vì bỏ test hay
nâng timeout chỉ để xanh.
