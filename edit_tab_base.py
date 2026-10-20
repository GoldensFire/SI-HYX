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
import struct
import subprocess

# Бэкенды Qt нужно выбрать ДО создания QMediaPlayer/QVideoWidget. Модуль
# импортируется в main.py до создания QApplication, поэтому setdefault ниже
# срабатывает вовремя и не перетирает значения, заданные пользователем извне.

# Графический бэкенд сцены Qt Quick (на нём работает холст видео «Монтажа» —
# см. VideoCanvas). Программный рендер отключён всегда (настройка убрана из UI),
# а из двух аппаратных на Windows берём РОДНОЙ D3D11: замер того же холста на
# одном файле (tools/bench_video_path.py, режим montage, 1080p60, окно
# 1100x640) — d3d11 ЦП 19.7%, GUI-поток 5.3%; opengl ЦП 50.5%, GUI-поток 12.9%.
# Здесь opengl остался с тех пор, когда единственной альтернативой был
# "software" (обходной путь для оверлея RivaTuner), и осознанным выбором против
# d3d11 никогда не был. setdefault сохраняет приоритет за переменной окружения:
# QSG_RHI_BACKEND=opengl снаружи по-прежнему всё переключает обратно.
os.environ.setdefault("QSG_RHI_BACKEND", "d3d11" if os.name == "nt" else "opengl")
# Ожидание GPU — в Present(), а не в beginFrame(). По умолчанию Qt 6.10 на D3D
# держит очередь в 2 кадра через FRAME_LATENCY_WAITABLE_OBJECT и ждёт его в
# beginFrame() — а поток рендера Qt Quick зовёт beginFrame() ДО синхронизации
# сцены, пока GUI-поток стоит в polishAndSync. Когда GPU занят игрой, этот
# объект освобождается через 30–400 мс — и столько же стоял GUI-поток на каждом
# кадре холста «Монтажа». Без объекта ждёт Present(), уже после того как
# GUI-поток отпущен; глубину очереди и так ограничивают два буфера цепочки
# обмена. Замер (холст, синтетика ~100% GPU, 8–10 кадров/с): GUI-поток в
# ожидании синхронизации 50–85% времени → 0–7%. При 15–24 кадрах/с число
# кадров то же; при крайней перегрузке (2–6 кадров/с) их выходит ровнее, но в
# среднем меньше (~2.5 против 2–6) — зато интерфейс не стоит.
if os.name == "nt":
    os.environ.setdefault("QT_D3D_MAX_FRAME_LATENCY", "0")
# QT_FFMPEG_DECODING_HW_DEVICE_TYPES (HW-декодер H.264/HEVC) задаёт config.py,
# импортируемый выше, — он читает настройку video_hw_decode.
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from PyQt6.QtCore import (Qt, QSize, QPointF)
from PyQt6.QtWidgets import (QApplication, QPushButton, QFrame)
from PyQt6.QtGui import (QPainter, QColor, QPen, QFont, QPixmap, QIcon,
                         QFontDatabase, QFontMetricsF, QPainterPath,
                         QPainterPathStroker, QRawFont, QTransform)

# Вид программных субтитров — караоке генератора паков (см. PROG_SUB_FONTSIZE).
from karaoke import style as _karaoke_style

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
    from PyQt6.QtMultimedia import (QAudioFormat, QAudioSink, QMediaPlayer,
                                    QAudioOutput, QVideoSink, QMediaDevices)
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
    QMediaDevices = QAudioFormat = QAudioSink = None
    _HAS_MULTIMEDIA = False
# Копия звука, который плеер прямо сейчас отдаёт устройству (Qt 6.8+): по ней
# «Монтаж» узнаёт, что после перемотки на ходу пошёл звук нового места.
try:
    from PyQt6.QtMultimedia import QAudioBufferOutput
except Exception:
    QAudioBufferOutput = None

# Пути к ffmpeg/ffprobe и флаг скрытия консоли берём из общей конфигурации SI-HYX,
# чтобы редактор работал и в собранном .exe с bundled-ffmpeg.
from config import (FFPROBE, CREATE_NO_WINDOW, CONFIG_DIR, get_icon)

