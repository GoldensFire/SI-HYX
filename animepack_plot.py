# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# animepack_plot.py — вопросы ПО СЮЖЕТУ: пересказ с фэндом-вики превращается в
# вопрос руками Gemini. Ни Qt, ни сети здесь нет: текст приносит
# animepack_api.FandomApi, в модель ходит gemini_api.GeminiClient (в тестах и
# то, и другое подменяется), а тут — только промпты и разбор ответа.
#
# Два рода вопроса (настройка «Вопрос по сюжету» на вкладке):
#   • «title» — ведущий читает эпизод сюжета, игроки называют ТАЙТЛ. Ответ и
#     цена считаются как у любого другого вопроса пака, ничего доверять модели
#     не приходится: название мы знаем сами. Название и имена героев из текста
#     вопроса вычищаются (mask_names) — иначе вопрос решается с первого слова.
#   • «detail» — вопрос про сам сюжет («Что сделал герой, когда…»), ответ —
#     короткая деталь, её называет модель. Тайтл в вопросе назван прямо.
#
# Модель обязана молчать (пустой вопрос), если пересказ невнятный: выдуманный
# сюжет в паке хуже, чем вопрос, которого нет — упавшего кандидата генератор
# просто заменит следующим.
from __future__ import annotations

import re
from typing import Any, Optional

# Что можно спросить по сюжету.
PLOT_MODES = ("title", "detail")
PLOT_MODE_LABELS = {"title": "Ответ — название аниме",
                    "detail": "Ответ — деталь сюжета"}

# Короче этого пересказ ни на что не годится: из двух строк аннотации вопроса
# не выйдет, а запрос к модели будет потрачен впустую.
MIN_PLOT_CHARS = 220
# Сколько страниц серий пробуем, прежде чем пойти в статью самого тайтла.
# Каждая страница — это запрос к вики, а раздел с пересказом есть далеко не у
# всякой (бывают заготовки в две строки).
EPISODE_TRIES = 5
# Сколько пересказа отдаём модели за раз. Раздел «Сюжет» в статье самого
# тайтла бывает на несколько экранов, и модель цепляется за первый же яркий
# факт: из «Шарлотты» три пака подряд приходил один и тот же вопрос про пять
# секунд управления разумом (просьба пользователя). Окно берётся со СЛУЧАЙНОГО
# абзаца, поэтому по одной и той же статье выходят вопросы про разные места
# сюжета. Полторы тысячи знаков — это по-прежнему несколько абзацев подряд,
# то есть связный кусок, а не выдернутая фраза.
PLOT_WINDOW = 1500

SCHEMA_TITLE = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": ("вопрос для игры: пересказ эпизода сюжета своими "
                            "словами, без названия и имён собственных"),
        },
        "explanation": {
            "type": "string",
            "description": ("развёрнутое объяснение правильного ответа, "
                            "ровно одно предложение"),
        },
        "ok": {
            "type": "boolean",
            "description": "false, если по этому тексту вопроса не выходит",
        },
    },
    "required": ["question", "explanation", "ok"],
}

SCHEMA_DETAIL = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "вопрос по сюжету"},
        "answer": {"type": "string",
                   "description": ("правильный ответ, 1–5 слов; сюжетно "
                                   "важная конкретная деталь, НЕ простое число")},
        "alt": {
            "type": "array",
            "description": "другие написания того же ответа (можно пустой)",
            "items": {"type": "string"},
        },
        "answer_kind": {
            "type": "string",
            "enum": ["object", "action", "ability", "reason", "event",
                     "place", "organization", "person", "number", "other"],
            "description": ("тип правильного ответа; organization — любая "
                            "организация, группировка, фракция, команда, "
                            "отряд, гильдия, клан или банда"),
        },
        "explanation": {
            "type": "string",
            "description": ("развёрнутое объяснение правильного ответа, "
                            "ровно одно предложение"),
        },
        "ok": {"type": "boolean",
               "description": "false, если по этому тексту вопроса не выходит"},
    },
    "required": ["question", "answer", "answer_kind", "explanation", "ok"],
}

