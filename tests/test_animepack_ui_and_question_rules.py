# -*- coding: utf-8 -*-
"""Постоянные колонки, независимая база, цены видео и подписи вопросов."""
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QCheckBox, QSlider

import animepack as ap
from animepack_tab import AnimePackTab
from si_hyx_parts.animepack_tab.db_table_dialog import DbTableDialog


def _card(ident, kind="tv"):
    return {"id": ident, "malId": ident, "name": f"Title {ident}",
            "russian": f"Тайтл {ident}", "kind": kind, "score": 8,
            "franchise": f"series-{ident}", "airedOn": {"year": 2020},
            "statusesStats": [{"status": "completed", "count": 100_000}]}


def _question_items(candidate, **kwargs):
    settings = ap.PackSettings(rounds=1, themes=1, questions=1, **kwargs)
    root = ET.fromstring(ap.build_content_xml([candidate], settings))
    return root.findall(".//{*}param[@name='question']/{*}item")


@pytest.fixture
def tab(qapp):
    widget = AnimePackTab()
    yield widget
    widget.cleanup()
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def test_lists_stay_at_top_of_second_column_with_every_composition_off(tab, qapp):
    columns = tab.settings_columns
    first, lists = columns._groups[:2]
    checks = first.findChildren(QCheckBox)
    for width in (1600, 1200, 800):
        tab.resize(width, 900)
        tab.show()
        for check in checks:
            check.setChecked(False)
        qapp.processEvents()
        tab._fit_settings_width()
        assert columns._columns >= 2
        assert lists.parentWidget() is columns._holders[1]
        assert columns._holders[1].layout().itemAt(0).widget() is lists
        assert lists.geometry().top() == first.geometry().top()
        # Раскрытие состава не меняет закреплённую колонку списков.
        tab.chk_video.setChecked(True)
        qapp.processEvents()
        assert lists.parentWidget() is columns._holders[1]
        tab.chk_video.setChecked(False)


def test_sliders_change_saved_values_and_video_name(tab, qapp):
    from config import STYLESHEET
    tab.setStyleSheet(STYLESHEET + tab.styleSheet())
    tab.resize(1600, 900)
    tab.show()
    qapp.processEvents()
    assert isinstance(tab.cb_generation_priority.slider, QSlider)
    assert isinstance(tab.sp_manga_adapted.slider, QSlider)
    tab.cb_generation_priority.slider.setValue(2)
    qapp.processEvents()
    assert tab.cb_generation_priority.slider.width() >= 120
    assert (tab.cb_generation_priority.number.width() >=
            tab.cb_generation_priority.number.sizeHint().width())
    tab.sp_manga_adapted.slider.setValue(73)
    saved = tab.collect().to_dict()
    assert saved["generation_priority"] == "high"
    assert saved["manga_adapted_percent"] == 73
    assert tab.chk_video.text() == "Опенинги с видеорядом"
    assert tab.mix.LABELS["video"] == "Опенинги с видеорядом"


def test_template_popup_does_not_move_pack_controls(tab, qapp):
    tab.resize(1600, 800)
    tab.show()
    qapp.processEvents()
    before = (tab.templates_box.geometry(), tab.pack_box.geometry(),
              tab.actions_box.geometry())
    tab._update_template()
    qapp.processEvents()
    assert tab.template_notice.isWindow()
    assert not tab.template_notice.isHidden()
    assert before == (tab.templates_box.geometry(), tab.pack_box.geometry(),
                      tab.actions_box.geometry())
    tab._template_notice_timer.timeout.emit()
    assert tab.template_notice.isHidden()


