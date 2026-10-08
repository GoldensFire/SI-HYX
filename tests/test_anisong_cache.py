"""Сырые ответы AnisongDB переживают генерацию; ошибки сети не запоминаются."""
import time

import pytest

import animepack as ap
from si_hyx_parts.animepack.anisong_cache import CachedAnisong


def _song(mal, name):
    return {"songName": name, "linked_ids": {"myanimelist": mal}}


class Api:
    def __init__(self):
        self.asked = []
        self.fail = False

    def songs_by_mal_ids(self, ids):
        self.asked.append(list(ids))
        if self.fail:
            raise ap.AnimePackApiError("AnisongDB: таймаут")
        return [_song(mal, f"OP {mal}") for mal in ids if mal != 3]


def test_cached_ids_are_not_asked_again_and_empty_answer_counts(tmp_path):
    api = Api()
    cache = CachedAnisong(api, str(tmp_path / "a.sqlite"))
    assert [s["songName"] for s in cache.songs_by_mal_ids([1, 2, 3])] == ["OP 1", "OP 2"]
    again = CachedAnisong(api, str(tmp_path / "a.sqlite"))
    assert [s["songName"] for s in again.songs_by_mal_ids([3, 2, 4])] == ["OP 2", "OP 4"]
    assert api.asked == [[1, 2, 3], [4]]
    cache.close()
    again.close()


def test_network_error_is_not_cached(tmp_path):
    api = Api()
    cache = CachedAnisong(api, str(tmp_path / "a.sqlite"))
    api.fail = True
    with pytest.raises(ap.AnimePackApiError):
        cache.songs_by_mal_ids([5])
    api.fail = False
    assert cache.songs_by_mal_ids([5])[0]["songName"] == "OP 5"
    assert api.asked == [[5], [5]]
    cache.close()


def test_stale_answers_are_refreshed(tmp_path):
    api = Api()
    cache = CachedAnisong(api, str(tmp_path / "a.sqlite"), ttl=60)
    cache.songs_by_mal_ids([7])
    cache._connect().execute("UPDATE songs SET fetched = ?", (time.time() - 120,))
    cache.songs_by_mal_ids([7])
    assert api.asked == [[7], [7]]
    cache.close()


def test_other_methods_go_straight_to_the_api(tmp_path):
    api = Api()
    api.songs_by_ann_ids = lambda ids: ["ann"]
    assert CachedAnisong(api, str(tmp_path / "a.sqlite")).songs_by_ann_ids([1]) == ["ann"]
