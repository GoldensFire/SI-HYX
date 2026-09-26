# -*- coding: utf-8 -*-
"""Pixiv API filtering, AVIF path, settings and controls."""
import io
from types import SimpleNamespace

from PIL import Image

import animepack
import animepack_tab
from animepack import PIXIV_ART_KIND, PackSettings, SongCandidate
import pixiv_art_api
from pixiv_art_api import PixivArtClient
from test_animepack_new_kinds import make_anime
from test_animepack_tab_mix import _FakeMain


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), "blue").save(buf, "PNG")
    return buf.getvalue()


class FakePixivApi:
    def __init__(self):
        self.auth_tokens = []
        self.downloaded = []

    def auth(self, refresh_token):
        self.auth_tokens.append(refresh_token)

    def search_illust(self, word, **kwargs):
        # Размер у работ настоящий: планка качества (_good_enough) смотрит и
        # на короткую сторону, а без неё ни одна работа планку не проходит.
        def art(name, marks, **kw):
            return SimpleNamespace(
                type="illust", visible=True, total_bookmarks=marks,
                width=1400, height=1000, page_count=1,
                image_urls=SimpleNamespace(
                    original=f"https://i.pximg.net/{name}.png"),
                meta_pages=[], x_restrict=0, illust_ai_type=0, **kw)
        safe = art("safe", 50)
        unsafe = art("r18", 500)
        unsafe.x_restrict = 1
        ai = art("ai", 400)
        ai.illust_ai_type = 2
        return SimpleNamespace(illusts=[unsafe, ai, safe])

    def download(self, url, fname, referer):
        self.downloaded.append((url, referer))
        fname.write(_png())
        return True


def test_pixiv_client_uses_refresh_token_and_filters_unsafe_art():
    api = FakePixivApi()
    client = PixivArtClient("refresh-secret", api=api)
    # An injected authenticated API skips auth, like a reused application client.
    data, ext, url = client.fetch(make_anime(name="Death Note"))
    assert data == _png() and ext == ".png"
    assert url.endswith("safe.png")
    assert api.downloaded == [(url, "https://app-api.pixiv.net/")]


def test_r18_and_ai_filters_are_independent_but_shock_is_always_blocked():
    client = PixivArtClient(
        "token", api=FakePixivApi(), exclude_r18=False, exclude_ai=False)
    r18 = SimpleNamespace(type="illust", x_restrict=1, illust_ai_type=0,
                          visible=True, tags=[])
    ai = SimpleNamespace(type="illust", x_restrict=0, illust_ai_type=2,
                         visible=True, tags=[])
    vomit = SimpleNamespace(
        type="illust", x_restrict=0, illust_ai_type=0, visible=True,
        tags=[SimpleNamespace(name="嘔吐", translated_name="vomiting")])
    r18g = SimpleNamespace(type="illust", x_restrict=2, illust_ai_type=0,
                           visible=True, tags=[])
    assert client._safe(r18) and client._safe(ai)
    assert not client._safe(vomit) and not client._safe(r18g)


def _art(**kw):
    row = dict(type="illust", x_restrict=0, illust_ai_type=0, visible=True,
               tags=[])
    row.update(kw)
    tags = [SimpleNamespace(name=n, translated_name="")
            for n in row.pop("tag_names", ())] + list(row.pop("tags"))
    return SimpleNamespace(tags=tags, **row)


def test_giant_and_fat_characters_are_never_taken():
    """Просьба пользователя: по такой работе спрашивают про шутку, не про тайтл."""
    client = PixivArtClient("token", api=FakePixivApi(),
                            exclude_r18=False, exclude_ai=False)
    assert not client._safe(_art(tag_names=["巨大娘"]))
    assert not client._safe(_art(tag_names=["giantess"]))
    assert not client._safe(_art(tag_names=["ぽっちゃり女子"]))
    assert not client._safe(_art(tag_names=["fat"]))
    # Обычная работа мимо этого списка проходит: «giant» внутри другого слова
    # ловиться не должен.
    assert client._safe(_art(tag_names=["gigantic robot", "オリジナル"]))


