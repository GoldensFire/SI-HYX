# -*- coding: utf-8 -*-
"""Тесты клиента Gemini (gemini_api.py).

Сеть в тестовом наборе запрещена целиком (см. conftest), поэтому клиент всегда
получает FakeSession. Проверяем ровно то, из-за чего он вообще написан руками:
разбор нового формата ответа, троттлинг под бесплатный тариф и поведение на
429/ошибках ключа.
"""
import json
import time

import pytest

import gemini_api
from gemini_api import (GeminiAuthError, GeminiClient, GeminiError,
                        GeminiQuotaError)

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"]}


def _ok_body(payload) -> dict:
    """Ответ Interactions API с готовым JSON внутри."""
    return {"status": "completed",
            "steps": [{"type": "model_output",
                       "content": [{"type": "text",
                                    "text": json.dumps(payload, ensure_ascii=False)}]}],
            "usage": {"total_tokens": 10}}


def _client(session, **kw):
    kw.setdefault("rpm", 6000)          # троттлинг проверяем отдельным тестом
    kw.setdefault("max_retries", 3)
    return GeminiClient("test-key", session=session, **kw)


def _catch_sleep(client, monkeypatch) -> list:
    """Перехватывает паузы клиента. Возвращает только заметные (от секунды):
    доли секунды — это троттлинг под RPM, у него свой тест."""
    seen: list = []

    def fake_sleep(sec):
        if sec >= 1:
            seen.append(sec)

    monkeypatch.setattr(client, "_sleep", fake_sleep)
    return seen


# ── модели ───────────────────────────────────────────────────────────────────
def test_model_list_is_two_useful_choices():
    """Только рабочая лошадка и «подумать получше». Промежуточные версии не
    предлагаем: каждая строго уступает одной из этих двух."""
    assert gemini_api.MODELS == ("gemini-3.5-flash-lite", "gemini-3.6-flash")
    assert gemini_api.DEFAULT_MODEL == "gemini-3.5-flash-lite"


def test_rpm_follows_the_model():
    """У Flash потолок бесплатного тарифа вдвое ниже, чем у Flash-Lite: общий
    интервал загонял бы её в 429 на каждой пачке."""
    lite = GeminiClient("k", model="gemini-3.5-flash-lite")
    flash = GeminiClient("k", model="gemini-3.6-flash")
    assert flash._interval > lite._interval
    assert GeminiClient("k", model="gemini-3.5-flash-lite", rpm=60)._interval == 1.0


# ── разбор ответа ────────────────────────────────────────────────────────────
def test_parses_interactions_response(fake_session, fake_response):
    s = fake_session([("interactions",
                       fake_response(200, json_data=_ok_body({"ok": True})))])
    assert _client(s).generate_json("привет", SCHEMA) == {"ok": True}


def test_parses_legacy_generate_content_shape(fake_session, fake_response):
    """Старая форма (candidates → parts) тоже должна читаться: поля у API
    переезжают, а падать из-за этого клиент не должен."""
    legacy = {"candidates": [{"content": {"parts": [{"text": '{"ok": false}'}]}}]}
    s = fake_session([("interactions", fake_response(200, json_data=legacy))])
    assert _client(s).generate_json("привет", SCHEMA) == {"ok": False}


def test_strips_markdown_fence(fake_session, fake_response):
    """Модель изредка заворачивает JSON в ```json — ограду снимаем."""
    body = _ok_body({"ok": True})
    body["steps"][0]["content"][0]["text"] = '```json\n{"ok": true}\n```'
    s = fake_session([("interactions", fake_response(200, json_data=body))])
    assert _client(s).generate_json("привет", SCHEMA) == {"ok": True}


def test_non_json_answer_raises(fake_session, fake_response):
    body = _ok_body({})
    body["steps"][0]["content"][0]["text"] = "не могу помочь"
    s = fake_session([("interactions", fake_response(200, json_data=body))])
    with pytest.raises(GeminiError):
        _client(s).generate_json("привет", SCHEMA)


def test_request_shape(fake_session, fake_response):
    """Ключ уходит заголовком (не в URL — он попал бы в логи), схема — в
    response_format, размышления прижаты."""
    s = fake_session([("interactions",
                       fake_response(200, json_data=_ok_body({"ok": True})))])
    _client(s).generate_json("вопрос", SCHEMA)
    _method, url, kw = s.calls[0]
    assert url == gemini_api.INTERACTIONS_URL
    assert kw["headers"]["x-goog-api-key"] == "test-key"
    body = kw["json"]
    assert body["model"] == gemini_api.DEFAULT_MODEL
    assert body["input"] == "вопрос"
    assert body["response_format"]["schema"] == SCHEMA
    assert body["response_format"]["mime_type"] == "application/json"
    assert body["generation_config"]["temperature"] == 0.0
    assert body["generation_config"]["thinking_level"] == gemini_api.THINKING_LEVEL


