# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Controls for downloaded art questions (Pixiv and Gelbooru)."""
from __future__ import annotations

import animepack_tab as _api
from pixiv_art_api import MODE_LABELS, MODES, mode_of
from si_hyx_parts.animepack_tab.pixiv_tag_dialog import edit_tags, refresh_button


def _mode_box(tab, tip):
    box = _api.QComboBox()
    for mode in MODES:
        box.addItem(MODE_LABELS[mode], mode)
    box.setToolTip(tip)
    return box


# Откуда брать арты. Отбор у всех общий — меняется только источник.
SOURCES = (("pixiv", "Pixiv"), ("gelbooru", "Gelbooru"),
           ("both", "Pixiv и Gelbooru"))


def _key_row(tab, name, title, label, tip):
    """Строка «подпись — кнопка ключа» в своём контейнере: его прячет выбор
    источника, а саму кнопку — наличие ключа (_refresh_api_key_buttons)."""
    box = _api.QWidget(tab)
    grid = _api.QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    button = tab._api_key_button(name, title)
    button.setToolTip(tip)
    grid.addWidget(tab._lab(label), 0, 0)
    grid.addWidget(button, 0, 1)
    grid.setColumnStretch(1, 1)
    return box, button


def build_controls(tab):
    tab.chk_pixiv_art = _api.QCheckBox("Арты Pixiv / Gelbooru")
    tab.chk_pixiv_art.setToolTip(
        "Ищет по названию аниме арты на Pixiv или Gelbooru и добавляет их как "
        "вопросы. R-18 и ИИ-работы можно разрешить или, наоборот, брать только "
        "их; шок-контент пропускается всегда. Картинка сжимается как обычный кадр.")
    tab.box_pixiv_art = _api.SettingsBox()
    layout = _api.QGridLayout(tab.box_pixiv_art)
    layout.setContentsMargins(16, 0, 0, 0)
    layout.setHorizontalSpacing(8)
    tab.cb_pixiv_source = _api.QComboBox()
    for key, label in SOURCES:
        tab.cb_pixiv_source.addItem(label, key)
    tab.cb_pixiv_source.setToolTip(
        "Откуда брать арты. Все настройки ниже (R-18, ИИ, лайки, однополые "
        "пары, исключаемые теги, проверка Gemini) действуют на оба источника.\n"
        "Gelbooru: «лайк» — это score поста, R-18 — рейтинг questionable и "
        "explicit, ИИ — метка ai-generated. Тайтл ищется по метке-копирайту "
        "(ромадзи-название: kimetsu_no_yaiba).\n"
        "«Pixiv и Gelbooru» — источник выбирается случайно для каждого арта, "
        "а если там арта нет, пробуется второй; хватит и одного ключа.")
    layout.addWidget(tab._lab("Источник"), 0, 0)
    layout.addWidget(tab.cb_pixiv_source, 0, 1)
    tab.row_pixiv_key, tab.btn_pixiv_key = _key_row(
        tab, "pixiv", "Refresh token Pixiv", "Pixiv API",
        "Откройте Настройки → Ключи API и добавьте refresh token Pixiv.")
    layout.addWidget(tab.row_pixiv_key, 1, 0, 1, 2)
    tab.row_gelbooru_key, tab.btn_gelbooru_key = _key_row(
        tab, "gelbooru", "Ключ API Gelbooru", "Gelbooru API",
        "Откройте Настройки → Ключи API и вставьте строку «&api_key=…&user_id=…» "
        "со страницы gelbooru.com → My Account → Options.")
    layout.addWidget(tab.row_gelbooru_key, 2, 0, 1, 2)
    tab.cb_pixiv_source.currentIndexChanged.connect(lambda _i: _show_source(tab))
    tab.cb_pixiv_r18 = _mode_box(tab, (
        "Что делать со взрослыми работами (R-18).\n"
        "«Только их» соберёт пак ровно из таких артов — арт без метки R-18 "
        "в него не попадёт вовсе.\n"
        "R-18G (гуро, расчленение и подобное) не берётся ни в каком режиме."))
    tab.cb_pixiv_ai = _mode_box(tab, (
        "Что делать с работами, нарисованными нейросетью.\n"
        "«Только их» оставит в паке ровно такие арты: Pixiv помечает их сам, "
        "и отбор идёт по этой метке.\n"
        "Чем уже режим, тем чаще подходящего арта у тайтла не находится — "
        "тогда вопрос достаётся следующему тайтлу."))
    layout.addWidget(tab._lab("R-18"), 3, 0)
    layout.addWidget(tab.cb_pixiv_r18, 3, 1)
    layout.addWidget(tab._lab("ИИ-арты"), 4, 0)
    layout.addWidget(tab.cb_pixiv_ai, 4, 1)
    # Планка лайков (закладок Pixiv): по ней и отбирается пул, из которого
    # тянется случайная работа (просьба пользователя).
    tab.sp_pixiv_likes = _api.QSpinBox()
    tab.sp_pixiv_likes.setRange(0, 100000)
    tab.sp_pixiv_likes.setSingleStep(5)
    tab.sp_pixiv_likes.setValue(_api.PIXIV_MIN_LIKES)
    tab.sp_pixiv_likes.setSpecialValueText("без планки")
    tab.sp_pixiv_likes.setMinimumWidth(84)
    tab.sp_pixiv_likes.setToolTip(
        "Сколько лайков должно быть у арта, чтобы он попал в пул случайного "
        "выбора. «Лайк» на Pixiv — это закладка: другого счётчика одобрения "
        f"открытый API не отдаёт. По умолчанию {_api.PIXIV_MIN_LIKES}.\n"
        "Планка строгая: если ей не отвечает ни одна работа ни по одному "
        "из названий тайтла, вопрос достанется другому тайтлу.\n"
        "Ноль («без планки») снимает отбор по лайкам совсем.\n"
        "У Gelbooru «лайк» — это score поста, и планка там не выше 5: "
        "score у Gelbooru гораздо скромнее закладок Pixiv.")
    layout.addWidget(tab._lab("Лайков не меньше"), 5, 0)
    layout.addWidget(tab.sp_pixiv_likes, 5, 1)
    tab.chk_pixiv_same_sex = _api.QCheckBox("Пускать работы про однополые пары")
    tab.chk_pixiv_same_sex.setToolTip(
        "BL/яой, GL/юри и подобные метки. По умолчанию такие арты в пак не "
        "идут вовсе (просьба пользователя) — снятая галочка их и отсекает.")
    layout.addWidget(tab.chk_pixiv_same_sex, 6, 0, 1, 2)
    tab.chk_pixiv_gemini = _api.QCheckBox("Проверять арт через Gemini")
    tab.chk_pixiv_gemini.setChecked(True)
    tab.chk_pixiv_gemini.setToolTip(
        "Gemini отсеивает крайне плохо нарисованные арты и персонажей "
        "из других тайтлов. Аккуратная простая рисовка и стилизация допустимы. "
        "Если способ проверки "
        "названия — Gemini, он проверяет и видимые названия. "
        "До четырёх картинок с одинаковой моделью проверяются одним запросом.")
    layout.addWidget(tab.chk_pixiv_gemini, 7, 0, 1, 2)
    tab.cb_pixiv_title_mode = _api.QComboBox()
    tab.cb_pixiv_title_mode.addItem("Название: Gemini", "gemini")
    tab.cb_pixiv_title_mode.addItem("Название: локальный OCR", "local")
    tab.cb_pixiv_title_mode.setToolTip(
        "В локальном режиме OCR проверяет видимое название. Gemini "
        "по-прежнему проверяет качество рисунка и персонажей других тайтлов, "
        "если галочка включена.")
    layout.addWidget(tab.cb_pixiv_title_mode, 8, 0, 1, 2)
    tab.cb_pixiv_gemini_model = _api.QComboBox()
    for model in _api.GEMINI_MODELS:
        tab.cb_pixiv_gemini_model.addItem(model, model)
    tab.cb_pixiv_gemini_model.setCurrentText(_api.GEMINI_DEFAULT_MODEL)
    tab.cb_pixiv_gemini_model.setToolTip(
        "Модель Gemini, которая визуально проверяет арты Pixiv и Gelbooru.")
    # Галочки «Пускать комиксы Pixiv» больше нет (просьба пользователя):
    # записи типа «манга» — это кадры с репликами, а не рисунок, и вопросом
    # такая работа не бывает. Поле pixiv_allow_manga осталось только ради
    # прежних settings.json и программного вызова клиента.
    # Списки меток пользователь правит сам (просьба пользователя): целую
    # группу можно выключить, отдельную метку снять, свою — дописать.
    tab._pixiv_groups_off: list = []
    tab._pixiv_tags_off: list = []
    tab._pixiv_tags_extra: list = []
    tab.btn_pixiv_tags = _api.QPushButton("Исключаемые теги…")
    tab.btn_pixiv_tags.setToolTip(
        "Какие метки Pixiv не пускать в пак: гуро, трёхмерка, наброски, "
        "солянки и прочее.\nГруппу можно выключить целиком, метку — снять по "
        "одной, а свои метки дописать. Они уходят минусом в сам запрос.")
    tab.btn_pixiv_tags.clicked.connect(lambda: edit_tags(tab))
    layout.addWidget(tab.btn_pixiv_tags, 10, 0, 1, 2)
    layout.setColumnStretch(1, 1)
    tab.box_pixiv_art.setVisible(False)
    tab.chk_pixiv_art.toggled.connect(lambda value: toggle(tab, value))
    _show_source(tab)


