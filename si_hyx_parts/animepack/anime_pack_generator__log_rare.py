# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: _log_rare. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def _log_rare(self, tag: str, message: str) -> None:
    """Пишет повторяющуюся жалобу не больше WARN_REPEATS раз за прогон.

        Когда сервер начинает отказывать, ошибка приходит на КАЖДЫЙ вопрос, и
        консоль превращается в простыню из одинаковых строк — по ней уже не
        видно, что вообще происходит с паком."""
    with self._warn_lock:
        n = self._warn_counts.get(tag, 0) + 1
        self._warn_counts[tag] = n
    if n <= self.WARN_REPEATS:
        self.log(message)
    elif n == self.WARN_REPEATS + 1:
        self.log(f"{tag}: та же ошибка повторяется — дальше молчу, "
                 "итог будет в конце.")

def _log_warn_totals(self) -> None:
    """Итог по замолчанным жалобам: сколько раз каждая из них случилась."""
    with self._warn_lock:
        rows = [(tag, n) for tag, n in self._warn_counts.items()
                if n > self.WARN_REPEATS]
    for tag, n in rows:
        self.log(f"{tag}: всего таких ошибок за прогон — {n}.")

def stopped(self) -> bool:
    return bool(self._should_stop())

# ── сколько времени ушло на что ───────────────────────────────────────
@_api.contextmanager
def _timed(self, stage: str):
    """Запоминает отрезок работы этапа: «с какой по какую секунду».

        Зовётся и из рабочих потоков, поэтому под замком; порядок первых
        появлений запоминаем — по нему потом печатается итог."""
    started = _api.time.monotonic()
    try:
        yield
    finally:
        ended = _api.time.monotonic()
        with self._stage_lock:
            if stage not in self._stage_spans:
                self._stage_spans[stage] = []
                self._stage_order.append(stage)
            self._stage_spans[stage].append((started, ended))

@staticmethod
def _merge_spans(spans) -> float:
    """Длина СКЛЕЕННЫХ отрезков — сколько времени на часах этап шёл хоть в
        одном потоке. Восемь картинок, качавшихся одновременно по десять секунд,
        это десять секунд работы, а не восемьдесят."""
    rows = sorted((a, b) for a, b in spans if b > a)
    total, cur_start, cur_end = 0.0, None, None
    for start, end in rows:
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        elif end > cur_end:
            cur_end = end
    if cur_end is not None:
        total += cur_end - cur_start
    return total

def log_stage_times(self, total: float = 0.0) -> None:
    """Печатает в лог, сколько заняла каждая часть работы.

        Время этапа — по часам, а не в человеко-секундах: сумма длительностей
        параллельных загрузок раньше давала «картинки: 17 мин, 487%» при трёх
        минутах работы. Сумма по потокам всё же остаётся в строке — по ней
        видно, насколько плотно этап был загружен."""
    with self._stage_lock:
        stages = [(name, list(self._stage_spans[name]))
                  for name in self._stage_order]
    if not stages:
        return
    if total > 0:
        self.log(f"Время по этапам (всего {_api.fmt_elapsed(total)}):")
    else:
        self.log("Время по этапам:")
    parallel = max(1, int(self.s.parallel))
    for name, spans in stages:
        wall = self._merge_spans(spans)
        summed = sum(max(0.0, b - a) for a, b in spans)
        share = f", {min(100.0, wall / total * 100):.0f}%" if total > 0 else ""
        tail = ""
        if parallel > 1 and summed > wall * 1.2:
            tail = f" (в {parallel} потоков суммарно {_api.fmt_elapsed(summed)})"
        self.log(f"  • {name}: {_api.fmt_elapsed(wall)}{share}{tail}")

def log_gemini_spent(self) -> None:
    """Сколько запросов к Gemini стоил прогон — и сколько пропало зря.

        Вопросов по сюжету в паке 13, а запросов за них уходило под полсотни:
        ретраи, таймауты и отказы модели не видны нигде, пока не сложить их в
        одну строку (просьба пользователя). Обслуженные запросы — те, что идут
        в суточный лимит; остальное сервер отклонил (429) или не смог (5xx)."""
    # Клиент в тестах бывает заглушкой — считаем только настоящие счётчики.
    clients = {id(c): c for c in (getattr(self, "gemini", None),
                                  getattr(self, "gemini_titles", None),
                                  getattr(self, "gemini_pixiv", None),
                                  getattr(self, "gemini_manga", None))
               if isinstance(getattr(c, "spent", None), dict)}
    spent: _api.Counter = _api.Counter()
    served = 0
    for client in clients.values():
        spent.update(client.spent)
        try:
            served += int(getattr(client, "requests_made", 0) or 0)
        except (TypeError, ValueError):
            served = -1
    if not spent:
        return
    parts = ", ".join(f"{name}: {count}"
                      for name, count in sorted(spent.items()))
    total = sum(spent.values())
    lost = total - served
    tail = (f"; из них {lost} сервер отклонил или не ответил" if lost > 0 else "")
    # Куда ушли обращения за сюжетом: без этой расшифровки «16 вопросов —
    # 23 запроса» выглядело необъяснимо (просьба пользователя).
    plot = getattr(self, "_plot_calls", None) or {}
    if plot:
        tail += "; сюжет: " + ", ".join(
            f"{name} — {count}" for name, count in sorted(plot.items()))
    self.log(f"Gemini: запросов за прогон {total} ({parts}){tail}.")


