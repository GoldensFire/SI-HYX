# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: _poster_bytes. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


# ── обложки: общая кладовая → Shikimori → TMDB ────────────────────────
def _poster_bytes(self, cand: _api.SongCandidate, url: str) -> tuple[bytes, str]:
    """Исходные байты обложки тайтла и её расширение (b"", "" — нет никакой).

        Три источника по очереди, и первый же годный побеждает:
          1. общая кладовая на диске (poster_cache) — обложка тайтла не меняется
             годами, а качают её и генератор, и «Апгрейд пака»;
          2. постер карточки Shikimori — основной источник;
          3. themoviedb.org — запасной, по ключу из настроек: у свежих ONA,
             спешлов и редкой манги постера в карточке Shikimori попросту нет.

        Скачанное сразу кладётся в кладовую — в том виде, в каком приехало:
        ужимает его каждая вкладка под свой лимит сама."""
    key = _api.poster_cache.anime_key(cand.mal_id, book=cand.is_manga)
    use_cache = bool(getattr(self.s, "poster_cache", True)) and bool(key)
    from animepack_plot import season_number
    sequel = season_number(
        cand.title_ru, cand.anime.get("name"), cand.anime.get("english"),
        *(cand.anime.get("synonyms") or ())) > 1
    # Ранее TMDB мог положить обложку первого сезона под ключ продолжения.
    # При наличии адреса Shikimori перезапишем такую старую запись.
    if use_cache and not sequel:
        data, ext = _api.poster_cache.find(key)
        if data:
            with self._poster_lock:
                self._poster_hits += 1
            return data, ext
    data, ext = b"", ".jpg"
    if url:
        try:
            data, ext = self._get_bytes(url), self._url_ext(url)
        except Exception as e:  # noqa: BLE001 — есть ещё TMDB
            if not self.stopped():
                self._log_rare("Постер",
                               f"Постер «{cand.title_ru}» не скачался: {e}")
    # TMDB сопоставляет сериал целиком и иногда возвращает постер первого
    # сезона для вопроса о пятом. Для продолжений лучше остаться без постера,
    # чем показать неверную часть франшизы.
    if not data and not self.stopped() and not sequel:
        data, ext = self._tmdb_poster(cand)
    if data and use_cache:
        _api.poster_cache.put(key, data, ext)
    return data, ext

def _tmdb_poster(self, cand: _api.SongCandidate) -> tuple[bytes, str]:
    """Обложка с themoviedb.org (b"", "" — ключа нет или тайтл не нашёлся).

        Манга там бывает редко, но обложку томика TMDB иногда всё же знает — по
        экранизации; пробуем и её, хуже от этого не будет."""
    tmdb = getattr(self, "tmdb", None)
    if tmdb is None or not tmdb.enabled:
        return b"", ""
    names = [cand.anime.get("name"), cand.anime.get("english"),
             cand.title_ru]
    names = [n for n in (str(x or "").strip() for x in names) if n]
    if not names:
        return b"", ""
    movie = str(cand.anime.get("kind") or "") == "movie"
    try:
        url = tmdb.poster_url(names, year=cand.year, movie=movie)
    except _api.AnimePackApiError as e:
        self._log_rare("TMDB", f"TMDB: {e}")
        return b"", ""
    if not url:
        return b"", ""
    try:
        data = self._get_bytes(url)
    except Exception as e:  # noqa: BLE001
        self._log_rare("TMDB", f"Обложка с TMDB не скачалась: {e}")
        return b"", ""
    with self._poster_lock:
        self._poster_tmdb += 1
    return data, self._url_ext(url)

