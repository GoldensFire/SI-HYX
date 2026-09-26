# -*- coding: utf-8 -*-
"""Persistent reuse of expensive anime-pack inputs and transforms."""
from pathlib import Path
import io
import threading

from PIL import Image
import pytest

import animepack as ap
import media_cache
from cover_service import AUDIO_FORMAT, CoverService


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    path = tmp_path / "media"
    monkeypatch.setattr(media_cache, "MEDIA_CACHE_DIR", str(path))
    monkeypatch.setattr(media_cache, "_SIZE", None)
    return path


class _Response:
    content = b"source-bytes"

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self):
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return _Response()


def _generator(tmp_path, **clients):
    cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    return ap.AnimePackGenerator(ap.PackSettings(), db_cache=cache, **clients)


def test_repeated_source_download_hits_disk_cache(cache_dir, tmp_path):
    session = _Session()
    gen = _generator(tmp_path, session=session)
    url = "https://cdn.example/song.mp3"

    assert gen._cached_bytes(url, "amq-audio") == b"source-bytes"
    assert gen._cached_bytes(url, "amq-audio") == b"source-bytes"
    assert session.calls == 1
    assert gen._media_cache_hits["исходники"] == 1


def test_disabled_disk_cache_does_not_capture_sources(cache_dir, tmp_path):
    session = _Session()
    settings = ap.PackSettings(poster_cache=False)
    gen = ap.AnimePackGenerator(
        settings, session=session,
        db_cache=ap.ShikimoriDbCache(str(tmp_path / "db.json")))
    url = "https://cdn.example/song.mp3"

    gen._cached_bytes(url, "amq-audio")
    gen._cached_bytes(url, "amq-audio")
    assert session.calls == 2
    assert media_cache.stats() == (0, 0)


def test_too_small_audio_is_not_cached(cache_dir, tmp_path):
    session = _Session()
    gen = _generator(tmp_path, session=session)
    url = "https://cdn.example/broken.mp3"

    gen._cached_bytes(url, "amq-audio", minimum=100)
    gen._cached_bytes(url, "amq-audio", minimum=100)
    assert session.calls == 2
    assert media_cache.stats() == (0, 0)


def test_reusable_avif_is_encoded_once(cache_dir, tmp_path, monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (32, 24), "blue").save(source, "PNG")
    calls = []

    def encode(_src, out, *_args, **_kwargs):
        calls.append(out)
        Path(out).write_bytes(b"cached-avif")
        return True

    monkeypatch.setattr(ap, "fit_to_limit", encode)
    gen = _generator(tmp_path)
    gen.folder = str(tmp_path / "work")
    (Path(gen.folder) / "Images").mkdir(parents=True)

    assert gen._save_reusable_image(source.getvalue(), "first", ".png")
    assert gen._save_reusable_image(source.getvalue(), "second", ".png")
    assert len(calls) == 1
    assert (Path(gen.folder) / "Images" / "second.avif").read_bytes() == b"cached-avif"
    assert gen._media_cache_hits["готовые AVIF"] == 1


def test_dense_manga_pages_get_enough_avif_search_passes(tmp_path, monkeypatch):
    calls = []

    def encode(_src, _out, _limit, **kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(ap, "fit_to_limit", encode)
    gen = _generator(tmp_path)
    gen.folder = str(tmp_path / "work")
    (Path(gen.folder) / "Images").mkdir(parents=True)
    assert gen._to_avif(b"not decoded because Pillow failure is tolerated",
                        "page.avif")
    assert calls[0]["passes"] >= 5


class _Frames:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    def frames(self, mal_id):
        self.calls += 1
        return [f"https://{self.name}.example/{mal_id}.jpg"]


def test_frame_sources_survive_generator_restart(tmp_path):
    path = tmp_path / "db.json"
    first_apis = [_Frames(name) for name in ("anilist", "kitsu", "anizip")]
    first = ap.AnimePackGenerator(
        ap.PackSettings(), anilist=first_apis[0], kitsu=first_apis[1],
        anizip=first_apis[2], db_cache=ap.ShikimoriDbCache(str(path)))
    card = {"malId": 7, "screenshots": []}
    expected = first._frame_urls(card)
    first.db_cache.save()

    second_apis = [_Frames(name) for name in ("anilist", "kitsu", "anizip")]
    second = ap.AnimePackGenerator(
        ap.PackSettings(), anilist=second_apis[0], kitsu=second_apis[1],
        anizip=second_apis[2], db_cache=ap.ShikimoriDbCache(str(path)))

    assert second._frame_urls(card) == expected
    assert sum(api.calls for api in first_apis) == 3
    assert sum(api.calls for api in second_apis) == 0
    assert second._media_cache_hits["метаданные"] == 1


def test_db_cache_save_snapshots_under_lock(tmp_path, monkeypatch):
    """Запись из рабочего потока не меняет словарь посреди сериализации."""
    path = tmp_path / "db.json"
    cache = ap.ShikimoriDbCache(str(path))
    cache.remember_memo("before", 1, {"value": 1})
    entered = threading.Event()
    release = threading.Event()
    writer_done = threading.Event()
    results = []
    from si_hyx_parts.animepack import db_json
    real_dumps = db_json.dump_parts

    def slow_dumps(value, *args, **kwargs):
        if value is cache._data:
            entered.set()
            assert release.wait(2)
        return real_dumps(value, *args, **kwargs)

    # База пишется кусками (db_json.dump_parts), а не одним json.dumps.
    monkeypatch.setattr(db_json, "dump_parts", slow_dumps)
    saver = threading.Thread(target=lambda: results.append(cache.save()))
    saver.start()
    assert entered.wait(2)

    def write_during_save():
        cache.remember_memo("during", 2, {"value": 2})
        writer_done.set()

    writer = threading.Thread(target=write_during_save)
    writer.start()
    assert not writer_done.wait(0.05)
    release.set()
    saver.join(2)
    writer.join(2)

    assert results == [True]
    assert writer_done.is_set()
    assert cache._dirty is True
    assert cache.save() is True
    fresh = ap.ShikimoriDbCache(str(path))
    assert fresh.memo("during", 2) == {"value": 2}


def test_selected_cover_audio_is_reused(cache_dir, tmp_path):
    calls = []

    def run(command, _timeout):
        calls.append(command)
        template = command[command.index("-o") + 1]
        Path(template.replace("%(ext)s", "m4a")).write_bytes(b"cover-audio")
        return 0, "", ""

    service = CoverService(run, "ffmpeg", ["yt-dlp"])
    first = service.fetch("video-1", str(tmp_path / "first"), AUDIO_FORMAT)
    second = service.fetch("video-1", str(tmp_path / "second"), AUDIO_FORMAT)

    assert Path(first).read_bytes() == Path(second).read_bytes() == b"cover-audio"
    assert len(calls) == 1


def test_media_cache_prunes_old_entries(cache_dir):
    media_cache.put("test", "old", b"old")
    media_cache.put("test", "new", b"new")
    assert media_cache.stats() == (2, 6)
    assert media_cache.prune(limit_mb=0) == 2
    assert media_cache.stats() == (0, 0)


def test_media_cache_lists_and_removes_one_file(cache_dir, tmp_path):
    path = media_cache.put("test", "one", b"payload", ".bin")
    rows = media_cache.entries()
    assert [row["path"] for row in rows] == [path]
    assert rows[0]["size"] == len(b"payload")
    assert media_cache.remove(str(tmp_path / "outside.bin")) is False
    assert media_cache.remove(path) is True
    assert media_cache.stats() == (0, 0)
