# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Главное окно: диалог настроек, сохранение, переключатели, ключи API и HTTP-сервер расширения браузера."""
import main as _api


class UnifiedWindowSettingsMixin:
    """Главное окно: диалог настроек, сохранение, переключатели, ключи API и HTTP-сервер расширения браузера."""

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

    def _open_settings_dialog(self, section=None):
        """section — имя раздела, к которому сразу перейти (например, «Ключи API»).

    Кнопки «задан / не задан» ключей обещают открыть именно этот раздел.
    clicked(bool) передаёт сюда False — это «без раздела».
    """
        dlg = _api.QDialog(self)
        dlg.setWindowTitle("Настройки — " + _api.APP_TITLE)
        dlg.setMinimumSize(680, 520)
        outer = _api.QVBoxLayout(dlg); outer.setSpacing(10); outer.setContentsMargins(12, 12, 12, 12)

        # ── Поиск по настройкам ──────────────────────────────────────────────
        search = _api.QLineEdit()
        search.setPlaceholderText("Поиск настроек…")
        search.addAction(_api.get_icon('fa5s.search'),
                         _api.QLineEdit.ActionPosition.LeadingPosition)
        search.setClearButtonEnabled(True)
        outer.addWidget(search)

        body = _api.QHBoxLayout(); body.setSpacing(10)
        outer.addLayout(body, 1)

        # ── Левая навигация (категории) ──────────────────────────────────────
        nav = _api.QListWidget()
        nav.setFixedWidth(160)
        nav.setStyleSheet(
            "QListWidget{background:#181825;border:1px solid #45475a;border-radius:6px;"
            "padding:4px;outline:none;}"
            "QListWidget::item{padding:8px 10px;border-radius:5px;color:#cdd6f4;}"
            "QListWidget::item:selected{background:#89b4fa;color:#1e1e2e;font-weight:bold;}"
            "QListWidget::item:hover:!selected{background:#313244;}")
        body.addWidget(nav)

        # ── Правая прокручиваемая область со всеми секциями ───────────────────
        scroll = _api.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = _api.QWidget(); content_l = _api.QVBoxLayout(content)
        content_l.setContentsMargins(4, 4, 8, 4); content_l.setSpacing(14)
        scroll.setWidget(content)
        body.addWidget(scroll, 1)

        sections = []  # [{'name','widget','header','layout','rows':[(w,keywords)]}]

        def make_section(name):
            sec = _api.QWidget()
            secl = _api.QVBoxLayout(sec); secl.setContentsMargins(0, 0, 0, 0); secl.setSpacing(10)
            hdr = _api.QLabel(name)
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
            lbl = _api.QLabel(text)
            lbl.setStyleSheet("color:#a6adc8; font-size:11px;")
            lbl.setWordWrap(True)
            return lbl

        # ══ Секция «Основное» ════════════════════════════════════════════════
        sec_main = make_section("Основное")

        grp_ui = _api.QGroupBox("Интерфейс")
        vui = _api.QVBoxLayout(grp_ui)
        chk_wheel = _api.QCheckBox("Колёсико мыши меняет значения в полях")
        chk_wheel.setChecked(bool(self._wheel_changes_values))
        chk_wheel.toggled.connect(self._set_wheel_changes_values)
        vui.addWidget(chk_wheel)
        vui.addWidget(hint("Выкл — колёсико над полями прокручивает панель, а не меняет числа."))
        add_row(sec_main, grp_ui, "колесо мышь интерфейс значения прокрутка битрейт ползунки")

        grp_ai = _api.QGroupBox("Фото — нейросети")
        vai = _api.QVBoxLayout(grp_ai)
        chk_keep = _api.QCheckBox("Не выгружать модели нейронок из ОЗУ")
        chk_keep.setChecked(bool(getattr(self, "_keep_models_in_ram", False)))
        chk_keep.toggled.connect(self._set_keep_models_in_ram)
        vai.addWidget(chk_keep)
        vai.addWidget(hint("Выкл (по умолч.): модели удаления объектов/фона выгружаются из памяти "
                           "через минуту простоя или при уходе со вкладки «Фото» (освобождается ~1–2 ГБ; "
                           "следующий запуск ждёт перезагрузку модели). Вкл — держать в ОЗУ всегда (быстрее)."))
        add_row(sec_main, grp_ai, "нейросеть модель озу память выгрузка lama rmbg удаление объект фон фото")

        grp_enc = _api.QGroupBox("Обработка — продвинутые настройки")
        venc = _api.QVBoxLayout(grp_enc)
        chk_adv_enc = _api.QCheckBox("Показывать Тюнинг / Метрику (XPSNR) / CQ-level")
        chk_adv_enc.setChecked(bool(getattr(self, "_show_advanced_encode", False)))
        chk_adv_enc.toggled.connect(self._set_advanced_encode_visible)
        venc.addWidget(chk_adv_enc)
        venc.addWidget(hint("Выкл по умолчанию — три поля скрыты во вкладке «Обработка», "
                            "чтобы не путать в базовом сценарии (используются ручной CRF и CQ по умолчанию). "
                            "Включите, если нужно тонко настроить тюнинг SVT-AV1, авто-подбор CRF по XPSNR "
                            "или ручной уровень качества AVIF."))
        add_row(sec_main, grp_enc, "обработка тюнинг метрика xpsnr cq level cq-level crf продвинутые расширенные")

        # ══ Секция «Монтаж» ══════════════════════════════════════════════════
        sec_edit = make_section("Монтаж")

        grp_keys = _api.QGroupBox("Сочетания обрезки")
        vk = _api.QVBoxLayout(grp_keys)
        te = getattr(self, "tab_edit", None)
        if te is not None and getattr(te, "_ready", False):
            start_seq, end_seq = te.get_trim_shortcuts()

            def _mk_key_row(label_text, init_seq, apply_idx):
                row = _api.QHBoxLayout()
                lbl = _api.QLabel(label_text)
                lbl.setStyleSheet("color:#cdd6f4; font-size:12px;")
                lbl.setFixedWidth(230)
                kse = _api.LatinKeySequenceEdit()
                kse.setKeySequence(_api.QKeySequence(init_seq))
                row.addWidget(lbl); row.addWidget(kse, 1)
                w = _api.QWidget(); w.setLayout(row)
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

            btn_reset = _api.QPushButton("Сбросить по умолчанию (Shift+C / Shift+V)")
            def _reset_keys():
                kse_start.setKeySequence(_api.QKeySequence("Shift+C"))
                kse_end.setKeySequence(_api.QKeySequence("Shift+V"))
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

        # Блок «Покадровая перемотка» убран: скраб-звук теперь всегда включён.

        grp_render = _api.QGroupBox("Видео и оверлеи")
        vr = _api.QVBoxLayout(grp_render)

        # Настройка «Субтитры рендерить прямо в кадр» убрана: зафиксирована
        # значением по умолчанию (рендер в кадр, как в VLC).

        chk_hw = _api.QCheckBox("Аппаратное ускорение видео (H.264 / HEVC)")
        chk_hw.setChecked(bool(getattr(self, "_video_hw_decode", True)))
        chk_hw.toggled.connect(self._set_video_hw_decode)
        vr.addWidget(chk_hw)
        vr.addWidget(hint("Вкл (по умолч.): H.264/HEVC декодируются на видеокарте (D3D11VA/DXVA2) "
                          "— тяжёлые файлы в «Монтаже» играют плавно. Выключите, если прямой AV1 "
                          "(SiQuesterHYX) даёт чёрный экран. Нужен перезапуск."))

        # Настройка «Программный рендер видео» убрана: программный рендер
        # отключён всегда (видео идёт по аппаратному D3D/GL-свопчейну).
        add_row(sec_edit, grp_render, "оверлей fps d3d11 рендер видео аппаратное ускорение hevc h264 dxva декодирование")

        # ══ Секция «Ключи API» ═══════════════════════════════════════════════
        # Единственное место ввода ключей на всю программу: раньше поле висело
        # в каждой вкладке, которой ключ нужен (Генерация аниме-пака), и один и
        # тот же ключ приходилось вбивать по нескольку раз.
        sec_api = make_section("Ключи API")

        def _key_row(box_layout, label_html, placeholder, name, note):
            lbl = _api.QLabel(label_html)
            lbl.setOpenExternalLinks(True)
            lbl.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextBrowserInteraction)
            lbl.setWordWrap(True)
            box_layout.addWidget(lbl)
            ed = _api.QLineEdit(self.get_api_key(name))
            ed.setPlaceholderText(placeholder)
            ed.setEchoMode(_api.QLineEdit.EchoMode.Password)
            ed.setClearButtonEnabled(True)
            ed.textChanged.connect(lambda t, n=name: self.set_api_key(n, t))
            box_layout.addWidget(ed)
            box_layout.addWidget(hint(note))
            return ed

        grp_gemini = _api.QGroupBox("Gemini (Google AI Studio)")
        vg = _api.QVBoxLayout(grp_gemini)
        _key_row(vg,
                 'Бесплатный ключ: <a href="https://aistudio.google.com/apikey" '
                 'style="color:#89b4fa;">aistudio.google.com/apikey</a>',
                 "Ключ Gemini API", "gemini",
                 "Нужен вкладке «Генерация аниме-пака» (сюжет, перевод диалогов). Без "
                 "ключа вкладка работает, просто без этой возможности. Тексты "
                 "уходят в Google.")
        add_row(sec_api, grp_gemini,
                "gemini гемини google ключ api нейросеть повторы сюжет аниме aistudio")

        grp_elevenlabs = _api.QGroupBox("ElevenLabs — озвучка описаний")
        ve = _api.QVBoxLayout(grp_elevenlabs)
        _key_row(ve,
                 '<a href="https://elevenlabs.io/app/settings/api-keys" '
                 'style="color:#89b4fa;">Ключи API ElevenLabs</a>',
                 "Ключ ElevenLabs", "elevenlabs",
                 "Озвучивает вопросы по описанию. Когда квота заканчивается, "
                 "генератор переключается на Google. Ключ в пак не сохраняется.")
        add_row(sec_api, grp_elevenlabs,
                "elevenlabs озвучка описание голос текст речь ключ api")

        grp_subdl = _api.QGroupBox("SubDL — русские субтитры")
        vs = _api.QVBoxLayout(grp_subdl)
        _key_row(vs,
                 'Ключ учётной записи: <a href="https://subdl.com/panel/api" '
                 'style="color:#89b4fa;">subdl.com/panel/api</a>',
                 "Ключ SubDL API", "subdl",
                 "Первый источник вопросов «Диалоги из аниме»: субтитры сразу на "
                 "русском, Gemini не нужен. Когда суточная квота ключа кончится, "
                 "диалоги берутся из Jimaku. Ключ уходит только на api.subdl.com "
                 "и в пак не попадает.")
        add_row(sec_api, grp_subdl,
                "subdl сабдл субтитры русские диалоги аниме ключ api серии")

        grp_jimaku = _api.QGroupBox("Jimaku — субтитры аниме")
        vj = _api.QVBoxLayout(grp_jimaku)
        _key_row(vj,
                 'Ключ учётной записи: <a href="https://jimaku.cc/account" '
                 'style="color:#89b4fa;">jimaku.cc/account</a>',
                 "Ключ Jimaku API", "jimaku",
                 "Нужен только вопросам «Диалоги из аниме». Субтитры ищутся по "
                 "точному AniList ID; Gemini переводит выбранные реплики на "
                 "русский. Ключ уходит только в заголовке запроса и в пак не "
                 "попадает.")
        add_row(sec_api, grp_jimaku,
                "jimaku джимаку субтитры диалоги аниме ключ api серии")

        grp_animelib = _api.QGroupBox("AnimeLIB — отрывки серий")
        _key_row(_api.QVBoxLayout(grp_animelib),
                 'Аккаунт: <a href="https://animelib.org/" style="color:#89b4fa;">animelib.org</a>',
                 "Bearer-токен аккаунта AnimeLIB (необязательно)", "animelib",
                 "Для native-видео, доступных вашему аккаунту. В браузере после входа: "
                 "F12 → Network → запрос к API → Authorization; скопируйте токен после Bearer. "
                 "Без токена проверяются публичные релизы. Токен передаётся только API AnimeLIB "
                 "и в пак не попадает.")
        add_row(sec_api, grp_animelib, "animelib анимелиб аниме отрывки субтитры аккаунт токен")

        grp_tmdb = _api.QGroupBox("TMDB (themoviedb.org)")
        vt = _api.QVBoxLayout(grp_tmdb)
        _key_row(vt,
                 'Бесплатный ключ: <a href="https://www.themoviedb.org/settings/api" '
                 'style="color:#89b4fa;">themoviedb.org → настройки профиля → API</a>',
                 "Ключ TMDB (необязательно)", "tmdb",
                 "ЗАПАСНОЙ источник обложек для вкладок «Генерация аниме-пака» и "
                 "«Апгрейд пака»: идёт в дело там, где у карточки Shikimori "
                 "постера нет вовсе или ссылка не открылась. В кино-паке нужнее "
                 "всего: у Wikidata афиша есть далеко не у каждого фильма. "
                 "Годятся оба вида ключа — старый «API Key» и токен «API Read "
                 "Access». Пусто — обложки берутся только из основной базы.")
        add_row(sec_api, grp_tmdb,
                "tmdb themoviedb обложка постер ключ api аниме запасной источник")

        grp_pixiv = _api.QGroupBox("Pixiv — арты аниме")
        vp = _api.QVBoxLayout(grp_pixiv)
        _key_row(vp,
                 '<a href="https://www.pixiv.net/" style="color:#89b4fa;">Pixiv</a>',
                 "Refresh token Pixiv", "pixiv",
                 "Нужен только для вопросов «Арты Pixiv» в генераторе аниме-пака. "
                 "Используется OAuth refresh token вашей учётной записи; пароль "
                 "приложение не запрашивает и не хранит. R-18 и ИИ-арты можно "
                 "исключить отдельными настройками во вкладке генератора; "
                 "шок-контент блокируется всегда.")
        add_row(sec_api, grp_pixiv,
                "pixiv пиксив арт аниме oauth refresh token ключ api картинки")

        grp_cloudflare = _api.QGroupBox("Cloudflare — ИИ-арты")
        vc = _api.QVBoxLayout(grp_cloudflare)
        account = _key_row(vc, "Account ID", "32 символа из кабинета Cloudflare",
                           "cloudflare_account_id",
                           "Workers AI → Use REST API → Account ID.")
        account.setEchoMode(_api.QLineEdit.EchoMode.Normal)
        _key_row(vc,
                 '<a href="https://developers.cloudflare.com/workers-ai/get-started/rest-api/" '
                 'style="color:#89b4fa;">Как получить токен Cloudflare</a>',
                 "Токен Workers AI", "cloudflare",
                 "Создайте Workers AI API Token с правами Read и Edit. "
                 "Для отображения остатка квоты добавьте Account → Account Analytics → Read. "
                 "Модель выбирается во вкладке генерации аниме-пака. "
                 "На бесплатном плане после исчерпания суточной квоты генерация остановится.")
        add_row(sec_api, grp_cloudflare,
                "cloudflare flux ии арты картинки генерация токен ключ account id")

        # ══ Секция «Экспериментально» (предпоследняя) ════════════════════════
        sec_exp = make_section("Экспериментально")

        grp_sv = _api.QGroupBox("Браузерное расширение")
        vsv = _api.QVBoxLayout(grp_sv)
        chk = _api.QCheckBox(f"Включить локальный сервер (localhost:{_api.HTTP_PORT})")
        chk.setChecked(bool(self._server_enabled))
        chk.toggled.connect(self._set_server_enabled)
        vsv.addWidget(chk)
        vsv.addWidget(hint("Выкл по умолчанию. Включите, чтобы расширение в браузере "
                           "слало ссылки в программу."))
        add_row(sec_exp, grp_sv, "браузер расширение сервер localhost порт ссылки экспериментально")

        grp_siq = _api.QGroupBox("Дополнительные вкладки")
        vexp = _api.QVBoxLayout(grp_siq)
        chk_prompt = _api.QCheckBox("Включить вкладку «Промпт»")
        chk_prompt.setChecked(bool(getattr(self, "_prompt_tab_enabled", False)))
        chk_prompt.toggled.connect(self._set_prompt_tab_enabled)
        vexp.addWidget(chk_prompt)
        vexp.addWidget(hint("Хранение и быстрый выбор промптов."))
        chk_siq = _api.QCheckBox("Включить вкладку «SiQuesterHYX»")
        chk_siq.setChecked(bool(getattr(self, "_siquester_tab_enabled", False)))
        chk_siq.toggled.connect(self._set_siquester_tab_enabled)
        vexp.addWidget(chk_siq)
        vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                            + " Просмотр пакетов .siq и статистики."))
        chk_shiki = _api.QCheckBox("Включить вкладку «ShikimoriHYX»")
        chk_shiki.setChecked(bool(getattr(self, "_shikimori_tab_enabled", False)))
        chk_shiki.toggled.connect(self._set_shikimori_tab_enabled)
        vexp.addWidget(chk_shiki)
        vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                            + " Поиск аниме на Shikimori с фильтрами."))
        chk_lb = _api.QCheckBox("Включить вкладку «ЛидербордHYX»")
        chk_lb.setChecked(bool(getattr(self, "_leaderboard_tab_enabled", False)))
        chk_lb.toggled.connect(self._set_leaderboard_tab_enabled)
        vexp.addWidget(chk_lb)
        vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                            + " Просмотр рекордов из JSON-выгрузки Firebase."))
        chk_coop = _api.QCheckBox("Включить вкладку «Collab»")
        chk_coop.setChecked(bool(getattr(self, "_coop_tab_enabled", False)))
        chk_coop.toggled.connect(self._set_coop_tab_enabled)
        vexp.addWidget(chk_coop)
        vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                            + " Совместное редактирование .siq. Нужен сервер синхронизации."))
        chk_animepack = _api.QCheckBox("Включить вкладку «Генерация аниме-пака»")
        chk_animepack.setChecked(bool(getattr(self, "_animepack_tab_enabled", False)))
        chk_animepack.toggled.connect(self._set_animepack_tab_enabled)
        vexp.addWidget(chk_animepack)
        vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                            + " Создание .siq «угадай аниме по песне». "
                            "На основе ASPG (Leleath), с разрешения автора."))
        chk_ap_upgrade = _api.QCheckBox("Включить вкладку «Апгрейд пака»")
        chk_ap_upgrade.setChecked(
            bool(getattr(self, "_animepack_upgrade_tab_enabled", False)))
        chk_ap_upgrade.toggled.connect(self._set_animepack_upgrade_tab_enabled)
        vexp.addWidget(chk_ap_upgrade)
        vexp.addWidget(hint(_api.icon_html('fa5s.exclamation-triangle', 12, '#f9e2af')
                            + " Добавляет названия и постеры, упрощает вопросы и сжимает медиа. "
                            "Результат сохраняется рядом."))
        add_row(sec_exp, grp_siq,
                "промпт prompt заготовки шаблоны "
                "siquester сиквестер siq пакет вопросы статистика эксперимент вкладка просмотр sigame "
                "shikimori шикимори аниме поиск оценка жанр год api "
                "лидерборд leaderboard рекорды никнеймы firebase счёт ник "
                "collab coop совместная работа пак напарник соавтор реалтайм темы вопросы ответы дубли синхронизация "
                "генерация аниме пак опенинг эндинг песни amq anisongdb myanimelist shikimori aspg угадайка siq "
                "апгрейд доводка спецвопросы с секретом ставка для себя варианты названий ромадзи синонимы "
                "постер в ответе регистр написание названия заглавные буквы "
                "сжать картинки avif вес пака мегабайт")

        # ══ Секция «О программе» ═════════════════════════════════════════════
        sec_about = make_section("О программе")

        grp_up = _api.QGroupBox("Обновления")
        vup = _api.QVBoxLayout(grp_up)
        btn_app_up = _api.QPushButton("Проверить обновления программы")
        btn_app_up.setIcon(_api.get_icon('fa5s.sync-alt'))
        btn_app_up.setIconSize(_api.QSize(20, 20))
        btn_app_up.setToolTip("Проверяет последнюю версию на GitHub и предлагает обновиться")
        btn_app_up.clicked.connect(lambda: self._check_updates(silent=False))
        vup.addWidget(btn_app_up)
        vup.addWidget(hint("При наличии новой версии программа сама скачает её и перезапустится."))
        btn_up = _api.QPushButton("Обновить yt-dlp")
        btn_up.setIcon(_api.get_icon('fa5s.download'))
        btn_up.setIconSize(_api.QSize(20, 20))
        btn_up.setToolTip("Скачивает свежую версию yt-dlp (исправляет загрузку, когда YouTube/TikTok ломают старую)")
        btn_up.clicked.connect(self._update_ytdlp)
        vup.addWidget(btn_up)
        vup.addWidget(hint("Если перестало качать с YouTube/TikTok — нажмите, чтобы обновить yt-dlp "
                           "(работает для bin/yt-dlp.exe)."))
        add_row(sec_about, grp_up, "обновление обновить программа yt-dlp youtube tiktok версия github")

        grp_links = _api.QGroupBox("Ссылки и сообщество")
        vl = _api.QVBoxLayout(grp_links)
        links = _api.QLabel(
            f'Discord: <a href="{_api.DISCORD_URL}" style="color:#89b4fa;">{_api.DISCORD_URL}</a><br>'
            f'GitHub: <a href="{_api.GITHUB_URL}" style="color:#89b4fa;">{_api.GITHUB_URL}</a><br>'
            f'Гайд: <a href="{_api.GUIDE_URL}" style="color:#89b4fa;">{_api.GUIDE_URL}</a><br>'
            'Поддержать автора: <a href="https://www.donationalerts.com/r/goldensfire" '
            'style="color:#89b4fa;">DonationAlerts</a>')
        links.setOpenExternalLinks(True)
        links.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextBrowserInteraction)
        links.setWordWrap(True)
        links.setStyleSheet("color:#a6adc8; font-size:12px;")
        vl.addWidget(links)
        add_row(sec_about, grp_links,
                "discord github ссылки сообщество поддержка поддержать автора донат donationalerts обновления")

        content_l.addStretch(1)

        # ── Навигация ↔ прокрутка (взаимная синхронизация) ───────────────────
        # Клик по категории прокручивает к секции; прокрутка колесом/ползунком
        # подсвечивает категорию активной секции. Флаг гасит рекурсию сигналов.
        syncing = {'v': False}

        def _scroll_to(rec):
            # Раздел — к ВЕРХУ области. ensureWidgetVisible прокручивал
            # минимально: при переходе вниз заголовок вставал у нижнего края,
            # и на экране оставался предыдущий раздел.
            bar = scroll.verticalScrollBar()
            top = rec['widget'].y() - content_l.contentsMargins().top()
            bar.setValue(min(bar.maximum(), max(0, top)))

        def _goto(idx):
            if syncing['v']:
                return
            if 0 <= idx < len(sections):
                syncing['v'] = True
                _scroll_to(sections[idx])
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
        names = [rec['name'] for rec in sections]
        if isinstance(section, str) and section in names:
            # Геометрия разделов готова лишь после показа окна.
            _api.QTimer.singleShot(0, lambda: nav.setCurrentRow(names.index(section)))

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
                content.layout().activate()
                _scroll_to(first_visible)
        search.textChanged.connect(_do_search)

        dlg.exec()

    def _collect_settings(self):
        try:
            tm = self.tab_media; ty = self.tab_ytdlp
            s = {
                'media': {
                    'audio': {
                        'remove': bool(tm.ck_no_audio.isChecked()),
                        'norm': bool(tm.ck_norm.isChecked()), 'tgt': float(tm.s_tgt.value()), 'lra': float(tm.s_lra.value()),
                        'tp': float(tm.s_tp.value()), 'fade': bool(tm.ck_fade.isChecked()), 'fade_d': float(tm.s_fade.value()),
                        'fade_in': bool(tm.ck_fade_in.isChecked()), 'fade_in_d': float(tm.s_fade_in.value()),
                        'deg': bool(tm.ck_deg.isChecked()), 'hz': int(tm.s_hz.value()), 'u8': bool(tm.ck_u8.isChecked()),
                        'lp': int(tm.s_lp.value()), 'hp': int(tm.s_hp.value()), 'deg_gain_db': float(tm.s_deg_gain.value()),
                        'bitrate': tm.c_abitrate.currentText()
                    },
                    'video': {
                        'enabled': bool(tm.chk_enable_video.isChecked()), 'speed': int(tm.s_spd.value()), 'crf': int(tm.s_crf.value()),
                        'pre': int(tm.s_pre.value()), 'res': _api.strip_default_tag(tm.c_res.currentText()), 'fps': tm.c_fps.currentText(),
                        'preset_mode': 'dark' if tm.btn_mode_dark.isChecked() else 'std',
                        'metric': tm._video_metric_value(), 'target_metric': float(tm.s_target_metric.value()),
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
                    'awidth': int(tm.s_width.value()), 'awidth_on': bool(tm.ck_width.isChecked()),
                    'aheight': int(tm.s_height.value()), 'aheight_on': bool(tm.ck_height.isChecked()),
                    'aspd': int(tm.sl_aspd.value()),
                    'cq': int(tm.s_cq.value()),
                    'overwrite_src': bool(tm.ck_overwrite_src.isChecked()) if hasattr(tm, 'ck_overwrite_src') else False,
                    'fit_passes': int(tm.s_passes.value()),
                    'img_fmt': _api.strip_default_tag(tm.c_img_fmt.currentText()),
                    'chroma': _api.strip_default_tag(tm.c_chroma.currentText()).replace(':', '')
                },
                'server_enabled': bool(getattr(self, '_server_enabled', False)),
                'wheel_changes_values': bool(getattr(self, '_wheel_changes_values', False)),
                'video_hw_decode': bool(getattr(self, '_video_hw_decode', True)),
                'keep_models_in_ram': bool(getattr(self, '_keep_models_in_ram', False)),
                'advanced_encode_visible': bool(getattr(self, '_show_advanced_encode', False)),
                'siquester_tab_enabled': bool(getattr(self, '_siquester_tab_enabled', False)),
                'shikimori_tab_enabled': bool(getattr(self, '_shikimori_tab_enabled', False)),
                'shikimori': self._collect_shikimori_settings(),
                'leaderboard_tab_enabled': bool(getattr(self, '_leaderboard_tab_enabled', False)),
                'coop_tab_enabled': bool(getattr(self, '_coop_tab_enabled', False)),
                'coop': self._collect_coop_settings(),
                'animepack_tab_enabled': bool(getattr(self, '_animepack_tab_enabled', False)),
                'animepack': self._collect_animepack_settings(),
                'animepack_upgrade_tab_enabled': bool(
                    getattr(self, '_animepack_upgrade_tab_enabled', False)),
                'animepack_upgrade': self._collect_animepack_upgrade_settings(),
                'prompt_tab_enabled': bool(getattr(self, '_prompt_tab_enabled', False)),
                'priority': tm.c_priority.currentText() if hasattr(tm, 'c_priority') else 'Обычный',
                'prompt_file': getattr(getattr(self, 'tab_prompt', None), '_prompt_path', '') or '',
                'api_keys': {k: str(v or '') for k, v in
                             (getattr(self, '_api_keys', {}) or {}).items()},
                'tab_order': list(getattr(self, '_tab_order', [])),
            }
            return s
        except Exception: return {}

    def _warn_settings_readonly(self):
        """Один раз, уже после появления окна, сообщает, что настройки этого
        запуска не читаются и не сохраняются. Раньше это было полностью молча —
        пользователь видел «все настройки слетели» и, поработав в этом сеансе,
        получал дефолты на диске уже навсегда."""
        def _show():
            try:
                from msgbox import msgbox_warning
                msgbox_warning(
                    self, "Настройки не прочитались",
                    "Файл настроек существует, но открыть его сейчас не удалось "
                    "(мог быть занят другой программой — например, антивирусом — "
                    "или повреждён).\n\n"
                    "Приложение работает на значениях по умолчанию, но НИЧЕГО не "
                    "сохраняет: ваши настройки на диске не тронуты. Перезапустите "
                    "программу — если файл снова читается, всё вернётся.")
            except Exception:
                pass
        try:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, _show)   # после того, как окно показано
        except Exception:
            pass

    def _save_settings_now(self):
        if getattr(self, "_settings_readonly", False):
            # Настройки не прочитались при старте — см. _load_settings.
            self.log("save settings: настройки не прочитались при запуске — "
                     "сохранение отключено до перезапуска (файл не затёрт)")
            return False
        try:
            data = self._collect_settings()
            # _collect_settings возвращает {} при любой ошибке (напр. после
            # изменения кода обращение к ещё не созданному виджету). НЕ пишем
            # пустой словарь — иначе settings.json затирается, и при следующем
            # запуске папка загрузчика и прочие настройки сбрасываются к дефолту.
            if not data:
                self.log("save settings: пустой результат сборки — пропуск (файл не затёрт)")
                return False
            if _api.save_settings(data):
                return True
            self.log("save settings: файл не был обновлён")
            return False
        except Exception as e:
            self.log(f"save settings error: {e}")
            return False

    def _save_settings_soon(self, *_args):
        """Отложенное сохранение (400 мс без изменений). Сохранение висит на
        КАЖДОМ поле, и протяжка ползунка раньше означала десятки полных
        перезаписей settings.json подряд — лишняя нагрузка на диск и лишние окна
        для сбоя ровно в момент подмены файла. Выход из программы и явные
        действия по-прежнему зовут _save_settings_now напрямую."""
        try:
            self._save_timer.start(400)
        except Exception:
            self._save_settings_now()

    def _attach_save_handlers(self):
        try:
            self._save_timer = _api.QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self._save_settings_now)
        except Exception:
            pass
        try:
            tm = self.tab_media
            ty = self.tab_ytdlp
            # Виджеты с сигналом toggled (QCheckBox, QPushButton checkable)
            toggle_widgets = [
                tm.ck_no_audio,
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
                tm.s_lim, tm.s_dim, tm.sl_aspd, tm.s_cq, tm.s_passes,
                tm.s_vfade_in, tm.s_vfade_out,
            ]
            # Виджеты с сигналом currentTextChanged (QComboBox)
            combo_widgets = [
                tm.c_abitrate, tm.c_res, tm.c_fps, tm.c_tune, tm.c_img_fmt, tm.c_priority,
                ty.c_q, ty.c_c, ty.c_s, ty.c_a,
            ]
            # Виджет с сигналом textChanged (QLineEdit)
            text_widgets = [ty.out, ty.cookie_edit, ty.proxy_edit]

            for w in toggle_widgets:
                w.toggled.connect(self._save_settings_soon)
            for w in value_widgets:
                w.valueChanged.connect(self._save_settings_soon)
            for w in combo_widgets:
                w.currentTextChanged.connect(self._save_settings_soon)
            for w in text_widgets:
                w.textChanged.connect(self._save_settings_soon)
        except Exception as e:
            self.log(f"_attach_save_handlers error: {e}")
