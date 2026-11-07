# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_PixelizeDialog. Public namespace: edit_tab_dialogs."""
import os

import edit_tab_dialogs as _api
from frame_reveal import EFFECT_HINTS, EFFECT_LABELS
from frame_reveal_dvd_media import IMAGE_EXTS

# Подсказки, которые у видео звучат иначе, чем в генераторе паков: летит
# заставка с частотой кадров клипа.
_VIDEO_HINTS = {
    "dvd": ("Чёрный экран, по нему летает прямоугольник, как логотип на заставке "
            "DVD, и открывает видео там, где пролетел. Картинки в прямоугольнике "
            "— из «Папка DVD» генератора аниме-паков (не задана — прямоугольник "
            "лишь окно в кадр). На последнем шаге след застывает, необлетённое "
            "остаётся чёрным."),
}
_IMAGE_FILTER = ("Картинки (" + " ".join("*" + ext for ext in IMAGE_EXTS) + ")"
                 ";;Все файлы (*)")


class _PixelizeDialog(_api.QDialog):
    """Настройка эффекта проявления: сам эффект (пикселизация или любой другой
    из генератора аниме-паков — frame_reveal), число шагов и, у пикселизации,
    стартовый размер блока. Превью показывает ступени или описание эффекта."""

    def __init__(self, steps=6, block=64, parent=None,
                 image_mode=False, duration=5.0, fps=25, effect="pixelize",
                 extra_images=(), dvd_folder=""):
        super().__init__(parent)
        self._image_mode = bool(image_mode)
        self.setWindowTitle("Эффект проявления")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"""
            QDialog {{ background: {_api.C['bg']}; }}
            QLabel {{ color: {_api.C['text2']}; font-size: 12px; }}
            QSpinBox {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 5px 8px; font-size: 13px; min-width: 64px;
            }}
            QSpinBox:focus {{ border-color: {_api.C['accent']}; }}
            QComboBox {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 5px 8px; font-size: 13px;
            }}
            QPushButton {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background: {_api.C['border2']}; border-color: {_api.C['accent']}; }}
            QListWidget {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                font-size: 12px;
            }}
        """)
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12); lay.setSpacing(10)
        if self._image_mode:
            info = _api.QLabel(
                "Из картинки получится ВИДЕО: кадр начнётся спрятанным выбранным "
                "эффектом и за несколько шагов проявится. Задай длительность ролика и "
                "параметры проявления. Готовое видео сохранится кнопкой «Экспорт».")
        else:
            info = _api.QLabel(
                "Видео начнётся спрятанным выбранным эффектом и с каждым шагом будет "
                "проявляться, пока не станет чётким. Идеально для угадайки. Эффекты — "
                "те же, что у кадров в генераторе аниме-паков. Применяется при "
                "«Экспорт» и требует перекодировки.")
        info.setWordWrap(True); lay.addWidget(info)

        rowe = _api.QHBoxLayout(); rowe.setSpacing(8)
        rowe.addWidget(_api.QLabel("Эффект"))
        self.cmb_effect = _api.QComboBox()
        for key, label in EFFECT_LABELS.items():
            self.cmb_effect.addItem(label, key)
        self.cmb_effect.setCurrentIndex(max(0, self.cmb_effect.findData(effect)))
        rowe.addStretch(1); rowe.addWidget(self.cmb_effect)
        lay.addLayout(rowe)

        # Для картинки нужна длительность результата (у изображения её нет) и FPS.
        self.sp_dur = None; self.sp_fps = None
        if self._image_mode:
            rowd = _api.QHBoxLayout(); rowd.setSpacing(8)
            rowd.addWidget(_api.QLabel("Длительность видео, сек"))
            self.sp_dur = _api.QSpinBox(); self.sp_dur.setRange(1, 120)
            self.sp_dur.setValue(max(1, int(round(float(duration)))))
            rowd.addStretch(1); rowd.addWidget(self.sp_dur)
            lay.addLayout(rowd)

            rowf = _api.QHBoxLayout(); rowf.setSpacing(8)
            rowf.addWidget(_api.QLabel("Кадров в секунду (FPS)"))
            self.sp_fps = _api.QSpinBox(); self.sp_fps.setRange(1, 60)
            self.sp_fps.setValue(max(1, int(fps)))
            rowf.addStretch(1); rowf.addWidget(self.sp_fps)
            lay.addLayout(rowf)

        row1 = _api.QHBoxLayout(); row1.setSpacing(8)
        row1.addWidget(_api.QLabel("Число шагов проявления"))
        self.sp_steps = _api.QSpinBox(); self.sp_steps.setRange(1, 20); self.sp_steps.setValue(int(steps))
        row1.addStretch(1); row1.addWidget(self.sp_steps)
        lay.addLayout(row1)

        row2 = _api.QHBoxLayout(); row2.setSpacing(8)
        self.lbl_block = _api.QLabel("Начальный размер блока, px")
        row2.addWidget(self.lbl_block)
        self.sp_block = _api.QSpinBox(); self.sp_block.setRange(4, 256)
        self.sp_block.setSingleStep(4); self.sp_block.setValue(int(block))
        row2.addStretch(1); row2.addWidget(self.sp_block)
        lay.addLayout(row2)

        # Откуда DVD-заставка берёт картинки прямоугольника — только подпись.
        self.lbl_dvd_folder = _api.QLabel(
            f"Картинки в прямоугольнике DVD: {dvd_folder}" if dvd_folder else
            "Картинки в прямоугольнике DVD: «Папка DVD» в генераторе аниме-паков "
            "не задана — прямоугольник окно в кадр")
        self.lbl_dvd_folder.setWordWrap(True)
        lay.addWidget(self.lbl_dvd_folder)

        self._build_extra_images(lay, extra_images)

        self.preview = _api.QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        lay.addWidget(self.preview)

        self.sp_steps.valueChanged.connect(self._update_preview)
        self.sp_block.valueChanged.connect(self._update_preview)
        self.cmb_effect.currentIndexChanged.connect(self._update_preview)
        self._update_preview()

        bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Ok
                              | _api.QDialogButtonBox.StandardButton.Cancel)
        bb.button(_api.QDialogButtonBox.StandardButton.Ok).setText("Применить")
        bb.button(_api.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # ── ещё картинки для пакета ───────────────────────────────────────
    def _build_extra_images(self, lay, paths):
        """Список «+ Файлы»: ещё картинки, из каждой при «Экспорт» выйдет своё
        видео с тем же эффектом (только в режиме картинки)."""
        self.box_extra = _api.QWidget()
        col = _api.QVBoxLayout(self.box_extra)
        col.setContentsMargins(0, 0, 0, 0); col.setSpacing(6)
        self.lbl_extra = _api.QLabel()
        self.lbl_extra.setWordWrap(True)
        col.addWidget(self.lbl_extra)
        self.lst_extra = _api.QListWidget()
        self.lst_extra.setSelectionMode(
            _api.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lst_extra.setMinimumHeight(90)
        self.lst_extra.setMaximumHeight(150)
        col.addWidget(self.lst_extra)
        row = _api.QHBoxLayout(); row.setSpacing(6)
        btn_files = _api.QPushButton("+ Файлы…")
        btn_files.setToolTip("Добавить картинки — можно сразу несколько "
                             "(Ctrl/Shift). Из каждой выйдет своё видео.")
        btn_files.clicked.connect(self._add_extra_files)
        self.btn_extra_remove = _api.QPushButton("Убрать")
        self.btn_extra_remove.clicked.connect(self._remove_extra_selected)
        btn_clear = _api.QPushButton("Очистить")
        btn_clear.clicked.connect(self._clear_extra)
        row.addWidget(btn_files)
        row.addStretch(1)
        row.addWidget(self.btn_extra_remove); row.addWidget(btn_clear)
        col.addLayout(row)
        lay.addWidget(self.box_extra)
        self.box_extra.setVisible(self._image_mode)
        self._extra_dir = ""
        self._add_extra_paths(paths or ())

    def _add_extra_paths(self, paths):
        have = set(self.extra_images())
        for path in paths:
            path = os.path.normpath(str(path))
            if (not path or path in have or not os.path.isfile(path)
                    or not path.lower().endswith(IMAGE_EXTS)):
                continue
            have.add(path)
            item = _api.QListWidgetItem(os.path.basename(path) or path)
            item.setToolTip(path)
            item.setData(_api.Qt.ItemDataRole.UserRole, path)
            self.lst_extra.addItem(item)
            self._extra_dir = os.path.dirname(path)
        self._update_extra_label()

    def _add_extra_files(self):
        files, _ = _api.QFileDialog.getOpenFileNames(
            self, "Ещё картинки — из каждой своё видео", self._extra_dir,
            _IMAGE_FILTER)
        if files:
            self._add_extra_paths(files)

    def _remove_extra_selected(self):
        for item in self.lst_extra.selectedItems():
            self.lst_extra.takeItem(self.lst_extra.row(item))
        self._update_extra_label()

    def _clear_extra(self):
        self.lst_extra.clear()
        self._update_extra_label()

    def _update_extra_label(self):
        count = self.lst_extra.count()
        self.lbl_extra.setText(
            f"Ещё картинки: {count} — «Экспорт» сделает {count + 1} видео "
            "(открытая картинка и эти), у каждой тот же эффект."
            if count else
            "Ещё картинки: нет — видео только из открытой картинки. «+ Файлы» "
            "добавит картинки, и из каждой выйдет своё видео.")
        self.btn_extra_remove.setEnabled(count > 0)

    def extra_images(self):
        """Добавленные картинки пакета (пути)."""
        return [self.lst_extra.item(i).data(_api.Qt.ItemDataRole.UserRole)
                for i in range(self.lst_extra.count())]

    def _update_preview(self):
        effect = self.effect()
        pixel = effect == "pixelize"
        # Размер блока есть только у пикселизации, папка картинок — у DVD.
        self.lbl_block.setVisible(pixel)
        self.sp_block.setVisible(pixel)
        self.lbl_dvd_folder.setVisible(effect == "dvd")
        if pixel:
            seq = _api._pixelize_block_sequence(self.sp_block.value(), self.sp_steps.value())
            parts = [f"{b}px" if b > 1 else "чётко" for b in seq]
            self.preview.setText("Блоки по шагам:   " + "   →   ".join(parts))
        else:
            self.preview.setText(_VIDEO_HINTS.get(effect) or EFFECT_HINTS.get(effect, ""))
        self.adjustSize()

    def values(self):
        return int(self.sp_steps.value()), int(self.sp_block.value())

    def effect(self):
        """Ключ эффекта (frame_reveal.EFFECT_LABELS)."""
        return self.cmb_effect.currentData() or "pixelize"

    def image_values(self):
        """Длительность (сек) и FPS — только в режиме картинки."""
        dur = int(self.sp_dur.value()) if self.sp_dur is not None else 5
        fps = int(self.sp_fps.value()) if self.sp_fps is not None else 25
        return dur, fps

_PixelizeDialog.__module__ = _api.__name__
_api._PixelizeDialog = _PixelizeDialog
