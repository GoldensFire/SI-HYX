# -*- coding: utf-8 -*-
"""Появление из меню монтажа: доступность, экспорт и отмена."""
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from PyQt6.QtCore import QEventLoop, QTimer
import pytest

import edit_tab as editor
from image_entrance import EFFECTS, EDITOR_ONLY_EFFECTS
from si_hyx_parts.edit_tab.entrance_dialog import EntranceDialog
from si_hyx_parts.edit_tab.entrance_worker import EntranceWorker

# На раннере CI нет bundled ffmpeg (внешний ассет): без него воркер падает, а
# EditTab показывает модальное окно ошибки и прогон висит до таймаута.
needs_ffmpeg = pytest.mark.skipif(not os.path.exists(editor.FFMPEG),
                                  reason="нет bundled ffmpeg (внешний ассет)")


def _menu(qapp, source):
    widget = editor.QWidget()
    stub = SimpleNamespace(
        actual_source_file=str(source), filepath=str(source), is_still_image=True,
        video_stream_index=None, duration=0, deleted=[], opened=[],
        _relax_width=lambda button: None)
    stub.delete_source_file = lambda: stub.deleted.append(True)
    stub.create_entrance = lambda: stub.opened.append(True)
    stub._entrance_busy = lambda: editor.EditTab._entrance_busy(stub)
    stub._refresh_more_actions = lambda: editor.EditTab._refresh_more_actions(stub)
    editor.EditTab._build_more_actions(stub)
    stub.btn_more_actions.setParent(widget)
    return stub, widget


def test_more_menu_actions_and_media_availability(qapp, tmp_path):
    source = tmp_path / "image.png"
    Image.new("RGB", (80, 50), "blue").save(source)
    stub, widget = _menu(qapp, source)
    try:
        assert [a.text() for a in stub.more_actions_menu.actions() if not a.isSeparator()] == [
            "Появление", "Удалить исходный файл"]
        assert stub.btn_more_actions.menu() is stub.more_actions_menu
        stub.action_entrance.trigger()
        stub.action_delete_source.trigger()
        assert stub.opened == [True] and stub.deleted == [True]
        stub.is_still_image = False
        stub._refresh_more_actions()
        assert not stub.action_entrance.isEnabled()
        assert stub.action_delete_source.isEnabled()
        stub.video_stream_index, stub.duration = 0, 3
        stub._refresh_more_actions()
        assert stub.action_entrance.isEnabled()
        stub._entrance_running = True
        stub._refresh_more_actions()
        assert not stub.action_delete_source.isEnabled()
        assert not stub.action_entrance.isEnabled()
        stub._entrance_running = False
        stub.actual_source_file = stub.filepath = None
        stub._refresh_more_actions()
        assert not stub.btn_more_actions.isEnabled()
    finally:
        widget.close()
        widget.deleteLater()


def test_editor_dialog_keeps_all_effects_and_source_preview(qapp, tmp_path):
    source = tmp_path / "картинка.png"
    image = Image.new("RGB", (80, 50), "blue")
    image.save(source)
    dialog = EntranceDialog(None, source, True)
    try:
        assert dialog.cb_entrance_effect.count() == len(EFFECTS)
        for effect in EDITOR_ONLY_EFFECTS:
            dialog.cb_entrance_effect.setCurrentIndex(dialog.cb_entrance_effect.findData(effect))
            assert dialog.options()["effect"] == effect
        assert dialog.entrance_preview.original.tobytes() == image.tobytes()
        dialog.show()
        qapp.processEvents()
        assert dialog.entrance_preview.timer.isActive()
        dialog.hide()
        qapp.processEvents()
        assert not dialog.entrance_preview.timer.isActive()
    finally:
        dialog.close()
        dialog.deleteLater()


