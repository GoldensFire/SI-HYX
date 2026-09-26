# -*- coding: utf-8 -*-
"""Chroma + OTI + Qmax local alignment: is this recording the same composition.

Классика (Serrà 2009), а не нейросеть, и вот почему. Замеры на настоящих
ютубовских каверах (139 пар «эталон — кавер» и 2662 чужие пары,
tools/cover_audio_probe.py): 0 ложных срабатываний при recall 0.813, 18 мс на
пару. Опубликованные нейросетевые CSI дают MAP 0.86 на
студийных датасетах, но 0.50–0.52 на реальных каверах с YouTube, а их чекпойнты
весят от 0.9 до 8.7 ГБ и предполагают GPU. Здесь же — только numpy, который в
проекте уже есть.

Выравнивание попутно отдаёт УЧАСТОК: обратный проход по матрице Qmax связывает
время эталона со временем кавера, поэтому отдельный поиск припева не нужен
(см. map_window). Именно это решает случай «эталон TV-size 90 с, кавер — полная
пятиминутная версия»: совпадение находится там, где оно есть, хоть на 274-й
секунде.

Ни сети, ни subprocess, ни Qt: ffmpeg зовёт вызывающая сторона своим killable
раннером (decode_args), сюда приходит готовый WAV.
"""
from __future__ import annotations

import wave

import numpy as np

SR = 22050
N_FFT = 4096
HOP = 1024
SMOOTH = 21                  # окно сглаживания хромы, кадров (~1 с)
DOWN = 5                     # прореживание -> FPS
FPS = SR / HOP / DOWN        # ~4.31 кадра/с итоговой хромы
FMIN, FMAX = 65.0, 2093.0    # C2…C7: ниже — гул, выше — шипение тарелок
GAMMA = 100.0                # log-сжатие спектра; без него solo-инструменты тонут
KAPPA = 0.09                 # доля ближайших соседей в бинарной матрице
GAP = 0.5                    # штраф за разрыв в локальном выравнивании
# Сколько кадров STFT считаем за раз. Наивный одношаговый STFT давал пик 798 МБ
# на 377-секундном треке — при четырёх параллельных проверках это 3 ГБ.
CHUNK = 512

_BANK = None


