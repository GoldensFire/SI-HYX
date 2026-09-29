# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackTab: __init__. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


def __init__(self, main_window=None, settings: _api.Optional[dict] = None):
    super(_api.AnimePackTab, self).__init__()
    self.main = main_window
    self._pool = _api.QThreadPool.globalInstance()
    self._task = None
    self._queue = []                  # снимки настроек ожидающих паков
    self._active_settings = None
    self._genres_task = None
    self._genres_timer = None          # отложенная загрузка списка жанров
    self._db_task = None               # обновление базы Shikimori
    self._db_parts = ()                # какие её части сейчас собираются
    self._genres_items: list = []      # (id, подпись, группа) для окна выбора
    self._sel_genres: list = []
    self._excl_genres: list = []
    self._pending_genres: list = []
    self._pending_excl: list = []
    self._user_cards: list = []
    self._saved_users: list = []       # адресная книга ников
    self._exclude_siq: list = []       # паки, чьи франшизы не повторяем
    self._exclude_exact_siq: list = [] # паки, чьи вопросы не повторяем
    self._out_dir = ""
    self._pack_number = 0              # сколько паков уже собрано (для «№ N»)
    self._test_pack_number = 0
    self._last_pack = ""
    self._started_at = 0.0             # для оценки времени на прогресс-баре
    self._closing = False              # после cleanup() новых задач не заводим
    self._initial = dict(settings or {})
    self._load_templates(self._initial)

    if not _api._HAS_CORE:
        self._build_unavailable()
        return
    self._build_ui()
    if self._initial:
        try:
            self.apply_settings(self._initial)
        except Exception:
            pass
    self._recount()
    self._update_table_hint()
    # Жанры нужны только при открытии окна выбора — тянем их с задержкой,
    # чтобы не толкаться с остальным стартом приложения. Таймер именно свой,
    # а не QTimer.singleShot: статический уходит жить сам по себе, и его уже
    # ничем не отменить — cleanup() закрывал вкладку, а через полторы секунды
    # всё равно уходил сетевой запрос.
    self._genres_timer = _api.QTimer(self)
    self._genres_timer.setSingleShot(True)
    self._genres_timer.timeout.connect(self._load_genres_async)
    self._genres_timer.start(1500)

# ── UI ────────────────────────────────────────────────────────────────
def _build_unavailable(self):
    lay = _api.QVBoxLayout(self)
    lbl = _api.QLabel("Не удалось загрузить вкладку «Генерация аниме-пака».\n\n"
                 f"{_api._IMPORT_ERROR}")
    lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color:{_api.C['text2']}; font-size:13px;")
    lay.addStretch(); lay.addWidget(lbl); lay.addStretch()

