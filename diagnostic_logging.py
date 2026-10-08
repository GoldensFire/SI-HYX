# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Bridge Python/Qt diagnostics to the GUI signal, buffering startup messages."""
from collections import deque
import logging
import threading
import weakref
from logging.handlers import RotatingFileHandler
import os
import html

_file = None


class ConsoleHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self._pending = deque(maxlen=1000)
        self._window = None
        self._guard = threading.RLock()

    def emit(self, record):
        message = f"[{record.levelname}] {record.name}: {record.getMessage()}"
        self.publish(message)

    def publish(self, message):
        with self._guard:
            window = self._window() if self._window is not None else None
            if window is None:
                self._pending.append(message)
                return
            try:
                window.log_signal.emit(html.escape(message))
            except RuntimeError:  # Qt window already destroyed
                self._window = None
                self._pending.append(message)

    def bind(self, window):
        with self._guard:
            self._window = weakref.ref(window)
            pending = list(self._pending)
            self._pending.clear()
            for message in pending:
                window.log_signal.emit(html.escape(message))


HANDLER = ConsoleHandler()


def install():
    root = logging.getLogger()
    if HANDLER not in root.handlers:
        root.addHandler(HANDLER)


def qt_message(message):
    HANDLER.publish(f"[Qt] {message}")


def bind(window):
    install()
    HANDLER.bind(window)


def start_file(directory):
    global _file
    if _file is not None:
        return
    try:
        os.makedirs(directory, exist_ok=True)
        _file = RotatingFileHandler(os.path.join(directory, "console.log"),
                                   maxBytes=4 << 20, backupCount=3, encoding="utf-8")
        _file.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    except OSError:
        _file = None


def archive(message):
    if _file is not None:
        _file.handle(logging.LogRecord("console", logging.INFO, "", 0, str(message), (), None))
