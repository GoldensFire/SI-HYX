# -*- coding: utf-8 -*-
"""OCR checks title text locally while preserving Pixiv's semantic check."""
from types import SimpleNamespace

import cv2
import numpy as np

from si_hyx_parts.animepack import local_visual_ocr as ocr
from si_hyx_parts.animepack.local_title_match import decide, normalize, titles
from si_hyx_parts.animepack.manga_visual_check import check as manga_check
from si_hyx_parts.animepack.pixiv_visual_check import check as pixiv_check
from animepack import PackSettings


class Cache:
    def __init__(self):
        self.values = {}

    def memo(self, group, key):
        return self.values.get((group, key))

    def remember_memo(self, group, key, value):
        self.values[(group, key)] = value


def row(text, confidence=.99, model="latin", crop=0):
    return {"text": text, "confidence": confidence, "det_score": .9,
            "model": model, "crop": crop}


def test_title_variants_normalization_and_short_names():
    card = {"russian": "Клинок, рассекающий демонов", "name": "Kimetsu no Yaiba",
            "english": "Demon Slayer", "synonyms": ["Demon Slayer"]}
    names = titles(card, ["鬼滅の刃", "Клинок демонов"])
    assert names.count("Demon Slayer") == 1
    assert "Клинок демонов" in names
    assert normalize("N—A | N · A").replace(" ", "") == "nana"
    assert decide([row("DEMON"), row("SLAYER", crop=1)], names)["status"] == "title"
    assert decide([row("Demon Slayr")], names)["status"] == "title"
    assert decide([row("NANA")], ["Nana"])["status"] == "title"
    assert decide([row("NANB")], ["Nana"])["status"] == "safe"
    assert decide([row("86")], ["86"])["status"] == "uncertain"
    assert decide([row("K")], ["K"])["status"] == "uncertain"
    assert decide([row("Бродяга", model="cyrillic")],
                  ["Бродяга"])["status"] == "title"
    assert decide([row("Vagabomd")], ["Vagabond"])["status"] == "uncertain"
    assert decide([row("Artist", .98, "latin"), row("", .1, "cyrillic")],
                  ["Vagabond"])["status"] == "safe"


def test_one_detection_two_recognizers_and_image_hash_cache():
    calls = {"det": 0, "latin": 0, "cyrillic": 0}

    class Model:
        def __init__(self, name):
            self.name = name

        def __call__(self, image, **kwargs):
            calls["det"] += 1
            return SimpleNamespace(boxes=np.array([[[0, 0], [30, 0],
                                                     [30, 20], [0, 20]]]),
                                   scores=[.9])

        def crop_text_regions(self, image, boxes):
            return [image[:20, :30]]

        def recognize_txt(self, crops):
            calls[self.name] += 1
            return SimpleNamespace(txts=["Nana"], scores=[.99])

    image = np.full((40, 50, 3), 255, np.uint8)
    data = cv2.imencode(".png", image)[1].tobytes()
    gen = SimpleNamespace(db_cache=Cache(), stopped=lambda: False)
    ocr.initialize(gen)
    gen._ocr_models = (Model("latin"), Model("cyrillic"))
    first, _time, cached = ocr.read(gen, data)
    second, _time, cached_again = ocr.read(gen, data)
    assert cached is False and cached_again is True
    assert first == second and len(first) == 2
    assert calls == {"det": 1, "latin": 1, "cyrillic": 1}


def test_manga_local_mode_rejects_title_without_gemini(monkeypatch):
    monkeypatch.setattr(ocr, "read", lambda gen, data: ([row("Vagabond")], .1, False))
    gen = SimpleNamespace(s=SimpleNamespace(manga_title_check_mode="local"),
                          gemini_manga=None, stopped=lambda: False, log=lambda msg: None)
    cand = SimpleNamespace(anime={"name": "Different Name"})
    assert manga_check(gen, cand, b"image", ".png",
                       manga_titles=["Vagabond"])[0] is False


def test_manga_local_mode_needs_no_key_and_uses_gemini_for_border(monkeypatch):
    settings = PackSettings(pct_songs=0, pack_manga=True, pct_manga=100,
                            manga_title_check_mode="local", manga_character_crop=False)
    assert not any("страниц манги нужен ключ Gemini" in problem
                   for problem in settings.validate())
    calls = []

    class Gemini:
        model = "test"

        def generate_json(self, parts, schema, temperature=0):
            calls.append(parts)
            return {"accept": False, "has_title_text": True,
                    "reason": "логотип"}

    monkeypatch.setattr(ocr, "read", lambda gen, data: ([row("Vagabomd")], .1, False))
    gen = SimpleNamespace(s=settings, gemini_manga=Gemini(), db_cache=Cache(),
                          stopped=lambda: False, log=lambda msg: None)
    cand = SimpleNamespace(anime={"name": "Vagabond"})
    assert manga_check(gen, cand, b"image", ".png")[0] is False
    assert len(calls) == 1


def test_pixiv_local_title_skips_gemini_but_safe_art_checks_mixed(monkeypatch):
    class Gemini:
        model = "test"

        def __init__(self):
            self.calls = []

        def generate_json(self, parts, schema, temperature=0):
            self.calls.append(parts)
            return {"accept": True, "has_title_text": True,
                    "mixed_anime": False, "reason": "название"}

    client = Gemini()
    gen = SimpleNamespace(s=SimpleNamespace(pixiv_title_check_mode="local",
                                            pixiv_gemini_check=True),
                          gemini_pixiv=client, db_cache=Cache(),
                          stopped=lambda: False, log=lambda msg: None)
    cand = SimpleNamespace(anime={"english": "Demon Slayer"})
    monkeypatch.setattr(ocr, "read", lambda gen, data: ([row("Demon Slayer")], .1, False))
    assert pixiv_check(gen, cand, b"title", ".png")[0] is False
    assert client.calls == []
    monkeypatch.setattr(ocr, "read", lambda gen, data: ([row("Artist")], .1, False))
    assert pixiv_check(gen, cand, b"safe", ".png")[0] is True
    assert len(client.calls) == 1
    assert "только чужие франшизы" in client.calls[0][0]["text"]


def test_tab_roundtrips_both_local_modes(qapp):
    from animepack_tab import AnimePackTab

    tab = AnimePackTab()
    try:
        tab.cb_manga_title_mode.setCurrentIndex(
            tab.cb_manga_title_mode.findData("local"))
        tab.cb_pixiv_title_mode.setCurrentIndex(
            tab.cb_pixiv_title_mode.findData("local"))
        saved = tab.get_settings()
        tab.apply_settings(PackSettings().to_dict())
        tab.apply_settings(saved)
        settings = tab.collect()
        assert settings.manga_title_check_mode == "local"
        assert settings.pixiv_title_check_mode == "local"
    finally:
        tab.cleanup()
