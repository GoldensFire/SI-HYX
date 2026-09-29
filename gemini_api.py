# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# gemini_api.py — тонкий клиент Google Gemini поверх requests. Здесь НЕТ Qt:
# модуль проверяется тестами отдельно от GUI (см. tests/test_gemini_api.py).
#
# Почему REST, а не официальный google-genai: SDK тянет за собой grpc и
# protobuf, а релиз собирается PyInstaller-ом — это десятки мегабайт в .exe и
# ещё один источник поломок сборки ради двух HTTP-запросов. requests в
# зависимостях уже есть, SI-HYX.spec трогать не нужно.
#
# Обычные запросы идут через Interactions API. Текстовые запросы с уровнем
# high идут через поддерживаемый models/{model}:generateContent: на выбранной
# Flash-Lite простой запрос через Interactions висел до таймаута, а тот же
# запрос через generateContent ответил за несколько секунд. Оба формата ответа
# разбирает _extract_text.
#
# Рассчитан на БЕСПЛАТНЫЙ тариф, и это определяет всё поведение:
#   • модель по умолчанию — Flash-Lite: у неё самые высокие бесплатные лимиты
#     (порядка 15 запросов в минуту и 1000 в сутки против 10/250 у Flash);
#   • запросы троттлятся по RPM ЛОКАЛЬНО, до отправки: упереться в 429 и потом
#     ждать — значит потратить лимит впустую;
#   • 429 и 5xx переживаются ретраями с паузой, которую называет сам сервер
#     (RetryInfo.retryDelay / заголовок Retry-After);
#   • исчерпанная модель запоминается НА СУТКИ (gemini_quota.QuotaBoard): иначе
#     каждый следующий прогон выяснял это заново десятком отброшенных запросов;
#   • ответ, не дождавшийся таймаута, НЕ повторяется: сервер запрос уже
#     обработал и в суточный лимит его засчитал, а четыре повтора превращали
#     один вопрос в четыре потраченных запроса.
#
# Ключ — ВСЕГДА пользовательский (вводится в настройках вкладки). Зашивать
# общий ключ в открытое GPL-приложение нельзя: его вытащат из бинаря, а платить
# по счёту будет автор.
from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from typing import Any, Callable, Optional

import requests

from gemini_quota import QuotaBoard, error_message, is_quota, retry_after

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
INTERACTIONS_URL = f"{API_ROOT}/interactions"


def _generate_schema(value):
    """GenerateContent accepts the schema fields we use, without JSON Schema extras."""
    if isinstance(value, dict):
        return {key: _generate_schema(item) for key, item in value.items()
                if key != "additionalProperties"}
    if isinstance(value, list):
        return [_generate_schema(item) for item in value]
    return value

# Модель по умолчанию. Flash-Lite — не «похуже», а «для потока»: наша задача
# (разложить готовый список ответов по франшизам) — классификация, а не
# рассуждение, и упирается она в лимит ЗАПРОСОВ, а не в интеллект модели.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
# Базовые модели видны даже без сети. При наличии ключа вкладка
# добавляет из API новые стабильные Gemini Flash. Lite остаётся рабочей
# лошадкой; preview/image/tts и прочие специальные варианты не показываем.
MODELS = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
)
# Запросов в минуту. У обычных Flash бесплатный предел — 5 RPM (не 10): старое
# значение 8 и давало на странице квот красные «8 / 5». Flash-Lite оставляем
# ниже её 15 RPM, чтобы граница минутного окна не превращалась в случайный 429.
FREE_RPM = 12
MODEL_RPM = {
    "gemini-3.1-flash-lite": 12,
    "gemini-3.5-flash-lite": 12,
    "gemini-3.6-flash": 5,
    "gemini-3.7-flash": 5,
    "gemini-3.8-flash": 5,
}
# «Размышления» модели. Для классификации (разложить готовый список по
# франшизам) это чистый расход выходных токенов и секунд, поэтому по умолчанию
# берём самый низкий уровень; совсем выключить их на Flash-Lite нельзя. А вот
# загадкам по названию и пересказам сюжета уровень повыше и правда помогает —
# поэтому его можно выбрать на вкладке (просьба пользователя).
#
# Уровни — общие для всех моделей Gemini 3.x. Какие из них модель принимает,
# решает сама модель: незнакомый уровень она отвергает ответом 400, и мы
# показываем её сообщение как есть, ничего не подменяя молча.
THINKING_LEVELS = ("minimal", "low", "medium", "high")
THINKING_LEVEL = "minimal"
# «Минимальный» умеет только Flash-Lite. Обычный Flash отвергает его ответом
# 400, поэтому у такой модели этого уровня нет ни в списке на вкладке, ни в
# запросе — он молча повышается до «низкого» (просьба пользователя).
LEVELS_WITHOUT_MINIMAL = THINKING_LEVELS[1:]


