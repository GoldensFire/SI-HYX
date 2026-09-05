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
# Используется НОВЫЙ Interactions API (/v1beta/interactions), а не устаревающий
# models/{model}:generateContent: только через него доступны модели 3.x. Форма
# ответа у него другая (steps → content → text), поэтому текст достаём
# терпимо — см. _extract_text, там же разобран и старый формат.
#
# Рассчитан на БЕСПЛАТНЫЙ тариф, и это определяет всё поведение:
#   • модель по умолчанию — Flash-Lite: у неё самые высокие бесплатные лимиты
#     (порядка 15 запросов в минуту и 1000 в сутки против 10/250 у Flash);
#   • запросы троттлятся по RPM ЛОКАЛЬНО, до отправки: упереться в 429 и потом
#     ждать — значит потратить лимит впустую;
#   • 429 и 5xx переживаются ретраями с паузой, которую называет сам сервер
#     (RetryInfo.retryDelay / заголовок Retry-After).
#
# Ключ — ВСЕГДА пользовательский (вводится в настройках вкладки). Зашивать
# общий ключ в открытое GPL-приложение нельзя: его вытащат из бинаря, а платить
# по счёту будет автор.
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable, Optional

import requests

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
INTERACTIONS_URL = f"{API_ROOT}/interactions"

# Модель по умолчанию. Flash-Lite — не «похуже», а «для потока»: наша задача
# (разложить готовый список ответов по франшизам) — классификация, а не
# рассуждение, и упирается она в лимит ЗАПРОСОВ, а не в интеллект модели.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
# Что предложить в выпадающем списке настроек — ровно два осмысленных выбора:
# рабочая лошадка с самой высокой бесплатной квотой и «подумать получше» для
# паков, где первая путается в редких тайтлах. Промежуточные версии (3.1
# Flash-Lite, 3.5 Flash) не предлагаем: каждая строго уступает одной из этих
# двух и там, и там — при вчетверо меньшей суточной квоте у Flash.
MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
)
# Запросов в минуту. Держимся ниже настоящего потолка бесплатного тарифа (около
# 15 у Flash-Lite и 10 у Flash): лимит считает сервер по своим часам, и
# попадание в 429 стоит дороже, чем лишние секунды ожидания.
FREE_RPM = 12
MODEL_RPM = {
    "gemini-3.5-flash-lite": 12,
    "gemini-3.6-flash": 8,
}
# «Размышления» модели для классификации — чистый расход выходных токенов и
# секунд. Совсем выключить их на Flash-Lite нельзя, минимум — этот уровень.
THINKING_LEVEL = "minimal"

_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"?(\d+(?:\.\d+)?)s')


class GeminiError(RuntimeError):
    """Общая ошибка обращения к Gemini."""


class GeminiAuthError(GeminiError):
    """Ключ не принят (нет, просрочен, не тот проект) — ретраить бессмысленно."""


class GeminiQuotaError(GeminiError):
    """Кончилась квота бесплатного тарифа (429 после всех ретраев)."""


class GeminiBlockedError(GeminiError):
    """Модель отказалась разбирать ЭТОТ запрос (правила о недопустимом
    содержимом).

    Отдельный тип нарочно: с ключом и квотой всё в порядке, беда ровно в одном
    тексте — пересказ серии про войну или расправу Gemini не берёт. Такой ответ
    значит «возьми следующий тайтл», а не «выключай всю затею» (раньше это был
    GeminiAuthError, и один неудачный пересказ отключал вопросы по сюжету на
    весь прогон)."""


# По этим словам ответ 400 опознаётся как «запрос не понравился», а не «ключ не
# тот». Google пишет их и в message, и в status.
_BLOCKED_MARKS = ("prohibited_content", "prohibited use policy", "input blocked",
                  "blocked", "safety", "sensitive words", "block_reason")


