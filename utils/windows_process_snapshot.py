"""One bounded Windows process-table query for telemetry, with no process writes.

SystemProcessInformation is dynamically resolved from ntdll as Microsoft advises:
https://learn.microsoft.com/windows/win32/api/winternl/nf-winternl-ntquerysysteminformation
The prefix through WorkingSetSize is stable on supported Windows 10/11 systems.
Every record offset and Unicode pointer is validated before dereferencing it.
"""
import ctypes
from functools import lru_cache
from typing import NamedTuple


class _UnicodeString(ctypes.Structure):
    _fields_ = [('Length', ctypes.c_uint16), ('MaximumLength', ctypes.c_uint16),
                ('Buffer', ctypes.c_void_p)]


class _ProcessPrefix(ctypes.Structure):
    _fields_ = [
        ('NextEntryOffset', ctypes.c_uint32), ('NumberOfThreads', ctypes.c_uint32),
        ('WorkingSetPrivateSize', ctypes.c_int64), ('HardFaultCount', ctypes.c_uint32),
        ('NumberOfThreadsHighWatermark', ctypes.c_uint32), ('CycleTime', ctypes.c_uint64),
        ('CreateTime', ctypes.c_int64), ('UserTime', ctypes.c_int64), ('KernelTime', ctypes.c_int64),
        ('ImageName', _UnicodeString), ('BasePriority', ctypes.c_int32),
        ('UniqueProcessId', ctypes.c_void_p), ('InheritedFromUniqueProcessId', ctypes.c_void_p),
        ('HandleCount', ctypes.c_uint32), ('SessionId', ctypes.c_uint32), ('Reserved3', ctypes.c_void_p),
        ('PeakVirtualSize', ctypes.c_size_t), ('VirtualSize', ctypes.c_size_t),
        ('Reserved4', ctypes.c_uint32), ('PeakWorkingSetSize', ctypes.c_size_t),
        ('WorkingSetSize', ctypes.c_size_t),
    ]


class _CpuTimes(NamedTuple):
    user: float
    system: float


@lru_cache(maxsize=1)
def _query_function():
    query = ctypes.WinDLL('ntdll', use_last_error=True).NtQuerySystemInformation
    query.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                      ctypes.POINTER(ctypes.c_uint32)]
    query.restype = ctypes.c_int32
    return query


def _parse(buffer, length):
    prefix_size = ctypes.sizeof(_ProcessPrefix)
    if length < prefix_size or length > ctypes.sizeof(buffer):
        raise ValueError('Invalid process-table length')
    base = ctypes.addressof(buffer)
    offset, result = 0, []
    while True:
        if offset+prefix_size > length:
            raise ValueError('Truncated process record')
        record = _ProcessPrefix.from_buffer(buffer, offset)
        size = record.ImageName.Length
        pointer = record.ImageName.Buffer or 0
        if size % 2 or size > record.ImageName.MaximumLength:
            raise ValueError('Invalid process name length')
        if size and not (base <= pointer <= base+length-size):
            raise ValueError('Process name points outside query buffer')
        name = ctypes.string_at(pointer, size).decode('utf-16-le') if size else ''
        if min(record.UserTime, record.KernelTime, record.CreateTime) < 0:
            raise ValueError('Invalid process time')
        result.append(dict(pid=int(record.UniqueProcessId or 0), name=name,
                           # Exact 100ns creation value is the baseline identity;
                           # it need not be converted to a human timestamp.
                           create_time=int(record.CreateTime),
                           cpu_times=_CpuTimes(record.UserTime/10_000_000,
                                               record.KernelTime/10_000_000),
                           memory_rss=int(record.WorkingSetSize)))
        jump = record.NextEntryOffset
        if not jump:
            return result
        if jump < prefix_size or offset+jump > length-prefix_size:
            raise ValueError('Invalid next process offset')
        offset += jump


def read_windows_processes(query=None):
    query = query or _query_function()
    capacity = 1024*1024
    for _ in range(8):
        if capacity > 32*1024*1024:
            raise OSError('Windows process table exceeds 32 MiB limit')
        buffer = ctypes.create_string_buffer(capacity)
        needed = ctypes.c_uint32()
        status = query(5, buffer, capacity, ctypes.byref(needed)) & 0xffffffff
        if status in (0xc0000004, 0xc0000023):
            capacity = max(capacity*2, needed.value+65536)
            continue
        if status != 0:
            raise OSError(f'NtQuerySystemInformation failed: 0x{status:08x}')
        return _parse(buffer, needed.value)
    raise OSError('Windows process table kept growing during query')
