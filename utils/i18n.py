"""
CyberClean v2.0 — Internationalization (i18n)
Supports: English · Tiếng Việt

Add a new language: add its code to SUPPORTED_LANGS below, then add a
matching dict of the same keys under TRANSLATIONS. Keep en/vi as the
reference — every key in one must exist in all others (nothing enforces
this at runtime, so a missing key silently falls back to the English string
via _t()'s default argument rather than raising).
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
    'nav_uninstall':  'UNINSTALL',
    'nav_history':    'HISTORY',
    'nav_rollback':   'AUDIT LOG',
    'nav_booster':    'SYS BOOSTER',
    # Dashboard
    'sys_overview':   'SYSTEM OVERVIEW',
    'btn_refresh':    'REFRESH',
    'lbl_health':     'LOAD INDEX',
    'lbl_oneclick':   'ONE-CLICK OPTIMIZE',
    'btn_optimize':   'OPTIMIZE NOW',
    'lbl_top_proc':   'TOP PROCESSES',
    'lbl_disk':       'DISK USAGE',
    'lbl_drive':      'DRIVE',
    'col_drive':      'Drive',
    'sys_healthy':    'Normal load',
    'health_disk': 'Disk',
    'health_temperature': 'temperature',
    'health_none': 'none',
    'health_waiting': 'Waiting for system readings',
    'health_partial': 'Estimate · missing {metrics}',
    'health_score_explanation': 'Estimated score: higher means more headroom. This is not CPU usage or hardware health. Missing readings: {metrics}.',
    'health_tooltip': 'Heuristic load index estimated from CPU, RAM, disk usage, temperature, and swap (not hardware SMART health).',
    'lbl_calculating':'Calculating...',
    'lbl_temperature':'TEMPERATURE',
    'temp_source_cpu': 'CPU sensor',
    'temp_reading_ok': 'Source: {source}; latest sample {age:.1f}s ago.',
    'temp_reading_ok_no_age': 'Source: {source}.',
    'temp_pawnio_missing': 'LHM detected the CPU, but PawnIO is not installed. Windows needs administrator approval to install this sensor driver.',
    'temp_access_denied': 'Windows denied access to the CPU sensor. This sensor needs administrator-level hardware access.',
    'temp_driver_blocked': 'Windows blocked the hardware sensor driver. No temperature is shown; keep Windows security protections enabled.',
    'temp_driver_unavailable': 'The hardware sensor driver is unavailable. No temperature could be read.',
    'temp_hardware_missing': 'LibreHardwareMonitor did not detect a CPU sensor device.',
    'temp_sensor_missing': 'The CPU was detected, but it exposes no temperature sensor to LibreHardwareMonitor.',
    'temp_sensor_no_value': 'The CPU temperature sensor was detected, but returned no value.',
    'temp_data_stale': 'The last CPU temperature sample is too old, so it is hidden.',
    'temp_helper_not_installed': 'The protected temperature reader is not installed. Install CyberClean to enable CPU temperature.',
    'temp_elevation_cancelled': 'Administrator approval was cancelled. No temperature was read.',
    'temp_helper_failed': 'The protected temperature reader could not start. No temperature was read.',
    'temp_click_access': 'Click this card to request Windows permission for a read-only CPU temperature sample.',
    'temp_access_pending': 'Waiting for Windows approval to read CPU temperature.',
    'temp_helper_install_title': 'Temperature reader unavailable',
    'temp_helper_install_body': 'This source-run copy cannot safely request hardware access. Install CyberClean so its protected, read-only temperature helper can run when you approve the Windows prompt.',
    'temp_unavailable': 'No fresh CPU temperature is available. The dashboard will not substitute GPU or estimated values.',
    'lbl_swap':       'SWAP',
    'lbl_cpu_chart':  'CPU %',
    'lbl_ram_chart':  'RAM %',
    'lbl_ready':      '● READY',
    'lbl_running':    'Running...',
    'lbl_mounts':     '{n} MOUNTS',
    'lbl_used_fmt':   'USED ({path}): {used} / {total} ({pct:.1f}%){extra}',
    'lbl_free_fmt':   'FREE ({path}): {free}',
    'lbl_total_dash': 'TOTAL: —',
    'lbl_free_dash':  'FREE: —',
    'oc_desc_win':    'Flush DNS  ·  Clear TEMP  ·  Drop cache  ·  TRIM SSD',
    'oc_desc_linux':  'Drop cache  ·  Tune swap  ·  TRIM SSD  ·  Clean journal',
    'oc_chip_dns_title':     '◈ DNS CACHE',
    'oc_chip_dns_sub':       'ipconfig /flushdns',
    'oc_chip_temp_title':    '⬡ TEMP PURGE',
    'oc_chip_temp_sub':      'Win Temp & Cache',
    'oc_chip_ram_title':     '⚡ RAM COMPACT',
    'oc_chip_ram_sub_win':   'Working Set Trim',
    'oc_chip_ram_sub_lin':   'Memory Defrag',
    'oc_chip_io_title':      '◎ STORAGE I/O',
    'oc_chip_io_sub':        'Volume Health',
    'oc_chip_swap_title':    '◈ SWAP TUNE',
    'oc_chip_swap_sub':      'vm.swappiness→10',
    'oc_chip_trim_title':    '⬡ SSD FSTRIM',
    'oc_chip_trim_sub':      'NVMe/SSD Blocks',
    'oc_chip_journal_title': '◎ JOURNAL',
    'oc_chip_journal_sub':   'Vacuum Logs >7d',
    # Clean
    'clean_targets':  'CLEAN TARGETS',
    'clean_subtitle': 'Select targets · Dry-run to preview · Clean to execute',
    'btn_dryrun':     'DRY-RUN',
    'btn_clean_now':  'CLEAN NOW',
    # ── 3 tiers (3.1) ───────────────────────────────────
    'tier_auto_desc':   'Always regenerable · ticked by default · the only targets the background scheduler may run.',
    'review_scanning':  'Scanning…',
    'review_deleting':  'Deleting…',
    'review_nothing':   'Nothing to review here.',
    'review_selected':  '{n} of {m} selected  ·  {size}',
    'review_confirm_perm': 'Permanently delete {n} item(s) ({size})?',
    'review_cannot_undo':  'This cannot be undone — nothing goes to the Trash.',
    'review_high_risk': 'HIGH-RISK items you selected:',
    'col_item': 'ITEM', 'col_last_used': 'LAST USED', 'col_risk': 'RISK',
    'col_note': 'NOTE', 'col_age': 'AGE', 'col_advice': 'WHAT TO DO',
    'risk_low': 'LOW', 'risk_medium': 'MEDIUM', 'risk_high': 'HIGH',
    'btn_select_safe':  'SELECT ALL (not high-risk)',
    'btn_delete_selected': 'DELETE SELECTED',
    'btn_open_folder':  'OPEN FOLDER',
    'btn_rescan':       'RESCAN',
    'advisor_title':    'Advisor report',
    'advisor_scanning': 'Scanning your disk…',
    'advisor_nothing':  'Nothing large found — your disk looks tidy.',
    'advisor_total':    'Accounted for: {size}  ·  scanned in {sec:.0f}s',
    'confirm_perm_note': 'Files are deleted permanently — they do not go to the Trash.',
    'helper_outdated':  '⚠ The privileged helper is out of date — a security fix is available.',
    'helper_missing':   'ℹ Privileged helper not installed — system targets (logs, package caches) need it. Re-run install.sh.',
    'btn_update_helper': 'UPDATE HELPER',
    'review_logged':    'Review clean: {name}',
    # ── Hai trang riêng: DEEP CLEAN + DISK ADVISOR (3.1) ─────
    'nav_deep': 'DEEP CLEAN', 'nav_advisor': 'DISK ADVISOR',
    'more_ways': 'Packages, Docker, dev caches, Trash — or find the biggest space hogs:',
    'deep_title': 'DEEP CLEAN',
    'deep_sub': 'Things that might matter — you choose every item.',
    'deep_callout': 'Nothing here is ticked for you and nothing runs in the background. High-risk rows must be ticked by hand, deletions are permanent, and every delete asks first (default answer: Cancel).',
    'deep_categories': 'CATEGORIES', 'deep_pick': 'Pick a category on the left',
    'deep_pick_hint': 'CyberClean lists every item inside it — you tick exactly what should go.',
    'deep_total': '{size} to review across {n} categories',
    'deep_none': 'No review categories are available on this system.',
    'btn_scan_all': 'SCAN ALL', 'btn_stop': 'STOP', 'btn_scan_disk': 'SCAN DISK', 'btn_copy_report': 'COPY REPORT',
    'state_scanning': 'SCANNING', 'state_items': 'ITEMS', 'state_clean': 'NOTHING TO REVIEW',
    'state_error': 'ERROR', 'state_idle': 'NOT SCANNED',
    'adv_title': 'DISK ADVISOR', 'adv_sub': 'Where your disk space really went.',
    'adv_callout': 'Read-only. This page only reads names and sizes — CyberClean never changes or deletes anything here. You decide what to do with what it finds.',
    'adv_intro_title': 'See what is eating your disk',
    'adv_intro_body': 'Finds virtual machines, game libraries, /opt, the heaviest packages, forgotten node_modules / target / venv folders, big files and your Downloads. Takes about a minute.',
    'adv_stopping': 'Stopping…', 'adv_copied': 'Report copied to the clipboard',
    'adv_tile_total': 'ACCOUNTED FOR', 'adv_tile_total_sub': 'across {n} findings',
    'adv_tile_big': 'BIGGEST CATEGORY', 'adv_tile_scan': 'SCAN',
    'adv_tile_partial': 'partial — hit the time limit', 'adv_age_tip': 'Days since this was last modified',
    'btn_all':        'ALL',
    'btn_none':       'NONE',
    'placeholder_clean': '  → Select targets and click DRY-RUN to preview...',
    'tgt_xbps_cache_name': 'XBPS Package Cache',
    'tgt_xbps_cache_desc': 'Outdated packages in /var/cache/xbps (xbps-remove -O)',
    'tgt_xbps_orphaned_name': 'XBPS Orphaned Packages',
    'tgt_xbps_orphaned_desc': 'Unneeded dependencies (xbps-remove -o)',
    'rn_chromium-service-worker-cache': 'Service Worker CacheStorage — may contain offline web-app / PWA data',
    'rn_chromium-service-worker-cache-win': 'Service Worker CacheStorage — may contain offline web-app / PWA data',
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
    'booster_kill_bloat': 'THROTTLE BACKGROUND BLOAT',
    'btn_free_now':   'FREE NOW',
    'btn_clear_cache':'CLEAR CACHE',
    'btn_tune_now':   'TUNE NOW',
    'btn_kill_bloat': 'THROTTLE BLOAT',
    'btn_game_mode':  'GAME MODE',
    'btn_eco_mode':   'ECO MODE',
    'btn_smart_boost': 'SMART BOOST',
    'smart_tooltip':    'Auto-detect PC tier — disable transparency on low-end, full Game + Eco Mode on all tiers',
    'ram_desc':       'Drop page cache, reclaim unused memory. Instant RAM boost without rebooting.',
    'cpu_desc':       'Freeze or throttle background bloat. Give foreground app 100% CPU resources.',
    'disk_desc':      'Clear GPU/shader cache, temp files. Frees VRAM, fixes video stutter & WebGL glitches.',
    'mem_tune_desc':  'Linux: set swappiness=10 + compact memory. Windows: flush standby list & optimize VM.',
    'kill_desc':      'Deprioritize idle background bloat processes safely without killing active apps.',
    'game_tooltip':   'Jail background apps to last CPU cores — no kill, no suspend, no deadlock',
    'eco_tooltip':    'Soft-throttle all background tasks to below-normal priority',
    # Common
    'btn_kill':       'KILL',
    'btn_activate':   'ACTIVATE',
    'btn_active_restore': 'ACTIVE — CLICK TO RESTORE',
    'lbl_output':     'OUTPUT',
    'lbl_language':   'Language',
    'lbl_done':       'Done',
    'kill_failed':    'Kill failed',
    'kill_terminated':'Terminated',
    'kill_confirm_title': 'Confirm Terminate Process',
    'kill_confirm_msg':   'Terminate {n} selected process(es)?\n\n{items}\n\nUnsaved work in those applications may be lost.',
    'kill_protected_msg': 'Protected system/session process (cannot be terminated from CyberClean): {names}',
    'kill_still_alive':   '{name} (PID {pid}): process did not exit after SIGTERM',
    'no_targets_title':   'No targets',
    'no_targets_msg':     'Select at least one target first.',
    'confirm_clean_msg':  'Clean {n} target(s)?',
    'uninst_busy_title':  'Busy',
    'uninst_busy_msg':    'An uninstall is already in progress.',
    'uninst_select_title':'Select',
    'uninst_select_msg':  'Select at least one app first.',
    'uninst_protected_msg': 'These are protected system packages and will NOT be removed:\n\n{items}\n\nRemoving a kernel, bootloader, init system, sudo or the network manager can leave the machine unable to boot or connect.',
    'uninst_confirm_msg': 'Uninstall {n} app(s)?{size_str}\n\n{detail}',
    'uninst_not_reversible': '  ⚠ not reversible',
    'uninst_starting':    '  ▸  Starting uninstall ({n} app(s))...',
    'uninst_running_btn': '⟳  UNINSTALLING...',
    'uninst_done_log':    '  ✓  Done — disk usage updated & refreshing list...',
    'uninst_scanning':    '⟳  Scanning installed apps...',
    'uninst_reading_reg': '  ⟳  Reading app registry — please wait...',
    'uninst_placeholder_log': '  → Select an app and click Uninstall...',
    'clear_history_title':'Clear',
    'clear_history_msg':  'Delete all history?',
    'clear_rollback_msg': 'Delete rollback history?',
    'helper_updated_msg': 'Helper updated.',
    'helper_update_err':  'Could not update the helper:\n{msg}',
    'polkit_warn_msg':    'The privileged helper is not installed, so root-level cleaning (system logs, package caches, journal) is unavailable.\n\nFix: re-run the installer\n  curl -fsSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash\n\nPlease do NOT start the whole app with sudo: the GUI loses access to your desktop session (Wayland/DBus) and may treat /root as your home folder.',
    'empty_apps_title':   'No applications found',
    'empty_apps_body':    'Try changing the filter, or click Refresh to rescan installed applications.',
    'empty_history_title':'No cleaning history yet',
    'empty_history_body': 'Run DRY-RUN or CLEAN on the Clean tab — results will appear here.',
    'empty_rollback_title':'No deleted items yet',
    'empty_rollback_body':'Clean and uninstall operations will be logged here for auditing.',
    'msg_restart':    'Please restart CyberClean to apply language changes.',
    'msg_restart_title': 'Restart Required',
    'confirm_clean':  'Confirm Clean',
    'confirm_uninstall': 'Uninstall',
    'setup_required': 'Setup Required',
    'badge_safe':     'SAFE',
    'badge_locked':   'LOCKED',
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
    'upd_installing_optimizing': 'Installing… this can take a little while, please don\'t close the app',
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
    'log_psi_active': 'PSI monitor: active — auto kill-bloat on memory pressure',
    'log_mem_compacted': 'Memory compacted — fragmented pages defragged',
    'log_cache_preserved': 'Page cache preserved — browser/app data stays warm',
    'log_scan_bloat': 'Scanning for background bloat...',
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
    # Uninstaller
    'uninstall_found':   'Found {n} apps — select one or more, then click Uninstall',
    'lbl_installer_open':'Installer window opened — complete it, then click REFRESH',
    # Booster active label
    'lbl_smart_active':  'ACTIVE',
    'boost_btn_idle':        'BOOST',
    'boost_btn_active':      'ACTIVE',
    'boost_hud_sub':         'Tactical resource optimizer · automatic state snapshot & restore on exit',
    'boost_state_standby':   'STANDBY',
    'boost_state_scanning':  'SCANNING',
    'boost_state_monitoring':'MONITORING',
    'boost_state_restoring': 'RESTORING',
    'boost_mc_gpu':          'GPU BUSY',
    'boost_mc_cpu_proxy':    'CPU LOAD',
    'boost_mc_ram':          'RAM FREED',
    'boost_mc_bg':           'BACKGROUND',
    'boost_mc_game':         'GAME DETECT',
    'boost_profile_lbl':     'ACTIVE MODULES:',
    'boost_mod_ram':         'Compact / Free RAM',
    'boost_mod_gov':         'CPU Performance Mode',
    'boost_mod_prio':        'Process Priority (Nice)',
    'boost_mod_swap':        'Low Swappiness',
    'boost_mod_hypr':        'Hyprland VFR / Scanout',
    'boost_phase_scan':      '1 · SCAN',
    'boost_phase_apply':     '2 · APPLY',
    'boost_phase_monitor':   '3 · MONITOR',
    'boost_log_placeholder': 'Press BOOST to scan GPU / RAM / background load…',
    'boost_log_ready':       '[ ready — press BOOST to optimize ]',
    'boost_no_game':         'no game',
    'autoclean_btn_off':     'Auto-Clean: OFF',
    'autoclean_btn_on':      'Auto-Clean: ON (6h)',
    'autoclean_tip':         'Toggle background idle cleanup of safe cache targets (default: OFF; never touches Trash/Recycle Bin)',
    'filter_all':            'ALL',
    'btn_theme_light':       'LIGHT MODE',
    'btn_theme_dark':        'CYBER DARK',
    'theme_toggle_tip':      'Switch between Cyber Dark Mode and Harmonious Light Mode',
    'lbl_holo_3d':           '3D HOLO DISK CORE',
    'warn_trash':            'Permanently deleted — NOT moved anywhere. Nothing is selected by default.',
    'trash_in_dir':          'In Trash',
    'trash_perm_del':        'permanently deleted — cannot be restored',
    'win_dism_reboot_warn':  '⚠ DISM cleanup completed — please RESTART Windows (Start → Restart) to finish freeing space',
},

# ════════════════════════════════════════════════════
# TIẾNG VIỆT  — tự nhiên, có hồn, không máy móc
# ════════════════════════════════════════════════════
'vi': {
    # Nav — ngắn gọn, dễ nhận diện
    'nav_dashboard':  'TỔNG QUAN',
    'nav_clean':      'DỌN RÁC',
    'nav_uninstall':  'GỠ ỨNG DỤNG',
    'nav_history':    'LỊCH SỬ',
    'nav_rollback':   'NHẬT KÝ XÓA',
    'nav_booster':    'TĂNG TỐC',
    # Dashboard
    'sys_overview':   'TỔNG QUAN HỆ THỐNG',
    'btn_refresh':    'LÀM MỚI',
    'lbl_health':     'CHỈ SỐ TẢI',
    'lbl_oneclick':   'TỐI ƯU MỘT CHẠM',
    'btn_optimize':   'TỐI ƯU NGAY',
    'lbl_top_proc':   'TIẾN TRÌNH TOP',
    'lbl_disk':       'DUNG LƯỢNG Ổ ĐĨA',
    'lbl_drive':      'Ổ ĐĨA',
    'col_drive':      'Ổ đĩa',
    'sys_healthy':    'Tải ổn định',
    'health_disk': 'Ổ đĩa',
    'health_temperature': 'nhiệt độ',
    'health_none': 'không có',
    'health_waiting': 'Đang chờ số liệu hệ thống',
    'health_partial': 'Ước tính · thiếu {metrics}',
    'health_score_explanation': 'Điểm ước tính: càng cao thì hệ thống càng còn dư tài nguyên. Đây không phải % CPU hay độ bền phần cứng. Số liệu còn thiếu: {metrics}.',
    'health_tooltip': 'Chỉ số tải ước lượng từ CPU, RAM, dung lượng đĩa, nhiệt độ và swap (không phải SMART phần cứng).',
    'lbl_calculating':'Đang tính toán...',
    'lbl_temperature':'NHIỆT ĐỘ',
    'temp_source_cpu': 'Cảm biến CPU',
    'temp_reading_ok': 'Nguồn: {source}; mẫu mới nhất cách đây {age:.1f} giây.',
    'temp_reading_ok_no_age': 'Nguồn: {source}.',
    'temp_pawnio_missing': 'LHM đã nhận diện CPU nhưng chưa có PawnIO. Windows cần bạn duyệt quyền quản trị để cài driver cảm biến này.',
    'temp_access_denied': 'Windows từ chối quyền đọc cảm biến CPU. Cảm biến này cần quyền quản trị để truy cập phần cứng.',
    'temp_driver_blocked': 'Windows đã chặn driver cảm biến. Không hiển thị nhiệt độ; hãy giữ nguyên các lớp bảo vệ của Windows.',
    'temp_driver_unavailable': 'Driver cảm biến phần cứng hiện không dùng được nên chưa đọc được nhiệt độ.',
    'temp_hardware_missing': 'LibreHardwareMonitor chưa nhận diện được thiết bị cảm biến CPU.',
    'temp_sensor_missing': 'Đã nhận diện CPU nhưng CPU không cung cấp cảm biến nhiệt độ cho LibreHardwareMonitor.',
    'temp_sensor_no_value': 'Đã nhận diện cảm biến nhiệt CPU nhưng cảm biến chưa trả về số đo.',
    'temp_data_stale': 'Mẫu nhiệt độ CPU đã cũ nên được ẩn đi.',
    'temp_helper_not_installed': 'Chưa cài bộ đọc nhiệt độ được bảo vệ. Hãy cài CyberClean để bật số đo nhiệt CPU.',
    'temp_elevation_cancelled': 'Bạn đã hủy quyền quản trị. Chưa có số đo nhiệt độ nào được đọc.',
    'temp_helper_failed': 'Không khởi động được bộ đọc nhiệt độ an toàn. Chưa có số đo nào được đọc.',
    'temp_click_access': 'Nhấp thẻ này để xin Windows quyền chỉ đọc nhiệt độ CPU.',
    'temp_access_pending': 'Đang chờ Windows cho phép đọc nhiệt độ CPU.',
    'temp_helper_install_title': 'Chưa có bộ đọc nhiệt độ',
    'temp_helper_install_body': 'Bản chạy trực tiếp từ mã nguồn không thể xin quyền phần cứng một cách an toàn. Hãy cài CyberClean để bộ đọc nhiệt độ chỉ đọc, được bảo vệ, có thể chạy khi bạn duyệt thông báo Windows.',
    'temp_unavailable': 'Chưa có số đo nhiệt độ CPU mới. Bảng điều khiển không thay bằng nhiệt GPU hoặc số ước tính.',
    'lbl_swap':       'SWAP',
    'lbl_cpu_chart':  'CPU %',
    'lbl_ram_chart':  'RAM %',
    'lbl_ready':      '● SẴN SÀNG',
    'lbl_running':    'Đang chạy...',
    'lbl_mounts':     '{n} PHÂN VÙNG',
    'lbl_used_fmt':   'ĐÃ DÙNG ({path}): {used} / {total} ({pct:.1f}%){extra}',
    'lbl_free_fmt':   'CÒN TRỐNG ({path}): {free}',
    'lbl_total_dash': 'TỔNG: —',
    'lbl_free_dash':  'CÒN TRỐNG: —',
    'oc_desc_win':    'Xóa cache DNS  ·  Dọn TEMP  ·  Xả cache  ·  TRIM SSD',
    'oc_desc_linux':  'Xả cache  ·  Chỉnh swap  ·  TRIM SSD  ·  Dọn journal',
    'oc_chip_dns_title':     '◈ CACHE DNS',
    'oc_chip_dns_sub':       'ipconfig /flushdns',
    'oc_chip_temp_title':    '⬡ DỌN TEMP',
    'oc_chip_temp_sub':      'Temp & Cache Windows',
    'oc_chip_ram_title':     '⚡ GOM RAM',
    'oc_chip_ram_sub_win':   'Thu gọn Working Set',
    'oc_chip_ram_sub_lin':   'Chống phân mảnh RAM',
    'oc_chip_io_title':      '◎ Ổ ĐĨA I/O',
    'oc_chip_io_sub':        'Tối ưu phân vùng',
    'oc_chip_swap_title':    '◈ CHỈNH SWAP',
    'oc_chip_swap_sub':      'vm.swappiness→10',
    'oc_chip_trim_title':    '⬡ SSD FSTRIM',
    'oc_chip_trim_sub':      'Khối NVMe/SSD',
    'oc_chip_journal_title': '◎ JOURNAL',
    'oc_chip_journal_sub':   'Dọn log >7 ngày',
    # Clean
    'clean_targets':  'MỤC TIÊU DỌN DẸP',
    'clean_subtitle': 'Chọn mục tiêu · Chạy thử · Dọn dẹp',
    'btn_dryrun':     'CHẠY THỬ',
    'btn_clean_now':  'DỌN NGAY',
    # ── 3 tầng (3.1) ────────────────────────────────────
    'tier_auto_desc':   'Luôn tái tạo được · tick sẵn · là nhóm duy nhất được phép chạy nền.',
    'review_scanning':  'Đang quét…',
    'review_deleting':  'Đang xóa…',
    'review_nothing':   'Không có gì để xem lại ở đây.',
    'review_selected':  'Đã chọn {n}/{m}  ·  {size}',
    'review_confirm_perm': 'Xóa vĩnh viễn {n} mục ({size})?',
    'review_cannot_undo':  'Không thể hoàn tác — không đi vào Thùng rác.',
    'review_high_risk': 'Mục RỦI RO CAO bạn đã chọn:',
    'col_item': 'MỤC', 'col_last_used': 'DÙNG CUỐI', 'col_risk': 'RỦI RO',
    'col_note': 'GHI CHÚ', 'col_age': 'TUỔI', 'col_advice': 'NÊN LÀM GÌ',
    'risk_low': 'THẤP', 'risk_medium': 'VỪA', 'risk_high': 'CAO',
    'btn_select_safe':  'CHỌN HẾT (trừ rủi ro cao)',
    'btn_delete_selected': 'XÓA MỤC ĐÃ CHỌN',
    'btn_open_folder':  'MỞ THƯ MỤC',
    'btn_rescan':       'QUÉT LẠI',
    'advisor_title':    'Báo cáo tư vấn',
    'advisor_scanning': 'Đang quét ổ đĩa…',
    'advisor_nothing':  'Không thấy gì lớn — ổ đĩa của bạn khá gọn.',
    'advisor_total':    'Đã thống kê: {size}  ·  quét trong {sec:.0f}s',
    'confirm_perm_note': 'File bị xóa vĩnh viễn — không đi vào Thùng rác.',
    'helper_outdated':  '⚠ Helper đặc quyền đã cũ — có bản vá bảo mật.',
    'helper_missing':   'ℹ Chưa cài helper đặc quyền — các mục hệ thống (log, cache gói) cần nó. Chạy lại install.sh.',
    'btn_update_helper': 'CẬP NHẬT HELPER',
    'review_logged':    'Dọn từ Xem lại: {name}',
    # ── Hai trang riêng: DEEP CLEAN + DISK ADVISOR (3.1) ─────
    'nav_deep': 'DỌN SÂU', 'nav_advisor': 'TƯ VẤN Ổ ĐĨA',
    'more_ways': 'Gói phần mềm, Docker, cache lập trình, Thùng rác — hoặc tìm thứ ngốn nhiều dung lượng nhất:',
    'deep_title': 'DỌN SÂU',
    'deep_sub': 'Những thứ có thể quan trọng — bạn tự chọn từng mục.',
    'deep_callout': 'Không có gì được tick sẵn và không có gì chạy nền. Mục rủi ro cao phải tự tay tick, xóa là xóa vĩnh viễn, và lần nào cũng hỏi lại trước (mặc định là Hủy).',
    'deep_categories': 'DANH MỤC', 'deep_pick': 'Chọn một danh mục ở bên trái',
    'deep_pick_hint': 'CyberClean liệt kê từng mục bên trong — bạn tick đúng thứ muốn xóa.',
    'deep_total': '{size} có thể xem lại ở {n} danh mục',
    'deep_none': 'Hệ thống này không có danh mục nào cần xem lại.',
    'btn_scan_all': 'QUÉT TẤT CẢ', 'btn_stop': 'DỪNG', 'btn_scan_disk': 'QUÉT Ổ ĐĨA', 'btn_copy_report': 'SAO CHÉP BÁO CÁO',
    'state_scanning': 'ĐANG QUÉT', 'state_items': 'MỤC', 'state_clean': 'KHÔNG CÓ GÌ',
    'state_error': 'LỖI', 'state_idle': 'CHƯA QUÉT',
    'adv_title': 'TƯ VẤN Ổ ĐĨA', 'adv_sub': 'Dung lượng ổ đĩa của bạn thật sự đi đâu.',
    'adv_callout': 'Chỉ đọc. Trang này chỉ đọc tên và dung lượng — CyberClean không bao giờ sửa hay xóa gì ở đây. Bạn tự quyết định làm gì với kết quả.',
    'adv_intro_title': 'Xem cái gì đang ngốn ổ đĩa của bạn',
    'adv_intro_body': 'Tìm máy ảo, thư viện game, /opt, các gói nặng nhất, thư mục node_modules / target / venv bị bỏ quên, file lớn và thư mục Downloads. Mất khoảng một phút.',
    'adv_stopping': 'Đang dừng…', 'adv_copied': 'Đã sao chép báo cáo vào clipboard',
    'adv_tile_total': 'ĐÃ THỐNG KÊ', 'adv_tile_total_sub': 'trong {n} mục',
    'adv_tile_big': 'DANH MỤC LỚN NHẤT', 'adv_tile_scan': 'LẦN QUÉT',
    'adv_tile_partial': 'chưa đủ — hết thời gian quét', 'adv_age_tip': 'Số ngày kể từ lần sửa gần nhất',
    # ── Nội dung báo cáo Advisor (bản Việt; bản Anh nằm trong core/advisor.py) ──
    'adv_cat_vm': 'Máy ảo & ảnh đĩa',
    'adv_cat_games': 'Game & lớp tương thích',
    'adv_cat_containers': 'Container',
    'adv_cat_wsl': 'Ổ đĩa WSL / Docker Desktop',
    'adv_cat_windows': 'Thứ còn sót của Windows',
    'adv_cat_projects': 'Thư mục build của dự án cũ',
    'adv_cat_packages': 'Gói cài đặt nặng nhất',
    'adv_cat_opt': '/opt',
    'adv_cat_downloads': 'Thư mục Downloads',
    'adv_cat_large': 'File lớn',
    'adv_cat_info': 'Ghi chú',
    'adv_dl_title': 'Thư mục Downloads — {n} mục',
    'adv_dl_summary': '{n} mục ({size}) cũ hơn {days} ngày. Sắp xếp theo dung lượng và xóa bộ cài / ISO không cần nữa.',
    'adv_dl_iso': 'File ISO — chỉ giữ nếu bạn còn cần để cài đặt',
    'adv_dl_archive': 'File nén — đã giải nén rồi thì có thể xóa',
    'adv_dl_installer': 'Bộ cài / gói — thường xóa được sau khi đã cài xong',
    'adv_dl_large': 'File tải về lớn',
    'adv_big_vm': 'Máy ảo / ảnh đĩa — tắt máy ảo rồi xóa (hoặc thu gọn đĩa) nếu bạn không còn dùng',
    'adv_big_iso': 'File ISO — xóa sau khi đã cài xong hệ điều hành cần dùng nó',
    'adv_big_game': 'Dữ liệu game — hãy gỡ từ launcher (Steam/Heroic/Lutris) thay vì xóa tay',
    'adv_big_large': 'File lớn — kiểm tra xem bạn còn cần nó không',
    'adv_proj_node': 'Dự án không đụng tới {age} ngày; chạy `npm install` / `pnpm install` là dựng lại được.',
    'adv_proj_node_noage': '`npm install` / `pnpm install` dựng lại được.',
    'adv_proj_cargo': 'Dự án không đụng tới {age} ngày; `cargo build` dựng lại được (hoặc `cargo clean`).',
    'adv_proj_cargo_noage': '`cargo build` dựng lại được (hoặc `cargo clean`).',
    'adv_proj_venv': 'Dự án không đụng tới {age} ngày; tạo lại bằng `python -m venv` + `pip install -r requirements.txt`.',
    'adv_proj_venv_noage': 'Tạo lại bằng `python -m venv` + `pip install -r requirements.txt`.',
    'adv_opt_dir': 'Cài ngoài trình quản lý gói — gỡ bằng trình gỡ cài đặt của hãng, hoặc xóa thư mục nếu không còn dùng.',
    'adv_pkg_remove': 'Gói đã cài — nếu không dùng, hãy gỡ bằng trình quản lý gói (tab Gỡ ứng dụng).',
    'adv_flatpak_remove': '`flatpak uninstall --delete-data <app>` gỡ app cùng dữ liệu của nó.',
    'adv_container': '{reclaim} có thể thu hồi. Vào Dọn sâu → Docker/Podman để chọn thứ cần xóa.',
    'adv_game_uninstall': 'Game đã cài — gỡ từ launcher nếu bạn không còn chơi.',
    'adv_wine_prefix': 'Wine prefix / dữ liệu launcher — chỉ xóa prefix khi không game nào còn dùng.',
    'adv_win_old': 'Bản Windows trước đó. Gỡ bằng Cài đặt → Hệ thống → Lưu trữ → Tệp tạm thời ("Bản cài đặt Windows trước"), đừng xóa tay.',
    'adv_hiberfil': 'File ngủ đông. `powercfg /h off` (quyền admin) gỡ nó nếu bạn không dùng hibernate hay Fast Startup.',
    'adv_pagefile': 'File bộ nhớ ảo — chỉnh kích thước ở System Properties → Advanced → Performance; đừng xóa.',
    'adv_swapfile': 'File swap của UWP — do Windows quản lý.',
    'adv_pkg_cache': 'Cache cài đặt dùng để sửa/gỡ chương trình — để yên trừ khi bạn biết cái nào mồ côi.',
    'adv_installer_cache': 'Cache bản vá Windows Installer — KHÔNG BAO GIỜ xóa tay (hỏng gỡ/sửa chương trình).',
    'adv_wsl_disk': 'Ổ ảo này chỉ phình ra. Giải phóng chỗ trong distro trước, rồi thu nhỏ: `wsl --shutdown` và `wsl --manage <distro> --set-sparse true`, hoặc Optimize-VHD.',
    # ── Tên/mô tả target + ghi chú luật (3.1) ───────────────
    'tgt_pacman_cache_name': 'Cache Pacman',
    'tgt_pacman_cache_desc': 'Phiên bản gói cũ — giữ 2 bản mới nhất (cần pacman-contrib)',
    'tgt_pacman_broken_name': 'Tải dở (Pacman)',
    'tgt_pacman_broken_desc': 'download-* / *.part dang dở trong cache pacman (bỏ qua khi pacman đang chạy)',
    'tgt_apt_cache_name': 'Cache APT',
    'tgt_apt_cache_desc': 'Gói .deb đã tải trong /var/cache/apt',
    'tgt_dnf_cache_name': 'Cache DNF',
    'tgt_dnf_cache_desc': 'Gói RPM và metadata đã tải',
    'tgt_zypper_cache_name': 'Cache Zypper',
    'tgt_zypper_cache_desc': 'Gói đã tải trong /var/cache/zypp',
    'tgt_xbps_cache_name': 'Cache gói XBPS',
    'tgt_xbps_cache_desc': 'Gói lỗi thời trong /var/cache/xbps (xbps-remove -O)',
    'tgt_apk_cache_name': 'Cache APK',
    'tgt_apk_cache_desc': 'Cache gói trong /var/cache/apk (apk cache clean)',
    'tgt_rpm_ostree_name': 'Cache rpm-ostree',
    'tgt_rpm_ostree_desc': 'Cache base + rpm-md (rpm-ostree cleanup -bm) — các deployment được giữ lại',
    'tgt_aur_cache_name': 'Cache build AUR',
    'tgt_aur_cache_desc': '~/.cache/yay và ~/.cache/paru — chỉ khi yay/paru/makepkg/pacman không chạy',
    'tgt_journal_name': 'Nhật ký Journal',
    'tgt_journal_desc': 'Log systemd cũ hơn 7 ngày (giới hạn 500 MB)',
    'tgt_chromium_cache_name': 'Cache trình duyệt & app Electron',
    'tgt_chromium_cache_desc': 'Chrome, Brave, Edge, Vivaldi, Opera, VS Code, Discord, Slack… — chỉ cache, không đụng cookie/đăng nhập',
    'tgt_firefox_cache_name': 'Cache Firefox',
    'tgt_firefox_cache_desc': 'cache2 / startupCache của mọi profile (cả Flatpak & Snap) — tự dựng lại',
    'tgt_thumbnails_name': 'Ảnh thu nhỏ',
    'tgt_thumbnails_desc': 'Ảnh xem trước của trình quản lý file — tự dựng lại khi cần',
    'tgt_pip_cache_name': 'Cache Pip',
    'tgt_pip_cache_desc': '~/.cache/pip — wheel đã tải, tải lại khi cần',
    'tgt_tmp_files_name': 'File tạm',
    'tgt_tmp_files_desc': '/tmp và /var/tmp: không đụng tới ≥ 3 ngày, không đang dùng, không chứa socket',
    'tgt_system_logs_name': 'Log hệ thống cũ',
    'tgt_system_logs_desc': 'Log đã xoay vòng trong /var/log (.gz, .1, .old) — log đang dùng được giữ lại',
    'tgt_crash_reports_name': 'Báo cáo crash',
    'tgt_crash_reports_desc': 'Core dump, apport, systemd-coredump — chỉ file cũ hơn 1 giờ',
    'tgt_orphaned_pkgs_name': 'Gói mồ côi',
    'tgt_orphaned_pkgs_desc': 'Gói không còn gói nào cần — chọn từng gói để gỡ',
    'tgt_apt_autoremove_name': 'APT Autoremove',
    'tgt_apt_autoremove_desc': 'Gói thừa và kernel cũ — chọn từng gói để gỡ',
    'tgt_dnf_autoremove_name': 'DNF Autoremove',
    'tgt_dnf_autoremove_desc': 'Dependency không còn cần — chọn từng gói để gỡ',
    'tgt_xbps_orphaned_name': 'Gói mồ côi XBPS',
    'tgt_xbps_orphaned_desc': 'Gói không còn được yêu cầu (xbps-remove -o)',
    'tgt_nix_gc_name': 'Dọn rác Nix',
    'tgt_nix_gc_desc': 'Xóa generation cũ của user-profile và store path không còn tham chiếu',
    'tgt_empty_trash_name': 'Thùng rác',
    'tgt_empty_trash_desc': 'File bạn đã xóa — chỉ xóa vĩnh viễn những mục BẠN tick',
    'tgt_flatpak_name': 'Runtime Flatpak không dùng',
    'tgt_flatpak_desc': 'Runtime không app nào cần (user + system)',
    'tgt_flatpak_cache_name': 'Cache app Flatpak',
    'tgt_flatpak_cache_desc': '~/.var/app/*/cache của từng app — mặc định KHÔNG chọn mục nào',
    'tgt_docker_name': 'Docker/Podman',
    'tgt_docker_desc': 'Image mồ côi, container đã dừng, build cache, volume không dùng — chọn từng mục',
    'tgt_snap_old_name': 'Bản Snap cũ',
    'tgt_snap_old_desc': 'Chỉ các revision đã tắt (bản đang dùng được giữ lại)',
    'tgt_dev_cache_name': 'Cache lập trình',
    'tgt_dev_cache_desc': 'npm, yarn, pnpm, gradle, maven, cargo, go, JetBrains… — chọn từng mục; tải lại ở lần build sau',
    'tgt_app_cache_name': 'Cache app khác (~/.cache)',
    'tgt_app_cache_desc': 'Thư mục lạ trong ~/.cache, không dùng ≥ 14 ngày — mặc định KHÔNG chọn mục nào',
    'tgt_win_temp_name': 'Temp Windows',
    'tgt_win_temp_desc': '%TEMP% và C:\\Windows\\Temp — mục không đụng tới ≥ 24 giờ, không bị khóa, không thuộc thư mục app được bảo vệ',
    'tgt_win_thumbcache_name': 'Cache ảnh thu nhỏ',
    'tgt_win_thumbcache_desc': 'thumbcache_*.db của Explorer — tự dựng lại',
    'tgt_win_error_reports_name': 'Báo cáo lỗi Windows',
    'tgt_win_error_reports_desc': 'Kho báo cáo WER cũ hơn 7 ngày',
    'tgt_win_dns_name': 'Cache DNS',
    'tgt_win_dns_desc': 'Xóa cache DNS resolver (không giải phóng dung lượng đĩa)',
    'tgt_win_recycle_name': 'Thùng rác',
    'tgt_win_recycle_desc': 'Làm trống Thùng rác trên mọi ổ — xóa vĩnh viễn',
    'tgt_win_prefetch_name': 'Cache Prefetch',
    'tgt_win_prefetch_desc': 'Prefetch khởi chạy app (.pf cũ hơn 7 ngày) — app khởi động chậm hơn một lần khi nó dựng lại',
    'tgt_win_updates_name': 'Cache Windows Update',
    'tgt_win_updates_desc': 'SoftwareDistribution\\Download — dừng dịch vụ Windows Update khi dọn',
    'tgt_win_delivery_name': 'Delivery Optimization',
    'tgt_win_delivery_desc': 'Cache P2P của Windows Update — dừng dịch vụ DoSvc khi dọn',
    'tgt_win_font_cache_name': 'Cache phông chữ',
    'tgt_win_font_cache_desc': 'FontCache*.dat — dựng lại ở lần khởi động sau (mục xử lý sự cố)',
    'tgt_win_shader_cache_name': 'Cache shader GPU',
    'tgt_win_shader_cache_desc': 'Cache shader DirectX/GPU — game giật khi chạy lần đầu trong lúc dựng lại',
    'tgt_win_winsxs_name': 'Dọn WinSxS',
    'tgt_win_winsxs_desc': 'DISM chỉ gỡ thành phần đã bị thay thế — chậm, có thể cần khởi động lại',
    'tgt_win_eventlog_name': 'Nhật ký sự kiện',
    'tgt_win_eventlog_desc': 'Xóa TOÀN BỘ log Event Viewer (wevtutil) — mất dữ liệu chẩn đoán',
    'tgt_win_crash_dumps_name': 'Crash dump (Minidump)',
    'tgt_win_crash_dumps_desc': 'Minidump + MEMORY.DMP + CrashDumps — bằng chứng duy nhất của một BSOD',
    'rn_chromium-family': 'cache — tự dựng lại khi mở app',
    'rn_chromium-family-win': 'cache — tự dựng lại khi mở app',
    'rn_chromium-service-worker-cache': 'Service Worker CacheStorage — có thể chứa dữ liệu ứng dụng web / PWA chạy offline',
    'rn_chromium-service-worker-cache-win': 'Service Worker CacheStorage — có thể chứa dữ liệu ứng dụng web / PWA chạy offline',
    'rn_firefox': 'cache — tự dựng lại khi mở trình duyệt',
    'rn_firefox-win': 'cache — tự dựng lại khi mở trình duyệt',
    'rn_thumbnails': 'ảnh xem trước — dựng lại khi mở thư mục',
    'rn_tmp-children': 'file tạm cũ',
    'rn_vartmp-children': 'file tạm cũ (tồn tại qua reboot)',
    'rn_aur': 'thư mục build + gói đã build — tải/build lại khi cài',
    'rn_crash-user-apport': 'báo cáo crash của user',
    'rn_crash-core-files': 'core dump thô',
    'rn_dev-npm': 'cache gói npm',
    'rn_dev-yarn': 'cache yarn',
    'rn_dev-pnpm': 'pnpm store — hardlink vào node_modules nên giải phóng được ít hơn dung lượng hiển thị',
    'rn_dev-gradle': 'cache dependency + build của Gradle (đóng Gradle daemon / IDE trước)',
    'rn_dev-maven': 'CẨN THẬN: chứa cả thư viện bạn tự `mvn install` ở máy — KHÔNG tải lại được từ mạng',
    'rn_dev-cargo': 'crate đã tải (src/ được giữ lại)',
    'rn_dev-go-mod': 'cache tải module Go (file read-only được xử lý riêng)',
    'rn_dev-go-build': 'cache build của Go',
    'rn_dev-cypress': 'binary Cypress (~500 MB/phiên bản) — tải lại khi chạy test',
    'rn_dev-playwright': 'browser của Playwright — cần `npx playwright install` lại',
    'rn_dev-jetbrains': 'index cache của IDE — IDE sẽ index lại dự án (đóng IDE trước)',
    'rn_dev-node-gyp': 'header node-gyp / binary Electron',
    'rn_dev-python-tools': 'pre-commit / uv / poetry / pipenv / tsserver',
    'rn_dev-compiler-cache': 'ccache/sccache — lần build kế tiếp sẽ chậm hơn',
    'rn_app-cache-children': 'không rõ app nào — kiểm tra trước khi xóa',
    'rn_flatpak-app-cache': 'cache của app Flatpak (app phải đã tắt)',
    'rn_dev-npm-win': 'cache gói npm',
    'rn_dev-yarn-win': 'cache yarn',
    'rn_dev-pnpm-win': 'pnpm store — hardlink vào node_modules nên giải phóng được ít hơn dung lượng hiển thị',
    'rn_dev-pip-win': 'cache wheel của pip',
    'rn_dev-nuget-win': 'cache http của NuGet (gói đã restore ở ~/.nuget/packages không bị đụng)',
    'rn_dev-gradle-win': 'cache dependency + build của Gradle (đóng Gradle daemon / IDE trước)',
    'rn_dev-maven-win': 'CẨN THẬN: chứa cả thư viện bạn tự `mvn install` ở máy — KHÔNG tải lại được từ mạng',
    'rn_dev-cargo-win': 'crate đã tải (src/ được giữ lại)',
    'rn_dev-go-win': 'cache tải module Go + cache build',
    'rn_dev-cypress-win': 'binary Cypress — tải lại khi chạy test',
    'rn_dev-playwright-win': 'browser của Playwright — cần `npx playwright install` lại',
    'rn_dev-jetbrains-win': 'index cache của IDE — IDE sẽ index lại dự án (đóng IDE trước)',
    'btn_all':        'CHỌN TẤT',
    'btn_none':       'BỎ CHỌN',
    'placeholder_clean': '  → Chọn mục tiêu rồi nhấn CHẠY THỬ để kiểm tra trước khi xóa...',
    # Scanner
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
    'booster_kill_bloat': 'HẠ ƯU TIÊN TIẾN TRÌNH NỀN',
    'btn_free_now':   'GIẢI PHÓNG NGAY',
    'btn_clear_cache':'XÓA CACHE',
    'btn_tune_now':   'TINH CHỈNH',
    'btn_kill_bloat': 'HẠ ƯU TIÊN NỀN',
    'btn_game_mode':  'CHẾ ĐỘ GAME',
    'btn_eco_mode':   'CHẾ ĐỘ TIẾT KIỆM',
    'btn_smart_boost': 'TĂNG TỐC THÔNG MINH',
    'smart_tooltip':    'Tự nhận diện cấu hình máy — tối ưu phù hợp cho từng loại',
    'ram_desc':       'Xả page cache, thu hồi bộ nhớ chưa dùng. Tăng RAM ngay, không cần khởi động lại.',
    'cpu_desc':       'Nhốt app nền vào nhân CPU cuối, dành toàn bộ nhân chính cho game hoặc app đang chạy.',
    'disk_desc':      'Xóa GPU/shader cache và file tạm. Giải phóng VRAM, khắc phục giật lag & WebGL.',
    'mem_tune_desc':  'Linux: swappiness=10 + compact bộ nhớ. Windows: xả standby list & tối ưu VM.',
    'kill_desc':      'Hạ độ ưu tiên các tiến trình nền rảnh rỗi ngốn RAM một cách an toàn (không tắt ngang ứng dụng).',
    'game_tooltip':   'Nhốt app nền vào CPU cuối — không kill, không treo, không deadlock',
    'eco_tooltip':    'Hạ nhẹ độ ưu tiên toàn bộ tiến trình nền, nhường tài nguyên cho app đang dùng',
    # Common
    'btn_kill':       'KẾT THÚC',
    'btn_activate':   'KÍCH HOẠT',
    'btn_active_restore': 'ĐANG BẬT — NHẤN ĐỂ TẮT',
    'lbl_output':     'KẾT QUẢ',
    'lbl_language':   'Ngôn ngữ',
    'lbl_done':       'Hoàn tất',
    'kill_failed':    'Không thể kết thúc tiến trình',
    'kill_terminated':'Đã kết thúc',
    'kill_confirm_title': 'Xác nhận kết thúc tiến trình',
    'kill_confirm_msg':   'Kết thúc {n} tiến trình đã chọn?\n\n{items}\n\nDữ liệu chưa lưu trong các ứng dụng đó có thể bị mất.',
    'kill_protected_msg': 'Tiến trình hệ thống/phiên làm việc được bảo vệ (không cho phép tắt từ CyberClean): {names}',
    'kill_still_alive':   '{name} (PID {pid}): tiến trình vẫn còn chạy sau khi gửi tín hiệu kết thúc',
    'no_targets_title':   'Chưa chọn mục tiêu',
    'no_targets_msg':     'Vui lòng chọn ít nhất một mục tiêu trước.',
    'confirm_clean_msg':  'Dọn dẹp {n} mục tiêu đã chọn?',
    'uninst_busy_title':  'Đang bận',
    'uninst_busy_msg':    'Đang có thao tác gỡ cài đặt khác chạy.',
    'uninst_select_title':'Chọn ứng dụng',
    'uninst_select_msg':  'Vui lòng chọn ít nhất một ứng dụng trước.',
    'uninst_protected_msg': 'Các gói hệ thống được bảo vệ dưới đây sẽ KHÔNG bị gỡ:\n\n{items}\n\nViệc gỡ kernel, bootloader, init, sudo hoặc trình quản lý mạng có thể khiến máy không thể khởi động hoặc mất mạng.',
    'uninst_confirm_msg': 'Gỡ cài đặt {n} ứng dụng?{size_str}\n\n{detail}',
    'uninst_not_reversible': '  ⚠ không thể hoàn tác',
    'uninst_starting':    '  ▸  Bắt đầu gỡ cài đặt ({n} ứng dụng)...',
    'uninst_running_btn': '⟳  ĐANG GỠ...',
    'uninst_done_log':    '  ✓  Hoàn tất — đã cập nhật dung lượng đĩa và làm mới danh sách...',
    'uninst_scanning':    '⟳  Đang quét danh sách ứng dụng đã cài...',
    'uninst_reading_reg': '  ⟳  Đang đọc danh sách ứng dụng — vui lòng đợi...',
    'uninst_placeholder_log': '  → Chọn ứng dụng rồi nhấn Gỡ đã chọn...',
    'clear_history_title':'Xóa lịch sử',
    'clear_history_msg':  'Xóa toàn bộ lịch sử dọn dẹp?',
    'clear_rollback_msg': 'Xóa toàn bộ nhật ký file đã xóa?',
    'helper_updated_msg': 'Đã cập nhật helper.',
    'helper_update_err':  'Không thể cập nhật helper:\n{msg}',
    'polkit_warn_msg':    'Chưa cài đặt helper đặc quyền nên các mục dọn cấp hệ thống (log hệ thống, cache gói, journal) chưa dùng được.\n\nCách khắc phục: chạy lại trình cài đặt\n  curl -fsSL https://raw.githubusercontent.com/vuphitung/CyberClean/main/install.sh | sudo bash\n\nVui lòng KHÔNG chạy toàn bộ ứng dụng bằng sudo: giao diện đồ họa sẽ mất kết nối phiên desktop (Wayland/DBus) và có thể nhận nhầm /root là thư mục người dùng.',
    'empty_apps_title':   'Không tìm thấy ứng dụng',
    'empty_apps_body':    'Thử đổi bộ lọc, hoặc bấm Làm mới để quét lại danh sách cài đặt.',
    'empty_history_title':'Chưa có lịch sử dọn',
    'empty_history_body': 'Chạy CHẠY THỬ hoặc DỌN NGAY trên tab Dọn rác — kết quả sẽ hiện ở đây.',
    'empty_rollback_title':'Chưa có mục đã xóa',
    'empty_rollback_body':'Các thao tác gỡ/xóa sẽ được ghi lại tại đây để bạn đối chiếu sau này.',
    'msg_restart':    'Vui lòng khởi động lại CyberClean để áp dụng ngôn ngữ mới.',
    'msg_restart_title': 'Cần Khởi Động Lại',
    'confirm_clean':  'Xác nhận dọn dẹp',
    'confirm_uninstall': 'Gỡ cài đặt',
    'setup_required': 'Cần thiết lập',
    'badge_safe':     'AN TOÀN',
    'badge_locked':   'ĐANG KHÓA',
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
    'upd_installing_optimizing': 'Đang cài đặt... có thể mất một chút thời gian, vui lòng không đóng ứng dụng',
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
    'log_psi_active': 'Giám sát PSI: đang hoạt động — tự tắt app nền khi áp lực RAM',
    'log_mem_compacted': 'Bộ nhớ đã được gom — chống phân mảnh xong',
    'log_cache_preserved': 'Giữ nguyên page cache — dữ liệu trình duyệt không bị xóa',
    'log_scan_bloat': 'Đang quét phần mềm nền...',
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
    # Gỡ ứng dụng
    'uninstall_found':   'Tìm thấy {n} ứng dụng — chọn một hoặc nhiều, rồi nhấn Gỡ cài đặt',
    'lbl_installer_open':'Cửa sổ gỡ đã mở — hoàn tất thao tác rồi nhấn LÀM MỚI',
    # Booster
    'lbl_smart_active':  'ĐANG BẬT',
    'boost_btn_idle':        'TĂNG TỐC',
    'boost_btn_active':      'ĐANG BẬT',
    'boost_hud_sub':         'Tối ưu tài nguyên hệ thống · tự động chụp trạng thái & khôi phục khi thoát',
    'boost_state_standby':   'CHỜ LỆNH',
    'boost_state_scanning':  'ĐANG QUÉT',
    'boost_state_monitoring':'ĐANG GIÁM SÁT',
    'boost_state_restoring': 'ĐANG KHÔI PHỤC',
    'boost_mc_gpu':          'TẢI GPU',
    'boost_mc_cpu_proxy':    'TẢI CPU',
    'boost_mc_ram':          'RAM GIẢI PHÓNG',
    'boost_mc_bg':           'TIẾN TRÌNH NỀN',
    'boost_mc_game':         'NHẬN DIỆN GAME',
    'boost_profile_lbl':     'MÔ-ĐUN TỐI ƯU:',
    'boost_mod_ram':         'Giải phóng && chống phân mảnh RAM',
    'boost_mod_gov':         'CPU hiệu năng cao',
    'boost_mod_prio':        'Ưu tiên tiến trình (Nice)',
    'boost_mod_swap':        'Giảm Swappiness',
    'boost_mod_hypr':        'Hyprland VFR / Scanout',
    'boost_phase_scan':      '1 · QUÉT',
    'boost_phase_apply':     '2 · ÁP DỤNG',
    'boost_phase_monitor':   '3 · GIÁM SÁT',
    'boost_log_placeholder': 'Nhấn TĂNG TỐC để quét GPU / RAM / tải nền…',
    'boost_log_ready':       '[ sẵn sàng — nhấn TĂNG TỐC để tối ưu ]',
    'boost_no_game':         'chưa có game',
    'autoclean_btn_off':     'Dọn tự động: TẮT',
    'autoclean_btn_on':      'Dọn tự động: BẬT (6h)',
    'autoclean_tip':         'Bật/tắt tự động dọn cache an toàn khi máy rảnh (mặc định: TẮT; không bao giờ đụng tới Thùng rác)',
    'filter_all':            'TẤT CẢ',
    'btn_theme_light':       'GIAO DIỆN SÁNG',
    'btn_theme_dark':        'CYBER TỐI',
    'theme_toggle_tip':      'Chuyển đổi giữa giao diện Cyber Tối và giao diện Sáng hài hòa',
    'lbl_holo_3d':           'LÕI Ổ ĐĨA 3D HOLO',
    'warn_trash':            'Xóa vĩnh viễn — KHÔNG chuyển đi đâu cả. Mặc định không chọn mục nào.',
    'trash_in_dir':          'Trong Thùng rác',
    'trash_perm_del':        'xóa vĩnh viễn — không thể khôi phục',
    'win_dism_reboot_warn':  '⚠ DISM xong — hãy KHỞI ĐỘNG LẠI Windows (Start → Restart) để hoàn tất giải phóng dung lượng',
},


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
