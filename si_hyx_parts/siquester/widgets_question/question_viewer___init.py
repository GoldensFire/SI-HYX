# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""QuestionViewer: __init__. Public namespace: siquester.widgets_question."""
import siquester.widgets_question as _api


def __init__(self, siq: _api.SiqPackage, parent=None):
    super(_api.QuestionViewer, self).__init__(parent)
    self.siq = siq
    self.setStyleSheet("background:#181825;")
    self._media_widgets: list = []
    self._current_rnd = 0
    self._current_th = 0
    self._current_price = 0
    self.setAcceptDrops(True)

    root = _api.QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

    # ── Header ──────────────────────────────────────────────
    hdr_row = _api.QHBoxLayout(); hdr_row.setContentsMargins(0, 0, 0, 0); hdr_row.setSpacing(0)
    self._hdr = _api.QLabel("← Нажмите на цену вопроса в таблице")
    self._hdr.setStyleSheet(
        "color:#a6adc8; font-size:12px; font-weight:500;"
        "background:#1e1e2e; padding:8px 14px; border-bottom:1px solid #313244;")
    hdr_row.addWidget(self._hdr, stretch=1)

    self._edit_btn = _api.QPushButton("✏  Изменить")
    self._edit_btn.setObjectName(_api._ON_BTN_UPDATE)
    self._edit_btn.setFixedHeight(32)
    self._edit_btn.setToolTip("Редактировать вопрос (текст, ответы, цену)")
    self._edit_btn.setEnabled(False)
    self._edit_btn.setStyleSheet(
        "QPushButton{background:#313244;color:#a6e3a1;border:none;"
        "border-left:1px solid #313244;border-bottom:1px solid #313244;"
        "padding:0 14px;font-size:12px;font-weight:600;}"
        "QPushButton:hover{background:#313244;color:#a6e3a1;}"
        "QPushButton:disabled{color:#45475a;background:#1e1e2e;}"
    )
    self._edit_btn.clicked.connect(self._on_edit_clicked)
    hdr_row.addWidget(self._edit_btn)
    root.addLayout(hdr_row)

    # ── Single shared scroll area ────────────────────────────
    self._scroll = _api.QScrollArea(); self._scroll.setWidgetResizable(True)
    self._scroll.setStyleSheet("border:none; background:#181825;")
    self._scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    self._scroll.viewport().setStyleSheet("background:#181825;")
    _api._install_wheel_filter(self._scroll)

    self._content_w = _api.QWidget(); self._content_w.setStyleSheet("background:#181825;")
    self._content_vl = _api.QVBoxLayout(self._content_w)
    self._content_vl.setContentsMargins(0,0,0,12); self._content_vl.setSpacing(0)

    # ВОПРОС section
    q_hdr = _api.QLabel("ВОПРОС")
    q_hdr.setStyleSheet(_api._SS_TOPBAR_LABEL)
    self._content_vl.addWidget(q_hdr)
    self._q_inner = _api.QWidget(); self._q_inner.setStyleSheet("background:#181825;")
    self._q_inner.setAcceptDrops(True)
    self._q_inner.dragEnterEvent = self._section_drag_enter
    self._q_inner.dragLeaveEvent = lambda e, w=self._q_inner: self._section_drag_leave(w)
    self._q_inner.dropEvent      = self.dropEvent
    self._q_lay = _api.QVBoxLayout(self._q_inner)
    self._q_lay.setContentsMargins(10,10,10,10); self._q_lay.setSpacing(6)
    self._content_vl.addWidget(self._q_inner)

    # Separator
    sep = _api.QFrame(); sep.setFixedHeight(1)
    sep.setStyleSheet("background:#313244; margin:0;")
    self._content_vl.addWidget(sep)

    # ОТВЕТ section
    a_hdr = _api.QLabel("ОТВЕТ")
    a_hdr.setStyleSheet(_api._SS_TOPBAR_LABEL)
    self._content_vl.addWidget(a_hdr)
    self._a_inner = _api.QWidget(); self._a_inner.setStyleSheet("background:#181825;")
    self._a_inner.setAcceptDrops(True)
    self._a_inner.dragEnterEvent = self._section_drag_enter
    self._a_inner.dragLeaveEvent = lambda e, w=self._a_inner: self._section_drag_leave(w)
    # Force param_name="answer" for any file dropped directly onto the answer section
    def _a_inner_drop(ev, _self=self):
        md = ev.mimeData()
        if md.hasFormat(_api._MIME_BLOCK) and _self._current_price:
            _self.dropEvent(ev); return
        if md.hasUrls() and _self._current_price:
            rnd, th, price = _self._current_rnd, _self._current_th, _self._current_price
            try:
                qs = _self.siq.rounds[rnd]["themes"][th]["questions"]
                q_idx = _api._q_idx(qs, price)
            except (StopIteration, Exception):
                return
            for url in md.urls():
                path = url.toLocalFile()
                if _api.Path(path).suffix.lower() in _api._MEDIA_EXTS:
                    _self._do_add_media(rnd, th, q_idx, path, param_name="answer")
            ev.acceptProposedAction()
            _self._clear_section_highlights()
    self._a_inner.dropEvent = _a_inner_drop
    self._a_lay = _api.QVBoxLayout(self._a_inner)
    self._a_lay.setContentsMargins(10,10,10,10); self._a_lay.setSpacing(6)
    self._content_vl.addWidget(self._a_inner)

    self._content_vl.addStretch(1)
    self._scroll.setWidget(self._content_w)
    root.addWidget(self._scroll, stretch=1)
    self._copy_hl_clear = None   # set by copy button; cleared on mouse press

