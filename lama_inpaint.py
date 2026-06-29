# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# lama_inpaint.py — изолированный хелпер инференса модели LaMa (ONNX) для
# качественного удаления водяных знаков/надписей (аналог Spot Healing Brush).
#
# Здесь НЕТ Qt — только numpy / opencv / onnxruntime, чтобы класс можно было
# тестировать и переиспользовать отдельно от интерфейса. Конвертация
# QImage <-> numpy живёт в слое интерфейса (tabs.py).
#
# Особенность ИМЕННО этой сборки модели (models/lama_fp32.onnx):
#   • вход  image: [N, 3, 512, 512] float32, RGB, нормализован в [0..1] (/255);
#   • вход  mask:  [N, 1, 512, 512] float32, {0,1}, 1 = «дыра» (что стираем);
#   • выход output:[N, 3, 512, 512] float32, УЖЕ в [0..255] (домножать НЕ нужно),
#     причём вне маски выход в точности равен входу.
# Размер входа ФИКСИРОВАННЫЙ (512×512) — поэтому вырезанный фрагмент мы приводим
# к 512×512 (через квадратный reflect-паддинг, чтобы не искажать пропорции), а
# результат масштабируем обратно. «Кратность 8» тут неприменима — она нужна для
# динамических экспортов LaMa, а у нас вход жёстко 512.

import os
import sys
import threading
import multiprocessing as mp

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


# Размер входа модели (жёстко зашит в графе ONNX).
_MODEL_SIZE = 512


def _resolve_model(name: str) -> str:
    """Ищет файл модели models/<name> в нескольких местах и возвращает первый
    существующий путь (а если ни одного — самый вероятный кандидат):
      1) рядом с .exe (сборка onedir — модели лежат внешними ассетами, как bin);
      2) внутри _internal (_MEIPASS — если всё же вшиты как data);
      3) рядом с исходником (запуск из исходников / тесты).
    Так одна и та же функция работает и в сборке, и из исходников."""
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(os.path.dirname(sys.executable), "models", name))
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            cands.append(os.path.join(mei, "models", name))
    cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "models", name))
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


def default_model_path() -> str:
    """Путь к models/lama_fp32.onnx (см. _resolve_model)."""
    return _resolve_model("lama_fp32.onnx")


