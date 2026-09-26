# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""get_icon. Public namespace: config."""
import config as _api


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  ВНИМАНИЕ РАЗРАБОТЧИКА: В этом приложении категорически запрещено          ║
# ║  использовать эмодзи. Все новые иконки добавлять строго через метод/       ║
# ║  функцию get_icon() из библиотеки qtawesome!                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝
@_api.functools.lru_cache(maxsize=512)
def get_icon(name, color='#cdd6f4', overlay=None, overlay_color=None):
    """Единая точка создания иконок интерфейса. У приложения ТОЛЬКО тёмная тема,
    поэтому по умолчанию иконки светлые — но не «жёсткий» белый, а мягкий
    Catppuccin text (#cdd6f4): лучше смотрится на тёмном фоне. На кнопках со
    СВЕТЛОЙ заливкой (accent/green/red) передавайте тёмный цвет (#11111b/#1e1e2e).
    scale_factor<1 даёт глифу поля внутри иконки — он не упирается в края кнопки.
    name — имя иконки из паков Font Awesome 5 Solid (fa5s.*) или Material Design (mdi6.*).
    overlay — доп. глиф маленьким значком в правом нижнем углу (составная иконка
    для двух одновременных статусов, например «есть комментарий» + «скачан»).

    Результат КЭШИРУЕТСЯ (lru_cache): на старте набегает ~300 вызовов всего на
    ~70 разных значков — одну и ту же info-circle просили под 60 раз. QIcon в Qt
    разделяемый и только для чтения (setIcon копирует его по значению), поэтому
    отдавать один объект нескольким кнопкам безопасно. НО: никогда не вызывайте
    у результата addPixmap()/addFile() — это испортит значок всем, кто получил
    его из кэша; нужен другой значок — просите его с другими аргументами."""
    if overlay:
        return _api.qta.icon(name, overlay, color=color, options=[
            {'scale_factor': 0.8},
            {'color': overlay_color or color, 'scale_factor': 0.5, 'offset': (0.28, 0.28)},
        ])
    return _api.qta.icon(name, color=color, scale_factor=0.8)

get_icon.__module__ = _api.__name__
_api.get_icon = get_icon

def get_icon_pixmap(name, size=16, color='white'):
    """Иконка как QPixmap — для QLabel.setPixmap() (значки без интерактивности)."""
    return _api.get_icon(name, color=color).pixmap(_api.QSize(size, size))

get_icon_pixmap.__module__ = _api.__name__
_api.get_icon_pixmap = get_icon_pixmap

def icon_html(name, size=16, color='white', style=''):
    """Иконка как <img …> для вставки в rich-text (QLabel/HTML), где нельзя
    использовать setIcon(). Заменяет инлайновые эмодзи в HTML-подписях.

    `style` — доп. CSS для самого <img>: например `vertical-align:middle`,
    иначе значок стоит на базовой линии строки и выглядит поднятым над
    текстом (см. карточку пака в «Поиске пакетов»)."""
    from PyQt6.QtCore import QBuffer
    pm = _api.get_icon_pixmap(name, size, color)
    ba = _api.QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    pm.save(buf, 'PNG')
    buf.close()
    b64 = bytes(ba.toBase64()).decode('ascii')
    css = f" style='{style}'" if style else ""
    return (f"<img src='data:image/png;base64,{b64}' "
            f"width='{size}' height='{size}'{css}>")

icon_html.__module__ = _api.__name__
_api.icon_html = icon_html

def status_html(icon_name, text, color='white', size=13):
    """Строка статуса «значок + текст» для QLabel.setText(): значок-эмодзи
    заменён на векторную иконку. Текст экранируется (html.escape), чтобы
    «<script>», «<...>» и т.п. в сообщениях не ломали rich-text рендеринг."""
    import html as _html
    return _api.icon_html(icon_name, size, color) + " " + _html.escape(str(text))

status_html.__module__ = _api.__name__
_api.status_html = status_html
