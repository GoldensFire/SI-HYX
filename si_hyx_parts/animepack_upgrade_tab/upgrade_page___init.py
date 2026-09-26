# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_UpgradePage: __init__. Public namespace: animepack_upgrade_tab."""
from __future__ import annotations
import animepack_upgrade_tab as _api


def __init__(self, main_window=None, settings: _api.Optional[dict] = None,
             profile: str = "anime"):
    super(_api._UpgradePage, self).__init__()
    self.main = main_window
    self.profile = _api.normalize_profile(profile) if _api._HAS_CORE else "anime"
    self._pool = _api.QThreadPool.globalInstance()
    self._task = None
    self._siq = ""                     # какой пак апгрейдим
    self._out_dir = ""
    self._last_pack = ""
    self._started_at = 0.0
    self._initial = dict(settings or {})

    if not _api._HAS_CORE:
        self._build_unavailable()
        return
    self._build_ui()
    self.apply_settings(self._initial or _api.UpgradeSettings(
        profile=self.profile).to_dict())
    # Пак можно просто бросить на вкладку мышью — как файлы на «Обработку».
    self.setAcceptDrops(True)

# ── чем наполнен пак ──────────────────────────────────────────────────
@property
def source_name(self) -> str:
    """Как зовут базу названий."""
    return "Shikimori"

@property
def what(self) -> str:
    """Чем наполнен пак — словом, каким это называть в подписях."""
    return "аниме"

# ── UI ────────────────────────────────────────────────────────────────
def _build_unavailable(self):
    lay = _api.QVBoxLayout(self)
    lbl = _api.QLabel("Не удалось загрузить вкладку «Апгрейд пака».\n\n"
                 f"{_api._IMPORT_ERROR}")
    lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color:{_api.C['text2']}; font-size:13px;")
    lay.addStretch(); lay.addWidget(lbl); lay.addStretch()
