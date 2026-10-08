"""Question profiles from saved cards; building this index makes no requests."""
import animepack as ap


class CachedProfiles:
    def __init__(self, generator, manga=False):
        self.generator = generator
        self.manga = manga
        target = 'manga' if manga else 'anime'
        cache = generator.db_cache
        self.cards = {}
        for card in cache.all_cards(target):
            try:
                ident = int(card.get('malId') or card.get('id') or 0)
            except (AttributeError, TypeError, ValueError):
                continue
            if ident:
                self.cards[ident] = card
        self.cards.update(generator._manga_cache if manga else generator._card_cache)
        self.favorites = cache.memo_group(target + '_favorites')
        self.parts = {}
        self.indexes = {}
        self.profiles = {}
        self.screens = {}
        if manga:
            self.screens = {str(c.get('id')): c for c in cache.all_cards('anime')}
            from .ru_popularity_store import service
            self.ru = service(generator)
            self.ru.prefetch(self.cards.values())

    def flush(self):
        """Записать наблюдения, накопленные при обходе каталога."""
        if self.manga:
            self.ru.flush()

    def get(self, ident):
        if ident in self.profiles:
            return self.profiles[ident]
        card = self.cards.get(ident)
        if not card:
            return None
        gen = self.generator
        key = str(card.get('franchise') or '').strip()
        if key not in self.parts:
            self.parts[key] = gen.db_cache.franchise(key) if key else []
        parts = self.parts[key]
        branch = ap.franchise_branch_key(card, parts)
        if (key, branch) not in self.indexes:
            self.indexes[key, branch] = ap.branch_franchise_index(card, parts)
        try:
            favored = int(self.favorites.get(str(card.get('id')), -1))
        except (TypeError, ValueError):
            favored = -1
        candidate = ap.SongCandidate(
            {}, card, kind=ap.MANGA_KIND if self.manga else ap.FRAME_KIND,
            media='manga' if self.manga else 'anime', favorites=favored,
            franchise_index=self.indexes[key, branch])
        candidate._profile_incomplete = bool(key and parts is None)
        if self.manga:
            adaptations = ap.adaptation_ids(card)
            screens = [self.screens[str(i)] for i in adaptations if str(i) in self.screens]
            if screens:
                ap.apply_adaptation(candidate, max(screens,
                    key=lambda c: ap.SongCandidate({}, c).own_index))
            candidate.ru_popularity = self.ru.evaluate(candidate, network=False)
            candidate._profile_incomplete |= ('related' not in card or
                any(str(i) not in self.screens for i in adaptations))
        self.profiles[ident] = candidate
        return candidate


def profiles(generator, manga=False):
    indexes = getattr(generator, '_catalog_profiles', None)
    if indexes is None:
        indexes = generator._catalog_profiles = {}
    if manga not in indexes:
        indexes[manga] = CachedProfiles(generator, manga)
    return indexes[manga]
