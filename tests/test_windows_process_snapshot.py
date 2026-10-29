"""Bounded process-table parsing and read-only native counter comparison."""
import ctypes
import os
import sys
import pytest
from utils.windows_process_snapshot import _ProcessPrefix, _parse, read_windows_processes


def _table():
    stride = (ctypes.sizeof(_ProcessPrefix)+7)//8*8
    names = ['worker.exe'.encode('utf-16-le'), 'other.exe'.encode('utf-16-le')]
    buffer = ctypes.create_string_buffer(stride*2+sum(map(len, names)))
    pointer = ctypes.addressof(buffer)+stride*2
    for index, name in enumerate(names):
        record = _ProcessPrefix.from_buffer(buffer, index*stride)
        record.NextEntryOffset = stride if index == 0 else 0
        record.UniqueProcessId = 101+index
        record.CreateTime = 1000+index
        record.UserTime, record.KernelTime = 20_000_000, 10_000_000
        record.WorkingSetSize = 8192+index
        record.ImageName.Length = record.ImageName.MaximumLength = len(name)
        record.ImageName.Buffer = pointer
        ctypes.memmove(pointer, name, len(name))
        pointer += len(name)
    return buffer


def test_process_table_preserves_identity_cpu_and_working_set():
    table = _table()
    result = _parse(table, ctypes.sizeof(table))
    assert [row['name'] for row in result] == ['worker.exe', 'other.exe']
    assert [row['create_time'] for row in result] == [1000, 1001]
    assert result[0]['cpu_times'].user == 2 and result[0]['cpu_times'].system == 1
    assert result[1]['memory_rss'] == 8193


@pytest.mark.parametrize('field,value', [('NextEntryOffset', 4), ('NextEntryOffset', 99999999),
                                       ('UserTime', -1)])
def test_invalid_record_fails_closed(field, value):
    table = _table()
    setattr(_ProcessPrefix.from_buffer(table), field, value)
    with pytest.raises(ValueError):
        _parse(table, ctypes.sizeof(table))


def test_name_pointer_outside_buffer_is_never_dereferenced():
    table = _table()
    _ProcessPrefix.from_buffer(table).ImageName.Buffer = 1
    with pytest.raises(ValueError, match='outside'):
        _parse(table, ctypes.sizeof(table))


def test_query_failure_and_excessive_growth_are_bounded():
    with pytest.raises(OSError, match='c0000001'):
        read_windows_processes(lambda *args: 0xc0000001)
    calls=[]
    def growing(kind, buffer, capacity, needed):
        calls.append(capacity)
        return 0xc0000004
    with pytest.raises(OSError, match='limit'):
        read_windows_processes(growing)
    assert len(calls) <= 8


@pytest.mark.skipif(sys.platform != 'win32', reason='requires native Windows')
def test_native_process_snapshot_matches_current_process_counters():
    import psutil
    process = psutil.Process()
    before = process.cpu_times()
    row = next(row for row in read_windows_processes() if row['pid'] == os.getpid())
    after = process.cpu_times()
    assert before.user <= row['cpu_times'].user <= after.user
    assert before.system <= row['cpu_times'].system <= after.system
    assert abs(row['create_time']/10_000_000-11644473600-process.create_time()) < .00001
    assert row['name'].lower() == process.name().lower()
    assert abs(row['memory_rss']-process.memory_info().rss) < 8*1024*1024
