# -*- coding: utf-8 -*-
"""Редактируемые шаблоны лёгкого, среднего и сложного пака."""
import animepack_tab


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
        assert settings.difficulty_min == 65
        assert (settings.level_min, settings.level_max, settings.level_avg) == (
            1, 6, 3)
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