def model_thinking_levels(model: str = "") -> tuple[str, ...]:
    """Уровни рассуждения, которые принимает эта модель."""
    name = str(model or "").strip().lower()
    if name and _STABLE_FLASH_MODEL.fullmatch(name):
        return LEVELS_WITHOUT_MINIMAL
    return THINKING_LEVELS


def thinking_level(value: str = "", model: str = "") -> str:
    """Уровень рассуждения из настроек (незнакомый — уровень по умолчанию).

    Модель, которая уровня не знает, отвечает 400 и вопрос пропадает, поэтому
    недоступный ей уровень подменяется ближайшим доступным."""
    allowed = model_thinking_levels(model)
    level = str(value or "").strip().lower()
    if level not in THINKING_LEVELS:
        level = THINKING_LEVEL
    return level if level in allowed else allowed[0]


def fallback_models(model: str) -> tuple[str, ...]:
    """При исчерпании квоты: модели слабее, затем модели сильнее."""
    choices = list(MODELS)
    if model not in choices:
        choices.append(model)
        choices.sort(key=lambda name: tuple(int(n) for n in re.findall(r"\d+", name)))
    pos = choices.index(model)
    return tuple(reversed(choices[:pos])) + tuple(choices[pos + 1:])


_STABLE_FLASH_MODEL = re.compile(r"^gemini-\d+(?:\.\d+)*-flash$")
_STABLE_FLASH_LITE_MODEL = re.compile(r"^gemini-\d+(?:\.\d+)*-flash-lite$")
# Соединение ждём коротко, ответ — долго: на уровне «high» модель думает над
# пересказом серии минуты, а оборванный по таймауту запрос всё равно уже
# посчитан Google. Лучше один терпеливый заход, чем четыре торопливых.
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 180.0


class GeminiError(RuntimeError):
    """Общая ошибка обращения к Gemini."""


class GeminiAuthError(GeminiError):
    """Ключ не принят (нет, просрочен, не тот проект) — ретраить бессмысленно."""


class GeminiQuotaError(GeminiError):
    """Кончилась квота бесплатного тарифа (429 после всех ретраев)."""


class GeminiUnavailableError(GeminiError):
    """Сервер не ответил: 5xx после всех повторов, таймаут или нет сети."""


class GeminiDownError(GeminiError):
    """Gemini не отвечал несколько запросов подряд — до конца прогона не ждём."""


class GeminiBlockedError(GeminiError):
    """Модель отказалась разбирать ЭТОТ запрос (правила о недопустимом
    содержимом).

    Отдельный тип нарочно: с ключом и квотой всё в порядке, беда ровно в одном
    тексте — пересказ серии про войну или расправу Gemini не берёт. Такой ответ
    значит «возьми следующий тайтл», а не «выключай всю затею» (раньше это был
    GeminiAuthError, и один неудачный пересказ отключал вопросы по сюжету на
    весь прогон)."""


class _ModelChanged(RuntimeError):
    """Запланированный запрос относится к уже исчерпанной модели."""


def discover_models(api_key: str, session=None, timeout: float = 15.0) -> tuple[str, ...]:
    """Return built-in choices plus stable general-purpose Flash models.

    The Models endpoint is advisory: callers keep the built-in list when this
    request fails. API keys stay in a header so they cannot leak through URLs.
    """
    key = str(api_key or "").strip()
    if not key:
        return MODELS
    http = session or requests.Session()
    found = set(MODELS)
    token = ""
    for _ in range(5):
        params = {"pageSize": 1000}
        if token:
            params["pageToken"] = token
        try:
            response = http.get(
                f"{API_ROOT}/models", headers={"x-goog-api-key": key},
                params=params, timeout=timeout)
        except requests.RequestException as exc:
            raise GeminiError("Список моделей Gemini временно недоступен.") from exc
        try:
            code = int(getattr(response, "status_code", 0) or 0)
            if code in (400, 401, 403):
                raise GeminiAuthError("Ключ Gemini не подошёл для загрузки моделей.")
            if not 200 <= code < 300:
                raise GeminiError(f"Список моделей Gemini: HTTP {code}.")
            try:
                data = response.json()
            except ValueError as exc:
                raise GeminiError("Список моделей Gemini вернул неверные данные.") from exc
        finally:
            response.close()
        if not isinstance(data, dict):
            break
        for row in data.get("models") or ():
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").removeprefix("models/")
            if (_STABLE_FLASH_MODEL.fullmatch(name)
                    or _STABLE_FLASH_LITE_MODEL.fullmatch(name)):
                found.add(name)
        token = str(data.get("nextPageToken") or "")
        if not token:
            break

    def order(name):
        numbers = tuple(int(part) for part in re.findall(r"\d+", name))
        return (name.endswith("-flash"), numbers, name)

    return tuple(sorted(found, key=order))


