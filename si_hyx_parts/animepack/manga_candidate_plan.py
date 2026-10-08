"""Plan a balanced comic stream from cached metadata before source searches."""
from collections import deque

import animepack as ap

from .manga_editions import edition, level_avg, level_range
from .ru_popularity_store import RuPopularityStore, service


def order(generator, pairs):
    if not getattr(generator.s, "manga_strict_targets", False):
        return pairs
    settings = generator.s
    cache = generator.db_cache
    anime = {str(row.get("id")): row for row in cache.all_cards("anime")}
    generator._adapt_cache.update({int(k): v for k, v in anime.items() if k.isdigit()})
    existing = service(generator)
    store = RuPopularityStore(cache, existing.clients, existing.config, persist=False)
    favored = cache.memo_group("manga_favorites")
    low, high = settings.level_range(ap.MANGA_KIND)
    target = (ap.level_avg_target(settings, ap.MANGA_BUCKET) or settings.level_avg
              or (low + high) / 2)
    mix = generator._manga_mix
    quotas = {"manga": mix.kind_target[""], "manhwa": mix.kind_target["manhwa"],
              "manhua": mix.kind_target["manhua"]}
    bands = {key: level_range(settings, key) for key in quotas}
    desired = {"manga": target, "manhwa": min(high, target + .75),
               "manhua": min(high, target + 1.5)}
    # Своя средняя издания важнее прикидки «вебтуны чуть труднее манги».
    own = {key: level_avg(settings, key) for key in quotas if level_avg(settings, key)}
    desired.update(own)
    if quotas["manga"] and "manga" not in own:
        desired["manga"] = max(low, min(high, (target * sum(quotas.values())
            - quotas["manhwa"] * desired["manhwa"]
            - quotas["manhua"] * desired["manhua"]) / quotas["manga"]))
    groups = {key: [] for key in quotas}
    unknown = []
    preferred = getattr(generator, "_manga_catalog_matches", 0)
    for position, pair in enumerate(pairs):
        if generator.stopped():
            break
        card = generator._manga_cache.get(pair[0])
        if not card:
            unknown.append(pair)
            continue
        if not ap.filter_anime(card, settings, manga=True):
            continue
        key = edition(card)
        if not quotas[key]:
            continue
        candidate = ap.SongCandidate({}, card, kind=ap.MANGA_KIND, media="manga")
        candidate.favorites = favored.get(str(card.get("id")))
        candidate.ru_popularity = store.evaluate(candidate, network=False)
        ids = ap.adaptation_ids(card)
        adaptations = [anime[str(i)] for i in ids if str(i) in anime]
        if adaptations:
            ap.apply_adaptation(candidate, max(adaptations,
                                key=lambda c: ap.SongCandidate({}, c).own_index))
        franchise_key = str(card.get("franchise") or "").strip()
        franchise = cache.franchise(franchise_key) if franchise_key else None
        if franchise:
            candidate.franchise_index = max(candidate.franchise_index,
                                            ap.branch_franchise_index(card, franchise))
        level = candidate.level
        if not bands[key][0] <= level <= bands[key][1]:
            # Missing screen metadata can later make this book easier.
            if any(str(i) not in anime for i in ids):
                unknown.append(pair)
            continue
        groups[key].append((position >= preferred, abs(level - desired[key]), position, pair))
    counts = {k: len(v) for k, v in groups.items()}
    queues = {k: deque(row[-1] for row in sorted(v)) for k, v in groups.items()}
    used = dict.fromkeys(quotas, 0)
    ordered = []
    while any(queues.values()):
        key = min((k for k in queues if queues[k]),
                  key=lambda k: (used[k] / max(1, quotas[k]), counts[k]))
        ordered.append(queues[key].popleft())
        used[key] += 1
    generator._manga_plan_stats = {"pool": counts, "desired_levels": desired,
                                  "unknown_screen_metadata": len(unknown)}
    generator.log(f"План комиксов: квоты {quotas}; предварительный пул {counts}; "
                  f"кандидатов с неполными экранизациями {len(unknown)}.")
    return ordered + unknown
