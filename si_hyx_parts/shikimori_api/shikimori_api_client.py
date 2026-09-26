# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApiClient. Public namespace: shikimori_api."""
from __future__ import annotations
import shikimori_api as _api


class ShikimoriApiClient:
    """Тонкий клиент Shikimori REST API v1.

    Особенности:
      • requests.Session с обязательным User-Agent (Shikimori без него отдаёт 403);
      • таймауты (connect, read) на каждый запрос;
      • ретраи на 429/5xx с уважением Retry-After и экспоненциальным backoff;
      • опциональный OAuth-токен (Bearer) — для приватных эндпоинтов; публичный
        поиск работает и без него.
    """

    def __init__(self, base_url: str = _api.DEFAULT_BASE_URL,
                 user_agent: str = _api.DEFAULT_USER_AGENT,
                 token: _api.Optional[str] = None,
                 timeout: tuple[float, float] = (5.0, 15.0),
                 max_retries: int = 3,
                 session: _api.Optional['_api.Session'] = None):
        if not _api._HAS_REQUESTS:
            raise _api.ShikimoriError(
                "Не установлен пакет requests — добавьте его в окружение.")
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent or _api.DEFAULT_USER_AGENT
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self._session = session or _api.requests.Session()
        self._session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        })
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    # ── Низкоуровневый GET с ретраями ──────────────────────────────────────
    def _get(self, path: str, params: _api.Optional[dict] = None) -> _api.Any:
        url = self.base_url + path
        last_err: _api.Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except _api.requests.Timeout as e:
                last_err = _api.ShikimoriError(f"Таймаут запроса к Shikimori: {e}")
            except _api.requests.RequestException as e:
                last_err = _api.ShikimoriError(f"Сетевая ошибка: {e}")
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError as e:
                        raise _api.ShikimoriError(f"Некорректный JSON от сервера: {e}")
                # 429/5xx — временные, повторяем с задержкой.
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = _api.ShikimoriError(
                        f"Сервер вернул {resp.status_code}.")
                    delay = self._retry_delay(resp, attempt)
                    if attempt < self.max_retries:
                        _api.time.sleep(delay)
                        continue
                else:
                    # 4xx, кроме 429 — повтор не поможет.
                    raise _api.ShikimoriError(
                        f"Запрос отклонён сервером (HTTP {resp.status_code}).")
            if attempt < self.max_retries:
                _api.time.sleep(self._backoff(attempt))
        raise last_err or _api.ShikimoriError("Неизвестная ошибка запроса.")

    # ── GraphQL POST (для полного списка жанров/тем) ───────────────────────
    def _graphql(self, query: str, variables: _api.Optional[dict] = None) -> _api.Any:
        """POST к /api/graphql с ретраями. Сами обрабатываем редирект (301/302/
        307/308): requests на 301 превращает POST→GET и теряет тело, поэтому
        перепосылаем тело на адрес из Location (домен Shikimori мигрирует между
        .one/.io). Возвращает содержимое поля data или бросает ShikimoriError."""
        from urllib.parse import urljoin
        url = self.base_url + "/api/graphql"
        payload = {"query": query, "variables": variables or {}}
        last_err: _api.Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.post(
                    url, json=payload, timeout=self.timeout, allow_redirects=False)
                # Следуем за редиректом ВРУЧНУЮ, сохраняя метод POST и тело.
                hops = 0
                while resp.status_code in (301, 302, 307, 308) and hops < 4:
                    loc = resp.headers.get("Location")
                    if not loc:
                        break
                    nurl = urljoin(resp.url, loc)
                    resp = self._session.post(
                        nurl, json=payload, timeout=self.timeout,
                        allow_redirects=False)
                    hops += 1
            except _api.requests.Timeout as e:
                last_err = _api.ShikimoriError(f"Таймаут запроса к Shikimori: {e}")
            except _api.requests.RequestException as e:
                last_err = _api.ShikimoriError(f"Сетевая ошибка: {e}")
            else:
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                    except ValueError as e:
                        raise _api.ShikimoriError(f"Некорректный JSON от сервера: {e}")
                    if isinstance(body, dict) and body.get("errors"):
                        msg = body["errors"][0].get("message", "GraphQL error") \
                            if isinstance(body["errors"], list) and body["errors"] \
                            else "GraphQL error"
                        raise _api.ShikimoriError(f"GraphQL: {msg}")
                    return (body or {}).get("data") if isinstance(body, dict) else None
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = _api.ShikimoriError(f"Сервер вернул {resp.status_code}.")
                    if attempt < self.max_retries:
                        _api.time.sleep(self._retry_delay(resp, attempt))
                        continue
                else:
                    raise _api.ShikimoriError(
                        f"GraphQL отклонён сервером (HTTP {resp.status_code}).")
            if attempt < self.max_retries:
                _api.time.sleep(self._backoff(attempt))
        raise last_err or _api.ShikimoriError("Неизвестная ошибка GraphQL-запроса.")

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(8.0, 0.5 * (2 ** attempt))

    def _retry_delay(self, resp, attempt: int) -> float:
        ra = resp.headers.get("Retry-After")
        if ra:
            try:
                return min(15.0, float(ra))
            except ValueError:
                pass
        return self._backoff(attempt)

    # ── Высокоуровневые методы ─────────────────────────────────────────────
    def search_titles(self, content_type: str = "anime", *, page: int = 1,
                      limit: int = 50, **params: _api.Any) -> list[_api.Anime]:
        """Один «страничный» запрос /api/animes или /api/mangas.
        limit ≤ 50 (ограничение API). content_type: "anime" | "manga"."""
        endpoint = "/api/mangas" if content_type == "manga" else "/api/animes"
        q = {"page": max(1, int(page)), "limit": max(1, min(50, int(limit)))}
        for k, v in params.items():
            if v not in (None, "", []):
                q[k] = v
        data = self._get(endpoint, q)
        if not isinstance(data, list):
            raise _api.ShikimoriError("Ожидался список тайтлов, получено иное.")
        return [_api.Anime.from_json(d, self.base_url) for d in data if isinstance(d, dict)]

    # Обратная совместимость со старым именем.

    def get_anime(self, anime_id: int) -> dict:
        """Полная карточка одного аниме (сырой словарь)."""
        data = self._get(f"/api/animes/{int(anime_id)}")
        if not isinstance(data, dict):
            raise _api.ShikimoriError("Ожидалась карточка аниме, получено иное.")
        return data

    def genres(self, content_type: str = "anime") -> list[dict]:
        """Полный список жанров/тем/демографий (id/name/russian/kind) для фильтра.

        Берём через GraphQL (`genres(entryType: …)`): только он отдаёт СОВРЕМЕННЫЙ
        набор с правильным `kind` ("genre"/"theme"/"demographic") и id, понятными
        параметру genre_v2 поиска. Это даёт ВСЕ темы (включая «Reincarnation»,
        «Isekai» и т.п.), которых нет в легаси /api/genres.

        Если GraphQL недоступен — откатываемся на REST /api/genres (легаси-набор,
        классифицируется по имени в genre_group)."""
        ct = (content_type or "anime").lower()
        entry = "Manga" if ct == "manga" else "Anime"
        try:
            data = self._graphql(
                "query($e: GenreEntryTypeEnum!){ genres(entryType: $e){ "
                "id name russian kind } }", {"e": entry})
            glist = (data or {}).get("genres") if isinstance(data, dict) else None
            if isinstance(glist, list) and glist:
                out = []
                for g in glist:
                    if not isinstance(g, dict):
                        continue
                    # id из GraphQL приходит строкой — нормализуем к int.
                    try:
                        gid = int(g.get("id"))
                    except (TypeError, ValueError):
                        continue
                    out.append({
                        "id": gid,
                        "name": g.get("name") or "",
                        "russian": g.get("russian") or "",
                        "kind": (g.get("kind") or "genre"),
                    })
                if out:
                    return out
        except _api.ShikimoriError:
            pass  # тихий откат на REST ниже

        # Откат: легаси REST (без новых тем; kind всегда "genre").
        data = self._get("/api/genres")
        if not isinstance(data, list):
            return []
        out = []
        for g in data:
            if not isinstance(g, dict):
                continue
            et = str(g.get("entry_type") or "").lower()
            if et:
                if et == ct:
                    out.append(g)
            elif g.get("kind") in (None, content_type):  # совместимость со старым API
                out.append(g)
        return out

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

