# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_load_subtitle_presets. Public namespace: edit_tab_base."""
import edit_tab_base as _api


def _load_subtitle_presets():
    """Читает именованные пресеты стиля субтитров (НЕ путать с общими настройками
    приложения — отдельный файл, чтобы не трогать реальный settings.json)."""
    for path in (_api._SUBTITLE_PRESETS_PATH, _api._SUBTITLE_PRESETS_PATH + ".bak"):
        try:
            if _api.os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = _api.json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception:
            continue
    return {}

_load_subtitle_presets.__module__ = _api.__name__
_api._load_subtitle_presets = _load_subtitle_presets

def _save_subtitle_presets(presets):
    """Атомарная запись (tmp+.bak+os.replace) с защитой от затирания пустым
    словарём — та же схема, что и utils.save_settings, но для отдельного файла."""
    try:
        if not presets:
            for p in (_api._SUBTITLE_PRESETS_PATH, _api._SUBTITLE_PRESETS_PATH + ".bak"):
                if _api.os.path.exists(p) and _api.os.path.getsize(p) > 2:
                    return
    except Exception:
        pass
    try:
        _api.os.makedirs(_api.os.path.dirname(_api._SUBTITLE_PRESETS_PATH), exist_ok=True)
        tmp = _api._SUBTITLE_PRESETS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _api.json.dump(presets, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                _api.os.fsync(f.fileno())
            except Exception:
                pass
        try:
            if _api.os.path.exists(_api._SUBTITLE_PRESETS_PATH):
                _api.os.replace(_api._SUBTITLE_PRESETS_PATH, _api._SUBTITLE_PRESETS_PATH + ".bak")
        except Exception:
            pass
        _api.os.replace(tmp, _api._SUBTITLE_PRESETS_PATH)
    except Exception:
        pass

_save_subtitle_presets.__module__ = _api.__name__
_api._save_subtitle_presets = _save_subtitle_presets
