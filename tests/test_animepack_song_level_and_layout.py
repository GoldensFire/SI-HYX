# -*- coding: utf-8 -*-
"""Своя рамка узнаваемости у песен, общая колонка рамок и нерасползающаяся панель."""
import pytest

import animepack as ap
import animepack_tab
from si_hyx_parts.animepack_tab.settings_box import SettingsBox
from test_animepack_tab_mix import _FakeMain


@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab(main_window=_FakeMain())
    yield widget
    widget.cleanup()


# ── рамка узнаваемости песен ─────────────────────────────────────────────────
def test_song_level_defaults_to_the_common_band():
    """Пока рамку не трогали, песни слушают общую «Сложность»."""
    settings = ap.PackSettings.from_dict({"level_min": 3, "level_max": 7})
    assert settings.song_level_min is None
    assert settings.level_range("opening") == (3, 7)
    assert settings.level_range("video") == (3, 7)
    assert settings.level_range(None) == (3, 7)


def test_song_level_band_is_independent_once_set():
    settings = ap.PackSettings(level_min=1, level_max=10,
                               song_level_min=2, song_level_max=4)
    assert settings.level_range("opening") == (2, 4)
    assert settings.level_range("ending") == (2, 4)
    assert settings.level_range("insert") == (2, 4)
    assert settings.level_range(ap.VIDEO_KIND) == (2, 4)
    # Кадры и персонажи остаются на общей рамке.
    assert settings.level_range(ap.FRAME_KIND) == (1, 10)


def test_song_level_span_covers_songs_only_pack():
    settings = ap.PackSettings(level_min=1, level_max=10,
                               song_level_min=2, song_level_max=4,
                               pct_songs=100, pct_frames=0, pct_chars=0)
    assert settings.level_span == (2, 4)


def test_song_level_average_has_its_own_bucket():
    assert ap.level_bucket("opening") == "song"
    assert ap.level_bucket(ap.VIDEO_KIND) == "song"
    settings = ap.PackSettings(song_level_avg=5)
    assert ap.own_bucket(settings, "opening") == "song"
    # Ноль в своей средней возвращает песни в общую корзину.
    assert ap.own_bucket(ap.PackSettings(), "opening") is None


def test_song_level_survives_save_and_load(tab):
    tab.song_level_range.set_range(2, 5)
    tab.sp_song_level_avg.setValue(3)
    saved = tab.get_settings()
    tab.song_level_range.set_range(1, 10)
    tab.apply_settings(saved)
    settings = tab.collect()
    assert (settings.song_level_min, settings.song_level_max) == (2, 5)
    assert settings.song_level_avg == 3


def test_studio_level_has_an_independent_band_and_average(tab):
    settings = ap.PackSettings.from_dict({"level_min": 3, "level_max": 7})
    assert settings.studio_level_min is None
    assert settings.level_range(ap.STUDIO_KIND) == (3, 7)
    tab.chk_studio.setChecked(True)
    tab.studio_level_range.set_range(5, 8)
    tab.sp_studio_level_avg.setValue(7)
    saved = tab.get_settings()
    tab.apply_settings(saved)
    collected = tab.collect()
    assert collected.level_range(ap.STUDIO_KIND) == (5, 8)
    assert collected.studio_level_avg == 7
    assert ap.level_bucket(ap.STUDIO_KIND) == "studio"
    assert ap.own_bucket(collected, ap.STUDIO_KIND) == "studio"


# ── все рамки одной колонкой в группе «Аниме» ────────────────────────────────
def test_every_level_band_lives_in_the_anime_group(tab):
    anime_group = tab.settings_columns._groups[2]
    assert anime_group.title() == "Аниме"
    for key in ("song", "studio", "chars", "art", "manga", "plot"):
        _label, bar = tab._level_blocks[key]
        assert bar.parent() is anime_group
        assert bar.avg_control.parent() is bar

    # AMQ-рамки теперь тоже здесь, непосредственно под песнями.
    assert tab.song_diff_range.parent() is anime_group
    assert tab.ost_diff_range.parent() is anime_group
    assert not hasattr(tab, "lbl_diff_bands")
    assert tab._level_blocks["manga"][0].text() == "Комиксы"


