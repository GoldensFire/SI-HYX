# -*- coding: utf-8 -*-
"""English prompts and serialized art requests without persistent reuse."""
from concurrent.futures import ThreadPoolExecutor
import io
import time

from PIL import Image
import pytest

from animepack_art import AnimeArtService, art_prompt
from cloudflare_art_api import CloudflareArtError, CloudflareArtUnavailable


class Client:
    def __init__(self):
        self.calls = 0
        self.active = 0
        self.max_active = 0
        buf = io.BytesIO()
        Image.new("RGB", (128, 128), "blue").save(buf, "PNG")
        self.data = buf.getvalue()

    def check_cancelled(self):
        pass

    def generate(self, *args, **kwargs):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        time.sleep(0.002)
        self.active -= 1
        return self.data, ".png"


def test_prompt_uses_title_and_neutral_palette():
    prompt = art_prompt({"english": "Death Note", "name": "Desu Noto"})
    assert "Death Note" in prompt and "Desu Noto" not in prompt
    assert "neutral daylight" in prompt and "balanced lighting" in prompt
    assert "Text-free" in prompt and "Ghibli" not in prompt
    with pytest.raises(CloudflareArtError):
        art_prompt({"name": "Naruto"})
    assert len(art_prompt({"english": "A" * 5000})) <= 2048


def test_repeated_concurrent_titles_generate_fresh_serialized_images():
    client = Client()
    service = AnimeArtService(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(service.generate, [{"english": "Naruto"}] * 8))
    assert client.calls == 8 and client.max_active == 1
    assert all(ext == ".png" and data for data, ext in results)


def test_quota_failure_stops_queued_requests():
    class Limited(Client):
        def generate(self, *args, **kwargs):
            self.calls += 1
            raise CloudflareArtUnavailable("quota")

    client = Limited()
    service = AnimeArtService(client)
    for title in ("Naruto", "Death Note", "Bleach"):
        with pytest.raises(CloudflareArtUnavailable):
            service.generate({"english": title})
    assert client.calls == 1


def test_repeated_bad_responses_do_not_burn_the_whole_quota():
    class Broken(Client):
        def generate(self, *args, **kwargs):
            self.calls += 1
            raise CloudflareArtError("bad image")

    client = Broken()
    service = AnimeArtService(client)
    for i in range(5):
        with pytest.raises(CloudflareArtError):
            service.generate({"english": str(i)})
    assert client.calls == 3
