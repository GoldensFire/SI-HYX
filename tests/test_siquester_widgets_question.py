# -*- coding: utf-8 -*-
"""Удаление медиа-блока из вопроса (QuestionViewer) — третий путь пересборки .siq.

Кнопка «✕» у блока выкидывает файл из архива, а всё остальное медиа обязано
доехать до нового архива как есть: без распаковки и обратного сжатия.
"""
import zipfile

import pytest

from conftest import CONTENT_XML_V5
from siquester.siq_package import SiqPackage

pytestmark = [pytest.mark.integration, pytest.mark.qt]

BIG_MEDIA = b"media-bytes" * 3000


@pytest.fixture
def viewer_with_pack(qapp, tmp_path):
    """Пак с картинкой в вопросе 200 + открытый на нём QuestionViewer."""
    from siquester.widgets_question import QuestionViewer

    path = str(tmp_path / "pack.siq")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", CONTENT_XML_V5)
        zf.writestr("Images/pic.png", b"\x89PNG\r\n\x1a\nfake")
        zf.writestr("Audio/sound.mp3", BIG_MEDIA, zipfile.ZIP_DEFLATED)
        zf.writestr("Video/clip.mp4", BIG_MEDIA, zipfile.ZIP_STORED)
    siq = SiqPackage(path)
    viewer = QuestionViewer(siq)
    yield qapp, viewer, siq, path
    # Виджет сносим ДО закрытия пакета и не откладывая: с отложенным
    # deleteLater он доживал до выхода из интерпретатора и ронял процесс уже
    # после теста (access violation в Qt).
    viewer.close()
    viewer.setParent(None)
    viewer.deleteLater()
    qapp.processEvents()
    siq.close()


def _delete_buttons(viewer):
    from PyQt6.QtWidgets import QPushButton
    return [b for b in viewer.findChildren(QPushButton)
            if b.text() == "✕" and b.toolTip() == "Удалить блок"]


def _show_image_question(qapp, viewer, siq):
    q = siq.rounds[0]["themes"][0]["questions"][1]      # цена 200, картинка pic.png
    viewer.show_question(q, rnd_idx=0, theme_idx=0)
    qapp.processEvents()
    return q


def test_deleting_media_keeps_the_rest_of_the_pack_intact(viewer_with_pack):
    qapp, viewer, siq, path = viewer_with_pack
    _show_image_question(qapp, viewer, siq)
    buttons = _delete_buttons(viewer)
    assert buttons, "у блоков вопроса нет кнопки удаления"
    buttons[0].click()                                  # первый блок — картинка
    qapp.processEvents()
    with zipfile.ZipFile(path) as zf:
        assert zf.testzip() is None
        assert "Images/pic.png" not in zf.namelist()
        assert zf.read("Audio/sound.mp3") == BIG_MEDIA
        assert zf.read("Video/clip.mp4") == BIG_MEDIA
        assert zf.getinfo("Video/clip.mp4").compress_type == zipfile.ZIP_STORED


def test_the_remaining_media_is_not_recompressed(viewer_with_pack, monkeypatch):
    """Дефлейт за всё удаление заводится ровно один раз — на content.xml."""
    import zlib
    qapp, viewer, siq, path = viewer_with_pack
    _show_image_question(qapp, viewer, siq)
    real, calls = zlib.compressobj, []

    def spy(*a, **kw):
        calls.append(a)
        return real(*a, **kw)

    monkeypatch.setattr(zlib, "compressobj", spy)
    _delete_buttons(viewer)[0].click()
    qapp.processEvents()
    assert len(calls) == 1