def load_bgr(path: str) -> "np.ndarray":
    """Грузит изображение как BGR uint8 (H, W, 3). Unicode-безопасно на Windows
    (cv2.imread спотыкается о кириллицу в пути — читаем байтами и декодируем).
    Для форматов, которые OpenCV не знает (avif/heic/svg…), откатываемся на Pillow.
    Бросает исключение, если открыть не удалось."""
    if cv2 is None:
        raise RuntimeError("opencv-python не установлен (pip install opencv-python)")
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if img is not None:
        return np.ascontiguousarray(img)
    # Фолбэк через Pillow (avif/heic/и т.п.) или общий загрузчик приложения.
    try:
        from utils import open_image_any
        pil = open_image_any(path).convert("RGB")
    except Exception:
        from PIL import Image
        pil = Image.open(path).convert("RGB")
    rgb = np.asarray(pil, dtype=np.uint8)
    return np.ascontiguousarray(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def save_bgr(path: str, img_bgr: "np.ndarray", quality: int = 95) -> None:
    """Сохраняет BGR uint8 в файл по расширению. Unicode-безопасно (imencode +
    tofile). PNG — без потерь, JPEG/WEBP — с качеством quality."""
    if cv2 is None:
        raise RuntimeError("opencv-python не установлен")
    ext = os.path.splitext(path)[1].lower() or ".png"
    params = []
    if ext in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
    elif ext == ".webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, int(quality)]
    ok, buf = cv2.imencode(ext, img_bgr, params)
    if not ok:
        raise RuntimeError(f"Не удалось закодировать изображение в {ext}")
    buf.tofile(path)


def _round_box(x0, y0, x1, y1, pad, w, h):
    """Расширяет прямоугольник на pad во все стороны и зажимает в границы (w, h)."""
    x0 = max(0, int(x0) - pad)
    y0 = max(0, int(y0) - pad)
    x1 = min(w, int(x1) + pad)
    y1 = min(h, int(y1) + pad)
    return x0, y0, x1, y1


def _merge_boxes(boxes):
    """Объединяет пересекающиеся/касающиеся прямоугольники (x0,y0,x1,y1) в их
    общие охватывающие. Так несколько близких пятен маски обрабатываются одним
    проходом, а далеко разнесённые — по отдельности (быстрее и качественнее, чем
    один общий bbox на всё изображение)."""
    boxes = list(boxes)
    changed = True
    while changed:
        changed = False
        out = []
        while boxes:
            a = boxes.pop()
            ax0, ay0, ax1, ay1 = a
            merged = True
            while merged:
                merged = False
                rest = []
                for b in boxes:
                    bx0, by0, bx1, by1 = b
                    # Пересекаются (или вплотную) — по обеим осям.
                    if ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1:
                        ax0, ay0 = min(ax0, bx0), min(ay0, by0)
                        ax1, ay1 = max(ax1, bx1), max(ay1, by1)
                        merged = True
                        changed = True
                    else:
                        rest.append(b)
                boxes = rest
            out.append((ax0, ay0, ax1, ay1))
        boxes = out
    return boxes


class LaMaInpainter:
    """Инференс LaMa (ONNX) с адаптивным выбором железа и Crop-техникой.

    • Сессия создаётся лениво (при первом inpaint) и переиспользуется.
    • Провайдеры выбираются автоматически: CUDA (если есть видеокарта NVIDIA с
      рабочими CUDA-драйверами) → иначе CPU. Недоступные провайдеры
      отфильтровываются заранее, поэтому никаких падений/страшных варнингов на
      машинах без CUDA.
    • Crop-техника: модель применяется не ко всему изображению, а к небольшому
      фрагменту вокруг маски (bbox + отступ), что делает обработку быстрой даже
      на CPU и на больших картинках.
    """

    MODEL_SIZE = _MODEL_SIZE

    def __init__(self, model_path: str = None, providers=None):
        self.model_path = model_path or default_model_path()
        # Приоритет железа: CUDA (NVIDIA) → DirectML (любая видеокарта на Windows,
        # onnxruntime-directml) → CPU. Недоступные провайдеры отбрасываются ниже.
        self._requested = providers or ["CUDAExecutionProvider",
                                        "DmlExecutionProvider",
                                        "CPUExecutionProvider"]
        self._session = None
        self._active_provider = None
        self._in_img = "image"
        self._in_mask = "mask"
        self._out = "output"
        self._lock = threading.Lock()

    # ── Сессия / железо ─────────────────────────────────────────────────────
    def is_available(self) -> bool:
        return cv2 is not None and os.path.exists(self.model_path)

    def _ensure_session(self):
        """Лениво и потокобезопасно создаёт InferenceSession."""
        if self._session is not None:
            return self._session
        with self._lock:
            if self._session is not None:
                return self._session
            import onnxruntime as ort
            if not os.path.exists(self.model_path):
                raise FileNotFoundError(
                    f"Файл модели не найден: {self.model_path}")
            avail = set(ort.get_available_providers())
            # Берём только реально доступные провайдеры в заданном приоритете;
            # если ни один не подошёл — CPU (есть всегда). Так на ПК без CUDA
            # библиотека «бесшумно» работает на процессоре.
            use = [p for p in self._requested if p in avail]
            if not use:
                use = ["CPUExecutionProvider"]
            so = ort.SessionOptions()
            # EXTENDED — лучший баланс для этой 200-МБ модели: создание сессии
            # ~вдвое быстрее, чем ENABLE_ALL (≈11 с против ≈22 с на CPU), при той
            # же скорости инференса (~3 с/тайл). Поэтому модель грузим один раз и
            # переиспользуем, а в UI прогреваем сессию заранее в фоне.
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
            try:
                sess = ort.InferenceSession(
                    self.model_path, sess_options=so, providers=use)
            except Exception:
                # GPU-провайдер есть в сборке, но не поднялся (нет драйверов/устройства)
                # — не падаем, откатываемся на CPU.
                if use != ["CPUExecutionProvider"]:
                    sess = ort.InferenceSession(
                        self.model_path, sess_options=so,
                        providers=["CPUExecutionProvider"])
                else:
                    raise
            self._session = sess
            self._active_provider = (sess.get_providers() or ["?"])[0]
            ins = sess.get_inputs()
            outs = sess.get_outputs()
            # Имена входов/выходов берём из модели (на случай иных экспортов).
            if len(ins) >= 2:
                self._in_img, self._in_mask = ins[0].name, ins[1].name
            if outs:
                self._out = outs[0].name
            return self._session

    @property
    def device_label(self) -> str:
        """Человекочитаемое имя активного устройства (для статуса в UI)."""
        p = self._active_provider or ""
        if "CUDA" in p:
            return "GPU (CUDA)"
        if "Dml" in p or "DML" in p:
            return "GPU (DirectML)"
        if "CPU" in p:
            return "CPU"
        return p or "—"

    def warmup(self):
        """Заранее создаёт сессию (например, в фоне), чтобы первый запуск не ждал
        загрузку 200-МБ модели."""
        self._ensure_session()
        return self.device_label

    # ── Препроцессинг одного фрагмента ──────────────────────────────────────
    def _run_tile(self, crop_bgr: "np.ndarray", crop_mask: "np.ndarray"):
        """Прогон одного фрагмента через модель.
        crop_bgr: (h, w, 3) uint8 BGR; crop_mask: (h, w) uint8 {0,255}.
        Возвращает (h, w, 3) uint8 BGR — очищенный фрагмент того же размера."""
        sess = self._ensure_session()
        h, w = crop_mask.shape[:2]

        # Квадратный reflect-паддинг: приводим к квадрату БЕЗ искажения пропорций,
        # затем ресайз к 512. Зеркальный паддинг даёт модели правдоподобный
        # контекст по краям; добавленная область НЕ является дырой (mask=0).
        side = max(h, w)
        top = (side - h) // 2
        bottom = side - h - top
        left = (side - w) // 2
        right = side - w - left
        img_sq = cv2.copyMakeBorder(crop_bgr, top, bottom, left, right,
                                    cv2.BORDER_REFLECT_101)
        msk_sq = cv2.copyMakeBorder(crop_mask, top, bottom, left, right,
                                    cv2.BORDER_CONSTANT, value=0)

        # К размеру модели. Картинку — INTER_AREA при уменьшении (меньше муара).
        interp = cv2.INTER_AREA if side > _MODEL_SIZE else cv2.INTER_LINEAR
        img_r = cv2.resize(img_sq, (_MODEL_SIZE, _MODEL_SIZE), interpolation=interp)
        msk_r = cv2.resize(msk_sq, (_MODEL_SIZE, _MODEL_SIZE),
                           interpolation=cv2.INTER_LINEAR)

        # Тензоры. Image: BGR→RGB, /255, CHW, float32. Mask: бинаризуем (1=дыра).
        rgb = cv2.cvtColor(img_r, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img_t = np.transpose(rgb, (2, 0, 1))[None]                  # (1,3,512,512)
        msk_bin = (msk_r > 127).astype(np.float32)
        msk_t = msk_bin[None, None]                                 # (1,1,512,512)

        out = sess.run([self._out],
                       {self._in_img: img_t, self._in_mask: msk_t})[0]
        # Выход уже в [0..255] (домножать не нужно) — только клип и в uint8.
        out = np.clip(out[0], 0, 255).astype(np.uint8)             # (3,512,512)
        out_rgb = np.transpose(out, (1, 2, 0))                      # (512,512,3) RGB
        out_bgr = cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR)

        # Обратно к квадрату стороны side, затем убираем reflect-поля → (h, w).
        out_sq = cv2.resize(out_bgr, (side, side), interpolation=cv2.INTER_LINEAR)
        return out_sq[top:top + h, left:left + w]

    # ── Публичный API ───────────────────────────────────────────────────────
    def inpaint(self, img_bgr, mask, pad: int = 32, dilate: int = 4,
                feather: float = 2.0, progress=None):
        """Удаляет область(и) под маской.

        img_bgr : (H, W, 3) uint8 BGR — исходное изображение.
        mask    : (H, W) uint8 — закрашенная пользователем маска (>0 = удалить).
        pad     : отступ контекста вокруг bbox (px) перед вырезанием.
        dilate  : насколько расширить маску перед инференсом (px), чтобы гарантировать
                  полное покрытие штриха кистью.
        feather : размытие края маски при вклейке (px) — бесшовный переход.
        progress: callable(done, total) — опциональный колбэк прогресса по регионам.

        Возвращает НОВЫЙ массив (H, W, 3) uint8 BGR. Исходник не меняется. Если
        маска пуста — возвращает копию исходника.
        """
        if cv2 is None:
            raise RuntimeError("opencv-python не установлен (pip install opencv-python)")
        img_bgr = np.ascontiguousarray(img_bgr)
        H, W = img_bgr.shape[:2]
        if mask.shape[:2] != (H, W):
            mask = cv2.resize(mask, (W, H), interpolation=cv2.INTER_NEAREST)
        mask = (mask > 127).astype(np.uint8) * 255
        if int(mask.max()) == 0:
            return img_bgr.copy()

        # Чуть расширяем маску — кисть может не докрывать пиксель-в-пиксель.
        if dilate > 0:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                          (2 * dilate + 1, 2 * dilate + 1))
            mask = cv2.dilate(mask, k)

        # Связные компоненты → их bbox с отступом → слияние пересекающихся.
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        boxes = []
        for i in range(1, n):
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            bw = stats[i, cv2.CC_STAT_WIDTH]
            bh = stats[i, cv2.CC_STAT_HEIGHT]
            boxes.append(_round_box(x, y, x + bw, y + bh, pad, W, H))
        boxes = _merge_boxes(boxes)

        result = img_bgr.copy()
        total = len(boxes) or 1
        for idx, (x0, y0, x1, y1) in enumerate(boxes):
            if progress:
                try:
                    progress(idx, total)
                except Exception:
                    pass
            crop_img = img_bgr[y0:y1, x0:x1]
            crop_msk = mask[y0:y1, x0:x1]
            if int(crop_msk.max()) == 0:
                continue
            cleaned = self._run_tile(crop_img, crop_msk)

            # Бесшовная вклейка: меняем ТОЛЬКО область маски, край пера размываем,
            # чтобы не было видно шва (вне маски ресайз слегка «мылит» — туда не лезем).
            m = crop_msk.astype(np.float32) / 255.0
            if feather and feather > 0:
                m = cv2.GaussianBlur(m, (0, 0), sigmaX=float(feather))
            m3 = m[..., None]
            blended = result[y0:y1, x0:x1].astype(np.float32) * (1.0 - m3) \
                + cleaned.astype(np.float32) * m3
            result[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)

        if progress:
            try:
                progress(total, total)
            except Exception:
                pass
        return result


