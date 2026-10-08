# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Подсказка строки в панели базы Shikimori. Namespace: animepack_tab.

Своя тёмная всплывашка (widgets._InfoTipPopup), а не системный QToolTip.
Текст строится ПО НАВЕДЕНИЮ: считать разбор индекса у десятков тысяч строк
заранее незачем.

Почему подсказка «лагала» (просьба пользователя):

* Qt присылает ToolTip только после паузы курсора (~0,7 с). Пока попап висел,
  переход на соседнюю строку оставлял на экране ЧУЖОЙ разбор до следующей
  паузы — подсказка отставала от мыши. Теперь, пока попап показан, смена
  ячейки под курсором сразу меняет и текст, без ожидания.
* На каждый ToolTip попап заново подгонялся по размеру и передвигался, даже
  если под курсором та же ячейка. Теперь та же ячейка попап не трогает.
* Разбор ячейки запоминается: возврат на строку не считает его снова.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtGui import QCursor
from si_hyx_parts.widgets.info_tip_frame import source_is_current

try:
    from widgets import _InfoTipPopup
except Exception:      # pragma: no cover — панель живёт и без попапа
    _InfoTipPopup = None

# Сколько разборов держим в памяти: наведение обходит от силы сотню строк, а
# без предела словарь рос бы на всю сессию панели.
CACHE_LIMIT = 512


class RowTipWatcher(QObject):
    """Фильтр событий viewport'а: ToolTip, движение мыши и уход курсора."""

    def __init__(self, page):
        super().__init__(page)
        self._page = page
        self._key = None
        self._texts: dict = {}
        self._follow = QTimer(self)
        self._follow.setSingleShot(True)
        self._follow.timeout.connect(self._follow_cursor)

    def reset(self) -> None:
        """Строки таблицы сменились — прежние разборы больше не годятся."""
        self._key = None
        self._texts.clear()
        self._hide()

    def eventFilter(self, _object, event):   # noqa: N802 — имя из Qt
        if _InfoTipPopup is None:
            return False
        kind = event.type()
        if kind == QEvent.Type.ToolTip:
            self._show(event.pos(), event.globalPos())
            return True
        if kind in (QEvent.Type.MouseMove, QEvent.Type.Enter) and self._owns_tip():
            # Re-entering the viewport may deliver only Enter after another
            # window intercepted the move. Resume the already active row tip.
            try:
                pos = event.position().toPoint()
                gpos = event.globalPosition().toPoint()
            except AttributeError:  # pragma: no cover — старый Qt
                pos, gpos = event.pos(), event.globalPos()
            self._show(pos, gpos)
            # Native pointer events can precede QCursor's update. The global
            # filter has hidden the old cell; retry after the cursor settles.
            self._follow.start(0)
        elif kind in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress,
                      QEvent.Type.Wheel):
            self._hide()
        return False

    def _visible(self) -> bool:
        return self._owns_tip() and _InfoTipPopup.instance().isVisible()

    def _follow_cursor(self) -> None:
        viewport = self._page.table.viewport()
        point = QCursor.pos()
        if source_is_current(viewport, point):
            self._show(viewport.mapFromGlobal(point), point)

    def _owns_tip(self) -> bool:
        # The application filter hides an old cell before this filter receives
        # MouseMove. Keep following rows while this watcher still owns the tip.
        popup = _InfoTipPopup.instance()
        return (self._key is not None
                and popup._anchor == id(self._page.table.viewport()))

    def _show(self, pos, global_pos) -> None:
        if not source_is_current(self._page.table.viewport(), global_pos):
            return
        key = self._page.tip_key_at(pos)
        if key is None:
            self._hide()
            return
        if key == self._key and self._visible():
            return          # та же ячейка — попап стоит, где стоял
        text = self._texts.get(key)
        if text is None:
            text = str(self._page.explain_at(pos) or "")
            if len(self._texts) >= CACHE_LIMIT:
                self._texts.clear()
            self._texts[key] = text
        if not text:
            self._hide()
            return
        self._key = key
        table = self._page.table
        _InfoTipPopup.instance().show_at(
            global_pos, text, owner=table.viewport(),
            region=table.visualRect(table.indexAt(pos)))

    def _hide(self) -> None:
        self._follow.stop()
        if self._key is None:
            return
        self._key = None
        _InfoTipPopup.instance().hide_for(self._page.table.viewport())
