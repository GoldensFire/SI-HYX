# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: файл проекта и проекты, собранные нейросетью.

Проект вкладки по-прежнему сам пишется в MONTAGE_PROJECT_PATH. Сверх того он
может быть связан с файлом проекта (`_proj_link`): «Открыть проект…», бросок
файла проекта на вкладку (_mp.is_project_file), «Сохранить проект как…» и
проекты нейросети. Правки связанного проекта сохраняются и в этот файл
(только когда проект изменился, прежняя версия — `x.bak.montage.json`, тоже
проект); файл, изменённый снаружи (нейросеть пересобрала видео или правит
проект, в том числе пока программа была закрыта), вкладка перечитывает сама
— Ctrl+Z вернёт свою версию. Связь — часть снимка отмены: отмена открытия возвращает и прежний
проект, и его связь, а не пишет старый проект в файл нейросети.

Нейросеть (montage_tool render, MCP) после каждой сборки кладёт проект
видео рядом с ним (`<итог>.montage.json`) и записывает его в журнал
montage_handoff. Вкладка проверяет журнал раз в _POLL_MS: новый проект при
пустом таймлайне открывается сам, иначе над таймлайном появляется полоса
«Открыть проект». Последние проекты — в меню «⋯» → «Проекты нейросети»."""
import json

import montage_handoff
import montage_project as _mp

import edit_tab as _api

_POLL_MS = 2000
_MENU_MAX = 12


def _file_stamp(path):
    try:
        st = _api.os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _same_path(a, b):
    return bool(a) and bool(b) and (_api.os.path.normcase(_api.os.path.abspath(str(a)))
                                    == _api.os.path.normcase(_api.os.path.abspath(str(b))))


class EditTabProjectLinkMixin:
    """Монтаж: открытие и сохранение файла проекта, проекты нейросети."""

    def _link_init(self):
        """Из _project_init: связь проекта с файлом и журнал нейросети."""
        self._proj_link = ""             # файл проекта, куда уходят правки
        self._proj_link_stamp = None     # (mtime_ns, размер) после нашей записи/чтения
        self._proj_link_saved = None     # JSON того, что лежит в файле (не писать зря)
        self._aiproj_seen = 0.0          # время последней показанной записи журнала
        self._aiproj_stamp = None        # отметка журнала при прошлой проверке
        self._aiproj_offer = None        # запись журнала, предложенная полосой
        self._aiproj_timer = None

    # ── Панель ───────────────────────────────────────────────────────────────
    def _link_build_bar(self, lay):
        """Полоса над таймлайном: предложение открыть проект нейросети."""
        bar = _api.QFrame()
        bar.setObjectName("AiProjectBar")
        bar.setStyleSheet(f"#AiProjectBar {{ background: {_api.C['surface2']}; "
                          f"border: 1px solid {_api.C['accent']}; border-radius: 4px; }}")
        row = _api.QHBoxLayout(bar)
        row.setContentsMargins(8, 2, 4, 2)
        row.setSpacing(6)
        self.lbl_aiproj_offer = _api.QLabel()
        self.lbl_aiproj_offer.setStyleSheet(f"color: {_api.C['text']}; font-size: 12px;")
        row.addWidget(self.lbl_aiproj_offer, 1)
        btn_open = _api.QPushButton("Открыть проект")
        btn_open.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        btn_open.clicked.connect(self._aiproj_accept_offer)
        row.addWidget(btn_open)
        btn_close = _api.QPushButton("Не сейчас")
        btn_close.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self._aiproj_dismiss_offer)
        row.addWidget(btn_close)
        bar.hide()
        self._aiproj_bar = bar
        lay.addWidget(bar)

        self._aiproj_timer = _api.QTimer(self)
        self._aiproj_timer.setInterval(_POLL_MS)
        self._aiproj_timer.timeout.connect(self._link_poll)
        self._aiproj_timer.start()
        # Первая проверка — после load_settings (там время прошлой записи).
        _api.QTimer.singleShot(1500, self._link_poll)

    def _link_stop(self):
        """Из _project_shutdown."""
        timer = getattr(self, "_aiproj_timer", None)
        if timer is not None:
            timer.stop()

    # ── Состояние ────────────────────────────────────────────────────────────
    def _link_state(self):
        """Для session_state (между запусками)."""
        return {'link': self._proj_link, 'ai_seen': float(self._aiproj_seen)}

    def _link_load_state(self, state):
        if not isinstance(state, dict):
            return
        try:
            self._aiproj_seen = max(0.0, float(state.get('ai_seen') or 0.0))
        except (TypeError, ValueError):
            self._aiproj_seen = 0.0
        link = state.get('link')
        if isinstance(link, str) and link and _api.os.path.isfile(link):
            self._link_set(link)
            # Пока программа была закрыта, файл могли пересобрать (нейросеть):
            # проект вкладки не пишется в него, пока _link_poll их не сверит, —
            # другой проект из файла откроется на таймлайне (Ctrl+Z вернёт
            # прежний). Иначе первое же сохранение затирало новую сборку.
            self._proj_link_stamp = (-1, -1)

    def _link_set(self, path, saved=None):
        """Связать проект с файлом path ('' — развязать). saved — JSON, который
        сейчас лежит в файле (None — неизвестно: первая запись его перепишет)."""
        self._proj_link = str(path or "")
        self._proj_link_stamp = _file_stamp(self._proj_link) if self._proj_link else None
        self._proj_link_saved = saved if self._proj_link else None

    def _proj_state(self):
        """Снимок для отмены: проект и его связь с файлом."""
        d = self.project.to_dict()
        d['_link'] = self._proj_link
        return d

    def _project_restore_state(self, state):
        """Отмена/повтор: проект снимка и его связь."""
        link = state.get('_link', "") if isinstance(state, dict) else ""
        if not _same_path(link, self._proj_link):
            self._link_set(link if isinstance(link, str) else "")
        self._project_replace(_mp.Project.from_dict(state))

    # ── Запись в связанный файл ──────────────────────────────────────────────
    def _link_write_back(self):
        """Из _project_save: связанный проект — и в его файл. Файл, изменённый
        снаружи после нашего чтения, не затирается: его перечитает _link_poll."""
        path = self._proj_link
        if not path:
            return
        data = json.dumps(self.project.to_dict(), ensure_ascii=False, sort_keys=True)
        if data == self._proj_link_saved:
            return
        if self._proj_link_stamp is not None and _file_stamp(path) != self._proj_link_stamp:
            return
        try:
            _mp.save_project(self.project, path)
        except OSError as e:
            self._proj_status(f"проект не сохранён в {path}: {e}")
            return
        self._proj_link_saved = data
        self._proj_link_stamp = _file_stamp(path)

    # ── Открытие и сохранение ────────────────────────────────────────────────
    def project_open_dialog(self):
        start = (_api.os.path.dirname(self._proj_link) if self._proj_link
                 else self.export_dir or "")
        path, _f = _api.QFileDialog.getOpenFileName(
            self, "Открыть проект Монтажа", start,
            "Проект Монтажа (*.montage.json *.json *.montage.json.bak);;Все файлы (*)")
        if path:
            self.project_open_file(path)

    def project_open_file(self, path, note=""):
        """Проект из файла — на таймлайн (отмена — Ctrl+Z), правки — в этот
        файл. False — не открылся."""
        path = _api.os.path.abspath(str(path))
        try:
            p = _mp.load_project(path)
        except _mp.ProjectError as e:
            _api.msgbox_warning(self, "Проект", f"Проект не открылся:\n{path}\n\n{e}")
            return False
        except Exception as e:
            _api.msgbox_warning(self, "Проект", f"Проект не открылся:\n{path}\n\n{e}")
            return False
        if p.is_empty() and not p.texts:
            _api.msgbox_warning(self, "Проект", f"В проекте нет клипов:\n{path}")
            return False
        self._project_leave()
        self._project_snapshot()
        self._link_set(path, saved=json.dumps(p.to_dict(), ensure_ascii=False, sort_keys=True))
        self._project_show_loaded(p)
        missing = sorted({s for c in p.clips for s in (c.src, c.audio_path)
                          if s and not _api.os.path.exists(s)})
        msg = note or f"открыт проект {_api.os.path.basename(path)}"
        if p.is_empty():
            msg += "; клипов в нём нет — только текст, играть нечего"
        if missing:
            msg += f"; не найдено файлов: {len(missing)} ({missing[0]})"
        self._proj_status(msg + " — Ctrl+Z вернёт прежний")
        return True

    def _project_show_loaded(self, p):
        """Новый проект целиком — на таймлайн, плейхед в начало."""
        self.project_timeline.selected = ""
        self.project_timeline.select_text("")
        self._project_replace(p)
        tl = self.project_timeline
        tl.set_playhead(0.0, follow=False)
        tl.zoom_to_fit()
        if not p.is_empty():
            self._project_seek(0.0)

    def project_save_as(self):
        if self.project.is_empty() and not self.project.texts:
            self._proj_status("сохранять нечего — проект пуст")
            return
        if self._proj_link:
            default = self._proj_link
        else:
            first = next(iter(self.project.clips_on(self.project.main_track)), None)
            folder = (self.export_dir if self.export_dir and _api.os.path.isdir(self.export_dir)
                      else _api.os.path.dirname(first.src) if first is not None else "")
            stem = _api.Path(first.src).stem if first is not None else "проект"
            default = _api.os.path.join(folder, f"{stem}{montage_handoff.PROJECT_SUFFIX}")
        path, _f = _api.QFileDialog.getSaveFileName(
            self, "Сохранить проект Монтажа", default, "Проект Монтажа (*.montage.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += montage_handoff.PROJECT_SUFFIX
        try:
            _mp.save_project(self.project, path)
        except OSError as e:
            _api.msgbox_warning(self, "Проект", f"Проект не сохранён:\n{path}\n\n{e}")
            return
        self._link_set(path, saved=json.dumps(self.project.to_dict(), ensure_ascii=False,
                                              sort_keys=True))
        self._proj_status(f"проект сохранён: {path}")

    def _proj_unlink(self):
        """Проект начинают заново (файл открыт новым проектом, «Очистить»)."""
        if self._proj_link:
            self._link_set("")

    # ── Проекты нейросети ────────────────────────────────────────────────────
    def _link_poll(self):
        """Раз в _POLL_MS: связанный файл изменили снаружи — перечитать; в
        журнале нейросети новый проект — открыть или предложить."""
        if getattr(self, "project_timeline", None) is None:
            return
        path = self._proj_link
        if path and self._proj_link_stamp is not None:
            stamp = _file_stamp(path)
            if stamp is not None and stamp != self._proj_link_stamp:
                # Отметка — сразу: файл, который не читается, не должен
                # спрашивать о себе каждые две секунды.
                self._proj_link_stamp = stamp
                self._link_reload(path)
        stamp = montage_handoff.journal_stamp()
        if stamp is None or stamp == self._aiproj_stamp:
            return
        self._aiproj_stamp = stamp
        fresh = [e for e in montage_handoff.read_journal()
                 if e["time"] > self._aiproj_seen + 1e-6 and _api.os.path.isfile(e["project"])]
        if not fresh:
            return
        entry = fresh[-1]
        self._aiproj_seen = entry["time"]
        self.save_settings()
        if _same_path(entry["project"], self._proj_link):
            return                         # уже перечитан выше по отметке файла
        if self.project.is_empty() and not self.project.texts:
            self.project_open_file(entry["project"],
                                   note=f"нейросеть собрала {self._aiproj_name(entry)} — "
                                        "её проект на таймлайне")
            return
        self._aiproj_offer = entry
        self.lbl_aiproj_offer.setText(
            f"Нейросеть собрала «{self._aiproj_name(entry)}». "
            "Открыть её проект на таймлайне, чтобы поправить?")
        self._aiproj_bar.show()

    def _link_reload(self, path):
        """Связанный файл изменён снаружи: тот же проект — только запомнить,
        другой — открыть его (Ctrl+Z вернёт версию вкладки)."""
        try:
            data = json.dumps(_mp.load_project(path).to_dict(), ensure_ascii=False,
                              sort_keys=True)
        except Exception:
            data = None
        if data is not None and data in (
                self._proj_link_saved,
                json.dumps(self.project.to_dict(), ensure_ascii=False, sort_keys=True)):
            self._proj_link_saved = data
            return
        if not self.project_open_file(path, note=f"проект обновлён снаружи (нейросеть): "
                                                 f"{_api.os.path.basename(path)}"):
            # Файл не открылся (битый, без клипов) — правки вкладки его не
            # затирают: связь снята, проект вкладки остаётся как был.
            self._link_set("")

    @staticmethod
    def _aiproj_name(entry):
        return _api.os.path.basename(entry.get("output") or entry["project"])

    def _aiproj_accept_offer(self):
        entry, self._aiproj_offer = self._aiproj_offer, None
        self._aiproj_bar.hide()
        if entry is not None:
            self.project_open_file(entry["project"],
                                   note=f"проект «{self._aiproj_name(entry)}» на таймлайне")

    def _aiproj_dismiss_offer(self):
        self._aiproj_offer = None
        self._aiproj_bar.hide()

    def _aiproj_fill_menu(self, menu):
        """Подменю «Проекты нейросети»: последние сборки, новые сверху."""
        menu.clear()
        entries = [e for e in reversed(montage_handoff.read_journal())
                   if _api.os.path.isfile(e["project"])][:_MENU_MAX]
        if not entries:
            act = menu.addAction("Нейросеть ещё ничего не собирала")
            act.setEnabled(False)
            return
        for e in entries:
            when = _api.time.strftime("%d.%m %H:%M", _api.time.localtime(e["time"]))
            label = f"{self._aiproj_name(e)} — {when}"
            if e.get("preview"):
                label += " (превью)"
            act = menu.addAction(label)
            act.setToolTip(e["project"])
            act.triggered.connect(lambda _c=False, path=e["project"]: self.project_open_file(path))
