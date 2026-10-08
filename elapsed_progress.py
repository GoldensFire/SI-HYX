"""Shared progress display with elapsed time and outlined text."""
from __future__ import annotations

import re
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QProgressBar, QStyle, QStyleOptionProgressBar


# Цвета подписи: время — акцентом, имя файла в конце (после «·») — приглушённо.
_TEXT_COLOR = QColor("#f5f5ff")
_TIME_COLOR = QColor("#f9e2af")
_FILE_COLOR = QColor(186, 194, 222, 205)
_OUTLINE = QColor(17, 17, 27, 150)
_SHADOW = QColor(0, 0, 0, 90)
_FILE_TAIL = re.compile(r"\.\w{2,5}$")
# Справа в полосе лежит кнопка папки: поля текста одинаковые с обеих сторон,
# чтобы подпись оставалась ровно по центру полосы.
_SIDE_ROOM = 28

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
        self._status = "Ожидание"
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

    def _segments(self):
        """[(текст, цвет)] подписи: «(06:31)», статус и приглушённое имя файла."""
        text = self._display_text()
        out = []
        match = re.match(r"^(\(\d[\d:]*\))\s", text)
        if match:
            out.append((match.group(1), _TIME_COLOR))
            text = " " + text[match.end():]
        head, sep, tail = text.rpartition(" · ")
        if sep and _FILE_TAIL.search(tail.strip()):
            out.append((head + sep, _TEXT_COLOR))
            out.append((tail, _FILE_COLOR))
        else:
            out.append((text, _TEXT_COLOR))
        return out

    def paintEvent(self, event):
        option = QStyleOptionProgressBar()
        self.initStyleOption(option)
        option.textVisible = False
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_ProgressBar,
                                 option, painter, self)
        if not self.isTextVisible():
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
        whole = QPainterPath()
        for path, _ in paths:
            whole.addPath(path)
        bounds = whole.boundingRect()
        dx = rect.center().x() - (x / 2.0)
        dy = rect.center().y() - bounds.center().y()
        painter.setClipRect(rect)
        pen = QPen(_OUTLINE, 1.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        for path, color in paths:
            path.translate(dx, dy)
            # Мягкая тень вниз и тонкий тёмный контур вместо толстой обводки.
            painter.fillPath(path.translated(0, 1.2), _SHADOW)
            painter.strokePath(path, pen)
            painter.fillPath(path, color)
