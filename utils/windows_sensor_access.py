"""Narrow IPC for the protected, read-only Windows temperature helper.

Only the installed helper under Program Files may be elevated. The user-writable
Python GUI cannot ask an elevated process to run commands; it can receive bounded
sensor JSON and send the single command STOP.
"""
import ctypes
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time

PROTOCOL = 'CyberCleanSensor/1'
MAX_LINE = 65536


def installed_sensor_helper():
    """Return only the installer-protected helper location; never elevate source files."""
    if sys.platform != 'win32':
        return None
    program_files = os.environ.get('ProgramFiles')
    if not program_files:
        return None
    path = Path(program_files) / 'CyberClean' / 'sensor-host' / 'CyberCleanSensorHost.exe'
    try:
        resolved = path.resolve(strict=True)
        if resolved != path.absolute() or not resolved.is_file():
            return None
        return resolved
    except OSError:
        return None


def _mac(key, role, server_nonce, client_nonce):
    data = (role + '|' + server_nonce + '|' + client_nonce).encode('ascii')
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _send_handshake(sock, message):
    sock.sendall(json.dumps(message, separators=(',', ':')).encode('ascii') + b'\n')


def _read_handshake(sock):
    data = bytearray()
    while len(data) <= 1024:
        part = sock.recv(1)
        if not part:
            raise EOFError('Sensor helper closed during authentication')
        if part == b'\n':
            message = json.loads(data.decode('ascii'))
            if not isinstance(message, dict):
                raise ValueError('Invalid sensor handshake')
            return message
        data.extend(part)
    raise ValueError('Sensor handshake frame too large')


def _authenticate_server(sock, token):
    server_nonce = secrets.token_hex(32)
    _send_handshake(sock, dict(protocol=PROTOCOL, nonce=server_nonce))
    response = _read_handshake(sock)
    client_nonce = response.get('nonce', '')
    if len(client_nonce) != 64 or any(c not in '0123456789abcdef' for c in client_nonce):
        raise ValueError('Invalid helper nonce')
    expected = _mac(token, 'client', server_nonce, client_nonce)
    if not hmac.compare_digest(str(response.get('proof', '')), expected):
        raise PermissionError('Sensor helper authentication failed')
    _send_handshake(sock, dict(proof=_mac(token, 'server', server_nonce, client_nonce)))


def _authenticate_client(sock, token):
    challenge = _read_handshake(sock)
    server_nonce = challenge.get('nonce', '')
    if (challenge.get('protocol') != PROTOCOL or len(server_nonce) != 64 or
            any(c not in '0123456789abcdef' for c in server_nonce)):
        raise ValueError('Invalid sensor server challenge')
    client_nonce = secrets.token_hex(32)
    _send_handshake(sock, dict(nonce=client_nonce,
                               proof=_mac(token, 'client', server_nonce, client_nonce)))
    reply = _read_handshake(sock)
    expected = _mac(token, 'server', server_nonce, client_nonce)
    if not hmac.compare_digest(str(reply.get('proof', '')), expected):
        raise PermissionError('Sensor server authentication failed')


