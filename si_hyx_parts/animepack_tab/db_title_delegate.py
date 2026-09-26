# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Кнопки названия в дереве базы: копирование и страница Shikimori."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QRect, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QStyle, QStyleOptionViewItem, QStyledItemDelegate,
)

from config import get_icon

ICON = 16
GAP = 5
RIGHT = 6
COPY_FEEDBACK_MS = 1500


def shikimori_url(row) -> str:
    """Адрес карточки по id Shikimori (не MAL)."""
    canonical = str((row or {}).get("url") or "").strip()
    if canonical:
        if canonical.startswith("/"):
            canonical = "https://shikimori.io" + canonical
        url = canonical.replace("shikimori.one", "shikimori.io")
    else:
        try:
            ident = int((row or {}).get("id") or 0)
        except (TypeError, ValueError):
            return ""
        if ident <= 0:
            return ""
        section = ("mangas" if (row or {}).get("media") == "manga"
                   else "animes")
        url = f"https://shikimori.io/{section}/z{ident}"
    if (row or {}).get("_franchise_header"):
        return url.rstrip("/") + "/franchise"
    return url


def character_url(row) -> str:
    """Страница персонажа Shikimori по его собственному id."""
    try:
        ident = int((row or {}).get("id") or 0)
    except (TypeError, ValueError):
        return ""
    return f"https://shikimori.io/characters/{ident}" if ident > 0 else ""


class TitleActionsDelegate(QStyledItemDelegate):
    """Две маленькие SVG-кнопки справа от каждого названия."""

    def __init__(self, parent=None, *, column=0, text_key="title",
                 url_for=shikimori_url):
        super().__init__(parent)
        self._column = int(column)
        self._text_key = str(text_key)
        self._url_for = url_for
        self._copy = get_icon("fa5s.copy", color="#a6adc8")
        self._copied = get_icon("fa5s.check", color="#a6e3a1")
        self._open = get_icon("fa5s.external-link-alt", color="#89b4fa")
        self._copied_id = None
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._clear_copied)

    @staticmethod
    def _row_id(row):
        if row.get("_franchise_header"):
            return ("franchise", str(row.get("franchise") or ""))
        try:
            ident = int(row.get("id") or 0)
        except (TypeError, ValueError):
            ident = 0
        return (str(row.get("media") or row.get("owner_media") or "anime"),
                ident, str(row.get("title") or row.get("name") or ""))

    def _clear_copied(self):
        self._copied_id = None
        self._update_view()

    def _update_view(self):
        view = self.parent()
        viewport = getattr(view, "viewport", None)
        if callable(viewport):
            viewport().update()

    @staticmethod
    def _rects(option):
        top = option.rect.center().y() - ICON // 2
        open_rect = QRect(option.rect.right() - RIGHT - ICON, top, ICON, ICON)
        copy_rect = QRect(open_rect.left() - GAP - ICON, top, ICON, ICON)
        return copy_rect, open_rect

    def paint(self, painter, option, index):
        if index.column() != self._column:
            return super().paint(painter, option, index)
        source = getattr(index.model(), "source", None)
        row = source(index) if callable(source) else None
        copy_rect, open_rect = self._rects(option)
        if option.state & QStyle.StateFlag.State_Selected:
            # super().paint ниже рисует фон только в урезанном
            # text_option. Докрашиваем правый край за кнопками, чтобы
            # выделенная строка была одной сплошной полосой.
            painter.fillRect(copy_rect.left() - GAP, option.rect.top(),
                             option.rect.right() - copy_rect.left() + GAP + 1,
                             option.rect.height(), option.palette.highlight())
        text_option = QStyleOptionViewItem(option)
        text_option.rect.setRight(copy_rect.left() - GAP)
        super().paint(painter, text_option, index)
        icon = (self._copied if isinstance(row, dict)
                and self._row_id(row) == self._copied_id else self._copy)
        icon.paint(painter, copy_rect)
        self._open.paint(painter, open_rect)

    def sizeHint(self, option, index):       # noqa: N802 — имя из Qt
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), option.fontMetrics.height() * 2 + 8))
        return size

    def editorEvent(self, event, model, option, index):
        if (index.column() != self._column
                or event.type() != QEvent.Type.MouseButtonRelease
                or event.button() != Qt.MouseButton.LeftButton):
            return super().editorEvent(event, model, option, index)
        try:
            pos = event.position().toPoint()
        except AttributeError:  # pragma: no cover — старый Qt
            pos = event.pos()
        copy_rect, open_rect = self._rects(option)
        row = model.source(index)
        if not isinstance(row, dict):
            return False
        if copy_rect.contains(pos):
            QApplication.clipboard().setText(str(row.get(self._text_key) or ""))
            self._copied_id = self._row_id(row)
            self._reset_timer.start(COPY_FEEDBACK_MS)
            self._update_view()
            return True
        if open_rect.contains(pos):
            url = self._url_for(row)
            if url:
                QDesktopServices.openUrl(QUrl(url))
            return True
        return super().editorEvent(event, model, option, index)
