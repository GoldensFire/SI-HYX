# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Сведения о медиа: ffprobe, кодеки, fps, битрейт и размер. Public namespace: utils."""
import utils as _api


def human_size(n):
    if not n:
        return "-"
    try:
        n = float(n)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if n < 1024.0:
                return f"{n:.1f}{unit}"
            n /= 1024.0
    except Exception:
        return "-"
    return f"{n * 1024:.1f}TB"  # fallback для экстремально больших значений

human_size.__module__ = _api.__name__
_api.human_size = human_size


def pretty_audio_codec(name):
    """Человекочитаемое имя аудиокодека для колонки «Битрейт» (слева от цифр).
    ffprobe отдаёт codec_name в нижнем регистре (aac/opus/mp3…) — приводим к
    привычным меткам, незнакомые просто капсим."""
    if not name:
        return ""
    n = str(name).strip().lower()
    table = {
        'aac': 'AAC', 'opus': 'Opus', 'libopus': 'Opus', 'mp3': 'MP3',
        'mp2': 'MP2', 'vorbis': 'Vorbis', 'libvorbis': 'Vorbis',
        'flac': 'FLAC', 'alac': 'ALAC', 'ac3': 'AC3', 'eac3': 'E-AC3',
        'dts': 'DTS', 'wmav1': 'WMA', 'wmav2': 'WMA', 'amr_nb': 'AMR',
        'truehd': 'TrueHD',
    }
    if n in table:
        return table[n]
    if n.startswith('pcm'):
        return 'PCM'
    return n.upper()

pretty_audio_codec.__module__ = _api.__name__
_api.pretty_audio_codec = pretty_audio_codec


def fmt_bitrate_with_codec(codec, br):
    """«AAC 153 кбит/с». Кодек слева от цифр; если кодек неизвестен — только битрейт,
    если битрейт неизвестен — только кодек (или «—»)."""
    c = _api.pretty_audio_codec(codec)
    has_br = bool(br) and br not in ("-", "—")
    if c and has_br:
        return f"{c} {br}"
    if has_br:
        return br
    return c or "—"

fmt_bitrate_with_codec.__module__ = _api.__name__
_api.fmt_bitrate_with_codec = fmt_bitrate_with_codec


def get_media_info(path):
    """Возвращает (duration, bitrate_str, size, audio_bitrate_str, audio_codec).
    Один вызов ffprobe с JSON-выводом — поля именованные, порядок не важен.
    """
    dur = 0.0
    size = 0
    br_str = "-"
    a_br = "-"
    a_codec = None
    try:
        size = _api.os.path.getsize(path)
    except Exception:
        size = 0
    try:
        p = _api.subprocess.run(
            [_api.FFPROBE, "-v", "error",
             "-show_entries",
             "format=duration,bit_rate:stream=bit_rate,sample_rate,channels,bits_per_sample,codec_name",
             "-select_streams", "a:0",
             "-of", "json",
             path],
            stdout=_api.subprocess.PIPE, stderr=_api.subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=_api.CREATE_NO_WINDOW,
        )
        data = _api.json.loads(p.stdout or "{}")

        fmt = data.get("format", {})
        try:
            dur = float(fmt.get("duration", 0) or 0)
        except Exception:
            dur = 0.0
        try:
            fmt_br = int(fmt.get("bit_rate", 0) or 0)
            if fmt_br > 0:
                br_str = f"{fmt_br // 1000} кбит/с"
        except Exception:
            pass

        streams = data.get("streams", [])
        if streams:
            s0 = streams[0]
            a_codec = s0.get("codec_name") or None
            try:
                abr = int(s0.get("bit_rate", 0) or 0)
                if abr > 0:
                    a_br = f"{abr // 1000} кбит/с"
                    br_str = a_br
            except Exception:
                pass
            # WAV / PCM / FLAC не хранят bit_rate в stream — вычисляем вручную
            if a_br == "-":
                try:
                    sr   = int(s0.get("sample_rate", 0) or 0)
                    ch   = int(s0.get("channels", 0) or 0)
                    bps  = int(s0.get("bits_per_sample", 0) or 0)
                    if sr > 0 and ch > 0 and bps > 0:
                        calc = sr * ch * bps
                        a_br = f"{calc // 1000} кбит/с"
                        br_str = a_br
                except Exception:
                    pass
            # Нет тега bit_rate (частый случай для opus и ряда mp4) — считаем по
            # сумме размеров аудиопакетов за длительность: точнее format.bit_rate
            # (тот включает видео) и ВСЕГДА даёт значение, а не прочерк.
            if a_br == "-" and dur > 0:
                try:
                    pk = _api.subprocess.run(
                        [_api.FFPROBE, "-v", "error", "-select_streams", "a:0",
                         "-show_entries", "packet=size", "-of", "csv=p=0", path],
                        stdout=_api.subprocess.PIPE, stderr=_api.subprocess.PIPE,
                        text=True, encoding="utf-8", errors="replace",
                        creationflags=_api.CREATE_NO_WINDOW)
                    total = sum(int(x) for x in pk.stdout.replace(",", " ").split() if x.isdigit())
                    if total > 0:
                        kbps = int(round(total * 8 / dur / 1000))
                        if kbps > 0:
                            a_br = f"{kbps} кбит/с"
                            br_str = a_br
                except Exception:
                    pass
            # Последний резерв: format.bit_rate (работает для opus, mp3, m4a…)
            if a_br == "-" and fmt_br > 0:
                a_br = f"{fmt_br // 1000} кбит/с"
                br_str = a_br

    except Exception:
        pass
    try:
        if br_str == "-" and dur and size:
            est = int(size * 8 / dur)
            br_str = f"{est // 1000} кбит/с"
            if a_br == "-":
                a_br = br_str
    except Exception:
        pass
    return dur, br_str, size, a_br, a_codec

