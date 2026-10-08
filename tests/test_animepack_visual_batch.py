# -*- coding: utf-8 -*-
"""Пачки Gemini экономят запросы без смешивания вердиктов и зависаний."""
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from gemini_api import GeminiError, GeminiQuotaError
from si_hyx_parts.animepack import visual_batch as batch
from si_hyx_parts.animepack.manga_visual_check import SCHEMA as MANGA_SCHEMA
from si_hyx_parts.animepack.pixiv_visual_check import SCHEMA as PIXIV_SCHEMA
from si_hyx_parts.animepack.frame_visual_check import SCHEMA as FRAME_SCHEMA


def _parts(index):
    return [{"type": "text", "text": f"expected title {index}"},
            {"type": "image", "mime_type": "image/png", "data": str(index)}]


def _verdict(index):
    return {"id": index, "accept": index % 2 == 0,
            "has_characters": index % 2 == 0,
            "has_title_text": index % 2 != 0, "mixed_anime": False,
            "very_poor_drawing": False, "matches_expected_anime": True,
            "identified_source": "", "visible_text": "",
            "reason": f"picture {index}"}


class _Client:
    model = "gemini-test"
    thinking = "minimal"

    def __init__(self, response=None, board=None):
        self.calls = []
        self.response = response
        self.board = board or object()

    def generate_json(self, parts, schema, temperature=0):
        self.calls.append((parts, schema))
        if isinstance(self.response, Exception):
            raise self.response
        if self.response is not None:
            return self.response
        images = [p for p in parts if p["type"] == "image"]
        if "results" not in schema["properties"]:
            return _verdict(int(images[0]["data"]))
        return {"results": [dict(_verdict(int(p["data"])), id=index)
                            for index, p in reversed(list(enumerate(images)))]}


def test_multi_image_jobs_respect_total_image_budget():
    client = _Client({"results": [_verdict(0), _verdict(1)]})
    batcher = batch.VisualCheckBatcher(client, max_images=4, collect_seconds=1)
    gate = threading.Barrier(4)
    def check(index):
        gate.wait(timeout=3)
        return batcher.check(_parts(index) + _parts(index), FRAME_SCHEMA)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [future.result(timeout=5) for future in [pool.submit(check, i) for i in range(4)]]
    assert len(rows) == 4 and len(client.calls) == 2
    assert all(sum(part.get("type") == "image" for part in parts) == 4 for parts, _ in client.calls)


def test_nested_scene_schemas_never_use_flat_verdict_batch_protocol():
    client = _Client({"scenes": []})
    schema = {"type": "object", "properties": {"scenes": {"type": "array", "items": {"type": "integer"}}},
              "required": ["scenes"]}
    batcher = batch.VisualCheckBatcher(client, max_images=2, collect_seconds=0.01)
    rows = _together(batcher, count=2, schema=schema)
    assert rows == [{"scenes": []}, {"scenes": []}] and len(client.calls) == 2


def _together(batcher, count=4, schema=PIXIV_SCHEMA):
    gate = threading.Barrier(count)

    def check(index):
        gate.wait(timeout=3)
        return batcher.check(_parts(index), schema)

    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(check, index) for index in range(count)]
        return [future.result(timeout=5) for future in futures]


def test_four_images_use_one_request_and_reversed_results_go_to_the_right_jobs():
    client = _Client()
    batcher = batch.VisualCheckBatcher(client, collect_seconds=1)
    verdicts = _together(batcher)
    assert len(client.calls) == 1
    assert [row["reason"] for row in verdicts] == [f"picture {i}" for i in range(4)]
    assert [row["accept"] for row in verdicts] == [True, False, True, False]
    parts, _schema = client.calls[0]
    assert len([part for part in parts if part["type"] == "image"]) == 4
    assert all(f"expected title {i}" in str(parts) for i in range(4))


def test_single_or_partial_batch_finishes_without_waiting_for_more_images():
    client = _Client()
    batcher = batch.VisualCheckBatcher(client, collect_seconds=0.01)
    assert batcher.check(_parts(0), MANGA_SCHEMA)["accept"] is True
    assert len(_together(batcher, count=2)) == 2
    assert len(client.calls) == 2


def test_frame_title_and_character_results_share_one_request_and_keep_their_ids():
    client = _Client()
    batcher = batch.VisualCheckBatcher(client, collect_seconds=1)
    verdicts = _together(batcher, schema=FRAME_SCHEMA)
    assert len(client.calls) == 1
    assert [row["has_characters"] for row in verdicts] == [True, False, True, False]
    assert [row["has_title_text"] for row in verdicts] == [False, True, False, True]


def test_frames_pixiv_and_manga_can_share_the_same_model_request():
    client = _Client()
    gen = SimpleNamespace(stopped=lambda: False)
    batch.initialize(gen)
    schemas = [FRAME_SCHEMA, PIXIV_SCHEMA, MANGA_SCHEMA, FRAME_SCHEMA]
    gate = threading.Barrier(4)
    def check(index):
        gate.wait(timeout=3)
        return batch.request(gen, client, _parts(index), schemas[index])
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(check, i) for i in range(4)]
        rows = [future.result(timeout=5) for future in futures]
    assert len(client.calls) == 1
    assert [row["reason"] for row in rows] == [f"picture {i}" for i in range(4)]


