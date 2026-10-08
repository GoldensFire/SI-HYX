# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_PixelizeDialog. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api


class _PixelizeDialog(_api.QDialog):
    """Настройка эффекта «проявление из пикселей»: число шагов и стартовый размер
    блока. Превью показывает, как блок мельчает по шагам до чёткой картинки."""

    def __init__(self, steps=6, block=64, parent=None,
                 image_mode=False, duration=5.0, fps=25):
        super().__init__(parent)
        self._image_mode = bool(image_mode)
        self.setWindowTitle("Пикселизация — проявление")
        self.setStyleSheet(f"""
            QDialog {{ background: {_api.C['bg']}; }}
            QLabel {{ color: {_api.C['text2']}; font-size: 12px; }}
            QSpinBox {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 5px 8px; font-size: 13px; min-width: 64px;
            }}
            QSpinBox:focus {{ border-color: {_api.C['accent']}; }}
            QPushButton {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background: {_api.C['border2']}; border-color: {_api.C['accent']}; }}
        """)
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12); lay.setSpacing(10)
        if self._image_mode:
            info = _api.QLabel(
                "Из картинки получится ВИДЕО: кадр начнётся крупными «пикселями» и за "
                "несколько шагов прояснится. Задай длительность ролика и параметры "
                "проявления. Готовое видео сохранится кнопкой «Обрезать».")
        else:
            info = _api.QLabel(
                "Видео начнётся крупными «пикселями» и с каждым шагом будет становиться "
                "чётче, пока не прояснится полностью. Идеально для угадайки. Эффект "
                "применяется при «Обрезать» и требует перекодировки.")
        info.setWordWrap(True); lay.addWidget(info)

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
        row2.addWidget(_api.QLabel("Начальный размер блока, px"))
        self.sp_block = _api.QSpinBox(); self.sp_block.setRange(4, 256)
        self.sp_block.setSingleStep(4); self.sp_block.setValue(int(block))
        row2.addStretch(1); row2.addWidget(self.sp_block)
        lay.addLayout(row2)

        self.preview = _api.QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        lay.addWidget(self.preview)

        self.sp_steps.valueChanged.connect(self._update_preview)
        self.sp_block.valueChanged.connect(self._update_preview)
        self._update_preview()

        bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Ok
                              | _api.QDialogButtonBox.StandardButton.Cancel)
        bb.button(_api.QDialogButtonBox.StandardButton.Ok).setText("Применить")
        bb.button(_api.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _update_preview(self):
        seq = _api._pixelize_block_sequence(self.sp_block.value(), self.sp_steps.value())
        parts = [f"{b}px" if b > 1 else "чётко" for b in seq]
        self.preview.setText("Блоки по шагам:   " + "   →   ".join(parts))

    def values(self):
        return int(self.sp_steps.value()), int(self.sp_block.value())

    def image_values(self):
        """Длительность (сек) и FPS — только в режиме картинки."""
        dur = int(self.sp_dur.value()) if self.sp_dur is not None else 5
        fps = int(self.sp_fps.value()) if self.sp_fps is not None else 25
        return dur, fps

_PixelizeDialog.__module__ = _api.__name__
_api._PixelizeDialog = _PixelizeDialog
