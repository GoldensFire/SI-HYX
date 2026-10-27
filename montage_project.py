# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# montage_project.py — проект «Монтажа» из кусков, как в Filmora: несколько
# дорожек видео и звука, куски из одного или разных файлов, разрезание,
# перестановка, подрезка и сборка итогового видео одной командой ffmpeg.
"""Проект «Монтажа»: дорожки, клипы и сборка ffmpeg.

Модель без Qt — её используют вкладка (si_hyx_parts/edit_tab/project.py) и
виджет таймлайна (si_hyx_parts/edit_tab_widgets/project_timeline.py).

Дорожки: «Видео 1» — основная и «магнитная», как в Filmora: клипы на ней
стоят вплотную друг за другом, удалённый кусок не оставляет дыры, а
перетаскивание меняет порядок. Остальные дорожки свободные: клип стоит там,
куда его поставили. Верхняя видеодорожка перекрывает нижние (кадр целиком),
звук всех клипов смешивается.

Время везде в секундах: start — место клипа на шкале проекта, in_s/out_s —
кусок исходника. Скорость клипа (speed) меняет только длину на шкале: кусок
исходника тот же, а на проект он идёт быстрее или медленнее.

Файл проекта — JSON схемы PROJECT_VERSION: v1 (без настроек формата)
читается как v2, v2 — как v3 (v3 — ключевые кадры, эффекты и кривая
скорости клипа; проект без них пишется как v2), файл новее программы —
ProjectError. Строгая проверка для
внешних агентов — validate (si_hyx_parts/montage_project/schema.py)."""
import json
import math
import os
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from fractions import Fraction

PROJECT_VERSION = 3
# Поля v3 у клипа: пустые в файл не пишутся, и проект без них остаётся v2 —
# его читают и прежние версии программы.
_V3_CLIP_FIELDS = ('keyframes', 'effects', 'speed_curve', 'curve_audio', 'interpolate',
                   'upscale', 'crop', 'box', 'mask', 'stroke', 'blend', 'matte')
_V3_SETTINGS = {'upscale': '', 'deband': False, 'finish': []}
MIN_CLIP_S = 0.04          # короче клип не бывает (подрезка, разрезание)
MIN_SPEED = 0.1            # пределы скорости клипа (доли и разы)
MAX_SPEED = 8.0
_EPS = 1e-6
_AUDIO_RATE = 48000          # частота звука сборки (и просмотра проекта)
# Вписывание кадра клипа в кадр проекта: fit — целиком, с полями цвета фона;
# fill — растянуть на весь кадр (пропорции не держатся); crop — заполнить
# кадр, срезав лишнее по краям (рефрейм 16:9 ↔ 9:16 ↔ 1:1).
FIT_MODES = ('fit', 'fill', 'crop')
# Виды маркеров шкалы: сцена (смена плана), бит и начало звука музыки,
# тишина и речь (отрезки), слово (отрезок с текстом), свой маркер; карта
# песни (montage_tool music): сильная доля (label — номер такта), фраза и
# часть песни (отрезки; label — 4/8 тактов, «chorus A»), удары бочки,
# малого барабана и тарелок, место для реза (label — уровень доли).
MARKER_KINDS = ('scene', 'beat', 'onset', 'silence', 'speech', 'word', 'custom',
                'downbeat', 'phrase', 'section', 'kick', 'snare', 'hat', 'slot')
# Переходы между клипами основной дорожки — виды ffmpeg xfade (без custom и
# новых, которых нет в сборках ffmpeg 6).
TRANSITIONS = (
    'fade', 'fadeblack', 'fadewhite', 'fadegrays', 'fadefast', 'fadeslow', 'dissolve',
    'pixelize', 'radial', 'distance', 'hblur', 'wipeleft', 'wiperight', 'wipeup',
    'wipedown', 'wipetl', 'wipetr', 'wipebl', 'wipebr', 'slideleft', 'slideright',
    'slideup', 'slidedown', 'smoothleft', 'smoothright', 'smoothup', 'smoothdown',
    'circlecrop', 'rectcrop', 'circleopen', 'circleclose', 'vertopen', 'vertclose',
    'horzopen', 'horzclose', 'diagtl', 'diagtr', 'diagbl', 'diagbr', 'hlslice',
    'hrslice', 'vuslice', 'vdslice', 'squeezeh', 'squeezev', 'zoomin')
# Роль дорожки: голос приглушает музыку (ProjectSettings.duck).
TRACK_ROLES = ('', 'voice', 'music')
MIN_SCALE, MAX_SCALE = 0.02, 4.0
# Реверс держит все кадры куска в памяти (фильтр reverse) — длиннее не берём.
MAX_REVERSE_S = 10.0


class ProjectError(ValueError):
    """Проект не загружается: файл не читается, версия новее программы или
    (строгая загрузка) проверка нашла проблемы. problems — как у validate,
    path — файл, который не загрузился."""

    def __init__(self, message, problems=None, path=""):
        super().__init__(message)
        self.problems = list(problems or [])
        self.path = path


