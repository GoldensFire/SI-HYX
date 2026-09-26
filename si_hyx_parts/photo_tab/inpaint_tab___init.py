# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintTab: __init__. Public namespace: photo_tab."""
import photo_tab as _api


def __init__(self, main_window):
    super(_api.InpaintTab, self).__init__()
    self.main = main_window
    # Сессию держим в дочернем процессе: её создание удерживает GIL ~10–25 c
    # и в обычном QThread заморозило бы весь UI (см. lama_inpaint.py).
    self._inpainter = _api.LaMaProcessInpainter() if _api._HAS_INPAINT else None
    # Удаление фона (RMBG-2.0) — отдельная модель/процесс, грузится лениво при
    # первом нажатии «Удалить фон» (модель ~360 МБ — не держим зря в памяти).
    self._remover = _api.RMBGProcessRemover() if _api._HAS_RMBG else None
    self._worker = None
    self._bg_worker = None
    self._cancelling = False
    self._warmup = None
    # Длительность инференса нейросети заранее НЕ известна (один проход модели
    # не даёт сигнала прогресса), поэтому НЕ выдумываем «осталось N секунд» и не
    # рисуем фейковый бар. Показываем ЧЕСТНО: бесконечный индикатор занятости +
    # реально прошедшее время (счётчик вверх). У LaMa с НЕСКОЛЬКИМИ областями
    # прогресс настоящий (готово/всего) — там бар детерминированный.
    self._proc_start = 0.0          # time.monotonic() старта (для счётчика времени)
    self._proc_region_mode = False  # LaMa: прогресс ведут реальные области
    self._proc_timer = None
    self._warmed = False
    self._device = "—"
    self._src_path = None       # путь исходника (для имени и папки сохранения)
    self._out_dir = None        # выбранная папка сохранения (None → рядом с исходником)
    # Выгрузка моделей из ОЗУ при простое. Настройка «Не выгружать…» (по умолч.
    # выкл) держит их всегда. Иначе — таймер на минуту, сбрасывается при любом
    # взаимодействии; по срабатыванию убивает процессы LaMa/RMBG.
    self._keep_models = False
    self._idle_timer = _api.QTimer(self)
    self._idle_timer.setSingleShot(True)
    self._idle_timer.setInterval(60_000)
    self._idle_timer.timeout.connect(self._maybe_unload_models)
    if not _api._HAS_INPAINT:
        self._build_unavailable()
    else:
        self._build_ui()
        self.setAcceptDrops(True)
        self.canvas.installEventFilter(self)   # взаимодействие → сброс таймера

# ── Заглушка при отсутствии зависимостей ─────────────────────────────────
def _build_unavailable(self):
    lay = _api.QVBoxLayout(self)
    msg = ("Подвкладка «Удаление объектов» недоступна.\n\n"
           "Нужны пакеты: opencv-python, numpy, onnxruntime.\n"
           "Установка:  pip install opencv-python onnxruntime")
    if _api._INPAINT_ERR:
        msg += f"\n\n{_api._INPAINT_ERR}"
    lbl = _api.QLabel(msg)
    lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color:#a6adc8; font-size:13px;")
    lay.addStretch(); lay.addWidget(lbl); lay.addStretch()
