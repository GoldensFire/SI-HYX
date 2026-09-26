# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""run_ffprobe. Public namespace: edit_tab_base."""
import edit_tab_base as _api


# ─── Helpers ─────────────────────────────────────────────────────────────────
def run_ffprobe(path):
    cmd = [_api.FFPROBE, "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        p = _api.subprocess.run(cmd, capture_output=True, text=True, check=True,
                           encoding="utf-8", errors="replace",
                           creationflags=_api.CREATE_NO_WINDOW)
        return _api.json.loads(p.stdout)
    except Exception:
        return None

run_ffprobe.__module__ = _api.__name__
_api.run_ffprobe = run_ffprobe

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

time_to_s.__module__ = _api.__name__
_api.time_to_s = time_to_s

def s_to_time(seconds: float) -> str:
    if seconds is None:
        return "00:00:00.000"
    s = float(seconds)
    if not _api.math.isfinite(s) or s < 0:
        return "00:00:00.000"
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"

s_to_time.__module__ = _api.__name__
_api.s_to_time = s_to_time

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

format_fps.__module__ = _api.__name__
_api.format_fps = format_fps

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

_fmt_channels.__module__ = _api.__name__
_api._fmt_channels = _fmt_channels

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
    if _api.QMediaDevices is None or audio_output is None:
        return None
    try:
        watcher = _api.QMediaDevices(owner if owner is not None else audio_output)
    except Exception:
        return None

    def _reattach():
        try:
            dev = _api.QMediaDevices.defaultAudioOutput()
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

install_audio_device_recovery.__module__ = _api.__name__
_api.install_audio_device_recovery = install_audio_device_recovery

def _unique_output(path: str) -> str:
    """Возвращает путь, которого ещё нет на диске: к имени добавляется _1, _2…
    перед расширением (foo_обрез.mp4 → foo_обрез_1.mp4). Используется, когда
    «Перезаписать» выключено, а файл с целевым именем уже существует —
    результат просто сохраняется под новым именем."""
    if not _api.os.path.exists(path):
        return path
    base, ext = _api.os.path.splitext(path)
    i = 1
    while True:
        cand = f"{base}_{i}{ext}"
        if not _api.os.path.exists(cand):
            return cand
        i += 1

_unique_output.__module__ = _api.__name__
_api._unique_output = _unique_output

# ─── Small UI helpers ─────────────────────────────────────────────────────────
def make_divider():
    line = _api.QFrame()
    line.setFrameShape(_api.QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {_api.C['border']}; border: none; border-top: 1px solid {_api.C['border']};")
    line.setFixedHeight(1)
    return line

make_divider.__module__ = _api.__name__
_api.make_divider = make_divider

def make_icon_btn(text, icon_std=None, accent=False, danger=False, w=None, icon=None):
    btn = _api.QPushButton(text)
    # На светлой заливке (accent/danger) — тёмные значок и текст: контраст лучше,
    # чем белый по светло-голубому/розовому (ср. кнопку «НАЧАТЬ» — тёмное по зелёному).
    on_fill = accent or danger
    fg = "#11111b" if on_fill else _api.C["text"]
    if icon:
        # Векторная иконка qtawesome (см. get_icon в config.py).
        btn.setIcon(_api.get_icon(icon, color=fg))
        btn.setIconSize(_api.QSize(20, 20))
    elif icon_std:
        btn.setIcon(_api.QApplication.style().standardIcon(icon_std))
    base_bg = _api.C["accent"] if accent else (_api.C["red"] if danger else _api.C["surface3"])
    hover_bg = _api.C["accent2"] if accent else (_api.C["red2"] if danger else _api.C["border2"])
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {base_bg};
            color: {fg};
            border: 1px solid {_api.C['border2'] if not accent and not danger else 'transparent'};
            border-radius: 6px;
            padding: 7px 14px;
            font-weight: 500;
            font-size: 13px;
        }}
        QPushButton:hover {{ background: {hover_bg}; }}
        QPushButton:pressed {{ background: {_api.C['surface2']}; }}
        QPushButton:disabled {{
            background: {_api.C['surface2']};
            color: {_api.C['text3']};
            border: 1px solid {_api.C['border2']};
        }}
    """)
    if w:
        btn.setFixedWidth(w)
    return btn

make_icon_btn.__module__ = _api.__name__
_api.make_icon_btn = make_icon_btn

def _fullscreen_icon(expand=True, color="#ffffff", size=32):
    """Рисует значок полноэкранного режима «как на YouTube» — четыре уголка.
    expand=True  → уголки в углах рамки (войти в полноэкранный режим);
    expand=False → уголки сдвинуты к центру (выйти из полноэкранного)."""
    pm = _api.QPixmap(size, size)
    pm.fill(_api.Qt.GlobalColor.transparent)
    p = _api.QPainter(pm)
    p.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
    pen = _api.QPen(_api.QColor(color))
    pen.setWidthF(max(2.0, size * 0.085))
    pen.setCapStyle(_api.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(_api.Qt.PenJoinStyle.RoundJoin)
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
    return _api.QIcon(pm)

_fullscreen_icon.__module__ = _api.__name__
_api._fullscreen_icon = _fullscreen_icon

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

_parse_srt.__module__ = _api.__name__
_api._parse_srt = _parse_srt

def _paint_subtitle(painter, rect, text="", px=28, image=None, image_pos=(0, 0)):
    """Рисует субтитры в области rect: либо готовый кадр от libass (image,
    приоритетнее), либо стиль VLC — белый жирный текст с чёрной обводкой снизу
    по центру. Используется и оверлеем-окном, и встроенным рендером в кадр."""
    if image is not None and not image.isNull():
        painter.drawImage(rect.left() + image_pos[0], rect.top() + image_pos[1], image)
        return
    if not text:
        return
    painter.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(_api.QPainter.RenderHint.TextAntialiasing)
    f = _api.QFont("Arial"); f.setBold(True); f.setPixelSize(px)
    painter.setFont(f)
    margin_v = max(10, int(rect.height() * 0.05))
    side = int(rect.width() * 0.05)
    area = _api.QRect(rect.left() + side, rect.top(),
                 max(10, rect.width() - 2 * side),
                 max(10, rect.height() - margin_v))
    flags = (_api.Qt.AlignmentFlag.AlignHCenter | _api.Qt.AlignmentFlag.AlignBottom
             | _api.Qt.TextFlag.TextWordWrap)
    o = max(2, px // 11)   # толщина обводки
    painter.setPen(_api.QPen(_api.QColor(0, 0, 0)))
    for dx in (-o, 0, o):
        for dy in (-o, 0, o):
            if dx == 0 and dy == 0:
                continue
            painter.drawText(area.translated(dx, dy), flags, text)
    painter.setPen(_api.QPen(_api.QColor(255, 255, 255)))
    painter.drawText(area, flags, text)

_paint_subtitle.__module__ = _api.__name__
_api._paint_subtitle = _paint_subtitle
