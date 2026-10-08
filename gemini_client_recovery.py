# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Let a client recover after its temporary model cooldowns expire."""
import gemini_api as _api


def fallback_chain(client, model: str) -> tuple[str, ...]:
    """Модели на замену model с учётом запрета Gemma у клиента."""
    choices = _api.fallback_models(model)
    if not getattr(client, "fallback_gemma", True):
        choices = tuple(name for name in choices if not _api.is_gemma(name))
    return choices


def recover(client):
    """Restore a live model without clearing daily quota or cooldown state."""
    recovered = ""
    with client._model_lock:
        if not client._terminal_down or client._terminal_quota:
            return False
        primary = getattr(client, "primary_model", client.model)
        choices = ((primary,) if not client.allow_model_fallback else
                   tuple(dict.fromkeys((primary, client.model)
                                       + fallback_chain(client, client.model))))
        available = next((model for model in choices
                          if not client.board.exhausted(model)
                          and not client.board.unavailable(model)), None)
        if available is None:
            return False
        client.model = available
        client.thinking = _api.thinking_level(client.thinking, available)
        client._interval = client._model_interval(available)
        client._terminal_down = ""
        recovered = available
    client.log(f"Gemini: временная перегрузка закончилась; снова пробую {recovered}.")
    return True