ShikimoriApiClient.__module__ = _api.__name__
_api.ShikimoriApiClient = ShikimoriApiClient

def find_anime(client: _api.ShikimoriApiClient, criteria: _api.AnimeFilter, *,
               max_pages: int = 200, per_page: int = 50,
               throttle: float = 0.0,
               progress: _api.Optional[_api.Any] = None,
               on_batch: _api.Optional[_api.Any] = None,
               should_stop: _api.Optional[_api.Any] = None) -> list[_api.Anime]:
    """Высокоуровневый поиск: серверная фильтрация с пагинацией + локальная
    доводка под полный набор критериев.

    Листает страницы ПОДРЯД, пока не дойдёт до последней (сервер отдал меньше
    per_page), не упрётся в max_pages или пока вызывающая сторона не попросит
    остановиться через should_stop(). Раннего «хватит» по числу результатов НЕТ:
    поиск идёт «до конца или до Стоп» (как просил пользователь).

    • max_pages — жёсткий потолок (страховка от выкачивания всей базы).
    • throttle — пауза (сек) между страницами, чтобы не упереться в лимит
      Shikimori на длинной выдаче. 0 — без паузы.
    • progress(page, matched) — необязательный колбэк прогресса.
    • on_batch(new_matches: list[Anime]) — колбэк с НОВЫМИ подходящими тайтлами
      каждой страницы (для потокового наполнения списка в UI).
    • should_stop() -> bool — необязательная остановка (кнопка «Стоп»).
    """
    server_params = criteria.to_server_params()
    ctype = criteria.content_type
    matched: list[_api.Anime] = []
    seen: set[int] = set()
    for page in range(1, max_pages + 1):
        if should_stop is not None and should_stop():
            break
        try:
            batch = client.search_titles(ctype, page=page, limit=per_page,
                                         **server_params)
        except _api.ShikimoriError:
            # Временная ошибка (обычно 429 на большой глубине выдачи): если уже
            # что-то набрали — отдаём накопленное, а не теряем весь поиск. На
            # самой первой странице ошибка реальна — пробрасываем дальше.
            if matched:
                break
            raise
        new_matches: list[_api.Anime] = []
        for a in batch:
            if a.id in seen:
                continue
            seen.add(a.id)
            if criteria.matches_local(a):
                matched.append(a)
                new_matches.append(a)
        if on_batch is not None and new_matches:
            try:
                on_batch(new_matches)
            except Exception:
                pass
        if progress is not None:
            try:
                progress(page, len(matched))
            except Exception:
                pass
        if len(batch) < per_page:
            break  # последняя страница
        if throttle > 0:
            # Дробим паузу, чтобы «Стоп» срабатывал быстро.
            slept = 0.0
            while slept < throttle:
                if should_stop is not None and should_stop():
                    break
                _api.time.sleep(min(0.1, throttle - slept))
                slept += 0.1
    return matched

find_anime.__module__ = _api.__name__
_api.find_anime = find_anime
