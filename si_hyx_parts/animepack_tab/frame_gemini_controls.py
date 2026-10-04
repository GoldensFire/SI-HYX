# -*- coding: utf-8 -*-
"""Независимые проверки обычных кадров и кадров с эффектами."""
import animepack_tab as api


def build_controls(tab):
    tab.box_frames = api.SettingsBox()
    layout = api.QGridLayout(tab.box_frames)
    layout.setContentsMargins(16, 0, 0, 0)
    for name, box in (("frame", tab.box_frames), ("pixel", tab.box_pixel)):
        check = api.QCheckBox("Проверять кадр через Gemini")
        check.setToolTip(
            "Проверяет исходный кадр до эффектов: название или логотип тайтла "
            "на кадре — повод выбрать другой. В том же запросе определяется, "
            "есть ли персонажи; если их нет, цена повышается на +2. "
            "До четырёх картинок объединяются в один запрос. "
            "Используются общие ключ и модель Gemini.")
        setattr(tab, f"chk_{name}_gemini", check)
        grid = box.layout()
        grid.addWidget(check, grid.rowCount(), 0, 1, 4)
        check.toggled.connect(lambda _: tab._refresh_song_opts())
    tab.box_frames.hide()


def collect(tab, settings):
    settings.frame_gemini_check = tab.chk_frame_gemini.isChecked()
    settings.pixel_gemini_check = tab.chk_pixel_gemini.isChecked()


def apply_controls(tab, settings):
    tab.chk_frame_gemini.setChecked(settings.frame_gemini_check)
    tab.chk_pixel_gemini.setChecked(settings.pixel_gemini_check)


def refresh(tab):
    tab.box_frames.setVisible(tab.chk_frames.isChecked())
    return ((tab.chk_frames.isChecked() and tab.chk_frame_gemini.isChecked())
            or (tab.chk_pixel.isChecked() and tab.chk_pixel_gemini.isChecked()))