def _finite(v, default, low=None):
    """Число v или default, если v не число (строка, None, NaN, бесконечность)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v if low is None else max(low, v)


def stream_display_size(stream):
    """(ширина, высота) кадра видеопотока так, как его показывают плееры и
    отдаёт ffmpeg после -i: неквадратный пиксель (sample_aspect_ratio)
    растягивает ширину, поворот на 90/270° (матрица отображения или старый
    тег rotate) меняет стороны местами. Размер потока (width/height) этого
    не учитывает: видео с телефона (поток 1920x1080, поворот 90°) давало
    проекту альбомный формат с полями. stream — поток из ffprobe
    -show_streams. (0, 0) — размер неизвестен."""
    if not isinstance(stream, dict):
        return 0, 0
    try:
        w, h = int(stream.get('width') or 0), int(stream.get('height') or 0)
    except (TypeError, ValueError):
        return 0, 0
    if w <= 0 or h <= 0:
        return 0, 0
    num, _, den = str(stream.get('sample_aspect_ratio') or "").partition(":")
    try:
        num, den = int(num), int(den)
        if num > 0 and den > 0 and num != den:
            w = max(1, int(w * num / den))   # как iw*sar у ffmpeg
    except ValueError:
        pass
    rot = 0
    for sd in stream.get('side_data_list') or []:
        if isinstance(sd, dict) and 'rotation' in sd:
            try:
                rot = int(round(float(sd['rotation'])))
            except (TypeError, ValueError):
                pass
    if not rot:
        tags = stream.get('tags') if isinstance(stream.get('tags'), dict) else {}
        try:
            rot = int(float(tags.get('rotate') or 0))
        except (TypeError, ValueError):
            rot = 0
    if rot % 180 == 90:
        w, h = h, w
    return w, h


@dataclass
class Clip:
    """Кусок исходника на дорожке проекта."""
    src: str                      # файл с картинкой (у звукового клипа — сам звук)
    in_s: float
    out_s: float
    track: int                    # индекс дорожки в Project.tracks
    start: float = 0.0            # место на шкале проекта
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    has_video: bool = True
    is_image: bool = False        # картинка: держится in..out секунд
    audio_path: str = ""          # откуда звук (исходник или внешняя озвучка); "" — без звука
    audio_stream: int = -1        # абсолютный индекс потока в audio_path; -1 — первый звуковой
    volume: float = 1.0
    muted: bool = False
    speed: float = 1.0            # 1.0 — как в исходнике, 2.0 — вдвое быстрее
    audio_detached: bool = False  # звук отделён в свой клип — не возвращать при смене дорожки
    width: int = 0                # размер кадра как на экране (stream_display_size)
    height: int = 0
    fps: float = 0.0
    src_duration: float = 0.0     # длина исходника — предел подрезки
    # v2 — вид и звук клипа; по умолчанию всё как в v1.
    fit: str = ''                 # вписывание (FIT_MODES); '' — как у проекта
    pos_x: float = 0.5            # клип верхней дорожки: центр, доли кадра
    pos_y: float = 0.5
    scale: float = 1.0            # клип верхней дорожки: размер, доля кадра
    opacity: float = 1.0          # клип верхней дорожки: непрозрачность 0…1
    transition: str = ''          # переход В этот клип основной дорожки (TRANSITIONS)
    transition_s: float = 0.0     # его длина: клип встаёт внахлёст на предыдущий
    fade_in: float = 0.0          # нарастание и затухание звука клипа, с
    fade_out: float = 0.0
    reverse: bool = False         # кусок исходника идёт задом наперёд (до MAX_REVERSE_S)
    freeze_at: float = -1.0       # стоп-кадр: кадр исходника на этом времени всю длину
                                  # клипа (in_s/out_s задают только длину, как у картинки)
    # v3 — эффекты (si_hyx_parts/montage_project/effects.py); пустые — как v2.
    keyframes: dict = field(default_factory=dict)   # {свойство: [{t, v, ease}]}
    effects: list = field(default_factory=list)     # [{type, on, section, amount, …}]
    speed_curve: list = field(default_factory=list)  # [{at: доля куска, speed}]
    curve_audio: bool = False     # звук клипа с кривой скорости (rubberband); иначе тишина
    interpolate: str = ''         # RIFE для замедления (vulkan_fx.RIFE_MODELS); '' — нет
    upscale: str = ''             # Anime4K (vulkan_fx.UPSCALE_PRESETS); '' — как проект, none — нет
    # v3 — слои (si_hyx_parts/montage_project/layers.py); пустые — как раньше.
    crop: list = field(default_factory=list)        # [x0, y0, x1, y1] кусок кадра исходника
    box: list = field(default_factory=list)         # [ширина, высота] наложения, доли кадра
    mask: dict = field(default_factory=dict)        # форма видимой части наложения
    stroke: dict = field(default_factory=dict)      # обводка по альфе наложения
    blend: str = ''               # режим наложения (layers.BLEND_MODES); '' — обычный
    matte: str = ''               # вырезать персонажа (layers.MATTE_MODELS); '' — нет

    def __post_init__(self):
        """Типы и пределы полей — при любом создании клипа: из файла проекта,
        копией или вручную. Строка вместо числа в файле роняла загрузку
        проекта TypeError, а скорость мимо set_speed (Clip(speed=20)) шла в
        картинку ×20, а в звук — ×8 (предел atempo_chain). Время клипа и
        дорожка обязаны быть числами — иначе TypeError/ValueError; громкость,
        fps и длина исходника, если не числа, берутся по умолчанию."""
        self.src = str(self.src)
        self.audio_path = str(self.audio_path or "")
        self.id = str(self.id) if self.id else uuid.uuid4().hex[:12]
        for name in ('has_video', 'is_image', 'muted', 'audio_detached'):
            setattr(self, name, bool(getattr(self, name)))
        for name in ('track', 'audio_stream', 'width', 'height'):
            setattr(self, name, int(getattr(self, name)))
        self.width, self.height = max(0, self.width), max(0, self.height)
        for name in ('in_s', 'out_s', 'start'):
            v = float(getattr(self, name))
            if not math.isfinite(v):
                raise ValueError(f"{name} клипа — не число")
            setattr(self, name, v)
        self.volume = _finite(self.volume, 1.0, low=0.0)
        self.fps = _finite(self.fps, 0.0, low=0.0)
        self.src_duration = _finite(self.src_duration, 0.0, low=0.0)
        speed = _finite(self.speed, 1.0)
        self.speed = 1.0 if self.is_image else max(MIN_SPEED, min(MAX_SPEED, speed))
        self.fit = self.fit if self.fit in FIT_MODES else ''
        self.pos_x = _finite(self.pos_x, 0.5)
        self.pos_y = _finite(self.pos_y, 0.5)
        self.scale = max(MIN_SCALE, min(MAX_SCALE, _finite(self.scale, 1.0)))
        self.opacity = max(0.0, min(1.0, _finite(self.opacity, 1.0)))
        self.transition = self.transition if self.transition in TRANSITIONS else ''
        self.transition_s = _finite(self.transition_s, 0.0, low=0.0)
        self.fade_in = _finite(self.fade_in, 0.0, low=0.0)
        self.fade_out = _finite(self.fade_out, 0.0, low=0.0)
        self.reverse = bool(self.reverse) and not self.is_image
        freeze = _finite(self.freeze_at, -1.0)
        self.freeze_at = freeze if freeze >= 0 and not self.is_image and self.has_video else -1.0
        if self.frozen:
            self.reverse, self.speed = False, 1.0
        # v3: мягкая чистка (негодное выбрасывается, как у полей v2).
        self.keyframes = sanitize_keyframes(self.keyframes)
        self.effects = sanitize_effects(self.effects)
        self.speed_curve = sanitize_curve(self.speed_curve)
        self.curve_audio = bool(self.curve_audio)
        self.interpolate = self.interpolate if self.interpolate in RIFE_MODELS else ''
        self.upscale = (self.upscale if self.upscale in UPSCALE_PRESETS or self.upscale == 'none'
                        else '')
        if self.speed_curve and (self.is_image or self.frozen or self.reverse):
            self.speed_curve = []        # кривая — только у обычного видео/звука
        self.crop = sanitize_crop(self.crop)
        self.box = sanitize_box(self.box)
        self.mask = sanitize_mask(self.mask)
        self.stroke = sanitize_stroke(self.stroke)
        self.blend = sanitize_blend(self.blend)
        self.matte = sanitize_matte(self.matte) if not self.is_image else ''

    @property
    def frozen(self):
        """Стоп-кадр (freeze_at): длина — out_s − in_s, звука нет."""
        return self.freeze_at >= 0

    @property
    def play_speed(self):
        """Скорость на шкале в пределах MIN_SPEED…MAX_SPEED, у картинки и
        стоп-кадра — 1. Ею считают и длину клипа, и сборку картинки и звука:
        speed, присвоенный в обход set_speed, не разводит их."""
        if self.is_image or self.frozen:
            return 1.0
        if self.speed_curve:
            # Средняя скорость кривой: длина клипа — время τ всего куска.
            tau = curve_length(self)
            return (self.out_s - self.in_s) / tau if tau > 0 else 1.0
        return max(MIN_SPEED, min(MAX_SPEED, self.speed))

    @property
    def length(self):
        return max(0.0, (self.out_s - self.in_s) / self.play_speed)

    @property
    def end(self):
        return self.start + self.length

    @property
    def name(self):
        return os.path.basename(self.src)

    def source_time(self, t):
        """Время исходника для времени проекта t (внутри клипа); у реверса —
        от конца куска к началу."""
        if self.reverse:
            return self.out_s - max(0.0, t - self.start) * self.play_speed
        if self.speed_curve:
            return self.in_s + curve_source_offset(self, max(0.0, t - self.start))
        return self.in_s + max(0.0, t - self.start) * self.play_speed


@dataclass
class TextItem:
    """Текст проекта во времени проекта (титр, подпись): вшивается ASS-ом
    после склейки и наложений. style — поверх стиля программы
    (subtitle_ass.DEFAULT_SUBTITLE_STYLE: font, size, bold, italic,
    underline, align 1…9, spacing, color, outline_color, outline, shadow,
    shadow_alpha, animation none/fade/slide/pop); pos_x/pos_y — точка
    привязки, доли кадра (None — по выравниванию align)."""
    start: float
    end: float
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    style: dict = field(default_factory=dict)
    pos_x: float = None
    pos_y: float = None
    layer: int = None             # v3: над какой видеодорожкой (индекс); None — поверх всего


@dataclass
class ProjectSettings:
    """Формат итога. Нули — «по первому клипу», как у Filmora: размер и fps
    берутся у первого видеоклипа основной дорожки."""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    fit: str = 'fit'              # FIT_MODES
    background: str = '#000000'   # поля и пустые места кадра, #RRGGBB
    loudness: float = None        # целевая громкость итога, LUFS; None — как есть
    duck: float = 0.0             # 0…1: насколько голос (Track.role) приглушает музыку
    upscale: str = ''             # v3: Anime4K для кадров меньше кадра проекта; '' — нет
    deband: bool = False          # v3: deband libplacebo вместе с апскейлом
    finish: list = field(default_factory=list)  # v3: эффекты всего кадра (effects.FINISH_TYPES)


@dataclass
class Marker:
    """Метка на шкале проекта (время проекта, секунды): итог анализа
    (montage_tool analyze) или своя. Таймлайн её показывает и прилипает к ней."""
    t: float
    kind: str = 'custom'          # MARKER_KINDS
    label: str = ''
    strength: float = 1.0         # 0…1: сила бита, уверенность сцены
    end: float = None             # конец отрезка (тишина, речь, слово); None — точка


@dataclass
class Track:
    kind: str                     # 'video' | 'audio'
    enabled: bool = True
    muted: bool = False           # звук клипов дорожки выключен (картинка остаётся)
    role: str = ''                # TRACK_ROLES: голос приглушает музыку


def snap_to_frame(t, fps):
    """Начало кадра, на котором стоит t (как показывает плеер — кадр с pts ≤ t)."""
    if not fps or fps <= 0:
        return max(0.0, float(t))
    return max(0.0, math.floor(float(t) * fps + 1e-3) / fps)


class Project:
    """Дорожки и клипы. Все правки идут через методы — они же держат основную
    дорожку плотной (pack) и не дают клипам свободных дорожек налезать друг
    на друга."""

    def __init__(self):
        self.tracks = [Track('video'), Track('video'), Track('audio'), Track('audio')]
        self.clips = []
        self.settings = ProjectSettings()
        self.markers = []             # Marker по времени
        self.texts = []               # TextItem по времени

    # ── Дорожки ──────────────────────────────────────────────────────────────
    @property
    def main_track(self):
        """Индекс основной («магнитной») видеодорожки — первой видеодорожки."""
        return next(i for i, t in enumerate(self.tracks) if t.kind == 'video')

    def track_name(self, ti):
        kind = self.tracks[ti].kind
        num = sum(1 for t in self.tracks[:ti + 1] if t.kind == kind)
        return f"{'Видео' if kind == 'video' else 'Аудио'} {num}"

    def track_short(self, ti):
        kind = self.tracks[ti].kind
        num = sum(1 for t in self.tracks[:ti + 1] if t.kind == kind)
        return f"{'В' if kind == 'video' else 'А'}{num}"

    def display_order(self):
        """Дорожки сверху вниз, как в Filmora: видео от верхней к основной,
        затем звук."""
        video = [i for i, t in enumerate(self.tracks) if t.kind == 'video']
        audio = [i for i, t in enumerate(self.tracks) if t.kind == 'audio']
        return list(reversed(video)) + audio

    def add_track(self, kind):
        self.tracks.append(Track(kind))
        return len(self.tracks) - 1

    def tracks_of(self, kind):
        return [i for i, t in enumerate(self.tracks) if t.kind == kind]

    def track_has_audio(self, ti):
        """На дорожке есть клип со звуком (видео со своим звуком, озвучка)."""
        return any(c.track == ti and c.audio_path for c in self.clips)

    # ── Клипы ────────────────────────────────────────────────────────────────
    def clip(self, cid):
        return next((c for c in self.clips if c.id == cid), None)

    def clips_on(self, ti):
        return sorted((c for c in self.clips if c.track == ti), key=lambda c: c.start)

    def is_empty(self):
        return not self.clips

    def duration(self):
        return max((c.end for c in self.clips
                    if self.tracks[c.track].enabled), default=0.0)

    def clip_at(self, ti, t):
        return next((c for c in self.clips_on(ti) if c.start <= t < c.end), None)

    @staticmethod
    def transition_overlap(prev, c):
        """Нахлёст клипа c на предыдущий prev основной дорожки — длина
        перехода, не больше половины каждого из двух клипов (иначе два
        перехода одного клипа налезли бы друг на друга)."""
        if prev is None or not c.transition or c.transition_s <= 0:
            return 0.0
        return max(0.0, min(c.transition_s, prev.length / 2.0, c.length / 2.0))

    def pack(self):
        """Основная дорожка — вплотную, в порядке start (магнитная); клип с
        переходом встаёт внахлёст на предыдущий (transition_overlap)."""
        t, prev = 0.0, None
        for c in self.clips_on(self.main_track):
            c.start = max(0.0, t - self.transition_overlap(prev, c))
            t, prev = c.end, c

    def _free_spot(self, clip):
        """Ставит клип свободной дорожки туда, где он ни на кого не налезает:
        при наложении — сразу за мешающим клипом."""
        clip.start = max(0.0, clip.start)
        others = [c for c in self.clips_on(clip.track) if c is not clip]
        moved = True
        while moved:
            moved = False
            for c in others:
                if clip.start < c.end - _EPS and c.start < clip.end - _EPS:
                    clip.start = c.end
                    moved = True

    def _settle(self, clip):
        if clip.track == self.main_track:
            self.pack()
        else:
            self._free_spot(clip)
            self.pack()

    def append(self, clip):
        """Добавляет клип: на основной дорожке — в конец, на свободной — на
        clip.start (или ближайшее свободное место после него)."""
        if clip.track == self.main_track:
            clip.start = self.duration_of(self.main_track) + 1.0
        self.clips.append(clip)
        self._settle(clip)
        return clip

    def duration_of(self, ti):
        return max((c.end for c in self.clips if c.track == ti), default=0.0)

    def remove(self, cid):
        c = self.clip(cid)
        if c is None:
            return False
        self.clips.remove(c)
        self.pack()
        return True

    def split(self, cid, t):
        """Режет клип в точке проекта t. Возвращает (левый, правый) или None."""
        c = self.clip(cid)
        if c is None:
            return None
        # У стоп-кадра in/out — только длина: режем её, а не исходник.
        cut = c.in_s + (t - c.start) if c.frozen else c.source_time(t)
        if c.fps and not c.is_image and not c.frozen:
            cut = snap_to_frame(cut, c.fps)
        speed = c.play_speed
        if ((cut - c.in_s) / speed < MIN_CLIP_S - _EPS
                or (c.out_s - cut) / speed < MIN_CLIP_S - _EPS):
            return None
        right = Clip(**{f.name: getattr(c, f.name) for f in fields(Clip)})
        right.id = uuid.uuid4().hex[:12]
        # Переход и нарастание звука — у начала клипа, затухание — у конца.
        right.transition, right.transition_s, right.fade_in = '', 0.0, 0.0
        c.fade_out = 0.0
        t_local = t - c.start
        if c.reverse:
            # Реверс: слева на шкале — конец куска исходника [cut, out_s).
            right.out_s = cut
            right.start = c.start + (c.out_s - cut) / speed
            c.in_s = cut
        else:
            right.in_s = cut
            right.start = c.start + (cut - c.in_s) / speed
            if c.speed_curve:
                split_fx(c, right, t_local, cut)    # своя кривая у каждой половины
            elif c.keyframes:
                split_fx(c, right, t_local, cut)
            c.out_s = cut
        self.clips.insert(self.clips.index(c) + 1, right)
        self.pack()
        return c, right

    def paste(self, clips, t):
        """Вставляет копии clips у времени проекта t, сохраняя их взаимное
        расположение. Возвращает вставленные клипы (у копий новые id).

        Клипы основной дорожки встают подряд с t, а всё правее сдвигается —
        дорожка магнитная; клип под t разрезается (у самого его края вставка
        идёт к ближнему краю). Клипы свободных дорожек держатся за первый
        клип основной (без него — за t) и встают на свою дорожку, а если там
        на этом месте занято — на другую того же рода (нигде — на новую)."""
        clips = sorted(clips, key=lambda c: (c.start, c.track))
        if not clips:
            return []
        main = self.main_track
        base = clips[0].start
        on_main = [c for c in clips if c.track == main and c.has_video]
        free = [c for c in clips if not (c.track == main and c.has_video)]
        dst = max(0.0, float(t))
        new = []
        if on_main:
            at = self._main_insert_point(dst)
            shift = sum(c.length for c in on_main)
            for o in self.clips_on(main):
                if o.start >= at - _EPS:
                    o.start += shift
            pos = at
            for c in on_main:
                nc = replace(c, id=uuid.uuid4().hex[:12], track=main, start=pos)
                pos += nc.length
                self.clips.append(nc)
                new.append(nc)
            dst = at - (on_main[0].start - base)
        for c in free:
            kind = 'video' if c.has_video else 'audio'
            nc = replace(c, id=uuid.uuid4().hex[:12],
                         start=max(0.0, dst + (c.start - base)))
            own = (0 <= c.track < len(self.tracks) and c.track != main
                   and self.tracks[c.track].kind == kind)
            cands = ([c.track] if own else []) + [
                ti for ti in self.tracks_of(kind) if ti != main and ti != c.track]
            track = next((ti for ti in cands if all(
                o.end <= nc.start + _EPS or o.start >= nc.end - _EPS
                for o in self.clips_on(ti))), None)
            nc.track = self.add_track(kind) if track is None else track
            self.clips.append(nc)
            new.append(nc)
        self.pack()
        return new

    def _main_insert_point(self, t):
        """Стык основной дорожки, куда встаёт вставка у времени t: клип под t
        разрезается, а у самого его края (кусок вышел бы короче MIN_CLIP_S) —
        ближний край. За концом дорожки — её конец."""
        main = self.main_track
        c = self.clip_at(main, t)
        if c is None:
            return min(t, self.duration_of(main))
        parts = self.split(c.id, t)
        if parts is not None:
            return parts[0].end
        return c.start if t - c.start <= c.end - t else c.end

    def set_speed(self, cid, speed):
        """Скорость клипа: та же вырезка исходника идёт по шкале быстрее или
        медленнее. Длина клипа меняется — соседи на дорожке сдвигаются."""
        c = self.clip(cid)
        if c is None or c.is_image:
            return False
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(speed):
            return False
        c.speed = max(MIN_SPEED, min(MAX_SPEED, speed))
        self._settle(c)
        return True

    def move(self, cid, track, start):
        """Переносит клип на дорожку track. На основной дорожке start задаёт
        место вставки (клип встаёт перед тем, чья середина правее), на
        свободной — само место."""
        c = self.clip(cid)
        if c is None or not (0 <= track < len(self.tracks)):
            return False
        kind = 'video' if c.has_video else 'audio'
        if self.tracks[track].kind != kind:
            return False
        c.track = track
        if track == self.main_track:
            others = [o for o in self.clips_on(track) if o is not c]
            pos = len(others)
            for i, o in enumerate(others):
                if start < o.start + o.length / 2.0:
                    pos = i
                    break
            # Порядок задаём через start: pack раскладывает по нему.
            for i, o in enumerate(others):
                o.start = float(i if i < pos else i + 1)
            c.start = float(pos)
            self.pack()
        else:
            c.start = max(0.0, start)
            self._free_spot(c)
            self.pack()
        return True

    def move_group(self, ids, lead_id, track, start):
        """Переносит выделенные клипы вместе. Ведущий lead_id (его тянут мышью)
        встаёт как в move(): на дорожку track, на место start; остальные
        сдвигаются на ту же разницу по времени, оставаясь на своих дорожках.
        Клипы основной дорожки едут одним блоком в прежнем порядке (дорожка
        магнитная), клипы свободных — каждый на свой новый start."""
        lead = self.clip(lead_id)
        if lead is None or not (0 <= track < len(self.tracks)):
            return False
        ids = set(ids) | {lead_id}
        group = [c for c in self.clips if c.id in ids]
        if len(group) < 2:
            return self.move(lead_id, track, start)
        if self.tracks[track].kind != ('video' if lead.has_video else 'audio'):
            return False
        main = self.main_track
        dst = {c.id: (track if c is lead else c.track) for c in group}
        delta = start - lead.start
        # Свободные клипы не уходят левее начала шкалы — тогда и вся группа.
        free = [c for c in group if dst[c.id] != main]
        if free:
            delta = max(delta, -min(c.start for c in free))
        new_start = {c.id: max(0.0, c.start + delta) for c in group}
        block = sorted((c for c in group if dst[c.id] == main),
                       key=lambda c: (new_start[c.id], c.start))
        for c in group:
            c.track = dst[c.id]
        if block:
            # Блок встаёт перед клипом, чья середина правее начала блока (как move).
            at = new_start[block[0].id]
            others = [o for o in self.clips_on(main) if o.id not in ids]
            pos = next((i for i, o in enumerate(others) if at < o.start + o.length / 2.0),
                       len(others))
            order = others[:pos] + block + others[pos:]
            for i, o in enumerate(order):
                o.start = float(i)
        rest = sorted((c for c in group if dst[c.id] != main), key=lambda c: new_start[c.id])
        for c in rest:
            c.start = new_start[c.id]
        for c in rest:
            self._free_spot(c)
        self.pack()
        return True

    def trim(self, cid, edge, t):
        """Подрезка за край: edge 'left' или 'right', t — время проекта, куда
        тянут край. Пределы — начало и конец исходника (у картинки только
        начало: её можно растянуть сколько угодно)."""
        c = self.clip(cid)
        if c is None:
            return False
        still = c.is_image or c.frozen
        limit = c.src_duration if (c.src_duration > 0 and not still) else float("inf")
        speed = c.play_speed
        min_src = MIN_CLIP_S * speed
        free = c.track != self.main_track
        # На свободной дорожке край упирается в соседа (и в начало шкалы).
        others = [o for o in self.clips_on(c.track) if o is not c] if free else []
        if c.reverse:
            self._trim_reversed(c, edge, t, limit, others, free)
        elif edge == 'left':
            new_in = c.in_s + (t - c.start) * speed
            if c.fps and not c.is_image:
                new_in = snap_to_frame(new_in, c.fps)
            low = 0.0
            if free:
                prev_end = max((o.end for o in others if o.end <= c.start + _EPS), default=0.0)
                low = max(low, c.in_s - (c.start - prev_end) * speed)
            new_in = min(max(low, new_in), c.out_s - min_src)
            shift = (new_in - c.in_s) / speed
            c.in_s = new_in
            if free:
                c.start = max(0.0, c.start + shift)
        else:
            new_out = c.in_s + (t - c.start) * speed
            if c.fps and not c.is_image:
                new_out = snap_to_frame(new_out, c.fps)
            high = limit
            if free:
                next_start = min((o.start for o in others if o.start >= c.end - _EPS),
                                 default=float("inf"))
                high = min(high, c.in_s + (next_start - c.start) * speed)
            c.out_s = max(c.in_s + min_src, min(high, new_out))
        self.pack()
        return True

    @staticmethod
    def _trim_reversed(c, edge, t, limit, others, free):
        """Подрезка клипа-реверса: левый край на шкале — конец куска
        исходника (out_s), правый — начало (in_s)."""
        speed = c.play_speed
        min_src = MIN_CLIP_S * speed
        if edge == 'left':
            new_out = c.out_s - (t - c.start) * speed
            if c.fps:
                new_out = snap_to_frame(new_out, c.fps)
            high = limit
            if free:
                prev_end = max((o.end for o in others if o.end <= c.start + _EPS), default=0.0)
                high = min(high, c.out_s + (c.start - prev_end) * speed)
            new_out = max(c.in_s + min_src, min(high, new_out))
            shift = (c.out_s - new_out) / speed
            c.out_s = new_out
            if free:
                c.start = max(0.0, c.start + shift)
        else:
            new_in = c.out_s - (t - c.start) * speed
            if c.fps:
                new_in = snap_to_frame(new_in, c.fps)
            low = 0.0
            if free:
                next_start = min((o.start for o in others if o.start >= c.end - _EPS),
                                 default=float("inf"))
                low = max(low, c.out_s - (next_start - c.start) * speed)
            c.in_s = min(c.out_s - min_src, max(low, new_in))

    # ── Что видно и что слышно ───────────────────────────────────────────────
    def _flatten(self, track_ids, keep):
        """[(t0, t1, clip|None)] по дорожкам track_ids: в каждый момент берётся
        клип самой верхней дорожки (позже в списке — выше)."""
        rank = {ti: r for r, ti in enumerate(track_ids)}
        clips = [c for c in self.clips
                 if c.track in rank and keep(c) and c.length > _EPS]
        if not clips:
            return []
        pts = sorted({0.0} | {c.start for c in clips} | {c.end for c in clips})
        out = []
        for a, b in zip(pts, pts[1:]):
            if b - a < _EPS:
                continue
            mid = (a + b) / 2.0
            top = max((c for c in clips if c.start <= mid < c.end),
                      key=lambda c: rank[c.track], default=None)
            if out and out[-1][2] is top and abs(out[-1][1] - a) < _EPS:
                out[-1] = (out[-1][0], b, top)
            else:
                out.append((a, b, top))
        return out

    def video_segments(self):
        """Что в кадре проекта: [(t0, t1, clip|None)], None — чёрный кадр."""
        vts = [ti for ti in self.tracks_of('video') if self.tracks[ti].enabled]
        return self._flatten(vts, lambda c: c.has_video)

    def has_video(self):
        return any(c.has_video and self.tracks[c.track].enabled for c in self.clips)

    def preview_segments(self):
        """Цепочка для просмотра проекта в плеере: картинка, а если видео в
        проекте нет вовсе — звуковые клипы."""
        if self.has_video():
            return self.video_segments()
        ats = [ti for ti in self.tracks_of('audio') if self.tracks[ti].enabled]
        return self._flatten(list(reversed(ats)), lambda c: bool(c.audio_path))

    def audio_parts(self):
        """Клипы, чей звук попадает в итог (смешиваются все разом)."""
        return [c for c in self.clips
                if self.tracks[c.track].enabled and not self.tracks[c.track].muted
                and c.audio_path and not c.muted and c.volume > 0 and c.length > _EPS
                and not c.frozen and (not c.speed_curve or c.curve_audio)]

    def live_preview_gaps(self):
        """Что из проекта живой плеер вкладки не покажет (он играет один
        клип за раз и без эффектов) — видно только в превью montage_tool и
        в собранном файле. Пустой список — просмотр совпадает с итогом."""
        gaps = []
        main = self.main_track
        upper = [c for c in self.clips if c.track != main and c.has_video
                 and self.tracks[c.track].enabled]
        if any(abs(c.scale - 1.0) > _EPS or abs(c.pos_x - 0.5) > _EPS
               or abs(c.pos_y - 0.5) > _EPS or c.opacity < 1.0 for c in upper):
            gaps.append("наложения (размер, место, прозрачность)")
        if any(c.transition and c.transition_s > 0 for c in self.clips_on(main)):
            gaps.append("переходы")
        if self.texts:
            gaps.append("текст")
        if any(c.fit for c in self.clips) or self.settings.fit != 'fit':
            gaps.append("вписывание кадра")
        if any(c.fade_in > 0 or c.fade_out > 0 for c in self.clips):
            gaps.append("нарастание и затухание звука")
        if self.settings.duck > 0 and any(t.role for t in self.tracks):
            gaps.append("приглушение музыки под голос")
        if self.settings.loudness is not None:
            gaps.append("выравнивание громкости")
        if any(c.reverse or c.frozen for c in self.clips):
            gaps.append("реверс и стоп-кадр")
        if any(c.keyframes for c in self.clips):
            gaps.append("ключевые кадры (зум, панорама, поворот, прозрачность)")
        if any(c.effects for c in self.clips):
            gaps.append("эффекты: " + ", ".join(sorted({e["type"] for c in self.clips
                                                        for e in c.effects})))
        if any(c.speed_curve for c in self.clips):
            gaps.append("плавная смена скорости")
        if any(c.interpolate for c in self.clips):
            gaps.append("интерполяция RIFE")
        if self.settings.upscale or any(c.upscale not in ('', 'none') for c in self.clips):
            gaps.append("апскейл Anime4K")
        if any(c.crop or c.box or c.mask or c.stroke or c.blend for c in self.clips):
            gaps.append("обрезка, маски, обводка и режимы наложения")
        if any(c.matte for c in self.clips):
            gaps.append("вырезанный персонаж")
        if self.settings.finish:
            gaps.append("эффекты всего кадра")
        return gaps

    def output_format(self):
        """(ширина, высота, fps) итогового видео: из настроек проекта, а что
        там не задано — по первому видеоклипу основной дорожки, как «по
        первому клипу» у Filmora."""
        first = next((c for c in self.clips_on(self.main_track)
                      if c.has_video and c.width > 0), None)
        if first is None:
            first = next((c for c in sorted(self.clips, key=lambda c: c.start)
                          if c.has_video and c.width > 0), None)
        st = self.settings
        if st.width > 0 and st.height > 0:
            w, h = int(st.width) // 2 * 2, int(st.height) // 2 * 2
        elif first is not None:
            w, h = int(first.width) // 2 * 2, int(first.height) // 2 * 2
        else:
            w, h = 1280, 720
        if st.fps and st.fps > 0:
            fps = st.fps
        elif first is not None and first.fps and first.fps > 0 and not first.is_image:
            fps = first.fps
        else:
            fps = 30.0
        return max(2, w), max(2, h), float(fps)

    # ── Сохранение ───────────────────────────────────────────────────────────
    def to_dict(self):
        clips, v3 = [], False
        for c in self.clips:
            d = asdict(c)
            for k in _V3_CLIP_FIELDS:
                if d.get(k):
                    v3 = True
                else:
                    d.pop(k, None)
            clips.append(d)
        settings = asdict(self.settings)
        for k, default in _V3_SETTINGS.items():
            if settings.get(k) != default:
                v3 = True
            else:
                settings.pop(k, None)
        texts = []
        for t in self.texts:
            d = asdict(t)
            if d.get('layer') is None:
                d.pop('layer', None)
            else:
                v3 = True
            if is_kinetic(t.style or {}):
                v3 = True
            texts.append(d)
        return {'version': PROJECT_VERSION if v3 else 2,
                'settings': settings,
                'tracks': [asdict(t) for t in self.tracks],
                'clips': clips,
                'markers': [asdict(m) for m in self.markers],
                'texts': texts}

    @classmethod
    def from_dict(cls, data, strict=False):
        """Проект из словаря. Версия проверяется всегда: v1 переводится в v2,
        версия новее программы — ProjectError. strict (внешние агенты) —
        любая проблема validate (без проверки файлов) тоже ProjectError;
        иначе, как и раньше во вкладке, негодные клипы выбрасываются."""
        p = cls()
        if not isinstance(data, dict):
            if strict:
                raise ProjectError("проект должен быть JSON-объектом")
            return p
        data = migrate_project_data(data)
        if strict:
            problems = validate(data, strict=True, check_files=False)
            if problems:
                raise ProjectError(f"проект не прошёл проверку: {len(problems)} проблем",
                                   problems)
        p.settings = parse_settings(data.get('settings'))
        p.markers = parse_markers(data.get('markers'))
        p.texts = parse_texts(data.get('texts'))
        # Списки — только списками: «"tracks": 5» в файле ронял загрузку
        # TypeError (итерация по числу) вместо пустого проекта.
        raw_tracks = data.get('tracks')
        raw_clips = data.get('clips')
        tracks = [Track(kind=t.get('kind', 'video'), enabled=bool(t.get('enabled', True)),
                        muted=bool(t.get('muted', False)),
                        role=t.get('role') if t.get('role') in TRACK_ROLES else '')
                  for t in (raw_tracks if isinstance(raw_tracks, list) else [])
                  if isinstance(t, dict) and t.get('kind') in ('video', 'audio')]
        if any(t.kind == 'video' for t in tracks):
            p.tracks = tracks
        names = {f.name for f in fields(Clip)}
        for raw in raw_clips if isinstance(raw_clips, list) else []:
            if not isinstance(raw, dict):
                continue
            try:
                # Типы и пределы (скорость) приводит Clip.__post_init__.
                c = Clip(**{k: v for k, v in raw.items() if k in names})
            except (TypeError, ValueError):
                continue                 # нет обязательных полей или они не числа
            if not (0 <= c.track < len(p.tracks)) or c.length <= _EPS:
                continue
            if p.tracks[c.track].kind != ('video' if c.has_video else 'audio'):
                continue                 # видеоклип на звуковой дорожке и наоборот
            p.clips.append(c)
        p.pack()
        return p

    def copy(self):
        return Project.from_dict(json.loads(json.dumps(self.to_dict())))

    def excerpt(self, t0, t1):
        """Копия проекта, где осталось только время [t0, t1) — сдвинутое к
        нулю. Клипы обрезаются по краям окна, раскладка не пересчитывается."""
        p = Project()
        p.tracks = [replace(t) for t in self.tracks]
        # Формат — всего проекта: у выдержки первый клип может быть другим,
        # и превью (или сэмпл «Обработки») вышло бы в чужом размере.
        w, h, fps = self.output_format()
        p.settings = replace(self.settings, width=w, height=h, fps=fps)
        for c in self.clips:
            a, b = max(c.start, t0), min(c.end, t1)
            if b - a <= _EPS:
                continue
            part = Clip(**{f.name: getattr(c, f.name) for f in fields(Clip)})
            if not c.frozen:
                part.in_s, part.out_s = sorted((c.source_time(a), c.source_time(b)))
            else:
                part.in_s, part.out_s = c.in_s + (a - c.start), c.in_s + (b - c.start)
            part.start = a - t0
            p.clips.append(part)
        return p


# ── Сборка итогового видео ───────────────────────────────────────────────────
def _num(v):
    return f"{float(v):.6f}".rstrip("0").rstrip(".") or "0"


def atempo_chain(speed):
    """Цепочка atempo для смены скорости звука: ffmpeg принимает звено от
    0.5 до 2.0, поэтому большие разы собираются из нескольких."""
    chain = []
    t = max(MIN_SPEED, min(MAX_SPEED, float(speed)))
    while t > 2.0:
        chain.append("atempo=2.0")
        t /= 2.0
    while t < 0.5:
        chain.append("atempo=0.5")
        t *= 2.0
    if abs(t - 1.0) > 0.001:
        chain.append(f"atempo={t:.6f}")
    return chain


def fps_expr(fps):
    """fps дробью для фильтров ffmpeg: 23.976 → 24000/1001."""
    fr = Fraction(float(fps)).limit_denominator(1001)
    return f"{fr.numerator}/{fr.denominator}"


def source_key(path):
    """Ключ файла для сравнения путей (регистр и вид разделителей)."""
    return os.path.normcase(os.path.abspath(str(path)))


def ff_color(color):
    """Цвет #RRGGBB для фильтров ffmpeg; чёрный — словом, как было в графе."""
    c = str(color or "").lower()
    if len(c) != 7 or c[0] != "#" or any(ch not in "0123456789abcdef" for ch in c[1:]):
        return "black"
    return "black" if c == "#000000" else "0x" + c[1:]


