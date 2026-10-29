"""Cleanup regression checks using only temporary files and mocked Windows APIs."""
import ctypes
import os
import stat
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from core import windows_cleaner as W


def test_font_cache_locked_until_reboot_frees_nothing_and_keeps_old_files(monkeypatch, tmp_path):
    monkeypatch.setenv('SystemRoot', str(tmp_path))
    font = tmp_path / 'System32' / 'FNTCACHE.DAT'
    font.parent.mkdir()
    font.write_bytes(b'x' * 200)
    unrelated = font.parent / 'driver-backup.old'
    unrelated.write_bytes(b'precious')
    previous = font.with_suffix('.DAT.old')
    previous.write_bytes(b'previous cache')
    scheduled = []
    monkeypatch.setattr(ctypes, 'windll', NS(kernel32=NS(
        MoveFileExW=lambda *args: scheduled.append(args) or 1)), raising=False)
    monkeypatch.setattr(W, 'is_admin', lambda: True)
    real_unlink = Path.unlink
    def locked(path, *args, **kwargs):
        if path == font:
            raise PermissionError('held by FontCache')
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', locked)
    result = W.WindowsCleaner()._win_font_cache(False)
    assert result.freed_bytes == 0 and result.files_removed == 0
    assert font.exists() and unrelated.exists() and previous.exists()
    assert scheduled == [(str(font), None, 4)]
    assert result.rollback[0]['size'] == 0
    assert any('NOT freed yet' in note for note in result.notes)


def test_font_cache_direct_deletion_counts_only_removed_temp_file(monkeypatch, tmp_path):
    monkeypatch.setenv('SystemRoot', str(tmp_path))
    font = tmp_path / 'System32' / 'FNTCACHE.DAT'
    font.parent.mkdir()
    font.write_bytes(b'x' * 200)
    monkeypatch.setattr(W, 'is_admin', lambda: True)
    monkeypatch.setattr(ctypes, 'windll', NS(kernel32=NS()), raising=False)
    result = W.WindowsCleaner()._win_font_cache(False)
    assert result.freed_bytes == 200 and result.files_removed == 1
    assert not font.exists()


@pytest.mark.parametrize('target', ['win_updates', 'win_delivery', 'win_font_cache', 'win_eventlog'])
def test_admin_denied_never_claims_estimated_bytes(monkeypatch, tmp_path, target):
    monkeypatch.setenv('SystemRoot', str(tmp_path))
    monkeypatch.setattr(W, 'Path', lambda *args: tmp_path)
    monkeypatch.setattr(W, '_dir_size_safe', lambda *args: 500)
    monkeypatch.setattr(W.E.Guards, 'running', lambda *args: '')
    monkeypatch.setattr(W, 'is_admin', lambda: False)
    result = getattr(W.WindowsCleaner(), '_' + target)(False)
    assert result.error and result.freed_bytes == 0 and result.files_removed == 0


@pytest.mark.parametrize('code,after,freed,removed', [
    (0, (300, 1), 700, 2),
    (-2147024891, (1000, 3), 0, 0),
    (-2147024891, (300, 1), 700, 2),
])
def test_recycle_reports_observed_removal_even_on_partial_failure(monkeypatch, code, after, freed, removed):
    samples = iter([(1000, 3), after])
    monkeypatch.setattr(W, '_recycle_stats', lambda: next(samples))
    monkeypatch.setattr(W, '_empty_recycle_bin', lambda: code)
    result = W.WindowsCleaner()._win_recycle(False)
    assert result.freed_bytes == freed and result.files_removed == removed
    assert bool(result.error) == bool(code)


def test_recycle_unavailable_after_delete_does_not_guess_freed_bytes(monkeypatch):
    calls = []
    def query():
        if calls:
            raise OSError('drive unavailable')
        calls.append(True)
        return 1000, 3
    monkeypatch.setattr(W, '_recycle_stats', query)
    monkeypatch.setattr(W, '_empty_recycle_bin', lambda: 0)
    result = W.WindowsCleaner()._win_recycle(False)
    assert result.error and result.freed_bytes == 0 and result.files_removed == 0


