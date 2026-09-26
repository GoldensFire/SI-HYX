# -*- coding: utf-8 -*-
"""Ctrl+F в консоли — как в браузере: подсветка, счётчик, стрелки, Esc."""
import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QTextEdit

from si_hyx_parts.main.console_search import install_search


# Виджеты тестов не удаляем до конца сессии: удалённая посреди чужих тестов
# консоль роняла процесс в их processEvents (access violation). В программе
# консоль живёт всё время работы окна.
_KEEP = []


@pytest.fixture
def console(qapp):
    edit = QTextEdit()
    edit.setReadOnly(True)
    edit.resize(600, 300)
    edit.setPlainText("\n".join(
        ["[1] Аниме-пак: старт", "[2] кадр готов", "[3] Кадр не скачался",
         "[4] персонаж", "[5] КАДР с эффектом"]))
    install_search(edit)
    edit.show()
    yield edit
    edit.hide()
    _KEEP.append(edit)


def _key(widget, key, mods=Qt.KeyboardModifier.NoModifier, vk=0, text=""):
    for kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
        QApplication.sendEvent(widget, QKeyEvent(kind, key, mods, 0, vk, 0, text))


def test_ctrl_f_on_russian_layout_opens_the_bar(console):
    bar = console._console_find_bar
    # Русская раскладка: буква «А», но виртуальная клавиша — F.
    _key(console, 0x0410, Qt.KeyboardModifier.ControlModifier,
         vk=0x46, text="а")
    assert bar.isVisible()


def test_all_matches_are_highlighted_and_counted(console):
    bar = console._console_find_bar
    bar.open_bar()
    bar.field.setText("кадр")               # без учёта регистра
    assert len(bar.matches) == 3
    assert bar.counter.text() == "1 из 3"
    assert len(console.extraSelections()) == 3
    _key(bar.field, Qt.Key.Key_Return)
    assert bar.counter.text() == "2 из 3"
    _key(bar.field, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    _key(bar.field, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert bar.counter.text() == "3 из 3"   # по кругу, как в браузере
    # Курсор стоит на текущем совпадении — туда и прокручено.
    assert console.textCursor().position() == bar.matches[2][0]


def test_counter_follows_the_growing_log_and_esc_clears(console):
    bar = console._console_find_bar
    bar.open_bar()
    bar.field.setText("кадр")
    console.append("[6] ещё кадр")
    bar.refresh(keep=True)                  # то же делает таймер
    assert bar.counter.text().endswith("из 4")
    bar.field.setText("нет такого")
    assert bar.counter.text() == "0 из 0"
    assert console.extraSelections() == []
    _key(bar.field, Qt.Key.Key_Escape)
    assert not bar.isVisible()
    assert console.extraSelections() == []
