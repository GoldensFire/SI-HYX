"""Resolution evidence, highest rendition selection and external audio preservation."""
import asyncio
import json
from pathlib import Path
import random
import socket
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
from urllib.request import urlopen
import xml.etree.ElementTree as ET

import pytest
import animepack  # Initialize the supported public API before loading its parts.
from si_hyx_parts.animepack import episode_media as media
from si_hyx_parts.animepack import episode_stream_quality as quality
from test_animepack_episode import info, stream


HLS = '''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="sound",NAME="Japanese",LANGUAGE="ja",URI="audio/ja.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=1280x720,AUDIO="sound"
low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080,AUDIO="sound"
full.m3u8?token=abc
#EXT-X-STREAM-INF:BANDWIDTH=12000000,RESOLUTION=2560x1440,AUDIO="sound"
best.m3u8
'''


def test_hls_selection_preserves_remote_audio_and_discards_low_renditions(monkeypatch):
    async def get(*args, **kwargs):
        return SimpleNamespace(text=HLS, url="https://cdn/dir/master.m3u8")
    monkeypatch.setattr(quality, "get", get)
    rows = asyncio.run(quality.variants(stream()))
    assert [s["manifest_height"] for s in rows] == [1440, 1080]
    text = rows[1]["manifest"]
    assert 'URI="https://cdn/dir/audio/ja.m3u8"' in text
    assert "https://cdn/dir/full.m3u8?token=abc" in text
    assert "low.m3u8" not in text and "best.m3u8" not in text


def test_explicit_japanese_player_language_binds_only_a_single_audio_track():
    english_tag = {"index": 1, "codec_type": "audio", "tags": {"language": "eng"}}
    source_info = {"streams": [english_tag]}
    assert media.audio_track(source_info) is None
    assert media.audio_track(source_info, source_language="ja") is english_tag
    source_info["streams"].append({"index": 2, "codec_type": "audio", "tags": {"language": "rus"}})
    assert media.audio_track(source_info, source_language="ja") is None


def test_unknown_hls_resolution_is_not_inferred_from_url_or_quality_label(monkeypatch):
    async def get(*args, **kwargs):
        return SimpleNamespace(text="#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2000\n1080.m3u8\n",
                               url="https://cdn/master.m3u8")
    monkeypatch.setattr(quality, "get", get)
    row = asyncio.run(quality.variants(stream(quality="1080p")))[0]
    assert row["manifest_height"] == 0


def test_dash_restricts_video_representation_but_keeps_audio_and_base_url():
    mpd = '''<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>
    <AdaptationSet contentType="video"><SegmentTemplate media="v-$RepresentationID$-$Number$.m4s"/>
      <Representation id="low" height="720" bandwidth="2000"/>
      <Representation id="best" height="1080" bandwidth="4000"/></AdaptationSet>
    <AdaptationSet contentType="audio"><Representation id="ja" bandwidth="100"/></AdaptationSet>
    </Period></MPD>'''
    selected = quality.dash_variant(mpd, "https://cdn/dir/index.mpd?token=abc")
    assert selected["height"] == 1080
    root = ET.fromstring(selected["manifest"])
    ns = "{urn:mpeg:dash:schema:mpd:2011}"
    assert [r.get("id") for r in root.iter(ns + "Representation")] == ["best", "ja"]
    assert root.find(ns + "BaseURL").text == "https://cdn/dir/"


@pytest.mark.parametrize("height", [0, 480, 720])
def test_fake_1080_label_cannot_reach_encoder(tmp_path, height):
    calls = []
    gen = SimpleNamespace(_run_capture=lambda *a, **kw: (0, json.dumps(info(duration=1400, height=height)), ""),
                          _run_killable=lambda *a, **kw: calls.append(a), stopped=lambda: False)
    source = stream(height=1080, quality="1080p")
    assert media.cut(gen, None, source, tmp_path / "clip.mp4") is None
    assert not calls


def test_measured_highest_video_is_mapped_and_source_resolution_recorded(tmp_path):
    source_info = info(duration=1400, height=720)
    source_info["streams"].append({"index": 4, "codec_type": "video", "height": 1080})
    calls = []
    def capture(cmd, **kwargs):
        return 0, json.dumps(source_info if str(cmd[-1]).startswith("https:") else info()), ""
    def run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"clip")
        return 0, ""
    gen = SimpleNamespace(_run_capture=capture, _run_killable=run, stopped=lambda: False,
                          rng=random.Random(1), video_encode_args=lambda: ["-vf", "scale=-2:720"],
                          opus_args=lambda seconds: ["-c:a", "libopus"])
    source = stream(quality=2160)
    measured = media.inspect_stream(gen, source, tmp_path / "clip.mp4", time.monotonic() + 60)
    assert measured and source["source_height"] == 1080
    assert media.cut(gen, None, source, tmp_path / "clip.mp4", info=measured) is not None
    assert calls[0][calls[0].index("-map") + 1] == "0:4"
    assert "scale=-2:720" in calls[0]


def test_restricted_manifest_server_closes_even_when_probe_fails(tmp_path):
    source = stream(manifest=HLS, manifest_height=1080)
    urls = []
    def capture(cmd, **kwargs):
        urls.append(cmd[-1])
        with urlopen(cmd[-1], timeout=2) as response:
            assert response.read().decode("utf-8") == HLS
        return 1, "", "unreadable"
    gen = SimpleNamespace(_run_capture=capture)
    assert not media.inspect_stream(gen, source, tmp_path / "clip.mp4", time.monotonic() + 60)
    address = urlsplit(urls[0])
    with pytest.raises(OSError):
        socket.create_connection((address.hostname, address.port), timeout=1)
    assert not list(tmp_path.glob("*.source.m3u8"))
