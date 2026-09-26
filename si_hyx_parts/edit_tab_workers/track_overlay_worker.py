# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TrackOverlayWorker. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class TrackOverlayWorker(_api.QThread):
    """Привязка текста/картинки к движущемуся объекту.

    Пользователь обводит объект рамкой на одном кадре (диалог _TrackAttachDialog),
    а этот воркер:
      1) гонит видео через ffmpeg сырыми кадрами (rawvideo bgr24) — без записи
         PNG на диск, в отличие от VideoInpaintWorker: кадров тут столько же, но
         менять их надо целиком и по одному разу;
      2) на каждом кадре внутри выбранного отрезка спрашивает у трекера DyHiT
         (dyhit_tracker.py, ONNX; запасной вариант — CSRT из OpenCV), где теперь
         объект, и подмешивает накладку по альфе рядом с рамкой;
      3) тут же отдаёт кадр второму ffmpeg, который кодирует результат и
         подмешивает исходную аудиодорожку.

    Оба ffmpeg живут одновременно (декодер → python → кодировщик), поэтому
    промежуточных файлов нет вообще. stderr обоих уходит в DEVNULL: читать его
    некому, а неопустошённый pipe на Windows вешает процесс (см. ProxyWorker).
    """
    progress = _api.pyqtSignal(int, str)      # (процент 0..100; -1 = «busy», текст фазы)
    done = _api.pyqtSignal(str)               # путь готового файла
    failed = _api.pyqtSignal(str)             # текст ошибки ("Отменено" при отмене)

    def __init__(self, src, out_path, venc, has_audio, fps, size, duration,
                 init_box, start_s, end_s, overlay_bgra, anchor="center",
                 off_x=0, off_y=0, scale_with_box=False, smooth=0.35,
                 prefer="auto", boxes=None, trim_in=None, trim_out=None,
                 static_overlays=None):
        super().__init__()
        self._src = _api.os.path.abspath(str(src))
        self._out = str(out_path)
        self._venc = list(venc)
        self._has_audio = bool(has_audio)
        self._fps = float(fps) if fps and fps > 0 else 25.0
        self._w, self._h = int(size[0]), int(size[1])
        self._duration = float(duration or 0.0)
        self._box0 = [float(v) for v in init_box]
        self._start = max(0.0, float(start_s))
        self._end = float(end_s) if end_s and end_s > 0 else float('inf')
        self._ovl = overlay_bgra
        self._anchor = anchor
        self._off = (int(off_x), int(off_y))
        self._scale_with_box = bool(scale_with_box)
        self._smooth = float(smooth)
        self._prefer = prefer
        # Готовая траектория из TrackPathWorker: с ней рендер ровно повторяет то,
        # что человек видел в предпросмотре, и не тратит время на отслеживание
        # второй раз. None — считаем путь на ходу (старый одношаговый режим).
        self._boxes = list(boxes) if boxes else None
        # Выделенный в Монтаже отрезок: «Обрезать» с активной накладкой должна и
        # резать, и вшивать. None — берём файл целиком.
        self._trim_in = max(0.0, float(trim_in)) if trim_in else 0.0
        self._trim_out = (float(trim_out) if trim_out and trim_out > 0
                          else float('inf'))
        # Неподвижные накладки Монтажа (логотип/водяной знак): [(BGRA, x, y)] в
        # пикселях кадра. Обычный экспорт вшивает их фильтром overlay=…, но этот
        # путь собирает кадры сам — подмешиваем их тем же blend_bgra.
        self._static = list(static_overlays or [])
        self._cancel = False
        self._procs = []
        self._tmp = None

    def cancel(self):
        """Просит прервать обработку и мгновенно валит оба ffmpeg."""
        self._cancel = True
        for p in list(self._procs):
            try:
                if p is not None and p.poll() is None:
                    p.terminate()
            except Exception:
                pass

    # Единообразная остановка в EditTab.shutdown (как у остальных воркеров).
    def stop(self):
        self.cancel()

    def _popen(self, cmd, **kw):
        if _api.os.name == 'nt':
            kw['creationflags'] = _api.CREATE_NO_WINDOW
        p = _api.subprocess.Popen(cmd, **kw)
        self._procs.append(p)
        return p

    def _scaled_overlay(self, cache, scale):
        """Накладка, масштабированная под текущий размер рамки. Масштаб округляем
        до 2% — иначе cv2.resize дёргается на каждом кадре без видимой разницы."""
        import cv2
        q = max(0.25, min(4.0, round(float(scale) / 0.02) * 0.02))
        got = cache.get(q)
        if got is not None:
            return got
        oh, ow = self._ovl.shape[:2]
        nw, nh = max(1, int(round(ow * q))), max(1, int(round(oh * q)))
        interp = cv2.INTER_AREA if q < 1.0 else cv2.INTER_LINEAR
        img = self._ovl if q == 1.0 else cv2.resize(self._ovl, (nw, nh),
                                                    interpolation=interp)
        if len(cache) > 64:
            cache.clear()
        cache[q] = img
        return img

    def run(self):
        import numpy as np
        tracker = None
        if self._boxes is None:
            try:
                from dyhit_tracker import create_tracker
            except Exception as e:                   # pragma: no cover
                self.failed.emit(f"Отслеживание недоступно: {e}")
                return

        frame_bytes = self._w * self._h * 3
        span_total = (min(self._duration, self._trim_out) - self._trim_in
                      if self._duration > 0 else 0.0)
        total = int(span_total * self._fps) if span_total > 0 else 0
        base_area = max(1.0, self._box0[2] * self._box0[3])
        cache = {}
        dec = enc = None
        try:
            if self._boxes is None:
                self.progress.emit(-1, "Подготовка трекера…")
                tracker = create_tracker(prefer=self._prefer,
                                         smooth=self._smooth, fps=self._fps)
                tracker.warmup()
            else:
                self.progress.emit(-1, "Подготовка…")
            if self._cancel:
                raise RuntimeError("Отменено")

            out_tmp = _api.os.path.join(_api.tempfile.gettempdir(),
                                   f"sihyx_track_{_api.os.getpid()}_{id(self)}"
                                   + _api.os.path.splitext(self._out)[1])
            self._tmp = out_tmp

            # Обрезка: перемотка ДО -i (быстро) + длительность отрезка. Время
            # кадра дальше считаем от trim_in, поэтому накладка встаёт на те же
            # кадры, что и в предпросмотре.
            trim_args = []
            if self._trim_in > 0.001:
                trim_args += ["-ss", f"{self._trim_in:.6f}"]
            span = (self._trim_out - self._trim_in
                    if self._trim_out != float('inf') else 0.0)
            dur_args = ["-t", f"{span:.6f}"] if span > 0.001 else []
            dec_cmd = ([_api.FFMPEG, "-hide_banner", "-nostdin"] + trim_args
                       + ["-i", self._src] + dur_args
                       + ["-an", "-sn", "-dn", "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "-"])
            enc_cmd = [_api.FFMPEG, "-hide_banner", "-nostdin", "-y",
                       "-f", "rawvideo", "-pixel_format", "bgr24",
                       "-video_size", f"{self._w}x{self._h}",
                       "-framerate", f"{self._fps:.6f}", "-i", "-"]
            if self._w % 2 or self._h % 2:
                # yuv420p требует чётных сторон — редкие нечётные размеры
                # (кадрированные исходники) иначе роняют кодировщик.
                enc_cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
            if self._has_audio:
                enc_cmd += (trim_args + ["-i", self._src] + dur_args
                            + ["-map", "0:v:0", "-map", "1:a:0?",
                               "-c:a", "aac", "-b:a", "192k"])
            else:
                enc_cmd += ["-map", "0:v:0"]
            enc_cmd += self._venc + ["-pix_fmt", "yuv420p",
                                     "-movflags", "+faststart", "-shortest", out_tmp]

            dec = self._popen(dec_cmd, stdout=_api.subprocess.PIPE,
                              stderr=_api.subprocess.DEVNULL)
            enc = self._popen(enc_cmd, stdin=_api.subprocess.PIPE,
                              stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL)

            buf = bytearray(frame_bytes)
            view = memoryview(buf)
            idx = 0
            started = False
            phase = ("Наложение на кадры…" if self._boxes is not None
                     else "Отслеживание объекта…")
            self.progress.emit(0, phase)
            while True:
                if self._cancel:
                    raise RuntimeError("Отменено")
                # readinto по кускам: pipe отдаёт данные порциями, а кадр нам
                # нужен целиком (иначе картинка «поедет» на полкадра).
                got = 0
                while got < frame_bytes:
                    n = dec.stdout.readinto(view[got:])
                    if not n:
                        break
                    got += n
                if got < frame_bytes:
                    break                      # видео кончилось
                frame = np.frombuffer(buf, np.uint8).reshape(self._h, self._w, 3).copy()

                t = self._trim_in + idx / self._fps
                if self._start <= t <= self._end:
                    if self._boxes is not None:
                        box = _api.track_box_at(self._boxes, t, self._start, self._fps)
                        started = True
                    elif not started:
                        tracker.init(frame, self._box0)
                        box = list(self._box0)
                        started = True
                    else:
                        box, _score = tracker.update(frame)
                    if self._scale_with_box:
                        scale = _api.math.sqrt(max(1.0, box[2] * box[3]) / base_area)
                        ovl = self._scaled_overlay(cache, scale)
                    else:
                        ovl = self._ovl
                    x, y = _api.overlay_top_left(box, ovl.shape[1], ovl.shape[0],
                                            self._anchor, *self._off)
                    _api.blend_bgra(frame, ovl, x, y)

                for sovl, sx, sy in self._static:
                    _api.blend_bgra(frame, sovl, sx, sy)

                try:
                    enc.stdin.write(frame.tobytes())
                except (BrokenPipeError, OSError):
                    raise RuntimeError("Кодировщик неожиданно завершился")

                idx += 1
                if total > 0 and idx % 5 == 0:
                    pct = max(0, min(97, int(97 * idx / total)))
                    self.progress.emit(pct, f"{phase} кадр {idx}/{total}")

            if self._cancel:
                # Декодер убит отменой — поток кадров просто оборвался.
                raise RuntimeError("Отменено")
            if idx == 0:
                raise RuntimeError("В видео не найдено кадров")

            self.progress.emit(98, "Сборка видео…")
            try:
                enc.stdin.close()
            except Exception:
                pass
            rc = enc.wait()
            try:
                dec.stdout.close()
                dec.wait(timeout=10)
            except Exception:
                pass
            if self._cancel:
                raise RuntimeError("Отменено")
            if rc != 0:
                raise RuntimeError("Не удалось собрать видео")

            # Ленивый импорт (edit_tab зависит от этого модуля — цикл разрывается
            # тем, что импорт происходит уже во время работы воркера).
            from edit_tab import EditTab
            final = EditTab._replace_tolerant(out_tmp, self._out)
            self._tmp = None
            self.done.emit(final)
        except Exception as e:
            msg = str(e)
            self.failed.emit("Отменено" if (self._cancel or msg == "Отменено") else msg)
        finally:
            for p in (dec, enc):
                try:
                    if p is not None and p.poll() is None:
                        p.terminate()
                        p.wait(timeout=5)
                except Exception:
                    pass
            self._procs = []
            try:
                if self._tmp and _api.os.path.exists(self._tmp):
                    _api.os.remove(self._tmp)
            except Exception:
                pass

TrackOverlayWorker.__module__ = _api.__name__
_api.TrackOverlayWorker = TrackOverlayWorker