# ════════════════════════════════════════════════════════════════════════════
#  Процессный прокси (чтобы UI не зависал)
# ════════════════════════════════════════════════════════════════════════════
# Создание ONNX-сессии для этой 200-МБ модели УДЕРЖИВАЕТ GIL на все ~10–25 c
# (замерено: onnxruntime.InferenceSession не отпускает GIL во время построения
# графа). Поэтому «фоновый» QThread НЕ спасает — поток-прогрев держит GIL и
# подвешивает весь Qt-интерфейс. Решение: держать сессию в ОТДЕЛЬНОМ ПРОЦЕССЕ.
# Тогда тяжёлая загрузка идёт в дочернем процессе, а вызовы из UI-процесса лишь
# ждут ответ по пайпу (recv отпускает GIL) — окно остаётся отзывчивым.

def _worker_loop(conn):
    """Точка входа дочернего процесса. ВСЯ работа с onnxruntime (прогрев +
    инференс) живёт здесь, поэтому её GIL-блокирующая загрузка не морозит
    UI-процесс. Общается с родителем простыми кортежами по Pipe."""
    inp = LaMaInpainter()
    while True:
        try:
            msg = conn.recv()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg or msg[0] == "stop":
            break
        cmd = msg[0]
        try:
            if cmd == "warmup":
                conn.send(("ok", inp.warmup()))
            elif cmd == "inpaint":
                _, img, mask, kw = msg

                def _prog(d, t):
                    try:
                        conn.send(("progress", int(d), int(t)))
                    except Exception:
                        pass

                res = inp.inpaint(img, mask, progress=_prog, **kw)
                conn.send(("result", res, inp.device_label))
        except Exception as e:           # pragma: no cover
            import traceback
            traceback.print_exc()
            conn.send(("error", str(e)))


