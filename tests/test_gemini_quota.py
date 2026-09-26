# -*- coding: utf-8 -*-
"""Пределы бесплатного тарифа Gemini: что считается, что помнится, что не
повторяется.

Всё здесь — из разбора живого прогона: тринадцать вопросов по сюжету стоили
полторы сотни запросов. Считались отклонённые сервером 429, четырежды
повторялся запрос, ответа которого мы не дождались (а Google его уже
засчитал), и каждый следующий прогон заново выяснял, что модель кончилась.
"""
import json

import pytest
import requests

import gemini_api
import gemini_quota
import gemini_usage
from gemini_api import GeminiClient, GeminiError, GeminiQuotaError
from gemini_quota import QuotaBoard

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"]}
QUOTA_BODY = json.dumps({"error": {
    "code": 429, "status": "RESOURCE_EXHAUSTED",
    "message": "Quota exceeded for quota metric 'requests per day', limit: 20"}})
RATE_BODY = json.dumps({"error": {"code": 429, "message": "rate limit"}})


def _ok_body(payload=None):
    return {"steps": [{"type": "model_output", "content": [
        {"type": "text", "text": json.dumps(payload or {"ok": True})}]}]}


def _client(session, monkeypatch=None, **kw):
    kw.setdefault("rpm", 6000)
    kw.setdefault("max_retries", 3)
    client = GeminiClient("test-key", session=session, **kw)
    if monkeypatch is not None:
        monkeypatch.setattr(client, "_sleep", lambda _seconds: None)
    return client


def _raise(error):
    def route(_url, **_kw):
        raise error
    return route


def _by_model(fake_session, fake_response, dead, body=QUOTA_BODY):
    """Сессия, которая отвечает отказом только по названным моделям."""
    def route(_url, **kw):
        model = str((kw.get("json") or {}).get("model") or "")
        if model in dead:
            return fake_response(429, text=body)
        return fake_response(json_data=_ok_body())

    return fake_session([("interactions", route)])


# ── разбор ответа сервера ────────────────────────────────────────────────────
def test_quota_is_told_apart_from_a_rate_limit():
    assert gemini_quota.is_quota("RESOURCE_EXHAUSTED")
    assert gemini_quota.is_quota("Quota exceeded")
    assert not gemini_quota.is_quota("rate limit")


def test_only_a_daily_limit_is_taken_as_daily():
    """Под тем же 429 прячется и минутный предел — на сутки его писать нельзя."""
    assert gemini_quota.is_daily("quota metric 'requests per day', limit: 20")
    assert not gemini_quota.is_daily("GenerateRequestsPerMinute, limit: 5")
    assert gemini_quota.daily_cap("requests per day, limit: 20") == 20
    assert gemini_quota.daily_cap("requests per minute, limit: 5") == 0


# ── что идёт в суточный счёт ─────────────────────────────────────────────────
def test_rejected_requests_are_not_counted(fake_session, fake_response,
                                           monkeypatch):
    """429 и 5xx сервер не обслужил — в суточный лимит они не идут."""
    replies = iter([fake_response(429, text=RATE_BODY),
                    fake_response(503, text="oops"),
                    fake_response(json_data=_ok_body())])
    session = fake_session([("interactions", lambda _u, **_kw: next(replies))])
    client = _client(session, monkeypatch, max_retries=4)
    assert client.generate_json("привет", SCHEMA) == {"ok": True}
    assert len(session.calls) == 3
    assert client.requests_made == 1            # столько видит Google
    assert sum(client.spent.values()) == 3      # а столько мы отправили
    assert gemini_usage.requests_today("test-key", gemini_api.DEFAULT_MODEL) == 1


def test_read_timeout_is_counted_and_never_repeated(fake_session):
    """Сервер запрос принял: повтор — это плата второй раз за тот же вопрос."""
    session = fake_session([("interactions",
                             _raise(requests.exceptions.ReadTimeout("slow")))])
    client = _client(session)
    with pytest.raises(GeminiError) as error:
        client.generate_json("привет", SCHEMA)
    assert "не ответил" in str(error.value)
    assert len(session.calls) == 1
    assert client.requests_made == 1
    assert gemini_usage.requests_today("test-key", gemini_api.DEFAULT_MODEL) == 1


