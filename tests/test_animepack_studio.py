# -*- coding: utf-8 -*-
"""Вопрос-СТУДИЯ: три разных аниме, а в ответе студия.

Проверяем: три кадра взяты у разных аниме одной студии, постеры склеены в том
же порядке, студия в паке не повторяется, а ответ не выдаёт названия аниме.
"""
import io
import random
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

import animepack
from animepack import FRAME_KIND, STUDIO_KIND, PackSettings, SongCandidate
from si_hyx_parts.animepack import studio_question

from test_animepack_new_kinds import make_anime as _make_anime


def make_anime(**kwargs):
    return _make_anime(**{"related": [], "studios": [{"id": 11, "name": "Madhouse"}],
                          **kwargs})


def _png(size=(320, 180), color="white"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _studio_card(number, studio="Madhouse"):
    return make_anime(
        id=1534 + number, malId=1534 + number,
        name=f"Anime {number}", russian=f"Аниме {number}",
        franchise=f"anime_{number}",
        poster={"originalUrl": f"https://shiki/poster-{number}.jpg"},
        screenshots=[{"originalUrl": f"https://shiki/{number}-{i}.jpg"}
                     for i in range(3)],
        studios=[{"id": 11, "name": studio}])


@pytest.fixture
def generator(tmp_path, monkeypatch):
    monkeypatch.setattr(animepack, "CONFIG_DIR", str(tmp_path))
    settings = PackSettings(
        pct_songs=0, rounds=1, themes=1, questions=3, compress_images=False,
        level_min=0, level_max=100, mark_owners=False, parallel=1,
        pack_studio=True, pct_studio=100)
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=object(), mal=object(), tmdb=object(),
        rng=random.Random(7),
        # Память кадров лежит в РЕАЛЬНОМ %APPDATA% и от подмены CONFIG_DIR не
        # переезжает: путь связывается значением по умолчанию ещё при импорте.
        frames_history_path=str(tmp_path / "frames.json"))
    cards = [_studio_card(i) for i in range(1, 5)]
    gen.db_cache.add_cards("anime", "studio-test", cards)
    gen.db_cache.save()
    colors = {card["malId"]: color for card, color in zip(
        cards, ("red", "green", "blue", "yellow"))}
    monkeypatch.setattr(
        gen, "_poster_bytes",
        lambda cand, _url: (_png((100, 150), colors[cand.mal_id]), ".png"))
    monkeypatch.setattr(gen, "_get_bytes", lambda url, **kw: _png())
    gen.prepare_dirs()
    yield gen
    gen.cleanup()


def _settings(**over):
    base = dict(rounds=1, themes=1, questions=1, pack_studio=True,
                pct_songs=0, pct_studio=100)
    base.update(over)
    return PackSettings(**base)


def _question(cand, settings):
    xml = animepack.build_content_xml([cand], settings)
    root = ET.fromstring(xml)
    return next(node for node in root.iter()
                if node.tag.rsplit("}", 1)[-1] == "question")


def _items(question):
    for param in question.iter():
        if (param.tag.rsplit("}", 1)[-1] == "param"
                and param.get("name") == "question"):
            return list(param)
    return []


# ── Кадры ────────────────────────────────────────────────────────────────────
def test_three_different_frames_are_downloaded(generator):
    gen = generator
    cand = SongCandidate({}, _studio_card(1), kind=STUDIO_KIND)
    assert gen._fetch_media(cand) is True
    assert cand.has_frame
    assert len(cand.question_frames) == 3
    # Кадры именно РАЗНЫЕ: один и тот же дважды — это не три кадра.
    assert len(set(cand.question_frames)) == 3
    assert len(set(cand.extra_frame_urls + [cand.frame_url])) == 3
    assert len({card["malId"] for card in cand.studio_cards}) == 3
    # В ответе — горизонтальная полоса из трёх постеров того же порядка.
    assert cand.has_poster
    with Image.open(gen.folder + "/Images/" + cand.poster_name) as strip:
        assert strip.size == (300, 150)
        expected = [Image.new("RGB", (1, 1), {
            1535: "red", 1536: "green", 1537: "blue", 1538: "yellow",
        }[card["malId"]]).getpixel((0, 0)) for card in cand.studio_cards]
        assert [strip.getpixel((50 + 100 * i, 75)) for i in range(3)] == expected


