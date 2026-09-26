# -*- coding: utf-8 -*-
"""Книжная часть пака: экранизация, шкала сложности и доли изданий."""
import pytest

import animepack as ap
from animepack import MANGA_KIND, MangaMix, PackSettings, SongCandidate
from si_hyx_parts.animepack.manga_adaptation import (
    adaptation_ids, apply_adaptation, load_adaptations)


def anime_card(count, **over):
    card = {"id": 100, "malId": 100, "name": "Vagabond", "russian": "Вагабонд",
            "kind": "tv", "score": 8.0, "airedOn": {"year": 2010},
            "poster": {"originalUrl": "https://shiki/p.jpg"},
            "related": [], "statusesStats": [{"status": "completed",
                                              "count": count}]}
    card.update(over)
    return card


def manga_card(count, *, adaptation=None, kind="manga", **over):
    related = ([{"relationKind": "adaptation", "anime": {"id": adaptation,
                                                         "kind": "tv"}}]
               if adaptation else [])
    card = {"id": 1, "malId": 656, "name": "Vagabond", "russian": "Вагабонд",
            "kind": kind, "score": 8.9, "airedOn": {"year": 1998},
            "poster": {"originalUrl": "https://shiki/m.jpg"},
            "related": related,
            "statusesStats": [{"status": "completed", "count": count}]}
    card.update(over)
    return card


# ── Шкала сложности ──────────────────────────────────────────────────────────
def test_manga_has_its_own_recognisability_ladder():
    """Читателей у книги на порядок меньше зрителей — считается она отдельно.

    Шаг книжной лесенки тот же, что у анимешной (просьба пользователя: при
    прежнем шаге ×1,44 в 15-й уровень падало 94 % каталога манги): десять
    тысяч книжного индекса — восьмой уровень, тысяча — одиннадцатый."""
    assert ap.index_level(10_000) < ap.index_level(10_000, manga=True)
    assert ap.index_level(10_000, manga=True) == 8
    assert ap.index_level(1_000, manga=True) == 11
    anime = ap.INDEX_LEVELS[ap.MANGA_MIN_LEVEL - 1:]
    for pos in range(len(ap.MANGA_INDEX_LEVELS) - 1):
        book = ap.MANGA_INDEX_LEVELS[pos] / ap.MANGA_INDEX_LEVELS[pos + 1]
        assert book == pytest.approx(anime[pos] / anime[pos + 1], rel=0.05)
    # Низ лесенки на месте, а вот верх книге не положен НИКОГДА: книгу, которой
    # не сняли аниме, знают только читавшие.
    assert ap.index_level(10 ** 9, manga=True) == ap.MANGA_MIN_LEVEL == 6
    assert ap.index_level(0, manga=True) == ap.MAX_LEVEL


def test_the_book_ladder_is_the_common_one_after_the_conversion():
    """Книжная лесенка — не вторая линейка, а та же самая.

    manga_reach переводит книжный счёт на общую шкалу, и уровень после этого
    считается одним и тем же кодом: цена и сложность больше не могут
    разойтись, как расходились, пока лесенок было две."""
    for book in (10 ** 7, 120_000, 30_000, 29_999, 9_250, 1_500, 1_499, 0):
        assert ap.index_level(book, manga=True) == \
            ap.index_level(ap.manga_reach(book))
    # Потолок и есть правило: сколько бы книгу ни читали, выше него не выйдет.
    assert ap.manga_reach(10 ** 7) == ap.MANGA_TOP_INDEX
    assert ap.manga_reach(0) == 0.0


def test_a_widely_read_book_without_an_anime_stays_harder_than_an_adapted_one():
    """«Прощай, Эри» против «Восхождения героя щита» — живой случай.

    В книжных списках у Эри людей БОЛЬШЕ, аниме у неё нет, а у «Героя щита»
    книга скромнее, зато сериал посмотрели сотни тысяч. Пока книжная шкала
    просто растягивалась на все десять уровней, Эри выходила первым уровнем —
    легче «Героя щита». Так быть не должно: разворот манги узнают либо по
    сериалу, либо по тому, что её читали."""
    eri = SongCandidate({}, manga_card(131_000, airedOn={"year": 2022}),
                        media="manga", kind=MANGA_KIND)
    shield = SongCandidate({}, manga_card(78_000), media="manga",
                           kind=MANGA_KIND)
    apply_adaptation(shield, anime_card(660_000, airedOn={"year": 2019}))
    assert eri.own_index > shield.own_index      # читателей у Эри больше
    assert shield.level < eri.level              # а узнают — «Героя щита»
    assert eri.level >= ap.MANGA_MIN_LEVEL


