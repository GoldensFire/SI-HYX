# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_PaintedVideoCanvas. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


class _PaintedVideoCanvas(_api.QWidget):
    """Холст видео на ЦП: сам рисует кадры (QVideoSink → frame.toImage() →
    QPainter) и накладывает субтитры ПРЯМО В КАДР, как VLC. Кадр вписывается с
    сохранением пропорций (letterbox). Совместим по API субтитров с
    SubtitleOverlay.

    ВНИМАНИЕ: во вкладке «Монтаж» этот класс больше НЕ используется — там кадр
    выводит GPU-путь (VideoCanvas ниже: QQuickWidget + QML VideoOutput), потому
    что toImage() каждого кадра занимал главный поток на 8-9 мс при бюджете
    кадра 16.7 мс (1080p60), и вкладка «лагала». Здесь остался ЦП-путь для
    мини-плеера диалога субтитров (_SubtitlePreview): у него поверх холста живёт
    обычный дочерний виджет-оверлей (_StyledSubtitleOverlay), и переезд на Quick
    ему ничего не даёт.

    Вся логика, не связанная с САМИМ выводом кадра (пин кадра, часы кадра,
    граница OUT, кадрирование, накладки, трек-превью, зум/панорама, мышь), живёт
    здесь же — GPU-холст наследует её и переопределяет только вывод."""

    # Кадр пришёл с PTS за границей OUT (см. set_play_bound) — плеер надо ставить
    # на паузу ДО показа этого кадра (защита от проскока правой границы).
    boundaryReached = _api.pyqtSignal()
    # Кадрирование видео завершено кнопкой «Применить»/«Отмена» на холсте (как в
    # «Редактировании фото») — вкладка снимает чек с кнопки «Кадрировать».
    cropApplied = _api.pyqtSignal()
    cropCancelled = _api.pyqtSignal()
    # Предпросмотр привязки к объекту снят с холста (Esc). Рендер в файл делает
    # обычная кнопка экспорта «Обрезать» — отдельной кнопки «Применить» нет.
    trackCancelled = _api.pyqtSignal()
    # Наложенные картинки: состав списка изменился (добавили/удалили) либо слой
    # подвинули/растянули/повернули мышью — вкладка обновляет список слоёв.
    overlaysChanged = _api.pyqtSignal()
    overlaySelected = _api.pyqtSignal(int)

    from si_hyx_parts.edit_tab_widgets.painted_video_canvas___init import (
        __init__,
        set_crop_mode,
        set_scrub_active,
        set_playing,
        has_crop,
        crop_norm,
        apply_crop,
        cancel_crop,
        _widget_to_norm,
        _crop_rect_screen,
        _crop_handle_at,
        _crop_cursor,
        _drag_crop,
        set_track_preview,
        has_track_preview,
        set_track_time,
    )

    from si_hyx_parts.edit_tab_widgets.painted_video_canvas__track_overlay_rect import (
        _track_overlay_rect,
        _paint_track_preview,
        image_overlays,
        has_image_overlays,
        add_image_overlay,
        remove_image_overlay,
        clear_image_overlays,
        selected_overlay_index,
        set_selected_overlay,
        set_overlay_edit,
        _ovl_rect_screen,
        _ovl_transform,
        _ovl_hit,
        _ovl_cursor,
        _ovl_drag_to,
        _paint_image_overlays,
    )

    from si_hyx_parts.edit_tab_widgets.painted_video_canvas__update_crop_buttons import (
        _update_crop_buttons,
        resizeEvent,
        keyPressEvent,
        videoSink,
        setAspectRatioMode,
        clear_frame,
        set_static_image,
        current_frame_image,
        set_audio_only_message,
        reset_view,
        _has_frame,
        _frame_size,
        _base_video_rect,
        _clamp_pan,
        wheelEvent,
        mousePressEvent,
        mouseMoveEvent,
    )

    from si_hyx_parts.edit_tab_widgets.painted_video_canvas_mouse_release_event import (
        mouseReleaseEvent,
        set_play_bound,
        arm_frame_pin,
        set_exact_frame,
        clear_frame_pin,
        has_frame_pin,
        pinned_frame_pts,
        last_frame_pts,
        frame_clock_age,
        _on_frame,
        _paint_crop_overlay,
        _paint_crop_indicator,
        video_rect,
        subtitle_area_size,
        set_subtitle_image,
        set_subtitle_text,
        clear_subtitle,
        _paint_overlays,
        _paint_audio_only,
    )

    from si_hyx_parts.edit_tab_widgets.painted_video_canvas_paint_event import paintEvent

_PaintedVideoCanvas.__module__ = _api.__name__
_api._PaintedVideoCanvas = _PaintedVideoCanvas
