"""Real report failures: punctuation, omitted verses, aliases, resets and exact means."""
from types import SimpleNamespace
import requests
import pytest

from karaoke.excerpt_alignment import recover, windows, payload_for
from karaoke.languages import rank
from karaoke.model import Line, Unit, validate
from karaoke.search import context
from karaoke.ttml import read_ttml


def line(start, text):
    return Line(start, start + 8, [Unit(start, start + 8, text)])


def test_model_threads_respect_hardware_and_explicit_override(monkeypatch):
    from karaoke import asr_worker as worker
    monkeypatch.setattr(worker.os, 'cpu_count', lambda: 12)
    monkeypatch.delenv('SI_HYX_ML_THREADS', raising=False)
    assert worker.cpu_threads(12) == 12 and worker.cpu_threads() == 4
    monkeypatch.setenv('SI_HYX_ML_THREADS', '20')
    assert worker.cpu_threads(12) == 12
    monkeypatch.setenv('SI_HYX_ML_THREADS', '2')
    assert worker.cpu_threads(12) == 2


def test_japanese_separator_does_not_reject_roman_lyrics():
    assert validate([line(0, 'one ・ two')])
    with pytest.raises(ValueError, match='romaji'):
        validate([line(0, 'one 歌 two')])


def test_omitted_line_splits_verse_and_finds_another_complete_twenty_seconds():
    original = ['first phrase', 'missing words', 'second verse', 'third verse', 'last verse']
    anchors = [{'line_index': i, 'start': i * 8, 'end': i * 8 + 8} for i in range(5)]
    lines = [line(i * 8, original[i]) for i in (0, 2, 3, 4)]
    result = recover(lines, anchors, original, 20)
    assert [row['line_index'] for row in result] == [2, 3, 4]
    assert not recover(lines[:2], anchors, original, 20)
    assert not recover([line(0, 'unrelated')], anchors, original, 20)


def test_shifted_verse_roundtrip_preserves_timing():
    lines = [line(35, 'hello'), line(43, 'world')]
    assert read_ttml(payload_for(lines)) == lines
    assert list(windows(100)) == [(0, 60), (35, 95), (70, 100)]


