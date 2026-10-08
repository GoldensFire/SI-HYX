# -*- coding: utf-8 -*-
"""Отбор вопросов не должен жечь кандидатов впустую.

Живой случай: пак из 12 вопросов (манга, сакуга и третий род) набрал 2.
База дала 12904 тайтла, годными оказались 1739 — а до загрузки медиа дошли
семь. Остальные 1732 цикл отбора выбросил, пока восемь потоков были заняты
работой: место в паке было, но занимала его текущая загрузка."""
import collections
from concurrent.futures import Future
import random
import time

import pytest

import animepack
from animepack import MANGA_KIND, SAKUGA_KIND, PackSettings, SongCandidate

from test_animepack_new_kinds import make_anime as _make_anime


def make_anime(**kwargs):
    return _make_anime(**{"related": [], **kwargs})


def _generator(tmp_path, monkeypatch, **over):
    monkeypatch.setattr(animepack, "CONFIG_DIR", str(tmp_path))
    settings = PackSettings(**{
        "pct_songs": 0, "rounds": 1, "themes": 1, "questions": 4,
        "level_min": 0, "level_max": 100, "parallel": 2,
        "pack_manga": True, "pct_manga": 50,
        "pack_sakuga": True, "pct_sakuga": 50, **over})
    return animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=object(), mal=object(), tmdb=object(),
        rng=random.Random(5))


def test_busy_workers_do_not_burn_the_candidate_pool(tmp_path, monkeypatch):
    """Кандидат ждёт свободного потока, а не отправляется в мусор.

    Сакуга занимает оба потока, у манги места свободны — но мангой карточка
    аниме стать не может. Раньше такой кандидат просто выбрасывался: пока
    первые две вырезки качались (и не нашлись), пул успевал кончиться, и на
    сакугу в паке не оставалось ни одного тайтла."""
    gen = _generator(tmp_path, monkeypatch)
    pool = [SongCandidate({}, make_anime(malId=100 + i), kind=SAKUGA_KIND)
            for i in range(4)]
    pool += [SongCandidate({}, make_anime(malId=200 + i), kind=MANGA_KIND,
                           media="manga") for i in range(2)]

    def candidates():
        yield from pool

    monkeypatch.setattr(gen, "iter_candidates", candidates)

    # Первые два тайтла вырезки не дали (обычное дело для Sakugabooru). Без
    # задержки не воспроизвести главное: пока они качаются, цикл отбора
    # успевает пройти весь пул.
    def fetch(cand):
        time.sleep(0.05)
        return cand.mal_id not in (100, 101)

    monkeypatch.setattr(gen, "_fetch_media", fetch)
    picked = gen.select_songs()
    kinds = collections.Counter(c.kind for c in picked)
    assert kinds == {SAKUGA_KIND: 2, MANGA_KIND: 2}, f"набрано {kinds}"


def test_failed_selection_stops_and_joins_running_workers(tmp_path, monkeypatch):
    """Исключение не оставляет загрузчик писать в удалённую рабочую папку."""
    gen = _generator(tmp_path, monkeypatch)
    shutdown = []
    stopped = []

    class Pool:
        def submit(self, _fn, _cand):
            # Загрузка отвечает отказом: отбор дожидается начатых задач и
            # только потом сообщает о сломанном источнике.
            future = Future()
            assert future.set_running_or_notify_cancel()
            future.set_result(False)
            return future

        def shutdown(self, *, wait, cancel_futures):
            shutdown.append((wait, cancel_futures))

    def candidates():
        yield SongCandidate({}, make_anime(malId=100), kind=SAKUGA_KIND)
        raise ValueError("сломанный поток кандидатов")

    monkeypatch.setattr(animepack, "ThreadPoolExecutor", lambda **_kw: Pool())
    monkeypatch.setattr(gen, "iter_candidates", candidates)
    monkeypatch.setattr(gen, "stop_processes", lambda: stopped.append(True))

    with pytest.raises(animepack.AnimePackError, match="сломанный поток"):
        gen.select_songs()

    assert stopped == [True]
    assert shutdown == [(True, True)]


