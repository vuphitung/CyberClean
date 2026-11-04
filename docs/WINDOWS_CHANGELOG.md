# Windows stabilization — change batches

Baseline: original archive Git marker 123cdacbb7d1d6ad77a93763082ef748f65878d3.
This ZIP lacks Git objects; a local baseline commit preserves its exact bytes.
Branch: fix/windows-stability. No upstream push was performed.

## Batch 1: startup diagnostics and test collection

Removed import-time UAC. Added Windows-only early rotating Python logging,
main/thread exception hooks, native faulthandler file, Qt messages, startup,
tray and shutdown stages, event-loop exit status. Explicit UAC calls retain the
current process when ShellExecuteW returns an error; shell acceptance does not
prove the elevated child started successfully.

Tests: tests/test_windows_startup.py — 4 passed on Linux using fake Windows APIs
and Python subprocesses. No Windows-native execution. Crash cause on the user's
machine remains undetermined until a diagnostic log captures it.

Windows test collection: guard POSIX resource imports and geteuid checks;
skip only the POSIX helper/install suite and resource-specific test as needed.
Original Linux baseline tests still run with their original semantics.

## Batch 2: Windows telemetry ownership

Windows get_snapshot now returns a detached cache immediately. A single service
owns CPU/RAM/per-interface network baselines; a second worker samples process
and disk inventory every 5 s. Linux get_snapshot and temperature paths retain
their original implementation. CPU total and per-core share one cpu_times
boundary (Windows user/system/idle; DPC/interrupt already included in user).
Process CPU uses process-time delta / elapsed monotonic time / logical CPUs
for every value; (PID, create_time) identifies its baseline. First samples,
counter resets, reconnects, disappearing adapters and stale snapshots do not
produce fabricated zero readings. Valid idle throughput displays 0 B/s.
ALL NICs includes virtual NICs and may count tunneled traffic twice; the tooltip
identifies individual interfaces. It is not a Wi-Fi-only measurement.

RAM tooltip distinguishes psutil used/available/total/percent and working-set
percentage. Windows swap_memory is commit charge, not disk pagefile occupancy.
Missing data clears temperature and suppresses the heuristic score.

Tests: startup + telemetry contracts: 8 passed, Linux/fake APIs only. No Windows
performance target or Task Manager/hardware match has been established.

## Batch 3: persistent temperature host and dependencies

One child loads pinned LHM v0.9.4 net472 + matching HidSharp from the official
release. SHA-256 manifest checked before loading and by the Windows build path.
The original root DLL is preserved for baseline compatibility; Windows host
uses vendor/lhm only. READY startup (12 s) is independent of the 4 s sample
watchdog. Cached samples expire after 3 s. Closed managers never reopen.
Only the dedicated native child can be terminated after cooperative STOP fails;
Qt threads and the main process are never terminated to hide shutdown errors.

The host enables CPU/GPU only and has no WMI/ACPI/PowerShell polling chain.
No CPU sensor means unavailable. Sensor identifiers/labels/kinds, age and errors
are available in the tooltip. Distance-to-TjMax is excluded. Unavailable readings
never inherit a GPU/ACPI temperature. Host retries use bounded exponential backoff.

Tests: 12 startup/telemetry/protocol tests passed. Host tests launch isolated fake
Python children, not CLR. Packaging references and bundled file hashes passed.
Native driver access, Computer.Open/Close and same-sensor HWiNFO comparison are
unverified. CPU/GPU updates still share the child loop; a stuck native GPU Update
can stall subsequent CPU updates until the watchdog recovers the child.

## Batch 4: dashboard layout

Windows dashboard uses a scroll viewport, stacks hero/header/table rows below
980 logical px of content width, and reflows statistics into 2/3/5 columns.
Sidebar compacts at 1200 px on Windows. Process cells are reused on Windows.
Fonts are preserved. Horizontal scrolling remains available as a fallback.
Linux layout rules are unchanged.

Tests: 5 Qt offscreen subprocess cases passed at 1024 and 1366 logical px,
scales 1/1.25/1.5/2. Content width equals viewport width with horizontal range 0;
cooperative shutdown returns code 0, without os._exit. These use fake snapshots
and Windows layout branches on Linux, not Windows-native DPI/font testing.
Other pages and physical 1366x768 at 200% require native review.

