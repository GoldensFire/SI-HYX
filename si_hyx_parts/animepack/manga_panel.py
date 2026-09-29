# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Вопрос по манге: страница оригинала с MangaDex. Namespace: animepack."""
from __future__ import annotations
import animepack as _api


# Столько тайтлов подряд может не найтись на MangaDex, прежде чем род вопросов
# снимается с прогона. Иначе редкая манга из каталога Shikimori выжигала бы
# кандидатов пачками, а мест в паке так и не занимала.
MISS_GIVE_UP = 8
# Столько страниц одной манги может отклонить Gemini (видно название),
# прежде чем тайтл уступит место следующему.
VISUAL_TRIES = 3


def init_mangadex_service(self, client=None):
    """Клиент MangaDex — только когда доля манги в паке вообще есть."""
    self.mangadex = client
    if client is None and self.s.mix_shares.get(_api.MANGA_KIND):
        self.mangadex = _api.MangaDexApi(
            self.session,
            language=str(getattr(self.s, "manga_lang", "") or ""),
            allow_erotica=bool(getattr(self.s, "manga_allow_erotica", False)),
            rng=self.rng)
    self._mangadex_misses = 0


def download_manga_panel(self, cand) -> bool:
    """Скачивает разворот манги — сам вопрос («ложь» — не вышло).

    Обложкой больше не спрашиваем: она же лежит в ответе постером, и вопрос
    решался бы сравнением двух одинаковых картинок. Страницу берём из середины
    случайной главы — на титуле стояло бы название тайтла. Если на странице
    всё же видно название (так решил Gemini, см. manga_visual_check), берётся
    другая страница той же манги, как у артов Pixiv."""
    if self.stopped():
        return False
    if _api.MANGA_KIND in self._dead_kinds or self.mangadex is None:
        cand.rejected = True
        self._drop_kind(_api.MANGA_KIND)
        return False
    for _ in range(VISUAL_TRIES):
        try:
            url, chapter = _pick_page(self, cand)
        except _api.AnimePackApiError as e:
            self._log_rare("MangaDex", f"MangaDex «{cand.title_ru}»: {e}")
            return False
        if not url:
            return _miss(self, cand)
        if self.stopped():
            return False
        with self._manga_lock:
            self._mangadex_misses = 0
        page = _fetch_page(self, cand, url)
        if page is None:
            return False
        if not _visual_ok(self, cand, *page):
            continue
        name = self._save_image(page[0], f"{cand.file_base}_frame", page[1])
        if not name:
            return False
        cand.frame_url = url
        cand.frame_name = name
        # Адрес ГЛАВЫ, а не картинки: раздающий узел MangaDex меняется каждый
        # час, а страница главы открывается в браузере и показывает тот же
        # разворот.
        cand.source_link = _api.mangadex_chapter_link(chapter)
        cand.has_frame = True
        return True
    self._log_rare("Страница манги отклонена Gemini",
                   f"«{cand.title_ru}»: на {VISUAL_TRIES} страницах подряд "
                   "видно название — беру следующий тайтл")
    return False


def _pick_page(self, cand) -> tuple[str, str]:
    """(адрес страницы, id главы); страница сразу помечается занятой.

    Выбор страницы и её резервирование — под одним замком: иначе два рабочих
    потока взяли бы один и тот же разворот. Отклонённая Gemini страница тоже
    остаётся занятой — следующая попытка возьмёт другую."""
    with self._manga_lock:
        with self._frames_lock:
            excluded = set(self._frames_used)
        url = self.mangadex.panel_url(cand.anime, excluded)
        # Главу читаем ЗДЕСЬ, под тем же замком, что и выбор страницы: это
        # поле общего клиента, и соседний поток перепишет его своим
        # разворотом (та же история, что была с ссылкой на арт Pixiv).
        chapter = str(getattr(self.mangadex, "last_chapter", "") or "")
        if url:
            with self._frames_lock:
                self._frames_used.add(_api.frame_url_key(url))
    return url, chapter


def _fetch_page(self, cand, url: str):
    """(байты, расширение) страницы в том виде, в каком она уйдёт в пак."""
    try:
        data = self._get_bytes(url)
        ext = self._url_ext(url, ".png")
        # Страница манхвы и маньхуа — это кусок вертикальной ленты вебтуна в
        # десяток тысяч пикселей высотой: на экране SIGame такая полоса
        # превращается в ниточку. Режем её до книжных пропорций (см.
        # manga_crop.py). У обычной манги разворот и так книжный — там ничего
        # не меняется.
        cut = _api.fit_manga_page(data, ext, rng=self.rng)
    except Exception as e:  # noqa: BLE001 — сеть и разбор картинки
        self._log_rare("MangaDex", f"Страница «{cand.title_ru}» не скачалась: {e}")
        return None
    if cut:
        data, ext = cut
        self._log_rare("Манхва",
                       f"«{cand.title_ru}»: лента вебтуна обрезана до "
                       "книжного разворота")
    return data, ext


def _visual_ok(self, cand, data: bytes, ext: str) -> bool:
    """Можно ли брать страницу: на ней не видно названия манги.

    Кончилась квота, ключ не принят или сервер перестал отвечать
    (GeminiDownError, см. visual_batch) — проверка выключается до конца
    прогона, и страницы идут как раньше, без неё: из середины главы название
    попадается редко, а терять из-за этого все вопросы по манге жалко."""
    if getattr(self, "gemini_manga", None) is None:
        return True
    from .manga_visual_check import check
    try:
        approved, reason = check(self, cand, data, ext)
    except Exception as exc:  # noqa: BLE001 — типы gemini_api
        if type(exc).__name__ in ("GeminiAuthError", "GeminiQuotaError",
                                  "GeminiDownError"):
            self.gemini_manga = None
            self.log("Проверка страниц манги через Gemini выключена до конца "
                     f"прогона ({exc}) — страницы берутся без неё.")
            return True
        self._log_rare("Проверка манги через Gemini",
                       f"Страница «{cand.title_ru}» не прошла проверку "
                       f"Gemini: {exc} — беру другую страницу")
        return False
    if not approved:
        self._log_rare(
            "Страница манги отклонена Gemini",
            f"«{cand.title_ru}»: на странице видно название "
            f"({reason or 'надпись с названием'}) — беру другую страницу "
            "той же манги")
    return approved


def _miss(self, cand) -> bool:
    """Тайтла на MangaDex нет — считаем промахи и вовремя сдаёмся."""
    with self._manga_lock:
        self._mangadex_misses += 1
        misses = self._mangadex_misses
    self._log_rare("MangaDex",
                   f"«{cand.title_ru}»: страниц на MangaDex нет — беру "
                   "следующий тайтл")
    if misses >= MISS_GIVE_UP:
        self.log(f"MangaDex: подряд не нашлось {misses} тайтлов — вопросы "
                 "по манге пропускаю, их места отдам остальным родам "
                 "вопросов. Проверьте язык глав и типы изданий.")
        self._drop_kind(_api.MANGA_KIND)
        cand.rejected = True
    return False
