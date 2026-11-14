# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SubSearchTab. Public namespace: sub_search_tab."""
import sub_search_tab as _api
from si_hyx_parts.shikimori_tab.pack_exclusion import PackExclusionMixin
from si_hyx_parts.sub_search_tab.layout import SubSearchLayoutMixin


class SubSearchTab(SubSearchLayoutMixin, PackExclusionMixin, _api.QWidget):
    """Вкладка «Поиск по сабам» (по умолчанию выключена, включается в Настройках)."""

    def __init__(self, main_window=None, settings=None):
        super().__init__()
        self.main = main_window
        self._pool = _api.QThreadPool.globalInstance()
        self._worker = None
        self._hits: list = []
        self._rows: dict = {}            # shiki_id -> ResultRow
        self._items: dict = {}           # shiki_id -> QListWidgetItem
        self._thumb_pending: set = set()
        self._started_at = 0.0
        # Исключение паков (общий миксин с ShikimoriHYX).
        self.init_pack_exclusion_state()
        self._collapse_franchise = True  # «Вместе с их франшизами»
        self._franchise_of: dict = {}
        self._build_ui()
        initial = dict(settings if settings is not None else
                       getattr(main_window, "_subsearch_settings", {}) or {})
        try:
            self.apply_settings(initial)
        except Exception:  # noqa: BLE001 — битые настройки не мешают открыть вкладку
            pass
        self._refresh_sources()
        _api.QTimer.singleShot(0, self._refresh_cache_label)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_sources()

    # ── ключи и источники ───────────────────────────────────────────────────
    def _key(self, name: str) -> str:
        getter = getattr(self.main, "get_api_key", None)
        try:
            return str(getter(name) if getter else "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def _keys(self) -> dict:
        return {n: self._key(n) for n in ("subdl", "subsource", "tsdb", "opensubtitles",
                                          "opensubtitles_user", "opensubtitles_password")}

    def _refresh_sources(self):
        keys = self._keys()
        os_parts = [n for n, k in (("ключ", "opensubtitles"), ("логин", "opensubtitles_user"),
                                   ("пароль", "opensubtitles_password")) if not keys[k]]
        state = {
            "subdl": (bool(keys["subdl"]), "ключ из Настроек" if keys["subdl"]
                      else "нужен ключ SubDL"),
            "subsource": (bool(keys["subsource"]), "ключ из Настроек" if keys["subsource"]
                          else "нужен ключ SubSource"),
            "tsdb": (True, "ключ из Настроек" if keys["tsdb"] else "без ключа, 1000/час"),
            "opensubtitles": (not os_parts, "вход из Настроек" if not os_parts
                              else "нужны: " + ", ".join(os_parts)),
        }
        for key, (ok, text) in state.items():
            lbl = self.lbl_src[key]
            lbl.setText(("✓ " if ok else "") + text)
            lbl.setToolTip("" if ok else "Впишите в Настройки → «Ключи API» "
                           "(кнопка «Ключи API…» ниже). Без ключа источник пропускается.")
            lbl.setStyleSheet(f"color:{_api.C['green'] if ok else _api.C['red']}; "
                              "font-size:11px;")

    def _open_keys(self):
        opener = getattr(self.main, "_open_settings_dialog", None)
        if opener is not None:
            opener("Ключи API")
            self._refresh_sources()

    # ── поиск ────────────────────────────────────────────────────────────────
    def _request(self):
        kinds = tuple(k for k, cb in self.chk_kinds.items() if cb.isChecked())
        sources = tuple(k for k, cb in self.chk_src.items() if cb.isChecked())
        lo, hi = self.sp_lvl_min.value(), self.sp_lvl_max.value()
        return _api.engine.SearchRequest(
            phrase=self.ed_phrase.text().strip(),
            max_titles=self.sp_count.value(),
            order=self.cb_order.currentData() or _api.engine.ORDER_EASY,
            level_min=min(lo, hi), level_max=max(lo, hi),
            kinds=kinds, sources=sources,
            cache_only=self.chk_cache_only.isChecked(),
            max_gap=float(self.sp_gap.value()),
            one_per_franchise=self.chk_one_fr.isChecked(),
            first_match_only=self.chk_first.isChecked(),
            files_per_title=self.sp_files.value(),
            keys=self._keys(),
        )

    def start_search(self):
        if self._worker is not None:
            return
        req = self._request()
        if not _api.engine.tokenize(req.phrase):
            _api.msgbox_warning(self, "Поиск по сабам", "Введите фразу для поиска.")
            return
        if not req.kinds:
            _api.msgbox_warning(self, "Поиск по сабам", "Отметьте хотя бы один тип тайтлов.")
            return
        if not req.sources and not req.cache_only:
            _api.msgbox_warning(self, "Поиск по сабам", "Отметьте хотя бы один источник.")
            return
        self.clear_results()
        self.log_box.clear()
        self._log(f"Поиск «{req.phrase}»: {self.cb_order.currentText().lower()}, "
                  f"уровни {req.level_min}–{req.level_max}, "
                  f"тайтлов: {req.max_titles or 'все'}.")
        has_packs = bool(self._excluded or self._excluded_question_texts
                         or self._excluded_shiki_franchises)
        self._worker = _api.SearchWorker(req, self._excluded_ids if has_packs else None, self)
        self._worker.status.connect(self._on_status)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(self._on_progress)
        self._worker.hit.connect(self._on_hit)
        self._worker.finished.connect(self._on_finished)
        self._started_at = _api.time.monotonic()
        self._set_running(True)
        self._worker.start()

    def stop_search(self):
        if self._worker is not None:
            self._worker.stop()
            self.lbl_status.setText("Останавливаю…")

    def _set_running(self, on: bool):
        self.btn_search.setEnabled(not on)
        self.btn_stop.setEnabled(on)
        self.btn_clear.setEnabled(not on)
        self.btn_packs.setEnabled(not on)
        self.btn_packs_shiki.setEnabled(not on)
        self.btn_clear_cache.setEnabled(not on)
        self.progress.setVisible(on)
        if on:
            self.progress.setRange(0, 0)

    def _excluded_ids(self, titles) -> set:
        """Исключение паков для списка тайтлов (зовётся из потока поиска; пока
        он идёт, паки не меняются — кнопки выключены)."""
        for t in titles:
            self._franchise_of[t.id] = t.franchise
        animes = [t.anime for t in titles]
        self._learn_excluded_franchises(animes)
        return {t.id for t in titles if self._is_excluded(t.anime)}

    def _on_status(self, text: str):
        self.lbl_status.setText(text)

    def _on_progress(self, done: int, total: int):
        if total <= 0:
            return
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def _log(self, text: str):
        stamp = _api.time.strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"{stamp}  {text}")

    def _on_hit(self, hit):
        self._hits.append(hit)
        self.lbl_empty.setVisible(False)
        row = _api.ResultRow(hit, len(self._hits))
        item = _api.QListWidgetItem()
        item.setData(_api.Qt.ItemDataRole.UserRole, hit.title.id)
        self.list.addItem(item)
        self.list.setItemWidget(item, row)
        self._fit_row_item(item, row)
        self._rows[hit.title.id] = row
        self._items[hit.title.id] = item
        self._load_poster(hit.title.id, hit.title.anime.image_url)
        self.btn_copy_all.setEnabled(True)
        self.btn_export.setEnabled(True)
        m = hit.matches[0]
        self._log(f"Найдено: {hit.title.anime.title} (уровень {hit.level or '?'}) — "
                  f"«{m['text']}» [{m.get('episode') or '—'}, {m['timecode'][:8]}]")

    def _fit_row_item(self, item, row):
        """Высота строки — по фактической ширине списка: реплики и названия
        переносятся, а sizeHint() считает их в одну строку, и низ карточки
        (кнопка «Свернуть») обрезался."""
        # 4 px — поля ::item (margin: 2px) слева и справа.
        w = max(200, self.list.viewport().width() - 4)
        h = row.heightForWidth(w) if row.hasHeightForWidth() else -1
        if h <= 0:
            row.adjustSize()
            h = row.sizeHint().height()
        item.setSizeHint(_api.QSize(w, h))

    def _resize_row_items(self):
        for aid, row in self._rows.items():
            item = self._items.get(aid)
            if item is not None:
                self._fit_row_item(item, row)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._rows:
            _api.QTimer.singleShot(0, self._resize_row_items)

    def eventFilter(self, obj, event):
        # Появилась/пропала полоса прокрутки — ширина карточек меняется без
        # resizeEvent самой вкладки.
        if (self._rows and event.type() == _api.QEvent.Type.Resize
                and obj is self.list.viewport()):
            _api.QTimer.singleShot(0, self._resize_row_items)
        return super().eventFilter(obj, event)

    def _on_finished(self, summary: dict):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._set_running(False)
        secs = _api.time.monotonic() - self._started_at
        found = len(self._hits)
        if summary.get("error"):
            text = f"Ошибка: {summary['error']}"
        elif summary.get("stopped"):
            text = f"Остановлено. Найдено тайтлов: {found}."
        else:
            text = f"Готово. Найдено тайтлов: {found}."
        text += (f"  Проверено тайтлов: {summary.get('titles', 0)}, файлов: "
                 f"{summary.get('files', 0)} (скачано {summary.get('downloads', 0)})"
                 f", {secs:.0f} с.")
        if summary.get("excluded"):
            text += f"  Исключено паками: {summary['excluded']}."
        self.lbl_status.setText(text)
        self._log(text)
        if summary.get("error"):
            self.btn_log.setChecked(True)
        self._refresh_cache_label()

    def clear_results(self):
        self.list.clear()
        self._hits = []
        self._rows = {}
        self._items = {}
        self.lbl_empty.setVisible(True)
        self.btn_copy_all.setEnabled(False)
        self.btn_export.setEnabled(False)
        if self._worker is None:
            self.lbl_status.setText("Готово к поиску.")

    # ── постеры (общий кэш обложек ShikimoriHYX) ────────────────────────────
    def _load_poster(self, aid: int, url: str):
        pm = _api._load_cover_from_disk(aid)
        if pm is not None:
            self._rows[aid].set_poster(pm)
            return
        if not url or aid in self._thumb_pending:
            return
        self._thumb_pending.add(aid)
        task = _api._ThumbTask(aid, url)
        task.signals.done.connect(self._on_thumb)
        self._pool.start(task)

    def _on_thumb(self, aid: int, data: bytes):
        self._thumb_pending.discard(aid)
        pm = _api.QPixmap()
        if not pm.loadFromData(data):
            return
        pm = pm.scaled(_api._THUMB_W, _api._THUMB_H, _api.Qt.AspectRatioMode.KeepAspectRatio,
                       _api.Qt.TransformationMode.SmoothTransformation)
        _api._save_cover_to_disk(aid, pm)
        row = self._rows.get(aid)
        if row is not None:
            row.set_poster(pm)

    # ── строка: меню, открытие ──────────────────────────────────────────────
    def _row_of(self, item):
        if item is None:
            return None
        return self._rows.get(item.data(_api.Qt.ItemDataRole.UserRole))

    def _open_item(self, item):
        row = self._row_of(item)
        if row is not None and row.anime.url:
            row.open_url(row.anime.url)

    def _row_menu(self, pos):
        row = self._row_of(self.list.itemAt(pos))
        if row is None:
            return
        a = row.anime
        clip = _api.QGuiApplication.clipboard()
        menu = _api.QMenu(self)
        menu.addAction(_api.get_icon("fa5s.copy"), "Копировать название",
                       lambda: clip.setText(a.title))
        if a.name and a.name != a.title:
            menu.addAction(_api.get_icon("fa5s.copy"), "Копировать оригинальное название",
                           lambda: clip.setText(a.name))
        menu.addAction(_api.get_icon("fa5s.copy"), "Копировать строку с репликой",
                       lambda: clip.setText(row.copy_text()))
        menu.addSeparator()
        if a.url:
            menu.addAction(_api.get_icon("fa5s.external-link-alt"), "Открыть на Shikimori",
                           lambda: row.open_url(a.url))
        m = row.hit.matches[0] if row.hit.matches else {}
        if m.get("url"):
            menu.addAction(_api.get_icon("fa5s.file-alt"), "Открыть файл субтитров",
                           lambda: row.open_url(m["url"]))
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _copy_all(self):
        lines = [self._rows[h.title.id].copy_text() for h in self._hits
                 if h.title.id in self._rows]
        if lines:
            _api.QGuiApplication.clipboard().setText("\n".join(lines))
            self.lbl_status.setText(f"Скопировано тайтлов: {len(lines)}.")

    def _export_csv(self):
        if not self._hits:
            return
        path, _ = _api.QFileDialog.getSaveFileName(
            self, "Экспорт CSV", _api.os.path.expanduser("~/sub_search.csv"),
            "CSV (*.csv)")
        if not path:
            return
        cols = ["title", "original", "shikimori_id", "level", "index", "episode",
                "timecode", "text", "matched", "source", "file", "file_url", "shikimori_url"]
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = _api.csv.writer(fh)
                w.writerow(cols)
                for h in self._hits:
                    a = h.title.anime
                    for m in h.matches:
                        w.writerow([a.title, a.name, h.title.id, h.level or "",
                                    int(round(h.index)) if h.index else "",
                                    m.get("episode", ""), m.get("timecode", ""),
                                    m.get("text", ""), m.get("matched", ""),
                                    _api.engine.SOURCE_LABELS.get(m.get("source"), ""),
                                    m.get("file", ""), m.get("url", ""), a.url])
        except OSError as exc:
            _api.msgbox_warning(self, "Экспорт CSV", f"Не удалось сохранить файл:\n{exc}")
            return
        self.lbl_status.setText(f"Сохранено: {path}")

    # ── кэш ──────────────────────────────────────────────────────────────────
    def _refresh_cache_label(self):
        try:
            corpus = _api.engine.Corpus()
            try:
                st = corpus.stats()
            finally:
                corpus.close()
        except Exception as exc:  # noqa: BLE001
            self.lbl_cache.setText(f"Кэш недоступен: {exc}")
            return
        mb = st["bytes"] / (1024 * 1024)
        self.lbl_cache.setText(f"Файлов субтитров: {st['files']}, тайтлов: {st['titles']}, "
                               f"{mb:.1f} МБ.")

    def _clear_cache(self):
        if self._worker is not None:
            return
        answer = _api.msgbox_question(
            self, "Очистить кэш",
            "Удалить все скачанные реплики и ответы источников?\n"
            "Следующий поиск скачает субтитры заново.")
        from PyQt6.QtWidgets import QMessageBox
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            corpus = _api.engine.Corpus()
            try:
                corpus.clear()
            finally:
                corpus.close()
        except Exception as exc:  # noqa: BLE001
            _api.msgbox_warning(self, "Очистить кэш", f"Не удалось очистить кэш:\n{exc}")
        self._refresh_cache_label()

    # ── исключение паков ────────────────────────────────────────────────────
    def _on_packs_changed(self):
        """Паки выбраны — действуют со следующего поиска."""

    def _on_excl_fr_toggled(self, on: bool):
        self._collapse_franchise = bool(on)
        self._name_excluded_memo = {}

    def _packs_from_shikimori(self):
        tab = getattr(self.main, "tab_shikimori", None)
        s = {}
        if tab is not None and hasattr(tab, "get_settings"):
            try:
                s = tab.get_settings()
            except Exception:  # noqa: BLE001
                s = {}
        if not s:
            s = dict(getattr(self.main, "_shikimori_settings", {}) or {})
        names = list(s.get("excluded_packs") or [])
        files = list(s.get("excluded_pack_files") or [])
        self._disabled_pack_files = list(s.get("disabled_pack_files") or [])
        self._restore_packs(names, files)
        if not names and not files:
            self.lbl_packs.setText("В ShikimoriHYX паки не выбраны.")

    # ── настройки ────────────────────────────────────────────────────────────
    def get_settings(self) -> dict:
        return {
            "phrase": self.ed_phrase.text(),
            "count": self.sp_count.value(),
            "order": self.cb_order.currentData(),
            "level_min": self.sp_lvl_min.value(),
            "level_max": self.sp_lvl_max.value(),
            "kinds": [k for k, cb in self.chk_kinds.items() if cb.isChecked()],
            "sources": [k for k, cb in self.chk_src.items() if cb.isChecked()],
            "sources_known": list(self.chk_src),
            "first_match_only": self.chk_first.isChecked(),
            "one_per_franchise": self.chk_one_fr.isChecked(),
            "cache_only": self.chk_cache_only.isChecked(),
            "max_gap": float(self.sp_gap.value()),
            "files_per_title": self.sp_files.value(),
            "exclude_franchises": self.chk_excl_fr.isChecked(),
            "excluded_packs": list(self._excluded_packs),
            "excluded_pack_files": list(self._excluded_pack_files),
            "disabled_pack_files": list(self._disabled_pack_files),
            "packs_initialized": True,
        }

    def apply_settings(self, s: dict):
        s = dict(s or {})
        if "phrase" in s:
            self.ed_phrase.setText(str(s.get("phrase") or ""))
        self.sp_count.setValue(int(s.get("count", 5)))
        idx = self.cb_order.findData(s.get("order", _api.engine.ORDER_EASY))
        if idx >= 0:
            self.cb_order.setCurrentIndex(idx)
        self.sp_lvl_min.setValue(int(s.get("level_min", 1)))
        self.sp_lvl_max.setValue(int(s.get("level_max", 15)))
        if "kinds" in s:
            for k, cb in self.chk_kinds.items():
                cb.setChecked(k in (s.get("kinds") or []))
        if "sources" in s:
            # Источник, которого не было при сохранении (SubSource), — по умолчанию.
            known = set(s.get("sources_known") or ("github", "subdl", "opensubtitles"))
            for k, cb in self.chk_src.items():
                if k in known:
                    cb.setChecked(k in (s.get("sources") or []))
        self.chk_first.setChecked(bool(s.get("first_match_only", True)))
        self.chk_one_fr.setChecked(bool(s.get("one_per_franchise", True)))
        self.chk_cache_only.setChecked(bool(s.get("cache_only", False)))
        self.sp_gap.setValue(float(s.get("max_gap", 3.0)))
        self.sp_files.setValue(int(s.get("files_per_title", 0)))
        self.chk_excl_fr.setChecked(bool(s.get("exclude_franchises", True)))
        if s.get("packs_initialized"):
            self._disabled_pack_files = list(s.get("disabled_pack_files") or [])
            names = list(s.get("excluded_packs") or [])
            files = list(s.get("excluded_pack_files") or [])
            if names or files:
                self._restore_packs(names, files)
            else:
                self._refresh_packs_label()
        else:
            # Первое открытие — тот же набор паков, что в ShikimoriHYX.
            self._packs_from_shikimori()

    # ── закрытие ─────────────────────────────────────────────────────────────
    def cleanup(self):
        worker = self._worker
        if worker is not None:
            worker.stop()
            worker.wait(3.0)
