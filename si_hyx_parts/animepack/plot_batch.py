# -*- coding: utf-8 -*-
"""До трёх независимых страниц сюжета в одном запросе Gemini."""
from __future__ import annotations

import threading
from concurrent.futures import Future
from dataclasses import dataclass, field

from gemini_api import GeminiError

MAX_PAGES = 3
COLLECT_SECONDS = 1.0


@dataclass(eq=False)
class _Job:
    prompt: str
    schema: dict
    temperature: float
    future: Future = field(default_factory=Future)


class PlotBatcher:
    def __init__(self, client, stopped=lambda: False):
        self.client = client
        self.stopped = stopped
        self._condition = threading.Condition()
        self._pending: list[_Job] = []
        self._sending = False

    def generate_json(self, prompt, schema, temperature=0.6):
        job = _Job(str(prompt), schema, float(temperature))
        with self._condition:
            self._pending.append(job)
            self._condition.notify_all()
        while not job.future.done():
            with self._condition:
                if self.stopped() and job in self._pending:
                    self._pending.remove(job)
                    job.future.set_exception(GeminiError("Отменено"))
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
                lambda: len(self._pending) >= MAX_PAGES or self.stopped(),
                timeout=COLLECT_SECONDS)
            first = self._pending.pop(0)
            batch = [first]
            while self._pending and len(batch) < MAX_PAGES:
                next_job = self._pending[0]
                if (next_job.schema != first.schema
                        or next_job.temperature != first.temperature):
                    break
                batch.append(self._pending.pop(0))
        try:
            if self.stopped():
                raise GeminiError("Отменено")
            if len(batch) == 1:
                first.future.set_result(self.client.generate_json(
                    first.prompt, first.schema,
                    temperature=first.temperature))
                return
            prompt, schema = _request(batch)
            response = self.client.generate_json(
                prompt, schema, temperature=first.temperature)
            for job, answer in zip(batch, _answers(response, len(batch))):
                job.future.set_result(answer)
        except Exception as error:  # noqa: BLE001 — ошибку модели видят все ожидающие
            for job in batch:
                if not job.future.done():
                    job.future.set_exception(error)


def _request(batch):
    prompts = [
        "Сделай каждое задание независимо. Страница и название с одним id "
        "не относятся к другим id. Для каждого id верни его items по "
        "инструкции задания. Не смешивай сюжет и ответы разных произведений."
    ]
    for index, job in enumerate(batch):
        prompts.append(f"\n<задание id={index}>\n{job.prompt}\n</задание>")
    child = job.schema["properties"]["items"]
    schema = {"type": "object", "properties": {"results": {
        "type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "integer"}, "items": child,
        }, "required": ["id", "items"]},
        "minItems": len(batch), "maxItems": len(batch),
    }}, "required": ["results"]}
    return "\n".join(prompts), schema


def _answers(response, count):
    rows = response.get("results") if isinstance(response, dict) else None
    if not isinstance(rows, list) or len(rows) != count:
        raise GeminiError("Gemini вернула неполную пачку сюжетных вопросов")
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            raise GeminiError("Gemini вернула неверный сюжетный ответ")
        index = row.get("id")
        if (type(index) is not int or not 0 <= index < count or index in found
                or not isinstance(row.get("items"), list)):
            raise GeminiError("Gemini перепутала id сюжетных страниц")
        found[index] = {"items": row["items"]}
    return [found[index] for index in range(count)]


def initialize(generator):
    generator._plot_batch_lock = threading.Lock()
    generator._plot_batches = {}


def client_for(generator, client):
    from .generation_priority import parallel_limit
    if parallel_limit(generator.s) < 2:
        return client
    lock = getattr(generator, "_plot_batch_lock", None)
    if lock is None:
        return client
    with lock:
        batcher = generator._plot_batches.get(id(client))
        if batcher is None:
            batcher = PlotBatcher(client, generator.stopped)
            generator._plot_batches[id(client)] = batcher
    return batcher
