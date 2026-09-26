# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
"""Лежит ли ВНУТРИ записи сам мастер оригинала (игра под оригинал).

Зачем отдельный признак, если есть хрома. Хрома (cover_audio + cover_match)
отвечает «та же композиция», и на вопрос «а не звучит ли тут сам оригинал» она
ответить не может в принципе: точный band-кавер играется в том же темпе и в той
же тональности, и путь выравнивания у него такой же прямой, как у записи, в
которую оригинал просто подмешан. Замер это подтвердил — доля пути с
постоянным смещением у честного band-кавера 0.985 при 0.982 у гитары поверх
оригинала, разделить нельзя.

Здесь считается другое: созвездие спектральных пиков (Wang 2003 — то, на чём
стоит «Шазам»). Пары пиков — это отпечаток КОНКРЕТНОЙ записи, а не композиции:
у одного и того же мастера они совпадают сотнями и все с ОДНИМ И ТЕМ ЖЕ
сдвигом, у чужого исполнения не совпадают вовсе, как бы точно оно ни было
сыграно.

Замерено на 19 парах «эталон — ролик с YouTube» (tools/cover_inside_probe.py):

| что за запись | совпавших пар в секунду |
| --- | --- |
| честные каверы (12: вокал, фортепиано, гитара, оркестр, группа) | 0.05…0.66 |
| игра под оригинал (6 из 7: drum cover, гитара поверх записи) | 3.13…55.44 |

Отсюда порог MAX_OVERLAP = 1.5: вдвое выше самого «липкого» честного кавера и
вдвое ниже самой слабой пойманной игры под оригинал. Седьмая запись (drum
cover на «Tank!») набрала 0.08 — барабанщик играл под другой мастер той же
песни, и поймать её этим способом нельзя; такие ловит гейт по заголовку
(cover_meta_rules.PLAYALONG).

Ни scipy, ни сети, ни Qt: только numpy, который в проекте уже есть. Считается
0.27 с на 90 секунд звука — примерно пятая часть того, что и так тратится на
кандидата.
"""
from __future__ import annotations

import numpy as np

import cover_audio as audio

N_FFT = 2048
HOP = 512
FPS = audio.SR / HOP               # ~43 кадра/с: втрое подробнее хромы
# Полоса, в которой у музыки есть устойчивые пики. Ниже — гул и бас-бочка,
# выше — тарелки и шипение кодека: и то, и другое у одной записи в разных
# перезаливах YouTube выглядит по-разному.
LOW_HZ, HIGH_HZ = 200.0, 5000.0
# Окрестность локального максимума (кадров, бинов). Шире — пиков меньше и
# отпечаток грубее, уже — в него лезет шум.
PEAK_T, PEAK_F = 5, 9
PEAK_PERCENTILE = 90               # тише этого уровня пики не берём вовсе
FAN = 8                            # с сколькими соседями справа вяжем пару
DT_MIN, DT_MAX = 1, 60             # кадров между пиками пары (0.02…1.4 с)
BAND = 4                           # огрубление частоты пары, бинов
CHUNK = 512                        # кадров STFT за раз (та же экономия, что в
                                   # cover_audio: полный проход ел бы сотни МБ)

# Выше этого числа совпавших пар в секунду считаем, что играет сам оригинал.
MAX_OVERLAP = 1.5


def _spectrogram(y: np.ndarray) -> np.ndarray:
    """Лог-спектр нужной полосы, [кадров, бинов]."""
    window = np.hanning(N_FFT).astype(np.float32)
    if y.size < N_FFT:
        y = np.pad(y, (0, N_FFT - y.size))
    total = 1 + (y.size - N_FFT) // HOP
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / audio.SR)
    low = int(np.searchsorted(freqs, LOW_HZ))
    high = max(low + 1, int(np.searchsorted(freqs, HIGH_HZ)))
    out = np.empty((total, high - low), dtype=np.float32)
    for start in range(0, total, CHUNK):
        count = min(CHUNK, total - start)
        block = np.lib.stride_tricks.as_strided(
            y[start * HOP:], shape=(count, N_FFT),
            strides=(y.strides[0] * HOP, y.strides[0]))
        spec = np.abs(np.fft.rfft(block * window, axis=1))[:, low:high]
        out[start:start + count] = spec
    return np.log1p(out * 1000.0)


