"""Inline text editors, the point-on-image widget and the question/compare dialogs."""

from .qt import *
from .constants import *
from .util import *
from .widgets_common import *

def _editor_context_menu(widget, e):
    """Shared context menu for editable QTextEdit subclasses."""
    menu = QMenu(widget)
    menu.addAction("Вырезать",     widget.cut)
    menu.addAction("Копировать",   widget.copy)
    menu.addAction("Вставить",     widget.paste)
    menu.addSeparator()
    menu.addAction("Выделить всё", widget.selectAll)
    menu.addAction("Отменить",     widget.undo)
    menu.addAction("Повторить",    widget.redo)
    menu.exec(e.globalPos())


class _InlineTextEdit(QTextEdit):
    """Label-like text that becomes editable on click.
    A LMB drag (>9 px) emits block_drag instead of starting edit.
    Focus-out with changes emits save_done(text)."""
    block_drag = pyqtSignal()
    save_done  = pyqtSignal(str)

    def __init__(self, text: str, style_idle: str, style_focus: str = "", parent=None):
        super().__init__(parent)
        self.setPlainText(text)
        self.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        if e.button() == Qt.MouseButton.LeftButton:
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
        if not was_dragging and e.button() == Qt.MouseButton.LeftButton:
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
        if e.key() == Qt.Key.Key_Escape:
            self._changed = False; self.clearFocus()
        else:
            super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        _editor_context_menu(self, e)


class _AnsEdit(QTextEdit):
    """Auto-height answer-row editor.
    Enter (without modifier) → enter_pressed.
    Backspace on empty text    → backspace_empty.
    LMB drag > 9 px            → block_drag (for row reordering).
    File drop with media ext   → media_dropped(path)."""
    enter_pressed   = pyqtSignal()
    backspace_empty = pyqtSignal()
    block_drag      = pyqtSignal()
    media_dropped   = pyqtSignal(str)   # emits local file path

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setPlainText(text)
        self.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        if e.button() == Qt.MouseButton.LeftButton:
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
        no_mod = not (e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier)
        ctrl = e.modifiers() == Qt.KeyboardModifier.ControlModifier
        if e.key() == Qt.Key.Key_Return and no_mod:
            self.enter_pressed.emit()
        elif e.key() == Qt.Key.Key_Backspace and not self.toPlainText():
            self.backspace_empty.emit()
        elif ctrl and e.key() == Qt.Key.Key_A:
            # Select all text in THIS row only (not propagate to parent)
            self.selectAll()
        else:
            super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        # Accept media-file drops; let plain text / row-reorder MIME through normally
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls()]
            if any(Path(p).suffix.lower() in _MEDIA_EXTS for p in paths):
                e.acceptProposedAction(); return
        super().dragEnterEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls()]
            media = [p for p in paths if Path(p).suffix.lower() in _MEDIA_EXTS]
            if media:
                e.acceptProposedAction()
                for p in media:
                    self.media_dropped.emit(p)
                return
        super().dropEvent(e)

    def contextMenuEvent(self, e):
        _editor_context_menu(self, e)