class LaMaProcessInpainter:
    """Тот же интерфейс, что у LaMaInpainter (is_available/warmup/inpaint/
    device_label), но ONNX-сессия исполняется в дочернем процессе.

    Вызовы блокирующие (ждут ответ по пайпу), НО на ожидании GIL отпущен —
    поэтому их безопасно дёргать из QThread: UI-поток не подвисает. Если
    запустить дочерний процесс не удалось (например, в экзотической сборке),
    аккуратно откатываемся на внутрипроцессный LaMaInpainter."""

    def __init__(self, model_path: str = None, providers=None):
        self.model_path = model_path or default_model_path()
        self._providers = providers
        self._proc = None
        self._conn = None
        self._device = "—"
        self._fallback = None            # LaMaInpainter, если процесс не поднялся
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return cv2 is not None and os.path.exists(self.model_path)

    # ── Дочерний процесс ─────────────────────────────────────────────────────
    def _ensure_proc(self):
        if self._fallback is not None:
            return False
        if self._proc is not None and self._proc.is_alive():
            return True
        ctx = mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe()
        proc = ctx.Process(target=_worker_loop, args=(child_conn,), daemon=True)
        proc.start()
        child_conn.close()              # дочерний конец нужен только потомку
        self._proc = proc
        self._conn = parent_conn
        return True

    def _use_fallback(self):
        if self._fallback is None:
            self._fallback = LaMaInpainter(self.model_path, self._providers)
        return self._fallback

    # ── API ──────────────────────────────────────────────────────────────────
    def warmup(self):
        with self._lock:
            try:
                if not self._ensure_proc():
                    return self._use_fallback().warmup()
                self._conn.send(("warmup",))
                tag, payload = self._conn.recv()
            except Exception:
                # Процесс/пайп не задались — переходим на внутрипроцессный режим.
                self._kill_proc()
                return self._use_fallback().warmup()
            if tag == "error":
                raise RuntimeError(payload)
            self._device = payload
            return payload

    @property
    def device_label(self) -> str:
        if self._fallback is not None:
            return self._fallback.device_label
        return self._device

    def inpaint(self, img_bgr, mask, pad: int = 32, dilate: int = 4,
                feather: float = 2.0, progress=None):
        with self._lock:
            if self._fallback is not None:
                return self._fallback.inpaint(
                    img_bgr, mask, pad=pad, dilate=dilate,
                    feather=feather, progress=progress)
            try:
                if not self._ensure_proc():
                    return self._use_fallback().inpaint(
                        img_bgr, mask, pad=pad, dilate=dilate,
                        feather=feather, progress=progress)
                kw = dict(pad=pad, dilate=dilate, feather=feather)
                self._conn.send(("inpaint", img_bgr, mask, kw))
                while True:
                    rec = self._conn.recv()
                    tag = rec[0]
                    if tag == "progress":
                        if progress:
                            try:
                                progress(rec[1], rec[2])
                            except Exception:
                                pass
                    elif tag == "result":
                        self._device = rec[2]
                        return rec[1]
                    elif tag == "error":
                        raise RuntimeError(rec[1])
            except (EOFError, BrokenPipeError, ConnectionResetError) as e:
                self._kill_proc()
                raise RuntimeError(f"Процесс обработки прервался: {e}")

    def unload(self):
        """Выгружает модель из ОЗУ: убивает дочерний процесс (или сбрасывает
        in-process фолбэк). Следующий вызов поднимет всё заново."""
        with self._lock:
            self._kill_proc()
            self._fallback = None
            self._device = "—"

    def _kill_proc(self):
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        try:
            if self._proc is not None and self._proc.is_alive():
                self._proc.terminate()
        except Exception:
            pass
        self._proc = None
        self._conn = None
