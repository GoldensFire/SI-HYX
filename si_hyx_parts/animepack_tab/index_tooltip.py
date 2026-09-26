# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Из чего сложился «Индекс» в таблице состава пака. Namespace: animepack_tab.

В колонке стоит одно число, и по нему не видно ни откуда оно, ни почему у
сиквела оно такое же, как у первого сезона. Теперь при наведении на ячейку
всплывает та же разбивка, что во вкладке ShikimoriHYX: сколько людей и с каким
статусом дали базу, как её приглушили свежесть выхода и оценка, и чем всё
кончилось (просьба пользователя).

Подсказка — СВОЙ тёмный попап (widgets._InfoTipPopup), а не системный
QToolTip: синюю всплывашку пользователь не выносит, и вешать item.setToolTip
здесь нельзя (см. hover_tip / no_qtooltip).
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt

# Роль, в которой текст подсказки лежит прямо в ячейке: item.clone() уносит
# её вместе с ячейкой в отдельное окно состава пака (см. _NumItem.clone).
TIP_ROLE = Qt.ItemDataRole.UserRole + 7
# Та же роль для ячейки «Цена»: из чего сложилась цена вопроса.
PRICE_ROLE = Qt.ItemDataRole.UserRole + 8

try:
    from widgets import _InfoTipPopup
except Exception:      # pragma: no cover — вкладка живёт и без попапа
    _InfoTipPopup = None


def _fmt(number) -> str:
    return f"{int(round(float(number or 0))):,}".replace(",", " ")


def _dec(number) -> str:
    text = f"{float(number or 0):.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def build_text(cand) -> str:
    """Короткая последовательная формула индекса (пусто — нечего)."""
    try:
        import animepack as ap
        import shikimori_api as shiki
    except Exception:  # pragma: no cover — без сети модуля может не быть
        return ""
    anime = getattr(cand, "anime", None) or {}
    base = shiki.index_base_from_statuses_stats(anime.get("statusesStats"))
    own = float(getattr(cand, "own_index", 0.0) or 0.0)
    index = float(getattr(cand, "index", 0.0) or 0.0)
    if index <= 0:
        return ""
    year = int(getattr(cand, "year", 0) or 0)
    score = float(getattr(cand, "score", 0.0) or 0.0)
    manga = bool(getattr(cand, "is_manga", False))
    until = int(getattr(cand, "released_year", 0) or 0)
    going = bool(getattr(cand, "ongoing", False))
    recency, score_factor = shiki.index_factors(year or None, score, manga,
                                                until=until or None,
                                                ongoing=going)
    lines = []
    if base > 0:
        terms = []
        for label, weighted, count in _components(anime):
            weight = weighted / count
            terms.append(f"{label.lower()} {_fmt(count)}×{_dec(weight)}")
        lines.append(f"База: {' + '.join(terms)} = {_fmt(base)}")
        lines.append(f"Свой индекс: {_fmt(base)} × {_dec(recency)} × "
                     f"{_dec(score_factor)} = {_fmt(own)}")
    franchise = float(getattr(cand, "franchise_index", 0.0) or 0.0)
    fav = float(getattr(cand, "favorites_factor", 1.0) or 1.0)
    try:
        favorites = int(getattr(cand, "favorites", -1))
    except (TypeError, ValueError):
        favorites = -1
    if favorites >= 0 and base > 0:
        lines.append(f"Избранное: {_fmt(favorites)} → ×{_dec(fav)}")
    if manga:
        book = float(getattr(cand, "book_index", 0.0) or 0.0)
        reached = ap.manga_reach(book)
        lines.append(f"Книжная шкала: {_fmt(own)} × {_dec(fav)} → "
                     f"{_fmt(reached)}")
        if franchise > 0:
            lines.append(f"Индекс: max(книга {_fmt(reached)}; аниме "
                         f"{_fmt(franchise)}×{_dec(fav)}) = {_fmt(index)}")
        else:
            lines.append(f"Индекс: {_fmt(index)}")
    elif franchise > 0:
        lines.append(f"Индекс: max(свой {_fmt(own)}; серия "
                     f"{_fmt(franchise)}) × {_dec(fav)} = {_fmt(index)}")
    elif fav != 1.0:
        lines.append(f"Индекс: {_fmt(own)} × {_dec(fav)} = {_fmt(index)}")
    else:
        lines.append(f"Индекс: {_fmt(index)}")
    level = getattr(cand, "level", "?")
    lines.append(f"Уровень: {level}")
    return "\n".join(lines)


