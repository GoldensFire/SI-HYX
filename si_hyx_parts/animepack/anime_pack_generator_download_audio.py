# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: download_audio. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api
from .generation_runtime import encoding_operation
from .generation_diagnostics import operation


def download_audio(self, cand: _api.SongCandidate) -> bool:
    """Качает mp3 с CDN AMQ и режет его ffmpeg-ом до нужной длины."""
    if cand.music_effect == "karaoke":
        from .karaoke_processing import download_karaoke
        return download_karaoke(self, cand)
    if cand.music_effect == "chiptune":
        from .music_processing import download_chiptune
        return download_chiptune(self, cand)
    if cand.music_effect == "cover":
        from .cover_processing import download_cover
        return download_cover(self, cand)
    if cand.music_effect != "original":
        self.log(f"Неизвестный способ подачи музыки: {cand.music_effect}")
        return False
    name = cand.audio_file
    if not name:
        return False
    final = _api.os.path.join(self.folder, "Audio", cand.audio_out)
    if _api.os.path.exists(final):
        return True
    raw = _api.os.path.join(self.folder, "Audio", f"_tmp_{name}")
    try:
        from .song_downloads import source_bytes
        data = source_bytes(self, cand)
        if len(data) < _api._MIN_AUDIO_BYTES:
            raise _api.AnimePackError("файл подозрительно мал")
        with open(raw, "wb") as f:
            f.write(data)
        try:
            length = float(cand.song.get("songLength") or 0.0)
        except (TypeError, ValueError):
            length = 0.0
        duration = self.s.audio_cut
        if length:
            duration = min(duration, max(1, int(length - cand.trim_start)))
        cmd = ([_api.FFMPEG, "-y", "-loglevel", "error",
                "-ss", str(int(cand.trim_start)), "-i", raw,
                "-t", str(int(duration)), "-vn"]
               + self.audio_encode_args(duration) + [final])
        code, err = self._run_killable(cmd, timeout=180)
        if code != 0 or not _api.os.path.exists(final):
            if self.stopped():
                return False
            raise _api.AnimePackError((err or "ffmpeg не справился").strip()[:200])
        return True
    except Exception as e:  # noqa: BLE001
        self.log(f"Не вышло со звуком «{cand.title_ru}»: {e}")
        try:
            if _api.os.path.exists(final):
                _api.os.remove(final)
        except OSError:
            pass
        return False
    finally:
        try:
            if _api.os.path.exists(raw):
                _api.os.remove(raw)
        except OSError:
            pass

@staticmethod
def _url_ext(url, default: str = ".jpg") -> str:
    """Расширение картинки по ссылке (без ?query). Незнакомое — .jpg."""
    ext = _api.os.path.splitext(str(url or "").split("?")[0])[1].lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else default

def _save_image(self, data: bytes, base: str, src_ext: str = ".jpg") -> str:
    """Кладёт картинку в Images/ и возвращает её имя внутри пака («» — не
        вышло). Со сжатием это AVIF под лимит (кодирование общее с «Обработкой»),
        без — исходные байты как есть: ни ужимания, ни перекодирования."""
    if self.s.compress_images:
        name = f"{base}.avif"
        return name if self._to_avif(data, name, src_ext) else ""
    name = f"{base}{src_ext}"
    with open(_api.os.path.join(self.folder, "Images", name), "wb") as f:
        f.write(data)
    return name

def _save_reusable_image(self, data: bytes, base: str,
                         src_ext: str = ".jpg", *, reuse: bool = True) -> str:
    """Save an image and reuse its deterministic AVIF on later packs."""
    enabled = (reuse and self.s.compress_images
               and bool(getattr(self.s, "poster_cache", True)))
    if not enabled:
        return self._save_image(data, base, src_ext)
    key = _api.media_cache.content_key(
        data, "avif-1", int(self.s.image_limit_kb), int(self.s.image_speed),
        _api.IMAGE_FIT_PASSES, _api.IMAGE_MAX_SIDE)
    name = f"{base}.avif"
    out = _api.os.path.join(self.folder, "Images", name)
    ready = _api.media_cache.read("poster-avif", key, ".avif")
    if ready is not None:
        try:
            with open(out, "wb") as stream:
                stream.write(ready)
            with self._media_cache_lock:
                self._media_cache_hits["готовые AVIF"] += 1
            return name
        except OSError:
            pass
    name = self._save_image(data, base, src_ext)
    if name:
        try:
            with open(_api.os.path.join(self.folder, "Images", name), "rb") as stream:
                _api.media_cache.put("poster-avif", key, stream.read(), ".avif")
        except OSError:
            pass
    return name


