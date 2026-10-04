# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpTab: __init__. Public namespace: tabs."""
import tabs as _api


def __init__(self, main_win):
    super(_api.YtdlpTab, self).__init__()
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
