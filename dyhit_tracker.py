# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# dyhit_tracker.py — отслеживание выбранной области на видео (visual object
# tracking): по рамке, нарисованной на одном кадре, считает положение объекта на
# каждом следующем кадре. Нужен «Монтажу», чтобы привязать текст/картинку к
# движущемуся объекту (рука, лицо, машина).
#
# Движок — DyHiT/HiT (ICCV'2023 + IJCV'2025, https://github.com/kangben258/HIT),
# запускаемый через ONNX Runtime. Здесь НЕТ PyTorch: повторён ровно тот
# препроцессинг/постпроцессинг, что в оригинальном инференсе (lib/test/tracker/
# HiT.py, DyHiT.py, tracking/video_demo.py), но на numpy/opencv:
#
#   • вход  template: [1,3,128,128] float32 — кроп вокруг цели с запасом ×2.0;
#   • вход  search:   [1,3,256,256] float32 — кроп вокруг ПРЕДЫДУЩЕГО положения
#     с запасом ×4.0; оба — RGB, /255 и ImageNet-нормализация;
#   • выход [1,1,4] float32 — (cx, cy, w, h) в долях [0..1] от поисковой области;
#     обратно в координаты кадра — map_box_back (тот же расчёт, что в репозитории).
# Размеры входов и число выходов читаются ИЗ САМОГО графа, поэтому одинаково
# работают экспорт HiT (tracking/transfer_onnx.py) и экспорт DyHiT-route1
# (см. tracking/profile_model_dyhit_route1.py) — у них общий интерфейс.
#
# «Динамическая» часть DyHiT: у route-2 сети есть голова-роутер, дающая оценку
# сложности кадра; в оригинале по ней выбирают быструю/тяжёлую ветку. Тяжёлой
# ветки в одиночном ONNX нет, поэтому, если граф отдаёт вторым выходом карту
# роутера, мы используем её ровно как в DyHiT — считаем score и сравниваем с
# threshold × score первого кадра, — но не для переключения ветки, а как
# признак «цель потеряна/кадр сложный»: рамка на такой кадр не дёргается.
#
# Файл модели НЕ поставляется в сборке (веса лежат в Google Drive автора, см.
# README репозитория HIT). Положите экспортированный .onnx в models/ рядом с
# lama_fp32.onnx — он подхватится автоматически (имена см. MODEL_NAMES). Если
# модели нет, create_tracker() возвращает запасной трекер OpenCV (CSRT) — кнопка
# в «Монтаже» работает и без нейросети, просто менее устойчиво.
#
# Qt здесь нет намеренно: модуль тестируется и переиспользуется отдельно от UI.

import math
import os
import sys
import threading

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


# Параметры инференса из experiments/HiT/HiT_Base.yaml и experiments/DyHiT/
# stage2.yaml (TEST): запас поиска ×4 от размера цели, шаблон ×2.
SEARCH_FACTOR = 4.0
TEMPLATE_FACTOR = 2.0
SEARCH_SIZE = 256
TEMPLATE_SIZE = 128

# ImageNet-нормализация (DATA.MEAN / DATA.STD тех же конфигов).
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)

# Порог отбора элементов карты роутера при подсчёте score (cfg.TEST.SCORE_T).
SCORE_T = 0.6
# Доля от score первого кадра, ниже которой кадр считается «сложным»
# (cfg.TEST.THRESHOLD; в оригинале 0.6…1.0, -9999 = «только быстрая ветка»).
SCORE_THRESHOLD = 0.75

# Имена файлов модели, которые ищем в models/ (в порядке приоритета).
MODEL_NAMES = ("dyhit.onnx", "dyhit_route1.onnx", "DyHiT.onnx",
               "hit_tiny.onnx", "hit_small.onnx", "hit_base.onnx", "hit.onnx",
               "HiT.onnx")


def _models_dirs():
    """Каталоги, где может лежать models/ — как в lama_inpaint/rmbg_bg:
    рядом с .exe (сборка onedir), внутри _MEIPASS, рядом с исходником."""
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.join(os.path.dirname(sys.executable), "models"))
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            dirs.append(os.path.join(mei, "models"))
    dirs.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"))
    return dirs


