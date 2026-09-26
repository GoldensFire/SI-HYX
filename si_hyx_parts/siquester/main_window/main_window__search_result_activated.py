# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MainWindow: _search_result_activated. Public namespace: siquester.main_window."""
import siquester.main_window as _api


def _search_result_activated(self, item: _api.QListWidgetItem):
    data = item.data(_api.Qt.ItemDataRole.UserRole)
    if not data: return
    ds_idx, ri, ti, price = data
    if not (0 <= ds_idx < len(self.datasets)): return
    self.sidebar.select_by_real(ds_idx)
    self._show_ds(ds_idx)
    if price >= 0:
        w = self.datasets[ds_idx]["widget"]
        def _nav(ri=ri, ti=ti, p=price, rp=w):
            rp._on_question_clicked(ri, ti, p)
            drop_area = rp._drop_area_index.get((ri, ti))
            if drop_area is None: return
            try:
                drop_area.select_tile(p)
                tile_global = drop_area.mapToGlobal(drop_area.rect().topLeft())
                content_local = rp._content_widget.mapFromGlobal(tile_global)
                rp._scroll.verticalScrollBar().setValue(
                    max(0, content_local.y() - 80))
            except Exception:
                pass
        _api.QTimer.singleShot(80, _nav)
    # Close the search panel after navigating
    self._hide_search()

def eventFilter(self, obj, event):
    # ── Close panels on click outside ─────────────────────────
    if event.type() == _api.QEvent.Type.MouseButtonPress:
        if hasattr(self, '_search_panel'):
            try:
                gp = event.globalPosition().toPoint()
                for panel in (self._search_panel, self._media_search_panel):
                    if not panel.isVisible(): continue
                    local = panel.mapFromGlobal(gp)
                    if panel.rect().contains(local): continue
                    # Don't hide if click is on a toolbar button (toggle handles it)
                    # Find the toolbar frame (first child QFrame of central widget)
                    click_on_toolbar = False
                    for tb in self.centralWidget().findChildren(_api.QFrame):
                        if tb.height() == 46:  # our toolbar height
                            tl = tb.mapFromGlobal(gp)
                            if tb.rect().contains(tl):
                                click_on_toolbar = True; break
                    if not click_on_toolbar:
                        panel.hide()
            except Exception:
                pass
    # ── Global keyboard shortcuts (work even inside QTextEdit) ─
    if event.type() == _api.QEvent.Type.KeyPress:
        fw = _api.QApplication.focusWidget()
        # Let text-editing widgets handle their OWN undo/redo
        is_editable = False
        if fw:
            if isinstance(fw, _api.QTextEdit):
                is_editable = bool(fw.textInteractionFlags() &
                                   _api.Qt.TextInteractionFlag.TextEditable)
            elif isinstance(fw, _api.QLineEdit):
                is_editable = not fw.isReadOnly()
        ctrl = event.modifiers() == _api.Qt.KeyboardModifier.ControlModifier
        # nativeVirtualKey — фолбэк для НЕ-латинских раскладок: физическая
        # S/Z/Y/O/F на кириллице шлёт Qt-код кириллической буквы, а не
        # Key_S/Z/Y/O/F, и одна только проверка event.key() молча не
        # срабатывает (тот же баг и приём, что и в edit_tab.py/tabs.py —
        # WASD-навигация чуть ниже свою кириллицу уже покрывает через
        # _WASD_MAP, но там же то не годится для Ctrl-сочетаний).
        try:
            vk = event.nativeVirtualKey()
        except Exception:
            vk = 0
        if ctrl and (event.key() == _api.Qt.Key.Key_S or vk == 0x53) and not is_editable:
            idx = self.sidebar.current_real_idx()
            if 0 <= idx < len(self.datasets):
                w = self.datasets[idx]["widget"]
                if hasattr(w, '_save_siq_inplace'):
                    w._save_siq_inplace()
            return True
        if ctrl and (event.key() == _api.Qt.Key.Key_Z or vk == 0x5A) and not is_editable:
            idx = self.sidebar.current_real_idx()
            if 0 <= idx < len(self.datasets):
                self.datasets[idx]["widget"].do_undo()
            return True
        if ctrl and (event.key() == _api.Qt.Key.Key_Y or vk == 0x59) and not is_editable:
            idx = self.sidebar.current_real_idx()
            if 0 <= idx < len(self.datasets):
                self.datasets[idx]["widget"].do_redo()
            return True
        if ctrl and (event.key() == _api.Qt.Key.Key_O or vk == 0x4F) and not is_editable:
            path, _ = _api.QFileDialog.getOpenFileName(
                self, "Открыть .siq", "", "SIGame Package (*.siq);;All (*)")
            if path: self._open_siq_file(path)
            return True
        if ctrl and (event.key() == _api.Qt.Key.Key_F or vk == 0x46):
            if self._search_panel.isVisible():
                self._hide_search()
            else:
                self._show_search()
            return True
        if event.key() == _api.Qt.Key.Key_Escape:
            if self._search_panel.isVisible():
                self._hide_search(); return True
        if event.key() == _api.Qt.Key.Key_F5:
            idx = self.sidebar.current_real_idx()
            if 0 <= idx < len(self.datasets):
                w = self.datasets[idx]["widget"]
                if hasattr(w, '_save_siq_inplace'):
                    w._save_siq_inplace()
            return True
        # ── WASD tile navigation ───────────────────────────────
        key_int = int(event.key())
        if key_int in _api._WASD_MAP and not is_editable and not ctrl:
            idx = self.sidebar.current_real_idx()
            if 0 <= idx < len(self.datasets):
                self.datasets[idx]["widget"]._wasd_navigate(*_api._WASD_MAP[key_int])
            return True
    # ── Body resize → reposition collapse button ──────────────
    if hasattr(self, '_collapse_btn'):
        if event.type() in (_api.QEvent.Type.Resize, _api.QEvent.Type.Show):
            self._reposition_collapse_btn()
    return super(_api.MainWindow, self).eventFilter(obj, event)

