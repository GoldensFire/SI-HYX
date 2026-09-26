# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: _sanitize_name. Public namespace: workers."""
import workers as _api


@staticmethod
def _sanitize_name(name: str) -> str:
    """Если имя содержит AI-бренд — заменяет на 6 случайных символов."""
    if any(b in name.lower() for b in _api.ProcessWorker._AI_BRANDS):
        return ''.join(_api.random.choices(_api.ProcessWorker._RAND_CHARS, k=6))
    return name

def stop(self): self.stop_flag = True

def measure_loudness(self, path, start=None, dur=None):
    return _api.measure_loudness(path, should_stop=lambda: self.stop_flag, start=start, dur=dur)

@staticmethod
def _priority_creationflag(priority):
    """Windows priority-class флаг для creationflags по выбору пользователя.
        Низкий = Low (IDLE), Обычный = Normal, Высокий = High — как в Диспетчере задач.
        На не-Windows возвращает 0."""
    if not _api.IS_WIN:
        return 0
    p = (priority or 'normal').lower()
    if p in ('low', 'низкий', 'idle'):
        return getattr(_api.subprocess, 'IDLE_PRIORITY_CLASS', 0)
    if p in ('high', 'высокий'):
        return getattr(_api.subprocess, 'HIGH_PRIORITY_CLASS', 0)
    return getattr(_api.subprocess, 'NORMAL_PRIORITY_CLASS', 0)

def _inc_active(self, weight=1):
    with self._active_lock:
        self._active_count += weight
        n = self._active_count
    self.active_threads.emit(n, max(1, self._max_threads))

def _dec_active(self, weight=1):
    with self._active_lock:
        self._active_count = max(0, self._active_count - weight)
        n = self._active_count
    self.active_threads.emit(n, max(1, self._max_threads))

def _out_dir_for(self, path):
    """Каталог экспорта: выбранная пользователем папка (если задана и
        существует), иначе — рядом с исходным файлом."""
    d = self.settings.get('export_dir') or ''
    if d and _api.os.path.isdir(d):
        return d
    return _api.os.path.dirname(path) or "."

@staticmethod
def _source_has_alpha(path: str) -> bool:
    """True только если в изображении есть пиксели с реальной прозрачностью."""
    ext = _api.os.path.splitext(path)[1].lower()
    if ext in {'.png', '.gif', '.tiff', '.tif', '.webp', '.bmp',
               '.ico', '.avif', '.heic', '.heif'}:
        if _api.Image:
            try:
                with _api.Image.open(path) as im:
                    # Палитра с tRNS — есть прозрачность
                    if im.mode == 'P' and 'transparency' in im.info:
                        return True
                    # LA / RGBa — всегда с альфой
                    if im.mode in ('LA', 'RGBa'):
                        return True
                    # RGBA — проверяем реальные пиксели
                    if im.mode == 'RGBA':
                        r, g, b, a = im.split()
                        return a.getextrema()[0] < 255  # есть хоть один непрозрачный пиксель
                    return False
            except Exception:
                pass
    # Видео — ffprobe
    try:
        p = _api.subprocess.run(
            [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW,
        )
        fmt = p.stdout.strip().lower()
        _NO_ALPHA = {'gray', 'grayf32le', 'grayf32be', 'rgb24', 'bgr24',
                     'rgb48le', 'rgb48be', 'bgr48le', 'bgr48be'}
        return 'a' in fmt and fmt not in _NO_ALPHA
    except Exception:
        return False

@staticmethod
def _bt709_color_args(path: str) -> list:
    """-color_primaries/-color_trc/-colorspace bt709 — тегирует поток BT.709,
        чтобы плееры не гадали и не показывали SDR-видео «вымытым»/пересвеченным
        из-за неизвестного цветового пространства. Не меняет пиксели — только
        метаданные контейнера.

        БЕЗОПАСНО только для обычных SDR-источников: у настоящего HDR (PQ/HLG,
        BT.2020) эти теги были бы НЕВЕРНЫМИ и испортили бы цвет при просмотре —
        поэтому сперва читаем теги исходника через ffprobe и тегируем BT.709
        лишь когда он сам уже BT.709 или вообще без тегов (частый случай для
        обычных SDR-рипов) — то есть только ДОБАВЛЯЕМ то, что и так верно, а не
        переопределяем реально другое цветовое пространство."""
    try:
        p = _api.subprocess.run(
            [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=color_primaries,color_transfer,color_space",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW, timeout=15,
        )
        vals = [v.strip().lower() for v in (p.stdout or "").splitlines()]
    except Exception:
        return []
    _SAFE = {"", "unknown", "unspecified", "n/a", "bt709", "bt470bg", "smpte170m"}
    _HDR_MARKERS = ("bt2020", "smpte2084", "arib-std-b67")
    if any(any(m in v for m in _HDR_MARKERS) for v in vals):
        return []  # настоящий HDR/BT.2020 — не трогаем
    if any(v not in _SAFE for v in vals):
        return []  # что-то нестандартное — на всякий случай не тегируем
    return ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
