# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# speech_sync.py — где в звуке речь и на сколько сдвинуть к ней субтитры;
# numpy, без Qt.
"""Речь в звуке и сдвиг субтитров к ней — расчёт без Qt.

Жил в si_hyx_parts/edit_tab/subtitle_sync.py (кнопка «Синхронизировать
субтитры со звуком», там же — как устроен расчёт); тот его реэкспортирует.
speech_activity и onset_strength берёт и анализ проекта montage_tool
(тишина, речь, начала звуков)."""
import numpy as np

SYNC_RATE = 16000
_HOP = SYNC_RATE // 100        # 10 мс
MAX_SHIFT_S = 5.0
_WINDOWS = 6
_REFINE_S = 0.4
_AGREE_S = 0.2
# Меньше этого субтитры уже совпадают со звуком — сдвигать незачем.
MIN_SHIFT_S = 0.08


# ── Расчёт (без Qt) ──────────────────────────────────────────────────────────
def _band_spectrum(x):
    """Спектр мощности окон 20 мс с шагом 10 мс и частоты его полос."""
    win = 2 * _HOP
    n = (len(x) - win) // _HOP + 1
    if n <= 0:
        return None, None
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::_HOP][:n]
    spec = np.abs(np.fft.rfft(frames * np.hanning(win), n=512)) ** 2
    return spec, np.fft.rfftfreq(512, 1.0 / SYNC_RATE)


def speech_activity(x):
    """Оценка «здесь говорят» на каждые 10 мс звука x (моно, SYNC_RATE)."""
    spec, f = _band_spectrum(x)
    if spec is None:
        return np.zeros(0, np.float32)
    band = spec[:, (f >= 300) & (f <= 3000)].sum(axis=1)
    total = spec[:, f >= 60].sum(axis=1) + 1e-9
    loud = np.log10(band + 1e-9)
    k = 600                                   # нормировка по соседним 6 с
    n = len(loud)
    pad = np.pad(loud, (k // 2, k - k // 2), mode="edge")
    cs = np.concatenate(([0.0], np.cumsum(pad)))
    cs2 = np.concatenate(([0.0], np.cumsum(pad * pad)))
    mean = ((cs[k:] - cs[:-k]) / k)[:n]
    var = np.maximum(((cs2[k:] - cs2[:-k]) / k)[:n] - mean * mean, 1e-6)
    z = (loud - mean) / np.sqrt(var)
    return (np.clip(z, -2.0, 3.0) * (0.5 + band / total)).astype(np.float32)


def onset_strength(x):
    """Где речь НАЧИНАЕТСЯ: рост громкости полосы речи (на каждые 10 мс)."""
    spec, f = _band_spectrum(x)
    if spec is None:
        return np.zeros(0, np.float32)
    loud = np.log10(spec[:, (f >= 300) & (f <= 3000)].sum(axis=1) + 1e-9)
    loud = np.convolve(loud, np.ones(3) / 3.0, mode="same")
    return np.maximum(np.diff(loud, prepend=loud[0]), 0.0).astype(np.float32)


def pick_windows(cues, count=_WINDOWS, length=60.0):
    """(начала отрезков, длина отрезка): до count непересекающихся отрезков,
    где реплик больше всего. У коротких субтитров отрезки короче (до 20 с)."""
    if not cues:
        return [], length
    first = min(a for a, _b in cues)
    end = max(b for _a, b in cues)
    span = max(0.0, end - first)
    length = max(20.0, min(length, span / count)) if span > 0 else 20.0
    step = max(1.0, length / 6.0)
    lo = max(0.0, first - 1.0)
    starts = np.arange(lo, max(lo, end - length) + step, step)
    a = np.array([c[0] for c in cues])
    b = np.array([c[1] for c in cues])
    cover = np.array([np.clip(np.minimum(b, s + length) - np.maximum(a, s), 0, None).sum()
                      for s in starts])
    picked = []
    for i in np.argsort(cover)[::-1]:
        if cover[i] <= 0:
            break
        s = float(starts[i])
        if all(abs(s - p) >= length for p in picked):
            picked.append(s)
        if len(picked) >= count:
            break
    return sorted(picked), length


def estimate_offset(cues, decode, max_shift=MAX_SHIFT_S, progress=None):
    """Поправка ко времени реплик: реплика T должна стоять на T + offset.

    cues — [(начало, конец)] в секундах файла; decode(t0, длительность) —
    звук с t0 (моно, SYNC_RATE, float32; у краёв файла может быть короче).
    Возвращает словарь: ok, offset, agree, windows и reason, если не вышло."""
    picked, length = pick_windows(cues)
    if not picked:
        return {'ok': False, 'reason': "в субтитрах нет реплик"}
    K = int(round(max_shift * 100))
    n = int(round(length * 100))
    shifts = 2 * K + 1
    total = np.zeros(shifts)
    onsets = np.zeros(shifts)
    per = []
    kernel = np.exp(-0.5 * (np.arange(-15, 16) / 5.0) ** 2)
    for w, s in enumerate(picked):
        if progress is not None:
            progress(w, len(picked))
        t0 = s - max_shift
        x = decode(max(0.0, t0), length + 2 * max_shift - max(0.0, -t0))
        if t0 < 0:                       # начало файла — слева тишина
            x = np.concatenate((np.zeros(int(round(-t0 * SYNC_RATE)), np.float32), x))
        act, on = speech_activity(x), onset_strength(x)
        need = n + 2 * K
        if len(act) < need:              # конец файла — справа тишина
            act = np.pad(act, (0, need - len(act)))
            on = np.pad(on, (0, need - len(on)))
        mask = np.zeros(n, np.float32)
        starts = np.zeros(n, np.float32)
        for a, b in cues:
            i0, i1 = int(round((a - s) * 100)), int(round((b - s) * 100))
            if i1 <= 0 or i0 >= n:
                continue
            mask[max(0, i0):min(n, i1)] = 1.0
            if i0 >= 0:
                starts[i0] = 1.0
        if mask.sum() < 50:              # меньше полсекунды реплик — не отрезок
            continue
        mask -= mask.mean()
        score = np.correlate(act[:need], mask, mode="valid")[:shifts]
        total += score
        per.append(int(np.argmax(score)))
        onsets += np.correlate(on[:need], np.convolve(starts, kernel, mode="same"),
                               mode="valid")[:shifts]
    if not per:
        return {'ok': False, 'reason': "под репликами не нашлось звука"}
    coarse = int(np.argmax(total))
    reach = int(round(_REFINE_S * 100))
    lo, hi = max(0, coarse - reach), min(shifts, coarse + reach + 1)
    best = lo + int(np.argmax(onsets[lo:hi]))
    agree = sum(1 for p in per if abs(p - coarse) <= int(round(_AGREE_S * 100)))
    need_agree = max(2, int(np.ceil(len(per) * 2 / 3))) if len(per) > 1 else 1
    res = {'offset': (best - K) / 100.0, 'agree': agree, 'windows': len(per)}
    if abs(coarse - K) >= K - 20:
        res.update(ok=False, reason=f"расхождение больше ±{max_shift:g} с — это уже "
                                    "не небольшая рассинхронизация")
    elif agree < need_agree:
        res.update(ok=False, reason=f"звук и реплики не сошлись: согласны {agree} "
                                    f"отрезков из {len(per)}")
    else:
        res['ok'] = True
    return res
