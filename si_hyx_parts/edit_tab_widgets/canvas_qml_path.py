# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_canvas_qml_path. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


def _canvas_qml_path():
    """Кладёт QML-сцену холста во временный файл и возвращает путь.

    Файлом, а не строкой: QQuickWidget.setContent() в PyQt6 не проброшен, а
    setSource() принимает только URL. Держать .qml отдельным ресурсом сборки
    ради двадцати строк не хочется — при первом холсте пишем заново."""
    tmp = _api.tempfile.gettempdir()
    path = _api.os.path.join(tmp, f"sihyx_video_canvas_{_api.os.getpid()}.qml")
    try:
        if not _api.os.path.exists(path):
            # Подчищаем сцены прошлых запусков (файл на процесс, иначе они
            # копились бы в temp по одному за каждый запуск программы).
            for name in _api.os.listdir(tmp):
                if (name.startswith("sihyx_video_canvas_")
                        and name.endswith(".qml") and name != _api.os.path.basename(path)):
                    try:
                        _api.os.remove(_api.os.path.join(tmp, name))
                    except OSError:
                        pass
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_api._QML_CANVAS_SOURCE.replace("__BG__", _api.C["bg"]))
        return path
    except OSError:
        return None

_canvas_qml_path.__module__ = _api.__name__
_api._canvas_qml_path = _canvas_qml_path

class _CanvasOverlayItem(_api.QQuickPaintedItem):
    """Слой оверлеев поверх кадра в QML-сцене холста.

    Рисует ровно то же и тем же кодом, что рисовал paintEvent ЦП-холста, —
    просто в сцене Quick, а не в backing store виджета."""

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas

    def paint(self, p):
        c = self._canvas
        if c is None:
            return
        try:
            if c._has_frame():
                c._paint_overlays(p, c.video_rect())
            elif c._audio_only_msg:
                c._paint_audio_only(p)
        except RuntimeError:            # холст уже снесён Qt — рисовать нечего
            pass

_CanvasOverlayItem.__module__ = _api.__name__
_api._CanvasOverlayItem = _CanvasOverlayItem
