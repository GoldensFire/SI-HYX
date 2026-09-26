# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: _style_tab_scroll_buttons. Public namespace: main."""
import main as _api


def _style_tab_scroll_buttons(self):
    """Стрелки прокрутки вкладок — как в браузере: своя стрелка-иконка
        вместо «пустого квадратика» от глобального стиля QToolButton, левая у
        левого края и только пока слева есть уехавшие вкладки, правая — у
        правого (см. widgets.TabScrollArrows)."""
    from widgets import install_tab_scroll_arrows
    self._tab_arrows = install_tab_scroll_arrows(self.tabs.tabBar())

def _tab_wheel_scroll(self, event):
    """Крутим вкладки колёсиком мыши, как в браузере — через нативные
        стрелки-прокрутки QTabBar (клика по ним программно)."""
    try:
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
            return
        arrows = getattr(self, "_tab_arrows", None)
        if arrows is not None:
            left, right = arrows.buttons()
        else:
            bar = self.tabs.tabBar()
            buttons = [b for b in bar.findChildren(_api.QToolButton) if b.isVisible()]
            if not buttons:
                return
            left, right = buttons[0], buttons[-1]
        if left is None or right is None:
            return
        btn = left if delta > 0 else right
        if btn.isEnabled():
            btn.click()
    except Exception:
        pass

# ── Перетаскивание файла на заголовок вкладки ────────────────────────────
@staticmethod
def _tab_drag_has_files(event):
    try:
        md = event.mimeData()
        return bool(md and md.hasUrls()
                    and any(u.toLocalFile() for u in md.urls()))
    except Exception:
        return False

def _tab_drag_hover(self, bar, pos):
    """Курсор с файлом завис над заголовком: запускаем таймер автопереключения
        на эту вкладку (как в браузерах при перетаскивании на заголовок)."""
    idx = bar.tabAt(pos)
    if idx < 0:
        self._tab_drag_idx = -1
        self._tab_drag_timer.stop()
        return
    if idx == self.tabs.currentIndex():
        self._tab_drag_idx = -1
        self._tab_drag_timer.stop()
        return
    if idx != self._tab_drag_idx:
        self._tab_drag_idx = idx
        self._tab_drag_timer.start(600)

def _tab_drag_switch(self):
    if self._tab_drag_idx >= 0:
        self.setUpdatesEnabled(False)
        try:
            self._sync_console_visibility(self._tab_drag_idx)
            self.tabs.setCurrentIndex(self._tab_drag_idx)
        except Exception: pass
        finally:
            _api.QTimer.singleShot(0, lambda: self.setUpdatesEnabled(True))

def _tab_drag_drop(self, bar, event):
    """Бросок файла прямо на заголовок: открываем вкладку и добавляем в неё
        файл(ы) — тем же путём, что и обычный drop в её содержимое."""
    self._tab_drag_timer.stop()
    self._tab_drag_idx = -1
    idx = bar.tabAt(event.position().toPoint())
    if idx < 0:
        return
    paths = [u.toLocalFile() for u in event.mimeData().urls()
             if u.toLocalFile()]
    if not paths:
        return
    self.setUpdatesEnabled(False)
    self._sync_console_visibility(idx)
    self.tabs.setCurrentIndex(idx)
    _api.QTimer.singleShot(0, lambda: self.setUpdatesEnabled(True))
    page = self.tabs.widget(idx)
    fn = (getattr(page, "accept_dropped_paths", None)
          or getattr(page, "add_paths", None))
    if fn is not None:
        fn(paths)
    try:
        self.raise_(); self.activateWindow()
    except Exception:
        pass

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
    badge = bar.tabButton(idx, _api.QTabBar.ButtonPosition.RightSide)
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

    dlg = _api.QDialog(self)
    dlg.setWindowTitle("Консоль")
    dlg.setWindowFlag(_api.Qt.WindowType.WindowMaximizeButtonHint, True)
    v = _api.QVBoxLayout(dlg); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

    big = _api.QTextEdit(dlg); big.setReadOnly(True)
    big.setDocument(self.txt_log.document())   # общий документ → живой лог
    big.moveCursor(_api.QTextCursor.MoveOperation.End)
    big.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
    big.customContextMenuRequested.connect(
        lambda pos, w=big: self._log_context_menu(pos, w))
    from si_hyx_parts.main.console_search import copy_text, install_search
    install_search(big)
    v.addWidget(big)

    row = _api.QHBoxLayout(); row.addStretch(1)
    btn_copy = _api.QPushButton("Копировать", dlg)
    btn_copy.clicked.connect(lambda: copy_text(big))
    btn_clr = _api.QPushButton("Очистить", dlg)
    btn_clr.clicked.connect(self.txt_log.clear)
    btn_close = _api.QPushButton("Закрыть", dlg)
    btn_close.clicked.connect(dlg.close)
    row.addWidget(btn_copy); row.addWidget(btn_clr); row.addWidget(btn_close)
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
    big.moveCursor(_api.QTextCursor.MoveOperation.End)

def _log_context_menu(self, pos, widget=None):
    """Русское контекстное меню для лог-консоли (вместо системного англ.)."""
    w = widget or self.txt_log
    m = _api.QMenu(w)
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
    try:
        t = _api.time.strftime("%Y-%m-%d %H:%M:%S")
        bar = self.txt_log.verticalScrollBar()
        # Насильно вниз тянем, только если человек и так смотрел конец: иначе
        # отматывать журнал во время работы стало бы невозможно.
        at_end = bar.value() >= bar.maximum() - 4
        self.txt_log.append(f"[{t}] {txt}")
        if at_end:
            _scroll_log_down(self)
    except Exception: pass

def _scroll_log_down(self):
    """Прокручивает консоль в самый низ — там свежие строки.

        После отбивки пустыми строками QTextEdit сам вниз не едет, и окно
        выглядело пустым, пока его не прокрутят руками (просьба
        пользователя)."""
    bar = self.txt_log.verticalScrollBar()
    bar.setValue(bar.maximum())

def log_gap(self, lines: int = 5):
    """Пустая полоса в консоли — отбивка нового прогона от прошлых логов.

        Зовётся перед первой строкой длинной работы (сборка аниме-пака),
        чтобы сразу было видно, где кончились прошлые записи. Пустую консоль
        отбивать не от чего, поэтому в самом начале полоса не ставится."""
    try:
        if not self.txt_log.toPlainText().strip():
            return
        # append("") молча не делает ничего — пустые строки добавляем прямо
        # в конец текста, а курсор потом уводим туда же.
        end = _api.QTextCursor.MoveOperation.End
        cursor = self.txt_log.textCursor()
        cursor.movePosition(end)
        cursor.insertText("\n" * max(0, int(lines)))
        self.txt_log.moveCursor(end)
        _scroll_log_down(self)
    except Exception:
        pass

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
    super(_api.UnifiedWindow, self).closeEvent(ev)
