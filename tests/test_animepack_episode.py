"""Real-episode selection, media validation and SIQ integration."""
import json
from pathlib import Path
import random
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
import animepack as api
from si_hyx_parts.animepack import episode_generation as generation
from si_hyx_parts.animepack import episode_media as media
from si_hyx_parts.animepack.episode_sources import choose_start, episode_catalog, playable
from test_animepack_new_kinds import make_anime


def info(language="jpn", duration=15, video=True, audio=True, height=1080):
    streams = []
    if video:
        streams.append({"index": 0, "codec_type": "video", "duration": str(duration), "width": 1920, "height": height})
    if audio:
        streams.append({"index": 1, "codec_type": "audio", "tags": {"language": language}, "duration": str(duration)})
    return {"streams": streams, "format": {"duration": str(duration)}}


@pytest.mark.parametrize("language,expected", [("ja", True), ("jpn", True), ("", True), ("eng", False), ("rus", False)])
def test_validation_rejects_explicit_non_japanese(language, expected):
    assert media.valid_clip(info(language)) is expected


@pytest.mark.parametrize("kwargs", [{"video": False}, {"audio": False}, {"duration": 10}, {"duration": 24}])
def test_incomplete_or_bad_duration_is_not_a_question(kwargs):
    assert not media.valid_clip(info(**kwargs))


def test_audio_mapping_selects_japanese_from_multiple_tracks():
    source = info("eng", 1400)
    source["streams"].append({"index": 4, "codec_type": "audio", "tags": {"language": "ja"}})
    assert media.audio_track(source)["index"] == 4


def test_sampled_windows_exclude_entire_intro_and_outro():
    source = {"intro": {"start": 300, "end": 390}, "outro": {"start": 1000, "end": 1090}}
    rng = random.Random(42)
    starts = [choose_start(1400, source, rng) for _ in range(2000)]
    for start in starts:
        assert 0 <= start <= 1385
        assert start + 15 <= 300 or start >= 390
        assert start + 15 <= 1000 or start >= 1090
    assert any(s < 100 for s in starts) and any(s > 1200 for s in starts)


def test_unknown_op_ed_avoids_edges_and_rejects_too_short():
    for seed in range(100):
        start = choose_start(1400, {}, random.Random(seed))
        assert 180 <= start and start + 15 <= 1220
    assert choose_start(15, {}, random.Random()) is None
    assert choose_start(1400, {"intro": {"start": 0, "end": 1400}}, random.Random()) is None


def test_only_existing_sub_or_raw_episodes_are_sampled():
    result = {"providers": {"mkissa": {"episodes": {"raw": [{"number": 7}], "dub": [{"number": 2}]}},
                            "anineko": {"episodes": {"sub": [{"number": 3}, {"number": 9}, {"number": 8, "audio": "dub"}, {"number": 1.5}]}}}}
    assert episode_catalog(result) == {7: {"mkissa": ["raw"]}, 3: {"anineko": ["sub"]}, 9: {"anineko": ["sub"]}}


def stream(provider="mkissa", audio="raw", **kwargs):
    return {"provider": provider, "audio": audio, "type": "hls", "url": f"https://{provider}/clip.m3u8", **kwargs}


def test_streams_prefer_raw_then_softsub_and_never_embed_or_dub():
    hard = stream("hard", "sub")
    soft = stream("soft", "sub", subtitles=[{"url": "https://soft/sub.vtt"}])
    raw = stream()
    assert playable([hard, stream("dub", "dub"), soft, raw, stream(type="embed")]) == [raw, soft, hard]


def test_cut_seeks_input_forwards_headers_and_checks_result(tmp_path):
    calls = []
    def capture(cmd, timeout):
        source = str(cmd[-1]).startswith("https:")
        return 0, json.dumps(info("jpn", 1400 if source else 15)), ""
    def run(cmd, timeout):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"clip")
        return 0, ""
    gen = SimpleNamespace(_run_capture=capture, _run_killable=run, stopped=lambda: False,
                          rng=random.Random(1), video_encode_args=lambda: ["-c:v", "libsvtav1", "-vf", "scale=-2:720"],
                          opus_args=lambda seconds: ["-c:a", "libopus"])
    source = stream(headers={"Origin": "https://custom", "User-Agent": "required"}, referer="https://site/watch")
    assert media.cut(gen, None, source, tmp_path / "clip.mp4") is not None
    cmd = calls[0]
    assert cmd.index("-ss") < cmd.index("-i") < cmd.index("-t")
    assert "Referer: https://site/watch\r\n" in cmd[cmd.index("-headers") + 1]
    assert "User-Agent: required\r\n" in cmd[cmd.index("-headers") + 1]
    assert "Origin: https://custom\r\n" in cmd[cmd.index("-headers") + 1]
    assert cmd[cmd.index("-t") + 1] == "15.0"


@pytest.fixture
def generator(tmp_path, monkeypatch):
    settings = api.PackSettings(pack_episode=True, pct_episode=100, pct_songs=0,
                                rounds=1, themes=1, questions=5, mark_owners=False)
    anizip = SimpleNamespace(info=lambda _: {"mappings": {"anilist_id": 1}})
    gen = api.AnimePackGenerator(settings, anizip=anizip, session=object(),
                                amq=object(), anisong=object(), mal=object(), shikimori=object(),
                                anilist=object(), kitsu=object(), themes=object(), tmdb=object(),
                                rng=random.Random(2))
    gen.prepare_dirs()
    # Unit fixtures don't contact real catalogues or probe imaginary hosts.
    gen.episode_ru.close()
    gen.episode_ru = None
    monkeypatch.setattr(generation, "inspect_stream", lambda *a: info(duration=1400))
    yield gen
    gen.cleanup()


def test_failed_stream_provider_and_episode_fallback(generator, monkeypatch):
    gen = generator
    calls = []
    catalog = {"providers": {"mkissa": {"episodes": {"raw": [{"number": 3}, {"number": 7}]}},
                              "soft": {"episodes": {"sub": [{"number": 3}, {"number": 7}]}}}}
    gen.kuhi.close()
    gen.kuhi = SimpleNamespace(episodes=lambda *a: catalog, streams=lambda aid, ep, *a: [
        stream(), stream("soft", "sub", subtitles=[{}], episode=ep), stream("hard", "sub")], close=lambda: None)
    def cut(*args, **kw):
        source = args[2]
        calls.append(source["provider"])
        return 500 if source["provider"] == "soft" and source["episode"] == 3 else None
    monkeypatch.setattr(generation, "cut", cut)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    assert gen.download_episode(candidate)
    assert calls == ["mkissa", "soft", "hard", "mkissa", "soft"]
    assert candidate.episode_clip["episode"] == 3
    assert candidate.has_video and candidate.is_silent


def test_settings_and_siq_are_a_separate_video_kind(generator):
    settings = generator.s
    assert settings.question_quotas[api.EPISODE_KIND] == 5
    assert not settings.episode_ru_subtitles and not settings.has_songs
    assert api.PackSettings.from_dict(settings.to_dict()).mix_shares == settings.mix_shares
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND, has_video=True)
    xml = ET.fromstring(api.build_content_xml([candidate], settings))
    videos = [n for n in xml.iter() if n.tag.split("}")[-1] == "item" and n.get("type") == "video"]
    assert len(videos) == 1 and videos[0].text == candidate.video_out
    assert not any(n.get("type") == "audio" for n in xml.iter())
