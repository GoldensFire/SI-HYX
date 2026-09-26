# -*- coding: utf-8 -*-
"""Панель поиска по консоли — как Ctrl+F в браузере.

Плашка в правом верхнем углу консоли: поле, счётчик «3 из 17», стрелки
вверх/вниз и крестик. Все совпадения подсвечиваются сразу, текущее — ярче;
Enter — следующее, Shift+Enter — предыдущее, Esc — закрыть. Регистр не
учитывается. Лог продолжает писаться во время поиска — подсветка и счётчик
пересчитываются сами (с небольшой задержкой, чтобы не считать на каждую
строку).
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QToolButton,
)

# Больше совпадений не подсвечиваем: тысячи выделений тормозят отрисовку,
# а считать их счётчик продолжает все.
MAX_HIGHLIGHTS = 3000
_ALL = QColor(255, 214, 0, 110)
_CURRENT = QColor(255, 140, 0, 230)
_VK_F = 0x46                              # клавиша F на любой раскладке


class ConsoleFindBar(QFrame):
    """Плашка поиска поверх QTextEdit (у каждой консоли своя)."""

    def __init__(self, edit: QTextEdit):
        super().__init__(edit)
        self.edit = edit
        self.matches: list[tuple[int, int]] = []
        self.current = -1
        self.setObjectName("consoleFindBar")
        self.setStyleSheet(
            "#consoleFindBar{background:#2b2d35; border:1px solid #4a4d5a;"
            " border-radius:6px;}"
            "QLineEdit{background:#1e1f25; border:1px solid #4a4d5a;"
            " border-radius:4px; padding:2px 6px; color:#e8e8ee;}"
            "QLabel{color:#b8bac4; background:transparent; padding:0 4px;}"
            "QToolButton{background:transparent; border:none; color:#e8e8ee;"
            " padding:2px 6px; border-radius:4px;}"
            "QToolButton:hover{background:rgba(255,255,255,0.1);}")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 4, 4)
        row.setSpacing(2)
        self.field = QLineEdit(self)
        self.field.setPlaceholderText("Найти в консоли")
        self.field.setMinimumWidth(200)
        self.field.setClearButtonEnabled(True)
        self.counter = QLabel("", self)
        self.counter.setMinimumWidth(64)
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_prev = self._button("▲", "Предыдущее (Shift+Enter)", self.prev)
        self.btn_next = self._button("▼", "Следующее (Enter)", self.next)
        self.btn_close = self._button("✕", "Закрыть (Esc)", self.close_bar)
        row.addWidget(self.field, 1)
        row.addWidget(self.counter)
        for button in (self.btn_prev, self.btn_next, self.btn_close):
            row.addWidget(button)
        self.field.textChanged.connect(lambda _t: self.refresh(keep=False))
        self.field.installEventFilter(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(lambda: self.refresh(keep=True))
        self._doc = None
        self._watch_document()
        edit.installEventFilter(self)
        self.hide()

    def _button(self, text: str, tip: str, slot) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    def _watch_document(self) -> None:
        """Документ у большой консоли подменяется (setDocument) — следим."""
        doc = self.edit.document()
        if doc is self._doc:
            return
        if self._doc is not None:
            try:
                self._doc.contentsChanged.disconnect(self._on_changed)
            except (TypeError, RuntimeError):
                pass
        self._doc = doc
        doc.contentsChanged.connect(self._on_changed)

    # ── показ ─────────────────────────────────────────────────────────
    def open_bar(self) -> None:
        self._watch_document()
        selected = self.edit.textCursor().selectedText().strip()
        if selected and " " not in selected:
            self.field.setText(selected)
        self.show()
        self.raise_()
        self._place()
        self.field.setFocus()
        self.field.selectAll()
        self.refresh(keep=False)

    def close_bar(self) -> None:
        self.hide()
        self.matches, self.current = [], -1
        self.edit.setExtraSelections([])
        self.edit.setFocus()

    def _place(self) -> None:
        self.adjustSize()
        width = min(max(self.sizeHint().width(), 360), max(200, self.edit.width() - 16))
        self.resize(width, self.sizeHint().height())
        bar = self.edit.verticalScrollBar()
        right = bar.width() if bar.isVisible() else 0
        self.move(max(0, self.edit.width() - width - right - 8), 6)

    # ── поиск ─────────────────────────────────────────────────────────
    def _on_changed(self) -> None:
        if self.isVisible() and self.field.text():
            self._timer.start()

    def refresh(self, keep: bool) -> None:
        """Пересчёт совпадений. keep — остаться на том же месте (лог дописался)."""
        query = self.field.text()
        was = self.matches[self.current][0] if 0 <= self.current < len(self.matches) else -1
        self.matches = find_all(self.edit.document(), query)
        if not self.matches:
            self.current = -1
        elif keep and was >= 0:
            self.current = next((i for i, (s, _e) in enumerate(self.matches)
                                 if s >= was), len(self.matches) - 1)
        else:
            self.current = self._nearest()
        self._paint(scroll=not keep)

    def _nearest(self) -> int:
        """Первое совпадение от курсора вниз — как у браузера."""
        pos = self.edit.textCursor().selectionStart()
        return next((i for i, (s, _e) in enumerate(self.matches) if s >= pos), 0)

    def next(self) -> None:
        self._step(1)

    def prev(self) -> None:
        self._step(-1)

    def _step(self, delta: int) -> None:
        if not self.matches:
            self.refresh(keep=False)
            return
        self.current = (self.current + delta) % len(self.matches)
        self._paint(scroll=True)

    def _paint(self, scroll: bool) -> None:
        total = len(self.matches)
        query = self.field.text()
        if not query:
            self.counter.setText("")
        else:
            self.counter.setText(f"{self.current + 1} из {total}" if total
                                 else "0 из 0")
        self.counter.setStyleSheet("color:#ff7b7b;" if query and not total else "")
        self.btn_prev.setEnabled(total > 0)
        self.btn_next.setEnabled(total > 0)
        doc = self.edit.document()
        selections = []
        for index, (start, end) in enumerate(self.matches[:MAX_HIGHLIGHTS]):
            if index != self.current:
                selections.append(_selection(doc, start, end, _ALL))
        if 0 <= self.current < total:
            start, end = self.matches[self.current]
            selections.append(_selection(doc, start, end, _CURRENT))
            if scroll:
                # Курсор ставим БЕЗ выделения: синее выделение перекрыло бы
                # оранжевую подсветку текущего совпадения.
                cursor = QTextCursor(doc)
                cursor.setPosition(start)
                self.edit.setTextCursor(cursor)
                self.edit.ensureCursorVisible()
        self.edit.setExtraSelections(selections)

    # ── клавиши ───────────────────────────────────────────────────────
    def eventFilter(self, obj: QObject, event) -> bool:  # noqa: N802 — имя Qt
        kind = event.type()
        if obj is self.edit:
            if kind == QEvent.Type.Resize and self.isVisible():
                self._place()
            elif kind in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
                if is_find_key(event):
                    if kind == QEvent.Type.KeyPress:
                        self.open_bar()
                    event.accept()
                    return True
                if (kind == QEvent.Type.KeyPress and self.isVisible()
                        and event.key() == Qt.Key.Key_Escape):
                    self.close_bar()
                    return True
                if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_F3:
                    self._f3(event)
                    return True
            return False
        if obj is self.field and kind == QEvent.Type.KeyPress:
            key = event.key()
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.prev() if shift else self.next()
                return True
            if key == Qt.Key.Key_Escape:
                self.close_bar()
                return True
            if key == Qt.Key.Key_F3:
                self._f3(event)
                return True
            if is_find_key(event):
                self.field.selectAll()
                return True
        return False

    def _f3(self, event) -> None:
        if not self.isVisible():
            self.open_bar()
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.prev()
        else:
            self.next()


def is_find_key(event) -> bool:
    """Ctrl+F на любой раскладке: и по букве, и по виртуальной клавише F."""
    if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
        return False
    try:
        vk = int(event.nativeVirtualKey())
    except (AttributeError, TypeError):
        vk = 0
    return event.key() == Qt.Key.Key_F or vk == _VK_F


def find_all(doc: QTextDocument, query: str) -> list[tuple[int, int]]:
    """Все совпадения без учёта регистра: [(начало, конец)]."""
    out: list[tuple[int, int]] = []
    if not query:
        return out
    cursor = QTextCursor(doc)
    while True:
        cursor = doc.find(query, cursor)
        if cursor.isNull():
            return out
        out.append((cursor.selectionStart(), cursor.selectionEnd()))
        if cursor.selectionEnd() == cursor.selectionStart():
            return out


def _selection(doc, start: int, end: int, color: QColor):
    fmt = QTextCharFormat()
    fmt.setBackground(color)
    item = QTextEdit.ExtraSelection()
    item.cursor = QTextCursor(doc)
    item.cursor.setPosition(start)
    item.cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    item.format = fmt
    return item
