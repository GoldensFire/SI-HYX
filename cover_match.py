# -*- coding: utf-8 -*-
"""Verdict on one candidate: same composition, and which 20 seconds to cut.

Пороги здесь — не догадка, а замер на 139 настоящих парах «эталон AMQ — кавер с
YouTube» и 2662 чужих парах (tools/cover_audio_probe.py). Что из этого вышло:

* Решает ОДНО число — счёт Qmax, делённый на корень из длины эталона. Проверены
  ещё пять: сырой счёт, деление на длину, на корень произведения длин, отношение
  к уровню случайного совпадения (перемешанный кавер) и «чистота» пути. Ни одно
  не отделяло лучше, а перемешанный кавер стоил бы второго выравнивания.
* Утечки ТОЖДЕСТВА, которые пропускает гейт по заголовку, набирают не больше
  1.64; чужие песни в лоб — не больше 2.48; настоящие каверы держатся выше 3.0
  в 81% случаев. Отсюда и порог с запасом в 1.2 раза.
* Оригиналы РАЗНЫХ песен между собой дают 14 (медиана) и 29 (максимум) — то есть
  порог 3.0 (это ~60 очков на 90-секундном эталоне) выше шума вдвое.
* Двадцать секунд берутся ИЗ ТОГО ЖЕ выравнивания: у всех 111 принятых каверов
  нашлось окно с плотностью пути не ниже 0.8, а у полной версии кавера окно
  само уезжает с начала файла (64 из 74 начинались позже пятой секунды) —
  вступление, разговоры и аплодисменты отсекаются без отдельного поиска.

Ни сети, ни Qt, ни subprocess: сюда приходят две готовые хромы (cover_audio).
"""
from __future__ import annotations

import math
import random

import cover_audio as audio
import cover_fingerprint as fingerprint

# Порог для кандидата, назвавшего песню, и для назвавшего только аниме. Второй
# строже нарочно: у такого тождество доказывает ОДИН звук. На стенде слабые
# каверы держались выше 3.76, слабые чужие пары — ниже 2.16.
MIN_SCORE = 3.0
MIN_SCORE_WEAK = 3.5
# Какая доля окна эталона обязана лежать на пути выравнивания. У принятых
# каверов лучшее окно давало 0.80…1.01, так что 0.5 — это запас, а не отбор.
MIN_DENSITY = 0.5
WINDOW_STEP = 1.0                # шаг перебора окон эталона, секунды
WANT_SECONDS = 20.0              # длина отрезка по умолчанию (audio_cut пака)
# Границы «близости к оригиналу» для сложности кавера: 10-й и 90-й процентили
# принятых каверов (3.44 и 16.78 — округлены).
CLOSE_LOW, CLOSE_HIGH = 3.0, 17.0
SHIFT_PENALTY = 0.85             # кавер в другой тональности узнать труднее
TEMPO_PENALTY = 0.90             # и с заметно другим темпом тоже


def floor_for(strength: str) -> float:
    """Порог по силе совпадения заголовка (см. cover_meta.STRONG/WEAK)."""
    return MIN_SCORE_WEAK if str(strength or "").lower() == "weak" else MIN_SCORE


def original_inside(value) -> bool:
    """Играет ли внутри записи сам мастер оригинала (игра под оригинал).

    Считает это НЕ хрома, а отпечаток записи (cover_fingerprint): точный
    band-кавер даёт ровно такое же выравнивание, как гитара поверх мастера, и
    по хроме их не разделить. Сюда приходит уже готовое число совпавших пар в
    секунду, сохранённое в кладовой."""
    return float(value or 0.0) > fingerprint.MAX_OVERLAP


def normalized(score: float, ref_frames: int) -> float:
    """Счёт Qmax, приведённый к длине эталона.

    Корень, а не сама длина: счёт растёт примерно как длина совпавшего участка,
    а вот СЛУЧАЙНЫЕ совпадения — как её корень. На замере обе нормировки
    разделяли одинаково (эталоны AMQ все около 90 с), но корень не развалится,
    когда эталоном окажется полная версия вставки."""
    return float(score) / math.sqrt(max(int(ref_frames), 1))


def closeness(score_norm: float, shift: int = 0, tempo: float = 1.0) -> float:
    """Насколько кавер близок к оригиналу, 0…1 — основа СЛОЖНОСТИ вопроса.

    Мера не выдумана: на стенде медиана нормированного счёта у вокальных и
    band-каверов 10.4 и 11.3, у фортепианных и оркестровых — 7.8 и 8.8, то есть
    число само отражает, насколько далеко ушло исполнение. Тональность и темп
    учитываются отдельно: их слух замечает сразу."""
    span = max(CLOSE_HIGH - CLOSE_LOW, 1e-6)
    value = (float(score_norm) - CLOSE_LOW) / span
    value = min(1.0, max(0.0, value))
    if int(shift or 0) % 12:
        value *= SHIFT_PENALTY
    if tempo and abs(math.log2(max(float(tempo), 1e-6))) > 0.1:
        value *= TEMPO_PENALTY
    return round(value, 3)


# Сколько ступеней сложности у кавера — столько же, сколько у узнаваемости
# тайтла (index_level), чтобы во вкладке была одна и та же шкала 1…10.
LEVELS = 10


