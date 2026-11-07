# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: свойства клипа, текста и проекта (окна edit_tab_dialogs).

Каждое «Применить» — шаг отмены (Ctrl+Z) и сохранение проекта; значения
проходят чистку модели (Clip.__post_init__, parse_texts, parse_settings), как
у файла проекта. В просмотре с эффектами (FX) правка видна сразу."""
import dataclasses

import montage_project as _mp

import edit_tab as _api


class EditTabProjectPropsMixin:
    """Монтаж: окна свойств проекта."""

    def project_clip_props(self, cid=None):
        clip = self.project.clip(cid or self.project_timeline.selected)
        if clip is None:
            self._proj_status("выделите клип — свойства у выделенного клипа")
            return
        cid = clip.id

        def apply(vals):
            c = self.project.clip(cid)
            if c is None:
                return
            data = {f.name: getattr(c, f.name) for f in dataclasses.fields(_mp.Clip)}
            data.update(vals)
            try:
                fixed = _mp.Clip(**data)
            except (TypeError, ValueError) as e:
                _api.msgbox_warning(self, "Клип", f"Свойства не применены: {e}")
                return
            self._project_snapshot()
            for f in dataclasses.fields(_mp.Clip):
                setattr(c, f.name, getattr(fixed, f.name))
            self.project.pack()
            self._project_changed()

        on_main = clip.track == self.project.main_track
        _api.ClipPropsDialog(clip, on_main, apply, self).exec()

    def project_text_props(self, tid):
        item = self._project_text(tid)
        if item is None:
            return

        def apply(vals):
            cur = self._project_text(tid)
            if cur is None:
                return
            if not vals["text"].strip():
                _api.msgbox_warning(self, "Текст", "Текст пустой — удалите его клавишей Delete.")
                return
            d = {"id": cur.id, "layer": cur.layer, **vals}
            parsed = _mp.parse_texts([d])
            if not parsed:
                _api.msgbox_warning(self, "Текст", "Конец текста должен быть позже начала.")
                return
            new = parsed[0]
            self._project_snapshot()
            for f in dataclasses.fields(_mp.TextItem):
                setattr(cur, f.name, getattr(new, f.name))
            self.project.texts.sort(key=lambda t: (t.start, t.end))
            self._project_changed()

        _api.TextPropsDialog(item, apply, self).exec()

    def project_settings_dialog(self):
        def apply(vals):
            data = dataclasses.asdict(self.project.settings)
            data.update(vals)
            self._project_snapshot()
            self.project.settings = _mp.parse_settings(data)
            self._project_changed()

        _api.ProjectSettingsDialog(self.project, apply, self).exec()