def _reposition_collapse_btn(self):
    body = self._collapse_btn.parent()
    if body is None: return
    # geometry().right() gives actual rendered right edge within body
    x = self.sidebar.geometry().right()
    y = (body.height() - self._collapse_btn.height()) // 2
    self._collapse_btn.move(max(0, x), max(0, y))
    self._collapse_btn.raise_()

def _toggle_sidebar(self):
    expanded_w = 248
    self._sidebar_visible = not self._sidebar_visible
    self._collapse_btn.setText("▶" if not self._sidebar_visible else "◀")
    self._collapse_btn.setToolTip(
        "Развернуть боковую панель" if not self._sidebar_visible
        else "Свернуть боковую панель")
    self._sidebar_anim.stop()
    try: self._sidebar_anim.valueChanged.disconnect()
    except Exception: pass
    try: self._sidebar_anim.finished.disconnect()
    except Exception: pass
    start = self.sidebar.width()
    end   = expanded_w if self._sidebar_visible else 0

    def _on_value(v):
        self.sidebar.setFixedWidth(int(v))
        self._reposition_collapse_btn()

    def _on_finish():
        if self._sidebar_visible:
            self.sidebar.setMinimumWidth(0)
            self.sidebar.setMaximumWidth(expanded_w)
        else:
            self.sidebar.setFixedWidth(0)
        self._reposition_collapse_btn()

    self._sidebar_anim.valueChanged.connect(_on_value)
    self._sidebar_anim.finished.connect(_on_finish)
    self._sidebar_anim.setStartValue(start)
    self._sidebar_anim.setEndValue(end)
    self._sidebar_anim.start()
    _api.save_settings({"sidebar_visible": self._sidebar_visible})

def _restart(self): _api.QApplication.quit(); _api.os.execl(_api.sys.executable,_api.sys.executable,*_api.sys.argv)

