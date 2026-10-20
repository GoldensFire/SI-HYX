# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Объединяет параллельные проверки изображений в один запрос Gemini.

Отдельного потока нет: один из ожидающих работников отправляет пачку,
остальные получают свои вердикты по id. Одиночная проверка не ждёт других
бесконечно; ошибка пачки не запускает дорогие одиночные повторы.

Предохранитель: когда сервер DOWN_AFTER запросов подряд не отвечает (503 «high
demand» после всех повторов или таймаут), проверки картинок встают на паузу
PAUSE_STEPS и до её конца сразу получают GeminiCoolingError, не трогая сеть.
Иначе каждая пачка ждала бы минуты, а пока все рабочие потоки стоят в очереди
к Gemini, другие роды вопросов не качаются вовсе: живой прогон собрал 4 вопроса
из 144 за 14 минут. После паузы идёт пробный запрос; тайтлы, сорвавшиеся на
паузе, ждут её конца (wait_seen). Раньше пауза длилась до конца прогона, и
минутный сбой Gemini стоил трети пака: кадры, Pixiv и манга выпадали, хотя
через пять минут модели снова отвечали. До конца прогона Gemini выключается,
только когда молчит дольше DOWN_TOTAL.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from collections import Counter
from dataclasses import dataclass, field

from gemini_api import GeminiCoolingError, GeminiDownError, GeminiError, GeminiUnavailableError

MAX_IMAGES = 4
MAX_INPUT = 16_000_000  # запас до ограничения 20 МБ с учётом JSON
COLLECT_SECONDS = 2.0
# Пока слот модели занят чужими запросами, пачка копится даром: раньше она
# закрывалась через 0,75 с и потом ещё ждала слот RPM, а картинки, пришедшие
# за это ожидание, уходили следующим запросом (47 проверок кадров по одной).
MAX_COLLECT_SECONDS = 12.0
# Столько запросов подряд без ответа — и проверки картинок встают на паузу.
# Каждый такой запрос — это уже пять попыток 503 или полный таймаут, так что
# двух хватает с запасом.
DOWN_AFTER = 2
# Паузы подряд: пробный запрос после паузы снова молчит — следующая длиннее.
PAUSE_STEPS = (120.0, 300.0, 600.0)
# Молчит дольше — Gemini для картинок выключается до конца прогона.
DOWN_TOTAL = 20 * 60.0
# Ответа на проверку картинки ждём меньше, чем на пересказ сюжета: рассуждение
# здесь минимальное, и минута без ответа значит перегруженный сервер.
READ_TIMEOUT = 60.0


_WAIT = threading.local()


def wait_reset():
    _WAIT.until = 0.0


def wait_seen():
    """Конец паузы, на которой сорвалась проверка этого потока (0 — не было)."""
    return getattr(_WAIT, "until", 0.0)


class VisualPause:
    """Общая на прогон пауза проверок картинок после молчания Gemini."""

    def __init__(self, log=None):
        self._lock = threading.Lock()
        self._log = log or (lambda message: None)
        self.misses = 0
        self.strikes = 0
        self.since = 0.0        # начало нынешней полосы молчания
        self.until = 0.0
        self.reason = ""
        self.down = ""

    def remaining(self):
        return max(0.0, self.until - time.monotonic())

    def check(self):
        if self.down:
            raise GeminiDownError(self.down)
        left = self.remaining()
        if left > 0:
            _WAIT.until = self.until
            raise GeminiCoolingError(f"проверки картинок на паузе ещё {left:.0f} с "
                                     f"({self.reason})")

    def answered(self):
        with self._lock:
            recovered = self.strikes > 0
            self.misses = self.strikes = 0
            self.since = 0.0
            self.reason = ""
        if recovered:
            self._log("Gemini для картинок снова отвечает — кадры, Pixiv и манга "
                      "проверяются дальше.")

    def failed(self, error):
        """Запрос без ответа; отдаёт ошибку, которую получат ожидающие."""
        with self._lock:
            if self.down:
                return GeminiDownError(self.down)
            now = time.monotonic()
            if now < self.until:
                # Ответ на запрос, ушедший до паузы: пауза уже идёт.
                _WAIT.until = self.until
                return GeminiCoolingError(f"проверки картинок на паузе ({self.reason})")
            self.since = self.since or now
            self.misses += 1
            # После паузы хватает одного молчаливого пробного запроса.
            if self.misses < DOWN_AFTER and not self.strikes:
                return error
            if now - self.since >= DOWN_TOTAL:
                self.down = (f"Gemini не отвечает {(now - self.since) / 60:.0f} мин, "
                             f"последний: {error}")
                return GeminiDownError(self.down)
            pause = PAUSE_STEPS[min(self.strikes, len(PAUSE_STEPS) - 1)]
            self.reason = f"{self.misses} запроса подряд без ответа, последний: {error}"
            self.strikes += 1
            self.misses = 0
            self.until = now + pause
            reason, until = self.reason, self.until
        self._log(f"Внимание: Gemini для картинок не отвечает ({reason}); "
                  f"пауза {pause / 60:.0f} мин, затем пробный запрос. Кадры, Pixiv "
                  "и манга ждут, остальной пак набирается дальше.")
        _WAIT.until = until
        return GeminiCoolingError(f"проверки картинок на паузе ({reason})")