_RULES_COMMON = """Ты составляешь вопросы для игры «Своя игра» по аниме.
Тебе дают пересказ сюжета с фэндом-вики. Пиши ПО-РУССКИ, даже если пересказ на английском.

Общие правила:
1. Вопрос — одно-два предложения, не длиннее 300 символов. Живой человек должен прочитать его вслух за десять секунд.
2. Опирайся ТОЛЬКО на данный текст. Ничего не додумывай: выдуманный сюжет портит пак.
3. Если текст невнятный, обрывочный или это не пересказ событий (список серий, разметка, реклама вики) — верни ok=false и пустой вопрос.
4. Никакой разметки: ни звёздочек, ни ссылок, ни сносок.
4а. Источник должен описывать именно АНИМЕ. Если речь об игре, манге или ранобэ,
а подтверждения события в аниме нет — верни ok=false.
4б. Имена японских персонажей передавай по системе Хепбёрна: ши, чи, джи,
Шиничи, Джузо, Хяккимару. Проверяй падежи и согласование подлежащего со сказуемым;
если не можешь сформулировать естественный русский вопрос — верни ok=false.
4в. Вопрос должен быть прямым и фактическим, обязательно заканчиваться знаком
вопроса. Не задавай риторических вопросов.
4г. Если дан номер серии, естественно вплети его в вопрос («В 7-й серии…»),
а не добавляй отдельную служебную фразу. В explanation номер серии не пиши.
4д. explanation — ровно одно развёрнутое предложение, которое объясняет,
почему ответ верен, без ссылок, номера серии и повторения самого вопроса."""

_RULES_TITLE = """
Вопрос должен описывать ЗАПОМИНАЮЩИЙСЯ эпизод сюжета так, чтобы смотревший узнал произведение, а не смотревший — нет.

Ещё правила:
5. НЕ называй ни само произведение, ни его героев по именам: игроки как раз и должны угадать тайтл. Вместо имён пиши «главный герой», «его напарница», «злодей».
6. Не пересказывай общеизвестную завязку из одной фразы («парень становится сильнейшим») — бери именно тот эпизод, который описан в тексте.
7. Начинай сразу с сути, без «В этом аниме…» и «Угадайте произведение…»."""

_RULES_DETAIL = """
Вопрос должен спрашивать КРУПНУЮ, ЗАПОМИНАЮЩУЮСЯ деталь сюжета, у которой один короткий ответ.

Ещё правила:
5. Произведение в вопросе НАЗЫВАЙ ОБЯЗАТЕЛЬНО и в первом же предложении — угадывают не его, а деталь. Пиши название ровно так, как оно дано в строке «Произведение».
6. Ответ — от одного до пяти слов. Никаких «потому что…».
6a. Спрашивай о том, что двигает сюжет и что зритель запомнил: поворот событий, решение героя, цена победы, чья-то способность. Проходную обстановку не спрашивай вовсе — помещение, визит в чей-то дом, мимолётное чувство и прочие мелочи фона под вопрос не годятся. Если в тексте нет ничего, кроме таких деталей, верни ok=false.
6б. НИКОГДА не спрашивай название организации, группировки, фракции, команды,
отряда, гильдии, клана или банды. Для такого ответа ставь answer_kind="organization"
и возвращай ok=false. Эти названия неинтересны для игры.
7. ИМЯ ПЕРСОНАЖА — САМЫЙ ПЛОХОЙ ОТВЕТ, и спрашивать его нельзя. «Кто сделал…», «как зовут…», «кого герой встретил…» — такие вопросы не составляй вовсе. Число допустимо только тогда, когда именно оно определяет главный конфликт, а не случайный размер группы. Предпочитай важный ПРЕДМЕТ, ПОСТУПОК, СПОСОБНОСТЬ или ПРИЧИНУ.
8. Ответ обязан прямо следовать из данного текста, дословно или почти. В alt положи другие написания того же ответа (перевод, ромадзи, сокращение) — или оставь список пустым.
9. Не спрашивай то, чего в тексте нет.
10. Вопрос не должен сам подсказывать ответ. Электрощиток → электричество, проколы → пирсинг, поиски слабого места → слабое место — плохие вопросы. Ответы «раздражение», «дом героя» и подобные банальности тоже отклоняй. Если после чтения вопроса можно угадать ответ, не зная аниме, верни ok=false.
11. Прочитай вопрос вслух и проверь грамматику. Кто кого считает существом? Кто признаёт чувство? Если падежи или смысл двусмысленны, верни ok=false."""