def test_database_uses_only_its_own_filters(qapp, tmp_path):
    cache = ap.ShikimoriDbCache(str(tmp_path / "database.json"))
    cache.add_cards("anime", "all", [_card(1), _card(2, "movie")])
    cache.add_cards("manga", "all", [_card(3, "manga"), _card(4, "manhwa")])
    cache.save()
    calls = []

    def collect():
        calls.append(True)
        return ap.PackSettings(manga_kinds={"manhwa": True}, kinds={"movie": True})

    source = SimpleNamespace(collect=collect)
    dialog = DbTableDialog(cache, source)
    try:
        dialog.flush()
        dialog.tabs.setCurrentWidget(dialog.manga)
        dialog.flush()
        assert len(dialog.manga.model._rows) == 2
        assert len(dialog.anime.model._rows) == 2
        assert not calls

        def choose_filters():
            popup = QApplication.activeModalWidget()
            for kind, check in popup.checks["manga"].items():
                check.setChecked(kind == "manhwa")
            for kind, check in popup.checks["anime"].items():
                check.setChecked(kind == "movie")
            popup.accept()

        QTimer.singleShot(0, choose_filters)
        dialog.btn_filters.click()
        dialog.flush()
        assert [row["kind"] for row in dialog.manga.model._rows] == ["manhwa"]
        assert dialog._counts["manga"]["count"] == 2
        dialog.tabs.setCurrentWidget(dialog.anime)
        dialog.flush()
        assert [row["kind"] for row in dialog.anime.model._rows] == ["movie"]
        dialog._set_filters({"anime": None, "manga": ()})
        dialog.flush()
        dialog.tabs.setCurrentWidget(dialog.manga)
        dialog.flush()
        assert not dialog.manga.model._rows
        dialog._set_filters({"anime": None, "manga": None})
        dialog.flush()
        assert len(dialog.manga.model._rows) == 2
        assert not calls
    finally:
        dialog.close()
        dialog.flush()


@pytest.mark.parametrize("song_type", ["Opening 1", "Ending 2"])
@pytest.mark.parametrize("difficulty", [0, 80, 100])
def test_video_price_equals_frame_price_without_music_bonuses(song_type, difficulty):
    song = {"songType": song_type, "songDifficulty": difficulty}
    frame = ap.SongCandidate({}, _card(1), kind=ap.FRAME_KIND)
    video = ap.SongCandidate(song, _card(1), kind=ap.VIDEO_KIND, has_video=True)
    song_video = ap.SongCandidate(song, _card(1), kind=ap.song_kind(song_type),
                                 has_video=True, theme_video_ready=True)
    ap.assign_prices([frame, video, song_video], ap.PackSettings())
    assert video.price == frame.price
    assert video.price_parts == frame.price_parts
    assert song_video.price == frame.price
    assert song_video.price_parts == frame.price_parts


@pytest.mark.parametrize("has_video", [False, True])
@pytest.mark.parametrize("effect", ["", "chiptune", "cover"])
def test_hint_lists_all_song_types_in_the_answer(has_video, effect):
    cand = ap.SongCandidate(
        {"songType": "Opening 1", "songName": "Connect"}, _card(1),
        kind=ap.VIDEO_KIND if has_video else "opening", has_video=has_video,
        music_effect=effect)
    cand.song_alternates = [
        {"anime": _card(2), "song": {"songType": "Insert Song"}},
        {"anime": _card(3), "song": {"songType": "Opening 2"}}]
    items = _question_items(cand, hint=True)
    assert items[0].text.startswith("Опенинг/OST")
    assert items[0].get("waitForFinish") == "False"
    if has_video:
        assert items[0].get("placement") == "replic"


def test_studio_entrances_show_a_caption_with_each_video():
    cand = ap.SongCandidate({}, _card(1), kind=ap.STUDIO_KIND,
                            frame_name="a.png", has_frame=True)
    cand.extra_frames = ["b.png", "c.png"]
    cand.entrance_frames = {name: name + ".mp4" for name in cand.question_frames}
    items = _question_items(cand, entrance_enabled=True, studio_seconds=12)
    assert len(items) == 6
    for task, video in zip(items[::2], items[1::2]):
        assert task.text == ap.STUDIO_TASK_TEXT
        assert task.attrib == {"waitForFinish": "False"}
        assert video.get("duration") == "00:00:04"
        assert video.get("type") == "video"
        assert video.text.endswith(".png.mp4")
