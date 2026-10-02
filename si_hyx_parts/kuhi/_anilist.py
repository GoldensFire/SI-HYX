"""Small AniList dependency for Kuhi's season matching; root data comes from SI-HYX."""
from . import _cache
from ._transport import AsyncClient


async def anilist_query(query, variables):
    key = ("graphql", query, tuple(sorted(variables.items())))
    cached = _cache.cached(key, _cache.MAPPING_TTL)
    if cached is not None:
        return cached
    async with AsyncClient() as client:
        response = await client.post("https://graphql.anilist.co",
                                     json={"query": query, "variables": variables})
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError("AniList: ошибка сопоставления сезона")
    data = payload.get("data") or {}
    _cache.set(key, data, _cache.MAPPING_TTL)
    return data
