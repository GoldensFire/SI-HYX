# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# tabs.py — вкладки интерфейса
from config import *
from utils import *
from widgets import *
from workers import *
from PyQt6.QtWidgets import QSizePolicy


class YtdlpTab(QWidget):
    thumb_sig = pyqtSignal(str, QIcon)
    kodik_info_sig = pyqtSignal(object, int, str, int)  # (озвучки, число серий, тек.озвучка, тек.серия)
    def __init__(self, main_win):
        super().__init__()
        self.main = main_win
        self.items = {}
        self.pool = QThreadPool()
        self.active_workers: dict = {}  # iid → YtdlpWorker, O(1) поиск
        self._dl_pct: dict = {}         # iid → последний % загрузки (для прогресса в таскбаре)
        self._kodik_last_url = ""       # для какой ссылки уже подгружены списки

        self.fetch_timer = QTimer()
        self.fetch_timer.setSingleShot(True)
        self.fetch_timer.setInterval(800)
        self.fetch_timer.timeout.connect(self._start_fetch)
        self.info_worker = None
        self.setup_ui()
        self.kodik_info_sig.connect(self._populate_kodik)

    def setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6); root.setSpacing(8)
        # ЛЕВО — добавление ссылки + список результатов (как очередь в 1-й вкладке)
        left_w = QWidget(); left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0); left.setSpacing(6)
        # ПРАВО — все настройки в прокручиваемой панели
        right_scroll = QScrollArea(); right_scroll.setWidgetResizable(True)
        right_scroll.setFixedWidth(460)                       # всегда полноразмерно, как в 1-й вкладке
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # AsNeeded (не Off) — страховка: если контент чуть шире, он остаётся
        # доступным прокруткой, а не обрезается. После ужатия строк ниже
        # полоса в норме не появляется.
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_w.setMinimumWidth(140)
        right_w = QWidget(); layout = QVBoxLayout(right_w)
        layout.setContentsMargins(6, 4, 6, 4); layout.setSpacing(8)
        right_scroll.setWidget(right_w)
        root.addWidget(left_w, 1); root.addWidget(right_scroll, 0)
        grp = QGroupBox("Источник"); fl = QFormLayout()
        fl.setSpacing(6)
        
        self.url_edit = QLineEdit(); self.url_edit.setPlaceholderText("Вставьте ссылку.")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.url_edit.customContextMenuRequested.connect(self.on_url_ctx)
        
        # Отдельной кнопки «Проверить ссылку» нет — длительность/инфо и списки
        # Kodik подтягиваются автоматически при вставке/изменении ссылки.
        self.url_edit.textChanged.connect(lambda: self.fetch_timer.start())

        h = QHBoxLayout()
        btn_v = QPushButton("⬇  Скачать"); btn_v.clicked.connect(lambda: self.add_dl(False))
        btn_a = QPushButton("🎵  Скачать (Audio)"); btn_a.clicked.connect(lambda: self.add_dl(True))
        self.btn_stop = QPushButton("■  СТОП"); self.btn_stop.setObjectName("b_stop")
        self.btn_stop.clicked.connect(self.stop_all_dl)
        self.btn_stop.setEnabled(False)   # активна только при активных загрузках
        
        h.addWidget(self.url_edit); h.addWidget(btn_v); h.addWidget(btn_a); h.addWidget(self.btn_stop)
        
        self.out = QLineEdit(default_download_dir())
        btn_p = QPushButton("📂"); btn_p.clicked.connect(self.ch_dir); btn_p.setFixedWidth(36)
        ho = QHBoxLayout(); ho.addWidget(self.out); ho.addWidget(btn_p)

        self.cookie_edit = QLineEdit(); self.cookie_edit.setPlaceholderText("Путь к файлу cookies.txt (необязательно)")
        self.cookie_edit.setClearButtonEnabled(True)
        btn_ck = QPushButton("📂"); btn_ck.setFixedWidth(36)
        btn_ck.clicked.connect(self._choose_cookie)
        ho_ck = QHBoxLayout(); ho_ck.addWidget(self.cookie_edit); ho_ck.addWidget(btn_ck)

        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("http://host:port")
        self.proxy_edit.setClearButtonEnabled(True)
        ho_px = QHBoxLayout(); ho_px.addWidget(self.proxy_edit)

        # Аниме-сайты с плеером Kodik (animego и т.п.): выбор серии и озвучки.
        # Списки заполняются автоматически после вставки ссылки. Только выбор.
        self.kodik_ep = QComboBox()
        self.kodik_ep.addItem("—")              # пока ссылка не вставлена
        self.kodik_ep.setFixedWidth(64)
        self.kodik_trans = QComboBox()
        self.kodik_trans.addItem("—")
        # узкие min/max + короткие подписи — длинные названия озвучек не
        # распирают правую панель (в выпадающем списке текст эллипсизируется).
        self.kodik_trans.setMinimumWidth(90)
        self.kodik_trans.setMaximumWidth(128)
        # та же высота, что у строк выше — иначе ряд Kodik «выпадает» из ритма
        # и отступ от Прокси выглядит неровным.
        self.kodik_ep.setFixedHeight(26); self.kodik_trans.setFixedHeight(26)
        ho_kd = QHBoxLayout(); ho_kd.setSpacing(4)
        ho_kd.addWidget(QLabel("Сер.:")); ho_kd.addWidget(self.kodik_ep)
        ho_kd.addWidget(QLabel("Озв.:")); ho_kd.addWidget(self.kodik_trans)
        ho_kd.addStretch()

        # URL + кнопки скачивания — слева (это «добавление»)
        left.addWidget(QLabel("Ссылка для скачивания:"))
        left.addLayout(h)
        fl.addRow("Папка:", ho)
        fl.addRow(label_with_info("Cookies:", "Файл cookies.txt для приватных/возрастных видео. Для YouTube обычно не требуется (скачивание идёт через клиент tv + Deno)."), ho_ck)
        fl.addRow(label_with_info("Прокси:", "Прокси для скачивания (yt-dlp). Помогает при блокировке YouTube провайдером. "
                                  "Браузерный VPN тут не работает — нужен именно прокси. Примеры: http://127.0.0.1:8080, socks5://127.0.0.1:1080"), ho_px)
        fl.addRow(label_with_info("Kodik:", "Для сайтов с плеером Kodik (animego и т.п.): номер серии и название озвучки. "
                                  "После вставки ссылки списки заполняются автоматически, в лог выводится число серий и доступные озвучки. "
                                  "«тек.»/пусто = серия и озвучка по умолчанию. Примечание: 1080p на таких сайтах обычно апскейл, реальный максимум — 720p."), ho_kd)
        # Поля Папка/Cookies/Прокси — компактнее по высоте
        for _w in (self.out, btn_p, self.cookie_edit, btn_ck, self.proxy_edit):
            _w.setFixedHeight(26)
        fl.setVerticalSpacing(4)
        grp.setLayout(fl); layout.addWidget(grp)

        opt = QGroupBox("Опции"); ho = QHBoxLayout()
        self.c_q = QComboBox(); self.c_q.addItems(list(FORMAT_OPTIONS.keys())); self.c_q.setCurrentText("1080p")
        self.c_c = QComboBox(); self.c_c.addItems(MERGE_OPTIONS)
        self.c_s = QComboBox(); self.c_s.addItems(SUB_OPTIONS)
        self.c_a = QComboBox(); self.c_a.addItems(AUDIO_OPTIONS)
        # компактные комбобоксы опций — чтобы ряд Кач./Конт. не распирал панель
        self.c_q.setMaximumWidth(96); self.c_c.setMaximumWidth(72)
        self.c_s.setMaximumWidth(84); self.c_a.setMaximumWidth(120)
        self.chk_k = QCheckBox("Force KF")
        ho.addWidget(QLabel("Кач.:")); ho.addWidget(self.c_q)
        ho.addWidget(info_badge("Максимальная высота видео. Качается лучшее видео до выбранной высоты + лучшее аудио, затем склейка."))
        ho.addWidget(QLabel("Конт.:")); ho.addWidget(self.c_c)
        ho.addWidget(info_badge("Контейнер для склейки: mp4 — макс. совместимость, mkv — SiQuester не поддерживает, webm — для VP9/Opus."))
        ho.addStretch()
        # Субтитры и язык — отдельной строкой
        ho_sl = QHBoxLayout()
        ho_sl.addWidget(QLabel("Суб.:")); ho_sl.addWidget(self.c_s)
        ho_sl.addWidget(info_badge("Скачивать субтитры выбранного языка. all — все доступные дорожки субтитров."))
        ho_sl.addWidget(QLabel("Язык:")); ho_sl.addWidget(self.c_a)
        ho_sl.addWidget(info_badge("Предпочитаемая аудиодорожка — для видео с несколькими озвучками."))
        ho_sl.addStretch()
        # Force KF — отдельной строкой (в ряд с Кач-во/Конт. не помещается).
        ho_kf = QHBoxLayout()
        ho_kf.addWidget(self.chk_k)
        ho_kf.addWidget(info_badge("Force KF — точная нарезка по таймингам: вставляет ключевые кадры в точках реза. Точнее, но медленнее(понятия не имею, зачем оно)"))
        ho_kf.addStretch()
        v = QVBoxLayout(); v.addLayout(ho); v.addLayout(ho_sl); v.addLayout(ho_kf)

        ht = QVBoxLayout()
        start_box = QHBoxLayout(); start_box.setSpacing(2)
        self.ts = [ZeroSpinBox() for _ in range(3)]
        for s in self.ts:
            s.setRange(0,59); s.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons); s.setFixedWidth(34)
            s.valueChanged.connect(self._spin_to_sliders)
        start_box.addWidget(QLabel("С:"))
        for w in self.ts: start_box.addWidget(w)

        end_box = QHBoxLayout(); end_box.setSpacing(2)
        self.te = [ZeroSpinBox() for _ in range(3)]
        for s in self.te:
            s.setRange(0,59); s.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons); s.setFixedWidth(34)
            s.valueChanged.connect(self._spin_to_sliders)
        end_box.addWidget(QLabel("По:"))
        for w in self.te: end_box.addWidget(w)

        btn_clear_time = QPushButton("✕")
        # Равная высота с полями-циферками слева (С: / По:), чтобы стоять с ними в одну строку
        btn_clear_time.setFixedHeight(self.ts[0].sizeHint().height())
        btn_clear_time.setFixedWidth(40)
        btn_clear_time.setToolTip("Сбросить тайминги")
        btn_clear_time.clicked.connect(self._clear_timings)

        sliders_box = QVBoxLayout()
        self.slider_start = QSlider(Qt.Orientation.Horizontal)
        self.slider_end = QSlider(Qt.Orientation.Horizontal)
        self.slider_start.setRange(0, 36000); self.slider_end.setRange(0, 36000)
        self.slider_start.valueChanged.connect(self._slider_to_spins)
        self.slider_end.valueChanged.connect(self._slider_to_spins)

        _time_lbl = QHBoxLayout()
        _time_lbl.addWidget(QLabel("Обрезка:"))
        _time_lbl.addWidget(info_badge("Обрезка: качается только отрезок от Start до End. Пусто = всё видео. Точность нарезки зависит от Force KF."))
        _time_lbl.addStretch()
        sliders_box.addLayout(_time_lbl)
        sliders_box.addWidget(self.slider_start); sliders_box.addWidget(self.slider_end)

        # Спинбоксы С:/По: + Сбросить — одной строкой; ползунки — ниже (чтобы
        # всё влезало в фиксированную ширину правой панели, как в 1-й вкладке).
        ht_top = QHBoxLayout()
        ht_top.addLayout(start_box); ht_top.addSpacing(8); ht_top.addLayout(end_box); ht_top.addSpacing(8)
        ht_top.addWidget(btn_clear_time, 0, Qt.AlignmentFlag.AlignVCenter); ht_top.addStretch()
        ht.addLayout(ht_top); ht.addLayout(sliders_box)
        v.setSpacing(10)
        v.addLayout(ht); opt.setLayout(v); layout.addWidget(opt)
        layout.addStretch()

        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["URL", "Размер", "Инфо", "Статус"])
        self.tree.setColumnWidth(0, 380); self.tree.setColumnWidth(3, 100)
        self.tree.setIconSize(QSize(160,90)); self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.ctx)
        left.addWidget(self.tree, 1)
        # Клавиша Delete — удалить выделенные загрузки из списка
        self._sc_delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree)
        self._sc_delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_delete.activated.connect(self.delete_sel)

        hb = QHBoxLayout()
        b_del = QPushButton("✖  Удалить"); b_del.clicked.connect(self.delete_sel)
        b_clr = QPushButton("🗑  Очистить"); b_clr.clicked.connect(self.tree.clear)
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

    def _start_fetch(self):
        url = self.url_edit.text().strip()
        if not url: return
        self.main.log(f"Запрос метаданных для: {url[:30]}...")

        # Для Kodik-сайтов (animego и т.п.) — подгружаем списки озвучек и серий
        # в выпадашки (один раз на ссылку).
        if is_embed_candidate(url) and url != self._kodik_last_url:
            self._kodik_last_url = url
            def _kinfo(u=url, px=self.proxy_edit.text().strip()):
                try:
                    info = kodik_get_info(u, proxy=px)
                    tr = info.get("translations") or []
                    if tr:
                        self.kodik_info_sig.emit(
                            tr, int(info.get("episodes", 0)),
                            info.get("cur_translation", "") or "",
                            int(info.get("cur_episode", 0) or 0))
                except Exception:
                    pass
            threading.Thread(target=_kinfo, daemon=True).start()
        # Отменяем предыдущий воркер через флаг — НЕ terminate(), он вызывает сегфолт в PyQt6
        if self.info_worker and self.info_worker.isRunning():
            self.info_worker.cancelled = True
            # Отключаем сигналы старого воркера чтобы не получить stale callback
            try: self.info_worker.success.disconnect()
            except Exception: pass
            try: self.info_worker.error.disconnect()
            except Exception: pass
            # Не ждём завершения — пусть доработает в фоне и тихо умрёт
        self.info_worker = InfoWorker(url, proxy=self.proxy_edit.text().strip())
        self.info_worker.success.connect(self._on_info_success)
        self.info_worker.error.connect(self._on_info_error)
        self.info_worker.start()

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

    def _on_info_success(self, duration, thumb_url):
        self.main.log(f"Длительность получена: {duration} сек.")
        try:
            if duration > 0:
                self.slider_start.setRange(0, duration); self.slider_end.setRange(0, duration)
                self.slider_start.setValue(0); self.slider_end.setValue(duration)
                self._slider_to_spins()
        except Exception: pass

    def _on_info_error(self, err_msg):
        self.main.log(f"[Ошибка метаданных] {err_msg}")

    def _clear_timings(self):
        for box in self.ts + self.te:
            box.blockSignals(True); box.setValue(0); box.blockSignals(False)
        self.slider_start.blockSignals(True); self.slider_start.setValue(0); self.slider_start.blockSignals(False)
        self.slider_end.blockSignals(True);   self.slider_end.setValue(self.slider_end.maximum()); self.slider_end.blockSignals(False)

    def on_url_ctx(self, pos):
        m = QMenu()
        try: cb = QApplication.clipboard().text().strip()
        except Exception: cb = ""
        if cb and cb.startswith("http"):
            a = QAction("Скачать из буфера", self)
            a.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(False)))
            a2 = QAction("Скачать аудио из буфера", self)
            a2.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(True)))
            m.addAction(a); m.addAction(a2); m.addSeparator()
        m.addAction(QAction("Вставить", self, triggered=self.url_edit.paste))
        m.exec(self.url_edit.mapToGlobal(pos))

    def stop_all_dl(self):
        for w in list(self.active_workers.values()):
            try: w.stop()
            except Exception: pass

    def stop_sel_dl(self):
        for it in self.tree.selectedItems():
            iid = it.data(0, Qt.ItemDataRole.UserRole)
            w = self.active_workers.get(iid)
            if w:
                try: w.stop()
                except Exception: pass

    def ctx(self, pos):
        m = QMenu()
        sel = self.tree.itemAt(pos)
        if sel:
            m.addAction(QAction("Перейти к URL (копировать в буфер)", self, triggered=lambda checked=False, it=sel: QApplication.clipboard().setText(it.text(0))))
            m.addAction(QAction("Остановить загрузку", self, triggered=self.stop_sel_dl))
            m.addSeparator()
        try: cb = QApplication.clipboard().text().strip()
        except Exception: cb = ""
        if cb and cb.startswith('http'):
            a_cb = QAction('Скачать из буфера', self); 
            a_cb.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(False)))
            a_cba = QAction('Скачать аудио из буфера', self); 
            a_cba.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(True)))
            m.addAction(a_cb); m.addAction(a_cba); m.addSeparator()
        m.addAction(QAction('Удалить', self, triggered=self.delete_sel))
        m.addAction(QAction('Очистить', self, triggered=self.tree.clear))
        m.exec(self.tree.mapToGlobal(pos))

    def _choose_cookie(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл cookies", "", "Text files (*.txt);;All files (*)")
        if path:
            self.cookie_edit.setText(path)

    def ch_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка", self.out.text())
        if d:
            self.out.setText(d)
            try: self.main.recent_strip.refresh(d)
            except Exception: pass

    def get_sec(self, arr):
        return arr[0].value()*3600 + arr[1].value()*60 + arr[2].value()

    def _connect_worker_signals(self, w: 'YtdlpWorker', iid: str):
        """Подключает стандартные сигналы воркера к обработчикам дерева."""
        def on_prog(iid_, p, t):
            item = self.items.get(iid_, {}).get('item')
            if item:
                # p < 0 — индикатор активности без реального % (download-sections/ffmpeg)
                item.setText(1, "…" if p < 0 else f"{p:.1f}%"); item.setText(3, t)
            self._dl_pct[iid_] = p
            self._update_dl_taskbar()

        def on_done(iid_, status, clean_info, file_path):
            self._dl_pct.pop(iid_, None); self._update_dl_taskbar()
            item = self.items.get(iid_, {}).get('item')
            if item:
                item.setText(3, "✅ " + status)
                for col in range(self.tree.columnCount()):
                    item.setBackground(col, QBrush(COLOR_DONE))
                self.tree.viewport().update()
                if file_path and os.path.exists(file_path):
                    try:
                        dur, br_str, size, a_br = get_media_info(file_path)
                        item.setText(1, human_size(size))
                        item.setText(2, clean_info if clean_info and clean_info != "Unknown" else br_str)
                        self.main.log(f"Загружено: {file_path} ({human_size(size)}, {a_br})")
                    except Exception: pass

        def on_err(iid_, msg):
            self._dl_pct.pop(iid_, None); self._update_dl_taskbar()
            try:
                item = self.items.get(iid_, {}).get('item')
                if not item: return
                item.setText(3, "Ошибка"); item.setToolTip(3, msg)
                for col in range(self.tree.columnCount()):
                    item.setBackground(col, QBrush(COLOR_ERR))
            except RuntimeError:
                pass  # QTreeWidgetItem уже удалён пользователем

        def on_thumb(iid_, thumb_url):
            if thumb_url:
                self.pool.start(RemoteThumbnailRunnable(thumb_url, iid_, self.thumb_sig))

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
            if not outdir or not os.path.exists(outdir):
                outdir = default_download_dir()

            iid = uuid.uuid4().hex
            it = QTreeWidgetItem(self.tree)
            it.setText(0, url); it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
            it.setData(0, Qt.ItemDataRole.UserRole, iid)
            self.items[iid] = {'item': it, 'url': url}

            config = {
                'iid': iid, 'url': url,
                'fmt': FORMAT_OPTIONS.get("1080p", 'bestvideo[height<=1080]+bestaudio/best'),
                'outdir': outdir, 'merge': 'mp4', 'sub_lang': 'Выкл',
                'audio': 'Original', 'force_kf': True,
                'audio_only': bool(audio_only),
                'cookie_path': self.cookie_edit.text().strip() if hasattr(self, 'cookie_edit') else '',
                'proxy': self.proxy_edit.text().strip() if hasattr(self, 'proxy_edit') else '',
            }
            w = YtdlpWorker(config)
            self.active_workers[iid] = w
            w.finished.connect(lambda _=None, i=iid: self._remove_worker(i))
            self._connect_worker_signals(w, iid)
            w.start()
            self._update_stop_btn()
            self.main.log(f"Загрузка добавлена: {url}")
        except Exception as e:
            self.main.log(f"add_dl_direct error: {e}")

    def add_dl(self, audio_only=False):
        self.fetch_timer.stop()
        try:
            url = self.url_edit.text().strip()
            self.url_edit.clear()
            if not url: return
            iid = uuid.uuid4().hex
            it = QTreeWidgetItem(self.tree)
            it.setText(0, url); it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
            it.setData(0, Qt.ItemDataRole.UserRole, iid)
            self.items[iid] = {'item': it, 'url': url}
            config = {
                'iid': iid, 'url': url, 'fmt': FORMAT_OPTIONS.get(self.c_q.currentText(), 'best'),
                'outdir': self.out.text(), 'merge': self.c_c.currentText(), 'sub_lang': self.c_s.currentText(),
                'audio': self.c_a.currentText(), 'force_kf': self.chk_k.isChecked(),
                'start_s': self.get_sec(self.ts) if any(x.value() for x in self.ts) else None,
                'end_s': self.get_sec(self.te) if any(x.value() for x in self.te) else None,
                'audio_only': bool(audio_only),
                'cookie_path': self.cookie_edit.text().strip(),
                'proxy': self.proxy_edit.text().strip(),
                'kodik_episode': self._kodik_episode_value(),
                'kodik_translation': (lambda t: "" if t in ("", "—") else t)(self.kodik_trans.currentText().strip()),
            }
            w = YtdlpWorker(config)
            self.active_workers[iid] = w
            w.finished.connect(lambda _=None, i=iid: self._remove_worker(i))
            self._connect_worker_signals(w, iid)
            w.start()
            self._update_stop_btn()
        except Exception as e:
            self.main.log(f"add_dl error: {e}")

    def _update_stop_btn(self):
        """Кнопка СТОП активна только когда есть хотя бы одна активная загрузка."""
        try: self.btn_stop.setEnabled(bool(self.active_workers))
        except Exception: pass

    def _update_dl_taskbar(self):
        """Сводный прогресс загрузок на иконке в панели задач: среднее по
        активным элементам. Если все в «неопределённом» режиме (—1) — бегущая
        полоса; если активных нет — снять индикатор."""
        try:
            vals = list(self._dl_pct.values())
            if not vals:
                self.main.clear_taskbar_progress(); return
            real = [v for v in vals if v is not None and v >= 0]
            if real:
                self.main.set_taskbar_progress(int(sum(real) / len(real)), 100)
            else:
                self.main.set_taskbar_progress(0, 100)  # 0 → неопределённый режим
        except Exception:
            pass

    def _remove_worker(self, iid):
        self.active_workers.pop(iid, None)
        self._update_stop_btn()

    def delete_sel(self):
        try:
            for it in list(self.tree.selectedItems()):
                iid = it.data(0, Qt.ItemDataRole.UserRole)
                if iid:
                    self.active_workers.pop(iid, None)
                    self.items.pop(iid, None)
                self.tree.invisibleRootItem().removeChild(it)
            self._update_stop_btn()
        except Exception: pass

    def set_thumb(self, iid, icon):
        try:
            entry = self.items.get(iid)
            if entry and isinstance(entry, dict):
                it = entry.get('item')
                if it and isinstance(it, QTreeWidgetItem):
                    it.setIcon(0, icon)
        except Exception: pass


class MediaTab(QWidget):
    thumb_sig = pyqtSignal(str, QIcon)
    def __init__(self, main_win):
        super().__init__()
        self.main = main_win
        self.items = []
        self._item_map: dict = {}
        self._item_data_map: dict = {}
        self.pool = QThreadPool()
        self.export_dir = ""  # пусто = экспортировать рядом с исходником
        self.setAcceptDrops(True)
        self.setup_ui()
        self.thumb_sig.connect(self.set_thumb)
        self.worker = None

    def _find_item(self, iid) -> 'QTreeWidgetItem | None':
        """Возвращает QTreeWidgetItem по iid за O(1)."""
        return self._item_map.get(iid)

    def setup_ui(self):
        l = QHBoxLayout(self)
        l.setContentsMargins(6, 6, 6, 6); l.setSpacing(8)
        lw = QWidget(); lv = QVBoxLayout(lw)
        lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(6)

        quick_dl_grp = QGroupBox("Быстрая загрузка")
        qdl_form = QFormLayout()
        qdl_h = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Вставьте ссылку для скачивания (файлы не добавляются в очередь обработки)...")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.url_edit.customContextMenuRequested.connect(self.on_url_ctx)

        btn_qdl_video = QPushButton("⬇  Скачать"); btn_qdl_video.clicked.connect(lambda: self.download_url(False))
        btn_qdl_audio = QPushButton("🎵  Скачать (Audio)"); btn_qdl_audio.clicked.connect(lambda: self.download_url(True))

        qdl_h.addWidget(self.url_edit); qdl_h.addWidget(btn_qdl_video); qdl_h.addWidget(btn_qdl_audio)
        qdl_form.addRow("URL:", qdl_h)
        quick_dl_grp.setLayout(qdl_form); lv.addWidget(quick_dl_grp)

        self.tree = DraggableTreeWidget()
        self.tree.setAcceptDrops(True)
        self.tree.setHeaderLabels(["Превью", "", "Размер", "Битрейт", "LUFS", "Статус"])
        self.tree.setRootIsDecorated(False)
        self.tree.setItemDelegate(StatusColorDelegate(self.tree))  # цветовая подсветка строк
        self.tree.setIconSize(QSize(160,90)); self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.ctx)
        self.tree.setWordWrap(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(0, 180)
        for i in range(1, 6): self.tree.header().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        h = QHBoxLayout()
        b1 = QPushButton("➕  Добавить файлы"); b1.clicked.connect(self.add)
        b2 = QPushButton("✖  Удалить"); b2.clicked.connect(self.rem)
        b3 = QPushButton("🗑  Очистить"); b3.clicked.connect(self.clear)
        self.btn_export_dir = QPushButton("📂")
        self.btn_export_dir.setFixedWidth(36)
        self.btn_export_dir.setToolTip("Выбрать папку экспорта. По умолчанию — рядом с исходным файлом.")
        self.btn_export_dir.clicked.connect(self._choose_export_dir)
        self.btn_export_reset = QPushButton("↺")
        self.btn_export_reset.setFixedWidth(36)
        self.btn_export_reset.setToolTip("Сбросить — экспортировать в папку исходника")
        self.btn_export_reset.clicked.connect(self._reset_export_dir)
        self.btn_export_reset.setEnabled(False)
        self.lbl_export_dir = QLabel("По умолчанию экспорт в папку исходника")
        self.lbl_export_dir.setStyleSheet("color:#a6adc8; font-size:11px;")
        h.addWidget(b1); h.addWidget(b2); h.addWidget(b3); h.addWidget(self.btn_export_dir); h.addWidget(self.btn_export_reset); h.addWidget(self.lbl_export_dir)
        h.addStretch()

        # Левая часть может ужиматься (растяжимая, маленький минимум),
        # чтобы правая панель всегда полностью помещалась по горизонтали.
        lw.setMinimumWidth(140)
        lv.addWidget(self.tree); lv.addLayout(h)
        l.addWidget(lw, 1)

        RIGHT_W = 460  # фиксированная ширина правой панели — всегда видна целиком
        right_container = QWidget(); right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0); right_layout.setSpacing(6)
        right_container.setFixedWidth(RIGHT_W)
        rw = QScrollArea(); rw.setWidgetResizable(True)
        rw.setFrameShape(QFrame.Shape.NoFrame)
        # Горизонтальная скрыта (панель фикс. ширины), вертикальная — по необходимости
        rw.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rw.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        w = QWidget(); rv_inner = QVBoxLayout(w)
        rv_inner.setContentsMargins(6, 4, 6, 4); rv_inner.setSpacing(8)

        ga = QGroupBox("Аудио эффекты"); fa = QFormLayout()
        self.ck_norm = QCheckBox("Loudnorm"); self.ck_norm.setChecked(True)
        self.s_tgt = QDoubleSpinBox(); self.s_tgt.setValue(-20.0); self.s_tgt.setRange(-60.0, 20.0); self.s_tgt.setSingleStep(0.1)
        self.s_lra = QDoubleSpinBox(); self.s_lra.setValue(20.0); self.s_lra.setRange(0.0, 50.0); self.s_lra.setSingleStep(0.1)
        self.s_tp = QDoubleSpinBox(); self.s_tp.setValue(-1.5); self.s_tp.setRange(-60.0, 10.0); self.s_tp.setSingleStep(0.1)
        self.ck_fade = QCheckBox("Затухание (Fade Out)"); self.ck_fade.setChecked(True)
        self.s_fade = QDoubleSpinBox(); self.s_fade.setValue(1.0); self.s_fade.setRange(0.0, 60.0); self.s_fade.setSingleStep(0.1)
        self.s_fade.setMaximumWidth(110)
        self.ck_fade_in = QCheckBox("Нарастание (Fade In)"); self.ck_fade_in.setChecked(False)
        self.s_fade_in = QDoubleSpinBox(); self.s_fade_in.setValue(1.0); self.s_fade_in.setRange(0.0, 60.0); self.s_fade_in.setSingleStep(0.1)
        self.s_fade_in.setMaximumWidth(110)
        self.ck_deg = QCheckBox("Ухудшить звук (Degrade)")
        self.s_hz = QSpinBox(); self.s_hz.setValue(8000); self.s_hz.setRange(1000, 48000)
        self.ck_u8 = QCheckBox("8-bit")
        self.s_lp = QSpinBox(); self.s_lp.setRange(0, 24000); self.s_lp.setValue(3000)
        self.s_hp = QSpinBox(); self.s_hp.setRange(0, 24000); self.s_hp.setValue(200)
        self.s_deg_gain = QDoubleSpinBox(); self.s_deg_gain.setRange(-60, 0); self.s_deg_gain.setValue(0.0)
        for _sb in (self.s_tgt, self.s_lra, self.s_tp):
            _sb.setMaximumWidth(70)
        fa.addRow(row_with_info(self.ck_norm, "Нормализация уровня громкости, рекомендуется все видео/аудио кодировать с этой опцией"))
        hn = QHBoxLayout()
        hn.addWidget(QLabel("LUFS:")); hn.addWidget(self.s_tgt)
        hn.addWidget(QLabel("LRA:")); hn.addWidget(self.s_lra)
        hn.addWidget(QLabel("TP:")); hn.addWidget(self.s_tp)
        hn.addStretch()
        fa.addRow(hn)
        fa.addRow(row_with_info(self.ck_fade_in, "Плавное нарастание звука в начале ролика (секунды)"), self.s_fade_in)
        fa.addRow(row_with_info(self.ck_fade, "Плавное затухание звука в конце ролика в секундах"), self.s_fade)

        # Битрейт аудио — ПЕРЕД секцией degrade
        hbr = QHBoxLayout(); hbr.addWidget(QLabel("Битрейт аудио:"))
        self.c_abitrate = InvertedWheelComboBox(); self.c_abitrate.addItems(AUDIO_BITRATES); self.c_abitrate.setCurrentText("128")
        hbr.addWidget(self.c_abitrate)
        hbr.addWidget(info_badge("128 кбит - стандартное качество аудио в Youtube"))
        hbr.addStretch()
        fa.addRow(hbr)

        fa.addRow(row_with_info(self.ck_deg, "Намеренное ухудшение звука (эффект «телефон/радио»). Открывает дополнительные параметры ниже."))

        # Degrade-виджеты: скрываются/показываются по галочке
        for _sb in (self.s_hz, self.s_lp, self.s_hp):
            _sb.setMaximumWidth(95)
        self._lbl_samplebit = QLabel("Sample/Bit:")
        hd = QHBoxLayout(); hd.addWidget(QLabel("Hz:")); hd.addWidget(self.s_hz)
        hd.addWidget(info_badge("Частота дискретизации (Гц). Ниже = грубее звук. 8000 Гц ≈ телефонное качество."))
        hd.addWidget(self.ck_u8)
        hd.addWidget(info_badge("8-битный звук (u8) — сильное огрубление, шумный ретро-эффект."))
        hd.addStretch()
        fa.addRow(self._lbl_samplebit, hd)

        # Lowpass и Highpass — отдельными строками, чтобы умещались на узких экранах
        hlp = QHBoxLayout(); hlp.addWidget(QLabel("Lowpass:")); hlp.addWidget(self.s_lp)
        hlp.addWidget(info_badge("Срезает частоты ВЫШЕ указанной (Гц) — убирает «верха», звук становится глуше."))
        hlp.addStretch()
        self._lbl_lowpass = QLabel("")
        fa.addRow(self._lbl_lowpass, hlp)

        hhp = QHBoxLayout(); hhp.addWidget(QLabel("Highpass:")); hhp.addWidget(self.s_hp)
        hhp.addWidget(info_badge("Срезает частоты НИЖЕ указанной (Гц) — убирает «низы»/гул."))
        hhp.addStretch()
        self._lbl_highpass = QLabel("")
        fa.addRow(self._lbl_highpass, hhp)

        self._lbl_degvol = QLabel("Degrade vol (dB):")
        hdv = QHBoxLayout(); hdv.addWidget(self.s_deg_gain)
        self._badge_degvol = info_badge("Громкость degrade-звука в дБ. 0 = без изменений, отрицательное значение = тише.")
        hdv.addWidget(self._badge_degvol); hdv.addStretch()
        fa.addRow(self._lbl_degvol, hdv)

        self._deg_group = [self._lbl_samplebit, self.s_hz, self.ck_u8,
                           self._lbl_lowpass, self.s_lp,
                           self._lbl_highpass, self.s_hp,
                           self._lbl_degvol, self.s_deg_gain, self._badge_degvol]

        def _update_deg_vis(checked):
            for w in self._deg_group:
                w.setVisible(checked)
            # Скрываем layout-строки полностью через содержимое
            for layout_item in [hd, hlp, hhp]:
                for i in range(layout_item.count()):
                    wi = layout_item.itemAt(i).widget()
                    if wi: wi.setVisible(checked)
        self.ck_deg.toggled.connect(_update_deg_vis)
        _update_deg_vis(self.ck_deg.isChecked())

        ga.setLayout(fa); rv_inner.addWidget(ga)

        # --- Скорость: отдельный блок между аудио и видео (без названия группы) ---
        self.s_spd = SpeedSpinBox(); self.s_spd.setValue(100); self.s_spd.setSuffix("%")
        self.s_spd.setMaximumWidth(110)
        speed_w = QWidget(); speed_h = QHBoxLayout(speed_w)
        speed_h.setContentsMargins(8, 2, 8, 2); speed_h.setSpacing(6)
        speed_h.addWidget(QLabel("Скорость:"))
        speed_h.addWidget(self.s_spd)
        speed_h.addWidget(info_badge("Изменение скорости видео и звука. 100% = без изменений"))
        speed_h.addStretch()
        rv_inner.addWidget(speed_w)

        gv = QGroupBox("Перекодирование видео"); fv = QFormLayout()
        self.chk_enable_video = QCheckBox("Включить перекодирование"); self.chk_enable_video.setChecked(True)

        # --- Переключатель профиля: две кнопки-тогглы ---
        self.btn_mode_std  = QPushButton("Стандарт");       self.btn_mode_std.setCheckable(True);  self.btn_mode_std.setChecked(True)
        self.btn_mode_dark = QPushButton("🌑 Тёмные сцены"); self.btn_mode_dark.setCheckable(True); self.btn_mode_dark.setChecked(False)
        self.btn_mode_std.setToolTip("yuv420p, 1-pass")
        self.btn_mode_dark.setToolTip("10-бит (yuv420p10le), tune=ssim, 2-pass AV1\nCRF, preset и разрешение — без изменений")
        self.btn_mode_std.clicked.connect(lambda: self._set_preset_mode("std"))
        self.btn_mode_dark.clicked.connect(lambda: self._set_preset_mode("dark"))
        mode_h = QHBoxLayout(); mode_h.addWidget(self.btn_mode_std); mode_h.addWidget(self.btn_mode_dark)

        self.s_crf = QSpinBox(); self.s_crf.setRange(0, 63); self.s_crf.setValue(35)
        self.s_pre = QSpinBox(); self.s_pre.setRange(0, 13); self.s_pre.setValue(8)
        self.c_res = QComboBox(); self.c_res.addItems(["Исходное", "1920x1080", "1280x720" + DEFAULT_TAG, "854x480", "144x72"])
        self.c_res.setCurrentText("1280x720" + DEFAULT_TAG)
        self.c_res.setMinimumWidth(210); self.c_res.setMaximumWidth(240)
        self.c_res.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.c_fps = InvertedWheelComboBox(); self.c_fps.addItems(["Исходный", "Исходный (max 30)", "5", "12", "23.976", "24", "30", "60"])
        self.c_fps.setEditable(True)   # можно вводить своё число FPS, а пресеты — из выпадашки
        self.c_fps.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        try: self.c_fps.lineEdit().setPlaceholderText("напр. 48")
        except Exception: pass
        self.c_fps.setMinimumWidth(150); self.c_fps.setMaximumWidth(200)
        fv.addRow(row_with_info(self.chk_enable_video, "Если выключено — видео не трогается, меняется только звук. Включено — перекодирование в AV1 (SVT-AV1)."))
        fv.addRow(label_with_info("Профиль:", "Стандарт: Использовать по умолчанию. Тёмные сцены: Только в темных сценах."), mode_h)
        henc = QHBoxLayout(); henc.addWidget(self.s_crf); henc.addWidget(self.s_pre)
        self._badge_crf = info_badge("Preset — скорость кодирования (0 медленно и качественно … 13 быстро, но страдает качество (Рекомендуется 1, если позволяет процессор)).")
        henc.addWidget(self._badge_crf)
        henc.addStretch()
        fv.addRow(label_with_info("CRF / Preset:", "CRF — качество (меньше = качественнее, но больше файл. Рекомендуется 40-45. Может принимать значения от 0 до 63)"), henc)
        fv.addRow(label_with_info("Разрешение:", "Масштаб выходного видео. «Исходное» — без изменений. Уменьшение сохраняет пропорции (без растяжения)."), self.c_res)
        fv.addRow(label_with_info("FPS:", "Частота кадров на выходе. «Исходный (max 30)» — снижает только если выше 30."), self.c_fps)

        # Видео fade in / fade out (через чёрный экран)
        self.ck_vfade_in = QCheckBox("Fade In (из чёрного)"); self.ck_vfade_in.setChecked(False)
        self.s_vfade_in = QDoubleSpinBox(); self.s_vfade_in.setValue(1.0); self.s_vfade_in.setRange(0.0, 60.0); self.s_vfade_in.setSingleStep(0.1)
        self.s_vfade_in.setMaximumWidth(110)
        self.ck_vfade_out = QCheckBox("Fade Out (в чёрный)"); self.ck_vfade_out.setChecked(False)
        self.s_vfade_out = QDoubleSpinBox(); self.s_vfade_out.setValue(1.0); self.s_vfade_out.setRange(0.0, 60.0); self.s_vfade_out.setSingleStep(0.1)
        self.s_vfade_out.setMaximumWidth(110)
        fv.addRow(row_with_info(self.ck_vfade_in, "Плавное появление картинки из чёрного экрана в начале (секунды)"), self.s_vfade_in)
        fv.addRow(row_with_info(self.ck_vfade_out, "Плавный уход картинки в чёрный экран в конце (секунды)"), self.s_vfade_out)

        gv.setLayout(fv); rv_inner.addWidget(gv)
        # Скрываем строки видео если перекодирование выключено
        self._video_enc_rows = [self.btn_mode_std, self.btn_mode_dark,
                                 self.s_crf, self.s_pre, self.c_res, self.c_fps,
                                 self._badge_crf,
                                 self.s_vfade_in, self.s_vfade_out]
        def _update_video_enc(checked):
            for w in self._video_enc_rows:
                w.setVisible(checked)
            # Скрываем лейблы через FormLayout
            for row_idx in range(fv.rowCount()):
                lbl = fv.itemAt(row_idx, QFormLayout.ItemRole.LabelRole)
                fld = fv.itemAt(row_idx, QFormLayout.ItemRole.FieldRole)
                if fld:
                    wgt = fld.widget()
                    if wgt is None and fld.layout():
                        # layout-строка: проверяем первый виджет
                        wgt = fld.layout().itemAt(0).widget() if fld.layout().count() else None
                    if wgt in self._video_enc_rows or (
                        fld.layout() and any(
                            fld.layout().itemAt(i).widget() in self._video_enc_rows
                            for i in range(fld.layout().count())
                            if fld.layout().itemAt(i).widget()
                        )
                    ):
                        if lbl and lbl.widget(): lbl.widget().setVisible(checked)
        self.chk_enable_video.toggled.connect(_update_video_enc)
        _update_video_enc(self.chk_enable_video.isChecked())

        gavi = QGroupBox("Изображения"); favi = QFormLayout()
        # Выбор выходного формата
        self.c_img_fmt = InvertedWheelComboBox()
        self.c_img_fmt.addItems(["avif" + DEFAULT_TAG, "webp", "png", "jpg", "ico"])
        self.c_img_fmt.setCurrentText("avif" + DEFAULT_TAG)
        self.c_img_fmt.setMinimumWidth(190); self.c_img_fmt.setMaximumWidth(220)
        self.c_img_fmt.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        favi.addRow(label_with_info("Формат:", "Выходной формат изображений. avif — лучшее сжатие, webp — запасной вариант + используется для картинок с прозрачностью"), self.c_img_fmt)

        # ── Лимит размера файла ──────────────────────────────────────────────
        hlim = QHBoxLayout()
        self.ck_lim = QCheckBox("Сжать до")
        self.ck_lim.setChecked(True)
        self.s_lim = QSpinBox()
        self.s_lim.setRange(0, 50000); self.s_lim.setSuffix(" КБ")
        self.s_lim.setSingleStep(50); self.s_lim.setValue(100)
        hlim.addWidget(self.ck_lim); hlim.addWidget(self.s_lim)
        hlim.addWidget(info_badge("Подбирает качество так, чтобы файл не превышал указанный размер (КБ). 100 для AVIF - достаточное для SiGame"))
        hlim.addStretch()
        # Привязка: спинбокс активен только если галочка включена
        self.ck_lim.toggled.connect(self.s_lim.setEnabled)
        favi.addRow(hlim)

        # ── Проходы подбора под лимит размера ────────────────────────────────
        hpass = QHBoxLayout()
        self.s_passes = QSpinBox()
        self.s_passes.setRange(1, 8); self.s_passes.setValue(4)
        hpass.addWidget(QLabel("Проходы подбора:")); hpass.addWidget(self.s_passes)
        hpass.addWidget(info_badge("Сколько проб качества делать при подборе под лимит размера (бинарный поиск). Больше — точнее под лимит, но дольше. Работает для avif / webp / jpg. По умолчанию 4, максимум 8."))
        hpass.addStretch()
        self.ck_lim.toggled.connect(self.s_passes.setEnabled)
        self.s_passes.setEnabled(self.ck_lim.isChecked())
        favi.addRow(hpass)

        # ── Лимит разрешения ─────────────────────────────────────────────────
        hdim = QHBoxLayout()
        self.ck_dim = QCheckBox("Снизить до")
        self.ck_dim.setChecked(False)
        self.s_dim = QSpinBox()
        self.s_dim.setRange(16, 8000); self.s_dim.setSuffix(" px")
        self.s_dim.setValue(1280); self.s_dim.setEnabled(False)
        hdim.addWidget(self.ck_dim); hdim.addWidget(self.s_dim)
        hdim.addWidget(QLabel("(макс. сторона)"))
        hdim.addWidget(info_badge("Ограничивает максимальную сторону изображения (px) с сохранением пропорций."))
        hdim.addStretch()
        self.ck_dim.toggled.connect(self.s_dim.setEnabled)
        favi.addRow(hdim)

        self.sl_aspd = QSlider(Qt.Orientation.Horizontal); self.sl_aspd.setRange(0, 8); self.sl_aspd.setValue(0)
        self.ck_arec = QCheckBox("Перезаписывать"); self.ck_arec.setChecked(True)
        favi.addRow(label_with_info("Скорость:", "левее — медленнее и компактнее файл, правее — быстрее, но больше"), self.sl_aspd)
        favi.addRow(row_with_info(self.ck_arec, "(Перекодируешь 2-ой раз одно и то же изображение? Включи эту опцию, чтобы перезаписать старый файл(не исходный) вместо создания ещё 1 копии)"))
        gavi.setLayout(favi); rv_inner.addWidget(gavi)

        rv_inner.addStretch(); w.setLayout(rv_inner); rw.setWidget(w); right_layout.addWidget(rw)

        # ── Низ правой панели: приоритет процесса + счётчик задействованных потоков ──
        foot = QWidget(); foot_l = QHBoxLayout(foot); foot_l.setContentsMargins(6, 0, 6, 2)
        foot_l.addWidget(QLabel("Приоритет:"))
        self.c_priority = InvertedWheelComboBox()
        self.c_priority.addItems(["Низкий", "Обычный", "Высокий"])
        self.c_priority.setCurrentText("Обычный")
        self.c_priority.setMaximumWidth(120)
        foot_l.addWidget(self.c_priority)
        foot_l.addWidget(info_badge("Приоритет процессов кодирования (ffmpeg) в системе. Высокий — кодирует быстрее; на Низком ПК отзывчивее. Виден в Диспетчере задач у ffmpeg.exe."))
        foot_l.addStretch()
        # Всего логических потоков ЦП на этой машине — показываем сразу (0/N),
        # а не 0/0, чтобы было видно потенциал ещё до запуска обработки.
        self._cpu_threads = max(1, os.cpu_count() or 1)
        self.lbl_threads = QLabel(f"Потоки ЦП в работе: 0/{self._cpu_threads}")
        self.lbl_threads.setToolTip(
            "Занятые логические потоки ЦП. Видео/аудио кодируются по одному файлу, "
            "но SVT-AV1 нагружает все ядра — поэтому показывается полное число потоков. "
            "Изображения обрабатываются параллельно (по числу ядер).")
        foot_l.addWidget(self.lbl_threads)
        right_layout.addWidget(foot)

        btn_box = QWidget(); btn_layout = QHBoxLayout(btn_box)
        btn_layout.setContentsMargins(0, 6, 0, 6)
        self.b_run = QPushButton("▶  НАЧАТЬ"); self.b_run.setObjectName("b_run")
        self.b_stop = QPushButton("■  СТОП"); self.b_stop.setObjectName("b_stop"); self.b_stop.setEnabled(False)
        self.b_run.clicked.connect(self.run); self.b_stop.clicked.connect(self.stop)
        btn_layout.addWidget(self.b_run); btn_layout.addWidget(self.b_stop)

        right_layout.addWidget(btn_box); right_container.setLayout(right_layout); l.addWidget(right_container, 0)

        self.shortcut_paste = QShortcut(QKeySequence("Ctrl+V"), self.tree)
        self.shortcut_paste.activated.connect(self.paste_files)
        # Клавиша Delete — удалить выделенные файлы из очереди
        self.shortcut_delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree)
        self.shortcut_delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.shortcut_delete.activated.connect(self.rem)
        self.tree.itemDoubleClicked.connect(self.on_double_click)

    def _set_preset_mode(self, mode):
        """Переключает профиль кодирования без изменения preset и битрейта аудио."""
        is_dark = (mode == "dark")
        self.btn_mode_std.blockSignals(True);  self.btn_mode_dark.blockSignals(True)
        self.btn_mode_std.setChecked(not is_dark); self.btn_mode_dark.setChecked(is_dark)
        self.btn_mode_std.blockSignals(False); self.btn_mode_dark.blockSignals(False)
        try: self.main._save_settings_now()
        except Exception: pass

    def on_url_ctx(self, pos):
        m = QMenu()
        try: cb = QApplication.clipboard().text().strip()
        except Exception: cb = ""
        if cb and cb.startswith("http"):
            a = QAction("Скачать из буфера", self)
            a.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.download_url(False)))
            a2 = QAction("Скачать аудио из буфера", self)
            a2.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.download_url(True)))
            m.addAction(a); m.addAction(a2); m.addSeparator()
        m.addAction(QAction("Вставить", self, triggered=self.url_edit.paste))
        m.exec(self.url_edit.mapToGlobal(pos))

    def on_double_click(self, item, column):
        """Двойной клик по обработанному файлу — открывает результат в плеере."""
        try:
            iid = item.data(0, Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if entry and entry.get('is_done'):
                out_path = entry.get('out_path')
                if out_path and os.path.exists(out_path):
                    self.open_output_file(out_path)
                else:
                    self.open_file_location(item)
        except Exception: pass

    def open_output_file(self, path):
        """Открывает файл в ассоциированном приложении (плеер, просмотрщик)."""
        try:
            if IS_WIN:
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            self.main.log(f"Не удалось открыть файл: {e}")

    def _choose_export_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка экспорта", self.export_dir or default_download_dir())
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
            if self.export_dir and os.path.isdir(self.export_dir):
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
            if not dl_path or not os.path.exists(dl_path): dl_path = default_download_dir()
        except Exception: dl_path = default_download_dir()

        self.main.tab_ytdlp.add_dl_direct(url, audio_only=audio_only, outdir=dl_path)

    def reset_status(self):
        for i in self.tree.selectedItems():
            iid = i.data(0, Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if entry:
                entry['is_done'] = False
            i.setText(5, "Ожидание")
            # Сброс «новых» данных — оставляем только исходные (верхняя строка «было»)
            self._set_pair(i, 2, bottom="—")   # Размер: стало
            self._set_pair(i, 3, bottom="—")   # Битрейт: итог
            self._set_pair(i, 4, bottom="—")   # LUFS: после
            i.setData(0, ITEM_STATUS_ROLE, None)
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

    def ctx(self, pos):
        m = QMenu()
        sel = self.tree.itemAt(pos)
        if sel:
            iid = sel.data(0, Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid, {})
            out_path = entry.get('out_path', '')
            if out_path and os.path.exists(out_path):
                m.addAction("▶  Открыть файл", lambda checked=False, p=out_path: self.open_output_file(p))
            m.addAction("📁  Перейти к файлу", lambda checked=False, it=sel: self.open_file_location(it))
            m.addAction("↺  Сбросить статус", lambda checked=False: self.reset_status())
            m.addSeparator()
            m.addAction("✕  Удалить", lambda checked=False: self.rem())
        m.addAction("📋  Вставить файлы", lambda checked=False: self.paste_files())
        m.addAction("🗑  Очистить всё", lambda checked=False: self.clear())
        m.exec(self.tree.mapToGlobal(pos))

    def open_file_location(self, item):
        try:
            path = item.toolTip(0) or item.data(0, Qt.ItemDataRole.ToolTipRole)
            if not path: return
            path = os.path.abspath(path)
            if IS_WIN: subprocess.Popen(['explorer', '/select,', path])
            elif sys.platform == 'darwin': subprocess.Popen(['open', '-R', path])
            else: subprocess.Popen(['xdg-open', os.path.dirname(path)])
        except Exception as e:
            self.main.log(f"open_file_location error: {e}")

    def paste_files(self):
        try:
            mime = QApplication.clipboard().mimeData()
            if mime.hasUrls():
                self.add_paths([u.toLocalFile() for u in mime.urls() if u.toLocalFile()])
        except Exception as e:
            self.main.log(f"paste_files error: {e}")

    def add(self):
        p, _ = QFileDialog.getOpenFileNames(self, "Файлы")
        if p: self.add_paths(p)

    def add_paths(self, paths):
        for p in paths:
            try:
                if not os.path.exists(p): continue

                # Не добавляем файлы, которые сами являются результатом обработки
                stem = Path(p).stem
                if stem.endswith("_Сжатый") or stem.endswith("_Compressed"):
                    continue

                ext = Path(p).suffix.lower()
                if ext in ALLOWED_MEDIA: ft = "MEDIA"
                elif ext in ALLOWED_IMG: ft = "IMG"
                else: continue

                iid = uuid.uuid4().hex
                # Только быстрый getsize — ffprobe уйдёт в фоновый поток
                try: size = os.path.getsize(p)
                except Exception: size = 0

                item_data = {'iid': iid, 'path': p, 'type': ft, 'dur': 0, 'is_done': False}
                self.items.append(item_data)
                self._item_data_map[iid] = item_data

                it = QTreeWidgetItem(self.tree)
                it.setToolTip(0, f"{os.path.basename(p)}\n{p}")
                it.setText(1, "было\nстало")              # метка двух строк
                it.setText(2, f"{human_size(size)}\n—")   # Размер: было(исх) / стало(нов)
                it.setText(3, "—\n—")                     # Битрейт: исх / итог
                it.setText(4, "—\n—")                     # LUFS: до / после
                it.setText(5, "Ожидание")                 # Статус
                it.setData(0, Qt.ItemDataRole.UserRole, iid)
                self._item_map[iid] = it
                self.tree.scrollToItem(it)
                self.pool.start(LocalThumbnailRunnable(p, iid, self.thumb_sig))

                if ft == "MEDIA":
                    def _bg(path_local, iid_local):
                        # ffprobe + loudness — всё в фоне, UI не блокируем
                        try:
                            dur_r, br_r, size_r, a_br_r = get_media_info(path_local)
                            def _apply_info():
                                d = self._item_data_map.get(iid_local)
                                if d: d['dur'] = dur_r
                                item = self._find_item(iid_local)
                                if item:
                                    self._set_pair(item, 2, top=human_size(size_r))
                                    self._set_pair(item, 3, top=(a_br_r or br_r or "—"))
                            QTimer.singleShot(0, _apply_info)
                        except Exception: pass
                        try:
                            val = measure_loudness(path_local)
                        except Exception: val = None
                        QTimer.singleShot(0, lambda: self.update_lufs_columns(iid_local, val, None))
                    threading.Thread(target=_bg, args=(p, iid), daemon=True).start()

            except Exception as e:
                self.main.log(f"add_paths error: {e}")

    def set_thumb(self, iid, icon):
        try:
            item = self._find_item(iid)
            if item:
                item.setIcon(0, icon)
        except Exception: pass

    @staticmethod
    def _set_pair(item, col, top=None, bottom=None):
        """Двустрочная ячейка: верх = исходное, низ = новое. Меняет только
        переданную часть (top/bottom), сохраняя вторую."""
        cur = (item.text(col) or "").split("\n")
        t = cur[0] if cur and cur[0] else "—"
        b = cur[1] if len(cur) > 1 and cur[1] else "—"
        if top is not None: t = top
        if bottom is not None: b = bottom
        item.setText(col, f"{t}\n{b}")

    def update_item_info(self, iid, size_new, bitrate_result):
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 2, bottom=size_new)          # Размер: стало
                self._set_pair(item, 3, bottom=bitrate_result)    # Битрейт: итог
                item.setData(0, ITEM_STATUS_ROLE, 'done')
                self.tree.viewport().update()
        except Exception: pass

    def update_lufs_columns(self, iid, before, after):
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 4, top=("—" if before is None else f"{before:.2f}"))
                self._set_pair(item, 4, bottom=("—" if after is None else f"{after:.2f}"))
        except Exception: pass

    def rem(self):
        try:
            for i in self.tree.selectedItems():
                iid = i.data(0, Qt.ItemDataRole.UserRole)
                self.items = [x for x in self.items if x['iid'] != iid]
                self._item_map.pop(iid, None)
                self._item_data_map.pop(iid, None)
                self.tree.invisibleRootItem().removeChild(i)
        except Exception: pass

    def clear(self):
        try:
            self.items.clear()
            self._item_map.clear()
            self._item_data_map.clear()
            self.tree.clear()
        except Exception: pass

    def run(self):
        if not self.items: return
        try: ab = self.c_abitrate.currentText() or "128"
        except Exception: ab = "128"
        try: spd = self.s_spd.value()
        except Exception: spd = 100
        s = {
            'audio': {
                'norm': bool(self.ck_norm.isChecked()),
                'tgt': float(self.s_tgt.value()), 'lra': float(self.s_lra.value()), 'tp': float(self.s_tp.value()),
                'fade': bool(self.ck_fade.isChecked()), 'fade_d': float(self.s_fade.value()),
                'fade_in': bool(self.ck_fade_in.isChecked()), 'fade_in_d': float(self.s_fade_in.value()),
                'deg': bool(self.ck_deg.isChecked()), 'hz': int(self.s_hz.value()), 'u8': bool(self.ck_u8.isChecked()),
                'lp': int(self.s_lp.value()), 'hp': int(self.s_hp.value()), 'deg_gain_db': float(self.s_deg_gain.value()),
                'bitrate': ab
            },
            'video': {
                'enabled': bool(self.chk_enable_video.isChecked()), 'speed': int(spd), 'crf': int(self.s_crf.value()),
                'pre': int(self.s_pre.value()), 'res': strip_default_tag(self.c_res.currentText()), 'fps': self.c_fps.currentText().strip().replace(',', '.'),
                'preset_mode': 'dark' if self.btn_mode_dark.isChecked() else 'std',
                'vfade_in': bool(self.ck_vfade_in.isChecked()), 'vfade_in_d': float(self.s_vfade_in.value()),
                'vfade_out': bool(self.ck_vfade_out.isChecked()), 'vfade_out_d': float(self.s_vfade_out.value())
            },
            'avif': {
                'limit': int(self.s_lim.value()) if self.ck_lim.isChecked() else 0,
                'adim': int(self.s_dim.value()) if self.ck_dim.isChecked() else 0,
                'aspd': int(self.sl_aspd.value()), 'arec': bool(self.ck_arec.isChecked()),
                'fit_passes': int(self.s_passes.value()) if hasattr(self, 's_passes') else 4,
                'img_fmt': strip_default_tag(self.c_img_fmt.currentText()) if hasattr(self, 'c_img_fmt') else 'avif'
            },
            'export_dir': self.export_dir or '',
            'priority': {'Низкий': 'low', 'Обычный': 'normal', 'Высокий': 'high'}.get(
                self.c_priority.currentText(), 'normal') if hasattr(self, 'c_priority') else 'normal'
        }
        self.worker = ProcessWorker(self.items, s)
        self.worker.status.connect(self.on_stat); self.worker.progress.connect(self.on_prog)
        self.worker.log.connect(self.main.log); self.worker.finished_all.connect(self.done)
        self.worker.global_progress.connect(self.main.update_global_progress)
        self.worker.update_item_sig.connect(self.update_item_info); self.worker.update_lufs_sig.connect(self.update_lufs_columns)
        self.worker.active_threads.connect(self._on_active_threads)

        try:
            for itdata in self.items:
                if itdata.get('is_done'): continue
                iid = itdata.get('iid')
                item = self._find_item(iid)
                if item:
                    item.setData(0, ITEM_STATUS_ROLE, 'proc')
            self.tree.viewport().update()
        except Exception: pass

        self.b_run.setEnabled(False); self.b_stop.setEnabled(True)
        self.worker.start()

    def stop(self):
        if self.worker:
            try: self.worker.stop()
            except Exception: pass

    def on_stat(self, iid, txt, code):
        try:
            i = self._find_item(iid)
            if i:
                i.setData(0, ITEM_STATUS_ROLE, code)
                i.setText(5, txt)
                self.tree.viewport().update()
        except Exception: pass

    def on_prog(self, iid, val):
        try:
            i = self._find_item(iid)
            if i:
                i.setText(5, "Готово" if val >= 100 else f"{val}%")
        except Exception: pass

    def _on_active_threads(self, n, m):
        try:
            # В простое показываем 0 из всех потоков ЦП машины (а не 0/0).
            total = m if m > 0 else self._cpu_threads
            self.lbl_threads.setText(f"Потоки ЦП в работе: {n}/{total}")
        except Exception: pass

    def done(self):
        self.b_run.setEnabled(True); self.b_stop.setEnabled(False)
        try: self.lbl_threads.setText(f"Потоки ЦП в работе: 0/{self._cpu_threads}")
        except Exception: pass
        self.main.log("Готово")
        try: play_done_sound()
        except Exception: pass

    def restart_gui(self):
        try:
            python = sys.executable; script = os.path.abspath(sys.argv[0])
            subprocess.Popen([python, script], cwd=os.getcwd())
        except Exception as e:
            self.main.log(f"Не удалось запустить новый процесс: {e}")
            return
        try:
            self.main.close()
            QTimer.singleShot(200, QApplication.quit)
        except Exception:
            try:
                QApplication.quit()
            except Exception:
                os._exit(0)


