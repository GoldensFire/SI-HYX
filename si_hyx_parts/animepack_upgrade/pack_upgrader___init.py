# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackUpgrader: __init__. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def __init__(self, path: str, s: _api.UpgradeSettings,
             log: _api.Optional[_api.Callable[[str], None]] = None,
             progress: _api.Optional[_api.Callable[[int, int, str], None]] = None,
             should_stop: _api.Optional[_api.Callable[[], bool]] = None,
             api=None):
    self.path = str(path or "")
    self.s = s
    self._log = log or (lambda _m: None)
    self._progress = progress or (lambda _d, _t, _m: None)
    self._should_stop = should_stop or (lambda: False)
    self._api = api
    # Один и тот же тайтл спрашиваем ровно раз: в паке из 60 вопросов одно
    # аниме встречается по нескольку раз, а каждый запрос — это лимитер
    # Shikimori (5/с и 80/мин). Ключ — (книга?, название): по книгам и по
    # аниме это два разных поиска с разными ответами.
    self._cache: dict[tuple, _api.Optional[dict]] = {}
    # То же для персонажей: {ответ: имя героя или None}.
    self._chars: dict[str, _api.Optional[str]] = {}
    # Постеры: {номер тайтла: задание} — файл на тайтл один, сколько бы
    # вопросов про него в паке ни было. Качаются и кодируются они в фоне,
    # потоки живут в self._pool (см. _poster_job).
    self._posters: dict[str, _api.Optional[_api._PosterJob]] = {}
    self._pool: _api.Optional[_api.ThreadPoolExecutor] = None
    self._poster_temps: list[str] = []
    # Клиент TMDB заводится по первой надобности: None — ещё не пробовали,
    # False — ключа нет или сервер сердится, больше не ходим.
    self._tmdb = None
    # Новые файлы, которых в исходном архиве не было: {имя записи: временный
    # файл}. Кладутся в пак при записи, потом временные удаляются.
    self._extra: dict[str, str] = {}
    self._taken_names: set[str] = set()
    # Имена, выданные пережатым картинкам и дорожкам: в архиве их ещё нет, а
    # занимать их второй раз уже нельзя (картинки считаются раньше аудио).
    self._new_names: set[str] = set()

# ── мелочи ────────────────────────────────────────────────────────────
def log(self, msg: str) -> None:
    try:
        self._log(msg)
    except Exception:  # pragma: no cover — лог не должен ронять работу
        pass

def stopped(self) -> bool:
    try:
        return bool(self._should_stop())
    except Exception:  # pragma: no cover
        return False

@property
def api(self):
    """Клиент базы названий — Shikimori, тот же, что у генератора
        (лимитер, ретраи, ключи полей). Создаётся лениво: без функции названий
        сеть не нужна вовсе."""
    if self._api is None:
        from animepack_api import ShikimoriApi
        self._api = ShikimoriApi()
    return self._api

# ── поиск тайтла ──────────────────────────────────────────────────────
def find_title(self, query: str, book: bool = False) -> _api.Optional[dict]:
    """Карточка тайтла по названию. book — искать книгу (мангу, манхву,
        ранобэ), а не аниме: так делается на темах, где это написано в названии
        самой темы."""
    book = bool(book)
    key = (book, _api.norm_title(query))
    if key in self._cache:
        return self._cache[key]
    what = "мангу" if book else "аниме"
    try:
        if book:
            cards = self.api.search_mangas_by_name(query)
        else:
            cards = self.api.search_animes_by_name(query)
    except AttributeError:
        # Клиент без такого поиска (старый или подставной) — не повод падать.
        cards = []
    except Exception as e:  # noqa: BLE001 — один упавший запрос не повод
        self.log(f"{self.s.source_name} не ответил(а) про {what} "
                 f"«{query}»: {e}")
        cards = []
    card = _api.pick_card(query, cards, strict=self.s.strict_match)
    if card is not None and _api.is_clip(card):
        self.log(f"«{query}» — это клип, а не {what}: одноимённый тайтл "
                 f"известен в разы хуже, беру клип.")
    self._cache[key] = card
    return card

def find_character(self, query: str) -> _api.Optional[str]:
    """Имя персонажа, совпавшее с ответом слово в слово, или None.

        Кэш — как у тайтлов: одного и того же героя в паке спрашивают по
        нескольку раз, а запрос идёт через общий лимитер Shikimori."""
    key = _api.norm_title(query)
    if key in self._chars:
        return self._chars[key]
    try:
        chars = self.api.search_characters_by_name(query)
    except Exception as e:  # noqa: BLE001 — упавший запрос не повод падать
        self.log(f"Персонажи Shikimori не ответили про «{query}»: {e}")
        chars = []
    name = _api.character_hit(query, chars)
    self._chars[key] = name
    return name

