# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Карта песни для монтажа под музыку. Public namespace: montage_tool.

Доли и сильные доли — Beat This! (CPJKU, MIT; без DBN) в Python генератора
(music_worker.py), время каждой доли уточняется по своей огибающей начала
звука (сетка 10 мс, analysis.onset_envelope). Без Python генератора — DSP
analysis (темп автокорреляцией, биты динамическим программированием).

Из долей: размер (доли между сильными), такты с номером доли, темп по
тактам и его смены, фразы по 4 такта (8 — пара фраз). Удары — барабаны
HTDemucs (4 стема той же модели, что у караоке) → начала звука по полосам:
бочка 35–130 Гц, малый барабан (середина и шум 1,5–6 кГц), тарелки 7–12 кГц.
Части песни — признаки по тактам (хрома и MFCC librosa в обработчике,
без него — свои на numpy): матрица самоподобия → новизна (шахматное ядро)
+ скачки энергии и вокала → границы динамическим программированием на
сетке фраз; повторы гармонии и тембра → группы A, B…; подписи intro, verse,
build, chorus, drop, bridge, outro — эвристикой по энергии, повторам и
вокалу. Места для резов — доли с приоритетом (начало фразы > сильная доля >
доля > слабая; удар барабана повышает), плотность — по энергии части.