def test_only_r18_and_only_ai_modes_keep_just_those_works():
    only_r18 = PixivArtClient("token", api=FakePixivApi(), r18_mode="only")
    assert only_r18._safe(_art(x_restrict=1))
    assert not only_r18._safe(_art(x_restrict=0))
    assert not only_r18._safe(_art(x_restrict=2))     # R-18G — никогда
    only_ai = PixivArtClient("token", api=FakePixivApi(), ai_mode="only")
    assert only_ai._safe(_art(illust_ai_type=2))
    assert not only_ai._safe(_art(illust_ai_type=1))


def test_only_ai_mode_asks_pixiv_for_everything_and_filters_here():
    """Значения search_ai_type: 1 — СКРЫТЬ работы нейросети, 0 — показывать всё.

    Перепутанные местами, они ровно выключали режим «только ИИ»: Pixiv прятал
    все работы нейросети, и отбирать у себя было нечего."""
    class Recorder(FakePixivApi):
        def __init__(self):
            super().__init__()
            self.asked = []
            self.words = []

        def search_illust(self, word, **kwargs):
            self.asked.append(kwargs.get("search_ai_type"))
            self.words.append(word)
            return super().search_illust(word, **kwargs)

    api = Recorder()
    client = PixivArtClient("token", api=api, ai_mode="only")
    _data, _ext, url = client.fetch(make_anime(name="Death Note"))
    assert set(api.asked) == {0}
    # Сам режим уходит в запрос тегом: своего «только ИИ» у поиска нет.
    assert api.words[0].endswith(" " + pixiv_art_api.AI_TAG)
    assert url.endswith("ai.png")
    api = Recorder()
    PixivArtClient("token", api=api).fetch(make_anime(name="Death Note"))
    assert set(api.asked) == {1}
    assert not any(pixiv_art_api.AI_TAG in word for word in api.words)


def test_both_only_modes_ask_for_both_tags_at_once():
    """«Только R-18» и «только ИИ» вместе — обе метки уходят в один запрос.

    Запасные запросы идут от узкого к простому: если по связке не нашлось
    ничего, пробуем одну метку, потом голое название."""
    client = PixivArtClient("token", api=FakePixivApi(),
                            r18_mode="only", ai_mode="only")
    assert client._queries("Naruto") == [
        f"Naruto {pixiv_art_api.R18_TAG} {pixiv_art_api.AI_TAG}",
        f"Naruto {pixiv_art_api.R18_TAG}",
        "Naruto",
    ]
    only_ai = PixivArtClient("token", api=FakePixivApi(), ai_mode="only")
    assert only_ai._queries("Naruto") == [
        f"Naruto {pixiv_art_api.AI_TAG}", "Naruto"]


def test_old_settings_without_modes_still_mean_exclude():
    client = PixivArtClient("token", api=FakePixivApi())
    assert client.r18_mode == "exclude" and client.ai_mode == "exclude"
    assert client.exclude_r18 and client.exclude_ai
    allowed = PixivArtClient("token", api=FakePixivApi(),
                             exclude_r18=False, exclude_ai=False)
    assert allowed.r18_mode == "allow" and allowed.ai_mode == "allow"


def test_generator_builds_default_pixiv_client_after_rng_exists():
    settings = PackSettings(
        pct_songs=0, pack_pixiv_art=True, pct_pixiv_art=100,
        pixiv_refresh_token="refresh-secret")
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=object(), mal=object(), anilist=object(), kitsu=object(),
        themes=object(), tmdb=object())
    assert gen.pixiv.rng is gen.rng


def test_pixiv_art_uses_common_image_compression(tmp_path, monkeypatch):
    settings = PackSettings(
        pct_songs=0, pack_pixiv_art=True, pct_pixiv_art=100,
        pixiv_refresh_token="refresh-secret", compress_images=True,
        pixiv_gemini_check=False,
        out_dir=str(tmp_path))
    client = PixivArtClient("refresh-secret", api=FakePixivApi())
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=object(), mal=object(), tmdb=object(), pixiv=client)
    gen.prepare_dirs()
    monkeypatch.setattr(gen, "_poster_bytes", lambda *args: (b"", ""))
    saved = []
    monkeypatch.setattr(gen, "_to_avif", lambda data, name, ext:
                        saved.append((data, name, ext)) or True)
    cand = SongCandidate({}, make_anime(), kind=PIXIV_ART_KIND)
    assert gen._fetch_media(cand)
    assert cand.has_frame and cand.frame_name.endswith(".avif")
    assert saved and saved[0][2] == ".png"