# ── работа ────────────────────────────────────────────────────────────
def run(self, out_path: _api.Optional[str] = None) -> _api.UpgradeResult:
    started = _api.time.monotonic()
    if not _api.os.path.isfile(self.path):
        raise _api.UpgradeError(f"Файл не найден: {self.path}")
    problems = self.s.validate()
    if problems:
        raise _api.UpgradeError("\n\n".join(problems))

    cname, data = _api.read_content(self.path)
    root, ns = _api.parse_content(data)
    tag = _api.tag_fn(ns)
    result = _api.UpgradeResult(source=self.path)

    if not list(_api.iter_questions(root)):
        raise _api.UpgradeError("В паке нет ни одного вопроса — править нечего.")
    # Пустые вопросы выкидываются ДО всего остального: их не за чем ни
    # расколдовывать, ни искать по ним тайтлы, а нумерация вопросов должна
    # считаться уже по тому, что в паке останется.
    if self.s.drop_empty_questions:
        self._do_empty(root, result)

    questions = list(_api.iter_questions(root))
    result.questions = len(questions)
    if not questions:
        raise _api.UpgradeError("В паке нет ни одного вопроса — править нечего.")
    self.log(f"В паке {len(questions)} вопрос(ов).")

    # Медиа считаем заранее: оно идёт вторым этапом, а полоса прогресса
    # должна знать про него с самого начала.
    heavy = self._heavy_images() if self.s.compress_images else []
    result.heavy_images = len(heavy)
    heavy_audio = self._heavy_audio() if self.s.compress_audio else []
    result.heavy_audio = len(heavy_audio)
    heavy_video = self._video_entries() if self.s.compress_video else []
    result.heavy_video = len(heavy_video)
    steps = (len(questions) + len(heavy) + len(heavy_audio)
             + len(heavy_video))

    # Повторы считаются по теме целиком, поэтому идут отдельным проходом до
    # общего цикла — сети он не трогает и стоит доли секунды.
    if self.s.strip_repeated_text:
        self._do_repeats(root, questions, result)

    try:
        for i, (rname, tname, q) in enumerate(questions):
            if self.stopped():
                result.cancelled = True
                break
            price = _api.question_price(q)
            if self.s.strip_specials:
                self._do_special(q, rname, tname, price, i, result)
            if self.s.merge_text_audio:
                self._do_merge(q, rname, tname, price, i, result)
            if self.s.add_titles:
                self._do_titles(q, tag, rname, tname, price, i, result)
            self._progress(i + 1, steps, f"вопрос {i + 1}/{len(questions)}")
    finally:
        # Постеры готовятся фоном, пока идёт опрос базы названий, — тут они
        # догоняют. Даже если цикл сорвался, потоки надо закрыть.
        self._finish_posters(result)

    images: dict[str, tuple[str, str]] = {}
    if heavy and not result.cancelled:
        images = self._do_images(heavy, root, result, len(questions), steps)
    if heavy_audio and not result.cancelled:
        images.update(self._do_audio(heavy_audio, root, result,
                                     len(questions) + len(heavy), steps))
    if heavy_video and not result.cancelled:
        images.update(self._do_video(
            heavy_video, root, result,
            len(questions) + len(heavy) + len(heavy_audio), steps))

    # Мусор ищем ПОСЛЕДНИМ: к этому моменту ссылки уже переписаны на
    # пережатые файлы, а постеры вписаны в ответы — иначе только что
    # добавленное посчиталось бы неиспользуемым.
    dropped: set = set()
    if self.s.drop_unused and not result.cancelled:
        dropped = self._do_unused(root, result, images)

    result.added_bytes = sum(_api.os.path.getsize(p) for p in self._extra.values()
                             if _api.os.path.exists(p))
    try:
        if result.cancelled:
            result.elapsed = _api.time.monotonic() - started
            return result
        result.path = self._write(root, ns, cname, out_path, images,
                                  dropped)
    finally:
        temps = [tmp for _new_name, tmp in images.values()]
        temps += list(self._extra.values())
        # Постеры, которые не дались (в _extra их нет), тоже за собой
        # прибираем: временный файл мог остаться от сорванного кодирования.
        temps += self._poster_temps
        for tmp in temps:
            _api._drop(tmp)
    result.elapsed = _api.time.monotonic() - started
    return result

