# -*- coding: utf-8 -*-
"""Раздельные шкалы AMQ песни, OST и схожести кавера."""
from pathlib import Path

from PyQt6.QtWidgets import QSlider
import pytest

import animepack as ap
import animepack_tab
import cover_cache
from si_hyx_parts.animepack.cover_processing import wanted_cover
from si_hyx_parts.animepack_tab.difficulty_range import DifficultyRange
from test_animepack_tab_mix import _FakeMain


def anisong(kind, difficulty):
    return {"audio": "song.mp3", "songLength": 90, "songType": kind,
            "songDifficulty": difficulty, "songCategory": "standard",
            "animeType": "TV",
            "linked_ids": {"myanimelist": 1}}


def test_ost_has_its_own_amq_band_and_openings_keep_the_common_one():
    settings = ap.PackSettings(difficulty_min=40, difficulty_max=80,
                               ost_difficulty_min=10,
                               ost_difficulty_max=30)
    assert ap.filter_song(anisong("Opening 1", 40), settings)
    assert not ap.filter_song(anisong("Opening 1", 39), settings)
    assert ap.filter_song(anisong("Insert Song", 20), settings)
    assert not ap.filter_song(anisong("Insert Song", 40), settings)


def test_old_settings_apply_the_common_amq_band_to_ost():
    settings = ap.PackSettings.from_dict({"difficulty_min": 40,
                                          "difficulty_max": 80})
    assert settings.ost_difficulty_min is None
    assert ap.filter_song(anisong("Insert Song", 40), settings)
    assert not ap.filter_song(anisong("Insert Song", 39), settings)


@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab(main_window=_FakeMain())
    yield widget
    widget.cleanup()


def test_every_difficulty_control_is_a_slider(tab):
    names = ("sp_diff_min", "sp_diff_max", "sp_ost_diff_min",
             "sp_ost_diff_max", "sp_level_from", "sp_level_to",
             "sp_level_avg", "sp_art_level_from", "sp_art_level_to",
             "sp_art_level_avg", "sp_plot_level_from", "sp_plot_level_to",
             "sp_plot_level_avg", "sp_char_level_from", "sp_char_level_to",
             "sp_char_avg", "sp_manga_level_from", "sp_manga_level_to",
             "sp_manga_level_avg", "sp_cover_amq_from", "sp_cover_amq_to")
    for name in names:
        assert isinstance(getattr(tab, name).slider, QSlider), name


def test_separate_ost_band_survives_collect_and_reload(tab):
    tab.sp_diff_min.setValue(40)
    tab.sp_diff_max.setValue(80)
    tab.sp_ost_diff_min.setValue(15)
    tab.sp_ost_diff_max.setValue(35)
    saved = ap.PackSettings.from_dict(tab.collect().to_dict())
    assert (saved.difficulty_min, saved.difficulty_max) == (40, 80)
    assert (saved.ost_difficulty_min, saved.ost_difficulty_max) == (15, 35)
    tab.apply_settings(saved)
    assert (tab.sp_ost_diff_min.value(), tab.sp_ost_diff_max.value()) == (15, 35)


def test_song_difficulty_uses_two_full_width_range_bars_in_anime_group(tab):
    anime_group = tab.settings_columns._groups[2]
    assert tab.song_diff_range.parent() is anime_group
    assert tab.ost_diff_range.parent() is anime_group
    labels = [label.text() for label in anime_group.findChildren(
        animepack_tab.QLabel)]
    assert "Сложность AMQ опенингов/эндингов" in labels
    assert "Сложность AMQ OST" in labels
    tab.sp_diff_min.setValue(45)
    tab.sp_diff_max.setValue(90)
    assert tab.song_diff_range.range_values() == (45, 90)


def test_every_from_to_difficulty_uses_one_range_bar(tab):
    bars = (tab.level_range, tab.art_level_range, tab.plot_level_range,
            tab.char_level_range, tab.manga_level_range,
            tab.cover_similarity_range)
    assert all(isinstance(bar, DifficultyRange) for bar in bars)
    assert all(bar.low_control.isHidden() and bar.high_control.isHidden()
               for bar in bars)
    tab.level_range.set_range(3, 8)
    assert (tab.sp_level_from.value(), tab.sp_level_to.value()) == (3, 8)


