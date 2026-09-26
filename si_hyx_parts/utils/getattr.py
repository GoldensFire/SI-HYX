# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""__getattr__. Public namespace: utils."""
import utils as _api


def __getattr__(name):
    # requests подключается лениво (см. config._requests): на старте он никому не
    # нужен, а стоил ~240 мс до появления окна. Хук оставляет привычным
    # `utils.requests` — им пользуются тесты, подменяя requests.Session.
    # Внутри самого utils зовите _requests(), а не глобальное имя.
    if name == "requests":
        return _api._requests()
    raise AttributeError(f"module {_api.__name__!r} has no attribute {name!r}")

__getattr__.__module__ = _api.__name__
_api.__getattr__ = __getattr__
