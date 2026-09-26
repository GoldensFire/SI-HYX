# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpTab. Public namespace: tabs."""
import tabs as _api


class YtdlpTab(_api.QWidget):
    thumb_sig = _api.pyqtSignal(str, _api.QIcon)
    kodik_info_sig = _api.pyqtSignal(object, int, str, int)  # (озвучки, число серий, тек.озвучка, тек.серия)

    from si_hyx_parts.tabs.ytdlp_tab___init import (
        __init__,
        setup_ui,
        _spin_to_sliders,
        _add_duration,
        _fill_time_boxes,
        _slider_to_spins,
    )

    from si_hyx_parts.tabs.ytdlp_tab__on_url_edited import (
        _on_url_edited,
        _start_fetch,
        _kodik_episode_value,
        _populate_kodik,
        _on_info_success,
        _populate_lang_combos,
        _on_info_error,
        _clear_timings,
        on_url_ctx,
        stop_all_dl,
        stop_sel_dl,
        ctx,
        _choose_cookie,
        ch_dir,
        get_sec,
        _connect_worker_signals,
        add_dl_direct,
    )

    from si_hyx_parts.tabs.ytdlp_tab_add_dl import (
        add_dl,
        _update_stop_btn,
        _update_dl_taskbar,
        _remove_worker,
        _dl_config,
        redownload_sel,
        delete_sel,
        set_thumb,
    )

YtdlpTab.__module__ = _api.__name__
_api.YtdlpTab = YtdlpTab

class MediaTab(_api.QWidget):
    thumb_sig = _api.pyqtSignal(str, _api.QIcon)
    media_info_sig = _api.pyqtSignal(str, str, str, float)  # iid, размер, битрейт, длительность(с)
    media_lufs_sig = _api.pyqtSignal(str, object)           # iid, LUFS до (или None)

    from si_hyx_parts.tabs.media_tab___init import (
        __init__,
        _find_item,
        setup_ui,
        _build_queue_and_panel,
        _build_audio_group,
    )

    from si_hyx_parts.tabs.media_tab__build_video_group import (
        _build_video_group,
        _build_images_group,
    )

    from si_hyx_parts.tabs.media_tab__build_footer import (
        _build_footer,
        _persist_priority,
        _size_profile_toggle_buttons,
        _set_preset_mode,
        _video_metric_value,
        _set_form_row_visible,
        set_advanced_encode_visible,
        _apply_advanced_encode_visibility,
        _video_tune_value,
        _set_tune_value,
        on_url_ctx,
        on_double_click,
        open_output_file,
        _choose_export_dir,
        _reset_export_dir,
        _update_export_label,
        download_url,
        _quick_dl_stop,
        reset_status,
        dragEnterEvent,
        dropEvent,
    )

    from si_hyx_parts.tabs.media_tab_ctx import ctx, open_file_location, paste_files

    _VK_V = 0x56

    from si_hyx_parts.tabs.media_tab_key_press_event import (
        keyPressEvent,
        add,
        add_paths,
        set_thumb,
        _apply_media_info,
        _apply_media_lufs,
        _set_pair,
        _fmt_dur,
        update_item_info,
        _on_compare_clicked,
        _compare_any_files,
        update_item_dur,
        update_item_xpsnr,
        update_lufs_columns,
        rem,
        clear,
        run,
    )

    from si_hyx_parts.tabs.media_tab__collect_settings import (
        _collect_settings,
        _settings_sync_tick,
        _run_items,
        stop,
    )

    _RE_IMG_PASS = _api.re.compile(r"картинки (\d+)/(\d+)")

    from si_hyx_parts.tabs.media_tab_on_stat import (
        on_stat,
        on_prog,
        _fmt_elapsed,
        _elapsed_text_for,
        _update_elapsed_text,
        _start_elapsed,
        _tick_elapsed,
        _freeze_elapsed,
        _on_active_threads,
        done,
    )

MediaTab.__module__ = _api.__name__
_api.MediaTab = MediaTab

