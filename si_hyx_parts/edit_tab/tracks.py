# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: аудиодорожки, внешняя озвучка и субтитры (поиск, оверлей, правка)."""
import re

import edit_tab as _api
from si_hyx_parts.edit_tab import subtitle_style


AUDIO_OFF_LABEL = "Нет"
MORE_FILES_LABEL = "Показать другие файлы в папке… ({})"

# Теги в скобках у имён релизов: «[Group] Title - 01 [1080p] (BD)».
_NAME_TAGS = re.compile(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}")
_NAME_SEPS = re.compile(r"[._]+")
_NAME_SPACES = re.compile(r"\s+")
_NAME_NUMBERS = re.compile(r"\d+")


def media_name_key(path) -> str:
    """Имя файла без расширения и тегов в скобках, в нижнем регистре:
    «[Group] Title - 01 [1080p].mkv» и «[Dub] Title - 01.mka» → «title - 01»."""
    name = _api.os.path.splitext(_api.os.path.basename(str(path)))[0].lower()
    name = _NAME_SEPS.sub(" ", _NAME_TAGS.sub(" ", name))
    return _NAME_SPACES.sub(" ", name).strip(" -")


def names_relate(a: str, b: str) -> bool:
    """Ключи имён (media_name_key) про один и тот же фильм/серию: один
    содержит другой, а последние числа (номер серии) совпадают, если есть у
    обоих — «title - 01» не родня «title - 011»."""
    if not a or not b or not (a == b or a in b or b in a):
        return False
    na, nb = _NAME_NUMBERS.findall(a), _NAME_NUMBERS.findall(b)
    return not na or not nb or int(na[-1]) == int(nb[-1])


def _audio_is_off(self) -> bool:
    return bool(getattr(self, "audio_disabled", False))


def _track_title(tags: dict) -> str:
    """Имя дорожки из тегов ffprobe. MKV кладёт его в title, MP4/M4V — в name
    (атом udta), иногда только в handler_name. Служебные handler_name
    («SoundHandler», «Core Media Audio», «ISO Media file produced by…»)
    именем не считаются."""
    for key in ('title', 'TITLE', 'name', 'NAME'):
        value = str(tags.get(key) or '').strip()
        if value:
            return value
    handler = str(tags.get('handler_name') or tags.get('HANDLER_NAME') or '').strip()
    low = handler.casefold()
    if not handler or 'handler' in low or low.startswith(('core media', 'iso media')):
        return ''
    return handler


def drop_audio(cmd: list, out: str) -> list:
    """Команда ffmpeg без звука на выходе: -an прямо перед путём вывода."""
    if cmd and cmd[-1] == out and "-an" not in cmd:
        cmd = cmd[:-1] + ["-an", out]
    return cmd