def _is_blocked(text: str) -> bool:
    low = str(text or "").lower()
    return any(mark in low for mark in _BLOCKED_MARKS)


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
    """Один запрос — один вызов generate_json. Потокобезопасен: троттлинг
    общий на клиента, поэтому один клиент можно отдать нескольким потокам, и
    вместе они не превысят RPM.

    stopped — необязательная функция «пора прекращать»: проверяется перед
    отправкой и во время пауз, чтобы кнопка «Стоп» на вкладке не ждала
    минутного ретрая.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL,
                 session: Optional[requests.Session] = None,
                 rpm: Optional[int] = None, timeout: float = 120.0,
                 max_retries: int = 4,
                 log: Optional[Callable[[str], None]] = None,
                 stopped: Optional[Callable[[], bool]] = None):
        self.api_key = (api_key or "").strip()
        self.model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self._log = log
        self._stopped = stopped
        # Не задан явно — берём по модели: у Flash потолок вдвое ниже, чем у
        # Flash-Lite, и общий интервал загонял бы её в 429 на каждой пачке.
        if rpm is None:
            rpm = MODEL_RPM.get(self.model, FREE_RPM)
        self._interval = 60.0 / max(1, int(rpm))
        self._lock = threading.Lock()
        self._next_at = 0.0
        # Сколько запросов сделали — вкладке есть что показать пользователю,
        # когда он подбирается к суточному потолку бесплатного тарифа.
        self.requests_made = 0

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

    def _throttle(self) -> None:
        """Держит расстояние между запросами: бесплатный тариф считает RPM."""
        with self._lock:
            wait = self._next_at - time.monotonic()
            self._next_at = max(self._next_at, time.monotonic()) + self._interval
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
        body = {
            "model": self.model,
            "input": prompt,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            },
            "generation_config": {
                "temperature": float(temperature),
                "thinking_level": THINKING_LEVEL,
            },
        }
        data = self._post(body)
        return _json_from_text(_extract_text(data))

    def _post(self, body: dict) -> Any:
        """POST с ретраями. Возвращает разобранное тело ответа."""
        headers = {"x-goog-api-key": self.api_key,
                   "Content-Type": "application/json"}
        delay = 2.0
        last = ""
        for attempt in range(self.max_retries):
            if self.stopped():
                raise GeminiError("Отменено")
            self._throttle()
            if self.stopped():
                raise GeminiError("Отменено")
            try:
                resp = self.session.post(INTERACTIONS_URL, headers=headers,
                                         json=body, timeout=self.timeout)
            except Exception as e:  # noqa: BLE001 — сеть отвалилась, пробуем ещё
                last = str(e)
                self.log(f"Gemini: сеть недоступна ({e}), попытка "
                         f"{attempt + 1} из {self.max_retries}")
                self._sleep(delay)
                delay *= 2
                continue
            self.requests_made += 1
            code = int(getattr(resp, "status_code", 0) or 0)
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
                raise GeminiBlockedError(_error_message(text, code))
            if code in (400, 401, 403):
                # 400 сюда же: у Gemini это «ключ не той формы» и «модель не
                # существует» — ретраить бессмысленно, надо править настройки.
                raise GeminiAuthError(_error_message(text, code))
            if code == 429:
                wait = _retry_after(resp, text, default=delay)
                last = _error_message(text, code)
                self.log(f"Gemini: лимит бесплатного тарифа, жду {wait:.0f} с "
                         f"(попытка {attempt + 1} из {self.max_retries})")
                self._sleep(wait)
                delay = min(delay * 2, 60.0)
                continue
            if code >= 500:
                last = _error_message(text, code)
                self.log(f"Gemini: сервер ответил {code}, повтор через "
                         f"{delay:.0f} с")
                self._sleep(delay)
                delay *= 2
                continue
            raise GeminiError(_error_message(text, code))
        # Ретраи кончились. Отдельным типом — только квота: вкладке надо
        # сказать пользователю не «ошибка», а «на сегодня хватит».
        if "429" in last or "RESOURCE_EXHAUSTED" in last or "quota" in last.lower():
            raise GeminiQuotaError(last or "Gemini: исчерпана квота")
        raise GeminiError(last or "Gemini не ответил")


def _retry_after(resp: Any, text: str, default: float = 2.0) -> float:
    """Сколько ждать после 429: сервер называет срок сам.

    Сначала заголовок Retry-After, потом RetryInfo.retryDelay в теле ошибки
    («21s»). Верхняя граница — минута: дольше ждать в интерактивной вкладке
    бессмысленно, лучше отдать пользователю сообщение о квоте.
    """
    try:
        raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
        if raw:
            return max(1.0, min(60.0, float(str(raw).strip())))
    except Exception:  # noqa: BLE001
        pass
    m = _RETRY_DELAY.search(text or "")
    if m:
        try:
            return max(1.0, min(60.0, float(m.group(1))))
        except ValueError:
            pass
    return max(1.0, min(60.0, default))


def _error_message(text: str, code: int) -> str:
    """Человеческое сообщение из тела ошибки Gemini (или просто код)."""
    try:
        data = json.loads(text or "")
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            msg = str(err.get("message") or "").strip()
            status = str(err.get("status") or "").strip()
            if msg:
                return f"Gemini {code}: {msg}" + (f" [{status}]" if status else "")
    except Exception:  # noqa: BLE001
        pass
    snippet = (text or "").strip().replace("\n", " ")[:200]
    return f"Gemini {code}" + (f": {snippet}" if snippet else "")
