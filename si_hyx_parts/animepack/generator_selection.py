# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Генератор: выбор вида вопроса, уровни и средняя, квоты, подбор вопросов и запись пакета."""
from __future__ import annotations
import animepack as _api


# Из каких типов аниме вообще берутся антонимы (просьба пользователя):
# только ТВ-сериалы и полнометражки, без OVA, ONA и спешлов.
ANTONYM_KINDS = ("tv", "movie")


def _level_ok(settings, cand: _api.SongCandidate, kind: str) -> bool:
    """Проходит ли тайтл рамку сложности ИМЕННО этого рода вопросов."""
    low, high = settings.level_range(kind)
    return low <= cand.level <= high


def _antonyms_ok(checked: dict, title_cand) -> bool:
    """Годится ли название под антонимы: тип тайтла и вердикт модели."""
    if str((title_cand.anime or {}).get("kind") or "").lower() not in ANTONYM_KINDS:
        return False
    return bool(checked.get("antonyms"))


def _warn_average(self, bucket) -> None:
    """Один раз за прогон: средняя уступает ради полного пака."""
    if bucket in self._level_warned:
        return
    self._level_warned.add(bucket)
    target = _api.level_avg_target(self.s, bucket)
    where = (" " + _api.BUCKET_TITLES[bucket]) if bucket else ""
    self.log(f"Внимание: средняя сложность{where} {target} не выдерживается — "
             "подходящих тайтлов не хватает, беру что есть: полный пак важнее "
             "точной середины.")


def _note_close_reason(self, kind: str, reason: str) -> None:
    """Первая причина закрытия рода — для строки «больше не получается».

        Повторные жалобы гасит _log_rare, и без этой записи журнал говорил
        только «манга больше не получается» без единого слова почему."""
    reasons = self.__dict__.setdefault("_kind_close_reasons", {})
    if reason and kind not in reasons:
        reasons[kind] = " ".join(str(reason).split())[:300]


def _close_reason(self, kind: str) -> str:
    reason = getattr(self, "_kind_close_reasons", {}).get(kind)
    return f" Причина: {reason}." if reason else ""


def _busy(inflight) -> str:
    """Чем генератор занят прямо сейчас: роды вопросов, которые качаются.

    Порядок — тот же, что в реестре родов вопросов, чтобы подпись не прыгала
    от вопроса к вопросу. Больше трёх родов разом не пишем: полоса внизу окна
    узкая, а смысл подписи — показать, на чём генерация стоит."""
    order = _api.SONG_KINDS + (_api.VIDEO_KIND,) + _api.SILENT_KINDS
    busy = [_api.KIND_TITLES.get(k, k) for k in order if inflight.get(k)]
    if not busy:
        return ""
    return ", ".join(busy[:3]) + ("…" if len(busy) > 3 else "")


