# -*- coding: utf-8 -*-
"""Страницы MangaDex и сакуга внутри генератора и вкладки."""
import io
import os
import random
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

import animepack
import animepack_tab
from animepack import (MANGA_KIND, SAKUGA_KIND, PackSettings,
                       SongCandidate)
from test_animepack_new_kinds import make_anime as _make_anime
from test_animepack_tab_mix import _FakeMain


def make_anime(**kwargs):
    return _make_anime(**{"related": [], **kwargs})


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (600, 900), "white").save(buf, "PNG")
    return buf.getvalue()


class FakeMangaDex:
    def __init__(self, url="https://cdn.md/data/abc/p3.png"):
        self.url = url
        self.asked = []
        # Глава, из которой взят разворот: её адрес уходит в ответ вопроса.
        self.last_chapter = ""

    def panel_url(self, card, excluded=()):
        self.asked.append((card.get("malId"), set(excluded)))
        self.last_chapter = "ch-42" if self.url else ""
        return self.url


class FakeSakuga:
    def __init__(self, clip=None):
        self.clip_row = clip if clip is not None else {
            "id": "251547", "url": "https://sb/cut.mp4", "ext": "mp4",
            "size": 3_000_000, "source": "#26"}

    def clip(self, card, excluded=()):
        return dict(self.clip_row) if self.clip_row else {}


@pytest.fixture
def generator(tmp_path, monkeypatch):
    monkeypatch.setattr(animepack, "CONFIG_DIR", str(tmp_path))
    settings = PackSettings(
        pct_songs=0, rounds=1, themes=1, questions=3, compress_images=False,
        level_min=0, level_max=100, mark_owners=False, parallel=1,
        pack_manga=True, pct_manga=50, pack_sakuga=True, pct_sakuga=50,
        manga_character_crop=False)
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=object(), mal=object(), tmdb=object(),
        mangadex=FakeMangaDex(), sakuga=FakeSakuga(),
        rng=random.Random(5))
    monkeypatch.setattr(gen, "_poster_bytes", lambda *a: (_png(), ".png"))
    monkeypatch.setattr(gen, "_get_bytes", lambda url, **kw: _png())
    gen.prepare_dirs()
    yield gen
    gen.cleanup()


# ── Манга: страница вместо обложки и персонажа ───────────────────────────────
def test_manga_question_is_a_mangadex_page_not_the_cover(generator):
    gen = generator
    cand = SongCandidate({}, make_anime(malId=656, name="Vagabond"),
                         kind=MANGA_KIND, media="manga")
    assert gen._fetch_media(cand) is True
    assert cand.has_frame and cand.frame_url.endswith("p3.png")
    # Постер в ответе остался, но картинкой ВОПРОСА он больше не служит.
    assert cand.has_poster and cand.frame_file != cand.poster_file
    assert not cand.character and not cand.is_character


def test_manga_page_is_not_shown_twice_in_one_run(generator):
    gen = generator
    first = SongCandidate({}, make_anime(malId=656), kind=MANGA_KIND, media="manga")
    gen._fetch_media(first)
    second = SongCandidate({}, make_anime(malId=657), kind=MANGA_KIND, media="manga")
    gen._fetch_media(second)
    assert gen.mangadex.asked[1][1]                # второй раз уже с чёрным списком
    assert animepack.frame_url_key(first.frame_url) in gen.mangadex.asked[1][1]


def test_manga_without_pages_gives_up_and_frees_its_slots(generator):
    gen = generator
    gen.mangadex = FakeMangaDex(url="")
    from si_hyx_parts.animepack.manga_panel import MISS_GIVE_UP
    for i in range(MISS_GIVE_UP):
        cand = SongCandidate({}, make_anime(malId=1000 + i), kind=MANGA_KIND,
                             media="manga")
        assert gen._fetch_media(cand) is False
    assert gen._dead_kinds == {MANGA_KIND}


