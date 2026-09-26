"""Reject untranslated titles before quotas are filled, including Cyrillic ones."""
import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import animepack as ap
from si_hyx_parts.animepack.title_eligibility import (
    checked_candidates, has_russian_letters_only,
)

# «Не годится ни подо что»: и русских слов нет, и антонимов не подобрать.
NO = {"eligible": False, "antonyms": False}


def candidate(title, ident=1):
    # kind у карточки нужен антонимам: их берут только с ТВ-сериалов и
    # полнометражек (см. ANTONYM_KINDS).
    return ap.SongCandidate(song={}, anime={
        "id": ident, "russian": title, "name": "Original name",
        "kind": "tv", "related": []}, kind="synonyms")


@pytest.mark.parametrize("title", ["", "Attack on Titan", "Атака Titan",
                                    "進撃の巨人", "Атака 進撃", "123"])
def test_non_russian_titles_are_rejected_without_model(title):
    client = Mock()
    gen = SimpleNamespace(s=ap.PackSettings(pack_synonyms=True, pct_synonyms=100),
                          gemini=client, stopped=lambda: False)
    items = [candidate(title)]
    assert list(checked_candidates(gen, iter(items))) == items
    assert gen._title_eligibility[title] == NO
    client.generate_json.assert_not_called()


def test_cyrillic_transliterations_require_semantic_check():
    titles = ["Атака титанов", "Секирей", "Дневник Наруто", "Блич", "Тетрадь смерти"]
    assert all(has_russian_letters_only(title) for title in titles)
    client = Mock()
    client.generate_json.return_value = {"items": [
        {"id": i, "eligible": i in (0, 4), "antonyms": i == 0}
        for i in range(len(titles))]}
    gen = SimpleNamespace(s=ap.PackSettings(pack_synonyms=True, pct_synonyms=100),
                          gemini=client, stopped=lambda: False, log=lambda msg: None)
    items = [candidate(title, titles.index(title) + 1) for title in titles * 2]
    assert list(checked_candidates(gen, iter(items))) == items
    assert gen._title_eligibility == {
        title: {"eligible": i in (0, 4), "antonyms": i == 0}
        for i, title in enumerate(titles)}
    assert client.generate_json.call_count == 1


@pytest.mark.parametrize("response", [{}, {"items": [{"id": 0, "eligible": "true"}]}])
def test_invalid_check_cannot_accept_title(response):
    gen = SimpleNamespace(s=ap.PackSettings(pack_synonyms=True, pct_synonyms=100),
        gemini=Mock(generate_json=Mock(return_value=response)),
        stopped=lambda: False, log=lambda msg: None)
    with pytest.raises(RuntimeError, match="Gemini"):
        list(checked_candidates(gen, iter([candidate("Секирей")])))


def test_rejected_titles_are_replaced_for_all_three_kinds(tmp_path, monkeypatch):
    settings = ap.PackSettings(rounds=1, themes=1, questions=3, pct_songs=0,
        pack_synonyms=True, pct_synonyms=34, pack_antonyms=True, pct_antonyms=33,
        pack_ukrainian=True, pct_ukrainian=33, gemini_key="test", poster_cache=False)
    allowed = {"Атака титанов", "Тетрадь смерти", "Стальной алхимик"}
    titles = ["Секирей", "Дневник Наруто", "Атака Titan", "Блич", "",
              "Атака титанов", "Тетрадь смерти", "Стальной алхимик"]
    client = Mock()

    def respond(prompt, schema):
        rows = json.loads(prompt.split("\n")[-1])
        if "eligible" in schema["properties"]["items"]["items"]["properties"]:
            return {"items": [{"id": row["id"],
                               "eligible": row["title"] in allowed,
                               "antonyms": row["title"] in allowed}
                              for row in rows]}
        return {"items": [{"id": row["id"], "text": "Изменённое название"}
                          for row in rows]}

    client.generate_json.side_effect = respond
    gen = ap.AnimePackGenerator(settings, gemini=client,
                               frames_history_path=str(tmp_path / "frames.json"))
    monkeypatch.setattr(gen, "iter_candidates", lambda: iter(
        [candidate(title, i + 1) for i, title in enumerate(titles)]))
    fetched = []
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: fetched.append(cand) or True)
    result = gen.select_songs()
    assert len(result) == 3
    assert {cand.title_ru for cand in result} == allowed
    assert {cand.kind for cand in result} == {"synonyms", "antonyms", "ukrainian"}
    assert {cand.title_ru for cand in fetched} == allowed


def test_title_filter_does_not_exclude_song_questions(tmp_path):
    gen = ap.AnimePackGenerator(ap.PackSettings(),
                               frames_history_path=str(tmp_path / "frames.json"))
    cand = candidate("Секирей")
    cand.kind = "opening"
    gen._title_eligibility = {"Секирей": False}
    quotas = {"opening": 1, "synonyms": 1, "antonyms": 1, "ukrainian": 1}
    assert gen._pick_kind(cand, Counter(), Counter(), quotas) == "opening"
