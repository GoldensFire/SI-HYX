# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: eventFilter. Public namespace: edit_tab."""
import edit_tab as _api


def eventFilter(self, watched, event):
    # Колесо мыши НЕ меняет значения полей (спинбоксы кадров, комбобоксы
    # дорожек/режима, ползунки громкости/позиции) — частая причина случайных
    # изменений. Виджет волны (WaveformWidget) не входит в эти типы → его
    # зум колесом сохраняется.
    # Шкала уровня звука изменила высоту → пересчёт размера кнопок (ровно 8).
    if (event.type() == _api.QEvent.Type.Resize
            and watched is getattr(self, "audio_meter", None)):
        self._resize_montage_side_btns(watched.height())
    if event.type() == _api.QEvent.Type.Wheel and isinstance(
            watched, (_api.QSpinBox, _api.QComboBox, _api.QSlider)):
        # Виджеты с пометкой wheelAlways (ползунок громкости) — колесо меняет
        # значение ВСЕГДА: пропускаем событие к их собственному wheelEvent.
        if watched.property("wheelAlways"):
            return False
        return True
    # Двойной клик по видео → переключение полноэкранного режима.
    if (event.type() == _api.QEvent.Type.MouseButtonDblClick
            and watched is self.video_widget):
        self.toggle_fullscreen()
        return True
    # Главное окно подвинули/изменили → ведём за ним оверлей субтитров.
    if (watched is self._overlay_win
            and event.type() in (_api.QEvent.Type.Move, _api.QEvent.Type.Resize,
                                 _api.QEvent.Type.WindowStateChange)):
        self._position_overlay()
    if event.type() == _api.QEvent.Type.DragEnter:
        md = event.mimeData()
        if md.hasUrls() or md.hasText():
            event.acceptProposedAction(); return True
    if event.type() == _api.QEvent.Type.DragMove:
        md = event.mimeData()
        if md.hasUrls() or md.hasText():
            event.acceptProposedAction(); return True
    if event.type() == _api.QEvent.Type.Drop:
        md = event.mimeData(); loaded = False
        try:
            urls = md.urls()
            if urls:
                local = urls[0].toLocalFile()
                if local and _api.os.path.exists(local):
                    self.load_file(local); loaded = True
        except Exception:
            pass
        if not loaded:
            try:
                txt = md.text()
                if txt:
                    path = txt.strip()
                    if _api.os.path.exists(path):
                        self.load_file(path); loaded = True
            except Exception:
                pass
        if loaded:
            event.acceptProposedAction()
            return True
    return super(_api.EditTab, self).eventFilter(watched, event)

# ── Папка экспорта ──────────────────────────────────────────────────────
def _choose_export_dir(self):
    start = self.export_dir or (str(self.actual_source_file.parent)
                                if self.actual_source_file else "")
    d = _api.QFileDialog.getExistingDirectory(self, "Папка для сохранения обрезки", start)
    if d:
        self.export_dir = d
        self._update_export_dir_label()
        self.save_settings()

def _reset_export_dir(self):
    self.export_dir = ""
    self._update_export_dir_label()
    self.save_settings()

def _update_export_dir_label(self):
    lbl = getattr(self, "lbl_export_dir", None)
    if lbl is None:
        return
    if self.export_dir and _api.os.path.isdir(self.export_dir):
        # Укорачиваем путь в середине, чтобы он не распирал панель; полный
        # путь — в подсказке.
        fm = _api.QFontMetrics(lbl.font())
        elided = fm.elidedText(self.export_dir, _api.Qt.TextElideMode.ElideMiddle, 210)
        lbl.setText(elided)
        lbl.setToolTip(self.export_dir)
    else:
        lbl.setText("Рядом с исходником")
        lbl.setToolTip("Файл сохраняется в папке исходника")

# ── Аудио/субтитры: дорожки ─────────────────────────────────────────────
@staticmethod
def _fmt_bitrate(ainfo):
    raw = (ainfo or {}).get('bit_rate')
    if not raw:
        # Контейнеры mkvmerge (MKV) не пишут bit_rate в поток, а кладут его в
        # тег статистики — обычно «BPS-eng» (язык в суффиксе), реже «BPS».
        # Берём первый тег, чьё имя начинается на BPS (без учёта регистра).
        tags = (ainfo or {}).get('tags', {}) or {}
        raw = tags.get('BPS') or tags.get('BPS-eng')
        if not raw:
            for k, v in tags.items():
                if k.upper().startswith('BPS'):
                    raw = v
                    break
    try:
        return f"{round(int(raw) / 1000)} кбит/с"
    except Exception:
        return "—"

@staticmethod
def _track_label(s, i, kind, total=1):
    tags = s.get('tags', {}) or {}
    lang = tags.get('language') or tags.get('LANGUAGE') or ''
    title = tags.get('title') or tags.get('TITLE') or ''
    codec = (s.get('codec_name') or '').upper()
    parts = [f"{i + 1}."]
    # Тег языка показываем ТОЛЬКО когда дорожек несколько — иначе выбирать
    # нечего, а тег часто врёт (YouTube помечает единственную/оригинальную
    # дорожку как "eng" независимо от реального языка озвучки).
    if lang and total > 1: parts.append(lang)
    if title: parts.append(title[:18])
    if codec and not title: parts.append(codec)
    return " ".join(parts) or f"Дорожка {i + 1}"

