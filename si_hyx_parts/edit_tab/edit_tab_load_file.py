# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: load_file. Public namespace: edit_tab."""
import edit_tab as _api


def load_file(self, path):
    # Останавливаем воркер волны и подчищаем его временный wav (баг #7).
    if self.audio_worker and self.audio_worker.isRunning():
        self.audio_worker.stop(); self.audio_worker.wait()
    if self.audio_worker:
        try:
            if self.audio_worker.tmp_wav and _api.os.path.exists(self.audio_worker.tmp_wav):
                _api.os.remove(self.audio_worker.tmp_wav)
        except Exception:
            pass
        self.audio_worker = None
    if self._audio_partial_worker and self._audio_partial_worker.isRunning():
        self._audio_partial_worker.stop(); self._audio_partial_worker.wait()
    if self._audio_partial_worker:
        try:
            if self._audio_partial_worker.tmp_wav and _api.os.path.exists(self._audio_partial_worker.tmp_wav):
                _api.os.remove(self._audio_partial_worker.tmp_wav)
        except Exception:
            pass
        self._audio_partial_worker = None

    # Останавливаем фоновый proxy-воркер ДО удаления его файла (баг #2).
    if self.proxy_thread and self.proxy_thread.isRunning():
        self.proxy_thread.stop(); self.proxy_thread.wait()
    self.proxy_thread = None

    if self.tmp_proxy_file and _api.os.path.exists(self.tmp_proxy_file):
        try:
            _api.os.remove(self.tmp_proxy_file)
        except Exception:
            pass
    self.tmp_proxy_file = None
    self.is_proxy_active = False
    self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)

    # Сбрасываем визуальные границы/обзор волны СРАЗУ при загрузке нового
    # файла — иначе красная/зелёная полоски (и окно обзора) оставались от
    # предыдущего файла, пока не догрузится новая волна.
    self.current_in = 0.0
    self.current_out = 0.0
    if getattr(self, "is_still_image", False):
        # Возврат к обычному медиа — восстанавливаем подпись кнопки экспорта.
        try:
            self.btn_cut.setText("Обрезать")
            self.btn_cut.setIcon(_api.get_icon('fa5s.cut', color='#1e1e2e'))
        except Exception:
            pass
    self.is_still_image = False   # сбрасываем; _load_still_image выставит заново
    # Сбрасываем пикселизацию при загрузке ЛЮБОГО файла — эффект НЕ должен
    # тянуться с прошлого клипа (иначе следующий экспорт молча пикселит, хотя
    # на этом файле его «не включали»). Каждый файл начинается чистым.
    self._pixelize_active = False
    _pb = getattr(self, "btn_pixelize", None)
    if _pb is not None and _pb.isChecked():
        _pb.blockSignals(True); _pb.setChecked(False); _pb.blockSignals(False)
    self._sync_pixelize_icon()
    # Наложенные картинки — тоже строго «на файл»: следующий клип начинается
    # без чужих слоёв (иначе экспорт молча вшил бы логотип с прошлого видео).
    self._clear_image_overlays()
    self.waveform.reset_markers()
    # …и «часы кадра» холста: pts последнего показанного кадра принадлежит
    # ПРОШЛОМУ файлу. Без сброса метка времени/жёлтая полоска нового файла
    # вставали по чужому времени (у аудиофайла с обложкой кадров нет вовсе —
    # полоска намертво прилипала к концу волны, а «обрезать старт до
    # плейхеда» ставило IN/OUT в самый конец).
    if isinstance(self.video_widget, _api.VideoCanvas):
        self.video_widget.clear_frame()

    self.actual_source_file = _api.Path(path)
    self.filepath = self.actual_source_file

    # Источник кадров для превью полосы воспроизведения (берём из исходника).
    try:
        if getattr(self, "seek_preview", None) is not None:
            self.seek_preview.set_source(self.actual_source_file)
    except Exception:
        pass

    # Сбрасываем внешнюю озвучку и пере-сканируем внешние субтитры рядом
    # с новым файлом (в т.ч. в подпапках). Списки используются при построении
    # комбобоксов в finish_loading_file → _populate_track_combos.
    self._clear_external_audio()
    self._audio_ext = []
    self._sub_ext = self._scan_external_subs(self.actual_source_file)

    name = self.actual_source_file.name
    if len(name) > 30:
        name = "…" + name[-27:]
    self.lbl_file.setText(f"{_api.icon_html('fa5s.file', 14, _api.C['text'])}  {name}")
    self.lbl_file.setToolTip(str(self.actual_source_file))
    self.lbl_file.setStyleSheet(f"""
            color: {_api.C['text']};
            font-size: 11px;
            padding: 8px;
            background: {_api.C['surface3']};
            border: 1px solid {_api.C['border2']};
            border-radius: 6px;
        """)

    self.undo_stack = _api.deque(maxlen=50); self.redo_stack = _api.deque(maxlen=50)

    # Still-картинка (png/jpg/…) — отдельный лёгкий режим «картинка → видео»:
    # ни плеер, ни прокси, ни обрезка не применимы. Показываем кадр статично и
    # включаем только пикселизацию/кадрирование. Экспорт собирает видео из
    # картинки (-loop 1) при «Обрезать».
    _ext = _api.os.path.splitext(str(path))[1].lower()
    if _ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"):
        self._load_still_image()
        return

    self.waveform.set_loading("Ожидание метаданных...")

    metadata = _api.run_ffprobe(self.actual_source_file)
    if not metadata:
        _api.msgbox_critical(self, "Ошибка", "Не удалось получить метаданные (ffprobe недоступен).")
        self.waveform.set_data([], 0.0)
        return

    try:
        self.duration = float(metadata.get('format', {}).get('duration', 0.0))
        self.lbl_duration.setText(_api.s_to_time(self.duration))
    except Exception:
        self.duration = 0.0; self.lbl_duration.setText("—")
    self._update_total_time()
    # Даём волне длительность СРАЗУ (не дожидаясь построения семплов) — иначе
    # клик по полосе во время «Создание превью…»/«Загрузка волны…» сикал в 0.
    self.waveform.prime_duration(self.duration)

    vinfo, ainfo = self._pick_av_streams(metadata.get('streams', []))

    # Все аудио- и субтитровые дорожки контейнера (для выбора в боковой панели)
    self._audio_streams = [s for s in metadata.get('streams', [])
                           if s.get('codec_type') == 'audio']
    self._sub_streams = [s for s in metadata.get('streams', [])
                         if s.get('codec_type') == 'subtitle']

    if vinfo:
        self.video_stream_index = vinfo.get('index')
        is_av1 = vinfo.get('codec_name', '').lower() == 'av1'
        self._source_is_av1 = is_av1
        # Размер/FPS источника нужны для «оптимизации» превью-прокси (см.
        # _proxy_scale_for) — сохраняем, чтобы ими же пользовалась смена качества.
        try: self._src_video_h = int(vinfo.get('height') or 0)
        except Exception: self._src_video_h = 0
        self._src_video_fps = self._parse_fps(vinfo)
        scale = self._proxy_scale_for(is_av1)
        # Прокси нужен если: исходник AV1 (QtMultimedia его не тянет плавно), ИЛИ
        # выбрано пониженное качество, ИЛИ тяжёлый источник ужат под painted-режим.
        if is_av1 or scale < 0.999:
            self.create_proxy_for_preview(vinfo, ainfo, scale=scale, is_av1=is_av1); return
        self.finish_loading_file(vinfo, ainfo)
    else:
        self.finish_loading_file(None, ainfo)

