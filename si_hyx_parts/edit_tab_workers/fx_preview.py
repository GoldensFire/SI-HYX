# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""FxPreview — просмотр проекта «Монтажа» с эффектами и текстом.
Public namespace: edit_tab_workers.

Живой плеер вкладки играет исходники кусками и ни эффектов, ни текста, ни
наложений с масками не показывает: всё это существует только в графе ffmpeg
сборки. Поэтому кадр просмотра рендерится ТЕМ ЖЕ графом
(montage_project.build_source по окну проекта), только в кадре превью
(короткая сторона PREVIEW_SHORT, fps проекта):

* пауза и протяжка — кадр на плейхеде (still): из готового куска кэша или
  рендером окна в один кадр; запрос новее отменяет ожидающий;
* игра — поток кадров rawvideo (play): по кускам CHUNK_S от плейхеда; готовый
  кусок кэша декодируется, неготовый рендерится на ходу и заодно пишется в
  кэш (split графа на второй выход) — второй просмотр того же места идёт из
  кэша;
* на паузе кэш дорисовывается фоном от плейхеда (fill).

Ключ куска — SHA-1 графа и входов окна (пути, время, фильтры, текст) и
отметок файлов (время правки, размер): правка проекта сбрасывает ровно те
куски, чей граф изменился. Кэш — %TEMP%/si-hyx-fx-preview, старше
_CACHE_DAYS дней и сверх _CACHE_MAX_BYTES удаляется."""
import hashlib

import hdr_tonemap
from ffmpeg_env import escape_filter_path

import edit_tab_workers as _api

PREVIEW_SHORT = 540
CHUNK_S = 5.0
_AHEAD_FRAMES = 90          # столько кадров игры держим впереди часов
_CACHE_DAYS = 7
_CACHE_MAX_BYTES = 3 * 1024 ** 3
_VERSION = 1
_ENC = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-g", "12",
        "-pix_fmt", "yuv420p", "-an"]


def cache_dir():
    return _api.os.path.join(_api.tempfile.gettempdir(), "si-hyx-fx-preview")


def preview_project(project):
    """Копия проекта в кадре превью (те же пропорции, чётные стороны, fps
    проекта) — граф целиком считается в малом кадре, а не уменьшается в конце."""
    p = project.copy()
    w, h, fps = p.output_format()
    k = min(1.0, float(PREVIEW_SHORT) / max(1, min(w, h)))
    p.settings.width = max(2, int(round(w * k / 2.0)) * 2)
    p.settings.height = max(2, int(round(h * k / 2.0)) * 2)
    p.settings.fps = fps
    return p


def _stamp(path):
    try:
        st = _api.os.stat(path)
    except OSError:
        return "-"
    return f"{st.st_mtime_ns}:{st.st_size}"


def _graph(p, f0, f1):
    """SourceGraph кадров [f0, f1) проекта превью (только картинка) или None."""
    _w, _h, fps = p.output_format()
    tonemap = hdr_tonemap.tonemap_filters(
        (c.src for c in p.clips if c.has_video and not c.is_image), escape_filter_path)
    return _api.montage_project.build_source(p, audio=False, tonemap=tonemap,
                                             window=(f0 / fps, f1 / fps))


def _key(src):
    files = [a for args in src.inputs for i, a in enumerate(args)
             if i > 0 and args[i - 1] == "-i"]
    h = hashlib.sha1()
    h.update(f"{_VERSION}|{src.width}x{src.height}@{src.fps}|".encode("utf-8"))
    h.update(src.graph.encode("utf-8", "replace"))
    for a in src.input_args():
        h.update(b"\0" + str(a).encode("utf-8", "replace"))
    for f in files:
        h.update(b"\1" + _stamp(f).encode("ascii"))
    return h.hexdigest()


def _graph_file(graph):
    tf = _api.tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False,
                                          suffix=".txt", prefix="sihyx_fx_")
    tf.write(graph)
    tf.close()
    return tf.name


def _remove(path):
    try:
        _api.os.remove(path)
    except OSError:
        pass


def prune_cache():
    """Старые куски и лишний объём кэша — прочь (вызывается из потока)."""
    folder = cache_dir()
    try:
        names = _api.os.listdir(folder)
    except OSError:
        return
    now = _api.time.time()
    items = []
    for n in names:
        path = _api.os.path.join(folder, n)
        try:
            st = _api.os.stat(path)
        except OSError:
            continue
        if now - st.st_mtime > _CACHE_DAYS * 86400:
            _remove(path)
            continue
        items.append((st.st_mtime, st.st_size, path))
    total = sum(s for _m, s, _p in items)
    for _m, size, path in sorted(items):
        if total <= _CACHE_MAX_BYTES:
            break
        _remove(path)
        total -= size


class _Plan:
    """Куски проекта превью: (f0, f1, ключ, файл кэша) по сетке кадров."""

    def __init__(self, project):
        self.p = preview_project(project)
        w, h, fps = self.p.output_format()
        self.w, self.h, self.fps = w, h, fps
        self.n_frames = int(round(self.p.duration() * fps)) if self.p.has_video() else 0
        self.chunk = max(1, int(round(CHUNK_S * fps)))
        self._keys = {}

    def chunks(self):
        return range((self.n_frames + self.chunk - 1) // self.chunk)

    def span(self, k):
        f0 = k * self.chunk
        return f0, min(self.n_frames, f0 + self.chunk)

    def key(self, k):
        """(ключ, путь кэша) куска k или None (нечего рендерить)."""
        if k not in self._keys:
            f0, f1 = self.span(k)
            src = _graph(self.p, f0, f1) if f1 > f0 else None
            if src is None or not src.video:
                self._keys[k] = None
            else:
                key = _key(src)
                self._keys[k] = (key, _api.os.path.join(cache_dir(), key + ".mp4"))
        return self._keys[k]

    def ready(self, k):
        kp = self.key(k)
        return kp is not None and _api.os.path.isfile(kp[1])


def _image(buf, w, h):
    return _api.QImage(buf, w, h, 3 * w, _api.QImage.Format.Format_RGB888).copy()


def _popen(cmd):
    return _api.subprocess.Popen(cmd, stdin=_api.subprocess.DEVNULL,
                                 stdout=_api.subprocess.PIPE,
                                 stderr=_api.subprocess.DEVNULL,
                                 creationflags=_api.CREATE_NO_WINDOW)


def _kill(proc):
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    if proc is not None:
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


def _frames_cmd(plan, k, f_from, cache_out=None, limit=None):
    """ffmpeg, выдающий rawvideo rgb24 кадров [f_from, конец куска k) (limit —
    не больше стольких); с cache_out — ещё и файл куска (только когда кусок
    рендерится целиком). (команда, файл графа или None)."""
    f0, f1 = plan.span(k)
    ff = [_api.FFMPEG, "-hide_banner", "-v", "error", "-nostdin"]
    n = f1 - f_from if limit is None else min(limit, f1 - f_from)
    raw = ["-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    if plan.ready(k):
        off = (f_from - f0) / plan.fps
        cmd = ff + (["-ss", f"{off:.6f}"] if off > 0 else []) + ["-i", plan.key(k)[1],
                                                               "-map", "0:v:0"] + raw
        return cmd, None
    src = _graph(plan.p, f_from, f_from + n if limit is not None else f1)
    if src is None or not src.video:
        return None, None
    graph = src.graph
    if cache_out:
        graph += ";[vout]split=2[vraw][vcache]"
        maps = (["-map", "[vraw]"] + raw + ["-map", "[vcache]"] + _ENC
                + ["-f", "mp4", "-y", cache_out])
    else:
        maps = ["-map", "[vout]"] + raw
    gfile = _graph_file(graph)
    return ff + src.input_args() + ["-/filter_complex", gfile] + maps, gfile


class FxPreview(_api.QObject):
    """Кадры просмотра с эффектами: still (пауза), play (игра), fill (кэш).
    Живёт в главном потоке; ffmpeg и чтение кадров — в своих потоках."""

    stillReady = _api.pyqtSignal(int, float, object)   # поколение, время, QImage
    cacheProgress = _api.pyqtSignal(int, int)          # готово кусков, всего
    failed = _api.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = _api.threading.Lock()
        self._plan = None
        self._plan_src = None          # проект, по которому построен план
        self._still_req = None         # (поколение, время) — последний запрос
        self._still_gen = 0
        self._still_thread = None
        self._play_gen = 0
        self._play_thread = None
        self._play_proc = None
        self._frames = _api.collections.deque()
        self._play_done = False
        self._fill_gen = 0
        self._fill_thread = None
        self._fill_proc = None
        self._fill_from = 0.0
        self._pruned = False

    # ── План ─────────────────────────────────────────────────────────────────
    def set_project(self, project):
        """Проект изменился: новый план (ключи считаются лениво, в потоках)."""
        self.stop()
        self.stop_fill()
        with self._lock:
            self._plan = _Plan(project) if project.has_video() else None
            self._plan_src = project

    def plan(self):
        with self._lock:
            return self._plan

    def fps(self):
        p = self.plan()
        return p.fps if p is not None else 30.0

    def size(self):
        p = self.plan()
        return (p.w, p.h) if p is not None else (0, 0)

    # ── Кадр на паузе ────────────────────────────────────────────────────────
    def still(self, t):
        """Кадр проекта на t (асинхронно, stillReady); поколение запроса."""
        self._still_gen += 1
        self._still_req = (self._still_gen, float(t))
        if self._still_thread is None or not self._still_thread.is_alive():
            self._still_thread = _api.threading.Thread(target=self._still_loop, daemon=True)
            self._still_thread.start()
        return self._still_gen

    def _still_loop(self):
        while True:
            req, self._still_req = self._still_req, None
            if req is None:
                return
            gen, t = req
            plan = self.plan()
            if plan is None or plan.n_frames <= 0:
                continue
            f = max(0, min(plan.n_frames - 1, int(_api.math.floor(t * plan.fps + 1e-3))))
            k = f // plan.chunk
            img = None
            try:
                cmd, gfile = _frames_cmd(plan, k, f, limit=1)
                if cmd is not None:
                    r = _api.subprocess.run(cmd, stdin=_api.subprocess.DEVNULL,
                                            capture_output=True, timeout=120,
                                            creationflags=_api.CREATE_NO_WINDOW)
                    if gfile:
                        _remove(gfile)
                    need = plan.w * plan.h * 3
                    if r.returncode == 0 and len(r.stdout) >= need:
                        img = _image(r.stdout[:need], plan.w, plan.h)
                    elif r.returncode != 0:
                        tail = (r.stderr or b"").decode("utf-8", "replace").strip()[-300:]
                        self.failed.emit(tail or f"ffmpeg: код {r.returncode}")
            except Exception as e:        # сбой ffmpeg или графа — не роняем поток
                self.failed.emit(str(e))
            if img is not None and self._still_req is None:
                self.stillReady.emit(gen, f / plan.fps, img)

    # ── Игра ─────────────────────────────────────────────────────────────────
    def play(self, t):
        """Поток кадров с t: кадры копятся в очереди, take() отдаёт нужный."""
        self.stop()
        self.stop_fill()
        plan = self.plan()
        if plan is None or plan.n_frames <= 0:
            return False
        self._play_gen += 1
        self._play_done = False
        f = max(0, min(plan.n_frames - 1, int(_api.math.floor(t * plan.fps + 1e-3))))
        th = _api.threading.Thread(target=self._play_loop, args=(plan, f, self._play_gen),
                                   daemon=True)
        self._play_thread = th
        th.start()
        return True

    def _play_loop(self, plan, f, gen):
        try:
            self._play_run(plan, f, gen)
        except Exception as e:            # сбой графа (файл, текст) — не роняем поток
            self.failed.emit(str(e))
        if gen == self._play_gen:
            self._play_done = True

    def _play_run(self, plan, f, gen):
        need = plan.w * plan.h * 3
        _api.os.makedirs(cache_dir(), exist_ok=True)
        if not self._pruned:
            self._pruned = True
            prune_cache()
        k = f // plan.chunk
        while gen == self._play_gen and k < len(plan.chunks()):
            f0, f1 = plan.span(k)
            start = max(f, f0)
            whole = start == f0 and not plan.ready(k)
            kp = plan.key(k)
            part = (kp[1] + f".part{gen}.mp4") if whole and kp is not None else None
            cmd, gfile = _frames_cmd(plan, k, start, cache_out=part)
            if cmd is None:
                k += 1
                continue
            try:
                proc = _popen(cmd)
            except OSError as e:
                self.failed.emit(str(e))
                break
            self._play_proc = proc
            n = start
            ok = True
            while gen == self._play_gen and n < f1:
                while gen == self._play_gen and len(self._frames) > _AHEAD_FRAMES:
                    _api.time.sleep(0.005)
                buf = proc.stdout.read(need) if gen == self._play_gen else b""
                if len(buf) < need:
                    ok = n >= f1 - 1
                    break
                self._frames.append((n / plan.fps, _image(buf, plan.w, plan.h)))
                n += 1
            finished = gen == self._play_gen and ok
            if not finished:
                _kill(proc)
            else:
                try:
                    proc.stdout.close()
                    proc.wait(timeout=30)
                except Exception:
                    _kill(proc)
            if gfile:
                _remove(gfile)
            if part:
                if finished and proc.returncode == 0 and _api.os.path.isfile(part):
                    try:
                        _api.os.replace(part, kp[1])
                    except OSError:
                        _remove(part)
                else:
                    _remove(part)
            if not finished:
                break
            k += 1

    def take(self, t):
        """Последний готовый кадр со временем ≤ t (старые выбрасываются) —
        (время, QImage) или None, если такого ещё нет."""
        got = None
        fr = self._frames
        while fr and fr[0][0] <= t + 1e-4:
            got = fr.popleft()
        return got

    def buffered(self):
        return len(self._frames)

    def play_done(self):
        return self._play_done and not self._frames

    def stop(self):
        self._play_gen += 1
        _kill(self._play_proc)
        self._play_proc = None
        th = self._play_thread
        if th is not None and th.is_alive():
            th.join(timeout=3)
        self._play_thread = None
        self._frames.clear()

    # ── Кэш на паузе ─────────────────────────────────────────────────────────
    def fill(self, t):
        """Дорисовать кэш кусков фоном: от куска с t вперёд, потом с начала."""
        self.stop_fill()
        plan = self.plan()
        if plan is None or plan.n_frames <= 0:
            return
        self._fill_gen += 1
        th = _api.threading.Thread(target=self._fill_loop, args=(plan, t, self._fill_gen),
                                   daemon=True)
        self._fill_thread = th
        th.start()

    def _fill_loop(self, plan, t, gen):
        try:
            self._fill_run(plan, t, gen)
        except Exception as e:
            self.failed.emit(str(e))

    def _fill_run(self, plan, t, gen):
        _api.os.makedirs(cache_dir(), exist_ok=True)
        ks = list(plan.chunks())
        first = max(0, min(len(ks) - 1, int(t * plan.fps) // plan.chunk)) if ks else 0
        order = ks[first:] + ks[:first]
        done = sum(1 for k in ks if plan.ready(k))
        self.cacheProgress.emit(done, len(ks))
        for k in order:
            if gen != self._fill_gen:
                return
            kp = plan.key(k)
            if kp is None or _api.os.path.isfile(kp[1]):
                continue
            f0, f1 = plan.span(k)
            src = _graph(plan.p, f0, f1)
            if src is None or not src.video:
                continue
            part = kp[1] + f".fill{gen}.mp4"
            gfile = _graph_file(src.graph)
            cmd = ([_api.FFMPEG, "-hide_banner", "-v", "error", "-nostdin"] + src.input_args()
                   + ["-/filter_complex", gfile, "-map", "[vout]"] + _ENC
                   + ["-f", "mp4", "-y", part])
            try:
                proc = _api.subprocess.Popen(cmd, stdin=_api.subprocess.DEVNULL,
                                             stdout=_api.subprocess.DEVNULL,
                                             stderr=_api.subprocess.DEVNULL,
                                             creationflags=_api.CREATE_NO_WINDOW
                                             | getattr(_api.subprocess,
                                                       "BELOW_NORMAL_PRIORITY_CLASS", 0))
            except OSError:
                _remove(gfile)
                return
            self._fill_proc = proc
            rc = proc.wait()
            _remove(gfile)
            if gen != self._fill_gen or rc != 0:
                _remove(part)
                if gen != self._fill_gen:
                    return
                continue
            try:
                _api.os.replace(part, kp[1])
            except OSError:
                _remove(part)
                continue
            done += 1
            self.cacheProgress.emit(done, len(ks))

    def stop_fill(self):
        self._fill_gen += 1
        _kill(self._fill_proc)
        self._fill_proc = None

    def shutdown(self):
        self._still_req = None
        self.stop()
        self.stop_fill()
