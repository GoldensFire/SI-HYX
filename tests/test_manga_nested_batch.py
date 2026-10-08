"""Scene batching preserves each nested identifier and rejects partial responses."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from gemini_api import GeminiError
from si_hyx_parts.animepack.visual_nested_batch import NestedVisualBatcher

SCHEMA = {"type": "object", "properties": {
    "accept": {"type": "boolean"},
    "candidates": {"type": "array", "items": {"type": "object",
        "properties": {"page_index": {"type": "integer"}}, "required": ["page_index"]}}},
    "required": ["accept", "candidates"]}


def test_two_titles_share_one_request_without_sharing_page_indices():
    calls = []
    class Client:
        def generate_json(self, parts, schema, temperature=0):
            calls.append((parts, schema))
            return {"jobs": [{"job_id": 1, "accept": True, "candidates": [{"page_index": 3}]},
                             {"job_id": 0, "accept": False, "candidates": []}]}
    batcher = NestedVisualBatcher(Client(), max_images=8, collect_seconds=.05)
    gate = threading.Barrier(2)
    def send(index):
        gate.wait(timeout=3)
        return batcher.check([{"type": "text", "text": f"Title {index}"},
                              {"type": "image", "data": "image"}], SCHEMA)
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(send, range(2)))
    assert len(calls) == 1
    assert sorted(a["accept"] for a in answers) == [False, True]
    assert next(a for a in answers if a["accept"])["candidates"] == [{"page_index": 3}]
    assert "jobs" in calls[0][1]["properties"]


@pytest.mark.parametrize("rows", [[], [{"job_id": 0, "accept": True, "candidates": []}] * 2,
    [{"job_id": 0, "accept": True, "candidates": []},
     {"job_id": 1, "accept": True, "candidates": [{"page_index": "wrong"}]}]])
def test_missing_duplicate_or_malformed_nested_answers_are_rejected(rows):
    from types import SimpleNamespace
    batch = [SimpleNamespace(schema=SCHEMA), SimpleNamespace(schema=SCHEMA)]
    with pytest.raises(GeminiError):
        NestedVisualBatcher(object()).batch_verdicts({"jobs": rows}, batch)
