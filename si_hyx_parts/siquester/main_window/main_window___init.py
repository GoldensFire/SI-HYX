# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MainWindow: __init__. Public namespace: siquester.main_window."""
import siquester.main_window as _api


def __init__(self):
    super(_api.MainWindow, self).__init__()
    # Suppress any native window creation flash on Windows:
    # keep the window fully hidden until main() calls showMaximized().
    self.hide()
    _api._get_ui_bridge()
    self.setWindowTitle("SIGame Statistics + SiQ Viewer")
    self.setMinimumSize(980, 620)
    try:
        screen = _api.QApplication.primaryScreen().availableGeometry()
        self.resize(min(screen.width(), 1440), min(screen.height(), 900))
    except Exception:
        self.resize(1440, 860)
    self.datasets: list[dict] = []
    self._build()
    self._load_saved()

def showEvent(self, ev):
    """Cache the MainWindow reference on first show — avoids repeated .window() traversal."""
    super(_api.MainWindow, self).showEvent(ev)
    if not hasattr(self, '_mw') or self._mw is None:
        self._mw = _api._find_mw(self)  # type: ignore


def _build(self):
    root=_api.QWidget(); root.setStyleSheet("background:#181825;"); self.setCentralWidget(root)
    v=_api.QVBoxLayout(root); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
    # App-level event filter (global shortcuts: Ctrl+S/F, WASD, click-outside)
    # is installed/removed by the SI-HYX host wrapper only while the SiQuester
    # tab is visible — so its hotkeys don't fire on the other SI-HYX tabs.
    tb=_api.QFrame(); tb.setFixedHeight(46); tb.setStyleSheet(_api._SS_TOPBAR)
    tbl=_api.QHBoxLayout(tb); tbl.setContentsMargins(8,0,16,0); tbl.setSpacing(6)
    # Search & Media buttons on the LEFT (replace the old title)
    for obj,label,slot in [("btn_search","🔍 Поиск",self._toggle_search),
                            ("btn_media_search","🎬 Медиа",self._toggle_media_search)]:
        btn=_api.AnimatedButton(label); btn.setObjectName(obj); btn.clicked.connect(slot); tbl.addWidget(btn)
    self.lbl_filename = _api.QLabel("")
    self.lbl_filename.setStyleSheet(
        "color:#a6adc8;font-size:12px;padding-left:12px;padding-right:16px;")
    self.lbl_filename.setSizePolicy(_api._Expand, _api._Pref)
    self.lbl_filename.setMinimumWidth(0)
    self.lbl_filename.setTextFormat(_api.Qt.TextFormat.PlainText)
    tbl.addWidget(self.lbl_filename, stretch=1)

    self.lbl_filename._full_text = ""

    def _apply_elision(lbl=self.lbl_filename):
        text = lbl._full_text
        if not text:
            lbl.setText(""); return
        w = lbl.width()
        if w <= 4:
            _api.QTimer.singleShot(0, lambda: _apply_elision(lbl)); return
        fm = lbl.fontMetrics()
        lbl.setText(fm.elidedText(text, _api.Qt.TextElideMode.ElideMiddle, w - 4))

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
    self._save_notif = _api.QLabel("✅  Файл сохранён")
    self._save_notif.setStyleSheet(
        "background:rgba(166,227,161,0.92);color:#181825;font-size:13px;font-weight:700;"
        "border-radius:8px;padding:8px 24px;")
    self._save_notif.setAlignment(_api._AlignC)
    self._save_notif.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    self._save_notif.hide()
    self._save_notif.setParent(self)   # reparented after window is built
    self._save_notif_timer = _api.QTimer(self)
    self._save_notif_timer.setSingleShot(True)
    self._save_notif_timer.timeout.connect(self._save_notif.hide)
    self.lbl_info=_api.QLabel(""); self.lbl_info.setStyleSheet("color:#585b70;font-size:12px;"); tbl.addWidget(self.lbl_info)
    for obj,label,slot in [("btn_restart","↺ Перезапуск",self._restart)]:
        btn=_api.AnimatedButton(label); btn.setObjectName(obj); btn.clicked.connect(slot); tbl.addWidget(btn)
    v.addWidget(tb)
    body=_api.QWidget(); body.setStyleSheet("background:#181825;")
    bl=_api.QHBoxLayout(body); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(0); v.addWidget(body,stretch=1)
    self.sidebar=_api.Sidebar()
    self.sidebar.setMinimumWidth(0)
    self.sidebar.setAttribute(_api.Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
    self.sidebar.setAutoFillBackground(True)  # prevent content bleeding through during animation
    self.sidebar.item_selected.connect(self._show_ds)
    self.sidebar.delete_requested.connect(self._delete_ds)
    self.sidebar.reorder_requested.connect(self._on_reorder)
    self.sidebar.move_to_tab.connect(self._move_to_tab)
    self.sidebar.rename_requested.connect(self._rename_pkg)
    bl.addWidget(self.sidebar)

    # ── Collapse button ──────────────────────────────────────
    settings = _api.load_settings()
    self._sidebar_visible = settings.get("sidebar_visible", True)
    self._sidebar_anim = _api.QPropertyAnimation(self.sidebar, b"maximumWidth")
    self._sidebar_anim.setDuration(130)
    self._sidebar_anim.setEasingCurve(_api.QEasingCurve.Type.OutCubic)

    # Apply saved state immediately (no animation on startup)
    if not self._sidebar_visible:
        self.sidebar.setFixedWidth(0)

    # ── Stack lives directly after the sidebar, no separator column ──
    self.stack=_api.QStackedWidget(); self.stack.setStyleSheet("background:#181825;")
    self.stack.setAttribute(_api.Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
    bl.addWidget(self.stack,stretch=1)

    # Floating collapse button — parented to body so it sits on top of the stack
    self._collapse_btn = _api.QPushButton("▶" if not self._sidebar_visible else "◀")
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
    self.empty_page=_api.EmptyPage()
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
def _build_search_panel(self) -> _api.QFrame:
    """Build the floating Ctrl+F search overlay."""
    panel = _api.QFrame()
    panel.setStyleSheet(_api._SS_PANEL_BRD2)
    pl = _api.QVBoxLayout(panel); pl.setContentsMargins(12, 10, 12, 10); pl.setSpacing(8)

    hdr = _api.QHBoxLayout(); hdr.setSpacing(8)
    hdr.addWidget(_api._lbl("🔍  Поиск по всем пакам", "color:#cdd6f4;font-size:13px;font-weight:700;"))
    hdr.addStretch()
    close_btn = _api.QPushButton("✕"); close_btn.setObjectName(_api._ON_BTN_DEL)
    close_btn.setFixedSize(22, 22)
    close_btn.clicked.connect(self._hide_search)
    hdr.addWidget(close_btn)
    pl.addLayout(hdr)

    self._search_edit = _api.QLineEdit()
    self._search_edit.setPlaceholderText("Введите текст для поиска в вопросах, ответах, темах…")
    self._search_edit.setStyleSheet(_api._SS_INPUT_LARGE)
    self._search_edit.textChanged.connect(self._on_search_text_changed)
    self._search_edit.returnPressed.connect(self._run_search)
    pl.addWidget(self._search_edit)

    opt_row = _api.QHBoxLayout(); opt_row.setSpacing(12)
    self._search_cb_q   = _api.QCheckBox("Вопросы");  self._search_cb_q.setChecked(True)
    self._search_cb_ans = _api.QCheckBox("Ответы");   self._search_cb_ans.setChecked(True)
    self._search_cb_th  = _api.QCheckBox("Темы");     self._search_cb_th.setChecked(True)
    for cb in (self._search_cb_q, self._search_cb_ans, self._search_cb_th):
        cb.setStyleSheet("color:#a6adc8;font-size:11px;")
        cb.stateChanged.connect(self._run_search)
        opt_row.addWidget(cb)
    opt_row.addStretch()
    self._search_count_lbl = _api._lbl("", "color:#585b70;font-size:11px;")
    opt_row.addWidget(self._search_count_lbl)
    pl.addLayout(opt_row)

    self._search_results = _api.QListWidget()
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

    pl.addWidget(_api._lbl("Enter / двойной клик — перейти к вопросу", "color:#585b70;font-size:10px;"))
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
