# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Зрение для каталога планов: модели ONNX в onnxruntime приложения.
Public namespace: montage_tool.

Детекторы аниме deepghs (лица, головы, фигуры; YOLO, MIT) — предобработка
как в dghs-imgutils (кадр растягивается до imgsz из метаданных модели или
640², RGB/255, NMS по IoU 0,7, порог — threshold.json модели). CCIP
(OpenRAIL) — признаки персонажа 768 по кадру 384² (нормировка CLIP) и
модель-метрика «разница пар»: тот же персонаж — разница ≤ порога; кластеры
— средняя связь на этой метрике (library.recluster_characters). Теги — WD
tagger v3 (SmilingWolf, Apache-2.0): квадрат с белыми полями 448², BGR
0…255, выход — вероятности; общие ≥ 0,35, персонажи ≥ 0,85, рейтинг —
наибольший из четырёх. Текст — rapidocr приложения (PP-OCRv6 small, те же
файлы моделей, что у генерации; детектор строк — по меньшей стороне 480, а
не 736: кадр 640×360 не растягивается вчетверо, текст тот же). Сам
dghs-imgutils не ставится: он требует numpy < 2. Провайдер — DirectML,
если есть; у приложения его нет, и теги и TransNetV2 идут в
Python с onnxruntime-directml (WorkerSession, dml_worker.py), иначе CPU."""
import csv
import io
import json
import struct
import sys
import threading

import numpy as np

import montage_tool as _api

DML_PYTHON_ENV = "SI_HYX_DML_PYTHON"
_DML_WORKER = _api.os.path.join(_api.os.path.dirname(_api.os.path.abspath(__file__)),
                                "dml_worker.py")
_WORKER_START_S = 120                 # запуск Python, импорт ORT и сборка графа DirectML

# Модели из jobs.ASSETS: имя → (onnx, порог-json).
DETECTORS = {"face": ("anime/face_detect_v1.4_n.onnx", "anime/face_detect_v1.4_n.threshold.json"),
             "head": ("anime/head_detect_v2.0_n.onnx", "anime/head_detect_v2.0_n.threshold.json"),
             "person": ("anime/person_detect_v1.1_n.onnx",
                        "anime/person_detect_v1.1_n.threshold.json")}
TAGGERS = {"vit": ("tagger/wd-vit-v3.onnx", "tagger/wd-v3-tags.csv"),
           "eva02": ("tagger/wd-eva02-large-v3.onnx", "tagger/wd-eva02-v3-tags.csv")}
GENERAL_T, CHARACTER_T = 0.35, 0.85
_CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)[:, None, None]
_CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)[:, None, None]


def session(path, threads=6, dml=True, worker=False):
    """InferenceSession: DirectML (iGPU) → CPU; DirectML не поднялся — CPU.
    dml=False — только CPU. Замер Vega 7 (tools/montage_dml_bench.py,
    onnxruntime-directml 1.24.4 против CPU 6 потоков): TransNetV2 ×1,4,
    детекторы ×1,5–1,75, WD ViT ×1,7 (пачка 1), CCIP ×0,74 — медленнее,
    EVA02 на DirectML не встаёт (уходит на CPU). У onnxruntime приложения
    DirectML нет: worker=True — тогда модель считается в Python с
    onnxruntime-directml (dml_python) через WorkerSession, и CPU свободен
    для остальных моделей."""
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.log_severity_level = 3
    avail = set(ort.get_available_providers())
    if dml and "DmlExecutionProvider" in avail:
        # DirectML требует последовательного исполнения и без шаблонов памяти.
        so.enable_mem_pattern = False
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        try:
            return ort.InferenceSession(path, sess_options=so,
                                        providers=["DmlExecutionProvider", "CPUExecutionProvider"])
        except Exception:                # noqa: BLE001 — iGPU не взлетел: CPU
            pass
    elif dml and worker and dml_python():
        try:
            return WorkerSession(path, dml_python(), threads)
        except (OSError, ValueError) as e:
            print(f"montage_tool: DirectML-обработчик не поднялся ({e}) — CPU", file=sys.stderr)
    return ort.InferenceSession(path, sess_options=so, providers=["CPUExecutionProvider"])


def dml_python():
    """Python с onnxruntime-directml: SI_HYX_DML_PYTHON или dml-venv в кэше
    montage_tool (как в tools/montage_dml_bench.py); нет — ""."""
    exe = _api.os.environ.get(DML_PYTHON_ENV, "")
    if not exe:
        exe = _api.os.path.join(_api.cache_dir(), "dml-venv",
                                *(("Scripts", "python.exe") if _api.os.name == "nt" else ("bin", "python")))
    return exe if _api.os.path.isfile(exe) else ""


class _Node:
    """Вход или выход модели — как NodeArg onnxruntime (имя и форма)."""

    def __init__(self, d):
        self.name, self.shape = d["name"], d["shape"]


class _Meta:
    def __init__(self, meta):
        self.custom_metadata_map = meta


class WorkerSession:
    """Сеанс модели в процессе dml_worker.py (DirectML своей среды) с видом
    InferenceSession: get_inputs, get_outputs, get_modelmeta, run. Сеанс
    на iGPU не встал (провайдер — CPU) — ValueError: CPU приложения быстрее
    без пересылки. Обработчик упал посреди работы — дальше свой сеанс на
    CPU (fell_back)."""

    def __init__(self, path, python, threads=6):
        self.path, self.threads = path, threads
        self.fell_back = False
        self._local = None
        self._lock = threading.Lock()
        self._proc = _api.subprocess.Popen(
            [python, "-I", "-X", "utf8", _DML_WORKER, str(path), str(threads)],
            stdin=_api.subprocess.PIPE, stdout=_api.subprocess.PIPE,
            stderr=_api.subprocess.DEVNULL, creationflags=_api.CREATE_NO_WINDOW)
        got = []
        t = threading.Thread(target=lambda: got.append(_frame_read(self._proc.stdout)), daemon=True)
        t.start()
        t.join(_WORKER_START_S)
        info = json.loads(got[0].decode("utf-8")) if got and got[0] else {}
        if info.get("provider") != "DmlExecutionProvider":
            self.close()
            raise ValueError(info.get("error") or f"провайдер {info.get('provider') or 'нет ответа'}")
        self._inputs = [_Node(d) for d in info["inputs"]]
        self._outputs = [_Node(d) for d in info["outputs"]]
        self._meta = _Meta(info.get("meta") or {})

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return self._outputs

    def get_modelmeta(self):
        return self._meta

    def run(self, output_names, feeds):
        with self._lock:
            if self._local is None:
                try:
                    res = self._remote(feeds)
                except (OSError, ValueError) as e:
                    print(f"montage_tool: DirectML-обработчик ({e}) — дальше CPU", file=sys.stderr)
                    self.close()
                    self._local = session(self.path, self.threads, dml=False)
                    self.fell_back = True
                else:
                    if output_names is None:
                        return res
                    names = [o.name for o in self._outputs]
                    return [res[names.index(n)] for n in output_names]
            return self._local.run(output_names, feeds)

    def _remote(self, feeds):
        p = self._proc
        if p is None or p.poll() is not None:
            raise OSError("процесс завершился")
        _frame_write(p.stdin, json.dumps({"inputs": list(feeds)}).encode("utf-8"))
        for x in feeds.values():
            buf = io.BytesIO()
            np.save(buf, np.ascontiguousarray(x), allow_pickle=False)
            _frame_write(p.stdin, buf.getvalue())
        p.stdin.flush()
        head = _frame_read(p.stdout)
        if head is None:
            raise OSError("обработчик не ответил")
        res = json.loads(head.decode("utf-8"))
        if not res.get("ok"):
            raise ValueError(res.get("error") or "ошибка обработчика")
        out = []
        for _ in range(int(res["n"])):
            data = _frame_read(p.stdout)
            if data is None:
                raise OSError("ответ оборван")
            out.append(np.load(io.BytesIO(data), allow_pickle=False))
        return out

    def close(self):
        p, self._proc = getattr(self, "_proc", None), None
        if p is None:
            return
        try:
            p.stdin.close()                  # конец stdin — обработчик выходит сам
            p.wait(timeout=5)
        except (OSError, _api.subprocess.TimeoutExpired):
            p.kill()
            p.wait()
        finally:
            p.stdout.close()

    def __del__(self):
        self.close()


def _frame_read(f):
    head = f.read(4)
    if len(head) < 4:
        return None
    n = struct.unpack("<I", head)[0]
    data = f.read(n)
    return data if len(data) == n else None


def _frame_write(f, data):
    f.write(struct.pack("<I", len(data)))
    f.write(data)


def _iou_nms(boxes, scores, thr=0.7):
    order = np.argsort(-scores)
    keep = []
    while len(order):
        i = order[0]
        keep.append(int(i))
        if len(order) == 1:
            break
        rest = order[1:]
        x0 = np.maximum(boxes[i, 0], boxes[rest, 0])
        y0 = np.maximum(boxes[i, 1], boxes[rest, 1])
        x1 = np.minimum(boxes[i, 2], boxes[rest, 2])
        y1 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(x1 - x0, 0, None) * np.clip(y1 - y0, 0, None)
        area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        iou = inter / (area[i] + area[rest] - inter + 1e-9)
        order = rest[iou <= thr]
    return keep


class Detector:
    """YOLO deepghs: detect(RGB uint8) → [(x0, y0, x1, y1, оценка)]."""

    def __init__(self, kind, ctl=None, worker=False):
        onnx, thr = DETECTORS[kind]
        # worker — обработчик DirectML: детекторы идут на iGPU до тегов (×1,5–1,75),
        # пока процессор читает текст; рядом с тегами они стояли бы в очереди.
        self.sess = session(_api.asset(onnx, ctl or _api.NO_CONTROL), worker=worker)
        with open(_api.asset(thr, ctl or _api.NO_CONTROL), "r", encoding="utf-8") as f:
            self.threshold = float(json.load(f).get("threshold", 0.25))
        meta = self.sess.get_modelmeta().custom_metadata_map
        size = json.loads(meta["imgsz"]) if "imgsz" in meta else [640, 640]
        self.h, self.w = int(size[0]), int(size[1])

    def detect(self, rgb):
        import cv2
        H, W = rgb.shape[:2]
        x = cv2.resize(rgb, (self.w, self.h), interpolation=cv2.INTER_LINEAR)
        x = (x.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        out = self.sess.run(None, {self.sess.get_inputs()[0].name: x})[0][0]
        if out.shape[0] > out.shape[1]:   # [якоря, 4+классы] → [4+классы, якоря]
            out = out.T
        scores = out[4:].max(axis=0)
        sel = scores > self.threshold
        if not sel.any():
            return []
        b, s = out[:4, sel].T, scores[sel]
        boxes = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2,
                          b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], axis=1)
        boxes *= np.array([W / self.w, H / self.h, W / self.w, H / self.h], np.float32)
        boxes = np.clip(boxes, 0, [W, H, W, H])
        return [(*map(float, boxes[i]), float(s[i])) for i in _iou_nms(boxes, s)]


class CCIP:
    """Признаки персонажа и разница пар (меньше порога — один персонаж)."""

    def __init__(self, ctl=None):
        ctl = ctl or _api.NO_CONTROL
        self.feat = session(_api.asset("anime/ccip_feat.onnx", ctl), dml=False)   # на DirectML медленнее
        self.metric = session(_api.asset("anime/ccip_metrics.onnx", ctl), threads=4)
        with open(_api.asset("anime/ccip_metrics.json", ctl), "r", encoding="utf-8") as f:
            self.threshold = float(json.load(f)["threshold"])

    def features(self, crops):
        import cv2
        if not crops:
            return np.zeros((0, 768), np.float32)
        x = np.stack([cv2.resize(c, (384, 384), interpolation=cv2.INTER_LINEAR) for c in crops])
        x = (x.astype(np.float32) / 255.0).transpose(0, 3, 1, 2)
        x = (x - _CLIP_MEAN) / _CLIP_STD
        name = self.feat.get_inputs()[0].name
        # По одной фигуре: на CPU пачка 4 медленнее на фигуру (0,74 с против 0,66).
        return np.concatenate([self.feat.run(None, {name: x[i:i + 1]})[0]
                               for i in range(len(x))]).astype(np.float32)

    def differences(self, a, b=None):
        """Разницы пар: a×a или (b задан) a×b. Модель считает «каждый с
        каждым» внутри батча, поэтому a и b — блоки (до 1024)."""
        name = self.metric.get_inputs()[0].name
        if b is None:
            return self.metric.run(None, {name: a})[0]
        return self.metric.run(None, {name: np.concatenate([a, b])})[0][:len(a), len(a):]


class Tagger:
    """WD tagger v3: tag(RGB) → (общие {тег: оценка}, персонажи, рейтинг)."""

    def __init__(self, kind="vit", ctl=None, worker=True):
        onnx, tags = TAGGERS[kind]
        ctl = ctl or _api.NO_CONTROL
        self.kind = kind
        self.sess = session(_api.asset(onnx, ctl), worker=worker)
        with open(_api.asset(tags, ctl), "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.names = [r["name"] for r in rows]
        self.cats = np.array([int(r["category"]) for r in rows])
        self.size = int(self.sess.get_inputs()[0].shape[1])
        # На iGPU пачка 4 — одна команда ~2,6 с: Windows считает видеокарту
        # зависшей (TDR, DXGI_ERROR_DEVICE_HUNG) и сбрасывает её; по одному
        # кадру ~0,6 с.
        self.step = 1 if isinstance(self.sess, WorkerSession) else 4

    def _prep(self, rgb):
        import cv2
        h, w = rgb.shape[:2]
        side = max(h, w)
        sq = np.full((side, side, 3), 255, np.uint8)
        sq[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = rgb
        sq = cv2.resize(sq, (self.size, self.size), interpolation=cv2.INTER_AREA
                        if side > self.size else cv2.INTER_CUBIC)
        return sq[:, :, ::-1].astype(np.float32)

    def tag_batch(self, images):
        if not images:
            return []
        name = self.sess.get_inputs()[0].name
        out = []
        for i in range(0, len(images), self.step):
            x = np.stack([self._prep(im) for im in images[i:i + self.step]])
            for p in self.sess.run(None, {name: x})[0]:
                rating = {self.names[k]: float(p[k]) for k in np.flatnonzero(self.cats == 9)}
                general = {self.names[k]: round(float(p[k]), 3)
                           for k in np.flatnonzero((self.cats == 0) & (p >= GENERAL_T))}
                chars = {self.names[k]: round(float(p[k]), 3)
                         for k in np.flatnonzero((self.cats == 4) & (p >= CHARACTER_T))}
                out.append((general, chars, max(rating, key=rating.get) if rating else ""))
        return out


class OCR:
    """Текст на кадре (rapidocr приложения): [(рамка x0,y0,x1,y1, текст, оценка)]."""

    def __init__(self):
        import os
        from pathlib import Path
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import ModelType, OCRVersion
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
        # Имя папки осталось от 3.9.2: набор моделей PP-OCRv6/v5 тот же, поэтому
        # после обновления rapidocr не качаем их заново.
        root = root / "SI-HYX" / "rapidocr-3.9.2"
        root.mkdir(parents=True, exist_ok=True)
        self.engine = RapidOCR(params={
            "Global.model_root_dir": str(root), "Global.use_cls": False,
            "Global.log_level": "error", "Det.thresh": .3, "Det.box_thresh": .5,
            "Det.ocr_version": OCRVersion.PPOCRV6, "Det.model_type": ModelType.SMALL,
            # Замер на 411 планах: ×2,5 быстрее 736, кадры с текстом — 74 и 74.
            "Det.limit_side_len": 480,
            "Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType.SMALL})

    def read(self, rgb):
        # Сначала только поиск строк: на большинстве кадров текста нет, и
        # распознавание (две трети времени OCR) не нужно.
        bgr = rgb[:, :, ::-1]
        H = rgb.shape[0]
        det = self.engine(bgr, use_det=True, use_cls=False, use_rec=False)
        found = det.boxes if getattr(det, "boxes", None) is not None else []
        plausible = False
        for b in found:
            b = np.asarray(b)
            w, h = float(np.ptp(b[:, 0])), float(np.ptp(b[:, 1]))
            if 0.02 * H <= min(w, h) <= 0.5 * H and max(w, h) >= 1.5 * min(w, h):
                plausible = True
                break
        if not plausible:
            return []
        # Флаги — явно: RapidOCR запоминает их с прошлого вызова.
        res = self.engine(bgr, use_det=True, use_cls=False, use_rec=True)
        boxes = res.boxes if res.boxes is not None else []
        txts = res.txts if res.txts is not None else []
        scores = res.scores if res.scores is not None else []
        out = []
        for b, t, s in zip(boxes, txts, scores):
            b = np.asarray(b)
            out.append(((float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 0].max()),
                         float(b[:, 1].max())), str(t), float(s)))
        return out