def _dilate(a: np.ndarray, radius: int, axis: int) -> np.ndarray:
    """Максимум в окне 2*radius+1 вдоль оси — свой, потому что scipy в сборку
    не входит вовсе (см. SI-HYX.spec).

    Шаг окна удваивается: радиус 9 обходится четырьмя проходами вместо девяти.
    """
    out = a
    step, left = 1, int(radius)
    while left > 0:
        take = min(step, left)
        pad = [(0, 0), (0, 0)]
        pad[axis] = (take, take)
        wide = np.pad(out, pad, mode="edge")
        front = [slice(None), slice(None)]
        back = [slice(None), slice(None)]
        front[axis] = slice(0, out.shape[axis])
        back[axis] = slice(2 * take, 2 * take + out.shape[axis])
        out = np.maximum(np.maximum(out, wide[tuple(front)]), wide[tuple(back)])
        left -= take
        step *= 2
    return out


def marks(y) -> tuple[np.ndarray, int]:
    """Звук -> (созвездие пиков [[кадр, бин], …], сколько всего кадров)."""
    y = np.ascontiguousarray(np.asarray(y, dtype=np.float32))
    if not y.size:
        return np.empty((0, 2), dtype=np.int64), 0
    spec = _spectrogram(y)
    top = _dilate(_dilate(spec, PEAK_T, 0), PEAK_F, 1)
    floor = float(np.percentile(spec, PEAK_PERCENTILE))
    times, bins = np.nonzero((spec >= top) & (spec > floor))
    return np.stack([times, bins], axis=1).astype(np.int64), int(len(spec))


def pairs(points) -> tuple[np.ndarray, np.ndarray]:
    """Созвездие -> (хеши пар, время первого пика каждой пары).

    Пара — это (частота первого пика, частота второго, расстояние во времени);
    именно она и переживает перекодирование, тогда как отдельный пик — нет.
    Всё векторно: пары строятся сдвигами отсортированного списка, а не циклом
    по каждому пику (на 90-секундном ролике это 0.06 с вместо секунд).
    """
    empty = (np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64))
    if points is None or not len(points):
        return empty                    # созвездия нет — признак молчит
    points = np.asarray(points, dtype=np.int64)
    if points.ndim != 2 or points.shape[0] < 2:
        return empty
    order = points[np.lexsort((points[:, 1], points[:, 0]))]
    times, bins = order[:, 0], order[:, 1] // BAND
    keys, starts = [], []
    for step in range(1, FAN + 1):
        if step >= len(order):
            break
        gap = times[step:] - times[:-step]
        good = (gap >= DT_MIN) & (gap <= DT_MAX)
        if not good.any():
            continue
        keys.append(((bins[:-step][good] * 1024 + bins[step:][good]) * 64
                     + gap[good]))
        starts.append(times[:-step][good])
    if not keys:
        return empty
    return np.concatenate(keys), np.concatenate(starts)


def overlap(ref_points, cover_points, cover_frames: int) -> float:
    """Сколько пар в секунду совпало на ОДНОМ И ТОМ ЖЕ сдвиге.

    Общий сдвиг здесь и есть всё доказательство: случайные совпадения пар
    рассыпаны по тысячам разных сдвигов, а подмешанный оригинал собирает их в
    один. Нормируем на длину КАНДИДАТА: больше, чем в нём есть, совпасть и не
    может.
    """
    ref_keys, ref_times = pairs(ref_points)
    cover_keys, cover_times = pairs(cover_points)
    if not len(ref_keys) or not len(cover_keys) or cover_frames <= 0:
        return 0.0
    order = np.argsort(ref_keys, kind="stable")
    ref_keys, ref_times = ref_keys[order], ref_times[order]
    low = np.searchsorted(ref_keys, cover_keys, "left")
    high = np.searchsorted(ref_keys, cover_keys, "right")
    count = high - low
    total = int(count.sum())
    if not total:
        return 0.0
    # Разворачиваем «каждой паре кандидата — все её совпадения в эталоне» без
    # питоновского цикла: индекс внутри своей группы = номер в общем ряду
    # минус начало группы.
    inside = np.arange(total) - np.repeat(np.cumsum(count) - count, count)
    shift = np.repeat(cover_times, count) - ref_times[np.repeat(low, count)
                                                      + inside]
    best = int(np.bincount(shift - int(shift.min())).max())
    return best / max(1.0, float(cover_frames) / FPS)


def inside(ref_points, cover_points, cover_frames: int,
           limit: float = MAX_OVERLAP) -> tuple[bool, float]:
    """(играет ли внутри сам оригинал, само число совпадений в секунду).

    Пустое созвездие эталона или кандидата означает «не знаем» — и тогда
    кандидата не отвергаем: молчащий признак не повод выбросить кавер.
    """
    score = overlap(ref_points, cover_points, cover_frames)
    return score > float(limit), round(score, 3)
