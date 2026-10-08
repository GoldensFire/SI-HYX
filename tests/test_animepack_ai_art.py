# -*- coding: utf-8 -*-
"""Random anime selection through real media/answer/SIQ assembly."""
import base64
from collections import Counter
import io
import random
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image
import pytest

import animepack
from animepack import AI_ART_KIND, ANAGRAM_KIND, PackSettings, SongCandidate
from cloudflare_art_api import CloudflareArtClient, CloudflareArtUnavailable
from test_animepack_new_kinds import make_anime as _make_anime


def make_anime(**kwargs):
    return _make_anime(**{"related": [], **kwargs})


@pytest.fixture
def generator(tmp_path, monkeypatch, fake_session, fake_response):
    monkeypatch.setattr(animepack, "CONFIG_DIR", str(tmp_path))
    buf = io.BytesIO()
    Image.new("RGB", (128, 128), "blue").save(buf, "PNG")
    body = {"success": True, "result": {
        "image": base64.b64encode(buf.getvalue()).decode("ascii")}}
    session = fake_session([("/ai/run/", fake_response(json_data=body))])
    client = CloudflareArtClient("a" * 32, "test-token", session=session)
    settings = PackSettings(
        pct_songs=0, pack_ai_art=True, pct_ai_art=100,
        cloudflare_account_id="a" * 32, cloudflare_token="test-token",
        rounds=1, themes=1, questions=4, compress_images=False,
        level_min=0, level_max=100, mark_owners=False, parallel=1)
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=object(), mal=object(), tmdb=object(), cloudflare=client,
        rng=random.Random(3))
    monkeypatch.setattr(gen, "_poster_bytes", lambda *a: (b"", ""))
    yield gen, session, buf.getvalue()
    gen.cleanup()


def test_pure_art_pack_random_titles_answers_and_images(generator, tmp_path, monkeypatch):
    gen, session, image = generator
    titles = ["Naruto", "Bleach", "Death Note", "Clannad", "Monster", "Steins Gate"]
    cards = [make_anime(id=i, malId=i, name=t, english=t, russian=t,
                        franchise=t.lower(), synonyms=[], screenshots=[], poster={})
             for i, t in enumerate(titles, 1)]

    class Shikimori:
        def random_animes(self, page, **kwargs):
            return cards if page == 1 else []

        def franchise_parts(self, ids):
            return {}

    gen.shikimori = Shikimori()
    # Real randomized catalog collection and filters; no AMQ/Anisong methods exist.
    output = gen.run(str(tmp_path / "art.siq"))
    assert len(output.songs) == 4
    assert {c.kind for c in output.songs} == {AI_ART_KIND}
    assert len({c.mal_id for c in output.songs}) == 4
    prompts = [kw["files"]["prompt"][1] for _, _, kw in session.calls]
    assert len(prompts) == 4
    assert not all(title in prompt for title, prompt in zip(titles[:4], prompts))
    with zipfile.ZipFile(output.path) as archive:
        root = ET.fromstring(archive.read("content.xml"))
        assert archive.read("quality.marker") == b""
        questions = root.findall(".//{*}question")
        assert len(questions) == 4
        assert not any(name.startswith(("Audio/", "Video/")) for name in archive.namelist())
        for question in questions:
            items = question.findall("./{*}params/{*}param[@name='question']/{*}item")
            assert len(items) == 1 and items[0].get("type") == "image"
            image_name = items[0].text.lstrip("@")
            assert archive.read("Images/" + image_name) == image
            assert question.findall("./{*}right/{*}answer")
        assert "test-token" not in archive.read("content.xml").decode("utf-8")


def test_generated_art_uses_existing_image_compression(generator, monkeypatch):
    gen, _, image = generator
    gen.s.compress_images = True
    gen.prepare_dirs()
    saved = []
    monkeypatch.setattr(gen, "_to_avif", lambda data, name, ext:
                        saved.append((data, name, ext)) or True)
    cand = SongCandidate({}, make_anime(), kind=AI_ART_KIND)
    assert gen._fetch_media(cand)
    assert cand.is_picture and cand.is_silent and not cand.is_frame
    assert cand.frame_file.endswith(".avif")
    assert saved[0][0] == image and saved[0][2] == ".png"


def test_failed_art_has_no_empty_question(generator, monkeypatch):
    gen, _, _ = generator
    gen.prepare_dirs()
    monkeypatch.setattr(gen.art_service, "generate", lambda *_:
                        (_ for _ in ()).throw(CloudflareArtUnavailable("quota")))
    cand = SongCandidate({}, make_anime(), kind=AI_ART_KIND)
    assert gen._fetch_media(cand) is False
    assert not cand.has_frame and cand.rejected
    assert gen._dead_kinds == {AI_ART_KIND}


def test_quota_does_not_scan_the_rest_of_the_catalog(generator, monkeypatch):
    gen, _, _ = generator
    gen.prepare_dirs()
    from si_hyx_parts.animepack.candidate_source import WINDOW
    seen, calls = [], []

    def candidates():
        for i in range(WINDOW * 5):
            seen.append(i)
            yield SongCandidate({}, make_anime(malId=i + 1), kind=AI_ART_KIND)

    def unavailable(*args):
        calls.append(args)
        raise CloudflareArtUnavailable("quota")

    monkeypatch.setattr(gen, "iter_candidates", candidates)
    monkeypatch.setattr(gen.art_service, "generate", unavailable)
    assert gen.select_songs() == []
    # Источник кандидатов заранее читает одно окно (без запросов): окно,
    # взятый кандидат и тот, на котором ждёт производитель. После смерти
    # рода генерации больше не просят и каталог дальше не листают.
    assert len(calls) <= 2
    assert len(seen) <= WINDOW + 2


def test_art_and_other_kinds_share_quotas_and_recover(generator):
    gen, _, _ = generator
    gen.s.pct_ai_art = 50
    gen.s.pack_anagram = True
    gen.s.pct_anagram = 50
    gen.s.preserve_composition = False      # иначе доли не перекладываются
    quotas = gen.s.question_quotas
    assert quotas[AI_ART_KIND] == 2 and quotas[ANAGRAM_KIND] == 2
    cand = SongCandidate({}, make_anime(), kind=ANAGRAM_KIND)
    assert gen._pick_kind(cand, Counter({ANAGRAM_KIND: 2}), Counter(), quotas) == AI_ART_KIND
    gen._drop_kind(AI_ART_KIND)
    gen._share_out_dead(quotas, Counter(), Counter())
    assert quotas[AI_ART_KIND] == 0 and quotas[ANAGRAM_KIND] == 4


def test_art_settings_validate_only_active_category():
    s = PackSettings()
    assert not s.validate()
    s.pct_songs = 0
    s.pack_ai_art = True
    s.pct_ai_art = 100
    assert any("Account ID" in p for p in s.validate())
    s.cloudflare_account_id = "a" * 32
    s.cloudflare_token = "secret"
    assert not s.validate()
    copy = PackSettings.from_dict(s.to_dict())
    assert copy.only_kind == AI_ART_KIND and copy.cloudflare_token == "secret"
    assert "secret" not in repr(copy)


def test_old_flux_one_setting_migrates_to_current_default():
    settings = PackSettings.from_dict({
        "cloudflare_model": "@cf/black-forest-labs/flux-1-schnell"})
    assert "flux-2" in settings.cloudflare_model


def test_art_only_does_not_require_posters_or_screenshots(generator):
    gen, _, _ = generator
    gen.s.images = True  # leftover audio collage preference
    assert animepack.filter_anime(make_anime(poster={}, screenshots=[]), gen.s)