def title_named(question: str, title: str) -> bool:
    """Названо ли произведение в тексте вопроса.

    Сверяем по значимым словам названия (короткие служебные не в счёт): модель
    склоняет и сокращает («в „Атаке титанов“», «в Атаке на титанов»), и точное
    вхождение строки тут ничего не доказало бы."""
    words = [w for w in re.split(r"[^0-9a-zA-Zа-яёА-ЯЁ]+",
                                 str(title or "").casefold()) if len(w) >= 4]
    if not words:
        return True
    text = str(question or "").casefold()
    season = season_number(title)
    if season > 1 and not re.search(rf"(?<!\d){season}(?!\d)", text):
        roman = {2: "ii", 3: "iii", 4: "iv", 5: "v", 6: "vi"}.get(season, "")
        if not roman or not re.search(rf"\b{roman}\b", text):
            return False
    # Достаточно половины значимых слов: «Реинкарнация безработного» в вопросе
    # обычно зовётся одним словом.
    hit = sum(1 for w in words if w[:-1] in text or w in text)
    return hit * 2 >= len(words)


_ROMAN_SEASONS = {"I": 1, "II": 2, "III": 3, "IV": 4,
                  "V": 5, "VI": 6}
_SEASON_MARKERS = (
    re.compile(r"\b(?:season|сезон(?:а|е|ом)?|part|част[ьи])\s*[-:#]?\s*"
               r"(\d{1,2}|I{1,3}|IV|V|VI)\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s+season\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*[- ]?(?:й|я|е|го|м)\s+сезон\b",
               re.IGNORECASE),
)


def _season_token(value: str) -> int:
    token = str(value or "").upper()
    number = int(token) if token.isdigit() else _ROMAN_SEASONS.get(token, 0)
    # У «Покемона» официальная нумерация давно перевалила за двадцатый сезон.
    return number if 1 <= number <= 99 else 0


def _explicit_seasons(title: str) -> list[int]:
    text = str(title or "").replace("_", " ").strip()
    found = [_season_token(match.group(1)) for pattern in _SEASON_MARKERS
             for match in pattern.finditer(text)]
    sxe = re.search(r"\bS(\d{1,2})E\d{1,3}\b", text, re.IGNORECASE)
    if sxe:
        found.append(_season_token(sxe.group(1)))
    return [number for number in found if number]


def season_number(*titles: str) -> int:
    """Номер продолжения из любого известного написания тайтла.

    Shikimori иногда не ставит номер в русском названии, но оставляет его в
    ромадзи (`2nd Season`). Поэтому одного ``cand.title_ru`` недостаточно и для
    проверки страницы вики, и для выбора постера продолжения.
    """
    explicit = [number for title in titles for number in _explicit_seasons(title)]
    if explicit:
        return max(explicit)
    # Число, с которого начинается другое написание, — часть названия:
    # «Samurai 7» — это «7 самураев», а не седьмой сезон (просьба
    # пользователя: вопрос вышел про «7 самураев — 7-й сезон»).
    named = {int(match.group(1)) for title in titles
             for match in [re.match(r"\s*(\d{1,2})\s+\w",
                                    str(title or ""))] if match}
    trailing: list[int] = []
    for title in titles:
        match = re.search(r"(?:^|[\s:—-])(\d{1,2}|I{1,3}|IV|V|VI)$",
                          str(title or "").strip(), re.IGNORECASE)
        if match:
            number = _season_token(match.group(1))
            if number and number not in named:
                trailing.append(number)
    return max(trailing, default=1)


def season_title(title: str, *alternatives: str) -> str:
    """Русское название с явным сезоном, если номер виден лишь в вариантах."""
    clean = " ".join(str(title or "").split())
    season = season_number(clean, *alternatives)
    if not clean or season <= 1 or season_number(clean) == season:
        return clean
    return f"{clean} — {season}-й сезон"


def _title_without_season(title: str) -> str:
    text = str(title or "").strip()
    text = re.sub(r"\s*[—:-]?\s*\d{1,2}\s*[- ]?(?:й|я|е|го|м)\s+сезон$",
                  "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:\d{1,2}|I{1,3}|IV|V|VI)$", "", text,
                  flags=re.IGNORECASE)
    return text.strip()


def episode_number(page: str) -> str:
    """Номер серии со страницы вики; название тома/фильма не подставляем."""
    name = str(page or "").replace("_", " ")
    match = re.search(r"\b(?:episode|эпизод|серия)\s*[#№:]?\s*(\d{1,3})\b",
                      name, re.IGNORECASE)
    if not match:
        match = re.search(r"\bS\d{1,2}E(\d{1,3})\b", name, re.IGNORECASE)
    if not match:
        # Pokémon Wiki / Bulbapedia: ``P144: ...`` и ``JN144``.
        match = re.search(r"(?:^|[|/ ])(?:P|JN)(\d{1,3})(?=\D|$)", name,
                          re.IGNORECASE)
    return str(int(match.group(1))) if match else ""


