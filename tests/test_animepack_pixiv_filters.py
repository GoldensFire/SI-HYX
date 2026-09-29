# -*- coding: utf-8 -*-
"""Отбор артов Pixiv: фетиши, однополые пары, пейзажи, ссылка и первый сезон.

Отделено от test_animepack_pixiv_art: тот файл и так у предела размера.
"""
import random
from types import SimpleNamespace

from animepack import PIXIV_ART_KIND, SongCandidate
from pixiv_art_api import PixivArtClient
from pixiv_art_api import PixivArtError
import pytest
from si_hyx_parts.animepack.pixiv_art_generation import _is_clip
from test_animepack_new_kinds import make_anime


def art(*tags, **over):
    """Работа Pixiv с заданными метками."""
    row = dict(type="illust", x_restrict=0, illust_ai_type=0, visible=True,
               total_bookmarks=500, width=1200, height=1600, page_count=1,
               id=777,
               tags=[SimpleNamespace(name=t, translated_name="") for t in tags],
               image_urls=SimpleNamespace(original="https://i.pximg.net/a.png"),
               meta_pages=[])
    row.update(over)
    return SimpleNamespace(**row)


def test_fetish_tags_never_pass():
    """Запах, ноги и щекотка не берутся ни при каких настройках."""
    client = PixivArtClient("token", api=object())
    for tag in ("footfetish", "tickling", "smellfetish", "足フェチ", "くすぐり"):
        assert not client._safe(art(tag)), tag
    # Обычная метка про пляж под запрет не попадает.
    assert client._safe(art("summer", "beach"))


def test_same_sex_works_are_off_until_asked():
    """«Гейское» — отдельным выбором, по умолчанию выключенным."""
    strict = PixivArtClient("token", api=object())
    allowed = PixivArtClient("token", api=object(), allow_same_sex=True)
    for tag in ("yaoi", "bl", "yuri", "腐向け"):
        assert not strict._safe(art(tag)), tag
        assert allowed._safe(art(tag)), tag


def test_work_without_a_character_is_skipped():
    """В арте всегда должен быть персонаж — пейзажи мимо."""
    client = PixivArtClient("token", api=object())
    for tag in ("landscape", "背景", "nohumans"):
        assert not client._safe(art(tag)), tag


def test_the_pick_is_random_across_the_whole_pool():
    """Выбирается случайная работа, а не одна и та же самая закладочная."""
    rows = [art("Death Note", id=i, total_bookmarks=1000 - i,
                image_urls=SimpleNamespace(original=f"https://i.pximg.net/{i}.png"))
            for i in range(30)]

    class Api:
        def auth(self, refresh_token):
            pass

        def search_illust(self, word, **kwargs):
            return SimpleNamespace(illusts=rows)

        def download(self, url, fname, referer):
            fname.write(b"x")
            return True

    picked = set()
    for seed in range(12):
        client = PixivArtClient("token", api=Api(), rng=random.Random(seed))
        client._good_enough = staticmethod(lambda row: True)
        try:
            _data, _ext, url = client.fetch(make_anime())
        except Exception:                     # картинка-заглушка не картинка
            url = client.last_link
        picked.add(url)
    assert len(picked) > 3


@pytest.mark.parametrize("title,tags", [
    ("Monster", ("モンスター", "MonsterHunter", "モンハン")),
    ("Kumo no Ito", ("蜘蛛の糸", "CHUNITHM")),
    ("Akira", ("Akira", "BlueArchive", "ブルーアーカイブ")),
])
def test_foreign_franchise_tags_are_rejected_without_gemini(title, tags):
    """Pixiv title tags may name a game character or a generic monster."""
    class Api:
        def auth(self, refresh_token):
            pass

        def search_illust(self, word, **kwargs):
            return SimpleNamespace(illusts=[art(*tags)])

    client = PixivArtClient("token", api=Api())
    with pytest.raises(PixivArtError):
        client.fetch({"name": title, "japanese": tags[0]})


def test_the_art_link_is_the_last_answer_variant():
    """Адрес работы уходит последним вариантом ответа (просьба пользователя)."""
    cand = SongCandidate({}, make_anime(), kind=PIXIV_ART_KIND)
    assert "https://www.pixiv.net/artworks/777" not in cand.answer_variants()
    cand.art_link = "https://www.pixiv.net/artworks/777"
    variants = cand.answer_variants()
    assert variants[-1] == "https://www.pixiv.net/artworks/777"
    assert variants[0] == cand.main_answer


def test_promo_clips_are_not_titles():
    """Самая ранняя часть франшизы бывает промо-роликом — он не тайтл.

    Из-за этого ответом вопроса становилось «Подземелье вкусностей PV (2017)»
    (просьба пользователя)."""
    assert _is_clip({"kind": "pv"})
    assert _is_clip({"kind": "CM"})
    assert _is_clip({"kind": "music"})
    assert not _is_clip({"kind": "tv"})
    assert not _is_clip({})
