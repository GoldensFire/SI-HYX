# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AssExtractor. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class AssExtractor(_api.QThread):
    """Извлекает выбранную дорожку субтитров в .ass (для рендера через libass) —
    в фоне. Эмитит (token, путь_к_ass|None)."""
    done = _api.pyqtSignal(int, object)   # (token, ass_path|None)

    def __init__(self, src, sub_index, token):
        super().__init__()
        self.src = str(src)
        self.sub_index = int(sub_index)
        self.token = int(token)

    def run(self):
        out = None
        try:
            tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
            out = tf.name; tf.close()
            cmd = [_api.FFMPEG, "-y", "-i", self.src,
                   "-map", f"0:s:{self.sub_index}", "-c:s", "ass", out]
            kw = {}
            if _api.os.name == 'nt':
                kw['creationflags'] = _api.CREATE_NO_WINDOW
            _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                           stderr=_api.subprocess.DEVNULL, timeout=120, **kw)
            if not (_api.os.path.exists(out) and _api.os.path.getsize(out) > 0):
                try: _api.os.remove(out)
                except Exception: pass
                out = None
        except Exception:
            if out:
                try: _api.os.remove(out)
                except Exception: pass
            out = None
        self.done.emit(self.token, out)

AssExtractor.__module__ = _api.__name__
_api.AssExtractor = AssExtractor

class _SeekThumbnailer(_api.QThread):
    """Фоновый извлекатель кадров для превью полосы воспроизведения. Держит одну
    «целевую» позицию; пока идёт извлечение, новые запросы лишь обновляют цель
    (промежуточные отбрасываются — на быстром движении мыши не копится очередь)."""
    ready = _api.pyqtSignal(float, object)   # quantized_sec, QImage

    def __init__(self):
        super().__init__()
        self._src = None
        self._pending = None
        self._stop = False
        self._cond = _api.threading.Condition()

    def set_source(self, src):
        with self._cond:
            self._src = str(src) if src else None
            self._pending = None

    def request(self, sec):
        with self._cond:
            self._pending = float(sec)
            self._cond.notify()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify()

    def run(self):
        while True:
            with self._cond:
                while self._pending is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                sec = self._pending; src = self._src
                self._pending = None
            if src is None:
                continue
            img = self._extract(src, sec)
            if img is not None and not img.isNull():
                self.ready.emit(sec, img)

    @staticmethod
    def _extract(src, sec):
        try:
            # Скорость превью важнее точности кадра, поэтому жертвуем качеством:
            #   -noaccurate_seek — прыжок СРАЗУ на ближайший ключевой кадр, без
            #     декодирования от него до точной позиции (главный источник
            #     задержки при наведении);
            #   -probesize/-analyzeduration — короткий анализ входа (не сканируем
            #     весь файл ради одного кадра);
            #   scale=160 + -q:v 8 — мелкий кадр пониженного качества кодируется и
            #     передаётся через pipe быстрее.
            cmd = [_api.FFMPEG, "-nostdin",
                   "-probesize", "2M", "-analyzeduration", "0",
                   "-noaccurate_seek", "-ss", f"{max(0.0, sec):.3f}",
                   "-i", str(src), "-frames:v", "1", "-an", "-sn",
                   "-vf", "scale=160:-2", "-q:v", "8", "-threads", "1",
                   "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
            pr = _api.subprocess.run(cmd, capture_output=True,
                                creationflags=_api.CREATE_NO_WINDOW, timeout=8)
            if pr.returncode == 0 and pr.stdout:
                im = _api.QImage.fromData(pr.stdout, "JPG")
                return im
        except Exception:
            pass
        return None

_SeekThumbnailer.__module__ = _api.__name__
_api._SeekThumbnailer = _SeekThumbnailer