def _do_empty(self, root, result) -> None:
    """Выкидывает из пака вопросы, в которых пусто.

        Весь пак разом не сносим никогда: если пустыми оказались ВСЕ вопросы,
        значит, содержимое лежит как-то иначе, а не «пак пустой», — и трогать
        такой файл вслепую нельзя."""
    doomed = _api.empty_questions(root)
    if not doomed:
        return
    total = sum(1 for _rname, _tname, _q in _api.iter_questions(root))
    if len(doomed) >= total:
        self.log(f"Пустыми выглядят все {total} вопрос(ов) пака — не трогаю "
                 f"ни одного: пустой пак игре не открыть.")
        return
    for rname, tname, number, box, q in doomed:
        box.remove(q)
        answers = [str(a.text or "").strip() for a in _api.answers_of(q)]
        answers = [a for a in answers if a]
        result.empties.append(_api.Change(
            kind="empty", round_name=rname, theme_name=tname,
            price=_api.question_price(q),
            before=(f"пусто, ответ «{_api._shorten(answers[0], 40)}»"
                    if answers else "пусто, и ответа нет"),
            after="вопрос удалён", order=number))
    self.log(f"Пустых вопросов удалено: {len(doomed)}.")
    for rname, tname in _api.drop_empty_themes(root):
        result.dropped_themes += 1
        self.log(f"«{rname}» · «{tname}»: тема осталась без вопросов — "
                 f"убрал и её.")

def _do_repeats(self, root, questions, result) -> None:
    """Убирает текст, стоящий в каждом вопросе темы («Назвать аниме»), и
        известные подписи (KNOWN_LABELS) — эти и там, где в одном вопросе темы
        подписи всё-таки нет.

        Номер вопроса берётся из общего списка пака: правки всех функций стоят
        в таблице в одном порядке — в том, в каком идут в файле."""
    order_of = {id(q): i for i, (_r, _t, q) in enumerate(questions)}
    for rname, tname, theme_questions in _api.iter_themes(root):
        if self.stopped():
            return
        texts = _api.repeated_texts(theme_questions, self.s.repeat_text_max_len)
        every = {_api.norm_title(t) for t in texts}
        known: set = set()
        if self.s.strip_known_labels:
            labels = _api.known_labels_in(theme_questions,
                                     self.s.repeat_text_max_len)
            known = {_api.norm_title(t) for t in labels} - every
            texts = texts + [t for t in labels if _api.norm_title(t) in known]
        if not texts:
            continue
        keys = every | known
        self.log(f"«{tname}»: убираю "
                 + ", ".join(f"«{t}»" for t in texts))
        for q in theme_questions:
            for text in _api.drop_text_blocks(q, keys):
                known_here = _api.norm_title(text) in known
                result.repeats.append(_api.Change(
                    kind="repeat", round_name=rname, theme_name=tname,
                    price=_api.question_price(q), before=text,
                    after=("убран (известная подпись)" if known_here else
                           "убран (стоял в каждом вопросе темы)"),
                    order=order_of.get(id(q), 0)))

def _do_merge(self, q, rname, tname, price, order, result) -> None:
    """Текст, за которым сразу идёт звук, играет вместе с ним."""
    for text in _api.merge_text_with_audio(q):
        result.merged.append(_api.Change(
            kind="merge", round_name=rname, theme_name=tname, price=price,
            before=_api._shorten(text) or "текстовый блок",
            after="играет одновременно со звуком", order=order))

def _do_special(self, q, rname, tname, price, order, result) -> None:
    key = _api.special_key(q)
    if not key:
        return
    label = _api.SPECIAL_LABELS.get(key, key)
    if key == "secretnoquestion" and not self.s.strip_no_question:
        result.skipped_specials.append(_api.Change(
            kind="special", round_name=rname, theme_name=tname, price=price,
            before=label, after="оставлен как есть", order=order))
        return
    if not _api.has_question_content(q):
        # Обычным вопрос сделать нечем: самого вопроса в нём нет.
        result.skipped_specials.append(_api.Change(
            kind="special", round_name=rname, theme_name=tname, price=price,
            before=label, after="оставлен как есть (нет самого вопроса)",
            order=order))
        return
    _api.make_simple(q)
    result.specials.append(_api.Change(
        kind="special", round_name=rname, theme_name=tname, price=price,
        before=label, after="обычный вопрос", order=order))
