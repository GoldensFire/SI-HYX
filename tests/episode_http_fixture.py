"""Local, header-protected MP4/HLS/DASH server for actual FFmpeg checks."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import re
import subprocess
import shutil
import threading

import animepack as api


class RangeHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if (self.headers.get("User-Agent") != "SI-HYX-test"
                or self.headers.get("Referer") != self.server.base + "/watch"
                or self.headers.get("Origin") != self.server.base):
            self.server.rejected += 1
            self.send_error(403)
            return
        path = self.translate_path(self.path)
        try:
            with open(path, "rb") as stream:
                stream.seek(0, 2)
                size = stream.tell()
                match = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
                start = int(match.group(1)) if match else 0
                end = min(size - 1, int(match.group(2))) if match and match.group(2) else size - 1
                self.send_response(206 if match else 200)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                if match:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                stream.seek(start)
                data = stream.read(end - start + 1)
                self.server.requests.append((self.path, start, len(data)))
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            self.send_error(404)


def fixtures(folder):
    source = folder / "episode.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=128x96:rate=5", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", "120", "-c:v", "libx264", "-preset", "ultrafast", "-g", "20", "-c:a", "aac",
         "-metadata:s:a:0", "language=jpn", "-movflags", "+faststart", str(source)])
    run(["-i", str(source), "-c", "copy", "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
         "-hls_segment_filename", str(folder / "segment%03d.ts"), str(folder / "episode.m3u8")])
    run(["-i", str(source), "-c", "copy", "-f", "dash", "-seg_duration", "4", "episode.mpd"], cwd=folder)
    for path in folder.glob("segment*.ts"):
        shutil.copyfile(path, path.with_suffix(".jpg"))
    text = (folder / "episode.m3u8").read_text(encoding="utf-8")
    (folder / "opaque.m3u8").write_text(text.replace(".ts", ".jpg"), encoding="utf-8")


def run(args, cwd=None):
    return subprocess.run([api.FFMPEG, "-y", "-loglevel", "error"] + args,
                          capture_output=True, timeout=60, check=True, cwd=cwd)


def serve(folder):
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(RangeHandler, directory=str(folder)))
    server.base = f"http://127.0.0.1:{server.server_port}"
    server.requests = []
    server.rejected = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