class Base64Tab(_api.QWidget):
    """Вкладка кодирования любого файла в Base64."""
    _sig_done     = _api.pyqtSignal(str, str, str)   # b64, size_str, txt_path
    _sig_error    = _api.pyqtSignal(str)
    _sig_progress = _api.pyqtSignal(int)             # 0-100, только из фонового потока

    # Расширения и их иконки — имена значков qtawesome (см. get_icon в config.py).
    _ICON_MAP = {
        # Видео
        '.mp4': 'fa5s.film', '.mkv': 'fa5s.film', '.avi': 'fa5s.film', '.mov': 'fa5s.film', '.webm': 'fa5s.film',
        '.flv': 'fa5s.film', '.wmv': 'fa5s.film', '.m4v': 'fa5s.film', '.ts': 'fa5s.film', '.mts': 'fa5s.film',
        '.m2ts': 'fa5s.film', '.vob': 'fa5s.film', '.ogv': 'fa5s.film', '.3gp': 'fa5s.film', '.3g2': 'fa5s.film',
        '.divx': 'fa5s.film', '.f4v': 'fa5s.film', '.mxf': 'fa5s.film', '.rm': 'fa5s.film', '.rmvb': 'fa5s.film',
        # Аудио
        '.mp3': 'fa5s.music', '.opus': 'fa5s.music', '.wav': 'fa5s.music', '.flac': 'fa5s.music', '.ogg': 'fa5s.music',
        '.aac': 'fa5s.music', '.m4a': 'fa5s.music', '.wma': 'fa5s.music', '.aiff': 'fa5s.music', '.aif': 'fa5s.music',
        '.ape': 'fa5s.music', '.mka': 'fa5s.music', '.mid': 'fa5s.music', '.midi': 'fa5s.music', '.amr': 'fa5s.music',
        '.ac3': 'fa5s.music', '.dts': 'fa5s.music', '.ra': 'fa5s.music', '.au': 'fa5s.music',
        # 3D / Игровые ассеты
        '.glb': 'fa5s.cube', '.gltf': 'fa5s.cube', '.obj': 'fa5s.cube', '.fbx': 'fa5s.cube', '.dae': 'fa5s.cube',
        '.3ds': 'fa5s.cube', '.stl': 'fa5s.cube', '.ply': 'fa5s.cube', '.blend': 'fa5s.cube', '.usdz': 'fa5s.cube',
        '.usd': 'fa5s.cube', '.abc': 'fa5s.cube', '.x3d': 'fa5s.cube', '.vrml': 'fa5s.cube', '.wrl': 'fa5s.cube',
        # Изображения (будут показываться как превью)
        '.jpg': None, '.jpeg': None, '.png': None, '.gif': None, '.webp': None,
        '.bmp': None, '.tiff': None, '.tif': None, '.avif': None, '.heic': None,
        '.heif': None, '.ico': None, '.svg': 'fa5s.image',
        # Документы
        '.pdf': 'fa5s.file-alt', '.doc': 'fa5s.file-alt', '.docx': 'fa5s.file-alt', '.xls': 'fa5s.file-alt', '.xlsx': 'fa5s.file-alt',
        '.ppt': 'fa5s.file-alt', '.pptx': 'fa5s.file-alt', '.txt': 'fa5s.file-alt', '.rtf': 'fa5s.file-alt', '.odt': 'fa5s.file-alt',
        '.ods': 'fa5s.file-alt', '.odp': 'fa5s.file-alt', '.csv': 'fa5s.file-alt', '.md': 'fa5s.file-alt',
        # Архивы
        '.zip': 'fa5s.file-archive', '.rar': 'fa5s.file-archive', '.7z': 'fa5s.file-archive', '.tar': 'fa5s.file-archive', '.gz': 'fa5s.file-archive',
        '.bz2': 'fa5s.file-archive', '.xz': 'fa5s.file-archive', '.zst': 'fa5s.file-archive', '.lz4': 'fa5s.file-archive',
        # Шрифты
        '.ttf': 'fa5s.font', '.otf': 'fa5s.font', '.woff': 'fa5s.font', '.woff2': 'fa5s.font', '.eot': 'fa5s.font',
        # Код / данные
        '.json': 'fa5s.database', '.xml': 'fa5s.database', '.yaml': 'fa5s.database', '.yml': 'fa5s.database', '.toml': 'fa5s.database',
        '.bin': 'fa5s.database', '.dat': 'fa5s.database', '.db': 'fa5s.database', '.sqlite': 'fa5s.database', '.proto': 'fa5s.database',
        # Игровые / движковые форматы
        '.pak': 'fa5s.gamepad', '.vpk': 'fa5s.gamepad', '.bsp': 'fa5s.gamepad', '.mdl': 'fa5s.gamepad', '.vtf': 'fa5s.gamepad',
        '.vmt': 'fa5s.gamepad', '.prefab': 'fa5s.gamepad', '.asset': 'fa5s.gamepad', '.unity': 'fa5s.gamepad',
        # Прочее
        '.iso': 'fa5s.compact-disc', '.img': 'fa5s.compact-disc', '.dmg': 'fa5s.compact-disc',
    }

    from si_hyx_parts.tabs.base64_tab___init import (
        __init__,
        progress_update,
        add_paths,
        _is_html,
        _route_paths,
        _build_ui,
        dragEnterEvent,
        dragMoveEvent,
        dropEvent,
        _browse,
        _set_path,
        _load_thumb,
        _copy,
        _read_html,
    )

    from si_hyx_parts.tabs.base64_tab__mask_html import (
        _mask_html,
        _mask_html_action,
        _mask_one,
        _mask_paths,
        _mask_current_html,
        _mask_folder_html,
        _start_encode,
        _clear_result,
        _on_done,
        _on_error,
    )

Base64Tab.__module__ = _api.__name__
_api.Base64Tab = Base64Tab
