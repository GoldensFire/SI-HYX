"""Serve a restricted manifest over loopback so FFmpeg preserves HTTP options."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from uuid import uuid4


class ManifestHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != self.server.manifest_path:
            self.send_error(404)
            return
        body = self.server.manifest_body
        self.send_response(200)
        self.send_header("Content-Type", self.server.manifest_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


@contextmanager
def serve_manifest(text, kind):
    """Only this generated manifest is exposed; segments keep their remote URLs."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), ManifestHandler)
    server.daemon_threads = True
    suffix = ".mpd" if kind == "dash" else ".m3u8"
    server.manifest_path = "/" + uuid4().hex + suffix
    server.manifest_body = text.encode("utf-8")
    server.manifest_type = "application/dash+xml" if kind == "dash" else "application/vnd.apple.mpegurl"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True, name="Episode manifest")
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}" + server.manifest_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
