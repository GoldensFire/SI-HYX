# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: select_songs. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


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


def select_songs(self) -> list:
    """Набирает ровно столько вопросов, сколько в паке, соблюдая квоты по
        типам. Медиа качаются параллельно прямо по ходу отбора."""
    total = self.s.total_questions
    quotas = self.s.question_quotas
    from music_effects import EffectSlots
    effect_slots = EffectSlots(self.s, sum(quotas.get(k, 0) for k in _api.SONG_KINDS))
    self._manga_mix.sync(quotas.get(_api.MANGA_KIND, 0))
    accepted: list[_api.SongCandidate] = []
    levels: list[int] = []          # узнаваемость набранного (level_avg)
    counts: _api.Counter = _api.Counter()
    inflight: _api.Counter = _api.Counter()
    from .title_eligibility import checked_candidates
    candidates = checked_candidates(self, self.iter_candidates())
    exhausted = False
    over_budget = False
    workers = max(1, min(16, int(self.s.parallel)))
    pending: dict = {}
    # Кандидат, которому место в паке есть, но прямо сейчас оно занято
    # ЗАГРУЗКОЙ. Такого не выбрасываем: дождёмся свободного потока и возьмём
    # его же. Больше одного тут не копится — сразу после откладывания цикл
    # уходит ждать готовые загрузки.
    deferred: list = []

    self._progress(0, total, "Отбираю вопросы…")
    # Пул НЕ через `with`: выход из блока ждал бы конца всех запущенных
    # загрузок, и «Стоп» отзывался бы только через десятки секунд. Здесь
    # очередь сбрасывается, а работающие ffmpeg убиваются сразу.
    pool = _api.ThreadPoolExecutor(max_workers=workers,
                              thread_name_prefix="animepack")
    try:
        try:
            while not self.stopped():
                # Род вопросов мог отвалиться совсем (кончился ключ Gemini) —
                # его места надо отдать остальным ДО того, как просить
                # следующего кандидата.
                if self._dead_kinds or self._spent_kinds:
                    self._share_out_dead(quotas, counts, inflight)
                    effect_slots.expand(self.s, sum(quotas.get(k, 0) for k in _api.SONG_KINDS))
                    self._manga_mix.sync(quotas.get(_api.MANGA_KIND, 0))
                # Досыпаем задач, пока есть куда: набранное + в работе < нужного.
                while ((not exhausted or deferred)
                       and len(accepted) + sum(inflight.values()) < total
                       and len(pending) < workers * 2
                       and any(quotas[k] > counts[k] + inflight[k]
                               for k in quotas if k not in self._dead_kinds)):
                    # Проверяем на КАЖДОМ кандидате, а не раз за круг: этот
                    # цикл не выходит наружу, пока есть кого просить, и
                    # каталог книг успел бы вычерпаться целиком.
                    self._close_spent_streams(quotas, counts)
                    if deferred:
                        cand = deferred.pop()
                    else:
                        with self._timed("поиск кандидатов"):
                            cand = next(candidates, None)
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
                            bench = self._take_level_bench()
                        if bench:
                            candidates = iter(bench)
                            continue
                        exhausted = True
                        break
                    if not self._rebook_candidate(cand):
                        # Пока кандидат лежал на скамейке, его серию занял
                        # другой тайтл — двух вопросов из одной серии в паке
                        # быть не должно.
                        self._drops["франшизу заняли, пока кандидат ждал"] += 1
                        continue
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
                    if kind in _api.SONG_KINDS:
                        effect_slots.reserve(cand)
                    inflight[kind] += 1
                    self._tries[kind] += 1
                    self._manga_mix.reserve(cand)
                    pending[pool.submit(self._fetch_media, cand)] = cand
                if not pending:
                    break
                # timeout: без него цикл спал бы до конца первой загрузки и
                # не замечал нажатого «Стоп» по полминуты.
                done, _ = _api.wait(list(pending), timeout=0.3,
                               return_when=_api.FIRST_COMPLETED)
                for fut in done:
                    cand = pending.pop(fut)
                    inflight[cand.kind] -= 1
                    try:
                        ok = fut.result()
                    except Exception as e:  # noqa: BLE001
                        self.log(f"Загрузка сорвалась: {e}")
                        ok = False
                    if not ok:
                        self._manga_mix.release(cand)
                        self._release_candidate(cand)
                        if cand.music_slot >= 0:
                            effect_slots.release(cand)
                        # Отвергнутый по средней сложности — не «не
                        # скачалось»: медиа мы даже не трогали.
                        if cand.rejected:
                            self._rejected_media += 1
                        else:
                            self._failed_media += 1
                        continue
                    if len(accepted) >= total or counts[cand.kind] >= quotas.get(cand.kind, 0):
                        self._late["пока качали, место занял другой"] += 1
                        self._manga_mix.release(cand)
                        self._release_candidate(cand)
                        # Слот способа подачи возвращаем ОБЯЗАТЕЛЬНО: вопрос
                        # готов, а места ему не нашлось, и это не неудача
                        # эффекта. Без этого слоты утекали, и на последних
                        # вопросах пака reserve оставался без свободных.
                        if cand.music_slot >= 0:
                            effect_slots.give_back(cand)
                        continue        # пока качали, место уже заняли
                    if self._exact_keys:
                        from .exact_repeat import candidate_keys
                        keys = candidate_keys(cand, self.folder)
                        if keys & (self._exact_keys | self._exact_seen):
                            self._late["тот же вопрос в выбранных паках"] += 1
                            self._manga_mix.release(cand)
                            self._release_candidate(cand)
                            if cand.music_slot >= 0:
                                effect_slots.give_back(cand)
                            continue
                        self._exact_seen.update(keys)
                    if cand.music_slot >= 0:
                        effect_slots.succeed(cand)
                    accepted.append(cand)
                    self._remember_level(cand, levels)
                    self._remember_char_level(cand)
                    counts[cand.kind] += 1
                    self._bytes_used += self._media_size(cand)
                    # Название тайтла на прогресс-баре не пишем (просьба
                    # пользователя): в лог оно и так идёт, а на баре нужны
                    # счётчик, оставшееся время и то, чем генератор занят
                    # прямо сейчас — «Сакуга», «Кадр», «Манга».
                    self._progress(len(accepted), total, _busy(inflight))
                    if self._over_budget(len(accepted), total):
                        over_budget = True
                        break
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
        finally:
            for fut in pending:
                fut.cancel()
    finally:
        # Ненужные ffmpeg прекращаем на любом выходе: не только по «Стоп», но
        # и после набора пака или исключения. Уже запущенный Future отменить
        # нельзя, поэтому обязательно дожидаемся его выхода. Иначе он успевает
        # менять общий кэш во время save(), а cleanup удаляет Images у него из
        # под ног — отсюда шли обе ошибки живого прогона.
        self.stop_processes()
        pool.shutdown(wait=True, cancel_futures=True)

    # Всё, что приехало с Shikimori за этот отбор, сохраняем на диск. Само по
    # себе это дёшево (без изменений save() ничего не делает), а нужно из-за
    # старых карточек манги: их перезапрашивает _mangas_by_ids, и без этой
    # строки свежие карточки жили бы только до конца генерации — следующий
    # прогон спрашивал бы их заново.
    self.db_cache.save()

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
    if exhausted and len(accepted) < total and not self.stopped():
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
    xml = _api.build_content_xml(songs, self.s)
    with open(_api.os.path.join(self.folder, "content.xml"), "wb") as f:
        f.write(xml)

    used_audio = {c.audio_out for c in songs
                  if not c.is_silent and not c.has_video}
    # Ролик — и с AnimeThemes, и собранный из кадра (вопрос-пиксели).
    used_video = {c.video_out for c in songs if c.has_video}
    used_images = {c.poster_file for c in songs if c.has_poster}
    used_images |= {c.collage_file for c in songs if c.has_collage}
    used_images |= {c.frame_file for c in songs if c.has_frame}
    # У вопроса-студии кадров несколько, и в пак обязаны попасть все.
    used_images |= {name for c in songs for name in c.extra_frames if name}

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
        name = pack_title(self.s.title, getattr(self.s, "pack_number", 0),
                          songs)
        target = Path(out_dir) / f"{_api.safe_filename(name, 'Аниме пак')}.siq"
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _api.unique_path(target)

    with _api.zipfile.ZipFile(target, "w") as zf:
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
    service = getattr(self, "_cover_service", None)
    if service is not None:
        service.close()
        self._cover_service = None
    if self.folder and _api.os.path.isdir(self.folder):
        _api.shutil.rmtree(self.folder, ignore_errors=True)
    self.folder = ""
