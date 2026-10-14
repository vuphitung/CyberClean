# Changelog

## 3.1.0

Security hardening of the root helper and updater, a rewrite of the cleaning pipeline (plan → preview →
guarded execute), and the three-tier model **AUTO / REVIEW / ADVISOR**.

### ⚠ Release / migration checklist (read before tagging)

1. Build with `python3 build.py --linux` — the tarball now carries `cyber-clean-helper` and `VERSION` next to
   the executable (required by `install.sh` and by the helper's `update-apply`). Sign it with `sign_release.py`
   and upload the tarball **and** its `.sig`.
2. Publish the GitHub release **before** merging the new `install.sh` to `main`: it installs the *latest release*
   and refuses releases that do not ship the helper.
3. Existing 3.0.x users: the in-app update still works (the old updater uses the old helper once). After the
   first start of 3.1.0 a banner appears in the Clean tab — **UPDATE HELPER** (asks for the admin password via
   polkit) or simply re-run `install.sh`. Until then Linux root targets keep working through the old helper,
   but the in-app updater of 3.1.0 refuses to run through an outdated helper.
4. `tomli` is only needed when running from source on Python < 3.11.

### Verification of the 3.0.3 audit report

| # | Report item | Result |
|---|-------------|--------|
| 1 | Helper path traversal (`..`) | **Confirmed, fixed.** `case` patterns let `*` match `/` and `..`. Paths are now canonicalised, must be symlink-free, inside `/var/log` / `/var/crash` / coredump, under root-owned non-group/other-writable directories, regular files, not modified in the last hour. Tests: `tests/test_helper.py`. |
| 2 | `user_cache` (tier *safe*) deleted dev caches | **Confirmed, fixed.** Replaced by an allow-list (rules) + a REVIEW-tier `app_cache`; regression test `test_user_cache_regression_dev_caches_not_deleted_by_safe_tier`. |
| 3 | `tmp_files` missing guards | **Confirmed, fixed.** Age = newest file *inside* the item; sockets/FIFOs, other users' files, mounts, open files and well-known runtime dirs (`.X11-unix`, `tmux-*`, `ssh-*`, `.mount_*`…) are skipped; RAM-backed `/tmp` is skipped. |
| 4 | "paccache missing → no error" was wrong | **Confirmed, fixed.** The estimate said 0 B and a real clean said "Need root". It now reports `paccache not found — install pacman-contrib` in both modes. |
| 5 | `docker volume prune` | **Confirmed, fixed.** Volumes are individual REVIEW items (risk HIGH, never pre-ticked, never touched unless ticked). |
| 6 | `pacman-remove` option injection | **Tested with a fake pacman — injection is real** (`--hookdir=…` would run hooks as root; the orphan path also word-split `$pkgs`). Fixed: names must match `^[A-Za-z0-9][A-Za-z0-9+._:@-]{0,127}$`, one package per call, `--` before names, core packages refused, orphan list re-checked against `pacman -Qdtq`. |
| 7 | Auto-clean ran every "safe" target incl. Trash | **Confirmed, fixed.** `empty_trash` is REVIEW; the scheduler runs only `tier == auto and scheduled`, and `clean(..., unattended=True)` re-checks that. |
| 8 | No pacman lock guard | **Confirmed, fixed.** Helper refuses while `db.lck` exists / pacman runs; `aur_cache` is blocked while yay/paru/makepkg/pacman/fakeroot run. |
| 9 | Helper `stop-service "$2"` | **Removed** (it had no caller). |
| 10 | Uninstaller can remove core packages | **Confirmed, fixed.** Same protected list in the UI (🔒) and in the helper; a helper refusal no longer falls back to `sudo pacman -Rns`. |
| 11 | Confirm dialog does not say "permanent" | **Fixed.** Both dialogs say it; the Review dialog defaults to *Cancel* and names HIGH-risk items. |
| 12 | `one-click-fix` uses `drop_caches` | `one-click-fix` / `drop-cache` were dead helper code (no caller) — removed. |
| 13 | `booster.py` `sudo -n tee oom_score_adj` never runs | **Confirmed** (`<<<` is not in `/bin/sh`, sudoers allows only the helper). Branch removed on purpose. |
| 14 | Widget killer: 0.4 s of CPU sampling | **Fixed.** Current user's processes only, ignore < 8 s old, 0.3 s pre-check, then 4 consecutive samples above 85 % (~2 s), SIGTERM → wait → SIGKILL. |
| 15 | Unused `_disk_free_before`/`disk_after`; "freed" maybe not measured | **Confirmed.** History's `disk_after` always equalled `disk_before`, and totals were plan/estimate numbers. Now measured with `shutil.disk_usage`; History stores `planned_bytes` and `measured_bytes`; Btrfs/ZFS snapshot warning. |
| 16 | `sudo python3 main.py` → `Path.home()` may be `/root` | **Confirmed as a risk.** `real_home()` / `real_uid()` resolve `SUDO_*`/`PKEXEC_UID`; the hint to start the GUI with sudo was removed. |

### More defects found while fixing

**Security**
- `update-replace SRC DST BACKUP` gave every process of a sudo-group user an arbitrary *root copy / `rm -rf` / move* primitive (instant root). Replaced by `update-apply`: root-side Ed25519 re-verification on a private copy, symlink-escape check, mandatory newer `VERSION`, atomic swap with rollback. The old flow also had a TOCTOU between signature check and install (staging was user-writable).
- `install.sh`: fixed `/tmp/CyberClean.tar.gz` (symlink attack as root), no signature check, extracted over the previous install (stale files), wrote a sudoers rule *before* validating it, hard-coded fallback version `3.0.1`. Now: random root-owned work dir, Ed25519 verification, atomic swap, rule written via temp file + `visudo -c`, version pinned/validated.
- `apt-remove "$2"`/`dnf-remove "$2"` accepted option-looking names (`-o…`, `--setopt`).
- `snap-remove-rev` arguments were unvalidated.
- `ensure_privileged_session()` tested `sudo -n true` — impossible to pass with a helper-only sudoers rule (it would ask for a password even when everything was configured). Now uses a harmless `ping` action.
- Uninstaller fallback `sudo pacman -Rns …` bypassed the helper's protections on machines with broad sudo.

**Correctness**
- `journal`: the user-level `journalctl --vacuum` ran first and the privileged helper only on a non-zero exit. Whether an unprivileged vacuum exits non-zero depends on the systemd version (not verified here), so the root path was unreliable. It now always goes through the helper and the result is measured.
- `crash_reports`: bytes freed for root-owned dumps were always 0.
- `pacman_broken`: pacman ≥ 6 uses `download-*/` *directories* (counted as 4096 B, `find -delete` could not remove them).
- `docker` estimate added total + reclaimable; `flatpak` counted header lines and guessed sizes; `snap_old` estimated "25 % of /var/lib/snapd".
- `remove_dir_contents` counted symlink targets as freed and hid failures (`rmtree(ignore_errors=True)`); Go's read-only module cache could not be removed.
- `empty_trash`: `rglob` walked entire external drives; stale `directorysizes`.
- AUR cleanup deleted `vcs.json` (yay forgets `-git` package state).
- `paccache -rk1` → keeps 2 versions (downgrade path).
- `safe_delete()` reported success for a symlink it could not remove.
- Kill-process dialog never appeared and the button stayed disabled: `QTimer.singleShot` from a plain Python thread never fires — now a `QThread` signal.
- Booster `_run_helper` fell back to running a command literally named `swappiness` (not the helper action) when sudo/helper were unavailable and the app ran as root.
- Windows: one-click "Clear TEMP" ran `del /q /f /s %TEMP%\*` (no age/lock/junction guards); thumbcache reported delayed deletions as errors *and* as freed; `dosvc` was stopped and never restarted; Delivery Optimization removed its own root folder (service ACLs); Windows Update cache was cleaned while an update was installing.

### New

- **Three tiers, three pages.** The Clean tab keeps only the AUTO tier (ticked, may run unattended) plus a one-line pointer. The other two tiers got their own sidebar pages instead of being squeezed into Clean:
  - **DEEP CLEAN** (REVIEW tier): categories on the left, every item on the right, risk labels, high-risk warnings shown in full, nothing pre-ticked, "select all" skips high-risk rows, every delete asks first (default Cancel), results + measured free space shown inline, "scan all" for a total.
  - **DISK ADVISOR** (ADVISOR tier): read-only report with summary tiles, a share-of-disk bar, per-category cards, "open folder" and "copy report"; no delete button exists on the page (a test enforces it).
  - Also fixed on the way: Qt reads `#RRGGBBAA` as ARGB, so the app's `{color}40`-style borders/backgrounds were never translucent (they rendered pink or invisible) — the new pages use `rgba()`; labels inside rows no longer inherit the row's border; Vietnamese had two different buttons both called "XEM TRƯỚC" (DRY-RUN is now "CHẠY THỬ").
- **Engine** (`core/engine.py`): plan → preview → re-validated execute; guards for age, running app (process list, `SingletonLock`, `--user-data-dir`, Flatpak `bwrap`), open files, symlinks/junctions, mount points, sockets/FIFOs, owner, hard links; measured free space; Btrfs/ZFS snapshot warning. Missing `psutil` fails closed.
- **Declarative rules** (`rules/*.toml`, `~/.config/cyber-clean/rules.d/`): one Chromium/Electron rule (all profiles; `Cache`, `Code Cache`, `GPUCache`, `DawnCache`, `Service Worker/CacheStorage`… — never Cookies / Local Storage / IndexedDB), Firefox incl. Snap/Flatpak, Flatpak app caches, developer caches, thumbnails, pip, temp, AUR.
- **Distro coverage**: `ID_LIKE` detection, Fedora Atomic/Bazzite (`rpm-ostree`), NixOS, Alpine, `dnf autoremove`, Flatpak user + system. `tests/containers/` holds a per-distro dry-run harness.
- **Vietnamese** names/descriptions for every target and rule note.

### Known limits

- Windows-only code paths (DISM, services, `wevtutil`, MoveFileEx) were not executed on a real Windows host; the engine, tiers, rules and guards are unit-tested on Linux.
- `tests/containers/run_matrix.sh` (docker/podman wrapper) was not executed where this release was prepared; the harness it runs is covered by `tests/test_containers_harness.py`.
- pacman, dnf, zypper, xbps, apk, snap, flatpak and docker were exercised against fakes (recorded argv / canned output), never against the real tools.
- The GUI was rendered and exercised with Qt's offscreen platform, not on a real desktop session.
