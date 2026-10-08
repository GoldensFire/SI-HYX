"""Exact balanced selection, revalidating and rendering saved song candidates."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

import animepack as ap


def install(generator, paths):
    seen = {}
    for path in paths:
        for row in json.loads(path.read_text(encoding="utf-8")):
            old = ap.SongCandidate(**row)
            if old.has_video and old.karaoke and old.music_effect == "karaoke":
                seen[(old.song_name.casefold(), old.artist.casefold())] = ap.SongCandidate(
                    song=old.song, anime=old.anime, kind=old.base_kind,
                    trim_start=old.trim_start, favorites=old.favorites,
                    franchise_index=old.franchise_index, siblings=old.siblings)
    pool = list(seen.values())
    generator._card_cache.update({int(c.anime['id']): c.anime for c in pool
                                  if str(c.anime.get('id', '')).isdecimal()})
    generator.log(f"Новый рендер из {len(pool)} известных песен; версии проверяются заново.")
    generator.anisong.songs_by_name_artist = lambda name, artist: [c.song for c in pool
        if c.song_name.casefold() == name.casefold() and c.artist.casefold() == artist.casefold()]
    ready, rejected = set(), set()

    def choose():
        indices = [i for i in range(len(pool)) if i not in rejected]
        quotas = generator.s.question_quotas
        matrix = np.array([[1] * len(indices), [pool[i].level for i in indices],
            *[[pool[i].base_kind == kind for i in indices] for kind in ap.SONG_KINDS]], dtype=float)
        targets = [generator.s.total_questions,
                   generator.s.total_questions * generator.s.song_level_avg,
                   *[quotas[kind] for kind in ap.SONG_KINDS]]
        costs = [(-10 if i in ready else 0) + i / 10000 for i in indices]
        result = milp(costs, integrality=np.ones(len(indices)), bounds=Bounds(0, 1),
                      constraints=LinearConstraint(matrix, targets, targets),
                      options={"time_limit": 30})
        if not result.success:
            raise RuntimeError("Не найден набор с точной средней: " + result.message)
        return [i for i, value in zip(indices, result.x) if value > .5]

    def select():
        generator._runtime.begin_selection()
        measured = generator._diagnostics.wrap(generator._fetch_media, ap.KIND_TITLES)
        fetch = generator._runtime.wrap_task(measured)
        try:
            with ThreadPoolExecutor(max_workers=generator.s.parallel) as executor:
                while True:
                    chosen = choose()
                    missing = [i for i in chosen if i not in ready]
                    if not missing:
                        result = [pool[i] for i in chosen]
                        generator.rng.shuffle(result)
                        return result
                    pending = {}
                    for i in missing:
                        pool[i].music_effect = "karaoke"
                        pool[i].music_slot = i
                        pool[i]._queued_at = time.monotonic()
                        pending[executor.submit(fetch, pool[i])] = i
                    for future in as_completed(pending):
                        i = pending[future]
                        good = bool(future.result())
                        (ready if good else rejected).add(i)
                        generator._progress(len(ready), generator.s.total_questions,
                                            "Проверка записи и караоке")
                        generator.log(f"Подтверждено {len(ready)} песен; отказов {len(rejected)}.")
        finally:
            generator._runtime.end_selection()

    generator.select_songs = select
