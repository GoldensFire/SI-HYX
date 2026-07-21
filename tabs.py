# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# tabs.py — вкладки интерфейса
import base64
import io
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from config import (
    ALLOWED_AUDIO, ALLOWED_IMG, ALLOWED_MEDIA, AUDIO_BITRATES,
    CREATE_NO_WINDOW, DEFAULT_TAG, FFMPEG, FORMAT_OPTIONS, IS_WIN,
    ITEM_AUDIO_ROLE, ITEM_COMPARE_ROLE, ITEM_STATUS_ROLE, Image, ImageOps,
    MERGE_OPTIONS, QAbstractItemView, QAbstractSpinBox, QAction,
    QApplication, QByteArray, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFont, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QIcon, QKeySequence, QLabel, QLineEdit, QMenu, QPixmap,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QShortcut,
    QSize, QSlider, QSpinBox, QThreadPool, QTimer, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget, Qt, cpu_thread_count, get_icon,
    icon_html, pyqtSignal, status_html, strip_default_tag
)
from utils import (
    default_download_dir, fmt_bitrate_with_codec, get_media_info,
    get_video_codec_label, human_size, is_embed_candidate, kodik_get_info,
    load_settings, mask_html_js, measure_loudness,
    parse_youtube_start_seconds, play_done_sound, save_settings
)
from widgets import (
    DraggableTreeWidget, InvertedWheelComboBox, LocalThumbnailRunnable,
    PreviewNameDelegate, RemoteThumbnailRunnable, SpeedSpinBox,
    StatusColorDelegate, ZeroSpinBox, _JumpSlider, _icon_btn, info_badge,
    label_with_info, row_with_info, show_image_compare,
    show_image_fullscreen, show_video_compare
)
from workers import (InfoWorker, ProcessWorker, YtdlpWorker)

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
        self._url_start_s = None    # тайминг из ?t=/&t= ссылки (None — не задан)
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
        self.url_edit.textChanged.connect(self._on_url_edited)

        h = QHBoxLayout()
        btn_v = _icon_btn("Скачать", 'fa5s.download'); btn_v.clicked.connect(lambda: self.add_dl(False))
        btn_a = _icon_btn("Скачать (аудио)", 'fa5s.music'); btn_a.clicked.connect(lambda: self.add_dl(True))
        self.btn_stop = _icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e'); self.btn_stop.setObjectName("b_stop")
        self.btn_stop.clicked.connect(self.stop_all_dl)
        self.btn_stop.setEnabled(False)   # активна только при активных загрузках
        
        h.addWidget(self.url_edit); h.addWidget(btn_v); h.addWidget(btn_a); h.addWidget(self.btn_stop)
        
        self.out = QLineEdit(default_download_dir())
        btn_p = _icon_btn("", 'fa5s.folder-open'); btn_p.clicked.connect(self.ch_dir); btn_p.setFixedWidth(36)
        ho = QHBoxLayout(); ho.addWidget(self.out); ho.addWidget(btn_p)

        self.cookie_edit = QLineEdit(); self.cookie_edit.setPlaceholderText("Путь к файлу cookies.txt (необязательно)")
        self.cookie_edit.setClearButtonEnabled(True)
        btn_ck = _icon_btn("", 'fa5s.folder-open'); btn_ck.setFixedWidth(36)
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
        fl.addRow(label_with_info("Папка:", "Папка, куда сохраняются скачанные видео и аудио. "
                                  ), ho)
        fl.addRow(label_with_info("Cookies:", "Файл cookies.txt для приватных/возрастных видео. Получите файл cookies через любое расширение браузера и выберите к нему путь. В ином случае, половина видео может не скачиваться"), ho_ck)
        fl.addRow(label_with_info("Прокси:", "Прокси для скачивания (yt-dlp). Помогает при блокировке YouTube провайдером. "
                                  "Браузерный VPN тут не работает — нужен именно прокси. Примеры: http://127.0.0.1:8080, socks5://127.0.0.1:1080"), ho_px)
        fl.addRow(label_with_info("Kodik:", "Для сайтов с плеером Kodik (animego и т.п.): номер серии и название озвучки. "
                                  "После вставки ссылки списки заполняются автоматически, в лог выводится число серий и доступные озвучки. "
                                  "Примечание: 1080p на таких сайтах обычно апскейл, реальный максимум — 720p."), ho_kd)
        # Поля Папка/Cookies/Прокси — компактнее по высоте
        for _w in (self.out, btn_p, self.cookie_edit, btn_ck, self.proxy_edit):
            _w.setFixedHeight(26)
        fl.setVerticalSpacing(4)
        grp.setLayout(fl); layout.addWidget(grp)

        opt = QGroupBox("Опции"); ho = QHBoxLayout()
        self.c_q = QComboBox(); self.c_q.addItems(list(FORMAT_OPTIONS.keys())); self.c_q.setCurrentText("1080p")
        self.c_c = QComboBox(); self.c_c.addItems(MERGE_OPTIONS)
        # Списки субтитров/языка пусты, пока не добавлено видео. Заполняются
        # реально доступными дорожками после пробы метаданных (см.
        # _on_info_success/_populate_lang_combos). Так в них не висят ru/en/…,
        # когда видео ещё не добавлено или других дорожек у него нет.
        self.c_s = QComboBox()
        self.c_a = QComboBox()
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

        btn_clear_time = _icon_btn("", 'fa5s.times')
        # Равная высота с полями-циферками слева (С: / По:), чтобы стоять с ними в одну строку
        btn_clear_time.setFixedHeight(self.ts[0].sizeHint().height())
        btn_clear_time.setFixedWidth(40)
        btn_clear_time.setToolTip("Сбросить тайминги")
        btn_clear_time.clicked.connect(self._clear_timings)

        sliders_box = QVBoxLayout()
        # _JumpSlider — клик по дорожке сразу ставит ползунок в точку клика
        # (а не «ползёт» на pageStep). Двигать можно и кликом, и протаскиванием.
        self.slider_start = _JumpSlider(Qt.Orientation.Horizontal)
        self.slider_end = _JumpSlider(Qt.Orientation.Horizontal)
        self.slider_start.setRange(0, 36000); self.slider_end.setRange(0, 36000)
        self.slider_start.valueChanged.connect(self._slider_to_spins)
        self.slider_end.valueChanged.connect(self._slider_to_spins)

        _time_lbl = QHBoxLayout()
        _time_lbl.addWidget(QLabel("Обрезка:"))
        _time_lbl.addWidget(info_badge("Обрезка: качается только отрезок от Start до End. Пусто = всё видео. Точность нарезки зависит от Force KF."))
        _time_lbl.addStretch()
        sliders_box.addLayout(_time_lbl)
        sliders_box.addWidget(self.slider_start); sliders_box.addWidget(self.slider_end)

        # Быстрые кнопки длины отрезка: ставят ползунок «По» на +N от ползунка «С».
        # Удобно, когда нужен ровный кусок фиксированной длины от выбранной точки.
        dur_box = QHBoxLayout(); dur_box.setSpacing(4)
        dur_box.addWidget(QLabel("Длина:"))
        for _lbl, _sec in (("+30с", 30), ("+1 мин", 60), ("+3 мин", 180), ("+5 мин", 300)):
            _b = QPushButton(_lbl)
            _b.setToolTip(f"Поставить «По» на +{_lbl.lstrip('+')} от ползунка «С»")
            _b.clicked.connect(lambda _=False, s=_sec: self._add_duration(s))
            dur_box.addWidget(_b)
        dur_box.addStretch()
        sliders_box.addLayout(dur_box)

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
        # Список плоский (вложенности нет) — убираем отступ-«ветку» и стрелку
        # раскрытия слева, из-за которых у строк появлялась пустая область слева.
        self.tree.setIndentation(0); self.tree.setRootIsDecorated(False)
        # Цветовая подсветка строк по статусу (синий — качается, зелёный — готово,
        # красный — ошибка) + видимое выделение при клике — как на странице обработки.
        self.tree.setItemDelegate(StatusColorDelegate(self.tree))
        self.tree.customContextMenuRequested.connect(self.ctx)
        left.addWidget(self.tree, 1)
        # Клавиша Delete — удалить выделенные загрузки из списка
        self._sc_delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree)
        self._sc_delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_delete.activated.connect(self.delete_sel)

        hb = QHBoxLayout()
        b_del = _icon_btn("Удалить", 'fa5s.times'); b_del.clicked.connect(self.delete_sel)
        b_clr = _icon_btn("Очистить", 'fa5s.trash'); b_clr.clicked.connect(self.tree.clear)
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
        ts = parse_youtube_start_seconds(url) if url else None
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

    def _on_info_success(self, duration, thumb_url, sub_langs=None, audio_langs=None):
        self.main.log(f"Длительность получена: {duration} сек.")
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
            m.addAction(QAction(get_icon('fa5s.redo'), "Скачать заново", self, triggered=self.redownload_sel))
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
            # Опоздавший тик уже завершённого воркера (его watchdog мог эмитнуть
            # «Скачивание…» в момент гибели процесса) не должен воскрешать строку
            # и индикатор в панели задач после ошибки/остановки.
            if iid_ not in self.active_workers:
                return
            item = self.items.get(iid_, {}).get('item')
            if item:
                # p <= 0 — индикатор активности без реального % (подготовка/повторы
                # извлечения/тихий ffmpeg); реальный процент показываем от >0.
                item.setText(1, "…" if p <= 0 else f"{p:.1f}%"); item.setText(3, t)
            self._dl_pct[iid_] = p
            self._update_dl_taskbar()

        def on_done(iid_, status, clean_info, file_path):
            self._dl_pct.pop(iid_, None); self._update_dl_taskbar()
            item = self.items.get(iid_, {}).get('item')
            if item:
                item.setText(3, status)
                # Зелёная подсветка строки — как на странице обработки (делегат
                # StatusColorDelegate рисует фон по статусу из 0-й колонки).
                item.setData(0, ITEM_STATUS_ROLE, 'done')
                self.tree.viewport().update()
                if file_path and os.path.exists(file_path):
                    try:
                        dur, br_str, size, a_br, _a_codec = get_media_info(file_path)
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
                # Красная подсветка строки — как на странице обработки.
                item.setData(0, ITEM_STATUS_ROLE, 'err')
                self.tree.viewport().update()
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
            it.setData(0, ITEM_STATUS_ROLE, 'proc')  # синяя подсветка «в работе»
            self.items[iid] = {'item': it, 'url': url, 'audio_only': bool(audio_only)}

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
            it.setData(0, ITEM_STATUS_ROLE, 'proc')  # синяя подсветка «в работе»
            self.items[iid] = {'item': it, 'url': url, 'audio_only': bool(audio_only)}
            config = self._dl_config(iid, url, audio_only)
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

    def _remove_worker(self, iid):
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
        return {
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

    def redownload_sel(self):
        """Скачать выбранные заново В ТОЙ ЖЕ строке — без дубля в списке.
        Если по элементу ещё идёт воркер, СНАЧАЛА останавливаем его: иначе два
        процесса пишут один и тот же выходной файл и падают с WinError 32
        («файл занят другим процессом», 'X.m4a'->'X.m4a')."""
        for it in list(self.tree.selectedItems()):
            try:
                iid = it.data(0, Qt.ItemDataRole.UserRole)
                entry = self.items.get(iid, {}) if iid else {}
                url = (entry.get('url') if isinstance(entry, dict) else "") or it.text(0)
                if not (url and url.strip().startswith('http')):
                    continue
                url = url.strip()
                audio_only = bool(entry.get('audio_only', False)) if isinstance(entry, dict) else False
                # Гасим прежний воркер этого же элемента (если ещё активен) —
                # не плодим второй процесс на тот же файл.
                old = self.active_workers.pop(iid, None)
                if old:
                    try: old.stop()
                    except Exception: pass
                # Сброс строки в исходное состояние «в очереди»
                it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
                it.setToolTip(3, "")
                it.setData(0, ITEM_STATUS_ROLE, 'proc')
                self.tree.viewport().update()
                self.items[iid] = {'item': it, 'url': url, 'audio_only': audio_only}
                w = YtdlpWorker(self._dl_config(iid, url, audio_only))
                self.active_workers[iid] = w
                w.finished.connect(lambda _=None, i=iid: self._remove_worker(i))
                self._connect_worker_signals(w, iid)
                w.start()
                self._update_stop_btn()
                self.main.log(f"Повторная загрузка: {url}")
            except Exception as e:
                self.main.log(f"redownload error: {e}")

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
    media_info_sig = pyqtSignal(str, str, str, float)  # iid, размер, битрейт, длительность(с)
    media_lufs_sig = pyqtSignal(str, object)           # iid, LUFS до (или None)
    def __init__(self, main_win):
        super().__init__()
        self.main = main_win
        self.items = []
        self._item_map: dict = {}
        self._item_data_map: dict = {}
        # iid'ы, удалённые из очереди пользователем — та же живая ссылка
        # передаётся ProcessWorker'у, чтобы он мог прервать УЖЕ идущую обработку
        # конкретного файла, а не только не начинать ещё не стартовавшие.
        self._removed_ids: set = set()
        self.pool = QThreadPool()
        self.export_dir = ""  # пусто = экспортировать рядом с исходником
        self.setAcceptDrops(True)
        # Колонка «Время» (7): сколько длится перекодирование каждого файла.
        # _proc_started: iid → момент старта (time.monotonic); _proc_running —
        # iid'ы, которые сейчас кодируются (таймер тикает их время вверх).
        self._proc_started: dict = {}
        self._proc_running: set = set()
        self._item_pass: dict = {}   # iid → «N/total» текущего прохода подбора картинки
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(500)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        # Пока воркер работает, каждые 500мс подсовываем ему АКТУАЛЬНЫЕ настройки
        # с виджетов (см. _settings_sync_tick) — иначе файл, добавленный в очередь
        # уже во время обработки, кодировался бы с настройками, замороженными в
        # момент нажатия «НАЧАТЬ» (та же проблема, что и с CRF/скоростью/etc.,
        # изменёнными на лету).
        self._settings_sync_timer = QTimer(self)
        self._settings_sync_timer.setInterval(500)
        self._settings_sync_timer.timeout.connect(self._settings_sync_tick)
        self.setup_ui()
        self.thumb_sig.connect(self.set_thumb)
        self.media_info_sig.connect(self._apply_media_info)
        self.media_lufs_sig.connect(self._apply_media_lufs)
        self.worker = None

    def _find_item(self, iid) -> 'QTreeWidgetItem | None':
        """Возвращает QTreeWidgetItem по iid за O(1)."""
        return self._item_map.get(iid)

    def setup_ui(self):
        """Сборка интерфейса вкладки «Обработка».

        Раньше — один метод на ~560 строк. Разбит по границам групп настроек:
        каждая группа сама себя создаёт, наполняет и добавляет в rv_inner,
        поэтому секции независимы. Порядок вызовов и сами операции не менялись."""
        l, right_container, right_layout, rv_inner, rw, w = self._build_queue_and_panel()
        self._build_audio_group(rv_inner)
        self._build_video_group(rv_inner)
        self._build_images_group(rv_inner)
        self._build_footer(l, right_container, right_layout, rv_inner, rw, w)

    def _build_queue_and_panel(self):
        """Левая часть (очередь файлов, кнопки) и каркас правой панели настроек.
        Возвращает контейнеры каркаса: rv_inner — вертикальный layout, в который
        три следующих метода добавляют свои группы, остальные нужны футеру,
        который собирает панель уже после наполнения групп."""
        l = QHBoxLayout(self)
        l.setContentsMargins(6, 6, 6, 6); l.setSpacing(8)
        lw = QWidget(); lv = QVBoxLayout(lw)
        lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(6)

        # Строка быстрой загрузки сделана 1-в-1 как на вкладке «Загрузчик»
        # (YtdlpTab): подпись «Ссылка для скачивания:» над строкой + поле и три
        # кнопки в один ряд, без обрамляющего блока «Быстрая загрузка».
        lv.addWidget(QLabel("Ссылка для скачивания:"))
        qdl_h = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Вставьте ссылку.")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.url_edit.customContextMenuRequested.connect(self.on_url_ctx)

        btn_qdl_video = _icon_btn("Скачать", 'fa5s.download'); btn_qdl_video.clicked.connect(lambda: self.download_url(False))
        btn_qdl_audio = _icon_btn("Скачать (аудио)", 'fa5s.music'); btn_qdl_audio.clicked.connect(lambda: self.download_url(True))
        # Кнопка СТОП — как в строке загрузки на вкладке «Загрузчик» (YtdlpTab):
        # быстрые загрузки идут через тот же воркер-пул вкладки «Загрузчик», поэтому
        # СТОП останавливает их там же. Активна только при активных загрузках —
        # состояние ведёт YtdlpTab._update_stop_btn.
        self.btn_qdl_stop = _icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e')
        self.btn_qdl_stop.setObjectName("b_stop")
        self.btn_qdl_stop.clicked.connect(self._quick_dl_stop)
        self.btn_qdl_stop.setEnabled(False)

        qdl_h.addWidget(self.url_edit); qdl_h.addWidget(btn_qdl_video); qdl_h.addWidget(btn_qdl_audio); qdl_h.addWidget(self.btn_qdl_stop)
        lv.addLayout(qdl_h)

        self.tree = DraggableTreeWidget()
        self.tree.setAcceptDrops(True)
        self.tree.setPlaceholderText(
            "Добавляйте файлы сюда\n\n"
            "Перетащите видео, аудио или изображения в это окно\n"
            "или нажмите «Добавить файлы»")
        self.tree.setHeaderLabels(["Превью", "", "Размер", "Битрейт", "LUFS", "Длительность", "Статус", "Время", "Оценка XPSNR"])
        self.tree.setRootIsDecorated(False)
        self.tree.setItemDelegate(StatusColorDelegate(self.tree))  # цветовая подсветка строк
        # 0-я колонка: миниатюра + имя файла под ней (одной строкой, с многоточием).
        self._preview_delegate = PreviewNameDelegate(self.tree)
        self._preview_delegate.compare_clicked.connect(self._on_compare_clicked)
        self.tree.setItemDelegateForColumn(0, self._preview_delegate)
        self.tree.setIconSize(QSize(160,90)); self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.ctx)
        self.tree.setWordWrap(True)
        # Плавная прокрутка: по умолчанию список «прыгает» на целую строку (а строки
        # тут высокие — с превью 160×90), отчего колесо/скроллбар двигаются рывками.
        # Попиксельный режим прокручивает гладко, а шаг колеса задаём вручную (иначе
        # в попиксельном режиме одно деление колеса = 1 px, и крутить пришлось бы вечно).
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.verticalScrollBar().setSingleStep(24)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(0, 180)
        for i in range(1, 9): self.tree.header().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        # Колонка 1 — только метки «Было/Стало» (имя файла переехало под превью),
        # поэтому ширину отдаём по содержимому (ResizeToContents выше).
        # «Длительность» (5) и «Время» (7) — при ResizeToContents ширину диктует
        # длинное слово в заголовке, а не сам текст ячейки («22.75 с», «01:38»),
        # из-за чего колонки заметно шире содержимого. Фиксируем уже (но оставляем
        # Interactive — можно растянуть руками при необходимости).
        self.tree.header().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(5, 90)
        self.tree.header().setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(7, 78)

        h = QHBoxLayout()
        b1 = _icon_btn("Добавить файлы", 'fa5s.plus'); b1.clicked.connect(self.add)
        b2 = _icon_btn("Удалить", 'fa5s.times'); b2.clicked.connect(self.rem)
        b3 = _icon_btn("Очистить", 'fa5s.trash'); b3.clicked.connect(self.clear)
        for b in (b1, b2, b3): b.setMaximumWidth(120)
        b4 = _icon_btn("", 'fa5s.columns')
        b4.setFixedWidth(36)
        b4.setToolTip("Сравнить любые два файла с диска (картинки или видео)")
        b4.clicked.connect(self._compare_any_files)
        self.btn_export_dir = _icon_btn("", 'fa5s.folder-open')  # выбор папки экспорта
        self.btn_export_dir.setFixedWidth(36)
        self.btn_export_dir.setToolTip("Выбрать папку экспорта. По умолчанию — рядом с исходным файлом.")
        self.btn_export_dir.clicked.connect(self._choose_export_dir)
        self.btn_export_reset = _icon_btn("", 'fa5s.undo')
        self.btn_export_reset.setFixedWidth(36)
        self.btn_export_reset.setToolTip("Сбросить — экспортировать в папку исходника")
        self.btn_export_reset.clicked.connect(self._reset_export_dir)
        self.btn_export_reset.setEnabled(False)
        self.lbl_export_dir = QLabel("По умолчанию экспорт в папку исходника")
        self.lbl_export_dir.setStyleSheet("color:#a6adc8; font-size:11px;")
        h.addWidget(b1); h.addWidget(b2); h.addWidget(b3); h.addWidget(b4); h.addWidget(self.btn_export_dir); h.addWidget(self.btn_export_reset); h.addWidget(self.lbl_export_dir)
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

        return l, right_container, right_layout, rv_inner, rw, w

    def _build_audio_group(self, rv_inner):
        """Группа «Аудио эффекты» (нормализация, фейды, деградация) + строка скорости."""
        ga = QGroupBox("Аудио эффекты"); fa = QFormLayout()
        self.ck_norm = QCheckBox("Loudnorm"); self.ck_norm.setChecked(True)
        self.s_tgt = QDoubleSpinBox(); self.s_tgt.setValue(-20.0); self.s_tgt.setRange(-60.0, 20.0); self.s_tgt.setSingleStep(0.1)
        self.s_lra = QDoubleSpinBox(); self.s_lra.setValue(11.0); self.s_lra.setRange(0.0, 50.0); self.s_lra.setSingleStep(0.1)
        self.s_tp = QDoubleSpinBox(); self.s_tp.setValue(-1.5); self.s_tp.setRange(-60.0, 10.0); self.s_tp.setSingleStep(0.1)
        self.ck_fade = QCheckBox("Затухание (Fade Out)"); self.ck_fade.setChecked(False)
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
        hbr.addWidget(info_badge("Кодируется в OPUS. 128 кбит - стандартное качество аудио в Youtube"))
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

        self.ck_no_audio = QCheckBox("Удалить аудио"); self.ck_no_audio.setChecked(False)
        fa.addRow(row_with_info(self.ck_no_audio, "Полностью вырезает звуковую дорожку из видео (-an). Остальные настройки звука выше становятся неактуальны."))

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

        # «Удалить аудио» гасит остальные настройки звука (они бы всё равно
        # игнорировались в process_media, но серым фоном честнее показать это в UI).
        self._audio_effect_widgets = [self.ck_norm, self.s_tgt, self.s_lra, self.s_tp,
                                      self.ck_fade_in, self.s_fade_in, self.ck_fade, self.s_fade,
                                      self.c_abitrate, self.ck_deg] + self._deg_group

        def _update_no_audio_vis(checked):
            for wdg in self._audio_effect_widgets:
                wdg.setEnabled(not checked)
            if checked:
                _update_deg_vis(False)   # скрыть под-настройки degrade, если были открыты
            else:
                _update_deg_vis(self.ck_deg.isChecked())
        self.ck_no_audio.toggled.connect(_update_no_audio_vis)
        _update_no_audio_vis(self.ck_no_audio.isChecked())

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

    def _build_video_group(self, rv_inner):
        """Группа «Перекодирование видео»: CRF/preset, режим, метрика XPSNR, тюнинг."""
        gv = QGroupBox("Перекодирование видео"); fv = QFormLayout()
        self.chk_enable_video = QCheckBox("Включить перекодирование"); self.chk_enable_video.setChecked(True)

        # --- Переключатель профиля: две кнопки-тогглы ---
        self.btn_mode_std  = QPushButton("Стандарт");       self.btn_mode_std.setCheckable(True);  self.btn_mode_std.setChecked(True)
        self.btn_mode_dark = _icon_btn("Тёмные сцены", 'fa5s.moon'); self.btn_mode_dark.setCheckable(True); self.btn_mode_dark.setChecked(False)
        self.btn_mode_std.setToolTip("yuv420p, 1-pass")
        self.btn_mode_dark.setToolTip("10-бит (yuv420p10le), tune=0, 2-pass AV1\nCRF, preset и разрешение — без изменений")
        self.btn_mode_std.clicked.connect(lambda: self._set_preset_mode("std"))
        self.btn_mode_dark.clicked.connect(lambda: self._set_preset_mode("dark"))
        mode_h = QHBoxLayout(); mode_h.addWidget(self.btn_mode_std); mode_h.addWidget(self.btn_mode_dark)
        mode_h.addStretch(1)
        # Ширину тоглов профиля резервируем под ЖИРНЫЙ текст: глобальный QSS
        # (QPushButton:checked → font-weight:bold) делает активную кнопку жирной,
        # из-за чего «Тёмные сцены» обрезалось до «…сцень». sizeHint() у Qt НЕ
        # учитывает font-weight, заданный CSS-псевдо-состоянием (:checked) —
        # только реальный .font() виджета — так что заранее посчитать нужную
        # ширину числом (как раньше) не выйдет, ЛЮБАЯ константа была подогнана
        # под неверный шрифт (при setMinimumWidth в __init__ кнопка ещё не
        # «располирована» глобальным QSS — .font() отдаёт временный дефолтный
        # шрифт, а не итоговый Segoe UI/13px). Меряем НАСТОЯЩИЙ размер: временно
        # выставляем жирный шрифт САМОМУ виджету (после ensurePolished — это уже
        # правильный шрифт), берём sizeHint() и возвращаем шрифт обратно —
        # bold остаётся исключительно на совести CSS :checked, как и было.
        QTimer.singleShot(0, self._size_profile_toggle_buttons)

        # ── Метрика качества (AV1, всегда SVT-AV1) ────────────────────────────
        # Выкл — ручной CRF как есть, кодировщик просто тюнится под tune=0
        # (как и раньше). XPSNR — CRF на каждый файл подбирается
        # самостоятельно (_metric_crf_search в workers.py, без внешних
        # инструментов: короткий пробный сэмпл + бинарный поиск + встроенный
        # ffmpeg-фильтр xpsnr) так, чтобы результат достигал заданного
        # значения в дБ (см. s_target_metric ниже); сам кодировщик всё равно
        # тюнится под tune=0 — метрика здесь означает цель ПОДБОРА CRF, а не
        # тюнинг энкодера.
        self.ck_metric_xpsnr = QCheckBox("XPSNR")
        self.ck_metric_xpsnr.setChecked(False)

        self.s_crf = QSpinBox(); self.s_crf.setRange(0, 63); self.s_crf.setValue(45)
        self.s_pre = QSpinBox(); self.s_pre.setRange(0, 13); self.s_pre.setValue(2)
        self.c_res = QComboBox(); self.c_res.addItems(["Исходное", "1920x1080", "1280x720" + DEFAULT_TAG, "854x480", "144x72"])
        self.c_res.setCurrentText("1280x720" + DEFAULT_TAG)
        self.c_res.setMinimumWidth(210); self.c_res.setMaximumWidth(240)
        self.c_res.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.c_fps = InvertedWheelComboBox(); self.c_fps.addItems(["Исходный", "Исходный (max 30)", "5", "12", "23.976", "24", "30", "60"])
        self.c_fps.setCurrentText("Исходный (max 30)")
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

        # ── Тюнинг SVT-AV1 (--tune) — под какую метрику оптимизирует энкодер ──
        # Реально поддерживаемые SVT-AV1 режимы тюнинга (проверено на бандленном
        # ffmpeg/SVT-AV1): 0=VQ, 1=PSNR, 2=SSIM, 4=MS-SSIM, 5=VMAF. tune=3 (IQ)
        # сознательно пропущен — он поддерживает только all-intra/low-delay
        # предсказание и падает с ошибкой на нашей random-access GOP-структуре
        # (keyint=-1:scd=1, см. _av1_encoder_args в workers.py).
        self.c_tune = InvertedWheelComboBox()
        self.c_tune.addItem("VQ (0)" + DEFAULT_TAG, 0)
        self.c_tune.addItem("PSNR (1)", 1)
        self.c_tune.addItem("SSIM (2)", 2)
        self.c_tune.addItem("MS-SSIM (4)", 4)
        self.c_tune.addItem("VMAF (5)", 5)
        self.c_tune.setMinimumWidth(150); self.c_tune.setMaximumWidth(180)
        fv.addRow(label_with_info(
            "Тюнинг:",
            "Под какую метрику качества оптимизирует SVT-AV1 при кодировании.\n"
            "VQ — субъективное визуальное качество (по умолчанию).\n"
            "PSNR / SSIM / MS-SSIM / VMAF — оптимизация под соответствующую объективную метрику."),
            self.c_tune)

        # ── Метрика: Выкл (ручной CRF) / XPSNR (авто-подбор CRF) ───────────
        self.s_target_metric = QSlider(Qt.Orientation.Horizontal)
        self.s_target_metric.setRange(15, 60); self.s_target_metric.setValue(40)
        self.s_target_metric.setSingleStep(1); self.s_target_metric.setPageStep(1)
        self.s_target_metric.setEnabled(False)
        self.s_target_metric.setMaximumWidth(140)

        self.lbl_target_metric = QLabel("40 дБ")
        self.lbl_target_metric.setMinimumWidth(55)
        self.lbl_target_metric.setEnabled(False)

        def _on_metric_toggled(checked):
            self.s_target_metric.setEnabled(checked)
            self.lbl_target_metric.setEnabled(checked)
            try: self.main._save_settings_now()
            except Exception: pass
        def _on_target_changed(v):
            self.lbl_target_metric.setText(f"{v} дБ")
            try: self.main._save_settings_now()
            except Exception: pass
        self.ck_metric_xpsnr.toggled.connect(_on_metric_toggled)
        self.s_target_metric.valueChanged.connect(_on_target_changed)

        metric_h = QHBoxLayout()
        metric_h.addWidget(self.ck_metric_xpsnr)
        metric_h.addWidget(self.s_target_metric)
        metric_h.addWidget(self.lbl_target_metric)
        self._badge_metric = info_badge(
            "Выкл — CRF задаётся вручную выше, кодировщик просто кодирует с ним как есть.\n"
            "XPSNR — перед кодированием на коротком сэмпле подбирается CRF под каждый файл так, "
            "чтобы результат достигал указанного значения в дБ (выше — качественнее и крупнее файл). "
            "Ручной CRF выше остаётся резервным значением, если подбор не удался. "
            "Дольше по времени — на каждый файл делается до 6 пробных кодирований.")
        metric_h.addWidget(self._badge_metric)
        metric_h.addStretch()
        fv.addRow(label_with_info("Метрика:", "Выкл — ручной CRF (по умолчанию). XPSNR — CRF подбирается автоматически под целевое значение в дБ."), metric_h)

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

        # Обрезка чёрных полос (cropdetect) — убирает letterbox/pillarbox при перекоде
        self.ck_crop_black = QCheckBox("Обрезать чёрные полосы"); self.ck_crop_black.setChecked(False)
        self._crop_black_row = row_with_info(self.ck_crop_black, "Автоматически определяет и вырезает чёрные поля (letterbox/pillarbox) при перекодировании. Рамка определяется по началу видео через cropdetect.")
        fv.addRow(self._crop_black_row)

        self._fv_form = fv
        gv.setLayout(fv); rv_inner.addWidget(gv)
        # Скрываем строки видео если перекодирование выключено
        self._video_enc_rows = [self.btn_mode_std, self.btn_mode_dark,
                                 self.ck_metric_xpsnr,
                                 self.s_crf, self.s_pre, self.c_tune, self.c_res, self.c_fps,
                                 self._badge_crf,
                                 self.s_target_metric, self.lbl_target_metric, self._badge_metric,
                                 self.s_vfade_in, self.s_vfade_out, self._crop_black_row]
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

    def _build_images_group(self, rv_inner):
        """Группа «Изображения»: формат, лимиты размера/разрешения, проходы подбора."""
        gavi = QGroupBox("Изображения"); favi = QFormLayout()
        # Выбор выходного формата
        self.c_img_fmt = InvertedWheelComboBox()
        self.c_img_fmt.addItems(["avif" + DEFAULT_TAG, "webp", "png", "jpg", "ico"])
        self.c_img_fmt.setCurrentText("avif" + DEFAULT_TAG)
        self.c_img_fmt.setMinimumWidth(190); self.c_img_fmt.setMaximumWidth(220)
        self.c_img_fmt.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        favi.addRow(label_with_info("Формат:", "Выходной формат изображений. avif — лучшее сжатие, на остальные форматы можно забить"), self.c_img_fmt)

        # Цветовая субдискретизация AVIF (только для avif; при альфе всегда 4:2:0)
        self.c_chroma = InvertedWheelComboBox()
        self.c_chroma.addItems(["4:2:0" + DEFAULT_TAG, "4:2:2", "4:4:4"])
        self.c_chroma.setCurrentText("4:2:0" + DEFAULT_TAG)
        self.c_chroma.setMinimumWidth(140); self.c_chroma.setMaximumWidth(180)
        favi.addRow(label_with_info(
            "Субдискретизация:",
            "Цветовая субдискретизация AVIF. 4:2:0 — минимальный размер файла (хватает для фото). "
            "4:4:4 — максимум цветовой чёткости (текст, графика, скриншоты), но файл крупнее. "
            "Для изображений с прозрачностью всегда 4:2:0."), self.c_chroma)

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

        # ── CQ-level: фиксированное качество AVIF (используется, когда лимит
        # размера выше выключен — при включённом лимите качество подбирается
        # автоматически бинарным поиском независимо от этого значения, поэтому
        # при включённом «Сжать до» поле визуально отключается) ─────────────
        self.s_cq = QSpinBox()
        self.s_cq.setRange(0, 63); self.s_cq.setValue(30)
        self.s_cq.setMaximumWidth(80)
        self._lbl_cq = label_with_info(
            "--cq-level:",
            "Уровень качества AVIF (libaom-av1, CQ-level: 0 — максимальное качество, 63 — максимальное сжатие). "
            "Применяется только когда выключен лимит «Сжать до» — при включённом лимите качество подбирается "
            "автоматически под нужный размер файла.")
        favi.addRow(self._lbl_cq, self.s_cq)
        # При включённом лимите размера CQ-level не участвует в кодировании —
        # отключаем визуально (темнее), чтобы не создавать видимость выбора.
        self.ck_lim.toggled.connect(lambda on: self.s_cq.setEnabled(not on))
        self.ck_lim.toggled.connect(lambda on: self._lbl_cq.setEnabled(not on))
        self.s_cq.setEnabled(not self.ck_lim.isChecked())
        self._lbl_cq.setEnabled(not self.ck_lim.isChecked())

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

        # ── Отдельные лимиты ширины / высоты (независимо от макс. стороны) ────
        # Применяются вместе с «макс. стороной»: итог — самый строгий предел,
        # пропорции сохраняются, увеличение никогда не делается.
        hwid = QHBoxLayout()
        self.ck_width = QCheckBox("Ширина до"); self.ck_width.setChecked(False)
        self.s_width = QSpinBox(); self.s_width.setRange(16, 8000); self.s_width.setSuffix(" px")
        self.s_width.setValue(1280); self.s_width.setEnabled(False)
        hwid.addWidget(self.ck_width); hwid.addWidget(self.s_width)
        hwid.addWidget(QLabel("(ширина)"))
        hwid.addWidget(info_badge("Ограничивает ШИРИНУ изображения (px), высота подстраивается пропорционально. Работает независимо и вместе с «макс. стороной»."))
        hwid.addStretch()
        self.ck_width.toggled.connect(self.s_width.setEnabled)
        favi.addRow(hwid)

        hhei = QHBoxLayout()
        self.ck_height = QCheckBox("Высота до"); self.ck_height.setChecked(False)
        self.s_height = QSpinBox(); self.s_height.setRange(16, 8000); self.s_height.setSuffix(" px")
        self.s_height.setValue(720); self.s_height.setEnabled(False)
        hhei.addWidget(self.ck_height); hhei.addWidget(self.s_height)
        hhei.addWidget(QLabel("(высота)"))
        hhei.addWidget(info_badge("Ограничивает ВЫСОТУ изображения (px), ширина подстраивается пропорционально. Работает независимо и вместе с «макс. стороной»."))
        hhei.addStretch()
        self.ck_height.toggled.connect(self.s_height.setEnabled)
        favi.addRow(hhei)

        self.sl_aspd = _JumpSlider(Qt.Orientation.Horizontal); self.sl_aspd.setRange(0, 8); self.sl_aspd.setValue(2)
        # Перезаписывать ИСХОДНИК: результат сохраняется под именем оригинала
        # (без суффикса «_Сжатый»), а сам исходный файл удаляется. По умолчанию
        # ВЫКЛ — операция необратима (оригинал не восстановить).
        self.ck_overwrite_src = QCheckBox("Перезаписывать исходник")
        self.ck_overwrite_src.setChecked(False)
        favi.addRow(label_with_info("Скорость:", "левее — медленнее и компактнее файл, правее — быстрее, но больше"), self.sl_aspd)
        favi.addRow(row_with_info(self.ck_overwrite_src, "ОПАСНО: удаляет исходное изображение и оставляет только сжатую версию (с именем оригинала, без «_Сжатый»). Оригинал не восстановить. По умолчанию выключено."))
        self._favi_form = favi
        gavi.setLayout(favi); rv_inner.addWidget(gavi)

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
        foot = QWidget(); foot_l = QHBoxLayout(foot); foot_l.setContentsMargins(6, 0, 6, 2)
        foot_l.addWidget(QLabel("Приоритет:"))
        self.c_priority = InvertedWheelComboBox()
        self.c_priority.addItems(["Низкий", "Обычный", "Высокий"])
        self.c_priority.setCurrentText("Обычный")
        self.c_priority.setMaximumWidth(150)
        # Приоритет сохраняем СВОИМ изолированным write (read-modify-write только
        # ключа 'priority'), а не только общим _save_settings_now: тот собирает
        # ВЕСЬ словарь настроек и при любой ошибке сборки молча НИЧЕГО не пишет
        # (см. _collect_settings → {}), из-за чего смена приоритета терялась.
        self.c_priority.currentTextChanged.connect(self._persist_priority)
        foot_l.addWidget(self.c_priority)
        foot_l.addWidget(info_badge("Приоритет процессов кодирования (ffmpeg) в системе. Высокий — кодирует быстрее; на Низком ПК отзывчивее."))
        foot_l.addStretch()
        # Всего логических потоков ЦП на этой машине — показываем сразу (0/N),
        # а не 0/0, чтобы было видно потенциал ещё до запуска обработки.
        self._cpu_threads = max(1, cpu_thread_count())
        self.lbl_threads = QLabel(f"Параллельных задач: 0/{self._cpu_threads}")
        self.lbl_threads.setToolTip(
            "Занятые логические потоки ЦП. Видео/аудио кодируются по одному файлу, "
            "но SVT-AV1 нагружает все ядра — поэтому показывается полное число потоков. "
            "Изображения обрабатываются параллельно (по числу ядер).")
        foot_l.addWidget(self.lbl_threads)
        right_layout.addWidget(foot)

        btn_box = QWidget(); btn_layout = QHBoxLayout(btn_box)
        btn_layout.setContentsMargins(0, 6, 0, 6)
        self.b_run = _icon_btn("НАЧАТЬ", 'fa5s.play', color='#1e1e2e'); self.b_run.setObjectName("b_run")
        self.b_stop = _icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e'); self.b_stop.setObjectName("b_stop"); self.b_stop.setEnabled(False)
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

    def _persist_priority(self, text):
        """Изолированно пишет ТОЛЬКО ключ 'priority' (read-modify-write), не трогая
        остальные настройки. Нужен потому, что общий _save_settings_now собирает
        весь словарь разом и при любой ошибке сборки молча не сохраняет ничего —
        тогда смена приоритета не доживала до следующего запуска."""
        try:
            s = load_settings()
            if isinstance(s, dict) and s:
                # Загрузили существующий словарь — дописываем только приоритет.
                s['priority'] = text
                save_settings(s)
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
            _bold_font = QFont(_orig_font); _bold_font.setBold(True)
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
            lbl = form.itemAt(row_idx, QFormLayout.ItemRole.LabelRole)
            fld = form.itemAt(row_idx, QFormLayout.ItemRole.FieldRole)
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
        # Колонка "Оценка XPSNR" в таблице файлов заполняется только когда метрика
        # включена — без неё это всегда пустой прочерк, прячем саму колонку.
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
        """Двойной клик: по готовому файлу — открыть результат в плеере;
        по ещё не обработанному (только добавленному) — запустить
        перекодирование ТОЛЬКО этого файла."""
        try:
            iid = item.data(0, Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if not entry:
                return
            if entry.get('is_done'):
                out_path = entry.get('out_path')
                if out_path and os.path.exists(out_path):
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
            iid = i.data(0, Qt.ItemDataRole.UserRole)
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
            i.setData(0, ITEM_STATUS_ROLE, None)
            i.setData(0, ITEM_COMPARE_ROLE, None)   # снять значок «сравнить»
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
                m.addAction(get_icon('fa5s.play'), "Открыть файл", lambda checked=False, p=out_path: self.open_output_file(p))
            m.addAction(get_icon('fa5s.folder-open'), "Перейти к файлу", lambda checked=False, it=sel: self.open_file_location(it))
            m.addAction(get_icon('fa5s.undo'), "Сбросить статус", lambda checked=False: self.reset_status())
            m.addSeparator()
            m.addAction(get_icon('fa5s.times'), "Удалить", lambda checked=False: self.rem())
        m.addAction(get_icon('fa5s.paste'), "Вставить файлы", lambda checked=False: self.paste_files())
        m.addAction(get_icon('fa5s.trash'), "Очистить всё", lambda checked=False: self.clear())
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

    _VK_V = 0x56

    def keyPressEvent(self, ev):
        # Резерв Ctrl+V для кириллической раскладки: физическая V шлёт Qt-код
        # кириллической буквы (М), и self.shortcut_paste (QShortcut("Ctrl+V"))
        # на ней молча не срабатывает — та же природа бага, что и Ctrl+Z/Y в
        # Монтаже (edit_tab.py) и WASD в редакторе фото (см. _pan_dir_from_event).
        # Доходит сюда, только если QShortcut его не поймал (для латиницы уже
        # сработал он — двойной вставки нет).
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            try:
                vk = ev.nativeVirtualKey()
            except Exception:
                vk = 0
            if vk == self._VK_V or ev.key() == Qt.Key.Key_V:
                self.paste_files()
                ev.accept()
                return
        super().keyPressEvent(ev)

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
                name = os.path.basename(p)
                # Колонка 0 (Превью): миниатюра + имя файла под ней (рисует
                # PreviewNameDelegate, длинное имя обрезается многоточием).
                # Полное имя — в тултипе.
                it.setText(0, name)
                # Тултип превью — только путь; полное имя показывается при
                # наведении на строку имени под превью (см. DraggableTreeWidget).
                it.setToolTip(0, p)
                # Колонка 1: метки Было/Стало. 2 строки [было, стало] —
                # центрируются по высоте строки как имя файла и статус (пустая
                # 1-я строка раньше сдвигала пару вниз от центра).
                it.setText(1, "Было\nСтало")
                it.setText(2, f"{human_size(size)}\n—")     # Размер: было(исх) / стало
                it.setText(3, "—\n—")                       # Битрейт: исх / итог
                it.setText(4, "—\n—")                       # LUFS: до / после
                it.setText(5, "—\n—")                       # Длительность: исх / итог
                it.setText(6, "Ожидание")                   # Статус (одна строка)
                it.setText(7, "—")                          # Время перекодирования (мм:сс)
                it.setToolTip(7, "Время, потраченное на перекодирование")
                it.setText(8, "—")                          # Оценка XPSNR (заполняется после видео-кодирования)
                it.setToolTip(8, "Оценка качества результата (XPSNR, дБ) — выше значит ближе к оригиналу.\n"
                                 "Только для перекодированного видео (AV1); при копировании/аудио — «—».")
                it.setData(0, Qt.ItemDataRole.UserRole, iid)
                # Аудио (без видеоряда) → компактная строка без места под превью.
                if ext in ALLOWED_AUDIO:
                    it.setData(0, ITEM_AUDIO_ROLE, True)
                self._item_map[iid] = it
                self.tree.scrollToItem(it)
                self.pool.start(LocalThumbnailRunnable(p, iid, self.thumb_sig))

                if ft == "MEDIA":
                    def _bg(path_local, iid_local):
                        # ffprobe + loudness — всё в фоне, UI не блокируем.
                        # Результат отдаём в GUI-поток через сигналы: QTimer.singleShot
                        # из обычного threading.Thread (без Qt event loop) НЕ
                        # срабатывает — из-за этого битрейт и длительность не
                        # появлялись при добавлении файла.
                        try:
                            dur_r, br_r, size_r, a_br_r, a_codec_r = get_media_info(path_local)
                            v_r = get_video_codec_label(path_local)
                            size_label_r = f"{v_r} {human_size(size_r)}" if v_r else human_size(size_r)
                            self.media_info_sig.emit(
                                iid_local, size_label_r,
                                fmt_bitrate_with_codec(a_codec_r, a_br_r or br_r),
                                float(dur_r or 0.0))
                        except Exception: pass
                        try:
                            val = measure_loudness(path_local)
                        except Exception: val = None
                        self.media_lufs_sig.emit(iid_local, val)
                    threading.Thread(target=_bg, args=(p, iid), daemon=True).start()

            except Exception as e:
                self.main.log(f"add_paths error: {e}")

    def set_thumb(self, iid, icon):
        try:
            item = self._find_item(iid)
            if item:
                item.setIcon(0, icon)
        except Exception: pass

    def _apply_media_info(self, iid, size_str, bitrate, dur):
        """GUI-поток: исходные размер/битрейт/длительность из ffprobe (верхняя
        строка «Было»). Вызывается через media_info_sig из фонового потока."""
        try:
            d = self._item_data_map.get(iid)
            if d: d['dur'] = dur
            item = self._find_item(iid)
            if item:
                if size_str:
                    self._set_pair(item, 2, top=size_str)
                self._set_pair(item, 3, top=(bitrate if bitrate and bitrate != "-" else "—"))
                self._set_pair(item, 5, top=self._fmt_dur(dur))
        except Exception: pass

    def _apply_media_lufs(self, iid, val):
        """GUI-поток: исходный LUFS (через media_lufs_sig из фонового потока)."""
        self.update_lufs_columns(iid, val, None)

    @staticmethod
    def _set_pair(item, col, top=None, bottom=None):
        """Ячейка из 2 строк: [было, стало]. Меняет только было/стало
        (top/bottom), сохраняя другую строку. Пара центрируется по высоте
        строки (как имя файла и статус)."""
        cur = (item.text(col) or "").split("\n")
        # Легаси-формат из 3 строк ([пусто, было, стало]) — отбрасываем пустую.
        if len(cur) >= 3:
            cur = cur[1:]
        t = cur[0] if len(cur) > 0 and cur[0] else "—"
        b = cur[1] if len(cur) > 1 and cur[1] else "—"
        if top is not None: t = top
        if bottom is not None: b = bottom
        item.setText(col, f"{t}\n{b}")

    @staticmethod
    def _fmt_dur(sec):
        """Длительность для колонки: «5.72 с» (<1 мин) или «M:SS.ss»."""
        try: sec = float(sec)
        except Exception: return "—"
        if sec <= 0: return "—"
        if sec < 60: return f"{sec:.2f} с"
        m = int(sec // 60); s = sec - m * 60
        return f"{m}:{s:05.2f}"

    def update_item_info(self, iid, size_new, bitrate_result):
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 2, bottom=size_new)          # Размер: стало
                self._set_pair(item, 3, bottom=bitrate_result)    # Битрейт: итог
                item.setData(0, ITEM_STATUS_ROLE, 'done')
                # Для обработанной картинки/видео включаем значок «сравнить» на превью
                # (аудио без видеоряда сравнивать нечем — там значок не нужен).
                entry = self._item_data_map.get(iid)
                is_video = entry and entry.get('type') == 'MEDIA' and Path(entry.get('path', '')).suffix.lower() not in ALLOWED_AUDIO
                if entry and (entry.get('type') == 'IMG' or is_video):
                    item.setData(0, ITEM_COMPARE_ROLE, True)
                    item.setToolTip(0, (item.toolTip(0) or "")
                                    + "\n\nЗначок в углу превью — сравнить исходник и результат.")
                self.tree.viewport().update()
        except Exception: pass

    def _on_compare_clicked(self, index):
        """Клик по значку «сравнить» на превью обработанного файла: открывает
        полноэкранное сравнение исходника и результата (картинка — по форме,
        видео — плеер слева/справа с синхронной перемоткой). Если оригинал/
        результат недоступны — показывает то, что есть."""
        try:
            iid = index.data(Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if not entry:
                return
            src = entry.get('path', '')
            out = entry.get('out_path', '')
            src_ok = bool(src) and os.path.exists(src)
            out_ok = bool(out) and os.path.exists(out)
            is_video = entry.get('type') == 'MEDIA' and Path(src or out).suffix.lower() not in ALLOWED_AUDIO
            if src_ok and out_ok and os.path.abspath(src) != os.path.abspath(out):
                if is_video:
                    show_video_compare(src, out, self)
                else:
                    show_image_compare(src, out, self)
            elif out_ok:
                if is_video:
                    show_video_compare(out, out, self)
                else:
                    show_image_fullscreen(out, self)
            elif src_ok:
                if is_video:
                    show_video_compare(src, src, self)
                else:
                    show_image_fullscreen(src, self)
        except Exception as e:
            self.main.log(f"Сравнение: {e}")

    def _compare_any_files(self):
        """Кнопка «Сравнить» в тулбаре списка — сравнение ЛЮБЫХ двух файлов с
        диска, а не только пары исходник/результат из очереди обработки. Тип
        (картинка или видео) определяется по расширению первого файла. Можно
        выбрать всего один файл — окно сравнения откроется сразу с ним (слева),
        а второй добавляется прямо в окне значком папки (тот же интерфейс,
        что и при обычном сравнении)."""
        try:
            video_exts = ALLOWED_MEDIA - ALLOWED_AUDIO
            exts = " ".join(f"*{e}" for e in sorted(ALLOWED_IMG | video_exts))
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Выберите файл(ы) для сравнения (можно один — второй добавите в окне)", "",
                f"Изображения и видео ({exts});;Все файлы (*)")
            if not paths:
                return
            a = paths[0]
            b = paths[1] if len(paths) > 1 else None
            ext_a = Path(a).suffix.lower()
            if ext_a in ALLOWED_IMG:
                show_image_compare(a, b, self, use_filenames=True)
            elif ext_a in video_exts:
                show_video_compare(a, b, self, use_filenames=True)
            else:
                self.main.log(f"Сравнение: неподдерживаемый тип файла «{ext_a}»")
        except Exception as e:
            self.main.log(f"Сравнение: {e}")

    def update_item_dur(self, iid, dur_str):
        """Длительность итогового файла (после перекодирования) — нижняя строка."""
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 5, bottom=self._fmt_dur(dur_str))
        except Exception: pass

    def update_item_xpsnr(self, iid, score):
        """Оценка качества результата (XPSNR, дБ) — заполняется после видео-
        кодирования (см. xpsnr_sig в workers.py). score=None — не измерялась
        (не видео, копия без перекодирования, или замер не удался)."""
        try:
            item = self._find_item(iid)
            if item:
                item.setText(8, "—" if score is None else f"{score:.1f} дБ")
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
                # Мутируем СПИСОК НА МЕСТЕ (не self.items = [...]) — ProcessWorker
                # держит ссылку на этот же объект-список как «живую» очередь
                # (см. queue_ref в _run_items); переприсваивание отвязывало бы
                # воркер от изменений, и удалённый файл всё равно обрабатывался
                # бы до конца, а не только до нажатия «СТОП».
                self.items[:] = [x for x in self.items if x['iid'] != iid]
                self._item_map.pop(iid, None)
                self._item_data_map.pop(iid, None)
                self._removed_ids.add(iid)
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
        """Кнопка «НАЧАТЬ» — обрабатывает всю очередь."""
        self._run_items(self.items)

    def _collect_settings(self):
        """Собирает АКТУАЛЬНОЕ состояние всех настроек «Обработки» с виджетов —
        единственное место сборки, чтобы кнопка «НАЧАТЬ» и фоновая пере-синхронизация
        настроек уже идущего воркера (_settings_sync_tick) всегда читали одно и то же
        и любая новая настройка, добавленная сюда в будущем, подхватывалась обоими
        путями сама собой."""
        try: ab = self.c_abitrate.currentText() or "128"
        except Exception: ab = "128"
        try: spd = self.s_spd.value()
        except Exception: spd = 100
        return {
            'audio': {
                'remove': bool(self.ck_no_audio.isChecked()),
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
                'tune': self._video_tune_value(),
                'metric': self._video_metric_value(), 'target_metric': float(self.s_target_metric.value()),
                'vfade_in': bool(self.ck_vfade_in.isChecked()), 'vfade_in_d': float(self.s_vfade_in.value()),
                'vfade_out': bool(self.ck_vfade_out.isChecked()), 'vfade_out_d': float(self.s_vfade_out.value()),
                'crop_black': bool(self.ck_crop_black.isChecked())
            },
            'avif': {
                'limit': int(self.s_lim.value()) if self.ck_lim.isChecked() else 0,
                'adim': int(self.s_dim.value()) if self.ck_dim.isChecked() else 0,
                'awidth': int(self.s_width.value()) if self.ck_width.isChecked() else 0,
                'aheight': int(self.s_height.value()) if self.ck_height.isChecked() else 0,
                'aspd': int(self.sl_aspd.value()),
                'cq': int(self.s_cq.value()),
                'overwrite_src': bool(self.ck_overwrite_src.isChecked()),
                'fit_passes': int(self.s_passes.value()),
                'img_fmt': strip_default_tag(self.c_img_fmt.currentText()),
                'chroma': strip_default_tag(self.c_chroma.currentText()).replace(':', '')
            },
            'export_dir': self.export_dir or '',
            'priority': {'Низкий': 'low', 'Обычный': 'normal', 'Высокий': 'high'}.get(
                self.c_priority.currentText(), 'normal')
        }

    def _settings_sync_tick(self):
        """Пока воркер работает — подсовывает ему свежий словарь настроек (см.
        _collect_settings). ProcessWorker читает self.settings заново для КАЖДОГО
        файла (self.settings.get(...) внутри process_media), поэтому уже начатый
        файл фоновым перезапросом не затрагивается — досрочно подхватывают
        изменение только ещё не стартовавшие (в т.ч. добавленные во время работы)."""
        w = getattr(self, 'worker', None)
        if w is None or not w.isRunning():
            self._settings_sync_timer.stop()
            return
        try:
            w.settings = self._collect_settings()
        except Exception:
            pass

    def _run_items(self, target):
        if not target: return
        # Не запускаем второй воркер поверх активного (двойной клик во время работы)
        if getattr(self, 'worker', None) is not None:
            try:
                if self.worker.isRunning():
                    self.main.log("Дождитесь завершения текущей обработки.")
                    return
            except Exception: pass
        s = self._collect_settings()
        self.worker = ProcessWorker(target, s, removed_ids=self._removed_ids)
        self.worker.status.connect(self.on_stat); self.worker.progress.connect(self.on_prog)
        self.worker.log.connect(self.main.log); self.worker.finished_all.connect(self.done)
        self.worker.global_progress.connect(self.main.update_global_progress)
        self.worker.update_item_sig.connect(self.update_item_info); self.worker.update_lufs_sig.connect(self.update_lufs_columns)
        self.worker.update_dur_sig.connect(self.update_item_dur)
        self.worker.xpsnr_sig.connect(self.update_item_xpsnr)
        self.worker.active_threads.connect(self._on_active_threads)

        try:
            for itdata in target:
                if itdata.get('is_done'): continue
                iid = itdata.get('iid')
                item = self._find_item(iid)
                if item:
                    item.setData(0, ITEM_STATUS_ROLE, 'proc')
                    item.setText(6, "Ожидание")   # сброс прошлого «Готово»/«Ошибка»
                    item.setText(7, "—")
                # Сбрасываем прошлый замер времени — новый запуск считает с нуля.
                self._proc_started.pop(iid, None)
                self._proc_running.discard(iid)
            self.tree.viewport().update()
        except Exception: pass

        self.b_run.setEnabled(False); self.b_stop.setEnabled(True)
        self.worker.start()
        self._settings_sync_timer.start()

    def stop(self):
        if self.worker:
            try: self.worker.stop()
            except Exception: pass

    _RE_IMG_PASS = re.compile(r"картинки (\d+)/(\d+)")

    def on_stat(self, iid, txt, code):
        try:
            i = self._find_item(iid)
            if i:
                i.setData(0, ITEM_STATUS_ROLE, code)
                # Не показываем промежуточные подписи «Обработка.»/«Конвертация
                # картинки» — в колонке «Статус» сразу идут проценты (on_prog)
                # и финальные «Готово»/«Ошибка»/«Остановлено».
                if code != 'proc':
                    i.setText(6, txt)
                self.tree.viewport().update()
            # Подбор AVIF/WebP под лимит размера идёт несколькими проходами —
            # текст вида «Конвертация картинки N/total» несёт номер прохода,
            # который показываем рядом с временем (колонка «Время»).
            if code == 'proc':
                m = self._RE_IMG_PASS.search(txt or "")
                if m:
                    self._item_pass[iid] = f"{m.group(1)}/{m.group(2)}"
                    self._update_elapsed_text(iid)
            # Учёт времени перекодирования (колонка «Время»):
            #   proc      → засекаем старт (единожды) и запускаем тик-таймер;
            #   done/err  → фиксируем итог и больше не тикаем этот файл.
            if code == 'proc':
                self._start_elapsed(iid)
            elif code in ('done', 'err'):
                self._item_pass.pop(iid, None)
                self._freeze_elapsed(iid)
        except Exception: pass

    def on_prog(self, iid, val):
        try:
            i = self._find_item(iid)
            if i:
                i.setText(6, "Готово" if val >= 100 else f"{val}%")
            if val >= 100:
                self._freeze_elapsed(iid)
        except Exception: pass

    # ── Время перекодирования (колонка 7) ──────────────────────────────────────
    @staticmethod
    def _fmt_elapsed(sec) -> str:
        """Секунды → «мм:сс» (минуты и секунды через двоеточие)."""
        sec = max(0, int(sec))
        m, s = divmod(sec, 60)
        return f"{m:02d}:{s:02d}"

    def _elapsed_text_for(self, iid, elapsed_sec) -> str:
        """мм:сс + «(x/y)» прохода подбора картинки, если он сейчас идёт."""
        txt = self._fmt_elapsed(elapsed_sec)
        p = self._item_pass.get(iid)
        return f"{txt} ({p})" if p else txt

    def _update_elapsed_text(self, iid):
        """Перерисовывает колонку «Время» текущего файла (напр. когда сменился
        номер прохода, а не только тик таймера)."""
        start = self._proc_started.get(iid)
        if start is None:
            return
        i = self._find_item(iid)
        if i:
            i.setText(7, self._elapsed_text_for(iid, time.monotonic() - start))

    def _start_elapsed(self, iid):
        """Засекает старт перекодирования файла (если ещё не засечён) и
        включает таймер, который тикает время вверх до завершения."""
        if iid not in self._proc_started:
            self._proc_started[iid] = time.monotonic()
        self._proc_running.add(iid)
        i = self._find_item(iid)
        if i:
            i.setText(7, self._elapsed_text_for(iid, time.monotonic() - self._proc_started[iid]))
        if not self._elapsed_timer.isActive():
            self._elapsed_timer.start()

    def _tick_elapsed(self):
        """Раз в 0.5 с обновляет время у всех кодирующихся сейчас файлов."""
        now = time.monotonic()
        for iid in list(self._proc_running):
            i = self._find_item(iid)
            if i is None:
                self._proc_running.discard(iid)
                continue
            start = self._proc_started.get(iid)
            if start is not None:
                i.setText(7, self._elapsed_text_for(iid, now - start))
        if not self._proc_running:
            self._elapsed_timer.stop()

    def _freeze_elapsed(self, iid):
        """Фиксирует итоговое время файла и снимает его с тиканья (идемпотентно —
        повторные сигналы done/100% не пересчитывают и не сдвигают итог)."""
        self._proc_running.discard(iid)
        self._item_pass.pop(iid, None)
        start = self._proc_started.pop(iid, None)
        if start is not None:
            i = self._find_item(iid)
            if i:
                i.setText(7, self._fmt_elapsed(time.monotonic() - start))
        if not self._proc_running:
            self._elapsed_timer.stop()

    def _on_active_threads(self, n, m):
        try:
            # В простое показываем 0 из всех потоков ЦП машины (а не 0/0).
            total = m if m > 0 else self._cpu_threads
            self.lbl_threads.setText(f"Параллельных задач: {n}/{total}")
        except Exception: pass

    def done(self):
        self.b_run.setEnabled(True); self.b_stop.setEnabled(False)
        self._removed_ids.clear()
        # Страховка: фиксируем итоговое время по всем ещё «тикающим» файлам и
        # останавливаем таймер (на случай, если кто-то не прислал done/err).
        for iid in list(self._proc_running):
            self._freeze_elapsed(iid)
        self._elapsed_timer.stop()
        try: self.lbl_threads.setText(f"Параллельных задач: 0/{self._cpu_threads}")
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

    # Расширения и их иконки — имена значков qtawesome (см. get_icon в config.py).
    _ICON_MAP = {
        # Видео
        '.mp4': 'fa5s.film', '.mkv': 'fa5s.film', '.avi': 'fa5s.film', '.mov': 'fa5s.film', '.webm': 'fa5s.film',
        '.flv': 'fa5s.film', '.wmv': 'fa5s.film', '.m4v': 'fa5s.film', '.ts': 'fa5s.film', '.mts': 'fa5s.film',
        '.m2ts': 'fa5s.film', '.vob': 'fa5s.film', '.ogv': 'fa5s.film', '.3gp': 'fa5s.film', '.3g2': 'fa5s.film',
        '.divx': 'fa5s.film', '.f4v': 'fa5s.film', '.mxf': 'fa5s.film', '.rm': 'fa5s.film', '.rmvb': 'fa5s.film',
        # Аудио
        '.mp3': 'fa5s.music', '.opus': 'fa5s.music', '.wav': 'fa5s.music', '.flac': 'fa5s.music', '.ogg': 'fa5s.music',
        '.aac': 'fa5s.music', '.m4a': 'fa5s.music', '.wma': 'fa5s.music', '.aiff': 'fa5s.music', '.aif': 'fa5s.music',
        '.ape': 'fa5s.music', '.mka': 'fa5s.music', '.mid': 'fa5s.music', '.midi': 'fa5s.music', '.amr': 'fa5s.music',
        '.ac3': 'fa5s.music', '.dts': 'fa5s.music', '.ra': 'fa5s.music', '.au': 'fa5s.music',
        # 3D / Игровые ассеты
        '.glb': 'fa5s.cube', '.gltf': 'fa5s.cube', '.obj': 'fa5s.cube', '.fbx': 'fa5s.cube', '.dae': 'fa5s.cube',
        '.3ds': 'fa5s.cube', '.stl': 'fa5s.cube', '.ply': 'fa5s.cube', '.blend': 'fa5s.cube', '.usdz': 'fa5s.cube',
        '.usd': 'fa5s.cube', '.abc': 'fa5s.cube', '.x3d': 'fa5s.cube', '.vrml': 'fa5s.cube', '.wrl': 'fa5s.cube',
        # Изображения (будут показываться как превью)
        '.jpg': None, '.jpeg': None, '.png': None, '.gif': None, '.webp': None,
        '.bmp': None, '.tiff': None, '.tif': None, '.avif': None, '.heic': None,
        '.heif': None, '.ico': None, '.svg': 'fa5s.image',
        # Документы
        '.pdf': 'fa5s.file-alt', '.doc': 'fa5s.file-alt', '.docx': 'fa5s.file-alt', '.xls': 'fa5s.file-alt', '.xlsx': 'fa5s.file-alt',
        '.ppt': 'fa5s.file-alt', '.pptx': 'fa5s.file-alt', '.txt': 'fa5s.file-alt', '.rtf': 'fa5s.file-alt', '.odt': 'fa5s.file-alt',
        '.ods': 'fa5s.file-alt', '.odp': 'fa5s.file-alt', '.csv': 'fa5s.file-alt', '.md': 'fa5s.file-alt',
        # Архивы
        '.zip': 'fa5s.file-archive', '.rar': 'fa5s.file-archive', '.7z': 'fa5s.file-archive', '.tar': 'fa5s.file-archive', '.gz': 'fa5s.file-archive',
        '.bz2': 'fa5s.file-archive', '.xz': 'fa5s.file-archive', '.zst': 'fa5s.file-archive', '.lz4': 'fa5s.file-archive',
        # Шрифты
        '.ttf': 'fa5s.font', '.otf': 'fa5s.font', '.woff': 'fa5s.font', '.woff2': 'fa5s.font', '.eot': 'fa5s.font',
        # Код / данные
        '.json': 'fa5s.database', '.xml': 'fa5s.database', '.yaml': 'fa5s.database', '.yml': 'fa5s.database', '.toml': 'fa5s.database',
        '.bin': 'fa5s.database', '.dat': 'fa5s.database', '.db': 'fa5s.database', '.sqlite': 'fa5s.database', '.proto': 'fa5s.database',
        # Игровые / движковые форматы
        '.pak': 'fa5s.gamepad', '.vpk': 'fa5s.gamepad', '.bsp': 'fa5s.gamepad', '.mdl': 'fa5s.gamepad', '.vtf': 'fa5s.gamepad',
        '.vmt': 'fa5s.gamepad', '.prefab': 'fa5s.gamepad', '.asset': 'fa5s.gamepad', '.unity': 'fa5s.gamepad',
        # Прочее
        '.iso': 'fa5s.compact-disc', '.img': 'fa5s.compact-disc', '.dmg': 'fa5s.compact-disc',
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
        """Принимает один или несколько файлов. Если передано несколько и среди
        них есть HTML — маскирует все HTML-файлы сразу; иначе берёт первый файл."""
        self._route_paths(paths)

    def _route_paths(self, paths):
        paths = [p for p in (paths or []) if p]
        if not paths:
            return
        html = [p for p in paths
                if os.path.splitext(p)[1].lower() in (".html", ".htm")]
        if len(paths) > 1 and html:
            # Показываем первый HTML для превью и сразу маскируем все HTML-файлы.
            self._set_path(html[0])
            self._mask_paths(html)
        else:
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

        self.lbl_hint = QLabel(status_html('fa5s.lightbulb',
            "Перетащите файл (или сразу несколько HTML) из любой "
            "вкладки или с рабочего стола", '#6c7086', 11))
        self.lbl_hint.setStyleSheet("color:#6c7086; font-size:10px;")
        right.addWidget(self.lbl_hint)
        right.addStretch()

        btn_row = QHBoxLayout()
        btn_browse = _icon_btn("Выбрать файл", 'fa5s.folder-open')
        btn_browse.clicked.connect(self._browse)

        # Кнопка «Кодировать» убрана: файлы кодируются автоматически при
        # добавлении (drag&drop / «Выбрать файл»).
        self.btn_stop = _icon_btn("Очистить", 'fa5s.trash')
        self.btn_stop.setFixedHeight(32)
        self.btn_stop.setEnabled(True)
        self.btn_stop.clicked.connect(self._clear_result)

        btn_row.addWidget(btn_browse)
        btn_row.addWidget(self.btn_stop)
        right.addLayout(btn_row)

        # ── Маскировка HTML под VK (скрытие JS) ─────────────────────────────
        mask_row = QHBoxLayout()
        self.btn_mask_file = _icon_btn("Замаскировать HTML (JavaScript) для VK", 'fa5s.mask')
        self.btn_mask_file.setFixedHeight(32)
        self.btn_mask_file.setToolTip("Прячет JavaScript, чтобы обойти запрет VK")
        self.btn_mask_file.clicked.connect(self._mask_current_html)

        self.btn_mask_folder = _icon_btn("Замаскировать все HTML (JavaScript) в папке для VK", 'fa5s.mask')
        self.btn_mask_folder.setFixedHeight(32)
        self.btn_mask_folder.setToolTip(
            "Пакетно обрабатывает все .html в выбранной папке.\n"
            "Оригиналы не трогаются — результат в подпапке encoded\\")
        self.btn_mask_folder.clicked.connect(self._mask_folder_html)

        mask_row.addWidget(self.btn_mask_file)
        mask_row.addWidget(self.btn_mask_folder)
        right.addLayout(mask_row)

        # Галочка: переименовывать ли выходной HTML (добавлять суффикс _base).
        # Включена — поведение как раньше (<имя>_base.html).
        # Выключена — файл на выходе сохраняет оригинальное имя (<имя>.html).
        self.chk_rename_html = QCheckBox("Переименовывать выходной HTML (суффикс _base)")
        self.chk_rename_html.setChecked(True)
        self.chk_rename_html.setToolTip(
            "Включено: результат маскировки называется <имя>_base.html.\n"
            "Выключено: выходной HTML сохраняет оригинальное имя <имя>.html.")
        right.addWidget(self.chk_rename_html)

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

        # Сохранять ли результат в <имя>_base64.txt рядом с файлом.
        # По умолчанию ВЫКЛ — base64 копируется в буфер и показан в поле,
        # лишний .txt на диск не пишется.
        self.chk_make_txt = QCheckBox("Создавать .txt файл")
        self.chk_make_txt.setChecked(False)
        self.chk_make_txt.setToolTip(
            "Включено: рядом с файлом сохраняется <имя>_base64.txt.\n"
            "Выключено: результат только в этом поле и в буфере обмена.")
        vl.addWidget(self.chk_make_txt)

        h_btns = QHBoxLayout()
        self.lbl_size = QLabel("")
        self.lbl_size.setStyleSheet("color:#6c7086; font-size:11px;")
        btn_copy = _icon_btn("Копировать", 'fa5s.copy')
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
        if urls: self._route_paths(urls)

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
        html    = "HTML (*.html *.htm)"
        all_f   = "Все файлы (*)"
        flt = ";;".join([media, images, model3d, docs, fonts, archives, html, other, all_f])
        # Можно выбрать несколько файлов: несколько HTML маскируются разом.
        paths, _ = QFileDialog.getOpenFileNames(self, "Выбрать файл(ы) для кодирования в Base64", "", flt)
        if paths: self._route_paths(paths)

    def _set_path(self, path):
        self._current_path = path
        self.lbl_fname.setText(os.path.basename(path))
        self.lbl_hint.hide()
        self.txt_out.clear()
        self.lbl_size.setText("")
        self._load_thumb(path)
        # HTML-файлы предназначены для маскировки под VK, а не для обычного
        # base64: НЕ запускаем авто-кодирование (никаких .txt и дампа base64 в
        # GUI) — пользователь жмёт «🎭 Замаскировать HTML (JavaScript) для VK».
        if os.path.splitext(path)[1].lower() in (".html", ".htm"):
            self.lbl_size.setText("HTML готов — нажмите «Замаскировать HTML (JavaScript) для VK»")
        else:
            # Для прочих файлов — авто-кодирование сразу после выбора
            QTimer.singleShot(80, self._start_encode)

    def _load_thumb(self, path):
        ext = os.path.splitext(path)[1].lower()
        icon_val = self._ICON_MAP.get(ext, 'fa5s.box')  # fa5s.box — для неизвестных

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

        # Для всего остального — большой векторный значок типа файла + расширение.
        icon_name = icon_val if icon_val else 'fa5s.box'
        ext_upper = ext.upper().lstrip('.') if ext else '??'
        self.lbl_thumb.setText(
            f"{icon_html(icon_name, 30, '#89b4fa')}<br>{ext_upper}")
        self.lbl_thumb.setStyleSheet(
            "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; "
            "color:#89b4fa; font-size:18px; qproperty-alignment: AlignCenter;")

    def _copy(self):
        text = self.txt_out.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.main.log("Base64 скопирован в буфер обмена")

    # ── Маскировка HTML под VK ───────────────────────────────────────────────
    @staticmethod
    def _read_html(path):
        # utf-8-sig снимает возможный BOM; ошибки декодирования не роняют процесс
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read()

    def _mask_one(self, src):
        """Маскирует один HTML-файл → encoded\\<имя>[_base].html.
        Возвращает (out_path, n_in, n_ext)."""
        masked, n_in, n_ext = mask_html_js(self._read_html(src))
        base, ext = os.path.splitext(os.path.basename(src))
        out_dir = os.path.join(os.path.dirname(src), "encoded")
        os.makedirs(out_dir, exist_ok=True)
        suffix = "_base" if self.chk_rename_html.isChecked() else ""
        out_path = os.path.join(out_dir, base + suffix + ext)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(masked)
        return out_path, n_in, n_ext

    def _mask_paths(self, paths):
        """Пакетно маскирует переданный список HTML-файлов (из разных папок)."""
        files = [p for p in paths
                 if os.path.isfile(p)
                 and os.path.splitext(p)[1].lower() in (".html", ".htm")]
        if not files:
            self.lbl_size.setText(status_html('fa5s.exclamation-triangle', "Среди файлов нет .html", '#f9e2af'))
            return
        if len(files) == 1:
            # Один файл — показываем подробный отчёт как для одиночной маскировки.
            self._set_path(files[0])
            self._mask_current_html()
            return
        done = skipped = errors = 0
        report = [f"🎭 Маскировка HTML-файлов: {len(files)} шт.", ""]
        for src in files:
            try:
                out_path, n_in, n_ext = self._mask_one(src)
                if n_in or n_ext:
                    done += 1
                    report.append(f"✅ {os.path.basename(src)} — инлайн {n_in}, внешних {n_ext}")
                    self.main.log(f"HTML→VK: {os.path.basename(src)} (инлайн {n_in}, внешних {n_ext})")
                else:
                    skipped += 1
                    report.append(f"➖ {os.path.basename(src)} — нет <script>, копия")
                    self.main.log(f"HTML→VK: {os.path.basename(src)} — нет <script>, копия")
            except Exception as ex:
                errors += 1
                report.append(f"❌ {os.path.basename(src)} — {ex}")
                self.main.log(f"HTML→VK: {os.path.basename(src)} — ошибка: {ex}")
        self.txt_out.setPlainText("\n".join(report))
        self.lbl_size.setText(
            status_html('fa5s.check-circle', f"Готово: замаскировано {done}, без скриптов {skipped}, ошибок {errors} → encoded\\", '#a6e3a1'))
        self.main.log(f"HTML→VK: пакет из {len(files)} файлов — {done} замаскировано, "
                      f"{skipped} без скриптов, {errors} ошибок.")

    def _mask_current_html(self):
        """Маскирует текущий выбранный HTML-файл → encoded\\<имя>_base.html."""
        path = self._current_path
        if not path or not os.path.isfile(path):
            self.lbl_size.setText(status_html('fa5s.times-circle', "Сначала выберите .html файл", '#f38ba8'))
            self.main.log("HTML→VK: файл не выбран")
            return
        if os.path.splitext(path)[1].lower() not in (".html", ".htm"):
            self.lbl_size.setText(status_html('fa5s.times-circle', "Это не HTML-файл (нужен .html / .htm)", '#f38ba8'))
            self.main.log("HTML→VK: выбран не HTML-файл")
            return
        try:
            out_path, n_in, n_ext = self._mask_one(path)
            if n_in == 0 and n_ext == 0:
                self.lbl_size.setText(status_html('fa5s.exclamation-triangle', "В файле нет <script> — скопировано как есть", '#f9e2af'))
                self.main.log("HTML→VK: тегов <script> не найдено")
                return
            self.txt_out.setPlainText(
                "✅ HTML замаскирован под VK\n"
                f"Исходник:  {os.path.basename(path)}\n"
                f"Результат: encoded\\{os.path.basename(out_path)}\n\n"
                f"Закодировано инлайн-скриптов: {n_in}\n"
                f"Внешних <script src> → динамическая загрузка: {n_ext}\n\n"
                "Что сделано:\n"
                "• теги <script> удалены из разметки;\n"
                "• тело JS закодировано в base64;\n"
                "• запуск повешен на onload скрытой картинки;\n"
                "• инлайн onclick=… сохранены (код исполняется в глобале).")
            self.lbl_size.setText(
                status_html('fa5s.check-circle', f"encoded\\{os.path.basename(out_path)}  •  инлайн: {n_in}, внешних: {n_ext}", '#a6e3a1'))
            self.main.log(f"HTML→VK: {os.path.basename(path)} → {out_path} "
                          f"(инлайн {n_in}, внешних {n_ext})")
        except Exception as ex:
            self.lbl_size.setText(status_html('fa5s.times-circle', f"{ex}", '#f38ba8'))
            self.main.log(f"HTML→VK error: {ex}")

    def _mask_folder_html(self):
        """Пакетно маскирует все .html в выбранной папке → подпапка encoded\\."""
        folder = QFileDialog.getExistingDirectory(self, "Папка с HTML-файлами для маскировки", "")
        if not folder:
            return
        try:
            files = [f for f in os.listdir(folder)
                     if f.lower().endswith((".html", ".htm"))]
        except Exception as ex:
            self.lbl_size.setText(status_html('fa5s.times-circle', f"{ex}", '#f38ba8'))
            self.main.log(f"HTML→VK error: {ex}")
            return
        if not files:
            self.lbl_size.setText(status_html('fa5s.exclamation-triangle', "В папке нет .html файлов", '#f9e2af'))
            self.main.log("HTML→VK: в папке нет .html")
            return

        out_dir = os.path.join(folder, "encoded")
        os.makedirs(out_dir, exist_ok=True)
        done = skipped = errors = 0
        report = [f"📁 {folder}", f"→ {out_dir}", ""]
        for name in files:
            src = os.path.join(folder, name)
            try:
                masked, n_in, n_ext = mask_html_js(self._read_html(src))
                stem, ext = os.path.splitext(name)
                suffix = "_base" if self.chk_rename_html.isChecked() else ""
                with open(os.path.join(out_dir, stem + suffix + ext), "w", encoding="utf-8") as f:
                    f.write(masked)
                if n_in or n_ext:
                    done += 1
                    report.append(f"✅ {name} — инлайн {n_in}, внешних {n_ext}")
                    self.main.log(f"HTML→VK: {name} (инлайн {n_in}, внешних {n_ext})")
                else:
                    skipped += 1
                    report.append(f"➖ {name} — нет <script>, скопировано как есть")
                    self.main.log(f"HTML→VK: {name} — нет <script>, копия")
            except Exception as ex:
                errors += 1
                report.append(f"❌ {name} — {ex}")
                self.main.log(f"HTML→VK: {name} — ошибка: {ex}")

        self.txt_out.setPlainText("\n".join(report))
        self.lbl_size.setText(status_html('fa5s.check-circle',
            f"Готово: замаскировано {done}, без скриптов {skipped}, ошибок {errors} → encoded\\", '#a6e3a1'))
        self.main.log(f"HTML→VK: папка обработана — {done} замаскировано, "
                      f"{skipped} без скриптов, {errors} ошибок. Результат: {out_dir}")

    # ── Кодирование ──────────────────────────────────────────────────────────
    def _start_encode(self):
        path = self._current_path
        if not path or not os.path.isfile(path):
            self.main.log("Base64: файл не выбран или не существует")
            return
        self._stop_flag.clear()
        self.txt_out.clear()
        self.lbl_size.setText("Чтение файла…")
        self.progress.setValue(0)
        self.progress.show()
        make_txt = self.chk_make_txt.isChecked()  # читаем до старта потока

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

                txt_path = ""
                if make_txt:
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

    def _on_done(self, b64: str, size_str: str, txt_path: str):
        self.txt_out.setPlainText(b64)
        self.progress.setValue(100)
        self.progress.hide()
        # Автокопирование в буфер обмена
        QApplication.clipboard().setText(b64)
        if txt_path:
            self.lbl_size.setText(status_html('fa5s.check-circle', f"Скопировано! Размер: {size_str}  •  {os.path.basename(txt_path)}", '#a6e3a1'))
            self.main.log(f"Base64 готов ({size_str}), скопирован в буфер, сохранён: {txt_path}")
        else:
            self.lbl_size.setText(status_html('fa5s.check-circle', f"Скопировано! Размер: {size_str}", '#a6e3a1'))
            self.main.log(f"Base64 готов ({size_str}), скопирован в буфер")

    def _on_error(self, msg: str):
        self.lbl_size.setText(status_html('fa5s.times-circle', f"{msg}", '#f38ba8'))
        self.progress.hide()
        self.main.log(f"Base64: {msg}")



class PromptTab(QWidget):
    """Вкладка с промптами из произвольного .txt файла, выбранного пользователем.
    Последний выбранный файл запоминается в настройках и подгружается при старте."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checkboxes = []  # list of QCheckBox, each has ._full_text attribute
        # Последний выбранный файл (любой .txt) — из настроек; по умолчанию пусто.
        try:
            self._prompt_path = load_settings().get("prompt_file", "") or ""
        except Exception:
            self._prompt_path = ""
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

        btn_all = _icon_btn("Все", 'fa5s.check')
        btn_all.setFixedWidth(72)
        btn_all.clicked.connect(self._select_all)
        btn_none = _icon_btn("Снять", 'fa5s.times')
        btn_none.setFixedWidth(72)
        btn_none.clicked.connect(self._select_none)
        self.btn_copy_sel = _icon_btn("Копировать выбранные", 'fa5s.copy')
        self.btn_copy_sel.clicked.connect(self._copy_selected)
        btn_pick = _icon_btn("Выбрать файл", 'fa5s.folder-open')
        btn_pick.setToolTip("Загрузить промпты из любого .txt файла")
        btn_pick.clicked.connect(self._choose_prompt_file)
        btn_reload = _icon_btn("Обновить", 'fa5s.sync-alt')
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

        # Подсказка на пустом поле — как пользоваться вкладкой.
        self._empty_hint = QLabel(
            "Как это работает\n\n"
            "• Нажмите «Выбрать файл» и укажите любой .txt с промптами.\n"
            "   Выбранный файл запоминается и подгружается при следующем запуске.\n"
            "• Каждый пункт, начинающийся с «1)», «2)», «3)» … — отдельный промпт.\n"
            "   Файл без такой нумерации показывается одним цельным промптом.\n"
            "• Отметьте нужные галочками и нажмите «Копировать выбранные» —\n"
            "   они скопируются в буфер обмена (через пустую строку между собой).\n"
            "• «Обновить» — перечитать файл, если вы его изменили.\n\n"
            "Сейчас файл не выбран — нажмите «Выбрать файл».")
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet("color:#9399b2; font-size:12px; padding:8px 4px;")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._cb_layout.addWidget(self._empty_hint)

        self._cb_layout.addStretch()
        scroll.setWidget(self._cb_widget)
        root.addWidget(scroll)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#585b70; font-size:11px;")
        root.addWidget(self._status)

    def _load_prompts(self):
        # Удаляем только сами чекбоксы — подсказка _empty_hint и stretch остаются.
        for cb in self._checkboxes:
            self._cb_layout.removeWidget(cb)
            cb.deleteLater()
        self._checkboxes.clear()

        if not self._prompt_path:
            self._status.setText("Файл не выбран — нажмите «Выбрать файл»")
            self._empty_hint.setVisible(True)
            return
        if not os.path.exists(self._prompt_path):
            self._status.setText(f"Файл не найден: {self._prompt_path}")
            self._empty_hint.setVisible(True)
            return
        try:
            with open(self._prompt_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self._status.setText(f"Ошибка чтения: {e}")
            self._empty_hint.setVisible(True)
            return

        sections = self._parse_sections(content)
        # Файл без нумерованных секций (N)) — показываем как один цельный промпт
        if not sections and content.strip():
            sections = [(os.path.basename(self._prompt_path), content.strip())]

        # Чекбоксы вставляем перед stretch (последний элемент), но после подсказки.
        for title, body in sections:
            cb = QCheckBox(title)
            cb.setStyleSheet("font-size:13px; padding:5px 2px;")
            cb._full_text = title + "\n" + body  # type: ignore[attr-defined]
            self._checkboxes.append(cb)
            self._cb_layout.insertWidget(self._cb_layout.count() - 1, cb)

        # Подсказку показываем, только когда промптов нет.
        self._empty_hint.setVisible(not self._checkboxes)
        self._status.setText(f"{len(self._checkboxes)} промптов  ·  {os.path.basename(self._prompt_path)}")

    def _choose_prompt_file(self):
        start_dir = os.path.dirname(self._prompt_path) if self._prompt_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл с промптами", start_dir,
            "Текстовые файлы (*.txt);;Все файлы (*.*)")
        if path:
            self._prompt_path = path
            # Запоминаем выбор в общих настройках (merge, чтобы не затереть прочее).
            try:
                s = load_settings(); s["prompt_file"] = path; save_settings(s)
            except Exception:
                pass
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
        self.btn_copy_sel.setText(f"Скопировано {n} пункт{suffix}!")
        QTimer.singleShot(2000, lambda: self.btn_copy_sel.setText(orig))
        self._status.setText(f"Скопировано {n} пункт{suffix} в буфер")
