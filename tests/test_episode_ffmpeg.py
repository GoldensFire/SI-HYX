"""End-to-end seeks, AV validation and Russian subtitle burning with bundled tools."""
from pathlib import Path
import random

import pytest
import animepack as api
from si_hyx_parts.animepack.episode_media import cut, probe, valid_clip
from si_hyx_parts.animepack.episode_subtitles import burn
from episode_http_fixture import fixtures, serve


@pytest.fixture(scope="module")
def remote_episode(tmp_path_factory):
    if not Path(api.FFMPEG).is_file() or not Path(api.FFPROBE).is_file():
        pytest.skip("bundled FFmpeg/ffprobe unavailable")
    folder = tmp_path_factory.mktemp("episode-http")
    fixtures(folder)
    server, thread = serve(folder)
    yield folder, server
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


@pytest.fixture
def generator():
    gen = api.AnimePackGenerator(api.PackSettings(video_preset=12), rng=random.Random(4))
    # Small source verifies network/seek behavior without encoding a 720p test fixture.
    gen.video_encode_args = lambda: ["-c:v", "libsvtav1", "-preset", "12", "-crf", "45", "-vf", "scale=-2:96"]
    yield gen
    gen.cleanup()


@pytest.mark.parametrize("kind,extension", [("mp4", "mp4"), ("hls", "m3u8"), ("dash", "mpd")])
def test_real_remote_format_is_only_cut_at_selected_segments(remote_episode, generator, tmp_path, kind, extension):
    folder, server = remote_episode
    before = len(server.requests)
    stream = {"url": server.base + "/episode." + extension, "type": kind, "audio": "raw",
              "referer": server.base + "/watch", "headers": {"User-Agent": "SI-HYX-test"}}
    target = tmp_path / "clip.mp4"
    start = cut(generator, None, stream, target)
    assert start is not None and 18 <= start <= 82
    assert valid_clip(probe(generator, target))
    requests = server.requests[before:]
    assert server.rejected == 0
    if kind == "hls":
        segments = {path for path, _, _ in requests if path.endswith(".ts")}
        assert 1 < len(segments) < len(list(folder.glob("*.ts"))) / 2
    elif kind == "dash":
        segments = {path for path, _, _ in requests if path.endswith(".m4s") and "chunk" in path}
        assert segments and len(segments) < len(list(folder.glob("chunk*.m4s"))) / 2
    else:
        assert any(offset > 0 for _, offset, _ in requests)
        # Individual HTTP requests are ranges; no request transfers the complete episode.
        assert all(size < (folder / "episode.mp4").stat().st_size for _, _, size in requests)


def test_real_ru_burn_preserves_a_valid_clip(remote_episode, generator, tmp_path):
    _folder, server = remote_episode
    stream = {"url": server.base + "/episode.m3u8", "type": "hls", "audio": "raw",
              "referer": server.base + "/watch", "headers": {"User-Agent": "SI-HYX-test"}}
    target = tmp_path / "clip.mp4"
    assert cut(generator, None, stream, target) is not None
    before = target.read_bytes()
    assert burn(generator, target, [(0, 20, "Русские субтитры")])
    assert target.read_bytes() != before
    assert valid_clip(probe(generator, target))
    assert not target.with_suffix(".srt").exists()


def test_hls_segments_with_image_extensions_are_still_media(remote_episode, generator, tmp_path):
    _folder, server = remote_episode
    stream = {"url": server.base + "/opaque.m3u8", "type": "hls", "audio": "sub",
              "referer": server.base + "/watch", "headers": {"User-Agent": "SI-HYX-test"}}
    target = tmp_path / "clip.mp4"
    assert cut(generator, None, stream, target) is not None
    assert valid_clip(probe(generator, target))
