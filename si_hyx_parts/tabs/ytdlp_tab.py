# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpTab. Public namespace: tabs."""
import tabs as _api


class YtdlpTab(_api.QWidget):
    thumb_sig = _api.pyqtSignal(str, _api.QIcon)
    kodik_info_sig = _api.pyqtSignal(object, int, str, int)  # (озвучки, число серий, тек.озвучка, тек.серия)

    def __init__(self, main_win):
        super().__init__()
        self.main = main_win
        self.items = {}
        self.pool = _api.QThreadPool()
        self.active_workers: dict = {}  # iid → YtdlpWorker, O(1) поиск
        self._dl_pct: dict = {}         # iid → последний % загрузки (для прогресса в таскбаре)
        self._kodik_last_url = ""       # для какой ссылки уже подгружены списки

        self.fetch_timer = _api.QTimer()
        self.fetch_timer.setSingleShot(True)
        self.fetch_timer.setInterval(800)
        self.fetch_timer.timeout.connect(self._start_fetch)
        self.info_worker = None
        self._info_workers = set()  # retain cancelled threads until they actually finish
        self._source_duration = None
        self._source_url = ""
        self._timing_url = ""
        self._url_start_s = None    # тайминг из ?t=/&t= ссылки (None — не задан)
        self.setup_ui()
        self.kodik_info_sig.connect(self._populate_kodik)

    def setup_ui(self):
        root = _api.QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6); root.setSpacing(8)
        # ЛЕВО — добавление ссылки + список результатов (как очередь в 1-й вкладке)
        left_w = _api.QWidget(); left = _api.QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0); left.setSpacing(6)
        # ПРАВО — все настройки в прокручиваемой панели
        right_scroll = _api.QScrollArea(); right_scroll.setWidgetResizable(True)
        right_scroll.setFixedWidth(460)                       # всегда полноразмерно, как в 1-й вкладке
        right_scroll.setFrameShape(_api.QFrame.Shape.NoFrame)
        # AsNeeded (не Off) — страховка: если контент чуть шире, он остаётся
        # доступным прокруткой, а не обрезается. После ужатия строк ниже
        # полоса в норме не появляется.
        right_scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_w.setMinimumWidth(140)
        right_w = _api.QWidget(); layout = _api.QVBoxLayout(right_w)
        layout.setContentsMargins(6, 4, 6, 4); layout.setSpacing(8)
        right_scroll.setWidget(right_w)
        root.addWidget(left_w, 1); root.addWidget(right_scroll, 0)
        grp = _api.QGroupBox("Источник"); fl = _api.QFormLayout()
        fl.setSpacing(6)

        self.url_edit = _api.QLineEdit(); self.url_edit.setPlaceholderText("Вставьте ссылку.")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
        self.url_edit.customContextMenuRequested.connect(self.on_url_ctx)

        # Отдельной кнопки «Проверить ссылку» нет — длительность/инфо и списки
        # Kodik подтягиваются автоматически при вставке/изменении ссылки.
        self.url_edit.textChanged.connect(self._on_url_edited)

        h = _api.QHBoxLayout()
        btn_v = _api._icon_btn("Скачать", 'fa5s.download'); btn_v.clicked.connect(lambda: self.add_dl(False))
        btn_a = _api._icon_btn("Скачать (аудио)", 'fa5s.music'); btn_a.clicked.connect(lambda: self.add_dl(True))
        self.btn_stop = _api._icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e'); self.btn_stop.setObjectName("b_stop")
        self.btn_stop.clicked.connect(self.stop_all_dl)
        self.btn_stop.setEnabled(False)   # активна только при активных загрузках

        h.addWidget(self.url_edit); h.addWidget(btn_v); h.addWidget(btn_a); h.addWidget(self.btn_stop)

        self.out = _api.QLineEdit(_api.default_download_dir())
        btn_p = _api._icon_btn("", 'fa5s.folder-open'); btn_p.clicked.connect(self.ch_dir)
        ho = _api.QHBoxLayout(); ho.addWidget(self.out); ho.addWidget(btn_p)

        self.cookie_edit = _api.QLineEdit(); self.cookie_edit.setPlaceholderText("Путь к файлу cookies.txt (необязательно)")
        self.cookie_edit.setClearButtonEnabled(True)
        btn_ck = _api._icon_btn("", 'fa5s.folder-open')
        btn_ck.clicked.connect(self._choose_cookie)
        ho_ck = _api.QHBoxLayout(); ho_ck.addWidget(self.cookie_edit); ho_ck.addWidget(btn_ck)

        self.proxy_edit = _api.QLineEdit()
        self.proxy_edit.setPlaceholderText("http://host:port")
        self.proxy_edit.setClearButtonEnabled(True)
        ho_px = _api.QHBoxLayout(); ho_px.addWidget(self.proxy_edit)

        # Аниме-сайты с плеером Kodik (animego и т.п.): выбор серии и озвучки.
        # Списки заполняются автоматически после вставки ссылки. Только выбор.
        self.kodik_ep = _api.QComboBox()
        self.kodik_ep.addItem("—")              # пока ссылка не вставлена
        self.kodik_ep.setFixedWidth(64)
        self.kodik_trans = _api.QComboBox()
        self.kodik_trans.addItem("—")
        # узкие min/max + короткие подписи — длинные названия озвучек не
        # распирают правую панель (в выпадающем списке текст эллипсизируется).
        self.kodik_trans.setMinimumWidth(90)
        self.kodik_trans.setMaximumWidth(128)
        # Высота ряда Kodik выставляется ниже, вместе с остальными строками
        # (общая константа _ROW_H) — иначе ряд «выпадает» из ритма и отступ от
        # Прокси выглядит неровным.
        ho_kd = _api.QHBoxLayout(); ho_kd.setSpacing(4)
        ho_kd.addWidget(_api.QLabel("Сер.:")); ho_kd.addWidget(self.kodik_ep)
        ho_kd.addWidget(_api.QLabel("Озв.:")); ho_kd.addWidget(self.kodik_trans)
        ho_kd.addStretch()

        # URL + кнопки скачивания — слева (это «добавление»)
        left.addWidget(_api.QLabel("Ссылка для скачивания:"))
        left.addLayout(h)
        fl.addRow(_api.label_with_info("Папка:", "Папка, куда сохраняются скачанные видео и аудио. "
                                  ), ho)
        fl.addRow(_api.label_with_info("Cookies:", "Файл cookies.txt для приватных/возрастных видео. Получите файл cookies через любое расширение браузера и выберите к нему путь. В ином случае, половина видео может не скачиваться"), ho_ck)
        fl.addRow(_api.label_with_info("Прокси:", "Прокси для скачивания (yt-dlp). Помогает при блокировке YouTube провайдером. "
                                  "Браузерный VPN тут не работает — нужен именно прокси. Примеры: http://127.0.0.1:8080, socks5://127.0.0.1:1080"), ho_px)
        fl.addRow(_api.label_with_info("Kodik:", "Для сайтов с плеером Kodik (animego и т.п.): номер серии и название озвучки. "
                                  "После вставки ссылки списки заполняются автоматически, в лог выводится число серий и доступные озвучки. "
                                  "Примечание: 1080p на таких сайтах обычно апскейл, реальный максимум — 720p."), ho_kd)
        # Единая высота строк Папка/Cookies/Прокси/Kodik.
        #
        # Глобальный STYLESHEET задаёт QPushButton{min-height:24px;
        # padding:5px 14px} → 36px, а QLineEdit{min-height:22px; padding:4px 7px}
        # → 32px, из-за чего кнопки «папка» торчали выше строк ввода. Одного
        # setFixedSize тут мало: QStyleSheetStyle при полировке виджета
        # выставляет minimumSize из min-width/min-height таблицы стилей и
        # затирает всё, что проставлено руками (кнопка сжималась до 20px по
        # ширине — соседнее поле забирало место). Поэтому размер кнопок задаём
        # ИМЕННО их собственным правилом; фон, рамка и hover при этом
        # по-прежнему приходят каскадом из глобального листа.
        # 30px содержимого + рамка 1px с каждой стороны = 32×32 — ровно высота
        # строки, кнопка квадратная.
        _ROW_H = 32
        _BTN_QSS = ("QPushButton{padding:0px;"
                    f"min-width:{_ROW_H - 2}px;max-width:{_ROW_H - 2}px;"
                    f"min-height:{_ROW_H - 2}px;max-height:{_ROW_H - 2}px;}}")
        for _b in (btn_p, btn_ck):
            _b.setStyleSheet(_BTN_QSS)
            # Значок 20×20 (умолчание _icon_btn) в такой кнопке занимал почти
            # всю её высоту и выглядел крупнее строки ввода рядом.
            _b.setIconSize(_api.QSize(14, 14))
        for _w in (self.out, self.cookie_edit, self.proxy_edit):
            _w.setFixedHeight(_ROW_H)
        self.kodik_ep.setFixedHeight(_ROW_H)
        self.kodik_trans.setFixedHeight(_ROW_H)
        fl.setVerticalSpacing(4)
        grp.setLayout(fl); layout.addWidget(grp)

        opt = _api.QGroupBox("Опции"); ho = _api.QHBoxLayout()
        self.c_q = _api.QComboBox(); self.c_q.addItems(list(_api.FORMAT_OPTIONS.keys())); self.c_q.setCurrentText("1080p")
        self.c_c = _api.QComboBox(); self.c_c.addItems(_api.MERGE_OPTIONS)
        # Списки субтитров/языка пусты, пока не добавлено видео. Заполняются
        # реально доступными дорожками после пробы метаданных (см.
        # _on_info_success/_populate_lang_combos). Так в них не висят ru/en/…,
        # когда видео ещё не добавлено или других дорожек у него нет.
        self.c_s = _api.QComboBox()
        self.c_a = _api.QComboBox()
        # компактные комбобоксы опций — чтобы ряд Кач./Конт. не распирал панель
        self.c_q.setMaximumWidth(96); self.c_c.setMaximumWidth(72)
        self.c_s.setMaximumWidth(84); self.c_a.setMaximumWidth(120)
        self.chk_k = _api.QCheckBox("Force KF")
        ho.addWidget(_api.QLabel("Кач.:")); ho.addWidget(self.c_q)
        ho.addWidget(_api.info_badge("Максимальная высота видео. Качается лучшее видео до выбранной высоты + лучшее аудио, затем склейка."))
        ho.addWidget(_api.QLabel("Конт.:")); ho.addWidget(self.c_c)
        ho.addWidget(_api.info_badge("Контейнер для склейки: mp4 — макс. совместимость, mkv — SiQuester не поддерживает, webm — для VP9/Opus."))
        ho.addStretch()
        # Субтитры и язык — отдельной строкой
        ho_sl = _api.QHBoxLayout()
        ho_sl.addWidget(_api.QLabel("Суб.:")); ho_sl.addWidget(self.c_s)
        ho_sl.addWidget(_api.info_badge("Скачивать субтитры выбранного языка. all — все доступные дорожки субтитров."))
        ho_sl.addWidget(_api.QLabel("Язык:")); ho_sl.addWidget(self.c_a)
        ho_sl.addWidget(_api.info_badge("Предпочитаемая аудиодорожка — для видео с несколькими озвучками."))
        ho_sl.addStretch()
        # Force KF — отдельной строкой (в ряд с Кач-во/Конт. не помещается).
        ho_kf = _api.QHBoxLayout()
        ho_kf.addWidget(self.chk_k)
        ho_kf.addWidget(_api.info_badge("Force KF — точная нарезка по таймингам: вставляет ключевые кадры в точках реза. Точнее, но медленнее(понятия не имею, зачем оно)"))
        ho_kf.addStretch()
        v = _api.QVBoxLayout(); v.addLayout(ho); v.addLayout(ho_sl); v.addLayout(ho_kf)

        ht = _api.QVBoxLayout()
        start_box = _api.QHBoxLayout(); start_box.setSpacing(2)
        self.ts = [_api.ZeroSpinBox() for _ in range(3)]
        for s in self.ts:
            s.setRange(0,59); s.setButtonSymbols(_api.QAbstractSpinBox.ButtonSymbols.NoButtons); s.setFixedWidth(34)
            s.valueChanged.connect(self._spin_to_sliders)
        start_box.addWidget(_api.QLabel("С:"))
        for w in self.ts: start_box.addWidget(w)

        end_box = _api.QHBoxLayout(); end_box.setSpacing(2)
        self.te = [_api.ZeroSpinBox() for _ in range(3)]
        for s in self.te:
            s.setRange(0,59); s.setButtonSymbols(_api.QAbstractSpinBox.ButtonSymbols.NoButtons); s.setFixedWidth(34)
            s.valueChanged.connect(self._spin_to_sliders)
        end_box.addWidget(_api.QLabel("По:"))
        for w in self.te: end_box.addWidget(w)

        btn_clear_time = _api._icon_btn("", 'fa5s.times')
        # Равная высота с полями-циферками слева (С: / По:), чтобы стоять с ними в одну строку
        btn_clear_time.setFixedHeight(self.ts[0].sizeHint().height())
        btn_clear_time.setFixedWidth(40)
        btn_clear_time.setToolTip("Сбросить тайминги")
        btn_clear_time.clicked.connect(self._clear_timings)

        sliders_box = _api.QVBoxLayout()
        # _JumpSlider — клик по дорожке сразу ставит ползунок в точку клика
        # (а не «ползёт» на pageStep). Двигать можно и кликом, и протаскиванием.
        self.slider_start = _api._JumpSlider(_api.Qt.Orientation.Horizontal)
        self.slider_end = _api._JumpSlider(_api.Qt.Orientation.Horizontal)
        self.slider_start.setRange(0, 36000); self.slider_end.setRange(0, 36000)
        self.slider_start.valueChanged.connect(self._slider_to_spins)
        self.slider_end.valueChanged.connect(self._slider_to_spins)

        _time_lbl = _api.QHBoxLayout()
        _time_lbl.addWidget(_api.QLabel("Обрезка:"))
        _time_lbl.addWidget(_api.info_badge("Обрезка: качается только отрезок от Start до End. Пусто = всё видео. Точность нарезки зависит от Force KF."))
        _time_lbl.addStretch()
        sliders_box.addLayout(_time_lbl)
        sliders_box.addWidget(self.slider_start); sliders_box.addWidget(self.slider_end)

        # Быстрые кнопки длины отрезка: ставят ползунок «По» на +N от ползунка «С».
        # Удобно, когда нужен ровный кусок фиксированной длины от выбранной точки.
        dur_box = _api.QHBoxLayout(); dur_box.setSpacing(4)
        dur_box.addWidget(_api.QLabel("Длина:"))
        for _lbl, _sec in (("+30с", 30), ("+1 мин", 60), ("+3 мин", 180), ("+5 мин", 300)):
            _b = _api.QPushButton(_lbl)
            _b.setToolTip(f"Поставить «По» на +{_lbl.lstrip('+')} от ползунка «С»")
            _b.clicked.connect(lambda _=False, s=_sec: self._add_duration(s))
            dur_box.addWidget(_b)
        dur_box.addStretch()
        sliders_box.addLayout(dur_box)

        # Спинбоксы С:/По: + Сбросить — одной строкой; ползунки — ниже (чтобы
        # всё влезало в фиксированную ширину правой панели, как в 1-й вкладке).
        ht_top = _api.QHBoxLayout()
        ht_top.addLayout(start_box); ht_top.addSpacing(8); ht_top.addLayout(end_box); ht_top.addSpacing(8)
        ht_top.addWidget(btn_clear_time, 0, _api.Qt.AlignmentFlag.AlignVCenter); ht_top.addStretch()
        ht.addLayout(ht_top); ht.addLayout(sliders_box)
        v.setSpacing(10)
        v.addLayout(ht); opt.setLayout(v); layout.addWidget(opt)
        layout.addStretch()

        self.tree = _api.QTreeWidget(); self.tree.setHeaderLabels(["URL", "Размер", "Инфо", "Статус"])
        self.tree.setColumnWidth(0, 380); self.tree.setColumnWidth(3, 100)
        self.tree.setIconSize(_api.QSize(160,90)); self.tree.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
        # Список плоский (вложенности нет) — убираем отступ-«ветку» и стрелку
        # раскрытия слева, из-за которых у строк появлялась пустая область слева.
        self.tree.setIndentation(0); self.tree.setRootIsDecorated(False)
        # Цветовая подсветка строк по статусу (синий — качается, зелёный — готово,
        # красный — ошибка) + видимое выделение при клике — как на странице обработки.
        self.tree.setItemDelegate(_api.StatusColorDelegate(self.tree))
        self.tree.customContextMenuRequested.connect(self.ctx)
        left.addWidget(self.tree, 1)
        # Клавиша Delete — удалить выделенные загрузки из списка
        self._sc_delete = _api.QShortcut(_api.QKeySequence(_api.Qt.Key.Key_Delete), self.tree)
        self._sc_delete.setContext(_api.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_delete.activated.connect(self.delete_sel)

        hb = _api.QHBoxLayout()
        b_del = _api._icon_btn("Удалить", 'fa5s.times'); b_del.clicked.connect(self.delete_sel)
        b_clr = _api._icon_btn("Очистить", 'fa5s.trash'); b_clr.clicked.connect(self.tree.clear)
        hb.addWidget(b_del); hb.addWidget(b_clr); hb.addStretch(); left.addLayout(hb)

    def _spin_to_sliders(self):
        try:
            start_s = self.ts[0].value()*3600 + self.ts[1].value()*60 + self.ts[2].value()
            end_s = self.te[0].value()*3600 + self.te[1].value()*60 + self.te[2].value()
            maxv = max(self.slider_start.maximum(), 1)
            start_s = max(0, min(start_s, maxv))
            end_s = max(0, min(end_s, self.slider_end.maximum()))
            if end_s < start_s: end_s = start_s
            self.slider_start.blockSignals(True); self.slider_end.blockSignals(True)
            self.slider_start.setValue(start_s); self.slider_end.setValue(end_s)
            self.slider_start.blockSignals(False); self.slider_end.blockSignals(False)
        except Exception: pass

    def _add_duration(self, seconds):
        """Ставит ползунок «По» на +seconds от текущего ползунка «С»
        (кнопки быстрой длины отрезка). Спинбоксы обновятся через сигнал."""
        try:
            start_s = self.slider_start.value()
            end_s = min(start_s + seconds, self.slider_end.maximum())
            self.slider_end.setValue(end_s)
        except Exception: pass

    def _fill_time_boxes(self, sec, boxes):
        """Заполняет три спинбокса (ч, м, с) из значения в секундах."""
        h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
        for box in boxes: box.blockSignals(True)
        boxes[0].setValue(h); boxes[1].setValue(m); boxes[2].setValue(s)
        for box in boxes: box.blockSignals(False)

    def _slider_to_spins(self):
        try:
            start_s = self.slider_start.value()
            end_s = self.slider_end.value()
            if end_s < start_s:
                end_s = start_s
                self.slider_end.blockSignals(True); self.slider_end.setValue(end_s); self.slider_end.blockSignals(False)
            self._fill_time_boxes(start_s, self.ts)
            self._fill_time_boxes(end_s, self.te)
        except Exception: pass

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

    def add_dl(self, audio_only=False):
        self.fetch_timer.stop()
        try:
            url = self.url_edit.text().strip()
            if not url: return
            iid = _api.uuid.uuid4().hex
            config = self._dl_config(iid, url, audio_only)
            self.url_edit.clear()
            it = _api.QTreeWidgetItem(self.tree)
            it.setText(0, url); it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
            it.setData(0, _api.Qt.ItemDataRole.UserRole, iid)
            it.setData(0, _api.ITEM_STATUS_ROLE, 'proc')  # синяя подсветка «в работе»
            self.items[iid] = {'item': it, 'url': url, 'audio_only': bool(audio_only)}
            self._start_download(config)
        except Exception as e:
            self.main.log(f"add_dl error: {e}")

    def _update_stop_btn(self):
        """Кнопка СТОП активна только когда есть хотя бы одна активная загрузка."""
        active = bool(self.active_workers)
        try: self.btn_stop.setEnabled(active)
        except Exception: pass
        # Зеркалим состояние на кнопку СТОП в строке «Быстрая загрузка»
        # вкладки «Обработка» — быстрые загрузки идут через этот же пул.
        try: self.main.tab_media.btn_qdl_stop.setEnabled(active)
        except Exception: pass

    def _update_dl_taskbar(self):
        """Сводный прогресс загрузок на иконке в панели задач:
          • есть реальный % (v>0) — средний % (обычный режим);
          • идёт загрузка, но % неизвестен (тихий ffmpeg, v==-1) — бегущая полоса;
          • только подготовка/извлечение (v==0) или активных нет — снять индикатор,
            чтобы падающее извлечение не выглядело как «что-то грузится»."""
        try:
            vals = [v for v in self._dl_pct.values() if v is not None]
            real = [v for v in vals if v > 0]
            if real:
                self.main.set_taskbar_progress(int(sum(real) / len(real)), 100)
            elif any(v < 0 for v in vals):
                self.main.set_taskbar_progress(0, 100)  # 0 → неопределённый режим
            else:
                self.main.clear_taskbar_progress()
        except Exception:
            pass

    def _remove_worker(self, iid, worker=None):
        if worker is not None and self.active_workers.get(iid) is not worker:
            return
        self.active_workers.pop(iid, None)
        # Сигнал finished у потока срабатывает ВСЕГДА при его завершении — даже если
        # загрузка упала, не отправив error_sig/finished_sig (тогда в _dl_pct оставался
        # бы «-1», и на иконке в панели задач навсегда зависала «бегущая полоса»
        # загрузки, хотя по факту ошибка). Снимаем элемент из прогресса здесь —
        # это гарантированно убирает индикатор после ошибочной/прерванной загрузки.
        self._dl_pct.pop(iid, None)
        self._update_dl_taskbar()
        self._update_stop_btn()

    def _dl_config(self, iid, url, audio_only):
        """Конфиг загрузки из текущих настроек вкладки. Общий для add_dl и
        перезапуска (redownload), чтобы режимы не расходились."""
        start = self.get_sec(self.ts) or None
        end = self.get_sec(self.te) or None
        duration = self._source_duration if self._source_url == url else None
        if not start and duration and end and end >= duration:
            end = None
        return {
            'iid': iid, 'url': url, 'fmt': _api.FORMAT_OPTIONS.get(self.c_q.currentText(), 'best'),
            'outdir': self.out.text(), 'merge': self.c_c.currentText(), 'sub_lang': self.c_s.currentText(),
            'audio': self.c_a.currentText(), 'force_kf': self.chk_k.isChecked(),
            'start_s': start, 'end_s': end, 'source_duration': duration,
            'audio_only': bool(audio_only),
            'cookie_path': self.cookie_edit.text().strip(),
            'proxy': self.proxy_edit.text().strip(),
            'kodik_episode': self._kodik_episode_value(),
            'kodik_translation': (lambda t: "" if t in ("", "—") else t)(self.kodik_trans.currentText().strip()),
        }

    def _start_download(self, config):
        iid = config['iid']
        self.items[iid]['config'] = dict(config)
        worker = _api.YtdlpWorker(config)
        self.active_workers[iid] = worker
        worker.finished.connect(lambda i=iid, w=worker: self._remove_worker(i, w))
        self._connect_worker_signals(worker, iid)
        worker.start()
        self._update_stop_btn()

    def redownload_sel(self):
        """Скачать выбранные заново В ТОЙ ЖЕ строке — без дубля в списке.
        Если по элементу ещё идёт воркер, СНАЧАЛА останавливаем его: иначе два
        процесса пишут один и тот же выходной файл и падают с WinError 32
        («файл занят другим процессом», 'X.m4a'->'X.m4a')."""
        for it in list(self.tree.selectedItems()):
            try:
                iid = it.data(0, _api.Qt.ItemDataRole.UserRole)
                entry = self.items.get(iid, {}) if iid else {}
                url = (entry.get('url') if isinstance(entry, dict) else "") or it.text(0)
                if not (url and url.strip().startswith('http')):
                    continue
                url = url.strip()
                audio_only = bool(entry.get('audio_only', False)) if isinstance(entry, dict) else False
                # Гасим прежний воркер этого же элемента (если ещё активен) —
                # не плодим второй процесс на тот же файл.
                old = self.active_workers.get(iid)
                current = self._dl_config(iid, url, audio_only)
                config = dict(entry.get('config') or current)
                # Retain this video's range/episode, while allowing the user to
                # retry with a different proxy, cookies or quality.
                for key in ('fmt', 'merge', 'sub_lang', 'audio', 'force_kf', 'cookie_path', 'proxy'):
                    config[key] = current[key]
                config['overwrite'] = True
                entry['restart_config'] = config

                def restart(i=iid, item=it, saved=entry, settings=config, address=url):
                    if self.items.get(i) is not saved or saved.get('restart_config') is not settings:
                        return
                    saved.pop('restart_config', None)
                    item.setText(1, "-"); item.setText(2, "-"); item.setText(3, "В очереди")
                    item.setToolTip(3, "")
                    item.setData(0, _api.ITEM_STATUS_ROLE, 'proc')
                    self.tree.viewport().update()
                    self._start_download(settings)
                    self.main.log(f"Повторная загрузка: {address}")

                if old and old.isRunning():
                    old.finished.connect(restart)
                    old.stop()
                else:
                    restart()
            except Exception as e:
                self.main.log(f"redownload error: {e}")

    def delete_sel(self):
        try:
            for it in list(self.tree.selectedItems()):
                iid = it.data(0, _api.Qt.ItemDataRole.UserRole)
                if iid:
                    worker = self.active_workers.get(iid)
                    if worker:
                        worker.stop()
                    self.items.pop(iid, None)
                self.tree.invisibleRootItem().removeChild(it)
            self._update_stop_btn()
        except Exception: pass

    def set_thumb(self, iid, icon):
        try:
            entry = self.items.get(iid)
            if entry and isinstance(entry, dict):
                it = entry.get('item')
                if it and isinstance(it, _api.QTreeWidgetItem):
                    it.setIcon(0, icon)
        except Exception: pass


YtdlpTab.__module__ = _api.__name__
_api.YtdlpTab = YtdlpTab