def test_adapted_manga_is_measured_by_its_anime():
    """Книга с экранизацией считается по анимешной шкале и её индексу."""
    hit = SongCandidate({}, manga_card(3_000), media="manga", kind=MANGA_KIND)
    lonely = SongCandidate({}, manga_card(3_000), media="manga", kind=MANGA_KIND)
    assert hit.level == lonely.level == ap.index_level(hit.own_index, manga=True)
    apply_adaptation(hit, anime_card(300_000))
    assert hit.adapted_from and not lonely.adapted_from
    # Узнаваемость взялась от сериала, и шкала стала общей, анимешной.
    assert hit.index == pytest.approx(
        SongCandidate({}, anime_card(300_000)).own_index)
    assert hit.level == ap.index_level(hit.index) < lonely.level


def test_adaptation_ids_take_only_real_adaptations():
    card = manga_card(10, adaptation=100)
    card["related"].append({"relationKind": "sequel", "anime": {"id": 999}})
    card["related"].append({"relationKind": "adaptation", "anime": None})
    assert adaptation_ids(card) == [100]
    assert adaptation_ids(manga_card(10)) == []


def test_load_adaptations_picks_the_most_popular_screen_version(tmp_path):
    """Экранизаций бывает несколько — книгу узнают по самой заметной."""
    gen = ap.AnimePackGenerator(PackSettings(),
                                frames_history_path=str(tmp_path / "f.json"))

    class FakeShiki:
        asked = []

        def animes_by_ids(self, ids):
            FakeShiki.asked.append(list(ids))
            return [anime_card(5_000, id=100, malId=100),
                    anime_card(400_000, id=200, malId=200)]

    gen.shikimori = FakeShiki()
    card = manga_card(10, adaptation=100)
    card["related"].append({"relationKind": "adaptation", "anime": {"id": 200}})
    found = load_adaptations(gen, [card])
    assert found[id(card)]["id"] == 200
    # Спрашиваем один раз пачкой, а не по одному аниме на книгу.
    assert FakeShiki.asked == [[100, 200]]


# ── Старый кэш каталога ──────────────────────────────────────────────────────
def test_a_cached_book_without_related_is_asked_again(tmp_path):
    """Карточка без поля `related` — из кэша, набранного до экранизаций.

    Отличить «экранизаций нет» от «про экранизации не спрашивали» можно только
    по наличию самого поля: у книги без аниме оно приезжает пустым списком. Пока
    мы этого не проверяли, вся манга из старого кэша считалась
    неэкранизованной — «Этот замечательный мир! (2014)» мерился книжной шкалой и
    стоил 20 вместо цены своего аниме плюс два."""
    gen = ap.AnimePackGenerator(PackSettings(),
                                frames_history_path=str(tmp_path / "f.json"))
    stale = manga_card(3_000, malId=656)
    stale.pop("related")                       # так выглядит старый кэш
    gen._manga_cache[656] = stale

    class FakeShiki:
        asked = []

        def mangas_by_ids(self, ids):
            FakeShiki.asked.append(list(ids))
            return [manga_card(3_000, adaptation=100, malId=656)]

    gen.shikimori = FakeShiki()
    cards = gen._mangas_by_ids([656])
    assert FakeShiki.asked == [[656]]
    assert adaptation_ids(cards[0]) == [100]
    # Свежая карточка легла в кэш — второй раз за ней не ходим.
    assert gen._mangas_by_ids([656]) == cards and FakeShiki.asked == [[656]]


def test_a_cached_book_with_empty_related_is_trusted(tmp_path):
    """Пустой список — это ответ «экранизаций нет», и перезапрашивать нечего."""
    gen = ap.AnimePackGenerator(PackSettings(),
                                frames_history_path=str(tmp_path / "f.json"))
    gen._manga_cache[656] = manga_card(3_000, malId=656)

    class NoShiki:
        def mangas_by_ids(self, ids):
            raise AssertionError(f"лишний запрос к Shikimori: {ids}")

    gen.shikimori = NoShiki()
    assert gen._mangas_by_ids([656])[0]["related"] == []


