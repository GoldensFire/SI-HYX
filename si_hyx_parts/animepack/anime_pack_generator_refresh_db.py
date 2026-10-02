# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: refresh_db. Public namespace: animepack.

Кнопка «Обновить базу» открывает панель «Что в базе», и обновить оттуда можно
ЧАСТЬ базы: только каталог аниме, только мангу, только узнаваемость франшиз,
только «в избранном» (просьба пользователя). Раньше всё это делалось одним
куском и забывало кэш целиком — включая то, что копилось генерациями по одному
запросу.
"""
from __future__ import annotations
import animepack as _api
from .db_source_refresh import refresh_database_sources


def refresh_db(self, parts=None) -> int:
    """Собирает заново выбранные части базы Shikimori.

        Каталог берётся ЦЕЛИКОМ, а не «сколько нужно на пак»: кнопка на то и
        нужна, чтобы база потом хватала на любой пак с этими фильтрами (просьба
        пользователя — раньше обход останавливался на нескольких сотнях
        карточек). Идёт это долго, поэтому на каждой странице проверяется
        «Остановить», а набранное сохраняется по ходу дела.

        parts — какие части обновлять (см. db_refresh_parts); None значит
        полный обход: аниме, манга с популярностью внешних сайтов (если у пака
        есть книжная доля) и франшизы. Возвращает, сколько карточек
        каталога лежит в кэше после обновления."""
    wanted = _api.db_refresh_parts(parts, self.s)
    started = _api.time.time()
    if "extras" in wanted:
        gone = self.db_cache.clear_part("extras")
        self.log(f"База Shikimori: забыто {gone} запомненных ответов "
                 "(персонажи, кадры, пригодность тайтлов) — спросятся заново "
                 "при следующей генерации.")
    cards = refresh_database_sources(self, wanted, _refresh_catalogs, _refresh_favorites)
    if self.stopped():
        self.db_cache.save()
        self.log("База Shikimori: остановлено, набранное всё же сохранено.")
        return _db_card_count(self)
    if "franchises" in wanted:
        _refresh_franchises(self, cards)
    self.db_cache.save()
    failures = [message for target, message in
                getattr(self, "_catalog_refresh_errors", {}).items() if target in wanted]
    sources = [source for source in ("remanga", "mangalib") if source in wanted]
    if "manga" in wanted or "favorites" in wanted:
        sources.append("shikimori")
    for source in sources:
        status = self.db_cache.memo("ru_population_refresh_status_v1", source) or {}
        if status.get("status") == "ERROR" and status.get("timestamp", 0) >= started:
            failures.append(f"{source}: {status.get('reason', 'обход не завершён')}")
    if failures:
        raise _api.AnimePackError("Обновление базы не завершено. Полученные данные сохранены.\n"
                                 + "\n".join(failures))
    total = _db_card_count(self)
    self.log(f"База Shikimori обновлена: {total} карточек, "
             f"{len(self._fr_parts)} франшиз.")
    return total


def _refresh_catalogs(self, wanted) -> list[dict]:
    """Каталоги аниме и манги. Незатронутый раздел просто читается из кэша:
    его карточки нужны, чтобы пересчитать по ним узнаваемость франшиз."""
    cards: list[dict] = []
    for target in ("anime", "manga"):
        if self.stopped():
            break
        if target not in wanted:
            cards += self.db_cache.all_cards(target)
            continue
        self.db_cache.clear_part(target)
        what = "манги" if target == "manga" else "аниме"
        self.log(f"База Shikimori: собираю каталог {what} заново — он "
                 "берётся целиком, это дольше минуты. Кнопка «Остановить» "
                 "сохранит набранное.")
        store = self._manga_cache if target == "manga" else self._card_cache
        for mal in self.fetch_full_catalog(manga=(target == "manga")):
            if mal in store:
                cards.append(store[mal])
    return cards


# Через сколько спрошенных тайтлов писать в журнал и сбрасывать набранное на
# диск. Обход идёт часами, и бросить его должно быть не жалко.
FAVORITES_LOG_EVERY = 50
FAVORITES_SAVE_EVERY = 200


def _refresh_favorites(self) -> None:
    """Спрашивает «в избранном» у карточек, каким это число вообще что-то
    меняет, — сверху вниз по узнаваемости.

    Каждое число стоит отдельного запроса к странице Shikimori (в API его нет),
    поэтому обход долгий и его бросают на середине: спрошенное сохраняется по
    ходу дела, а уже известное второй раз не спрашивается. Кому ответ ничего не
    изменит, тех не трогаем вовсе (favorites_targets)."""
    getter = getattr(self.shikimori, "title_favorites", None)
    if getter is None:
        return
    for target in ("anime", "manga"):
        if self.stopped():
            break
        manga = target == "manga"
        what = "манги" if manga else "аниме"
        cards = self.db_cache.all_cards(target)
        ids = _api.favorites_targets(cards, manga)
        urls = {}
        for card in cards:
            try:
                card_id = int((card or {}).get("id") or 0)
            except (TypeError, ValueError):
                continue
            if card_id:
                urls[card_id] = str((card or {}).get("url") or "")
        group = f"{target}_favorites"
        known = set(self.db_cache.memo_group(group))
        need = [i for i in ids if str(i) not in known]
        if not need:
            self.log(f"«В избранном» у {what}: спрашивать нечего — всё, что "
                     "может сменить уровень, уже в базе.")
            continue
        self.log(f"«В избранном» у {what}: спрашиваю {len(need)} тайтлов "
                 f"(из {len(ids)}, остальные уже в базе). Число живёт только "
                 "на странице тайтла — это запрос на каждый, идти будет "
                 "долго. «Остановить» сохранит набранное.")
        done = 0
        for shiki_id in need:
            if self.stopped():
                break
            try:
                try:
                    value = int(getter(shiki_id, target,
                                       urls.get(shiki_id, "")))
                except TypeError:  # старый подменённый клиент
                    value = int(getter(shiki_id, target))
            except Exception:  # noqa: BLE001 — мера полезная, но не обязательная
                continue
            self.db_cache.remember_memo(group, shiki_id, value)
            done += 1
            if done % FAVORITES_LOG_EVERY == 0:
                self.log(f"«В избранном» у {what}: {done} из {len(need)}…")
            if done % FAVORITES_SAVE_EVERY == 0:
                self.db_cache.save()
        self.db_cache.save()
        self.log(f"«В избранном» у {what}: узнано {done} тайтлов.")


def _refresh_franchises(self, cards) -> None:
    """Узнаваемость франшиз по карточкам, какие сейчас в базе.

    Считается по ВСЕМ карточкам каталога, а не только по свежепривезённым:
    франшиза общая для аниме и манги, и обновлять её вполсилы нельзя."""
    self.db_cache.clear_part("franchises")
    self._fr_index.clear()
    self._fr_parts.clear()
    representatives = {}
    for card in cards:
        key = str((card or {}).get("franchise") or "").strip()
        if key:
            representatives.setdefault(key, card)
    if not representatives:
        return
    total = len(representatives)
    self.log(f"База Shikimori: считаю узнаваемость {total} "
             "франшиз…")
    done = 0
    batch_size = int(getattr(self.shikimori, "FRANCHISE_BATCH", 13))
    for batch in _api._chunks(list(representatives.values()), batch_size):
        if self.stopped():
            break
        self._load_franchise_indexes(batch)
        done += len(batch)
        self.log(f"База Shikimori: франшизы {done} из {total}…")


def _db_card_count(self) -> int:
    """Сколько карточек каталога лежит в базе (аниме + манга)."""
    counts = self.db_cache.part_counts()
    return int(counts["anime"]["count"]) + int(counts["manga"]["count"])
