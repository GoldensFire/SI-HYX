# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Запасная полоса Gemma 4 31B для простых проверок кадров и названий манги.

Gemma ходит по своей квоте (свои RPM и сутки), поэтому снимает часть очереди с
основной модели изображений. Но отвечает она 30–60 с и в живой пачке из четырёх
повторила id, поэтому берёт только плоские проверки кадров и видимого названия
на странице манги, по одной, и только когда основная модель занята очередью или
стоит на паузе после 503. Любой отказ Gemma возвращает проверку основной модели.
Выбор сцены манги (координаты вырезки) остаётся основной модели.

Проверка сцен отрывков сюда не попадает: звук Gemma не принимает (400 «Audio
input modality is not enabled»), а по немому ролику выдумывает японские реплики.
"""
from __future__ import annotations

from collections import Counter
import threading

from gemini_api import (GeminiAuthError, GeminiCoolingError, GeminiDownError,
                        GeminiQuotaError, is_gemma)

MODEL = "gemma-4-31b-it"
THINKING = "minimal"
TIMEOUT = 90.0
# Одновременных запросов к Gemma: при её задержке полоса иначе упиралась бы в
# один ответ за полминуты, а больше трёх рабочих потоков занимать не хочется.
LIMIT = 3
# Основная модель занята дольше — проверка уходит Gemma: два запроса впереди
# уже дольше ответа Gemma с учётом её собственной очереди.
BUSY_SECONDS = 10.0


class SpareLane:
    def __init__(self, client):
        self.client = client
        self.slots = threading.BoundedSemaphore(LIMIT)
        self.off = ""
        self.stats = Counter()
        self._lock = threading.Lock()

    def _note(self, name):
        with self._lock:
            self.stats[name] += 1

    def ready(self):
        board, model = self.client.board, self.client.model
        return (not self.off and not board.unavailable(model)
                and not board.exhausted(model)
                and board.wait_time(model) < BUSY_SECONDS)

    def check(self, parts, schema, valid):
        """Вердикт Gemma либо None — тогда проверку делает основная модель."""
        if not self.ready() or not self.slots.acquire(blocking=False):
            return None
        try:
            verdict = self.client.generate_json(parts, schema, temperature=0.0)
        except GeminiCoolingError:
            # Пауза после 503 временная: доска сама вернёт Gemma в строй.
            self._note("пауза")
            return None
        except (GeminiAuthError, GeminiQuotaError, GeminiDownError) as error:
            self.off = str(error)
            self._note("отказ")
            return None
        except Exception:  # noqa: BLE001 — перегрузка, таймаут, не JSON: к основной
            self._note("отказ")
            return None
        finally:
            self.slots.release()
        if not valid(verdict):
            self._note("неверный вердикт")
            return None
        self._note("принято")
        return verdict


def primary_busy(client):
    board, model = getattr(client, "board", None), str(getattr(client, "model", ""))
    if board is None or not callable(getattr(board, "wait_time", None)):
        return False
    return (board.unavailable(model) or board.exhausted(model)
            or board.wait_time(model) >= BUSY_SECONDS)


def create(generator, make_client, primary):
    """Полоса для кадров и манги, если основная модель изображений — не сама Gemma."""
    if primary is None or is_gemma(getattr(primary, "model", "")):
        return None
    client = make_client(MODEL, THINKING, timeout=TIMEOUT, allow_model_fallback=False)
    client.purpose = "Изображения, запас Gemma"
    generator.log(f"Gemini: проверки кадров и названий манги при занятой {primary.model} уходят в "
                  f"{MODEL} (своя квота, по одной, не больше {LIMIT} сразу).")
    return SpareLane(client)


def verdict(generator, primary, parts, schema, valid):
    lane = getattr(generator, "_visual_spare", None)
    if lane is None or not primary_busy(primary):
        return None
    return lane.check(parts, schema, valid)


def log_summary(generator):
    lane = getattr(generator, "_visual_spare", None)
    if lane is None or not lane.stats:
        return
    parts = ", ".join(f"{name} {count}" for name, count in sorted(lane.stats.items()))
    tail = f"; полоса выключена: {lane.off}" if lane.off else ""
    generator.log(f"Gemma, запасная полоса кадров и манги: {parts}{tail}.")
