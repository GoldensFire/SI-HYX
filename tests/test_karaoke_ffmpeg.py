"""Real filter rendering and SIQ video references, including disabled reverse."""
import json
from pathlib import Path
import shutil
import wave
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import pytest
import animepack as ap

from karaoke.model import Line, Unit
from si_hyx_parts.animepack.karaoke_processing import download_karaoke


@pytest.fixture
def generator(tmp_path, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe are required for real karaoke rendering")
    monkeypatch.setattr(ap, "FFMPEG", ffmpeg)
    monkeypatch.setattr(ap, "FFPROBE", ffprobe)
    settings = ap.PackSettings(rounds=1, themes=1, questions=1, karaoke_enabled=True,
                               karaoke_percent=100, audio_cut=5, video_preset=10,
                               karaoke_crf=35, karaoke_preset=12)
    generator = ap.AnimePackGenerator(settings)
    generator.folder = str(tmp_path)
    for folder in ("Audio", "Video", "Images"):
        (tmp_path / folder).mkdir()
    source = tmp_path / "source.wav"
    t = np.arange(44100 * 6) / 44100
    pcm = (np.sin(2 * np.pi * 440 * t) * 5000).astype("<i2")
    with wave.open(str(source), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(44100)
        stream.writeframes(pcm.tobytes())
    monkeypatch.setattr(generator, "_cached_bytes", lambda *a: source.read_bytes())
    lines = [Line(0, 5, [Unit(0, 2, "kimi "), Unit(2, 5, "wa")], {"en": "You"})]
    metadata = {"duration": 6, "offset": 0, "source": "fixture", "ai_used": False}
    monkeypatch.setattr(generator.karaoke_resolver, "resolve", lambda *a: (lines, dict(metadata)))
    return generator


@pytest.mark.parametrize("effect", ["original", "pitch", "noise", "bandpass", "tempo"])
def test_real_filter_video_has_audio_and_matches_transformed_duration(generator, effect, monkeypatch):
    commands = []
    original = generator._run_killable
    def capture(command, **kwargs):
        commands.append(command)
        return original(command, **kwargs)
    monkeypatch.setattr(generator, "_run_killable", capture)
    generator.s.karaoke_effect = effect
    generator.s.karaoke_pitch = 2
    generator.s.karaoke_tempo = 1.25
    candidate = ap.SongCandidate({"audio": "source.wav", "songName": "Test", "songArtist": "Test"},
                                 {"name": "Anime"}, kind="opening", music_effect="karaoke")
    assert download_karaoke(generator, candidate)
    assert candidate.has_video
    target = Path(generator.folder) / "Video" / candidate.video_out
    code, text, _ = generator._run_capture([ap.FFPROBE, "-v", "error", "-show_streams",
                                           "-show_format", "-of", "json", str(target)], timeout=30)
    probe = json.loads(text)
    assert code == 0
    assert {row["codec_name"] for row in probe["streams"]} == {"av1", "opus"}
    expected = 4 if effect == "tempo" else 5
    assert float(probe["format"]["duration"]) == pytest.approx(expected, abs=.1)
    assert candidate.karaoke["output_duration"] == expected
    assert candidate.karaoke["crf"] == 35 and candidate.karaoke["preset"] == 12
    assert commands[-1][commands[-1].index("-crf") + 1] == "35"
    assert commands[-1][commands[-1].index("-preset") + 1] == "12"
    candidate.anime["score"] = "8.7"
    candidate.has_poster = True
    from PIL import Image
    Image.new("RGB", (100, 150), "red").save(Path(generator.folder) / "Images" / candidate.poster_file)
    path = generator.write_package([candidate], str(Path(generator.folder) / "test.siq"))
    with zipfile.ZipFile(path) as archive:
        assert "Video/" + candidate.video_out in archive.namelist()
        assert "karaoke.json" in archive.namelist()
        assert candidate.video_out.encode() in archive.read("content.xml")
        root = ET.fromstring(archive.read("content.xml"))
        items = root.findall(".//{*}item")
        video = next(item for item in items if item.get("type") == "video")
        assert "duration" not in video.attrib
        prompt = root.find(".//{*}param[@name='question']")
        answer = root.find(".//{*}param[@name='answer']")
        assert "караоке" not in " ".join(prompt.itertext()).casefold()
        assert "8.70⭐" in " ".join(answer.itertext())
        poster = answer.find("{*}item[@type='image']")
        assert poster.text == candidate.poster_file
        assert "Images/" + poster.text in archive.namelist()
        assert r"\kf" in archive.read("Karaoke/" + target.stem + ".ass").decode("utf-8-sig")


def test_reverse_generates_audio_without_looking_for_lyrics_or_models(generator, monkeypatch):
    generator.s.karaoke_effect = "reverse"
    def unexpected(*args):
        raise AssertionError("Reverse must disable lyrics completely")
    monkeypatch.setattr(generator.karaoke_resolver, "resolve", unexpected)
    candidate = ap.SongCandidate({"audio": "source.wav", "songName": "Test"}, {"name": "Anime"},
                                 kind="ending", music_effect="karaoke")
    assert download_karaoke(generator, candidate)
    assert not candidate.has_video and candidate.karaoke["disabled"] == "reverse"
    assert (Path(generator.folder) / "Audio" / candidate.audio_out).is_file()
