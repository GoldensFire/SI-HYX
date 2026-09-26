# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintTab: keyPressEvent. Public namespace: photo_tab."""
import photo_tab as _api


def keyPressEvent(self, ev):
    mods = ev.modifiers()
    # Резерв Ctrl+Z/Ctrl+Y для кириллической раскладки: физическая Z/Y там
    # шлёт Qt-код кириллической буквы, и QShortcut("Ctrl+Z"/"Ctrl+Y") выше
    # (см. self._sc_undo/_sc_redo) на ней молча не срабатывает (та же
    # природа бага, что и с WASD — см. _pan_dir_from_event). Событие сюда
    # доходит, только если QShortcut его не поймал — для латиницы там уже
    # сработало, тут лишь докрывается случай перевода раскладкой.
    if mods & _api.Qt.KeyboardModifier.ControlModifier:
        try:
            vk = ev.nativeVirtualKey()
        except Exception:
            vk = 0
        if vk == self._VK_Z:
            (self.canvas.redo() if (mods & _api.Qt.KeyboardModifier.ShiftModifier)
             else self.canvas.undo())
            ev.accept()
            return
        if vk == self._VK_Y:
            self.canvas.redo()
            ev.accept()
            return
    # Резерв: WASD/стрелки панорамируют, даже если фокус не на холсте (клавиши
    # всплывают сюда от кнопок панели). Ctrl не трогаем (Ctrl+Z/Y и пр.).
    pan_dir = _api._pan_dir_from_event(ev)
    if (not (mods & _api.Qt.KeyboardModifier.ControlModifier)
            and pan_dir is not None and hasattr(self, "canvas")
            and self.canvas.has_image()):
        step = 120 if (mods & _api.Qt.KeyboardModifier.ShiftModifier) else 50
        sx, sy = pan_dir
        self.canvas._pan_by(sx * step, sy * step)
        ev.accept()
        return
    super(_api.InpaintTab, self).keyPressEvent(ev)

def _on_brush(self, v):
    self.lbl_brush.setText(str(v))
    self.canvas.set_brush(v)

def _on_blur_strength(self, v):
    self.lbl_blur.setText(str(v))
    self.canvas.set_blur_strength(v)

def _set_status(self, text):
    self.lbl_status.setText(text)

def set_left_width(self, w):
    """PhotoTab задаёт ширину левой панели под переключатель режима, чтобы
        обе подписи («Редактирование фото» / «Объединить фото») влезали целиком."""
    if hasattr(self, "_left_col"):
        self._left_col.setFixedWidth(int(w))

def _refresh_enabled(self):
    has = self.canvas.has_image() if hasattr(self, "canvas") else False
    busy = ((self._worker is not None and self._worker.isRunning())
            or (self._bg_worker is not None and self._bg_worker.isRunning()))
    for b in (self.btn_run, self.btn_bg, self.btn_bars, self.btn_save, self.btn_fit):
        b.setEnabled(has and not busy)
    self.btn_open.setEnabled(not busy)
    self.btn_outdir.setEnabled(not busy)
    # «Ластик» стирает ТОЛЬКО ещё не вжатые мазки «Кисти» (см. _paint_image_to) —
    # пока их нет, стирать нечего, кнопка неактивна.
    self.btn_erase.setEnabled(has and not busy and bool(getattr(self.canvas, "_has_paint", False)))
    # Во время обработки холст не трогаем (мазки кистью всё равно сбросятся
    # результатом) — блокируем ввод, оставляя картинку видимой.
    self.canvas.setEnabled(has and not busy)

# ── Открытие / сохранение / drag-n-drop ──────────────────────────────────
def _open(self):
    # По умолчанию открываем папку, которую сейчас показывает общая лента
    # файлов сверху (RecentFilesStrip), иначе — папку прошлого исходника.
    start = self._ribbon_folder() or \
        (_api.os.path.dirname(self._src_path) if self._src_path else "")
    path, _ = _api.QFileDialog.getOpenFileName(
        self, "Открыть изображение", start,
        "Изображения (*.png *.jpg *.jpeg *.bmp *.webp *.tiff *.tif *.avif *.heic *.heif)")
    if path:
        self._load(path)

def _ribbon_folder(self) -> str:
    """Папка, которую показывает общая лента файлов сверху (если задана)."""
    try:
        strip = getattr(self.main, "recent_strip", None)
        folder = strip._effective_folder() if strip is not None else ""
        return folder if folder and _api.os.path.isdir(folder) else ""
    except Exception:
        return ""

def _clear_canvas(self):
    self.canvas.clear_canvas()
    self._src_path = None
    self._refresh_enabled()

