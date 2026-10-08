# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Генератор: загрузка, кэш и кодирование медиа — аудио, картинки, видео, раскрытие кадров, DVD и пикселизация."""
from __future__ import annotations
import animepack as _api
from si_hyx_parts.animepack.generation_runtime import encoding_operation, track_process, untrack_process
from si_hyx_parts.animepack.generation_diagnostics import operation, process_label
import math
from pathlib import Path
from PIL import Image, ImageOps
from frame_reveal import RevealRenderer, stage_frame_counts
import random
import subprocess
import tempfile
from frame_reveal_dvd import DvdAnimation, dvd_fps
from frame_reveal_dvd_media import FolderMedia, list_media
from frame_reveal import EFFECT_LABELS, choose_effect
from pixelize import block_sequence



def dvd_media(self, rng, fps: int):
    """Источник картинок/видео для прямоугольника или None (папки нет)."""
    folder = str(getattr(self.s, "frame_dvd_folder", "") or "").strip()
    files = list_media(folder)
    if not files:
        if folder:
            self._log_rare("DVD-заставка", f"В папке «{folder}» нет картинок "
                           "и видео — прямоугольник будет просто окном в кадр.")
        return None

    def track(proc):
        track_process(self, proc)

    def untrack(proc):
        untrack_process(self, proc)

    return FolderMedia(files, rng, _api.FFMPEG, _api.FFPROBE, fps,
                       track, untrack)


def _close(anim, media) -> None:
    anim.close()
    if media is not None:
        media.close()


def _feed(self, proc, anim, moving: int, total: int):
    """Пишет кадры в ffmpeg; None — остановлено кнопкой «Стоп».

    После движения до конца ролика стоит последний кадр анимации, а НЕ
    полный кадр: необлетённое остаётся чёрным (просьба пользователя)."""
    last = None
    try:
        for number in range(total):
            if self.stopped():
                self._kill(proc)
                return None
            if number < moving:
                proc.stdin.write(anim.frame().tobytes())
                anim.step()
            else:
                if last is None:
                    last = anim.frame().tobytes()
                proc.stdin.write(last)
        proc.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass                      # ffmpeg упал — причина будет в его stderr
    deadline = _api.time.monotonic() + 300
    while True:
        try:
            return proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        if self.stopped() or _api.time.monotonic() > deadline:
            self._kill(proc)
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            return None if self.stopped() else 1