def level(close: float) -> int:
    """Сложность кавера 1…10: 1 — почти оригинал, 10 — узнать почти нельзя.

    Шкала обратна близости: closeness считается из того же нормированного
    счёта, по которому и различаются исполнения (у вокальных каверов медиана
    10.4, у фортепианных 7.8), поэтому «дальше от оригинала» и означает
    «труднее угадать»."""
    hard = 1.0 - min(1.0, max(0.0, float(close)))
    return int(min(LEVELS, max(1, 1 + round(hard * (LEVELS - 1)))))


def similarity_percent(close: float) -> int:
    """Измеренная схожесть исполнения с оригиналом, 0…100 процентов.

    Это результат сравнения звука, а не `songDifficulty` и не статистика сайта
    Anime Music Quiz. Вокальное исполнение с медианой closeness 0.53 даёт 53%,
    фортепианное с 0.34 — 34%."""
    return int(round(min(1.0, max(0.0, float(close))) * 100))


def amq(close: float) -> int:
    """Совместимое старое имя для :func:`similarity_percent`.

    Новому коду нельзя показывать это имя пользователю: величина не приходит
    с AMQ и не является сложностью песни.
    """
    return similarity_percent(close)


def windows(path, ref_seconds: float, want: float = WANT_SECONDS,
            step: float = WINDOW_STEP) -> list[dict]:
    """Годные окна эталона: {"at", "density", "cover"} по всему эталону.

    "cover" — тот же участок в кавере, (начало, конец) в секундах. Окна с
    рыхлым путём не возвращаются вовсе: по ним вырезать нельзя."""
    out: list[dict] = []
    if not path or want <= 0:
        return out
    start = 0.0
    limit = max(ref_seconds - want, 0.0)
    while start <= limit + 1e-6:
        density = audio.window_density(path, start, want)
        mapped = audio.map_window(path, start, want)
        if mapped and density >= MIN_DENSITY:
            out.append({"at": round(start, 2), "density": round(density, 3),
                        "cover": (round(mapped[0], 2), round(mapped[1], 2))})
        start += max(step, 0.1)
    return out


def nearest(good, prefer, step: float = WINDOW_STEP) -> dict:
    """Годное окно рядом с запрошенной секундой эталона ({} — такого нет).

    Допуск — шаг перебора окон: ближе, чем на шаг, окна и не бывает."""
    if not good or prefer is None:
        return {}
    near = min(good, key=lambda w: abs(float(w["at"]) - float(prefer)))
    return near if abs(float(near["at"]) - float(prefer)) <= step else {}


def choose(good, rng=None, prefer=None) -> dict:
    """Одно окно из годных. Случайно — чтобы в паках был не один и тот же кусок.

    `prefer` — точка в эталоне, которую хотел генератор (у оригинала отрезок
    тоже берётся со случайного места). Если рядом с ней окно годное, берём его:
    так у кавера и у оригинала звучит одна и та же часть песни."""
    if not good:
        return {}
    near = nearest(good, prefer)
    if near:
        return near
    # Плотность как вес: рыхлые окна берём реже, но не запрещаем.
    weights = [max(w["density"] - MIN_DENSITY, 0.01) for w in good]
    picker = rng or random
    return picker.choices(good, weights=weights, k=1)[0]


def verify(ref, cover, *, strength: str = "strong", want: float = WANT_SECONDS,
           rng=None, prefer=None) -> dict:
    """Хрома эталона и кавера -> вердикт.

    {"ok", "reason", "score", "norm", "shift", "tempo", "closeness",
     "at": секунда КАВЕРА, "length": сколько там же секунд соответствует окну,
     "ref_at", "density", "windows": сколько годных окон нашлось,
     "good": сами эти окна}.

    "good" отдаётся целиком нарочно: оно уже посчитано, а кэш (cover_cache)
    хранит его, чтобы в следующем паке взять у того же кавера ДРУГОЙ участок,
    не скачивая и не разбирая ролик заново."""
    empty = {"ok": False, "reason": "no_audio", "score": 0.0, "norm": 0.0,
             "shift": 0, "tempo": 0.0, "closeness": 0.0, "at": 0.0,
             "length": 0.0, "ref_at": 0.0, "density": 0.0, "windows": 0,
             "good": []}
    if ref is None or cover is None or not len(ref) or not len(cover):
        return empty
    result = audio.align(ref, cover)
    norm = normalized(result["score"], len(ref))
    verdict = dict(empty, reason="", score=round(float(result["score"]), 2),
                   norm=round(norm, 3), shift=result["shift"],
                   tempo=round(result["tempo"], 3),
                   closeness=closeness(norm, result["shift"], result["tempo"]))
    if norm < floor_for(strength):
        return dict(verdict, reason="not_the_song")
    good = windows(result["path"], len(ref) / audio.FPS, want)
    picked = choose(good, rng, prefer)
    if not picked:
        # Счёт есть, а связного окна нет: обычно кавер совпал коротким куском.
        return dict(verdict, reason="no_window", windows=0)
    begin, end = picked["cover"]
    return dict(verdict, ok=True, at=begin, length=round(end - begin, 2),
                ref_at=picked["at"], density=picked["density"],
                windows=len(good), good=good)
