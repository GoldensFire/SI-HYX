"""Regressions for network bounds, cache poisoning and diagnostic routing."""
import asyncio
import gc
import json
from types import SimpleNamespace
import weakref

import pytest
import animepack as api
import animepack_api
from si_hyx_parts.animepack import db_json, episode_suitability, frame_visual_check, media_transfer
from si_hyx_parts.animepack.episode_collect import collect


def test_anizip_recovers_after_transient_empty_response():
    source = animepack_api.AniZipApi(SimpleNamespace())
    calls = []
    def mappings(mal):
        calls.append(mal)
        if len(calls) == 1:
            raise TimeoutError("offline")
        return {"episodes": {"1": {"image": "https://cdn/1.jpg"}}}
    source._mappings = mappings
    assert source.frames(1) == []
    assert source.frames(1) == ["https://cdn/1.jpg"]
    assert calls == [1, 1]


def test_db_load_does_not_retain_unrelated_cycles(tmp_path):
    class Cycle:
        pass
    value = Cycle()
    value.self = value
    ref = weakref.ref(value)
    path = tmp_path / "db.json"
    path.write_text('{"anime": {}}', encoding="utf-8")
    before = gc.get_freeze_count()
    assert db_json.load_file(str(path)) == {"anime": {}}
    assert gc.get_freeze_count() == before
    del value
    gc.collect()
    assert ref() is None


def test_different_episodes_and_qualities_have_separate_verdicts(tmp_path):
    memory = episode_suitability.Suitability(str(tmp_path / "s.json"))
    low = dict(provider="anibd", type="hls", url="https://cdn/show/e1/720.m3u8?token=x")
    memory.mark(1, low, "low")
    for url in ("https://cdn/show/e2/720.m3u8", "https://cdn/show/e1/1080.m3u8"):
        assert memory.verdict(1, {**low, "url": url}) == ""


def test_new_memory_update_during_write_remains_dirty(tmp_path, monkeypatch):
    memory = episode_suitability.Suitability(str(tmp_path / "s.json"))
    memory.mark(1, {"url": "https://cdn/1"}, "low")
    original = episode_suitability.os.replace
    def replace(source, target):
        with memory._lock:
            memory.data["titles"]["2"] = 42
            memory._revision += 1
            memory._dirty = True
        original(source, target)
    monkeypatch.setattr(episode_suitability.os, "replace", replace)
    memory.mark(3, {"url": "https://cdn/3"}, "ok")
    memory.save()
    assert memory._dirty
    monkeypatch.setattr(episode_suitability.os, "replace", original)
    memory.save()
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["titles"]["2"] == 42


def test_frame_download_tries_another_url_without_gemini():
    urls = iter(["https://cdn/dead.jpg", "https://cdn/good.jpg"])
    calls = []
    def download(url, category):
        calls.append(url)
        if len(calls) == 1:
            raise TimeoutError("dead CDN")
        return b"picture"
    generator = SimpleNamespace(s=api.PackSettings(), stopped=lambda: False,
        _pick_frame_url=lambda cand: next(urls, ""), _cached_bytes=download,
        _url_ext=lambda url: ".jpg", log=lambda msg: None, _log_rare=lambda *a: None)
    candidate = api.SongCandidate({}, {"name": "Title"}, kind=api.FRAME_KIND)
    assert frame_visual_check.select(generator, candidate) == (b"picture", ".jpg")
    assert len(calls) == 2


def test_partial_catalogue_survives_slow_sibling():
    async def run():
        async def ready():
            return {1: "ready"}
        async def stuck():
            await asyncio.sleep(30)
        scope = SimpleNamespace(deadline=media_transfer.time.monotonic() + 60)
        results = await collect([ready(), stuck()], scope, 1.05)
        assert results[0] == {1: "ready"}
        assert isinstance(results[1], TimeoutError)
    asyncio.run(run())


