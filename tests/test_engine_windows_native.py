"""Native NTFS identity/removal checks; only pytest temporary files are deleted."""
import os
import sys
import errno
import ctypes
from contextlib import contextmanager

import pytest

from core import engine as E
from tests.helpers import age, tree

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='native Windows filesystem contracts')


@contextmanager
def _without_delete_share(path):
    """Hold a real Windows file handle that allows reading/writing, not deletion."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 0x1 | 0x2, None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    try:
        yield
    finally:
        assert close(handle), ctypes.get_last_error()


def test_ntfs_hardlinks_are_shared_outside_and_counted_once_inside(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    outside = tmp_path / 'outside'
    outside.write_bytes(b'a' * 1000)
    os.link(outside, cache / 'link')
    shared = E.tree_stats(cache)
    assert (shared.size, shared.shared, shared.files) == (0, 1000, 1)
    assert shared.entries['link'][1:3] == (outside.stat().st_dev, outside.stat().st_ino)
    outside.unlink()
    os.link(cache / 'link', cache / 'second')
    internal = E.tree_stats(cache)
    assert (internal.size, internal.shared, internal.files) == (1000, 0, 2)


def test_windows_manifest_contains_real_identity_for_every_entry(tmp_path):
    cache = tree(tmp_path / 'cache', {'one': 100, 'sub/two': 200})
    snapshot = E.tree_stats(cache)
    identities = set()
    for relative, record in snapshot.entries.items():
        native = os.lstat(cache / relative)
        assert record[1:3] == (native.st_dev, native.st_ino)
        assert native.st_ino != 0
        identities.add(record[1:3])
    assert len(identities) == 3


def test_windows_owner_never_compares_dummy_uid_with_posix_override(monkeypatch, tmp_path):
    cache = tree(tmp_path / 'cache', {'data': 100})
    monkeypatch.setattr(E.os, 'geteuid', lambda: 1000, raising=False)
    monkeypatch.setattr(E, '_OWNER_UID', 1000)
    assert E._euid() is None
    assert not E.tree_stats(cache).foreign_owner
    item, reason = E.make_item(cache, E.Policy())
    assert item is not None, reason


def test_windows_nested_plan_executes_with_real_manifest_and_no_posix_fds(monkeypatch, tmp_path):
    cache = tree(tmp_path / 'cache', {'one': 100, 'sub/two': 200})
    monkeypatch.setattr(E, '_open_verified_parent_fd',
                        lambda *args: pytest.fail('POSIX dir_fd deletion used on Windows'))
    item, reason = E.make_item(cache, E.Policy(), allowed_root=str(tmp_path))
    assert item is not None, reason
    preview = E.execute_plan([item], dry=True)
    assert cache.exists() and preview.freed == 300 and preview.removed == 2
    result = E.execute_plan([item])
    assert not cache.exists()
    assert result.freed == 300 and result.removed == 2
    assert result.outcomes[0].status == 'removed'


def test_windows_old_files_plan_has_real_identity_and_skips_shared_links(tmp_path):
    cache = tree(tmp_path / 'cache', {'one': 100, 'sub/two': 200})
    outside = tmp_path / 'outside'
    outside.write_bytes(b'keep')
    os.link(outside, cache / 'shared')
    age(cache / 'shared', 30)
    age(cache, 30)
    item = E.plan_old_files(cache, E.Policy(), allowed_root=str(tmp_path))
    assert item is not None
    paths = {os.path.basename(record[0]) for record in item.meta['files']}
    assert paths == {'one', 'two'}
    for path, mtime, inode, size, ctime in item.meta['files']:
        assert inode == os.lstat(path).st_ino and inode != 0
    result = E.execute_plan([item])
    assert result.freed == 300 and result.removed == 2
    assert outside.read_bytes() == b'keep'
    assert (cache / 'shared').exists()


def test_windows_single_file_changed_at_final_removal_boundary_is_preserved(monkeypatch, tmp_path):
    target = tmp_path / 'old-cache'
    target.write_bytes(b'original')
    age(target, 30)
    item, reason = E.make_item(target, E.Policy(), allowed_root=str(tmp_path))
    assert item is not None, reason
    remove = E.remove_path
    def modify_at_boundary(path):
        target.write_bytes(b'new live data')
        return remove(path)
    monkeypatch.setattr(E, 'remove_path', modify_at_boundary)
    result = E.execute_item(item)
    assert result.status == 'skipped' and 'modified' in result.reason
    assert target.read_bytes() == b'new live data'


def test_windows_real_file_lock_preserves_data_until_native_handle_closes(tmp_path):
    target = tmp_path / 'held-cache'
    target.write_bytes(b'cache' * 20)
    age(target, 30)
    with _without_delete_share(target):
        item, reason = E.make_item(target, E.Policy(), allowed_root=str(tmp_path))
        assert item is not None, reason
        preview = E.execute_plan([item], dry=True)
        assert target.read_bytes() == b'cache' * 20
        assert preview.freed == 100   # preview is an estimate, not a deletion
        result = E.execute_plan([item])
        assert target.read_bytes() == b'cache' * 20
        assert result.freed == 0 and result.removed == 0
        assert result.outcomes[0].status == 'skipped'
        assert 'locked' in result.outcomes[0].reason or 'in use' in result.outcomes[0].reason
    # Reading and holding the handle did not change the scanned file identity/content.
    retry = E.execute_plan([item])
    assert not target.exists()
    assert retry.freed == 100 and retry.removed == 1


def test_windows_partial_oserror_retains_already_removed_byte_and_file_counts(monkeypatch, tmp_path):
    cache = tree(tmp_path / 'partial-cache', {'a': 10, 'b': 20, 'c': 30})
    item, reason = E.make_item(cache, E.Policy(), allowed_root=str(tmp_path))
    assert item is not None, reason
    real_unlink = os.unlink
    cache_files = {str(cache / name) for name in ('a', 'b', 'c')}
    deleted = []
    def fail_after_first(path, *args, **kwargs):
        if os.fspath(path) in cache_files:
            if deleted:
                raise OSError(errno.EMFILE, 'injected handle exhaustion after one deletion')
            result = real_unlink(path, *args, **kwargs)
            deleted.append(os.fspath(path))
            return result
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(E.os, 'unlink', fail_after_first)
    result = E.execute_plan([item])
    assert result.outcomes[0].status == 'partial'
    assert result.removed == 1 and result.freed == 10
    assert 'handle exhaustion' in result.outcomes[0].reason
    assert not (cache / 'a').exists()
    assert (cache / 'b').read_bytes() == b'x' * 20
    assert (cache / 'c').read_bytes() == b'x' * 30


def test_windows_mid_delete_modification_preserves_changed_and_remaining_files(monkeypatch, tmp_path):
    cache = tree(tmp_path / 'changing-cache', {'a': 10, 'b': 20, 'c': 30})
    item, reason = E.make_item(cache, E.Policy(), allowed_root=str(tmp_path))
    assert item is not None, reason
    real_unlink = os.unlink
    def modify_next_after_first(path, *args, **kwargs):
        result = real_unlink(path, *args, **kwargs)
        if os.fspath(path) == str(cache / 'a'):
            (cache / 'b').write_bytes(b'new live content during cleanup')
        return result
    monkeypatch.setattr(E.os, 'unlink', modify_next_after_first)
    result = E.execute_plan([item])
    assert result.outcomes[0].status == 'partial'
    assert result.removed == 1 and result.freed == 10
    assert 'modified since the scan' in result.outcomes[0].reason
    assert not (cache / 'a').exists()
    assert (cache / 'b').read_bytes() == b'new live content during cleanup'
    assert (cache / 'c').read_bytes() == b'x' * 30
