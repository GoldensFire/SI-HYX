# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_base.py — база вкладки «Монтаж»: импорты, палитра, константы и
# чистые хелперы (ffprobe, время, субтитры/ASS, пикселизация).
#
# Выделено из edit_tab.py (исторически ~12,5к строк одним файлом) в 5 слоёв:
#   edit_tab_base → edit_tab_workers → edit_tab_widgets → edit_tab_dialogs → edit_tab
# Зависимости строго в одну сторону (проверено: обратных рёбер нет).
#
# ВАЖНО: этот модуль выставляет env-переменные Qt-бэкенда (QSG_RHI_BACKEND /
# QT_MEDIA_BACKEND) и определяет _HAS_MULTIMEDIA / LIBASS_AVAILABLE ДО создания
# QApplication — потому и стоит первым в цепочке импортов вкладки.
#
# Адаптировано из standalone-редактора Edit.py (JashaLava) под вкладку SI-HYX.

import os
import json
import math
import subprocess

# Бэкенды Qt нужно выбрать ДО создания QMediaPlayer/QVideoWidget. Модуль
# импортируется в main.py до создания QApplication, поэтому setdefault здесь
# срабатывает вовремя и не перетирает значения, заданные пользователем извне.
from config import SETTINGS_FILE as _SETTINGS_FILE


def _read_bool_setting(key, default=False):
    """Читает булев флаг прямо из settings.json (нужно ДО создания QApplication)."""
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as _f:
            return bool(json.load(_f).get(key, default))
    except Exception:
        return default


# Программный рендер видео отключён всегда (настройка убрана из UI): окно видео
# идёт по аппаратному D3D/GL-свопчейну.
os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
# QT_FFMPEG_DECODING_HW_DEVICE_TYPES (HW-декодер H.264/HEVC) задаёт config.py,
# импортируемый выше, — он читает настройку video_hw_decode.
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from PyQt6.QtCore import (Qt, QRect, QSize)
from PyQt6.QtWidgets import (QApplication, QPushButton, QFrame)
from PyQt6.QtGui import (QPainter, QColor, QPen, QFont, QPixmap, QIcon)

# Нативный рендер ASS/SSA для превью (libass). Если DLL нет/не загрузились —
# LIBASS_AVAILABLE=False, и субтитры показываются обычным текстовым оверлеем.
try:
    import libass_renderer as _libass
    LIBASS_AVAILABLE = bool(_libass.AVAILABLE)
except Exception:
    _libass = None
    LIBASS_AVAILABLE = False

# Мультимедиа PyQt6 поставляется вместе с основным wheel'ом, но на некоторых
# урезанных сборках его может не быть — деградируем мягко (заглушка во вкладке).
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _HAS_MULTIMEDIA = True
except Exception:
    # Имена обязаны СУЩЕСТВОВАТЬ даже без мультимедиа: верхние слои
    # (edit_tab_widgets / edit_tab.py) импортируют их отсюда на уровне модуля, и
    # без заглушек такой импорт падал бы ImportError — вкладка «Монтаж» роняла бы
    # всё приложение вместо мягкой деградации. Пока всё жило одним файлом, этой
    # проблемы не было (неопределённые имена просто не трогались под гардом
    # _HAS_MULTIMEDIA). Использовать их можно ТОЛЬКО при _HAS_MULTIMEDIA=True.
    QMediaPlayer = QAudioOutput = QVideoSink = QVideoWidget = None
    _HAS_MULTIMEDIA = False

# Пути к ffmpeg/ffprobe и флаг скрытия консоли берём из общей конфигурации SI-HYX,
# чтобы редактор работал и в собранном .exe с bundled-ffmpeg.
from config import (FFPROBE, CREATE_NO_WINDOW, CONFIG_DIR, get_icon)

EDITOR_SETTINGS_PATH = os.path.join(CONFIG_DIR, "editor_settings.json")


