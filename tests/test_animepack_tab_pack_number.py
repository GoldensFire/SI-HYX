# -*- coding: utf-8 -*-
"""Номер пака после остановки и падения генерации (просьба пользователя).

Живая жалоба: нажатие «Стоп» роняло программу с
`AttributeError: 'AnimePackTab' object has no attribute '_release_pack_number'`.
Метод был написан, но не перечислен в теле класса — то есть его просто не
существовало у вкладки (см. CLAUDE.md: методы подключаются явными импортами).
"""
import animepack_tab


def _tab(qapp):
    return animepack_tab.AnimePackTab()


def test_the_tab_really_has_the_number_release(qapp):
    """Метод подключён к классу, а не только написан в модуле-части."""
    tab = _tab(qapp)
    try:
        assert callable(getattr(tab, "_release_pack_number", None))
    finally:
        tab.cleanup()


def test_a_cancelled_run_gives_its_number_back(qapp):
    tab = _tab(qapp)
    try:
        tab._pack_number = 4
        tab._release_pack_number(4)
        assert tab._pack_number == 3
        # Чужой номер (человек сменил его руками, пока шла генерация) не трогаем.
        tab._pack_number = 9
        tab._release_pack_number(4)
        assert tab._pack_number == 9
    finally:
        tab.cleanup()


def test_a_stopped_run_does_not_crash(qapp):
    """Полный путь «Стоп» → отменённый результат: раньше здесь падало."""
    class _Result:
        cancelled = True
        path = ""
        songs = ()
        requested = 10
        elapsed = 1.0
        pack_number = 4

    tab = _tab(qapp)
    try:
        tab._pack_number = 4
        tab._on_finished(_Result())
        assert tab._pack_number == 3
    finally:
        tab.cleanup()