def source_page_ok(page: str, body: str, title: str, year: int = 0) -> bool:
    """Не смешивает пересказ аниме с томами книг, игрой и иным сезоном."""
    name = str(page or "").replace("_", " ")
    if re.search(r"\b(light novel|novel|manga|volume|chapter|game|ранобэ|"
                 r"манга|том|глава|игра)\b", name, re.IGNORECASE):
        return False
    season = season_number(title)
    page_seasons = _explicit_seasons(name)
    # Страница второго сезона не годится для карточки первого — именно так у
    # «Арифурэты» вопрос S2 получил название и постер S1. Обратное тоже верно.
    if page_seasons and season not in page_seasons:
        return False
    if season > 1:
        # Номер СЕРИИ не должен приниматься за номер СЕЗОНА.
        season_name = re.sub(r"\b(?:episode|эпизод|серия)\s*[#№:]?\s*\d+\b",
                             "", name, flags=re.IGNORECASE)
        roman = {2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI"}.get(season, "")
        markers = [rf"\b{season}\b", rf"\b{roman}\b" if roman else r"(?!)"]
        if not any(re.search(mark, season_name, re.IGNORECASE)
                   for mark in markers):
            # Некоторые вики нумеруют всю арку подряд и не пишут сезон в
            # заголовке: ``Sword Art Online Alicization Episode 47``. Такая
            # страница подтверждает нужную часть датой показа в инфобоксе;
            # apply_season затем выберет карточку и пересчитает сквозной номер.
            # Без подтверждённого года сохраняем прежнюю строгую проверку,
            # чтобы S5 не взял безымянную серию из S1.
            try:
                from si_hyx_parts.animepack.plot_air_date import air_date_of_page
                aired = air_date_of_page(body)
            except (ImportError, ValueError):
                aired = ()
            if not (year and aired and aired[0] == int(year)):
                return False
    # Эти адаптации имеют два отдельных телесериала с общими персонажами:
    # без явной датировки страницы нельзя уверенно приписать событие одному.
    if "дороро" in title.casefold() or "dororo" in title.casefold():
        sample = f"{name} {body[:600]}"
        if year and str(year) not in sample:
            return False
    if "перерождение" in title.casefold() or ":re" in title.casefold():
        if not re.search(r"(?:tokyo\s*ghoul\s*:?re|перерождени)",
                         f"{name} {body[:300]}", re.IGNORECASE):
            return False
    return True


def name_title(question: str, title: str) -> str:
    """Вопрос с обязательно названным произведением.

    Модель нет-нет да и забудет назвать тайтл, и вопрос выходит про неизвестно
    что — «что сделает Бог, если на небеса попадёт достаточно людей?». Вместо
    того чтобы выбрасывать такой вопрос, приписываем название сами (просьба
    пользователя)."""
    question = str(question or "").strip()
    title = " ".join(str(title or "").split())
    if not question or not title or title_named(question, title):
        return question
    if season_number(title) > 1:
        base = _title_without_season(title)
        for match in re.finditer(r"«([^»]+)»", question):
            if title_named(match.group(1), base):
                return (question[:match.start()] + f"«{title}»"
                        + question[match.end():])
    return f"«{title}»: {question[:1].lower() + question[1:]}"


def plot_window(text, rng, window: int = PLOT_WINDOW) -> str:
    """Случайный связный кусок пересказа, не короче MIN_PLOT_CHARS.

    Режем ПО АБЗАЦАМ: обрывок с середины фразы модель честно назовёт невнятным
    и вернёт ok=false. Короткий пересказ отдаём как есть — резать там нечего.
    """
    text = str(text or "").strip()
    if len(text) <= window:
        return text
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) < 2:
        return text[:window]
    # Начинать можно с любого абзаца, после которого ещё осталось на вопрос.
    tail, starts = 0, []
    for index in range(len(parts) - 1, -1, -1):
        tail += len(parts[index]) + 2
        if tail >= MIN_PLOT_CHARS:
            starts.append(index)
    begin = rng.choice(starts) if starts else 0
    out: list[str] = []
    size = 0
    for part in parts[begin:]:
        out.append(part)
        size += len(part) + 2
        if size >= window:
            break
    return "\n\n".join(out)


