# -*- coding: utf-8 -*-
"""Metadata gate: is a YouTube result a cover PERFORMANCE of this exact song.

Почему гейт по заголовку вообще нужен и почему он важнее самого CSI. Проверка
звука (cover_audio + cover_match) отвечает на вопрос «та ли это композиция» и
отвечает хорошо: 0 ложных срабатываний на 2662 чужих парах. Но реакция на
опенинг, фортепианный ТУТОРИАЛ, lyric-видео и сырой рип содержат ровно ту же
музыку — на замерах они набрали 314, 113 и 371 очка там, где порог 60. Отсечь их может только
текст вокруг видео. Поэтому здесь белый список: без маркера ИСПОЛНЕНИЯ кандидат
не проходит, как бы хорошо ни звучал.

Словарь выражений — в cover_meta_rules. Ни сети, ни Qt: модуль зовут и
генератор, и вкладка, и tools/cover_probe.py.
"""
from __future__ import annotations

import cover_meta_rules as rules
from cover_meta_rules import cover_type, normalize

# Ниже порогов — shorts и нарезки, выше — сборники, разборы и часовые петли.
# На размеченном корпусе настоящие каверы укладывались в 51…415 с; единственный
# вышедший за предел — восьмиминутный «Piano Cover (Full Extended)».
MIN_SECONDS = 40
MAX_SECONDS = 420
# Порог просмотров: ниже него почти всегда лежит запись с телефона, спетая мимо
# нот, — на корпусе такие набирали десятки просмотров, а разобранные настоящие
# каверы начинались с трёхзначных (просьба пользователя — низкокачественные
# каверы не брать). Порог намеренно низкий: у кавера песни из безвестного
# тайтла тысячи просмотров не наберётся никогда, и жёсткий отбор оставил бы
# полкаталога без вопросов.
MIN_VIEWS = 500

# Кандидат назвал песню -> "strong"; назвал только аниме или исполнителя ->
# "weak" (у тайтла бывает три ED, и какой именно спели, решает уже звук — но по
# строгому порогу, см. cover_match). Ни того, ни другого -> отказ.
STRONG, WEAK = "strong", "weak"
# Сколько слабых пускать в пул: они дают recall на вставках, но у плодовитого
# исполнителя их десятки, и каждый стоит отдельной загрузки.
WEAK_LIMIT = 4


def song_ref(row: dict, siblings=()) -> dict:
    """Из строки AnisongDB — то, что нужно гейту и поиску.

    `siblings` — названия ОСТАЛЬНЫХ песен этого же аниме. Они приезжают тем же
    запросом AnisongDB, ничего не стоят и закрывают самую неприятную коллизию:
    кавер другого OP/ED того же тайтла и медли из двух его песен."""
    titles = [row.get("animeENName"), row.get("animeJPName")]
    titles += list(row.get("animeAltName") or [])
    titles = [str(t).strip() for t in titles if str(t or "").strip()]
    artist = str(row.get("songArtist") or "").strip()
    name = str(row.get("songName") or "").strip()
    song_keys = [normalize(name)] if name else []
    anime_keys = [normalize(t) for t in titles]
    return {
        # В заголовках тайтл зовут коротко: «Evangelion» вместо «Neon Genesis
        # Evangelion», «FMA BROTHERHOOD» вместо «Fullmetal Alchemist:
        # Brotherhood». Поэтому к полным названиям добавляем их отдельные
        # длинные слова — это вернуло семь настоящих каверов из корпуса. Только
        # для СЛАБОГО совпадения: «Yuusha» (герой) есть в названии десятка
        # тайтлов, тождества оно не доказывает.
        "anime_word_keys": sorted(
            {word for title in titles for word in rules.tokens(title)
             if len(word) >= ANIME_WORD} - set(anime_keys)),
        "song_id": str(row.get("annSongId") or row.get("amqSongId") or ""),
        "song": name, "artist": artist,
        "type": str(row.get("songType") or "").strip(),
        "anime": titles, "song_keys": song_keys, "anime_keys": anime_keys,
        "artist_keys": [normalize(artist)] if artist else [],
        # Имя соседней песни берём не всякое. Совпадающее с нашим — нельзя,
        # иначе песня отвергала бы саму себя (у аниме бывают две записи одной
        # композиции). Совпадающее с названием АНИМЕ — тоже нельзя: у
        # «Tsukigakirei» так зовётся эндинг, и этот «сосед» находился в каждом
        # втором заголовке просто потому, что там назван тайтл, — двадцать
        # настоящих каверов опенинга улетали как медли.
        "sibling_keys": [k for k in (normalize(s) for s in siblings)
                         if k and k not in song_keys
                         and not any(k in a or a in k for a in anime_keys)],
        # Имя песни совпало с именем аниме («Tsuki ga Kirei» — и ED, и тайтл).
        # Тогда совпадение по названию не доказывает ничего: под него подходят
        # каверы всех песен этого аниме и любых песен с той же фразой.
        "degenerate": any(k and (k in a or a in k)
                          for k in song_keys for a in anime_keys),
    }


