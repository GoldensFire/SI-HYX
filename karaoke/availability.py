"""Transient infrastructure failures are distinct from unsuitable lyrics."""
import requests


class TemporaryUnavailable(ValueError):
    pass


def temporary(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        status = getattr(error, "http_status", 0) or getattr(getattr(error, "response", None), "status_code", 0)
        if (isinstance(error, (TemporaryUnavailable, TimeoutError, ConnectionError,
                               requests.Timeout, requests.ConnectionError))
                or status == 429 or isinstance(status, int) and 500 <= status < 600):
            return True
        text = str(error).casefold()
        if any(word in text for word in ("временно на паузе", "таймаут", "timed out", "общий лимит времени")):
            return True
        error = error.__cause__ or error.__context__
    return False