def test_a_studio_without_three_different_anime_is_skipped(generator):
    gen = generator
    said = []
    gen.log = said.append
    cand = SongCandidate({}, _studio_card(20, "Bones"), kind=STUDIO_KIND)
    assert gen._fetch_media(cand) is False
    assert any("трёх разных франшиз" in line for line in said)


def test_different_seasons_of_one_franchise_are_not_reused(generator):
    """Три сезона «Гинтамы» дают только один кадр, а не весь вопрос."""
    cards = [_studio_card(i, "Sunrise") for i in range(1, 4)]
    for card in cards:
        card["franchise"] = "gintama"
    generator._studio_catalog = {"sunrise": cards}
    got = studio_question._cards_for_studio(
        generator, SongCandidate({}, cards[0], kind=STUDIO_KIND), "Sunrise")
    assert len(got) == 1


def test_studio_titles_are_topped_up_from_shikimori(generator):
    primary = _studio_card(1, "Sunrise")
    extra = [_studio_card(i, "Sunrise") for i in (2, 3)]
    asked = []

    class Shiki:
        def random_animes(self, **kwargs):
            asked.append(kwargs)
            return extra

    generator.shikimori = Shiki()
    generator._studio_catalog = {"sunrise": [primary]}
    got = studio_question._cards_for_studio(
        generator, SongCandidate({}, primary, kind=STUDIO_KIND), "Sunrise")
    assert len(got) == 3
    assert asked[0]["studios"] == (11,)


def test_a_title_without_a_studio_is_skipped(generator):
    gen = generator
    gen.log = lambda *a: None
    cand = SongCandidate({}, make_anime(studios=[]), kind=STUDIO_KIND)
    assert gen._fetch_media(cand) is False


def test_studios_are_asked_once_for_an_old_card(generator, monkeypatch):
    """У карточки из старой базы поля нет ВОВСЕ — доспрашиваем и запоминаем."""
    gen = generator
    card = make_anime()
    card.pop("studios")
    asked = []

    class _Shikimori:
        def animes_by_ids(self, ids):
            asked.append(list(ids))
            return [{"studios": [{"name": "Bones"}]}]

    gen.shikimori = _Shikimori()
    assert studio_question.studio_names(gen, SongCandidate({}, dict(card),
                                                           kind=STUDIO_KIND)) == ["Bones"]
    # Второй раз то же самое берётся из памяти базы, а не из сети.
    assert studio_question.studio_names(gen, SongCandidate({}, dict(card),
                                                           kind=STUDIO_KIND)) == ["Bones"]
    assert len(asked) == 1


def test_the_frames_of_the_studio_question_are_remembered(generator):
    """Память «не повторять» обязана знать ВСЕ кадры вопроса, а не первый."""
    gen = generator
    gen.s.frames_no_repeat = True
    cand = SongCandidate({}, _studio_card(1), kind=STUDIO_KIND)
    assert gen._fetch_media(cand) is True
    gen.save_frames_history([cand])
    saved = {animepack.frame_url_key(url)
             for url in animepack.load_frame_history(gen.frames_history_path)}
    assert len(saved) == 3


# ── Как вопрос выглядит в паке ───────────────────────────────────────────────
def test_the_task_is_shown_together_with_every_frame():
    cand = SongCandidate({}, make_anime(), kind=STUDIO_KIND)
    cand.has_frame = True
    cand.frame_name = "a.jpg"
    cand.extra_frames = ["b.jpg", "c.jpg"]
    cand.studios = ["Madhouse"]
    items = _items(_question(cand, _settings()))
    assert len(items) == 6
    for task, frame in zip(items[0::2], items[1::2]):
        # waitForFinish="False" — надпись идёт ОДНОВРЕМЕННО со своим кадром.
        assert task.get("waitForFinish") == "False"
        assert task.text == animepack.STUDIO_TASK_TEXT
        assert task.get("type") is None
        assert frame.get("type") == "image" and frame.get("isRef") == "True"
        assert frame.get("duration") == "00:00:05"
    assert [item.text for item in items[1::2]] == ["a.jpg", "b.jpg", "c.jpg"]


