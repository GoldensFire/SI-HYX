# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Base64Tab: _mask_html. Public namespace: tabs."""
import tabs as _api


def _mask_html(self, html):
    """Диспетчер маскировки: лёгкий режим (галочка) или прежний алгоритм.
        Возвращает ту же тройку (masked, n_in, n_ext)."""
    if self.chk_lite_mask.isChecked():
        return _api.mask_html_js_lite(html)
    return _api.mask_html_js(html)

def _mask_html_action(self):
    """Обработчик кнопки «Замаскировать HTML»: маскирует ВСЕ загруженные
        HTML-файлы. Один — подробный отчёт; несколько — пакетно."""
    htmls = [p for p in (self._html_paths or [])
             if _api.os.path.isfile(p) and self._is_html(p)]
    # Фолбэк на текущий файл, если список пуст (напр. одиночный выбор).
    if not htmls and self._current_path and self._is_html(self._current_path):
        htmls = [self._current_path]
    if len(htmls) >= 2:
        self._mask_paths(htmls)
    else:
        self._mask_current_html()

def _mask_one(self, src):
    """Маскирует один HTML-файл → encoded\\<имя>[_base].html.
        Возвращает (out_path, n_in, n_ext)."""
    masked, n_in, n_ext = self._mask_html(self._read_html(src))
    base, ext = _api.os.path.splitext(_api.os.path.basename(src))
    out_dir = _api.os.path.join(_api.os.path.dirname(src), "encoded")
    _api.os.makedirs(out_dir, exist_ok=True)
    suffix = "_base" if self.chk_rename_html.isChecked() else ""
    out_path = _api.os.path.join(out_dir, base + suffix + ext)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(masked)
    return out_path, n_in, n_ext

def _mask_paths(self, paths):
    """Пакетно маскирует переданный список HTML-файлов (из разных папок)."""
    files = [p for p in paths
             if _api.os.path.isfile(p)
             and _api.os.path.splitext(p)[1].lower() in (".html", ".htm")]
    if not files:
        self.lbl_size.setText(_api.status_html('fa5s.exclamation-triangle', "Среди файлов нет .html", '#f9e2af'))
        return
    if len(files) == 1:
        # Один файл — показываем подробный отчёт как для одиночной маскировки.
        self._set_path(files[0])
        self._mask_current_html()
        return
    done = skipped = errors = 0
    report = [f"🎭 Маскировка HTML-файлов: {len(files)} шт.", ""]
    for src in files:
        try:
            out_path, n_in, n_ext = self._mask_one(src)
            if n_in or n_ext:
                done += 1
                report.append(f"✅ {_api.os.path.basename(src)} — инлайн {n_in}, внешних {n_ext}")
                self.main.log(f"HTML→VK: {_api.os.path.basename(src)} (инлайн {n_in}, внешних {n_ext})")
            else:
                skipped += 1
                report.append(f"➖ {_api.os.path.basename(src)} — нет <script>, копия")
                self.main.log(f"HTML→VK: {_api.os.path.basename(src)} — нет <script>, копия")
        except Exception as ex:
            errors += 1
            report.append(f"❌ {_api.os.path.basename(src)} — {ex}")
            self.main.log(f"HTML→VK: {_api.os.path.basename(src)} — ошибка: {ex}")
    self.txt_out.setPlainText("\n".join(report))
    self.lbl_size.setText(
        _api.status_html('fa5s.check-circle', f"Готово: замаскировано {done}, без скриптов {skipped}, ошибок {errors} → encoded\\", '#a6e3a1'))
    self.main.log(f"HTML→VK: пакет из {len(files)} файлов — {done} замаскировано, "
                  f"{skipped} без скриптов, {errors} ошибок.")

