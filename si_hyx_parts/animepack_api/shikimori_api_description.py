"""Load a description only when a question actually needs one."""
from __future__ import annotations

import animepack_api as _api


def anime_description(self, shikimori_id: int) -> str:
    query = ("query($ids: String!) { "
             "animes(ids: $ids, limit: 1) { id description } }")
    self.limiter.acquire()
    try:
        data = self.client._graphql(query, {"ids": str(int(shikimori_id))})
    except Exception as exc:
        raise _api._friendly(exc, "Shikimori") from exc
    rows = (data or {}).get("animes") if isinstance(data, dict) else []
    for row in rows or []:
        if isinstance(row, dict) and str(row.get("id")) == str(shikimori_id):
            return str(row.get("description") or "")
    return ""
