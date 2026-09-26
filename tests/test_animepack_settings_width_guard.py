# -*- coding: utf-8 -*-
"""Ни одна галочка настроек не имеет права схлопнуть колонки.

Раскрытая вложенная коробка шире колонки — и SettingsColumns честно
отступает к меньшему числу колонок: панель настроек растягивается одной
колонкой на всё окно. Так было с «Мангой» (галочка Gemini и модель в одну
строку) и с «Каверами» (рамка схожести на три колонки сетки). Тест
перебирает КАЖДУЮ галочку панели, поодиночке и все разом.
"""
import pytest
from PyQt6.QtWidgets import QCheckBox

animepack_tab = pytest.importorskip("animepack_tab")

WIDTH, HEIGHT = 1600, 900


@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab()
    widget.resize(WIDTH, HEIGHT)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.cleanup()


def _checks(tab):
    return [chk for chk in tab.settings_columns.findChildren(QCheckBox)
            if chk.isEnabled()]


def _settle(tab, qapp):
    qapp.processEvents()
    tab._fit_settings_width()
    qapp.processEvents()


def _widest(tab):
    groups = tab.settings_columns._groups
    return {group.title(): group.minimumSizeHint().width() for group in groups}


def test_no_single_checkbox_collapses_columns(tab, qapp):
    columns = tab.settings_columns._columns
    base = _widest(tab)
    assert columns > 1
    broken = []
    for chk in _checks(tab):
        was = chk.isChecked()
        chk.setChecked(not was)
        _settle(tab, qapp)
        if tab.settings_columns._columns < columns:
            broken.append((chk.text(), _widest(tab)))
        chk.setChecked(was)
        _settle(tab, qapp)
    assert not broken, f"база {base}; ломают колонки: {broken}"


def test_all_checkboxes_on_keep_columns(tab, qapp):
    columns = tab.settings_columns._columns
    # Режим «по спискам людей» с парой карточек — тоже часть «всего сразу».
    tab.chk_random.setChecked(False)
    tab.chk_random_shiki.setChecked(False)
    tab._add_user_card()
    tab._add_user_card()
    # Несколько проходов: часть галочек появляется только внутри раскрытых
    # коробок.
    for _ in range(3):
        for chk in _checks(tab):
            chk.setChecked(True)
        _settle(tab, qapp)
    assert tab.settings_columns._columns == columns, _widest(tab)
