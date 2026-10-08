"""Same backing track cannot turn a cast recording into a solo lyric reference."""
import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

import animepack as ap
from karaoke.matching import metadata_matches
from karaoke.model import Track
from karaoke.mugen import Mugen
from karaoke.search import context
from karaoke.resolver import Resolver
from karaoke.rejections import SourceRejected


CAST = ["Yuki Matsuoka", "Ami Koshimizu", "Asuka Oogame", "Kei Shindô", "Iori Nomizu"]


def test_beam_solo_rejects_cast_even_when_performer_is_a_member():
    track = Track("BEAM my BEAM", CAST, 90, "Karaoke Mugen", "lyrics", "audio")
    assert not metadata_matches("BEAM my BEAM", "Asuka Oogame", 89.47, track)
    assert metadata_matches("BEAM my BEAM", " & ".join(reversed(CAST)), 89.47, track)
    assert not metadata_matches("BEAM my BEAM", " & ".join(CAST[:-1]), 89.47, track)


def test_explicit_cast_lineup_matches_group_but_solo_affiliations_do_not():
    group = {"names": ["Himarinko L Shizukuesu"],
             "members": [{"names": [singer]} for singer in CAST]}
    track = Track("BEAM my BEAM", CAST, 90, "KM", "lyrics", "audio")
    info = context({"artists": [group]}, {})
    assert metadata_matches("BEAM my BEAM", "Himarinko L Shizukuesu", 90, track,
                            lineup=info["performer_lineup"])
    solo = context({"artists": [{"names": ["Asuka Oogame"], "groups": [group]}]}, {})
    assert not metadata_matches("BEAM my BEAM", "Asuka Oogame", 90, track,
                                lineup=solo["performer_lineup"])


def test_group_tags_are_alternative_credits_not_extra_singers():
    row = {"titles": {"eng": "Song"}, "lyrics_infos": [{"filename": "song.ass"}],
           "mediafile": "song.mp4", "singers": [{"name": "Alice"}, {"name": "Bob"}],
           "singergroups": [{"name": "Band"}], "duration": 90}
    track = next(Mugen.tracks({"content": [row]}))
    assert track.artists == ["Alice", "Bob"]
    assert metadata_matches("Song", "Band", 90, track)
    assert metadata_matches("Song", "Bob, Alice", 90, track)
    assert not metadata_matches("Song", "Alice", 90, track)


def test_band_name_with_and_is_one_credit_when_tagged_as_a_singer():
    track = Track("Song", ["Boys and Men"], 90, "KM", "lyrics", "audio")
    assert metadata_matches("Song", "Boys and Men", 90, track)
    assert not metadata_matches("Song", "Boys", 90, track)


def test_stale_positive_cache_is_not_used_after_reference_policy_changes(tmp_path, monkeypatch):
    import karaoke.resolver as module
    from karaoke.rejections import cache_key
    from karaoke.search import SEARCH_POLICY

    source = tmp_path / "source.mp3"
    source.write_bytes(b"recording")
    resolver = Resolver(None, ap.PackSettings(karaoke_ai_fallback=False), "ffmpeg", None,
                        cache=tmp_path)
    old_key = cache_key(hashlib.sha256(b"recording").hexdigest(), "BEAM my BEAM",
                        "Asuka Oogame", "karaoke-v6", SEARCH_POLICY, {})
    resolver.cache.mkdir()
    (resolver.cache / (old_key + ".json")).write_text(
        '{"lines": [{"start": 0, "end": 1, "units": [{"start": 0, "end": 1, '
        '"text": "wrong lyrics"}]}], "metadata": {"source": "Karaoke Mugen", "ai_used": false}}',
        encoding="utf-8")
    resolver.providers = [SimpleNamespace(search=lambda *a: [
        Track("BEAM my BEAM", CAST, 90, "KM", "lyrics", "audio")])]
    monkeypatch.setattr(module, "decode", lambda *a: np.zeros(90 * 22050))
    monkeypatch.setattr(resolver.paired, "resolve", lambda *a: None)
    monkeypatch.setattr(resolver.http, "bytes", lambda *a, **k: pytest.fail("Wrong cast must be rejected"))
    with pytest.raises(SourceRejected):
        resolver.resolve(source, "BEAM my BEAM", "Asuka Oogame")