# Латинское имя короче этого ищется только ЦЕЛЫМ словом (см. _matches).
WHOLE_WORD_BELOW = 8
# Короче этого слово названия аниме в ключи не берём: «Titan», «Ghoul», «Gate»
# встречаются в заголовках сами по себе.
ANIME_WORD = 6


def _matches(keys, haystack: str, title_tokens=()) -> bool:
    """Названо ли в заголовке хоть одно из имён.

    Латиницу ищем по словам, японский — подстрокой, и это не прихоть: в
    латинском заголовке слова разделены, поэтому попадание внутрь слова —
    случайность («Over» внутри «cover», «Ana» внутри «Clannad», «Rain» внутри
    «Rainych»), а в японском разделителей нет вовсе, и «進撃の巨人ED» обязано
    совпасть с «進撃の巨人»."""
    for key in keys:
        if len(key) < 3:
            continue
        if key.isascii() and len(key) < WHOLE_WORD_BELOW:
            if rules.token_run(key, title_tokens):
                return True
        elif key in haystack or rules.fold(key) in rules.fold(haystack):
            return True
    return False


def _position_clash(title: str, song_type: str) -> bool:
    """Заголовок называет ДРУГУЮ позицию: опенинг там, где нужен эндинг.

    Проверяем только вид (OP против ED), но не номер: номера в чужих
    метаданных расходятся сплошь и рядом, и отказ по ним стоил бы recall."""
    kind = song_type.lower()
    wanted_op = kind.startswith("opening")
    wanted_ed = kind.startswith("ending")
    if not (wanted_op or wanted_ed):
        return False                    # у вставки позиции нет
    has_op = bool(rules.OPENING_TOKEN.search(title))
    has_ed = bool(rules.ENDING_TOKEN.search(title))
    if has_op and has_ed:
        return False                    # назвали оба — пусть решает звук
    return (wanted_op and has_ed) or (wanted_ed and has_op)


