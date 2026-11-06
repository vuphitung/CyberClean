"""One-shot CPU temperature check using TemperatureHost."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.windows_temperature import TemperatureHost


def main():
    host = TemperatureHost(startup_timeout=12., sample_timeout=4.)
    host.start()
    deadline = time.monotonic() + 25.
    result = None
    try:
        while time.monotonic() < deadline:
            result = host.snapshot()
            if result['cpu'] is not None:
                break
            if result['reason_code'] in ('pawnio_missing', 'pawnio_reboot_required', 'cpu_access_denied'):
                break
            time.sleep(.1)
    finally:
        host.close()

    payload = dict(cpu_c=result['cpu'] if result else None,
                   source=result['source'] if result else None,
                   reason_code=result['reason_code'] if result else 'no_result',
                   requires_admin=result['requires_admin'] if result else None,
                   backend=result['backend'] if result else None,
                   diagnostics=result['diagnostics'] if result else {})
    out = Path(__file__).with_name('installed-sensor-host-probe.json')
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload['cpu_c'] is not None else 1


if __name__ == '__main__':
    raise SystemExit(main())