class PointOnImageWidget(QWidget):
    """Interactive image where the player clicks to mark a point answer.
    Shows the correct point (and tolerance circle) after reveal, or lets
    the editor reposition it by clicking/dragging.
    Coordinates are normalised 0..1 (x=left→right, y=top→bottom).
    """

    def __init__(self, image_path: str, cx: float, cy: float, deviation: float,
                 siq=None, rnd=0, th=0, price=0, viewer=None, parent=None):
        super().__init__(parent)
        self._cx  = cx; self._cy  = cy; self._dev = deviation
        self._siq = siq; self._rnd = rnd; self._th = th; self._price = price
        self._viewer = viewer
        self._dragging_point = False
        self._revealed = True        # always show answer in editor mode

        # Load image
        self._pm: QPixmap | None = None
        try:
            reader = QImageReader(image_path); reader.setAutoTransform(True)
            img = reader.read()
            if not img.isNull():
                self._pm = QPixmap.fromImage(img)
        except Exception:
            pass
        if self._pm is None or self._pm.isNull():
            try:
                from PIL import Image as _PI
                with _PI.open(image_path) as _pil:
                    _pil = _pil.convert("RGBA")
                    w_px, h_px = _pil.size
                    raw = _pil.tobytes("raw", "RGBA")
                qimg = QImage(raw, w_px, h_px, w_px * 4,
                              QImage.Format.Format_RGBA8888).copy()
                if not qimg.isNull():
                    self._pm = QPixmap.fromImage(qimg)
            except Exception:
                self._pm = None

        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumHeight(160)
        self.setSizePolicy(_Expand, _Pref)

        # Info bar
        vl = QVBoxLayout(self); vl.setContentsMargins(0,0,0,4); vl.setSpacing(2)
        self._canvas = _PointCanvas(self)
        vl.addWidget(self._canvas, stretch=1)
        info_row = QHBoxLayout(); info_row.setContentsMargins(0, 0, 0, 0); info_row.setSpacing(8)
        self._coord_lbl = QLabel(f"📍 ({cx:.3f}, {cy:.3f})  допуск ±{deviation:.3f}")
        self._coord_lbl.setStyleSheet("color:#a6adc8;font-size:10px;")
        info_row.addWidget(self._coord_lbl)
        info_row.addStretch()
        if siq:
            dev_btn = QPushButton("Допуск…")
            dev_btn.setObjectName(_ON_BTN_COMPARE); dev_btn.setFixedHeight(20)
            dev_btn.setStyleSheet("font-size:10px;padding:0 6px;")
            dev_btn.clicked.connect(self._change_deviation)
            info_row.addWidget(dev_btn)
        vl.addLayout(info_row)
        self._canvas.update()

    def _px_to_norm(self, px: int, py: int):
        """Convert canvas pixel coords to normalised 0..1. Returns None if outside image."""
        r = self._canvas.rect()
        if not self._pm or r.width() == 0 or r.height() == 0:
            return None
        asp = self._pm.width() / self._pm.height()
        if r.width() / max(r.height(), 1) > asp:
            iw = int(r.height() * asp); ih = r.height()
        else:
            iw = r.width(); ih = int(r.width() / max(asp, 0.001))
        ox = (r.width()  - iw) // 2
        oy = (r.height() - ih) // 2
        # Only accept clicks inside the actual image rect
        if px < ox or px > ox + iw or py < oy or py > oy + ih:
            return None
        nx = max(0.0, min(1.0, (px - ox) / iw))
        ny = max(0.0, min(1.0, (py - oy) / ih))
        return nx, ny

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            result = self._px_to_norm(int(e.position().x()), int(e.position().y()))
            if result is not None:
                self._dragging_point = True
                self._cx, self._cy = result
                self._canvas.update(); self._update_coord_lbl()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging_point:
            result = self._px_to_norm(int(e.position().x()), int(e.position().y()))
            if result is not None:
                self._cx, self._cy = result
                self._canvas.update(); self._update_coord_lbl()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._dragging_point:
            self._dragging_point = False
            # Push undo on the ResultPage before saving
            if self._viewer:
                rp = None
                try:
                    rp = self._viewer.parent()
                    while rp and not hasattr(rp, '_push_undo'):
                        rp = rp.parent()
                    if rp and hasattr(rp, '_push_undo'):
                        rp._push_undo()
                except Exception:
                    pass
            self._save_point()
        super().mouseReleaseEvent(e)

    def _update_coord_lbl(self):
        self._coord_lbl.setText(
            f"📍 ({self._cx:.3f}, {self._cy:.3f})  допуск ±{self._dev:.3f}")

    def _change_deviation(self):
        val, ok = QInputDialog.getDouble(
            self, "Допуск", "Радиус допуска (0.01 – 0.5):",
            value=self._dev, min=0.01, max=0.5, decimals=3)
        if ok:
            self._dev = val; self._update_coord_lbl()
            self._canvas.update(); self._save_point()

    def _save_point(self):
        if not self._siq: return
        try:
            qs = self._siq.rounds[self._rnd]["themes"][self._th]["questions"]
            q_idx = _q_idx(qs, self._price)
            # Update in-memory
            qs[q_idx]["answers"] = [f"{self._cx:.4f},{self._cy:.4f}"]
            # Update XML
            root, ns_url, tag, q_el = self._siq._xml_nav_q(self._rnd, self._th, q_idx)
            # Update or create right/answer
            right_el = q_el.find(tag("right"))
            if right_el is None:
                right_el = ET.SubElement(q_el, tag("right"))
            ans_els = right_el.findall(tag("answer"))
            if ans_els:
                ans_els[0].text = f"{self._cx:.4f},{self._cy:.4f}"
            else:
                a = ET.SubElement(right_el, tag("answer"))
                a.text = f"{self._cx:.4f},{self._cy:.4f}"
            # Update answerDeviation
            params_el = q_el.find(tag("params"))
            if params_el is not None:
                for p in params_el.findall(tag("param")):
                    if p.get("name") == "answerDeviation":
                        p.text = f"{self._dev:.4f}"; break
                else:
                    dp = ET.SubElement(params_el, tag("param"))
                    dp.set("name", "answerDeviation"); dp.text = f"{self._dev:.4f}"
            self._siq._save_xml(root, ns_url)
        except Exception as ex:
            _logger.warning(f"[save_point] {ex}")


