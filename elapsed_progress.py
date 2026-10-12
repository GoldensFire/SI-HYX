"""Shared progress display with elapsed time and outlined text."""
from __future__ import annotations

import re
import time

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QProgressBar, QStyle, QStyleOptionProgressBar


# Подпись всегда белая с тонкой тёмной обводкой: читается и на пустой полосе,
# и поверх заливки любого цвета (просьба пользователя).
_TEXT_COLOR = QColor("#ffffff")
_OUTLINE = QColor(10, 10, 18, 210)
_TIME_PREFIX = re.compile(r"^\(\d[\d:]*\)\s*")
_FILE_TAIL = re.compile(r"\.\w{2,5}$")
# Справа в полосе лежит кнопка папки: поля текста одинаковые с обеих сторон,
# чтобы подпись оставалась ровно по центру полосы.
_SIDE_ROOM = 28

# В простое полоса пустая: «Ожидание» в ней ничего не сообщает.
_IDLE_TEXT = ("", "ожидание")
_FINISHED_TEXT = ("ожидание", "готово", "ошибка", "отменено", "остановлено",
                  "не получилось", "файл удалён", "частичный пак")


def elapsed_text(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class ElapsedProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._started_at = None
        self._elapsed = 0.0
        self._status = ""
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh_text)

    def set_progress(self, value, text, *, started_at=None, running=None):
        self._status = str(text or "")
        busy = value is None or value < 0
        if running is None:
            running = ((busy or value < 100)
                       and not self._status.casefold().startswith(_FINISHED_TEXT))
        if running:
            if not self._timer.isActive() or (
                    started_at is not None and started_at != self._started_at):
                self._started_at = time.monotonic() if started_at is None else started_at
                self._elapsed = 0.0
                self._timer.start()
        else:
            if self._timer.isActive():
                self._elapsed = time.monotonic() - self._started_at
            self._timer.stop()
            if self._status.casefold() == "ожидание":
                self._started_at = None
        self.setRange(0, 0 if busy else 100)
        if not busy:
            self.setValue(value)
        self._refresh_text()

    def _refresh_text(self):
        if self._timer.isActive():
            self._elapsed = time.monotonic() - self._started_at
        prefix = f"({elapsed_text(self._elapsed)}) " if self._started_at is not None else ""
        self.setFormat(prefix + self._status)
        self.setToolTip(self._display_text())
        self.update()

    def _display_text(self):
        total = self.maximum() - self.minimum()
        percent = max(0, (self.value() - self.minimum()) * 100 // total) if total else 0
        return (self.format().replace("%p", str(percent))
                .replace("%v", str(self.value())).replace("%m", str(total)))

    def _idle(self):
        text = _TIME_PREFIX.sub("", self._display_text())
        return text.strip().rstrip(".…").casefold() in _IDLE_TEXT

    def _segments(self):
        """[(текст, цвет)] подписи; имя файла в конце (после «·») — отдельным
        куском: если строка не влезает, ужимается сначала оно."""
        text = self._display_text()
        head, sep, tail = text.rpartition(" · ")
        if sep and _FILE_TAIL.search(tail.strip()):
            return [(head + sep, _TEXT_COLOR), (tail, _TEXT_COLOR)]
        return [(text, _TEXT_COLOR)]

    def paintEvent(self, event):
        option = QStyleOptionProgressBar()
        self.initStyleOption(option)
        option.textVisible = False
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_ProgressBar,
                                 option, painter, self)
        if not self.isTextVisible() or self._idle():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rect = self.rect().adjusted(_SIDE_ROOM, 2, -_SIDE_ROOM, -2)
        if rect.width() <= 0:
            return
        font = self.font()
        metrics = QFontMetricsF(font)
        segments = self._segments()
        room = rect.width() - 2
        widths = [metrics.horizontalAdvance(t) for t, _ in segments]
        if sum(widths) > room:
            # Не влезает — сначала ужимаем имя файла, затем всю строку.
            last, color = segments[-1]
            rest = sum(widths[:-1])
            if len(segments) > 1 and room - rest > metrics.horizontalAdvance("…") * 3:
                segments[-1] = (metrics.elidedText(last, Qt.TextElideMode.ElideRight,
                                                   room - rest), color)
            else:
                whole = "".join(t for t, _ in segments)
                segments = [(metrics.elidedText(whole, Qt.TextElideMode.ElideRight,
                                                room), _TEXT_COLOR)]
        paths, x = [], 0.0
        for text, color in segments:
            path = QPainterPath()
            path.addText(x, 0, font, text)
            paths.append((path, color))
            x += metrics.horizontalAdvance(text)
        # Центр — по дробной середине полосы и по высоте ЗАГЛАВНЫХ букв, а не
        # по рамке набранного текста: у QRect.center() целочисленное деление
        # поднимало подпись на пиксель, а рамка текста зависит от букв
        # («д», «у» с хвостами тянули её вверх).
        center = QRectF(self.rect()).center()
        dx = center.x() - (x / 2.0)
        dy = center.y() + metrics.capHeight() / 2.0
        painter.setClipRect(rect)
        # Перо шириной 2 видно снаружи буквы на 1 пиксель: заливка ложится
        # поверх его внутренней половины.
        pen = QPen(_OUTLINE, 2.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        for path, color in paths:
            path.translate(dx, dy)
            painter.strokePath(path, pen)
            painter.fillPath(path, color)
