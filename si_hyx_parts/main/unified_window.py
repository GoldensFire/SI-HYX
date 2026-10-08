# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow, фильтр сообщений Qt и обработчик падений. Public namespace: main."""
import main as _api
from si_hyx_parts.main.window_tabs import UnifiedWindowTabsMixin
from si_hyx_parts.main.window_settings import UnifiedWindowSettingsMixin
from si_hyx_parts.main.window_updates import UnifiedWindowUpdatesMixin
from si_hyx_parts.main.window_console import UnifiedWindowConsoleMixin


def _qt_message_filter(mode, context, message):
    for noise in _api._QT_LOG_NOISE:
        if noise in message:
            return
    try:
        from diagnostic_logging import qt_message
        qt_message(message)
        if _api.sys.stderr is not None:
            _api.sys.stderr.write(message + "\n")
            _api.sys.stderr.flush()
    except Exception:
        pass

_qt_message_filter.__module__ = _api.__name__
_api._qt_message_filter = _qt_message_filter

class UnifiedWindow(
    UnifiedWindowTabsMixin,
    UnifiedWindowSettingsMixin,
    UnifiedWindowUpdatesMixin,
    UnifiedWindowConsoleMixin,
    _api.QMainWindow,
):
    url_from_browser = _api.pyqtSignal(str, bool)  # URL + audio_only из браузерного расширения (HTTP-сервер → Qt)
    log_signal = _api.pyqtSignal(str)              # потокобезопасный лог (из фоновых потоков → GUI)
    update_available_sig = _api.pyqtSignal(str, str, int, str, str)  # версия, ссылка на zip, размер (байт), sha256 архива ("" = не проверять), ченжлог
    update_ready_sig = _api.pyqtSignal(str)        # путь к распакованной новой версии (готово к установке)
    ffmpeg_missing_sig = _api.pyqtSignal()         # проверка ffmpeg в фоне не прошла (из потока → GUI)

    # ВНИМАНИЕ РАЗРАБОТЧИКА: В этом приложении категорически запрещено использовать
    # эмодзи. Все новые иконки добавлять строго через метод get_icon() из библиотеки
    # qtawesome! (Реализация — общая функция get_icon() в config.py.)
    def get_icon(self, name, color='#cdd6f4'):
        return _api.get_icon(name, color=color)

    def __init__(self):
        super().__init__()
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
        from .window_visibility import WindowVisibilityGuard
        self._window_visibility_guard = WindowVisibilityGuard(self)
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
        self._tab_tip_badge = None
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
        from elapsed_progress import ElapsedProgressBar
        self.pbar = ElapsedProgressBar()
        self.pbar.setTextVisible(True)
        self.pbar.setFormat("Ожидание")
        self.pbar.setFixedHeight(22)

        # Значок открытия — прямо поверх правого края полосы, без отдельной строки.
        self.btn_open_progress = _api.QToolButton(self.pbar)
        self.btn_open_progress.setText("")
        if _api.OPEN_FILE_ICON:
            self.btn_open_progress.setIcon(_api.QIcon(_api.OPEN_FILE_ICON))
        # Компактный полупрозрачный контейнер без рамки, ярче при наведении.
        self.btn_open_progress.setIconSize(_api.QSize(13, 13))
        self.btn_open_progress.setFixedSize(22, 16)
        self.btn_open_progress.setAutoRaise(True)
        self.btn_open_progress.setStyleSheet(
            "QToolButton{border:none; border-radius:4px; padding:0; margin:0; "
            "min-height:0; background:rgba(205,214,244,28)}"
            "QToolButton:hover{background:rgba(205,214,244,64)}"
            "QToolButton:pressed{background:rgba(205,214,244,92)}"
            "QToolButton:disabled{background:rgba(205,214,244,14)}")
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
        self.txt_log.document().setMaximumBlockCount(10000)
        from diagnostic_logging import bind as bind_diagnostics
        bind_diagnostics(self)
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

    def _build_deferred_tabs_step(self):
        """Достраивает по ОДНОЙ отложенной вкладке за такт цикла событий, чтобы
        между ними окно успевало обработать ввод (см. __init__)."""
        queue = getattr(self, "_deferred_tabs", None)
        if not queue:
            return
        add_tab = queue.pop(0)
        try:
            add_tab()
        except Exception as e:
            self.log(f"Не удалось добавить отложенную вкладку: {e}")
        if queue:
            _api.QTimer.singleShot(0, self._build_deferred_tabs_step)

    def _check_ffmpeg_async(self):
        """Запускает проверку ffmpeg в отдельном потоке (см. __init__): сам запуск
        процесса блокирующий, а держать на нём цикл событий незачем."""
        def worker():
            ok = False
            try:
                ok = _api.check_ffmpeg()
            except Exception:
                ok = False
            if not ok:
                try:
                    self.ffmpeg_missing_sig.emit()
                except Exception:
                    pass
        _api.threading.Thread(target=worker, daemon=True).start()

    def _on_ffmpeg_missing(self):
        _api.msgbox_critical(self, "Error", "FFmpeg not found!")

    def add_paths(self, paths):
        """Роутит файлы из общего стрипа в активную вкладку."""
        current = self.tabs.currentWidget()
        if hasattr(current, 'add_paths') and current is not self:
            current.add_paths(paths)
        else:
            self.tab_media.add_paths(paths)

    def _load_settings(self):
        s, status = _api.load_settings_ex()
        # Прочитать не вышло, хотя сохранённые настройки на диске ЕСТЬ (файл
        # занят антивирусом/другим процессом). Дальше всё поднимется на
        # дефолтах, и первое же авто-сохранение (оно висит на КАЖДОМ
        # чекбоксе/поле, см. _attach_save_handlers, и срабатывает при выходе)
        # записало бы эти дефолты поверх настроек пользователя — насовсем,
        # вместе с .bak. Именно так «слетали все настройки». Поэтому на такой
        # запуск сохранение выключается целиком: настройки на диске остаются
        # нетронутыми, а перезапуск (когда файл снова читается) всё возвращает.
        self._settings_readonly = (status == "locked"
                                   or bool(not s and _api.settings_files_exist()))
        if self._settings_readonly:
            self.log("НАСТРОЙКИ НЕ ПРОЧИТАЛИСЬ: файл настроек есть, но открыть/разобрать "
                     "его не удалось — работаем на значениях по умолчанию, СОХРАНЕНИЕ "
                     "ОТКЛЮЧЕНО до перезапуска (файл на диске не тронут).")
            self._warn_settings_readonly()
        elif status == "recovered":
            # Основной файл и .bak оказались непригодны, но настройки подняты из
            # снимка истории (см. utils._snapshot_settings_history) — работаем
            # как обычно, сохранение включено, просто сообщаем об этом.
            self.log("Настройки восстановлены из резервного снимка: основной файл "
                     "и .bak оказались повреждены.")
        tm = self.tab_media
        ty = self.tab_ytdlp
        self._server_enabled = bool(s.get("server_enabled", False))
        self._wheel_changes_values = bool(s.get("wheel_changes_values", False))
        self._video_hw_decode = bool(s.get("video_hw_decode", True))
        self._keep_models_in_ram = bool(s.get("keep_models_in_ram", False))
        try:
            self.tab_photo.inpaint.set_keep_models(self._keep_models_in_ram)
        except Exception:
            pass
        self._show_advanced_encode = bool(s.get("advanced_encode_visible", False))
        try:
            tm.set_advanced_encode_visible(self._show_advanced_encode)
        except Exception:
            pass
        self._siquester_tab_enabled = bool(s.get("siquester_tab_enabled", False))
        self._shikimori_tab_enabled = bool(s.get("shikimori_tab_enabled", False))
        self._shikimori_settings = dict(s.get("shikimori", {}) or {})
        self._leaderboard_tab_enabled = bool(s.get("leaderboard_tab_enabled", False))
        self._coop_tab_enabled = bool(s.get("coop_tab_enabled", False))
        self._coop_settings = dict(s.get("coop", {}) or {})
        self._animepack_tab_enabled = bool(s.get("animepack_tab_enabled", False))
        self._animepack_settings = dict(s.get("animepack", {}) or {})
        self._animepack_upgrade_tab_enabled = bool(
            s.get("animepack_upgrade_tab_enabled", False))
        self._animepack_upgrade_settings = dict(s.get("animepack_upgrade", {}) or {})
        self._prompt_tab_enabled = bool(s.get("prompt_tab_enabled", False))
        # Ключи внешних API (Gemini, TMDB) — общие для всех вкладок и
        # живут ТОЛЬКО тут: раньше поле ввода дублировалось в каждой вкладке,
        # которой ключ нужен (см. Настройки → «Ключи API»).
        self._api_keys = {k: str(v or "") for k, v in
                          (s.get("api_keys", {}) or {}).items()}
        self._tab_order = list(s.get("tab_order", []) or [])
        m = s.get("media", {})

        # Секции ниже НАРОЧНО в отдельных try/except каждая (а не одном общем):
        # раньше один общий try оборачивал вообще всё восстановление настроек
        # подряд (аудио → видео → папка экспорта → yt-dlp → AVIF), и исключение
        # на ЛЮБОМ раннем поле (например, из-за правки кода, сломавшей метод
        # виджета) тихо обрывало загрузку — все поля, что шли ПОСЛЕ сбойного
        # (папка загрузки, скорость AVIF, cookie_path — они ближе к концу),
        # оставались с дефолтом виджета и выглядели «сброшенными». Первое же
        # следующее изменение любой настройки тут же затирало settings.json
        # этими дефолтами через автосохранение. Изоляция по секциям гарантирует,
        # что падение одной секции не блокирует восстановление остальных.
        try:
            a = m.get("audio", {})
            tm.ck_no_audio.setChecked(a.get("remove", False))
            tm.ck_norm.setChecked(a.get("norm", True))
            tm.s_tgt.setValue(a.get("tgt", -20.0))
            tm.s_lra.setValue(a.get("lra", 11.0))
            tm.s_tp.setValue(a.get("tp", -1.5))
            tm.ck_fade.setChecked(a.get("fade", False))
            tm.s_fade.setValue(a.get("fade_d", 1.0))
            tm.ck_fade_in.setChecked(a.get("fade_in", False))
            tm.s_fade_in.setValue(a.get("fade_in_d", 1.0))
            tm.ck_deg.setChecked(a.get("deg", False))
            tm.s_hz.setValue(a.get("hz", 8000))
            tm.ck_u8.setChecked(a.get("u8", False))
            tm.s_lp.setValue(a.get("lp", 3000))
            tm.s_hp.setValue(a.get("hp", 200))
            tm.s_deg_gain.setValue(a.get("deg_gain_db", 0.0))
            tm.c_abitrate.setCurrentText(a.get("bitrate", "128"))
        except Exception as e:
            self.log(f"_load_settings(audio) error: {e}")

        try:
            v = m.get("video", {})
            tm.chk_enable_video.setChecked(v.get("enabled", True))
            tm.s_spd.setValue(v.get("speed", 100))
            tm.s_crf.setValue(v.get("crf", 45))
            tm.s_pre.setValue(v.get("pre", 2))
            _api.combo_set_value(tm.c_res, v.get("res", "1280x720"))
            tm.c_fps.setCurrentText(v.get("fps", "Исходный (max 30)"))
            tm._set_preset_mode(v.get("preset_mode", "std"))
            tm._set_tune_value(v.get("tune", 0))
            try:
                metric_saved = v.get("metric", "none")
                tm.ck_metric_xpsnr.setChecked(metric_saved == "xpsnr")
                if "target_metric" in v:
                    tm.s_target_metric.setValue(int(float(v.get("target_metric", 40.0))))
                tm.s_target_metric.setEnabled(tm._video_metric_value() == 'xpsnr')
                tm.lbl_target_metric.setEnabled(tm._video_metric_value() == 'xpsnr')
            except Exception: pass
            tm.ck_vfade_in.setChecked(v.get("vfade_in", False))
            tm.s_vfade_in.setValue(v.get("vfade_in_d", 1.0))
            tm.ck_vfade_out.setChecked(v.get("vfade_out", False))
            tm.s_vfade_out.setValue(v.get("vfade_out_d", 1.0))
        except Exception as e:
            self.log(f"_load_settings(video) error: {e}")

        try:
            # Папка экспорта (пусто = рядом с исходником)
            tm.export_dir = m.get("export_dir", "") or ""
            try: tm._update_export_label()
            except Exception: pass
        except Exception as e:
            self.log(f"_load_settings(export_dir) error: {e}")

        try:
            y = s.get("ytdlp", {})
            saved_outdir = y.get("outdir", "")
            if saved_outdir and _api.os.path.isdir(saved_outdir):
                ty.out.setText(saved_outdir)
            ty.c_q.setCurrentText(y.get("quality", ty.c_q.currentText()))
            ty.c_c.setCurrentText(y.get("merge", ty.c_c.currentText()))
            ty.c_s.setCurrentText(y.get("sub_lang", ty.c_s.currentText()))
            ty.c_a.setCurrentText(y.get("audio", ty.c_a.currentText()))
            ty.chk_k.setChecked(y.get("force_kf", ty.chk_k.isChecked()))
            saved_cookie = y.get("cookie_path", "")
            if saved_cookie:
                ty.cookie_edit.setText(saved_cookie)
            saved_proxy = y.get("proxy", "")
            if saved_proxy:
                ty.proxy_edit.setText(saved_proxy)
        except Exception as e:
            self.log(f"_load_settings(ytdlp) error: {e}")

        try:
            av = s.get("avif", {})
            tm.s_lim.setValue(av.get("limit", tm.s_lim.value()))
            tm.ck_lim.setChecked(av.get("limit_on", True))
            tm.s_lim.setEnabled(tm.ck_lim.isChecked())
            tm.s_dim.setValue(av.get("adim", tm.s_dim.value()))
            tm.ck_dim.setChecked(av.get("adim_on", False))
            tm.s_dim.setEnabled(tm.ck_dim.isChecked())
            tm.s_width.setValue(av.get("awidth", tm.s_width.value()) or tm.s_width.value())
            tm.ck_width.setChecked(av.get("awidth_on", False))
            tm.s_width.setEnabled(tm.ck_width.isChecked())
            tm.s_height.setValue(av.get("aheight", tm.s_height.value()) or tm.s_height.value())
            tm.ck_height.setChecked(av.get("aheight_on", False))
            tm.s_height.setEnabled(tm.ck_height.isChecked())
            tm.sl_aspd.setValue(av.get("aspd", tm.sl_aspd.value()))
            tm.s_cq.setValue(av.get("cq", tm.s_cq.value()))
            tm.s_passes.setValue(av.get("fit_passes", 4))
            try: tm.c_priority.setCurrentText(s.get("priority", "Обычный"))
            except Exception: pass
            if hasattr(tm, "ck_overwrite_src"):
                tm.ck_overwrite_src.setChecked(av.get("overwrite_src", False))
            _api.combo_set_value(tm.c_img_fmt, av.get("img_fmt", "avif"))
            try:
                _chroma = str(av.get("chroma", "420"))
                _api.combo_set_value(tm.c_chroma, {"420": "4:2:0", "422": "4:2:2", "444": "4:4:4"}.get(_chroma, "4:2:0"))
            except Exception: pass
        except Exception as e:
            self.log(f"_load_settings(avif) error: {e}")

        # Обновляем стрип последних файлов по восстановленной папке
        try:
            self.recent_strip.refresh(ty.out.text())
        except Exception: pass

    def _on_ipc_connection(self):
        try:
            conn = self._ipc_server.nextPendingConnection()
            if conn:
                conn.readyRead.connect(lambda: self._on_ipc_data(conn))
                conn.disconnected.connect(conn.deleteLater)
        except Exception: pass

    def _on_ipc_data(self, conn):
        try:
            data = bytes(conn.readAll()).decode('utf-8', errors='replace')
            files = [f.strip() for f in data.splitlines() if f.strip() and _api.os.path.exists(f.strip())]
            if files:
                self.raise_(); self.activateWindow()
                self.tabs.setCurrentWidget(self.tab_media)
                self.tab_media.add_paths(files)
                self.log(f"Добавлено через контекстное меню: {', '.join(_api.os.path.basename(f) for f in files)}")
        except Exception: pass

    # ------------------------------------------------------------------
    # HTTP-сервер для браузерного расширения
    # ------------------------------------------------------------------
    def _on_url_from_browser(self, url: str, audio: bool):
        """Вызывается в Qt-потоке: URL от браузерного расширения или служебный сигнал скриншота."""
        try:
            if url.startswith("__screenshot_saved__"):
                fpath = url[len("__screenshot_saved__"):]
                self.log(f"📷 Скриншот сохранён: {fpath}")
                return
            self.tabs.setCurrentWidget(self.tab_ytdlp)
            self.tab_ytdlp.add_dl_direct(url, audio_only=audio)
            self.log(f"URL из браузера ({'аудио' if audio else 'видео'}): {url}")
        except Exception as e:
            self.log(f"_on_url_from_browser error: {e}")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.accept()
        else: e.ignore()

    def dropEvent(self, e):
        try:
            self.raise_(); self.activateWindow()
            files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
            if files:
                self.tabs.setCurrentWidget(self.tab_media); self.tab_media.add_paths(files)
        except Exception: pass

    def eventFilter(self, obj, event):
        # Держим кнопку-значок «развернуть консоль» прижатой к правому верхнему
        # углу консоли при её ресайзе/показе.
        if obj is getattr(self, "txt_log", None) and event.type() in (
                _api.QEvent.Type.Resize, _api.QEvent.Type.Show):
            self._reposition_console_btn()
        if obj is getattr(self, "pbar", None) and event.type() in (
                _api.QEvent.Type.Resize, _api.QEvent.Type.Show):
            self._position_progress_button()
        bar = self.tabs.tabBar() if getattr(self, "tabs", None) is not None else None
        if bar is not None and obj is bar:
            et = event.type()
            if et == _api.QEvent.Type.ToolTip:
                return True
            elif et in (_api.QEvent.Type.Leave, _api.QEvent.Type.Hide,
                        _api.QEvent.Type.WindowDeactivate):
                self._hide_tab_tip()
            elif et in (_api.QEvent.Type.LayoutRequest, _api.QEvent.Type.Resize,
                        _api.QEvent.Type.Move, _api.QEvent.Type.ChildRemoved):
                try: _api.QApplication.instance()._hover_tip_mgr._queue_hover_tip()
                except Exception: pass
            elif et == _api.QEvent.Type.DragEnter:
                if self._tab_drag_has_files(event):
                    event.acceptProposedAction(); return True
            elif et == _api.QEvent.Type.DragMove:
                if self._tab_drag_has_files(event):
                    try: self._tab_drag_hover(bar, event.position().toPoint())
                    except Exception: pass
                    event.acceptProposedAction(); return True
            elif et == _api.QEvent.Type.DragLeave:
                self._tab_drag_idx = -1
                self._tab_drag_timer.stop()
            elif et == _api.QEvent.Type.Drop:
                if self._tab_drag_has_files(event):
                    try: self._tab_drag_drop(bar, event)
                    except Exception as e:
                        try: self.log(f"tab drop error: {e}")
                        except Exception: pass
                    event.acceptProposedAction(); return True
            elif et == _api.QEvent.Type.Wheel:
                self._tab_wheel_scroll(event)
                return True
        elif bar is not None and obj.property("tabTipManaged"):
            if event.type() == _api.QEvent.Type.ToolTip:
                return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _stop_worker(w, stop_ms=5000, kill_ms=2000):
        """Останавливает QThread-воркер: stop() → wait → terminate → wait."""
        try:
            if hasattr(w, "stop"):
                w.stop()
            w.wait(stop_ms)
            if w.isRunning():
                w.terminate()
                w.wait(kill_ms)
        except Exception:
            pass

    def closeEvent(self, ev):
        try:
            self.log("Завершение: останавливаем активные потоки...")
            mr = getattr(self.tab_media, "worker", None)
            if mr and mr.isRunning():
                self._stop_worker(mr)
            for w in list(getattr(self.tab_ytdlp, "active_workers", [])):
                self._stop_worker(w)
            try:
                te = getattr(self, "tab_edit", None)
                if te is not None:
                    te.shutdown()
            except Exception:
                pass
            try:
                tsq = getattr(self, "tab_siquester", None)
                if tsq is not None:
                    tsq.cleanup()
            except Exception:
                pass
            try:
                tsh = getattr(self, "tab_shikimori", None)
                if tsh is not None:
                    tsh.cleanup()
            except Exception:
                pass
            try:
                tlb = getattr(self, "tab_leaderboard", None)
                if tlb is not None:
                    tlb.cleanup()
            except Exception:
                pass
            try:
                tcp = getattr(self, "tab_coop", None)
                if tcp is not None:
                    tcp.cleanup()
            except Exception:
                pass
            try:
                self._stop_browser_http_server()
            except Exception:
                pass
            try:
                _api.QThreadPool.globalInstance().waitForDone(3000)
            except Exception:
                pass
            try:
                self._save_settings_now()
            except Exception:
                pass
            self.log("Потоки остановлены, завершаем приложение.")
        except Exception:
            pass
        super().closeEvent(ev)


