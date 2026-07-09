"""Generic reusable widgets and event filters (buttons, progress bars, scroll areas, list)."""

from .qt import *
from .constants import *


def _selectable_box(icon, parent, title, text, buttons, default_button):
    """QMessageBox с выделяемым мышью и копируемым текстом (в отличие от
    статических QMessageBox.critical/warning/information/question)."""
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.setStandardButtons(buttons)
    if default_button is not None:
        box.setDefaultButton(default_button)
    return box.exec()


def msgbox_critical(parent, title, text,
                     buttons=QMessageBox.StandardButton.Ok,
                     defaultButton=QMessageBox.StandardButton.NoButton):
    return _selectable_box(QMessageBox.Icon.Critical, parent, title, text, buttons, defaultButton)


def msgbox_warning(parent, title, text,
                    buttons=QMessageBox.StandardButton.Ok,
                    defaultButton=QMessageBox.StandardButton.NoButton):
    return _selectable_box(QMessageBox.Icon.Warning, parent, title, text, buttons, defaultButton)


def msgbox_information(parent, title, text,
                        buttons=QMessageBox.StandardButton.Ok,
                        defaultButton=QMessageBox.StandardButton.NoButton):
    return _selectable_box(QMessageBox.Icon.Information, parent, title, text, buttons, defaultButton)


def msgbox_question(parent, title, text,
                     buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                     defaultButton=QMessageBox.StandardButton.NoButton):
    return _selectable_box(QMessageBox.Icon.Question, parent, title, text, buttons, defaultButton)


class _HoverFilter(QObject):
    """Event filter that tracks Enter/Leave for a container widget.
    Defined at module level so Python doesn't reallocate the class
    bytecode for every call to _build_deletable_item().
    on_enter / on_leave callbacks are called with no arguments."""

    def __init__(self, watched: QWidget, on_enter, on_leave):
        super().__init__(watched)
        self._w        = watched
        self._on_enter = on_enter
        self._on_leave = on_leave
        self._inside   = False

    def eventFilter(self, obj, event):
        try:
            t = event.type()
            if t == QEvent.Type.Enter:
                if not self._inside:
                    self._inside = True
                    self._on_enter()
            elif t == QEvent.Type.Leave:
                try:
                    from PyQt6.QtGui import QCursor
                    lp = self._w.mapFromGlobal(QCursor.pos())
                    if not self._w.rect().contains(lp):
                        self._inside = False
                        self._on_leave()
                except RuntimeError:
                    self._inside = False
        except RuntimeError:
            pass
        return False


class _WheelToViewport(QObject):
    """Handles wheel events on scrollbars by directly adjusting the scrollbar value."""
    def __init__(self, scroll_area):
        super().__init__(scroll_area)
        self._sa = scroll_area

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            bar = self._sa.verticalScrollBar()
            bar.setValue(bar.value() - delta // 3)
            return True  # consume — do NOT forward further
        return False


def _install_wheel_filter(scroll_area):
    f = _WheelToViewport(scroll_area)
    scroll_area.verticalScrollBar().installEventFilter(f)
    scroll_area.horizontalScrollBar().installEventFilter(f)


class AnimatedButton(QPushButton):
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw)
        self._eff = QGraphicsOpacityEffect(self); self._eff.setOpacity(1.0); self.setGraphicsEffect(self._eff)
        self._anim = QPropertyAnimation(self._eff,b"opacity",self)
        self._anim.setDuration(200); self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    def mousePressEvent(self,e):
        self._eff.setOpacity(0.5); self._anim.stop()
        self._anim.setStartValue(0.5); self._anim.setEndValue(1.0); self._anim.start()
        super().mousePressEvent(e)


class GameProgressBar(QFrame):
    def __init__(self,text,pct,parent=None):
        super().__init__(parent); self.pct=max(0.0,min(100.0,pct)); self.text=text
        self.setFixedHeight(26); self.setSizePolicy(_Expand,_Fixed)
        self.setMinimumWidth(220)
    def paintEvent(self,_):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w,h,r=self.width(),self.height(),5
        p.setBrush(QBrush(QColor(_C_BG4))); p.setPen(QColor(_C_BORDER)); p.drawRoundedRect(0,0,w,h,r,r)
        fw=max(0,int(w*self.pct/100))
        if fw>0:
            # Конец градиента НЕ должен совпадать с цветом текста (#cba6f7) —
            # иначе на закрашенной части текст сливается с фоном и его не видно.
            g=QLinearGradient(0,0,fw,0); g.setColorAt(0,QColor("#313244")); g.setColorAt(1,QColor("#89b4fa"))
            p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
            path=QPainterPath(); path.addRoundedRect(QRectF(0,0,fw,h),r,r)
            p.setClipPath(path); p.drawRect(0,0,fw,h); p.setClipping(False)
        p.setPen(QColor("#cba6f7")); p.setFont(QFont("Segoe UI",9,QFont.Weight.DemiBold))
        p.drawText(0,0,w,h,_AlignC,self.text); p.end()


