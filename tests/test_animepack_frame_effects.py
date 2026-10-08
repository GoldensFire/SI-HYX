# -*- coding: utf-8 -*-
"""Настройки и интерфейс всех эффектов раскрытия кадра."""
import json

import pytest

from animepack import PackSettings
from frame_reveal import EFFECT_LABELS, LEGACY_EFFECTS

# Эффекты, появившиеся после старых настроек: их получает любой
# сохранённый случайный набор (просьба пользователя).
NEW = [k for k in EFFECT_LABELS if k not in LEGACY_EFFECTS]


@pytest.mark.parametrize("effect", ["holes", "spots", "blots"])
def test_removed_dot_effects_are_migrated_out_of_saved_settings(effect):
    assert effect not in EFFECT_LABELS
    settings = PackSettings.from_dict({"frame_effect": effect,
                                      "frame_effects": [effect, "tiles"],
                                      "frame_effects_known": list(EFFECT_LABELS)})
    assert settings.frame_effect == "pixelize"
    assert settings.frame_effects == ["tiles"]


@pytest.fixture
def tab(qapp):
    from animepack_tab import AnimePackTab
    widget = AnimePackTab()
    yield widget
    widget.cleanup()


def test_old_pixel_settings_keep_their_effect():
    settings = PackSettings.from_dict({"pack_pixel": True, "pct_pixel": 100,
                                       "pixel_seconds": 8, "pixel_block": 96})
    assert settings.frame_effect == "pixelize"
    assert settings.pixel_seconds == 8 and settings.pixel_block == 96
    assert set(settings.frame_effects) == set(EFFECT_LABELS)


def test_effect_settings_survive_json_roundtrip():
    settings = PackSettings(frame_effect="random", frame_effects=["tiles", "zoom"],
                            frame_effect_strength=70)
    back = PackSettings.from_dict(json.loads(json.dumps(settings.to_dict())))
    assert back.frame_effect == "random"
    assert back.frame_effects == ["tiles", "zoom"]
    assert back.frame_effect_strength == 70
    assert PackSettings().frame_effects is not PackSettings().frame_effects


def test_empty_random_selection_is_only_rejected_when_needed():
    settings = PackSettings(pct_songs=0, pack_pixel=True, pct_pixel=100,
                            frame_effect="random", frame_effects=[])
    assert any("хотя бы один эффект" in p for p in settings.validate())
    settings.frame_effect = "zoom"
    assert not settings.validate()
    settings.frame_effect = "random"
    settings.pack_pixel = False
    assert not any("эффект" in p for p in settings.validate())


@pytest.mark.parametrize("effect", [*EFFECT_LABELS, "random"])
def test_each_effect_reaches_generator_and_survives_reload(tab, effect):
    tab.chk_pixel.setChecked(True)
    tab.cb_frame_effect.setCurrentIndex(tab.cb_frame_effect.findData(effect))
    tab.sp_frame_effect_strength.setValue(75)
    tab.sp_pixel_sec.setValue(12)
    tab.sp_pixel_steps.setValue(6)
    for key, check in tab.frame_effect_checks.items():
        check.setChecked(key in ("tiles", "zoom"))
    settings = tab.collect()
    assert settings.frame_effect == effect
    assert settings.frame_effects == ["tiles", "zoom"]
    assert settings.frame_effect_strength == 75
    assert settings.question_quotas["pixel"] > 0
    saved = tab.get_settings()
    tab.apply_settings(PackSettings().to_dict())
    tab.apply_settings(saved)
    assert tab.cb_frame_effect.currentData() == effect
    assert tab.collect().frame_effects == ["tiles", "zoom"]
    assert tab.collect().frame_effect_strength == 75
    assert tab.box_frame_effects.isVisibleTo(tab) == (effect == "random")


def test_timing_fields_are_not_shown(tab):
    """Длительность, кадры/с, ступени, сила и блок убраны из панели (просьба
    пользователя); значения остаются только в сохранённых настройках."""
    tab.chk_pixel.setChecked(True)
    tab.cb_frame_effect.setCurrentIndex(tab.cb_frame_effect.findData("random"))
    for spin in (tab.sp_pixel_sec, tab.sp_pixel_fps, tab.sp_pixel_steps,
                 tab.sp_frame_effect_strength, tab.sp_pixel_block):
        assert not spin.isVisibleTo(tab)
    assert not hasattr(tab, "lbl_pixel_steps")


def test_fps_and_legacy_one_step_cannot_remove_clean_final_stage(tab):
    tab.apply_settings({"pack_pixel": True, "pixel_seconds": 2,
                        "pixel_fps": 1, "pixel_steps": 1})
    assert tab.sp_pixel_steps.value() == 2


