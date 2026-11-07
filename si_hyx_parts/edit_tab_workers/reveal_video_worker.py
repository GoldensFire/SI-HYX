# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""RevealVideoWorker. Public namespace: edit_tab_workers."""
import reveal_pipe
from ffmpeg_faststart import with_faststart

import edit_tab_workers as _api


class RevealVideoWorker(_api.QThread):
    """Экспорт Монтажа с эффектом раскрытия кадра (кроме пикселизации) —
    ОДНИМ кодированием.

    Декодер (рез, кадрирование, субтитры, накладки) отдаёт кадры по трубе,
    на каждый ложится эффект (frame_reveal_video.VideoReveal), и они сразу
    уходят в кодировщик Монтажа вместе со звуком (reveal_pipe). Сигналы те
    же, что у FfmpegWorker, — обработчики экспорта общие.
    """
    progress = _api.pyqtSignal(float)
    finished = _api.pyqtSignal(bool, str)

    def __init__(self, decode_cmd, encode_cmd, effect, steps, fps,
                 duration=None, still=False, dvd_media="", parent=None):
        super().__init__(parent)
        # Папка картинок/видео для прямоугольника DVD-заставки (frame_reveal_dvd_media).
        self.dvd_media = str(dvd_media or "")
        self.decode_cmd = list(decode_cmd)
        self.encode_cmd = with_faststart(encode_cmd)
        self.effect = effect
        self.steps = int(steps)
        self.fps = float(fps) if fps and fps > 0 else 25.0
        self.duration = float(duration or 0.0)
        self.still = bool(still)
        self._stopped = False
        self._procs = []

    def stop(self):
        """Отмена: гасит оба процесса ffmpeg этого экспорта."""
        self._stopped = True
        for p in list(self._procs):
            try:
                if p is not None and p.poll() is None:
                    p.kill()
            except Exception:
                pass

    def _popen(self, cmd, **kw):
        if _api.os.name == 'nt':
            kw['creationflags'] = _api.CREATE_NO_WINDOW
        p = _api.subprocess.Popen(cmd, **kw)
        self._procs.append(p)
        return p

    def run(self):
        try:
            self._encode()
        except Exception as e:
            self.finished.emit(False, "Отменено" if self._stopped else str(e))
            return
        finally:
            for p in self._procs:
                try:
                    if p.poll() is None:
                        p.kill()
                        p.wait(timeout=5)
                except Exception:
                    pass
            self._procs = []
        self.finished.emit(True, "Код: 0")

    def _encode(self):
        from frame_reveal_video import VideoReveal
        total = max(1, round(self.duration * self.fps))
        reveal = VideoReveal(self.effect, self.steps, total, self.fps, still=self.still,
                             dvd_media=self.dvd_media,
                             ffmpeg=_api.FFMPEG, ffprobe=_api.FFPROBE)
        result = {}
        # stderr декодера — во временный файл: недочитанная труба вешает ffmpeg.
        with _api.tempfile.TemporaryFile() as dec_err:
            dec = self._popen(self.decode_cmd, stdout=_api.subprocess.PIPE,
                              stderr=dec_err, stdin=_api.subprocess.DEVNULL)
            enc = self._popen(self.encode_cmd, stdin=_api.subprocess.PIPE,
                              stdout=_api.subprocess.DEVNULL,
                              stderr=_api.subprocess.PIPE, text=True,
                              encoding="utf-8", errors="replace")

            def feed():
                try:
                    result['frames'] = reveal_pipe.pump(
                        dec.stdout, enc.stdin.buffer, reveal, lambda: self._stopped)
                except (BrokenPipeError, OSError, ValueError):
                    pass                   # кодировщик закрылся — причину скажет он
                except Exception as e:  # noqa: BLE001 — ошибка эффекта в сообщение
                    result['error'] = str(e)
                    self.stop()
                finally:
                    reveal.close()

            pump = _api.threading.Thread(target=feed, daemon=True)
            pump.start()
            tail = []
            for line in enc.stderr:
                if self._stopped:
                    break
                if 'time=' not in line:
                    if line.strip():
                        tail.append(line.rstrip())
                        del tail[:-12]
                    continue
                try:
                    tsec = _api.time_to_s(line[line.index('time=') + 5:].split()[0])
                except Exception:
                    continue
                if self.duration > 0:
                    self.progress.emit(min(99.0, 100.0 * tsec / self.duration))
            rc = enc.wait()
            pump.join()
            try:
                dec.wait(timeout=30)
            except Exception:
                pass
            if self._stopped and not result.get('error'):
                raise RuntimeError("Отменено")
            if result.get('error'):
                raise RuntimeError(f"Эффект не наложился: {result['error']}")
            if not result.get('frames'):
                dec_err.seek(0)
                text = dec_err.read().decode("utf-8", "replace").strip()
                raise RuntimeError("Нет кадров: " + ("\n".join(text.splitlines()[-12:])
                                                     or "декодер ничего не отдал"))
            if rc != 0:
                raise RuntimeError(f"Код: {rc}\n" + "\n".join(tail))
        self.progress.emit(100.0)

RevealVideoWorker.__module__ = _api.__name__
_api.RevealVideoWorker = RevealVideoWorker
