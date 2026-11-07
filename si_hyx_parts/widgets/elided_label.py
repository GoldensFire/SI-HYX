# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ElidedLabel. Public namespace: widgets."""
import widgets as _api


class ElidedLabel(_api.QLabel):
    """Подпись в одну строку: длинный текст сокращается «…» посередине по
    реальной ширине подписи. Раньше имя файла резалось до последних 27
    символов («…s OVA 1 [BDRemux 1080p].mkv»), а путь — до 210 px по шрифту
    без стилей, хотя место в подписи оставалось. Ширину берёт у панели и сама
    её не распирает: в ряду с кнопками отдаёт им место первой."""

    def __init__(self, text=""):
        super().__init__(text)
        self._full_text = None
        self.setTextFormat(_api.Qt.TextFormat.PlainText)
        self.setSizePolicy(_api.QSizePolicy.Policy.Ignored,
                           _api.QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(1)

    def set_full_text(self, text):
        self._full_text = str(text)
        self.ensurePolished()      # размер шрифта из styleSheet — до замера
        self._elide_full_text()

    def clear_full_text(self, text):
        self._full_text = None
        self.setText(text)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._elide_full_text()

    def _elide_full_text(self):
        if self._full_text is None:
            return
        width = max(0, self.contentsRect().width())
        self.setText(self.fontMetrics().elidedText(
            self._full_text, _api.Qt.TextElideMode.ElideMiddle, width))
