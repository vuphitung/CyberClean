import os
import time
from pathlib import Path

from core import engine as E
from core.engine import Guards

DAY = 86400


def age(path, days):
    t = time.time() - days * DAY
    if os.utime in os.supports_follow_symlinks:
        os.utime(path, (t, t), follow_symlinks=False)
    else:
        # Windows does not implement utime(follow_symlinks=False). Fixtures
        # only age ordinary files/directories, never a symlink target.
        if Path(path).is_symlink() or getattr(Path(path), 'is_junction', lambda: False)():
            raise ValueError('cannot age a link fixture on this platform')
        os.utime(path, (t, t))


def tree(base: Path, spec: dict, days=30):
    """spec: {'a/b.txt': 100, 'c/': None} → tạo file có kích thước, tuổi `days`."""
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    for rel, size in spec.items():
        p = base / rel
        if rel.endswith("/"):
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * (size or 0))
    for p in sorted(base.rglob("*"), key=lambda q: -len(q.parts)):
        if not p.is_symlink():
            age(p, days)
    age(base, days)
    return base


class FakeGuards(Guards):
    def __init__(self, procs=(), open_paths=(), udd=(), sandbox=()):
        super().__init__()
        self._snap = ({E._norm_name(p) for p in procs}, {E._norm_path(u) for u in udd}, set(sandbox))
        anc = set()
        for op in open_paths:
            q = op
            while q and q not in anc:
                anc.add(q)
                nq = os.path.dirname(q)
                if nq == q:
                    break
                q = nq
        self._open_anc = anc

    def psutil_available(self) -> bool:
        return True
