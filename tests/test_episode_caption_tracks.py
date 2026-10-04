"""Russian mode accepts only captions timed to the chosen video release."""
import time
from types import SimpleNamespace

import animepack as api
import pytest
from si_hyx_parts.animepack import episode_captions as captions
from si_hyx_parts.animepack import episode_generation as generation
from si_hyx_parts.animepack.episode_caption_text import parse
from si_hyx_parts.kuhi._transport import RequestScope
from test_animepack_episode import info, stream


@pytest.fixture(autouse=True)
def fixed_scene_start(monkeypatch):
    monkeypatch.setattr(captions, "choose_start", lambda *args: 100)


def generator(files, translate=None):
    return SimpleNamespace(s=api.PackSettings(episode_ru_subtitles=True),
        stopped=lambda: False, rng=SimpleNamespace(uniform=lambda *a: 100),
        kuhi=SimpleNamespace(captions=lambda *a: files),
        gemini=SimpleNamespace(generate_json=translate) if translate else None,
        _log_rare=lambda *a: None)


def scope():
    return RequestScope(lambda: False, time.monotonic() + 30)


VTT = b"WEBVTT\n\n01:39.500 --> 01:43.000 align:center\nHello!\n\n01:50.000 --> 02:00.000\nHow are you?\n"


def test_webvtt_short_times_are_real_episode_times():
    assert parse(VTT, "captions.vtt") == [(99.5, 103, "Hello!"), (110, 120, "How are you?")]


def test_translation_retains_the_video_track_times_and_both_crop_boundaries():
    calls = []
    def translate(prompt, schema):
        calls.append(prompt)
        return {"lines": ["Привет!", "Как дела?"]}
    gen = generator([(VTT, "captions.vtt")], translate)
    source = stream("soft", "sub", subtitles=[{"url": "https://soft/sub.vtt", "srclang": "en"}])
    start, rows = captions.prepare(gen, source, info(duration=1400), scope())
    assert start == 100
    assert rows == [(0, 3, "Привет!"), (10, 15, "Как дела?")]
    assert source["_caption_language"] == "en"
    assert source["_ru_cues"][0]["source_text"] == "Hello!"
    assert len(calls) == 1


def test_missing_track_does_not_use_an_unaligned_external_release():
    gen = generator([])
    source = stream(audio="raw")
    assert captions.prepare(gen, source, info(duration=1400), scope()) is None


def test_english_hardsub_is_the_fallback_and_ru_hardsub_is_preserved():
    gen = generator([])
    english = stream("english", "sub", hardsub=True)
    assert captions.allowed(gen, english)
    assert captions.prepare(gen, english, info(duration=1400), scope()) == (100, [])
    assert english["_caption_output_language"] == "en"
    assert not captions.allowed(gen, stream("other", "sub", hardsub=True, subtitle_language="ja"))
    source = stream("animego", "sub", hardsub=True, ru_subtitles=True)
    assert captions.allowed(gen, source)
    assert captions.prepare(gen, source, info(duration=1400), scope()) == (100, [])
    assert source["_caption_output_language"] == "ru"


@pytest.mark.parametrize("failure", [None, {"lines": ["wrong count"]}, RuntimeError("quota")])
def test_english_timed_captions_survive_missing_or_failed_translation(failure):
    def translate(*args):
        if isinstance(failure, Exception):
            raise failure
        return failure
    gen = generator([(VTT, "captions.vtt")], translate if failure is not None else None)
    source = stream("soft", "sub", subtitles=[{"url": "https://soft/sub.vtt", "srclang": "en"}])
    assert captions.prepare(gen, source, info(duration=1400), scope()) == (
        100, [(0, 3, "Hello!"), (10, 15, "How are you?")])
    assert source["_caption_output_language"] == "en"
    assert source["_ru_cues"][0]["source_text"] == "Hello!"


def test_russian_track_has_priority_over_english_without_spending_translation():
    calls = []
    data = "1\n00:01:39,500 --> 00:01:43,000\nПривет!\n".encode()
    gen = generator([])
    def load(selected, scope):
        calls.append(selected["subtitles"][0]["srclang"])
        return [(data, "ru.srt")]
    gen.kuhi.captions = load
    source = stream("soft", "sub", subtitles=[{"srclang": "en"}, {"srclang": "ru"}])
    assert captions.prepare(gen, source, info(duration=1400), scope()) == (100, [(0, 3, "Привет!")])
    assert calls == ["ru"] and source["_caption_output_language"] == "ru"


def test_partial_english_or_missing_translated_lines_are_rejected():
    for shown in (["Привет!"], ["Привет!", "How are you? Я"], ["", "Как дела?"]):
        gen = generator([(VTT, "captions.vtt")], lambda *a: {"lines": shown})
        source = stream("soft", "sub", subtitles=[{"url": "https://soft/sub.vtt"}])
        assert captions.prepare(gen, source, info(duration=1400), scope()) is None


def test_native_ru_track_is_used_without_translation():
    data = "1\n00:01:39,500 --> 00:01:43,000\nПривет!\n".encode("cp1251")
    gen = generator([])
    gen.episode_ru = SimpleNamespace(captions=lambda *a: [(data, "episode.srt")])
    source = stream("animelib", "sub", ru_subtitles=True, hardsub=False,
                    subtitles=[{"url": "https://lib/sub.srt"}])
    assert captions.prepare(gen, source, info(duration=1400), scope()) == (100, [(0, 3, "Привет!")])


def test_disabled_ru_does_not_add_or_request_captions():
    gen = generator([])
    gen.s.episode_ru_subtitles = False
    assert captions.prepare(gen, stream("english", "sub", hardsub=True),
                            info(duration=1400), scope()) == (100, [])


@pytest.mark.parametrize("hard", [False, True])
def test_english_fallback_reaches_the_finished_clip_with_honest_language_metadata(tmp_path, monkeypatch, hard):
    gen = generator([(VTT, "captions.vtt")])
    gen.episode_ru = None
    gen.log = lambda *a: None
    source = stream("english", "sub", hardsub=hard, source_height=1080,
                    subtitles=[] if hard else [{"srclang": "en"}])
    source["_probe_info"] = info(duration=1400)
    final = tmp_path / "clip.mp4"
    written = []
    def cut(*args, start, subtitles, **kwargs):
        if subtitles:
            written.append(subtitles.read_text(encoding="utf-8"))
        final.write_bytes(b"video")
        return start
    monkeypatch.setattr(generation, "cut", cut)
    candidate = api.SongCandidate({}, {"russian": "Тайтл"}, kind=api.EPISODE_KIND)
    start = generation._try_cut(gen, candidate, source, final, scope())
    assert start == 100
    assert generation._finish(gen, candidate, 1, 2, source, start, final, scope())
    assert candidate.has_video and not candidate.episode_clip["ru_subtitles"]
    assert candidate.episode_clip["subtitle_language"] == "en"
    assert candidate.episode_clip["subtitle_source"] == ("en_hardsub" if hard else "video_track")
    assert not list(tmp_path.glob("*.srt"))
    if not hard:
        assert "Hello!" in written[0] and "00:00:00,000 --> 00:00:03,000" in written[0]
