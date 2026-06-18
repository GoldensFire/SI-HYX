"""Tile drag-and-drop board and the package-info dialog."""

from .qt import *
from .constants import *
from .util import *
from .widgets_common import *

class _TileDropArea(QWidget):
    """Horizontal flow of question tiles with animated insertion-gap on drag-over."""
    question_clicked = pyqtSignal(int, int, int)   # r, t, price
    add_clicked      = pyqtSignal(int, int)         # r, t
    move_requested   = pyqtSignal(int, int, int, int, int)  # src_r, src_t, price, dst_r, dst_t, insert_idx
    # We use a 5-arg version; insert_idx is carried as 5th int via custom emit

    def __init__(self, r_idx, t_idx, result_page, has_siq, parent=None):
        super().__init__(parent)
        self.r_idx = r_idx; self.t_idx = t_idx
        self._rp = result_page; self._has_siq = has_siq
        self.setStyleSheet(_SS_TRANSPARENT)
        self.setAcceptDrops(has_siq)
        self.setMinimumHeight(82)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6,4,6,4)
        self._layout.setSpacing(5)
        self._layout.setAlignment(_AlignL | _AlignVC)

        # Gap spacer shown during drag-hover
        self._gap = QWidget(); self._gap.setFixedWidth(0); self._gap.setFixedHeight(70)
        self._gap.setStyleSheet("background:rgba(137,180,250,0.18);border-radius:6px;")
        self._gap_idx = -1   # position in layout where gap is shown
        self._gap_anim = QPropertyAnimation(self._gap, b"minimumWidth")
        self._gap_anim.setDuration(80); self._gap_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._tiles: list = []   # list of tile QFrame widgets (no gap, no plus)
        self._plus_tile = None
        self._selected_price: int = -1  # price of currently highlighted tile
        self._selected_tile: object = None   # direct ref to currently selected tile widget
        self._price_to_tile: dict = {}       # price → tile widget for O(1) lookup

    def add_tile(self, q: dict, has_siq: bool):
        pct_t = q.get("tries", 0); pct_r = q.get("right", 0)

        if pct_t > 0 or pct_r > 0:
            both = min(pct_t, pct_r)
            if both > 75:
                bg, bd = "rgba(166,227,161,0.45)",  "#a6e3a1"
            elif both > 50:
                bg, bd = "rgba(249,226,175,0.42)",  "#f9e2af"
            elif both > 30:
                bg, bd = "rgba(250,179,135,0.42)",  "#fab387"
            else:
                bg, bd = "rgba(243,139,168,0.42)",  "#f38ba8"
        else:
            bg, bd = "rgba(249,226,175,0.22)", "#f9e2af"

        # Content completeness — cache .get() results, avoid repeated lookups
        items   = q.get("items", [])
        answers = q.get("answers", [])
        has_q_text = any(
            (it.get("param") in ("question", "background") and
             ((it.get("text") or "").strip() or it.get("is_ref")))
            for it in items
        )
        has_answer = bool(answers and any(a.strip() for a in answers))

        # Base border & background from stats; override for empty/partial
        if pct_t == 0 and pct_r == 0:
            if not has_q_text and not has_answer:
                bg, bd = "rgba(108,112,134,0.22)", "#7f849c"   # grey — fully empty
            elif has_q_text and not has_answer:
                bg, bd = "rgba(137,180,250,0.26)", "#89b4fa"    # blue — Q ok, no A
            elif not has_q_text and has_answer:
                bg, bd = "rgba(203,166,247,0.26)", "#cba6f7"   # purple — A ok, no Q
            else:
                bg, bd = "rgba(249,226,175,0.24)", "#f9e2af"    # gold — complete

        # Build the stylesheet string once; reuse it for sel_ss — avoid
        # calling tile.styleSheet() which goes through Qt's C++ bridge.
        if pct_t == 0 and pct_r == 0 and (has_q_text or has_answer):
            q_col = "rgba(137,180,250,0.40)"  if has_q_text else "rgba(243,139,168,0.26)"
            a_col = "rgba(203,166,247,0.40)" if has_answer  else "rgba(243,139,168,0.26)"
            gradient_ss = (f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                           f"stop:0 {q_col},stop:0.5 {q_col},"
                           f"stop:0.501 {a_col},stop:1 {a_col});")
            base_ss = f"QFrame{{{gradient_ss}border:1px solid {bd};border-radius:6px;}}"
        else:
            base_ss = f"QFrame{{background:{bg};border:1px solid {bd};border-radius:6px;}}"

        tile = QFrame(); tile.setFixedSize(84, 70)
        tile.setStyleSheet(base_ss)

        tile.setProperty("q_price", q["price"])
        tl = QVBoxLayout(tile); tl.setContentsMargins(3,3,3,3); tl.setSpacing(1)
        tl.addWidget(_lbl(str(q["price"]), f"color:{bd};font-size:14px;font-weight:700;"), 0, _AlignC)
        if pct_t > 0 or pct_r > 0:
            tl.addWidget(_lbl(f"▶ {pct_t}%", "color:#f9e2af;font-size:11px;font-weight:600;"), 0, _AlignC)
            tl.addWidget(_lbl(f"✓ {pct_r}%", "color:#a6e3a1;font-size:11px;font-weight:600;"), 0, _AlignC)
        else:
            tl.addWidget(_lbl("нет стат.", "color:#7f849c;font-size:10px;"), 0, _AlignC)

        if has_siq:
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setProperty("q_ri", self.r_idx)
            tile.setProperty("q_ti", self.t_idx)
            tile.setProperty("q_price", q["price"])
            press, move, release, dbl = self._make_tile_handlers(tile)
            tile.mousePressEvent       = press
            tile.mouseMoveEvent        = move
            tile.mouseReleaseEvent     = release
            tile.mouseDoubleClickEvent = dbl

        # Store tile data as Python attributes (not Qt properties) — avoids
        # the overhead of Qt's property() C++ bridge on every select/deselect/drag.
        tile._q_ri    = self.r_idx
        tile._q_ti    = self.t_idx
        tile._q_price = q["price"]
        tile._base_ss = base_ss
        sel_ss = _RE_TILE_BORDER.sub('border:2px solid #89b4fa;', base_ss, count=1)
        sel_ss = sel_ss.rstrip("}") + "outline:2px solid rgba(137,180,250,0.4);}"
        tile._sel_ss  = sel_ss
        # Keep Qt properties for any remaining code using .property() API
        tile.setProperty("q_price", q["price"])
        tile.setProperty("base_ss", base_ss)
        tile.setProperty("sel_ss",  sel_ss)
        tile.setProperty("tile_idx", len(self._tiles))
        self._tiles.append(tile)
        self._price_to_tile[q["price"]] = tile
        self._layout.addWidget(tile)

    def select_tile_obj(self, target_tile):
        """Highlight a specific tile object, deselect previous — O(1).
        Uses Python __dict__ attrs (_base_ss/_sel_ss) instead of Qt property()
        bridge — measurably faster on the select/deselect hot path."""
        prev = self._selected_tile
        if prev is target_tile:
            return
        if prev is not None:
            try:
                prev.setStyleSheet(getattr(prev, '_base_ss', '') or "")
            except RuntimeError:
                pass
        if target_tile is not None:
            try:
                sel_ss = getattr(target_tile, '_sel_ss', None)
                if sel_ss:
                    target_tile.setStyleSheet(sel_ss)
            except RuntimeError:
                target_tile = None
        self._selected_tile = target_tile

    def select_tile(self, price: int):
        """Highlight tile matching price — O(1) via dict index."""
        target = self._price_to_tile.get(price)
        prev = self._selected_tile
        if prev is not None and prev is not target:
            try:
                prev.setStyleSheet(getattr(prev, '_base_ss', '') or "")
            except RuntimeError:
                pass
        self._selected_tile = None
        if target is None:
            return
        try:
            sel_ss = getattr(target, '_sel_ss', None)
            if sel_ss:
                target.setStyleSheet(sel_ss)
            self._selected_tile = target
        except RuntimeError:
            pass

    # ── Shared tile event handlers (one set per tile, not per-event-type) ──
    _DRAG_THRESH = 6

    def _make_tile_handlers(self, tile):
        """Return (press, move, release, dbl) bound to *tile* without per-tile closures.
        Uses a single shared method lookup + property reads to avoid allocating
        4 new closure objects per tile."""
        _self = self
        _THRESH = self._DRAG_THRESH

        def press(ev, _t=tile):
            if ev.button() == Qt.MouseButton.LeftButton:
                _t._drag_origin = ev.position().toPoint()
                _t._dragging    = False
            elif ev.button() == Qt.MouseButton.RightButton:
                ri    = _t._q_ri
                ti    = _t._q_ti
                price = _t._q_price
                menu  = QMenu(_t)
                chp = menu.addAction(f"🔢  Изменить стоимость [{price}]")
                dl  = menu.addAction(f"🗑  Удалить вопрос [{price}]")
                chosen = menu.exec(ev.globalPosition().toPoint())
                if chosen == chp:
                    _self._rp._on_question_price_change(ri, ti, price)
                elif chosen == dl:
                    _self._rp._on_delete_question_requested(ri, ti, price)

        def move(ev, _t=tile):
            origin = getattr(_t, "_drag_origin", None)
            if origin is None or getattr(_t, "_dragging", False):
                return
            if (ev.position().toPoint() - origin).manhattanLength() >= _THRESH:
                _t._dragging = True; _t._drag_origin = None
                ri    = _t._q_ri
                ti    = _t._q_ti
                price = _t._q_price
                mime = QMimeData()
                mime.setData(TILE_MIME, QByteArray(struct.pack('>iii', ri, ti, price)))
                drag = QDrag(_t); drag.setMimeData(mime)
                drag.setPixmap(_t.grab()); drag.setHotSpot(ev.position().toPoint())
                _t.setVisible(False)
                drag.exec(Qt.DropAction.MoveAction)
                try: _t.setVisible(True)
                except RuntimeError: pass

        def release(ev, _t=tile):
            if ev.button() == Qt.MouseButton.LeftButton:
                if getattr(_t, "_drag_origin", None) is not None and \
                        not getattr(_t, "_dragging", False):
                    _t._drag_origin = None
                    _self.select_tile_obj(_t)
                    _self.question_clicked.emit(_t._q_ri, _t._q_ti, _t._q_price)

        def dbl(ev, _t=tile):
            if ev.button() == Qt.MouseButton.LeftButton:
                _self._rp._on_question_price_change(_t._q_ri, _t._q_ti, _t._q_price)

        return press, move, release, dbl

    def reorder_tile(self, price: int, new_idx: int):
        """Move tile widget to new_idx in-place — no widget teardown.

        new_idx is a tiles-list index (0-based, gap/plus/stretch not counted).
        We need to translate it to the actual layout position for insertWidget().
        """
        tile = self._price_to_tile.get(price)
        if tile is None: return
        try:
            old_idx = self._tiles.index(tile)
        except ValueError:
            return
        if old_idx == new_idx: return

        # Update _tiles list first
        self._tiles.pop(old_idx)
        clamped = max(0, min(new_idx, len(self._tiles)))
        self._tiles.insert(clamped, tile)

        # Rebuild layout order to match _tiles exactly.
        # This is safer than computing an absolute layout position because
        # the gap widget and plus/stretch items can be anywhere.
        self._layout.removeWidget(tile)
        # Find the layout position of _tiles[clamped+1] (next tile) and insert before it.
        # If clamped is at the end, append before plus_tile/stretch.
        if clamped < len(self._tiles) - 1:
            next_tile = self._tiles[clamped + 1]
            next_pos = self._layout.indexOf(next_tile)
            self._layout.insertWidget(next_pos, tile)
        else:
            # Insert before plus_tile if present, else before stretch
            if self._plus_tile is not None:
                plus_pos = self._layout.indexOf(self._plus_tile)
                self._layout.insertWidget(plus_pos, tile)
            else:
                # Before stretch (last item)
                count = self._layout.count()
                self._layout.insertWidget(max(0, count - 1), tile)

    def repopulate(self, questions: list, has_siq: bool):
        """Replace tiles with new question data — cheaper than full _rebuild_content.
        The drop-area stays at the same (r_idx, t_idx) position so _drop_area_index
        entries remain valid — no index update needed."""
        # Remove old tiles
        for tile in self._tiles:
            self._layout.removeWidget(tile)
            tile.hide(); tile.setParent(None); tile.deleteLater()
        self._tiles.clear()
        self._price_to_tile.clear()
        self._selected_tile = None
        # Remove plus tile
        if self._plus_tile is not None:
            self._layout.removeWidget(self._plus_tile)
            self._plus_tile.hide(); self._plus_tile.setParent(None)
            self._plus_tile.deleteLater(); self._plus_tile = None
        # Remove all remaining stretch/spacer items (no widget)
        for i in range(self._layout.count() - 1, -1, -1):
            item = self._layout.itemAt(i)
            if item and item.widget() is None:
                self._layout.takeAt(i)
        # Add fresh tiles
        for q in questions:
            self.add_tile(q, has_siq)
        if has_siq:
            self.add_plus_tile()

    def add_plus_tile(self):
        plus = QFrame(); plus.setFixedSize(84, 70)
        plus.setStyleSheet("QFrame{background:rgba(137,180,250,0.06);border:1px dashed #89b4fa;border-radius:6px;}")
        plus.setCursor(Qt.CursorShape.PointingHandCursor)
        plus.setToolTip("Добавить вопрос в эту тему")
        pl = QVBoxLayout(plus); pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(_lbl("＋","color:#89b4fa;font-size:26px;font-weight:300;"), 0, _AlignC)
        ri, ti = self.r_idx, self.t_idx
        plus.mousePressEvent = lambda ev, ri=ri, ti=ti: self.add_clicked.emit(ri, ti) if ev.button() == Qt.MouseButton.LeftButton else None
        self._plus_tile = plus
        self._layout.addWidget(plus)
        self._layout.addStretch()

    def _insert_idx_from_x(self, x: int) -> int:
        """Return 0-based tile insert index for given x coordinate.
        Tiles are ordered left→right so we can binary-search by center X."""
        tiles = self._tiles
        lo, hi = 0, len(tiles)
        while lo < hi:
            mid = (lo + hi) // 2
            if x < tiles[mid].x() + tiles[mid].width() // 2:
                hi = mid
            else:
                lo = mid + 1
        return lo

    def _show_gap(self, insert_idx: int):
        if self._gap_idx == insert_idx: return
        # Remove gap from layout if present
        self._layout.removeWidget(self._gap); self._gap.hide()
        self._gap_idx = insert_idx
        self._layout.insertWidget(insert_idx, self._gap)
        self._gap.show()
        self._gap_anim.stop()
        self._gap_anim.setStartValue(self._gap.minimumWidth())
        self._gap_anim.setEndValue(84)
        self._gap_anim.start()

    def _hide_gap(self):
        if self._gap_idx < 0: return
        self._gap_anim.stop()
        self._layout.removeWidget(self._gap)
        self._gap.hide(); self._gap.setMinimumWidth(0)
        self._gap_idx = -1

    # ── Drop protocol ─────────────────────────────────────────
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(TILE_MIME):
            ev.acceptProposedAction()
            self._show_gap(self._insert_idx_from_x(ev.position().toPoint().x()))

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(TILE_MIME):
            ev.acceptProposedAction()
            new_idx = self._insert_idx_from_x(ev.position().toPoint().x())
            if new_idx != self._gap_idx:   # skip layout change when gap won't move
                self._show_gap(new_idx)

    def dragLeaveEvent(self, ev):
        self._hide_gap()

    def dropEvent(self, ev):
        if not ev.mimeData().hasFormat(TILE_MIME): return
        # Use the gap's current position as the definitive insert index.
        # Recomputing via _insert_idx_from_x() here would give stale results
        # because tile geometries haven't been updated yet after _hide_gap().
        insert_idx = self._gap_idx if self._gap_idx >= 0 else len(self._tiles)
        self._hide_gap()
        raw = bytes(ev.mimeData().data(TILE_MIME))
        src_r, src_t, price = struct.unpack('>iii', raw)
        ev.acceptProposedAction()
        self._rp._move_tile_question(src_r, src_t, price, self.r_idx, self.t_idx, insert_idx)