# ── Цена ─────────────────────────────────────────────────────────────────────
def test_adapted_manga_costs_two_more_than_a_frame_of_the_same_anime():
    """Ровно на два балла дороже кадра по тому же аниме (просьба пользователя)."""
    s = PackSettings(rounds=1, themes=1, questions=2)
    frame = SongCandidate({}, anime_card(300_000), kind=ap.FRAME_KIND)
    book = SongCandidate({}, manga_card(3_000), media="manga", kind=MANGA_KIND)
    apply_adaptation(book, anime_card(300_000))
    ap.assign_prices([frame, book], s)
    assert book.price - frame.price == 2


def test_adapted_manga_accepts_every_russian_anime_title():
    book = SongCandidate({}, manga_card(3_000), media="manga", kind=MANGA_KIND)
    anime = anime_card(
        300_000,
        russian="Реинкарнация сильнейшего оммёдзи: Эти монстры слишком слабы",
        synonyms=[
            "Перерождение сильнейшего экзорциста в другом мире",
            "The Reincarnation of the Strongest Onmyouji in Another World",
        ],
    )
    apply_adaptation(book, anime)
    answers = book.answer_variants()
    assert anime["russian"] in answers
    assert "Перерождение сильнейшего экзорциста в другом мире" in answers
    assert anime["synonyms"][1] not in answers


def test_manga_without_an_anime_gets_no_surcharge():
    """Книге без экранизации надбавка не положена: её цена и так посчитана по
    книжному счёту, переведённому на общую шкалу.

    Равной эта цена выходит при равном МЕСТЕ после перевода, а не при равном
    сыром индексе: читателей у книги на порядок меньше зрителей (см.
    MANGA_INDEX_LEVELS)."""
    s = PackSettings(rounds=1, themes=1, questions=2)
    book = SongCandidate({}, manga_card(25_000), media="manga",
                         kind=MANGA_KIND)
    # Аниме ставим РОВНО на то же место общей шкалы, куда встала книга: иначе
    # разошлась бы сама лесенка, и надбавку было бы не разглядеть.
    frame = SongCandidate({}, anime_card(10), kind=ap.FRAME_KIND,
                          franchise_index=book.price_index)
    assert book.price_index == pytest.approx(frame.price_index)
    ap.assign_prices([frame, book], s)
    assert book.price == frame.price


def test_book_is_not_automatically_the_priciest_question():
    """Заметная книга не обязана стоить 20 просто потому, что она книга.

    Цена считается местом в ОДНОЙ лесенке на весь пак, а книжный индекс с
    анимешным несравним напрямую: пока их клали в лесенку как есть, любой
    вопрос по неэкранизованной книге оказывался в самом низу и стоил 20 — так
    «Этот замечательный мир! (2014)» вышел дороже безвестной OVA."""
    s = PackSettings(rounds=1, themes=1, questions=3)
    # Книга крепкая (25 000 читателей), аниме рядом — полузабытое.
    book = SongCandidate({}, manga_card(25_000, airedOn={"year": 2014}),
                         media="manga", kind=MANGA_KIND)
    dim = SongCandidate({}, anime_card(4_000, id=101, malId=101),
                        kind=ap.FRAME_KIND)
    loud = SongCandidate({}, anime_card(900_000, id=102, malId=102),
                         kind=ap.FRAME_KIND)
    ap.assign_prices([book, dim, loud], s)
    assert loud.price < book.price < dim.price


def test_pixiv_art_costs_two_more_than_a_frame():
    s = PackSettings(rounds=1, themes=1, questions=2)
    frame = SongCandidate({}, anime_card(300_000), kind=ap.FRAME_KIND)
    art = SongCandidate({}, anime_card(300_000), kind=ap.PIXIV_ART_KIND)
    ap.assign_prices([frame, art], s)
    assert art.price - frame.price == 2


# ── Реплика ведущего ─────────────────────────────────────────────────────────
def _manga_question(cand):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(ap.build_content_xml([cand], PackSettings()))
    return root.find(".//{*}question")


