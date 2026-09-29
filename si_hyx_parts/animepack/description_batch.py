"""Combine independent description translations into one Gemini request."""
from __future__ import annotations

import threading
from concurrent.futures import Future
from dataclasses import dataclass, field

from gemini_api import GeminiError

MAX_INPUT_CHARS = 32000
COLLECT_SECONDS = 0.8


@dataclass(eq=False)
class _Job:
    source: str
    language: str
    future: Future = field(default_factory=Future)


class DescriptionBatcher:
    def __init__(self, client, max_jobs=8, stopped=lambda: False):
        self.client, self.max_jobs, self.stopped = client, max(1, max_jobs), stopped
        self._condition = threading.Condition()
        self._pending: list[_Job] = []
        self._sending = False

    def translate(self, source: str, language: str) -> str:
        job = _Job(source[:4000], language)
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
                lambda: len(self._pending) >= self.max_jobs or self.stopped(),
                timeout=COLLECT_SECONDS)
            batch = [self._pending.pop(0)]
            size = len(batch[0].source)
            while self._pending and len(batch) < self.max_jobs:
                next_job = self._pending[0]
                if size + len(next_job.source) > MAX_INPUT_CHARS:
                    break
                batch.append(self._pending.pop(0))
                size += len(next_job.source)
        try:
            if self.stopped():
                raise GeminiError("Отменено")
            from .description_question import TRANSLATION_SCHEMA, translation_prompt
            if len(batch) == 1:
                job = batch[0]
                answer = self.client.generate_json(
                    translation_prompt(job.source, job.language),
                    TRANSLATION_SCHEMA)
                job.future.set_result(answer["text"])
                return
            answer = self.client.generate_json(*_request(batch))
            for job, text in zip(batch, _answers(answer, len(batch))):
                job.future.set_result(text)
        except Exception as error:  # errors belong to all jobs in the request
            for job in batch:
                if not job.future.done():
                    job.future.set_exception(error)


def _request(batch):
    from .description_question import translation_prompt
    prompts = [
        "Translate each numbered description independently. Return exactly "
        "one result per id. Do not mix facts, titles, or languages between ids."
    ]
    for index, job in enumerate(batch):
        prompts.append(f"\n<task id={index}>\n"
                       + translation_prompt(job.source, job.language,
                                            batched=True)
                       + "\n</task>")
    row = {"type": "object", "properties": {
        "id": {"type": "integer"}, "text": {"type": "string"}},
        "required": ["id", "text"]}
    schema = {"type": "object", "properties": {"results": {
        "type": "array", "items": row,
        "minItems": len(batch), "maxItems": len(batch)}},
        "required": ["results"]}
    return "\n".join(prompts), schema


def _answers(response, count):
    rows = response.get("results") if isinstance(response, dict) else None
    if not isinstance(rows, list) or len(rows) != count:
        raise GeminiError("Gemini вернула неполную пачку описаний")
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            raise GeminiError("Gemini вернула неверное описание")
        index, value = row.get("id"), row.get("text")
        if (type(index) is not int or not 0 <= index < count or index in found
                or not isinstance(value, str)):
            raise GeminiError("Gemini перепутала id описаний")
        found[index] = value
    return [found[index] for index in range(count)]
