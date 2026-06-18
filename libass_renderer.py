# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# libass_renderer.py — рендер ASS/SSA-субтитров в превью через нативную libass.
#
# Зачем: QtMultimedia не даёт стилизовать субтитры и не пускает рисовать поверх
# нативной поверхности видео. Чтобы в превью был ПОЛНЫЙ ASS (шрифты, цвета,
# позиции, караоке \k, анимации) как в VLC/PotPlayer, мы вызываем libass на
# текущей позиции воспроизведения и накладываем готовую RGBA-картинку на
# окно-оверлей субтитров (см. edit_tab.SubtitleOverlay). Видео при этом остаётся
# на быстром GPU-пути QVideoWidget — мы НЕ перехватываем кадры.
#
# Нативные DLL (libass-9.dll + freetype/fribidi/harfbuzz/glib2/…) кладутся рядом
# с программой в bin/. Если их нет или загрузка не удалась — AVAILABLE=False, и
# вызывающий код откатывается на обычный текстовый оверлей.
import os
import sys
import ctypes
from ctypes import (c_int, c_uint, c_uint32, c_double, c_void_p, c_char_p,
                    c_size_t, c_longlong, c_ubyte, POINTER, Structure, byref)

try:
    import numpy as np
except Exception:
    np = None

# ── Поиск и загрузка libass-9.dll + зависимостей ───────────────────────────────
_LIB = None
_DLL_DIR = None
AVAILABLE = False
LOAD_ERROR = ""

_LIBASS_NAMES = ("libass-9.dll", "libass.dll", "ass.dll")


def _candidate_dirs():
    """Каталоги, где могут лежать bundled-DLL (рядом с exe/скриптом и в bin/)."""
    dirs = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        dirs += [base, os.path.join(base, "bin")]
    try:
        d1 = os.path.dirname(os.path.abspath(sys.argv[0] or "."))
        dirs += [d1, os.path.join(d1, "bin")]
    except Exception:
        pass
    d2 = os.path.dirname(os.path.abspath(__file__))
    dirs += [d2, os.path.join(d2, "bin")]
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d); out.append(d)
    return out


def _try_load():
    global _LIB, _DLL_DIR, AVAILABLE, LOAD_ERROR
    if np is None:
        LOAD_ERROR = "numpy недоступен"
        return False
    for d in _candidate_dirs():
        for name in _LIBASS_NAMES:
            path = os.path.join(d, name)
            if not os.path.isfile(path):
                continue
            try:
                # Зависимости (freetype/harfbuzz/…) лежат в той же папке. Грузим
                # libass по полному пути с LOAD_WITH_ALTERED_SEARCH_PATH (0x8),
                # чтобы весь его граф зависимостей резолвился из этой папки.
                try:
                    os.add_dll_directory(d)
                except Exception:
                    pass
                lib = ctypes.CDLL(path, winmode=0x00000008)
                _bind(lib)
                _LIB = lib
                _DLL_DIR = d
                AVAILABLE = True
                return True
            except Exception as e:
                LOAD_ERROR = f"{name}: {e}"
                continue
    if not LOAD_ERROR:
        LOAD_ERROR = "libass-9.dll не найден в bin/"
    return False


# ── Структуры C API ────────────────────────────────────────────────────────────
class ASS_Image(Structure):
    pass


ASS_Image._fields_ = [
    ("w", c_int), ("h", c_int), ("stride", c_int),
    ("bitmap", POINTER(c_ubyte)),
    ("color", c_uint32),               # 0xRRGGBBAA (AA — прозрачность: 0=непрозр.)
    ("dst_x", c_int), ("dst_y", c_int),
    ("next", POINTER(ASS_Image)),
    ("type", c_int),
]

# Провайдеры шрифтов (ASS_DefaultFontProvider)
ASS_FONTPROVIDER_AUTODETECT = 1


def _bind(lib):
    lib.ass_library_init.restype = c_void_p
    lib.ass_library_done.argtypes = [c_void_p]
    lib.ass_set_extract_fonts.argtypes = [c_void_p, c_int]
    lib.ass_set_fonts_dir.argtypes = [c_void_p, c_char_p]

    lib.ass_renderer_init.restype = c_void_p
    lib.ass_renderer_init.argtypes = [c_void_p]
    lib.ass_renderer_done.argtypes = [c_void_p]
    lib.ass_set_frame_size.argtypes = [c_void_p, c_int, c_int]
    lib.ass_set_storage_size.argtypes = [c_void_p, c_int, c_int]
    lib.ass_set_pixel_aspect.argtypes = [c_void_p, c_double]
    lib.ass_set_fonts.argtypes = [c_void_p, c_char_p, c_char_p, c_int, c_char_p, c_int]

    lib.ass_read_memory.restype = c_void_p
    lib.ass_read_memory.argtypes = [c_void_p, c_char_p, c_size_t, c_char_p]
    lib.ass_free_track.argtypes = [c_void_p]

    lib.ass_render_frame.restype = POINTER(ASS_Image)
    lib.ass_render_frame.argtypes = [c_void_p, c_void_p, c_longlong, POINTER(c_int)]


_try_load()


