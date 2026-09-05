# -*- coding: utf-8 -*-
"""Залипшее выделение в счётчиках. Два разных случая, оба чинит глобальный
HoverTipManager:

  • колесо над НЕсфокусированным спинбоксом: Qt выделяет весь текст в stepBy, а
    фокус полю не отдаёт (проверено на живом окне: после колеса hasFocus=False),
    поэтому выделение висело синим, пока не кликнешь в само поле —
    _drop_wheel_selection;
  • поле сфокусировано (кликнули внутрь), а клик по «пустому» месту окна фокус
    не забирает — _release_spinbox_focus.
"""
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget

import widgets


class _Spin(QSpinBox):
    """Спинбокс, который запоминает, снимали ли с него фокус."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cleared = False

    def clearFocus(self):
        self.cleared = True
        super().clearFocus()


@pytest.fixture
def form(qapp, monkeypatch):
    """Окошко «спинбокс + пустая область» с подменённым «текущим фокусом»:
    настоящий фокус в тестах без показанного активного окна не выставить."""
    page = QWidget()
    lay = QVBoxLayout(page)
    spin = _Spin(page)
    empty = QLabel("пустая область", page)
    lay.addWidget(spin)
    lay.addWidget(empty)
    monkeypatch.setattr(
        widgets, "QApplication",
        SimpleNamespace(instance=lambda: SimpleNamespace(focusWidget=lambda: spin)),
        raising=True)
    return SimpleNamespace(page=page, spin=spin, empty=empty)


def test_click_outside_releases_spinbox(form):
    widgets.HoverTipManager._release_spinbox_focus(form.empty)
    assert form.spin.cleared


def test_click_on_spinbox_keeps_focus(form):
    widgets.HoverTipManager._release_spinbox_focus(form.spin)
    assert not form.spin.cleared


def test_click_on_spinbox_child_keeps_focus(form):
    """Поле ввода и стрелки — потомки спинбокса; терять фокус от клика по
    ним было бы хуже исходной проблемы."""
    widgets.HoverTipManager._release_spinbox_focus(form.spin.lineEdit())
    assert not form.spin.cleared


def test_non_spinbox_focus_is_left_alone(qapp, monkeypatch):
    """Обычное текстовое поле фокус по клику мимо не теряет — там выделение
    ставит сам пользователь, а не колесо."""
    ed = QLineEdit()
    ed.setText("текст")
    ed.selectAll()
    monkeypatch.setattr(
        widgets, "QApplication",
        SimpleNamespace(instance=lambda: SimpleNamespace(focusWidget=lambda: ed)),
        raising=True)
    widgets.HoverTipManager._release_spinbox_focus(QLabel("мимо"))
    assert ed.selectedText() == "текст"


def test_non_widget_object_does_not_crash(form):
    """Фильтр стоит на всём приложении и получает события не только виджетов."""
    widgets.HoverTipManager._release_spinbox_focus(object())
    assert form.spin.cleared  # клик «вне» спинбокса — фокус снят


def test_manager_reacts_to_mouse_press(form):
    """Сквозной путь: фильтр приложения ловит нажатие мыши мимо счётчика."""
    mgr = widgets.HoverTipManager()
    mgr.eventFilter(form.empty, QEvent(QEvent.Type.MouseButtonPress))
    assert form.spin.cleared


# ── Колесо над НЕсфокусированным счётчиком ─────────────────────────────────

class _FocusedSpin(QSpinBox):
    """Спинбокс «с фокусом»: настоящий фокус в тестах без активного окна не
    выставить, а решение целиком зависит от hasFocus()."""
    def hasFocus(self):
        return True


def _wheeled(qapp, spin):
    """Имитирует то, что делает Qt при шаге колеса: значение + выделение."""
    spin.setValue(spin.value() + 1)
    spin.lineEdit().selectAll()
    widgets.HoverTipManager._drop_wheel_selection(spin)
    qapp.processEvents()          # снятие выделения отложено на singleShot(0)
    return spin.lineEdit().selectedText()


def test_wheel_selection_dropped_when_unfocused(qapp):
    spin = QSpinBox()
    spin.setRange(0, 63)
    spin.setValue(41)
    assert _wheeled(qapp, spin) == ""
    assert spin.value() == 42      # значение колесо менять обязано


def test_wheel_selection_kept_when_focused(qapp):
    """В поле работают руками — выделение осмысленно (набор заменит значение)."""
    spin = _FocusedSpin()
    spin.setRange(0, 63)
    spin.setValue(41)
    assert _wheeled(qapp, spin) == "42"


def test_wheel_over_inner_line_edit_counts(qapp):
    """Колесо приходит и потомкам спинбокса — поле ввода, стрелки."""
    spin = QSpinBox()
    spin.setValue(7)
    spin.lineEdit().selectAll()
    widgets.HoverTipManager._drop_wheel_selection(spin.lineEdit())
    qapp.processEvents()
    assert spin.lineEdit().selectedText() == ""


def test_wheel_over_non_spinbox_is_ignored(qapp):
    """Над обычным полем ввода выделение ставит пользователь — не трогаем."""
    ed = QLineEdit()
    ed.setText("текст")
    ed.selectAll()
    widgets.HoverTipManager._drop_wheel_selection(ed)
    qapp.processEvents()
    assert ed.selectedText() == "текст"


def test_manager_reacts_to_wheel(qapp):
    """Сквозной путь: фильтр приложения ловит колесо над счётчиком."""
    spin = QSpinBox()
    spin.setValue(3)
    spin.lineEdit().selectAll()
    mgr = widgets.HoverTipManager()
    mgr.eventFilter(spin, QEvent(QEvent.Type.Wheel))
    qapp.processEvents()
    assert spin.lineEdit().selectedText() == ""