@dataclass(eq=False)
class _Job:
    parts: list
    schema: dict
    purpose: str = "изображения"
    future: Future = field(default_factory=Future)
    deadline: float | None = None

    @property
    def size(self):
        return sum(len(str(part.get("data") or part.get("text") or ""))
                   for part in self.parts)

    @property
    def images(self):
        return max(1, sum(part.get("type") == "image" for part in self.parts))


def compatible(first, other):
    """Only flat visual verdicts can share the results-by-id protocol."""
    left, right = first.schema.get("properties", {}), other.schema.get("properties", {})
    if any(value.get("type") in ("array", "object") for value in [*left.values(), *right.values()]):
        return False
    return all(left[key] == right[key] for key in left.keys() & right.keys())


class VisualCheckBatcher:
    def __init__(self, client, stopped=lambda: False, *,
                 max_images=MAX_IMAGES, collect_seconds=COLLECT_SECONDS, pause=None):
        self.client = client
        self.stopped = stopped
        self.max_images = max(1, int(max_images))
        self.collect_seconds = max(0.0, float(collect_seconds))
        self._condition = threading.Condition()
        self._pending: list[_Job] = []
        self._sending = False
        self.pause = pause or VisualPause()
        self.stats = Counter()
        self.purpose_stats = Counter()

    @property
    def down(self):
        return self.pause.down

    def can_combine(self, first, other):
        return compatible(first, other)

    def batch_request(self, batch):
        return _request(batch)

    def batch_verdicts(self, response, batch):
        return _verdicts(response, batch)

    def check(self, parts, schema, purpose="изображения", deadline=None):
        try:
            return self._check(parts, schema, purpose, deadline)
        except GeminiCoolingError:
            if self.pause.until > time.monotonic():
                _WAIT.until = self.pause.until
            raise

    def _check(self, parts, schema, purpose, deadline):
        self.pause.check()
        job = _Job(parts, schema, purpose, deadline=deadline)
        with self._condition:
            self._pending.append(job)
            self._condition.notify_all()
        while not job.future.done():
            with self._condition:
                if (job.deadline is not None and time.monotonic() >= job.deadline
                        and not job.future.done()):
                    if job in self._pending:
                        self._pending.remove(job)
                    job.future.set_exception(TimeoutError("Истекло время ожидания проверки сцены"))
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

    def _collect_seconds(self):
        """Окно сбора: не меньше обычного и до свободного слота модели,
        но не дольше ближайшего срока ожидающей проверки."""
        board = getattr(self.client, "board", None)
        busy = 0.0
        if callable(getattr(board, "wait_time", None)):
            try:
                busy = float(board.wait_time(str(getattr(self.client, "model", ""))))
            except (TypeError, ValueError):
                busy = 0.0
        seconds = max(self.collect_seconds, min(MAX_COLLECT_SECONDS, busy))
        deadlines = [job.deadline for job in self._pending if job.deadline is not None]
        if deadlines:
            seconds = min(seconds, max(0.0, min(deadlines) - time.monotonic() - 1.0))
        return seconds

    def _send_next(self):
        with self._condition:
            self._condition.wait_for(
                lambda: sum(job.images for job in self._pending) >= self.max_images or self.stopped(),
                timeout=self._collect_seconds())
            batch, size, images = [], 0, 0
            while self._pending and images < self.max_images:
                job = self._pending[0]
                if job.deadline is not None and time.monotonic() >= job.deadline:
                    # Просроченная проверка иначе обрушила бы срок всей пачки.
                    self._pending.pop(0)
                    job.future.set_exception(TimeoutError("Истекло время ожидания проверки сцены"))
                    continue
                if job.size > MAX_INPUT:
                    self._pending.pop(0)
                    job.future.set_exception(GeminiError(
                        "Изображение слишком большое для проверки Gemini"))
                    continue
                if batch and (size + job.size > MAX_INPUT or images + job.images > self.max_images
                              or not self.can_combine(batch[0], job)):
                    break
                self._pending.pop(0)
                batch.append(job)
                size += job.size
                images += job.images
        if not batch:
            return
        try:
            if self.stopped():
                raise GeminiError("Отменено")
            self.pause.check()
            self.stats[len(batch)] += 1
            purposes = ", ".join(sorted({job.purpose for job in batch}))
            images = sum(part.get("type") == "image" for job in batch for part in job.parts)
            self.purpose_stats[(purposes, images)] += 1
            if len(batch) == 1:
                job = batch[0]
                from .visual_request_budget import call
                verdict = call(self.client, job.parts, job.schema, [job.deadline])
                if not job.future.done():
                    job.future.set_result(verdict)
            else:
                parts, schema = self.batch_request(batch)
                from .visual_request_budget import call
                response = call(self.client, parts, schema, [job.deadline for job in batch])
                verdicts = self.batch_verdicts(response, batch)
                for index, job in enumerate(batch):
                    if not job.future.done():
                        job.future.set_result(verdicts[index])
        except Exception as error:  # noqa: BLE001 — передаём отказ всем ожидающим
            error = self._note_failure(error)
            for job in batch:
                if not job.future.done():
                    job.future.set_exception(error)
        else:
            self.pause.answered()

    def _note_failure(self, error):
        """Считает запросы подряд без ответа; на пороге — пауза (VisualPause)."""
        if isinstance(error, GeminiCoolingError):
            # Модель на паузе после перегрузки или пауза самих проверок: запрос
            # в сеть не уходил. Предохранитель это не взводит.
            return error
        if not isinstance(error, GeminiUnavailableError):
            if not isinstance(error, GeminiDownError):
                self.pause.answered()   # сервер ответил — пусть и неудачно
            return error
        return self.pause.failed(error)