@encoding_operation
@operation("обработка картинок")
def _to_avif(self, data: bytes, out_name: str, src_ext: str = ".jpg") -> bool:
    """Кладёт скачанную картинку в Images/<out_name> как AVIF ≤ лимита.

        Кодирование — общее с «Обработкой» (avif_fit: libaom, tune=iq, подбор
        CQ под размер, при нужде ужимание разрешения)."""
    raw = _api.os.path.join(self.folder, "Images", f"_tmp_{_api.uuid.uuid4().hex}{src_ext}")
    out = _api.os.path.join(self.folder, "Images", out_name)
    try:
        with open(raw, "wb") as f:
            f.write(data)
        limit = max(10, int(self.s.image_limit_kb))
        # Стартовый CQ считаем сами: проба с CQ=0 (самая медленная) для
        # такого лимита промахивается на порядок и уходит впустую. Плюс
        # заранее ужимаем гигантские постеры Shikimori — на экране SIGame
        # больше IMAGE_MAX_SIDE всё равно не видно, а время кодирования
        # почти прямо пропорционально числу пикселей.
        try:
            from config import Image
            with Image.open(raw) as im:
                w, h = im.size
            # Считаем по размеру ПОСЛЕ предварительного ужимания: кодировать
            # будут уже его, а от числа пикселей оценка и зависит.
            if max(w, h) > _api.IMAGE_MAX_SIDE:
                k = _api.IMAGE_MAX_SIDE / float(max(w, h))
                w, h = max(1, int(w * k)), max(1, int(h * k))
            start = _api.start_cq_guess(w, h, limit)
        except Exception:  # noqa: BLE001 — без Pillow просто идём как раньше
            start = None
        return _api.fit_to_limit(raw, out, limit,
                            speed=max(0, min(8, int(self.s.image_speed))),
                            passes=_api.IMAGE_FIT_PASSES,
                            start_cq=start, max_side=_api.IMAGE_MAX_SIDE,
                            should_stop=self._should_stop,
                            runner=lambda command: self._run_capture(
                                command, timeout=600)[0] == 0)
    finally:
        try:
            if _api.os.path.exists(raw):
                _api.os.remove(raw)
        except OSError:
            pass

# ── персонажи ─────────────────────────────────────────────────────────
def _pick_character(self, cand: _api.SongCandidate) -> None:
    """Выбирает персонажа для вопроса (и уводит ответ на первый тайтл).

        Персонажи спрашиваются по тайтлу прямо здесь, а не на этапе отбора:
        characterRoles — тяжёлое поле, и тянуть его для всех кандидатов подряд
        (а в пак попадает малая их часть) вышло бы дороже, чем взять по одному
        запросу на реально нужный вопрос."""
    if cand.kind == _api.MANGA_KIND:
        # Мангу спрашиваем страницей с MangaDex, а не портретом (см.
        # manga_panel): персонажа для неё выбирать больше незачем.
        return
    manga = cand.is_manga
    target = "manga" if manga else "anime"
    # GraphQL `animes(ids:)` и `mangas(ids:)` принимают id SHIKIMORI, а не
    # MAL. Раньше сюда всегда уходил malId: при несовпадающих идентификаторах
    # API возвращал пусто и в лог попадало ложное «без персонажа».
    try:
        catalog_id = int(cand.anime.get("id") or cand.mal_id or 0)
    except (TypeError, ValueError):
        catalog_id = 0
    memo_key = f"{target}:{cand.mal_id or catalog_id}"
    rows = self.db_cache.memo("characters", memo_key,
                              _api.ENRICHMENT_CACHE_TTL)
    if rows is None:
        try:
            groups = self.shikimori.characters_by_anime_ids(
                [catalog_id], target=target)
            rows = (groups.get(cand.mal_id) or groups.get(catalog_id) or [])
        except _api.AnimePackApiError as e:
            self.log(f"Персонажи «{cand.title_ru}»: {e}")
            return
        self.db_cache.remember_memo("characters", memo_key, rows)
    else:
        with self._media_cache_lock:
            self._media_cache_hits["метаданные"] += 1
    role = str(self.s.char_roles or "both").lower()
    if role == "main":
        rows = [r for r in rows if r.get("main")]
    elif role == "supporting":
        rows = [r for r in rows if not r.get("main")]
    # Персонажа с иероглифическим именем не спросить: игрок его не наберёт.
    rows = [r for r in rows if not _api.has_cjk(r.get("name"))]
    from .character_repeat import character_keys
    with self._exact_lock:
        previous = self._exact_keys | self._exact_seen
    rows = [row for row in rows if not character_keys(row) & previous]
    # Одного и того же персонажа два раза в пак не пускаем (Shikimori
    # держит сквозные id — совпадения ловятся даже между сиквелами).
    with self._frames_lock:
        free = [r for r in rows
                if f"char:{r.get('id')}" not in self._frames_used]
        if not free:
            if rows:
                self.log(f"«{cand.title_ru}»: подходящих персонажей не "
                         "осталось — беру следующий тайтл")
            return
    # Уровень любого героя теперь равен уровню тайтла, поэтому запросы
    # «в избранном» и перебор нескольких героев здесь больше ничего не решают.
    self.rng.shuffle(free)
    with self._frames_lock:
        picked = next((row for row in free
                       if f"char:{row.get('id')}" not in self._frames_used), None)
        if picked is None:
            return
        self._frames_used.add(f"char:{picked.get('id')}")
    cand.character = dict(picked)
    cand.char_favorites = -1

    # Карточку дебюта выбирает _fetch_media: после выбора героя, до проверки
    # его сложности и скачивания портрета.

