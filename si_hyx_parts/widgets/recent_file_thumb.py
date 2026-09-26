# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""RecentFileThumb. Public namespace: widgets."""
import widgets as _api


class RecentFileThumb(_api.QWidget):
    """Карточка в стрипе: миниатюра + тип-значок + имя файла."""

    _ICON_VIDEO = "fa5s.film"
    _ICON_IMAGE = "fa5s.image"
    _ICON_AUDIO = "fa5s.music"

    _thumb_ready = _api.pyqtSignal(object, str)  # (bytes|None, dur_str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setFixedSize(108, 108)
        self.setCursor(_api.Qt.CursorShape.OpenHandCursor)
        self.setToolTip(path)
        self._drag_start = None
        self._selected = False      # выделена ли карточка (ЛКМ / Shift / Ctrl)
        self._thumb_attempts = 0
        self._last_seen_size = -1   # для дозаписываемых файлов (Filmora и пр.)
        self._has_thumb = False     # получена ли настоящая миниатюра
        # Состояние файла (размер/mtime), которому соответствует ТЕКУЩАЯ миниатюра.
        # Если файл по тому же пути перезапишут (напр. «…_обрез.mp4» переэкспортируют
        # перекодировкой — он станет короче/легче), эти значения разойдутся с
        # фактическими и карточка перегенерирует превью/размер/длительность.
        self._content_mtime = -1.0
        self._content_size = -1

        ext = _api.os.path.splitext(path)[1].lower()
        is_img   = ext in _api.RIBBON_IMG
        is_video = not is_img and ext in {'.mp4', '.mkv', '.avi', '.mov', '.webm',
                                           '.flv', '.wmv', '.m4v', '.ts', '.mts',
                                           '.m2ts', '.vob', '.ogv', '.3gp'}
        self._type_icon = self._ICON_IMAGE if is_img else (self._ICON_VIDEO if is_video else self._ICON_AUDIO)

        layout = _api.QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        # Контейнер миниатюры с бейджем типа
        thumb_container = _api.QWidget()
        thumb_container.setFixedHeight(72)
        tc_layout = _api.QHBoxLayout(thumb_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)

        ext_disp = _api.os.path.splitext(path)[1].lstrip('.').upper() or '—'
        self._ext_txt = ext_disp
        try: self._size_str = _api.human_size(_api.os.path.getsize(path))
        except Exception: self._size_str = ""
        self._thumb_lbl = _api.QLabel()
        self._thumb_lbl.setFixedSize(96, 72)
        self._thumb_lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self._thumb_lbl.setTextFormat(_api.Qt.TextFormat.RichText)
        # Прозрачный фон: у миниатюр с «неподходящим» соотношением сторон (не 4:3)
        # пиксмап масштабируется с сохранением пропорций и не заполняет 96×72 —
        # раньше по бокам/сверху проступал серый прямоугольник #1e1e1e. Теперь
        # незаполненная область прозрачна и сливается с карточкой.
        self._thumb_lbl.setStyleSheet("background:transparent;border-radius:3px;")
        self._thumb_lbl.setText(self._placeholder_html())  # значок типа + расширение, пока нет превью
        tc_layout.addWidget(self._thumb_lbl)

        # Имя файла
        name = _api.os.path.basename(path)
        short = (name[:15] + "…") if len(name) > 15 else name
        name_lbl = _api.QLabel(f"{_api.icon_html(self._type_icon, 10, '#cccccc')} {short}")
        name_lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(False)
        name_lbl.setStyleSheet("color:#ccc;font-size:8px;")
        name_lbl.setToolTip(name)

        layout.addWidget(thumb_container)
        layout.addWidget(name_lbl)

        # Дочерние элементы прозрачны для мыши — чтобы перетаскивание (drag) в очередь
        # и клики ловила сама карточка, а не QLabel внутри (иначе drag не стартует).
        for _w in (thumb_container, self._thumb_lbl, name_lbl):
            _w.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Прозрачная рамка 1px уже в обычном состоянии: при наведении меняется
        # только ЦВЕТ рамки, а не геометрия. Иначе добавление рамки на :hover
        # сдвигало содержимое на 1px → переразметка → мерцание/лаг (как было у ⓘ).
        self._apply_selection_style()

        # Загрузка миниатюры в фоне (через QThreadPool — НЕ блокирует GUI при старте)
        self._thumb_ready.connect(self._apply_thumb)
        _api.QThreadPool.globalInstance().start(_api._RecentThumbWorker(self.path, self._thumb_ready))

    def _apply_selection_style(self):
        """Стиль карточки. Подсветку выделения даём ДВУМЯ способами разом:
        • ФОН через QSS (на голом QWidget на Windows фон рисуется надёжно — рамка
          QSS нет, поэтому полагаться только на неё нельзя);
        • рамку поверх — в paintEvent (гарантированно).
        Раньше выделение рисовалось ТОЛЬКО в paintEvent и на части машин не было
        видно — теперь выделенная карточка дополнительно получает синеватый фон."""
        if self._selected:
            self.setStyleSheet(
                "RecentFileThumb{background:#2d3c57;border-radius:5px;"
                "border:1px solid #89b4fa;}"
                "RecentFileThumb:hover{background:#344665;"
                "border:1px solid #89b4fa;}")
        else:
            self.setStyleSheet(
                "RecentFileThumb{background:#2a2a2a;border-radius:5px;"
                "border:1px solid transparent;}"
                "RecentFileThumb:hover{background:#363636;border:1px solid #555;}")

    def set_selected(self, on):
        on = bool(on)
        if on != self._selected:
            self._selected = on
            self._apply_selection_style()   # синеватый фон выделения (надёжный QSS)
            self.update()                   # + рамка в paintEvent

    def paintEvent(self, e):
        # Базовый фон/hover из stylesheet рисует QStyle через super().
        super().paintEvent(e)
        if not self._selected:
            return
        p = _api.QPainter(self)
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
        p.setBrush(_api.QColor(137, 180, 250, 55))      # лёгкая синяя заливка
        p.setPen(_api.QPen(_api.QColor("#89b4fa"), 2))       # синяя рамка выделения
        r = _api.QRectF(self.rect()).adjusted(1.0, 1.0, -1.5, -1.5)
        p.drawRoundedRect(r, 5, 5)

    def _strip(self):
        """Поднимается по родителям до ленты RecentFilesStrip (управляет выделением)."""
        p = self.parent()
        while p is not None and not isinstance(p, _api.RecentFilesStrip):
            p = p.parent()
        return p

    def _placeholder_html(self):
        """HTML-заглушка превью: крупный значок типа + расширение файла снизу."""
        return (f"<div style='line-height:25px;'>{_api.icon_html(self._type_icon, 24, '#cdd6f4')}</div>"
                f"<div style='font-size:9px; color:#9399b2;'>{self._ext_txt}</div>"
                f"<div style='font-size:9px; color:#7f849c;'>{self._size_str}</div>")

    def _refresh_size(self):
        """Перечитать размер файла (мог вырасти, пока шла генерация миниатюры)."""
        try:
            self._size_str = _api.human_size(_api.os.path.getsize(self.path))
        except Exception:
            pass

    def _apply_thumb(self, data, dur_str):
        """Слот в GUI-потоке: строит QPixmap из байтов и рисует длительность."""
        try:
            # Размер мог измениться с момента создания карточки (Filmora и др.
            # пишут файл постепенно) — всегда показываем актуальный.
            self._refresh_size()
            if not data:
                self._thumb_lbl.setText(self._placeholder_html())
                try: cur = _api.os.path.getsize(self.path)
                except Exception: cur = -1
                if cur != self._last_seen_size:
                    # Файл ещё дозаписывается (размер растёт) — сбрасываем счётчик
                    # и продолжаем ждать готовности, сколько бы ни длилась запись.
                    self._last_seen_size = cur
                    self._thumb_attempts = 0
                    _api.QTimer.singleShot(1500, self._retry_thumb)
                elif self._thumb_attempts < 8:
                    # Размер стабилен, но превью пока нет (файл занят) — ещё попытки.
                    self._thumb_attempts += 1
                    _api.QTimer.singleShot(1500, self._retry_thumb)
                return
            pix = _api.QPixmap()
            if not pix.loadFromData(_api.QByteArray(data)):
                return
            pix = pix.scaled(96, 72, _api.Qt.AspectRatioMode.KeepAspectRatio,
                             _api.Qt.TransformationMode.SmoothTransformation)
            # Бейджи (длительность/размер) рисуем на ПОЛНОМ холсте 96×72, а не
            # поверх узкого pix — у портретных превью (высокий формат) pix
            # масштабируется до узкой полоски по ширине, и подпись вроде
            # "143.5KB" обрезалась бы клипом до "143". Холст даёт бейджам
            # полную ширину карточки независимо от пропорций превью.
            canvas = _api.QPixmap(96, 72)
            canvas.fill(_api.Qt.GlobalColor.transparent)
            cpaint = _api.QPainter(canvas)
            cpaint.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
            cx = (96 - pix.width()) // 2
            cy = (72 - pix.height()) // 2
            cpaint.drawPixmap(cx, cy, pix)
            if dur_str:
                font = _api.QFont(); font.setPointSize(7); font.setBold(True)
                cpaint.setFont(font)
                fm = cpaint.fontMetrics()
                tw = fm.horizontalAdvance(dur_str) + 6
                th = fm.height() + 2
                tx = canvas.width() - tw - 2
                ty = canvas.height() - th - 2
                cpaint.fillRect(tx, ty, tw, th, _api.QColor(0, 0, 0, 160))
                cpaint.setPen(_api.QPen(_api.QColor(255, 255, 255)))
                cpaint.drawText(tx + 3, ty + th - 3, dur_str)
            # Бейдж размера файла — верхний левый угол (минимум в КБ)
            if self._size_str:
                f2 = _api.QFont(); f2.setPointSize(7); f2.setBold(True); cpaint.setFont(f2)
                fm2 = cpaint.fontMetrics()
                sw = min(fm2.horizontalAdvance(self._size_str) + 6, canvas.width() - 4)
                sh = fm2.height() + 1
                cpaint.fillRect(2, 2, sw, sh, _api.QColor(0, 0, 0, 160))
                cpaint.setPen(_api.QPen(_api.QColor(255, 255, 255)))
                cpaint.drawText(2 + 3, 2 + sh - 3, self._size_str)
            cpaint.end()
            self._thumb_lbl.setText("")
            self._thumb_lbl.setPixmap(canvas)
            self._has_thumb = True
            # Запоминаем, какому состоянию файла соответствует это превью —
            # чтобы заметить позднюю перезапись файла по тому же пути.
            try:
                self._content_size = _api.os.path.getsize(self.path)
                self._content_mtime = _api.os.path.getmtime(self.path)
            except Exception:
                pass
        except Exception:
            pass

    def recheck_pending(self):
        """Периодический пинг от стрипа (раз в 5 c): если миниатюры ещё нет,
        а размер файла изменился — значит файл дописали (ffmpeg пишет moov-атом
        mp4 только в конце, до этого файл «висит» крошечным). Обновляем размер и
        пробуем снова. ffmpeg-воркер запускаем только при изменении размера —
        для готовых/безвидеошных файлов лишних запусков нет."""
        if self._has_thumb:
            # Превью уже есть, но файл по тому же пути могли ПЕРЕЗАПИСАТЬ (та же
            # «…_обрез.mp4» переэкспортирована перекодировкой — стала короче/легче).
            # Замечаем это по изменению размера/mtime и перегенерируем карточку
            # (превью + размер + длительность), иначе лента показывала бы старое.
            try:
                cur = _api.os.path.getsize(self.path)
                cur_mtime = _api.os.path.getmtime(self.path)
            except Exception:
                return
            if cur != self._content_size or cur_mtime != self._content_mtime:
                self._has_thumb = False
                self._content_size = cur
                self._content_mtime = cur_mtime
                self._last_seen_size = cur
                self._refresh_size()
                self._thumb_lbl.setText(self._placeholder_html())
                self._thumb_attempts = 0
                self._retry_thumb()
            return
        try:
            cur = _api.os.path.getsize(self.path)
        except Exception:
            return
        if cur != self._last_seen_size:
            self._last_seen_size = cur
            self._refresh_size()
            self._thumb_lbl.setText(self._placeholder_html())  # показать актуальный размер
            self._thumb_attempts = 0
            self._retry_thumb()

    def _retry_thumb(self):
        """Повторная попытка сделать миниатюру (файл мог быть занят/недописан)."""
        try:
            if _api.os.path.exists(self.path):
                _api.QThreadPool.globalInstance().start(_api._RecentThumbWorker(self.path, self._thumb_ready))
        except Exception:
            pass

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self._drag_start = e.pos()
            self._pending_collapse = False
            # Логика проводника: нажатие на УЖЕ выделенную карточку без модификаторов
            # НЕ схлопывает мультивыделение сразу — иначе drag утащит лишь одну.
            # Схлопываем до неё только на отпускании, если это был клик (без drag).
            strip = self._strip()
            if strip is not None:
                mods = e.modifiers()
                plain = not (mods & (_api.Qt.KeyboardModifier.ControlModifier
                                     | _api.Qt.KeyboardModifier.ShiftModifier))
                if plain and self._selected:
                    self._pending_collapse = True       # отложили до release
                else:
                    strip.handle_thumb_click(self, mods)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        # Клик (без перетаскивания) по уже выделенной карточке — теперь схлопываем
        # выделение до неё одной (как в проводнике).
        if (e.button() == _api.Qt.MouseButton.LeftButton
                and getattr(self, "_pending_collapse", False)):
            strip = self._strip()
            if strip is not None:
                strip.handle_thumb_click(self, _api.Qt.KeyboardModifier.NoModifier)
        self._pending_collapse = False
        self._drag_start = None
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_start is not None and (e.pos() - self._drag_start).manhattanLength() > 6:
            self._drag_start = None
            # Начали тащить — отменяем отложенное схлопывание, тащим всё выделенное.
            self._pending_collapse = False
            # Подсветка карточки на старте перетаскивания — как обычный ЛКМ. Обычно
            # это уже сделано в mousePressEvent, но при очень быстром drag repaint
            # после press мог не успеть отрисоваться до запуска блокирующего
            # drag.exec() — форсируем выделение и НЕМЕДЛЕННУЮ перерисовку здесь.
            strip = self._strip()
            if strip is not None and not self._selected:
                strip.handle_thumb_click(self, _api.Qt.KeyboardModifier.NoModifier)
            self.repaint()
            from PyQt6.QtCore import QMimeData, QUrl
            from PyQt6.QtGui import QDrag
            # Тащим ВСЕ выделенные, если перетягиваемая карточка — одна из выделенных;
            # иначе только её одну.
            paths = [self.path]
            strip = self._strip()
            if strip is not None and self._selected:
                sel = strip.selected_paths()
                if len(sel) > 1:
                    paths = sel
            drag = QDrag(self)
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(p) for p in paths])
            drag.setMimeData(md)
            drag.exec(_api.Qt.DropAction.CopyAction | _api.Qt.DropAction.MoveAction)
        super().mouseMoveEvent(e)

    def mouseDoubleClickEvent(self, e):
        try:
            p = self
            while p and not hasattr(p, 'add_paths'):
                p = p.parent()
            if not p:
                return
            # Двойной клик добавляет ВСЕ выделенные (если их несколько и текущая
            # среди них), иначе — только эту карточку.
            paths = [self.path]
            strip = self._strip()
            if strip is not None and self._selected:
                sel = strip.selected_paths()
                if len(sel) > 1:
                    paths = sel
            p.add_paths(paths)
        except Exception: pass

    # ── Контекстное меню (ПКМ) с действиями над файлом ──────────────────────
    def contextMenuEvent(self, e):
        # ПКМ подсвечивает карточку так же, как обычный ЛКМ — но если курсор уже
        # на одной из карточек мультивыделения, само выделение не схлопываем
        # (как в проводнике: ПКМ по группе выделенных файлов не сбрасывает её).
        strip = self._strip()
        if strip is not None and not self._selected:
            strip.handle_thumb_click(self, _api.Qt.KeyboardModifier.NoModifier)
        m = _api.QMenu(self)
        a_add = m.addAction(_api.get_icon('fa5s.plus'), "Добавить в активную вкладку")
        a_open = m.addAction(_api.get_icon('fa5s.play'), "Открыть в системе")
        a_folder = m.addAction(_api.get_icon('fa5s.folder-open'), "Показать в папке")
        m.addSeparator()
        a_copy_path = m.addAction(_api.get_icon('fa5s.clipboard'), "Копировать путь")
        a_copy_file = m.addAction(_api.get_icon('fa5s.copy'), "Копировать файл (в буфер)")
        a_rename = m.addAction(_api.get_icon('fa5s.pen'), "Переименовать…")
        m.addSeparator()
        a_delete = m.addAction(_api.get_icon('fa5s.trash'), "Удалить файл")
        chosen = m.exec(e.globalPos())
        if chosen is None:
            return
        if chosen is a_add:
            self.mouseDoubleClickEvent(None)
        elif chosen is a_open:
            self._action_open()
        elif chosen is a_folder:
            self._action_show_in_folder()
        elif chosen is a_copy_path:
            _api.QApplication.clipboard().setText(self.path)
        elif chosen is a_copy_file:
            self._action_copy_file()
        elif chosen is a_rename:
            self._action_rename()
        elif chosen is a_delete:
            self._action_delete()

    def _action_open(self):
        try:
            if _api.os.name == 'nt':
                _api.os.startfile(self.path)  # noqa
            else:
                _api.subprocess.Popen(["xdg-open", self.path])
        except Exception:
            pass

    def _action_show_in_folder(self):
        from utils import reveal_in_explorer
        reveal_in_explorer(self.path)

    def _action_copy_file(self):
        """Кладёт сам файл (как URL) в буфер обмена — можно вставить в проводник."""
        try:
            from PyQt6.QtCore import QMimeData, QUrl
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(self.path)])
            _api.QApplication.clipboard().setMimeData(md)
        except Exception:
            pass

    def _action_rename(self):
        try:
            old = _api.os.path.basename(self.path)
            new, ok = _api.QInputDialog.getText(self, "Переименовать", "Новое имя файла:", text=old)
            if not ok or not new.strip() or new == old:
                return
            new = new.strip()
            dst = _api.os.path.join(_api.os.path.dirname(self.path), new)
            if _api.os.path.exists(dst):
                _api.msgbox_warning(self, "Переименование", "Файл с таким именем уже существует.")
                return
            _api.os.rename(self.path, dst)
            self.path = dst
            self.setToolTip(dst)
        except Exception as ex:
            _api.msgbox_warning(self, "Переименование", f"Не удалось переименовать:\n{ex}")

    def _action_delete(self):
        # Без подтверждения: файл уходит в Корзину (откуда его можно вернуть),
        # поэтому диалог «вы уверены?» не нужен.
        # Владельцем операции отдаём top-level окно: лента/карточка могли стать
        # нативными дочерними окнами (drag&drop), и NULL-hwnd привёл бы к ошибке
        # «must be a top level window» и срыву удаления.
        try:
            hwnd = None
            try:
                top = self.window()
                if top is not None:
                    hwnd = int(top.winId())
            except Exception:
                hwnd = None
            if _api.move_to_trash(self.path, hwnd=hwnd):
                # Карточку уберёт автообновление стрипа (poll), а саму скрываем сразу.
                self.hide()
            else:
                _api.msgbox_warning(self, "Удаление",
                                    f"Не удалось отправить файл в Корзину:\n"
                                    f"{_api.os.path.basename(self.path)}")
        except Exception as ex:
            _api.msgbox_warning(self, "Удаление", f"Не удалось удалить:\n{ex}")

RecentFileThumb.__module__ = _api.__name__
_api.RecentFileThumb = RecentFileThumb
