# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_models_dirs. Public namespace: dyhit_tracker."""
import dyhit_tracker as _api


def _models_dirs():
    """Каталоги, где может лежать models/ — как в lama_inpaint/rmbg_bg:
    рядом с .exe (сборка onedir), внутри _MEIPASS, рядом с исходником."""
    dirs = []
    if getattr(_api.sys, "frozen", False):
        dirs.append(_api.os.path.join(_api.os.path.dirname(_api.sys.executable), "models"))
        mei = getattr(_api.sys, "_MEIPASS", None)
        if mei:
            dirs.append(_api.os.path.join(mei, "models"))
    dirs.append(_api.os.path.join(_api.os.path.dirname(_api.os.path.abspath(_api.__file__)), "models"))
    return dirs

_models_dirs.__module__ = _api.__name__
_api._models_dirs = _models_dirs

def find_model_path():
    """Путь к файлу модели трекера или None, если её нет.

    Сначала — известные имена (MODEL_NAMES), затем любой *.onnx, в имени которого
    есть 'hit' (dyhit_ep0060.onnx, HiT_Base_ep1500.onnx и т.п.): автор выкладывает
    веса с именами эпох, и заставлять пользователя переименовывать файл незачем."""
    for d in _api._models_dirs():
        for name in _api.MODEL_NAMES:
            p = _api.os.path.join(d, name)
            if _api.os.path.exists(p):
                return p
    for d in _api._models_dirs():
        try:
            names = sorted(_api.os.listdir(d))
        except Exception:
            continue
        for n in names:
            low = n.lower()
            if low.endswith(".onnx") and "hit" in low:
                return _api.os.path.join(d, n)
    return None

find_model_path.__module__ = _api.__name__
_api.find_model_path = find_model_path

def expected_model_path():
    """Куда положить модель, если её нет (для подсказки в интерфейсе)."""
    return _api.os.path.join(_api._models_dirs()[0], _api.MODEL_NAMES[0])

expected_model_path.__module__ = _api.__name__
_api.expected_model_path = expected_model_path

def dyhit_available():
    """True, если DyHiT реально можно запустить (numpy/opencv + onnxruntime + файл)."""
    if _api.cv2 is None or _api.find_model_path() is None:
        return False
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return True

dyhit_available.__module__ = _api.__name__
_api.dyhit_available = dyhit_available

def opencv_tracker_available():
    """True, если в сборке OpenCV есть трекеры (CSRT/KCF) — запасной движок."""
    return _api.cv2 is not None and (hasattr(_api.cv2, "TrackerCSRT_create")
                                or hasattr(_api.cv2, "TrackerKCF_create"))

opencv_tracker_available.__module__ = _api.__name__
_api.opencv_tracker_available = opencv_tracker_available

# ─── Чистая геометрия (повторяет lib/test/tracker/vittrack_utils.py и box_ops) ──

def sample_target(im, target_bb, search_area_factor, output_sz):
    """Квадратный кроп вокруг рамки target_bb = [x, y, w, h], со стороной
    search_area_factor × √(w·h), приведённый к output_sz×output_sz.

    Возвращает (кроп, resize_factor). Выход за границы кадра добивается чёрным
    (BORDER_CONSTANT) — ровно как в оригинале, иначе рамка «липнет» к краю."""
    x, y, w, h = (float(v) for v in target_bb)
    crop_sz = _api.math.ceil(_api.math.sqrt(max(w, 1e-6) * max(h, 1e-6)) * search_area_factor)
    if crop_sz < 1:
        raise ValueError("Слишком маленькая рамка объекта")

    x1 = round(x + 0.5 * w - crop_sz * 0.5)
    x2 = x1 + crop_sz
    y1 = round(y + 0.5 * h - crop_sz * 0.5)
    y2 = y1 + crop_sz

    x1_pad = max(0, -x1)
    x2_pad = max(x2 - im.shape[1] + 1, 0)
    y1_pad = max(0, -y1)
    y2_pad = max(y2 - im.shape[0] + 1, 0)

    im_crop = im[y1 + y1_pad:y2 - y2_pad, x1 + x1_pad:x2 - x2_pad, :]
    im_crop = _api.cv2.copyMakeBorder(im_crop, y1_pad, y2_pad, x1_pad, x2_pad,
                                 _api.cv2.BORDER_CONSTANT)
    resize_factor = output_sz / crop_sz
    return _api.cv2.resize(im_crop, (output_sz, output_sz)), resize_factor

sample_target.__module__ = _api.__name__
_api.sample_target = sample_target

def clip_box(box, H, W, margin=10):
    """Загоняет рамку [x, y, w, h] внутрь кадра H×W, не давая ей схлопнуться."""
    x1, y1, w, h = (float(v) for v in box)
    x2, y2 = x1 + w, y1 + h
    x1 = min(max(0.0, x1), W - margin)
    x2 = min(max(float(margin), x2), float(W))
    y1 = min(max(0.0, y1), H - margin)
    y2 = min(max(float(margin), y2), float(H))
    return [x1, y1, max(float(margin), x2 - x1), max(float(margin), y2 - y1)]

clip_box.__module__ = _api.__name__
_api.clip_box = clip_box

def map_box_back(pred_box, prev_state, search_size, resize_factor):
    """Из координат поисковой области — обратно в координаты кадра.

    pred_box = (cx, cy, w, h) в пикселях исходного кадра относительно центра
    поисковой области, prev_state = рамка на предыдущем кадре [x, y, w, h]."""
    cx_prev = prev_state[0] + 0.5 * prev_state[2]
    cy_prev = prev_state[1] + 0.5 * prev_state[3]
    cx, cy, w, h = pred_box
    half_side = 0.5 * search_size / resize_factor
    cx_real = cx + (cx_prev - half_side)
    cy_real = cy + (cy_prev - half_side)
    return [cx_real - 0.5 * w, cy_real - 0.5 * h, w, h]

map_box_back.__module__ = _api.__name__
_api.map_box_back = map_box_back

def preprocess_patch(patch_bgr):
    """Кроп (BGR uint8) → тензор [1,3,S,S] float32: RGB, /255, ImageNet-норма.

    BGR→RGB здесь принципиально: сеть обучалась на RGB (загрузчик датасета в
    репозитории отдаёт RGB). В tracking/video_demo.py кадры из cv2.VideoCapture
    скармливаются как есть — это ошибка демо, точность от неё падает."""
    rgb = _api.cv2.cvtColor(patch_bgr, _api.cv2.COLOR_BGR2RGB).astype(_api.np.float32) / 255.0
    rgb = (rgb - _api._MEAN) / _api._STD
    return _api.np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])

preprocess_patch.__module__ = _api.__name__
_api.preprocess_patch = preprocess_patch

def _ema(prev, cur, alpha):
    """Экспоненциальное сглаживание рамки: alpha=0 — без сглаживания."""
    if prev is None or alpha <= 0.0:
        return list(cur)
    a = float(min(0.95, max(0.0, alpha)))
    return [p * a + c * (1.0 - a) for p, c in zip(prev, cur)]

_ema.__module__ = _api.__name__
_api._ema = _ema
