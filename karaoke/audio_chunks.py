"""Kim's half-chunk overlap and reflected context preserve recording duration."""
import numpy as np


def pad_context(audio, length):
    border = length // 2 if audio.shape[-1] > length else 0
    if border:
        audio = np.pad(audio, ((0, 0), (border, border)), mode="reflect")
    return audio, border


def chunks(audio, length):
    step, fade = length // 2, length // 10
    for start in range(0, audio.shape[-1], step):
        count = min(length, audio.shape[-1] - start)
        chunk = audio[:, start:start + count]
        mode = "reflect" if count > length // 2 else "constant"
        chunk = np.pad(chunk, ((0, 0), (0, length - count)), mode=mode)
        weight = np.ones(length, dtype=np.float32)
        weight[:fade] = np.linspace(0, 1, fade)
        weight[-fade:] = np.linspace(1, 0, fade)
        if start == 0:
            weight[:fade] = 1
        if start + step >= audio.shape[-1]:
            weight[-fade:] = 1
        yield start, count, chunk, weight
