"""Bound one visual call without changing the shared client's timeout or stop flag."""
from copy import copy
import math
import time


def call(client, parts, schema, deadlines):
    deadline = min((d for d in deadlines if d is not None), default=float("inf"))
    fields = ("_stopped", "timeout", "requests_made", "_model_lock", "model", "thinking")
    if not math.isfinite(deadline) or not all(hasattr(client, name) for name in fields):
        return client.generate_json(parts, schema, temperature=0.0)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Истекло время проверки сцены")
    request_client = copy(client)
    request_client.timeout = min(client.timeout, max(.1, remaining))
    request_client._stopped = lambda: client.stopped() or time.monotonic() >= deadline
    initial_model = client.model
    before = request_client.requests_made
    try:
        return request_client.generate_json(parts, schema, temperature=0.0)
    finally:
        with client._model_lock:
            client.requests_made += request_client.requests_made - before
            if client.model == initial_model:
                client.model, client.thinking = request_client.model, request_client.thinking
            for name in ("_terminal_quota", "_terminal_down"):
                if getattr(request_client, name, ""):
                    setattr(client, name, getattr(request_client, name))
