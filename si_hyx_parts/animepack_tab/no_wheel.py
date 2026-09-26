# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_no_wheel. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def _no_wheel(widget):
    """Отучает поле менять значение колёсиком мыши.

    Панель настроек длинная и прокручивается колесом; стоило курсору проехать
    над счётчиком — и он молча менял число, а прокрутка вставала. Событие
    отдаём дальше по цепочке, чтобы прокручивалась сама панель."""
    def wheelEvent(event, _w=widget):
        event.ignore()
    widget.wheelEvent = wheelEvent
    # Без StrongFocus поле ловило бы колесо и без клика по нему.
    widget.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
    return widget

_no_wheel.__module__ = _api.__name__
_api._no_wheel = _no_wheel

# ─────────────────────────────────────────────────────────────────────────────
# Ползунок состава пака
# ─────────────────────────────────────────────────────────────────────────────
class _ShareBar(_api.QWidget):
    """Полоса, делящая сотню процентов между несколькими частями.

    Готового многоручкового ползунка в Qt нет, поэтому полоса своя: ручки делят
    её на части, снизу — легенда с процентами. Тянуть можно и за саму границу, и
    просто кликнув по полосе — ближняя ручка приедет туда.

    Части задаются списком (ключ, подпись, цвет) и МЕНЯЮТСЯ на ходу: одна и та
    же полоса делит и состав пака, и типы песен, и списки людей."""

    changed = _api.pyqtSignal()

    BAR_H = 16
    HANDLE_W = 9
    # Цвета частей по кругу — на случай, когда частей сколько угодно (списки).
    PALETTE = ("accent", "accent2", "green", "yellow", "red", "text2")

    def __init__(self, parts=(), parent=None):
        super().__init__(parent)
        self._labels: dict[str, str] = {}
        self._colors: dict[str, str] = {}
        self._vals: dict[str, int] = {}
        self._keys: list[str] = []
        self._drag = -1
        self.setMinimumHeight(self.BAR_H + 20)
        self.setMouseTracking(True)
        self.setCursor(_api.Qt.CursorShape.SizeHorCursor)
        if parts:
            self.set_parts(parts)

    # ── части ─────────────────────────────────────────────────────────────
    def set_parts(self, parts) -> None:
        """Заменяет набор частей. Проценты уже известных сохраняются, новым
        место выделяется поровну из общего котла."""
        keys = []
        for i, part in enumerate(parts):
            key, label = part[0], part[1]
            color = part[2] if len(part) > 2 else self.PALETTE[i % len(self.PALETTE)]
            keys.append(key)
            self._labels[key] = label
            self._colors[key] = color
        if keys == self._keys:
            return
        # Новой части даём ровную долю, а не ноль: иначе добавленный третьим
        # список так и остался бы с 0%, пока его не подвинут руками.
        fair = 100 // max(1, len(keys))
        vals = {k: (self._vals[k] if k in self._vals else fair) for k in keys}
        if not any(vals.values()):
            vals = {k: fair for k in keys}
        self._keys = keys
        self._normalise(vals)
        self.update()

    def keys(self) -> list[str]:
        return list(self._keys)

    def values(self) -> dict:
        """{ключ: процент} по видимым частям (скрытые — ноль)."""
        return {k: (self._vals.get(k, 0) if k in self._keys else 0)
                for k in self._vals}

    def value_of(self, key: str) -> int:
        return int(self._vals.get(key, 0)) if key in self._keys else 0

    def set_values(self, vals: dict) -> None:
        raw = {k: max(0, int(vals.get(k, 0) or 0)) for k in self._keys}
        self._normalise(raw)
        self.update()

    def _normalise(self, vals: dict) -> None:
        """Приводит доли видимых частей к сумме ровно 100."""
        shown = {k: max(0, int(vals.get(k, 0))) for k in self._keys}
        total = sum(shown.values())
        if total <= 0:
            shown = {k: (100 if k == self._keys[0] else 0) for k in self._keys}
        elif total != 100:
            out = {k: v * 100 // total for k, v in shown.items()}
            rest = 100 - sum(out.values())
            for k in sorted(shown, key=lambda k: -(shown[k] * 100 % total)):
                if rest <= 0:
                    break
                out[k] += 1
                rest -= 1
            shown = out
        vals = dict(self._vals)
        vals.update({k: shown.get(k, 0) for k in self._keys})
        for key in list(vals):
            if key not in self._keys and key not in self._labels:
                vals.pop(key)
        self._vals = vals
        # Легенда переехала — под неё могло понадобиться больше места.
        self._sync_height()

    # ── геометрия ─────────────────────────────────────────────────────────
    def _cuts(self) -> list[int]:
        """Границы частей в процентах (их на одну меньше, чем частей)."""
        out, acc = [], 0
        for key in self._keys[:-1]:
            acc += self._vals.get(key, 0)
            out.append(acc)
        return out

    def _apply_cuts(self, cuts: list[int]) -> None:
        prev = 0
        for i, key in enumerate(self._keys[:-1]):
            self._vals[key] = cuts[i] - prev
            prev = cuts[i]
        self._vals[self._keys[-1]] = 100 - prev

    def _bar_rect(self) -> _api.QRect:
        return _api.QRect(0, 0, max(1, self.width()), self.BAR_H)

    def _x_of(self, pct: int) -> int:
        return int(round(self._bar_rect().width() * pct / 100.0))

    def _pct_of(self, x: int) -> int:
        w = max(1, self._bar_rect().width())
        return max(0, min(100, int(round(x * 100.0 / w))))

    # ── мышь ──────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        cuts = self._cuts()
        if not cuts:
            return
        pct = self._pct_of(e.position().x())
        # Какую ручку двигать: ближнюю. При совпавших ручках (нулевая доля)
        # решает сторона, в которую тянут, — иначе доля не разжимается.
        near = min(range(len(cuts)), key=lambda i: (abs(pct - cuts[i]), i))
        while (near + 1 < len(cuts) and cuts[near + 1] == cuts[near]
               and pct > cuts[near]):
            near += 1
        self._drag = near
        self._move_to(pct)

    def mouseMoveEvent(self, e):
        if self._drag >= 0:
            self._move_to(self._pct_of(e.position().x()))

    def mouseReleaseEvent(self, _e):
        self._drag = -1

    def _move_to(self, pct: int) -> None:
        cuts = self._cuts()
        i = self._drag
        if not (0 <= i < len(cuts)):
            return
        new = list(cuts)
        # Соседние границы не перепрыгиваем: они лишь сдвигаются вплотную.
        new[i] = max(0, min(100, pct))
        for j in range(i - 1, -1, -1):
            new[j] = min(new[j], new[j + 1])
        for j in range(i + 1, len(new)):
            new[j] = max(new[j], new[j - 1])
        if new != cuts:
            self._apply_cuts(new)
            self.update()
            self.changed.emit()

    # ── рисование ─────────────────────────────────────────────────────────
    def paintEvent(self, _e):
        if not self._keys:
            return
        p = _api.QPainter(self)
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
        bar = self._bar_rect()
        cuts = self._cuts()
        x = 0
        for i, key in enumerate(self._keys):
            right = bar.width() if i == len(self._keys) - 1 else self._x_of(cuts[i])
            w = right - x
            if w > 0:
                p.fillRect(_api.QRect(x, bar.y(), w, bar.height()),
                           _api.QColor(_api.C[self._colors.get(key, "accent")]))
            x = max(x, right)
        p.setPen(_api.QColor(_api.C["border"]))
        p.drawRect(bar.adjusted(0, 0, -1, -1))
        for cut in cuts:
            hx = self._x_of(cut)
            p.fillRect(_api.QRect(hx - self.HANDLE_W // 2, bar.y() - 1,
                             self.HANDLE_W, bar.height() + 2),
                       _api.QColor(_api.C["text"]))
        # Легенда сплошной строкой с переносом: частей может быть и восемь,
        # подписи «слева — по центру — справа» на них уже не разложить.
        p.setPen(_api.QColor(_api.C["text2"]))
        p.setFont(self._legend_font())
        # Область легенды — РОВНО остаток виджета под полосой. Раньше здесь
        # стояло max(18, …): на шрифте покрупнее прямоугольник вылезал за
        # нижний край, и подписи («Опенинги 80% · Эндинги 20%») срезало по
        # горизонтали пополам.
        top = bar.bottom() + 2
        p.drawText(_api.QRect(0, top, bar.width(), max(1, self.height() - top)),
                   int(_api.Qt.AlignmentFlag.AlignHCenter | _api.Qt.TextFlag.TextWordWrap),
                   self._legend_text())

    # ── легенда ───────────────────────────────────────────────────────────
    def _legend_text(self) -> str:
        return "  ·  ".join(f"{self._labels.get(k, k)} {self._vals.get(k, 0)}%"
                            for k in self._keys)

    def _legend_font(self):
        font = self.font(); font.setPointSize(8)
        return font

    def _sync_height(self) -> None:
        """Подгоняет высоту под легенду: восемь частей в одну строку не влезают,
        и хвост («Анаграммы 15% · Сюжет 15%») просто пропадал за краем.

        Пол высоты строки берётся у САМОГО шрифта, а не зашитыми четырнадцатью
        пикселями: на крупном системном шрифте (Windows со масштабом 125%) одна
        строка легенды в них не помещалась, и подписи срезало пополам."""
        from PyQt6.QtGui import QFontMetrics
        width = max(1, self.width())
        fm = QFontMetrics(self._legend_font())
        need = fm.boundingRect(
            _api.QRect(0, 0, width, 1000),
            int(_api.Qt.AlignmentFlag.AlignHCenter | _api.Qt.TextFlag.TextWordWrap),
            self._legend_text()).height()
        # +2 сверху (отступ от полосы) и +2 снизу — ровно те же числа, по
        # которым paintEvent кладёт легенду.
        height = self.BAR_H + 2 + max(fm.height(), need) + 2
        if height != self.minimumHeight():
            self.setMinimumHeight(height)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_height()

_ShareBar.__module__ = _api.__name__
_api._ShareBar = _ShareBar
