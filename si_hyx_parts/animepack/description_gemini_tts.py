"""Gemini speech synthesis through the REST Interactions API."""
from __future__ import annotations

import base64
import io
import wave


# Models listed in Google's speech-generation guide. Older previews return
# headerless 24 kHz PCM; the 3.8 models return a complete WAV file.
TTS_MODELS = (
    "gemini-3.8-flash-lite-tts",
    "gemini-3.8-flash-tts",
    "gemini-3.1-flash-tts-preview",
)


def synthesize(session, key: str, model: str, text: str):
    from .description_tts import SpeechError, _audio, _response_error

    if not key:
        raise SpeechError("нет ключа Gemini", exhausted=True)
    if model not in TTS_MODELS:
        raise SpeechError("неизвестная модель Gemini TTS", exhausted=True)
    body = {
        "model": model,
        "input": [{"type": "user_input", "content": [{"type": "text",
                    "text": text,
                    **({"annotations": [{"type": "speech_metadata",
                                         "style": "speaking rapidly"}]}
                       if model.startswith("gemini-3.8") else {})}]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": "Kore"}]},
    }
    response = session.post(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json=body, timeout=90)
    if response.status_code != 200:
        raise _response_error(response)
    try:
        data = response.json()
        for step in reversed(data.get("steps", [])):
            for item in reversed(step.get("content", [])):
                if item.get("type") == "audio":
                    payload = base64.b64decode(item["data"], validate=True)
                    if not payload.startswith(b"RIFF"):
                        payload = _wave(payload)
                    return _audio(payload, "wav")
    except (KeyError, ValueError, TypeError) as exc:
        raise SpeechError("Gemini TTS вернул повреждённое аудио") from exc
    raise SpeechError("Gemini TTS не вернул аудио")


def _wave(pcm: bytes) -> bytes:
    if not pcm or len(pcm) % 2:
        raise ValueError("неверная длина PCM")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(24000)
        file.writeframes(pcm)
    return buffer.getvalue()
