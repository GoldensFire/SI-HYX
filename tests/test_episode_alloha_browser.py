"""Exercise the packaged browser driver and bnsi bridge against a local fake player."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from si_hyx_parts.animepack.episode_ru_client import RuEpisodeClient
from si_hyx_parts.kuhi._transport import RequestScope


class Player(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        path = urlsplit(self.path).path
        if path == "/embed":
            body = (b'<html><script>if(window.top===window.self){document.write("Top-level player forbidden");}'
                    b'else{fetch("/bnsi/test", {headers: {"accepts-controls": "control", "borth": "nonce"}})}</script></html>')
            content_type = "text/html"
        elif path == "/bnsi/test":
            body = json.dumps({"hlsSource": [{"audioId": "2", "label": "Japanese", "quality": {
                "1080": base + "/master.m3u8"}}], "tracks": [
                    {"kind": "captions", "language": "rus", "src": base + "/subtitles.vtt"}]}).encode("utf-8")
            content_type = "application/json"
        elif path == "/master.m3u8":
            if self.headers.get("accepts-controls") != "control" or self.headers.get("borth"):
                self.send_error(403)
                return
            body = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION=1920x1080\nvideo.m3u8\n"
            content_type = "application/vnd.apple.mpegurl"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_real_installed_browser_extracts_bnsi_and_preserves_required_session_headers():
    pytest.importorskip("playwright")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Player)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = RuEpisodeClient()
    scope = RequestScope(lambda: False, time.monotonic() + 50)
    base = f"http://127.0.0.1:{server.server_port}"
    row = {"source": "yummyanime", "player": "alloha", "embed": base + "/embed?translation=79",
           "referer": base + "/", "release": "Субтитры"}
    try:
        from si_hyx_parts.animepack.episode_ru_alloha import open_streams
        resources = client.resources.setdefault(id(scope), [])
        async def extract():
            try:
                return await open_streams(row, scope, resources)
            except RuntimeError as error:
                if "не установлен" in str(error):
                    return "browser unavailable"
                raise
        streams = client.call(extract(), scope, 45)
        if streams == "browser unavailable":
            pytest.skip("Edge/Chrome unavailable on this test host")
        assert streams is not None, "Browser extraction timed out"
        assert len(streams) == 1
        url = streams[0]["url"]
        assert parse_qs(urlsplit(url).query)["url"] == [base + "/master.m3u8"]
        response = requests.get(url, timeout=10)
        assert response.status_code == 200
        assert "RESOLUTION=1920x1080" in response.text
        assert "127.0.0.1" in response.text and "video.m3u8" in response.text
        assert len(resources) == 1
        # Closing after expiry must still release browser and bridge.
        scope.deadline = time.monotonic() - 1
        client.finish_scope(scope)
        assert id(scope) not in client.resources
    finally:
        client.finish_scope(scope)
        client.close()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
