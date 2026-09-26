# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintCanvas. Public namespace: photo_tab."""
import photo_tab as _api


# ════════════════════════════════════════════════════════════════════════════
#  Удаление объектов / водяных знаков (LaMa, ONNX)
# ════════════════════════════════════════════════════════════════════════════
# WASD-пан, независимый от раскладки: на кириллице ev.key() физической W даёт Key_Ц,
# поэтому WASD читаем по nativeVirtualKey (Windows VK W=0x57/A=0x41/S=0x53/D=0x44).

class InpaintCanvas(_api.QWidget):
    """Холст редактора: показ изображения с зумом/панорамированием, рисование
    маски кистью/ластиком (полупрозрачным красным), инструмент кадрирования.

    Источник истины — numpy-массив BGR (self.img_bgr). Маска хранится как ARGB
    QImage-оверлей в РАЗРЕШЕНИИ изображения (а не экрана), поэтому точность не
    зависит от зума. Для инференса маска вынимается из альфа-канала оверлея."""

    TOOL_BRUSH = "brush"   # рисующая кисть ПО фото (мазок вживается в img_bgr)
    TOOL_MASK = "mask"     # кисть-маска: красным помечает область для удаления (LaMa)
    TOOL_ERASE = "erase"
    TOOL_CROP = "crop"
    TOOL_BLUR = "blur"     # кисть размытия: замыливает фото под мазком (в img_bgr)
    TOOL_MOVE = "move"   # перемещение наложенного (второго) изображения-слоя
    # Фигуры и текст (как в Paint) — рисуются прямо в изображение (self.img_bgr),
    # а не в маску-оверлей.
    TOOL_RECT = "rect"
    TOOL_ELLIPSE = "ellipse"
    TOOL_LINE = "line"
    TOOL_ARROW = "arrow"
    TOOL_TEXT = "text"
    _SHAPE_TOOLS = (TOOL_RECT, TOOL_ELLIPSE, TOOL_LINE, TOOL_ARROW)

    # Толщина скроллбаров, всплывающих при сильном приближении.
    _SB_THICK = 12

    statusChanged = _api.pyqtSignal(str)
    colorPicked = _api.pyqtSignal(_api.QColor)     # Alt-пипетка взяла цвет из изображения
    strokeFinished = _api.pyqtSignal()        # завершён штрих кистью (для авто-удаления)
    clearRequested = _api.pyqtSignal()        # нажата кнопка «Очистить» в углу холста
    imageChanged = _api.pyqtSignal()          # появилось/исчезло изображение (undo/redo) — пере-включить инструменты
    textSelected = _api.pyqtSignal()          # плавающий текст создан/выделен — открыть панель его свойств

    from si_hyx_parts.photo_tab.inpaint_canvas___init import (
        __init__,
        _sync_overlay_buttons,
        has_image,
        has_mask,
        set_image_bgr,
    )

    from si_hyx_parts.photo_tab.inpaint_canvas_add_overlay_image import (
        add_overlay_image,
        _rebuild_base,
        _draw_checker,
        has_alpha,
        apply_cutout,
        composited_bgra,
        _encode_layer,
        _decode_layer,
        _snapshot,
        _push_history,
        _restore_state,
        undo,
        redo,
        _transform_qimage,
        _after_orient_change,
        rotate_image,
        flip_image,
        _recompute_strokes_flag,
        _layer_alpha,
    )

    from si_hyx_parts.photo_tab.inpaint_canvas__recompute_paint_flag import (
        _recompute_paint_flag,
        set_tool,
        set_brush,
        set_blur_strength,
        set_brush_color,
        brush_color,
        set_shape_fill,
        set_text_font,
        set_text_color,
        set_text_stroke,
        _shape_pen,
        _draw_shape,
        _draw_arrow_head,
        _make_pending_shape,
        _draw_text_at,
        edit_pending_text,
        _draw_object,
        _object_bbox,
        _translate_pending,
        _pending_resizable,
        _pending_handle_at,
    )

    from si_hyx_parts.photo_tab.inpaint_canvas__resize_pending import (
        _resize_pending,
        _bake_object,
        _commit_pending,
        commit_pending,
        cancel_pending,
        _set_alt,
        _pick_color_at,
        clear_mask,
        clear_canvas,
        composited_bgr,
        bake_paint,
        fit,
        has_crop,
        _update_crop_buttons,
        apply_crop,
        cancel_crop,
    )

    from si_hyx_parts.photo_tab.inpaint_canvas_detect_black_bars import (
        detect_black_bars,
        crop_black_bars,
        _crop_rect_w,
        _crop_handle_at,
        _crop_cursor,
        _drag_crop,
        _on_crop_aspect_changed,
        _reshape_crop_to_aspect,
        _apply_aspect,
        _mask_alpha,
        get_mask,
        _fit,
        _w2i,
        _i2w,
        _img_rect_w,
        _content_size,
        _clamp_off,
    )

    from si_hyx_parts.photo_tab.inpaint_canvas__sync_scrollbars import (
        _sync_scrollbars,
        _on_hbar,
        _on_vbar,
        _paint_to,
        _paint_image_to,
        _begin_blur_stroke,
        _end_blur_stroke,
        _blur_to,
        _blit_base_region,
        mousePressEvent,
    )

    from si_hyx_parts.photo_tab.inpaint_canvas_mouse_move_event import (
        mouseMoveEvent,
        mouseDoubleClickEvent,
        mouseReleaseEvent,
        leaveEvent,
        wheelEvent,
        _pan_by,
        keyPressEvent,
        keyReleaseEvent,
        resizeEvent,
    )

    from si_hyx_parts.photo_tab.inpaint_canvas_paint_event import paintEvent

