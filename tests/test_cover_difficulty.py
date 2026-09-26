# -*- coding: utf-8 -*-
"""Сложность кавера: цена, схожесть с оригиналом и подсказка.

Числа опираются на замер: у вокальных каверов медиана близости 0.53, у
фортепианных 0.34 (tools/cover_audio_probe.py) — то есть 53% и 34% схожести.
Это не статистика AMQ: она есть только у исходной песни.
"""
import pytest

import animepack as ap
import animepack_tab
import cover_match
from si_hyx_parts.animepack.cover_processing import wanted_cover
from test_animepack_tab_mix import _FakeMain


def song(difficulty=50, **kwargs):
    cand = ap.SongCandidate(song={"songDifficulty": difficulty, "songName": "x",
                                  "annSongId": 7},
                            anime={"malId": 1, "name": "A"}, kind="opening")
    for key, value in kwargs.items():
        setattr(cand, key, value)
    return cand


def cover(difficulty=50, closeness=0.53):
    return song(difficulty, music_effect="cover",
                music_processing={"closeness": closeness})


# ── шкала ────────────────────────────────────────────────────────────────
def test_the_scale_matches_the_measured_medians():
    """Вокальный кавер — около пятёрки, фортепианный — около семёрки."""
    assert cover_match.level(0.53) == 5
    assert cover_match.level(0.34) == 7
    assert cover_match.level(1.0) == 1 and cover_match.level(0.0) == 10


# ── надбавка к цене ──────────────────────────────────────────────────────
@pytest.mark.parametrize("difficulty",
                         list(range(0, 101, 5)) + [1, 99, -5, 120, 33.3])
def test_a_question_without_a_cover_keeps_exactly_the_old_bonus(difficulty):
    """Старые паки и старая формула не должны шелохнуться.

    Шаг по всей шкале, а не несколько точек: на сложности 95 округление стоит
    ровно на половине, и запись формулы через разность единиц давала там лишнее
    очко к цене."""
    assert (ap.music_difficulty_bonus(song(difficulty))
            == ap.song_difficulty_bonus(difficulty))


def test_a_cover_adds_on_top_but_never_doubles_the_bonus():
    plain = ap.music_difficulty_bonus(song(50))
    with_cover = ap.music_difficulty_bonus(cover(50, closeness=0.34))
    assert plain < with_cover <= ap.SONG_DIFF_BONUS_MAX
    # Два потолка подряд остаются одним потолком, а не двадцатью очками.
    assert ap.music_difficulty_bonus(cover(0, closeness=0.0)) == ap.SONG_DIFF_BONUS_MAX


def test_a_far_cover_of_an_easy_song_is_still_a_hard_question():
    easy = ap.music_difficulty_bonus(song(90))
    assert ap.music_difficulty_bonus(cover(90, closeness=0.2)) > easy


def test_a_broken_closeness_costs_nothing_extra():
    assert (ap.music_difficulty_bonus(cover(50, closeness=None))
            == ap.music_difficulty_bonus(song(50)))


def test_an_unchecked_cover_costs_nothing_extra():
    unchecked = cover(50, closeness=0.0)
    unchecked.music_processing["similarity_checked"] = False
    assert (ap.music_difficulty_bonus(unchecked)
            == ap.music_difficulty_bonus(song(50)))


def test_the_price_of_a_cover_question_is_higher_than_the_same_song(tmp_path):
    settings = ap.PackSettings(rounds=1, themes=1, questions=2)
    plain, fancy = song(60), cover(60, closeness=0.2)
    for cand in (plain, fancy):
        cand.anime = {"malId": 1, "statusesStats": [], "score": 7.0}
    ap.assign_prices([plain, fancy], settings)
    assert fancy.price > plain.price


# ── рамка пользователя ───────────────────────────────────────────────────
def band(**kwargs):
    return wanted_cover(ap.PackSettings(cover_enabled=True, **kwargs))


def test_the_band_keeps_only_the_requested_similarity():
    """0% — далеко от оригинала, 100% — почти неотличимо от него."""
    assert cover_match.similarity_percent(0.53) == 53
    assert cover_match.similarity_percent(0.34) == 34
    assert cover_match.amq(0.53) == 53  # совместимое старое имя
    keep = band(cover_amq_from=0, cover_amq_to=40)
    assert keep({"closeness": 0.34, "type": "piano"})      # AMQ 34
    assert not keep({"closeness": 0.9, "type": "vocal"})   # AMQ 90


