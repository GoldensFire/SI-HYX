# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriTab: __init__. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def __init__(self, main_window=None):
    super(_api.ShikimoriTab, self).__init__()
    self.main = main_window
    self._pool = _api.QThreadPool.globalInstance()
    self._task = None          # текущая поисковая задача (ссылка, чтобы жила)
    self._cache_only = False   # True — «Найти по кэшу»: без дозагрузки просмотров
    self._genres_task = None
    self._results: list = []   # последние найденные Anime (после исключений)
    self._raw_results: list = []   # до применения исключения паков
    self._genres_cache: dict = {}  # content_type -> [(id, label, group)]
    self._thumb_cache: dict = {}   # anime_id -> QIcon
    self._thumb_pending: set = set()  # anime_id с уже запущенной загрузкой обложки
    self._placeholder = None       # серая заглушка-обложка
    self._excluded: set = set()    # нормализованные названия из паков
    self._excluded_bases: set = set()  # их «базовые» формы (без сезонов)
    self._excluded_franchises: set = set()  # их «ключи франшиз» (без подзаголовков)
    self._excluded_packs: list = []  # имена выбранных паков
    self._collapse_franchise = True   # схлопывать сезоны/части одной франшизы
    self._seen_franchises: set = set()  # уже показанные франшизы (для схлопывания)
    self._views_cache: dict = {}   # anime_id -> просмотры (для сортировки)
    self._index_base_cache: dict = {}  # anime_id -> взвешенная база индекса
    self._index_breakdown_cache: dict = {}  # anime_id -> разбивка индекса по статусам
    self._index_cache_ts: dict = {}  # anime_id -> когда запись попала в кеш (для TTL)
    # Отложенное (дебаунс) сохранение кеша индекса на диск, чтобы не писать файл
    # на каждый дозагруженный тайтл во время живой сортировки.
    self._index_cache_save_timer = _api.QTimer(self)
    self._index_cache_save_timer.setSingleShot(True)
    self._index_cache_save_timer.timeout.connect(self._save_index_cache)
    self._load_index_cache()
    # Подчистка дискового кеша обложек — с задержкой, чтобы не тормозить старт.
    _api.QTimer.singleShot(3000, _api._prune_covers_cache)
    self._views_task = None        # текущая задача дозагрузки просмотров
    self._anime_by_id: dict = {}   # anime_id -> Anime (для live-обновления строк)
    self._sel_genres: list = []    # выбранные id жанров/тем (текущий тип контента)
    self._pending_genres: list = []  # id для восстановления после async-загрузки
    self._excl_genres: list = []   # исключаемые id жанров/тем
    self._pending_excl: list = []  # исключаемые id для восстановления после async
    self._initial_settings = dict(getattr(main_window, "_shikimori_settings", {}) or {})

    if not _api._HAS_API:
        self._build_unavailable()
        return
    self._build_ui()
    # Восстанавливаем сохранённые настройки (если есть) ДО загрузки жанров,
    # чтобы корректно подтянуть жанры под нужный тип контента.
    if self._initial_settings:
        try:
            self.apply_settings(self._initial_settings)
        except Exception:
            pass
    self._load_genres_async(self._content_type())

# ── Построение UI ───────────────────────────────────────────────────────
def _build_unavailable(self):
    lay = _api.QVBoxLayout(self)
    msg = ("Не удалось загрузить вкладку «ShikimoriHYX».\n\n"
           "Нужен пакет «requests» (pip install requests).")
    if _api._IMPORT_ERROR:
        msg += f"\n\n{_api._IMPORT_ERROR}"
    lbl = _api.QLabel(msg)
    lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color:{_api.C['text2']}; font-size:13px;")
    lay.addStretch(); lay.addWidget(lbl); lay.addStretch()