def _load(self, path):
    try:
        if self.canvas.has_image():
            # Overlay-режим: загружаем с сохранением альфа-канала (PNG-прозрачность).
            arr = _api._load_image_alpha(path)
            self.canvas.add_overlay_image(arr)
            self._set_status(
                f"Поверх — {_api.os.path.basename(path)}. "
                "Перетащите на нужное место; Enter или клик вне — вжать.")
        else:
            # Сохраняем альфа-канал при первом открытии — иначе прозрачность
            # PNG/WEBP/AVIF терялась бы уже на этом шаге (cv2.IMREAD_COLOR
            # альфу отбрасывает), а «Удалить фон» потом рисовал бы поверх
            # чужого фона, оставшегося от исходника.
            arr = _api._load_image_alpha(path)
            if arr.ndim == 3 and arr.shape[2] == 4:
                self.canvas.set_image_bgr(arr[:, :, :3])
                self.canvas.apply_cutout(arr[:, :, 3])
            else:
                self.canvas.set_image_bgr(arr)
            self._src_path = path
            self._set_status(f"Загружено: {_api.os.path.basename(path)}. "
                             "Закрасьте объект кистью и нажмите «Удалить объект».")
            self._kick_warmup()
        self._refresh_enabled()
    except Exception as exc:
        _api.msgbox_warning(self, "Ошибка", f"Не удалось открыть изображение:\n{exc}")

def add_paths(self, paths):
    imgs = [p for p in paths if _api.os.path.splitext(p)[1].lower() in
            {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tiff', '.tif',
             '.avif', '.heic', '.heif'}]
    if imgs:
        self._load(imgs[0])

def dragEnterEvent(self, e):
    if e.mimeData().hasUrls(): e.accept()
    else: e.ignore()

def dropEvent(self, e):
    if e.mimeData().hasUrls():
        e.accept()
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls()])

def _choose_out_dir(self):
    start = self._out_dir or (_api.os.path.dirname(self._src_path) if self._src_path else "")
    d = _api.QFileDialog.getExistingDirectory(self, "Папка для сохранения", start)
    if d:
        self._out_dir = d
        self.lbl_outdir.setText(f"Папка: {d}")
        self.lbl_outdir.setToolTip(d)

def _output_path(self, has_alpha=False):
    """Путь сохранения: <имя_исходника>_photo.<ext> в выбранной папке (или
        рядом с исходником). Расширение — БЕЗ ПОТЕРЬ: исходные png/bmp/tiff
        сохраняем как есть, остальное (jpg/webp/avif/heic…) → png, чтобы не было
        повторного сжатия и потери качества. Если удалён фон (есть прозрачность) —
        формат обязан её хранить (png/webp/tiff), иначе принудительно png."""
    if self._src_path:
        base = _api.os.path.splitext(_api.os.path.basename(self._src_path))[0]
        src_ext = _api.os.path.splitext(self._src_path)[1].lower().lstrip('.')
        src_dir = _api.os.path.dirname(self._src_path)
    else:
        base, src_ext, src_dir = "image", "png", _api.os.getcwd()
    if has_alpha:
        ext = src_ext if src_ext in ("png", "webp", "tif", "tiff") else "png"
    else:
        ext = src_ext if src_ext in ("png", "bmp", "tif", "tiff") else "png"
    out_dir = self._out_dir or src_dir or _api.os.getcwd()
    stem = f"{base}_photo"
    path = _api.os.path.join(out_dir, f"{stem}.{ext}")
    if not _api.os.path.exists(path):
        return path
    n = 1
    while True:
        path = _api.os.path.join(out_dir, f"{stem}_{n}.{ext}")
        if not _api.os.path.exists(path):
            return path
        n += 1

def _save(self):
    if not self.canvas.has_image():
        return
    # Вжигаем незакреплённый плавающий объект (фигуру/текст) в картинку, чтобы
    # он попал в сохранённый файл.
    self.canvas.commit_pending()
    # composited_bgra: BGRA, если фон удалён (прозрачность), иначе BGR.
    arr = self.canvas.composited_bgra()
    has_alpha = arr is not None and arr.ndim == 3 and arr.shape[2] == 4
    out = self._output_path(has_alpha)
    try:
        _api.os.makedirs(_api.os.path.dirname(out) or ".", exist_ok=True)
        # Сохраняем фото с вжатыми мазками «Кисти» (и альфой прозрачности, если
        # удалён фон). Красная маска удаления — служебная, в файл не попадает.
        _api.save_bgr(out, arr)                            # png/webp/tiff — без потерь
        self._set_status(_api.status_html('fa5s.check-circle',
                         f"Сохранено: {_api.os.path.basename(out)}", '#a6e3a1'))
        self.lbl_status.setToolTip(out)
        # Всплывающее уведомление об успешном сохранении (по просьбе
        # пользователя) — показываем ТОЛЬКО если файл реально записан.
        if _api.os.path.exists(out):
            self._show_saved_toast(_api.os.path.basename(out))
    except Exception as exc:
        _api.msgbox_warning(self, "Ошибка", f"Не удалось сохранить:\n{exc}")