def test_reset_restores_two_second_steps_and_original_pixel_mode(tab):
    tab.cb_frame_effect.setCurrentIndex(tab.cb_frame_effect.findData("zoom"))
    tab.apply_settings(PackSettings().to_dict())
    assert tab.cb_frame_effect.currentData() == "pixelize"
    assert tab.sp_pixel_sec.value() / tab.sp_pixel_steps.value() == 2


@pytest.mark.parametrize("mode,selected,expected", [
    ("blinds", ["blinds"], ["window", *NEW]),
    ("random", ["blinds", "zoom"], ["zoom", *NEW]),
    ("random", ["blinds"], ["window", *NEW]),
])
def test_removed_blinds_migrate_without_breaking_saved_settings(tab, mode, selected, expected):
    data = {"pack_pixel": True, "pct_pixel": 100, "pct_songs": 0,
            "frame_effect": mode, "frame_effects": selected}
    settings = PackSettings.from_dict(data)
    assert settings.frame_effect == ("window" if mode == "blinds" else mode)
    assert settings.frame_effects == expected
    assert not settings.validate()
    tab.apply_settings(data)
    assert tab.collect().frame_effect == settings.frame_effect
    assert tab.collect().frame_effects == expected
    assert tab.cb_frame_effect.findData("blinds") == -1
    assert "blinds" not in tab.frame_effect_checks


@pytest.mark.parametrize("mode,selected,expected_mode,expected", [
    ("blur", ["tiles"], "pixelize", ["tiles", *NEW]),
    ("random", ["noise", "tiles"], "random", ["tiles", *NEW]),
    ("random", ["sketch", "palette"], "random", list(EFFECT_LABELS)),
])
def test_removed_effects_migrate(mode, selected, expected_mode, expected):
    """Наброски, размытие, оттенки и помехи убраны (просьба пользователя)."""
    settings = PackSettings.from_dict({
        "pack_pixel": True, "pct_pixel": 100, "pct_songs": 0,
        "frame_effect": mode, "frame_effects": selected})
    assert settings.frame_effect == expected_mode
    assert settings.frame_effects == expected
    assert not settings.validate()
    for key in ("sketch", "blur", "palette", "noise"):
        assert key not in EFFECT_LABELS


def test_new_effects_join_saved_random_set_once():
    old = PackSettings.from_dict({"frame_effect": "random",
                                  "frame_effects": ["tiles", "zoom"]})
    assert old.frame_effects == ["tiles", "zoom", *NEW]
    # Снятый после этого эффект не возвращается при следующем чтении.
    old.frame_effects.remove("swirl")
    back = PackSettings.from_dict(json.loads(json.dumps(old.to_dict())))
    assert back.frame_effects == old.frame_effects
    assert "swirl" not in back.frame_effects
    empty = PackSettings.from_dict({"frame_effects": []})
    assert empty.frame_effects == []


def test_effect_checks_fit_two_columns(tab):
    """Три колонки галочек раздували группу «Состав пака», и панель
    настроек схлопывалась в одну колонку на всю вкладку."""
    layout = tab.box_frame_effects.layout()
    columns = {layout.getItemPosition(layout.indexOf(check))[1]
               for check in tab.frame_effect_checks.values()}
    assert columns == {0, 1}
    assert set(tab.frame_effect_checks) == set(EFFECT_LABELS)


def test_dvd_folder_is_shown_only_for_dvd_and_survives_reload(tab, tmp_path):
    tab.chk_pixel.setChecked(True)
    tab.cb_frame_effect.setCurrentIndex(tab.cb_frame_effect.findData("zoom"))
    assert not tab.box_dvd_folder.isVisibleTo(tab)
    tab.cb_frame_effect.setCurrentIndex(tab.cb_frame_effect.findData("dvd"))
    assert tab.box_dvd_folder.isVisibleTo(tab)
    tab.ed_dvd_folder.setText(str(tmp_path))
    saved = tab.get_settings()
    tab.apply_settings(PackSettings().to_dict())
    assert tab.ed_dvd_folder.text() == ""
    tab.apply_settings(saved)
    assert tab.collect().frame_dvd_folder == str(tmp_path)


def test_dvd_fps_choice_is_shown_for_dvd_and_survives_reload(tab):
    tab.chk_pixel.setChecked(True)
    tab.cb_frame_effect.setCurrentIndex(tab.cb_frame_effect.findData("zoom"))
    assert not tab.cb_dvd_fps.isVisibleTo(tab)
    tab.cb_frame_effect.setCurrentIndex(tab.cb_frame_effect.findData("dvd"))
    assert tab.cb_dvd_fps.isVisibleTo(tab)
    assert tab.collect().frame_dvd_fps == 30          # по умолчанию как было
    tab.cb_dvd_fps.setCurrentIndex(tab.cb_dvd_fps.findData(60))
    saved = tab.get_settings()
    tab.apply_settings(PackSettings().to_dict())
    assert tab.cb_dvd_fps.currentData() == 30
    tab.apply_settings(saved)
    assert tab.collect().frame_dvd_fps == 60
