"""
CyberClean v2.0 — Base Cleaner
Abstract interface every OS cleaner implements.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, shutil, time

@dataclass
class CleanTarget:
    id:       str
    name:     str
    desc:     str
    safety:   str        # 'safe' | 'caution' | 'danger'
    needs_root: bool = False
    enabled:  bool = True

@dataclass
class CleanResult:
    target_id:   str
    freed_bytes: int = 0
    files_removed: int = 0
    error:       Optional[str] = None
    rollback:    List[dict] = field(default_factory=list)

    @property
    def success(self): return self.error is None

class BaseCleaner(ABC):
    """Every OS-specific cleaner inherits this."""

    # ── Estimate cache (per-target TTL) ────────────────────────
    # Dry-run scans hit the disk (or spawn external tools like PowerShell/DISM)
    # every call — expensive, especially on Windows. Cache results; invalidated
    # immediately on a real clean(). Default TTL is 60s, but some targets are
    # far more expensive to (re)scan than a plain temp-dir walk (e.g. DISM
    # component-store analysis can take 10-40s on its own) and barely change
    # minute to minute, so they get a longer TTL via TTL_OVERRIDES.
    _estimate_cache: dict = {}   # {target_id: (timestamp, CleanResult)}
    _CACHE_TTL = 60              # seconds — default

    # Subclasses may override this to give specific targets a longer TTL.
    # e.g. {'win_winsxs': 900}  (15 min — DISM analyze is expensive & stable)
    TTL_OVERRIDES: dict = {}

    def _ttl_for(self, target_id: str) -> int:
        return self.TTL_OVERRIDES.get(target_id, self._CACHE_TTL)

    def _cache_get(self, target_id: str):
        """Return cached CleanResult if still fresh, else None."""
        entry = self._estimate_cache.get(target_id)
        if entry and (time.monotonic() - entry[0]) < self._ttl_for(target_id):
            return entry[1]
        return None

    def _cache_set(self, target_id: str, result) -> None:
        self._estimate_cache[target_id] = (time.monotonic(), result)

    def _cache_invalidate(self, target_id: str) -> None:
        """Call this after a real clean so next dry-run rescans fresh."""
        self._estimate_cache.pop(target_id, None)

    @abstractmethod
    def get_targets(self) -> List[CleanTarget]:
        """Return list of available clean targets for this OS."""
        ...

    @abstractmethod
    def estimate(self, target_id: str) -> int:
        """Return estimated bytes that would be freed. No changes made."""
        ...

    @abstractmethod
    def clean(self, target_id: str, dry: bool = True) -> CleanResult:
        """Execute clean for a target. If dry=True, no changes made."""
        ...

    def clean_many(self, target_ids: List[str], dry: bool = True,
                   progress_cb=None) -> List[CleanResult]:
        results = []
        for i, tid in enumerate(target_ids):
            if progress_cb:
                pct = int((i / len(target_ids)) * 90)
                progress_cb(pct, tid)
            results.append(self.clean(tid, dry=dry))
        if progress_cb:
            progress_cb(100, 'done')
        return results

    # ── Parallel dry-run scan ───────────────────────────────
    # NOTE: this used to be called from ui_widgets.py via
    # `hasattr(CLEANER, 'estimate_parallel')` but was never actually
    # implemented anywhere, so the "fast path" silently never ran and every
    # scan fell through to the fully serial path — the #1 cause of slow
    # scans, especially on Windows where several targets (Recycle Bin via
    # PowerShell/COM, WinSxS via DISM, per-profile browser caches) are each
    # individually slow and used to stack up one after another instead of
    # overlapping.
    #
    # Each target is scanned (clean(dry=True)) on its own worker thread.
    # This is safe because every dry-run path in both cleaners is read-only
    # (no filesystem mutation, no shared state besides the cache dict, which
    # is fine to write from multiple threads since each key is only ever
    # touched by the worker scanning that specific target). A slow/hung
    # target (e.g. DISM) gets its own timeout and can never block the others.
    def estimate_parallel(self, target_ids: List[str],
                           max_workers: int = 6,
                           per_target_timeout: int = 90,
                           progress_cb=None) -> "dict[str, CleanResult]":
        """
        Run clean(tid, dry=True) for every target concurrently.
        Returns {target_id: CleanResult}. Populates the estimate cache as it
        goes, so a subsequent _cache_get(tid) call is instant.
        Never raises — a failed/timed-out target just gets a CleanResult
        with .error set, exactly like the serial path would produce.
        """
        results: "dict[str, CleanResult]" = {}
        if not target_ids:
            return results

        def _scan_one(tid: str) -> CleanResult:
            cached = self._cache_get(tid)
            if cached is not None:
                return cached
            res = self.clean(tid, dry=True)
            self._cache_set(tid, res)
            return res

        # NOTE on timeouts: individual slow operations (DISM, PowerShell/COM
        # calls, etc.) already carry their own subprocess-level timeout
        # inside each cleaner's run/run_win() helper — that's the real
        # per-target guard, since Python threads can't be force-killed from
        # outside. `per_target_timeout` here is a batch-level safety net so
        # one misbehaving target (e.g. a subprocess timeout that's set too
        # high) can't stall progress reporting for everything else forever;
        # unfinished targets are reported with an error and the caller can
        # still use whatever finished.
        done_count = 0
        workers = max(1, min(max_workers, len(target_ids)))
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {pool.submit(_scan_one, tid): tid for tid in target_ids}
            pending = set(futures)
            try:
                for fut in as_completed(futures, timeout=per_target_timeout * max(1, len(target_ids) // workers + 1)):
                    tid = futures[fut]
                    pending.discard(fut)
                    try:
                        results[tid] = fut.result()
                    except Exception as e:
                        r = CleanResult(target_id=tid)
                        r.error = f'Scan failed: {e}'
                        results[tid] = r
                    done_count += 1
                    if progress_cb:
                        pct = int((done_count / len(target_ids)) * 90)
                        progress_cb(pct, tid)
            except TimeoutError:
                # Whole batch took too long — mark whatever hasn't finished
                # yet as timed out and move on; those threads keep running
                # in the background and will populate the cache whenever
                # they eventually finish, which just means the *next* scan
                # will be instant for them.
                for fut in pending:
                    tid = futures[fut]
                    r = CleanResult(target_id=tid)
                    r.error = f'Timeout after {per_target_timeout}s — skipped this round'
                    results[tid] = r
        finally:
            # don't block the UI thread waiting for stragglers to exit;
            # they'll finish on their own and populate the cache.
            pool.shutdown(wait=False)
        if progress_cb:
            progress_cb(100, 'done')
        return results

    # ── Shared helpers ─────────────────────────────────────
    @staticmethod
    def dir_size(path) -> int:
        """
        Fast recursive directory size using os.scandir() (C-level API).
        ~5-10x faster than pathlib.rglob() — no Path object allocation per entry,
        stat() metadata cached by the OS during the scandir pass.
        """
        total = 0
        stack = [str(path)]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                            elif entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                        except OSError:
                            pass
            except OSError:
                pass
        return total

    @staticmethod
    def remove_dir_contents(path: Path, rollback_list: list, label: str):
        freed = 0
        for item in path.iterdir():
            try:
                sz = BaseCleaner.dir_size(item) if item.is_dir() else item.stat().st_size
                rollback_list.append({
                    'time':  time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'type':  label,
                    'path':  str(item),
                    'size':  sz,
                    'note':  'cache — auto-rebuilds',
                })
                if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                else:             item.unlink(missing_ok=True)
                freed += sz
            except (OSError, PermissionError):
                pass
        return freed
