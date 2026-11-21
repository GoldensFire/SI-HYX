# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Чанковый реверс видео и звука: кэш превью и пайп-генератор для экспорта.
Public namespace: montage_project.

Короткие клипы (до REVERSE_CHUNK_S = 4 с исходника) идут быстрым путём прямо
в графе graph.py (с format и fps до reverse). Длинные клипы делятся на чанки
по 4 с строго по сетке кадров и обрабатываются с конца к началу (N → 0):

* Превью на таймлайне (reverse_preview/<src_hash>_<in_us>_<out_us>_v1.mkv):
  каждый чанк реверсится FFmpeg в libx264 (-preset ultrafast -tune fastdecode
  -crf 20 -g 12 -pix_fmt yuv420p) + pcm_s16le и склеивается через
  -f concat -safe 0 -c copy. Границы округляются наружу, и при подрезке внутрь
  (_trim_reversed) или разрезании клипа кэш переиспользуется со сдвигом.
* Финальный экспорт (ReverseFeedGroup): без промежуточных файлов на диске —
  для каждого длинного реверс-клипа поднимается именованный канал (Windows
  Named Pipe / POSIX FIFO), куда фоновый поток по очереди стримит чанки N → 0
  (yuv4mpegpipe / pam для видео, f32le PCM для звука) прямо в итоговый ffmpeg.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import os
import subprocess
import tempfile
import threading
import uuid

import montage_project as _api
from si_hyx_parts.montage_project import vulkan_fx as _vfx

REVERSE_CHUNK_S = 4.0
_REV_VERSION = 1
_PIPE_BUF = 262144


def reverse_preview_dir():
    """Папка кэша реверс-превью (рядом с кэшами RIFE / Anime4K)."""
    return os.path.join(_vfx.cache_root(), "reverse_preview")


def _file_stamp(path):
    try:
        st = os.stat(path)
        return f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return "missing"


def reverse_src_hash(src, fps=0.0):
    """Стабильный хэш исходника (путь, размер, mtime, fps) для имени кэша."""
    fps_val = float(fps) if fps and fps > 0 else 0.0
    raw = f"{os.path.abspath(str(src))}|{_file_stamp(src)}|{fps_val:.4f}|v{_REV_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def reverse_preview_span(c):
    """Диапазон [span_in, span_out] исходника для кэша реверс-превью: границы
    округляются наружу по сетке REVERSE_CHUNK_S и выравниваются по кадрам."""
    in_s = max(0.0, float(c.in_s))
    out_s = max(in_s, float(c.out_s))
    dur = float(c.src_duration or 0.0)
    step = REVERSE_CHUNK_S
    span_in = math.floor(in_s / step) * step
    span_out = math.ceil(out_s / step) * step
    if span_out <= span_in + 1e-6:
        span_out = span_in + step
    if dur > 0.0:
        span_out = min(span_out, dur)
        span_in = min(span_in, max(0.0, span_out - 1e-3))
    fps = float(c.fps or 0.0)
    if fps > 0.0:
        span_in = max(0.0, math.floor(span_in * fps + 1e-3) / fps)
        span_out = max(span_in + 1.0 / fps, math.ceil(span_out * fps - 1e-3) / fps)
        if dur > 0.0:
            span_out = min(span_out, dur)
    return span_in, max(span_in + 1e-3, span_out)


def reverse_preview_path(src, span_in, span_out, fps=0.0):
    """Путь файла кэша реверс-превью для исходника и диапазона [span_in, span_out]."""
    h = reverse_src_hash(src, fps)
    in_us = int(round(max(0.0, float(span_in)) * 1_000_000))
    out_us = int(round(max(0.0, float(span_out)) * 1_000_000))
    return os.path.join(reverse_preview_dir(), f"{h}_{in_us}_{out_us}_v{_REV_VERSION}.mkv")


