# -*- coding: utf-8 -*-
"""Панель настроек аниме-пака после уборки (просьба пользователя).

Что проверяем: убранные настройки действительно убраны и ниоткуда не читаются,
настройки Chiptune не занимают полэкрана, пока он выключен, а сложность
персонажей стоит под своей галочкой, а не в группе «Аниме».
"""
import animepack as ap
import animepack_tab


def _tab(qapp):
    return animepack_tab.AnimePackTab()


def test_removed_controls_are_gone(qapp):
    """Ни «Пак не больше», ни «Не повторять прошлые кадры», ни лимита Gemini."""
    tab = _tab(qapp)
    try:
        for name in ("sp_max_mb", "chk_frames_new", "sp_gemini_daily"):
            assert not hasattr(tab, name), name
        settings = tab.collect()
        # Память о кадрах включена по умолчанию: повторов между паками нет.
        assert settings.max_pack_mb == ap.MAX_PACK_MB
        assert settings.frames_no_repeat is True
    finally:
        tab.cleanup()


def test_chiptune_settings_wait_for_the_checkbox(qapp):
    """Полтора десятка полей Chiptune показываются только при включённом."""
    tab = _tab(qapp)
    try:
        assert not tab.box_chiptune.isVisibleTo(tab)
        tab.chk_chiptune.setChecked(True)
        assert tab.box_chiptune.isVisibleTo(tab)
        tab.chk_chiptune.setChecked(False)
        assert not tab.box_chiptune.isVisibleTo(tab)
        # Сохранённые настройки тоже открывают коробку.
        tab.chk_chiptune.setChecked(True)
        saved = tab.get_settings()
        tab.chk_chiptune.setChecked(False)
        tab.apply_settings(saved)
        assert tab.box_chiptune.isVisibleTo(tab)
    finally:
        tab.cleanup()


def test_character_difficulty_lives_under_its_own_checkbox(qapp):
    """Сложность персонажей стоит в группе «Аниме», рядом с общей рамкой.

    Так просил пользователь: все рамки сложности — одним местом, а не
    россыпью по панели. Показывается она только при включённых персонажах."""
    tab = _tab(qapp)
    try:
        label, bar = tab._level_blocks["chars"]
        assert bar is tab.char_level_range
        assert bar.avg_control is tab.sp_char_avg
        assert bar.parent() is tab.settings_columns._groups[2]
        assert tab.sp_char_level_from.parent() is tab.char_level_range
        assert tab.sp_char_level_to.parent() is tab.char_level_range
        assert not bar.isVisibleTo(tab)
        assert not tab.box_chars.isVisibleTo(tab)
        tab.chk_chars.setChecked(True)
        assert tab.box_chars.isVisibleTo(tab)
        assert bar.isVisibleTo(tab)
        tab.sp_char_level_from.setValue(3)
        tab.sp_char_level_to.setValue(7)
        tab.sp_char_avg.setValue(5)
        settings = tab.collect()
        assert (settings.char_level_min, settings.char_level_max) == (3, 7)
        assert settings.char_level_avg == 5
        saved = tab.get_settings()
        tab.sp_char_level_to.setValue(10)
        tab.apply_settings(saved)
        assert tab.sp_char_level_to.value() == 7
    finally:
        tab.cleanup()


def test_character_bounds_are_checked_after_the_hero_is_picked(tmp_path):
    """Отдельная рамка персонажей проверяет уровень их тайтла."""
    from test_animepack_new_kinds import make_anime

    def candidate(viewers, favorites):
        anime = make_anime(
            airedOn={"year": 2024},
            statusesStats=[{"status": "completed", "count": viewers}],
        )
        cand = ap.SongCandidate(song={}, anime=anime, kind=ap.CHAR_KIND)
        cand.character = {"id": 1, "russian": "Лайт"}
        cand.char_favorites = favorites
        return cand

    known, obscure = candidate(200_000, 0), candidate(100, 9_000)
    assert known.char_level < obscure.char_level
    assert candidate(100, 0).char_level == candidate(100, 9_000).char_level

    def fits(cand, low, high):
        # Рамка рода вопросов проверяется в отборе (_level_ok); средняя
        # персонажей (_char_level_fits) от рамки не зависит.
        from si_hyx_parts.animepack.generator_selection import _level_ok
        settings = ap.PackSettings(char_level_min=low, char_level_max=high)
        return _level_ok(settings, cand, ap.CHAR_KIND)

    assert fits(known, known.char_level, known.char_level)
    assert not fits(obscure, known.char_level, known.char_level)
    # Рамка по умолчанию пускает кого угодно.
    assert (fits(obscure, 1, ap.MAX_LEVEL)
            and fits(known, 1, ap.MAX_LEVEL))
