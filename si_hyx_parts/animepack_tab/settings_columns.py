# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Панель настроек в НЕСКОЛЬКО колонок. Namespace: animepack_tab.

Раньше настройки жили одной узкой колонкой у правого края, а всё место слева
занимала таблица состава пака — пустая до самой генерации. Прокрутка панели
выходила на несколько экранов при том, что половина вкладки пустовала (просьба
пользователя).

Теперь таблица прячется под кнопку, а группы настроек раскладываются по
колонкам ровно настолько, насколько хватает ширины: узкое окно — одна колонка,
как было, широкое — две-три. Порядок групп сохраняется: сверху вниз, потом
слева направо.

Пересчёт идёт ТОЛЬКО при смене числа колонок, а не на каждое изменение высоты
группы: иначе группы прыгали бы между колонками от каждой поставленной
галочки.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from .settings_box import SettingsBox, needed_height

# Уже этой ширины колонка настроек не бывает: дальше подписи начинают резаться
# (то же число, что и SETTINGS_MIN_W у вкладки).
MIN_COLUMN_W = 320
SPACING = 12


def _refresh_tree(widget) -> None:
    """Снизу вверх принимает новую высоту всех раскрываемых контейнеров."""
    layout = widget.layout()
    if layout is None:
        return
    for index in range(layout.count()):
        child = layout.itemAt(index).widget()
        if child is not None:
            _refresh_tree(child)
    # Сначала снимаем прежний минимум: иначе после закрытия большой панели
    # её старая высота становилась частью нового sizeHint и уже не уменьшалась.
    widget.setMinimumHeight(0)
    layout.invalidate()
    layout.activate()
    # Не просто sizeHint: у QGroupBox сверху ещё поле под заголовок, и без
    # него минимум группы выходил на пару десятков точек меньше настоящего.
    # Нехватку высоты QGridLayout разбирает НАКЛАДКОЙ строк друг на друга —
    # ровно так раскрытый Chiptune и оказывался поверх галочек состава.
    widget.setMinimumHeight(needed_height(widget))
    widget.updateGeometry()


