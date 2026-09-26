# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackUpgrader: _do_titles. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


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
