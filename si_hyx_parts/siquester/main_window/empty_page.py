# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EmptyPage. Public namespace: siquester.main_window."""
import siquester.main_window as _api


class EmptyPage(_api.QWidget):
    """Welcome screen — drag a .siq file here as the primary action."""
    siq_dropped = _api.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#181825;")
        self.setAcceptDrops(True)
        self._drag_over = False
        lay = _api.QVBoxLayout(self)
        lay.setAlignment(_api._AlignC)
        lay.setSpacing(16)

        # Drop zone frame
        self._frame = _api.QFrame()
        self._frame.setObjectName("drop_zone")
        self._frame.setFixedSize(480, 300)
        self._frame.setStyleSheet(_api._SS_DROP_ZONE_LG)
        frame_lay = _api.QVBoxLayout(self._frame)
        frame_lay.setAlignment(_api._AlignC)
        frame_lay.setSpacing(12)

        icon_lbl = _api.QLabel("📦")
        icon_lbl.setAlignment(_api._AlignC)
        icon_lbl.setStyleSheet("font-size:56px;background:transparent;border:none;")
        frame_lay.addWidget(icon_lbl)

        frame_lay.addWidget(_api._lbl(
            "Перетащите .siq файл сюда",
            "color:#cdd6f4;font-size:18px;font-weight:700;background:transparent;"
            "border:none;"))

        frame_lay.addWidget(_api._lbl(
            "или",
            "color:#585b70;font-size:13px;background:transparent;border:none;"))

        open_btn = _api.AnimatedButton("📂  Открыть .siq…")
        open_btn.setObjectName("btn_paste")
        open_btn.setFixedHeight(38)
        open_btn.clicked.connect(self._open_dialog)
        frame_lay.addWidget(open_btn)

        lay.addWidget(self._frame)
        lay.addWidget(_api._lbl(
            "Статистика подтягивается автоматически с SIStatistics при открытии пакета",
            "color:#585b70;font-size:11px;"))

    def _open_dialog(self):
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Открыть .siq файл", "", "SIGame Package (*.siq);;All (*)")
        if path:
            self.siq_dropped.emit(path)

    def dragEnterEvent(self, e):
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        if any(_api.os.path.splitext(u.toLocalFile())[1].lower() == ".siq" for u in urls):
            e.acceptProposedAction()
            self._drag_over = True
            self._frame.setStyleSheet(
                "QFrame#drop_zone{background:rgba(137,180,250,0.08);"
                "border:2px dashed #89b4fa;border-radius:16px;}")

    def dragLeaveEvent(self, e):
        self._drag_over = False
        self._frame.setStyleSheet(_api._SS_DROP_ZONE_LG)

    def dropEvent(self, e):
        self._drag_over = False
        self._frame.setStyleSheet(_api._SS_DROP_ZONE_LG)
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if _api.os.path.splitext(p)[1].lower() == '.siq':
                e.acceptProposedAction()
                self.siq_dropped.emit(p)
                return

EmptyPage.__module__ = _api.__name__
_api.EmptyPage = EmptyPage

class MainWindow(_api.QMainWindow):

    from si_hyx_parts.siquester.main_window.main_window___init import (
        __init__,
        showEvent,
        _build,
        _build_search_panel,
        _toggle_search,
        _toggle_media_search,
        _show_search,
        _hide_search,
        _show_media_search,
        _hide_media_search,
        _reposition_panels,
    )

    from si_hyx_parts.siquester.main_window.main_window__build_media_search_panel import (
        _build_media_search_panel,
        _run_media_search,
        _media_result_activated_data,
        _on_search_text_changed,
        _run_search,
    )

    from si_hyx_parts.siquester.main_window.main_window__search_result_activated import (
        _search_result_activated,
        eventFilter,
        _reposition_collapse_btn,
        _toggle_sidebar,
        _restart,
        _load_saved,
        _load_saved_step,
        _add_dataset,
        _show_ds,
    )

    from si_hyx_parts.siquester.main_window.main_window__open_siq_file import (
        _open_siq_file,
        _auto_fetch_stats,
        _apply_auto_stats,
        _show_save_notification,
        resizeEvent,
        dragEnterEvent,
        dragMoveEvent,
        dropEvent,
        _delete_ds,
        _on_reorder,
        _move_to_tab,
        _save_after_theme_move,
        _rename_pkg,
        _update_info,
        closeEvent,
    )

MainWindow.__module__ = _api.__name__
_api.MainWindow = MainWindow