def decode_args(ffmpeg: str, source: str, target: str) -> list[str]:
    """Команда ffmpeg: что угодно -> моно WAV 22 050 Гц s16 для анализа."""
    return [str(ffmpeg), "-y", "-v", "error", "-i", str(source),
            "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(target)]


def read_wav(path) -> np.ndarray:
    """Моно s16 WAV, записанный decode_args, -> float32 в [-1, 1]."""
    with wave.open(str(path), "rb") as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise ValueError("Ожидался моно WAV s16 (см. decode_args).")
        if stream.getframerate() != SR:
            raise ValueError(f"Ожидалась частота {SR} Гц.")
        raw = stream.readframes(stream.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _filterbank() -> np.ndarray:
    """[12, 1+N_FFT/2]: вес бина FFT в питч-классе, гауссово окно 0.5 полутона."""
    global _BANK
    if _BANK is not None:
        return _BANK
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    inside = (freqs >= FMIN) & (freqs <= FMAX)
    midi = np.zeros_like(freqs)
    midi[inside] = 69.0 + 12.0 * np.log2(np.maximum(freqs[inside], 1e-6) / 440.0)
    bank = np.zeros((12, freqs.size), dtype=np.float32)
    for pitch in range(12):
        distance = np.abs(((midi - pitch + 6.0) % 12.0) - 6.0)
        bank[pitch] = np.where(inside, np.exp(-0.5 * (distance / 0.5) ** 2), 0.0)
    _BANK = bank
    return bank


def _frames(y: np.ndarray, start: int, count: int) -> np.ndarray:
    """Вид БЕЗ КОПИИ на `count` кадров STFT, начиная с кадра `start`.

    Вызывающий обязан следить, что последний кадр существует: as_strided границ
    не проверяет и молча прочитал бы чужую память."""
    step = y.strides[0]
    return np.lib.stride_tricks.as_strided(
        y[start * HOP:], shape=(count, N_FFT), strides=(step * HOP, step))


def _spectra(block: np.ndarray, window: np.ndarray) -> np.ndarray:
    return np.abs(np.fft.rfft(block * window, axis=1)).astype(np.float32)


def chroma(y) -> np.ndarray:
    """Аудио -> хрома [кадров, 12], L2-нормированная по кадрам.

    Нормировка спектра — на пик ВСЕГО трека: log-сжатие нелинейно, и от
    абсолютного уровня зависит форма признака. Громкость записей на YouTube
    гуляет на порядок, поэтому фиксированной шкалой обойтись нельзя, а пик
    считается отдельным дешёвым проходом по разреженной сетке кадров (соседние
    кадры при шаге 46 мс почти одинаковы, на итог это не влияет)."""
    y = np.ascontiguousarray(np.asarray(y, dtype=np.float32))
    if y.size < N_FFT:
        y = np.pad(y, (0, N_FFT - y.size))
    window = np.hanning(N_FFT).astype(np.float32)
    total = 1 + (y.size - N_FFT) // HOP

    # Пик — отдельным полным проходом, а не по разреженной сетке кадров.
    # Выборка каждого четвёртого экономила 0,2 с, но сдвигала счёт на единицы
    # (236.5 против 238.0): пороги калиброваны на точных значениях, а вердикт
    # уходит в кэш — приблизительная шкала однажды перебросила бы пограничного
    # кандидата через порог, и объяснить это было бы нечем.
    peak = 0.0
    for start in range(0, total, CHUNK):
        count = min(CHUNK, total - start)
        peak = max(peak, float(_spectra(_frames(y, start, count), window).max()))
    scale = GAMMA / max(peak, 1e-9)

    raw = np.empty((total, 12), dtype=np.float32)
    for start in range(0, total, CHUNK):
        count = min(CHUNK, total - start)
        spec = np.log1p(scale * _spectra(_frames(y, start, count), window))
        raw[start:start + count] = spec @ _filterbank().T

    energy = raw.sum(axis=1, keepdims=True)
    raw = np.divide(raw, energy, out=np.zeros_like(raw), where=energy > 1e-6)
    kernel = np.hanning(SMOOTH).astype(np.float32)
    kernel /= kernel.sum()
    smooth = np.vstack([np.convolve(raw[:, p], kernel, mode="same")
                        for p in range(12)]).T[::DOWN]
    norm = np.linalg.norm(smooth, axis=1, keepdims=True)
    return np.divide(smooth, norm, out=np.zeros_like(smooth), where=norm > 1e-6)


def oti_shift(ref: np.ndarray, cover: np.ndarray) -> int:
    """Транспозиция кавера относительно эталона (Optimal Transposition Index).

    На всех проверенных случаях одна лучшая транспозиция дала счёт, в точности
    равный перебору всех двенадцати, — двенадцатикратная экономия бесплатно."""
    if not ref.size or not cover.size:
        return 0
    profile = cover.mean(axis=0)
    reference = ref.mean(axis=0)
    return int(np.argmax([reference @ np.roll(profile, s) for s in range(12)]))


def cross_binary(ref: np.ndarray, cover: np.ndarray,
                 kappa: float = KAPPA) -> np.ndarray:
    """Бинарная кросс-рекуррентность: взаимные ближайшие соседи по квантилю."""
    dist = 2.0 - 2.0 * (ref @ cover.T)          # квадрат евклида для L2-норм.
    np.maximum(dist, 0.0, out=dist)
    rows, cols = dist.shape
    by_row = max(1, min(cols, int(round(kappa * cols))))
    by_col = max(1, min(rows, int(round(kappa * rows))))
    limit_row = np.partition(dist, by_row - 1, axis=1)[:, by_row - 1][:, None]
    limit_col = np.partition(dist, by_col - 1, axis=0)[by_col - 1, :][None, :]
    return ((dist <= limit_row) & (dist <= limit_col)).astype(np.float32)


def qmax(binary: np.ndarray, gap: float = GAP):
    """Локальное выравнивание Qmax -> (счёт, конец в эталоне, конец в кавере, Q).

    Цикл идёт по строкам эталона, а внутри строки всё считается numpy сразу:
    Q[i] зависит только от строк i-1 и i-2, внутри строки зависимостей нет."""
    rows, cols = binary.shape
    table = np.zeros((rows + 2, cols + 2), dtype=np.float32)
    for i in range(2, rows + 2):
        diagonal = table[i - 1, 1:cols + 1]
        skip_ref = table[i - 2, 1:cols + 1]
        skip_cover = table[i - 1, 0:cols]
        best = np.maximum(np.maximum(diagonal, skip_ref), skip_cover)
        broken = np.maximum(np.maximum(diagonal - gap, skip_ref - gap),
                            skip_cover - gap)
        table[i, 2:cols + 2] = np.where(binary[i - 2] > 0, best + 1.0,
                                        np.maximum(broken, 0.0))
    flat = int(np.argmax(table))
    i_end, j_end = np.unravel_index(flat, table.shape)
    return float(table[i_end, j_end]), int(i_end) - 2, int(j_end) - 2, table


def align(ref: np.ndarray, cover: np.ndarray, *, kappa: float = KAPPA,
          gap: float = GAP) -> dict:
    """Полное сравнение пары -> счёт, транспозиция и путь выравнивания.

    {"score", "shift", "path": [(кадр эталона, кадр кавера), …],
     "ref_span", "cov_span", "tempo"} — пустой path означает «совпадения нет»."""
    if not ref.size or not cover.size:
        return {"score": 0.0, "shift": 0, "path": [], "ref_span": (0.0, 0.0),
                "cov_span": (0.0, 0.0), "tempo": 0.0}
    shift = oti_shift(ref, cover)
    score, i_end, j_end, table = qmax(
        cross_binary(ref, np.roll(cover, shift, axis=1), kappa), gap)
    path = []
    i, j = i_end + 2, j_end + 2
    while i >= 2 and j >= 2 and table[i, j] > 0:
        path.append((i - 2, j - 2))
        steps = ((i - 1, j - 1), (i - 2, j - 1), (i - 1, j - 2))
        i, j = max(steps, key=lambda cell: table[cell])
    path.reverse()
    if not path:
        return {"score": score, "shift": shift, "path": [],
                "ref_span": (0.0, 0.0), "cov_span": (0.0, 0.0), "tempo": 0.0}
    ref_span = (path[0][0] / FPS, path[-1][0] / FPS)
    cov_span = (path[0][1] / FPS, path[-1][1] / FPS)
    width = ref_span[1] - ref_span[0]
    return {"score": score, "shift": shift, "path": path,
            "ref_span": ref_span, "cov_span": cov_span,
            "tempo": (cov_span[1] - cov_span[0]) / width if width > 0.05 else 0.0}


def map_window(path, start: float, length: float):
    """Участок ЭТАЛОНА [start, start+length] -> участок кавера в секундах.

    None — этой части эталона на пути нет. Так и должно быть: у полной версии
    кавера TV-size-эталон покрывает только свой отрезок, и притворяться, что
    остальное тоже совпало, нельзя."""
    if not path:
        return None
    cells = np.asarray(path, dtype=np.int64)
    low, high = start * FPS, (start + length) * FPS
    inside = cells[(cells[:, 0] >= low) & (cells[:, 0] <= high)]
    if inside.shape[0] < 3:
        return None
    return float(inside[:, 1].min() / FPS), float(inside[:, 1].max() / FPS)


def window_density(path, start: float, length: float) -> float:
    """Какая доля окна эталона реально лежит на пути (0…1).

    Рыхлый путь — признак случайных диагоналей, а не выравнивания: по нему
    вырезать двадцать секунд нельзя."""
    if not path:
        return 0.0
    cells = np.asarray(path, dtype=np.int64)
    low, high = start * FPS, (start + length) * FPS
    inside = cells[(cells[:, 0] >= low) & (cells[:, 0] <= high)]
    return float(len(set(inside[:, 0].tolist())) / max(1.0, high - low))