def test_disabling_similarity_filter_ignores_the_band_and_validation():
    keep = band(cover_similarity_enabled=False,
                cover_amq_from=80, cover_amq_to=30)
    assert keep({"closeness": 0.1, "type": "vocal"})
    settings = ap.PackSettings(cover_enabled=True,
                               cover_similarity_enabled=False,
                               cover_amq_from=80, cover_amq_to=30)
    assert not any("схожесть" in problem.lower()
                   for problem in settings.validate())


def test_an_empty_type_list_means_any_kind_of_performance():
    assert band()({"closeness": 0.5, "type": "metal"})
    keep = band(cover_types=["piano", "orchestra"])
    assert keep({"closeness": 0.5, "type": "piano"})
    assert not keep({"closeness": 0.5, "type": "metal"})


# ── язык исполнения ──────────────────────────────────────────────────────
def sung(language: str) -> dict:
    """Строка находки с заголовком, по которому узнаётся язык."""
    return {"closeness": 0.5, "type": "other_lang",
            "title": f"unravel {language} cover", "channel": ""}


def test_a_language_white_list_keeps_only_those_languages():
    keep = band(cover_langs=["английском"], cover_lang_mode="allow")
    assert keep(sung("english"))
    assert not keep(sung("spanish"))


def test_a_language_black_list_drops_only_those_languages():
    keep = band(cover_langs=["испанском"], cover_lang_mode="exclude")
    assert keep(sung("english"))
    assert not keep(sung("spanish"))


def test_a_cover_without_a_named_language_is_never_filtered_out():
    """«Неизвестно» — это не «другой язык»: иначе японские исполнения улетели
    бы заодно с испанскими."""
    plain = {"closeness": 0.5, "type": "vocal", "title": "unravel cover",
             "channel": ""}
    assert band(cover_langs=["английском"], cover_lang_mode="allow")(plain)
    assert band(cover_langs=["английском"], cover_lang_mode="exclude")(plain)


def test_an_empty_language_list_means_any_language():
    for mode in ("allow", "exclude"):
        keep = band(cover_lang_mode=mode)
        assert keep(sung("english")) and keep(sung("spanish"))


def test_unknown_language_keys_do_not_survive_the_settings_file():
    """Чужой ключ в settings.json не должен молча отбирать каверы."""
    saved = ap.PackSettings(cover_enabled=True).to_dict()
    saved["cover_langs"] = ["английском", "клингонском"]
    saved["cover_lang_mode"] = "вверх ногами"
    settings = ap.PackSettings.from_dict(saved)
    assert settings.cover_langs == ["английском"]
    assert settings.cover_lang_mode == "allow"


def test_an_upside_down_band_is_refused_by_validation():
    settings = ap.PackSettings(cover_enabled=True, cover_amq_from=80,
                               cover_amq_to=30)
    assert any("схожесть" in problem.lower() for problem in settings.validate())


# ── подсказка в паке ─────────────────────────────────────────────────────
def built(cand, **kwargs):
    settings = ap.PackSettings(rounds=1, themes=1, questions=1, hint=True,
                               **kwargs)
    cand.anime = {"malId": 1, "name": "A", "russian": "А"}
    return ap.build_content_xml([cand], settings).decode("utf-8")


def test_the_question_says_it_is_a_cover():
    assert "Опенинг (кавер)" in built(cover(50))


def test_the_question_names_the_kind_of_cover():
    """«Опенинг (кавер на английском)», а не безликое «Кавер»."""
    spoken = cover(50)
    spoken.music_processing = {"closeness": 0.5, "type": "other_lang",
                               "title": "Unravel - English Cover",
                               "channel": "Someone"}
    assert "Опенинг (кавер на английском)" in built(spoken)
    played = cover(50)
    played.music_processing = {"closeness": 0.5, "type": "piano",
                               "title": "Unravel [Piano]", "channel": "X"}
    assert "Опенинг (кавер на фортепиано)" in built(played)


def test_the_host_says_where_the_cover_came_from():
    """Канал звучит ОДНОВРЕМЕННО с отрезком, а не до него."""
    cand = cover(50)
    cand.music_processing = {"closeness": 0.5, "type": "vocal",
                             "title": "Unravel cover", "channel": "Nika Lenina"}
    xml = built(cand)
    assert 'placement="replic"' in xml and "Взято с канала Nika Lenina" in xml