# ── Поиск идёт по первому сезону франшизы ────────────────────────────────────
class RecordingPixivApi(FakePixivApi):
    """Запоминает, по каким словам искали, и отвечает только на первое из них."""

    def __init__(self, answers=("Kimetsu no Yaiba",)):
        super().__init__()
        self.words = []
        self.answers = set(answers)

    def search_illust(self, word, **kwargs):
        self.words.append(word)
        if word not in self.answers:
            return SimpleNamespace(illusts=[])
        return super().search_illust(word, **kwargs)


def _gen_with_pixiv(tmp_path, api):
    settings = PackSettings(
        pct_songs=0, pack_pixiv_art=True, pct_pixiv_art=100,
        pixiv_refresh_token="refresh-secret", pixiv_gemini_check=False,
        out_dir=str(tmp_path))
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=object(), mal=object(), tmdb=object(),
        pixiv=PixivArtClient("refresh-secret", api=api))
    gen.prepare_dirs()
    return gen


def test_art_is_searched_by_the_first_season_of_the_franchise(tmp_path, monkeypatch):
    """Тег на Pixiv висит на оригинале, а не на продолжении.

    Рисунок по «Магической битве 2» подписан названием первого сезона, и поиск
    по названию сиквела не находит ничего. Пак же берёт в кандидаты любой сезон:
    узнаваемость у него всё равно оригинала."""
    api = RecordingPixivApi()
    gen = _gen_with_pixiv(tmp_path, api)
    monkeypatch.setattr(gen, "_poster_bytes", lambda *args: (b"", ""))
    monkeypatch.setattr(gen, "_to_avif", lambda data, name, ext: True)
    first = make_anime(malId=100, name="Kimetsu no Yaiba", japanese="鬼滅の刃",
                       russian="Клинок, рассекающий демонов",
                       franchise="kimetsu_no_yaiba", airedOn={"year": 2019})
    sequel = make_anime(malId=200, name="Kimetsu no Yaiba: Yuukaku-hen",
                        japanese="鬼滅の刃 遊郭編",
                        russian="Клинок, рассекающий демонов 3",
                        franchise="kimetsu_no_yaiba", airedOn={"year": 2021})
    gen.db_cache.add_franchises({"kimetsu_no_yaiba": [sequel, first]})
    gen._card_cache[100] = first

    cand = SongCandidate({}, sequel, kind=PIXIV_ART_KIND)
    assert gen._fetch_media(cand)
    # Сначала все названия первого сезона, и только потом — сиквела.
    assert api.words[:2] == ["鬼滅の刃", "Kimetsu no Yaiba"]
    assert not any(w in api.words for w in ("鬼滅の刃 遊郭編",
                                            "Kimetsu no Yaiba: Yuukaku-hen"))


def test_the_titles_own_name_stays_a_fallback(tmp_path, monkeypatch):
    """Если по первому сезону ничего нет, ищем по названию самого тайтла."""
    api = RecordingPixivApi(answers=("Kimetsu no Yaiba: Yuukaku-hen",))
    gen = _gen_with_pixiv(tmp_path, api)
    monkeypatch.setattr(gen, "_poster_bytes", lambda *args: (b"", ""))
    monkeypatch.setattr(gen, "_to_avif", lambda data, name, ext: True)
    first = make_anime(malId=100, name="Kimetsu no Yaiba",
                       franchise="kimetsu_no_yaiba", airedOn={"year": 2019})
    sequel = make_anime(malId=200, name="Kimetsu no Yaiba: Yuukaku-hen",
                        franchise="kimetsu_no_yaiba", airedOn={"year": 2021})
    gen.db_cache.add_franchises({"kimetsu_no_yaiba": [sequel, first]})
    gen._card_cache[100] = first
    assert gen._fetch_media(SongCandidate({}, sequel, kind=PIXIV_ART_KIND))
    assert "Kimetsu no Yaiba: Yuukaku-hen" in api.words


