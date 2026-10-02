# -*- coding: utf-8 -*-
"""Студия не блокирует работы, которых нет в готовом вопросе."""
import json

from animepack import STUDIO_KIND, SongCandidate
from si_hyx_parts.animepack import studio_question, pack_manifest
from test_animepack_studio import generator, _studio_card as _base_card


def _studio_card(number):
    card = _base_card(number)
    for field in ("russian", "name", "english"):
        card[field] = "Произведение " + chr(ord("а") + number)
    return card


def test_studio_reserves_only_three_shown_titles(generator, monkeypatch):
    cards = [_studio_card(i) for i in range(10)]
    cand = SongCandidate({}, cards[0], kind=STUDIO_KIND)
    cand._reserved = tuple(studio_question._pack_marks(cards[0]))
    generator._used_franchise.update(cand._reserved)
    monkeypatch.setattr(studio_question, "_cards_for_studio", lambda *a: cards)
    monkeypatch.setattr(studio_question, "_download_one", lambda g, c, card, n:
                        (f"frame{n}", f"url{n}", object()))
    monkeypatch.setattr(studio_question, "_save_poster_strip", lambda *a: True)
    assert studio_question.download_frames(generator, cand)
    expected = set().union(*(studio_question._pack_marks(c) for c in cards[:3]))
    assert generator._used_franchise == expected
    assert cand.studio_cards == cards[:3]


def test_failed_studio_frame_releases_its_title(generator, monkeypatch):
    cards = [_studio_card(i) for i in range(5)]
    cand = SongCandidate({}, cards[0], kind=STUDIO_KIND)
    cand._reserved = tuple(studio_question._pack_marks(cards[0]))
    generator._used_franchise.update(cand._reserved)
    monkeypatch.setattr(studio_question, "_cards_for_studio", lambda *a: cards)

    def download(g, c, card, n):
        if card is cards[0]:
            return None
        assert not (studio_question._pack_marks(cards[4]) & g._used_franchise)
        return f"frame{n}", f"url{n}", object()

    monkeypatch.setattr(studio_question, "_download_one", download)
    monkeypatch.setattr(studio_question, "_save_poster_strip", lambda *a: True)
    assert studio_question.download_frames(generator, cand)
    expected = set().union(*(studio_question._pack_marks(c) for c in cards[1:4]))
    assert generator._used_franchise == expected
    manifest = json.loads(pack_manifest.build([cand]))
    assert {r["mal"] for r in manifest["titles"]} == {c["malId"] for c in cards[1:4]}


def test_studio_skips_a_title_taken_by_another_question(generator, monkeypatch):
    cards = [_studio_card(i) for i in range(5)]
    cand = SongCandidate({}, cards[0], kind=STUDIO_KIND)
    occupied = studio_question._pack_marks(cards[1])
    generator._used_franchise.update(occupied)
    monkeypatch.setattr(studio_question, "_cards_for_studio", lambda *a: cards)
    asked = []

    def download(g, c, card, n):
        asked.append(card)
        return f"frame{n}", f"url{n}", object()

    monkeypatch.setattr(studio_question, "_download_one", download)
    monkeypatch.setattr(studio_question, "_save_poster_strip", lambda *a: True)
    assert studio_question.download_frames(generator, cand)
    assert cards[1] not in asked
    assert occupied <= generator._used_franchise
