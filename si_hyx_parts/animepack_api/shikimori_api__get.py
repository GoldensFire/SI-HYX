# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi: _get. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


def _get(self, url: str, **kw):
    """GET к Shikimori через общий лимитер, с общей паузой при отказе.

        Ретраи на 429 живут в адаптере сессии, поэтому сюда такой отказ
        доезжает уже исключением RetryError («too many 429 error responses»)."""
    self.limiter.acquire()
    try:
        resp = self.session.get(url, **kw)
    except _api.requests.exceptions.RetryError:
        self.limiter.penalize(self.RETRY_PENALTY)
        raise
    if resp.status_code == 429:
        self.limiter.penalize(self.RETRY_PENALTY)
    return resp

def user_id(self, nickname: str) -> _api.Optional[int]:
    """Точный поиск по нику: /api/users/<ник>?is_nickname=1.

        В ASPG использовался /api/users?search=…, который ищет ПОДСТРОКОЙ среди
        всех пользователей и берёт первого попавшегося — из-за этого список мог
        приехать от постороннего человека.
        """
    nick = (nickname or "").strip()
    if not nick:
        return None
    try:
        resp = self._get(f"{self.base_url}/api/users/{nick}",
                         params={"is_nickname": 1}, timeout=(10, 30))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
    uid = (data or {}).get("id") if isinstance(data, dict) else None
    return int(uid) if uid else None

def user_anime_ids(self, nickname: str, statuses: _api.Iterable[str],
                   progress_cb: _api.Optional[_api.Callable[[str], None]] = None,
                   should_stop: _api.Optional[_api.Callable[[], bool]] = None,
                   target: str = "anime") -> list[int]:
    wanted = {s for s in statuses if s in _api.LIST_STATUSES}
    if not wanted:
        return []
    manga = str(target or "anime") == "manga"
    target_type = "Manga" if manga else "Anime"
    what = "манги" if manga else "аниме"
    uid = self.user_id(nickname)
    if not uid:
        raise _api.AnimePackApiError(
            f"Shikimori: пользователь «{nickname}» не найден "
            "(ник указывается точно, с учётом регистра).")
    out: list[int] = []
    seen: set[int] = set()
    page = 1
    while True:
        if should_stop and should_stop():
            break
        try:
            resp = self._get(
                f"{self.base_url}/api/v2/user_rates",
                params={"user_id": uid, "target_type": target_type,
                        "limit": self.PAGE, "page": page},
                timeout=(10, 45))
            resp.raise_for_status()
            chunk = resp.json()
        except Exception as e:
            raise _api._friendly(e, "Shikimori") from e
        if not isinstance(chunk, list) or not chunk:
            break
        fresh = 0
        for row in chunk:
            if not isinstance(row, dict):
                continue
            try:
                target = int(row["target_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if target in seen:
                continue
            seen.add(target)
            fresh += 1
            if _api._SHIKI_STATUS.get(row.get("status")) in wanted:
                out.append(target)
        if progress_cb:
            progress_cb(f"Shikimori/{nickname}: получено {len(out)} {what}…")
        # /api/v2/user_rates не умеет ни page, ни limit: он всегда отдаёт
        # ВЕСЬ список пользователя (проверено на живом аккаунте — limit=1000
        # вернул 1019 записей, а page=2 и page=3 те же самые). Раньше цикл
        # из-за этого крутился бесконечно, набивая список копиями одних и тех
        # же тайтлов. Признак конца — страница без единого нового id.
        if fresh == 0 or len(chunk) < self.PAGE:
            break
        page += 1
    return out

def animes_by_ids(self, ids: _api.Iterable[int]) -> list[dict]:
    """Карточки аниме пачкой (≤50 за раз).

        ВНИМАНИЕ: `animes(ids:)` ищет по id Shikimori. У подавляющего
        большинства тайтлов он совпадает с MAL id (так исторически заведено),
        но совпадение не гарантировано — те, у кого id разошлись, просто не
        найдутся и будут пропущены при отборе.
        """
    ids = [str(int(i)) for i in ids]
    if not ids:
        return []
    self.limiter.acquire()
    try:
        data = self.client._graphql(self.ANIMES_QUERY,
                                    {"ids": ",".join(ids), "limit": len(ids)})
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
    animes = (data or {}).get("animes") if isinstance(data, dict) else None
    return [a for a in (animes or []) if isinstance(a, dict)]