def test_the_seconds_per_frame_come_from_the_settings():
    cand = SongCandidate({}, make_anime(), kind=STUDIO_KIND)
    cand.has_frame = True
    cand.frame_name = "a.jpg"
    cand.studios = ["Madhouse"]
    items = _items(_question(cand, _settings(studio_seconds=8)))
    assert [item.get("duration") for item in items] == [None, "00:00:08"]


def test_the_answer_is_the_studio_not_the_title():
    cand = SongCandidate({}, make_anime(), kind=STUDIO_KIND)
    cand.studios = ["Madhouse"]
    assert cand.main_answer == "Madhouse"
    variants = cand.answer_variants()
    assert variants == ["Madhouse"]
    assert "Тетрадь смерти" not in variants


def test_the_studio_answer_has_no_author_or_shikimori_rating():
    cand = SongCandidate({}, make_anime(), kind=STUDIO_KIND)
    cand.studios = ["Madhouse"]
    cand.author_name = "Автор случайной первой карточки"
    question = _question(cand, _settings())
    spoken = [item.text for item in question.iter()
              if item.get("placement") == "replic"]
    assert spoken == []


def test_a_studio_is_not_repeated_in_one_pack(generator):
    first = SongCandidate({}, _studio_card(1), kind=STUDIO_KIND)
    second = SongCandidate({}, _studio_card(4), kind=STUDIO_KIND)
    assert generator._fetch_media(first) is True
    assert generator._fetch_media(second) is False


def test_the_studio_question_costs_half_again_the_shown_titles():
    """Цена — в полтора раза больше средней цены трёх показанных тайтлов
    (просьба пользователя), а не цена одного кадра."""
    card = make_anime()
    frame = SongCandidate({}, dict(card), kind=FRAME_KIND)
    studio = SongCandidate({}, dict(card), kind=STUDIO_KIND)
    studio.studios = ["Madhouse"]
    studio.studio_levels = [frame.level] * 3
    animepack.assign_prices([frame, studio], _settings())
    assert studio.price == round(frame.price * 1.5)


def test_the_studio_share_reaches_the_quotas():
    s = _settings(questions=10, themes=1, rounds=1, pct_songs=0, pct_frames=0,
                  pct_chars=0, pct_studio=100)
    assert s.mix_shares[STUDIO_KIND] == 100
    assert s.question_quotas[STUDIO_KIND] == 10


def test_joint_works_of_several_studios_are_not_used(generator):
    """Совместная работа двух студий кадром для вопроса-студии не идёт: по
    такому кадру студию не угадать (просьба пользователя)."""
    primary = _studio_card(1, "Sunrise")
    joint = _studio_card(2, "Sunrise")
    joint["studios"] = [{"id": 11, "name": "Sunrise"},
                        {"id": 12, "name": "Bones"}]
    solo = _studio_card(3, "Sunrise")
    generator._studio_catalog = {"sunrise": [primary, joint, solo]}
    got = studio_question._cards_for_studio(
        generator, SongCandidate({}, primary, kind=STUDIO_KIND), "Sunrise")
    assert {card["malId"] for card in got} == {primary["malId"],
                                               solo["malId"]}
    # Сам тайтл-затравка совместной работы вопросом-студией не становится.
    assert not studio_question.studio_possible(joint)
    said = []
    generator._log_rare = lambda _tag, line: said.append(line)
    cand = SongCandidate({}, joint, kind=STUDIO_KIND)
    assert studio_question.download_frames(generator, cand) is False
    assert any("несколько студий" in line for line in said)
