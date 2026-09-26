# -*- coding: utf-8 -*-
"""Настоящее видео и SIQ; сетевые источники заменены локальной картинкой."""
import io
import os
from pathlib import Path
import random
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageStat

import animepack
from frame_reveal import ANIMATED_EFFECTS, EFFECT_LABELS, stage_frame_counts
from frame_reveal_dvd import DVD_FPS


@pytest.fixture
def generator(tmp_path, monkeypatch):
    image = Image.new("RGB", (160, 90), "#4594cf")
    draw = ImageDraw.Draw(image)
    for x in range(0, 160, 8):
        draw.rectangle((x, 0, x + 3, 89), fill=(x, 180, 255 - x))
    draw.ellipse((48, 12, 116, 82), fill="#f4c897", outline="#282133", width=3)
    draw.rectangle((65, 36, 70, 43), fill="black")
    draw.rectangle((95, 36, 100, 43), fill="black")
    data = io.BytesIO()
    image.save(data, format="PNG")
    settings = animepack.PackSettings(
        pct_songs=0, pack_pixel=True, pct_pixel=100, rounds=1, themes=1, questions=1,
        pixel_seconds=4, pixel_steps=4, pixel_fps=5, frame_effect_strength=80,
        video_preset=12, video_crf=30, out_dir=str(tmp_path))
    gen = animepack.AnimePackGenerator(settings, session=object(), rng=random.Random(42),
                                      frames_history_path=str(tmp_path / "history.json"))
    gen.folder = str(tmp_path / "пак с пробелами")
    for name in ("Images", "Video", "Audio"):
        Path(gen.folder, name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(gen, "_pick_frame_url", lambda c: "https://example.invalid/frame.png")
    monkeypatch.setattr(gen, "_get_bytes", lambda url: data.getvalue())
    monkeypatch.setattr(animepack, "PIXEL_HEIGHT", 90)
    return gen, image


def candidate():
    return animepack.SongCandidate(
        song={}, anime={"malId": 1, "name": "Sample", "russian": "Пример"},
        kind=animepack.PIXEL_KIND, media_base="Кадр (пример)")


@pytest.mark.parametrize("effect", EFFECT_LABELS)
def test_real_video_and_package_contain_all_stages(generator, effect, tmp_path):
    if not (Path(animepack.FFMPEG).is_file() or shutil.which(animepack.FFMPEG)):
        pytest.skip("ffmpeg не установлен")
    gen, original = generator
    gen.s.frame_effect = effect
    cand = candidate()
    assert gen.download_pixel(cand)
    assert cand.has_video and cand.frame_effect == effect
    video = Path(gen.folder, "Video", cand.video_out)
    decoded = subprocess.run(
        [animepack.FFMPEG, "-v", "error", "-i", str(video), "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=45,
        creationflags=animepack.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert decoded.returncode == 0, decoded.stderr.decode("utf-8", "replace")
    frame_size = original.width * original.height * 3
    # 4 секунды при 5 кадрах/с; «DVD-заставка» всегда идёт 30 кадров/с.
    fps = DVD_FPS if effect in ANIMATED_EFFECTS else 5
    counts = stage_frame_counts(4, fps, 4)
    assert len(decoded.stdout) == frame_size * 4 * fps
    first = Image.frombytes("RGB", original.size, decoded.stdout[:frame_size])
    last = Image.frombytes("RGB", original.size, decoded.stdout[-frame_size:])
    error = lambda im: sum(ImageStat.Stat(ImageChops.difference(original, im)).mean) / 3
    clean = sum(counts[:-1])
    final_start = Image.frombytes(
        "RGB", original.size,
        decoded.stdout[clean * frame_size:(clean + 1) * frame_size])
    if effect in ANIMATED_EFFECTS:
        # DVD-заставка полный кадр не показывает: последняя ступень —
        # застывший последний кадр движения, необлетённое чёрное.
        assert error(last) > 8
        assert error(final_start) == error(last)
    else:
        assert error(last) < 8
        assert error(first) > error(last) + 1
        # Последняя ступень занимает своё полное окно, а не один кадр в конце.
        assert error(final_start) < 8
    package = gen.write_package([cand], str(tmp_path / "Тест эффектов.siq"))
    with zipfile.ZipFile(package) as archive:
        xml = ET.fromstring(archive.read("content.xml"))
        item = xml.find(".//s:param[@name='question']/s:item", {"s": animepack.SIQ_NS})
        assert item.get("type") == "video"
        # Ролик и вопрос длятся ровно одинаково: пятисекундного хвоста больше
        # нет (просьба пользователя).
        assert item.get("duration") == "00:00:04"
        assert archive.read(f"Video/{item.text}") == video.read_bytes()
        assert not any("step_" in name or "_reveal_" in name for name in archive.namelist())
    assert not list(Path(gen.folder).glob("_reveal_*"))
    assert not list(Path(gen.folder, "Images").glob("_pix_*"))


def test_random_choice_is_recorded_once_per_question(generator, monkeypatch):
    gen, _ = generator
    gen.s.frame_effect = "random"
    gen.s.frame_effects = ["tiles", "zoom"]
    calls = []

    def encode(source, output, effect, seed):
        calls.append((effect, seed))
        Path(output).write_bytes(b"video")
        return 0, ""

    monkeypatch.setattr(gen, "encode_reveal", encode)
    for _ in range(12):
        cand = candidate()
        assert gen.download_pixel(cand)
        assert cand.frame_effect == calls[-1][0]
    assert {effect for effect, _ in calls} == {"tiles", "zoom"}
    assert len({seed for _, seed in calls}) == 12


@pytest.mark.parametrize("effect", ["pixelize", "tiles"])
@pytest.mark.parametrize("seconds,fps,steps,clean_start", [(2, 1, 20, 1), (7, 7, 6, 40)])
def test_clean_final_stage_at_low_and_fractional_fps(generator, effect, seconds, fps, steps, clean_start):
    if not (Path(animepack.FFMPEG).is_file() or shutil.which(animepack.FFMPEG)):
        pytest.skip("ffmpeg не установлен")
    gen, original = generator
    gen.s.frame_effect = effect
    gen.s.pixel_seconds, gen.s.pixel_fps, gen.s.pixel_steps = seconds, fps, steps
    cand = candidate()
    assert gen.download_pixel(cand)
    decoded = subprocess.run(
        [animepack.FFMPEG, "-v", "error", "-i", str(Path(gen.folder, "Video", cand.video_out)),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=45,
        creationflags=animepack.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert decoded.returncode == 0
    frame_size = original.width * original.height * 3
    assert len(decoded.stdout) == seconds * fps * frame_size
    data = decoded.stdout[clean_start * frame_size:(clean_start + 1) * frame_size]
    clean = Image.frombytes("RGB", original.size, data)
    assert sum(ImageStat.Stat(ImageChops.difference(original, clean)).mean) / 3 < 8


@pytest.mark.parametrize("failure", ["encode", "stop", "invalid_image"])
def test_failure_and_stop_clean_temporary_files(generator, monkeypatch, failure):
    gen, _ = generator
    gen.s.frame_effect = "tiles"
    cand = candidate()

    def fail(cmd, timeout):
        Path(cmd[-1]).write_bytes(b"partial video")
        return 1, "test failure"

    monkeypatch.setattr(gen, "_run_killable", fail)
    if failure == "stop":
        checks = iter([False, False, True])
        monkeypatch.setattr(gen, "stopped", lambda: next(checks, True))
    elif failure == "invalid_image":
        monkeypatch.setattr(gen, "_get_bytes", lambda url: b"not an image")
    assert not gen.download_pixel(cand)
    assert not cand.has_video
    assert not Path(gen.folder, "Video", cand.video_out).exists()
    assert not list(Path(gen.folder).glob("_reveal_*"))
    assert not list(Path(gen.folder, "Images").glob("_pix_*"))
