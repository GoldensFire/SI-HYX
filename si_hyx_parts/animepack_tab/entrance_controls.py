# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Отдельная вкладка появления: выбор эффектов, составов и предпросмотр."""
import animepack_tab as _api

from image_entrance import PACK_EFFECTS as EFFECTS, TARGET_LABELS
from .settings_columns import SettingsColumns


def build_page(tab):
    scroll = _api.QScrollArea()
    scroll.setWidgetResizable(True)
    panel = _api.QWidget()
    panel.setObjectName("entranceSettingsPage")
    panel.setStyleSheet(f"#entranceSettingsPage {{ background: {_api.C['bg']}; }}")
    layout = _api.QVBoxLayout(panel)
    layout.setContentsMargins(8, 8, 8, 8)
    tab.chk_entrance = _api.QCheckBox("Включить эффекты появления")
    layout.addWidget(tab.chk_entrance)
    layout.addWidget(tab._hint(
        "В вопрос добавляется только готовое видео с таймером 5 секунд. "
        "В роликах эффект накладывается на начало видео; звук и общая "
        "длительность файла сохраняются."))
    options = _build_options(tab)
    targets = _build_targets(tab)
    choices = _build_choices(tab)
    tab.entrance_columns = SettingsColumns([options, targets, choices], 300)
    layout.addWidget(tab.entrance_columns)
    layout.addStretch()
    tab.chk_entrance.toggled.connect(lambda: _refresh(tab))
    tab.cb_entrance_effect.currentIndexChanged.connect(lambda: _refresh(tab))
    for field in (tab.sp_entrance_seconds, tab.sp_entrance_strength):
        field.valueChanged.connect(lambda: tab.entrance_preview.restart())
    scroll.setWidget(panel)
    tab._disable_wheel(panel)
    _refresh(tab)
    return scroll


def _build_options(tab):
    group = _api.QGroupBox("Появление картинки")
    layout = _api.QVBoxLayout(group)
    tab.cb_entrance_effect = _api.QComboBox()
    tab.cb_entrance_effect.addItem("Случайный из отмеченных", "random")
    for key, (label, english, hint) in EFFECTS.items():
        tab.cb_entrance_effect.addItem(label, key)
        tab.cb_entrance_effect.setItemData(tab.cb_entrance_effect.count() - 1,
                                         f"{english}\n{hint}", _api.Qt.ItemDataRole.ToolTipRole)
    layout.addWidget(tab.cb_entrance_effect)
    tab.lbl_entrance_hint = tab._hint("")
    layout.addWidget(tab.lbl_entrance_hint)
    form = _api.QGridLayout()
    tab.sp_entrance_seconds = _api.QDoubleSpinBox()
    tab.sp_entrance_seconds.setRange(0.2, 5)
    tab.sp_entrance_seconds.setSingleStep(0.1)
    tab.sp_entrance_seconds.setDecimals(1)
    tab.sp_entrance_seconds.setValue(1.2)
    tab.sp_entrance_seconds.setSuffix(" с")
    tab.sp_entrance_strength = _api.QSpinBox()
    tab.sp_entrance_strength.setRange(10, 100)
    tab.sp_entrance_strength.setValue(70)
    tab.sp_entrance_strength.setSuffix(" %")
    tab.sp_entrance_strength.setToolTip("Размах движения, вращения и размытия.")
    tab.sp_entrance_fps = _api.QSpinBox()
    tab.sp_entrance_fps.setRange(10, 60)
    tab.sp_entrance_fps.setValue(30)
    tab.sp_entrance_preset = _api.QSpinBox()
    tab.sp_entrance_preset.setRange(0, 13)
    tab.sp_entrance_preset.setValue(_api.VIDEO_PRESET)
    tab.sp_entrance_preset.setToolTip("13 — быстрее, 0 — медленнее. Свой пресет появления.")
    for row, (label, field) in enumerate((
            ("Длительность", tab.sp_entrance_seconds),
            ("Сила", tab.sp_entrance_strength),
            ("Кадров/с", tab.sp_entrance_fps),
            ("Пресет кодирования", tab.sp_entrance_preset))):
        form.addWidget(tab._lab(label), row, 0)
        form.addWidget(field, row, 1)
    layout.addLayout(form)
    # Предпросмотр использует тот же рендер, который готовит видео для пака.
    from .entrance_preview import EntrancePreview
    tab.entrance_effect_checks = {}
    tab.entrance_preview = EntrancePreview(tab)
    layout.addWidget(tab.entrance_preview)
    button = _api.QPushButton("Повторить предпросмотр")
    button.clicked.connect(tab.entrance_preview.restart)
    layout.addWidget(button)
    return group


