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
#   • модель по умолчанию — Flash-Lite; актуальные лимиты показывает AI Studio;
#   • запросы троттлятся по RPM ЛОКАЛЬНО, до отправки: упереться в 429 и потом
#     ждать — значит потратить лимит впустую;
#   • минутный 429 пережидаем по Retry-After, после двух серверных отказов
#     переходим на другую модель; перегрузка помнится только в этом прогоне;
#   • исчерпанная модель запоминается НА СУТКИ (gemini_quota.QuotaBoard): иначе
#     каждый следующий прогон выяснял это заново десятком отброшенных запросов;
#   • таймаут чтения не повторяется, поскольку сервер мог принять запрос;
#     ошибки 400/5xx и таймаут включаем в локальную оценку расхода квоты.
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

from gemini_quota import (QuotaBoard, error_message as error_message,
                          is_quota as is_quota, retry_after as retry_after)
from gemini_transport import request_fault

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
#
# Gemma 4 — открытые модели, которые Google раздаёт через тот же API и ключ.
# Они слабее любого Gemini Flash, поэтому стоят в начале списка: при
# исчерпании квоты клиент сперва спускается к ним (см. fallback_models). Зато
# квота у них своя и большая (~15 RPM и ~1500 запросов в сутки). 26B-A4B —
# смесь экспертов с 4B активных параметров, она слабее плотной 31B.
GEMMA_MODELS = (
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
)
MODELS = GEMMA_MODELS + (
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
    "gemma-4-26b-a4b-it": 12,
    "gemma-4-31b-it": 12,
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
# Gemma знает только «выключено» (minimal) и «включено» (high); на low и
# medium API отвечает 400 «Thinking level is not supported for this model».
GEMMA_LEVELS = ("minimal", "high")


def is_gemma(model: str) -> bool:
    return str(model or "").strip().lower().startswith("gemma-")


def model_rank(name: str) -> tuple:
    """Порядок от слабой модели к сильной: Gemma ниже любой Gemini."""
    numbers = tuple(int(n) for n in re.findall(r"\d+", name))
    return (not is_gemma(name), numbers)


def model_thinking_levels(model: str = "") -> tuple[str, ...]:
    """Уровни рассуждения, которые принимает эта модель."""
    name = str(model or "").strip().lower()
    if is_gemma(name):
        return GEMMA_LEVELS
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
    if level in allowed:
        return level
    # Ближайший доступный; при равенстве — нижний (дешевле по токенам).
    want = THINKING_LEVELS.index(level)
    return min(allowed, key=lambda name: (abs(THINKING_LEVELS.index(name) - want),
                                          THINKING_LEVELS.index(name)))


def fallback_models(model: str) -> tuple[str, ...]:
    """При исчерпании квоты: модели слабее, затем модели сильнее."""
    choices = list(MODELS)
    if model not in choices:
        choices.append(model)
        choices.sort(key=model_rank)
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


class GeminiCoolingError(GeminiDownError, GeminiUnavailableError):
    """Все доступные модели на паузе после перегрузки (503 «high demand»).

    Сеть не трогается, и клиент сам вернётся к модели после паузы (recover),
    поэтому для генератора это временный сбой: тайтл уходит на повтор, а род
    вопросов не выключается. Раньше один 503 при выключенной замене модели
    закрывал мангу до конца прогона, и пак выходил неполным."""


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


class _ModelUnavailable(GeminiUnavailableError):
    """Повторные серверные отказы: пропускаем модель на время паузы."""


class _EndpointUnavailable(GeminiUnavailableError):
    """GenerateContent failed; try the supported Interactions endpoint."""


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
        return (not is_gemma(name), name.endswith("-flash"), numbers, name)

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

    После таймаута чтения или обрыва ответа сервер мог обработать запрос:
    повтор способен расходовать квоту ещё раз. Таймаут соединения не означает
    отправку тела, поэтому такой запрос допустимо повторить."""
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return False
    return isinstance(exc, (requests.exceptions.ReadTimeout,
                            requests.exceptions.ChunkedEncodingError))


def _json_from_response(data: Any) -> Any:
    """JSON из тела ответа: весь текст, а если он не разбирается — по кускам.

    Рядом с ответом модели в теле бывают служебные текстовые куски (сводка
    рассуждения, шаги Interactions). Склеенные, они ломали разбор целой пачки
    проверок, хотя сам ответ модели был цельным JSON."""
    try:
        return _json_from_text(_extract_text(data))
    except GeminiError:
        pieces = _text_pieces(data)
        for piece in reversed(pieces):
            try:
                return _json_from_text(piece)
            except GeminiError:
                continue
        preview = " | ".join(" ".join(p[:120].split()) for p in pieces[-2:])
        raise GeminiError(f"Gemini вернул не JSON ({preview or 'пустой ответ'})") from None


def _text_pieces(data: Any) -> list[str]:
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            txt = node.get("text")
            if isinstance(txt, str) and txt.strip():
                out.append(txt)
            for key, val in node.items():
                if key != "text":
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return out


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
                 daily_limits: Optional[dict] = None,
                 allow_model_fallback: bool = True,
                 fallback_gemma: bool = True):
        self.api_key = (api_key or "").strip()
        self.model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.primary_model = self.model
        self.allow_model_fallback = bool(allow_model_fallback)
        # False — замена идёт только по Gemini: визуальные проверки и отрывки
        # не спускаются на Gemma (31B не меняется на 26B, звука Gemma не слышит).
        self.fallback_gemma = bool(fallback_gemma)
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
        self._terminal_down = ""
        # Доска квот общая на все клиенты одного ключа: троттлинг, исчерпанные
        # модели и память между прогонами живут там (см. gemini_quota).
        self.board = board or QuotaBoard(self.api_key, daily_limits)
        # spent — все HTTP-попытки; requests_made — оценка расхода квоты,
        # включая 5xx и таймаут чтения. Коды ответов считаются независимо:
        # успешный HTTP ещё не гарантирует пригодный вопрос.
        self.requests_made = 0
        self.spent: Counter = Counter()
        self.response_codes: Counter = Counter()
        self.image_generate_content = False
        self.prefer_interactions = False

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
            time.sleep(max(0.0, min(0.25, end - time.monotonic())))

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
    from gemini_client_generation import generate_json, _switch

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
        generate_content = "contents" in body
        if generate_content:
            url = f"{api.API_ROOT}/models/{model}:generateContent"
            payload = {key: value for key, value in body.items() if key != "model"}
        else:
            url, payload = api.INTERACTIONS_URL, body
        from gemini_client_recovery import recover
        for attempt in range(self.max_retries):
            recover(self)
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
                    raise api.GeminiCoolingError(self._terminal_down)
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
            if code == 400 and request_fault(text):
                # A malformed image/schema affects this job, not the API key or
                # other question kinds. Do not retry the same invalid payload.
                raise api.GeminiError(api.error_message(text, code))
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
                if generate_content:
                    raise api._EndpointUnavailable(last)
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
