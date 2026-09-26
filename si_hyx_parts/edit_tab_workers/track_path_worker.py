# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TrackPathWorker. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class TrackPathWorker(_api.QThread):
    """Первый (быстрый) этап привязки к объекту: считает ТРАЕКТОРИЮ рамки и
    ничего не кодирует.

    Сделано отдельно от рендера ради предпросмотра «как в Filmora»: сначала за
    несколько секунд получаем путь объекта, показываем накладку прямо в плеере
    Монтажа — и только если человек доволен, запускаем длинный экспорт
    (TrackOverlayWorker, которому траектория уже отдаётся готовой).

    Отслеживаем на УМЕНЬШЕННОМ кадре (длинная сторона до TRACK_MAX_SIDE): сеть
    всё равно режет из кадра окно ×4 вокруг цели и жмёт его до 256², поэтому
    точность практически не страдает, а декодирование и препроцессинг заметно
    дешевле. Рамки возвращаются уже в координатах ИСХОДНОГО кадра."""

    TRACK_MAX_SIDE = 720

    progress = _api.pyqtSignal(int, str)
    done = _api.pyqtSignal(object)            # список рамок [x, y, w, h] в px исходника
    failed = _api.pyqtSignal(str)

    def __init__(self, src, fps, size, init_box, start_s, end_s,
                 smooth=1.0, prefer="auto"):
        super().__init__()
        self._src = _api.os.path.abspath(str(src))
        self._fps = float(fps) if fps and fps > 0 else 25.0
        self._w, self._h = int(size[0]), int(size[1])
        self._box0 = [float(v) for v in init_box]
        self._start = max(0.0, float(start_s))
        self._end = float(end_s) if end_s and end_s > 0 else float('inf')
        self._smooth = float(smooth)
        self._prefer = prefer
        self._cancel = False
        self._procs = []

    def cancel(self):
        self._cancel = True
        for p in list(self._procs):
            try:
                if p is not None and p.poll() is None:
                    p.terminate()
            except Exception:
                pass

    def stop(self):
        self.cancel()

    def _scale(self):
        """Во сколько раз уменьшаем кадр для отслеживания (1.0 — не уменьшаем)."""
        side = max(self._w, self._h)
        if side <= self.TRACK_MAX_SIDE:
            return 1.0, self._w, self._h
        k = self.TRACK_MAX_SIDE / float(side)
        # Чётные стороны: rawvideo-декодирование не любит нечётных размеров у
        # yuv-исходников, а ffmpeg округляет сам — считаем так же, как он.
        w = max(2, int(round(self._w * k / 2)) * 2)
        h = max(2, int(round(self._h * k / 2)) * 2)
        return w / float(self._w), w, h

    def run(self):
        import numpy as np
        try:
            from dyhit_tracker import create_tracker
        except Exception as e:                       # pragma: no cover
            self.failed.emit(f"Отслеживание недоступно: {e}")
            return

        k, tw, th = self._scale()
        frame_bytes = tw * th * 3
        span = (self._end - self._start) if self._end != float('inf') else 0.0
        total = int(span * self._fps) if span > 0 else 0
        dec = None
        try:
            self.progress.emit(-1, "Подготовка трекера…")
            tracker = create_tracker(prefer=self._prefer, smooth=self._smooth,
                                     fps=self._fps)
            tracker.warmup()
            if self._cancel:
                raise RuntimeError("Отменено")

            cmd = [_api.FFMPEG, "-hide_banner", "-nostdin"]
            if self._start > 0.05:
                # Кадры до начала отрезка не нужны вообще — input-seek экономит
                # всё время декодирования «хвоста» перед выбранным моментом.
                cmd += ["-ss", f"{self._start:.6f}"]
            cmd += ["-i", self._src, "-an", "-sn", "-dn"]
            if k < 1.0:
                cmd += ["-vf", f"scale={tw}:{th}"]
            cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
            dec = self._popen(cmd)

            box0 = [v * k for v in self._box0]
            buf = bytearray(frame_bytes)
            view = memoryview(buf)
            boxes = []
            self.progress.emit(0, "Отслеживание объекта…")
            while True:
                if self._cancel:
                    raise RuntimeError("Отменено")
                got = 0
                while got < frame_bytes:
                    n = dec.stdout.readinto(view[got:])
                    if not n:
                        break
                    got += n
                if got < frame_bytes:
                    break
                frame = np.frombuffer(buf, np.uint8).reshape(th, tw, 3).copy()

                if not boxes:
                    tracker.init(frame, box0)
                    box = list(box0)
                else:
                    box, _score = tracker.update(frame)
                boxes.append([v / k for v in box])

                if total > 0 and len(boxes) >= total:
                    break
                if total > 0 and len(boxes) % 5 == 0:
                    pct = max(0, min(99, int(99 * len(boxes) / total)))
                    self.progress.emit(pct, f"Отслеживание объекта… "
                                            f"кадр {len(boxes)}/{total}")

            if self._cancel:
                raise RuntimeError("Отменено")
            if not boxes:
                raise RuntimeError("В видео не найдено кадров")
            self.done.emit(boxes)
        except Exception as e:
            msg = str(e)
            self.failed.emit("Отменено" if (self._cancel or msg == "Отменено")
                             else msg)
        finally:
            for p, close in ((dec, True),):
                try:
                    if p is not None:
                        if close and p.stdout is not None:
                            p.stdout.close()
                        if p.poll() is None:
                            p.terminate()
                        p.wait(timeout=5)
                except Exception:
                    pass

    def _popen(self, cmd):
        kw = {"stdout": _api.subprocess.PIPE, "stderr": _api.subprocess.DEVNULL}
        if _api.os.name == 'nt':
            kw['creationflags'] = _api.CREATE_NO_WINDOW
        p = _api.subprocess.Popen(cmd, **kw)
        self._procs.append(p)
        return p

TrackPathWorker.__module__ = _api.__name__
_api.TrackPathWorker = TrackPathWorker
