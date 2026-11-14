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
from .manga_editions import shares


# Сколько книг держим на скамейке в расчёте на одно книжное место. Отложенные
# идут в дело, только когда кандидаты кончились, и заполнить долю хватает
# первых же. Без потолка скамейка вырастала до десятков тысяч карточек (в логе
# пользователя — 39 149) и держала их в памяти весь прогон.
BENCH_PER_SLOT = 20
BENCH_MIN = 200
# Сколько id каталога план должен выдать ПОСЛЕ того, как издание в нём
# кончилось, прежде чем его места отдаются другим: столько успевают дойти до
# отбора книги этого издания, ещё сидящие в пачке карточек и окне проверок
# (CandidateSource.WINDOW). Раньше — отдать их было нельзя, они бы пришли
# «лишними» и ушли на скамейку.
DRY_TRANSIT = 60


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
        # Вебтуны без Gemini не собрать (сцену с персонажами выбирает модель):
        # тогда закрываются только они, а не вся книжная доля.
        self.webtoons_off = ""
        # Издания, которых в каталоге под рамку сложности больше нет: их
        # недобранные места отданы другим (drop_dry).
        self._dry: set[str] = set()
        self.sync(quota)

    # ── цели ──────────────────────────────────────────────────────────────
    def sync(self, quota: int) -> None:
        """Пересчитывает цели под нынешнюю квоту манги (она меняется, когда
        места умерших родов вопросов раздаются живым)."""
        self.quota = max(0, int(quota or 0))
        self.bench_cap = max(BENCH_MIN, self.quota * BENCH_PER_SLOT)
        pct = int(getattr(self.s, "manga_adapted_percent", 50) or 0)
        if pct < 0:
            self.adapted_target = {True: self.quota, False: self.quota}
        else:
            adapted = int(round(self.quota * min(100, pct) / 100.0))
            self.adapted_target = {True: adapted, False: self.quota - adapted}
        values = shares(self.s)
        targets = {k: self.quota * v // 100 for k, v in values.items()}
        rest = self.quota - sum(targets.values()) if any(values.values()) else 0
        order = sorted(values, key=lambda k: -(self.quota * values[k] % 100))
        for key in order[:rest]:
            targets[key] += 1
        self.kind_target = {"manhwa": targets["manhwa"],
                            "manhua": targets["manhua"], "": targets["manga"]}
        if self.webtoons_off and not getattr(self.s, "manga_strict_targets", False):
            self.kind_target[""] += self.kind_target["manhwa"] + self.kind_target["manhua"]
            self.kind_target["manhwa"] = self.kind_target["manhua"] = 0
        self._give_away_dry()

    def _give_away_dry(self) -> int:
        """Недобранные места кончившихся изданий — живому изданию с самой
        большой долей. Пересчитывается при каждой sync: сорвавшаяся загрузка
        снова открывает место, и оно опять уходит живым."""
        values = shares(self.s)
        receivers = sorted((k for k in self.kind_target
                            if k not in self._dry and values.get(k or "manga")
                            and not (k and self.webtoons_off)),
                           key=lambda k: -self.kind_target[k])
        moved = 0
        if not receivers:
            return moved
        for key in sorted(self._dry):
            spare = max(0, self.kind_target.get(key, 0) - self._used[("kind", key)])
            if spare:
                self.kind_target[key] -= spare
                self.kind_target[receivers[0]] += spare
                moved += spare
        return moved

    def drop_dry(self, plan, waiting=()) -> None:
        """Отдаёт места издания, которого в плане каталога больше нет.

        Паку нужны две маньхуа, а маньхуа уровня 1–5 в Shikimori — полтора
        десятка, и половина не проходит проверку страниц. Раньше отбор после
        этого перебирал по 100 карточек на книжное место (2400 на 24 книги),
        откладывая каждую японскую мангу как «лишнюю», и только потом брал
        отложенных: 7–20 минут на два последних вопроса (паки 11.11 и 12.11).
        Теперь, как только план каталога (CatalogPlan.dry) не держит ни одной
        группы издания в его рамке, а книги этого издания, выданные раньше,
        успели дойти до отбора, недобранные места переходят другому изданию.

        waiting — кандидаты, ждущие свободного потока (deferred): пока среди
        них есть книга этого издания, его места ещё не пусты."""
        dry = getattr(plan, "dry", None)
        if (not dry or self.off or not self.quota
                or getattr(self.s, "manga_strict_targets", False)):
            return
        served = getattr(plan, "served", 0)
        for key, since in list(dry.items()):
            if self._used[("kind", key)] >= self.kind_target.get(key, 0):
                continue
            if key in self._dry:
                # Загрузка книги этого издания сорвалась уже после передачи
                # мест — освободившееся место тоже уходит живым.
                self._give_away_dry()
                continue
            if served - since < DRY_TRANSIT:
                continue
            if any(c.is_manga and self._edition(c) == key for c in waiting):
                continue
            self._dry.add(key)
            moved = self._give_away_dry()
            if moved:
                names = {"": "японской манги", "manhwa": "манхвы",
                         "manhua": "маньхуа"}
                self._log(f"Доли манги: {names.get(key, key)} под рамку сложности "
                          "в каталоге больше нет — её недобранные места "
                          f"({moved} шт.) отдаю другим изданиям, не перебирая "
                          "каталог дальше.")

    def close_webtoons(self, reason: str) -> bool:
        """Манхва и маньхуа больше не берутся; их места — японской манге.
        Возвращает True при первом закрытии (чтобы сообщить один раз)."""
        if self.webtoons_off:
            return False
        self.webtoons_off = reason or "вебтуны недоступны"
        self._bench = [cand for cand in self._bench if not self._edition(cand)]
        self.sync(self.quota)
        return True

    # ── учёт ──────────────────────────────────────────────────────────────
    @staticmethod
    def _edition(cand) -> str:
        """Ключ издания: манхва, маньхуа или японские комиксы."""
        kind = str((cand.anime or {}).get("kind") or "").lower()
        return kind if kind in ("manhwa", "manhua") else ""

    def _keys(self, cand) -> tuple:
        return (("adapted", bool(cand.adapted_from)), ("kind", self._edition(cand)))

    def allows(self, cand) -> bool:
        """Нужен ли ещё такой вопрос. Лишний уходит на скамейку, а не в мусор."""
        if cand.is_manga:
            key = self._edition(cand) or "manga"
            if not shares(self.s).get(key):
                return False
            if self.webtoons_off and self._edition(cand):
                return False
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

    def wants(self, cand, extra=None) -> bool:
        """Нужна ли ещё такая книга — счёт allows, но без скамейки.

        Его спрашивает план каталога (CatalogPlan): книга издания, которого
        в паке уже хватает, подаётся после нужных. Раньше план смотрел только
        на уровень, и отбор отправлял лишние на скамейку одну за другой: в
        прогоне 2026-10-08 скамейка упёрлась в потолок 320, а каталог
        просматривался 18 минут. extra — книги, уже набранные в текущую пачку
        плана, но ещё не дошедшие до отбора."""
        if cand.is_manga:
            key = self._edition(cand) or "manga"
            if not shares(self.s).get(key):
                return False
            if self.webtoons_off and self._edition(cand):
                return False
        if self.off or not self.quota or not cand.is_manga:
            return True
        extra = extra or {}
        adapted_key, kind_key = self._keys(cand)
        return (self._used[adapted_key] + extra.get(adapted_key, 0)
                < self.adapted_target.get(adapted_key[1], 0)
                and self._used[kind_key] + extra.get(kind_key, 0)
                < self.kind_target.get(kind_key[1], 0))

    def count(self, cand, into) -> None:
        """Добавляет книгу в счётчик into (пачка плана, см. wants)."""
        if cand.is_manga:
            into.update(self._keys(cand))

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
        if getattr(self.s, "manga_strict_targets", False):
            bench = [cand for cand in bench
                     if all(self._used[key] < (self.adapted_target if key[0] == "adapted"
                                              else self.kind_target).get(key[1], 0)
                            for key in self._keys(cand))]
            self._log("Строгие доли комиксов: возвращаю отложенных кандидатов "
                      "с сохранением квот изданий.")
            return bench
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
