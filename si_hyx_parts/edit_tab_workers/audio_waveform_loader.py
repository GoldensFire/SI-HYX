# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AudioWaveformLoader. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class AudioWaveformLoader(_api.QThread):
    # samples (combined max L/R для рисовки), duration, left, right (раздельные
    # огибающие каналов — для честного стерео-индикатора уровня).
    finished = _api.pyqtSignal(list, float, list, list)
    progress = _api.pyqtSignal(str)

    def __init__(self, filepath, audio_index, duration=0.0, parent=None):
        super().__init__(parent)
        self.filepath = str(filepath)
        self.audio_index = audio_index
        self.total_dur = float(duration or 0.0)   # для процентов извлечения
        self.tmp_wav = None
        self.proc = None
        self._stopped = False

    def _run_ffmpeg(self, cmd, feed_path=None):
        # -progress pipe:1 даёт машинный прогресс (out_time_us=…) — по нему
        # показываем проценты. -nostats глушит обычный лог в stderr.
        # feed_path задан → вход «pipe:0» кормим файлом через FILE_SHARE_DELETE
        # (исходник остаётся удаляемым из Проводника во время построения волны).
        full = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
        self.proc = _api.subprocess.Popen(
            full, stdin=(_api.subprocess.PIPE if feed_path else None),
            stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=_api.CREATE_NO_WINDOW)
        if feed_path:
            _api.start_share_delete_feeder(
                feed_path, self.proc.stdin, stop_flag=lambda: self._stopped)
        last_pct = -1
        try:
            for line in self.proc.stdout:
                if self._stopped:
                    break
                line = line.strip()
                if self.total_dur > 0 and line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        pct = max(0, min(99, int(us / (10000.0 * self.total_dur))))
                        if pct != last_pct:
                            last_pct = pct
                            self.progress.emit(f"Извлечение аудио… {pct}%")
                    except Exception:
                        pass
        except Exception:
            pass
        self.proc.wait()
        return self.proc.returncode == 0

    def run(self):
        self.progress.emit("Извлечение аудио...")
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tf.close()
        self.tmp_wav = tf.name

        tail = []
        if self.audio_index is not None:
            tail += ["-map", f"0:{self.audio_index}"]
        # -ac 2: тянем ДВА канала (mono-источник ffmpeg продублирует — L==R, как и
        # положено; 5.1 сведёт в стерео) → у индикатора уровня честные L и R.
        tail += ["-af", "aresample=6000,asetpts=PTS-STARTPTS",
                 "-ac", "2", "-ar", "6000", "-f", "wav", self.tmp_wav]
        cmd_pipe = [_api.FFMPEG, "-y", "-i", "pipe:0", "-vn"] + tail
        cmd_file = [_api.FFMPEG, "-y", "-i", self.filepath, "-vn"] + tail

        ok = False
        # Сначала через FILE_SHARE_DELETE-пайп (исходник остаётся удаляемым во
        # время построения волны). Не для всех контейнеров pipe:0 годится
        # (moov в конце mp4 без faststart) — ffmpeg тогда может отрапортовать
        # rc=0, при этом записав ПУСТОЙ wav (см. тот же баг в ProxyWorker), так
        # что дополнительно проверяем реальное число сэмплов, а не только rc.
        if _api.os.name == 'nt':
            try:
                ok = self._run_ffmpeg(cmd_pipe, feed_path=self.filepath) and self._wav_has_frames(self.tmp_wav)
            except Exception:
                ok = False
        if not ok and not self._stopped:
            try:
                ok = self._run_ffmpeg(cmd_file) and self._wav_has_frames(self.tmp_wav)
            except Exception:
                ok = False

        if not ok and not self._stopped:
            try:
                ok = self._run_ffmpeg(
                    [_api.FFMPEG, "-y", "-i", self.filepath, "-vn",
                     "-ac", "2", "-ar", "6000", "-f", "wav", self.tmp_wav]) and self._wav_has_frames(self.tmp_wav)
            except Exception:
                ok = False

        if self._stopped or not ok or not _api.os.path.exists(self.tmp_wav):
            self._cleanup_tmp()
            self.finished.emit([], 0.0, [], [])
            return

        self.progress.emit("Генерация волны...")
        try:
            samples, duration, left, right = self.read_wav_chunked(
                self.tmp_wav, target_samples=8000)
        except Exception:
            samples, duration, left, right = [], 0.0, [], []
        self._cleanup_tmp()
        self.finished.emit(samples, duration, left, right)

    @staticmethod
    def _wav_has_frames(path):
        try:
            wf = _api.wave.open(path, 'rb')
            try:
                return wf.getnframes() > 0
            finally:
                wf.close()
        except Exception:
            return False

    def _cleanup_tmp(self):
        try:
            if self.tmp_wav and _api.os.path.exists(self.tmp_wav):
                _api.os.remove(self.tmp_wav)
        except Exception:
            pass

    def stop(self):
        self._stopped = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

    def read_wav_chunked(self, wav_path, target_samples=8000):
        """Возвращает (combined, duration, left, right): combined — поканальный
        максимум (для рисовки волны), left/right — раздельные огибающие каналов
        (для честного стерео-индикатора). Кадры деинтерливим (буфер L,R,L,R…)
        и считаем пики L и R в одних и тех же бакетах, чтобы шкалы были выровнены."""
        import array as _array
        try:
            wf = _api.wave.open(wav_path, 'rb')
        except Exception:
            return [], 0.0, [], []

        n_frames  = wf.getnframes()
        framerate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        nchan     = max(1, wf.getnchannels())
        duration  = n_frames / framerate if framerate > 0 else 0.0

        if n_frames == 0:
            wf.close()
            return [], duration, [], []

        samples_per_pixel = max(1, n_frames // target_samples)
        chunk_size_frames = 256 * 1024

        if sampwidth == 1:
            typecode = 'B'; scale = 128.0; bias = 128
        elif sampwidth == 2:
            typecode = 'h'; scale = 32768.0; bias = 0
        elif sampwidth == 4:
            typecode = 'i'; scale = 2147483648.0; bias = 0
        else:
            wf.close()
            return [], duration, [], []

        def _peak(seg):
            if not len(seg):
                return 0.0
            hi = max(seg); lo = min(seg)
            if bias:
                return max(abs(hi - bias), abs(lo - bias)) / scale
            return max(abs(hi), abs(lo)) / scale

        comb: list[float] = []; left: list[float] = []; right: list[float] = []
        cur_l = 0.0; cur_r = 0.0; acc = 0

        processed = 0
        while processed < n_frames:
            if self._stopped:
                break
            raw = wf.readframes(chunk_size_frames)
            if not raw:
                break
            buf = _array.array(typecode, raw)
            if typecode != 'B' and _api.sys.byteorder == 'big':
                buf.byteswap()
            if nchan >= 2:
                lbuf = buf[0::nchan]; rbuf = buf[1::nchan]
            else:
                lbuf = buf; rbuf = buf
            frames_in_chunk = len(lbuf)
            i = 0
            while i < frames_in_chunk:
                take = min(samples_per_pixel - acc, frames_in_chunk - i)
                if take <= 0:
                    break
                pl = _peak(lbuf[i: i + take])
                pr = _peak(rbuf[i: i + take])
                if pl > cur_l: cur_l = pl
                if pr > cur_r: cur_r = pr
                acc += take
                i += take
                if acc >= samples_per_pixel:
                    left.append(cur_l); right.append(cur_r)
                    comb.append(cur_l if cur_l > cur_r else cur_r)
                    cur_l = 0.0; cur_r = 0.0; acc = 0
            processed += frames_in_chunk

        wf.close()
        if not comb:
            return [0.0], duration, [0.0], [0.0]
        return comb, duration, left, right

AudioWaveformLoader.__module__ = _api.__name__
_api.AudioWaveformLoader = AudioWaveformLoader

class AudioSegmentWaveformLoader(_api.AudioWaveformLoader):
    """Быстрая волна ТОЛЬКО для отрезка IN..OUT — используется при смене
    аудиодорожки, чтобы сразу показать, как звучит новая дорожка именно на
    выделенном куске, не дожидаясь полного прохода по всему файлу (для фильма
    это могут быть минуты). Точный -ss перед -i декодирует только сам отрезок."""
    finished = _api.pyqtSignal(list, float, float, list, list)  # samples, seg_in, seg_out, left, right

    def __init__(self, filepath, audio_index, seg_in, seg_out, full_duration, parent=None):
        super().__init__(filepath, audio_index, duration=max(0.05, seg_out - seg_in), parent=parent)
        self.seg_in = float(seg_in)
        self.seg_out = float(seg_out)
        self.full_duration = max(0.001, float(full_duration or (seg_out - seg_in)))

    def run(self):
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tf.close()
        self.tmp_wav = tf.name

        tail = []
        if self.audio_index is not None:
            tail += ["-map", f"0:{self.audio_index}"]
        tail += ["-af", "aresample=6000,asetpts=PTS-STARTPTS",
                 "-ac", "2", "-ar", "6000", "-f", "wav", self.tmp_wav]
        cmd = ([_api.FFMPEG, "-y", "-ss", f"{self.seg_in:.3f}", "-i", self.filepath,
                "-t", f"{max(0.05, self.seg_out - self.seg_in):.3f}", "-vn"] + tail)

        ok = False
        try:
            ok = self._run_ffmpeg(cmd) and self._wav_has_frames(self.tmp_wav)
        except Exception:
            ok = False

        if self._stopped or not ok or not _api.os.path.exists(self.tmp_wav):
            self._cleanup_tmp()
            self.finished.emit([], self.seg_in, self.seg_out, [], [])
            return

        # Разрешение отрезка пропорционально его доле в полном файле — тот же
        # эффективный масштаб «сэмплов на секунду», что и у полной волны.
        seg_dur = max(0.001, self.seg_out - self.seg_in)
        target = max(50, min(4000, int(8000 * seg_dur / self.full_duration)))
        try:
            samples, _dur, left, right = self.read_wav_chunked(self.tmp_wav, target_samples=target)
        except Exception:
            samples, left, right = [], [], []
        self._cleanup_tmp()
        self.finished.emit(samples, self.seg_in, self.seg_out, left, right)

AudioSegmentWaveformLoader.__module__ = _api.__name__
_api.AudioSegmentWaveformLoader = AudioSegmentWaveformLoader

class SubtitleExtractor(_api.QThread):
    """Извлекает выбранную текстовую дорожку субтитров в SRT и парсит её —
    в фоне, чтобы не подвешивать GUI."""
    done = _api.pyqtSignal(int, object)   # (token, cues|None)

    def __init__(self, src, sub_index, token):
        super().__init__()
        self.src = str(src)
        self.sub_index = int(sub_index)
        self.token = int(token)

    def run(self):
        cues = None
        tmp = None
        try:
            tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
            tmp = tf.name; tf.close()
            cmd = [_api.FFMPEG, "-y", "-i", self.src,
                   "-map", f"0:s:{self.sub_index}", tmp]
            kw = {}
            if _api.os.name == 'nt':
                kw['creationflags'] = _api.CREATE_NO_WINDOW
            _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                           stderr=_api.subprocess.DEVNULL, timeout=90, **kw)
            if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
                with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                    cues = _api._parse_srt(f.read())
        except Exception:
            cues = None
        finally:
            if tmp:
                try: _api.os.remove(tmp)
                except Exception: pass
        self.done.emit(self.token, cues)

SubtitleExtractor.__module__ = _api.__name__
_api.SubtitleExtractor = SubtitleExtractor
