# -*- coding: utf-8 -*-
"""Отпечатки ключей и сохранение суточного расхода при смене формата."""
import json

import gemini_usage as usage


def test_fingerprint_is_stable_distinct_and_key_is_not_written():
    first = usage._digest("first-secret")
    assert first.startswith("v2-") and len(first) == 35
    assert usage._digest("first-secret") == first
    assert usage._digest("second-secret") != first
    usage.record_request("first-secret", "model")
    content = usage._path().read_text(encoding="utf-8")
    assert "first-secret" not in content
    assert usage.requests_today("first-secret", "model") == 1
    assert usage.requests_today("second-secret", "model") == 0


def test_old_daily_usage_and_exhaustion_survive_fingerprint_upgrade():
    day = usage._key("secret", "model").split(":")[0]
    old = f"{day}:{'a' * 16}:model"
    data = {old: 7, "out:" + old: {"hard": True, "at": 1}}
    usage._write(data)
    assert usage.requests_today("secret", "model") == 7
    assert usage.exhausted_today("secret", "model") is True
    usage.record_request("secret", "model")
    assert usage.requests_today("secret", "model") == 8
    stored = json.loads(usage._path().read_text(encoding="utf-8"))
    assert stored[old] == 7
    assert stored[usage._key("secret", "model")] == 8
    assert usage.requests_today("secret", "other-model") == 0
