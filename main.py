# -*- coding: utf-8 -*-
# main.py — главное окно, HTTP-сервер расширения, точка входа
from config import *
from utils import *
from widgets import *
from workers import *
from tabs import *


class UnifiedWindow(QMainWindow):
    url_from_browser = pyqtSignal(str, bool)  # URL + audio_only из браузерного расширения (HTTP-сервер → Qt)
    log_signal = pyqtSignal(str)              # потокобезопасный лог (из фоновых потоков → GUI)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        screen = QApplication.primaryScreen()
        try: geom = screen.availableGeometry(); max_h = geom.height() - 80
        except Exception: geom = screen.geometry(); max_h = geom.height() - 80
        init_h = min(900, max_h); init_w = 1280
        self.resize(init_w, init_h)
        try: center_x = geom.x() + (geom.width() - init_w)//2; center_y = geom.y() + (geom.height() - init_h)//2; self.move(center_x, center_y)
        except Exception: pass

        self.setAcceptDrops(True)
        self.log_signal.connect(self.log)
        if not check_ffmpeg(): QMessageBox.critical(self, "Error", "FFmpeg not found!")

        c = QWidget(); self.setCentralWidget(c); l = QVBoxLayout(c)
        l.setContentsMargins(8, 8, 8, 8); l.setSpacing(6)

        self.tabs = QTabWidget()
        self.tab_media = MediaTab(self); self.tab_ytdlp = YtdlpTab(self)
        self.tab_photo = PhotoMergerTab(self)
        self.tab_b64    = Base64Tab(self)
        self.tab_prompt = PromptTab(self)
        self.tab_media.thumb_sig.connect(self.tab_media.set_thumb)
        self.tab_ytdlp.thumb_sig.connect(self.tab_ytdlp.set_thumb)
        self.tabs.addTab(self.tab_media,  "🎬  Обработка")
        self.tabs.addTab(self.tab_ytdlp,  "📥  Загрузчик")
        self.tabs.addTab(self.tab_photo,  "🖼️  Фото")
        self.tabs.addTab(self.tab_b64,    "🔡  Base64")
        self.tabs.addTab(self.tab_prompt, "📋  Промпт")

        # Кнопки в строке вкладок — corner widget подгоняется под высоту таббара
        self.btn_top_restart = QPushButton("↻  Перезапустить GUI")
        self.btn_top_restart.setObjectName("b_restart")
        self.btn_top_restart.clicked.connect(lambda: self.tab_media.restart_gui())
        self.btn_settings = QToolButton()
        self.btn_settings.setText("⚙")
        self.btn_settings.setToolTip("Настройки")
        self.btn_settings.clicked.connect(self._open_settings_dialog)
        corner = QWidget()
        ch = QHBoxLayout(corner); ch.setContentsMargins(0, 0, 4, 0); ch.setSpacing(4)
        ch.addWidget(self.btn_settings); ch.addWidget(self.btn_top_restart)
        self.tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        # Единый стрип файлов — общий для всех вкладок
        self.recent_strip = RecentFilesStrip(self, mode='all')
        l.addWidget(self.recent_strip)
        l.addWidget(self.tabs)

        self.pbar = QProgressBar(); self.pbar.setTextVisible(True); self.pbar.setFormat("Ожидание")
        self.pbar.setFixedHeight(22)
        l.addWidget(self.pbar)

        self.txt_log = QTextEdit(); self.txt_log.setFixedHeight(120); self.txt_log.setReadOnly(True)
        l.addWidget(self.txt_log)

        # Состояние локального сервера для расширения (по умолчанию ВЫКЛ)
        self._server_enabled = False
        self._http_srv = None
        self._http_thread = None

        try: self._load_settings()
        except Exception: pass

        self._attach_save_handlers()

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
        else:
            self.log("Сервер для расширения выключен (включить можно в ⚙ Настройки).")

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
        try:
            m = s.get("media", {}); a = m.get("audio", {})
            tm.ck_norm.setChecked(a.get("norm", True))
            tm.s_tgt.setValue(a.get("tgt", -16.0))
            tm.s_lra.setValue(a.get("lra", 20.0))
            tm.s_tp.setValue(a.get("tp", -1.5))
            tm.ck_fade.setChecked(a.get("fade", True))
            tm.s_fade.setValue(a.get("fade_d", 1.0))
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
            tm.s_crf.setValue(v.get("crf", 35))
            tm.s_pre.setValue(v.get("pre", 8))
            tm.c_res.setCurrentText(v.get("res", "Исходное"))
            tm.c_fps.setCurrentText(v.get("fps", "Исходный"))
            tm._set_preset_mode(v.get("preset_mode", "std"))

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

            av = s.get("avif", {})
            tm.s_lim.setValue(av.get("limit", tm.s_lim.value()))
            tm.ck_lim.setChecked(av.get("limit_on", True))
            tm.s_lim.setEnabled(tm.ck_lim.isChecked())
            tm.s_dim.setValue(av.get("adim", tm.s_dim.value()))
            tm.ck_dim.setChecked(av.get("adim_on", False))
            tm.s_dim.setEnabled(tm.ck_dim.isChecked())
            tm.sl_aspd.setValue(av.get("aspd", tm.sl_aspd.value()))
            tm.ck_arec.setChecked(av.get("arec", tm.ck_arec.isChecked()))
            tm.c_img_fmt.setCurrentText(av.get("img_fmt", "avif"))

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
            def _send_cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def do_OPTIONS(self):
                self.send_response(200)
                self._send_cors()
                self.end_headers()

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", 0))

                    # ── /screenshot — тело бинарное (PNG), читаем ДО json.loads ──
                    if self.path == "/screenshot":
                        img_bytes = self.rfile.read(length)
                        from urllib.parse import unquote
                        filename = unquote(self.headers.get("X-Filename", "screenshot.png")) or "screenshot.png"
                        if not img_bytes:
                            self.send_response(400); self._send_cors(); self.end_headers()
                            self.wfile.write(b'{"ok":false,"error":"empty body"}'); return
                        try:
                            out_dir = win.tab_ytdlp.out.text().strip()
                        except Exception:
                            out_dir = ""
                        if not out_dir or not os.path.isdir(out_dir):
                            out_dir = str(Path.home())
                        out_path = os.path.join(out_dir, filename)
                        if os.path.exists(out_path):
                            base_n, ext_n = os.path.splitext(filename)
                            out_path = os.path.join(out_dir, f"{base_n}_{int(time.time())}{ext_n}")
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
                        if not img_url:
                            self.send_response(400); self._send_cors(); self.end_headers()
                            self.wfile.write(b'{"ok":false,"error":"empty url"}'); return
                        try:
                            out_dir = win.tab_ytdlp.out.text().strip()
                        except Exception:
                            out_dir = ""
                        if not out_dir or not os.path.isdir(out_dir):
                            out_dir = str(Path.home())
                        out_path = os.path.join(out_dir, filename)
                        if os.path.exists(out_path):
                            base_n, ext_n = os.path.splitext(filename)
                            out_path = os.path.join(out_dir, f"{base_n}_{int(time.time())}{ext_n}")
                        req = urllib.request.Request(img_url, headers={"User-Agent": USER_AGENT, "Referer": img_url})
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            img_bytes = resp.read()
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

    def _open_url(self, url: str):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            self.log(f"Не удалось открыть ссылку: {e}")

    def _update_ytdlp(self):
        """Обновляет yt-dlp.exe командой `-U` (работает только для standalone-exe)."""
        base = ytdlp_base_cmd()
        if not base:
            self.log("yt-dlp не найден — положите yt-dlp.exe в папку bin рядом с программой.")
            return
        if len(base) != 1:
            self.log("Обновление через -U доступно только для bin/yt-dlp.exe "
                     "(в dev-режиме используется pip-версия: обновляйте через `pip install -U yt-dlp`).")
            return
        exe = base[0]
        self.log("Обновляю yt-dlp…")

        def _run():
            try:
                p = subprocess.run([exe, "-U"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=CREATE_NO_WINDOW, timeout=180)
                for ln in (p.stdout or "").splitlines():
                    if ln.strip():
                        self.log_signal.emit(ln.strip())
                self.log_signal.emit("Готово (обновление yt-dlp).")
            except Exception as e:
                self.log_signal.emit(f"Ошибка обновления yt-dlp: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _open_settings_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Настройки — " + APP_TITLE)
        dlg.setMinimumWidth(400)
        lay = QVBoxLayout(dlg); lay.setSpacing(10)

        title = QLabel(APP_TITLE)
        title.setStyleSheet("font-size:17px; font-weight:bold; color:#89b4fa;")
        lay.addWidget(title)

        # --- Discord ---
        grp_dc = QGroupBox("Сообщество")
        vdc = QVBoxLayout(grp_dc)
        btn_dc = QPushButton("💬  Открыть Discord-канал")
        btn_dc.clicked.connect(lambda: self._open_url(DISCORD_URL))
        vdc.addWidget(btn_dc)
        lbl_dc = QLabel(f'<a href="{DISCORD_URL}" style="color:#89b4fa;">{DISCORD_URL}</a>')
        lbl_dc.setOpenExternalLinks(True)
        lbl_dc.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lbl_dc.setWordWrap(True)
        vdc.addWidget(lbl_dc)
        lay.addWidget(grp_dc)

        # --- Сервер расширения ---
        grp_sv = QGroupBox("Браузерное расширение")
        vsv = QVBoxLayout(grp_sv)
        chk = QCheckBox(f"Включить локальный сервер (localhost:{HTTP_PORT})")
        chk.setChecked(bool(self._server_enabled))
        chk.toggled.connect(self._set_server_enabled)
        vsv.addWidget(chk)
        hint = QLabel("По умолчанию выключен. Включите, чтобы кнопки расширения "
                      "в браузере могли отправлять ссылки в программу.")
        hint.setStyleSheet("color:#a6adc8; font-size:11px;")
        hint.setWordWrap(True)
        vsv.addWidget(hint)
        lay.addWidget(grp_sv)

        # --- Обновления ---
        grp_up = QGroupBox("Обновления")
        vup = QVBoxLayout(grp_up)
        btn_up = QPushButton("⬇  Обновить yt-dlp")
        btn_up.setToolTip("Скачивает свежую версию yt-dlp (исправляет загрузку, когда YouTube/TikTok ломают старую)")
        btn_up.clicked.connect(self._update_ytdlp)
        vup.addWidget(btn_up)
        hint_up = QLabel("Если перестало качать с YouTube/TikTok — нажмите, чтобы обновить yt-dlp "
                         "(работает для bin/yt-dlp.exe). Результат — в логе программы.")
        hint_up.setStyleSheet("color:#a6adc8; font-size:11px;")
        hint_up.setWordWrap(True)
        vup.addWidget(hint_up)
        lay.addWidget(grp_up)

        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(dlg.accept)
        lay.addWidget(btn_close)
        dlg.exec()

    def _collect_settings(self):
        try:
            tm = self.tab_media; ty = self.tab_ytdlp
            s = {
                'media': {
                    'audio': {
                        'norm': bool(tm.ck_norm.isChecked()), 'tgt': float(tm.s_tgt.value()), 'lra': float(tm.s_lra.value()),
                        'tp': float(tm.s_tp.value()), 'fade': bool(tm.ck_fade.isChecked()), 'fade_d': float(tm.s_fade.value()),
                        'deg': bool(tm.ck_deg.isChecked()), 'hz': int(tm.s_hz.value()), 'u8': bool(tm.ck_u8.isChecked()),
                        'lp': int(tm.s_lp.value()), 'hp': int(tm.s_hp.value()), 'deg_gain_db': float(tm.s_deg_gain.value()),
                        'bitrate': tm.c_abitrate.currentText()
                    },
                    'video': {
                        'enabled': bool(tm.chk_enable_video.isChecked()), 'speed': int(tm.s_spd.value()), 'crf': int(tm.s_crf.value()),
                        'pre': int(tm.s_pre.value()), 'res': tm.c_res.currentText(), 'fps': tm.c_fps.currentText(),
                        'preset_mode': 'dark' if tm.btn_mode_dark.isChecked() else 'std'
                    }
                },
                'ytdlp': {
                    'outdir': ty.out.text(), 'quality': ty.c_q.currentText(), 'merge': ty.c_c.currentText(),
                    'sub_lang': ty.c_s.currentText(), 'audio': ty.c_a.currentText(), 'force_kf': bool(ty.chk_k.isChecked()),
                    'cookie_path': ty.cookie_edit.text().strip(),
                },
                'avif': {
                    'limit': int(tm.s_lim.value()), 'limit_on': bool(tm.ck_lim.isChecked()),
                    'adim': int(tm.s_dim.value()), 'adim_on': bool(tm.ck_dim.isChecked()),
                    'aspd': int(tm.sl_aspd.value()), 'arec': bool(tm.ck_arec.isChecked()),
                    'img_fmt': tm.c_img_fmt.currentText()
                },
                'server_enabled': bool(getattr(self, '_server_enabled', False)),
            }
            return s
        except Exception: return {}

    def _save_settings_now(self):
        try: save_settings(self._collect_settings())
        except Exception as e: self.log(f"save settings error: {e}")

    def _attach_save_handlers(self):
        try:
            tm = self.tab_media
            ty = self.tab_ytdlp
            # Виджеты с сигналом toggled (QCheckBox, QPushButton checkable)
            toggle_widgets = [
                tm.ck_norm, tm.ck_fade, tm.ck_deg, tm.ck_u8,
                tm.chk_enable_video, tm.btn_mode_dark, tm.ck_arec,
                tm.ck_lim, tm.ck_dim,
                ty.chk_k,
            ]
            # Виджеты с сигналом valueChanged (QSpinBox, QDoubleSpinBox, QSlider)
            value_widgets = [
                tm.s_tgt, tm.s_lra, tm.s_tp, tm.s_fade,
                tm.s_hz, tm.s_lp, tm.s_hp, tm.s_deg_gain,
                tm.s_spd, tm.s_crf, tm.s_pre,
                tm.s_lim, tm.s_dim, tm.sl_aspd,
            ]
            # Виджеты с сигналом currentTextChanged (QComboBox)
            combo_widgets = [
                tm.c_abitrate, tm.c_res, tm.c_fps, tm.c_img_fmt,
                ty.c_q, ty.c_c, ty.c_s, ty.c_a,
            ]
            # Виджет с сигналом textChanged (QLineEdit)
            text_widgets = [ty.out, ty.cookie_edit]
            # Сохраняем outdir MediaTab тоже
            try:
                if hasattr(tm, 'out_edit'): text_widgets.append(tm.out_edit)
            except Exception: pass

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
        self.pbar.setValue(val); self.pbar.setFormat(text)

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


def main():
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

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

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