def _build_ui(self):
    root = _api.QVBoxLayout(self)
    root.setContentsMargins(12, 12, 12, 12)
    root.setSpacing(10)

    # ── Строка поиска: тип контента + запрос + кнопки ─────────────────
    search_row = _api.QHBoxLayout()
    search_row.setSpacing(8)
    self.cb_content = _api.QComboBox()
    self.cb_content.addItem("Аниме", _api.CONTENT_ANIME)
    self.cb_content.addItem("Манга", _api.CONTENT_MANGA)
    self.cb_content.setFixedWidth(110)
    self.cb_content.currentIndexChanged.connect(self._on_content_changed)
    self.ed_query = _api.QLineEdit()
    self.ed_query.setPlaceholderText("Название (можно пусто — тогда фильтры)…")
    self.ed_query.setClearButtonEnabled(True)
    self.ed_query.returnPressed.connect(lambda: self.start_search(False))
    self.ed_query.addAction(_api.get_icon('fa5s.search'),
                            _api.QLineEdit.ActionPosition.LeadingPosition)
    self.btn_search = _api.QPushButton("Найти")
    self.btn_search.setIcon(_api.get_icon('fa5s.search', color='#11111b'))
    self.btn_search.setIconSize(_api.QSize(16, 16))
    self.btn_search.setObjectName("b_primary")
    self.btn_search.clicked.connect(lambda: self.start_search(False))
    self.btn_search_cache = _api.QPushButton("По кэшу")
    self.btn_search_cache.setIcon(_api.get_icon('fa5s.database'))
    self.btn_search_cache.setToolTip(
        "Тот же поиск, но БЕЗ дозагрузки просмотров по сети для сортировки —\n"
        "используются только уже закешированные ранее числа (за один день "
        "просмотры почти не меняются).\nБыстрее, но новые/незнакомые тайтлы "
        "могут остаться внизу списка (без данных).")
    self.btn_search_cache.clicked.connect(lambda: self.start_search(True))
    self.btn_cancel = _api.QPushButton("Стоп")
    self.btn_cancel.setIcon(_api.get_icon('fa5s.stop'))
    self.btn_cancel.setToolTip("Остановить поиск (накопленные результаты останутся)")
    self.btn_cancel.setEnabled(False)
    self.btn_cancel.clicked.connect(self.cancel_search)
    self.btn_clear = _api.QPushButton("Очистить")
    self.btn_clear.setIcon(_api.get_icon('fa5s.trash'))
    self.btn_clear.setToolTip("Очистить список результатов")
    self.btn_clear.clicked.connect(self.clear_results)
    search_row.addWidget(self.cb_content)
    search_row.addWidget(self.ed_query, 1)
    search_row.addWidget(self.btn_search)
    search_row.addWidget(self.btn_search_cache)
    search_row.addWidget(self.btn_cancel)
    search_row.addWidget(self.btn_clear)
    root.addLayout(search_row)

    # ── Тело: слева список с обложками, справа панель настроек ─────────
    body = _api.QHBoxLayout()
    body.setSpacing(12)
    root.addLayout(body, 1)

    # Левая колонка — список результатов.
    left = _api.QVBoxLayout(); left.setSpacing(6)
    self.list = _api.QListWidget()
    self.list.setIconSize(_api.QSize(_api._THUMB_W, _api._THUMB_H))
    self.list.setSpacing(2)
    self.list.setUniformItemSizes(False)
    self.list.setWordWrap(True)
    self.list.itemDoubleClicked.connect(self._open_selected_in_browser)
    self.list.itemSelectionChanged.connect(self._on_selection_changed)
    # Значок «глаз» + просмотры рисует делегат (qtawesome SVG, не emoji).
    self._views_delegate = _api._ViewsBadgeDelegate(self)
    self.list.setItemDelegate(self._views_delegate)
    # Курсор-«рука» при наведении на кнопку «копировать» (видно, что кликабельно).
    self.list.setMouseTracking(True)
    self.list.viewport().setMouseTracking(True)
    self.list.viewport().installEventFilter(self)
    self._copy_hover = False
    # Обложки грузим ЛЕНИВО — только для видимых строк (иначе при широком
    # поиске сотни параллельных запросов к Shikimori упираются в лимит → 429).
    self.list.verticalScrollBar().valueChanged.connect(
        lambda *_: self._load_visible_thumbs())
    left.addWidget(self.list, 1)
    self.lbl_status = _api.QLabel("Готово к поиску.")
    self.lbl_status.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
    left.addWidget(self.lbl_status)
    body.addLayout(left, 1)

    # Правая колонка — прокручиваемая панель настроек.
    self._build_settings_panel(body)

    self._apply_styles()
    self._rebuild_kind_status()
