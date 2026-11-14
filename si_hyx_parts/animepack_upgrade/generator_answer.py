# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""«Ответ как в генераторе»: год в первом ответе, автор и оценка MAL устно.

Ответ считается тем же тайтлом, если он записан ровно как на Shikimori — сам
по себе или так, как его пишет «Генерация аниме-пака»: с годом, тегом
OP/ED/OST и хвостом «— 『…』» (песня или персонаж), а также несколькими
именами через «/». Такому ответу дописываются остальные названия (последним —
основное русское), «(год)» в первую строку и реплика ведущему
«Автор — 『…』 · Рейтинг MAL — 『…』». Если в устном ответе уже назван
исполнитель, автор не повторяется: добавляется только рейтинг. Вопрос с
несколькими ответами получает только реплику — варианты названий и год у него
не трогаются. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api

# Тот же запрос ролей, что у генератора (author_lookup), плюс оценка: в
# поисковой выдаче Shikimori её нет. Пачка — 15 тайтлов, как у генератора:
# больше сервер не пропускает по сложности запроса.
_INFO_QUERY = """query($ids: String!, $limit: Int!) {
  TARGET(ids: $ids, limit: $limit) {
    id score personRoles { rolesRu rolesEn person { name russian } }
  }
}"""
_INFO_CHUNK = 15
_RE_ANY_YEAR = _api.re.compile(r"[(\[]\s*(?:19|20)\d{2}\s*[)\]]")
# «… — 『Песня』» / «… — 『Персонаж』»: хвост, перед которым генератор ставит
# год, а не в самый конец ответа.
_RE_DASH_TAIL = _api.re.compile(r"^(.*?)(\s+[—–-]\s+.*)$", _api.re.DOTALL)
_PERFORMER = "исполнител"


def _title_key(text) -> str:
    """Название в сравнимом виде — без года, тега песни и хвоста за тире."""
    return _api.norm_title(_api.strip_year(_api.answer_title(text)))


def whole_exact(text: str, card: dict) -> bool:
    """Ответ — это название тайтла, записанное как на Shikimori.

    Допускается ровно то, что пишет генератор: «Название (год) OP1 —
    『Песня』» и «Название (год) — 『Персонаж』», а также ответ из нескольких
    имён через «/» («Агент времени 2 / Shiguang Dailiren II») — тогда каждое
    имя должно быть названием этой же карточки. Синонимы и русское имя — в счёт,
    японское поле — нет (см. spelling_names). Опечатки сюда не входят: это
    проверка «написано ровно то же самое»."""
    line = _api.answer_title(text)
    key = _title_key(line)
    if not key:
        return False
    names = {_title_key(name) for name in _api.spelling_names(card)}
    names.discard("")
    if key in names:
        return True
    parts = [part.strip() for part in line.split("/") if part.strip()]
    return (len(parts) > 1
            and all(_title_key(part) in names for part in parts))


def card_year(card: dict) -> int:
    """Год выхода тайтла — как у генератора (airedOn), запасной — releasedOn."""
    for field in ("airedOn", "releasedOn"):
        try:
            year = int(((card or {}).get(field) or {}).get("year") or 0)
        except (AttributeError, TypeError, ValueError):
            year = 0
        if year:
            return year
    return 0


def add_year(answer_el, card: dict) -> _api.Optional[tuple[str, str]]:
    """Дописывает «(год)» в первый ответ, если года там ещё нет.

    Год ставится туда же, где его ставит генератор: в конец названия, но
    ПЕРЕД хвостом «— 『…』», а не после него. Возвращает (было, стало) или
    None, если ничего не поменялось."""
    before = (answer_el.text or "").strip()
    year = card_year(card)
    if not before or not year or _RE_ANY_YEAR.search(before):
        return None
    match = _RE_DASH_TAIL.match(before)
    if match:
        head, tail = match.group(1).strip(), match.group(2)
        after = f"{head} ({year}){tail}"
    else:
        after = f"{before} ({year})"
    answer_el.text = after
    return before, after


def info_lines(author: str, score, with_author: bool = True) -> list[str]:
    """Строки реплики — ровно те, что пишет генератор (без индекса и уровня:
    их у чужого пака нет). with_author=False — только рейтинг: автор уже
    назван иначе («Исполнитель — …»)."""
    from si_hyx_parts.animepack.build_content_xml import author_line, score_line
    out = [author_line(author)] if author and with_author else []
    out.append(score_line(score))
    return out


