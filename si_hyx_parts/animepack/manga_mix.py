# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Состав книжной доли пака. Namespace: animepack.

Вопросов по манге в паке обычно немного, но книги между собой очень разные, и
доли внутри книжной части задаются отдельно (просьба пользователя):

* сколько из них ЭКРАНИЗОВАНЫ — такую мангу узнают по её аниме, и вопрос
  выходит куда легче (см. manga_adaptation.py);
* сколько манхвы и сколько маньхуа — у корейских и китайских изданий своя
  рисовка и свой круг читателей, и без отдельной доли они тонули среди
  японской манги, которой в каталоге на порядок больше.

Обе доли соблюдаются мягко. Книга, которой в паке уже хватает, не выбрасывается
насовсем, а откладывается «на скамейку»: когда кандидаты кончились, а места в
паке ещё есть, отложенные идут в дело и доли больше не сторожатся. Жёсткая
рамка оставила бы книжную долю полупустой на каталоге, где, скажем, манхвы
просто нет, — а недобранный пак хуже, чем пак с перекосом долей.
"""
from __future__ import annotations
import animepack as _api


# Сколько книг держим на скамейке в расчёте на одно книжное место. Отложенные
# идут в дело, только когда кандидаты кончились, и заполнить долю хватает
# первых же. Без потолка скамейка вырастала до десятков тысяч карточек (в логе
# пользователя — 39 149) и держала их в памяти весь прогон.
BENCH_PER_SLOT = 20
BENCH_MIN = 200


class MangaMix:
    """Счётчик книжных долей: кого ещё берём, а кого уже хватит."""

    def __init__(self, settings, quota: int, log=None):
        self.s = settings
        self._log = log or (lambda msg: None)
        self._used: _api.Counter = _api.Counter()
        # Отложенные книги и то, кого мы уже откладывали (одного кандидата
        # _pick_kind спрашивает по нескольку раз — на скамейку он попадает
        # ровно один раз).
        self._bench: list = []
        self._benched: set[int] = set()
        self.off = False
        self.sync(quota)

    # ── цели ──────────────────────────────────────────────────────────────
    def sync(self, quota: int) -> None:
        """Пересчитывает цели под нынешнюю квоту манги (она меняется, когда
        места умерших родов вопросов раздаются живым)."""
        self.quota = max(0, int(quota or 0))
        self.bench_cap = max(BENCH_MIN, self.quota * BENCH_PER_SLOT)
        pct = max(0, min(100, int(getattr(self.s, "manga_adapted_percent", 50) or 0)))
        adapted = int(round(self.quota * pct / 100.0))
        self.adapted_target = {True: adapted, False: self.quota - adapted}
        manhwa = max(0, min(100, int(getattr(self.s, "manga_pct_manhwa", 0) or 0)))
        manhua = max(0, min(100, int(getattr(self.s, "manga_pct_manhua", 0) or 0)))
        if manhwa + manhua > 100:
            share = 100.0 / (manhwa + manhua)
            manhwa, manhua = int(manhwa * share), int(manhua * share)
        self.kind_target = {
            "manhwa": int(round(self.quota * manhwa / 100.0)),
            "manhua": int(round(self.quota * manhua / 100.0)),
        }
        self.kind_target[""] = max(0, self.quota - sum(self.kind_target.values()))

    # ── учёт ──────────────────────────────────────────────────────────────
    @staticmethod
    def _edition(cand) -> str:
        """Ключ издания: манхва, маньхуа или «всё остальное» (манга, ранобэ)."""
        kind = str((cand.anime or {}).get("kind") or "").lower()
        return kind if kind in ("manhwa", "manhua") else ""

    def _keys(self, cand) -> tuple:
        return (("adapted", bool(cand.adapted_from)), ("kind", self._edition(cand)))

    def allows(self, cand) -> bool:
        """Нужен ли ещё такой вопрос. Лишний уходит на скамейку, а не в мусор."""
        if self.off or not self.quota or not cand.is_manga:
            return True
        adapted_key, kind_key = self._keys(cand)
        full = (self._used[adapted_key] >= self.adapted_target.get(adapted_key[1], 0)
                or self._used[kind_key] >= self.kind_target.get(kind_key[1], 0))
        if not full:
            return True
        # В _benched попадают только те, кто и правда лежит на скамейке:
        # иначе id выброшенной карточки мог бы достаться новой.
        if len(self._bench) < self.bench_cap and id(cand) not in self._benched:
            self._benched.add(id(cand))
            self._bench.append(cand)
        return False

    @property
    def bench_size(self) -> int:
        """Сколько книг ждёт на скамейке прямо сейчас."""
        return len(self._bench)

    def _need_rank(self, cand) -> tuple:
        """Чего в паке ещё не хватает — то и берём со скамейки первым.

        Доли больше не сторожатся, но порядок остаётся за нами: манхва,
        отложенная в начале прогона, должна уйти в пак раньше пятисотой
        японской книги, иначе «взял отложенных» снова кончится перекосом."""
        adapted_key, kind_key = self._keys(cand)
        return (self._used[kind_key] >= self.kind_target.get(kind_key[1], 0),
                self._used[adapted_key] >= self.adapted_target.get(
                    adapted_key[1], 0))

    def take_bench(self) -> list:
        """Отложенные книги — и больше долей не сторожим.

        Зовётся, когда кандидаты кончились: доли важны, но недобранный пак
        важнее. Возвращает пустой список, когда откладывать было нечего."""
        self._bench.sort(key=self._need_rank)
        bench, self._bench = self._bench, []
        self._benched.clear()
        if not bench:
            return []
        self.off = True
        self._log(f"Доли манги: подходящих книг в каталоге не хватило — беру "
                  f"отложенные ({len(bench)} шт.), чтобы пак не остался "
                  "недобранным.")
        return bench

    def reserve(self, cand) -> None:
        if cand.is_manga:
            for key in self._keys(cand):
                self._used[key] += 1

    def release(self, cand) -> None:
        if cand.is_manga:
            for key in self._keys(cand):
                self._used[key] = max(0, self._used[key] - 1)

MangaMix.__module__ = _api.__name__
_api.MangaMix = MangaMix