class _PointCanvas(QWidget):
    """Draws the image with the answer point and tolerance circle."""

    def __init__(self, owner: "PointOnImageWidget", parent=None):
        super().__init__(parent)
        self._o = owner
        self.setSizePolicy(_Expand, _Expand)
        self.setMinimumHeight(140)

    def sizeHint(self):
        pm = self._o._pm
        if pm:
            w = self.width() or 380
            return QSize(w, min(400, int(w * pm.height() / max(pm.width(), 1))))
        return QSize(380, 220)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()

        pm = self._o._pm
        if pm and not pm.isNull():
            asp = pm.width() / pm.height()
            if r.width() / max(r.height(), 1) > asp:
                iw = int(r.height() * asp); ih = r.height()
            else:
                iw = r.width(); ih = int(r.width() / max(asp, 0.001))
            ox = (r.width()  - iw) // 2
            oy = (r.height() - ih) // 2
            scaled = pm.scaled(iw, ih,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(ox, oy, scaled)

            # Tolerance circle
            cx_px = ox + int(self._o._cx * iw)
            cy_px = oy + int(self._o._cy * ih)
            dev_px = int(self._o._dev * min(iw, ih))

            circle_pen = p.pen()
            circle_pen.setColor(QColor(88, 166, 255, 160))
            circle_pen.setWidth(2)
            p.setPen(circle_pen)
            p.setBrush(QBrush(QColor(88, 166, 255, 30)))
            p.drawEllipse(cx_px - dev_px, cy_px - dev_px, dev_px * 2, dev_px * 2)

            # Point marker
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(_C_RED)))
            p.drawEllipse(cx_px - 7, cy_px - 7, 14, 14)
            p.setBrush(QBrush(QColor("white")))
            p.drawEllipse(cx_px - 3, cy_px - 3, 6, 6)

            # Crosshair lines
            cross_pen = p.pen()
            cross_pen.setColor(QColor(248, 81, 73, 200))
            cross_pen.setWidth(1)
            p.setPen(cross_pen)
            p.drawLine(cx_px, oy, cx_px, oy + ih)
            p.drawLine(ox, cy_px, ox + iw, cy_px)
        else:
            p.fillRect(r, QColor(_C_BG2))
            p.setPen(QColor(_C_TEXT4))
            p.drawText(r, _AlignC, "Изображение не найдено")
        p.end()