def test_a_first_season_is_searched_by_itself(tmp_path):
    """У самого первого сезона искать больше нечего — карточка та же."""
    gen = _gen_with_pixiv(tmp_path, FakePixivApi())
    first = make_anime(malId=100, name="Kimetsu no Yaiba",
                       franchise="kimetsu_no_yaiba", airedOn={"year": 2019})
    gen.db_cache.add_franchises({"kimetsu_no_yaiba": [first]})
    assert gen._first_season_card(first) is first
    # Одиночный тайтл без франшизы не стоит ни одного запроса.
    assert gen._first_season_card(make_anime(franchise="")) is not None


def test_pixiv_controls_and_secret_roundtrip(qapp):
    main = _FakeMain(pixiv="refresh-secret")
    tab = animepack_tab.AnimePackTab(main_window=main)
    try:
        tab.chk_pixiv_art.setChecked(True)
        tab.chk_pixiv_gemini.setChecked(False)
        tab.chk_songs.setChecked(False)
        tab.mix.set_shares({"pixiv_art": 100})
        settings = tab.collect()
        assert settings.only_kind == PIXIV_ART_KIND
        assert settings.pixiv_refresh_token == "refresh-secret"
        assert not settings.validate()
        tab.cb_pixiv_r18.setCurrentIndex(tab.cb_pixiv_r18.findData("only"))
        tab.cb_pixiv_ai.setCurrentIndex(tab.cb_pixiv_ai.findData("allow"))
        data = tab.get_settings()
        assert "pixiv_refresh_token" not in data
        tab.apply_settings(data)
        assert tab.cb_pixiv_r18.currentData() == "only"
        assert tab.cb_pixiv_ai.currentData() == "allow"
        # Старые галочки пишутся рядом — прежние сборки читают только их.
        assert data["pixiv_exclude_r18"] is False
        assert "Артов Pixiv" in tab.lbl_left.text()
    finally:
        tab.cleanup()


def test_the_likes_bar_is_a_tab_setting(qapp):
    """Планка лайков задаётся на вкладке и доезжает до самого клиента."""
    import random
    tab = animepack_tab.AnimePackTab(main_window=_FakeMain(pixiv="secret"))
    try:
        tab.chk_pixiv_art.setChecked(True)
        tab.chk_songs.setChecked(False)
        tab.mix.set_shares({"pixiv_art": 100})
        assert tab.sp_pixiv_likes.value() == pixiv_art_api.MIN_BOOKMARKS == 15
        assert tab.collect().pixiv_min_likes == 15
        tab.sp_pixiv_likes.setValue(120)
        data = tab.get_settings()
        assert data["pixiv_min_likes"] == 120
        tab.sp_pixiv_likes.setValue(15)
        tab.apply_settings(data)
        assert tab.sp_pixiv_likes.value() == 120
        gen = SimpleNamespace(s=tab.collect(), stopped=lambda: False,
                              rng=random.Random(0), log=lambda msg: None)
        from si_hyx_parts.animepack.pixiv_art_generation import (
            init_pixiv_service)
        init_pixiv_service(gen)
        assert gen.pixiv.min_likes == 120
    finally:
        tab.cleanup()


