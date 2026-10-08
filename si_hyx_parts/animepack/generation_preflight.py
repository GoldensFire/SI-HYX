"""Check quota bounds and explain scarce source combinations before media work."""
import animepack as ap
from music_effects import plan
from .level_avg import own_bucket, level_avg_target, BUCKET_TITLES


def average_problems(settings):
    groups = {}
    for kind, count in settings.question_quotas.items():
        if count:
            bucket = own_bucket(settings, kind)
            low, high = settings.level_range(kind)
            slots, minimum, maximum = groups.get(bucket, (0, 0, 0))
            groups[bucket] = slots + count, minimum + low * count, maximum + high * count
    problems = []
    for bucket, (slots, minimum, maximum) in groups.items():
        target = level_avg_target(settings, bucket)
        if target and not minimum <= target * slots <= maximum:
            where = BUCKET_TITLES.get(bucket, "пака")
            problems.append(f"Средняя сложность {where} {target} недостижима при выбранных квотах: "
                            f"возможный диапазон {minimum / slots:.1f}–{maximum / slots:.1f}.")
    return problems


def describe(generator):
    settings = generator.s
    quotas = settings.question_quotas
    if quotas.get(ap.MANGA_KIND):
        from .manga_preflight import describe as describe_comics
        describe_comics(generator)
    songs = sum(quotas.get(kind, 0) for kind in ap.SONG_KINDS)
    karaoke = plan(settings, songs).get("karaoke", 0)
    if karaoke and not settings.karaoke_ai_fallback and settings.karaoke_effect != "reverse":
        generator.log(f"Предварительная проверка караоке: нужно {karaoke} подтверждённых песен. "
                      "AI fallback выключен; наличие готовых таймингов проверяется до загрузки аудио. "
                      "Если доступного пула не хватит, готовые вопросы будут сохранены.")
    kinds = [kind for kind, selected in settings.kinds.items() if selected]
    if settings.only_kind != ap.MANGA_KIND and len(kinds) == 1 and kinds[0] == "movie":
        generator.log("Выбраны только фильмы: сериалы и OVA не входят в пул; "
                      "продолжения фильмов проходят обычные правила франшиз.")