def build_prompt(title: str, plot: str, mode: str = "title",
                 page: str = "", episode="") -> str:
    """Текст запроса к модели по одному тайтлу."""
    rules = _RULES_TITLE if mode != "detail" else _RULES_DETAIL
    head = [_RULES_COMMON + rules, ""]
    if mode == "detail":
        head.append(f"Произведение: {title}")
    if page:
        head.append(f"Страница вики: {page}")
    if str(episode or "").strip():
        head.append(f"Номер серии: {str(episode).strip()}")
    head += ["", "Пересказ сюжета:", str(plot or "").strip()]
    return "\n".join(head)


def _clean(text: Any) -> str:
    """Ответ модели в одну строку без разметки."""
    out = " ".join(str(text or "").split())
    out = re.sub(r"[*_`]+", "", out)
    return out.strip()


def _capitalized(text: str) -> str:
    """Первая буква — заглавная; остальное как было.

    Модель пишет ответ строчными («меч тессайга»), и в списке ответов пака это
    смотрелось небрежно рядом с названиями тайтлов (просьба пользователя).
    Регистр остальных букв не трогаем: в ответе бывают аббревиатуры и имена
    собственные, и `capitalize()` их бы испортил."""
    out = str(text or "")
    return out[:1].upper() + out[1:] if out else out


def mask_names(text: str, names) -> str:
    """Прячет названия и имена собственные в тексте вопроса.

    Модель иногда всё-таки называет тайтл («Как и в „Наруто“, герой…») — такой
    вопрос решается с первого слова. Вместо того чтобы выбрасывать вопрос
    целиком, затираем найденное многоточием: смысл остаётся, подсказка уходит.
    """
    out = str(text or "")
    words: list[str] = []
    for name in names or ():
        name = str(name or "").strip()
        if not name:
            continue
        words.append(name)
        # Отдельные слова названия тоже выдают тайтл («Атака титанов» →
        # «титанов»), но однобуквенные и служебные куски трогать нельзя.
        words += [w for w in re.split(r"[\s:,\-–—/]+", name) if len(w) >= 4]
    for word in sorted(set(words), key=len, reverse=True):
        out = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", "…", out,
                     flags=re.IGNORECASE)
    # Несколько затёртых слов подряд схлопываем в одно многоточие.
    out = re.sub(r"(?:…[\s«»\"'(),.]*){2,}", "… ", out)
    return " ".join(out.split()).strip(" ,;:")


def parse_answer_full(data: Any, mode: str = "title", *, strict=False) \
        -> tuple[str, list[str], str]:
    """Ответ модели → (вопрос, варианты ответа, пояснение)."""
    if not isinstance(data, dict) or data.get("ok") is False:
        return "", [], ""
    question = _clean(data.get("question"))
    explanation = _clean(data.get("explanation"))
    if not question or (strict and (not explanation
                                    or not question.endswith("?"))):
        return "", [], ""
    if mode != "detail":
        return question, [], explanation
    answers: list[str] = []
    for raw in [data.get("answer")] + list(data.get("alt") or []):
        text = _capitalized(_clean(raw))
        if text and text.casefold() not in {a.casefold() for a in answers}:
            answers.append(text)
    if not answers:
        return "", [], ""
    answer = answers[0].casefold()
    answer_kind = str(data.get("answer_kind") or "").strip().casefold()
    organization_question = re.search(
        r"\b(?:организац|группиров|фракц|команд|отряд|гильди|клан|банд)",
        question, re.IGNORECASE)
    if (answer_kind == "organization" or organization_question
            or re.fullmatch(r"\d+(?:[.,]\d+)?", answer)
            or answer in {"слабое место", "раздражение", "электричество",
                          "пирсинг"}
            or (len(answer) >= 5 and answer in question.casefold())):
        return "", [], ""
    return question, answers, explanation


def make_question(title: str, plot: str, client, *, mode: str = "title",
                  page: str = "", names=(), episode="",
                  temperature: float = 0.6) -> tuple[str, list[str]]:
    """Вопрос по пересказу сюжета: (текст, варианты ответа).

    («», []) — вопроса не вышло (пересказ короткий, модель отказалась). Ошибки
    самого gemini_api (нет ключа, кончилась квота) НЕ глушим: вкладке надо
    сказать пользователю, что именно случилось.

    temperature нарочно не нулевая: два вопроса подряд по похожим пересказам
    при нуле выходят близнецами."""
    question, answers, _explanation = _make_question(
        title, plot, client, mode=mode, page=page, names=names,
        episode=episode, temperature=temperature, strict=False)
    return question, answers


