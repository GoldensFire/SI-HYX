# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""VideoInpaintWorker. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class VideoInpaintWorker(_api.QThread):
    """Покадровое удаление объекта (водяной знак/эмодзи и т.п.) с ВИДЕО в отдельном
    потоке, чтобы интерфейс не зависал.

    Принципиально НЕ содержит собственной реализации инпейнтинга: для каждого кадра
    вызывается ТОТ ЖЕ движок LaMa (inpainter.inpaint), что и при удалении объекта с
    одиночного изображения в фоторедакторе. Пайплайн целиком на FFmpeg + LaMa:

      1) FFmpeg разбивает видео на PNG-кадры (полное разрешение, дисплейная
         ориентация — autorotate по умолчанию, без потерь);
      2) каждый кадр прогоняется через inpainter.inpaint(frame, mask) — функция
         сама обрабатывает только ROI вокруг маски (см. lama_inpaint.py), поэтому
         для небольшого знака весь кадр через сеть НЕ гоняется и это быстро;
      3) FFmpeg собирает кадры обратно, сохраняя исходные FPS, разрешение,
         ориентацию и аудиодорожку оригинала.

    Маска ОДНА на всё видео (закрашивается на одном кадре в диалоге) — рассчитано
    на статичные объекты, что и нужно для водяных знаков/логотипов/эмодзи.

    Отмена (cancel) прерывает на любом этапе; временная папка удаляется ВСЕГДА —
    и при успехе, и при ошибке, и при отмене.
    """
    progress = _api.pyqtSignal(int, str)      # (процент 0..100; -1 = «busy», текст фазы)
    done = _api.pyqtSignal(str)               # путь готового файла
    failed = _api.pyqtSignal(str)             # текст ошибки ("Отменено" при отмене)

    def __init__(self, inpainter, src, mask, fps, out_path, venc, has_audio):
        super().__init__()
        self._inp = inpainter
        # Абсолютный путь: ffmpeg для разных этапов вызывается в разное время, и
        # относительный путь ненадёжен (рабочий каталог процесса мог измениться).
        self._src = _api.os.path.abspath(str(src))
        self._mask = mask                # numpy (H,W) uint8 {0,255}
        self._fps = float(fps) if fps and fps > 0 else 25.0
        self._out = str(out_path)
        self._venc = list(venc)          # аргументы видеокодировщика (как у «Обрезать»)
        self._has_audio = bool(has_audio)
        self._cancel = False
        self._proc = None                # текущий subprocess ffmpeg (для отмены)
        self._tmp = None

    def cancel(self):
        """Просит прервать обработку (потокобезопасно по флагу) и убивает текущий
        ffmpeg, если он запущен, чтобы отмена была мгновенной."""
        self._cancel = True
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    # Алиас для единообразной остановки в EditTab.shutdown (как у остальных воркеров).
    def stop(self):
        self.cancel()

    def _run_ffmpeg(self, cmd):
        """Запускает ffmpeg и ждёт завершения, периодически проверяя отмену.
        Возвращает returncode (или -1, если прервали по cancel)."""
        kw = {}
        if _api.os.name == 'nt':
            kw['creationflags'] = _api.CREATE_NO_WINDOW
        self._proc = _api.subprocess.Popen(cmd, stdout=_api.subprocess.DEVNULL,
                                      stderr=_api.subprocess.DEVNULL, **kw)
        try:
            while True:
                try:
                    return self._proc.wait(timeout=0.2)
                except _api.subprocess.TimeoutExpired:
                    if self._cancel:
                        try:
                            self._proc.terminate()
                        except Exception:
                            pass
                        try:
                            self._proc.wait(timeout=5)
                        except Exception:
                            pass
                        return -1
        finally:
            self._proc = None

    def run(self):
        # Загрузчик/сохранятель кадров — те же, что использует фоторедактор
        # (Unicode-безопасные обёртки над OpenCV). Импорт ленивый: тяжёлые
        # зависимости подтягиваются только при реальном запуске обработки.
        from lama_inpaint import load_bgr, save_bgr
        import shutil
        try:
            self._tmp = _api.tempfile.mkdtemp(prefix="sihyx_vinp_")
            frames_dir = _api.os.path.join(self._tmp, "frames")
            _api.os.makedirs(frames_dir, exist_ok=True)
            patt = _api.os.path.join(frames_dir, "%08d.png")

            # 1) Разбор видео на кадры (полное разрешение, дисплейная ориентация).
            self.progress.emit(-1, "Разбор видео на кадры…")
            if self._run_ffmpeg([_api.FFMPEG, "-y", "-i", self._src, patt]) != 0 or self._cancel:
                raise RuntimeError("Отменено" if self._cancel
                                   else "Не удалось извлечь кадры из видео")

            frames = sorted(f for f in _api.os.listdir(frames_dir) if f.endswith(".png"))
            total = len(frames)
            if total == 0:
                raise RuntimeError("В видео не найдено кадров")

            # 2) Прогрев модели ДО цикла (её загрузка длится ~10–25 c) — чтобы
            #    прогресс по кадрам шёл ровно, а не «застрял» на первом кадре.
            self.progress.emit(-1, "Загрузка модели LaMa…")
            try:
                self._inp.warmup()
            except Exception:
                pass
            if self._cancel:
                raise RuntimeError("Отменено")

            # 3) Покадровый инпейнт ТЕМ ЖЕ движком, что и для фото. Маска одна на
            #    всё видео; inpaint сам работает только по ROI вокруг неё.
            for i, name in enumerate(frames):
                if self._cancel:
                    raise RuntimeError("Отменено")
                fp = _api.os.path.join(frames_dir, name)
                res = self._inp.inpaint(load_bgr(fp), self._mask)
                save_bgr(fp, res)        # перезаписываем кадр результатом (экономит диск)
                pct = 5 + int(88 * (i + 1) / total)
                self.progress.emit(pct, f"Удаление объекта… кадр {i + 1}/{total}")

            if self._cancel:
                raise RuntimeError("Отменено")

            # 4) Сборка обратно: исходные FPS + аудиодорожка из оригинала.
            self.progress.emit(95, "Сборка видео…")
            out_tmp = _api.os.path.join(self._tmp, "out" + _api.os.path.splitext(self._out)[1])

            def _assemble(copy_audio):
                cmd = [_api.FFMPEG, "-y", "-framerate", f"{self._fps:.6f}", "-i", patt]
                if self._has_audio:
                    # Аудио берём из оригинала; copy — без потерь; при несовместимости
                    # контейнера/кодека (редко) ниже откатываемся на перекодировку в AAC.
                    cmd += ["-i", self._src, "-map", "0:v:0", "-map", "1:a?"]
                    cmd += (["-c:a", "copy"] if copy_audio
                            else ["-c:a", "aac", "-b:a", "192k"])
                else:
                    cmd += ["-map", "0:v:0"]
                cmd += self._venc + ["-pix_fmt", "yuv420p",
                                     "-movflags", "+faststart", "-shortest", out_tmp]
                return self._run_ffmpeg(cmd)

            rc = _assemble(copy_audio=True)
            if rc != 0 and not self._cancel and self._has_audio:
                # Аудио не скопировалось (несовместимый кодек для контейнера) —
                # пробуем ещё раз, перекодировав звук в AAC. Дорожка сохраняется.
                rc = _assemble(copy_audio=False)
            if rc != 0 or self._cancel:
                raise RuntimeError("Отменено" if self._cancel
                                   else "Не удалось собрать видео")

            # Переносим результат во финальное имя (терпимо к занятому файлу — как
            # обычная обрезка; см. EditTab._replace_tolerant). Ленивый импорт: этот
            # воркер живёт в edit_tab_workers, а EditTab — в edit_tab; импорт внутри
            # метода (а не на уровне модуля) разрывает цикл parts↔tab и безопасен —
            # к моменту вызова edit_tab уже полностью загружен.
            from edit_tab import EditTab
            final = EditTab._replace_tolerant(out_tmp, self._out)
            self.done.emit(final)
        except Exception as e:
            msg = str(e)
            if self._cancel or msg == "Отменено":
                self.failed.emit("Отменено")
            else:
                self.failed.emit(msg)
        finally:
            # Уборка временных файлов — безусловная.
            try:
                if self._tmp and _api.os.path.isdir(self._tmp):
                    shutil.rmtree(self._tmp, ignore_errors=True)
            except Exception:
                pass