# ── Узкие режимы: «только R-18», «только ИИ» ─────────────────────────────────
class PagedPixivApi:
    """Отдаёт разные страницы поиска; подходящая работа лежит на второй."""

    def __init__(self):
        self.offsets = []
        self.downloaded = []

    def auth(self, refresh_token):
        pass

    @staticmethod
    def _row(name, **kw):
        row = dict(type="illust", x_restrict=0, illust_ai_type=0, visible=True,
                   total_bookmarks=300, width=1200, height=1200, page_count=1,
                   tags=[],
                   image_urls=SimpleNamespace(
                       original=f"https://i.pximg.net/{name}.png"),
                   meta_pages=[])
        row.update(kw)
        return SimpleNamespace(**row)

    def search_illust(self, word, **kwargs):
        offset = int(kwargs.get("offset") or 0)
        self.offsets.append(offset)
        if offset == 0:
            # Целая страница годных работ: столько и нужно пулу выбора.
            return SimpleNamespace(
                illusts=[self._row(f"plain{n}")
                         for n in range(pixiv_art_api.MIN_CHOICES)])
        if offset == 30:
            return SimpleNamespace(illusts=[self._row("ai", illust_ai_type=2)])
        return SimpleNamespace(illusts=[])

    def download(self, url, fname, referer):
        self.downloaded.append(url)
        fname.write(_png())
        return True


def test_narrow_modes_page_through_the_search():
    """«Только ИИ» отбирает одну работу из сотни — первой страницы ей мало.

    Раньше поиск смотрел ровно 30 работ и сдавался с «подходящих артов по тегу
    не найдено»; из-за этого пак из одних R-18-ИИ-артов не набирался вовсе."""
    api = PagedPixivApi()
    client = PixivArtClient("token", api=api, ai_mode="only")
    _data, _ext, url = client.fetch(make_anime(name="Death Note"))
    assert url.endswith("ai.png")
    assert api.offsets[:2] == [0, 30]


def test_a_full_pool_on_the_first_page_costs_a_single_request():
    """Набрался пул выбора — вглубь ходить незачем.

    Раньше поиск останавливался на ПЕРВОЙ же годной работе, пул выбора
    состоял из неё одной, и «случайный» арт по тайтлу был всегда один и тот
    же (просьба пользователя)."""
    api = PagedPixivApi()
    PixivArtClient("token", api=api).fetch(make_anime(name="Death Note"))
    assert api.offsets == [0]


def test_the_answer_is_the_title_whose_tag_matched(tmp_path, monkeypatch):
    """Арт подписан названием первого сезона — его и надо спрашивать.

    Раньше в ответе оставался сиквел: картинка была по «Клинку», а ответ — по
    «Клинку 3», и вопрос не сходился сам с собой (просьба пользователя)."""
    api = RecordingPixivApi()
    gen = _gen_with_pixiv(tmp_path, api)
    monkeypatch.setattr(gen, "_poster_bytes", lambda *args: (b"", ""))
    monkeypatch.setattr(gen, "_to_avif", lambda data, name, ext: True)
    first = make_anime(malId=100, name="Kimetsu no Yaiba", japanese="鬼滅の刃",
                       russian="Клинок, рассекающий демонов",
                       franchise="kimetsu_no_yaiba", airedOn={"year": 2019})
    sequel = make_anime(malId=200, name="Kimetsu no Yaiba: Yuukaku-hen",
                        russian="Клинок, рассекающий демонов 3",
                        franchise="kimetsu_no_yaiba", airedOn={"year": 2021})
    gen.db_cache.add_franchises({"kimetsu_no_yaiba": [sequel, first]})
    gen._card_cache[100] = first
    cand = SongCandidate({}, sequel, kind=PIXIV_ART_KIND)
    assert gen._fetch_media(cand)
    assert cand.title_ru == "Клинок, рассекающий демонов"
    assert cand.mal_id == 100


def test_a_fallback_match_keeps_the_titles_own_answer(tmp_path, monkeypatch):
    """По первому сезону не нашлось, нашлось по своему названию — ответ свой."""
    api = RecordingPixivApi(answers=("Kimetsu no Yaiba: Yuukaku-hen",))
    gen = _gen_with_pixiv(tmp_path, api)
    monkeypatch.setattr(gen, "_poster_bytes", lambda *args: (b"", ""))
    monkeypatch.setattr(gen, "_to_avif", lambda data, name, ext: True)
    first = make_anime(malId=100, name="Kimetsu no Yaiba",
                       russian="Клинок, рассекающий демонов",
                       franchise="kimetsu_no_yaiba", airedOn={"year": 2019})
    sequel = make_anime(malId=200, name="Kimetsu no Yaiba: Yuukaku-hen",
                        russian="Клинок, рассекающий демонов 3",
                        franchise="kimetsu_no_yaiba", airedOn={"year": 2021})
    gen.db_cache.add_franchises({"kimetsu_no_yaiba": [sequel, first]})
    gen._card_cache[100] = first
    cand = SongCandidate({}, sequel, kind=PIXIV_ART_KIND)
    assert gen._fetch_media(cand)
    assert cand.title_ru == "Клинок, рассекающий демонов 3"


