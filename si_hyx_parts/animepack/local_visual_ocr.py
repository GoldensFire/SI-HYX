# -*- coding: utf-8 -*-
"""One PP-OCRv6 detection pass, two ONNX recognizers, image-hash memo."""
from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

MEMO_GROUP = "visual_ocr_v1_pp6s_cyr5m"


@contextmanager
def _held_until_cancelled(lock, stopped):
    while not lock.acquire(timeout=.1):
        if stopped():
            raise RuntimeError("Отменено")
    try:
        yield
    finally:
        lock.release()


def initialize(generator):
    generator._ocr_lock = threading.Lock()
    generator._ocr_models = None
    generator._ocr_stats_lock = threading.Lock()
    generator._ocr_stats = Counter()


def _models():
    from rapidocr import RapidOCR
    from rapidocr.utils.typings import LangRec, ModelType, OCRVersion

    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    root = root / "SI-HYX" / "rapidocr-3.9.2"
    root.mkdir(parents=True, exist_ok=True)
    common = {"Global.model_root_dir": str(root), "Global.use_cls": False,
              "Global.log_level": "warning", "Det.thresh": .25,
              "Det.box_thresh": .35}
    latin = RapidOCR(params={**common, "Det.ocr_version": OCRVersion.PPOCRV6,
                             "Det.model_type": ModelType.SMALL,
                             "Rec.ocr_version": OCRVersion.PPOCRV6,
                             "Rec.model_type": ModelType.SMALL})
    cyrillic = RapidOCR(params={**common, "Global.use_det": False,
                                "Rec.ocr_version": OCRVersion.PPOCRV5,
                                "Rec.model_type": ModelType.MOBILE,
                                "Rec.lang_type": LangRec.CYRILLIC})
    return latin, cyrillic


def _decode(data: bytes):
    import io

    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as opened:
            image = cv2.cvtColor(np.asarray(opened.convert("RGB")),
                                 cv2.COLOR_RGB2BGR)
    return image


def _recognized(model, crops, det_scores, name):
    result = model.recognize_txt(crops)
    texts = result.txts if result.txts is not None else []
    scores = result.scores if result.scores is not None else []
    return [{"text": str(texts[i]) if i < len(texts) else "",
             "confidence": float(scores[i]) if i < len(scores) else 0.0,
             "det_score": float(det_scores[i]), "model": name, "crop": i}
            for i in range(len(crops))]


def read(generator, data: bytes) -> tuple[list[dict], float, bool]:
    """OCR rows, elapsed seconds, cache hit. Cache contains no title decision."""
    key = hashlib.sha256(data).hexdigest()
    cached = generator.db_cache.memo(MEMO_GROUP, key)
    if isinstance(cached, list):
        return cached, 0.0, True
    lock = getattr(generator, "_ocr_lock", None)
    if lock is None:
        lock = generator._ocr_lock = threading.Lock()
    with _held_until_cancelled(lock, generator.stopped):
        cached = generator.db_cache.memo(MEMO_GROUP, key)
        if isinstance(cached, list):
            return cached, 0.0, True
        if generator.stopped():
            raise RuntimeError("Отменено")
        started = time.perf_counter()
        if generator._ocr_models is None:
            generator.log("OCR: загружаю локальные модели PP-OCRv6 Small и "
                          "Cyrillic PP-OCRv5 Mobile (при первом запуске "
                          "файлы скачиваются в кэш пользователя)")
            generator._ocr_models = _models()
        latin, cyrillic = generator._ocr_models
        image = _decode(data)
        detected = latin(image, use_det=True, use_cls=False, use_rec=False)
        boxes = getattr(detected, "boxes", None)
        rows = []
        if boxes is not None and len(boxes):
            crops = latin.crop_text_regions(image, boxes)
            scores = getattr(detected, "scores", None)
            det_scores = list(scores) if scores is not None else [0.0] * len(crops)
            for name, model in (("latin", latin), ("cyrillic", cyrillic)):
                if generator.stopped():
                    raise RuntimeError("Отменено")
                rows.extend(_recognized(model, crops, det_scores, name))
        elapsed = time.perf_counter() - started
        generator.db_cache.remember_memo(MEMO_GROUP, key, rows)
        return rows, elapsed, False


def note(generator, source: str, result: dict, elapsed: float, cached: bool,
         fallback: bool):
    stats = getattr(generator, "_ocr_stats", None)
    lock = getattr(generator, "_ocr_stats_lock", None)
    if stats is not None and lock is not None:
        with lock:
            stats["images"] += 1
            stats["cache_hits" if cached else "ocr_runs"] += 1
            stats["local" if not fallback else "gemini_fallback"] += 1
            stats["matches"] += result["status"] == "title"
            stats["ocr_ms"] += int(elapsed * 1000)
    detail = (f"; OCR «{result['ocr']}» ↔ «{result['title']}», "
              f"similarity={result['similarity']}%, "
              f"confidence={result['confidence']:.3f}" if result["title"] else "")
    generator.log(f"OCR {source}: {result['status']}, {elapsed * 1000:.0f} мс"
                  f"{' (кэш)' if cached else ''}{detail}"
                  f"{' → Gemini fallback' if fallback else ''}")


def summary(generator):
    stats = getattr(generator, "_ocr_stats", None)
    if not stats or not stats["images"]:
        return
    generator.log(
        f"OCR изображений: {stats['images']}; локально {stats['local']}; "
        f"Gemini fallback {stats['gemini_fallback']}; совпадений {stats['matches']}; "
        f"время OCR {stats['ocr_ms'] / 1000:.1f} с; "
        f"из кэша {stats['cache_hits']}.")
