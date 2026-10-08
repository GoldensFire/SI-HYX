"""SD-era titles survive manifest filtering, probing, encoding and cache reuse."""
import asyncio
import json
from pathlib import Path
import random
from types import SimpleNamespace

import pytest
import animepack
from si_hyx_parts.animepack import episode_media as media
from si_hyx_parts.animepack import episode_stream_quality as quality
from si_hyx_parts.animepack.episode_quality_policy import minimum
from si_hyx_parts.animepack.episode_suitability import Suitability
from test_animepack_episode import info, stream


@pytest.mark.parametrize("year,height", [(1989, 480), (2005, 480), (2006, 1080), (2026, 1080), (0, 1080)])
def test_release_policy(year, height):
    assert minimum(SimpleNamespace(year=year)) == height


def test_sd_hls_keeps_480_prefers_hd_and_excludes_360(monkeypatch):
    manifest = "#EXTM3U\n" + "".join(
        f"#EXT-X-STREAM-INF:BANDWIDTH={height * 1000},RESOLUTION=640x{height}\n{height}.m3u8\n"
        for height in (360, 480, 1080))
    async def get(*args, **kwargs):
        return SimpleNamespace(text=manifest, url="https://cdn/master.m3u8")
    monkeypatch.setattr(quality, "get", get)
    rows = asyncio.run(quality.variants(stream(min_height=480)))
    assert [row["manifest_height"] for row in rows] == [1080, 480]
    assert [row["manifest_height"] for row in asyncio.run(quality.variants(stream()))] == [1080]


def test_sd_dash_retains_real_manifest_and_audio():
    text = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>'
    text += '<AdaptationSet contentType="video"><Representation id="sd" height="480" bandwidth="1"/></AdaptationSet>'
    text += '<AdaptationSet contentType="audio"><Representation id="ja"/></AdaptationSet></Period></MPD>'
    assert "manifest" not in quality.dash_variant(text, "https://cdn/master.mpd")
    selected = quality.dash_variant(text, "https://cdn/master.mpd", 480)
    assert selected["height"] == 480 and 'id="ja"' in selected["manifest"]


def test_real_480_track_is_accepted_and_cut_without_upscale(tmp_path):
    commands = []
    def capture(command, timeout):
        seconds = 1400 if str(command[-1]).startswith("https:") else 15
        return 0, json.dumps(info(duration=seconds, height=480)), ""
    def run(command, timeout):
        commands.append(command)
        Path(command[-1]).write_bytes(b"clip")
        return 0, ""
    generator = SimpleNamespace(_run_capture=capture, _run_killable=run, stopped=lambda: False,
        rng=random.Random(1), video_encode_args=lambda: ["-vf", "scale=-2:720"],
        opus_args=lambda _: ["-c:a", "libopus"])
    final = tmp_path / "clip.mp4"
    source = stream(min_height=480, manifest_height=480)
    import time
    assert media.inspect_stream(generator, source, final, time.monotonic() + 60)
    assert source["source_height"] == 480
    assert media.cut(generator, None, source, final) is not None
    # Фильтр масштаба — у локального кодирования, после копии куска из сети.
    filter_text = commands[-1][commands[-1].index("-vf") + 1]
    assert "scale=-2:480" in filter_text and "720" not in filter_text
    assert not media.inspect_stream(generator, stream(manifest_height=480), final, time.monotonic() + 60)


def test_hd_rejection_does_not_poison_sd_policy(tmp_path):
    memory = Suitability(str(tmp_path / "sources.json"))
    source = stream(min_height=1080)
    memory.mark(7, source, "low")
    memory.block_title(7)
    assert memory.verdict(7, dict(source, min_height=480)) == ""
    assert not memory.title_blocked(7, 480)
    assert memory.title_blocked(7)
    memory.mark(8, stream(min_height=480, manifest_height=480), "low")
    assert memory.verdict(8, stream(min_height=480, manifest_height=1080)) == ""


def test_bundled_ffmpeg_cuts_actual_480p_stream_without_upscale(tmp_path):
    import animepack as ap
    import time
    from episode_http_fixture import run, serve
    if not Path(ap.FFMPEG).is_file() or not Path(ap.FFPROBE).is_file():
        pytest.skip("bundled FFmpeg unavailable")
    run(["-f", "lavfi", "-i", "testsrc2=size=854x480:rate=2", "-f", "lavfi", "-i",
         "sine=frequency=440:sample_rate=48000", "-t", "30", "-c:v", "libx264",
         "-preset", "ultrafast", "-c:a", "aac", "-metadata:s:a:0", "language=jpn",
         "-movflags", "+faststart", str(tmp_path / "episode.mp4")])
    server, thread = serve(tmp_path)
    generator = ap.AnimePackGenerator(ap.PackSettings(video_preset=12))
    try:
        source = stream(type="mp4", url=server.base + "/episode.mp4", min_height=480,
                        referer=server.base + "/watch", headers={"User-Agent": "SI-HYX-test"})
        final = tmp_path / "clip.mp4"
        verified = media.inspect_stream(generator, source, final, time.monotonic() + 60)
        assert verified and source["source_height"] == 480
        assert media.cut(generator, None, source, final, start=2, info=verified) == 2
        result = media.probe(generator, final)
        assert media.valid_clip(result) and media.video_track(result)["height"] == 480
        assert media.video_track(result)["width"] == 854 and server.rejected == 0
    finally:
        generator.cleanup()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