def test_service_transaction_preserves_initially_stopped_services(monkeypatch):
    states = {'wuauserv': 'running', 'bits': 'stopped', 'dosvc': 'running'}
    commands = []
    monkeypatch.setattr(W, '_service_status', states.__getitem__)
    def command(cmd, **kwargs):
        commands.append(cmd)
        _, action, name = cmd.split()
        states[name] = 'stop_pending' if action == 'stop' else 'start_pending'
        return '', 0
    def wait(name, state):
        assert states[name].endswith('_pending')
        states[name] = state
    monkeypatch.setattr(W, 'run_win', command)
    monkeypatch.setattr(W, '_wait_service', wait)
    with W._stopped_services(('wuauserv', 'bits', 'dosvc')):
        assert set(states.values()) == {'stopped'}
    assert states == {'wuauserv': 'running', 'bits': 'stopped', 'dosvc': 'running'}
    assert commands == ['sc stop wuauserv', 'sc stop dosvc', 'sc start dosvc', 'sc start wuauserv']


def test_service_stop_failure_restores_previous_service_and_never_enters_cleanup(monkeypatch):
    states = {'wuauserv': 'running', 'bits': 'running'}
    monkeypatch.setattr(W, '_service_status', states.__getitem__)
    commands = []
    def command(cmd, **kwargs):
        commands.append(cmd)
        if cmd == 'sc stop bits':
            return 'denied', 5
        _, action, name = cmd.split()
        states[name] = 'stopped' if action == 'stop' else 'running'
        return '', 0
    monkeypatch.setattr(W, 'run_win', command)
    monkeypatch.setattr(W, '_wait_service', lambda name, state: None)
    with pytest.raises(OSError, match='Could not stop bits'):
        with W._stopped_services(('wuauserv', 'bits')):
            pytest.fail('cleanup must not run while a required service is running')
    assert set(states.values()) == {'running'}
    assert commands[-1] == 'sc start wuauserv'


def test_service_stop_pending_is_not_treated_as_stopped(monkeypatch):
    clock = iter([0, 1, 11])
    monkeypatch.setattr(W.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(W.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(W, '_service_status', lambda name: 'stop_pending')
    with pytest.raises(OSError, match='did not reach stopped'):
        W._wait_service('wuauserv', 'stopped')


def test_sizing_does_not_traverse_ntfs_reparse_entries(monkeypatch, tmp_path):
    fake = NS(path=str(tmp_path / 'junction'), stat=lambda **kwargs: NS(
        st_mode=stat.S_IFDIR, st_file_attributes=0x400, st_dev=tmp_path.stat().st_dev))
    monkeypatch.setattr(W.E, '_entry_lstat', lambda entry: entry.stat(follow_symlinks=False))
    class Entries:
        def __enter__(self): return iter([fake])
        def __exit__(self, *args): pass
    monkeypatch.setattr(W.os, 'scandir', lambda path: Entries() if str(path) == str(tmp_path)
                        else pytest.fail('followed a junction'))
    assert W._dir_size_safe(tmp_path) == 0


def test_sizing_external_hardlinks_are_not_reclaimable(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    source = tmp_path / 'source'
    source.write_bytes(b'x' * 100)
    os.link(source, cache / 'linked')
    assert W._dir_size_safe(cache) == 0
    source.unlink()
    assert W._dir_size_safe(cache) == 100


def test_empty_granular_review_cannot_delete_new_unpreviewed_files(monkeypatch, tmp_path):
    monkeypatch.setenv('SystemRoot', str(tmp_path / 'Windows'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'Local'))
    cleaner = W.WindowsCleaner()
    assert cleaner.review_scan('win_crash_dumps').items == []
    new_dump = tmp_path / 'Local' / 'CrashDumps' / 'new.dmp'
    new_dump.parent.mkdir(parents=True)
    new_dump.write_bytes(b'not previewed')
    result = cleaner.review_clean('win_crash_dumps', ['all'])
    assert result.error and result.files_removed == 0 and new_dump.exists()


def test_monolithic_review_rejects_unknown_selection(monkeypatch):
    cleaner = W.WindowsCleaner()
    calls = []
    monkeypatch.setattr(cleaner, '_win_recycle', lambda dry: calls.append(dry) or W.CleanResult('win_recycle'))
    cleaner.review_scan('win_recycle')
    result = cleaner.review_clean('win_recycle', ['not-shown-in-preview'])
    assert result.error and calls == [True]
