# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""DraggableTreeWidget. Public namespace: widgets."""
import widgets as _api
from PyQt6.QtGui import QRegion
from .info_tip_frame import source_is_current


class DraggableTreeWidget(_api.QTreeWidget):
    """QTreeWidget с поддержкой drag-and-drop файлов наружу (по tooltip = полный
    путь) и текстом-подсказкой по центру, когда список пуст."""

    # viewportEvent selects different hints for the image, filename and badge.
    # The application filter must not replace them with the cell's file path.
    _custom_item_tooltips = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # Нужно для наведения на значок «сравнить» без зажатой кнопки.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def setPlaceholderText(self, text: str):
        self._placeholder = text or ""
        self.viewport().update()

    def _badge_iid_at(self, pos):
        """Если pos (в координатах viewport) попадает в значок «сравнить»
        обработанной картинки — возвращает id строки, иначе None."""
        if pos is None:
            return None
        deleg = self.itemDelegateForColumn(0)
        if deleg is None or not hasattr(deleg, '_badge_rect'):
            return None
        idx = self.indexAt(pos)
        if not idx.isValid():
            return None
        idx = idx.sibling(idx.row(), 0)
        if not idx.data(_api.ITEM_COMPARE_ROLE):
            return None
        br = deleg._badge_rect(self.visualRect(idx), self.fontMetrics())
        if br.contains(pos):
            return idx.data(_api.Qt.ItemDataRole.UserRole)
        return None

    def _update_badge_hover(self, pos):
        deleg = self.itemDelegateForColumn(0)
        if deleg is None or not hasattr(deleg, 'set_badge_hover'):
            return
        iid = self._badge_iid_at(pos)
        deleg.set_badge_hover(iid)

    def _over_name_region(self, pos, idx):
        """Колонка «Превью»: True — курсор над строкой имени (внизу ячейки),
        False — над миниатюрой. Аудио-строки (без превью) — целиком имя."""
        try:
            idx0 = idx.sibling(idx.row(), 0)
            rect = self.visualRect(idx0)
            if not rect.isValid() or rect.height() <= 0:
                return False
            if idx0.data(_api.ITEM_AUDIO_ROLE):
                return True
            # Имя рисуется одной строкой у нижнего края ячейки
            # (см. PreviewNameDelegate.paint).
            text_h = self.fontMetrics().height() + 2
            return pos.y() >= rect.bottom() - text_h - 6
        except Exception:
            return False

    def viewportEvent(self, e):
        # Тултип ячейки (полное имя/путь) показываем тем же стабильным попапом,
        # что и значки ⓘ. Системный QToolTip на ячейках дерева мерцает —
        # перехватываем событие и рисуем свой попап, не дёргающийся при
        # микродвижениях мыши.
        try:
            et = e.type()
            if et == _api.QEvent.Type.ToolTip:
                if not source_is_current(self.viewport(), e.globalPos()):
                    e.accept()
                    return True
                item = self.itemAt(e.pos())
                idx = self.indexAt(e.pos())
                col = idx.column() if idx.isValid() else -1
                # Над значком «сравнить» — подсказка о значке (БЕЗ имени файла);
                # имя файла остаётся только при наведении на саму картинку.
                if self._badge_iid_at(e.pos()) is not None:
                    tip = "Сравнить исходник и результат"
                elif item is None:
                    tip = ""
                elif col == 0:
                    # Превью → путь файла; имя под превью → полное имя файла.
                    tip = item.text(0) if self._over_name_region(e.pos(), idx) \
                        else item.toolTip(0)
                else:
                    # На своей колонке — её подсказка (напр. «Время…»);
                    # иначе путь файла из колонки превью.
                    tip = item.toolTip(col) or item.toolTip(0)
                if tip:
                    _api._InfoTipPopup.instance().show_at(
                        e.globalPos(), tip, owner=self.viewport(),
                        region=self._tip_region(e.pos(), idx))
                else:
                    _api._InfoTipPopup.instance().hide_for(self.viewport())
                e.accept()
                return True
            if et == _api.QEvent.Type.MouseMove:
                self._update_badge_hover(e.pos())
            if et in (_api.QEvent.Type.Leave, _api.QEvent.Type.Wheel):
                _api._InfoTipPopup.instance().hide_for(self.viewport())
                self._update_badge_hover(None)
        except Exception:
            pass
        return super().viewportEvent(e)

    def _tip_region(self, pos, index):
        """Keep image, filename, and compare badge hints in their own areas."""
        rect = self.visualRect(index)
        region = QRegion(rect)
        if index.column() != 0:
            return region
        if not index.data(_api.ITEM_AUDIO_ROLE):
            name_rect = _api.QRect(rect)
            name_rect.setTop(rect.bottom() - self.fontMetrics().height() - 8)
            region = (QRegion(name_rect) if self._over_name_region(pos, index)
                      else region.subtracted(QRegion(name_rect)))
        delegate = self.itemDelegateForColumn(0)
        if (index.data(_api.ITEM_COMPARE_ROLE)
                and hasattr(delegate, '_badge_rect')):
            badge = delegate._badge_rect(rect, self.fontMetrics())
            if badge.contains(pos):
                return QRegion(badge)
            region = region.subtracted(QRegion(badge))
        return region

    def paintEvent(self, e):
        super().paintEvent(e)
        text = getattr(self, "_placeholder", "")
        if text and self.topLevelItemCount() == 0:
            painter = _api.QPainter(self.viewport())
            painter.setPen(_api.QColor(150, 150, 150))
            rect = self.viewport().rect().adjusted(24, 24, -24, -24)
            painter.drawText(
                rect,
                int(_api.Qt.AlignmentFlag.AlignCenter) | int(_api.Qt.TextFlag.TextWordWrap),
                text)
            painter.end()

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self._drag_start_pos = e.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not (e.buttons() & _api.Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(e)
        if not hasattr(self, '_drag_start_pos'):
            return super().mouseMoveEvent(e)
        if (e.pos() - self._drag_start_pos).manhattanLength() < 10:
            return super().mouseMoveEvent(e)

        items = self.selectedItems()
        if not items:
            return super().mouseMoveEvent(e)

        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDrag

        urls = []
        for item in items:
            path = item.toolTip(0)  # tooltip хранит полный путь
            if path and _api.os.path.isfile(path):
                urls.append(QUrl.fromLocalFile(path))

        if not urls:
            return super().mouseMoveEvent(e)

        drag = QDrag(self)
        md = QMimeData()
        md.setUrls(urls)
        drag.setMimeData(md)
        drag.exec(_api.Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
            if paths:
                p = self.parent()
                while p and not hasattr(p, 'add_paths'):
                    p = p.parent()
                if p:
                    p.add_paths(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

DraggableTreeWidget.__module__ = _api.__name__
_api.DraggableTreeWidget = DraggableTreeWidget

# ─────────────────────────────────────────────────────────────
#  Photo Merger Tab  (вкладка объединения фотографий)
# ─────────────────────────────────────────────────────────────
class PhotoDragList(_api.QTreeWidget):
    """Список с drag-and-drop файлов извне + перестановка внутри."""

    VALID_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff',
                  '.webp', '.avif', '.heic', '.heif', '.ico', '.svg'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["Превью", "Файл", "Статус"])
        self.header().setSectionResizeMode(0, _api.QHeaderView.ResizeMode.Fixed)
        self.header().setSectionResizeMode(1, _api.QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(2, _api.QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 90)
        self.setColumnWidth(2, 100)
        self.setIconSize(_api.QSize(80, 68))
        self.setAcceptDrops(True)
        self.setDragDropMode(_api.QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(_api.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setStyleSheet("""
            QTreeWidget {
                background-color: #181825;
                alternate-background-color: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 6px;
            }
            QTreeWidget::item { padding: 4px 2px; min-height: 72px; }
            QTreeWidget::item:selected { background-color: transparent; }
            QTreeWidget::item:hover    { background-color: transparent; }
        """)
        # Фон строки по статусу (зелёный — объединено, красный — ошибка) + видимое
        # выделение/hover тем же делегатом, что в Обработке и Загрузчике.
        self.setItemDelegate(_api.StatusColorDelegate(self))

    # ── External drag-and-drop ──────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(_api.Qt.DropAction.CopyAction)
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            links = [str(url.toLocalFile()) for url in event.mimeData().urls()]
            self.add_files(links)
        else:
            super().dropEvent(event)

    # ── Add files ──────────────────────────────────────────
    def add_files(self, paths):
        added = False
        for p in paths:
            if _api.os.path.isfile(p) and _api.os.path.splitext(p)[1].lower() in self.VALID_EXTS:
                item = _api.QTreeWidgetItem(["", _api.os.path.basename(p), "новый"])
                item.setData(0, _api.Qt.ItemDataRole.UserRole, p)
                item.setData(0, _api.Qt.ItemDataRole.UserRole + 1, "new")  # state

                # thumbnail (SVG растеризуется через QtSvg)
                pix = _api.load_pixmap_any(p)
                if not pix.isNull():
                    item.setIcon(0, _api.QIcon(pix.scaled(80, 68, _api.Qt.AspectRatioMode.KeepAspectRatio,
                                                     _api.Qt.TransformationMode.SmoothTransformation)))
                self.addTopLevelItem(item)
                added = True
        if added:
            self.scrollToBottom()

    def get_all_items(self):
        return [self.topLevelItem(i) for i in range(self.topLevelItemCount())]

    def get_new_items(self):
        return [it for it in self.get_all_items()
                if it.data(0, _api.Qt.ItemDataRole.UserRole + 1) == "new"]

    def mark_processed(self, items):
        """Успех: строка зелёная (как в Обработке), без значка-галочки."""
        for it in items:
            it.setData(0, _api.Qt.ItemDataRole.UserRole + 1, "processed")
            it.setIcon(2, _api.QIcon())          # убираем прежний значок «готово»
            it.setText(2, "Готово")
            it.setData(0, _api.ITEM_STATUS_ROLE, 'done')
            for col in range(3):            # снимаем старый произвольный фон
                it.setBackground(col, _api.QBrush())

    def mark_failed(self, items):
        """Ошибка объединения: строка красная. Файлы остаются «новыми» —
        их можно объединить повторно."""
        for it in items:
            it.setIcon(2, _api.QIcon())
            it.setText(2, "Ошибка")
            it.setData(0, _api.ITEM_STATUS_ROLE, 'err')
            for col in range(3):
                it.setBackground(col, _api.QBrush())

PhotoDragList.__module__ = _api.__name__
_api.PhotoDragList = PhotoDragList
