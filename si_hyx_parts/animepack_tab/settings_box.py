# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Коробка настроек, высота которой НЕ пересчитывается от ширины.

Зачем понадобился свой класс. Настройки рода вопросов лежат в коробке под
своей галочкой, а коробки — строками одной QGridLayout группы «Состав пака».
Внутри коробок есть подписи с переносом слов, а такая подпись объявляет
heightForWidth — и объявляет его вся коробка следом за ней.

Дальше начинается беда самой QGridLayout: строку с heightForWidth она считает
ТОЛЬКО по этому числу, а минимальную высоту виджета в такой строке не смотрит
вовсе (`setupHfwLayoutData` обнуляет минимум строки и заменяет его на hfw).
Стоило раскрыть Chiptune или каверы — и коробка песен получала строку прежней,
«свёрнутой» высоты, а сама оставалась раскрытой: настройки Chiptune рисовались
поверх галочек «Кадры», «Персонажи», «Манга» и дальше по списку.

Поэтому коробка настроек heightForWidth не объявляет вовсе, а нужную высоту
отдаёт обычным sizeHint — с уже учтённым переносом подписей при своей нынешней
ширине. Строка тогда считается по минимуму и по sizeHint, как у всех остальных
виджетов, и накладок не остаётся. Сами подписи переносить слова не перестают:
у них heightForWidth как был, так и есть.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QWidget


def needed_height(widget: QWidget) -> int:
    """Высота, при которой содержимое виджета помещается целиком.

    Раскладка считает свой минимум без полей САМОГО виджета: у QGroupBox это
    место под заголовок. Без них минимум выходил меньше настоящего, а нехватку
    высоты QGridLayout разбирает накладкой строк друг на друга."""
    layout = widget.layout()
    hint = widget.sizeHint().height()
    if layout is None:
        return hint
    margins = widget.contentsMargins()
    extra = margins.top() + margins.bottom()
    return max(hint, layout.minimumSize().height() + extra,
               layout.sizeHint().height() + extra)


class SettingsBox(QWidget):
    """Контейнер настроек: высота от содержимого, а не от ширины."""

    def hasHeightForWidth(self) -> bool:  # noqa: N802 — имя из Qt
        return False

    def heightForWidth(self, width: int) -> int:  # noqa: N802 — имя из Qt
        return -1

    def _with_wrapped(self, size: QSize) -> QSize:
        layout = self.layout()
        if layout is None or not layout.hasHeightForWidth():
            return size
        # Ширина берётся своя нынешняя: колонка настроек её и задаёт, а к
        # моменту вопроса о высоте она уже выставлена.
        wrapped = layout.totalHeightForWidth(max(1, self.width()))
        return QSize(size.width(), max(size.height(), wrapped))

    def sizeHint(self) -> QSize:  # noqa: N802 — имя из Qt
        return self._with_wrapped(QWidget.sizeHint(self))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 — имя из Qt
        base = QWidget.minimumSizeHint(self)
        return QSize(base.width(), max(base.height(), self.sizeHint().height()))
