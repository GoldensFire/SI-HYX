# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: проект из кусков, как в Filmora. Шкала у вкладки одна — таймлайн
проекта.

Открытый файл сразу целиком ложится на основную дорожку «Видео 1». Дальше всё
на таймлайне: Ctrl+B режет клип у плейхеда, Shift+C / Shift+V обрезают начало
и конец клипа до плейхеда, края клипов тянутся мышью, Delete удаляет (на
основной дорожке дыра закрывается сама), Ctrl+C копирует выделенные клипы, а
Ctrl+V вставляет их у плейхеда (Project.paste). Ещё файлы — «＋» или бросок на
таймлайн: встают в конец. Клипы уходят на верхнюю видеодорожку (перекрывают
кадр) или на звуковые через меню; «Отделить звук» выносит звук видеоклипа
отдельным клипом, «Скорость» ускоряет видео и звук клипа.

Плеер всегда показывает проект: плейхед таймлайна и плеер связаны в обе
стороны (клик по шкале — плеер на клипе; шаг кадра, игра — плейхед за ним).
Сохранение одной кнопкой: проект из одного куска одного файла уходит прежней
«Обрезкой» (Smart Cut, кадрирование, субтитры — IN/OUT источника держатся по
клипу), иначе проект собирается одной командой ffmpeg (montage_project).
Звуковые дорожки, звук под наложением и громкость клипов в просмотре слышны
через «голоса» (project_audio).

