# -*- coding: utf-8 -*-
"""Интеграционные тесты сквозных сценариев (несколько модулей вместе).

Проверяют, что модули стыкуются друг с другом:
  • Shikimori: клиент + фильтр + пагинация + локальная доводка + экспорт строки.
"""
import pytest

pytestmark = pytest.mark.integration


# ── Shikimori: клиент + фильтр + пагинация + экспорт ──────────────────────────
class TestShikimoriPipeline:
    def test_search_filter_export(self, monkeypatch):
        import shikimori_api as api
        from conftest import FakeResponse, FakeSession

        monkeypatch.setattr(api.time, "sleep", lambda s: None)

        def anime(i, score, year):
            return {"id": i, "name": f"Anime {i}", "russian": f"Аниме {i}",
                    "kind": "tv", "score": score, "status": "released",
                    "episodes": 12, "aired_on": f"{year}-01-01",
                    "image": {"preview": f"/im/{i}.jpg"}, "url": f"/animes/{i}"}

        # две страницы: первая полная (50), вторая частичная (конец выдачи)
        page1 = [anime(i, 8.5 if i % 2 else 5.0, 2015) for i in range(1, 51)]
        page2 = [anime(i, 9.0, 2015) for i in range(51, 55)]

        def handler(url, **kw):
            page = kw["params"]["page"]
            return FakeResponse(json_data={1: page1, 2: page2}.get(page, []))

        s = FakeSession(routes=[("/api/animes", handler)])
        client = api.ShikimoriApiClient(session=s)

        # серверные параметры уходят в запрос, локальный фильтр режет по score>=8
        flt = api.AnimeFilter(query="аниме", kind="tv", score_min=8.0,
                              year_from=2010, year_to=2020)
        params = flt.to_server_params()
        assert params["search"] == "аниме" and params["score"] == "8"

        results = api.find_anime(client, flt, per_page=50)
        # 25 нечётных из page1 (score 8.5) + 4 из page2 (score 9.0)
        assert len(results) == 29
        assert all(a.score >= 8.0 for a in results)
        assert all(flt.matches_local(a) for a in results)  # фильтр реально применён

        # экспорт строки для CSV/JSON
        row = results[0].as_row()
        assert row["title"].startswith("Аниме")
        assert row["year"] == 2015
        assert row["url"].startswith(api.DEFAULT_BASE_URL)

    def test_genres_graphql_then_group(self, monkeypatch):
        import shikimori_api as api
        from conftest import FakeResponse, FakeSession

        monkeypatch.setattr(api.time, "sleep", lambda s: None)
        s = FakeSession(routes=[("graphql", FakeResponse(json_data={"data": {"genres": [
            {"id": "1", "name": "Comedy", "russian": "Комедия", "kind": "genre"},
            {"id": "2", "name": "Mecha", "russian": "Меха", "kind": "theme"},
            {"id": "3", "name": "Shounen", "russian": "Сёнэн", "kind": "demographic"},
        ]}}))])
        client = api.ShikimoriApiClient(session=s)
        genres = client.genres("anime")
        groups = {g["name"]: api.genre_group(g) for g in genres}
        assert groups == {"Comedy": "genre", "Mecha": "theme",
                          "Shounen": "demographic"}


# ── настройки приложения: сохранение переживает «сбой» ───────────────────────
class TestSettingsResilience:
    def test_survives_corruption_via_bak(self):
        import utils
        utils.save_settings({"версия": 1, "папка": "C:/Видео"})
        utils.save_settings({"версия": 2, "папка": "D:/Кино"})
        # эмулируем обрыв записи основного файла
        with open(utils.SETTINGS_FILE, "w", encoding="utf-8") as f:
            f.write('{"версия": 2, "пап')  # обрезано
        loaded = utils.load_settings()
        # поднялись из .bak — прошлая валидная версия
        assert loaded == {"версия": 1, "папка": "C:/Видео"}

    def test_empty_save_never_wipes(self):
        import utils
        utils.save_settings({"важное": "значение"})
        for _ in range(3):
            utils.save_settings({})       # разовые сбои сборки настроек
            utils.save_settings(None)
        assert utils.load_settings() == {"важное": "значение"}