def test_the_host_says_whether_the_book_was_animated():
    """В ответе по книге ведущий вслух говорит, есть ли аниме-адаптация.

    Реплика идёт с waitForFinish="False", то есть звучит ОДНОВРЕМЕННО с
    обложкой, а не задерживает её (просьба пользователя)."""
    book = SongCandidate({}, manga_card(3_000), media="manga", kind=MANGA_KIND,
                         has_poster=True)
    apply_adaptation(book, anime_card(300_000))
    replic = _manga_question(book).find(
        "./{*}params/{*}param[@name='answer']/{*}item[@placement='replic']")
    assert "Аниме-адаптация есть" in replic.text
    assert replic.get("waitForFinish") == "False"

    lonely = SongCandidate({}, manga_card(3_000), media="manga",
                           kind=MANGA_KIND, has_poster=True)
    replic = _manga_question(lonely).find(
        "./{*}params/{*}param[@name='answer']/{*}item[@placement='replic']")
    assert "Аниме-адаптации нет" in replic.text


def test_the_host_says_when_an_anime_adaptation_is_only_announced():
    book = SongCandidate({}, manga_card(3_000), media="manga", kind=MANGA_KIND,
                         has_poster=True)
    apply_adaptation(book, anime_card(300_000, status="anons"))
    replic = _manga_question(book).find(
        "./{*}params/{*}param[@name='answer']/{*}item[@placement='replic']")
    assert "Аниме-адаптация анонсирована" in replic.text
    assert "Аниме-адаптация есть" not in replic.text


def test_a_frame_question_says_nothing_about_adaptations():
    """Это только про книги: у кадра вместо адаптации читается рейтинг."""
    frame = SongCandidate({}, anime_card(300_000), kind=ap.FRAME_KIND,
                          has_poster=True)
    replic = _manga_question(frame).find(
        "./{*}params/{*}param[@name='answer']/{*}item[@placement='replic']")
    assert "Рейтинг MAL" in replic.text
    assert "адаптац" not in replic.text.casefold()


# ── Доли внутри книжной части ────────────────────────────────────────────────
def _book(adapted=False, kind="manga"):
    cand = SongCandidate({}, manga_card(10, kind=kind), media="manga",
                         kind=MANGA_KIND)
    if adapted:
        apply_adaptation(cand, anime_card(300_000))
    return cand


def test_adapted_share_is_respected():
    mix = MangaMix(PackSettings(manga_adapted_percent=50), 4)
    taken = []
    for cand in [_book(adapted=True) for _ in range(4)]:
        if mix.allows(cand):
            mix.reserve(cand)
            taken.append(cand)
    assert len(taken) == 2                 # половина мест — книгам без аниме
    # Лишние не выброшены: они ждут на скамейке.
    assert len(mix.take_bench()) == 2


def test_manhwa_and_manhua_shares_are_respected():
    mix = MangaMix(PackSettings(manga_adapted_percent=0, manga_pct_manhwa=50,
                                manga_pct_manhua=25), 4)
    kinds = []
    for cand in ([_book(kind="manhwa") for _ in range(4)]
                 + [_book(kind="manhua") for _ in range(4)]
                 + [_book(kind="manga") for _ in range(4)]):
        if mix.allows(cand):
            mix.reserve(cand)
            kinds.append(cand.anime["kind"])
    assert kinds == ["manhwa", "manhwa", "manhua", "manga"]


def test_bench_is_used_when_the_catalogue_runs_dry():
    """Недобранный пак хуже перекоса долей: отложенное идёт в дело."""
    said = []
    mix = MangaMix(PackSettings(manga_adapted_percent=50), 2, log=said.append)
    books = [_book(), _book()]
    assert mix.allows(books[0]) is True
    mix.reserve(books[0])
    assert mix.allows(books[1]) is False
    bench = mix.take_bench()
    assert bench == [books[1]] and said and "отложенные" in said[0]
    # Скамейка опустела, а доли больше не сторожатся.
    assert mix.take_bench() == [] and mix.allows(_book()) is True


def test_bench_gives_the_missing_edition_first():
    """Со скамейки первой уходит книга того издания, которого не хватает.

    Доли к этому времени уже не сторожатся, но порядок остаётся за нами: иначе
    отложенная манхва так и лежит под сотней японских книг, и «беру
    отложенных» снова кончается паком без единой манхвы."""
    # Все места — под экранизованные книги, поэтому неэкранизованные уходят на
    # скамейку независимо от издания.
    mix = MangaMix(PackSettings(manga_adapted_percent=100,
                                manga_pct_manhwa=50), 4)
    for cand in [_book() for _ in range(2)]:
        mix.reserve(cand)                  # японских книг в паке уже вдоволь
    benched = [_book(kind="manga") for _ in range(3)] + [_book(kind="manhwa")]
    for cand in benched:
        assert mix.allows(cand) is False
    assert [c.anime["kind"] for c in mix.take_bench()][0] == "manhwa"


