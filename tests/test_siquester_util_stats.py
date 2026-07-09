# -*- coding: utf-8 -*-
"""Тесты siquester/util.py и siquester/stats.py (хелперы без GUI)."""
import pytest

from siquester import util as sq_util
from siquester import stats as sq_stats


# ── fmt_dur ──────────────────────────────────────────────────────────────────
class TestFmtDur:
    @pytest.mark.parametrize("sec,expected", [
        (0, "0:00"),
        (5, "0:05"),
        (65, "1:05"),
        (3600, "1:00:00"),
        (3725, "1:02:05"),
        (59.9, "0:59"),   # int() отсекает дробную часть
    ])
    def test_values(self, sec, expected):
        assert sq_util.fmt_dur(sec) == expected


# ── _parse_hms ───────────────────────────────────────────────────────────────
class TestParseHms:
    @pytest.mark.parametrize("s,expected", [
        ("00:00:26", 26.0),
        ("01:02:03", 3723.0),
        ("02:30", 150.0),
        (" 1:05 ", 65.0),
    ])
    def test_valid(self, s, expected):
        assert sq_util._parse_hms(s) == expected

    @pytest.mark.parametrize("s", ["", "abc", "1:2:3:4", "1", "aa:bb"])
    def test_invalid(self, s):
        assert sq_util._parse_hms(s) is None


# ── _make_tag_fn ─────────────────────────────────────────────────────────────
class TestMakeTagFn:
    def test_no_namespace(self):
        tag = sq_util._make_tag_fn("")
        assert tag("round") == "round"

    def test_with_namespace(self):
        tag = sq_util._make_tag_fn("http://ns.example/siq")
        assert tag("round") == "{http://ns.example/siq}round"

    def test_cache_consistent(self):
        tag = sq_util._make_tag_fn("http://x")
        assert tag("a") is tag("a")  # закешированная строка


# ── _q_idx ───────────────────────────────────────────────────────────────────
class TestQIdx:
    def test_linear_fallback(self):
        qs = [{"price": 100}, {"price": 200}, {"price": 300}]
        assert sq_util._q_idx(qs, 200) == 1

    def test_registered_map(self):
        qs = [{"price": 100}, {"price": 200}]
        sq_util._qs_price_map[id(qs)] = {100: 0, 200: 1}
        try:
            assert sq_util._q_idx(qs, 200) == 1
        finally:
            sq_util._qs_price_map.pop(id(qs), None)

    def test_not_found_raises(self):
        with pytest.raises(ValueError, match="999"):
            sq_util._q_idx([{"price": 100}], 999)

    def test_empty_list(self):
        with pytest.raises(ValueError):
            sq_util._q_idx([], 100)


# ── _tight / _lbl (Qt) ──────────────────────────────────────────────────────
@pytest.mark.qt
class TestQtHelpers:
    def test_tight(self, qapp):
        from PyQt6.QtWidgets import QVBoxLayout
        lay = sq_util._tight(QVBoxLayout())
        m = lay.contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == (0, 0, 0, 0)
        assert lay.spacing() == 0

    def test_lbl(self, qapp):
        l = sq_util._lbl("<b>текст</b>", "color:#fff;")
        assert l.text() == "<b>текст</b>"
        assert l.styleSheet() == "color:#fff;"

    def test_screen_scale_cached_and_bounded(self, qapp, monkeypatch):
        monkeypatch.setattr(sq_util, "_SCREEN_SCALE_CACHE", None)
        v = sq_util._screen_scale()
        assert 0.75 <= v <= 1.5
        assert sq_util._screen_scale() == v  # из кеша


# ── stats.py ─────────────────────────────────────────────────────────────────
class TestStatsPct:
    def test_found(self):
        assert sq_stats.stats_pct("Попыток 5 (42%)") == 42.0

    def test_missing(self):
        assert sq_stats.stats_pct("нет процентов") == 0.0

    def test_first_match(self):
        assert sq_stats.stats_pct("(10%) и (99%)") == 10.0


class TestDsAvgs:
    def test_averages(self):
        ds = {"rounds": [
            {"themes": [
                {"questions": [{"tries": 50, "right": 40}, {"tries": 30, "right": 20}]},
            ]},
            {"themes": [
                {"questions": [{"tries": 10, "right": 0}]},
            ]},
        ]}
        tries, right = sq_stats.ds_avgs(ds)
        assert tries == pytest.approx(30.0)
        assert right == pytest.approx(20.0)

    def test_missing_keys_default_zero(self):
        ds = {"rounds": [{"themes": [{"questions": [{}]}]}]}
        assert sq_stats.ds_avgs(ds) == (0.0, 0.0)

    def test_empty(self):
        assert sq_stats.ds_avgs({"rounds": []}) == (0.0, 0.0)


class TestGetHl:
    def test_no_rules_by_default(self):
        assert sq_stats.HIGHLIGHT_RULES == []
        assert sq_stats.get_hl("любой пакет") is None

    def test_rule_matches(self, monkeypatch):
        monkeypatch.setattr(sq_stats, "HIGHLIGHT_RULES",
                            [("особый", "#111", "#222", "#333")])
        assert sq_stats.get_hl("Мой ОСОБЫЙ пак") == ("#111", "#222", "#333")
        assert sq_stats.get_hl("обычный") is None
