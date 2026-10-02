# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Объединяет параллельные проверки изображений в один запрос Gemini.

Отдельного потока нет: один из ожидающих работников отправляет пачку,
остальные получают свои вердикты по id. Одиночная проверка не ждёт других
бесконечно; ошибка пачки не запускает дорогие одиночные повторы.

Предохранитель: когда сервер DOWN_AFTER запросов подряд не отвечает (503 «high
demand» после всех повторов или таймаут), проверки до конца прогона сразу
получают GeminiDownError, не трогая сеть. Иначе каждая пачка ждала бы минуты,
а пока все рабочие потоки стоят в очереди к Gemini, другие роды вопросов не
качаются вовсе: живой прогон собрал 4 вопроса из 144 за 14 минут.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future
from dataclasses import dataclass, field

from gemini_api import GeminiDownError, GeminiError, GeminiUnavailableError

MAX_IMAGES = 4
MAX_INPUT = 16_000_000  # запас до ограничения 20 МБ с учётом JSON
COLLECT_SECONDS = 0.25
# Столько запросов подряд без ответа — и Gemini для картинок до конца прогона
# считается недоступным. Каждый такой запрос — это уже пять попыток 503 или
# полный таймаут, так что двух хватает с запасом.
DOWN_AFTER = 2
# Ответа на проверку картинки ждём меньше, чем на пересказ сюжета: рассуждение
# здесь минимальное, и минута без ответа значит перегруженный сервер.
READ_TIMEOUT = 60.0


@dataclass(eq=False)
class _Job:
    parts: list
    schema: dict
    future: Future = field(default_factory=Future)

    @property
    def size(self):
        return sum(len(str(part.get("data") or part.get("text") or ""))
                   for part in self.parts)


class VisualCheckBatcher:
    def __init__(self, client, stopped=lambda: False, *,
                 max_images=MAX_IMAGES, collect_seconds=COLLECT_SECONDS):
        self.client = client
        self.stopped = stopped
        self.max_images = max(1, int(max_images))
        self.collect_seconds = max(0.0, float(collect_seconds))
        self._condition = threading.Condition()
        self._pending: list[_Job] = []
        self._sending = False
        self._misses = 0
        self.down = ""

    def check(self, parts, schema):
        job = _Job(parts, schema)
        with self._condition:
            self._pending.append(job)
            self._condition.notify_all()
        while not job.future.done():
            with self._condition:
                if self.stopped() and job in self._pending:
                    self._pending.remove(job)
                    job.future.set_exception(GeminiError("Отменено"))
                    self._condition.notify_all()
                if job.future.done():
                    break
                if self._sending:
                    self._condition.wait(0.1)
                    continue
                self._sending = True
            try:
                self._send_next()
            finally:
                with self._condition:
                    self._sending = False
                    self._condition.notify_all()
        return job.future.result()

    def _send_next(self):
        with self._condition:
            self._condition.wait_for(
                lambda: len(self._pending) >= self.max_images or self.stopped(),
                timeout=self.collect_seconds)
            batch, size = [], 0
            while self._pending and len(batch) < self.max_images:
                job = self._pending[0]
                if job.size > MAX_INPUT:
                    self._pending.pop(0)
                    job.future.set_exception(GeminiError(
                        "Изображение слишком большое для проверки Gemini"))
                    continue
                if batch and size + job.size > MAX_INPUT:
                    break
                self._pending.pop(0)
                batch.append(job)
                size += job.size
        if not batch:
            return
        try:
            if self.stopped():
                raise GeminiError("Отменено")
            if self.down:
                raise GeminiDownError(self.down)
            if len(batch) == 1:
                job = batch[0]
                verdict = self.client.generate_json(
                    job.parts, job.schema, temperature=0.0)
                job.future.set_result(verdict)
            else:
                parts, schema = _request(batch)
                response = self.client.generate_json(parts, schema,
                                                     temperature=0.0)
                verdicts = _verdicts(response, batch)
                for index, job in enumerate(batch):
                    job.future.set_result(verdicts[index])
        except Exception as error:  # noqa: BLE001 — передаём отказ всем ожидающим
            error = self._note_failure(error)
            for job in batch:
                if not job.future.done():
                    job.future.set_exception(error)
        else:
            self._misses = 0

    def _note_failure(self, error):
        """Считает запросы подряд без ответа; на пороге — GeminiDownError."""
        if not isinstance(error, GeminiUnavailableError):
            if not isinstance(error, GeminiDownError):
                self._misses = 0    # сервер ответил — пусть и неудачно
            return error
        self._misses += 1
        if self._misses >= DOWN_AFTER and not self.down:
            self.down = (f"{self._misses} запроса подряд без ответа, "
                         f"последний: {error}")
        return GeminiDownError(self.down) if self.down else error


def _request(batch):
    parts = [{"type": "text", "text": (
        "Проверь каждое изображение независимо по инструкции перед ним. "
        "Названия и метки относятся только к изображению с тем же id; "
        "не сравнивай разные изображения между собой. Верни results: "
        "по одному вердикту с целочисленным id для каждого изображения. "
        "Для манги mixed_anime=false: эта проверка относится к артам Pixiv.") }]
    properties, required = {}, {"id"}
    for index, job in enumerate(batch):
        parts.append({"type": "text", "text": f"Изображение id={index}"})
        parts.extend(job.parts)
        properties.update(job.schema["properties"])
        required.update(job.schema["required"])
    properties["id"] = {"type": "integer"}
    schema = {"type": "object", "properties": {"results": {
        "type": "array", "items": {"type": "object",
        "properties": properties, "required": sorted(required)},
    }}, "required": ["results"]}
    return parts, schema


def _verdicts(response, batch):
    count = len(batch)
    rows = response.get("results") if isinstance(response, dict) else None
    if not isinstance(rows, list) or len(rows) != count:
        raise GeminiError("Gemini вернула неполную пачку вердиктов")
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            raise GeminiError("Gemini вернула неверный вердикт")
        index = row.get("id")
        if (type(index) is not int or not 0 <= index < count or index in found
                or type(row.get("accept")) is not bool
                or type(row.get("has_title_text")) is not bool
                or not isinstance(row.get("reason"), str)
                or ("mixed_anime" in row and type(row["mixed_anime"]) is not bool)
                or not set(batch[index].schema["required"]).issubset(row)):
            raise GeminiError("Gemini вернула неверные id или поля вердиктов")
        found[index] = {key: value for key, value in row.items() if key != "id"}
    return found


def initialize(generator):
    generator._visual_batch_lock = threading.Lock()
    generator._visual_batches = {}


def request(generator, client, parts, schema):
    lock = getattr(generator, "_visual_batch_lock", None)
    if lock is None:
        return client.generate_json(parts, schema, temperature=0.0)
    # Одинаковые модель, рассуждение и доска квот — один запрос даже для
    # смеси Pixiv и манги. Разные выбранные модели остаются раздельными.
    # Multi-page selection and multi-crop review use different nested arrays.
    # Keep these stages separate so their required fields cannot get mixed.
    properties = schema.get("properties", {})
    stage = next((name for name in ("candidates", "scenes") if name in properties), "visual")
    key = (id(getattr(client, "board", client)),
           str(getattr(client, "model", "")),
           str(getattr(client, "thinking", "")), stage)
    with lock:
        batcher = generator._visual_batches.get(key)
        if batcher is None:
            batcher = VisualCheckBatcher(client, generator.stopped)
            generator._visual_batches[key] = batcher
    return batcher.check(parts, schema)
