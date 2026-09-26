# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""QuestionViewer. Public namespace: siquester.widgets_question."""
import siquester.widgets_question as _api


class QuestionViewer(_api.QWidget):
    edit_requested = _api.pyqtSignal(int, int, int)   # rnd_idx, theme_idx, price

    from si_hyx_parts.siquester.widgets_question.question_viewer___init import (
        __init__,
        mousePressEvent,
        _section_drag_enter,
        _section_drag_leave,
        show_question,
    )

    from si_hyx_parts.siquester.widgets_question.question_viewer__rebuild_answer_editor import (
        _rebuild_answer_editor,
    )

    from si_hyx_parts.siquester.widgets_question.question_viewer__on_edit_clicked import (
        _on_edit_clicked,
        _detect_section,
        contextMenuEvent,
        _add_text_item,
        _do_add_media,
        dragEnterEvent,
        dragMoveEvent,
        dragLeaveEvent,
        _highlight_section,
        _clear_section_highlights,
        dropEvent,
        _move_item_to_section,
        _stop_player,
        _clear_lay,
    )

    from si_hyx_parts.siquester.widgets_question.question_viewer__build_deletable_item import (
        _build_deletable_item,
    )

    from si_hyx_parts.siquester.widgets_question.question_viewer__fill_lay import _fill_lay

    from si_hyx_parts.siquester.widgets_question.question_viewer__build_item import (
        _build_item,
        _open_propagate_wrong_dialog,
    )

QuestionViewer.__module__ = _api.__name__
_api.QuestionViewer = QuestionViewer
