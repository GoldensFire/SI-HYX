# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Главное окно: обновление yt-dlp и самого приложения."""
import main as _api


class UnifiedWindowUpdatesMixin:
    """Главное окно: обновление yt-dlp и самого приложения."""

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
        base = _api.ytdlp_base_cmd()
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
                p = _api.subprocess.run([exe, "--update-to", "nightly"],
                                   stdout=_api.subprocess.PIPE, stderr=_api.subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=_api.CREATE_NO_WINDOW, timeout=180)
                for ln in (p.stdout or "").splitlines():
                    if ln.strip():
                        self.log_signal.emit(ln.strip())
                self.log_signal.emit("Готово (обновление yt-dlp).")
            except Exception as e:
                self.log_signal.emit(f"Ошибка обновления yt-dlp: {e}")

        _api.threading.Thread(target=_run, daemon=True).start()

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
                api = (f"https://api.github.com/repos/{_api.GITHUB_OWNER}/{_api.GITHUB_REPO}"
                       f"/releases?per_page=10")
                with _api.http_get(api, headers={
                    "User-Agent": _api.APP_NAME,
                    "Accept": "application/vnd.github+json",
                }, timeout=15, allow_insecure=False) as r:
                    releases = _api.json.loads(r.read().decode("utf-8", "replace"))
                if not isinstance(releases, list):
                    releases = []

                # Находим самый свежий не-черновик с zip-ассетом и наибольшей версией
                best_tag, best_ver, best_rel = "", (0,), None
                for rel in releases:
                    if rel.get("draft"):
                        continue
                    tag = rel.get("tag_name") or rel.get("name") or ""
                    ver = _api.parse_version(tag)
                    has_zip = any(str(a.get("name", "")).lower().endswith(".zip")
                                  for a in rel.get("assets", []))
                    if has_zip and ver > best_ver:
                        best_ver, best_tag, best_rel = ver, tag, rel

                if best_rel is not None and best_ver > _api.parse_version(_api.APP_VERSION):
                    # Выбираем ассет умно: только код (update-архив), если bin не
                    # менялся, иначе полный zip (см. _pick_update_asset). Третьим
                    # элементом — ожидаемый sha256, четвёртым — флаг «необязательное
                    # обновление» (manifest["silent"]): такой релиз остаётся обычным
                    # (не pre-release, не draft) — новые пользователи с GitHub качают
                    # именно его, — но тихая (авто) проверка при запуске программы
                    # НЕ показывает плашку; узнать о нём можно только вручную, кнопкой
                    # «Проверить обновления».
                    best_url, best_size, best_sha, best_silent = self._pick_update_asset(best_rel)
                    if best_url:
                        if silent and best_silent:
                            return
                        # запоминаем, тихая ли это проверка — слот решает, уважать ли «пропуск»
                        self._check_was_silent = silent
                        changelog = str(best_rel.get("body") or "").strip()
                        self.update_available_sig.emit(
                            best_tag, best_url, best_size, best_sha, changelog)
                    elif not silent:
                        self.log_signal.emit("Обновление найдено, но подходящий ассет не найден.")
                elif not silent:
                    self.log_signal.emit(
                        f"Обновлений нет. Текущая версия: {_api.APP_VERSION}"
                        f" (последняя: {best_tag or '—'}).")
            except Exception as e:
                if not silent:
                    self.log_signal.emit(f"Не удалось проверить обновления: {e}")

        _api.threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _local_bin_sha() -> str:
        """Хеш текущего набора bin — читаем из bin/.binver рядом с программой.
        Пусто, если файла нет (старая установка без манифеста) → значит «bin
        неизвестен», и обновление возьмёт полный zip."""
        try:
            if getattr(_api.sys, "frozen", False):
                app_dir = _api.os.path.dirname(_api.os.path.abspath(_api.sys.executable))
            else:
                app_dir = _api.os.path.dirname(_api.os.path.abspath(_api.__file__))
            with open(_api.os.path.join(app_dir, "bin", ".binver"), encoding="ascii") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _pick_update_asset(self, rel):
        """Решает, что качать из релиза, экономя трафик:
        • update-архив (только код, ~десятки МБ) — если bin не изменился
          (manifest.bin_sha == локальный bin/.binver);
        • full-архив (код + bin, ~сотни МБ) — если bin изменился, либо релиз
          старого формата (нет manifest.json / update-архива).
        Возвращает (url, size_bytes, sha256, silent). sha256 — ожидаемый хеш
        выбранного архива из manifest (для проверки после загрузки); "" если
        проверить нечем (старый формат / нет хеша в manifest). silent — флаг
        manifest["silent"]: True у релиза, помеченного «необязательным» (см.
        _check_updates) — старый формат релиза (без manifest) всегда даёт
        False, т.е. ведёт себя как обычное обязательное обновление."""
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
            return (z.get("browser_download_url", ""), int(z.get("size", 0) or 0), "", False) if z else ("", 0, "", False)

        # Читаем manifest: bin_sha (что качать) + update_sha/full_sha (что проверять)
        # + silent (необязательное обновление — см. _check_updates).
        man = {}
        try:
            with _api.http_get(manifest.get("browser_download_url", ""),
                          headers={"User-Agent": _api.APP_NAME}, timeout=15,
                          allow_insecure=False) as r:
                man = _api.json.loads(r.read().decode("utf-8", "replace")) or {}
        except Exception:
            man = {}
        remote_bin_sha = man.get("bin_sha", "") or ""
        is_silent = bool(man.get("silent", False))

        bin_unchanged = bool(remote_bin_sha) and remote_bin_sha == self._local_bin_sha()
        if bin_unchanged and update_asset:
            self.log_signal.emit("Обновление: bin не изменился — качаем только update-часть (меньше трафика).")
            chosen, sha = update_asset, (man.get("update_sha", "") or "")
        else:
            chosen = full_asset or update_asset
            sha = (man.get("full_sha", "") or "") if chosen is full_asset else (man.get("update_sha", "") or "")
        return (chosen.get("browser_download_url", ""), int(chosen.get("size", 0) or 0), sha, is_silent) if chosen else ("", 0, "", False)

    def _skip_file(self):
        return _api.os.path.join(_api.CONFIG_DIR, "skipped_update.txt")

    def _load_skipped_version(self):
        try:
            with open(self._skip_file(), encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _save_skipped_version(self, version: str):
        try:
            _api.os.makedirs(_api.CONFIG_DIR, exist_ok=True)
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

    def _on_update_available(self, version: str, url: str, size: int,
                             sha: str = "", changelog: str = ""):
        if getattr(self, "_updating", False):
            return
        # Пропущенную версию не показываем при ТИХОЙ (авто) проверке; ручная
        # проверка («Проверить обновления») показывает баннер всегда.
        if (version and version == self._skipped_update_version
                and getattr(self, "_check_was_silent", True)):
            return
        if not getattr(_api.sys, "frozen", False):
            self.log(f"Доступна новая версия {version}, но автоустановка работает "
                     f"только в собранной программе (.exe). Скачайте вручную.")
            return
        sz = f"~{size/1024/1024:.0f} МБ" if size else "размер неизвестен"
        self._pending_update_url = url
        self._pending_update_version = version
        self._pending_update_sha = sha or ""
        self._pending_update_changelog = changelog or ""
        self.update_banner_lbl.setText(
            f"Доступна новая версия {version} ({sz}). "
            f"Программа обновится и перезапустится.")
        self.btn_changelog.setVisible(bool(self._pending_update_changelog))
        self.update_banner.setVisible(True)

    def _on_banner_update(self):
        self.update_banner.setVisible(False)
        if self._pending_update_url:
            self._start_update_download(self._pending_update_url)

    def _show_changelog(self):
        """Окно со списком изменений релиза (тело релиза с GitHub releases,
        обычно Markdown — рендерим как Markdown)."""
        text = (self._pending_update_changelog or "").strip()
        if not text:
            return
        ver = self._pending_update_version or ""
        dlg = _api.QDialog(self)
        dlg.setWindowTitle(f"Что нового — {ver}" if ver else "Что нового")
        dlg.setWindowFlag(_api.Qt.WindowType.WindowMaximizeButtonHint, True)
        v = _api.QVBoxLayout(dlg); v.setContentsMargins(12, 12, 12, 12); v.setSpacing(8)
        view = _api.QTextEdit(dlg); view.setReadOnly(True)
        try:
            view.setMarkdown(text)        # GitHub-тело релиза — Markdown
        except Exception:
            view.setPlainText(text)       # на всякий случай — как есть
        v.addWidget(view)
        row = _api.QHBoxLayout(); row.addStretch(1)
        btn_close = _api.QPushButton("Закрыть", dlg)
        btn_close.clicked.connect(dlg.close)
        row.addWidget(btn_close)
        v.addLayout(row)
        g = self.geometry()
        dlg.resize(max(560, int(g.width() * 0.6)), max(420, int(g.height() * 0.7)))
        dlg.move(g.x() + (g.width() - dlg.width()) // 2,
                 g.y() + (g.height() - dlg.height()) // 2)
        dlg.exec()

    def _start_update_download(self, url: str):
        if getattr(self, "_updating", False):
            return
        self._updating = True
        self.log("Скачивание обновления…")

        def _run():
            try:
                tmp = _api.os.path.join(_api.tempfile.gettempdir(), "sihyx_update")
                _api.shutil.rmtree(tmp, ignore_errors=True)
                _api.os.makedirs(tmp, exist_ok=True)
                zip_path = _api.os.path.join(tmp, "update.zip")

                with _api.http_get(url, headers={"User-Agent": _api.APP_NAME}, timeout=60,
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
                    h = _api.hashlib.sha256()
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
                extract_dir = _api.os.path.join(tmp, "extracted")
                import zipfile
                with zipfile.ZipFile(zip_path) as z:
                    z.extractall(extract_dir)

                src_root = self._find_exe_root(extract_dir)
                if not src_root:
                    self.log_signal.emit("Ошибка обновления: в архиве не найден "
                                         f"{_api.APP_NAME}.exe.")
                    self._updating = False
                    return
                self.update_ready_sig.emit(src_root)
            except Exception as e:
                self.log_signal.emit(f"Ошибка обновления: {e}")
                self._updating = False

        _api.threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _find_exe_root(root: str):
        """Ищет каталог, в котором лежит SI-HYX.exe, внутри распакованного архива."""
        target = _api.APP_NAME + ".exe"
        for dirpath, _dirs, files in _api.os.walk(root):
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
            app_dir = _api.os.path.dirname(_api.os.path.abspath(_api.sys.executable))
            exe_path = _api.os.path.abspath(_api.sys.executable)
            upd_dir = _api.os.path.join(_api.tempfile.gettempdir(), "sihyx_update")
            _api.os.makedirs(upd_dir, exist_ok=True)
            ps_path = _api.os.path.join(upd_dir, "apply_update.ps1")
            cmd_path = _api.os.path.join(upd_dir, "run_updater.cmd")
            log_path = _api.os.path.join(upd_dir, "update_log.txt")
            lock_path = _api.os.path.join(upd_dir, "updater.lock")
            for _p in (log_path, lock_path):
                try:
                    if _api.os.path.exists(_p): _api.os.remove(_p)
                except Exception: pass

            def q(s):  # безопасная одинарно-кавыченная строка PowerShell
                return "'" + str(s).replace("'", "''") + "'"

            task_name = "SIHYX_SelfUpdate"
            launch_task = task_name + "_Launch"
            relaunch_path = _api.os.path.join(upd_dir, "relaunch.cmd")
            register_path = _api.os.path.join(upd_dir, "register.cmd")
            leaf = _api.os.path.basename(exe_path)
            src_exe = _api.os.path.join(src_root, leaf)
            # Время триггера задач (в будущем). Реально задачи запускаются через
            # schtasks /Run; авто-срабатывание по /ST безвредно — у программы
            # single-instance (повторный старт просто закроется).
            st = _api.time.strftime("%H:%M", _api.time.localtime(_api.time.time() + 120))

            # Параметры «зашиты» в скрипт (а не через -args) — запускается и
            # Планировщиком, и напрямую, без возни с кавычками в путях.
            hdr = (
                "$AppPid=" + str(int(_api.os.getpid())) + "\n"
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
            _api.QTimer.singleShot(700, lambda: _api.os._exit(0))
        except Exception as e:
            self._updating = False
            self.log(f"Ошибка применения обновления: {e}")

    def _spawn_updater(self, task_name, register_cmd, ps_path):
        """Запускает апдейтер ВНЕ job-объекта программы. Основной путь —
        Планировщик задач через register.cmd (служба исполняет задачу в своей
        сессии, job родителя на неё не влияет — работает даже в Win Sandbox).
        Фолбэк — обычный detached Popen (+breakaway) для машин без жёсткого job."""
        flags = getattr(_api.subprocess, "CREATE_NO_WINDOW", 0)
        # 1) Планировщик задач (register.cmd сам делает /Create и /Run)
        try:
            # encoding задан явно, как и везде в проекте: без него Python берёт
            # кодировку системной локали (cp1251 на русской Windows, cp1252 на
            # английской) — поведение зависело бы от языка системы пользователя.
            # Вывод здесь не разбирается, важен только returncode; если он всё
            # же понадобится — учесть, что cmd/schtasks пишут в OEM-кодировку
            # консоли, и errors="replace" превратит кириллицу в «?».
            _api.subprocess.run(["cmd", "/c", register_cmd], creationflags=flags,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
            chk = _api.subprocess.run(["schtasks", "/Query", "/TN", task_name],
                                 creationflags=flags, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=15)
            if chk.returncode == 0:
                self.log("Апдейтер запущен через Планировщик задач (вне job-объекта).")
                return True
            self.log("Планировщик: задача не зарегистрирована — пробую прямой запуск.")
        except Exception as e:
            self.log(f"Планировщик задач недоступен ({e}); пробую прямой запуск.")
        # 2) Фолбэк: detached Popen (+breakaway) — для обычных машин без жёсткого job
        try:
            DETACHED = getattr(_api.subprocess, "DETACHED_PROCESS", 0)
            NEWGRP = getattr(_api.subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            BREAKAWAY = getattr(_api.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
            args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-WindowStyle", "Hidden", "-File", ps_path]
            try:
                _api.subprocess.Popen(args, creationflags=DETACHED | NEWGRP | BREAKAWAY, close_fds=True)
            except OSError:
                _api.subprocess.Popen(args, creationflags=DETACHED | NEWGRP, close_fds=True)
            self.log("Апдейтер запущен напрямую (detached).")
            return True
        except Exception as e:
            self.log(f"Не удалось запустить апдейтер: {e}")
            return False
