# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_character_favorites_are_read_from_the_page. Public namespace: test_animepack_chars_cache."""
import test_animepack_chars_cache as _api


def test_character_favorites_are_read_from_the_page(fake_session, fake_response):
    """В API этого числа нет вовсе: у GraphQL-типа Character полей про избранное
    не существует, а REST отдаёт лишь флаг «добавил ли я». Берём со страницы."""
    import animepack_api as api
    session = fake_session([("/characters/417",
                             fake_response(text=_api._CHAR_PAGE))])
    assert api.ShikimoriApi(session).character_favorites(417) == 10740

test_character_favorites_are_read_from_the_page.__module__ = _api.__name__
_api.test_character_favorites_are_read_from_the_page = test_character_favorites_are_read_from_the_page

def test_character_without_favorites_is_zero_not_unknown(fake_session,
                                                         fake_response):
    """Страница пришла, блока нет — значит в избранном он ни у кого. А вот 404 и
    посторонний ответ — это «не узнали», и путать их нельзя: иначе сложность
    вопроса считалась бы по случайности."""
    import animepack_api as api
    empty = '<body class="p-characters p-characters-show">пусто</body>'
    session = fake_session([("/characters/5", fake_response(text=empty))])
    assert api.ShikimoriApi(session).character_favorites(5) == 0

    gone = fake_session([("/characters/6", fake_response(status_code=404))])
    assert api.ShikimoriApi(gone).character_favorites(6) == -1

    junk = fake_session([("/characters/7", fake_response(text="<html>?</html>"))])
    assert api.ShikimoriApi(junk).character_favorites(7) == -1
    assert api.ShikimoriApi(junk).character_favorites("ерунда") == -1

test_character_without_favorites_is_zero_not_unknown.__module__ = _api.__name__
_api.test_character_without_favorites_is_zero_not_unknown = test_character_without_favorites_is_zero_not_unknown

def test_franchise_parts_returns_every_season(fake_session):
    """Запрашиваем не одну самую популярную часть, а первые FRANCHISE_PARTS."""
    import animepack_api as api
    asked = {}

    class FakeClient:
        base_url = "https://shikimori.io"

        def _graphql(self, query, variables):
            asked["query"] = query
            return {"f0": [_api._part(1000, 2002), _api._part(900, 2007)], "f1": []}

    parts = api.ShikimoriApi(session=object(),
                             client=FakeClient()).franchise_parts(["naruto",
                                                                   "bleach"])
    assert f"limit: {api.ShikimoriApi.FRANCHISE_PARTS}" in asked["query"]
    assert len(parts["naruto"]) == 2
    # Пустой ответ — тоже ответ: ключ есть, спрашивать снова незачем.
    assert parts["bleach"] == []

test_franchise_parts_returns_every_season.__module__ = _api.__name__
_api.test_franchise_parts_returns_every_season = test_franchise_parts_returns_every_season

def test_franchise_parts_keep_quiet_about_a_broken_batch(fake_session):
    """Сорвавшуюся пачку не выдаём за «частей нет»: разовый обрыв связи иначе
    навсегда осел бы в кэше нулевой узнаваемостью."""
    import animepack_api as api

    class DeadClient:
        base_url = "https://shikimori.io"

        def _graphql(self, query, variables):
            raise RuntimeError("нет связи")

    parts = api.ShikimoriApi(session=object(),
                             client=DeadClient()).franchise_parts(["naruto"])
    assert parts == {}

test_franchise_parts_keep_quiet_about_a_broken_batch.__module__ = _api.__name__
_api.test_franchise_parts_keep_quiet_about_a_broken_batch = test_franchise_parts_keep_quiet_about_a_broken_batch

def test_franchise_parts_stay_below_graphql_complexity_limit():
    """Четырнадцатую франшизу выносим в следующий GraphQL-документ."""
    import animepack_api as api
    sizes = []

    class FakeClient:
        base_url = "https://shikimori.io"

        def _graphql(self, query, variables):
            size = query.count(": animes")
            sizes.append(size)
            return {f"f{i}": [] for i in range(size)}

    keys = [f"series_{i}" for i in range(14)]
    parts = api.ShikimoriApi(session=object(),
                             client=FakeClient()).franchise_parts(keys)
    assert sizes == [13, 1]
    assert set(parts) == set(keys)

test_franchise_parts_stay_below_graphql_complexity_limit.__module__ = _api.__name__
_api.test_franchise_parts_stay_below_graphql_complexity_limit = test_franchise_parts_stay_below_graphql_complexity_limit

def test_franchise_parts_preserve_bracketed_cache_key():
    """Скобки — часть ключа Shikimori и остаются в запросе и кэше."""
    import animepack_api as api
    asked = {}

    class FakeClient:
        base_url = "https://shikimori.io"

        def _graphql(self, query, variables):
            asked["query"] = query
            return {"f0": [_api._part(100, 2024)]}

    parts = api.ShikimoriApi(session=object(),
                             client=FakeClient()).franchise_parts(
                                 ["[oshi_no_ko]"])
    assert 'franchise: "[oshi_no_ko]"' in asked["query"]
    assert list(parts) == ["[oshi_no_ko]"]

test_franchise_parts_preserve_bracketed_cache_key.__module__ = _api.__name__
_api.test_franchise_parts_preserve_bracketed_cache_key = test_franchise_parts_preserve_bracketed_cache_key

def _replic(settings, cand):
    root = _api.ET.fromstring(_api.build_content_xml([cand], settings))
    for item in root.iter():
        if item.get("placement") == "replic":
            return item.text
    return None

_replic.__module__ = _api.__name__
_api._replic = _replic

def test_artist_comes_first_and_nicks_are_bare():
    """Порядок в реплике один и тот же, откуда бы ни собрался пак: сперва
    исполнитель, потом голые ники — без «Есть у» (просьба пользователя)."""
    cand = _api.make_candidate()
    cand.users = ["morr", "kao"]
    marked = _api.PackSettings(rounds=1, themes=1, questions=1, random_mode=True,
                          mark_owners=True)
    by_lists = _api.PackSettings(rounds=1, themes=1, questions=1, random_mode=False,
                            mark_owners=False)
    want = "Исполнитель — 『Nightmare』 · Сложность AMQ — 85 · Рейтинг MAL — 『8.60⭐』 · morr, kao"
    assert _api._replic(marked, cand) == want
    assert _api._replic(by_lists, cand) == want
    assert "Есть у" not in want

test_artist_comes_first_and_nicks_are_bare.__module__ = _api.__name__
_api.test_artist_comes_first_and_nicks_are_bare = test_artist_comes_first_and_nicks_are_bare

def test_nicks_alone_when_the_question_is_not_a_song():
    """У вопроса-персонажа исполнителя нет — остаются одни ники."""
    cand = _api._char_cand(500)
    cand.users = ["morr"]
    s = _api.PackSettings(rounds=1, themes=1, questions=1, random_mode=True,
                     mark_owners=True)
    assert _api._replic(s, cand) == "morr"

test_nicks_alone_when_the_question_is_not_a_song.__module__ = _api.__name__
_api.test_nicks_alone_when_the_question_is_not_a_song = test_nicks_alone_when_the_question_is_not_a_song