def find_model_path():
    """Путь к файлу модели трекера или None, если её нет.

    Сначала — известные имена (MODEL_NAMES), затем любой *.onnx, в имени которого
    есть 'hit' (dyhit_ep0060.onnx, HiT_Base_ep1500.onnx и т.п.): автор выкладывает
    веса с именами эпох, и заставлять пользователя переименовывать файл незачем."""
    for d in _models_dirs():
        for name in MODEL_NAMES:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    for d in _models_dirs():
        try:
            names = sorted(os.listdir(d))
        except Exception:
            continue
        for n in names:
            low = n.lower()
            if low.endswith(".onnx") and "hit" in low:
                return os.path.join(d, n)
    return None


def expected_model_path():
    """Куда положить модель, если её нет (для подсказки в интерфейсе)."""
    return os.path.join(_models_dirs()[0], MODEL_NAMES[0])


def dyhit_available():
    """True, если DyHiT реально можно запустить (numpy/opencv + onnxruntime + файл)."""
    if cv2 is None or find_model_path() is None:
        return False
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def opencv_tracker_available():
    """True, если в сборке OpenCV есть трекеры (CSRT/KCF) — запасной движок."""
    return cv2 is not None and (hasattr(cv2, "TrackerCSRT_create")
                                or hasattr(cv2, "TrackerKCF_create"))


# ─── Чистая геометрия (повторяет lib/test/tracker/vittrack_utils.py и box_ops) ──

def sample_target(im, target_bb, search_area_factor, output_sz):
    """Квадратный кроп вокруг рамки target_bb = [x, y, w, h], со стороной
    search_area_factor × √(w·h), приведённый к output_sz×output_sz.

    Возвращает (кроп, resize_factor). Выход за границы кадра добивается чёрным
    (BORDER_CONSTANT) — ровно как в оригинале, иначе рамка «липнет» к краю."""
    x, y, w, h = (float(v) for v in target_bb)
    crop_sz = math.ceil(math.sqrt(max(w, 1e-6) * max(h, 1e-6)) * search_area_factor)
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
    im_crop = cv2.copyMakeBorder(im_crop, y1_pad, y2_pad, x1_pad, x2_pad,
                                 cv2.BORDER_CONSTANT)
    resize_factor = output_sz / crop_sz
    return cv2.resize(im_crop, (output_sz, output_sz)), resize_factor


def clip_box(box, H, W, margin=10):
    """Загоняет рамку [x, y, w, h] внутрь кадра H×W, не давая ей схлопнуться."""
    x1, y1, w, h = (float(v) for v in box)
    x2, y2 = x1 + w, y1 + h
    x1 = min(max(0.0, x1), W - margin)
    x2 = min(max(float(margin), x2), float(W))
    y1 = min(max(0.0, y1), H - margin)
    y2 = min(max(float(margin), y2), float(H))
    return [x1, y1, max(float(margin), x2 - x1), max(float(margin), y2 - y1)]


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


def preprocess_patch(patch_bgr):
    """Кроп (BGR uint8) → тензор [1,3,S,S] float32: RGB, /255, ImageNet-норма.

    BGR→RGB здесь принципиально: сеть обучалась на RGB (загрузчик датасета в
    репозитории отдаёт RGB). В tracking/video_demo.py кадры из cv2.VideoCapture
    скармливаются как есть — это ошибка демо, точность от неё падает."""
    rgb = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - _MEAN) / _STD
    return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])


def _ema(prev, cur, alpha):
    """Экспоненциальное сглаживание рамки: alpha=0 — без сглаживания."""
    if prev is None or alpha <= 0.0:
        return list(cur)
    a = float(min(0.95, max(0.0, alpha)))
    return [p * a + c * (1.0 - a) for p, c in zip(prev, cur)]