class QuestionEditorDialog(QDialog):
    """Full-featured question editor: supports both regular and select (choice) questions."""

    saved = pyqtSignal()

    _GRP_STYLE_BLUE  = ("QGroupBox{color:#89b4fa;font-size:11px;font-weight:700;"
                        "border:1px solid #45475a;border-radius:6px;margin-top:6px;padding-top:6px;}"
                        "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
    _GRP_STYLE_GREEN = ("QGroupBox{color:#a6e3a1;font-size:11px;font-weight:700;"
                        "border:1px solid #313244;border-radius:6px;margin-top:6px;padding-top:6px;}"
                        "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
    _GRP_STYLE_GOLD  = ("QGroupBox{color:#f9e2af;font-size:11px;font-weight:700;"
                        "border:1px solid #45475a;border-radius:6px;margin-top:6px;padding-top:6px;}"
                        "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
    _LE_STYLE        = ("background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;"
                        "border-radius:4px;padding:4px 8px;font-size:13px;")
    _TE_STYLE        = ("background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;"
                        "border-radius:4px;padding:4px;font-size:13px;")

    def __init__(self, siq: "SiqPackage", rnd_idx: int, theme_idx: int, q_idx: int,
                 parent=None):
        super().__init__(parent)
        self.siq = siq
        self.rnd_idx = rnd_idx; self.theme_idx = theme_idx; self.q_idx = q_idx
        self.q_obj = siq.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]

        theme_name = siq.rounds[rnd_idx]["themes"][theme_idx]["name"]
        price = self.q_obj["price"]
        is_select = self.q_obj.get("q_type") == "select"
        is_point  = self.q_obj.get("q_type") == "point"
        mode = "Выбор из вариантов" if is_select else ("Точка на изображении" if is_point else "Обычный")
        self.setWindowTitle(f"Редактор — {theme_name} [{price}]  ({mode})")
        self.resize(700, 600)
        self.setStyleSheet(
            "QDialog{background:#181825;color:#cdd6f4;}"
            "QLabel{background:transparent;}"
            "QGroupBox{color:#a6adc8;font-size:11px;font-weight:700;"
            "  border:1px solid #45475a;border-radius:6px;margin-top:6px;padding-top:6px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
        )

        # State
        self._text_edits: list     = []   # QTextEdit list for question text items
        self._ans_edits:  list     = []   # QLineEdit list for regular answers
        self._ans_container        = None
        self._option_rows: list    = []   # [(key_lbl, text_edit, correct_cb), ...]
        self._opt_container        = None
        self._qgrp_vl              = None  # direct ref to question group inner layout
        self._media_labels: list   = []    # labels showing added media files

        self._build()

    # ── Build ──────────────────────────────────────────────────
    def _build(self):

        is_select = self.q_obj.get("q_type") == "select"

        root_vl = QVBoxLayout(self)
        root_vl.setContentsMargins(16, 12, 16, 12); root_vl.setSpacing(10)

        # ── Scrollable area so content fits ──────────────────────
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none; background:#181825;")
        scroll.viewport().setStyleSheet("background:#181825;")
        inner = QWidget(); inner.setStyleSheet("background:#181825;")
        vl = QVBoxLayout(inner); vl.setContentsMargins(0,0,2,8); vl.setSpacing(10)
        scroll.setWidget(inner)
        root_vl.addWidget(scroll, stretch=1)

        # ── Price + mode row ────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.addWidget(_lbl("Цена:", "color:#a6adc8;font-size:12px;"))
        self._price_edit = QLineEdit(str(self.q_obj["price"]))
        self._price_edit.setFixedWidth(90)
        self._price_edit.setStyleSheet(
            "background:#1e1e2e;color:#f9e2af;border:1px solid #45475a;"
            "border-radius:4px;padding:4px 8px;font-size:13px;font-weight:700;")
        top_row.addWidget(self._price_edit)
        top_row.addSpacing(20)
        top_row.addWidget(_lbl("Тип:", "color:#a6adc8;font-size:12px;"))
        self._type_cb = QComboBox()
        self._type_cb.addItem("Обычный", "normal")
        self._type_cb.addItem("Выбор из вариантов", "select")
        self._type_cb.addItem("Точка на изображении", "point")
        cur_type = self.q_obj.get("q_type", "normal") or "normal"
        idx = {"normal": 0, "select": 1, "point": 2}.get(cur_type, 0)
        self._type_cb.setCurrentIndex(idx)
        _style_cb(self._type_cb)
        self._type_cb.setFixedWidth(180)
        top_row.addWidget(self._type_cb)
        top_row.addStretch()
        vl.addLayout(top_row)

        # ── Question text group ─────────────────────────────────
        qgrp = QGroupBox("Текст вопроса"); qgrp.setStyleSheet(self._GRP_STYLE_BLUE)
        qvl = QVBoxLayout(qgrp); qvl.setSpacing(4)
        self._qgrp_vl = qvl  # store direct reference

        txt_items = [it for it in self.q_obj["items"]
                     if it["param"] == "question" and it["type"] == "text" and not it["is_ref"]]
        media_items = [it for it in self.q_obj["items"]
                       if it["param"] == "question" and it["is_ref"]]
        if txt_items:
            for it in txt_items:
                te = QTextEdit(it["text"]); te.setFixedHeight(68)
                te.setStyleSheet(self._TE_STYLE)
                qvl.addWidget(te); self._text_edits.append(te)
        if media_items:
            for it in media_items:
                icon = {"image": "🖼", "audio": "🎵", "video": "🎥"}.get(it["type"], "📎")
                lbl = _lbl(f"{icon} {it['text']}", "color:#a6adc8;font-size:10px;padding:2px 4px;"
                           "background:#1e1e2e;border-radius:3px;")
                qvl.addWidget(lbl); self._media_labels.append(lbl)

        add_txt_btn = QPushButton("＋ Добавить текст")
        add_txt_btn.setObjectName(_ON_BTN_COMPARE); add_txt_btn.setFixedHeight(24)
        add_txt_btn.clicked.connect(lambda: self._add_question_text(""))
        qvl.addWidget(add_txt_btn)

        # ── Media add buttons ─────────────────────────────────
        media_row = QHBoxLayout(); media_row.setSpacing(6)
        for icon, label, filt, itype in [
            ("🖼", "Изображение", "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.avif)", "image"),
            ("🎵", "Аудио",       "Audio (*.mp3 *.ogg *.wav *.aac *.flac *.m4a)",   "audio"),
            ("🎥", "Видео",       "Video (*.mp4 *.avi *.mkv *.mov *.wmv *.webm)",   "video"),
        ]:
            mb = QPushButton(f"{icon} {label}")
            mb.setObjectName(_ON_BTN_COMPARE); mb.setFixedHeight(24)
            mb.clicked.connect(lambda _, f=filt, t=itype: self._pick_media_file(f, t, 'question'))
            media_row.addWidget(mb)
        media_row.addStretch()
        qvl.addLayout(media_row)
        vl.addWidget(qgrp)

        # ── Answer section — swaps between modes ────────────────
        self._ans_stack = QStackedWidget()
        vl.addWidget(self._ans_stack)

        # ─ Regular answer panel ────────────────────────────────
        reg_w = QWidget(); reg_w.setStyleSheet(_SS_TRANSPARENT)
        reg_vl = QVBoxLayout(reg_w); reg_vl.setContentsMargins(0, 0, 0, 0); reg_vl.setSpacing(6)
        agrp = QGroupBox("Правильный ответ"); agrp.setStyleSheet(self._GRP_STYLE_GREEN)
        avl = QVBoxLayout(agrp); avl.setSpacing(4)
        self._ans_container = QVBoxLayout(); self._ans_container.setSpacing(4)
        ans_src = self.q_obj["answers"] if not is_select else []
        for ans in ans_src:
            self._add_answer_row(ans)
        add_ans_btn = QPushButton("＋ Добавить вариант")
        add_ans_btn.setObjectName(_ON_BTN_ANALYZE); add_ans_btn.setFixedHeight(24)
        add_ans_btn.clicked.connect(lambda: self._add_answer_row(""))
        avl.addLayout(self._ans_container); avl.addWidget(add_ans_btn)
        reg_vl.addWidget(agrp)
        self._ans_stack.addWidget(reg_w)   # index 0

        # ─ Select (choice) answer panel ────────────────────────
        sel_w = QWidget(); sel_w.setStyleSheet(_SS_TRANSPARENT)
        sel_vl = QVBoxLayout(sel_w); sel_vl.setContentsMargins(0, 0, 0, 0); sel_vl.setSpacing(6)

        sel_grp = QGroupBox("Варианты ответов  (✓ = правильный)")
        sel_grp.setStyleSheet(self._GRP_STYLE_GOLD)
        sel_inner = QVBoxLayout(sel_grp); sel_inner.setSpacing(4)
        self._opt_container = QVBoxLayout(); self._opt_container.setSpacing(4)

        # Populate existing options or defaults
        existing_opts = self.q_obj.get("answer_options", {})
        correct_keys  = set(self.q_obj.get("answers", []))
        if existing_opts:
            for key in sorted(existing_opts.keys()):
                oi_list = existing_opts[key]
                text = oi_list[0]["text"] if oi_list else ""
                self._add_option_row(key, text, key in correct_keys)
        else:
            # Default: two options A/B
            for key, correct in [("A", True), ("B", False)]:
                self._add_option_row(key, "", correct)

        add_opt_btn = QPushButton("＋ Добавить вариант")
        add_opt_btn.setObjectName(_ON_BTN_COMPARE); add_opt_btn.setFixedHeight(24)
        add_opt_btn.clicked.connect(self._add_next_option)
        sel_inner.addLayout(self._opt_container)
        sel_inner.addWidget(add_opt_btn)
        sel_vl.addWidget(sel_grp)
        self._ans_stack.addWidget(sel_w)   # index 1

        # ─ Point-on-image panel ─────────────────────────────────
        pt_w = QWidget(); pt_w.setStyleSheet(_SS_TRANSPARENT)
        pt_vl = QVBoxLayout(pt_w); pt_vl.setContentsMargins(0, 0, 0, 0); pt_vl.setSpacing(6)
        pt_grp = QGroupBox("Точка ответа  (кликните по изображению ответа)")
        pt_grp.setStyleSheet(self._GRP_STYLE_GREEN)
        pt_inner_vl = QVBoxLayout(pt_grp); pt_inner_vl.setSpacing(4)
        # Point coords input
        coords_row = QHBoxLayout(); coords_row.setSpacing(6)
        coords_row.addWidget(_lbl("X (0–1):", "color:#a6adc8;font-size:11px;"))
        self._pt_x = QLineEdit(); self._pt_x.setStyleSheet(self._LE_STYLE); self._pt_x.setFixedWidth(70)
        coords_row.addWidget(self._pt_x)
        coords_row.addWidget(_lbl("Y (0–1):", "color:#a6adc8;font-size:11px;"))
        self._pt_y = QLineEdit(); self._pt_y.setStyleSheet(self._LE_STYLE); self._pt_y.setFixedWidth(70)
        coords_row.addWidget(self._pt_y)
        coords_row.addWidget(_lbl("Допуск:", "color:#a6adc8;font-size:11px;"))
        self._pt_dev = QLineEdit(); self._pt_dev.setStyleSheet(self._LE_STYLE); self._pt_dev.setFixedWidth(70)
        coords_row.addWidget(self._pt_dev); coords_row.addStretch()
        pt_inner_vl.addLayout(coords_row)
        # Pre-fill from existing data
        existing_ans = self.q_obj.get("answers", [])
        if existing_ans:
            try:
                ex_cx, ex_cy = map(float, existing_ans[0].split(","))
                self._pt_x.setText(f"{ex_cx:.4f}"); self._pt_y.setText(f"{ex_cy:.4f}")
            except Exception:
                self._pt_x.setText("0.5"); self._pt_y.setText("0.5")
        else:
            self._pt_x.setText("0.5"); self._pt_y.setText("0.5")
        self._pt_dev.setText(f"{self.q_obj.get('answer_deviation', 0.1):.4f}")
        pt_vl.addWidget(pt_grp)
        self._ans_stack.addWidget(pt_w)   # index 2

        cur_idx = {"normal": 0, "select": 1, "point": 2}.get(self.q_obj.get("q_type", ""), 0)
        self._ans_stack.setCurrentIndex(cur_idx)
        self._type_cb.currentIndexChanged.connect(
            lambda i: self._ans_stack.setCurrentIndex(i))

        # ── Bottom buttons ──────────────────────────────────────
        bot = QHBoxLayout(); bot.setSpacing(8); bot.addStretch()
        cancel_btn = AnimatedButton("Отмена"); cancel_btn.clicked.connect(self.reject)
        save_btn = AnimatedButton("💾  Сохранить"); save_btn.setObjectName(_ON_BTN_ANALYZE)
        save_btn.clicked.connect(self._save)
        bot.addWidget(cancel_btn); bot.addWidget(save_btn)
        root_vl.addLayout(bot)

    # ── Helpers: question text ─────────────────────────────────
    def _add_question_text(self, text: str = ""):
        te = QTextEdit(text); te.setFixedHeight(68)
        te.setStyleSheet(self._TE_STYLE)
        if self._qgrp_vl:
            # Insert before the "add text" button (second-to-last item) + before media row
            # Count: last 2 items are add_txt_btn + media_row → insert before them
            insert_pos = max(0, self._qgrp_vl.count() - 2)
            self._qgrp_vl.insertWidget(insert_pos, te)
            self._text_edits.append(te)

    def _pick_media_file(self, file_filter: str, itype: str, param_name: str):
        """Open file dialog, copy picked file into the SIQ zip, refresh the label list."""
        if not self.siq.path:
            QMessageBox.warning(self, "Нет файла", "SIQ файл не прикреплён."); return
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл", "", file_filter + ";;All (*)")
        if not path: return
        ok = self.siq.add_media_to_question(
            self.rnd_idx, self.theme_idx, self.q_idx, path, param_name)
        if ok:
            icon = {"image": "🖼", "audio": "🎵", "video": "🎥"}.get(itype, "📎")
            fname = os.path.basename(path)
            lbl = _lbl(f"{icon} {fname}", "color:#a6adc8;font-size:10px;padding:2px 4px;"
                       "background:#1e1e2e;border-radius:3px;")
            if self._qgrp_vl:
                insert_pos = max(0, self._qgrp_vl.count() - 2)
                self._qgrp_vl.insertWidget(insert_pos, lbl)
            self._media_labels.append(lbl)
            QMessageBox.information(self, "Добавлено", f"Файл добавлен: {fname}")
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось добавить файл в .siq пакет.")

    # ── Helpers: regular answers ───────────────────────────────
    def _add_answer_row(self, text: str = ""):
        row = QHBoxLayout(); row.setSpacing(4)
        le = QLineEdit(text); le.setStyleSheet(
            "background:#1e1e2e;color:#a6e3a1;border:1px solid #45475a;"
            "border-radius:4px;padding:4px 8px;font-size:13px;")
        self._ans_edits.append(le); row.addWidget(le, stretch=1)
        del_btn = QPushButton("✕"); del_btn.setObjectName(_ON_BTN_DEL)
        del_btn.setFixedSize(22, 22)
        def _rm(le=le, del_btn=del_btn):
            if le in self._ans_edits: self._ans_edits.remove(le)
            le.deleteLater(); del_btn.deleteLater()
        del_btn.clicked.connect(lambda *_: _rm()); row.addWidget(del_btn)
        row_w = QWidget(); row_w.setStyleSheet(_SS_TRANSPARENT)
        row_w.setLayout(row)
        self._ans_container.addWidget(row_w)

    # ── Helpers: select options ────────────────────────────────
    _OPTION_KEYS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    def _next_free_key(self) -> str:
        used = {r[0] for r in self._option_rows}
        for k in self._OPTION_KEYS:
            if k not in used: return k
        return str(len(self._option_rows) + 1)

    def _add_option_row(self, key: str, text: str = "", correct: bool = False):
        row = QHBoxLayout(); row.setSpacing(6)

        # Correct-answer checkbox
        cb = QCheckBox(); cb.setChecked(correct)
        cb.setStyleSheet("QCheckBox::indicator{width:16px;height:16px;border-radius:8px;"
                         "border:2px solid #45475a;background:#1e1e2e;}"
                         "QCheckBox::indicator:checked{background:#a6e3a1;border-color:#a6e3a1;}")
        cb.setToolTip("Отметьте правильный вариант")
        # Single-select: uncheck others when this one is checked
        cb.toggled.connect(lambda checked, c=cb: self._on_opt_checked(c, checked))
        row.addWidget(cb)

        # Key label
        key_lbl = QLabel(key)
        key_lbl.setFixedSize(24, 24)
        key_lbl.setAlignment(_AlignC)
        key_lbl.setStyleSheet(
            "background:#313244;color:#a6adc8;border-radius:12px;"
            "font-size:12px;font-weight:700;")
        row.addWidget(key_lbl)

        # Text input
        le = QLineEdit(text); le.setStyleSheet(self._LE_STYLE)
        le.setPlaceholderText(f"Вариант {key}…")
        row.addWidget(le, stretch=1)

        # Delete button
        del_btn = QPushButton("✕"); del_btn.setObjectName(_ON_BTN_DEL)
        del_btn.setFixedSize(22, 22)
        rec = [key, le, cb]   # mutable container so _rm can find it
        def _rm(rec=rec, del_btn=del_btn):
            if rec in self._option_rows: self._option_rows.remove(rec)
            rec[1].deleteLater(); del_btn.deleteLater()
        del_btn.clicked.connect(lambda *_: _rm()); row.addWidget(del_btn)

        row_w = QWidget(); row_w.setStyleSheet(_SS_TRANSPARENT)
        row_w.setLayout(row)
        self._opt_container.addWidget(row_w)
        self._option_rows.append(rec)   # [key, le, cb]

    def _on_opt_checked(self, sender_cb, checked: bool):
        """Keep only one checkbox checked at a time (single-correct mode)."""
        if not checked: return
        for rec in self._option_rows:
            cb = rec[2]
            if cb is not sender_cb and cb.isChecked():
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)

    def _add_next_option(self):
        if len(self._option_rows) >= len(self._OPTION_KEYS): return
        self._add_option_row(self._next_free_key(), "", False)

    # ── Save ───────────────────────────────────────────────────
    def _save(self):
        try:
            new_price = int(self._price_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Цена должна быть целым числом."); return

        new_q_texts = [te.toPlainText().strip() for te in self._text_edits]
        cur_type = self._type_cb.currentData()
        is_select = (cur_type == "select")
        is_point  = (cur_type == "point")

        if is_point:
            # ── Point-on-image ───────────────────────────────────
            try:
                cx  = float(self._pt_x.text().strip())
                cy  = float(self._pt_y.text().strip())
                dev = float(self._pt_dev.text().strip())
            except ValueError:
                QMessageBox.warning(self, "Ошибка", "X, Y и допуск должны быть числами от 0 до 1."); return
            ok = self.siq.save_point_question(
                self.rnd_idx, self.theme_idx, self.q_idx,
                new_price, new_q_texts, cx, cy, dev)
        elif is_select:
            # ── Select options (allow empty text, correct_key optional) ──
            options: dict[str, str] = {}
            correct_key = None
            for rec in self._option_rows:
                key = rec[0]; le = rec[1]; cb = rec[2]
                options[key] = le.text().strip()  # allow empty
                if cb.isChecked(): correct_key = key
            if not options:
                QMessageBox.warning(self, "Ошибка", "Добавьте хотя бы один вариант."); return
            if correct_key is None and options:
                correct_key = next(iter(options))  # default to first

            ok = self.siq.save_select_question(
                self.rnd_idx, self.theme_idx, self.q_idx,
                new_price, new_q_texts, options, correct_key)
        else:
            # ── Regular question ─────────────────────────────────
            new_answers = [le.text().strip() for le in self._ans_edits if le.text().strip()]
            ok_txt   = self.siq.save_question(
                self.rnd_idx, self.theme_idx, self.q_idx, new_q_texts, new_answers)
            ok_price = True
            if new_price != self.q_obj["price"]:
                ok_price = self.siq.save_question_price(
                    self.rnd_idx, self.theme_idx, self.q_idx, new_price)
            ok = ok_txt and ok_price

        if ok:
            self.saved.emit(); self.accept()
        else:
            QMessageBox.warning(self, "Ошибка",
                "Не удалось сохранить.\nУбедитесь, что файл не открыт другой программой.")

__all__ = [
    'PointOnImageWidget',
    'QuestionEditorDialog',
    '_AnsEdit',
    '_InlineTextEdit',
    '_PointCanvas',
    '_editor_context_menu',
]