class _QProgressWidget(QFrame):
    """Thin gradient progress bar for question completeness (0-100%)."""
    def __init__(self, pct: float, parent=None):
        super().__init__(parent)
        self._pct = max(0.0, min(100.0, pct))
        self.setFixedHeight(8)
        self.setSizePolicy(_Expand, _Fixed)

    def update_pct(self, pct: float):
        """Update percentage in-place and trigger a repaint (no widget rebuild)."""
        new = max(0.0, min(100.0, pct))
        if new != self._pct:
            self._pct = new
            self.update()   # schedules a single paintEvent, no layout change

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, r = self.width(), self.height(), 4
        # Track
        p.setBrush(QBrush(QColor(_C_BG3))); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, r, r)
        # Fill
        fw = max(0, int(w * self._pct / 100))
        if fw > 0:
            # Green gradient: empty→half→full
            g = QLinearGradient(0, 0, fw, 0)
            g.setColorAt(0.0, QColor("#89b4fa"))
            g.setColorAt(0.5, QColor("#a6e3a1"))
            g.setColorAt(1.0, QColor("#a6e3a1"))
            p.setBrush(QBrush(g))
            fill_path = QPainterPath()
            fill_path.addRoundedRect(QRectF(0, 0, fw, h), r, r)
            p.setClipPath(fill_path); p.drawRect(0, 0, fw, h); p.setClipping(False)
        p.end()


class SmoothScrollArea(QScrollArea):
    def __init__(self,parent=None):
        super().__init__(parent); self.setWidgetResizable(True)
        self._target_v=0.0; self._timer=QTimer(self); self._timer.setInterval(14)
        self._timer.timeout.connect(self._step)
    def wheelEvent(self,event):
        if not self._timer.isActive(): self._target_v=float(self.verticalScrollBar().value())
        self._target_v -= event.angleDelta().y()*1.1
        self._target_v = max(0.0, min(float(self.verticalScrollBar().maximum()), self._target_v))
        self._timer.start(); event.accept()
    def _step(self):
        bar=self.verticalScrollBar(); cur=float(bar.value()); diff=self._target_v-cur
        if abs(diff)<0.9: bar.setValue(int(self._target_v)); self._timer.stop()
        else: bar.setValue(int(cur+diff*0.20))


class _OutsideClickFilter(QObject):
    """Global event filter that calls a commit function when the user clicks
    outside a given widget, then removes itself.  Defined at module level so
    Python doesn't reallocate the class on every theme-rename interaction."""
    def __init__(self, watched_widget, commit_fn):
        super().__init__()
        self._w      = watched_widget
        self._commit = commit_fn

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonPress:
            try:
                if obj is not self._w and not self._w.isHidden():
                    self._commit()
            except RuntimeError:
                pass
            QApplication.instance().removeEventFilter(self)
            try: self.deleteLater()
            except RuntimeError: pass
        return False


class DropEdit(QTextEdit):
    def __init__(self,parent=None): super().__init__(parent); self.setAcceptDrops(True)
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith((".txt",".html",".htm")) for u in e.mimeData().urls()): e.acceptProposedAction(); return
        super().dragEnterEvent(e)
    def dragMoveEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
        else: super().dragMoveEvent(e)
    def dropEvent(self,e):
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                p=url.toLocalFile()
                if p.lower().endswith((".txt",".html",".htm")):
                    try:
                        with open(p,"r",encoding="utf-8") as f: self.setPlainText(f.read())
                    except Exception as ex: msgbox_warning(self,"Ошибка",str(ex))
                    e.acceptProposedAction(); return
        else: super().dropEvent(e)


class PkgListWidget(QListWidget):
    reorder_real = pyqtSignal(int,int)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True); self.setAcceptDrops(True); self.setDropIndicatorShown(True)
        self._drag_display=-1; self._real_indices: list[int]=[]
    def startDrag(self,s): self._drag_display=self.currentRow(); super().startDrag(s)
    def dropEvent(self,event):
        old=self._drag_display; super().dropEvent(event); new=self.currentRow()
        if old>=0 and new>=0 and old!=new and old<len(self._real_indices) and new<len(self._real_indices):
            self.reorder_real.emit(self._real_indices[old],self._real_indices[new])
        self._drag_display=-1

__all__ = [
    'AnimatedButton',
    'DropEdit',
    'GameProgressBar',
    'PkgListWidget',
    'SmoothScrollArea',
    '_HoverFilter',
    '_OutsideClickFilter',
    '_QProgressWidget',
    '_WheelToViewport',
    '_install_wheel_filter',
    'msgbox_critical',
    'msgbox_warning',
    'msgbox_information',
    'msgbox_question',
]