def test_bench_has_a_ceiling():
    """Скамейка не растёт без конца: заполнить долю хватает первых же книг.

    Без потолка она набирала десятки тысяч карточек (в живом логе — 39 149) и
    держала их в памяти весь прогон."""
    from si_hyx_parts.animepack.manga_mix import BENCH_MIN
    mix = MangaMix(PackSettings(manga_adapted_percent=0), 2)
    assert mix.bench_cap == BENCH_MIN      # у маленькой доли — нижняя граница
    books = [_book(adapted=True) for _ in range(BENCH_MIN + 50)]
    for cand in books:
        assert mix.allows(cand) is False   # мест под экранизованные нет вовсе
    assert len(mix.take_bench()) == BENCH_MIN


def test_mix_ignores_anime_candidates_and_empty_quota():
    mix = MangaMix(PackSettings(manga_adapted_percent=100), 0)
    assert mix.allows(_book()) is True
    mix = MangaMix(PackSettings(manga_adapted_percent=100), 2)
    assert mix.allows(SongCandidate({}, anime_card(10), kind=ap.FRAME_KIND))


# ── Общая память о франшизах ─────────────────────────────────────────────────
def test_franchise_is_not_asked_twice_by_anime_and_manga(tmp_path):
    """Кадр из франшизы и страница книги оттуда же в один пак не попадают."""
    gen = ap.AnimePackGenerator(PackSettings(level_min=1, level_max=10),
                                frames_history_path=str(tmp_path / "f.json"))
    anime = anime_card(300_000, franchise="vagabond")
    book = manga_card(300_000, franchise="vagabond")
    assert gen._accept_anime(anime, 100, set(), gen._used_franchise) is True
    assert gen._accept_anime(book, 656, set(), gen._used_franchise,
                             manga=True) is False
    assert gen._skips["франшиза уже в паке"] == 1


def test_manga_bounds_are_separate_from_the_pack_ones(tmp_path):
    gen = ap.AnimePackGenerator(
        PackSettings(level_min=1, level_max=3, manga_level_min=12,
                     manga_level_max=15),
        frames_history_path=str(tmp_path / "f.json"))
    quiet = manga_card(10)                      # книга, которую никто не читал
    assert gen._accept_anime(quiet, 656, set(), set(), manga=True) is True
    assert gen._accept_anime(anime_card(10), 100, set(), set()) is False


# ── Франшиза книги берётся ещё и у её экранизации ────────────────────────────
def test_a_book_reserves_the_franchise_of_its_anime():
    """У манги поле franchise на Shikimori сплошь и рядом пустует, а у её
    аниме-экранизации оно есть. Без этого «Покемон XY: Хупа и столкновение
    веков» (манга) и «Покемон: Хроники приключений» (аниме) спокойно попадали
    в один пак (просьба пользователя)."""
    from si_hyx_parts.animepack.anime_pack_generator__iter_picture_candidates \
        import _franchise_marks

    book = {"id": 1, "malId": 1, "franchise": "",
            "russian": "Покемон XY: Хупа и столкновение веков"}
    film = {"id": 2, "malId": 2, "franchise": "pokemon",
            "russian": "Покемон XY: Хупа и столкновение веков (фильм)"}
    marks = _franchise_marks(book, film)
    assert "pokemon" in marks
    # Корень названия по-прежнему на месте — это вторая линия обороны.
    assert "покемон" in marks
    # Без экранизации остаются только собственные ключи книги.
    assert "pokemon" not in _franchise_marks(book, None)


def test_an_anime_from_the_same_series_is_then_refused(monkeypatch):
    """Ключ экранизации и правда закрывает серию для потока аниме."""
    from si_hyx_parts.animepack.anime_pack_generator__iter_picture_candidates \
        import _franchise_marks

    book_marks = _franchise_marks(
        {"id": 1, "malId": 1, "franchise": "",
         "russian": "Покемон XY: Хупа и столкновение веков"},
        {"id": 2, "malId": 2, "franchise": "pokemon", "russian": "Покемон XY"})
    anime_marks = _franchise_marks(
        {"id": 3, "malId": 3, "franchise": "pokemon",
         "russian": "Покемон: Хроники приключений"}, None)
    assert set(book_marks) & set(anime_marks)