def test_connect_timeout_is_retried_and_costs_nothing(fake_session,
                                                      monkeypatch):
    """До сервера не дошло ничего — вот это повторять и можно."""
    session = fake_session([("interactions",
                             _raise(requests.exceptions.ConnectTimeout("no"))) ])
    client = _client(session, monkeypatch, max_retries=3)
    with pytest.raises(GeminiError):
        client.generate_json("привет", SCHEMA)
    assert len(session.calls) == 3
    assert client.requests_made == 0
    assert gemini_usage.requests_today("test-key", gemini_api.DEFAULT_MODEL) == 0


def test_read_timeout_waits_longer_than_it_connects():
    client = GeminiClient("k")
    assert client.timeout == gemini_api.READ_TIMEOUT
    assert gemini_api.READ_TIMEOUT > gemini_api.CONNECT_TIMEOUT


# ── память об исчерпанной модели ─────────────────────────────────────────────
def test_exhausted_model_is_remembered_until_tomorrow(fake_session,
                                                      fake_response, monkeypatch):
    """Следующий прогон не должен выяснять то же самое десятком 429."""
    session = _by_model(fake_session, fake_response, {"gemini-3.8-flash"})
    first = _client(session, monkeypatch, model="gemini-3.8-flash")
    assert first.generate_json("привет", SCHEMA) == {"ok": True}
    assert gemini_usage.exhausted_today("test-key", "gemini-3.8-flash")
    assert gemini_usage.daily_cap("test-key", "gemini-3.8-flash") == 20

    # Новый клиент с новой доской — и всё равно ни одного запроса к 3.8.
    fresh = _by_model(fake_session, fake_response, set())
    client = _client(fresh, monkeypatch, model="gemini-3.8-flash")
    assert client.generate_json("привет", SCHEMA) == {"ok": True}
    assert [call[2]["json"]["model"] for call in fresh.calls] == ["gemini-3.7-flash"]


def test_a_minute_limit_does_not_bury_the_model_for_a_day(fake_session,
                                                          fake_response,
                                                          monkeypatch):
    minute = json.dumps({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                   "message": "Quota exceeded for requests "
                                              "per minute, limit: 5"}})
    session = fake_session([("interactions", fake_response(429, text=minute))])
    client = _client(session, monkeypatch, model="gemini-3.8-flash")
    with pytest.raises(GeminiQuotaError):
        client.generate_json("привет", SCHEMA)
    # Метка мягкая: через час она сама снимется, суточного потолка мы не узнали.
    assert gemini_usage.daily_cap("test-key", "gemini-3.8-flash") == 0
    monkeypatch.setattr(gemini_usage.time, "time",
                        lambda: 9e9)                 # «прошёл час»
    assert not gemini_usage.exhausted_today("test-key", "gemini-3.8-flash")


def test_clients_of_one_key_share_the_board(fake_session, fake_response,
                                            monkeypatch):
    """Сюжет и загадки по названию ходят по одному ключу — и квота у них одна."""
    board = QuotaBoard("test-key")
    plot_session = _by_model(fake_session, fake_response, {"gemini-3.8-flash"})
    plot = _client(plot_session, monkeypatch, model="gemini-3.8-flash",
                   board=board)
    plot.generate_json("привет", SCHEMA)
    # Второй клиент про мёртвую 3.8 ещё не знал — раньше он слал туда своё.
    titles_session = _by_model(fake_session, fake_response, set())
    titles = _client(titles_session, monkeypatch, model="gemini-3.8-flash",
                     board=board)
    titles.generate_json("привет", SCHEMA)
    assert all(call[2]["json"]["model"] != "gemini-3.8-flash"
               for call in titles_session.calls)


def test_slots_are_shared_so_two_clients_keep_one_rpm(monkeypatch):
    board = QuotaBoard("test-key")
    first = board.reserve("gemini-3.8-flash", 12.0)
    second = board.reserve("gemini-3.8-flash", 12.0)
    assert first <= 0 < second         # второй клиент встаёт в ту же очередь


def test_daily_limit_from_settings_stops_before_the_first_429(
        fake_session, fake_response, monkeypatch):
    """Потолок, выставленный на вкладке, проверяется ДО отправки."""
    board = QuotaBoard("test-key", {"gemini-3.8-flash": 1})
    session = fake_session([("interactions", fake_response(json_data=_ok_body()))])
    client = _client(session, monkeypatch, model="gemini-3.8-flash", board=board)
    client.generate_json("первый", SCHEMA)
    client.generate_json("второй", SCHEMA)
    models = [call[2]["json"]["model"] for call in session.calls]
    assert models == ["gemini-3.8-flash", "gemini-3.7-flash"]
