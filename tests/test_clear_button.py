# -*- coding: utf-8 -*-
"""Крестик «очистить» в полях ввода: его ставит глобальный HoverTipManager, а не
каждый вызов setClearButtonEnabled руками (widgets._enable_clear_button)."""
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox,
                             QTableWidget, QWidget)

import widgets


def test_plain_field_gets_the_button(qapp):
    ed = QLineEdit()
    widgets._enable_clear_button(ed)
    assert ed.isClearButtonEnabled()


def test_read_only_field_is_left_alone(qapp):
    """Стирать нечего — крестик только мешал бы."""
    ed = QLineEdit()
    ed.setReadOnly(True)
    widgets._enable_clear_button(ed)
    assert not ed.isClearButtonEnabled()


def test_password_field_is_left_alone(qapp):
    ed = QLineEdit()
    ed.setEchoMode(QLineEdit.EchoMode.Password)
    widgets._enable_clear_button(ed)
    assert not ed.isClearButtonEnabled()


def test_spinbox_inner_field_is_left_alone(qapp):
    """У счётчика свои стрелки — крестик влез бы прямо в них."""
    for box in (QSpinBox(), QDoubleSpinBox()):
        widgets._enable_clear_button(box.lineEdit())
        assert not box.lineEdit().isClearButtonEnabled()


def test_editable_combo_field_is_left_alone(qapp):
    combo = QComboBox()
    combo.setEditable(True)
    widgets._enable_clear_button(combo.lineEdit())
    assert not combo.lineEdit().isClearButtonEnabled()


def test_cell_editor_is_left_alone(qapp):
    """Редактор ячейки таблицы живёт на её viewport'е: правку завершают
    Enter/Esc, крестик там лишний."""
    table = QTableWidget(1, 1)
    ed = QLineEdit(table.viewport())
    widgets._enable_clear_button(ed)
    assert not ed.isClearButtonEnabled()


def test_manager_reacts_to_polish(qapp):
    """Проверка сквозного пути: фильтр приложения ловит Polish обычного поля."""
    from PyQt6.QtCore import QEvent
    mgr = widgets.HoverTipManager()
    parent = QWidget()
    ed = QLineEdit(parent)
    mgr.eventFilter(ed, QEvent(QEvent.Type.Polish))
    assert ed.isClearButtonEnabled()