def download_images(self, cand: _api.SongCandidate) -> None:
    """Постер (в ответ), кадр (сам вопрос в режиме кадров) и коллаж 2×2 из
        скриншотов (поверх песни).

        Провал картинки не отменяет вопрос: просто не будет соответствующего
        элемента в XML (в ASPG ссылка оставалась и пак ломался). Исключение —
        кадр в режиме «только кадры»: без него вопроса нет вовсе."""
    from PIL import Image  # локально: Pillow нужен только здесь
    import io

    if cand.is_studio:
        # Кадры и горизонтальную склейку трёх постеров уже собрал
        # studio_question.download_frames. Один постер основного
        # тайтла здесь перетёр бы правильный ответ-склейку.
        return

    poster = cand.anime.get("poster") or {}
    poster_url = poster.get("originalUrl") or poster.get("mainUrl")
    data, ext = self._poster_bytes(cand, str(poster_url or ""))
    if data:
        try:
            name = self._save_reusable_image(
                data, f"{cand.file_base}_poster", ext)
            cand.poster_name = name or cand.poster_name
            cand.has_poster = bool(name)
        except Exception as e:  # noqa: BLE001
            self.log(f"Постер «{cand.title_ru}» не сохранился: {e}")
    if cand.song_alternates:
        from .song_multi_anime import join_posters
        try:
            join_posters(self, cand, data, ext)
        except Exception as e:  # noqa: BLE001
            cand.song_alternates = []
            self.log(f"Постеры одинаковой песни не склеились: {e}")

    shots = list(cand.anime.get("screenshots") or [])
    if cand.is_text or cand.kind in (_api.DESCRIPTION_AUDIO_KIND,
                                     _api.AI_ART_KIND, _api.PIXIV_ART_KIND,
                                     _api.MANGA_KIND,
                                     _api.SAKUGA_KIND, _api.EPISODE_KIND):
        # Анаграмме и вопросу по сюжету картинка не нужна вовсе: весь вопрос
        # — текст. Страница манги, уличный снимок, вырезка анимации и кадры
        # вопроса-студии (их несколько) к этому часу уже скачаны своими
        # загрузчиками (см. _fetch_media), а постер для ответа взят выше — тут
        # делать нечего.
        return
    if cand.is_character:
        self._download_character(cand)
        return
    if cand.is_pixel:
        # Кадр вопроса-пикселей уже стал роликом (download_pixel) — второй
        # раз качать его в Images/ незачем.
        return
    if cand.is_frame:
        url = self._pick_frame_url(cand)
        if not url:
            if shots:
                self.log(f"«{cand.title_ru}»: все кадры уже были в прошлых "
                         "паках — беру следующий тайтл")
            return
        cand.frame_url = url
        try:
            name = self._save_reusable_image(
                self._cached_bytes(url, "anime-frame"),
                f"{cand.file_base}_frame", self._url_ext(url), reuse=False)
            cand.frame_name = name or cand.frame_name
            cand.has_frame = bool(name)
        except Exception as e:  # noqa: BLE001
            self.log(f"Кадр «{cand.title_ru}» не скачался: {e}")
        return

    if not self.s.images:
        return
    self.rng.shuffle(shots)
    tiles = []
    for shot in shots:
        if len(tiles) >= _api.COLLAGE_IMAGES:
            break
        url = (shot or {}).get("originalUrl") or (shot or {}).get("x332Url")
        if not url:
            continue
        try:
            tile = Image.open(io.BytesIO(
                self._cached_bytes(url, "anime-frame"))).convert("RGB")
            tiles.append(tile.resize(_api.COLLAGE_CELL, Image.LANCZOS))
        except Exception:  # noqa: BLE001 — попробуем следующий скриншот
            continue
    if len(tiles) < _api.COLLAGE_IMAGES:
        self.log(f"Коллаж «{cand.title_ru}» пропущен: скриншотов не хватило")
        return
    try:
        collage = Image.new("RGB", _api.COLLAGE_SIZE, (0, 0, 0))
        cw, ch = _api.COLLAGE_CELL
        for i, tile in enumerate(tiles):
            collage.paste(tile, ((i % 2) * cw, (i // 2) * ch))
        buf = io.BytesIO()
        collage.save(buf, "PNG")
        name = self._save_image(buf.getvalue(), cand.file_base, ".png")
        cand.collage_name = name or cand.collage_name
        cand.has_collage = bool(name)
    except Exception as e:  # noqa: BLE001
        self.log(f"Коллаж «{cand.title_ru}» не собрался: {e}")

# ── видео с AnimeThemes ───────────────────────────────────────────────
def _theme_video(self, cand: _api.SongCandidate) -> str:
    """Ссылка на ролик именно этой песни («» — не нашлось).

        Ищем по MAL id и метке «OP1»/«ED2»: в AnisongDB та же песня зовётся
        «Opening 1», перевод делает song_tag. OST на AnimeThemes не лежат
        вовсе, поэтому для них сразу пусто."""
    mal = cand.mal_id
    tag = cand.tag.replace(" ", "").upper()
    if not mal or not tag or cand.base_kind == "insert":
        return ""
    with self._themes_lock:
        known = self._themes_cache.get(mal)
    if known is None:
        known = self.db_cache.memo("anime_themes", mal,
                                   _api.ENRICHMENT_CACHE_TTL)
        if known is not None:
            with self._media_cache_lock:
                self._media_cache_hits["метаданные"] += 1
            with self._themes_lock:
                self._themes_cache[mal] = known
    if known is None:
        try:
            fresh = self.themes.themes_by_mal_ids([mal])
        except _api.AnimePackApiError as e:
            self.log(f"AnimeThemes: {e}")
            fresh = {}
            loaded = False
        else:
            loaded = True
        with self._themes_lock:
            self._themes_cache[mal] = fresh.get(mal, {})
            known = self._themes_cache[mal]
        if loaded:
            self.db_cache.remember_memo("anime_themes", mal, known)
    row = (known or {}).get(tag) or {}
    return str(row.get("url") or "")

def video_encode_args(self, preset=None) -> list[str]:
    """Флаги кодирования ролика — тот же libsvtav1, что в «Обработке»
        (ProcessWorker._svt_args): keyint=-1 и scd=1, ключевые кадры только на
        сменах сцены. Из настроек вкладки берутся crf и пресет, остальное
        оттуда же, что и у «Обработки».

        preset задаётся отдельно там, где скорость кодирования своя: у сакуги
        она настраивается независимо от вопросов-роликов (просьба
        пользователя)."""
    crf = max(0, min(63, int(self.s.video_crf)))
    preset = max(0, min(13, int(self.s.video_preset if preset is None
                                else preset)))
    return ["-c:v", "libsvtav1", "-crf", str(crf), "-preset", str(preset),
            "-svtav1-params", f"tune={_api.VIDEO_TUNE}:keyint=-1:scd=1",
            "-pix_fmt", "yuv420p10le",
            "-vf", f"scale=-2:{_api.VIDEO_HEIGHT}:flags=bicubic"]

def _video_seconds(self, url: str) -> float:
    """Длительность ролика на сервере AnimeThemes.

        В ответе API её нет (есть только размер и разрешение), поэтому
        спрашиваем ffprobe: он читает заголовки файла Range-запросом, а не
        качает все сорок мегабайт. Ответ кладём в кэш — один и тот же ролик
        может попасться в паке дважды. Не ответил (нет ffprobe, сеть) — ноль,
        и точка старта останется прежней, фиксированной."""
    with self._video_len_lock:
        known = self._video_len.get(url)
    if known is not None:
        return known
    cmd = [_api.FFPROBE, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", url]
    # Под тем же замком, что и сама загрузка: CDN отвергает параллельные
    # чтения, а проба — такое же чтение, только короткое.
    with self._video_lock:
        code, out, _err = self._run_capture(cmd, timeout=60)
    try:
        value = float(out.strip()) if code == 0 else 0.0
    except (TypeError, ValueError):
        value = 0.0
    if value < 0:
        value = 0.0
    with self._video_len_lock:
        self._video_len[url] = value
    return value

def _video_start(self, cand: _api.SongCandidate, url: str, duration: int) -> int:
    """Откуда резать ролик — СЛУЧАЙНАЯ секунда, ровно как у отрезка песни
        (_trim_start): иначе один и тот же опенинг во всех паках начинался бы с
        одной и той же секунды (просьба пользователя).

        Первые секунды опенинга — заставка студии, их пропускаем (VIDEO_LEAD_IN).
        Если длительность узнать не вышло, остаётся прежнее поведение: начало
        ролика со сдвигом на заставку."""
    lead = _api.VIDEO_LEAD_IN if cand.base_kind == "opening" else 0
    total = self._video_seconds(url)
    if total <= 0:
        return lead
    latest = int(total) - int(duration)
    if latest <= lead:
        # Ролик короче отрезка (или почти) — берём его с самого начала,
        # иначе ffmpeg вернул бы пустой файл.
        return max(0, latest)
    return self.rng.randint(lead, latest)

def download_video(self, cand: _api.SongCandidate) -> bool:
    """Режет ролик прямо с сервера AnimeThemes и кодирует его в пак.

        Файл там весит под полсотни мегабайт, но сервер отдаёт Range (206), и
        ffmpeg с input-seek скачивает только нужные секунды — качать всё
        целиком, чтобы взять пятнадцать секунд, не приходится."""
    url = self._theme_video(cand)
    if not url:
        return False
    cand.video_url = url
    final = _api.os.path.join(self.folder, "Video", cand.video_out)
    duration = max(3, int(self.s.video_cut))
    start = self._video_start(cand, url, duration)
    # Звук ролика кодируется ровно так же, как любой другой звук в паке:
    # opus 192 кбит, нормализация громкости и затухание в конце отрезка
    # (opus_args). Иначе ролик звучал бы заметно громче или тише соседних
    # вопросов-песен.
    def make_cmd(seek: int) -> list[str]:
        return ([_api.FFMPEG, "-y", "-loglevel", "error", "-ss", str(seek),
                 "-i", url, "-t", str(duration)]
                + self.video_encode_args()
                + self.opus_args(duration)
                + ["-movflags", "+faststart", final])

    err = ""
    for attempt in range(_api.VIDEO_RETRIES + 1):
        if self.stopped():
            return False
        # Первая попытка — со случайной секунды; если не вышло, повторяем с
        # начала ролика: вдруг длительность мы угадали неверно и отрезка там
        # попросту нет.
        cmd = make_cmd(start if attempt == 0 else 0)
        # По одному за раз: параллельные чтения CDN отвергает.
        with self._video_lock:
            code, err = self._run_killable(cmd, timeout=600)
        size = _api.os.path.getsize(final) if _api.os.path.exists(final) else 0
        broken_stream = any(text in err.casefold() for text in
                            ("file ended prematurely", "stream ends prematurely"))
        if code == 0 and size >= _api.MIN_VIDEO_BYTES and not broken_stream:
            cand.has_video = True
            return True
        # Оборванный вход ffmpeg не считает ошибкой: код ноль, а в файле
        # одни заголовки — поэтому и смотрим на размер, а не только на код.
        try:
            if _api.os.path.exists(final):
                _api.os.remove(final)
        except OSError:
            pass
        if attempt < _api.VIDEO_RETRIES:
            _api.time.sleep(_api.VIDEO_RETRY_PAUSE * (attempt + 1))
    if not self.stopped():
        reason = ("поток AnimeThemes оборвался до конца ролика"
                  if broken_stream else (err or "пустой файл").strip()[:160])
        self.log(f"Ролик «{cand.title_ru}» не получен: {reason}. "
                 f"После {_api.VIDEO_RETRIES + 1} попыток беру аудио песни.")
    return False
