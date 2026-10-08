# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Компактная панель выбора и настройки раскрытия кадра."""
import animepack_tab as _api
from frame_reveal import EFFECT_HINTS, EFFECT_LABELS, clean_effects
from frame_reveal_dvd import DVD_FPS, DVD_FPS_CHOICES, dvd_fps


def build_controls(tab):
    # Имена pixel оставлены для совместимости формы, настроек и долей пака.
    tab.chk_pixel = _api.QCheckBox("Кадры с эффектами")
    tab.chk_pixel.setToolTip(
        "Кадр аниме превращается в ролик и постепенно раскрывается.\n"
        "Выберите один эффект или случайный из отмеченных.\n"
        "Кадры берутся из тех же источников, что и обычные вопросы по кадру.")
    tab.chk_pixel.toggled.connect(tab._on_pixel_toggled)
    tab.box_pixel = _api.SettingsBox()
    grid = _api.QGridLayout(tab.box_pixel)
    grid.setContentsMargins(16, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    tab.cb_frame_effect = _api.QComboBox()
    for key, label in EFFECT_LABELS.items():
        tab.cb_frame_effect.addItem(label, key)
    tab.cb_frame_effect.addItem("Случайный эффект из выбранных", "random")
    grid.addWidget(tab._lab("Эффект"), 0, 0)
    grid.addWidget(tab.cb_frame_effect, 0, 1, 1, 3)

    tab.box_frame_effects = _api.SettingsBox()
    choices = _api.QGridLayout(tab.box_frame_effects)
    choices.setContentsMargins(0, 0, 0, 0)
    tab.frame_effect_checks = {}
    for i, (key, label) in enumerate(EFFECT_LABELS.items()):
        check = _api.QCheckBox(label)
        check.setChecked(True)
        check.setToolTip(EFFECT_HINTS[key])
        check.toggled.connect(tab._refresh_pixel_hint)
        tab.frame_effect_checks[key] = check
        # Две колонки, а не три: три колонки галочек просили 656 px, группа
        # «Состав пака» переставала помещаться рядом с соседями, и панель
        # настроек схлопывалась в одну колонку на всю вкладку.
        choices.addWidget(check, i // 2, i % 2)
    grid.addWidget(tab.box_frame_effects, 1, 0, 1, 4)

    # Длительность, кадры/с, ступени, сила и блок из панели убраны (просьба
    # пользователя): поля остаются скрытыми держателями сохранённых значений.
    tab.sp_pixel_sec = _hidden_spin(tab, 2, 60, _api.PIXEL_SECONDS)
    tab.sp_pixel_fps = _hidden_spin(tab, 1, 60, _api.PIXEL_FPS)
    tab.sp_pixel_steps = _hidden_spin(tab, 2, 20, _api.PIXEL_STEPS)
    tab.sp_frame_effect_strength = _hidden_spin(tab, 10, 100, 55)
    tab.sp_pixel_block = _hidden_spin(tab, 4, 256, _api.PIXEL_BLOCK)
    tab.sp_frame_preset = _api.QSpinBox()
    tab.sp_frame_preset.setRange(0, 13)
    tab.sp_frame_preset.setValue(_api.VIDEO_PRESET)
    tab.sp_frame_preset.setToolTip(
        "Пресет кодирования кадров с эффектами, включая DVD-заставку.\n"
        "13 — самый быстрый, 0 — самый медленный. Значение можно вписать.\n"
        "У песенных роликов и сакуги свои пресеты.")
    grid.addWidget(tab._lab("Пресет кодирования"), 2, 0)
    grid.addWidget(tab.sp_frame_preset, 2, 1)
    _build_dvd_folder(tab, grid, 3)
    _build_dvd_fps(tab, grid, 4)
    tab.cb_frame_effect.currentIndexChanged.connect(tab._refresh_pixel_hint)
    grid.setColumnStretch(1, 1)
    grid.setColumnStretch(3, 1)
    tab.box_pixel.setVisible(False)
    refresh_controls(tab)


def _hidden_spin(tab, low: int, high: int, value: int):
    spin = _api.QSpinBox(tab.box_pixel)
    spin.setRange(low, high)
    spin.setValue(value)
    spin.hide()
    return spin


def _build_dvd_folder(tab, grid, row: int) -> None:
    """Папка картинок и видео для прямоугольника «DVD-заставки»."""
    tab.lbl_dvd_folder = tab._lab("Папка DVD")
    tab.box_dvd_folder = _api.QWidget()
    line = _api.QHBoxLayout(tab.box_dvd_folder)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(4)
    tab.ed_dvd_folder = _api.QLineEdit()
    tab.ed_dvd_folder.setPlaceholderText("не задана — прямоугольник окно в кадр")
    tab.ed_dvd_folder.setToolTip(
        "Папка с картинками и видео (подпапки тоже). Прямоугольник заставки\n"
        "показывает случайный файл отсюда и меняет его при каждом отскоке;\n"
        "форма прямоугольника — как у файла. Видео идёт без звука.")
    tab.btn_dvd_folder = _api.QToolButton()
    tab.btn_dvd_folder.setText("…")
    tab.btn_dvd_folder.clicked.connect(lambda: _pick_dvd_folder(tab))
    line.addWidget(tab.ed_dvd_folder, 1)
    line.addWidget(tab.btn_dvd_folder)
    grid.addWidget(tab.lbl_dvd_folder, row, 0)
    grid.addWidget(tab.box_dvd_folder, row, 1, 1, 3)


def _build_dvd_fps(tab, grid, row: int) -> None:
    """Своя частота кадров «DVD-заставки»: 30 или 60."""
    tab.lbl_dvd_fps = tab._lab("DVD, кадров/с")
    tab.cb_dvd_fps = _api.QComboBox()
    for fps in DVD_FPS_CHOICES:
        tab.cb_dvd_fps.addItem(str(fps), fps)
    tab.cb_dvd_fps.setToolTip(
        "Частота кадров ролика с DVD-заставкой. 60 — движение плавнее,\n"
        "но ролик тяжелее и собирается примерно вдвое дольше.")
    tab.cb_dvd_fps.currentIndexChanged.connect(tab._refresh_pixel_hint)
    grid.addWidget(tab.lbl_dvd_fps, row, 0)
    grid.addWidget(tab.cb_dvd_fps, row, 1)


def _pick_dvd_folder(tab) -> None:
    folder = _api.QFileDialog.getExistingDirectory(
        tab, "Папка с картинками и видео для DVD-заставки",
        tab.ed_dvd_folder.text().strip())
    if folder:
        tab.ed_dvd_folder.setText(folder)


def selected_effects(tab):
    return [key for key, check in tab.frame_effect_checks.items() if check.isChecked()]


def refresh_controls(tab):
    if not hasattr(tab, "cb_frame_effect"):
        return
    mode = tab.cb_frame_effect.currentData()
    is_random = mode == "random"
    tab.box_frame_effects.setVisible(is_random)
    active = selected_effects(tab) if is_random else [mode]
    dvd = "dvd" in active
    tab.lbl_dvd_folder.setVisible(dvd)
    tab.box_dvd_folder.setVisible(dvd)
    tab.lbl_dvd_fps.setVisible(dvd)
    tab.cb_dvd_fps.setVisible(dvd)
    tab._fit_settings_width()


def apply_controls(tab, settings):
    tab.sp_frame_preset.setValue(max(0, min(13, int(settings.frame_preset))))
    index = tab.cb_frame_effect.findData(settings.frame_effect)
    tab.cb_frame_effect.setCurrentIndex(max(0, index))
    selected = clean_effects(settings.frame_effects)
    for key, check in tab.frame_effect_checks.items():
        check.setChecked(key in selected)
    tab.sp_frame_effect_strength.setValue(settings.frame_effect_strength)
    tab.ed_dvd_folder.setText(str(getattr(settings, "frame_dvd_folder", "") or ""))
    fps = dvd_fps(getattr(settings, "frame_dvd_fps", DVD_FPS))
    tab.cb_dvd_fps.setCurrentIndex(max(0, tab.cb_dvd_fps.findData(fps)))
    refresh_controls(tab)