def test_known_reader_catalog_survives_eight_missing_titles(generator):
    gen = generator
    gen.mangadex = FakeMangaDex(url="")
    gen._manga_catalog_matches = 100
    from si_hyx_parts.animepack.manga_panel import (
        MISS_GIVE_UP, KNOWN_CATALOG_MISS_LIMIT)
    for i in range(KNOWN_CATALOG_MISS_LIMIT):
        cand = SongCandidate({}, make_anime(malId=2000 + i), kind=MANGA_KIND,
                             media="manga")
        assert gen._fetch_media(cand) is False
        if i < MISS_GIVE_UP:
            assert MANGA_KIND not in gen._dead_kinds
    assert gen._dead_kinds == {MANGA_KIND}


def test_unavailable_image_is_not_reported_as_failed_title_check(generator, monkeypatch):
    gen = generator
    gen.s.manga_gemini_check = False
    messages = []
    gen._log_rare = lambda category, message: messages.append((category, message))

    def unavailable(*args, **kwargs):
        raise animepack.AnimePackApiError("HTTP 403")

    monkeypatch.setattr(gen, "_get_bytes", unavailable)
    cand = SongCandidate({}, make_anime(malId=656), kind=MANGA_KIND, media="manga")
    assert gen.download_manga_panel(cand) is False
    assert messages[-1][0] == "Страница манги недоступна"
    assert not any(category == "Страница манги отклонена проверкой"
                   for category, _ in messages)


# ── Сакуга ───────────────────────────────────────────────────────────────────
def _fake_ffmpeg(gen, monkeypatch, ok=True):
    seen = {}

    def run(cmd, timeout=0):
        seen["cmd"] = list(cmd)
        if ok:
            with open(cmd[-1], "wb") as f:
                f.write(b"0" * (animepack.MIN_VIDEO_BYTES + 1))
        return (0 if ok else 1), ""

    def get_bytes(url, timeout=None):
        seen["url"] = url
        return b"clip"

    monkeypatch.setattr(gen, "_run_killable", run)
    monkeypatch.setattr(gen, "_get_bytes", get_bytes)
    return seen


def test_sakuga_question_is_a_silent_clip(generator, monkeypatch):
    gen = generator
    seen = _fake_ffmpeg(gen, monkeypatch)
    cand = SongCandidate({}, make_anime(), kind=SAKUGA_KIND)
    assert gen._fetch_media(cand) is True
    assert cand.is_sakuga and cand.is_silent and cand.has_video
    assert not cand.is_picture and not cand.has_frame
    # Звука у вопроса нет вовсе: голоса выдали бы тайтл мимо анимации.
    assert "-an" in seen["cmd"]
    # Вырезка сначала скачивается, а кодируется уже локальный файл: ffmpeg
    # не держит сетевой замок всё время кодирования.
    assert seen["url"] == "https://sb/cut.mp4"
    source = seen["cmd"][seen["cmd"].index("-i") + 1]
    assert not source.startswith("http") and not os.path.exists(source)
    assert seen["cmd"][seen["cmd"].index("-t") + 1] == str(gen.s.sakuga_cut)
    assert os.path.exists(os.path.join(gen.folder, "Video", cand.video_out))


def test_sakuga_encodes_with_its_own_preset(generator, monkeypatch):
    """Скорость кодирования у вырезки своя, отдельно от вопросов-роликов."""
    gen = generator
    gen.s.video_preset = 3
    gen.s.sakuga_preset = 11
    seen = _fake_ffmpeg(gen, monkeypatch)
    cand = SongCandidate({}, make_anime(), kind=SAKUGA_KIND)
    assert gen._fetch_media(cand) is True
    assert seen["cmd"][seen["cmd"].index("-preset") + 1] == "11"
    # А у ролика остаётся его собственный.
    assert gen.video_encode_args()[
        gen.video_encode_args().index("-preset") + 1] == "3"


