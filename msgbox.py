# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# msgbox.py — обёртки над QMessageBox.critical/warning/information/question,
# делающие текст диалога выделяемым мышью и копируемым (Ctrl+C), в отличие от
# стандартных статических методов QMessageBox.

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QMessageBox


class _CopyableBox(QMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.copy_button = None
        self._copy_requested = False
        self.buttonClicked.connect(self._remember_click)

    def _remember_click(self, button):
        self._copy_requested = button is self.copy_button

    def done(self, result):
        if self._copy_requested:
            self._copy_requested = False
            QGuiApplication.clipboard().setText(self.text())
            return
        super().done(result)


def _center_over_parent(box, parent):
    # Qt НЕ центрирует QDialog/QMessageBox над родителем сам по себе на Windows —
    # без этого диалог всплывал там, где ОС решит (по факту — в левом верхнем
    # углу экрана), а не над окном, с которым реально работает пользователь.
    # Берём activeWindow() (а не сразу parent.window()) — общие action-методы
    # вкладок передают в качестве parent саму вкладку (часть ГЛАВНОГО окна)
    # даже когда вызваны из отдельного окна; без этого предупреждение
    # центрировалось бы над главным окном где-то позади, а не над окном,
    # которое реально видит пользователь.
    box.adjustSize()
    active = QApplication.activeWindow()
    top = active if (active is not None and active.isVisible()) \
        else (parent.window() if parent is not None else None)
    if top is not None and top.isVisible():
        center = top.frameGeometry().center()
    else:
        screen = QGuiApplication.primaryScreen()
        center = screen.availableGeometry().center() if screen else None
    if center is not None:
        geo = box.frameGeometry()
        geo.moveCenter(center)
        box.move(geo.topLeft())


def _selectable_box(icon, parent, title, text, buttons, default_button, copyable=False):
    box = _CopyableBox(parent) if copyable else QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.setStandardButtons(buttons)
    if default_button is not None:
        box.setDefaultButton(default_button)
    if copyable:
        box.copy_button = box.addButton('Копировать', QMessageBox.ButtonRole.ActionRole)
        box.copy_button.setAutoDefault(False)
    _center_over_parent(box, parent)
    box.exec()
    clicked = box.clickedButton()
    return box.standardButton(clicked) if clicked is not None else QMessageBox.StandardButton.NoButton


def msgbox_critical(parent, title, text,
                     buttons=QMessageBox.StandardButton.Ok,
                     defaultButton=QMessageBox.StandardButton.NoButton):
    return _selectable_box(QMessageBox.Icon.Critical, parent, title, text, buttons, defaultButton, copyable=True)


def msgbox_warning(parent, title, text,
                    buttons=QMessageBox.StandardButton.Ok,
                    defaultButton=QMessageBox.StandardButton.NoButton):
    return _selectable_box(QMessageBox.Icon.Warning, parent, title, text, buttons, defaultButton, copyable=True)


def msgbox_information(parent, title, text,
                        buttons=QMessageBox.StandardButton.Ok,
                        defaultButton=QMessageBox.StandardButton.NoButton):
    return _selectable_box(QMessageBox.Icon.Information, parent, title, text, buttons, defaultButton)


def msgbox_question(parent, title, text,
                     buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                     defaultButton=QMessageBox.StandardButton.NoButton):
    return _selectable_box(QMessageBox.Icon.Question, parent, title, text, buttons, defaultButton)
