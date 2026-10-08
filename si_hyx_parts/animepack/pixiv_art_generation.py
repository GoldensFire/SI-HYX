# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Pixiv illustration questions; regular title and poster remain the answer."""
from __future__ import annotations

import animepack as _api
from .generation_diagnostics import locked, operation
from pixiv_art_api import PixivArtClient, PixivArtError, PixivArtUnavailable


def init_pixiv_service(self, client=None):
    self.pixiv = None
    if not self.s.mix_shares.get(_api.PIXIV_ART_KIND):
        return
    self.pixiv = client or PixivArtClient(
        self.s.pixiv_refresh_token, stopped=self.stopped, rng=self.rng,
        exclude_r18=self.s.pixiv_exclude_r18,
        exclude_ai=self.s.pixiv_exclude_ai,
        r18_mode=str(getattr(self.s, "pixiv_r18_mode", "") or ""),
        ai_mode=str(getattr(self.s, "pixiv_ai_mode", "") or ""),
        allow_same_sex=bool(getattr(self.s, "pixiv_allow_same_sex", False)),
        min_likes=getattr(self.s, "pixiv_min_likes", None),
        # Названия всех тайтлов каталога — по ним узнаётся арт сразу по
        # нескольким сериалам. Функцией, а не набором: собирать его до
        # первого арта незачем.
        known_titles=lambda: self.db_cache.title_index(),
        # Списки меток-исключений — из настроек пака целиком: их правит сам
        # пользователь (окно «Исключаемые теги»).
        settings=self.s)
    # Сразу говорим, во что обойдётся узкий режим: «только R-18» и «только
    # ИИ» вместе оставляют одну работу из сотни, и весь прогон может уйти в
    # «подходящих артов по тегу не найдено» (просьба пользователя).
    narrow = [name for name, mode in
              (("только R-18", self.pixiv.r18_mode),
               ("только ИИ-арты", self.pixiv.ai_mode)) if mode == "only"]
    if narrow:
        self.log("Арты Pixiv: включено «" + "» и «".join(narrow) + "». Под "
                 "такой отбор подходит малая часть работ: тайтлов на пак "
                 "уйдёт во много раз больше обычного, а сам прогон будет "
                 "заметно дольше. Не набирается пак — ослабьте один из "
                 "режимов до «Разрешать».")


# Промо-ролики, рекламные вставки и клипы. Ответом вопроса такая запись быть
# не может: это не тайтл, а его реклама.
CLIP_KINDS = ("pv", "cm", "music")


def _is_clip(card) -> bool:
    """Запись Shikimori — ролик, а не сам тайтл."""
    return str((card or {}).get("kind") or "").strip().lower() in CLIP_KINDS


