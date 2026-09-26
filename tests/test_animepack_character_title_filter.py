"""Characters named in the title stay usable but cost only one extra point."""
import animepack as ap
from si_hyx_parts.animepack.character_title_filter import character_named_in_title
from animepack import AnimePackGenerator, PackSettings, SongCandidate


def test_given_name_inside_title_is_rejected():
    character = {"name": "Uzumaki Naruto", "russian": "Наруто Удзумаки"}
    anime = {"name": "Naruto: Shippuuden", "russian": "Наруто: Ураганные хроники"}
    assert character_named_in_title(character, anime)


def test_unrelated_character_is_allowed():
    character = {"name": "Hatake Kakashi", "russian": "Какаси Хатакэ"}
    anime = {"name": "Naruto: Shippuuden", "russian": "Наруто: Ураганные хроники"}
    assert not character_named_in_title(character, anime)


def test_title_synonyms_and_character_aliases_are_checked():
    character = {"name": "Ryuk", "names": ["Ryuuku"]}
    anime = {"name": "Death Note", "synonyms": ["Ryuuku no Techou"]}
    assert character_named_in_title(character, anime)


def test_generator_keeps_a_character_named_in_title_at_reduced_price():
    class Shikimori:
        def characters_by_anime_ids(self, ids, target="anime"):
            return {ids[0]: [
                {"id": 1, "name": "Uzumaki Naruto", "main": True},
            ]}

        def character_favorites(self, char_id):
            return 10

    gen = AnimePackGenerator(
        PackSettings(), session=object(), amq=object(), anisong=object(),
        mal=object(), shikimori=Shikimori(), anilist=object(), kitsu=object(),
        themes=object(), tmdb=object())
    cand = SongCandidate({}, {
        "malId": 20, "name": "Naruto", "russian": "Наруто"},
        kind=ap.CHAR_KIND)
    gen._pick_character(cand)
    assert cand.character["name"] == "Uzumaki Naruto"
    frame = SongCandidate({}, dict(cand.anime), kind=ap.FRAME_KIND)
    ap.assign_prices([frame, cand], PackSettings())
    assert cand.price == frame.price + ap.CHAR_TITLE_PRICE_STEP
    assert any("Имя персонажа уже в названии" in line
               for line in cand.price_parts)


def test_character_query_uses_shikimori_id_not_mal_id():
    asked = []

    class Shikimori:
        def characters_by_anime_ids(self, ids, target="anime"):
            asked.extend(ids)
            return {530: [{"id": 7, "name": "Сома Кадзуя", "main": True}]}

        def character_favorites(self, _char_id):
            return 100

    class Cache:
        def memo(self, *_args):
            return None

        def remember_memo(self, *_args):
            pass

    gen = AnimePackGenerator(
        PackSettings(), session=object(), amq=object(), anisong=object(),
        mal=object(), shikimori=Shikimori(), anilist=object(), kitsu=object(),
        themes=object(), tmdb=object())
    gen.db_cache = Cache()
    cand = SongCandidate({}, {
        "id": 41426, "malId": 530, "name": "Genjitsu Shugi Yuusha",
        "russian": "Герой-рационал перестраивает королевство. Часть 2",
    }, kind=ap.CHAR_KIND)
    gen._pick_character(cand)
    assert asked == [41426]
    assert cand.character["name"] == "Сома Кадзуя"


def test_every_title_level_has_its_own_base_price():
    assert [ap.price_for_level(level) for level in range(1, 16)] == list(
        range(6, 21))


def test_regular_character_price_explains_fixed_role_step():
    anime = {"name": "Death Note", "russian": "Тетрадь смерти"}
    cand = SongCandidate({}, anime, kind=ap.CHAR_KIND,
                         character={"name": "L Lawliet", "main": True},
                         char_favorites=1200)
    ap.assign_prices([cand], PackSettings())
    text = "\n".join(cand.price_parts)
    assert "Главный персонаж" in text
    assert "+4" in text
    assert "Поправка по избранному персонажа" not in text
    assert text.endswith(f"Итого: {cand.price}")


def test_explicit_main_role_takes_the_earliest_title_with_that_role():
    """Фильтр «главные» не отключает первое появление, а сужает его: самое
    раннее произведение, где герой тоже главный. Второстепенная роль в более
    старой «Гинтаме» и анонс ответом не становятся."""
    class Shikimori:
        def character_titles(self, _char_id):
            return {"animes": [
                {"id": 918, "kind": "tv", "aired_on": "2006-04-04",
                 "roles": ["Supporting"]},
                {"id": 9863, "kind": "tv", "aired_on": "2011-04-07",
                 "roles": ["Main"]},
                {"id": 9999, "kind": "tv", "aired_on": "2001-01-01",
                 "status": "anons", "roles": ["Main"]},
                {"id": 12000, "kind": "tv", "aired_on": "2013-01-01",
                 "roles": ["Main"]}], "mangas": []}

    gen = AnimePackGenerator(
        PackSettings(char_roles="main"), session=object(), amq=object(),
        anisong=object(), mal=object(), shikimori=Shikimori(),
        anilist=object(), kitsu=object(), themes=object(), tmdb=object())
    first = {"id": 9863, "malId": 9863, "russian": "Скет Данс",
             "poster": {"originalUrl": "https://x/p.jpg"}}
    asked = []
    gen._animes_by_ids = lambda ids: asked.extend(ids) or [first]
    anime = {"id": 12000, "malId": 12000, "russian": "Скет Данс OVA"}
    cand = SongCandidate({}, anime, kind=ap.CHAR_KIND,
                         character={"id": 7, "name": "Химэ", "main": True})
    gen._use_first_title(cand)
    assert asked == [9863]
    assert cand.anime is first