def test_the_answer_credits_the_original_artist_of_a_cover():
    cand = cover(50)
    cand.song["songArtist"] = "TK"
    assert "Исполнитель оригинала — 『TK』" in built(cand)
    plain = song(50)
    plain.song["songArtist"] = "TK"
    assert "Исполнитель — 『TK』" in built(plain)


def test_the_answer_ends_with_a_link_to_the_cover():
    """Адрес ролика с кавером — отдельной последней строкой ответа."""
    cand = cover(50)
    cand.music_processing = {"closeness": 0.5, "type": "piano",
                             "title": "Unravel [Piano]", "channel": "X",
                             "url": "https://www.youtube.com/watch?v=abc123"}
    variants = cand.answer_variants()
    assert variants[-1] == "https://www.youtube.com/watch?v=abc123"
    assert variants[0] == cand.main_answer
    assert "https://www.youtube.com/watch?v=abc123" in built(cand)
    # У обычной песни лишней строки в ответе не появляется.
    assert not song(50).cover_link


def test_the_audio_track_carries_no_timer():
    """Таймера у дорожки нет вовсе: duration на ней больше не пишется."""
    xml = built(song(50))
    audio = xml[xml.index('type="audio"'):]
    assert "duration" not in audio[:audio.index(">")]


# ── вкладка ──────────────────────────────────────────────────────────────
@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab(main_window=_FakeMain())
    yield widget
    widget.cleanup()


def test_cover_settings_survive_a_reload(tab):
    tab.chk_cover.setChecked(True)
    tab.chk_cover_similarity.setChecked(False)
    tab.sp_cover_percent.setValue(40)
    tab.sp_cover_amq_from.setValue(4)
    tab.sp_cover_amq_to.setValue(8)
    tab.sp_cover_pool.setValue(5)
    tab.cover_type_checks["piano"].setChecked(True)
    saved = ap.PackSettings.from_dict(tab.collect().to_dict())
    assert saved.cover_enabled and saved.cover_percent == 40
    assert not saved.cover_similarity_enabled
    assert (saved.cover_amq_from, saved.cover_amq_to) == (4, 8)
    assert saved.cover_pool == 5 and saved.cover_types == ["piano"]
    tab.apply_settings(saved)
    assert not tab.chk_cover_similarity.isChecked()
    assert "Фильтровать по проценту" in tab.chk_cover_similarity.text()
    assert "та же песня" in tab.chk_cover_similarity.toolTip()
    assert not tab.cover_similarity_range.isEnabled()
    assert tab.sp_cover_amq_to.value() == 8
    assert tab.cover_type_checks["piano"].isChecked()
    assert not tab.cover_type_checks["metal"].isChecked()


def test_the_cover_box_appears_only_with_the_checkbox(tab):
    assert not tab.box_cover.isVisibleTo(tab)
    tab.chk_cover.setChecked(True)
    assert tab.box_cover.isVisibleTo(tab)


def test_an_upside_down_band_cannot_be_collected(tab):
    """«от 8 до 3» во вкладке невозможно: «до» подтягивается к «от»."""
    tab.chk_cover.setChecked(True)
    tab.sp_cover_amq_from.setValue(8)
    tab.sp_cover_amq_to.setValue(3)
    settings = tab.collect()
    assert settings.cover_amq_to == 8 and not settings.validate()


def test_quality_floor_drops_the_worst_covers(tab):
    """Планка просмотров и лайков: «мега плохих» каверов в паке быть не должно.

    Ноль в самой записи значит «неизвестно» (лайки поиск YouTube отдаёт не
    всегда) — по такому числу никого не выбрасываем."""
    from si_hyx_parts.animepack.cover_processing import wanted_cover

    tab.chk_cover.setChecked(True)
    tab.sp_cover_views.setValue(1000)
    tab.sp_cover_likes.setValue(20)
    settings = tab.collect()
    assert (settings.cover_min_views, settings.cover_min_likes) == (1000, 20)
    keep = wanted_cover(settings)
    good = {"closeness": 0.5, "views": 5000, "likes": 100}
    assert keep(good)
    assert not keep(dict(good, views=40))
    assert not keep(dict(good, likes=3))
    # Неизвестные числа планку не включают.
    assert keep(dict(good, views=0, likes=0))
    # Планку можно снять совсем.
    tab.sp_cover_views.setValue(0)
    tab.sp_cover_likes.setValue(0)
    assert wanted_cover(tab.collect())(dict(good, views=40, likes=1))