class EditTabTracksMixin:
    """Монтаж: аудиодорожки, внешняя озвучка и субтитры (поиск, оверлей, правка)."""

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
        """Подпись дорожки — её имя из файла целиком («English DUB from
        StudioCanal Stereo»). Безымянная — язык и кодек («2. eng AAC»)."""
        tags = s.get('tags', {}) or {}
        lang = tags.get('language') or tags.get('LANGUAGE') or ''
        title = _track_title(tags)
        if title:
            return f"{i + 1}. {title}"
        codec = (s.get('codec_name') or '').upper()
        parts = [f"{i + 1}."]
        # Тег языка показываем ТОЛЬКО когда дорожек несколько — иначе выбирать
        # нечего, а тег часто врёт (YouTube помечает единственную/оригинальную
        # дорожку как "eng" независимо от реального языка озвучки).
        if lang and total > 1: parts.append(lang)
        if codec: parts.append(codec)
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
            # ── Аудио: встроенные дорожки + внешние файлы (озвучка), «Нет» —
            # выключить звук (превью молчит, экспорт без звука) ──
            self._fill_audio_combo()
            self._audio_sel_entry = self._audio_entries[0] if self._audio_entries else None

            # ── Субтитры: «Выкл» + встроенные + внешние файлы ──
            self.cmb_subs.clear()
            self.cmb_subs.addItem("Выкл")
            self._sub_entries = []
            self._sub_sel_entry = None
            for i, s in enumerate(self._sub_streams):
                self.cmb_subs.addItem(self._track_label(s, i, "Субтитры", total=len(self._sub_streams)))
                self._sub_entries.append(('emb', i))
            for p in self._sub_ext:
                self.cmb_subs.addItem(_api.os.path.basename(p))
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
        if kind == 'more':
            # Как у субтитров: досыпать отложенные файлы, остаться на прежнем
            # выборе и снова раскрыть список — его открывали, чтобы выбрать.
            self._expand_external_audio()
            _api.QTimer.singleShot(0, self._reopen_audio_popup)
            return
        self._audio_sel_entry = (kind, ref)
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

    def _set_audio_disabled(self, on: bool) -> None:
        """Включает/выключает звук превью по пункту «Нет»."""
        on = bool(on)
        if _audio_is_off(self) == on:
            return
        self.audio_disabled = on
        try:
            self.player.setAudioOutput(None if on else self.audio_output)
        except Exception:
            pass

    def _add_audio_off_entry(self) -> None:
        """Пункт «Нет» в конце списка дорожек (если звук у файла вообще есть)."""
        if not self._audio_entries:
            return
        self.cmb_audio.addItem(_api.get_icon('fa5s.volume-mute'), AUDIO_OFF_LABEL)
        self._audio_entries.append(('none', None))

    def _external_audio_insert_at(self) -> int:
        """Куда вставить новый файл озвучки: перед пунктом «Нет»."""
        for i, (kind, _ref) in enumerate(self._audio_entries):
            if kind in ('none', 'more'):
                return i
        return len(self._audio_entries)

    def _add_audio_more_entry(self) -> None:
        """«Показать другие файлы в папке…» — последним пунктом, если поиск
        озвучки что-то отложил (см. _scan_external_audio)."""
        hidden = getattr(self, "_audio_ext_hidden", None)
        if not hidden:
            return
        if not self._audio_entries:
            # У файла нет своего звука: плейсхолдер «— нет —» и значит «Нет».
            self._audio_entries.append(('none', None))
        self.cmb_audio.addItem(_api.get_icon('fa5s.folder-open'),
                               MORE_FILES_LABEL.format(len(hidden)))
        self._audio_entries.append(('more', None))

    def _external_audio_label(self, path):
        """Подпись внешней озвучки. Файл из подпапки — вместе с её путём
        («Eng Sound / файл.mka»): по папке обычно и видно, чья это озвучка."""
        base = _api.os.path.basename(str(path))
        src = getattr(self, "actual_source_file", None)
        if not src:
            return base
        try:
            rel = _api.os.path.relpath(_api.os.path.dirname(str(path)),
                                       _api.os.path.dirname(str(src)))
        except (ValueError, TypeError):
            return base
        if rel in (".", "") or rel.startswith(".."):
            return base
        return f"{rel.replace(_api.os.sep, ' / ')} / {base}"

    def _fill_audio_combo(self):
        """Список аудиодорожек: встроенные, внешние файлы, «Нет» и «ещё»."""
        self.cmb_audio.clear()
        self._audio_entries = []
        for i, s in enumerate(self._audio_streams):
            self.cmb_audio.addItem(self._track_label(s, i, "Аудио", total=len(self._audio_streams)))
            self._audio_entries.append(('emb', i))
        for p in self._audio_ext:
            self.cmb_audio.addItem(self._external_audio_label(p))
            self._audio_entries.append(('ext', p))
        if not self._audio_entries:
            self.cmb_audio.addItem("— нет —")
        self._add_audio_off_entry()
        self._add_audio_more_entry()
        self.cmb_audio.setEnabled(len(self._audio_entries) > 1)

    def _expand_external_audio(self):
        """«Показать другие файлы» у звука: отложенные файлы — в список, выбор
        остаётся на той дорожке, что играет сейчас."""
        hidden = getattr(self, "_audio_ext_hidden", None) or []
        self._audio_ext_hidden = []
        for p in hidden:
            if p not in self._audio_ext:
                self._audio_ext.append(p)
        sel = getattr(self, "_audio_sel_entry", None)
        self._loading_tracks = True
        try:
            self._fill_audio_combo()
            if sel is not None and sel in self._audio_entries:
                self.cmb_audio.setCurrentIndex(self._audio_entries.index(sel))
        finally:
            self._loading_tracks = False

    def _reopen_audio_popup(self):
        cmb = getattr(self, "cmb_audio", None)
        if cmb is None or not cmb.isEnabled() or not cmb.isVisible():
            return
        try:
            cmb.showPopup()
        except Exception:
            pass

    # Слова в названии папки с озвучкой: Rus Sound, Eng Sound [Studio], Audio,
    # Dub, Озвучка, Звук…
    _AUDIO_FOLDER_WORDS = ('sound', 'audio', 'dub', 'voice', 'звук', 'озвуч', 'аудио')

    def _scan_external_audio(self, src):
        """Внешняя озвучка рядом с видео и в подпапках (до 3 уровней) — как у
        субтитров. Сразу в список: файлы, чьё имя совпадает с видео без тегов в
        скобках (media_name_key), и единственный звуковой файл папки озвучки
        (Rus Sound, Audio, Озвучка…) — у фильма с переводом имя бывает своё.
        Остальное (папка озвучки на весь сезон, чужие mp3 рядом) откладывается
        в self._audio_ext_hidden — его открывает «Показать другие файлы…»."""
        found, hidden, folders = [], [], {}
        try:
            base = _api.os.path.dirname(str(src))
            if not base or not _api.os.path.isdir(base):
                self._audio_ext_hidden = []
                return []
            own = _api.os.path.normcase(_api.os.path.abspath(str(src)))
            key = media_name_key(src)
            seen = 0
            for root, dirs, files in _api.os.walk(base):
                rel_dir = root[len(base):].lstrip(_api.os.sep)
                depth = rel_dir.count(_api.os.sep) + (1 if rel_dir else 0)
                if depth >= 3:
                    dirs[:] = []
                # Папка озвучки — подпапка самого видео (Rus Sound/Студия/…), а
                # не «Rus Sound» соседнего фильма в его собственной папке.
                segs = [s.lower() for s in rel_dir.split(_api.os.sep) if s]
                audio_dir = bool(segs) and any(w in segs[0] for w in self._AUDIO_FOLDER_WORDS)
                for fn in files:
                    if _api.os.path.splitext(fn)[1].lower() not in self._AUDIO_EXTS:
                        continue
                    p = _api.os.path.join(root, fn)
                    if _api.os.path.normcase(_api.os.path.abspath(p)) == own:
                        continue
                    seen += 1
                    if names_relate(media_name_key(fn), key):
                        found.append(p)
                    elif audio_dir:
                        folders.setdefault(root, []).append(p)
                    else:
                        hidden.append(p)
                if seen >= 500:
                    break
            for paths in folders.values():
                (found if len(paths) == 1 else hidden).extend(paths)
        except Exception:
            pass
        self._audio_ext_hidden = self._sort_external_subs(hidden, src)
        return self._sort_external_subs(found, src)

    def _ensure_ext_audio_player(self):
        if self._ext_audio_player is None:
            self._ext_audio_player = _api.QMediaPlayer()
            self._ext_audio_output = _api.QAudioOutput()
            self._ext_audio_player.setAudioOutput(self._ext_audio_output)
            self._ext_audio_player.mediaStatusChanged.connect(
                self._on_ext_audio_status)
        return self._ext_audio_player

    def _set_external_audio(self, path):
        if not path or not _api.os.path.exists(path):
            return
        p = self._ensure_ext_audio_player()
        try:
            self.audio_output.setMuted(True)   # глушим звук видео
        except Exception:
            pass
        try:
            self._ext_audio_output.setVolume(self._output_volume())
        except Exception:
            pass
        self._ext_audio_active = True
        self._ext_audio_sync_pending = True
        p.setSource(_api.QUrl.fromLocalFile(str(path)))

        # Точную синхронизацию делаем по событию загрузки (_on_ext_audio_status).

    def _on_ext_audio_status(self, status):
        """Первая синхронизация озвучки с видео — ОДИН раз после загрузки.

        Раньше она срабатывала на каждый BufferedMedia, а её же setPosition
        снова запускает буферизацию: плеер озвучки перематывался по кругу
        (70 раз за 3 с), позиция шла, а звук так и не начинался —
        после перемотки аудио-конвейеру нужно ~0.4 с на раскрутку."""
        if not self._ext_audio_active or self._ext_audio_player is None:
            return
        if not getattr(self, "_ext_audio_sync_pending", False):
            return
        if status in (_api.QMediaPlayer.MediaStatus.LoadedMedia,
                      _api.QMediaPlayer.MediaStatus.BufferedMedia):
            self._ext_audio_sync_pending = False
            try:
                self._ext_audio_player.setPosition(self.player.position())
                if (self.player.playbackState()
                        == _api.QMediaPlayer.PlaybackState.PlayingState):
                    self._ext_audio_player.play()
                else:
                    self._ext_audio_player.pause()
            except Exception:
                pass

    def _ext_audio_seek(self, ms):
        if self._ext_audio_active and self._ext_audio_player is not None:
            try:
                self._ext_audio_player.setPosition(int(max(0, ms)))
            except Exception:
                pass

    def _ext_audio_set_state(self, playing):
        if not self._ext_audio_active or self._ext_audio_player is None:
            return
        try:
            self._ext_audio_player.setPosition(self.player.position())
            if playing:
                self._ext_audio_player.play()
            else:
                self._ext_audio_player.pause()
        except Exception:
            pass

    def _clear_external_audio(self):
        if not getattr(self, "_ext_audio_active", False):
            return
        self._ext_audio_active = False
        self._ext_audio_sync_pending = False
        p = self._ext_audio_player
        if p is not None:
            try: p.pause()
            except Exception: pass
            try: p.setSource(_api.QUrl())
            except Exception: pass
        try:
            self.audio_output.setMuted(False)
        except Exception:
            pass

    @classmethod
    def _path_relates_to_stem(cls, rel_dir, stem):
        """True, если относительный путь подпапки (от папки видео) похож на
        подпапку ИМЕННО этого фильма/серии — по имени сегмента пути или по
        типовому названию папки субтитров. Не считаем «своей» произвольную
        подпапку общего каталога с раздачами — см. _scan_external_subs."""
        if not rel_dir:
            return True
        for seg in rel_dir.replace('\\', '/').split('/'):
            seg_l = seg.lower()
            if seg_l in cls._SUB_FOLDER_NAMES:
                return True
            if stem and (stem in seg_l or seg_l in stem):
                return True
        return False

    def _scan_external_subs(self, src, expanded=False):
        """Ищет внешние файлы субтитров рядом с видео и в подпапках (до 3
        уровней). По умолчанию (expanded=False) включает только «свои»:
        файлы прямо в папке видео + файлы в подпапках самого фильма/серии
        (см. _path_relates_to_stem) — иначе общая папка с чужими раздачами
        (шрифты/сабы десятков разных тайтлов лежат рядом) засоряла список
        посторонними файлами. Отфильтрованные складываются в
        self._sub_ext_hidden — доступны через пункт «Показать другие файлы»
        в списке дорожек (см. _expand_external_subs)."""
        found, hidden = [], []
        try:
            base = _api.os.path.dirname(str(src))
            if not base or not _api.os.path.isdir(base):
                self._sub_ext_hidden = []
                return []
            stem = _api.os.path.splitext(_api.os.path.basename(str(src)))[0].lower()
            key = media_name_key(src)
            for root, dirs, files in _api.os.walk(base):
                rel_dir = root[len(base):].lstrip(_api.os.sep)
                depth = rel_dir.count(_api.os.sep) + (1 if rel_dir else 0)
                if depth >= 3:
                    dirs[:] = []
                related = expanded or self._path_relates_to_stem(rel_dir, stem)
                for fn in files:
                    if _api.os.path.splitext(fn)[1].lower() in self._SUB_EXTS:
                        p = _api.os.path.join(root, fn)
                        # Имя совпадает с видео без тегов в скобках («Rus Sub/
                        # Фильм.srt», «[Group] Title - 01.ass») — свой файл в
                        # любой подпапке.
                        own = related or names_relate(media_name_key(fn), key)
                        (found if own else hidden).append(p)
                        if len(found) + len(hidden) >= 500:
                            self._sub_ext_hidden = self._sort_external_subs(hidden, src)
                            return self._sort_external_subs(found, src)
        except Exception:
            pass
        self._sub_ext_hidden = self._sort_external_subs(hidden, src)
        return self._sort_external_subs(found, src)

    def _expand_external_subs(self):
        """«Показать другие файлы» — досыпает в cmb_subs файлы, отфильтрованные
        _scan_external_subs как не относящиеся к этому фильму/серии."""
        hidden = getattr(self, "_sub_ext_hidden", None)
        if not hidden:
            return
        self._sub_ext_hidden = []
        for p in hidden:
            if p not in self._sub_ext:
                self._sub_ext.append(p)
        self._populate_track_combos_subs_only()

    def _populate_track_combos_subs_only(self):
        """Перестраивает только cmb_subs (список дорожек субтитров), не трогая
        аудио/сброс текущего показа — используется _expand_external_subs, чтобы
        клик «Показать другие файлы» не гасил уже выбранную дорожку.

        Что восстановить, берём из _sub_sel_entry (последняя РЕАЛЬНО выбранная
        дорожка), а не из текущего пункта комбобокса: «Показать другие файлы» —
        сам пункт списка, и на момент перестройки выбран именно он. Раньше
        отсюда и брали — в итоге восстанавливать было нечего (после раскрытия
        этого пункта в списке уже нет), комбобокс молча вставал на «Выкл», и
        выбор дорожки расходился с тем, что на самом деле показано."""
        cur_kind_ref = getattr(self, "_sub_sel_entry", None)
        self._loading_tracks = True
        try:
            self.cmb_subs.clear()
            self.cmb_subs.addItem("Выкл")
            self._sub_entries = []
            for i, s in enumerate(self._sub_streams):
                self.cmb_subs.addItem(self._track_label(s, i, "Субтитры", total=len(self._sub_streams)))
                self._sub_entries.append(('emb', i))
            for p in self._sub_ext:
                self.cmb_subs.addItem(_api.os.path.basename(p))
                self._sub_entries.append(('ext', p))
            if getattr(self, "_sub_ext_hidden", None):
                self.cmb_subs.addItem(_api.get_icon('fa5s.folder-open'),
                                       f"Показать другие файлы в папке… ({len(self._sub_ext_hidden)})")
                self._sub_entries.append(('more', None))
            self.cmb_subs.setEnabled(len(self._sub_entries) > 0)
            if cur_kind_ref is not None and cur_kind_ref in self._sub_entries:
                self.cmb_subs.setCurrentIndex(self._sub_entries.index(cur_kind_ref) + 1)
        finally:
            self._loading_tracks = False

    @staticmethod
    def _sort_external_subs(paths, src):
        stem = _api.os.path.splitext(_api.os.path.basename(str(src)))[0].lower()

        def key(p):
            name = _api.os.path.splitext(_api.os.path.basename(p))[0].lower()
            match = 0 if (stem and (stem in name or name in stem)) else 1
            return (match, _api.os.path.basename(p).lower())

        return sorted(dict.fromkeys(paths), key=key)

    # ── Кнопки «найти» (внешние аудио/субтитры с ПК) ──────────────────────────
    def find_external_subs(self):
        if not self.actual_source_file:
            return
        start = str(self.actual_source_file.parent)
        fname, _ = _api.QFileDialog.getOpenFileName(
            self, "Выбрать файл субтитров", start,
            "Субтитры (*.srt *.ass *.ssa *.vtt *.sub);;Все файлы (*)")
        if fname:
            self._add_external_sub(_api.os.path.normpath(fname))

    def find_external_audio(self):
        if not self.actual_source_file:
            return
        start = str(self.actual_source_file.parent)
        fname, _ = _api.QFileDialog.getOpenFileName(
            self, "Выбрать аудиофайл (озвучку)", start,
            "Аудио (*.mp3 *.aac *.m4a *.ac3 *.eac3 *.flac *.wav *.opus *.ogg "
            "*.dts *.mka *.wma);;Все файлы (*)")
        if fname:
            self._add_external_audio(_api.os.path.normpath(fname))

    def _add_external_sub(self, path):
        target = ('ext', path)
        if path not in self._sub_ext:
            self._sub_ext.append(path)
            self._loading_tracks = True
            # «Показать другие файлы…», если есть, всегда должен остаться
            # последним пунктом списка — новую дорожку вставляем ПЕРЕД ним,
            # а не просто в конец (иначе выбор «Показать другие» смещался бы).
            more_at = next((i for i, e in enumerate(self._sub_entries)
                            if e[0] == 'more'), None)
            if more_at is None:
                self._sub_entries.append(target)
                self.cmb_subs.addItem(_api.os.path.basename(path))
            else:
                self._sub_entries.insert(more_at, target)
                self.cmb_subs.insertItem(more_at + 1, _api.os.path.basename(path))
            self.cmb_subs.setEnabled(True)
            self._loading_tracks = False
        try:
            idx = self._sub_entries.index(target) + 1   # +1: пункт 0 = «Выкл»
        except ValueError:
            return
        if self.cmb_subs.currentIndex() == idx:
            self.on_sub_track_changed(idx)
        else:
            self.cmb_subs.setCurrentIndex(idx)

    # ── Правка текста субтитров ──────────────────────────────────────────────
    @staticmethod
    def _cues_to_srt(cues):
        def _ts(t):
            if t < 0:
                t = 0.0
            h = int(t // 3600); m = int((t % 3600) // 60); s = t - h * 3600 - m * 60
            return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')
        out = []
        for i, (start, end, body) in enumerate(cues, 1):
            out.append(str(i))
            out.append(f"{_ts(start)} --> {_ts(end)}")
            out.append(body)
            out.append("")
        return "\n".join(out)

    def _current_subs_as_srt(self):
        """Текст активной дорожки субтитров в виде SRT для редактора. Если cues уже
        разобраны (текстовая дорожка) — берём их; иначе (ASS/ещё грузится) —
        извлекаем SRT из источника синхронно. None — текст недоступен (битмап)."""
        if getattr(self, "_sub_cues", None):
            return self._cues_to_srt(self._sub_cues)
        src = getattr(self, "_cur_sub_src", None)
        idx = getattr(self, "_cur_sub_index", -1)
        if getattr(self, "selected_sub_ext_path", None):
            src = self.selected_sub_ext_path; idx = 0
        if not src or idx is None or idx < 0:
            return None
        tmp = None
        try:
            tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
            tmp = tf.name; tf.close()
            cmd = [_api.FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{idx}", tmp]
            kw = {'creationflags': _api.CREATE_NO_WINDOW} if _api.os.name == 'nt' else {}
            _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                           stderr=_api.subprocess.DEVNULL, timeout=60, **kw)
            if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
                with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
        except Exception:
            return None
        finally:
            if tmp:
                try: _api.os.remove(tmp)
                except Exception: pass
        return None

    def _extract_srt_for_entry(self, kind, ref):
        """Текст произвольной дорожки (self._sub_entries) в виде SRT — не
        трогает текущий выбор в cmb_subs/состояние плеера, в отличие от
        _current_subs_as_srt (та работает только с АКТИВНОЙ дорожкой). Нужен
        для «Создать субтитры» → «Редактировать существующую», где дорожка,
        которую правит пользователь, может отличаться от активной."""
        if kind == 'emb':
            src, idx = self.actual_source_file, ref
        else:
            src, idx = ref, 0
            if str(ref).lower().endswith('.srt'):
                try:
                    with open(ref, 'r', encoding='utf-8', errors='replace') as f:
                        return f.read()
                except Exception:
                    pass
        if not src:
            return None
        tmp = None
        try:
            tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
            tmp = tf.name; tf.close()
            cmd = [_api.FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{idx}", tmp]
            kw = {'creationflags': _api.CREATE_NO_WINDOW} if _api.os.name == 'nt' else {}
            _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL,
                           stderr=_api.subprocess.DEVNULL, timeout=60, **kw)
            if _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
                with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
        except Exception:
            return None
        finally:
            if tmp:
                try: _api.os.remove(tmp)
                except Exception: pass
        return None

    def edit_subtitles(self):
        if self.cmb_subs.currentIndex() <= 0:
            _api.msgbox_information(self, "Субтитры",
                                    "Сначала выберите дорожку субтитров.")
            return
        srt = self._current_subs_as_srt()
        if not srt or not srt.strip():
            _api.msgbox_information(
                self, "Субтитры",
                "Не удалось получить текст субтитров для редактирования "
                "(возможно, это субтитры-картинки).")
            return
        try:
            cur_t = self._ui_time_s()
        except Exception:
            cur_t = None
        dlg = _api.SubtitleEditDialog(srt, self, current_time_s=cur_t)
        if dlg.exec() != _api.QDialog.DialogCode.Accepted:
            return
        new_text = dlg.text()
        new_cues = _api._parse_srt(new_text)
        if not new_cues:
            _api.msgbox_warning(self, "Субтитры",
                                "После правки не осталось ни одной реплики.")
            return
        # Стилизованная дорожка (ASS/SSA/mov_text) сохраняется в .ass со
        # стилями оригинала: правился только текст, а голый SRT вшивался бы
        # стилем libass по умолчанию вместо исходного.
        styled = self._styled_edit_result(new_cues)
        ext, payload = (".ass", styled) if styled else (".srt", new_text)
        try:
            _api.os.makedirs(_api.CONFIG_DIR, exist_ok=True)
            base = self.actual_source_file.stem if self.actual_source_file else "subs"
            path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_edited{ext}")
            n = 1
            while _api.os.path.exists(path) and _api.os.path.normpath(path) not in self._sub_ext:
                path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_edited_{n}{ext}"); n += 1
            with open(path, 'w', encoding='utf-8') as f:
                f.write(payload if payload.endswith("\n") else payload + "\n")
        except Exception as e:
            _api.msgbox_warning(self, "Субтитры", f"Не удалось сохранить: {e}")
            return
        path = _api.os.path.normpath(path)
        # Делаем отредактированный файл активной дорожкой (превью + вшивание).
        if path in self._sub_ext:
            self._sub_cues = []
            try:
                idx = self._sub_entries.index(('ext', path)) + 1
            except ValueError:
                self._add_external_sub(path); return
            if self.cmb_subs.currentIndex() == idx:
                self.on_sub_track_changed(idx)
            else:
                self.cmb_subs.setCurrentIndex(idx)
        else:
            self._add_external_sub(path)

    def _styled_edit_result(self, cues):
        """Текст .ass для правленых реплик активной дорожки со стилями её
        оригинала, или None (дорожка без своих стилей — srt/vtt)."""
        entry = getattr(self, "_sub_sel_entry", None)
        if not entry:
            return None
        kind, ref = entry
        try:
            if kind == 'emb':
                src, idx = self.actual_source_file, ref
                codec = (self._sub_streams[ref].get('codec_name') or '').lower()
            elif kind == 'ext':
                src, idx = ref, 0
                codec = _api.os.path.splitext(str(ref))[1].lower().lstrip('.')
            else:
                return None
        except Exception:
            return None
        if codec not in ('ass', 'ssa', 'mov_text') or not src:
            return None
        original = None
        if kind == 'ext' and codec == 'ass':
            try:
                with open(ref, 'r', encoding='utf-8-sig', errors='replace') as f:
                    original = f.read()
            except Exception:
                original = None
        if not original:
            original = subtitle_style.extract_ass(src, idx, codec)
        if not original:
            return None
        return subtitle_style.rebuild_ass(original, cues)

    def create_subtitles(self):
        """«Создать субтитры»: диалог с репликами (текст+тайминг) и позицией на
        экране. Если в Монтаже сейчас выбрана дорожка субтитров (cmb_subs) —
        сразу редактируем ЕЁ (без лишнего диалога-выбора — раньше он всплывал
        каждый раз и раздражал); если ничего не выбрано — начинаем с чистого
        листа. Результат — новый .ass, добавляется как внешняя дорожка (та же
        логика, что и для отредактированного файла в edit_subtitles)."""
        if not self.actual_source_file and not getattr(self, "is_still_image", False):
            _api.msgbox_information(self, "Субтитры", "Сначала откройте видео.")
            return
        # Пока пересобирается прокси (смена качества предпросмотра), self.filepath
        # на мгновение указывает на уже удалённый временный файл (см.
        # _on_pb_quality_changed) — второй плеер диалога открыл бы то, чего нет.
        if self.proxy_thread and self.proxy_thread.isRunning():
            _api.msgbox_information(self, "Субтитры",
                               "Дождитесь подготовки превью и повторите.")
            return
        cues_arg = None
        idx = self.cmb_subs.currentIndex()
        if 0 < idx <= len(self._sub_entries):
            kind, ref = self._sub_entries[idx - 1]
            if kind != 'more':
                srt = self._extract_srt_for_entry(kind, ref)
                cues_arg = _api._parse_srt(srt) if srt else None
                if not cues_arg:
                    _api.msgbox_warning(
                        self, "Субтитры",
                        "Не удалось получить текст этой дорожки для "
                        "редактирования (возможно, это субтитры-картинки).")
                    return
        # Диапазон — ровно та обрезка, что выделена в Монтаже (current_in/
        # current_out), а не всё видео целиком: превью/таймлайн диалога
        # показывают только его.
        range_start = self.current_in
        range_end = self.current_out if self.current_out > range_start else None
        start_hint = range_start
        try:
            pos = self._ui_time_s()
            if range_end is not None:
                start_hint = max(range_start, min(pos, range_end))
            else:
                start_hint = max(range_start, pos)
        except Exception:
            pass
        # self.filepath — РЕАЛЬНО проигрываемый файл (== actual_source_file, либо
        # H.264-прокси для AV1/пониженного качества, см. create_proxy_for_preview) —
        # тот же путь, что и в основном плеере Монтажа. Диалог держит СВОЙ, второй
        # независимый QMediaPlayer (см. _SubtitlePreview) — если скормить ему сырой
        # AV1-исходник напрямую, QtMultimedia молча не отдаёт ни одного кадра
        # (ровно то, ради чего в самом Монтаже и строится прокси).
        source_path = (self.filepath or self.actual_source_file
                       or getattr(self, "still_image_path", None))
        partial_proxy = bool(getattr(self, "is_proxy_active", False)
                             and getattr(self, "_proxy_partial", False))
        # Звук превью — та же дорожка, что выбрана в Монтаже (cmb_audio), а не
        # дефолтная первая дорожка файла (была жалоба на именно это).
        audio_track_index, audio_ext_path = None, None
        ext_path = getattr(self, "selected_audio_ext_path", None)
        if ext_path:
            audio_ext_path = ext_path
        else:
            aidx = self.cmb_audio.currentIndex()
            if 0 <= aidx < len(self._audio_entries):
                kind, ref = self._audio_entries[aidx]
                if kind == 'emb':
                    audio_track_index = ref
        dlg = _api.SubtitleCreatorDialog(source_path=source_path, cues=cues_arg,
                                    start_hint=start_hint,
                                    range_start=range_start, range_end=range_end,
                                    ignore_media_duration=partial_proxy,
                                    default_style=getattr(self, '_last_subtitle_style', None),
                                    audio_track_index=audio_track_index,
                                    audio_ext_path=audio_ext_path,
                                    parent=self)
        # Диалог декодирует ТОТ ЖЕ файл вторым, независимым QMediaPlayer — на
        # некоторых GPU аппаратный декодер (d3d11va/dxva2, см. video_hw_decode)
        # держит лимит одновременных сессий на кодек, и второй сеанс тогда
        # молча не получает ни одного видеокадра (аудио/позиция при этом
        # тикают нормально — подтверждено логом watchdog'а: NoError, позиция и
        # BufferedMedia в порядке, а кадра нет). stop() освобождает декодер
        # плеера Монтажа на время диалога, не трогая источник/дорожки —
        # позиция и воспроизведение восстанавливаются простым seek()'ом после.
        was_playing = self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState
        resume_pos_ms = self.player.position()
        self.player.stop()
        try:
            result = dlg.exec()
        finally:
            try:
                self.player.setPosition(resume_pos_ms)
                if was_playing:
                    self.player.play()
            except Exception:
                pass
        if result != _api.QDialog.DialogCode.Accepted:
            return
        # Запоминаем стиль (шрифт/размер/цвет/…), которым закончил работу
        # пользователь — следующее открытие «Создать субтитры» стартует с него
        # (см. default_style выше и save_settings/load_settings).
        try:
            self._last_subtitle_style = dlg.last_style()
            self.save_settings()
        except Exception:
            pass
        cues = dlg.cues()
        if not cues:
            return
        ass_text = _api._cues_to_ass(cues)
        try:
            _api.os.makedirs(_api.CONFIG_DIR, exist_ok=True)
            base = self.actual_source_file.stem if self.actual_source_file else "subs"
            path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_created.ass")
            n = 1
            while _api.os.path.exists(path) and _api.os.path.normpath(path) not in self._sub_ext:
                path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_created_{n}.ass"); n += 1
            with open(path, 'w', encoding='utf-8') as f:
                f.write(ass_text)
        except Exception as e:
            _api.msgbox_warning(self, "Субтитры", f"Не удалось сохранить: {e}")
            return
        self._add_external_sub(_api.os.path.normpath(path))

    def _add_external_audio(self, path):
        target = ('ext', path)
        if path not in self._audio_ext:
            self._audio_ext.append(path)
            hidden = getattr(self, "_audio_ext_hidden", None)
            if hidden and path in hidden:
                hidden.remove(path)
            # Список собирается заново (файл встаёт перед «Нет», плейсхолдер
            # «— нет —» уходит, счётчик «ещё» верный); выбор пока прежний.
            sel = getattr(self, "_audio_sel_entry", None)
            self._loading_tracks = True
            try:
                self._fill_audio_combo()
                if sel is not None and sel in self._audio_entries:
                    self.cmb_audio.setCurrentIndex(self._audio_entries.index(sel))
            finally:
                self._loading_tracks = False
        try:
            idx = self._audio_entries.index(target)
        except ValueError:
            return
        if self.cmb_audio.currentIndex() == idx:
            self.on_audio_track_changed(idx)
        else:
            self.cmb_audio.setCurrentIndex(idx)

    def _ensure_overlay(self):
        """Лениво создаёт окно-оверлей субтитров и подписывается на Move/Resize
        верхнеуровневого окна (чтобы оверлей следовал за видео)."""
        if self.sub_overlay is None:
            self.sub_overlay = _api.SubtitleOverlay(self.window())
            win = self.window()
            if win is not None and win is not self._overlay_win:
                try:
                    win.installEventFilter(self)
                    self._overlay_win = win
                except Exception:
                    pass
            # Подписки на состояние приложения/фокус окна — ОДИН раз за жизнь
            # вкладки (оверлей может пересоздаваться при смене метода субтитров).
            if not getattr(self, "_overlay_signals_connected", False):
                self._overlay_signals_connected = True
                # Окно поверх всех → прячем, когда приложение неактивно, чтобы текст
                # субтитров не висел поверх других программ при Alt+Tab.
                try:
                    _api.QApplication.instance().applicationStateChanged.connect(
                        self._on_app_state_changed)
                except Exception:
                    pass
                # …и когда активно другое окно приложения (диалог настроек/консоль
                # и т.п.) — иначе субтитры висят поверх него.
                try:
                    _api.QApplication.instance().focusWindowChanged.connect(
                        self._on_focus_window_changed)
                except Exception:
                    pass
        return self.sub_overlay

    def _on_focus_window_changed(self, *args):
        self._position_overlay()

    def _on_app_state_changed(self, state):
        if self.sub_overlay is None:
            return
        if state == _api.Qt.ApplicationState.ApplicationActive:
            self._position_overlay()
        else:
            self.sub_overlay.hide()

    def _position_overlay(self):
        """Подгоняет окно-оверлей под текущую область видео (в окне или в
        полноэкранном режиме) и показывает/прячет его.
        В frame-режиме окна-оверлея нет — субтитры рисует сам холст; здесь лишь
        перерисовываем кадр ASS при изменении геометрии."""
        if self._subs_in_frame:
            if self._sub_use_ass and self._ass is not None:
                try: self._update_subtitle(self._ui_time_s())
                except Exception: pass
            return
        ov = self.sub_overlay
        if ov is None:
            return
        fs = getattr(self, "_fs_window", None)
        if not self._sub_use_overlay or not self.isVisible():
            ov.hide()
            return
        # Если активно другое окно приложения (диалог настроек/консоль и т.п.) —
        # прячем оверлей, чтобы субтитры не висели поверх него.
        try:
            aw = _api.QApplication.activeWindow()
            allowed = {self.window(), fs}
            if aw is not None and aw not in allowed:
                ov.hide()
                return
        except Exception:
            pass
        target = (fs._video if (fs is not None and getattr(fs, "_video", None) is not None)
                  else self.video_widget)
        # Оверлей субтитров — отдельное окно «поверх всех»; его владельцем должно
        # быть то окно, где сейчас видео. Иначе при показе оверлея в полноэкранном
        # режиме Windows вытягивает вперёд окно-владельца (главное окно) и его GUI
        # оказывается поверх видео. Привязываем владельца к текущему окну видео.
        self._reparent_overlay(target.window())
        ov.place_over(target)
        # ASS: подгоняем разрешение рендера под размер оверлея и перерисовываем.
        if self._sub_use_ass and self._ass is not None:
            try:
                self._ass.set_frame_size(ov.width(), ov.height())
                self._update_subtitle(self._ui_time_s())
            except Exception:
                pass
        if not ov.isVisible():
            ov.show()
        ov.raise_()

    def _reparent_overlay(self, owner):
        ov = self.sub_overlay
        if ov is None or owner is None or ov.parent() is owner:
            return
        try:
            flags = ov.windowFlags()
            vis = ov.isVisible()
            ov.setParent(owner, flags)
            ov.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            ov.setAttribute(_api.Qt.WidgetAttribute.WA_TranslucentBackground, True)
            ov.setAttribute(_api.Qt.WidgetAttribute.WA_NoSystemBackground, True)
            ov.setAttribute(_api.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            if vis:
                ov.show()
        except Exception:
            pass

    def on_sub_track_changed(self, idx):
        if self._loading_tracks:
            return
        # Пункт «Показать другие файлы…» — не дорожка, а команда: досыпать
        # отфильтрованные файлы в список и остаться на прежнем выборе (см.
        # _expand_external_subs / _populate_track_combos_subs_only). Список при
        # этом закрывается — его закрывает сам QComboBox на любом выборе, — но
        # раскрыли его ради того, чтобы ВЫБРАТЬ файл из досыпанных, поэтому
        # открываем снова: иначе после каждого клика приходилось лезть в список
        # заново. Через singleShot — сперва Qt должен закончить текущий выбор.
        if 0 < idx <= len(self._sub_entries) and self._sub_entries[idx - 1][0] == 'more':
            self._expand_external_subs()
            _api.QTimer.singleShot(0, self._reopen_subs_popup)
            return
        # Запоминаем РЕАЛЬНО выбранную дорожку: по ней список восстанавливает
        # выбор при перестроении (см. _populate_track_combos_subs_only).
        self._sub_sel_entry = (self._sub_entries[idx - 1]
                               if 0 < idx <= len(self._sub_entries) else None)
        self._stop_sub_extractor()
        self._stop_ass()
        self._sub_cues = []
        self._sub_use_overlay = False
        self._hide_sub_display()
        self.selected_sub_ext_path = None

        # Пункт 0 = «Выкл» → субтитры выключены.
        if idx <= 0 or (idx - 1) >= len(self._sub_entries):
            try: self.player.setActiveSubtitleTrack(-1)
            except Exception: pass
            return

        kind, ref = self._sub_entries[idx - 1]
        if kind == 'emb':
            sub_i = ref
            src = self.actual_source_file
            try:
                codec = (self._sub_streams[sub_i].get('codec_name') or '').lower()
            except Exception:
                codec = ''
        else:
            # Внешний файл субтитров: извлекаем/рендерим прямо из него (stream 0).
            self.selected_sub_ext_path = ref
            sub_i = 0
            src = ref
            codec = _api.os.path.splitext(ref)[1].lower().lstrip('.')

        is_bitmap = codec in self._BITMAP_SUB_CODECS
        if is_bitmap or not src:
            # Битмап-дорожка (или нет источника) → встроенный рендер. Для внешних
            # файлов битмап-кодеков нет, поэтому это только встроенные дорожки.
            if kind == 'emb':
                try: self.player.setActiveSubtitleTrack(sub_i)
                except Exception: pass
            return

        # Текстовые субтитры → свой рендер; встроенный (с плашкой) гасим.
        try: self.player.setActiveSubtitleTrack(-1)
        except Exception: pass
        self._sub_use_overlay = True
        self._prepare_sub_display()
        self._sub_token += 1
        tok = self._sub_token
        # Запоминаем источник субтитров (для отката ASS→SRT в _on_ass_extracted).
        self._cur_sub_src = src
        self._cur_sub_index = sub_i

        if _api.LIBASS_AVAILABLE and codec in ('ass', 'ssa'):
            # ASS/SSA → полный стиль и караоке через libass (рендер в фоне после
            # извлечения дорожки в .ass; при неудаче — откат на текстовый SRT).
            ex = _api.AssExtractor(src, sub_i, tok)
            ex.done.connect(self._on_ass_extracted)
            ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                                if e in self._sub_threads else None)
            self._sub_threads.append(ex)
            self._ass_extractor = ex
            ex.start()
            return

        # Прочие текстовые дорожки (srt/mov_text/webvtt) → чистый текст-оверлей.
        ex = _api.SubtitleExtractor(src, sub_i, tok)
        ex.done.connect(self._on_sub_cues)
        ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                            if e in self._sub_threads else None)
        self._sub_threads.append(ex)
        self._sub_extractor = ex
        ex.start()

    def _reopen_subs_popup(self):
        """Снова раскрывает список дорожек субтитров после «Показать другие
        файлы…»: пользователь раскрывал его, чтобы выбрать файл, а команда
        досыпала их в тот же список."""
        cmb = getattr(self, "cmb_subs", None)
        if cmb is None or not cmb.isEnabled() or not cmb.isVisible():
            return
        try:
            cmb.showPopup()
        except Exception:
            pass

    def _stop_sub_extractor(self):
        ex = getattr(self, "_sub_extractor", None)
        if ex is not None:
            try:
                ex.done.disconnect()
            except Exception:
                pass
            self._sub_extractor = None

    def _stop_ass(self):
        """Останавливает ASS-рендер: таймер, libass, временный .ass и картинку."""
        self._sub_use_ass = False
        ex = getattr(self, "_ass_extractor", None)
        if ex is not None:
            try: ex.done.disconnect()
            except Exception: pass
            self._ass_extractor = None
        t = getattr(self, "_ass_timer", None)
        if t is not None:
            try: t.stop()
            except Exception: pass
        if getattr(self, "_ass", None) is not None:
            try: self._ass.close()
            except Exception: pass
            self._ass = None
        if getattr(self, "_ass_path", None):
            try: _api.os.remove(self._ass_path)
            except Exception: pass
            self._ass_path = None
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            vw.set_subtitle_image(None)
        ov = getattr(self, "sub_overlay", None)
        if ov is not None:
            ov.set_image(None)

    def _ensure_ass_timer(self):
        if self._ass_timer is None:
            t = _api.QTimer(self)
            t.setInterval(60)   # ~16 к/с — достаточно для плавного караоке
            t.timeout.connect(self._on_ass_tick)
            self._ass_timer = t
        if not self._ass_timer.isActive():
            self._ass_timer.start()

    def _on_ass_tick(self):
        """Перерисовка libass во время воспроизведения (караоке, анимации).

        Время берём ТОЛЬКО через _ui_time_s. Раньше здесь стояла сырая
        player.position(), и это был единственный кусок интерфейса, который
        обходил защиту _ui_pinned_ms: во время беззвучного разбега прогрева
        плеер формально играет, а позиция бежит с отметки на полсекунды
        РАНЬШЕ плейхеда — libass честно рисовал субтитры из прошлого, и они
        вспыхивали на каждый покадровый шаг, а потом пропадали."""
        if not self._sub_use_ass or self._ass is None:
            return
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                self._update_subtitle(self._ui_time_s())
        except Exception:
            pass

    def _on_ass_extracted(self, token, path):
        if token != self._sub_token:
            if path:
                try: _api.os.remove(path)
                except Exception: pass
            return
        if not path:
            # libass-извлечение не удалось → откат на текстовый SRT-оверлей.
            self._sub_use_ass = False
            src = getattr(self, "_cur_sub_src", None) or self.actual_source_file
            sub_i = getattr(self, "_cur_sub_index", -1)
            if sub_i >= 0 and src:
                ex = _api.SubtitleExtractor(src, sub_i, token)
                ex.done.connect(self._on_sub_cues)
                ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                                    if e in self._sub_threads else None)
                self._sub_threads.append(ex)
                self._sub_extractor = ex
                ex.start()
            return
        try:
            # Шрифт караоке — у реплик, созданных в «Создать субтитры» стилем
            # по умолчанию (системным провайдером libass он не виден).
            self._ass = _api._libass.AssRenderer(
                fonts=[str(_api._karaoke_style.FONT_FILE)])
            if not self._ass.load_ass_file(path):
                raise RuntimeError("load_ass_file failed")
            self._ass_path = path
            self._sub_use_ass = True
            self._prepare_sub_display()
            self._ensure_ass_timer()
            self._update_subtitle(self._ui_time_s())
        except Exception:
            self._sub_use_ass = False
            if self._ass is not None:
                try: self._ass.close()
                except Exception: pass
                self._ass = None
            try: _api.os.remove(path)
            except Exception: pass

    def _on_sub_cues(self, token, cues):
        if token != self._sub_token:
            return   # пришёл результат от уже неактуального выбора — игнорируем
        self._sub_cues = cues or []
        try:
            self._update_subtitle(self._ui_time_s())
        except Exception:
            pass

    def _subtitle_at(self, pos_s):
        for start, end, body in self._sub_cues:
            if start <= pos_s <= end:
                return body
            if start > pos_s:
                break
        return ""

    def _update_subtitle(self, pos_s):
        # Цель показа: сам холст (frame-режим) или окно-оверлей (overlay-режим).
        tgt = self.video_widget if self._subs_in_frame else self.sub_overlay
        if tgt is None or not hasattr(tgt, "set_subtitle_text"):
            return
        if self._sub_use_ass and self._ass is not None:
            try:
                w, h = tgt.subtitle_area_size()
            except Exception:
                return
            if w <= 0 or h <= 0:
                return
            try:
                self._ass.set_frame_size(w, h)
                arr, ax, ay, changed = self._ass.render(pos_s * 1000.0)
            except Exception:
                arr = None
                changed = True
            # libass говорит, изменилась ли картинка с прошлого рендера — если нет,
            # то, что уже на экране, всё ещё актуально: не гоняем QImage-копию и
            # перерисовку виджета впустую на каждый тик sync_ui (12.5 раз/сек).
            if not changed:
                return
            if arr is None:
                tgt.clear_subtitle()
            else:
                ih, iw = int(arr.shape[0]), int(arr.shape[1])
                qimg = _api.QImage(arr.data, iw, ih, iw * 4,
                              _api.QImage.Format.Format_RGBA8888_Premultiplied).copy()
                tgt.set_subtitle_image(qimg, ax, ay)
            return
        if self._sub_use_overlay:
            tgt.set_subtitle_text(self._subtitle_at(pos_s))

        # Субтитры выключены — ничего не рисуем (очистка уже сделана при смене
        # дорожки через _hide_sub_display), чтобы не дёргать перерисовку.

    def _apply_active_tracks(self, *args):
        """tracksChanged: применяет выбор из комбобоксов, когда плеер обнаружил дорожки."""
        try:
            ai = self.cmb_audio.currentIndex()
            if ai is not None and ai >= 0:
                self.player.setActiveAudioTrack(ai)
        except Exception:
            pass
        try:
            si = self.cmb_subs.currentIndex()
            self.player.setActiveSubtitleTrack((si - 1) if si is not None else -1)
        except Exception:
            pass

    def _subtitles_vf(self, src, ext_sub=None, burn_idx=-1):
        """Фильтр ffmpeg `subtitles=…` для вшивания выбранной дорожки, или None.

        Одно место на оба пути экспорта: собственную перекодировку Монтажа
        (_execute_cut) и «перекодировать настройками «Обработки»» (там тот же
        фильтр уезжает в ProcessWorker, см. _execute_cut_and_process).

        libass рендерит ASS со всеми стилями; для родных ШРИФТОВ извлекаем
        вложенные attachments контейнера и отдаём их через :fontsdir."""
        if ext_sub:
            esc = self._escape_filter_path(ext_sub)
            vf = f"subtitles='{esc}'"
            sub_codec = _api.os.path.splitext(ext_sub)[1].lower().lstrip('.')
        else:
            if burn_idx is None or burn_idx < 0:
                return None
            esc = self._escape_filter_path(src)
            vf = f"subtitles='{esc}':si={burn_idx}"
            try:
                sub_codec = (self._sub_streams[burn_idx].get('codec_name') or '').lower()
            except Exception:
                sub_codec = ''
        # Стиль вшиваемых субтитров — по выбору пользователя (cmb_sub_style):
        #   0 Авто      — стиль программы для SRT/VTT/mov_text, у ASS/SSA свой;
        #   1 Программа — насильно стиль программы даже поверх ASS/SSA;
        #   2 Оригинал  — свой стиль у ASS/SSA/mov_text. У SRT/VTT своего стиля
        #                 нет вовсе — им стиль программы, тот же, что в превью
        #                 (раньше вшивался голый Arial libass, а в плеере был
        #                 другой вид).
        # Стиль программы — как у караоке в генерации паков (prog_sub_force_style).
        try:
            style_choice = int(self.cmb_sub_style.currentIndex())
        except Exception:
            style_choice = 0
        native_styled = sub_codec in ('ass', 'ssa')
        if style_choice == 1:
            apply_prog_style = True
        elif style_choice == 2:
            apply_prog_style = not (native_styled or sub_codec == 'mov_text')
        else:
            apply_prog_style = not native_styled
        if not apply_prog_style and not ext_sub and sub_codec == 'mov_text':
            # Оригинальный mov_text: его шрифт задан в пикселях кадра, а ffmpeg
            # сам ставит холст 384×288 — выходили субтитры в полэкрана. Вшиваем
            # ASS-копию с холстом по размеру видео (subtitle_style).
            fixed = subtitle_style.mov_text_burn_file(src, burn_idx)
            if fixed:
                vf = f"subtitles='{self._escape_filter_path(fixed)}'"
        if apply_prog_style:
            # Караоке-вид — РОВНО как в превью Монтажа (_paint_subtitle считает
            # пиксели по тем же правилам libass). Текстовые субтитры ffmpeg
            # рендерит на холсте 384×288 и масштабирует до кадра, поэтому кегль
            # в долях кадра один на любом разрешении. У ASS холст свой — кегль
            # пересчитывается на его PlayResY, иначе на холсте 1080 текст вышел
            # бы вчетверо мельче.
            play_res_y = (self._ass_play_res_y(src, ext_sub, burn_idx)
                          if native_styled else None)
            vf += f":force_style='{_api.prog_sub_force_style(play_res_y)}'"
        fonts_dir = self._subtitle_fonts_dir(src)
        if fonts_dir:
            fesc = self._escape_filter_path(fonts_dir)
            vf += f":fontsdir='{fesc}'"
        return vf

    def _ass_play_res_y(self, src, ext_sub=None, burn_idx=-1):
        """PlayResY дорожки ASS/SSA для вшивания (None — не прочитать)."""
        text = None
        if ext_sub:
            try:
                with open(ext_sub, 'r', encoding='utf-8-sig', errors='replace') as f:
                    text = f.read()
            except Exception:
                text = None
        elif burn_idx is not None and burn_idx >= 0:
            text = subtitle_style.extract_ass(src, burn_idx)
        return subtitle_style.play_res_y(text) if text else None

    def _subtitle_fonts_dir(self, src):
        """Папка шрифтов для вшивания: вложенные шрифты контейнера (родные
        стили ASS) плюс шрифт караоке — им рисуется стиль программы и он же
        стиль «Создать субтитры» по умолчанию. ffmpeg принимает одну папку,
        поэтому шрифт караоке кладётся к извлечённым."""
        karaoke_font = _api._karaoke_style.FONT_FILE
        fonts_dir = self._extract_subtitle_fonts(src)
        if not fonts_dir:
            return str(karaoke_font.parent)
        target = _api.os.path.join(fonts_dir, karaoke_font.name)
        if not _api.os.path.exists(target):
            try:
                _api.shutil.copyfile(str(karaoke_font), target)
            except Exception:
                pass
        return fonts_dir

    def _burn_subs_spec(self, src, in_s):
        """Описание вшивания субтитров для вкладки «Обработка», или None.

        Возвращает {'vf': <фильтр subtitles=…>, 'src_offset': <секунды>}.

        `src_offset` — это разница между временем ИСХОДНИКА и временем
        фильтрграфа у ProcessWorker. Он режет отрезок быстрым входным
        pre-seek'ом (см. _trim_seek_args), а входной seek обнуляет тайминги в
        своей точке — фильтр же subtitles ищет реплики по времени САМОГО файла
        субтитров. Без поправки текст уехал бы на (in_s − PRESEEK) секунд.
        Саму поправку накладывает ProcessWorker (setpts вокруг фильтра): только
        он знает, какой pre-seek выбрал."""
        vf = self._subtitles_vf(src, self.selected_sub_ext_path,
                                self.cmb_subs.currentIndex() - 1)
        if not vf:
            return None
        return {'vf': vf, 'src_in': float(max(0.0, in_s))}
