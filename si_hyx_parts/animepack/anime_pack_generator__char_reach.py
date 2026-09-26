# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator: _char_reach. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def _char_reach(self, cand: _api.SongCandidate) -> tuple[int, int]:
    """Единственный достижимый уровень героя — уровень его тайтла."""
    base = cand.level
    return (_api.char_question_level(base, self._FAV_ALL),
            _api.char_question_level(base, 0))

def _char_level_fits(self, cand: _api.SongCandidate) -> bool:
    """Держит среднюю сложность ВОПРОСОВ-ПЕРСОНАЖЕЙ около char_level_avg.

        Отдельная от общей средней величина (просьба пользователя), но сам
        уровень героя теперь равен уровню тайтла. Зовётся из рабочих потоков,
        поэтому список набранного — под замком.

        Просимая сложность бывает недостижима в принципе — не «подходящих мало»,
        а «таких не бывает»: при паке из тайтлов шестого уровня персонажа легче
        четвёртого взять неоткуда (см. _char_reach). Тогда генератор не хватает
        что попало, а переезжает на БЛИЖАЙШУЮ достижимую сложность и дальше
        держит уже её (просьба пользователя)."""
    if not cand.is_character:
        return True
    # Рамка сложности персонажей своя (просьба пользователя). Основная
    # проверка — ещё при выборе рода вопроса (level_bounds): уровень героя
    # равен уровню тайтла и известен заранее. Здесь — страховка на случай,
    # если уровень сдвинулся уже по дороге (например, «в избранном» тайтла).
    low = int(getattr(self.s, "char_level_min", 1) or 1)
    high = int(getattr(self.s, "char_level_max", _api.MAX_LEVEL)
               or _api.MAX_LEVEL)
    if not low <= cand.char_level <= max(low, high):
        self._log_rare("Сложность персонажей",
                       f"«{cand.title_ru}»: уровень тайтла {cand.char_level} "
                       f"не входит в рамку персонажей {low}…{high} — беру "
                       "следующий тайтл")
        return False
    target = int(getattr(self.s, "char_level_avg", 0) or 0)
    if not target:
        return True
    floor, ceil = self._char_reach(cand)
    level = cand.char_level
    message = ""
    with self._char_lock:
        # Границы считаем по РЕАЛЬНО попадавшимся персонажам, а не по
        # теоретическому размаху тайтлов: один удачный хит в пуле иначе
        # объявлял бы тройку достижимой, и генератор гнался бы за ней весь
        # пак. Границы только расширяются (min/max), поэтому цель ходит лишь
        # В СТОРОНУ просимой — туда-сюда она не мечется.
        self._char_reach_lo = min(self._char_reach_lo, level)
        self._char_reach_hi = max(self._char_reach_hi, level)
        self._char_floor = min(self._char_floor, floor)
        self._char_ceil = max(self._char_ceil, ceil)
        self._char_seen += 1
        near = max(self._char_reach_lo, min(self._char_reach_hi, target))
        if (self._char_seen >= self.CHAR_REACH_SAMPLE
                and near != (self._char_target_eff or target)):
            self._char_target_eff = near
            self._char_skips = 0
            if near == target:
                message = ("Нашлись персонажи поподходящее — возвращаюсь к "
                           f"запрошенной сложности {target}.")
            else:
                side = "легче" if near > target else "сложнее"
                # Одно дело «таких тайтлов не бывает» в просмотренном пуле,
                # другое — «пока не попадались».
                why = ("не бывает" if near == self._char_floor
                       else "пока не попадалось")
                message = (f"Сложность персонажей {target} недостижима: "
                           f"{side} {near} в этом паке {why} — держу "
                           f"ближайшую, {near}.")
        aim = self._char_target_eff or target
        levels = list(self._char_levels)
        give_up = self._char_skips >= self.CHAR_LEVEL_GIVE_UP
        if give_up:
            self._char_skips = 0
            if not self._char_warned:
                self._char_warned = True
                message = (f"Средняя сложность персонажей {aim} не "
                           "выдерживается — подходящих не хватает, беру "
                           "что есть.")
        if give_up or len(levels) < 3:
            fits = True
        else:
            avg = sum(levels) / len(levels)
            level = cand.char_level
            fits = not ((avg > aim + 0.25 and level > aim)
                        or (avg < aim - 0.25 and level < aim))
            self._char_skips = 0 if fits else self._char_skips + 1
    if message:
        self.log(message)
    return fits

def _remember_char_level(self, cand: _api.SongCandidate) -> None:
    """Запоминает сложность принятого вопроса-персонажа."""
    if not cand.is_character:
        return
    with self._char_lock:
        self._char_levels.append(cand.char_level)

def _drop_kind(self, kind: str) -> None:
    """Помечает род вопросов как больше не получающийся в этом прогоне.

        Зовётся из рабочего потока (Gemini отваливается прямо на загрузке), а
        разбирается с этим главный цикл отбора: свободные места надо отдать
        оставшимся родам, иначе они так и будут жечь кандидатов впустую."""
    with self._warn_lock:
        self._dead_kinds.add(kind)

