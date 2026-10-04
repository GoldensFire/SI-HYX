# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpTab: _on_url_edited. Public namespace: tabs."""
import tabs as _api


def _on_url_edited(self):
    self.fetch_timer.start()
    # Ссылка вида youtu.be/xxx?t=9182 — сразу выставляем «С:» на этот тайминг
    # (не дожидаясь ответа InfoWorker с длительностью).
    url = self.url_edit.text().strip()
    if url != self._timing_url:
        if self.info_worker:
            self.info_worker.cancel()
        self._timing_url = url
        self._source_duration = None
        self._source_url = ""
        self._clear_timings()
    ts = _api.parse_youtube_start_seconds(url) if url else None
    self._url_start_s = ts
    if ts is not None:
        if ts > self.slider_start.maximum():
            self.slider_start.setRange(0, ts)
            if self.slider_end.maximum() < ts:
                self.slider_end.setRange(0, ts)
        self.slider_start.setValue(ts)
        if self.slider_end.value() < ts:
            self.slider_end.setValue(self.slider_end.maximum())
        self.main.log(f"Ссылка содержит тайминг: качаю с {ts} сек.")

def _start_fetch(self):
    url = self.url_edit.text().strip()
    if not url: return
    self.main.log(f"Запрос метаданных для: {url[:30]}...")

    # Для Kodik-сайтов (animego и т.п.) — подгружаем списки озвучек и серий
    # в выпадашки (один раз на ссылку).
    if _api.is_embed_candidate(url) and url != self._kodik_last_url:
        self._kodik_last_url = url
        def _kinfo(u=url, px=self.proxy_edit.text().strip()):
            try:
                info = _api.kodik_get_info(u, proxy=px)
                tr = info.get("translations") or []
                if tr:
                    self.kodik_info_sig.emit(
                        tr, int(info.get("episodes", 0)),
                        info.get("cur_translation", "") or "",
                        int(info.get("cur_episode", 0) or 0))
            except Exception:
                pass
        _api.threading.Thread(target=_kinfo, daemon=True).start()
    # Stop the subprocess, retaining the QThread until its finished signal.
    if self.info_worker and self.info_worker.isRunning():
        self.info_worker.cancel()
        # Отключаем сигналы старого воркера чтобы не получить stale callback
        try: self.info_worker.success.disconnect()
        except Exception: pass
        try: self.info_worker.error.disconnect()
        except Exception: pass
    self.info_worker = _api.InfoWorker(url, proxy=self.proxy_edit.text().strip())
    worker = self.info_worker
    self._info_workers.add(worker)
    worker.finished.connect(lambda w=worker: self._info_workers.discard(w))
    worker.success.connect(lambda *args, w=worker: self._on_info_success(*args)
                           if w is self.info_worker and not w.cancelled else None)
    worker.error.connect(lambda message, w=worker: self._on_info_error(message)
                         if w is self.info_worker and not w.cancelled else None)
    worker.start()

def _kodik_episode_value(self):
    """Номер выбранной серии (int) или None, если список ещё не заполнен."""
    txt = self.kodik_ep.currentText().strip()
    return int(txt) if txt.isdigit() else None

def _populate_kodik(self, translations, episodes, cur_translation, cur_episode):
    """Заполняет выпадашки серий и озвучек (только выбор, не ввод).
        По умолчанию выбирает то, что отмечено в плеере; иначе — первый пункт."""
    try:
        self.kodik_trans.blockSignals(True)
        self.kodik_trans.clear()
        for t in translations:
            self.kodik_trans.addItem(t)
        idx = self.kodik_trans.findText(cur_translation) if cur_translation else -1
        self.kodik_trans.setCurrentIndex(idx if idx >= 0 else 0)
        self.kodik_trans.blockSignals(False)

        self.kodik_ep.blockSignals(True)
        self.kodik_ep.clear()
        for i in range(1, int(episodes) + 1):
            self.kodik_ep.addItem(str(i))
        if episodes <= 0:
            self.kodik_ep.addItem("—")
        ep_idx = self.kodik_ep.findText(str(cur_episode)) if cur_episode else -1
        self.kodik_ep.setCurrentIndex(ep_idx if ep_idx >= 0 else 0)
        self.kodik_ep.blockSignals(False)

        self.main.log(f"Kodik: озвучек {len(translations)}, серий {episodes}. "
                      f"Выбрано: серия {self.kodik_ep.currentText()}, "
                      f"озвучка «{self.kodik_trans.currentText()}».")
    except Exception as e:
        self.main.log(f"_populate_kodik error: {e}")