def test_a_spent_catalog_gives_its_slots_away(tmp_path, monkeypatch):
    """Каталог манги кончился — её места забирает сакуга.

    Мангой может стать только карточка из своего каталога, и пока её доля
    висела неисполнимой, цикл требовал кандидатов до последнего тайтла базы."""
    gen = _generator(tmp_path, monkeypatch)
    gen.s.preserve_composition = False      # иначе доли не перекладываются
    quotas = dict(gen.s.question_quotas)
    assert quotas[MANGA_KIND] == 2 and quotas[SAKUGA_KIND] == 2
    gen._spend_kind(MANGA_KIND)
    gen._share_out_dead(quotas, collections.Counter(), collections.Counter())
    assert quotas[MANGA_KIND] == 0 and quotas[SAKUGA_KIND] == 4
    # Уже запущенные загрузки манги при этом живут: род вопросов не «мёртв».
    assert MANGA_KIND not in gen._dead_kinds


def test_the_manga_stream_reports_its_own_end(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch)
    monkeypatch.setattr(gen, "collect_manga_ids", lambda: [])
    assert list(gen._iter_manga_candidates()) == []
    assert gen._spent_kinds == {MANGA_KIND}


# ── Набранная книжная доля закрывает свой каталог ───────────────────────────
def test_a_filled_manga_share_closes_its_stream(tmp_path, monkeypatch):
    """Книжная доля набрана — карточки книг больше не спрашиваются.

    Каталог книг вчетверо больше каталога аниме, а мангой ничто, кроме книги,
    стать не может: пока поток открыт, цикл отбора тянет карточки с Shikimori
    только затем, чтобы их выбросить (в живом логе так ушло шесть минут из
    девяти на «поиск кандидатов»)."""
    gen = _generator(tmp_path, monkeypatch)
    quotas = dict(gen.s.question_quotas)
    counts = collections.Counter()

    counts[MANGA_KIND] = quotas[MANGA_KIND] - 1
    gen._close_spent_streams(quotas, counts)
    assert gen._closed_streams == set()      # доля ещё не набрана

    counts[MANGA_KIND] = quotas[MANGA_KIND]
    gen._close_spent_streams(quotas, counts)
    assert gen._closed_streams == {MANGA_KIND}
    # Заодно род вопросов помечен вычерпанным, иначе места умерших родов
    # вопросов могли бы вернуться манге, которую больше неоткуда взять.
    assert gen._spent_kinds == {MANGA_KIND}
    assert MANGA_KIND not in gen._dead_kinds


def test_a_filled_manga_share_stops_fetching_books(tmp_path, monkeypatch):
    """То же самое целиком: набрав книжную долю, отбор перестаёт их просить."""
    gen = _generator(tmp_path, monkeypatch)
    asked = []

    def books():
        for i in range(5000):
            asked.append(i)
            yield SongCandidate({}, make_anime(malId=200 + i),
                                kind=MANGA_KIND, media="manga")

    def animes():
        for i in range(3):
            yield SongCandidate({}, make_anime(malId=100 + i),
                                kind=SAKUGA_KIND)

    monkeypatch.setattr(gen, "_iter_anime_candidates", animes)
    monkeypatch.setattr(gen, "_iter_manga_candidates", books)
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    kinds = collections.Counter(c.kind for c in picked)
    assert kinds == {SAKUGA_KIND: 2, MANGA_KIND: 2}, f"набрано {kinds}"
    # Раньше каталог книг вычерпывался до конца: места под сакугу в паке были,
    # и цикл продолжал просить кандидатов, а поток отдавал ему только книги.
    # Теперь просмотр упирается в потолок и дальше идут отложенные.
    assert len(asked) <= gen.BOOK_SCAN_MIN + 20, f"книг запрошено {len(asked)}"