def _spend_kind(self, kind: str) -> None:
    """Кандидаты этого рода вопросов кончились (вычерпан свой каталог).

        Не то же самое, что _drop_kind: сам род работает, и уже запущенные
        загрузки надо довести до конца. Главному циклу это говорит одно —
        новых вопросов такого рода не будет, свободные места пора отдать
        остальным. Без этого доля манги, чей каталог в сотню карточек кончился
        первым, до конца прогона требовала кандидатов, и цикл жёг на неё всю
        базу аниме (ни один тайтл аниме мангой стать не может)."""
    with self._warn_lock:
        self._spent_kinds.add(kind)

def _close_spent_streams(self, quotas: dict, counts) -> None:
    """Закрывает поток книг, когда просить их больше незачем.

        Карточка манги приезжает из своего каталога и ничем, кроме вопроса по
        манге, стать не может. Пока поток открыт, цикл отбора продолжает его
        просить (места-то в паке ещё есть — под сакугу, кадры, песни), каждую
        лишнюю книгу отправляет на скамейку и платит за это разбором связей и
        экранизаций целой пачки карточек.

        Закрываем в двух случаях:

        * книжная доля набрана. Считаем по ПРИНЯТЫМ вопросам, а не по
          запущенным загрузкам: сорвавшаяся загрузка иначе оставила бы долю
          недобранной, а поток уже закрытым;
        * книг просмотрено вдоволь (BOOK_SCAN_PER_SLOT на место), а долю и так
          есть чем добрать — отложенных на скамейке хватает. Дальше каталог
          перебирается уже впустую: в логе пользователя так было просмотрено
          48 050 карточек и отложено 39 149 при доле в двадцать вопросов.

        Закрываем вместе со `_spend_kind`: иначе места умерших родов вопросов
        могли бы вернуться манге, которую больше неоткуда взять."""
    kind = _api.MANGA_KIND
    if kind in self._closed_streams:
        return
    quota = int(quotas.get(kind, 0) or 0)
    if not quota:
        return
    done = counts[kind]
    if done < quota:
        budget = max(self.BOOK_SCAN_MIN, quota * self.BOOK_SCAN_PER_SLOT)
        bench = self._manga_mix.bench_size
        # Отложенных должно хватать на весь остаток доли БЕЗ учёта запущенных
        # загрузок: сорвавшаяся иначе оставила бы долю недобранной, а каталог
        # уже закрытым.
        if self._manga_seen < budget or done + bench < quota:
            return
        self.log(f"Каталог книг просмотрен на {self._manga_seen} карточек — "
                 f"дальше беру из отложенных ({bench} шт.): подходящих по "
                 "книжным долям больше не попадается, а перебирать каталог "
                 "до конца — только время.")
        # Закрываем ТОЛЬКО поток каталога. Долю книг при этом не хороним:
        # добрать её есть чем — отложенных на скамейке хватает на весь
        # остаток. `_spend_kind` тут был прямой ошибкой: он пускал
        # `_share_out_dead`, тот на каждом круге срезал книжную квоту до уже
        # набранного и раздавал места родам вопросов, чей каталог давно
        # кончился. В логе пользователя так ушли четыре места (16 книг вместо
        # 20 при 400 отложенных), и пак вышел 140 вопросов из 144.
        self._closed_streams.add(kind)
        return
    self._closed_streams.add(kind)
    self._spend_kind(kind)

def _share_out_dead(self, quotas: dict, counts, inflight) -> None:
    """Отдаёт места отвалившихся родов вопросов остальным.

        Без этого пак недобирался на ровном месте: доля «по сюжету» с
        кончившимся ключом Gemini продолжала просить кандидатов, каждый из них
        тут же отваливался, и база кончалась раньше, чем набирались анаграммы
        (лог пользователя: 21 вопрос из 48 при живых 2891 тайтлах)."""
    with self._warn_lock:
        dead = sorted(self._dead_kinds | self._spent_kinds)
    for kind in dead:
        alive = [k for k in quotas
                 if quotas.get(k, 0) > 0 and k not in dead]
        if not alive:
            # Закрываем квоту целиком, включая уже запущенные попытки. Иначе
            # при восьми потоках она уменьшалась сперва на 89, затем ещё семь
            # раз по одному — ровно такой шум был в журнале пользователя.
            left = quotas.get(kind, 0) - counts[kind]
            if left <= 0:
                continue
            quotas[kind] = counts[kind]
            name = _api.KIND_TITLES.get(kind, kind).lower()
            self.log(f"Мест под «{name}» больше не занимаю ({left} шт.) — "
                     "переложить их не на кого, пак будет короче.")
            continue
        left = quotas.get(kind, 0) - counts[kind] - inflight[kind]
        if left <= 0:
            continue
        quotas[kind] = counts[kind] + inflight[kind]
        name = _api.KIND_TITLES.get(kind, kind).lower()
        # Крупные доли первыми: лишние места достаются тому рода вопросов,
        # которого в паке и так больше всего.
        alive.sort(key=lambda k: (-quotas[k], k))
        for i in range(left):
            quotas[alive[i % len(alive)]] += 1
        where = ", ".join(_api.KIND_TITLES.get(k, k).lower() for k in alive)
        self.log(f"Оставшиеся места «{name}» ({left} шт.) отдаю "
                 f"остальным: {where}.")
