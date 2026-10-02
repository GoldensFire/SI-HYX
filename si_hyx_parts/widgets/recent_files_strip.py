# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""RecentFilesStrip. Public namespace: widgets."""
import widgets as _api


class RecentFilesStrip(_api.QWidget):
    """Горизонтальный стрип последних файлов из папки.
    Автоматически обновляется каждые 5 секунд — показывает только новые файлы.
    mode='media'  — только ALLOWED_MEDIA | ALLOWED_IMG (по умолчанию, первая вкладка)
    mode='all'    — все файлы кроме .txt (вкладка Base64)
    """
    _ALL_EXT = None  # заполняется лениво

    # Расширения, которые ВСЕГДА исключаются в режиме 'all'
    _EXCLUDE_EXT = {'.txt', '.log', '.lnk', '.ini', '.cfg', '.tmp', '.db', '.desktop'}

    def __init__(self, media_tab, parent=None, mode='media'):
        super().__init__(parent)
        self.media_tab = media_tab
        self._mode = mode
        self._folder = ""
        self._default_folder = ""   # папка загрузки (из вкладки «Загрузчик»)
        self._custom_folder = ""    # выбранная пользователем папка-источник (приоритет)
        try:
            self._custom_folder = (_api.load_settings().get('recent_folders', {}) or {}).get(mode, "") or ""
        except Exception:
            self._custom_folder = ""
        self._known_paths: list = []  # текущий список путей (актуальный снимок)
        self._anchor_thumb = None      # якорь для Shift-выделения диапазона
        from .recent_files_scan import DirectoryScanner
        self._scanner = DirectoryScanner(self)
        self._scanner.ready.connect(self._scan_finished)
        self.setFixedHeight(128)

        outer = _api.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        self._scroll = _api.QScrollArea()
        self._scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        self._inner = _api.QWidget()
        self._row = _api.QHBoxLayout(self._inner)
        self._row.setContentsMargins(4, 4, 4, 4); self._row.setSpacing(6)
        self._row.addStretch()
        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll)

        # Правая колонка (сверху справа): выбор папки-источника ленты.
        ctl = _api.QVBoxLayout(); ctl.setContentsMargins(2, 2, 4, 2); ctl.setSpacing(2)
        self._btn_folder = _api.QToolButton(); self._btn_folder.setAutoRaise(True)
        self._btn_folder.setIcon(_api.get_icon('fa5s.folder-open'))
        self._btn_folder.clicked.connect(self._choose_folder)
        self._btn_folder_reset = _api.QToolButton(); self._btn_folder_reset.setAutoRaise(True)
        self._btn_folder_reset.setIcon(_api.get_icon('fa5s.undo'))
        self._btn_folder_reset.setToolTip("Сбросить — брать из папки загрузки")
        self._btn_folder_reset.clicked.connect(self._reset_folder)
        ctl.addWidget(self._btn_folder, 0, _api.Qt.AlignmentFlag.AlignTop)
        ctl.addWidget(self._btn_folder_reset, 0, _api.Qt.AlignmentFlag.AlignTop)
        ctl.addStretch()
        outer.addLayout(ctl)

        self._lbl_empty = _api.QLabel("Нет медиафайлов в папке")
        self._lbl_empty.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setStyleSheet("color:#666;font-size:10px;")
        self._row.insertWidget(0, self._lbl_empty)

        # Таймер автообновления
        self._timer = _api.QTimer(self)
        self._timer.setInterval(5000)  # каждые 5 секунд
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        self._update_folder_btn()
        # Клик ЛКМ в любом месте интерфейса ВНЕ ленты снимает выделение карточек.
        try:
            _api.QApplication.instance().installEventFilter(self)
        except Exception:
            pass
        if self._custom_folder:        # своя папка задана — показываем сразу, до refresh()
            self._folder = self._effective_folder()
            self._request_scan()

    def wheelEvent(self, event):
        """Колесо мыши — горизонтальная прокрутка стрипа."""
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y() // 2)
        event.accept()

    # ── Выделение карточек (как в проводнике: ЛКМ / Shift / Ctrl) ────────────
    def _ordered_thumbs(self) -> list:
        """Карточки-миниатюры в визуальном порядке слева направо."""
        out = []
        for i in range(self._row.count()):
            it = self._row.itemAt(i)
            w = it.widget() if it else None
            if isinstance(w, _api.RecentFileThumb):
                out.append(w)
        return out

    def selected_paths(self) -> list:
        """Пути выделенных карточек в визуальном порядке."""
        return [t.path for t in self._ordered_thumbs() if t._selected]

    def clear_selection(self):
        """Снимает выделение со всех карточек (клик мимо — как в проводнике)."""
        changed = False
        for t in self._ordered_thumbs():
            if t._selected:
                t.set_selected(False)
                changed = True
        self._anchor_thumb = None
        return changed

    def eventFilter(self, obj, ev):
        # ЛКМ в любом месте интерфейса ВНЕ ленты снимает выделение карточек
        # (как в проводнике). Фильтр стоит на всём приложении.
        #
        # ВАЖНО (не откатывать на проверку obj!): нельзя判断 «внутри ли ленты» по
        # `obj`/`isAncestorOf(obj)`. Необработанный press карточки ВСПЛЫВАЕТ к
        # родителям ленты и выше (главное окно) — фильтр получал тот же press с
        # obj = ПРЕДКОМ ленты (вне неё) и ошибочно звал clear_selection СРАЗУ после
        # выделения карточки (выделение «не появлялось»). Поэтому проверяем
        # ГЛОБАЛЬНУЮ позицию клика относительно экранного прямоугольника ленты.
        try:
            if (ev.type() == _api.QEvent.Type.MouseButtonPress
                    and ev.button() == _api.Qt.MouseButton.LeftButton
                    and any(t._selected for t in self._ordered_thumbs())):
                gp = ev.globalPosition().toPoint()
                rect = _api.QRect(self.mapToGlobal(_api.QPoint(0, 0)), self.size())
                if not rect.contains(gp):
                    self.clear_selection()
        except Exception:
            pass
        return False

    def handle_thumb_click(self, thumb, modifiers):
        """Обновляет выделение по клику на карточку с учётом Shift/Ctrl:
        • без модификаторов — выделить только эту (снять остальные);
        • Ctrl — переключить эту, не трогая остальные;
        • Shift — выделить диапазон от якоря до этой;
        • Ctrl+Shift — добавить диапазон к текущему выделению."""
        thumbs = self._ordered_thumbs()
        if not thumbs or thumb not in thumbs:
            return
        ctrl = bool(modifiers & _api.Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & _api.Qt.KeyboardModifier.ShiftModifier)
        if shift and self._anchor_thumb in thumbs:
            i0 = thumbs.index(self._anchor_thumb)
            i1 = thumbs.index(thumb)
            lo, hi = sorted((i0, i1))
            rng = set(thumbs[lo:hi + 1])
            for t in thumbs:
                if t in rng:
                    t.set_selected(True)
                elif not ctrl:           # Ctrl+Shift — копим, иначе заменяем
                    t.set_selected(False)
            # якорь при Shift не двигаем
        elif ctrl:
            thumb.set_selected(not thumb._selected)
            self._anchor_thumb = thumb
        else:
            for t in thumbs:
                t.set_selected(t is thumb)
            self._anchor_thumb = thumb

    @classmethod
    def _get_all_ext(cls):
        if cls._ALL_EXT is None:
            cls._ALL_EXT = _api.ALLOWED_MEDIA | _api.RIBBON_IMG
        return cls._ALL_EXT

    def _scan(self) -> list:
        """Synchronous compatibility helper; GUI callers use the worker."""
        from .recent_files_scan import scan_recent
        return scan_recent(self._folder, self._mode, self._get_all_ext(),
                           self._EXCLUDE_EXT)

    def _request_scan(self):
        self._scanner.request(self._folder, self._mode, self._get_all_ext(),
                              self._EXCLUDE_EXT)

    def _scan_finished(self, paths):
        if paths != self._known_paths:
            self._apply(paths)

    def showEvent(self, event):  # noqa: N802 — Qt override
        super(_api.RecentFilesStrip, self).showEvent(event)
        self._request_scan()

    def _poll(self):
        """Вызывается таймером — обновляет стрип если список файлов изменился."""
        if (not self._folder or not self.isVisible()
                or self.window().isMinimized()):
            return
        self._request_scan()
        self._recheck_pending()

    def _recheck_pending(self):
        # Пингуем карточки без миниатюры: файл мог дозаписаться (mp4 при
        # перекодировании весь процесс висит ~48 Б, moov пишется в конце).
        for i in range(self._row.count()):
            it = self._row.itemAt(i)
            w = it.widget() if it else None
            if isinstance(w, _api.RecentFileThumb):
                w.recheck_pending()

    def refresh(self, folder: str):
        """Папка загрузки сменилась (вкладка «Загрузчик»). Если своя папка не
        задана — лента берёт её; иначе остаётся на пользовательской."""
        self._default_folder = folder or ""
        self._folder = self._effective_folder()
        self._request_scan()

    def force_refresh(self):
        """Немедленный опрос папки/карточек, не дожидаясь 5-сек. таймера — напр.
        после обрезки/экспорта в «Монтаже», когда файл по тому же пути
        перезаписан перекодировкой (стал короче/легче)."""
        try:
            self._request_scan()
            self._recheck_pending()
        except Exception:
            pass

    def _effective_folder(self) -> str:
        """Своя папка пользователя приоритетнее; иначе — папка загрузки."""
        if self._custom_folder and _api.os.path.isdir(self._custom_folder):
            return self._custom_folder
        return self._default_folder

    def _choose_folder(self):
        start = self._effective_folder() or _api.default_download_dir()
        d = _api.QFileDialog.getExistingDirectory(self, "Папка-источник ленты", start)
        if not d:
            return
        self._custom_folder = d
        self._persist_folder()
        self._folder = self._effective_folder()
        self._request_scan()
        self._update_folder_btn()

    def _reset_folder(self):
        self._custom_folder = ""
        self._persist_folder()
        self._folder = self._effective_folder()
        self._request_scan()
        self._update_folder_btn()

    def _persist_folder(self):
        """Сохраняем выбор папки в настройках (по режиму ленты)."""
        try:
            s = _api.load_settings()
            folders = dict(s.get('recent_folders', {}) or {})
            if self._custom_folder:
                folders[self._mode] = self._custom_folder
            else:
                folders.pop(self._mode, None)
            s['recent_folders'] = folders
            _api.save_settings(s)
        except Exception:
            pass

    def _update_folder_btn(self):
        custom = bool(self._custom_folder)
        self._btn_folder_reset.setVisible(custom)
        if custom:
            self._btn_folder.setToolTip(
                f"Папка-источник ленты:\n{self._custom_folder}\n(нажмите, чтобы сменить)")
        else:
            self._btn_folder.setToolTip(
                "Выбрать папку-источник ленты.\n"
                "По умолчанию — папка загрузки из вкладки «Загрузчик».")

    def _apply(self, paths: list):
        """Обновляет виджеты: добавляет только новые, удаляет исчезнувшие."""
        old_paths = self._known_paths
        self._known_paths = paths

        # Удаляем карточки файлов которых больше нет
        removed = set(old_paths) - set(paths)
        if removed:
            for i in range(self._row.count() - 1, -1, -1):
                item = self._row.itemAt(i)
                w = item.widget() if item else None
                if isinstance(w, _api.RecentFileThumb) and w.path in removed:
                    self._row.takeAt(i)
                    w.deleteLater()

        # Собираем существующие карточки
        existing = {
            self._row.itemAt(i).widget().path
            for i in range(self._row.count())
            if isinstance(self._row.itemAt(i).widget() if self._row.itemAt(i) else None, _api.RecentFileThumb)
        }
        added = [p for p in paths if p not in existing]

        if not paths:
            if not self._has_empty_label():
                lbl = _api.QLabel("Нет медиафайлов в папке загрузок")
                lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet("color:#666;font-size:10px;")
                self._row.insertWidget(0, lbl)
            return

        self._remove_empty_label()

        for path in reversed(added):
            card = _api.RecentFileThumb(path, self._inner)
            self._row.insertWidget(0, card)

        # Переупорядочиваем только если что-то реально изменилось по сравнению с
        # предыдущим снимком (не только добавились новые в начало)
        need_reorder = bool(removed) or (
            added and old_paths and paths[:len(old_paths)] != old_paths
        )
        if need_reorder:
            self._reorder(paths)

    def _reorder(self, ordered_paths: list):
        """Переставляет карточки в соответствии с порядком ordered_paths."""
        path_to_widget = {}
        for i in range(self._row.count()):
            item = self._row.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, _api.RecentFileThumb):
                path_to_widget[w.path] = w

        # Переставляем по желаемому порядку
        for idx, path in enumerate(ordered_paths):
            w = path_to_widget.get(path)
            if w:
                self._row.removeWidget(w)
                self._row.insertWidget(idx, w)

    def _has_empty_label(self) -> bool:
        for i in range(self._row.count()):
            item = self._row.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, _api.QLabel) and not isinstance(w, _api.RecentFileThumb):
                return True
        return False

    def _remove_empty_label(self):
        for i in range(self._row.count() - 1, -1, -1):
            item = self._row.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, _api.QLabel) and not isinstance(w, _api.RecentFileThumb):
                self._row.takeAt(i)
                w.deleteLater()

RecentFilesStrip.__module__ = _api.__name__
_api.RecentFilesStrip = RecentFilesStrip