def fit_chain(mode, w, h, color="black"):
    """Цепочка «кадр в квадратных пикселях → ровно w×h» по способу
    вписывания (FIT_MODES), с запятой в конце."""
    if mode == 'fill':
        return f"scale={w}:{h},"
    if mode == 'crop':
        return (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},")
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={color},")


def _seek_s(c, s):
    """Точка входного -ss для кадра, начинающегося в s: на четверть кадра
    раньше — ffmpeg оставляет первый кадр с pts ≥ ss, а дробные fps не
    ложатся ровно в миллисекунды (тот же приём, что у «Экспорт»)."""
    if c.fps and c.fps > 0 and not c.is_image:
        idx = math.floor(s * c.fps + 1e-3)
        return max(0.0, (idx - 0.25) / c.fps)
    return max(0.0, s)


@dataclass
class SourceGraph:
    """Проект как источник для ffmpeg: входы и граф фильтров с выходами
    [vout] (видео yuv420p в размере и fps проекта) и [aout] (стерео 48 кГц)."""
    inputs: list                  # аргументы каждого входа: [..., "-i", путь]
    graph: str
    video: bool
    audio: bool
    duration: float               # длина итога (по сетке кадров, если есть видео)
    width: int
    height: int
    fps: float

    def input_args(self):
        return [a for args in self.inputs for a in args]


