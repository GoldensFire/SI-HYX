# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_UpgradePage: _group_titles. Public namespace: animepack_upgrade_tab."""
from __future__ import annotations
import animepack_upgrade_tab as _api


# ── группа «Варианты названий» ────────────────────────────────────────
def _group_titles(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Дописать варианты названий")
    grp.setCheckable(True)
    grp.setChecked(True)
    grp.setToolTip(
        f"Если правильный ответ похож на название {self.what}, оно ищется "
        f"на {self.source_name}, и в ответ дописываются остальные его "
        f"названия — ровно как это делает «Генерация аниме-пака».\n"
        "Иероглифика не берётся вовсе: ведущему её не прочитать, игроку "
        "не набрать.")
    self.grp_titles = grp
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    r = 0
    self.chk_strict = _api.QCheckBox("Только точное совпадение названия")
    self.chk_strict.setChecked(True)
    self.chk_strict.setToolTip(
        "Варианты дописываются, только когда одно из названий тайтла "
        "совпало с ответом слово в слово (регистр и знаки не в счёт).\n"
        "Опечатка в букву-другую сюда всё равно входит — «Gokukoku no "
        "Brunhildr» это «Brynhildr», а не другой тайтл. Слов при этом "
        "должно быть поровну, а номера сезонов совпадать точно: «Sword Art "
        "Online II» и «III» отличаются одним символом, но это разное.\n"
        "Снимите — засчитается и просто близкое название, но тогда чужой "
        "ответ может утащить варианты постороннего тайтла (например, "
        "сиквела).")
    g.addWidget(self.chk_strict, r, 0, 1, 2)
    r += 1
    self.chk_other_answers = _api.QCheckBox("Искать по всем вариантам ответа")
    self.chk_other_answers.setChecked(True)
    self.chk_other_answers.setToolTip(
        "Тайтл ищется не только по первой строке ответа, но и по остальным "
        "— а первая ещё и без песни за тире («Эхо террора - Trigger» → "
        "«Эхо террора»).\n"
        "На живом паке без этого не опознавался каждый третий ответ: "
        "голое название там лежит второй строкой. Ищем до первого "
        "попадания, так что на опознанных ответах лишних запросов нет.")
    g.addWidget(self.chk_other_answers, r, 0, 1, 2)
    r += 1
    self.chk_fix_case = _api.QCheckBox("Исправлять написание названия")
    self.chk_fix_case.setChecked(True)
    self.chk_fix_case.setToolTip(
        f"Ответ переписывается так, как название написано на "
        f"{self.source_name}: в паке «наруто» — станет «Наруто».\n"
        "Меняется ТОЛЬКО регистр букв и только при точном совпадении: "
        "иначе это был бы уже другой ответ, а не другое написание.")
    g.addWidget(self.chk_fix_case, r, 0, 1, 2)
    r += 1
    self.chk_poster = _api.QCheckBox(f"Ставить постер {self.what} в ответ")
    self.chk_poster.setChecked(True)
    self.chk_poster.setToolTip(
        f"В ответ кладётся постер с {self.source_name} — так же, как это "
        "делает «Генерация аниме-пака» (AVIF, три секунды на экране).\n"
        "Только при точном совпадении названия и только если своей картинки "
        "в ответе ещё нет. Один тайтл — один файл на весь пак.")
    g.addWidget(self.chk_poster, r, 0, 1, 2)
    r += 1
    self.chk_book_themes = _api.QCheckBox("Манга и ранобэ — искать книгу")
    self.chk_book_themes.setChecked(True)
    self.chk_book_themes.setToolTip(
        "Если в названии темы написано «манга», «манхва» или «ранобэ» "
        "(и латиницей тоже — «Manga»), ответ ищется по книгам, а не по "
        "аниме: обложка аниме в таком вопросе неверна, а у части ответов "
        "аниме нет вовсе («Soul Cartel», «Noblesse» — манхва).\n"
        "Книга не нашлась — названия всё равно доищутся по аниме, но "
        "обложка из него уже не берётся.")
    self.chk_characters = _api.QCheckBox("Не путать персонажа с тайтлом")
    self.chk_characters.setChecked(True)
    self.chk_characters.setToolTip(
        "Если ответ похож на имя героя (латиница в одно-три слова — «Mumei», "
        "«Teto Kasane»), он проверяется по базе персонажей Shikimori. Имя "
        "совпало точно — вопрос не трогается вовсе: спрашивали персонажа, а "
        "не аниме.\n"
        "Лишний запрос уходит только на такие ответы, и о каждом пропущенном "
        "пишется в таблицу.")
    g.addWidget(self.chk_book_themes, r, 0, 1, 2)
    r += 1
    g.addWidget(self.chk_characters, r, 0, 1, 2)
    r += 1
    g.addWidget(self._hint(
        "Дописываются все названия сразу: ромадзи, английское, "
        "лицензионное, синонимы и русское."),
        r, 0, 1, 2)
    r += 1
    self.sp_max_variants = _api.QSpinBox(); self.sp_max_variants.setRange(1, 50)
    self.sp_max_variants.setValue(8)
    self.sp_max_variants.setToolTip(
        "Потолок дописанных строк на один ответ. У популярных тайтлов "
        "синонимов бывает под два десятка, и весь список в ответе читать "
        "невозможно.")
    g.addWidget(self._lab("Не больше вариантов"), r, 0)
    g.addWidget(self.sp_max_variants, r, 1)
    r += 1
    self.sp_min_len = _api.QSpinBox(); self.sp_min_len.setRange(1, 20)
    self.sp_min_len.setValue(3)
    self.sp_min_len.setToolTip(
        f"Ответы короче этого на {self.source_name} не ищутся вовсе: «Да», "
        f"«1945» и прочее к {self.what} отношения не имеют, а запрос на "
        f"каждый такой ответ — это лишние секунды.")
    g.addWidget(self._lab("Ответ длиннее, символов"), r, 0)
    g.addWidget(self.sp_min_len, r, 1)
    r += 1
    g.addWidget(self._hint(
        f"Один и тот же тайтл спрашивается ровно раз на пак. "
        f"{self.source_name} отвечает не быстрее пяти раз в секунду — на "
        f"паке из полусотни разных названий это примерно полминуты."),
        r, 0, 1, 2)
    g.setColumnStretch(1, 1)
    return grp

# ── группа «Повторяющийся текст» ──────────────────────────────────────
def _group_repeats(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Убрать повторяющийся текст")
    grp.setCheckable(True)
    grp.setChecked(True)
    grp.setToolTip(
        "Если один и тот же короткий текстовый блок стоит в КАЖДОМ вопросе "
        "темы («Назвать аниме»), он оттуда убирается: за ним всё равно идёт "
        "скрин или отрывок, и так понятно, что назвать надо аниме, а на "
        "экране это лишние секунды на каждом вопросе.\n"
        "Понимает оба формата: v5 (<item> в параметре вопроса) и v4 (<atom> "
        "сценария до маркера ответа). Вопрос без содержимого не остаётся "
        "никогда: если убирать пришлось бы всё, вопрос не трогается.")
    self.grp_repeats = grp
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    r = 0
    self.sp_repeat_len = _api._no_wheel(_api.QSpinBox())
    self.sp_repeat_len.setRange(1, 500)
    self.sp_repeat_len.setValue(_api.UpgradeSettings().repeat_text_max_len)
    self.sp_repeat_len.setSuffix(" симв.")
    self.sp_repeat_len.setToolTip(
        "Длиннее этого текст не убирается, даже если он стоит во всех "
        "вопросах темы: короткая подпись — это указание, а длинный текст "
        "скорее сам вопрос.")
    g.addWidget(self._lab("Подпись не длиннее"), r, 0)
    g.addWidget(self.sp_repeat_len, r, 1)
    r += 1
    self.chk_known_labels = _api.QCheckBox("Убирать известные подписи")
    self.chk_known_labels.setChecked(True)
    self.chk_known_labels.setToolTip(
        "Закрытый список знакомых подписей — «Назвать аниме», «Назвать "
        "персонажа», «Назвать фильм», «Назвать песню» и подобные — "
        "убирается и тогда, когда в одном вопросе темы такой подписи нет.\n"
        "Правило «в КАЖДОМ вопросе» на живых паках спотыкается: в теме "
        "«Hayami Saori» из «Anime by Hinoriku 6» «Назвать персонажа» стоит "
        "в семи вопросах из восьми, а восьмой спрашивает совсем другое — "
        "и подпись оставалась во всех семи.\n"
        "Вопрос без содержимого тут тоже не остаётся: если убрать пришлось "
        "бы всё, вопрос не трогается.")
    g.addWidget(self.chk_known_labels, r, 0, 1, 2)
    r += 1
    g.addWidget(self._hint(
        "Тема из одного вопроса не в счёт: «в каждом» там значит «в "
        "единственном». Убирается только текст — картинки, звук и ролики "
        "остаются на месте."), r, 0, 1, 2)
    g.setColumnStretch(1, 1)
    return grp

# ── группа «Текст под звук» ───────────────────────────────────────────
def _group_merge(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Текст под звук")
    grp.setCheckable(True)
    grp.setChecked(True)
    grp.setToolTip(
        "Если в вопросе идёт текстовый блок, а сразу за ним отрывок, текст "
        "включается ОДНОВРЕМЕННО со звуком — то самое «Объединить со "
        "следующим (играть одновременно)» из SIQuester.\n"
        "Без этого игра сначала держит текст на экране по таймеру и только "
        "потом включает музыку, хотя текст там как раз подпись к ней.\n"
        "Понимает оба формата: v5 (waitForFinish у <item>) и v4 (time=\"-1\" "
        "у <atom>). Ни новых блоков, ни параметров при этом не заводится — "
        "правится то, что в вопросе уже есть.")
    self.grp_merge = grp
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    g.addWidget(self._hint(
        "Там, где автор уже включил одновременное воспроизведение, ничего "
        "не меняется. Картинки и ролики не в счёт: правило только про "
        "текст перед звуком."), 0, 0, 1, 2)
    g.setColumnStretch(1, 1)
    return grp

# ── группа «Пустые вопросы» ───────────────────────────────────────────
def _group_empty(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Удалить пустые вопросы")
    grp.setCheckable(True)
    grp.setChecked(True)
    grp.setToolTip(
        "Вопросы, в которых нет ничего — ни текста, ни картинки, ни звука, "
        "ни ролика, — выкидываются из пака целиком.\n"
        "Ответ не в счёт: играть в такой вопрос всё равно нечем, на экране "
        "пустота, сколько бы вариантов ответа под ним ни лежало.\n"
        "Тема, оставшаяся совсем без вопросов, убирается следом за ними.")
    self.grp_empty = grp
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    g.addWidget(self._hint(
        "Каждый удалённый вопрос попадает в таблицу правок — видно, что "
        "именно ушло. Если пустыми выглядят ВСЕ вопросы пака, не трогается "
        "ни один: пустой пак игре не открыть."), 0, 0, 1, 2)
    g.setColumnStretch(1, 1)
    return grp

# ── группа «Картинки» ─────────────────────────────────────────────────
def _group_images(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Сжать тяжёлые картинки")
    grp.setCheckable(True)
    grp.setChecked(True)
    grp.setToolTip(
        "Картинки в паке тяжелее порога пережимаются в AVIF под лимит — тем "
        "же кодированием и с теми же быстрыми настройками, что в «Генерации "
        "аниме-пака» (libaom, tune=iq, подбор CQ, сторона не больше 1280).\n"
        "Ссылки в content.xml переводятся на новое имя файла, всё остальное "
        "медиа копируется как есть. GIF и уже готовый AVIF не трогаются.")
    self.grp_images = grp
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    r = 0
    self.sp_img_min = _api._no_wheel(_api.QDoubleSpinBox())
    self.sp_img_min.setRange(0.1, 100.0)
    self.sp_img_min.setSingleStep(0.5)
    self.sp_img_min.setDecimals(1)
    self.sp_img_min.setValue(1.0)
    self.sp_img_min.setSuffix(" МБ")
    self.sp_img_min.setToolTip(
        "Картинки легче этого не трогаются вовсе: они и так не тянут пак "
        "вниз, а каждое кодирование — это время.")
    g.addWidget(self._lab("Сжимать, если тяжелее"), r, 0)
    g.addWidget(self.sp_img_min, r, 1)
    r += 1
    self.sp_img_kb = _api._no_wheel(_api.QSpinBox())
    self.sp_img_kb.setRange(50, 20000)
    self.sp_img_kb.setSingleStep(50)
    self.sp_img_kb.setValue(500)
    self.sp_img_kb.setSuffix(" КБ")
    self.sp_img_kb.setToolTip(
        "До скольки килобайт ужимать. Кодер подбирает качество под этот "
        "размер, а если не влезает даже на минимальном — ужимает и "
        "разрешение.")
    g.addWidget(self._lab("Ужимать до"), r, 0)
    g.addWidget(self.sp_img_kb, r, 1)
    r += 1
    self.sp_img_speed = _api._no_wheel(_api.QSpinBox())
    self.sp_img_speed.setRange(0, 8)
    self.sp_img_speed.setValue(8)
    self.sp_img_speed.setToolTip(
        "Скорость кодирования AVIF (-cpu-used): 8 — быстро, 0 — медленно и "
        "чуть качественнее. Восьмёрка стоит и в генераторе паков.")
    g.addWidget(self._lab("Скорость (0–8)"), r, 0)
    g.addWidget(self.sp_img_speed, r, 1)
    r += 1
    g.addWidget(self._hint(
        "Кодирование идёт с низким приоритетом процесса — работать за "
        "компьютером оно не мешает. Картинка, которая после сжатия не стала "
        "легче, остаётся исходной."), r, 0, 1, 2)
    g.setColumnStretch(1, 1)
    return grp
