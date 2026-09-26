# -*- coding: utf-8 -*-
import io

from PIL import Image
import pytest

from animepack_art_filter import eligible_art_title, possible_art_title
from animepack_art_quality import validate_art_composition
from cloudflare_art_api import CloudflareArtClient, CloudflareArtError, CloudflareArtUnavailable
from cloudflare_ai_quota import fetch_quota, QuotaError


@pytest.mark.parametrize("kind", ["movie", "ova", "ona", "special", "tv_special", ""])
def test_art_requires_tv(kind):
    assert not eligible_art_title({"kind": kind, "related": []}, object())


@pytest.mark.parametrize("name", ["Anime Season 2", "Anime 2nd Season", "Аниме: Часть 2"])
def test_named_sequels_are_excluded(name):
    assert not possible_art_title({"kind": "tv", "name": name, "related": []})


def test_relations_exclude_unlabelled_sequel():
    card = {"kind": "tv", "name": "Shippuuden", "english": "Naruto Shippuden", "related": [
        {"relationKind": "prequel", "anime": {"id": "20", "kind": "tv"}}]}
    assert not eligible_art_title(card, object())
    card["related"][0]["relationKind"] = "sequel"
    assert eligible_art_title(card, object())


def test_old_cache_refreshes_metadata_and_fails_closed():
    card = {"id": 20, "kind": "tv", "english": "Example"}
    assert not eligible_art_title(card, object())

    class Shiki:
        def animes_by_ids(self, ids):
            assert ids == [20]
            return [{"id": 20, "kind": "tv", "english": "Example", "related": []}]

    assert eligible_art_title(card, Shiki())
    assert card["related"] == []


def test_art_requires_shikimori_english_title():
    assert not possible_art_title({
        "kind": "tv", "name": "Naruto", "russian": "Наруто", "related": []})


def test_white_bottom_is_rejected_without_rejecting_bright_scene():
    image = Image.new("RGB", (256, 256), "blue")
    image.paste("white", (0, 190, 256, 256))
    data = io.BytesIO()
    image.save(data, "PNG")
    with pytest.raises(CloudflareArtError, match="белую"):
        validate_art_composition(data.getvalue())
    data = io.BytesIO()
    Image.new("RGB", (256, 256), "white").save(data, "PNG")
    validate_art_composition(data.getvalue())


def test_flagged_output_skips_title_without_disabling_service(fake_session, fake_response):
    session = fake_session([("/ai/run/", fake_response(400, json_data={"errors": [
        {"code": 3030, "message": "Your output has been flagged. secret"}]}))])
    client = CloudflareArtClient("a" * 32, "secret", session=session)
    with pytest.raises(CloudflareArtError) as exc:
        client.generate("Anime", seed=42)
    assert not isinstance(exc.value, CloudflareArtUnavailable)
    assert "secret" not in str(exc.value)
    assert len(session.calls) == 3


@pytest.mark.parametrize("used,remaining", [(0, 10000), (1234.5, 8765.5), (12000, 0)])
def test_account_quota(fake_session, fake_response, used, remaining):
    session = fake_session([("/graphql", fake_response(json_data={"data": {"viewer": {
        "accounts": [{"aiInferenceAdaptiveGroups": [{"sum": {"totalNeurons": used}}]}]
    }}, "errors": None}))])
    assert fetch_quota("a" * 32, "secret", session=session)["remaining"] == remaining


def test_quota_permission_failure_never_reports_full_balance(fake_session, fake_response):
    session = fake_session([("/graphql", fake_response(json_data={"data": None, "errors": [
        {"message": "secret", "extensions": {"code": "authz"}}]}))])
    with pytest.raises(QuotaError, match="Account Analytics: Read") as exc:
        fetch_quota("a" * 32, "secret", session=session)
    assert "secret" not in str(exc.value)
