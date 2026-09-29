"""Speech providers for description questions, with run-wide quota fallback."""
from __future__ import annotations

import base64
from collections import deque
import threading
import time

import requests


class SpeechError(RuntimeError):
    def __init__(self, message: str, *, exhausted: bool = False,
                 rate_limited: bool = False, retry_after: float = 0):
        super().__init__(message)
        self.exhausted = exhausted
        self.rate_limited = rate_limited
        self.retry_after = retry_after


class DescriptionSpeech:
    def __init__(self, settings, session, log, stopped=lambda: False):
        self.settings, self.session, self.log = settings, session, log
        self.stopped = stopped
        self._lock = threading.RLock()
        self._unavailable: set[str] = set()
        self._cooldown_until: dict[str, float] = {}
        self._rate_failures: dict[str, int] = {}
        self._gemini_recent: dict[str, deque[float]] = {}
        self._credentials = None

    @property
    def unavailable(self) -> bool:
        return self.unavailable_for(self.settings.description_language)

    def unavailable_for(self, language) -> bool:
        with self._lock:
            return all(name in self._unavailable
                       for name in self._providers(language))

    def _providers(self, language=None) -> tuple[str, ...]:
        from .description_gemini_tts import TTS_MODELS
        language = language or self.settings.description_language
        selected = self.settings.description_gemini_tts_model
        gemini_models = (selected,) + tuple(
            model for model in TTS_MODELS if model != selected)
        choices = gemini_models + (("google",) if language in ("en", "uk")
                                   else ()) + ("elevenlabs",)
        first = self.settings.description_tts_first
        if first == "google" and language in ("en", "uk"):
            return ("google",) + tuple(name for name in choices if name != "google")
        if first == "elevenlabs":
            return ("elevenlabs",) + tuple(name for name in choices
                                            if name != "elevenlabs")
        return choices

    def synthesize(self, text: str, language=None) -> tuple[bytes, str]:
        errors = []
        for provider in self._providers(language):
            if self.stopped():
                raise SpeechError("Остановлено")
            with self._lock:
                if provider in self._unavailable:
                    continue
                if self._cooldown_until.get(provider, 0) > time.monotonic():
                    errors.append(f"{provider}: временный лимит запросов")
                    continue
            try:
                if provider == "elevenlabs":
                    result = self._elevenlabs(text)
                elif provider.startswith("gemini-"):
                    self._wait_for_gemini_slot(provider)
                    result = self._gemini_tts(text, provider)
                else:
                    result = self._google_chirp(text, language)
                with self._lock:
                    self._cooldown_until.pop(provider, None)
                    self._rate_failures.pop(provider, None)
                if errors:
                    self.log(f"Озвучка: переключился на {provider}.")
                return result
            except SpeechError as exc:
                errors.append(f"{provider}: {exc}")
                if exc.exhausted:
                    with self._lock:
                        self._unavailable.add(provider)
                elif exc.rate_limited:
                    with self._lock:
                        failures = min(self._rate_failures.get(provider, 0) + 1, 5)
                        self._rate_failures[provider] = failures
                        delay = min(60, max(2 ** failures, exc.retry_after))
                        self._cooldown_until[provider] = time.monotonic() + delay
                self.log(f"Озвучка {provider}: {exc}; пробую другой сервис.")
            except requests.RequestException as exc:
                errors.append(f"{provider}: ошибка сети")
                self.log(f"Озвучка {provider}: ошибка сети ({type(exc).__name__}); "
                         "пробую другой сервис.")
        raise SpeechError("; ".join(errors) or "Нет доступного сервиса озвучки")

    def _wait_for_gemini_slot(self, model: str) -> None:
        # AI Studio: 3 RPM на каждую модель. Три описания до 1600 символов
        # также остаются значительно ниже её входного лимита 10K TPM.
        while True:
            if self.stopped():
                raise SpeechError("Остановлено")
            with self._lock:
                now = time.monotonic()
                recent = self._gemini_recent.setdefault(model, deque())
                while recent and recent[0] <= now - 60:
                    recent.popleft()
                if len(recent) < 3:
                    recent.append(now)
                    return
                delay = max(0.01, recent[0] + 60 - now)
            time.sleep(min(delay, 0.5))

    def _elevenlabs(self, text: str) -> tuple[bytes, str]:
        key = str(self.settings.elevenlabs_key or "").strip()
        voice = str(self.settings.elevenlabs_voice or "").strip()
        if not key or not voice:
            raise SpeechError("не заданы ключ или голос", exhausted=True)
        response = self.session.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={"text": text, "model_id": "eleven_v3",
                  "voice_settings": {"speed": 1.2}}, timeout=90)
        if response.status_code != 200:
            raise _response_error(response)
        return _audio(response.content, "mp3")

    def _google_chirp(self, text: str, language=None) -> tuple[bytes, str]:
        language = {"en": "en-US", "uk": "uk-UA"}[
            language or self.settings.description_language]
        voice = f"{language}-Chirp3-HD-Kore"
        response = self.session.post(
            "https://texttospeech.googleapis.com/v1/text:synthesize",
            headers=self._google_headers(),
            json={"input": {"text": text},
                  "voice": {"languageCode": language, "name": voice},
                  "audioConfig": {"audioEncoding": "MP3",
                                  "speakingRate": 1.2}}, timeout=90)
        if response.status_code != 200:
            raise _response_error(response)
        try:
            encoded = response.json()["audioContent"]
            return _audio(base64.b64decode(encoded, validate=True), "mp3")
        except (KeyError, ValueError, TypeError) as exc:
            raise SpeechError("Google не вернул аудиоданные") from exc

    def _google_headers(self) -> dict:
        try:
            import google.auth
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as exc:
            raise SpeechError("не установлен google-auth", exhausted=True) from exc
        with self._lock:
            if self._credentials is None:
                scopes = ["https://www.googleapis.com/auth/cloud-platform"]
                path = str(self.settings.google_tts_credentials or "").strip()
                try:
                    if path:
                        self._credentials = service_account.Credentials.from_service_account_file(
                            path, scopes=scopes)
                    else:
                        self._credentials, _ = google.auth.default(scopes=scopes)
                except Exception as exc:
                    raise SpeechError("нет учётных данных Google Cloud: укажите "
                                      "service account JSON или настройте ADC",
                                      exhausted=True) from exc
            try:
                if not self._credentials.valid:
                    self._credentials.refresh(Request())
            except Exception as exc:
                raise SpeechError("не удалось обновить доступ к Google Cloud",
                                  exhausted=True) from exc
            return {"Authorization": f"Bearer {self._credentials.token}",
                    "Content-Type": "application/json"}

    def _gemini_tts(self, text: str, model: str) -> tuple[bytes, str]:
        key = str(self.settings.gemini_key or "").strip()
        from .description_gemini_tts import synthesize
        return synthesize(self.session, key, model, text)