class PackageInfoDialog(QDialog):
    """Dialog for viewing/editing package-level metadata."""
    saved = pyqtSignal()

    _LE = ("QLineEdit{background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;"
           "border-radius:4px;padding:4px 8px;font-size:12px;}"
           "QLineEdit:focus{border-color:#89b4fa;}")
    _TE = ("QTextEdit{background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;"
           "border-radius:4px;padding:4px 8px;font-size:12px;}"
           "QTextEdit:focus{border-color:#89b4fa;}")

    def __init__(self, siq, parent=None):
        super().__init__(parent)
        self.siq = siq
        self.setWindowTitle("📦  Информация о пакете")
        self.setMinimumWidth(560)
        self.setStyleSheet("QDialog{background:#181825;}")
        self._build()

    def _build(self):
        root_vl = QVBoxLayout(self)
        root_vl.setContentsMargins(16, 14, 16, 14); root_vl.setSpacing(10)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none;background:#181825;")
        inner = QWidget(); inner.setStyleSheet(_SS_TRANSPARENT)
        vl = QVBoxLayout(inner); vl.setContentsMargins(0,0,4,0); vl.setSpacing(8)
        scroll.setWidget(inner)
        root_vl.addWidget(scroll, stretch=1)

        meta = self.siq.pkg_meta

        def _row(label, widget):
            row = QWidget(); row.setStyleSheet(_SS_TRANSPARENT)
            rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(8)
            lbl = QLabel(label); lbl.setFixedWidth(110)
            lbl.setStyleSheet("color:#a6adc8;font-size:11px;")
            rl.addWidget(lbl); rl.addWidget(widget, stretch=1)
            return row

        def _le(val=''):
            le = QLineEdit(val); le.setStyleSheet(self._LE); return le

        vl.addWidget(_lbl("Основная информация", "color:#cdd6f4;font-size:12px;font-weight:700;"))

        self._name_le    = _le(self.siq.name)
        self._restr_le   = _le(meta.get('restriction',''))
        self._date_le    = _le(meta.get('date',''))
        self._contact_le = _le(meta.get('contactUri',''))
        self._diff_le    = _le(meta.get('difficulty',''))
        self._logo_le    = _le(meta.get('logo',''))
        self._lang_le    = _le(meta.get('language','ru-RU'))

        for label, widget in [
            ("Название", self._name_le),
            ("Ограничение", self._restr_le),
            ("Дата", self._date_le),
            ("Контакт (URI)", self._contact_le),
            ("Сложность (0-10)", self._diff_le),
            ("Логотип (файл)", self._logo_le),
            ("Язык", self._lang_le),
        ]:
            vl.addWidget(_row(label, widget))

        vl.addWidget(_lbl("Авторы", "color:#cdd6f4;font-size:12px;font-weight:700;margin-top:4px;"))
        self._authors_te = QTextEdit("\n".join(self.siq.pkg_authors))
        self._authors_te.setFixedHeight(60)
        self._authors_te.setPlaceholderText("По одному автору на строку...")
        self._authors_te.setStyleSheet(self._TE)
        vl.addWidget(self._authors_te)

        vl.addWidget(_lbl("Теги", "color:#cdd6f4;font-size:12px;font-weight:700;"))
        self._tags_te = QTextEdit("\n".join(self.siq.pkg_tags))
        self._tags_te.setFixedHeight(80)
        self._tags_te.setPlaceholderText("По одному тегу на строку...")
        self._tags_te.setStyleSheet(self._TE)
        vl.addWidget(self._tags_te)

        vl.addWidget(_lbl("Описание пакета (комментарии)", "color:#cdd6f4;font-size:12px;font-weight:700;"))
        self._comments_te = QTextEdit(self.siq.pkg_comments)
        self._comments_te.setFixedHeight(90)
        self._comments_te.setPlaceholderText("Описание пакета, рекомендации, инструкции...")
        self._comments_te.setStyleSheet(self._TE)
        vl.addWidget(self._comments_te)

        # ── Buttons ──
        bot = QHBoxLayout(); bot.addStretch()
        cancel_btn = AnimatedButton("Отмена"); cancel_btn.clicked.connect(self.reject)
        save_btn   = AnimatedButton("💾  Сохранить"); save_btn.setObjectName(_ON_BTN_ANALYZE)
        save_btn.clicked.connect(self._save)
        bot.addWidget(cancel_btn); bot.addWidget(save_btn)
        root_vl.addLayout(bot)

    def _save(self):
        meta = {
            'name':       self._name_le.text().strip(),
            'version':    '5',
            'restriction':self._restr_le.text().strip(),
            'date':       self._date_le.text().strip(),
            'contactUri': self._contact_le.text().strip(),
            'difficulty': self._diff_le.text().strip(),
            'logo':       self._logo_le.text().strip(),
            'language':   self._lang_le.text().strip(),
        }
        tags    = [t.strip() for t in self._tags_te.toPlainText().splitlines() if t.strip()]
        authors = [a.strip() for a in self._authors_te.toPlainText().splitlines() if a.strip()]
        comments = self._comments_te.toPlainText().strip()
        ok = self.siq.save_pkg_info(meta, tags, authors, comments)
        if ok:
            self.saved.emit(); self.accept()
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось сохранить информацию о пакете.")

__all__ = [
    'PackageInfoDialog',
    '_TileDropArea',
]
