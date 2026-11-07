# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ffmpeg: проверка, кодировщики, фильтры накладки и громкость; разбор версии. Public namespace: utils."""
import math

import ffmpeg_env
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
    """Путь как значение опции фильтра — без кавычек (см. ffmpeg_env):
    двухуровневое экранирование выдерживает и `'`, и `:`, и `[`/`]`."""
    return ffmpeg_env.escape_filter_path(p)

escape_filter_path.__module__ = _api.__name__
_api.escape_filter_path = escape_filter_path


def overlay_filter_graph(base_chain, rendered, escape_path=None,
                         pix_fmt="yuv420", pre_chain=""):
    """Собирает -vf для экспорта с наложенными картинками.

    base_chain — уже готовая цепочка видеофильтров одной строкой (кадрирование,
                 субтитры, пикселизация, масштаб/фейды «Обработки»), может быть
                 пустой;
    rendered   — список (png_path, x, y) от ImageOverlay.save_png;
    pix_fmt    — формат работы overlay (см. overlay_chroma_format);
    pre_chain  — цепочка ДО накладок (сведение HDR в SDR — hdr_tonemap:
                 картинка ложится уже на SDR-кадр), может быть пустой.

    Схема графа (без спец-меток вроде [in]/[out], их поддержка у ffmpeg
    исторически плавала): картинки заводятся источниками `movie`, кадр проходит
    через `null` (единственный неподписанный вход графа = вход -vf), дальше
    последовательные overlay, и в конце — базовая цепочка. Накладки идут ПЕРЕД
    базовой цепочкой: их координаты посчитаны в пикселях ИСХОДНОГО кадра, и
    кадрирование/масштаб обязаны применяться уже к кадру с картинкой — ровно
    так, как это видно в плеере Монтажа."""
    if not rendered:
        return ",".join(c for c in (pre_chain, base_chain) if c)
    esc = escape_path or _api.escape_filter_path
    fmt = (pix_fmt or "yuv420").strip()
    parts = []
    for i, (png, _x, _y) in enumerate(rendered):
        parts.append(f"movie={esc(png)},format=rgba[sihyxovl{i}]")
    parts.append(f"{pre_chain or 'null'}[sihyxbase0]")
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


