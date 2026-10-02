# -*- coding: utf-8 -*-
"""A daily rate-limit message need not contain the word 'quota'."""
import gemini_usage
from test_gemini_quota import _by_model, _client, SCHEMA


def test_daily_rate_limit_without_quota_word_switches_without_minute_retries(
        fake_session, fake_response, monkeypatch):
    model = "gemini-3.1-flash-lite"
    message = ("Rate limit exceeded for model gemini-3.1-flash-lite "
               "(limit: 500 requests per day on Free Tier). Please retry in 29s")
    session = _by_model(fake_session, fake_response, {model}, body=message)
    client = _client(session, monkeypatch, model=model)
    sleeps = []
    monkeypatch.setattr(client, "_sleep", sleeps.append)
    assert client.generate_json("Check image", SCHEMA) == {"ok": True}
    assert client.model != model and client.spent[model] == 1
    assert client.board.exhausted(model)
    assert gemini_usage.daily_cap("test-key", model) == 500
    assert sleeps == []