def _on_info_success(self, duration, thumb_url, sub_langs=None, audio_langs=None):
    self.main.log(f"Длительность получена: {duration} сек.")
    self._source_duration = duration if duration > 0 else None
    self._source_url = self.info_worker.url if self.info_worker else self.url_edit.text().strip()
    try:
        if duration > 0:
            self.slider_start.setRange(0, duration); self.slider_end.setRange(0, duration)
            start_val = min(self._url_start_s, duration) if self._url_start_s else 0
            self.slider_start.setValue(start_val); self.slider_end.setValue(duration)
            self._slider_to_spins()
    except Exception: pass
    try:
        self._populate_lang_combos(sub_langs or [], audio_langs or [])
    except Exception: pass

def _populate_lang_combos(self, sub_langs, audio_langs):
    """Заполняет «Суб.» и «Язык» реально доступными дорожками видео.
        Субтитры показываем, только если они есть; «Язык» — только если у видео
        больше одной аудиодорожки (иначе выбирать нечего → список пуст)."""
    # Субтитры
    cur_s = self.c_s.currentText()
    self.c_s.blockSignals(True); self.c_s.clear()
    if sub_langs:
        items = ["Выкл", "all"] + list(sub_langs)
        self.c_s.addItems(items)
        if cur_s in items:
            self.c_s.setCurrentText(cur_s)
    self.c_s.blockSignals(False)
    # Язык (аудиодорожка)
    cur_a = self.c_a.currentText()
    self.c_a.blockSignals(True); self.c_a.clear()
    if len(audio_langs) > 1:
        items = ["Original"] + list(audio_langs)
        self.c_a.addItems(items)
        if cur_a in items:
            self.c_a.setCurrentText(cur_a)
    self.c_a.blockSignals(False)

def _on_info_error(self, err_msg):
    self.main.log(f"[Ошибка метаданных] {err_msg}")

def _clear_timings(self):
    self._url_start_s = None
    for box in self.ts + self.te:
        box.blockSignals(True); box.setValue(0); box.blockSignals(False)
    self.slider_start.blockSignals(True); self.slider_start.setValue(0); self.slider_start.blockSignals(False)
    self.slider_end.blockSignals(True);   self.slider_end.setValue(self.slider_end.maximum()); self.slider_end.blockSignals(False)

def on_url_ctx(self, pos):
    m = _api.QMenu()
    try: cb = _api.QApplication.clipboard().text().strip()
    except Exception: cb = ""
    if cb and cb.startswith("http"):
        a = _api.QAction("Скачать из буфера", self)
        a.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(False)))
        a2 = _api.QAction("Скачать аудио из буфера", self)
        a2.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(True)))
        m.addAction(a); m.addAction(a2); m.addSeparator()
    m.addAction(_api.QAction("Вставить", self, triggered=self.url_edit.paste))
    m.exec(self.url_edit.mapToGlobal(pos))

def stop_all_dl(self):
    for entry in self.items.values():
        entry.pop('restart_config', None)
    for w in list(self.active_workers.values()):
        try: w.stop()
        except Exception: pass

def stop_sel_dl(self):
    for it in self.tree.selectedItems():
        iid = it.data(0, _api.Qt.ItemDataRole.UserRole)
        self.items.get(iid, {}).pop('restart_config', None)
        w = self.active_workers.get(iid)
        if w:
            try: w.stop()
            except Exception: pass

def ctx(self, pos):
    m = _api.QMenu()
    sel = self.tree.itemAt(pos)
    if sel:
        m.addAction(_api.QAction("Перейти к URL (копировать в буфер)", self, triggered=lambda checked=False, it=sel: _api.QApplication.clipboard().setText(it.text(0))))
        m.addAction(_api.QAction(_api.get_icon('fa5s.redo'), "Скачать заново", self, triggered=self.redownload_sel))
        m.addAction(_api.QAction("Остановить загрузку", self, triggered=self.stop_sel_dl))
        m.addSeparator()
    try: cb = _api.QApplication.clipboard().text().strip()
    except Exception: cb = ""
    if cb and cb.startswith('http'):
        a_cb = _api.QAction('Скачать из буфера', self); 
        a_cb.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(False)))
        a_cba = _api.QAction('Скачать аудио из буфера', self); 
        a_cba.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(True)))
        m.addAction(a_cb); m.addAction(a_cba); m.addSeparator()
    m.addAction(_api.QAction('Удалить', self, triggered=self.delete_sel))
    m.addAction(_api.QAction('Очистить', self, triggered=self.tree.clear))
    m.exec(self.tree.mapToGlobal(pos))

def _choose_cookie(self):
    path, _ = _api.QFileDialog.getOpenFileName(self, "Выбрать файл cookies", "", "Text files (*.txt);;All files (*)")
    if path:
        self.cookie_edit.setText(path)

