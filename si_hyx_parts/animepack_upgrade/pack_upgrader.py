# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackUpgrader. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


class PackUpgrader:
    """Читает .siq, правит content.xml и пишет результат отдельным файлом.

    Медиа из архива не распаковывается вовсе: записи копируются как есть, в том
    же виде и с тем же сжатием, — на паке в сотню мегабайт это секунды, а не
    минуты перекодирования. Исключение — тяжёлые картинки при включённой третьей
    функции: только они и достаются наружу, чтобы уйти в AVIF под лимит."""

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

    def _do_titles(self, q, tag, rname, tname, price, order, result) -> None:
        answers = _api.answers_of(q)
        if not answers:
            return
        queries = _api.answer_queries([a.text for a in answers],
                                 use_others=self.s.use_other_answers,
                                 min_len=self.s.min_query_len)
        if not queries:
            return
        result.checked_answers += 1
        # На теме про мангу первым спрашивается книга: обложка аниме в таком
        # вопросе неверна, а у манхвы аниме может не быть вовсе. Не нашлась —
        # доищем названия по аниме, но постер из него уже не возьмём.
        book_theme = bool(self.s.book_themes) and _api.is_book_theme(tname)
        card, hit, from_book = None, "", False
        for query in queries:
            if self.stopped():
                return
            if book_theme:
                card = self.find_title(query, book=True)
                if card is not None:
                    hit, from_book = query, True
                    break
            card = self.find_title(query)
            if card is not None:
                hit = query
                break
        if card is None:
            result.not_found += 1
            return
        title = str(card.get("russian") or card.get("name") or "")
        # Ответ мог быть именем героя, а не названием: тогда «Mumei» находит
        # одноимённый клип, и вопрос про персонажа обрастал бы чужими
        # названиями и постером. Переспрашиваем базу персонажей — но только
        # когда ответ похож на имя И собственное название тайтла с ним НЕ
        # совпало точь-в-точь: иначе запрос уходил бы на каждый «Shiki» и
        # «Monster» впустую (и, если ему верить, ломал бы их).
        if (self.s.check_characters and _api.looks_like_character_name(hit)
                and not _api.exact_main(hit, card)):
            name = self.find_character(hit)
            if name:
                result.skipped_titles.append(_api.Change(
                    kind="character", round_name=rname, theme_name=tname,
                    price=price, before=hit,
                    after=f"это имя персонажа, не тайтл (нашёлся «{title}»)",
                    title=name, order=order))
                return
        # Постер и написание названия — только на точном совпадении: при
        # нестрогом поиске карточка может быть от сиквела, и подставлять ему
        # чужой постер (или переписывать под него ответ) нельзя.
        exact = _api.is_exact(hit, card)
        if exact:
            result.exact_titles += 1
            # Совпало не буква в букву, а с точностью до опечатки или пробела:
            # правку вносим, но пусть будет видно, что в ответе пака написано
            # не то («Gokukoku no Brunhildr» вместо «Brynhildr», «Tegami bachi»
            # вместо «Tegamibachi»).
            if _api.matched_by_typo(hit, card):
                result.typo_titles += 1
                self.log(f"«{tname}»: ответ «{hit}» написан не так, как на "
                         f"{self.s.source_name} — это «{title}», дописываю "
                         f"названия и ставлю постер.")

        place = dict(round_name=rname, theme_name=tname, price=price,
                     title=title, order=order)
        # Написание правим ДО дописывания вариантов: иначе «наруто» осталось бы
        # в паке рядом с только что дописанным правильным «Наруто», и проверка
        # «уже написано» посчитала бы их разными строками.
        if exact and self.s.fix_case:
            for was, now in _api.fix_answer_case(q, card):
                result.recased.append(_api.Change(kind="case", before=was, after=now,
                                             **place))

        first = (answers[0].text or "").strip()
        variants = _api.title_variants(card)[:max(1, self.s.max_variants)]
        added = _api.add_answers(q, tag, variants)
        if added:
            result.titles.append(_api.Change(
                kind="title", before=first,
                after=" / ".join([first] + added), added=added, **place))

        # На теме про мангу обложка ставится только та, что нашлась по книге:
        # тянуть в такой вопрос постер аниме пользователь просил не надо.
        if exact and self.s.add_poster and not self.stopped():
            if book_theme and not from_book:
                self.log(f"«{tname}»: тема про книги, а «{title}» нашёлся "
                         f"только аниме — обложку не ставлю.")
            else:
                self._do_poster(q, tag, card, result, place, book=from_book)

    # ── постер в ответе ───────────────────────────────────────────────────
    def _do_poster(self, q, tag, card: dict, result, place: dict,
                   book: bool = False) -> None:
        if _api.has_answer_media(q):
            # В ответе уже своё медиа (картинка, ролик, дорожка) — постер туда
            # не лезет: он перебил бы то, что автор пака показывает сам.
            return
        job = self._poster_job(card, book=book)
        if job is None:
            return
        if not _api.add_poster(q, tag, job.ref):
            return
        # Размер постера пока неизвестен — он ещё качается; допишется в
        # _finish_posters, когда файл будет готов.
        change = _api.Change(kind="poster", before="в ответе не было картинки",
                        after="постер", **place)
        result.posters.append(change)
        job.uses.append((q, change))

    def _poster_job(self, card: dict, book: bool = False) -> _api.Optional[_api._PosterJob]:
        """Ставит постер тайтла (обложку книги) в очередь на скачивание и
        кодирование. Возвращает задание с уже известным ИМЕНЕМ файла — ссылку в
        вопрос можно писать сразу, не дожидаясь картинки.

        Скачивание с кодированием уходят в фон нарочно: пока постеры готовятся,
        основной ход успевает спросить Shikimori про следующие вопросы, а он
        отвечает не быстрее двух раз в секунду (лимитер). Раньше эти два
        ожидания стояли в очередь друг за другом и вместе занимали больше
        времени, чем вся остальная работа (замер на «Лёгкий аниме пак.siq»:
        постеры 73 с, сеть 47 с из 129 с всего).

        Файл на тайтл один: одно и то же аниме встречается в паке по нескольку
        раз, а весит постер как весь остальной прирост пака. Номера у аниме и
        манги свои, поэтому в ключ и в имя файла идёт ещё и вид записи — иначе
        манга №20 забрала бы себе постер аниме №20."""
        num = str(card.get("malId") or card.get("id") or "").strip()
        poster = card.get("poster") if isinstance(card.get("poster"), dict) else {}
        url = str((poster or {}).get("originalUrl")
                  or (poster or {}).get("mainUrl") or "").strip()
        names = tuple(str(card.get(k) or "").strip()
                      for k in ("name", "english", "russian")
                      if str(card.get(k) or "").strip())
        # Ссылки может не быть вовсе — тогда обложка ещё найдётся в общей
        # кладовой (её мог скачать генератор паков) или на TMDB.
        if not num or not (url or names):
            return None
        key = ("manga:" if book else "") + num
        if key in self._posters:
            # За тем же постером второй раз не ходим — ни удачно, ни впустую.
            return self._posters[key]
        prefix = "shiki_manga_" if book else "shiki_"
        ref = self._free_poster_name(
            f"{prefix}{_api.safe_filename(num, 'poster')}_poster.avif")
        self._taken_names.add(ref.lower())
        try:
            year = int(str((card.get("airedOn") or {}).get("year")
                           or (card.get("releasedOn") or {}).get("year") or 0))
        except (TypeError, ValueError):
            year = 0
        job = _api._PosterJob(ref=ref, url=url,
                         title=str(card.get("russian") or card.get("name") or num),
                         key=_api.poster_cache.anime_key(num, book=book),
                         names=names, year=year,
                         # У аниме-фильма (kind == "movie") TMDB ищет
                         # надёжнее сперва по разделу "movie", а не "tv" — та
                         # же логика, что у поиска обложки в генераторе паков.
                         movie=str(card.get("kind") or "") == "movie",
                         out=_api.os.path.join(_api._temp_dir(),
                                          f"siqposter_{_api.uuid.uuid4().hex}.avif"))
        self._posters[key] = job
        job.future = self._poster_pool().submit(self._poster_file, job)
        return job

    def _poster_pool(self) -> _api.ThreadPoolExecutor:
        """Потоки под постеры. Их немного: качается постер быстро, а кодируется
        тем же libaom, что и картинки пака, — больше трёх сразу только толкались
        бы за процессор."""
        if self._pool is None:
            self._pool = _api.ThreadPoolExecutor(
                max_workers=_api.media_jobs(_api.IMAGE_JOBS),
                thread_name_prefix="siqposter")
        return self._pool

    def _poster_bytes(self, job: _api._PosterJob) -> tuple[bytes, str]:
        """Исходные байты обложки: общая кладовая → Shikimori → TMDB.

        Кладовая та же самая, что у вкладки «Генерация аниме-пака» (просьба
        пользователя: обе вкладки берут обложки из одного места), и скачанное
        сюда же и складывается — в следующий раз качать его не придётся ни
        здесь, ни там."""
        if job.key:
            data, ext = _api.poster_cache.find(job.key)
            if data:
                return data, ext
        data, ext = b"", ".jpg"
        if job.url:
            try:
                data, ext = self._fetch(job.url), self._url_ext(job.url)
            except Exception as e:  # noqa: BLE001 — попробуем ещё TMDB
                job.note = f"Постер «{job.title}»: {e}"
        if not data and job.names and not self.stopped():
            url = self._tmdb_url(job)
            if url:
                try:
                    data, ext = self._fetch(url), self._url_ext(url)
                    job.note = ""
                except Exception as e:  # noqa: BLE001
                    job.note = f"Обложка «{job.title}» с TMDB: {e}"
        if data and job.key:
            _api.poster_cache.put(job.key, data, ext)
        return data, ext

    def _tmdb_url(self, job: _api._PosterJob) -> str:
        """Ссылка на обложку с themoviedb.org («» — ключа нет или не нашлась).

        Ключ тот же, что во вкладке «Генерация аниме-пака»: он лежит в
        настройках программы, отдельного поля здесь нет нарочно."""
        api = getattr(self, "_tmdb", None)
        if api is None:
            key = _api.poster_cache.settings_tmdb_key()
            if not key:
                self._tmdb = False
                return ""
            from animepack_api import TmdbApi
            session = getattr(self._api, "session", None) if self._api else None
            api = self._tmdb = TmdbApi(session, key=key)
        if api is False:
            return ""
        try:
            return api.poster_url(job.names, year=job.year, movie=job.movie)
        except Exception as e:  # noqa: BLE001 — запасной источник не обязателен
            job.note = f"TMDB: {e}"
            self._tmdb = False       # сердится — второй раз не идём
            return ""

    def _poster_file(self, job: _api._PosterJob) -> int:
        """Скачивает и кодирует один постер, возвращает размер готового файла
        (0 — не вышло). Зовётся из потока: правит только своё задание."""
        if self.stopped():
            return 0
        data, ext = self._poster_bytes(job)
        if not data:
            if not job.note:
                job.note = f"Обложка «{job.title}» не нашлась, пропускаю."
            return 0
        raw = _api.os.path.join(_api._temp_dir(), f"siqposter_{_api.uuid.uuid4().hex}{ext}")
        try:
            with open(raw, "wb") as f:
                f.write(data)
            if not self._to_avif(raw, job.out, _api.IMAGE_LIMIT_KB):
                _api._drop(job.out)      # ffmpeg мог оставить недописанный файл
                job.note = f"Постер «{job.title}» не закодировался, пропускаю."
                return 0
            job.size = int(_api.os.path.getsize(job.out))
        except Exception as e:  # noqa: BLE001 — одна картинка не повод падать
            job.note = f"Постер «{job.title}»: {e}"
            return 0
        finally:
            _api._drop(raw)
        return job.size

    def _finish_posters(self, result) -> None:
        """Дожидается постеров и разбирается с теми, что не дались: ссылку из
        вопроса убираем, строку из отчёта тоже — иначе пак ссылался бы на файл,
        которого в нём нет."""
        pool, self._pool = self._pool, None
        if pool is None:
            return
        jobs = [j for j in self._posters.values() if j is not None]
        if self.stopped():
            for job in jobs:
                if job.future is not None:
                    job.future.cancel()
        pool.shutdown(wait=True)
        dead: set = set()
        for job in jobs:
            self._poster_temps.append(job.out)
            if job.size > 0:
                # Имя ASCII — percent-кодировать нечего, ссылка и запись
                # совпадают.
                self._extra[f"{_api.POSTER_DIR}/{job.ref}"] = job.out
                for _q, change in job.uses:
                    change.after = f"постер, {_api.fmt_size(job.size)}"
                continue
            if job.note and not self.stopped():
                self.log(job.note)
            for q, change in job.uses:
                _api.remove_poster(q, job.ref)
                dead.add(id(change))
        if dead:
            result.posters = [ch for ch in result.posters if id(ch) not in dead]

    def _free_poster_name(self, want: str) -> str:
        """Имя, которого в паке ещё нет (в архиве уже может лежать одноимённый
        файл — подменять чужую картинку нельзя)."""
        if not self._taken_names:
            try:
                with _api.zipfile.ZipFile(self.path) as zf:
                    self._taken_names = {
                        _api.unquote(n.replace("\\", "/")).rsplit("/", 1)[-1].lower()
                        for n in zf.namelist()}
            except (OSError, _api.zipfile.BadZipFile):  # pragma: no cover
                self._taken_names = {""}
        base, ext = _api.os.path.splitext(want)
        name = want
        for n in range(2, 1000):
            if name.lower() not in self._taken_names:
                break
            name = f"{base} ({n}){ext}"
        return name

    @staticmethod
    def _url_ext(url: str, default: str = ".jpg") -> str:
        ext = _api.os.path.splitext(str(url or "").split("?")[0])[1].lower()
        return ext if ext in (".jpg", ".jpeg", ".png", ".webp") else default

    def _fetch(self, url: str) -> bytes:
        """Байты картинки. Сессия — общая с клиентом Shikimori (там уже стоят
        заголовки и таймауты), своя заводится только без него."""
        session = getattr(self._api, "session", None) if self._api else None
        if session is None:
            session = getattr(self.api, "session", None)
        if session is None:  # pragma: no cover — клиент всегда с сессией
            import requests
            session = requests.Session()
        resp = session.get(url, timeout=(10, 60))
        resp.raise_for_status()
        return resp.content

    # ── картинки ──────────────────────────────────────────────────────────
    def _heavy_images(self) -> list[tuple[str, int]]:
        """Записи архива с картинками тяжелее порога: [(имя в архиве, байт)]."""
        limit = int(max(0.1, float(self.s.image_min_mb)) * 1024 * 1024)
        heavy: list[tuple[str, int]] = []
        try:
            with _api.zipfile.ZipFile(self.path) as zf:
                for info in zf.infolist():
                    if info.is_dir() or info.file_size <= limit:
                        continue
                    name = _api.unquote(info.filename.replace("\\", "/"))
                    if _api.os.path.splitext(name)[1].lower() in _api.COMPRESS_EXTS:
                        heavy.append((info.filename, info.file_size))
        except (OSError, _api.zipfile.BadZipFile) as e:
            raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
        return heavy

    def _plans(self, heavy, new_ext: str) -> list[_api._MediaPlan]:
        """Что с чем делать: имена новых файлов раздаём ЗАРАНЕЕ и по порядку.

        Само кодирование идёт потом и в несколько потоков, а имена должны
        получаться те же самые, в каком бы порядке кодировки ни закончились."""
        plans: list[_api._MediaPlan] = []
        try:
            with _api.zipfile.ZipFile(self.path) as zf:
                # Занятые ИМЕНА файлов, без папок: ссылка в content.xml зовёт
                # файл по имени, и одноимённые в разных папках — это уже спор.
                taken = {_api.unquote(n.replace("\\", "/")).rsplit("/", 1)[-1].lower()
                         for n in zf.namelist()}
                # Постеры и уже пережатые картинки кладутся раньше, и в архиве
                # их ещё нет — но имена уже заняты.
                taken |= {n.rsplit("/", 1)[-1].lower() for n in self._extra}
                taken |= set(self._new_names)
        except (OSError, _api.zipfile.BadZipFile) as e:
            raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
        for name, size in heavy:
            folder, _, raw_base = name.replace("\\", "/").rpartition("/")
            decoded = _api.unquote(raw_base)
            base, ext = _api.os.path.splitext(decoded)
            # Имя может быть занято: в паках рядом с «кадр.webp» лежит
            # «кадр.avif» (вопрос и ответ одного тайтла). Подменять чужой файл
            # нельзя — берём соседнее свободное имя, ссылка всё равно
            # переписывается на него.
            new_decoded = f"{base}{new_ext}"
            for n in range(2, 100):
                if new_decoded.lower() not in taken:
                    break
                new_decoded = f"{base} ({n}){new_ext}"
            else:  # pragma: no cover — сотня одноимённых файлов в одном паке
                self.log(f"«{decoded}»: свободного имени не нашлось, пропускаю.")
                continue
            taken.add(new_decoded.lower())
            self._new_names.add(new_decoded.lower())
            plans.append(_api._MediaPlan(
                name=name, size=size, decoded=decoded, ext=ext,
                new_decoded=new_decoded, folder=folder,
                percent=(raw_base != decoded)))
        return plans

    def _run_jobs(self, plans: list, work, base_step: int, steps: int,
                  label: str, jobs: int) -> list:
        """Гоняет work(plan) по нескольким потокам и отдаёт ответы В ПОРЯДКЕ
        plans: отчёт и имена файлов не должны зависеть от того, какое
        кодирование закончилось первым.

        Работа тут — внешний ffmpeg, поэтому потоки Python ему не мешают: они
        только ждут процессы (GIL на это время отпущен)."""
        total = len(plans)
        out: list = [None] * total
        jobs = max(1, min(int(jobs), total))
        if jobs == 1:
            for j, plan in enumerate(plans):
                self._progress(base_step + j + 1, steps, f"{label} {j + 1}/{total}")
                out[j] = work(plan)
            return out
        with _api.ThreadPoolExecutor(max_workers=jobs,
                                thread_name_prefix="siqmedia") as pool:
            futures = {pool.submit(work, plan): j for j, plan in enumerate(plans)}
            for done, fut in enumerate(_api.as_completed(futures), start=1):
                out[futures[fut]] = fut.result()
                self._progress(base_step + done, steps, f"{label} {done}/{total}")
        return out

    def _extract(self, plan: _api._MediaPlan, prefix: str) -> str:
        """Достаёт запись из архива во временный файл (свой архив на поток:
        один объект ZipFile на несколько потоков не рассчитан)."""
        raw = _api.os.path.join(_api._temp_dir(),
                           f"{prefix}_{_api.uuid.uuid4().hex}{plan.ext}")
        with _api.zipfile.ZipFile(self.path) as zf, open(raw, "wb") as f:
            f.write(zf.read(plan.name))
        return raw

    def _do_images(self, heavy, root, result, base_step: int,
                   steps: int) -> dict:
        """Пережимает тяжёлые картинки и переписывает ссылки на них.

        Возвращает {имя записи в архиве: (новое имя, путь к готовому AVIF)} —
        сам архив собирается позже, в _write."""
        self.log(f"Картинок тяжелее {self.s.image_min_mb:g} МБ: {len(heavy)}.")
        plans = self._plans(heavy, ".avif")
        made = self._run_jobs(plans, self._compress_one, base_step, steps,
                              "картинка", _api.media_jobs(_api.IMAGE_JOBS))
        done: dict[str, tuple[str, str]] = {}
        for plan, got in zip(plans, made):
            if got is None or not got.out:
                if got is not None and got.note and not self.stopped():
                    self.log(got.note)
                continue
            result.saved_bytes += plan.size - got.size
            result.images.append(_api.Change(
                kind="image", theme_name=plan.decoded, price=0,
                before=f"{plan.ext.lstrip('.') or '?'}, {_api.fmt_size(plan.size)}",
                after=f"avif, {_api.fmt_size(got.size)}",
                title=plan.new_decoded,
                # Картинки идут после всех вопросов — так они и стоят в таблице.
                order=result.questions + len(result.images)))
            done[plan.name] = (plan.new_name, got.out)
        if self.stopped():
            result.cancelled = True
        if done:
            # Ссылка в content.xml зовёт файл по имени, и после переименования
            # её надо перевести на .avif — иначе пак останется без картинок.
            _api.retarget_refs(root, {p.decoded: p.new_decoded for p in plans
                                 if p.name in done})
        return done

    def _compress_one(self, plan: _api._MediaPlan) -> _api.Optional[_api._MediaDone]:
        """Одна картинка: AVIF под лимит. Пустой out — оставляем как было.

        Зовётся из потока: ничего общего с соседями не трогает, всё нужное уже
        разложено по plan, а сообщение для лога отдаётся ответом."""
        if self.stopped():
            return None
        raw = ""
        out = _api.os.path.join(_api._temp_dir(), f"siqimg_{_api.uuid.uuid4().hex}.avif")
        try:
            raw = self._extract(plan, "siqimg")
            if not self._to_avif(raw, out):
                _api._drop(out)          # ffmpeg мог оставить недописанный файл
                return _api._MediaDone(note=f"«{plan.decoded}»: сжать не вышло, "
                                       f"оставляю как есть.")
            new_size = _api.os.path.getsize(out)
            if new_size >= plan.size:
                # Так бывает с крошечными PNG-скриншотами: пережатие только
                # прибавило бы весу.
                _api._drop(out)
                return _api._MediaDone(note=f"«{plan.decoded}»: после сжатия не "
                                       f"легче, оставляю.")
        except (OSError, _api.zipfile.BadZipFile) as e:
            _api._drop(out)
            return _api._MediaDone(note=f"«{plan.decoded}»: {e}")
        finally:
            _api._drop(raw)
        return _api._MediaDone(out=out, size=new_size)

    def _to_avif(self, raw: str, out: str, limit_kb: _api.Optional[int] = None) -> bool:
        """Кодирование — общее с генератором паков и «Обработкой» (avif_fit:
        libaom, tune=iq, подбор CQ под лимит, при нужде ужимание разрешения).
        Настройки те же «быстрые»: cpu-used 8, четыре прохода, сторона 1280.

        limit_kb — под сколько ужимать; по умолчанию это настройка сжатия
        картинок пака, у постера свой лимит (тот же, что у генератора)."""
        from avif_fit import fit_to_limit, start_cq_guess
        limit = max(10, int(limit_kb if limit_kb else self.s.image_limit_kb))
        start = None
        try:
            from config import Image
            with Image.open(raw) as im:
                w, h = im.size
            if max(w, h) > _api.IMAGE_MAX_SIDE:
                k = _api.IMAGE_MAX_SIDE / float(max(w, h))
                w, h = max(1, int(w * k)), max(1, int(h * k))
            start = start_cq_guess(w, h, limit)
        except Exception:  # noqa: BLE001 — без Pillow просто идём с CQ=0
            start = None
        return fit_to_limit(raw, out, limit,
                            speed=max(0, min(8, int(self.s.image_speed))),
                            passes=_api.IMAGE_FIT_PASSES, start_cq=start,
                            max_side=_api.IMAGE_MAX_SIDE,
                            should_stop=self._should_stop)

    # ── аудио ─────────────────────────────────────────────────────────────
    def _heavy_audio(self) -> list[tuple[str, int]]:
        """Записи архива со звуком тяжелее порога: [(имя в архиве, байт)]."""
        limit = int(max(0.1, float(self.s.audio_min_mb)) * 1024 * 1024)
        heavy: list[tuple[str, int]] = []
        try:
            with _api.zipfile.ZipFile(self.path) as zf:
                for info in zf.infolist():
                    if info.is_dir() or info.file_size <= limit:
                        continue
                    name = _api.unquote(info.filename.replace("\\", "/"))
                    if _api.os.path.splitext(name)[1].lower() in _api.AUDIO_EXTS:
                        heavy.append((info.filename, info.file_size))
        except (OSError, _api.zipfile.BadZipFile) as e:
            raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
        return heavy

    def _do_audio(self, heavy, root, result, base_step: int,
                  steps: int) -> dict:
        """Перекодирует тяжёлые дорожки в opus и переписывает ссылки на них.

        Возвращает {имя записи в архиве: (новое имя, путь к готовому opus)} — в
        том же виде, что и картинки: архив собирается позже, в _write."""
        self.log(f"Аудио тяжелее {self.s.audio_min_mb:g} МБ: {len(heavy)}.")
        target = _api.nearest_bitrate(self.s.audio_kbps)
        plans = self._plans(heavy, ".opus")
        made = self._run_jobs(plans, self._compress_audio_one, base_step, steps,
                              "аудио", _api.media_jobs(_api.AUDIO_JOBS))
        done: dict[str, tuple[str, str]] = {}
        for plan, got in zip(plans, made):
            if got is None or not got.out:
                if got is not None and got.note and not self.stopped():
                    self.log(got.note)
                continue
            result.saved_audio_bytes += plan.size - got.size
            result.audios.append(_api.Change(
                kind="audio", theme_name=plan.decoded, price=0,
                before=f"{plan.ext.lstrip('.') or '?'}"
                       + (f", {got.was} кбит" if got.was else "")
                       + f", {_api.fmt_size(plan.size)}",
                after=f"opus {target} кбит, {_api.fmt_size(got.size)}",
                title=plan.new_decoded,
                # Медиа идёт в таблице после вопросов, следом за картинками.
                order=result.questions + result.heavy_images
                + len(result.audios)))
            done[plan.name] = (plan.new_name, got.out)
        if self.stopped():
            result.cancelled = True
        if done:
            _api.retarget_refs(root, {p.decoded: p.new_decoded for p in plans
                                 if p.name in done})
        return done

    def _compress_audio_one(self, plan: _api._MediaPlan) -> _api.Optional[_api._MediaDone]:
        """Одна дорожка: opus на заданном битрейте. Пустой out — оставляем как
        было. Зовётся из потока, как и _compress_one."""
        if self.stopped():
            return None
        target = _api.nearest_bitrate(self.s.audio_kbps)
        raw, was = "", 0
        out = _api.os.path.join(_api._temp_dir(), f"siqaud_{_api.uuid.uuid4().hex}.opus")
        try:
            raw = self._extract(plan, "siqaud")
            was = self._audio_kbps(raw, plan.size)
            # С включённой нормализацией обе оговорки «не трогаю» снимаются:
            # ради неё дорожку и перекодируют, а пропущенная дорожка осталась бы
            # с прежней громкостью — то есть громче или тише всех соседних.
            norm = bool(self.s.audio_norm)
            if was and was <= target and not norm:
                # Перекод тут только испортил бы звук: opus на 192 из mp3 на 128
                # весит примерно столько же, а качества уже не вернуть.
                _api._drop(out)
                return _api._MediaDone(note=f"«{plan.decoded}»: и так {was} кбит — "
                                       f"не трогаю.")
            if not self._to_opus(raw, out):
                _api._drop(out)          # ffmpeg мог оставить недописанный файл
                return _api._MediaDone(note=f"«{plan.decoded}»: перекодировать не "
                                       f"вышло, оставляю как есть.")
            new_size = _api.os.path.getsize(out)
            if new_size >= plan.size and not norm:
                _api._drop(out)
                return _api._MediaDone(note=f"«{plan.decoded}»: после перекода не "
                                       f"легче, оставляю.")
        except (OSError, _api.zipfile.BadZipFile) as e:
            _api._drop(out)
            return _api._MediaDone(note=f"«{plan.decoded}»: {e}")
        finally:
            _api._drop(raw)
        return _api._MediaDone(out=out, size=new_size, was=was)

    def _audio_kbps(self, raw: str, size: int = 0) -> int:
        """Битрейт исходной дорожки в килобитах (0 — узнать не вышло).

        Спрашиваем ffprobe: перекодировать дорожку, которая и так не богаче
        целевого битрейта, — значит просто испортить звук, ничего не выиграв."""
        code, out = _api.run_hidden(
            [_api.FFPROBE, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bit_rate:format=bit_rate,duration",
             "-of", "default=noprint_wrappers=1", raw],
            self._should_stop, timeout=60.0, capture=True)
        if code != 0:
            return 0
        return _api.parse_probe_kbps(out, size)

    def _to_opus(self, raw: str, out: str) -> bool:
        """Кодирование звука — то же, что в генераторе паков и «Обработке»:
        libopus с переменным битрейтом и фиксом раскладки каналов (libopus не
        берёт «боковые» раскладки). Громкость трогаем, только если это включено
        настройкой: в готовом паке её уже выставил автор, и двигать её вслепую
        нельзя.

        Картинки внутри файла (обложка альбома в mp3) отбрасываются: в opus им
        всё равно не лечь, а ffmpeg на них спотыкается."""
        kbps = _api.nearest_bitrate(self.s.audio_kbps)
        code, _out = _api.run_hidden(
            [_api.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", raw,
             "-vn", "-af", _api.audio_filter_chain(self.s), "-c:a", "libopus",
             "-b:a", f"{kbps}k", "-vbr", "on", "-application", "audio", out],
            self._should_stop)
        return code == 0 and _api.os.path.exists(out) and _api.os.path.getsize(out) > 0

    # ── видео ─────────────────────────────────────────────────────────────
    def _video_entries(self) -> list[tuple[str, int]]:
        """Записи архива с видео, которые надо посмотреть: [(имя, байт)].

        С галочкой «кодек не AV1» сюда идут ВСЕ ролики, сколько бы они ни
        весили: тяжёлый он или нет, решается по кодеку, а кодек виден только
        после распаковки (ffprobe читает файл, а не запись архива). Без неё —
        только те, что тяжелее порога, и лишнего никто не распаковывает."""
        limit = int(max(0.1, float(self.s.video_min_mb)) * 1024 * 1024)
        take_all = bool(self.s.video_non_av1)
        heavy: list[tuple[str, int]] = []
        try:
            with _api.zipfile.ZipFile(self.path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    if not take_all and info.file_size <= limit:
                        continue
                    name = _api.unquote(info.filename.replace("\\", "/"))
                    if _api.os.path.splitext(name)[1].lower() in _api.VIDEO_EXTS:
                        heavy.append((info.filename, info.file_size))
        except (OSError, _api.zipfile.BadZipFile) as e:
            raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
        return heavy

    def _do_video(self, heavy, root, result, base_step: int,
                  steps: int) -> dict:
        """Перекодирует ролики в AV1 и переписывает ссылки на них.

        Возвращает {имя записи в архиве: (новое имя, путь к готовому mp4)} — в
        том же виде, что картинки и аудио: архив собирается позже, в _write."""
        why = f"тяжелее {self.s.video_min_mb:g} МБ"
        if self.s.video_non_av1:
            why += " или не в AV1"
        self.log(f"Роликов под перекод ({why}): {len(heavy)}.")
        plans = self._plans(heavy, ".mp4")
        made = self._run_jobs(plans, self._compress_video_one, base_step, steps,
                              "видео", _api.media_jobs(_api.VIDEO_JOBS))
        done: dict[str, tuple[str, str]] = {}
        for plan, got in zip(plans, made):
            if got is None or not got.out:
                if got is not None and got.note and not self.stopped():
                    self.log(got.note)
                continue
            result.saved_video_bytes += plan.size - got.size
            height = _api.nearest_height(self.s.video_height)
            result.videos.append(_api.Change(
                kind="video", theme_name=plan.decoded, price=0,
                before=f"{plan.ext.lstrip('.') or '?'}"
                       + (f", {got.codec}" if got.codec else "")
                       + f", {_api.fmt_size(plan.size)}",
                after=f"av1 crf {max(0, min(63, int(self.s.video_crf)))}"
                      + (f", {height}p" if height else "")
                      + f", {_api.fmt_size(got.size)}",
                title=plan.new_decoded,
                # Медиа идёт в таблице после вопросов: картинки, дорожки, ролики.
                order=result.questions + result.heavy_images
                + len(result.audios) + len(result.videos)))
            done[plan.name] = (plan.new_name, got.out)
        if self.stopped():
            result.cancelled = True
        if done:
            _api.retarget_refs(root, {p.decoded: p.new_decoded for p in plans
                                 if p.name in done})
        return done

    def _compress_video_one(self, plan: _api._MediaPlan) -> _api.Optional[_api._MediaDone]:
        """Один ролик: AV1 + opus. Пустой out — оставляем как было.

        Зовётся из потока, как и картинки с дорожками. Решение «трогать или
        нет» принимается уже здесь: тяжёлый файл берём всегда, лёгкий — только
        если он не в AV1 и это разрешено настройкой."""
        if self.stopped():
            return None
        limit = int(max(0.1, float(self.s.video_min_mb)) * 1024 * 1024)
        raw, codec = "", ""
        out = _api.os.path.join(_api._temp_dir(), f"siqvid_{_api.uuid.uuid4().hex}.mp4")
        try:
            raw = self._extract(plan, "siqvid")
            if plan.size <= limit:
                codec = self._video_codec(raw)
                if not codec:
                    return _api._MediaDone(note=f"«{plan.decoded}»: кодек не "
                                           f"опознан, не трогаю.")
                if codec == _api.VIDEO_TARGET_CODEC:
                    return _api._MediaDone(note=f"«{plan.decoded}»: и так AV1, "
                                           f"легче порога — не трогаю.")
            else:
                codec = self._video_codec(raw)
            if not self._to_av1(raw, out):
                _api._drop(out)          # ffmpeg мог оставить недописанный файл
                return _api._MediaDone(note=f"«{plan.decoded}»: перекодировать не "
                                       f"вышло, оставляю как есть.")
            new_size = _api.os.path.getsize(out)
            if new_size >= plan.size:
                _api._drop(out)
                return _api._MediaDone(note=f"«{plan.decoded}»: после перекода не "
                                       f"легче, оставляю.")
        except (OSError, _api.zipfile.BadZipFile) as e:
            _api._drop(out)
            return _api._MediaDone(note=f"«{plan.decoded}»: {e}")
        finally:
            _api._drop(raw)
        return _api._MediaDone(out=out, size=new_size, codec=codec)

    def _video_codec(self, raw: str) -> str:
        """Кодек первой видеодорожки файла («» — узнать не вышло)."""
        code, out = _api.run_hidden(
            [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1", raw],
            self._should_stop, timeout=60.0, capture=True)
        if code != 0:
            return ""
        return _api.parse_probe_codec(out)

    def _video_filter(self) -> list[str]:
        """`-vf` под выбранную высоту (пусто — разрешение не трогаем).

        Ролик только уменьшается: min с высотой источника не даст растянуть
        480p до «тысячи восьмидесяти» — это был бы вес без единого лишнего
        пикселя. Ширина считается сама и остаётся чётной (-2), иначе libsvtav1
        откажется кодировать."""
        height = _api.nearest_height(self.s.video_height)
        if not height:
            return []
        return ["-vf", f"scale=-2:'min({height},ih)':flags=bicubic"]

    def _to_av1(self, raw: str, out: str) -> bool:
        """Перекод ролика — те же флаги, что во вкладке «Обработка»
        (workers.ProcessWorker._av1_encoder_args) и в генераторе паков:
        libsvtav1, keyint=-1 и scd=1 (ключевые кадры только на сменах сцены),
        crf и пресет из настроек. Звук — тот же opus и с той же нормализацией,
        что у дорожек пака, иначе ролик звучал бы громче соседних вопросов."""
        crf = max(0, min(63, int(self.s.video_crf)))
        preset = max(0, min(13, int(self.s.video_preset)))
        kbps = _api.nearest_bitrate(self.s.audio_kbps)
        cmd = ([_api.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", raw,
                # 0:V? — только настоящее видео: обложки и вложения в av1 не
                # переложить, а ffmpeg на них спотыкается (то же, что
                # workers._map_av_args).
                "-map", "0:V?", "-map", "0:a?",
                "-c:v", "libsvtav1", "-crf", str(crf), "-preset", str(preset),
                "-svtav1-params", f"tune={_api.VIDEO_TUNE}:keyint=-1:scd=1",
                "-pix_fmt", _api.VIDEO_PIX_FMT]
               + self._video_filter()
               + ["-af", _api.audio_filter_chain(self.s), "-c:a", "libopus",
                  "-b:a", f"{kbps}k", "-vbr", "on", "-application", "audio",
                  "-movflags", "+faststart", out])
        code, _out = _api.run_hidden(cmd, self._should_stop, timeout=_api.VIDEO_TIMEOUT)
        return code == 0 and _api.os.path.exists(out) and _api.os.path.getsize(out) > 0

    # ── неиспользуемые файлы ──────────────────────────────────────────────
    def _do_unused(self, root, result, media: dict) -> set:
        """Находит медиа, на которое в паке нет ни одной ссылки, и возвращает
        имена записей, которые в новый архив писать не надо.

        Зовётся ПОСЛЕ всех правок content.xml: ссылки к этому моменту уже
        переписаны на пережатые файлы, а постеры уже вписаны в ответы. media —
        то, что пережато: старое имя записи там сменилось на новое, и по
        старому её, конечно, никто не зовёт."""
        refs = _api.referenced_names(root)
        # Имена, которые пак получит взамен пережатых, тоже считаются занятыми:
        # ссылка на них есть, просто зовут они другой файл.
        try:
            with _api.zipfile.ZipFile(self.path) as zf:
                names = [i.filename for i in zf.infolist() if not i.is_dir()]
                sizes = {i.filename: int(i.file_size) for i in zf.infolist()}
        except (OSError, _api.zipfile.BadZipFile) as e:
            raise _api.UpgradeError(f"Файл не читается как .siq: {e}") from e
        doomed = _api.unused_entries(names, refs, keep=set(media or {}))
        if not doomed:
            self.log("Неиспользуемых файлов в паке нет.")
            return set()
        # Весь пак разом не сносим никогда: если «неиспользуемым» вышло всё
        # медиа, значит ссылки записаны как-то иначе, а не пак из одного мусора.
        media_total = sum(1 for n in names if _api.is_media_entry(n))
        if media_total and len(doomed) >= media_total:
            self.log(f"Неиспользуемыми выглядят все {media_total} файл(ов) "
                     f"медиа — не трогаю ни одного: так не бывает.")
            return set()
        for name in doomed:
            size = sizes.get(name, 0)
            result.saved_unused_bytes += size
            result.unused.append(_api.Change(
                kind="unused", theme_name=_api.entry_basename(name), price=0,
                before=_api.fmt_size(size), after="файл удалён (ссылок на него нет)",
                title=name,
                order=result.questions + result.heavy_images
                + len(result.audios) + len(result.videos) + len(result.unused)))
        self.log(f"Неиспользуемых файлов удалено: {len(doomed)} "
                 f"({_api.fmt_size(result.saved_unused_bytes)}).")
        return set(doomed)

    # ── запись ────────────────────────────────────────────────────────────
    def _out_path(self, out_path: _api.Optional[str]) -> str:
        if out_path:
            target = out_path
        else:
            folder = (self.s.out_dir or "").strip() or _api.os.path.dirname(self.path)
            base = _api.os.path.splitext(_api.os.path.basename(self.path))[0]
            name = _api.safe_filename(f"{base}{_api.OUT_SUFFIX}", "Пак") + ".siq"
            target = _api.os.path.join(folder, name)
        _api.os.makedirs(_api.os.path.dirname(target) or ".", exist_ok=True)
        return str(_api.unique_path(target))

    def _write(self, root, ns: str, cname: str, out_path: _api.Optional[str],
               images: _api.Optional[dict] = None,
               dropped: _api.Optional[set] = None) -> str:
        """Пишет новый .siq: правленый content.xml плюс все прочие записи как
        есть. Исходный файл не трогается — на случай, если правка не понравится.

        images — {имя записи: (новое имя, путь к готовому файлу)}: такие записи
        подменяются пережатыми, остальные копируются байт в байт. dropped —
        имена записей, которые в новый пак не идут вовсе (мусор без ссылок)."""
        images = images or {}
        dropped = dropped or set()
        if ns:
            # Иначе ElementTree расставит по всему файлу префиксы ns0:, и пак
            # перестанет открываться в SIGame.
            _api.ET.register_namespace("", ns)
        xml = _api.ET.tostring(root, encoding="utf-8", xml_declaration=True)
        target = self._out_path(out_path)
        try:
            with _api.zipfile.ZipFile(self.path) as src, \
                    _api.zipfile.ZipFile(target, "w") as dst:
                dst.writestr(cname, xml, _api.zipfile.ZIP_DEFLATED)
                for info in src.infolist():
                    if (info.filename == cname or info.is_dir()
                            or info.filename in dropped):
                        continue
                    made = images.get(info.filename)
                    if made:
                        # Сжатая картинка: имя новое (.avif), сжимать её ещё и
                        # архиватором незачем — AVIF уже сжат.
                        with open(made[1], "rb") as f:
                            dst.writestr(made[0], f.read(), _api.zipfile.ZIP_STORED)
                        continue
                    # Копируем запись КАК ЕСТЬ, вместе с её способом сжатия:
                    # медиа в паках лежит уже сжатым (opus/avif/mp4), и разжимать
                    # его, чтобы тут же сжать обратно, — чистая трата времени.
                    if not _api.copy_zip_entry(src, dst, info):
                        dst.writestr(_api.copy.copy(info), src.read(info.filename))
                # Файлы, которых в исходном паке не было (постеры из ответов).
                for name, tmp in (self._extra or {}).items():
                    if not _api.os.path.exists(tmp):
                        continue
                    with open(tmp, "rb") as f:
                        dst.writestr(name, f.read(), _api.zipfile.ZIP_STORED)
        except (OSError, _api.zipfile.BadZipFile) as e:
            raise _api.UpgradeError(f"Не удалось записать пак: {e}") from e
        return target


PackUpgrader.__module__ = _api.__name__
_api.PackUpgrader = PackUpgrader

# ─────────────────────────────────────────────────────────────────────────────
# Примеры изменений («покажи по три с каждой функции»)
# ─────────────────────────────────────────────────────────────────────────────
def _shorten(text: str, limit: int = 70) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= limit else line[:limit - 1] + "…"

_shorten.__module__ = _api.__name__
_api._shorten = _shorten

def example_lines(result: _api.UpgradeResult, limit: int = 3) -> list[str]:
    """Готовые строки отчёта: по нескольку примеров с каждой функции.

    Пустая функция тоже отчитывается — «ничего не нашлось» это ответ, а не
    повод промолчать."""
    lines: list[str] = []

    lines.append(f"Спецвопросов расколдовано: {len(result.specials)}.")
    for change in result.specials[:limit]:
        lines.append(f"  • {change.place}: «{change.before}» → {change.after}")
    if not result.specials:
        lines.append("  • примеров нет: спецвопросов в паке не нашлось.")
    if result.skipped_specials:
        lines.append(f"  • пропущено {len(result.skipped_specials)}: "
                     f"{_api._shorten(result.skipped_specials[0].after)}.")

    lines.append(f"Ответов дополнено названиями: {len(result.titles)}.")
    for change in result.titles[:limit]:
        added = ", ".join(change.added)
        lines.append(f"  • {change.place}: «{_api._shorten(change.before)}» "
                     f"+ {len(change.added)} вариант(ов) — {_api._shorten(added, 90)}")
    if not result.titles:
        lines.append("  • примеров нет: названий аниме в ответах не опознано.")
    elif result.not_found:
        lines.append(f"  • не нашлось на Shikimori: {result.not_found} из "
                     f"{result.checked_answers} проверенных ответов.")
    if getattr(result, "typo_titles", 0):
        lines.append(f"  • опознано с опечаткой в ответе: {result.typo_titles} "
                     f"(в паке название написано с ошибкой).")
    if result.skipped_titles:
        first = result.skipped_titles[0]
        lines.append(f"  • пропущено как имена персонажей: "
                     f"{len(result.skipped_titles)} (например «{first.before}» "
                     f"— {_api._shorten(first.after, 60)})")

    lines.append(f"Названий переписано как на Shikimori: {len(result.recased)}.")
    for change in result.recased[:limit]:
        lines.append(f"  • {change.place}: «{_api._shorten(change.before)}» → "
                     f"«{_api._shorten(change.after)}»")
    if not result.recased:
        lines.append("  • примеров нет: написание везде и так совпадает.")

    lines.append(f"Постеров поставлено в ответ: {len(result.posters)}"
                 + (f" (пак тяжелее на {_api.fmt_size(result.added_bytes)})."
                    if result.added_bytes > 0 else "."))
    for change in result.posters[:limit]:
        lines.append(f"  • {change.place}: «{_api._shorten(change.title)}» — "
                     f"{change.after}")
    if not result.posters:
        lines.append("  • примеров нет: точных совпадений названия не было."
                     if not result.exact_titles else
                     "  • примеров нет: в ответах уже стояли свои картинки "
                     "либо постера у тайтла на Shikimori нет.")

    repeats = list(getattr(result, "repeats", []))
    lines.append(f"Повторяющихся подписей убрано: {len(repeats)}.")
    for change in repeats[:limit]:
        lines.append(f"  • {change.place}: «{_api._shorten(change.before)}» — убран")
    if not repeats:
        lines.append("  • примеров нет: одинакового текста во всех вопросах "
                     "темы не нашлось.")

    merged = list(getattr(result, "merged", []))
    lines.append(f"Текстов, включённых вместе со звуком: {len(merged)}.")
    for change in merged[:limit]:
        lines.append(f"  • {change.place}: «{_api._shorten(change.before)}» — "
                     f"{change.after}")
    if not merged:
        lines.append("  • примеров нет: текста прямо перед отрывком в паке нет "
                     "(или он уже играл одновременно).")

    empties = list(getattr(result, "empties", []))
    lines.append(f"Пустых вопросов удалено: {len(empties)}"
                 + (f" (и {result.dropped_themes} тем(ы) без вопросов)."
                    if result.dropped_themes else "."))
    for change in empties[:limit]:
        lines.append(f"  • {change.place}: {_api._shorten(change.before)}")
    if not empties:
        lines.append("  • примеров нет: вопросов без содержимого в паке нет.")

    lines.append(f"Картинок сжато: {len(result.images)}"
                 + (f" (пак легче на {_api.fmt_size(result.saved_bytes)})."
                    if result.saved_bytes > 0 else "."))
    for change in result.images[:limit]:
        lines.append(f"  • {_api._shorten(change.theme_name)}: {change.before} → "
                     f"{change.after}")
    if not result.images:
        lines.append("  • примеров нет: картинок тяжелее порога в паке нет."
                     if not result.heavy_images else
                     f"  • примеров нет: ни одну из {result.heavy_images} "
                     f"тяжёлых картинок сжать не вышло.")

    audios = list(getattr(result, "audios", []))
    lines.append(f"Дорожек перекодировано в opus: {len(audios)}"
                 + (f" (пак легче на {_api.fmt_size(result.saved_audio_bytes)})."
                    if result.saved_audio_bytes > 0 else "."))
    for change in audios[:limit]:
        lines.append(f"  • {_api._shorten(change.theme_name)}: {change.before} → "
                     f"{change.after}")
    if not audios:
        lines.append("  • примеров нет: аудио тяжелее порога в паке нет."
                     if not getattr(result, "heavy_audio", 0) else
                     f"  • примеров нет: ни одну из {result.heavy_audio} "
                     f"тяжёлых дорожек перекодировать не пришлось.")

    videos = list(getattr(result, "videos", []))
    lines.append(f"Роликов перекодировано в AV1: {len(videos)}"
                 + (f" (пак легче на {_api.fmt_size(result.saved_video_bytes)})."
                    if result.saved_video_bytes > 0 else "."))
    for change in videos[:limit]:
        lines.append(f"  • {_api._shorten(change.theme_name)}: {change.before} → "
                     f"{change.after}")
    if not videos:
        lines.append("  • примеров нет: видео под перекод в паке нет."
                     if not getattr(result, "heavy_video", 0) else
                     f"  • примеров нет: ни один из {result.heavy_video} "
                     f"роликов перекодировать не пришлось.")

    unused = list(getattr(result, "unused", []))
    lines.append(f"Неиспользуемых файлов удалено: {len(unused)}"
                 + (f" (пак легче на {_api.fmt_size(result.saved_unused_bytes)})."
                    if result.saved_unused_bytes > 0 else "."))
    for change in unused[:limit]:
        lines.append(f"  • {_api._shorten(change.theme_name)}: {change.before} — "
                     f"ссылок нет")
    if not unused:
        lines.append("  • примеров нет: на каждый файл в паке есть ссылка.")
    return lines

example_lines.__module__ = _api.__name__
_api.example_lines = example_lines
