# -*- coding: utf-8 -*-
"""Страница манги с названием тайтла отклоняется Gemini — берётся другая."""
import base64
import io

from PIL import Image

import animepack
from animepack import MANGA_KIND, PackSettings, SongCandidate
from si_hyx_parts.animepack.manga_visual_check import check, titles
from test_animepack_manga_sakuga import generator, make_anime  # noqa: F401
from test_animepack_pixiv_gemini import _Cache


def _png(size=(600, 900)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


class _Gemini:
    model = "gemini-test"

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = []

    def generate_json(self, prompt, schema, temperature=0):
        self.calls.append(prompt)
        verdict = self.verdicts.pop(0)
        if isinstance(verdict, Exception):
            raise verdict
        return verdict


def _verdict(ok):
    return {"accept": ok, "has_title_text": not ok,
            "reason": "" if ok else "титул главы"}


class _Gen:
    def __init__(self, verdicts):
        self.gemini_manga = _Gemini(verdicts)
        self.db_cache = _Cache()


class _Cand:
    anime = {"russian": "Бродяга", "name": "Vagabond",
             "english": "Vagabond", "japanese": ["バガボンド"],
             "synonyms": ["Vagabond (manga)"]}


def test_prompt_names_every_title_and_carries_the_page():
    gen = _Gen([_verdict(True)])
    data = _png()
    ok, _ = check(gen, _Cand(), data, ".png")
    assert ok
    text, image = gen.gemini_manga.calls[0]
    for name in ("Бродяга", "Vagabond", "バガボンド", "Vagabond (manga)"):
        assert name in text["text"]
    assert image == {"type": "image", "mime_type": "image/png",
                     "data": base64.b64encode(data).decode("ascii")}
    assert titles(_Cand.anime).count("Vagabond") == 1


def test_big_page_is_sent_shrunk_and_the_verdict_is_cached():
    gen = _Gen([_verdict(False)])
    data = _png((1200, 6000))
    assert check(gen, _Cand(), data, ".png")[0] is False
    assert check(gen, _Cand(), data, ".png")[0] is False
    assert len(gen.gemini_manga.calls) == 1
    image = gen.gemini_manga.calls[0][1]
    assert image["mime_type"] == "image/jpeg"
    sent = Image.open(io.BytesIO(base64.b64decode(image["data"])))
    assert max(sent.size) <= 1600


def _pages(gen):
    urls = iter(f"https://cdn.md/data/abc/p{i}.png" for i in range(10))
    fake = gen.mangadex

    def panel_url(card, excluded=()):
        fake.asked.append((card.get("malId"), set(excluded)))
        fake.last_chapter = "ch-42"
        return next(urls)

    fake.panel_url = panel_url

    def page(url, **kw):
        # Разные страницы — разные байты: вердикт кешируется по содержимому.
        buf = io.BytesIO()
        Image.new("RGB", (600, 900), (int(url[-5]) * 20, 0, 0)).save(buf, "PNG")
        return buf.getvalue()

    gen._get_bytes = page
    return fake


def test_page_with_the_title_is_replaced_by_another_page(generator):
    gen = generator
    fake = _pages(gen)
    gen.gemini_manga = _Gemini([_verdict(False), _verdict(True)])
    cand = SongCandidate({}, make_anime(malId=656, name="Vagabond"),
                         kind=MANGA_KIND, media="manga")
    assert gen._fetch_media(cand) is True
    assert cand.frame_url.endswith("p1.png")
    # Отклонённая страница больше не предлагается.
    assert animepack.frame_url_key("https://cdn.md/data/abc/p0.png") in fake.asked[1][1]
    assert len(gen.gemini_manga.calls) == 2


def test_ordinary_page_still_checks_title_when_scene_crop_is_enabled(generator):
    gen = generator
    gen.s.manga_character_crop = True
    _pages(gen)
    gen.gemini_manga = _Gemini([_verdict(False), _verdict(True)])
    cand = SongCandidate({}, make_anime(malId=656), kind=MANGA_KIND, media="manga")
    assert gen._fetch_media(cand)
    assert cand.frame_url.endswith("p1.png")
    assert len(gen.gemini_manga.calls) == 2
    with Image.open(gen.folder + "/Images/" + cand.frame_name) as picture:
        assert picture.size == (600, 900)


def test_title_on_every_page_gives_the_slot_to_the_next_title(generator):
    from si_hyx_parts.animepack.manga_panel import VISUAL_TRIES
    gen = generator
    _pages(gen)
    gen.gemini_manga = _Gemini([_verdict(False)] * VISUAL_TRIES)
    cand = SongCandidate({}, make_anime(malId=656), kind=MANGA_KIND, media="manga")
    assert gen._fetch_media(cand) is False
    assert MANGA_KIND not in gen._dead_kinds


def test_exhausted_quota_turns_the_check_off_not_the_manga(generator):
    from gemini_api import GeminiQuotaError
    gen = generator
    _pages(gen)
    gen.gemini_manga = _Gemini([GeminiQuotaError("лимит")])
    cand = SongCandidate({}, make_anime(malId=656), kind=MANGA_KIND, media="manga")
    assert gen._fetch_media(cand) is True
    assert gen.gemini_manga is None
    assert MANGA_KIND not in gen._dead_kinds


def test_silent_server_turns_the_check_off_not_the_manga(generator):
    # Gemini перегружен (503/таймауты подряд) — ждать его на каждой странице
    # значит держать рабочие потоки минутами; страницы идут без проверки.
    from gemini_api import GeminiDownError
    gen = generator
    _pages(gen)
    gen.gemini_manga = _Gemini([GeminiDownError("2 запроса подряд без ответа")])
    cand = SongCandidate({}, make_anime(malId=656), kind=MANGA_KIND, media="manga")
    assert gen._fetch_media(cand) is True
    assert gen.gemini_manga is None
    assert MANGA_KIND not in gen._dead_kinds


def test_settings_need_a_gemini_key_only_when_the_check_is_on():
    base = dict(pct_songs=0, pack_manga=True, pct_manga=100)
    on = PackSettings(**base)
    assert any("страниц манги" in p for p in on.validate())
    off = PackSettings(**base, manga_gemini_check=False, manga_character_crop=False)
    assert not any("страниц манги" in p for p in off.validate())
    keyed = PackSettings(**base, gemini_key="key")
    assert not any("страниц манги" in p for p in keyed.validate())


def test_tab_keeps_the_manga_check_and_its_model(qapp):
    from animepack_tab import AnimePackTab
    tab = AnimePackTab()
    try:
        assert tab.collect().manga_gemini_check is True     # как у Pixiv
        tab.chk_manga_gemini.setChecked(False)
        assert tab.cb_manga_gemini_model.isEnabled()  # выбор сцены тоже требует модель
        tab.chk_manga_character_crop.setChecked(False)
        assert not tab.cb_manga_gemini_model.isEnabled()
        box = tab.cb_manga_gemini_model
        other = [box.itemText(i) for i in range(box.count())
                 if box.itemText(i) != box.currentText()][0]
        box.setCurrentText(other)
        saved = tab.get_settings()
        tab.apply_settings(PackSettings().to_dict())
        assert tab.chk_manga_gemini.isChecked()
        tab.apply_settings(saved)
        got = tab.collect()
        assert got.manga_gemini_check is False
        assert got.manga_character_crop is False
        assert got.manga_gemini_model == other
    finally:
        tab.cleanup()
