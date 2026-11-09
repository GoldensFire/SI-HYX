# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# pgs_subtitles.py — картиночные субтитры Blu-ray (PGS, поток .sup) для превью
# «Монтажа».
#
# Зачем: QtMultimedia показывает только текстовые субтитры, а включённую
# дорожку PGS Qt 6.12 разбирает как текст и роняет процесс (чтение по нулевому
# адресу в ffmpegmediaplugin.dll). Поэтому плееру картиночные дорожки не
# отдаются: ffmpeg копирует дорожку в поток .sup (`-c:s copy -f sup`), здесь он
# разбирается на события показа, а картинка события собирается в RGBA только
# тогда, когда её надо показать.
#
# Картинка — ровно как у pgssubdec ffmpeg, которым субтитры вшиваются при
# экспорте: объекты в своих позициях без обрезки и окон, палитра YCbCr
# «студийного» диапазона (BT.709 у HD-холста, BT.601 у SD), кэш объектов и
# палитр сбрасывается на каждом PCS с состоянием «начало эпохи» или «точка
# входа». Превью и вшитый файл совпадают.
#
# Формат .sup: сегменты «PG» + PTS/DTS (90 кГц) + тип + длина + тело. Набор
# показа — PCS (композиция) [WDS] [PDS палитры] [ODS объекты] END; PCS без
# объектов гасит экран.
import bisect
import struct
from collections import OrderedDict

import numpy as np

# Кодеки дорожек, которые разбирает этот модуль (имена ffprobe).
PGS_CODECS = frozenset({'hdmv_pgs_subtitle', 'pgssub'})

_PDS, _ODS, _PCS, _END = 0x14, 0x15, 0x16, 0x80

# Сколько собранных картинок и распакованных объектов держим в памяти: при
# перемотке назад и покадровом шаге одно и то же событие показывается снова.
_IMAGE_CACHE = 8
_BITMAP_CACHE = 32


def iter_segments(data):
    """(pts в 1/90000 с, тип, тело) каждого сегмента потока .sup. Мусор между
    сегментами пропускается до следующей метки «PG»."""
    pos, n = 0, len(data)
    while pos + 13 <= n:
        if data[pos] != 0x50 or data[pos + 1] != 0x47:      # b"PG"
            nxt = data.find(b"PG", pos + 1)
            if nxt < 0:
                return
            pos = nxt
            continue
        pts = int.from_bytes(data[pos + 2:pos + 6], "big")
        kind = data[pos + 10]
        end = pos + 13 + int.from_bytes(data[pos + 11:pos + 13], "big")
        if end > n:
            return
        yield pts, kind, data[pos + 13:end]
        pos = end


def decode_rle(data, width, height):
    """RLE объекта PGS → индексы палитры (height × width, uint8).

    Как decode_rle в pgssubdec: ненулевой байт — один пиксель этого цвета;
    0x00 + флаги — серия (0x40 — длина в 14 бит, 0x80 — цвет отдельным байтом,
    иначе цвет 0); серия нулевой длины — конец строки. Пиксели идут подряд,
    строки не добиваются; недостающее в конце прозрачно."""
    total = width * height
    out = bytearray()
    find = data.find
    pos, n, rows = 0, len(data), 0
    while pos < n and rows < height:
        z = find(b"\x00", pos)
        if z < 0:
            z = n
        if z > pos:
            out += data[pos:z]          # подряд идущие одиночные пиксели
            if z >= n:
                break
        if z + 1 >= n:
            break
        flags = data[z + 1]
        p = z + 2
        run = flags & 0x3F
        if flags & 0x40:
            if p >= n:
                break
            run = (run << 8) | data[p]
            p += 1
        color = 0
        if flags & 0x80:
            if p >= n:
                break
            color = data[p]
            p += 1
        pos = p
        if run:
            out += bytes((color,)) * run if color else bytes(run)
        else:
            rows += 1
    if len(out) < total:
        out += bytes(total - len(out))
    elif len(out) > total:
        del out[total:]
    return np.frombuffer(out, dtype=np.uint8).reshape(height, width)


def palette_rgba(entries, hd):
    """Палитра PDS {индекс: (Y, Cr, Cb, A)} → массив 256 × 4 RGBA с
    предумноженной альфой (формат RGBA8888_Premultiplied). Цвета без записи
    прозрачны."""
    pal = np.zeros((256, 4), dtype=np.uint8)
    if not entries:
        return pal
    idx = np.fromiter(entries.keys(), dtype=np.intp, count=len(entries))
    ycca = np.array(list(entries.values()), dtype=np.float64)
    y = (ycca[:, 0] - 16.0) * (255.0 / 219.0)
    cr = (ycca[:, 1] - 128.0) * (255.0 / 224.0)
    cb = (ycca[:, 2] - 128.0) * (255.0 / 224.0)
    if hd:      # BT.709
        rgb = np.stack([y + 1.5747 * cr,
                        y - 0.1873 * cb - 0.4682 * cr,
                        y + 1.8556 * cb], axis=1)
    else:       # BT.601
        rgb = np.stack([y + 1.402 * cr,
                        y - 0.34414 * cb - 0.71414 * cr,
                        y + 1.772 * cb], axis=1)
    alpha = ycca[:, 3:4]
    rgb = np.clip(rgb, 0.0, 255.0) * (alpha / 255.0)
    pal[idx, :3] = np.rint(rgb).astype(np.uint8)
    pal[idx, 3] = alpha[:, 0].astype(np.uint8)
    return pal