# ─── Color Palette ───────────────────────────────────────────────────────────
# Палитра вкладки приведена к общему стилю приложения (Catppuccin Mocha,
# см. STYLESHEET в config.py), чтобы «Монтаж» не выбивался из остальных вкладок.
C = {
    "bg":        "#1e1e2e",   # base
    "surface":   "#181825",   # mantle
    "surface2":  "#24273a",   # surface0-ish (панели)
    "surface3":  "#313244",   # surface0 (поля/кнопки)
    "border":    "#45475a",   # surface1
    "border2":   "#585b70",   # surface2
    "accent":    "#89b4fa",   # blue
    "accent2":   "#b4befe",   # lavender (hover)
    "green":     "#a6e3a1",   # green
    "green2":    "#94e2d5",   # teal
    "red":       "#f38ba8",   # red
    "red2":      "#eba0ac",   # maroon
    "yellow":    "#f9e2af",   # yellow
    "text":      "#cdd6f4",   # text
    "text2":     "#a6adc8",   # subtext0
    "text3":     "#6c7086",   # overlay0
    "playhead":  "#f9e2af",   # yellow
    "wave_bg":   "#45475a",
    "wave_sel":  "#89b4fa",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────
def run_ffprobe(path):
    cmd = [FFPROBE, "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=True,
                           encoding="utf-8", errors="replace",
                           creationflags=CREATE_NO_WINDOW)
        return json.loads(p.stdout)
    except Exception:
        return None


def time_to_s(hms_str: str) -> float:
    parts = [p for p in hms_str.split(':') if p]
    if not parts:
        return 0.0
    try:
        partsf = [float(p) for p in parts]
    except Exception:
        return 0.0
    if len(partsf) == 3:
        h, m, s = partsf
        return h * 3600 + m * 60 + s
    elif len(partsf) == 2:
        m, s = partsf
        return m * 60 + s
    else:
        return partsf[0]


def s_to_time(seconds: float) -> str:
    if seconds is None:
        return "00:00:00.000"
    s = float(seconds)
    if not math.isfinite(s) or s < 0:
        return "00:00:00.000"
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"


def format_fps(fps):
    if fps is None:
        return "—"
    try:
        f = float(fps)
    except Exception:
        return str(fps)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    else:
        txt = f"{f:.3f}"
        txt = txt.rstrip('0').rstrip('.')
        return txt


def _fmt_channels(ainfo):
    """Человекочитаемое описание числа каналов аудио: 1 → «моно», 2 → «стерео»,
    6 → «5.1», 8 → «7.1», иначе «Nch». Берётся channel_layout, если он есть."""
    info = ainfo or {}
    try:
        ch = int(info.get('channels'))
    except Exception:
        ch = None
    layout = (info.get('channel_layout') or '').lower()
    if ch == 1 or layout == 'mono':
        return "моно"
    if ch == 2 or layout == 'stereo':
        return "стерео"
    if ch == 6 or layout.startswith('5.1'):
        return "5.1"
    if ch == 8 or layout.startswith('7.1'):
        return "7.1"
    if ch:
        return f"{ch}ch"
    return "—"


def _unique_output(path: str) -> str:
    """Возвращает путь, которого ещё нет на диске: к имени добавляется _1, _2…
    перед расширением (foo_обрез.mp4 → foo_обрез_1.mp4). Используется, когда
    «Перезаписать» выключено, а файл с целевым именем уже существует —
    результат просто сохраняется под новым именем."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = f"{base}_{i}{ext}"
        if not os.path.exists(cand):
            return cand
        i += 1


# ─── Small UI helpers ─────────────────────────────────────────────────────────
def make_divider():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {C['border']}; border: none; border-top: 1px solid {C['border']};")
    line.setFixedHeight(1)
    return line


def make_icon_btn(text, icon_std=None, accent=False, danger=False, w=None, icon=None):
    btn = QPushButton(text)
    # На светлой заливке (accent/danger) — тёмные значок и текст: контраст лучше,
    # чем белый по светло-голубому/розовому (ср. кнопку «НАЧАТЬ» — тёмное по зелёному).
    on_fill = accent or danger
    fg = "#11111b" if on_fill else C["text"]
    if icon:
        # Векторная иконка qtawesome (см. get_icon в config.py).
        btn.setIcon(get_icon(icon, color=fg))
        btn.setIconSize(QSize(20, 20))
    elif icon_std:
        btn.setIcon(QApplication.style().standardIcon(icon_std))
    base_bg = C["accent"] if accent else (C["red"] if danger else C["surface3"])
    hover_bg = C["accent2"] if accent else (C["red2"] if danger else C["border2"])
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {base_bg};
            color: {fg};
            border: 1px solid {C['border2'] if not accent and not danger else 'transparent'};
            border-radius: 6px;
            padding: 7px 14px;
            font-weight: 500;
            font-size: 13px;
        }}
        QPushButton:hover {{ background: {hover_bg}; }}
        QPushButton:pressed {{ background: {C['surface2']}; }}
        QPushButton:disabled {{
            background: {C['surface2']};
            color: {C['text3']};
            border: 1px solid {C['border2']};
        }}
    """)
    if w:
        btn.setFixedWidth(w)
    return btn