def _title_favorites(self, cand: _api.SongCandidate) -> int:
    """Сколько человек добавили ТАЙТЛ кандидата в избранное (−1 — не узнали).

        Вторая мера узнаваемости рядом со списками: тайтл могли смотреть
        немногие, а в избранное класть часто — значит знают его лучше, чем
        говорит посещаемость (просьба пользователя). Число живёт только на
        странице Shikimori, то есть стоит запроса на тайтл, — поэтому
        спрашивается ЗДЕСЬ, у кандидата, дошедшего до загрузки, а не у каждой
        карточки каталога. Ответ запоминается в кэше навсегда."""
    try:
        tid = int((cand.anime or {}).get("id") or 0)
    except (TypeError, ValueError):
        return -1
    if not tid:
        return -1
    getter = getattr(self.shikimori, "title_favorites", None)
    if getter is None:
        return -1
    target = "manga" if cand.is_manga else "anime"
    known = self.db_cache.memo(f"{target}_favorites", tid,
                               _api.ENRICHMENT_CACHE_TTL)
    if known is not None:
        with self._media_cache_lock:
            self._media_cache_hits["метаданные"] += 1
        try:
            return int(known)
        except (TypeError, ValueError):
            pass
    try:
        try:
            value = int(getter(tid, target,
                               str((cand.anime or {}).get("url") or "")))
        except TypeError:  # старый сторонний/тестовый клиент
            value = int(getter(tid, target))
    except Exception:  # noqa: BLE001 — мера полезная, но не обязательная
        return -1
    self.db_cache.remember_memo(f"{target}_favorites", tid, value)
    return value

def _download_character(self, cand: _api.SongCandidate) -> None:
    """Портрет выбранного персонажа — сам вопрос «угадай персонажа»."""
    row = cand.character or {}
    url = str(row.get("poster") or "")
    if not url:
        return
    cand.frame_url = url
    # Портрет тоже лежит в общей кладовой: один и тот же герой попадается в
    # паках раз за разом, а картинка у него не меняется.
    key = _api.poster_cache.character_key(row.get("id"))
    use_cache = False  # портрет вопроса тоже должен быть одноразовым
    data, ext = (_api.poster_cache.find(key) if use_cache else (b"", ""))
    try:
        if not data:
            data, ext = self._cached_bytes(url, "anime-frame"), self._url_ext(url)
            if use_cache:
                _api.poster_cache.put(key, data, ext)
        name = self._save_reusable_image(data, f"{cand.file_base}_frame", ext,
                                         reuse=False)
        cand.frame_name = name or cand.frame_name
        cand.has_frame = bool(name)
    except Exception as e:  # noqa: BLE001
        self.log(f"Портрет «{row.get('name')}» не скачался: {e}")

