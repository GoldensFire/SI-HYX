# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# rmbg_bg.py — изолированный хелпер удаления ФОНА (RMBG-2.0 / BiRefNet, ONNX).
# Выдаёт альфа-маску переднего плана, чтобы отделить объект от фона (как «Удалить
# фон» в Photoshop). Архитектура и процессный прокси повторяют lama_inpaint.py:
# создание ONNX-сессии этой модели (~360 МБ) удерживает GIL на десятки секунд,
# поэтому тяжёлую работу держим в ОТДЕЛЬНОМ ПРОЦЕССЕ — UI не виснет.
#
# Особенность сборки модели (models/model_uint8.onnx, квантованная uint8):
#   • вход  pixel_values: [1, 3, H, W] float32, RGB, ImageNet-нормализация
#       mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]; считаем на 1024×1024;
#   • выход alphas: [1, 1, H, W] float32, УЖЕ в [0..1] (sigmoid внутри графа),
#       1 = передний план (объект), 0 = фон.
# Размеры входа динамические, но модель обучена на 1024 — гоним именно так и
# масштабируем альфу обратно к размеру изображения.

import os
import sys
import threading
import multiprocessing as mp

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


# Размер, на котором считаем (модель обучена на 1024×1024).
_SIZE = 1024
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)


def _resolve_model(name: str) -> str:
    """Ищет файл модели models/<name> в нескольких местах и возвращает первый
    существующий путь (а если ни одного — самый вероятный кандидат):
      1) рядом с .exe (сборка onedir — модели лежат внешними ассетами, как bin);
      2) внутри _internal (_MEIPASS — если всё же вшиты как data);
      3) рядом с исходником (запуск из исходников / тесты)."""
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
    """Путь к models/model_uint8.onnx (см. _resolve_model)."""
    return _resolve_model("model_uint8.onnx")


class RMBGRemover:
    """Инференс RMBG-2.0 (ONNX) с авто-выбором железа. Сессия создаётся лениво и
    переиспользуется. Провайдеры выбираются автоматически: CUDA (если есть) →
    иначе CPU (недоступные отфильтровываются заранее — без падений на ПК без CUDA)."""

    SIZE = _SIZE

    def __init__(self, model_path: str = None, providers=None):
        self.model_path = model_path or default_model_path()
        # Приоритет железа: CUDA (видеокарты NVIDIA) → DirectML (ЛЮБАЯ видеокарта на
        # Windows — NVIDIA/AMD/Intel, через onnxruntime-directml) → CPU. Реально
        # доступные провайдеры отбираются ниже, недоступные молча отбрасываются.
        self._requested = providers or ["CUDAExecutionProvider",
                                        "DmlExecutionProvider",
                                        "CPUExecutionProvider"]
        self._session = None
        self._active_provider = None
        self._in = "pixel_values"
        self._out = "alphas"
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return cv2 is not None and os.path.exists(self.model_path)

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
            use = [p for p in self._requested if p in avail]
            if not use:
                use = ["CPUExecutionProvider"]
            so = ort.SessionOptions()
            # Эта квантованная модель сыпет безобидными W-варнингами о слиянии форм
            # (lenient merge) — глушим их уровнем логирования.
            so.log_severity_level = 3
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
            try:
                sess = ort.InferenceSession(self.model_path, sess_options=so,
                                            providers=use)
            except Exception:
                # GPU-провайдер скомпилирован, но не поднялся (нет драйверов/устройства)
                # — не падаем, считаем на CPU.
                if use != ["CPUExecutionProvider"]:
                    sess = ort.InferenceSession(self.model_path, sess_options=so,
                                                providers=["CPUExecutionProvider"])
                else:
                    raise
            self._session = sess
            self._active_provider = (sess.get_providers() or ["?"])[0]
            ins = sess.get_inputs()
            outs = sess.get_outputs()
            if ins:
                self._in = ins[0].name
            if outs:
                self._out = outs[0].name
            return self._session

    @property
    def device_label(self) -> str:
        p = self._active_provider or ""
        if "CUDA" in p:
            return "GPU (CUDA)"
        if "Dml" in p or "DML" in p:
            return "GPU (DirectML)"
        if "CPU" in p:
            return "CPU"
        return p or "—"

    def warmup(self):
        self._ensure_session()
        return self.device_label

    def remove(self, img_bgr, progress=None):
        """Возвращает альфа-маску переднего плана (H, W) uint8 [0..255] под размер
        входного изображения. 255 = объект (оставить), 0 = фон (прозрачный)."""
        if cv2 is None:
            raise RuntimeError("opencv-python не установлен (pip install opencv-python)")
        sess = self._ensure_session()
        img_bgr = np.ascontiguousarray(img_bgr)
        if img_bgr.ndim == 3 and img_bgr.shape[2] == 4:
            img_bgr = img_bgr[:, :, :3]
        H, W = img_bgr.shape[:2]
        if progress:
            try: progress(0, 1)
            except Exception: pass

        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        interp = cv2.INTER_AREA if max(H, W) > _SIZE else cv2.INTER_LINEAR
        rz = cv2.resize(rgb, (_SIZE, _SIZE), interpolation=interp)
        x = (rz.astype(np.float32) / 255.0 - _MEAN) / _STD
        x = np.transpose(x, (2, 0, 1))[None].astype(np.float32)   # (1,3,1024,1024)

        out = sess.run([self._out], {self._in: x})[0]
        a = np.clip(out[0, 0], 0.0, 1.0)                          # (1024,1024) [0..1]
        alpha = cv2.resize((a * 255.0).astype(np.uint8), (W, H),
                           interpolation=cv2.INTER_LINEAR)
        if progress:
            try: progress(1, 1)
            except Exception: pass
        return np.ascontiguousarray(alpha)


