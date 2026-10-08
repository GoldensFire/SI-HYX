# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Вопрос по манге: страница одного из выбранных источников."""
from __future__ import annotations
import animepack as _api
from .generation_diagnostics import locked, operation


# Столько тайтлов подряд может не найтись в источниках, прежде чем род вопросов
# снимается с прогона. Иначе редкая манга из каталога Shikimori выжигала бы
# кандидатов пачками, а мест в паке так и не занимала.
MISS_GIVE_UP = 8
# A complete reader catalog is evidence that more matching titles remain.
# Eight missing chapters must not discard that known pool. Keep the search
# bounded even when a reader exposes many titles with no usable chapters.
KNOWN_CATALOG_MISS_LIMIT = 80
# Столько страниц одной манги может отклонить проверка названия,
# прежде чем тайтл уступит место следующему.
VISUAL_TRIES = 3


def init_mangadex_service(self, client=None):
    """Клиенты страниц — только когда доля манги в паке вообще есть."""
    self.mangadex = client
    if client is None and self.s.mix_shares.get(_api.MANGA_KIND):
        self.mangadex = _api.MangaPageSources(
            self.session,
            sources=getattr(self.s, "manga_sources", None),
            language=str(getattr(self.s, "manga_lang", "") or ""),
            allow_erotica=bool(getattr(self.s, "manga_allow_erotica", False)),
            rng=self.rng)
    self._mangadex_misses = 0
    self._manga_catalog_matches = 0
    if hasattr(getattr(self, "gemini_manga", None), "image_generate_content"):
        self.gemini_manga.image_generate_content = True


class MangaPanelMixin:
    """Генератор: страница манги для книжного вопроса."""

    def download_manga_panel(self, cand) -> bool:
        """Скачивает разворот манги — сам вопрос («ложь» — не вышло).

    Обложкой больше не спрашиваем: она же лежит в ответе постером, и вопрос
    решался бы сравнением двух одинаковых картинок. Страницу берём из середины
    случайной главы — на титуле стояло бы название тайтла. Если на странице
    всё же видно название (см. manga_visual_check), берётся
    другая страница той же манги, как у артов Pixiv."""
        from .manga_budget import start
        start(self, cand)
        if self.stopped():
            return False
        if _api.MANGA_KIND in self._dead_kinds or self.mangadex is None:
            cand.rejected = True
            self._drop_kind(_api.MANGA_KIND, "источники страниц манги не подключены")
            return False
        from .manga_page_context import is_webtoon
        if getattr(self.s, "manga_character_crop", True) and is_webtoon(cand):
            from .manga_page_batch import prepare
            chosen = prepare(self, cand)
            if chosen is None:
                return False
            url, page, manga_titles = chosen
            if not _visual_ok(self, cand, *page, manga_titles=manga_titles):
                return False
            return _save_frame(self, cand, url, page)
        from .manga_page_reuse import keep, take
        prepared = 0
        for _ in range(VISUAL_TRIES):
            kept = take(self, cand)
            if kept and kept[0] == "page":
                # Повтор после паузы Gemini: та же страница, без поиска и
                # скачивания (а если уже вырезана — и без выбора сцены).
                kept = kept[1]
                url, chapter, manga_titles = kept["url"], kept["chapter"], kept["titles"]
                cand._manga_page_client, cand._manga_page_info = kept["client"], kept["info"]
            else:
                kept = None
                try:
                    url, chapter, manga_titles = _pick_page(self, cand)
                except _api.AnimePackApiError as e:
                    self._log_rare("Источники манги", f"Манга «{cand.title_ru}»: {e}")
                    return False
                if not url:
                    return _miss(self, cand)
            # Отпечаток главы известен до скачивания страницы и её проверки.
            if not cand.source_link:
                cand.source_link = _api.mangadex_chapter_link(chapter)
            from .early_repeat import reserve
            if not reserve(self, cand):
                return False
            if self.stopped():
                return False
            with self._manga_lock:
                self._mangadex_misses = 0
            cand._manga_transient, cand._manga_raw = False, None
            page = kept.get("page") if kept else None
            if page is None:
                page = _fetch_page(self, cand, url, manga_titles=manga_titles,
                                   raw=kept.get("raw") if kept else None)
            if page is None:
                if _api.MANGA_KIND in self._dead_kinds:
                    return False
                if cand._manga_transient:
                    # Пауза модели: следующие попытки сгорели бы так же, а
                    # скачанная страница дождётся повтора тайтла.
                    if cand._manga_raw:
                        keep(self, cand, ("page", dict(
                            url=url, chapter=chapter, titles=manga_titles,
                            client=getattr(cand, "_manga_page_client", None),
                            info=getattr(cand, "_manga_page_info", {}),
                            raw=cand._manga_raw)))
                    return False
                continue
            prepared += 1
            if not _visual_ok(self, cand, *page, manga_titles=manga_titles):
                if cand._manga_transient:
                    keep(self, cand, ("page", dict(
                        url=url, chapter=chapter, titles=manga_titles,
                        client=getattr(cand, "_manga_page_client", None),
                        info=getattr(cand, "_manga_page_info", {}), page=page)))
                    return False
                continue
            return _save_frame(self, cand, url, page)
        if not prepared:
            self._log_rare("Страница манги недоступна",
                           f"«{cand.title_ru}»: за {VISUAL_TRIES} попытки не удалось "
                           "загрузить и подготовить страницу — беру следующий тайтл")
        else:
            self._log_rare("Страница манги отклонена проверкой",
                           f"«{cand.title_ru}»: за {VISUAL_TRIES} попытки не нашлось "
                           "пригодной сцены без названия — беру следующий тайтл")
        return False