class _WindowsProcess:
    def __init__(self, handle):
        from ctypes import wintypes
        self.handle = handle
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetExitCodeProcess.restype = wintypes.BOOL
        self.kernel.GetProcessId.argtypes = [wintypes.HANDLE]
        self.kernel.GetProcessId.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.pid = int(self.kernel.GetProcessId(handle))

    def poll(self):
        from ctypes import wintypes
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return None if code.value == 259 else int(code.value)

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            code = self.poll()
            if code is not None:
                return code
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('CyberCleanSensorHost', timeout)
            time.sleep(.05)

    def close_handle(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        try:
            self.close_handle()
        except Exception:
            pass


def _shell_execute(command):
    """Run the fixed Program Files helper with runas; never elevate Python or a .py path."""
    from ctypes import wintypes

    class ExecuteInfo(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
            ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR),
            ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR),
            ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
            ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR),
            ('hkeyClass', wintypes.HKEY), ('dwHotKey', wintypes.DWORD),
            ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE),
        ]

    request = ExecuteInfo()
    request.cbSize = ctypes.sizeof(request)
    request.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS; keep normal Windows error reporting
    request.lpVerb = 'runas'
    request.lpFile = command[0]
    request.lpParameters = subprocess.list2cmdline(command[1:])
    request.lpDirectory = str(Path(command[0]).parent)
    request.nShow = 1  # SW_SHOWNORMAL; the helper itself is built without a console window
    shell = ctypes.WinDLL('shell32', use_last_error=True).ShellExecuteExW
    shell.argtypes = [ctypes.POINTER(ExecuteInfo)]
    shell.restype = wintypes.BOOL
    if not shell(ctypes.byref(request)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not request.hProcess:
        raise OSError('Windows returned no sensor helper process handle')
    return _WindowsProcess(request.hProcess)


class _Channel:
    def __init__(self, sock):
        self.socket = sock
        self.closed = False
        self.lock = threading.Lock()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.socket.close()
            except OSError:
                pass


class _SensorReader:
    def __init__(self, channel):
        self.channel = channel
        self.stream = channel.socket.makefile('r', encoding='utf-8', newline='\n')
        self.ended = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.ended:
            raise StopIteration
        line = self.stream.readline(MAX_LINE + 1)
        if not line:
            self.ended = True
            raise StopIteration
        if len(line.encode('utf-8')) > MAX_LINE or not line.endswith('\n'):
            self.close()
            raise ValueError('Sensor helper output frame too large')
        message = json.loads(line)
        if not isinstance(message, dict) or message.get('type') not in ('READY', 'sample', 'error'):
            self.close()
            raise ValueError('Invalid sensor helper message')
        return line

    def close(self):
        if not self.ended:
            self.ended = True
        try:
            self.stream.close()
        finally:
            self.channel.close()


class _StopWriter:
    def __init__(self, channel):
        self.channel = channel

    def write(self, text):
        if text != 'STOP\n':
            raise ValueError('Only STOP is accepted by the elevated sensor helper')
        self.channel.socket.sendall(b'STOP\n')
        return len(text)

    def flush(self):
        pass

    def close(self):
        self.channel.close()


class SensorProcess:
    def __init__(self, process, sock):
        self.process = process
        self.pid = process.pid
        self.channel = _Channel(sock)
        self.stdin = _StopWriter(self.channel)
        self.stdout = _SensorReader(self.channel)

    def poll(self):
        return self.process.poll()

    def wait(self, timeout=None):
        return self.process.wait(timeout)

    def terminate(self):
        # Disconnect only. The helper exits itself; the normal GUI never kills an elevated process.
        self.channel.close()

    kill = terminate


def start_elevated_sensor_host(*, launch=None, connect_timeout=30.):
    helper = installed_sensor_helper()
    if helper is None:
        raise FileNotFoundError('Protected CyberClean sensor helper is not installed')

    token = secrets.token_bytes(32)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    process = None
    try:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        command = [str(helper), '--windows-temp-host', '--sensor-port', str(port),
                   '--sensor-token', token.hex()]
        process = (launch or _shell_execute)(command)
        listener.settimeout(connect_timeout)
        connection, peer = listener.accept()
        if peer[0] != '127.0.0.1':
            connection.close()
            raise PermissionError('Sensor connection was not from loopback')
        connection.settimeout(5.)
        _authenticate_server(connection, token)
        connection.settimeout(None)
        return SensorProcess(process, connection)
    finally:
        listener.close()


class _HelperInput:
    def __init__(self, stream, watchdog):
        self.stream = stream
        self.watchdog = watchdog
        self.ended = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.ended:
            raise StopIteration
        data = bytearray()
        try:
            while len(data) <= 32:
                part = self.stream.read(1)
                if not part:
                    self.ended = True
                    self.watchdog()
                    raise StopIteration
                if part == '\n':
                    self.ended = True
                    self.watchdog()
                    if bytes(data).rstrip(b'\r') != b'STOP':
                        return 'STOP\n'
                    return 'STOP\n'
                data.extend(part.encode('ascii'))
        except (OSError, UnicodeError, ValueError):
            self.ended = True
            self.watchdog()
            return 'STOP\n'
        self.ended = True
        self.watchdog()
        return 'STOP\n'


class _HelperOutput:
    def __init__(self, channel):
        self.channel = channel
        self.pending = ''

    def write(self, text):
        self.pending += text
        if len(self.pending.encode('utf-8')) > MAX_LINE:
            self.channel.close()
            raise ValueError('Sensor helper output frame too large')
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            message = json.loads(line)
            if not isinstance(message, dict) or message.get('type') not in ('READY', 'sample', 'error'):
                self.channel.close()
                raise ValueError('Invalid sensor helper output')
            self.channel.socket.sendall(line.encode('utf-8') + b'\n')
        return len(text)

    def flush(self):
        pass

    def close(self):
        self.channel.close()


def attach_sensor_stdio(arguments=None):
    """Helper entry point; authenticate before the CLR opens any hardware."""
    args = list(sys.argv[1:] if arguments is None else arguments)
    present = '--sensor-port' in args or '--sensor-token' in args
    if not present:
        return False
    if args.count('--sensor-port') != 1 or args.count('--sensor-token') != 1:
        raise ValueError('Invalid sensor helper arguments')
    allowed = {'--windows-temp-host', '--sensor-port', '--sensor-token'}
    if any(item.startswith('--') and item not in allowed for item in args):
        raise ValueError('Unexpected sensor helper argument')
    try:
        port_index = args.index('--sensor-port')
        token_index = args.index('--sensor-token')
        port = int(args[port_index + 1])
        token_text = args[token_index + 1]
        if not 1 <= port <= 65535 or len(token_text) != 64:
            raise ValueError('Invalid sensor endpoint')
        token = bytes.fromhex(token_text)
    except (ValueError, IndexError) as exc:
        raise ValueError('Invalid sensor endpoint/token') from exc

    connection = socket.create_connection(('127.0.0.1', port), timeout=5.)
    try:
        _authenticate_client(connection, token)
        connection.settimeout(None)
    except BaseException:
        connection.close()
        raise

    channel = _Channel(connection)
    watchdog_armed = threading.Event()
    def watchdog():
        if watchdog_armed.is_set():
            return
        watchdog_armed.set()
        timer = threading.Timer(8., lambda: os._exit(0))
        timer.daemon = True
        timer.start()

    sys.stdin = _HelperInput(connection.makefile('r', encoding='ascii', newline='\n'), watchdog)
    sys.stdout = _HelperOutput(channel)
    sys.stderr = io.StringIO()
    return True
