# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: состояние вкладки между запусками.

Клипы проекта сохраняются сами (MONTAGE_PROJECT_PATH), а то, на чём
остановились, лежит в настройках Монтажа (EDITOR_SETTINGS_PATH, ключ
'session'):

* плейхед проекта и вид таймлайна (масштаб, прокрутка). При первом показе
  вкладки файл под плейхедом открывается сам — на экране тот же кадр, а не
  пустой плеер до первого клика по шкале;
* для каждого файла — выбранная аудиодорожка (встроенная, внешняя озвучка или
  «Нет») и субтитры (встроенная дорожка или внешний файл). Звук кусков проекта
  по-прежнему задаёт сам проект (_project_restore_audio); запись файла выбирает
  звук, когда кусков этого файла в проекте нет (файл открывают заново).

«Только звук» и громкость до выключения динамиком сохраняет save_settings.
Эффекты источника (кадрирование, пикселизация, накладки) сюда не входят: их
load_file сбрасывает на каждом открытии файла намеренно."""
import edit_tab as _api

_FILES_MAX = 200        # столько файлов помним; давние вытесняются
_RESTORE_DELAY_MS = 200  # первый показ: сперва окно дорисуется, потом файл


class EditTabSessionMixin:
    """Монтаж: запоминание и восстановление состояния вкладки."""

    def _session_init(self):
        """Вызывается из __init__ до load_settings."""
        self._session_files = {}         # ключ файла → {'audio': …, 'subs': …}
        self._session_playhead = None    # плейхед проекта из прошлого запуска
        self._session_view = None        # (пикселей на секунду, сдвиг) таймлайна
        self._session_restored = False   # первый показ вкладки уже был

    # ── Настройки ────────────────────────────────────────────────────────────
    def _session_settings(self):
        """Состояние для save_settings."""
        tl = getattr(self, "project_timeline", None)
        if tl is not None and self._session_restored:
            playhead, view = float(tl.playhead), [float(tl.pps), float(tl.offset)]
        else:
            # Вкладку в этот запуск не открывали — плейхед и вид прошлого
            # запуска не затираем нулями.
            playhead = self._session_playhead
            view = list(self._session_view) if self._session_view else None
        return {'playhead': playhead, 'view': view, 'files': self._session_files}

    def _session_load(self, state):
        """Состояние из load_settings."""
        if not isinstance(state, dict):
            return
        files = state.get('files')
        if isinstance(files, dict):
            self._session_files = {str(k): v for k, v in files.items() if isinstance(v, dict)}
        try:
            ph = state.get('playhead')
            self._session_playhead = max(0.0, float(ph)) if ph is not None else None
        except (TypeError, ValueError):
            self._session_playhead = None
        view = state.get('view')
        try:
            if isinstance(view, (list, tuple)) and len(view) == 2:
                self._session_view = (float(view[0]), max(0.0, float(view[1])))
        except (TypeError, ValueError):
            self._session_view = None

    # ── Дорожки файла ────────────────────────────────────────────────────────
    def _session_file_key(self):
        src = getattr(self, "actual_source_file", None)
        if not src or getattr(self, "is_still_image", False):
            return None
        return _api.os.path.normcase(_api.os.path.abspath(str(src)))

    def _session_audio_spec(self):
        """Выбранный звук открытого файла: ['emb', индекс потока],
        ['ext', путь], ['none'] или None."""
        sel = getattr(self, "_audio_sel_entry", None)
        if sel is None:
            return None
        kind, ref = sel
        if kind == 'emb':
            try:
                return ['emb', int(self._audio_streams[ref].get('index'))]
            except (IndexError, TypeError, ValueError):
                return None
        if kind == 'ext':
            return ['ext', str(ref)]
        if kind == 'none':
            return ['none']
        return None

    def _session_subs_spec(self):
        """Выбранные субтитры: ['emb', индекс потока], ['ext', путь] или None
        («Выкл»)."""
        sel = getattr(self, "_sub_sel_entry", None)
        if sel is None:
            return None
        kind, ref = sel
        if kind == 'emb':
            try:
                return ['emb', int(self._sub_streams[ref].get('index'))]
            except (IndexError, TypeError, ValueError):
                return None
        if kind == 'ext':
            return ['ext', str(ref)]
        return None

    def _session_remember_tracks(self):
        """Выбрали дорожку (звук, субтитры) — запоминаем её для этого файла.
        Сброс списков при открытии файла (_loading_tracks) выбором не считается."""
        key = self._session_file_key()
        if key is None or getattr(self, "_loading_tracks", False):
            return
        files = self._session_files
        files.pop(key, None)
        files[key] = {'audio': self._session_audio_spec(), 'subs': self._session_subs_spec()}
        while len(files) > _FILES_MAX:
            files.pop(next(iter(files)))
        self.save_settings()

    @staticmethod
    def _session_same_path(a, b):
        return (_api.os.path.normcase(_api.os.path.abspath(str(a)))
                == _api.os.path.normcase(_api.os.path.abspath(str(b))))

    def _session_restore_tracks(self, audio=True):
        """Файл открыт (finish_loading_file): дорожки — как в прошлый раз.
        audio=False — звук уже выбрал проект по своим кускам."""
        key = self._session_file_key()
        rec = self._session_files.get(key) if key else None
        if not rec:
            return
        if audio:
            self._session_pick_audio(rec.get('audio'))
        self._session_pick_subs(rec.get('subs'))

    def _session_pick_audio(self, spec):
        if not isinstance(spec, list) or not spec:
            return
        target = None
        if spec[0] == 'emb' and len(spec) > 1:
            target = next((('emb', i) for i, s in enumerate(self._audio_streams)
                           if s.get('index') == spec[1]), None)
        elif spec[0] == 'none':
            target = ('none', None)
        elif spec[0] == 'ext' and len(spec) > 1:
            target = next((e for e in self._audio_entries
                           if e[0] == 'ext' and self._session_same_path(e[1], spec[1])), None)
            if target is None:
                if _api.os.path.exists(spec[1]):
                    self._add_external_audio(spec[1])
                return
        if target is None or target not in self._audio_entries:
            return
        idx = self._audio_entries.index(target)
        if idx != self.cmb_audio.currentIndex():
            self.cmb_audio.setCurrentIndex(idx)

    def _session_pick_subs(self, spec):
        if not isinstance(spec, list) or len(spec) < 2:
            return
        target = None
        if spec[0] == 'emb':
            target = next((('emb', i) for i, s in enumerate(self._sub_streams)
                           if s.get('index') == spec[1]), None)
        elif spec[0] == 'ext':
            target = next((e for e in self._sub_entries
                           if e[0] == 'ext' and self._session_same_path(e[1], spec[1])), None)
            if target is None:
                if _api.os.path.exists(spec[1]):
                    self._add_external_sub(spec[1])
                return
        if target is None or target not in self._sub_entries:
            return
        idx = self._sub_entries.index(target) + 1      # пункт 0 — «Выкл»
        if idx != self.cmb_subs.currentIndex():
            self.cmb_subs.setCurrentIndex(idx)

    # ── Первый показ вкладки ─────────────────────────────────────────────────
    def _session_schedule_restore(self):
        """Из showEvent: таймлайн и плеер — туда, где остановились (один раз)."""
        if self._session_restored:
            return
        self._session_restored = True
        _api.QTimer.singleShot(_RESTORE_DELAY_MS, self._session_restore_view)

    def _session_restore_view(self):
        tl = getattr(self, "project_timeline", None)
        if tl is None or self.project.is_empty():
            return
        view = self._session_view
        if view is not None:
            tl.pps = max(0.5, min(400.0, view[0]))
            tl.set_offset(view[1])
        if self.actual_source_file is not None:
            return      # файл уже открыли (бросок, лента) — плеер занят им
        t = self._session_playhead if self._session_playhead is not None else 0.0
        self._project_seek(min(t, self._proj_last_frame_t()))
