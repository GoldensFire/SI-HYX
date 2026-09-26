# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ResultPage. Public namespace: siquester.result_page."""
import siquester.result_page as _api


class ResultPage(_api.QWidget):

    from si_hyx_parts.siquester.result_page.result_page___init import (
        __init__,
        showEvent,
        _invalidate_fill_cache,
    )

    from si_hyx_parts.siquester.result_page.result_page__refresh_banner_widget import (
        _refresh_banner_widget,
        _mw_ref,
    )

    from si_hyx_parts.siquester.result_page.result_page_attach_siq import (
        attach_siq,
        _ensure_siq_view,
        _wasd_navigate,
        _mk_sep,
        _rebuild_content,
    )

    from si_hyx_parts.siquester.result_page.result_page__build_tile_view import _build_tile_view

    from si_hyx_parts.siquester.result_page.result_page__flush_tile_fills_sync import (
        _flush_tile_fills_sync,
        _start_tile_fill,
        _fill_tiles_chunk,
        _move_round,
        _add_theme,
        _move_tile_question,
        _on_question_clicked,
        _on_question_price_change,
        _on_delete_question_requested,
    )

    from si_hyx_parts.siquester.result_page.result_page__on_change_round_prices import (
        _on_change_round_prices,
        _delete_round,
        _delete_theme,
        _move_theme,
        _add_round,
        _on_edit_question_requested,
        _on_add_question_requested,
    )

    from si_hyx_parts.siquester.result_page.result_page__copy_all_answers_dialog import (
        _copy_all_answers_dialog,
        _save_siq_inplace,
    )

    # ── Undo / Redo ────────────────────────────────────────
    _MAX_UNDO = 40

    from si_hyx_parts.siquester.result_page.result_page__push_undo import (
        _push_undo,
        _snapshot_current,
        _apply_snapshot,
        do_undo,
        do_redo,
    )

ResultPage.__module__ = _api.__name__
_api.ResultPage = ResultPage