def _over_budget(self, done: int, total: int) -> bool:
    """Пора ли останавливаться из-за веса.

        Ждать, пока пак реально перевалит за потолок, поздно — половина работы
        к тому моменту уже сделана впустую. Поэтому смотрим на средний вес
        набранного вопроса и прикидываем, во что выльется весь пак; первые
        BUDGET_WARMUP вопросов в расчёт не берём — на них разброс слишком велик
        (у одного тайтла ролик, у другого один постер)."""
    if self._bytes_used >= self._byte_budget:
        return True
    if done < _api.BUDGET_WARMUP or done >= total:
        return False
    return self._bytes_used / done * total > self._byte_budget

def _media_size(self, cand: _api.SongCandidate) -> int:
    """Сколько байт занимает медиа этого вопроса в готовом паке."""
    names = []
    if cand.has_video:
        names.append(_api.os.path.join("Video", cand.video_out))
    elif not cand.is_silent or (cand.kind == _api.DESCRIPTION_AUDIO_KIND
                                and cand.description_audio_ext):
        names.append(_api.os.path.join("Audio", cand.audio_out))
    for flag, name in ((cand.has_poster, cand.poster_file),
                       (cand.has_collage, cand.collage_file),
                       (cand.has_frame, cand.frame_file)):
        if flag and name:
            names.append(_api.os.path.join("Images", name))
    # Остальные кадры вопроса-студии весят столько же, сколько первый, и в
    # бюджет пака обязаны входить наравне с ним.
    for name in cand.extra_frames:
        if name:
            names.append(_api.os.path.join("Images", name))
    total = 0
    # Через set: у вопроса-обложки картинка вопроса и постер ответа — это
    # ОДИН файл, и считать его дважды нельзя.
    for rel in dict.fromkeys(names):
        try:
            total += _api.os.path.getsize(_api.os.path.join(self.folder, rel))
        except OSError:
            pass
    return total

def load_exclusions(self) -> None:
    """Собирает франшизы из чужих паков (настройка «Не повторять из этих
        .siq»). Непрочитанный файл — не ошибка: о нём просто пишем в лог."""
    self._excluded_roots = set()
    self._excluded_franchises = set()
    self._excluded_studios = set()
    self._exact_keys = set()
    from .test_packs import is_test_pack
    skip_tests = bool(getattr(self.s, "ignore_test_packs", False))
    if getattr(self.s, "exclude_exact_siq", None):
        from .exact_repeat import read_exact_keys
        for path in self.s.exclude_exact_siq:
            if self.stopped():
                return
            if skip_tests and is_test_pack(path):
                continue
            found = read_exact_keys(path)
            self._exact_keys.update(found)
            if not found:
                self.log(f"Не вышло прочитать вопросы из "
                         f"{_api.os.path.basename(path)}")
        self.log(f"Не повторяю сами вопросы из выбранных паков: "
                 f"{len(self._exact_keys)} отпечатков.")
    from .pack_manifest import read as read_manifest, read_studios
    for path in (self.s.exclude_siq or []):
        if self.stopped():
            return
        if skip_tests and is_test_pack(path):
            continue
        # Пак, собранный этой же программой, носит список спрошенного при себе
        # (см. pack_manifest). Он точнее разбора ответов: у «детали сюжета»,
        # персонажа и загадки по названию в ответе стоит не тайтл, и прежним
        # способом такая франшиза не находилась вовсе.
        spent = read_manifest(path)
        self._excluded_roots |= spent["roots"]
        self._excluded_franchises |= spent["franchises"]
        self._excluded_studios |= read_studios(path)
        roots = _api.siq_answer_roots(path)
        if roots:
            self._excluded_roots |= roots
        elif not spent["roots"] and not spent["franchises"]:
            self.log(f"Не вышло прочитать ответы из {_api.os.path.basename(path)}")
    if (not self._excluded_roots and not self._excluded_franchises
            and not self._excluded_studios):
        return
    # Корень названия закрывает только части с ТЕМ ЖЕ названием («Наруто» и
    # «Наруто: Ураганные хроники»). Франшиза шире: у «Fate/Zero» и «Fate/stay
    # night» корни разные, а серия одна, и спрашивать её второй раз не надо
    # (просьба пользователя). Франшизы достаём из уже набранного каталога —
    # сети это не стоит ничего.
    from .catalog_superset import cached_catalog
    for target in ("anime", "manga"):
        sig = _api.shiki_cache_signature(self.s, target == "manga")
        for card in cached_catalog(self.db_cache, target, sig)[0]:
            key = (_api.franchise_key(card) if card.get("franchise") else "")
            if not key or key in self._excluded_franchises:
                continue
            if self._root_excluded(card):
                self._excluded_franchises.add(key)
    self.log(f"Не повторяю франшизы из чужих паков: "
             f"{len(self._excluded_roots)} шт."
             + (f" (франшиз по каталогу: {len(self._excluded_franchises)})"
                if self._excluded_franchises else ""))
    if self._excluded_studios:
        self.log(f"Не повторяю студии из чужих паков: "
                 f"{len(self._excluded_studios)} шт.")


