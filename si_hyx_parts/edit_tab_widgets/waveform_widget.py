# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""WaveformWidget. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


# ─── Waveform Widget ──────────────────────────────────────────────────────────
class WaveformWidget(_api.QWidget):
    seekRequested       = _api.pyqtSignal(float)
    playSeekRequested   = _api.pyqtSignal(float)
    inSetRequested      = _api.pyqtSignal(float)
    outSetRequested     = _api.pyqtSignal(float)
    selectionChanged    = _api.pyqtSignal(float, float)
    viewChanged         = _api.pyqtSignal(float, float)
    interactionStarted  = _api.pyqtSignal()

    from si_hyx_parts.edit_tab_widgets.waveform_widget___init import (
        __init__,
        _tick_anim,
        set_loading,
        _compute_display_samples,
        level_at,
        level_at_lr,
        set_data,
        set_partial_data,
        reset_markers,
        prime_duration,
        set_in_out,
        set_playhead,
        ensure_view_contains,
    )

    from si_hyx_parts.edit_tab_widgets.waveform_widget__draw_static import (
        _draw_static,
        paintEvent,
        mousePressEvent,
        mouseMoveEvent,
        mouseReleaseEvent,
        leaveEvent,
        hover_time_from_x,
        show_tooltip_for_pos,
    )

    from si_hyx_parts.edit_tab_widgets.waveform_widget_show_tooltip_at_global_pos import (
        show_tooltip_at_global_pos,
        wheelEvent,
        set_view_offset,
        set_zoom,
    )

WaveformWidget.__module__ = _api.__name__
_api.WaveformWidget = WaveformWidget