def _build_targets(tab):
    group = _api.QGroupBox("К каким составам применять")
    layout = _api.QVBoxLayout(group)
    tab.entrance_target_checks = {}
    for key, label in TARGET_LABELS.items():
        check = _api.QCheckBox(label)
        check.setChecked(key == "frame")
        tab.entrance_target_checks[key] = check
        layout.addWidget(check)
    layout.addWidget(tab._hint(
        "Отметьте любые составы. Их доли задаются на вкладке «Настройки». "
        "В вопросах по студии эффект применяется к каждому кадру."))
    return group


def _build_choices(tab):
    tab.box_entrance_effects = group = _api.QGroupBox("Эффекты для случайного выбора")
    grid = _api.QGridLayout(group)
    for i, (key, (label, english, hint)) in enumerate(EFFECTS.items()):
        check = _api.QCheckBox(label)
        check.setChecked(True)
        check.setToolTip(f"{english}\n{hint}")
        check.toggled.connect(lambda: _refresh(tab))
        tab.entrance_effect_checks[key] = check
        grid.addWidget(check, i, 0)
    buttons = _api.QHBoxLayout()
    for label, checked in (("Все", True), ("Снять все", False)):
        button = _api.QPushButton(label)
        button.clicked.connect(lambda _, value=checked: _select_all(tab, value))
        buttons.addWidget(button)
    grid.addLayout(buttons, len(EFFECTS), 0)
    return group


def _select_all(tab, value):
    for check in tab.entrance_effect_checks.values():
        check.setChecked(value)


def _refresh(tab):
    mode = tab.cb_entrance_effect.currentData()
    tab.box_entrance_effects.setEnabled(mode == "random")
    if mode == "random":
        selected = [k for k, c in tab.entrance_effect_checks.items() if c.isChecked()]
        text = ("На каждый вопрос — один эффект из отмеченных. "
                "В примере показан первый отмеченный." if selected else
                "Отметьте хотя бы один эффект появления.")
    else:
        _, english, hint = EFFECTS[mode]
        text = f"{english}\n{hint}"
    tab.lbl_entrance_hint.setText(text)
    tab.entrance_preview.restart()


def collect(tab, settings):
    settings.entrance_enabled = tab.chk_entrance.isChecked()
    settings.entrance_effect = tab.cb_entrance_effect.currentData()
    settings.entrance_effects = [k for k, c in tab.entrance_effect_checks.items() if c.isChecked()]
    settings.entrance_targets = [k for k, c in tab.entrance_target_checks.items() if c.isChecked()]
    for name in ("seconds", "strength", "fps", "preset"):
        setattr(settings, "entrance_" + name, getattr(tab, "sp_entrance_" + name).value())


def apply(tab, settings):
    tab.chk_entrance.setChecked(settings.entrance_enabled)
    index = tab.cb_entrance_effect.findData(settings.entrance_effect)
    tab.cb_entrance_effect.setCurrentIndex(max(0, index))
    for name in ("effects", "targets"):
        selected = getattr(settings, "entrance_" + name)
        checks = getattr(tab, "entrance_" + ("effect_checks" if name == "effects" else "target_checks"))
        for key, check in checks.items():
            check.setChecked(key in selected)
    for name in ("seconds", "strength", "fps", "preset"):
        getattr(tab, "sp_entrance_" + name).setValue(getattr(settings, "entrance_" + name))
    _refresh(tab)
