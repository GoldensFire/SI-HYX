# -*- coding: utf-8 -*-
"""Последний созданный файл у общей полосы прогресса."""
from __future__ import annotations

import main as _api


def _position_progress_button(self):
    """Прижимает SVG-кнопку к правому краю самой полосы прогресса."""
    bar = getattr(self, "pbar", None)
    button = getattr(self, "btn_open_progress", None)
    if bar is None or button is None:
        return
    button.move(max(0, bar.width() - button.width() - 1),
                max(0, (bar.height() - button.height()) // 2))
    button.raise_()


def set_global_result(self, path):
    value = _api.os.path.abspath(str(path or "")) if path else ""
    self._global_result_path = value
    button = getattr(self, "btn_open_progress", None)
    if button is None:
        return
    ready = bool(value and _api.os.path.isfile(value))
    button.setEnabled(ready)
    button.setToolTip(value if ready else "Последний созданный файл появится здесь")


def clear_global_result(self):
    self.set_global_result("")


def _open_global_result(self):
    path = str(getattr(self, "_global_result_path", "") or "")
    if not path or not _api.os.path.isfile(path):
        self.clear_global_result()
        return
    try:
        if _api.IS_WIN:
            _api.os.startfile(path)
        elif _api.sys.platform == "darwin":
            _api.subprocess.Popen(["open", path])
        else:
            _api.subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        _api.msgbox_critical(self, "Файл не открылся", str(exc))
