# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE for details.
"""Картинки «Монтажа»: какие файлы считаются картинкой и как их отдать
ffmpeg и Qt. Без Qt при импорте — модулем пользуются montage_project и
montage_tool.

Большинство форматов ffmpeg читает картинкой сам (`-loop 1 -i файл`). Части
нужна PNG-копия:

* GIF — у демультиплексора gif нет `-loop`, вход падал «Option loop not found»;
* AVIF и HEIC/HEIF — альфа приходит отдельным потоком и теряется, у HEIC
  ещё и размер плиток вместо размера картинки;
* значки (ICO/CUR/ICNS) — несколько размеров в одном файле;
* SVG — в сборке ffmpeg нет librsvg.

Копия — первый кадр в RGBA, лежит в TEMP по отпечатку пути, времени правки
и размера файла (тот же файл — та же копия)."""
import hashlib
import os
import subprocess

from ffmpeg_env import CREATE_NO_WINDOW, FFMPEG, TEMP_DIR

# Что ffmpeg читает картинкой сам.
FFMPEG_EXTS = (
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".pjpeg", ".pjp", ".bmp", ".dib",
    ".webp", ".tif", ".tiff", ".tga", ".dds", ".qoi", ".pcx", ".sgi", ".rgb",
    ".rgba", ".bw", ".ppm", ".pgm", ".pbm", ".pam", ".pnm", ".pfm", ".phm",
    ".xbm", ".xpm", ".xwd", ".jp2", ".j2k", ".j2c", ".jpx", ".jxl", ".psd",
    ".exr", ".hdr", ".sun", ".ras", ".dpx",
)
# Что ему отдаётся PNG-копией (см. описание модуля).
CONVERT_EXTS = (
    ".gif", ".avif", ".heic", ".heif", ".hif", ".ico", ".cur", ".icns",
    ".svg", ".svgz", ".wbmp",
)
IMAGE_EXTS = FFMPEG_EXTS + CONVERT_EXTS

_COPY_DIR = os.path.join(TEMP_DIR, "si-hyx-stills")


def is_image_path(path):
    """Файл — картинка (по расширению)."""
    return os.path.splitext(str(path or ""))[1].lower() in IMAGE_EXTS


def dialog_patterns():
    """«*.png *.jpg …» для фильтра окна выбора файла."""
    return " ".join("*" + ext for ext in IMAGE_EXTS)


def _copy_path(path):
    st = os.stat(path)
    key = f"{os.path.abspath(path)}|{st.st_mtime_ns}|{st.st_size}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return os.path.join(_COPY_DIR, digest + ".png")


def _save_pillow(path, out):
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        if hasattr(pillow_heif, "register_avif_opener"):
            pillow_heif.register_avif_opener()
    except Exception:
        pass
    with Image.open(path) as im:
        try:
            im.seek(0)                 # анимация — первый кадр
        except Exception:
            pass
        # Значок (ICO/ICNS) Pillow сам открывает самым крупным размером.
        im = ImageOps.exif_transpose(im)
        im.convert("RGBA").save(out, "PNG")


def _save_qt(path, out):
    from PyQt6.QtGui import QImageReader
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    img = reader.read()
    if img.isNull() or not img.save(out, "PNG"):
        raise OSError(reader.errorString() or "Qt не прочитал картинку")


def _save_ffmpeg(path, out):
    r = subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-i", path, "-map", "0:v:0", "-frames:v", "1",
         "-update", "1", "-pix_fmt", "rgba", out],
        capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 or not os.path.isfile(out):
        raise OSError(r.stderr.decode("utf-8", "replace").strip() or "ffmpeg не прочитал картинку")


def png_copy(path):
    """PNG-копия картинки (первый кадр, RGBA) в TEMP; None — не вышло.
    Читают по очереди Pillow (с pillow_heif), Qt (SVG) и ffmpeg."""
    path = str(path)
    try:
        out = _copy_path(path)
    except OSError:
        return None
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    os.makedirs(_COPY_DIR, exist_ok=True)
    tmp = f"{out}.{os.getpid()}.tmp.png"
    for saver in (_save_pillow, _save_qt, _save_ffmpeg):
        try:
            saver(path, tmp)
            os.replace(tmp, out)
            return out
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return None


def ffmpeg_still(path):
    """Путь картинки для `-loop 1 -i`: сам файл или его PNG-копия."""
    path = str(path)
    if os.path.splitext(path)[1].lower() in CONVERT_EXTS:
        return png_copy(path) or path
    return path


def read_qimage(path):
    """QImage картинки любого формата из IMAGE_EXTS; None — не вышло. Что
    Qt сам не читает (AVIF, HEIC, JPEG XL, EXR, PSD…) — через PNG-копию."""
    from PyQt6.QtGui import QImage
    path = str(path)
    img = QImage()
    if os.path.splitext(path)[1].lower() not in CONVERT_EXTS:
        img = QImage(path)
    if img.isNull():
        copy = png_copy(path)
        img = QImage(copy) if copy else QImage()
    return None if img.isNull() else img