def _request(batch):
    parts = [{"type": "text", "text": (
        "Выполни каждую проверку id независимо по её инструкции. "
        "Внутри одной проверки может быть несколько изображений; "
        "названия и метки относятся только к проверке с тем же id. "
        "Не сравнивай изображения разных проверок. Верни results: "
        "ровно один вердикт с целочисленным id на каждую проверку. "
        "Для манги и кадров mixed_anime=false: эта проверка относится к артам Pixiv. "
        "Наличие персонажей в кадре не влияет на accept.") }]
    properties, required = {}, {"id"}
    for index, job in enumerate(batch):
        parts.append({"type": "text", "text": f"Проверка id={index}, изображений: {job.images}"})
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
                or ("has_characters" in row and type(row["has_characters"]) is not bool)
                or not set(batch[index].schema["required"]).issubset(row)):
            raise GeminiError("Gemini вернула неверные id или поля вердиктов")
        found[index] = {key: value for key, value in row.items() if key != "id"}
    return found


def initialize(generator):
    generator._visual_batch_lock = threading.Lock()
    generator._visual_batches = {}
    generator._visual_pause = VisualPause(log=lambda message: generator.log(message))


def uses_gemini(generator, cand):
    """Нужна ли вопросу этого рода проверка картинки через Gemini."""
    import animepack as api
    from .visual_mode import ocr_only
    settings = generator.s
    if ocr_only(settings):
        return False
    if cand.kind in api.FRAME_KINDS or cand.kind == api.STUDIO_KIND:
        from .frame_visual_check import enabled
        return enabled(settings, cand.kind)
    if cand.kind == api.PIXIV_ART_KIND:
        return (getattr(settings, "pixiv_gemini_check", True)
                and getattr(settings, "pixiv_title_check_mode", "gemini") != "local")
    if cand.kind == api.MANGA_KIND:
        if getattr(generator, "gemini_manga", None) is None:
            return False
        from .manga_page_context import is_webtoon
        return ((getattr(settings, "manga_gemini_check", True)
                 and getattr(settings, "manga_title_check_mode", "gemini") == "gemini")
                or (is_webtoon(cand) and getattr(settings, "manga_character_crop", True)))
    return False


