"""Top-level pages (EmptyPage) and the MainWindow."""

from .qt import *
from .constants import *
from .util import *
from .stats import *
from .persistence import *
from .media import *
from .siq_package import *
from .widgets_common import *
from .widgets_editors import *
from .result_page import *
from .sidebar import *
from . import auto_stats

class EmptyPage(QWidget):
    """Welcome screen — drag a .siq file here as the primary action."""
    siq_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#181825;")
        self.setAcceptDrops(True)
        self._drag_over = False
        lay = QVBoxLayout(self)
        lay.setAlignment(_AlignC)
        lay.setSpacing(16)

        # Drop zone frame
        self._frame = QFrame()
        self._frame.setObjectName("drop_zone")
        self._frame.setFixedSize(480, 300)
        self._frame.setStyleSheet(_SS_DROP_ZONE_LG)
        frame_lay = QVBoxLayout(self._frame)
        frame_lay.setAlignment(_AlignC)
        frame_lay.setSpacing(12)

        icon_lbl = QLabel("📦")
        icon_lbl.setAlignment(_AlignC)
        icon_lbl.setStyleSheet("font-size:56px;background:transparent;border:none;")
        frame_lay.addWidget(icon_lbl)

        frame_lay.addWidget(_lbl(
            "Перетащите .siq файл сюда",
            "color:#cdd6f4;font-size:18px;font-weight:700;background:transparent;"
            "border:none;"))

        frame_lay.addWidget(_lbl(
            "или",
            "color:#585b70;font-size:13px;background:transparent;border:none;"))

        open_btn = AnimatedButton("📂  Открыть .siq…")
        open_btn.setObjectName("btn_paste")
        open_btn.setFixedHeight(38)
        open_btn.clicked.connect(self._open_dialog)
        frame_lay.addWidget(open_btn)

        lay.addWidget(self._frame)
        lay.addWidget(_lbl(
            "Статистика подтягивается автоматически с SIStatistics при открытии пакета",
            "color:#585b70;font-size:11px;"))

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть .siq файл", "", "SIGame Package (*.siq);;All (*)")
        if path:
            self.siq_dropped.emit(path)

    def dragEnterEvent(self, e):
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        if any(os.path.splitext(u.toLocalFile())[1].lower() == ".siq" for u in urls):
            e.acceptProposedAction()
            self._drag_over = True
            self._frame.setStyleSheet(
                "QFrame#drop_zone{background:rgba(137,180,250,0.08);"
                "border:2px dashed #89b4fa;border-radius:16px;}")

    def dragLeaveEvent(self, e):
        self._drag_over = False
        self._frame.setStyleSheet(_SS_DROP_ZONE_LG)

    def dropEvent(self, e):
        self._drag_over = False
        self._frame.setStyleSheet(_SS_DROP_ZONE_LG)
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if os.path.splitext(p)[1].lower() == '.siq':
                e.acceptProposedAction()
                self.siq_dropped.emit(p)
                return


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Suppress any native window creation flash on Windows:
        # keep the window fully hidden until main() calls showMaximized().
        self.hide()
        _get_ui_bridge()
        self.setWindowTitle("SIGame Statistics + SiQ Viewer")
        self.setMinimumSize(980, 620)
        try:
            screen = QApplication.primaryScreen().availableGeometry()
            self.resize(min(screen.width(), 1440), min(screen.height(), 900))
        except Exception:
            self.resize(1440, 860)
        self.datasets: list[dict] = []
        self._build()
        self._load_saved()

    def showEvent(self, ev):
        """Cache the MainWindow reference on first show — avoids repeated .window() traversal."""
        super().showEvent(ev)
        if not hasattr(self, '_mw') or self._mw is None:
            self._mw = _find_mw(self)  # type: ignore
        # Window is shown by main() via showMaximized()

    def _build(self):
        root=QWidget(); root.setStyleSheet("background:#181825;"); self.setCentralWidget(root)
        v=QVBoxLayout(root); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        # App-level event filter (global shortcuts: Ctrl+S/F, WASD, click-outside)
        # is installed/removed by the SI-HYX host wrapper only while the SiQuester
        # tab is visible — so its hotkeys don't fire on the other SI-HYX tabs.
        # (Standalone use: see siquester.app, which installs it directly.)
        tb=QFrame(); tb.setFixedHeight(46); tb.setStyleSheet(_SS_TOPBAR)
        tbl=QHBoxLayout(tb); tbl.setContentsMargins(8,0,16,0); tbl.setSpacing(6)
        # Search & Media buttons on the LEFT (replace the old title)
        for obj,label,slot in [("btn_search","🔍 Поиск",self._toggle_search),
                                ("btn_media_search","🎬 Медиа",self._toggle_media_search)]:
            btn=AnimatedButton(label); btn.setObjectName(obj); btn.clicked.connect(slot); tbl.addWidget(btn)
        self.lbl_filename = QLabel("")
        self.lbl_filename.setStyleSheet(
            "color:#a6adc8;font-size:12px;padding-left:12px;padding-right:16px;")
        self.lbl_filename.setSizePolicy(_Expand, _Pref)
        self.lbl_filename.setMinimumWidth(0)
        self.lbl_filename.setTextFormat(Qt.TextFormat.PlainText)
        tbl.addWidget(self.lbl_filename, stretch=1)

        self.lbl_filename._full_text = ""

        def _apply_elision(lbl=self.lbl_filename):
            text = lbl._full_text
            if not text:
                lbl.setText(""); return
            w = lbl.width()
            if w <= 4:
                QTimer.singleShot(0, lambda: _apply_elision(lbl)); return
            fm = lbl.fontMetrics()
            lbl.setText(fm.elidedText(text, Qt.TextElideMode.ElideMiddle, w - 4))

        _orig_lbl_re = self.lbl_filename.resizeEvent
        def _lbl_resize(ev, _orig=_orig_lbl_re):
            _orig(ev); _apply_elision()
        self.lbl_filename.resizeEvent = _lbl_resize

        def _set_filename_text(text, lbl=self.lbl_filename):
            lbl._full_text = text
            lbl.setToolTip(text)
            _apply_elision(lbl)
        self._set_filename_text = _set_filename_text

        # ── Floating save notification (top-center, hidden by default) ──────
        self._save_notif = QLabel("✅  Файл сохранён")
        self._save_notif.setStyleSheet(
            "background:rgba(166,227,161,0.92);color:#181825;font-size:13px;font-weight:700;"
            "border-radius:8px;padding:8px 24px;")
        self._save_notif.setAlignment(_AlignC)
        self._save_notif.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._save_notif.hide()
        self._save_notif.setParent(self)   # reparented after window is built
        self._save_notif_timer = QTimer(self)
        self._save_notif_timer.setSingleShot(True)
        self._save_notif_timer.timeout.connect(self._save_notif.hide)
        self.lbl_info=QLabel(""); self.lbl_info.setStyleSheet("color:#585b70;font-size:12px;"); tbl.addWidget(self.lbl_info)
        for obj,label,slot in [("btn_restart","↺ Перезапуск",self._restart)]:
            btn=AnimatedButton(label); btn.setObjectName(obj); btn.clicked.connect(slot); tbl.addWidget(btn)
        v.addWidget(tb)
        body=QWidget(); body.setStyleSheet("background:#181825;")
        bl=QHBoxLayout(body); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(0); v.addWidget(body,stretch=1)
        self.sidebar=Sidebar()
        self.sidebar.setMinimumWidth(0)
        self.sidebar.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.sidebar.setAutoFillBackground(True)  # prevent content bleeding through during animation
        self.sidebar.item_selected.connect(self._show_ds)
        self.sidebar.delete_requested.connect(self._delete_ds)
        self.sidebar.reorder_requested.connect(self._on_reorder)
        self.sidebar.move_to_tab.connect(self._move_to_tab)
        self.sidebar.rename_requested.connect(self._rename_pkg)
        bl.addWidget(self.sidebar)

        # ── Collapse button ──────────────────────────────────────
        settings = load_settings()
        self._sidebar_visible = settings.get("sidebar_visible", True)
        self._sidebar_anim = QPropertyAnimation(self.sidebar, b"maximumWidth")
        self._sidebar_anim.setDuration(130)
        self._sidebar_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Apply saved state immediately (no animation on startup)
        if not self._sidebar_visible:
            self.sidebar.setFixedWidth(0)

        # ── Stack lives directly after the sidebar, no separator column ──
        self.stack=QStackedWidget(); self.stack.setStyleSheet("background:#181825;")
        self.stack.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        bl.addWidget(self.stack,stretch=1)

        # Floating collapse button — parented to body so it sits on top of the stack
        self._collapse_btn = QPushButton("▶" if not self._sidebar_visible else "◀")
        self._collapse_btn.setParent(body)
        self._collapse_btn.setFixedSize(18, 52)
        self._collapse_btn.setStyleSheet(
            "QPushButton{background:rgba(36,39,58,0.90);color:#89b4fa;"
            "border:1px solid #45475a;border-radius:4px;"
            "font-size:10px;padding:0;}"
            "QPushButton:hover{background:#313244;color:#cdd6f4;}")
        self._collapse_btn.setToolTip(
            "Развернуть боковую панель" if not self._sidebar_visible else "Свернуть боковую панель")
        self._collapse_btn.clicked.connect(self._toggle_sidebar)
        self._collapse_btn.raise_()
        # Position the button once body is shown; also re-position on resize
        body.installEventFilter(self)
        self.empty_page=EmptyPage()
        self.empty_page.siq_dropped.connect(self._open_siq_file)
        self.stack.addWidget(self.empty_page)
        self.stack.setCurrentIndex(0); self.setAcceptDrops(True)

        # ── Floating search panel (Ctrl+F) ────────────────────────
        self._search_panel = self._build_search_panel()
        self._search_panel.setParent(self)
        self._search_panel.hide()

        # ── Floating media search panel ───────────────────────────
        self._media_search_panel = self._build_media_search_panel()
        self._media_search_panel.setParent(self)
        self._media_search_panel.hide()

    # ── Search panel ──────────────────────────────────────────
    def _build_search_panel(self) -> QFrame:
        """Build the floating Ctrl+F search overlay."""
        panel = QFrame()
        panel.setStyleSheet(_SS_PANEL_BRD2)
        pl = QVBoxLayout(panel); pl.setContentsMargins(12, 10, 12, 10); pl.setSpacing(8)

        hdr = QHBoxLayout(); hdr.setSpacing(8)
        hdr.addWidget(_lbl("🔍  Поиск по всем пакам", "color:#cdd6f4;font-size:13px;font-weight:700;"))
        hdr.addStretch()
        close_btn = QPushButton("✕"); close_btn.setObjectName(_ON_BTN_DEL)
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self._hide_search)
        hdr.addWidget(close_btn)
        pl.addLayout(hdr)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Введите текст для поиска в вопросах, ответах, темах…")
        self._search_edit.setStyleSheet(_SS_INPUT_LARGE)
        self._search_edit.textChanged.connect(self._on_search_text_changed)
        self._search_edit.returnPressed.connect(self._run_search)
        pl.addWidget(self._search_edit)

        opt_row = QHBoxLayout(); opt_row.setSpacing(12)
        self._search_cb_q   = QCheckBox("Вопросы");  self._search_cb_q.setChecked(True)
        self._search_cb_ans = QCheckBox("Ответы");   self._search_cb_ans.setChecked(True)
        self._search_cb_th  = QCheckBox("Темы");     self._search_cb_th.setChecked(True)
        for cb in (self._search_cb_q, self._search_cb_ans, self._search_cb_th):
            cb.setStyleSheet("color:#a6adc8;font-size:11px;")
            cb.stateChanged.connect(self._run_search)
            opt_row.addWidget(cb)
        opt_row.addStretch()
        self._search_count_lbl = _lbl("", "color:#585b70;font-size:11px;")
        opt_row.addWidget(self._search_count_lbl)
        pl.addLayout(opt_row)

        self._search_results = QListWidget()
        self._search_results.setWordWrap(True)
        self._search_results.setStyleSheet(
            "QListWidget{background:#181825;border:1px solid #313244;border-radius:6px;"
            "color:#cdd6f4;font-size:12px;outline:none;}"
            "QListWidget::item{padding:5px 8px;border-radius:4px;}"
            "QListWidget::item:hover{background:#313244;}"
            "QListWidget::item:selected{background:#313244;}")
        pl.addWidget(self._search_results, stretch=1)
        self._search_results.itemDoubleClicked.connect(self._search_result_activated)
        self._search_results.itemActivated.connect(self._search_result_activated)

        pl.addWidget(_lbl("Enter / двойной клик — перейти к вопросу", "color:#585b70;font-size:10px;"))
        return panel

    def _toggle_search(self):
        if self._search_panel.isVisible():
            self._hide_search()
        else:
            self._media_search_panel.hide()
            self._show_search()

    def _toggle_media_search(self):
        if self._media_search_panel.isVisible():
            self._hide_media_search()
        else:
            self._search_panel.hide()
            self._show_media_search()

    def _show_search(self):
        p = self._search_panel
        self._reposition_panels()
        p.raise_(); p.show()
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    def _hide_search(self):
        self._search_panel.hide()

    def _show_media_search(self):
        p = self._media_search_panel
        self._reposition_panels()
        p.raise_(); p.show()
        self._media_search_edit.setFocus()
        self._run_media_search()

    def _hide_media_search(self):
        self._media_search_panel.hide()

    def _reposition_panels(self):
        """Position search panels: left-aligned, starting just below toolbar, down to bottom."""
        y = 46
        panel_h = self.height() - y
        panel_w = 580
        for p in (self._search_panel, self._media_search_panel):
            p.setFixedWidth(panel_w)
            p.setFixedHeight(panel_h)
        self._search_panel.move(0, y)
        self._media_search_panel.move(0, y)

    def _build_media_search_panel(self) -> QFrame:
        """Floating panel: lists all media files in the currently shown SIQ pack."""
        panel = QFrame()
        panel.setStyleSheet(_SS_PANEL_BRD2)
        pl = QVBoxLayout(panel); pl.setContentsMargins(12, 10, 12, 10); pl.setSpacing(8)

        # ── Header ────────────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(8)
        hdr.addWidget(_lbl("🎬  Медиафайлы пака", "color:#cdd6f4;font-size:13px;font-weight:700;"))
        hdr.addStretch()
        close_btn = QPushButton("✕"); close_btn.setObjectName(_ON_BTN_DEL)
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self._hide_media_search)
        hdr.addWidget(close_btn)
        pl.addLayout(hdr)

        # ── Search box ────────────────────────────────────────
        self._media_search_edit = QLineEdit()
        self._media_search_edit.setPlaceholderText("Фильтр по имени файла…")
        self._media_search_edit.setStyleSheet(_SS_INPUT_LARGE)
        self._media_search_edit.textChanged.connect(
            lambda: QTimer.singleShot(100, self._run_media_search))
        pl.addWidget(self._media_search_edit)

        # ── Filters row ───────────────────────────────────────
        flt_row = QHBoxLayout(); flt_row.setSpacing(10)
        flt_row.addWidget(_lbl("Тип:", "color:#a6adc8;font-size:11px;"))
        self._mf_cb_img   = QCheckBox("Картинки");  self._mf_cb_img.setChecked(True)
        self._mf_cb_audio = QCheckBox("Аудио");     self._mf_cb_audio.setChecked(True)
        self._mf_cb_video = QCheckBox("Видео");     self._mf_cb_video.setChecked(True)
        for cb in (self._mf_cb_img, self._mf_cb_audio, self._mf_cb_video):
            cb.setStyleSheet("color:#a6adc8;font-size:11px;")
            cb.stateChanged.connect(self._run_media_search)
            flt_row.addWidget(cb)
        flt_row.addSpacing(8)
        flt_row.addWidget(_lbl("Сортировка:", "color:#a6adc8;font-size:11px;"))
        self._mf_sort_cb = QComboBox()
        self._mf_sort_cb.addItems(["По умолчанию", "Размер ↑", "Размер ↓",
                                    "Длительность ↑", "Длительность ↓", "Имя ↑", "Имя ↓"])
        self._mf_sort_cb.setStyleSheet(
            "QComboBox{background:#313244;color:#cdd6f4;border:1px solid #45475a;"
            "border-radius:4px;padding:2px 6px;font-size:11px;}"
            "QComboBox QAbstractItemView{background:#1e1e2e;color:#cdd6f4;}")
        self._mf_sort_cb.currentIndexChanged.connect(self._run_media_search)
        flt_row.addWidget(self._mf_sort_cb)
        flt_row.addStretch()
        self._media_count_lbl = _lbl("", "color:#585b70;font-size:11px;")
        flt_row.addWidget(self._media_count_lbl)
        pl.addLayout(flt_row)

        # ── Results scroll area with thumbnails ───────────────
        self._media_scroll = QScrollArea()
        self._media_scroll.setWidgetResizable(True)
        self._media_scroll.setStyleSheet("border:1px solid #313244;border-radius:6px;background:#181825;")
        self._media_scroll.setMaximumHeight(16777215)
        self._media_results_widget = QWidget(); self._media_results_widget.setStyleSheet("background:#181825;")
        self._media_results_vl = QVBoxLayout(self._media_results_widget)
        self._media_results_vl.setContentsMargins(4,4,4,4); self._media_results_vl.setSpacing(2)
        self._media_results_vl.addStretch()
        self._media_scroll.setWidget(self._media_results_widget)
        pl.addWidget(self._media_scroll, stretch=1)
        pl.addWidget(_lbl("Двойной клик — перейти к вопросу с этим файлом",
                          "color:#585b70;font-size:10px;"))
        # Keep a dummy QListWidget reference for backwards compat (not shown)
        self._media_results = QListWidget(); self._media_results.hide()
        return panel

    def _run_media_search(self):
        """Collect all media items from current pack, filter by type/name, then sort."""
        # Clear old rows (keep stretch at end)
        vl = self._media_results_vl
        while vl.count() > 1:
            it = vl.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()

        idx = self.sidebar.current_real_idx()
        if not (0 <= idx < len(self.datasets)):
            self._media_count_lbl.setText("нет пака"); return
        w = self.datasets[idx].get("widget")
        siq = w._siq if w and hasattr(w, "_siq") else None
        if not siq:
            self._media_count_lbl.setText("нет .siq"); return

        query  = self._media_search_edit.text().strip().lower()
        do_img = self._mf_cb_img.isChecked()
        do_aud = self._mf_cb_audio.isChecked()
        do_vid = self._mf_cb_video.isChecked()
        sort_i = self._mf_sort_cb.currentIndex()

        results = []
        for ri, rd in enumerate(siq.rounds):
            for ti, th in enumerate(rd["themes"]):
                th_name = th.get("name", "")
                for q in th["questions"]:
                    for it in q.get("items", []):
                        if not it.get("is_ref"): continue
                        itype = it.get("type","")
                        if itype == "image" and not do_img: continue
                        if itype == "audio" and not do_aud: continue
                        if itype == "video" and not do_vid: continue
                        if itype not in ("image","audio","video"): continue
                        fname = it.get("text","")
                        base = _unquote(fname.split("/")[-1])
                        if query and query not in base.lower(): continue
                        path = siq.extract_media(fname)
                        if not path: continue
                        try: sz = os.path.getsize(path)
                        except: sz = 0
                        dur_sec = it.get("dur", 0.0)
                        results.append((itype, base, path, sz, dur_sec, th_name, q["price"], ri, ti))

        # Sort
        if sort_i == 1: results.sort(key=lambda x: x[3])
        elif sort_i == 2: results.sort(key=lambda x: x[3], reverse=True)
        elif sort_i == 3: results.sort(key=lambda x: x[4])
        elif sort_i == 4: results.sort(key=lambda x: x[4], reverse=True)
        elif sort_i == 5: results.sort(key=lambda x: x[1].lower())
        elif sort_i == 6: results.sort(key=lambda x: x[1].lower(), reverse=True)

        self._media_count_lbl.setText(f"{len(results)} файлов")

        for itype, base, path, sz, dur_sec, th_name, price, ri, ti in results:
            row_w = QWidget()
            row_w.setCursor(Qt.CursorShape.PointingHandCursor)
            row_w.setStyleSheet("QWidget{background:#1e1e2e;border-radius:5px;}"
                                "QWidget:hover{background:#313244;}")
            row_l = QHBoxLayout(row_w); row_l.setContentsMargins(6,4,6,4); row_l.setSpacing(8)

            # ── Thumbnail (48×36 for image/video, waveform icon for audio) ──
            thumb_lbl = QLabel()
            thumb_lbl.setFixedSize(64, 48)
            thumb_lbl.setAlignment(_AlignC)
            thumb_lbl.setStyleSheet("background:#181825;border-radius:3px;color:#585b70;font-size:18px;")
            if itype == "image":
                try:
                    reader = QImageReader(path); reader.setAutoTransform(True)
                    img = reader.read()
                    if not img.isNull():
                        pm = QPixmap.fromImage(img).scaled(
                            64, 48, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
                        thumb_lbl.setPixmap(pm)
                    else:
                        thumb_lbl.setText("🖼")
                except Exception:
                    thumb_lbl.setText("🖼")
            elif itype == "video":
                # Try to get first frame via QImageReader (works for some formats)
                thumb_lbl.setText("🎬")
                try:
                    reader = QImageReader(path); reader.setAutoTransform(True)
                    img = reader.read()
                    if not img.isNull():
                        pm = QPixmap.fromImage(img).scaled(
                            64, 48, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
                        thumb_lbl.setPixmap(pm)
                except Exception:
                    pass
            else:
                thumb_lbl.setText("🎵")
            row_l.addWidget(thumb_lbl)

            # ── Info ──────────────────────────────────────────────
            info_col = QVBoxLayout(); info_col.setSpacing(2)
            sz_str = (f"{sz/1_048_576:.1f} МБ" if sz >= 1_048_576
                      else f"{sz//1024} КБ" if sz > 0 else "")
            dur_str = fmt_dur(dur_sec) if dur_sec > 0 else ""
            meta = "  ·  ".join(filter(None, [sz_str, dur_str]))

            name_lbl = QLabel(base)
            name_lbl.setWordWrap(True)
            name_lbl.setStyleSheet("color:#cdd6f4;font-size:11px;font-weight:600;background:transparent;")
            name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            info_col.addWidget(name_lbl)

            sub_lbl = QLabel(f"{th_name}  [{price}]" + (f"   {meta}" if meta else ""))
            sub_lbl.setStyleSheet(_SS_LABEL_DIM)
            info_col.addWidget(sub_lbl)
            row_l.addLayout(info_col, stretch=1)

            # ── Double-click to navigate ───────────────────────────
            _nav_data = (idx, ri, ti, price)
            def _dbl(ev, nd=_nav_data, mw=self):
                if ev.type() == ev.Type.MouseButtonDblClick:
                    mw._media_result_activated_data(nd)
            row_w.mouseDoubleClickEvent = _dbl

            vl.insertWidget(vl.count() - 1, row_w)   # before the stretch

    def _media_result_activated_data(self, data):
        ds_idx, ri, ti, price = data
        if not (0 <= ds_idx < len(self.datasets)): return
        self.sidebar.select_by_real(ds_idx)
        self._show_ds(ds_idx)
        w = self.datasets[ds_idx]["widget"]
        QTimer.singleShot(80, lambda ri=ri, ti=ti, p=price:
                          w._on_question_clicked(ri, ti, p))

    def _on_search_text_changed(self):
        QTimer.singleShot(120, self._run_search)

    def _run_search(self):
        query = self._search_edit.text().strip().lower()
        self._search_results.clear()
        if not query:
            self._search_count_lbl.setText(""); return

        do_q   = self._search_cb_q.isChecked()
        do_ans = self._search_cb_ans.isChecked()
        do_th  = self._search_cb_th.isChecked()
        results = []

        for ds_idx, ds in enumerate(self.datasets):
            pkg_name = ds.get("pkg_name", "?")
            w = ds.get("widget")
            siq = w._siq if w and hasattr(w, "_siq") else None
            rounds = siq.rounds if siq else []

            for ri, rd in enumerate(rounds):
                rnd_name = rd.get("name", f"Раунд {ri+1}")
                for ti, th in enumerate(rd["themes"]):
                    th_name = th.get("name", "")
                    if do_th and query in th_name.lower():
                        th_all_t = [q.get("tries",0) for q in th["questions"]]
                        th_all_r = [q.get("right",0) for q in th["questions"]]
                        th_avg_t = sum(th_all_t)/len(th_all_t) if th_all_t else 0
                        th_avg_r = sum(th_all_r)/len(th_all_r) if th_all_r else 0
                        th_stats = f"  🟡{th_avg_t:.0f}% 🟢{th_avg_r:.0f}%" if th_all_t else ""
                        results.append((
                            f"📚  {pkg_name}  ›  {rnd_name}  ›  {th_name}{th_stats}",
                            ds_idx, ri, ti, -1))
                    for q in th["questions"]:
                        items = q.get("items", [])
                        price = q["price"]
                        q_hit = False
                        if do_q:
                            q_texts = " ".join(
                                it.get("text","") for it in items
                                if it.get("param") in ("question","background")
                                and it.get("type") == "text" and not it.get("is_ref"))
                            q_hit = query in q_texts.lower()
                        ans_hit = False
                        if do_ans:
                            all_ans = " ".join(q.get("answers",[]) + q.get("wrong_answers",[]))
                            ans_par = " ".join(it.get("text","") for it in items
                                               if it.get("param") == "answer"
                                               and it.get("type") == "text"
                                               and not it.get("is_ref"))
                            ans_hit = query in (all_ans + " " + ans_par).lower()
                        if q_hit or ans_hit:
                            tag_icon = "❓" if q_hit else "✅"
                            # Build preview: show matched answer text if ans_hit, else question text
                            if ans_hit and not q_hit:
                                # Find the specific matching answer
                                all_ans_list = q.get("answers", []) + q.get("wrong_answers", [])
                                ans_param_texts = [it.get("text","").strip() for it in items
                                                   if it.get("param") == "answer"
                                                   and it.get("type") == "text"
                                                   and not it.get("is_ref")
                                                   and it.get("text","").strip()]
                                all_ans_list += ans_param_texts
                                matched_ans = next((a for a in all_ans_list if query in a.lower()), "")
                                preview = matched_ans[:80] + ("…" if len(matched_ans) > 80 else "")
                            else:
                                preview = " / ".join(
                                    it.get("text","").strip() for it in items
                                    if it.get("param") in ("question","background")
                                    and it.get("type") == "text" and not it.get("is_ref")
                                    and it.get("text","").strip())
                                if len(preview) > 80: preview = preview[:80] + "…"

                            # Build stats suffix
                            pct_t = q.get("tries", 0)
                            pct_r = q.get("right", 0)
                            stats_str = f"  🟡{pct_t}% 🟢{pct_r}%" if (pct_t or pct_r) else ""

                            # Format: pkg › theme · [price]  preview  stats
                            line = f"{tag_icon}  {pkg_name}  ›  {th_name}  ·  [{price}]{stats_str}"
                            if preview:
                                line += f"   {preview}"
                            results.append((line, ds_idx, ri, ti, price))

        MAX = 250
        total = len(results)
        self._search_count_lbl.setText(
            f"{total} совпад." if total <= MAX else f"{MAX}+ совпад.")
        for text, ds_idx, ri, ti, price in results[:MAX]:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, (ds_idx, ri, ti, price))
            self._search_results.addItem(item)

    def _search_result_activated(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
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
                    scroll_area = rp._scroll
                    tile_global = drop_area.mapToGlobal(drop_area.rect().topLeft())
                    content_local = rp._content_widget.mapFromGlobal(tile_global)
                    rp._scroll.verticalScrollBar().setValue(
                        max(0, content_local.y() - 80))
                except Exception:
                    pass
            QTimer.singleShot(80, _nav)
        # Close the search panel after navigating
        self._hide_search()

    def eventFilter(self, obj, event):
        # ── Close panels on click outside ─────────────────────────
        if event.type() == QEvent.Type.MouseButtonPress:
            if hasattr(self, '_search_panel'):
                try:
                    gp = event.globalPosition().toPoint()
                    for panel in (self._search_panel, self._media_search_panel):
                        if not panel.isVisible(): continue
                        local = panel.mapFromGlobal(gp)
                        if panel.rect().contains(local): continue
                        # Don't hide if click is on a toolbar button (toggle handles it)
                        tb_local = self.menuWidget().mapFromGlobal(gp) if self.menuWidget() else None
                        # Find the toolbar frame (first child QFrame of central widget)
                        click_on_toolbar = False
                        for tb in self.centralWidget().findChildren(QFrame):
                            if tb.height() == 46:  # our toolbar height
                                tl = tb.mapFromGlobal(gp)
                                if tb.rect().contains(tl):
                                    click_on_toolbar = True; break
                        if not click_on_toolbar:
                            panel.hide()
                except Exception:
                    pass
        # ── Global keyboard shortcuts (work even inside QTextEdit) ─
        if event.type() == QEvent.Type.KeyPress:
            fw = QApplication.focusWidget()
            # Let text-editing widgets handle their OWN undo/redo
            is_editable = False
            if fw:
                if isinstance(fw, QTextEdit):
                    is_editable = bool(fw.textInteractionFlags() &
                                       Qt.TextInteractionFlag.TextEditable)
                elif isinstance(fw, QLineEdit):
                    is_editable = not fw.isReadOnly()
            ctrl = event.modifiers() == Qt.KeyboardModifier.ControlModifier
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
            if ctrl and (event.key() == Qt.Key.Key_S or vk == 0x53) and not is_editable:
                idx = self.sidebar.current_real_idx()
                if 0 <= idx < len(self.datasets):
                    w = self.datasets[idx]["widget"]
                    if hasattr(w, '_save_siq_inplace'):
                        w._save_siq_inplace()
                return True
            if ctrl and (event.key() == Qt.Key.Key_Z or vk == 0x5A) and not is_editable:
                idx = self.sidebar.current_real_idx()
                if 0 <= idx < len(self.datasets):
                    self.datasets[idx]["widget"].do_undo()
                return True
            if ctrl and (event.key() == Qt.Key.Key_Y or vk == 0x59) and not is_editable:
                idx = self.sidebar.current_real_idx()
                if 0 <= idx < len(self.datasets):
                    self.datasets[idx]["widget"].do_redo()
                return True
            if ctrl and (event.key() == Qt.Key.Key_O or vk == 0x4F) and not is_editable:
                path, _ = QFileDialog.getOpenFileName(
                    self, "Открыть .siq", "", "SIGame Package (*.siq);;All (*)")
                if path: self._open_siq_file(path)
                return True
            if ctrl and (event.key() == Qt.Key.Key_F or vk == 0x46):
                if self._search_panel.isVisible():
                    self._hide_search()
                else:
                    self._show_search()
                return True
            if event.key() == Qt.Key.Key_Escape:
                if self._search_panel.isVisible():
                    self._hide_search(); return True
            if event.key() == Qt.Key.Key_F5:
                idx = self.sidebar.current_real_idx()
                if 0 <= idx < len(self.datasets):
                    w = self.datasets[idx]["widget"]
                    if hasattr(w, '_save_siq_inplace'):
                        w._save_siq_inplace()
                return True
            # ── WASD tile navigation ───────────────────────────────
            key_int = int(event.key())
            if key_int in _WASD_MAP and not is_editable and not ctrl:
                idx = self.sidebar.current_real_idx()
                if 0 <= idx < len(self.datasets):
                    self.datasets[idx]["widget"]._wasd_navigate(*_WASD_MAP[key_int])
                return True
        # ── Body resize → reposition collapse button ──────────────
        if hasattr(self, '_collapse_btn'):
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self._reposition_collapse_btn()
        return super().eventFilter(obj, event)

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
        except: pass
        try: self._sidebar_anim.finished.disconnect()
        except: pass
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
        save_settings({"sidebar_visible": self._sidebar_visible})

    def _restart(self): QApplication.quit(); os.execl(sys.executable,sys.executable,*sys.argv)

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
        self._pending_saved = load_datasets()
        self._load_idx = 0
        if not self._pending_saved:
            self.stack.setCurrentWidget(self.empty_page)
            return
        # Таймер — ДОЧЕРНИЙ объект окна: если окно уничтожат во время загрузки
        # (вкладку выключили в настройках), таймер уничтожится вместе с ним и
        # гарантированно не дёрнет метод на уже удалённых виджетах.
        self._load_timer = QTimer(self)
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
            if siq_path and os.path.exists(siq_path):
                try:
                    siq = SiqPackage(siq_path)
                    self.datasets[real_idx]["total_duration_sec"] = siq.total_duration
                    self.datasets[real_idx]["widget"].attach_siq(siq)
                    # Пакеты, уже сохранённые ранее, тоже обновляют статистику при
                    # каждом запуске — не только свежеоткрытые (см. _open_siq_file).
                    self._auto_fetch_stats(real_idx, siq.name, list(siq.pkg_authors), siq.rounds)
                except Exception as e:
                    _logger.warning(f"[siq reload] {e}")
            self.sidebar.rebuild(self.datasets)
            self._update_info()
            self.sidebar.select_by_real(prev if prev >= 0 else 0)
        except Exception as e:
            _logger.warning(f"[load_saved step] {e}")
        # Следующий пакет — на следующем тике цикла событий (GUI остаётся живым).
        self._load_timer.start(0)

    def _add_dataset(self, ds, save=True, _batch=False):
        w = ResultPage(ds, parent=self)
        self.stack.addWidget(w)
        self.datasets.append({**ds, "widget": w})
        if not _batch:
            self.sidebar.rebuild(self.datasets)
            self._update_info()
        if save:
            save_datasets(self.datasets)

    def _show_ds(self,real_idx):
        if 0<=real_idx<len(self.datasets):
            self.stack.setCurrentWidget(self.datasets[real_idx]["widget"])
            siq_path = self.datasets[real_idx].get("siq_path", "")
            if siq_path and os.path.exists(siq_path):
                try:
                    mtime = os.path.getmtime(siq_path)
                    dt = _dt.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")
                    self._set_filename_text(
                        f"📂 {os.path.dirname(siq_path)}{os.sep}  "
                        f"📄 {os.path.basename(siq_path)}  · сохранён {dt}")
                except Exception:
                    self._set_filename_text(
                        f"📂 {os.path.dirname(siq_path)}{os.sep}  "
                        f"📄 {os.path.basename(siq_path)}")
            else:
                self.lbl_filename.setText("")
                self.lbl_filename.setToolTip("")
            # Refresh media search if visible
            if hasattr(self, '_media_search_panel') and self._media_search_panel.isVisible():
                QTimer.singleShot(50, self._run_media_search)

    def _open_siq_file(self, path):
        try: siq = SiqPackage(path)
        except Exception as e: msgbox_warning(self,"Ошибка .siq",str(e)); return
        file_mb = os.path.getsize(path)/1024/1024
        siq_rounds = [{"round_name":rd["name"],"themes":[{"name":th["name"],"questions":[{"price":q["price"],"tries":0,"right":0} for q in th["questions"]]} for th in rd["themes"]]} for rd in siq.rounds]

        match_idx = None
        for i,ds in enumerate(self.datasets):
            if ds["pkg_name"].strip().lower() == siq.name.strip().lower(): match_idx=i; break

        if match_idx is not None:
            ds = self.datasets[match_idx]
            ds["total_duration_sec"] = siq.total_duration
            ds["siq_path"] = path
            if not ds.get("pkg_size"): ds["pkg_size"] = f"{file_mb:.1f} МБ"
            # Ensure ds has at least as many rounds as the siq (handles newly added rounds)
            for ri, siq_rd in enumerate(siq.rounds):
                if ri >= len(ds.get("rounds", [])):
                    if "rounds" not in ds: ds["rounds"] = []
                    ds["rounds"].append({
                        "round_name": siq_rd["name"],
                        "round_type": siq_rd.get("type", ""),
                        "round_comment": siq_rd.get("comment", ""),
                        "themes": [
                            {"name": th["name"],
                             "questions": [{"price": q["price"], "tries": 0, "right": 0}
                                           for q in th["questions"]]}
                            for th in siq_rd["themes"]
                        ]
                    })
            save_datasets(self.datasets)
            ds["widget"].attach_siq(siq)
            self.sidebar.rebuild(self.datasets)
            self.sidebar.select_by_real(match_idx); self._show_ds(match_idx)
            real_idx = match_idx
        else:
            new_ds = {"pkg_name":siq.name,"stats":"","pkg_size":f"{file_mb:.1f} МБ",
                      "rounds":siq_rounds,"tab_id":self.sidebar.current_tab_id(),
                      "total_duration_sec":siq.total_duration,"siq_path":path}
            self._add_dataset(new_ds)
            idx = len(self.datasets)-1
            self.sidebar.select_by_real(idx); self._show_ds(idx)
            self.datasets[idx]["widget"].attach_siq(siq)
            real_idx = idx

        self._auto_fetch_stats(real_idx, siq.name, list(siq.pkg_authors), siq.rounds)

    def _auto_fetch_stats(self, real_idx, name, authors, siq_rounds):
        """Тянет статистику пакета с SIStatistics в фоне — та же логика имя+авторы,
        что и в «Поиск пакетов» (см. sigstats/stats_api.py, siquester/auto_stats.py).
        Без авторов запрос почти гарантированно 404 — не тратим время впустую."""
        if not authors:
            return
        # Карта (round_idx,theme_idx,question_idx) -> (round_name,theme_name,price):
        # у API индексы порядковые, а в ds["rounds"] (после attach_siq) вопросы
        # ищутся по имени раунда/темы + цене — строим карту, пока индексы под рукой.
        keymap = {}
        for r_idx, rd in enumerate(siq_rounds):
            for t_idx, th in enumerate(rd["themes"]):
                for q_idx, q in enumerate(th["questions"]):
                    keymap[(r_idx, t_idx, q_idx)] = (rd["name"], th["name"], q["price"])

        def _do_fetch():
            try:
                result = auto_stats.fetch(name, authors)
            except Exception as e:
                _logger.warning(f"[auto stats] {e}")
                return
            if result is None:
                return
            summary, per_question = result
            named = {keymap[k]: v for k, v in per_question.items() if k in keymap}
            _get_ui_bridge().deliver_call(
                lambda: self._apply_auto_stats(real_idx, summary, named))
        _threading.Thread(target=_do_fetch, daemon=True, name="auto-stats").start()

    def _apply_auto_stats(self, real_idx, summary, named_stats):
        """Накладывает результат _auto_fetch_stats на уже открытый датасет.

        И сводная строка ("Завершённых игр"), и поштучная статистика вопросов
        (tries/right) обновляются КАЖДЫЙ раз, когда пришли свежие данные — обе
        растут со временем по мере того, как в игру играют ещё. Раньше tries/
        right заполнялись только в пустые (0/0) значения (защита от перетирания
        ручной вставки HTML с сайта) — но ручная вставка убрана, автофетч теперь
        единственный источник, поэтому «замораживать» значения на первом фетче
        больше не нужно: пак иначе никогда не подхватывал бы новую статистику."""
        if real_idx >= len(self.datasets):
            return
        ds = self.datasets[real_idx]
        changed = False
        if summary.get("rate") is not None:
            pct = round(summary["rate"] * 100)
            new_stats = f"Завершенных игр: {summary['completed']} из {summary['started']} ({pct}%)"
            if new_stats != ds.get("stats"):
                ds["stats"] = new_stats
                changed = True
        for rd in ds.get("rounds", []):
            rn = rd.get("round_name", "")
            for th in rd.get("themes", []):
                tn = th.get("name", "")
                for q in th.get("questions", []):
                    key = (rn, tn, q.get("price"))
                    st = named_stats.get(key)
                    if st and (q.get("tries") != st["tries"] or q.get("right") != st["right"]):
                        q["tries"] = st["tries"]; q["right"] = st["right"]
                        changed = True
        if not changed:
            return

        # Пересобираем страницу пакета целиком — точечно перекрашивать уже
        # построенные плитки менее надёжно, чем просто пересоздать страницу.
        old_w = ds["widget"]
        new_w = ResultPage(ds, parent=self)
        if hasattr(old_w, "_siq") and old_w._siq:
            new_w.attach_siq(old_w._siq)
        self.stack.addWidget(new_w)
        ds["widget"] = new_w
        was_current = self.stack.currentWidget() is old_w
        self.stack.removeWidget(old_w)
        old_w.deleteLater()
        if was_current:
            self.stack.setCurrentWidget(new_w)
        self.sidebar.rebuild(self.datasets)
        save_datasets(self.datasets)

    def _show_save_notification(self):
        """Show 'Файл сохранён' banner at top-center of the window for 3 seconds."""
        lbl = self._save_notif
        lbl.adjustSize()
        x = (self.width() - lbl.width()) // 2
        lbl.move(x, 8)
        lbl.raise_(); lbl.show()
        self._save_notif_timer.start(3000)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, '_save_notif') and self._save_notif.isVisible():
            self._save_notif.adjustSize()
            x = (self.width() - self._save_notif.width()) // 2
            self._save_notif.move(x, 8)
        if hasattr(self, '_search_panel'):
            self._reposition_panels()
            # Keep visible panels in correct position
            for p in (self._search_panel, self._media_search_panel):
                if p.isVisible():
                    p.raise_()

    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
        else: super().dragEnterEvent(e)
    def dragMoveEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self,e):
        for url in e.mimeData().urls():
            p=url.toLocalFile()
            if os.path.splitext(p)[1].lower() == '.siq': self._open_siq_file(p); e.acceptProposedAction(); return
        super().dropEvent(e)

    def _delete_ds(self,real_idx):
        if not(0<=real_idx<len(self.datasets)): return
        ds=self.datasets[real_idx]; w=ds["widget"]
        if hasattr(w,"_siq") and w._siq:
            try: w._siq.close()
            except: pass
        self.stack.removeWidget(w); w.deleteLater(); self.datasets.pop(real_idx)
        self.sidebar.rebuild(self.datasets); self._update_info()
        save_datasets(self.datasets)   # saves immediately with item removed
        if self.datasets: ni=min(real_idx,len(self.datasets)-1); self.sidebar.select_by_real(ni); self._show_ds(ni)
        else: self.stack.setCurrentWidget(self.empty_page)

    def _on_reorder(self,real_from,real_to):
        if not(0<=real_from<len(self.datasets) and 0<=real_to<len(self.datasets)) or real_from==real_to: return
        item=self.datasets.pop(real_from); self.datasets.insert(real_to,item)
        self.sidebar.rebuild(self.datasets); self.sidebar.select_by_real(real_to); self._show_ds(real_to); save_datasets(self.datasets)

    def _move_to_tab(self,real_idx,tab_id):
        if 0<=real_idx<len(self.datasets): self.datasets[real_idx]["tab_id"]=tab_id; self.sidebar.rebuild(self.datasets); save_datasets(self.datasets)

    def _save_after_theme_move(self):
        save_datasets(self.datasets)
        # Refresh the "saved: dd.mm.yyyy HH:MM" label for the current package
        try:
            idx = self.sidebar.current_real_idx()
            if 0 <= idx < len(self.datasets):
                siq_path = self.datasets[idx].get("siq_path", "")
                if siq_path and os.path.exists(siq_path):
                    mtime = os.path.getmtime(siq_path)
                    dt = _dt.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")
                    self._set_filename_text(f"📄 {os.path.basename(siq_path)}  · сохранён {dt}")
        except Exception:
            pass

    def _rename_pkg(self, real_idx: int, new_name: str):
        if not (0 <= real_idx < len(self.datasets)): return
        self.datasets[real_idx]["pkg_name"] = new_name
        # Update SIQ file name if attached
        w = self.datasets[real_idx]["widget"]
        if hasattr(w, '_siq') and w._siq:
            w._siq.name = new_name
        w._refresh_banner_widget()
        self.sidebar.rebuild(self.datasets)
        self._update_info()
        save_datasets(self.datasets)

    def _update_info(self):
        n=len(self.datasets)
        if not n: self.lbl_info.setText(""); return
        total=sum(sum(sum(len(t["questions"]) for t in rd["themes"]) for rd in ds["rounds"]) for ds in self.datasets)
        self.lbl_info.setText(f"Пакетов: {n}  ·  вопросов: {total}")

    def closeEvent(self,e):
        for ds in self.datasets:
            w=ds["widget"]
            if hasattr(w,"_siq") and w._siq:
                try: w._siq.close()
                except: pass
        e.accept()
        # Force exit so any stuck daemon threads don't keep the process alive —
        # ТОЛЬКО в standalone-режиме (окно top-level, без родителя). Встроенное в
        # SI-HYX окно имеет родителя (вкладку): убивать весь хост-процесс нельзя.
        if self.parent() is None:
            QTimer.singleShot(500, lambda: os._exit(0))

__all__ = [
    'EmptyPage',
    'MainWindow',
]
