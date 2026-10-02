# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Выбор источника обновления в блоке манги панели базы."""
from PyQt6.QtWidgets import QMenu, QSizePolicy, QToolButton

MANGA_PARTS = ("manga", "remanga", "mangalib")
MANGA_ACTIONS = (
    ("manga", "Каталог манги Shikimori"),
    ("remanga", "Популярность ReManga"),
    ("mangalib", "Популярность MangaLib"),
    ("manga_all", "Все источники манги"),
)


def refresh_button(on_action, parent):
    button = QToolButton(parent)
    button.setText("Обновить")
    button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    button.setStyleSheet("QToolButton { padding-right: 26px; } "
                        "QToolButton::menu-button { width: 24px; }")
    button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    button.clicked.connect(lambda: on_action("manga"))
    menu = QMenu(button)
    for part, text in MANGA_ACTIONS:
        action = menu.addAction(text)
        action.setData(part)
        action.triggered.connect(lambda checked=False, key=part: on_action(key))
    button.setMenu(menu)
    button.setToolTip(
        "Обновить каталог Shikimori. Стрелка справа позволяет отдельно "
        "обновить популярность ReManga, MangaLib или все источники манги.\n"
        "Первый обход популярности требует запроса деталей каждого тайтла "
        "и может занять часы. Загруженные детали сохраняются для продолжения.")
    return button


def sync_menu(button, busy):
    for action in button.menu().actions():
        action.setEnabled(not busy)
