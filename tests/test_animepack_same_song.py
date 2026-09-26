# -*- coding: utf-8 -*-
import animepack as ap

from si_hyx_parts.animepack.song_multi_anime import enrich


def _card(mal, title, franchise, year=2020):
    return {"id": mal, "malId": mal, "russian": title, "name": title,
            "english": title + " EN", "synonyms": [title + " Alt"],
            "franchise": franchise, "airedOn": {"year": year},
            "statusesStats": []}


def _song(mal, kind="Opening 1"):
    return {"songName": "Same Song", "songArtist": "Same Artist",
            "songType": kind, "linked_ids": {"myanimelist": mal}}


class _Api:
    def songs_by_name_artist(self, name, artist):
        assert (name, artist) == ("Same Song", "Same Artist")
        return [_song(1), _song(2, "Ending 1"), _song(3), _song(4)]


class _Cache:
    def __init__(self):
        self.value = None

    def memo(self, *_args):
        return self.value

    def remember_memo(self, _group, _key, value):
        self.value = value


class _Gen:
    anisong = _Api()
    db_cache = _Cache()

    def _animes_by_ids(self, ids):
        cards = {2: _card(2, "Фильм той же серии", "one"),
                 3: _card(3, "Другой тайтл", "two", 2021),
                 4: _card(4, "Третий тайтл", "three", 2022)}
        return [cards[i] for i in ids]

    def _log_rare(self, *_args):
        pass


def test_same_franchise_placement_is_not_added_to_the_answer():
    cand = ap.SongCandidate(_song(1), _card(1, "Оригинал", "one"))
    enrich(_Gen(), cand)
    assert [row["anime"]["malId"] for row in cand.song_alternates] == [3, 4]
    assert cand.main_answer == (
        "Оригинал OP1 (2020) / Другой тайтл OP1 (2021) / "
        "Третий тайтл OP1 (2022) — 『Same Song』")
    variants = cand.answer_variants()
    assert "Другой тайтл EN" in variants
    assert "Третий тайтл Alt" in variants
