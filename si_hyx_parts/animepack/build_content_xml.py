# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""build_content_xml. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


def build_content_xml(songs: list, s: _api.PackSettings,
                      author: str = _api.PACK_AUTHOR) -> bytes:
    """SIQ 5: раунды → темы → вопросы. Вопросы внутри темы идут по возрастанию
    цены (в ASPG порядок был случайный, и таблица в SIGame выглядела рвано)."""
    from . import pack_summary
    pkg = _api.ET.Element("package", {
        # Номер и средняя сложность приписываются к названию, чтобы собранные
        # подряд паки различались (просьба пользователя).
        "name": (pack_summary.pack_title(
            s.title, getattr(s, "pack_number", 0), songs,
            test_number=getattr(s, "test_pack_number", 0),
            ignore_test_packs=getattr(s, "ignore_test_packs", False))
                 or "Generated Songs Anime Pack"),
        "version": "5",
        "id": str(_api.uuid.uuid4()),
        "date": _api.date.today().strftime("%d.%m.%Y"),
        "xmlns": _api.SIQ_NS,
    })
    tags = _api.ET.SubElement(pkg, "tags")
    _api.ET.SubElement(tags, "tag").text = "Аниме"
    info = _api.ET.SubElement(pkg, "info")
    authors = _api.ET.SubElement(info, "authors")
    _api.ET.SubElement(authors, "author").text = author
    # Раскладку считаем ДО комментариев: цены и роды вопросов проставляет
    # именно она, а состав пака пишется уже по ним.
    themes = _api.arrange_questions(songs, s)
    comments = pack_summary.composition_text(songs, s, _api.KIND_TITLES,
                                             _api.VIDEO_KIND)
    if comments:
        _api.ET.SubElement(info, "comments").text = comments
    rounds_el = _api.ET.SubElement(pkg, "rounds")

    per_round = max(1, int(s.themes))
    for r in range(max(1, int(s.rounds))):
        chunk = themes[r * per_round:(r + 1) * per_round]
        if not chunk:
            break
        round_el = _api.ET.SubElement(rounds_el, "round", {"name": f"Раунд {r + 1}"})
        themes_el = _api.ET.SubElement(round_el, "themes")
        for theme in chunk:
            theme_el = _api.ET.SubElement(themes_el, "theme",
                                     {"name": s.theme_title or "SONGS ONLY"})
            questions_el = _api.ET.SubElement(theme_el, "questions")
            for cand in theme:
                _api._append_question(questions_el, cand, s)
    return _api.ET.tostring(pkg, encoding="utf-8", xml_declaration=True)

build_content_xml.__module__ = _api.__name__
_api.build_content_xml = build_content_xml