# ── Гашение дрожания рамки ──────────────────────────────────────────────────
# Обычное EMA здесь не годится: коэффициент, при котором пропадает дрожание на
# стоящем объекте, даёт заметное отставание накладки на быстром движении (и
# наоборот). Поэтому берём фильтр «одно евро» (Casiez et al., 2012): срез
# фильтра растёт вместе со скоростью цели — стоит объект, срез низкий и шум
# давится; дёрнулся — срез поднимается и накладка успевает следом.
#
# Размер рамки фильтруем ОТДЕЛЬНО и жёстче: сеть заметно шумит по w/h (±5%), а
# от них зависят и якоря «над/под областью», и масштаб накладки, — на глаз это
# и есть основное «дрожание» текста.
_CUTOFF_SLOW = 5.0        # Гц при strength≈0 (почти прозрачный фильтр)
_CUTOFF_FAST = 0.45       # Гц при strength=1 (сильное сглаживание)
_SIZE_CUTOFF_K = 0.35     # размер сглаживаем во столько раз сильнее центра
_BETA_POS = 0.050         # насколько скорость (px/с) поднимает срез для центра
_BETA_SIZE = 0.010        # то же для w/h
_DERIV_CUTOFF = 1.0       # срез фильтра самой оценки скорости, Гц

# Мёртвая зона («залипание»): пока сглаженная рамка гуляет в её пределах, наружу
# отдаётся ПРЕЖНЕЕ число — на стоящем объекте накладка стоит намертво, а не
# ползает на пиксель туда-сюда. Зона сужается по мере роста скорости цели
# (_DEAD_V_REF), иначе на медленном движении накладка шла бы ступеньками.
_DEAD_POS = 0.045         # мёртвая зона центра, доля от стороны рамки
_DEAD_SIZE = 0.070        # мёртвая зона размера, доля от стороны рамки
_DEAD_MIN = 0.6           # но не меньше, px (мелкие рамки)
_DEAD_MAX = 4.0           # и не больше, px (крупные рамки)
_DEAD_V_REF = 60.0        # скорость (px/с), на которой зона сжимается вдвое


class BoxSmoother:
    """Сглаживание рамки [x, y, w, h] фильтром «одно евро» + мёртвая зона.

    strength: 0 — фильтр выключен (рамка отдаётся как есть), 1 — максимум.
    fps нужен, чтобы скорость считалась в пикселях в секунду и настройки не
    зависели от частоты кадров исходника."""

    def __init__(self, strength=0.0, fps=25.0):
        self.strength = float(min(1.0, max(0.0, strength)))
        self.fps = float(fps) if fps and fps > 0 else 25.0
        self._filt = None      # состояние фильтра (cx, cy, w, h)
        self._prev = None      # предыдущее сырое значение — для скорости
        self._vel = None       # сглаженная скорость по каждой из четырёх осей
        self._out = None       # последнее ВЫДАННОЕ значение (для мёртвой зоны)

    @property
    def enabled(self):
        return self.strength > 0.0

    def reset(self, box=None):
        self._filt = self._prev = self._vel = self._out = None
        if box is not None:
            self._filt = self._prev = self._out = _to_cxcywh(box)
            self._vel = [0.0, 0.0, 0.0, 0.0]

    def _alpha(self, cutoff):
        """Коэффициент однополюсного фильтра для заданного среза (Гц)."""
        tau = 1.0 / (2.0 * math.pi * max(1e-3, cutoff))
        te = 1.0 / self.fps
        return te / (tau + te)

    def __call__(self, box):
        if not self.enabled:
            return [float(v) for v in box]
        cur = _to_cxcywh(box)
        if self._filt is None:
            self.reset(box)
            return list(box)

        s = self.strength
        base_pos = _CUTOFF_SLOW * (_CUTOFF_FAST / _CUTOFF_SLOW) ** s
        base = (base_pos, base_pos,
                base_pos * _SIZE_CUTOFF_K, base_pos * _SIZE_CUTOFF_K)
        beta = (_BETA_POS, _BETA_POS, _BETA_SIZE, _BETA_SIZE)

        a_d = self._alpha(_DERIV_CUTOFF)
        raw_v = [(c - p) * self.fps for c, p in zip(cur, self._prev)]
        self._vel = _ema(self._vel, raw_v, 1.0 - a_d)
        self._prev = cur

        out = []
        for i in range(4):
            a = self._alpha(base[i] + beta[i] * abs(self._vel[i]))
            self._filt[i] += a * (cur[i] - self._filt[i])
            out.append(self._filt[i])

        # Мёртвая зона, сужающаяся со скоростью (см. константы выше).
        side = max(4.0, math.sqrt(max(1.0, out[2] * out[3])))
        speed = math.hypot(self._vel[0], self._vel[1])
        k = 1.0 / (1.0 + speed / _DEAD_V_REF)
        dead = [min(_DEAD_MAX, max(_DEAD_MIN, side * f)) * k
                for f in (_DEAD_POS, _DEAD_POS, _DEAD_SIZE, _DEAD_SIZE)]
        # Выход из зоны — со СМЕЩЕНИЕМ на её ширину, а не скачком к новому
        # значению: иначе накладка, простояв на месте, «щёлкала» на пару пикселей
        # в момент, когда шум наконец пробивал порог.
        held = []
        for o, p, d in zip(out, self._out, dead):
            diff = o - p
            if abs(diff) <= d:
                held.append(p)
            else:
                held.append(o - math.copysign(d, diff))
        self._out = held
        return _to_xywh(held)


