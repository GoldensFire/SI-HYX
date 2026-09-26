"""Каверы подключаются к тому же загрузчику звука, что и оригинал.

Вопрос-кавер — это обычный песенный вопрос, у которого вместо отрезка с CDN
играет чужое исполнение той же композиции с YouTube. Всё остальное — ответ,
подсказка, цена, постер — остаётся прежним, поэтому здесь только звук.

Неудача кавера НЕ роняет пак: у песни может не оказаться ни одного
подтверждённого исполнения, и это обычное дело. Загрузчик возвращает False,
слот освобождается, и место занимает следующий кандидат (см. EffectSlots).
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

import animepack as _api
import cover_cache
import cover_match
import cover_meta
from cover_meta_rules import cover_language
from cover_search import fatal_reason
from cover_service import CoverService, ytdlp_command

try:
    from config import ytdlp_base_cmd
except Exception:  # pragma: no cover — генератор должен жить и без конфига
    def ytdlp_base_cmd():
        return None

# Сколько кандидатов держим в пуле одной песни. Больше двенадцати гейт и так не
# отдаёт (cover_meta.screen), а каждый — это отдельная загрузка.
COVER_LIMIT = 12


def cover_service(generator):
    """Один сервис на генерацию: у него общий пул потоков и счётчик типов."""
    service = getattr(generator, "_cover_service", None)
    if service is None:
        def run(command, timeout=120):
            return generator._run_capture(command, timeout)
        service = CoverService(run, _api.FFMPEG, ytdlp_command(ytdlp_base_cmd()),
                               stopped=generator.stopped, log=generator.log,
                               workers=max(1, min(16, int(generator.s.parallel))),
                               cache_enabled=bool(getattr(
                                   generator.s, "poster_cache", True)),
                               # Даже без процентного фильтра звук проверяется:
                               # сетевой поток остаётся один, чтобы YouTube не
                               # закрыл IP всплеском параллельных загрузок.
                               net_limit=1)
        generator._cover_service = service
    return service


def wanted_cover(settings):
    """Рамка пользователя: процент схожести и виды исполнения.

    Проверка «та ли это композиция» выполняется до этой рамки всегда. Галочка
    `cover_similarity_enabled` управляет только дополнительным отбором по
    измеренной схожести 0…100%, а не самой проверкой звука. Старые имена
    настроек cover_amq_* сохранены для совместимости.

    Пустой список типов — любые. Рамка проверяется ДО того, как пул наберётся
    (см. CoverService.ensure): иначе на узкой рамке мы набирали бы три кавера и
    все три выбрасывали.

    Язык отбирается отдельно от вида (просьба пользователя): «кавер на другом
    языке» бывает и вокальным, и band-овым, а слушать испанский фандаб хочется
    не всякому. Записи, у которых язык в заголовке не назван, не трогает ни
    один режим — «неизвестно» это не «другой язык», и отбрасывать по нему
    значило бы выбросить заодно все японские исполнения."""
    low = max(0, min(100, int(settings.cover_amq_from)))
    high = max(low, min(100, int(settings.cover_amq_to)))
    check_similarity = bool(getattr(settings, "cover_similarity_enabled", True))
    kinds = {str(kind) for kind in (settings.cover_types or ()) if kind}
    # Планка «чтобы совсем плохих не было» (просьба пользователя). Ноль в самой
    # записи значит «неизвестно»: лайки поиск YouTube отдаёт не всегда, и
    # выбрасывать по неизвестному числу нельзя — иначе пул опустел бы.
    min_views = max(0, int(getattr(settings, "cover_min_views", 0) or 0))
    min_likes = max(0, int(getattr(settings, "cover_min_likes", 0) or 0))
    langs = {str(name) for name in (getattr(settings, "cover_langs", None)
                                    or ()) if name}
    only_langs = str(getattr(settings, "cover_lang_mode", "allow")) != "exclude"

    def keep(row):
        if kinds and str(row.get("type") or "") not in kinds:
            return False
        if langs:
            spoken = cover_language(row.get("title") or "",
                                    row.get("channel") or "")
            if spoken and (spoken in langs) is not only_langs:
                return False
        views = int(row.get("views") or 0)
        if min_views and 0 < views < min_views:
            return False
        likes = int(row.get("likes") or 0)
        if min_likes and 0 < likes < min_likes:
            return False
        if check_similarity:
            similarity = cover_match.similarity_percent(
                row.get("closeness") or 0.0)
            return low <= similarity <= high
        return True
    return keep


def cover_record(got, length) -> dict:
    """Что именно прозвучало — для covers.json и для памяти о повторах."""
    return {"video": got.get("id", ""),
            "url": f"https://www.youtube.com/watch?v={got.get('id', '')}",
            "title": got.get("title", ""), "channel": got.get("channel", ""),
            "type": got.get("type", ""), "strength": got.get("strength", ""),
            # Язык считается из заголовка (cover_meta_rules) — тот же, что
            # уйдёт в подсказку вопроса. В covers.json он нужен, чтобы по
            # готовому паку было видно, на чём перепето.
            "language": cover_language(got.get("title") or "",
                                       got.get("channel") or ""),
            "at": round(float(got.get("at") or 0.0), 2),
            "length": round(float(length), 2),
            "ref_at": round(float(got.get("ref_at") or 0.0), 2),
            "norm": round(float(got.get("norm") or 0.0), 3),
            "similarity_checked": bool(got.get("similarity_checked", True)),
            "closeness": (round(float(got.get("closeness") or 0.0), 3)
                          if got.get("similarity_checked", True) else None),
            "shift": int(got.get("shift") or 0),
            "tempo": round(float(got.get("tempo") or 0.0), 3)}


def download_cover(generator, candidate) -> bool:
    """Ищет, проверяет и режет кавер вместо отрезка с CDN."""
    settings = generator.s
    destination = Path(generator.folder) / "Audio" / candidate.audio_out
    # Обычно это уже гарантировал filter_song. Повторная узкая проверка не
    # даёт устаревшему/стороннему кандидату обойти реальную рамку songDifficulty.
    if (candidate.song.get("songDifficulty") is not None
            and not _api.song_difficulty_allowed(candidate.song, settings)):
        generator.log(f"Кавер «{candidate.song_name}»: сложность песни AMQ "
                      f"{candidate.difficulty:g} вне заданной рамки — "
                      "беру следующего кандидата.")
        return False
    song = cover_meta.song_ref(candidate.song, candidate.siblings)
    if not (song.get("song_id") and song.get("song") and candidate.audio_file):
        generator.log(f"Кавер «{candidate.title_ru}»: у песни нет названия или "
                      "эталона — беру следующего кандидата.")
        return False
    seconds = max(1.0, float(settings.audio_cut))
    try:
        with tempfile.TemporaryDirectory(prefix="cover-",
                                         dir=generator.folder) as directory:
            work = Path(directory)
            keep_cover = wanted_cover(settings)
            # Название ролика — только первый гейт. Даже когда пользователь не
            # фильтрует исполнения по проценту схожести, звук обязан доказать,
            # что это та же композиция. Иначе «Promare … Ashes (Cover)»
            # проходит к Inferno лишь по названию аниме.
            reference = cover_service(generator).reference(
                song["song_id"],
                lambda: generator._cached_bytes(
                    f"{_api.AMQ_CDN}/{candidate.audio_file}", "amq-audio",
                    _api._MIN_AUDIO_BYTES),
                work)
            rows = cover_service(generator).ensure(
                song, reference, work,
                want=max(1, int(settings.cover_pool)), limit=COVER_LIMIT,
                seconds=seconds, keep=keep_cover)
            if generator.stopped():
                return False
            if not rows:
                generator.log(f"Кавер «{candidate.song_name}»: подходящих "
                              "исполнений не нашлось — беру следующего "
                              "кандидата.")
                return False
            output = work / destination.name
            while rows:
                got = cover_service(generator).choose(
                    song, rows, rng=generator.rng,
                    prefer=candidate.trim_start)
                # Защита на границе выбора: даже сервис-подмена или старый
                # кэш не может протащить исполнение за рамкой.
                if not got or not keep_cover(got):
                    return False
                length = max(1.0, min(seconds, float(got["length"])))
                try:
                    cover_service(generator).cut(
                        got["id"], got["at"], length, output, work,
                        generator.audio_encode_args(length))
                    break
                except Exception as error:  # noqa: BLE001 — пробуем соседа
                    if fatal_reason(error):
                        raise
                    output.unlink(missing_ok=True)
                    cover_cache.remember_failure(song["song_id"], got["id"],
                                                 str(error))
                    rows = [row for row in rows
                            if str(row.get("id")) != str(got.get("id"))]
                    generator.log(
                        f"Кавер «{candidate.song_name}»: ролик недоступен — "
                        "пробую другое исполнение той же песни.")
            else:
                return False
            if generator.stopped():
                return False
            output.replace(destination)
            cover_cache.remember_use(song["song_id"], got["id"], got.get("ref_at"))
            candidate.music_processing = cover_record(got, length)
            if got.get("similarity_checked", True):
                similarity = cover_match.similarity_percent(
                    got.get("closeness") or 0.0)
                checked = f"схожесть с оригиналом {similarity}%"
            else:
                checked = "схожесть с оригиналом не проверялась"
            generator.log(f"Кавер «{candidate.song_name}»: {got.get('title')} "
                          f"({got.get('type')}, {checked}, сложность песни AMQ "
                          f"{candidate.difficulty:g}), с {got['at']:.0f}-й "
                          "секунды.")
            return True
    except Exception as error:  # noqa: BLE001 — кандидат, а не пак
        try:
            destination.unlink(missing_ok=True)
        except OSError:  # pragma: no cover — файл мог быть занят
            pass
        # Сломан весь эффект или только эта песня — разные вещи: первое надо
        # сказать один раз и бросить, иначе пак часами перебирает тайтлы, а
        # ответ у YouTube на все один и тот же.
        fatal = fatal_reason(error)
        if fatal:
            candidate.music_failure = fatal
            # Говорим один раз на прогон: в этот миг то же самое прилетает
            # каждому из потоков, уже качавших свой кавер. И не обещаем, что
            # каверы уже отключились: одна такая жалоба бывает и минутной
            # осечкой, а сдаются они только после FATAL_STRIKES подряд (см.
            # music_effects.EffectSlots.release). Итог пишет select_songs.
            if not getattr(generator, "_cover_broken", ""):
                generator._cover_broken = fatal
                generator.log(f"Каверы: {fatal}. Пробую ещё несколько песен — "
                              "если повторится, музыкальные вопросы пойдут "
                              "оригиналом.")
            return False
        generator.log(f"Кавер «{candidate.title_ru}»: {error} — беру "
                      "следующего кандидата.")
        return False


def covers_manifest(songs, settings) -> str:
    """covers.json: какой ролик и какой его участок прозвучал в каждом вопросе.

    Нужен и для воспроизводимости («откуда это исполнение»), и человеку —
    чтобы по готовому паку было видно, что именно он слушает."""
    questions = [{"file": candidate.audio_out, "song": candidate.song_name,
                  "anime": candidate.title_ru, "source": candidate.audio_file,
                  "cover": candidate.music_processing}
                 for candidate in songs if candidate.music_effect == "cover"]
    if not questions:
        return ""
    if any(not row["cover"] for row in questions):
        raise ValueError("Кавер: нельзя упаковать вопрос без подтверждённого "
                         "исполнения.")
    similarity_band = [settings.cover_amq_from, settings.cover_amq_to]
    return json.dumps({"percent": settings.cover_percent,
                       "pool": settings.cover_pool,
                       # Проверка композиции обязательна; эта галочка включает
                       # только дополнительный отбор по процентному диапазону.
                       "identity_check": True,
                       "similarity_filter": bool(getattr(
                           settings, "cover_similarity_enabled", True)),
                       # Старый ключ оставлен читателям прежних covers.json.
                       "amq": similarity_band,
                       "similarity": similarity_band,
                       "types": list(settings.cover_types or ()),
                       "langs": list(getattr(settings, "cover_langs", None)
                                     or ()),
                       "lang_mode": str(getattr(settings, "cover_lang_mode",
                                                "allow")),
                       "cut": settings.audio_cut, "questions": questions},
                      ensure_ascii=False, indent=2)