def _root_excluded(self, anime: dict) -> bool:
    """Спрашивали ли этот тайтл (или его франшизу) в чужих паках."""
    if not self._excluded_roots and not self._excluded_franchises:
        return False
    key = (_api.franchise_key(anime) if (anime or {}).get("franchise")
           else "")
    legacy_key = str((anime or {}).get("franchise") or "").strip()
    if (key and key in self._excluded_franchises
            or legacy_key and legacy_key in self._excluded_franchises):
        return True
    for name in ((anime or {}).get("russian"), (anime or {}).get("name"),
                 (anime or {}).get("english")):
        root = _api.title_root(name)
        if root and root in self._excluded_roots:
            # Раз одна часть франшизы уже была в чужом паке, закрываем всю:
            # остальные её части названы иначе, и по корню не отсеклись бы.
            if key:
                self._excluded_franchises.add(key)
            return True
    return False

# ── шаг 1: список аниме ───────────────────────────────────────────────
def _user_lists(self, target: str = "anime") -> list:
    """Живые карточки списков нужного раздела (аниме либо манга)."""
    return [u for u in self.s.users
            if u.username.strip() and u.statuses
            and str(u.target or "anime") == target]

def _fetch_user_list(self, user, target: str = "anime") -> list[int]:
    """Список одного человека — с оглядкой на память между генерациями."""
    nick = user.username.strip()
    key = _api.user_list_cache_key(f"{user.source}:{target}", nick, user.statuses)
    ids = _api.cached_user_list(key)
    if ids is not None:
        self.log(f"Список {nick} ({user.source}) уже спрашивали — беру "
                 f"из памяти: {len(ids)} шт.")
        return list(ids)
    self.log(f"Беру список {nick} ({user.source}, "
             f"{_api.TARGET_LABELS.get(target, target)})…")
    if user.source == "shikimori":
        api = self.shikimori
    elif user.source == "anilist":
        api = self.anilist
    else:
        api = self.mal
    ids = api.user_anime_ids(nick, user.statuses, progress_cb=self.log,
                             should_stop=self._should_stop, target=target)
    # Оборванный по «Стоп» список неполон — запоминать его нельзя:
    # следующий пак собрался бы по огрызку.
    if ids and not self.stopped():
        _api.remember_user_list(key, ids)
    return list(ids)

def _order_by_shares(self, seen: dict, by_user: dict) -> list[tuple[int, list]]:
    """Раскладывает id по долям списков (ползунок «Доли списков»).

        Без него порядок был просто случайным, и список на 1500 тайтлов
        забивал пак целиком, пока три списка по сотне почти не попадали в него
        (просьба пользователя). Здесь id выдаются по очереди, но очередь
        взвешенная: у кого доля больше, тот чаще и ходит.

        Метод — тот же, что при дележе мест по голосам (Д'Ондт): следующим
        берём список с наибольшим share/(взято+1). Тайтл, который есть у
        нескольких, отдаётся тому, чья очередь, и второй раз уже не выдаётся."""
    shares = {nick: max(0, int(pct)) for nick, pct in by_user.items()}
    if sum(shares.values()) <= 0 or len(shares) < 2:
        pairs = list(seen.items())
        self.rng.shuffle(pairs)
        return pairs
    pools: dict[str, list] = {}
    for nick in shares:
        pool = [aid for aid, owners in seen.items() if nick in owners]
        self.rng.shuffle(pool)
        pools[nick] = pool
    taken = {nick: 0 for nick in shares}
    out: list[tuple[int, list]] = []
    used: set = set()
    live = [n for n in shares if shares[n] > 0 and pools.get(n)]
    while live:
        nick = max(live, key=lambda n: shares[n] / (taken[n] + 1))
        pool = pools[nick]
        while pool and pool[-1] in used:
            pool.pop()
        if not pool:
            live.remove(nick)
            continue
        aid = pool.pop()
        used.add(aid)
        taken[nick] += 1
        out.append((aid, seen[aid]))
    # Хвост: тайтлы, до которых очередь не дошла (списки кончились
    # неодновременно). Они идут последними — если пак к тому времени не
    # набрался, пусть лучше будут они, чем недобор вопросов.
    rest = [(aid, owners) for aid, owners in seen.items() if aid not in used]
    self.rng.shuffle(rest)
    parts = ", ".join(f"{n} {shares[n]}%" for n in sorted(shares))
    self.log(f"Доли списков: {parts}")
    return out + rest

