# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackResult. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


@_api.dataclass
class PackResult:
    path: str = ""
    songs: list = _api.field(default_factory=list)
    requested: int = 0
    failed_media: int = 0
    cancelled: bool = False
    elapsed: float = 0.0             # сколько секунд заняла генерация
    planned: dict = _api.field(default_factory=dict)
    actual: dict = _api.field(default_factory=dict)
    log_path: str = ''
    warnings: list[str] = _api.field(default_factory=list)
    # Номер, под которым собирался этот пак («№ 3»). Нужен вкладке: отменённый
    # прогон номер ВОЗВРАЩАЕТ, и следующий пак получит тот же (просьба
    # пользователя).
    pack_number: int = 0
    # Пак сохранён аварийно, после ошибки генерации (см. pack_completion).
    aborted: bool = False

PackResult.__module__ = _api.__name__
_api.PackResult = PackResult