UnifiedWindow.__module__ = _api.__name__
_api.UnifiedWindow = UnifiedWindow

def _install_crash_handler():
    """Глобальный обработчик необработанных исключений: пишет трейсбек в
    crash.log, показывает пользователю диалог с ошибкой и аккуратно завершает
    программу. Так падение не «исчезает в никуда», а видно пользователю."""
    import traceback as _tb
    import datetime as _dt
    crash_log = _api.os.path.join(_api.CONFIG_DIR, "crash.log")
    _already = {"shown": False}

    def _handle(exc_type, exc_value, exc_tb):
        # Ctrl+C — стандартное поведение, не показываем диалог
        if issubclass(exc_type, KeyboardInterrupt):
            _api.sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_text = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        # Защита от рекурсии: если падение случилось при показе диалога
        if _already["shown"]:
            try:
                _api.sys.stderr.write(tb_text)
            except Exception:
                pass
            _api.os._exit(1)
        _already["shown"] = True
        try:
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\n===== {_dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
                f.write(tb_text)
        except Exception:
            pass
        try:
            if _api.sys.stderr is not None:
                _api.sys.stderr.write(tb_text)
                _api.sys.stderr.flush()
        except Exception:
            pass
        try:
            from error_report import ErrorReportDialog
            dlg = ErrorReportDialog(
                "SI-HYX — критическая ошибка",
                "Произошла непредвиденная ошибка, программа будет закрыта.",
                detail=f"{exc_type.__name__}: {exc_value}",
                where="Критическая ошибка (краш)",
                report_detail=tb_text)
            try:
                if _api.APP_ICON:
                    dlg.setWindowIcon(_api.QIcon(_api.APP_ICON))
            except Exception:
                pass
            dlg.exec()
        except Exception:
            try:
                from PyQt6.QtWidgets import QMessageBox
                box = QMessageBox()
                box.setIcon(QMessageBox.Icon.Critical)
                box.setWindowTitle("SI-HYX — критическая ошибка")
                box.setText("Произошла непредвиденная ошибка, программа будет закрыта.")
                box.setInformativeText(f"{exc_type.__name__}: {exc_value}")
                box.setDetailedText(tb_text)
                box.exec()
            except Exception:
                pass
        _api.os._exit(1)

    _api.sys.excepthook = _handle

_install_crash_handler.__module__ = _api.__name__
_api._install_crash_handler = _install_crash_handler