class GeneratorSelectionMixin:
    """Генератор: выбор вида вопроса, уровни и средняя, квоты, подбор вопросов и запись пакета."""

    # ── анаграмма ─────────────────────────────────────────────────────────
    def build_anagram(self, cand: _api.SongCandidate) -> bool:
        """Перемешивает буквы названия — весь вопрос-анаграмма и есть.

        Ни сети, ни медиа тут не нужно: название уже лежит в карточке
        Shikimori. Не вышло (на выбранном языке названия нет или оно написано
        не той письменностью, оно короче минимума, длиннее потолка либо это
        продолжение с приставкой) — кандидат уступает место следующему
        тайтлу."""
        limit = max(0, int(getattr(self.s, "anagram_max_chars", 0) or 0))
        source = _api.anagram_source(cand.anime, str(self.s.anagram_lang or "russian"),
                                max_chars=limit)
        if not source:
            why = (f", не длиннее {limit} символов" if limit else "")
            self.log(f"«{cand.title_ru}»: под анаграмму нужно простое название "
                     f"на выбранном языке{why} — беру следующий тайтл")
            return False
        cand.anagram = _api.make_anagram(source, self.rng)
        if not cand.anagram:
            self.log(f"«{cand.title_ru}»: из названия анаграммы не выходит")
            return False
        return True

    # ── вопрос по сюжету (Fandom + Gemini) ────────────────────────────────
    def make_plot_question(self, cand: _api.SongCandidate) -> bool:
        """Достаёт пересказ серии с фэндом-вики и делает из него вопрос.

        Вики есть не у всякого тайтла, а раздел с пересказом — не на всякой
        странице: это нормальный ход дел, и такой кандидат просто уступает
        место следующему. А вот беда с ключом или кончившаяся квота Gemini
        отключают этот род вопросов целиком — иначе на каждый следующий тайтл
        в лог валилась бы та же ошибка."""
        # Клиента забираем В МЕСТНУЮ переменную и дальше зовём только его:
        # соседний поток может обнулить self.gemini прямо посреди работы, и
        # тогда в лог сыпалось «'NoneType' object has no attribute
        # generate_json» вместо настоящей причины.
        gemini = self.gemini
        if gemini is None or self.fandom is None:
            # Ключа нет или он уже отвалился: этот род вопросов в прогоне
            # больше не получится вовсе. Кандидат при этом ни в чём не виноват
            # — медиа мы даже не трогали, и «не скачалось» это не считается.
            self._drop_kind(_api.PLOT_KIND)
            cand.rejected = True
            return False
        names = [cand.anime.get("name"), cand.anime.get("english"),
                 cand.title_ru]
        names = [n for n in (str(x or "").strip() for x in names) if n]
        # Номер продолжения часто есть только в ромадзи (`2nd Season`), а русское
        # название у Shikimori остаётся таким же, как у первой части. Дальше одно
        # и то же явное название используется и для сверки страницы, и в вопросе.
        plot_title = _api.season_title(cand.title_ru, *names)
        try:
            with self._timed("сюжет"):
                got = _api.pick_plot(self.fandom, names, self.rng,
                                     title=plot_title, year=cand.year,
                                     movie=str(cand.anime.get("kind") or "") == "movie")
        except _api.AnimePackApiError as e:
            self._log_rare("Fandom", f"Фэндом-вики: {e}")
            return False
        if not got:
            self._log_rare("Сюжет не найден",
                           f"«{cand.title_ru}»: пересказа на фэндом-вики нет — "
                           "беру следующий тайтл")
            return False
        page = f"{got.get('wiki', '')}|{got.get('page', '')}"
        with self._plot_lock:
            if page in self._plot_seen:
                return False           # эту серию уже спрашивали в этом паке
            self._plot_seen.add(page)
        # Серия могла оказаться из другого сезона: вики нумерует их сплошь, а в
        # каталог попалась карточка первого сезона. Карточку подменяем ДО вопроса —
        # от неё и название в вопросе, и постер в ответе, и имена для маскировки
        # (см. plot_season).
        from .plot_season import apply_season
        with self._timed("сюжет"):
            episode = apply_season(self, cand, str(got.get("source") or ""),
                                   str(got.get("page") or ""))
        names = [cand.anime.get("name"), cand.anime.get("english"), cand.title_ru]
        names = [n for n in (str(x or "").strip() for x in names) if n]
        plot_title = _api.season_title(cand.title_ru, *names)
        mode = str(self.s.plot_mode or "title")
        display_episode = (episode
                           if str(cand.anime.get("kind") or "") != "movie" else "")
        # В режиме «ответ — название» из вопроса вычищаются и сам тайтл, и его
        # написания: иначе вопрос решается с первого слова.
        hide = names + list(cand.anime.get("synonyms") or [])
        try:
            with self._timed("сюжет"):
                from .plot_batch import client_for
                question, answers, explanation = _api.make_question_with_explanation(
                    plot_title or (names[0] if names else ""),
                    got["text"], client_for(self, gemini), mode=mode,
                    page=str(got.get("page") or ""), names=hide,
                    episode=display_episode)
        except Exception as e:  # noqa: BLE001 — тип зависит от gemini_api
            name = type(e).__name__
            self._plot_calls["ошибка" if name != "GeminiBlockedError"
                             else "отказ по правилам"] += 1
            if name == "GeminiBlockedError":
                # Модель не взялась именно за ЭТОТ пересказ (расправа, война —
                # у аниме такое сплошь и рядом). Ключ и квота при этом целы:
                # берём следующий тайтл, а род вопросов не трогаем.
                self._log_rare("Сюжет не по правилам",
                               f"«{cand.title_ru}»: Gemini не берётся за этот "
                               "пересказ — беру следующий тайтл")
                return False
            if name == "GeminiCoolingError":
                from .media_transfer import trouble_mark
                trouble_mark()      # модель на паузе — тайтл повторится позже
            if name in ("GeminiAuthError", "GeminiQuotaError", "GeminiDownError"):
                self.gemini = None
                self._drop_kind(_api.PLOT_KIND)
                cand.rejected = True
                self.log(f"Вопросы по сюжету отключены: {e}")
            else:
                self._log_rare("Gemini", f"Gemini: {e}")
            return False
        self._plot_calls["вопрос" if question else "без вопроса"] += 1
        if not question:
            self._log_rare("Сюжет без вопроса",
                           f"«{cand.title_ru}»: по пересказу вопроса не вышло "
                           "— беру следующий тайтл")
            return False
        cand.plot_question = question
        cand.plot_answers = list(answers)
        cand.plot_explanation = explanation
        wiki = str(got.get("wiki") or "")
        page_name = str(got.get("page") or "")
        cand.plot_source = ", ".join(p for p in (wiki, page_name) if p)
        # Номер серии уже пересчитан под свой сезон (apply_season): у «Моей
        # геройской академии» страница «Episode 73» — это десятая серия четвёртого
        # сезона, и ведущему надо объявить именно её.
        cand.plot_episode = display_episode
        # Страница вики последней строкой ответа: вопрос собран из пересказа, и
        # спорный ответ ведущему надо чем-то подтвердить (просьба пользователя).
        cand.source_link = _api.fandom_page_link(wiki, page_name)
        return True

    def _fetch_media(self, cand: _api.SongCandidate) -> bool:
        if self.stopped():
            return False
        if getattr(cand, "_ready_media", None) == (cand.kind, cand.music_effect):
            return True
        from .early_repeat import reserve as reserve_exact
        if not reserve_exact(self, cand):
            return False
        # «В избранном» у тайтла — вторая мера узнаваемости (просьба
        # пользователя). Спрашивается здесь, а не при отборе: число живёт только
        # на странице Shikimori, то есть стоит запроса на тайтл, и платить за
        # каждую карточку каталога незачем. Индекс, сложность и цена считаются
        # уже с этой поправкой, поэтому рамку сложности рода вопроса проверяем
        # ЗАНОВО — иначе вопрос выехал бы за выставленные рамки.
        with self._timed("в избранном"):
            cand.favorites = self._title_favorites(cand)
        if cand.favorites >= 0:
            from si_hyx_parts.animepack.generator_selection import _level_ok
            if not _level_ok(self.s, cand, cand.kind):
                # Не «не скачалось»: медиа мы даже не трогали.
                self._log_rare("Избранное сдвинуло сложность",
                               f"«{cand.title_ru}»: с учётом «в избранном» "
                               f"узнаваемость стала {cand.level} — за рамками "
                               "этого рода вопросов, беру следующий тайтл")
                cand.rejected = True
                return False
        # Персонажа выбираем ДО имён файлов и до постера: ответом станет самое
        # первое произведение с ним, а значит и постер в ответе, и имена файлов
        # должны быть уже от него (см. _use_first_title).
        if cand.kind == _api.CHAR_KIND:
            with self._timed("персонажи"):
                self._pick_character(cand)
            if cand.character:
                # Сложность должна относиться к дебюту героя, а не к случайному
                # позднему сезону, из которого он был выбран.
                with self._timed("персонажи"):
                    self._use_first_title(cand)
                if cand.rejected or not self._char_level_fits(cand):
                    cand.rejected = True
                    return False
            if not cand.character:
                if not self.stopped():
                    self.log(f"«{cand.title_ru}» без персонажа — беру "
                             "следующий тайтл")
                return False
        cand.media_base = self._media_base(cand)
        # Текстовые вопросы (анаграмма, сюжет) складываются ДО картинок: не
        # вышел вопрос — нечего и качать постер.
        if cand.kind == _api.ANAGRAM_KIND and not self.build_anagram(cand):
            return False
        if cand.kind == _api.PLOT_KIND and not self.make_plot_question(cand):
            return False
        if cand.kind == _api.DIALOGUE_KIND and not self.make_dialogue_question(cand):
            return False
        if cand.kind == _api.DESCRIPTION_AUDIO_KIND and not self.make_description_audio(cand):
            return False
        if not reserve_exact(self, cand):
            return False
        if cand.kind == _api.AI_ART_KIND:
            with self._timed("ИИ-арты"):
                if not self.generate_ai_art(cand):
                    return False
        if cand.kind == _api.PIXIV_ART_KIND:
            with self._timed("Pixiv-арты"):
                if not self.download_pixiv_art(cand):
                    return False
        if cand.kind == _api.MANGA_KIND:
            with self._timed("страницы манги"):
                if not self.download_manga_panel(cand):
                    return False
        if cand.kind == _api.SAKUGA_KIND:
            # Вопрос-сакуга — это сам ролик, и без него вопроса нет.
            with self._timed("сакуга"):
                if not self.download_sakuga(cand):
                    return False
        if cand.kind == _api.EPISODE_KIND:
            with self._timed("отрывки серий"):
                if not self.download_episode(cand):
                    return False
        if cand.kind == _api.STUDIO_KIND:
            # Вопрос-студия: кадров нужно несколько, и качает их свой загрузчик —
            # общий download_images берёт ровно один.
            from .studio_question import download_frames
            with self._timed("картинки"):
                if not download_frames(self, cand):
                    return False
        if not cand.is_silent:
            # Видео-вопрос: если ролика для этой песни нет, вопрос всё равно
            # состоится — просто обычным отрезком звука.
            from .song_video import requested as wants_video
            if wants_video(self.s, cand):
                with self._timed("ролики"):
                    got = self.download_video(cand)
            else:
                got = False
            if not got:
                with self._timed("аудио"):
                    if not self.download_audio(cand):
                        return False
        if cand.is_pixel:
            # Кадр-проявление: сам вопрос — ролик, и без него вопроса нет.
            with self._timed("кадры с эффектами"):
                if not self.download_pixel(cand):
                    return False
        if cand.song_name:
            from .song_multi_anime import enrich
            with self._timed("одинаковые песни"):
                enrich(self, cand)
        try:
            with self._timed("картинки"):
                self.download_images(cand)
        except Exception as e:  # noqa: BLE001 — картинки не критичны
            self.log(f"Картинки «{cand.title_ru}»: {e}")
        if cand.is_picture and not cand.is_pixel and not cand.has_frame:
            if not self.stopped():
                what = "портрета" if cand.is_character else "картинки"
                self.log(f"«{cand.title_ru}» без {what} — беру следующий тайтл")
            return False
        from .entrance_processing import apply as apply_entrance
        return apply_entrance(self, cand)

    def _use_first_title(self, cand: _api.SongCandidate) -> None:
        """Меняет карточку вопроса-персонажа на САМОЕ ПЕРВОЕ произведение, где
        этот персонаж вообще появлялся (просьба пользователя).

        Персонажа мы вытащили из того тайтла, что попался в списке, — а это
        запросто третий сезон или спин-офф. Отвечать «Наруто: Ураганные
        хроники» там, где по-человечески ответ «Наруто», неправильно, поэтому
        спрашиваем у Shikimori все его тайтлы и берём самый ранний по дате
        выхода. Если первое появление проверить не удалось, вопрос пропускаем."""
        char_id = (cand.character or {}).get("id")
        if not char_id:
            cand.rejected = True
            return
        titles = self.db_cache.memo("character_titles", char_id,
                                    _api.ENRICHMENT_CACHE_TTL)
        if titles is None:
            try:
                titles = self.shikimori.character_titles(char_id)
            except _api.AnimePackApiError as e:
                self._log_rare("Где ещё был персонаж",
                               f"Где ещё был «{cand.char_name}»: {e}")
                cand.rejected = True
                return
            self.db_cache.remember_memo("character_titles", char_id, titles)
        else:
            with self._media_cache_lock:
                self._media_cache_hits["метаданные"] += 1
        rows = titles.get("mangas" if cand.is_manga else "animes") or []
        # Анонсы ответом не бывают (просьба пользователя): ни кадра, ни постера у
        # них толком нет, а игроки их не смотрели.
        rows = [row for row in rows if not _api.is_announced(row)]
        # Роль определяет выбор героя, а не дату его дебюта: он мог сначала
        # появиться второстепенным. Формат тоже не меняет хронологию.
        if not cand.is_manga:
            rows = [row for row in rows
                    if str((row or {}).get("kind") or "").lower()
                    not in ("pv", "cm", "music")]
        best, best_date = None, ""
        for row in rows:
            aired = str((row or {}).get("aired_on") or "")
            try:
                rid = int(row.get("id") or 0)
            except (TypeError, ValueError):
                continue
            # Даты Shikimori — «ГГГГ-ММ-ДД», сравниваются как строки. Тайтлы без
            # даты (анонсы) в расчёт не берём: у них ничего не известно.
            if not rid or not aired:
                continue
            if best is None or aired < best_date:
                best, best_date = rid, aired
        if not best:
            cand.rejected = True
            self._log_rare("Первое появление персонажа не подтверждено",
                           f"«{cand.char_name}»: нет выпущенного тайтла с датой "
                           "дебюта — беру другого персонажа")
            return
        if best == int(cand.anime.get("id") or cand.mal_id or 0):
            return
        try:
            cards = (self._mangas_by_ids([best]) if cand.is_manga
                     else self._animes_by_ids([best]))
        except _api.AnimePackApiError as e:
            self.log(f"Первый тайтл франшизы не загрузился: {e}")
            cand.rejected = True
            return
        card = cards[0] if cards else None
        if not isinstance(card, dict) or int(card.get("id") or 0) != best:
            cand.rejected = True
            return
        # В лог о подмене не пишем: это рабочая мелочь отбора, а не событие, и
        # строчка на каждый вопрос-персонаж только засоряла консоль (просьба
        # пользователя).
        cand.anime = card
        cand.favorites = self._title_favorites(cand)

    def _media_base(self, cand: _api.SongCandidate) -> str:
        """Имя медиафайлов вопроса внутри пака — «Сгенерировано в
        SI-HYX(Название тайтла)» (просьба пользователя: чтобы файлы в архиве
        читались глазами, а не числами).

        Одноимённые вопросы (несколько песен одного тайтла при разрешённых
        дублях) разводятся номером в конце — иначе они делили бы один файл."""
        title = _api.safe_filename(cand.title_ru or str(cand.media_key), "Аниме",
                              max_len=80)
        base = f"{_api.MEDIA_NAME_PREFIX}({title})"
        with self._names_lock:
            n = self._names.get(base, 0) + 1
            self._names[base] = n
        return base if n == 1 else f"{base} {n}"

    # ── шаг 4: набор пака ─────────────────────────────────────────────────
    def _prefers_music(self, cand: _api.SongCandidate) -> bool:
        """Тайтл пришёл из списка с пометкой «в основном музыка»?

        Такой список человек ведёт ради песен: тайтл он может и не узнать в
        лицо, а вот опенинг угадает. Поэтому его тайтлы по возможности идут в
        песенные вопросы, а в кадры и персонажи — только если песенных мест уже
        не осталось (просьба пользователя)."""
        if not self._music_nicks:
            return False
        return any(str(n).strip().casefold() in self._music_nicks
                   for n in (cand.users or []))

    def _pick_kind(self, cand: _api.SongCandidate, counts, inflight, quotas):
        """Каким вопросом станет кандидат — или None, если он больше не нужен.

        В смешанном режиме песня может стать вопросом-кадром: карточка аниме у
        неё уже есть, кадр берётся оттуда же. Узкая рамка получает подходящие
        тайтлы прежде широкой; одинаковые рамки делятся по заполненности."""
        from .candidate_options import available_kinds, choose_kind
        options = available_kinds(self, cand, quotas)
        # Keep a usable song for its unfilled quota, including while its slots
        # are downloading. Returning None makes the caller wait for those slots.
        music = [k for k in options if cand.song and k in _api.SONG_KINDS
                 and counts[k] < quotas.get(k, 0)]
        if music:
            options = music
        free = [k for k in options
                if counts[k] + inflight[k] < quotas.get(k, 0)]
        # Книжные доли: экранизованная/нет, манхва, маньхуа.
        if _api.MANGA_KIND in free and not self._manga_mix.allows(cand):
            free.remove(_api.MANGA_KIND)
        if not free:
            return None
        from .average_selection import selection_fits, priority
        fitting = [k for k in free if selection_fits(self, cand, k)]
        if fitting:
            free = fitting
        if self._prefers_music(cand):
            # Песенные места есть — картинки и текст этому тайтлу не предлагаем
            # вовсе.
            songs = [k for k in free if k not in _api.SILENT_KINDS]
            if songs:
                free = songs
        if len(free) == 1:
            return free[0]
        # A title may fit the general average but fail the art/song average.
        # Assign the compatible category before any download starts.
        if any(priority(self, cand, k) for k in free):
            return min(free, key=lambda k: (self.s.level_range(k)[1] - self.s.level_range(k)[0],
                                           priority(self, cand, k),
                                           (counts[k] + inflight[k]) / max(1, quotas[k])))
        return choose_kind(self.s, free, counts, inflight, quotas)

    def _level_fits(self, cand: _api.SongCandidate, levels: list,
                    kind: _api.Optional[str] = None, flying=()) -> bool:
        """Не принимать вопрос, после которого заданная средняя недостижима.

        Полный пак важнее точной середины (просьба пользователя). Клапан: после
        LEVEL_AVG_GIVE_UP подряд отвергнутых кандидат проходит, а в журнале
        пишется, что средняя не выдерживается. Строгие цели (своя средняя
        песен, «строгие цели» манги) не уступают — см. average_selection.yields."""
        from .average_selection import fits, character_fits, yields
        flying = tuple(flying)
        questions = tuple(getattr(self, '_selected_songs', ())) + flying
        if not character_fits(self, cand, kind, questions):
            return False
        kind = cand.kind if kind is None else kind
        bucket = _api.own_bucket(self.s, kind)
        if fits(self, cand, levels, kind, flying):
            self._level_skips[bucket] = 0
            return True
        if not yields(self, kind):
            return False
        if self._level_skips[bucket] < self.LEVEL_AVG_GIVE_UP:
            self._level_skips[bucket] += 1
            return False
        self._level_skips[bucket] = 0
        _warn_average(self, bucket)
        return True

    def _remember_level(self, cand: _api.SongCandidate, levels: list) -> None:
        """Запоминает узнаваемость принятого вопроса в его корзине."""
        bucket = _api.own_bucket(self.s, cand.kind)
        if bucket is None:
            levels.append(cand.level)
        else:
            self._bucket_levels.setdefault(bucket, []).append(cand.level)

    # ── отложенные ради средней сложности ─────────────────────────────────
    def _bench_candidate(self, cand) -> None:
        """Откладывает кандидата, который прямо сейчас увёл бы среднюю.

        Раньше такой выбрасывался навсегда: за прогон так сгорел 321 кандидат,
        а пак всё равно остался недобранным (116 вопросов из 144). Клапан
        LEVEL_AVG_GIVE_UP тут не спасал — любой случайно прошедший кандидат
        обнулял счётчик подряд отвергнутых.

        Бронь на франшизу отпускается: пока кандидат ждёт, серия должна
        оставаться доступной другим тайтлам. Ключи брони запоминаются, и при
        возврате со скамейки франшиза занимается заново (_rebook_candidate)."""
        self._level_benched += 1
        if len(self._level_bench) < self._level_bench_cap:
            self._level_bench.append(cand)
        self._release_candidate(cand)

    def _take_level_bench(self, levels=(), flying=()) -> list:
        """Отложенные ради средней — и дальше середина не сторожится.

        Зовётся, когда основной поток кандидатов иссяк, а мест в паке ещё
        полно. Ближайшие к просимой середине идут первыми: так средняя
        уезжает настолько мало, насколько это вообще возможно."""
        # Остаток раннего добора аниме (см. _take_anime_bench) — тоже сюда.
        early, self._anime_bench = self._anime_bench, []
        if self._level_relaxed or not (self._level_bench or early):
            return []
        bench, self._level_bench = self._level_bench, []
        # Дальше середина не сторожится (кроме строгих целей, см. yields).
        self._level_relaxed = True
        self._level_reused += len(bench)
        bench.sort(key=self._bench_distance(levels, flying))
        bench = early + bench
        self.log(f"Внимание: кандидаты кончились, а пак не набран — беру "
                 f"отложенных ради средней сложности ({len(bench)} шт.), ближайших "
                 "к ней первыми; средняя может уйти от заданной: полный пак важнее "
                 "точной середины.")
        return bench

    def _bench_distance(self, levels, flying):
        """Насколько кандидат со скамейки уведёт свою корзину от середины."""
        flying = tuple(flying)

        def distance(cand):
            bucket = _api.own_bucket(self.s, cand.kind)
            target = _api.level_avg_target(self.s, bucket)
            seen = (levels if bucket is None else self._bucket_levels.get(bucket, ()))
            current = sum(seen) + sum(int(c.level) for c in flying
                                      if _api.own_bucket(self.s, c.kind) == bucket)
            return abs(current + int(cand.level) - target * (len(seen) +
                       sum(_api.own_bucket(self.s, c.kind) == bucket for c in flying) + 1))
        return distance

    def _take_anime_bench(self, levels=(), flying=()):
        """Следующий отложенный ради средней тайтл аниме — не дожидаясь книг.

        Каталог аниме разобран до конца, а каталог книг ещё перебирается. Раньше
        отложенные аниме ждали, пока кончатся и книги: в логе пользователя пак
        стоял на 129 из 144 пять минут, пока каталог книг досматривался на
        1600 карточек, хотя для опенингов и кадров на скамейке лежало 1821
        кандидата. Книжные кандидаты остаются на скамейке, и середина для книг
        по-прежнему сторожится."""
        if self._level_relaxed:
            return None
        if not self._anime_level_relaxed:
            feed = getattr(self, "_card_feed", None)
            manga_live = (_api.MANGA_KIND not in self._closed_streams
                          and int(self.s.question_quotas.get(_api.MANGA_KIND, 0) or 0))
            if feed is None or not feed.drained or not manga_live:
                # Без живого потока книг каталог кончится сразу следом —
                # тогда отложенных выдаёт общий добор (_take_level_bench).
                return None
            anime = [c for c in self._level_bench if not c.is_manga]
            if not anime:
                return None
            self._level_bench = [c for c in self._level_bench if c.is_manga]
            self._anime_level_relaxed = True
            self._level_reused += len(anime)
            anime.sort(key=self._bench_distance(levels, flying))
            self._anime_bench = anime
            self.log(f"Каталог аниме разобран, а пак не набран — беру отложенных "
                     f"ради средней сложности ({len(anime)} шт.), ближайших к ней "
                     "первыми, не дожидаясь конца каталога книг; средняя может "
                     "уйти от заданной: полный пак важнее точной середины.")
        return self._anime_bench.pop(0) if self._anime_bench else None

    def _rebook_candidate(self, cand) -> bool:
        """Снова занимает франшизу кандидата, вернувшегося со скамейки.

        Пока он ждал, его серию мог занять другой тайтл — тогда кандидат
        больше не нужен, иначе в паке оказалась бы пара вопросов из одной
        серии. Свежему кандидату (бронь при нём) проверка ничего не стоит."""
        keys = getattr(cand, "_bench_keys", None)
        if not keys:
            return True
        cand._bench_keys = None
        with self._studio_lock:
            if not self.s.dup_franchise and any(k in self._used_franchise
                                                for k in keys if k):
                return False
            self._used_franchise.update(k for k in keys if k)
        cand._reserved = keys
        return True

    def _char_reach(self, cand: _api.SongCandidate) -> tuple[int, int]:
        """Единственный достижимый уровень героя — уровень его тайтла."""
        base = cand.level
        return (_api.char_question_level(base, self._FAV_ALL),
                _api.char_question_level(base, 0))

    def _char_level_fits(self, cand: _api.SongCandidate) -> bool:
        """Preserve the user's character average without silently changing its target."""
        from .average_selection import character_fits
        return character_fits(self, cand)

    def _remember_char_level(self, cand: _api.SongCandidate) -> None:
        """Запоминает сложность принятого вопроса-персонажа."""
        if not cand.is_character:
            return
        with self._char_lock:
            self._char_levels.append(cand.char_level)

    def _drop_kind(self, kind: str, reason: str = "") -> None:
        """Помечает род вопросов как больше не получающийся в этом прогоне.

        Зовётся из рабочего потока (Gemini отваливается прямо на загрузке), а
        разбирается с этим главный цикл отбора: свободные места надо отдать
        оставшимся родам, иначе они так и будут жечь кандидатов впустую."""
        with self._warn_lock:
            self._dead_kinds.add(kind)
            _note_close_reason(self, kind, reason)

    def _spend_kind(self, kind: str, reason: str = "") -> None:
        """Кандидаты этого рода вопросов кончились (вычерпан свой каталог).

        Не то же самое, что _drop_kind: сам род работает, и уже запущенные
        загрузки надо довести до конца. Главному циклу это говорит одно —
        новых вопросов такого рода не будет, свободные места пора отдать
        остальным. Без этого доля манги, чей каталог в сотню карточек кончился
        первым, до конца прогона требовала кандидатов, и цикл жёг на неё всю
        базу аниме (ни один тайтл аниме мангой стать не может)."""
        with self._warn_lock:
            self._spent_kinds.add(kind)
            _note_close_reason(self, kind, reason)

    def _close_spent_streams(self, quotas: dict, counts, deferred=()) -> None:
        """Закрывает поток книг, когда просить их больше незачем.

        Карточка манги приезжает из своего каталога и ничем, кроме вопроса по
        манге, стать не может. Пока поток открыт, цикл отбора продолжает его
        просить (места-то в паке ещё есть — под сакугу, кадры, песни), каждую
        лишнюю книгу отправляет на скамейку и платит за это разбором связей и
        экранизаций целой пачки карточек.

        Закрываем в двух случаях:

        * книжная доля набрана. Считаем по ПРИНЯТЫМ вопросам, а не по
          запущенным загрузкам: сорвавшаяся загрузка иначе оставила бы долю
          недобранной, а поток уже закрытым;
        * книг просмотрено вдоволь (BOOK_SCAN_PER_SLOT на место), а долю и так
          есть чем добрать — отложенных на скамейке хватает. Дальше каталог
          перебирается уже впустую: в логе пользователя так было просмотрено
          48 050 карточек и отложено 39 149 при доле в двадцать вопросов.

        Закрываем вместе со `_spend_kind`: иначе места умерших родов вопросов
        могли бы вернуться манге, которую больше неоткуда взять."""
        self._rest_anime_streams(quotas, counts)
        kind = _api.MANGA_KIND
        ended = getattr(self, "_manga_catalog_end", "")
        if (ended and getattr(self, "_manga_drawn", 0) >= getattr(self, "_manga_yielded", 0)
                and not any(c.is_manga for c in (*deferred, *self._level_bench))
                and not self._manga_mix.bench_size):
            # Каталог кончился, и все его книги дошли до отбора: раньше доля
            # закрывалась, пока последние ещё стояли в очереди проверок.
            self._manga_catalog_end = ""
            self._spend_kind(kind, ended)
        if kind in self._closed_streams:
            return
        quota = int(quotas.get(kind, 0) or 0)
        if not quota:
            return
        done = counts[kind]
        if done < quota:
            budget = max(self.BOOK_SCAN_MIN, quota * self.BOOK_SCAN_PER_SLOT)
            bench = self._manga_mix.bench_size
            # Отложенных должно хватать на весь остаток доли БЕЗ учёта запущенных
            # загрузок: сорвавшаяся иначе оставила бы долю недобранной, а каталог
            # уже закрытым.
            if self._manga_seen < budget or done + bench < quota:
                return
            self.log(f"Каталог книг просмотрен на {self._manga_seen} карточек — "
                     f"дальше беру из отложенных ({bench} шт.): подходящих по "
                     "книжным долям больше не попадается, а перебирать каталог "
                     "до конца — только время.")
            # Закрываем ТОЛЬКО поток каталога. Долю книг при этом не хороним:
            # добрать её есть чем — отложенных на скамейке хватает на весь
            # остаток. `_spend_kind` тут был прямой ошибкой: он пускал
            # `_share_out_dead`, тот на каждом круге срезал книжную квоту до уже
            # набранного и раздавал места родам вопросов, чей каталог давно
            # кончился. В логе пользователя так ушли четыре места (16 книг вместо
            # 20 при 400 отложенных), и пак вышел 140 вопросов из 144.
            self._closed_streams.add(kind)
            return
        self._closed_streams.add(kind)
        self._spend_kind(kind, "книжная доля набрана")

    def _rest_anime_streams(self, quotas: dict, counts) -> None:
        """Усыпляет потоки аниме, пока набирается одна манга.

        Все остальные доли набраны ПРИНЯТЫМИ вопросами — тайтлу аниме места
        нет, а поток продолжал выдавать карточки: каждую разбирали, проверяли
        и откладывали. Сон обратим: перераспределение квот снова откроет
        места, и потоки проснутся; кончится каталог книг — _merge_streams
        сам вернётся к спящим."""
        idle = getattr(self, "_idle_streams", None)
        if idle is None:
            return
        with self._warn_lock:
            gone = self._dead_kinds | self._spent_kinds
        manga = _api.MANGA_KIND
        full = all(counts[k] >= int(n or 0) for k, n in quotas.items()
                   if k != manga and k not in gone)
        wanted = (int(quotas.get(manga, 0) or 0) > counts[manga]
                  and manga not in gone and manga not in self._closed_streams)
        if full and wanted:
            if not idle:
                idle.update(("anime", "silent"))
                self.log("Доли аниме набраны — дальше спрашиваю только книги.")
        elif idle:
            idle.clear()

    def _share_out_dead(self, quotas: dict, counts, inflight) -> None:
        """Отдаёт места отвалившихся родов вопросов остальным.

        Без этого пак недобирался на ровном месте: доля «по сюжету» с
        кончившимся ключом Gemini продолжала просить кандидатов, каждый из них
        тут же отваливался, и база кончалась раньше, чем набирались анаграммы
        (лог пользователя: 21 вопрос из 48 при живых 2891 тайтлах)."""
        with self._warn_lock:
            dead = sorted(self._dead_kinds | self._spent_kinds)
        if getattr(self.s, 'preserve_composition', True):
            # Доли не перекладываем, но и пак не рвём: остальные роды вопросов
            # набираются до конца, а недобор называется в итоге. Раньше здесь
            # летела ошибка, и недоступный Pixiv обрывал пак на третьем вопросе.
            for kind in dead:
                left = quotas.get(kind, 0) - counts[kind] - inflight[kind]
                if left <= 0:
                    continue
                quotas[kind] = counts[kind] + inflight[kind]
                self._closed_kinds[kind] = self._closed_kinds.get(kind, 0) + left
                name = _api.KIND_TITLES.get(kind, kind).lower()
                self.log(f"«{name}» больше не получается — {left} мест "
                         "не занимаю (доли не перекладываются: «сохранять "
                         "состав»), остальной пак набираю дальше."
                         + _close_reason(self, kind))
            return
        for kind in dead:
            alive = [k for k in quotas
                     if quotas.get(k, 0) > 0 and k not in dead]
            if not alive:
                # Закрываем квоту целиком, включая уже запущенные попытки. Иначе
                # при восьми потоках она уменьшалась сперва на 89, затем ещё семь
                # раз по одному — ровно такой шум был в журнале пользователя.
                left = quotas.get(kind, 0) - counts[kind]
                if left <= 0:
                    continue
                quotas[kind] = counts[kind]
                name = _api.KIND_TITLES.get(kind, kind).lower()
                self.log(f"Мест под «{name}» больше не занимаю ({left} шт.) — "
                         "переложить их не на кого, пак будет короче."
                         + _close_reason(self, kind))
                continue
            left = quotas.get(kind, 0) - counts[kind] - inflight[kind]
            if left <= 0:
                continue
            quotas[kind] = counts[kind] + inflight[kind]
            name = _api.KIND_TITLES.get(kind, kind).lower()
            # Крупные доли первыми: лишние места достаются тому рода вопросов,
            # которого в паке и так больше всего.
            alive.sort(key=lambda k: (-quotas[k], k))
            for i in range(left):
                quotas[alive[i % len(alive)]] += 1
            where = ", ".join(_api.KIND_TITLES.get(k, k).lower() for k in alive)
            self.log(f"Оставшиеся места «{name}» ({left} шт.) отдаю "
                     f"остальным: {where}." + _close_reason(self, kind))

    def select_songs(self) -> list:
        """Набирает ровно столько вопросов, сколько в паке, соблюдая квоты по
        типам. Медиа качаются параллельно прямо по ходу отбора."""
        total = self.s.total_questions
        from .early_repeat import reserve as reserve_exact
        quotas = self.s.question_quotas
        self._selection_quotas = quotas
        from music_effects import EffectSlots
        effect_slots = EffectSlots(self.s, sum(quotas.get(k, 0) for k in _api.SONG_KINDS))
        self._effect_slots = effect_slots
        self._manga_mix.sync(quotas.get(_api.MANGA_KIND, 0))
        accepted: list[_api.SongCandidate] = []
        # Keep the live list: selection itself can fail after preparing media.
        # run() saves it only after the worker pool has stopped.
        self._selected_songs = accepted
        levels: list[int] = []          # узнаваемость набранного (level_avg)
        counts: _api.Counter = _api.Counter()
        inflight: _api.Counter = _api.Counter()
        from .title_eligibility import checked_candidates
        candidates = checked_candidates(self, self.iter_candidates())
        exhausted = False
        source_error = None
        over_budget = False
        from .generation_priority import parallel_limit
        from .candidate_source import CandidateSource
        from .selection_results import collect_finished
        from .candidate_reserve import CandidateReserve, remember
        reserve = CandidateReserve(self, quotas)
        workers = parallel_limit(self.s)
        runtime = self._runtime
        runtime.begin_selection()
        from .selection_resources import guarded_fetch, take_deferred, capacity
        fetch_media = runtime.wrap_task(
            self._diagnostics.wrap(guarded_fetch(self), _api.KIND_TITLES))
        self.log(f"Параллелизм: запрошено {self.s.parallel}, "
                 f"действующий лимит {workers} задач.")
        self.log(f"Кодирование AV1: лимит {runtime.encoder_limit} процессов одновременно.")
        pending: dict = {}
        self._selection_state = ()
        # Кандидат, которому место в паке есть, но прямо сейчас оно занято
        # ЗАГРУЗКОЙ. Такого не выбрасываем: дождёмся свободного потока и возьмём
        # его же. Копится не больше `workers` (см. ниже): без потолка книжный род
        # с ёмкостью в `workers` загрузок откладывал каждую следующую карточку и
        # за минуту сжигал весь каталог (2715 годных книг — 11 попыток).
        deferred: list = []

        self._progress(0, total, "Отбираю вопросы…")
        # Пул НЕ через `with`: выход из блока ждал бы конца всех запущенных
        # загрузок, и «Стоп» отзывался бы только через десятки секунд. Здесь
        # очередь сбрасывается, а работающие ffmpeg убиваются сразу.
        source = CandidateSource(self, candidates)
        # Чей исход ещё неизвестен — по этому поток карточек ждёт серии отложенных.
        self._selection_waits = lambda: bool(pending or deferred or source.pending)
        pool = _api.ThreadPoolExecutor(max_workers=runtime.worker_capacity,
                                      thread_name_prefix="animepack")
        self._defer_cache_writes = True
        try:
            try:
                while not self.stopped():
                    workers = parallel_limit(self.s)
                    done = [future for future in pending if future.done()]
                    over_budget = collect_finished(
                        self, done, pending, accepted, counts, inflight, levels,
                        quotas, effect_slots, deferred, total, reserve)
                    self._selection_state = tuple(accepted) + tuple(pending.values())
                    if over_budget:
                        mb = self._bytes_used / (1024.0 * 1024.0)
                        self.log(
                            f"Пак упрётся в потолок {self.s.max_pack_mb} МБ: "
                            f"останавливаюсь на {len(accepted)} вопросах из "
                            f"{total} ({mb:.1f} МБ набрано). Дайте паку больше "
                            "мегабайт или ужмите медиа.")
                        break
                    if len(accepted) >= total:
                        break
                    # Род вопросов мог отвалиться совсем (кончился ключ Gemini) —
                    # его места надо отдать остальным ДО того, как просить
                    # следующего кандидата.
                    self._close_spent_streams(quotas, counts, deferred)
                    if self._dead_kinds or self._spent_kinds:
                        self._share_out_dead(quotas, counts, inflight)
                        effect_slots.expand(self.s, sum(quotas.get(k, 0) for k in _api.SONG_KINDS))
                        self._manga_mix.sync(quotas.get(_api.MANGA_KIND, 0))
                    self._song_lookup_needed = any(
                        quotas.get(kind, 0) > counts[kind]
                        for kind in _api.SONG_KINDS + (_api.VIDEO_KIND,)
                        if kind not in self._dead_kinds)
                    # Сколько песенных мест ещё не занято ни готовым, ни качающимся
                    # вопросом: по нему поток карточек решает, можно ли отдать
                    # тайтл с песней под кадр (см. AnimeCardFeed._song_supply_ok).
                    self._song_slots_left = sum(
                        max(0, quotas.get(kind, 0) - counts[kind] - inflight[kind])
                        for kind in _api.SONG_KINDS + (_api.VIDEO_KIND,)
                        if kind not in self._dead_kinds)
                    # Досыпаем задач, пока есть куда: набранное + в работе < нужного.
                    scanned = 0
                    while ((not exhausted or deferred or reserve)
                           and len(accepted) + sum(inflight.values()) < total
                           and len(pending) < workers * 2
                           and any(quotas[k] > counts[k] + inflight[k]
                                   for k in quotas if k not in self._dead_kinds)):
                        # Проверяем на КАЖДОМ кандидате, а не раз за круг: этот
                        # цикл не выходит наружу, пока есть кого просить, и
                        # каталог книг успел бы вычерпаться целиком.
                        if any(future.done() for future in pending):
                            break
                        workers = parallel_limit(self.s)
                        scanned += 1
                        if scanned > 32:
                            break
                        self._close_spent_streams(quotas, counts, deferred)
                        cand = take_deferred(deferred, inflight, workers)
                        if cand is None and len(deferred) >= workers:
                            break   # отложенные ждут потоков — каталог не трогаем
                        if cand is None:
                            cand = reserve.take(counts, inflight, quotas)
                            if cand is None and not exhausted and any(
                                    quotas[k] > counts[k] + inflight[k] for k in quotas
                                    if k != _api.MANGA_KIND and k not in self._dead_kinds):
                                cand = self._take_anime_bench(levels, pending.values())
                            if cand is None:
                                if exhausted or not source.request().done():
                                    break
                                try:
                                    cand = source.take()
                                except Exception as error:
                                    source_error = error
                                    exhausted = True
                                    break
                                if cand is not None and cand.is_manga:
                                    self._manga_drawn = getattr(self, "_manga_drawn", 0) + 1
                        if cand is not None and cand.is_manga:
                            # Сколько книг каталог уже отдал: по этому счёту
                            # решается, не пора ли перейти на отложенных (см.
                            # _close_spent_streams).
                            self._manga_seen += 1
                        if cand is None:
                            # Кандидаты кончились — но часть книг могла лежать на
                            # скамейке из-за книжных долей. Недобранный пак хуже
                            # перекоса долей, поэтому отложенные идут в дело.
                            # ...но только если книжной доле ещё есть куда их
                            # класть: иначе отложенные пройдут весь путь до
                            # _pick_kind и будут выброшены до единой.
                            free = (quotas.get(_api.MANGA_KIND, 0)
                                    - counts[_api.MANGA_KIND]
                                    - inflight[_api.MANGA_KIND])
                            bench = (self._manga_mix.take_bench() if free > 0
                                     else [])
                            if not bench:
                                # Следом за книгами — отложенные ради средней
                                # сложности: недобранный пак хуже промаха по
                                # середине (см. _take_level_bench).
                                bench = self._take_level_bench(levels, pending.values())
                            if bench:
                                # Запас и книжная скамейка могут хранить один
                                # объект. Передаём его источнику только один раз.
                                for returned in bench:
                                    reserve.withdraw(returned)
                                # Книги снова в очереди: долю не закрываем, пока не дойдут.
                                self._manga_yielded = (getattr(self, "_manga_yielded", 0)
                                                       + sum(c.is_manga for c in bench))
                                source.replace(bench)
                                continue
                            exhausted = True
                            break
                        reserve.withdraw(cand)
                        if not self._rebook_candidate(cand):
                            # Пока кандидат лежал на скамейке, его серию занял
                            # другой тайтл — двух вопросов из одной серии в паке
                            # быть не должно.
                            self._drops["франшизу заняли, пока кандидат ждал"] += 1
                            continue
                        remember(cand)
                        kind = self._pick_kind(cand, counts, inflight, quotas)
                        if kind is None:
                            # Мест под этот тайтл нет — но почему? Если они заняты
                            # не набранными вопросами, а теми, что качаются прямо
                            # сейчас, кандидата надо ДОЖДАТЬСЯ, а не выбросить:
                            # иначе редкий род вопросов (сакуга, места, манга) в
                            # восемь потоков сжигал базу целиком за пару секунд —
                            # 1732 годных тайтла на 7 попыток загрузки.
                            if self._pick_kind(cand, counts, _api.Counter(),
                                               quotas) is not None:
                                deferred.append(cand)
                                break       # ждём, пока освободится поток
                            # Вопросом кандидат не стал — франшизу за ним не
                            # держим, она ещё пригодится другому тайтлу серии.
                            self._drops["мест под такой тайтл уже не осталось"] += 1
                            self._release_candidate(cand)
                            reserve.park(cand)
                            continue        # квоты подходящих типов уже заняты
                        from .title_selection import TITLE_QUESTION_KINDS
                        variant = getattr(cand, "_title_variant", None)
                        if kind in TITLE_QUESTION_KINDS and variant is not None:
                            cand.anime = variant.anime
                        if not self._level_fits(cand, levels, kind,
                                                pending.values()):
                            # НЕ выбрасываем: кандидат не подходит под нынешнюю
                            # середину, но вполне подойдёт под неё позже или
                            # сгодится в финальном доборе.
                            self._bench_candidate(cand)
                            continue        # средняя сложность уехала бы дальше
                        cand.kind = kind    # в смешанном режиме тип мог смениться
                        if inflight[kind] >= capacity(kind, workers):
                            deferred.append(cand)
                            continue
                        if kind in _api.SONG_KINDS and effect_slots.refuses(cand):
                            self._drops["нет готовых таймингов, а свободно только караоке"] += 1
                            self._release_candidate(cand)
                            reserve.park(cand, failed=True)
                            continue
                        if not reserve_exact(self, cand):
                            if getattr(cand, "_exact_waiting", False):
                                deferred.append(cand)
                                break
                            self._drops["тот же вопрос — отсечён до загрузки"] += 1
                            self._release_candidate(cand)
                            reserve.park(cand, failed=True)
                            continue
                        if kind in _api.SONG_KINDS:
                            effect_slots.reserve(cand)
                            from .song_downloads import prefetch
                            prefetch(self, cand)
                        inflight[kind] += 1
                        self._tries[kind] += 1
                        self._manga_mix.reserve(cand)
                        cand._queued_at = _api.time.monotonic()
                        pending[pool.submit(fetch_media, cand)] = cand
                        self._selection_state = tuple(accepted) + tuple(pending.values())
                    waiting = list(pending)
                    if source.future is not None and not source.future.done():
                        waiting.append(source.future)
                    if not waiting:
                        if not any(quotas[k] > counts[k] for k in quotas if k not in self._dead_kinds):
                            break
                        if deferred or reserve.retry_wait() or scanned > 32 and not exhausted:
                            _api.time.sleep(0.1)
                            continue
                        if exhausted and reserve.redistribute(quotas, counts):
                            effect_slots.expand(self.s, sum(
                                quotas.get(k, 0) for k in _api.SONG_KINDS))
                            self._manga_mix.sync(quotas.get(_api.MANGA_KIND, 0))
                            continue
                        break
                    from .progress_heartbeat import beat
                    beat(self, len(accepted), total, inflight)
                    _api.wait(waiting, timeout=0.1, return_when=_api.FIRST_COMPLETED)
            finally:
                for fut in pending:
                    fut.cancel()
        finally:
            # Ненужные ffmpeg прекращаем на любом выходе: не только по «Стоп», но
            # и после набора пака или исключения. Уже запущенный Future отменить
            # нельзя, поэтому обязательно дожидаемся его выхода. Иначе он успевает
            # менять общий кэш во время save(), а cleanup удаляет Images у него из
            # под ног — отсюда шли обе ошибки живого прогона.
            runtime.end_selection()
            self._selection_waits = None
            self.stop_processes()
            try:
                source.close()
            finally:
                from .song_downloads import close as close_downloads
                close_downloads(self)
                pool.shutdown(wait=True, cancel_futures=True)
                with self._exact_lock:
                    self._exact_pending.clear()
                # Include new metadata on success, cancellation and exceptions.
                # No producers can still mutate it or trigger another checkpoint.
                self._defer_cache_writes = False
                self.db_cache.save()
        self._selection_end = {"exhausted": exhausted, "over_budget": over_budget}
        if source_error is not None and len(accepted) < total and not self.stopped():
            raise _api.AnimePackError(f'Источник кандидатов прервался: {source_error}. '
                                     f'Готово {len(accepted)} вопросов; они будут сохранены.') from source_error
        if reserve.returned:
            self.log(f"Из сохранённого запаса вернулись в отбор: "
                     f"{reserve.returned} кандидатов.")

        if self.s.only_kind:
            self.log(f"Отобрано тайтлов: {len(accepted)} из {total}")
        else:
            # OST — аббревиатура, строчными её писать нельзя.
            by_kind = ", ".join(
                f"{_api.KIND_TITLES[k] if _api.KIND_TITLES[k].isupper() else _api.KIND_TITLES[k].lower()}"
                f": {counts[k]}"
                for k in (_api.SONG_KINDS + (_api.VIDEO_KIND,) + _api.SILENT_KINDS)
                if quotas.get(k))
            self.log(f"Отобрано вопросов: {len(accepted)} из {total} ({by_kind})")
        from .song_video import log_summary as log_video_summary
        log_video_summary(self, accepted)
        if self.s.karaoke_enabled:
            made = sum(c.music_effect == "karaoke" and c.has_video for c in accepted)
            self.log(f"Караоке: готово {made} из {effect_slots.slots.count('karaoke')} запланированных")
        if self.s.chiptune_enabled:
            made = sum(c.music_effect == "chiptune" for c in accepted)
            target = effect_slots.slots.count("chiptune")
            self.log(f"Chiptune: готово {made} из {target} запланированных; "
                     f"отказов при подготовке {effect_slots.failures}.")
        if self.s.cover_enabled:
            made = sum(c.music_effect == "cover" for c in accepted)
            self.log(f"Каверы: готово {made} из {effect_slots.counts.get('cover', 0)} "
                     "запланированных.")
            if "cover" in effect_slots.dropped:
                why = effect_slots.reasons.get("cover", "")
                self.log(f"Каверы отключились ({why}) — остальные музыкальные "
                         "вопросы играют оригиналом." if why else
                         "Каверов не находилось слишком часто — остальные "
                         "музыкальные вопросы играют оригиналом.")
                # Самая частая причина пустого прогона — не сеть, а слишком
                # Высокая нижняя граница схожести: вокальное исполнение обычно
                # около 53%, фортепианное — 34% (см. cover_match).
                if not made and int(self.s.cover_amq_from) > 45:
                    self.log(f"Минимальная схожесть кавера с оригиналом — "
                             f"{self.s.cover_amq_from}%. По замерам вокальный кавер "
                             "набирает около 53%, фортепианный — 34%, так что почти "
                             "все найденные исполнения отсеиваются ею. Опустите "
                             "нижнюю границу, если каверы нужны.")
        if levels:
            avg = sum(levels) / len(levels)
            target = int(self.s.level_avg or 0)
            aim = f" (просили {target})" if target else ""
            # Роды вопросов со своей средней (арты, манга, песни…) в эту цифру не
            # входят — так и пишем. Без приписки строка «Средняя сложность пака:
            # 7.2» рядом с «всего пака: 6.9» выглядела ошибкой счёта.
            own = [_api.BUCKET_TITLES[b] for b in _api.LEVEL_BUCKETS
                   if self._bucket_levels.get(b)]
            where = f" без {', '.join(own)}" if own else ""
            self.log(f"Средняя сложность пака{where}: {avg:.1f}{aim}")
        # Арты, книги и сюжет со своей средней считаются отдельной строкой — в
        # общую они не входят вовсе (см. level_avg.py). Перебираем реестр корзин,
        # а не список имён: иначе новая корзина молча теряет строку в журнале.
        for bucket in _api.LEVEL_BUCKETS:
            seen = self._bucket_levels.get(bucket) or []
            if not seen:
                continue
            target = _api.level_avg_target(self.s, bucket)
            aim = f" (просили {target})" if target else ""
            self.log(f"Средняя сложность {_api.BUCKET_TITLES[bucket]}: "
                     f"{sum(seen) / len(seen):.1f}{aim}")
        # Своя середина у части пака — и общая строка выше уже не про весь пак.
        # Весь пак считается так же, как «(Ур. N)» в его названии.
        if any(self._bucket_levels.get(b) for b in _api.LEVEL_BUCKETS):
            every = [int(c.level) for c in accepted if int(c.level or 0) > 0]
            if every:
                self.log(f"Средняя сложность всего пака (она же в названии): "
                         f"{sum(every) / len(every):.1f}")
        # Персонажей выделяем отдельной строкой; их уровень равен уровню тайтла,
        # но собственную рамку/среднюю настройки по-прежнему сохраняют.
        chars = [c for c in accepted if c.is_character]
        if chars:
            avg = sum(c.char_level for c in chars) / len(chars)
            target = int(getattr(self.s, "char_level_avg", 0) or 0)
            eff = int(self._char_target_eff or 0)
            aim = f" (просили {target})" if target else ""
            if target and eff and eff != target:
                # Просимая сложность оказалась недостижимой — говорим, какую
                # держали вместо неё, иначе цифра выглядит промахом.
                aim = f" (просили {target}, достижимо {eff})"
            known = [c.char_favorites for c in chars if c.char_favorites >= 0]
            fav = (f", в избранном в среднем у {sum(known) / len(known):.0f} чел."
                   if known else "")
            self.log(f"Средняя сложность персонажей: {avg:.1f}{aim}{fav}")
        if self._failed_media:
            self.log(f"Не скачалось и заменено: {self._failed_media}")
        if self._poster_hits or self._poster_tmdb:
            parts = []
            if self._poster_hits:
                parts.append(f"из кладовой обложек {self._poster_hits}")
            if self._poster_tmdb:
                parts.append(f"с TMDB {self._poster_tmdb}")
            self.log("Обложки: " + ", ".join(parts) + ".")
        with self._media_cache_lock:
            cache_hits = list(self._media_cache_hits.items())
        if cache_hits:
            parts = [f"{name}: {count}" for name, count in cache_hits if count]
            if parts:
                self.log("Повторно использовано из кэша — " + ", ".join(parts) + ".")
        # Кладовая обложек не должна расти без конца: лишнее выбрасывается по
        # времени последнего обращения (см. poster_cache.prune).
        if getattr(self.s, "poster_cache", True):
            gone = _api.poster_cache.prune()
            if gone:
                self.log(f"Кладовая обложек подчищена: убрано {gone} давних.")
            gone = _api.media_cache.prune()
            if gone:
                self.log(f"Кэш медиа подчищен: убрано {gone} давних файлов.")
        # Недобор объясняем и тогда, когда каталог не кончился, а род вопросов
        # закрылся (Gemini, источники): раньше 9 вопросов из 144 шли без отчёта.
        if len(accepted) < total and not self.stopped() and not over_budget:
            self._log_shortage(len(accepted), total, quotas, counts)
        self._log_warn_totals()
        if self.s.sort_by_index and not self.s.shuffle_questions:
            # Порядок задаст индекс популярности (arrange_questions) — мешать
            # список смысла нет, а лог приятнее читать по убыванию узнаваемости.
            accepted.sort(key=lambda c: c.index, reverse=True)
        else:
            self.rng.shuffle(accepted)
        from .title_questions import generate_titles
        return generate_titles(self, accepted[:total])

    # ── шаг 4б: у кого из списков есть отобранное ─────────────────────────
    def mark_list_owners(self, songs: list) -> None:
        """Дописывает в реплику ведущего ники тех, у кого тайтл есть в списке.

        Работает при общей базе (галочка «Отмечать, у кого есть»): аниме
        берутся случайно, но если выпавший тайтл нашёлся у кого-то из
        добавленных списков — его ник попадёт в ответ. Списки спрашиваются
        В КОНЦЕ, когда вопросы уже отобраны (просьба пользователя): раньше
        неизвестно, какие id вообще понадобятся."""
        if not (self.s.random_pool and getattr(self.s, "mark_owners", False)):
            return
        if not songs:
            return
        want = {"anime": {c.mal_id for c in songs if not c.is_manga and c.mal_id},
                "manga": {c.mal_id for c in songs if c.is_manga and c.mal_id}}
        owners: dict[str, dict[int, list[str]]] = {"anime": {}, "manga": {}}
        for target in ("anime", "manga"):
            if not want[target]:
                continue
            for user in self._user_lists(target):
                if self.stopped():
                    return
                nick = user.username.strip()
                try:
                    ids = set(self._fetch_user_list(user, target))
                except _api.AnimePackApiError as e:
                    self.log(f"Список {nick}: {e} — отметок от него не будет")
                    continue
                for mal in want[target] & ids:
                    owners[target].setdefault(mal, []).append(nick)
        marked = 0
        for cand in songs:
            found = owners["manga" if cand.is_manga else "anime"].get(cand.mal_id)
            if found:
                cand.users = list(found)
                marked += 1
        if owners["anime"] or owners["manga"]:
            self.log(f"Есть в чьих-то списках: {marked} из {len(songs)} вопросов")

    # ── шаг 5: упаковка ───────────────────────────────────────────────────
    def write_package(self, songs: list, out_path: _api.Optional[str] = None) -> str:
        from pathlib import Path
        from .popular_franchise_title import popular_franchise_title
        known_parts = getattr(self, "_fr_parts", {})
        for cand in songs:
            franchise = str(cand.anime.get("franchise") or "").strip()
            cand.popular_franchise_title = popular_franchise_title(
                cand.anime, known_parts.get(franchise, ()))
        xml = _api.build_content_xml(songs, self.s)
        with open(_api.os.path.join(self.folder, "content.xml"), "wb") as f:
            f.write(xml)

        used_audio = {c.audio_out for c in songs
                      if (not c.is_silent or c.kind == _api.DESCRIPTION_AUDIO_KIND)
                      and not c.has_video}
        # Ролик — и с AnimeThemes, и собранный из кадра (вопрос-пиксели).
        used_video = {c.entrance_video or c.video_out for c in songs if c.has_video}
        used_video |= {name for c in songs for name in c.entrance_frames.values()}
        used_images = {c.poster_file for c in songs if c.has_poster}
        used_images |= {c.collage_file for c in songs if c.has_collage}
        used_images |= {c.frame_file for c in songs if c.has_frame
                        and c.frame_file not in c.entrance_frames}
        # У вопроса-студии кадров несколько, и в пак обязаны попасть все.
        used_images |= {name for c in songs for name in c.extra_frames
                        if name and name not in c.entrance_frames}

        if out_path:
            target = Path(out_path)
        else:
            out_dir = self.s.out_dir.strip()
            if not out_dir:
                try:
                    from utils import default_download_dir
                    out_dir = default_download_dir()
                except Exception:  # pragma: no cover
                    out_dir = _api.os.path.expanduser("~")
            # Имя файла — то же, что название внутри пака (номер и средняя
            # сложность): иначе соседние паки различались бы только «(1)», «(2)».
            from .pack_summary import pack_title
            name = pack_title(
                self.s.title, getattr(self.s, "pack_number", 0), songs,
                test_number=getattr(self.s, "test_pack_number", 0),
                ignore_test_packs=getattr(self.s, "ignore_test_packs", False))
            target = Path(out_dir) / f"{_api.safe_filename(name, 'Аниме пак')}.siq"
        target.parent.mkdir(parents=True, exist_ok=True)
        target = _api.unique_path(target)

        from storage_guard import require_space, WORK_RESERVE
        media_size = sum((Path(self.folder) / folder / name).stat().st_size
                         for folder, names in (("Audio", used_audio), ("Images", used_images), ("Video", used_video))
                         for name in names if (Path(self.folder) / folder / name).is_file())
        require_space(target.parent, media_size + len(xml) + WORK_RESERVE)

        from .package_transaction import archive
        with archive(target, _api.zipfile, maximum=self._byte_budget) as zf:
            zf.writestr("content.xml", xml, _api.zipfile.ZIP_DEFLATED)
            # SIQuester represents the package-level "Quality control" checkbox
            # with an empty marker stream at the archive root, not in content.xml.
            zf.writestr("quality.marker", b"", _api.zipfile.ZIP_STORED)
            from .music_processing import processing_manifest
            manifest = processing_manifest(songs, self.s)
            if manifest:
                zf.writestr("chiptune.json", manifest, _api.zipfile.ZIP_DEFLATED)
            from .cover_processing import covers_manifest
            covers = covers_manifest(songs, self.s)
            if covers:
                zf.writestr("covers.json", covers, _api.zipfile.ZIP_DEFLATED)
            from .karaoke_processing import manifest as karaoke_manifest
            karaoke_data = karaoke_manifest(songs)
            if karaoke_data:
                zf.writestr("karaoke.json", karaoke_data, _api.zipfile.ZIP_DEFLATED)
                for candidate in songs:
                    if candidate.music_effect == "karaoke" and candidate.has_video:
                        subtitle = Path(self.folder) / "Video" / (Path(candidate.video_out).stem + ".ass")
                        if subtitle.is_file():
                            zf.write(subtitle, "Karaoke/" + subtitle.name, _api.zipfile.ZIP_DEFLATED)
            episodes = [{"file": c.video_out, **c.episode_clip} for c in songs if c.episode_clip]
            if episodes:
                zf.writestr("episodes.json", _api.json.dumps(episodes, ensure_ascii=False, indent=2),
                            _api.zipfile.ZIP_DEFLATED)
            # Список спрошенного: по нему следующий пак узнаёт франшизы этого,
            # даже когда ответом стояло не название тайтла (см. pack_manifest).
            from .pack_manifest import MANIFEST_NAME, build as build_manifest
            spent = build_manifest(songs)
            if spent:
                zf.writestr(MANIFEST_NAME, spent, _api.zipfile.ZIP_DEFLATED)
            # Медиа уже сжато (opus/avif) — deflate только жжёт время.
            for folder, names in (("Audio", used_audio), ("Images", used_images),
                                  ("Video", used_video)):
                for name in sorted(names):
                    src = _api.os.path.join(self.folder, folder, name)
                    if _api.os.path.exists(src):
                        zf.write(src, f"{folder}/{name}", _api.zipfile.ZIP_STORED)
        return str(target)

    def cleanup(self) -> None:
        self.stop_processes()
        manga_close = getattr(getattr(self, "mangadex", None), "close", None)
        if callable(manga_close):
            manga_close()
        from .song_downloads import close as close_downloads
        close_downloads(self)
        kuhi = getattr(self, "kuhi", None)
        if kuhi is not None:
            kuhi.close()
        episode_ru = getattr(self, "episode_ru", None)
        if episode_ru is not None:
            episode_ru.close()
        anisong_close = getattr(getattr(self, "anisong", None), "close", None)
        if callable(anisong_close):
            anisong_close()
        service = getattr(self, "_cover_service", None)
        if service is not None:
            service.close()
            self._cover_service = None
        if getattr(self, "_preserve_media", False):
            return
        if self.folder and _api.os.path.isdir(self.folder):
            _api.shutil.rmtree(self.folder, ignore_errors=True)
        self.folder = ""