def _frame_urls(self, anime: dict) -> list[str]:
    """Все ссылки на кадры тайтла.

        Основной источник — скриншоты Shikimori, к ним всегда добавляются
        превью серий AniList (по кадру на серию, с легальных стримингов),
        Kitsu (тоже по серии) и AniZip (превью каждой серии с TheTVDB): сцены
        получаются разные, а один и тот же тайтл в разных паках выглядит
        по-новому. Отдельной галочки для этого больше нет — лишняя пара
        запросов на вопрос того стоит.

        AniZip добавлен третьим не случайно: он знает те тайтлы, которых нет ни
        на легальных стримингах (AniList), ни в каталоге Kitsu, — у «Наруто»
        это 48 кадров из 246 серий."""
    out = []
    for shot in (anime.get("screenshots") or []):
        url = (shot or {}).get("originalUrl") or (shot or {}).get("x332Url")
        if url:
            out.append(str(url))
    try:
        mal = int(anime.get("malId") or 0)
    except (TypeError, ValueError):
        mal = 0
    if not mal:
        return out
    extra = self.db_cache.memo("frame_urls", mal,
                               _api.ENRICHMENT_CACHE_TTL)
    if extra is None:
        extra = []
        for api in (self.anilist, self.kitsu, self.anizip):
            if self.stopped():
                break
            try:
                extra.extend(api.frames(mal))
            except Exception:  # noqa: BLE001 — доп. источник, пропускаем
                continue
        # Пустой ответ не запоминаем: клиенты дополнительных источников
        # намеренно превращают сетевой сбой в [], и отличить его от честного
        # отсутствия кадров здесь невозможно.
        if extra and not self.stopped():
            self.db_cache.remember_memo("frame_urls", mal, extra)
    else:
        with self._media_cache_lock:
            self._media_cache_hits["метаданные"] += 1
    out.extend(str(url) for url in extra if url)
    # Порядок сохраняем, дубли убираем: AniList, Kitsu и AniZip иногда отдают
    # одно и то же превью с общего CDN.
    seen, uniq = set(), []
    for url in out:
        key = _api.frame_url_key(url)
        if key and key not in seen:
            seen.add(key)
            uniq.append(url)
    return uniq

def _pick_frame_url(self, cand: _api.SongCandidate) -> str:
    """Какой скриншот станет вопросом-кадром («» — годного нет).

        Кадр всегда случайный, а не первый: один и тот же тайтл в разных паках
        спрашивается разными сценами (настройки для этого больше нет — первый
        кадр никому не был нужен). Уже показанные кадры пропускаются — в этом
        паке всегда, а с галочкой «не повторять» ещё и те, что были в прошлых.
        Если у тайтла свободных кадров не осталось, вопроса не будет вовсе: пак
        возьмёт следующий тайтл."""
    urls = self._frame_urls(cand.anime)
    if not urls:
        return ""
    with self._frames_lock:
        free = [u for u in urls if _api.frame_url_key(u) not in self._frames_used]
        if not free:
            if self.s.frames_no_repeat:
                return ""
            free = urls          # в пределах пака повторов и так не будет
        url = self.rng.choice(free)
        self._frames_used.add(_api.frame_url_key(url))
    return url

def save_frames_history(self, songs: list) -> None:
    """Запоминает кадры собранного пака, чтобы они не повторились в
        следующем. Пишется только при включённой галочке и только по вопросам,
        реально попавшим в пак."""
    if not self.s.frames_no_repeat:
        return
    # Вопрос-пиксели тоже помнится: там тот же самый кадр, просто поданный
    # роликом — картинки в Images/ у него нет, поэтому «дошло до пака»
    # означает не has_frame, а собранный ролик.
    fresh = [_api.frame_url_key(c.frame_url) for c in songs
             if c.frame_url and ((c.kind in (_api.FRAME_KIND,
                                              _api.PIXIV_ART_KIND,
                                              _api.MANGA_KIND,
                                              _api.STUDIO_KIND)
                                  and c.has_frame)
                                 or ((c.is_pixel or c.is_sakuga)
                                     and c.has_video))]
    # У вопроса-студии кадров несколько, и помнить надо каждый: иначе
    # следующий пак покажет те же сцены другим родом вопроса.
    fresh += [_api.frame_url_key(url) for c in songs if c.has_frame
              for url in c.extra_frame_urls if url]
    if not fresh:
        return
    old = [_api.frame_url_key(u) for u in _api.load_frame_history(self.frames_history_path)]
    seen, merged = set(), []
    for url in old + fresh:
        if url and url not in seen:
            seen.add(url)
            merged.append(url)
    if _api.save_frame_history(merged, self.frames_history_path):
        self.log(f"Кадров в памяти «не повторять»: {len(merged)} "
                 f"(+{len(fresh)})")
    else:
        self.log("Не вышло запомнить кадры пака — в следующий раз они "
                 "могут повториться.")
