"""Player priority, failover, quality ranking and already supplied RU captions."""
from pathlib import Path
from types import SimpleNamespace

import animepack as api
from si_hyx_parts.animepack import episode_generation as generation
from si_hyx_parts.animepack import episode_subtitles as subtitles
from test_animepack_episode import generator, info, stream
from test_animepack_new_kinds import make_anime


def ru_client(rows, calls):
    return SimpleNamespace(catalogue=lambda *a: {7: rows}, releases=lambda rows, *a: rows,
        streams=lambda rows, *a: calls.extend(row["player"] for row in rows) or [
            stream(row["player"], "sub", player=row["player"], ru_subtitles=True, hardsub=True,
                   url=f"https://{row['player']}/clip-{row.get('height', 1080)}.m3u8",
                   source_height=row.get("height", 1080), bandwidth=row.get("bandwidth", 0),
                   source_link="https://animego.me/anime/title-1", release=row.get("release", "Sub")) for row in rows],
        variants=lambda rows, *a: rows, close=lambda: None)


def test_player_priority_failover_ignores_catalogue_order(generator, monkeypatch):
    calls, cuts = [], []
    generator.episode_ru = ru_client([{"player": p} for p in ("alloha", "animelib", "aniboom", "cvh")], calls)
    def cut(gen, candidate, stream, *a, **kw):
        cuts.append(stream["provider"])
        return 100 if stream["provider"] == "animelib" else None
    monkeypatch.setattr(generation, "cut", cut)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    assert generator.download_episode(candidate)
    assert calls == ["cvh", "aniboom", "animelib"]
    assert cuts == calls
    assert candidate.episode_clip["duration"] == 15
    assert candidate.episode_clip["source_height"] == 1080
    assert candidate.episode_clip["output_height"] == 720
    assert candidate.episode_clip["ru_subtitles"]
    assert candidate.source_link == "https://animego.me/anime/title-1"


def test_highest_verified_quality_wins_within_the_same_player(generator, monkeypatch):
    calls = []
    generator.episode_ru = ru_client([{"player": "cvh", "height": h} for h in (1080, 1440, 720)], calls)
    def inspect(gen, stream, *a):
        return info(duration=1400, height=stream["source_height"]) if stream["source_height"] >= 1080 else {}
    monkeypatch.setattr(generation, "inspect_stream", inspect)
    chosen = []
    monkeypatch.setattr(generation, "cut", lambda gen, candidate, stream, *a, **kw: chosen.append(stream["source_height"]) or 100)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    assert generator.download_episode(candidate)
    assert chosen == [1440]


def test_existing_hardsub_does_not_fetch_or_overlay_external_subtitles(generator, monkeypatch):
    generator.episode_ru = ru_client([{"player": "cvh"}], [])
    generator.s.episode_ru_subtitles = True
    monkeypatch.setattr(generation, "cut", lambda *a, **kw: 100)
    def unwanted(*a):
        raise AssertionError("Must not overlay already embedded Russian subtitles")
    monkeypatch.setattr(subtitles, "find", unwanted)
    monkeypatch.setattr(subtitles, "burn", unwanted)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    assert generator.download_episode(candidate)
    assert candidate.episode_clip["ru_subtitles"]


def test_ru_softsub_failure_tries_next_source(generator, monkeypatch):
    calls = []
    client = ru_client([{"player": "aniboom"}, {"player": "animelib"}], calls)
    original = client.streams
    def streams(rows, *a):
        result = original(rows, *a)
        if rows and rows[0]["player"] == "aniboom":
            result[0]["hardsub"] = False
        return result
    client.streams = streams
    client.captions = lambda *a: []
    generator.episode_ru = client
    monkeypatch.setattr(generation, "cut", lambda *a, **kw: 100)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    assert generator.download_episode(candidate)
    assert calls == ["aniboom", "animelib"]
    assert candidate.episode_clip["provider"] == "animelib"


def test_probe_failure_and_mp4_range_error_do_not_hide_next_release(generator, monkeypatch):
    from si_hyx_parts.kuhi._transport import RequestScope
    import time
    good = stream("good", source_height=1080)
    bad = stream("bad", type="mp4")
    generator.kuhi = SimpleNamespace(range_supported=lambda *a: (_ for _ in ()).throw(RuntimeError("network")), close=lambda: None)
    monkeypatch.setattr(generation, "inspect_stream", lambda *a: info(duration=1400))
    scope = RequestScope(lambda: False, time.monotonic() + 60)
    assert generation._verified(generator, [bad, good], Path(generator.folder) / "clip.mp4", scope) == [good]
