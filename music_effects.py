"""Musical presentation settings, independent of opening/ending/insert.

Способов подачи теперь несколько (оригинал, chiptune, кавер), и доля у каждого
своя. Раскладка по вопросам одна на все: слоты делятся заранее и перемешиваются
ОДНИМ зерном (chiptune_seed) — им и раньше решалось, каким вопросам достанется
эффект, поэтому сохранённые настройки продолжают давать тот же пак.

Неудачи считаются по эффектам врозь, потому что означают разное. У chiptune
неудача — это сбой настроек (не распозналась ведущая партия), и после предела
генерация обязана остановиться с объяснением. У кавера неудача — это «у песни
нет подтверждённого кавера», обычное дело: такой эффект после предела просто
уступает оставшиеся слоты оригиналу, а пак собирается дальше.
"""
from __future__ import annotations

import random
from pathlib import Path

VERSION = "chiptune-2"
MODEL = "htdemucs-955717e8+rmvpe-5370e71a+crepe-full-0.0.23"
ORIGINAL = "original"
EFFECTS = {ORIGINAL: "Оригинал", "chiptune": "Chiptune", "cover": "Кавер", "karaoke": "Караоке"}
# Эффекты, у которых череда неудач означает неверные настройки, а не пустой
# результат: такие останавливают генерацию.
STRICT = {"chiptune": ("Chiptune: слишком много неудачных распознаваний. "
                       "Проверьте фрагмент в прослушивании или смените "
                       "ведущую партию."),
          "karaoke": "Караоке: не хватает песен с подтверждённой версией и таймингами."}
# Сколько неудач терпим: по четыре на запланированный вопрос, но не меньше
# дюжины — иначе одиночный вопрос падал бы с первой же осечки.
FAILURES_PER_SLOT = 4
FAILURES_MIN = 12
# Сколько неудач ПОДРЯД, без единой удачи, означает «дело не в этой песне».
#
# Общего счёта неудач мало: при доле 100% на паке в 96 вопросов он равен 384, и
# полностью сломанный эффект (YouTube просит подтвердить, что ты не робот; нет
# yt-dlp; рамка сложности уже никому) грыз бы каталог часами, сжигая по тайтлу
# на каждую попытку. Череда же не зависит от размера пака: если эффект вообще
# работает, тридцать промахов подряд при живых удачах не выпадают.
FAILURES_STREAK = 30
# Сколько раз подряд эффект должен пожаловаться на поломку ЦЕЛИКОМ, прежде чем
# сдаться. Одной жалобы мало: YouTube отвечает «войдите в аккаунт» не всегда, а
# на всплеск запросов — в живом прогоне так отвалилась ровно первая песня из
# восьми, пока остальные семь искали и качали как обычно. Три подряд уже
# означают, что дело не в минутной осечке, и стоят пака ровно трёх тайтлов.
FATAL_STRIKES = 3


def runtime_python():
    return Path.home() / ".cache/si-hyx-chiptune/venv/Scripts/python.exe"


def shares(settings):
    """[(эффект, доля аудиовопросов в процентах)] — только включённые."""
    out = []
    if getattr(settings, "chiptune_enabled", False):
        out.append(("chiptune", int(getattr(settings, "chiptune_percent", 0))))
    if getattr(settings, "cover_enabled", False):
        out.append(("cover", int(getattr(settings, "cover_percent", 0))))
    if getattr(settings, "karaoke_enabled", False):
        out.append(("karaoke", int(getattr(settings, "karaoke_percent", 0))))
    return out


def slot_seed(settings):
    """Зерно раскладки слотов — общее на все способы подачи."""
    return int(getattr(settings, "chiptune_seed", 0) or 0)


