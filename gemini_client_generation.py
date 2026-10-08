# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""JSON generation and fallback methods of the public Gemini client."""
from __future__ import annotations
from typing import Any

import gemini_api as _api
from gemini_client_recovery import fallback_chain, recover


def generate_json(self, prompt, schema: dict, *,
                  temperature: float = 0.0) -> Any:
    """Ответ модели, разобранный по schema (JSON Schema для response_format).

    prompt — строка либо готовый список частей (для будущих запросов с
    картинками: Interactions API принимает в input и то, и другое).

    Бросает GeminiAuthError (ключ), GeminiQuotaError (кончилась квота) или
    GeminiError (всё остальное). Звать имеет смысл только у configured
    клиента — иначе сразу GeminiAuthError, в сеть не ходим.
    """
    if not self.configured:
        raise _api.GeminiAuthError("Не введён ключ Gemini API")
    while True:
        recover(self)
        with self._model_lock:
            if self._terminal_down:
                raise _api.GeminiCoolingError(self._terminal_down)
            if self._terminal_quota:
                raise _api.GeminiQuotaError(self._terminal_quota)
            model, thinking = self.model, self.thinking
        if self.board.unavailable(model):
            self._switch(model, f"Gemini: {model} временно недоступна",
                         unavailable=True)
            continue
        if self.board.exhausted(model):
            # Про исчерпанную квоту уже известно — с прошлого прогона или
            # от соседнего клиента. Запрос не отправляем вовсе: раньше на
            # это выяснение уходил десяток отброшенных 429 подряд.
            self._switch(model, f"Gemini: квота {model} на сегодня "
                                "исчерпана (известно из прошлых запросов)")
            continue
        body = {
            "model": model,
            "store": False,
            "input": prompt,
            "response_format": {
                "type": "text", "mime_type": "application/json",
                "schema": schema,
            },
            "generation_config": {
                "temperature": float(temperature),
                "thinking_level": thinking,
            },
        }
        video_input = isinstance(prompt, list) and any(
            isinstance(part, dict) and part.get("type") == "video" for part in prompt)
        image_input = isinstance(prompt, list) and any(
            isinstance(part, dict) and part.get("type") == "image" for part in prompt)
        if (not getattr(self, "prefer_interactions", False)
                and ((thinking == "high" and isinstance(prompt, str)) or video_input
                     or (image_input and (self.image_generate_content
                                          or _api.is_gemma(model))))):
            # Interactions held even a trivial high-thinking request until
            # the read timeout. The supported GenerateContent endpoint
            # answered the same model/level in seconds in a live probe.
            parts = ([{"text": prompt}] if isinstance(prompt, str) else [
                {"text": part["text"]} if part.get("type") == "text" else
                {"inlineData": {"mimeType": part["mime_type"], "data": part["data"]}}
                for part in prompt])
            body = {
                "model": model,
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": float(temperature),
                    "thinkingConfig": {"thinkingLevel": thinking.upper()},
                    "responseMimeType": "application/json",
                    "responseSchema": _api._generate_schema(schema),
                },
            }
        try:
            return _api._json_from_response(self._post(body))
        except _api._EndpointUnavailable:
            self.prefer_interactions = True
            self.log("Gemini: GenerateContent временно недоступен; пробую Interactions.")
            continue
        except _api._ModelChanged:
            continue
        except _api._ModelUnavailable as exc:
            self._switch(model, str(exc), unavailable=True)
        except _api.GeminiQuotaError as exc:
            self._switch(model, str(exc))

def _switch(self, model: str, why: str, *, unavailable=False) -> None:
    """Переходит на следующую живую модель.

    Дневная квота остаётся конечным отказом. После временной перегрузки
    recover снова проверит модели по истечении их пауз. Соседний поток мог
    переключить модель раньше — тогда второй раз менять её незачем."""
    with self._model_lock:
        if self.model != model:
            return
        if not self.allow_model_fallback:
            message = (f"Gemini: выбранная модель {model}: {why}; "
                       "автоматическая замена модели отключена")
            if unavailable:
                self._terminal_down = message
                raise _api.GeminiCoolingError(message)
            self._terminal_quota = message
            raise _api.GeminiQuotaError(message)
        primary = getattr(self, "primary_model", model)
        choices = tuple(dict.fromkeys(fallback_chain(self, model) + (primary,)))
        if unavailable:
            # При перегрузке сначала пробуем менее тяжёлую Flash-Lite.
            choices = tuple(n for n in choices if n.endswith("-lite")) + tuple(
                n for n in choices if not n.endswith("-lite"))
        next_model = next((name for name in choices
                           if not self.board.exhausted(name)
                           and not self.board.unavailable(name)), None)
        if next_model is None:
            if unavailable or any(self.board.unavailable(n) for n in choices):
                self._terminal_down = ("Gemini: доступных моделей не осталось "
                                       f"(квота или перегрузка); {why}")
                raise _api.GeminiCoolingError(self._terminal_down)
            self._terminal_quota = why
            raise _api.GeminiQuotaError(why)
        self.model = next_model
        self.thinking = _api.thinking_level(self.thinking, next_model)
        self._interval = self._model_interval(next_model)
    from gemini_quota import UNAVAILABLE_COOLDOWN
    reason = ("сервер временно недоступен, пропускаю модель на "
              f"{UNAVAILABLE_COOLDOWN / 60:.0f} мин"
              if unavailable else "квота исчерпана")
    self.log(f"Gemini: {model}: {reason}; переключаюсь на {next_model}.")