def test_expanded_song_settings_update_the_column_height(tab, qapp):
    tab.resize(1168, 691)
    tab.show()
    tab.chk_chiptune.setChecked(True)
    tab.chk_cover.setChecked(True)
    tab._fit_settings_width()
    qapp.processEvents()
    assert tab.box_song_opts.height() >= tab.box_song_opts.sizeHint().height()


def test_collapsed_cover_restores_columns_without_stretching_first_group(
        tab, qapp):
    """Closing the wide cover panel must restore the compact layout."""
    tab.resize(1600, 900)
    tab.show()
    qapp.processEvents()
    columns = tab.settings_columns._columns
    assert columns > 1

    tab.chk_cover.setChecked(True)
    qapp.processEvents()
    tab.chk_cover.setChecked(False)
    qapp.processEvents()

    assert tab.settings_columns._columns == columns
    assert tab.settings_columns.height() == tab.settings_columns.minimumHeight()
    # Группа стоит по своей нужной высоте, а не растянута на всю панель.
    # Мерим именно needed_height: sizeHint раскладки не знает про поле под
    # заголовок QGroupBox, и по нему группа выходила бы «завышенной».
    from si_hyx_parts.animepack_tab.settings_box import needed_height
    first = tab.settings_columns._groups[0]
    assert first.height() <= needed_height(first) + 2


def test_cover_similarity_floor_is_inclusive_and_drops_39_percent():
    keep = wanted_cover(ap.PackSettings(cover_enabled=True,
                                        cover_amq_from=40,
                                        cover_amq_to=100))
    assert not keep({"closeness": .39})
    assert keep({"closeness": .40})


class FakeCovers:
    def __init__(self, row):
        self.row = row
        self.reference_calls = 0

    def reference(self, *_args):
        self.reference_calls += 1
        return object()

    def ensure(self, *_args, **_kwargs):
        # Нарочно игнорирует keep: download_cover обязан проверить ещё раз.
        return [self.row]

    def choose(self, _song, rows, **_kwargs):
        row = dict(rows[0])
        if row.get("windows") and not row.get("length"):
            spot = row["windows"][0]
            begin, end = spot["cover"]
            row.update(at=begin, length=end - begin, ref_at=spot["at"])
        return row

    def cut(self, _video, _at, _length, target, *_args):
        Path(target).write_bytes(b"cover")


def cover_candidate(difficulty=50):
    song = {"audio": "source.mp3", "annSongId": 7,
            "songType": "Opening 1", "songName": "Preserved Roses",
            "songArtist": "T.M.Revolution", "songDifficulty": difficulty}
    return ap.SongCandidate(song=song, anime={"malId": 1, "name": "Valvrave"},
                            kind="opening", music_effect="cover")


def cover_generator(tmp_path, service, **settings):
    generator = ap.AnimePackGenerator(ap.PackSettings(
        cover_enabled=True, audio_cut=5, rounds=1, themes=1, questions=1,
        **settings))
    generator.folder = str(tmp_path)
    (tmp_path / "Audio").mkdir()
    generator._get_bytes = lambda _url: b"source"
    generator._cover_service = service
    return generator


def cover_row(closeness=.39):
    return {"id": "v1", "title": "Preserved Roses cover", "channel": "X",
            "type": "vocal", "closeness": closeness, "length": 5.0,
            "at": 22.0, "ref_at": 22.0, "norm": 8.0, "shift": 0,
            "tempo": 1.0}


def test_unfiltered_song_below_amq_minimum_never_reaches_cover_service(tmp_path):
    service = FakeCovers(cover_row(.8))
    generator = cover_generator(tmp_path, service, difficulty_min=40)
    logs = []
    generator.log = logs.append
    assert not generator.download_audio(cover_candidate(39))
    assert service.reference_calls == 0
    assert any("сложность песни AMQ 39" in line for line in logs)


def test_cover_below_similarity_floor_is_not_selected_or_logged(tmp_path):
    service = FakeCovers(cover_row(.39))
    generator = cover_generator(tmp_path, service, cover_amq_from=40)
    logs = []
    generator.log = logs.append
    assert not generator.download_audio(cover_candidate(50))
    assert not any("схожесть с оригиналом 39%" in line for line in logs)
    assert not list((tmp_path / "Audio").iterdir())