# По этим словам ответ 400 опознаётся как «запрос не понравился», а не «ключ не
# тот». Google пишет их и в message, и в status.
_BLOCKED_MARKS = ("prohibited_content", "prohibited use policy", "input blocked",
                  "blocked", "safety", "sensitive words", "block_reason")


def _is_blocked(text: str) -> bool:
    low = str(text or "").lower()
    return any(mark in low for mark in _BLOCKED_MARKS)


def _answered(exc: BaseException) -> bool:
    """Успел ли сервер принять запрос, ответа которого мы не дождались.

    Таймаут ЧТЕНИЯ значит, что тело ушло и модель над ним уже работала: такой
    запрос Google засчитал в суточный лимит, и повторять его — платить второй
    раз за тот же вопрос. Таймаут соединения и обрыв до отправки — другое
    дело: там не дошло ничего, и ретрай уместен."""
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return False
    return isinstance(exc, (requests.exceptions.ReadTimeout,
                            requests.exceptions.ChunkedEncodingError))


def _extract_text(data: Any) -> str:
    """Текст ответа из тела Interactions API.

    Штатная форма — steps[].content[].text у шага model_output. Но рядом живёт
    старый generateContent с candidates[].content.parts[].text, и обе формы
    время от времени меняются, поэтому вместо жёсткого пути обходим дерево и
    собираем все текстовые куски: лишнего в ответе всё равно нет, а поломка от
    переезда поля дороже, чем эта пара строк.
    """
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            # Текстовый кусок: {"type": "text", "text": "..."} либо {"text": "..."}.
            txt = node.get("text")
            if isinstance(txt, str) and txt:
                out.append(txt)
            for key, val in node.items():
                if key != "text":
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return "\n".join(out).strip()


