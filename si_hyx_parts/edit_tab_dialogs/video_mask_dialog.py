# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_VideoMaskDialog. Public namespace: edit_tab_dialogs."""
import edit_tab_dialogs as _api


class _VideoMaskDialog(_api.QDialog):
    """Диалог рисования маски удаления на одном кадре видео. ПЕРЕИСПОЛЬЗУЕТ
    InpaintCanvas из фоторедактора — то же самое рисование маски кистью, что и при
    удалении объекта с изображения (никакой новой логики рисования). Возвращает
    бинарную маску (numpy H×W uint8) через get_mask(); затем она применяется ко
    ВСЕМ кадрам видео в VideoInpaintWorker."""

    def __init__(self, frame_bgr, parent=None):
        super().__init__(parent)
        # Импорт холста ленивый: тянем тяжёлый модуль только при открытии диалога.
        from photo_tab import InpaintCanvas
        self._InpaintCanvas = InpaintCanvas
        self._mask = None
        self.setWindowTitle("Удаление объекта с видео")
        self.resize(960, 700)

        v = _api.QVBoxLayout(self)
        hint = _api.QLabel(
            "Закрасьте кистью объект (водяной знак, эмодзи, логотип и т.п.), который "
            "нужно убрать со ВСЕГО видео. Маска применяется ко всем кадрам, поэтому "
            "лучше всего подходит для статичных объектов в одном месте экрана.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
        v.addWidget(hint)

        self.canvas = InpaintCanvas()
        self.canvas.set_image_bgr(frame_bgr)
        self.canvas.set_tool(InpaintCanvas.TOOL_MASK)
        self.canvas.set_brush(30)
        v.addWidget(self.canvas, 1)

        ctl = _api.QHBoxLayout()
        lbl = _api.QLabel("Размер кисти:")
        lbl.setStyleSheet(f"color:{_api.C['text2']};")
        ctl.addWidget(lbl)
        sl = _api.QSlider(_api.Qt.Orientation.Horizontal)
        sl.setRange(4, 160)
        sl.setValue(30)
        sl.setFixedWidth(220)
        sl.valueChanged.connect(self.canvas.set_brush)
        ctl.addWidget(sl)
        btn_clear = _api.make_icon_btn("Очистить", icon='fa5s.eraser')
        btn_clear.clicked.connect(self.canvas.clear_mask)
        ctl.addWidget(btn_clear)
        ctl.addStretch(1)
        v.addLayout(ctl)

        bb = _api.QDialogButtonBox()
        self.btn_ok = bb.addButton("Удалить объект с видео",
                                   _api.QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton("Отмена", _api.QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _accept(self):
        m = self.canvas.get_mask()
        if m is None or int(m.max()) == 0:
            _api.msgbox_information(
                self, "Маска пуста",
                "Сначала закрасьте кистью объект, который нужно удалить.")
            return
        self._mask = m
        self.accept()

    def get_mask(self):
        return self._mask

_VideoMaskDialog.__module__ = _api.__name__
_api._VideoMaskDialog = _VideoMaskDialog
