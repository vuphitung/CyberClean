"""Capture before mutation; retain pending state until exact read-back succeeds."""
import ctypes
from contextlib import contextmanager

DWORD = ctypes.c_uint32


class PowerState(ctypes.Structure):
    _fields_ = [('Version', DWORD), ('ControlMask', DWORD), ('StateMask', DWORD)]


class MemoryState(ctypes.Structure):
    _fields_ = [('MemoryPriority', DWORD)]


class ProcessAPI:
    def __init__(self, kernel=None):
        self.kernel = kernel or ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [DWORD, ctypes.c_int, DWORD]
        self.kernel.OpenProcess.restype = ctypes.c_void_p
        for name in ('GetProcessInformation', 'SetProcessInformation'):
            fn = getattr(self.kernel, name)
            fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, DWORD]
            fn.restype = ctypes.c_int
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.restype = ctypes.c_int

    @contextmanager
    def handle(self, pid):
        handle = self.kernel.OpenProcess(0x0200 | 0x0400, False, pid)
        if not handle:
            raise OSError('OpenProcess failed')
        try:
            yield handle
        finally:
            self.kernel.CloseHandle(handle)

    def read(self, handle, kind):
        state = PowerState(1, 0, 0) if kind == 'power' else MemoryState()
        cls = 4 if kind == 'power' else 0
        # MEMORY_PRIORITY_INFORMATION is ProcessMemoryPriority = 0.
        if not self.kernel.GetProcessInformation(handle, cls, ctypes.byref(state), ctypes.sizeof(state)):
            raise OSError(f'GetProcessInformation({kind}) failed')
        return [state.ControlMask, state.StateMask] if kind == 'power' else state.MemoryPriority

    def write(self, handle, kind, value):
        state = PowerState(1, *value) if kind == 'power' else MemoryState(value)
        cls = 4 if kind == 'power' else 0
        return bool(self.kernel.SetProcessInformation(handle, cls, ctypes.byref(state), ctypes.sizeof(state)))


def capture(process, eco=True, api=None):
    api = api or ProcessAPI()
    # Refuse to mutate if any original setting/identity cannot be read.
    entry = dict(pid=process.pid, create_time=process.create_time(), name=process.name(),
                 nice=process.nice(), pending=[], applied=[], verified=[])
    with api.handle(process.pid) as handle:
        entry['memory'] = api.read(handle, 'memory')
        if eco:
            entry['power'] = api.read(handle, 'power')
    return entry


def apply(process, entry, *, priority=None, api=None):
    api = api or ProcessAPI()
    if process.create_time() != entry['create_time'] or process.name() != entry['name']:
        raise ProcessLookupError('PID identity changed before apply')
    desired = {'memory': 2}
    if 'power' in entry:
        control, state = entry['power']
        desired['power'] = [control | 1, state | 1]
    if priority is not None:
        entry['pending'].append('nice')
        process.nice(priority)
        entry['applied'].append('nice')
        if process.nice() == priority:
            entry['verified'].append('nice')
    with api.handle(process.pid) as handle:
        for kind, value in desired.items():
            # The API may have applied the value even if read-back fails.
            entry['pending'].append(kind)
            if api.write(handle, kind, value):
                entry['applied'].append(kind)
                if api.read(handle, kind) == value:
                    entry['verified'].append(kind)
    return all(kind in entry['verified'] for kind in entry['pending'])


def restore(process, entry, api=None):
    api = api or ProcessAPI()
    if process.create_time() != entry['create_time'] or process.name() != entry['name']:
        return True  # Old process is gone; never change the new occupant of this PID.
    with api.handle(process.pid) as handle:
        for kind in list(entry['pending']):
            try:
                if kind == 'nice':
                    process.nice(entry['nice'])
                    verified = process.nice() == entry['nice']
                else:
                    verified = api.write(handle, kind, entry[kind]) and api.read(handle, kind) == entry[kind]
                if verified:
                    entry['pending'].remove(kind)
            except OSError:
                continue
    return not entry['pending']
