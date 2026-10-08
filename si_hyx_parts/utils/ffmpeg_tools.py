# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ffmpeg: проверка, кодировщики, фильтры накладки и громкость; разбор версии. Public namespace: utils."""
import utils as _api


def parse_version(s):
    """Извлекает кортеж чисел из строки версии/тега для сравнения.
    'v0.2-beta' → (0, 2);  '0.10 BETA' → (0, 10);  '' → (0,)."""
    nums = _api.re.findall(r'\d+', s or '')
    return tuple(int(n) for n in nums) if nums else (0,)

parse_version.__module__ = _api.__name__
_api.parse_version = parse_version


def check_ffmpeg():
    try:
        _api.subprocess.run([_api.FFMPEG, "-version"], stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                       creationflags=_api.CREATE_NO_WINDOW)
        return True
    except Exception:
        return False

check_ffmpeg.__module__ = _api.__name__
_api.check_ffmpeg = check_ffmpeg


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


@_api.functools.lru_cache(maxsize=None)
def detect_ffmpeg_encoders():
    """Определяет доступные кодеки FFmpeg. Результат кешируется — ffmpeg запускается только один раз."""
    try:
        p = _api.subprocess.run([_api.FFMPEG, "-hide_banner", "-encoders"], stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW)
        encs = set()
        for line in (p.stdout or "").splitlines():
            m = _api.re.match(r'^\s*[A-Z\.]+\s+([a-z0-9_\-]+)\s+', line, _api.re.I)
            if m: encs.add(m.group(1).strip().lower())
        return frozenset(encs)  # frozenset совместим с lru_cache (хешируемый)
    except Exception:
        return frozenset()

detect_ffmpeg_encoders.__module__ = _api.__name__
_api.detect_ffmpeg_encoders = detect_ffmpeg_encoders


def require_svt():
    return 'libsvtav1' in _api.detect_ffmpeg_encoders()

require_svt.__module__ = _api.__name__
_api.require_svt = require_svt
