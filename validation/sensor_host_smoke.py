"""Start the packaged or source temperature host over stdio pipes; verify READY, sample, and STOP."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    exe = Path(os.environ.get('CYBERCLEAN_EXE', ROOT / 'dist' / 'CyberClean' / 'CyberClean.exe'))
    cmd = [str(exe), '--windows-temp-host'] if exe.is_file() else [
        sys.executable, str(ROOT / 'main.py'), '--windows-temp-host'
    ]
    proc = None
    result = {'command': cmd, 'ready': False, 'cpu_sample': False, 'backend': None, 'exit_code': None}
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        deadline = time.monotonic() + 25.
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError('temperature host closed before READY')
            message = json.loads(line)
            if message.get('type') == 'READY':
                result['ready'] = True
                result['backend'] = message.get('backend')
                result['diagnostics'] = message.get('diagnostics')
            elif message.get('type') == 'sample' and message.get('group') == 'cpu':
                result['cpu_sample_received'] = True
                result['cpu_sample'] = bool(message.get('readings'))
                if result['cpu_sample']:
                    result['readings'] = message['readings']
                break
            elif message.get('type') == 'error':
                raise RuntimeError(message.get('reason'))
        else:
            raise TimeoutError('no CPU sample heartbeat from temperature host')
        proc.stdin.write('STOP\n')
        proc.stdin.flush()
        result['exit_code'] = proc.wait(timeout=8.)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5.)
            result['exit_code'] = proc.returncode
    out = ROOT / 'validation' / 'sensor-host-smoke.json'
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['ready'] and result.get('cpu_sample_received') else 1


if __name__ == '__main__':
    raise SystemExit(main())
