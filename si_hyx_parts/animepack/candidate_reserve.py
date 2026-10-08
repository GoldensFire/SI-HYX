# -*- coding: utf-8 -*-
"""Сохранённые тайтлы для альтернативного вопроса и позднего добора."""
import animepack as ap
import time

from .candidate_options import available_kinds
from .quota_balance import rebalance


# Сколько секунд верить пустому обходу резерва при неизменном отборе: за это
# время могли смениться вердикты Gemini и прочее, что в ключ не входит.
MISS_TTL = 1.0

SOURCE_FIELDS = (
    "song", "anime", "users", "kind", "trim_start", "media",
    "compress_audio", "compress_images", "franchise_index", "adapted_from",
    "siblings", "favorites", "ru_popularity",
)


def remember(candidate):
    """Снимок входных данных до того, как загрузчик сменит карточку/медиа."""
    if hasattr(candidate, "_retry_seed"):
        return
    candidate._origin_kind = candidate.kind
    candidate._retry_seed = {field: getattr(candidate, field)
                             for field in SOURCE_FIELDS}
    candidate._retry_title = getattr(candidate, "_title_variant", None)
    candidate._retry_has_title = hasattr(candidate, "_title_variant")
    candidate._tried_kinds = set(getattr(candidate, "_tried_kinds", ()))


def clean_copy(candidate, failed=False):
    remember(candidate)
    seed = candidate._retry_seed
    from .song_supply import retry_song
    alternative, remaining = retry_song(candidate, failed)
    if alternative is not None:
        seed = dict(seed, song=alternative,
                    kind=ap.song_kind(alternative.get('songType')) or seed['kind'])
    same_title = (candidate.anime.get("id") or candidate.anime.get("malId")) == (
        seed["anime"].get("id") or seed["anime"].get("malId"))
    favorites = candidate.favorites if same_title else seed["favorites"]
    fresh = ap.SongCandidate(**dict(seed, favorites=favorites))
    fresh._retry_seed = seed
    fresh._origin_kind = seed["kind"]
    fresh._retry_title = candidate._retry_title
    fresh._retry_has_title = candidate._retry_has_title
    if candidate._retry_has_title:
        fresh._title_variant = candidate._retry_title
    # История неудачных форм общая у всех копий тайтла: иначе старая запись
    # резерва снова пробует уже проваленную форму. Своя — только у другой песни.
    tried = candidate._tried_kinds
    if alternative is not None:
        tried = set(tried)
        tried.discard(fresh.kind)
    elif failed:
        tried.add(candidate.kind)
    fresh._tried_kinds = tried
    fresh._song_alternatives = remaining
    fresh._retry_after = getattr(candidate, "_retry_after", 0)
    fresh._technical_retries = getattr(candidate, "_technical_retries", 0)
    from si_hyx_parts.animepack.generator_catalog import _franchise_marks
    fresh._bench_keys = (getattr(candidate, "_bench_keys", None)
                         or getattr(candidate, "_reserved", None)
                         or _franchise_marks(seed["anime"], seed["adapted_from"]))
    return fresh