def test_a_failed_download_keeps_the_manga_stream_open(tmp_path, monkeypatch):
    """Считаем по ПРИНЯТЫМ вопросам: сорвавшаяся загрузка не закрывает поток."""
    gen = _generator(tmp_path, monkeypatch)
    quotas = dict(gen.s.question_quotas)
    counts = collections.Counter({MANGA_KIND: quotas[MANGA_KIND] - 1})
    gen._manga_seen = 10 ** 6              # каталог просмотрен вдоволь
    gen._close_spent_streams(quotas, counts)
    # Скамейка пуста: добрать сорвавшуюся книгу неоткуда, значит смотрим дальше.
    assert gen._closed_streams == set()


def test_a_long_scan_switches_to_the_bench(tmp_path, monkeypatch):
    """Книг просмотрено вдоволь, а отложенных хватает — каталог закрываем.

    В живом логе так было перебрано 48 050 карточек и отложено 39 149 при
    книжной доле в двадцать вопросов."""
    gen = _generator(tmp_path, monkeypatch)
    quotas = dict(gen.s.question_quotas)
    counts = collections.Counter()
    gen._manga_mix._bench = [object()] * quotas[MANGA_KIND]

    gen._manga_seen = gen.BOOK_SCAN_MIN - 1
    gen._close_spent_streams(quotas, counts)
    assert gen._closed_streams == set()    # каталог ещё толком не смотрели

    gen._manga_seen = max(gen.BOOK_SCAN_MIN,
                          quotas[MANGA_KIND] * gen.BOOK_SCAN_PER_SLOT)
    gen._close_spent_streams(quotas, counts)
    assert gen._closed_streams == {MANGA_KIND}


def test_a_bench_full_of_books_keeps_their_slots(tmp_path, monkeypatch):
    """Каталог книг закрыт, но книжная доля ЖИВА: добрать её есть чем.

    Живой случай: каталог просмотрен на 2000 карточек, на скамейке 400 книг —
    и ровно в этот момент места книг уходили сакуге и кадрам, чей каталог
    давно кончился. Пак вышел 140 вопросов из 144 при полной скамейке."""
    gen = _generator(tmp_path, monkeypatch)
    quotas = dict(gen.s.question_quotas)
    counts = collections.Counter()
    gen._manga_mix._bench = [object()] * (quotas[MANGA_KIND] + 10)
    gen._manga_seen = max(gen.BOOK_SCAN_MIN,
                          quotas[MANGA_KIND] * gen.BOOK_SCAN_PER_SLOT)
    gen._close_spent_streams(quotas, counts)
    assert gen._closed_streams == {MANGA_KIND}   # каталог спрашивать нечего
    assert gen._spent_kinds == set()             # а доля ещё наберётся
    gen._share_out_dead(quotas, counts, collections.Counter())
    assert quotas[MANGA_KIND] == gen.s.question_quotas[MANGA_KIND]


def test_the_bench_fills_the_share_the_catalogue_could_not(tmp_path, monkeypatch):
    """Целиком: книги со скамейки добирают пак до полного размера.

    Каталог отдаёт одни НЕэкранизованные книги, а книжных долей две (половина
    мест — книгам с аниме), поэтому каждая вторая сразу уходит на скамейку и
    доля с одного каталога не набирается. Загрузка небыстрая — цикл отбора
    успевает уйти в ожидание потоков, и как раз там раньше раздавались книжные
    места: пак кончался на трёх вопросах при полной скамейке."""
    gen = _generator(tmp_path, monkeypatch)

    def books():
        for i in range(gen.BOOK_SCAN_MIN + 50):
            yield SongCandidate({}, make_anime(malId=200 + i),
                                kind=MANGA_KIND, media="manga")

    def animes():
        for i in range(2):
            yield SongCandidate({}, make_anime(malId=100 + i),
                                kind=SAKUGA_KIND)

    def fetch(cand):
        time.sleep(0.05)
        return True

    monkeypatch.setattr(gen, "_iter_anime_candidates", animes)
    monkeypatch.setattr(gen, "_iter_manga_candidates", books)
    monkeypatch.setattr(gen, "_fetch_media", fetch)
    picked = gen.select_songs()
    kinds = collections.Counter(c.kind for c in picked)
    assert kinds == {SAKUGA_KIND: 2, MANGA_KIND: 2}, f"набрано {kinds}"


