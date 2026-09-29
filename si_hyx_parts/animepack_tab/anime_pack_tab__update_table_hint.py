# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: _update_table_hint. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def _update_table_hint(self):
    """Показывает предупреждение НАКЛАДКОЙ на таблицу, пока пак ещё не
        собран (строк нет), и прячет её, как только строки появились. Саму
        таблицу видимость не трогает — только накладку поверх неё."""
    hint = getattr(self, "lbl_table_hint", None)
    if hint is None:
        return
    hint.setGeometry(self.table.rect())
    hint.setVisible(self.table.rowCount() == 0)

def _on_sort_changed(self, section: int, order):
    """Своя стрелка сортировки — в подписи колонки (родную мы выключили,
        чтобы она не резервировала место во всех секциях сразу)."""
    arrow = "↑" if order == _api.Qt.SortOrder.AscendingOrder else "↓"
    for col, name in enumerate(self.TABLE_HEADERS):
        item = self.table.horizontalHeaderItem(col)
        if item is not None:
            item.setText(f"{name} {arrow}" if col == section else name)

def _lab(self, text):
    l = _api.QLabel(text)
    l.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
    l.setWordWrap(True)
    return l

def _hint(self, text):
    l = _api.QLabel(text)
    l.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
    l.setWordWrap(True)
    return l

# ── Ключи внешних API (единое место — Настройки программы) ────────────
def _api_key(self, name: str) -> str:
    fn = getattr(getattr(self, "main", None), "get_api_key", None)
    if fn is None:
        return ""
    try:
        return str(fn(name) or "").strip()
    except Exception:
        return ""

def _migrate_api_key(self, name: str, old_value):
    """Ключ, сохранённый ещё в настройках самой вкладки, один раз
        переезжает в общие настройки программы (Настройки → «Ключи API»)."""
    val = str(old_value or "").strip()
    setter = getattr(getattr(self, "main", None), "set_api_key", None)
    if val and setter is not None and not self._api_key(name):
        try:
            setter(name, val)
        except Exception:
            pass
    self._refresh_api_key_buttons()

def _open_api_settings(self):
    fn = getattr(getattr(self, "main", None), "_open_settings_dialog", None)
    if fn is not None:
        try:
            fn("Ключи API")
        except Exception:
            pass
    self._refresh_api_key_buttons()

def _api_key_button(self, name: str, title: str) -> _api.QPushButton:
    """Вместо поля ввода — кнопка «задан / не задан», открывающая Настройки:
        один и тот же ключ нужен нескольким вкладкам, и место у него одно."""
    btn = _api.QPushButton()
    btn.setToolTip(f"{title} — открыть Настройки программы, раздел «Ключи API»")
    btn.clicked.connect(self._open_api_settings)
    if not hasattr(self, "_api_key_buttons"):
        self._api_key_buttons = []
    self._api_key_buttons.append((btn, name, title))
    self._refresh_api_key_buttons()
    return btn

def _refresh_api_key_buttons(self):
    for btn, name, title in getattr(self, "_api_key_buttons", []):
        has = bool(self._api_key(name))
        btn.setText("задан" if has else "не задан — ввести")

