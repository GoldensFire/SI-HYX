# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: _add_animepack_tab. Public namespace: main."""
import main as _api


# ------------------------------------------------------------------
# Экспериментальная вкладка Генерация аниме-пака (порт ASPG)
# ------------------------------------------------------------------
def _add_animepack_tab(self):
    """Создаёт и добавляет вкладку Генерация аниме-пака (если ещё не
        добавлена). Импорт ленивый — модуль тянется только когда включена."""
    if getattr(self, "tab_animepack", None) is not None:
        return
    try:
        from animepack_tab import AnimePackTab
        self.tab_animepack = AnimePackTab(
            self, dict(getattr(self, "_animepack_settings", {}) or {}))
        self._add_tab(self.tab_animepack, 'animepack')
        self._apply_tab_order(getattr(self, "_tab_order", []))
    except Exception as e:
        self.tab_animepack = None
        self.log(f"Не удалось добавить вкладку Генерация аниме-пака: {e}")

def _remove_animepack_tab(self):
    t = getattr(self, "tab_animepack", None)
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
    self.tab_animepack = None

def _set_animepack_tab_enabled(self, checked: bool):
    self._animepack_tab_enabled = bool(checked)
    if checked:
        self._add_animepack_tab()
    else:
        # Перед закрытием запоминаем текущие настройки генератора.
        self._animepack_settings = self._collect_animepack_settings()
        self._remove_animepack_tab()
    try: self._save_settings_now()
    except Exception: pass

def _collect_animepack_settings(self):
    """Актуальные настройки вкладки Генерация аниме-пака (или последние
        сохранённые, если вкладка сейчас не открыта)."""
    t = getattr(self, "tab_animepack", None)
    if t is not None and hasattr(t, "get_settings"):
        try:
            return t.get_settings()
        except Exception:
            pass
    return dict(getattr(self, "_animepack_settings", {}) or {})

# ------------------------------------------------------------------
# Экспериментальная вкладка Апгрейд пака
# ------------------------------------------------------------------
def _add_animepack_upgrade_tab(self):
    """Создаёт и добавляет вкладку Апгрейд пака (если ещё не
        добавлена). Импорт ленивый — модуль тянется только когда включена."""
    if getattr(self, "tab_animepack_upgrade", None) is not None:
        return
    try:
        from animepack_upgrade_tab import AnimePackUpgradeTab
        self.tab_animepack_upgrade = AnimePackUpgradeTab(
            self, dict(getattr(self, "_animepack_upgrade_settings", {}) or {}))
        self._add_tab(self.tab_animepack_upgrade, 'animepack_upgrade')
        self._apply_tab_order(getattr(self, "_tab_order", []))
    except Exception as e:
        self.tab_animepack_upgrade = None
        self.log(f"Не удалось добавить вкладку Апгрейд пака: {e}")

def _remove_animepack_upgrade_tab(self):
    t = getattr(self, "tab_animepack_upgrade", None)
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
    self.tab_animepack_upgrade = None

def _set_animepack_upgrade_tab_enabled(self, checked: bool):
    self._animepack_upgrade_tab_enabled = bool(checked)
    if checked:
        self._add_animepack_upgrade_tab()
    else:
        # Перед закрытием запоминаем настройки доводки.
        self._animepack_upgrade_settings = \
            self._collect_animepack_upgrade_settings()
        self._remove_animepack_upgrade_tab()
    try: self._save_settings_now()
    except Exception: pass

def _collect_animepack_upgrade_settings(self):
    """Актуальные настройки вкладки Апгрейд пака (или последние
        сохранённые, если вкладка сейчас не открыта)."""
    t = getattr(self, "tab_animepack_upgrade", None)
    if t is not None and hasattr(t, "get_settings"):
        try:
            return t.get_settings()
        except Exception:
            pass
    return dict(getattr(self, "_animepack_upgrade_settings", {}) or {})

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