EDITOR_SETTINGS_PATH = os.path.join(CONFIG_DIR, "editor_settings.json")
# Проект «Монтажа» из кусков (montage_project): сохраняется сам после каждой
# правки и переживает перезапуск.
MONTAGE_PROJECT_PATH = os.path.join(CONFIG_DIR, "montage_project.json")


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

def install_audio_device_recovery(audio_output, owner=None):
    """Пере-привязывает QAudioOutput к текущему устройству вывода, когда набор
    звуковых устройств меняется. Возвращает объект-наблюдатель (его надо где-то
    держать) или None.

    Зачем: сеанс WASAPI привязан к КОНКРЕТНОМУ устройству. Стоит отключить
    наушники, выключить устройство в «Звуке» или перезапуститься драйверу — и
    сеанс аннулируется. Qt пишет это в консоль как
    `IAudioClient3::GetCurrentPadding failed "AUDCLNT_E_DEVICE_INVALIDATED"`,
    а плеер остаётся с мёртвым выводом: видео идёт, звука нет до перезапуска.
    setDevice() пересоздаёт сеанс на живом устройстве.

    Громкость и «без звука» переносим руками: setDevice поднимает новый sink
    со своими значениями по умолчанию."""
    if QMediaDevices is None or audio_output is None:
        return None
    try:
        watcher = QMediaDevices(owner if owner is not None else audio_output)
    except Exception:
        return None

    def _reattach():
        try:
            dev = QMediaDevices.defaultAudioOutput()
            if dev is None or dev.isNull():
                return
            vol, muted = audio_output.volume(), audio_output.isMuted()
            audio_output.setDevice(dev)
            audio_output.setVolume(vol)
            audio_output.setMuted(muted)
        except Exception:
            pass

    try:
        watcher.audioOutputsChanged.connect(_reattach)
    except Exception:
        return None
    return watcher

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

# ── Программный стиль субтитров — как у караоке в генерации паков ────────────
# Текстовые субтитры без собственного стиля Монтаж рисует сам: шрифт Karaoke
# Rounded (Nunito Black из karaoke/fonts), почти белый текст, тёмная обводка и
# полупрозрачная тень — ровно как подписи караоке-видео. Цвета, обводку и тень
# берём из karaoke/style.py, чтобы стиль был один на оба места. Размер —
# субтитровый: у караоке текст единственный в кадре (кегль 1/11.25 высоты), а
# поверх видео такой занял бы пятую часть кадра.
#
# Всё задано в единицах ASS при PlayResY 288 — на таком холсте ffmpeg вшивает
# SRT. Превью переводит их в пиксели ТЕМИ ЖЕ правилами, что и libass
# (_ass_text_metrics), поэтому субтитры в плеере и в готовом файле совпадают.
PROG_SUB_FONTSIZE = 21          # кегль ASS: em ≈ 5.3 % высоты кадра
PROG_SUB_MARGIN_V = 14          # отступ снизу ≈ 4.9 % высоты кадра

_KARAOKE_FAMILY = None
_ASS_METRICS = {}
_ASS_TEXT_CACHE = {}


def _karaoke_font_family():
    """Семейство шрифта караоке для Qt; шрифт регистрируется один раз.

    Шрифт не системный, поэтому Qt (превью, список шрифтов «Создать субтитры»)
    его без регистрации не видит. До создания QApplication регистрировать
    нечем — тогда отвечаем Arial, но не запоминаем."""
    global _KARAOKE_FAMILY
    if _KARAOKE_FAMILY is not None:
        return _KARAOKE_FAMILY
    if QApplication.instance() is None:
        return "Arial"
    family = ""
    try:
        fid = QFontDatabase.addApplicationFont(str(_karaoke_style.FONT_FILE))
        if fid >= 0 and _karaoke_style.FONT_NAME in QFontDatabase.applicationFontFamilies(fid):
            family = _karaoke_style.FONT_NAME
    except Exception:
        family = ""
    _KARAOKE_FAMILY = family or "Arial"
    return _KARAOKE_FAMILY


