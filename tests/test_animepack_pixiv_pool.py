# -*- coding: utf-8 -*-
"""Верхушка тега, пул случайного выбора и ссылка на работу.

Три беды одного прогона (просьба пользователя): в вопросе оказывался арт с
четырьмя закладками, «случайный» выбор из пака в пак давал один и тот же
рисунок, а ссылка в ответе вела на арт соседнего вопроса."""
import io
import random
from types import SimpleNamespace

import pytest
from PIL import Image

import animepack
import pixiv_art_api
from animepack import PIXIV_ART_KIND, PackSettings, SongCandidate
from pixiv_art_api import PixivArtClient
from test_animepack_new_kinds import make_anime


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), "blue").save(buf, "PNG")
    return buf.getvalue()


_PNG = _png_bytes()


def _row(name, marks=300, **kw):
    row = dict(type="illust", x_restrict=0, illust_ai_type=0, visible=True,
               id=abs(hash(name)) % 10**8, total_bookmarks=marks, width=1200,
               height=1200, page_count=1, tags=[], meta_pages=[],
               image_urls=SimpleNamespace(
                   original=f"https://i.pximg.net/{name}.png"))
    row.update(kw)
    return SimpleNamespace(**row)


class PopularPixivApi:
    """Фейк с верхушкой тега — как настоящий PixivPy."""

    hosts = "https://app-api.pixiv.net"
    access_token = "token"

    def __init__(self, popular, plain=()):
        self.popular = list(popular)
        self.plain = list(plain)
        self.calls = []
        self.words = []

    def auth(self, refresh_token):
        pass

    def no_auth_requests_call(self, method, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        return SimpleNamespace(illusts=list(self.popular))

    @staticmethod
    def parse_result(answer):
        return answer

    def search_illust(self, word, **kwargs):
        self.words.append(word)
        return SimpleNamespace(
            illusts=list(self.plain) if not kwargs.get("offset") else [])

    def download(self, url, fname, referer):
        fname.write(b"")
        return True


def _fetch_pool(client, api):
    """Из чего клиент выбирает арт — без самой загрузки картинки."""
    keep = lambda row: bool(client._url(row)) and client._safe(row)  # noqa: E731
    rows = client._search_word("Death Note", keep)
    rows.sort(key=lambda row: int(row.total_bookmarks or 0), reverse=True)
    good = [row for row in rows if client._good_enough(row)]
    return good[:pixiv_art_api.CHOICE_POOL]


def test_popular_preview_answers_first_and_fills_the_pool():
    """Верхушка тега — один запрос, и обычный поиск уже не нужен.

    Бесплатному ключу обычный поиск отдаёт ВЧЕРАШНИЕ загрузки (popular_desc
    молча заменяют на date_desc), и планку проходила одна работа из девяноста.
    """
    popular = [_row(f"top{n}", marks=5000 - n)
               for n in range(pixiv_art_api.MIN_CHOICES + 4)]
    api = PopularPixivApi(popular, plain=[_row("fresh", marks=0)])
    client = PixivArtClient("token", api=api)
    pool = _fetch_pool(client, api)
    assert len(pool) == len(popular)
    assert api.calls and api.calls[0][0].endswith(pixiv_art_api.POPULAR_PATH)
    assert api.words == []          # до постраничного поиска не дошло


def test_a_thin_tag_top_is_topped_up_by_the_plain_search():
    """У малоизвестного тайтла в верхушке две работы — добираем поиском."""
    api = PopularPixivApi([_row("top", marks=900)],
                          plain=[_row("page", marks=800)])
    client = PixivArtClient("token", api=api)
    pool = _fetch_pool(client, api)
    assert [row.total_bookmarks for row in pool] == [900, 800]
    assert set(api.words) == {"Death Note"}


def test_the_same_title_does_not_always_give_the_same_art():
    """Из пака в пак по одному тайтлу должны приходить РАЗНЫЕ арты.

    Раньше поиск останавливался на первой годной работе, пул состоял из неё
    одной, и случайность была только на словах (просьба пользователя)."""
    popular = [_row(f"top{n}", marks=5000 - n) for n in range(20)]
    picked = set()
    for seed in range(12):
        api = PopularPixivApi(popular)
        client = PixivArtClient("token", api=api, rng=random.Random(seed))
        pool = _fetch_pool(client, api)
        picked.add(client.rng.choice(pool).image_urls.original)
    assert len(picked) > 3


def test_without_any_good_work_the_title_gets_no_art_at_all():
    """Планку не прошёл никто — значит, вопроса по этому тайтлу не будет.

    Запасной пул «самых замеченных из остальных» и приводил к жалобе: при
    планке в пятнадцать закладок в пак уходила работа с шестью, и из прогона
    в прогон одна и та же — выбирать-то было не из чего."""
    junk = [_row(f"junk{n}", marks=n) for n in range(40)]
    api = PopularPixivApi(junk)
    client = PixivArtClient("token", api=api, min_likes=100)
    assert _fetch_pool(client, api) == []
    with pytest.raises(pixiv_art_api.PixivArtError) as failure:
        client.fetch({"name": "Death Note"})
    # В сообщении видно, ЧТО случилось: работы есть, планку не прошла ни одна.
    assert "закладок" in str(failure.value)


def test_a_weak_first_title_does_not_stop_the_other_title_variants():
    """Одна слабая работа не должна закрывать поиск по остальным именам."""
    class AliasPixivApi(PopularPixivApi):
        def __init__(self):
            super().__init__([])

        def search_illust(self, word, **kwargs):
            self.words.append(word)
            if kwargs.get("offset"):
                return SimpleNamespace(illusts=[])
            rows = ([_row("weak", marks=1)] if word == "魔法少女まどか★マギカ"
                    else [_row("good", marks=500)] if word == "Madoka Magica"
                    else [])
            return SimpleNamespace(illusts=rows)

    api = AliasPixivApi()
    api.download = lambda _url, fname, referer: fname.write(_PNG) or True
    client = PixivArtClient("token", api=api, min_likes=15)
    client._popular_illusts = lambda _query, **_kw: []
    _data, _ext, url = client.fetch({
        "japanese": "魔法少女まどか★マギカ", "name": "Madoka Magica"})
    assert url.endswith("good.png")
    assert "魔法少女まどか★マギカ" in api.words
    assert "Madoka Magica" in api.words


def test_pixiv_title_variants_swap_the_two_star_glyphs():
    words = [word for _card, word in PixivArtClient._titles({
        "japanese": "魔法少女まどか★マギカ"})]
    assert words == ["魔法少女まどか★マギカ", "魔法少女まどか☆マギカ"]


def test_the_likes_bar_is_the_users_own_number():
    """Планка лайков задаётся настройкой, а ноль снимает её совсем."""
    rows = [_row(f"art{n}", marks=n) for n in (0, 5, 20, 900)]
    api = PopularPixivApi(rows)
    strict = PixivArtClient("token", api=api, min_likes=100)
    assert [row.total_bookmarks for row in rows
            if strict._good_enough(row)] == [900]
    default = PixivArtClient("token", api=api)
    assert default.min_likes == pixiv_art_api.MIN_BOOKMARKS == 15
    assert [row.total_bookmarks for row in rows
            if default._good_enough(row)] == [20, 900]
    # Настройки пака клиент читает сам — вкладка передаёт их целиком.
    from types import SimpleNamespace as NS
    from_settings = PixivArtClient("token", api=api,
                                   settings=NS(pixiv_min_likes=5))
    assert [row.total_bookmarks for row in rows
            if from_settings._good_enough(row)] == [5, 20, 900]
    off = PixivArtClient("token", api=api, min_likes=0)
    assert all(off._good_enough(row) for row in rows)


def test_a_broken_popular_preview_falls_back_to_the_plain_search():
    """Адрес верхушки не ответил — прогон идёт обычным поиском, как раньше."""
    api = PopularPixivApi([], plain=[_row("page", marks=800)])

    def boom(*args, **kwargs):
        raise OSError("no network")

    api.no_auth_requests_call = boom
    client = PixivArtClient("token", api=api)
    pool = _fetch_pool(client, api)
    assert [row.total_bookmarks for row in pool] == [800]


def test_minus_tags_never_reach_the_pixiv_query():
    """Минус поиск Pixiv не понимает: «鬼滅の刃 -落書き» отдаёт ноль работ.

    Проверено на живом API — с минусом выдача пуста при поиске по полному
    совпадению тегов и не меняется вовсе при поиске по части тега. Поэтому
    ни один «плохой» тег в запрос уходить не должен, отбор только у себя."""
    for mode in ("exclude", "allow", "only"):
        client = PixivArtClient("token", api=PopularPixivApi([]),
                                r18_mode=mode, ai_mode=mode)
        for query in client._queries("鬼滅の刃"):
            assert "-" not in query.replace("R-18", "")


class TwoArtPixivApi:
    """Два разных арта на два разных названия — как два соседних вопроса."""

    def __init__(self):
        self.downloaded = []

    def auth(self, refresh_token):
        pass

    def search_illust(self, word, **kwargs):
        if kwargs.get("offset"):
            return SimpleNamespace(illusts=[])
        mark = "one" if word == "One" else "two"
        return SimpleNamespace(illusts=[_row(mark, id=1 if mark == "one" else 2)])

    def download(self, url, fname, referer):
        self.downloaded.append(url)
        fname.write(_PNG)
        return True


def test_the_answer_link_belongs_to_its_own_art(tmp_path, monkeypatch):
    """Ссылка в ответе — на арт ЭТОГО вопроса, а не соседнего.

    Медиа качают восемь потоков на один общий клиент Pixiv. Ссылку брали уже
    после сохранения картинки — а сохранение это перекодирование в AVIF,
    секунда с лишним, — и за это время соседний поток успевал переписать её
    своим артом (просьба пользователя: «по ссылке другая картинка»)."""
    api = TwoArtPixivApi()
    settings = PackSettings(
        pct_songs=0, pack_pixiv_art=True, pct_pixiv_art=100,
        pixiv_refresh_token="refresh-secret", pixiv_gemini_check=False,
        out_dir=str(tmp_path))
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=object(), mal=object(), tmdb=object(),
        pixiv=PixivArtClient("refresh-secret", api=api))
    gen.prepare_dirs()
    monkeypatch.setattr(gen, "_poster_bytes", lambda *args: (b"", ""))

    other = make_anime(malId=2, name="Two", japanese="", russian="Два")
    saved = gen._save_image

    def save_and_let_the_neighbour_in(data, base, ext=".jpg"):
        # Ровно то, что делает соседний поток, пока идёт перекодирование.
        gen.pixiv.fetch(other)
        return saved(data, base, ext)

    monkeypatch.setattr(gen, "_to_avif", lambda data, name, ext: True)
    monkeypatch.setattr(gen, "_save_image", save_and_let_the_neighbour_in)
    cand = SongCandidate({}, make_anime(malId=1, name="One", japanese="",
                                        russian="Один"), kind=PIXIV_ART_KIND)
    assert gen._fetch_media(cand)
    assert cand.art_link == "https://www.pixiv.net/artworks/1"