@pytest.mark.parametrize("response", [
    {"results": [_verdict(0)]},
    {"results": [_verdict(0), _verdict(0)]},
    {"results": [_verdict(0), dict(_verdict(1), id=99)]},
    {"results": [_verdict(0), dict(_verdict(1), accept="false")]},
    {"results": [_verdict(0), {k: v for k, v in _verdict(1).items()
                             if k != "mixed_anime"}]},
    GeminiQuotaError("quota"),
])
def test_bad_or_failed_batch_wakes_all_waiters_without_individual_retries(response):
    client = _Client(response)
    batcher = batch.VisualCheckBatcher(client, max_images=2, collect_seconds=1)
    gate = threading.Barrier(2)

    def check(index):
        gate.wait(timeout=3)
        with pytest.raises(GeminiError):
            batcher.check(_parts(index), PIXIV_SCHEMA)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(check, i) for i in range(2)]
        for future in futures:
            future.result(timeout=5)
    assert len(client.calls) == 1


def test_cancelled_job_is_not_sent_and_cancellation_does_not_poison_next_batch():
    client = _Client()
    stopped = threading.Event()
    stopped.set()
    batcher = batch.VisualCheckBatcher(client, stopped.is_set, collect_seconds=0)
    with pytest.raises(GeminiError, match="Отменено"):
        batcher.check(_parts(0), MANGA_SCHEMA)
    assert not client.calls
    stopped.clear()
    assert batcher.check(_parts(0), MANGA_SCHEMA)["accept"] is True


def test_stop_cancels_a_waiting_job_while_another_request_is_in_flight():
    started, release, stopped = (threading.Event() for _ in range(3))

    class _BlockingClient(_Client):
        def generate_json(self, parts, schema, temperature=0):
            started.set()
            assert release.wait(timeout=3)
            return super().generate_json(parts, schema, temperature)

    client = _BlockingClient()
    batcher = batch.VisualCheckBatcher(
        client, stopped.is_set, max_images=1, collect_seconds=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(batcher.check, _parts(0), MANGA_SCHEMA)
        try:
            assert started.wait(timeout=3)
            second = pool.submit(batcher.check, _parts(1), PIXIV_SCHEMA)
            stopped.set()
            with pytest.raises(GeminiError, match="Отменено"):
                second.result(timeout=1)
        finally:
            release.set()
        assert first.result(timeout=3)["accept"] is True
    assert len(client.calls) == 1


def test_pixiv_and_manga_share_a_batch_only_when_models_match():
    board = object()
    clients = [_Client(board=board), _Client(board=board)]
    gen = SimpleNamespace(stopped=lambda: False)
    batch.initialize(gen)
    gate = threading.Barrier(4)

    def check(index):
        gate.wait(timeout=3)
        return batch.request(gen, clients[index % 2], _parts(index),
                             PIXIV_SCHEMA if index % 2 else MANGA_SCHEMA)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(check, i) for i in range(4)]
        assert len([f.result(timeout=5) for f in futures]) == 4
    assert sum(len(c.calls) for c in clients) == 1
    clients[1].model = "another-model"
    batch.request(gen, clients[1], _parts(0), MANGA_SCHEMA)
    assert len(gen._visual_batches) == 2
    assert clients[1].calls[-1][1] is MANGA_SCHEMA


def test_large_images_are_split_before_the_request_size_limit(monkeypatch):
    monkeypatch.setattr(batch, "MAX_INPUT", 32)
    client = _Client()
    batcher = batch.VisualCheckBatcher(client, collect_seconds=0.01)
    verdicts = _together(batcher)
    assert [row["reason"] for row in verdicts] == [f"picture {i}" for i in range(4)]
    assert len(client.calls) == 4


def test_oversized_input_is_rejected_without_spending_a_request(monkeypatch):
    monkeypatch.setattr(batch, "MAX_INPUT", 1)
    client = _Client()
    batcher = batch.VisualCheckBatcher(client, collect_seconds=0)
    with pytest.raises(GeminiError, match="слишком большое"):
        batcher.check(_parts(0), PIXIV_SCHEMA)
    assert not client.calls


def _unavailable():
    from gemini_api import GeminiUnavailableError
    return GeminiUnavailableError("Gemini 503: high demand")


def test_server_silent_twice_in_a_row_stops_asking_until_the_end_of_the_run():
    from gemini_api import GeminiDownError, GeminiUnavailableError
    client = _Client(response=_unavailable())
    batcher = batch.VisualCheckBatcher(client, collect_seconds=0)
    with pytest.raises(GeminiUnavailableError):
        batcher.check(_parts(0), PIXIV_SCHEMA)
    # Второй подряд — предохранитель: и этот, и все следующие получают
    # GeminiDownError, а сеть больше не трогается.
    with pytest.raises(GeminiDownError):
        batcher.check(_parts(1), PIXIV_SCHEMA)
    with pytest.raises(GeminiDownError):
        batcher.check(_parts(2), MANGA_SCHEMA)
    assert len(client.calls) == batch.DOWN_AFTER


def test_an_answer_between_silences_resets_the_count():
    from gemini_api import GeminiUnavailableError
    client = _Client(response=_unavailable())
    batcher = batch.VisualCheckBatcher(client, collect_seconds=0)
    for _ in range(3):
        client.response = _unavailable()
        with pytest.raises(GeminiUnavailableError):
            batcher.check(_parts(0), PIXIV_SCHEMA)
        client.response = None
        assert batcher.check(_parts(0), PIXIV_SCHEMA)["accept"] is True
    assert not batcher.down