Кэш — ~/.cache/si-hyx-montage/music/<хэш звука>/: доли, стемы, признаки и
готовая карта; время в карте — время звука (файла от t0)."""
import hashlib
import math
import re
import time
import wave

import numpy as np

import montage_tool as _api
from si_hyx_parts.montage_tool import analysis as _an

MUSIC_VERSION = 1
SONG_RATE = 44100                    # звук для Demucs и Beat This!
BEAT_MODELS = ("small0", "final0")
DEFAULT_BEAT_MODEL = "final0"        # на клик-треке со сменой темпа: 99 % долей против 82 % у small0
MUSIC_KINDS = ("beat", "downbeat", "phrase", "section", "kick", "snare", "hat", "slot")
# Маркеры, которые music --write кладёт в проект без --kinds: тарелок в песне
# тысячи — шкала ими зарастает.
MUSIC_WRITE_KINDS = ("beat", "downbeat", "phrase", "section", "kick", "snare", "slot")
SECTION_LABELS = ("intro", "verse", "build", "chorus", "drop", "bridge", "outro")
PHRASE_BARS = 4
_PACKAGES = (["beat_this"], ["beat-this==1.1.0"])
_WORKER = _api.os.path.join(_api.os.path.dirname(_api.os.path.abspath(__file__)),
                            "music_worker.py")
_REFINE_FRAMES = 5                   # ±50 мс: доля Beat This! — на сетке 20 мс и бывает раньше на 2 кадра
_PAUSE_S = 0.6                       # тишина длиннее — пауза песни
# Барабаны: окно 512 (21 мс) — у середины и верха, 1024 — у бочки (частоты).
_DRUM_RATE = 24000
_DRUM_HOP = 240
_DRUM_BANDS = {"low": (35.0, 130.0, 1024), "mid": (150.0, 1000.0, 512),
               "noise": (1500.0, 6000.0, 512), "high": (7000.0, 11500.0, 512)}
# Пик потока полосы позже начала удара на полокна вперёд минус время
# нарастания; замер на синтетике (song_map, клик-трек) — см. CODE_MAP.
_DRUM_LAG = {"low": 0.010, "mid": 0.0, "noise": 0.0, "high": 0.0}


# ── Звук и кэш ───────────────────────────────────────────────────────────────
def _audio_key(audio):
    return hashlib.sha256(np.ascontiguousarray(audio, np.float32).tobytes()).hexdigest()[:24]


def _read_wav(path):
    """16-битный WAV → float32 (моно — среднее каналов), частота."""
    with wave.open(str(path), "rb") as w:
        rate, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x[: len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
    return x, rate


def _db_grid(x, rate):
    """Громкость (dBFS) на сетке 10 мс, окно 30 мс, любой частоты."""
    hop = max(1, rate // 100)
    if len(x) < 3 * hop:
        return np.zeros(0)
    fr = np.lib.stride_tricks.sliding_window_view(x, 3 * hop)[::hop]
    return 10 * np.log10(np.mean(fr.astype(np.float64) ** 2, axis=1) + 1e-12)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return _api.json.load(f)


def _save_json(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _api.json.dump(obj, f, ensure_ascii=False,
                       default=lambda o: o.item() if hasattr(o, "item") else str(o))
    _api.os.replace(tmp, path)


class _Song:
    """Звук песни и его рабочая папка: mix.wav для обработчика пишется по
    требованию и удаляется в конце (close)."""

    def __init__(self, stereo, mono, ctl):
        self.stereo, self.mono, self.ctl = stereo, mono, ctl
        self.duration = len(mono) / _an.SR
        self.key = _audio_key(stereo)
        self.dir = _api.cache_dir("music", self.key)
        self._wav = ""

    def wav(self):
        if not self._wav:
            self._wav = _api.os.path.join(self.dir, "mix.wav")
            _an._write_wav(self.stereo, self._wav, SONG_RATE)
        return self._wav

    def close(self):
        if self._wav and _api.os.path.exists(self._wav):
            _api.os.remove(self._wav)
        self._wav = ""


# ── Доли ─────────────────────────────────────────────────────────────────────
def _ml_ready(python, ctl):
    """Python генератора с Beat This! (пакет ставится по требованию)."""
    if not _api.os.path.isfile(python):
        return False
    _api.ensure_packages(python, *_PACKAGES, ctl=ctl)
    return True


def _beats_ml(song, model, python):
    out = _api.os.path.join(song.dir, f"beats-{model}.json")
    if not _api.os.path.isfile(out):
        ckpt = _api.asset(f"beat_this/{model}.ckpt", song.ctl)
        song.ctl.stage("beats", model=model)
        _api.run_worker(python, _WORKER, ["beats", song.wav(), out, "--checkpoint", ckpt],
                        song.ctl, timeout=900, stage="beats")
    data = _load_json(out)
    return [float(t) for t in data.get("beats", [])], [float(t) for t in data.get("downbeats", [])]


def _beats_dsp(env, bass):
    bpm = _an.estimate_tempo(env)
    idx = _an.track_beats(env, bpm)
    if not idx:
        return [], []
    phase = _an.downbeat_phase(bass, idx)
    times = [i * _an.HOP_S + _an.ONSET_LAG_S for i in idx]
    return times, times[phase::4]


def refine_times(times, env, radius=_REFINE_FRAMES, floor=0.06):
    """Время каждой доли — по пику своей огибающей начала звука в ±radius
    кадров (10 мс): из местных максимумов выше floor — самый сильный с
    поправкой на расстояние (гаусс 40 мс), уточнение параболой; пика нет —
    как было. (время, сила 0…1)."""
    out = []
    n = len(env)
    for t in times:
        i = int(round((t - _an.ONSET_LAG_S) / _an.HOP_S))
        best, score = None, 0.0
        for j in range(max(1, i - radius), min(n - 1, i + radius + 1)):
            v = float(env[j])
            if v >= floor and env[j] >= env[j - 1] and env[j] >= env[j + 1]:
                sc = v * math.exp(-0.5 * ((j - i) / 4.0) ** 2)
                if sc > score:
                    best, score = j, sc
        if best is None:
            out.append((t, float(env[min(max(i, 0), n - 1)]) if n else 0.0))
            continue
        j = best
        y0, y1, y2 = float(env[j - 1]), float(env[j]), float(env[j + 1])
        den = y0 - 2 * y1 + y2
        frac = 0.5 * (y0 - y2) / den if den < 0 else 0.0
        out.append(((j + max(-0.5, min(0.5, frac))) * _an.HOP_S + _an.ONSET_LAG_S, y1))
    return out


def _nearest(arr, t):
    i = int(np.searchsorted(arr, t))
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(arr) and (best is None or abs(arr[j] - t) < abs(arr[best] - t)):
            best = j
    return best


def build_bars(beat_t, down_t):
    """Размер и такты по долям и сильным долям: (размер, индексы долей —
    начал тактов, номер доли в такте для каждой доли). Пропущенные сильные
    доли (такт в 2 размера) достраиваются, затакт — доли до первого такта."""
    nb = len(beat_t)
    if nb == 0:
        return 4, [], []
    bt = np.asarray(beat_t)
    starts = set()
    for d in down_t:
        j = _nearest(bt, d)
        if j is not None and abs(bt[j] - d) < 0.08:
            starts.add(j)
    starts = sorted(starts)
    if len(starts) < 2:
        meter = 4
        starts = list(range(starts[0] if starts else 0, nb, meter))
    else:
        counts = np.diff(starts)
        valid = counts[(counts >= 2) & (counts <= 7)]
        meter = int(np.bincount(valid).argmax()) if len(valid) else 4
        fixed = [starts[0]]
        for a, b in zip(starts, starts[1:]):
            k = b - a
            if k >= 2 * meter and k % meter == 0:
                fixed += list(range(a + meter, b, meter))
            fixed.append(b)
        while fixed[0] - meter >= 0:
            fixed.insert(0, fixed[0] - meter)
        last = fixed[-1]
        while last + meter < nb - 1 and (nb - last) > meter:
            last += meter
            fixed.append(last)
        starts = fixed
    pos = [0] * nb
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else nb
        for j in range(s, end):
            pos[j] = j - s + 1
    first = starts[0] if starts else nb
    for j in range(first):                    # затакт: доли до первого такта
        pos[j] = meter - (first - j) + 1
    return meter, starts, pos


def tempo_curve(beat_t, starts, meter):
    """Темп каждого такта (BPM по его долям) и смены темпа: отклонение > 4 %
    от темпа отрезка два такта подряд начинает новый отрезок."""
    if len(beat_t) < 2:
        return [], [], 0.0
    bt = np.asarray(beat_t)
    ibi = np.diff(bt)
    bpm_bar = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(bt) - 1
        e = min(e, len(bt) - 1)
        if e > s:
            bpm_bar.append(60.0 / float(np.median(ibi[s:e])))
        else:
            bpm_bar.append(60.0 / float(np.median(ibi)))
    bpm = np.asarray(bpm_bar, float)
    if len(bpm) >= 5:
        # Медиана по пяти тактам: лишняя доля в сбивке барабанов (Beat This!
        # ставит шестнадцатые) не даёт ложной смены, ступенька темпа остаётся.
        pad = np.pad(bpm, 2, mode="edge")
        bpm = np.median(np.lib.stride_tricks.sliding_window_view(pad, 5), axis=1)
    changes, seg, i = [], 0, 1
    tol = math.log(1.04)

    def far(a, b):
        return abs(math.log(a / b)) > tol

    while i < len(bpm):
        ref = float(np.median(bpm[seg:i]))
        if far(bpm[i], ref) and (i + 1 >= len(bpm) or far(bpm[i + 1], ref)):
            # Переходные такты (смесь двух темпов) пропускаются: новый
            # отрезок — с такта, после которого темп держится.
            j = i
            while j + 1 < len(bpm) and far(bpm[j], bpm[j + 1]):
                j += 1
            new = float(np.median(bpm[j:j + 2]))
            seg = j
            if far(new, ref):
                changes.append({"bar": j + 1, "t": round(float(bt[starts[j]]), 3),
                                "bpm": round(new, 2), "ratio": round(new / ref, 3)})
            i = j + 1
        else:
            i += 1
    durations = np.diff(np.append(bt[starts], bt[-1])) if starts else np.ones(1)
    order = np.argsort(bpm)
    cum = np.cumsum(durations[order])
    main = float(bpm[order][int(np.searchsorted(cum, cum[-1] / 2))]) if len(cum) else 0.0
    return [round(float(v), 2) for v in bpm], changes, round(main, 2)


# ── Барабаны ─────────────────────────────────────────────────────────────────
def _stems(song, python):
    stem_dir = _api.os.path.join(song.dir, "stems")
    drums = _api.os.path.join(stem_dir, "drums.wav")
    vocals = _api.os.path.join(stem_dir, "vocals.wav")
    if not (_api.os.path.isfile(drums) and _api.os.path.isfile(vocals)):
        song.ctl.stage("stems", engine="htdemucs")
        _api.run_worker(python, _WORKER, ["stems", song.wav(), stem_dir], song.ctl,
                        timeout=1800, stage="stems")
    return drums, vocals


def _band_flux(x, rate, lo, hi, win):
    """Поток (рост логарифма энергии) полосы lo…hi Гц на сетке 10 мс и
    уровень полосы (dB)."""
    if len(x) < win:
        return np.zeros(0, np.float32), np.zeros(0, np.float32)
    xp = np.pad(x, (win // 2, win // 2), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(xp, win)[::_DRUM_HOP]
    a, b = max(1, int(lo * win / rate)), max(2, int(math.ceil(hi * win / rate)) + 1)
    spec = np.fft.rfft(frames * np.hanning(win).astype(np.float32), axis=1)[:, a:b]
    level = 10.0 * np.log10(np.mean(np.abs(spec) ** 2, axis=1) + 1e-10)
    flux = np.maximum(level - np.concatenate(([level[0]], level[:-1])), 0.0)
    return flux.astype(np.float32), level.astype(np.float32)


def _peaks(v, thresh, gap):
    """Пики: максимум в ±3 кадрах, выше thresh и местного среднего ±100 мс."""
    if len(v) < 3:
        return []
    mx = np.lib.stride_tricks.sliding_window_view(np.pad(v, 3, mode="edge"), 7).max(axis=1)
    avg = _an._moving_mean(v, 21)
    cand = np.nonzero((v >= mx) & (v >= thresh) & (v >= avg + 0.04))[0]
    out, last = [], -gap - 1
    for i in cand:
        if i - last > gap:
            out.append(int(i))
            last = i
    return out


def drum_hits(x, rate=_DRUM_RATE):
    """Удары барабанов дорожки x (моно rate): {'kick'|'snare'|'hat': [(t, сила,
    'crash'|'')]}. Начало удара — пик потока полосы; вид — по уровням полос
    на пике относительно их громких мест (95-й процентиль): у бочки низ не
    тише середины, у малого барабана середина и шум громче низа, тарелка —
    верх без шума малого барабана. Сила — поток полосы (0…1)."""
    flux, rel = {}, {}
    for name, (lo, hi, win) in _DRUM_BANDS.items():
        f, lv = _band_flux(x, rate, lo, hi, win)
        top = float(np.percentile(f, 99.5)) if len(f) else 1.0
        flux[name] = np.clip(f / (top or 1.0), 0.0, 1.0)
        rel[name] = lv - (float(np.percentile(lv, 95)) if len(lv) else 0.0)
    n = min(len(v) for v in flux.values())
    out = {"kick": [], "snare": [], "hat": []}
    if n == 0:
        return out
    fl = {k: v[:n] for k, v in flux.items()}
    rl = {k: v[:n] for k, v in rel.items()}
    hop_s = _DRUM_HOP / rate

    def lvl(name, i):                         # уровень полосы на атаке (3 кадра)
        return float(rl[name][i:i + 3].max())

    def fmax(name, i, r=2):
        return float(fl[name][max(0, i - r):i + r + 1].max())

    for i in _peaks(fl["low"], 0.18, 5):
        if lvl("low", i) >= -9.0 and lvl("low", i) >= lvl("mid", i) - 3.0:
            out["kick"].append((i * hop_s + _DRUM_LAG["low"], float(fl["low"][i]), ""))
    snare_idx = []
    for i in _peaks(np.maximum(fl["mid"], fl["noise"]), 0.2, 5):
        m, z, lo = lvl("mid", i), lvl("noise", i), lvl("low", i)
        if m >= -9.0 and z >= -12.0 and max(m, z) >= lo + 3.0:
            snare_idx.append(i)
            out["snare"].append((i * hop_s + _DRUM_LAG["noise"],
                                 float(max(fmax("mid", i), fmax("noise", i))), ""))
    for i in _peaks(fl["high"], 0.18, 4):
        h = lvl("high", i)
        if h < -12.0:
            continue
        if any(abs(i - j) <= 2 for j in snare_idx) and h < lvl("noise", i) + 3.0:
            continue                          # шум малого барабана, а не тарелка
        tail = rl["high"][i + 30:i + 31]      # через 300 мс уровень почти тот же — тарелка
        crash = bool(len(tail)) and float(tail[0]) > h - 6.0
        out["hat"].append((i * hop_s + _DRUM_LAG["high"], float(fl["high"][i]),
                           "crash" if crash else ""))
    return out


# ── Признаки по долям ────────────────────────────────────────────────────────
def _features_ml(song, python, beat_t, model, vocals=""):
    out = _api.os.path.join(song.dir, f"features-{model}{'-v' if vocals else ''}.json")
    if not _api.os.path.isfile(out):
        grid = _api.os.path.join(song.dir, f"grid-{model}.json")
        _save_json({"beats": [round(t, 4) for t in beat_t]}, grid)
        song.ctl.stage("features", engine="librosa")
        args = ["features", song.wav(), grid, out] + (["--vocals", vocals] if vocals else [])
        _api.run_worker(python, _WORKER, args, song.ctl, timeout=900, stage="features")
    return _load_json(out)["rows"]


def _dct_matrix(n_in, n_out):
    k = np.arange(n_out)[:, None]
    m = np.arange(n_in)[None, :]
    d = np.cos(np.pi * k * (2 * m + 1) / (2 * n_in)) * math.sqrt(2.0 / n_in)
    d[0] /= math.sqrt(2.0)
    return d.astype(np.float32)


def features_numpy(x, beat_t):
    """Признаки по долям без librosa (моно 16 кГц): хрома по бинам STFT
    55 Гц…2 кГц, MFCC (DCT логарифма 40 лог-полос), громкость, яркость,
    сила начала звука — те же поля, что у обработчика."""
    sr, win = _an.SR, 2048
    if len(x) < win or not beat_t:
        return []
    xp = np.pad(x, (win // 2, win // 2), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(xp, win)[::_an.HOP]
    mag = np.abs(np.fft.rfft(frames * np.hanning(win).astype(np.float32), axis=1))
    freqs = np.arange(mag.shape[1]) * sr / win
    sel = (freqs >= 55) & (freqs <= 2000)
    pc = (np.round(12 * np.log2(freqs[sel] / 440.0)) + 69).astype(int) % 12
    chroma = np.zeros((mag.shape[0], 12), np.float32)
    for c in range(12):
        chroma[:, c] = mag[:, sel][:, pc == c].sum(axis=1)
    chroma /= chroma.max(axis=1, keepdims=True) + 1e-9
    starts = _an._log_bands(win, count=40, lo=40.0, hi=7600.0)
    bands = np.add.reduceat(mag[:, :starts[-1]] ** 2, starts[:-1], axis=1)
    mfcc = np.log(bands + 1e-8) @ _dct_matrix(bands.shape[1], 13).T
    db = 10 * np.log10(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    cent = (mag * freqs).sum(axis=1) / (mag.sum(axis=1) + 1e-9)
    env = _an.onset_envelope(x)
    n = min(len(db), len(env))
    edges = [int(round(t / _an.HOP_S)) for t in beat_t] + [n]
    rows = []
    for a, b in zip(edges[:-1], edges[1:]):
        a, b = max(0, min(a, n - 1)), max(1, min(b, n))
        if b <= a:
            b = a + 1
        rows.append({"chroma": [round(float(v), 4) for v in np.median(chroma[a:b], axis=0)],
                     "mfcc": [round(float(v), 3) for v in mfcc[a:b].mean(axis=0)],
                     "db": round(float(10 * np.log10(np.mean(10 ** (db[a:b] / 10)) + 1e-12)), 2),
                     "centroid": round(float(cent[a:b].mean()), 1),
                     "onset": round(float(env[a:b].mean()), 4)})
    return rows


# ── Части песни ──────────────────────────────────────────────────────────────
def _norm01(v, lo_q=5, hi_q=95):
    v = np.asarray(v, float)
    if not len(v):
        return v
    lo, hi = np.percentile(v, lo_q), np.percentile(v, hi_q)
    return np.clip((v - lo) / (hi - lo), 0.0, 1.0) if hi > lo else np.full(len(v), 0.5)


def _bar_matrix(rows, starts, nbeats):
    """Средние признаки тактов: хрома 12, MFCC 1…12, dB, яркость, начала;
    с вокалом — его хрома (взвешенная громкостью) и громкость."""
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else nbeats
        sub = rows[s:max(e, s + 1)] or rows[-1:]
        bar = {"chroma": np.mean([r["chroma"] for r in sub], axis=0),
               "mfcc": np.mean([r["mfcc"][1:13] for r in sub], axis=0),
               "db": 10 * math.log10(np.mean([10 ** (r["db"] / 10) for r in sub]) + 1e-12),
               "centroid": float(np.mean([r["centroid"] for r in sub])),
               "onset": float(np.mean([r["onset"] for r in sub]))}
        if all("vchroma" in r for r in sub):
            w = np.array([10 ** (r["vdb"] / 10) for r in sub])
            bar["vchroma"] = (np.array([r["vchroma"] for r in sub]) * w[:, None]).sum(axis=0) / (
                w.sum() + 1e-12)
            bar["vdb"] = 10 * math.log10(w.mean() + 1e-12)
        out.append(bar)
    return out


def _cos(X):
    X = np.asarray(X, float)
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    return X @ X.T


def _ssm(bars):
    """Самоподобие тактов: косинус хромы, z-MFCC и — если есть стем вокала
    — хромы вокала (мелодия различает куплет и припев, у которых гармония
    и тембр рока почти одни). Такты без пения: между собой 0,5, с поющими 0."""
    c = _cos([b["chroma"] for b in bars])
    m = np.array([b["mfcc"] for b in bars], float)
    m = (m - m.mean(axis=0)) / (m.std(axis=0) + 1e-9)
    t = (_cos(m) + 1.0) / 2.0
    if not all("vchroma" in b for b in bars):
        return 0.5 * c + 0.5 * t
    vdb = np.array([b["vdb"] for b in bars])
    voiced = vdb > max(-50.0, float(np.percentile(vdb, 95)) - 25.0)
    v = _cos([b["vchroma"] for b in bars])
    v[~voiced, :] = 0.0
    v[:, ~voiced] = 0.0
    v[np.ix_(~voiced, ~voiced)] = 0.5
    return 0.25 * c + 0.35 * t + 0.4 * v


def _novelty(S, half):
    n = len(S)
    if n < 2 * half + 1 or half < 1:
        return np.zeros(n)
    g = np.exp(-0.5 * (np.linspace(-1.5, 1.5, 2 * half)) ** 2)
    sign = np.concatenate([-np.ones(half), np.ones(half)])
    K = np.outer(g, g) * np.outer(sign, sign)
    P = np.pad(S, half, mode="edge")
    nov = np.array([float((K * P[i:i + 2 * half, i:i + 2 * half]).sum()) for i in range(n)])
    nov = np.maximum(nov, 0.0)
    return nov / (nov.max() or 1.0)


def _section_vectors(bars):
    """Признаки тактов для поиска повторов: хрома, z-MFCC и хрома вокала
    (такты без пения — нули), каждая часть единичной длины."""
    def nrm(X):
        X = np.asarray(X, float)
        return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)

    m = np.array([b["mfcc"] for b in bars], float)
    parts = [nrm([b["chroma"] for b in bars]), nrm((m - m.mean(axis=0)) / (m.std(axis=0) + 1e-9))]
    if all("vchroma" in b for b in bars):
        vdb = np.array([b["vdb"] for b in bars])
        v = nrm([b["vchroma"] for b in bars])
        v[vdb < max(-50.0, float(np.percentile(vdb, 95)) - 25.0)] = 0.0
        parts.append(1.3 * v)
    return np.hstack(parts)


def _structure_novelty(X, emb=4, kappa=0.04, sigma=4.0):
    """Новизна по структурным признакам (Serrà и др., 2012): такты со
    своими emb соседями → взаимные k ближайших (k = kappa·n) → матрица
    задержек, размытая по времени, → скачок её строки — смена того, что с
    чем повторяется (граница куплета и припева при одной гармонии)."""
    n = len(X)
    if n < 3 * emb:
        return np.zeros(n)
    E = np.hstack([np.vstack([X[k:], np.repeat(X[-1:], k, axis=0)]) for k in range(emb)])
    D = ((E[:, None, :] - E[None, :, :]) ** 2).sum(-1)
    k = max(2, int(kappa * n))
    R = np.zeros((n, n))
    nn = np.argsort(D, axis=1)[:, 1:k + 1]
    R[np.repeat(np.arange(n), k), nn.ravel()] = 1.0
    R *= R.T
    lag = np.array([np.roll(R[i], -i) for i in range(n)])
    w = np.exp(-0.5 * (np.arange(-int(3 * sigma), int(3 * sigma) + 1) / sigma) ** 2)
    w /= w.sum()
    pad = len(w) // 2
    P = np.stack([np.convolve(np.pad(lag[:, j], pad, mode="edge"), w, mode="valid")
                  for j in range(n)], axis=1)
    c = np.concatenate(([0.0], ((P[1:] - P[:-1]) ** 2).sum(axis=1)))
    return c / (c.max() or 1.0)


def _step(v, w=2):
    """|среднее v после − до| в каждом такте (скачки энергии и вокала)."""
    v = np.asarray(v, float)
    n = len(v)
    out = np.zeros(n)
    for i in range(1, n):
        out[i] = abs(v[i:i + w].mean() - v[max(0, i - w):i].mean())
    return out / (out.max() or 1.0)


def _segment(novelty, n, forced=(), min_len=4, max_len=32, cost=0.35):
    """Начала частей (такты) динамическим программированием: граница —
    новизна минус цена; длина кратна 8/4 тактам — без штрафа/малый штраф."""
    def pen(L):
        if L % 8 == 0:
            p = 0.0
        elif L % 4 == 0:
            p = 0.05
        elif L % 2 == 0:
            p = 0.35
        else:
            p = 0.6
        return p + (0.08 * (L - 16) / 8 if L > 16 else 0.0)

    bonus = np.zeros(n + 1)
    bonus[:n] = novelty
    for f in forced:
        if 0 < f < n:
            bonus[f] += 1.0
    best = np.full(n + 1, -np.inf)
    back = np.zeros(n + 1, int)
    best[0] = 0.0
    for j in range(1, n + 1):
        lo = max(0, j - max_len)
        for i in range(lo, j):
            L = j - i
            if L < min_len and not (j == n and L >= 1) and not (i == 0 and L >= 1):
                continue
            gain = (bonus[j] - cost if j < n else 0.0) - pen(L) * (0.3 if j == n or i == 0 else 1.0)
            if best[i] + gain > best[j]:
                best[j], back[j] = best[i] + gain, i
    cuts, j = [], n
    while j > 0:
        cuts.append(back[j])
        j = back[j]
    return sorted({int(c) for c in cuts})


def _segment_similarity(S, a0, a1, b0, b1):
    m = min(a1 - a0, b1 - b0)
    if m <= 0:
        return 0.0
    return float(np.mean([S[a0 + k, b0 + k] for k in range(m)]))


def label_sections(segs, S, energy, vocal, ends_silent):
    """Группы повторов (A, B…) и подписи частей эвристикой: самая громкая
    повторяющаяся группа — chorus, тише — verse; перед припевом с ростом
    энергии — build; громкая часть без вокала после build — drop;
    неповторённая середина после припева — bridge; края — intro/outro."""
    k = len(segs)
    off = S[~np.eye(len(S), dtype=bool)] if len(S) > 1 else np.zeros(1)
    mu, sd = float(off.mean()), float(off.std() or 1.0)
    groups = []
    for i, (a0, a1) in enumerate(segs):
        for g in groups:
            b0, b1 = segs[g[0]]
            if (_segment_similarity(S, a0, a1, b0, b1) - mu) / sd >= 0.8:
                g.append(i)
                break
        else:
            groups.append([i])
    gid = {}
    for n_, g in enumerate(groups):
        for i in g:
            gid[i] = chr(ord("A") + n_ % 26)
    e = np.array([float(np.mean(energy[a:b])) for a, b in segs])
    if len(vocal) and float(np.mean(vocal)) < 0.15:
        vocal = np.zeros(0)                   # инструментал: вокал не подсказка
    v = np.array([float(np.mean(vocal[a:b])) if len(vocal) else 0.5 for a, b in segs])
    labels = [""] * k
    rep = [g for g in groups if len(g) >= 2]
    e_med = float(np.median(e)) if k else 0.0
    sung = [i for i in range(k) if v[i] >= 0.3] if len(vocal) else list(range(k))
    last_sung = sung[-1] if sung else k - 1
    total = segs[-1][1] if segs else 1

    def chorus_score(g):
        # Припев громкий, повторяется и обычно им песня кончается (последняя
        # часть с пением) — у рока энергия куплета и припева почти одна.
        return (float(np.mean(e[g])) + 0.05 * len(g) + (0.2 if last_sung in g else 0.0)
                + (0.1 if segs[g[-1]][0] >= total * 2 / 3 else 0.0))

    cands = [g for g in rep if float(np.mean(e[g])) >= e_med - 0.05
             and (not len(vocal) or float(np.mean(v[g])) >= 0.3)]
    chorus_g = max(cands, key=chorus_score) if cands else None
    if chorus_g is not None:
        for i in chorus_g:
            labels[i] = "chorus"
    else:
        for i in range(k):
            if e[i] >= np.percentile(e, 75) and k > 2:
                labels[i] = "chorus"
    for g in rep:
        if g is chorus_g:
            continue
        # Повторяющаяся группа прямо перед припевом — подводка (build).
        before = sum(1 for i in g if i + 1 < k and labels[i + 1] == "chorus")
        for i in g:
            labels[i] = labels[i] or ("build" if before * 2 >= len(g) else "verse")
    for i in range(k):
        a, b = segs[i]
        if labels[i]:
            continue
        nxt = labels[i + 1] if i + 1 < k else ""
        half = (b - a) // 2
        rising = half > 0 and (float(np.mean(energy[a + half:b]))
                               > float(np.mean(energy[a:a + half])) + 0.08)
        if i + 1 < k and (b - a) <= 8 and (rising or e[i + 1] > e[i] + 0.15) and (
                nxt == "chorus" or e[i + 1] >= np.percentile(e, 70)):
            labels[i] = "build"
    for i in range(k):
        if labels[i] == "chorus" and i > 0 and labels[i - 1] == "build" and v[i] < 0.25:
            labels[i] = "drop"
    first_chorus = next((i for i in range(k) if labels[i] in ("chorus", "drop")), k)
    for i in range(k):
        if labels[i]:
            continue
        if i == 0 and (e[0] < e_med or v[0] < 0.3):
            labels[i] = "intro"
        elif i == k - 1 and (e[i] < e_med or ends_silent):
            labels[i] = "outro"
        elif i > first_chorus and len(next(g for g in groups if i in g)) == 1:
            labels[i] = "bridge"
        else:
            labels[i] = "verse"
    if k > 1 and labels[0] != "chorus" and (e[0] < e_med or (labels[0] == "verse"
                                                          and e[0] < 0.35 and v[0] < 0.3)):
        labels[0] = "intro"
    if k > 2 and labels[-1] != "chorus" and (e[-1] < e_med - 0.1 or ends_silent):
        labels[-1] = "outro"
    return labels, [gid[i] for i in range(k)]


# ── Места для резов ──────────────────────────────────────────────────────────
_LEVEL_PRIORITY = {"phrase": 1.0, "downbeat": 0.8, "strong": 0.6, "beat": 0.5, "offbeat": 0.3}


def _spacing_s(energy):
    """Наименьший промежуток рекомендованных резов (с) по энергии части —
    в секундах, а не в долях: у быстрых песен Beat This! считает доли
    восьмыми (Stormtroopers — 244 BPM), и шаг «в долю» был бы 0,25 с."""
    if energy >= 0.75:
        return 0.45
    if energy >= 0.5:
        return 0.9
    if energy >= 0.25:
        return 1.8
    return 3.6


def cut_slots(beats, bars, phrases, sections, hits, meter):
    """Кандидаты для резов: каждая доля и слабая доля с ударом бочки или
    малого барабана; приоритет — уровень (фраза > сильная доля > доля >
    слабая) + удар барабана; recommended — плотность по энергии части."""
    drums = sorted([(t, s) for k in ("kick", "snare") for t, s, _x in hits.get(k, [])])
    dt = np.array([t for t, _s in drums]) if drums else np.zeros(0)
    ds = np.array([s for _t, s in drums]) if drums else np.zeros(0)

    def drum_at(t, r=0.04):
        if not len(dt):
            return 0.0
        i, j = np.searchsorted(dt, t - r), np.searchsorted(dt, t + r)
        return float(ds[i:j].max()) if j > i else 0.0

    phrase_t = {round(p["t"], 3) for p in phrases}
    section_t = {round(s["t"], 3) for s in sections}
    strong_pos = {1 + meter // 2} if meter in (4, 6) else set()
    cand = []
    for k, b in enumerate(beats):
        t = b["t"]
        if b["pos"] == 1 and round(t, 3) in phrase_t:
            level = "phrase"
        elif b["pos"] == 1:
            level = "downbeat"
        elif b["pos"] in strong_pos:
            level = "strong"
        else:
            level = "beat"
        hit = drum_at(t)
        pr = _LEVEL_PRIORITY[level] + 0.25 * hit + (0.2 if round(t, 3) in section_t else 0.0)
        cand.append({"t": t, "level": level, "bar": b["bar"], "pos": b["pos"],
                     "priority": round(min(1.0, pr), 3), "drum": round(hit, 3)})
        if k + 1 < len(beats):
            mid = 0.5 * (t + beats[k + 1]["t"])
            hit = drum_at(mid, 0.03)
            if hit >= 0.3:
                cand.append({"t": round(mid, 3), "level": "offbeat", "bar": b["bar"],
                             "pos": b["pos"] + 0.5,
                             "priority": round(min(1.0, _LEVEL_PRIORITY["offbeat"] + 0.25 * hit), 3),
                             "drum": round(hit, 3)})
    # Рекомендованные: по частям, от высокого приоритета, не ближе шага.
    for c in cand:
        c["recommended"] = False
    for s in sections or [{"t": 0.0, "end": float("inf"), "energy": 0.5}]:
        inside = [c for c in cand if s["t"] - 1e-3 <= c["t"] < s["end"] - 1e-3]
        if not inside:
            continue
        step = _spacing_s(s["energy"])
        taken = []
        for c in sorted(inside, key=lambda c: (-c["priority"], c["t"])):
            if c["level"] == "offbeat" and step > 0.5:
                continue
            if all(abs(c["t"] - o) >= step * 0.95 for o in taken):
                c["recommended"] = True
                taken.append(c["t"])
    return cand


def snap_frame(t, fps, lead=0):
    """Время ближайшей границы кадра (минус lead кадров) и номер кадра."""
    f = int(round(t * fps)) - int(lead)
    return max(0, f) / fps, max(0, f)


# ── Карта целиком ────────────────────────────────────────────────────────────
def song_map(stereo, mono, *, model=DEFAULT_BEAT_MODEL, python="", drums=True,
             sections=True, gemini=False, gemini_client=None, ctl=None):
    """Карта песни по звуку: stereo — float32 [сэмплы, 2] 44,1 кГц, mono —
    float32 16 кГц. Время — от начала звука (shift_map, snap_slots)."""
    ctl = ctl or _api.NO_CONTROL
    if model not in BEAT_MODELS:
        raise _api.ToolError("usage", f"модель долей: {', '.join(BEAT_MODELS)}")
    if len(mono) < _an.SR:
        raise _api.ToolError("nothing_to_render", "звук короче секунды")
    timing, t_start = {}, time.monotonic()

    def lap(name):
        nonlocal t_start
        now = time.monotonic()
        timing[name] = round(now - t_start, 2)
        t_start = now

    song = _Song(stereo, mono, ctl)
    cached = _api.os.path.join(song.dir, f"map-v{MUSIC_VERSION}-{model}-"
                                         f"{int(bool(drums))}{int(bool(sections))}"
                                         f"{'g' if gemini else ''}.json")
    try:
        if _api.os.path.isfile(cached):
            out = _load_json(cached)
            out["cached"] = True
        else:
            out = _compute_map(song, model, python, drums, sections, ctl, lap, gemini,
                               gemini_client)
            out["timing"] = timing
            _save_json(out, cached)
            out["cached"] = False
    finally:
        song.close()
    out["cache"] = song.dir
    return out


def _compute_map(song, model, python, drums, sections, ctl, lap, gemini=False,
                 gemini_client=None):
    python = _an.ml_python(python)
    mono = song.mono
    ctl.stage("onsets")
    env = _an.onset_envelope(mono)
    engine = {"beats": "dsp", "drums": None, "features": "numpy", "sections": "local"}
    ml = False
    try:
        ml = _ml_ready(python, ctl)
    except _api.ToolError as e:
        if e.code == "cancelled":
            raise
        engine["ml_error"] = e.message
    raw_b, raw_d = [], []
    if ml:
        raw_b, raw_d = _beats_ml(song, model, python)
        engine["beats"] = f"beat_this:{model}"
    if len(raw_b) < 8:
        raw_b, raw_d = _beats_dsp(env, _an.onset_envelope(mono, hi=200.0))
        engine["beats"] = "dsp"
    lap("beats")
    pauses = [(a * _an.HOP_S, b * _an.HOP_S)
              for a, b, _s in _an.silence_spans(mono, min_s=_PAUSE_S)]

    def in_pause(t):
        return any(a + 0.05 < t < b - 0.05 for a, b in pauses)

    keep = [t for t in raw_b if not in_pause(t)]
    meter, starts, pos = build_bars(keep, raw_d)
    refined = refine_times(keep, env)
    beat_t = [round(t, 4) for t, _v in refined]
    lap("bars")
    hits = {"kick": [], "snare": [], "hat": []}
    vocal_db, vpath = None, ""
    if drums and ml:
        dpath, vpath = _stems(song, python)
        dx, drate = _read_wav(dpath)
        hits = drum_hits(dx, drate)
        vx, vrate = _read_wav(vpath)
        vocal_db = _db_grid(vx, vrate)
        engine["drums"] = "htdemucs"
        lap("drums")
    rows = []
    if ml:
        rows = _features_ml(song, python, beat_t, model, vpath if engine["drums"] else "")
        engine["features"] = "librosa"
    if len(rows) != len(beat_t):
        rows = features_numpy(mono, beat_t)
        engine["features"] = "numpy"
    lap("features")
    bpm_bar, changes, tempo = tempo_curve(beat_t, starts, meter)
    # Энергия: громкость, яркость, плотность ударов (или начала звука).
    nb = len(beat_t)
    bars_feat = _bar_matrix(rows, starts, nb) if rows and starts else []
    bar_t = [beat_t[s] for s in starts]
    bar_end = [beat_t[starts[k + 1]] if k + 1 < len(starts) else song.duration
               for k in range(len(starts))]
    drum_t = np.array(sorted(t for k in ("kick", "snare") for t, _s, _x in hits[k]))
    hat_t = np.array(sorted(t for t, _s, _x in hits["hat"]))
    dens = []
    for a, b in zip(bar_t, bar_end):
        span = max(0.1, b - a)
        n_d = int(np.searchsorted(drum_t, b) - np.searchsorted(drum_t, a)) if len(drum_t) else 0
        n_h = int(np.searchsorted(hat_t, b) - np.searchsorted(hat_t, a)) if len(hat_t) else 0
        dens.append((n_d + 0.5 * n_h) / span)
    loud = _norm01([b["db"] for b in bars_feat]) if bars_feat else np.zeros(0)
    bright = _norm01([b["centroid"] for b in bars_feat]) if bars_feat else np.zeros(0)
    dens_n = (_norm01(dens) if engine["drums"] else
              _norm01([b["onset"] for b in bars_feat]) if bars_feat else np.zeros(0))
    energy = (0.45 * loud + 0.2 * bright + 0.35 * dens_n) if len(loud) else np.zeros(len(starts))
    vocal = np.zeros(0)
    if vocal_db is not None and len(bar_t):
        vb = []
        for a, b in zip(bar_t, bar_end):
            seg = vocal_db[int(a * 100):max(int(a * 100) + 1, int(b * 100))]
            vb.append(float(np.percentile(seg, 80)) if len(seg) else -90.0)
        vocal = np.clip((np.asarray(vb) + 45.0) / 25.0, 0.0, 1.0)
    # Части.
    nbar = len(starts)
    segs, labels, groups = [(0, nbar)] if nbar else [], ["verse"] if nbar else [], ["A"] if nbar else []
    if sections and nbar >= 8 and bars_feat:
        S = _ssm(bars_feat)
        nov = (0.35 * _novelty(S, min(4, nbar // 4))
               + 0.35 * _structure_novelty(_section_vectors(bars_feat))
               + 0.15 * _step(energy) + (0.15 * _step(vocal) if len(vocal) else 0.0))
        # После паузы песни — новая часть: первый такт, начавшийся после неё.
        forced = [int(np.searchsorted(bar_t, pb - 0.1)) for _pa, pb in pauses]
        cuts = _segment(nov, nbar, forced)
        segs = [(a, b) for a, b in zip(cuts, cuts[1:] + [nbar])]
        ends_silent = bool(pauses) and pauses[-1][1] >= song.duration - 0.5
        labels, groups = label_sections(segs, S, energy, vocal, ends_silent)
        lap("sections")
    # Сборка.
    bar_of = [0] * nb
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else nb
        for j in range(s, e):
            bar_of[j] = k + 1
    beat_energy = []
    if rows:
        bl = _norm01([r["db"] for r in rows])
        bo = _norm01([r["onset"] for r in rows])
        beat_energy = 0.6 * bl + 0.4 * bo
    beats = [{"t": beat_t[j], "bar": bar_of[j], "pos": pos[j],
              "strength": round(float(refined[j][1]), 3),
              "energy": round(float(beat_energy[j]), 3) if len(beat_energy) == nb else None}
             for j in range(nb)]
    sec_of_bar = {}
    sections_out = []
    for n_, ((a, b), lab, grp) in enumerate(zip(segs, labels, groups)):
        t0 = 0.0 if a == 0 else bar_t[a]
        t1 = song.duration if b >= nbar else bar_t[b]
        sections_out.append({"index": n_ + 1, "label": lab, "group": grp, "t": round(t0, 3),
                             "end": round(t1, 3), "first_bar": a + 1, "bars": b - a,
                             "energy": round(float(np.mean(energy[a:b])), 3) if len(energy) else 0.5,
                             "vocals": round(float(np.mean(vocal[a:b])), 3) if len(vocal) else None})
    if gemini and sections_out:
        ctl.stage("gemini", what="sections")
        try:
            sections_out, raw = gemini_sections(sections_out, bar_t, energy, vocal,
                                                song.duration, song.stereo, gemini_client)
            engine["sections"] = "gemini"
            engine["gemini_raw"] = raw
        except _api.ToolError as e:       # без ключа и квоты — свои подписи
            engine["gemini_error"] = {"code": e.code, "message": e.message}
    for sec in sections_out:
        for k in range(sec["first_bar"] - 1, sec["first_bar"] - 1 + sec["bars"]):
            sec_of_bar[k] = sec["index"]
    bars = []
    for k in range(nbar):
        bars.append({"index": k + 1, "t": round(bar_t[k], 3), "end": round(bar_end[k], 3),
                     "beats": (starts[k + 1] if k + 1 < nbar else nb) - starts[k],
                     "bpm": bpm_bar[k] if k < len(bpm_bar) else tempo,
                     "energy": round(float(energy[k]), 3) if len(energy) else None,
                     "loudness": round(float(loud[k]), 3) if len(loud) else None,
                     "brightness": round(float(bright[k]), 3) if len(bright) else None,
                     "density": round(float(dens[k]), 2),
                     "vocals": round(float(vocal[k]), 3) if len(vocal) else None,
                     "section": sec_of_bar.get(k)})
    phrases = []
    for s in sections_out:
        a = s["first_bar"] - 1
        b = a + s["bars"]
        for n_, k in enumerate(range(a, b, PHRASE_BARS)):
            e = min(b, k + PHRASE_BARS)
            phrases.append({"t": round(bar_t[k], 3),
                            "end": round(bar_t[e] if e < nbar else song.duration, 3),
                            "first_bar": k + 1, "bars": e - k, "section": s["index"],
                            "long": n_ % 2 == 0})
    slots = cut_slots(beats, bars, phrases, sections_out, hits, meter)
    lap("slots")
    hits_out = {k: [[round(t, 3), round(s, 3)] + ([x] if x else []) for t, s, x in v]
                for k, v in hits.items()}
    return {"version": MUSIC_VERSION, "duration": round(song.duration, 3), "engine": engine,
            "tempo": tempo, "meter": meter, "time_signature": f"{meter}/4",
            "tempo_changes": changes, "beats": beats, "bars": bars, "phrases": phrases,
            "sections": sections_out, "hits": hits_out, "slots": slots,
            "pauses": [{"t": round(a, 3), "end": round(b, 3)} for a, b in pauses]}


# ── Время карты, кадры и маркеры ─────────────────────────────────────────────
def shift_map(m, dt):
    """Сдвиг всех времён карты на dt (время звука → время файла)."""
    if not dt:
        return m

    def sh(v):
        return round(v + dt, 4)

    for key in ("beats", "bars", "phrases", "sections", "slots", "pauses"):
        for row in m.get(key, []):
            for f in ("t", "end"):
                if row.get(f) is not None:
                    row[f] = sh(row[f])
    for row in m.get("tempo_changes", []):
        row["t"] = sh(row["t"])
    for rows in m.get("hits", {}).values():
        for h in rows:
            h[0] = sh(h[0])
    m["t0"] = round(dt, 6)
    return m


def snap_slots(m, fps, lead=0):
    """Места для резов на сетке кадров: t_frame (граница ближайшего кадра
    минус lead кадров) и номер кадра."""
    if not fps or fps <= 0:
        return m
    for s in m.get("slots", []):
        tf, f = snap_frame(s["t"], fps, lead)
        s["t_frame"], s["frame"] = round(tf, 6), f
    m["fps"], m["lead_frames"] = float(fps), int(lead)
    return m


def music_file(path, t0=0.0, t1=None, stream=-1, **kw):
    """Карта песни файла path (звук [t0, t1)) во времени файла."""
    if not _api.os.path.isfile(str(path)):
        raise _api.ToolError("missing_files", f"нет файла: {path}")
    t0 = max(0.0, float(t0 or 0.0))
    stereo = _an.file_audio(path, t0, t1, stream, rate=SONG_RATE, channels=2)
    mono = _an.file_audio(path, t0, t1, stream)
    if not len(mono):
        raise _api.ToolError("nothing_to_render", "в файле нет звука")
    out = shift_map(song_map(stereo, mono, **kw), t0)
    out["source"] = _api.os.path.abspath(str(path))
    out["time_base"] = "source"
    return out


def music_project(p, t0=0.0, t1=None, track=None, **kw):
    """Карта песни звука проекта (смесь или дорожка track) во времени проекта."""
    t0 = max(0.0, float(t0 or 0.0))
    t1 = p.duration() if t1 is None else min(float(t1), p.duration())
    if t1 - t0 <= 1.0:
        raise _api.ToolError("bad_range", "отрезок короче секунды")
    stereo = _an.project_audio(p, t0, t1, track, rate=SONG_RATE, channels=2)
    mono = _an.project_audio(p, t0, t1, track)
    if not len(mono):
        raise _api.ToolError("nothing_to_render", "в проекте нет звука")
    out = shift_map(song_map(stereo, mono, **kw), t0)
    out["time_base"] = "project"
    return out


def map_markers(m, kinds, to_project=None):
    """Маркеры проекта (словари для parse_markers) из карты песни: kinds —
    из MUSIC_KINDS; to_project(t) → время проекта или None (вне клипа);
    без него — время карты. Места для резов — только рекомендованные."""
    conv = to_project or (lambda t, clamp=False: t)
    out = []

    def add(t, kind, label="", strength=1.0, end=None):
        if end is None:
            a, b = conv(t), None
        else:
            # Отрезок (часть, фраза) — по границам клипа: часть, начатая до
            # клипа, видна с его начала.
            a, b = conv(t, clamp=True), conv(end, clamp=True)
            if a is None or b is None or b - a < 0.05:
                return
        if a is None:
            return
        out.append(_an._marker(a, kind, label, max(0.0, min(1.0, strength)), b))

    if "beat" in kinds:
        for b in m.get("beats", []):
            add(b["t"], "beat", str(b["pos"]), b.get("strength") or 0.0)
    if "downbeat" in kinds:
        for b in m.get("bars", []):
            add(b["t"], "downbeat", str(b["index"]), 1.0)
    if "phrase" in kinds:
        for ph in m.get("phrases", []):
            add(ph["t"], "phrase", "8" if ph.get("long") else "4",
                1.0 if ph.get("long") else 0.6, ph["end"])
    if "section" in kinds:
        for s in m.get("sections", []):
            add(s["t"], "section", f"{s['label']} {s['group']}", s.get("energy") or 0.5, s["end"])
    for kind in ("kick", "snare", "hat"):
        if kind in kinds:
            for h in m.get("hits", {}).get(kind, []):
                add(h[0], kind, h[2] if len(h) > 2 else "", h[1])
    if "slot" in kinds:
        for s in m.get("slots", []):
            if s.get("recommended"):
                add(s.get("t_frame", s["t"]), "slot", s["level"], s["priority"])
    return out


def clip_mapper(clips):
    """to_project для map_markers: время исходника → время проекта через
    клипы (не реверс, не стоп-кадр), первый подходящий; clamp — время вне
    клипов прижимается к ближайшему краю клипа (концы отрезков)."""
    spans = [(c.in_s, c.out_s, c.start, c.play_speed) for c in clips
             if not c.reverse and not c.frozen]

    def conv(t, clamp=False):
        for a, b, start, speed in spans:
            if a - 1e-6 <= t < b:
                return start + (t - a) / speed
        if clamp and spans:
            a, b, start, speed = min(spans, key=lambda sp: min(abs(t - sp[0]), abs(t - sp[1])))
            return start + (min(max(t, a), b) - a) / speed
        return None

    return conv


# ── Подписи частей от Gemini (необязательно) ─────────────────────────────────
_GEMINI_SECTIONS_SCHEMA = {
    "type": "object",
    "properties": {"sections": {"type": "array", "items": {
        "type": "object",
        "properties": {"start": {"type": "string", "description": "M:SS"},
                       "label": {"type": "string", "enum": list(SECTION_LABELS)}},
        "required": ["start", "label"]}}},
    "required": ["sections"]}
def _mss(text):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2}(?:\.\d+)?)\s*", str(text))
    return int(m.group(1)) * 60 + float(m.group(2)) if m else None


def gemini_sections(secs, bar_t, energy, vocal, dur, stereo, client=None):
    """Подписи частей по звуку песни — один запрос Gemini (Flash-Lite, ключ
    пользователя, учёт QuotaBoard в GeminiClient): модель называет начала и
    подписи частей сама (подсказка своими границами сбивала её на них же);
    части — её, границы прилипают к своим (±1,5 с) или к началу ближайшего
    такта; группа повторов — у своей части с наибольшим перекрытием. Группа
    повторов (group) остаётся своей. (новые части, ответ модели)."""
    import base64
    import gemini_api
    if not secs:
        return secs, []
    if dur > 480:
        raise _api.ToolError("bad_range", "Gemini: песня длиннее 8 минут")
    mono = np.ascontiguousarray(stereo.mean(axis=1) if stereo.ndim == 2 else stereo, np.float32)
    r = _api.subprocess.run(
        [_api.FFMPEG, "-v", "error", "-nostdin", "-f", "f32le", "-ar", str(SONG_RATE), "-ac", "1",
         "-i", "-", "-c:a", "libmp3lame", "-b:a", "48k", "-ar", "22050", "-f", "mp3", "-"],
        input=mono.tobytes(), capture_output=True, creationflags=_api.CREATE_NO_WINDOW, timeout=300)
    if r.returncode != 0 or not r.stdout:
        raise _api.ToolError("ffmpeg_failed", "звук для Gemini не сжат",
                             detail=r.stderr.decode("utf-8", "replace")[-800:])
    prompt = (
        "Это песня. Раздели её на части и подпиши каждую одной меткой:\n"
        "intro — вступление; verse — куплет (текст меняется от раза к разу); build — "
        "подводка к припеву, предприпев; chorus — припев: повторяющаяся часть с главной "
        "строкой песни, у песни с вокалом кульминация — это chorus; drop — только "
        "инструментальная кульминация электронной музыки после подводки, без пения; "
        "bridge — непохожая середина, соло, проигрыш; outro — концовка.\n"
        "Начала частей — M:SS от начала файла, по порядку, первая — 0:00; граница — "
        "там, где слышна смена части (строка текста, рисунок барабанов).")
    parts = [{"type": "audio", "data": base64.b64encode(r.stdout).decode("ascii"),
              "mime_type": "audio/mp3"}, {"type": "text", "text": prompt}]
    if client is None:
        key = _api.gemini_key()
        if not key:
            raise _api.ToolError("gemini_no_key", "нет ключа Gemini (GEMINI_API_KEY или настройки)")
        client = gemini_api.GeminiClient(key, model=gemini_api.DEFAULT_MODEL)
    try:
        ans = client.generate_json(parts, _GEMINI_SECTIONS_SCHEMA)
    except Exception as e:               # GeminiError и сетевые сбои — ответом JSON
        name = type(e).__name__
        raise _api.ToolError("gemini_quota" if "Quota" in name else "gemini_failed",
                             f"{name}: {e}") from e
    rows = sorted((t, row["label"]) for row in (ans or {}).get("sections", [])
                  if isinstance(row, dict) and row.get("label") in SECTION_LABELS
                  and (t := _mss(row.get("start"))) is not None and 0 <= t < dur)
    if not rows:
        raise _api.ToolError("gemini_failed", "Gemini не вернул частей")
    bounds = sorted({0.0} | {x["t"] for x in secs})
    gem = []
    for t, lab in rows:
        near = min(bounds, key=lambda b: abs(b - t))
        if abs(near - t) > 1.5 and bar_t:
            near = min(bar_t, key=lambda b: abs(b - t))
        gem.append((near if t > 0 else 0.0, lab))
    gem_end = [g[0] for g in gem[1:]] + [dur]
    edges = sorted({t for t, _l in gem} | {0.0})
    out = []
    for a, b in zip(edges, edges[1:] + [dur]):
        if b - a < 0.5:
            continue
        votes = {}
        for (ga, lab), gb in zip(gem, gem_end):
            ov = min(b, gb) - max(a, ga)
            if ov > 0:
                votes[lab] = votes.get(lab, 0.0) + ov
        old = max(secs, key=lambda x: min(b, x["end"]) - max(a, x["t"]))
        k0 = int(np.searchsorted(bar_t, a - 1e-3))
        k1 = max(k0 + 1, int(np.searchsorted(bar_t, b - 1e-3)))
        out.append(dict(old, index=len(out) + 1, t=round(a, 3), end=round(b, 3),
                        label=max(votes, key=votes.get) if votes else old["label"],
                        local_label=old["label"], first_bar=k0 + 1, bars=k1 - k0,
                        energy=round(float(np.mean(energy[k0:k1])), 3) if len(energy) else 0.5,
                        vocals=round(float(np.mean(vocal[k0:k1])), 3) if len(vocal) else None))
    for x in out:
        # drop — кульминация без пения; с пением это припев (Gemini путает их
        # от раза к разу даже при temperature 0).
        if x["label"] == "drop" and (x.get("vocals") or 0.0) >= 0.3:
            x["label"] = "chorus"
    return out, [{"t": t, "label": lab} for t, lab in rows]
