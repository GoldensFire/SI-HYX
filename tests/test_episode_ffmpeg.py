"""End-to-end seeks, AV validation and Russian subtitle burning with bundled tools."""
from pathlib import Path
import random
import time

import pytest
import animepack as api
from si_hyx_parts.animepack.episode_media import cut, inspect_stream, probe, valid_clip
from si_hyx_parts.animepack.episode_stream_quality import dash_variant, hls_variants, selected_hls
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
    # A real 1080p source is scaled down cheaply for seek/subtitle integration checks.
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
    assert start is not None and 18 <= start <= 87
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
    assert burn(generator, target, [(0, 15, "Русские субтитры")])
    assert target.read_bytes() != before
    assert valid_clip(probe(generator, target))
    assert not target.with_suffix(".srt").exists()


@pytest.mark.parametrize("kind,extension", [("mp4", "mp4"), ("hls", "m3u8"), ("dash", "mpd")])
def test_single_encode_burn_uses_clip_clock_after_remote_seek(remote_episode, generator, tmp_path, kind, extension):
    import subprocess
    import numpy as np
    from si_hyx_parts.animepack.episode_subtitles import srt
    _folder, server = remote_episode
    source = {"url": server.base + "/episode." + extension, "type": kind, "audio": "raw",
              "referer": server.base + "/watch", "headers": {"User-Agent": "SI-HYX-test"}}
    plain, shown = tmp_path / "plain.mp4", tmp_path / "shown.mp4"
    subtitles = tmp_path / "relative.srt"
    subtitles.write_text(srt([(3, 7, "Проверка синхронности")]), encoding="utf-8")
    assert cut(generator, None, source, plain, start=30) == 30
    assert cut(generator, None, source, shown, start=30, subtitles=subtitles) == 30
    assert valid_clip(probe(generator, shown))
    def frame(path, at):
        command = [api.FFMPEG, "-v", "error", "-ss", str(at), "-i", str(path),
                   "-frames:v", "1", "-vf", "crop=iw:ih/3:0:2*ih/3,format=gray", "-f", "rawvideo", "-"]
        result = subprocess.run(command, capture_output=True, timeout=20, check=True)
        return np.frombuffer(result.stdout, dtype=np.uint8).astype(float)
    differences = [float(np.mean(abs(frame(plain, at) - frame(shown, at)))) for at in (1, 5, 10)]
    assert differences[1] > max(differences[0], differences[2]) + 1


def test_hls_segments_with_image_extensions_are_still_media(remote_episode, generator, tmp_path):
    _folder, server = remote_episode
    stream = {"url": server.base + "/opaque.m3u8", "type": "hls", "audio": "sub",
              "referer": server.base + "/watch", "headers": {"User-Agent": "SI-HYX-test"}}
    target = tmp_path / "clip.mp4"
    assert cut(generator, None, stream, target) is not None
    assert valid_clip(probe(generator, target))


@pytest.mark.parametrize("kind", ["hls", "dash"])
def test_restricted_manifest_keeps_headers_during_real_encode(remote_episode, generator, tmp_path, kind):
    folder, server = remote_episode
    stream = {"url": server.base + "/episode." + ("mpd" if kind == "dash" else "m3u8"),
              "type": kind, "audio": "sub", "referer": server.base + "/watch",
              "headers": {"User-Agent": "SI-HYX-test"}}
    if kind == "hls":
        master = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="ja",NAME="Japanese",'
                  'LANGUAGE="ja",DEFAULT=YES,URI="audio.m3u8"\n'
                  '#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080,AUDIO="ja"\nvideo.m3u8\n')
        stream["manifest"] = selected_hls(hls_variants(master, stream["url"])[0], stream["url"])
    else:
        selected = dash_variant((folder / "episode.mpd").read_text(encoding="utf-8"), stream["url"])
        stream["manifest"] = selected["manifest"]
    target = tmp_path / "clip.mp4"
    deadline = time.monotonic() + 60
    info = inspect_stream(generator, stream, target, deadline)
    assert info and stream["source_height"] == 1080
    assert cut(generator, None, stream, target, info=info, deadline=deadline) is not None
    assert valid_clip(probe(generator, target))
    assert server.rejected == 0
