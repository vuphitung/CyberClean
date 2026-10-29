# CyberClean

**A Python/PyQt6 desktop utility for viewing system metrics, reviewing cleanup candidates, and running selected maintenance actions on Windows and Linux.**

[English](README.md) · [Tiếng Việt](README_vi.md)

> **Status:** source is still under verification. It was run on one Windows 10 machine; this Windows-updated source has **not yet been retested on Linux**. The full test suite is not green, so this is not a claim of stability across all systems.

## What it does

- **Dashboard:** CPU, RAM, commit memory, network traffic, per-volume space, and processes. The *load/health index* is a heuristic based on sampled metrics; it is not CPU usage percent, SMART data, or a disk-health diagnosis.
- **Cleanup:** targets are grouped as `AUTO` (regenerable caches), `REVIEW` (items that need explicit selection/confirmation), and `ADVISOR` (report only). The engine plans, previews, and rechecks conditions before deletion. Cache deletion is permanent; there is no recovery guarantee.
- **Disk Advisor:** reports large folders and files without deleting them.
- **Booster:** exposes selected Windows/Linux actions such as working-set trimming, process-priority changes, and game mode. Results depend on the machine, permissions, and workload; the project has not established an FPS or general speedup guarantee.
- **Uninstaller, history, and tray:** reads installed-app entries from the Windows Registry or Linux package managers and keeps local history. Scheduled cleanup runs only while the app is open/in the tray; there is no always-running Windows service.
- **Updater:** checks GitHub Releases. There is no analytics/telemetry; version checks still make a network request to GitHub.

## Technology

- Python 3.10+, PyQt6 UI, and QThread workers.
- `psutil` plus operating-system APIs for telemetry. Windows code also calls Win32 through `ctypes` for CPU time, RAM, commit, volume space, and process data. Linux paths use distro APIs and utilities.
- TOML cleanup rules live in `rules/`. Most cleanup flows share `core/` logic; OS-specific actions live in the corresponding cleaner.
- Windows CPU temperature is an optional path using LibreHardwareMonitor for .NET (`LibreHardwareMonitorLib.dll`), `pythonnet`, and the PawnIO sensor backend through a separate read-only helper. Sensor availability depends on firmware and driver permissions. **On the Windows review machine, the app still showed `N/A`; the integrated helper did not return a sample end to end.** A source run of `main.py` does not have the installed helper needed to request hardware access. Temperature support is therefore not confirmed for every machine.

## Compatibility and evidence

| Environment | Checked | Not established |
|---|---|---|
| Windows 10 build 19044, Python 3.12.10, Intel i7-6600U | Source GUI and onedir app launch; CPU/RAM/commit/C: and D: compared with Windows APIs in sampled runs; all 8 pages, refresh, minimize/restore exercised | Every Windows version, driver, DPI setting, ARM64; in-app CPU temperature; FPS improvement |
| Linux | Code paths exist for multiple package managers and distributions; an earlier source snapshot had Linux test runs | The source after Windows changes has not been downloaded and retested on Linux; do that before release |

In one 90-second GUI sample on that Windows machine, CyberClean plus the sensor helper averaged **3.09% of total machine CPU** (2.73% while the dashboard was idle after second 45), aggregate process working set peaked at **197.48 MiB**, and event-loop p95 was **25 ms**. This is one machine and one short sample, not a resource-use target or comparative benchmark.

The [Windows native report](docs/WINDOWS_NATIVE_REPORT_VI.md) records **113 passed, 1 skipped, 0 failed** in the Windows-specific group and **373 passed, 49 failed, 180 skipped** across the full suite in that run. The 49 failures were classified as POSIX/Linux fixture or permission assumptions; that **does not make the full suite green**. These are report results, not a rerun after every later edit.

## Run from source

On Linux or in Windows PowerShell:

```bash
git clone https://github.com/vuphitung/CyberClean.git
cd CyberClean
python -m venv .venv
```

Activate the virtual environment:

```bash
# Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install runtime dependencies and launch:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -X utf8 main.py
```

Python 3.10 gets `tomli` through the requirements marker; on Windows, pip installs `pythonnet` through its platform marker. Administrator/root is not needed just to view the dashboard. Some maintenance actions need separate permissions or will report that permission is unavailable.

### Development checks

`requirements-dev.txt` includes runtime requirements plus pytest and pyflakes:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m pyflakes main.py ui_widgets.py ui_pages.py core utils
```

On Windows, focused sensor/native checks can be run with:

```powershell
python -m pytest -q tests/test_windows_native.py tests/test_windows_temperature.py tests/test_windows_sensor_access.py tests/test_engine_windows_native.py
```

For a manual smoke check, launch from source, compare CPU/RAM/disk with Task Manager or another system tool, refresh a few times, and review a cleanup plan. Use a dedicated test directory if you need to exercise deletion; do not use personal files as a quick test. Metrics can differ slightly because sampling times and background workload differ.

**Before releasing on Linux:** clone the source branch, install `requirements-dev.txt`, run the full suite, launch the GUI, and inspect preview/dry-run results on the target distribution. Windows results do not replace this step.

## Build

PyInstaller is a separate build dependency:

```bash
python -m pip install pyinstaller

# Linux tar.gz
python build.py --linux

# Windows onedir folder under dist/CyberClean
python build.py --windows

# Build onedir and generate an Inno Setup script; open it in Inno Setup Compiler to compile the installer
python build.py --inno
```

`--windows` creates an application directory, not a single standalone EXE. `--inno` also generates an installer script; Inno Setup Compiler is required to produce the installer. Do not publish binaries/installers before Linux testing and a final version/signature check.

## Source layout

```text
CyberClean/                    # normal repository root; main.py is here
├── main.py                    # startup and UI coordination
├── ui_widgets.py, ui_pages.py
├── core/                      # cleaner, engine, booster, advisor
├── utils/                     # telemetry, translations, updater, Windows helpers
├── rules/                     # per-OS TOML cleanup rules
├── tests/                     # pytest
├── packaging/                 # scoped Linux privilege helper
├── vendor/lhm/                # Windows sensor library and hash manifest
├── build.py                   # PyInstaller packaging
└── install.sh                 # Linux installer
```

The `CyberClean-Windows-Review/` handoff folder is an outer review wrapper containing a Git bundle, patches, checksums, and reports. Its inner `CyberClean/` folder is the source. The wrapper is not part of the release repository. A normal GitHub clone has files such as `main.py` directly at the checkout root.

## Limits and safety

- `AUTO` permanently deletes caches. `REVIEW` can include user data; inspect each item before confirming.
- Log/WinSxS estimates and recovered-byte counts can vary by volume, permissions, snapshots, and mount points.
- Booster actions change system state. Use the specific feature you understand; no speedup is guaranteed.
- CPU temperature remains unconfirmed end to end in the tested app; `N/A` is the accurate status when no sample is available.
- See the [Windows report and remaining limitations](docs/WINDOWS_NATIVE_REPORT_VI.md).

## License

MIT — see [LICENSE](LICENSE).