def _append_question(questions_el, cand: _api.SongCandidate, s: _api.PackSettings) -> None:
    price = cand.price or _api.price_for_difficulty(cand.difficulty)
    q = _api.ET.SubElement(questions_el, "question", {"price": str(price)})
    params = _api.ET.SubElement(q, "params")

    # ── Вопрос: текст, кадр, ролик ЛИБО аудио (фоном) с коллажем и подсказкой ─
    q_param = _api.ET.SubElement(params, "param", {"name": "question", "type": "content"})
    if cand.is_character:
        # Задание показывается одновременно с портретом или видео появления.
        task = _api.ET.SubElement(q_param, "item", {"waitForFinish": "False"})
        task.text = _api.CHAR_TASK_TEXT
    from .entrance_content import append_question
    if not cand.is_studio and append_question(q_param, cand):
        _api._append_answer(params, q, cand, s)
        return
    if cand.kind == _api.DESCRIPTION_AUDIO_KIND:
        if cand.description_audio_ext:
            audio = _api.ET.SubElement(q_param, "item", {
                "type": "audio", "isRef": "True", "placement": "background"})
            audio.text = cand.audio_out
        else:
            _api.ET.SubElement(q_param, "item").text = cand.description_text
    elif cand.is_text:
        # Вопрос из одного текста — анаграмма или пересказ сюжета. У пересказа
        # задание идёт ПЕРЕД текстом и с waitForFinish="False", как у портрета
        # персонажа: без него это просто рассказ, и непонятно, что называть.
        # У анаграммы подписи нет вовсе (просьба пользователя): перемешанные
        # прописные буквы говорят сами за себя.
        # Подпись нужна только режиму «ответ — название аниме». В режиме
        # «ответ — деталь сюжета» тайтл в вопросе назван прямо, и «Назвать
        # аниме по сюжету» там было прямой ложью (просьба пользователя):
        # непустые plot_answers и значат этот режим.
        if cand.kind == _api.PLOT_KIND and not cand.plot_answers:
            task = _api.ET.SubElement(q_param, "item", {"waitForFinish": "False"})
            task.text = _api.PLOT_TASK_TEXT
        text = cand.question_text
        attrs = {}
        # Одна настройка скорости действует на все текстовые вопросы: анаграммы,
        # сюжет и преобразования названия. Ноль оставляет текст до ответа.
        seconds = _api.anagram_seconds(text, getattr(s, "anagram_cps",
                                                _api.ANAGRAM_CHARS_PER_SEC))
        if seconds:
            attrs["duration"] = _api.fmt_duration(seconds)
        body = _api.ET.SubElement(q_param, "item", attrs)
        body.text = text
    elif cand.is_pixel:
        # Кадр с эффектом: ролик постепенно раскрывает исходную картинку.
        # Добавочных секунд после ролика нет (просьба пользователя): вопрос
        # длится ровно столько же, сколько сам файл.
        video = _api.ET.SubElement(q_param, "item", {
            "type": "video", "isRef": "True",
            "duration": _api.fmt_duration(s.pixel_seconds)})
        video.text = cand.entrance_video or cand.video_out
    elif cand.is_episode or cand.is_sakuga:
        # Отрывок серии со звуком или сакуга без звука. Таймера у них нет
        # ВОВСЕ (просьба пользователя): duration не пишем, и вопрос стоит,
        # пока ведущий не перейдёт дальше, — отрывок в несколько секунд иначе
        # закрывался бы раньше, чем игроки успевают сообразить.
        video = _api.ET.SubElement(q_param, "item", {
            "type": "video", "isRef": "True"})
        video.text = cand.entrance_video or cand.video_out
    elif cand.is_studio:
        # Надпись показывается одновременно с каждым кадром студии.
        from .studio_question import append_items
        append_items(q_param, cand, s)
    elif cand.is_picture:
        # Вопрос-картинка: песни нет, показывается кадр тайтла либо портрет
        # персонажа. Портрет персонажа имеет четырёхсекундный таймер.
        from .entrance_content import append_image
        append_image(q_param, cand, cand.frame_file, 4 if cand.is_character else None)
    else:
        # Подсказка «Опенинг/Эндинг/OST» идёт ПЕРЕД дорожкой и с
        # waitForFinish="False": так текст выводится одновременно с песней и
        # висит на экране, пока она играет. Раньше он стоял последним и
        # показывался уже ПОСЛЕ отрезка — то есть впустую.
        # Поверх ролика той же надписи нет: она загородила бы картинку. Там
        # «Опенинг»/«Эндинг» уходит ведущему в реплику — он произносит это вслух
        # одновременно с видео (просьба пользователя, см. ниже).
        from .song_multi_anime import song_hint
        hint_text = song_hint(cand)
        if cand.music_effect == "chiptune":
            hint_text += " · Chiptune"
        elif cand.music_effect == "cover":
            # Игроку важно знать, что звучит ЧУЖОЕ исполнение: иначе вопрос
            # читается как «не узнал опенинг», хотя оригинала он и не слышал.
            # Вид исполнения называется прямо — «(кавер на английском)»,
            # «(кавер на фортепиано)» (просьба пользователя): ждать вокала или
            # одного инструмента, игрок должен знать заранее.
            hint_text = _api.cover_hint(hint_text, cand.music_processing)
        if s.hint and not cand.has_video:
            hint = _api.ET.SubElement(q_param, "item", {"waitForFinish": "False"})
            hint.text = hint_text
        if cand.has_video:
            if s.hint:
                # placement="replic" — это устный текст ведущего, а
                # waitForFinish="False" пускает его ОДНОВРЕМЕННО с роликом, а не
                # до него.
                said = _api.ET.SubElement(q_param, "item",
                                     {"waitForFinish": "False",
                                      "placement": "replic"})
                said.text = hint_text
            # Ролик опенинга с AnimeThemes: он и картинка, и звук сразу, так
            # что ни коллаж, ни фоновая дорожка тут не нужны.
            attrs = {"type": "video", "isRef": "True"}
            # Karaoke duration comes from its cropped/tempo-adjusted recording;
            # omit the separate AnimeThemes timer and wait for the media end.
            if cand.music_effect != "karaoke":
                attrs["duration"] = _api.fmt_duration(s.video_cut)
            video = _api.ET.SubElement(q_param, "item", attrs)
            video.text = cand.entrance_video or cand.video_out
            _api._append_answer(params, q, cand, s)
            return
        # Чьё исполнение звучит — устным текстом ведущего, одновременно с
        # отрезком (просьба пользователя). placement="replic" и
        # waitForFinish="False" — ровно как подсказка поверх ролика.
        credit = (_api.cover_credit(cand.music_processing)
                  if cand.music_effect == "cover" else "")
        if credit:
            said = _api.ET.SubElement(q_param, "item",
                                      {"waitForFinish": "False",
                                       "placement": "replic"})
            said.text = credit
        # Таймера у дорожки нет ВОВСЕ (просьба пользователя): без duration
        # SIGame ждёт конца самой записи, а не отсчитывает секунды на экране.
        # Отрезок и так вырезан ровно на audio_cut секунд, так что вопрос
        # длится столько же, сколько длился с таймером, — только без него.
        audio = _api.ET.SubElement(q_param, "item", {
            "type": "audio", "isRef": "True", "placement": "background"})
        audio.text = cand.audio_out
        if s.images and cand.has_collage:
            img = _api.ET.SubElement(q_param, "item", {
                "type": "image", "isRef": "True",
                "duration": _api.fmt_duration(s.images_time)})
            img.text = cand.collage_file

    _api._append_answer(params, q, cand, s)

