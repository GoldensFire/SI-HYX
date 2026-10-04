# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: pixel_encode_args. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api
from frame_reveal import EFFECT_LABELS, choose_effect, stage_frame_counts
from pixelize import block_sequence


# ── пиксели: кадр, который проявляется ────────────────────────────────
def pixel_encode_args(self, vf: str) -> list[str]:
    """Флаги раскрытия кадра: свой пресет, общий с роликами CRF."""
    crf = max(0, min(63, int(self.s.video_crf)))
    preset = max(0, min(13, int(self.s.frame_preset)))
    return ["-c:v", "libsvtav1", "-crf", str(crf), "-preset", str(preset),
            "-svtav1-params", f"tune={_api.VIDEO_TUNE}:keyint=-1:scd=1",
            "-pix_fmt", "yuv420p10le", "-vf", vf, "-an"]

def pixel_filter(self) -> str:
    """Цепочка -vf для ролика-проявления: сперва кадр приводится к 720p (в
        паке он всё равно смотрится на экране SIGame), затем идёт та же
        пикселизация, что у кнопки «Пикселизация» во вкладке «Монтаж».

        Порядок нарочно такой: масштабирование ПОСЛЕ пикселизации размыло бы
        блоки, и «крупные пиксели» вышли бы мыльными пятнами."""
    chain = [f"scale=-2:{_api.PIXEL_HEIGHT}"]
    fps = max(1, min(60, int(self.s.pixel_fps)))
    counts = stage_frame_counts(self.s.pixel_seconds, fps, self.s.pixel_steps)
    blocks = block_sequence(self.s.pixel_block, len(counts))
    elapsed = 0
    for count, block in zip(counts, blocks):
        if block > 1:
            # Граница между кадрами: inclusive between() не задевает первую
            # картинку следующей ступени, даже при 1 кадре/с и дробном шаге.
            start = max(0, elapsed - 0.5) / fps
            end = (elapsed + count - 0.5) / fps
            pix = _api.pixelize_filter(end - start, 1, block, start)
            if pix:
                chain.append(pix)
        elapsed += count
    return ",".join(chain)

def download_pixel(self, cand: _api.SongCandidate) -> bool:
    """Кадр с выбранным эффектом; прежнее имя сохраняет API и историю кадров."""
    effect = choose_effect(self.s.frame_effect, self.s.frame_effects, self.rng)
    seed = self.rng.getrandbits(64)
    from .frame_visual_check import select
    selected = select(self, cand)
    if selected is None:
        return False
    data, ext = selected
    raw = _api.os.path.join(self.folder, "Images",
                       f"_pix_{_api.uuid.uuid4().hex}{ext}")
    final = _api.os.path.join(self.folder, "Video", cand.video_out)
    try:
        with open(raw, "wb") as f:
            f.write(data)
    except Exception as e:  # noqa: BLE001
        self.log(f"Кадр «{cand.title_ru}» не скачался: {e}")
        return False
    try:
        if self.stopped():
            return False
        if effect == "pixelize":
            dur = max(2, int(self.s.pixel_seconds))
            fps = max(1, min(60, int(self.s.pixel_fps)))
            cmd = ([_api.FFMPEG, "-y", "-loglevel", "error", "-loop", "1",
                    "-framerate", str(fps), "-i", raw, "-t", str(dur)]
                   + self.pixel_encode_args(self.pixel_filter())
                   + ["-movflags", "+faststart", final])
            code, err = self._run_killable(cmd, timeout=300)
        elif effect == "dvd":
            # Покадровая анимация 30/60 к/с, а не ступени (encode_dvd).
            code, err = self.encode_dvd(raw, final, seed)
        else:
            code, err = self.encode_reveal(raw, final, effect, seed)
    except Exception as e:  # noqa: BLE001 — битый кадр заменяется следующим
        code, err = 1, str(e)
    finally:
        try:
            _api.os.remove(raw)
        except OSError:
            pass
    size = _api.os.path.getsize(final) if _api.os.path.exists(final) else 0
    if code == 0 and size > 0:
        cand.has_video = True
        cand.frame_effect = effect
        self.log(f"«{cand.title_ru}»: {EFFECT_LABELS[effect]}")
        return True
    if not self.stopped():
        self.log(f"Проявление «{cand.title_ru}» не собралось: "
                 f"{(err or 'пустой файл').strip()[:160]}")
    try:
        if _api.os.path.exists(final):
            _api.os.remove(final)
    except OSError:
        pass
    return False

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
        from .anime_pack_generator__media_base import _level_ok
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
        if cand.is_video:
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
