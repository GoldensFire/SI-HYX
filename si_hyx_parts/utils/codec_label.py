# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""codec_label. Public namespace: utils."""
import utils as _api


def codec_label(codec_name):
    """Читаемое имя кодека (h264 → «H.264», av1 → «AV1» и т.п.) для UI —
    неизвестные кодеки показываются как есть, в верхнем регистре."""
    if not codec_name:
        return None
    key = codec_name.strip().lower()
    return _api._CODEC_LABELS.get(key, key.upper())

codec_label.__module__ = _api.__name__
_api.codec_label = codec_label

def get_video_codec_label(path):
    """Кодек видеодорожки файла в человекочитаемом виде («H.264»/«H.265»/«AV1»…)
    или None, если видеодорожки нет (аудио-файл) либо ffprobe не смог определить."""
    return _api.codec_label(_api.get_video_codec(path))

get_video_codec_label.__module__ = _api.__name__
_api.get_video_codec_label = get_video_codec_label

def get_pix_fmt(path):
    """pix_fmt первого видеопотока ("" — не вышло/видео нет).

    Нужен там, где фильтрграф обязан назвать формат явно: см.
    overlay_chroma_format."""
    try:
        p = _api.subprocess.run(
            [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW,
            timeout=15)
        return (p.stdout or "").strip().lower()
    except Exception:
        return ""

get_pix_fmt.__module__ = _api.__name__
_api.get_pix_fmt = get_pix_fmt

def overlay_chroma_format(pix_fmt):
    """Значение опции `format=` фильтра overlay под формат ИСХОДНИКА.

    Почему нельзя оставлять `format=auto` (это был баг «после Монтажа видео
    другого цвета»): накладка приходит в граф как RGBA (movie=…,format=rgba), и
    при `auto` ffmpeg волен свести ВЕСЬ граф к RGB. Тогда libx264 кодирует поток
    в gbrp, кадр уезжает в цветовое пространство «gbr», и уже сам ffmpeg,
    декодируя такой файл, показывает кислотно-зелёное/малиновое изображение
    (проверено на живом файле: исходник оранжевый — итог зелёный). Явный
    YUV-формат оставляет кадр в YUV, конвертируется только накладка, а теги
    цвета (bt709) исходника доезжают до вывода нетронутыми.

    Формат выбираем ПО ИСХОДНИКУ, чтобы накладка не роняла ни глубину (10 бит),
    ни цветность (4:2:2/4:4:4) видео. Исключение — RGB-исходники (кадр из
    картинки): «auto» врёт и на них (проверено: PNG → gbrp → тот же зелёный
    кадр), а на выходе всё равно обычное видео, поэтому им идёт самый
    совместимый yuv420."""
    v = (pix_fmt or "").strip().lower()
    deep = ("p10" in v) or ("p12" in v) or ("p14" in v) or ("p16" in v)
    if "444" in v:
        base = "yuv444"
    elif "422" in v:
        base = "yuv422"
    else:
        base = "yuv420"
    return base + ("p10" if deep else "")

overlay_chroma_format.__module__ = _api.__name__
_api.overlay_chroma_format = overlay_chroma_format

def escape_filter_path(p):
    """Экранирует путь для libavfilter (movie/subtitles/fontsdir): прямые слэши
    + экранированное двоеточие диска (обратный слэш перед `:`) + экранированная
    кавычка. Без
    экранирования двоеточия фильтр на Windows не инициализируется."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

escape_filter_path.__module__ = _api.__name__
_api.escape_filter_path = escape_filter_path

def overlay_filter_graph(base_chain, rendered, escape_path=None,
                         pix_fmt="yuv420"):
    """Собирает -vf для экспорта с наложенными картинками.

    base_chain — уже готовая цепочка видеофильтров одной строкой (кадрирование,
                 субтитры, пикселизация, масштаб/фейды «Обработки»), может быть
                 пустой;
    rendered   — список (png_path, x, y) от ImageOverlay.save_png;
    pix_fmt    — формат работы overlay (см. overlay_chroma_format).

    Схема графа (без спец-меток вроде [in]/[out], их поддержка у ffmpeg
    исторически плавала): картинки заводятся источниками `movie`, кадр проходит
    через `null` (единственный неподписанный вход графа = вход -vf), дальше
    последовательные overlay, и в конце — базовая цепочка. Накладки идут ПЕРЕД
    базовой цепочкой: их координаты посчитаны в пикселях ИСХОДНОГО кадра, и
    кадрирование/масштаб обязаны применяться уже к кадру с картинкой — ровно
    так, как это видно в плеере Монтажа."""
    if not rendered:
        return base_chain or ""
    esc = escape_path or _api.escape_filter_path
    fmt = (pix_fmt or "yuv420").strip()
    parts = []
    for i, (png, _x, _y) in enumerate(rendered):
        parts.append(f"movie='{esc(png)}',format=rgba[sihyxovl{i}]")
    parts.append("null[sihyxbase0]")
    last = len(rendered) - 1
    for i, (_png, x, y) in enumerate(rendered):
        out = "" if (i == last and not base_chain) else f"[sihyxbase{i + 1}]"
        parts.append(f"[sihyxbase{i}][sihyxovl{i}]"
                     f"overlay=x={int(x)}:y={int(y)}:eof_action=repeat"
                     f":format={fmt}{out}")
    if base_chain:
        parts.append(f"[sihyxbase{last + 1}]{base_chain}")
    return ";".join(parts)

overlay_filter_graph.__module__ = _api.__name__
_api.overlay_filter_graph = overlay_filter_graph

def measure_loudness(path, should_stop=None, start=None, dur=None):
    """Сканирует громкость файла. should_stop — необязательный callable: если он
    начинает возвращать True во время сканирования (пользователь нажал «Стоп»),
    процесс ffmpeg убивается и функция возвращает None. Без него — как раньше,
    блокирующий проход. Для длинных файлов (часы) без этого «Стоп» не срабатывал,
    пока полный проход loudnorm не закончится (см. process_media).

    start/dur (необязательные, секунды) — сканировать только этот диапазон
    (обрезка + «Обработка» одним проходом: «до»-LUFS должен быть за сам
    вырезаемый отрезок, а не за весь исходник). Точность кадра тут не нужна —
    обычный входной seek.

    `-vn -sn -dn`: меряется ГРОМКОСТЬ, а видео здесь не нужно. Без -vn ffmpeg
    по правилам выбора потоков для нулевого мультиплексора берёт ещё и лучшую
    видеодорожку и честно декодирует её целиком — на длинном фильме это
    минуты впустую перед каждым кодированием (замер идёт всегда, даже когда
    нормализация выключена: значение показывает колонка «LUFS»). Замерено на
    1080p25: 0.61 с → 0.32 с на 10-секундном отрезке, а на исходниках с
    тяжёлым кодеком (AV1/HEVC 4K) разрыв кратно больше."""
    try:
        ss = ["-ss", f"{start:.3f}"] if start else []
        t = ["-t", f"{dur:.3f}"] if dur else []
        cmd = [_api.FFMPEG, "-hide_banner", "-nostats"] + ss + ["-i", path] + t + ["-vn", "-sn", "-dn", "-af", "loudnorm=I=-16:LRA=20:TP=-1.5:print_format=json", "-f", "null", "-"]
        p = _api.subprocess.Popen(cmd, stderr=_api.subprocess.PIPE, stdout=_api.subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW)
        if should_stop is None:
            stderr = p.communicate()[1] or ""
        else:
            # communicate(timeout=…) короткими тиками: фоновые потоки чтения
            # сами осушают pipe (нет дедлока на длинном файле), а мы между
            # тиками проверяем should_stop() и убиваем ffmpeg при «Стоп».
            stderr = ""
            while True:
                if should_stop():
                    try: p.kill()
                    except Exception: pass
                    try: p.communicate(timeout=2)
                    except Exception: pass
                    return None
                try:
                    stderr = p.communicate(timeout=0.2)[1] or ""
                    break
                except _api.subprocess.TimeoutExpired:
                    continue
        m = _api._RE_LUFS.search(stderr)
        if m:
            data = _api.json.loads(m.group(0))
            if 'input_i' in data:
                return float(data.get('input_i'))
    except Exception:
        pass
    return None

measure_loudness.__module__ = _api.__name__
_api.measure_loudness = measure_loudness

def play_done_sound():
    try:
        if _api.IS_WIN:
            import winsound
            try: winsound.MessageBeep(winsound.MB_ICONEXCLAMATION); return
            except Exception: winsound.Beep(750, 300); return
    except Exception: pass
    try: print('\a', end='', flush=True)
    except Exception: pass

play_done_sound.__module__ = _api.__name__
_api.play_done_sound = play_done_sound

def rasterize_svg(path, max_dim=2048):
    """Растеризует SVG-файл в PIL.Image (RGBA) через QtSvg. PIL не умеет SVG,
    поэтому рисуем вектор в QImage и переводим в PIL. Возвращает None при ошибке
    или если QtSvg/PIL недоступны."""
    if not _api.Image:
        return None
    try:
        from PyQt6.QtSvg import QSvgRenderer
        from PyQt6.QtCore import QBuffer
    except Exception:
        return None
    try:
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            return None
        size = renderer.defaultSize()
        w, h = size.width(), size.height()
        if w <= 0 or h <= 0:
            w = h = 1024
        # Векторную картинку растеризуем покрупнее, чтобы при объединении она
        # была чёткой (но не больше max_dim по большей стороне).
        scale = max(1.0, 1024 / max(w, h))
        w2, h2 = int(round(w * scale)), int(round(h * scale))
        if max(w2, h2) > max_dim:
            k = max_dim / max(w2, h2)
            w2, h2 = int(round(w2 * k)), int(round(h2 * k))
        qimg = _api.QtGuiImage(w2, h2, _api.QtGuiImage.Format.Format_ARGB32)
        qimg.fill(0)  # прозрачный фон
        p = _api.QPainter(qimg)
        renderer.render(p)
        p.end()
        ba = _api.QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        qimg.save(buf, 'PNG')
        buf.close()
        return _api.Image.open(_api.io.BytesIO(bytes(ba))).convert('RGBA')
    except Exception:
        return None

rasterize_svg.__module__ = _api.__name__
_api.rasterize_svg = rasterize_svg

def open_image_any(path):
    """Открывает изображение как PIL.Image, поддерживая в т.ч. SVG (через
    растеризацию QtSvg). Возвращает PIL.Image. Бросает исключение, как Image.open,
    если формат не распознан."""
    if _api.os.path.splitext(path)[1].lower() == '.svg':
        im = _api.rasterize_svg(path)
        if im is None:
            raise ValueError(f"Не удалось растеризовать SVG: {path}")
        return im
    return _api.Image.open(path)

open_image_any.__module__ = _api.__name__
_api.open_image_any = open_image_any

def load_pixmap_any(path, max_dim=1024):
    """QPixmap из любого файла, включая SVG (растеризуется через QtSvg).
    Пустой QPixmap при ошибке."""
    if _api.os.path.splitext(path)[1].lower() == '.svg':
        try:
            from PyQt6.QtSvg import QSvgRenderer
            renderer = QSvgRenderer(path)
            if renderer.isValid():
                size = renderer.defaultSize()
                w, h = size.width(), size.height()
                if w <= 0 or h <= 0:
                    w = h = max_dim
                scale = min(1.0, max_dim / max(w, h))
                qimg = _api.QtGuiImage(int(w * scale) or 1, int(h * scale) or 1,
                                  _api.QtGuiImage.Format.Format_ARGB32)
                qimg.fill(0)
                p = _api.QPainter(qimg)
                renderer.render(p)
                p.end()
                return _api.QPixmap.fromImage(qimg)
        except Exception:
            pass
        return _api.QPixmap()
    # Сначала пробуем штатный загрузчик Qt.
    pix = _api.QPixmap(path)
    if not pix.isNull():
        return pix
    # Qt не открыл (нет плагина — частый случай для avif/heic): пробуем через
    # Pillow (avif/heic регистрируются pillow-heif) и переводим в QPixmap.
    if _api.Image:
        try:
            with _api.Image.open(path) as im:
                if _api.ImageOps:
                    im = _api.ImageOps.exif_transpose(im)
                im = im.convert("RGBA")
                bio = _api.io.BytesIO(); im.save(bio, format="PNG")
                p2 = _api.QPixmap()
                if p2.loadFromData(_api.QByteArray(bio.getvalue())):
                    return p2
        except Exception:
            pass
    # Последний резерв — bundled ffmpeg. Критично для сравнения «исходник/
    # результат»: результат у нас обычно AVIF, а в собранном .exe ни Qt, ни
    # Pillow могут не уметь его декодировать (нет плагина/кодека). ffmpeg с
    # libaom в комплекте точно открывает AVIF/HEIC (он же их и создаёт), поэтому
    # рендерим один кадр в PNG и грузим его — иначе панель «Результат» пустая.
    try:
        tmp = _api.os.path.join(_api.TEMP_DIR, f"ym_pix_{_api.uuid.uuid4().hex}.png")
        cmd = [_api.FFMPEG, "-y", "-i", path, "-frames:v", "1"]
        if max_dim:
            cmd += ["-vf", f"scale='min({int(max_dim)},iw)':-1"]
        cmd.append(tmp)
        _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                       creationflags=_api.CREATE_NO_WINDOW, timeout=20)
        if _api.os.path.exists(tmp):
            p3 = _api.QPixmap(tmp)
            try: _api.os.remove(tmp)
            except Exception: pass
            if not p3.isNull():
                return p3
    except Exception:
        pass
    return pix

load_pixmap_any.__module__ = _api.__name__
_api.load_pixmap_any = load_pixmap_any
