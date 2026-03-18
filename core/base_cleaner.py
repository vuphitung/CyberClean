"""
CyberClean v2.0 — Base Cleaner
Abstract interface every OS cleaner implements.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import shutil, time

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
        total = 0
        try:
            for f in Path(path).rglob('*'):
                if f.is_file() and not f.is_symlink():
                    try: total += f.stat().st_size
                    except: pass
        except: pass
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
            except: pass
        return freed
