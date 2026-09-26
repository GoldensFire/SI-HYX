# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: _iter_picture_candidates. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def _iter_picture_candidates(self, kind, ids, users_by_id, used_anime,
                             used_franchise) -> _api.Iterator[_api.SongCandidate]:
    """Кандидаты по готовому списку id: кадры, пиксели, персонажи, анаграммы,
        сюжет. Вопросом служит картинка или текст, и AnisongDB такому паку не
        нужен вовсе.

        Сам отбор ходит не сюда, а в общий разбор каталога (anime_card_feed):
        там карточка достаётся один раз и на песенный поток, и на непесенный.
        Здесь то же самое для отдельно взятого списка id.

        Списки людей и каталог Shikimori дают MAL id сразу, поэтому AnisongDB
        там не нужен вовсе. А мастер-лист AMQ хранит ANN id, и перевести их в
        MAL умеет только AnisongDB — тогда пачка всё равно идёт через него, но
        уже без фильтров по песням."""
    for batch in _api._chunks(ids, _api.ANISONG_BATCH):
        if self.stopped():
            return
        if self._ids_are_ann:
            self.log(f"AnisongDB: перевожу {len(batch)} id в MAL…")
            try:
                songs = self.anisong.songs_by_ann_ids(batch)
            except _api.AnimePackApiError as e:
                self.log(f"AnisongDB: {e} — пропускаю пачку")
                continue
            mal_ids, seen = [], set()
            for song in songs:
                try:
                    mal = int((song.get("linked_ids") or {})["myanimelist"])
                except (KeyError, TypeError, ValueError):
                    continue
                if mal in seen or mal in used_anime:
                    continue
                seen.add(mal)
                mal_ids.append(mal)
        else:
            mal_ids = [i for i in batch if i not in used_anime]
        if not mal_ids:
            continue

        for sub in _api._chunks(mal_ids, _api.SHIKIMORI_BATCH):
            if self.stopped():
                return
            try:
                animes = self._animes_by_ids(sub)
            except _api.AnimePackApiError as e:
                self.log(f"Shikimori: {e} — пропускаю пачку")
                continue
            self._load_franchise_indexes(animes)
            for anime in animes:
                if self.stopped():
                    return
                try:
                    mal = int(anime.get("malId") or 0)
                except (TypeError, ValueError):
                    continue
                if not mal:
                    continue
                if not self._accept_anime(anime, mal, used_anime,
                                          used_franchise):
                    continue
                cand = _api.SongCandidate(
                    song={}, anime=anime, kind=kind,
                    users=list(users_by_id.get(mal, [])),
                    franchise_index=self._franchise_index(anime),
                    compress_images=self.s.compress_images)
                cand._reserved = self._last_reserved
                yield cand

# ── общие проверки тайтла (оба потока кандидатов) ─────────────────────
def _load_franchise_indexes(self, animes: list) -> None:
    """Догружает узнаваемость франшиз для пачки карточек.

        Части франшизы (до FRANCHISE_PARTS штук по убыванию популярности)
        спрашиваются один раз на все генерации — дальше они лежат в кэше на
        диске. Из них считается индекс серии целиком: самая популярная часть
        плюс надбавка за живые сезоны и послабление по году, если у старого
        тайтла есть заметное продолжение (franchise_parts_index)."""
    cards = [a for a in animes if isinstance(a, dict)]
    need = {str(a.get("franchise") or "").strip() for a in cards}
    need = {f for f in need if f and f not in self._fr_parts}
    fresh: dict[str, list] = {}
    ask = set()
    for key in need:
        known = self.db_cache.franchise(key)
        if known is None:
            ask.add(key)
        else:
            fresh[key] = known
    if ask:
        try:
            loaded = self.shikimori.franchise_parts(sorted(ask))
        except Exception as e:  # noqa: BLE001 — без этого пак всё равно соберётся
            self.log(f"Узнаваемость франшиз не загрузилась: {e}")
            loaded = {}
        # В кэш идут ТОЛЬКО те франшизы, про которые сервер и правда
        # ответил (пустой список — тоже ответ: «частей нет»). Про молчание
        # не запоминаем ничего: разовый обрыв связи иначе навсегда осел бы
        # в кэше нулевой узнаваемостью.
        got = {key: list(rows) for key, rows in (loaded or {}).items()
               if key in ask}
        self.db_cache.add_franchises(got)
        self.db_cache.save()
        fresh.update(got)
    for key in need:
        self._fr_parts[key] = list(fresh.get(key) or [])
    for anime in cards:
        key = str(anime.get("franchise") or "").strip()
        if not key:
            continue
        parts = self._fr_parts.get(key, [])
        branch = _api.franchise_branch_key(anime, parts)
        cache_key = (key, branch)
        if cache_key not in self._fr_index:
            self._fr_index[cache_key] = _api.branch_franchise_index(anime, parts)