def make_question_with_explanation(
        title: str, plot: str, client, *, mode: str = "title",
        page: str = "", names=(), episode="", temperature: float = 0.6
) -> tuple[str, list[str], str]:
    """Как :func:`make_question`, но с пояснением для ответа."""
    return _make_question(title, plot, client, mode=mode, page=page,
                          names=names, episode=episode,
                          temperature=temperature, strict=True)


def _make_question(title: str, plot: str, client, *, mode: str, page: str,
                   names, episode, temperature: float, strict: bool):
    text = str(plot or "").strip()
    if len(text) < MIN_PLOT_CHARS:
        return "", [], ""
    # Несколько вариантов за один запрос: отказ модели или строгого разбора
    # по одному из них больше не стоит нового запроса (см. plot_variants).
    from si_hyx_parts.animepack import plot_variants
    schema = SCHEMA_DETAIL if mode == "detail" else SCHEMA_TITLE
    data = client.generate_json(
        build_prompt(title, text, mode, page, episode)
        + plot_variants.prompt_tail(), plot_variants.many(schema),
        temperature=temperature)
    for item in plot_variants.variants(data):
        question, answers, explanation = parse_answer_full(item, mode,
                                                            strict=strict)
        if question and mode != "detail":
            question = mask_names(question, names or (title,))
        elif question:
            # В режиме «деталь сюжета» название тайтла в вопросе обязательно:
            # без него игроки не понимают, о каком произведении речь вообще.
            question = name_title(question, title)
        if question:
            return question, answers, explanation
    return "", [], ""


def pick_plot(fandom, names, rng, *, log: Optional[Any] = None,
              title: str = "", year: int = 0, movie: bool = False) -> dict:
    """Пересказ для одного тайтла: {"text", "page", "wiki", "source"} или {}.

    Порядок такой: находим вики по названию (пробуем ромадзи, английское,
    русское — какое найдётся), берём случайную страницу СЕРИИ и из неё раздел
    с пересказом. Серий у вики может не быть вовсе (фильм, короткометражка) —
    тогда берём статью самого тайтла и её раздел «Сюжет».
    """
    names = [str(n or "").strip() for n in (names or ()) if str(n or "").strip()]
    wiki = fandom.find_wiki(names)
    if not wiki:
        return {}
    pages = [] if movie else list(fandom.episode_pages(wiki))
    rng.shuffle(pages)
    pages = pages[:EPISODE_TRIES]
    # Хвост подстрахует, если разделов с пересказом у серий не окажется (или
    # серий у вики нет вовсе — фильм, короткометражка): статья самого тайтла
    # есть всегда, и раздел «Сюжет» в ней тоже. Перемешиваем и его: у вики без
    # страниц серий хвост решает всё, а в прежнем порядке он был один и тот же
    # от прогона к прогону — отсюда и одинаковые вопросы по одному тайтлу.
    if names:
        tail = [p for p in fandom.search(wiki, names[0], limit=3)
                if p not in pages]
        if title and not movie:
            tail = [p for p in tail if episode_number(p)]
        rng.shuffle(tail)
        pages += tail
    for page in pages:
        # Разметка нужна целиком: пересказ читается очищенным, а номер сезона
        # стоит в инфобоксе, который чистка сносит (см. plot_season). Источник
        # без page_source (подменённый в тестах, чужая заглушка) отдаёт сразу
        # чистый текст — тогда сезона в нём просто не найдётся.
        source = getattr(fandom, "page_source", None)
        if source is None:
            raw = body = fandom.page_text(wiki, page)
        else:
            raw = source(wiki, page)
            # Импорт внутри: модуль намеренно не тянет сеть при загрузке, а
            # animepack_api тащит за собой requests (см. запуск программы).
            from animepack_api import strip_wikitext
            body = strip_wikitext(raw)
        if not source_page_ok(page, raw, title, year):
            continue
        chunk = fandom.plot_section(body)
        if len(chunk) >= MIN_PLOT_CHARS:
            # Не начало раздела, а случайное его место: иначе по длинной
            # статье модель раз за разом спрашивает об одном и том же.
            return {"text": plot_window(chunk, rng), "page": page,
                    "wiki": wiki, "source": raw}
    return {}
