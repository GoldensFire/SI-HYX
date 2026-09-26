# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: _start_browser_http_server. Public namespace: main."""
import main as _api


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
    PORT = _api.HTTP_PORT

    class _Handler(BaseHTTPRequestHandler):
        # Разрешаем только запросы из расширения браузера. Origin браузер
        # проставляет сам — со страницы его из JS не подделать, поэтому это
        # надёжно отсекает «любой сайт дёргает наши эндпоинты», не требуя
        # изменений в расширении (оно шлёт chrome-extension://… Origin).
        # fullmatch + строгий набор символов (без CR/LF и прочих управляющих)
        # — Origin отражается в заголовок ответа, поэтому он обязан быть без
        # переводов строки (защита от HTTP response splitting).
        _EXT_ORIGIN_RX = _api.re.compile(
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
            return _api.re.sub(r"[\x00-\x1f]", "", value)

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
            name = _api.os.path.basename((name or "").strip().replace("\\", "/").split("/")[-1])
            name = _api.re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
            return name or fallback

        @staticmethod
        def _safe_out_path(out_dir: str, filename: str) -> str:
            """Строит путь записи внутри out_dir и нормализацией+проверкой
                префикса гарантирует, что результат не выходит за пределы out_dir
                (защита от path traversal, CWE-22). filename уже очищен
                _safe_name, но явная проверка не зависит от его реализации."""
            base = _api.os.path.realpath(out_dir)
            full = _api.os.path.realpath(_api.os.path.join(base, _api.os.path.basename(filename)))
            if not full.startswith(base + _api.os.sep):
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
                    if not out_dir or not _api.os.path.isdir(out_dir):
                        out_dir = str(_api.Path.home())
                    out_path = self._safe_out_path(out_dir, filename)
                    if _api.os.path.exists(out_path):
                        base_n, ext_n = _api.os.path.splitext(filename)
                        out_path = self._safe_out_path(out_dir, f"{base_n}_{int(_api.time.time())}{ext_n}")
                    with open(out_path, "wb") as fout:
                        fout.write(img_bytes)
                    win.url_from_browser.emit(f"__screenshot_saved__{out_path}", False)
                    self.send_response(200); self._send_cors()
                    self.send_header("Content-Type", "application/json"); self.end_headers()
                    self.wfile.write(_api.json.dumps({"ok": True, "path": out_path}).encode())
                    return

                # Для остальных эндпоинтов — JSON
                body = self.rfile.read(length).decode("utf-8", errors="replace")
                data = _api.json.loads(body)

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
                    if not _api.re.match(r'^https?://', img_url, _api.re.I):
                        self.send_response(400); self._send_cors(); self.end_headers()
                        self.wfile.write(b'{"ok":false,"error":"only http(s) urls allowed"}'); return
                    try:
                        out_dir = win.tab_ytdlp.out.text().strip()
                    except Exception:
                        out_dir = ""
                    if not out_dir or not _api.os.path.isdir(out_dir):
                        out_dir = str(_api.Path.home())
                    out_path = self._safe_out_path(out_dir, filename)
                    if _api.os.path.exists(out_path):
                        base_n, ext_n = _api.os.path.splitext(filename)
                        out_path = self._safe_out_path(out_dir, f"{base_n}_{int(_api.time.time())}{ext_n}")
                    with _api.http_get(img_url, headers={"User-Agent": _api.USER_AGENT, "Referer": img_url}, timeout=30) as resp:
                        img_bytes = resp.read(200 * 1024 * 1024)  # лимит 200 МБ
                    with open(out_path, "wb") as fout:
                        fout.write(img_bytes)
                    win.url_from_browser.emit(f"__screenshot_saved__{out_path}", False)
                    self.send_response(200); self._send_cors()
                    self.send_header("Content-Type", "application/json"); self.end_headers()
                    self.wfile.write(_api.json.dumps({"ok": True, "path": out_path}).encode())
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
                    self.wfile.write(_api.json.dumps({"ok": False, "error": str(ex)}).encode())
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
    t = _api.threading.Thread(target=srv.serve_forever, daemon=True, name="BrowserHTTP")
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

def _set_video_hw_decode(self, checked: bool):
    self._video_hw_decode = bool(checked)
    try: self._save_settings_now()
    except Exception: pass

def _set_advanced_encode_visible(self, checked: bool):
    self._show_advanced_encode = bool(checked)
    try: self.tab_media.set_advanced_encode_visible(self._show_advanced_encode)
    except Exception: pass
    try: self._save_settings_now()
    except Exception: pass

def _set_keep_models_in_ram(self, checked: bool):
    self._keep_models_in_ram = bool(checked)
    try: self.tab_photo.inpaint.set_keep_models(self._keep_models_in_ram)
    except Exception: pass
    try: self._save_settings_now()
    except Exception: pass

# ------------------------------------------------------------------
# Ключи внешних API — одно место на всю программу (Настройки → «Ключи API»)
# ------------------------------------------------------------------
def get_api_key(self, name: str) -> str:
    """Ключ по имени ('gemini' / 'tmdb'); пусто, если не задан."""
    return str((getattr(self, "_api_keys", None) or {}).get(name, "") or "").strip()

def set_api_key(self, name: str, value: str, save: bool = True):
    if not hasattr(self, "_api_keys") or self._api_keys is None:
        self._api_keys = {}
    self._api_keys[name] = str(value or "").strip()
    if save:
        try: self._save_settings_soon()
        except Exception: pass