def test_sakuga_without_a_clip_gives_up_after_a_while(generator):
    gen = generator
    gen.sakuga = FakeSakuga(clip={})
    from si_hyx_parts.animepack.sakuga_generation import MISS_GIVE_UP
    for i in range(MISS_GIVE_UP):
        cand = SongCandidate({}, make_anime(malId=3000 + i), kind=SAKUGA_KIND)
        assert gen._fetch_media(cand) is False
    assert gen._dead_kinds == {SAKUGA_KIND}


def test_found_sakuga_resets_misses_before_slow_encoding(generator, monkeypatch):
    """Найденный клип прерывает серию промахов ещё до очереди ffmpeg."""
    from si_hyx_parts.animepack import sakuga_generation as generation

    gen = generator
    gen._sakuga_misses = generation.MISS_GIVE_UP - 1
    monkeypatch.setattr(generation, "_encode", lambda *_: False)
    cand = SongCandidate({}, make_anime(), kind=SAKUGA_KIND)

    assert gen.download_sakuga(cand) is False
    assert gen._sakuga_misses == 0
    assert SAKUGA_KIND not in gen._dead_kinds


def test_empty_ffmpeg_output_is_not_a_question(generator, monkeypatch):
    gen = generator
    _fake_ffmpeg(gen, monkeypatch, ok=False)
    monkeypatch.setattr(animepack.time, "sleep", lambda *_: None)
    cand = SongCandidate({}, make_anime(), kind=SAKUGA_KIND)
    assert gen._fetch_media(cand) is False
    assert not cand.has_video


# ── Сборка content.xml ───────────────────────────────────────────────────────
def _question(cand, settings=None):
    s = settings or PackSettings()
    root = ET.fromstring(animepack.build_content_xml([cand], s))
    return root.find(".//{*}question")


def test_sakuga_question_is_a_video_without_a_timer():
    """Таймера у сакуги нет вовсе: duration не пишется (просьба пользователя)."""
    settings = PackSettings(sakuga_cut=6)
    cand = SongCandidate({}, make_anime(), kind=SAKUGA_KIND, has_video=True)
    items = _question(cand, settings).findall(
        "./{*}params/{*}param[@name='question']/{*}item")
    assert len(items) == 1 and items[0].get("type") == "video"
    assert items[0].text == cand.video_out
    assert items[0].get("duration") is None


def test_manga_page_question_has_no_task_text():
    cand = SongCandidate({}, make_anime(), kind=MANGA_KIND, media="manga",
                         has_frame=True, frame_name="panel.png")
    items = _question(cand).findall(
        "./{*}params/{*}param[@name='question']/{*}item")
    assert len(items) == 1 and items[0].text == "panel.png"


# ── AniZip рядом с AniList и Kitsu ───────────────────────────────────────────
def test_anizip_frames_join_the_common_pool(generator):
    gen = generator
    gen.anilist = type("A", (), {"frames": staticmethod(lambda mal: ["https://ani/1.jpg"])})()
    gen.kitsu = type("K", (), {"frames": staticmethod(lambda mal: ["https://kitsu/1.jpg"])})()
    gen.anizip = type("Z", (), {"frames": staticmethod(
        lambda mal: ["https://tvdb/7.jpg", "https://ani/1.jpg"])})()
    urls = gen._frame_urls(make_anime(screenshots=[
        {"originalUrl": "https://shiki/0.jpg"}]))
    assert "https://tvdb/7.jpg" in urls
    # Дубль с общего CDN не задваивается.
    assert urls.count("https://ani/1.jpg") == 1


# ── Вкладка ──────────────────────────────────────────────────────────────────
def test_tab_collects_and_restores_the_new_categories(qapp, monkeypatch):
    tab = animepack_tab.AnimePackTab()
    fresh = animepack_tab.AnimePackTab()
    # Обе вкладки закрываем: у брошенной остаётся заведённый таймер жанров, и
    # запрос уходит уже посреди СОСЕДНЕГО теста (полный прогон падал на
    # «закрытая вкладка не идёт за жанрами»).
    try:
        _check_new_category_controls(tab, fresh)
    finally:
        tab.cleanup()
        fresh.cleanup()


