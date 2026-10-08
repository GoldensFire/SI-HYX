"""Song video mode retains quotas and respects other musical presentations."""
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

import animepack as ap
from si_hyx_parts.animepack.song_video import log_summary
from test_animepack_manga_sakuga import generator, make_anime  # noqa: F401


@pytest.mark.parametrize("kind,effect,wants_video", [
    ("opening", "original", True), ("ending", "original", True),
    ("insert", "original", False), ("opening", "cover", False),
    ("opening", "chiptune", False), ("opening", "karaoke", False),
])
@pytest.mark.parametrize("video_succeeds", [True, False])
def test_media_preparation_keeps_song_kind(
        generator, monkeypatch, kind, effect, wants_video, video_succeeds):
    gen = generator
    gen.s.song_video = True
    calls = []
    monkeypatch.setattr(gen, "_title_favorites", lambda c: -1)
    monkeypatch.setattr(gen, "download_images", lambda c: None)

    def video(candidate):
        calls.append("video")
        candidate.has_video = video_succeeds
        candidate.theme_video_ready = video_succeeds
        return video_succeeds

    def audio(candidate):
        calls.append("audio")
        return True

    monkeypatch.setattr(gen, "download_video", video)
    monkeypatch.setattr(gen, "download_audio", audio)
    candidate = ap.SongCandidate({}, make_anime(), kind=kind, music_effect=effect)
    assert gen._fetch_media(candidate)
    expected = ["video"] if wants_video else []
    if not wants_video or not video_succeeds:
        expected.append("audio")
    assert calls == expected
    assert candidate.kind == kind
    assert candidate.has_video == (wants_video and video_succeeds)
    # Check the exported question really plays the selected media.
    candidate.music_effect = "original"
    root = ET.fromstring(ap.build_content_xml([candidate], gen.s))
    items = root.findall(".//{*}param[@name='question']/{*}item")
    media = [item for item in items if item.get("type") in ("audio", "video")]
    assert len(media) == 1
    assert media[0].get("type") == ("video" if candidate.has_video else "audio")


def test_actual_video_count_excludes_audio_and_other_video_effects():
    logs = []
    settings = ap.PackSettings(song_video=True)
    candidates = [
        ap.SongCandidate({}, make_anime(), theme_video_ready=True, has_video=True),
        ap.SongCandidate({}, make_anime(), has_video=True, entrance_video="entrance.mp4"),
        ap.SongCandidate({}, make_anime(), kind="ending"),
        ap.SongCandidate({}, make_anime(), kind="insert"),
        ap.SongCandidate({}, make_anime(), music_effect="karaoke", has_video=True),
    ]
    log_summary(SimpleNamespace(s=settings, log=logs.append), candidates)
    assert logs == ["Видео песен: готово 1 из 3; аудио вместо видео — 2."]
