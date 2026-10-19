# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Сцена GPU-холста: окно Qt Quick и слой оверлеев. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


# Имя провайдера картинок в адресах «image://…» слоя оверлеев.
_OVERLAY_PROVIDER = "sihyxcanvas"


class _CanvasOverlayProvider(_api.QQuickImageProvider):
    """Отдаёт сцене холста готовую картинку оверлеев.

    Картинку рисует GUI-поток (VideoCanvas._refresh_overlay) тем же
    QPainter-кодом, что и ЦП-холст, а сцена забирает её при смене адреса
    источника. Провайдер зовётся синхронно в GUI-потоке (у Image стоит
    asynchronous: false) — Python в поток рендера не попадает."""

    def __init__(self):
        super().__init__(_api.QQuickImageProvider.ImageType.Image)
        self.image = _api.QImage()

    def requestImage(self, _id, _requested_size):
        img = self.image
        return img, img.size()


_CanvasOverlayProvider.__module__ = _api.__name__
_api._CanvasOverlayProvider = _CanvasOverlayProvider


def _create_canvas_window(engine):
    """Создаёт окно сцены холста из QML.

    Окно рождает QML, а не Python-подкласс QQuickWindow: у объекта,
    созданного из Python, sip проверяет переопределения виртуальных методов
    под GIL, и первый же такой вызов из потока рендера во время синхронизации
    (GUI-поток в этот момент ждёт поток рендера, держа GIL внутри show() или
    setGeometry()) заклинил бы программу намертво."""
    comp = _api.QQmlComponent(engine)
    src = _api._QML_CANVAS_SOURCE.replace("__BG__", _api.C["bg"])
    comp.setData(src.encode("utf-8"), _api.QUrl())
    win = comp.create()
    if win is None or not isinstance(win, _api.QQuickWindow):
        errs = "; ".join(e.toString() for e in comp.errors())
        raise RuntimeError(errs or "QML-сцена холста не поднялась")
    # Мышь, колесо и перетаскивание файлов Qt отдаёт РОДИТЕЛЮ такого окна
    # (верхнему окну вкладки), а там их, как и прежде, разбирает сам холст:
    # кадрирование, накладки, зум, панорама, двойной клик, бросок файла.
    # Фокус окну сцены тоже не нужен — клавиши остаются у виджетов.
    win.setFlags(win.flags() | _api.Qt.WindowType.WindowTransparentForInput
                 | _api.Qt.WindowType.WindowDoesNotAcceptFocus)
    return win


_create_canvas_window.__module__ = _api.__name__
_api._create_canvas_window = _create_canvas_window


def _make_native_alone(widget):
    """Даёт виджету собственное нативное окно, не трогая никого вокруг.

    Обычный WA_NativeWindow делает нативными и всех соседей виджета, а те —
    своих предков и их соседей: от одной кнопки на холсте нативной становилась
    половина вкладки (боковая панель, таймлайн, плеер), а контейнер сцены
    переезжал в собственное окно. Соседей Qt не трогает, пока стоит
    AA_DontCreateNativeWidgetSiblings, — ставим его на время одного вызова
    (виджет при этом не должен потом менять родителя: смена родителя снова
    навязала бы нативность соседям)."""
    attr = _api.Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings
    was = _api.QApplication.testAttribute(attr)
    _api.QApplication.setAttribute(attr, True)
    try:
        widget.setAttribute(_api.Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        widget.setAttribute(_api.Qt.WidgetAttribute.WA_NativeWindow, True)
    finally:
        _api.QApplication.setAttribute(attr, was)


_make_native_alone.__module__ = _api.__name__
_api._make_native_alone = _make_native_alone


def _round_mask(size, radius):
    """Маска со скруглёнными углами для нативной кнопки поверх видео: углы
    вне маски показывают кадр, а не фон холста под окном сцены."""
    bm = _api.QBitmap(size)
    bm.fill(_api.Qt.GlobalColor.color0)
    p = _api.QPainter(bm)
    p.setPen(_api.Qt.PenStyle.NoPen)
    p.setBrush(_api.Qt.GlobalColor.color1)
    p.drawRoundedRect(_api.QRectF(0, 0, size.width(), size.height()), radius, radius)
    p.end()
    return _api.QRegion(bm)


_round_mask.__module__ = _api.__name__
_api._round_mask = _round_mask
