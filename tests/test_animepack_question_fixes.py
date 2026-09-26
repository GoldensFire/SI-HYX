# -*- coding: utf-8 -*-
"""Сакуга, арты Pixiv, антонимы и подпись прогресса."""
from collections import Counter

import pytest

import animepack as ap
from animepack import PackSettings, SongCandidate
from animepack_api import SakugaApi
import pixiv_art_api
from pixiv_art_api import PixivArtClient
from si_hyx_parts.animepack.anime_pack_generator_select_songs import _busy


# ── Sakugabooru: тег тайтла ──────────────────────────────────────────────────
def _tag_rows(*names):
    return [{"name": name, "type": 3, "count": count}
            for name, count in names]


def test_short_english_name_does_not_steal_a_foreign_tag():
    """«Rainbow» не превращается в `rainbow_sentai_robin`.

    Живая ошибка: у «Rainbow: Nisha Rokubou no Shichinin» английское название —
    просто «Rainbow», точного тега нет, и самым населённым «похожим» оказывался
    сериал 1966 года. В вопросе была одна анимация, а в ответе — другой тайтл."""
    rows = _tag_rows(("rainbow_sentai_robin", 120), ("rainbow_brite", 40))
    assert SakugaApi._pick_tag(rows, "rainbow") == ""


def test_series_suffix_is_still_the_same_title():
    """`shingeki_no_kyojin_series` — тот же тайтл, хвост служебный."""
    rows = _tag_rows(("shingeki_no_kyojin_series", 900),
                     ("shingeki_no_kyojin_the_final_season", 300))
    assert SakugaApi._pick_tag(rows, "shingeki_no_kyojin") == \
        "shingeki_no_kyojin_series"
    # Точное совпадение всегда побеждает самый населённый «похожий».
    rows.append({"name": "shingeki_no_kyojin", "type": 3, "count": 5})
    assert SakugaApi._pick_tag(rows, "shingeki_no_kyojin") == "shingeki_no_kyojin"


def test_yamato_1974_does_not_take_the_2199_remake():
    rows = _tag_rows(("uchuu_senkan_yamato_2199", 98),
                     ("uchuu_senkan_yamato_(1974)", 1),
                     ("uchuu_senkan_yamato_3", 999),
                     ("uchuu_senkan_yamato_2202", 30))
    assert SakugaApi._pick_tag(rows, "uchuu_senkan_yamato", 1974) == \
        "uchuu_senkan_yamato_(1974)"
    assert not SakugaApi._same_series(
        "uchuu_senkan_yamato_2199", "uchuu_senkan_yamato", 1974)


@pytest.mark.parametrize("name,want,ok", [
    ("bleach_tv", "bleach", True),
    ("bleach_2", "bleach", True),
    ("bleach_sennen_kessen_hen", "bleach", False),
    ("one_piece", "one_piece", True),
    # Отдельный полнометражный фильм серии — уже другой тайтл, и ответом на
    # него была бы не та карточка, по которой мы искали тег.
    ("one_piece_film_red", "one_piece", False),
    ("one_punch_man", "one_p", False),
])
def test_same_series_only_allows_service_tails(name, want, ok):
    assert SakugaApi._same_series(name, want) is ok


def test_sakuga_question_has_no_timer_at_all():
    """У вырезки таймера нет вовсе (просьба пользователя): вопрос стоит,
    пока ведущий не перейдёт дальше, сколько бы ни длился сам ролик."""
    s = PackSettings(pct_songs=0, pack_sakuga=True, pct_sakuga=100,
                     sakuga_cut=45, rounds=1, themes=1, questions=1)
    cand = SongCandidate({}, {"malId": 1, "russian": "Тайтл",
                              "airedOn": {"year": 2020}},
                         kind=ap.SAKUGA_KIND)
    cand.has_video = True
    root = ap.ET.fromstring(ap.build_content_xml([cand], s))
    item = root.find(".//s:param[@name='question']/s:item", {"s": ap.SIQ_NS})
    assert item.get("type") == "video" and item.get("duration") is None


# ── Pixiv: что не годится в вопрос ───────────────────────────────────────────
def illust(**over):
    row = {"type": "illust", "x_restrict": 0, "illust_ai_type": 1,
           "visible": True, "tags": [{"name": "オリジナル"}],
           "width": 1200, "height": 1600, "total_bookmarks": 900,
           "page_count": 1}
    row.update(over)
    return row


def _client():
    return PixivArtClient("token", api=object())


@pytest.mark.parametrize("tag", ["crossover", "クロスオーバー", "版権まとめ",
                                 "コラボ", "落書きまとめ"])
def test_multi_franchise_art_is_rejected(tag):
    """Сборная солянка: правильных ответов на картинке столько же, сколько
    франшизий."""
    assert _client()._safe(illust(tags=[{"name": tag}])) is False


@pytest.mark.parametrize("tag", ["Koikatsu", "コイカツ", "MMD", "blender",
                                 "3D", "3DCG"])
def test_three_d_art_is_rejected(tag):
    assert _client()._safe(illust(tags=[{"name": tag}])) is False


@pytest.mark.parametrize("tag", ["落書き", "sketch", "線画", "ラフ画"])
def test_sketches_are_rejected(tag):
    assert _client()._safe(illust(tags=[{"name": tag}])) is False


def test_a_plain_illustration_passes():
    assert _client()._safe(illust()) is True
    # «3d» ищется целым словом, а не куском чужой метки.
    assert _client()._safe(illust(tags=[{"name": "3days"}])) is True