def _mask_current_html(self):
    """Маскирует текущий выбранный HTML-файл → encoded\\<имя>_base.html."""
    path = self._current_path
    if not path or not _api.os.path.isfile(path):
        self.lbl_size.setText(_api.status_html('fa5s.times-circle', "Сначала выберите .html файл", '#f38ba8'))
        self.main.log("HTML→VK: файл не выбран")
        return
    if _api.os.path.splitext(path)[1].lower() not in (".html", ".htm"):
        self.lbl_size.setText(_api.status_html('fa5s.times-circle', "Это не HTML-файл (нужен .html / .htm)", '#f38ba8'))
        self.main.log("HTML→VK: выбран не HTML-файл")
        return
    try:
        lite = self.chk_lite_mask.isChecked()
        out_path, n_in, n_ext = self._mask_one(path)
        if n_in == 0 and n_ext == 0:
            msg = ("В файле нет скриптов с логикой — скопировано как есть" if lite
                   else "В файле нет <script> — скопировано как есть")
            self.lbl_size.setText(_api.status_html('fa5s.exclamation-triangle', msg, '#f9e2af'))
            self.main.log("HTML→VK: прятать нечего, копия")
            return
        if lite:
            what = (f"Спрятано скриптов с кодом: {n_in}\n\n"
                    "Что сделано (лёгкий режим):\n"
                    "• код движка собран в один непрерывный base64-блоб;\n"
                    "• запуск через (0,eval)(decodeURIComponent(escape(atob(…))));\n"
                    "• разметка, картинки, скрипты-данные и внешние <script src> "
                    "оставлены как есть → файл заметно меньше;\n"
                    "• инлайн onclick=… работают (код в глобальной области).")
        else:
            what = (f"Закодировано инлайн-скриптов: {n_in}\n"
                    f"Внешних <script src> → динамическая загрузка: {n_ext}\n\n"
                    "Что сделано:\n"
                    "• теги <script> удалены из разметки;\n"
                    "• тело JS закодировано в base64;\n"
                    "• запуск повешен на onload скрытой картинки;\n"
                    "• инлайн onclick=… сохранены (код исполняется в глобале).")
        self.txt_out.setPlainText(
            "✅ HTML замаскирован под VK" + (" (лёгкий режим)" if lite else "") + "\n"
            f"Исходник:  {_api.os.path.basename(path)}\n"
            f"Результат: encoded\\{_api.os.path.basename(out_path)}\n\n" + what)
        tail = f"спрятано: {n_in}" if lite else f"инлайн: {n_in}, внешних: {n_ext}"
        self.lbl_size.setText(
            _api.status_html('fa5s.check-circle', f"encoded\\{_api.os.path.basename(out_path)}  •  {tail}", '#a6e3a1'))
        self.main.log(f"HTML→VK: {_api.os.path.basename(path)} → {out_path} "
                      f"(инлайн {n_in}, внешних {n_ext})")
    except Exception as ex:
        self.lbl_size.setText(_api.status_html('fa5s.times-circle', f"{ex}", '#f38ba8'))
        self.main.log(f"HTML→VK error: {ex}")

def _mask_folder_html(self):
    """Пакетно маскирует все .html в выбранной папке → подпапка encoded\\."""
    folder = _api.QFileDialog.getExistingDirectory(self, "Папка с HTML-файлами для маскировки", "")
    if not folder:
        return
    try:
        files = [f for f in _api.os.listdir(folder)
                 if f.lower().endswith((".html", ".htm"))]
    except Exception as ex:
        self.lbl_size.setText(_api.status_html('fa5s.times-circle', f"{ex}", '#f38ba8'))
        self.main.log(f"HTML→VK error: {ex}")
        return
    if not files:
        self.lbl_size.setText(_api.status_html('fa5s.exclamation-triangle', "В папке нет .html файлов", '#f9e2af'))
        self.main.log("HTML→VK: в папке нет .html")
        return

    out_dir = _api.os.path.join(folder, "encoded")
    _api.os.makedirs(out_dir, exist_ok=True)
    done = skipped = errors = 0
    report = [f"📁 {folder}", f"→ {out_dir}", ""]
    for name in files:
        src = _api.os.path.join(folder, name)
        try:
            masked, n_in, n_ext = self._mask_html(self._read_html(src))
            stem, ext = _api.os.path.splitext(name)
            suffix = "_base" if self.chk_rename_html.isChecked() else ""
            with open(_api.os.path.join(out_dir, stem + suffix + ext), "w", encoding="utf-8") as f:
                f.write(masked)
            if n_in or n_ext:
                done += 1
                report.append(f"✅ {name} — инлайн {n_in}, внешних {n_ext}")
                self.main.log(f"HTML→VK: {name} (инлайн {n_in}, внешних {n_ext})")
            else:
                skipped += 1
                report.append(f"➖ {name} — нет <script>, скопировано как есть")
                self.main.log(f"HTML→VK: {name} — нет <script>, копия")
        except Exception as ex:
            errors += 1
            report.append(f"❌ {name} — {ex}")
            self.main.log(f"HTML→VK: {name} — ошибка: {ex}")

    self.txt_out.setPlainText("\n".join(report))
    self.lbl_size.setText(_api.status_html('fa5s.check-circle',
        f"Готово: замаскировано {done}, без скриптов {skipped}, ошибок {errors} → encoded\\", '#a6e3a1'))
    self.main.log(f"HTML→VK: папка обработана — {done} замаскировано, "
                  f"{skipped} без скриптов, {errors} ошибок. Результат: {out_dir}")

