# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_audio_scrub.py — звук покадрового шага «Монтажа»: фоновый декодер
# окна PCM вокруг плейхеда (AudioScrubber).
#
# Отделён от edit_tab_frames.py (кадры) чисто по размеру файла: обе половины
# покадрового слоя независимы — кадры идут в холст, звук в QAudioSink.
# Прежний импорт `from edit_tab_frames import AudioScrubber` продолжает
# работать: edit_tab_frames реэкспортирует класс.

import array
import subprocess
import sys
import threading

from config import (CREATE_NO_WINDOW, FFMPEG, QThread, pyqtSignal)


# ── Звук покадрового шага ────────────────────────────────────────────────────
class AudioScrubber(QThread):
    """Короткий звук покадрового шага — ровно с pts кадра, как в монтажках.

    Почему не отдельным QMediaPlayer, как было раньше. Замерено на живом файле
    щупом QAudioBufferOutput:
      • первый аудиобуфер после его перемотки приходит через 140–160 мс — звук
        отставал от картинки на восьмую долю секунды;
      • перематывается он по границе аудиопакета (у AAC это ~21 мс), а кадр при
        60 fps — 16.7 мс: шаг на ОДИН кадр звук вообще не двигал, звучал тот же
        самый кусок;
      • оборвать его вовремя нечем: за 400 мс «блипа» плеер успевал проиграть
        БОЛЬШЕ СЕКУНДЫ исходника, и следующий шаг начинал звук заметно раньше
        того места, до которого доиграл предыдущий, — то самое «звук уезжает
        вперёд, а потом пятится назад».

    Поэтому звук берём сами: окно PCM вокруг плейхеда декодирует фоновый ffmpeg
    (8 секунд — 80 мс работы, замерено), а шаг играет из него ТОЧНЫЙ срез через
    QAudioSink (звук идёт через 1–9 мс после записи в устройство). Точность
    среза даёт input `-ss`: для PCM он сэмпл-точен — проверено побайтовым
    сравнением перекрывающихся окон.
    """

    ready = pyqtSignal()             # окно PCM готово (можно играть)

    WINDOW_S = 8.0                   # длина окна PCM
    LEAD_S = 2.5                     # сколько окна лежит ДО плейхеда
    MARGIN_S = 0.75                  # ближе этого к краю окна — пора перекачивать
    MAX_FAILS = 2                    # столько пустых декодов = «звука нет»

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cond = threading.Condition()
        self._lock = threading.Lock()
        self._src = None
        self._stream = "a:0"         # -map 0:<это>: «a:0» или абсолютный индекс
        self._rate = 48000
        self._channels = 2
        self._sample_bytes = 2
        self._fmt = "s16le"
        self._want = None            # заказанное начало окна (с)
        self._busy = None            # окно, которое декодируется прямо сейчас
        self._win = None             # (начало_с, PCM-байты)
        self._fails = 0              # подряд неудачных декодов (нет дорожки?)
        self._stop = False
        self._proc = None

    # ── публичный API (главный поток) ────────────────────────────────────────
    def configure(self, rate, channels, sample_bytes):
        """Формат PCM. Обязан совпадать с форматом QAudioSink — иначе звук
        поедет по скорости и тону."""
        with self._cond:
            self._rate = max(8000, int(rate or 48000))
            self._channels = max(1, int(channels or 2))
            self._sample_bytes = 4 if int(sample_bytes or 2) == 4 else 2
            self._fmt = "f32le" if self._sample_bytes == 4 else "s16le"
        with self._lock:
            self._win = None

    def set_source(self, path, stream="a:0"):
        with self._lock:
            self._win = None
        with self._cond:
            self._src = str(path) if path else None
            self._stream = str(stream or "a:0")
            self._want = None
            self._busy = None
            self._fails = 0
        self._kill_proc()

    def source(self):
        with self._cond:
            return (self._src, self._stream)

    def frame_bytes(self):
        return self._sample_bytes * self._channels

    def request(self, t_s):
        """Заказать окно PCM вокруг t_s, если текущего не хватает."""
        t_s = max(0.0, float(t_s or 0.0))
        with self._lock:
            win = self._win
        if win is not None:
            start, buf = win
            end = start + len(buf) / float(self.frame_bytes() * self._rate)
            if (t_s >= start or start <= 0.0) and t_s <= end - self.MARGIN_S:
                return
        want = max(0.0, t_s - self.LEAD_S)
        with self._cond:
            if self._src is None or self._fails >= self.MAX_FAILS:
                return           # у файла просто нет звука — не гоняем ffmpeg
            if self._busy is not None and abs(self._busy - want) < 0.05:
                return           # ровно это окно уже декодируется
            self._want = want
            self._cond.notify()

    def slice_at(self, t_s, dur_s, fade_s=0.003):
        """PCM-срез [t_s, t_s+dur_s) из готового окна (None — окна ещё нет).
        Края приглушены: без этого на стыке срезов слышен щелчок."""
        with self._lock:
            win = self._win
        if win is None:
            return None
        start, buf = win
        fb = self.frame_bytes()
        off = int(round((float(t_s) - start) * self._rate)) * fb
        if off < 0 or off >= len(buf):
            return None
        n = max(fb, int(round(max(0.0, float(dur_s)) * self._rate)) * fb)
        chunk = buf[off:off + n]
        if len(chunk) < fb * 8:
            return None
        return self._faded(chunk, fade_s)

    def stop(self):
        with self._cond:
            self._stop = True
            self._want = None
            self._cond.notify()
        self._kill_proc()

    # ── внутреннее ───────────────────────────────────────────────────────────
    def _faded(self, data, fade_s):
        code = "f" if self._sample_bytes == 4 else "h"
        try:
            a = array.array(code)
            a.frombytes(data)
        except Exception:
            return data
        if sys.byteorder == "big":
            a.byteswap()             # ffmpeg отдаёт little-endian
        ch = max(1, self._channels)
        total = len(a) // ch
        n = min(int(max(0.0, fade_s) * self._rate), total // 2)
        if n <= 0:
            return data
        is_int = (code == "h")
        for i in range(n):
            g = (i + 1) / float(n + 1)
            for c in range(ch):
                k = i * ch + c
                j = (total - 1 - i) * ch + c
                if is_int:
                    a[k] = int(a[k] * g)
                    a[j] = int(a[j] * g)
                else:
                    a[k] = a[k] * g
                    a[j] = a[j] * g
        if sys.byteorder == "big":
            a.byteswap()
        return a.tobytes()

    def _kill_proc(self):
        p = self._proc
        if p is not None:
            try:
                p.kill()
            except Exception:
                pass

    def run(self):
        while True:
            with self._cond:
                while self._want is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                want = self._want
                self._want = None
                src, stream = self._src, self._stream
                rate, ch, fmt = self._rate, self._channels, self._fmt
                self._busy = want
            data = self._decode(src, stream, want, rate, ch, fmt) if src else None
            with self._cond:
                self._busy = None
                # Пусто — скорее всего у файла нет звуковой дорожки (картинка,
                # немое видео). Пара попыток, и перестаём звать ffmpeg на каждый
                # шаг: иначе удержание клавиши запускало бы его без конца.
                self._fails = 0 if data else (self._fails + 1)
            if data:
                with self._lock:
                    self._win = (want, data)
                self.ready.emit()

    def _decode(self, src, stream, start, rate, ch, fmt):
        cmd = [FFMPEG, "-nostdin", "-loglevel", "error",
               "-ss", f"{start:.6f}", "-i", str(src),
               "-t", f"{self.WINDOW_S:.3f}",
               "-vn", "-sn", "-map", f"0:{stream}",
               "-f", fmt, "-ar", str(rate), "-ac", str(ch), "-"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW)
        except Exception:
            return None
        self._proc = proc
        try:
            out, _ = proc.communicate(timeout=25)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            out = None
        finally:
            if self._proc is proc:
                self._proc = None
        return out or None
