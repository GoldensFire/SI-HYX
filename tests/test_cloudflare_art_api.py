# -*- coding: utf-8 -*-
"""Wire formats, error handling and cancellation without real API spending."""
import base64
import io

from PIL import Image
import pytest
import requests

from cloudflare_art_api import (
    CloudflareArtClient, CloudflareArtError, CloudflareArtUnavailable,
    CloudflareArtCancelled, DEFAULT_MODEL, MODELS,
)


@pytest.fixture
def image_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (128, 128), (70, 110, 190)).save(buf, "PNG")
    return buf.getvalue()


def response_body(data):
    return {"success": True, "result": {"image": base64.b64encode(data).decode("ascii")}}


@pytest.mark.parametrize("model", MODELS)
def test_wire_format_and_decoded_image(model, image_bytes, fake_session, fake_response):
    session = fake_session([("/ai/run/", fake_response(json_data=response_body(image_bytes)))])
    client = CloudflareArtClient("a" * 32, "secret", model=model, session=session)
    data, ext = client.generate("A text-free anime illustration", seed=42)
    assert (data, ext) == (image_bytes, ".png")
    method, url, kw = session.calls[0]
    assert method == "POST" and url.endswith(model)
    assert "/accounts/" + "a" * 32 + "/" in url
    assert kw["headers"] == {"Authorization": "Bearer secret"}
    assert kw["allow_redirects"] is False
    assert "json" not in kw
    assert kw["files"]["width"] == (None, "1024")
    assert kw["files"]["height"] == (None, "1024")
    assert kw["files"]["seed"] == (None, "42")


@pytest.mark.parametrize("status,code", [(429, 3036), (403, 5035), (401, 10000)])
def test_fatal_errors_are_not_retried_or_echoed(status, code, fake_session, fake_response):
    session = fake_session([("/ai/run/", fake_response(status, json_data={
        "success": False, "errors": [{"code": code, "message": "Bearer secret"}]}))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    with pytest.raises(CloudflareArtUnavailable) as exc:
        client.generate("Anime", seed=1)
    assert "secret" not in str(exc.value)
    assert len(session.calls) == 1


def test_busy_api_obeys_retry_after(image_bytes, fake_session, fake_response, monkeypatch):
    replies = iter([
        fake_response(429, json_data={"errors": [{"code": 3040}]},
                      headers={"Retry-After": "7"}),
        fake_response(json_data=response_body(image_bytes)),
    ])
    session = fake_session([("/ai/run/", lambda *a, **kw: next(replies))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    delays = []
    monkeypatch.setattr(client, "_sleep", delays.append)
    assert client.generate("Anime", seed=1)[0] == image_bytes
    assert delays == [7] and len(session.calls) == 2


def test_busy_api_has_bounded_retries(fake_session, fake_response, monkeypatch):
    session = fake_session([("/ai/run/", fake_response(503))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    monkeypatch.setattr(client, "_sleep", lambda *_: None)
    with pytest.raises(CloudflareArtUnavailable):
        client.generate("Anime", seed=1)
    assert len(session.calls) == 3


def test_transport_timeout_does_not_resubmit(fake_session):
    def timeout(*a, **kw):
        raise requests.ReadTimeout("secret")

    session = fake_session([("/ai/run/", timeout)])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    with pytest.raises(CloudflareArtUnavailable) as exc:
        client.generate("Anime", seed=1)
    assert "secret" not in str(exc.value) and len(session.calls) == 1


@pytest.mark.parametrize("body", [
    {"success": True, "result": {"image": "not base64!"}},
    response_body(b"this is not a PNG"),
    {"success": True, "result": None, "errors": None},
    [],
])
def test_invalid_payload_is_not_treated_as_an_image(body, fake_session, fake_response):
    session = fake_session([("/ai/run/", fake_response(json_data=body))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    with pytest.raises(CloudflareArtError):
        client.generate("Anime", seed=1)


def test_cancelled_request_never_reaches_network(fake_session):
    session = fake_session()
    client = CloudflareArtClient("a" * 32, "secret", session=session, stopped=lambda: True)
    with pytest.raises(CloudflareArtCancelled):
        client.generate("Anime", seed=1)
    assert session.calls == []


def test_cancelled_response_is_not_used(image_bytes, fake_session, fake_response):
    stopped = []

    def reply(*a, **kw):
        stopped.append(True)
        return fake_response(json_data=response_body(image_bytes))

    session = fake_session([("/ai/run/", reply)])
    client = CloudflareArtClient("a" * 32, "secret", session=session,
                                stopped=lambda: bool(stopped))
    with pytest.raises(CloudflareArtCancelled):
        client.generate("Anime", seed=1)


def test_bad_account_or_model_fails_before_network(fake_session):
    session = fake_session()
    client = CloudflareArtClient("../account", "secret", session=session)
    with pytest.raises(CloudflareArtUnavailable):
        client.generate("Anime", seed=1)
    assert session.calls == []


def test_flux_one_is_not_available():
    assert not any("flux-1" in model for model in MODELS)
    assert "flux-2" in DEFAULT_MODEL
