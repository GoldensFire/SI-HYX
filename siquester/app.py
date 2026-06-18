"""Application entry point: builds QApplication and shows MainWindow."""

from .qt import *
from .constants import *
from .main_window import *

def main():
    import traceback as _tb, sys as _sys_eh
    def _excepthook(exc_type, exc_value, exc_tb):
        msg = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        print("CRASH:\n" + msg, flush=True)
        try:
            from PyQt6.QtWidgets import QMessageBox, QApplication
            if QApplication.instance():
                mb = QMessageBox()
                mb.setWindowTitle("Ошибка")
                mb.setText(str(exc_value))
                mb.setDetailedText(msg)
                mb.exec()
        except Exception:
            pass
    _sys_eh.excepthook = _excepthook

    os.environ.setdefault("QT_LOGGING_RULES",
        "qt.multimedia.ffmpeg=false;qt.multimedia.player=false;qt.multimedia=false")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    import signal
    signal.signal(signal.SIGINT, lambda *_: os._exit(0))
    p = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window,          "#181825"),
        (QPalette.ColorRole.WindowText,      "#cdd6f4"),
        (QPalette.ColorRole.Base,            "#1e1e2e"),
        (QPalette.ColorRole.AlternateBase,   "#313244"),
        (QPalette.ColorRole.Text,            "#cdd6f4"),
        (QPalette.ColorRole.Button,          "#313244"),
        (QPalette.ColorRole.ButtonText,      "#cdd6f4"),
        (QPalette.ColorRole.Highlight,       "#89b4fa"),
        (QPalette.ColorRole.HighlightedText, "#181825"),
    ]:
        p.setColor(role, QColor(color))
    app.setPalette(p)
    from PyQt6.QtCore import qInstallMessageHandler
    def _qt_msg_handler(msg_type, context, message):
        if any(s in message for s in ("QThreadStorage", "destroyed before end of thread",
                                      "qt.multimedia", "DirectShow")):
            return
        print("[Qt]", message, flush=True)
    qInstallMessageHandler(_qt_msg_handler)
    try:
        w = MainWindow()
    except Exception:
        import traceback; traceback.print_exc(); return
    # Global shortcuts / click-outside are driven by MainWindow.eventFilter.
    # _build() no longer self-installs it (so the SI-HYX host can scope it to the
    # active tab) — for standalone use we install it here.
    QApplication.instance().installEventFilter(w)
    def _on_about_to_quit():
        try:
            for ds in getattr(w, "datasets", []):
                widget = ds.get("widget")
                if not widget:
                    continue
                for mw_item in getattr(widget, "_media_widgets", []):
                    try: mw_item.stop()
                    except Exception as _e: _logger.debug(str(_e))
                widget._media_widgets = []
        except Exception:
            pass
        _time.sleep(0.08)
    app.aboutToQuit.connect(_on_about_to_quit)
    w.showMaximized()
    sys.exit(app.exec())

__all__ = [
    'main',
]
