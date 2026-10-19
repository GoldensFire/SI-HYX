# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: проект из кусков, как в Filmora.

Вкладка как была — «источник»: открываешь файл, ставишь IN/OUT. Кнопка
«＋ В проект» (Insert) кладёт выделенный кусок в проект — по умолчанию в конец
основной дорожки. Так из ОДНОГО файла набирается сколько угодно кусков (и из
разных файлов тоже). Панель «Проект» внизу — таймлайн с дорожками: куски
режутся (Ctrl+B), двигаются, подрезаются за край, удаляются (на основной
дорожке дыра закрывается сама), уходят на верхнюю видеодорожку (перекрывают
кадр) или на звуковые. «▶» показывает проект в плеере цепочкой кусков, а
звуковые дорожки, звук под наложением и громкость клипов слышны через
«голоса» (project_audio). «Сохранить видео» собирает итог одной командой
ffmpeg (montage_project).

Модель — montage_project.Project; виджет — edit_tab_widgets.ProjectTimeline.
Проект сохраняется сам (MONTAGE_PROJECT_PATH) и переживает перезапуск."""
import montage_project as _mp

import edit_tab as _api

# Длинная команда ffmpeg: граф фильтров уходит в файл (-/filter_complex) —
# у Windows предел командной строки 32767 символов, а на каждый кусок
# приходится путь к файлу и строка фильтров.
_INLINE_GRAPH_MAX = 6000
_THUMB_H = 40


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
        self._proj_active = False      # монитор показывает проект, а не источник
        self._proj_play = None         # план просмотра (список кусков) или None
        self._proj_idx = 0
        self._proj_limit_s = None      # конец текущего куска во времени источника
        self._proj_transition = False  # пауза между кусками — не остановка просмотра
        self._proj_pending = None      # что сделать, когда догрузится другой файл
        self._proj_edit_id = ""        # клип, открытый в источнике для правки
        self._proj_collapsed = False
        self._proj_thumbs = {}
        self._proj_thumb_worker = None
        self._pmix_init()              # звук дорожек в просмотре (project_audio)

    # ── Панель ───────────────────────────────────────────────────────────────
    def _proj_button(self, text="", icon=None, tip="", accent=False):
        b = _api.QPushButton(text)
        if icon:
            b.setIcon(_api.get_icon(icon, color='#11111b' if accent else _api.C['text']))
            b.setIconSize(_api.QSize(14, 14))
        b.setToolTip(tip)
        b.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        bg = _api.C['accent'] if accent else _api.C['surface3']
        hover = _api.C['accent2'] if accent else _api.C['border2']
        fg = '#11111b' if accent else _api.C['text']
        pad = "4px 10px" if text else "4px 6px"
        b.setStyleSheet(f"""
            QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {_api.C['border2'] if not accent else 'transparent'};
                           border-radius: 5px; padding: {pad}; font-size: 12px; font-weight: 600; }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:disabled {{ background: {_api.C['surface2']}; color: {_api.C['text3']}; }}
            QPushButton::menu-indicator {{ width: 0; }}
        """)
        return b

    def _build_project_panel(self):
        """Панель «Проект» во всю ширину вкладки под шкалой источника."""
        panel = _api.QFrame()
        panel.setObjectName("ProjectPanel")
        panel.setStyleSheet(f"#ProjectPanel {{ background: {_api.C['surface']}; "
                            f"border-top: 1px solid {_api.C['border']}; }}")
        lay = _api.QVBoxLayout(panel)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(4)
        hdr = _api.QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(6)

        self.btn_proj_toggle = self._proj_button("Проект", 'fa5s.chevron-down',
                                                 "Свернуть/развернуть таймлайн проекта")
        self.btn_proj_toggle.clicked.connect(self._project_toggle_collapsed)
        hdr.addWidget(self.btn_proj_toggle)

        self.btn_proj_add = self._proj_button(
            "＋ В проект", None,
            "Добавить выделенный кусок источника (IN–OUT) в конец основной дорожки (Insert).\n"
            "Стрелка справа — поверх кадра на «Видео 2» или только звук на «Аудио 1».",
            accent=True)
        self.btn_proj_add.clicked.connect(lambda: self.project_add_selection('main'))
        hdr.addWidget(self.btn_proj_add)
        self.btn_proj_add_more = self._proj_button("", 'fa5s.caret-down',
                                                   "Куда добавить кусок")
        menu = _api.QMenu(self.btn_proj_add_more)
        menu.addAction("В конец основной дорожки («Видео 1»)\tInsert",
                       lambda: self.project_add_selection('main'))
        menu.addAction("Поверх кадра — на «Видео 2» у плейхеда проекта",
                       lambda: self.project_add_selection('overlay'))
        menu.addAction("Только звук — на «Аудио 1» у плейхеда проекта",
                       lambda: self.project_add_selection('audio'))
        self.btn_proj_add_more.setMenu(menu)
        hdr.addWidget(self.btn_proj_add_more)

        self.btn_proj_update = self._proj_button(
            "Обновить клип", 'fa5s.sync-alt',
            "Записать текущие IN–OUT источника в клип, открытый двойным кликом")
        self.btn_proj_update.clicked.connect(self.project_update_clip)
        self.btn_proj_update.setVisible(False)
        hdr.addWidget(self.btn_proj_update)

        hdr.addSpacing(6)
        self.btn_proj_split = self._proj_button("", 'fa5s.cut', "Разрезать клип у плейхеда (Ctrl+B)")
        self.btn_proj_split.clicked.connect(lambda: self.project_split())
        hdr.addWidget(self.btn_proj_split)
        self.btn_proj_delete = self._proj_button("", 'fa5s.trash-alt', "Удалить выбранный клип (Delete)")
        self.btn_proj_delete.clicked.connect(lambda: self.project_delete())
        hdr.addWidget(self.btn_proj_delete)
        self.btn_proj_undo = self._proj_button("", 'fa5s.undo', "Отменить правку проекта (Ctrl+Z на таймлайне)")
        self.btn_proj_undo.clicked.connect(self.project_undo)
        hdr.addWidget(self.btn_proj_undo)
        self.btn_proj_redo = self._proj_button("", 'fa5s.redo', "Повторить правку проекта (Ctrl+Y на таймлайне)")
        self.btn_proj_redo.clicked.connect(self.project_redo)
        hdr.addWidget(self.btn_proj_redo)

        hdr.addStretch(1)
        self.lbl_proj_info = _api.QLabel("")
        self.lbl_proj_info.setStyleSheet(f"color: {_api.C['text2']}; font-size: 12px;")
        hdr.addWidget(self.lbl_proj_info)
        hdr.addSpacing(6)
        self.btn_proj_play = self._proj_button("", 'fa5s.play',
                                               "Смотреть проект в плеере (Пробел, когда плеер на проекте)")
        self.btn_proj_play.clicked.connect(self.project_toggle_play)
        hdr.addWidget(self.btn_proj_play)
        self.btn_proj_fit = self._proj_button("", 'fa5s.expand-arrows-alt', "Весь проект в окне")
        self.btn_proj_fit.clicked.connect(lambda: self.project_timeline.zoom_to_fit())
        hdr.addWidget(self.btn_proj_fit)
        self.btn_proj_more = self._proj_button("", 'fa5s.ellipsis-h', "Ещё")
        more = _api.QMenu(self.btn_proj_more)
        more.addAction("Добавить видеодорожку", lambda: self._project_action('add_track:video', ''))
        more.addAction("Добавить аудиодорожку", lambda: self._project_action('add_track:audio', ''))
        more.addSeparator()
        more.addAction("Очистить проект…", self.project_clear)
        self.btn_proj_more.setMenu(more)
        hdr.addWidget(self.btn_proj_more)
        self.btn_proj_export = self._proj_button("Сохранить видео", 'fa5s.file-export',
                                                 "Собрать проект в один файл", accent=True)
        self.btn_proj_export.clicked.connect(self.project_export)
        hdr.addWidget(self.btn_proj_export)
        lay.addLayout(hdr)

        tl = _api.ProjectTimeline(self.project)
        tl.thumb_provider = self._project_thumb
        tl.seekRequested.connect(self._project_seek)
        tl.clipActivated.connect(self._project_open_clip)
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
        self._project_apply_collapsed()
        self._project_update_ui()
        return panel

    def _project_toggle_collapsed(self):
        self._proj_collapsed = not self._proj_collapsed
        self._project_apply_collapsed()
        self.save_settings()

    def _project_apply_collapsed(self):
        tl = getattr(self, "project_timeline", None)
        if tl is None:
            return
        tl.setVisible(not self._proj_collapsed)
        self.btn_proj_toggle.setIcon(_api.get_icon(
            'fa5s.chevron-right' if self._proj_collapsed else 'fa5s.chevron-down',
            color=_api.C['text']))
        self._project_sync_scroll()
        _api.QTimer.singleShot(0, self._adjust_video_height)

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
        sb.setVisible(total > span * 0.05 and not self._proj_collapsed)

    def _project_on_scroll(self, value):
        self.project_timeline.set_offset(value / 100.0)

    def _project_update_ui(self):
        """Подписи и доступность кнопок панели."""
        if getattr(self, "lbl_proj_info", None) is None:
            return
        n = len(self.project.clips)
        if n:
            word = "клип" if n % 10 == 1 and n % 100 != 11 else (
                "клипа" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "клипов")
            self.lbl_proj_info.setText(f"{n} {word}  ·  {_api.s_to_time(self.project.duration())}")
        else:
            self.lbl_proj_info.setText("пусто")
        sel = self.project.clip(self.project_timeline.selected)
        self.btn_proj_delete.setEnabled(sel is not None)
        self.btn_proj_split.setEnabled(n > 0)
        self.btn_proj_undo.setEnabled(bool(self._proj_undo))
        self.btn_proj_redo.setEnabled(bool(self._proj_redo))
        self.btn_proj_export.setEnabled(n > 0)
        self.btn_proj_play.setEnabled(n > 0)
        self.btn_proj_play.setIcon(_api.get_icon(
            'fa5s.pause' if self._proj_play is not None else 'fa5s.play', color=_api.C['text']))
        editing = self.project.clip(self._proj_edit_id)
        self.btn_proj_update.setVisible(editing is not None
                                        and self._proj_is_loaded(editing.src))

    def _proj_status(self, text):
        try:
            self.log_label.setText(text)
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"Монтаж, проект: {text}")
        except Exception:
            pass

    # ── Правка ───────────────────────────────────────────────────────────────
    def _project_snapshot(self):
        """Снимок ДО правки — для отмены (Ctrl+Z на таймлайне)."""
        self._proj_undo.append(self.project.to_dict())
        self._proj_redo.clear()

    def _project_changed(self):
        """Правка закончена: сохранить, перерисовать, остановить просмотр."""
        if self._proj_play is not None:
            self.project_stop()
        try:
            _api.os.makedirs(_api.os.path.dirname(_api.MONTAGE_PROJECT_PATH), exist_ok=True)
            _mp.save_project(self.project, _api.MONTAGE_PROJECT_PATH)
        except Exception:
            pass
        self.project_timeline.refresh()
        self._project_update_ui()

    def _project_replace(self, project):
        self.project = project
        self.project_timeline.set_project(project)
        self._project_changed()

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

    def project_add_selection(self, where='main'):
        """Кладёт выделенный кусок источника (IN–OUT) в проект."""
        src = self.actual_source_file
        if not src or not _api.os.path.exists(str(src)) or self.duration <= 0:
            _api.msgbox_information(self, "Проект", "Сначала откройте файл и выделите кусок.")
            return
        still = bool(getattr(self, "is_still_image", False))
        has_video = still or self.video_stream_index is not None
        audio_path, audio_stream = ("", -1) if still else self._source_audio()
        if where == 'audio' or not has_video:
            if not audio_path:
                _api.msgbox_information(self, "Проект", "У этого куска нет звука.")
                return
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
            _api.msgbox_information(self, "Проект", "Кусок слишком короткий: передвиньте IN/OUT.")
            return
        if still:
            width, height = int(getattr(self, "_still_w", 0)), int(getattr(self, "_still_h", 0))
        else:
            width = int(getattr(self, "_src_video_w", 0) or 0)
            height = int(getattr(self, "_src_video_h", 0) or 0)
        p = self.project
        playhead = self.project_timeline.playhead
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
        self._project_snapshot()
        p.append(clip)
        self.project_timeline.selected = clip.id
        self._project_changed()
        if where == 'main':
            # Как в Filmora: плейхед проекта встаёт за добавленным куском, и
            # следующий кусок видно сразу на своём месте.
            self.project_timeline.set_playhead(clip.end)
        if self._proj_collapsed:
            self._proj_collapsed = False
            self._project_apply_collapsed()
        if was_empty:
            _api.QTimer.singleShot(0, self.project_timeline.zoom_to_fit)
        lost = [n for n, on in (("кадрирование", self._video_crop_filter() is not None),
                                ("пикселизация", getattr(self, "_pixelize_active", False)),
                                ("наложенные картинки", self.has_image_overlays()))
                if on]
        note = f" (в проект не переносятся: {', '.join(lost)})" if lost else ""
        self._proj_status(f"добавлен кусок {clip.name} "
                          f"{_api.s_to_time(clip.in_s)}–{_api.s_to_time(clip.out_s)}{note}")

    def project_update_clip(self):
        """Клип, открытый в источнике, получает текущие IN–OUT."""
        clip = self.project.clip(self._proj_edit_id)
        if clip is None or not self._proj_is_loaded(clip.src):
            return
        in_s, out_s = float(self.current_in), float(self.current_out)
        if clip.fps and not clip.is_image:
            in_s = _mp.snap_to_frame(in_s, clip.fps)
            out_s = min(self.duration, round(out_s * clip.fps) / clip.fps)
        if out_s - in_s < _mp.MIN_CLIP_S:
            return
        self._project_snapshot()
        clip.in_s, clip.out_s = in_s, out_s
        if clip.track != self.project.main_track:
            self.project._free_spot(clip)
        self.project.pack()
        self._project_changed()
        self._proj_status(f"клип обновлён: {_api.s_to_time(in_s)}–{_api.s_to_time(out_s)}")

    def _project_target(self, cid=None):
        """Клип для разрезания: явный; иначе выбранный, если плейхед на нём;
        иначе клип под плейхедом — сперва на основной дорожке, потом сверху
        вниз."""
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
            self._proj_status("плейхед проекта не стоит на клипе — резать нечего")
            return
        self._project_snapshot()
        parts = self.project.split(clip.id, t)
        if parts is None:
            self._proj_undo.pop()
            self._proj_status("слишком близко к краю клипа")
            return
        self.project_timeline.selected = parts[1].id
        self._project_changed()

    def project_delete(self, cid=None):
        cid = cid or self.project_timeline.selected
        if not cid or self.project.clip(cid) is None:
            return
        self._project_snapshot()
        self.project.remove(cid)
        self.project_timeline.selected = ""
        self._project_changed()

    def project_clear(self):
        if self.project.is_empty():
            return
        ans = _api.msgbox_question(self, "Проект", "Очистить проект — убрать все клипы?\n"
                                   "Отменить можно кнопкой «Отменить» на панели проекта.")
        if ans != _api.QMessageBox.StandardButton.Yes:
            return
        self._project_snapshot()
        fresh = _mp.Project()
        self._project_replace(fresh)
        self.project_timeline.set_playhead(0.0)

    def _project_action(self, action, cid):
        p = self.project
        clip = p.clip(cid) if cid else None
        if action == 'open' and clip is not None:
            self._project_open_clip(cid)
        elif action == 'split':
            self.project_split(cid)
        elif action == 'delete':
            self.project_delete(cid)
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

    # ── Миниатюры ────────────────────────────────────────────────────────────
    def _project_thumb(self, clip):
        key = f"{clip.src}|{clip.in_s:.2f}"
        pm = self._proj_thumbs.get(key)
        if pm is not None:
            return pm
        if key in self._proj_thumbs:
            return None
        self._proj_thumbs[key] = None          # заказан
        worker = self._proj_thumb_worker
        if worker is None:
            worker = _api.ProjectThumbWorker()
            worker.ready.connect(self._project_thumb_ready)
            worker.start()
            self._proj_thumb_worker = worker
        sec = clip.in_s + (0.0 if clip.is_image else min(0.05, clip.length / 2))
        worker.request(key, clip.src, 0.0 if clip.is_image else sec, _THUMB_H)
        return None

    def _project_thumb_ready(self, key, img):
        try:
            self._proj_thumbs[key] = _api.QPixmap.fromImage(img)
        except Exception:
            return
        tl = getattr(self, "project_timeline", None)
        if tl is not None:
            tl.update()

    def _project_shutdown(self):
        self._pmix_stop()
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
        norm = _api.os.path.normcase
        return norm(_api.os.path.abspath(str(cur))) == norm(_api.os.path.abspath(str(src)))

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
                    and last['clip'].src == c.src and abs(last['t1'] - t0) < 1e-6
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
        """Клик или протяжка по таймлайну проекта: плеер показывает проект."""
        t = max(0.0, float(t))
        self._proj_active = True
        tl = self.project_timeline
        tl.set_playhead(t, follow=False)
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
        clip = seg['clip']
        if not self._proj_ready_for(clip.src):
            self._proj_pending = ('show', clip.src, src_t)
            if not self._proj_is_loaded(clip.src):
                self._proj_load(clip.src)
            return
        if not clip.is_image:
            self.seek_to(src_t)

    def _project_open_clip(self, cid):
        """Двойной клик по клипу: кусок открывается в источнике с IN–OUT по
        клипу, «Обновить клип» записывает правку обратно."""
        clip = self.project.clip(cid)
        if clip is None:
            return
        if not _api.os.path.exists(clip.src):
            _api.msgbox_warning(self, "Проект", f"Файл не найден:\n{clip.src}")
            return
        self._project_leave()
        self._proj_edit_id = cid
        if self._proj_ready_for(clip.src):
            self._proj_open_now(clip)
        else:
            self._proj_pending = ('open', cid)
            if not self._proj_is_loaded(clip.src):
                self._proj_load(clip.src)
        self._project_update_ui()

    def _proj_open_now(self, clip):
        if clip.is_image:
            return
        self.set_in_out(clip.in_s, min(clip.out_s, self.duration), keep_view=False)
        try:
            self.waveform.ensure_view_contains(clip.in_s, clip.out_s)
        except Exception:
            pass
        self.seek_to(clip.in_s)
        self._project_update_ui()

    def _project_leave(self):
        """Пользователь вернулся к источнику (клик по его шкале, открыл файл)."""
        if self._proj_play is not None:
            self.project_stop()
        self._proj_active = False
        self._proj_pending = None

    def _proj_resume_pending(self):
        """Другой файл догрузился — делаем то, ради чего его открывали."""
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
        elif kind == 'open':
            clip = self.project.clip(pend[1])
            if clip is not None and self._proj_is_loaded(clip.src):
                self._proj_open_now(clip)
        elif kind == 'add' and self._proj_is_loaded(pend[1]):
            self._project_add_whole()
            self._project_drop_next()

    def _proj_load(self, src):
        """Открывает файл куска. Картинка грузится сразу и без плеера —
        продолжаем тут же (LoadedMedia от плеера у неё не будет)."""
        self.load_file(src)
        if getattr(self, "is_still_image", False) and self._proj_pending is not None:
            _api.QTimer.singleShot(0, self._proj_resume_pending)

    def _project_drop(self, paths):
        """Файлы, брошенные на таймлайн проекта, — в конец проекта целиком,
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

    def _project_add_whole(self):
        """Весь открытый файл — в проект."""
        if not getattr(self, "is_still_image", False) and self.duration > 0:
            self.set_in_out(0.0, self.duration, skip_undo=True)
        self.project_add_selection('main')

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
        if t >= plan[-1]['t1'] - 0.05:
            t = 0.0
        idx = next((i for i, s in enumerate(plan) if s['t0'] <= t < s['t1']), 0)
        self._proj_active = True
        self._proj_play = plan
        self._pmix_start()
        self._project_update_ui()
        self._proj_play_segment(idx, max(0.0, t - plan[idx]['t0']))

    def project_stop(self):
        self._proj_play = None
        self._proj_limit_s = None
        self._proj_transition = False
        self._proj_pending = None
        self._pmix_stop()
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
        except Exception:
            pass
        self._set_play_bound(False)
        self._project_update_ui()

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
            end = plan[-1]['t1'] if plan else 0.0
            self.project_stop()
            self.project_timeline.set_playhead(end)
            return
        seg = plan[idx]
        clip = seg['clip']
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
        src_t = seg['s0'] + max(0.0, offset)
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState
                       and not getattr(self, "_prerolling", False))
        except Exception:
            playing = False
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
        self.seek_to(src_t)
        self._proj_start_player()

    def _proj_start_player(self):
        """«Воспроизвести» без логики кнопки: та начинает с IN, если плейхед
        стоит на OUT, — а у проекта свои границы."""
        self._scrubbing = False
        self._flush_preroll_mute()
        self._flush_frame_seek()
        if getattr(self, "_prerolling", False):
            self._preroll_cancel()
        hold_ms = self._play_start_hold_ms()
        self._release_frame_lock()
        self.player.play()
        self._hold_play_start(hold_ms)

    def _proj_boundary_begin(self):
        """Плеер упёрся в конец куска — пауза будет переходом, а не остановкой."""
        if self._proj_play is None:
            return False
        self._proj_transition = True
        return True

    def _proj_boundary_end(self):
        nxt = self._proj_idx + 1
        _api.QTimer.singleShot(0, lambda: self._proj_play_segment(nxt, 0.0, cont=True))

    def _proj_on_state(self, playing):
        """Смена состояния плеера (on_playback_changed)."""
        if playing:
            self._proj_transition = False
        elif self._proj_play is not None and not self._proj_transition:
            # Пауза пользователем (Пробел, СТОП) — просмотр проекта окончен;
            # плеер остаётся на проекте, Пробел продолжит с плейхеда проекта.
            self._proj_play = None
            self._proj_limit_s = None
            self._pmix_stop()
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
        self.btn_proj_export.setEnabled(False)
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
            self.btn_proj_export.setEnabled(True)
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
