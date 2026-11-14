# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# process_mirror.py — зеркало виджетов вкладки «Обработка» в чужих окнах
# настроек экспорта (Монтаж — _ExportSettingsDialog, фото — PhotoExportDialog).
"""Зеркало виджетов «Обработки»: копия виджета, связанная с оригиналом в обе
стороны. Правка зеркала ставит значение оригиналу (с его реакциями и
сохранением настроек), правка оригинала сразу видна в зеркале."""
from PyQt6.QtWidgets import (QAbstractButton, QCheckBox, QComboBox,
                             QDoubleSpinBox, QSlider)


def mirror_value(w):
    """Значение виджета-настройки в одном виде для обеих сторон зеркала."""
    if isinstance(w, QAbstractButton):
        return w.isChecked()
    if isinstance(w, QComboBox):
        return w.currentText() if w.isEditable() else w.currentIndex()
    return w.value()


def set_mirror_value(w, v):
    if isinstance(w, QAbstractButton):
        w.setChecked(bool(v))
    elif isinstance(w, QComboBox):
        if w.isEditable():
            w.setCurrentText(str(v))
        else:
            w.setCurrentIndex(int(v))
    else:
        w.setValue(v)


def mirror_changed_signal(w):
    if isinstance(w, QAbstractButton):
        return w.toggled
    if isinstance(w, QComboBox):
        # У редактируемого (FPS) значение — текст: ввод своего числа тоже правка.
        return w.currentTextChanged if w.isEditable() else w.currentIndexChanged
    return w.valueChanged


class ProcessMirrorMixin:
    """Зеркала виджетов для окна настроек. Окно заводит `self._pairs = []` и
    `self._syncing = True` до постройки (пока зеркала создаются, их сигналы в
    «Обработку» не идут) и определяет `_refresh_states()` — доступность своих
    виджетов после любой правки."""

    def _mirror(self, src, text=None):
        """Виджет того же типа и с теми же пределами, что src, связанный с
        ним в обе стороны."""
        if isinstance(src, QCheckBox):
            dst = QCheckBox(src.text() if text is None else text)
        elif isinstance(src, QComboBox):
            dst = type(src)()
            for i in range(src.count()):
                dst.addItem(src.itemIcon(i), src.itemText(i), src.itemData(i))
            if src.isEditable():
                dst.setEditable(True)
                dst.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                if src.lineEdit() is not None:
                    dst.lineEdit().setPlaceholderText(src.lineEdit().placeholderText())
            # Пункты короткие (кроме режима обрезки — его ширину держит строка):
            # видны целиком, без «по умо…».
            dst.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            if src.isEditable():
                dst.setMinimumWidth(src.minimumWidth() + 20)
        elif isinstance(src, QSlider):
            dst = QSlider(src.orientation())
            dst.setRange(src.minimum(), src.maximum())
            dst.setSingleStep(src.singleStep()); dst.setPageStep(src.pageStep())
        else:                                     # QSpinBox / QDoubleSpinBox
            dst = type(src)()
            if isinstance(src, QDoubleSpinBox):
                dst.setDecimals(src.decimals())
            dst.setRange(src.minimum(), src.maximum())
            dst.setSingleStep(src.singleStep())
            dst.setPrefix(src.prefix()); dst.setSuffix(src.suffix())
            dst.setMaximumWidth(max(80, src.maximumWidth() if src.maximumWidth() < 1000 else 110))
        dst.setToolTip(src.toolTip())
        self._pairs.append((src, dst))
        mirror_changed_signal(dst).connect(lambda *_a, s=src, d=dst: self._push(s, d))
        mirror_changed_signal(src).connect(lambda *_a, s=src, d=dst: self._pull(s, d))
        return dst

    def _push(self, src, dst):
        """Правка здесь → виджет «Обработки» (без глушения сигналов: пусть
        сработает всё, что там завязано на правку, — сохранение, видимость)."""
        if self._syncing:
            return
        self._syncing = True
        try:
            if mirror_value(src) != mirror_value(dst):
                set_mirror_value(src, mirror_value(dst))
        finally:
            self._syncing = False
        self._refresh_states()

    def _pull(self, src, dst):
        """Правка в «Обработке» → здесь."""
        if self._syncing:
            return
        try:
            v = mirror_value(src)
            if mirror_value(dst) != v:
                dst.blockSignals(True)
                try:
                    set_mirror_value(dst, v)
                finally:
                    dst.blockSignals(False)
            self._refresh_states()
        except RuntimeError:
            pass                                  # окно или виджет уже удалены (выход)

    def _pull_pairs(self):
        """Все зеркала — заново из «Обработки» (часть правок там идёт с
        заглушёнными сигналами: профиль, загрузка настроек)."""
        for src, dst in self._pairs:
            self._pull(src, dst)
