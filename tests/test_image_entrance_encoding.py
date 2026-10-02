# -*- coding: utf-8 -*-
"""Настоящие MP4 и SIQ: статичные картинки, несколько кадров и движущееся видео."""
import json
import os
from pathlib import Path
import random
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageStat

import animepack as ap
from image_entrance import PACK_EFFECTS
from si_hyx_parts.animepack.entrance_processing import apply


@pytest.fixture
def generator(tmp_path, monkeypatch):
    if not Path(ap.FFMPEG).is_file():
        pytest.skip("локальный ffmpeg не установлен")
    settings = ap.PackSettings(entrance_enabled=True, entrance_seconds=0.4,
                               entrance_fps=10, entrance_preset=12,
                               video_crf=25, rounds=1, themes=1, questions=1)
    gen = ap.AnimePackGenerator(settings, session=object(), rng=random.Random(42),
                               frames_history_path=str(tmp_path / "history.json"))
    gen.folder = str(tmp_path / "пак с пробелами")
    for name in ("Images", "Video", "Audio"):
        Path(gen.folder, name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ap, "PIXEL_HEIGHT", 90)
    image = Image.new("RGB", (160, 90), "#4594cf")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 10, 70, 80), fill="#f4c897")
    draw.ellipse((82, 22, 135, 74), fill="#cba6f7")
    image.save(Path(gen.folder, "Images", "source.png"))
    return gen, image


def candidate(kind="frame"):
    return ap.SongCandidate(song={}, anime={"malId": 1, "name": "Sample", "russian": "Пример"},
                            kind=kind, media_base=f"Пример {kind}", has_frame=True,
                            frame_name="source.png")


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, timeout=60,
                            creationflags=ap.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


@pytest.mark.parametrize("effect", PACK_EFFECTS)
def test_every_effect_is_encoded_and_packaged(generator, effect, tmp_path):
    gen, original = generator
    gen.s.entrance_effect = effect
    cand = candidate()
    assert apply(gen, cand)
    assert cand.entrance_effect == effect and not cand.has_video
    name = cand.entrance_frames["source.png"]
    video = Path(gen.folder, "Video", name)
    assert gen._media_size(cand) == video.stat().st_size
    data = run([ap.FFMPEG, "-v", "error", "-i", str(video),
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    frame_size = original.width * original.height * 3
    assert len(data) == 4 * frame_size
    last = Image.frombytes("RGB", original.size, data[-frame_size:])
    assert sum(ImageStat.Stat(ImageChops.difference(original, last)).mean) / 3 < 8
    assert data[:frame_size] != data[-frame_size:]
    package = gen.write_package([cand], str(tmp_path / "Эффекты.siq"))
    with zipfile.ZipFile(package) as archive:
        xml = ET.fromstring(archive.read("content.xml"))
        items = xml.findall(".//s:param[@name='question']/s:item", {"s": ap.SIQ_NS})
        assert [(i.get("type"), i.text) for i in items] == [("video", name)]
        assert all(i.get("duration") == "00:00:05" for i in items)
        assert archive.read("Video/" + name) == video.read_bytes()
        assert "Images/source.png" not in archive.namelist()
    assert not list(Path(gen.folder).glob("_entrance_*"))


@pytest.mark.parametrize("kind", ["manga", "character", "ai_art", "pixiv_art", "studio"])
def test_image_targets_and_studio_timing(generator, kind):
    gen, _ = generator
    gen.s.entrance_targets = [kind]
    gen.s.entrance_effect = "split"
    cand = candidate(kind)
    if kind == "studio":
        cand.extra_frames = ["second.png"]
        Path(gen.folder, "Images", "second.png").write_bytes(
            Path(gen.folder, "Images", "source.png").read_bytes())
    assert apply(gen, cand)
    root = ET.fromstring(ap.build_content_xml([cand], gen.s))
    items = root.findall(".//s:param[@name='question']/s:item", {"s": ap.SIQ_NS})
    if cand.is_character:
        caption = items.pop(0)
        assert caption.text == ap.CHAR_TASK_TEXT
        assert caption.attrib == {"waitForFinish": "False"}
    if cand.is_studio:
        for caption in items[::2]:
            assert caption.text == ap.STUDIO_TASK_TEXT
            assert caption.attrib == {"waitForFinish": "False"}
        items = items[1::2]
    assert sum(i.get("type") == "video" for i in items) == len(cand.question_frames)
    seconds = "00:00:04" if cand.is_character or cand.is_studio else "00:00:05"
    assert all(i.get("type") == "video" and i.get("duration") == seconds
               for i in items)


def test_unselected_target_and_stopped_encoding_create_no_output(generator):
    gen, _ = generator
    cand = candidate("manga")
    assert apply(gen, cand) and not cand.entrance_frames
    gen.s.entrance_targets = ["manga"]
    gen._should_stop = lambda: True
    assert not apply(gen, cand)
    assert not cand.entrance_frames and not list(Path(gen.folder, "Video").iterdir())


@pytest.mark.parametrize("kind,with_audio", [("sakuga", False), ("video", True), ("pixel", False)])
def test_video_keeps_movement_duration_and_audio(generator, kind, with_audio, tmp_path):
    gen, _ = generator
    cand = candidate(kind)
    cand.has_frame, cand.has_video = False, True
    gen.s.entrance_targets = [kind]
    gen.s.entrance_effect = "spin"
    cmd = [ap.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-c:a", "aac"]
    original = Path(gen.folder, "Video", cand.video_out)
    run(cmd + ["-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(original)])
    assert apply(gen, cand) and cand.entrance_video
    result = Path(gen.folder, "Video", cand.entrance_video)
    probe = json.loads(run([ap.FFPROBE, "-v", "error", "-show_entries",
                           "stream=codec_type:format=duration", "-of", "json", str(result)]))
    assert float(probe["format"]["duration"]) == pytest.approx(2, abs=0.05)
    assert any(s["codec_type"] == "audio" for s in probe["streams"]) == with_audio
    frames = run([ap.FFMPEG, "-v", "error", "-i", str(result), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    assert len(frames) == 20 * 160 * 90 * 3
    assert frames[160 * 90 * 3:2 * 160 * 90 * 3] != frames[2 * 160 * 90 * 3:3 * 160 * 90 * 3]
    if with_audio:
        extract = lambda path: run([ap.FFMPEG, "-v", "error", "-i", str(path), "-vn", "-c:a", "copy", "-f", "adts", "-"])
        assert extract(original) == extract(result)
    package = gen.write_package([cand], str(tmp_path / "Видео.siq"))
    with zipfile.ZipFile(package) as archive:
        root = ET.fromstring(archive.read("content.xml"))
        items = root.findall(".//s:param[@name='question']/s:item", {"s": ap.SIQ_NS})
        assert len(items) == 1
        item = items[0]
        assert item.text == cand.entrance_video
        assert item.get("duration") == "00:00:05"
        assert "Video/" + cand.entrance_video in archive.namelist()
        assert "Video/" + cand.video_out not in archive.namelist()