class Base64Tab(QWidget):
    """Вкладка кодирования любого файла в Base64."""
    _sig_done     = pyqtSignal(str, str, str)   # b64, size_str, txt_path
    _sig_error    = pyqtSignal(str)
    _sig_progress = pyqtSignal(int)             # 0-100, только из фонового потока

    # Расширения и их иконки
    _ICON_MAP = {
        # Видео
        '.mp4': '🎬', '.mkv': '🎬', '.avi': '🎬', '.mov': '🎬', '.webm': '🎬',
        '.flv': '🎬', '.wmv': '🎬', '.m4v': '🎬', '.ts': '🎬', '.mts': '🎬',
        '.m2ts': '🎬', '.vob': '🎬', '.ogv': '🎬', '.3gp': '🎬', '.3g2': '🎬',
        '.divx': '🎬', '.f4v': '🎬', '.mxf': '🎬', '.rm': '🎬', '.rmvb': '🎬',
        # Аудио
        '.mp3': '🎵', '.opus': '🎵', '.wav': '🎵', '.flac': '🎵', '.ogg': '🎵',
        '.aac': '🎵', '.m4a': '🎵', '.wma': '🎵', '.aiff': '🎵', '.aif': '🎵',
        '.ape': '🎵', '.mka': '🎵', '.mid': '🎵', '.midi': '🎵', '.amr': '🎵',
        '.ac3': '🎵', '.dts': '🎵', '.ra': '🎵', '.au': '🎵',
        # 3D / Игровые ассеты
        '.glb': '🧊', '.gltf': '🧊', '.obj': '🧊', '.fbx': '🧊', '.dae': '🧊',
        '.3ds': '🧊', '.stl': '🧊', '.ply': '🧊', '.blend': '🧊', '.usdz': '🧊',
        '.usd': '🧊', '.abc': '🧊', '.x3d': '🧊', '.vrml': '🧊', '.wrl': '🧊',
        # Изображения (будут показываться как превью)
        '.jpg': None, '.jpeg': None, '.png': None, '.gif': None, '.webp': None,
        '.bmp': None, '.tiff': None, '.tif': None, '.avif': None, '.heic': None,
        '.heif': None, '.ico': None, '.svg': '🖼',
        # Документы
        '.pdf': '📄', '.doc': '📄', '.docx': '📄', '.xls': '📄', '.xlsx': '📄',
        '.ppt': '📄', '.pptx': '📄', '.txt': '📄', '.rtf': '📄', '.odt': '📄',
        '.ods': '📄', '.odp': '📄', '.csv': '📄', '.md': '📄',
        # Архивы
        '.zip': '🗜', '.rar': '🗜', '.7z': '🗜', '.tar': '🗜', '.gz': '🗜',
        '.bz2': '🗜', '.xz': '🗜', '.zst': '🗜', '.lz4': '🗜',
        # Шрифты
        '.ttf': '🔤', '.otf': '🔤', '.woff': '🔤', '.woff2': '🔤', '.eot': '🔤',
        # Код / данные
        '.json': '💾', '.xml': '💾', '.yaml': '💾', '.yml': '💾', '.toml': '💾',
        '.bin': '💾', '.dat': '💾', '.db': '💾', '.sqlite': '💾', '.proto': '💾',
        # Игровые / движковые форматы
        '.pak': '🎮', '.vpk': '🎮', '.bsp': '🎮', '.mdl': '🎮', '.vtf': '🎮',
        '.vmt': '🎮', '.prefab': '🎮', '.asset': '🎮', '.unity': '🎮',
        # Прочее
        '.iso': '💿', '.img': '💿', '.dmg': '💿',
    }

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._stop_flag = threading.Event()
        self._sig_done.connect(self._on_done)
        self._sig_error.connect(self._on_error)
        self._sig_progress.connect(self.progress_update)
        self._current_path = ""
        self._build_ui()

    def progress_update(self, pct: int):
        self.progress.setValue(pct)

    def add_paths(self, paths):
        """Совместимость с RecentFileThumb — устанавливает первый файл."""
        if paths:
            self._set_path(paths[0])

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Верхний блок: миниатюра + кнопки ────────────────────────────────
        top = QHBoxLayout()

        # Миниатюра — принимает дроп
        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(120, 90)
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thumb.setStyleSheet(
            "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; color:#6c7086; font-size:11px;")
        self.lbl_thumb.setText("нет\nфайла")
        top.addWidget(self.lbl_thumb)

        top.addSpacing(12)

        # Правая колонка: имя файла + кнопки
        right = QVBoxLayout()
        self.lbl_fname = QLabel("Файл не выбран")
        self.lbl_fname.setStyleSheet("color:#cdd6f4; font-size:12px;")
        self.lbl_fname.setWordWrap(True)
        right.addWidget(self.lbl_fname)

        self.lbl_hint = QLabel("💡 Перетащите файл из любой вкладки или с рабочего стола")
        self.lbl_hint.setStyleSheet("color:#6c7086; font-size:10px;")
        right.addWidget(self.lbl_hint)
        right.addStretch()

        btn_row = QHBoxLayout()
        btn_browse = QPushButton("📂  Выбрать файл")
        btn_browse.clicked.connect(self._browse)

        self.btn_encode = QPushButton("⚙  Кодировать")
        self.btn_encode.setFixedHeight(32)
        self.btn_encode.clicked.connect(self._start_encode)

        self.btn_stop = QPushButton("🗑  Очистить")
        self.btn_stop.setFixedHeight(32)
        self.btn_stop.setEnabled(True)
        self.btn_stop.clicked.connect(self._clear_result)

        btn_row.addWidget(btn_browse)
        btn_row.addWidget(self.btn_encode)
        btn_row.addWidget(self.btn_stop)
        right.addLayout(btn_row)

        top.addLayout(right, 1)
        root.addLayout(top)

        # ── Прогресс-бар ─────────────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        self.progress.hide()
        root.addWidget(self.progress)

        # ── Результат ─────────────────────────────────────────────────────────
        grp_out = QGroupBox("Результат (Base64)")
        vl = QVBoxLayout(grp_out)

        self.txt_out = QPlainTextEdit()
        self.txt_out.setReadOnly(True)
        self.txt_out.setPlaceholderText("Здесь появится Base64-строка после кодирования…")
        self.txt_out.setFont(QFont("Courier New", 9))
        self.txt_out.setMinimumHeight(80)
        self.txt_out.setMaximumHeight(260)
        vl.addWidget(self.txt_out)

        h_btns = QHBoxLayout()
        self.lbl_size = QLabel("")
        self.lbl_size.setStyleSheet("color:#6c7086; font-size:11px;")
        btn_copy = QPushButton("📋  Копировать")
        btn_copy.setFixedWidth(130)
        btn_copy.clicked.connect(self._copy)
        h_btns.addWidget(self.lbl_size)
        h_btns.addStretch()
        h_btns.addWidget(btn_copy)
        vl.addLayout(h_btns)

        root.addWidget(grp_out, 1)
        self.setAcceptDrops(True)

    # ── Drag & drop ───────────────────────────────────────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls: self._set_path(urls[0])

    # ── Вспомогательные ──────────────────────────────────────────────────────
    def _browse(self):
        # Строим фильтры: популярные группы + «Все файлы»
        media   = "Медиафайлы (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv *.m4v *.ts *.3gp *.mp3 *.opus *.wav *.flac *.ogg *.aac *.m4a *.wma *.aiff)"
        images  = "Изображения (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.tiff *.avif *.heic *.heif *.ico *.svg)"
        model3d = "3D / Игровые ассеты (*.glb *.gltf *.obj *.fbx *.dae *.3ds *.stl *.ply *.blend *.usdz *.usd *.abc *.pak *.vpk *.bsp *.mdl *.vtf *.prefab *.asset)"
        docs    = "Документы (*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.txt *.rtf *.odt *.csv *.md *.json *.xml *.yaml *.yml *.toml)"
        fonts   = "Шрифты (*.ttf *.otf *.woff *.woff2 *.eot)"
        archives= "Архивы (*.zip *.rar *.7z *.tar *.gz *.bz2 *.xz *.zst)"
        other   = "Прочее (*.bin *.dat *.db *.sqlite *.iso *.img *.dmg)"
        all_f   = "Все файлы (*)"
        flt = ";;".join([media, images, model3d, docs, fonts, archives, other, all_f])
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл для кодирования в Base64", "", flt)
        if path: self._set_path(path)

    def _set_path(self, path):
        self._current_path = path
        self.lbl_fname.setText(os.path.basename(path))
        self.lbl_hint.hide()
        self.txt_out.clear()
        self.lbl_size.setText("")
        self._load_thumb(path)
        # Автоматически запускаем кодирование сразу после выбора файла
        QTimer.singleShot(80, self._start_encode)

    def _load_thumb(self, path):
        ext = os.path.splitext(path)[1].lower()
        icon_val = self._ICON_MAP.get(ext, '📦')  # 📦 для неизвестных

        # Изображения — показываем превью
        img_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
                    '.tiff', '.tif', '.avif', '.heic', '.heif', '.ico'}
        if ext in img_exts:
            pix = QPixmap()
            if Image:
                try:
                    with Image.open(path) as im:
                        if ImageOps: im = ImageOps.exif_transpose(im)
                        im.thumbnail((240, 180))
                        bio = io.BytesIO()
                        im.convert("RGBA").save(bio, "PNG")
                        pix.loadFromData(QByteArray(bio.getvalue()))
                except Exception:
                    pass
            if pix.isNull():
                pix = QPixmap(path)
            if not pix.isNull():
                self.lbl_thumb.setPixmap(
                    pix.scaled(120, 90, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
                return

        # Видео — пытаемся вытащить кадр через ffmpeg
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv',
                      '.m4v', '.ts', '.mts', '.m2ts', '.vob', '.ogv', '.3gp',
                      '.3g2', '.divx', '.f4v', '.mxf', '.rm', '.rmvb'}
        if ext in video_exts:
            pix = QPixmap()
            try:
                tmp = os.path.join(tempfile.gettempdir(), f"ym_b64_thumb_{uuid.uuid4().hex}.jpg")
                subprocess.run([FFMPEG, "-y", "-i", path, "-vframes", "1", "-q:v", "5", tmp],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=CREATE_NO_WINDOW, timeout=8)
                if os.path.exists(tmp):
                    pix = QPixmap(tmp)
                    try: os.remove(tmp)
                    except Exception: pass
            except Exception:
                pass
            if not pix.isNull():
                self.lbl_thumb.setPixmap(
                    pix.scaled(120, 90, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
                return

        # Для всего остального — большой эмодзи-значок
        icon_chr = icon_val if icon_val else '📦'
        ext_upper = ext.upper().lstrip('.') if ext else '??'
        self.lbl_thumb.setText(f"{icon_chr}\n{ext_upper}")
        self.lbl_thumb.setStyleSheet(
            "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; "
            "color:#89b4fa; font-size:22px; qproperty-alignment: AlignCenter;")

    def _copy(self):
        text = self.txt_out.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.main.log("Base64 скопирован в буфер обмена")

    # ── Кодирование ──────────────────────────────────────────────────────────
    def _start_encode(self):
        path = self._current_path
        if not path or not os.path.isfile(path):
            self.main.log("Base64: файл не выбран или не существует")
            return
        self._stop_flag.clear()
        self.btn_encode.setEnabled(False)
        self.txt_out.clear()
        self.lbl_size.setText("Чтение файла…")
        self.progress.setValue(0)
        self.progress.show()

        def _worker():
            try:
                total = os.path.getsize(path)
                CHUNK = 256 * 1024  # 256 КБ
                chunks = []
                read = 0
                with open(path, "rb") as f:
                    while True:
                        if self._stop_flag.is_set():
                            self._sig_error.emit("Отменено пользователем")
                            return
                        chunk = f.read(CHUNK)
                        if not chunk: break
                        chunks.append(chunk)
                        read += len(chunk)
                        pct = int(read * 100 / total) if total else 0
                        self._sig_progress.emit(pct)

                raw = b"".join(chunks)
                if self._stop_flag.is_set():
                    self._sig_error.emit("Отменено пользователем")
                    return

                b64 = base64.b64encode(raw).decode("ascii")

                base_name = os.path.splitext(os.path.basename(path))[0]
                txt_path = os.path.join(os.path.dirname(path), base_name + "_base64.txt")
                with open(txt_path, "w", encoding="ascii") as f:
                    f.write(b64)

                size_kb = len(b64) / 1024
                size_str = (f"{size_kb/1024:.2f} МБ" if size_kb >= 1024 else f"{size_kb:.1f} КБ")
                self._sig_done.emit(b64, size_str, txt_path)
            except Exception as ex:
                self._sig_error.emit(str(ex))

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_encode(self):
        self._stop_flag.set()

    def _clear_result(self):
        """Очищает поле результата, сбрасывает превью и прогресс."""
        self._stop_flag.set()  # останавливает фоновый поток если идёт кодирование
        self.txt_out.clear()
        self.lbl_size.setText("")
        self.lbl_fname.setText("Файл не выбран")
        self.lbl_thumb.setPixmap(QPixmap())
        self.lbl_thumb.setText("нет\nфайла")
        self.lbl_thumb.setStyleSheet(
            "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; color:#6c7086; font-size:11px;")
        self.lbl_hint.show()
        self.progress.hide()
        self.progress.setValue(0)
        self._current_path = ""
        self.btn_encode.setEnabled(True)

    def _on_done(self, b64: str, size_str: str, txt_path: str):
        self.txt_out.setPlainText(b64)
        self.progress.setValue(100)
        self.progress.hide()
        self.btn_encode.setEnabled(True)
        # Автокопирование в буфер обмена
        QApplication.clipboard().setText(b64)
        self.lbl_size.setText(f"✅ Скопировано! Размер: {size_str}  •  {os.path.basename(txt_path)}")
        self.main.log(f"Base64 готов ({size_str}), скопирован в буфер, сохранён: {txt_path}")

    def _on_error(self, msg: str):
        self.lbl_size.setText(f"❌ {msg}")
        self.progress.hide()
        self.btn_encode.setEnabled(True)
        self.main.log(f"Base64: {msg}")


class PhotoMergerTab(QWidget):
    # Форматы сохранения: (расширение, PIL-формат, параметры сохранения)
    _FMT_MAP = [
        ("tiff", "TIFF",  {"compression": "tiff_deflate"}),
        ("jpg",  "JPEG",  {"quality": 95}),
        ("png",  "PNG",   {}),
        ("webp", "WEBP",  {"quality": 90}),
    ]

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        # ЛЕВО — добавление + список + превью результата
        left_w = QWidget(); left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0); left.setSpacing(8)
        # ПРАВО — настройки (как в 1-й вкладке)
        right_scroll = QScrollArea(); right_scroll.setWidgetResizable(True)
        right_scroll.setFixedWidth(460)                       # всегда полноразмерно, как в 1-й вкладке
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_w.setMinimumWidth(140)
        right_w = QWidget(); right = QVBoxLayout(right_w)
        right.setContentsMargins(6, 4, 6, 4); right.setSpacing(8)
        right_scroll.setWidget(right_w)
        root.addWidget(left_w, 1); root.addWidget(right_scroll, 0)

        # ── Status bar ─────────────────────────────────────
        top = QHBoxLayout()
        self.lbl_status = QLabel("Перетащите фотографии или нажмите «Добавить»")
        self.lbl_status.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 13px;")
        # Подсказка уступает место кнопкам (иначе её длинный текст распирает ряд
        # и подписи кнопок обрезаются).
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        # Без setFixedWidth — крупный шрифт обрезал подписи («Добави…», «Очистить вс…»).
        # Кнопки берут ширину по содержимому; статус-лейбл (stretch=1) отдаёт им место.
        btn_open = QPushButton("📂  Добавить файлы")
        btn_open.clicked.connect(self._open_files)

        btn_clear_sel = QPushButton("✂  Удалить выбранные")
        btn_clear_sel.clicked.connect(self._remove_selected)

        btn_clear_all = QPushButton("🗑  Очистить всё")
        btn_clear_all.setObjectName("b_stop")
        btn_clear_all.clicked.connect(self._clear_all)

        top.addWidget(self.lbl_status, 1)
        top.addWidget(btn_open)
        top.addWidget(btn_clear_sel)
        top.addWidget(btn_clear_all)
        left.addLayout(top)

        # ── File list ───────────────────────────────────────
        self.file_list = PhotoDragList()
        left.addWidget(self.file_list, 3)
        # Клавиша Delete — удалить выделенные фото из списка
        self._sc_delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.file_list)
        self._sc_delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_delete.activated.connect(self._remove_selected)

        # ── ПРАВО: настройки объединения ──────────────────────
        grp_set = QGroupBox("Настройки"); set_l = QVBoxLayout(grp_set)
        self.rb_horiz = QPushButton("➡  Горизонт.")
        self.rb_vert  = QPushButton("⬇  Вертикал.")
        self.rb_horiz.setCheckable(True); self.rb_horiz.setChecked(True)
        self.rb_vert.setCheckable(True)
        self.rb_horiz.clicked.connect(lambda: self.rb_vert.setChecked(False))
        self.rb_vert.clicked.connect(lambda: self.rb_horiz.setChecked(False))
        row_mode = QHBoxLayout(); row_mode.addWidget(QLabel("Режим:"))
        row_mode.addWidget(self.rb_horiz); row_mode.addWidget(self.rb_vert); row_mode.addStretch()
        set_l.addLayout(row_mode)

        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItems(["TIFF", "JPEG", "PNG", "WEBP"])
        self.cmb_fmt.setFixedWidth(90)
        row_fmt = QHBoxLayout(); row_fmt.addWidget(QLabel("Формат:"))
        row_fmt.addWidget(self.cmb_fmt); row_fmt.addStretch()
        set_l.addLayout(row_fmt)
        right.addWidget(grp_set)

        self.btn_merge_new = QPushButton("▶  Объединить новые")
        self.btn_merge_new.setObjectName("b_run")
        self.btn_merge_new.clicked.connect(lambda: self._do_merge(force_all=False))
        self.btn_merge_all = QPushButton("⟳  Переобъединить всё")
        self.btn_merge_all.setObjectName("b_restart")
        self.btn_merge_all.clicked.connect(lambda: self._do_merge(force_all=True))
        right.addWidget(self.btn_merge_new)
        right.addWidget(self.btn_merge_all)
        right.addStretch()

        # ── Preview ─────────────────────────────────────────
        grp_prev = QGroupBox("Результат последнего объединения")
        prev_l = QVBoxLayout(grp_prev)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(220)
        scroll.setStyleSheet("background-color: #181825; border: 1px solid #45475a; border-radius:4px;")
        self.lbl_preview = QLabel("Здесь появится результат")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet("color: #585b70; font-size: 13px;")
        scroll.setWidget(self.lbl_preview)
        prev_l.addWidget(scroll)
        left.addWidget(grp_prev, 2)

        # ── Accept drops on the whole widget ───────────────
        self.setAcceptDrops(True)

    # ── Drag-and-drop forwarding ────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            links = [str(u.toLocalFile()) for u in event.mimeData().urls()]
            self.file_list.add_files(links)

    # ── Helpers ─────────────────────────────────────────────
    def add_paths(self, paths):
        _img = {'.png','.jpg','.jpeg','.bmp','.gif','.tiff','.tif',
                '.webp','.avif','.heic','.heif','.ico'}
        valid = [p for p in paths if os.path.splitext(p)[1].lower() in _img]
        if valid:
            self.file_list.add_files(valid)

    def _open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выбрать изображения", "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp *.avif *.heic *.heif *.ico)"
        )
        if files:
            self.file_list.add_files(files)

    def _remove_selected(self):
        for it in self.file_list.selectedItems():
            idx = self.file_list.indexOfTopLevelItem(it)
            if idx >= 0:
                self.file_list.takeTopLevelItem(idx)

    def _clear_all(self):
        self.file_list.clear()
        self.lbl_preview.clear()
        self.lbl_preview.setText("Здесь появится результат")
        self.lbl_status.setText("Список очищен")

    # ── Core merge ──────────────────────────────────────────
    def _do_merge(self, force_all: bool):
        if not Image:
            self.lbl_status.setText("❌ Pillow не установлен (pip install Pillow)")
            return

        items = self.file_list.get_all_items() if force_all else self.file_list.get_new_items()

        if not items:
            if force_all:
                self.lbl_status.setText("Список пуст!")
            else:
                self.lbl_status.setText("Нет новых файлов. Нажмите «Переобъединить всё».")
            return

        try:
            paths = [it.data(0, Qt.ItemDataRole.UserRole) for it in items]
            imgs = [Image.open(p) for p in paths]

            vertical = self.rb_vert.isChecked()

            if vertical:
                max_w = max(im.width for im in imgs)
                processed = []
                total_h = 0
                for im in imgs:
                    r = max_w / im.width
                    new_h = int(im.height * r)
                    processed.append(im.resize((max_w, new_h), Image.Resampling.LANCZOS))
                    total_h += new_h
                canvas = Image.new('RGB', (max_w, total_h), (0, 0, 0))
                y = 0
                for im in processed:
                    if im.mode != 'RGB': im = im.convert('RGB')
                    canvas.paste(im, (0, y)); y += im.height
            else:
                max_h = max(im.height for im in imgs)
                processed = []
                total_w = 0
                for im in imgs:
                    r = max_h / im.height
                    new_w = int(im.width * r)
                    processed.append(im.resize((new_w, max_h), Image.Resampling.LANCZOS))
                    total_w += new_w
                canvas = Image.new('RGB', (total_w, max_h), (0, 0, 0))
                x = 0
                for im in processed:
                    if im.mode != 'RGB': im = im.convert('RGB')
                    canvas.paste(im, (x, 0)); x += im.width

            # ── Output path: всегда рядом с исходными файлами ──
            out_dir = os.path.dirname(paths[0]) or "."

            ext, pil_fmt, save_kwargs = self._FMT_MAP[self.cmb_fmt.currentIndex()]
            out_path = os.path.join(out_dir, f"merged_{random.randint(1000, 9999)}.{ext}")
            canvas.save(out_path, format=pil_fmt, **save_kwargs)

            # ── Mark items ─────────────────────────────────
            r = random.randint(30, 90); g = random.randint(30, 90); b = random.randint(30, 90)
            self.file_list.mark_processed(items, QColor(r, g, b))

            # ── Preview ────────────────────────────────────
            pix = QPixmap(out_path)
            prev_w = self.lbl_preview.parent().width() - 30
            if prev_w < 80: prev_w = 80
            self.lbl_preview.setPixmap(
                pix.scaledToWidth(prev_w, Qt.TransformationMode.SmoothTransformation))

            self.lbl_status.setText(
                f"✅ Готово! {len(imgs)} фото → {os.path.basename(out_path)}")
            self.main.log(f"[Фото] Объединено {len(imgs)} файлов → {out_path}")

            # ── Отправить результат в очередь первой вкладки ──
            try:
                self.main.tab_media.add_paths([out_path])
                self.main.tabs.setCurrentWidget(self.main.tab_media)
                self.main.log(f"[Фото] Файл добавлен в очередь обработки: {os.path.basename(out_path)}")
            except Exception as send_exc:
                self.main.log(f"[Фото] Не удалось добавить в очередь: {send_exc}")

            try: play_done_sound()
            except Exception: pass

        except Exception as exc:
            self.lbl_status.setText(f"❌ Ошибка: {exc}")
            self.main.log(f"[Фото] Ошибка объединения: {exc}")
        finally:
            # Закрываем все PIL-изображения, чтобы избежать утечки памяти
            for im in imgs if 'imgs' in dir() else []:
                try: im.close()
                except Exception: pass


