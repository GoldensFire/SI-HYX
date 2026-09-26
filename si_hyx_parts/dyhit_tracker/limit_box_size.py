# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""limit_box_size. Public namespace: dyhit_tracker."""
import dyhit_tracker as _api


def limit_box_size(new_box, prev_box, init_box, rate=_api.SIZE_RATE,
                   k_min=_api.SIZE_MIN_K, k_max=_api.SIZE_MAX_K):
    """Оставляет предсказанный ЦЕНТР рамки, но удерживает её размер.

    Возвращает [x, y, w, h] с тем же центром, что у new_box."""
    nx, ny, nw, nh = (float(v) for v in new_box)
    cx, cy = nx + nw / 2.0, ny + nh / 2.0
    out = []
    for n, p, i0 in ((nw, float(prev_box[2]), float(init_box[2])),
                     (nh, float(prev_box[3]), float(init_box[3]))):
        v = max(p * (1.0 - rate), min(p * (1.0 + rate), n))
        v = max(i0 * k_min, min(i0 * k_max, v))
        out.append(max(2.0, v))
    w, h = out
    return [cx - w / 2.0, cy - h / 2.0, w, h]

limit_box_size.__module__ = _api.__name__
_api.limit_box_size = limit_box_size

def _to_cxcywh(box):
    x, y, w, h = (float(v) for v in box)
    return [x + w / 2.0, y + h / 2.0, w, h]

_to_cxcywh.__module__ = _api.__name__
_api._to_cxcywh = _to_cxcywh

def _to_xywh(cxcywh):
    cx, cy, w, h = cxcywh
    return [cx - w / 2.0, cy - h / 2.0, w, h]

_to_xywh.__module__ = _api.__name__
_api._to_xywh = _to_xywh

