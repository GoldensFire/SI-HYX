# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_thumb_cache_key. Public namespace: widgets."""
import widgets as _api


def _thumb_cache_key(path: str) -> str:
    st = _api.os.stat(path)
    raw = f"{_api.os.path.abspath(path)}|{int(st.st_mtime)}|{st.st_size}"
    return _api.hashlib.sha1(raw.encode("utf-8")).hexdigest()

_thumb_cache_key.__module__ = _api.__name__
_api._thumb_cache_key = _thumb_cache_key

def _thumb_cache_read(path: str):
    """(байты картинки, строка длительности) из кэша или (None, "")."""
    try:
        with open(_api.os.path.join(_api._THUMB_CACHE_DIR, _api._thumb_cache_key(path)), "rb") as f:
            blob = f.read()
    except Exception:
        return None, ""
    head, sep, data = blob.partition(b"\n")
    if not sep or not data:
        return None, ""
    try:
        return data, head.decode("utf-8")
    except Exception:
        return data, ""

_thumb_cache_read.__module__ = _api.__name__
_api._thumb_cache_read = _thumb_cache_read

def _thumb_cache_write(path: str, data: bytes, dur: str) -> None:
    if not data:
        return
    tmp = ""
    try:
        _api.os.makedirs(_api._THUMB_CACHE_DIR, exist_ok=True)
        fp = _api.os.path.join(_api._THUMB_CACHE_DIR, _api._thumb_cache_key(path))
        tmp = f"{fp}.{_api.uuid.uuid4().hex}.part"
        with open(tmp, "wb") as f:
            f.write((dur or "").encode("utf-8") + b"\n" + data)
        _api.os.replace(tmp, fp)    # атомарно: недописанную запись никто не прочтёт
    except Exception:
        if tmp:
            try: _api.os.remove(tmp)
            except Exception: pass

_thumb_cache_write.__module__ = _api.__name__
_api._thumb_cache_write = _thumb_cache_write

def _thumb_cache_trim() -> None:
    """Оставляет в кэше только _THUMB_CACHE_LIMIT самых свежих записей."""
    pass  # Shared state is addressed through _api.
    if _api._thumb_cache_trimmed:
        return
    _api._thumb_cache_trimmed = True
    try:
        entries = []
        with _api.os.scandir(_api._THUMB_CACHE_DIR) as it:
            for e in it:
                try:
                    if e.is_file():
                        entries.append((e.stat().st_mtime, e.path))
                except Exception:
                    pass
        if len(entries) <= _api._THUMB_CACHE_LIMIT:
            return
        entries.sort()
        for _, p in entries[:len(entries) - _api._THUMB_CACHE_LIMIT]:
            try: _api.os.remove(p)
            except Exception: pass
    except Exception:
        pass

_thumb_cache_trim.__module__ = _api.__name__
_api._thumb_cache_trim = _thumb_cache_trim