def test_second_audio_window_restores_original_recording_clock(tmp_path, monkeypatch):
    from karaoke import excerpt_alignment as module
    from karaoke.rejections import SourceRejected
    def runner(name, function, command, timeout, **kwargs):
        if 'format=duration' in command:
            return 0, '100'
        from pathlib import Path
        Path(command[-1]).write_bytes(b'window')
        return 0, ''
    monkeypatch.setattr(module, 'budget_run', runner)
    calls = []
    def anchors(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise SourceRejected('no first verse')
        return [{'line_index': i, 'start': i * 8, 'end': (i + 1) * 8} for i in range(3)]
    def aligned(python, group, original, work, minimum, **kwargs):
        return [{**row, 'line': line(row['start'], 'verse')} for row in group]
    monkeypatch.setattr(module, 'align_group', aligned)
    details = {}
    lines, payload = module.run('python', tmp_path / 'source', ['a', 'b', 'c'], ['en'],
        tmp_path, tmp_path, {}, 20, details, anchors,
        stopped=SimpleNamespace(check=lambda: None), log=lambda _: None)
    assert [row.start for row in lines] == [35, 43, 51]
    assert details['confirmed_excerpt'] == [35, 59]
    assert details['analysis_windows_attempted'] == 2
    assert read_ttml(payload) == lines


def test_short_japanese_inserts_do_not_trigger_breton_or_swahili():
    original = ['君と歩くこの世界で未来を信じて歌う', 'Hello my secret code']
    assert rank(original, lambda _: ('br', .999)) == ['ja']
    assert rank(original, lambda _: ('sw', .7)) == ['ja']


def test_catalogue_credited_native_aliases_keep_duets_complete():
    solo = {'songArtist': 'Shoko Nakagawa', 'artists': [{'names': ['Shoko Nakagawa', '中川翔子']}]}
    assert '中川翔子' in context(solo, {})['artists']
    duet = {'songArtist': 'Rei & SennaRin', 'artists': [{'names': ['Rei']}, {'names': ['SennaRin']}]}
    assert context(duet, {})['artists'] == ['Rei & SennaRin']


def test_uta_published_full_name_reading_accepts_shoko_but_not_other_credits():
    from karaoke.uta_net import published_artist_alias
    page = '<h1>中川翔子(nakagawashouko)</h1>'.encode()
    assert published_artist_alias(page, '中川翔子', ['Shoko Nakagawa'])
    assert not published_artist_alias(page, '中川翔子', ['Shoko Nakagawa & Other'])
    assert not published_artist_alias(page, '他の歌手', ['Shoko Nakagawa'])
    assert not published_artist_alias(page, '中川翔子', ['Shoko'])


def test_http_retries_connection_reset_once_but_not_forbidden(tmp_path, monkeypatch):
    from karaoke.http import Http
    client = Http(None, cache=tmp_path)
    calls = []
    def receive(*args):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError('reset')
        return b'lyrics'
    monkeypatch.setattr(client, '_receive', receive)
    assert client.bytes('url') == b'lyrics' and len(calls) == 2
    failure = requests.HTTPError('403', response=SimpleNamespace(status_code=403))
    calls.clear()
    def forbidden(*args):
        calls.append(1)
        raise failure
    monkeypatch.setattr(client, '_receive', forbidden)
    with pytest.raises(requests.HTTPError):
        client.bytes('url')
    assert len(calls) == 1


def test_unavailable_audio_uses_another_exact_catalogue_recording():
    from si_hyx_parts.animepack.song_audio_fallback import load
    import animepack as ap
    candidate = ap.SongCandidate({'songName': 'Song', 'songArtist': 'Artist', 'audio': 'bad.mp3'}, {})
    rows = [{'songName': 'Song', 'songArtist': 'Other', 'audio': 'wrong.mp3'},
            {'songName': 'Song', 'songArtist': 'Artist', 'audio': 'good.mp3'}]
    calls = []
    generator = SimpleNamespace(anisong=SimpleNamespace(songs_by_name_artist=lambda *a: rows),
        _cached_bytes=lambda url, *a: calls.append(url) or b'audio', stopped=lambda: False, log=lambda _: None)
    error = requests.HTTPError('404', response=SimpleNamespace(status_code=404))
    wrapped = ap.AnimePackError('missing')
    wrapped.__cause__ = error
    assert load(generator, candidate, wrapped) == b'audio'
    assert len(calls) == 1 and calls[0].endswith('good.mp3')


def test_permanent_media_error_is_not_retried_and_preserves_http_status():
    import animepack as ap
    from test_animepack_extras import _gen
    generator = _gen(ap.PackSettings())
    calls = []
    def request(*args, **kwargs):
        calls.append(1)
        response = SimpleNamespace(status_code=404)
        def fail():
            raise requests.HTTPError('missing', response=response)
        response.raise_for_status = fail
        return response
    generator.session = SimpleNamespace(get=request)
    with pytest.raises(ap.AnimePackError) as error:
        generator._get_bytes('url')
    assert error.value.http_status == 404 and len(calls) == 1


def test_twelve_song_mean_is_exact_even_when_average_gate_is_relaxed():
    import animepack as ap
    from test_animepack_extras import _gen
    from si_hyx_parts.animepack.level_avg import short_pack_average_error, SONG_BUCKET
    settings = ap.PackSettings(rounds=1, themes=3, questions=4, pct_songs=100, song_level_avg=4)
    generator = _gen(settings)
    generator._level_relaxed = True
    generator._bucket_levels[SONG_BUCKET] = [4] * 11
    assert not generator._level_fits(SimpleNamespace(kind='opening', level=5), [], 'opening')
    assert generator._level_fits(SimpleNamespace(kind='opening', level=4), [], 'opening')
    songs = [SimpleNamespace(kind='opening', level=4) for _ in range(12)]
    assert not short_pack_average_error(settings, songs)
    songs[-1].level = 5
    assert short_pack_average_error(settings, songs)


def test_optional_card_failure_has_no_nested_retries_and_uses_a_cooldown(monkeypatch):
    from si_hyx_parts.animepack.song_optional_catalog import cards
    import shikimori_api
    calls = []
    def client(**options):
        assert options['max_retries'] == 0 and options['timeout'] == (3, 7)
        def request(*args):
            calls.append(args)
            raise RuntimeError('unavailable')
        return SimpleNamespace(_graphql=request)
    monkeypatch.setattr(shikimori_api, 'ShikimoriApiClient', client)
    generator = SimpleNamespace(_card_cache={1: {'id': 1}}, _log_rare=lambda *a: None,
        shikimori=SimpleNamespace(session=None, ANIMES_QUERY='query',
            limiter=SimpleNamespace(acquire=lambda: None),
            client=SimpleNamespace(base_url='https://example.invalid', user_agent='test')))
    assert cards(generator, [1, 2]) == [{'id': 1}]
    assert cards(generator, [1, 2]) == [{'id': 1}]
    assert len(calls) == 1