@pytest.mark.parametrize("over,ok", [
    ({}, True),
    ({"width": 400, "height": 400}, False),
    ({"total_bookmarks": 3}, False),
    ({"page_count": 12}, False),
    ({"total_bookmarks": None}, False),
])
def test_quality_bar(over, ok):
    assert _client()._good_enough(illust(**over)) is ok


def _pool_of(monkeypatch, client, *rows):
    """Подменяет поиск целиком: проверяем сам отбор, а не запросы."""
    monkeypatch.setattr(client, "_search_word",
                        lambda word, keep: [row for row in rows if keep(row)])
    monkeypatch.setattr(client, "_ensure_api", lambda: None)
    client.api = type("A", (), {"download": staticmethod(
        lambda url, fname=None, referer=None: fname.write(b"x") and None)})()


def test_the_likes_bar_is_a_ban_and_not_a_preference(monkeypatch):
    """Планку не прошёл никто — вопроса по этому тайтлу не будет вовсе.

    Раньше вместо отказа брались «самые замеченные из остальных», и при планке
    в пятнадцать закладок в пак уходила работа с шестью — причём одна и та же
    из прогона в прогон (просьба пользователя)."""
    client = _client()
    weak = illust(total_bookmarks=1, image_urls={"original": "https://p/1.png"})
    _pool_of(monkeypatch, client, weak)
    with pytest.raises(pixiv_art_api.PixivArtError) as err:
        client.fetch({"name": "Vagabond"})
    assert "закладок" in str(err.value)


def test_a_work_over_the_bar_still_goes_to_the_pack(monkeypatch):
    """Запреты на солянку и трёхмерку при этом остаются в силе."""
    client = _client()
    good = illust(total_bookmarks=90, image_urls={"original": "https://p/1.png"})
    blocked = illust(total_bookmarks=900, tags=[{"name": "koikatsu"}],
                     image_urls={"original": "https://p/2.png"})
    _pool_of(monkeypatch, client, good, blocked)
    with pytest.raises(Exception) as err:       # картинка-заглушка не откроется
        client.fetch({"name": "Vagabond"})
    assert "повреждённую" in str(err.value)


# ── Антонимы ─────────────────────────────────────────────────────────────────
def _title_cand(kind="tv", title="Атака титанов"):
    cand = SongCandidate({}, {"id": 1, "malId": 1, "russian": title,
                              "name": "Shingeki", "kind": kind,
                              "related": [], "airedOn": {"year": 2013},
                              "poster": {"originalUrl": "https://s/p.jpg"}},
                         kind="antonyms")
    cand._title_variant = cand
    return cand


def _pick(gen, cand):
    return gen._pick_kind(cand, Counter(), Counter(),
                          {"antonyms": 1, ap.FRAME_KIND: 1})


@pytest.fixture
def gen(tmp_path):
    return ap.AnimePackGenerator(
        PackSettings(pct_songs=0, pct_frames=50, pack_antonyms=True,
                     pct_antonyms=50),
        frames_history_path=str(tmp_path / "f.json"))


def test_antonyms_need_a_title_with_real_opposites(gen):
    """У «сердца» антонима нет — такое название ждёт другого рода вопроса."""
    gen._title_eligibility = {"Атака титанов": {"eligible": True,
                                                "antonyms": True},
                              "Сердце пандоры": {"eligible": True,
                                                 "antonyms": False}}
    assert _pick(gen, _title_cand()) == "antonyms"
    assert _pick(gen, _title_cand(title="Сердце пандоры")) == ap.FRAME_KIND


@pytest.mark.parametrize("kind,expected", [
    ("tv", "antonyms"), ("movie", "antonyms"),
    ("ova", ap.FRAME_KIND), ("ona", ap.FRAME_KIND),
    ("special", ap.FRAME_KIND),
])
def test_antonyms_come_only_from_tv_and_movies(gen, kind, expected):
    gen._title_eligibility = {"Атака титанов": {"eligible": True,
                                                "antonyms": True}}
    assert _pick(gen, _title_cand(kind=kind)) == expected


# ── Рамка сложности артов ────────────────────────────────────────────────────
def test_art_bounds_are_separate_from_the_pack_ones(tmp_path):
    gen = ap.AnimePackGenerator(
        PackSettings(pct_songs=0, pct_frames=50, pack_pixiv_art=True,
                     pct_pixiv_art=50, level_min=1, level_max=ap.MAX_LEVEL,
                     art_level_min=1, art_level_max=3),
        frames_history_path=str(tmp_path / "f.json"))
    quotas = {ap.FRAME_KIND: 1, ap.PIXIV_ART_KIND: 1}
    quiet = SongCandidate({}, {"malId": 1, "russian": "Редкость",
                               "airedOn": {"year": 1999},
                               "statusesStats": []}, kind=ap.FRAME_KIND)
    assert quiet.level == ap.MAX_LEVEL
    assert gen._pick_kind(quiet, Counter(), Counter(), quotas) == ap.FRAME_KIND


# ── Подпись прогресса ────────────────────────────────────────────────────────
def test_progress_says_what_is_being_downloaded():
    assert _busy(Counter()) == ""
    assert _busy(Counter({ap.SAKUGA_KIND: 1})) == "Сакуга"
    busy = _busy(Counter({ap.FRAME_KIND: 1, ap.SAKUGA_KIND: 2, "opening": 1}))
    assert busy == "Опенинг, Кадр, Сакуга"
    many = Counter({"opening": 1, "ending": 1, ap.FRAME_KIND: 1,
                    ap.SAKUGA_KIND: 1})
    assert _busy(many).endswith("…")
