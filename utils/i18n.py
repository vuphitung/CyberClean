"""
CyberClean v2.0 — Internationalization (i18n)
Supports: English · Tiếng Việt · 中文 · 日本語 · 한국어
          Français · Deutsch · Español · Português · Русский · العربية · Italiano
"""
import json, sys
from pathlib import Path

import os as _os, sys as _sys
if _sys.platform == 'win32':
    CONFIG_FILE = Path(_os.getenv('LOCALAPPDATA', str(Path.home()))) / 'CyberClean/config.json'
else:
    CONFIG_FILE = Path.home() / '.local/share/cyber-clean/config.json'

SUPPORTED_LANGS = {
    'en': 'English',
    'vi': 'Tiếng Việt',
}

TRANSLATIONS = {

# ════════════════════════════════════════════════════
# ENGLISH
# ════════════════════════════════════════════════════
'en': {
    # Nav
    'nav_dashboard':  'DASHBOARD',
    'nav_clean':      'CLEAN',
    'nav_scanner':    'SCANNER',
    'nav_uninstall':  'UNINSTALL',
    'nav_history':    'HISTORY',
    'nav_rollback':   'DELETION LOG',
    'nav_booster':    'SYS BOOSTER',
    # Dashboard
    'sys_overview':   'SYSTEM OVERVIEW',
    'btn_refresh':    'REFRESH',
    'lbl_health':     'HEALTH',
    'lbl_oneclick':   'ONE-CLICK OPTIMIZE',
    'btn_optimize':   'OPTIMIZE NOW',
    'lbl_top_proc':   'TOP PROCESSES',
    'lbl_disk':       'DISK USAGE',
    'lbl_drive':      'DRIVE',
    'col_drive':      'Drive',
    'sys_healthy':    'System healthy',
    'lbl_calculating':'Calculating...',
    'lbl_temperature':'TEMPERATURE',
    'lbl_swap':       'SWAP',
    'lbl_cpu_chart':  'CPU %',
    'lbl_ram_chart':  'RAM %',
    # Clean
    'clean_targets':  'CLEAN TARGETS',
    'clean_subtitle': 'Select targets · Dry-run to preview · Clean to execute',
    'btn_dryrun':     'DRY-RUN',
    'btn_clean_now':  'CLEAN NOW',
    'btn_all':        'ALL',
    'btn_none':       'NONE',
    'placeholder_clean': '  → Select targets and click DRY-RUN to preview...',
    # Scanner
    'scanner_title':  'SECURITY SCANNER',
    'scanner_readonly':'Read-only scan — nothing deleted automatically',
    'scanner_readonly_badge': '⬡  Read-only scan — nothing deleted automatically',
    'btn_run_scan':   'RUN DEEP SCAN',
    'btn_autofix':    'AUTO-FIX SELECTED',
    'btn_mark_safe':  'MARK AS SAFE',
    'lbl_scan_output':'SCAN OUTPUT',
    'lbl_findings':   'FINDINGS',
    'placeholder_scan':'  ◈  Click RUN DEEP SCAN to start...',
    'scan_tooltip':   'Run scan first, then select findings to fix',
    # Uninstall
    'uninstall_title':'APP UNINSTALLER',
    'btn_uninstall':  'UNINSTALL SELECTED',
    'placeholder_filter': 'Filter apps...',
    'uninstall_hint': 'Select one or more apps  →  Uninstall',
    # History / Rollback
    'history_title':  'HISTORY LOG',
    'rollback_title': 'DELETED ITEMS (AUDIT)',
    'rollback_hint':  'These entries are a record of what was removed — files are not kept for restore. Caches rebuild on their own. For packages, reinstall or use any command shown in the note column.',
    'rollback_open_folder': 'OPEN LOG FOLDER',
    'btn_clear':      'CLEAR',
    # Booster
    'booster_title':  'SYSTEM BOOSTER',
    'booster_sub':    'Free RAM · optimize CPU · clear disk cache · tune system',
    'booster_free_ram':   'FREE RAM',
    'booster_cpu':        'CPU PRIORITY MODE',
    'booster_disk':       'DISK CACHE CLEAR',
    'booster_mem_tune':   'MEMORY TUNE',
    'booster_kill_bloat': 'KILL BACKGROUND BLOAT',
    'btn_free_now':   'FREE NOW',
    'btn_clear_cache':'CLEAR CACHE',
    'btn_tune_now':   'TUNE NOW',
    'btn_kill_bloat': 'KILL BLOAT',
    'btn_game_mode':  'GAME MODE',
    'btn_eco_mode':   'ECO MODE',
    'btn_smart_boost': 'SMART BOOST',
    'smart_tooltip':    'Auto-detect PC tier — disable transparency on low-end, full Game + Eco Mode on all tiers',
    'ram_desc':       'Drop page cache, reclaim unused memory. Instant RAM boost without rebooting.',
    'cpu_desc':       'Freeze or throttle background bloat. Give foreground app 100% CPU resources.',
    'disk_desc':      'Clear GPU/shader cache, temp files. Frees VRAM, fixes video stutter & WebGL glitches.',
    'mem_tune_desc':  'Linux: set swappiness=10 + compact memory. Windows: flush standby list & optimize VM.',
    'kill_desc':      'Find and kill zombie, sleeping & high-memory idle processes safely.',
    'game_tooltip':   'Jail background apps to last CPU cores — no kill, no suspend, no deadlock',
    'eco_tooltip':    'Soft-throttle all background tasks to below-normal priority',
    # Common
    'btn_kill':       'KILL',
    'btn_activate':   'ACTIVATE',
    'btn_active_restore': 'ACTIVE — CLICK TO RESTORE',
    'lbl_output':     'OUTPUT',
    'lbl_language':   'Language',
    'kill_failed':    'Kill failed',
    'msg_restart':    'Please restart CyberClean to apply language changes.',
    'msg_restart_title': 'Restart Required',
    'confirm_clean':  'Confirm Clean',
    'confirm_autofix':'Auto-Fix',
    'confirm_uninstall': 'Uninstall',
    'setup_required': 'Setup Required',
    'badge_safe':     'SAFE',
    'badge_caution':  'CAUTION',
    'badge_danger':   'DANGER',
    'header_subtitle':'SMART DISK MANAGER',
    'header_cross':   'CROSS-PLATFORM',
    # Table columns
    'col_pid':        'PID',
    'col_name':       'NAME',
    'col_cpu':        'CPU %',
    'col_mem':        'MEM %',
    'col_mount':      'DRIVE',
    'col_used':       'USED',
    'col_free':       'FREE',
    'col_sev':        'SEV',
    'col_category':   'CATEGORY',
    'col_path':       'PATH',
    'col_detail':     'DETAIL',
    'col_version':    'VERSION',
    'col_size':       'SIZE',
    'col_source':     'SOURCE',
    'col_time':       'TIME',
    'col_disk_before':'DISK BEFORE',
    'col_disk_after': 'DISK AFTER',
    'col_freed':      'FREED',
    'col_type':       'TYPE',
    'col_path_note':  'PATH / NOTE',
    # Updater dialog
    'upd_badge':          '⬆ v{ver} UPDATE',
    'upd_title':          '⬆  VERSION {ver} AVAILABLE',
    'upd_installed':      'Installed: v{cur}   →   New: v{ver}',
    'upd_notes_label':    'RELEASE NOTES',
    'upd_no_notes':       '(No release notes for this version.)',
    'upd_btn_later':      'LATER',
    'upd_btn_update':     'UPDATE NOW',
    'upd_btn_cancel':     'CANCEL',
    'upd_btn_retry':      'RETRY',
    'upd_btn_close':      'CLOSE',
    'upd_btn_updating':   'UPDATING…',
    'upd_done':           '✓  Done — restarting…',
    'upd_err_small':      'Download too small — check release assets on GitHub.',
    'upd_err_network':    'Network error: {reason}',
    'upd_err_no_binary':  'Could not find CyberClean binary in archive.',
    'upd_err_install':    'Install failed (run install.sh once for helper+sudoers): {err}',
    'upd_err_no_opt':     'In-app update requires the standard install (/opt). Download the .tar.gz from GitHub instead.',
    'upd_err_cancelled':  'Update cancelled.',
    'upd_err_small_win':  'Installer too small — asset name may differ on GitHub.',
    'upd_err_unsupported':'Auto-update not supported on this OS.',
    'upd_preparing':      'Preparing download…',
    'upd_downloading':    'Downloading v{ver}… {done} KB / {total} KB',
    'upd_extracting':     'Extracting…',
    'upd_installing':     'Installing',
    'upd_installing_optimizing': 'Installing and optimizing... Will restart in 3 seconds!',
    'upd_restarting':     'Restarting',
    'upd_restart_countdown': 'Restarting in',
    'upd_final_message': 'Launching new version...',
    'upd_dl_installer':   'Downloading installer v{ver} {done} KB / {total} KB',
    'upd_launching':      'Launching installer',
    'upd_installer_run':  'Installer running  closing app',
    'tray_view_update':   '⬆  View update…',
    'tray_upd_msg':       'v{ver}: click the header badge or tray → View update…',
    # System tray / dialogs
    'close_btn_tray': 'HIDE TO TRAY',
    'close_btn_quit': 'QUIT',
    'confirm_close_title': 'Background Mode',
    'confirm_close_msg':   'Auto-clean (6h) is enabled.\n\n• YES: Hide to system tray and keep running\n• NO: Quit completely (stops background auto-clean)',
    'remember_close_choice': 'Remember my choice — skip this dialog next time',
    'tray_reset_close_pref': 'Reset close-window preference…',
    'close_pref_reset_title': 'Preference reset',
    'close_pref_reset_body': 'You will be asked again the next time you close the window.',
    'tray_running_bg': 'Running in background. Auto-clean every 6h.',
    'zombie_title':   'Background Process Detected',
    'zombie_msg':     'CyberClean is running in background but cannot be shown.\n\nForce kill the old process and reopen?',
    'zombie_err':     'Could not kill old process. Please restart your computer.',

    # ── Log output (runtime messages) ──────────────
    'log_mode_dryrun': 'DRY-RUN',
    'log_mode_clean': 'CLEAN',
    'log_freed': 'freed',
    'log_removed': 'removed',
    'log_items': 'items',
    'log_total_freed': 'TOTAL FREED',
    'log_total_estimated': 'TOTAL ESTIMATED',
    'log_scanning_net': 'Scanning active network processes...',
    'log_net_complete_ok': 'Network scan complete — no suspicious connections',
    'log_net_complete_warn': 'Network scan complete',
    'log_net_suspicious_count': 'suspicious connection(s) found',
    'log_net_skipped': 'Network scan skipped',
    'log_scan_all_done': 'All scan steps finished.',
    'log_scan_header': 'SECURITY SCAN  //  Smart Analysis v2.3',
    'log_scan_processes': 'Scanning running processes...',
    'log_scan_suid': 'Scanning SUID/SGID binaries...',
    'log_scan_writable': 'Scanning world-writable files in system dirs...',
    'log_scan_cron': 'Scanning cron jobs for backdoors...',
    'log_scan_tempfiles': 'Scanning suspicious files in temp/user dirs...',
    'log_scan_network': 'Scanning active network connections...',
    'log_scan_ldpreload': 'Checking LD_PRELOAD / dynamic linker hijacks...',
    'log_scan_ssh': 'Checking SSH authorized_keys...',
    'log_scan_hosts': 'Checking /etc/hosts for tampering...',
    'log_scan_autorun': 'Scanning Windows autorun entries...',
    'log_scan_ok_processes': 'No malicious processes detected',
    'log_scan_ok_suid': 'No unexpected SUID binaries',
    'log_scan_ok_writable': 'No world-writable system files',
    'log_scan_ok_cron': 'No cron backdoors found',
    'log_scan_ok_tempfiles': 'No suspicious files found in temp/user dirs',
    'log_scan_ok_network': 'No suspicious listening ports',
    'log_scan_ok_ldpreload': 'No LD_PRELOAD hijacks detected',
    'log_scan_ok_ssh': 'No authorized_keys file',
    'log_scan_ok_hosts': 'Hosts file looks clean',
    'log_scan_complete': 'SCAN COMPLETE',
    'log_scan_clean': 'System looks clean — no threats detected',
    'log_scan_total': 'Total findings',
    'log_scan_categories': 'Categories OK',
    'log_scan_duration': 'Scan duration',
    'log_detecting_tier': 'Detecting PC tier (RAM / CPU / GPU)...',
    'log_boost_on_high': 'Smart Boost ON  [HIGH-END — Gaming rig]',
    'log_boost_on_mid': 'Smart Boost ON  [MID — Solid machine]',
    'log_boost_on_low': 'Smart Boost ON  [LOW-END — Potato mode]',
    'log_boost_off': 'Smart Boost OFF — settings restored',
    'log_starting_game': 'Starting Game Mode...',
    'log_starting_eco': 'Starting Eco Mode...',
    'log_freeing_ram': 'Freeing RAM...',
    'log_freeing_ram_cache': 'Freeing RAM (cache-preserving)...',
    'log_game_on': '⚡ GAME MODE ON',
    'log_game_off': 'GAME MODE OFF — restored',
    'log_tuning_mem': 'Tuning memory settings...',
    'log_clearing_cache': 'Clearing disk & GPU cache...',
    'log_scan_bloat': 'Scanning for background bloat...',
    'log_psi_active': 'PSI monitor: active — auto kill-bloat on memory pressure',
    'log_mem_compacted': 'Memory compacted — fragmented pages defragged',
    'log_cache_preserved': 'Page cache preserved — browser/app data stays warm',
    'log_boost_all_done': 'Smart Boost ON [{tier}] — all layers applied',
    'log_no_game_running': 'No game running — browser/media apps will NOT be jailed',

    # ── New feature keys (v2.3.0) ─────────────────
    'lbl_before': 'BEFORE',
    'lbl_after': 'AFTER',
    'lbl_after_est': 'AFTER (EST)',
    'lbl_pct_used': 'used',
    'lbl_simulated': 'simulated',
    'btn_preview': 'PREVIEW FILES',
    'preview_title': 'Preview — Files to be Deleted',
    'preview_desc': 'Files that would be deleted (up to 200 per target):',
    'auto_clean_title': 'AUTO-CLEAN SCHEDULE',
    'auto_clean_desc': 'Auto-clean safe targets when system is idle.',
    'sched_off': 'Off',
    'sched_6h': 'Every 6 hours',
    'sched_12h': 'Every 12 hours',
    'sched_24h': 'Every 24 hours',
    'sched_idle': 'When idle only',
    'lbl_last_run': 'Last run',
    'lbl_never_run': 'Never run yet',
    'btn_run_now': 'RUN NOW',
    'lbl_disk_trend': 'DISK USAGE TREND (30 days)',
    'nav_startup': 'STARTUP',
    'startup_sub': 'Enable or disable programs that run at login',
    'startup_info': 'Changes take effect at next login. Only disable items you recognise.',
    'startup_items_count': 'items',
    'col_toggle': 'TOGGLE',
    'status_enabled': 'ENABLED',
    'status_disabled': 'DISABLED',
    'btn_enable': 'ENABLE',
    'btn_disable': 'DISABLE',
    'lbl_loading': 'Loading…',
    'btn_close': 'CLOSE',
    # Sidebar / status bar (previously hardcoded)
    'lbl_navigation':    'NAVIGATION',
    'lbl_active':        'ACTIVE',
    # Scanner
    'col_status':        'STATUS',
    'safe_btn_tooltip':  'Mark selected finding as trusted — scanner will ignore it next time',
    # Uninstaller
    'uninstall_found':   'Found {n} apps — select one or more, then click Uninstall',
    'lbl_installer_open':'Installer window opened — complete it, then click REFRESH',
    # Booster active label
    'lbl_smart_active':  'ACTIVE',
},

# ════════════════════════════════════════════════════
# TIẾNG VIỆT  — tự nhiên, có hồn, không máy móc
# ════════════════════════════════════════════════════
'vi': {
    # Nav — ngắn gọn, dễ nhận diện
    'nav_dashboard':  'TỔNG QUAN',
    'nav_clean':      'DỌN RÁC',
    'nav_scanner':    'QUÉT BẢO MẬT',
    'nav_uninstall':  'GỠ ỨNG DỤNG',
    'nav_history':    'LỊCH SỬ',
    'nav_rollback':   'NHẬT KÝ XÓA',
    'nav_booster':    'TĂNG TỐC',
    # Dashboard
    'sys_overview':   'TỔNG QUAN HỆ THỐNG',
    'btn_refresh':    'LÀM MỚI',
    'lbl_health':     'SỨC KHỎE',
    'lbl_oneclick':   'TỐI ƯU MỘT CHẠM',
    'btn_optimize':   'TỐI ƯU NGAY',
    'lbl_top_proc':   'TIẾN TRÌNH TOP',
    'lbl_disk':       'DUNG LƯỢNG Ổ ĐĨA',
    'lbl_drive':      'Ổ ĐĨA',
    'col_drive':      'Ổ đĩa',
    'sys_healthy':    'Hệ thống hoạt động tốt',
    'lbl_calculating':'Đang tính toán...',
    'lbl_temperature':'NHIỆT ĐỘ',
    'lbl_swap':       'SWAP',
    'lbl_cpu_chart':  'CPU %',
    'lbl_ram_chart':  'RAM %',
    # Clean
    'clean_targets':  'MỤC TIÊU DỌN DẸP',
    'clean_subtitle': 'Chọn mục tiêu · Xem trước · Dọn dẹp',
    'btn_dryrun':     'XEM TRƯỚC',
    'btn_clean_now':  'DỌN NGAY',
    'btn_all':        'CHỌN TẤT',
    'btn_none':       'BỎ CHỌN',
    'placeholder_clean': '  → Chọn mục tiêu rồi nhấn XEM TRƯỚC để kiểm tra trước khi xóa...',
    # Scanner
    'scanner_title':  'QUÉT BẢO MẬT',
    'scanner_readonly':'Chỉ đọc — không tự xóa bất kỳ thứ gì',
    'scanner_readonly_badge': '⬡  Chỉ đọc — không tự động xóa bất cứ thứ gì',
    'btn_run_scan':   'QUÉT SÂU',
    'btn_autofix':    'TỰ ĐỘNG SỬA',
    'btn_mark_safe':  'ĐÁNH DẤU AN TOÀN',
    'lbl_scan_output':'KẾT QUẢ QUÉT',
    'lbl_findings':   'PHÁT HIỆN',
    'placeholder_scan':'  ◈  Nhấn QUÉT SÂU để bắt đầu...',
    'scan_tooltip':   'Quét trước, chọn mục cần sửa, rồi nhấn tự động sửa',
    # Uninstall
    'uninstall_title':'GỠ ỨNG DỤNG',
    'btn_uninstall':  'GỠ ĐÃ CHỌN',
    'placeholder_filter': 'Tìm kiếm ứng dụng...',
    'uninstall_hint': 'Chọn một hoặc nhiều ứng dụng  →  Gỡ cài đặt',
    # History / Rollback
    'history_title':  'LỊCH SỬ DỌN DẸP',
    'rollback_title': 'FILE ĐÃ XÓA (NHẬT KÝ)',
    'rollback_hint':  'Đây chỉ là bản ghi những gì đã bị xóa — app không lưu file để khôi phục. Cache sẽ tự tạo lại. Gói phần mềm: cài lại hoặc dùng lệnh trong cột ghi chú (nếu có).',
    'rollback_open_folder': 'MỞ THƯ MỤC LOG',
    'btn_clear':      'XÓA',
    # Booster — sinh động, đúng cảm giác "tăng tốc"
    'booster_title':  'TĂNG TỐC HỆ THỐNG',
    'booster_sub':    'Giải phóng RAM · tối ưu CPU · xóa cache · tinh chỉnh hệ thống',
    'booster_free_ram':   'GIẢI PHÓNG RAM',
    'booster_cpu':        'ƯU TIÊN CPU',
    'booster_disk':       'XÓA CACHE Ổ ĐĨA',
    'booster_mem_tune':   'TINH CHỈNH BỘ NHỚ',
    'booster_kill_bloat': 'DIỆT TIẾN TRÌNH RÁC',
    'btn_free_now':   'GIẢI PHÓNG NGAY',
    'btn_clear_cache':'XÓA CACHE',
    'btn_tune_now':   'TINH CHỈNH',
    'btn_kill_bloat': 'DIỆT NGAY',
    'btn_game_mode':  'CHẾ ĐỘ GAME',
    'btn_eco_mode':   'CHẾ ĐỘ TIẾT KIỆM',
    'btn_smart_boost': 'TĂNG TỐC THÔNG MINH',
    'smart_tooltip':    'Tự nhận diện cấu hình máy — tối ưu phù hợp cho từng loại',
    'ram_desc':       'Xả page cache, thu hồi bộ nhớ chưa dùng. Tăng RAM ngay, không cần khởi động lại.',
    'cpu_desc':       'Nhốt app nền vào nhân CPU cuối, dành toàn bộ nhân chính cho game hoặc app đang chạy.',
    'disk_desc':      'Xóa GPU/shader cache và file tạm. Giải phóng VRAM, khắc phục giật lag & WebGL.',
    'mem_tune_desc':  'Linux: swappiness=10 + compact bộ nhớ. Windows: xả standby list & tối ưu VM.',
    'kill_desc':      'Tìm và diệt tiến trình zombie, ngủ đông, hoặc ngốn RAM vô tội vạ một cách an toàn.',
    'game_tooltip':   'Nhốt app nền vào CPU cuối — không kill, không treo, không deadlock',
    'eco_tooltip':    'Hạ nhẹ độ ưu tiên toàn bộ tiến trình nền, nhường tài nguyên cho app đang dùng',
    # Common
    'btn_kill':       'KẾT THÚC',
    'btn_activate':   'KÍCH HOẠT',
    'btn_active_restore': 'ĐANG BẬT — NHẤN ĐỂ TẮT',
    'lbl_output':     'KẾT QUẢ',
    'lbl_language':   'Ngôn ngữ',
    'kill_failed':    'Không thể kết thúc tiến trình',
    'msg_restart':    'Vui lòng khởi động lại CyberClean để áp dụng ngôn ngữ mới.',
    'msg_restart_title': 'Cần Khởi Động Lại',
    'confirm_clean':  'Xác nhận dọn dẹp',
    'confirm_autofix':'Tự động sửa',
    'confirm_uninstall': 'Gỡ cài đặt',
    'setup_required': 'Cần thiết lập',
    'badge_safe':     'AN TOÀN',
    'badge_caution':  'CẨN THẬN',
    'badge_danger':   'NGUY HIỂM',
    'header_subtitle':'QUẢN LÝ ĐĨA THÔNG MINH',
    'header_cross':   'ĐA NỀN TẢNG',
    # Table columns — ngắn gọn để không tràn
    'col_pid':        'PID',
    'col_name':       'TÊN',
    'col_cpu':        'CPU %',
    'col_mem':        'RAM %',
    'col_mount':      'Ổ đĩa',
    'col_used':       'Đã dùng',
    'col_free':       'Còn lại',
    'col_sev':        'Mức độ',
    'col_category':   'Loại',
    'col_path':       'Đường dẫn',
    'col_detail':     'Chi tiết',
    'col_version':    'Phiên bản',
    'col_size':       'Dung lượng',
    'col_source':     'Nguồn',
    'col_time':       'Thời gian',
    'col_disk_before':'Trước',
    'col_disk_after': 'Sau',
    'col_freed':      'Đã giải phóng',
    'col_type':       'Loại',
    'col_path_note':  'Đường dẫn / Ghi chú',
    # Updater dialog
    'upd_badge':          '⬆ v{ver} CẬP NHẬT',
    'upd_title':          '⬆  PHIÊN BẢN {ver} ĐÃ CÓ',
    'upd_installed':      'Đang dùng: v{cur}   →   Mới: v{ver}',
    'upd_notes_label':    'GHI CHÚ PHIÊN BẢN',
    'upd_no_notes':       '(Không có ghi chú cho phiên bản này.)',
    'upd_btn_later':      'ĐỂ SAU',
    'upd_btn_update':     'CẬP NHẬT NGAY',
    'upd_btn_cancel':     'HỦY',
    'upd_btn_retry':      'THỬ LẠI',
    'upd_btn_close':      'ĐÓNG',
    'upd_btn_updating':   'ĐANG CẬP NHẬT…',
    'upd_done':           '✓  Xong — đang khởi động lại…',
    'upd_err_small':      'File tải quá nhỏ — kiểm tra lại release trên GitHub.',
    'upd_err_network':    'Lỗi mạng: {reason}',
    'upd_err_no_binary':  'Không tìm thấy file CyberClean trong archive.',
    'upd_err_install':    'Cài đặt thất bại (chạy install.sh một lần để cấu hình helper): {err}',
    'upd_err_no_opt':     'Cập nhật trong app yêu cầu cài qua install.sh (/opt). Tải .tar.gz từ GitHub thủ công.',
    'upd_err_cancelled':  'Đã hủy cập nhật.',
    'upd_err_unsupported':'Cập nhật tự động chưa hỗ trợ trên hệ điều hành này.',
    'upd_preparing':      'Đang chuẩn bị tải…',
    'upd_downloading':    'Đang tải v{ver}… {done} KB / {total} KB',
    'upd_extracting':     'Đang giải nén…',
    'upd_installing':     'Đang cài đặt…',
    'upd_installing_optimizing': 'Đang cài đặt và tối ưu hóa... Sẽ khởi động lại trong 3 giây!',
    'upd_restarting':     'Đang khởi động lại…',
    'upd_restart_countdown': 'Khởi động lại trong',
    'upd_final_message': 'Đang khởi chạy phiên bản mới...',
    'upd_dl_installer':   'Đang tải installer v{ver} {done} KB / {total} KB',
    'upd_launching':      'Đang khởi chạy installer…',
    'upd_installer_run':  'Installer đang chạy — đóng ứng dụng…',
    'tray_view_update':   '⬆  Xem cập nhật…',
    'tray_upd_msg':       'v{ver}: nhấn badge trên header hoặc tray để cập nhật…',
    # Dialogs
    'close_btn_tray': 'ẨN XUỐNG KHAY',
    'close_btn_quit': 'THOÁT HẲN',
    'confirm_close_title': 'Chạy Ngầm',
    'confirm_close_msg':   'Tự động dọn rác (6h) đang bật.\n\n• ĐỒNG Ý: Ẩn xuống khay, chạy nền\n• KHÔNG: Thoát hẳn (tắt dọn tự động nền)',
    'remember_close_choice': 'Ghi nhớ lựa chọn — lần sau đóng cửa sổ không hỏi lại',
    'tray_reset_close_pref': 'Đặt lại cách đóng cửa sổ…',
    'close_pref_reset_title': 'Đã đặt lại',
    'close_pref_reset_body': 'Lần sau khi đóng cửa sổ, hộp thoại sẽ hỏi lại.',
    'tray_running_bg': 'Đang chạy nền. Tự động dọn mỗi 6 giờ.',
    'zombie_title':   'Phát Hiện Tiến Trình Cũ',
    'zombie_msg':     'CyberClean đang chạy ngầm và không thể hiển thị.\n\nBạn có muốn tắt ép tiến trình cũ và mở lại không?',
    'zombie_err':     'Không thể tắt tiến trình cũ. Vui lòng khởi động lại máy tính.',

    # ── Log output (runtime messages) ──────────────
    'log_mode_dryrun': 'THỬ NGHIỆM',
    'log_mode_clean': 'DỌN RÁC',
    'log_freed': 'đã giải phóng',
    'log_removed': 'đã xóa',
    'log_items': 'mục',
    'log_total_freed': 'TỔNG DỌN ĐƯỢC',
    'log_total_estimated': 'TỔNG ƯỚC TÍNH',
    'log_scanning_net': 'Đang quét tiến trình mạng...',
    'log_net_complete_ok': 'Đã quét xong mạng — không có kết nối đáng ngờ',
    'log_net_complete_warn': 'Đã quét xong mạng',
    'log_net_suspicious_count': 'kết nối đáng ngờ được phát hiện',
    'log_net_skipped': 'Đã bỏ qua quét mạng',
    'log_scan_all_done': 'Đã hoàn tất toàn bộ các bước quét.',
    'log_scan_header': 'QUÉT BẢO MẬT  //  Phân tích thông minh v2.3',
    'log_scan_processes': 'Đang quét tiến trình đang chạy...',
    'log_scan_suid': 'Đang quét file SUID/SGID...',
    'log_scan_writable': 'Đang quét file ghi-được-bởi-mọi-người...',
    'log_scan_cron': 'Đang quét cron job tìm backdoor...',
    'log_scan_tempfiles': 'Đang quét file nghi ngờ trong thư mục tạm...',
    'log_scan_network': 'Đang quét kết nối mạng đang hoạt động...',
    'log_scan_ldpreload': 'Kiểm tra LD_PRELOAD / chiếm quyền linker...',
    'log_scan_ssh': 'Kiểm tra SSH authorized_keys...',
    'log_scan_hosts': 'Kiểm tra /etc/hosts bị chỉnh sửa...',
    'log_scan_autorun': 'Đang quét autorun Windows...',
    'log_scan_ok_processes': 'Không phát hiện tiến trình độc hại',
    'log_scan_ok_suid': 'Không có file SUID bất thường',
    'log_scan_ok_writable': 'Không có file hệ thống có thể ghi tự do',
    'log_scan_ok_cron': 'Không phát hiện backdoor trong cron',
    'log_scan_ok_tempfiles': 'Không có file đáng ngờ trong thư mục tạm',
    'log_scan_ok_network': 'Không có cổng lắng nghe đáng ngờ',
    'log_scan_ok_ldpreload': 'Không phát hiện chiếm quyền LD_PRELOAD',
    'log_scan_ok_ssh': 'Không có file authorized_keys',
    'log_scan_ok_hosts': 'File hosts trông sạch',
    'log_scan_complete': 'QUÉT HOÀN TẤT',
    'log_scan_clean': 'Hệ thống trông sạch — không phát hiện mối đe dọa',
    'log_scan_total': 'Tổng phát hiện',
    'log_scan_categories': 'Danh mục an toàn',
    'log_scan_duration': 'Thời gian quét',
    'log_detecting_tier': 'Đang xác định cấu hình máy (RAM / CPU / GPU)...',
    'log_boost_on_high': 'Smart Boost BẬT  [CAO CẤP — Máy chơi game]',
    'log_boost_on_mid': 'Smart Boost BẬT  [TRUNG BÌNH — Máy ổn định]',
    'log_boost_on_low': 'Smart Boost BẬT  [THẤP CẤP — Chế độ khoai tây]',
    'log_boost_off': 'Smart Boost TẮT — đã khôi phục cài đặt',
    'log_starting_game': 'Đang bật Chế độ Game...',
    'log_starting_eco': 'Đang bật Chế độ Tiết kiệm...',
    'log_freeing_ram': 'Đang giải phóng RAM...',
    'log_freeing_ram_cache': 'Đang giải phóng RAM (giữ cache)...',
    'log_game_on': '⚡ CHẾ ĐỘ GAME BẬT',
    'log_game_off': 'CHẾ ĐỘ GAME TẮT — đã khôi phục',
    'log_tuning_mem': 'Đang điều chỉnh bộ nhớ...',
    'log_clearing_cache': 'Đang xóa cache ổ đĩa & GPU...',
    'log_scan_bloat': 'Đang quét phần mềm nền...',
    'log_psi_active': 'Giám sát PSI: đang hoạt động — tự tắt app nền khi áp lực RAM',
    'log_mem_compacted': 'Bộ nhớ đã được gom — chống phân mảnh xong',
    'log_cache_preserved': 'Giữ nguyên page cache — dữ liệu trình duyệt không bị xóa',
    'log_boost_all_done': 'Smart Boost BẬT [{tier}] — đã áp dụng tất cả lớp',
    'log_no_game_running': 'Không có game đang chạy — trình duyệt/media sẽ KHÔNG bị cách ly',


    # ── New feature keys (v2.3.0) ─────────────────
    'lbl_before': 'TRƯỚC',
    'lbl_after': 'SAU',
    'lbl_after_est': 'SAU (ƯỚC)',
    'lbl_pct_used': 'đã dùng',
    'lbl_simulated': 'mô phỏng',
    'btn_preview': 'XEM TRƯỚC',
    'preview_title': 'Xem trước — Các file sẽ bị xóa',
    'preview_desc': 'Các file sẽ bị xóa (tối đa 200 file mỗi mục tiêu):',
    'auto_clean_title': 'LỊCH DỌN TỰ ĐỘNG',
    'auto_clean_desc': 'Tự động dọn các mục an toàn khi máy rảnh.',
    'sched_off': 'Tắt',
    'sched_6h': 'Mỗi 6 tiếng',
    'sched_12h': 'Mỗi 12 tiếng',
    'sched_24h': 'Mỗi 24 tiếng',
    'sched_idle': 'Khi máy rảnh',
    'lbl_last_run': 'Lần cuối',
    'lbl_never_run': 'Chưa chạy lần nào',
    'btn_run_now': 'CHẠY NGAY',
    'lbl_disk_trend': 'XU HƯỚNG Ổ ĐĨA (30 ngày)',
    'nav_startup': 'KHỞI ĐỘNG',
    'startup_sub': 'Bật hoặc tắt chương trình chạy khi đăng nhập',
    'startup_info': 'Thay đổi có hiệu lực lần đăng nhập tiếp theo. Chỉ tắt những mục bạn biết.',
    'startup_items_count': 'mục',
    'col_toggle': 'BẬT/TẮT',
    'status_enabled': 'BẬT',
    'status_disabled': 'TẮT',
    'btn_enable': 'BẬT',
    'btn_disable': 'TẮT',
    'lbl_loading': 'Đang tải…',
    'btn_close': 'ĐÓNG',
    'upd_err_small_win': 'File tải về quá nhỏ — kiểm tra kết nối internet',
    # Sidebar / thanh trạng thái (trước đây hardcode tiếng Anh)
    'lbl_navigation':    'ĐIỀU HƯỚNG',
    'lbl_active':        'ĐANG CHẠY',
    # Scanner
    'col_status':        'TRẠNG THÁI',
    'safe_btn_tooltip':  'Đánh dấu mục được chọn là an toàn — lần quét sau sẽ bỏ qua',
    # Gỡ ứng dụng
    'uninstall_found':   'Tìm thấy {n} ứng dụng — chọn một hoặc nhiều, rồi nhấn Gỡ cài đặt',
    'lbl_installer_open':'Cửa sổ gỡ đã mở — hoàn tất thao tác rồi nhấn LÀM MỚI',
    # Booster
    'lbl_smart_active':  'ĐANG BẬT',},


}  # end TRANSLATIONS


