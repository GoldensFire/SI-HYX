# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Миниатюры ленты последних файлов: длительность из лога ffmpeg и рабочий поток. Public namespace: widgets."""
import widgets as _api


def _duration_from_ffmpeg_log(text: str) -> float:
    """Секунды из строки «Duration: 00:03:21.44», которую ffmpeg сам печатает в
    stderr, разбирая входной файл. Раньше этот вывод уходил в DEVNULL, а за той
    же цифрой следом запускался отдельный ffprobe — то есть второй 215-МБ
    процесс на тот же файл. 0.0 — в выводе длительности нет (поток без неё или
    файл не открылся); тогда вызывающий код честно спрашивает ffprobe."""
    m = _api._FFMPEG_DURATION_RE.search(text or "")
    if not m:
        return 0.0
    try:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        return 0.0

_duration_from_ffmpeg_log.__module__ = _api.__name__
_api._duration_from_ffmpeg_log = _duration_from_ffmpeg_log

def _fmt_duration(d: float) -> str:
    """Секунды → «12:34» или «1:02:03» (подпись на карточке ленты)."""
    if not d or d <= 0:
        return ""
    h = int(d // 3600); m = int((d % 3600) // 60); s = int(d % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

_fmt_duration.__module__ = _api.__name__
_api._fmt_duration = _fmt_duration

class _RecentThumbWorker(_api.QRunnable):
    """Готовит миниатюру в фоне (ffmpeg/ffprobe/PIL) и отдаёт БАЙТЫ изображения
    в GUI-поток через сигнал. QPixmap нельзя создавать вне главного потока, поэтому
    из воркера возвращаются именно байты, а пиксмап строится в слоте."""
    def __init__(self, path, signal):
        super().__init__()
        self.path = path
        self.signal = signal

    def run(self):
        data = None
        dur_str = ""
        # Готовое из кэша — и ни одного процесса (см. комментарий у кэша выше).
        try:
            data, dur_str = _api._thumb_cache_read(self.path)
        except Exception:
            data, dur_str = None, ""
        if data:
            try:
                self.signal.emit(data, dur_str)
            except Exception:
                pass
            return
        try:
            ext = _api.os.path.splitext(self.path)[1].lower()
            if ext == '.svg':
                # PIL не умеет SVG — растеризуем вектор через QtSvg (QImage, не
                # QPixmap — допустимо вне GUI-потока) и отдаём байты PNG.
                try:
                    im = _api.rasterize_svg(self.path, max_dim=256)
                    if im is not None:
                        im.thumbnail((96, 72))
                        bio = _api.io.BytesIO()
                        im.convert("RGBA").save(bio, "PNG")
                        data = bio.getvalue()
                except Exception:
                    pass
            elif ext in _api.ALLOWED_IMG and _api.Image:
                try:
                    with _api.Image.open(self.path) as im:
                        im.thumbnail((96, 72))
                        bio = _api.io.BytesIO()
                        im.convert("RGBA").save(bio, "PNG")
                        data = bio.getvalue()
                except Exception:
                    pass
            if data is None:
                tmp = _api.os.path.join(_api.TEMP_DIR, f"rft_{_api.uuid.uuid4().hex}.jpg")
                dur = 0.0
                # Пробуем несколько позиций: 1с → 0с (для коротких клипов)
                for seek in ("00:00:01", "00:00:00"):
                    cmd = [_api.FFMPEG, "-y", "-ss", seek, "-i", self.path,
                           "-vframes", "1", "-vf", "scale=96:-2", "-q:v", "3", tmp]
                    try:
                        # stderr забираем, а не выбрасываем: ffmpeg печатает туда
                        # «Duration:» разбираемого файла, и этой цифры хватает —
                        # отдельный ffprobe ниже остаётся только запасным путём.
                        p = _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                                           stderr=_api.subprocess.PIPE, text=True,
                                           encoding="utf-8", errors="replace",
                                           creationflags=_api.CREATE_NO_WINDOW, timeout=8)
                        if not dur:
                            dur = _api._duration_from_ffmpeg_log(p.stderr)
                    except Exception:
                        pass
                    if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
                        try:
                            with open(tmp, "rb") as f:
                                data = f.read()
                        except Exception:
                            pass
                        try: _api.os.remove(tmp)
                        except Exception: pass
                        if data:
                            break
                    else:
                        try:
                            if _api.os.path.exists(tmp): _api.os.remove(tmp)
                        except Exception: pass
                if dur <= 0:
                    # Запасной путь: ffmpeg длительность не назвал (поток без неё
                    # или файл не открылся) — спрашиваем ffprobe, как раньше.
                    try:
                        probe = _api.subprocess.run(
                            [_api.FFPROBE, "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", self.path],
                            stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=_api.CREATE_NO_WINDOW, timeout=4)
                        dur = float(probe.stdout.strip() or 0)
                    except Exception:
                        pass
                dur_str = _api._fmt_duration(dur)
        except Exception:
            pass
        _api._thumb_cache_write(self.path, data, dur_str)
        _api._thumb_cache_trim()   # раз за запуск и только в этом фоновом потоке
        try:
            self.signal.emit(data, dur_str)
        except Exception:
            pass

_RecentThumbWorker.__module__ = _api.__name__
_api._RecentThumbWorker = _RecentThumbWorker
