# Kiểm tra CyberClean trực tiếp trên Windows — 28–29/10/2026

Đã chạy bản nguồn trên chính máy hiện tại, đọc bộ đếm Windows, thử toàn bộ 8 trang,
refresh, thu nhỏ/khôi phục và thoát. Đã sửa lỗi ngay trong thư mục `CyberClean/`.
Báo cáo `WINDOWS_REPORT_VI.md` cũ là lịch sử kiểm tra trên Linux; số liệu bên dưới
là đợt kiểm tra Windows mới. Không áp dụng lại patch cũ lên bản nguồn hiện tại.

## Máy và phạm vi kiểm tra

- Windows 10 build 19044, Python 3.12.10 64 bit, psutil 7.2.2.
- Intel Core i7-6600U, 2 nhân / 4 luồng; RAM vật lý 8.476.532.736 byte (~7,89 GiB).
- Chạy dưới quyền người dùng thường. Không bật Boost thật, không gỡ phần mềm,
  không thay power plan/registry/dịch vụ thật và không dọn dữ liệu người dùng.
- Kiểm tra xóa file dùng thư mục tạm trên NTFS và API giả khi cần quyền hệ thống.
- Kiểm tra GUI dùng cấu hình riêng; số liệu CPU/RAM/đĩa/mạng và host cảm biến vẫn đọc thật.
  Chỉ tắt truy vấn bản cập nhật lúc chạy phép đo để giữ kịch bản lặp lại được.

## Đối chiếu số liệu với Windows

Chi tiết: `../../validation/native-metrics-2026-10-28.json`.

| Chỉ số | Kết quả đối chiếu |
|---|---|
| CPU toàn máy | 4 cửa sổ lấy mẫu khớp `GetSystemTimes`, chênh 0 điểm phần trăm trong đợt đo |
| RAM tổng | Khớp `GlobalMemoryStatusEx`; RAM available giữa hai lần đọc liên tiếp lệch tối đa ~1,54 MiB do tải nền |
| Commit | Đọc riêng `GetPerformanceInfo`; giới hạn khớp, used giữa các lần đọc lệch tối đa ~2,21 MiB |
| Ổ C và D | Total/free khớp `GetDiskFreeSpaceExW` trong cùng lượt đối chiếu |
| Mạng | Kiểm tra delta byte/thời gian, reset/reconnect và adapter; chưa kiểm chứng lưu lượng bằng thiết bị độc lập |
| Nhiệt độ CPU | Máy hiện không trả cảm biến CPU qua LHM. Hiển thị N/A/unavailable; chưa thể xác nhận giá trị °C |

RAM/Commit/free space thay đổi theo hoạt động máy, nên xem timestamp và file JSON;
không lấy một con số tĩnh làm giá trị đúng cho mọi thời điểm. CPU time cũng không
cam kết bằng tuyệt đối chỉ số CPU utility của Task Manager ở cửa sổ cập nhật khác.

## Lỗi đã sửa

1. **Quét/xóa file Windows:** `DirEntry.stat()` trên Windows trả inode/dev/link-count
   bằng 0, gây báo vượt mount giả, bỏ sót thư mục con và sai số hardlink. Dùng lstat
   thật, kiểm tra lại kích thước/thời gian trước xóa và thử bằng cây NTFS thật.
2. **Báo dung lượng dọn rác:** không còn lấy ước lượng làm số đã dọn khi thiếu quyền
   hoặc thao tác thất bại. Không đổi tên font cache rồi tính như đã giải phóng; không
   xóa mọi file `.old` trong System32. Recycle Bin đọc kích thước native. Kết quả đo
   một phần volume được ghi là chưa đủ dữ liệu.
3. **Dịch vụ khi dọn cache:** chờ xác nhận trạng thái; chỉ khôi phục dịch vụ vốn đang
   chạy. Review từ chối lựa chọn không có trong bản xem trước/hết hạn.
4. **Số liệu Dashboard:** Commit tách khỏi pagefile, không còn phụ thuộc cách psutil
   diễn giải swap. Dữ liệu hết hạn chuyển unavailable; không giấu các tác vụ Python khác.
5. **Boost:** sửa quyền và kích thước handle WinAPI; lấy mẫu CPU đủ thời gian trước
   khi coi ứng dụng idle; bảo vệ tiến trình foreground. Rollback xác minh PID/name/
   create-time, giữ trạng thái khi khôi phục chưa xong, không báo thành công giả.
