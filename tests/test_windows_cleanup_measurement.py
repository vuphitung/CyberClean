import ntpath
import os
from types import SimpleNamespace as NS
from utils.windows_cleanup_measurement import VolumeMeter
from core import windows_cleaner as W


def test_volume_delta_is_signed_and_each_volume_counted_once():
    values={'C:\\':iter([100,80]),'D:\\':iter([200,240])}
    calls=[]
    def usage(root):
        calls.append(root)
        return NS(free=next(values[root]), total=1000, percent=90)
    meter=VolumeMeter(['C:\\a','C:\\b','D:\\c'],usage,ntpath.splitdrive)
    meter.begin()
    assert meter.end()==20
    assert meter.observations[os.path.normcase('C:')]['delta']==-20
    assert calls.count('C:\\')==2 and calls.count('D:\\')==2


def test_measurement_error_is_unavailable_not_zero():
    def usage(root):raise OSError('denied')
    meter=VolumeMeter(['C:\\a'],usage,ntpath.splitdrive)
    meter.begin()
    assert meter.end() is None
    assert 'denied' in meter.errors[0]


def test_partial_volume_sample_is_unavailable_not_a_full_total():
    def usage(root):
        if root == 'D:\\':
            raise OSError('offline')
        return NS(free=100, total=1000, percent=90)
    meter = VolumeMeter(['C:\\a', 'D:\\b'], usage, ntpath.splitdrive)
    meter.begin()
    assert meter.end() is None
    assert len(meter.observations) == 1


def test_reused_meter_does_not_retain_previous_samples():
    fail = False
    def usage(root):
        if fail:
            raise OSError('offline')
        return NS(free=100, total=1000, percent=90)
    meter = VolumeMeter(['C:\\a'], usage, ntpath.splitdrive)
    meter.begin()
    assert meter.end() == 0
    fail = True
    meter.begin()
    assert meter.end() is None
    assert not meter.before and not meter.observations


def test_dns_is_an_operation_not_a_removed_file(monkeypatch):
    monkeypatch.setattr(W,'run_win',lambda *a,**k:('',0))
    result=W.WindowsCleaner()._win_dns(False)
    assert not result.error and result.files_removed==0 and result.freed_bytes==0


def test_browser_labels_are_not_user_data():
    from core.engine import windows_browser_label
    assert windows_browser_label(r'C:\Users\a\AppData\Local\Google\Chrome\User Data')=='Google Chrome'
    assert windows_browser_label(r'C:\Users\a\AppData\Local\Microsoft\Edge\User Data')=='Microsoft Edge'
    assert windows_browser_label(r'C:\SomeApp\User Data')=='SomeApp'