# ── Кодирование ──────────────────────────────────────────────────────────
def _start_encode(self):
    path = self._current_path
    if not path or not _api.os.path.isfile(path):
        self.main.log("Base64: файл не выбран или не существует")
        return
    self._stop_flag.clear()
    self.txt_out.clear()
    self.lbl_size.setText("Чтение файла…")
    self.progress.setValue(0)
    self.progress.show()
    make_txt = self.chk_make_txt.isChecked()  # читаем до старта потока

    def _worker():
        try:
            total = _api.os.path.getsize(path)
            CHUNK = 256 * 1024  # 256 КБ
            chunks = []
            read = 0
            with open(path, "rb") as f:
                while True:
                    if self._stop_flag.is_set():
                        self._sig_error.emit("Отменено пользователем")
                        return
                    chunk = f.read(CHUNK)
                    if not chunk: break
                    chunks.append(chunk)
                    read += len(chunk)
                    pct = int(read * 100 / total) if total else 0
                    self._sig_progress.emit(pct)

            raw = b"".join(chunks)
            if self._stop_flag.is_set():
                self._sig_error.emit("Отменено пользователем")
                return

            b64 = _api.base64.b64encode(raw).decode("ascii")

            txt_path = ""
            if make_txt:
                base_name = _api.os.path.splitext(_api.os.path.basename(path))[0]
                txt_path = _api.os.path.join(_api.os.path.dirname(path), base_name + "_base64.txt")
                with open(txt_path, "w", encoding="ascii") as f:
                    f.write(b64)

            size_kb = len(b64) / 1024
            size_str = (f"{size_kb/1024:.2f} МБ" if size_kb >= 1024 else f"{size_kb:.1f} КБ")
            self._sig_done.emit(b64, size_str, txt_path)
        except Exception as ex:
            self._sig_error.emit(str(ex))

    _api.threading.Thread(target=_worker, daemon=True).start()

def _clear_result(self):
    """Очищает поле результата, сбрасывает превью и прогресс."""
    self._stop_flag.set()  # останавливает фоновый поток если идёт кодирование
    self.txt_out.clear()
    self.lbl_size.setText("")
    self.lbl_fname.setText("Файл не выбран")
    self.lbl_thumb.setPixmap(_api.QPixmap())
    self.lbl_thumb.setText("нет\nфайла")
    self.lbl_thumb.setStyleSheet(
        "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; color:#6c7086; font-size:11px;")
    self.lbl_hint.show()
    self.progress.hide()
    self.progress.setValue(0)
    self._current_path = ""

def _on_done(self, b64: str, size_str: str, txt_path: str):
    self.txt_out.setPlainText(b64)
    self.progress.setValue(100)
    self.progress.hide()
    # Автокопирование в буфер обмена
    _api.QApplication.clipboard().setText(b64)
    if txt_path:
        self.lbl_size.setText(_api.status_html('fa5s.check-circle', f"Скопировано! Размер: {size_str}  •  {_api.os.path.basename(txt_path)}", '#a6e3a1'))
        self.main.log(f"Base64 готов ({size_str}), скопирован в буфер, сохранён: {txt_path}")
    else:
        self.lbl_size.setText(_api.status_html('fa5s.check-circle', f"Скопировано! Размер: {size_str}", '#a6e3a1'))
        self.main.log(f"Base64 готов ({size_str}), скопирован в буфер")

def _on_error(self, msg: str):
    self.lbl_size.setText(_api.status_html('fa5s.times-circle', f"{msg}", '#f38ba8'))
    self.progress.hide()
    self.main.log(f"Base64: {msg}")