def _build_settings_panel(self, body):
    # Правая колонка прокручивается отдельно: при низком окне шаблон,
    # параметры пака и кнопки сохраняют полную высоту и доступны через скролл.
    self.scroll_settings = scroll = _api.QScrollArea()
    scroll.setWidgetResizable(True)
    # Горизонтальная полоса — на самый крайний случай (окно уже, чем панель
    # вообще может сжаться). Раньше она была выключена наглухо, и правый
    # край настроек просто срезало.
    scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    panel = _api.QWidget()
    pv = _api.QVBoxLayout(panel)
    pv.setContentsMargins(2, 2, 8, 2)
    pv.setSpacing(12)

    # Группы настроек раскладываются по колонкам под ширину панели: пока
    # таблица спрятана, вкладка отдаёт настройкам всю ширину, и одна узкая
    # колонка на несколько экранов прокрутки больше не нужна (просьба
    # пользователя). Список групп и их порядок прежние.
    # «Пак» из колонок ушёл: он теперь стоит справа, рядом с кнопками.
    from si_hyx_parts.animepack_tab.settings_columns import SettingsColumns
    groups = [self._group_songs(), self._group_lists(),
              self._group_anime(), self._group_other()]
    self.settings_columns = SettingsColumns(groups, self.SETTINGS_MIN_W)
    pv.addWidget(self.settings_columns)

    self.btn_reset = _api.QPushButton("Сбросить настройки")
    self.btn_reset.setIcon(_api.get_icon('fa5s.undo'))
    self.btn_reset.clicked.connect(self.reset_settings)
    pv.addWidget(self.btn_reset)
    pv.addStretch(1)

    scroll.setWidget(panel)
    body.addWidget(scroll, 1)

    self.right_col = _api.QWidget()
    self.right_col.setObjectName("packSettingsPanel")
    self.right_col.setStyleSheet(
        f"#packSettingsPanel {{ background: {_api.C['bg']}; }}")
    col = _api.QVBoxLayout(self.right_col)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(8)
    self.templates_box = self._build_templates()
    col.addWidget(self.templates_box)
    self.pack_box = self._group_pack()
    col.addWidget(self.pack_box)
    # Действия относятся к «Паку», поэтому держим их рядом. Растяжка ниже
    # оставляет свободное место внизу колонки, а не разрывает связанные
    # элементы огромной пустотой на высоком окне.
    self.actions_box = self._build_actions()
    col.addWidget(self.actions_box)
    col.addStretch(1)
    self.scroll_pack = _api.QScrollArea()
    self.scroll_pack.setWidgetResizable(True)
    self.scroll_pack.setFrameShape(_api.QFrame.Shape.NoFrame)
    self.scroll_pack.setHorizontalScrollBarPolicy(
        _api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    self.scroll_pack.setVerticalScrollBarPolicy(
        _api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    self.scroll_pack.setWidget(self.right_col)
    body.addWidget(self.scroll_pack)
    # Колесо мыши не должно менять счётчики ни в настройках, ни в «Паке».
    self._disable_wheel(panel)
    self._disable_wheel(self.right_col)
    self._fit_settings_width()

def _build_actions(self) -> _api.QWidget:
    """Полоса запуска под настройками: «Сгенерировать пак», «Стоп»,
        «Открыть папку» и строчка про автора идеи."""
    box = _api.QWidget()
    v = _api.QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)

    self.btn_start = _api.QPushButton("Сгенерировать пак")
    self.btn_start.setIcon(_api.get_icon('fa5s.magic', color='#11111b'))
    self.btn_start.setIconSize(_api.QSize(16, 16))
    self.btn_start.setObjectName("b_primary")
    self.btn_start.clicked.connect(self.start)
    priority_row = _api.QHBoxLayout()
    priority_row.addWidget(_api.QLabel("Приоритет генерации:"))
    self.cb_generation_priority = _api.QComboBox()
    for title, key in (("Низкий", "low"), ("Обычный", "normal"),
                       ("Высокий", "high")):
        self.cb_generation_priority.addItem(title, key)
    self.cb_generation_priority.setCurrentIndex(1)
    self.cb_generation_priority.setToolTip(
        "Низкий ограничивает параллельные задачи двумя и понижает приоритет "
        "рабочих потоков и ffmpeg. Обычный использует заданное число потоков.")
    priority_row.addWidget(self.cb_generation_priority)
    priority_row.addStretch()
    self.queue_list = _api.QListWidget()
    self.queue_list.setMaximumHeight(100)
    self.queue_list.setVisible(False)
    self.btn_queue_remove = _api.QPushButton("Убрать выбранный из очереди")
    self.btn_queue_remove.setVisible(False)
    self.btn_queue_remove.clicked.connect(self._remove_queued)
    self.btn_stop = _api.QPushButton("Стоп")
    self.btn_stop.setIcon(_api.get_icon('fa5s.stop'))
    self.btn_stop.setEnabled(False)
    self.btn_stop.setToolTip("Остановить генерацию и очистить очередь")
    self.btn_stop.clicked.connect(self.stop)
    self.btn_open = _api.QPushButton("Открыть папку")
    self.btn_open.setIcon(_api.get_icon('fa5s.folder-open'))
    self.btn_open.setEnabled(False)
    self.btn_open.clicked.connect(self._open_result)
    # Таблица состава пака показывается ТОЛЬКО по этой кнопке (просьба
    # пользователя): до генерации в ней всё равно пусто, а место у неё —
    # половина вкладки, и настройкам оно нужнее.
    self.btn_table = _api.QPushButton("Показать таблицу")
    self.btn_table.setIcon(_api.get_icon('fa5s.table'))
    self.btn_table.setEnabled(False)
    self.btn_table.setToolTip(
        "Что именно отобрано в пак: тема, раунд, аниме, песня, род вопроса и "
        "цена. После генерации открывается в отдельном окне.")
    self.btn_table.clicked.connect(self._toggle_table)
    v.addLayout(priority_row)
    v.addWidget(self.btn_start)
    v.addWidget(self.queue_list)
    v.addWidget(self.btn_queue_remove)
    row = _api.QHBoxLayout(); row.setSpacing(6)
    row.addWidget(self.btn_stop, 1)
    row.addWidget(self.btn_open, 1)
    v.addLayout(row)
    v.addWidget(self.btn_table)

    # Ссылка на автора идеи — единственная благодарность на вкладке: слева,
    # под таблицей, такой же надписи больше нет (просьба пользователя).
    # Открывается в браузере (setOpenExternalLinks). Прочие имена в скобках —
    # те же самые ники того же человека, поэтому они выделены и кликабельны
    # ровно так же, как «Leleath» (просьба пользователя).
    link = ('<a href="https://github.com/Leleath/aspg"'
            f' style="color:{_api.C["accent"]}; text-decoration:none;">%s</a>')
    # Это один человек: ссылка охватывает и основной ник, и скобки, и запятые,
    # поэтому вся подпись имени выглядит одним цельным синим фрагментом.
    self.lbl_credit = _api.QLabel(
        "Идея взята у уважаемого " + (link % "Leleath (ффыв, nanri, нефор)"))
    self.lbl_credit.setWordWrap(True)
    self.lbl_credit.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    self.lbl_credit.setOpenExternalLinks(True)
    self.lbl_credit.setTextInteractionFlags(
        _api.Qt.TextInteractionFlag.TextBrowserInteraction)
    self.lbl_credit.setToolTip("https://github.com/Leleath/aspg")
    self.lbl_credit.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
    # Без флага выравнивания в addWidget! С ним раскладка отдаёт надписи её
    # собственный sizeHint, а у QLabel с переносом слов он в одну короткую
    # строку (122 px на живом окне) — строка обрезалась сразу после «Идея
    # взята у уважаемого», и ни «Leleath», ни «нефор» видно не было. Ширину
    # даёт сама колонка, а по центру текст ставит setAlignment выше.
    v.addWidget(self.lbl_credit)
    return box

@staticmethod
def _disable_wheel(root) -> None:
    """Колесо мыши не должно менять значения счётчиков и списков — оно
        прокручивает панель (просьба пользователя)."""
    for cls in (_api.QSpinBox, _api.QDoubleSpinBox, _api.QComboBox):
        for widget in root.findChildren(cls):
            _api._no_wheel(widget)