def _file_valid(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 1024
    except OSError:
        return False


def reverse_preview_lookup(c):
    """Ищет готовый кэш реверс-превью, покрывающий [c.in_s, c.out_s].
    Возвращает (path, cache_in, cache_out) или None."""
    if c is None or not c.reverse or not c.has_video or c.is_image:
        return None
    fps = float(c.fps or 0.0)
    span_in, span_out = reverse_preview_span(c)
    exact = reverse_preview_path(c.src, span_in, span_out, fps)
    if _file_valid(exact):
        return (exact, span_in, span_out)
    d = reverse_preview_dir()
    if not os.path.isdir(d):
        return None
    prefix = reverse_src_hash(c.src, fps) + "_"
    suffix = f"_v{_REV_VERSION}.mkv"
    best = None
    best_len = float("inf")
    try:
        with os.scandir(d) as it:
            for entry in it:
                name = entry.name
                if not (name.startswith(prefix) and name.endswith(suffix)):
                    continue
                mid = name[len(prefix):-len(suffix)]
                parts = mid.split("_")
                if len(parts) != 2:
                    continue
                try:
                    c_in = int(parts[0]) / 1_000_000.0
                    c_out = int(parts[1]) / 1_000_000.0
                except ValueError:
                    continue
                if c_in <= c.in_s + 1e-3 and c_out >= c.out_s - 1e-3:
                    span = c_out - c_in
                    if span < best_len and _file_valid(entry.path):
                        best = (entry.path, c_in, c_out)
                        best_len = span
    except OSError:
        return None
    return best


def reverse_preview_source(c):
    """Клип-заместитель для живого плеера и дек: src = готовый кэш реверса,
    in_s/out_s сдвинуты внутрь кэша, reverse = False. None, если кэш не готов."""
    hit = reverse_preview_lookup(c)
    if hit is None:
        return None
    path, cache_in, cache_out = hit
    rev_in = max(0.0, cache_out - float(c.out_s))
    rev_out = max(rev_in, cache_out - float(c.in_s))
    cache_dur = max(rev_out, cache_out - cache_in)
    return replace(c, src=path, in_s=rev_in, out_s=rev_out, reverse=False,
                   src_duration=cache_dur)


# ── Чанковая нарезка ─────────────────────────────────────────────────────────
def reverse_chunks(a, b, fps, chunk_s=REVERSE_CHUNK_S):
    """Чанки [(f0, f1, t0, t1), ...] отрезка [a, b] строго по сетке кадров fps
    в обратном порядке (от конца к началу)."""
    fps = float(fps) if fps and fps > 0 else 25.0
    f_start = max(0, int(math.floor(float(a) * fps + 1e-3)))
    f_end = max(f_start + 1, int(round(float(b) * fps)))
    step = max(1, int(round(float(chunk_s) * fps)))
    out = []
    cur = f_end
    while cur > f_start:
        prev = max(f_start, cur - step)
        out.append((prev, cur, prev / fps, cur / fps))
        cur = prev
    return out


def reverse_audio_chunks(a, b, rate=48000, chunk_s=REVERSE_CHUNK_S):
    """Чанки [(s0, s1, t0, t1), ...] отрезка [a, b] по сэмплам в обратном
    порядке (от конца к началу)."""
    rate = max(8000, int(rate))
    s_start = max(0, int(round(float(a) * rate)))
    s_end = max(s_start + 1, int(round(float(b) * rate)))
    step = max(1, int(round(float(chunk_s) * rate)))
    out = []
    cur = s_end
    while cur > s_start:
        prev = max(s_start, cur - step)
        out.append((prev, cur, prev / float(rate), cur / float(rate)))
        cur = prev
    return out


def _assign_job(proc):
    try:
        import process_guard
        process_guard.assign_to_job(proc)
    except Exception:
        pass


def _probe_has_audio(src, ffprobe, creationflags):
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(src)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=creationflags, timeout=15)
        return bool((r.stdout or "").strip())
    except Exception:
        return False