class DyHiTTracker:
    """DyHiT/HiT через ONNX Runtime: init() один раз на кадре с рамкой, дальше
    update() на каждом следующем кадре.

    Сессия создаётся лениво и переиспользуется; провайдеры выбираются как в
    остальных ONNX-помощниках проекта: CUDA → DirectML → CPU."""

    def __init__(self, model_path=None, providers=None, smooth=0.0, fps=25.0,
                 search_factor=_api.SEARCH_FACTOR, template_factor=_api.TEMPLATE_FACTOR,
                 threshold=_api.SCORE_THRESHOLD):
        self.model_path = model_path or _api.find_model_path() or _api.expected_model_path()
        self._requested = providers or ["CUDAExecutionProvider",
                                        "DmlExecutionProvider",
                                        "CPUExecutionProvider"]
        self._session = None
        self._active_provider = None
        self._lock = _api.threading.Lock()
        self._in_search = "search"
        self._in_template = "template"
        self.search_size = _api.SEARCH_SIZE
        self.template_size = _api.TEMPLATE_SIZE
        self.search_factor = float(search_factor)
        self.template_factor = float(template_factor)
        self.threshold = float(threshold)
        self.smooth = float(smooth)
        self.smoother = _api.BoxSmoother(smooth, fps)
        self.state = None
        self._template = None
        self._smoothed = None
        self._first_score = None
        self.last_score = None
        self.frame_id = 0

    name = "DyHiT (ONNX)"

    def is_available(self):
        return _api.cv2 is not None and _api.os.path.exists(self.model_path)

    @property
    def provider(self):
        return self._active_provider

    def _ensure_session(self):
        if self._session is not None:
            return self._session
        with self._lock:
            if self._session is not None:
                return self._session
            import onnxruntime as ort
            if not _api.os.path.exists(self.model_path):
                raise FileNotFoundError(f"Файл модели не найден: {self.model_path}")
            avail = set(ort.get_available_providers())
            use = [p for p in self._requested if p in avail] or ["CPUExecutionProvider"]
            so = ort.SessionOptions()
            so.log_severity_level = 3
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
            try:
                sess = ort.InferenceSession(self.model_path, sess_options=so,
                                            providers=use)
            except Exception:
                # GPU-провайдер собран, но не поднялся (нет драйверов) — считаем на CPU.
                if use != ["CPUExecutionProvider"]:
                    sess = ort.InferenceSession(self.model_path, sess_options=so,
                                                providers=["CPUExecutionProvider"])
                else:
                    raise
            self._read_io(sess)
            self._session = sess
            self._active_provider = (sess.get_providers() or ["?"])[0]
            return sess

    def _read_io(self, sess):
        """Определяет, какой вход — поисковая область, а какой — шаблон, и их
        размеры. Имена в экспортах автора — 'search'/'template', но опираться
        только на них нельзя: берём размеры из графа, а роли — по стороне входа
        (поисковая область всегда больше шаблона)."""
        ins = sess.get_inputs()
        if len(ins) < 2:
            raise RuntimeError("Модель трекера должна иметь два входа "
                               "(search и template)")

        def _side(inp):
            shape = list(inp.shape or [])
            side = shape[-1] if len(shape) >= 2 else None
            return side if isinstance(side, int) and side > 0 else None

        named = {i.name.lower(): i for i in ins}
        if "search" in named and "template" in named:
            s_in, t_in = named["search"], named["template"]
        else:
            a, b = ins[0], ins[1]
            sa, sb = _side(a) or 0, _side(b) or 0
            s_in, t_in = (a, b) if sa >= sb else (b, a)
        self._in_search, self._in_template = s_in.name, t_in.name
        self.search_size = _side(s_in) or _api.SEARCH_SIZE
        self.template_size = _side(t_in) or _api.TEMPLATE_SIZE

    def warmup(self):
        """Прогревает сессию до начала обработки (создание сессии — секунды)."""
        self._ensure_session()

    def init(self, frame_bgr, box):
        """Задаёт цель: box = (x, y, w, h) в пикселях кадра."""
        self._ensure_session()
        z_patch, _ = _api.sample_target(frame_bgr, list(box), self.template_factor,
                                   self.template_size)
        self._template = _api.preprocess_patch(z_patch)
        self.state = [float(v) for v in box]
        self._init_box = list(self.state)
        self.smoother.reset(self.state)
        self._smoothed = list(self.state)
        self._first_score = None
        self.last_score = None
        self.frame_id = 0

    def update(self, frame_bgr):
        """Считает положение цели на очередном кадре.

        Возвращает (box, score): box = [x, y, w, h] float, score — оценка
        уверенности (None, если экспорт модели её не отдаёт)."""
        if self.state is None:
            raise RuntimeError("Трекер не инициализирован (нет init)")
        sess = self._ensure_session()
        H, W = frame_bgr.shape[:2]
        self.frame_id += 1

        x_patch, resize_factor = _api.sample_target(frame_bgr, self.state,
                                               self.search_factor, self.search_size)
        outs = sess.run(None, {self._in_search: _api.preprocess_patch(x_patch),
                               self._in_template: self._template})

        boxes = _api.np.asarray(outs[0], _api.np.float32).reshape(-1, 4)
        pred = boxes.mean(axis=0) * self.search_size / resize_factor  # (cx,cy,w,h) px
        new_state = _api.clip_box(_api.map_box_back(pred, self.state, self.search_size,
                                          resize_factor), H, W, margin=10)
        # Держим размер рамки в узде — иначе она «раздувается» и уводит за собой
        # поисковое окно (см. limit_box_size).
        new_state = _api.limit_box_size(new_state, self.state, self._init_box)

        score = self._route_score(outs)
        self.last_score = score
        if score is not None:
            if self._first_score is None:
                self._first_score = score
            elif score < self.threshold * self._first_score:
                # «Сложный» кадр по логике DyHiT: доверяем предсказанию меньше —
                # сдвигаем рамку лишь наполовину, вместо рывка на промах.
                new_state = [(a + b) * 0.5 for a, b in zip(self.state, new_state)]

        self.state = new_state
        self._smoothed = self.smoother(new_state)
        return list(self._smoothed), score

    def _route_score(self, outs):
        """score по карте роутера DyHiT (второй выход графа, если он есть):
        среднее по элементам выше SCORE_T — как в levit_dyhit_stage2.forward_test."""
        if len(outs) < 2:
            return None
        try:
            arr = _api.np.asarray(outs[1], _api.np.float32).ravel()
            if arr.size == 0:
                return None
            if arr.size == 1:
                return float(arr[0])
            sel = arr[arr > _api.SCORE_T]
            val = float(sel.mean()) if sel.size else float(arr.max())
            return 0.01 if _api.math.isnan(val) else val
        except Exception:
            return None

