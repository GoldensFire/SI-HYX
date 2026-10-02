# -*- coding: utf-8 -*-
"""Пресет эффектов независим от сакуги и песенных роликов."""
import animepack as ap


def test_old_settings_keep_the_previous_frame_preset():
    settings = ap.PackSettings.from_dict({"video_preset": 3, "sakuga_preset": 6})
    assert settings.frame_preset == 3
    settings.frame_preset = 8
    restored = ap.PackSettings.from_dict(settings.to_dict())
    assert (restored.video_preset, restored.sakuga_preset, restored.frame_preset) == (3, 6, 8)


def test_all_frame_effect_encoders_use_their_own_preset():
    gen = ap.AnimePackGenerator(ap.PackSettings(
        video_preset=3, sakuga_preset=6, frame_preset=8), session=object())
    args = gen.pixel_encode_args("setsar=1")
    assert args[args.index("-preset") + 1] == "8"
    song_args = gen.video_encode_args()
    assert song_args[song_args.index("-preset") + 1] == "3"


def test_typed_frame_preset_survives_ui_save_and_restore(qapp):
    from animepack_tab import AnimePackTab
    tab, fresh = AnimePackTab(), AnimePackTab()
    try:
        tab.apply_settings({"video_preset": 3, "sakuga_preset": 6})
        assert tab.sp_frame_preset.value() == 3
        tab.sp_frame_preset.lineEdit().setText("8")
        tab.sp_frame_preset.interpretText()
        fresh.apply_settings(tab.get_settings())
        settings = fresh.collect()
        assert (settings.video_preset, settings.sakuga_preset, settings.frame_preset) == (3, 6, 8)
    finally:
        tab.cleanup()
        fresh.cleanup()


def test_exclusion_count_does_not_show_the_whole_pack_list(qapp):
    from animepack_tab import AnimePackTab
    tab = AnimePackTab()
    try:
        tab.apply_settings({"exclude_exact_siq": [f"pack-{i}.siq" for i in range(63)]})
        assert "63" in tab.lbl_exact_siq.text()
        assert not tab.lbl_exact_siq.toolTip()
    finally:
        tab.cleanup()