class Translator:
    def __init__(self):
        self.lang = 'en'
        self._load_config()

    def _load_config(self):
        try:
            if CONFIG_FILE.exists():
                conf = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
                lang = conf.get('lang', 'en')
                if lang in TRANSLATIONS:
                    self.lang = lang
        except:
            pass

    def set_lang(self, lang_code: str):
        if lang_code not in TRANSLATIONS:
            return
        self.lang = lang_code
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if CONFIG_FILE.exists():
                existing = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            existing['lang'] = lang_code
            CONFIG_FILE.write_text(json.dumps(existing), encoding='utf-8')
        except:
            pass

    def get(self, key: str, default: str = '') -> str:
        return TRANSLATIONS.get(self.lang, {}).get(key) or \
               TRANSLATIONS['en'].get(key) or \
               default or key


# Global singleton
T = Translator()

def _t(key: str, default: str = '', **kwargs) -> str:
    """Translate a key. Falls back to English, then to default, then to key itself.
    If kwargs are given, they are applied with str.format (e.g. placeholders like {ver})."""
    text = T.get(key, default)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text


# ═══════════════════════════════════════════════════════════════════════
# LOG LINE TRANSLATOR
# Pattern-match các chuỗi hardcode trong CleanWorker / scanner / booster
# rồi trả về bản dịch theo ngôn ngữ hiện tại.
# ═══════════════════════════════════════════════════════════════════════
import re as _re

