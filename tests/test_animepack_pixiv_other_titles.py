# -*- coding: utf-8 -*-
"""Арт сразу по нескольким тайтлам вопросом быть не может.

Живой случай: https://www.pixiv.net/artworks/97896395 — «2022春アニメ», сборка
сезона, подписанная пятью сериалами сразу. Ни метки кроссовера, ни подборки у
неё нет, страница одна, закладок много — и все прежние проверки она проходила.
В пак работа попала как вопрос про «Дэнс Дэнс Дансэр».
"""
import pixiv_tag_rules
from pixiv_art_api import PixivArtClient, card_titles, norm_title

# Метки той самой работы (как их отдаёт API Pixiv).
SEASON_ART_TAGS = [
    "2022年春アニメ", "SPY×FAMILY", "サマータイムレンダ", "パリピ孔明",
    "ダンス・ダンス・ダンスール", "くノ一ツバキの胸の内",
    "アーニャ・フォージャー", "小舟潮", "今季のアニメ",
]


def _illust(tags, **extra):
    row = {"id": 97896395, "type": "illust", "x_restrict": 0,
           "illust_ai_type": 0, "visible": True, "width": 1200, "height": 900,
           "total_bookmarks": 500, "page_count": 1,
           "tags": [{"name": tag} for tag in tags]}
    row.update(extra)
    return row


def _client(**kwargs):
    return PixivArtClient("token", api=object(), **kwargs)


def test_season_roundup_tags_are_blocked_by_the_tag_rules():
    """Сезонная сборка отсекается ещё списками меток — без каталога."""
    rules = pixiv_tag_rules.TagRules.from_settings(None)
    assert rules.hits(SEASON_ART_TAGS)
    assert not _client()._safe(_illust(SEASON_ART_TAGS))


def test_a_tag_of_another_title_rejects_the_work():
    """Метка ЧУЖОГО тайтла из каталога — повод выбросить работу."""
    known = {norm_title(name) for name in
             ("SPY×FAMILY", "サマータイムレンダ", "パリピ孔明",
              "ダンス・ダンス・ダンスール")}
    client = _client(known_titles=known)
    own = card_titles({"japanese": "ダンス・ダンス・ダンスール",
                       "russian": "Дэнс Дэнс Дансэр"})
    assert client._foreign_title(_illust(SEASON_ART_TAGS), own)


def test_own_titles_and_character_tags_are_not_foreign():
    known = {norm_title("ダンス・ダンス・ダンスール")}
    client = _client(known_titles=known)
    own = card_titles({"japanese": "ダンス・ダンス・ダンスール"})
    tags = ["ダンス・ダンス・ダンスール", "村尾潤平", "イラスト"]
    assert not client._foreign_title(_illust(tags), own)


def test_short_tags_never_count_as_a_title():
    """«Air», «One» и подобные короткие названия совпадают с обычными словами."""
    client = _client(known_titles={norm_title("Air")})
    own = card_titles({"name": "Clannad"})
    assert not client._foreign_title(_illust(["Air", "Clannad"]), own)


def test_without_a_catalog_the_check_stays_silent():
    client = _client()
    assert not client._foreign_title(_illust(SEASON_ART_TAGS), set())


def test_multi_page_work_is_rejected_because_tags_are_shared_between_pages():
    """Pixiv 62877802: стр. 1 — Fate/GO, а тайтловый тег со стр. 2 —
    Hinako Note. API не даёт меток отдельно по страницам, поэтому такую
    публикацию нельзя честно превратить в вопрос по первой картинке."""
    art = _illust(["Fate/GrandOrder", "ひなこのーと"],
                  id=62877802, page_count=3, width=2270, height=3955)
    assert not _client()._good_enough(art)


def test_catalog_title_index_reads_every_bucket(tmp_path):
    import animepack as ap
    cache = ap.ShikimoriDbCache(str(tmp_path / "shiki.json"))
    cache.add_cards("anime", "tv-2022", [
        {"malId": 1, "japanese": "ダンス・ダンス・ダンスール",
         "russian": "Дэнс Дэнс Дансэр"}])
    cache.add_cards("anime", "movies", [{"malId": 2, "name": "SPY×FAMILY"}])
    index = cache.title_index()
    assert norm_title("ダンス・ダンス・ダンスール") in index
    assert norm_title("SPY×FAMILY") in index


def test_the_pixiv_comics_checkbox_is_gone(qapp):
    """Записи type=manga — кадры с репликами, а не рисунок (просьба юзера)."""
    import animepack_tab
    from test_animepack_tab_mix import _FakeMain
    tab = animepack_tab.AnimePackTab(main_window=_FakeMain())
    try:
        assert not hasattr(tab, "chk_pixiv_manga")
        assert tab.collect().pixiv_allow_manga is False
        comic = _illust(["ダンス・ダンス・ダンスール"], type="manga")
        assert not _client(settings=tab.collect())._safe(comic)
    finally:
        tab.cleanup()