def _load_still_image(self):
    """Лёгкий режим «картинка → видео»: грузим still-картинку, показываем её
        статично на холсте и включаем только пикселизацию/кадрирование. Плеер,
        прокси, волна и обрезка видео не задействованы — экспорт собирает ролик из
        картинки (-loop 1) в _export_still_pixelize."""
    path = self.actual_source_file
    # Останавливаем плеер и снимаем источник, чтобы он не держал прошлый файл.
    try: self.player.stop()
    except Exception: pass
    try: self.player.setSource(_api.QUrl())
    except Exception: pass

    img = _api.QImage(str(path))
    if img.isNull():
        _api.msgbox_critical(self, "Ошибка", "Не удалось открыть картинку.")
        return
    self.is_still_image = True
    self.still_image_path = _api.Path(path)
    self._still_w, self._still_h = img.width(), img.height()
    self.video_stream_index = None     # видеопотока-для-плеера нет
    self.audio_stream_index = None
    self._audio_streams = []; self._sub_streams = []
    self._source_is_av1 = False

    # Синтетическая длительность будущего ролика (правится в диалоге пикселизации).
    self.duration = float(self._still_duration)
    self.current_in = 0.0
    self.current_out = self.duration
    try:
        self.lbl_duration.setText(_api.s_to_time(self.duration))
        self._update_total_time()
    except Exception:
        pass

    # Показываем картинку статично; волну заменяем подсказкой.
    vw = getattr(self, "video_widget", None)
    if isinstance(vw, _api.VideoCanvas):
        vw.set_static_image(img)
    try:
        self.waveform.set_data([], 0.0)
        self.waveform.set_loading(
            f"Картинка {self._still_w}×{self._still_h} — включите «Пикселизацию» "
            f"и нажмите «Обрезать», чтобы сделать видео-проявление",
            animated=False)
    except Exception:
        pass

    # Плеер для картинки не нужен — играть нечего.
    try: self.btn_play.setEnabled(False)
    except Exception: pass
    try:
        self.btn_cut.setEnabled(True)
        self.btn_cut.setText("Создать видео")
        self.btn_cut.setIcon(_api.get_icon('fa5s.film', color='#1e1e2e'))
    except Exception:
        pass
    self._report_progress(0, "")
    self.log_label.setText(
        _api.icon_html('fa5s.image', 12, _api.C['text2'])
        + " Картинка загружена — включите «Пикселизацию»")
    self.log_label.setStyleSheet(f"color: {_api.C['text2']}; font-size: 12px;")
    self._update_media_buttons()