def _response_error(response) -> SpeechError:
    detail = _error_detail(response)
    lower = detail.casefold()
    permanent_quota = any(marker in lower for marker in (
        "quota_exceeded", "insufficient_credit", "out of credit",
        "payment_required", "billing", "daily quota", "monthly quota",
        "per day", "per month", "limit: 0"))
    invalid_config = any(marker in lower for marker in (
        "voice_not_found", "invalid_voice", "model_not_found",
        "invalid_model", "invalid_api_key", "unsupported_language"))
    invalid_config |= (response.status_code in (400, 404)
                       and any(name in lower for name in ("voice", "model", "language"))
                       and any(issue in lower for issue in (
                           "not found", "does not exist", "invalid", "unsupported")))
    exhausted = (permanent_quota or invalid_config
                 or response.status_code in (401, 402, 403))
    rate_limited = response.status_code == 429 and not exhausted
    headers = getattr(response, "headers", {}) or {}
    try:
        retry_after = min(60.0, max(0.0, float(headers.get("Retry-After", 0))))
    except (TypeError, ValueError):
        retry_after = 0.0
    return SpeechError(f"HTTP {response.status_code}: {detail}",
                       exhausted=exhausted, rate_limited=rate_limited,
                       retry_after=retry_after)


def _error_detail(response) -> str:
    try:
        data = response.json()
    except ValueError:
        return "ошибка сервиса"
    detail = data.get("detail", data.get("error", {})) if isinstance(data, dict) else {}
    if isinstance(detail, dict):
        status = str(detail.get("status") or detail.get("code") or "")
        message = str(detail.get("message") or "")
        return (f"{status}: {message}" if status and message else
                status or message or "ошибка сервиса")[:180]
    return str(detail or "ошибка сервиса")[:180]


def _audio(data: bytes, ext: str) -> tuple[bytes, str]:
    mp3 = data.startswith(b"ID3") or (
        len(data) >= 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0)
    wav = data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    if not (mp3 if ext == "mp3" else wav):
        raise SpeechError("сервис вернул некорректное аудио")
    return data, ext