# Map: (regex pattern, i18n_key, optional format_fn(match) -> dict)
# format_fn nhận re.Match, trả về dict kwargs cho str.format()
_LOG_PATTERNS: list = []

def _p(pattern: str, key: str, fmt=None):
    _LOG_PATTERNS.append((_re.compile(pattern, _re.IGNORECASE), key, fmt))

# ── CleanWorker ──────────────────────────────────────────────────────────
_p(r'^DRY-RUN$',       'log_mode_dryrun')
_p(r'^CLEAN$',         'log_mode_clean')
_p(r'(\d[\d.,]* \w+)\s+freed$',  'log_freed',
   lambda m: {'size': m.group(1)})
_p(r'(\d+)\s+removed$','log_removed',
   lambda m: {'n': m.group(1)})
_p(r'(\d+)\s+items$',  'log_items',
   lambda m: {'n': m.group(1)})
_p(r'^TOTAL FREED:\s*(.+)$',      'log_total_freed',
   lambda m: {'size': m.group(1)})
_p(r'^TOTAL ESTIMATED:\s*(.+)$',  'log_total_estimated',
   lambda m: {'size': m.group(1)})
_p(r'Scanning active network processes', 'log_scanning_net')

# ── Scanner ──────────────────────────────────────────────────────────────
_p(r'SECURITY SCAN.*Smart Analysis',  'log_scan_header')
_p(r'Scanning running processes',      'log_scan_processes')
_p(r'Scanning SUID/SGID',             'log_scan_suid')
_p(r'Scanning world-writable',        'log_scan_writable')
_p(r'Scanning cron jobs',             'log_scan_cron')
_p(r'Scanning suspicious files.*temp','log_scan_tempfiles')
_p(r'Scanning active network conn',   'log_scan_network')
_p(r'Checking LD_PRELOAD',            'log_scan_ldpreload')
_p(r'Checking SSH authorized',        'log_scan_ssh')
_p(r'Checking /etc/hosts',            'log_scan_hosts')
_p(r'Scanning Windows autorun',       'log_scan_autorun')
_p(r'No malicious processes detected \((\d+) processes scanned, (\d+) trusted\)',
   'log_scan_ok_processes',
   lambda m: {'scanned': m.group(1), 'trusted': m.group(2)})