def classify(title, channel="", duration=0, song=None, views=None) -> dict:
    """Вердикт по одному результату поиска.

    {"state": "ok"|"rejected", "reason": <слаг>, "strength", "via", "type"}.
    Слаг причины нужен, чтобы cover_probe складывал статистику отказов, а
    вкладка могла объяснить пользователю, что произошло."""
    song = song or {}
    title = str(title or "")
    channel = str(channel or "")

    def no(reason):
        return {"state": "rejected", "reason": reason, "strength": "",
                "via": "", "type": cover_type(title, channel)}

    try:
        seconds = int(float(duration or 0))
    except (TypeError, ValueError):
        seconds = 0
    if seconds < MIN_SECONDS:
        return no("too_short")
    if seconds > MAX_SECONDS:
        return no("too_long")
    # Просмотры знает только поиск. Их отсутствие (None) — это «неизвестно», а
    # не «ноль»: так зовут classify из тестов и из старых записей кладовой, где
    # поля ещё не было, и отбирать по нему там нечего.
    if views is not None:
        try:
            if int(views) < MIN_VIEWS:
                return no("low_views")
        except (TypeError, ValueError):
            pass

    # Мусорные признаки ищем ТОЛЬКО в заголовке. По каналу это уже ломалось:
    # «Animenz Piano Sheets» содержит sheets, и настоящий фортепианный кавер
    # улетал как туториал.
    text = rules.prepare(title)
    for reason, pattern in rules.JUNK:
        if pattern.search(text):
            return no(reason)
    performed = bool(rules.PERFORMED.search(text))
    if not performed:
        for reason, pattern in rules.SOFT_JUNK:
            if pattern.search(text):
                return no(reason)
    if rules.OFFICIAL_CHANNEL.search(rules.prepare(channel)):
        return no("official_channel")

    words = rules.tokens(title)
    key = "".join(words)
    named_song = _matches(song.get("song_keys") or [], key, words)
    degenerate = bool(song.get("degenerate"))
    # Порядок проверок задаёт не исход, а ПРИЧИНУ отказа: пока не известно, что
    # кандидат вообще про нашу песню, «не та позиция» объясняло бы неверно.
    named_anime = (_matches(song.get("anime_keys") or [], key, words)
                   or _matches(song.get("anime_word_keys") or [], key, words))
    if not (named_song or named_anime
            or _matches(song.get("artist_keys") or [], key, words)):
        return no("name_mismatch")
    if _matches(song.get("sibling_keys") or [], key, words):
        # Названы и наша песня, и соседняя — это медли, из него вопрос не
        # вырезать. Названа только соседняя — это её кавер, а не наш. При
        # вырожденном имени «названа наша» ничего не доказывает.
        return no("medley" if named_song and not degenerate else "other_song")
    if _position_clash(text, str(song.get("type") or "")):
        return no("wrong_position")

    if named_song and not degenerate:
        strength, via = STRONG, "song"
    elif named_song or named_anime:
        # Назвали только аниме (или название песни неотличимо от названия
        # аниме). «Tokyo Ghoul - Ending | Saints» тоже сюда: годный кавер, у
        # которого в заголовке переведённое название песни.
        strength, via = WEAK, "song" if named_song else "anime"
    elif _matches(song.get("artist_keys") or [], key, words):
        # Назвали только исполнителя. Нужно вставкам: AnisongDB пишет
        # «3-gatsu 9-ka», а мир — «Sangatsu Kokonoka» и «3月9日», и по названию
        # песни два десятка настоящих каверов не находились вовсе. Зато у
        # плодовитого исполнителя так приходят каверы ДРУГИХ его песен —
        # поэтому их число ограничено (WEAK_LIMIT), а решает всё равно звук.
        strength, via = WEAK, "artist"

    if not (performed or rules.INSTRUMENT.search(text)
            or rules.nickname_tag(text)):
        return no("no_performance_marker")
    return {"state": "ok", "reason": "", "strength": strength, "via": via,
            "type": cover_type(title, channel)}


def screen(candidates, song, limit: int = 12,
           weak_limit: int = WEAK_LIMIT) -> tuple[list, list]:
    """Прогоняет результаты поиска -> (принятые, отклонённые).

    Принятые отсортированы так, чтобы первыми качались самые надёжные: назвавшие
    песню, потом аниме, потом исполнителя. Просмотры в сортировку НЕ входят: пул
    нужен разнообразный, а малопросматриваемый кавер ничем не хуже."""
    order = {"song": 0, "anime": 1, "artist": 2}
    ok, bad = [], []
    for cand in candidates:
        verdict = classify(cand.get("title"), cand.get("channel"),
                           cand.get("duration"), song, cand.get("views"))
        row = dict(cand, **verdict)
        (ok if verdict["state"] == "ok" else bad).append(row)
    ok.sort(key=lambda r: order.get(r.get("via"), 3))
    strong = [r for r in ok if r["strength"] == STRONG]
    weak = [r for r in ok if r["strength"] != STRONG][:max(0, int(weak_limit))]
    return (strong + weak)[:max(1, int(limit))], bad
