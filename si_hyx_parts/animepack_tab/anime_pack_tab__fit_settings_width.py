# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: _fit_settings_width. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def _table_shown(self) -> bool:
    """Встроенная таблица больше не показывается: она открывается окном."""
    box = getattr(self, "table_box", None)
    return box is not None and not box.isHidden()

def _toggle_table(self):
    """Открыть состав пакета отдельным окном, не сжимая настройки."""
    if self.table.rowCount() <= 0:
        return
    from .table_dialog import open_pack_table
    open_pack_table(self)

# Расстояние между колонками вкладки — то же, что задано body в _build_ui.
BODY_SPACING = 12


def _fit_pack_column(self) -> int:
    """Ширина неподвижной колонки «Пак» + кнопки; она же и возвращается.

    Колонка стоит на месте всегда, поэтому ширину ей даёт СВОЁ содержимое, а
    не остаток вкладки: иначе кнопка «Сгенерировать пак» ездила бы туда-сюда
    от каждого показа таблицы.

    Сверху — потолок: своим желанием группа «Пак» просит на четыре десятка
    пикселей больше, чем ей нужно (поле «Название» тянется), а отнимает их у
    настроек, и на экране 1600 точек это стоило им целой колонки."""
    pack = getattr(self, "right_col", None)
    if pack is None:
        return 0
    group = getattr(self, "pack_box", None)
    if group is not None:
        from .settings_box import needed_height
        # Стили добавляют полям padding и min-height уже после создания.
        # Обычный минимум QGroupBox этого не учитывает целиком и позволяет
        # низкому окну обрезать счётчики. Берём полную высоту после стилей.
        group.ensurePolished()
        group.setMinimumHeight(0)
        group.layout().invalidate()
        group.layout().activate()
        group.setMinimumHeight(needed_height(group))
    want = max(self.PACK_MIN_W,
               min(self.PACK_MAX_W, int(pack.sizeHint().width())))
    scroll = getattr(self, "scroll_pack", None)
    reserved = scroll.verticalScrollBar().sizeHint().width() if scroll else 0
    content_width = max(1, want - reserved)
    if pack.maximumWidth() != content_width:
        pack.setFixedWidth(content_width)
    # Содержимое не должно сжиматься по высоте: недостающее место отдаётся
    # прокрутке. Учитываем и действия с переносимой подписью под кнопками.
    from .settings_box import needed_height
    boxes = (self.templates_box, self.pack_box, self.actions_box)
    pack.setMinimumHeight(sum(needed_height(box) for box in boxes)
                          + 2 * pack.layout().spacing())
    if scroll is None:
        return want
    # Полоса помещается внутри прежней ширины правой панели: соседние
    # настройки не теряют целую колонку из-за нескольких новых пикселей.
    scroll.setFixedWidth(want)
    return want


def _fit_settings_width(self):
    """Keep a stable settings column; only resizing the window can shrink it."""
    scroll = getattr(self, "scroll_settings", None)
    panel = scroll.widget() if scroll is not None else None
    if panel is None:
        return
    pack = _fit_pack_column(self)
    margins = self.layout().contentsMargins()
    available = self.width() - margins.left() - margins.right()
    entrance_columns = getattr(self, "entrance_columns", None)
    if entrance_columns is not None:
        entrance_columns.apply_width(max(1, available - pack - BODY_SPACING - 40))
    if not self._table_shown():
        # Таблица спрятана — настройки забирают всю оставшуюся ширину вкладки
        # и сами раскладываются в несколько колонок (settings_columns).
        # Фиксированную ширину, выставленную в режиме с таблицей, здесь надо
        # снять: иначе панель так и осталась бы узкой полосой.
        panel.setMinimumWidth(0)
        scroll.setMinimumWidth(self.SETTINGS_MIN_W)
        scroll.setMaximumWidth(_api.QWIDGETSIZE_MAX)
        _fit_columns(self, scroll, available - pack - BODY_SPACING)
        return
    need = max(480, self.SETTINGS_MIN_W)
    # Панель не даём сжимать ниже её собственной ширины: тогда в совсем
    # узком окне появляется горизонтальная полоса и до правого края всё
    # равно можно доехать, вместо того чтобы поля молча резались.
    if panel.minimumWidth() != need:
        panel.setMinimumWidth(need)
    sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
    want = need + sb + 2 * scroll.frameWidth() + 4
    # Поля root-раскладки плюс две неподвижные соседки: таблица слева и
    # колонка «Пак» справа.
    avail = available - self.TABLE_MIN_W - pack - 2 * BODY_SPACING
    if avail > 0:
        want = min(want, max(self.SETTINGS_MIN_W, avail))
    if want != scroll.width() or scroll.maximumWidth() != want:
        scroll.setFixedWidth(want)
    _fit_columns(self, scroll, want)

