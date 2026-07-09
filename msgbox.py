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
from PyQt6.QtWidgets import QMessageBox


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