# Ограничитель размера рамки. Сеть предсказывает w/h независимо на каждом кадре,
# и на сложном материале это даёт положительную обратную связь: рамка чуть
# подросла → поисковое окно (×4 от неё) стало шире → цель в нём мельче → рамка
# ещё больше. За пару десятков кадров рамка раздувается на весь кадр, цель
# теряется окончательно, а привязанный текст начинает скакать по экрану. Ни один
# реальный объект не меняет размер на десятки процентов за кадр, поэтому
# ограничиваем и скорость изменения, и абсолютный разброс от исходной рамки.
SIZE_RATE = 0.06          # максимальное изменение стороны за кадр (доля)
SIZE_MIN_K = 0.40         # во сколько раз рамка может стать меньше исходной
SIZE_MAX_K = 3.00         # и во сколько больше


def limit_box_size(new_box, prev_box, init_box, rate=SIZE_RATE,
                   k_min=SIZE_MIN_K, k_max=SIZE_MAX_K):
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


def _to_cxcywh(box):
    x, y, w, h = (float(v) for v in box)
    return [x + w / 2.0, y + h / 2.0, w, h]


def _to_xywh(cxcywh):
    cx, cy, w, h = cxcywh
    return [cx - w / 2.0, cy - h / 2.0, w, h]


class DyHiTTracker:
    """DyHiT/HiT через ONNX Runtime: init() один раз на кадре с рамкой, дальше
    update() на каждом следующем кадре.

    Сессия создаётся лениво и переиспользуется; провайдеры выбираются как в
    остальных ONNX-помощниках проекта: CUDA → DirectML → CPU."""

    def __init__(self, model_path=None, providers=None, smooth=0.0, fps=25.0,
                 search_factor=SEARCH_FACTOR, template_factor=TEMPLATE_FACTOR,
                 threshold=SCORE_THRESHOLD):
        self.model_path = model_path or find_model_path() or expected_model_path()
        self._requested = providers or ["CUDAExecutionProvider",
                                        "DmlExecutionProvider",
                                        "CPUExecutionProvider"]
        self._session = None
        self._active_provider = None
        self._lock = threading.Lock()
        self._in_search = "search"
        self._in_template = "template"
        self.search_size = SEARCH_SIZE
        self.template_size = TEMPLATE_SIZE
        self.search_factor = float(search_factor)
        self.template_factor = float(template_factor)
        self.threshold = float(threshold)
        self.smooth = float(smooth)
        self.smoother = BoxSmoother(smooth, fps)
        self.state = None
        self._template = None
        self._smoothed = None
        self._first_score = None
        self.last_score = None
        self.frame_id = 0

    name = "DyHiT (ONNX)"

    def is_available(self):
        return cv2 is not None and os.path.exists(self.model_path)

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
            if not os.path.exists(self.model_path):
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
        self.search_size = _side(s_in) or SEARCH_SIZE
        self.template_size = _side(t_in) or TEMPLATE_SIZE

    def warmup(self):
        """Прогревает сессию до начала обработки (создание сессии — секунды)."""
        self._ensure_session()

    def init(self, frame_bgr, box):
        """Задаёт цель: box = (x, y, w, h) в пикселях кадра."""
        self._ensure_session()
        z_patch, _ = sample_target(frame_bgr, list(box), self.template_factor,
                                   self.template_size)
        self._template = preprocess_patch(z_patch)
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

        x_patch, resize_factor = sample_target(frame_bgr, self.state,
                                               self.search_factor, self.search_size)
        outs = sess.run(None, {self._in_search: preprocess_patch(x_patch),
                               self._in_template: self._template})

        boxes = np.asarray(outs[0], np.float32).reshape(-1, 4)
        pred = boxes.mean(axis=0) * self.search_size / resize_factor  # (cx,cy,w,h) px
        new_state = clip_box(map_box_back(pred, self.state, self.search_size,
                                          resize_factor), H, W, margin=10)
        # Держим размер рамки в узде — иначе она «раздувается» и уводит за собой
        # поисковое окно (см. limit_box_size).
        new_state = limit_box_size(new_state, self.state, self._init_box)

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
            arr = np.asarray(outs[1], np.float32).ravel()
            if arr.size == 0:
                return None
            if arr.size == 1:
                return float(arr[0])
            sel = arr[arr > SCORE_T]
            val = float(sel.mean()) if sel.size else float(arr.max())
            return 0.01 if math.isnan(val) else val
        except Exception:
            return None


