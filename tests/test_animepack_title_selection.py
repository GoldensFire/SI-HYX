"""First franchise entries and short titles apply only to title questions."""
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import animepack as ap
from si_hyx_parts.animepack.title_selection import first_title, short_title


def card(ident, title="Тетрадь смерти", kind="tv", related=None):
    return {"id": ident, "malId": ident, "russian": title, "kind": kind,
            "related": related or []}


def link(ident, relation="prequel", kind="tv"):
    return {"relationKind": relation, "anime": {"id": ident, "kind": kind}}


def generator(cards):
    api = Mock()
    api.animes_by_ids.side_effect = lambda ids: [cards[i] for i in ids if i in cards]
    return SimpleNamespace(shikimori=api, stopped=lambda: False, log=Mock())


def test_length_counts_spaces_and_punctuation():
    assert short_title(card(1, "А" * 38 + " !"))
    assert not short_title(card(1, "А" * 39 + " !"))
    assert not short_title(card(1, ""))


@pytest.mark.parametrize("kind", ["tv", "movie", "ova", "ona"])
def test_standalone_entries_allowed(kind):
    original = card(1, kind=kind)
    gen = generator({})
    assert first_title(gen, original) == original
    gen.shikimori.animes_by_ids.assert_not_called()


def test_third_season_resolves_to_first_and_caches():
    first = card(1)
    second = card(2, "Тетрадь смерти 2", related=[link(1)])
    third = card(3, "Тетрадь смерти 3", related=[link(2)])
    gen = generator({1: first, 2: second})
    assert first_title(gen, third) == first
    assert first_title(gen, second) == first
    assert gen.shikimori.animes_by_ids.call_count == 2


@pytest.mark.parametrize("kind", ["ova", "movie", "special"])
def test_franchise_extras_resolve_to_main_series(kind):
    first = card(1)
    extra = card(2, kind=kind, related=[link(1, "parent_story")])
    assert first_title(generator({1: first}), extra) == first


def test_old_cache_refresh_and_unavailable_relations():
    old = card(2)
    del old["related"]
    first = card(1)
    refreshed = card(2, related=[link(1)])
    assert first_title(generator({1: first, 2: refreshed}), old) == first
    assert first_title(generator({2: old}), old) is None


def test_cycles_and_unlinked_numbered_seasons_are_rejected():
    one = card(1, related=[link(2)])
    two = card(2, related=[link(1)])
    assert first_title(generator({1: one, 2: two}), one) is None
    assert first_title(generator({}), card(3, "Атака титанов: Сезон 2")) is None


def test_recap_uses_full_story_and_unrelated_special_is_rejected():
    first = card(1)
    recap = card(2, kind="movie", related=[link(1, "full_story")])
    assert first_title(generator({1: first}), recap) == first
    assert first_title(generator({}), card(3, kind="special")) is None


def test_title_pack_uses_short_first_season(tmp_path, monkeypatch):
    """Загадка по названию достаётся ПЕРВОЙ части франшизы с коротким именем."""
    settings = ap.PackSettings(rounds=1, themes=1, questions=1, pct_songs=0,
                              pack_definitions=True, pct_definitions=100,
                              gemini_key="test")
    first = card(1)
    sequel = card(2, "Очень длинное название продолжения " * 3, related=[link(1)])
    shiki = generator({1: first}).shikimori
    gemini = Mock()

    def respond(prompt, schema):
        import json as _json
        rows = _json.loads(prompt.split("\n")[-1])
        if "eligible" in schema["properties"]["items"]["items"]["properties"]:
            return {"items": [{"id": row["id"], "eligible": True,
                               "antonyms": True} for row in rows]}
        return {"items": [{"id": row["id"], "text": "Загадка"} for row in rows]}

    gemini.generate_json.side_effect = respond
    gen = ap.AnimePackGenerator(settings, shikimori=shiki, gemini=gemini,
                               frames_history_path=str(tmp_path / "frames.json"))
    monkeypatch.setattr(gen, "iter_candidates", lambda: iter([
        ap.SongCandidate(song={}, anime=sequel, kind="definitions")]))
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    result = gen.select_songs()
    assert len(result) == 1
    assert result[0].mal_id == 1
    assert result[0].title_ru == "Тетрадь смерти"


def test_long_title_does_not_block_music_in_mixed_pack(tmp_path):
    gen = ap.AnimePackGenerator(ap.PackSettings(),
                               frames_history_path=str(tmp_path / "frames.json"))
    cand = ap.SongCandidate(song={}, anime=card(1, "А" * 41), kind="opening")
    assert gen._pick_kind(cand, Counter(), Counter(),
                          {"definitions": 1, "opening": 1}) == "opening"
    assert gen._pick_kind(cand, Counter(), Counter(), {"definitions": 1}) is None
