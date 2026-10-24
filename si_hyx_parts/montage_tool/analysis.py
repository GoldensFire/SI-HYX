# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Анализ проекта или файла → маркеры (montage_project.Marker).
Public namespace: montage_tool.

Сцены — ffmpeg scdet по картинке, собранной как итог (build_source с
окном) или по самому файлу. Звук сводится в моно 16 кГц
(speech_sync.SYNC_RATE), и на сетке 10 мс считаются: начала звуков и биты
(спектральный поток, темп автокорреляцией, биты — динамическим
программированием, как у Эллиса; сильная доля — фаза из четырёх с самым
громким потоком), тишина (громкость кадра) и речь (speech_sync.
speech_activity — та же оценка, что у синхронизации субтитров; пение она
тоже считает речью). Слова и стемы — karaoke/asr_worker.py в отдельном
Python генератора (faster-whisper, HTDemucs).

Бит и виды карты песни (сильная доля, фраза, часть, удары, места резов) —
music.py: Beat This! и HTDemucs в Python генератора, без него — DSP выше."""
import re

import numpy as np

import speech_sync

import montage_tool as _api

# Карта песни (music.py): бит, сильная доля, фраза, часть, удары, места резов.
_MUSIC_ONLY = ("downbeat", "phrase", "section", "kick", "snare", "hat", "slot")
_DEFAULT_KINDS = ("scene", "beat", "onset", "silence", "speech", "word")
ANALYSIS_KINDS = _DEFAULT_KINDS + _MUSIC_ONLY
SR = speech_sync.SYNC_RATE           # 16 кГц, моно
HOP = SR // 100                      # кадр анализа — 10 мс
HOP_S = HOP / SR
SCENE_THRESHOLD = 10.0               # порог scdet по умолчанию (0…100)
SILENCE_DB = -45.0
MIN_SPAN_S = 0.3
# Поток растёт, пока удар входит в окно (1024 сэмпла), и пик выходит на
# четверть окна раньше удара: замер на клик-треке −20 мс.
ONSET_LAG_S = 0.016
_CHUNK_S = 120.0                     # длинный звук считается кусками
_CHUNK_PAD_S = 4.0
_ML_TIMEOUT = 1800
_WORKER = _api.os.path.join(_api.os.path.dirname(_api.os.path.abspath(_api.__file__)),
                            "karaoke", "asr_worker.py")
_PTS_RX = re.compile(r"pts_time:(-?[0-9.]+)")
_SCORE_RX = re.compile(r"lavfi\.scd\.score=([0-9.]+)")


# ── Источники ────────────────────────────────────────────────────────────────
def _run_bytes(cmd, timeout=600):
    try:
        r = _api.subprocess.run(cmd, stdin=_api.subprocess.DEVNULL, capture_output=True,
                                creationflags=_api.CREATE_NO_WINDOW, timeout=timeout)
    except _api.subprocess.TimeoutExpired as e:
        raise _api.ToolError("ffmpeg_timeout", f"ffmpeg не уложился в {timeout} с") from e
    except OSError as e:
        raise _api.ToolError("ffmpeg_not_started", f"не удалось запустить ffmpeg: {e}") from e
    if r.returncode != 0:
        tail = r.stderr.decode("utf-8", "replace").strip().splitlines()[-15:]
        raise _api.ToolError("ffmpeg_failed", f"ffmpeg завершился с кодом {r.returncode}",
                             detail="\n".join(tail))
    return r.stdout


def _part(p, t0, t1, track):
    """Проект для окна [t0, t1); track — только клипы этой дорожки (копия)."""
    part = p
    if track is not None:
        if not 0 <= track < len(p.tracks):
            raise _api.ToolError("bad_track", f"нет дорожки {track}")
        part = p.copy()
        part.clips = [c for c in part.clips if c.track == track]
    missing = _api.missing_files(part, t0, t1)
    if missing:
        raise _api.ToolError("missing_files", "не найдены файлы проекта",
                             problems=[{"path": m, "message": "нет файла"} for m in missing])
    return part


def project_audio(p, t0, t1, track=None, rate=SR, channels=1):
    """Звук выдержки проекта (как в итоге: громкости, скорость, смешивание)
    float32 [сэмплы] (моно) или [сэмплы, каналы]; пустой — звука нет."""
    part = _part(p, t0, t1, track)
    src = _api.montage_project.build_source(part, video=False, window=(t0, t1))
    if src is None or not src.audio:
        return np.zeros(0, np.float32)
    raw = _run_bytes([_api.FFMPEG, "-v", "error", "-nostdin"] + src.input_args()
                     + ["-filter_complex", src.graph, "-map", "[aout]", "-ac", str(channels),
                        "-ar", str(rate), "-t", f"{src.duration:.6f}", "-f", "f32le", "-"])
    x = np.frombuffer(raw, dtype=np.float32)
    return x if channels == 1 else x[: len(x) // channels * channels].reshape(-1, channels)


def file_audio(path, t0=0.0, t1=None, stream=-1, rate=SR, channels=1):
    """Звук файла [t0, t1) float32: моно [сэмплы] или [сэмплы, каналы]
    (stream — абсолютный индекс потока)."""
    spec = f"0:{int(stream)}" if stream is not None and stream >= 0 else "0:a:0"
    cmd = [_api.FFMPEG, "-v", "error", "-nostdin", "-ss", f"{max(0.0, t0):.3f}", "-i", str(path)]
    if t1 is not None:
        cmd += ["-t", f"{max(0.01, t1 - t0):.3f}"]
    raw = _run_bytes(cmd + ["-map", spec, "-vn", "-sn", "-ac", str(channels), "-ar", str(rate),
                            "-f", "f32le", "-"])
    x = np.frombuffer(raw, dtype=np.float32)
    return x if channels == 1 else x[: len(x) // channels * channels].reshape(-1, channels)


def _scenes_from(cmd_head, threshold):
    """[(время, сила 0…1)] смен плана по выводу scdet."""
    raw = _run_bytes(cmd_head + ["-an", "-sn", "-f", "null", "-"])
    out, t = [], None
    for line in raw.decode("utf-8", "replace").splitlines():
        m = _PTS_RX.search(line)
        if m:
            t = float(m.group(1))
            continue
        m = _SCORE_RX.search(line)
        if m and t is not None:
            out.append((t, min(1.0, float(m.group(1)) / 100.0)))
            t = None
    return out


def _scene_chain(threshold):
    th = max(0.1, min(100.0, float(threshold)))
    return f"scale=256:-2,scdet=threshold={th:g}:sc_pass=1,metadata=mode=print:file=-"


def project_scenes(p, t0, t1, threshold=SCENE_THRESHOLD):
    part = _part(p, t0, t1, None)
    src = _api.montage_project.build_source(
        part, audio=False, window=(t0, t1), tonemap=_api.hdr_tonemap.tonemap_filters(
            (c.src for c in part.clips if c.has_video and not c.is_image),
            _api.escape_filter_path))
    if src is None or not src.video:
        return []
    graph = src.graph + f";[vout]{_scene_chain(threshold)}[sv]"
    return _scenes_from([_api.FFMPEG, "-hide_banner", "-nostdin"] + src.input_args()
                        + ["-filter_complex", graph, "-map", "[sv]"], threshold)


def file_scenes(path, t0=0.0, t1=None, threshold=SCENE_THRESHOLD):
    cmd = [_api.FFMPEG, "-hide_banner", "-nostdin", "-ss", f"{max(0.0, t0):.3f}", "-i", str(path)]
    if t1 is not None:
        cmd += ["-t", f"{max(0.01, t1 - t0):.3f}"]
    return _scenes_from(cmd + ["-map", "0:v:0", "-vf", _scene_chain(threshold)], threshold)


# ── Звук: расчёт ─────────────────────────────────────────────────────────────
def _chunked(fn, x):
    """fn(звук) → значения на сетке 10 мс; длинный звук — кусками по 2 мин с
    запасом по краям (у speech_activity нормировка по соседним 6 с)."""
    step, pad = int(_CHUNK_S * SR), int(_CHUNK_PAD_S * SR)
    if len(x) <= step + 2 * pad:
        return fn(x)
    out = []
    for a in range(0, len(x), step):
        lo = max(0, a - pad)
        vals = fn(x[lo:min(len(x), a + step + pad)])
        skip = (a - lo) // HOP
        out.append(vals[skip:skip + step // HOP])
    return np.concatenate(out) if out else np.zeros(0, np.float32)


def _log_bands(win, count=40, lo=30.0, hi=7600.0):
    """Начала полос спектра (индексы бинов) с шагом по логарифму частоты —
    как мел-полосы: бочка весит наравне с тарелками, а не в 1/500 спектра."""
    edges = np.geomspace(lo, hi, count + 1) * win / SR
    return np.unique(np.clip(np.round(edges).astype(int), 1, win // 2))


def _music_flux(x, hi=7600.0):
    """Спектральный поток музыки на сетке 10 мс: рост логарифма амплитуды в
    лог-частотных полосах до hi Гц (как onset_strength у речи, но во весь
    спектр)."""
    win = 1024
    if len(x) < win:
        return np.zeros(0, np.float32)
    # Кадр i — с центром в i·10 мс (как centered STFT): без сдвига на
    # полокна начала звуков выходили на ~50 мс раньше удара. Края — отражением:
    # ступенька от нулей давала ложный удар в начале и глушила первый бит.
    x = np.pad(x, (win // 2, win // 2), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::HOP]
    mag = np.abs(np.fft.rfft(frames * np.hanning(win).astype(np.float32), axis=1))
    starts = _log_bands(win, count=40 if hi > 1000 else 8, hi=hi)
    bands = np.add.reduceat(mag[:, :starts[-1]], starts[:-1], axis=1) / np.diff(starts)
    logm = np.log1p(100.0 * bands.astype(np.float32))
    flux = np.maximum(np.diff(logm, axis=0, prepend=logm[:1]), 0.0).mean(axis=1)
    # Удар между двумя кадрами делит поток пополам — сглаживание в 3 кадра
    # (как у speech_sync.onset_strength) возвращает ему силу.
    return np.convolve(flux, np.ones(3) / 3.0, mode="same").astype(np.float32)


def _moving_mean(v, n):
    if n <= 1 or len(v) == 0:
        return v
    k = np.ones(n, np.float32) / n
    return np.convolve(np.pad(v, (n // 2, n - 1 - n // 2), mode="edge"), k, mode="valid")


def onset_envelope(x, hi=7600.0):
    """Сила начала звука на сетке 10 мс, 0…1 (поток минус медленный фон);
    hi — верхняя частота полос (бас — для сильной доли)."""
    flux = _chunked(lambda part: _music_flux(part, hi), x)
    if len(flux) == 0:
        return flux
    env = np.maximum(flux - _moving_mean(flux, 100), 0.0)
    top = float(np.percentile(env, 99.5)) or float(env.max()) or 1.0
    return np.clip(env / top, 0.0, 1.0).astype(np.float32)


def pick_onsets(env, delta=0.08, wait=5):
    """Индексы пиков огибающей: максимум в ±30 мс, выше местного среднего
    (±100 мс) на delta, не ближе wait кадров к прошлому."""
    if len(env) < 3:
        return []
    mx = np.lib.stride_tricks.sliding_window_view(np.pad(env, 3, mode="edge"), 7).max(axis=1)
    avg = _moving_mean(env, 21)
    cand = np.nonzero((env >= mx) & (env >= avg + delta) & (env > 0))[0]
    out, last = [], -wait - 1
    for i in cand:
        if i - last > wait:
            out.append(int(i))
            last = i
    return out


def estimate_tempo(env, lo_bpm=60.0, hi_bpm=200.0):
    """Темп (BPM) по автокорреляции огибающей с мягким предпочтением 120 BPM
    (логнормальный вес шириной в октаву, как у librosa). 0 — не вышло."""
    if len(env) < 400:
        return 0.0
    e = env - env.mean()
    n = 1 << int(np.ceil(np.log2(2 * len(e))))
    spec = np.fft.rfft(e, n)
    ac = np.fft.irfft(spec * np.conj(spec), n)[:len(e)]
    lags = np.arange(int(60.0 / hi_bpm / HOP_S), int(60.0 / lo_bpm / HOP_S) + 1)
    lags = lags[(lags > 1) & (lags < len(ac) - 1)]
    if len(lags) == 0 or ac[0] <= 0:
        return 0.0
    bpm = 60.0 / (lags * HOP_S)
    score = ac[lags] / ac[0] * np.exp(-0.5 * np.log2(bpm / 120.0) ** 2)
    i = int(np.argmax(score))
    lag = float(lags[i])
    if 0 < i < len(lags) - 1:             # уточнение параболой
        a, b, c = ac[lags[i] - 1], ac[lags[i]], ac[lags[i] + 1]
        den = a - 2 * b + c
        if den < 0:
            lag += 0.5 * (a - c) / den
    return 60.0 / (lag * HOP_S) if score[i] > 0 else 0.0


def track_beats(env, bpm, tightness=100.0):
    """Индексы битов: динамическое программирование (Ellis 2007) — каждый бит
    на сильном месте огибающей и на расстоянии около периода от прошлого."""
    if bpm <= 0 or len(env) == 0 or env.std() <= 0:
        return []
    period = 60.0 / bpm / HOP_S
    w = np.arange(-int(period), int(period) + 1)
    local = np.convolve(env / env.std(), np.exp(-0.5 * (w * 32.0 / period) ** 2), mode="same")
    n = len(local)
    cum = np.zeros(n)
    back = np.full(n, -1)
    lo_off, hi_off = int(round(2 * period)), int(round(period / 2))
    for i in range(n):
        a, b = max(0, i - lo_off), i - hi_off
        if b <= a:
            cum[i] = local[i]
            continue
        prev = np.arange(a, b)
        score = cum[a:b] - tightness * np.log((i - prev) / period) ** 2
        j = int(np.argmax(score))
        cum[i] = local[i] + score[j]
        back[i] = a + j
    peaks = np.nonzero((cum[1:-1] > cum[:-2]) & (cum[1:-1] >= cum[2:]))[0] + 1
    if len(peaks) == 0:
        return []
    med = np.median(cum[peaks])
    good = np.nonzero(cum[peaks] >= 0.5 * med)[0]
    last = int(peaks[good[-1]] if len(good) else peaks[-1])
    beats = []
    while last >= 0:
        beats.append(last)
        last = int(back[last])
    beats.reverse()
    # Края: слабые биты в тишине до первого и после последнего звука.
    if beats:
        strong = local[beats]
        floor = 0.5 * float(np.sqrt(np.mean(strong ** 2)))
        keep = np.nonzero(strong >= floor)[0]
        if len(keep):
            beats = beats[keep[0]:keep[-1] + 1]
    return beats


def downbeat_phase(env, beats, meter=4):
    """Номер бита (0…meter-1), с которого идут сильные доли: фаза с самой
    громкой суммой огибающей. env — поток баса (бочка и бас приходятся на
    сильную долю, малый барабан на 2 и 4 их бы перекрыл); 1-ю и 3-ю долю
    такта это надёжно не различает."""
    if len(beats) < meter * 2:
        return 0
    vals = env[np.asarray(beats)]
    return int(np.argmax([vals[k::meter].mean() for k in range(meter)]))


def _frame_db(x):
    """Громкость кадров 10 мс (окно 30 мс), dBFS."""
    if len(x) < 3 * HOP:
        return np.zeros(0, np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(x, 3 * HOP)[::HOP]
    return (10.0 * np.log10(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)).astype(np.float32)


def _runs(mask, min_frames, max_gap=0):
    """[(начало, конец)] в кадрах: подряд идущие True, щели до max_gap
    кадров зашиваются, короче min_frames — выбрасываются."""
    idx = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    runs = list(zip(idx[::2], idx[1::2]))
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= max_gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [(int(a), int(b)) for a, b in merged if b - a >= min_frames]


def silence_spans(x, threshold_db=SILENCE_DB, min_s=MIN_SPAN_S):
    db = _frame_db(x)
    return [(a, b, 1.0) for a, b in _runs(db < threshold_db, int(min_s / HOP_S))]


def speech_spans(x, threshold=0.25, min_s=MIN_SPAN_S, threshold_db=SILENCE_DB):
    """Отрезки речи: оценка speech_activity, сглаженная за 300 мс, выше
    порога и не в тишине; паузы до 300 мс внутри фразы зашиваются."""
    act = _chunked(speech_sync.speech_activity, x)
    db = _frame_db(x)
    n = min(len(act), len(db))
    if n == 0:
        return []
    smooth = _moving_mean(act[:n], 30)
    mask = (smooth > threshold) & (db[:n] > threshold_db)
    out = []
    for a, b in _runs(mask, int(min_s / HOP_S), max_gap=30):
        out.append((a, b, float(np.clip(smooth[a:b].mean() / 2.0, 0.0, 1.0))))
    return out


# ── Слова и стемы (karaoke/asr_worker.py) ────────────────────────────────────
def ml_python(path=""):
    """Python генератора с faster-whisper и HTDemucs (music_effects.runtime_python)."""
    if path:
        return str(path)
    import music_effects
    return str(music_effects.runtime_python())


def _run_worker(python, args, timeout=_ML_TIMEOUT):
    if not _api.os.path.isfile(python):
        raise _api.ToolError("ml_unavailable", f"нет Python обработчика: {python}")
    try:
        r = _api.subprocess.run([python, "-I", "-X", "utf8", _WORKER] + args,
                                stdin=_api.subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=_api.CREATE_NO_WINDOW, timeout=timeout)
    except _api.subprocess.TimeoutExpired as e:
        raise _api.ToolError("ml_timeout", f"обработчик не уложился в {timeout} с") from e
    except OSError as e:
        raise _api.ToolError("ml_unavailable", f"обработчик не запустился: {e}") from e
    if r.returncode != 0:
        tail = "\n".join(((r.stderr or "") + (r.stdout or "")).strip().splitlines()[-15:])
        raise _api.ToolError("ml_failed", f"обработчик завершился с кодом {r.returncode}",
                             detail=tail)


def _write_wav(x, path, rate):
    """float32 [сэмплы] или [сэмплы, каналы] → WAV через ffmpeg (16 бит)."""
    ch = 1 if x.ndim == 1 else x.shape[1]
    r = _api.subprocess.run(
        [_api.FFMPEG, "-v", "error", "-nostdin", "-y", "-f", "f32le", "-ar", str(rate),
         "-ac", str(ch), "-i", "-", "-c:a", "pcm_s16le", str(path)],
        input=np.ascontiguousarray(x, dtype=np.float32).tobytes(), capture_output=True,
        creationflags=_api.CREATE_NO_WINDOW, timeout=300)
    if r.returncode != 0:
        raise _api.ToolError("ffmpeg_failed", "WAV не записан",
                             detail=r.stderr.decode("utf-8", "replace")[-800:])


def separate_vocals(wav_in, vocals_out, python="", device="cpu"):
    """Вокал HTDemucs (asr_worker separate) в vocals_out."""
    _run_worker(ml_python(python), ["separate", str(wav_in), str(vocals_out),
                                    "--device", device])
    if not _api.os.path.isfile(vocals_out):
        raise _api.ToolError("ml_failed", "обработчик не записал вокал")


def transcribe_words(wav, python="", language="auto", model="medium", device="cpu",
                     compute="int8"):
    """[(начало, конец, слово)] — asr_worker transcribe (faster-whisper)."""
    tmpdir = _api.tempfile.mkdtemp(prefix="sihyx_asr_")
    try:
        target = _api.os.path.join(tmpdir, "words.json")
        _run_worker(ml_python(python), ["transcribe", str(wav), target, "--device", device,
                                        "--compute", compute, "--language", language or "auto",
                                        "--model", model])
        with open(target, "r", encoding="utf-8") as f:
            rows = _api.json.load(f)
    finally:
        _api.shutil.rmtree(tmpdir, ignore_errors=True)
    out = []
    for row in rows if isinstance(rows, list) else []:
        for w in row.get("words") or []:
            try:
                a, b = float(w["start"]), float(w["end"])
            except (KeyError, TypeError, ValueError):
                continue
            text = str(w.get("word") or "").strip()
            if text and b >= a:
                out.append((a, b, text))
    return out


def stems(audio, rate, out_dir, python="", device="cpu"):
    """Стемы звука audio ([сэмплы, 2], rate): vocals.wav — HTDemucs, music.wav
    — остаток (звук минус вокал, сэмпл в сэмпл). Пути файлов."""
    out_dir = _api.os.path.abspath(str(out_dir))
    _api.os.makedirs(out_dir, exist_ok=True)
    mix = _api.os.path.join(out_dir, "mix.wav")
    vocals = _api.os.path.join(out_dir, "vocals.wav")
    music = _api.os.path.join(out_dir, "music.wav")
    for f in (vocals, music):
        if _api.os.path.exists(f):
            _api.os.remove(f)               # asr_worker не перезаписывает готовый вокал
    _write_wav(audio, mix, rate)
    separate_vocals(mix, vocals, python, device)
    _run_bytes([_api.FFMPEG, "-v", "error", "-nostdin", "-y", "-i", mix, "-i", vocals,
                "-filter_complex",
                f"[0:a]aresample={rate},aformat=sample_fmts=fltp:channel_layouts=stereo[m];"
                f"[1:a]aresample={rate},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                "volume=-1[v];[m][v]amix=inputs=2:normalize=0:duration=first[out]",
                "-map", "[out]", "-c:a", "pcm_s16le", music])
    return {"mix": mix, "vocals": vocals, "music": music}


# ── Сборка маркеров ──────────────────────────────────────────────────────────
def _marker(t, kind, label="", strength=1.0, end=None):
    return {"t": round(float(t), 3), "kind": kind, "label": label,
            "strength": round(float(strength), 3),
            "end": None if end is None else round(float(end), 3)}


def audio_markers(x, kinds, offset=0.0):
    """Маркеры звука x (моно SR) со сдвигом offset; и темп (BPM или None)."""
    out, tempo = [], None
    if not len(x):
        return out, tempo
    if "beat" in kinds or "onset" in kinds:
        env = onset_envelope(x)
        if "onset" in kinds:
            out += [_marker(offset + i * HOP_S + ONSET_LAG_S, "onset", "", env[i])
                    for i in pick_onsets(env)]
        if "beat" in kinds:
            bpm = estimate_tempo(env)
            beats = track_beats(env, bpm)
            if beats:
                tempo = round(float(bpm), 2)
                phase = downbeat_phase(onset_envelope(x, hi=200.0), beats)
                for k, i in enumerate(beats):
                    pos = (k - phase) % 4 + 1
                    out.append(_marker(offset + i * HOP_S + ONSET_LAG_S, "beat", str(pos), env[i]))
    if "silence" in kinds:
        out += [_marker(offset + a * HOP_S, "silence", "тишина", s, offset + b * HOP_S)
                for a, b, s in silence_spans(x)]
    if "speech" in kinds:
        out += [_marker(offset + a * HOP_S, "speech", "речь", s, offset + b * HOP_S)
                for a, b, s in speech_spans(x)]
    return out, tempo


def _word_markers(x, offset, vocals, opts):
    tmpdir = _api.tempfile.mkdtemp(prefix="sihyx_words_")
    try:
        wav = _api.os.path.join(tmpdir, "audio.wav")
        _write_wav(x, wav, SR)
        if vocals:
            voc = _api.os.path.join(tmpdir, "vocals.wav")
            separate_vocals(wav, voc, opts.get("python", ""), opts.get("device", "cpu"))
            wav = voc
        words = transcribe_words(wav, opts.get("python", ""), opts.get("language", "auto"),
                                 opts.get("model", "medium"), opts.get("device", "cpu"))
    finally:
        _api.shutil.rmtree(tmpdir, ignore_errors=True)
    return [_marker(offset + a, "word", w, 1.0, offset + b) for a, b, w in words]


def _music_markers(kinds, ml, get_map, fps=0.0):
    """Маркеры карты песни для видов kinds (бит — тоже отсюда) и темп."""
    want = [k for k in kinds if k == "beat" or k in _MUSIC_ONLY]
    if not want:
        return [], None
    ml = ml or {}
    try:
        m = get_map(model=ml.get("beat_model") or _api.DEFAULT_BEAT_MODEL,
                    python=ml.get("python", ""),
                    drums=any(k in want for k in ("kick", "snare", "hat", "slot")),
                    sections=any(k in want for k in ("section", "phrase", "slot")),
                    ctl=ml.get("ctl"))
    except _api.ToolError as e:
        if e.code in ("nothing_to_render", "bad_range"):
            return [], None              # нет звука или он короче секунды — нет и битов
        raise
    _api.snap_slots(m, fps)
    return _api.map_markers(m, want), m.get("tempo")


def _kinds(kinds):
    kinds = [k.strip() for k in (kinds or _DEFAULT_KINDS) if k and k.strip()]
    bad = [k for k in kinds if k not in ANALYSIS_KINDS]
    if bad:
        raise _api.ToolError("usage", f"неизвестный вид анализа: {', '.join(bad)} "
                                      f"(есть {', '.join(ANALYSIS_KINDS)})")
    return kinds


def analyze_project(p, kinds=None, t0=0.0, t1=None, track=None, scene_threshold=SCENE_THRESHOLD,
                    vocals=False, ml=None):
    """Маркеры проекта во времени проекта на [t0, t1): картинка — как итог
    (сцены), звук — смесь или дорожка track (музыка для битов). ml —
    {'python', 'device', 'language', 'model'} для слов."""
    kinds = _kinds(kinds)
    t0 = max(0.0, float(t0 or 0.0))
    t1 = p.duration() if t1 is None else min(float(t1), p.duration())
    if t1 - t0 <= 0.05:
        raise _api.ToolError("bad_range", "пустой отрезок времени")
    markers, tempo = [], None
    if "scene" in kinds:
        markers += [_marker(t0 + t, "scene", "", s)
                    for t, s in project_scenes(p, t0, t1, scene_threshold)]
    found, tempo = _music_markers(
        kinds, ml, lambda **kw: _api.music_project(p, t0, t1, track, **kw), p.output_format()[2])
    markers += found
    audio_kinds = [k for k in kinds if k not in ("scene", "beat") + _MUSIC_ONLY]
    if audio_kinds:
        x = project_audio(p, t0, t1, track)
        found, _t = audio_markers(x, audio_kinds, t0)
        markers += found
        if "word" in kinds and len(x):
            markers += _word_markers(x, t0, vocals, ml or {})
    markers.sort(key=lambda m: (m["t"], m["kind"]))
    return {"time_base": "project", "t0": round(t0, 6), "t1": round(t1, 6),
            "kinds": kinds, "tempo": tempo, "markers": markers}


def analyze_file(path, kinds=None, t0=0.0, t1=None, stream=-1,
                 scene_threshold=SCENE_THRESHOLD, vocals=False, ml=None):
    """Маркеры файла во времени самого файла (выбор in/out для клипов)."""
    kinds = _kinds(kinds)
    if not _api.os.path.isfile(str(path)):
        raise _api.ToolError("missing_files", f"нет файла: {path}")
    t0 = max(0.0, float(t0 or 0.0))
    markers, tempo = [], None
    if "scene" in kinds:
        markers += [_marker(t0 + t, "scene", "", s)
                    for t, s in file_scenes(path, t0, t1, scene_threshold)]
    found, tempo = _music_markers(
        kinds, ml, lambda **kw: _api.music_file(path, t0, t1, stream, **kw))
    markers += found
    audio_kinds = [k for k in kinds if k not in ("scene", "beat") + _MUSIC_ONLY]
    if audio_kinds:
        x = file_audio(path, t0, t1, stream)
        found, _t = audio_markers(x, audio_kinds, t0)
        markers += found
        if "word" in kinds and len(x):
            markers += _word_markers(x, t0, vocals, ml or {})
    markers.sort(key=lambda m: (m["t"], m["kind"]))
    return {"time_base": "source", "source": _api.os.path.abspath(str(path)),
            "t0": round(t0, 6), "t1": None if t1 is None else round(float(t1), 6),
            "kinds": kinds, "tempo": tempo, "markers": markers}


def merge_markers(p, found, kinds, t0, t1):
    """Кладёт найденные маркеры в проект: прежние маркеры тех же видов на
    [t0, t1) заменяются, свои (custom) и вне отрезка остаются."""
    keep = [m for m in p.markers
            if not (m.kind in kinds and m.kind != "custom" and t0 <= m.t < t1)]
    new = _api.montage_project.parse_markers(found)
    p.markers = sorted(keep + new, key=lambda m: (m.t, m.kind))
    return len(new)
