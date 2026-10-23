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
исходника тот же, а на проект он идёт быстрее или медленнее."""
import json
import math
import os
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from fractions import Fraction

PROJECT_VERSION = 1
MIN_CLIP_S = 0.04          # короче клип не бывает (подрезка, разрезание)
MIN_SPEED = 0.1            # пределы скорости клипа (доли и разы)
MAX_SPEED = 8.0
_EPS = 1e-6
_AUDIO_RATE = 48000          # частота звука сборки (и просмотра проекта)


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

    @property
    def play_speed(self):
        """Скорость на шкале в пределах MIN_SPEED…MAX_SPEED, у картинки — 1.
        Ею считают и длину клипа, и сборку картинки и звука: speed, присвоенный
        в обход set_speed, не разводит их."""
        if self.is_image:
            return 1.0
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
        """Время исходника для времени проекта t (внутри клипа)."""
        return self.in_s + max(0.0, t - self.start) * self.play_speed


@dataclass
class Track:
    kind: str                     # 'video' | 'audio'
    enabled: bool = True
    muted: bool = False           # звук клипов дорожки выключен (картинка остаётся)


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

    def pack(self):
        """Основная дорожка — вплотную, в порядке start (магнитная)."""
        t = 0.0
        for c in self.clips_on(self.main_track):
            c.start = t
            t = c.end

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
        cut = c.source_time(t)
        if c.fps and not c.is_image:
            cut = snap_to_frame(cut, c.fps)
        speed = c.play_speed
        if ((cut - c.in_s) / speed < MIN_CLIP_S - _EPS
                or (c.out_s - cut) / speed < MIN_CLIP_S - _EPS):
            return None
        right = Clip(**{f.name: getattr(c, f.name) for f in fields(Clip)})
        right.id = uuid.uuid4().hex[:12]
        right.in_s = cut
        right.start = c.start + (cut - c.in_s) / speed
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

    def trim(self, cid, edge, t):
        """Подрезка за край: edge 'left' или 'right', t — время проекта, куда
        тянут край. Пределы — начало и конец исходника (у картинки только
        начало: её можно растянуть сколько угодно)."""
        c = self.clip(cid)
        if c is None:
            return False
        limit = c.src_duration if (c.src_duration > 0 and not c.is_image) else float("inf")
        speed = c.play_speed
        min_src = MIN_CLIP_S * speed
        free = c.track != self.main_track
        # На свободной дорожке край упирается в соседа (и в начало шкалы).
        others = [o for o in self.clips_on(c.track) if o is not c] if free else []
        if edge == 'left':
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
                and c.audio_path and not c.muted and c.volume > 0 and c.length > _EPS]

    def output_format(self):
        """(ширина, высота, fps) итогового видео — по первому видеоклипу
        основной дорожки, как «по первому клипу» у Filmora."""
        first = next((c for c in self.clips_on(self.main_track)
                      if c.has_video and c.width > 0), None)
        if first is None:
            first = next((c for c in sorted(self.clips, key=lambda c: c.start)
                          if c.has_video and c.width > 0), None)
        if first is None:
            return 1280, 720, 30.0
        w, h = int(first.width) // 2 * 2, int(first.height) // 2 * 2
        fps = first.fps if (first.fps and first.fps > 0 and not first.is_image) else 30.0
        return max(2, w), max(2, h), float(fps)

    # ── Сохранение ───────────────────────────────────────────────────────────
    def to_dict(self):
        return {'version': PROJECT_VERSION,
                'tracks': [asdict(t) for t in self.tracks],
                'clips': [asdict(c) for c in self.clips]}

    @classmethod
    def from_dict(cls, data):
        p = cls()
        if not isinstance(data, dict):
            return p
        # Списки — только списками: «"tracks": 5» в файле ронял загрузку
        # TypeError (итерация по числу) вместо пустого проекта.
        raw_tracks = data.get('tracks')
        raw_clips = data.get('clips')
        tracks = [Track(kind=t.get('kind', 'video'), enabled=bool(t.get('enabled', True)),
                        muted=bool(t.get('muted', False)))
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
            if 0 <= c.track < len(p.tracks) and c.length > _EPS:
                p.clips.append(c)
        p.pack()
        return p

    def copy(self):
        return Project.from_dict(json.loads(json.dumps(self.to_dict())))

    def excerpt(self, t0, t1):
        """Копия проекта, где осталось только время [t0, t1) — сдвинутое к
        нулю. Клипы обрезаются по краям окна, раскладка не пересчитывается."""
        p = Project()
        p.tracks = [Track(t.kind, t.enabled, t.muted) for t in self.tracks]
        for c in self.clips:
            a, b = max(c.start, t0), min(c.end, t1)
            if b - a <= _EPS:
                continue
            part = Clip(**{f.name: getattr(c, f.name) for f in fields(Clip)})
            part.in_s = c.source_time(a)
            part.out_s = c.source_time(b)
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


def build_source(project, video=True, audio=True, subs=None, tonemap=None):
    """Граф проекта без кодирования: SourceGraph или None, если собирать
    нечего. video/audio=False выбрасывают соответствующую часть.

    tonemap — HDR-куски в SDR: {source_key(файл): цепочка фильтров}
    (hdr_tonemap.tonemap_filters). Цепочка встаёт первой, на кадр исходника:
    субтитры потом рисуются уже в SDR, а куски HDR и SDR файлов склеиваются
    в одном цветовом пространстве.

    subs — вшивание субтитров: {source_key(файл): фильтр subtitles=…}. Куски
    этих файлов получают фильтр на кадре исходника (до масштаба под проект)
    и во времени исходника: входной -ss обнуляет метки, а реплики фильтр
    ищет по времени самого файла субтитров.

    Как устроено: каждый видимый кусок видео — свой вход с входным -ss/-t
    (кадрово точно и без декодирования файла с начала), приводится к размеру и
    fps проекта и обрезается РОВНО до своего числа кадров; куски склеивает
    concat. Границы кусков округляются к сетке кадров проекта независимо, так
    что ошибка не копится: звук, расставленный по точному времени (adelay),
    не уезжает дальше полукадра на любом числе кусков. Звук всех клипов —
    отдельные входы, смешивание amix без приглушения."""
    segments = project.video_segments() if video else []
    parts = project.audio_parts() if audio else []
    if not segments and not parts:
        return None
    if segments and project.duration() > segments[-1][1] + _EPS:
        # Звук длиннее картинки — хвост видео добиваем чёрным кадром.
        segments.append((segments[-1][1], project.duration(), None))
    w, h, fps = project.output_format()
    rate = fps_expr(fps)
    inputs, chains = [], []
    total_s = project.duration()
    with_video = bool(segments)
    if with_video:
        frames_total = int(round(total_s * fps))
        total_s = frames_total / fps
    labels = []
    for t0, t1, c in segments:
        n = int(round(t1 * fps)) - int(round(t0 * fps))
        if n <= 0:
            continue
        lab = f"v{len(labels)}"
        if c is None:
            chains.append(f"color=c=black:s={w}x{h}:r={rate},trim=end_frame={n},"
                          f"setsar=1,format=yuv420p[{lab}]")
        else:
            idx = len(inputs)
            speed = c.play_speed
            s = c.source_time(t0)
            span = t1 - t0
            if c.is_image:
                inputs.append(["-loop", "1", "-framerate", rate,
                               "-t", _num(span + 1.0), "-i", c.src])
            else:
                inputs.append(["-ss", _num(_seek_s(c, s)),
                               "-t", _num(span * speed + 0.5), "-i", c.src])
            sub_vf = (subs or {}).get(source_key(c.src)) if not c.is_image else None
            tone_vf = (tonemap or {}).get(source_key(c.src)) if not c.is_image else None
            tone = f"{tone_vf}," if tone_vf else ""
            burn = ""
            if sub_vf:
                # Первый кадр после входного seek — кадр, на котором стоит s.
                first = snap_to_frame(s, c.fps)
                burn = (f"setpts=PTS-STARTPTS+{_num(first)}/TB,{sub_vf},")
            speed_vf = "" if abs(speed - 1.0) <= 1e-6 else f"setpts=(PTS-STARTPTS)/{_num(speed)},"
            # scale=iw*sar:ih — неквадратный пиксель (анаморфный DVD) в
            # квадратный до вписывания: вписывание шло по размеру в пикселях,
            # а setsar=1 потом показывал кадр 16:9 как 3:2. У квадратного
            # пикселя размер тот же — фильтр кадр не трогает.
            chains.append(
                f"[{idx}:v:0]{tone}{burn}setpts=PTS-STARTPTS,{speed_vf}"
                f"scale=iw*sar:ih,setsar=1,"
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
                f"fps={rate},tpad=stop_mode=clone:stop_duration=1,"
                f"trim=end_frame={n},setpts=PTS-STARTPTS,format=yuv420p[{lab}]")
        labels.append(lab)
    amix = []
    for c in parts:
        idx = len(inputs)
        speed = c.play_speed
        inputs.append(["-ss", _num(c.in_s), "-t", _num(c.length * speed + 0.25),
                       "-i", c.audio_path])
        spec = f"{idx}:{c.audio_stream}" if c.audio_stream >= 0 else f"{idx}:a:0"
        lab = f"a{len(amix)}"
        tempo = atempo_chain(speed)
        tempo_vf = (",".join(tempo) + ",") if tempo else ""
        # Место и длина — в сэмплах, от общей сетки шкалы: конец клипа и
        # начало следующего попадают в один и тот же сэмпл. С миллисекундами
        # (adelay округлял начало) на стыке оставалась дыра до 0.5 мс — щелчок.
        a0 = int(round(c.start * _AUDIO_RATE))
        n = max(1, int(round((c.start + c.length) * _AUDIO_RATE)) - a0)
        chains.append(
            f"[{spec}]aresample={_AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"{tempo_vf}atrim=end_sample={n},asetpts=PTS-STARTPTS,"
            f"volume={_num(c.volume)},adelay={a0}S:all=1[{lab}]")
        amix.append(lab)
    if labels:
        if len(labels) == 1:
            chains.append(f"[{labels[0]}]null[vout]")
        else:
            chains.append("".join(f"[{x}]" for x in labels)
                          + f"concat=n={len(labels)}:v=1:a=0[vout]")
    if amix:
        # Первым входом amix — тишина на всю длину проекта: amix берёт метки
        # времени у первого входа, и если им оказывался задержанный adelay
        # кусок (клип не с начала шкалы), ffmpeg выдавал битые метки — звук
        # обрывался на первых 20 мс («Error submitting a packet to the muxer»).
        # Тишина с нуля даёт ровную шкалу, а duration=first — точную длину.
        chains.append(f"anullsrc=r={_AUDIO_RATE}:cl=stereo,"
                      f"atrim=end_sample={max(1, int(round(total_s * _AUDIO_RATE)))}[asil]")
        chains.append("[asil]" + "".join(f"[{x}]" for x in amix)
                      + f"amix=inputs={len(amix) + 1}:normalize=0:"
                        f"dropout_transition=0:duration=first[aout]")
    return SourceGraph(inputs, ";".join(chains), bool(labels), bool(amix),
                       total_s, w, h, fps)


def build_export(project, out_path, ffmpeg, video_args, audio_args=None, subs=None,
                 tonemap=None):
    """Команда ffmpeg для сборки проекта.

    Возвращает (cmd, graph, duration): graph — граф фильтров (его кладут в
    файл и передают через -/filter_complex, если команда длинная), duration —
    длина итога для прогресса. None, если собирать нечего. subs и tonemap —
    как у build_source."""
    audio_args = audio_args or ["-c:a", "aac", "-b:a", "192k"]
    src = build_source(project, subs=subs, tonemap=tonemap)
    if src is None:
        return None
    cmd = [ffmpeg, "-y", "-hide_banner"] + src.input_args()
    cmd += ["-filter_complex", src.graph]
    if src.video:
        cmd += ["-map", "[vout]"] + list(video_args)
        if "-pix_fmt" not in video_args:
            cmd += ["-pix_fmt", "yuv420p"]
    if src.audio:
        cmd += ["-map", "[aout]"] + list(audio_args)
    else:
        cmd += ["-an"]
    cmd += ["-t", _num(src.duration), str(out_path)]
    return cmd, src.graph, src.duration


def save_project(project, path):
    """Атомарная запись проекта (tmp + replace)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(project.to_dict(), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_project(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return Project.from_dict(json.load(f))
    except (OSError, ValueError):
        return Project()
