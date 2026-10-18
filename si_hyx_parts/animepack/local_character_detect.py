# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Локальный поиск персонажей: детектор голов аниме/манги (YOLOv8s, ONNX).

Модель deepghs/anime_head_detection head_detect_v2.0_s (MIT) скачивается
при первом использовании в пользовательский кэш SI-HYX, как модели OCR
(local_visual_ocr); ревизия и SHA-256 закреплены. Голова видна и у персонажа
со спины, и на чёрно-белой странице манги, поэтому именно головы, а не лица,
отвечают на вопрос «есть ли в кадре персонаж» в режиме «только OCR»
(visual_mode) и задают сцену длинной страницы вебтуна (local_scene)."""
from __future__ import annotations

import hashlib
import io
import os
import threading
from pathlib import Path

MODEL_URL = ("https://huggingface.co/deepghs/anime_head_detection/resolve/"
             "06604feee81983792a57c21081e539c0ae229833/head_detect_v2.0_s/model.onnx")
MODEL_SHA256 = "6679f9b71192298bbf174d82e9e5581c3237b0c3dc67deace7cdbf686b070a00"
MODEL_SIZE = 44585386
# Порог из threshold.json модели (лучший F1 = 0.92 на её проверочной выборке).
THRESHOLD = 0.413
SIDE = 640
MEMO_GROUP = "character_heads_v1_head2s"
# Голова меньше этой доли короткой стороны — фоновая толпа, а не персонаж
# кадра: «есть персонажи» по ней не засчитывается.
MIN_HEAD = 0.04

_lock = threading.Lock()
_session = None


class DetectorUnavailable(RuntimeError):
    """Модель не скачалась или не загрузилась — локально персонажей не найти."""


def _model_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    return root / "SI-HYX" / "anime-head-detect-v2.0s" / "model.onnx"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(generator, path: Path) -> None:
    generator.log("Персонажи: скачиваю локальный детектор голов (45 МБ, один раз) "
                  "в кэш пользователя")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    session = getattr(generator, "session", None)
    if session is None:
        import requests
        session = requests.Session()
    with session.get(MODEL_URL, stream=True, timeout=(15, 120)) as response:
        response.raise_for_status()
        with part.open("wb") as stream:
            for block in response.iter_content(1 << 20):
                if generator.stopped():
                    raise RuntimeError("Отменено")
                stream.write(block)
    if part.stat().st_size != MODEL_SIZE or _sha256(part) != MODEL_SHA256:
        part.unlink(missing_ok=True)
        raise RuntimeError("детектор голов скачался повреждённым")
    os.replace(part, path)


def _model(generator):
    global _session
    if _session is None:
        path = _model_path()
        try:
            if not path.is_file() or path.stat().st_size != MODEL_SIZE:
                _download(generator, path)
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.log_severity_level = 3
            _session = ort.InferenceSession(str(path), options,
                                            providers=["CPUExecutionProvider"])
        except Exception as error:
            if generator.stopped():
                raise
            raise DetectorUnavailable(f"детектор персонажей недоступен: {error}") from error
    return _session


def _letterbox(image):
    """RGB PIL → вход 1×3×640×640 и (масштаб, сдвиг x, сдвиг y)."""
    import numpy as np
    from PIL import Image
    width, height = image.size
    scale = SIDE / max(width, height)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    canvas = Image.new("RGB", (SIDE, SIDE), (114, 114, 114))
    dx, dy = (SIDE - size[0]) // 2, (SIDE - size[1]) // 2
    canvas.paste(image.resize(size, Image.Resampling.BILINEAR), (dx, dy))
    array = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    return array, scale, dx, dy


def _detect(generator, image) -> list[tuple[int, int, int, int, float]]:
    """Головы на одном RGB-изображении PIL: (x0, y0, x1, y1, уверенность)."""
    import cv2
    import numpy as np
    tensor, scale, dx, dy = _letterbox(image)
    with _lock:
        session = _model(generator)
        output = session.run(None, {session.get_inputs()[0].name: tensor})[0]
    rows = np.asarray(output)[0].T          # (N, 4 + классы): cx, cy, w, h
    scores = rows[:, 4:].max(axis=1)
    keep = scores >= THRESHOLD
    rows, scores = rows[keep], scores[keep]
    if not len(rows):
        return []
    boxes = np.stack([rows[:, 0] - rows[:, 2] / 2, rows[:, 1] - rows[:, 3] / 2,
                      rows[:, 2], rows[:, 3]], axis=1)
    chosen = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), THRESHOLD, 0.7)
    width, height = image.size
    found = []
    for index in np.asarray(chosen).reshape(-1):
        x, y, w, h = boxes[index]
        x0 = max(0, round((x - dx) / scale))
        y0 = max(0, round((y - dy) / scale))
        x1 = min(width, round((x + w - dx) / scale))
        y1 = min(height, round((y + h - dy) / scale))
        if x1 > x0 and y1 > y0:
            found.append((x0, y0, x1, y1, float(scores[index])))
    return found


def heads(generator, picture, windows=None) -> list[tuple[int, int, int, int, float]]:
    """Головы на картинке; длинная полоса смотрится окнами (windows)."""
    if not windows:
        return _detect(generator, picture)
    found = []
    for left, top, right, bottom in windows:
        if generator.stopped():
            raise RuntimeError("Отменено")
        for x0, y0, x1, y1, score in _detect(generator, picture.crop((left, top, right, bottom))):
            found.append((x0 + left, y0 + top, x1 + left, y1 + top, score))
    # Окна перекрываются: одна голова находится дважды.
    found.sort(key=lambda box: -box[4])
    unique = []
    for box in found:
        if all(_overlap(box, other) < .5 for other in unique):
            unique.append(box)
    return unique


def _overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / max(1, small)


def visible(boxes, size) -> list:
    """Головы заметного размера: фоновая мелочь персонажем кадра не считается."""
    side = min(size) * MIN_HEAD
    return [box for box in boxes if min(box[2] - box[0], box[3] - box[1]) >= side]


def has_characters(generator, data: bytes) -> bool:
    """Есть ли на картинке персонаж; вердикт кэшируется по хэшу картинки."""
    key = hashlib.sha256(data).hexdigest()
    cached = generator.db_cache.memo(MEMO_GROUP, key)
    if isinstance(cached, bool):
        return cached
    from PIL import Image
    with Image.open(io.BytesIO(data)) as opened:
        picture = opened.convert("RGB")
    found = bool(visible(heads(generator, picture), picture.size))
    generator.db_cache.remember_memo(MEMO_GROUP, key, found)
    return found
