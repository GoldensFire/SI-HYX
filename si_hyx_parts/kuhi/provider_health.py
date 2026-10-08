"""Pause failing network providers; missing anime never disables a provider."""
from collections import Counter
import re
import ssl
import threading
import time

import httpx
import requests


def network_failure(error):
    status = getattr(getattr(error, "response", None), "status_code", 0)
    return (isinstance(error, (TimeoutError, ConnectionError, httpx.TransportError,
                              ssl.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout))
            or (isinstance(status, int) and (status in (403, 429) or 500 <= status < 600))
            or bool(re.search(r"\bHTTP\s+(?:403|429|5\d\d)\b", str(error), re.I)))


class ProviderHealth:
    def __init__(self, clock=time.monotonic, threshold=3, cooldown=120):
        self.clock, self.threshold, self.cooldown = clock, threshold, cooldown
        self.lock = threading.Lock()
        self.states = {}

    def _state(self, name, kind):
        return self.states.setdefault((name, kind), dict(
            consecutive=0, until=0, probing=False, counts=Counter()))

    def allow(self, name, kind):
        with self.lock:
            state = self._state(name, kind)
            if state["until"]:
                if self.clock() < state["until"] or state["probing"]:
                    state["counts"]["paused"] += 1
                    return False
                state["probing"] = True
            state["counts"]["attempts"] += 1
            return True

    def result(self, name, kind, *, ok=False, error=None):
        with self.lock:
            state = self._state(name, kind)
            state["probing"] = False
            state["counts"]["ok" if ok else "network" if network_failure(error) else "missing"] += 1
            if ok or not network_failure(error):
                state["consecutive"] = state["until"] = 0
                return False
            state["consecutive"] += 1
            certificate = isinstance(error, (ssl.SSLCertVerificationError, requests.exceptions.SSLError)) or "certificate verify failed" in str(error).casefold()
            if state["consecutive"] >= self.threshold or certificate:
                fresh = not state["until"] or self.clock() >= state["until"]
                state["until"] = self.clock() + (max(600, self.cooldown) if certificate else self.cooldown)
                return fresh
            return False

    def paused(self, name, kind):
        with self.lock:
            state = self.states.get((name, kind))
            return bool(state and (self.clock() < state["until"] or state["probing"]))

    def cancelled(self, name, kind):
        with self.lock:
            self._state(name, kind)["probing"] = False

    def snapshot(self):
        with self.lock:
            return {key: dict(state["counts"]) for key, state in self.states.items()}


HEALTH = ProviderHealth()
