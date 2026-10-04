# -*- coding: utf-8 -*-
"""Real download-tab controls preserve ranges and safely replace old workers."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

import tabs


class FakeWorker(QObject):
    finished = pyqtSignal()
    log_sig = pyqtSignal(str)
    progress_sig = pyqtSignal(str, float, str)
    finished_sig = pyqtSignal(str, str, str, str)
    error_sig = pyqtSignal(str, str)
    thumb_sig = pyqtSignal(str, str)

    def __init__(self, config):
        super().__init__()
        self.c = config
        self.running = False
        self.stop_requested = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def stop(self):
        self.stop_requested = True

    def complete(self):
        self.running = False
        self.finished.emit()


class FakeInfoWorker(QObject):
    finished = pyqtSignal()
    success = pyqtSignal(int, str, list, list)
    error = pyqtSignal(str)

    def __init__(self, url, proxy=""):
        super().__init__()
        self.url = url
        self.cancelled = False
        self.running = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def tab(qapp, monkeypatch):
    monkeypatch.setattr(tabs, "YtdlpWorker", FakeWorker)
    monkeypatch.setattr(tabs, "InfoWorker", FakeInfoWorker)
    main = SimpleNamespace(log=Mock(), clear_taskbar_progress=Mock(),
                           set_taskbar_progress=Mock())
    widget = tabs.YtdlpTab(main)
    yield widget
    widget.fetch_timer.stop()
    widget.close()
    widget.deleteLater()


def metadata(tab, url="https://www.youtube.com/watch?v=one", duration=195):
    tab.url_edit.setText(url)
    tab.fetch_timer.stop()
    tab._start_fetch()
    tab.info_worker.success.emit(duration, "", [], [])


def enqueue(tab):
    tab.add_dl(False)
    iid = next(iter(tab.items))
    tab.items[iid]['item'].setSelected(True)
    return iid, tab.active_workers[iid]


def test_default_full_video_does_not_become_a_cut(tab):
    metadata(tab)
    _, worker = enqueue(tab)
    assert worker.c['start_s'] is None
    assert worker.c['end_s'] is None
    assert worker.c['source_duration'] == 195


def test_clearing_url_does_not_erase_selected_cut_before_enqueue(tab):
    metadata(tab)
    tab.slider_start.setValue(30)
    tab.slider_end.setValue(60)
    _, worker = enqueue(tab)
    assert worker.c['start_s'] == 30
    assert worker.c['end_s'] == 60
    assert worker.c['source_duration'] == 195


def test_new_url_cannot_inherit_the_previous_clip_range(tab):
    metadata(tab)
    tab.slider_start.setValue(30)
    tab.slider_end.setValue(60)
    tab.url_edit.setText("https://www.youtube.com/watch?v=two")
    tab.fetch_timer.stop()
    _, worker = enqueue(tab)
    assert worker.c['start_s'] is None
    assert worker.c['end_s'] is None
    assert worker.c['source_duration'] is None


def test_old_metadata_is_retained_until_finished_and_cannot_replace_new_range(tab):
    metadata(tab)
    old = tab.info_worker
    tab.url_edit.setText("https://www.youtube.com/watch?v=two")
    tab.fetch_timer.stop()
    tab._start_fetch()
    assert old.cancelled
    assert old in tab._info_workers
    old.success.emit(999, "", [], [])
    assert tab._source_duration is None
    tab.info_worker.success.emit(200, "", [], [])
    assert tab._source_duration == 200
    old.finished.emit()
    assert old not in tab._info_workers


def test_redownload_waits_for_old_worker_and_forces_a_fresh_download(tab):
    metadata(tab)
    iid, old = enqueue(tab)
    tab.redownload_sel()
    assert old.stop_requested
    assert tab.active_workers[iid] is old
    old.complete()
    new = tab.active_workers[iid]
    assert new is not old
    assert new.c['overwrite'] is True
    assert new.c['source_duration'] == 195
    tab._remove_worker(iid, old)
    old.progress_sig.emit(iid, 95, "old progress")
    old.error_sig.emit(iid, "old error")
    assert tab.active_workers[iid] is new
    assert tab.items[iid]['item'].text(3) == "В очереди"


def test_repeated_restart_requests_only_launch_one_replacement(tab):
    metadata(tab)
    iid, old = enqueue(tab)
    launch = Mock(wraps=tab._start_download)
    tab._start_download = launch
    tab.redownload_sel()
    tab.redownload_sel()
    old.complete()
    assert launch.call_count == 1
    assert tab.active_workers[iid] is not old


def test_stop_cancels_a_pending_restart(tab):
    metadata(tab)
    iid, old = enqueue(tab)
    tab.redownload_sel()
    tab.stop_all_dl()
    old.complete()
    assert iid not in tab.active_workers


def test_queued_metadata_from_finished_worker_cannot_override_a_new_url(tab):
    metadata(tab)
    old = tab.info_worker
    old.running = False
    tab.url_edit.setText("https://www.youtube.com/watch?v=two")
    tab.fetch_timer.stop()
    old.success.emit(999, "", [], [])
    assert old.cancelled
    assert tab._source_duration is None


def test_redownload_uses_updated_proxy_and_quality_but_retains_the_cut(tab):
    metadata(tab)
    tab.slider_start.setValue(30)
    tab.slider_end.setValue(60)
    iid, old = enqueue(tab)
    tab.proxy_edit.setText("http://127.0.0.1:8080")
    tab.c_q.setCurrentText("720p")
    tab.redownload_sel()
    old.complete()
    settings = tab.active_workers[iid].c
    assert settings['proxy'] == "http://127.0.0.1:8080"
    assert settings['fmt'] == tabs.FORMAT_OPTIONS['720p']
    assert settings['start_s'] == 30
    assert settings['end_s'] == 60
