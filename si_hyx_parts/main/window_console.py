# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Главное окно: консоль журнала, общий прогресс и прогресс на панели задач."""
import main as _api


def _scroll_log_down(self):
    """Прокручивает консоль в самый низ — там свежие строки.

        После отбивки пустыми строками QTextEdit сам вниз не едет, и окно
        выглядело пустым, пока его не прокрутят руками (просьба
        пользователя)."""
    bar = self.txt_log.verticalScrollBar()
    bar.setValue(bar.maximum())


class UnifiedWindowConsoleMixin:
    """Главное окно: консоль журнала, общий прогресс и прогресс на панели задач."""

    def update_global_progress(self, val, text, *, started_at=None, running=None):
        self.pbar.set_progress(val, text, started_at=started_at, running=running)
        # val < 0 → неопределённый («busy») режим: полоса пульсирует. Нужен для
        # фаз, где реального процента нет (перемотка декодера до точки реза при
        # обрезке с перекодированием), чтобы полоса не выглядела зависшей на 0%.
        if val is None or val < 0:
            self.set_taskbar_progress(0, 0)   # indeterminate в панели задач
            return
        # Зеркалим прогресс перекодирования на иконку в панели задач.
        # ВАЖНО: val==0 — это «простаивает/завершилось/ошибка/отменено», НЕ занятость.
        # set_value(…,0,100) трактует completed<=0 как INDETERMINATE (бегущий бар),
        # из-за чего после ошибки/отмены на иконке вечно «крутился» процесс. Поэтому
        # на 0 (и на ≥100) индикатор УБИРАЕМ, а не оставляем пульсировать.
        if val >= 100 or val <= 0:
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

    def _sync_console_visibility(self, index=None):
        """Нижняя консоль и прогрессбар. Консоль скрыта на «Монтаж» и
        «SiQuesterHYX» (там она лишь занимает место). Прогрессбар скрыт на
        «SiQuesterHYX» (на «Монтаж» он нужен для прогресса экспорта).

        Принимает индекс явно (а не только через currentChanged), чтобы можно
        было спрятать консоль ДО фактического показа страницы — иначе видео на
        «Монтаж» сперва рисуется в старой (с консолью) высоте и тут же
        дёргается на новую, бóльшую — см. _on_tab_bar_clicked."""
        try:
            cur = self.tabs.widget(index) if isinstance(index, int) else self.tabs.currentWidget()
            is_edit = cur is self.tab_edit
            tsq = getattr(self, "tab_siquester", None)
            is_siq = tsq is not None and cur is tsq
            tsh = getattr(self, "tab_shikimori", None)
            is_shiki = tsh is not None and cur is tsh
            tlb = getattr(self, "tab_leaderboard", None)
            is_lb = tlb is not None and cur is tlb
            tcp = getattr(self, "tab_coop", None)
            is_coop = tcp is not None and cur is tcp
            is_photo = cur is getattr(self, "tab_photo", None)
            self.console_panel.setVisible(not (is_edit or is_siq or is_shiki or is_lb or is_coop or is_photo))
            show_progress = not (is_siq or is_shiki or is_lb or is_coop or is_photo)
            self.pbar.setVisible(show_progress)
        except Exception:
            pass

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
            from diagnostic_logging import archive
            archive(txt)
            t = _api.time.strftime("%Y-%m-%d %H:%M:%S")
            bar = self.txt_log.verticalScrollBar()
            # Насильно вниз тянем, только если человек и так смотрел конец: иначе
            # отматывать журнал во время работы стало бы невозможно.
            at_end = bar.value() >= bar.maximum() - 4
            self.txt_log.append(f"[{t}] {txt}")
            if at_end:
                _scroll_log_down(self)
        except Exception: pass

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

    def _position_progress_button(self):
        """Прижимает SVG-кнопку к правому краю самой полосы прогресса."""
        bar = getattr(self, "pbar", None)
        button = getattr(self, "btn_open_progress", None)
        if bar is None or button is None:
            return
        button.move(max(0, bar.width() - button.width() - 3),
                    max(0, (bar.height() - button.height()) // 2))
        button.raise_()

    def set_global_result(self, path):
        value = _api.os.path.abspath(str(path or "")) if path else ""
        self._global_result_path = value
        button = getattr(self, "btn_open_progress", None)
        if button is None:
            return
        ready = bool(value and _api.os.path.isfile(value))
        button.setEnabled(ready)
        button.setToolTip(value if ready else "Последний созданный файл появится здесь")

    def clear_global_result(self):
        self.set_global_result("")

    def _open_global_result(self):
        path = str(getattr(self, "_global_result_path", "") or "")
        if not path or not _api.os.path.isfile(path):
            self.clear_global_result()
            return
        try:
            if _api.IS_WIN:
                _api.os.startfile(path)
            elif _api.sys.platform == "darwin":
                _api.subprocess.Popen(["open", path])
            else:
                _api.subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            _api.msgbox_critical(self, "Файл не открылся", str(exc))