DyHiTTracker.__module__ = _api.__name__
_api.DyHiTTracker = DyHiTTracker

class OpenCVTracker:
    """Запасной трекер на встроенных в OpenCV алгоритмах (CSRT по умолчанию,
    KCF — если CSRT в сборке нет). Используется, когда файла модели DyHiT нет:
    качество ниже, зато работает всегда и без onnxruntime."""

    def __init__(self, kind="CSRT", smooth=0.0, fps=25.0):
        self.kind = kind if hasattr(_api.cv2, f"Tracker{kind}_create") else "KCF"
        self.smooth = float(smooth)
        self.smoother = _api.BoxSmoother(smooth, fps)
        self._trk = None
        self.state = None
        self._smoothed = None
        self.last_score = None
        self.frame_id = 0

    @property
    def name(self):
        return f"{self.kind} (OpenCV)"

    def is_available(self):
        return _api.opencv_tracker_available()

    def warmup(self):
        return None

    def init(self, frame_bgr, box):
        self._trk = getattr(_api.cv2, f"Tracker{self.kind}_create")()
        x, y, w, h = (float(v) for v in box)
        self._trk.init(frame_bgr, (int(round(x)), int(round(y)),
                                   int(round(max(1, w))), int(round(max(1, h)))))
        self.state = [x, y, w, h]
        self._init_box = list(self.state)
        self.smoother.reset(self.state)
        self._smoothed = list(self.state)
        self.frame_id = 0

    def update(self, frame_bgr):
        if self._trk is None:
            raise RuntimeError("Трекер не инициализирован (нет init)")
        self.frame_id += 1
        ok, box = self._trk.update(frame_bgr)
        if ok:
            H, W = frame_bgr.shape[:2]
            self.state = _api.limit_box_size(
                _api.clip_box([float(v) for v in box], H, W, margin=10),
                self.state, self._init_box)
            self.last_score = 1.0
        else:
            # Цель потеряна — держим последнюю рамку (объект часто возвращается).
            self.last_score = 0.0
        self._smoothed = self.smoother(self.state)
        return list(self._smoothed), self.last_score

OpenCVTracker.__module__ = _api.__name__
_api.OpenCVTracker = OpenCVTracker

def create_tracker(prefer="auto", smooth=0.0, fps=25.0):
    """Создаёт трекер: DyHiT (если найдена модель и есть onnxruntime), иначе —
    запасной OpenCV. prefer: 'auto' | 'dyhit' | 'opencv'.

    При prefer='dyhit' и отсутствии модели бросает RuntimeError (вызывающий код
    сам решает, показать ли подсказку про models/). При 'auto' молча откатывается."""
    if _api.cv2 is None:
        raise RuntimeError("Не установлен OpenCV (opencv-python) — "
                           "отслеживание объекта недоступно")
    if prefer in ("auto", "dyhit") and _api.dyhit_available():
        return _api.DyHiTTracker(smooth=smooth, fps=fps)
    if prefer == "dyhit":
        raise RuntimeError(
            "Модель DyHiT не найдена. Положите .onnx-файл трекера в папку "
            f"models (ожидается {_api.expected_model_path()})")
    if not _api.opencv_tracker_available():
        raise RuntimeError("В этой сборке OpenCV нет трекеров (CSRT/KCF)")
    return _api.OpenCVTracker(smooth=smooth, fps=fps)

create_tracker.__module__ = _api.__name__
_api.create_tracker = create_tracker

def active_backend_label():
    """Короткое имя движка, который будет выбран сейчас — для подписи в диалоге."""
    if _api.dyhit_available():
        return "DyHiT (нейросеть, ONNX)"
    if _api.opencv_tracker_available():
        return "CSRT (OpenCV, запасной)"
    return "недоступно"

active_backend_label.__module__ = _api.__name__
_api.active_backend_label = active_backend_label
