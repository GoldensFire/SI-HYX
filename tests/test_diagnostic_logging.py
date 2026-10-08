"""Background Python and Qt diagnostics reach the same GUI signal."""
import logging
import threading
from types import SimpleNamespace

from diagnostic_logging import ConsoleHandler


def test_startup_and_worker_messages_reach_gui_signal_once():
    messages = []
    handler = ConsoleHandler()
    handler.publish("[Qt] startup")
    window = SimpleNamespace()
    # SimpleNamespace cannot be weak referenced; a normal GUI-like object can.
    class Window:
        log_signal = SimpleNamespace(emit=messages.append)
    window = Window()
    handler.bind(window)
    record = logging.LogRecord("urllib3", logging.WARNING, "", 0, "timeout", (), None)
    thread = threading.Thread(target=lambda: handler.emit(record))
    thread.start()
    thread.join()
    assert messages == ["[Qt] startup", "[WARNING] urllib3: timeout"]
