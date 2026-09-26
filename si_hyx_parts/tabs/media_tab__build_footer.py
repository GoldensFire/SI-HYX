# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MediaTab: _build_footer. Public namespace: tabs."""
import tabs as _api


    # ── Продвинутые настройки кодирования (Тюнинг / Метрика-XPSNR / CQ-level) ─
    # Редко нужны и путают в базовом сценарии — скрыты по умолчанию, включаются
    # ОДНИМ переключателем в Настройках (см. set_advanced_encode_visible).

def _build_footer(self, l, right_container, right_layout, rv_inner, rw, w):
    """Футер (счётчик потоков, кнопки) и финальная сборка правой панели."""
    self._adv_encode_widgets_fv = [self.c_tune, self.ck_metric_xpsnr,
                                    self.s_target_metric, self.lbl_target_metric,
                                    self._badge_metric]
    self._adv_encode_widgets_favi = [self.s_cq, self._lbl_cq]
    self._show_advanced_encode = False
    self.chk_enable_video.toggled.connect(lambda _c: self._apply_advanced_encode_visibility())
    self._apply_advanced_encode_visibility()

    rv_inner.addStretch(); w.setLayout(rv_inner); rw.setWidget(w); right_layout.addWidget(rw)

    # ── Низ правой панели: приоритет процесса + счётчик задействованных потоков ──
    foot = _api.QWidget(); foot_l = _api.QHBoxLayout(foot); foot_l.setContentsMargins(6, 0, 6, 2)
    foot_l.addWidget(_api.QLabel("Приоритет:"))
    self.c_priority = _api.InvertedWheelComboBox()
    self.c_priority.addItems(["Низкий", "Обычный", "Высокий"])
    self.c_priority.setCurrentText("Обычный")
    self.c_priority.setMaximumWidth(150)
    # Приоритет сохраняем СВОИМ изолированным write (read-modify-write только
    # ключа 'priority'), а не только общим _save_settings_now: тот собирает
    # ВЕСЬ словарь настроек и при любой ошибке сборки молча НИЧЕГО не пишет
    # (см. _collect_settings → {}), из-за чего смена приоритета терялась.
    self.c_priority.currentTextChanged.connect(self._persist_priority)
    foot_l.addWidget(self.c_priority)
    foot_l.addWidget(_api.info_badge("Приоритет процессов кодирования (ffmpeg) в системе. Высокий — кодирует быстрее; на Низком ПК отзывчивее."))
    foot_l.addStretch()
    # Всего логических потоков ЦП на этой машине — показываем сразу (0/N),
    # а не 0/0, чтобы было видно потенциал ещё до запуска обработки.
    self._cpu_threads = max(1, _api.cpu_thread_count())
    self.lbl_threads = _api.QLabel(f"Параллельных задач: 0/{self._cpu_threads}")
    self.lbl_threads.setToolTip(
        "Занятые логические потоки ЦП. Видео/аудио кодируются по одному файлу, "
        "но SVT-AV1 нагружает все ядра — поэтому показывается полное число потоков. "
        "Изображения обрабатываются параллельно (по числу ядер).")
    foot_l.addWidget(self.lbl_threads)
    right_layout.addWidget(foot)

    btn_box = _api.QWidget(); btn_layout = _api.QHBoxLayout(btn_box)
    btn_layout.setContentsMargins(0, 6, 0, 6)
    self.b_run = _api._icon_btn("НАЧАТЬ", 'fa5s.play', color='#1e1e2e'); self.b_run.setObjectName("b_run")
    self.b_stop = _api._icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e'); self.b_stop.setObjectName("b_stop"); self.b_stop.setEnabled(False)
    self.b_run.clicked.connect(self.run); self.b_stop.clicked.connect(self.stop)
    btn_layout.addWidget(self.b_run); btn_layout.addWidget(self.b_stop)

    right_layout.addWidget(btn_box); right_container.setLayout(right_layout); l.addWidget(right_container, 0)

    self.shortcut_paste = _api.QShortcut(_api.QKeySequence("Ctrl+V"), self.tree)
    self.shortcut_paste.activated.connect(self.paste_files)
    # Клавиша Delete — удалить выделенные файлы из очереди
    self.shortcut_delete = _api.QShortcut(_api.QKeySequence(_api.Qt.Key.Key_Delete), self.tree)
    self.shortcut_delete.setContext(_api.Qt.ShortcutContext.WidgetWithChildrenShortcut)
    self.shortcut_delete.activated.connect(self.rem)
    self.tree.itemDoubleClicked.connect(self.on_double_click)

def _persist_priority(self, text):
    """Изолированно пишет ТОЛЬКО ключ 'priority' (read-modify-write), не трогая
        остальные настройки. Нужен потому, что общий _save_settings_now собирает
        весь словарь разом и при любой ошибке сборки молча не сохраняет ничего —
        тогда смена приоритета не доживала до следующего запуска."""
    try:
        s = _api.load_settings()
        if isinstance(s, dict) and s:
            # Загрузили существующий словарь — дописываем только приоритет.
            s['priority'] = text
            _api.save_settings(s)
        else:
            # Файл пуст/нечитаем: НЕ пишем одинокий ключ (затёр бы остальное),
            # а просим общий сборщик собрать полный словарь.
            self.main._save_settings_now()
    except Exception:
        pass

