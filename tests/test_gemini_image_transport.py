"""Image checks can use GenerateContent without changing legacy text requests."""
from gemini_api import GeminiClient

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_opted_in_image_request_uses_inline_generate_content(fake_session, fake_response):
    response = {"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]}
    session = fake_session([("generateContent", fake_response(200, json_data=response))])
    client = GeminiClient("test-key", session=session, rpm=6000)
    client.image_generate_content = True
    assert client.generate_json([{"type": "text", "text": "Inspect"},
        {"type": "image", "mime_type": "image/jpeg", "data": "image-data"}], SCHEMA) == {"ok": True}
    _, url, options = session.calls[0]
    assert url.endswith(":generateContent")
    assert options["json"]["contents"][0]["parts"][1] == {
        "inlineData": {"mimeType": "image/jpeg", "data": "image-data"}}


def test_image_opt_in_preserves_low_thinking_text_transport(fake_session, fake_response):
    response = {"status": "completed", "steps": [{"type": "model_output",
        "content": [{"type": "text", "text": '{"ok":true}'}]}]}
    session = fake_session([("interactions", fake_response(200, json_data=response))])
    client = GeminiClient("test-key", session=session, rpm=6000)
    client.image_generate_content = True
    assert client.generate_json("Text request", SCHEMA) == {"ok": True}
    assert session.calls[0][1].endswith("/interactions")