def _franchise_index(self, anime: dict) -> float:
    key = str(anime.get("franchise") or "").strip()
    parts = self._fr_parts.get(key, [])
    branch = _api.franchise_branch_key(anime, parts)
    return self._fr_index.get((key, branch), 0.0)

def _accept_anime(self, anime: dict, mal: int, used_anime: set,
                  used_franchise: set, manga: bool = False,
                  adapted: _api.Optional[dict] = None) -> bool:
    """Годится ли тайтл: фильтры, дубли и сложность. Принятый сразу
        помечается использованным."""
    self._seen_titles += 1
    # Аниме и книги считаем порознь: «база дала 6 627 тайтлов» одной строкой
    # ни о чём не говорило — там были и 5 778 книг, и 849 аниме с песней.
    self._seen_by_media["manga" if manga else "anime"] += 1
    if not self.s.dup_anime and mal in used_anime:
        self._skips["тайтл уже брали"] += 1
        return False
    if not _api.filter_anime(anime, self.s, manga=manga):
        self._skips["фильтры (тип, год, оценка, жанры)"] += 1
        return False
    marks = _franchise_marks(anime, adapted if manga else None)
    # Франшизы, уже спрошенные в чужих паках (кнопка «Не повторять из паков»):
    # закрыт и сам тайтл, и вся его франшиза.
    if self._root_excluded(anime):
        self._skips["уже спрашивали в чужих паках"] += 1
        return False
    if not self.s.dup_franchise and any(m in used_franchise for m in marks):
        self._skips["франшиза уже в паке"] += 1
        return False
    # Сложность считаем через карточку-пустышку: там year/score разбираются
    # безопасно, и величина получается ровно та же, что у кандидата.
    probe = _api.SongCandidate(song={}, anime=anime,
                          media="manga" if manga else "anime",
                          franchise_index=self._franchise_index(anime))
    if manga:
        # Экранизованная книга меряется узнаваемостью своего АНИМЕ: по книжной
        # шкале её вопрос вышел бы вдесятеро труднее, чем он на самом деле.
        _api.apply_adaptation(probe, adapted or {})
        low, high = self.s.level_range(_api.MANGA_KIND)
        note = "рамки сложности манги"
    else:
        # Род вопроса ещё не выбран, поэтому рамка тут самая широкая из
        # задействованных: свою (у артов она отдельная) вопрос пройдёт уже
        # в _pick_kind.
        low, high = self.s.level_span
        note = "рамки сложности пака"
    if not (low <= probe.level <= high):
        self._skips[note] += 1
        return False
    self._good_titles += 1
    self._good_by_media["manga" if manga else "anime"] += 1
    used_anime.add(mal)
    used_franchise.update(marks)
    # Что именно забронировано под этого кандидата: цикл отбора вернёт
    # франшизу в оборот, если вопросом кандидат так и не станет (см.
    # _release_candidate). Между этой строкой и созданием карточки кандидата
    # управление никуда не уходит — оба потока кандидатов разбираются в одном
    # потоке выполнения, так что перезаписать чужую бронь тут нечем.
    self._last_reserved = marks
    return True