class PixivArtMixin:
    """Генератор: арт Pixiv — первый сезон тайтла, поиск и загрузка."""

    def _first_season_card(self, anime: dict) -> dict:
        """Карточка ПЕРВОЙ части франшизы (или та же самая, если она и есть первая).

    Нужна поиску артов на Pixiv. Теги там висят на названии оригинала:
    рисунок по «Магической битве 2» подписан 呪術廻戦, а не 呪術廻戦2, и по
    названию сиквела не находится ничего. Пак же спокойно берёт в кандидаты
    любой сезон — узнаваемость у него оригинала (franchise_index), — и
    пятьдесят арт-кандидатов подряд отваливались с «подходящих артов по тегу
    не найдено».

    Части франшизы уже лежат в кэше от расчёта узнаваемости
    (_load_franchise_indexes), и лишнего запроса это обычно не стоит: берём
    самый ранний год, а при равных годах — самую популярную часть (части
    приходят по убыванию популярности). Полную карточку (с японским и
    английским названием) достаём через общий кэш карточек аниме."""
        anime = anime or {}
        key = str(anime.get("franchise") or "").strip()
        if not key:
            return anime
        known = self._first_season.get(key)
        if known is not None:
            return known or anime
        self._first_season[key] = {}          # больше одного раза не спрашиваем
        best, best_year = None, None
        for row in (self.db_cache.franchise(key) or []):
            if not isinstance(row, dict):
                continue
            # Ролики и заставки — не тайтлы: самой ранней частью франшизы обычно
            # оказывается именно PV, и ответом вопроса становилось «Подземелье
            # вкусностей PV (2017)» (просьба пользователя). У старых кэшей поля
            # kind нет вовсе — там отсеет уже проверка полной карточки ниже.
            if "kind" in row and _is_clip(row):
                continue
            if _api.is_announced(row):          # анонс — не тайтл для ответа
                continue
            try:
                year = int((row.get("airedOn") or {}).get("year") or 0)
            except (TypeError, ValueError):
                continue
            if not year:
                continue
            if best_year is None or year < best_year:
                best, best_year = row, year
        if not best:
            return anime
        try:
            mal = int(best.get("malId") or best.get("id") or 0)
        except (TypeError, ValueError):
            mal = 0
        try:
            own = int(anime.get("malId") or anime.get("id") or 0)
        except (TypeError, ValueError):
            own = 0
        if not mal or mal == own:
            return anime
        try:
            cards = self._animes_by_ids([mal])
        except _api.AnimePackApiError:
            return anime
        card = cards[0] if cards else {}
        if not isinstance(card, dict) or not card or _is_clip(card):
            return anime
        self._first_season[key] = card
        return card

    def download_pixiv_art(self, cand):
        if self.stopped():
            return False
        if _api.PIXIV_ART_KIND in self._dead_kinds or self.pixiv is None:
            cand.rejected = True
            self._drop_kind(_api.PIXIV_ART_KIND)
            return False
        searched = cand.title_ru
        try:
            # Ищем по первому сезону франшизы, а своё название тайтла
            # оставляем запасным: на Pixiv тег обычно у оригинала.
            first = self._first_season_card(cand.anime)
            also = () if first is cand.anime else (cand.anime,)
            searched = _searched_title(first, cand)
            for _ in range(VISUAL_TRIES):
                data, ext, url, matched, art_link, illust = _pick_art(
                    self, first, also)
                if self.stopped():
                    return False
                # Ответом становится тот тайтл, по ТЕГУ которого арт и нашёлся:
                # рисунок по «Магической битве 2» подписан названием первого
                # сезона, и спрашивать по нему второй сезон было неправильно —
                # ответ не сходился с картинкой (просьба пользователя). Имена
                # файлов считаем заново, до сохранения: иначе они остались бы от
                # прежнего названия.
                if (isinstance(matched, dict) and matched
                        and matched is not cand.anime):
                    cand.anime = matched
                    cand.media_base = self._media_base(cand)
                cand.art_link = art_link
                from .early_repeat import reserve
                if not reserve(self, cand):
                    return False
                verdict = _visual_ok(self, cand, data, ext, illust)
                if verdict is None:
                    return False
                if verdict:
                    break
            else:
                return False
            name = self._save_image(data, f"{cand.file_base}_pixiv_art", ext)
            if not name:
                return False
            cand.frame_url = url
            cand.frame_name = name
            cand.art_link = art_link
            cand.has_frame = True
            self.log(f"Pixiv-арт «{cand.title_ru}»: добавлен.")
            return True
        except PixivArtUnavailable as exc:
            self.log(str(exc))
            self._drop_kind(_api.PIXIV_ART_KIND)
            cand.rejected = True
            return False
        except (PixivArtError, OSError) as exc:
            from pixiv_auth import PixivNetworkError
            if isinstance(exc, PixivNetworkError):
                from .media_transfer import trouble_mark
                trouble_mark()
            self._log_rare("Pixiv-арты", f"Pixiv-арт «{searched}»: {exc}")
            return False


def _searched_title(first: dict, cand) -> str:
    """Как назвать в журнале тот тайтл, по которому И ШЁЛ поиск.

    Раньше в строке ошибки стояло название КАНДИДАТА («Моя геройская академия:
    Битва героев „Юэй“»), хотя искали по первому сезону франшизы, — и выглядело
    это так, будто поиск идёт не туда (просьба пользователя)."""
    name = str((first or {}).get("russian") or (first or {}).get("name") or "")
    own = cand.title_ru or ""
    if not name or name == own:
        return own or name
    return f"{name} (первый сезон для «{own}»)"