def test_lists_stay_in_the_middle_column(tab):
    columns = tab.settings_columns._split(3)
    assert tab.settings_columns._groups[1] in columns[1]
    assert tab.settings_columns._groups[1] not in columns[0] + columns[2]


def test_plot_model_explanation_is_gone(tab):
    texts = [label.text() for label in tab.findChildren(animepack_tab.QLabel)]
    assert not any("Эта модель отвечает за сюжетные вопросы" in text
                   for text in texts)


def test_studio_explanation_is_removed_and_credit_is_one_link(tab):
    texts = [label.text() for label in tab.findChildren(animepack_tab.QLabel)]
    assert not any("Правильный ответ — только название студии" in text
                   for text in texts)
    credit = tab.lbl_credit.text()
    assert credit.count("<a ") == 1
    assert "Leleath (ффыв, nanri, нефор)</a>" in credit


def test_numeric_fields_stay_compact_across_the_tab(tab):
    fields = (tab.findChildren(animepack_tab.QSpinBox)
              + tab.findChildren(animepack_tab.QDoubleSpinBox))
    assert fields
    assert all(field.maximumWidth() <= 112 for field in fields)


def test_level_band_shows_up_with_its_question_kind(tab):
    _label, bar = tab._level_blocks["manga"]
    assert not bar.isVisibleTo(tab)
    tab.chk_manga.setChecked(True)
    assert bar.isVisibleTo(tab)
    tab.chk_manga.setChecked(False)
    assert not bar.isVisibleTo(tab)


# ── раскрытые настройки не наезжают друг на друга ────────────────────────────
def _overlaps(widget) -> list:
    layout = widget.layout()
    if layout is None:
        return []
    kids = [layout.itemAt(i).widget() for i in range(layout.count())]
    kids = [k for k in kids if k is not None and k.isVisible()]
    found = []
    for first in range(len(kids)):
        for second in range(first + 1, len(kids)):
            if kids[first].geometry().intersects(kids[second].geometry()):
                found.append((kids[first], kids[second]))
    for kid in kids:
        found += _overlaps(kid)
    return found


@pytest.mark.parametrize("name", ["chk_chiptune", "chk_cover", "chk_manga",
                                  "chk_plot", "chk_pixiv_art"])
def test_open_settings_never_overlap_the_composition_checkboxes(tab, qapp, name):
    """Раскрытая коробка настроек не рисуется поверх соседних галочек.

    Chiptune ровно так и ломал панель: QGridLayout считает строку с
    heightForWidth только по нему и минимальную высоту виджета в ней не
    смотрит вовсе (см. SettingsBox)."""
    tab.resize(2000, 1000)
    tab.show()
    qapp.processEvents()
    getattr(tab, name).setChecked(True)
    qapp.processEvents()
    tab.resize(2000, 1001)
    qapp.processEvents()
    tab.resize(2000, 1000)
    for _ in range(3):
        qapp.processEvents()
    for group in tab.settings_columns._groups:
        assert not _overlaps(group)


def test_settings_boxes_do_not_report_height_for_width(tab):
    for name in ("box_song_opts", "box_audio_opts", "box_chiptune",
                 "box_cover", "box_manga", "box_plot"):
        box = getattr(tab, name)
        assert isinstance(box, SettingsBox)
        assert not box.hasHeightForWidth()


# ── панель каверов больше не занимает две трети колонки ──────────────────────
def test_cover_kinds_and_languages_moved_into_their_own_window(tab):
    from si_hyx_parts.animepack_tab import cover_kinds_dialog
    assert tab.btn_cover_kinds.text() == "Виды и языки исполнения…"
    assert tab.lbl_cover_kinds.text() == "Виды: любые; языки: любые."
    tab.cover_type_checks["piano"].setChecked(True)
    cover_kinds_dialog.refresh_summary(tab)
    assert "Фортепиано" in tab.lbl_cover_kinds.text()
    # Галочки остались теми же объектами — их читают настройки и тесты.
    assert tab.collect().cover_types == ["piano"]