class CandidateReserve:
    def __init__(self, generator, quotas):
        self.generator = generator
        self.enabled = {kind: 1 for kind, count in quotas.items() if count}
        self.candidates = {}
        self.by_kind = {kind: {} for kind in self.enabled}
        self.accepted_titles = set()
        self.returned = 0
        self.reassigned = 0
        # Пустой обход резерва и состояние отбора, при котором он был пуст.
        self._version = 0
        self._miss = None

    def __bool__(self):
        return bool(self.candidates)

    def _title_key(self, candidate):
        return candidate.media, candidate.mal_id

    def accepted(self, candidate):
        remember(candidate)
        if candidate.studio_cards:
            self.accepted_titles.update(("anime", int(card.get("malId") or 0))
                                        for card in candidate.studio_cards)
        else:
            self.accepted_titles.add(self._title_key(candidate))
        self._remove(id(candidate._retry_seed))

    def _remove(self, token):
        self._version += 1
        self.candidates.pop(token, None)
        for rows in self.by_kind.values():
            rows.pop(token, None)

    def withdraw(self, candidate):
        """Книжная скамейка может вернуть тот же объект, что хранится здесь."""
        seed = getattr(candidate, "_retry_seed", None)
        if seed is not None:
            self._remove(id(seed))

    def park(self, candidate, failed=False):
        fresh = clean_copy(candidate, failed)
        if fresh.song != candidate.song:
            fresh.trim_start = self.generator._trim_start(fresh.song)
            fresh._retry_seed['trim_start'] = fresh.trim_start
            fresh._technical_retries = 0
        token = id(fresh._retry_seed)
        self._remove(token)
        options = available_kinds(self.generator, fresh, self.enabled)
        if options:
            self._version += 1
            self.candidates[token] = fresh
            for kind in options:
                self.by_kind[kind][token] = fresh

    def _ready(self, candidate):
        if time.monotonic() < getattr(candidate, "_retry_after", 0):
            return False
        gen = self.generator
        if (not gen.s.dup_anime
                and self._title_key(candidate) in self.accepted_titles):
            return False
        if not gen.s.dup_franchise:
            marks = (getattr(candidate, "_bench_keys", None)
                     or getattr(candidate, "_reserved", None) or ())
            with gen._studio_lock:
                if any(mark in gen._used_franchise for mark in marks):
                    return False
        return True

    def retry_wait(self):
        now = time.monotonic()
        times = [c._retry_after - now for c in self.candidates.values()
                 if getattr(c, "_retry_after", 0) > now]
        return min(times, default=0)

    def take(self, counts, inflight, quotas):
        # Не обходим тысячи сохранённых кадров, пока свободны только
        # персонажи: индекс по формам исключает квадратичный разбор каталога.
        state = self._state(counts, inflight, quotas)
        if (self._miss is not None and self._miss[0] == state
                and time.monotonic() < self._miss[1]):
            return None
        seen = set()
        for kind in quotas:
            if counts[kind] + inflight[kind] >= quotas[kind]:
                continue
            for token, candidate in list(self.by_kind.get(kind, {}).items()):
                if token in seen:
                    continue
                seen.add(token)
                if (self._ready(candidate)
                        and self.generator._pick_kind(
                            candidate, counts, inflight, quotas) is not None):
                    self._remove(token)
                    self.returned += 1
                    return candidate
        # Главный цикл спрашивает резерв каждые 0,1 с. Пока не сменились
        # квоты, загрузки, набранные вопросы и сам резерв, ответ тот же, а
        # полный обход сотен книг отнимал GIL у потока каталога.
        due = min((getattr(c, "_retry_after", 0) for c in self.candidates.values()
                   if getattr(c, "_retry_after", 0) > time.monotonic()), default=None)
        self._miss = state, min(time.monotonic() + MISS_TTL, due or float("inf"))
        return None

    def _state(self, counts, inflight, quotas):
        gen = self.generator
        return (self._version, tuple(sorted(counts.items())),
                tuple(sorted(inflight.items())), tuple(sorted(quotas.items())),
                tuple(map(id, getattr(gen, "_selection_state", ()))),
                frozenset(getattr(gen, "_dead_kinds", ())),
                frozenset(getattr(gen, "_spent_kinds", ())),
                len(getattr(gen, "_used_franchise", ())), len(self.accepted_titles))

    def _stock(self):
        """Один ресурс на тайтл/франшизу, включая связанные книги и сезоны."""
        gen = self.generator
        rows = [c for c in self.candidates.values() if self._ready(c)]
        groups, by_mark = [], {}
        for candidate in rows:
            options = set(available_kinds(gen, candidate, self.enabled))
            options.difference_update(gen._spent_kinds)
            if not options:
                continue
            marks = ((getattr(candidate, "_bench_keys", None)
                      or getattr(candidate, "_reserved", None) or ())
                     if not gen.s.dup_franchise else ())
            if not gen.s.dup_anime:
                marks = (*marks, self._title_key(candidate))
            linked = {by_mark[mark] for mark in marks if mark in by_mark}
            group = min(linked) if linked else len(groups)
            if not linked:
                groups.append(set())
            groups[group].update(options)
            for old in linked - {group}:
                groups[group].update(groups[old])
                groups[old].clear()
                by_mark = {mark: group if owner == old else owner
                           for mark, owner in by_mark.items()}
            by_mark.update((mark, group) for mark in marks)
        return [options for options in groups if options]

    def redistribute(self, quotas, counts):
        if getattr(self.generator.s, 'preserve_composition', True):
            return False
        updated = rebalance(self._stock(), quotas, counts)
        changes = {k: updated[k] - quotas[k] for k in quotas
                   if updated[k] != quotas[k]}
        if not changes:
            return False
        moved = sum(delta for delta in changes.values() if delta > 0)
        self.reassigned += moved
        quotas.update(updated)
        names = ", ".join(f"{ap.KIND_TITLES.get(k, k)} {delta:+d}"
                          for k, delta in changes.items())
        self.generator.log(f"Добор по оставшимся тайтлам: {names}.")
        return True