def test_an_empty_bench_keeps_the_catalogue_open(tmp_path, monkeypatch):
    """Добрать долю нечем — перебираем каталог дальше, сколько бы ни смотрели."""
    gen = _generator(tmp_path, monkeypatch)
    quotas = dict(gen.s.question_quotas)
    gen._manga_seen = 10 ** 6
    gen._close_spent_streams(quotas, collections.Counter())
    assert gen._closed_streams == set()


# ── Отвергнутый кандидат возвращает франшизу ────────────────────────────────
def test_a_dropped_candidate_gives_its_franchise_back(tmp_path, monkeypatch):
    """Бронь на серию держит вопрос, а не всякий рассмотренный тайтл.

    Живой лог: «отсеяно „франшиза уже в паке“: 8987» при паке из 134 вопросов —
    франшизы жгли кандидаты, которые вопросами так и не стали."""
    gen = _generator(tmp_path, monkeypatch)
    first, second = make_anime(malId=1), make_anime(malId=2)

    assert gen._accept_anime(first, 1, set(), gen._used_franchise) is True
    cand = SongCandidate({}, first, kind=SAKUGA_KIND)
    cand._reserved = gen._last_reserved
    # Пока бронь держится, второй тайтл той же серии в пак не идёт.
    assert gen._accept_anime(second, 2, set(), gen._used_franchise) is False

    gen._release_candidate(cand)
    assert gen._accept_anime(second, 2, set(), gen._used_franchise) is True
    # Отпустить дважды нельзя: чужую бронь так можно было бы и снять.
    gen._release_candidate(cand)
    assert gen._accept_anime(make_anime(malId=3), 3, set(),
                             gen._used_franchise) is False


def test_an_accepted_question_keeps_holding_its_franchise(tmp_path, monkeypatch):
    """У принятого вопроса бронь никто не снимает."""
    gen = _generator(tmp_path, monkeypatch)
    assert gen._accept_anime(make_anime(malId=1), 1, set(),
                             gen._used_franchise) is True
    assert gen._accept_anime(make_anime(malId=2), 2, set(),
                             gen._used_franchise) is False


# ── Размер выборки каталога считается по родам вопросов ─────────────────────
def test_catalog_sample_grows_for_low_yield_kinds():
    """Сакуге нужно куда больше тайтлов на вопрос, чем кадру."""
    cheap = PackSettings(pct_songs=0, pct_frames=100,
                         rounds=1, themes=1, questions=100)
    rare = PackSettings(pct_songs=0, pct_frames=0, pack_sakuga=True,
                        pct_sakuga=100, rounds=1, themes=1, questions=100)
    assert (animepack.anime_catalog_want(rare)
            > 4 * animepack.anime_catalog_want(cheap))


def test_catalog_sample_does_not_grow_for_ordinary_packs():
    """Пак из песен и кадров набирает ровно столько же, сколько набирал."""
    songs = PackSettings(pct_songs=100, rounds=1, themes=1, questions=100)
    assert animepack.anime_catalog_want(songs) == 100 * animepack.SONG_COST
    frames = PackSettings(pct_songs=0, pct_frames=100,
                          rounds=1, themes=1, questions=100)
    assert animepack.anime_catalog_want(frames) == 100 * animepack.CHEAP_COST


def test_books_are_not_counted_in_the_anime_sample():
    """Карточки книг приезжают из своего каталога со своим запасом."""
    s = PackSettings(pct_songs=0, pct_frames=50, pack_manga=True,
                     pct_manga=50, rounds=1, themes=1, questions=100)
    assert s.question_quotas[MANGA_KIND] == 50
    assert animepack.anime_catalog_want(s) == 50 * animepack.CHEAP_COST