class GeneratorMediaMixin:
    """Генератор: загрузка, кэш и кодирование медиа — аудио, картинки, видео, раскрытие кадров, DVD и пикселизация."""

    # ── шаг 3: медиа ──────────────────────────────────────────────────────
    def prepare_dirs(self) -> str:
        self.folder = _api.tempfile.mkdtemp(prefix="sihyx_animepack_")
        self._preserve_media = False
        self._storage_error = None
        for sub in ("Audio", "Images", "Video"):
            _api.os.makedirs(_api.os.path.join(self.folder, sub), exist_ok=True)
        return self.folder

    @operation("скачивание")
    def _get_bytes(self, url: str, timeout=(10, 90)) -> bytes:
        from .media_transfer import download
        return download(self, url, timeout)

    @operation("ожидание повторного запроса")
    def _download_retry_pause(self, seconds):
        end = _api.time.monotonic() + seconds
        while _api.time.monotonic() < end:
            if self.stopped():
                raise _api.AnimePackError("Остановлено")
            _api.time.sleep(min(0.1, max(0, end - _api.time.monotonic())))

    def _cached_bytes(self, url: str, namespace: str, minimum: int = 1) -> bytes:
        """Повторяем только обложки; песни и кадры скачиваем для одного пака."""
        if namespace in ("amq-audio", "anime-frame", "cover-audio"):
            return self._get_bytes(url)
        if not bool(getattr(self.s, "poster_cache", True)):
            return self._get_bytes(url)
        data, hit = _api.media_cache.get_or_load(
            namespace, str(url), lambda: self._get_bytes(url), minimum=minimum)
        if hit:
            with self._media_cache_lock:
                self._media_cache_hits["исходники"] += 1
        return data

    @staticmethod
    def audio_filters(duration: float) -> str:
        """Цепочка `-af` для отрезка песни — та же, что в «Обработке»:
        нормализация громкости (loudnorm), затухание в конце и фикс раскладки
        каналов под libopus. Отсчёт от нуля: вход режется input-seek'ом, так что
        фильтры видят уже обнулённое время."""
        fade_at = max(0.0, float(duration) - _api.AUDIO_FADE_OUT)
        return ",".join([
            f"loudnorm=I={_api.AUDIO_LOUDNORM_I}:LRA={_api.AUDIO_LOUDNORM_LRA}"
            f":TP={_api.AUDIO_LOUDNORM_TP}",
            f"afade=t=out:st={fade_at:.3f}:d={_api.AUDIO_FADE_OUT}",
            _api.OPUS_LAYOUT_FIX,
        ])

    @classmethod
    def opus_args(cls, duration: float) -> list[str]:
        """Opus 192 кбит с нормализацией и затуханием — единственный способ,
        которым в паке кодируется звук: и отрезок песни, и дорожка ролика."""
        return ["-af", cls.audio_filters(duration),
                "-c:a", "libopus", "-b:a", _api.AUDIO_BITRATE,
                "-vbr", "on", "-application", "audio"]

    def audio_encode_args(self, duration: float) -> list[str]:
        """Чем кодировать отрезок. Со сжатием — opus 192 кбит с нормализацией,
        без — поток копируется как есть: mp3 с CDN попадает в пак ровно в том
        качестве, в каком его отдал сервер, без единого перекодирования."""
        if not self.s.compress_audio:
            return ["-c:a", "copy"]
        return self.opus_args(duration)

    def _run_killable(self, cmd, timeout: float = 180.0) -> tuple[int, str]:
        """Запускает ffmpeg так, чтобы «Стоп» останавливал вкладку СРАЗУ.

        subprocess.run() ждал бы конца кодирования (секунды на каждый вопрос, а
        их качается parallel штук разом) — из-за этого кнопка «Стоп» и казалась
        залипшей. Здесь процесс живёт в реестре self._procs: stop_processes()
        убивает всё разом, а цикл ожидания просыпается каждые 0,2 с и сам
        проверяет флаг остановки."""
        code, _out, err = self._run_capture(cmd, timeout)
        return code, err

    @encoding_operation
    @operation(process_label)
    def _run_capture(self, cmd, timeout: float = 180.0) -> tuple[int, str, str]:
        """То же самое, но с выводом процесса: ffprobe отвечает в stdout, а
        ffmpeg — в stderr, реестр процессов и «Стоп» им нужны одинаково."""
        from .generation_priority import creation_flags
        kw = {"creationflags": _api.CREATE_NO_WINDOW | creation_flags(self.s)} if _api.os.name == "nt" else {}
        try:
            proc = _api.subprocess.Popen(cmd, stdout=_api.subprocess.PIPE,
                                    stderr=_api.subprocess.PIPE, **kw)
        except Exception as e:  # noqa: BLE001
            return 1, "", str(e)
        track_process(self, proc)
        deadline = _api.time.monotonic() + max(1.0, float(timeout))
        try:
            while True:
                try:
                    out, err = proc.communicate(timeout=0.2)
                    return (proc.returncode,
                            (out or b"").decode("utf-8", "replace"),
                            (err or b"").decode("utf-8", "replace"))
                except _api.subprocess.TimeoutExpired:
                    pass
                if self.stopped() or _api.time.monotonic() > deadline:
                    self._kill(proc)
                    try:
                        proc.communicate(timeout=5)
                    except Exception:  # noqa: BLE001
                        pass
                    # Таймаут — не «остановлено»: так журнал путал долгое
                    # кодирование с нажатой кнопкой «Стоп».
                    if self.stopped():
                        return 1, "", "остановлено"
                    return 1, "", f"не уложился в {float(timeout):.0f} с"
        finally:
            untrack_process(self, proc)

    @staticmethod
    def _kill(proc) -> None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001 — процесс мог уже завершиться
            pass

    def stop_processes(self) -> None:
        """Убивает все запущенные ffmpeg (зовётся по «Стоп» и при уборке)."""
        with self._procs_lock:
            procs = list(self._procs)
        for proc in procs:
            self._kill(proc)

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
        if cand.music_effect not in ("original", "video"):
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
        """Fresh known counts are cached; source failures remain separate states."""
        from .db_favorites_refresh import ACCESS_GROUP, _read, _recent, anonymous
        try:
            tid = int((cand.anime or {}).get("id") or 0)
        except (TypeError, ValueError):
            return -1
        if not tid:
            return -1
        target = "manga" if cand.is_manga else "anime"
        known = self.db_cache.memo(f"{target}_favorites", tid, _api.ENRICHMENT_CACHE_TTL)
        try:
            value = int(known) if known is not None else -1
        except (TypeError, ValueError):
            value = -1
        if value >= 0:
            with self._media_cache_lock:
                self._media_cache_hits["метаданные"] += 1
            return value
        key = f"{target}:{tid}"
        previous = self.db_cache.memo(ACCESS_GROUP, key)
        reuse = _recent(previous)
        if previous and previous.get("status") == "AGE_RESTRICTED" and not anonymous(self.shikimori):
            reuse = False
        if reuse:
            return -1
        result = _read(self, tid, target, str((cand.anime or {}).get("url") or ""))
        result = {**result, "checked": result.get("checked", _api.time.time())}
        self.db_cache.remember_memo(ACCESS_GROUP, key, result)
        value = int(result.get("value", -1))
        if result.get("status") == "NORMAL" and value >= 0:
            self.db_cache.remember_memo(f"{target}_favorites", tid, value)
            return value
        return -1

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
            from .frame_catalog import extra_frames
            extra = extra_frames(self, mal)
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
        urls = getattr(cand, '_available_frames', None)
        if getattr(cand, '_available_frame_mal', None) != cand.mal_id:
            urls = None
        if urls is None:
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
            from .frame_visual_check import select
            selected = select(self, cand)
            if selected is None:
                return
            data, ext = selected
            try:
                name = self._save_reusable_image(
                    data, f"{cand.file_base}_frame", ext, reuse=False)
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

    def video_encode_args(self, preset=None, *, crf=None) -> list[str]:
        """Флаги кодирования ролика — тот же libsvtav1, что в «Обработке»
        (ProcessWorker._svt_args): keyint=-1 и scd=1, ключевые кадры только на
        сменах сцены. Из настроек вкладки берутся crf и пресет, остальное
        оттуда же, что и у «Обработки».

        preset задаётся отдельно там, где скорость кодирования своя: у сакуги
        она настраивается независимо от вопросов-роликов (просьба
        пользователя)."""
        crf = max(0, min(63, int(self.s.video_crf if crf is None else crf)))
        preset = max(0, min(13, int(self.s.video_preset if preset is None
                                    else preset)))
        return ["-c:v", "libsvtav1", "-crf", str(crf), "-preset", str(preset),
                "-svtav1-params", f"tune={_api.VIDEO_TUNE}:keyint=-1:scd=1",
                "-pix_fmt", "yuv420p10le",
                "-vf", f"scale=-2:{_api.VIDEO_HEIGHT}:flags=bicubic"]

    def _video_seconds(self, url: str) -> float:
        """Длительность местного файла или совместимого последовательного HTTP-чтения.

    Быстрый загрузчик сам записывает в этот кеш длительность из ограниченной
    сетевой пробы. Запасной путь проверяет уже скачанный местный исходник."""
        with self._video_len_lock:
            known = self._video_len.get(url)
        if known is not None:
            return known
        from contextlib import nullcontext
        from .theme_http import GATE
        network = url.startswith(("https://", "http://"))
        args = ["-seekable", "0", "-rw_timeout", "10000000"] if network else []
        cmd = [_api.FFPROBE, "-v", "error"] + args + ["-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", url]
        with GATE.slot(self.stopped) if network else nullcontext():
            with self._video_lock:
                code, out, _err = self._run_capture(cmd, timeout=60)
        try:
            value = float(out.strip()) if code == 0 else 0.0
        except (TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value) or value < 0:
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
        """Готовит отрывок AnimeThemes и проверяет наличие полного видео и звука."""
        from .theme_video import download_video as prepare_video
        return prepare_video(self, cand)

    @operation("подготовка кадров")
    def encode_reveal(self, source: str, output: str, effect: str, seed: int):
        """PNG существуют лишь во временной папке; в пак попадает один ролик."""
        fps = max(1, min(60, int(self.s.pixel_fps)))
        counts = stage_frame_counts(self.s.pixel_seconds, fps, self.s.pixel_steps)
        with Image.open(source) as opened:
            original = ImageOps.exif_transpose(opened).convert("RGB")
        height = _api.PIXEL_HEIGHT
        width = max(2, round(original.width * height / original.height / 2) * 2)
        original = original.resize((width, height), Image.Resampling.LANCZOS)
        renderer = RevealRenderer(original, effect, self.s.frame_effect_strength, seed)
        with _api.tempfile.TemporaryDirectory(prefix="_reveal_", dir=self.folder) as folder:
            root = Path(folder)
            lines = ["ffconcat version 1.0"]
            for i, count in enumerate(counts):
                if self.stopped():
                    return 1, "остановлено"
                name = f"step_{i:02d}.png"
                renderer.render(i / (len(counts) - 1)).save(root / name)
                lines.extend([f"file '{name}'", f"option framerate {fps}",
                              f"duration {count / fps:.9f}"])
            # Последний повтор задаёт конец длительности последней ступени.
            lines.extend([f"file 'step_{len(counts) - 1:02d}.png'", f"option framerate {fps}"])
            manifest = root / "stages.ffconcat"
            manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
            if self.stopped():
                return 1, "остановлено"
            # Последняя ступень обязана быть чистым кадром. После почти чёрных
            # плиток межкадровое сжатие могло протащить их след в единственный
            # финальный кадр при 1 fps; принудительный ключевой кадр разрывает
            # такую зависимость, не раздувая ключевыми кадрами весь ролик.
            clean_at = sum(counts[:-1]) / fps
            cmd = ([_api.FFMPEG, "-y", "-loglevel", "error", "-f", "concat",
                    "-safe", "0", "-i", str(manifest), "-r", str(fps),
                    "-frames:v", str(sum(counts)), "-force_key_frames",
                    f"{clean_at:.9f}"]
                   + self.pixel_encode_args("setsar=1")
                   + ["-movflags", "+faststart", output])
            return self._run_killable(cmd, timeout=300)

    @encoding_operation
    @operation("подготовка и кодирование DVD")
    def encode_dvd(self, source: str, output: str, seed: int):
        """(код возврата, текст ошибки) — как у _run_killable."""
        fps = dvd_fps(getattr(self.s, "frame_dvd_fps", None))
        counts = stage_frame_counts(self.s.pixel_seconds, fps, self.s.pixel_steps)
        total = sum(counts)
        moving = total - counts[-1]
        with Image.open(source) as opened:
            original = ImageOps.exif_transpose(opened).convert("RGB")
        height = _api.PIXEL_HEIGHT
        width = max(2, round(original.width * height / original.height / 2) * 2)
        original = original.resize((width, height), Image.Resampling.LANCZOS)
        rng = random.Random(seed)
        media = dvd_media(self, rng, fps)
        strength = max(10, min(100, int(self.s.frame_effect_strength))) / 100.0
        try:
            anim = DvdAnimation(original, strength, rng, media, fps, moving)
        except Exception:
            if media is not None:
                media.close()
            raise
        still_at = moving / fps
        cmd = ([_api.FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                "-framerate", str(fps), "-i", "-", "-frames:v", str(total),
                "-force_key_frames", f"{still_at:.9f}"]
               + self.pixel_encode_args("setsar=1")
               + ["-movflags", "+faststart", output])
        from .generation_priority import creation_flags
        kw = {"creationflags": _api.CREATE_NO_WINDOW | creation_flags(self.s)} if _api.os.name == "nt" else {}
        # stderr — во временный файл, а не в PIPE: недочитанная труба ошибок
        # подвешивает ffmpeg (см. память про proxy-stderr).
        with tempfile.TemporaryFile() as errors:
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=errors,
                                        **kw)
            except Exception as e:  # noqa: BLE001
                _close(anim, media)
                return 1, str(e)
            track_process(self, proc)
            try:
                code = _feed(self, proc, anim, moving, total)
            finally:
                _close(anim, media)
                untrack_process(self, proc)
            errors.seek(0)
            text = errors.read().decode("utf-8", "replace")
        if code is None:
            return 1, "остановлено"
        return code, text

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
