# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_editor_context_menu. Public namespace: siquester.widgets_editors."""
import siquester.widgets_editors as _api


def _editor_context_menu(widget, e):
    """Shared context menu for editable QTextEdit subclasses."""
    menu = _api.QMenu(widget)
    menu.addAction("Вырезать",     widget.cut)
    menu.addAction("Копировать",   widget.copy)
    menu.addAction("Вставить",     widget.paste)
    menu.addSeparator()
    menu.addAction("Выделить всё", widget.selectAll)
    menu.addAction("Отменить",     widget.undo)
    menu.addAction("Повторить",    widget.redo)
    menu.exec(e.globalPos())

_editor_context_menu.__module__ = _api.__name__
_api._editor_context_menu = _editor_context_menu

class _InlineTextEdit(_api.QTextEdit):
    """Label-like text that becomes editable on click.
    A LMB drag (>9 px) emits block_drag instead of starting edit.
    Focus-out with changes emits save_done(text)."""
    block_drag = _api.pyqtSignal()
    save_done  = _api.pyqtSignal(str)

    def __init__(self, text: str, style_idle: str, style_focus: str = "", parent=None):
        super().__init__(parent)
        self.setPlainText(text)
        self.setWordWrapMode(_api.QTextOption.WrapMode.WordWrap)
        self.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._style_idle  = style_idle
        self._style_focus = style_focus if style_focus else (
            style_idle + "border:1px solid #89b4fa;border-radius:4px;")
        self.setStyleSheet(self._style_idle)
        self._drag_origin = None
        self._dragging    = False   # True once drag threshold exceeded
        self._changed = False
        self._last_doc_h  = -1     # tracks last measured height — skip layout when unchanged
        self.document().contentsChanged.connect(self._on_change)
        self._fit_height()

    def _on_change(self):
        self._changed = True; self._fit_height()

    def _fit_height(self):
        doc_h = int(self.document().size().height())
        new_h = max(24, doc_h + 10)
        if new_h != self._last_doc_h:        # skip setFixedHeight when nothing changed
            self._last_doc_h = new_h
            self.setFixedHeight(new_h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_height()

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self._drag_origin = e.position().toPoint()
            self._dragging    = False
        # Don't call super yet — wait to see if it's a drag

    def mouseMoveEvent(self, e):
        if self._drag_origin and not self._dragging:
            if (e.position().toPoint() - self._drag_origin).manhattanLength() > 9:
                self._dragging    = True
                self._drag_origin = None
                self.block_drag.emit()
                return
        if not self._dragging:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        was_dragging = self._dragging
        self._drag_origin = None
        self._dragging    = False
        if not was_dragging and e.button() == _api.Qt.MouseButton.LeftButton:
            # Only NOW act as a normal click → focus and place cursor
            super().mousePressEvent(e)    # replay press so cursor is placed correctly
            super().mouseReleaseEvent(e)
        elif not was_dragging:
            super().mouseReleaseEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.setStyleSheet(self._style_focus)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.setStyleSheet(self._style_idle)
        if self._changed:
            self._changed = False
            self.save_done.emit(self.toPlainText())

    def keyPressEvent(self, e):
        if e.key() == _api.Qt.Key.Key_Escape:
            self._changed = False; self.clearFocus()
        else:
            super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        _api._editor_context_menu(self, e)

_InlineTextEdit.__module__ = _api.__name__
_api._InlineTextEdit = _InlineTextEdit

class _AnsEdit(_api.QTextEdit):
    """Auto-height answer-row editor.
    Enter (without modifier) → enter_pressed.
    Backspace on empty text    → backspace_empty.
    LMB drag > 9 px            → block_drag (for row reordering).
    File drop with media ext   → media_dropped(path)."""
    enter_pressed   = _api.pyqtSignal()
    backspace_empty = _api.pyqtSignal()
    block_drag      = _api.pyqtSignal()
    media_dropped   = _api.pyqtSignal(str)   # emits local file path

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setPlainText(text)
        self.setWordWrapMode(_api.QTextOption.WrapMode.WordWrap)
        self.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QTextEdit{background:#1e1e2e;color:#a6e3a1;border:1px solid #45475a;"
            "border-radius:4px;padding:4px 8px;font-size:13px;}")
        self._drag_origin = None
        self._dragging    = False
        self.document().contentsChanged.connect(self._fit_height)
        self._fit_height()

    def _fit_height(self):
        h = int(self.document().size().height()) + 10
        self.setFixedHeight(max(30, h))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_height()

    def text(self): return self.toPlainText()
    def setText(self, t): self.setPlainText(t)

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self._drag_origin = e.position().toPoint()
            self._dragging    = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        # Only trigger block_drag on vertical drag (Y > X) to avoid breaking text selection
        if self._drag_origin and not self._dragging:
            delta = e.position().toPoint() - self._drag_origin
            if (abs(delta.y()) > abs(delta.x()) + 3
                    and delta.manhattanLength() > 9):
                self._dragging    = True
                self._drag_origin = None
                self.block_drag.emit()
                return
        if not self._dragging:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_origin = None
        self._dragging    = False
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        e.ignore()   # не прокручивать строку при наведении колеса мыши

    def keyPressEvent(self, e):
        no_mod = not (e.modifiers() & ~_api.Qt.KeyboardModifier.KeypadModifier)
        ctrl = e.modifiers() == _api.Qt.KeyboardModifier.ControlModifier
        if e.key() == _api.Qt.Key.Key_Return and no_mod:
            self.enter_pressed.emit()
        elif e.key() == _api.Qt.Key.Key_Backspace and not self.toPlainText():
            self.backspace_empty.emit()
        elif ctrl and (e.key() == _api.Qt.Key.Key_A or self._is_native_vk_a(e)):
            # Select all text in THIS row only (not propagate to parent).
            # e.key()==Key_A alone misses кириллицу (физическая A шлёт код
            # буквы Ф) — фолбэк по nativeVirtualKey (VK_A=0x41), не зависящий
            # от раскладки (тот же приём, что и Ctrl+Z/Y в edit_tab.py/tabs.py).
            self.selectAll()
        else:
            super().keyPressEvent(e)

    @staticmethod
    def _is_native_vk_a(e):
        try:
            return e.nativeVirtualKey() == 0x41
        except Exception:
            return False

    def dragEnterEvent(self, e):
        # Accept media-file drops; let plain text / row-reorder MIME through normally
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls()]
            if any(_api.Path(p).suffix.lower() in _api._MEDIA_EXTS for p in paths):
                e.acceptProposedAction(); return
        super().dragEnterEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls()]
            media = [p for p in paths if _api.Path(p).suffix.lower() in _api._MEDIA_EXTS]
            if media:
                e.acceptProposedAction()
                for p in media:
                    self.media_dropped.emit(p)
                return
        super().dropEvent(e)

    def contextMenuEvent(self, e):
        _api._editor_context_menu(self, e)

_AnsEdit.__module__ = _api.__name__
_api._AnsEdit = _AnsEdit