## Batch 5: Windows process-state rollback and honest Boost metrics

Capture identity, original priority, exact EcoQoS ControlMask/StateMask and
memory priority before mutation. Pending/applied/verified are distinct lists.
Failed read-back retains originals; failed restore retains pending entries.
PID reuse never changes the new process. Unknown legacy records are reported,
not restored to guessed defaults. Eco Mode skips changes whose original state
cannot be read. Free RAM no longer leaves untracked memory-priority changes.
Fixed ProcessMemoryPriority information-class value (0, not 1) and pointer-sized
OpenProcess bindings. Windows plan escalation is disabled; the current plan is
preserved, with Balanced recommended. Power restore verifies the exact GUID.
Timer requests check the return code and no longer promise smoother games.
RAM deltas retain their sign and are labeled observed system changes, not
memory released by Boost or the summed RSS of deprioritized processes.

Tests: 7 new fake-API rollback/plan cases + 14 existing booster tests: 21 passed.
Native EcoQoS/priority/GUID restoration remains unverified. The existing game
watcher priority callback still needs asynchronous/race-safe restructuring;
this batch does not claim it is fixed. Crash persistence for all standalone
Boost actions also remains to be completed.

## Batch 6: Windows cleanup reporting

Whole-operation free-space measurements deduplicate drive roots and retain
signed deltas per observed volume. Do not sum overlapping per-target deltas.
The report separates planned bytes, logical removed and observed free-space
change (all disk activity). Windows history uses that measurement and no longer
replaces it with a cached disk snapshot or defaults to Btrfs/ZFS explanations.
Skipped-item reasons are logged. Locked Chromium profiles identify the browser,
not 'User Data'. DNS flush removes zero files and is reported as an operation.
Preview/identity/deletion guards and Windows cleanup rules are unchanged.

Tests: new measurement/DNS/browser tests and existing Windows cleaner tests pass.
The Linux clean-worker warning test still fails exactly as in baseline; no Linux
cleanup logic was changed. The meter covers known planned and Windows system/user
volumes, not unknown locations discovered by external tools. Aliased/mounted
volumes need further native validation. No real user files were cleaned.

## Batch 7: independent temperature sampling and native validation tools

CPU and GPU each have one sampler inside the same persistent child; JSON output
is serialized and the parent merges group snapshots without erasing the other
group. Each sensor has its own monotonic age. Native global/driver locks may
still block sampling and are handled by freshness rules and the host watchdog.
Metadata is explicit on SystemSnapshot, and inaccessible process attributes are
excluded instead of triggering a Qt callback exception.

Added a Windows-only native subprocess smoke (runtime/refresh/minimize/restore/
close, no cleanup or Boost), an opt-in real CPU sensor test, and a read-only
app-plus-host CPU/RAM/threads/handles observer for same-machine before/after runs.
These native tests are skipped on Linux, never reported as native passes.
The three remaining direct POSIX UID/pwd tests are skipped only where unsupported.

Startup diagnostics now use per-process filenames to prevent rotation races
between GUI and host logs. Update/single-instance exits have explicit reasons.
Known hologram/orbit animation timers pause during Windows minimize and resume
only when visible. Operational/background timers keep their intended behavior.

Visual QA at 1024 px found a crowded header; optional OS metadata is now hidden
in compact Windows headers. Disk rings show a dash until real disk data arrives
and clear stale availability, rather than displaying initial 0% as a measurement.

Windowed-host packaging: restore inherited stdin/stdout/stderr pipe handles when
pythonw/PyInstaller sets sys.std* to None. The spec now validates dependency hashes
as well as build.py. These windowed Windows paths still require a native build test.

Rollback regression coverage confirms the existing cleanup registration also
runs when the first Windows write cannot be verified. This path now reports
pending verification instead of incorrectly saying no idle heavy process was found.

Legacy Windows Game/Eco buttons also keep saved state and show RESTORE PENDING
when a restore returns failure or no verified outcome; turning off no longer
unconditionally discards rollback. Linux callbacks retain their previous behavior.