def _save_frame(self, cand, url, page):
    name = self._save_image(page[0], f"{cand.file_base}_frame", page[1])
    if not name:
        return False
    cand.frame_url, cand.frame_name, cand.has_frame = url, name, True
    # Persist the chosen page and its context, not the rejected page pool.
    cand.extra_frame_urls = [u for u in getattr(cand, "_manga_context_urls", ())
                             if _api.frame_url_key(u) != _api.frame_url_key(url)]
    return True


@operation("поиск")
def _pick_page(self, cand) -> tuple[str, str, list[str]]:
    """(адрес страницы, id главы); страница сразу помечается занятой.

    Выбор страницы и её резервирование — под одним замком: иначе два рабочих
    потока взяли бы один и тот же разворот. Отклонённая проверкой страница тоже
    остаётся занятой — следующая попытка возьмёт другую."""
    if callable(getattr(self.mangadex, "select_page", None)):
        from .manga_parallel_page import pick
        return pick(self, cand)
    with locked(self, self._manga_lock):
        with self._frames_lock:
            excluded = set(self._frames_used)
        url = self.mangadex.panel_url(cand.anime, excluded)
        # Главу читаем ЗДЕСЬ, под тем же замком, что и выбор страницы: это
        # поле общего клиента, и соседний поток перепишет его своим
        # разворотом (та же история, что была с ссылкой на арт Pixiv).
        chapter = str(getattr(self.mangadex, "last_chapter", "") or "")
        manga_titles = list(getattr(self.mangadex, "last_titles", []) or [])
        cand.source_link = str(getattr(self.mangadex, "last_source_link", "") or "")
        cand._manga_page_client = getattr(self.mangadex, "last_client", None)
        cand._manga_page_info = dict(getattr(self.mangadex, "last_page_info", {}) or {})
        for error in getattr(self.mangadex, "last_errors", []):
            self._log_rare("Источники манги", error)
        if url:
            with self._frames_lock:
                self._frames_used.add(_api.frame_url_key(url))
    return url, chapter, manga_titles


