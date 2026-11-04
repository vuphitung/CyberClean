"""Windows advisor regressions on small temporary NTFS trees and in-memory reports."""
import os
from pathlib import Path
import sys
import time

import pytest

from core import advisor as A
from tests.helpers import tree


@pytest.mark.skipif(sys.platform != 'win32', reason='native Windows directory identities')
def test_windows_walk_descends_nested_directories_and_classifies_files(tmp_path):
    home = tree(tmp_path / 'home', {'VMs/test.vhdx': 1000, 'Videos/clip.mkv': 2000,
                                     'AppData/Local/ignored.bin': 3000})
    walk = A.walk_home(str(home), big_min=500, budget=A._Budget(10))
    findings = A.collect_big_files(walk, time.time())
    assert {finding.title: finding.category for finding in findings} == {
        'test.vhdx': 'vm', 'clip.mkv': 'large'}
    assert {finding.size for finding in findings} == {1000, 2000}


@pytest.mark.skipif(sys.platform != 'win32', reason='native Windows directory identities')
def test_windows_walk_finds_nested_old_project_artifacts(tmp_path):
    home = tree(tmp_path / 'home', {'code/old/node_modules/pkg/data': 1024,
                                     'code/old/package.json': 2}, days=90)
    walk = A.walk_home(str(home), big_min=500, budget=A._Budget(10))
    findings = A.collect_project_artifacts(walk, time.time(), A._Budget(10), min_mb=0)
    assert len(findings) == 1 and findings[0].category == 'projects'
    assert findings[0].size == 1024 and findings[0].age_days >= 89


def overlap_report():
    return A.Report(findings=[
        A.Finding('vm', 'ISO', r'C:\Users\u\Downloads\image.iso', 600),
        A.Finding('downloads', 'Downloads folder', r'C:\Users\u\Downloads', 1000),
        A.Finding('downloads', 'ISO download row', r'c:/users/U/downloads/IMAGE.ISO', 600),
        A.Finding('downloads', 'archive', r'C:\Users\u\Downloads\archive.zip', 300),
        A.Finding('large', 'other volume', r'D:\data.bin', 200),
        A.Finding('large', 'sibling folder', r'C:\Users\u\Downloads-old\other.bin', 50),
    ], windows_accounting=True)


def test_windows_totals_count_overlapping_download_rows_only_once():
    report = overlap_report()
    original_sizes = [finding.size for finding in report.findings]
    assert report.total == 1250
    assert report.category_totals() == {'vm': 600, 'downloads': 400, 'large': 250}
    assert [finding.size for finding in report.findings] == original_sizes
    text = A.report_to_text(report)
    assert 'Accounted for: 1.2 KB' in text
    assert 'Downloads folder — 400 B' in text


def test_windows_overlap_handles_nested_aggregates_and_largest_exact_duplicate():
    report = A.Report(findings=[
        A.Finding('games', 'library', r'C:\Games', 1000),
        A.Finding('large', 'game folder', r'C:\Games\One', 600),
        A.Finding('vm', 'disk', r'C:\Games\One\disk.vhd', 200),
        A.Finding('windows', 'newer disk sample', r'c:/games/one/DISK.vhd', 250),
        A.Finding('wsl', 'UNC disk', r'\\server\share\disk.vhd', 100),
    ], windows_accounting=True)
    assert report.total == 1100
    assert report.category_totals() == {'games': 400, 'large': 350, 'vm': 0, 'windows': 250, 'wsl': 100}


def test_linux_report_keeps_existing_sum_semantics():
    report = overlap_report()
    report.windows_accounting = False
    assert report.total == 2750


def test_windows_partial_home_scan_marks_the_whole_report_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(A, 'IS_WINDOWS', True)
    def partial_walk(home, **kwargs):
        kwargs['budget'].hit = True
        return A.WalkResult()
    monkeypatch.setattr(A, 'walk_home', partial_walk)
    monkeypatch.setattr(A, 'collect_windows', lambda *args: [])
    monkeypatch.setattr(A, 'collect_wsl_docker_desktop', lambda *args: [])
    report = A.scan(str(tmp_path), seconds=100)
    assert report.truncated


def test_windows_advisor_ui_uses_unique_totals_without_changing_rows(monkeypatch):
    from PyQt6.QtWidgets import QApplication
    from utils.i18n import T
    import ui_pages
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(T, 'lang', 'en')
    page = ui_pages.AdvisorPage(str(Path.cwd()), '')
    report = overlap_report()
    page._render(report)
    tiles = page.findChildren(ui_pages._Tile)
    assert tiles[0]._val.text() == '1.2 KB'
    assert '600.0 B' in tiles[1]._sub.text() and '48%' in tiles[1]._sub.text()
    bars = page.findChildren(ui_pages.ShareBar)
    assert len(bars) == 1 and sum(size for _, size in bars[0]._segs) == 1250
    page.shutdown()