get_media_info.__module__ = _api.__name__
_api.get_media_info = get_media_info


def csv_fields(out, sep=","):
    """Непустые поля первой строки CSV-вывода ffprobe (`-of csv=p=0`).

    Сборки ffmpeg 2026 года ставят разделитель И В КОНЦЕ строки: `h264,`,
    `60/1,`, `960x540x`. Наивный разбор на этом ломается молча и по-разному:
    float()/int() кидает исключение (и вызывающий получает 0 или «не смогли»),
    а сравнение с кодеком просто не совпадает — «AV1» перестаёт опознаваться.
    Поэтому любое поле ffprobe достаём отсюда."""
    for line in (out or "").splitlines():
        line = line.strip()
        if not line:
            continue
        return [f.strip() for f in line.split(sep) if f.strip()]
    return []

csv_fields.__module__ = _api.__name__
_api.csv_fields = csv_fields


def csv_first(out, sep=","):
    """Первое непустое поле CSV-вывода ffprobe (см. csv_fields)."""
    fields = _api.csv_fields(out, sep)
    return fields[0] if fields else ""

csv_first.__module__ = _api.__name__
_api.csv_first = csv_first


def get_fps_float(path):
    try:
        cmd = [_api.FFPROBE, "-v", "0", "-of", "csv=p=0", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", path]
        p = _api.subprocess.run(cmd, stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW)
        val = _api.csv_first(p.stdout)
        if '/' in val:
            num, den = val.split('/', 1)
            return float(num) / float(den)
        return float(val)
    except Exception:
        return 0.0

get_fps_float.__module__ = _api.__name__
_api.get_fps_float = get_fps_float


def get_video_codec(path):
    """Кодек видеодорожки файла (None — видеоряда нет).

    Поток выбираем как `V:0`, а не `v:0`: заглавная V отсеивает ОБЛОЖКИ
    (attached_pic). Иначе mp3 с картинкой альбома выглядел как «видеофайл
    mjpeg 1000×1000», и «Обработка» гнала обложку в AV1-кодирование вместо
    аудио-ветки (а имя результата — .mp4 с crf-суффиксом — потом не находилось:
    на диске лежал .opus)."""
    try:
        p = _api.subprocess.run([_api.FFPROBE, "-v", "error", "-select_streams", "V:0", "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", path],
                           stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW)
        return p.stdout.strip().lower() or None
    except Exception:
        return None

get_video_codec.__module__ = _api.__name__
_api.get_video_codec = get_video_codec


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