class OpenCVTracker:
    """Запасной трекер на встроенных в OpenCV алгоритмах (CSRT по умолчанию,
    KCF — если CSRT в сборке нет). Используется, когда файла модели DyHiT нет:
    качество ниже, зато работает всегда и без onnxruntime."""

    def __init__(self, kind="CSRT", smooth=0.0, fps=25.0):
        self.kind = kind if hasattr(cv2, f"Tracker{kind}_create") else "KCF"
        self.smooth = float(smooth)
        self.smoother = BoxSmoother(smooth, fps)
        self._trk = None
        self.state = None
        self._smoothed = None
        self.last_score = None
        self.frame_id = 0

    @property
    def name(self):
        return f"{self.kind} (OpenCV)"

    def is_available(self):
        return opencv_tracker_available()

    def warmup(self):
        return None

    def init(self, frame_bgr, box):
        self._trk = getattr(cv2, f"Tracker{self.kind}_create")()
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
            self.state = limit_box_size(
                clip_box([float(v) for v in box], H, W, margin=10),
                self.state, self._init_box)
            self.last_score = 1.0
        else:
            # Цель потеряна — держим последнюю рамку (объект часто возвращается).
            self.last_score = 0.0
        self._smoothed = self.smoother(self.state)
        return list(self._smoothed), self.last_score


def create_tracker(prefer="auto", smooth=0.0, fps=25.0):
    """Создаёт трекер: DyHiT (если найдена модель и есть onnxruntime), иначе —
    запасной OpenCV. prefer: 'auto' | 'dyhit' | 'opencv'.

    При prefer='dyhit' и отсутствии модели бросает RuntimeError (вызывающий код
    сам решает, показать ли подсказку про models/). При 'auto' молча откатывается."""
    if cv2 is None:
        raise RuntimeError("Не установлен OpenCV (opencv-python) — "
                           "отслеживание объекта недоступно")
    if prefer in ("auto", "dyhit") and dyhit_available():
        return DyHiTTracker(smooth=smooth, fps=fps)
    if prefer == "dyhit":
        raise RuntimeError(
            "Модель DyHiT не найдена. Положите .onnx-файл трекера в папку "
            f"models (ожидается {expected_model_path()})")
    if not opencv_tracker_available():
        raise RuntimeError("В этой сборке OpenCV нет трекеров (CSRT/KCF)")
    return OpenCVTracker(smooth=smooth, fps=fps)


def active_backend_label():
    """Короткое имя движка, который будет выбран сейчас — для подписи в диалоге."""
    if dyhit_available():
        return "DyHiT (нейросеть, ONNX)"
    if opencv_tracker_available():
        return "CSRT (OpenCV, запасной)"
    return "недоступно"
