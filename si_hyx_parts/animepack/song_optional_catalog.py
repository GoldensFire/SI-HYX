"""Optional extra answer cards use supplied metadata and one bounded request."""
import time


def cards(generator, ids):
    api = getattr(generator, 'shikimori', None)
    if api is None or not hasattr(api, 'client'):
        return generator._animes_by_ids(ids)
    cache = getattr(generator, '_card_cache', {})
    ready = [cache[i] for i in ids if i in cache]
    missing = [i for i in ids if i not in cache]
    if not missing or time.monotonic() < getattr(generator, '_same_song_cards_retry_at', 0):
        return ready
    from network_attempt import single_attempt_session
    from shikimori_api import ShikimoriApiClient
    with single_attempt_session(api.session) as session:
        client = ShikimoriApiClient(base_url=api.client.base_url, user_agent=api.client.user_agent,
                                   timeout=(3, 7), max_retries=0, session=session)
        try:
            api.limiter.acquire()
            data = client._graphql(api.ANIMES_QUERY, {'ids': ','.join(map(str, missing)),
                                                     'limit': len(missing)})
            fresh = (data or {}).get('animes') or []
        except Exception as error:
            generator._same_song_cards_retry_at = time.monotonic() + 300
            generator._log_rare('Одинаковые песни',
                               f'Shikimori: дополнительные ответы временно не загружены: {error}')
            return ready
    fresh = [card for card in fresh if isinstance(card, dict)]
    for card in fresh:
        if str(card.get('id', '')).isdecimal():
            cache[int(card['id'])] = card
    return ready + fresh
