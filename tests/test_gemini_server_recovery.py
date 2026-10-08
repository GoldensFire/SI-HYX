"""Перегрузка модели не расходует весь дневной лимит повторными запросами."""
import json
from collections import Counter
from types import SimpleNamespace

import pytest
import requests

import animepack
import gemini_api
import gemini_usage
from gemini_api import GeminiClient, GeminiDownError
from gemini_quota import QuotaBoard

SCHEMA = {"type": "object"}


def _ok():
    return {"outputs": [{"type": "text", "text": '{"ok": true}'}]}


def _client(session, monkeypatch, **kwargs):
    client = GeminiClient("recovery-key", session=session, rpm=6000, **kwargs)
    monkeypatch.setattr(client, "_sleep", lambda _seconds: None)
    return client


def test_two_503s_switch_to_lite_and_never_retry_busy_flash(
        fake_session, fake_response, monkeypatch):
    def route(_url, **kwargs):
        model = kwargs["json"]["model"]
        return fake_response(503, text="high demand") if model.endswith(
            "-flash") else fake_response(json_data=_ok())

    session = fake_session([("interactions", route)])
    client = _client(session, monkeypatch, model="gemini-3.8-flash")
    assert client.generate_json("вопрос", SCHEMA) == {"ok": True}
    assert client.generate_json("следующий вопрос", SCHEMA) == {"ok": True}
    assert [call[2]["json"]["model"] for call in session.calls] == [
        "gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite"]
    assert client.response_codes == {503: 2, 200: 2}
    assert client.requests_made == 4
    assert gemini_usage.requests_today("recovery-key", "gemini-3.8-flash") == 2
    assert not gemini_usage.exhausted_today("recovery-key", "gemini-3.8-flash")


def test_unavailable_state_is_shared_but_not_saved_for_next_run(
        fake_session, fake_response, monkeypatch):
    board = QuotaBoard("recovery-key")
    board.note_server_failure("gemini-3.8-flash")
    board.note_server_failure("gemini-3.8-flash")
    session = fake_session([("interactions", fake_response(json_data=_ok()))])
    sibling = _client(session, monkeypatch, model="gemini-3.8-flash", board=board)
    sibling.generate_json("вопрос", SCHEMA)
    assert session.calls[0][2]["json"]["model"] == "gemini-3.5-flash-lite"
    fresh = _client(session, monkeypatch, model="gemini-3.8-flash")
    fresh.generate_json("новый прогон", SCHEMA)
    assert session.calls[-1][2]["json"]["model"] == "gemini-3.8-flash"


def test_success_between_errors_resets_consecutive_failure_count(
        fake_session, fake_response, monkeypatch):
    responses = iter([fake_response(503, text="busy"),
                      fake_response(json_data=_ok()),
                      fake_response(503, text="busy"),
                      fake_response(json_data=_ok())])
    session = fake_session([("interactions", lambda _u, **_k: next(responses))])
    client = _client(session, monkeypatch, model="gemini-3.8-flash")
    for _ in range(2):
        assert client.generate_json("вопрос", SCHEMA) == {"ok": True}
    assert client.model == "gemini-3.8-flash"


def test_no_sleep_after_last_failed_attempt(fake_session, fake_response,
                                            monkeypatch):
    session = fake_session([("interactions", fake_response(503, text="busy"))])
    client = _client(session, monkeypatch, max_retries=1)
    monkeypatch.setattr(client, "_throttle", lambda _model: None)
    waits = []
    monkeypatch.setattr(client, "_sleep", waits.append)
    with pytest.raises(gemini_api.GeminiUnavailableError):
        client.generate_json("вопрос", SCHEMA)
    assert waits == []


def test_known_daily_cap_is_checked_before_retry(fake_session, fake_response,
                                               monkeypatch):
    board = QuotaBoard("recovery-key", {"gemini-3.8-flash": 1})
    replies = iter([fake_response(503, text="busy"), fake_response(json_data=_ok())])
    session = fake_session([("interactions", lambda _u, **_k: next(replies))])
    client = _client(session, monkeypatch, model="gemini-3.8-flash", board=board)
    client.generate_json("вопрос", SCHEMA)
    assert [call[2]["json"]["model"] for call in session.calls] == [
        "gemini-3.8-flash", "gemini-3.7-flash"]


def test_summary_separates_failures_from_possible_quota_usage():
    lines = []
    client = SimpleNamespace(spent=Counter({"model": 5}), requests_made=4,
                             response_codes=Counter({503: 3, 200: 1, 429: 1}))
    generator = SimpleNamespace(gemini=client, log=lines.append,
                                _plot_calls={"вопрос": 1})
    animepack.AnimePackGenerator.log_gemini_spent(generator)
    assert "HTTP-попыток за прогон 5" in lines[0]
    assert "успешных HTTP-ответов 1" in lines[0]
    assert "503: 3" in lines[0] and "429: 1" in lines[0]
    assert "возможный расход квоты 4 (локальная оценка)" in lines[0]


def test_minute_resource_exhausted_retries_same_model(
        fake_session, fake_response, monkeypatch):
    error = json.dumps({"error": {"status": "RESOURCE_EXHAUSTED",
                                 "message": "Quota exceeded per minute"}})
    replies = iter([fake_response(429, text=error), fake_response(json_data=_ok())])
    session = fake_session([("interactions", lambda _u, **_k: next(replies))])
    client = _client(session, monkeypatch, model="gemini-3.8-flash")
    client.generate_json("вопрос", SCHEMA)
    assert all(call[2]["json"]["model"] == "gemini-3.8-flash"
               for call in session.calls)
    assert not client.board.exhausted(client.model)