@operation("подготовка страницы")
def _fetch_page(self, cand, url: str, *, manga_titles=(), raw=None):
    """(байты, расширение, сцена проверена) готовой страницы для вопроса.

    raw — уже скачанная в прошлой попытке страница (manga_page_reuse)."""
    scene_checked = False
    select_scene = False
    try:
        from .manga_page_context import download, is_webtoon
        if raw:
            data, ext = raw
            cand._manga_context_urls = [url]
        elif getattr(self.s, "manga_character_crop", True):
            data, ext = download(self, cand, url)
        else:
            client = getattr(cand, "_manga_page_client", None)
            if client is None:
                data = self._get_bytes(url)
                ext = self._url_ext(url, ".png")
            else:
                data, ext = client.download_page(url, cand._manga_page_info)
        cand._manga_raw = data, ext
        from .manga_crop import is_long_page
        if not is_long_page(data) and not (is_webtoon(cand)
                and getattr(self.s, "manga_character_crop", True)):
            return data, ext, scene_checked
        # Readers also split webtoons into short chunks, often through a face.
        if getattr(self.s, "manga_character_crop", True):
            select_scene = True
            from .manga_character_crop import crop
            cut = crop(self, cand, data, ext, manga_titles=manga_titles)
            if cut is None:
                return None
            scene_checked = True
        else:
            cut = _api.fit_manga_page(data, ext, rng=self.rng)
    except Exception as e:  # noqa: BLE001 — сеть и разбор картинки
        if (select_scene
                and (self.gemini_manga is None or type(e).__name__ in
                     ("GeminiAuthError", "GeminiQuotaError", "GeminiDownError"))):
            self._drop_kind(_api.MANGA_KIND, f"Gemini не выбрал сцену страницы: {e}")
            cand.rejected = True
            self._log_rare("Выбор сцены Gemini",
                           f"Не удалось выбрать сцену с персонажами: {e}")
            return None
        from .manga_page_batch import gemini_transient, note_wall
        note_wall(self, e)
        if select_scene and gemini_transient(e):
            from .media_transfer import trouble_mark
            trouble_mark()   # тайтл уйдёт на повтор, см. manga_page_batch
            cand._manga_transient = True
        self._log_rare("Источники манги", f"Страница «{cand.title_ru}» не скачалась: {e}")
        return None
    if cut:
        data, ext = cut
        self._log_rare("Сцена манги",
                       f"«{cand.title_ru}»: выбрана область страницы для вопроса")
    return data, ext, scene_checked


@operation("проверка изображения")
def _visual_ok(self, cand, data: bytes, ext: str, scene_checked: bool = False,
               *, manga_titles=()) -> bool:
    """Можно ли брать страницу: на ней не видно названия манги.

    В режиме Gemini отказ сервиса выключает проверку до конца прогона.
    В локальном режиме OCR продолжает работу после отказа Gemini fallback."""
    if not getattr(self.s, "manga_gemini_check", True):
        return True
    if (scene_checked
            and getattr(self.s, "manga_title_check_mode", "gemini") == "gemini"):
        # The scene selection already checks title lettering inside this crop.
        return True
    if (getattr(self.s, "manga_title_check_mode", "gemini") == "gemini"
            and getattr(self, "gemini_manga", None) is None):
        return not getattr(self.s, "manga_strict_targets", False)
    from .manga_visual_check import check
    try:
        approved, reason = check(self, cand, data, ext,
                                 manga_titles=manga_titles)
    except Exception as exc:  # noqa: BLE001 — типы gemini_api
        if type(exc).__name__ in ("GeminiAuthError", "GeminiQuotaError",
                                  "GeminiDownError"):
            self.gemini_manga = None
            local = getattr(self.s, "manga_title_check_mode", "gemini") == "local"
            strict = getattr(self.s, "manga_strict_targets", False)
            self.log("Gemini для страниц манги выключен до конца прогона "
                     f"({exc}). " + ("OCR продолжает работу; сомнительные "
                                    "страницы отклоняются." if local else
                                    "Непроверенные страницы отклоняются." if strict else
                                    "Страницы берутся без проверки."))
            return not local and not strict
        from .manga_page_batch import gemini_transient
        if gemini_transient(exc):
            from .media_transfer import trouble_mark
            trouble_mark()      # пауза модели — тайтл повторится позже
            cand._manga_transient = True
        self._log_rare("Проверка манги через Gemini",
                       f"Страница «{cand.title_ru}» не прошла проверку "
                       f"Gemini: {exc} — беру другую страницу")
        return False
    if not approved:
        self._log_rare(
            "Страница манги отклонена проверкой",
            f"«{cand.title_ru}»: на странице видно название "
            f"({reason or 'надпись с названием'}) — беру другую страницу "
            "той же манги")
    return approved


def _miss(self, cand) -> bool:
    """Ни один выбранный источник не нашёл страниц — считаем промахи."""
    with self._manga_lock:
        self._mangadex_misses += 1
        misses = self._mangadex_misses
    self._log_rare("Источники манги",
                   f"«{cand.title_ru}»: страниц в выбранных источниках нет — беру "
                   "следующий тайтл")
    known = getattr(self, "_manga_catalog_matches", 0)
    limit = max(MISS_GIVE_UP, min(KNOWN_CATALOG_MISS_LIMIT, known))
    if misses >= limit:
        self.log(f"Манга: подряд не нашлось {misses} тайтлов — вопросы "
                 "по манге пропускаю, их места отдам остальным родам "
                 "вопросов. Проверьте язык глав и типы изданий.")
        self._drop_kind(_api.MANGA_KIND, f"подряд {misses} тайтлов без страниц")
        cand.rejected = True
    return False
