# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Компактная панель выбора и настройки раскрытия кадра."""
import animepack_tab as _api
from frame_reveal import EFFECT_HINTS, EFFECT_LABELS, clean_effects, stage_frame_counts
from frame_reveal import window_area
from frame_reveal_dvd import DVD_FPS, DVD_FPS_CHOICES, dvd_fps
from pixelize import block_sequence


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
    note = tab._hint("На каждый вопрос — один случайный эффект из отмеченных.")
    note.setWordWrap(True)
    choices.addWidget(note, 0, 0, 1, 2)
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
        choices.addWidget(check, i // 2 + 1, i % 2)
    grid.addWidget(tab.box_frame_effects, 1, 0, 1, 4)

    tab.sp_pixel_sec = _api.QSpinBox()
    tab.sp_pixel_sec.setRange(2, 60)
    tab.sp_pixel_sec.setValue(_api.PIXEL_SECONDS)
    tab.sp_pixel_sec.setSuffix(" с")
    tab.sp_pixel_sec.setToolTip("Длительность всего раскрытия, включая чистый кадр в конце.")
    tab.sp_pixel_fps = _api.QSpinBox()
    tab.sp_pixel_fps.setRange(1, 60)
    tab.sp_pixel_fps.setValue(_api.PIXEL_FPS)
    tab.sp_pixel_fps.setToolTip("Кадры в секунду. Для ступенчатых эффектов достаточно 10.")
    tab.sp_pixel_steps = _api.QSpinBox()
    tab.sp_pixel_steps.setRange(2, 20)
    tab.sp_pixel_steps.setValue(_api.PIXEL_STEPS)
    tab.sp_pixel_steps.setToolTip(
        "Количество ступеней, включая последнюю с чистым кадром.\n"
        "Например: 12 секунд и 6 ступеней — улучшение каждые 2 секунды.")
    tab.sp_frame_effect_strength = _api.QSpinBox()
    tab.sp_frame_effect_strength.setRange(10, 100)
    tab.sp_frame_effect_strength.setValue(55)
    tab.sp_frame_effect_strength.setSuffix(" %")
    tab.sp_frame_effect_strength.setToolTip(
        "Чем выше сила, тем сложнее начало. Для пикселизации используется размер блока.")
    tab.sp_pixel_block = _api.QSpinBox()
    tab.sp_pixel_block.setRange(4, 256)
    tab.sp_pixel_block.setSingleStep(4)
    tab.sp_pixel_block.setValue(_api.PIXEL_BLOCK)
    tab.sp_pixel_block.setToolTip("Размер начального блока. Только для пикселизации.")
    fields = (("Длительность", tab.sp_pixel_sec, "Кадров/с", tab.sp_pixel_fps),
              ("Ступеней", tab.sp_pixel_steps, "Сила", tab.sp_frame_effect_strength))
    for row, (label, control, label2, control2) in enumerate(fields, 2):
        grid.addWidget(tab._lab(label), row, 0)
        grid.addWidget(control, row, 1)
        grid.addWidget(tab._lab(label2), row, 2)
        grid.addWidget(control2, row, 3)
    grid.addWidget(tab._lab("Блок, px"), 4, 0)
    grid.addWidget(tab.sp_pixel_block, 4, 1)
    tab.sp_frame_preset = _api.QSpinBox()
    tab.sp_frame_preset.setRange(0, 13)
    tab.sp_frame_preset.setValue(_api.VIDEO_PRESET)
    tab.sp_frame_preset.setToolTip(
        "Пресет кодирования кадров с эффектами, включая DVD-заставку.\n"
        "13 — самый быстрый, 0 — самый медленный. Значение можно вписать.\n"
        "У песенных роликов и сакуги свои пресеты.")
    grid.addWidget(tab._lab("Пресет кодирования"), 4, 2)
    grid.addWidget(tab.sp_frame_preset, 4, 3)
    _build_dvd_folder(tab, grid, 5)
    _build_dvd_fps(tab, grid, 6)
    tab.lbl_pixel_steps = tab._hint("")
    tab.lbl_pixel_steps.setWordWrap(True)
    grid.addWidget(tab.lbl_pixel_steps, 7, 0, 1, 4)
    for control in (tab.sp_pixel_sec, tab.sp_pixel_fps, tab.sp_pixel_steps,
                    tab.sp_pixel_block, tab.sp_frame_effect_strength):
        control.setMinimumWidth(54)
        control.valueChanged.connect(tab._refresh_pixel_hint)
    tab.cb_frame_effect.currentIndexChanged.connect(tab._refresh_pixel_hint)
    grid.setColumnStretch(1, 1)
    grid.setColumnStretch(3, 1)
    tab.box_pixel.setVisible(False)
    refresh_controls(tab)


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
        "но ролик тяжелее и собирается примерно вдвое дольше.\n"
        "Общий «Кадров/с» относится только к остальным эффектам.")
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
    if not hasattr(tab, "sp_frame_effect_strength"):
        return
    mode = tab.cb_frame_effect.currentData()
    is_random = mode == "random"
    tab.box_frame_effects.setVisible(is_random)
    active = selected_effects(tab) if is_random else [mode]
    tab.sp_pixel_block.setEnabled("pixelize" in active)
    tab.sp_frame_effect_strength.setEnabled(any(k != "pixelize" for k in active))
    dvd = "dvd" in active
    tab.lbl_dvd_folder.setVisible(dvd)
    tab.box_dvd_folder.setVisible(dvd)
    tab.lbl_dvd_fps.setVisible(dvd)
    tab.cb_dvd_fps.setVisible(dvd)
    fps = tab.sp_pixel_fps.value()
    duration = tab.sp_pixel_sec.value()
    tab.sp_pixel_steps.setMaximum(min(20, duration * fps))
    counts = stage_frame_counts(duration, fps, tab.sp_pixel_steps.value())
    interval = f"{duration / len(counts):.2f}".rstrip("0").rstrip(".")
    final = f"{counts[-1] / fps:.2f}".rstrip("0").rstrip(".")
    timing = f"Шаг примерно каждые {interval} с. В конце — чистый кадр на {final} с."
    if not active:
        description = "Отметьте хотя бы один эффект для случайного выбора."
    elif is_random:
        description = f"Выбрано эффектов: {len(active)}. Каждый вопрос получает один из них."
    else:
        description = EFFECT_HINTS.get(mode, "")
    if mode == "window":
        strength = tab.sp_frame_effect_strength.value()
        description += "\nОткрыто по ступеням: " + " → ".join(
            f"{window_area(strength, i / (len(counts) - 1)):.0%}"
            for i in range(len(counts)))
    if dvd:
        description += (f"\nDVD-заставка движется плавно, "
                        f"{tab.cb_dvd_fps.currentData() or DVD_FPS} кадров/с, "
                        "и к чистому кадру сама открывает весь экран — "
                        "«Кадров/с» и ступени её не касаются.")
    if "pixelize" in active:
        seq = block_sequence(tab.sp_pixel_block.value(), len(counts))
        description += "\nБлоки по ступеням: " + " → ".join(
            f"{b}px" if b > 1 else "чётко" for b in seq)
    tab.lbl_pixel_steps.setText(description + "\n" + timing)
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