def save_project(project, path):
    """Атомарная запись проекта, как у пресетов субтитров
    (edit_tab_base._save_subtitle_presets): tmp на диск с fsync, прежний
    файл — в .bak, затем tmp на место. Сбой между двумя переносами оставляет
    .bak — его подхватит load_project."""
    path = str(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(project.to_dict(), f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(path, path + ".bak")
    os.replace(tmp, path)


def load_project(path, strict=False):
    """Проект из файла. Файла нет — его .bak (сбой посреди save_project),
    нет и его — пустой проект. Файл есть, но не загружается (не JSON,
    версия новее программы, строгая проверка) — ProjectError с path этого
    файла: вызывающий решает, что с ним делать, и не затирает его молча."""
    path = str(path)
    if not os.path.exists(path) and os.path.exists(path + ".bak"):
        path += ".bak"
    if not os.path.exists(path):
        return Project()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ProjectError(f"проект не прочитан: {e}", path=path) from e
    try:
        return Project.from_dict(data, strict=strict)
    except ProjectError as e:
        e.path = path
        raise


from si_hyx_parts.montage_project.schema import (  # noqa: E402
    describe_schema, migrate_project_data, parse_markers, parse_settings, parse_texts, validate)
from si_hyx_parts.montage_project.effects import (  # noqa: E402,F401
    EASES, EFFECT_KEYS, EFFECT_LIMITS, EFFECT_TYPES, CURVES_PRESETS, FINISH_TYPES, KEYFRAME_PROPS,
    curve_length, curve_source_offset, has_fx, keyframe_value, sanitize_curve, sanitize_effect,
    sanitize_effects, sanitize_keyframes, split_fx)
from si_hyx_parts.montage_project.layers import (  # noqa: E402,F401
    BLEND_MODES, MASK_SHAPES, MATTE_MODELS, STROKE_STYLES, matte_path, matte_span, matte_wanted,
    sanitize_blend, sanitize_box, sanitize_crop, sanitize_mask, sanitize_matte, sanitize_stroke)
from si_hyx_parts.montage_project.text_fx import (  # noqa: E402,F401
    FONT_ALIASES, is_kinetic, resolve_font)
from si_hyx_parts.montage_project.vulkan_fx import (  # noqa: E402,F401
    RIFE_MODELS, UPSCALE_PRESETS, interp_path, interp_rate, interp_wanted, shader_path,
    to_compute, upscale_of, vulkan_ok)
from si_hyx_parts.montage_project.graph import (  # noqa: E402,F401
    build_export, build_source, loudnorm_filter, text_cues)