def _show_saved_toast(self, name: str):
    """Зелёный плавающий баннер «Файл сохранён» по центру сверху вкладки."""
    self._show_toast(f"✅  Файл сохранён: {name}")

def _show_toast(self, text: str, bg: str = "rgba(166,227,161,0.94)"):
    """Плавающий баннер по центру сверху вкладки, автоскрытие через 3 с
        (как в SiQuesterHYX). Создаётся лениво."""
    lbl = getattr(self, "_saved_toast", None)
    if lbl is None:
        lbl = _api.QLabel(self)
        lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        lbl.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._saved_toast = lbl
        self._saved_toast_timer = _api.QTimer(self)
        self._saved_toast_timer.setSingleShot(True)
        self._saved_toast_timer.timeout.connect(lbl.hide)
    lbl.setStyleSheet(
        f"background:{bg};color:#181825;font-size:13px;"
        "font-weight:700;border-radius:8px;padding:8px 24px;")
    lbl.setText(text)
    lbl.adjustSize()
    lbl.move(max(0, (self.width() - lbl.width()) // 2), 12)
    lbl.raise_(); lbl.show()
    self._saved_toast_timer.start(3000)

# ── Прогрев модели ───────────────────────────────────────────────────────
def showEvent(self, ev):
    super(_api.InpaintTab, self).showEvent(ev)
    # Грузим модель в фоне при первом показе вкладки (а не при старте приложения).
    if _api._HAS_INPAINT and not self._warmed:
        self._kick_warmup()
    self._touch()

def hideEvent(self, ev):
    # Уход со вкладки = простой: запускаем отсчёт выгрузки (минута).
    super(_api.InpaintTab, self).hideEvent(ev)
    if _api._HAS_INPAINT and not self._keep_models:
        self._idle_timer.start()

# ── Выгрузка моделей из ОЗУ при простое ──────────────────────────────────
def set_keep_models(self, keep: bool):
    """Настройка «Не выгружать модели из ОЗУ»: True — держать всегда (таймер
        стоп), False — выгружать после минуты простоя."""
    self._keep_models = bool(keep)
    if self._keep_models:
        self._idle_timer.stop()
    elif self.isVisible():
        self._touch()
    else:
        self._idle_timer.start()

def _touch(self):
    """Взаимодействие со вкладкой → сбрасываем отсчёт выгрузки. Модель тут НЕ
        подгружаем: загрузка только при открытии вкладки (showEvent) и при самом
        удалении объекта/фона. Клики/рисование лишь не дают выгрузить загруженную."""
    if not _api._HAS_INPAINT or self._keep_models:
        return
    self._idle_timer.start()

def eventFilter(self, obj, ev):
    if ev.type() in (_api.QEvent.Type.MouseButtonPress, _api.QEvent.Type.MouseMove,
                     _api.QEvent.Type.KeyPress, _api.QEvent.Type.Wheel):
        self._touch()
    return super(_api.InpaintTab, self).eventFilter(obj, ev)

def _models_busy(self) -> bool:
    return ((self._worker is not None and self._worker.isRunning())
            or (self._bg_worker is not None and self._bg_worker.isRunning())
            or self._warmup is not None)

def _maybe_unload_models(self):
    if self._keep_models:
        return
    if self._models_busy():
        self._idle_timer.start()     # занят — отложим проверку
        return
    was_loaded = self._warmed
    for m in (self._inpainter, self._remover):
        if m is not None and hasattr(m, "unload"):
            try: m.unload()
            except Exception: pass
    self._warmed = False
    self._device = "—"
    if was_loaded and hasattr(self, "lbl_device"):
        self.lbl_device.setText("Устройство: модель выгружена из ОЗУ")

def _kick_warmup(self):
    if not _api._HAS_INPAINT or self._warmed or self._warmup is not None:
        return
    if not _api._HAS_ORT:
        self.lbl_device.setText("Устройство: нет onnxruntime")
        return
    self.lbl_device.setText("Устройство: загрузка модели…")
    self._warmup = _api._WarmupWorker(self._inpainter)
    self._warmup.done.connect(self._on_warmed)
    self._warmup.failed.connect(self._on_warm_failed)
    self._warmup.start()