def collect_manga_ids(self) -> list[tuple[int, list[str]]]:
    """[(id манги, у кого она в списке)] — то же, что collect_anime_ids, но
        для раздела манги/манхвы/ранобэ.

        Общей базы вроде AMQ у манги нет вовсе, поэтому случайный режим всегда
        идёт в каталог Shikimori."""
    if self.s.random_pool:
        return [(i, []) for i in self._random_shikimori_ids(manga=True)]
    seen: dict[int, list[str]] = {}
    by_user: dict[str, int] = {}
    for user in self._user_lists("manga"):
        if self.stopped():
            break
        nick = user.username.strip()
        by_user[nick] = int(user.share or 0)
        ids = self._fetch_user_list(user, "manga")
        for aid in ids:
            seen.setdefault(int(aid), [])
            if nick not in seen[int(aid)]:
                seen[int(aid)].append(nick)
        self.log(f"{nick}: {len(ids)} манги/ранобэ")
    if not seen:
        return []
    pairs = self._order_by_shares(seen, by_user)
    self.log(f"Всего манги в работе: {len(pairs)}")
    return pairs

def collect_anime_ids(self) -> list[tuple[int, list[str]]]:
    """[(id аниме, кто его смотрел)] в случайном порядке.

        Id — это ANN id только когда случайные аниме берутся из мастер-листа
        AMQ (так он устроен). И списки людей, и каталог Shikimori дают MAL id."""
    if self.s.random_pool:
        if not self.s.random_mode:
            # Галочка «Похожие» снята — списки не спрашиваем вовсе: пак
            # собирается случайными аниме, как и просил пользователь.
            self.log("«Похожие» снято — списки не спрашиваю, беру случайные "
                     "аниме из общей базы.")
        if self._random_source == "shikimori":
            if str(self.s.random_source or "") == "amq":
                self.log("Песен в паке нет — базу беру с Shikimori: "
                         "мастер-лист AMQ знает только тайтлы с песнями.")
            return [(i, []) for i in self._random_shikimori_ids()]
        library = self.amq.library(progress_cb=self.log,
                                   should_stop=self._should_stop)
        ids = [ann for ann, year in library.items()
               if year and self.s.year_from <= int(year) <= self.s.year_to]
        self.rng.shuffle(ids)
        self.log(f"Подходящих по году аниме в базе AMQ: {len(ids)}")
        return [(i, []) for i in ids]

    seen: dict[int, list[str]] = {}
    by_user: dict[str, int] = {}
    users = self._user_lists("anime")
    for user in users:
        if self.stopped():
            break
        nick = user.username.strip()
        by_user[nick] = int(user.share or 0)
        ids = self._fetch_user_list(user, "anime")
        for aid in ids:
            seen.setdefault(int(aid), [])
            if nick not in seen[int(aid)]:
                seen[int(aid)].append(nick)
        self.log(f"{nick}: {len(ids)} аниме")

    if self.s.similar_count > 1:
        before = len(seen)
        need = int(self.s.similar_count)
        seen = {k: v for k, v in seen.items() if len(v) >= need}
        self.log(f"«Похожие»: из {before} аниме у {need}+ пользователей "
                 f"нашлось {len(seen)}")
    elif len(users) > 1:
        # «Похожие: 1 чел.» — списки просто складываются, совпадение не
        # требуется. Пишем об этом прямо, чтобы не выглядело, будто
        # совпадение всё-таки проверяется.
        self.log("«Похожие: 1 чел.» — беру всё из всех списков подряд, "
                 "совпадение не требуется.")
    pairs = self._order_by_shares(seen, by_user)
    self.log(f"Всего аниме в работе: {len(pairs)}")
    return pairs