def _show_source(tab):
    """Строки ключей — только у выбранных источников."""
    source = tab.cb_pixiv_source.currentData() or "pixiv"
    tab.row_pixiv_key.setVisible(source in ("pixiv", "both"))
    tab.row_gelbooru_key.setVisible(source in ("gelbooru", "both"))


def toggle(tab, checked):
    tab.box_pixiv_art.setVisible(checked)
    tab.mix.set_pixiv_art(checked)
    tab._refresh_song_opts()


def _apply_mode(box, mode, exclude):
    """Ставит режим из настроек; у старых настроек есть только галочка."""
    index = box.findData(mode_of(mode, bool(exclude)))
    box.setCurrentIndex(index if index >= 0 else 0)


def apply_controls(tab, settings):
    tab._migrate_api_key("pixiv", settings.pixiv_refresh_token)
    source = str(getattr(settings, "pixiv_art_source", "pixiv") or "pixiv")
    tab.cb_pixiv_source.setCurrentIndex(
        max(0, tab.cb_pixiv_source.findData(source)))
    _show_source(tab)
    tab.chk_pixiv_same_sex.setChecked(
        bool(getattr(settings, "pixiv_allow_same_sex", False)))
    tab.chk_pixiv_gemini.setChecked(
        bool(getattr(settings, "pixiv_gemini_check", True)))
    mode = str(getattr(settings, "pixiv_title_check_mode", "gemini") or "gemini")
    tab.cb_pixiv_title_mode.setCurrentIndex(max(0, tab.cb_pixiv_title_mode.findData(mode)))
    model = (str(getattr(settings, "pixiv_gemini_model", "") or "")
             or str(getattr(settings, "gemini_model", "") or "")
             or _api.GEMINI_DEFAULT_MODEL)
    if tab.cb_pixiv_gemini_model.findText(model) < 0:
        tab.cb_pixiv_gemini_model.addItem(model, model)
    tab.cb_pixiv_gemini_model.setCurrentText(model)
    likes = getattr(settings, "pixiv_min_likes", None)
    tab.sp_pixiv_likes.setValue(
        _api.PIXIV_MIN_LIKES if likes is None else max(0, int(likes)))
    tab._pixiv_groups_off = list(getattr(settings, "pixiv_groups_off", None) or [])
    tab._pixiv_tags_off = list(getattr(settings, "pixiv_tags_off", None) or [])
    tab._pixiv_tags_extra = list(getattr(settings, "pixiv_tags_extra", None) or [])
    refresh_button(tab)
    _apply_mode(tab.cb_pixiv_r18, getattr(settings, "pixiv_r18_mode", ""),
                settings.pixiv_exclude_r18)
    _apply_mode(tab.cb_pixiv_ai, getattr(settings, "pixiv_ai_mode", ""),
                settings.pixiv_exclude_ai)