6. **Đóng app:** đợi worker hoàn tất, nhận trạng thái gốc rồi mới phục hồi; chặn
   callback muộn tạo scan/monitor mới. Không hủy QThread đang chạy.
7. **Tối ưu tải:** thay truy vấn từng tiến trình bằng một snapshot Windows có kiểm
   tra giới hạn buffer và fallback rõ lỗi. Bỏ hỏi status không được hiển thị.
   Inventory từ ~2–4 giây còn ~23–38 ms ở phép đo riêng. Không có sensor thì dò
   lại tối đa mỗi 10 giây, heartbeat không làm mới nhiệt độ cũ. Giảm hoạt ảnh lúc
   idle kể cả khi con trỏ đứng yên, tránh dựng lại bảng ổ đĩa/áp lại stylesheet khi dữ liệu
   không đổi, bỏ bóng mờ tốn CPU trên Windows. Dashboard cập nhật mỗi 4 giây như tài
   liệu công bố; sampler vẫn chạy mỗi giây và Refresh vẫn cập nhật ngay.
8. **Auto-clean/one-click:** ngưỡng mạng Windows dùng KB/giây đúng thời gian lấy mẫu;
   lệnh TRIM không nuốt lỗi; thao tác đã hủy không tiếp tục mở tác vụ kế tiếp.
9. **Disk Advisor:** không bỏ sót thư mục con do định danh ổ đĩa NTFS bằng 0;
   tổng dung lượng/biểu đồ không cộng lặp thư mục cha và file con, kể cả khác hoa/thường.
   Từng dòng giữ kích thước thật. Quét hết hạn ở tác vụ con cũng được đánh dấu chưa đầy đủ.

## Đo ứng dụng và kết quả test

Kết quả cuối ghi trong các file `validation/windows-runtime-external-final.json`,
`validation/windows-release-final.log` / `.xml` ở thư mục gốc.
Lượt cuối chạy GUI 90 giây, với tiến trình quan sát riêng. CPU của bộ quan sát được
loại khỏi CPU CyberClean và báo riêng. Không gọi bộ đếm số luồng tốn CPU trong GUI.
CPU là tỷ lệ trên toàn máy, cộng cả host cảm biến; working set cộng các tiến trình
có thể đếm trùng trang bộ nhớ chia sẻ. Bộ quan sát và tải nền vẫn có thể cạnh tranh
tài nguyên, nên đây không phải benchmark phòng thí nghiệm.

**Đính chính phép đo cũ:** các file `windows-runtime-check*.json`,
`windows-runtime-final.json`, `windows-runtime-result.json` trước đó chạy bộ quan sát
ngay trong GUI. Truy vấn số luồng của psutil quét bảng tiến trình, làm tăng CPU và độ
trễ được đo. Những file này được giữ làm lịch sử và đã gắn cờ không hợp lệ để suy ra
CPU riêng của app. Không dùng các số 7–15% từ chúng để kết luận hiệu năng CyberClean
hoặc tỷ lệ cải thiện trước/sau. Chỉ lượt đo bên ngoài mới dùng cho kết luận cuối.

Lượt GUI cuối (90 giây, 29/10):

| Phép đo | Kết quả |
|---|---:|
| CPU app và host, trung bình toàn lượt | 3,09% toàn máy |
| CPU khi Dashboard để yên, sau giây 45 | 2,73% toàn máy |
| CPU bộ quan sát, không tính vào app | 0,15% toàn máy |
| Working set cộng các tiến trình, cao nhất | 197,48 MiB |
| Working set mẫu cuối | 125,34 MiB |
| Độ trễ event loop p95 / lớn nhất | 25 / 119 ms |
| Từ bắt đầu nhập mã đến mẫu CPU hợp lệ đầu tiên | 9,41 giây |
| Đóng app | 0,63 giây; worker dừng, không còn tiến trình con |

Đã mở đủ 8 trang và refresh, thu nhỏ/khôi phục. Snapshot cuối không có lỗi bộ đếm.
Nhiệt độ vẫn unavailable. Khởi động và tải CPU còn có thể cải thiện; chưa có phép đo
baseline bên ngoài tương đương để khẳng định giảm bao nhiêu phần trăm.