# ── R-18 спрашивается прямо в запросе ────────────────────────────────────────
class TagAwarePixivApi(FakePixivApi):
    """Отдаёт взрослые работы только тому запросу, где есть тег R-18."""

    def __init__(self, answer_plain=True):
        super().__init__()
        self.words = []
        self.answer_plain = answer_plain

    def search_illust(self, word, **kwargs):
        self.words.append(word)
        row = SimpleNamespace(
            type="illust", visible=True, tags=[], total_bookmarks=300,
            width=1200, height=1200, page_count=1, meta_pages=[],
            x_restrict=1 if "R-18" in word else 0, illust_ai_type=0,
            image_urls=SimpleNamespace(
                original="https://i.pximg.net/r18.png" if "R-18" in word
                else "https://i.pximg.net/safe.png"))
        if "R-18" not in word and not self.answer_plain:
            return SimpleNamespace(illusts=[])
        return SimpleNamespace(illusts=[row])


def test_only_r18_asks_pixiv_for_the_tag_itself():
    """Просьба пользователя: R-18 должен уходить в сам поиск, а не отбираться
    из общей выдачи по одной работе из сотни."""
    api = TagAwarePixivApi()
    client = PixivArtClient("token", api=api, r18_mode="only")
    _data, _ext, url = client.fetch(make_anime(name="Death Note", japanese=""))
    assert api.words[0] == "Death Note R-18"
    assert url.endswith("r18.png")


def test_a_plain_query_stays_the_fallback():
    """Связка тегов не нашла ничего — ищем по одному названию."""
    api = TagAwarePixivApi()
    client = PixivArtClient("token", api=api, r18_mode="allow")
    client.fetch(make_anime(name="Death Note", japanese=""))
    # Без «только их» тег не нужен ни одному из запросов.
    assert set(api.words) == {"Death Note"}


def test_no_adult_works_at_all_points_at_the_pixiv_account():
    """Ни одной работы R-18 — почти всегда дело в настройках аккаунта Pixiv."""
    api = TagAwarePixivApi(answer_plain=True)

    def only_safe(word, **kwargs):
        if "R-18" in word:
            return SimpleNamespace(illusts=[])
        api.words.append(word)
        return SimpleNamespace(illusts=[SimpleNamespace(
            type="illust", visible=True, tags=[], x_restrict=0,
            illust_ai_type=0, total_bookmarks=300, width=1200, height=1200,
            page_count=1, meta_pages=[],
            image_urls=SimpleNamespace(
                original="https://i.pximg.net/safe.png"))])

    api.search_illust = only_safe
    client = PixivArtClient("token", api=api, r18_mode="only")
    try:
        client.fetch(make_anime(name="Death Note", japanese=""))
    except Exception:
        pass
    note = client.summary()
    assert "показ R-18" in note and "аккаунта Pixiv" in note


def test_the_log_names_the_title_that_was_actually_searched(tmp_path, monkeypatch):
    """В журнале стояло название КАНДИДАТА, хотя искали по первому сезону."""
    from si_hyx_parts.animepack.pixiv_art_generation import _searched_title

    first = make_anime(malId=100, russian="Моя геройская академия")
    cand = SongCandidate({}, make_anime(
        malId=200, russian="Моя геройская академия: Битва героев «Юэй»"),
        kind=PIXIV_ART_KIND)
    note = _searched_title(first, cand)
    assert note.startswith("Моя геройская академия (первый сезон для")
    # У самого первого сезона приписки нет.
    assert _searched_title(first, SongCandidate({}, first,
                                                kind=PIXIV_ART_KIND)) == \
        "Моя геройская академия"
