"""
CyberClean — Base Cleaner
Abstract interface every OS cleaner implements + the plan-based mixin shared by
Linux and Windows (rules → plan → guarded execute, see core/engine.py).

Three tiers (what the UI shows, and what may run unattended):

    auto     Always regenerable. Ticked by default. The ONLY tier the idle
             scheduler may run (and only targets flagged `scheduled`).
    review   Listed item-by-item for the user to tick. Never pre-ticked,
             never run in the background.
    advisor  Report only (see core/advisor.py) — the app never deletes these.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
import os, time

from . import engine as E

TIERS = ('auto', 'review', 'advisor')
NEVER_UNATTENDED_TARGETS = frozenset({'empty_trash', 'win_recycle', 'trash', 'recycle_bin'})


@dataclass
class CleanTarget:
    id:       str
    name:     str
    desc:     str
    safety:   str        # 'safe' | 'caution' | 'danger'  (badge colour)
    needs_root: bool = False
    enabled:  bool = True
    tier:     str = ''             # 'auto' | 'review' | 'advisor'; '' → derived from safety
    scheduled: Optional[bool] = None   # may the idle scheduler run it? (auto tier only)

    def __post_init__(self):
        if not self.tier:
            self.tier = 'auto' if self.safety == 'safe' else 'review'
        if self.tier not in TIERS:
            raise ValueError(f'bad tier {self.tier!r}')
        if self.scheduled is None:
            self.scheduled = self.tier == 'auto'
        if self.id in NEVER_UNATTENDED_TARGETS:
            self.tier = 'review'
            self.scheduled = False        # Trash / Recycle Bin NEVER run in auto or background
        if self.tier != 'auto':
            self.scheduled = False        # review / advisor NEVER run unattended


@dataclass
class CleanResult:
    target_id:   str
    freed_bytes: int = 0
    files_removed: int = 0
    error:       Optional[str] = None
    rollback:    List[dict] = field(default_factory=list)
    dry:         bool = True
    planned_bytes: int = 0                       # what the plan said (dry-run == plan)
    measured_bytes: Optional[int] = None         # real change in free disk space (shutil.disk_usage)
    notes:       List[str] = field(default_factory=list)      # warnings (app running, snapshots...)
    skipped:     List[Tuple[str, str]] = field(default_factory=list)   # (path, reason)
    blocked:     int = 0
    plan:        Optional["E.Plan"] = None       # kept on dry-runs so CLEAN executes exactly this plan

    @property
    def success(self): return self.error is None


@dataclass
class ReviewItem:
    """One row in the Review dialog."""
    id:      str
    label:   str
    size:    int = 0
    files:   int = 0
    newest:  float = 0.0
    detail:  str = ''
    risk:    str = 'low'          # low | medium | high
    blocked: str = ''             # non-empty → cannot be selected right now (reason)
    payload: dict = field(default_factory=dict)


@dataclass
class ReviewScan:
    target_id: str
    items:     List[ReviewItem] = field(default_factory=list)
    notes:     List[str] = field(default_factory=list)
    warning:   str = ''           # shown prominently (e.g. "deleted volumes cannot be recovered")
    permanent: bool = True        # False → items go to Trash / can be restored


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
    _approved_plans: dict = {}   # {target_id: E.Plan} — bound from preview/dry-run until executed or invalidated
    _CACHE_TTL = 60              # seconds — default
    PLAN_TTL   = 3600            # seconds — max age of a previewed plan before requiring re-preview

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
        plan = getattr(result, "plan", None)
        if plan is not None:
            self.bind_approved_plan(target_id, plan)

    def bind_approved_plan(self, target_id: str, plan: Optional["E.Plan"]) -> None:
        """Bind a previewed/dry-run Plan so CLEAN NOW executes only the approved plan."""
        if not hasattr(self, "_approved_plans") or self._approved_plans is BaseCleaner._approved_plans:
            self._approved_plans = dict(getattr(self, "_approved_plans", {}))
        if plan is not None:
            self._approved_plans[target_id] = plan

    def get_approved_plan(self, target_id: str) -> Tuple[Optional["E.Plan"], bool]:
        """
        Return (plan, is_expired).
        - If an approved plan exists and is within PLAN_TTL: (plan, False)
        - If an approved plan exists but is older than PLAN_TTL: (plan, True)
        - Otherwise falls back to fresh _estimate_cache if available, or (None, False).
        """
        plans = getattr(self, "_approved_plans", {})
        plan = plans.get(target_id)
        if plan is None:
            cached = self._cache_get(target_id)
            plan = getattr(cached, "plan", None) if cached is not None else None
        if plan is None:
            return None, False
        if (time.time() - getattr(plan, "created", 0)) > self.PLAN_TTL:
            return plan, True
        return plan, False

    def _cache_invalidate(self, target_id: str) -> None:
        """Call this after a real clean so next dry-run rescans fresh."""
        self._estimate_cache.pop(target_id, None)
        if hasattr(self, "_approved_plans") and isinstance(self._approved_plans, dict):
            self._approved_plans.pop(target_id, None)

    @abstractmethod
    def get_targets(self) -> List[CleanTarget]:
        """Return list of available clean targets for this OS."""
        ...

    @abstractmethod
    def estimate(self, target_id: str) -> int:
        """Return estimated bytes that would be freed. No changes made."""
        ...

    @abstractmethod
    def clean(self, target_id: str, dry: bool = True, *, unattended: bool = False,
              plan: Optional["E.Plan"] = None) -> CleanResult:
        """
        Execute clean for a target. If dry=True, no changes made and the result
        carries the PLAN. Passing that plan back (dry=False, plan=...) executes
        exactly what was previewed — every item is re-validated right before it
        is deleted, so anything that changed in between is skipped, never deleted.
        unattended=True → background run: stricter age policy, auto-tier only.
        """
        ...

    # ── Review tier (per-item selection) ─────────────────────
    def review_scan(self, target_id: str, progress_cb=None) -> ReviewScan:
        raise NotImplementedError(target_id)

    def review_clean(self, target_id: str, item_ids: List[str], dry: bool = False) -> CleanResult:
        raise NotImplementedError(target_id)

    def targets_by_tier(self, tier: str) -> List[CleanTarget]:
        return [t for t in self.get_targets() if t.tier == tier]

    def clean_many(self, target_ids: List[str], dry: bool = True,
                   progress_cb=None, unattended: bool = False) -> List[CleanResult]:
        results = []
        for i, tid in enumerate(target_ids):
            if progress_cb:
                pct = int((i / len(target_ids)) * 90)
                progress_cb(pct, tid)
            results.append(self.clean(tid, dry=dry, unattended=unattended))
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
            except FuturesTimeout:
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
        """Delete everything inside `path` (symlinks removed, never followed).
        Returns bytes ACTUALLY freed — measured per item, not assumed."""
        freed = 0
        try:
            children = list(os.scandir(path))
        except OSError:
            return 0
        for entry in children:
            try:
                before = E.tree_stats(entry.path).size
                E.remove_path(entry.path)
                left = E.tree_stats(entry.path).size if os.path.lexists(entry.path) else 0
                done = max(0, before - left)
                rollback_list.append({
                    'time':  time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'type':  label,
                    'path':  entry.path,
                    'size':  done,
                    'note':  'cache — auto-rebuilds',
                })
                freed += done
            except (OSError, PermissionError):
                pass
        return freed


# ══════════════════════════════════════════════════════════════
# Plan-based mixin (rules → plan → guarded execute)
# ══════════════════════════════════════════════════════════════

class PlanCleanerMixin:
    """
    Gives a cleaner rule-driven targets (rules/*.toml). A cleaner using this
    sets `self.ctx` (RuleContext) and `self.ruleset` (RuleSet); targets whose
    rules live in the TOML files then need no code at all.
    """
    ctx = None
    ruleset = None
    _review_cache: dict = {}          # {target_id: (monotonic time, Plan)}
    REVIEW_TTL = 600

    # ── plan building (override for code-driven providers) ──
    def build_plan(self, target_id: str, *, unattended: bool = False) -> "E.Plan":
        return self.ruleset.plan(target_id, self.ctx, unattended=unattended)

    def has_rules(self, target_id: str) -> bool:
        return bool(self.ruleset and self.ruleset.rules_for(target_id, self.ctx))

    def _ensure_review_cache_dict(self) -> dict:
        if not hasattr(self, '_review_cache') or self._review_cache is PlanCleanerMixin._review_cache:
            self._review_cache = dict(getattr(self, '_review_cache', {}))
        return self._review_cache

    def _get_fresh_review_cache(self, target_id: str):
        rc = self._ensure_review_cache_dict()
        cached = rc.get(target_id)
        if not cached:
            return None
        ts, payload = cached
        if (time.monotonic() - ts) >= self.REVIEW_TTL:
            rc.pop(target_id, None)
            return None
        return payload

    def _expired_review_result(self, target_id: str, dry: bool) -> CleanResult:
        r = CleanResult(target_id, dry=dry)
        try:
            from utils.i18n import _t as _tr
        except Exception:
            _tr = lambda k, d='': d
        r.error = _tr(
            'review_plan_expired',
            'Review scan expired or is missing — please click Rescan and review the items again before deleting.',
        )
        return r

    def _execute(self, items: List["E.PlanItem"], stop=None) -> "E.ExecResult":
        """Hook: cleaner con ghi đè để chạy thêm loại mục đặc biệt (vd. mục dùng helper root)."""
        return E.execute_plan(items, guards=E.Guards(max_age=0), stop=stop)

    # ── plan → CleanResult ──
    def result_from_plan(self, target_id: str, plan: "E.Plan", *, dry: bool, label: str = '', stop=None) -> CleanResult:
        r = CleanResult(target_id, dry=dry)
        items = plan.deletable
        r.notes = list(plan.notes)
        r.skipped = list(plan.skipped)
        r.blocked = len(plan.items) - len(items)
        r.planned_bytes = plan.total_bytes
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        if dry:
            r.freed_bytes = plan.total_bytes
            r.files_removed = plan.total_files
            r.plan = plan
            r.rollback = [self._rb(stamp, label or target_id, it, it.size, plan_only=True) for it in items]
            return r
        meter = E.FreeSpaceMeter([i.path for i in items])
        meter.begin()
        try:
            res = self._execute(items, stop=stop)
        except TypeError:
            res = self._execute(items)
        measured = meter.end()
        if measured is not None:
            res.measured = measured
        r.freed_bytes = res.freed
        r.files_removed = res.removed
        r.measured_bytes = res.measured
        r.notes += [n for n in res.notes if n not in r.notes]
        r.skipped += res.skipped
        if res.errors:
            r.error = '; '.join(res.errors[:3])
        by_item = {o.item.path: o for o in res.outcomes}
        r.rollback = [self._rb(stamp, label or target_id, it, by_item[it.path].freed)
                      for it in items if it.path in by_item and by_item[it.path].status in ('removed', 'partial')]
        return r

    @staticmethod
    def _rb(stamp: str, label: str, it: "E.PlanItem", size: int, plan_only: bool = False) -> dict:
        note = it.note or 'cache — auto-rebuilds'
        if it.kind == 'files':
            note = f'{it.files} files · {note}'
        return {'time': stamp, 'type': label, 'path': it.display, 'size': size, 'note': note}

    def clean_rule_target(self, target_id: str, dry: bool, unattended: bool,
                          plan: Optional["E.Plan"] = None, label: str = '', stop=None) -> CleanResult:
        if not dry and not unattended and plan is None and hasattr(self, "get_approved_plan"):
            bound_plan, expired = self.get_approved_plan(target_id)
            if expired:
                r = CleanResult(target_id, dry=False)
                r.error = "Previewed plan expired — please run DRY-RUN or PREVIEW FILES again before cleaning"
                return r
            if bound_plan is not None:
                plan = bound_plan
        if plan is not None:
            if (time.time() - getattr(plan, "created", 0)) > getattr(self, "PLAN_TTL", 3600):
                if not dry:
                    r = CleanResult(target_id, dry=False)
                    r.error = "Previewed plan expired — please run DRY-RUN or PREVIEW FILES again before cleaning"
                    return r
                plan = self.build_plan(target_id, unattended=unattended)
        else:
            plan = self.build_plan(target_id, unattended=unattended)
        res = self.result_from_plan(target_id, plan, dry=dry, label=label, stop=stop)
        if dry and res.plan is not None and hasattr(self, "bind_approved_plan"):
            self.bind_approved_plan(target_id, res.plan)
        if not dry:
            self._cache_invalidate(target_id)
            self._ensure_review_cache_dict().pop(target_id, None)
        return res

    # ── Review tier on top of plans ──
    def review_scan(self, target_id: str, progress_cb=None) -> ReviewScan:
        rc = self._ensure_review_cache_dict()
        plan = self.build_plan(target_id, unattended=False)
        rc[target_id] = (time.monotonic(), plan)
        scan = ReviewScan(target_id, notes=list(plan.notes))
        for it in sorted(plan.items, key=lambda i: -i.size):
            scan.items.append(ReviewItem(
                id=it.id, label=it.display, size=it.size, files=it.files, newest=it.newest,
                detail=it.note, risk=it.risk, blocked=it.blocked, payload={'path': it.path, 'rule': it.group}))
        return scan

    def review_clean(self, target_id: str, item_ids: List[str], dry: bool = False) -> CleanResult:
        if not item_ids:
            return CleanResult(target_id, dry=dry)
        plan = self._get_fresh_review_cache(target_id)
        if plan is None or not isinstance(plan, E.Plan):
            return self._expired_review_result(target_id, dry)
        wanted = set(item_ids)
        sel = E.Plan(target_id, [i for i in plan.items if i.id in wanted], list(plan.skipped), list(plan.notes))
        return self.result_from_plan(target_id, sel, dry=dry, label=target_id)