def _ass_text_metrics(font):
    """(em/кегль, доля асцендера) шрифта так, как их считает libass.

    Кегль ASS у libass — высота winAscent+winDescent из таблицы OS/2 (так
    считал VSFilter), а не em, как у Qt. У Arial em = 0.895 кегля, у Nunito
    Black — всего 0.726: прими превью кегль за em, и текст в плеере вышел бы
    на 38 % крупнее вшитого. Межстрочный шаг libass — сам кегль, базовая линия
    стоит на доле hhea-асцендера от него."""
    key = (font.family(), font.bold(), font.italic())
    hit = _ASS_METRICS.get(key)
    if hit is not None:
        return hit
    ratio, asc_frac = 0.9, 0.8
    try:
        probe = QFont(font)
        probe.setPixelSize(100)
        raw = QRawFont.fromFont(probe)
        head = bytes(raw.fontTable("head"))
        os2 = bytes(raw.fontTable("OS/2"))
        hhea = bytes(raw.fontTable("hhea"))
        upem = struct.unpack(">H", head[18:20])[0]
        win_a, win_d = struct.unpack(">HH", os2[74:78])
        asc, desc = struct.unpack(">hh", hhea[4:8])
        if upem > 0 and win_a + win_d > 0:
            ratio = upem / float(win_a + win_d)
        if asc - desc > 0:
            asc_frac = asc / float(asc - desc)
    except Exception:
        pass
    _ASS_METRICS[key] = (ratio, asc_frac)
    return ratio, asc_frac


def _wrap_ass_text(text, fm, width):
    """Строки текста с переносом по словам, как WrapStyle 0 у libass: сперва
    жадно, затем слова переезжают вниз, пока соседние строки от этого
    становятся ровнее (верхняя остаётся чуть шире). Явные переносы — свои."""
    out = []
    for para in str(text).split("\n"):
        words = [w for w in para.strip().split(" ") if w]
        if not words:
            out.append("")
            continue
        lines, cur = [], ""
        for w in words:
            cand = w if not cur else cur + " " + w
            if cur and fm.horizontalAdvance(cand) > width:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        lines.append(cur)
        moved = True
        while moved and len(lines) > 1:
            moved = False
            for i in range(len(lines) - 1):
                top, bottom = lines[i], lines[i + 1]
                if " " not in top:
                    continue
                head, last = top.rsplit(" ", 1)
                new_bottom = last + " " + bottom
                old = abs(fm.horizontalAdvance(top) - fm.horizontalAdvance(bottom))
                new = abs(fm.horizontalAdvance(head) - fm.horizontalAdvance(new_bottom))
                if new < old:
                    lines[i], lines[i + 1] = head, new_bottom
                    moved = True
        out.extend(lines)
    return out


def _ass_text_shape(text, rect_w, rect_h, family, size, bold, italic, underline,
                    spacing, align, margin_l, margin_r, margin_v, outline,
                    play_res):
    """Контуры текста (path) и его «тела» с обводкой (body, для тени) в
    координатах области rect_w×rect_h. Считается один раз на текст и размер."""
    key = (text, rect_w, rect_h, family, round(size, 3), bold, italic, underline,
           round(spacing, 3), align, margin_l, margin_r, margin_v,
           round(outline, 3), play_res)
    hit = _ASS_TEXT_CACHE.get(key)
    if hit is not None:
        return hit
    scale_y = rect_h / float(play_res[1])
    scale_x = rect_w / float(play_res[0])
    font = QFont(family)
    font.setBold(bool(bold))
    font.setItalic(bool(italic))
    font.setUnderline(bool(underline))
    ratio, asc_frac = _ass_text_metrics(font)
    size_px = max(1.0, size * scale_y)
    # Контуры строим в крупном кегле и масштабируем: setPixelSize целый, и у
    # маленького превью округление em сдвигало бы размер на проценты.
    ref = 200.0
    font.setPixelSize(int(ref))
    k = size_px * ratio / ref
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                              spacing * scale_y / k)
    fm = QFontMetricsF(font)
    ml, mr, mv = margin_l * scale_x, margin_r * scale_x, margin_v * scale_y
    avail = max(1.0, rect_w - ml - mr)
    lines = _wrap_ass_text(text, fm, avail / k)
    block = size_px * len(lines)
    row, col = (int(align) - 1) // 3, (int(align) - 1) % 3
    top = (rect_h - mv - block if row == 0
           else (rect_h - block) / 2.0 if row == 1 else mv)
    ref_path = QPainterPath()
    for i, line in enumerate(lines):
        if not line:
            continue
        w = fm.horizontalAdvance(line) * k
        x = ml if col == 0 else (rect_w - mr - w if col == 2 else ml + (avail - w) / 2.0)
        base = top + i * size_px + size_px * asc_frac
        ref_path.addText(QPointF(x / k, base / k), font, line)
    path = QTransform.fromScale(k, k).map(ref_path)
    body = path
    if outline > 0:
        stroker = QPainterPathStroker()
        stroker.setWidth(2.0 * outline * scale_y)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        body = stroker.createStroke(path).united(path)
    if len(_ASS_TEXT_CACHE) >= 24:
        _ASS_TEXT_CACHE.pop(next(iter(_ASS_TEXT_CACHE)))
    _ASS_TEXT_CACHE[key] = (path, body, scale_y)
    return path, body, scale_y


