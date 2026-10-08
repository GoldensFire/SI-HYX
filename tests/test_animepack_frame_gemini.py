"""Frame verdicts, replacement, effect integration and the +2 price bonus."""
import base64
import io
from pathlib import Path
import random
from types import SimpleNamespace

from PIL import Image
import pytest

import animepack as api
import animepack_tab
from gemini_api import GeminiError, GeminiQuotaError
from si_hyx_parts.animepack import frame_visual_check as frames
from test_animepack_manga_gemini import _Gemini
from test_animepack_new_kinds import make_anime
from test_animepack_pixiv_gemini import _Cache
from test_animepack_tab_mix import _FakeMain


def png(color):
    output = io.BytesIO()
    Image.new("RGB", (60, 40), color).save(output, "PNG")
    return output.getvalue()


def verdict(title=False, characters=True):
    return {"accept": not title, "has_title_text": title,
            "has_characters": characters, "reason": "название" if title else "чисто"}


def candidate(kind=api.FRAME_KIND):
    return api.SongCandidate({}, make_anime(), kind=kind)


class Generator:
    def __init__(self, tmp_path, verdicts, **settings):
        self.s = api.PackSettings(frame_gemini_check=True, pixel_gemini_check=True,
                                  frame_effect="zoom", **settings)
        self.gemini_frames = _Gemini(verdicts)
        self.db_cache = _Cache()
        self.rng = random.Random(1)
        self.folder = str(tmp_path)
        self.urls = ["https://frames/one.png", "https://frames/two.png"]
        self.data = {self.urls[0]: png("white"), self.urls[1]: png("blue")}
        self.saved, self.encoded, self.dead = [], [], []
        for name in ("Images", "Video"):
            (tmp_path / name).mkdir(exist_ok=True)

    def stopped(self):
        return False

    def _pick_frame_url(self, cand):
        return self.urls.pop(0) if self.urls else ""

    def _cached_bytes(self, url, category):
        return self.data[url]

    def _url_ext(self, url):
        return ".png"

    def _poster_bytes(self, *args):
        return b"", ""

    def _save_reusable_image(self, data, name, ext, reuse=True):
        self.saved.append(data)
        return name + ext

    def encode_reveal(self, raw, final, *args):
        self.encoded.append(Path(raw).read_bytes())
        Path(final).write_bytes(b"video")
        return 0, ""

    def log(self, *args):
        pass

    _log_rare = log

    def _drop_kind(self, kind):
        self.dead.append(kind)


@pytest.mark.parametrize("kind", api.FRAME_KINDS)
def test_title_frame_is_replaced_before_saving_or_rendering(tmp_path, kind):
    gen = Generator(tmp_path, [verdict(title=True), verdict(characters=False)])
    cand = candidate(kind)
    if cand.is_pixel:
        assert api.AnimePackGenerator.download_pixel(gen, cand)
        assert cand.has_video and cand.frame_effect == "zoom"
        assert gen.encoded == [gen.data["https://frames/two.png"]]
        assert not list((tmp_path / "Images").iterdir())
    else:
        api.AnimePackGenerator.download_images(gen, cand)
        assert cand.has_frame
        assert gen.saved == [gen.data["https://frames/two.png"]]
    assert cand.frame_url.endswith("two.png")
    assert cand.frame_has_characters is False
    assert len(gen.gemini_frames.calls) == 2


def test_one_request_answers_both_questions_and_cache_reuses_the_verdict(tmp_path):
    gen = Generator(tmp_path, [verdict(characters=False)])
    data = png("white")
    first = frames.check(gen, candidate(), data, ".png")
    assert frames.check(gen, candidate(api.PIXEL_KIND), data, ".png") == first
    assert len(gen.gemini_frames.calls) == 1
    prompt, image = gen.gemini_frames.calls[0]
    assert "Тетрадь смерти" in prompt["text"] and "Death Note" in prompt["text"]
    assert "has_characters" in prompt["text"] and "has_title_text" in prompt["text"]
    assert base64.b64decode(image["data"]) == data


@pytest.mark.parametrize("kind", api.FRAME_KINDS)
@pytest.mark.parametrize("characters,bonus", [(False, 2), (True, 0), (None, 0)])
def test_only_confirmed_absence_adds_two_and_repricing_does_not_accumulate(kind, characters, bonus):
    cand = candidate(kind)
    cand.frame_has_characters = characters
    settings = api.PackSettings()
    api.assign_prices([cand], settings)
    price = cand.price
    cand.frame_has_characters = None
    api.assign_prices([cand], settings)
    assert price == cand.price + bonus
    cand.frame_has_characters = characters
    api.assign_prices([cand], settings)
    assert cand.price == price
    assert any("нет персонажей" in line for line in cand.price_parts) == bool(bonus)


