"""Centered periodic-Hann STFT/iSTFT matching the RoFormer export contract."""
import numpy as np
from scipy.signal.windows import hann
from scipy.fft import rfft, irfft


def window(nfft, win_length):
    result = np.zeros(nfft, dtype=np.float32)
    offset = (nfft - win_length) // 2
    result[offset:offset + win_length] = hann(win_length, sym=False)
    return result


def forward(audio, nfft, hop, win_length, normalized=False):
    padded = np.pad(audio, ((0, 0), (nfft // 2, nfft // 2)), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, nfft, axis=-1)[:, ::hop]
    spectrum = rfft(frames * window(nfft, win_length), axis=-1).transpose(0, 2, 1)
    return spectrum / np.sqrt(nfft) if normalized else spectrum


def inverse(spectrum, nfft, hop, win_length, length, normalized=False):
    if normalized:
        spectrum = spectrum * np.sqrt(nfft)
    win = window(nfft, win_length)
    frames = irfft(spectrum.transpose(0, 2, 1), n=nfft, axis=-1) * win
    size = nfft + hop * (frames.shape[1] - 1)
    audio, weight = np.zeros((frames.shape[0], size), dtype=np.float32), np.zeros(size, dtype=np.float32)
    for index in range(frames.shape[1]):
        start = index * hop
        audio[:, start:start + nfft] += frames[:, index]
        weight[start:start + nfft] += win ** 2
    audio /= np.maximum(weight, 1e-8)
    return audio[:, nfft // 2:nfft // 2 + length]