Модель — montage_project.Project; виджет — edit_tab_widgets.ProjectTimeline.
Проект сохраняется сам (MONTAGE_PROJECT_PATH) и переживает перезапуск."""
import bisect
import dataclasses
from collections import OrderedDict

import hdr_tonemap
import montage_project as _mp

import edit_tab as _api

# Длинная команда ffmpeg: граф фильтров уходит в файл (-/filter_complex) —
# у Windows предел командной строки 32767 символов, а на каждый кусок
# приходится путь к файлу и строка фильтров.
_INLINE_GRAPH_MAX = 6000
# Кадров полосы превью в памяти (~10 КБ каждый) — дальше вытесняются старые.
_THUMB_CACHE_MAX = 900


class EditTabProjectMixin:
    """Монтаж: проект из кусков — панель, правка, просмотр и сборка."""

    # ── Состояние ────────────────────────────────────────────────────────────
    def _project_init(self):
        """Вызывается из __init__ до сборки интерфейса."""
        self._proj_save_blocked = False   # файл проекта не загрузился и не отложен
        self.project = self._project_load_saved()
        self._proj_undo = _api.deque(maxlen=100)
        self._proj_redo = _api.deque(maxlen=100)
        self._proj_active = not self.project.is_empty()   # плеер на проекте
        self._proj_play = None         # план просмотра (список кусков) или None
        self._proj_idx = 0
        self._proj_limit_s = None      # конец текущего куска во времени источника
        self._proj_transition = False  # пауза между кусками — не остановка просмотра
        self._proj_pending = None      # что сделать, когда догрузится другой файл
        self._proj_cur_id = ""         # клип, который сейчас показывает плеер
        self._proj_internal_load = False   # файл открывает сам проект (кусок)
        self._proj_collapsed = False
        # Кадры полосы превью: ключ → QPixmap (None — заказан, False — не вышел)
        # и по каждому файлу — отсортированные (время, ключ) готовых кадров.
        self._proj_thumbs = OrderedDict()
        self._proj_thumb_index = {}
        self._proj_thumb_worker = None
        self._proj_thumb_timer = None
        self._proj_waves = {}          # волна файла: путь → (сэмплы, длительность)
        self._proj_clipboard = []      # копии клипов для Ctrl+V (project_copy)
        self._pmix_init()              # звук дорожек в просмотре (project_audio)
        self._snd_init()               # звук просмотра своим трактом (project_sound)

    # ── Панель ───────────────────────────────────────────────────────────────
    def _build_project_panel(self):
        """Таймлайн проекта во всю ширину вкладки — единственная шкала
        монтажа. Кнопки правки живут в строке плеера (layout._build_player_bar)."""
        panel = _api.QFrame()
        panel.setObjectName("ProjectPanel")
        panel.setStyleSheet(f"#ProjectPanel {{ background: {_api.C['surface']}; "
                            f"border-top: 1px solid {_api.C['border']}; }}")
        lay = _api.QVBoxLayout(panel)
        lay.setContentsMargins(8, 2, 8, 4)
        lay.setSpacing(2)

        # Чего живой плеер не покажет (он играет клипы по одному и без
        # эффектов): видно только в собранном файле и в превью montage_tool.
        self.lbl_proj_preview_gap = _api.QLabel()
        self.lbl_proj_preview_gap.setWordWrap(True)
        self.lbl_proj_preview_gap.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px;")
        self.lbl_proj_preview_gap.hide()
        lay.addWidget(self.lbl_proj_preview_gap)

        tl = _api.ProjectTimeline(self.project)
        tl.thumb_provider = self._project_thumb
        tl.wave_provider = self._project_wave
        tl.can_paste = lambda: bool(self._proj_clipboard)
        tl.seekRequested.connect(self._project_seek)
        tl.scrubStarted.connect(self._project_scrub_started)
        tl.scrubFinished.connect(self._project_scrub_finished)
        tl.selectionChanged.connect(lambda _cid: self._project_update_ui())
        tl.editStarted.connect(self._project_snapshot)
        tl.edited.connect(self._project_changed)
        tl.actionRequested.connect(self._project_action)
        tl.viewChanged.connect(self._project_sync_scroll)
        self.project_timeline = tl
        lay.addWidget(tl)

        self.proj_scroll = _api.QScrollBar(_api.Qt.Orientation.Horizontal)
        self.proj_scroll.setStyleSheet(self.wave_scroll.styleSheet())
        self.proj_scroll.valueChanged.connect(self._project_on_scroll)
        lay.addWidget(self.proj_scroll)
        self._project_panel = panel
        self._project_sync_scroll()
        self._project_update_ui()
        note = getattr(self, "_proj_load_note", "")
        if note:
            # Подпись строки состояния появится позже панели — после сборки окна.
            _api.QTimer.singleShot(0, lambda: self._proj_status(note))
        return panel

    def _project_apply_collapsed(self):
        """Сворачивания больше нет: таймлайн — единственная шкала вкладки.
        Метод оставлен для старых настроек (project_collapsed)."""
        self._proj_collapsed = False

    def _project_sync_scroll(self):
        tl = getattr(self, "project_timeline", None)
        sb = getattr(self, "proj_scroll", None)
        if tl is None or sb is None:
            return
        span = tl.visible_span()
        total = tl.scroll_limit()
        sb.blockSignals(True)
        sb.setRange(0, int(total * 100))
        sb.setPageStep(max(1, int(span * 100)))
        sb.setValue(int(tl.offset * 100))
        sb.blockSignals(False)
        # Проект целиком в окне — прокручивать нечего (запас за концом не в счёт).
        sb.setVisible(total > span * 0.05)

    def _project_on_scroll(self, value):
        self.project_timeline.set_offset(value / 100.0)

    def _project_update_ui(self):
        """Подписи и доступность кнопок правки, общее время и кнопка
        «Экспорт» с длительностью итога."""
        if getattr(self, "project_timeline", None) is None:
            return
        n = len(self.project.clips)
        sel = self.project.clip(self.project_timeline.selected)
        self.btn_proj_delete.setEnabled(sel is not None)
        for b in (self.btn_proj_split, self.btn_trim_start, self.btn_trim_end):
            b.setEnabled(n > 0)
        self.btn_proj_undo.setEnabled(bool(self._proj_undo) or (n == 0 and bool(self.undo_stack)))
        self.btn_proj_redo.setEnabled(bool(self._proj_redo))
        self._update_total_time()
        self.update_selection_label()
        gap_lbl = getattr(self, "lbl_proj_preview_gap", None)
        if gap_lbl is not None:
            gaps = self.project.live_preview_gaps()
            gap_lbl.setText("Просмотр во вкладке играет клипы без эффектов. "
                            f"Только в собранном файле и в превью montage_tool: {', '.join(gaps)}."
                            if gaps else "")
            gap_lbl.setVisible(bool(gaps))
        if n > 0:
            # Плеер на проекте: играть есть что, даже если на экране картинка.
            self.btn_play.setEnabled(True)
        b = getattr(self, "btn_cut", None)
        single = n == 0 or self._proj_single_clip() is not None
        still = getattr(self, "is_still_image", False)
        if (b is not None and not getattr(self, "_cut_btn_cancel", False)
                and not (still and single)):
            self._set_export_btn_mode("Экспорт", 'fa5s.file-export')
            b.setToolTip("Сохранить кусок в файл" if single
                         else "Склеить клипы проекта в один файл (Ctrl+S)")
            if n > 0:
                b.setEnabled(True)

    def _project_load_saved(self):
        """Проект из MONTAGE_PROJECT_PATH. Файл, который не загрузился (битый
        JSON, версия новее программы), не затирается первой же правкой: он
        откладывается рядом (…json.unreadable-ДАТА), и тогда берётся его .bak;
        не вышло отложить — проект не сохраняется до перезапуска."""
        path = _api.MONTAGE_PROJECT_PATH
        for _attempt in range(2):        # сам файл, затем его .bak
            try:
                return _mp.load_project(path)
            except _mp.ProjectError as e:
                bad = e.path or path
                aside = f"{bad}.unreadable-{_api.time.strftime('%Y%m%d-%H%M%S')}"
                try:
                    _api.os.replace(bad, aside)
                except OSError:
                    self._proj_save_blocked = True
                    self._proj_load_note = f"проект не загружен ({e}) и не сохраняется: {bad}"
                    return _mp.Project()
                self._proj_load_note = f"проект не загружен ({e}), файл отложен: {aside}"
            except Exception as e:
                self._proj_save_blocked = True
                self._proj_load_note = f"проект не загружен и не сохраняется: {e}"
                return _mp.Project()
        return _mp.Project()

    def _project_save(self):
        """Сохраняет проект в MONTAGE_PROJECT_PATH (не затирая файл, который
        не загрузился, — см. _project_load_saved)."""
        if getattr(self, "_proj_save_blocked", False):
            return
        try:
            _api.os.makedirs(_api.os.path.dirname(_api.MONTAGE_PROJECT_PATH), exist_ok=True)
            _mp.save_project(self.project, _api.MONTAGE_PROJECT_PATH)
        except Exception:
            pass

    def _proj_status(self, text):
        try:
            self.log_label.setText(text)
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"Монтаж, проект: {text}")
        except Exception:
            pass

    # ── Правка ───────────────────────────────────────────────────────────────
    def _project_snapshot(self):
        """Снимок ДО правки — для отмены (Ctrl+Z)."""
        self._proj_undo.append(self.project.to_dict())
        self._proj_redo.clear()

    def _project_changed(self):
        """Правка закончена: сохранить, перерисовать, остановить просмотр и
        подогнать IN/OUT источника под клип."""
        if self._proj_play is not None:
            self.project_stop()
        self._proj_active = not self.project.is_empty()
        self._project_save()
        self.project_timeline.refresh()
        self._project_sync_source()
        self._project_update_ui()
        self._snd_schedule_prepare()

    def _project_replace(self, project):
        self.project = project
        self.project_timeline.set_project(project)
        self._project_changed()
        # Отмена могла вернуть клипы другого файла (или вернуть их после
        # «Очистить») — плеер показывает то, что теперь под плейхедом.
        if not project.is_empty():
            tl = self.project_timeline
            t = min(tl.playhead, max(0.0, project.duration() - 0.04))
            tl.set_playhead(t, follow=False)
            self._project_seek(t)

    def project_undo(self):
        if not self._proj_undo:
            return
        self._proj_redo.append(self.project.to_dict())
        self._project_replace(_mp.Project.from_dict(self._proj_undo.pop()))

    def project_redo(self):
        if not self._proj_redo:
            return
        self._proj_undo.append(self.project.to_dict())
        self._project_replace(_mp.Project.from_dict(self._proj_redo.pop()))

    def _project_has_focus(self):
        tl = getattr(self, "project_timeline", None)
        return tl is not None and tl.hasFocus()

    def _proj_single_clip(self):
        """Клип, если проект — один непрерывный кусок одного файла без своей
        громкости (в том числе разрезанный, но не тронутый: куски встык и по
        порядку). Такой проект сохраняет прежняя «Обрезка» (Smart Cut,
        кадрирование, пикселизация, субтитры). Иначе None. У разрезанного
        возвращается копия первого куска с концом последнего."""
        p = self.project
        if not p.clips:
            return None
        first = p.clips[0]
        if any(c.track != first.track for c in p.clips):
            return None
        # Видео — на основной дорожке; звуковой файл — где угодно.
        if (first.has_video and first.track != p.main_track) or not p.tracks[first.track].enabled:
            return None
        if p.tracks[first.track].muted:
            return None                 # звук дорожки выключен — «Обрезка» его не знает
        run = p.clips_on(first.track)
        for a, b in zip(run, run[1:]):
            if (b.src != a.src or b.audio_path != a.audio_path
                    or abs(b.in_s - a.out_s) > 1e-3 or abs(b.start - a.end) > 1e-3):
                return None
        if any(c.muted or abs(c.volume - 1.0) > 1e-6
               or abs(c.speed - 1.0) > 1e-6 or c.audio_detached for c in run):
            return None
        if len(run) == 1:
            return run[0]
        return _mp.Clip(**{**{f: getattr(run[0], f) for f in run[0].__dataclass_fields__},
                           'out_s': run[-1].out_s})

    def _project_sync_source(self):
        """IN/OUT источника — по клипу одиночного проекта (по ним режет
        «Экспорт» и встаёт воспроизведение); у проекта из нескольких кусков
        — весь файл: границы кусков держит сам просмотр проекта."""
        if self.duration <= 0 or getattr(self, "is_still_image", False):
            return
        if self.project.is_empty():
            return
        c = self._proj_single_clip()
        if c is not None and self._proj_is_loaded(c.src):
            in_s, out_s = c.in_s, min(c.out_s, self.duration)
        else:
            in_s, out_s = 0.0, self.duration
        if abs(in_s - self.current_in) > 1e-4 or abs(out_s - self.current_out) > 1e-4:
            self.set_in_out(in_s, out_s, skip_undo=True)

    def _source_audio(self):
        """(путь, абсолютный индекс потока) звука, который сейчас выбран в
        источнике, или ("", -1) — звук выключен или его нет."""
        if getattr(self, "audio_disabled", False):
            return "", -1
        ext = getattr(self, "selected_audio_ext_path", None)
        if ext and _api.os.path.exists(ext):
            return str(ext), -1
        if not getattr(self, "_audio_streams", None):
            return "", -1
        idx = self.selected_audio_abs_index
        if idx is None:
            idx = self.audio_stream_index
        return str(self.actual_source_file), (int(idx) if idx is not None else -1)

    def _project_burn_subs(self):
        """Вшивание субтитров в проект: {ключ файла: фильтр subtitles=…} для
        открытого файла, если стоит «Вшить субтитры» и выбрана дорожка и в
        проекте есть его куски; иначе None. Выбор дорожки относится к открытому
        файлу (индекс si= — его), поэтому куски других файлов идут без субтитров."""
        if not (self.chk_burn_subs.isChecked() and self.cmb_subs.currentIndex() > 0):
            return None
        src = self.actual_source_file
        if not src or getattr(self, "is_still_image", False):
            return None
        if not any(c.has_video and not c.is_image and self._proj_is_loaded(c.src)
                   for c in self.project.clips):
            return None
        vf = self._subtitles_vf(src, self.selected_sub_ext_path,
                                self.cmb_subs.currentIndex() - 1)
        return {_mp.source_key(src): vf} if vf else None

    def _project_restore_audio(self):
        """Открыли файл, куски которого лежат в проекте, → в списке дорожек
        выбираем звук этих кусков. Иначе список вставал на первую встроенную
        дорожку, а проект играл и собирал запомненную в кусках озвучку.
        True — звук этого файла задают куски проекта."""
        if getattr(self, "project_timeline", None) is None or self.project.is_empty():
            return False
        if getattr(self, "is_still_image", False):
            return False
        clip = next((c for c in sorted(self.project.clips, key=lambda c: c.start)
                     if c.has_video and not c.is_image and not c.audio_detached
                     and self._proj_is_loaded(c.src)),
                    None)
        if clip is None:
            return False
        target = None
        if not clip.audio_path:
            target = ('none', None)
        elif self._proj_norm(clip.audio_path) != self._proj_norm(self.actual_source_file):
            want = self._proj_norm(clip.audio_path)
            target = next((e for e in self._audio_entries
                           if e[0] == 'ext' and self._proj_norm(e[1]) == want), None)
            if target is None and _api.os.path.exists(clip.audio_path):
                self._add_external_audio(clip.audio_path)
                return True
        else:
            want = clip.audio_stream
            for i, s in enumerate(self._audio_streams):
                if want < 0 or s.get('index') == want:
                    target = ('emb', i)
                    break
        if target is None or target not in self._audio_entries:
            return True
        idx = self._audio_entries.index(target)
        if idx != self.cmb_audio.currentIndex():
            self.cmb_audio.setCurrentIndex(idx)
        return True

    def _project_retarget_audio(self):
        """В источнике выбрали другую дорожку или озвучку → видеоклипы этого
        файла звучат ею. Клип запоминает звук, когда кладётся в проект, и
        просмотр проекта играл прежнюю дорожку голосом, а выбранную глушил:
        для него основной плеер звучал «не тем» звуком клипа."""
        if getattr(self, "project_timeline", None) is None or self.project.is_empty():
            return
        if getattr(self, "is_still_image", False):
            return
        path, idx = self._source_audio()
        changed = []
        for c in self.project.clips:
            if (c.is_image or not c.has_video or c.audio_detached
                    or not self._proj_is_loaded(c.src)):
                continue
            if c.audio_path != path or c.audio_stream != idx:
                c.audio_path, c.audio_stream = path, idx
                changed.append(c.id)
        if not changed:
            return
        self._project_save()
        if self._proj_play is not None and self._snd_active:
            # Звук тракта сведён со старой дорожкой — просмотр заново с того
            # же места: звук и картинка стартуют вместе уже с новой.
            self.project_timeline.refresh()
            self.project_stop()
            self.project_play()
            return
        if self._proj_play is not None:
            # Просмотр идёт: голоса со старым звуком закрыть, состав того, что
            # слышно, — заново (часы проекта не трогаем).
            for cid in changed:
                self._pmix_release(cid)
            parts = self.project.audio_parts()
            self._pmix_parts = {c.id: c for c in parts}
            self._pmix_need = {c.id for c in parts if self._pmix_needs_voice(c)}
            self._pmix_tick()
        self.project_timeline.refresh()

    def project_add_selection(self, where='main', snapshot=True):
        """Кладёт кусок открытого файла (IN–OUT) в проект: на основной дорожке
        — в конец, поверх кадра или звуком — у плейхеда."""
        src = self.actual_source_file
        if not src or not _api.os.path.exists(str(src)) or self.duration <= 0:
            return None
        still = bool(getattr(self, "is_still_image", False))
        has_video = still or self.video_stream_index is not None
        audio_path, audio_stream = ("", -1) if still else self._source_audio()
        if where == 'audio' or not has_video:
            if not audio_path:
                _api.msgbox_information(self, "Проект", "У этого файла нет ни видео, ни звука.")
                return None
            where = 'audio'
        fps = 0.0 if still else float(self.fps or 0.0)
        in_s, out_s = float(self.current_in), float(self.current_out)
        if still:
            in_s, out_s = 0.0, float(getattr(self, "_still_duration", 5.0) or 5.0)
        elif fps > 0:
            # Как у «Экспорт»: кадр, который показан на IN, и кадр, на котором
            # стоит OUT, — границы куска ложатся на сетку кадров.
            in_s = _mp.snap_to_frame(in_s, fps)
            out_s = min(self.duration, round(out_s * fps) / fps)
        if out_s - in_s < _mp.MIN_CLIP_S:
            return None
        if still:
            width, height = int(getattr(self, "_still_w", 0)), int(getattr(self, "_still_h", 0))
        else:
            # Как на экране, а не размер потока: у видео с телефона поток
            # 1920x1080 с поворотом 90° давал проекту альбомный формат.
            width = int(getattr(self, "_src_display_w", 0) or 0)
            height = int(getattr(self, "_src_display_h", 0) or 0)
        p = self.project
        playhead = self.project_timeline.playhead
        if where == 'audio' and has_video is False and p.is_empty():
            # Звуковой файл в пустом проекте — с начала шкалы.
            playhead = 0.0
        if where == 'audio':
            track = p.tracks_of('audio')[0] if p.tracks_of('audio') else p.add_track('audio')
            start = playhead
        elif where == 'overlay':
            upper = [ti for ti in p.tracks_of('video') if ti != p.main_track]
            track = upper[0] if upper else p.add_track('video')
            start = playhead
        else:
            track, start = p.main_track, 0.0
        clip = _mp.Clip(src=str(src), in_s=in_s, out_s=out_s, track=track, start=start,
                        has_video=(where != 'audio'), is_image=still,
                        audio_path=audio_path, audio_stream=audio_stream,
                        width=width, height=height, fps=fps,
                        src_duration=float(self.duration))
        was_empty = p.is_empty()
        if snapshot:
            self._project_snapshot()
        p.append(clip)
        self.project_timeline.selected = ""
        self._proj_cur_id = clip.id
        self._project_changed()
        # Плейхед — на начало нового клипа: плеер как раз стоит на его первом
        # кадре (файл только что открыт).
        self.project_timeline.set_playhead(clip.start)
        if was_empty:
            _api.QTimer.singleShot(0, self.project_timeline.zoom_to_fit)
        return clip

    def _project_target(self, cid=None):
        """Клип для правки у плейхеда: явный; иначе выбранный, если плейхед на
        нём; иначе клип под плейхедом — сперва на основной дорожке, потом
        сверху вниз."""
        p = self.project
        t = self.project_timeline.playhead
        if cid:
            return p.clip(cid)
        clip = p.clip(self.project_timeline.selected)
        if clip is not None and clip.start < t < clip.end:
            return clip
        for ti in [p.main_track] + [x for x in p.display_order() if x != p.main_track]:
            c = p.clip_at(ti, t)
            if c is not None:
                return c
        return None

    def project_split(self, cid=None):
        clip = self._project_target(cid)
        t = self.project_timeline.playhead
        if clip is None or not (clip.start < t < clip.end):
            self._proj_status("плейхед не стоит на клипе — резать нечего")
            return
        self._project_snapshot()
        parts = self.project.split(clip.id, t)
        if parts is None:
            self._proj_undo.pop()
            self._proj_status("слишком близко к краю клипа")
            return
        self.project_timeline.selected = parts[1].id
        self._proj_cur_id = parts[1].id
        self._project_changed()

    def project_set_speed(self, cid, speed):
        """Меняет скорость клипа (видео и его звук или звуковой клип).
        Кусок исходника тот же — на шкале он становится короче или длиннее."""
        clip = self.project.clip(cid)
        if clip is None or clip.is_image:
            return
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            return
        if not _api.math.isfinite(speed):
            return
        speed = max(_mp.MIN_SPEED, min(_mp.MAX_SPEED, speed))
        if abs(clip.speed - speed) < 1e-6:
            return
        self._project_snapshot()
        if not self.project.set_speed(clip.id, speed):
            self._proj_undo.pop()
            return
        self.project_timeline.selected = clip.id
        self._proj_cur_id = clip.id
        self._project_changed()
        t = min(clip.start, max(0.0, self.project.duration() - 0.04))
        self.project_timeline.set_playhead(t, follow=False)
        self._project_seek(t)

    def project_detach_audio(self, cid):
        """«Отделить звук»: звук видеоклипа становится отдельным клипом на
        звуковой дорожке. Видеоклип остаётся без звука, оба можно двигать,
        резать и ускорять независимо."""
        clip = self.project.clip(cid)
        if clip is None or not clip.has_video or clip.is_image or not clip.audio_path:
            return
        self._project_snapshot()
        p = self.project
        # Дорожка без клипов на этом месте: отделённый звук остаётся ровно под
        # видео. Занято на всех — новая дорожка, а не сдвиг в конец соседа.
        track = next((ti for ti in p.tracks_of('audio')
                      if all(o.end <= clip.start + 1e-6 or o.start >= clip.end - 1e-6
                             for o in p.clips_on(ti))), None)
        if track is None:
            track = p.add_track('audio')
        audio = _mp.Clip(src=clip.audio_path, in_s=clip.in_s, out_s=clip.out_s,
                         track=track, start=clip.start, has_video=False,
                         audio_path=clip.audio_path, audio_stream=clip.audio_stream,
                         volume=clip.volume, muted=clip.muted, speed=clip.speed,
                         fps=clip.fps, src_duration=clip.src_duration)
        clip.audio_path = ""
        clip.audio_stream = -1
        clip.audio_detached = True
        p.append(audio)
        self.project_timeline.selected = audio.id
        self._proj_cur_id = audio.id
        self._project_changed()

    def project_trim_to_playhead(self, edge):
        """Обрезать начало (edge='left') или конец клипа до плейхеда — как
        «Обрезать начало/конец до плейхеда» в Filmora. На основной дорожке
        соседи подтягиваются вплотную, плейхед встаёт на новый стык."""
        clip = self._project_target()
        t = self.project_timeline.playhead
        if clip is None or not (clip.start < t < clip.end):
            self._proj_status("плейхед не стоит на клипе — обрезать нечего")
            return
        before = (clip.in_s, clip.out_s, clip.start)
        self._project_snapshot()
        self.project.trim(clip.id, edge, t)
        if (clip.in_s, clip.out_s, clip.start) == before:
            self._proj_undo.pop()
            return
        self._proj_cur_id = clip.id
        self._project_changed()
        if edge == 'left':
            # На экране тот же кадр — теперь он первый кадр клипа.
            self.project_timeline.set_playhead(clip.start)
            self._paint_project_time(clip.start)
        else:
            self._project_seek(clip.end)

    def project_delete(self, cid=None):
        """Удаляет клип cid, а если он среди выделенных (или cid не задан) —
        все выделенные (рамкой / Ctrl+клик), одним шагом отмены."""
        sel = self.project_timeline.selected_ids()
        ids = sel if (not cid or cid in sel) else [cid]
        ids = [i for i in ids if self.project.clip(i) is not None]
        if not ids:
            return
        self._project_snapshot()
        for i in ids:
            self.project.remove(i)
        self.project_timeline.selected = ""
        self._project_changed()
        if not self.project.is_empty():
            t = min(self.project_timeline.playhead,
                    max(0.0, self.project.duration() - 0.04))
            self._project_seek(t)

    def project_copy(self, cid=None):
        """Ctrl+C: клип cid, а если он среди выделенных (или cid не задан) —
        все выделенные; без выделения — клип под плейхедом. В буфере копии:
        дальнейшая правка клипов на таймлайне его не меняет."""
        sel = self.project_timeline.selected_ids()
        ids = sel if (not cid or cid in sel) else [cid]
        clips = [c for c in (self.project.clip(i) for i in ids) if c is not None]
        if not clips:
            c = self._project_target()
            clips = [c] if c is not None else []
        if not clips:
            self._proj_status("нечего копировать — выделите клип")
            return
        self._proj_clipboard = [dataclasses.replace(c) for c in clips]
        self._proj_status("клип скопирован — Ctrl+V вставит его у плейхеда" if len(clips) == 1
                          else f"скопировано клипов: {len(clips)} — Ctrl+V вставит их у плейхеда")

    def project_paste(self):
        """Ctrl+V: клипы из буфера — у плейхеда, одним шагом отмены. Плейхед
        встаёт за вставкой: следующая вставка ляжет следом."""
        if not self._proj_clipboard:
            self._proj_status("вставлять нечего — сначала скопируйте клип (Ctrl+C)")
            return
        self._project_snapshot()
        new = self.project.paste(self._proj_clipboard, self.project_timeline.playhead)
        if not new:
            self._proj_undo.pop()
            return
        main = [c for c in new if c.track == self.project.main_track]
        self.project_timeline.select({c.id for c in new}, (main or new)[0].id)
        self._project_changed()
        end = max(c.end for c in (main or new))
        self._project_seek(min(end, self._proj_last_frame_t()))

    def project_clear(self):
        """Убирает все клипы (отмена — Ctrl+Z). Вызывается из «Очистить»."""
        if self.project.is_empty():
            return
        self._project_snapshot()
        self.project_stop()
        self._project_replace(_mp.Project())
        self.project_timeline.set_playhead(0.0)
        self._proj_cur_id = ""

    def project_add_file(self):
        """«＋»: файл целиком — в конец основной дорожки."""
        fname, _ = _api.QFileDialog.getOpenFileName(
            self, "Добавить в проект", "",
            "Медиа файлы (*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.aac *.m4a *.wav *.flac "
            "*.png *.jpg *.jpeg *.bmp *.webp *.gif);;Все файлы (*)")
        if fname:
            self._project_drop([fname])

    def _project_action(self, action, cid):
        p = self.project
        clip = p.clip(cid) if cid else None
        if action == 'split':
            self.project_split(cid)
        elif action == 'delete':
            self.project_delete(cid)
        elif action == 'copy':
            self.project_copy(cid)
        elif action == 'paste':
            self.project_paste()
        elif action.startswith('trim:') and clip is not None:
            self.project_timeline.selected = clip.id
            self.project_trim_to_playhead(action.split(':', 1)[1])
        elif action == 'mute' and clip is not None:
            self._project_snapshot()
            clip.muted = not clip.muted
            self._project_changed()
        elif action == 'volume' and clip is not None:
            val, ok = _api.QInputDialog.getInt(
                self, "Громкость клипа", "Громкость, % (100 — как в исходнике):",
                int(round(clip.volume * 100)), 0, 400, 5)
            if ok:
                self._project_snapshot()
                clip.volume = val / 100.0
                self._project_changed()
        elif action == 'detach_audio' and clip is not None:
            self.project_detach_audio(clip.id)
        elif action.startswith('speed:') and clip is not None:
            value = action.split(':', 1)[1]
            if value == 'custom':
                val, ok = _api.QInputDialog.getInt(
                    self, "Скорость клипа", "Скорость, % (100 — как в исходнике):",
                    int(round(clip.speed * 100)),
                    int(round(_mp.MIN_SPEED * 100)),
                    int(round(_mp.MAX_SPEED * 100)), 5)
                if not ok:
                    return
                speed = val / 100.0
            else:
                try:
                    speed = float(value)
                except ValueError:
                    return
            self.project_set_speed(clip.id, speed)
        elif action.startswith('track:') and clip is not None:
            try:
                ti = int(action.split(':', 1)[1])
            except ValueError:
                return
            self._project_snapshot()
            if not p.move(cid, ti, self.project_timeline.playhead
                          if ti != p.main_track else clip.start):
                self._proj_undo.pop()
                return
            self._project_changed()
        elif action.startswith('add_track:'):
            self._project_snapshot()
            p.add_track(action.split(':', 1)[1])
            self._project_changed()

    # ── Кадры и волна на клипах ──────────────────────────────────────────────
    def _project_thumb(self, clip, t, height):
        """Кадр для полосы превью клипа (ProjectTimeline.thumb_provider).
        Готов — сразу; нет — заказ фоном, а пока — ближайший готовый кадр того
        же файла в пределах клипа: полоса не пустеет при прокрутке и смене
        масштаба, кадры лишь уточняются."""
        tl = getattr(self, "project_timeline", None)
        dpr = tl.devicePixelRatioF() if tl is not None else 1.0
        hp = max(8, int(round(height * dpr)))
        src = self._proj_norm(clip.src)
        t = 0.0 if clip.is_image else round(float(t), 3)
        key = f"{src}|{t:.3f}|{hp}"
        cache = self._proj_thumbs
        if key in cache:
            pm = cache[key]
            if pm:
                cache.move_to_end(key)
                return pm
        else:
            cache[key] = None                  # заказан
            worker = self._proj_thumb_worker
            if worker is None:
                # Дисковый кэш кадров — рядом с файлом проекта.
                cache_dir = _api.os.path.join(
                    _api.os.path.dirname(_api.MONTAGE_PROJECT_PATH), "montage_thumbs")
                worker = _api.ProjectThumbWorker(cache_dir)
                worker.ready.connect(self._project_thumb_ready)
                worker.start()
                self._proj_thumb_worker = worker
            worker.request(key, clip.src, t, hp)
        return self._project_thumb_near(src, t, clip)

    def _project_thumb_near(self, src, t, clip):
        """Ближайший по времени готовый кадр файла внутри клипа (или None)."""
        index = self._proj_thumb_index.get(src)
        if not index:
            return None
        i = bisect.bisect_left(index, (t, ""))
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(index):
                tt, key = index[j]
                pm = self._proj_thumbs.get(key)
                if (pm and (clip.is_image or clip.in_s - 0.5 <= tt <= clip.out_s + 0.5)
                        and (best is None or abs(tt - t) < best[0])):
                    best = (abs(tt - t), pm)
        return best[1] if best else None

    def _project_thumb_ready(self, key, img):
        cache = self._proj_thumbs
        if img is None:
            cache[key] = False                 # не вышел — больше не заказываем
            return
        try:
            cache[key] = _api.QPixmap.fromImage(img)
        except Exception:
            return
        src, t, _h = key.rsplit("|", 2)
        bisect.insort(self._proj_thumb_index.setdefault(src, []), (float(t), key))
        while len(cache) > _THUMB_CACHE_MAX:
            old, pm = cache.popitem(last=False)
            if pm:
                o_src, o_t, _oh = old.rsplit("|", 2)
                index = self._proj_thumb_index.get(o_src)
                if index is not None:
                    try:
                        index.remove((float(o_t), old))
                    except ValueError:
                        pass
        # Кадры приходят пачкой — таймлайн перерисовываем раз на пачку.
        timer = self._proj_thumb_timer
        if timer is None:
            timer = _api.QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(60)
            timer.timeout.connect(self._project_thumbs_arrived)
            self._proj_thumb_timer = timer
        if not timer.isActive():
            timer.start()

    def _project_thumbs_arrived(self):
        tl = getattr(self, "project_timeline", None)
        if tl is not None:
            tl.invalidate()

    @staticmethod
    def _proj_norm(path):
        return _api.os.path.normcase(_api.os.path.abspath(str(path)))

    def _project_store_wave(self, samples, duration):
        """Волна открытого файла построена — запоминаем её для клипов этого
        файла (on_waveform_ready). Держим несколько последних файлов."""
        src = self.actual_source_file
        if not src or not samples or duration <= 0:
            return
        waves = self._proj_waves
        key = self._proj_norm(src)
        waves.pop(key, None)
        waves[key] = (samples, float(duration))
        while len(waves) > 12:
            waves.pop(next(iter(waves)))
        tl = getattr(self, "project_timeline", None)
        if tl is not None:
            tl.invalidate()

    def _project_wave(self, clip):
        """(сэмплы, длительность файла) для волны на клипе или None."""
        if not clip.audio_path:
            return None
        return self._proj_waves.get(self._proj_norm(clip.src))

    def _project_shutdown(self):
        self._pmix_stop()
        self._snd_shutdown()
        worker = getattr(self, "_proj_thumb_worker", None)
        if worker is not None:
            try:
                worker.stop()
                worker.wait(1500)
            except Exception:
                pass
            self._proj_thumb_worker = None

    # ── Плеер на проекте ─────────────────────────────────────────────────────
    def _proj_is_loaded(self, src):
        cur = self.actual_source_file
        if not cur or not src:
            return False
        return self._proj_norm(cur) == self._proj_norm(src)

    def _proj_ready_for(self, src):
        """Источник src открыт и готов: у картинки — сразу, у видео — когда
        плеер его принял."""
        if not self._proj_is_loaded(src):
            return False
        return bool(getattr(self, "is_still_image", False)) or self._proj_player_ready()

    def _proj_player_ready(self):
        """Плеер принял источник: до LoadedMedia setPosition он пропускает."""
        S = _api.QMediaPlayer.MediaStatus
        try:
            return self.player.mediaStatus() in (S.LoadedMedia, S.BufferedMedia,
                                                 S.BufferingMedia, S.EndOfMedia)
        except Exception:
            return False

    def _project_plan(self):
        """Цепочка для просмотра: куски подряд, соседние куски одного файла,
        идущие в нём встык (например, после разрезания), склеены в один —
        их плеер играет без перемотки.

        Проект без видео — одна «пустота» на всю длину: все звуковые клипы
        играют голоса (project_audio) по стене, основной плеер не грузит файлы
        на каждой смене клипа и звук не рвётся."""
        if not self.project.has_video():
            dur = self.project.duration()
            return [{'t0': 0.0, 't1': dur, 'clip': None}] if dur > 0 else []
        plan = []
        for t0, t1, c in self.project.preview_segments():
            if c is None:
                plan.append({'t0': t0, 't1': t1, 'clip': None})
                continue
            s0, s1 = c.source_time(t0), c.source_time(t1)
            last = plan[-1] if plan else None
            if (last is not None and last['clip'] is not None
                    and last['clip'].src == c.src
                    and abs(last['clip'].speed - c.speed) < 1e-6
                    and abs(last['t1'] - t0) < 1e-6
                    and abs(last['s1'] - s0) < 0.002):
                last['t1'], last['s1'] = t1, s1
                continue
            plan.append({'t0': t0, 't1': t1, 'clip': c, 's0': s0, 's1': s1})
        dur = self.project.duration()
        if plan and dur > plan[-1]['t1'] + 1e-6:
            # Звук длиннее картинки: в файле хвост — чёрный кадр со звуком.
            plan.append({'t0': plan[-1]['t1'], 't1': dur, 'clip': None})
        return plan

    def _project_seek(self, t):
        """Клик или протяжка по таймлайну (и любой переход по проекту): плеер
        показывает кадр проекта в точке t."""
        t = max(0.0, float(t))
        self._proj_active = not self.project.is_empty()
        tl = self.project_timeline
        tl.set_playhead(t, follow=False)
        self._paint_project_time(t)
        plan = self._project_plan()
        idx = next((i for i, s in enumerate(plan) if s['t0'] <= t < s['t1']), None)
        if self._proj_play is not None:
            if idx is None:
                self.project_stop()
            else:
                self._proj_play = plan
                if self._snd_active:
                    # Звук — с нового места; картинка встанет и подождёт его
                    # (иначе после прыжка она убегала бы вперёд звука).
                    self._snd_jump(t)
                    self._proj_hold_player()
                self._proj_play_segment(idx, t - plan[idx]['t0'])
            return
        if idx is None or plan[idx]['clip'] is None:
            return                      # пустота: показывать нечего, стоит плейхед
        seg = plan[idx]
        speed = max(_mp.MIN_SPEED, seg['clip'].speed) if seg['clip'] is not None else 1.0
        src_t = self._proj_clamp_src(seg, seg['s0'] + (t - seg['t0']) * speed)
        clip = self._proj_clip_at_source(seg, src_t)
        self._proj_cur_id = clip.id
        if not self._proj_ready_for(clip.src):
            self._proj_pending = ('show', clip.src, src_t)
            if not self._proj_is_loaded(clip.src):
                self._proj_load(clip.src)
            return
        if not clip.is_image:
            self.seek_to(src_t)

    def _proj_clamp_src(self, seg, src_t):
        """Время файла внутри куска плана — не дальше середины его последнего
        кадра: кадр, начинающийся ровно на s1, вырезан, а index_at (допуск
        1.5 мс) у самой границы отдавал именно его."""
        clip = seg.get('clip')
        fps = clip.fps if clip is not None and clip.fps and not clip.is_image else 0.0
        src_t = max(seg['s0'], src_t)
        if fps > 0 and 's1' in seg:
            _first, last = self._proj_seg_frames(seg, fps)
            src_t = min(src_t, (last + 0.5) / fps)
        return src_t

    def _proj_clip_at_source(self, seg, src_t):
        """Склеенный кусок плана может состоять из нескольких клипов (разрезали
        и не трогали) — какой из них на src_t."""
        c = seg['clip']
        for o in self.project.clips_on(c.track):
            if (o.src == c.src and seg['t0'] - 1e-6 <= o.start < seg['t1']
                    and o.in_s - 1e-6 <= src_t < o.out_s):
                return o
        return c

    def _paint_project_time(self, t):
        lbl = getattr(self, "lbl_current_time", None)
        if lbl is not None:
            lbl.setText(_api.s_to_time(t))
        self._fs_sync_position()

    def _proj_follow_source(self, src_s):
        """Плеер показал кадр src_s файла (_paint_playhead) — плейхед проекта
        и время под видео за ним. True — время проекта показано."""
        if getattr(self, "project_timeline", None) is None or self.project.is_empty():
            return False
        tl = self.project_timeline
        if self._proj_play is not None:
            self._proj_tick(src_s)
            self._paint_project_time(tl.playhead)
            return True
        c = self.project.clip(self._proj_cur_id)
        # Первый кадр клипа, разрезанного не по сетке кадров, начинается чуть
        # раньше его in — допуск в полкадра, иначе плейхед на нём не двигался.
        lead = (0.5 / c.fps) if c is not None and c.fps else 1e-4
        if (c is None or not self._proj_is_loaded(c.src)
                or not (c.in_s - lead <= src_s <= c.out_s + 1e-4)):
            c = self._proj_clip_for_source(src_s)
            if c is None:
                return False
            self._proj_cur_id = c.id
        t = c.start + (min(max(src_s, c.in_s), c.out_s) - c.in_s) / max(
            _mp.MIN_SPEED, c.speed)
        tl.set_playhead(t)
        self._paint_project_time(t)
        return True

    def _proj_clip_for_source(self, src_s):
        """Клип открытого файла, в котором лежит время файла src_s (ближайший
        к плейхеду, если файл в проекте несколько раз)."""
        t = self.project_timeline.playhead
        best, dist = None, None
        for c in self.project.clips:
            lead = (0.5 / c.fps) if c.fps else 1e-4
            if not self._proj_is_loaded(c.src) or not (c.in_s - lead <= src_s < c.out_s):
                continue
            d = abs(c.start + (src_s - c.in_s) / max(_mp.MIN_SPEED, c.speed) - t)
            if best is None or d < dist:
                best, dist = c, d
        return best

    def _proj_time_of_source(self, src_s):
        """Время проекта для кадра src_s открытого файла в текущем клипе или
        None (кадр не из него)."""
        c = self.project.clip(getattr(self, "_proj_cur_id", ""))
        if c is None or c.is_image or not self._proj_is_loaded(c.src):
            return None
        lead = (0.5 / c.fps) if c.fps else 1e-4
        if not (c.in_s - lead <= src_s < c.out_s):
            return None
        return c.start + (max(src_s, c.in_s) - c.in_s) / max(_mp.MIN_SPEED, c.speed)

    def _proj_audio_at(self, t):
        """Звук, который слышно в точке t проекта: (клип, время его звука) или
        None — там тишина (дорожка выключена, клип заглушён, звук убран или
        отделён в выключенную дорожку, пустота). Звучат несколько — свой звук
        показанного клипа, иначе верхняя звуковая дорожка: шагу кадра нужен
        один источник."""
        parts = [c for c in self.project.audio_parts() if c.start - 1e-6 <= t < c.end]
        if not parts:
            return None
        cur = getattr(self, "_proj_cur_id", "")
        c = next((p for p in parts if p.id == cur), None) or min(parts, key=lambda p: p.track)
        return c, c.source_time(t)

    def _proj_step(self, step):
        """Шаг кадра по проекту. True — шаг сделан здесь (через стык клипов
        или с плейхеда в пустоте); False — обычный шаг по файлу: плейхед
        проекта приедет за плеером сам."""
        if getattr(self, "project_timeline", None) is None or self.project.is_empty():
            return False
        c = self.project.clip(self._proj_cur_id)
        if c is not None and abs(c.speed - 1.0) > 1e-6:
            # Ускоренный клип: шаг кадра проекта — это speed кадров файла,
            # обычный шаг плеера дал бы speed-ю долю кадра.
            fps = c.fps or self.fps or 30.0
            t = self.project_timeline.playhead + int(step) / fps
            t = max(0.0, min(t, self.project.duration() - 1.0 / fps))
            self._project_seek(t)
            return True
        done = self._proj_step_frames(int(step))
        if done is not None:
            return done
        tl = self.project_timeline
        c = self.project.clip(self._proj_cur_id)
        fps = (c.fps if c is not None and c.fps else 0.0) or self.fps or 30.0
        t = tl.playhead
        nt = t + step / fps
        if (c is not None and not c.is_image and self._proj_ready_for(c.src)
                and c.start - 1e-6 <= t < c.end and c.start - 1e-6 <= nt < c.end - 1e-6):
            return False
        nt = max(0.0, min(nt, self.project.duration() - 0.5 / fps))
        self._project_seek(nt)
        return True

    @staticmethod
    def _proj_seg_frames(seg, fps):
        """Кадры файла (первый, последний), которые кусок плана показывает:
        [s0, s1) — от кадра, на котором стоит s0, до кадра перед s1 (кадр,
        начинающийся ровно на s1, уже вырезан). Так же режет и сборка."""
        first = int(_api.math.floor(seg['s0'] * fps + 1e-3))
        last = int(_api.math.ceil(seg['s1'] * fps - 1e-3)) - 1
        return first, max(first, last)

    def _proj_step_frames(self, step):
        """Шаг кадра у плейхеда, стоящего на видео открытого файла, — в НОМЕРАХ
        кадров. False — шаг внутри куска (обычный шаг по файлу), True — шаг
        через стык сделан, None — не этот случай (пустота, картинка, другой
        файл, нет сетки кадров).

        Прежде шаг через стык считался во времени проекта (плейхед ± 1/fps), и
        у стыка всё решали доли миллисекунды: шаг вправо с последнего кадра
        куска вставал на кадр, который начинается ровно на конце куска, —
        вырезанный, а следующий шаг перепрыгивал первый кадр нового куска."""
        grid = self._grid
        c = self.project.clip(self._proj_cur_id)
        if (c is None or c.is_image or not grid.valid or self._frame_idx is None
                or not self._proj_ready_for(c.src)):
            return None
        fps = grid.fps
        cur = self._current_frame_index()
        t = c.start + (grid.center_of(cur) - c.in_s) / max(_mp.MIN_SPEED, c.speed)
        plan = self._project_plan()
        i = next((k for k, s in enumerate(plan) if s['t0'] <= t < s['t1']), None)
        if i is None or plan[i]['clip'] is None or not self._proj_is_loaded(plan[i]['clip'].src):
            return None
        first, last = self._proj_seg_frames(plan[i], fps)
        if not first <= cur <= last:
            return None
        if first <= cur + step <= last:
            return False
        j = i + (1 if step > 0 else -1)
        if not 0 <= j < len(plan):
            return True                         # край проекта — стоим на месте
        seg = plan[j]
        clip = seg['clip']
        if clip is not None and not clip.is_image and self._proj_is_loaded(clip.src):
            f2, l2 = self._proj_seg_frames(seg, fps)
            idx = f2 if step > 0 else l2
            t2 = seg['t0'] + (grid.center_of(idx) - seg['s0']) / max(
                _mp.MIN_SPEED, clip.speed)
        else:
            # Другой файл, картинка или пустота: их край во времени проекта
            # (середина крайнего кадра — так плейхед не попадёт на стык).
            half = 0.5 / (clip.fps if clip is not None and clip.fps else fps)
            t2 = seg['t0'] + half if step > 0 else seg['t1'] - half
        self._project_seek(min(max(t2, seg['t0']), seg['t1'] - 1e-6))
        return True

    def jump_to_end(self):
        """«В конец»: последний кадр проекта (без проекта — OUT файла)."""
        if self.project.is_empty():
            self.seek_to(self.current_out)
            return
        if self._proj_play is not None:
            self.project_stop()
        self._project_seek(self._proj_last_frame_t())

    def _proj_last_frame_t(self):
        """Время последнего кадра проекта. Конец таймлайна для плейхеда —
        здесь, а не на самой длине проекта: там он стоит ЗА последним кадром,
        и шаг влево оттуда не возвращался шагом вправо (шаг не пускает дальше
        последнего кадра)."""
        end = self.project.duration()
        last = max(self.project.clips, key=lambda c: c.end, default=None)
        fps = (last.fps if last is not None else 0.0) or self.fps or 30.0
        return max(0.0, end - 1.0 / fps)

    def _project_leave(self):
        """Просмотр проекта прерван (открывают другой файл и т. п.)."""
        if self._proj_play is not None:
            self.project_stop()
        self._proj_set_rate(1.0)
        self._proj_active = not self.project.is_empty()
        self._proj_pending = None

    def _project_on_user_load(self, path):
        """Файл открывает пользователь (кнопка, бросок, лента, итог обрезки),
        а не сам проект. Пусто или один кусок — новый проект из этого файла;
        проект из нескольких кусков — спросить: добавить в конец или начать
        заново. False — передумали, файл не открываем."""
        kind = 'fresh'
        if len(self.project.clips) > 1:
            box = _api.QMessageBox(self)
            box.setWindowTitle("Монтаж")
            box.setText(f"В проекте {len(self.project.clips)} клипов. Что сделать с файлом?\n"
                        f"{_api.os.path.basename(str(path))}")
            b_add = box.addButton("Добавить в конец", _api.QMessageBox.ButtonRole.AcceptRole)
            b_new = box.addButton("Новый проект", _api.QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("Отмена", _api.QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_add)
            box.exec()
            if box.clickedButton() is b_add:
                self._project_drop([path])
                return False
            if box.clickedButton() is not b_new:
                return False
        self._project_leave()
        self._proj_drop_queue = []
        self._proj_pending = (kind, str(path))
        return True

    def _proj_resume_pending(self):
        """Файл догрузился — делаем то, ради чего его открывали."""
        pend = self._proj_pending
        if pend is None or not (getattr(self, "is_still_image", False)
                                or self._proj_player_ready()):
            return
        self._proj_pending = None
        kind = pend[0]
        if kind == 'play' and self._proj_play is not None:
            self._proj_play_segment(pend[1], pend[2], cont=pend[3])
        elif kind == 'show' and self._proj_is_loaded(pend[1]):
            if not getattr(self, "is_still_image", False):
                self.seek_to(pend[2])
        elif kind == 'fresh' and self._proj_is_loaded(pend[1]):
            # Открыли файл — он целиком и есть проект (отмена вернёт прежний).
            if not self.project.is_empty():
                self._project_snapshot()
                self.project = _mp.Project()
                self.project_timeline.set_project(self.project)
            self.project_timeline.set_playhead(0.0, follow=False)
            if self._project_add_whole(snapshot=False) is None:
                self._project_changed()
        elif kind == 'add' and self._proj_is_loaded(pend[1]):
            self._project_add_whole()
            self._project_drop_next()

    def _proj_load(self, src):
        """Открывает файл куска — это делает сам проект, а не пользователь
        (load_file не трогает проект)."""
        self._proj_internal_load = True
        try:
            self.load_file(src)
        finally:
            self._proj_internal_load = False

    def _project_drop(self, paths):
        """Файлы, брошенные на таймлайн (или «＋»), — в конец проекта целиком,
        по очереди."""
        self._proj_drop_queue = list(paths)
        self._project_drop_next()

    def _project_drop_next(self):
        queue = getattr(self, "_proj_drop_queue", None) or []
        while queue:
            path = queue.pop(0)
            self._project_leave()
            if self._proj_ready_for(path):
                self._project_add_whole()
                continue
            self._proj_pending = ('add', path)
            self._proj_load(path)
            return

    def _project_add_whole(self, snapshot=True):
        """Весь открытый файл — в конец проекта."""
        if not getattr(self, "is_still_image", False) and self.duration > 0:
            self.set_in_out(0.0, self.duration, skip_undo=True)
        return self.project_add_selection('main', snapshot=snapshot)

    def _project_export_route(self):
        """«Экспорт» / Ctrl+S. True — проект собран здесь; False — режет
        прежняя «Обрезка» (проект из одного куска открытого файла)."""
        if self.project.is_empty():
            return False
        c = self._proj_single_clip()
        if c is not None and self._proj_is_loaded(c.src):
            if not c.is_image:
                self._project_sync_source()
                return False
            if getattr(self, "_pixelize_active", False):
                return False            # картинка с проявлением — свой экспорт
        self.project_export()
        return True

    def project_toggle_play(self):
        if self._proj_play is not None:
            self.project_stop()
        else:
            self.project_play()

    def project_play(self):
        """Просмотр проекта с плейхеда проекта (с начала, если он в конце)."""
        plan = self._project_plan()
        if not plan or (not any(s['clip'] is not None for s in plan)
                        and not self.project.audio_parts()):
            return
        missing = sorted({s['clip'].src for s in plan
                          if s['clip'] is not None and not _api.os.path.exists(s['clip'].src)}
                         | {c.audio_path for c in self.project.audio_parts()
                            if not _api.os.path.exists(c.audio_path)})
        if missing:
            _api.msgbox_warning(self, "Проект", "Не найдены файлы:\n" + "\n".join(missing))
            return
        t = self.project_timeline.playhead
        if t >= min(plan[-1]['t1'] - 0.05, self._proj_last_frame_t() - 1e-3):
            t = 0.0                     # с последнего кадра — заново с начала
        idx = next((i for i, s in enumerate(plan) if s['t0'] <= t < s['t1']), 0)
        self._proj_active = True
        self._proj_play = plan
        self._snd_begin(t)
        self._pmix_start()
        self._project_update_ui()
        self._proj_play_segment(idx, max(0.0, t - plan[idx]['t0']))

    def project_stop(self):
        if self._proj_play is not None:
            # До _pmix_stop: тот возвращает громкость ползунка, и хвост очереди
            # устройства заглушённого клипа зазвучал бы в полную силу.
            self._mute_pause_tail()
        self._proj_play = None
        self._proj_limit_s = None
        self._proj_seam = None
        self._bridge_stop()
        self._proj_transition = False
        self._proj_pending = None
        self._pmix_stop()
        self._snd_stop()
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
        except Exception:
            pass
        self._proj_set_rate(1.0)
        self._set_play_bound(False)
        self._project_update_ui()

    def _proj_set_rate(self, speed):
        """Скорость основного плеера под клип проекта (1 — обычная)."""
        try:
            rate = max(0.1, min(8.0, float(speed)))
            if abs(self.player.playbackRate() - rate) > 1e-3:
                self.player.setPlaybackRate(rate)
        except Exception:
            pass

    def _proj_play_segment(self, idx, offset, cont=False):
        """Играет кусок idx плана с offset секунд от его начала. cont — это
        продолжение просмотра со стыка, а не прыжок (клик, старт, загрузка)."""
        plan = self._proj_play
        if plan is None:
            return
        self._pmix_hold = None
        while (idx < len(plan) and plan[idx]['clip'] is None
               and not self._pmix_covers(plan[idx]['t0'] + offset, plan[idx]['t1'])):
            idx += 1            # пустоту без звука пропускаем (в файле — чёрный кадр)
            offset = 0.0
        if idx >= len(plan):
            self.project_stop()
            # Конец просмотра — на последнем кадре, как «В конец». На самой
            # длине проекта плейхед стоял за последним кадром, а на экране был
            # кадр, начинающийся ровно на out клипа, то есть уже вырезанный.
            self._project_seek(self._proj_last_frame_t())
            return
        seg = plan[idx]
        clip = seg['clip']
        self._proj_set_rate(1.0 if clip is None or clip.is_image else clip.speed)
        self._proj_idx = idx
        self._proj_limit_s = seg.get('s1')
        if clip is not None and not self._proj_ready_for(clip.src):
            self._proj_transition = True
            # Пока грузится другой видеофайл, часы проекта стоят — и голоса
            # тоже, там, где их застал стык; картинка потом начнёт с того же
            # места. Картинку плеер не играет — её загрузка часов не держит:
            # голоса идут дальше, кадр просто стоит на долю секунды меньше.
            if cont and not clip.is_image:
                offset = self._pmix_catch_up(seg, offset, lag=0.0)
            self._proj_pending = ('play', idx, offset, cont)
            if not (clip.is_image and cont):
                self._pmix_anchor(seg['t0'] + offset, running=False)
            if not self._proj_is_loaded(clip.src):
                # Другой файл грузим при громкости по ползунку, а не заглушённым
                # клипом: громкость 0 на смене источника порой оставляла немым
                # весь следующий кусок. Громкость клипа встанет перед play().
                self._pmix_set_main_gain(None)
                self._proj_load(clip.src)
            return
        if clip is None or clip.is_image:
            # Картинку плеер не играет, пустота под звуком — тоже без плеера:
            # держим время куска, плейхед и голоса идут по стене.
            self._proj_transition = True
            if clip is None:
                try:
                    if (self.player.playbackState()
                            == _api.QMediaPlayer.PlaybackState.PlayingState):
                        self.player.pause()
                except Exception:
                    pass
            start_t = seg['t0'] + max(0.0, offset)
            if cont and self._pmix_running():
                start_t = min(max(start_t, self._pmix_now()), seg['t1'])
            else:
                # После загрузки картинки (cont) голоса продолжают с места
                # паузы, после клика по таймлайну — перематываются.
                self._pmix_anchor(start_t, jump=not cont)
            self._pmix_hold = (seg['t0'], seg['t1'])
            self._snd_ensure_playing()
            self.project_timeline.set_playhead(start_t)
            left = max(0.05, seg['t1'] - start_t)
            gen = getattr(self, "_proj_image_gen", 0) + 1
            self._proj_image_gen = gen
            _api.QTimer.singleShot(int(left * 1000), lambda g=gen, i=idx: (
                self._proj_play is not None and getattr(self, "_proj_image_gen", 0) == g
                and self._proj_play_segment(i + 1, 0.0, cont=True)))
            return
        if cont:
            offset = self._pmix_catch_up(seg, offset)
        src_t = self._proj_clamp_src(seg, seg['s0'] + max(0.0, offset) * max(
            _mp.MIN_SPEED, clip.speed))
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState
                       and not getattr(self, "_prerolling", False))
        except Exception:
            playing = False
        self._proj_cur_id = self._proj_clip_at_source(seg, src_t).id
        t = seg['t0'] + max(0.0, offset)
        self.project_timeline.set_playhead(t)
        # Громкость клипа — до старта: первый звук куска уже нужной громкости.
        self._pmix_main_gain_at(t)
        self._pmix_anchor(t, main=True, jump=not cont, src_ms=int(src_t * 1000))
        if playing:
            self.seek_to(src_t)
            self._set_play_bound(True)
            return
        self._proj_transition = True
        # Плеер уже стоит на этом кадре (обычный «Пробел» с места) — не
        # перематываем: перемотка остужает звук, и старт был бы немым ~0.35 с.
        half = (0.5 / clip.fps) if clip.fps else 0.02
        if abs(self._ui_time_s() - src_t) > half:
            self.seek_to(src_t)
        self._proj_start_player()

    def _proj_start_player(self):
        """«Воспроизвести» с текущего кадра — тем же путём, что кнопка
        (подхват прогретого звука), но без прыжка на IN: у проекта свои
        границы. Звук своим трактом — картинка стартует вместе с ним."""
        self._snd_start_with(self._play_from_here)

    def _proj_hold_player(self):
        """Остановить картинку на время перехода (не конец просмотра)."""
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                self._proj_transition = True
                self.player.pause()
        except Exception:
            pass

    def _proj_boundary_begin(self):
        """Плеер упёрся в конец куска — пауза будет переходом, а не остановкой."""
        if self._proj_play is None:
            return False
        self._proj_transition = True
        return True

    def _proj_boundary_end(self):
        nxt = self._proj_idx + 1
        _api.QTimer.singleShot(0, lambda: self._proj_play_segment(nxt, 0.0, cont=True))

    def _proj_play_span(self):
        """Текущий кусок просмотра во времени источника (s0, s1) или None."""
        plan = self._proj_play
        if plan is None or not 0 <= self._proj_idx < len(plan):
            return None
        seg = plan[self._proj_idx]
        if seg['clip'] is None or 's0' not in seg:
            return None
        return seg['s0'], seg['s1']

    def _proj_on_state(self, playing):
        """Смена состояния плеера (on_playback_changed)."""
        if playing:
            self._proj_transition = False
        elif (self._proj_play is not None and not self._proj_transition
                and self.player.playbackState() == _api.QMediaPlayer.PlaybackState.StoppedState
                and self.player.position() / 1000.0 >= self.duration - 0.1):
            # Плеер доиграл файл до конца (кусок до конца файла, граница не
            # успела; Qt перед остановкой ставит позицию на длину файла): это
            # конец куска, а не пауза пользователем — дальше следующий кусок
            # или конец просмотра на последнем кадре.
            self._proj_transition = True
            self._proj_boundary_end()
        elif self._proj_play is not None and not self._proj_transition:
            # Пауза пользователем (Пробел, СТОП) — просмотр проекта окончен;
            # плеер остаётся на проекте, Пробел продолжит с плейхеда проекта.
            self._proj_play = None
            self._proj_limit_s = None
            self._proj_set_rate(1.0)
            self._pmix_stop()
            self._snd_stop()
            self._project_update_ui()

    def _proj_tick(self, src_s):
        """Плейхед проекта едет за плеером (sync_ui)."""
        plan = self._proj_play
        if plan is None or self._proj_transition or not (0 <= self._proj_idx < len(plan)):
            return
        seg = plan[self._proj_idx]
        if seg['clip'] is None:
            return
        t = seg['t0'] + (src_s - seg['s0']) / max(_mp.MIN_SPEED, seg['clip'].speed)
        self.project_timeline.set_playhead(min(seg['t1'], max(seg['t0'], t)))
        self._bridge_prefetch(src_s)

    def _proj_play_limit(self):
        """Конец текущего куска во времени источника, пока идёт просмотр."""
        if self._proj_play is None or self._proj_limit_s is None:
            return None
        return self._proj_limit_s

    # ── Сборка ───────────────────────────────────────────────────────────────
    def project_export(self):
        p = self.project
        if p.is_empty():
            return
        th = getattr(self, "ffmpeg_thread", None)
        if th is not None and th.isRunning():
            _api.msgbox_information(self, "Проект", "Дождитесь окончания текущей обрезки.")
            return
        srcs = {c.src for c in p.clips} | {c.audio_path for c in p.clips if c.audio_path}
        missing = sorted(s for s in srcs if not _api.os.path.exists(s))
        if missing:
            _api.msgbox_warning(self, "Проект", "Не найдены файлы:\n" + "\n".join(missing))
            return
        first = next((c for c in p.clips_on(p.main_track)), None) or p.clips[0]
        stem = _api.Path(first.src).stem
        # «Перекодировать настройками «Обработки»» (4) и его аудио-вариант (5):
        # проект кодирует «Обработка» своими настройками, склейка и кодирование
        # — одним проходом ffmpeg (ProcessProjectMixin). Иначе проект молча
        # уходил в H.264 Монтажа.
        mode = self.cmb_mode.currentIndex()
        if mode in (4, 5):
            if mode == 5 and not p.audio_parts():
                _api.msgbox_warning(self, "Проект", "В проекте нет звука — обрабатывать нечего.")
                return
            self.project_stop()
            self._execute_cut_and_process(
                0.0, p.duration(), src=first.src, audio_only=(mode == 5),
                burn_subs=(mode == 4), project=p.to_dict(), name_stem=f"{stem}_проект")
            return
        video = p.has_video()
        ext = ".mp4" if video else ".m4a"
        folder = (self.export_dir if self.export_dir and _api.os.path.isdir(self.export_dir)
                  else _api.os.path.dirname(first.src))
        default = _api._unique_output(_api.os.path.join(folder, f"{stem}_проект{ext}"))
        flt = "Видео MP4 (*.mp4)" if video else "Звук M4A (*.m4a)"
        path, _f = _api.QFileDialog.getSaveFileName(self, "Сохранить видео проекта", default, flt)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        temp_out = self._make_temp_out(path)
        # HDR10-куски сводятся в SDR так, как их видно в просмотре.
        tonemap = hdr_tonemap.tonemap_filters(
            (c.src for c in p.clips if c.has_video and not c.is_image), self._escape_filter_path)
        built = _mp.build_export(p, temp_out, _api.FFMPEG, self._video_encoder_args(),
                                 subs=self._project_burn_subs(), tonemap=tonemap)
        if built is None:
            try:
                _api.os.remove(temp_out)
            except OSError:
                pass
            return
        cmd, graph, dur = built
        graph_file = None
        if len(" ".join(cmd)) > _INLINE_GRAPH_MAX:
            try:
                tf = _api.tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False,
                                                      suffix=".txt", prefix="sihyx_graph_")
                tf.write(graph)
                tf.close()
                graph_file = tf.name
                i = cmd.index("-filter_complex")
                cmd[i:i + 2] = ["-/filter_complex", graph_file]
            except Exception:
                graph_file = None
        self.project_stop()
        self._report_progress(0, "Сборка проекта…")
        self._set_cut_btn_cancel(True)
        self._start_cut_phase("Сборка проекта…")
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = _api.QTimer(self)
            self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()
        self.ffmpeg_thread = _api.FfmpegWorker(cmd, duration=dur)
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)

        def _done(success, message, _temp=temp_out, _final=path, _graph=graph_file):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self._set_cut_btn_cancel(False)
            self._project_update_ui()
            if _graph:
                try:
                    _api.os.remove(_graph)
                except OSError:
                    pass
            if not success:
                try:
                    if _api.os.path.exists(_temp):
                        _api.os.remove(_temp)
                except OSError:
                    pass
                self.on_ffmpeg_finished(False, message)
                return
            try:
                saved = self._replace_tolerant(_temp, _final)
            except Exception as e:
                self.on_ffmpeg_finished(False, f"Ошибка при сохранении: {e}")
                return
            self._progress_result_path = saved
            self._proj_status(f"видео проекта сохранено: {saved}")
            self.on_ffmpeg_finished(True, message)

        self.ffmpeg_thread.finished.connect(_done)
        self.ffmpeg_thread.start()