def build_price_text(cand) -> str:
    """Из чего сложилась цена вопроса (пусто — разбивку не считали).

    Строки готовит assign_prices (animepack/price_parts.py): она одна знает и
    порядок множителей, и надбавки за род вопроса."""
    lines = [str(row) for row in (getattr(cand, "price_parts", None) or [])]
    if not lines:
        return ""
    return "\n".join(["Цена вопроса", ""] + lines)


def _components(anime: dict):
    """(подпись, взвешенный вклад, человек) по статусам — из GraphQL-карточки."""
    import shikimori_api as shiki
    rows = []
    for row in (anime.get("statusesStats") or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("status") or "").strip().lower()
        weight = shiki._INDEX_STATUS_WEIGHTS.get(key)
        if not weight:
            continue
        try:
            count = int(row.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        label = shiki._INDEX_STATUS_LABELS.get(key, key.capitalize())
        rows.append((label, weight * count, count))
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows


def install(table, whole_row: bool = False) -> None:
    """Вешает на таблицу показ подсказки по ячейкам с разбивкой индекса.

    whole_row=True — подсказка показывается над ЛЮБОЙ ячейкой строки, а не
    только над «Индексом» и «Ценой»: так сделана панель базы Shikimori, и в
    отдельном окне состава пака человек ждёт того же (просьба пользователя)."""
    if _InfoTipPopup is None or getattr(table, "_index_tip_on", False):
        return
    table._index_tip_on = True
    # Фильтр держим ссылкой на самой таблице: иначе сборщик Python унесёт его,
    # и подсказка перестанет появляться через случайное время.
    table._index_tip_watcher = watcher = _TipWatcher(table, whole_row)
    table.viewport().installEventFilter(watcher)


def install_headers(table, hints: dict) -> None:
    """Подсказки на заголовках колонок: откуда взялось это значение."""
    if _InfoTipPopup is None or getattr(table, "_head_tip_on", False):
        return
    table._head_tip_on = True
    header = table.horizontalHeader()
    table._head_tip_watcher = watcher = _HeadWatcher(table, dict(hints))
    header.installEventFilter(watcher)


class _TipWatcher(QObject):
    """Фильтр событий: ToolTip над ячейкой с разбивкой — свой тёмный попап."""

    def __init__(self, table, whole_row: bool = False):
        super().__init__(table)
        self._table = table
        self._whole_row = bool(whole_row)

    def eventFilter(self, _object, event):   # noqa: N802 — имя из Qt
        if event.type() != QEvent.Type.ToolTip:
            return False
        item = self._table.itemAt(event.pos())
        text = None
        if item is not None:
            # Одна и та же всплывашка на две колонки: «Индекс» рассказывает,
            # из чего сложилась узнаваемость, «Цена» — из чего сложилась цена.
            text = item.data(TIP_ROLE) or item.data(PRICE_ROLE)
            if not text and self._whole_row:
                text = self._row_text(item.row())
        if text:
            _InfoTipPopup.instance().show_at(event.globalPos(), str(text))
        else:
            _InfoTipPopup.instance().hide()
        return True

    def _row_text(self, row: int) -> str:
        """Разбор всей строки: сперва узнаваемость, следом цена."""
        parts = []
        for role in (TIP_ROLE, PRICE_ROLE):
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                text = item.data(role) if item is not None else None
                if text:
                    parts.append(str(text))
                    break
        return "\n\n".join(parts)


class _HeadWatcher(QObject):
    """Фильтр событий: ToolTip над заголовком колонки."""

    def __init__(self, table, hints: dict):
        super().__init__(table)
        self._table = table
        self._hints = hints

    def eventFilter(self, _object, event):   # noqa: N802 — имя из Qt
        if event.type() != QEvent.Type.ToolTip:
            return False
        header = self._table.horizontalHeader()
        column = header.logicalIndexAt(event.pos())
        item = self._table.horizontalHeaderItem(column)
        text = self._hints.get(item.text() if item is not None else "")
        if text:
            _InfoTipPopup.instance().show_at(event.globalPos(), str(text))
        else:
            _InfoTipPopup.instance().hide()
        return True
