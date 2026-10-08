"""HTTP transport and retry policy for the public Gemini client."""
from __future__ import annotations

from typing import Any


def request_fault(text):
    value = str(text).casefold()
    if any(word in value for word in ("api key", "api_key", "permission", "authentication")):
        return False
    return any(word in value for word in ("schema", "response_format", "too many images",
                                         "request payload", "unsupported mime", "contents[",
                                         "maximum number", "size exceeds"))