def test_ordinary_frames_and_effects_have_independent_switches(tmp_path):
    gen = Generator(tmp_path, [verdict(title=True)])
    gen.s.frame_gemini_check = False
    cand = candidate()
    assert frames.select(gen, cand) is not None
    assert cand.frame_has_characters is None and not gen.gemini_frames.calls
    assert frames.select(gen, candidate(api.PIXEL_KIND)) is None
    assert len(gen.gemini_frames.calls) == 1


@pytest.mark.parametrize("response", [
    {**verdict(), "has_characters": "false"},
    {key: value for key, value in verdict().items() if key != "has_characters"},
    {**verdict(), "has_title_text": True},
])
def test_bad_or_contradictory_verdict_never_accepts_a_frame(tmp_path, response):
    gen = Generator(tmp_path, [response])
    assert frames.select(gen, candidate()) is None


def test_quota_failure_stops_checked_frame_kinds_without_unverified_fallback(tmp_path):
    gen = Generator(tmp_path, [GeminiQuotaError("quota")])
    client = gen.gemini_frames
    assert frames.select(gen, candidate()) is None
    assert gen.gemini_frames is None and set(gen.dead) == set(api.FRAME_KINDS)
    assert len(client.calls) == 1


def test_invalid_verdict_is_not_cached(tmp_path):
    gen = Generator(tmp_path, [{**verdict(), "has_characters": 0}])
    with pytest.raises(GeminiError):
        frames.check(gen, candidate(), png("white"), ".png")
    assert not gen.db_cache.rows


def test_switches_round_trip_and_gemini_options_are_visible_for_either_kind(qapp):
    tab = animepack_tab.AnimePackTab(main_window=_FakeMain(gemini="test-key"))
    try:
        tab.chk_frames.setChecked(True)
        tab.chk_frame_gemini.setChecked(True)
        tab.chk_pixel.setChecked(True)
        tab.chk_pixel_gemini.setChecked(False)
        settings = tab.collect()
        assert settings.frame_gemini_check and not settings.pixel_gemini_check
        assert tab.box_frames.isVisibleTo(tab) and tab.group_gemini.isVisibleTo(tab)
        tab.apply_settings(api.PackSettings.from_dict(settings.to_dict()))
        assert tab.chk_frame_gemini.isChecked() and not tab.chk_pixel_gemini.isChecked()
        tab.chk_frames.setChecked(False)
        assert not tab.box_frames.isVisibleTo(tab)
        tab.chk_pixel_gemini.setChecked(True)
        assert tab.group_gemini.isVisibleTo(tab)
    finally:
        tab.cleanup()


@pytest.mark.parametrize("kind,field", [(api.FRAME_KIND, "frame_gemini_check"),
                                        (api.PIXEL_KIND, "pixel_gemini_check")])
def test_enabled_check_needs_a_key_only_for_an_active_kind(kind, field):
    settings = api.PackSettings(pct_songs=0, pct_frames=100 if kind == api.FRAME_KIND else 0,
                               pack_pixel=kind == api.PIXEL_KIND,
                               pct_pixel=100 if kind == api.PIXEL_KIND else 0)
    assert not settings.validate()
    setattr(settings, field, True)
    assert any("проверки кадров" in issue for issue in settings.validate())
    settings.gemini_key = "key"
    assert not settings.validate()


def test_frame_client_uses_shared_quota_board_and_visual_timeout(monkeypatch):
    import gemini_api
    calls = []
    def client(key, **kwargs):
        calls.append((key, kwargs))
        return SimpleNamespace(**kwargs)
    monkeypatch.setattr(gemini_api, "GeminiClient", client)
    settings = api.PackSettings(pct_frames=100, pct_songs=0, frame_gemini_check=True,
                               gemini_key="key", gemini_model="test-model")
    gen = api.AnimePackGenerator(settings)
    assert gen.gemini_frames.board is gen.gemini_board
    assert gen.gemini_frames in gen._gemini_clients
    assert calls[0][1]["model"] == "test-model" and calls[0][1]["timeout"] == 60
