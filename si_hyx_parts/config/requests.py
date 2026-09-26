# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_requests. Public namespace: config."""
import config as _api


def _requests():
    """Модуль requests: импортируем при первом обращении и запоминаем."""
    pass  # Shared state is addressed through _api.
    if _api._requests_mod is None:
        import requests as _r
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        _api._requests_mod = _r
    return _api._requests_mod

_requests.__module__ = _api.__name__
_api._requests = _requests

def __getattr__(name):
    # PEP 562: срабатывает только на `config.requests` извне модуля. Внутри
    # самого config всегда зовите _requests() — глобальные имена ищутся в
    # __dict__ напрямую, мимо этого хука.
    if name == "requests":
        return _api._requests()
    raise AttributeError(f"module {_api.__name__!r} has no attribute {name!r}")

__getattr__.__module__ = _api.__name__
_api.__getattr__ = __getattr__

class _Resp:
    """Минимальная обёртка над requests.Response для совместимости с кодом,
    который раньше работал с urllib: .read() / .read(n), .headers.get(),
    статус, и работа как контекст-менеджер (`with ... as r:`)."""
    def __init__(self, r):
        self._r = r
        self._it = None
        self.headers = r.headers
        self.status = r.status_code

    def read(self, amt=None):
        if amt is None:
            return self._r.content
        if self._it is None:
            self._it = self._r.iter_content(chunk_size=amt)
        try:
            return next(self._it)
        except StopIteration:
            return b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try: self._r.close()
        except Exception: pass

_Resp.__module__ = _api.__name__
_api._Resp = _Resp

def http_get(url, headers=None, timeout=30, stream=True, allow_insecure=True):
    """GET через requests с проверкой сертификата.
    allow_insecure=True: при SSL-ошибке повторяет без проверки (verify=False) —
    нужно для превью/картинок на машинах без системных CA.
    allow_insecure=False: повтора НЕТ, нужен валидный сертификат. Критично для
    автообновления: иначе MITM мог бы подсунуть вредоносный .exe (повтор без
    проверки = установка непроверенного кода = RCE).
    Возвращает _Resp (совместим со старым urllib-кодом)."""
    requests = _api._requests()
    h = headers or {}
    try:
        r = requests.get(url, headers=h, timeout=timeout, stream=stream)
        r.raise_for_status()
        return _api._Resp(r)
    except requests.exceptions.SSLError:
        if not allow_insecure:
            raise
        r = requests.get(url, headers=h, timeout=timeout, stream=stream, verify=False)
        r.raise_for_status()
        return _api._Resp(r)

http_get.__module__ = _api.__name__
_api.http_get = http_get