Kiểm tra NTFS thật còn xác nhận file bị khóa bởi `CreateFileW` không bị xóa và không
báo đã thu hồi byte; đóng handle thì dùng lại plan thành công. Lỗi/xuất hiện thay đổi
giữa quá trình xóa vẫn giữ đúng phần đã xóa và bảo toàn dữ liệu còn lại.

Lượt kiểm thử tổng cuối: **373 đạt, 49 lỗi, 180 bỏ qua**. Trong đó, nhóm Windows
(`test_windows*.py` và `test_engine_windows_native.py`) có **113 đạt, 1 bỏ qua, 0 lỗi**;
nhóm này gồm cả API giả và kiểm tra NTFS/GUI native, không phải 113 thao tác hệ thống thật.
Bài bỏ qua trong nhóm Windows là cảm biến CPU cần bật kiểm chứng riêng.

49 lỗi còn lại đều đã có trong lượt trước; không xuất hiện tên lỗi mới. Chúng thuộc
fixture Linux/POSIX, quyền tạo symlink hoặc giả định về nhánh bảo vệ file giữa hai
nền tảng. Đã kiểm tra riêng bằng khóa file, lỗi xóa một phần và sửa file trên NTFS.
Xem `validation/windows-failure-classification.md`, `windows-release-failure-classification.json`
và `windows-validation-summary.json`. Cả 49 lỗi cuối đã có phân loại, không còn lỗi chưa rà.
Bộ kiểm thử toàn dự án vẫn chưa xanh; không được quảng bá kết quả thành bản phát hành
đã xác nhận ổn định hoàn toàn.

## Giới hạn còn lại

- Một lượt chạy ngắn không chứng minh ổn định nhiều giờ/ngày, mọi máy Windows,
  mọi DPI hoặc mọi driver. Nhiệt độ thật trên máy này vẫn chưa xác minh được.
- Chưa chạy game/FPS hoặc khẳng định Boost giúp tăng hiệu năng. Ép working set giảm
  không đồng nghĩa ứng dụng dùng ít bộ nhớ hơn hoặc hoạt động nhanh hơn.
- Một số test cũ giả định POSIX/Linux (shell helper, UID, Unix socket, đường dẫn,
  quyền tạo symlink). Phân biệt lỗi test này với nhóm native Windows trong log cuối;
  không xem bộ test toàn dự án là đã xanh nếu vẫn có lỗi.
- Chưa có installer/EXE phát hành mới đã được kiểm chứng; kết quả áp dụng cho source.
- Công cụ Computer Use trả `FrameArrived timed out` / `window capture timed out` khi
  chụp cửa sổ. Ảnh đính kèm được xuất bằng Qt từ phiên GUI thật; chưa thay thế việc
  kiểm tra độc lập màn hình, mọi font và DPI vật lý.
- Ước lượng Event Logs/WinSxS có thể cao hơn phần thu hồi thực tế; volume gắn qua
  thư mục chưa được bộ đo phân giải riêng theo mount point.
- Journal khôi phục Boost chưa ghi bền trước từng thay đổi hệ thống. Mất điện/kill
  cứng giữa thao tác chưa có bảo đảm phục hồi đầy đủ. Xóa file Windows vẫn kiểm tra
  đường dẫn, chưa bảo đảm nguyên tử chống mọi race bằng handle.

## Chạy và tái kiểm tra

Mở `Run-CyberClean.cmd` ở thư mục gốc để dùng source đã sửa với Python đang cài.
Hoặc vào `CyberClean/` và chạy `python -X utf8 main.py`.

Các công cụ chỉ đọc, chạy từ `CyberClean/`:

```powershell
python tools/windows_metrics_check.py --help
python tools/windows_runtime_check.py --seconds 90 --output ../validation/recheck.json
python tools/windows_telemetry_profile.py --help
```

Log phiên chẩn đoán ở `validation/*-profile/local/CyberClean/logs/`.
Phiên dùng bình thường ghi log ở `%LOCALAPPDATA%/CyberClean/logs/`.
Các thư mục fixture lớn do kiểm thử tạo đã được dọn; log, XML, số đo JSON và ảnh vẫn giữ lại.

Nguồn chính thức: [Python DirEntry.stat trên Windows](https://docs.python.org/3.12/library/os.html#os.DirEntry.stat),
[GetPerformanceInfo](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getperformanceinfo),
[NtQuerySystemInformation](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntquerysysteminformation).
