# -*- coding: utf-8 -*-
"""Сбор «в избранном» отдельной частью базы.

Число живёт только на странице тайтла Shikimori (в API его нет вовсе), поэтому
стоит отдельного запроса на карточку. Раньше его спрашивали лишь у тайтлов,
дошедших до вопроса, и в базе на полсотни тысяч карточек не набиралось ни
одного ответа — а мера эта вторая по важности после списков.
"""
import animepack as ap


def card(mal, people, *, year=2020, kind="tv"):
    return {"id": mal, "malId": mal, "russian": f"Тайтл {mal}", "kind": kind,
            "airedOn": {"year": year}, "score": 8.0,
            "statusesStats": [{"status": "completed", "count": people}]}


# ── кого вообще имеет смысл спрашивать ──────────────────────────────────────
def test_a_title_no_answer_can_move_is_not_asked():
    """Надбавка за избранное работает только в плюс и упирается в потолок.

    Значит, карточке, которой даже максимальная надбавка не поможет дотянуться
    до последнего порога лесенки, ответ ничего не изменит: она останется
    десяткой при любом числе. Спрашивать её — впустую потраченный запрос, а
    запросов тут десятки тысяч."""
    assert ap.favorites_worth_asking(card(1, 100_000)) is True
    assert ap.favorites_worth_asking(card(2, 1)) is False


def test_books_are_weighed_by_the_book_scale():
    """Расширенный хвост аниме не подменяет отдельные книжные пороги.

    Книжная лесенка идёт тем же шагом, что анимешная, и сотня читателей — уже
    не хвост; а вот четыре читателя остаются им и с максимальной надбавкой."""
    quiet = card(3, 4, kind="manga")
    assert ap.favorites_worth_asking(quiet, manga=True) is False
    assert ap.favorites_worth_asking(quiet) is True


def test_targets_go_from_the_loudest_titles_down():
    """Обход долгий, его бросают на середине — первыми должны узнаться те
    карточки, которые и правда попадают в паки."""
    cards = [card(1, 20_000), card(2, 500_000), card(3, 5), card(4, 90_000)]
    assert ap.favorites_targets(cards) == [2, 4, 1, 3]


# ── сам обход ───────────────────────────────────────────────────────────────
class _Shiki:
    """Shikimori, который умеет только отдавать «в избранном»."""

    def __init__(self, stop_after=None, on_ask=None):
        self.asked = []
        self._stop_after = stop_after
        self._on_ask = on_ask

    def title_favorites(self, shiki_id, target="anime"):
        self.asked.append((target, shiki_id))
        if self._on_ask is not None:
            self._on_ask(len(self.asked))
        return 100 + shiki_id

    def random_animes(self, page, **_kw):
        raise AssertionError("«в избранном» каталог не трогает")

    def franchise_parts(self, keys):
        raise AssertionError("«в избранном» франшизы не трогает")


def _gen(tmp_path, shiki, cards_by_part):
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    for part, cards in cards_by_part.items():
        db.add_cards(part, "sig", cards)
    settings = ap.PackSettings(rounds=1, themes=1, questions=5)
    return ap.AnimePackGenerator(settings, shikimori=shiki, db_cache=db), db


def test_the_sweep_asks_the_worthwhile_titles_and_remembers_them(tmp_path):
    shiki = _Shiki()
    gen, db = _gen(tmp_path, shiki, {"anime": [card(1, 300_000), card(2, 5)],
                                     "manga": [card(3, 40_000, kind="manga")]})
    gen.refresh_db(("favorites",))
    # После разделения глубокого хвоста даже пять зрителей могут сменить
    # уровень максимальной поправкой, поэтому карточка (2) тоже спрашивается.
    assert shiki.asked == [("anime", 1), ("anime", 2), ("manga", 3)]
    assert db.memo_group("anime_favorites") == {"1": 101, "2": 102}
    assert db.memo_group("manga_favorites") == {"3": 103}


def test_the_sweep_does_not_ask_twice(tmp_path):
    """Обход можно бросать и продолжать: известное второй раз не спрашивается."""
    shiki = _Shiki()
    gen, db = _gen(tmp_path, shiki, {"anime": [card(1, 300_000),
                                               card(2, 300_000)]})
    db.remember_memo("anime_favorites", 1, 4_000)
    gen.refresh_db(("favorites",))
    assert shiki.asked == [("anime", 2)]
    assert db.memo_group("anime_favorites") == {"1": 4_000, "2": 102}


def test_stopping_keeps_what_the_sweep_already_learned(tmp_path):
    """Обход идёт часами — брошенный на середине, он обязан сохранить всё,
    что успел узнать."""
    halt = []
    shiki = _Shiki(on_ask=lambda asked: halt.append(True))
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    db.add_cards("anime", "sig", [card(1, 900_000), card(2, 300_000)])
    settings = ap.PackSettings(rounds=1, themes=1, questions=5)
    gen = ap.AnimePackGenerator(settings, shikimori=shiki, db_cache=db,
                                should_stop=lambda: bool(halt))
    gen.refresh_db(("favorites",))
    assert shiki.asked == [("anime", 1)]
    assert db.memo_group("anime_favorites") == {"1": 101}


def test_a_gathered_favorite_lifts_the_title_it_belongs_to(tmp_path):
    """Ради этого всё и собирается: узнанное число идёт в индекс.

    Тайтл, который смотрели немногие, а в избранное кладут часто, знают лучше,
    чем говорят списки, — и вопрос по нему должен подешеветь."""
    from si_hyx_parts.animepack_tab import db_rows

    shiki = _Shiki()
    gen, db = _gen(tmp_path, shiki, {"anime": [card(1, 60_000)]})
    before = db_rows.title_rows(db, "anime")[0]
    gen.refresh_db(("favorites",))
    db.reload()
    after = db_rows.title_rows(db, "anime")[0]
    assert after["favorites"] == 101 and before["favorites"] == -1
    assert after["index"] >= before["index"]