def _json_from_text(text: str) -> Any:
    """JSON из ответа модели.

    С response_format приходит чистый JSON, но модель изредка оборачивает его в
    ```json … ``` — снимаем ограду и берём кусок от первой скобки до последней.
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = t.find(opener), t.rfind(closer)
        if a >= 0 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except Exception:
                continue
    raise GeminiError("Gemini вернул не JSON")


class GeminiClient:
    """Один логический вопрос — один вызов generate_json.

    HTTP-попыток у него может быть несколько после таймаута или 5xx; каждая
    такая попытка считается Google отдельным запросом. Клиент потокобезопасен:
    троттлинг общий, поэтому несколько потоков вместе не превысят RPM.

    stopped — необязательная функция «пора прекращать»: проверяется перед
    отправкой и во время пауз, чтобы кнопка «Стоп» на вкладке не ждала
    минутного ретрая.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL,
                 session: Optional[requests.Session] = None,
                 rpm: Optional[int] = None, timeout: float = READ_TIMEOUT,
                 max_retries: int = 4,
                 log: Optional[Callable[[str], None]] = None,
                 stopped: Optional[Callable[[], bool]] = None,
                 thinking: str = THINKING_LEVEL,
                 board: Optional[QuotaBoard] = None,
                 daily_limits: Optional[dict] = None):
        self.api_key = (api_key or "").strip()
        self.model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.thinking = thinking_level(thinking, self.model)
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self._log = log
        self._stopped = stopped
        # Не задан явно — берём по модели: у Flash потолок втрое ниже, чем у
        # Flash-Lite, и общий интервал загонял бы её в 429 на каждой пачке.
        self._rpm_override = None if rpm is None else max(1, int(rpm))
        self._interval = self._model_interval(self.model)
        self._model_lock = threading.Lock()
        self._terminal_quota = ""
        # Доска квот общая на все клиенты одного ключа: троттлинг, исчерпанные
        # модели и память между прогонами живут там (см. gemini_quota).
        self.board = board or QuotaBoard(self.api_key, daily_limits)
        # Сколько запросов сделали — вкладке есть что показать пользователю,
        # когда он подбирается к суточному потолку бесплатного тарифа. spent
        # считает ВСЕ отправленные тела, включая отброшенные сервером: именно
        # из них складывается разница между «13 вопросов» и «47 запросов».
        self.requests_made = 0
        self.spent: Counter = Counter()

    # ── служебное ────────────────────────────────────────────────────────────
    @property
    def configured(self) -> bool:
        """Есть ли с чем идти в сеть (ключ введён)."""
        return bool(self.api_key)

    def log(self, msg: str) -> None:
        if self._log:
            try:
                self._log(msg)
            except Exception:  # noqa: BLE001 — лог не должен ронять работу
                pass

    def stopped(self) -> bool:
        if self._stopped is None:
            return False
        try:
            return bool(self._stopped())
        except Exception:  # noqa: BLE001
            return False

    def _sleep(self, seconds: float) -> None:
        """Пауза, которую можно прервать «Стопом» (спим четвертями секунды)."""
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self.stopped():
                return
            time.sleep(min(0.25, end - time.monotonic()))

    def _model_interval(self, model: str) -> float:
        rpm = self._rpm_override
        if rpm is None:
            rpm = MODEL_RPM.get(
                model, 5 if str(model).endswith("-flash") else FREE_RPM)
        return 60.0 / max(1, int(rpm))

    def _throttle(self, model: str = "") -> None:
        """Держит расстояние между запросами: бесплатный тариф считает RPM."""
        model = str(model or self.model)
        wait = self.board.reserve(model, self._model_interval(model))
        if wait > 0:
            self._sleep(wait)

    # ── запрос ───────────────────────────────────────────────────────────────
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
            raise GeminiAuthError("Не введён ключ Gemini API")
        while True:
            with self._model_lock:
                if self._terminal_quota:
                    raise GeminiQuotaError(self._terminal_quota)
                model, thinking = self.model, self.thinking
            if self.board.exhausted(model):
                # Про исчерпанную квоту уже известно — с прошлого прогона или
                # от соседнего клиента. Запрос не отправляем вовсе: раньше на
                # это выяснение уходил десяток отброшенных 429 подряд.
                self._switch(model, f"Gemini: квота {model} на сегодня "
                                    "исчерпана (известно из прошлых запросов)")
                continue
            body = {
                "model": model,
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
            if thinking == "high" and isinstance(prompt, str):
                # Interactions held even a trivial high-thinking request until
                # the read timeout. The supported GenerateContent endpoint
                # answered the same model/level in seconds in a live probe.
                body = {
                    "model": model,
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "thinkingConfig": {"thinkingLevel": "HIGH"},
                        "responseMimeType": "application/json",
                        "responseSchema": _generate_schema(schema),
                    },
                }
            try:
                return _json_from_text(_extract_text(self._post(body)))
            except _ModelChanged:
                continue
            except GeminiQuotaError as exc:
                self._switch(model, str(exc))

    def _switch(self, model: str, why: str) -> None:
        """Переходит на следующую живую модель.

        Заменить нечем — это конец: дальше клиент сразу отвечает квотой, не
        трогая сеть. Соседний поток мог переключить модель раньше — тогда
        просто уходим, второй раз спускаться по списку незачем."""
        with self._model_lock:
            if self.model != model:
                return
            next_model = next((name for name in fallback_models(model)
                               if not self.board.exhausted(name)), None)
            if next_model is None:
                self._terminal_quota = why
                raise GeminiQuotaError(why)
            self.model = next_model
            self.thinking = thinking_level(self.thinking, next_model)
            self._interval = self._model_interval(next_model)
        self.log(f"Gemini: квота {model} исчерпана, "
                 f"переключаюсь на {next_model}.")

    def _post(self, body: dict) -> Any:
        """POST с ретраями. Возвращает разобранное тело ответа."""
        headers = {"x-goog-api-key": self.api_key,
                   "Content-Type": "application/json"}
        delay = 2.0
        last = ""
        model = str(body.get("model") or self.model)
        if "contents" in body:
            url = f"{API_ROOT}/models/{model}:generateContent"
            payload = {key: value for key, value in body.items() if key != "model"}
        else:
            url, payload = INTERACTIONS_URL, body
        for attempt in range(self.max_retries):
            if self.stopped():
                raise GeminiError("Отменено")
            self._throttle(model)
            if self.stopped():
                raise GeminiError("Отменено")
            # Восемь рабочих потоков заранее занимают будущие слоты. Если
            # первый из них узнал, что квота модели кончилась, остальные не
            # должны по очереди досылать старые тела и тратить ещё 7 RPD.
            with self._model_lock:
                if self._terminal_quota:
                    raise GeminiQuotaError(self._terminal_quota)
                if model != self.model:
                    raise _ModelChanged()
            try:
                resp = self.session.post(
                    url, headers=headers, json=payload,
                    timeout=(CONNECT_TIMEOUT, self.timeout))
            except Exception as e:  # noqa: BLE001 — сеть отвалилась, пробуем ещё
                if _answered(e):
                    # Ответа мы не дождались, но сервер запрос ПРИНЯЛ и в
                    # суточный лимит его засчитал. Повторять такое — платить
                    # за один вопрос четырежды: отдаём ошибку сразу, вкладка
                    # возьмёт следующий тайтл.
                    self.spent[model] += 1
                    self.requests_made += 1
                    self.board.spend(model)
                    raise GeminiUnavailableError(
                        f"Gemini не ответил за {self.timeout:.0f} с "
                        "(запрос всё равно засчитан в суточный лимит)") from e
                last = str(e)
                self.log(f"Gemini: сеть недоступна ({e}), попытка "
                         f"{attempt + 1} из {self.max_retries}")
                self._sleep(delay)
                delay *= 2
                continue
            self.spent[model] += 1
            code = int(getattr(resp, "status_code", 0) or 0)
            if code != 429 and code < 500:
                # В суточный лимит идут только ОБСЛУЖЕННЫЕ запросы: 429 сервер
                # отклоняет, 5xx не его вина. Считая их, приложение показывало
                # больше, чем видит Google, — и своя же проверка потолка
                # срабатывала раньше времени.
                self.requests_made += 1
                self.board.spend(model)
            text = getattr(resp, "text", "") or ""
            if 200 <= code < 300:
                try:
                    return resp.json()
                except Exception:
                    return _json_from_text(text)
            if code == 400 and _is_blocked(text):
                # «Запрос содержит недопустимые слова» — беда одного текста, а
                # не ключа: следующий запрос той же моделью пройдёт как ни в чём
                # не бывало.
                raise GeminiBlockedError(error_message(text, code))
            if code in (400, 401, 403):
                # 400 сюда же: у Gemini это «ключ не той формы» и «модель не
                # существует» — ретраить бессмысленно, надо править настройки.
                raise GeminiAuthError(error_message(text, code))
            if code == 429:
                if is_quota(text):
                    # Квота модели исчерпана. Повторять такой 429 четыре раза
                    # нельзя: каждый повтор сам попадает в RPD и на скрине
                    # получается 23 / 20. Разовый rate-limit без слова quota
                    # по-прежнему пережидаем по Retry-After ниже.
                    #
                    # Запоминаем исчерпанную модель на сутки: следующий прогон
                    # не должен выяснять то же самое заново.
                    self.board.mark(model, text)
                    raise GeminiQuotaError(error_message(text, code))
                wait = retry_after(resp, text, default=delay)
                last = error_message(text, code)
                self.log(f"Gemini: лимит бесплатного тарифа, жду {wait:.0f} с "
                         f"(попытка {attempt + 1} из {self.max_retries})")
                self._sleep(wait)
                delay = min(delay * 2, 60.0)
                continue
            if code >= 500:
                last = error_message(text, code)
                self.log(f"Gemini: сервер ответил {code}, повтор через "
                         f"{delay:.0f} с")
                self._sleep(delay)
                delay *= 2
                continue
            raise GeminiError(error_message(text, code))
        # Ретраи кончились. Отдельным типом — только квота: вкладке надо
        # сказать пользователю не «ошибка», а «на сегодня хватит».
        if "429" in last or "RESOURCE_EXHAUSTED" in last or "quota" in last.lower():
            raise GeminiQuotaError(last or "Gemini: исчерпана квота")
        raise GeminiUnavailableError(last or "Gemini не ответил")