def _size_profile_toggle_buttons(self):
    """Резервирует под кнопки «Стандарт»/«Тёмные сцены» ширину, достаточную
        для их ЖИРНОГО (:checked, см. глобальный QSS) начертания — см. пояснение
        в __init__. Меряет реальный полированный шрифт виджета, а не константу."""
    for _b in (self.btn_mode_std, self.btn_mode_dark):
        _b.ensurePolished()
        _orig_font = _b.font()
        _bold_font = _api.QFont(_orig_font); _bold_font.setBold(True)
        _b.setFont(_bold_font)
        _bold_w = _b.sizeHint().width()
        _b.setFont(_orig_font)
        if _b.minimumWidth() < _bold_w:
            _b.setMinimumWidth(_bold_w)

def _set_preset_mode(self, mode):
    """Переключает профиль кодирования без изменения preset и битрейта аудио."""
    is_dark = (mode == "dark")
    self.btn_mode_std.blockSignals(True);  self.btn_mode_dark.blockSignals(True)
    self.btn_mode_std.setChecked(not is_dark); self.btn_mode_dark.setChecked(is_dark)
    self.btn_mode_std.blockSignals(False); self.btn_mode_dark.blockSignals(False)
    try: self.main._save_settings_now()
    except Exception: pass

def _video_metric_value(self):
    """'none' | 'xpsnr' — цель авто-подбора CRF (_metric_crf_search
        в workers.py). 'none' — ручной CRF без подбора."""
    return 'xpsnr' if self.ck_metric_xpsnr.isChecked() else 'none'

@staticmethod
def _set_form_row_visible(form, widgets, visible):
    """Показывает/скрывает виджеты формы И их лейбл (QFormLayout не двигает
        лейбл сам по себе — ищем строку, где поле — один из widgets или их
        layout-обёртка, см. _update_video_enc)."""
    for w in widgets:
        w.setVisible(visible)
    for row_idx in range(form.rowCount()):
        lbl = form.itemAt(row_idx, _api.QFormLayout.ItemRole.LabelRole)
        fld = form.itemAt(row_idx, _api.QFormLayout.ItemRole.FieldRole)
        if not fld:
            continue
        wgt = fld.widget()
        if wgt is None and fld.layout():
            wgt = fld.layout().itemAt(0).widget() if fld.layout().count() else None
        matches = wgt in widgets or (
            fld.layout() and any(
                fld.layout().itemAt(i).widget() in widgets
                for i in range(fld.layout().count())
                if fld.layout().itemAt(i).widget()
            )
        )
        if matches and lbl and lbl.widget():
            lbl.widget().setVisible(visible)

def set_advanced_encode_visible(self, on: bool):
    """Настройки → единый переключатель «Тюнинг / Метрика (XPSNR) / CQ-level».
        Втроём скрыты по умолчанию (редко нужны, путают в базовом сценарии) —
        включаются/выключаются ОДНИМ чекбоксом в Настройках."""
    self._show_advanced_encode = bool(on)
    self._apply_advanced_encode_visibility()

def _apply_advanced_encode_visibility(self):
    show = bool(getattr(self, '_show_advanced_encode', False))
    # Тюнинг/Метрика имеют смысл только пока включено само перекодирование видео.
    self._set_form_row_visible(self._fv_form, self._adv_encode_widgets_fv,
                                show and self.chk_enable_video.isChecked())
    self._set_form_row_visible(self._favi_form, self._adv_encode_widgets_favi, show)
    # Колонка "Оценка XPSNR" в таблице файлов имеет смысл только вместе с
    # продвинутыми настройками — прячем её тем же переключателем. Пока она
    # скрыта, оценка и не считается (см. show_metric_col выше): её замер —
    # это отдельное пробное кодирование.
    self.tree.setColumnHidden(8, not show)

def _video_tune_value(self):
    """Числовое значение SVT-AV1 --tune (0/1/2/4/5, см. c_tune в __init__)
        для финального кодирования (_av1_encoder_args в workers.py)."""
    data = self.c_tune.currentData()
    return int(data) if data is not None else 0

def _set_tune_value(self, value):
    """Выставляет c_tune по числовому значению tune (обратная операция
        к _video_tune_value) — используется при загрузке сохранённых настроек."""
    idx = self.c_tune.findData(int(value))
    self.c_tune.setCurrentIndex(idx if idx >= 0 else 0)