_append_question.__module__ = _api.__name__
_api._append_question = _append_question

def _append_answer(params, q, cand: _api.SongCandidate, s: _api.PackSettings) -> None:
    """Ответ: кто смотрел + исполнитель + постер.

    Никакой подписи-плашки на экране: из содержимого ответа остаётся только
    постер (как в паках пользователя) — название игроки видят строкой
    правильного ответа, а исполнитель уходит в реплику ведущего."""
    a_param = _api.ET.SubElement(params, "param", {"name": "answer", "type": "content"})
    # Порядок в реплике один и тот же, откуда бы ни собрался пак (просьба
    # пользователя): сперва исполнитель — если вопрос песенный, — а следом голые
    # никнеймы тех, у кого тайтл есть в списке. Никаких «Есть у»: ведущий и так
    # читает имена людей.
    artist = cand.artist
    parts = []
    if artist:
        # У кавера это исполнитель ОРИГИНАЛА, а не тот, кого игроки только что
        # слышали (просьба пользователя): иначе ведущий называет чужое имя
        # как авторское. У обычного вопроса исполнитель и есть исполнитель.
        label = ("Исполнитель оригинала" if cand.music_effect == "cover"
                 else "Исполнитель")
        parts.append(f"{label} — 『{artist}』")
    # Сложность AMQ относится именно к песне, поэтому она идёт в реплику
    # каждого песенного вопроса рядом с исполнителем. У кадров, манги,
    # сюжета и прочих немых вопросов карточка песни иногда остаётся внутри
    # кандидата технически, но показывать её сложность там было бы ложью.
    if not cand.is_silent:
        parts.append(f"Сложность AMQ — {cand.difficulty:g}")
        # Рейтинг тайтла ведущий называет и у песен (просьба пользователя) —
        # как у кадров и прочих немых вопросов.
        parts.append(_score_text(cand))
    # У книжного вопроса ведущий вслух говорит, экранизована ли она (просьба
    # пользователя). Это не мелочь: от экранизации зависит и цена вопроса, и
    # то, откуда игроки вообще могли её узнать. Реплика идёт с
    # waitForFinish="False", то есть звучит ОДНОВРЕМЕННО с обложкой в ответе,
    # а не до неё.
    if cand.is_manga:
        status = str((cand.adapted_from or {}).get("status") or "").lower()
        if cand.adapted_from and status in ("anons", "announced"):
            parts.append("Аниме-адаптация анонсирована")
        else:
            parts.append("Аниме-адаптация есть" if cand.adapted_from
                         else "Аниме-адаптации нет")
        # Автор и оценка Shikimori — то же, что ведущий говорит по остальным
        # вопросам (просьба пользователя). Раньше книге они не доставались
        # вовсе: строка про экранизацию делала реплику непустой, а автор с
        # рейтингом приписывались только к пустой.
        parts.extend(_author_and_score(cand))
    if cand.kind == _api.DIALOGUE_KIND and cand.dialogue_episode:
        # У диалога устная реплика намеренно состоит ТОЛЬКО из номера серии.
        parts = [f"Серия {cand.dialogue_episode}"]
    if cand.users and cand.kind != _api.DIALOGUE_KIND:
        parts.append(", ".join(cand.users))
    # У студии правильный ответ уже говорит всё необходимое. Автор исходного
    # произведения и его рейтинг относятся к случайной первой карточке из
    # трёх и только вводят в заблуждение.
    if not parts and not cand.is_studio:
        parts.extend(_author_and_score(cand))
    if parts:
        replic = _api.ET.SubElement(a_param, "item",
                               {"waitForFinish": "False", "placement": "replic"})
        replic.text = " · ".join(parts)
    if cand.has_poster:
        # Без waitForFinish="False": постер не «играет одновременно» с репликой,
        # а показывается своим чередом (просьба пользователя).
        # Сколько он висит — настройка «Картинка в ответе»; ноль означает «без
        # ограничения»: тогда duration не пишем вовсе и картинка остаётся на
        # экране, пока ведущий не пойдёт дальше.
        attrs = {"type": "image", "isRef": "True"}
        seconds = max(0, min(_api.ANSWER_IMAGE_MAX,
                             int(getattr(s, "answer_image_time", 3) or 0)))
        if seconds:
            attrs["duration"] = _api.fmt_duration(seconds)
        poster = _api.ET.SubElement(a_param, "item", attrs)
        poster.text = cand.poster_file

    # Первый <answer> показывается игрокам, остальные — синонимы, которые
    # ведущему засчитываются как верные (ромадзи, английское, японское,
    # российское лицензионное имя и синонимы с Shikimori).
    right = _api.ET.SubElement(q, "right")
    for text in cand.answer_variants():
        _api.ET.SubElement(right, "answer").text = text

def _score_text(cand) -> str:
    """«Рейтинг MAL — 『8.60⭐』». Оценка в карточке Shikimori — это оценка
    MyAnimeList (Shikimori её зеркалит), поэтому и называется она так
    (просьба пользователя)."""
    score = cand.score
    return ("Рейтинг MAL — 『"
            + (f"{score:.2f}⭐" if score > 0 else "нет оценки") + "』")


def _author_and_score(cand) -> list:
    """Автор произведения и его оценка (MAL) — строками для реплики.

    Автора может и не быть (справочник ролей не ответил, у тайтла его не
    указали) — тогда остаётся одна оценка, а «нет оценки» пишется прямо: это
    честнее пустоты, по которой не понять, спрашивали ли вообще."""
    out = []
    if cand.author_name:
        out.append(f"Автор — 『{cand.author_name}』")
    out.append(_score_text(cand))
    out.append(f"Индекс популярности — {int(round(cand.index))} "
               f"(Ур. {cand.level})")
    return out


_append_answer.__module__ = _api.__name__
_api._append_answer = _append_answer