def _run(command):
    result = subprocess.run(command, capture_output=True, timeout=60,
                            creationflags=editor.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


@needs_ffmpeg
@pytest.mark.parametrize("is_image", [True, False])
def test_editor_worker_exports_effect_and_preserves_source(qapp, tmp_path, is_image):
    source = tmp_path / ("исходник.png" if is_image else "исходник.mp4")
    if is_image:
        Image.new("RGB", (160, 90), "blue").save(source)
    else:
        _run([editor.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
              "testsrc2=size=160x90:rate=10", "-f", "lavfi", "-i",
              "sine=frequency=440:sample_rate=48000", "-t", "1",
              "-c:v", "libx264", "-c:a", "aac", str(source)])
    before = source.read_bytes()
    output = tmp_path / "результат.mp4"
    worker = EntranceWorker(source, output, is_image, {
        "effect": "fly", "seconds": .4, "fps": 10, "preset": 13, "crf": 25})
    done, failed = [], []
    worker.done.connect(done.append)
    worker.failed.connect(failed.append)
    worker.start()
    assert worker.wait(60000)
    qapp.processEvents()
    assert not failed and done == [str(output)]
    assert source.read_bytes() == before
    probe = json.loads(_run([editor.FFPROBE, "-v", "error", "-show_entries",
                             "stream=codec_type:format=duration", "-of", "json", str(output)]))
    assert float(probe["format"]["duration"]) == pytest.approx(.4 if is_image else 1, abs=.05)
    assert any(s["codec_type"] == "audio" for s in probe["streams"]) == (not is_image)
    if not is_image:
        def audio(path):
            return _run([editor.FFMPEG, "-v", "error", "-i", str(path),
                         "-vn", "-c:a", "copy", "-f", "adts", "-"])
        assert audio(source) == audio(output)
    assert not list(tmp_path.glob("_entrance_*"))


def test_cancelled_worker_publishes_no_output(qapp, tmp_path):
    source, output = tmp_path / "source.png", tmp_path / "result.mp4"
    Image.new("RGB", (160, 90), "blue").save(source)
    worker = EntranceWorker(source, output, True, {"effect": "spin", "seconds": 5})
    failed = []
    worker.failed.connect(failed.append)
    original_run = worker._run

    def cancel_before_encoding(command, timeout):
        worker.stop()
        return original_run(command, timeout)

    worker._run = cancel_before_encoding
    worker.start()
    assert worker.wait(60000)
    qapp.processEvents()
    assert failed == ["Отменено"]
    assert not output.exists() and source.exists()
    assert not list(tmp_path.glob("_entrance_*"))


@needs_ffmpeg
def test_create_entrance_from_initialized_editor(qapp, tmp_path, monkeypatch):
    from si_hyx_parts.edit_tab import entrance_actions
    monkeypatch.setattr(editor, "EDITOR_SETTINGS_PATH", str(tmp_path / "settings.json"))
    source = tmp_path / "картинка.png"
    Image.new("RGB", (80, 50), "blue").save(source)
    tab = editor.EditTab()

    class AcceptedDialog(EntranceDialog):
        def exec(self):
            self.sp_entrance_seconds.setValue(.2)
            self.sp_entrance_fps.setValue(10)
            return editor.QDialog.DialogCode.Accepted

    monkeypatch.setattr(entrance_actions, "EntranceDialog", AcceptedDialog)
    try:
        assert tab.btn_more_actions in tab._montage_side_btns
        assert not tab.btn_more_actions.isEnabled()
        tab.load_file(str(source))
        assert tab.action_entrance.isEnabled()
        tab.action_entrance.trigger()
        assert tab._entrance_running and tab.btn_cut.text() == "Отмена"
        assert not tab.action_delete_source.isEnabled()
        worker = tab._entrance_worker
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        QTimer.singleShot(30000, loop.quit)
        loop.exec()
        qapp.processEvents()
        assert not tab._entrance_running
        assert tab.action_entrance.isEnabled()
        assert tab.action_delete_source.isEnabled()
        assert tab.btn_cut.text() != "Отмена"
        assert (tmp_path / "картинка — появление.mp4").is_file()
    finally:
        tab.shutdown()
        tab.close()
        tab.deleteLater()
