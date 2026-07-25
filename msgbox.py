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


def _center_over_parent(box, parent):
    # Qt НЕ центрирует QDialog/QMessageBox над родителем сам по себе на Windows —
    # без этого диалог всплывал там, где ОС решит (по факту — в левом верхнем
    # углу экрана), а не над окном, с которым реально работает пользователь.
    # Берём activeWindow() (а не сразу parent.window()) — action-методы вроде
    # «Удалить пак» общие для главного окна и отдельного окна тир-листа, и
    # передают в качестве parent саму вкладку (часть ГЛАВНОГО окна) всегда;
    # без этого предупреждение из тир-листа центрировалось бы над главным
    # окном где-то позади, а не над окном, которое реально видит пользователь.
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
    # copyable=True добавляет кнопку «Копировать» (текст ошибки — в буфер обмена,
    # для багрепортов). У QMessageBox нет штатного способа оставить диалог
    # открытым после клика по кнопке (закрывается ЛЮБАЯ, включая ActionRole) —
    # поэтому копирование переоткрывает то же окно вместо закрытия.
    while True:
        box = QMessageBox(parent)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.setStandardButtons(buttons)
        if default_button is not None:
            box.setDefaultButton(default_button)
        copy_btn = box.addButton("Копировать", QMessageBox.ButtonRole.ActionRole) if copyable else None
        _center_over_parent(box, parent)
        box.exec()
        clicked = box.clickedButton()
        if copyable and clicked is copy_btn:
            QGuiApplication.clipboard().setText(text)
            continue
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