# Сколько РАЗНЫХ артов одного тайтла показать Gemini, прежде чем сдаться.
# Отказ относится к картинке, а не к тайтлу: надпись с названием или чужой
# персонаж на одном рисунке ничего не говорят о соседнем (просьба
# пользователя: «надо просто брать другой арт, не меняя тайтл»). Каждая
# попытка — запрос к Gemini, поэтому без счёта не перебираем.
VISUAL_TRIES = 3


@operation("поиск и загрузка Pixiv")
def _pick_art(self, first, also):
    """Один арт по тегу тайтла: данные, расширение, адрес и его карточка.

    Поиск идёт под общим замком вместе с бронью адреса, чтобы параллельные
    потоки не взяли одну и ту же работу. Отвергнутая работа остаётся в
    брони — следующий поиск её уже не предложит."""
    with locked(self, self._pixiv_lock):
        with self._frames_lock:
            excluded = set(self._frames_used)
        # Работы, уже бывшие в выбранных паках («не повторять сами
        # вопросы»), отсеиваются ДО выбора: поздний отказ по отпечатку
        # стоил бы загрузки, проверки Gemini и самого тайтла.
        from .exact_repeat import pixiv_links
        with self._exact_lock:
            skip = pixiv_links(self._exact_keys | self._exact_seen
                               | set(self._exact_pending))
        data, ext, url = self.pixiv.fetch(first, excluded, also=also,
                                          skip_links=skip)
        # И карточка, и ссылка на работу читаются ЗДЕСЬ, под тем же
        # замком: это поля одного общего клиента, и следующий поток
        # перепишет их своим артом. Раньше ссылку брали уже после
        # сохранения картинки — а сохранение это перекодирование в AVIF,
        # секунда с лишним, — и в ответе оказывалась ссылка на арт
        # СОСЕДНЕГО вопроса (просьба пользователя: «по ссылке другая
        # картинка, не та что в вопросе»).
        matched = getattr(self.pixiv, "last_card", None)
        art_link = str(getattr(self.pixiv, "last_link", "") or "")
        illust = getattr(self.pixiv, "last_illust", None)
        with self._frames_lock:
            self._frames_used.add(_api.frame_url_key(url))
    return data, ext, url, matched, art_link, illust


@operation("проверка изображения")
def _visual_ok(self, cand, data, ext, illust):
    """Вердикт Gemini по картинке: True, False или None — сбой, дальше не пробовать."""
    if (not getattr(self.s, "pixiv_gemini_check", True)
            and getattr(self.s, "pixiv_title_check_mode", "gemini") != "local"):
        return True
    from .pixiv_visual_check import check
    try:
        approved, reason = check(self, cand, data, ext, illust)
    except Exception as exc:  # noqa: BLE001 — типы gemini_api
        name = type(exc).__name__
        if name == "GeminiCoolingError":
            from .media_transfer import trouble_mark
            trouble_mark()      # модель на паузе — тайтл повторится позже
        # GeminiDownError — сервер подряд не отвечает (visual_batch): ждать
        # его на каждом арте значит держать рабочие потоки минутами.
        if name in ("GeminiAuthError", "GeminiQuotaError", "GeminiDownError"):
            self.gemini_pixiv = None
            self._drop_kind(_api.PIXIV_ART_KIND)
            cand.rejected = True
            self.log(f"Арты Pixiv отключены: Gemini не может "
                     f"проверять изображения ({exc})")
            return None
        self._log_rare("Проверка Pixiv через Gemini",
                       f"Pixiv-арт «{cand.title_ru}» не прошёл "
                       f"проверку Gemini: {exc}")
        return None
    if not approved:
        self._log_rare(
            "Pixiv-арт отклонён проверкой",
            f"Pixiv-арт «{cand.title_ru}»: арт отклонён "
            f"({reason or 'название или персонажи другого аниме'}), "
            f"берётся другой арт того же тайтла")
    return approved