def test_streaming_download_observes_stop_and_closes_response():
    stopped, closed = [], []
    def chunks(size):
        yield b"first"
        stopped.append(True)
        yield b"second"
    response = SimpleNamespace(headers={}, raise_for_status=lambda: None,
        iter_content=chunks, close=lambda: closed.append(True))
    generator = SimpleNamespace(session=SimpleNamespace(get=lambda *a, **k: response),
        stopped=lambda: bool(stopped), _download_retry_pause=lambda _: None)
    with pytest.raises(api.AnimePackError, match="Остановлено"):
        media_transfer.download(generator, "https://cdn/x", (10, 90))
    assert closed == [True]


def test_media_size_limit_applies_before_reading(monkeypatch):
    monkeypatch.setattr(media_transfer, "MAX_BYTES", 3)
    response = SimpleNamespace(headers={"Content-Length": "4"})
    generator = SimpleNamespace(stopped=lambda: False)
    with pytest.raises(api.AnimePackError, match="размер"):
        media_transfer.read(generator, response, media_transfer.time.monotonic() + 5, None)


def test_failed_new_recovery_keeps_previous_attempt(tmp_path, monkeypatch):
    from si_hyx_parts.animepack import assembly_recovery
    from test_assembly_recovery import _gen, _songs
    generator = _gen(tmp_path, monkeypatch)
    generator.prepare_dirs()
    previous = assembly_recovery.save(generator, _songs(), "first")
    generator.prepare_dirs()
    monkeypatch.setattr(assembly_recovery.shutil, "move",
                        lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    assert assembly_recovery.save(generator, _songs(), "second") == ""
    assert assembly_recovery.latest()["path"] == previous
    assert assembly_recovery.load(previous)[0]
    generator.cleanup()


def test_recovery_cannot_delete_outside_its_store(tmp_path, monkeypatch):
    from si_hyx_parts.animepack import assembly_recovery
    monkeypatch.setattr(assembly_recovery, "recovery_dir", lambda: str(tmp_path / "recovery"))
    protected = tmp_path / "protected"
    protected.mkdir()
    with pytest.raises(ValueError, match="вне хранилища"):
        assembly_recovery.discard(str(protected))
    assert protected.is_dir()


def test_enriched_level_is_checked_before_committing_repeat_keys(monkeypatch):
    from collections import Counter
    from concurrent.futures import Future
    from si_hyx_parts.animepack import early_repeat
    from si_hyx_parts.animepack.selection_results import collect_finished
    from test_animepack_extras import _gen
    generator = _gen(api.PackSettings(level_avg=2))
    generator._exact_keys = {"old question"}
    generator._manga_mix = SimpleNamespace(release=lambda cand: None)
    generator._level_fits = lambda *args: False
    benched = []
    generator._bench_candidate = benched.append
    monkeypatch.setattr(early_repeat, "accept",
        lambda *args: (_ for _ in ()).throw(AssertionError("too early")))
    candidate = SimpleNamespace(kind=api.FRAME_KIND, level=10, music_slot=-1,
                                music_effect="original")
    future = Future()
    future.set_result(True)
    collect_finished(generator, [future], {future: candidate}, [], Counter(),
                     Counter({api.FRAME_KIND: 1}), [2, 2, 2],
                     {api.FRAME_KIND: 4}, None, [], 4)
    assert benched == [candidate]
    assert candidate._ready_media == (api.FRAME_KIND, "original")


def test_ready_deferred_question_does_not_download_again():
    generator = SimpleNamespace(stopped=lambda: False)
    candidate = SimpleNamespace(kind=api.FRAME_KIND, music_effect="original",
                                _ready_media=(api.FRAME_KIND, "original"))
    assert api.AnimePackGenerator._fetch_media(generator, candidate)


def test_failed_host_is_paused_without_poisoning_other_hosts():
    import requests
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        raise requests.ConnectTimeout("offline")
    generator = SimpleNamespace(session=SimpleNamespace(get=get), stopped=lambda: False,
                                _download_retry_pause=lambda _: None)
    with pytest.raises(api.AnimePackError):
        media_transfer.download(generator, "https://dead/first.jpg", (10, 90))
    first = len(calls)
    with pytest.raises(api.AnimePackError, match="на паузе"):
        media_transfer.download(generator, "https://dead/second.jpg", (10, 90))
    assert len(calls) == first
    media_transfer.host_state(generator, "https://other/ok.jpg")
