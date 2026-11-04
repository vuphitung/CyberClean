"""Start the frozen sensor host as the current user; authenticate, sample, STOP."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.windows_sensor_access import _authenticate_server


def main():
    helper = Path(os.environ.get(
        'CYBERCLEAN_SENSOR_HELPER',
        ROOT / 'dist' / 'CyberClean' / 'sensor-host' / 'CyberCleanSensorHost.exe'))
    if not helper.is_file():
        raise FileNotFoundError(helper)
    token = secrets.token_bytes(32)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    server.settimeout(35.)
    proc = None
    connection = None
    result = {'helper': str(helper), 'authenticated': False, 'ready': False,
              'cpu_sample': False, 'backend': None, 'exit_code': None}
    try:
        proc = subprocess.Popen(
            [str(helper), '--windows-temp-host', '--sensor-port',
             str(server.getsockname()[1]), '--sensor-token', token.hex()],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        connection, peer = server.accept()
        if peer[0] != '127.0.0.1':
            raise PermissionError('non-loopback peer')
        connection.settimeout(5.)
        _authenticate_server(connection, token)
        result['authenticated'] = True
        connection.settimeout(20.)
        stream = connection.makefile('r', encoding='utf-8', newline='\n')
        deadline = time.monotonic() + 25.
        while time.monotonic() < deadline:
            line = stream.readline(65537)
            if not line:
                raise RuntimeError('helper closed before READY')
            message = json.loads(line)
            if message.get('type') == 'READY':
                result['ready'] = True
                result['backend'] = message.get('backend')
                result['diagnostics'] = message.get('diagnostics')
            elif message.get('type') == 'sample':
                if message.get('group') == 'cpu':
                    result['cpu_sample_received'] = True
                    result['cpu_sample'] = bool(message.get('readings'))
                    if result['cpu_sample']:
                        result['readings'] = message['readings']
                    break
            elif message.get('type') == 'error':
                raise RuntimeError(message.get('reason'))
        else:
            raise TimeoutError('no CPU sample heartbeat from frozen helper')
        connection.sendall(b'STOP\n')
        result['exit_code'] = proc.wait(timeout=8.)
        if result['exit_code'] != 0:
            raise RuntimeError(f'helper exit code {result["exit_code"]}')
    finally:
        if connection is not None:
            connection.close()
        server.close()
        if proc is not None and proc.poll() is None:
            proc.wait(timeout=10.)
            result['exit_code'] = proc.returncode
    out = ROOT / 'validation' / 'sensor-host-smoke.json'
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result['authenticated'] or not result['ready'] or not result.get('cpu_sample_received'):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
