# -*- coding: utf-8 -*-
"""Подсказка (_InfoTipPopup) не должна вылезать за край экрана.

Кнопка у нижнего края окна (панель действий над таблицей паков) показывала
длинную подсказку ВНИЗ — и та уезжала под панель задач: по вертикали положение
вообще не проверялось, а высоту попапа со словопереносом adjustSize() занижал.
"""
import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QPushButton

LONG = ("Удалить сыгранные и из чёрного списка\n\n"
        "Удаляет с диска скачанные .siq и медиа ВСЕХ паков, которые отмечены "
        "как сыгранные, лежат в чёрном списке пакетов или все авторы которых "
        "в чёрном списке авторов. Статистика в базе остаётся — паки не "
        "пропадут из списков.")


@pytest.fixture
def tip(qapp):
    from widgets import _InfoTipPopup
    t = _InfoTipPopup.instance()
    yield t
    t.hide()


def _screen_rect():
    return QApplication.primaryScreen().availableGeometry()


def _fits(t):
    sg = _screen_rect()
    return (t.y() >= sg.top() and t.y() + t.height() <= sg.bottom()
            and t.x() >= sg.left() and t.x() + t.width() <= sg.right())


def test_height_matches_the_wrapped_text(tip):
    """Высота попапа считается по РЕАЛЬНОЙ ширине: по заниженной высоте вылет
    за нижний край экрана и не замечался."""
    tip._fit_size(LONG)
    assert tip.height() >= tip.heightForWidth(tip.width())


def test_tip_at_the_bottom_of_the_screen_flips_up(tip, qapp):
    sg = _screen_rect()
    btn = QPushButton("кнопка")
    btn.resize(36, 30)
    btn.move(sg.left() + 40, sg.bottom() - 40)
    btn.show()
    try:
        tip.show_for(btn, LONG)
        assert _fits(tip), "подсказка вылезла за пределы экрана"
        # Именно НАД кнопкой, а не поверх неё.
        assert tip.y() + tip.height() <= btn.mapToGlobal(btn.rect().topLeft()).y()
    finally:
        btn.hide()
        btn.deleteLater()


def test_tip_at_the_corner_stays_on_screen(tip):
    sg = _screen_rect()
    tip.show_at(QPoint(sg.right() - 5, sg.bottom() - 5), LONG)
    assert _fits(tip)


def test_normal_position_is_below_the_widget(tip, qapp):
    """Обычный случай не трогаем: подсказка по-прежнему под виджетом."""
    sg = _screen_rect()
    btn = QPushButton("кнопка")
    btn.resize(36, 30)
    btn.move(sg.left() + 40, sg.top() + 40)
    btn.show()
    try:
        tip.show_for(btn, "коротко")
        assert tip.y() >= btn.mapToGlobal(btn.rect().bottomLeft()).y()
        assert _fits(tip)
    finally:
        btn.hide()
        btn.deleteLater()