def _franchise_marks(anime: dict, adapted: _api.Optional[dict] = None) -> tuple:
    """Ключи, по которым тайтл считается «той же серией», что уже в паке.

        Это франшиза Shikimori и КОРЕНЬ названия — вторая линия обороны: у
        свежих тайтлов franchise иногда не проставлен, и тогда «Доктор Стоун:
        Научное будущее. Часть 3» проскакивал мимо проверки.

        У КНИГИ сюда добавляются ещё и ключи её аниме-экранизации: у манги
        поле franchise на Shikimori пустует сплошь и рядом, а у экранизации
        оно есть. Без этого «Покемон XY: Хупа и столкновение веков» (манга) и
        «Покемон: Хроники приключений» (аниме) спокойно попадали в один пак
        (просьба пользователя)."""
    out: list[str] = []
    for card, own in ((anime, True), (adapted or {}, False)):
        if not card:
            continue
        key = (_api.franchise_key(card) if own
               else str(card.get("franchise") or "").strip())
        root = _api.title_root(card.get("russian") or card.get("name"))
        for mark in (key, root):
            if mark and mark not in out:
                out.append(mark)
    return tuple(out)

def _release_candidate(self, cand) -> None:
    """Возвращает франшизу кандидата в оборот: вопросом он не стал.

        `_accept_anime` бронирует франшизу, как только тайтл прошёл фильтры, —
        иначе поток аниме и поток книг выдали бы кадр и страницу манги из одной
        серии. Но кандидат, которому не нашлось места, отвергнутый средней
        сложностью или сорвавшийся на загрузке, вопросом так и не стал, и
        держать за ним всю серию незачем: на небольшом каталоге из-за этого
        сгорали тысячи тайтлов («отсеяно „франшиза уже в паке“: 8987» при паке
        в 134 вопроса).

        Ключи берём те, что бронировались, а не считаем заново по карточке: у
        загадок по названию карточка кандидата к этому времени уже подменена
        на выбранный вариант тайтла."""
    studio = getattr(cand, "_studio_reserved", "")
    if studio:
        cand._studio_reserved = ""
        with self._studio_lock:
            self._used_studios.discard(studio)
    keys = getattr(cand, "_reserved", None)
    if not keys:
        return
    cand._reserved = None
    # Ключи не забываем: отложенный кандидат ещё может вернуться со скамейки,
    # и тогда франшизу надо занять заново (см. _rebook_candidate).
    cand._bench_keys = keys
    for key in keys:
        if key:
            self._used_franchise.discard(key)

def _trim_start(self, song: dict) -> int:
    """Случайная точка старта отрезка. Короткую песню берём с начала —
        в ASPG получалось отрицательное смещение."""
    try:
        length = float(song.get("songLength") or 0.0)
    except (TypeError, ValueError):
        length = 0.0
    latest = int(length) - int(self.s.audio_cut)
    if latest <= 0:
        return 0
    return self.rng.randint(0, latest)

# ── шаг 3: медиа ──────────────────────────────────────────────────────
def prepare_dirs(self) -> str:
    self.folder = _api.tempfile.mkdtemp(prefix="sihyx_animepack_")
    for sub in ("Audio", "Images", "Video"):
        _api.os.makedirs(_api.os.path.join(self.folder, sub), exist_ok=True)
    return self.folder

def _get_bytes(self, url: str, timeout=(10, 90)) -> bytes:
    last: _api.Optional[Exception] = None
    for attempt in range(_api._DOWNLOAD_RETRIES + 1):
        if self.stopped():
            raise _api.AnimePackError("Остановлено")
        try:
            resp = self.session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except Exception as e:  # noqa: BLE001 — любая сетевая беда
            last = e
            if attempt < _api._DOWNLOAD_RETRIES:
                _api.time.sleep(0.8 * (attempt + 1))
    raise _api.AnimePackError(str(last))


def _cached_bytes(self, url: str, namespace: str, minimum: int = 1) -> bytes:
    """Immutable source bytes shared by subsequent pack generations."""
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

def _run_capture(self, cmd, timeout: float = 180.0) -> tuple[int, str, str]:
    """То же самое, но с выводом процесса: ffprobe отвечает в stdout, а
        ffmpeg — в stderr, реестр процессов и «Стоп» им нужны одинаково."""
    kw = {"creationflags": _api.CREATE_NO_WINDOW} if _api.os.name == "nt" else {}
    try:
        proc = _api.subprocess.Popen(cmd, stdout=_api.subprocess.PIPE,
                                stderr=_api.subprocess.PIPE, **kw)
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)
    with self._procs_lock:
        self._procs.add(proc)
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
        with self._procs_lock:
            self._procs.discard(proc)

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
