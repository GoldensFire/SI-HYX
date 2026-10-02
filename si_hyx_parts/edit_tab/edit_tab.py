# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab. Public namespace: edit_tab."""
import edit_tab as _api


# ─── Edit Tab ─────────────────────────────────────────────────────────────────
class EditTab(_api.QWidget):
    # Боковая панель монтажа: кнопки масштабируются под ровно столько значков в высоту.
    _MSIDE_COUNT = 8
    _MSIDE_GAP = 6

    from si_hyx_parts.edit_tab.edit_tab___init import (
        __init__,
        _build_unavailable_ui,
        init_ui,
        _build_root_layout,
    )

    from si_hyx_parts.edit_tab.edit_tab__build_sidebar import _build_sidebar, _build_quality_card

    from si_hyx_parts.edit_tab.edit_tab__build_proxy_card import (
        _build_proxy_card,
        _build_cut_summary,
    )

    from si_hyx_parts.edit_tab.edit_tab__build_center_area import _build_center_area

    from si_hyx_parts.edit_tab.edit_tab__build_player_bar import _build_player_bar

    from si_hyx_parts.edit_tab.edit_tab__build_timeline_panel import (
        _build_timeline_panel,
        _slider_style,
        apply_theme,
        _install_wheel_scroll,
        _on_cut_progress,
        _report_cut,
        _set_cut_status,
        _clear_cut_status,
        _make_temp_out,
        _move_tolerant,
        _replace_tolerant,
    )

    from si_hyx_parts.edit_tab.edit_tab__notify_busy_rename import (
        _notify_busy_rename,
        _fmt_mmss,
        _report_progress,
        _read_subs_in_frame_pref,
        _build_video_output,
        _prepare_sub_display,
        _hide_sub_display,
        _adjust_video_height,
        resizeEvent,
        showEvent,
        hideEvent,
        _adjust_video_aspect_once,
        enable_global_drag_drop,
    )

    from si_hyx_parts.edit_tab.edit_tab_event_filter import (
        eventFilter,
        _choose_export_dir,
        _reset_export_dir,
        _update_export_dir_label,
        _fmt_bitrate,
        _track_label,
        _populate_track_combos,
        on_audio_track_changed,
        _update_audio_info_labels,
        _probe_audio_stream,
    )

    from si_hyx_parts.edit_tab.edit_tab_audio_off import (
        _set_audio_disabled,
        _add_audio_off_entry,
        _external_audio_insert_at,
    )

    # ── Внешняя озвучка (отдельный аудиофайл, синхронный с видео) ──────────────
    _SUB_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.sub')
    _AUDIO_EXTS = ('.mp3', '.aac', '.m4a', '.ac3', '.eac3', '.flac', '.wav',
                   '.opus', '.ogg', '.dts', '.mka', '.wma')

    from si_hyx_parts.edit_tab.edit_tab__ensure_ext_audio_player import (
        _ensure_ext_audio_player,
        _set_external_audio,
        _on_ext_audio_status,
        _ext_audio_seek,
        _ext_audio_set_state,
        _clear_external_audio,
    )

    # Типовые названия папок с субтитрами — подпапка с таким именем считается
    # «своей» для видео даже если её имя не перекликается со стемом файла.
    _SUB_FOLDER_NAMES = {'subs', 'sub', 'subtitles', 'subtitle', 'ass', 'srt',
                          'субтитры', 'сабы'}

    from si_hyx_parts.edit_tab.edit_tab__path_relates_to_stem import (
        _path_relates_to_stem,
        _scan_external_subs,
        _expand_external_subs,
        _populate_track_combos_subs_only,
        _sort_external_subs,
        find_external_subs,
        find_external_audio,
        _add_external_sub,
        _cues_to_srt,
        _current_subs_as_srt,
        _extract_srt_for_entry,
        edit_subtitles,
    )

    from si_hyx_parts.edit_tab.edit_tab_create_subtitles import (
        create_subtitles,
        _add_external_audio,
    )

    # Битмап-субтитры (картинками) свой оверлей рисовать не умеет — для них
    # оставляем встроенный рендер QtMultimedia.
    _BITMAP_SUB_CODECS = {
        'hdmv_pgs_subtitle', 'pgssub', 'dvd_subtitle', 'dvdsub',
        'dvb_subtitle', 'dvbsub', 'xsub',
    }

    from si_hyx_parts.edit_tab.edit_tab__ensure_overlay import (
        _ensure_overlay,
        _on_focus_window_changed,
        _on_app_state_changed,
        _position_overlay,
        _reparent_overlay,
        on_sub_track_changed,
        _reopen_subs_popup,
        _stop_sub_extractor,
        _stop_ass,
        _ensure_ass_timer,
        _on_ass_tick,
        _on_ass_extracted,
        _on_sub_cues,
        _subtitle_at,
    )

    from si_hyx_parts.edit_tab.edit_tab__update_subtitle import (
        _update_subtitle,
        _apply_active_tracks,
        open_file,
        clear_file,
        accept_dropped_paths,
    )

    from si_hyx_parts.edit_tab.edit_tab_load_file import (
        load_file,
        _load_still_image,
        _pb_quality_scale,
        _pick_av_streams,
        _parse_fps,
        _proxy_scale_for,
        _proxy_limit_sec,
    )

    from si_hyx_parts.edit_tab.edit_tab_create_proxy_for_preview import (
        create_proxy_for_preview,
        on_proxy_ready,
        _on_pb_quality_changed,
        _on_pb_proxy_progress,
        _on_pb_proxy_ready,
        _swap_player_source,
        _set_player_file,
        _close_play_device,
        finish_loading_file,
        _prime_scrub_audio,
    )

    from si_hyx_parts.edit_tab.edit_tab__grab_kbd_focus import (
        _grab_kbd_focus,
        start_waveform_loading,
        _file_cache_stamp,
        _start_waveform,
        _on_waveform_progress,
        on_waveform_partial_ready,
        on_waveform_ready,
        push_undo,
        undo,
        redo,
        _set_frame_spins,
        set_in_out,
        set_in_point,
        set_out_point,
        on_in_frame_changed,
        on_out_frame_changed,
        on_wave_seek,
        on_wave_playseek,
        on_wave_selection_changed,
        update_selection_label,
        _resize_montage_side_btns,
        _relax_width,
        _update_total_time,
    )

    from si_hyx_parts.edit_tab.edit_tab_on_player_duration_changed import (
        on_player_duration_changed,
        _update_seg_duration,
        on_position_changed,
        _update_meter,
        _effective_out_s,
        _set_play_bound,
        _on_play_boundary,
        sync_ui,
        on_slider_moved,
        seek_to,
        _on_scrub_idle,
        toggle_play,
        stop_playback,
    )

    # Сколько миллисекунд играем ДО целевой точки при прогреве («разбег»).
    # Замерено на живых файлах: после перемотки QtMultimedia раскручивает
    # конвейер ~300 мс, и ВСЁ это время часы плеера стоят, а потом одним скачком
    # догоняют реальное время. С коротким разбегом (было 140 мс) этот скачок
    # перелетал цель на 240–540 мс, из-за чего прогрев всегда заканчивался
    # обратной перемоткой — то есть ровно тем, чего он и должен избегать
    # (см. _preroll_finish). 500 мс разбега скачок поглощают: промах падает до
    # ±40 мс, обратной перемотки не остаётся вовсе.
    _PREROLL_LEAD_MS = 500
    # Короче этого разбег бессмыслен и ОПАСЕН: play() и pause() попадают в один
    # такт, и пауза теряется (см. _preroll_at).
    _PREROLL_MIN_LEAD_MS = 120
    # Как часто щупаем позицию во время разбега. Сигнал positionChanged приходит
    # раз в ~50 мс — этого мало: за такт плеер успевал уехать за цель дальше, чем
    # на кадр, и снова включалась обратная перемотка. Свой таймер на 5 мс ловит
    # цель настолько рано, насколько плеер вообще о ней сообщает.
    _PREROLL_POLL_MS = 5
    # Упреждение: тормозим чуть РАНЬШЕ цели — промахнуться назад безопаснее
    # (ничего не теряется), чем вперёд.
    _PREROLL_GUARD_MS = 8
    # Промах больше этого правим перемоткой, меньше — оставляем как есть.
    # Цена перемотки — ~350 мс тишины на старте (аудио-конвейер после seek'а
    # поднимается только на play(), проверено: пауза любой длины его не греет).
    # Цена промаха — столько же миллисекунд, срезанных со старта отрезка, причём
    # на экране всё равно пришпилен точный кадр цели. 80 мс — верх реального
    # разброса с разбегом 500 мс.
    _PREROLL_SNAP_MS = 80
    # Нажали «Воспроизвести» ПОСРЕДИ разбега и до цели осталось не больше этого —
    # не перематываем (это остудило бы звук), а доигрываем разбег под mute и
    # снимаем mute ровно на цели. Дальше этого порога ждать дольше, чем стоит
    # перемотка, — тогда перематываем.
    _PREROLL_HANDOFF_MS = 250
    # Через сколько после pause() возвращать звук. Пауза останавливает подачу
    # сэмплов, но устройство доигрывает уже принятую очередь, а mute у
    # ffmpeg-бэкенда гасит выход сессии, а не её вход: снятый сразу mute
    # открывал этот хвост, и покадровый шаг звучал дважды. Замер щупом WASAPI
    # (пик аудиосессии процесса): хвост держится до +200 мс после pause,
    # с задержкой 250 мс слышимых замеров не остаётся вовсе.
    _PREROLL_UNMUTE_MS = 260
    # Как часто во время серии покадровых шагов подтягивать ПЛЕЕР к выбранному
    # кадру. Картинку на шаге даёт предекодер, звук — скраббер, поэтому плееру
    # каждый шаг не нужен, а его setPosition на тяжёлом источнике — полная
    # раскрутка GOP (см. _dispatch_frame_seek). Итоговую позицию серии досылает
    # _flush_frame_seek, так что «Воспроизвести» стартует там, где стоит монтаж.
    _SCRUB_SEEK_MS = 250

    from si_hyx_parts.edit_tab.edit_tab__playhead_target_s import (
        _playhead_target_s,
        _ui_pinned_ms,
        _ui_time_s,
        _preroll_at,
        _preroll_cancel,
        _restore_preroll_mute,
        _finish_preroll_unmute,
        _flush_preroll_mute,
        _preroll_timer,
        _preroll_tick,
        _preroll_watch,
        _preroll_handoff_finish,
        _preroll_finish,
        _release_frame_lock,
    )

    from si_hyx_parts.edit_tab.edit_tab_on_playback_changed import (
        on_playback_changed,
        on_media_status_changed,
        toggle_mute,
        _on_volume_changed,
        _update_media_buttons,
        _toggle_audio_only,
        _apply_audio_only_to_player,
        _update_audio_only_placeholder,
    )

    from si_hyx_parts.edit_tab.edit_tab__update_mode_combo_for_media import (
        _update_mode_combo_for_media,
        _toggle_frame_crop,
        _toggle_pixelize,
        _sync_pixelize_icon,
        _video_pixelize_filter,
        _on_crop_applied,
        _on_crop_cancelled,
        _video_crop_filter,
        _overlay_frame_size,
        image_overlays,
        has_image_overlays,
        add_image_overlay,
        _refresh_overlay_panel,
        _on_overlays_changed,
        _on_overlay_picked,
        _on_overlay_selected,
        _delete_image_overlay,
        _set_overlay_opacity,
    )

    from si_hyx_parts.edit_tab.edit_tab__reset_image_overlay import (
        _reset_image_overlay,
        _crop_image_overlay,
        _clear_image_overlays,
        _render_export_overlays,
        _paint_overlays_on_image,
        _static_overlays_bgra,
        _wrap_vf,
        _overlay_pix_fmt,
        _apply_frame_crop,
        save_frame,
        _ensure_inpainter,
        _grab_source_frame_bgr,
    )

    from si_hyx_parts.edit_tab.edit_tab_remove_object_from_video import (
        remove_object_from_video,
        _set_remove_btn_cancel,
        _set_cut_btn_cancel,
        _cancel_cut,
        _cancel_cut_and_process,
        _cancel_video_inpaint,
        _on_vinp_progress,
        _finish_video_inpaint,
        _on_vinp_done,
        _on_vinp_failed,
        track_object_overlay,
    )

    from si_hyx_parts.edit_tab.edit_tab__on_track_path_ready import (
        _on_track_path_ready,
        _connect_track_preview_signals,
        has_track_preview,
        _clear_track_preview,
        _render_track_overlay,
        _cancel_track_overlay,
        _on_trk_progress,
        _set_track_export_busy,
        _finish_track_overlay,
        _on_trk_done,
        _on_trk_failed,
        delete_source_file,
        toggle_fullscreen,
        enter_fullscreen,
    )

    from si_hyx_parts.edit_tab.edit_tab_exit_fullscreen import (
        exit_fullscreen,
        _restore_canvas_frame,
        _fs_sync_position,
        _frames_engine,
        _frames_set_source,
        _refresh_frame_grid,
        _current_frame_index,
        _clock_pos_s,
        _show_exact_frame,
        _paint_playhead,
        _on_exact_frame,
        step_frame,
        _dispatch_frame_seek,
        _flush_frame_seek,
        _send_frame_seek,
    )

    from si_hyx_parts.edit_tab.edit_tab__confirm_frame_seek import (
        _confirm_frame_seek,
        _release_frame_seek,
        step_frame_scrub,
        _end_scrub_painted,
    )

    # ── Скраб-звук при покадровой перемотке ─────────────────────────────────
    # Длина «блипа»: кадр, но не короче — на 60 fps один кадр (16.7 мс) на слух
    # почти щелчок. При удержании клавиши срезы идут подряд и складываются в
    # непрерывную перемотку по звуку, как в монтажках.
    _SCRUB_BLIP_MIN_S = 0.045
    _SCRUB_BLIP_MAX_S = 0.120

    from si_hyx_parts.edit_tab.edit_tab__scrub_audio_engine import (
        _scrub_audio_engine,
        _scrub_audio_source,
        _sync_scrub_audio_source,
        _scrub_sink_format,
        _scrub_sink,
        _scrub_volume,
        _scrub_blip_seconds,
        _scrub_audio_time_s,
        _scrub_audio_blip,
        _on_scrub_audio_window,
        _play_scrub_slice,
        _release_scrub_sink,
        _end_scrub,
        _available_encoders,
        _gpu_encoder_args,
    )

    from si_hyx_parts.edit_tab.edit_tab__video_encoder_args import (
        _video_encoder_args,
        _subs_present_in_range,
        start_cut,
        _export_still_pixelize,
    )

    from si_hyx_parts.edit_tab.edit_tab__subtitles_vf import (
        _subtitles_vf,
        _burn_subs_spec,
    )

    from si_hyx_parts.edit_tab.edit_tab__execute_cut import _execute_cut

    from si_hyx_parts.edit_tab.edit_tab__smartcut_status import (
        _smartcut_status,
        _execute_smartcut,
        _process_tab_encodes_video,
        _execute_cut_and_process,
    )

    from si_hyx_parts.edit_tab.edit_tab_on_ffmpeg_finished import (
        on_ffmpeg_finished,
        _escape_filter_path,
        _extract_subtitle_fonts,
        _discard_temp_cut,
        _show_cut_choice_dialog,
        _notify_cut_accuracy,
    )

    from si_hyx_parts.edit_tab.edit_tab_register_shortcuts import register_shortcuts

    # Кириллица: QKeySequence-строкой ("Ctrl+Я"/"Ctrl+Н") её ловить нельзя —
    # QShortcut сопоставляет события по УЖЕ переведённому раскладкой Qt-коду
    # клавиши, а не по физической клавише, и вдобавок такая строка сама
    # ломала act_undo/act_redo неоднозначностью (см. комментарий выше). Единый
    # надёжный способ — как WASD-пан в фоторедакторе (tabs.py,
    # _pan_dir_from_event): читать ФИЗИЧЕСКУЮ клавишу через nativeVirtualKey
    # (Windows VK_Z=0x5A, VK_Y=0x59) — не зависит от раскладки. Событие сюда
    # доходит только если ни один QAction/QShortcut/дочерний виджет его не
    # поглотил раньше — для латиницы Ctrl+Z уже работает через act_undo выше,
    # это лишь докрывает случай, когда переведённый код клавиши не совпал.
    _VK_Z = 0x5A
    _VK_Y = 0x59
    _VK_W = 0x57
    _VK_A = 0x41
    _VK_S = 0x53
    _VK_D = 0x44
    _VK_F = 0x46
    _VK_I = 0x49
    _VK_O = 0x4F

    from si_hyx_parts.edit_tab.edit_tab_key_press_event import (
        keyPressEvent,
        trim_start_to_playhead,
        trim_end_to_playhead,
        _trim_ctx_menu,
        get_trim_shortcuts,
        set_trim_shortcuts,
        on_wave_view_changed,
        on_wave_scroll,
        update_wave_scroll,
        update_pan_slider_values,
        on_pan_moved,
        save_settings,
        load_settings,
    )

    from si_hyx_parts.edit_tab.entrance_actions import (
        _build_more_actions, _entrance_busy, _refresh_more_actions,
        create_entrance, _cancel_entrance, _finish_entrance,
        _on_entrance_done, _on_entrance_failed,
    )

    from si_hyx_parts.edit_tab.edit_tab_shutdown import shutdown, closeEvent

EditTab.__module__ = _api.__name__
_api.EditTab = EditTab
