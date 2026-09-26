# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: get_icon. Public namespace: main."""
import main as _api


# ВНИМАНИЕ РАЗРАБОТЧИКА: В этом приложении категорически запрещено использовать
# эмодзи. Все новые иконки добавлять строго через метод get_icon() из библиотеки
# qtawesome! (Реализация — общая функция get_icon() в config.py.)
def get_icon(self, name, color='#cdd6f4'):
    return _api.get_icon(name, color=color)
