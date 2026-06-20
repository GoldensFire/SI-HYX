# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# main.py — главное окно, HTTP-сервер расширения, точка входа
from config import *
from utils import *
from widgets import *
from workers import *
from tabs import *
from edit_tab import EditTab
from taskbar import TaskbarProgress
from PyQt6.QtCore import qInstallMessageHandler, QSize, QTranslator, QLibraryInfo, QLocale
from PyQt6.QtWidgets import QTabBar
import qtawesome as qta
import hashlib


# QtMultimedia с FFmpeg-бэкендом (плеер вкладки «Монтаж») при каждой смене
# состояния (play/pause/seek) пересобирает декодер и сыпет безобидными
# «QObject::disconnect: wildcard call disconnects from destroyed signal of
# QFFmpeg::…» в stderr. Глушим ТОЛЬКО этот шум, остальное пропускаем дальше.
_QT_LOG_NOISE = (
    "disconnects from destroyed signal",
    # Безобидное предупреждение opus-декодера ffmpeg-бэкенда при паузе/возобновлении
    # воспроизведения во вкладке «Монтаж» — глушим, чтобы не пугать пользователя.
    "Could not update timestamps for skipped samples",
    # MKV с прикреплёнными шрифтами (Attachment-потоки): ffmpeg-бэкенд QtMultimedia
    # не знает кодек шрифта и сыпет «Could not find codec parameters for stream N
    # (Attachment: none): unknown codec» + совет про analyzeduration/probesize.
    # Это безобидно (шрифты не нужны для воспроизведения видео/аудио) — глушим,
    # в т.ч. когда тот же файл открывает вкладка «SiQuesterHYX».
    "Could not find codec parameters for stream",
    "Consider increasing the value for the 'analyzeduration'",
)


def _qt_message_filter(mode, context, message):
    for noise in _QT_LOG_NOISE:
        if noise in message:
            return
    try:
        if sys.stderr is not None:
            sys.stderr.write(message + "\n")
            sys.stderr.flush()
    except Exception:
        pass


