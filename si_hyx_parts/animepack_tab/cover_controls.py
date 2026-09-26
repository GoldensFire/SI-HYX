# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Панель каверов внутри настроек песен. Namespace: animepack_tab.

У песни есть настоящая статистика AMQ (songDifficulty), а у исполнения —
измеренная программой схожесть с оригиналом. Это разные величины: называть
схожесть «сложностью AMQ» нельзя, иначе число в журнале выглядит так, будто
песня прошла мимо заданной пользователем рамки AMQ.
"""
from __future__ import annotations

import animepack_tab as _api
from cover_meta_rules import TYPE_LABELS

from . import cover_kinds_dialog, cover_lang_controls

COVER_TIP = ("Вместо отрезка с оригиналом играет ЧУЖОЕ исполнение той же "
             "песни, найденное на YouTube.\n"
             "Исполнение подтверждается звуком: программа сравнивает его с "
             "оригиналом и берёт только те записи, где это доказанно та же "
             "композиция.\n"
             "Если подтверждённого кавера у песни нет, вопрос соберётся "
             "обычным способом — пак от этого не остановится.")
LEVEL_TIP = ("Насколько исполнение близко к оригиналу по результату сравнения "
             "звука. Это не статистика сайта AMQ и не сложность песни.\n"
             "0% — совсем далеко, 100% — почти неотличимо от оригинала. "
             "Вокальные каверы обычно около 53, фортепианные — около 34.\n"
             "Чем ниже схожесть, тем труднее узнать исполнение и тем выше "
             "цена вопроса.")
POOL_TIP = ("Сколько подтверждённых исполнений набирать на песню, прежде чем "
            "выбирать одно.\n"
            "Больше — разнообразнее от пака к паку, но каждое лишнее "
            "исполнение это отдельная загрузка (около двух с половиной секунд)."
            "\nУже проверенные запоминаются: следующим пакам они достаются "
            "даром.")
VIEWS_TIP = ("Планка просмотров у ролика: ниже неё почти всегда лежит запись "
             "с телефона, спетая мимо нот (просьба пользователя). Ролики, у "
             "которых поиск YouTube просмотров не назвал, планка не трогает.")
LIKES_TIP = ("То же самое по лайкам. Их поиск YouTube отдаёт далеко не для "
             "каждого ролика, поэтому планка работает только там, где число "
             "известно, — считайте её добавкой к порогу просмотров, а не "
             "заменой.")
TYPES_TIP = ("Какие виды исполнения пускать. Ничего не отмечено — любые.\n"
             "Вид определяется по заголовку ролика и на проверку звуком не "
             "влияет.\n"
             "Концертных записей, караоке и игры под оригинал (drum cover, "
             "bass cover, play-along) среди видов нет вовсе: такие записи не "
             "берутся ни при каких настройках — в них слышен оригинал.")
SIMILARITY_TIP = ("Отбирать подтверждённые исполнения по проценту схожести с "
                  "оригиналом.\nПроверка «это вообще та же песня» выполняется "
                  "всегда и от этой галочки не зависит. Если выключить фильтр, "
                  "пройдут любые подтверждённые каверы вне зависимости от "
                  "процента.")


def build_controls(tab):
    """Коробка настроек каверов (ставится под настройками Chiptune)."""
    tab.chk_cover = _api.QCheckBox("Каверы — чужое исполнение той же песни")
    tab.chk_cover.setToolTip(COVER_TIP)
    box = _api.SettingsBox()
    grid = _api.QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    grid.addWidget(tab.chk_cover, 0, 0, 1, 4)

    tab.box_cover = _api.SettingsBox()
    inner = _api.QGridLayout(tab.box_cover)
    inner.setContentsMargins(16, 0, 0, 0)
    inner.setHorizontalSpacing(8)
    inner.setVerticalSpacing(6)
    tab.sp_cover_percent = _api.QSpinBox()
    tab.sp_cover_percent.setRange(1, 100)
    tab.sp_cover_percent.setSuffix(" % аудиовопросов")
    tab.sp_cover_percent.setValue(25)
    inner.addWidget(tab._lab("Доля каверов"), 0, 0)
    inner.addWidget(tab.sp_cover_percent, 0, 1, 1, 3)

    tab.chk_cover_similarity = _api.QCheckBox(
        "Фильтровать по проценту схожести")
    tab.chk_cover_similarity.setToolTip(SIMILARITY_TIP)
    inner.addWidget(tab.chk_cover_similarity, 1, 0, 1, 4)

    from .difficulty_range import DifficultyRange
    # Имена cover_amq_* оставлены для совместимости настроек и сторонних
    # обращений; галочка включает только эту рамку, а не проверку композиции.
    tab.cover_similarity_range = DifficultyRange(0, 100, suffix=" %")
    tab.sp_cover_amq_from = tab.cover_similarity_range.low_control
    tab.sp_cover_amq_to = tab.cover_similarity_range.high_control
    tab.cover_similarity_range.setMinimumWidth(240)
    tab.cover_similarity_range.setToolTip(LEVEL_TIP)
    tab.lbl_cover_similarity = tab._lab("Допустимая схожесть")
    inner.addWidget(tab.lbl_cover_similarity, 2, 0)
    # Рамка — в ОДНОЙ колонке, растягивается за счёт setColumnStretch ниже.
    # Растянутая на колонки 1..3, она вместе с длинной галочкой над ней
    # заставляла QGridLayout сложить их минимумы (495 px вместо 408), и
    # «Состав пака» выталкивал раскладку в одну колонку на всё окно.
    inner.addWidget(tab.cover_similarity_range, 2, 1)
    inner.setColumnStretch(1, 1)

    tab.sp_cover_pool = _api.QSpinBox()
    tab.sp_cover_pool.setRange(1, 12)
    tab.sp_cover_pool.setValue(3)
    tab.sp_cover_pool.setToolTip(POOL_TIP)
    inner.addWidget(tab._lab("Набирать исполнений"), 3, 0)
    inner.addWidget(tab.sp_cover_pool, 3, 1)

    tab.sp_cover_views = _api.QSpinBox()
    tab.sp_cover_views.setRange(0, 1000000)
    tab.sp_cover_views.setSingleStep(100)
    tab.sp_cover_views.setValue(1000)
    tab.sp_cover_views.setSpecialValueText("не следить")
    tab.sp_cover_views.setToolTip(VIEWS_TIP)
    tab.sp_cover_likes = _api.QSpinBox()
    tab.sp_cover_likes.setRange(0, 100000)
    tab.sp_cover_likes.setSingleStep(10)
    tab.sp_cover_likes.setValue(20)
    tab.sp_cover_likes.setSpecialValueText("не следить")
    tab.sp_cover_likes.setToolTip(LIKES_TIP)
    inner.addWidget(tab._lab("Просмотров не меньше"), 4, 0)
    inner.addWidget(tab.sp_cover_views, 4, 1)
    inner.addWidget(tab._lab("Лайков не меньше"), 5, 0)
    inner.addWidget(tab.sp_cover_likes, 5, 1)

    # Восемь галочек видов и ещё пятнадцать галочек языков занимали десяток
    # строк подряд — включённые каверы съедали две трети колонки настроек
    # (просьба пользователя). Сами галочки остались те же, но живут теперь в
    # своём окне, а на панели от них строчка-итог и кнопка.
    tab.cover_type_checks = {}
    for key, label in TYPE_LABELS.items():
        check = _api.QCheckBox(label)
        check.setToolTip(TYPES_TIP)
        tab.cover_type_checks[key] = check
    # Язык — отдельно от вида: перепеть на испанском могут и вокально, и
    # группой (просьба пользователя). Свой модуль, чтобы здесь не разрасталось.
    cover_lang_controls.build(tab)

    tab.btn_cover_kinds = _api.QPushButton("Виды и языки исполнения…")
    tab.btn_cover_kinds.setToolTip(TYPES_TIP)
    tab.btn_cover_kinds.clicked.connect(lambda: open_kinds(tab))
    inner.addWidget(tab.btn_cover_kinds, 6, 0, 1, 4)
    tab.lbl_cover_kinds = tab._hint("")
    tab.lbl_cover_kinds.setWordWrap(True)
    inner.addWidget(tab.lbl_cover_kinds, 7, 0, 1, 4)

    listen = _api.QPushButton("Проверить каверы…")
    listen.setToolTip("Найти и прослушать каверы одной песни, не собирая пак.")
    listen.clicked.connect(lambda: open_preview(tab))
    inner.addWidget(listen, 8, 0, 1, 4)
    grid.addWidget(tab.box_cover, 1, 0, 1, 4)
    tab.chk_cover.toggled.connect(lambda _=None: refresh(tab))
    tab.chk_cover_similarity.toggled.connect(
        lambda _=None: refresh_similarity(tab))
    cover_kinds_dialog.refresh_summary(tab)
    refresh(tab)
    return box


def open_kinds(tab):
    """Окно «Виды и языки исполнения»."""
    cover_kinds_dialog.open_dialog(tab)


def refresh(tab):
    """Настройки каверов видны, только пока каверы включены."""
    box = getattr(tab, "box_cover", None)
    if box is not None:
        box.setVisible(bool(tab.chk_cover.isChecked()))
    refresh_similarity(tab)
    if getattr(tab, "settings_columns", None) is not None:
        tab._fit_settings_width()


def refresh_similarity(tab):
    """Диапазон доступен только когда включён процентный фильтр."""
    enabled = bool(tab.chk_cover_similarity.isChecked())
    tab.lbl_cover_similarity.setEnabled(enabled)
    tab.cover_similarity_range.setEnabled(enabled)


def collect_controls(tab, settings):
    settings.cover_enabled = tab.chk_cover.isChecked()
    settings.cover_percent = tab.sp_cover_percent.value()
    settings.cover_pool = tab.sp_cover_pool.value()
    settings.cover_similarity_enabled = tab.chk_cover_similarity.isChecked()
    settings.cover_amq_from = tab.sp_cover_amq_from.value()
    settings.cover_amq_to = max(tab.sp_cover_amq_from.value(),
                                tab.sp_cover_amq_to.value())
    settings.cover_min_views = tab.sp_cover_views.value()
    settings.cover_min_likes = tab.sp_cover_likes.value()
    settings.cover_types = [key for key, check in tab.cover_type_checks.items()
                            if check.isChecked()]
    cover_lang_controls.collect(tab, settings)


def apply_controls(tab, settings):
    tab.chk_cover.setChecked(settings.cover_enabled)
    tab.sp_cover_percent.setValue(max(1, min(100, int(settings.cover_percent))))
    tab.sp_cover_pool.setValue(max(1, min(12, int(settings.cover_pool))))
    tab.chk_cover_similarity.setChecked(bool(getattr(
        settings, "cover_similarity_enabled", True)))
    tab.cover_similarity_range.set_range(
        max(0, min(100, int(settings.cover_amq_from))),
        max(0, min(100, int(settings.cover_amq_to))))
    tab.sp_cover_views.setValue(max(0, min(1000000, int(
        getattr(settings, "cover_min_views", 0) or 0))))
    tab.sp_cover_likes.setValue(max(0, min(100000, int(
        getattr(settings, "cover_min_likes", 0) or 0))))
    wanted = {str(key) for key in (settings.cover_types or ())}
    for key, check in tab.cover_type_checks.items():
        check.setChecked(key in wanted)
    cover_lang_controls.apply(tab, settings)
    cover_kinds_dialog.refresh_summary(tab)
    refresh(tab)


def open_preview(tab):
    from .cover_preview import CoverPreview
    CoverPreview(tab.collect(), tab).exec()
