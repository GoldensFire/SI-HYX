"""Память пригодности источников отрывков: годный — первым, негодный — мимо."""
from collections import Counter
from pathlib import Path
import time

import animepack as api
from si_hyx_parts.animepack import episode_generation as generation
from si_hyx_parts.animepack import episode_suitability
from si_hyx_parts.kuhi._transport import RequestScope
from test_animepack_episode import generator, info, stream  # noqa: F401


def _scope():
    return RequestScope(lambda: False, time.monotonic() + 60)


def test_known_good_variant_is_probed_alone_and_first(generator, monkeypatch):
    memory = episode_suitability.of(generator)
    good = stream("good", source_link="https://a/1", release="BD")
    rest = [stream(f"p{i}", source_link="https://a/1") for i in range(5)]
    memory.mark(7, good, "ok")
    probed = []
    monkeypatch.setattr(generation, "inspect_stream",
                        lambda gen, s, *a: probed.append(s["provider"]) or info(duration=1400))
    first = next(generation._verified(generator, rest + [good], Path(generator.folder) / "c.mp4",
                                      _scope(), title=7))
    assert first is good and probed == ["good"]


def test_confirmed_bad_variant_is_not_probed_again(generator, monkeypatch):
    low = stream("low", source_link="https://a/1")
    fine = stream("fine", source_link="https://a/1")

    def inspect(gen, s, *a):
        if s["provider"] == "low":
            s["_reject"] = "low"
            return {}
        return info(duration=1400)

    probed = []
    monkeypatch.setattr(generation, "inspect_stream",
                        lambda gen, s, *a: probed.append(s["provider"]) or inspect(gen, s))
    final = Path(generator.folder) / "c.mp4"
    assert list(generation._verified(generator, [low, fine], final, _scope(), title=7)) == [fine]
    episode_suitability.of(generator).save()
    # Новая генерация читает память с диска.
    generator._episode_suitability = episode_suitability.Suitability(
        episode_suitability.of(generator).path)
    probed.clear()
    tally = Counter()
    again = [dict(low), dict(fine)]
    assert [s["provider"] for s in generation._verified(
        generator, again, final, _scope(), title=7, tally=tally)] == ["fine"]
    assert probed == ["fine"] and tally["low"] == 1


def test_transient_failure_pauses_only_briefly(tmp_path):
    memory = episode_suitability.Suitability(str(tmp_path / "s.json"))
    source = stream("x")
    memory.mark(1, source, "pause")
    assert memory.verdict(1, source) == "pause"
    memory.data["streams"][f"1|{episode_suitability.identity(source)}"]["time"] -= 11 * 60
    assert memory.verdict(1, source) == ""


def test_signed_urls_do_not_split_identity():
    a = stream("x", url="https://cdn/clip.m3u8?token=1", release="BD")
    b = stream("x", url="https://cdn/clip.m3u8?token=2", release="BD")
    assert episode_suitability.identity(a) == episode_suitability.identity(b)


def test_title_without_any_good_source_is_skipped_next_time(generator, monkeypatch):
    from test_animepack_new_kinds import make_anime
    memory = episode_suitability.of(generator)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    memory.block_title(candidate.mal_id)
    called = []
    generator.episode_ru = type("Ru", (), {"catalogue": lambda *a: called.append(1) or {},
                                           "close": lambda self: None})()
    assert generator.download_episode(candidate) is False
    assert called == []
