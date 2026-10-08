# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""История кадров: ключ URL, чтение и запись уже использованных кадров. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def frame_url_key(url) -> str:
    """Ключ кадра в истории: ссылка без ?query (Shikimori дописывает к ней
    метку времени, и один и тот же кадр иначе выглядел бы новым каждый раз)."""
    return str(url or "").split("?")[0].strip()

frame_url_key.__module__ = _api.__name__
_api.frame_url_key = frame_url_key


def load_frame_history(path: str = _api.FRAMES_HISTORY_FILE) -> list[str]:
    """Ссылки на кадры, уже побывавшие в собранных паках (пусто — файла нет)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = _api.json.load(f)
    except Exception:  # noqa: BLE001 — истории может не быть вовсе
        return []
    urls = data.get("frames") if isinstance(data, dict) else data
    if not isinstance(urls, list):
        return []
    return [str(u) for u in urls if u]

load_frame_history.__module__ = _api.__name__
_api.load_frame_history = load_frame_history


def save_frame_history(urls, path: str = _api.FRAMES_HISTORY_FILE) -> bool:
    """Перезаписывает историю кадров (самые старые обрезаются по лимиту)."""
    keep = [u for u in urls if u][-_api.FRAME_HISTORY_LIMIT:]
    try:
        _api.os.makedirs(_api.os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _api.json.dump({"frames": keep}, f, ensure_ascii=False)
        _api.os.replace(tmp, path)
        return True
    except OSError:
        return False

save_frame_history.__module__ = _api.__name__
_api.save_frame_history = save_frame_history
