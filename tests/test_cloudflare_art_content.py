# -*- coding: utf-8 -*-
"""Content rejection recovery keeps the selected model and a bounded budget."""
import base64
import io

from PIL import Image
import pytest

from animepack_art import AnimeArtService
from cloudflare_art_api import (
    CloudflareArtClient, CloudflareArtCancelled, CloudflareArtContentRejected,
    CloudflareArtUnavailable, MODELS,
)


def image_body():
    buf = io.BytesIO()
    Image.new("RGB", (128, 128), "blue").save(buf, "PNG")
    return {"result": {"image": base64.b64encode(buf.getvalue()).decode()}}


def error_body(message=("AiError: AiError: Your output has been flagged. "
                        "Please choose another prompt / input image combination (secret)"),
               code=3030):
    return {"success": False, "errors": [{"code": code, "message": message}]}


@pytest.mark.parametrize("model", MODELS)
def test_output_retry_generates_and_caches_on_selected_model(
        model, tmp_path, fake_session, fake_response):
    replies = iter([fake_response(400, json_data=error_body()),
                    fake_response(json_data=image_body())])
    session = fake_session([("/ai/run/", lambda *a, **kw: next(replies))])
    logs = []
    client = CloudflareArtClient("a" * 32, "secret", model=model,
                                session=session, on_retry=logs.append)
    service = AnimeArtService(client)
    data, ext = service.generate({"english": "K-On!"})
    assert data and ext == ".png"
    assert len(session.calls) == 2
    assert all(url.endswith(model) for _, url, _ in session.calls)
    assert len(logs) == 1 and "2/3" in logs[0] and "secret" not in logs[0]
    first, second = [call[2] for call in session.calls]
    assert first["files"]["prompt"] == second["files"]["prompt"]
    assert first["files"]["seed"] != second["files"]["seed"]


def test_output_budget_seed_wrap_and_response_closure(fake_session, fake_response):
    closed = []

    def reply(*args, **kwargs):
        response = fake_response(400, json_data=error_body())
        response.close = lambda: closed.append(True)
        return response

    session = fake_session([("/ai/run/", reply)])
    client = CloudflareArtClient("a" * 32, "secret", model=list(MODELS)[1],
                                session=session)
    with pytest.raises(CloudflareArtContentRejected, match="3 попыток"):
        client.generate("A peaceful anime scene", seed=2**31 - 1)
    assert len(closed) == 3
    assert [c[2]["files"]["seed"][1] for c in session.calls] == [str(2**31 - 1), "0", "1"]


@pytest.mark.parametrize("message", [
    "AiError: Input prompt contains NSFW content. secret",
    "Your input has been flagged. secret",
    "Input prompt and output have been flagged. secret",
])
def test_input_rejection_never_retries(message, fake_session, fake_response):
    session = fake_session([("/ai/run/", fake_response(400, json_data=error_body(message)))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    with pytest.raises(CloudflareArtContentRejected, match="промпт") as exc:
        client.generate("Anime", seed=42)
    assert len(session.calls) == 1 and "secret" not in str(exc.value)


def test_unknown_3030_does_not_assume_content_rejection(fake_session, fake_response):
    session = fake_session([("/ai/run/", fake_response(400, json_data=error_body("secret")))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    with pytest.raises(CloudflareArtUnavailable, match="3030"):
        client.generate("Anime", seed=42)
    assert len(session.calls) == 1


def test_input_rejection_after_output_stops_immediately(fake_session, fake_response):
    replies = iter([fake_response(400, json_data=error_body()),
                    fake_response(400, json_data=error_body("Input prompt flagged"))])
    session = fake_session([("/ai/run/", lambda *a, **kw: next(replies))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    with pytest.raises(CloudflareArtContentRejected, match="промпт"):
        client.generate("Anime", seed=42)
    assert len(session.calls) == 2


def test_content_and_http_retries_share_budget(fake_session, fake_response, monkeypatch):
    replies = iter([fake_response(503), fake_response(400, json_data=error_body()),
                    fake_response(400, json_data=error_body())])
    session = fake_session([("/ai/run/", lambda *a, **kw: next(replies))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    monkeypatch.setattr(client, "_sleep", lambda *_: None)
    with pytest.raises(CloudflareArtContentRejected):
        client.generate("Anime", seed=42)
    assert len(session.calls) == 3


def test_stop_during_retry_does_not_submit_again(fake_session, fake_response):
    stopped = []
    session = fake_session([("/ai/run/", fake_response(400, json_data=error_body()))])
    client = CloudflareArtClient("a" * 32, "secret", session=session,
                                stopped=lambda: bool(stopped), on_retry=stopped.append)
    with pytest.raises(CloudflareArtCancelled):
        client.generate("Anime", seed=42)
    assert len(session.calls) == 1


def test_quota_after_rejection_stops_queue(tmp_path, fake_session, fake_response):
    replies = iter([fake_response(400, json_data=error_body()),
                    fake_response(429, json_data=error_body("quota", code=3036))])
    session = fake_session([("/ai/run/", lambda *a, **kw: next(replies))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    service = AnimeArtService(client)
    for name in ("K-On!", "Deaimon"):
        with pytest.raises(CloudflareArtUnavailable, match="квота"):
            service.generate({"english": name})
    assert len(session.calls) == 2
