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


# Отключение источника до конца прогона (start_run): столько сетевых сбоев
# видео и ссылок без единого годного видео — и ещё столько же на каждое
# годное. У пользователя anikoto и anizone за прогон отдавали 0–2 видео на
# 6–34 сбоя («не уложился в 35 с», PoolTimeout), а пауза на 120 с лишь
# откладывала следующую попытку: каждый тайтл снова ждал их таймаутов.
RUN_OFF_FAILURES = 3


class ProviderHealth:
    def __init__(self, clock=time.monotonic, threshold=3, cooldown=120):
        self.clock, self.threshold, self.cooldown = clock, threshold, cooldown
        self.lock = threading.Lock()
        self.states = {}
        self.run_names = frozenset()
        self.run_counts = Counter()
        self.disabled = {}
        self.on_disable = None

    def start_run(self, names, on_disable=None):
        """Новый прогон: источники names можно отключить до его конца.

        Отключение действует только до следующего start_run — сеть у
        пользователя меняется (VPN), и навсегда хоронить источник нельзя."""
        with self.lock:
            self.run_names = frozenset(names)
            self.run_counts = Counter()
            self.disabled = {}
            self.on_disable = on_disable

    def end_run(self, on_disable=None):
        """Прогон закончен: его журнал больше не принимает сообщений."""
        with self.lock:
            if on_disable is None or self.on_disable == on_disable:
                self.on_disable = None

    def _run_verdict(self, name, kind, ok, network):
        """Учёт прогона; текст сообщения, если источник только что отключён."""
        if name not in self.run_names or name in self.disabled:
            return ""
        if kind == "media" and ok:
            self.run_counts[name, "ok"] += 1
        elif kind in ("media", "watch") and network:
            self.run_counts[name, "network"] += 1
        else:
            return ""
        good = self.run_counts[name, "ok"]
        bad = self.run_counts[name, "network"]
        if bad < RUN_OFF_FAILURES * (1 + good):
            return ""
        self.disabled[name] = f"сетевых сбоев {bad}, годных видео {good}"
        return (f"Источник {name} отключён до конца прогона: {self.disabled[name]} — "
                "дальше тайтлы его не ждут.")

    def _state(self, name, kind):
        return self.states.setdefault((name, kind), dict(
            consecutive=0, until=0, probing=False, counts=Counter()))

    def allow(self, name, kind):
        with self.lock:
            state = self._state(name, kind)
            if name in self.disabled:
                state["counts"]["paused"] += 1
                return False
            if state["until"]:
                if self.clock() < state["until"] or state["probing"]:
                    state["counts"]["paused"] += 1
                    return False
                state["probing"] = True
            state["counts"]["attempts"] += 1
            return True

    def result(self, name, kind, *, ok=False, error=None):
        notice, callback, fresh = "", None, False
        try:
            with self.lock:
                network = not ok and network_failure(error)
                notice = self._run_verdict(name, kind, ok, network)
                callback = self.on_disable
                fresh = self._result(name, kind, ok, error, network)
                return fresh
        finally:
            # Журнал — вне замка: обработчик сообщения не должен ждать здоровья.
            if notice and callback is not None:
                try:
                    callback(notice)
                except Exception:  # noqa: BLE001 — журнал не роняет загрузку
                    pass

    def _result(self, name, kind, ok, error, network):
        state = self._state(name, kind)
        state["probing"] = False
        state["counts"]["ok" if ok else "network" if network else "missing"] += 1
        if ok or not network:
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
            if name in self.disabled:
                return True
            state = self.states.get((name, kind))
            return bool(state and (self.clock() < state["until"] or state["probing"]))

    def is_disabled(self, name):
        """Отключён ли источник до конца прогона (start_run)."""
        with self.lock:
            return name in self.disabled

    def cancelled(self, name, kind):
        with self.lock:
            self._state(name, kind)["probing"] = False

    def snapshot(self):
        with self.lock:
            return {key: dict(state["counts"]) for key, state in self.states.items()}


HEALTH = ProviderHealth()
