# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_qt_message_filter. Public namespace: main."""
import main as _api


def _qt_message_filter(mode, context, message):
    for noise in _api._QT_LOG_NOISE:
        if noise in message:
            return
    try:
        if _api.sys.stderr is not None:
            _api.sys.stderr.write(message + "\n")
            _api.sys.stderr.flush()
    except Exception:
        pass

_qt_message_filter.__module__ = _api.__name__
_api._qt_message_filter = _qt_message_filter

class UnifiedWindow(_api.QMainWindow):
    url_from_browser = _api.pyqtSignal(str, bool)  # URL + audio_only из браузерного расширения (HTTP-сервер → Qt)
    log_signal = _api.pyqtSignal(str)              # потокобезопасный лог (из фоновых потоков → GUI)
    update_available_sig = _api.pyqtSignal(str, str, int, str, str)  # версия, ссылка на zip, размер (байт), sha256 архива ("" = не проверять), ченжлог
    update_ready_sig = _api.pyqtSignal(str)        # путь к распакованной новой версии (готово к установке)
    ffmpeg_missing_sig = _api.pyqtSignal()         # проверка ffmpeg в фоне не прошла (из потока → GUI)

    from si_hyx_parts.main.unified_window_get_icon import get_icon

    from si_hyx_parts.main.unified_window___init import __init__

    from si_hyx_parts.main.unified_window__build_deferred_tabs_step import (
        _build_deferred_tabs_step,
        _check_ffmpeg_async,
        _on_ffmpeg_missing,
        add_paths,
        _load_settings,
        _on_ipc_connection,
        _on_ipc_data,
        _on_url_from_browser,
    )

    from si_hyx_parts.main.unified_window__start_browser_http_server import (
        _start_browser_http_server,
        _stop_browser_http_server,
        _set_server_enabled,
        _set_wheel_changes_values,
        _set_video_hw_decode,
        _set_advanced_encode_visible,
        _set_keep_models_in_ram,
        get_api_key,
        set_api_key,
    )

    from si_hyx_parts.main.unified_window__add_tab import (
        _add_tab,
        _on_tab_moved,
        _save_tab_order,
        _apply_tab_order,
        _add_prompt_tab,
        _remove_prompt_tab,
        _set_prompt_tab_enabled,
        _add_siquester_tab,
        _remove_siquester_tab,
        _set_siquester_tab_enabled,
        _add_shikimori_tab,
        _remove_shikimori_tab,
        _set_shikimori_tab_enabled,
        _collect_shikimori_settings,
        _add_leaderboard_tab,
        _remove_leaderboard_tab,
        _set_leaderboard_tab_enabled,
        _add_coop_tab,
        _remove_coop_tab,
        _set_coop_tab_enabled,
        _collect_coop_settings,
    )

    from si_hyx_parts.main.unified_window__add_animepack_tab import (
        _add_animepack_tab,
        _remove_animepack_tab,
        _set_animepack_tab_enabled,
        _collect_animepack_settings,
        _add_animepack_upgrade_tab,
        _remove_animepack_upgrade_tab,
        _set_animepack_upgrade_tab_enabled,
        _collect_animepack_upgrade_settings,
        _update_ytdlp,
        _check_updates,
        _local_bin_sha,
        _pick_update_asset,
        _skip_file,
        _load_skipped_version,
    )

    from si_hyx_parts.main.unified_window__save_skipped_version import (
        _save_skipped_version,
        _on_banner_skip,
        _on_update_available,
        _on_banner_update,
        _show_changelog,
        _start_update_download,
        _find_exe_root,
        _apply_update,
    )

    from si_hyx_parts.main.unified_window__spawn_updater import _spawn_updater

    from si_hyx_parts.main.unified_window__open_settings_dialog import _open_settings_dialog

    from si_hyx_parts.main.unified_window__collect_settings import (
        _collect_settings,
        _warn_settings_readonly,
        _save_settings_now,
        _save_settings_soon,
        _attach_save_handlers,
        dragEnterEvent,
        dropEvent,
        update_global_progress,
        _tb_hwnd,
        set_taskbar_progress,
        clear_taskbar_progress,
        _sync_console_visibility,
        _on_tab_bar_clicked,
        eventFilter,
    )

    from si_hyx_parts.main.global_result import (
        _position_progress_button,
        set_global_result,
        clear_global_result,
        _open_global_result,
    )

    from si_hyx_parts.main.unified_window__style_tab_scroll_buttons import (
        _style_tab_scroll_buttons,
        _tab_wheel_scroll,
        _tab_drag_has_files,
        _tab_drag_hover,
        _tab_drag_switch,
        _tab_drag_drop,
        _update_tab_tip,
        _hide_tab_tip,
        _reposition_console_btn,
        _open_console_window,
        _log_context_menu,
        log,
        log_gap,
        _stop_worker,
        closeEvent,
    )

UnifiedWindow.__module__ = _api.__name__
_api.UnifiedWindow = UnifiedWindow

def _install_crash_handler():
    """Глобальный обработчик необработанных исключений: пишет трейсбек в
    crash.log, показывает пользователю диалог с ошибкой и аккуратно завершает
    программу. Так падение не «исчезает в никуда», а видно пользователю."""
    import traceback as _tb
    import datetime as _dt
    crash_log = _api.os.path.join(_api.CONFIG_DIR, "crash.log")
    _already = {"shown": False}

    def _handle(exc_type, exc_value, exc_tb):
        # Ctrl+C — стандартное поведение, не показываем диалог
        if issubclass(exc_type, KeyboardInterrupt):
            _api.sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_text = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        # Защита от рекурсии: если падение случилось при показе диалога
        if _already["shown"]:
            try:
                _api.sys.stderr.write(tb_text)
            except Exception:
                pass
            _api.os._exit(1)
        _already["shown"] = True
        try:
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\n===== {_dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
                f.write(tb_text)
        except Exception:
            pass
        try:
            if _api.sys.stderr is not None:
                _api.sys.stderr.write(tb_text)
                _api.sys.stderr.flush()
        except Exception:
            pass
        try:
            from error_report import ErrorReportDialog
            dlg = ErrorReportDialog(
                "SI-HYX — критическая ошибка",
                "Произошла непредвиденная ошибка, программа будет закрыта.",
                detail=f"{exc_type.__name__}: {exc_value}",
                where="Критическая ошибка (краш)",
                report_detail=tb_text)
            try:
                if _api.APP_ICON:
                    dlg.setWindowIcon(_api.QIcon(_api.APP_ICON))
            except Exception:
                pass
            dlg.exec()
        except Exception:
            try:
                from PyQt6.QtWidgets import QMessageBox
                box = QMessageBox()
                box.setIcon(QMessageBox.Icon.Critical)
                box.setWindowTitle("SI-HYX — критическая ошибка")
                box.setText("Произошла непредвиденная ошибка, программа будет закрыта.")
                box.setInformativeText(f"{exc_type.__name__}: {exc_value}")
                box.setDetailedText(tb_text)
                box.exec()
            except Exception:
                pass
        _api.os._exit(1)

    _api.sys.excepthook = _handle

_install_crash_handler.__module__ = _api.__name__
_api._install_crash_handler = _install_crash_handler