def _fit_columns(self, scroll, outer: int):
    """Сколько колонок настроек помещается в отведённую панели ширину.

    Считаем по ширине, которую панель ТОЛЬКО ЧТО получила, а не по её
    нынешней геометрии: сама панель растёт вслед за числом колонок, и мерить
    по ней значило бы гнаться за собственным хвостом. По этой же причине не
    годится и viewport: сразу после «Показать таблицу» он ещё старый."""
    columns = getattr(self, "settings_columns", None)
    if columns is None:
        return
    sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
    # Поля самой панели (2 + 8) и рамка окна прокрутки.
    columns.apply_width(max(1, int(outer) - sb - 2 * scroll.frameWidth() - 14))

def resizeEvent(self, event):
    super(_api.AnimePackTab, self).resizeEvent(event)
    self._fit_settings_width()
    self._update_table_hint()

def showEvent(self, event):
    super(_api.AnimePackTab, self).showEvent(event)
    # Первый показ — единственный момент, когда размеры полей уже настоящие
    # (стили применены, шрифты подобраны).
    self._fit_settings_width()
    self._update_table_hint()

# ── группа «Пак» ──────────────────────────────────────────────────────
def _group_pack(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Пак")
    g = _api.QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
    self.ed_title = _api.QLineEdit("Сгенерировано в SI-HYX")
    self.ed_theme = _api.QLineEdit("SI-HYX")
    self.sp_rounds = _api.QSpinBox(); self.sp_rounds.setRange(1, 20); self.sp_rounds.setValue(3)
    self.sp_themes = _api.QSpinBox(); self.sp_themes.setRange(1, 20); self.sp_themes.setValue(5)
    self.sp_quest = _api.QSpinBox(); self.sp_quest.setRange(1, 20); self.sp_quest.setValue(6)
    for sp in (self.sp_rounds, self.sp_themes, self.sp_quest):
        sp.setMinimumWidth(44)
        sp.valueChanged.connect(self._recount)
    # Подписи текстовых полей стоят над ними. Три счётчика образуют одну
    # ровную строку: подписи сверху, одинаковые поля снизу. Все элементы
    # лежат прямо в сетке группы: вложенная сетка неверно отдавала Qt свою
    # высоту при масштабировании Windows, из-за чего счётчики обрезались, а
    # следующая подпись рисовалась поверх них.
    r = 0
    g.addWidget(self._lab("Название"), r, 0, 1, 3)
    r += 1
    g.addWidget(self.ed_title, r, 0, 1, 3)
    r += 1
    for column, (caption, field) in enumerate((
            ("Раунды", self.sp_rounds),
            ("Темы", self.sp_themes),
            ("Вопросов\nв теме", self.sp_quest))):
        label = self._lab(caption)
        # Явный перенос даёт строке постоянную высоту и убирает
        # heightForWidth, из-за которого Qt мог сжать соседние поля.
        label.setWordWrap(False)
        label.setSizePolicy(
            _api.QSizePolicy.Policy.Ignored,
            _api.QSizePolicy.Policy.Preferred)
        label.setAlignment(_api.Qt.AlignmentFlag.AlignHCenter
                           | _api.Qt.AlignmentFlag.AlignBottom)
        g.addWidget(label, r, column)
        field.setSizePolicy(
            _api.QSizePolicy.Policy.Expanding,
            _api.QSizePolicy.Policy.Fixed)
        g.addWidget(field, r + 1, column)
        g.setColumnStretch(column, 1)
    r += 2
    self.lbl_theme_title = self._lab("Название тем")
    g.addWidget(self.lbl_theme_title, r, 0, 1, 3)
    r += 1
    g.addWidget(self.ed_theme, r, 0, 1, 3)
    r += 1
    self.lbl_total = self._hint("")
    g.addWidget(self.lbl_total, r, 0, 1, 3)
    # Все подписи здесь короткие или имеют явный перенос. Даже одна
    # оставшаяся wordWrap-подпись включает heightForWidth у всей группы:
    # тогда при низком окне Qt снова сжимает счётчики ниже их полной высоты.
    for label in grp.findChildren(_api.QLabel):
        label.setWordWrap(False)
    return grp

# ── группа «Списки» ───────────────────────────────────────────────────
def _group_lists(self) -> _api.QGroupBox:
    grp = _api.QGroupBox("Списки")
    v = _api.QVBoxLayout(grp); v.setSpacing(6)
    self.chk_random = _api.QCheckBox("Случайные из базы AMQ")
    self.chk_random.setToolTip(
        "Аниме берутся из мастер-листа AnimeMusicQuiz. Он знает только те "
        "тайтлы, у которых есть песни в AMQ, поэтому годится лишь песенным "
        "пакам: без песен база всё равно берётся с Shikimori.")
    self.chk_random.toggled.connect(self._on_random_toggled)
    v.addWidget(self.chk_random)
    # База по умолчанию. С ней фильтры (год, тип, оценка) уходят прямо на
    # сервер Shikimori, поэтому кандидаты приезжают уже подходящие, а не
    # отсеиваются на нашей стороне, как с 16-мегабайтным листом AMQ.
    self.chk_random_shiki = _api.QCheckBox("Случайные из базы Shikimori")
    self.chk_random_shiki.setChecked(True)
    self.chk_random_shiki.setToolTip(
        "Аниме берутся случайной выборкой из каталога Shikimori "
        "(order: random), а не из базы AnimeMusicQuiz. Год, тип, оценка и "
        "исключённые жанры при этом фильтруются самим Shikimori — мусора "
        "приезжает меньше, а для паков из кадров и персонажей это вообще "
        "единственный источник, где база не ограничена песнями AMQ.")
    self.chk_random_shiki.toggled.connect(self._on_random_shiki_toggled)
    v.addWidget(self.chk_random_shiki)
    # Каталог Shikimori кэшируется на диск и живёт там, пока его не обновят
    # (просьба пользователя: «один раз собрал — и хранится»). Кнопка тут одна
    # на всю базу: прежние «Обновить базу Shikimori» и «Что в базе…» делали
    # одно дело с разных концов, и обновление шло вслепую одним куском.
    # Теперь она открывает панель, где видно, что в базе лежит, и где каждая
    # её часть обновляется отдельно (просьба пользователя).
    self.btn_refresh_db = _api.QPushButton("Обновить базу")
    self.btn_refresh_db.setIcon(_api.get_icon('fa5s.database'))
    self.btn_refresh_db.setToolTip(
        "Открывает панель базы Shikimori: сколько в ней карточек аниме и "
        "манги, сколько узнаваемых франшиз и что накопилось за генерации, а "
        "заодно таблицы тайтлов и персонажей с их индексом и сложностью.\n"
        "Обновляется база оттуда же и по частям: только аниме, только манга, "
        "только узнаваемость франшиз — или всё подряд, как раньше. Каталог "
        "берётся ЦЕЛИКОМ, сколько бы тайтлов под текущие фильтры (год, типы, "
        "оценка, исключённые жанры) в нём ни было, поэтому идти может долго — "
        "минуты и десятки минут; остановить можно там же, набранное "
        "останется.\n"
        "Сохранённое переживает перезапуск программы: следующая генерация не "
        "тратит на каталог ни одного запроса.")
    self.btn_refresh_db.clicked.connect(self._open_db_table)
    v.addWidget(self.btn_refresh_db)
    # Общая база + списки людей разом: тайтлы случайные, но чей-то ник в
    # ответе появляется, если тайтл нашёлся в его списке.
    self.chk_mark_owners = _api.QCheckBox("Отмечать, у кого из списков есть")
    self.chk_mark_owners.setToolTip(
        "Аниме берутся из общей базы, но КОГДА ВОПРОСЫ УЖЕ ОТОБРАНЫ, "
        "программа проверяет списки добавленных ниже людей: если выпавший "
        "тайтл есть у кого-то из них, его ник пишется в реплике ведущего в "
        "ответе.\n"
        "Отбор тайтлов от этого не меняется — списки только подписывают "
        "готовое.")
    self.chk_mark_owners.toggled.connect(self._on_mark_owners_toggled)
    v.addWidget(self.chk_mark_owners)
    v.addWidget(self._hint("Снимите обе галочки — и аниме возьмутся из "
                           "списков людей на MyAnimeList / Shikimori / "
                           "AniList."))

    self.box_users = _api.SettingsBox()
    uv = _api.QVBoxLayout(self.box_users)
    uv.setContentsMargins(0, 0, 0, 0); uv.setSpacing(6)
    # Строка «Аниме есть хотя бы у N чел.» живёт в своём контейнере: в
    # режиме «общая база + отметки» списки видны, а совпадение не при чём.
    self.box_similar = _api.SettingsBox()
    sim_row = _api.QHBoxLayout(self.box_similar); sim_row.setSpacing(6)
    sim_row.setContentsMargins(0, 0, 0, 0)
    # Отдельной галочки «Похожие» больше нет: сняты обе общие базы — значит
    # пак и так собирается по спискам, других вариантов не остаётся.
    lab_sim = self._lab("Аниме есть хотя бы у")
    self.sp_similar = _api.QSpinBox(); self.sp_similar.setRange(1, 20)
    self.sp_similar.setValue(2); self.sp_similar.setMinimumWidth(44)
    self.sp_similar.setToolTip(
        "«1» — годится всё, что есть хотя бы у одного человека; «2» и "
        "больше — только тайтлы, которые есть у стольких сразу.")
    sim_row.addWidget(lab_sim, 1)
    sim_row.addWidget(self.sp_similar)
    sim_row.addWidget(self._lab("чел."))
    uv.addWidget(self.box_similar)
    self.box_cards = _api.SettingsBox()
    self.cards_layout = _api.QVBoxLayout(self.box_cards)
    self.cards_layout.setContentsMargins(0, 0, 0, 0)
    self.cards_layout.setSpacing(6)
    uv.addWidget(self.box_cards)

    # Доли списков: сколько вопросов пака даёт каждый человек. Без них пак
    # заполнял тот, у кого список длиннее (просьба пользователя).
    self.box_shares = _api.SettingsBox()
    sh = _api.QVBoxLayout(self.box_shares)
    sh.setContentsMargins(0, 0, 0, 0); sh.setSpacing(2)
    self.chk_shares = _api.QCheckBox("Делить пак между списками")
    self.chk_shares.setToolTip(
        "Включено — каждый список даёт свою долю вопросов, как на полосе "
        "ниже. У кого 1500 тайтлов, а у кого 300 — неважно: доли считаются "
        "по проценту, а не по длине списка.\n"
        "Выключено — все списки просто складываются, и длинный список "
        "перевешивает остальные.")
    self.chk_shares.toggled.connect(self._on_shares_toggled)
    sh.addWidget(self.chk_shares)
    self.share_bar = _api._ShareBar()
    self.share_bar.setToolTip("Доля вопросов пака у каждого списка.")
    self.share_bar.changed.connect(self._on_share_bar_changed)
    sh.addWidget(self.share_bar)
    uv.addWidget(self.box_shares)
    self.box_shares.setVisible(False)

    btn_row = _api.QHBoxLayout(); btn_row.setSpacing(6)
    self.btn_add_user = _api.QPushButton("Добавить список")
    self.btn_add_user.setIcon(_api.get_icon('fa5s.plus'))
    self.btn_add_user.clicked.connect(lambda: self._add_user_card())
    self.btn_saved_users = _api.QPushButton("Из сохранённых")
    self.btn_saved_users.setIcon(_api.get_icon('fa5s.address-book'))
    self.btn_saved_users.setToolTip(
        "Ники, которые уже участвовали в генерации, запоминаются. Здесь их "
        "можно выбрать галочками и добавить сразу пачкой.")
    self.btn_saved_users.clicked.connect(self._open_saved_users)
    self.btn_clear_users = _api.QPushButton("Очистить")
    self.btn_clear_users.setIcon(_api.get_icon('fa5s.trash'))
    self.btn_clear_users.setToolTip(
        "Убрать все списки разом. Сами ники останутся в сохранённых.")
    self.btn_clear_users.clicked.connect(self._clear_user_cards)
    # Три кнопки в одну строку требовали 587 px: «Списки» переставали влезать
    # в колонку, и настройки схлопывались в одну колонку на всё окно.
    # Поэтому «Добавить список» — отдельной строкой, остальные две под ней.
    uv.addWidget(self.btn_add_user)
    btn_row.addWidget(self.btn_saved_users, 1)
    btn_row.addWidget(self.btn_clear_users, 1)
    uv.addLayout(btn_row)
    v.addWidget(self.box_users)
    self.box_users.setVisible(False)
    return grp

# ── доли списков ──────────────────────────────────────────────────────
def _on_shares_toggled(self, checked: bool):
    self.share_bar.setVisible(bool(checked))
    if not checked:
        for card in self._user_cards:
            card.set_share(0)
    else:
        self._refresh_share_bar()
        # Включили дележ — раздаём поровну, дальше двигайте руками.
        keys = self.share_bar.keys()
        if keys:
            self.share_bar.set_values({k: 1 for k in keys})
            self._on_share_bar_changed()
    self._fit_settings_width()

def _on_share_bar_changed(self):
    """Полосу подвинули — разложили проценты обратно по карточкам."""
    for card in self._user_cards:
        card.set_share(self.share_bar.value_of(self._card_key(card)))

@staticmethod
def _share_key(user) -> str:
    """Ключ списка на полосе долей: ник + источник + раздел (у одного
        человека могут быть и аниме-список, и манга-список)."""
    return f"{user.username.strip().casefold()}|{user.source}|{user.target}"

def _card_key(self, card) -> str:
    return self._share_key(card.value())

def _refresh_share_bar(self):
    """Пересобирает полосу под текущий набор карточек.

        Хозяин долей — сама полоса: она их и раздаёт карточкам. Обратно, из
        карточек, значения не читаем — иначе доля только что добавленного
        списка (ноль) тут же затирала бы честный дележ из set_parts."""
    bar = getattr(self, "share_bar", None)
    if bar is None:
        return
    parts, seen = [], set()
    for card in self._user_cards:
        key = self._card_key(card)
        if not card.value().username.strip() or key in seen:
            continue
        seen.add(key)
        parts.append((key, card.value().username.strip()))
    random_mode = (self.chk_random.isChecked()
                   or self.chk_random_shiki.isChecked())
    self.box_shares.setVisible(len(parts) > 1 and not random_mode)
    if not parts:
        return
    bar.set_parts(parts)
    self._on_share_bar_changed()
    self.share_bar.setVisible(self.chk_shares.isChecked())

# ── обновление базы (запускает панель «Обновить базу») ────────────────
def _refresh_db(self, parts=None):
    """Собрать заново части базы. parts=None — всю, как прежняя кнопка.

        Повторное нажатие работает на остановку: каталог берётся целиком, а это
        долго — бросить на середине можно в любой момент, набранное всё равно
        сохранится (просьба пользователя)."""
    if self._db_task is not None:
        self._db_task.stop()
        self.btn_refresh_db.setText("Останавливаю базу…")
        self.log("Останавливаю обновление базы — набранное сохранится.")
        return
    if self._task is not None:
        return
    self._db_parts = _api.db_refresh_parts(parts, self.collect())
    task = _api._RefreshDbTask(self.collect(), self._db_parts)
    task.signals.log.connect(self.log)
    task.signals.finished.connect(self._on_db_refreshed)
    task.signals.failed.connect(self._on_db_failed)
    self._db_task = task
    self.btn_refresh_db.setText("База обновляется…")
    self.log("Обновляю базу Shikimori "
             f"({', '.join(_api.DB_PART_NAMES.get(p, p) for p in self._db_parts)}). "
             "Остановить можно в панели базы — набранное сохранится.")
    self._pool.start(task)

def _db_panel(self):
    """Открытая панель базы или None."""
    dialog = getattr(self, "_db_table_dialog", None)
    try:
        return dialog if dialog is not None and dialog.isVisible() else None
    except RuntimeError:                 # окно уже удалено
        return None

def _on_db_refreshed(self, count: int):
    self._finish_db_ui()
    panel = _db_panel(self)
    if panel is not None:
        # Панель открыта и сама показывает свежие числа — окно поверх неё
        # только уводило фокус на главное окно, и панель пряталась за ним
        # (просьба пользователя). Хватит строки в журнале.
        self.log(f"База Shikimori обновлена: в кэше {count} карточек.")
        panel.raise_()
        panel.activateWindow()
        return
    _api.msgbox_information(self, "База обновлена",
                       f"В кэше {count} карточек Shikimori. Следующие паки "
                       "соберутся быстрее: за каталогом ходить больше не "
                       "придётся.")

def _on_db_failed(self, err: str):
    self._finish_db_ui()
    self.log(f"База Shikimori не обновилась: {err}")
    # Ошибку показываем поверх панели, если она открыта: иначе окно
    # сообщения поднимало главное окно, и панель оказывалась за ним.
    panel = _db_panel(self)
    _api.msgbox_critical(panel or self, "База не обновилась", err)
    if panel is not None:
        panel.raise_()
        panel.activateWindow()

def _finish_db_ui(self):
    self._db_task = None
    if getattr(self, "_queue", None):
        _api.QTimer.singleShot(0, self._start_next)
    self._db_parts = ()
    self.btn_refresh_db.setEnabled(True)
    self.btn_refresh_db.setIcon(_api.get_icon('fa5s.database'))
    self.btn_refresh_db.setText("Обновить базу")
    # Панель открыта — показать в ней свежие числа и вернуть кнопкам блоков
    # их обычные подписи.
    dialog = getattr(self, "_db_table_dialog", None)
    if dialog is not None:
        try:
            dialog.refresh()
        except Exception:  # noqa: BLE001 — панель могли уже закрыть
            pass