def test_all_busy_models_raise_terminal_down_error(
        fake_session, fake_response, monkeypatch):
    session = fake_session([("interactions", fake_response(503, text="busy"))])
    client = _client(session, monkeypatch)
    with pytest.raises(GeminiDownError):
        client.generate_json("вопрос", SCHEMA)
    calls = len(session.calls)
    assert calls == 2 * len(gemini_api.MODELS)
    with pytest.raises(GeminiDownError):
        client.generate_json("другой вопрос", SCHEMA)
    assert len(session.calls) == calls


def test_high_thinking_falls_back_to_interactions_when_generate_content_is_busy(
        fake_session, fake_response, monkeypatch):
    """Высокое рассуждение идёт через GenerateContent; его 5xx — повод
    перейти на Interactions той же моделью, а не сжигать её квоту."""
    def generate(url, **kwargs):
        assert kwargs["json"]["generationConfig"]["thinkingConfig"] == {
            "thinkingLevel": "HIGH"}
        return fake_response(503, text="high demand")

    session = fake_session([("generateContent", generate),
                            ("interactions", fake_response(json_data=_ok()))])
    client = _client(session, monkeypatch, model="gemini-3.8-flash", thinking="high")
    assert client.generate_json("вопрос", SCHEMA) == {"ok": True}
    assert session.calls[0][1].endswith("/gemini-3.8-flash:generateContent")
    assert session.calls[-1][1].endswith("/interactions")
    assert session.calls[-1][2]["json"]["model"] == "gemini-3.8-flash"
    assert len(session.calls) == 2
    assert client.prefer_interactions is True


def test_queued_request_skips_model_marked_unavailable(
        fake_session, fake_response, monkeypatch):
    session = fake_session([("interactions", fake_response(json_data=_ok()))])
    client = _client(session, monkeypatch, model="gemini-3.8-flash")
    client.board.note_server_failure(client.model)
    client.board.note_server_failure(client.model)
    with pytest.raises(gemini_api._ModelUnavailable):
        client._post({"model": client.model, "input": "старый запрос"})
    assert session.calls == []


def test_plot_is_disabled_when_all_models_are_down_and_stats_are_kept(monkeypatch):
    from si_hyx_parts.animepack import plot_season
    from tests.test_animepack_new_kinds import make_anime

    class DownClient:
        spent = {"model": 10}
        requests_made = 10
        response_codes = {503: 10}
        calls = 0

        def generate_json(self, *_args, **_kwargs):
            self.calls += 1
            raise GeminiDownError("Все модели временно недоступны")

    model = DownClient()
    lines = []
    settings = animepack.PackSettings(pack_plot=True, pct_plot=100, pct_songs=0,
                                     plot_mode="detail", parallel=1)
    generator = animepack.AnimePackGenerator(settings, gemini=model,
                                             fandom=object(), log=lines.append)
    monkeypatch.setattr(animepack, "pick_plot", lambda *_args, **_kwargs: {
        "wiki": "test.fandom.com", "page": "Episode", "text": "Пересказ " * 60})
    monkeypatch.setattr(plot_season, "apply_season", lambda *_args: "")
    candidate = animepack.SongCandidate({}, make_anime(), kind=animepack.PLOT_KIND)
    assert not generator.make_plot_question(candidate)
    assert candidate.rejected and animepack.PLOT_KIND in generator._dead_kinds
    assert generator.gemini is None and model.calls == 1
    generator.gemini_titles = generator.gemini_pixiv = generator.gemini_manga = None
    assert not generator.make_plot_question(candidate)
    assert model.calls == 1
    generator.log_gemini_spent()
    assert any("HTTP-попыток за прогон 10" in line for line in lines)
    assert any("503: 10" in line for line in lines)


def test_repeated_read_timeouts_do_not_resubmit_same_request(
        fake_session, fake_response, monkeypatch):
    attempts = []

    def route(_url, **kwargs):
        attempts.append(kwargs["json"]["model"])
        if attempts[-1] == "gemini-3.8-flash":
            raise requests.exceptions.ReadTimeout("slow")
        return fake_response(json_data=_ok())

    session = fake_session([("interactions", route)])
    client = _client(session, monkeypatch, model="gemini-3.8-flash")
    for _ in range(2):
        with pytest.raises(gemini_api.GeminiUnavailableError):
            client.generate_json("принятый сервером запрос", SCHEMA)
    assert attempts == ["gemini-3.8-flash", "gemini-3.8-flash"]
    assert client.generate_json("следующее задание", SCHEMA) == {"ok": True}
    assert attempts[-1] == "gemini-3.5-flash-lite"


def test_quota_label_describes_estimate_instead_of_served_requests(monkeypatch):
    from si_hyx_parts.animepack_tab.composition_controls import refresh_quota

    lines = []
    monkeypatch.setattr(gemini_usage, "requests_today", lambda *_args: 5)
    monkeypatch.setattr(gemini_usage, "daily_cap", lambda *_args: 20)
    monkeypatch.setattr(gemini_usage, "exhausted_today", lambda *_args: False)
    tab = SimpleNamespace(_api_key=lambda _name: "key",
                          cb_gemini_model=SimpleNamespace(currentText=lambda: "model"),
                          lbl_gemini_quota=SimpleNamespace(setText=lines.append))
    refresh_quota(tab)
    assert "возможный расход квоты сегодня — 5 (оценка SI-HYX)" in lines[0]
    assert "по этой оценке осталось 15" in lines[0]
    assert "обслужено" not in lines[0]
