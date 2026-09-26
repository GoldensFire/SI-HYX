# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_vid_settings. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def _vid_settings(**kw):
    base = dict(strip_specials=False, add_titles=False, compress_images=False,
                strip_repeated_text=False, drop_empty_questions=False,
                compress_audio=False, drop_unused=False, compress_video=True,
                video_min_mb=0.3)
    base.update(kw)
    return _api.UpgradeSettings(**base)

_vid_settings.__module__ = _api.__name__
_api._vid_settings = _vid_settings

def _fake_av1(monkeypatch, size: int = 9000, codec: str = "h264"):
    def fake_encode(self, raw, out):
        with open(out, "wb") as f:
            f.write(b"A" * size)
        return True

    monkeypatch.setattr(_api.PackUpgrader, "_to_av1", fake_encode)
    monkeypatch.setattr(_api.PackUpgrader, "_video_codec", lambda self, raw: codec)

_fake_av1.__module__ = _api.__name__
_api._fake_av1 = _fake_av1

def _q5_video(price: int, name: str) -> str:
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content">'
            f'<item type="video" isRef="True">{name}</item></param>'
            "</params><right><answer>Ответ</answer></right></question>")

_q5_video.__module__ = _api.__name__
_api._q5_video = _q5_video

def test_heavy_video_becomes_av1_and_ref_follows(tmp_path, monkeypatch):
    _api._fake_av1(monkeypatch)
    content = _api._pack(_api._q5_video(100, "ролик.mkv"))
    src = _api._siq(tmp_path, content, media={"Video/ролик.mkv": _api.BIG_VIDEO})
    result = _api.PackUpgrader(src, _api._vid_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        assert "Video/ролик.mp4" in names and "Video/ролик.mkv" not in names
        root, ns = _api.parse_content(zf.read("content.xml"))
    assert root.find(f'.//{_api.tag_fn(ns)("item")}').text == "ролик.mp4"
    assert len(result.videos) == 1 and result.heavy_video == 1
    assert result.saved_video_bytes == len(_api.BIG_VIDEO) - 9000
    assert "h264" in result.videos[0].before
    assert "av1 crf 45" in result.videos[0].after

test_heavy_video_becomes_av1_and_ref_follows.__module__ = _api.__name__
_api.test_heavy_video_becomes_av1_and_ref_follows = test_heavy_video_becomes_av1_and_ref_follows

def test_light_non_av1_video_is_recoded_only_with_the_checkbox(tmp_path,
                                                               monkeypatch):
    _api._fake_av1(monkeypatch, size=500, codec="h264")
    content = _api._pack(_api._q5_video(100, "ролик.mp4"))
    media = {"Video/ролик.mp4": b"V" * 1000}       # намного легче порога
    src = _api._siq(tmp_path, content, media=media)
    assert len(_api.PackUpgrader(src, _api._vid_settings(video_non_av1=True),
                            api=_api.FakeApi()).run().videos) == 1
    off = _api.PackUpgrader(src, _api._vid_settings(video_non_av1=False),
                       api=_api.FakeApi()).run()
    assert off.videos == [] and off.heavy_video == 0

test_light_non_av1_video_is_recoded_only_with_the_checkbox.__module__ = _api.__name__
_api.test_light_non_av1_video_is_recoded_only_with_the_checkbox = test_light_non_av1_video_is_recoded_only_with_the_checkbox

def test_light_av1_video_is_left_alone(tmp_path, monkeypatch):
    """Уже AV1 и легче порога — второй перекод только испортил бы картинку."""
    _api._fake_av1(monkeypatch, codec="av1")
    content = _api._pack(_api._q5_video(100, "ролик.mp4"))
    src = _api._siq(tmp_path, content, media={"Video/ролик.mp4": b"V" * 1000})
    result = _api.PackUpgrader(src, _api._vid_settings(video_non_av1=True),
                          api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Video/ролик.mp4") == b"V" * 1000
    assert result.videos == [] and result.heavy_video == 1

test_light_av1_video_is_left_alone.__module__ = _api.__name__
_api.test_light_av1_video_is_left_alone = test_light_av1_video_is_left_alone

def test_heavy_av1_video_is_recoded_anyway(tmp_path, monkeypatch):
    """Тяжелее порога — жмём, каким бы кодеком ролик ни был закодирован."""
    _api._fake_av1(monkeypatch, codec="av1")
    content = _api._pack(_api._q5_video(100, "ролик.mp4"))
    src = _api._siq(tmp_path, content, media={"Video/ролик.mp4": _api.BIG_VIDEO})
    result = _api.PackUpgrader(src, _api._vid_settings(), api=_api.FakeApi()).run()
    assert len(result.videos) == 1

test_heavy_av1_video_is_recoded_anyway.__module__ = _api.__name__
_api.test_heavy_av1_video_is_recoded_anyway = test_heavy_av1_video_is_recoded_anyway

def test_video_that_got_heavier_stays_as_it_was(tmp_path, monkeypatch):
    _api._fake_av1(monkeypatch, size=len(_api.BIG_VIDEO) + 10)
    content = _api._pack(_api._q5_video(100, "ролик.mp4"))
    src = _api._siq(tmp_path, content, media={"Video/ролик.mp4": _api.BIG_VIDEO})
    result = _api.PackUpgrader(src, _api._vid_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Video/ролик.mp4") == _api.BIG_VIDEO
    assert result.videos == []

test_video_that_got_heavier_stays_as_it_was.__module__ = _api.__name__
_api.test_video_that_got_heavier_stays_as_it_was = test_video_that_got_heavier_stays_as_it_was

def test_images_and_audio_are_not_video(tmp_path, monkeypatch):
    _api._fake_av1(monkeypatch)
    media = {"Images/кадр.jpg": _api.HEAVY, "Audio/песня.mp3": _api.BIG_AUDIO}
    src = _api._siq(tmp_path, _api._pack(_api._q5(100)), media=media)
    result = _api.PackUpgrader(src, _api._vid_settings(), api=_api.FakeApi()).run()
    assert result.heavy_video == 0 and result.videos == []

test_images_and_audio_are_not_video.__module__ = _api.__name__
_api.test_images_and_audio_are_not_video = test_images_and_audio_are_not_video

def test_video_ffmpeg_line_is_the_one_from_the_process_tab(tmp_path,
                                                           monkeypatch):
    seen = []

    def fake_run(cmd, should_stop=None, timeout=0, capture=False):
        seen.append(list(cmd))
        if "-show_entries" in cmd:              # это ffprobe
            return 0, "codec_name=h264"
        with open(cmd[-1], "wb") as f:
            f.write(b"A" * 100)
        return 0, ""

    monkeypatch.setattr("animepack_upgrade.run_hidden", fake_run)
    content = _api._pack(_api._q5_video(100, "ролик.mp4"))
    src = _api._siq(tmp_path, content, media={"Video/ролик.mp4": _api.BIG_VIDEO})
    _api.PackUpgrader(src, _api._vid_settings(video_height=720, audio_norm=True),
                 api=_api.FakeApi()).run()
    line = " ".join(seen[-1])
    assert "libsvtav1" in line and "tune=0:keyint=-1:scd=1" in line
    assert "-crf 45" in line and "-preset 13" in line
    assert "min(720,ih)" in line
    assert "libopus" in line and "loudnorm=I=-20" in line

test_video_ffmpeg_line_is_the_one_from_the_process_tab.__module__ = _api.__name__
_api.test_video_ffmpeg_line_is_the_one_from_the_process_tab = test_video_ffmpeg_line_is_the_one_from_the_process_tab

def test_video_report_and_helpers():
    assert _api.parse_probe_codec("codec_name=av1\n") == "av1"
    assert _api.parse_probe_codec("codec_name=\ncodec_name=hevc") == "hevc"
    assert _api.parse_probe_codec("") == ""
    assert _api.nearest_height(0) == 0 and _api.nearest_height(700) == 720
    assert _api.nearest_height(4000) == 1080 and _api.nearest_height("нет") == 0

test_video_report_and_helpers.__module__ = _api.__name__
_api.test_video_report_and_helpers = test_video_report_and_helpers

def test_video_is_reported(tmp_path, monkeypatch):
    _api._fake_av1(monkeypatch)
    content = _api._pack(_api._q5_video(100, "ролик.mp4"))
    src = _api._siq(tmp_path, content, media={"Video/ролик.mp4": _api.BIG_VIDEO})
    lines = _api.example_lines(_api.PackUpgrader(src, _api._vid_settings(),
                                       api=_api.FakeApi()).run())
    assert any("Роликов перекодировано в AV1: 1" in l for l in lines)

test_video_is_reported.__module__ = _api.__name__
_api.test_video_is_reported = test_video_is_reported

# ── Профиль ───────────────────────────────────────────────────────────────────
# Профиль на паке теперь только один («anime»), но старое сохранённое значение
# («movie», из версий с кино-паком) не должно ломать чтение settings.json —
# normalize_profile сводит любой мусор к единственному, что есть.
def test_profile_name_is_sanitised():
    assert _api.normalize_profile("movie") == "anime"
    assert _api.normalize_profile("anime") == "anime"
    assert _api.normalize_profile("что-то не то") == "anime"
    assert _api.normalize_profile(None) == "anime"
    assert _api.UpgradeSettings().source_name == "Shikimori"
    assert _api.UpgradeSettings.from_dict({"profile": "movie"}).profile == "anime"

test_profile_name_is_sanitised.__module__ = _api.__name__
_api.test_profile_name_is_sanitised = test_profile_name_is_sanitised