InpaintCanvas.__module__ = _api.__name__
_api.InpaintCanvas = InpaintCanvas

class _WarmupWorker(_api.QThread):
    """Фоновый прогрев сессии ONNX (загрузка 200-МБ модели ~10 с), чтобы первый
    клик «Удалить» не ждал инициализацию."""
    done = _api.pyqtSignal(str)
    failed = _api.pyqtSignal(str)

    def __init__(self, inpainter):
        super().__init__()
        self._inp = inpainter

    def run(self):
        try:
            self.done.emit(self._inp.warmup())
        except Exception as e:        # pragma: no cover
            import traceback; traceback.print_exc()
            self.failed.emit(str(e))

_WarmupWorker.__module__ = _api.__name__
_api._WarmupWorker = _WarmupWorker

class InpaintWorker(_api.QThread):
    """Фоновый инференс LaMa — UI не виснет на время обработки."""
    done = _api.pyqtSignal(object)
    failed = _api.pyqtSignal(str)
    progress = _api.pyqtSignal(int, int)

    def __init__(self, inpainter, img_bgr, mask):
        super().__init__()
        self._inp = inpainter
        self._img = img_bgr
        self._mask = mask

    def run(self):
        try:
            res = self._inp.inpaint(
                self._img, self._mask,
                progress=lambda d, t: self.progress.emit(int(d), int(t)))
            self.done.emit(res)
        except Exception as e:
            # Отмена пользователем (ModelCancelled) — не авария: сигнал шлём,
            # но консоль пугающим traceback'ом не засоряем.
            if not getattr(e, "cancelled", False):
                import traceback; traceback.print_exc()
            self.failed.emit(str(e))

InpaintWorker.__module__ = _api.__name__
_api.InpaintWorker = InpaintWorker

class BgRemoveWorker(_api.QThread):
    """Фоновое удаление фона (RMBG-2.0) — UI не виснет на инференсе/загрузке модели."""
    done = _api.pyqtSignal(object)
    failed = _api.pyqtSignal(str)
    progress = _api.pyqtSignal(int, int)

    def __init__(self, remover, img_bgr):
        super().__init__()
        self._rem = remover
        self._img = img_bgr

    def run(self):
        try:
            alpha = self._rem.remove(
                self._img,
                progress=lambda d, t: self.progress.emit(int(d), int(t)))
            self.done.emit(alpha)
        except Exception as e:
            # Отмена пользователем (ModelCancelled) — не авария: сигнал шлём,
            # но консоль пугающим traceback'ом не засоряем.
            if not getattr(e, "cancelled", False):
                import traceback; traceback.print_exc()
            self.failed.emit(str(e))

BgRemoveWorker.__module__ = _api.__name__
_api.BgRemoveWorker = BgRemoveWorker
