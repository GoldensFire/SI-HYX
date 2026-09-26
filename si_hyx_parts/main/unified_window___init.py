# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: __init__. Public namespace: main."""
import main as _api


def __init__(self):
    super(_api.UnifiedWindow, self).__init__()
    self.setWindowTitle(_api.APP_TITLE)
    if _api.APP_ICON:
        self.setWindowIcon(_api.QIcon(_api.APP_ICON))
    screen = _api.QApplication.primaryScreen()
    try: geom = screen.availableGeometry(); max_h = geom.height() - 80
    except Exception: geom = screen.geometry(); max_h = geom.height() - 80
    # Подгоняем стартовый размер под экран пользователя (не больше доступной области)
    try: avail_w = geom.width() - 40
    except Exception: avail_w = 1280
    init_h = min(900, max_h); init_w = min(1280, max(800, avail_w))
    self.setMinimumSize(720, 480)
    self.resize(init_w, init_h)
    try: center_x = geom.x() + (geom.width() - init_w)//2; center_y = geom.y() + (geom.height() - init_h)//2; self.move(center_x, center_y)
    except Exception: pass

    self.setAcceptDrops(True)
    # Прогресс на иконке в панели задач (Windows 11, ITaskbarList3)
    self._taskbar = _api.TaskbarProgress()
    self._taskbar_hwnd = 0
    self.log_signal.connect(self.log)
    self.update_available_sig.connect(self._on_update_available)
    self.update_ready_sig.connect(self._apply_update)

    # Колёсико мыши: меняет ли значения в полях (по умолчанию — нет, только прокрутка)
    self._wheel_changes_values = False
    self._wheel_filter = _api.WheelBlocker(self, lambda: self._wheel_changes_values)
    _api.QApplication.instance().installEventFilter(self._wheel_filter)
    # Проверка ffmpeg — В ФОНЕ, уже после показа окна. check_ffmpeg() запускает
    # bin\ffmpeg.exe (а это 215 МБ статической сборки) и ждёт его: на SSD это
    # ~350 мс до первого кадра, на жёстком диске — секунды, и всё это время
    # окна на экране просто нет. Результат нужен только чтобы показать
    # сообщение об ошибке, так что оно подождёт полторы секунды.
    self.ffmpeg_missing_sig.connect(self._on_ffmpeg_missing)
    _api.QTimer.singleShot(1500, self._check_ffmpeg_async)

    c = _api.QWidget(); self.setCentralWidget(c); l = _api.QVBoxLayout(c)
    l.setContentsMargins(8, 8, 8, 8); l.setSpacing(6)

    # --- Плашка обновления (скрыта по умолчанию) ---
    self._pending_update_url = ""
    self._pending_update_version = ""
    self._pending_update_sha = ""
    self._pending_update_changelog = ""   # текст релиза с GitHub (что нового)
    self._skipped_update_version = self._load_skipped_version()
    self.update_banner = _api.QWidget()
    self.update_banner.setObjectName("updateBanner")
    self.update_banner.setStyleSheet(
        "#updateBanner{background:#313244; border:1px solid #89b4fa; border-radius:6px;}")
    self.update_banner.setVisible(False)
    bl = _api.QHBoxLayout(self.update_banner)
    bl.setContentsMargins(12, 6, 12, 6); bl.setSpacing(8)
    self.update_banner_lbl = _api.QLabel("Доступно обновление")
    self.update_banner_lbl.setStyleSheet("color:#cdd6f4; font-weight:bold; background:transparent;")
    btn_up_now = _api.QPushButton("Обновить")
    btn_up_now.setIcon(_api.get_icon('fa5s.download', color='#1e1e2e'))
    btn_up_now.setIconSize(_api.QSize(20, 20))
    btn_up_now.setObjectName("b_run")
    btn_up_now.clicked.connect(self._on_banner_update)
    # «Что нового» — показывает ченжлог релиза, взятый со страницы GitHub
    # releases (тело релиза). Виден только если ченжлог пришёл.
    self.btn_changelog = _api.QPushButton("Что нового")
    self.btn_changelog.setIcon(_api.get_icon('fa5s.scroll'))
    self.btn_changelog.setToolTip("Показать список изменений этого релиза")
    self.btn_changelog.clicked.connect(self._show_changelog)
    self.btn_changelog.setVisible(False)
    btn_skip = _api.QPushButton("Пропустить версию")
    btn_skip.setToolTip("Больше не предлагать обновиться до этой версии (при выходе следующей — предложу снова)")
    btn_skip.clicked.connect(self._on_banner_skip)
    btn_later = _api.QPushButton("Позже")
    btn_later.clicked.connect(lambda: self.update_banner.setVisible(False))
    bl.addWidget(self.update_banner_lbl); bl.addStretch()
    bl.addWidget(self.btn_changelog)
    bl.addWidget(btn_up_now); bl.addWidget(btn_skip); bl.addWidget(btn_later)
    l.addWidget(self.update_banner)

    self.tabs = _api.QTabWidget()
    self.tab_media = _api.MediaTab(self); self.tab_ytdlp = _api.YtdlpTab(self)
    self.tab_photo = _api.PhotoTab(self)
    self.tab_b64    = _api.Base64Tab(self)
    self.tab_prompt = _api.PromptTab(self)
    # Объект создан, но если вкладка выключена — он НЕ в таббаре. Родитель у
    # него — главное окно, поэтому без явного hide() он «висит» дочерним
    # виджетом в левом верхнем углу. Прячем; addTab() сам покажет при включении.
    self.tab_prompt.hide()
    self.tab_edit   = _api.EditTab(self)
    self.tab_media.thumb_sig.connect(self.tab_media.set_thumb)
    self.tab_ytdlp.thumb_sig.connect(self.tab_ytdlp.set_thumb)
    # Заголовки + краткие описания вкладок (подсказка ⓘ при наведении).
    # (icon_name, title, tip) — значок вкладки рисуется через get_icon().
    self._tab_info = {
        'media':  ("fa5s.cogs", "Обработка",
                   "Тут происходит сжатие медиафайлов"),
        'ytdlp':  ("fa5s.cloud-download-alt", "Загрузчик",
                   "Скачивание видео/аудио с YouTube и других платформ"),
        'edit':   ("fa5s.cut", "Монтаж",
                   "(Бета-тест) Упрощённый видеоредактор, пока из основных фич только кадрирование, обрезка без перекодирования, удаление вотермарок"),
        'photo':  ("fa5s.image", "Редактирование фото",
                   "Супер-лайт версия Photoshop: Кадрирование, удаление объектов, удаление фона и отдельно объединение фото"),
        'b64':    ("fa5s.font", "Base64",
                   "Кодирование файлов и текста в Base64."),
        'prompt': ("fa5s.clipboard", "Промпт",
                   "Вам это не нужно. Менеджер промптов для нейронки."),
        'siquester': ("fa5s.dice", "SiQuesterHYX",
                      "Экспериментальная вкладка SiQuester: просмотр и работа "
                      "с .siq-вопросами."),
        'shikimori': ("fa5s.tv", "ShikimoriHYX",
                      "Экспериментальная вкладка: поиск аниме/манги через Shikimori"),
        'leaderboard': ("fa5s.trophy", "ЛидербордHYX",
                        "Просмотр выгрузки рекордов из Firebase: никнеймы и их "
                        "результаты, удаление ников из списка."),
        'coop': ("fa5s.users", "Collab",
                 "Совместная работа над .siq: темы, вопросы и ответы напарника "
                 "в реальном времени — видно, кто что сделал, и где дубли."),
        'animepack': ("fa5s.music", "Генерация аниме-пака",
                      "Собирает готовый .siq по опенингам/эндингам: аниме "
                      "берутся из базы AMQ или из списков MyAnimeList/"
                      "Shikimori, песни — из AnisongDB, обложки и кадры — "
                      "с Shikimori."),
        'animepack_upgrade': ("fa5s.magic", "Апгрейд пака",
                              "Дорабатывает ГОТОВЫЙ .siq: превращает "
                              "спецвопросы (с секретом, со ставкой, для "
                              "себя) в обычные, дописывает в ответы "
                              "остальные названия — аниме с Shikimori, "
                              "фильмов с Wikidata, — правит их написание, "
                              "кладёт в ответ постер, сжимает тяжёлые "
                              "картинки, дорожки и ролики и выбрасывает "
                              "файлы, на которые нет ссылок."),
    }
    self.tabs.setIconSize(_api.QSize(16, 16))
    self._add_tab(self.tab_media,  'media')
    self._add_tab(self.tab_ytdlp,  'ytdlp')
    self._add_tab(self.tab_edit,   'edit')
    self._add_tab(self.tab_photo,  'photo')
    self._add_tab(self.tab_b64,    'b64')
    # Вкладка «Промпт» по умолчанию ВЫКЛЮЧЕНА (как SiQuesterHYX/ShikimoriHYX).
    # Объект создан выше (он лёгкий и на него ссылается сохранение настроек),
    # но в таббар добавляется только если включена — см. _add_prompt_tab.

    # Вкладки можно перетаскивать мышью и сортировать в удобном порядке;
    # порядок сохраняется между запусками (см. _save_tab_order / tab_order).
    self.tabs.setMovable(True)
    # Как в браузере: вкладки НЕ ужимаются, а при нехватке ширины уезжают
    # за край — QTabBar сам рисует стрелки-прокрутки справа, ими можно
    # долистать до вкладок, которые не поместились. Дополнительно крутим
    # эти же вкладки колёсиком мыши (см. eventFilter/_tab_wheel_scroll).
    self.tabs.setUsesScrollButtons(True)
    try:
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.tabBar().setElideMode(_api.Qt.TextElideMode.ElideNone)
        self._style_tab_scroll_buttons()
    except Exception:
        pass
    self._reordering_tabs = False
    try:
        self.tabs.tabBar().tabMoved.connect(self._on_tab_moved)
    except Exception:
        pass

    # Подсказка ⓘ на вкладке: значок-бейдж внутри QTabBar не получает
    # enter/leave надёжно (таббар сам обрабатывает наведение), поэтому
    # показываем фирменный попап сами — отслеживаем движение мыши над
    # таббаром и проверяем, под каким бейджем курсор.
    self._tab_tip_idx = -1
    try:
        bar = self.tabs.tabBar()
        bar.setMouseTracking(True)
        bar.installEventFilter(self)
        # Перетаскивание файла НА заголовок вкладки: наведение задерживается
        # → вкладка открывается сама (можно бросить в её содержимое), а бросок
        # прямо на заголовок добавляет файл в эту вкладку (см. eventFilter).
        bar.setAcceptDrops(True)
    except Exception:
        pass
    self._tab_drag_idx = -1
    self._tab_drag_timer = _api.QTimer(self)
    self._tab_drag_timer.setSingleShot(True)
    self._tab_drag_timer.timeout.connect(self._tab_drag_switch)

    # Кнопки в строке вкладок — corner widget подгоняется под высоту таббара
    self.btn_settings = _api.QToolButton()
    self.btn_settings.setIcon(_api.get_icon('fa5s.cog'))
    self.btn_settings.setIconSize(_api.QSize(20, 20))
    self.btn_settings.setToolTip("Настройки")
    self.btn_settings.setStyleSheet("QToolButton{min-height:0px; padding:2px 8px;}")
    self.btn_settings.setFixedHeight(26)
    self.btn_settings.clicked.connect(self._open_settings_dialog)
    corner = _api.QWidget()
    ch = _api.QHBoxLayout(corner); ch.setContentsMargins(0, 2, 6, 2); ch.setSpacing(4)
    ch.addWidget(self.btn_settings)
    self.tabs.setCornerWidget(corner, _api.Qt.Corner.TopRightCorner)

    # Единый стрип файлов — общий для всех вкладок (только медиа: видео/аудио/изображения)
    self.recent_strip = _api.RecentFilesStrip(self, mode='media')
    l.addWidget(self.recent_strip)
    l.addWidget(self.tabs)

    self._global_result_path = ""
    self.pbar = _api.QProgressBar()
    self.pbar.setTextVisible(True)
    self.pbar.setFormat("Ожидание")
    self.pbar.setFixedHeight(22)

    # Значок открытия — прямо поверх правого края полосы, без отдельной строки.
    self.btn_open_progress = _api.QToolButton(self.pbar)
    self.btn_open_progress.setText("")
    if _api.OPEN_FILE_ICON:
        self.btn_open_progress.setIcon(_api.QIcon(_api.OPEN_FILE_ICON))
    self.btn_open_progress.setIconSize(_api.QSize(15, 15))
    self.btn_open_progress.setFixedSize(20, 20)
    self.btn_open_progress.setAutoRaise(True)
    self.btn_open_progress.setStyleSheet(
        "QToolButton{border:0; border-radius:4px; padding:2px; "
        "background:rgba(17,17,27,150)}"
        "QToolButton:hover{background:rgba(49,50,68,230)}"
        "QToolButton:pressed{background:rgba(69,71,90,240)}")
    self.btn_open_progress.setEnabled(False)
    self.btn_open_progress.setToolTip("Последний созданный файл появится здесь")
    self.btn_open_progress.clicked.connect(self._open_global_result)
    self.pbar.installEventFilter(self)
    self._position_progress_button()
    l.addWidget(self.pbar)

    # Лог-консоль внизу окна. Показывается на всех вкладках, КРОМЕ «Монтаж»
    # (там она занимает место, нужное редактору) — скрывается при переходе
    # на вкладку монтажа, см. _sync_console_visibility.
    self.console_panel = _api.QWidget(c)
    cpl = _api.QVBoxLayout(self.console_panel)
    cpl.setContentsMargins(0, 0, 0, 0); cpl.setSpacing(2)

    self.txt_log = _api.QTextEdit(self.console_panel); self.txt_log.setReadOnly(True)
    self.txt_log.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
    self.txt_log.customContextMenuRequested.connect(self._log_context_menu)
    self.txt_log.setMaximumHeight(150)
    cpl.addWidget(self.txt_log)
    from si_hyx_parts.main.console_search import install_search
    install_search(self.txt_log)
    l.addWidget(self.console_panel)

    # Кнопка-значок «развернуть консоль» — поверх самой консоли, в правом
    # верхнем углу (как кнопка полноэкранного режима у видео).
    self.btn_open_console = _api.QToolButton(self.txt_log)
    self.btn_open_console.setIcon(_api.get_icon('fa5s.expand-alt'))
    self.btn_open_console.setIconSize(_api.QSize(13, 13))
    self.btn_open_console.setToolTip("Развернуть консоль почти на всё окно")
    self.btn_open_console.setCursor(_api.Qt.CursorShape.PointingHandCursor)
    self.btn_open_console.setFixedSize(22, 22)
    self.btn_open_console.setStyleSheet(
        "QToolButton{background:rgba(40,40,48,0.65); border:1px solid rgba(255,255,255,0.12);"
        " border-radius:4px; padding:0;}"
        "QToolButton:hover{background:rgba(70,70,85,0.9);}")
    self.btn_open_console.clicked.connect(self._open_console_window)
    self.btn_open_console.raise_()
    self.txt_log.installEventFilter(self)
    # Перепозиционируем кнопку, когда появляется/исчезает вертикальный
    # скроллбар (рост лога), иначе он наезжает на кнопку.
    try:
        self.txt_log.verticalScrollBar().rangeChanged.connect(
            lambda *_: self._reposition_console_btn())
    except Exception:
        pass
    self._reposition_console_btn()
    self._console_dialog = None
    self.tabs.currentChanged.connect(self._sync_console_visibility)
    # tabBarClicked стреляет ДО фактического переключения страницы (в
    # отличие от currentChanged) — синхронизируем консоль заранее, чтобы
    # холст «Монтажа» получал финальную высоту сразу, без видимого прыжка.
    self.tabs.tabBar().tabBarClicked.connect(self._on_tab_bar_clicked)
    self._sync_console_visibility()

    # Состояние локального сервера для расширения (по умолчанию ВЫКЛ)
    self._server_enabled = False
    self._http_srv = None
    self._http_thread = None

    # Экспериментальная вкладка SiQuester (по умолчанию ВЫКЛ, см. Настройки).
    self._siquester_tab_enabled = False
    self.tab_siquester = None

    # Экспериментальная вкладка ShikimoriHYX (по умолчанию ВЫКЛ).
    self._shikimori_tab_enabled = False
    self.tab_shikimori = None
    self._shikimori_settings = {}   # сохранённые фильтры вкладки ShikimoriHYX

    # Экспериментальная вкладка ЛидербордHYX (по умолчанию ВЫКЛ).
    self._leaderboard_tab_enabled = False
    self.tab_leaderboard = None

    # Экспериментальная вкладка Collab (по умолчанию ВЫКЛ).
    self._coop_tab_enabled = False
    self.tab_coop = None
    self._coop_settings = {}   # сохранённые поля вкладки Collab

    # Экспериментальная вкладка Генерация аниме-пака (по умолчанию ВЫКЛ).
    self._animepack_tab_enabled = False
    self.tab_animepack = None
    self._animepack_settings = {}   # сохранённые настройки генератора

    # Экспериментальная вкладка Апгрейд пака (по умолчанию ВЫКЛ).
    self._animepack_upgrade_tab_enabled = False
    self.tab_animepack_upgrade = None
    self._animepack_upgrade_settings = {}   # сохранённые настройки доводки

    # Вкладка «Промпт» (по умолчанию ВЫКЛ).
    self._prompt_tab_enabled = False

    # Настройки на диске есть, но прочитать их не удалось — см.
    # _load_settings/_save_settings_now. Ставим ДО загрузки: она вызвана под
    # `except: pass` ниже и может свалиться до присвоения флага.
    self._settings_readonly = False

    try:
        self._load_settings()
    except Exception as e:
        # Загрузка оборвалась на полпути (например, правка кода сломала
        # обращение к виджету). Всё, что шло ПОСЛЕ места сбоя, осталось с
        # дефолтами — и автосохранение (висит на каждом поле) записало бы
        # эти дефолты поверх живых настроек пользователя. Поэтому такой
        # запуск тоже переводим в режим «ничего не сохраняем».
        self._settings_readonly = _api.settings_files_exist()
        self.log(f"ОШИБКА ЗАГРУЗКИ НАСТРОЕК: {e}")
        if self._settings_readonly:
            self.log("Сохранение отключено до перезапуска — файл настроек на "
                     "диске не тронут.")
            self._warn_settings_readonly()

    self._attach_save_handlers()

    # Подключаем вкладку «Промпт», если включена в настройках.
    if getattr(self, "_prompt_tab_enabled", False):
        self._add_prompt_tab()

    # Подключаем экспериментальную вкладку SiQuester, если включена в настройках.
    if getattr(self, "_siquester_tab_enabled", False):
        self._add_siquester_tab()

    # Остальные экспериментальные вкладки — ПОСЛЕ показа окна, по одной за
    # такт цикла событий (см. _build_deferred_tabs_step). Каждая из них
    # строится 1–2 секунды, и раньше эти секунды набегали ДО show(): окна
    # просто не было на экране ~10 секунд, нажать было нечего. Теперь окно
    # появляется сразу, а вкладки досоздаются на глазах, не блокируя ввод
    # между собой. Порядок — как в сохранённом _tab_order (каждая
    # _add_*_tab в конце сама зовёт _apply_tab_order).
    self._deferred_tabs = []
    if getattr(self, "_shikimori_tab_enabled", False):
        self._deferred_tabs.append(self._add_shikimori_tab)
    if getattr(self, "_leaderboard_tab_enabled", False):
        self._deferred_tabs.append(self._add_leaderboard_tab)
    if getattr(self, "_coop_tab_enabled", False):
        self._deferred_tabs.append(self._add_coop_tab)
    if getattr(self, "_animepack_tab_enabled", False):
        self._deferred_tabs.append(self._add_animepack_tab)
    if getattr(self, "_animepack_upgrade_tab_enabled", False):
        self._deferred_tabs.append(self._add_animepack_upgrade_tab)
    if self._deferred_tabs:
        _api.QTimer.singleShot(0, self._build_deferred_tabs_step)

    # Восстанавливаем сохранённый порядок вкладок (перетаскивание мышью).
    try:
        self._apply_tab_order(getattr(self, "_tab_order", []))
    except Exception:
        pass

    # Колёсико над полями не должно «активировать» их визуально (фокус по скроллу):
    # убираем WheelFocus у всех числовых полей/списков/ползунков во всех вкладках.
    try:
        for _w in (self.findChildren(_api.QAbstractSpinBox)
                   + self.findChildren(_api.QComboBox)
                   + self.findChildren(_api.QSlider)):
            _w.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
    except Exception:
        pass

    # IPC-сервер: принимает файлы от нового запуска через ПКМ проводника
    self._ipc_server = _api.QLocalServer(self)
    _api.QLocalServer.removeServer("YasperMoglotIPC")
    self._ipc_server.listen("YasperMoglotIPC")
    self._ipc_server.newConnection.connect(self._on_ipc_connection)

    # HTTP-сервер: принимает URL от браузерного расширения (localhost:7432).
    # По умолчанию выключен — включается в Настройках.
    self.url_from_browser.connect(self._on_url_from_browser)
    if self._server_enabled:
        self._start_browser_http_server()

    # Тихая проверка обновлений при запуске (молча, если версия актуальна)
    self._updating = False
    _api.QTimer.singleShot(2500, lambda: self._check_updates(silent=True))