def mousePressEvent(self, ev):
    # Clear copy-highlight on any click inside the viewer
    if self._copy_hl_clear:
        try: self._copy_hl_clear()
        except Exception as _e: _api._logger.debug(str(_e))
        self._copy_hl_clear = None
    super(_api.QuestionViewer, self).mousePressEvent(ev)

def _section_drag_enter(self, ev):
    """Highlight drop target section while dragging a block."""
    md = ev.mimeData()
    if md.hasFormat(_api._MIME_BLOCK) or (md.hasUrls() and self._current_price):
        # Highlight whichever section received the dragEnter
        # We re-use existing dropEvent — just highlight visually
        ev.acceptProposedAction()
        # Use the widget the event was installed on
        for section_w in (self._q_inner, self._a_inner):
            rect = section_w.rect()
            tl = section_w.mapToGlobal(rect.topLeft())
            gp = section_w.mapFromGlobal(ev.position().toPoint() if hasattr(ev, 'position') else tl)
            if rect.contains(gp):
                section_w.setStyleSheet("background:rgba(137,180,250,0.08);border:1px solid rgba(137,180,250,0.3);border-radius:4px;")
                break

def _section_drag_leave(self, widget: _api.QWidget):
    widget.setStyleSheet("background:#181825;")

def show_question(self, q_obj: dict, rnd_idx: int = 0, theme_idx: int = 0):
    price = q_obj["price"]; dur = q_obj["dur"]
    self._hdr.setText(f"Вопрос  •  Цена: {price}  •  ⏱ {_api.fmt_dur(dur)}")
    self._current_rnd = rnd_idx
    self._current_th = theme_idx
    self._current_price = price
    self._edit_btn.setEnabled(True)
    self._stop_player()
    q_type = q_obj.get("q_type", "")
    self._fill_lay(self._q_lay,
                   [i for i in q_obj["items"] if i["param"] in ("question","background")])
    # For point mode pass only answer items (image), _fill_lay will build PointOnImageWidget
    a_items = [i for i in q_obj["items"] if i["param"] == "answer"]
    self._fill_lay(self._a_lay, a_items,
                   q_obj["answers"],
                   q_obj.get("wrong_answers", []),
                   q_obj.get("answer_options", {}),
                   q_type,
                   q_obj.get("answer_deviation", 0.1))
    # Point mode and select mode have their own interactive panels
    if q_type not in ("point", "select"):
        clean_wrong = [w for w in q_obj.get("wrong_answers", [])
                       if w.strip() and
                       ("." not in w or _api.Path(w.strip()).suffix.lower() not in _api._MEDIA_EXTS)]
        answers_snap = q_obj.get("answers", [])
        _api.QTimer.singleShot(0, lambda a=answers_snap, w=clean_wrong:
                          self._rebuild_answer_editor(a, w))
    _api.QTimer.singleShot(30, lambda: self._scroll.verticalScrollBar().setValue(0))