def _replic_items(param) -> list:
    """Устные строки ответа формата v5."""
    return [item for item in _api.children(param, "item")
            if (item.get("placement") or "") == "replic"]


def _scenario_says(scenario) -> list:
    """Устные строки ответа формата v4 — <atom type="say"> за маркером."""
    if scenario is None:
        return []
    out, after_marker = [], False
    for atom in _api.children(scenario, "atom"):
        kind = (atom.get("type") or "")
        if kind == "marker":
            after_marker = True
        elif after_marker and kind == "say":
            out.append(atom)
    return out


def _performer_say(says: list):
    """Реплика, где уже назван исполнитель, — чтобы дописать рядом рейтинг."""
    return next((el for el in says
                 if _PERFORMER in (el.text or "").casefold()), None)


def add_info_replic(q_el, tag, lines: list[str]) -> str:
    """Кладёт строки ведущему в ответ вопроса. Возвращает добавленный текст;
    пустая строка — класть было некуда или оценка там уже есть (повторный
    апгрейд того же пака).

    v5 — <item placement="replic" waitForFinish="False"> в параметре ответа:
    реплика звучит одновременно с картинкой ответа, как у генератора. Если
    реплика у ответа уже есть, строки дописываются в неё через « · »; при
    «Исполнитель …» автор не дублируется, а рейтинг встаёт в ту же реплику.
    v4 — <atom type="say"> за маркером сценария; там всё так же, только
    реплик может быть несколько."""
    params = _api.child(q_el, "params")
    v4 = params is None and _api.child(q_el, "scenario") is not None
    if v4:
        says = _scenario_says(_api.child(q_el, "scenario"))
        param = None
    else:
        param = _api.answer_content(q_el, tag)
        says = _replic_items(param)
    if any("Рейтинг MAL" in (el.text or "") for el in says):
        return ""
    clean = [line for line in lines if line]
    performer = _performer_say(says)
    if performer is not None:
        clean = [line for line in clean
                 if not line.casefold().startswith("автор —")]
    text = " · ".join(clean)
    if not text:
        return ""
    target = performer or (says[-1] if says else None)
    if target is not None:
        old = (target.text or "").strip()
        target.text = f"{old} · {text}" if old else text
        return text
    if v4:
        scenario = _api.scenario_answer_tail(q_el, tag)
        if scenario is None:
            return ""
        atom = _api.ET.SubElement(scenario, tag("atom"), {"type": "say"})
        atom.text = text
        return text
    item = _api.ET.Element(tag("item"), {"waitForFinish": "False",
                                         "placement": "replic"})
    item.text = text
    param.insert(0, item)
    return text


def fetch_info(api, ids: list[str], book: bool, log) -> dict[str, tuple[str, float]]:
    """{id тайтла: (автор, оценка)} пачками через Shikimori GraphQL.

    Сбой одной пачки не роняет апгрейд: у её вопросов реплики просто не будет,
    а в журнал уйдёт причина."""
    from si_hyx_parts.animepack.author_lookup import _author
    target = "mangas" if book else "animes"
    query = _INFO_QUERY.replace("TARGET", target)
    out: dict[str, tuple[str, float]] = {}
    unique = list(dict.fromkeys(str(i) for i in ids if str(i).isdigit()))
    for start in range(0, len(unique), _INFO_CHUNK):
        chunk = unique[start:start + _INFO_CHUNK]
        try:
            api.limiter.acquire()
            data = api.client._graphql(query, {"ids": ",".join(chunk),
                                               "limit": len(chunk)})
        except Exception as exc:  # noqa: BLE001 — без реплики, но с паком
            log(f"Shikimori: не удалось получить авторов и оценки: {exc}")
            continue
        rows = data.get(target) if isinstance(data, dict) else None
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            try:
                score = float(row.get("score") or 0)
            except (TypeError, ValueError):
                score = 0.0
            out[str(row.get("id"))] = (_author(row), score)
    return out


for _fn in (whole_exact, card_year, add_year, info_lines, add_info_replic, fetch_info):
    _fn.__module__ = _api.__name__
