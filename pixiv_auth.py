# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Pixiv: сбой сети — не отказ ключа.

Раньше любое исключение при входе писалось как «Pixiv не принял refresh
token», род вопросов «Pixiv-арт» объявлялся мёртвым, а при «сохранять состав»
пак обрывался на третьем вопросе (живой прогон: 3 из 144 за 68 секунд при
потерях пакетов). Теперь отказом ключа считается только ответ Pixiv
400/401/403, а сетевой сбой повторяется и роняет лишь один тайтл.
"""
from __future__ import annotations

import re
import time

from pixiv_art_api import PixivArtError, PixivArtUnavailable

# Паузы между попытками входа: три попытки укладываются в ~15 секунд.
AUTH_PAUSES = (3, 10)
# Сколько сетевых срывов подряд, без единой удачи, означают «Pixiv лежит», а не
# «сеть моргнула». Срыв входа — это уже три попытки подряд.
DOWN_AFTER = 5


class PixivNetworkError(PixivArtError):
    """Pixiv не ответил: тайтл не виноват, его можно повторить позже."""


def rejected(error) -> bool:
    """Pixiv ответил и отказал (ключ отозван или неверен)."""
    match = re.search(r"HTTP (\d{3})", str(error))
    return bool(match) and match.group(1) in ("400", "401", "403")


def _short(error) -> str:
    text = " ".join(str(error).split())
    return text[:160] or type(error).__name__


def _pause(client, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if client.stopped():
            raise PixivArtError("Загрузка арта Pixiv остановлена.")
        time.sleep(0.25)


def succeeded(client):
    client._network_failures = 0


def network_failure(client, message):
    """Сетевой срыв: тайтл пропускаем, род — только после череды срывов."""
    client._network_failures = getattr(client, "_network_failures", 0) + 1
    if client._network_failures >= DOWN_AFTER:
        raise PixivArtUnavailable(
            f"{message}. Pixiv не отвечает {DOWN_AFTER} раз подряд — "
            "арты Pixiv в этом прогоне пропускаю.")
    raise PixivNetworkError(message + " — тайтл повторю позже.")


def authenticate(client):
    last = None
    for attempt in range(len(AUTH_PAUSES) + 1):
        if client.stopped():
            raise PixivArtError("Загрузка арта Pixiv остановлена.")
        try:
            client.api.auth(refresh_token=client.refresh_token)
            succeeded(client)
            return
        except Exception as error:  # noqa: BLE001 — PixivPy заворачивает всё в PixivError
            if rejected(error):
                raise PixivArtUnavailable(
                    "Pixiv не принял refresh token — обновите его в "
                    "Настройках → Ключи API.") from None
            last = error
        if attempt < len(AUTH_PAUSES):
            _pause(client, AUTH_PAUSES[attempt])
    network_failure(client, f"Pixiv не ответил при входе: {_short(last)}")
