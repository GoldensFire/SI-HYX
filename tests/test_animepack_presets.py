# -*- coding: utf-8 -*-
"""Редактируемые шаблоны лёгкого, среднего и сложного пака."""
import animepack_tab
from si_hyx_parts.animepack_tab.default_presets import DEFAULT_TEMPLATES


def _levels(source, prefix=""):
    get = source.get if isinstance(source, dict) else (
        lambda key: getattr(source, key))
    return tuple(get(f"{prefix}level_{part}") for part in ("min", "max", "avg"))


def test_default_templates_apply_and_keep_pack_identity(qapp):
    tab = animepack_tab.AnimePackTab(settings={"title": "Мой пак"})
    try:
        assert [tab.cb_template.itemText(i)
                for i in range(tab.cb_template.count())][:3] == [
                    "Лёгкий", "Средний", "Сложный"]
        tab.cb_template.setCurrentText("Лёгкий")
        tab._apply_template()
        settings = tab.collect()
        assert settings.title == "Мой пак"
        easy = DEFAULT_TEMPLATES["Лёгкий"]
        assert settings.difficulty_min == easy["difficulty_min"]
        assert _levels(settings) == _levels(easy)
    finally:
        tab.cleanup()


def test_hard_template_keeps_levels_above_eight_after_roundtrip(qapp):
    tab = animepack_tab.AnimePackTab()
    try:
        tab.cb_template.setCurrentText("Сложный")
        tab._apply_template()
        settings = tab.collect()
        hard = DEFAULT_TEMPLATES["Сложный"]
        assert max(_levels(hard)) > 8
        assert _levels(settings) == _levels(hard)
        for prefix in ("song", "studio", "char", "art", "manga", "plot"):
            assert (_levels(settings, f"{prefix}_")
                    == _levels(hard, f"{prefix}_"))
        tab.apply_settings(tab.get_settings())
        assert (tab.sp_level_from.value(), tab.sp_level_to.value(),
                tab.sp_level_avg.value()) == _levels(hard)
    finally:
        tab.cleanup()


def test_edited_template_survives_settings_roundtrip(qapp):
    tab = animepack_tab.AnimePackTab()
    try:
        tab.cb_template.setCurrentText("Средний")
        tab.sp_diff_min.setValue(41)
        tab._update_template()
        saved = tab.get_settings()
        assert saved["_templates"]["Средний"]["difficulty_min"] == 41
        assert saved["_active_template"] == "Средний"
    finally:
        tab.cleanup()


def test_template_can_be_renamed_in_its_title_and_deleted_by_icon(qapp, monkeypatch):
    tab = animepack_tab.AnimePackTab()
    try:
        assert not hasattr(tab, "btn_edit_template")
        assert tab.cb_template.isEditable()
        tab.cb_template.lineEdit().setText("Мой шаблон")
        tab._rename_template()
        assert "Мой шаблон" in tab._templates
        assert "Средний" not in tab._templates
        assert tab.cb_template.currentText() == "Мой шаблон"
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        tab.btn_delete_template.click()
        assert "Мой шаблон" not in tab._templates
        assert "Мой шаблон" in tab._deleted_templates
    finally:
        tab.cleanup()


def test_update_confirms_only_after_settings_are_saved(qapp, monkeypatch, tmp_path):
    import json
    import utils

    tab = animepack_tab.AnimePackTab()
    calls = []
    path = tmp_path / "settings.json"
    monkeypatch.setattr(utils, "SETTINGS_FILE", str(path))
    class Main:
        def _save_settings_now(self):
            saved = utils.save_settings({"animepack": tab.get_settings()})
            if saved:
                calls.append("saved")
            return saved
    try:
        tab.main = Main()
        tab.sp_diff_min.setValue(41)
        tab._update_template()
        assert calls == ["saved"]
        assert not tab.template_notice.isHidden()
        assert "Средний" in tab.template_notice.text()
        assert json.loads(path.read_text(encoding="utf-8"))["animepack"]["_templates"]["Средний"]["difficulty_min"] == 41
    finally:
        tab.cleanup()