VideoInpaintWorker.__module__ = _api.__name__
_api.VideoInpaintWorker = VideoInpaintWorker

def overlay_top_left(box, ovl_w, ovl_h, anchor="center", off_x=0, off_y=0):
    """Левый верхний угол накладки относительно отслеженной рамки box=[x,y,w,h].

    anchor: center — по центру области, top/bottom — над/под ней, left/right —
    слева/справа. off_x/off_y — дополнительный сдвиг в пикселях кадра."""
    bx, by, bw, bh = (float(v) for v in box)
    cx, cy = bx + bw / 2.0, by + bh / 2.0
    if anchor == "top":
        x, y = cx - ovl_w / 2.0, by - ovl_h
    elif anchor == "bottom":
        x, y = cx - ovl_w / 2.0, by + bh
    elif anchor == "left":
        x, y = bx - ovl_w, cy - ovl_h / 2.0
    elif anchor == "right":
        x, y = bx + bw, cy - ovl_h / 2.0
    else:                                    # center
        x, y = cx - ovl_w / 2.0, cy - ovl_h / 2.0
    return x + float(off_x), y + float(off_y)

overlay_top_left.__module__ = _api.__name__
_api.overlay_top_left = overlay_top_left

def blend_bgra(frame_bgr, ovl_bgra, x, y):
    """Накладывает BGRA-картинку на BGR-кадр по альфе, ПРЯМО в кадр (in-place).
    Часть накладки за границей кадра просто обрезается."""
    import numpy as np
    fh, fw = frame_bgr.shape[:2]
    oh, ow = ovl_bgra.shape[:2]
    x, y = int(round(x)), int(round(y))
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x + ow), min(fh, y + oh)
    if x1 <= x0 or y1 <= y0:
        return frame_bgr
    src = ovl_bgra[y0 - y:y1 - y, x0 - x:x1 - x]
    a = src[:, :, 3:4].astype(np.float32) / 255.0
    roi = frame_bgr[y0:y1, x0:x1]
    roi[:] = np.clip(src[:, :, :3].astype(np.float32) * a
                     + roi.astype(np.float32) * (1.0 - a) + 0.5, 0, 255).astype(np.uint8)
    return frame_bgr

blend_bgra.__module__ = _api.__name__
_api.blend_bgra = blend_bgra

def track_box_at(boxes, t, start_s, fps):
    """Рамка из посчитанной траектории на момент времени t (секунды).

    Единая точка правды для предпросмотра (VideoCanvas) и рендера
    (TrackOverlayWorker) — иначе накладка в готовом файле съезжает относительно
    того, что человек видел в плеере."""
    if not boxes:
        return None
    i = int(round((float(t) - float(start_s)) * float(fps)))
    return list(boxes[max(0, min(len(boxes) - 1, i))])

track_box_at.__module__ = _api.__name__
_api.track_box_at = track_box_at
