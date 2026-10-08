"""Try another catalogue recording after a missing CDN file, keeping song identity."""
from karaoke.identity import exact_identity, edition
from karaoke.search import context


def load(generator, candidate, error):
    cause = error.__cause__ or error
    status = getattr(error, 'http_status', 0) or getattr(getattr(cause, 'response', None), 'status_code', 0)
    if status not in (404, 410):
        raise error
    original = candidate.audio_file
    info = context(candidate.song, candidate.anime, candidate.base_kind)
    try:
        rows = generator.anisong.songs_by_name_artist(candidate.song_name, candidate.artist)
    except Exception:
        # AnisongDB 503: other recordings of the song are often already saved.
        local = getattr(generator.anisong, 'songs_by_name_artist_snapshot', None)
        if generator.stopped() or not callable(local):
            raise
        rows = local(candidate.song_name)
    visited = {original}
    for row in (rows or [])[:20]:
        audio = str(row.get('audio') or '')
        if (not audio or audio in visited or edition(row.get('songName', '')) != edition(candidate.song_name)
                or not exact_identity(candidate.song_name, candidate.artist,
                                      row.get('songName', ''), row.get('songArtist', ''), info)):
            continue
        visited.add(audio)
        if len(visited) > 4:
            break
        try:
            from animepack import AMQ_CDN, _MIN_AUDIO_BYTES
            data = generator._cached_bytes(f'{AMQ_CDN}/{audio}', 'amq-audio', _MIN_AUDIO_BYTES)
        except Exception as failure:
            if generator.stopped():
                raise
            generator.log(f'Другой источник аудио «{candidate.song_name}»: {str(failure)[:120]}')
            continue
        candidate.song = {**candidate.song, 'audio': audio}
        generator.log(f'«{candidate.song_name}»: недоступный файл заменён другой записью из каталога.')
        return data
    raise error
