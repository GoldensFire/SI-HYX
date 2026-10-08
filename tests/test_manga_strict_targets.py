"""Strict comic completion rejects quota drift and late difficulty drift."""
from collections import Counter
from types import SimpleNamespace

import animepack as ap
from si_hyx_parts.animepack.manga_targets import average_fits, final_error
from si_hyx_parts.animepack.level_avg import short_pack_average_error


def settings(**changes):
    values = dict(rounds=3, themes=8, questions=6, pct_songs=0,
                  pack_manga=True, pct_manga=100, manga_pct_manhwa=40,
                  manga_pct_manhua=20, manga_strict_targets=True,
                  manga_adapted_percent=-1, manga_level_min=3, manga_level_max=10,
                  manga_level_avg=6)
    values.update(changes)
    return ap.PackSettings(**values)


def book(kind="manga", level=6):
    return SimpleNamespace(anime={"kind": kind}, is_manga=True,
                           adapted_from={}, kind=ap.MANGA_KIND, level=level)


def test_exact_144_comic_mix_and_average_are_validated_together():
    configuration = settings()
    rows = [book("manga") for _ in range(58)]
    rows += [book("manhwa") for _ in range(57)]
    rows += [book("manhua") for _ in range(29)]
    assert not final_error(configuration, rows)
    rows[-1] = book("manga")
    assert "Состав" in final_error(configuration, rows)


def test_large_complete_pack_cannot_bypass_final_average_check():
    rows = [book("manga", 8) for _ in range(58)]
    rows += [book("manhwa", 8) for _ in range(57)]
    rows += [book("manhua", 8) for _ in range(29)]
    assert "Средняя" in short_pack_average_error(settings(), rows)


def test_average_uses_inflight_levels_and_ignores_relaxation_escape_valve():
    configuration = settings()
    generator = SimpleNamespace(s=configuration, _bucket_levels={"manga": [6] * 100},
                                _level_relaxed=True)
    assert not average_fits(generator, book(level=10), [], [book(level=10)] * 10)
    assert average_fits(generator, book(level=4), [], [book(level=10)] * 10)


def test_mix_bench_never_unlocks_strict_edition_quota():
    mix = ap.MangaMix(settings(), 144)
    for _ in range(58):
        mix.reserve(book())
    assert not mix.allows(book())
    assert mix.take_bench() == []
    assert not mix.off
    assert mix.allows(book("manhua"))


def test_partial_questions_remain_recoverable():
    assert final_error(settings(), [book(level=10)]) == ""
    assert Counter(ap.MangaMix(settings(), 144).kind_target) == {"": 58, "manhwa": 57, "manhua": 29}


def test_lighter_manga_is_kept_to_balance_future_webtoons():
    configuration = settings()
    selected = [book("manga", 4) for _ in range(10)]
    selected += [book("manhwa", 7) for _ in range(10)]
    generator = SimpleNamespace(s=configuration, _selected_songs=selected,
        _manga_mix=ap.MangaMix(configuration, 144),
        _bucket_levels={"manga": [c.level for c in selected]},
        _manga_plan_stats={"desired_levels": {"manga": 4.5, "manhwa": 6.75, "manhua": 7.5}})
    # The old global prefix rule rejected 4 because the current mean is 5.5.
    assert average_fits(generator, book("manga", 4), [])
    for row in selected[:10]:
        row.level = 5
    assert not average_fits(generator, book("manga", 9), [])