def plan(settings, song_count):
    """{эффект: сколько аудиовопросов ему достанется}."""
    counts, left = {}, max(0, int(song_count or 0))
    for name, percent in shares(settings):
        if not song_count:
            counts[name] = 0
            continue
        counts[name] = min(left, max(1, (song_count * percent + 50) // 100))
        left -= counts[name]
    return counts


def validate(settings):
    errors = []
    total = 0
    for name, percent in shares(settings):
        total += percent
        if not 1 <= percent <= 100:
            errors.append(f"{EFFECTS[name]}: доля музыкальных вопросов должна "
                          "быть 1–100%.")
    if total > 100:
        errors.append("Доли способов подачи музыки вместе больше 100% — "
                      "последним не хватит вопросов.")
    if getattr(settings, "karaoke_enabled", False):
        from karaoke.render import EFFECT_LABELS
        if settings.karaoke_effect not in EFFECT_LABELS:
            errors.append("Караоке: неизвестный аудиоэффект.")
        if not .5 <= settings.karaoke_tempo <= 2:
            errors.append("Караоке: темп должен быть от 0.5 до 2.")
        if not -12 <= settings.karaoke_pitch <= 12:
            errors.append("Караоке: высота тона от −12 до +12 полутонов.")
        if not 0 <= settings.karaoke_crf <= 63:
            errors.append("Караоке: CRF должен быть от 0 до 63.")
        if not 0 <= settings.karaoke_preset <= 13:
            errors.append("Караоке: пресет кодирования должен быть от 0 до 13.")
    if getattr(settings, "cover_enabled", False):
        low = int(getattr(settings, "cover_amq_from", 0))
        high = int(getattr(settings, "cover_amq_to", 100))
        if (getattr(settings, "cover_similarity_enabled", True)
                and (not 0 <= low <= 100 or not 0 <= high <= 100
                     or low > high)):
            errors.append("Каверы: схожесть с оригиналом задаётся от 0 до 100%, "
                          "и «от» не может быть больше «до».")
        if not 1 <= int(getattr(settings, "cover_pool", 3)) <= 12:
            errors.append("Каверы: набирать можно от 1 до 12 исполнений на песню.")
    if not settings.chiptune_enabled:
        return errors
    if settings.chiptune_version != VERSION:
        errors.append("Chiptune: неизвестная версия обработки; сбросьте настройки режима.")
    if settings.chiptune_lead not in ("auto", "vocals", "other"):
        errors.append("Chiptune: ведущая партия должна быть auto, vocals или other.")
    if not 1 <= settings.chiptune_lead_volume <= 100 or not 0 <= settings.chiptune_bass_volume <= 70:
        errors.append("Chiptune: громкость мелодии 1–100%, баса 0–70%.")
    if not 0 <= settings.chiptune_seed <= 2147483647:
        errors.append("Chiptune: зерно должно быть целым числом 0–2147483647.")
    if not Path(settings.chiptune_python or runtime_python()).is_file():
        errors.append("Chiptune: установите обработчик кнопкой «Установить модели» "
                      "или укажите Python его окружения.")
    return errors


def processing_options(settings):
    return {"version": settings.chiptune_version, "model": MODEL,
            "seed": settings.chiptune_seed, "lead": settings.chiptune_lead,
            "lead_volume": settings.chiptune_lead_volume / 100,
            "bass_volume": settings.chiptune_bass_volume / 100}


class EffectSlots:
    """Reserve presentation slots before parallel downloads; retry failed slots."""

    def __init__(self, settings, song_count):
        self.counts = plan(settings, song_count)
        self.slots = [name for name, count in self.counts.items()
                      for _ in range(count)]
        self.slots += [ORIGINAL] * max(0, song_count - len(self.slots))
        random.Random(slot_seed(settings)).shuffle(self.slots)
        self.free = list(range(song_count))
        self.failures = 0
        self.failed = {}
        self.limits = {name: max(FAILURES_MIN, count * FAILURES_PER_SLOT)
                       for name, count in self.counts.items()}
        # Неудачи ПОДРЯД у каждого эффекта: обнуляются первой же удачей.
        self.streak = {}
        # Жалобы «сломан весь эффект» подряд — см. FATAL_STRIKES.
        self.fatal = {}
        # Эффекты, уступившие оставшиеся слоты оригиналу (читает select_songs).
        self.dropped = []
        # Почему эффект сдался — для журнала (читает select_songs).
        self.reasons = {}

    def reserve(self, candidate):
        slot = self.free.pop(0)
        candidate.music_effect = self.slots[slot]
        candidate.music_slot = slot

    def expand(self, settings, song_count):
        if song_count <= len(self.slots):
            return
        target = EffectSlots(settings, song_count)
        extra = song_count - len(self.slots)
        additions = []
        for name, count in target.counts.items():
            if name in self.dropped:
                continue
            additions += [name] * max(0, count - self.counts.get(name, 0))
        additions = additions[:extra]
        additions += [ORIGINAL] * (extra - len(additions))
        random.Random(slot_seed(settings) + len(self.slots)).shuffle(additions)
        self.free.extend(range(len(self.slots), song_count))
        self.slots.extend(additions)
        self.counts = target.counts
        self.limits = target.limits

    def release(self, candidate):
        """Слот освобождается: вопрос с этим эффектом не получился.

        `candidate.music_failure` — то, что сломалось НЕ в этой песне, а во
        всём эффекте разом (нет yt-dlp, YouTube просит подтвердить, что ты не
        робот). Такое не перебирается кандидатами, поэтому эффект сдаётся после
        FATAL_STRIKES жалоб подряд, а не через сотни попыток."""
        self.free.insert(0, candidate.music_slot)
        name = candidate.music_effect
        if name == ORIGINAL:
            return
        self.failed[name] = self.failed.get(name, 0) + 1
        self.streak[name] = self.streak.get(name, 0) + 1
        self.failures = sum(self.failed.values())
        fatal = str(getattr(candidate, "music_failure", "") or "").strip()
        if fatal:
            self.fatal[name] = self.fatal.get(name, 0) + 1
            if self.fatal[name] >= FATAL_STRIKES:
                self.quit(name, fatal)
            return
        # Обычная неудача означает, что эффект вообще-то работает: жалобу на
        # поломку целиком после неё считаем заново.
        self.fatal[name] = 0
        if self.streak[name] >= FAILURES_STREAK:
            self.quit(name, f"{FAILURES_STREAK} неудач подряд, ни одной удачи")
            return
        if self.failed[name] < self.limits.get(name, FAILURES_MIN):
            return
        self.quit(name, f"неудач набралось {self.failed[name]}")

    def give_back(self, candidate):
        """Слот возвращается БЕЗ неудачи: вопрос готов, но места ему не нашлось
        (пока качали, квоту заняли другие). Эффект тут ни при чём."""
        self.free.insert(0, candidate.music_slot)

    def succeed(self, candidate):
        """Вопрос с эффектом дошёл до пака — череда неудач прервана."""
        name = candidate.music_effect
        if name != ORIGINAL:
            self.streak[name] = 0
            self.fatal[name] = 0

    def quit(self, name, reason):
        """Эффект больше не пробуем. Строгий обрывает пак, остальные уступают."""
        self.reasons.setdefault(name, reason)
        if name in STRICT:
            raise RuntimeError(f"{STRICT[name]} ({reason})")
        self.give_up(name)

    def give_up(self, name):
        """Эффект не получается — оставшиеся его слоты играют оригиналом.

        Так ведут себя каверы: «у песни нет подтверждённого кавера» — не повод
        обрывать пак, а повод собрать вопрос обычным способом.

        Свободные слоты переписываются на КАЖДОМ заходе, а не только на первом.
        В момент отказа часть слотов занята качающимися вопросами, и они
        возвращаются в оборот уже после него (release кладёт слот обратно в
        free). Ранний выход по `name in self.dropped` оставлял бы их прежними —
        и восемь занятых слотов крутились бы по кругу до конца каталога:
        живой прогон сжёг так 860 годных тайтлов и набрал 63 вопроса из 96."""
        if name not in self.dropped:
            self.dropped.append(name)
        for slot in self.free:
            if self.slots[slot] == name:
                self.slots[slot] = ORIGINAL
