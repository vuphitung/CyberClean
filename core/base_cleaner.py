"""
CyberClean v2.0 — Base Cleaner
Abstract interface every OS cleaner implements.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
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

    # ── Estimate cache (60s TTL) ──────────────────────────────
    # Dry-run scans hit the disk every call — expensive on Windows with large dirs.
    # Cache results for 60 seconds; invalidated immediately on a real clean().
    _estimate_cache: dict = {}   # {target_id: (timestamp, CleanResult)}
    _CACHE_TTL = 60              # seconds

    def _cache_get(self, target_id: str):
        """Return cached CleanResult if still fresh, else None."""
        entry = self._estimate_cache.get(target_id)
        if entry and (time.monotonic() - entry[0]) < self._CACHE_TTL:
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
