# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: загрузка файла, прокси для просмотра, плеер и полный экран."""
import edit_tab as _api


class EditTabPlaybackMixin:
    """Монтаж: загрузка файла, прокси для просмотра, плеер и полный экран."""

    # ── File loading ──────────────────────────────────────────────────────
    def open_file(self):
        fname, _ = _api.QFileDialog.getOpenFileName(
            self, "Открыть медиа файл", "",
            "Медиа файлы (*.mp4 *.mkv *.mov *.avi *.mp3 *.aac *.wav *.flac "
            "*.png *.jpg *.jpeg *.bmp *.webp *.gif);;Все файлы (*)")
        if fname:
            self.load_file(fname)

    def clear_file(self):
        """Убирает текущий файл и возвращает редактор в исходное «пустое»
        состояние (как при запуске без файла): останавливает плеер и фоновые
        воркеры, чистит временный proxy, сбрасывает инфо/волну/тайминги."""
        # Снимок для отмены «Очистить» через Ctrl+Z: файл + текущая обрезка.
        if self.filepath:
            self._cleared_snapshot = {
                'path': str(self.filepath),
                'in': self.current_in,
                'out': self.current_out,
            }
        # Останавливаем воспроизведение.
        try:
            self.player.stop()
        except Exception:
            pass
        # Воркер волны + его временный wav.
        if self.audio_worker and self.audio_worker.isRunning():
            self.audio_worker.stop(); self.audio_worker.wait()
        if self.audio_worker:
            try:
                if self.audio_worker.tmp_wav and _api.os.path.exists(self.audio_worker.tmp_wav):
                    _api.os.remove(self.audio_worker.tmp_wav)
            except Exception:
                pass
            self.audio_worker = None
        # Воркер быстрого предпросмотра волны выделения (см. _start_waveform).
        if self._audio_partial_worker and self._audio_partial_worker.isRunning():
            self._audio_partial_worker.stop(); self._audio_partial_worker.wait()
        if self._audio_partial_worker:
            try:
                if self._audio_partial_worker.tmp_wav and _api.os.path.exists(self._audio_partial_worker.tmp_wav):
                    _api.os.remove(self._audio_partial_worker.tmp_wav)
            except Exception:
                pass
            self._audio_partial_worker = None
        # Proxy-воркер + его временный файл.
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
        # Выгружаем источник из плеера.
        try:
            self.player.setSource(_api.QUrl())
        except Exception:
            pass
        # Очищаем последний кадр на холсте (frame-режим).
        if isinstance(self.video_widget, _api.VideoCanvas):
            self.video_widget.clear_frame()
        # …и отпускаем покадровый слой: буфер кадров прошлого файла больше не
        # нужен, а его ffmpeg нельзя оставлять работать по удалённому источнику.
        self._grid = _api.FrameGrid(0.0, 0.0)
        self._frame_idx = None
        if getattr(self, '_frames', None) is not None:
            self._frames.set_source(None)
        self._frames_src = None

        # Сбрасываем субтитры.
        self._stop_sub_extractor()
        self._stop_ass()
        self._sub_cues = []
        self._sub_use_overlay = False
        self._hide_sub_display()

        # Сбрасываем состояние.
        self.filepath = None
        self.actual_source_file = None
        self.duration = 0.0
        self.current_in = 0.0
        self.current_out = 0.0
        self.fps = None
        self.video_aspect = None
        self.video_stream_index = None
        self.audio_stream_index = None
        # Сбрасываем режим картинки и возвращаем подпись кнопки экспорта.
        if getattr(self, "is_still_image", False):
            try:
                self.btn_cut.setText("Обрезать")
                self.btn_cut.setIcon(_api.get_icon('fa5s.cut', color='#1e1e2e'))
            except Exception:
                pass
        self.is_still_image = False
        self.still_image_path = None
        # Снимаем пикселизацию вместе с очисткой файла.
        self._pixelize_active = False
        _pb = getattr(self, "btn_pixelize", None)
        if _pb is not None and _pb.isChecked():
            _pb.blockSignals(True); _pb.setChecked(False); _pb.blockSignals(False)
        self._sync_pixelize_icon()
        # Наложенные картинки — тоже строго «на файл»: следующий клип начинается
        # без чужих слоёв (иначе экспорт молча вшил бы логотип с прошлого видео).
        self._clear_image_overlays()
        self.selected_audio_abs_index = None
        self._clear_external_audio()
        self._set_audio_disabled(False)
        self._audio_streams = []
        self._sub_streams = []
        self._audio_ext = []
        self._sub_ext = []
        self.selected_audio_ext_path = None
        self.selected_sub_ext_path = None
        self.undo_stack.clear(); self.redo_stack.clear()

        # Инфо-карточка → прочерки.
        for lbl in (self.lbl_duration, self.lbl_fps, self.lbl_vstream,
                    self.lbl_astream, self.lbl_abitrate):
            lbl.setText("—")

        # Подпись файла → исходный «пустой» вид (пунктирная рамка).
        self.lbl_file.setText("Нет файла")
        self.lbl_file.setToolTip("")
        self.lbl_file.setStyleSheet(f"""
            color: {_api.C['text3']};
            font-size: 11px;
            padding: 8px;
            background: {_api.C['surface2']};
            border: 1px dashed {_api.C['border2']};
            border-radius: 6px;
        """)

        # Плашка proxy / строка лога.
        self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
        try:
            self.log_label.setText(""); self.log_label.setVisible(False)
        except Exception:
            pass

        # Дорожки (с пустыми списками → «— нет —» / «Выкл»).
        self._populate_track_combos()
        self._update_media_buttons()
        self._update_audio_only_placeholder()

        # Поля IN/OUT + кадры + позиция плеера.
        self.in_time_edit.setText(_api.s_to_time(0.0))
        self.out_time_edit.setText(_api.s_to_time(0.0))
        self._set_frame_spins(0.0, 0.0)
        lbl_cur = getattr(self, "lbl_current_time", None)
        if lbl_cur is not None:
            lbl_cur.setText(_api.s_to_time(0.0))
        try:
            self.slider.blockSignals(True); self.slider.setValue(0); self.slider.blockSignals(False)
        except Exception:
            pass

        # Волна → пустое состояние с подсказкой «Перетащите видео…».
        self.waveform.set_data([], 0.0)
        self._update_total_time()
        self.update_selection_label()

    def accept_dropped_paths(self, paths):
        """Бросок файла на заголовок вкладки «Монтаж» (см. main.eventFilter):
        грузим первый существующий файл в редактор, как обычный drop в окно."""
        for p in (paths or []):
            if p and _api.os.path.exists(p):
                self.load_file(p)
                break

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

    def create_proxy_for_preview(self, vinfo, ainfo=None, scale=1.0, is_av1=False):
        if scale < 0.999 and is_av1:
            self.log_label.setText("Подготовка превью (AV1, пониженное качество)...")
        elif scale < 0.999:
            self.log_label.setText("Подготовка превью (пониженное качество)...")
        else:
            self.log_label.setText("Подготовка AV1...")
        self._report_progress(0, "Подготовка превью…")
        self.btn_play.setEnabled(False); self.btn_cut.setEnabled(False)
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        tf.close(); self.tmp_proxy_file = tf.name
        self.proxy_thread = _api.ProxyWorker(self.actual_source_file, self.tmp_proxy_file,
                                        scale=scale, duration=getattr(self, 'duration', 0.0),
                                        limit_sec=self._proxy_limit_sec())
        self._proxy_is_av1 = is_av1; self._proxy_scale = scale
        self._proxy_partial = self._proxy_limit_sec() > 0
        # Проценты создания прокси — в волну, рядом с «Ожидание метаданных…»
        # (так же, как «Извлечение аудио… N%» для H.264).
        self.proxy_thread.progress.connect(self.waveform.set_loading)
        self.proxy_thread.finished.connect(lambda s, m, o: self.on_proxy_ready(s, m, o, vinfo, ainfo))
        self.proxy_thread.start()

    def on_proxy_ready(self, success, msg, output_path, vinfo, ainfo):
        self.btn_play.setEnabled(True); self.btn_cut.setEnabled(True)
        self._report_progress(100); self.log_label.setText("Готово")
        # Файл очистили, пока строился прокси — не оживляем UI удалённым файлом.
        if self.actual_source_file is None:
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            return

        if success:
            self.is_proxy_active = True
            self.filepath = _api.Path(output_path)
            scale = getattr(self, '_proxy_scale', 1.0)
            is_av1 = getattr(self, '_proxy_is_av1', False)
            q_txt = {0.5: " 1/2", 0.25: " 1/4"}.get(scale, "")
            if is_av1 and q_txt:
                badge = f" ПРЕВЬЮ РЕЖИМ (AV1 → H.264,{q_txt.strip()})"
            elif is_av1:
                badge = " ПРЕВЬЮ РЕЖИМ (AV1 → H.264)"
            else:
                badge = f" ПРЕВЬЮ РЕЖИМ (качество{q_txt})"
            lim = self._proxy_limit_sec()
            if lim > 0:
                badge += f" · первые {int(round(lim / 60))} мин"
            self.lbl_proxy.setText(_api.icon_html('fa5s.bolt', 13, _api.C['yellow']) + badge)
            self.lbl_proxy.setVisible(True)
        elif msg != "Отменено":
            _api.msgbox_warning(self, "Ошибка прокси", f"Не удалось создать превью: {msg}")
        # «Аудио»/«Битрейт аудио» должны показывать РЕАЛЬНЫЙ кодек исходника (напр.
        # Opus), а не превью-прокси — прокси ВСЕГДА транскодирует звук в AAC (см.
        # ProxyWorker.run, -c:a aac) ради совместимости с QtMultimedia, поэтому
        # ainfo здесь — тот же объект, что пришёл из ffprobe исходника в load_file
        # (передан через create_proxy_for_preview), а не повторный probe self.filepath.
        self.finish_loading_file(vinfo, ainfo)

    def _on_pb_quality_changed(self, _idx=None):
        """Смена «качества воспроизведения» на лету: пересобираем прокси (или
        возвращаемся к оригиналу), сохраняя позицию и состояние плеера. На экспорт
        не влияет — он всегда из self.actual_source_file."""
        src = self.actual_source_file
        if not src or not _api.os.path.exists(str(src)):
            return
        if getattr(self, 'video_stream_index', None) is None:
            return  # без видеодорожки качество воспроизведения не применимо
        # Если прокси уже строится — отменяем, начнём заново с новым качеством.
        if self.proxy_thread and self.proxy_thread.isRunning():
            self.proxy_thread.stop(); self.proxy_thread.wait()
        try: pos = int(self.player.position())
        except Exception: pos = 0
        try:
            was_playing = (self.player.playbackState()
                           == _api.QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            was_playing = False
        self._pb_restore = (pos, was_playing)

        is_av1 = bool(getattr(self, '_source_is_av1', False))
        scale = self._proxy_scale_for(is_av1)
        need_proxy = is_av1 or scale < 0.999

        # Освобождаем плеер от старого прокси-файла (иначе Windows его не отдаст),
        # затем удаляем временный файл.
        try: self.player.stop()
        except Exception: pass
        try: self.player.setSource(_api.QUrl())
        except Exception: pass
        old_proxy = self.tmp_proxy_file
        self.tmp_proxy_file = None
        self.is_proxy_active = False
        if old_proxy and _api.os.path.exists(old_proxy):
            try: _api.os.remove(old_proxy)
            except Exception: pass

        if need_proxy:
            self.log_label.setText("Смена качества предпросмотра…")
            self._report_progress(0, "Качество предпросмотра…")
            self.btn_play.setEnabled(False); self.btn_cut.setEnabled(False)
            tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".mp4"); tf.close()
            self.tmp_proxy_file = tf.name
            self._proxy_is_av1 = is_av1; self._proxy_scale = scale
            self.proxy_thread = _api.ProxyWorker(src, self.tmp_proxy_file, scale=scale,
                                            duration=getattr(self, 'duration', 0.0),
                                            limit_sec=self._proxy_limit_sec())
            self._proxy_partial = self._proxy_limit_sec() > 0
            # Здесь волна уже заполнена — set_loading её стёр бы; показываем
            # прогресс создания прокси в строке лога И в общем прогрессбаре окна.
            self.proxy_thread.progress.connect(self._on_pb_proxy_progress)
            self.proxy_thread.finished.connect(self._on_pb_proxy_ready)
            self.proxy_thread.start()
        else:
            # Полное качество и не-AV1 → играем оригинал.
            self._proxy_partial = False
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            self._swap_player_source(src)

    def _on_pb_proxy_progress(self, text):
        """Прогресс пересборки прокси при смене версии качества: пишем и в строку
        лога, и в общий прогрессбар окна (вытаскиваем проценты из «…N%»)."""
        self.log_label.setText(text)
        pct = None
        if '%' in text:
            try:
                pct = int(text.rsplit('%', 1)[0].split()[-1])
            except Exception:
                pct = None
        self._report_progress(pct if pct is not None else -1,
                              text or "Создание превью…")

    def _on_pb_proxy_ready(self, success, msg, output_path):
        self.btn_play.setEnabled(True); self.btn_cut.setEnabled(True)
        self._report_progress(100); self.log_label.setText("Готово")
        # Источник могли очистить, пока строился прокси (его finished-слот в этом
        # случае приходит уже после очистки) — показывать/переключать нечего.
        if self.actual_source_file is None:
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            return
        if success and output_path and _api.os.path.exists(output_path):
            self.is_proxy_active = True
            scale = getattr(self, '_proxy_scale', 1.0)
            is_av1 = getattr(self, '_proxy_is_av1', False)
            q_txt = {0.5: "1/2", 0.25: "1/4"}.get(scale, "")
            if is_av1 and q_txt:
                badge = f" ПРЕВЬЮ РЕЖИМ (AV1 → H.264, {q_txt})"
            elif is_av1:
                badge = " ПРЕВЬЮ РЕЖИМ (AV1 → H.264)"
            else:
                badge = f" ПРЕВЬЮ РЕЖИМ (качество {q_txt})"
            lim = self._proxy_limit_sec()
            if lim > 0:
                badge += f" · первые {int(round(lim / 60))} мин"
            self.lbl_proxy.setText(_api.icon_html('fa5s.bolt', 13, _api.C['yellow']) + badge)
            self.lbl_proxy.setVisible(True)
            self._swap_player_source(output_path)
        else:
            if msg != "Отменено":
                _api.msgbox_warning(self, "Ошибка прокси",
                                    f"Не удалось создать превью: {msg}")
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            self._swap_player_source(self.actual_source_file)

    def _swap_player_source(self, path):
        """Переключает источник плеера, сохраняя позицию/состояние из _pb_restore
        (применяются после загрузки медиа в on_media_status_changed)."""
        if path is None:
            return  # файл очистили — переключать нечего
        self.filepath = _api.Path(path)
        self._pending_pb_seek = getattr(self, '_pb_restore', None)
        self._set_player_file(path)
        # Точные кадры обязаны браться из ТОГО ЖЕ файла, что играет плеер:
        # иначе после смены качества превью стоп-кадр остался бы от прежнего
        # источника (другое разрешение — заметный «скачок» резкости на паузе).
        self._frames_set_source()

    def _set_player_file(self, path):
        """Грузит файл в плеер через девайс с FILE_SHARE_DELETE — тогда исходник
        можно удалить из Проводника прямо во время монтажа (плеер его не держит
        намертво). Если девайс открыть не удалось — обычная загрузка по URL."""
        path = str(path)
        old = getattr(self, '_play_device', None)
        dev = _api.ShareDeleteIODevice(path)
        opened = False
        try:
            opened = dev.open()
        except Exception:
            opened = False
        try:
            if opened:
                self._play_device = dev
                self.player.setSourceDevice(dev, _api.QUrl.fromLocalFile(path))
            else:
                self._play_device = None
                self.player.setSource(_api.QUrl.fromLocalFile(path))
        except Exception:
            self._play_device = None
            try:
                self.player.setSource(_api.QUrl.fromLocalFile(path))
            except Exception:
                pass
        # Старый девайс закрываем чуть позже — плеер уже переключился на новый.
        if old is not None and old is not dev:
            _api.QTimer.singleShot(0, lambda d=old: self._close_play_device(d))

    def _close_play_device(self, dev):
        try:
            dev.close()
        except Exception:
            pass

    def finish_loading_file(self, vinfo, ainfo):
        if vinfo:
            r = vinfo.get('r_frame_rate') or vinfo.get('avg_frame_rate') or "0/1"
            try:
                num, den = r.split('/')
                fps = float(num) / float(den) if float(den) != 0 else 0.0
                self.fps = fps if fps > 0 else None
            except Exception:
                self.fps = None
            w = vinfo.get('width', '?'); h = vinfo.get('height', '?')
            codec = vinfo.get('codec_name', '?').upper()
            self.lbl_vstream.setText(f"{codec} {w}×{h}")
            try:
                wv = int(vinfo.get('width') or 0); hv = int(vinfo.get('height') or 0)
                self.video_aspect = (wv / hv) if (wv > 0 and hv > 0) else None
            except Exception:
                self.video_aspect = None
        else:
            self.video_stream_index = None; self.fps = None
            self.video_aspect = None
            self.lbl_vstream.setText("—")

        if ainfo:
            self.audio_stream_index = ainfo.get('index')
            codec_a = ainfo.get('codec_name', '?').upper()
            self.lbl_astream.setText(f"{codec_a} {_api._fmt_channels(ainfo)}")
            self.lbl_abitrate.setText(self._fmt_bitrate(ainfo))
        else:
            self.audio_stream_index = None
            self.lbl_astream.setText("—")
            self.lbl_abitrate.setText("—")

        self._populate_track_combos()
        self._update_media_buttons()
        self._update_audio_only_placeholder()
        self.lbl_fps.setText(_api.format_fps(self.fps))
        # Покадровый слой перенастраиваем на новый клип: сетка кадров (fps +
        # длительность) и источник точных кадров — ТОТ ЖЕ файл, что уйдёт в
        # плеер (оригинал или превью-прокси, см. _frames_set_source).
        self._refresh_frame_grid()
        self._frame_idx = 0
        self._frames_set_source()

        self.undo_stack.clear(); self.redo_stack.clear()
        self.current_in = 0.0; self.current_out = max(0.001, self.duration)
        self.set_in_out(0.0, self.current_out, skip_undo=True)

        # Новый файл — сбрасываем зум/панораму превью (если активен холст-режим)
        # и снимаем предпросмотр привязки: он посчитан по ПРОШЛОМУ видео.
        if isinstance(self.video_widget, _api.VideoCanvas):
            self.video_widget.reset_view()
            self._clear_track_preview()

        self._set_player_file(self.filepath)
        self.player.setPosition(0); self.player.pause()

        self.start_waveform_loading()
        _api.QTimer.singleShot(50, self._adjust_video_aspect_once)
        self.update_selection_label(); self.update_pan_slider_values()
        # После загрузки файла (в т.ч. через drag&drop) забираем фокус клавиатуры
        # на вкладку, чтобы Пробел/I/O/←→ работали сразу — без клика по видео.
        # singleShot(0): после того, как плеер/видеовиджет отработают своё событие.
        _api.QTimer.singleShot(0, self._grab_kbd_focus)
        # Прогреваем отдельный плеер скраб-звука заранее (источник — оригинал).
        # Без прогрева ПЕРВЫЕ покадровые шаги часто шли без звука: плеер ещё
        # догружал медиа (а у AV1+Opus оригинала открытие/перемотка не мгновенны)
        # — отсюда баг «при av1 прокси звук при шаге по кадру появляется не всегда».
        _api.QTimer.singleShot(0, self._prime_scrub_audio)

    def _prime_scrub_audio(self):
        """Заранее декодирует окно PCM вокруг текущей точки, чтобы ПЕРВЫЙ же
        покадровый шаг звучал сразу (окно готовится ~80 мс — на первом шаге это
        было бы слышно как «звук появляется не всегда»). Только подготовка —
        ничего не играем (тишина при загрузке файла)."""
        if not getattr(self, "_scrub_audio_enabled", True):
            return
        try:
            eng = self._sync_scrub_audio_source()
            if eng is not None:
                eng.request(max(0.0, self.player.position() / 1000.0))
            self._scrub_sink()          # поднять устройство заранее (~45 мс)
        except Exception:
            pass

    # ── Playback ──────────────────────────────────────────────────────────
    def on_player_duration_changed(self, dur_ms):
        if dur_ms <= 0:
            return
        # Усечённый прокси (первые N минут) короче оригинала — НЕ даём его
        # длительности перетереть настоящую, иначе таймлайн/обрезка схлопнутся
        # до длины прокси (а резать-то надо весь файл). Истинную длительность
        # держим из ffprobe (load_file).
        if getattr(self, 'is_proxy_active', False) and getattr(self, '_proxy_partial', False):
            return
        new_dur = dur_ms / 1000.0
        # Выделение покрывало весь клип? Тогда тянем OUT к настоящей длительности.
        was_full = (self.current_out <= 0.001) or abs(self.current_out - self.duration) < 0.05
        self.duration = new_dur
        self.lbl_duration.setText(_api.s_to_time(self.duration))
        self._update_total_time()
        # Синхронизируем current_out / waveform.out_s с новой длительностью (баг #4).
        self._refresh_frame_grid()   # у сетки кадров новый предел
        new_out = new_dur if was_full else min(self.current_out, new_dur)
        new_in  = min(self.current_in, max(0.0, new_out - 0.001))
        if abs(new_out - self.current_out) > 1e-4 or abs(new_in - self.current_in) > 1e-4:
            self.set_in_out(new_in, new_out, skip_undo=True)

    def _update_seg_duration(self, pos_s=None):
        """Обновляет метку «старт→плейхед»: длительность от IN до жёлтой полосы
        воспроизведения. Зовётся отовсюду, где двигается плейхед или меняется IN."""
        lbl = getattr(self, "lbl_seg_dur", None)
        if lbl is None:
            return
        try:
            if pos_s is None:
                pos_s = self.player.position() / 1000.0
            lbl.setText(_api.s_to_time(max(0.0, pos_s - self.current_in)))
        except Exception:
            pass

    def on_position_changed(self, pos_ms):
        self._preroll_watch(pos_ms)        # см. _preroll_at (прогрев с разбега)
        if not getattr(self, "_prerolling", False):
            # Во время разбега позиция пробегает мимо любых целей покадрового
            # seek'а — «подтверждать» ими чужой seek нельзя.
            self._confirm_frame_seek(pos_ms)   # см. step_frame/_dispatch_frame_seek
        # Интерфейс — по мастер-часам (кадр на экране), а не по «сырой» позиции
        # плеера: иначе метка и картинка живут каждая своей жизнью, что и было
        # видно как рассинхрон метки с видео. Для аудиофайлов _clock_pos_s сам
        # возвращает позицию плеера.
        pinned_ms = self._ui_pinned_ms()
        pos_s = (pinned_ms / 1000.0) if pinned_ms is not None else self._clock_pos_s()
        self._paint_playhead(pos_s)
        self._update_meter(pos_s)
        self._update_subtitle(pos_s)

    def _update_meter(self, pos_s, force=False):
        """Кормит индикатор уровня значением аудиоволны на позиции плейхеда.
        При воспроизведении вызывается из sync_ui; `force=True` — при покадровой
        перемотке (скрабе), чтобы шкала «оживала» и на шаге, а не только на play.
        На паузе без force шкала плавно опадает сама."""
        meter = getattr(self, "audio_meter", None)
        if meter is None:
            return
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState)
            if not playing and not force:
                return
            # level_at_lr уже нормирован по пику и перцептивен (см. WaveformWidget),
            # поэтому шкала живая и отражает реальное присутствие звука. L и R —
            # честно раздельные каналы (для моно совпадут).
            lvl_l, lvl_r = self.waveform.level_at_lr(pos_s)
            try:
                vol = max(0.0, min(1.0, float(self.audio_output.volume())))
            except Exception:
                vol = 1.0
            k = 0.25 + 0.75 * vol
            meter.set_levels(min(1.0, lvl_l * k), min(1.0, lvl_r * k))
        except Exception:
            pass

    def _effective_out_s(self):
        """Граница авто-паузы воспроизведения. Если OUT у самого конца клипа —
        останавливаемся на кадр раньше: иначе плеер доходит до EndOfMedia и
        QtMultimedia гасит поверхность в чёрный кадр (баг #9)."""
        frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
        guard = max(frame_s, 0.05)
        at_end = self.current_out >= (self.duration - 0.02)
        return (self.duration - guard) if at_end else self.current_out

    def _set_play_bound(self, active):
        """Вкл/выкл блокировку кадров за OUT в painted-режиме (анти-overshoot)."""
        vw = self.video_widget
        if not isinstance(vw, _api.VideoCanvas):
            return
        if active and self.duration > 0:
            frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
            # граница = effective_out + полкадра: кадр НА границе ещё показываем,
            # а следующий (за ней) — блокируем и встаём на паузу.
            vw.set_play_bound(self._effective_out_s() + frame_s * 0.5)
        else:
            vw.set_play_bound(None)

    def _on_play_boundary(self):
        """Пришёл кадр за OUT (по PTS) — мгновенная пауза и снап на границу ДО
        показа кадра. Убирает проскок-и-отскок правой границы."""
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            out_s = self._effective_out_s()
            # Кадр остановки задаём явно: иначе пауза «пришпилила» бы последний
            # ПОКАЗАННЫЙ кадр, и метка отскочила бы от границы на кадр назад.
            if self._grid.valid:
                self._frame_idx = self._grid.index_at(out_s)
            self.player.setPosition(int(out_s * 1000))
            self.lbl_current_time.setText(_api.s_to_time(out_s))
            self.waveform.set_playhead(out_s)
            self._ext_audio_seek(int(out_s * 1000))
        except Exception:
            pass

    def sync_ui(self):
        if self.duration <= 0.1:
            return
        # Часы плеера (по сути аудио-часы) — ими проверяем границу OUT: она
        # обязана срабатывать по звуку, даже если видеокадры отстают.
        pos_s = self.player.position() / 1000.0
        # А интерфейс (метка времени, полоса, плейхед на волне, субтитры) ведём
        # по МАСТЕР-ЧАСАМ — времени кадра, который сейчас на экране. Пока плеер
        # занят служебным делом (разбег, транзиентный play скраба), часы стоят
        # на отметке пользователя — см. _ui_pinned_ms.
        pinned_ms = self._ui_pinned_ms()
        disp_s = (pinned_ms / 1000.0) if pinned_ms is not None else self._clock_pos_s()
        # Авто-пауза в конце воспроизводимого участка (резерв к покадровому
        # блоку VideoCanvas: ловит границу в overlay-режиме и как страховка).
        effective_out = self._effective_out_s()
        if effective_out > self.current_in and pos_s >= effective_out:
            self.player.pause()
            if self._grid.valid:
                self._frame_idx = self._grid.index_at(effective_out)
            self.player.setPosition(int(effective_out * 1000))
            self.lbl_current_time.setText(_api.s_to_time(effective_out))
            self.waveform.set_playhead(effective_out)
            self._update_seg_duration(effective_out)
            return
        self._paint_playhead(disp_s)
        self._update_meter(disp_s)
        self._update_subtitle(disp_s)
        # Рассинхрон внешней озвучки. Порог опущен с 220 до 130 мс: 220 мс — это
        # уже отчётливо слышимое «эхо» относительно картинки (заметно от ~40 мс),
        # а ниже сотни ставить нельзя — каждая правка это setPosition, то есть
        # микро-заминка в звуке. Сверяемся с ЧАСАМИ ПЛЕЕРА (звук к звуку), а не с
        # часами кадра: рассинхрон двух звуковых дорожек между собой слышен, а
        # отставание рендера видео к нему отношения не имеет.
        if self._ext_audio_active and self._ext_audio_player is not None:
            try:
                if (self._ext_audio_player.playbackState()
                        == _api.QMediaPlayer.PlaybackState.PlayingState):
                    drift = self._ext_audio_player.position() - self.player.position()
                    if abs(drift) > 130:
                        self._ext_audio_player.setPosition(self.player.position())
            except Exception:
                pass

    def on_slider_moved(self, value):
        if self.duration > 0:
            self.seek_to((value / 1000.0) * self.duration)

    def seek_to(self, t_s):
        try:
            ms = int(max(0.0, min(t_s, max(0.0, self.duration))) * 1000)
            # Идёт беззвучный разбег — гасим его ПЕРВЫМ делом. Иначе плеер
            # продолжил бы играть уже от новой отметки и уехал бы с неё.
            if getattr(self, "_prerolling", False):
                self._preroll_cancel()
            # Отложенная цель покадровой серии устарела — позицию ставим здесь.
            self._frame_seek_deferred_ms = None
            if isinstance(self.video_widget, _api.VideoCanvas):
                self.video_widget.set_scrub_active(True)
                self._scrub_idle_timer.start()   # перезапуск — «перемотка ещё идёт»
            # Целевой кадр запоминаем сразу: от него пойдёт покадровый шаг.
            # Пин ПЕРЕВОДИМ на новый кадр тут же — без этого холст продолжал бы
            # считать «своим» кадр, где перемотка началась, и отбрасывал бы все
            # кадры плеера: картинка стояла бы всю протяжку. Точные кадры при
            # этом не заказываем (ffmpeg на каждый пиксель протяжки не нужен) —
            # но если нужный кадр уже лежит в буфере, показываем его мгновенно.
            if self._grid.valid:
                self._frame_idx = self._grid.index_at(ms / 1000.0)
                vw = getattr(self, "video_widget", None)
                if isinstance(vw, _api.VideoCanvas):
                    span = self._grid.pts_span_us(self._frame_idx)
                    vw.arm_frame_pin(span)
                    eng = getattr(self, "_frames", None)
                    img = eng.frame(self._frame_idx) if eng is not None else None
                    if img is not None:
                        vw.set_exact_frame(
                            img, span,
                            int(self._grid.start_of(self._frame_idx) * 1_000_000))
            self.player.setPosition(ms)
            self.waveform.set_playhead(t_s)
            self._ext_audio_seek(ms)
        except Exception as e:
            self.main.log(f"seek_to error: {e}")

    def _on_scrub_idle(self):
        """Перемотка утихла (seek_to не вызывался _scrub_idle_timer.interval() мс) —
        возвращаем сглаженную отрисовку кадра в VideoCanvas."""
        if isinstance(self.video_widget, _api.VideoCanvas):
            self.video_widget.set_scrub_active(False)
        prerolling = getattr(self, "_prerolling", False)
        playing = (self.player.playbackState()
                   == _api.QMediaPlayer.PlaybackState.PlayingState)
        if not playing or prerolling:
            # Перемотка кончилась — ставим на холст ТОЧНЫЙ кадр этой позиции и
            # набиваем буфер соседями, чтобы первый же шаг стрелкой был мгновенным.
            # Во время прогрева («с разбега») плеер формально играет, но кадр всё
            # равно наш: пин прячет пробегающие кадры разбега.
            self._show_exact_frame(self._frame_idx)
        if not playing:
            # Окно PCM для скраб-звука — в новой точке (первый шаг после клика
            # по шкале обязан звучать сразу, см. AudioScrubber).
            self._prime_scrub_audio()
            # Греем аудио-конвейер в новой точке, пока стоим на паузе: иначе
            # первое «Воспроизвести» после перемотки начиналось с ~0.35 с тишины
            # и докрутить обрезку по слуху было нельзя (см. _preroll_at).
            self._preroll_at(self._playhead_target_s())

    def toggle_play(self):
        self._scrubbing = False   # явное play/pause не должно гаситься скрабом
        # Возврат звука после разбега отложен на четверть секунды (хвост очереди
        # аудиоустройства, см. _restore_preroll_mute) — но ждать его нельзя:
        # воспроизведение, начатое в этом окне, было бы немым.
        self._flush_preroll_mute()
        # …и позиция: серия покадровых шагов могла закончиться этим самым нажатием,
        # а её итоговую точку плеер ещё не получил (см. _dispatch_frame_seek).
        self._flush_frame_seek()
        # Пользователь нажал Play в окне беззвучного прогрева: отменяем прогрев,
        # возвращаем mute и продолжаем уже как обычный запуск (плеер уже играет
        # под mute — достаточно снять mute, не дёргая позицию).
        if getattr(self, "_prerolling", False):
            self._prerolling = False
            tgt = getattr(self, "_preroll_target_ms", None)
            # Прогрев идёт «с разбега», то есть плеер сейчас может быть ЕЩЁ НЕ
            # доехавшим до отметки пользователя. Продолжить прямо отсюда значило
            # бы начать воспроизведение раньше плейхеда. Но и перематывать на
            # цель нельзя: перемотка кладёт аудио-конвейер, и звук появится
            # только через ~0.35 с (ровно тот баг, ради которого прогрев и
            # существует). Поэтому пока остаток разбега короткий — ДОИГРЫВАЕМ
            # его под mute и снимаем mute на цели (_preroll_handoff): и картинка
            # (пин точного кадра держится), и звук стартуют ровно на отметке.
            behind = 0
            try:
                behind = (int(tgt) - self.player.position()) if tgt is not None else 0
            except Exception:
                behind = 0
            if tgt is not None and 0 < behind <= self._PREROLL_HANDOFF_MS:
                self._preroll_handoff = True
                self._preroll_timer().start()
                # Страховка: разбег мог упереться в конец файла и не доехать.
                _api.QTimer.singleShot(self._PREROLL_HANDOFF_MS + 300,
                                  self._preroll_handoff_finish)
                self.on_playback_changed(self.player.playbackState())
                return
            self._preroll_target_ms = None
            try:
                self._preroll_timer().stop()
            except Exception:
                pass
            try:
                self.audio_output.setMuted(self._preroll_prev_muted)
                # Остаток разбега длиннее порога — ждать дольше, чем стоит
                # перемотка; доводим позицию.
                if tgt is not None and behind > self._PREROLL_HANDOFF_MS:
                    self.player.setPosition(int(tgt))
            except Exception:
                pass
            self._release_frame_lock()
            self.on_playback_changed(self.player.playbackState())
            return
        if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            pos_s = self.player.position() / 1000.0
            if abs(pos_s - self.current_out) < 0.15 and self.current_out > (self.current_in + 0.5):
                self.seek_to(self.current_in)
            # Пин снимаем ДО play(): иначе первые кадры воспроизведения (у них
            # уже другой pts) холст отбросил бы как «чужие», и картинка стояла бы
            # лишние доли секунды. Предекодер тоже глушим — во время игры
            # процессор нужен декодеру плеера, а не буферу стоп-кадров.
            self._release_frame_lock()
            self.player.play()

    def stop_playback(self):
        self.player.pause(); self.seek_to(self.current_in)
        # «Камера» идёт за плейхедом: если зум стоит не на начале зоны, докручиваем
        # окно обзора так, чтобы точка, куда прыгнула жёлтая полоска, была видна.
        try:
            self.waveform.ensure_view_contains(self.current_in, self.current_in)
            self.waveform.update()
        except Exception:
            pass
        # Точный кадр точки IN — на холст СРАЗУ (до прогрева): иначе кадры
        # «разбега» успели бы мелькнуть на экране.
        self._show_exact_frame(self._frame_idx)
        # Прогреваем конвейер в точке IN — следующее «Воспроизвести» стартует
        # без задержки (см. _preroll_at). Цель берём у КАДРА (seek_to уже
        # поставил на него _frame_idx), иначе прогрев целился бы мимо сетки.
        self._preroll_at(self._playhead_target_s())

    def on_playback_changed(self, state):
        # Во время покадрового скраба play→pause транзиентны — не трогаем кнопку,
        # чтобы иконка/текст не дёргались (меняются только по явному действию).
        # То же во время беззвучного прогрева аудио (_preroll_at): кнопка/иконка
        # и внешняя озвучка не должны мигать на транзиентный play→pause.
        if self._scrubbing or getattr(self, "_prerolling", False):
            return
        playing = (state == _api.QMediaPlayer.PlaybackState.PlayingState)
        # Сигнал приходит с задержкой: «играю» могло прилететь уже ПОСЛЕ того,
        # как прогрев остановил плеер. Верим текущему состоянию, а не почтальону:
        # иначе устаревший сигнал снимал пин с холста и отпускал буфер кадров —
        # картинка уезжала с кадра, на котором стоял монтаж.
        try:
            if playing and (self.player.playbackState()
                            != _api.QMediaPlayer.PlaybackState.PlayingState):
                return
        except Exception:
            pass
        # Painted-режим: во время игры ресайзим кадр быстрым методом (экономим ЦП).
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            vw.set_playing(playing)
        # Покадровый слой: во время игры главные — кадры плеера (пин снят,
        # предекодер молчит); на паузе, наоборот, пришпиливаем к холсту точный
        # кадр остановки и греем соседей — тогда первый же шаг стрелкой
        # мгновенный и ровно тем кадром, что просили.
        if playing:
            # Исключение — «передача» разбега (см. toggle_play): пока доигрывается
            # немой остаток до отметки, пин точного кадра ОБЯЗАН держаться, иначе
            # на экране мелькнёт кусочек до отметки. Снимет его
            # _preroll_handoff_finish ровно на цели.
            if not getattr(self, "_preroll_handoff", False):
                self._release_frame_lock()
        elif self._grid.valid and self.video_stream_index is not None:
            # Сбрасываем ПЕРЕД вычислением: иначе _current_frame_index вернул бы
            # прежний номер (он на паузе доверяет _frame_idx), а нам нужен кадр,
            # на котором воспроизведение реально остановилось.
            self._frame_idx = None
            self._frame_idx = self._current_frame_index()
            self._show_exact_frame(self._frame_idx)
            # Плейхед — сразу на кадр остановки. Без этого интерфейс до первого
            # следующего события жил по позиции плеера (аудио-часы), и жёлтая
            # полоса после паузы успевала уехать вперёд, а потом вернуться назад,
            # когда из предекодера приезжал точный кадр.
            stop_s = self._grid.start_of(self._frame_idx)
            self._paint_playhead(stop_s)
            self._update_subtitle(stop_s)
        if playing:
            self.btn_play.setIcon(self.style().standardIcon(_api.QStyle.StandardPixmap.SP_MediaPause))
            self.sync_timer.start()
        else:
            self.btn_play.setIcon(self.style().standardIcon(_api.QStyle.StandardPixmap.SP_MediaPlay))
            self.sync_timer.stop()
        self._set_play_bound(playing)   # painted-режим: блокировка кадров за OUT
        # Внешняя озвучка следует за состоянием основного плеера.
        self._ext_audio_set_state(playing)
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.update_play_icon(state == _api.QMediaPlayer.PlaybackState.PlayingState)
            except Exception:
                pass

    def on_media_status_changed(self, status):
        # Дорожки известны только у загруженного медиа — поэтому режим «только
        # звук» доводим до плеера здесь же, а не в момент нажатия кнопки (иначе
        # у нового файла видео возвращалось само).
        if status in (_api.QMediaPlayer.MediaStatus.LoadedMedia,
                      _api.QMediaPlayer.MediaStatus.BufferedMedia):
            if getattr(self, "_audio_only_mode", False):
                self._apply_audio_only_to_player()
        # После смены качества воспроизведения (swap источника) восстанавливаем
        # позицию и состояние, как только медиа загрузилось.
        if (status in (_api.QMediaPlayer.MediaStatus.LoadedMedia,
                       _api.QMediaPlayer.MediaStatus.BufferedMedia)
                and getattr(self, '_pending_pb_seek', None) is not None):
            pos, was_playing = self._pending_pb_seek
            self._pending_pb_seek = None
            try:
                self.player.setPosition(int(max(0, pos)))
                if was_playing:
                    self.player.play()
                else:
                    self.player.pause()
            except Exception:
                pass
        # Подстраховка от чёрного кадра в конце: если воспроизведение всё же
        # дошло до EndOfMedia (таймер sync_ui не успел поставить паузу на кадр
        # раньше), возвращаемся на последний реальный кадр и держим паузу.
        try:
            if status == _api.QMediaPlayer.MediaStatus.EndOfMedia and self.duration > 0:
                frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
                last = max(self.current_in, self.duration - max(frame_s, 0.05))
                self.player.pause()
                self.player.setPosition(int(last * 1000))
                self.waveform.set_playhead(last)
                self.lbl_current_time.setText(_api.s_to_time(last))
        except Exception:
            pass

    def toggle_mute(self):
        """Клик по значку динамика: выключает звук и включает обратно, возвращая
        ПРЕЖНИЙ уровень громкости.

        Через сам ползунок (а не audio_output.setMuted): его valueChanged уже
        разводит громкость по всем трём выходам — видео, внешняя озвучка и
        скраб-звук покадрового шага, — обновляет значок динамика и полноэкранную
        панель. Плюс setMuted тут занят: им глушится звук видео, когда выбрана
        внешняя озвучка (см. _set_external_audio), и mute «поверх» него оставил
        бы пользователя без способа вернуть звук."""
        sl = getattr(self, "vol_slider", None)
        if sl is None:
            return
        cur = int(sl.value())
        if cur > 0:
            self._vol_before_mute = cur
            sl.setValue(0)
        else:
            # Прежний уровень мог быть нулевым (ползунок утащили в 0 руками) —
            # тогда возвращаем разумную громкость, а не «включаем в тишину».
            prev = int(getattr(self, "_vol_before_mute", 0) or 0)
            sl.setValue(prev if prev > 0 else 100)

    def _on_volume_changed(self, v):
        try:
            self.audio_output.setVolume(v / 100.0)
        except Exception:
            pass
        # Та же громкость — для внешней озвучки (отдельный аудиовыход).
        if self._ext_audio_output is not None:
            try:
                self._ext_audio_output.setVolume(v / 100.0)
            except Exception:
                pass
        # …и для скраб-звука покадровой перемотки.
        if getattr(self, "_scrub_sink_obj", None) is not None:
            try:
                self._scrub_sink_obj.setVolume(max(0.0, min(1.0, v / 100.0)))
            except Exception:
                pass
        try:
            self.vol_lbl.update_glyph(v)
        except Exception:
            pass
        # Полноэкранный ползунок громкости держим в курсе.
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.sync_volume()
            except Exception:
                pass

    def _update_media_buttons(self):
        """Кнопки «полноэкранный режим» и «сохранить кадр» активны только когда
        загружено видео (есть видеопоток и длительность)."""
        has_video = (getattr(self, "video_stream_index", None) is not None
                     and getattr(self, "duration", 0) > 0.1)
        is_image = bool(getattr(self, "is_still_image", False))
        # Для still-картинки доступны кадрирование/пикселизация/сохранение кадра
        # (полноэкранный режим — нет, он завязан на плеер).
        has_visual = has_video or is_image
        audio_only_mode = bool(getattr(self, "_audio_only_mode", False))
        _fsb = getattr(self, "btn_fullscreen", None)
        if _fsb is not None:
            # В режиме «только звук» смотреть в полный экран нечего.
            _fsb.setEnabled(has_video and not audio_only_mode)
        _aob = getattr(self, "btn_audio_only", None)
        if _aob is not None:
            _aob.setEnabled(has_video)
            if not has_video and _aob.isChecked():
                # Загрузили аудиофайл — режим сам себя выключает: у плеера и так
                # нет видео, а подсвеченная кнопка сбивала бы с толку.
                _aob.setChecked(False)
        for name in ("btn_save_frame", "btn_crop_frame", "btn_pixelize",
                     "btn_create_subs", "btn_image_overlay"):
            b = getattr(self, name, None)
            if b is not None:
                b.setEnabled(has_visual)
        # «Удалить объект» — только для видео (для одиночной картинки есть
        # фоторедактор) и только если не идёт уже обработка.
        b = getattr(self, "btn_remove_object", None)
        if b is not None and not getattr(self, "_vinp_running", False):
            b.setEnabled(has_video)
        # «Привязать к объекту» — тоже только для видео (нужно движение).
        b = getattr(self, "btn_track_object", None)
        if b is not None and not getattr(self, "_trk_running", False):
            b.setEnabled(has_video)
        # Нет визуала (ни видео, ни картинки) — выходим из режима кадрирования рамки.
        if not has_visual:
            b = getattr(self, "btn_crop_frame", None)
            if b is not None and b.isChecked():
                b.setChecked(False)
            # …и сбрасываем пикселизацию.
            if getattr(self, "_pixelize_active", False) or (
                    getattr(self, "btn_pixelize", None) is not None
                    and self.btn_pixelize.isChecked()):
                self._pixelize_active = False
                b = getattr(self, "btn_pixelize", None)
                if b is not None and b.isChecked():
                    b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
                self._sync_pixelize_icon()
            self._clear_image_overlays()
        if getattr(self, "btn_more_actions", None) is not None:
            self._refresh_more_actions()
        if getattr(self, "_entrance_running", False):
            for button in self._montage_side_btns:
                button.setEnabled(False)
        # Режимы обрезки, неприменимые к аудио, отключаем (см. ниже).
        self._update_mode_combo_for_media(has_video)
        # Иконка полноэкранного режима белая поверх accent-заливки; на сером
        # disabled-фоне белый значок «не выглядел» выключенным. Перекрашиваем его
        # в приглушённый цвет, когда видео нет, и обратно в белый, когда есть.
        try:
            if getattr(self, "btn_fullscreen", None) is not None \
                    and getattr(self, "_fs_window", None) is None:
                self.btn_fullscreen.setIcon(_api._fullscreen_icon(
                    expand=True, color="#ffffff" if has_video else _api.C['text3']))
        except Exception:
            pass

    def _toggle_audio_only(self, on):
        """Кнопка «Только звук»: снимает/возвращает видеодорожку у плеера.

        Декодирование видео прекращается на уровне QMediaPlayer (активный
        видеотрек = -1), предекодер точных кадров глушится, на холсте вместо
        картинки — надпись. Звук, волна, покадровый шаг, прогрев конвейера и
        обрезка работают как обычно: резать по волне и на слух можно ровно так
        же, а экспорт идёт отдельным ffmpeg по исходнику и видео сохраняет."""
        on = bool(on)
        if on == getattr(self, "_audio_only_mode", False):
            return
        self._audio_only_mode = on
        # Разбег греет звук — но он играет плеером, а мы сейчас плееру меняем
        # набор дорожек. Гасим, чтобы не столкнулись.
        if getattr(self, "_prerolling", False):
            self._preroll_cancel()
        self._apply_audio_only_to_player()
        eng = getattr(self, "_frames", None)
        if eng is not None:
            eng.cancel()          # ffmpeg больше не декодирует кадры впустую
        self._update_audio_only_placeholder()
        if not on:
            # Вернули видео — сразу возвращаем и точный кадр под плейхедом.
            self._show_exact_frame(self._frame_idx)
        self._update_media_buttons()

    def _apply_audio_only_to_player(self):
        """Переключает видеодорожку плеера под текущий режим.

        Смена активного трека у ffmpeg-бэкенда может сбросить позицию, поэтому
        запоминаем её и возвращаем: плейхед обязан остаться там же, где стоял
        (см. _ui_pinned_ms — позиция в Монтаже священна)."""
        player = getattr(self, "player", None)
        if player is None:
            return
        on = getattr(self, "_audio_only_mode", False)
        try:
            pos = player.position()
        except Exception:
            pos = None
        try:
            if on:
                cur = player.activeVideoTrack()
                if cur is not None and cur >= 0:
                    self._audio_only_prev_track = cur
                player.setActiveVideoTrack(-1)
            else:
                prev = getattr(self, "_audio_only_prev_track", 0)
                player.setActiveVideoTrack(prev if (prev is not None and prev >= 0) else 0)
        except Exception as e:
            self.main.log(f"audio-only: не удалось переключить видеодорожку: {e}")
            return
        try:
            if pos is not None and player.position() != pos:
                player.setPosition(int(pos))
        except Exception:
            pass

    def _update_audio_only_placeholder(self):
        """В области видео показываем поясняющий текст, когда у загруженного файла
        нет видеоряда (редактируется чистое аудио). При наличии видео или без файла
        — обычный режим (показ кадров)."""
        vw = getattr(self, "video_widget", None)
        if vw is None or not hasattr(vw, "set_audio_only_message"):
            return
        src = getattr(self, "actual_source_file", None)
        # Still-картинка показывается на холсте как кадр — это НЕ «аудио без видео».
        audio_only = (bool(src)
                      and not getattr(self, "is_still_image", False)
                      and getattr(self, "video_stream_index", None) is None
                      and getattr(self, "duration", 0) > 0.1)
        if audio_only:
            vw.set_audio_only_message("Вы редактируете аудиофайл — видеоряд отсутствует")
        elif getattr(self, "_audio_only_mode", False) and bool(src):
            # Видео у файла есть, но пользователь сам отключил его кнопкой —
            # прямо говорим об этом и как вернуть, иначе пустой холст читается
            # как поломка.
            vw.set_audio_only_message(
                "Только звук — видео отключено кнопкой 🎧 в панели плеера.\n"
                "Нажмите её ещё раз, чтобы вернуть картинку. "
                "На обрезку и экспорт это не влияет.")
        else:
            vw.set_audio_only_message("")

    # ── Полноэкранный режим ─────────────────────────────────────────────────
    def toggle_fullscreen(self):
        if getattr(self, "_fs_window", None) is not None:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        if getattr(self, "_fs_window", None) is not None:
            return
        if self.duration <= 0.1:   # нет загруженного видео
            return
        try:
            fs = _api.FullscreenVideo(self)
            # fs — самостоятельное окно без родителя (иначе showFullScreen на
            # дочернем виджете ведёт себя иначе), поэтому Qt может открыть его
            # fullscreen'ом на ПЕРВИЧНОМ мониторе, даже если само приложение
            # (и мышь пользователя) сейчас на другом. Явно ставим тот же экран,
            # где сейчас окно приложения — заодно фиксирует QScreen ДО первого
            # show(), от чего зависит и корректный клэмп tooltip'ов панели
            # управления (см. FullscreenVideo._relayout).
            try:
                src_screen = self.window().windowHandle().screen()
            except Exception:
                src_screen = None
            if src_screen is not None:
                fs.winId()   # форсирует создание нативного хэндла ДО setScreen
                wh = fs.windowHandle()
                if wh is not None:
                    wh.setScreen(src_screen)
            # Снимаем фиксированные размеры с видео и переносим его в окно.
            self.video_widget.setMinimumSize(0, 0)
            self.video_widget.setMaximumSize(16777215, 16777215)
            fs.attach_video(self.video_widget)
            self._fs_window = fs
            self.btn_fullscreen.setIcon(_api._fullscreen_icon(expand=False))
            self.btn_fullscreen.setToolTip("Свернуть (Esc / двойной клик по видео)")
            fs.showFullScreen()
            # Без этого клавиши (F/Esc/Space/стрелки) не доходили до окна: после
            # showFullScreen() фокус клавиатуры мог оставаться на виджете, у
            # которого он был ДО входа в полноэкранный режим (например, на
            # волне/поле ссылки в основном окне) — F там ничего не делал.
            fs.activateWindow()
            fs.setFocus(_api.Qt.FocusReason.OtherFocusReason)
            fs.sync_from_player()
            fs.sync_volume()
            fs.update_play_icon(
                self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState)
            # Холст переехал в другое окно, а с ним и его сцена Qt Quick:
            # графический контекст пересоздан, и показанный кадр в нём не
            # переживает переезд. На паузе кадров от плеера больше не будет —
            # ставим точный кадр заново (на воспроизведении метод сам ничего не
            # делает: там следующий кадр приедет через ~16 мс).
            _api.QTimer.singleShot(0, self._restore_canvas_frame)
            try:
                self._update_subtitle(self._ui_time_s())
                _api.QTimer.singleShot(0, self._position_overlay)
            except Exception:
                pass
        except Exception as e:
            self.main.log(f"enter_fullscreen error: {e}")
            self._fs_window = None

    def exit_fullscreen(self):
        fs = getattr(self, "_fs_window", None)
        if fs is None:
            return
        self._fs_window = None
        try:
            # Возвращаем видео обратно в контейнер вкладки.
            self.vc_layout.insertWidget(0, self.video_widget, 0, _api.Qt.AlignmentFlag.AlignCenter)
            self.video_widget.show()
        except Exception:
            pass
        # Оверлей субтитров мог стать дочерним к окну fs — вернём его главному
        # окну ДО удаления fs, иначе Qt удалит оверлей вместе с fs.
        try:
            if self.sub_overlay is not None:
                self._reparent_overlay(self.window())
        except Exception:
            pass
        try:
            fs.close(); fs.deleteLater()
        except Exception:
            pass
        try:
            self.btn_fullscreen.setIcon(_api._fullscreen_icon(expand=True))
            self.btn_fullscreen.setToolTip("Полноэкранный режим (F / двойной клик по видео)")
            self._adjust_video_height()
            _api.QTimer.singleShot(0, self._position_overlay)
            # Обратный переезд — та же история, что и при входе (см. там).
            _api.QTimer.singleShot(0, self._restore_canvas_frame)
        except Exception:
            pass

    def _restore_canvas_frame(self):
        """Возвращает кадр на холст после переезда в другое окно.

        Нужен только на паузе: сцена холста теряет показанный кадр вместе с
        графическим контекстом, а новых кадров плеер на паузе не шлёт. Точный
        кадр берётся из того же предекодера, что и при покадровом шаге, так что
        на экране оказывается ровно тот кадр, на котором стояли."""
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                return
        except Exception:
            return
        try:
            self._show_exact_frame(self._frame_idx)
        except Exception:
            pass

    def _fs_sync_position(self):
        """Обновляет полосу/тайминги в полноэкранном окне (вызывается из sync_ui
        и on_position_changed, когда оно открыто)."""
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.sync_from_player()
            except Exception:
                pass
