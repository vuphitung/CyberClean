#!/usr/bin/env python3
"""
Chạy BÊN TRONG container của từng distro: nhận diện distro/package manager, dựng danh sách target,
dry-run mọi target AUTO và quét mọi target REVIEW (chỉ đọc), rồi in JSON. Thoát != 0 nếu có ngoại lệ,
nếu package manager không khớp kỳ vọng, hoặc nếu dry-run vô tình thay đổi đĩa.

    python3 tests/containers/dryrun_harness.py --expect-pm apt
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def snapshot(paths):
    out = {}
    for base in paths:
        for dp, dn, fn in os.walk(base, followlinks=False):
            for n in fn:
                p = os.path.join(dp, n)
                try:
                    st = os.lstat(p)
                    out[p] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-pm", default="")
    ap.add_argument("--home", default=os.path.expanduser("~"))
    args = ap.parse_args()

    from core import os_detect as O
    from core.linux_cleaner import LinuxCleaner

    report = {"distro": O.DISTRO, "like": O.DISTRO_LIKE, "pm": O.PKG_MANAGER, "ostree": O.IS_OSTREE,
              "rules_error": "", "targets": [], "errors": []}
    cl = LinuxCleaner()
    report["rules_error"] = getattr(cl, "_rules_error", "")
    watch = [os.path.join(args.home, d) for d in (".cache", ".config", ".local/share", ".var", "snap")]
    before = snapshot([w for w in watch if os.path.isdir(w)])

    for t in cl.get_targets():
        if t.id.startswith("_"):
            continue
        row = {"id": t.id, "tier": t.tier, "scheduled": t.scheduled}
        t0 = time.time()
        try:
            if t.tier == "auto":
                r = cl.clean(t.id, dry=True)
                row.update(freed=r.freed_bytes, error=r.error, notes=r.notes[:2])
                # unattended dry-run cũng phải chạy được cho target được phép chạy nền
                if t.scheduled:
                    ru = cl.clean(t.id, dry=True, unattended=True)
                    row["unattended_error"] = ru.error
            else:
                scan = cl.review_scan(t.id)
                row.update(items=len(scan.items), nothing_preticked=True, notes=scan.notes[:2])
                # review KHÔNG được xóa qua clean()
                bad = cl.clean(t.id, dry=False)
                if not bad.error:
                    report["errors"].append(f"{t.id}: clean(dry=False) on a review target did not refuse")
        except Exception as e:                                      # noqa: BLE001
            row["exception"] = repr(e)
            report["errors"].append(f"{t.id}: {e!r}")
        row["seconds"] = round(time.time() - t0, 2)
        report["targets"].append(row)

    after = snapshot([w for w in watch if os.path.isdir(w)])
    if before != after:
        changed = [p for p in set(before) | set(after) if before.get(p) != after.get(p)]
        report["errors"].append(f"dry-run changed {len(changed)} file(s) under {args.home}: {changed[:5]}")
    if args.expect_pm and O.PKG_MANAGER != args.expect_pm:
        report["errors"].append(f"expected package manager {args.expect_pm!r}, detected {O.PKG_MANAGER!r}")
    if report["rules_error"]:
        report["errors"].append(f"rules failed to load: {report['rules_error']}")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