def _fullscreen_icon(expand=True, color="#ffffff", size=32):
    """Рисует значок полноэкранного режима «как на YouTube» — четыре уголка.
    expand=True  → уголки в углах рамки (войти в полноэкранный режим);
    expand=False → уголки сдвинуты к центру (выйти из полноэкранного)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(2.0, size * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    m = size * 0.22          # отступ уголков от края рамки
    arm = size * 0.20        # длина «плеча» уголка
    cen = size / 2.0
    if expand:
        # Уголки в четырёх углах, плечи смотрят внутрь.
        corners = [(m, m, 1, 1), (size - m, m, -1, 1),
                   (m, size - m, 1, -1), (size - m, size - m, -1, -1)]
    else:
        # Уголки стянуты к центру, плечи смотрят наружу (к углам экрана).
        g = size * 0.10
        corners = [(cen - g, cen - g, -1, -1), (cen + g, cen - g, 1, -1),
                   (cen - g, cen + g, -1, 1), (cen + g, cen + g, 1, 1)]
    for cx, cy, dx, dy in corners:
        p.drawLine(int(cx), int(cy), int(cx + dx * arm), int(cy))
        p.drawLine(int(cx), int(cy), int(cx), int(cy + dy * arm))
    p.end()
    return QIcon(pm)


def _parse_srt(text):
    """Простой парсер SRT → список (start_s, end_s, text). Теги (<...>, {\\...})
    вырезаются — для превью нужен чистый текст в стиле VLC."""
    import re
    cues = []
    if not text:
        return cues

    def _ts(s):
        s = s.replace(',', '.').strip()
        try:
            hh, mm, rest = s.split(':')
            return int(hh) * 3600 + int(mm) * 60 + float(rest)
        except Exception:
            return None

    blocks = re.split(r'\r?\n\r?\n', text.strip())
    tag_re = re.compile(r'<[^>]+>|\{[^}]*\}')
    time_re = re.compile(r'(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})')
    for b in blocks:
        lines = [ln for ln in b.splitlines() if ln.strip() != '']
        if not lines:
            continue
        # Находим строку с таймкодами (может быть после номера-индекса).
        ti = None
        for i, ln in enumerate(lines):
            m = time_re.search(ln)
            if m:
                ti = i; tm = m; break
        if ti is None:
            continue
        start = _ts(tm.group(1)); end = _ts(tm.group(2))
        if start is None or end is None:
            continue
        body = "\n".join(lines[ti + 1:]).strip()
        body = tag_re.sub('', body).strip()
        if body:
            cues.append((start, end, body))
    cues.sort(key=lambda c: c[0])
    return cues


def _paint_subtitle(painter, rect, text="", px=28, image=None, image_pos=(0, 0)):
    """Рисует субтитры в области rect: либо готовый кадр от libass (image,
    приоритетнее), либо стиль VLC — белый жирный текст с чёрной обводкой снизу
    по центру. Используется и оверлеем-окном, и встроенным рендером в кадр."""
    if image is not None and not image.isNull():
        painter.drawImage(rect.left() + image_pos[0], rect.top() + image_pos[1], image)
        return
    if not text:
        return
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont("Arial"); f.setBold(True); f.setPixelSize(px)
    painter.setFont(f)
    margin_v = max(10, int(rect.height() * 0.05))
    side = int(rect.width() * 0.05)
    area = QRect(rect.left() + side, rect.top(),
                 max(10, rect.width() - 2 * side),
                 max(10, rect.height() - margin_v))
    flags = (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
             | Qt.TextFlag.TextWordWrap)
    o = max(2, px // 11)   # толщина обводки
    painter.setPen(QPen(QColor(0, 0, 0)))
    for dx in (-o, 0, o):
        for dy in (-o, 0, o):
            if dx == 0 and dy == 0:
                continue
            painter.drawText(area.translated(dx, dy), flags, text)
    painter.setPen(QPen(QColor(255, 255, 255)))
    painter.drawText(area, flags, text)


def _paint_subtitle_styled(painter, rect, text, style=None):
    """Стилизованный рендер субтитров для превью в SubtitleCreatorDialog: шрифт,
    размер, жирный/курсив/подчёркивание, трекинг, выравнивание (numpad 1-9) и
    цвета — как в стиле реплики (см. DEFAULT_SUBTITLE_STYLE). Размер/трекинг
    заданы в единицах ASS PlayResY (288) и масштабируются в экранные px по
    высоте rect — так же, как libass масштабирует их при вшивании через ffmpeg,
    поэтому превью примерно совпадает с итоговым видео. НЕ используется вне
    этого диалога — обычный VLC-стиль оверлея (_paint_subtitle) не трогаем."""
    if not text:
        return
    style = style or DEFAULT_SUBTITLE_STYLE
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    scale = rect.height() / _ASS_PLAYRES_Y if rect.height() > 0 else 1.0
    px = max(8, int(round(float(style.get('size') or 20) * scale)))
    f = QFont(style.get('font') or 'Arial')
    f.setBold(bool(style.get('bold')))
    f.setItalic(bool(style.get('italic')))
    f.setUnderline(bool(style.get('underline')))
    f.setPixelSize(px)
    spacing = float(style.get('spacing') or 0) * scale
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    painter.setFont(f)

    align = int(style.get('align') or 2)
    row = (align - 1) // 3; col = (align - 1) % 3
    h_flag = (Qt.AlignmentFlag.AlignLeft if col == 0
              else Qt.AlignmentFlag.AlignRight if col == 2
              else Qt.AlignmentFlag.AlignHCenter)
    v_flag = (Qt.AlignmentFlag.AlignBottom if row == 0
              else Qt.AlignmentFlag.AlignTop if row == 2
              else Qt.AlignmentFlag.AlignVCenter)
    margin_v = max(6, int(rect.height() * 0.05))
    side = max(6, int(rect.width() * 0.04))
    area = QRect(rect.left() + side, rect.top() + margin_v,
                 max(10, rect.width() - 2 * side),
                 max(10, rect.height() - 2 * margin_v))
    flags = int(h_flag | v_flag | Qt.TextFlag.TextWordWrap)
    o = max(1, px // 11)
    outline = QColor(style.get('outline_color') or '#000000')
    fill = QColor(style.get('color') or '#FFFFFF')
    painter.setPen(QPen(outline))
    for dx in (-o, 0, o):
        for dy in (-o, 0, o):
            if dx == 0 and dy == 0:
                continue
            painter.drawText(area.translated(dx, dy), flags, text)
    painter.setPen(QPen(fill))
    painter.drawText(area, flags, text)


def _ass_timestamp(t):
    """Секунды → таймкод ASS «H:MM:SS.cc» (сотые доли, без ведущего нуля у часов)."""
    t = max(0.0, float(t))
    h = int(t // 3600); m = int((t % 3600) // 60); s = t - h * 3600 - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _hex_to_ass_color(hex_color, alpha=0x00):
    """«#RRGGBB» → цвет ASS «&HAABBGGRR» (порядок байт обратный HTML)."""
    hc = (hex_color or "#FFFFFF").lstrip('#')
    if len(hc) != 6:
        hc = "FFFFFF"
    r, g, b = hc[0:2], hc[2:4], hc[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


# Стиль субтитров по умолчанию (используется, пока у реплики нет собственного
# переопределения — см. SubtitleCreatorDialog._effective_style).
DEFAULT_SUBTITLE_STYLE = {
    'font': 'Arial', 'size': 20, 'bold': True, 'italic': False, 'underline': False,
    'align': 2, 'spacing': 0, 'color': '#FFFFFF', 'outline_color': '#000000',
    'animation': 'none',
}
_ASS_PLAYRES_X, _ASS_PLAYRES_Y = 384, 288
_ASS_MARGIN_L, _ASS_MARGIN_R, _ASS_MARGIN_V = 10, 10, 20


def _animation_override_tags(anim, align, duration_s):
    """Строит override-теги ASS ({\\...}) для простой анимации появления —
    fade/slide/pop. Тайминг анимации — треть длительности реплики (но не больше
    300мс и не меньше 50мс), чтобы короткие реплики не «залипали» в анимации."""
    if anim not in ('fade', 'slide', 'pop'):
        return ''
    dur_ms = max(10, int(round(duration_s * 1000)))
    t = min(300, max(50, dur_ms // 3))
    if anim == 'fade':
        return f"{{\\fad({t},{t})}}"
    if anim == 'pop':
        return f"{{\\fscx0\\fscy0\\t(0,{t},\\fscx100\\fscy100)}}"
    # slide: анкер — точка, куда libass поместил бы текст по Alignment (см.
    # обычные формулы ASS для \pos/\move), старт — со смещением за пределы
    # кадра со стороны, соответствующей горизонтали/вертикали выравнивания.
    row = (align - 1) // 3; col = (align - 1) % 3
    x = (_ASS_PLAYRES_X / 2 if col == 1
         else (_ASS_MARGIN_L if col == 0 else _ASS_PLAYRES_X - _ASS_MARGIN_R))
    y = (_ASS_PLAYRES_Y - _ASS_MARGIN_V if row == 0
         else (_ASS_PLAYRES_Y / 2 if row == 1 else _ASS_MARGIN_V))
    if col == 0:
        x0, y0 = -60, y
    elif col == 2:
        x0, y0 = _ASS_PLAYRES_X + 60, y
    elif row == 0:
        x0, y0 = x, _ASS_PLAYRES_Y + 40
    elif row == 2:
        x0, y0 = x, -40
    else:
        x0, y0 = x, y
    return f"{{\\move({x0:.0f},{y0:.0f},{x:.0f},{y:.0f},0,{t})}}"


def _style_line(name, style):
    font = style.get('font') or DEFAULT_SUBTITLE_STYLE['font']
    size = int(style.get('size') or DEFAULT_SUBTITLE_STYLE['size'])
    bold = 1 if style.get('bold') else 0
    italic = 1 if style.get('italic') else 0
    underline = 1 if style.get('underline') else 0
    spacing = int(style.get('spacing') or 0)
    align = int(style.get('align') or 2)
    primary = _hex_to_ass_color(style.get('color') or '#FFFFFF')
    outline = _hex_to_ass_color(style.get('outline_color') or '#000000')
    return (f"Style: {name},{font},{size},{primary},&H000000FF,{outline},&H00000000,"
            f"{bold},{italic},{underline},0,100,100,{spacing},0,1,1,0,{align},"
            f"{_ASS_MARGIN_L},{_ASS_MARGIN_R},{_ASS_MARGIN_V},1")


_ASS_TEMPLATE = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    f"PlayResX: {_ASS_PLAYRES_X}\n"
    f"PlayResY: {_ASS_PLAYRES_Y}\n"
    "WrapStyle: 0\n"
    "ScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding\n"
    "{styles}\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "{events}\n"
)


def _cues_to_ass(cues):
    """Собирает реплики в .ass. `cues` — список словарей {start,end,text,style};
    `style` уже разрешён (переопределение реплики или общий стиль по умолчанию —
    см. SubtitleCreatorDialog._effective_style). У каждой реплики СВОЙ именованный
    Style (без де-дупликации: так проще и надёжнее, чем сравнивать стили).
    Позиция/анимация — часть самого файла (Alignment + override-теги), а не
    «стиля вшивания», поэтому действует и в превью (libass), и при вшивании
    (ffmpeg -vf subtitles), независимо от выбора «Стиль вшитых субтитров»."""
    styles_txt = []
    events = []
    for i, c in enumerate(cues):
        name = f"Cue{i}"
        style = c['style']
        styles_txt.append(_style_line(name, style))
        txt = c['text'].replace("{", "｛").replace("}", "｝")
        txt = txt.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")
        align = int(style.get('align') or 2)
        anim_tag = _animation_override_tags(
            style.get('animation', 'none'), align, max(0.01, c['end'] - c['start']))
        events.append(f"Dialogue: 0,{_ass_timestamp(c['start'])},{_ass_timestamp(c['end'])},"
                       f"{name},,0,0,0,,{anim_tag}{txt}")
    return _ASS_TEMPLATE.format(styles="\n".join(styles_txt), events="\n".join(events))


_SUBTITLE_PRESETS_PATH = os.path.join(CONFIG_DIR, "subtitle_presets.json")


def _load_subtitle_presets():
    """Читает именованные пресеты стиля субтитров (НЕ путать с общими настройками
    приложения — отдельный файл, чтобы не трогать реальный settings.json)."""
    for path in (_SUBTITLE_PRESETS_PATH, _SUBTITLE_PRESETS_PATH + ".bak"):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception:
            continue
    return {}


def _save_subtitle_presets(presets):
    """Атомарная запись (tmp+.bak+os.replace) с защитой от затирания пустым
    словарём — та же схема, что и utils.save_settings, но для отдельного файла."""
    try:
        if not presets:
            for p in (_SUBTITLE_PRESETS_PATH, _SUBTITLE_PRESETS_PATH + ".bak"):
                if os.path.exists(p) and os.path.getsize(p) > 2:
                    return
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(_SUBTITLE_PRESETS_PATH), exist_ok=True)
        tmp = _SUBTITLE_PRESETS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        try:
            if os.path.exists(_SUBTITLE_PRESETS_PATH):
                os.replace(_SUBTITLE_PRESETS_PATH, _SUBTITLE_PRESETS_PATH + ".bak")
        except Exception:
            pass
        os.replace(tmp, _SUBTITLE_PRESETS_PATH)
    except Exception:
        pass


# Минимальный размер блока для ПРЕДпоследнего (последнего «блочного») шага.
# Раньше геометрия шла до 1px, и предпоследний шаг выходил ~2px — а 2px визуально
# почти неотличим от чёткого кадра, шаг получался «пустым». Держим пол в 6px:
# последний блочный шаг всегда заметно пикселизирован, потом сразу «чётко».
_PIXELIZE_MIN_BLOCK = 6


def _pixelize_block_sequence(block0, steps):
    """Размеры блока (px) по шагам проявления: геометрически убывают от block0 до
    пола (_PIXELIZE_MIN_BLOCK), а самый последний шаг — «чётко» (1). Каждый
    следующий блок мельче → «пикселей становится больше», пока кадр не прояснится.
    При steps==1 — один статичный уровень (block0) без финального прояснения.
    Предпоследний шаг не опускается ниже пола (5px), чтобы не было «пустого» 2px-
    шага у самой чёткости."""
    block0 = max(2, int(block0)); steps = max(1, int(steps))
    if steps == 1:
        return [max(1, min(1024, block0))]
    floor = min(block0, _PIXELIZE_MIN_BLOCK)   # пол не выше самого block0
    n_block = steps - 1                        # шаги до финального «чётко»
    seq = []
    for i in range(n_block):
        if n_block == 1:
            b = block0
        else:
            # i=0 → block0, i=n_block-1 → floor (геометрически между ними).
            t = i / (n_block - 1)
            b = block0 * (floor / block0) ** t
        seq.append(max(1, min(1024, int(round(b)))))
    seq.append(1)                              # финальный шаг — чётко
    return seq
