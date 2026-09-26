# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintTab: _on_warmed. Public namespace: photo_tab."""
import photo_tab as _api


def _on_warmed(self, device):
    self._warmed = True
    self._device = device
    self.lbl_device.setText(f"Устройство: {device}")
    self._warmup = None

def _on_warm_failed(self, err):
    self.lbl_device.setText("Устройство: ошибка загрузки модели")
    self._set_status(_api.status_html('fa5s.exclamation-triangle',
                     f"Модель не загрузилась: {err}", '#f9e2af'))
    self._warmup = None

# ── Запуск инференса ─────────────────────────────────────────────────────
def _run_inpaint(self):
    self._touch()
    if not self.canvas.has_image():
        return
    # Закрепляем плавающий объект, чтобы нейросеть видела финальную картинку.
    self.canvas.commit_pending()
    # Незавершённое кадрирование применяем (иначе нарисованная рамка пропадала,
    # а нейросеть работала по полному изображению — «убирала кадрирование»).
    if self.canvas.has_crop():
        self.canvas.apply_crop()
    if not _api._HAS_ORT:
        _api.msgbox_warning(self, "Нет onnxruntime",
                            "Для удаления объектов установите onnxruntime:\n\n"
                            "pip install onnxruntime")
        return
    if not self.canvas.has_mask():
        # Сюда попадаем только при пустом выделении (кисть удаления не оставила
        # мазка) — тихо выходим: сама кнопка «Удалить объект» уже включает кисть.
        self._set_status("Закрасьте кистью удаления то, что нужно стереть.")
        return
    if self._worker is not None and self._worker.isRunning():
        return
    self._cancelling = False        # новый запуск — снимаем возможный флаг отмены
    # Снимок «до» (с отдельным слоем краски и маской) — для Ctrl+Z, затем
    # вживляем мазки кисти, чтобы нейросеть видела финальную картинку.
    self.canvas._push_history()
    self.canvas.bake_paint()
    mask = self.canvas.get_mask()
    img = self.canvas.img_bgr
    self._set_status(_api.status_html('fa5s.spinner',
                     "Обработка нейросетью… (первый запуск дольше — грузится модель)",
                     '#89b4fa'))
    self.setCursor(_api.Qt.CursorShape.WaitCursor)
    self._show_proc_chip(mask)          # мини-прогресс возле выделения/курсора
    self._worker = _api.InpaintWorker(self._inpainter, img, mask)
    self._worker.done.connect(self._on_done)
    self._worker.failed.connect(self._on_failed)
    self._worker.progress.connect(self._on_progress)
    self._worker.start()
    self._refresh_enabled()

# ── Мини-прогресс «удаляю…» возле курсора/выделения ──────────────────────
def _show_proc_chip(self, mask=None, label="Удаляю…", icon='fa5s.magic'):
    chip = getattr(self, "_proc_chip", None)
    if chip is None:
        chip = _api.QFrame(self)
        chip.setObjectName("procChip")
        chip.setStyleSheet(
            "QFrame#procChip{background:rgba(30,30,46,235);"
            "border:1px solid #89b4fa;border-radius:9px;}"
            "QLabel{color:#cdd6f4;font-size:12px;font-weight:600;background:transparent;}"
            "QProgressBar{background:#11111b;border:1px solid #45475a;"
            "border-radius:5px;max-height:8px;min-height:8px;}"
            "QProgressBar::chunk{background:#89b4fa;border-radius:5px;}")
        lay = _api.QHBoxLayout(chip)
        lay.setContentsMargins(10, 7, 8, 7); lay.setSpacing(8)
        self._proc_ic = _api.QLabel()
        self._proc_ic.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._proc_ic)
        self._proc_lbl = _api.QLabel(label)
        self._proc_lbl.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._proc_lbl)
        self._proc_bar = _api.QProgressBar()
        self._proc_bar.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._proc_bar.setTextVisible(False)
        self._proc_bar.setFixedWidth(80)
        lay.addWidget(self._proc_bar)
        self._proc_cancel_btn = _api.QPushButton("Отменить")
        self._proc_cancel_btn.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self._proc_cancel_btn.setToolTip("Отменить обработку")
        self._proc_cancel_btn.setStyleSheet(
            "QPushButton{background:#313244;border:1px solid #45475a;"
            "border-radius:5px;color:#f38ba8;font-size:11px;font-weight:600;"
            "padding:3px 8px;}"
            "QPushButton:hover{background:#45475a;border-color:#f38ba8;}")
        self._proc_cancel_btn.clicked.connect(self._cancel_proc)
        lay.addWidget(self._proc_cancel_btn)
        self._proc_chip = chip
    # Честный индикатор: бесконечный «бегунок» занятости. Длительность одного
    # прохода нейросети заранее неизвестна, поэтому НЕ выдумываем проценты и
    # «осталось N секунд» — подпись показывает реально ПРОШЕДШЕЕ время (счётчик
    # вверх). У LaMa с несколькими областями прогресс настоящий (готово/всего) —
    # там бар становится детерминированным (см. _on_progress).
    self._proc_base_label = label
    self._proc_status_text = label
    self._proc_mask = mask
    self._proc_region_mode = False
    self._proc_start = _api.time.monotonic()
    self._proc_ic.setPixmap(_api.get_icon(icon, color='#89b4fa').pixmap(14, 14))
    self._proc_lbl.setText(label)
    self._proc_bar.setRange(0, 0)        # 0,0 -> бесконечный индикатор занятости
    if self._proc_timer is None:
        self._proc_timer = _api.QTimer(self)
        self._proc_timer.setInterval(500)
        self._proc_timer.timeout.connect(self._proc_tick)
    self._proc_timer.start()
    self._proc_anchor = None        # пересчитать якорь под новое выделение/курсор
    self._proc_chip.adjustSize()
    self._position_proc_chip(mask)
    self._proc_chip.show(); self._proc_chip.raise_()