def _load_saved(self):
    """Загружает сохранённые пакеты, НЕ блокируя GUI-поток: по одному пакету
        за тик цикла событий (см. _load_saved_step).

        Раньше всё делалось разом, синхронно: разбор каждого .siq (открытие zip +
        чтение длительностей медиа из архива) и построение всех плиток/вьюеров.
        При первом показе встроенной вкладки «SiQuesterHYX» это намертво занимало
        GUI-поток на ~30 секунд — приложение «зависало», а окно мерцало (Windows
        рисует «призрак» неотвечающего окна, который то появляется, то исчезает).
        Теперь оболочка окна видна сразу, пакеты «подъезжают» по одному, и между
        ними цикл событий успевает крутиться — никакого зависания и мерцания."""
    self._pending_saved = _api.load_datasets()
    self._load_idx = 0
    if not self._pending_saved:
        self.stack.setCurrentWidget(self.empty_page)
        return
    # Таймер — ДОЧЕРНИЙ объект окна: если окно уничтожат во время загрузки
    # (вкладку выключили в настройках), таймер уничтожится вместе с ним и
    # гарантированно не дёрнет метод на уже удалённых виджетах.
    self._load_timer = _api.QTimer(self)
    self._load_timer.setSingleShot(True)
    self._load_timer.timeout.connect(self._load_saved_step)
    self._load_timer.start(0)

def _load_saved_step(self):
    """Догружает один сохранённый пакет и планирует следующий на след. тик."""
    raw = getattr(self, "_pending_saved", None)
    if not raw or self._load_idx >= len(raw):
        self._pending_saved = None
        if not self.datasets:
            self.stack.setCurrentWidget(self.empty_page)
        return
    ds = raw[self._load_idx]
    self._load_idx += 1
    # Сохраняем выбор пользователя: первый пакет показываем сразу, дальше не
    # «выдёргиваем» его на нулевой, если он успел кликнуть другой.
    prev = self.sidebar.current_real_idx()
    try:
        self._add_dataset(ds, save=False, _batch=True)
        real_idx = len(self.datasets) - 1
        siq_path = ds.get("siq_path", "")
        if siq_path and _api.os.path.exists(siq_path):
            try:
                siq = _api.SiqPackage(siq_path)
                self.datasets[real_idx]["total_duration_sec"] = siq.total_duration
                self.datasets[real_idx]["widget"].attach_siq(siq)
                # Пакеты, уже сохранённые ранее, тоже обновляют статистику при
                # каждом запуске — не только свежеоткрытые (см. _open_siq_file).
                self._auto_fetch_stats(real_idx, siq.name, list(siq.pkg_authors), siq.rounds)
            except Exception as e:
                _api._logger.warning(f"[siq reload] {e}")
        self.sidebar.rebuild(self.datasets)
        self._update_info()
        self.sidebar.select_by_real(prev if prev >= 0 else 0)
    except Exception as e:
        _api._logger.warning(f"[load_saved step] {e}")
    # Следующий пакет — на следующем тике цикла событий (GUI остаётся живым).
    self._load_timer.start(0)

def _add_dataset(self, ds, save=True, _batch=False):
    w = _api.ResultPage(ds, parent=self)
    self.stack.addWidget(w)
    self.datasets.append({**ds, "widget": w})
    if not _batch:
        self.sidebar.rebuild(self.datasets)
        self._update_info()
    if save:
        _api.save_datasets(self.datasets)

def _show_ds(self,real_idx):
    if 0<=real_idx<len(self.datasets):
        self.stack.setCurrentWidget(self.datasets[real_idx]["widget"])
        siq_path = self.datasets[real_idx].get("siq_path", "")
        if siq_path and _api.os.path.exists(siq_path):
            try:
                mtime = _api.os.path.getmtime(siq_path)
                dt = _api._dt.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")
                self._set_filename_text(
                    f"📂 {_api.os.path.dirname(siq_path)}{_api.os.sep}  "
                    f"📄 {_api.os.path.basename(siq_path)}  · сохранён {dt}")
            except Exception:
                self._set_filename_text(
                    f"📂 {_api.os.path.dirname(siq_path)}{_api.os.sep}  "
                    f"📄 {_api.os.path.basename(siq_path)}")
        else:
            self.lbl_filename.setText("")
            self.lbl_filename.setToolTip("")
        # Refresh media search if visible
        if hasattr(self, '_media_search_panel') and self._media_search_panel.isVisible():
            _api.QTimer.singleShot(50, self._run_media_search)
