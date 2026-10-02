"""HTTP transport and retry policy for the public Gemini client."""
from __future__ import annotations

from typing import Any

def _post(self, body: dict) -> Any:
    """POST с ретраями. Возвращает разобранное тело ответа."""
    # Импорт при вызове сохраняет публичные исключения и точки подмены.
    import gemini_api as api
    from gemini_quota import is_daily, is_minute

    headers = {"x-goog-api-key": self.api_key,
               "Content-Type": "application/json"}
    delay = 2.0
    last = ""
    model = str(body.get("model") or self.model)
    if "contents" in body:
        url = f"{api.API_ROOT}/models/{model}:generateContent"
        payload = {key: value for key, value in body.items() if key != "model"}
    else:
        url, payload = api.INTERACTIONS_URL, body
    for attempt in range(self.max_retries):
        if self.stopped():
            raise api.GeminiError("Отменено")
        self._throttle(model)
        if self.stopped():
            raise api.GeminiError("Отменено")
        # Восемь рабочих потоков заранее занимают будущие слоты. Если
        # первый из них узнал, что квота модели кончилась, остальные не
        # должны по очереди досылать старые тела и тратить ещё 7 RPD.
        with self._model_lock:
            if self._terminal_down:
                raise api.GeminiDownError(self._terminal_down)
            if self._terminal_quota:
                raise api.GeminiQuotaError(self._terminal_quota)
            if model != self.model:
                raise api._ModelChanged()
        if self.board.unavailable(model):
            raise api._ModelUnavailable(f"Gemini: {model} временно недоступна")
        if self.board.exhausted(model):
            raise api.GeminiQuotaError(f"Gemini: квота {model} исчерпана")
        with self._model_lock:
            self.spent[model] += 1
        try:
            resp = self.session.post(
                url, headers=headers, json=payload,
                timeout=(api.CONNECT_TIMEOUT, self.timeout))
        except Exception as e:  # noqa: BLE001 — сеть отвалилась, пробуем ещё
            if api._answered(e):
                # Отправленный запрос мог быть принят сервером: считаем
                # возможный расход и не дублируем его после таймаута.
                with self._model_lock:
                    self.response_codes["timeout"] += 1
                    self.requests_made += 1
                self.board.spend(model)
                # Следующее задание обойдёт модель после серии таймаутов;
                # этот уже отправленный запрос другой моделью не повторяем.
                self.board.note_server_failure(model)
                raise api.GeminiUnavailableError(
                    f"Gemini не ответил за {self.timeout:.0f} с "
                    "(учтён как возможный расход квоты)") from e
            with self._model_lock:
                self.response_codes["network"] += 1
            last = str(e)
            self.log(f"Gemini: сеть недоступна ({e}), попытка "
                     f"{attempt + 1} из {self.max_retries}")
            if attempt + 1 < self.max_retries:
                self._sleep(delay)
            delay *= 2
            continue
        code = int(getattr(resp, "status_code", 0) or 0)
        counted = code not in (401, 403, 429)
        with self._model_lock:
            self.response_codes[code] += 1
            if counted:
                self.requests_made += 1
        if counted:
            # Google может учитывать ошибки 400/5xx в квоте. Это оценка
            # обращений данного ключа, а не фактический счёт всего проекта.
            self.board.spend(model)
        if code < 500:
            self.board.note_response(model)
        text = getattr(resp, "text", "") or ""
        if 200 <= code < 300:
            try:
                return resp.json()
            except Exception:
                return api._json_from_text(text)
        if code == 400 and api._is_blocked(text):
            # «Запрос содержит недопустимые слова» — беда одного текста, а
            # не ключа: следующий запрос той же моделью пройдёт как ни в чём
            # не бывало.
            raise api.GeminiBlockedError(api.error_message(text, code))
        if code in (400, 401, 403):
            # 400 сюда же: у Gemini это «ключ не той формы» и «модель не
            # существует» — ретраить бессмысленно, надо править настройки.
            raise api.GeminiAuthError(api.error_message(text, code))
        if code == 429:
            if is_daily(text) or (api.is_quota(text) and not is_minute(text)):
                # Суточный или неуточнённый предел не выясняем повторно.
                self.board.mark(model, text)
                raise api.GeminiQuotaError(api.error_message(text, code))
            wait = api.retry_after(resp, text, default=delay)
            last = api.error_message(text, code)
            self.board.defer(model, wait)
            if attempt + 1 < self.max_retries:
                self.log(f"Gemini: минутный лимит, жду {wait:.0f} с "
                         f"(попытка {attempt + 1} из {self.max_retries})")
                self._sleep(wait)
            delay = min(delay * 2, 60.0)
            continue
        if code >= 500:
            last = api.error_message(text, code)
            if self.board.note_server_failure(model):
                raise api._ModelUnavailable(last)
            if attempt + 1 < self.max_retries:
                self.log(f"Gemini: {model}: сервер ответил {code}, повтор через "
                         f"{delay:.0f} с")
                self._sleep(delay)
            delay *= 2
            continue
        raise api.GeminiError(api.error_message(text, code))
    raise api.GeminiUnavailableError(last or "Gemini не ответил")