def _build_ui(self):
    root = _api.QVBoxLayout(self)
    root.setContentsMargins(12, 12, 0, 12)
    root.setSpacing(10)

    body = _api.QHBoxLayout(); body.setSpacing(12)
    root.addLayout(body, 1)

    # ── Слева: состав пака, лог, прогресс ─────────────────────────────
    # Таблица живёт в своей коробке и по умолчанию СПРЯТАНА: до генерации в
    # ней пусто, а место (полвкладки) нужнее настройкам — они и занимают всю
    # ширину, раскладываясь в несколько колонок. Показывается таблица кнопкой
    # «Показать таблицу» под настройками (просьба пользователя).
    self.table_box = _api.QWidget()
    left = _api.QVBoxLayout(self.table_box); left.setSpacing(6)
    left.setContentsMargins(0, 0, 0, 0)
    self.table = _api.QTableWidget(0, len(self.TABLE_HEADERS))
    self.table.setHorizontalHeaderLabels(list(self.TABLE_HEADERS))
    self.table.verticalHeader().setVisible(False)
    self.table.setEditTriggers(_api.QAbstractItemView.EditTrigger.NoEditTriggers)
    self.table.setSelectionBehavior(_api.QAbstractItemView.SelectionBehavior.SelectRows)
    self.table.setAlternatingRowColors(False)
    # Клик по заголовку сортирует таблицу; «№» возвращает порядок пака.
    self.table.setSortingEnabled(True)
    hh = self.table.horizontalHeader()
    # Родная стрелка сортировки ВЫКЛЮЧЕНА нарочно: место под неё Qt
    # резервирует в каждой секции (замерено — ровно 28 px на колонку), из-за
    # чего «Раунд», «Цена» и «Ур.» были вчетверо шире своих цифр. Стрелку
    # рисуем сами — стрелочкой в подписи сортируемой колонки.
    hh.setSortIndicatorShown(False)
    hh.sortIndicatorChanged.connect(self._on_sort_changed)
    hh.setSectionsClickable(True)
    # Ширина колонки — по её содержимому: длинные названия аниме не режутся,
    # а короткие «Ур.» и «Цена» не занимают полтаблицы. Растягивать колонки
    # на всю ширину (Stretch) больше не нужно — пусть будут по значениям.
    hh.setSectionResizeMode(_api.QHeaderView.ResizeMode.ResizeToContents)
    hh.setStretchLastSection(False)
    # Узкие колонки не должны раздуваться из-за заголовка: у «Раунда» и
    # «Цены» содержимое — одна-две цифры, а секция выходила вчетверо шире
    # (просьба пользователя). Стрелку сортировки рисуем маленькой и поверх
    # текста — место под неё Qt резервирует в КАЖДОЙ секции.
    hh.setMinimumSectionSize(24)
    hh.setDefaultAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    # Подсказка «из чего сложился индекс» — своим тёмным попапом по наведению
    # (просьба пользователя), а не синим системным QToolTip.
    from si_hyx_parts.animepack_tab.index_tooltip import install as install_tip
    install_tip(self.table)
    # Таблица занимает всю высоту вкладки: строки состояния над ней больше
    # нет — «Готово за столько-то» пишется прямо на общей полосе прогресса
    # (просьба пользователя), а освободившееся место отдано таблице.
    # Пока таблица пустая (пак ещё не сгенерирован), вместо неё показываем
    # предупреждение про запрет выкладывать сгенерированное в сеть.
    left.addWidget(self.table, 1)
    # Предупреждение рисуется НАКЛАДКОЙ прямо на таблицу (родитель — сама
    # таблица, а не общий layout): скрывать/показывать саму QTableWidget
    # здесь нельзя — hide()/show() на ней плодит крэши в тестах на этой
    # связке PyQt6/Qt. Накладка перекрывает пустую таблицу целиком, пока
    # пак не собран, а прячется — сама, table остаётся видимой всегда.
    self.lbl_table_hint = _api.QLabel(
        "Сгенерированные паки/вопросы запрещено выкладывать в сеть.",
        self.table)
    self.lbl_table_hint.setWordWrap(True)
    self.lbl_table_hint.setAlignment(
        _api.Qt.AlignmentFlag.AlignCenter)
    self.lbl_table_hint.setStyleSheet(
        f"background:{_api.C['bg']}; color:{_api.C['text2']}; font-size:13px; "
        "padding: 0 12px;")
    self.lbl_table_hint.setGeometry(self.table.rect())
    # Ни своей консоли, ни своего прогресс-бара у вкладки нет: и то, и
    # другое идёт в общую полосу внизу окна, как у остальных вкладок.
    self.table_box.setVisible(False)
    body.addWidget(self.table_box, 1)

    self._build_settings_panel(body)
    _compact_numeric_fields(self)
    self._apply_styles()
    # Стили меняют размеры полей — ширину панели считаем уже по ним.
    self._fit_settings_width()
    self._on_song_kinds_toggled()


def _compact_numeric_fields(tab):
    """Не даёт числовым полям растягиваться на целую колонку.

    Сетки настроек нарочно тянут правую колонку: это нужно длинным
    спискам и строкам, но QSpinBox из-за этого вырастал до 200–300 px.
    112 px хватает году, дробной оценке, проценту и длинному seed.
    """
    for cls in (_api.QSpinBox, _api.QDoubleSpinBox):
        for field in tab.findChildren(cls):
            field.setMaximumWidth(112)