def _proc_tick(self):
    """Тик: подпись = реально ПРОШЕДШЕЕ время (честный счётчик вверх). Бар —
        бесконечный индикатор занятости, кроме режима реальных областей LaMa."""
    chip = getattr(self, "_proc_chip", None)
    if chip is None or not chip.isVisible():
        return
    elapsed = int(max(0.0, _api.time.monotonic() - self._proc_start))
    if self._proc_region_mode:
        self._proc_lbl.setText(f"{self._proc_status_text} · {elapsed} с")
    else:
        self._proc_lbl.setText(f"{self._proc_base_label} {elapsed} с")
    # Чип подгоняем под подпись и пере-центрируем (якорь стабилен), чтобы текст
    # не обрезался по мере роста счётчика.
    self._proc_chip.adjustSize()
    self._position_proc_chip(self._proc_mask)

def _finish_proc(self):
    """Завершение: останавливаем счётчик времени (чип прячется следом)."""
    if self._proc_timer is not None:
        self._proc_timer.stop()

def _position_proc_chip(self, mask=None):
    # Якорь (центр привязки) вычисляем ОДИН раз при показе чипа и кэшируем —
    # иначе при обновлении подписи (счётчик времени растит ширину) чип бы прыгал
    # за курсором (для фона mask=None фолбэк брал бы текущую позицию мыши).
    gp = getattr(self, "_proc_anchor", None)
    if gp is None:
        canvas = self.canvas
        pt = None
        try:
            if mask is not None:
                ys, xs = _api._np.where(mask > 0)
                if len(xs):
                    pt = canvas._i2w(_api.QPointF(float(xs.mean()), float(ys.mean())))
        except Exception:
            pt = None
        if pt is None:
            pt = canvas._mouse_w
        if pt is None:
            pt = _api.QPointF(canvas.width() / 2.0, canvas.height() / 2.0)
        gp = canvas.mapTo(self, _api.QPoint(int(pt.x()), int(pt.y())))
        self._proc_anchor = gp
    w, h = self._proc_chip.width(), self._proc_chip.height()
    x = max(4, min(gp.x() - w // 2, self.width() - w - 4))
    y = max(4, min(gp.y() - h - 14, self.height() - h - 4))
    self._proc_chip.move(x, y)

def _hide_proc_chip(self):
    if self._proc_timer is not None:
        self._proc_timer.stop()
    chip = getattr(self, "_proc_chip", None)
    if chip is not None:
        chip.hide()

def _cancel_proc(self):
    """Отмена текущей обработки (LaMa/RMBG). В процессном режиме kill дочернего
        процесса прерывает инференс за миллисекунды (воркер ловит обрыв пайпа и
        завершается сам). НО интерфейс приводим в «Отменено» СРАЗУ, не дожидаясь
        сигнала воркера: в редком in-process фолбэке одиночный sess.run() прервать
        нельзя, и иначе чип «Удаляю…» и курсор-«ожидание» висели бы до конца прохода
        («не останавливает / с задержкой»). Поздний результат осиротевшего воркера
        отбрасывается по флагу _cancelling (см. _on_done/_on_bg_done)."""
    running = ((self._worker is not None and self._worker.isRunning())
               or (self._bg_worker is not None and self._bg_worker.isRunning()))
    if not running:
        return
    self._cancelling = True
    if self._worker is not None and self._worker.isRunning() and self._inpainter is not None:
        try: self._inpainter.cancel()
        except Exception: pass
    if self._bg_worker is not None and self._bg_worker.isRunning() and self._remover is not None:
        try: self._remover.cancel()
        except Exception: pass
    # Мгновенная реакция UI — не ждём, пока воркер domотает/разблокируется.
    self._finish_proc()
    self._hide_proc_chip()
    self.unsetCursor()
    self._set_status(_api.status_html('fa5s.ban', "Отменено пользователем.", '#f9e2af'))
    self._refresh_enabled()

def _on_progress(self, done, total):
    # Отменено — чип уже скрыт в _cancel_proc, поздний прогресс игнорируем.
    if getattr(self, "_cancelling", False):
        return
    # LaMa с НЕСКОЛЬКИМИ областями: показываем РЕАЛЬНЫЙ прогресс по областям —
    # переключаем чип в детерминированный «режим областей».
    chip = getattr(self, "_proc_chip", None)
    if total > 1:
        self._proc_region_mode = True
        if chip is not None and chip.isVisible():
            self._proc_bar.setRange(0, 1000)
            self._proc_bar.setValue(int(min(done + 1, total) / total * 1000))
            self._proc_status_text = f"Удаляю {min(done + 1, total)}/{total}"
            elapsed = int(max(0.0, _api.time.monotonic() - self._proc_start))
            self._proc_lbl.setText(f"{self._proc_status_text} · {elapsed} с")
        self._set_status(_api.status_html('fa5s.spinner',
                         f"Обработка области {min(done + 1, total)} из {total}…",
                         '#89b4fa'))

def _on_done(self, result):
    # Пользователь отменил, пока шёл инференс, — результат уже не нужен (UI
    # приведён в «Отменено» в _cancel_proc). Прибираемся и выходим, НЕ применяя
    # результат (иначе объект «удалялся» вопреки отмене — «не останавливает»).
    if getattr(self, "_cancelling", False):
        self._cancelling = False
        self._worker = None
        self._hide_proc_chip()
        self.unsetCursor()
        self._refresh_enabled()
        return
    # Состояние сохранено в истории ещё до запуска, поэтому результат
    # применяем без повторного пуша.
    self.canvas.img_bgr = _api._np.ascontiguousarray(result)
    self.canvas._overlay.fill(0)
    self.canvas._has_strokes = False
    self.canvas._rebuild_base()
    self.canvas.update()
    self._finish_proc()
    self._hide_proc_chip()
    self.unsetCursor()
    self._device = self._inpainter.device_label
    self.lbl_device.setText(f"Устройство: {self._device}")
    self._set_status(_api.status_html('fa5s.check-circle',
                     "Готово! Объект удалён.", '#a6e3a1'))
    self._worker = None
    self._refresh_enabled()
    try: _api.play_done_sound()
    except Exception: pass

def _on_failed(self, err):
    self._hide_proc_chip()
    self.unsetCursor()
    self._worker = None
    self._refresh_enabled()
    if getattr(self, "_cancelling", False):
        self._cancelling = False
        self._set_status(_api.status_html('fa5s.ban', "Отменено пользователем.", '#f9e2af'))
        return
    self._set_status(_api.status_html('fa5s.times-circle', f"Ошибка: {err}", '#f38ba8'))
    _api.msgbox_warning(self, "Ошибка обработки", str(err))

# ── Удаление фона (RMBG-2.0) ─────────────────────────────────────────────
def _remove_black_bars(self):
    """«Удалить чёрные полосы»: тот же детект, что во вкладке «Обработка»
        (ProcessWorker._crop_from_counts), только по одной картинке. Работает
        мгновенно и локально — нейросети и фоновые потоки не нужны."""
    self._touch()
    if not self.canvas.has_image():
        return
    if (self._worker is not None and self._worker.isRunning()) or \
       (self._bg_worker is not None and self._bg_worker.isRunning()):
        return
    # Плавающий слой (наложенная картинка/фигура/текст) вжимаем — иначе он
    # остался бы висеть поверх уже обрезанного кадра со старыми координатами.
    self.canvas.commit_pending()
    size = self.canvas.crop_black_bars()
    if size is None:
        self._set_status(_api.status_html('fa5s.info-circle',
                         "Чёрные полосы не обнаружены.", '#89b4fa'))
        self._show_toast("Чёрные полосы не обнаружены",
                         bg="rgba(249,226,175,0.94)")
    else:
        self._set_status(_api.status_html('fa5s.check-circle',
                         f"Чёрные полосы обрезаны → {size[0]}×{size[1]}.", '#a6e3a1'))
        self._show_toast(f"✂  Чёрные полосы обрезаны → {size[0]}×{size[1]}")
    self._refresh_enabled()
