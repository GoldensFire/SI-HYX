# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: текст проекта (Project.texts) на таймлайне.

Титры, строки и слова песни, которые ставит нейросеть (montage_tool op
text/words/lyrics, карточки), лежат на полосе «Текст» таймлайна. Перенос и
подрезку делает сам ProjectTimeline; здесь — добавление и удаление по его
actionRequested (text_add, text_delete), правка (text_edit) — окно свойств
(project_props). Новый текст берёт вид, место и слой у выделенного текста.
Виден текст в просмотре с эффектами (project_fx) и в собранном видео."""
import montage_project as _mp

import edit_tab as _api

_NEW_TEXT_S = 3.0


class EditTabProjectTextsMixin:
    """Монтаж: правка текста проекта."""

    def _project_text_action(self, action, tid):
        if action == 'text_edit':
            self.project_text_edit(tid)
        elif action == 'text_delete':
            self.project_text_delete(tid)
        elif action == 'text_add':
            self.project_text_add()

    def _project_text(self, tid):
        return next((t for t in self.project.texts if t.id == tid), None) if tid else None

    def project_text_edit(self, tid):
        """Двойной клик по тексту: окно свойств (текст, время, вид, место,
        анимация — project_props)."""
        self.project_text_props(tid)

    def project_text_delete(self, tid=None):
        tid = tid or self.project_timeline.selected_text
        item = self._project_text(tid)
        if item is None:
            return
        self._project_snapshot()
        self.project.texts.remove(item)
        self.project_timeline.select_text("")
        self._project_changed()

    def project_text_add(self):
        """Новый текст у плейхеда на _NEW_TEXT_S; вид — как у выделенного текста."""
        text, ok = _api.QInputDialog.getMultiLineText(
            self, "Текст проекта", "Текст у плейхеда:", "")
        if not ok or not text.strip():
            return
        tl = self.project_timeline
        like = self._project_text(tl.selected_text)
        _w, _h, fps = self.project.output_format()
        start = _mp.snap_to_frame(tl.playhead, fps)
        item = _mp.TextItem(start=start, end=start + _NEW_TEXT_S, text=text)
        if like is not None:
            item.style = dict(like.style or {})
            item.pos_x, item.pos_y, item.layer = like.pos_x, like.pos_y, like.layer
        self._project_snapshot()
        self.project.texts.append(item)
        self.project.texts.sort(key=lambda t: (t.start, t.end))
        self._project_changed()
        tl.select_text(item.id)