def _style_num(style, key, default):
    """Число из стиля реплики; нет ключа (стиль сохранён до караоке-вида) или
    он пуст — прежнее значение по умолчанию."""
    try:
        value = style.get(key)
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _paint_ass_text(painter, rect, text, style, margins=None,
                    play_res=None):
    """Текст субтитра с обводкой и тенью — так, как его рисует libass
    (BorderStyle 1): тень — копия текста с обводкой, сдвинутая вниз-вправо,
    затем обводка, затем сам текст. Размеры стиля (кегль, обводка, тень,
    отступы) — в единицах ASS холста play_res, кадр — rect."""
    if not text or rect.width() < 4 or rect.height() < 4:
        return
    play_res = play_res or (_ASS_PLAYRES_X, _ASS_PLAYRES_Y)
    ml, mr, mv = margins or (_ASS_MARGIN_L, _ASS_MARGIN_R, _ASS_MARGIN_V)
    family = style.get('font') or DEFAULT_SUBTITLE_STYLE['font']
    if family == _karaoke_style.FONT_NAME:
        family = _karaoke_font_family()
    outline = _style_num(style, 'outline', 1.0)
    shadow = _style_num(style, 'shadow', 0.0)
    path, body, scale_y = _ass_text_shape(
        text, rect.width(), rect.height(), family,
        float(style.get('size') or DEFAULT_SUBTITLE_STYLE['size']),
        bool(style.get('bold')), bool(style.get('italic')),
        bool(style.get('underline')), float(style.get('spacing') or 0),
        int(style.get('align') or 2), ml, mr, mv, outline, play_res)
    painter.save()
    painter.translate(rect.left(), rect.top())
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    shadow_px = shadow * scale_y
    alpha = 255 - int(_style_num(style, 'shadow_alpha', 0))
    if shadow_px > 0 and alpha > 0:
        painter.fillPath(body.translated(shadow_px, shadow_px), QColor(0, 0, 0, alpha))
    if outline > 0:
        pen = QPen(QColor(style.get('outline_color') or '#000000'),
                   2.0 * outline * scale_y)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.strokePath(path, pen)
    painter.fillPath(path, QColor(style.get('color') or '#FFFFFF'))
    painter.restore()


def _prog_sub_style():
    """Программный стиль субтитров Монтажа (см. PROG_SUB_FONTSIZE): стиль
    «Создать субтитры» по умолчанию — он и есть караоке-стиль."""
    return dict(DEFAULT_SUBTITLE_STYLE)


def prog_sub_force_style(play_res_y=None):
    """force_style ffmpeg-фильтра subtitles для программного стиля.

    play_res_y — высота холста самой дорожки: у SRT/VTT это 288 (холст, на
    котором их рендерит ffmpeg), у ASS — её PlayResY. Без пересчёта кегль 21
    на холсте 1080 вышел бы вчетверо мельче."""
    st = _prog_sub_style()
    k = float(play_res_y or _ASS_PLAYRES_Y) / _ASS_PLAYRES_Y

    def num(v):
        return f"{float(v) * k:.2f}".rstrip("0").rstrip(".")

    return (f"FontName={_karaoke_style.FONT_NAME},Fontsize={num(st['size'])},Bold=1,"
            f"PrimaryColour={_hex_to_ass_color(st['color'])},"
            f"OutlineColour={_hex_to_ass_color(st['outline_color'])},"
            f"BackColour={_hex_to_ass_color('#000000', st['shadow_alpha'])},"
            f"BorderStyle=1,Outline={num(st['outline'])},Shadow={num(st['shadow'])},"
            f"MarginV={num(PROG_SUB_MARGIN_V)},ScaledBorderAndShadow=yes")