def _check_new_category_controls(tab, fresh):
    tab.main = _FakeMain()
    tab.chk_sakuga.setChecked(True)
    tab.chk_manga.setChecked(True)
    tab.sp_sakuga_cut.setValue(11)
    tab.chk_sakuga_safe.setChecked(False)
    tab.sp_sakuga_preset.setValue(6)
    tab.sp_manga_level_avg.setValue(7)
    tab.sp_art_level_avg.setValue(3)
    tab.cb_manga_lang.setCurrentIndex(tab.cb_manga_lang.findData("ru"))
    tab.chk_manga_erotica.setChecked(True)
    s = tab.collect()
    assert s.pack_sakuga and s.pack_manga
    assert s.sakuga_cut == 11 and s.sakuga_safe_only is False
    assert s.sakuga_preset == 6
    assert s.manga_level_avg == 7 and s.art_level_avg == 3
    assert s.manga_lang == "ru" and s.manga_allow_erotica is True
    assert s.mix_shares[SAKUGA_KIND]
    saved = tab.get_settings()
    fresh.main = tab.main
    fresh.apply_settings(saved)
    assert fresh.chk_sakuga.isChecked()
    assert fresh.sp_sakuga_cut.value() == 11
    assert fresh.sp_sakuga_preset.value() == 6
    assert fresh.sp_manga_level_avg.value() == 7
    assert fresh.sp_art_level_avg.value() == 3
    assert fresh.cb_manga_lang.currentData() == "ru"
    assert fresh.chk_manga_erotica.isChecked()


# ── Манга ищется по карточке МАНГИ, а не одноимённого аниме ──────────────────
class RecordingMangaDex(FakeMangaDex):
    def __init__(self):
        super().__init__()
        self.cards = []

    def panel_url(self, card, excluded=()):
        self.cards.append(card)
        return super().panel_url(card, excluded)


class FakeShiki:
    """Каталоги аниме и манги, где ОДИН и тот же MAL id — разные вещи.

    На MAL нумерация аниме и манги своя, и id 656 занят и там и там."""

    def random_animes(self, page=1, **kw):
        if page > 1:
            return []
        return [make_anime(malId=656, name="Vagabond (anime)",
                           english="Vagabond TV", japanese="バガボンド (アニメ)")]

    def random_mangas(self, page=1, **kw):
        if page > 1:
            return []
        return [make_anime(malId=656, name="Vagabond", english="Vagabond",
                           japanese="バガボンド", kind="manga")]

    def franchise_parts(self, keys):
        return {}


def test_mangadex_is_asked_with_the_manga_card_not_the_anime_one(
        tmp_path, monkeypatch):
    monkeypatch.setattr(animepack, "CONFIG_DIR", str(tmp_path))
    settings = PackSettings(pct_songs=0, rounds=1, themes=1, questions=2,
                            level_min=0, level_max=100, compress_images=False,
                            random_mode=True, pack_manga=True, pct_manga=100,
                            manga_character_crop=False)
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=FakeShiki(), mal=object(), tmdb=object(),
        mangadex=RecordingMangaDex(), rng=random.Random(5))
    monkeypatch.setattr(gen, "_poster_bytes", lambda *a: (_png(), ".png"))
    monkeypatch.setattr(gen, "_get_bytes", lambda url, **kw: _png())
    gen.prepare_dirs()
    try:
        cands = list(gen._iter_manga_candidates())
        assert [c.anime["name"] for c in cands] == ["Vagabond"]
        assert cands[0].is_manga
        assert gen._fetch_media(cands[0]) is True
    finally:
        gen.cleanup()
    asked = gen.mangadex.cards[0]
    assert asked["name"] == "Vagabond" and asked["kind"] == "manga"
    assert asked["japanese"] == "バガボンド"
    # Каталоги аниме и манги живут в разных кэшах: карточка аниме с тем же MAL
    # id не должна подменять книгу.
    assert 656 not in gen._card_cache