def test_cover_log_names_song_amq_and_similarity_separately(
        tmp_path, monkeypatch):
    service = FakeCovers(cover_row(.39))
    generator = cover_generator(tmp_path, service)
    logs = []
    generator.log = logs.append
    monkeypatch.setattr(cover_cache, "remember_use", lambda *_args: None)
    assert generator.download_audio(cover_candidate(50))
    line = next(line for line in logs if line.startswith("Кавер «"))
    assert "схожесть с оригиналом 39%" in line
    assert "сложность песни AMQ 50" in line
    assert "сложность AMQ 39" not in line


def test_disabled_similarity_filter_still_verifies_song_identity(
        tmp_path, monkeypatch):
    service = FakeCovers(cover_row(.0))
    generator = cover_generator(
        tmp_path, service, cover_similarity_enabled=False)
    logs = []
    generator.log = logs.append
    monkeypatch.setattr(cover_cache, "remember_use", lambda *_args: None)

    assert generator.download_audio(cover_candidate(50))
    assert service.reference_calls == 1
    assert any("схожесть с оригиналом 0%" in line
               for line in logs)


def test_disabled_similarity_filter_never_falls_back_to_title_only(tmp_path):
    class RejectsWrongSong(FakeCovers):
        def ensure(self, *_args, **_kwargs):
            return []

    service = RejectsWrongSong(cover_row(.0))
    generator = cover_generator(
        tmp_path, service, cover_similarity_enabled=False)
    generator.log = lambda _message: None

    assert not generator.download_audio(cover_candidate(50))
    assert service.reference_calls == 1


def test_unavailable_pick_tries_another_cover_of_the_same_song(
        tmp_path, monkeypatch):
    class FallbackCovers(FakeCovers):
        def __init__(self):
            first = dict(cover_row(), id="gone", duration=180)
            second = dict(first, id="ready")
            super().__init__(first)
            self.rows = [first, second]
            self.cuts = []

        def ensure(self, *_args, **_kwargs):
            return list(self.rows)

        def cut(self, video, _at, _length, target, *_args):
            self.cuts.append(video)
            if video == "gone":
                raise RuntimeError("Video unavailable")
            Path(target).write_bytes(b"cover")

    service = FallbackCovers()
    generator = cover_generator(
        tmp_path, service, cover_similarity_enabled=False)
    generator.log = lambda _message: None
    monkeypatch.setattr(cover_cache, "remember_failure", lambda *_args: None)
    monkeypatch.setattr(cover_cache, "remember_use", lambda *_args: None)

    assert generator.download_audio(cover_candidate(50))
    assert service.cuts == ["gone", "ready"]


def test_the_answer_prints_the_real_amq_difficulty_even_for_a_cover():
    """В реплике ведущего — songDifficulty ПЕСНИ, а не схожесть кавера.

    Схожесть у фортепианных каверов как раз около 34, и число 34 рядом с
    рамкой AMQ «45–65» выглядело бы сбоем отбора. На цену схожесть влияет
    (music_difficulty_bonus), в ответ — нет."""
    import re

    song = {"songType": "Opening 1", "songName": "x", "songArtist": "Nightmare",
            "songDifficulty": 85.0, "audio": "a.mp3", "songLength": 90,
            "songCategory": "standard", "animeType": "TV",
            "linked_ids": {"myanimelist": 1}}
    card = {"id": 1, "malId": 1, "russian": "Тест", "name": "Test",
            "airedOn": {"year": 2020}, "score": 8.1}
    cand = ap.SongCandidate(song=song, anime=card, kind="opening")
    cand.music_effect = "cover"
    cand.music_processing = {"closeness": 0.34}
    settings = ap.PackSettings(rounds=1, themes=1, questions=1)
    xml = ap.build_content_xml([cand], settings).decode("utf-8")
    replics = re.findall(r'placement="replic"[^>]*>(.*?)</item>', xml)
    assert replics == ["Исполнитель оригинала — 『Nightmare』 · "
                       "Сложность AMQ — 85 · Рейтинг MAL — 『8.10⭐』"]
    # Схожесть кавера при этом честно поднимает цену вопроса.
    assert ap.music_difficulty_bonus(cand) > ap.song_difficulty_bonus(85.0)