_p(r'No malicious processes detected','log_scan_ok_processes')
_p(r'No unexpected SUID',             'log_scan_ok_suid')
_p(r'No world-writable system files', 'log_scan_ok_writable')
_p(r'No cron backdoors found',        'log_scan_ok_cron')
_p(r'No suspicious files found',      'log_scan_ok_tempfiles')
_p(r'No suspicious listening ports',  'log_scan_ok_network')
_p(r'No suspicious ports detected',   'log_scan_ok_network')
_p(r'No LD_PRELOAD hijacks',          'log_scan_ok_ldpreload')
_p(r'No authorized_keys file',        'log_scan_ok_ssh')
_p(r'Hosts file looks clean',         'log_scan_ok_hosts')
_p(r'^SCAN COMPLETE$',                'log_scan_complete')
_p(r'System looks clean.*no threats', 'log_scan_clean')
_p(r'^Total findings\s*:',            'log_scan_total')
_p(r'^Categories OK\s*:',             'log_scan_categories')
_p(r'^Scan duration\s*:',             'log_scan_duration')

# ── Booster ──────────────────────────────────────────────────────────────
_p(r'Detecting PC tier',              'log_detecting_tier')
_p(r'Smart Boost ON.*HIGH',           'log_boost_on_high')
_p(r'Smart Boost ON.*MID',            'log_boost_on_mid')
_p(r'Smart Boost ON.*[Ll][Oo][Ww]',  'log_boost_on_low')
_p(r'Smart Boost OFF',                'log_boost_off')
_p(r'Starting Game Mode',             'log_starting_game')
_p(r'Starting Eco Mode',              'log_starting_eco')
_p(r'Freeing RAM \(cache-preserving\)','log_freeing_ram_cache')
_p(r'Freeing RAM',                    'log_freeing_ram')
_p(r'GAME MODE ON',                   'log_game_on')
_p(r'GAME MODE OFF',                  'log_game_off')
_p(r'Tuning memory settings',         'log_tuning_mem')
_p(r'Clearing disk.*GPU cache',       'log_clearing_cache')
_p(r'Scanning for background bloat',  'log_scan_bloat')
_p(r'PSI monitor.*active',            'log_psi_active')
_p(r'Memory compacted.*defragg',      'log_mem_compacted')
_p(r'Memory compacted',               'log_mem_compacted')
_p(r'Page cache preserved',           'log_cache_preserved')
_p(r'Smart Boost ON \[(\w+)\].*all layers', 'log_boost_all_done',
   lambda m: {'tier': m.group(1)})
