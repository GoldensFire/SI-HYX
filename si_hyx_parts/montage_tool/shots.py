# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Планы видеофайла: границы, движение, акценты. Public namespace: montage_tool.

Один проход ffmpeg (декод программный: на iGPU d3d11va с копией кадров
обратно медленнее) даёт два выхода: каждый кадр 320 px в RGB (труба) и
кадры 640 px 4 раза в секунду в JPEG (ключевые кадры для зрения и листов);
HDR10 сводится в SDR, как в просмотре (hdr_tonemap.rgb_decode_filter), уже
после уменьшения. На кадрах 320 px — scdet ffmpeg (метаданные в файл),
миниатюры 48×27 для TransNetV2 (MIT, ONNX; окно 100 кадров, шаг 50,
средние 50 предсказаний), повторы кадров (анимация «на двойках», как
mpdecimate — разность меньше порога), движение — DIS-поток OpenCV между
разными кадрами: среднее, общий сдвиг (медиана — камера) и остаток
(движение в кадре). Белые и чёрные вспышки не режут план (кадры по обе
стороны похожи), растворение (многокадровый выход TransNetV2) — отрезок
перехода. Время — номер кадра / fps (CFR)."""
import math
import threading

import numpy as np

import montage_tool as _api

LO_W = 320                         # кадр для движения и scdet
TN_W, TN_H = 48, 27                # вход TransNetV2
SAMPLE_FPS = 4                     # частота ключевых кадров 640 px
SAMPLE_W = 640
CUT_P = 0.5                        # порог одиночного выхода TransNetV2
TRANSITION_P = 0.5                 # порог многокадрового (растворение)
MIN_TRANSITION_FRAMES = 4
# Средняя разность 160×90 (0…255) ниже — «тот же кадр»: повтор рисунка даёт
# 0,00–0,03 (у HEVC с зерном до ~0,2), новая фаза анимации — от 0,4.
DUP_DIFF = 0.3
STATIC_MOTION = 0.008              # движение (доля ширины в секунду): ниже — статичный план (медленная панорама ~0,02)
SCDET_STRONG = 30.0
QUIET_DIFF = 2.5                   # разность соседних кадров ниже — не рез (на Majo 01 резы совпали и при 6)
QUIET_SCDET = 6.0


# ── Декод ────────────────────────────────────────────────────────────────────
def video_props(path):
    """(ширина, высота как на экране, fps, длина, кадров) первого видеопотока."""
    try:
        info = _api.media_probe.probe_media(path)
    except _api.media_probe.ProbeError as e:
        raise _api.ToolError("probe_failed", f"{path}: {e}") from e
    clip = info.get("clip") or {}
    w, h = int(clip.get("width") or 0), int(clip.get("height") or 0)
    fps = float(clip.get("fps") or 0.0)
    dur = float(clip.get("src_duration") or info.get("duration") or 0.0)
    if not clip.get("has_video") or clip.get("is_image") or w <= 0 or h <= 0 or fps <= 0:
        raise _api.ToolError("bad_media", f"нет видео: {path}")
    return w, h, fps, dur, int(round(dur * fps))


def _chain(path, w, h):
    rgb = _api.hdr_tonemap.rgb_decode_filter(path, _api.escape_filter_path, "rgb24")
    return f"scale={w}:{h}:flags=area," + (rgb or "format=rgb24")


class FramePass:
    """ffmpeg: кадры lo_w×lo_h RGB в трубу, JPEG 640 px в sample_dir, оценки
    scdet в файл. Итерация — numpy-кадры по порядку."""

    def __init__(self, path, sample_dir, ctl, scdet_file, start=None, duration=None):
        self.path = str(path)
        self.w, self.h, self.fps, self.duration, self.frames_est = video_props(path)
        self.lo_w = LO_W
        self.lo_h = max(2, int(round(LO_W * self.h / self.w / 2)) * 2)
        sw = SAMPLE_W
        sh = max(2, int(round(sw * self.h / self.w / 2)) * 2)
        self.sample_dir = sample_dir
        self.scdet_file = scdet_file
        self.ctl = ctl
        meta = _api.escape_filter_path(scdet_file)
        graph = (f"[0:v:0]split=2[a][b];"
                 # scdet без sc_pass: дальше идут все кадры (sc_pass=1 пропускал
                 # только смены сцены, и вывод CFR дублировал их до полной частоты).
                 f"[a]scale={self.lo_w}:{self.lo_h}:flags=area,scdet=threshold=8,"
                 f"metadata=mode=print:file='{meta}',"
                 f"{_chain(self.path, self.lo_w, self.lo_h).split(',', 1)[1]}[lo];"
                 f"[b]fps={SAMPLE_FPS},{_chain(self.path, sw, sh)}[hi]")
        win = ((["-ss", f"{float(start):.3f}"] if start else [])
               + (["-t", f"{float(duration):.3f}"] if duration else []))
        self.cmd = [_api.FFMPEG, "-v", "error", "-nostdin"] + win + ["-i", self.path,
                    "-filter_complex", graph, "-map", "[lo]", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "pipe:1", "-map", "[hi]", "-q:v", "3", "-start_number", "0", "-f", "image2",
                    _api.os.path.join(sample_dir, "%06d.jpg")]

    def __iter__(self):
        size = self.lo_w * self.lo_h * 3
        proc = _api.subprocess.Popen(self.cmd, stdin=_api.subprocess.DEVNULL,
                                     stdout=_api.subprocess.PIPE, stderr=_api.subprocess.PIPE,
                                     creationflags=_api.CREATE_NO_WINDOW, bufsize=size * 8)
        err = []
        t = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
        t.start()
        try:
            while True:
                buf = proc.stdout.read(size)
                if len(buf) < size:
                    break
                yield np.frombuffer(buf, np.uint8).reshape(self.lo_h, self.lo_w, 3)
                if self.ctl.stop():
                    raise _api.ToolError("cancelled", "отменено файлом отмены")
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            t.join(timeout=5)
        if proc.returncode not in (0, None) and not self.ctl.stop():
            tail = (err[0] if err else b"").decode("utf-8", "replace").strip().splitlines()[-10:]
            raise _api.ToolError("ffmpeg_failed", f"декод {self.path}: код {proc.returncode}",
                                 detail="\n".join(tail))


def read_scdet(path):
    """{кадр: оценка 0…100} из файла metadata=print (кадр — по порядку)."""
    out, n = {}, -1
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("frame:"):
                    try:
                        n = int(line.split()[0].split(":")[1])
                    except (IndexError, ValueError):
                        n += 1
                elif "lavfi.scd.score=" in line and n >= 0:
                    try:
                        out[n] = float(line.split("=", 1)[1])
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


# ── Покадровые признаки ──────────────────────────────────────────────────────
class FrameStats:
    """Признаки кадров по мере декода: миниатюры TransNetV2, яркость,
    насыщенность, разность с прошлым, поток DIS (среднее, общий сдвиг,
    остаток) — у повтора кадра движение нулевое."""

    def __init__(self, n_hint):
        import cv2
        self.cv2 = cv2
        cap = max(1024, int(n_hint * 1.05) + 64)
        self.tn = np.zeros((cap, TN_H, TN_W, 3), np.uint8)
        self.cols = {k: np.zeros(cap, np.float32) for k in
                     ("luma", "sat", "diff", "flow", "cam", "obj")}
        self.n = 0
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST)
        self.prev_small = None
        self.prev_gray = None

    def _grow(self):
        cap = len(self.tn) * 2
        self.tn = np.concatenate([self.tn, np.zeros_like(self.tn)])[:cap]
        for k, v in self.cols.items():
            self.cols[k] = np.concatenate([v, np.zeros_like(v)])[:cap]

    def add(self, rgb):
        cv2 = self.cv2
        if self.n >= len(self.tn):
            self._grow()
        i = self.n
        self.tn[i] = cv2.resize(rgb, (TN_W, TN_H), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        small = cv2.resize(gray, (160, max(2, gray.shape[0] * 160 // gray.shape[1])),
                           interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(cv2.resize(rgb, (80, max(2, rgb.shape[0] * 80 // rgb.shape[1]))),
                           cv2.COLOR_RGB2HSV)
        c = self.cols
        c["luma"][i] = float(small.mean())
        c["sat"][i] = float(hsv[..., 1].mean())
        if self.prev_small is not None:
            d = float(cv2.absdiff(small, self.prev_small).mean())
            c["diff"][i] = d
            if d >= DUP_DIFF:
                flow = self.dis.calc(self.prev_gray, gray, None)
                fx, fy = flow[..., 0], flow[..., 1]
                gx, gy = float(np.median(fx)), float(np.median(fy))
                c["flow"][i] = float(np.sqrt(fx * fx + fy * fy).mean())
                c["cam"][i] = math.hypot(gx, gy)
                c["obj"][i] = float(np.sqrt((fx - gx) ** 2 + (fy - gy) ** 2).mean())
                self.prev_gray = gray
        else:
            self.prev_gray = gray
        self.prev_small = small
        self.n += 1

    def arrays(self):
        return self.tn[:self.n], {k: v[:self.n] for k, v in self.cols.items()}


# ── TransNetV2 ───────────────────────────────────────────────────────────────
def _quiet(tn, diff, scdet, a, b):
    """В кадрах [a, b) нет ни реза, ни растворения: соседние кадры почти
    одинаковы, scdet молчит и начало с концом похожи по цвету."""
    if b - a < 2:
        return True
    if float(diff[a:b].max()) >= QUIET_DIFF:
        return False
    if any(scdet.get(f, 0.0) >= QUIET_SCDET for f in range(a, b)):
        return False
    return float(_hist(tn[a]) @ _hist(tn[b - 1])) >= 0.95


def transnet(tn, session, ctl, diff=None, scdet=None):
    """(одиночный, многокадровый) — вероятности на каждый кадр. Окно, чья
    середина (с запасом в 3 кадра) тихая (_quiet), не считается: у
    TransNetV2 на CPU ~0,4 с на окно, а спокойных окон в серии около трети.
    (вероятности, сколько окон пропущено, сколько всего)."""
    n = len(tn)
    if n == 0:
        return np.zeros(0), np.zeros(0), 0, 0
    end_pad = 25 + 50 - (n % 50 if n % 50 else 50)
    frames = np.concatenate([np.repeat(tn[:1], 25, 0), tn, np.repeat(tn[-1:], end_pad, 0)])
    name = session.get_inputs()[0].name
    one, many = [], []
    skipped = total = 0
    for ptr in range(0, len(frames) - 99, 50):
        ctl.check()
        total += 1
        a, b = max(0, ptr - 3), min(n, ptr + 53)        # середина окна в кадрах файла
        if diff is not None and _quiet(tn, diff, scdet or {}, a, b):
            one.append(np.zeros(50, np.float32))
            many.append(np.zeros(50, np.float32))
            skipped += 1
            continue
        x = frames[ptr:ptr + 100].astype(np.float32)[None]
        p, q = session.run(None, {name: x})
        one.append(p[0, 25:75, 0])
        many.append(q[0, 25:75, 0])
    return np.concatenate(one)[:n], np.concatenate(many)[:n], skipped, total


class TransNetStream(threading.Thread):
    """TransNetV2 одновременно с декодом: окно (середина — 50 кадров с
    центра c, края — по 25 кадров, у начала и конца файла — повтор
    крайнего кадра, как в transnet) считается, как только его кадры есть в
    FrameStats; декод и Python-обработка кадра занимают не все ядра.
    finish() — кадров больше не будет; result() — как у transnet."""

    def __init__(self, stats, session, ctl):
        super().__init__(daemon=True)
        self.stats, self.session, self.ctl = stats, session, ctl
        self._final = threading.Event()
        self.error = None
        self.one, self.many = [], []
        self.skipped = self.total = 0

    def finish(self):
        self._final.set()
        self.join()
        if self.error is not None:
            raise self.error
        n = self.stats.n
        if not self.one:
            return np.zeros(0), np.zeros(0), 0, 0
        return (np.concatenate(self.one)[:n], np.concatenate(self.many)[:n],
                self.skipped, self.total)

    def run(self):
        try:
            name = self.session.get_inputs()[0].name
            c = 0
            while True:
                if self.ctl.stop():
                    return
                final = self._final.is_set()
                n = self.stats.n
                if final and c >= n:
                    break
                if not final and n < c + 75 + 1:
                    if self.ctl.stop():
                        return
                    self._final.wait(0.05)
                    continue
                tn = self.stats.tn
                diff = self.stats.cols["diff"]
                self.total += 1
                if _quiet(tn, diff, {}, max(0, c - 3), min(n, c + 53)):
                    self.one.append(np.zeros(50, np.float32))
                    self.many.append(np.zeros(50, np.float32))
                    self.skipped += 1
                else:
                    idx = np.clip(np.arange(c - 25, c + 75), 0, n - 1)
                    x = tn[idx].astype(np.float32)[None]
                    p, q = self.session.run(None, {name: x})
                    self.one.append(p[0, 25:75, 0])
                    self.many.append(q[0, 25:75, 0])
                c += 50
        except Exception as e:           # noqa: BLE001 — отдаётся в finish()
            self.error = e


def _hist(img):
    h = np.histogramdd(img.reshape(-1, 3) // 32, bins=(8, 8, 8), range=((0, 8),) * 3)[0].ravel()
    return h / (np.linalg.norm(h) + 1e-9)


def find_shots(p_one, p_many, scdet, tn, luma):
    """Планы [(начало, конец, вид)] в кадрах (включительно): вид 'shot' или
    'transition' (растворение); и вспышки [(кадр, сила)], не ставшие резом."""
    n = len(p_one)
    cut = p_one > CUT_P
    for f, score in scdet.items():
        # Сильная смена scdet при неуверенной сети — тоже рез (кадр f — первый
        # нового плана, у TransNetV2 рез отмечен последним кадром старого).
        if score >= SCDET_STRONG and 0 < f < n and p_one[f - 1] > 0.15:
            cut[f - 1] = True
    flashes = []
    idx = np.flatnonzero(cut)
    # Подряд идущие отметки — один рез (последняя).
    cuts = [int(i) for k, i in enumerate(idx) if k + 1 == len(idx) or idx[k + 1] != i + 1]
    keep = []
    for i in cuts:
        a, b = max(0, i - 3), min(n - 1, i + 4)
        if b - a < 4:
            keep.append(i)
            continue
        same = float(_hist(tn[a]) @ _hist(tn[b]))
        around = luma[max(0, i - 1):min(n, i + 3)]
        base = 0.5 * (float(luma[a]) + float(luma[b]))
        jump = max(float(around.max()) - base, base - float(around.min()))
        if same > 0.9 and jump > 40:
            flashes.append((i + 1, min(1.0, jump / 120.0)))     # вспышка, не рез
        else:
            keep.append(i)
    trans = []
    many = p_many > TRANSITION_P
    k = 0
    while k < n:
        if many[k]:
            j = k
            while j + 1 < n and many[j + 1]:
                j += 1
            if j - k + 1 >= MIN_TRANSITION_FRAMES:
                trans.append((k, j))
            k = j + 1
        else:
            k += 1
    bounds = sorted({0, n} | {i + 1 for i in keep if 0 < i + 1 < n})
    shots = []
    for a, b in zip(bounds, bounds[1:]):
        shots.append([a, b - 1, "shot"])
    # Растворение: свой отрезок, резы внутри него убираются.
    for ta, tb in trans:
        out = []
        for a, b, kind in shots:
            if b < ta or a > tb:
                out.append([a, b, kind])
                continue
            if a < ta:
                out.append([a, ta - 1, kind])
            if b > tb:
                out.append([tb + 1, b, kind])
        out.append([ta, tb, "transition"])
        shots = sorted(out)
    merged = []
    for s in shots:                           # пустые и обрезки короче 2 кадров
        if s[1] < s[0]:
            continue
        if merged and s[1] - s[0] < 1 and s[2] == "shot" and merged[-1][2] == "shot":
            merged[-1][1] = s[1]
            continue
        merged.append(s)
    return [tuple(s) for s in merged], flashes


def shot_features(a, b, fps, cols, flashes, lo_w):
    """Признаки плана [a, b] кадров: движение (доля ширины в секунду),
    камера и движение в кадре, повторы, статичность, яркость, акценты."""
    sl = slice(a, b + 1)
    # Разность и поток первого кадра — с прошлым планом (через рез): вне плана.
    ml = slice(a + 1, b + 1)
    diff, flow = cols["diff"][ml], cols["flow"][ml]
    moving = diff >= DUP_DIFF
    dup = float(1.0 - moving.mean()) if b > a else 0.0
    scale = fps / lo_w
    f = flow[moving] * scale if moving.any() else np.zeros(1)
    # Повторы кадров (двойки) дают ноль между рисунками — средняя скорость
    # по времени, а не по разным кадрам.
    span = max(1, b - a)
    mean_t = float(flow.sum() * scale / span)
    cam = float(cols["cam"][ml].sum() * scale / span)
    obj = float(cols["obj"][ml].sum() * scale / span)
    luma = cols["luma"][sl]
    acc = []
    for fr, s in flashes:
        if a <= fr <= b:
            acc.append({"t": round(fr / fps, 3), "strength": round(s, 3), "kind": "flash"})
    if b - a >= 4:
        dl = np.diff(luma)
        for i in np.flatnonzero(dl > 35):
            acc.append({"t": round((a + i + 1) / fps, 3),
                        "strength": round(min(1.0, float(dl[i]) / 100.0), 3), "kind": "flash"})
        m = flow * scale
        med = float(np.median(m[moving])) if moving.any() else 0.0
        thr = max(0.25, 3.0 * med)
        for i in range(1, len(m) - 1):
            if m[i] > thr and m[i] >= m[i - 1] and m[i] >= m[i + 1]:
                acc.append({"t": round((a + 1 + i) / fps, 3),
                            "strength": round(min(1.0, float(m[i]) / (thr * 3)), 3),
                            "kind": "motion"})
    acc = sorted(acc, key=lambda x: -x["strength"])[:6]
    acc.sort(key=lambda x: x["t"])
    return {"motion": round(mean_t, 4), "motion_peak": round(float(np.percentile(f, 95)), 4),
            "camera": round(cam, 4), "object": round(obj, 4), "dup_ratio": round(dup, 3),
            "static": bool(mean_t < STATIC_MOTION), "brightness": round(float(luma.mean()) / 255, 3),
            "saturation": round(float(cols["sat"][sl].mean()) / 255, 3), "accents": acc}