# ── ключ и квота ─────────────────────────────────────────────────────────────
def test_no_key_never_touches_network(fake_session):
    s = fake_session([])
    with pytest.raises(GeminiAuthError):
        GeminiClient("", session=s).generate_json("привет", SCHEMA)
    assert s.calls == []


@pytest.mark.parametrize("code", [400, 401, 403])
def test_bad_key_is_not_retried(fake_session, fake_response, code):
    """Ошибка ключа/модели ретраями не лечится — незачем жечь минуты."""
    err = json.dumps({"error": {"code": code, "message": "API key not valid",
                                "status": "INVALID_ARGUMENT"}})
    s = fake_session([("interactions", fake_response(code, text=err))])
    with pytest.raises(GeminiAuthError) as e:
        _client(s).generate_json("привет", SCHEMA)
    assert "API key not valid" in str(e.value)
    assert len(s.calls) == 1


def test_quota_exhausted_raises_quota_error(fake_session, fake_response,
                                            monkeypatch):
    err = json.dumps({"error": {"code": 429, "message": "Quota exceeded",
                                "status": "RESOURCE_EXHAUSTED"}})
    s = fake_session([("interactions", fake_response(429, text=err))])
    c = _client(s, max_retries=2)
    monkeypatch.setattr(c, "_sleep", lambda _s: None)
    with pytest.raises(GeminiQuotaError):
        c.generate_json("привет", SCHEMA)
    assert len(s.calls) == 2


def test_429_then_success(fake_session, fake_response, monkeypatch):
    """Разовый 429 переживаем: ждём столько, сколько назвал сервер."""
    err = json.dumps({"error": {"code": 429, "message": "rate", "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo",
         "retryDelay": "7s"}]}})
    seq = [fake_response(429, text=err),
           fake_response(200, json_data=_ok_body({"ok": True}))]
    s = fake_session([("interactions", lambda url, **kw: seq.pop(0))])
    c = _client(s)
    waited = _catch_sleep(c, monkeypatch)
    assert c.generate_json("привет", SCHEMA) == {"ok": True}
    assert waited == [7.0]


def test_retry_after_header_wins(fake_session, fake_response, monkeypatch):
    seq = [fake_response(429, text="{}", headers={"Retry-After": "12"}),
           fake_response(200, json_data=_ok_body({"ok": True}))]
    s = fake_session([("interactions", lambda url, **kw: seq.pop(0))])
    c = _client(s)
    waited = _catch_sleep(c, monkeypatch)
    c.generate_json("привет", SCHEMA)
    assert waited == [12.0]


def test_server_error_is_retried(fake_session, fake_response, monkeypatch):
    seq = [fake_response(503, text="oops"),
           fake_response(200, json_data=_ok_body({"ok": True}))]
    s = fake_session([("interactions", lambda url, **kw: seq.pop(0))])
    c = _client(s)
    monkeypatch.setattr(c, "_sleep", lambda _s: None)
    assert c.generate_json("привет", SCHEMA) == {"ok": True}
    assert len(s.calls) == 2


# ── троттлинг и отмена ───────────────────────────────────────────────────────
def test_throttle_spaces_requests(fake_session, fake_response, monkeypatch):
    """Между запросами выдерживается 60/RPM — бесплатный тариф считает минуты.

    Часы подменены: настоящая пауза двигает время сама, и без этого второй
    запрос «ждал» бы уже 10 секунд вместо пяти (счётчик слотов ушёл вперёд, а
    время нет)."""
    s = fake_session([("interactions",
                       fake_response(200, json_data=_ok_body({"ok": True})))])
    c = _client(s, rpm=12)              # интервал 5 с
    now = [1000.0]
    waited = []
    monkeypatch.setattr(gemini_api.time, "monotonic", lambda: now[0])

    def fake_sleep(sec):
        waited.append(round(sec))
        now[0] += sec

    monkeypatch.setattr(c, "_sleep", fake_sleep)
    for _ in range(3):
        c.generate_json("привет", SCHEMA)
    assert waited == [5, 5]             # первый запрос уходит сразу
    assert c.requests_made == 3


def test_stop_aborts_before_request(fake_session, fake_response):
    s = fake_session([("interactions",
                       fake_response(200, json_data=_ok_body({"ok": True})))])
    c = GeminiClient("k", session=s, stopped=lambda: True)
    with pytest.raises(GeminiError):
        c.generate_json("привет", SCHEMA)
    assert s.calls == []


def test_sleep_is_interruptible():
    """«Стоп» не должен ждать минутного ретрая."""
    c = GeminiClient("k", stopped=lambda: True)
    started = time.monotonic()
    c._sleep(30)
    assert time.monotonic() - started < 1.0
