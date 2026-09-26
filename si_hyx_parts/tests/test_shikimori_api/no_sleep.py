# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""no_sleep. Public namespace: test_shikimori_api."""
import test_shikimori_api as _api


@_api.pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Ретраи не должны реально спать."""
    monkeypatch.setattr(_api.api.time, "sleep", lambda s: None)

no_sleep.__module__ = _api.__name__
_api.no_sleep = no_sleep

# ── views_from_card / index_base_from_card ───────────────────────────────────
class TestViewsFromCard:
    def test_english_keys(self):
        card = {"rates_statuses_stats": [
            {"name": "completed", "value": 100},
            {"name": "watching", "value": 50},
            {"name": "dropped", "value": 10},
            {"name": "planned", "value": 999},
        ]}
        assert _api.api.views_from_card(card) == 160

    def test_russian_labels(self):
        card = {"rates_statuses_stats": [
            {"name": "Просмотрено", "value": 5},
            {"name": "Смотрю", "value": 3},
            {"name": "Брошено", "value": 2},
            {"name": "Запланировано", "value": 100},
            {"name": "Отложено", "value": 50},
        ]}
        assert _api.api.views_from_card(card) == 10

    def test_manga_labels(self):
        card = {"rates_statuses_stats": [
            {"name": "Прочитано", "value": 7},
            {"name": "Читаю", "value": 3},
        ]}
        assert _api.api.views_from_card(card) == 10

    def test_not_dict(self):
        assert _api.api.views_from_card(None) == 0
        assert _api.api.views_from_card("мусор") == 0

    def test_missing_stats(self):
        assert _api.api.views_from_card({}) == 0

    def test_bad_values_skipped(self):
        card = {"rates_statuses_stats": [
            {"name": "completed", "value": "не число"},
            {"name": "watching", "value": 4},
            "мусор",
        ]}
        assert _api.api.views_from_card(card) == 4

TestViewsFromCard.__module__ = _api.__name__
_api.TestViewsFromCard = TestViewsFromCard

class TestIndexBase:
    def test_weights(self):
        card = {"rates_statuses_stats": [
            {"name": "completed", "value": 1},   # 10
            {"name": "watching", "value": 1},    # 8
            {"name": "dropped", "value": 1},     # 6
            {"name": "on_hold", "value": 1},     # 6
            {"name": "planned", "value": 1},     # 2
        ]}
        assert _api.api.index_base_from_card(card) == 32.0

    def test_empty(self):
        assert _api.api.index_base_from_card({}) == 0.0
        assert _api.api.index_base_from_card(None) == 0.0

    def test_components_sorted_and_sum(self):
        card = {"rates_statuses_stats": [
            {"name": "Просмотрено", "value": 2},   # 20
            {"name": "запланировано", "value": 10},  # 20
            {"name": "Смотрю", "value": 1},        # 8
            {"name": "нулевой", "value": 0},
        ]}
        comps = _api.api.index_components_from_card(card)
        labels = [c[0] for c in comps]
        assert set(labels) == {"Просмотрено", "В планах", "Смотрю"}
        assert sum(c[1] for c in comps) == _api.api.index_base_from_card(card)
        # убывание по взвешенному вкладу
        weights = [c[1] for c in comps]
        assert weights == sorted(weights, reverse=True)

    def test_components_empty(self):
        assert _api.api.index_components_from_card(None) == []

TestIndexBase.__module__ = _api.__name__
_api.TestIndexBase = TestIndexBase

# ── kind/status helpers ──────────────────────────────────────────────────────
class TestKindStatusHelpers:
    def test_kinds_for(self):
        assert _api.api.kinds_for("anime") == _api.api.KINDS
        assert _api.api.kinds_for("manga") == _api.api.MANGA_KINDS

    def test_statuses_for(self):
        assert _api.api.statuses_for("manga") == _api.api.MANGA_STATUSES
        assert _api.api.statuses_for("anime") == _api.api.STATUSES

    def test_kind_label(self):
        assert _api.api.kind_label("anime", "tv") == "ТВ-сериал"
        assert _api.api.kind_label("manga", "manhwa") == "Манхва"
        assert _api.api.kind_label("anime", "неизвестный") == "неизвестный"

    def test_status_label(self):
        assert _api.api.status_label("anime", "ongoing") == "Онгоинг"
        assert _api.api.status_label("manga", "paused") == "Пауза"
        assert _api.api.status_label("manga", "x") == "x"

TestKindStatusHelpers.__module__ = _api.__name__
_api.TestKindStatusHelpers = TestKindStatusHelpers

class TestGenreGroup:
    def test_kind_from_api_trusted(self):
        assert _api.api.genre_group({"kind": "theme", "name": "whatever"}) == "theme"
        assert _api.api.genre_group({"kind": "demographic", "name": "x"}) == "demographic"

    def test_by_name_demographic(self):
        assert _api.api.genre_group({"kind": "genre", "name": "Shounen"}) == "demographic"

    def test_by_name_theme(self):
        assert _api.api.genre_group({"kind": "", "name": "Mecha"}) == "theme"

    def test_default_genre(self):
        assert _api.api.genre_group({"name": "Comedy"}) == "genre"

    def test_none_input(self):
        assert _api.api.genre_group(None) == "genre"
        assert _api.api.genre_group({}) == "genre"

TestGenreGroup.__module__ = _api.__name__
_api.TestGenreGroup = TestGenreGroup