class PromptTab(QWidget):
    """Вкладка с промптами из Промпт.txt, лежащего рядом со скриптом."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Промпт.txt")
        self._checkboxes = []  # list of QCheckBox, each has ._full_text attribute
        self._build_ui()
        self._load_prompts()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        lbl = QLabel("Промпты для SiGame-игр:")
        lbl.setStyleSheet("font-weight:bold; color:#89b4fa; font-size:14px;")
        top.addWidget(lbl)
        top.addStretch()

        btn_all = QPushButton("✓ Все")
        btn_all.setFixedWidth(72)
        btn_all.clicked.connect(self._select_all)
        btn_none = QPushButton("✗ Снять")
        btn_none.setFixedWidth(72)
        btn_none.clicked.connect(self._select_none)
        self.btn_copy_sel = QPushButton("📋  Копировать выбранные")
        self.btn_copy_sel.clicked.connect(self._copy_selected)
        btn_pick = QPushButton("📂  Выбрать файл")
        btn_pick.setToolTip("Загрузить промпты из другого .txt файла")
        btn_pick.clicked.connect(self._choose_prompt_file)
        btn_reload = QPushButton("↺  Обновить")
        btn_reload.clicked.connect(self._load_prompts)

        top.addWidget(btn_all)
        top.addWidget(btn_none)
        top.addWidget(self.btn_copy_sel)
        top.addWidget(btn_pick)
        top.addWidget(btn_reload)
        root.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cb_widget = QWidget()
        self._cb_layout = QVBoxLayout(self._cb_widget)
        self._cb_layout.setContentsMargins(4, 4, 4, 4)
        self._cb_layout.setSpacing(2)
        self._cb_layout.addStretch()
        scroll.setWidget(self._cb_widget)
        root.addWidget(scroll)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#585b70; font-size:11px;")
        root.addWidget(self._status)

    def _load_prompts(self):
        while self._cb_layout.count() > 1:
            item = self._cb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()

        if not os.path.exists(self._prompt_path):
            self._status.setText(f"Файл не найден: {self._prompt_path}")
            return
        try:
            with open(self._prompt_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self._status.setText(f"Ошибка чтения: {e}")
            return

        sections = self._parse_sections(content)
        # Файл без нумерованных секций (N)) — показываем как один цельный промпт
        if not sections and content.strip():
            sections = [(os.path.basename(self._prompt_path), content.strip())]

        for title, body in sections:
            cb = QCheckBox(title)
            cb.setStyleSheet("font-size:13px; padding:5px 2px;")
            cb._full_text = title + "\n" + body  # type: ignore[attr-defined]
            self._checkboxes.append(cb)
            self._cb_layout.insertWidget(self._cb_layout.count() - 1, cb)

        self._status.setText(f"{len(self._checkboxes)} промптов  ·  {os.path.basename(self._prompt_path)}")

    def _choose_prompt_file(self):
        start_dir = os.path.dirname(self._prompt_path) if self._prompt_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл с промптами", start_dir,
            "Текстовые файлы (*.txt);;Все файлы (*.*)")
        if path:
            self._prompt_path = path
            self._load_prompts()

    def _parse_sections(self, text):
        sections = []
        current_title = None
        current_lines = []
        for line in text.splitlines():
            if re.match(r'^\d+\)', line.strip()):
                if current_title is not None:
                    sections.append((current_title, "\n".join(current_lines).strip()))
                current_title = line.strip()
                current_lines = []
            else:
                if current_title is not None:
                    current_lines.append(line)
        if current_title is not None:
            sections.append((current_title, "\n".join(current_lines).strip()))
        return sections

    def _select_all(self):
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _select_none(self):
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _copy_selected(self):
        parts = [cb._full_text for cb in self._checkboxes if cb.isChecked()]  # type: ignore[attr-defined]
        if not parts:
            self._status.setText("Ничего не выбрано")
            return
        QApplication.clipboard().setText("\n\n".join(parts))
        n = len(parts)
        suffix = "а" if n in (2, 3, 4) else "ов" if n != 1 else ""
        orig = self.btn_copy_sel.text()
        self.btn_copy_sel.setText(f"✓  Скопировано {n} пункт{suffix}!")
        QTimer.singleShot(2000, lambda: self.btn_copy_sel.setText(orig))
        self._status.setText(f"Скопировано {n} пункт{suffix} в буфер")