def _paint_subtitle(painter, rect, text="", image=None, image_pos=(0, 0)):
    """Рисует субтитры в области кадра rect: либо готовый кадр от libass (image,
    приоритетнее), либо текст программным стилем — как у караоке (см.
    PROG_SUB_FONTSIZE): снизу по центру, обводка и тень. Используется и
    оверлеем-окном, и встроенным рендером в кадр."""
    if image is not None and not image.isNull():
        painter.drawImage(rect.left() + image_pos[0], rect.top() + image_pos[1], image)
        return
    if not text:
        return
    _paint_ass_text(painter, rect, text, _prog_sub_style(),
                    margins=(_ASS_MARGIN_L, _ASS_MARGIN_R, PROG_SUB_MARGIN_V))


def _paint_subtitle_styled(painter, rect, text, style=None):
    """Стилизованный рендер субтитров для превью в SubtitleCreatorDialog: шрифт,
    размер, жирный/курсив/подчёркивание, трекинг, выравнивание (numpad 1-9),
    цвета, обводка и тень — как в стиле реплики (см. DEFAULT_SUBTITLE_STYLE).
    Размеры заданы в единицах ASS PlayResY (288) и переводятся в пиксели по
    правилам libass (_paint_ass_text), поэтому превью совпадает с итоговым
    видео."""
    if not text:
        return
    _paint_ass_text(painter, rect, text, style or DEFAULT_SUBTITLE_STYLE)

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
# переопределения — см. SubtitleCreatorDialog._effective_style). Это же —
# программный стиль Монтажа (_prog_sub_style): караоке-вид из karaoke/style.py
# с кеглем субтитров. Обводка и тень у караоке заданы для кегля BASE_SIZE —
# здесь пропорционально меньше. 'outline'/'shadow' — в единицах ASS; у старых
# сохранённых стилей их нет, и там действуют прежние 1 и 0 (см. _style_line).
DEFAULT_SUBTITLE_STYLE = {
    'font': _karaoke_style.FONT_NAME, 'size': PROG_SUB_FONTSIZE, 'bold': True,
    'italic': False, 'underline': False, 'align': 2, 'spacing': 0,
    'color': '#' + _karaoke_style.TEXT_COLOUR,
    'outline_color': '#' + _karaoke_style.OUTLINE_COLOUR,
    'outline': round(PROG_SUB_FONTSIZE * _karaoke_style.OUTLINE
                     / _karaoke_style.BASE_SIZE, 2),
    'shadow': round(PROG_SUB_FONTSIZE * _karaoke_style.SHADOW
                    / _karaoke_style.BASE_SIZE, 2),
    'shadow_alpha': _karaoke_style.SHADOW_ALPHA,
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
    # Толщина обводки и тень: у стилей, сохранённых до караоке-вида, ключей
    # нет — им остаются прежние Outline 1 и Shadow 0.
    border = f"{_style_num(style, 'outline', 1):g},{_style_num(style, 'shadow', 0):g}"
    back = _hex_to_ass_color('#000000', int(_style_num(style, 'shadow_alpha', 0)))
    return (f"Style: {name},{font},{size},{primary},&H000000FF,{outline},{back},"
            f"{bold},{italic},{underline},0,100,100,{spacing},0,1,{border},{align},"
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


# Пикселизация («проявление из пикселей») живёт в общем модуле pixelize.py:
# тем же эффектом с теми же блоками пользуется генератор аниме-паков (вопрос-
# кадр, который проявляется). Здесь — только привычные имена, чтобы вкладка
# «Монтаж» и её диалоги импортировали их как раньше.
from pixelize import (block_sequence as _pixelize_block_sequence,
                      pixelize_filter as _pixelize_filter)