# ════════════════════════════════════════════════════════════════════════════
#  Процессный прокси (чтобы UI не зависал на загрузке ~360 МБ модели)
# ════════════════════════════════════════════════════════════════════════════
def _worker_loop(conn):
    """Точка входа дочернего процесса: вся работа с onnxruntime живёт здесь."""
    rem = RMBGRemover()
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
                conn.send(("ok", rem.warmup()))
            elif cmd == "remove":
                _, img = msg

                def _prog(d, t):
                    try: conn.send(("progress", int(d), int(t)))
                    except Exception: pass

                res = rem.remove(img, progress=_prog)
                conn.send(("result", res, rem.device_label))
        except Exception as e:           # pragma: no cover
            import traceback
            traceback.print_exc()
            conn.send(("error", str(e)))


class RMBGProcessRemover:
    """Тот же интерфейс (is_available/warmup/remove/device_label), но ONNX-сессия
    исполняется в дочернем процессе. Вызовы блокирующие, НО на ожидании GIL
    отпущен — безопасно дёргать из QThread. Если процесс не поднялся —
    откатываемся на внутрипроцессный RMBGRemover."""

    def __init__(self, model_path: str = None, providers=None):
        self.model_path = model_path or default_model_path()
        self._providers = providers
        self._proc = None
        self._conn = None
        self._device = "—"
        self._fallback = None
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return cv2 is not None and os.path.exists(self.model_path)

    def _ensure_proc(self):
        if self._fallback is not None:
            return False
        if self._proc is not None and self._proc.is_alive():
            return True
        ctx = mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe()
        proc = ctx.Process(target=_worker_loop, args=(child_conn,), daemon=True)
        proc.start()
        child_conn.close()
        self._proc = proc
        self._conn = parent_conn
        return True

    def _use_fallback(self):
        if self._fallback is None:
            self._fallback = RMBGRemover(self.model_path, self._providers)
        return self._fallback

    def warmup(self):
        with self._lock:
            try:
                if not self._ensure_proc():
                    return self._use_fallback().warmup()
                self._conn.send(("warmup",))
                tag, payload = self._conn.recv()
            except Exception:
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

    def remove(self, img_bgr, progress=None):
        with self._lock:
            if self._fallback is not None:
                return self._fallback.remove(img_bgr, progress=progress)
            try:
                if not self._ensure_proc():
                    return self._use_fallback().remove(img_bgr, progress=progress)
                self._conn.send(("remove", img_bgr))
                while True:
                    rec = self._conn.recv()
                    tag = rec[0]
                    if tag == "progress":
                        if progress:
                            try: progress(rec[1], rec[2])
                            except Exception: pass
                    elif tag == "result":
                        self._device = rec[2]
                        return rec[1]
                    elif tag == "error":
                        raise RuntimeError(rec[1])
            except (EOFError, BrokenPipeError, ConnectionResetError) as e:
                self._kill_proc()
                raise RuntimeError(f"Процесс удаления фона прервался: {e}")

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