def _populate_track_combos(self):
    self._loading_tracks = True
    # Новый файл → сбрасываем оверлей субтитров от предыдущего (combo
    # переустанавливается на «Выкл», но on_sub_track_changed под флагом молчит).
    self._stop_sub_extractor()
    self._stop_ass()
    self._sub_cues = []
    self._sub_use_overlay = False
    self._hide_sub_display()
    try:
        # ── Аудио: встроенные дорожки + внешние файлы (озвучка) ──
        self.cmb_audio.clear()
        self._audio_entries = []
        for i, s in enumerate(self._audio_streams):
            self.cmb_audio.addItem(self._track_label(s, i, "Аудио", total=len(self._audio_streams)))
            self._audio_entries.append(('emb', i))
        for p in self._audio_ext:
            self.cmb_audio.addItem(_api.get_icon('fa5s.file'), _api.os.path.basename(p))
            self._audio_entries.append(('ext', p))
        if not self._audio_entries:
            self.cmb_audio.addItem("— нет —")
        # «Нет» — выключить звук: превью молчит, экспорт идёт без звука.
        self._add_audio_off_entry()
        self.cmb_audio.setEnabled(len(self._audio_entries) > 1)

        # ── Субтитры: «Выкл» + встроенные + внешние файлы ──
        self.cmb_subs.clear()
        self.cmb_subs.addItem("Выкл")
        self._sub_entries = []
        self._sub_sel_entry = None
        for i, s in enumerate(self._sub_streams):
            self.cmb_subs.addItem(self._track_label(s, i, "Субтитры", total=len(self._sub_streams)))
            self._sub_entries.append(('emb', i))
        for p in self._sub_ext:
            self.cmb_subs.addItem(_api.get_icon('fa5s.file'), _api.os.path.basename(p))
            self._sub_entries.append(('ext', p))
        if getattr(self, "_sub_ext_hidden", None):
            self.cmb_subs.addItem(_api.get_icon('fa5s.folder-open'),
                                   f"Показать другие файлы в папке… ({len(self._sub_ext_hidden)})")
            self._sub_entries.append(('more', None))
        self.cmb_subs.setEnabled(len(self._sub_entries) > 0)
    finally:
        self._loading_tracks = False
    self.selected_audio_abs_index = (
        self._audio_streams[0].get('index') if self._audio_streams else None)
    self.selected_audio_ext_path = None
    self.selected_sub_ext_path = None
    self._clear_external_audio()
    self._set_audio_disabled(False)

def on_audio_track_changed(self, idx):
    if self._loading_tracks or idx < 0 or idx >= len(self._audio_entries):
        return
    kind, ref = self._audio_entries[idx]
    if kind == 'none':
        # Звук выключен: гасим и внешнюю озвучку, волну оставляем как есть.
        self.selected_audio_ext_path = None
        self._clear_external_audio()
        self.selected_audio_abs_index = None
        self._set_audio_disabled(True)
        self._update_audio_info_labels(None)
        return
    self._set_audio_disabled(False)
    if kind == 'emb':
        # Встроенная дорожка → возвращаем звук видео, гасим внешнюю озвучку.
        self.selected_audio_ext_path = None
        self._clear_external_audio()
        st = self._audio_streams[ref]
        self.selected_audio_abs_index = st.get('index')
        try:
            self.player.setActiveAudioTrack(ref)
        except Exception:
            pass
        # Инфо-метки (кодек/каналы/битрейт) и аудиоволна — под новую дорожку.
        # prioritize_selection: сперва быстро строим волну на выделенном
        # отрезке, полный файл досчитывается следом в фоне.
        self._update_audio_info_labels(st)
        self._start_waveform(self.actual_source_file, st.get('index'), prioritize_selection=True)
    else:
        # Внешний файл озвучки → играет отдельный синхронный плеер.
        self.selected_audio_abs_index = None
        self.selected_audio_ext_path = ref
        self._set_external_audio(ref)
        self._update_audio_info_labels(self._probe_audio_stream(ref))
        # Волну строим из самого файла озвучки (единственная дорожка).
        self._start_waveform(ref, None, prioritize_selection=True)

def _update_audio_info_labels(self, ainfo):
    """Обновляет метки «кодек/каналы» и «битрейт» под выбранную аудиодорожку
        (встроенную или внешний файл озвучки)."""
    if ainfo:
        codec_a = (ainfo.get('codec_name') or '?').upper()
        self.lbl_astream.setText(f"{codec_a} {_api._fmt_channels(ainfo)}")
        self.lbl_abitrate.setText(self._fmt_bitrate(ainfo))
    else:
        self.lbl_astream.setText("—")
        self.lbl_abitrate.setText("—")

def _probe_audio_stream(self, path):
    """Возвращает первую аудиодорожку внешнего файла озвучки (для инфо-меток).
        Лёгкий ffprobe; при ошибке — None (метки покажут «—»)."""
    try:
        cmd = [_api.FFPROBE, "-v", "error", "-select_streams", "a:0",
               "-show_entries", "stream=codec_name,channels,bit_rate,"
               "channel_layout:stream_tags=BPS,BPS-eng",
               "-of", "json", str(path)]
        r = _api.subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=_api.CREATE_NO_WINDOW, timeout=15)
        if r.returncode == 0:
            data = _api.json.loads(r.stdout or "{}")
            streams = data.get('streams') or []
            if streams:
                return streams[0]
    except Exception:
        pass
    return None
