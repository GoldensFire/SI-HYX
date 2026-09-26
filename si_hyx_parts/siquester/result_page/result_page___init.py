# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage: __init__. Public namespace: siquester.result_page."""
import siquester.result_page as _api


def __init__(self, ds, parent=None):
    super(_api.ResultPage, self).__init__(parent)
    self.setStyleSheet("background:#181825;")
    self.ds = ds
    self._siq: _api.SiqPackage | None = None
    self._viewer: _api.QuestionViewer | None = None
    self._gen = 0
    self._pending: list[_api.QWidget] = []
    self._content_widget = None
    # Сетку плиток строим ЛЕНИВО — только когда страница пакета реально
    # показана (см. _rebuild_content/showEvent). При старте так со всеми
    # пакетами сразу: иначе построение 18 пакетов по ~5 сек подряд намертво
    # вешало GUI-поток. Видимая страница строится сразу.
    self._content_dirty = False
    self._siq_view_dirty = False   # вьюер вопросов тоже строим лениво (см. attach_siq)
    # ── Undo / Redo stacks ──────────────────────────────
    self._undo_stack: _api._collections.deque = _api._collections.deque(maxlen=self._MAX_UNDO)
    self._redo_stack: list = []
    # ── Banner caches (must exist before first _refresh_banner_widget call) ─
    self._banner_fill_cache: tuple[int, float] | None = None
    self._banner_fill_siq_id: int | None = None
    self._banner_refs: dict | None = None
    self._banner_struct_key = None
    # Cache for g_t / g_r / n_all stats — invalidated when questions are played.
    # Key: id(rounds list), Value: (n_all, g_t, g_r)
    self._banner_stats_cache: tuple | None = None
    self._banner_stats_key: int = 0   # incremented on every stats update
    # ── Drop-area registry ───────────────────────────────
    # _drop_areas: flat list for iteration (WASD, deselect-all)
    # _drop_area_index: (r_idx, t_idx) → area for O(1) targeted lookup
    self._drop_areas: list = []
    self._drop_area_index: dict = {}
    # ── Cached MainWindow ref (set in showEvent to avoid repeated .window()) ─
    self._mw = None

    root = _api.QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
    self._banner_frame = _api.QFrame()
    self._refresh_banner_widget()   # safe now: all attrs exist
    root.addWidget(self._banner_frame)

    # Horizontal splitter: stats left | viewer right
    self._splitter = _api.QSplitter(_api.Qt.Orientation.Horizontal)
    self._splitter.setHandleWidth(3)
    root.addWidget(self._splitter, stretch=1)

    left_w = _api.QWidget(); left_w.setStyleSheet("background:#181825;")
    left_lay = _api.QVBoxLayout(left_w); left_lay.setContentsMargins(0, 0, 0, 0)
    self._scroll = _api.SmoothScrollArea(); self._scroll.setStyleSheet("border:none;background:#181825;")
    left_lay.addWidget(self._scroll)
    self._splitter.addWidget(left_w)

    # Right viewer panel (hidden until SIQ attached)
    self._viewer_wrap = _api.QWidget(); self._viewer_wrap.setStyleSheet("background:#181825;")
    self._viewer_wrap.setVisible(False)
    self._viewer_lay = _api.QVBoxLayout(self._viewer_wrap); self._viewer_lay.setContentsMargins(0, 0, 0, 0)
    ph = _api._lbl("← Нажмите на цену вопроса в таблице",
              "color:#585b70;font-size:13px;background:#181825;padding:20px;")
    ph.setAlignment(_api._AlignC); self._viewer_lay.addWidget(ph)
    self._splitter.addWidget(self._viewer_wrap)
    self._splitter.setSizes([10000, 0])

    self._rebuild_content(animated=False)

def showEvent(self, ev):
    super(_api.ResultPage, self).showEvent(ev)
    if self._mw is None:
        self._mw = _api._find_mw(self)
    # Достраиваем отложенное при первом реальном показе страницы: сначала
    # вьюер+сетку (если был привязан siq), иначе — только сетку плиток.
    if getattr(self, "_siq_view_dirty", False):
        self._ensure_siq_view()
    elif getattr(self, "_content_dirty", False):
        # Первый показ страницы пакета — сетку плиток заполняем порциями,
        # чтобы доска появилась мгновенно, а не висла на ~1.4 с.
        self._rebuild_content(animated=False, chunked=True)

# ── Banner ────────────────────────────────────────────
def _invalidate_fill_cache(self):
    """Call after any question is added, removed, or its items change."""
    self._banner_fill_cache = None