class UnifiedWindow(QMainWindow):
    url_from_browser = pyqtSignal(str, bool)  # URL + audio_only из браузерного расширения (HTTP-сервер → Qt)
    log_signal = pyqtSignal(str)              # потокобезопасный лог (из фоновых потоков → GUI)
    update_available_sig = pyqtSignal(str, str, int, str)  # версия, ссылка на zip, размер (байт), sha256 архива ("" = не проверять)
    update_ready_sig = pyqtSignal(str)        # путь к распакованной новой версии (готово к установке)

    # ВНИМАНИЕ РАЗРАБОТЧИКА: В этом приложении категорически запрещено использовать
    # эмодзи. Все новые иконки добавлять строго через метод get_icon() из библиотеки
    # qtawesome! (Реализация — общая функция get_icon() в config.py.)
    def get_icon(self, name, color='#cdd6f4'):
        return get_icon(name, color=color)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        if APP_ICON:
            self.setWindowIcon(QIcon(APP_ICON))
        screen = QApplication.primaryScreen()
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
        self._taskbar = TaskbarProgress()
        self._taskbar_hwnd = 0
        self.log_signal.connect(self.log)
        self.update_available_sig.connect(self._on_update_available)
        self.update_ready_sig.connect(self._apply_update)

        # Колёсико мыши: меняет ли значения в полях (по умолчанию — нет, только прокрутка)
        self._wheel_changes_values = False
        self._wheel_filter = WheelBlocker(self, lambda: self._wheel_changes_values)
        QApplication.instance().installEventFilter(self._wheel_filter)
        if not check_ffmpeg(): QMessageBox.critical(self, "Error", "FFmpeg not found!")

        c = QWidget(); self.setCentralWidget(c); l = QVBoxLayout(c)
        l.setContentsMargins(8, 8, 8, 8); l.setSpacing(6)

        # --- Плашка обновления (скрыта по умолчанию) ---
        self._pending_update_url = ""
        self._pending_update_version = ""
        self._pending_update_sha = ""
        self._skipped_update_version = self._load_skipped_version()
        self.update_banner = QWidget()
        self.update_banner.setObjectName("updateBanner")
        self.update_banner.setStyleSheet(
            "#updateBanner{background:#313244; border:1px solid #89b4fa; border-radius:6px;}")
        self.update_banner.setVisible(False)
        bl = QHBoxLayout(self.update_banner)
        bl.setContentsMargins(12, 6, 12, 6); bl.setSpacing(8)
        self.update_banner_lbl = QLabel("Доступно обновление")
        self.update_banner_lbl.setStyleSheet("color:#cdd6f4; font-weight:bold; background:transparent;")
        btn_up_now = QPushButton("Обновить")
        btn_up_now.setIcon(get_icon('fa5s.download', color='#1e1e2e'))
        btn_up_now.setIconSize(QSize(20, 20))
        btn_up_now.setObjectName("b_run")
        btn_up_now.clicked.connect(self._on_banner_update)
        btn_skip = QPushButton("Пропустить версию")
        btn_skip.setToolTip("Больше не предлагать обновиться до этой версии (при выходе следующей — предложу снова)")
        btn_skip.clicked.connect(self._on_banner_skip)
        btn_later = QPushButton("Позже")
        btn_later.clicked.connect(lambda: self.update_banner.setVisible(False))
        bl.addWidget(self.update_banner_lbl); bl.addStretch()
        bl.addWidget(btn_up_now); bl.addWidget(btn_skip); bl.addWidget(btn_later)
        l.addWidget(self.update_banner)

        self.tabs = QTabWidget()
        self.tab_media = MediaTab(self); self.tab_ytdlp = YtdlpTab(self)
        self.tab_photo = PhotoMergerTab(self)
        self.tab_b64    = Base64Tab(self)
        self.tab_prompt = PromptTab(self)
        # Объект создан, но если вкладка выключена — он НЕ в таббаре. Родитель у
        # него — главное окно, поэтому без явного hide() он «висит» дочерним
        # виджетом в левом верхнем углу. Прячем; addTab() сам покажет при включении.
        self.tab_prompt.hide()
        self.tab_edit   = EditTab(self)
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
                       "(Бета-тест) Обрезка видео / аудио, в том числе без перекодирования"),
            'photo':  ("fa5s.image", "Объединить фото",
                       "Объединение нескольких изображений в одно."),
            'b64':    ("fa5s.font", "Base64",
                       "Кодирование файлов и текста в Base64."),
            'prompt': ("fa5s.clipboard", "Промпт",
                       "Менеджер промптов: хранение и быстрый выбор заготовок."),
            'siquester': ("fa5s.dice", "SiQuesterHYX",
                          "Экспериментальная вкладка SiQuester: просмотр и работа "
                          "с .siq-вопросами."),
            'shikimori': ("fa5s.tv", "ShikimoriHYX",
                          "Экспериментальная вкладка: поиск аниме/манги через Shikimori"),
        }
        self.tabs.setIconSize(QSize(16, 16))
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
        except Exception:
            pass

        # Кнопки в строке вкладок — corner widget подгоняется под высоту таббара
        self.btn_settings = QToolButton()
        self.btn_settings.setIcon(get_icon('fa5s.cog'))
        self.btn_settings.setIconSize(QSize(20, 20))
        self.btn_settings.setToolTip("Настройки")
        self.btn_settings.setStyleSheet("QToolButton{min-height:0px; padding:2px 8px;}")
        self.btn_settings.setFixedHeight(26)
        self.btn_settings.clicked.connect(self._open_settings_dialog)
        corner = QWidget()
        ch = QHBoxLayout(corner); ch.setContentsMargins(0, 2, 6, 2); ch.setSpacing(4)
        ch.addWidget(self.btn_settings)
        self.tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        # Единый стрип файлов — общий для всех вкладок (только медиа: видео/аудио/изображения)
        self.recent_strip = RecentFilesStrip(self, mode='media')
        l.addWidget(self.recent_strip)
        l.addWidget(self.tabs)

        self.pbar = QProgressBar(); self.pbar.setTextVisible(True); self.pbar.setFormat("Ожидание")
        self.pbar.setFixedHeight(22)
        l.addWidget(self.pbar)

        # Лог-консоль внизу окна. Показывается на всех вкладках, КРОМЕ «Монтаж»
        # (там она занимает место, нужное редактору) — скрывается при переходе
        # на вкладку монтажа, см. _sync_console_visibility.
        self.console_panel = QWidget(c)
        cpl = QVBoxLayout(self.console_panel)
        cpl.setContentsMargins(0, 0, 0, 0); cpl.setSpacing(2)

        self.txt_log = QTextEdit(self.console_panel); self.txt_log.setReadOnly(True)
        self.txt_log.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.txt_log.customContextMenuRequested.connect(self._log_context_menu)
        self.txt_log.setMaximumHeight(150)
        cpl.addWidget(self.txt_log)
        l.addWidget(self.console_panel)

        # Кнопка-значок «развернуть консоль» — поверх самой консоли, в правом
        # верхнем углу (как кнопка полноэкранного режима у видео).
        self.btn_open_console = QToolButton(self.txt_log)
        self.btn_open_console.setIcon(get_icon('fa5s.expand-alt'))
        self.btn_open_console.setIconSize(QSize(13, 13))
        self.btn_open_console.setToolTip("Развернуть консоль почти на всё окно")
        self.btn_open_console.setCursor(Qt.CursorShape.PointingHandCursor)
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

        # Вкладка «Промпт» (по умолчанию ВЫКЛ).
        self._prompt_tab_enabled = False

        try: self._load_settings()
        except Exception: pass

        self._attach_save_handlers()

        # Подключаем вкладку «Промпт», если включена в настройках.
        if getattr(self, "_prompt_tab_enabled", False):
            self._add_prompt_tab()

        # Подключаем экспериментальную вкладку SiQuester, если включена в настройках.
        if getattr(self, "_siquester_tab_enabled", False):
            self._add_siquester_tab()

        # …и вкладку ShikimoriHYX, если включена.
        if getattr(self, "_shikimori_tab_enabled", False):
            self._add_shikimori_tab()

        # Восстанавливаем сохранённый порядок вкладок (перетаскивание мышью).
        try:
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception:
            pass

        # Колёсико над полями не должно «активировать» их визуально (фокус по скроллу):
        # убираем WheelFocus у всех числовых полей/списков/ползунков во всех вкладках.
        try:
            for _w in (self.findChildren(QAbstractSpinBox)
                       + self.findChildren(QComboBox)
                       + self.findChildren(QSlider)):
                _w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        except Exception:
            pass

        # IPC-сервер: принимает файлы от нового запуска через ПКМ проводника
        self._ipc_server = QLocalServer(self)
        QLocalServer.removeServer("YasperMoglotIPC")
        self._ipc_server.listen("YasperMoglotIPC")
        self._ipc_server.newConnection.connect(self._on_ipc_connection)

        # HTTP-сервер: принимает URL от браузерного расширения (localhost:7432).
        # По умолчанию выключен — включается в Настройках.
        self.url_from_browser.connect(self._on_url_from_browser)
        if self._server_enabled:
            self._start_browser_http_server()

        # Тихая проверка обновлений при запуске (молча, если версия актуальна)
        self._updating = False
        QTimer.singleShot(2500, lambda: self._check_updates(silent=True))

    def add_paths(self, paths):
        """Роутит файлы из общего стрипа в активную вкладку."""
        current = self.tabs.currentWidget()
        if hasattr(current, 'add_paths') and current is not self:
            current.add_paths(paths)
        else:
            self.tab_media.add_paths(paths)

    def _load_settings(self):
        s = load_settings()
        tm = self.tab_media
        ty = self.tab_ytdlp
        self._server_enabled = bool(s.get("server_enabled", False))
        self._wheel_changes_values = bool(s.get("wheel_changes_values", False))
        self._video_software_render = bool(s.get("video_software_render", False))
        self._video_hw_decode = bool(s.get("video_hw_decode", True))
        self._siquester_tab_enabled = bool(s.get("siquester_tab_enabled", False))
        self._shikimori_tab_enabled = bool(s.get("shikimori_tab_enabled", False))
        self._shikimori_settings = dict(s.get("shikimori", {}) or {})
        self._prompt_tab_enabled = bool(s.get("prompt_tab_enabled", False))
        self._tab_order = list(s.get("tab_order", []) or [])
        try:
            m = s.get("media", {}); a = m.get("audio", {})
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

            v = m.get("video", {})
            tm.chk_enable_video.setChecked(v.get("enabled", True))
            tm.s_spd.setValue(v.get("speed", 100))
            tm.s_crf.setValue(v.get("crf", 45))
            tm.s_pre.setValue(v.get("pre", 1))
            combo_set_value(tm.c_res, v.get("res", "1280x720"))
            tm.c_fps.setCurrentText(v.get("fps", "Исходный (max 30)"))
            tm._set_preset_mode(v.get("preset_mode", "std"))
            tm.ck_vfade_in.setChecked(v.get("vfade_in", False))
            tm.s_vfade_in.setValue(v.get("vfade_in_d", 1.0))
            tm.ck_vfade_out.setChecked(v.get("vfade_out", False))
            tm.s_vfade_out.setValue(v.get("vfade_out_d", 1.0))

            # Папка экспорта (пусто = рядом с исходником)
            tm.export_dir = m.get("export_dir", "") or ""
            try: tm._update_export_label()
            except Exception: pass

            y = s.get("ytdlp", {})
            saved_outdir = y.get("outdir", "")
            if saved_outdir and os.path.isdir(saved_outdir):
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

            av = s.get("avif", {})
            tm.s_lim.setValue(av.get("limit", tm.s_lim.value()))
            tm.ck_lim.setChecked(av.get("limit_on", True))
            tm.s_lim.setEnabled(tm.ck_lim.isChecked())
            tm.s_dim.setValue(av.get("adim", tm.s_dim.value()))
            tm.ck_dim.setChecked(av.get("adim_on", False))
            tm.s_dim.setEnabled(tm.ck_dim.isChecked())
            tm.sl_aspd.setValue(av.get("aspd", tm.sl_aspd.value()))
            tm.s_passes.setValue(av.get("fit_passes", 4))
            try: tm.c_priority.setCurrentText(s.get("priority", "Обычный"))
            except Exception: pass
            if hasattr(tm, "ck_overwrite_src"):
                tm.ck_overwrite_src.setChecked(av.get("overwrite_src", False))
            combo_set_value(tm.c_img_fmt, av.get("img_fmt", "avif"))

            # Обновляем стрип последних файлов по восстановленной папке
            try:
                self.recent_strip.refresh(ty.out.text())
            except Exception: pass
        except Exception as e:
            self.log(f"_load_settings error: {e}")

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
            files = [f.strip() for f in data.splitlines() if f.strip() and os.path.exists(f.strip())]
            if files:
                self.raise_(); self.activateWindow()
                self.tabs.setCurrentWidget(self.tab_media)
                self.tab_media.add_paths(files)
                self.log(f"Добавлено через контекстное меню: {', '.join(os.path.basename(f) for f in files)}")
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
            self.raise_()
            self.activateWindow()
            self.tabs.setCurrentWidget(self.tab_ytdlp)
            self.tab_ytdlp.add_dl_direct(url, audio_only=audio)
            self.log(f"URL из браузера ({'аудио' if audio else 'видео'}): {url}")
        except Exception as e:
            self.log(f"_on_url_from_browser error: {e}")

    def _start_browser_http_server(self):
        """Запускает HTTP-сервер в фоновом потоке на localhost:7432.
        Расширение шлёт POST /download с телом {"url": "...", "audio": false}.
        Ответ всегда JSON, поддерживается CORS для chrome-extension://.
        Идемпотентно: повторный вызов при уже запущенном сервере ничего не делает.
        """
        if getattr(self, "_http_srv", None) is not None:
            return
        from http.server import HTTPServer, BaseHTTPRequestHandler
        win = self
        PORT = HTTP_PORT

        class _Handler(BaseHTTPRequestHandler):
            # Разрешаем только запросы из расширения браузера. Origin браузер
            # проставляет сам — со страницы его из JS не подделать, поэтому это
            # надёжно отсекает «любой сайт дёргает наши эндпоинты», не требуя
            # изменений в расширении (оно шлёт chrome-extension://… Origin).
            # fullmatch + строгий набор символов (без CR/LF и прочих управляющих)
            # — Origin отражается в заголовок ответа, поэтому он обязан быть без
            # переводов строки (защита от HTTP response splitting).
            _EXT_ORIGIN_RX = re.compile(
                r"(?:chrome-extension|moz-extension|safari-web-extension)://[A-Za-z0-9._-]+")

            def _req_origin(self) -> str:
                return self.headers.get("Origin", "") or ""

            def _safe_ext_origin(self) -> str:
                """Возвращает Origin, ТОЛЬКО если это origin расширения строгого
                формата (без управляющих символов). Иначе — пустую строку. Именно
                это значение можно безопасно отражать в заголовок."""
                origin = self._req_origin()
                if not origin or "\r" in origin or "\n" in origin:
                    return ""
                return origin if self._EXT_ORIGIN_RX.fullmatch(origin) else ""

            def _origin_allowed(self) -> bool:
                # Нет Origin → не веб-страница (нативный клиент/локальный инструмент)
                # — пропускаем (сервер и так слушает только 127.0.0.1). Иначе —
                # только строгий origin расширения.
                return not self._req_origin() or bool(self._safe_ext_origin())

            @staticmethod
            def _strip_crlf(value: str) -> str:
                """Удаляет любые CR/LF (и прочие управляющие) символы из значения
                перед записью в HTTP-заголовок — барьер против HTTP response
                splitting (CWE-113). Дублирует проверку в _safe_ext_origin, но
                делает безопасность явной в точке записи заголовка.

                Сначала явные str.replace по CR/LF (их распознаёт статанализ как
                санитайзер), затем re.sub добивает остальные управляющие символы."""
                value = (value or "").replace("\r", "").replace("\n", "")
                return re.sub(r"[\x00-\x1f]", "", value)

            def _send_cors(self):
                # ACAO отдаём только проверенному origin расширения (а не "*" и не
                # сырому заголовку), иначе браузер чужого сайта не прочитает ответ.
                safe_origin = self._strip_crlf(self._safe_ext_origin())
                # Барьер от HTTP response splitting (CWE-113) ИМЕННО в точке записи:
                # явная проверка на CR/LF в одной функции с send_header, чтобы её
                # видел и статанализ (его guard'ы межпроцедурно не прослеживаются —
                # проверки в _safe_ext_origin/_strip_crlf ему не видны отсюда).
                if safe_origin and "\r" not in safe_origin and "\n" not in safe_origin:
                    self.send_header("Access-Control-Allow-Origin", safe_origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")

            def _reject_foreign_origin(self) -> bool:
                """Если Origin чужой (обычный сайт) — отвечает 403 и возвращает
                True. Вызывать до любого действия с побочными эффектами."""
                if self._origin_allowed():
                    return False
                self.send_response(403)
                self._send_cors()
                self.end_headers()
                try:
                    self.wfile.write(b'{"ok":false,"error":"forbidden origin"}')
                except Exception:
                    pass
                return True

            def do_OPTIONS(self):
                self.send_response(200)
                self._send_cors()
                self.end_headers()

            # Лимит тела запроса — защита от исчерпания памяти (DoS): сервер
            # слушает только 127.0.0.1, но CORS=* => любой сайт может слать POST.
            _MAX_BODY = 64 * 1024 * 1024

            @staticmethod
            def _safe_name(name: str, fallback: str) -> str:
                """Жёсткая очистка имени файла от path traversal и спецсимволов:
                только basename, без разделителей пути и недопустимых для Windows
                символов; пустое/«.»/«..» → fallback."""
                name = os.path.basename((name or "").strip().replace("\\", "/").split("/")[-1])
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
                return name or fallback

            @staticmethod
            def _safe_out_path(out_dir: str, filename: str) -> str:
                """Строит путь записи внутри out_dir и нормализацией+проверкой
                префикса гарантирует, что результат не выходит за пределы out_dir
                (защита от path traversal, CWE-22). filename уже очищен
                _safe_name, но явная проверка не зависит от его реализации."""
                base = os.path.realpath(out_dir)
                full = os.path.realpath(os.path.join(base, os.path.basename(filename)))
                if not full.startswith(base + os.sep):
                    raise ValueError("path traversal blocked")
                return full

            def do_POST(self):
                try:
                    # Отсекаем запросы со сторонних сайтов до любых действий.
                    if self._reject_foreign_origin():
                        return
                    try:
                        length = int(self.headers.get("Content-Length", 0))
                    except (TypeError, ValueError):
                        length = 0
                    if length < 0 or length > self._MAX_BODY:
                        self.send_response(413); self._send_cors(); self.end_headers()
                        self.wfile.write(b'{"ok":false,"error":"body too large"}'); return

                    # ── /screenshot — тело бинарное (PNG), читаем ДО json.loads ──
                    if self.path == "/screenshot":
                        img_bytes = self.rfile.read(length)
                        from urllib.parse import unquote
                        filename = unquote(self.headers.get("X-Filename", "screenshot.png"))
                        filename = self._safe_name(filename, "screenshot.png")  # защита от path traversal (CWE-22)
                        if not img_bytes:
                            self.send_response(400); self._send_cors(); self.end_headers()
                            self.wfile.write(b'{"ok":false,"error":"empty body"}'); return
                        try:
                            out_dir = win.tab_ytdlp.out.text().strip()
                        except Exception:
                            out_dir = ""
                        if not out_dir or not os.path.isdir(out_dir):
                            out_dir = str(Path.home())
                        out_path = self._safe_out_path(out_dir, filename)
                        if os.path.exists(out_path):
                            base_n, ext_n = os.path.splitext(filename)
                            out_path = self._safe_out_path(out_dir, f"{base_n}_{int(time.time())}{ext_n}")
                        with open(out_path, "wb") as fout:
                            fout.write(img_bytes)
                        win.url_from_browser.emit(f"__screenshot_saved__{out_path}", False)
                        self.send_response(200); self._send_cors()
                        self.send_header("Content-Type", "application/json"); self.end_headers()
                        self.wfile.write(json.dumps({"ok": True, "path": out_path}).encode())
                        return

                    # Для остальных эндпоинтов — JSON
                    body = self.rfile.read(length).decode("utf-8", errors="replace")
                    data = json.loads(body)

                    # ── /save_image — скачать картинку по URL ────────────────
                    if self.path == "/save_image":
                        img_url  = (data.get("url") or "").strip()
                        filename = (data.get("filename") or "image.jpg").strip()
                        filename = self._safe_name(filename, "image.jpg")  # защита от path traversal (CWE-22)
                        if not img_url:
                            self.send_response(400); self._send_cors(); self.end_headers()
                            self.wfile.write(b'{"ok":false,"error":"empty url"}'); return
                        # Только http(s): блокируем file://, ftp://, data: и прочие
                        # схемы (защита от SSRF/чтения локальных файлов через сервер).
                        if not re.match(r'^https?://', img_url, re.I):
                            self.send_response(400); self._send_cors(); self.end_headers()
                            self.wfile.write(b'{"ok":false,"error":"only http(s) urls allowed"}'); return
                        try:
                            out_dir = win.tab_ytdlp.out.text().strip()
                        except Exception:
                            out_dir = ""
                        if not out_dir or not os.path.isdir(out_dir):
                            out_dir = str(Path.home())
                        out_path = self._safe_out_path(out_dir, filename)
                        if os.path.exists(out_path):
                            base_n, ext_n = os.path.splitext(filename)
                            out_path = self._safe_out_path(out_dir, f"{base_n}_{int(time.time())}{ext_n}")
                        with http_get(img_url, headers={"User-Agent": USER_AGENT, "Referer": img_url}, timeout=30) as resp:
                            img_bytes = resp.read(200 * 1024 * 1024)  # лимит 200 МБ
                        with open(out_path, "wb") as fout:
                            fout.write(img_bytes)
                        win.url_from_browser.emit(f"__screenshot_saved__{out_path}", False)
                        self.send_response(200); self._send_cors()
                        self.send_header("Content-Type", "application/json"); self.end_headers()
                        self.wfile.write(json.dumps({"ok": True, "path": out_path}).encode())
                        return

                    # ── /download — скачать видео/аудио ──────────────────────
                    url = (data.get("url") or "").strip()
                    audio = bool(data.get("audio", False))
                    if url:
                        win.url_from_browser.emit(url, audio)
                        self.send_response(200)
                        self._send_cors()
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"ok":true}')
                    else:
                        self.send_response(400)
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(b'{"ok":false,"error":"empty url"}')
                except Exception as ex:
                    try:
                        self.send_response(500)
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": False, "error": str(ex)}).encode())
                    except Exception:
                        pass

            def log_message(self, fmt, *args):  # заглушаем вывод в консоль
                pass

        try:
            srv = HTTPServer(("127.0.0.1", PORT), _Handler)
        except OSError as e:
            self._http_srv = None
            self.log(f"Не удалось запустить сервер на :{PORT} ({e}). Возможно, порт занят.")
            return
        self._http_srv = srv
        t = threading.Thread(target=srv.serve_forever, daemon=True, name="BrowserHTTP")
        t.start()
        self._http_thread = t
        self.log(f"Сервер для браузерного расширения запущен: localhost:{PORT}")

    def _stop_browser_http_server(self):
        """Останавливает HTTP-сервер расширения (если запущен)."""
        srv = getattr(self, "_http_srv", None)
        if srv is None:
            return
        try:
            srv.shutdown(); srv.server_close()
        except Exception:
            pass
        self._http_srv = None
        self._http_thread = None
        self.log("Сервер для браузерного расширения остановлен.")

    def _set_server_enabled(self, checked: bool):
        self._server_enabled = bool(checked)
        if checked:
            self._start_browser_http_server()
        else:
            self._stop_browser_http_server()
        try: self._save_settings_now()
        except Exception: pass

    def _set_wheel_changes_values(self, checked: bool):
        self._wheel_changes_values = bool(checked)
        try: self._save_settings_now()
        except Exception: pass

    def _set_video_software_render(self, checked: bool):
        self._video_software_render = bool(checked)
        try: self._save_settings_now()
        except Exception: pass

    def _set_video_hw_decode(self, checked: bool):
        self._video_hw_decode = bool(checked)
        try: self._save_settings_now()
        except Exception: pass

    # ------------------------------------------------------------------
    # Вкладки: подсказки (ⓘ) и сохраняемый порядок (drag-n-drop)
    # ------------------------------------------------------------------
    def _add_tab(self, widget, key):
        """Добавляет вкладку с заголовком и значком ⓘ (тот же info_badge с
        всплывающей подсказкой, что и внутри первых двух вкладок — см. widgets.py).
        objectName вида 'tab::<key>' нужен для сохранения порядка вкладок."""
        icon_name, title, tip = self._tab_info.get(key, (None, key, ""))
        try:
            widget.setObjectName(f"tab::{key}")
        except Exception:
            pass
        if icon_name:
            idx = self.tabs.addTab(widget, get_icon(icon_name), title)
        else:
            idx = self.tabs.addTab(widget, title)
        # Значок ⓘ — отдельным виджетом на самой вкладке (как info_badge в формах),
        # с фирменным попапом-подсказкой вместо системного тултипа.
        try:
            badge = info_badge(tip)
            badge.setStyleSheet("#infoBadge{color:#89b4fa;}")
            # Бейдж ⓘ (16×16, значок 13px по центру) визуально садится на ~1px
            # ниже центра текста вкладки. Нижний отступ сдвигает значок вверх,
            # чтобы он встал на одну высоту с надписью (и с левым значком вкладки).
            badge.setContentsMargins(0, 0, 0, 2)
            self.tabs.tabBar().setTabButton(
                idx, QTabBar.ButtonPosition.RightSide, badge)
        except Exception:
            self.tabs.setTabToolTip(idx, tip)
        return idx

    def _on_tab_moved(self, *args):
        # Пользователь перетащил вкладку — сохраняем порядок (но не во время
        # программной перестановки в _apply_tab_order).
        if getattr(self, "_reordering_tabs", False):
            return
        self._save_tab_order()

    def _save_tab_order(self):
        order = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            on = w.objectName() if w is not None else ""
            if on.startswith("tab::"):
                order.append(on[len("tab::"):])
        self._tab_order = order
        try: self._save_settings_now()
        except Exception: pass

    def _apply_tab_order(self, order):
        """Переставляет вкладки согласно сохранённому порядку ключей. Двигаем
        через tabBar().moveTab (QTabWidget сам синхронизирует страницы по сигналу
        tabMoved), а от рекурсивного сохранения защищаемся флагом."""
        if not order:
            return
        bar = self.tabs.tabBar()
        self._reordering_tabs = True
        try:
            target = 0
            for key in order:
                name = f"tab::{key}"
                for i in range(self.tabs.count()):
                    w = self.tabs.widget(i)
                    if w is not None and w.objectName() == name:
                        if i != target:
                            bar.moveTab(i, target)
                        target += 1
                        break
        finally:
            self._reordering_tabs = False

    # ------------------------------------------------------------------
    # Вкладка «Промпт» (включается/выключается в Настройках, по умолч. ВЫКЛ)
    # ------------------------------------------------------------------
    def _add_prompt_tab(self):
        """Добавляет вкладку «Промпт» в таббар (если ещё не добавлена). Сам
        объект self.tab_prompt создаётся в __init__ — здесь только показ."""
        t = getattr(self, "tab_prompt", None)
        if t is None or self.tabs.indexOf(t) >= 0:
            return
        self._add_tab(t, 'prompt')
        try:
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception:
            pass

    def _remove_prompt_tab(self):
        t = getattr(self, "tab_prompt", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            # removeTab оставляет виджет дочерним к таббару — снова прячем, чтобы
            # он не всплыл в углу окна.
            t.setParent(self)
            t.hide()
        except Exception:
            pass

    def _set_prompt_tab_enabled(self, checked: bool):
        self._prompt_tab_enabled = bool(checked)
        if checked:
            self._add_prompt_tab()
        else:
            self._remove_prompt_tab()
        try: self._save_settings_now()
        except Exception: pass

    # ------------------------------------------------------------------
    # Экспериментальная вкладка SiQuester (просмотр .siq + статистика)
    # ------------------------------------------------------------------
    def _add_siquester_tab(self):
        """Создаёт и добавляет вкладку SiQuester (если ещё не добавлена).
        Импорт ленивый — пакет siquester тянет QtMultimedia и грузится только
        когда вкладка включена."""
        if getattr(self, "tab_siquester", None) is not None:
            return
        try:
            from siquester_tab import SiQuesterTab
            self.tab_siquester = SiQuesterTab(self)
            self._add_tab(self.tab_siquester, 'siquester')
            # Сохранённый порядок мог включать эту вкладку — применяем заново.
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception as e:
            self.tab_siquester = None
            self.log(f"Не удалось добавить вкладку SiQuester: {e}")

    def _remove_siquester_tab(self):
        t = getattr(self, "tab_siquester", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            try: t.cleanup()
            except Exception: pass
            t.deleteLater()
        except Exception: pass
        self.tab_siquester = None

    def _set_siquester_tab_enabled(self, checked: bool):
        self._siquester_tab_enabled = bool(checked)
        if checked:
            self._add_siquester_tab()
        else:
            self._remove_siquester_tab()
        try: self._save_settings_now()
        except Exception: pass

    # ------------------------------------------------------------------
    # Экспериментальная вкладка ShikimoriHYX (поиск аниме через Shikimori API)
    # ------------------------------------------------------------------
    def _add_shikimori_tab(self):
        """Создаёт и добавляет вкладку ShikimoriHYX (если ещё не добавлена).
        Импорт ленивый — модуль тянется только когда вкладка включена."""
        if getattr(self, "tab_shikimori", None) is not None:
            return
        try:
            from shikimori_tab import ShikimoriTab
            self.tab_shikimori = ShikimoriTab(self)
            self._add_tab(self.tab_shikimori, 'shikimori')
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception as e:
            self.tab_shikimori = None
            self.log(f"Не удалось добавить вкладку ShikimoriHYX: {e}")

    def _remove_shikimori_tab(self):
        t = getattr(self, "tab_shikimori", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            try: t.cleanup()
            except Exception: pass
            t.deleteLater()
        except Exception: pass
        self.tab_shikimori = None

    def _set_shikimori_tab_enabled(self, checked: bool):
        self._shikimori_tab_enabled = bool(checked)
        if checked:
            self._add_shikimori_tab()
        else:
            # Перед закрытием запоминаем текущие фильтры вкладки.
            self._shikimori_settings = self._collect_shikimori_settings()
            self._remove_shikimori_tab()
        try: self._save_settings_now()
        except Exception: pass

    def _collect_shikimori_settings(self):
        """Актуальные настройки вкладки ShikimoriHYX (или последние сохранённые,
        если вкладка сейчас не открыта)."""
        t = getattr(self, "tab_shikimori", None)
        if t is not None and hasattr(t, "get_settings"):
            try:
                return t.get_settings()
            except Exception:
                pass
        return dict(getattr(self, "_shikimori_settings", {}) or {})

    def _open_url(self, url: str):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            self.log(f"Не удалось открыть ссылку: {e}")

    def _update_ytdlp(self):
        """Обновляет yt-dlp.exe до последнего NIGHTLY (работает только для
        standalone-exe). Именно nightly первым получает исправления экстракторов,
        когда TikTok/YouTube ломают разметку (стабильный канал отстаёт на недели).
        `--update-to nightly` и переключает канал, и обновляет за один шаг —
        повторные нажатия тянут свежий nightly.

        ПРИМЕЧАНИЕ: ошибка TikTok «universal data for rehydration» — НЕ про версию.
        Это флапающий JS-challenge (~60% запусков отдают пустую страницу,
        НЕЗАВИСИМО от версии/UA/cookies). Лечится ПОВТОРАМИ процесса в workers.py
        (InfoWorker и YtdlpWorker), а не обновлением — см. там."""
        base = ytdlp_base_cmd()
        if not base:
            self.log("yt-dlp не найден — положите yt-dlp.exe в папку bin рядом с программой.")
            return
        if len(base) != 1:
            self.log("Обновление доступно только для bin/yt-dlp.exe "
                     "(в dev-режиме используется pip-версия: обновляйте через `pip install -U yt-dlp`).")
            return
        exe = base[0]
        self.log("Обновляю yt-dlp (nightly)…")

        def _run():
            try:
                p = subprocess.run([exe, "--update-to", "nightly"],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=CREATE_NO_WINDOW, timeout=180)
                for ln in (p.stdout or "").splitlines():
                    if ln.strip():
                        self.log_signal.emit(ln.strip())
                self.log_signal.emit("Готово (обновление yt-dlp).")
            except Exception as e:
                self.log_signal.emit(f"Ошибка обновления yt-dlp: {e}")

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Автообновление через GitHub Releases
    # ------------------------------------------------------------------
    def _check_updates(self, silent: bool = True):
        """Опрашивает GitHub API о последнем релизе. Если он новее текущей
        версии — эмитит update_available_sig (показ диалога на GUI-потоке)."""
        def _run():
            try:
                # Берём СПИСОК релизов (а не /latest), чтобы учитывать и
                # pre-release (beta), которые /latest пропускает.
                api = (f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
                       f"/releases?per_page=10")
                with http_get(api, headers={
                    "User-Agent": APP_NAME,
                    "Accept": "application/vnd.github+json",
                }, timeout=15, allow_insecure=False) as r:
                    releases = json.loads(r.read().decode("utf-8", "replace"))
                if not isinstance(releases, list):
                    releases = []

                # Находим самый свежий не-черновик с zip-ассетом и наибольшей версией
                best_tag, best_ver, best_rel = "", (0,), None
                for rel in releases:
                    if rel.get("draft"):
                        continue
                    tag = rel.get("tag_name") or rel.get("name") or ""
                    ver = parse_version(tag)
                    has_zip = any(str(a.get("name", "")).lower().endswith(".zip")
                                  for a in rel.get("assets", []))
                    if has_zip and ver > best_ver:
                        best_ver, best_tag, best_rel = ver, tag, rel

                if best_rel is not None and best_ver > parse_version(APP_VERSION):
                    # Выбираем ассет умно: только код (update-архив), если bin не
                    # менялся, иначе полный zip (см. _pick_update_asset). Третьим
                    # элементом — ожидаемый sha256 для проверки после загрузки.
                    best_url, best_size, best_sha = self._pick_update_asset(best_rel)
                    if best_url:
                        # запоминаем, тихая ли это проверка — слот решает, уважать ли «пропуск»
                        self._check_was_silent = silent
                        self.update_available_sig.emit(best_tag, best_url, best_size, best_sha)
                    elif not silent:
                        self.log_signal.emit("Обновление найдено, но подходящий ассет не найден.")
                elif not silent:
                    self.log_signal.emit(
                        f"Обновлений нет. Текущая версия: {APP_VERSION}"
                        f" (последняя: {best_tag or '—'}).")
            except Exception as e:
                if not silent:
                    self.log_signal.emit(f"Не удалось проверить обновления: {e}")

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _local_bin_sha() -> str:
        """Хеш текущего набора bin — читаем из bin/.binver рядом с программой.
        Пусто, если файла нет (старая установка без манифеста) → значит «bin
        неизвестен», и обновление возьмёт полный zip."""
        try:
            if getattr(sys, "frozen", False):
                app_dir = os.path.dirname(os.path.abspath(sys.executable))
            else:
                app_dir = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(app_dir, "bin", ".binver"), encoding="ascii") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _pick_update_asset(self, rel):
        """Решает, что качать из релиза, экономя трафик:
        • update-архив (только код, ~десятки МБ) — если bin не изменился
          (manifest.bin_sha == локальный bin/.binver);
        • full-архив (код + bin, ~сотни МБ) — если bin изменился, либо релиз
          старого формата (нет manifest.json / update-архива).
        Возвращает (url, size_bytes, sha256). sha256 — ожидаемый хеш выбранного
        архива из manifest (для проверки после загрузки); "" если проверить
        нечем (старый формат / нет хеша в manifest)."""
        assets = rel.get("assets", [])

        def by(pred):
            return next((a for a in assets if pred(str(a.get("name", "")).lower())), None)

        # update-архив: префикс "updatehyx" (новое имя UpdateHYX-vX.Y.Z.zip) +
        # легаси-префикс "hyxupdate" (старое имя) и суффиксы
        # "-update.zip"/"-app.zip"/"app.zip".
        def is_update(n):
            return (n.startswith("updatehyx") or n.startswith("hyxupdate")
                    or n.endswith("-update.zip")
                    or n.endswith("-app.zip") or n == "app.zip")
        update_asset = by(is_update)
        full_asset   = by(lambda n: n.endswith(".zip") and not is_update(n))
        manifest     = by(lambda n: n == "manifest.json")

        # Старый формат релиза (нет update-архива/manifest) → поведение как раньше:
        # берём полный (первый не-update) zip, а если такого нет — любой .zip.
        # Проверить целостность нечем → sha = "".
        if not update_asset or not manifest:
            z = full_asset or by(lambda n: n.endswith(".zip"))
            return (z.get("browser_download_url", ""), int(z.get("size", 0) or 0), "") if z else ("", 0, "")

        # Читаем manifest: bin_sha (что качать) + update_sha/full_sha (что проверять).
        man = {}
        try:
            with http_get(manifest.get("browser_download_url", ""),
                          headers={"User-Agent": APP_NAME}, timeout=15,
                          allow_insecure=False) as r:
                man = json.loads(r.read().decode("utf-8", "replace")) or {}
        except Exception:
            man = {}
        remote_bin_sha = man.get("bin_sha", "") or ""

        bin_unchanged = bool(remote_bin_sha) and remote_bin_sha == self._local_bin_sha()
        if bin_unchanged and update_asset:
            self.log_signal.emit("Обновление: bin не изменился — качаем только update-часть (меньше трафика).")
            chosen, sha = update_asset, (man.get("update_sha", "") or "")
        else:
            chosen = full_asset or update_asset
            sha = (man.get("full_sha", "") or "") if chosen is full_asset else (man.get("update_sha", "") or "")
        return (chosen.get("browser_download_url", ""), int(chosen.get("size", 0) or 0), sha) if chosen else ("", 0, "")

    def _skip_file(self):
        return os.path.join(CONFIG_DIR, "skipped_update.txt")

    def _load_skipped_version(self):
        try:
            with open(self._skip_file(), encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _save_skipped_version(self, version: str):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(self._skip_file(), "w", encoding="utf-8") as f:
                f.write(version or "")
        except Exception:
            pass

    def _on_banner_skip(self):
        """«Пропустить версию»: запоминаем версию — авто-проверка её больше не
        предлагает (ручная «Проверить обновления» всё равно покажет)."""
        ver = self._pending_update_version
        self._skipped_update_version = ver
        self._save_skipped_version(ver)
        self.update_banner.setVisible(False)
        if ver:
            self.log(f"Версия {ver} пропущена. Предложу обновиться при следующем релизе "
                     f"(или нажмите «Проверить обновления» вручную).")

    def _on_update_available(self, version: str, url: str, size: int, sha: str = ""):
        if getattr(self, "_updating", False):
            return
        # Пропущенную версию не показываем при ТИХОЙ (авто) проверке; ручная
        # проверка («Проверить обновления») показывает баннер всегда.
        if (version and version == self._skipped_update_version
                and getattr(self, "_check_was_silent", True)):
            return
        if not getattr(sys, "frozen", False):
            self.log(f"Доступна новая версия {version}, но автоустановка работает "
                     f"только в собранной программе (.exe). Скачайте вручную.")
            return
        sz = f"~{size/1024/1024:.0f} МБ" if size else "размер неизвестен"
        self._pending_update_url = url
        self._pending_update_version = version
        self._pending_update_sha = sha or ""
        self.update_banner_lbl.setText(
            f"Доступна новая версия {version} ({sz}). "
            f"Программа обновится и перезапустится.")
        self.update_banner.setVisible(True)

    def _on_banner_update(self):
        self.update_banner.setVisible(False)
        if self._pending_update_url:
            self._start_update_download(self._pending_update_url)

    def _start_update_download(self, url: str):
        if getattr(self, "_updating", False):
            return
        self._updating = True
        self.log("Скачивание обновления…")

        def _run():
            try:
                tmp = os.path.join(tempfile.gettempdir(), "sihyx_update")
                shutil.rmtree(tmp, ignore_errors=True)
                os.makedirs(tmp, exist_ok=True)
                zip_path = os.path.join(tmp, "update.zip")

                with http_get(url, headers={"User-Agent": APP_NAME}, timeout=60,
                              allow_insecure=False) as r:
                    total = int(r.headers.get("Content-Length", 0) or 0)
                    done = 0
                    last_pct = -1
                    with open(zip_path, "wb") as f:
                        while True:
                            chunk = r.read(262144)
                            if not chunk:
                                break
                            f.write(chunk)
                            done += len(chunk)
                            if total:
                                pct = done * 100 // total
                                if pct != last_pct and pct % 5 == 0:
                                    last_pct = pct
                                    self.log_signal.emit(f"Загрузка обновления: {pct}%")

                # Проверка целостности: сверяем sha256 загруженного архива с
                # ожидаемым из manifest. Битый/подменённый zip не распаковываем.
                expected_sha = (getattr(self, "_pending_update_sha", "") or "").lower()
                if expected_sha:
                    h = hashlib.sha256()
                    with open(zip_path, "rb") as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), b""):
                            h.update(chunk)
                    actual_sha = h.hexdigest()
                    if actual_sha != expected_sha:
                        self.log_signal.emit(
                            "Ошибка обновления: контрольная сумма архива не совпала "
                            "(файл повреждён или подменён). Установка отменена.")
                        self._updating = False
                        return
                    self.log_signal.emit("Контрольная сумма архива подтверждена.")

                self.log_signal.emit("Распаковка обновления…")
                extract_dir = os.path.join(tmp, "extracted")
                import zipfile
                with zipfile.ZipFile(zip_path) as z:
                    z.extractall(extract_dir)

                src_root = self._find_exe_root(extract_dir)
                if not src_root:
                    self.log_signal.emit("Ошибка обновления: в архиве не найден "
                                         f"{APP_NAME}.exe.")
                    self._updating = False
                    return
                self.update_ready_sig.emit(src_root)
            except Exception as e:
                self.log_signal.emit(f"Ошибка обновления: {e}")
                self._updating = False

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _find_exe_root(root: str):
        """Ищет каталог, в котором лежит SI-HYX.exe, внутри распакованного архива."""
        target = APP_NAME + ".exe"
        for dirpath, _dirs, files in os.walk(root):
            if target in files:
                return dirpath
        return None

    def _apply_update(self, src_root: str):
        """Готовит апдейтер и запускает его ВНЕ job-объекта программы через
        Планировщик задач, затем закрывает программу. В Win Sandbox/жёстких
        лаунчерах обычный detached-процесс убивается job'ом при выходе родителя
        (апдейтер не стартовал — не было даже update_log.txt). Планировщик
        исполняет задачу в своей сессии-службе, job родителя на неё не влияет.
        Лог апдейтера: %TEMP%\\sihyx_update\\update_log.txt."""
        try:
            app_dir = os.path.dirname(os.path.abspath(sys.executable))
            exe_path = os.path.abspath(sys.executable)
            upd_dir = os.path.join(tempfile.gettempdir(), "sihyx_update")
            os.makedirs(upd_dir, exist_ok=True)
            ps_path = os.path.join(upd_dir, "apply_update.ps1")
            cmd_path = os.path.join(upd_dir, "run_updater.cmd")
            log_path = os.path.join(upd_dir, "update_log.txt")
            lock_path = os.path.join(upd_dir, "updater.lock")
            for _p in (log_path, lock_path):
                try:
                    if os.path.exists(_p): os.remove(_p)
                except Exception: pass

            def q(s):  # безопасная одинарно-кавыченная строка PowerShell
                return "'" + str(s).replace("'", "''") + "'"

            task_name = "SIHYX_SelfUpdate"
            launch_task = task_name + "_Launch"
            relaunch_path = os.path.join(upd_dir, "relaunch.cmd")
            register_path = os.path.join(upd_dir, "register.cmd")
            leaf = os.path.basename(exe_path)
            src_exe = os.path.join(src_root, leaf)
            # Время триггера задач (в будущем). Реально задачи запускаются через
            # schtasks /Run; авто-срабатывание по /ST безвредно — у программы
            # single-instance (повторный старт просто закроется).
            st = time.strftime("%H:%M", time.localtime(time.time() + 120))

            # Параметры «зашиты» в скрипт (а не через -args) — запускается и
            # Планировщиком, и напрямую, без возни с кавычками в путях.
            hdr = (
                "$AppPid=" + str(int(os.getpid())) + "\n"
                "$Src=" + q(src_root) + "\n"
                "$Dst=" + q(app_dir) + "\n"
                "$Exe=" + q(exe_path) + "\n"
                "$Log=" + q(log_path) + "\n"
                "$Lock=" + q(lock_path) + "\n"
                "$TaskName=" + q(task_name) + "\n"
                "$RelaunchCmd=" + q(relaunch_path) + "\n"
            )
            body = (
                "$ErrorActionPreference='SilentlyContinue'\n"
                "function W($m){ \"$([DateTime]::Now.ToString('HH:mm:ss')) $m\" | "
                "Out-File -FilePath $Log -Append -Encoding utf8 }\n"
                # защита от двойного запуска (ручной /Run + срабатывание по времени)
                "if(Test-Path $Lock){ exit }\n"
                "New-Item -ItemType File -Path $Lock -Force | Out-Null\n"
                "W 'Updater started.'\n"
                "W \"AppPid=$AppPid\"; W \"Src=$Src\"; W \"Dst=$Dst\"; W \"Exe=$Exe\"\n"
                "# 1) Ждём выхода процесса программы (до ~30 сек)\n"
                "for($i=0; $i -lt 30; $i++){ if(-not (Get-Process -Id $AppPid -ErrorAction SilentlyContinue)){ break }; Start-Sleep -Milliseconds 1000 }\n"
                "# 2) Ждём, пока .exe реально освободится\n"
                "$free=$false\n"
                "if(-not (Test-Path $Exe)){ $free=$true }\n"
                "for($i=0; ($i -lt 60) -and (-not $free); $i++){ try { $fs=[System.IO.File]::Open($Exe,'Open','ReadWrite','None'); $fs.Close(); $free=$true; break } catch { Start-Sleep -Milliseconds 500 } }\n"
                "W \"Exe free=$free\"\n"
                "Start-Sleep -Milliseconds 500\n"
                "# 3) Копируем новую версию поверх старой (с ретраями)\n"
                "$ok=$false\n"
                "for($try=1; $try -le 12; $try++){ robocopy $Src $Dst /E /IS /IT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null; $rc=$LASTEXITCODE; W \"robocopy try $try rc=$rc\"; if($rc -lt 8){ $ok=$true; break }; Start-Sleep -Seconds 2 }\n"
                "if($ok){ W 'Copy OK.' } else { W 'Copy FAILED (robocopy rc>=8).' }\n"
                "# 4) Перезапуск новой версии ОТДЕЛЬНОЙ задачей (relaunch.cmd).\n"
                "#    Планировщик убивает ВСЁ дерево процессов завершившейся задачи —\n"
                "#    поэтому запускать приложение из самой задачи-апдейтера нельзя\n"
                "#    (новая версия тут же умрёт). Отдельная задача делает приложение\n"
                "#    своим ГЛАВНЫМ процессом → оно живёт и стартует в интерактивной\n"
                "#    сессии (видимое окно).\n"
                "try { Start-Process -FilePath $RelaunchCmd -Wait -WindowStyle Hidden; W 'Relaunch task triggered.' } catch { W \"Relaunch failed: $_\" }\n"
                "W 'Done.'\n"
                "Remove-Item $Lock -Force -ErrorAction SilentlyContinue\n"
                "schtasks /Delete /TN $TaskName /F | Out-Null\n"
            )
            with open(ps_path, "w", encoding="utf-8-sig") as f:
                f.write(hdr + body)
            # run_updater.cmd — действие задачи-апдейтера (находит ps1 рядом, %~dp0)
            with open(cmd_path, "w", encoding="ascii", errors="replace") as f:
                f.write("@echo off\r\n"
                        "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden "
                        "-File \"%~dp0apply_update.ps1\"\r\n")
            # relaunch.cmd — регистрирует и запускает ОТДЕЛЬНУЮ задачу-лаунчер,
            # действие которой = сам .exe (он становится главным процессом задачи
            # → переживает завершение задачи-апдейтера). Кавычки form2: /TR "\"path\""
            # — единственная форма, что работает для путей с пробелами (проверено).
            with open(relaunch_path, "w", encoding="ascii", errors="replace") as f:
                f.write("@echo off\r\n"
                        'set "EXE=' + exe_path + '"\r\n'
                        'if not exist "%EXE%" set "EXE=' + src_exe + '"\r\n'
                        'schtasks /Create /F /TN "' + launch_task + '" /TR "\\"%EXE%\\"" '
                        '/SC ONCE /ST ' + st + ' /RL LIMITED >nul 2>&1\r\n'
                        'schtasks /Run /TN "' + launch_task + '" >nul 2>&1\r\n')
            # register.cmd — регистрирует и запускает задачу-апдейтер (form2-кавычки)
            with open(register_path, "w", encoding="ascii", errors="replace") as f:
                f.write("@echo off\r\n"
                        'schtasks /Create /F /TN "' + task_name + '" /TR "\\"' + cmd_path + '\\"" '
                        '/SC ONCE /ST ' + st + ' /RL LIMITED >nul 2>&1\r\n'
                        'schtasks /Run /TN "' + task_name + '" >nul 2>&1\r\n')

            if not self._spawn_updater(task_name, register_path, ps_path):
                self._updating = False
                self.log("Не удалось запустить апдейтер. Обновите вручную из папки: " + src_root)
                return

            self.log(f"Обновление готово. Перезапуск… (лог: {log_path})")
            # ЖЁСТКО завершаем процесс: QApplication.quit() не всегда освобождает
            # файлы (живут Qt-потоки/серверы) → robocopy не перезапишет залоченный exe.
            try: self._save_settings_now()
            except Exception: pass
            try: self._stop_browser_http_server()
            except Exception: pass
            QTimer.singleShot(700, lambda: os._exit(0))
        except Exception as e:
            self._updating = False
            self.log(f"Ошибка применения обновления: {e}")

    def _spawn_updater(self, task_name, register_cmd, ps_path):
        """Запускает апдейтер ВНЕ job-объекта программы. Основной путь —
        Планировщик задач через register.cmd (служба исполняет задачу в своей
        сессии, job родителя на неё не влияет — работает даже в Win Sandbox).
        Фолбэк — обычный detached Popen (+breakaway) для машин без жёсткого job."""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # 1) Планировщик задач (register.cmd сам делает /Create и /Run)
        try:
            subprocess.run(["cmd", "/c", register_cmd], creationflags=flags,
                           capture_output=True, text=True, timeout=30)
            chk = subprocess.run(["schtasks", "/Query", "/TN", task_name],
                                 creationflags=flags, capture_output=True, text=True, timeout=15)
            if chk.returncode == 0:
                self.log("Апдейтер запущен через Планировщик задач (вне job-объекта).")
                return True
            self.log("Планировщик: задача не зарегистрирована — пробую прямой запуск.")
        except Exception as e:
            self.log(f"Планировщик задач недоступен ({e}); пробую прямой запуск.")
        # 2) Фолбэк: detached Popen (+breakaway) — для обычных машин без жёсткого job
        try:
            DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0)
            NEWGRP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
            args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-WindowStyle", "Hidden", "-File", ps_path]
            try:
                subprocess.Popen(args, creationflags=DETACHED | NEWGRP | BREAKAWAY, close_fds=True)
            except OSError:
                subprocess.Popen(args, creationflags=DETACHED | NEWGRP, close_fds=True)
            self.log("Апдейтер запущен напрямую (detached).")
            return True
        except Exception as e:
            self.log(f"Не удалось запустить апдейтер: {e}")
            return False

    def _open_settings_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Настройки — " + APP_TITLE)
        dlg.setMinimumSize(680, 520)
        outer = QVBoxLayout(dlg); outer.setSpacing(10); outer.setContentsMargins(12, 12, 12, 12)

        # ── Поиск по настройкам ──────────────────────────────────────────────
        search = QLineEdit()
        search.setPlaceholderText("Поиск настроек…")
        search.addAction(get_icon('fa5s.search'),
                         QLineEdit.ActionPosition.LeadingPosition)
        search.setClearButtonEnabled(True)
        outer.addWidget(search)

        body = QHBoxLayout(); body.setSpacing(10)
        outer.addLayout(body, 1)

        # ── Левая навигация (категории) ──────────────────────────────────────
        nav = QListWidget()
        nav.setFixedWidth(160)
        nav.setStyleSheet(
            "QListWidget{background:#181825;border:1px solid #45475a;border-radius:6px;"
            "padding:4px;outline:none;}"
            "QListWidget::item{padding:8px 10px;border-radius:5px;color:#cdd6f4;}"
            "QListWidget::item:selected{background:#89b4fa;color:#1e1e2e;font-weight:bold;}"
            "QListWidget::item:hover:!selected{background:#313244;}")
        body.addWidget(nav)

        # ── Правая прокручиваемая область со всеми секциями ───────────────────
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(); content_l = QVBoxLayout(content)
        content_l.setContentsMargins(4, 4, 8, 4); content_l.setSpacing(14)
        scroll.setWidget(content)
        body.addWidget(scroll, 1)

        sections = []  # [{'name','widget','header','layout','rows':[(w,keywords)]}]

        def make_section(name):
            sec = QWidget()
            secl = QVBoxLayout(sec); secl.setContentsMargins(0, 0, 0, 0); secl.setSpacing(10)
            hdr = QLabel(name)
            hdr.setStyleSheet("font-size:16px; font-weight:bold; color:#89b4fa; padding-top:2px;")
            secl.addWidget(hdr)
            rec = {'name': name, 'widget': sec, 'header': hdr, 'layout': secl, 'rows': []}
            sections.append(rec)
            content_l.addWidget(sec)
            nav.addItem(name)
            return rec

        def add_row(rec, widget, keywords=""):
            rec['layout'].addWidget(widget)
            rec['rows'].append((widget, (rec['name'] + " " + keywords).lower()))

        def hint(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("color:#a6adc8; font-size:11px;")
            lbl.setWordWrap(True)
            return lbl

        # ══ Секция «Основное» ════════════════════════════════════════════════
        sec_main = make_section("Основное")

        grp_ui = QGroupBox("Интерфейс")
        vui = QVBoxLayout(grp_ui)
        chk_wheel = QCheckBox("Колёсико мыши меняет значения в полях")
        chk_wheel.setChecked(bool(self._wheel_changes_values))
        chk_wheel.toggled.connect(self._set_wheel_changes_values)
        vui.addWidget(chk_wheel)
        vui.addWidget(hint("Выкл — колёсико над полями прокручивает панель, а не меняет числа."))
        add_row(sec_main, grp_ui, "колесо мышь интерфейс значения прокрутка битрейт ползунки")

        # ══ Секция «Монтаж» ══════════════════════════════════════════════════
        sec_edit = make_section("Монтаж")

        grp_keys = QGroupBox("Сочетания обрезки")
        vk = QVBoxLayout(grp_keys)
        te = getattr(self, "tab_edit", None)
        if te is not None and getattr(te, "_ready", False):
            start_seq, end_seq = te.get_trim_shortcuts()

            def _mk_key_row(label_text, init_seq, apply_idx):
                row = QHBoxLayout()
                lbl = QLabel(label_text)
                lbl.setStyleSheet("color:#cdd6f4; font-size:12px;")
                lbl.setFixedWidth(230)
                kse = LatinKeySequenceEdit()
                kse.setKeySequence(QKeySequence(init_seq))
                row.addWidget(lbl); row.addWidget(kse, 1)
                w = QWidget(); w.setLayout(row)
                return w, kse

            row_start, kse_start = _mk_key_row("Обрезать старт до плейхеда", start_seq, 0)
            row_end,   kse_end   = _mk_key_row("Обрезать конец до плейхеда", end_seq, 1)
            vk.addWidget(row_start)
            vk.addWidget(row_end)

            def _apply_keys():
                te.set_trim_shortcuts(
                    kse_start.keySequence().toString(),
                    kse_end.keySequence().toString())

            kse_start.editingFinished.connect(_apply_keys)
            kse_end.editingFinished.connect(_apply_keys)
            kse_start.keySequenceChanged.connect(lambda *_: _apply_keys())
            kse_end.keySequenceChanged.connect(lambda *_: _apply_keys())

            btn_reset = QPushButton("Сбросить по умолчанию (Shift+C / Shift+V)")
            def _reset_keys():
                kse_start.setKeySequence(QKeySequence("Shift+C"))
                kse_end.setKeySequence(QKeySequence("Shift+V"))
                te.set_trim_shortcuts("Shift+C", "Shift+V")
            btn_reset.clicked.connect(_reset_keys)
            vk.addWidget(btn_reset)
            vk.addWidget(hint("Кликните в поле и нажмите нужную комбинацию. «Старт» "
                              "ставит точку IN, «Конец» — точку OUT на текущую позицию "
                              "воспроизведения."))
        else:
            vk.addWidget(hint("Вкладка «Монтаж» недоступна (нет модуля мультимедиа), "
                              "настройка сочетаний невозможна."))
        add_row(sec_edit, grp_keys, "монтаж обрезка сочетание клавиши shift c v плейхед старт конец in out горячие")

        grp_scrub = QGroupBox("Покадровая перемотка")
        vsc = QVBoxLayout(grp_scrub)
        if te is not None and getattr(te, "_ready", False):
            chk_scrub_audio = QCheckBox("Звук при покадровой перемотке (скраб, как в Filmora)")
            chk_scrub_audio.setChecked(bool(getattr(te, "_scrub_audio_enabled", True)))
            chk_scrub_audio.toggled.connect(lambda v: te.set_scrub_audio(bool(v)))
            vsc.addWidget(chk_scrub_audio)
            vsc.addWidget(hint("Вкл (по умолч.): при шаге по кадрам (←/→, WASD) звучит короткий "
                               "фрагмент новой позиции — слышно, что под курсором."))
        else:
            vsc.addWidget(hint("Вкладка «Монтаж» недоступна (нет модуля мультимедиа)."))
        add_row(sec_edit, grp_scrub, "монтаж покадровая перемотка скраб звук filmora кадр шаг стрелки wasd аудио")

        grp_render = QGroupBox("Видео и оверлеи")
        vr = QVBoxLayout(grp_render)

        if te is not None and getattr(te, "_ready", False):
            chk_subframe = QCheckBox("Субтитры рендерить прямо в кадр (как в VLC)")
            chk_subframe.setChecked(bool(getattr(te, "_subs_in_frame", True)))
            chk_subframe.toggled.connect(lambda v: te.set_subs_in_frame(bool(v)))
            vr.addWidget(chk_subframe)
            vr.addWidget(hint("Вкл (по умолч.): субтитры рисуются внутри кадра (как в VLC). "
                              "Выкл: отдельный оверлей поверх видео. Применяется сразу."))

        chk_hw = QCheckBox("Аппаратное ускорение видео (H.264 / HEVC)")
        chk_hw.setChecked(bool(getattr(self, "_video_hw_decode", True)))
        chk_hw.toggled.connect(self._set_video_hw_decode)
        vr.addWidget(chk_hw)
        vr.addWidget(hint("Вкл (по умолч.): H.264/HEVC декодируются на видеокарте (D3D11VA/DXVA2) "
                          "— тяжёлые файлы в «Монтаже» играют плавно. Выключите, если прямой AV1 "
                          "(SiQuesterHYX) даёт чёрный экран. Нужен перезапуск."))

        chk_sw = QCheckBox("Программный рендер видео (убирает оверлей RivaTuner/FPS)")
        chk_sw.setChecked(bool(getattr(self, "_video_software_render", False)))
        chk_sw.toggled.connect(self._set_video_software_render)
        vr.addWidget(chk_sw)
        vr.addWidget(hint("Помогает, когда RivaTuner рисует FPS поверх видео: рендер без "
                          "D3D/GL-свопчейна (HW-ускорение видео при этом тоже выключается). "
                          "Нужен перезапуск."))
        add_row(sec_edit, grp_render, "rivatuner оверлей fps d3d11 рендер видео аппаратное программное ускорение субтитры кадр vlc метод hevc h264 dxva декодирование")

        # ══ Секция «Экспериментально» (предпоследняя) ════════════════════════
        sec_exp = make_section("Экспериментально")

        grp_sv = QGroupBox("Браузерное расширение")
        vsv = QVBoxLayout(grp_sv)
        chk = QCheckBox(f"Включить локальный сервер (localhost:{HTTP_PORT})")
        chk.setChecked(bool(self._server_enabled))
        chk.toggled.connect(self._set_server_enabled)
        vsv.addWidget(chk)
        vsv.addWidget(hint("Выкл по умолчанию. Включите, чтобы расширение в браузере "
                           "слало ссылки в программу."))
        add_row(sec_exp, grp_sv, "браузер расширение сервер localhost порт ссылки экспериментально")

        grp_siq = QGroupBox("Дополнительные вкладки")
        vexp = QVBoxLayout(grp_siq)
        chk_prompt = QCheckBox("Включить вкладку «Промпт»")
        chk_prompt.setChecked(bool(getattr(self, "_prompt_tab_enabled", False)))
        chk_prompt.toggled.connect(self._set_prompt_tab_enabled)
        vexp.addWidget(chk_prompt)
        vexp.addWidget(hint("Менеджер промптов: хранение и быстрый выбор заготовок."))
        chk_siq = QCheckBox("Включить вкладку «SiQuesterHYX» (просмотр .siq + статистика)")
        chk_siq.setChecked(bool(getattr(self, "_siquester_tab_enabled", False)))
        chk_siq.toggled.connect(self._set_siquester_tab_enabled)
        vexp.addWidget(chk_siq)
        vexp.addWidget(hint(icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                            + " Экспериментально. Просмотрщик пакетов SIGame (.siq) и "
                            "статистика. Без перезапуска."))
        chk_shiki = QCheckBox("Включить вкладку «ShikimoriHYX» (поиск аниме по Shikimori API)")
        chk_shiki.setChecked(bool(getattr(self, "_shikimori_tab_enabled", False)))
        chk_shiki.toggled.connect(self._set_shikimori_tab_enabled)
        vexp.addWidget(chk_shiki)
        vexp.addWidget(hint(icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                            + " Экспериментально. Поиск аниме через Shikimori API с фильтрами; "
                            "экспорт в JSON/CSV. OAuth-токен — в переменной SHIKIMORI_TOKEN. "
                            "Без перезапуска."))
        add_row(sec_exp, grp_siq,
                "промпт prompt заготовки шаблоны "
                "siquester сиквестер siq пакет вопросы статистика эксперимент вкладка просмотр sigame "
                "shikimori шикимори аниме поиск оценка жанр год api джойнт")

        # ══ Секция «О программе» ═════════════════════════════════════════════
        sec_about = make_section("О программе")

        grp_up = QGroupBox("Обновления")
        vup = QVBoxLayout(grp_up)
        btn_app_up = QPushButton("Проверить обновления программы")
        btn_app_up.setIcon(get_icon('fa5s.sync-alt'))
        btn_app_up.setIconSize(QSize(20, 20))
        btn_app_up.setToolTip("Проверяет последнюю версию на GitHub и предлагает обновиться")
        btn_app_up.clicked.connect(lambda: self._check_updates(silent=False))
        vup.addWidget(btn_app_up)
        vup.addWidget(hint("При наличии новой версии программа сама скачает её и перезапустится."))
        btn_up = QPushButton("Обновить yt-dlp")
        btn_up.setIcon(get_icon('fa5s.download'))
        btn_up.setIconSize(QSize(20, 20))
        btn_up.setToolTip("Скачивает свежую версию yt-dlp (исправляет загрузку, когда YouTube/TikTok ломают старую)")
        btn_up.clicked.connect(self._update_ytdlp)
        vup.addWidget(btn_up)
        vup.addWidget(hint("Если перестало качать с YouTube/TikTok — нажмите, чтобы обновить yt-dlp "
                           "(работает для bin/yt-dlp.exe)."))
        add_row(sec_about, grp_up, "обновление обновить программа yt-dlp youtube tiktok версия github")

        grp_links = QGroupBox("Ссылки и сообщество")
        vl = QVBoxLayout(grp_links)
        links = QLabel(
            f'Discord: <a href="{DISCORD_URL}" style="color:#89b4fa;">{DISCORD_URL}</a><br>'
            f'GitHub: <a href="{GITHUB_URL}" style="color:#89b4fa;">{GITHUB_URL}</a>')
        links.setOpenExternalLinks(True)
        links.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        links.setWordWrap(True)
        links.setStyleSheet("color:#a6adc8; font-size:12px;")
        vl.addWidget(links)
        add_row(sec_about, grp_links, "discord github ссылки сообщество поддержка обновления")

        content_l.addStretch(1)

        # ── Навигация ↔ прокрутка (взаимная синхронизация) ───────────────────
        # Клик по категории прокручивает к секции; прокрутка колесом/ползунком
        # подсвечивает категорию активной секции. Флаг гасит рекурсию сигналов.
        syncing = {'v': False}

        def _goto(idx):
            if syncing['v']:
                return
            if 0 <= idx < len(sections):
                syncing['v'] = True
                scroll.ensureWidgetVisible(sections[idx]['header'], 0, 0)
                syncing['v'] = False
        nav.currentRowChanged.connect(_goto)

        def _on_scroll(_val=None):
            if syncing['v']:
                return
            val = scroll.verticalScrollBar().value()
            cur = 0
            for i, rec in enumerate(sections):
                if rec['widget'].isVisible() and rec['widget'].y() <= val + 12:
                    cur = i
            if cur != nav.currentRow():
                syncing['v'] = True
                nav.setCurrentRow(cur)
                syncing['v'] = False
        scroll.verticalScrollBar().valueChanged.connect(_on_scroll)

        nav.setCurrentRow(0)

        # ── Поиск: прячем несовпадающие строки/секции ────────────────────────
        def _do_search(text):
            q = (text or "").strip().lower()
            first_visible = None
            for i, rec in enumerate(sections):
                any_vis = False
                for w, kw in rec['rows']:
                    vis = (q in kw) if q else True
                    w.setVisible(vis)
                    any_vis = any_vis or vis
                show_sec = any_vis if q else True
                rec['widget'].setVisible(show_sec)
                rec['header'].setVisible(show_sec)
                nav.item(i).setHidden(bool(q) and not show_sec)
                if show_sec and first_visible is None:
                    first_visible = rec
            if q and first_visible is not None:
                scroll.ensureWidgetVisible(first_visible['header'], 0, 0)
        search.textChanged.connect(_do_search)

        dlg.exec()

    def _collect_settings(self):
        try:
            tm = self.tab_media; ty = self.tab_ytdlp
            s = {
                'media': {
                    'audio': {
                        'norm': bool(tm.ck_norm.isChecked()), 'tgt': float(tm.s_tgt.value()), 'lra': float(tm.s_lra.value()),
                        'tp': float(tm.s_tp.value()), 'fade': bool(tm.ck_fade.isChecked()), 'fade_d': float(tm.s_fade.value()),
                        'fade_in': bool(tm.ck_fade_in.isChecked()), 'fade_in_d': float(tm.s_fade_in.value()),
                        'deg': bool(tm.ck_deg.isChecked()), 'hz': int(tm.s_hz.value()), 'u8': bool(tm.ck_u8.isChecked()),
                        'lp': int(tm.s_lp.value()), 'hp': int(tm.s_hp.value()), 'deg_gain_db': float(tm.s_deg_gain.value()),
                        'bitrate': tm.c_abitrate.currentText()
                    },
                    'video': {
                        'enabled': bool(tm.chk_enable_video.isChecked()), 'speed': int(tm.s_spd.value()), 'crf': int(tm.s_crf.value()),
                        'pre': int(tm.s_pre.value()), 'res': strip_default_tag(tm.c_res.currentText()), 'fps': tm.c_fps.currentText(),
                        'preset_mode': 'dark' if tm.btn_mode_dark.isChecked() else 'std',
                        'vfade_in': bool(tm.ck_vfade_in.isChecked()), 'vfade_in_d': float(tm.s_vfade_in.value()),
                        'vfade_out': bool(tm.ck_vfade_out.isChecked()), 'vfade_out_d': float(tm.s_vfade_out.value())
                    },
                    'export_dir': getattr(tm, 'export_dir', '') or ''
                },
                'ytdlp': {
                    'outdir': ty.out.text(), 'quality': ty.c_q.currentText(), 'merge': ty.c_c.currentText(),
                    'sub_lang': ty.c_s.currentText(), 'audio': ty.c_a.currentText(), 'force_kf': bool(ty.chk_k.isChecked()),
                    'cookie_path': ty.cookie_edit.text().strip(),
                    'proxy': ty.proxy_edit.text().strip(),
                },
                'avif': {
                    'limit': int(tm.s_lim.value()), 'limit_on': bool(tm.ck_lim.isChecked()),
                    'adim': int(tm.s_dim.value()), 'adim_on': bool(tm.ck_dim.isChecked()),
                    'aspd': int(tm.sl_aspd.value()),
                    'overwrite_src': bool(tm.ck_overwrite_src.isChecked()) if hasattr(tm, 'ck_overwrite_src') else False,
                    'fit_passes': int(tm.s_passes.value()),
                    'img_fmt': strip_default_tag(tm.c_img_fmt.currentText())
                },
                'server_enabled': bool(getattr(self, '_server_enabled', False)),
                'wheel_changes_values': bool(getattr(self, '_wheel_changes_values', False)),
                'video_software_render': bool(getattr(self, '_video_software_render', False)),
                'video_hw_decode': bool(getattr(self, '_video_hw_decode', True)),
                'siquester_tab_enabled': bool(getattr(self, '_siquester_tab_enabled', False)),
                'shikimori_tab_enabled': bool(getattr(self, '_shikimori_tab_enabled', False)),
                'shikimori': self._collect_shikimori_settings(),
                'prompt_tab_enabled': bool(getattr(self, '_prompt_tab_enabled', False)),
                'priority': tm.c_priority.currentText() if hasattr(tm, 'c_priority') else 'Обычный',
                'prompt_file': getattr(getattr(self, 'tab_prompt', None), '_prompt_path', '') or '',
                'tab_order': list(getattr(self, '_tab_order', [])),
            }
            return s
        except Exception: return {}

    def _save_settings_now(self):
        try:
            data = self._collect_settings()
            # _collect_settings возвращает {} при любой ошибке (напр. после
            # изменения кода обращение к ещё не созданному виджету). НЕ пишем
            # пустой словарь — иначе settings.json затирается, и при следующем
            # запуске папка загрузчика и прочие настройки сбрасываются к дефолту.
            if not data:
                self.log("save settings: пустой результат сборки — пропуск (файл не затёрт)")
                return
            save_settings(data)
        except Exception as e:
            self.log(f"save settings error: {e}")

    def _attach_save_handlers(self):
        try:
            tm = self.tab_media
            ty = self.tab_ytdlp
            # Виджеты с сигналом toggled (QCheckBox, QPushButton checkable)
            toggle_widgets = [
                tm.ck_norm, tm.ck_fade, tm.ck_fade_in, tm.ck_deg, tm.ck_u8,
                tm.chk_enable_video, tm.btn_mode_dark,
                tm.ck_overwrite_src,
                tm.ck_lim, tm.ck_dim,
                tm.ck_vfade_in, tm.ck_vfade_out,
                ty.chk_k,
            ]
            # Виджеты с сигналом valueChanged (QSpinBox, QDoubleSpinBox, QSlider)
            value_widgets = [
                tm.s_tgt, tm.s_lra, tm.s_tp, tm.s_fade, tm.s_fade_in,
                tm.s_hz, tm.s_lp, tm.s_hp, tm.s_deg_gain,
                tm.s_spd, tm.s_crf, tm.s_pre,
                tm.s_lim, tm.s_dim, tm.sl_aspd, tm.s_passes,
                tm.s_vfade_in, tm.s_vfade_out,
            ]
            # Виджеты с сигналом currentTextChanged (QComboBox)
            combo_widgets = [
                tm.c_abitrate, tm.c_res, tm.c_fps, tm.c_img_fmt, tm.c_priority,
                ty.c_q, ty.c_c, ty.c_s, ty.c_a,
            ]
            # Виджет с сигналом textChanged (QLineEdit)
            text_widgets = [ty.out, ty.cookie_edit, ty.proxy_edit]

            for w in toggle_widgets:
                w.toggled.connect(self._save_settings_now)
            for w in value_widgets:
                w.valueChanged.connect(self._save_settings_now)
            for w in combo_widgets:
                w.currentTextChanged.connect(self._save_settings_now)
            for w in text_widgets:
                w.textChanged.connect(self._save_settings_now)
        except Exception as e:
            self.log(f"_attach_save_handlers error: {e}")
    
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

    def update_global_progress(self, val, text):
        # val < 0 → неопределённый («busy») режим: полоса пульсирует. Нужен для
        # фаз, где реального процента нет (перемотка декодера до точки реза при
        # обрезке с перекодированием), чтобы полоса не выглядела зависшей на 0%.
        if val is None or val < 0:
            if self.pbar.maximum() != 0:
                self.pbar.setRange(0, 0)
            self.pbar.setFormat(text)
            self.set_taskbar_progress(0, 0)   # indeterminate в панели задач
            return
        if self.pbar.maximum() == 0:          # вернуть из busy в обычный режим
            self.pbar.setRange(0, 100)
        self.pbar.setValue(val); self.pbar.setFormat(text)
        # Зеркалим прогресс перекодирования на иконку в панели задач
        if val >= 100:
            self.clear_taskbar_progress()
        else:
            self.set_taskbar_progress(val, 100)

    def _tb_hwnd(self):
        """HWND окна для ITaskbarList3 (кэшируем; winId валиден после создания окна)."""
        if not self._taskbar_hwnd:
            try: self._taskbar_hwnd = int(self.winId())
            except Exception: self._taskbar_hwnd = 0
        return self._taskbar_hwnd

    def set_taskbar_progress(self, completed, total=100):
        """Показать прогресс длительной задачи на иконке приложения."""
        try: self._taskbar.set_value(self._tb_hwnd(), completed, total)
        except Exception: pass

    def clear_taskbar_progress(self):
        try: self._taskbar.clear(self._tb_hwnd())
        except Exception: pass

    def _sync_console_visibility(self, *args):
        """Нижняя консоль и прогрессбар. Консоль скрыта на «Монтаж» и
        «SiQuesterHYX» (там она лишь занимает место). Прогрессбар скрыт на
        «SiQuesterHYX» (на «Монтаж» он нужен для прогресса экспорта)."""
        try:
            cur = self.tabs.currentWidget()
            is_edit = cur is self.tab_edit
            tsq = getattr(self, "tab_siquester", None)
            is_siq = tsq is not None and cur is tsq
            tsh = getattr(self, "tab_shikimori", None)
            is_shiki = tsh is not None and cur is tsh
            self.console_panel.setVisible(not (is_edit or is_siq or is_shiki))
            self.pbar.setVisible(not (is_siq or is_shiki))
        except Exception:
            pass

    def eventFilter(self, obj, event):
        # Держим кнопку-значок «развернуть консоль» прижатой к правому верхнему
        # углу консоли при её ресайзе/показе.
        if obj is getattr(self, "txt_log", None) and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Show):
            self._reposition_console_btn()
        bar = self.tabs.tabBar() if getattr(self, "tabs", None) is not None else None
        if bar is not None and obj is bar:
            et = event.type()
            if et == QEvent.Type.MouseMove:
                try: self._update_tab_tip(event.position().toPoint())
                except Exception: pass
            elif et in (QEvent.Type.Leave, QEvent.Type.Hide,
                        QEvent.Type.WindowDeactivate):
                self._hide_tab_tip()
        return super().eventFilter(obj, event)

    def _update_tab_tip(self, pos):
        """Показывает попап-подсказку, если курсор над значком ⓘ вкладки.

        Текст берём не из значка, а из _tab_info по стабильному ключу вкладки
        (objectName 'tab::<key>'): Qt при tabButton() может вернуть значок как
        обычный QLabel, потеряв питоновский атрибут _tip, поэтому полагаться на
        сам объект значка нельзя."""
        from widgets import _InfoTipPopup
        bar = self.tabs.tabBar()
        idx = bar.tabAt(pos)
        if idx < 0:
            self._hide_tab_tip(); return
        badge = bar.tabButton(idx, QTabBar.ButtonPosition.RightSide)
        page = self.tabs.widget(idx)
        on = page.objectName() if page is not None else ""
        tip = self._tab_info.get(on[5:], ("", "", ""))[2] if on.startswith("tab::") else ""
        if badge is not None and tip and badge.geometry().contains(pos):
            if self._tab_tip_idx != idx:
                _InfoTipPopup.instance().show_for(badge, tip)
                self._tab_tip_idx = idx
        else:
            self._hide_tab_tip()

    def _hide_tab_tip(self):
        if getattr(self, "_tab_tip_idx", -1) != -1:
            try:
                from widgets import _InfoTipPopup
                _InfoTipPopup.instance().hide()
            except Exception:
                pass
            self._tab_tip_idx = -1

    def _reposition_console_btn(self):
        btn = getattr(self, "btn_open_console", None)
        if btn is None:
            return
        try:
            # Якоримся к ПРАВОМУ краю txt_log за вычетом ширины видимого
            # вертикального скроллбара — иначе он перекрывает кнопку.
            sb = self.txt_log.verticalScrollBar()
            sbw = sb.width() if (sb is not None and sb.isVisible()) else 0
            x = self.txt_log.width() - sbw - btn.width() - 6
            btn.move(max(0, x), 4)
            btn.raise_()
        except Exception:
            pass

    def _open_console_window(self):
        """Открывает консоль в окне почти на весь размер главного окна.
        Использует тот же QTextDocument, поэтому лог обновляется вживую."""
        dlg = getattr(self, "_console_dialog", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_(); dlg.activateWindow()
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Консоль")
        dlg.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        v = QVBoxLayout(dlg); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        big = QTextEdit(dlg); big.setReadOnly(True)
        big.setDocument(self.txt_log.document())   # общий документ → живой лог
        big.moveCursor(QTextCursor.MoveOperation.End)
        big.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        big.customContextMenuRequested.connect(
            lambda pos, w=big: self._log_context_menu(pos, w))
        v.addWidget(big)

        row = QHBoxLayout(); row.addStretch(1)
        btn_clr = QPushButton("Очистить", dlg)
        btn_clr.clicked.connect(self.txt_log.clear)
        btn_close = QPushButton("Закрыть", dlg)
        btn_close.clicked.connect(dlg.close)
        row.addWidget(btn_clr); row.addWidget(btn_close)
        v.addLayout(row)

        # Размер ~90% от главного окна, по центру над ним
        g = self.geometry()
        w = int(g.width() * 0.9); h = int(g.height() * 0.9)
        dlg.resize(max(640, w), max(400, h))
        dlg.move(g.x() + (g.width() - dlg.width()) // 2,
                 g.y() + (g.height() - dlg.height()) // 2)

        def _on_close():
            self._console_dialog = None
        dlg.finished.connect(lambda *_: _on_close())
        self._console_dialog = dlg
        dlg.show()
        big.moveCursor(QTextCursor.MoveOperation.End)

    def _log_context_menu(self, pos, widget=None):
        """Русское контекстное меню для лог-консоли (вместо системного англ.)."""
        w = widget or self.txt_log
        m = QMenu(w)
        a_copy = m.addAction("Копировать")
        a_copy.setEnabled(w.textCursor().hasSelection())
        a_copy.triggered.connect(w.copy)
        a_sel = m.addAction("Выделить всё")
        a_sel.triggered.connect(w.selectAll)
        m.addSeparator()
        a_clr = m.addAction("Очистить")
        a_clr.triggered.connect(self.txt_log.clear)
        m.exec(w.mapToGlobal(pos))

    def log(self, txt):
        try: t = time.strftime("%Y-%m-%d %H:%M:%S"); self.txt_log.append(f"[{t}] {txt}")
        except Exception: pass

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
                self._stop_browser_http_server()
            except Exception:
                pass
            try:
                QThreadPool.globalInstance().waitForDone(3000)
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


def _install_crash_handler():
    """Глобальный обработчик необработанных исключений: пишет трейсбек в
    crash.log, показывает пользователю диалог с ошибкой и аккуратно завершает
    программу. Так падение не «исчезает в никуда», а видно пользователю."""
    import traceback as _tb
    import datetime as _dt
    crash_log = os.path.join(CONFIG_DIR, "crash.log")
    _already = {"shown": False}

    def _handle(exc_type, exc_value, exc_tb):
        # Ctrl+C — стандартное поведение, не показываем диалог
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_text = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        # Защита от рекурсии: если падение случилось при показе диалога
        if _already["shown"]:
            try:
                sys.stderr.write(tb_text)
            except Exception:
                pass
            os._exit(1)
        _already["shown"] = True
        try:
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\n===== {_dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
                f.write(tb_text)
        except Exception:
            pass
        try:
            if sys.stderr is not None:
                sys.stderr.write(tb_text)
                sys.stderr.flush()
        except Exception:
            pass
        try:
            from PyQt6.QtWidgets import QMessageBox
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("SI-HYX — критическая ошибка")
            box.setText("Произошла непредвиденная ошибка, программа будет закрыта.")
            box.setInformativeText(f"{exc_type.__name__}: {exc_value}")
            box.setDetailedText(tb_text)
            try:
                if APP_ICON:
                    box.setWindowIcon(QIcon(APP_ICON))
            except Exception:
                pass
            box.exec()
        except Exception:
            pass
        os._exit(1)

    sys.excepthook = _handle


def main():
    # AppUserModelID задаём САМЫМ ПЕРВЫМ — до QLocalSocket, QApplication и любого
    # обращения к панели задач. Иначе Windows успевает связать кнопку на панели
    # задач с хост-процессом python.exe (его иконкой), и наша иконка окна больше
    # не подхватывается (баг «иконка пропала при запуске main.py»).
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GoldensFire.SI-HYX")
        except Exception:
            pass

    # Парсим аргументы один раз
    cli_files = [f for f in sys.argv[1:] if os.path.exists(f)]

    # Если запущен с аргументами (через ПКМ) — пробуем передать файлы уже открытому окну
    if cli_files:
        try:
            sock = QLocalSocket()
            sock.connectToServer("YasperMoglotIPC")
            if sock.waitForConnected(800):
                sock.write(('\n'.join(cli_files) + '\n').encode('utf-8'))
                sock.flush()
                sock.waitForBytesWritten(1000)
                sock.disconnectFromServer()
                return  # Файл передан — новое окно не открываем
        except Exception: pass
        # Сервер не найден — запускаем нормально и загружаем файлы

    qInstallMessageHandler(_qt_message_filter)
    _install_crash_handler()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Русификация стандартных кнопок диалогов Qt (QMessageBox и др.): без
    # переводчика «Да/Нет/ОК/Отмена» рисуются по-английски (Yes/No/OK/Cancel),
    # из-за чего окна подтверждения в «Монтаже» были на английском.
    try:
        _qt_translator = QTranslator(app)
        _tr_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if _qt_translator.load(QLocale("ru"), "qtbase", "_", _tr_path) or \
           _qt_translator.load("qtbase_ru", _tr_path):
            app.installTranslator(_qt_translator)
            app._qt_translator = _qt_translator  # держим ссылку от сборщика мусора
    except Exception:
        pass
    app.setStyleSheet(STYLESHEET)
    # Стабильные подсказки без мерцания (тот же попап, что у значков ⓘ) для всех
    # виджетов с setToolTip — заменяет системный QToolTip (см. widgets.py).
    install_hover_tips(app)
    if APP_ICON:
        app.setWindowIcon(QIcon(APP_ICON))

    w = UnifiedWindow()

    # Если файлы переданы аргументами и IPC не сработал — добавляем напрямую
    if cli_files:
        QTimer.singleShot(300, lambda: (
            w.tabs.setCurrentWidget(w.tab_media),
            w.tab_media.add_paths(cli_files)
        ))

    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
