# -*- coding: utf-8 -*-
"""Все эффекты движутся, воспроизводимы и заканчиваются исходным кадром."""
import json

import pytest
from PIL import Image, ImageDraw

from animepack import PackSettings
from image_entrance import (
    EFFECTS, EFFECT_LABELS, EDITOR_ONLY_EFFECTS, PACK_EFFECTS, TARGET_LABELS)
from image_entrance_renderer import render


@pytest.fixture
def picture():
    image = Image.new("RGB", (160, 90), "#4594cf")
    draw = ImageDraw.Draw(image)
    for x in range(0, 160, 8):
        draw.rectangle((x, 0, x + 3, 89), fill=(x, 180, 255 - x))
    draw.ellipse((48, 12, 116, 82), fill="#f4c897", outline="#282133", width=3)
    return image


@pytest.mark.parametrize("effect", EFFECTS)
def test_effect_is_animated_and_finishes_clean(picture, effect):
    frames = [render(picture, effect, p, 80, 42) for p in (0, 0.2, 0.6, 1)]
    assert all(frame.size == picture.size and frame.mode == "RGB" for frame in frames)
    assert frames[-1].tobytes() == picture.tobytes()
    assert len({frame.tobytes() for frame in frames}) >= 3
    assert render(picture, effect, 0.2, 80, 42).tobytes() == frames[1].tobytes()


def test_all_25_effects_are_distinct(picture):
    assert len(EFFECTS) == 25
    assert len({tuple(render(picture, effect, p, 80, 42).tobytes()
                      for p in (0.15, 0.45, 0.75)) for effect in EFFECTS}) == 25
    assert all(any("а" <= letter.lower() <= "я" for letter in label)
               for label in EFFECT_LABELS.values())


def test_settings_roundtrip_keeps_only_known_choices():
    settings = PackSettings(entrance_enabled=True, entrance_effect="random",
                            entrance_effects=["flip", "ripple"],
                            entrance_targets=["frame", "manga", "sakuga"],
                            entrance_seconds=0.7, entrance_fps=24)
    restored = PackSettings.from_dict(json.loads(json.dumps(settings.to_dict())))
    assert restored.entrance_effects == ["flip", "ripple"]
    assert restored.entrance_targets == ["frame", "manga", "sakuga"]
    assert restored.entrance_seconds == 0.7 and restored.entrance_fps == 24
    data = settings.to_dict()
    data.update(entrance_effects=["flip", "obsolete", "flip", []],
                entrance_targets=["manga", "songs", "manga"])
    clean = PackSettings.from_dict(data)
    assert clean.entrance_effects == ["flip"] and clean.entrance_targets == ["manga"]
    assert PackSettings().entrance_effects is not PackSettings().entrance_effects


def test_empty_selection_is_rejected_only_when_enabled():
    settings = PackSettings(entrance_effects=[], entrance_targets=[])
    assert not settings.validate()
    settings.entrance_enabled = True
    assert any("составы" in error for error in settings.validate())
    assert any("хотя бы один эффект появления" in error for error in settings.validate())
    settings.entrance_effect = "flip"
    settings.entrance_targets = ["manga"]
    assert not settings.validate()


def test_separate_page_and_all_choices_survive_reload(qapp):
    from animepack_tab import AnimePackTab
    tab = AnimePackTab()
    try:
        assert [tab.settings_tabs.tabText(i) for i in range(tab.settings_tabs.count())] == ["Настройки", "Появление"]
        quotas = tab.collect().question_quotas
        tab.chk_entrance.setChecked(True)
        for check in tab.entrance_target_checks.values():
            check.setChecked(True)
        for key, check in tab.entrance_effect_checks.items():
            check.setChecked(key in ("flip", "ripple"))
        tab.sp_entrance_seconds.setValue(0.7)
        assert len(tab.entrance_effect_checks) == 20
        assert not EDITOR_ONLY_EFFECTS.intersection(tab.entrance_effect_checks)
        for effect in EDITOR_ONLY_EFFECTS:
            assert tab.cb_entrance_effect.findData(effect) == -1
        for effect in PACK_EFFECTS:
            tab.cb_entrance_effect.setCurrentIndex(tab.cb_entrance_effect.findData(effect))
            assert tab.collect().entrance_effect == effect
        tab.cb_entrance_effect.setCurrentIndex(0)
        saved = tab.get_settings()
        tab.apply_settings(PackSettings().to_dict())
        tab.apply_settings(saved)
        restored = tab.collect()
        assert restored.entrance_enabled and restored.entrance_effect == "random"
        assert restored.entrance_effects == ["flip", "ripple"]
        assert restored.entrance_targets == list(TARGET_LABELS)
        assert restored.entrance_seconds == 0.7
        assert restored.question_quotas == quotas
        tab.settings_tabs.setCurrentIndex(1)
        tab.show()
        qapp.processEvents()
        assert tab.entrance_preview.timer.isActive()
        tab.settings_tabs.setCurrentIndex(0)
        qapp.processEvents()
        assert not tab.entrance_preview.timer.isActive()
    finally:
        tab.cleanup()
        tab.close()


def test_removed_generation_effects_are_migrated():
    for effect in EDITOR_ONLY_EFFECTS:
        settings = PackSettings.from_dict({
            "entrance_enabled": True, "entrance_effect": effect,
            "entrance_effects": [effect], "entrance_targets": ["frame"]})
        assert settings.entrance_effect == "random"
        assert set(settings.entrance_effects) == set(PACK_EFFECTS)
        assert not settings.validate()
    settings = PackSettings.from_dict({"entrance_effects": ["fly", "flip"]})
    assert settings.entrance_effects == ["flip"]
    assert not EDITOR_ONLY_EFFECTS.intersection(PackSettings().entrance_effects)