def _paused(generator):
    pause = getattr(generator, "_visual_pause", None)
    if pause is None or pause.down or pause.remaining() <= 0:
        return None
    return pause


def kind_uses_gemini(generator, kind):
    """uses_gemini для рода вопросов, пока кандидата нет: манга — с запасом
    на вебтун, которому сцену выбирает Gemini."""
    import animepack as api
    if kind != api.MANGA_KIND:
        from types import SimpleNamespace
        return uses_gemini(generator, SimpleNamespace(kind=kind))
    from .visual_mode import ocr_only
    settings = generator.s
    if ocr_only(settings) or getattr(generator, "gemini_manga", None) is None:
        return False
    return ((getattr(settings, "manga_gemini_check", True)
             and getattr(settings, "manga_title_check_mode", "gemini") == "gemini")
            or getattr(settings, "manga_character_crop", True))


def pause_blocks(generator, kind, inflight):
    """Не запускать вопрос этого рода, пока проверки картинок на паузе.

    Манга во время паузы готовит страницы впрок: поиск, скачивание и вырезка
    идут, а на проверке Gemini тайтл уходит на повтор, и его страницы ждут в
    manga_page_reuse. После паузы остаётся один запрос Gemini — в прогоне
    16.10 хвост манги стоял 22 минуты, а потом готовил страницы с нуля.
    Впрок готовим не больше, чем удержит кладовая страниц."""
    if _paused(generator) is None or not kind_uses_gemini(generator, kind):
        return False
    import animepack as api
    if kind == api.MANGA_KIND:
        from .manga_page_reuse import KEEP_TITLES, count
        return inflight[kind] + count(generator) >= KEEP_TITLES
    return True


def note_wait(generator):
    """Одна строка журнала на паузу: отбор ждёт её конца, каталог не трогает."""
    pause = _paused(generator)
    if pause is None or getattr(generator, "_pause_wait_noted", None) == pause.until:
        return
    generator._pause_wait_noted = pause.until
    generator.log(f"Пауза проверок Gemini ещё {pause.remaining():.0f} с: оставшимся "
                  "вопросам нужна проверка картинок — жду её конца, не перебирая "
                  "каталог; манга тем временем готовит страницы впрок.")


def hold(generator, cand):
    """Пауза проверок картинок идёт, а вопросу она нужна: не начинать загрузку.

    Мангу не держим: её страницы готовятся впрок (см. pause_blocks)."""
    import animepack as api
    pause = _paused(generator)
    if pause is None or cand.kind == api.MANGA_KIND:
        return False
    if not uses_gemini(generator, cand):
        return False
    _WAIT.until = pause.until
    return True


def request(generator, client, parts, schema, purpose="изображения", max_images=None):
    """max_images — своя очередь с таким размером пачки (иначе общая на MAX_IMAGES)."""
    lock = getattr(generator, "_visual_batch_lock", None)
    if lock is None:
        return client.generate_json(parts, schema, temperature=0.0)
    # Одинаковые модель, рассуждение и доска квот — один запрос даже для
    # смеси Pixiv и манги. Разные выбранные модели остаются раздельными.
    # Multi-page selection and multi-crop review use different nested arrays.
    # Keep these stages separate so their required fields cannot get mixed.
    properties = schema.get("properties", {})
    stage = next((name for name in ("candidates", "scenes", "characters")
                  if name in properties), "visual")
    key = (id(getattr(client, "board", client)),
           str(getattr(client, "model", "")),
           str(getattr(client, "thinking", "")), stage, max_images)
    with lock:
        batcher = generator._visual_batches.get(key)
        if batcher is None:
            pause = getattr(generator, "_visual_pause", None)
            if stage in ("candidates", "scenes", "characters"):
                from .visual_nested_batch import NestedVisualBatcher
                batcher = NestedVisualBatcher(client, generator.stopped,
                                             max_images=48, collect_seconds=2.0,
                                             pause=pause)
            else:
                batcher = VisualCheckBatcher(client, generator.stopped,
                                             max_images=max_images or MAX_IMAGES,
                                             pause=pause)
            generator._visual_batches[key] = batcher
    runtime = getattr(generator, "_runtime", None)
    deadline = getattr(getattr(runtime, "local", None), "manga_deadline", None)
    return batcher.check(parts, schema, purpose, deadline=deadline)
