# -*- coding: utf-8 -*-
"""Offline integration: actual yt-dlp/FFmpeg cut two local HTTP inputs."""
import http.server
import json
import os
import re
import subprocess
import threading
from pathlib import Path

import pytest

import workers
from si_hyx_parts.workers.download_result import probe_download


def test_real_ffmpeg_reconnect_arguments_apply_to_both_inputs(tmp_path):
    if not (os.path.isfile(workers.FFMPEG) and os.path.isfile(workers.FFPROBE)
            and workers.ytdlp_base_cmd()):
        pytest.skip("Bundled yt-dlp/FFmpeg required for offline integration")
    files = {}
    for name, source, codec in (
        ("video.mp4", "color=c=black:s=128x72:r=10:d=10", ["-an", "-c:v", "mpeg4"]),
        ("audio.m4a", "sine=frequency=440:duration=10", ["-vn", "-c:a", "aac"]),
    ):
        subprocess.run(
            [workers.FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", source, *codec, "-movflags", "+faststart", "-y", str(tmp_path / name)],
            check=True, creationflags=workers.CREATE_NO_WINDOW, timeout=30)
        files["/" + name] = (tmp_path / name).read_bytes()

    class RangeHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = files.get(self.path)
            if data is None:
                self.send_error(404)
                return
            start, end = 0, len(data) - 1
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
                assert match is not None
                start = int(match[1])
                end = min(end, int(match[2])) if match[2] else end
            self.send_response(206 if requested else 200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.end_headers()
            try:
                self.wfile.write(data[start:end + 1])
            except (BrokenPipeError, ConnectionResetError):
                pass  # FFmpeg can close an input after reading its requested section.

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_address[1]}"
    info = {
        "id": "local", "title": "integration", "extractor": "generic",
        "extractor_key": "Generic", "webpage_url": address + "/video.mp4", "duration": 10,
        "formats": [
            {"format_id": "v", "url": address + "/video.mp4", "ext": "mp4",
             "protocol": "http", "vcodec": "mpeg4", "acodec": "none", "width": 128, "height": 72},
            {"format_id": "a", "url": address + "/audio.m4a", "ext": "m4a",
             "protocol": "http", "vcodec": "none", "acodec": "aac"},
        ],
    }
    info_path = tmp_path / "info.json"
    info_path.write_text(json.dumps(info), encoding="utf-8")
    worker = workers.YtdlpWorker({
        "iid": "offline", "url": address + "/video.mp4", "outdir": str(tmp_path),
        "source_duration": 10, "start_s": 2, "end_s": 5,
    })
    command = workers.ytdlp_base_cmd() + [
        "--ignore-config", "--load-info-json", str(info_path), "--no-simulate", "--no-quiet",
        "-f", "v+a", "--merge-output-format", "mp4", "--ffmpeg-location",
        str(Path(workers.FFMPEG).parent), "-o", str(tmp_path / "cut.%(ext)s"),
        "--download-sections", "*2-5", "--downloader-args",
        "ffmpeg_i:-reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 "
        "-reconnect_delay_max 5 -reconnect_on_http_error 408,429,500,502,503,504 "
        "-rw_timeout 30000000", "--downloader-args", "ffmpeg_o:-xerror",
        "--print", "before_dl:@@CHECK@@%(duration)s\t%(vcodec)s\t%(acodec)s",
        "--print", "after_move:@@PATH@@%(filepath)s",
    ]
    try:
        result = worker._exec_ytdlp(command, "offline", False)
        assert result[0] == 0, "\n".join(result[3])
        assert worker._expected_audio is True
        assert worker._source_duration == 10
        assert result[1] == str(tmp_path / "cut.mp4")
        probe_download(worker, result[1], False)
        probe = subprocess.run(
            [workers.FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,duration",
             "-of", "json", result[1]], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
            creationflags=workers.CREATE_NO_WINDOW, timeout=30)
        tracks = json.loads(probe.stdout)["streams"]
        assert {track["codec_type"] for track in tracks} == {"video", "audio"}
        assert all(float(track["duration"]) >= 2.5 for track in tracks)
    finally:
        worker.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
