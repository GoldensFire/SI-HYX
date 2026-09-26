# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""English anime title → fixed art prompt → Cloudflare image."""
from __future__ import annotations

import random
import threading

from cloudflare_art_api import (
    CloudflareArtError, CloudflareArtUnavailable, CloudflareArtCancelled,
)
from animepack_art_quality import validate_art_composition

PROMPT_TEMPLATE = (
    "A family-friendly anime illustration of the first season of {title}. "
    "One or two recognizable main characters with their canonical appearance "
    "and usual everyday outfits, enjoying a peaceful moment in the familiar "
    "setting of the series. Medium shot at eye level, complete heads visible "
    "with space above them and on both sides. Detailed background fills the "
    "canvas edge to edge, including the bottom foreground. Crisp linework, "
    "clean cel shading, neutral daylight, balanced lighting, natural colors "
    "faithful to the series. Text-free illustration with unmarked surfaces, "
    "without lettering, logos, borders or watermarks."
)


def art_prompt(anime: dict) -> str:
    title = str(anime.get("english") or "").strip()
    if not title:
        raise CloudflareArtError("ИИ-арт: у тайтла нет английского названия.")
    title = " ".join(title.split())
    return PROMPT_TEMPLATE.format(title=title[:2048 - len(PROMPT_TEMPLATE)])


class AnimeArtService:
    """Serialize paid requests across media worker threads."""
    def __init__(self, client):
        self.client = client
        self._lock = threading.Lock()
        self._unavailable = ""
        self._failures = 0

    def generate(self, anime: dict) -> tuple[bytes, str]:
        prompt = art_prompt(anime)
        while not self._lock.acquire(timeout=0.1):
            self.client.check_cancelled()
        try:
            self.client.check_cancelled()
            if self._unavailable:
                raise CloudflareArtUnavailable(self._unavailable)
            try:
                data, ext = self.client.generate(
                    prompt, seed=random.SystemRandom().randrange(2**31))
                validate_art_composition(data)
            except CloudflareArtUnavailable as exc:
                self._unavailable = str(exc)
                raise
            except CloudflareArtCancelled:
                raise
            except CloudflareArtError:
                self._failures += 1
                if self._failures >= 3:
                    self._unavailable = (
                        "Cloudflare трижды подряд не вернул пригодную картинку. "
                        "ИИ-арты в этом запуске остановлены.")
                    raise CloudflareArtUnavailable(self._unavailable) from None
                raise
            self._failures = 0
            self.client.check_cancelled()
            return data, ext
        finally:
            self._lock.release()
