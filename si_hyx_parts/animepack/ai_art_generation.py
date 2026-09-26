# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Generated art questions; the original title/poster remains the answer."""
from __future__ import annotations

import animepack as _api
from animepack_art import AnimeArtService
from animepack_art_filter import eligible_art_title
from cloudflare_art_api import (
    CloudflareArtClient, CloudflareArtError, CloudflareArtCancelled,
    CloudflareArtUnavailable,
)


def init_art_service(self, client=None):
    self.art_service = None
    if not self.s.mix_shares.get(_api.AI_ART_KIND):
        return
    client = client or CloudflareArtClient(
        self.s.cloudflare_account_id, self.s.cloudflare_token,
        model=self.s.cloudflare_model, stopped=self.stopped, on_retry=self.log)
    self.art_service = AnimeArtService(client)


def generate_ai_art(self, cand):
    if self.stopped():
        return False
    if _api.AI_ART_KIND in self._dead_kinds or self.art_service is None:
        cand.rejected = True
        self._drop_kind(_api.AI_ART_KIND)
        return False
    try:
        if not eligible_art_title(cand.anime, self.shikimori):
            return False
        data, ext = self.art_service.generate(cand.anime)
        if self.stopped():
            return False
        name = self._save_image(data, f"{cand.file_base}_ai_art", ext)
        cand.frame_name = name
        cand.has_frame = bool(name)
        if name:
            self.log(f"ИИ-арт «{cand.title_ru}»: сгенерирован.")
        return bool(name)
    except CloudflareArtCancelled:
        return False
    except CloudflareArtUnavailable as exc:
        self.log(str(exc))
        self._drop_kind(_api.AI_ART_KIND)
        cand.rejected = True
        return False
    except (CloudflareArtError, OSError) as exc:
        self._log_rare("ИИ-арты", f"ИИ-арт «{cand.title_ru}»: {exc}")
        return False