def _loudnorm_json(cmd, should_stop=None):
    """Запускает ffmpeg с `loudnorm=…:print_format=json` и возвращает его
    JSON-сводку (dict, значения строками — как их печатает ffmpeg) или None.
    should_stop — как у measure_loudness: при True ffmpeg убивается."""
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
        if isinstance(data, dict) and 'input_i' in data:
            return data
    return None


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
    тяжёлым кодеком (AV1/HEVC 4K) разрыв кратно больше.

    Меряет тем же способом, что loudnorm_stats (линейный loudnorm с усилением
    0 дБ, -t до -i). Раньше здесь стоял динамический loudnorm и -t после -i:
    динамический режим на конце потока дважды считает последние ~2,9 с, а -t
    после -i пускает в фильтр звук за концом отрезка. Колонки «Было»/«После»
    расходились с ebur128 на коротких клипах до 0,65 LU: после нормализации
    в −20,0 обрезка [5,20) показывала «После −19,34»."""
    try:
        data = _api.loudnorm_stats(path, should_stop=should_stop, start=start, dur=dur)
        if data:
            return float(data.get('input_i'))
    except Exception:
        pass
    return None

measure_loudness.__module__ = _api.__name__
_api.measure_loudness = measure_loudness


# Замер громкости (второй проход и колонки LUFS) — тот же loudnorm, но в
# ЛИНЕЙНОМ режиме с усилением 0 дБ. Динамический режим на конце потока
# повторно подаёт в свой счётчик громкости последние ~2,9 с буфера упреждения
# (flush_frame → filter_frame в af_loudnorm.c), и input_i/input_lra коротких
# отрезков смещаются к громкости их хвоста: на вопросах-песнях 15–25 с до
# ±0,6 LU против ebur128, pyloudnorm и прямого расчёта BS.1770 (на треках в
# минуты — сотые). Линейный режим кадры не копит, замер честный. measured_*
# здесь не замер, а ключ: при measured_I = I и пике ниже любого TP init()
# фильтра выбирает linear с нулевым усилением. aresample до 192 кГц — как в
# динамическом режиме: input_tp остаётся пиком на 192 кГц, то есть истинным.
_LOUDNORM_STATS_AF = ("aresample=192000,loudnorm=I=-24:LRA=50:TP=0:measured_I=-24"
                      ":measured_LRA=1:measured_TP=-99:measured_thresh=-99:linear=true"
                      ":print_format=json")


def loudnorm_stats(path, should_stop=None, start=None, dur=None, stream=None):
    """Замер громкости для второго прохода loudnorm: вся JSON-сводка
    (input_i, input_tp, input_lra, input_thresh, … — строками, как печатает
    ffmpeg) или None. should_stop — как у measure_loudness.

    Меряется ровно то, что пойдёт в кодирование:
      • stream — абсолютный номер дорожки (выбор в Монтаже). Без -map ffmpeg
        берёт свою дорожку по умолчанию: на многодорожечном файле «Было» и
        усиление считались по другой озвучке (Hikaru S01E01: −22,6 LUFS у
        русской #1 против −27,3 у выбранной японской #3);
      • start/dur — отрезок обрезки. -t стоит ДО -i: после -i он стал бы
        atrim'ом за фильтром, и фильтр прочёл бы лишнее за концом отрезка."""
    try:
        ss = ["-ss", f"{start:.3f}"] if start else []
        t = ["-t", f"{dur:.3f}"] if dur else []
        mp = ["-map", f"0:{int(stream)}"] if stream is not None else []
        cmd = ([_api.FFMPEG, "-hide_banner", "-nostats"] + ss + t + ["-i", path] + mp
               + ["-vn", "-sn", "-dn", "-af", _LOUDNORM_STATS_AF, "-f", "null", "-"])
        return _loudnorm_json(cmd, should_stop)
    except Exception:
        return None

loudnorm_stats.__module__ = _api.__name__
_api.loudnorm_stats = loudnorm_stats


# Запас по истинному пику (дБ) при выборе линейного режима: input_tp округлён
# до сотых, а пик после передискретизации под кодек может чуть отличаться.
LOUDNORM_LINEAR_TP_MARGIN = 0.1


def loudnorm_linear_opts(stats, target_i, target_lra, target_tp):
    """Хвост опций loudnorm («:measured_I=…:linear=true») для второго прохода
    по замеру loudnorm_stats — или "", если линейный режим не гарантирован.

    С замером loudnorm применяет постоянное усиление (target_i − measured_I):
    громкость попадает в цель, а динамика источника не трогается. Одиночный
    проход (динамический режим) промахивался на реальных треках до 3 LU и
    сжимал диапазон громкости даже при LRA источника ниже цели. Но linear
    включается только при условиях init() af_loudnorm.c, иначе фильтр молча
    уходит в динамический режим — а тот с переданным замером ведёт себя иначе,
    чем без него (GATE 01, LRA 12,4: LRA итога 8,8 → 14,7 LU). Поэтому при
    любом сомнении "" — и цепочка остаётся прежней:
      • пик после усиления measured_TP + (I − measured_I) не выше TP с запасом
        LOUDNORM_LINEAR_TP_MARGIN, и measured_LRA ≤ LRA;
      • I=0, LRA=0, TP=99, thresh=−70 — значения «замера нет» у самого
        фильтра: так выходят тишина и отрезки короче 0,4 с;
      • −inf/inf и выход за диапазоны опций (I −99..0, LRA 0..99, TP −99..99,
        thresh −99..0): ffmpeg не создаст фильтр, и файл не закодируется вовсе
        (measured_I=-inf → «Result too large»)."""
    if not isinstance(stats, dict):
        return ""
    try:
        mi = float(stats["input_i"])
        mlra = float(stats["input_lra"])
        mtp = float(stats["input_tp"])
        mth = float(stats["input_thresh"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not all(math.isfinite(v) for v in (mi, mlra, mtp, mth)):
        return ""
    if not (-99.0 <= mi <= 0.0 and 0.0 <= mlra <= 99.0
            and -99.0 <= mtp <= 99.0 and -99.0 <= mth <= 0.0):
        return ""
    if mi == 0.0 or mlra == 0.0 or mtp == 99.0 or mth == -70.0:
        return ""
    if mlra > target_lra or mtp + (target_i - mi) > target_tp - LOUDNORM_LINEAR_TP_MARGIN:
        return ""
    return (f":measured_I={mi:.2f}:measured_LRA={mlra:.2f}"
            f":measured_TP={mtp:.2f}:measured_thresh={mth:.2f}:linear=true")

loudnorm_linear_opts.__module__ = _api.__name__
_api.loudnorm_linear_opts = loudnorm_linear_opts


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