def build_reverse_preview(c, ffmpeg=None, ffprobe=None, stop_check=None, on_progress=None):
    """Собирает кэш reverse_preview/<hash>.mkv чанками по REVERSE_CHUNK_S
    (N → 0) + -f concat -c copy. Возвращает путь к готовому кэш-файлу."""
    hit = reverse_preview_lookup(c)
    if hit is not None:
        return hit[0]
    from ffmpeg_env import CREATE_NO_WINDOW, FFMPEG, FFPROBE
    ffmpeg = ffmpeg or FFMPEG
    ffprobe = ffprobe or FFPROBE
    stop_check = stop_check or (lambda: False)

    fps = float(c.fps or 0.0)
    if fps <= 0.0:
        import reveal_pipe
        _, fps = reveal_pipe.probe_rate(ffprobe, c.src, CREATE_NO_WINDOW)
    rate = _api.fps_expr(fps)
    span_in, span_out = reverse_preview_span(c)
    final_path = reverse_preview_path(c.src, span_in, span_out, float(c.fps or 0.0))
    os.makedirs(reverse_preview_dir(), exist_ok=True)
    if _file_valid(final_path):
        return final_path

    chunks = reverse_chunks(span_in, span_out, fps)
    has_audio = _probe_has_audio(c.src, ffprobe, CREATE_NO_WINDOW)
    a_rate = _api._AUDIO_RATE
    total = len(chunks)
    tmp_dir = tempfile.mkdtemp(prefix="revprev_", dir=reverse_preview_dir())
    kw = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        part_paths = []
        for idx, (f0, f1, t0, t1) in enumerate(chunks):
            if stop_check():
                raise RuntimeError("Отменено")
            n_frames = f1 - f0
            seek = max(0.0, (f0 - 0.25) / fps)
            lead = max(0.0, t0 - seek)
            dur = (t1 - t0) + lead + 0.5 / fps
            part_path = os.path.join(tmp_dir, f"c_{idx:04d}.mkv")
            vf = (f"scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,fps={rate},"
                  f"tpad=stop_mode=clone:stop_duration=0.5,"
                  f"trim=end_frame={n_frames},setpts=PTS-STARTPTS,"
                  f"format=yuv420p,reverse,setpts=PTS-STARTPTS")
            cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
                   "-ss", _api._num(seek), "-t", _api._num(dur), "-i", str(c.src)]
            if has_audio:
                cmd += ["-ss", _api._num(t0), "-t", _api._num((t1 - t0) + 0.15),
                        "-i", str(c.src)]
            cmd += ["-map", "0:v:0", "-vf", vf,
                    "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode",
                    "-crf", "20", "-g", "12", "-keyint_min", "12", "-sc_threshold", "0",
                    "-pix_fmt", "yuv420p"]
            if has_audio:
                ns = max(1, int(round(t1 * a_rate)) - int(round(t0 * a_rate)))
                af = (f"aresample={a_rate},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                      f"atrim=end_sample={ns},areverse,asetpts=PTS-STARTPTS")
                cmd += ["-map", "1:a:0", "-af", af, "-c:a", "pcm_s16le"]
            else:
                cmd += ["-an"]
            cmd += ["-sn", "-dn", part_path]
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, **kw)
            _assign_job(proc)
            err_b = b""
            while proc.poll() is None:
                if stop_check():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    proc.wait(timeout=5)
                    raise RuntimeError("Отменено")
                try:
                    _, err_b = proc.communicate(timeout=0.15)
                except subprocess.TimeoutExpired:
                    pass
            if proc.returncode != 0:
                msg = (err_b or b"").decode("utf-8", errors="replace").strip()[-400:]
                raise RuntimeError(f"Ошибка реверса чанка {idx + 1}/{total}: {msg or proc.returncode}")
            part_paths.append(part_path)
            if on_progress is not None:
                on_progress(int(round(100.0 * (idx + 1) / max(1, total))))

        if stop_check():
            raise RuntimeError("Отменено")
        list_path = os.path.join(tmp_dir, "list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in part_paths:
                esc = p.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{esc}'\n")
        tmp_out = os.path.join(tmp_dir, "out.mkv")
        ccmd = [ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", tmp_out]
        proc = subprocess.Popen(ccmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, **kw)
        _assign_job(proc)
        _, err_b = proc.communicate()
        if proc.returncode != 0 or not _file_valid(tmp_out):
            msg = (err_b or b"").decode("utf-8", errors="replace").strip()[-400:]
            raise RuntimeError(f"Ошибка склейки реверс-превью: {msg or proc.returncode}")
        try:
            os.replace(tmp_out, final_path)
        except OSError:
            if not _file_valid(final_path):
                raise
        return final_path
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Пайп-генератор для финального экспорта ───────────────────────────────────
def make_pipe_name(kind):
    uid = uuid.uuid4().hex
    if os.name == "nt":
        return rf"\\.\pipe\sihyx_rev_{kind}_{uid}"
    return os.path.join(tempfile.gettempdir(), f"sihyx_rev_{kind}_{uid}.fifo")


@dataclass
class ReverseVideoFeedSpec:
    """Спецификация чанкового видео-пайпа для длинного реверс-клипа."""
    pipe_name: str
    src: str
    t_start: float        # начало исходного отрезка (с)
    t_end: float          # конец исходного отрезка (с)
    n_frames: int         # точное число выходных кадров
    fps: float            # fps проекта
    rate: str             # fps_expr(fps)
    src_fps: float        # fps исходника (0 если неизвестен)
    speed: float          # скорость воспроизведения клипа
    vf_pre: str           # цепочка фильтров после tone/burn до fps/format/reverse
    pix_fmt: str          # 'yuv420p' или 'rgba'
    fmt: str              # 'yuv4mpegpipe' или 'pam'
    tone_vf: str = ""     # HDR → SDR до субтитров
    sub_vf: str = ""      # фильтр subtitles=… (смещение считается на каждый чанк)


@dataclass
class ReverseAudioFeedSpec:
    """Спецификация чанкового аудио-пайпа (f32le 48 кГц стерео) для реверса."""
    pipe_name: str
    audio_path: str
    audio_stream: int     # -1 или абсолютный индекс потока
    t_start: float
    t_end: float
    rate: int = 48000


class _WinPipe:
    """Обёртка над Windows Named Pipe (однонаправленный выходной канал)."""

    def __init__(self, name):
        import ctypes
        self._k32 = ctypes.windll.kernel32
        self._ctypes = ctypes
        self.name = name
        # PIPE_ACCESS_OUTBOUND = 2, PIPE_TYPE_BYTE | PIPE_WAIT = 0
        h = self._k32.CreateNamedPipeW(
            name, 2, 0, 1, _PIPE_BUF, _PIPE_BUF, 0, None)
        if h in (0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            raise OSError(f"CreateNamedPipeW failed for {name}")
        self._h = h
        self._closed = False
        self._connected = False

    def connect(self):
        if self._closed:
            return False
        ok = self._k32.ConnectNamedPipe(self._h, None)
        if not ok:
            # ERROR_PIPE_CONNECTED (535) — клиент успел подключиться до ConnectNamedPipe
            if self._k32.GetLastError() != 535:
                return False
        self._connected = True
        return True

    def write(self, data):
        if self._closed or not data:
            return True
        view = memoryview(data)
        total = len(view)
        written_total = 0
        written = self._ctypes.c_ulong(0)
        while written_total < total:
            chunk = bytes(view[written_total:]) if written_total else data
            ok = self._k32.WriteFile(
                self._h, chunk, len(chunk), self._ctypes.byref(written), None)
            if not ok or written.value == 0:
                return False
            written_total += written.value
        return True

    def wake_connect(self):
        """Разблокировать ConnectNamedPipe при отмене до подключения клиента."""
        if self._connected or self._closed:
            return
        try:
            # GENERIC_READ = 0x80000000, OPEN_EXISTING = 3
            ch = self._k32.CreateFileW(self.name, 0x80000000, 0, None, 3, 0, None)
            if ch not in (0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                self._k32.CloseHandle(ch)
        except Exception:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._connected:
                self._k32.FlushFileBuffers(self._h)
        except Exception:
            pass
        try:
            self._k32.CloseHandle(self._h)
        except Exception:
            pass


class _PosixPipe:
    """Обёртка над POSIX FIFO."""

    def __init__(self, name):
        self.name = name
        os.mkfifo(name)
        self._f = None
        self._closed = False

    def connect(self):
        if self._closed:
            return False
        self._f = open(self.name, "wb", buffering=0)
        return True

    def write(self, data):
        if self._closed or self._f is None:
            return False
        try:
            self._f.write(data)
            return True
        except OSError:
            return False

    def wake_connect(self):
        if self._f is not None or self._closed:
            return
        try:
            fd = os.open(self.name, os.O_RDONLY | os.O_NONBLOCK)
            os.close(fd)
        except OSError:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._f is not None:
            try:
                self._f.close()
            except OSError:
                pass
            self._f = None
        try:
            if os.path.exists(self.name):
                os.remove(self.name)
        except OSError:
            pass


class ReverseFeedGroup:
    """Набор фоновых пайп-генераторов для одного запуска экспорта ffmpeg."""

    def __init__(self, specs, ffmpeg=None):
        self.specs = list(specs or [])
        from ffmpeg_env import CREATE_NO_WINDOW, FFMPEG
        self._ffmpeg = ffmpeg or FFMPEG
        self._cflags = CREATE_NO_WINDOW if os.name == "nt" else 0
        self._pipes = []
        self._threads = []
        self._procs = []
        self._lock = threading.Lock()
        self._stopped = False
        self.error = None

    def start(self):
        if not self.specs:
            return self
        pipe_cls = _WinPipe if os.name == "nt" else _PosixPipe
        for spec in self.specs:
            pipe = pipe_cls(spec.pipe_name)
            self._pipes.append(pipe)
            target = (self._pump_video if isinstance(spec, ReverseVideoFeedSpec)
                      else self._pump_audio)
            t = threading.Thread(target=target, args=(spec, pipe), daemon=True,
                                 name="rev-pipe")
            self._threads.append(t)
        for t in self._threads:
            t.start()
        return self

    def stop(self):
        self._stopped = True
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass
        for pipe in self._pipes:
            pipe.wake_connect()

    def join(self, timeout=30.0):
        for t in self._threads:
            t.join(timeout=timeout)
        for pipe in self._pipes:
            pipe.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.stop()
        self.join()
        return False

    def _run_chunk(self, cmd):
        kw = {"creationflags": self._cflags} if self._cflags else {}
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, **kw)
        _assign_job(proc)
        with self._lock:
            self._procs.append(proc)
        return proc

    def _finish_chunk(self, proc):
        with self._lock:
            if proc in self._procs:
                self._procs.remove(proc)
        try:
            err_b = proc.stderr.read() if proc.stderr else b""
        except Exception:
            err_b = b""
        try:
            rc = proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
            rc = -1
        return rc, (err_b or b"").decode("utf-8", errors="replace").strip()

    def _record_error(self, msg):
        if not self._stopped and self.error is None:
            self.error = msg

    def _pump_video(self, spec: ReverseVideoFeedSpec, pipe):
        try:
            if not pipe.connect() or self._stopped:
                return
            fps = spec.fps if spec.fps > 0 else 25.0
            src_fps = spec.src_fps if spec.src_fps > 0 else fps
            speed = spec.speed if spec.speed > 0 else 1.0
            span_src = max(1e-3, spec.t_end - spec.t_start)
            # Делим исходный отрезок на чанки ~REVERSE_CHUNK_S с конца к началу,
            # распределяя точное число выходных кадров spec.n_frames без дрейфа.
            n_chunks = max(1, int(math.ceil(span_src / REVERSE_CHUNK_S)))
            n_total = max(1, int(spec.n_frames))
            # Границы выходных кадров: [0, n_total)
            bounds = [int(round(i * n_total / float(n_chunks))) for i in range(n_chunks + 1)]
            # Идём по чанкам в прямом порядке выходного видео (т.е. от конца к началу исходника).
            for i in range(n_chunks):
                if self._stopped:
                    return
                out_f0, out_f1 = bounds[i], bounds[i + 1]
                n_chunk = out_f1 - out_f0
                if n_chunk <= 0:
                    continue
                # Соответствующий отрезок исходника (идёт задом наперёд).
                c_end = spec.t_end - (out_f0 / fps) * speed
                c_start = max(spec.t_start, spec.t_end - (out_f1 / fps) * speed)
                if src_fps > 0:
                    idx0 = math.floor(c_start * src_fps + 1e-3)
                    seek = max(0.0, (idx0 - 0.25) / src_fps)
                else:
                    seek = max(0.0, c_start)
                lead = max(0.0, c_start - seek)
                dur = max(1e-3, (c_end - c_start) + lead + 0.5 / max(1.0, src_fps))
                pre = spec.vf_pre.rstrip(",")
                tone = f"{spec.tone_vf}," if spec.tone_vf else ""
                burn = ""
                if spec.sub_vf:
                    first = _api.snap_to_frame(c_start, src_fps)
                    burn = f"setpts=PTS-STARTPTS+{_api._num(first)}/TB,{spec.sub_vf},"
                vf = (f"{tone}{burn}{pre},fps={spec.rate},"
                      f"tpad=stop_mode=clone:stop_duration=0.5,"
                      f"trim=end_frame={n_chunk},setpts=PTS-STARTPTS,"
                      f"format={spec.pix_fmt},reverse,setpts=PTS-STARTPTS")
                if spec.fmt == "pam":
                    out_args = ["-f", "image2pipe", "-c:v", "pam", "-"]
                else:
                    out_args = ["-f", "yuv4mpegpipe", "-"]
                cmd = [self._ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                       "-ss", _api._num(seek), "-t", _api._num(dur), "-i", str(spec.src),
                       "-map", "0:v:0", "-vf", vf, "-an", "-sn", "-dn"] + out_args
                proc = self._run_chunk(cmd)
                try:
                    if spec.fmt == "yuv4mpegpipe" and i > 0:
                        # Пропускаем заголовок YUV4MPEG2 ... следующего чанка.
                        hdr = proc.stdout.readline()
                        if not hdr:
                            break
                    while not self._stopped:
                        buf = proc.stdout.read(_PIPE_BUF)
                        if not buf:
                            break
                        if not pipe.write(buf):
                            self._stopped = True
                            break
                finally:
                    rc, err = self._finish_chunk(proc)
                if rc != 0 and not self._stopped:
                    self._record_error(f"Реверс видео (чанк {i + 1}/{n_chunks}): {err[-300:] or rc}")
                    return
        except Exception as e:  # noqa: BLE001
            self._record_error(f"Реверс видео: {e}")
        finally:
            pipe.close()

    def _pump_audio(self, spec: ReverseAudioFeedSpec, pipe):
        try:
            if not pipe.connect() or self._stopped:
                return
            chunks = reverse_audio_chunks(spec.t_start, spec.t_end, rate=spec.rate)
            amap = f"0:{spec.audio_stream}" if spec.audio_stream >= 0 else "0:a:0"
            for i, (s0, s1, c_t0, c_t1) in enumerate(chunks):
                if self._stopped:
                    return
                ns = s1 - s0
                if ns <= 0:
                    continue
                af = (f"aresample={spec.rate},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                      f"atrim=end_sample={ns},areverse,asetpts=PTS-STARTPTS")
                cmd = [self._ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                       "-ss", _api._num(c_t0), "-t", _api._num((c_t1 - c_t0) + 0.15),
                       "-i", str(spec.audio_path), "-map", amap, "-vn", "-sn", "-dn",
                       "-af", af, "-f", "f32le", "-ar", str(spec.rate), "-ac", "2", "-"]
                proc = self._run_chunk(cmd)
                try:
                    while not self._stopped:
                        buf = proc.stdout.read(_PIPE_BUF)
                        if not buf:
                            break
                        if not pipe.write(buf):
                            self._stopped = True
                            break
                finally:
                    rc, err = self._finish_chunk(proc)
                if rc != 0 and not self._stopped:
                    self._record_error(f"Реверс звука (чанк {i + 1}/{len(chunks)}): {err[-300:] or rc}")
                    return
        except Exception as e:  # noqa: BLE001
            self._record_error(f"Реверс звука: {e}")
        finally:
            pipe.close()
