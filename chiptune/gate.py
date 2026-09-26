"""One ML operation across preview, downloads and separate app processes."""
from contextlib import contextmanager
from pathlib import Path
import os
import threading
import time

from .notes import QualityError

MODEL_GATE = threading.BoundedSemaphore(1)


def lock_file():
    return Path.home() / ".cache/si-hyx-chiptune/model.lock"


@contextmanager
def model_slot(stopped):
    while not MODEL_GATE.acquire(timeout=.2):
        if stopped():
            raise QualityError("Chiptune: остановлено.")
    locked = False
    stream = None
    try:
        path = lock_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("a+b")
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        while not locked:
            if stopped():
                raise QualityError("Chiptune: остановлено.")
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                time.sleep(.2)
        yield
    finally:
        if stream:
            if locked:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()
        MODEL_GATE.release()