class PgsTrack:
    """Разобранная дорожка: события показа по времени и данные их картинок.
    Пользоваться — из одного потока (кэши без блокировок)."""

    def __init__(self, starts, events):
        self._starts = starts       # мс начала события, по возрастанию
        self._events = events       # (холст_w, холст_h, палитра, объекты) | None
        self._images = OrderedDict()
        self._bitmaps = OrderedDict()

    def __len__(self):
        return len(self._events)

    def has_images(self):
        return any(ev is not None for ev in self._events)

    def event_at(self, ms):
        """Номер события, видимого в момент ms, или -1 (экран пуст)."""
        i = bisect.bisect_right(self._starts, ms) - 1
        if i < 0 or self._events[i] is None:
            return -1
        return i

    def image(self, ev):
        """(rgba, x, y, холст_w, холст_h) события ev: rgba — массив h × w × 4
        (альфа предумножена) с левым верхним углом в (x, y) холста; None —
        показывать нечего."""
        if not 0 <= ev < len(self._events) or self._events[ev] is None:
            return None
        hit = self._images.get(ev)
        if hit is None:
            hit = self._compose(self._events[ev]) or False
            self._images[ev] = hit
            while len(self._images) > _IMAGE_CACHE:
                self._images.popitem(last=False)
        else:
            self._images.move_to_end(ev)
        return hit or None

    def _bitmap(self, obj):
        hit = self._bitmaps.get(obj)
        if hit is None:
            w, h, rle = obj
            hit = decode_rle(rle, w, h)
            self._bitmaps[obj] = hit
            while len(self._bitmaps) > _BITMAP_CACHE:
                self._bitmaps.popitem(last=False)
        else:
            self._bitmaps.move_to_end(obj)
        return hit

    def _compose(self, event):
        cw, ch, entries, objects = event
        placed = []
        for obj, x, y in objects:
            w, h = obj[0], obj[1]
            # Холст — кадр видео: всё, что за его краем, не видно и в экспорте.
            x0, y0 = max(x, 0), max(y, 0)
            x1, y1 = min(x + w, cw), min(y + h, ch)
            if x1 > x0 and y1 > y0:
                placed.append((obj, x, y, x0, y0, x1, y1))
        if not placed:
            return None
        pal = palette_rgba(entries, ch > 576)
        bx0 = min(p[3] for p in placed)
        by0 = min(p[4] for p in placed)
        bx1 = max(p[5] for p in placed)
        by1 = max(p[6] for p in placed)
        out = np.zeros((by1 - by0, bx1 - bx0, 4), dtype=np.uint8)
        for obj, x, y, x0, y0, x1, y1 in placed:
            idx = self._bitmap(obj)[y0 - y:y1 - y, x0 - x:x1 - x]
            # Объекты кладутся поверх по порядку композиции, без смешивания —
            # как sub2video ffmpeg при вшивании.
            out[y0 - by0:y1 - by0, x0 - bx0:x1 - bx0] = pal[idx]
        return out, bx0, by0, cw, ch


def parse_sup(data):
    """Поток .sup → PgsTrack. Объекты остаются сжатыми до первого показа."""
    starts, events = [], []
    palettes, objects = {}, {}
    pending = None      # (мс, холст_w, холст_h, палитра, ссылки) открытого набора

    def close_set():
        nonlocal pending
        if pending is None:
            return
        ms, cw, ch, pal_id, refs = pending
        pending = None
        entries = palettes.get(pal_id)
        items = []
        if entries is not None and cw > 0 and ch > 0:
            for oid, x, y in refs:
                obj = objects.get(oid)
                if obj is not None and obj[0] > 0 and obj[1] > 0:
                    items.append((obj, x, y))
        starts.append(ms)
        events.append((cw, ch, entries, tuple(items)) if items else None)

    for pts, kind, body in iter_segments(data):
        if kind == _PCS:
            close_set()
            if len(body) < 11:
                continue
            cw, ch = struct.unpack_from(">HH", body, 0)
            if body[7] >> 6:    # начало эпохи / точка входа: всё приходит заново
                palettes.clear()
                objects.clear()
            refs, p = [], 11
            for _ in range(body[10]):
                if p + 8 > len(body):
                    break
                oid, _window, flags, x, y = struct.unpack_from(">HBBHH", body, p)
                p += 16 if flags & 0x80 else 8      # 0x80 — с полями обрезки
                refs.append((oid, x, y))
            pending = (pts / 90.0, cw, ch, body[9], refs)
        elif kind == _PDS:
            if len(body) < 2:
                continue
            # Новый словарь, а не правка старого: прежние события держат свой.
            entries = dict(palettes.get(body[0], {}))
            for p in range(2, len(body) - 4, 5):
                entries[body[p]] = (body[p + 1], body[p + 2], body[p + 3], body[p + 4])
            palettes[body[0]] = entries
        elif kind == _ODS:
            if len(body) < 4:
                continue
            oid = int.from_bytes(body[0:2], "big")
            if body[3] & 0x80:      # первый фрагмент: длина, ширина, высота
                if len(body) < 11:
                    continue
                w, h = struct.unpack_from(">HH", body, 7)
                objects[oid] = (w, h, body[11:])
            elif oid in objects:
                w, h, rle = objects[oid]
                objects[oid] = (w, h, rle + body[4:])
        elif kind == _END:
            close_set()
    close_set()
    return PgsTrack(starts, events)
