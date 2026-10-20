# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: проект из кусков, как в Filmora. Шкала у вкладки одна — таймлайн
проекта.

Открытый файл сразу целиком ложится на основную дорожку «Видео 1». Дальше всё
на таймлайне: Ctrl+B режет клип у плейхеда, Shift+C / Shift+V обрезают начало
и конец клипа до плейхеда, края клипов тянутся мышью, Delete удаляет (на
основной дорожке дыра закрывается сама). Ещё файлы — «＋» или бросок на
таймлайн: встают в конец. Клипы уходят на верхнюю видеодорожку (перекрывают
кадр) или на звуковые через меню.

Плеер всегда показывает проект: плейхед таймлайна и плеер связаны в обе
стороны (клик по шкале — плеер на клипе; шаг кадра, игра — плейхед за ним).
Сохранение одной кнопкой: проект из одного куска одного файла уходит прежней
«Обрезкой» (Smart Cut, кадрирование, субтитры — IN/OUT источника держатся по
клипу), иначе проект собирается одной командой ffmpeg (montage_project).

Модель — montage_project.Project; виджет — edit_tab_widgets.ProjectTimeline.
Проект сохраняется сам (MONTAGE_PROJECT_PATH) и переживает перезапуск."""
import bisect
from collections import OrderedDict

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
        self.project = _mp.Project()
        try:
            if _api.os.path.exists(_api.MONTAGE_PROJECT_PATH):
                self.project = _mp.load_project(_api.MONTAGE_PROJECT_PATH)
        except Exception:
            self.project = _mp.Project()
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

        tl = _api.ProjectTimeline(self.project)
        tl.thumb_provider = self._project_thumb
        tl.wave_provider = self._project_wave
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
        """Подписи и доступность кнопок правки, общее время, «Итог» и текст
        кнопки сохранения."""
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
        if n > 0:
            # Плеер на проекте: играть есть что, даже если на экране картинка.
            self.btn_play.setEnabled(True)
        b = getattr(self, "btn_cut", None)
        single = n == 0 or self._proj_single_clip() is not None
        still = getattr(self, "is_still_image", False)
        if b is not None and b.text() != "Отмена" and not (still and single):
            b.setText("Обрезать" if single else "Собрать видео")
            b.setIcon(_api.get_icon('fa5s.cut' if single else 'fa5s.film', color='#1e1e2e'))
            b.setToolTip("" if single else "Склеить клипы проекта в один файл (Ctrl+S)")
            if n > 0:
                b.setEnabled(True)

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
        try:
            _api.os.makedirs(_api.os.path.dirname(_api.MONTAGE_PROJECT_PATH), exist_ok=True)
            _mp.save_project(self.project, _api.MONTAGE_PROJECT_PATH)
        except Exception:
            pass
        self.project_timeline.refresh()
        self._project_sync_source()
        self._project_update_ui()

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
        run = p.clips_on(first.track)
        for a, b in zip(run, run[1:]):
            if (b.src != a.src or b.audio_path != a.audio_path
                    or abs(b.in_s - a.out_s) > 1e-3 or abs(b.start - a.end) > 1e-3):
                return None
        if any(c.muted or abs(c.volume - 1.0) > 1e-6 for c in run):
            return None
        if len(run) == 1:
            return run[0]
        return _mp.Clip(**{**{f: getattr(run[0], f) for f in run[0].__dataclass_fields__},
                           'out_s': run[-1].out_s})

    def _project_sync_source(self):
        """IN/OUT источника — по клипу одиночного проекта (по ним режет
        «Обрезать» и встаёт воспроизведение); у проекта из нескольких кусков
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
            # Как у «Обрезать»: кадр, который показан на IN, и кадр, на котором
            # стоит OUT, — границы куска ложатся на сетку кадров.
            in_s = _mp.snap_to_frame(in_s, fps)
            out_s = min(self.duration, round(out_s * fps) / fps)
        if out_s - in_s < _mp.MIN_CLIP_S:
            return None
        if still:
            width, height = int(getattr(self, "_still_w", 0)), int(getattr(self, "_still_h", 0))
        else:
            width = int(getattr(self, "_src_video_w", 0) or 0)
            height = int(getattr(self, "_src_video_h", 0) or 0)
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
        cid = cid or self.project_timeline.selected
        if not cid or self.project.clip(cid) is None:
            return
        self._project_snapshot()
        self.project.remove(cid)
        self.project_timeline.selected = ""
        self._project_changed()
        if not self.project.is_empty():
            t = min(self.project_timeline.playhead,
                    max(0.0, self.project.duration() - 0.04))
            self._project_seek(t)

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
        их плеер играет без перемотки."""
        plan = []
        for t0, t1, c in self.project.preview_segments():
            if c is None:
                plan.append({'t0': t0, 't1': t1, 'clip': None})
                continue
            s0, s1 = c.source_time(t0), c.source_time(t1)
            last = plan[-1] if plan else None
            if (last is not None and last['clip'] is not None
                    and last['clip'].src == c.src and abs(last['t1'] - t0) < 1e-6
                    and abs(last['s1'] - s0) < 0.002):
                last['t1'], last['s1'] = t1, s1
                continue
            plan.append({'t0': t0, 't1': t1, 'clip': c, 's0': s0, 's1': s1})
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
                self._proj_play_segment(idx, t - plan[idx]['t0'])
            return
        if idx is None or plan[idx]['clip'] is None:
            return                      # пустота: показывать нечего, стоит плейхед
        seg = plan[idx]
        src_t = seg['s0'] + (t - seg['t0'])
        clip = self._proj_clip_at_source(seg, src_t)
        self._proj_cur_id = clip.id
        if not self._proj_ready_for(clip.src):
            self._proj_pending = ('show', clip.src, src_t)
            if not self._proj_is_loaded(clip.src):
                self._proj_load(clip.src)
            return
        if not clip.is_image:
            self.seek_to(src_t)

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
        eps = 1e-4
        if (c is None or not self._proj_is_loaded(c.src)
                or not (c.in_s - eps <= src_s <= c.out_s + eps)):
            c = self._proj_clip_for_source(src_s)
            if c is None:
                return False
            self._proj_cur_id = c.id
        t = c.start + (min(max(src_s, c.in_s), c.out_s) - c.in_s)
        tl.set_playhead(t)
        self._paint_project_time(t)
        return True

    def _proj_clip_for_source(self, src_s):
        """Клип открытого файла, в котором лежит время файла src_s (ближайший
        к плейхеду, если файл в проекте несколько раз)."""
        t = self.project_timeline.playhead
        best, dist = None, None
        for c in self.project.clips:
            if not self._proj_is_loaded(c.src) or not (c.in_s - 1e-4 <= src_s < c.out_s):
                continue
            d = abs(c.start + (src_s - c.in_s) - t)
            if best is None or d < dist:
                best, dist = c, d
        return best

    def _proj_step(self, step):
        """Шаг кадра по проекту. True — шаг сделан здесь (через стык клипов
        или с плейхеда в пустоте); False — обычный шаг по файлу: плейхед
        проекта приедет за плеером сам."""
        if getattr(self, "project_timeline", None) is None or self.project.is_empty():
            return False
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

    def jump_to_end(self):
        """«В конец»: последний кадр проекта (без проекта — OUT файла)."""
        if self.project.is_empty():
            self.seek_to(self.current_out)
            return
        if self._proj_play is not None:
            self.project_stop()
        end = self.project.duration()
        last = max(self.project.clips, key=lambda c: c.end)
        fps = last.fps or self.fps or 30.0
        self._project_seek(max(0.0, end - 1.0 / fps))

    def _project_leave(self):
        """Просмотр проекта прерван (открывают другой файл и т. п.)."""
        if self._proj_play is not None:
            self.project_stop()
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
            self._proj_play_segment(pend[1], pend[2])
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
        """«Обрезать» / Ctrl+S. True — проект собран здесь; False — режет
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
        if not any(s['clip'] is not None for s in plan):
            return
        missing = sorted({s['clip'].src for s in plan
                          if s['clip'] is not None and not _api.os.path.exists(s['clip'].src)})
        if missing:
            _api.msgbox_warning(self, "Проект", "Не найдены файлы:\n" + "\n".join(missing))
            return
        t = self.project_timeline.playhead
        if t >= plan[-1]['t1'] - 0.05:
            t = 0.0
        idx = next((i for i, s in enumerate(plan) if s['t0'] <= t < s['t1']), 0)
        self._proj_active = True
        self._proj_play = plan
        self._project_update_ui()
        self._proj_play_segment(idx, max(0.0, t - plan[idx]['t0']))

    def project_stop(self):
        self._proj_play = None
        self._proj_limit_s = None
        self._proj_transition = False
        self._proj_pending = None
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
        except Exception:
            pass
        self._set_play_bound(False)
        self._project_update_ui()

    def _proj_play_segment(self, idx, offset):
        """Играет кусок idx плана с offset секунд от его начала."""
        plan = self._proj_play
        if plan is None:
            return
        while idx < len(plan) and plan[idx]['clip'] is None:
            idx += 1            # пустоту в просмотре пропускаем (в файле — чёрный кадр)
            offset = 0.0
        if idx >= len(plan):
            end = plan[-1]['t1'] if plan else 0.0
            self.project_stop()
            self.project_timeline.set_playhead(end)
            return
        seg = plan[idx]
        clip = seg['clip']
        self._proj_idx = idx
        self._proj_limit_s = seg['s1']
        src_t = seg['s0'] + max(0.0, offset)
        if not self._proj_ready_for(clip.src):
            self._proj_transition = True
            self._proj_pending = ('play', idx, offset)
            if not self._proj_is_loaded(clip.src):
                self._proj_load(clip.src)
            return
        if clip.is_image:
            # Картинку плеер не играет: держим её на экране время куска.
            self._proj_transition = True
            self.project_timeline.set_playhead(seg['t0'] + max(0.0, offset))
            left = max(0.05, (seg['t1'] - seg['t0']) - max(0.0, offset))
            gen = getattr(self, "_proj_image_gen", 0) + 1
            self._proj_image_gen = gen
            _api.QTimer.singleShot(int(left * 1000), lambda g=gen, i=idx: (
                self._proj_play is not None and getattr(self, "_proj_image_gen", 0) == g
                and self._proj_play_segment(i + 1, 0.0)))
            return
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState
                       and not getattr(self, "_prerolling", False))
        except Exception:
            playing = False
        self._proj_cur_id = self._proj_clip_at_source(seg, src_t).id
        self.project_timeline.set_playhead(seg['t0'] + max(0.0, offset))
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
        границы."""
        self._play_from_here()

    def _proj_boundary_begin(self):
        """Плеер упёрся в конец куска — пауза будет переходом, а не остановкой."""
        if self._proj_play is None:
            return False
        self._proj_transition = True
        return True

    def _proj_boundary_end(self):
        nxt = self._proj_idx + 1
        _api.QTimer.singleShot(0, lambda: self._proj_play_segment(nxt, 0.0))

    def _proj_on_state(self, playing):
        """Смена состояния плеера (on_playback_changed)."""
        if playing:
            self._proj_transition = False
        elif self._proj_play is not None and not self._proj_transition:
            # Пауза пользователем (Пробел, СТОП) — просмотр проекта окончен;
            # плеер остаётся на проекте, Пробел продолжит с плейхеда проекта.
            self._proj_play = None
            self._proj_limit_s = None
            self._project_update_ui()

    def _proj_tick(self, src_s):
        """Плейхед проекта едет за плеером (sync_ui)."""
        plan = self._proj_play
        if plan is None or self._proj_transition or not (0 <= self._proj_idx < len(plan)):
            return
        seg = plan[self._proj_idx]
        if seg['clip'] is None:
            return
        t = seg['t0'] + (src_s - seg['s0'])
        self.project_timeline.set_playhead(min(seg['t1'], max(seg['t0'], t)))

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
        video = p.has_video()
        ext = ".mp4" if video else ".m4a"
        folder = (self.export_dir if self.export_dir and _api.os.path.isdir(self.export_dir)
                  else _api.os.path.dirname(first.src))
        stem = _api.Path(first.src).stem
        default = _api._unique_output(_api.os.path.join(folder, f"{stem}_проект{ext}"))
        flt = "Видео MP4 (*.mp4)" if video else "Звук M4A (*.m4a)"
        path, _f = _api.QFileDialog.getSaveFileName(self, "Сохранить видео проекта", default, flt)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        temp_out = self._make_temp_out(path)
        built = _mp.build_export(p, temp_out, _api.FFMPEG, self._video_encoder_args())
        if built is None:
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
        self._set_cut_status("Сборка проекта… подготовка", icon='fa5s.hourglass-half')
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
