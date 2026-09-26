# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""OverlayLayersPanel. Public namespace: edit_tab_overlay."""
import edit_tab_overlay as _api


# ─── Список слоёв ────────────────────────────────────────────────────────────
class OverlayLayersPanel(_api.QWidget):
    """Список наложенных картинок: выбор слоя, кадрирование, сброс, удаление и
    прозрачность выбранного. Панель прячется целиком, когда слоёв нет.

    Панель живёт в узкой (196 px) боковой панели Монтажа, поэтому у всего здесь
    задан ЯВНЫЙ минимальный размер, а строки прокручиваются: раньше при нехватке
    высоты Qt ужимал список до полоски в одну плашку выделения (её и принимали
    за прогресс-бар), а подпись «Прозрачность» наезжала на кнопки слоя.
    Прозрачность разведена на две строки (подпись + процент, под ними ползунок) —
    в одну строку на такой ширине она не помещалась.
    """

    selected = _api.pyqtSignal(int)
    cropRequested = _api.pyqtSignal(int)
    deleteRequested = _api.pyqtSignal(int)
    opacityChanged = _api.pyqtSignal(int, float)
    resetRequested = _api.pyqtSignal(int)

    # Высота списка: одна строка ~22 px. Показываем минимум две (видно, что
    # слоёв может быть несколько), максимум четыре — дальше прокрутка, чтобы
    # панель не выдавливала кнопки и шкалу уровня звука.
    ROW_PX = 22
    MIN_ROWS = 2
    MAX_ROWS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._syncing = False
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        # Заголовок + счётчик слоёв (сразу видно, сколько картинок наложено).
        head = _api.QHBoxLayout(); head.setContentsMargins(0, 0, 0, 0); head.setSpacing(4)
        title = _api.QLabel("Слои (картинки)")
        title.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        head.addWidget(title, 0)
        head.addStretch(1)
        self.lbl_count = _api.QLabel("0")
        self.lbl_count.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self.lbl_count.setMinimumWidth(18)
        self.lbl_count.setStyleSheet(
            f"color: {_api.C['accent']}; background: {_api.C['surface3']};"
            f"border: 1px solid {_api.C['border2']}; border-radius: 7px;"
            "font-size: 10px; font-weight: 700; padding: 0 4px;")
        head.addWidget(self.lbl_count, 0)
        lay.addLayout(head)

        self.list = _api.QListWidget()
        self.list.setIconSize(_api.QSize(24, 16))
        self.list.setUniformItemSizes(True)
        self.list.setTextElideMode(_api.Qt.TextElideMode.ElideMiddle)
        self.list.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(_api.QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setMinimumHeight(self.MIN_ROWS * self.ROW_PX + 8)
        # Выделение — не сплошная заливка акцентом (на сплюснутом списке она и
        # выглядела «полоской прогресса»), а мягкая подложка с акцентной чертой
        # слева. Прозрачная черта у невыбранных строк держит текст на месте.
        self.list.setStyleSheet(f"""
            QListWidget {{ background: {_api.C['surface3']}; color: {_api.C['text2']};
                border: 1px solid {_api.C['border2']}; border-radius: 5px;
                font-size: 11px; outline: none; padding: 2px; }}
            QListWidget::item {{ padding: 2px 4px; border-radius: 3px;
                border-left: 3px solid transparent; }}
            QListWidget::item:hover {{ background: {_api.C['surface2']}; }}
            QListWidget::item:selected {{ background: {_api.C['surface2']};
                color: {_api.C['accent']}; border-left: 3px solid {_api.C['accent']}; }}
        """)
        self.list.currentRowChanged.connect(self._on_row)
        lay.addWidget(self.list)

        row = _api.QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
        self.btn_crop = self._mini('fa5s.crop-alt', "Кадрировать картинку")
        self.btn_crop.clicked.connect(
            lambda: self.cropRequested.emit(self.list.currentRow()))
        self.btn_reset = self._mini('fa5s.undo', "Сбросить поворот и размер")
        self.btn_reset.clicked.connect(
            lambda: self.resetRequested.emit(self.list.currentRow()))
        self.btn_del = self._mini('fa5s.trash-alt', "Удалить слой", danger=True)
        self.btn_del.clicked.connect(
            lambda: self.deleteRequested.emit(self.list.currentRow()))
        row.addWidget(self.btn_crop); row.addWidget(self.btn_reset)
        row.addWidget(self.btn_del); row.addStretch(1)
        lay.addLayout(row)

        lay.addSpacing(2)
        op_head = _api.QHBoxLayout(); op_head.setContentsMargins(0, 0, 0, 0)
        op_head.setSpacing(4)
        lbl = _api.QLabel("Прозрачность")
        lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px;")
        op_head.addWidget(lbl, 0)
        op_head.addStretch(1)
        self.lbl_opacity = _api.QLabel("100%")
        self.lbl_opacity.setStyleSheet(
            f"color: {_api.C['text2']}; font-size: 11px; font-weight: 700;")
        op_head.addWidget(self.lbl_opacity, 0)
        lay.addLayout(op_head)

        self.sld_opacity = _api.QSlider(_api.Qt.Orientation.Horizontal)
        self.sld_opacity.setRange(5, 100)
        self.sld_opacity.setValue(100)
        self.sld_opacity.setFixedHeight(18)
        self.sld_opacity.setToolTip("Прозрачность выбранного слоя")
        self.sld_opacity.valueChanged.connect(self._on_opacity)
        lay.addWidget(self.sld_opacity)

        # Панель никогда не сжимается ниже суммы собственных минимумов — именно
        # это раньше и рождало наложение подписей друг на друга.
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(),
                           _api.QSizePolicy.Policy.Minimum)
        self.setVisible(False)

    def _mini(self, icon, tip, danger=False):
        b = _api.make_icon_btn("")
        b.setIcon(_api.get_icon(icon, color=_api.C['red']) if danger else _api.get_icon(icon))
        b.setIconSize(_api.QSize(14, 14))
        b.setFixedSize(28, 24)
        b.setToolTip(tip)
        b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        if danger:
            b.setStyleSheet(b.styleSheet() + f"""
                QPushButton:hover {{ background: {_api.C['red']}; color: #11111b;
                    border-color: {_api.C['red']}; }}
            """)
        return b

    def _on_row(self, row):
        self._sync_opacity(row)
        self.selected.emit(row)

    def _on_opacity(self, v):
        self.lbl_opacity.setText(f"{int(v)}%")
        row = self.list.currentRow()
        if row >= 0 and not self._syncing:
            self.opacityChanged.emit(row, v / 100.0)

    def _sync_opacity(self, row):
        if 0 <= row < len(self._items):
            self._syncing = True
            self.sld_opacity.setValue(int(round(self._items[row].opacity * 100)))
            self._syncing = False
        self.lbl_opacity.setText(f"{int(self.sld_opacity.value())}%")

    @staticmethod
    def _thumb(item):
        """Значок строки — сама накладка (кадрированная), вписанная в 24×16.
        По нему слой узнаётся быстрее, чем по имени файла."""
        img = item.cropped()
        if img is None or img.isNull():
            return None
        return _api.QIcon(_api.QPixmap.fromImage(
            img.scaled(24, 16, _api.Qt.AspectRatioMode.KeepAspectRatio,
                       _api.Qt.TransformationMode.SmoothTransformation)))

    def refresh(self, items, current=-1):
        """Перестраивает список по актуальным накладкам."""
        self._items = list(items or [])
        self.list.blockSignals(True)
        self.list.clear()
        for it in self._items:
            label = it.name
            if it.crop.width() < 0.999 or it.crop.height() < 0.999:
                label += " (кадр.)"
            row = _api.QListWidgetItem(label)
            row.setToolTip(it.path or label)
            row.setSizeHint(_api.QSize(0, self.ROW_PX))
            icon = self._thumb(it)
            if icon is not None:
                row.setIcon(icon)
            self.list.addItem(row)
        if self._items:
            row = current if 0 <= current < len(self._items) else len(self._items) - 1
            self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        self._sync_opacity(self.list.currentRow())
        has = bool(self._items)
        self.lbl_count.setText(str(len(self._items)))
        # Список ровно под содержимое (но в пределах MIN/MAX строк): одна
        # картинка не должна занимать высоту четырёх, пятая — уезжает в прокрутку.
        rows = max(self.MIN_ROWS, min(self.MAX_ROWS, len(self._items)))
        self.list.setFixedHeight(rows * self.ROW_PX + 8)
        self.setVisible(has)
        for b in (self.btn_crop, self.btn_del, self.btn_reset):
            b.setEnabled(has)
        self.sld_opacity.setEnabled(has)

OverlayLayersPanel.__module__ = _api.__name__
_api.OverlayLayersPanel = OverlayLayersPanel