# ── Высокоуровневый рендерер ────────────────────────────────────────────────────
class AssRenderer:
    """Загружает ASS-дорожку и рендерит её на заданное разрешение кадра.
    render(now_ms) -> (QImage|None, changed: bool). QImage в формате
    RGBA8888_Premultiplied, размером с кадр; None — если нет видимых субтитров."""

    def __init__(self, default_family="Arial"):
        if not AVAILABLE:
            raise RuntimeError("libass недоступна: " + LOAD_ERROR)
        self._lib = _LIB
        self._library = self._lib.ass_library_init()
        if not self._library:
            raise RuntimeError("ass_library_init вернул NULL")
        self._lib.ass_set_extract_fonts(self._library, 1)
        self._renderer = self._lib.ass_renderer_init(self._library)
        if not self._renderer:
            raise RuntimeError("ass_renderer_init вернул NULL")
        # Шрифты: автоопределение системного провайдера (DirectWrite/fontconfig).
        fam = default_family.encode("utf-8") if default_family else None
        self._lib.ass_set_fonts(self._renderer, None, fam,
                                ASS_FONTPROVIDER_AUTODETECT, None, 1)
        self._track = None
        self._w = 0
        self._h = 0

    def load_ass_bytes(self, data: bytes, codepage="UTF-8"):
        self._free_track()
        buf = ctypes.create_string_buffer(data, len(data))
        self._track = self._lib.ass_read_memory(
            self._library, buf, len(data),
            codepage.encode("ascii") if codepage else None)
        return bool(self._track)

    def load_ass_file(self, path: str):
        with open(path, "rb") as f:
            return self.load_ass_bytes(f.read())

    def set_frame_size(self, w, h):
        w = max(1, int(w)); h = max(1, int(h))
        if (w, h) == (self._w, self._h):
            return
        self._w, self._h = w, h
        self._lib.ass_set_frame_size(self._renderer, w, h)
        self._lib.ass_set_storage_size(self._renderer, w, h)
        try:
            self._lib.ass_set_pixel_aspect(self._renderer, 1.0)
        except Exception:
            pass

    def render(self, now_ms):
        """Рендерит кадр субтитров на момент now_ms (мс). Возвращает
        (numpy RGBA premultiplied | None, x, y, changed). Картинка обрезана до
        ограничивающего прямоугольника субтитров (x,y — его левый верхний угол в
        координатах кадра), чтобы не гонять полноэкранные numpy-операции."""
        if not self._track or not self._w or not self._h:
            return None, 0, 0, False
        change = c_int(0)
        head = self._lib.ass_render_frame(
            self._renderer, self._track, c_longlong(int(now_ms)), byref(change))
        if not head:
            return None, 0, 0, bool(change.value)
        # Ограничивающий прямоугольник всех картинок (с обрезкой по кадру).
        imgs = []
        minx = miny = 1 << 30
        maxx = maxy = -(1 << 30)
        img = head
        while img:
            im = img.contents
            if im.w > 0 and im.h > 0:
                x0 = max(0, im.dst_x); y0 = max(0, im.dst_y)
                x1 = min(self._w, im.dst_x + im.w); y1 = min(self._h, im.dst_y + im.h)
                if x1 > x0 and y1 > y0:
                    imgs.append(im)
                    minx = min(minx, x0); miny = min(miny, y0)
                    maxx = max(maxx, x1); maxy = max(maxy, y1)
            img = im.next
        if not imgs or maxx <= minx or maxy <= miny:
            return None, 0, 0, bool(change.value)
        bw, bh = maxx - minx, maxy - miny
        canvas = np.zeros((bh, bw, 4), dtype=np.float32)
        for im in imgs:
            self._blend(canvas, im, minx, miny)
        out = np.empty((bh, bw, 4), dtype=np.uint8)
        np.clip(canvas[..., 0:3], 0, 255, out=canvas[..., 0:3])
        out[..., 0:3] = canvas[..., 0:3].astype(np.uint8)
        out[..., 3] = np.clip(canvas[..., 3] * 255.0, 0, 255).astype(np.uint8)
        return out, int(minx), int(miny), bool(change.value)

    def _blend(self, canvas, im, ox=0, oy=0):
        w, h, stride = im.w, im.h, im.stride
        if w <= 0 or h <= 0:
            return
        x, y = im.dst_x - ox, im.dst_y - oy
        H, W = canvas.shape[0], canvas.shape[1]
        # Обрезка по краям буфера (bbox).
        sx = sy = 0
        if x < 0: sx = -x; x = 0
        if y < 0: sy = -y; y = 0
        cw = min(w - sx, W - x)
        ch = min(h - sy, H - y)
        if cw <= 0 or ch <= 0:
            return
        color = im.color
        r = (color >> 24) & 0xFF
        g = (color >> 16) & 0xFF
        b = (color >> 8) & 0xFF
        a = color & 0xFF                      # прозрачность 0..255 (0 = непрозр.)
        opacity = (255 - a) / 255.0
        if opacity <= 0.0:
            return
        n = stride * h
        cov = np.ctypeslib.as_array(im.bitmap, shape=(n,)).reshape(h, stride)
        cov = cov[sy:sy + ch, sx:sx + cw].astype(np.float32) * (opacity / 255.0)  # 0..1
        region = canvas[y:y + ch, x:x + cw]
        inv = 1.0 - cov
        region[..., 0] = r * cov + region[..., 0] * inv
        region[..., 1] = g * cov + region[..., 1] * inv
        region[..., 2] = b * cov + region[..., 2] * inv
        region[..., 3] = cov + region[..., 3] * inv

    def _free_track(self):
        if self._track:
            try: self._lib.ass_free_track(self._track)
            except Exception: pass
            self._track = None

    def close(self):
        self._free_track()
        try:
            if self._renderer:
                self._lib.ass_renderer_done(self._renderer); self._renderer = None
        except Exception: pass
        try:
            if self._library:
                self._lib.ass_library_done(self._library); self._library = None
        except Exception: pass

    def __del__(self):
        try: self.close()
        except Exception: pass