class SettingsColumns(SettingsBox):
    """Раскладывает готовые группы настроек по колонкам под ширину панели."""

    def __init__(self, groups, min_column=MIN_COLUMN_W, parent=None, *,
                 pinned_second=False):
        super().__init__(parent)
        self._groups = [g for g in groups if g is not None]
        self._min_column = int(min_column)
        self._pinned_second = bool(pinned_second and len(self._groups) >= 2)
        self._columns = 0
        self._holders: list[QWidget] = []
        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(SPACING)
        self.relayout(1)

    # ── сколько колонок помещается ────────────────────────────────────────
    def fit_columns(self, width: int) -> int:
        """Больше всего колонок, которые ВЛЕЗАЮТ в эту ширину.

        Считаем по настоящим минимальным ширинам групп, а не по одной общей
        планке: «Прочее» с его подписями не сжимается и до 640 px, а «Пак» —
        вдвое уже. По одной планке колонок выходило больше, чем помещается, и
        панель уезжала под горизонтальную полосу."""
        width = max(1, int(width))
        best = 2 if self._pinned_second else 1
        for count in range(best + 1, len(self._groups) + 1):
            if self._needed_width(self._split(count)) > width:
                break
            best = count
        return best

    def _needed_width(self, buckets) -> int:
        buckets = [b for b in buckets if b]
        if not buckets:
            return 0
        columns = [max(self._min_width(group) for group in bucket)
                   for bucket in buckets]
        return sum(columns) + SPACING * (len(columns) - 1)

    def _min_width(self, group) -> int:
        return max(self._min_column, int(group.minimumSizeHint().width()))

    def apply_width(self, width: int) -> None:
        """Пересобирает колонки под доступную ширину (зовёт сама вкладка).

        Своего resizeEvent тут нарочно нет: панель лежит в QScrollArea и
        растёт вслед за собственным содержимым, так что «своя» ширина —
        следствие числа колонок, а не причина. Считать по ней значит поймать
        петлю «шире → больше колонок → ещё шире»."""
        # Вложенная коробка могла только что скрыться. До активации её
        # раскладки Qt возвращает закэшированный sizeHint от раскрытого
        # состояния: после выключения каверов из-за этого оставалась одна
        # колонка, а первая группа сохраняла прежнюю огромную высоту.
        self.refresh_geometry()
        columns = self.fit_columns(width)
        if columns != self._columns:
            self.relayout(columns)
            # Перенос групп меняет высоту держателей; минимум панели должен
            # соответствовать уже новой, а не предыдущей раскладке.
            self.refresh_geometry()

    def refresh_geometry(self) -> None:
        """Обновляет высоту колонок после раскрытия вложенных настроек.

        Число колонок при галочке обычно не меняется, но sizeHint группы —
        меняется. Без явной активации Qt оставлял прежнюю высоту и обрезал
        Chiptune, каверы и нижнюю часть песенных настроек.
        """
        for group in self._groups:
            # Вложенность здесь существенна: Chiptune лежит внутри звука,
            # звук — внутри песен, песни — внутри группы. Обновление только
            # внешней группы оставляло внутренние коробки на старой высоте.
            _refresh_tree(group)
        for holder in self._holders:
            layout = holder.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
            holder.updateGeometry()
        # QScrollArea растягивает дочерний panel до высоты окна. Если здесь
        # нет собственного минимума, эта высота насильно раздаётся группам и
        # раскрытая вложенная панель обрезается вместо появления прокрутки.
        heights = []
        for holder in self._holders:
            layout = holder.layout()
            widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
            widgets = [widget for widget in widgets if widget is not None]
            heights.append(sum(needed_height(widget) for widget in widgets)
                           + max(0, len(widgets) - 1) * layout.spacing())
        self.setMinimumHeight(max(heights, default=0))
        self._root.invalidate()
        self._root.activate()
        self.updateGeometry()

    # ── сама раскладка ────────────────────────────────────────────────────
    def relayout(self, columns: int) -> None:
        minimum = 2 if self._pinned_second else 1
        columns = max(minimum, min(int(columns), len(self._groups) or 1))
        if columns == self._columns:
            return
        self._columns = columns
        old, self._holders = self._holders, []
        for bucket in self._split(columns):
            holder = SettingsBox(self)
            box = QVBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(SPACING)
            for group in bucket:
                # addWidget сам переносит группу к новому родителю — старая
                # колонка её отпускает, и удалять группы не приходится.
                box.addWidget(group)
            box.addStretch(1)
            self._root.addWidget(holder, 1)
            self._holders.append(holder)
        # Прежние колонки убираем ПОСЛЕ переноса: иначе группы удалились бы
        # вместе с ними.
        for holder in old:
            self._root.removeWidget(holder)
            holder.setParent(None)
            holder.deleteLater()

    def _split(self, columns: int) -> list[list[QWidget]]:
        """Делит группы по колонкам, выравнивая их суммарную высоту.

        Порядок групп не меняется: колонка набирается сверху вниз, пока не
        наберёт свою долю общей высоты."""
        buckets: list[list[QWidget]] = [[] for _ in range(columns)]
        if self._pinned_second:
            # Состав всегда в первой колонке, «Списки» всегда наверху второй.
            # Узкому окну отдаём горизонтальную прокрутку, а не перенос списка.
            buckets[0] = [self._groups[0]]
            buckets[1] = [self._groups[1]]
            for index, group in enumerate(self._groups[2:], 2):
                column = min(columns - 1, max(1, index - len(self._groups) + columns))
                buckets[column].append(group)
            return buckets
        if columns == 1:
            buckets[0] = list(self._groups)
            return buckets
        # «Списки» — вторая группа вкладки — закреплены в средней колонке.
        # Их положение не должно зависеть от текущей высоты раскрытых групп:
        # раньше при той же ширине они перескакивали между левой и средней.
        if columns == 3 and len(self._groups) >= 3:
            buckets[0] = [self._groups[0]]
            buckets[1] = list(self._groups[1:-1])
            buckets[2] = [self._groups[-1]]
            return buckets
        heights = [max(1, group.sizeHint().height()) for group in self._groups]
        target = sum(heights) / float(columns)
        index, filled = 0, 0.0
        for number, (group, height) in enumerate(zip(self._groups, heights)):
            left_groups = len(self._groups) - number
            left_columns = columns - index
            # Колонка не остаётся пустой: как только групп осталось ровно
            # столько же, сколько незанятых колонок, каждая следующая уходит
            # в свою. Пустая колонка — это просто дыра справа.
            crowded = left_groups <= left_columns
            if (index < columns - 1 and filled > 0
                    and (crowded or filled + height / 2.0 > target)):
                index += 1
                filled = 0.0
            buckets[index].append(group)
            filled += height
        return buckets