def on_url_ctx(self, pos):
    m = _api.QMenu()
    try: cb = _api.QApplication.clipboard().text().strip()
    except Exception: cb = ""
    if cb and cb.startswith("http"):
        a = _api.QAction("Скачать из буфера", self)
        a.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.download_url(False)))
        a2 = _api.QAction("Скачать аудио из буфера", self)
        a2.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.download_url(True)))
        m.addAction(a); m.addAction(a2); m.addSeparator()
    m.addAction(_api.QAction("Вставить", self, triggered=self.url_edit.paste))
    m.exec(self.url_edit.mapToGlobal(pos))

def on_double_click(self, item, column):
    """Двойной клик: по готовому файлу — открыть результат в плеере;
        по ещё не обработанному (только добавленному) — запустить
        перекодирование ТОЛЬКО этого файла."""
    try:
        iid = item.data(0, _api.Qt.ItemDataRole.UserRole)
        entry = self._item_data_map.get(iid)
        if not entry:
            return
        if entry.get('is_done'):
            out_path = entry.get('out_path')
            if out_path and _api.os.path.exists(out_path):
                self.open_output_file(out_path)
            else:
                self.open_file_location(item)
        else:
            # Файл ещё в очереди — перекодируем только его
            self._run_items([entry])
    except Exception: pass

def open_output_file(self, path):
    """Открывает файл в ассоциированном приложении (плеер, просмотрщик)."""
    try:
        if _api.IS_WIN:
            _api.os.startfile(path)
        elif _api.sys.platform == 'darwin':
            _api.subprocess.Popen(['open', path])
        else:
            _api.subprocess.Popen(['xdg-open', path])
    except Exception as e:
        self.main.log(f"Не удалось открыть файл: {e}")

def _choose_export_dir(self):
    d = _api.QFileDialog.getExistingDirectory(self, "Папка экспорта", self.export_dir or _api.default_download_dir())
    if d:
        self.export_dir = d
        self._update_export_label()
        try: self.main._save_settings_now()
        except Exception: pass

def _reset_export_dir(self):
    self.export_dir = ""
    self._update_export_label()
    try: self.main._save_settings_now()
    except Exception: pass

def _update_export_label(self):
    """Обновляет подпись пути экспорта и видимость кнопки сброса."""
    try:
        if self.export_dir and _api.os.path.isdir(self.export_dir):
            self.lbl_export_dir.setText(self.export_dir)
            self.lbl_export_dir.setToolTip(self.export_dir)
            self.btn_export_reset.setEnabled(True)
        else:
            self.lbl_export_dir.setText("По умолчанию экспорт в папку исходника")
            self.lbl_export_dir.setToolTip("")
            self.btn_export_reset.setEnabled(False)
    except Exception: pass

def download_url(self, audio_only=False):
    url = self.url_edit.text().strip()
    if not url: return
    self.url_edit.clear()

    try:
        dl_path = self.main.tab_ytdlp.out.text()
        if not dl_path or not _api.os.path.exists(dl_path): dl_path = _api.default_download_dir()
    except Exception: dl_path = _api.default_download_dir()

    self.main.tab_ytdlp.add_dl_direct(url, audio_only=audio_only, outdir=dl_path)

def _quick_dl_stop(self):
    """СТОП в строке «Быстрая загрузка» — останавливает активные загрузки.
        Быстрые загрузки выполняются воркер-пулом вкладки «Скачать» (YtdlpTab),
        поэтому останавливаем их там же — как кнопкой СТОП на той вкладке."""
    try:
        self.main.tab_ytdlp.stop_all_dl()
    except Exception as e:
        self.main.log(f"quick stop error: {e}")

def reset_status(self):
    for i in self.tree.selectedItems():
        iid = i.data(0, _api.Qt.ItemDataRole.UserRole)
        entry = self._item_data_map.get(iid)
        if entry:
            entry['is_done'] = False
        i.setText(6, "Ожидание")
        i.setText(7, "—")                  # Время перекодирования
        self._proc_started.pop(iid, None)
        self._proc_running.discard(iid)
        # Сброс «новых» данных — оставляем только исходные (верхняя строка «было»)
        self._set_pair(i, 2, bottom="—")   # Размер: стало
        self._set_pair(i, 3, bottom="—")   # Битрейт: итог
        self._set_pair(i, 4, bottom="—")   # LUFS: после
        i.setData(0, _api.ITEM_STATUS_ROLE, None)
        i.setData(0, _api.ITEM_COMPARE_ROLE, None)   # снять значок «сравнить»
    self.tree.viewport().update()

def dragEnterEvent(self, event):
    try:
        mime = event.mimeData()
        if mime and mime.hasUrls(): event.acceptProposedAction()
        else: event.ignore()
    except Exception: event.ignore()

def dropEvent(self, event):
    try:
        self.window().raise_(); self.window().activateWindow()
        mime = event.mimeData()
        if not mime: return
        if mime.hasUrls():
            paths = [u.toLocalFile() for u in mime.urls() if u.toLocalFile()]
            if paths: self.add_paths(paths)
            event.acceptProposedAction()
        else: event.ignore()
    except Exception as e:
        self.main.log(f"dropEvent error: {e}")
        event.ignore()