_p(r'No game running',                'log_no_game_running')


def translate_log_line(msg: str) -> str:
    """
    Nhận một chuỗi log hardcode tiếng Anh, trả về bản dịch theo T.lang.
    Nếu không match pattern nào → giữ nguyên (technical strings như path/số).

    Cách dùng trong ui_widgets.py:
        from utils.i18n import translate_log_line
        def _wrap_log(emit_fn):
            return lambda m, l='text': emit_fn(translate_log_line(m), l)
    """
    stripped = msg.strip().lstrip('✓✗⚠⛔⬡◆▸ ~+i.!⚡⏸▶⟳ℹ•→')
    stripped = stripped.strip()

    for pattern, key, fmt_fn in _LOG_PATTERNS:
        # Try match on full msg or stripped
        m = pattern.search(msg) or pattern.search(stripped)
        if m:
            base = T.get(key, '')
            if not base:
                return msg  # key not translated yet → original
            if fmt_fn:
                try:
                    kwargs = fmt_fn(m)
                    # Build translated with placeholders
                    # e.g. "freed" key doesn't have {size}, but total_freed does
                    try:
                        translated = base.format(**kwargs)
                    except (KeyError, IndexError):
                        translated = base
                except Exception:
                    translated = base
            else:
                translated = base
            # Preserve leading prefix symbols from original
            prefix_match = _re.match(r'^([\s✓✗⚠⛔◆▸~+i.⚡⏸▶⟳ℹ•→⬡]+)', msg)
            prefix = prefix_match.group(1) if prefix_match else ''
            # Preserve trailing info (e.g. counts, paths)
            # For lines that end with extra data not in the pattern
            suffix = ''
            if key in ('log_scan_duration',):
                # Keep the number after the colon
                num_m = _re.search(r':\s*(\d+.*?)$', msg)
                if num_m:
                    suffix = ': ' + num_m.group(1)
            elif key in ('log_scan_total', 'log_scan_categories'):
                num_m = _re.search(r':\s*(\d+)', msg)
                if num_m:
                    suffix = ' : ' + num_m.group(1)
            elif key in ('log_freed',):
                # "  ✓  273.9 MB freed" → "  ✓  273.9 MB đã giải phóng"
                size_m = _re.search(r'([\d.,]+\s+\w+)\s+freed', msg)
                if size_m:
                    return prefix.rstrip() + '  ' + size_m.group(1) + ' ' + T.get('log_freed', 'freed')
            elif key in ('log_removed',):
                n_m = _re.search(r'(\d+)\s+removed', msg)
                if n_m:
                    return prefix.rstrip() + '  ' + n_m.group(1) + ' ' + T.get('log_removed', 'removed')
            elif key in ('log_items',):
                n_m = _re.search(r'(\d+)\s+items', msg)
                if n_m:
                    return prefix.rstrip() + '  ' + n_m.group(1) + ' ' + T.get('log_items', 'items')
            elif key in ('log_total_freed','log_total_estimated'):
                size_m = _re.search(r':\s*([\d.,]+\s+\w+)', msg)
                if size_m:
                    return '  ' + translated + ': ' + size_m.group(1)
            elif key in ('log_scan_ok_processes',):
                # "No malicious processes detected (201 scanned, 91 trusted)"
                detail = _re.search(r'\((\d+) processes scanned, (\d+) trusted\)', msg)
                if detail:
                    suffix = f' ({detail.group(1)} / {detail.group(2)})'

            # Một số key đã có icon/prefix trong translation (game_on/off)
            # → không nhân đôi prefix gốc
            _no_prefix_keys = {'log_game_on','log_game_off','log_boost_on_high',
                                'log_boost_on_mid','log_boost_on_low','log_boost_off',
                                'log_boost_all_done','log_scan_complete','log_scan_header',
                                'log_mode_dryrun','log_mode_clean'}
            if key in _no_prefix_keys:
                return translated + suffix
            return prefix + translated + suffix

    return msg  # unchanged