def ch_dir(self):
    d = _api.QFileDialog.getExistingDirectory(self, "Папка", self.out.text())
    if d:
        self.out.setText(d)
        try: self.main.recent_strip.refresh(d)
        except Exception: pass

def get_sec(self, arr):
    return arr[0].value()*3600 + arr[1].value()*60 + arr[2].value()

def _connect_worker_signals(self, w: '_api.YtdlpWorker', iid: str):
    """Подключает стандартные сигналы воркера к обработчикам дерева."""
    def on_prog(iid_, p, t):
        # Опоздавший тик уже завершённого воркера (его watchdog мог эмитнуть
        # «Скачивание…» в момент гибели процесса) не должен воскрешать строку
        # и индикатор в панели задач после ошибки/остановки.
        if self.active_workers.get(iid_) is not w:
            return
        item = self.items.get(iid_, {}).get('item')
        if item:
            # p <= 0 — индикатор активности без реального % (подготовка/повторы
            # извлечения/тихий ffmpeg); реальный процент показываем от >0.
            item.setText(1, "…" if p <= 0 else f"{p:.1f}%"); item.setText(3, t)
        self._dl_pct[iid_] = p
        self._update_dl_taskbar()

    def on_done(iid_, status, clean_info, file_path):
        if self.active_workers.get(iid_) is not w:
            return
        self._dl_pct.pop(iid_, None); self._update_dl_taskbar()
        item = self.items.get(iid_, {}).get('item')
        if item:
            item.setText(3, status)
            # Зелёная подсветка строки — как на странице обработки (делегат
            # StatusColorDelegate рисует фон по статусу из 0-й колонки).
            item.setData(0, _api.ITEM_STATUS_ROLE, 'done')
            self.tree.viewport().update()
            if file_path and _api.os.path.exists(file_path):
                try:
                    dur, br_str, size, a_br, _a_codec = _api.get_media_info(file_path)
                    item.setText(1, _api.human_size(size))
                    item.setText(2, clean_info if clean_info and clean_info != "Unknown" else br_str)
                    self.main.log(f"Загружено: {file_path} ({_api.human_size(size)}, {a_br})")
                except Exception: pass

    def on_err(iid_, msg):
        if self.active_workers.get(iid_) is not w:
            return
        self._dl_pct.pop(iid_, None); self._update_dl_taskbar()
        try:
            item = self.items.get(iid_, {}).get('item')
            if not item: return
            item.setText(3, "Ошибка"); item.setToolTip(3, msg)
            # Красная подсветка строки — как на странице обработки.
            item.setData(0, _api.ITEM_STATUS_ROLE, 'err')
            self.tree.viewport().update()
        except RuntimeError:
            pass  # QTreeWidgetItem уже удалён пользователем

    def on_thumb(iid_, thumb_url):
        if thumb_url:
            self.pool.start(_api.RemoteThumbnailRunnable(thumb_url, iid_, self.thumb_sig))

    w.progress_sig.connect(on_prog); w.finished_sig.connect(on_done)
    w.error_sig.connect(on_err); w.thumb_sig.connect(on_thumb)
    w.log_sig.connect(lambda m: self.main.log(str(m)))

def add_dl_direct(self, url: str, audio_only: bool = False, outdir: str = ""):
    """Запускает загрузку с готовым URL — не читает поля UI.
        Используется при скачивании с вкладки MediaTab, чтобы элемент
        с прогрессом и миниатюрой появлялся именно здесь.
        """
    try:
        if not url: return
        if not outdir:
            outdir = self.out.text()
        if not outdir or not _api.os.path.exists(outdir):
            outdir = _api.default_download_dir()

        iid = _api.uuid.uuid4().hex
        it = _api.QTreeWidgetItem(self.tree)
        it.setText(0, url); it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
        it.setData(0, _api.Qt.ItemDataRole.UserRole, iid)
        it.setData(0, _api.ITEM_STATUS_ROLE, 'proc')  # синяя подсветка «в работе»
        self.items[iid] = {'item': it, 'url': url, 'audio_only': bool(audio_only)}

        config = {
            'iid': iid, 'url': url,
            'fmt': _api.FORMAT_OPTIONS.get("1080p", 'bestvideo[height<=1080]+bestaudio/best'),
            'outdir': outdir, 'merge': 'mp4', 'sub_lang': 'Выкл',
            'audio': 'Original', 'force_kf': True,
            'audio_only': bool(audio_only),
            'cookie_path': self.cookie_edit.text().strip() if hasattr(self, 'cookie_edit') else '',
            'proxy': self.proxy_edit.text().strip() if hasattr(self, 'proxy_edit') else '',
        }
        self._start_download(config)
        self.main.log(f"Загрузка добавлена: {url}")
    except Exception as e:
        self.main.log(f"add_dl_direct error: {e}")