def _pb_quality_scale(self):
    """Коэффициент масштаба прокси для текущего «качества воспроизведения».
        0 → Полное (без прокси по этой причине), 1 → 1/2, 2 → 1/4."""
    try:
        return {0: 1.0, 1: 0.5, 2: 0.25}.get(self.cmb_pb_quality.currentIndex(), 1.0)
    except Exception:
        return 1.0

@staticmethod
def _pick_av_streams(streams):
    """(видеопоток, аудиопоток) для плеера — первые подходящие из ffprobe.

        Обложки (attached_pic) видеопотоком НЕ считаются: см. _is_attached_pic.
        Чистая функция."""
    vinfo = None; ainfo = None
    for s in streams or []:
        if (s.get('codec_type') == 'video' and vinfo is None
                and not _api._is_attached_pic(s)):
            vinfo = s
        if s.get('codec_type') == 'audio' and ainfo is None:
            ainfo = s
    return vinfo, ainfo

@staticmethod
def _parse_fps(vinfo):
    """FPS видеодорожки из ffprobe-словаря ('avg_frame_rate'/'r_frame_rate'
        вида 'num/den'). 0.0 — если неизвестно."""
    for key in ('avg_frame_rate', 'r_frame_rate'):
        val = (vinfo or {}).get(key) or ''
        try:
            if '/' in str(val):
                num, den = str(val).split('/', 1)
                den = float(den)
                if den:
                    f = float(num) / den
                    if f > 0:
                        return f
            elif val:
                return float(val)
        except Exception:
            pass
    return 0.0

def _proxy_scale_for(self, is_av1):
    """Масштаб превью-прокси. По умолчанию прокси НЕ строится вообще — плеер
        играет оригинал напрямую. Исключение — исходники, которые QtMultimedia не
        тянет напрямую (сейчас это AV1): для них прокси обязателен (конвертация в
        H.264), и заодно даунскейлим его под painted-режим (VideoCanvas.toImage()
        дешевле на уменьшенном кадре — иначе на 1080p60 воспроизведение проседает
        до слайд-шоу). Обычные «тяжёлые, но поддерживаемые» источники (1080p60,
        2K/4K H.264/VP9 и т.п.) больше НЕ ужимаются автоматически — это осознанный
        выбор пользователя (жалоба на потерю качества по умолчанию), доступен через
        ручной выбор «1/2»/«1/4» в «Качество воспроизведения»."""
    user = self._pb_quality_scale()          # 1.0 / 0.5 / 0.25
    src_h = int(getattr(self, '_src_video_h', 0) or 0)
    fps = float(getattr(self, '_src_video_fps', 0.0) or 0.0)
    # 60 fps = вдвое больше кадров/с (вдвое больше toImage) → целимся в 540p,
    # иначе 720p (чуть чётче, кадров меньше).
    target = 540 if fps >= 49 else 720
    cap = 1.0
    if is_av1 and src_h > target:
        cap = target / float(src_h)
    return min(user, cap)

def _proxy_limit_sec(self):
    """Сколько секунд исходника класть в прокси (0 = весь файл).
        Берётся из спина «Минут для прокси» в правой панели."""
    try:
        return float(self.spin_proxy_min.value()) * 60.0
    except Exception:
        return 0.0
