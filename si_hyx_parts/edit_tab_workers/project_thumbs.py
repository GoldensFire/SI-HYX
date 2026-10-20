# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProjectThumbWorker — кадры для полосы превью вдоль клипов таймлайна.
Public namespace: edit_tab_workers."""
import hashlib
import shutil

import edit_tab_workers as _api

# Windows: процесс с приоритетом ниже обычного — кадры полосы не мешают
# воспроизведению и перемотке.
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
# Сколько файлов держит дисковый кэш кадров (папка на файл, старые удаляются).
_DISK_CACHE_FILES = 80


class ProjectThumbWorker(_api.QThread):
    """Маленькие кадры клипов для таймлайна (полоса кадров, как в Filmora).

    Очередь заданий разбирается С КОНЦА: последней кадры просит отрисовка
    того, что на экране сейчас, а старые заказы (прокрутили, сменили масштаб)
    подождут. Одно задание — короткий ffmpeg: перемотка к ключевому кадру и
    первый декодированный кадр (-noaccurate_seek), без разбора потока сверх
    заголовков. Дорого тут не декодирование (~0.2 с), а запуск процесса и
    открытие файла — на BDRemux в 10 ГБ ~0.6 с на кадр. Поэтому три процесса
    сразу с низким приоритетом и дисковый кэш: открытый снова файл получает
    полосу сразу. Неудача приходит как ready(ключ, None) — заново такой кадр
    не заказывают."""

    ready = _api.pyqtSignal(str, object)     # ключ, QImage или None
    THREADS = 3
    MAX_QUEUE = 400

    def __init__(self, cache_dir=None):
        super().__init__()
        self._jobs = []                      # (ключ, файл, секунда, высота); новые — в конце
        self._queued = set()
        self._stop = False
        self._cond = _api.threading.Condition()
        self._helpers = []
        self._cache_dir = cache_dir
        self._folders = {}                   # (файл, размер, mtime) → папка кэша

    def request(self, key, src, sec, height):
        with self._cond:
            if key in self._queued:
                return
            self._jobs.append((key, str(src), float(sec), int(height)))
            self._queued.add(key)
            if len(self._jobs) > self.MAX_QUEUE:
                old = self._jobs.pop(0)
                self._queued.discard(old[0])
            self._cond.notify()

    def stop(self):
        with self._cond:
            self._stop = True
            self._jobs = []
            self._queued.clear()
            self._cond.notify_all()

    def run(self):
        self._prune_disk_cache()
        for _ in range(self.THREADS - 1):
            helper = _api.threading.Thread(target=self._loop, daemon=True)
            helper.start()
            self._helpers.append(helper)
        self._loop()
        for helper in self._helpers:
            helper.join(1.0)

    def _loop(self):
        while True:
            with self._cond:
                while not self._jobs and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                key, src, sec, height = self._jobs.pop()
                self._queued.discard(key)
            path = self._disk_path(src, sec, height)
            img = self._load(path)
            if img is None:
                img = self._extract(src, sec, height)
                if img is not None and path:
                    try:
                        img.save(path, "PNG")
                    except Exception:
                        pass
            if self._stop:
                return
            self.ready.emit(key, img)

    # ── Дисковый кэш ─────────────────────────────────────────────────────────
    def _disk_path(self, src, sec, height):
        """Путь кадра в кэше: папка на файл — по пути, размеру и времени
        изменения (заменённый файл получит новые кадры)."""
        if not self._cache_dir:
            return None
        try:
            st = _api.os.stat(src)
        except OSError:
            return None
        ident = (_api.os.path.normcase(_api.os.path.abspath(src)), st.st_size, int(st.st_mtime))
        folder = self._folders.get(ident)
        if folder is None:
            tag = hashlib.sha1("|".join(map(str, ident)).encode("utf-8")).hexdigest()[:16]
            folder = _api.os.path.join(self._cache_dir, tag)
            try:
                _api.os.makedirs(folder, exist_ok=True)
                _api.os.utime(folder)        # свежая — старые вытесняются первыми
            except OSError:
                return None
            self._folders[ident] = folder
        return _api.os.path.join(folder, f"{sec:.3f}_{height}.png")

    @staticmethod
    def _load(path):
        if not path or not _api.os.path.exists(path):
            return None
        img = _api.QImage(path)
        return None if img.isNull() else img

    def _prune_disk_cache(self):
        root = self._cache_dir
        if not root or not _api.os.path.isdir(root):
            return
        try:
            folders = [e for e in _api.os.scandir(root) if e.is_dir()]
            folders.sort(key=lambda e: e.stat().st_mtime, reverse=True)
            for e in folders[_DISK_CACHE_FILES:]:
                shutil.rmtree(e.path, ignore_errors=True)
        except OSError:
            pass

    # ── ffmpeg ───────────────────────────────────────────────────────────────
    @staticmethod
    def _extract(src, sec, height):
        flags = _api.CREATE_NO_WINDOW
        if _api.os.name == 'nt':
            flags |= _BELOW_NORMAL_PRIORITY_CLASS
        tail = ["-ss", f"{max(0.0, sec):.3f}", "-i", src, "-map", "0:v:0?",
                "-frames:v", "1", "-vf", f"scale=-2:{max(8, height)}:flags=area",
                "-f", "image2pipe", "-vcodec", "png", "-"]
        # Сперва без разбора потока сверх заголовков (у MKV/MP4 их хватает);
        # не вышло (MPEG-TS и прочие) — с обычным разбором.
        for probe in (["-probesize", "1000000", "-analyzeduration", "0"], []):
            try:
                r = _api.subprocess.run(
                    [_api.FFMPEG, "-v", "error", "-noaccurate_seek"] + probe + tail,
                    capture_output=True, timeout=20, creationflags=flags)
            except Exception:
                return None
            img = _api.QImage()
            if r.stdout and img.loadFromData(r.stdout, "PNG"):
                return img
        return None


ProjectThumbWorker.__module__ = _api.__name__
