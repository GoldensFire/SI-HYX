# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: _apply_styles. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def _apply_styles(self):
    self.setStyleSheet(f"""
            QWidget {{ color: {_api.C['text']}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {_api.C['surface3']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; padding: 5px 7px; color: {_api.C['text']};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {_api.C['accent']};
            }}
            QPushButton, QToolButton {{
                background: {_api.C['surface3']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; padding: 6px 12px; color: {_api.C['text']};
            }}
            QPushButton:hover, QToolButton:hover {{ background: {_api.C['surface2']}; }}
            QPushButton:disabled {{ color: {_api.C['text3']}; }}
            QPushButton#b_primary {{
                background: {_api.C['accent']}; color: #11111b; border: none; font-weight: 700;
            }}
            QPushButton#b_primary:hover {{ background: {_api.C['accent2']}; }}
            QPushButton#b_primary:disabled {{
                background: {_api.C['surface3']}; color: {_api.C['text3']};
            }}
            QGroupBox {{
                border: 1px solid {_api.C['border']}; border-radius: 6px;
                margin-top: 10px; padding-top: 8px; font-weight: bold;
                color: {_api.C['accent']};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
            QFrame#userCard {{
                border: 1px solid {_api.C['border']}; border-radius: 6px;
                background: {_api.C['surface2']};
            }}
            /* Внутри карточки списка всё тесное: общие отступы полей и кнопок
               раздували её на треть панели настроек. */
            QFrame#userCard QLineEdit, QFrame#userCard QComboBox {{
                padding: 1px 5px; font-size: 11px;
            }}
            QFrame#userCard QToolButton {{
                padding: 1px 4px; font-size: 11px;
            }}
            /* «♪» — переключатель, и нажатое состояние должно быть ВИДНО:
               без этого правила включённая пометка «в основном музыка» выглядела
               ровно как выключенная, и понять, стоит она или нет, было нельзя. */
            QFrame#userCard QToolButton#musicBtn {{ color: {_api.C['text3']}; }}
            QFrame#userCard QToolButton#musicBtn:checked {{
                background: {_api.C['accent']}; border-color: {_api.C['accent']};
                color: #11111b; font-weight: 700;
            }}
            QFrame#userCard QToolButton#musicBtn:checked:hover {{
                background: {_api.C['accent2']};
            }}
            /* Справа оставляем место под стрелку меню. */
            QFrame#userCard QToolButton#statusBtn {{ padding: 1px 16px 1px 6px; }}
            QTableWidget {{
                background: {_api.C['surface']}; border: 1px solid {_api.C['border']};
                border-radius: 6px; outline: none;
            }}
            QHeaderView::section {{
                background: {_api.C['surface2']}; color: {_api.C['text2']};
                border: none; padding: 3px 3px; font-size: 11px;
            }}
            /* Стрелка сортировки — маленькая и без своего места: иначе Qt
               резервирует под неё ~20 px в КАЖДОЙ колонке, и «Раунд» с «Ценой»
               выходили вчетверо шире содержимого. */
            QHeaderView::up-arrow, QHeaderView::down-arrow {{
                width: 7px; height: 7px; subcontrol-position: top center;
            }}
            QTableWidget::item:selected {{ background: {_api.C['surface3']}; color: {_api.C['text']}; }}
            QProgressBar {{
                background: {_api.C['surface']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; text-align: center; color: {_api.C['text']};
            }}
            QProgressBar::chunk {{ background: {_api.C['accent']}; border-radius: 4px; }}
        """)
