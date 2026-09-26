# -*- coding: utf-8 -*-
"""Повтор артов Pixiv между паками, цена вопроса-студии и faststart."""
from types import SimpleNamespace

import animepack as ap
from ffmpeg_faststart import with_faststart
from pixiv_art_api import PixivArtClient
from si_hyx_parts.animepack import exact_repeat
from si_hyx_parts.animepack.studio_question import studio_price
from test_animepack_new_kinds import make_anime
from test_animepack_pixiv_art import FakePixivApi


# ── Pixiv: «не повторять сами вопросы» ─────────────────────────────────
def test_pixiv_art_is_fingerprinted_by_its_page_like_in_the_ready_pack():
    """В готовом паке арт узнаётся по ссылке pixiv.net в ответе, и у нового
    кандидата отпечаток обязан быть тем же — хеш AVIF у прогона свой."""
    cand = ap.SongCandidate({}, make_anime(), kind=ap.PIXIV_ART_KIND)
    cand.art_link = "https://www.pixiv.net/artworks/147777464"
    keys = exact_repeat.candidate_keys(cand, "")
    old_pack = exact_repeat._source_keys(
        ["Приключения во времени", "https://www.pixiv.net/artworks/147777464"])
    assert keys & old_pack
    assert exact_repeat.pixiv_links(old_pack) == {
        "https://www.pixiv.net/artworks/147777464"}


class _NumberedApi(FakePixivApi):
    def search_illust(self, word, **kwargs):
        def art(number):
            return SimpleNamespace(
                id=number, type="illust", visible=True, total_bookmarks=90,
                width=1400, height=1000, page_count=1, meta_pages=[],
                x_restrict=0, illust_ai_type=0,
                image_urls=SimpleNamespace(
                    original=f"https://i.pximg.net/{number}.png"))
        return SimpleNamespace(illusts=[art(1), art(2)])


def test_pixiv_fetch_skips_works_from_previous_packs():
    client = PixivArtClient("token", api=_NumberedApi())
    for _ in range(5):
        _data, _ext, url = client.fetch(
            make_anime(), skip_links={"https://www.pixiv.net/artworks/1"})
        assert url.endswith("/2.png")
        assert client.last_link == "https://www.pixiv.net/artworks/2"


# ── вопрос-студия ──────────────────────────────────────────────────────
def test_studio_costs_one_and_a_half_average_title_prices():
    levels = [1, 3, 8]
    prices = [ap.price_for_level(level) for level in levels]
    mean, price = studio_price(levels, 0)
    assert mean == sum(prices) / 3
    assert price == round(mean * 1.5)


def test_assign_prices_uses_the_three_titles_of_the_studio():
    cand = ap.SongCandidate({}, make_anime(), kind=ap.STUDIO_KIND)
    cand.studio_levels = [2, 2, 2]
    ap.assign_prices([cand], ap.PackSettings())
    assert cand.price == round(ap.price_for_level(2) * 1.5)
    assert any("Студия" in line for line in cand.price_parts)


# ── faststart ──────────────────────────────────────────────────────────
def test_faststart_goes_before_an_mp4_output_only():
    cmd = ["ffmpeg", "-y", "-i", "in.mkv", "-c:v", "libx264", "out.MP4"]
    assert with_faststart(cmd)[-3:] == ["-movflags", "+faststart", "out.MP4"]
    # Уже заданные флаги mov не трогаем, как и не-MP4 выходы и трубы.
    frag = cmd[:-1] + ["-movflags", "+frag_keyframe", "out.mp4"]
    assert with_faststart(frag) == frag
    for out in ("out.mkv", "out.webm", "-", "pipe:1", "out.avif"):
        plain = cmd[:-1] + [out]
        assert with_faststart(plain) == plain
