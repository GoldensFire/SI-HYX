# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Classification and diagnostics for interrupted downloader connections."""


def is_network_error(detail):
    low = str(detail).lower()
    return any(token in low for token in (
        "10054", "connection reset", "connectionreseterror", "connection aborted",
        "timed out", "timeout", "таймаут", "unable to read from socket", "error in the pull",
        "session has been invalidated", "i/o error", "temporary failure",
        "http error 408", "http error 429", "http error 500", "http error 502",
        "http error 503", "http error 504",
    ))


def terminal_ffmpeg_error(line):
    """A failed demuxer cannot recover; individual reconnect warnings can."""
    low = line.lower()
    if any(token in low for token in (
        "error during demuxing", "error opening input", "conversion failed!",
    )):
        return line
    return ""


def network_hint():
    return (
        "Проверьте доступ к youtube.com и googlevideo.com из самой программы. "
        "Если используется zapret-discord-youtube, проверьте его службу, "
        "стратегию для TCP 443 и системный DNS: браузер может использовать "
        "другой протокол и DNS. Для сравнения попробуйте другую сеть или системный VPN."
    )
