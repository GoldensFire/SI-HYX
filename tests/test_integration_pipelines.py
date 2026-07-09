# -*- coding: utf-8 -*-
"""Интеграционные тесты сквозных сценариев (несколько модулей вместе).

Проверяют, что модули стыкуются друг с другом:
  • sibrowser HTML → БД → аналитика → текстовый дамп;
  • .siq (zip) → parse_siq → БД → длительность в аналитике;
  • Shikimori: клиент + фильтр + пагинация + локальная доводка + экспорт строки.
"""
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


# ── sibrowser → db → analysis → export ───────────────────────────────────────
class TestSibrowserToAnalysisPipeline:
    def _card_html(self, pid, name, downloads, qcount, theme):
        return f"""
<article itemprop="itemListElement">
  <a href="/packages/{pid}"><h1>{name}</h1></a>
  <span itemprop="author"><span itemprop="name">Автор {pid}</span></span>
  <time datetime="2026-01-0{pid}">дата</time>
  <span itemprop="contentSize">10 МБ</span>
  <span data-packages--download_link--component-target="count">{downloads}</span>
  <table><tr><td>Всего</td><td>{qcount} вопросов</td></tr>
    <tr><td>Текст</td><td>50%</td></tr></table>
  <a rel="category" href="/categories/anime"><span>Аниме</span><span>90%</span></a>
  <div><h2>Темы в раундах</h2>Р1: <span class="text-neutral-500">{theme}</span></div>
</article>"""

    def test_full_pipeline(self, sigstats_db):
        from sigstats import sibrowser as sb
        from sigstats import db as sdb
        from sigstats import analysis, export, stats_api

        # 1) парсим карточки каталога
        html = "<html><body>" + self._card_html(
            1, "Аниме пак", "5 000", 100, "🎶Музыка"
        ) + self._card_html(2, "Кино пак", "3 000", 60, "Музыка") + "</body></html>"
        cards = sb.parse_list(html)
        assert len(cards) == 2

        # 2) кладём в БД (upsert + темы) и вешаем статистику
        stats_map = {
            "Аниме пак": {"topLevelStats": {"startedGameCount": 200,
                                            "completedGameCount": 160},
                          "questionStats": {}},
            "Кино пак": {"topLevelStats": {"startedGameCount": 100,
                                           "completedGameCount": 20},
                         "questionStats": {}},
        }
        for card in cards:
            pid = sdb.upsert_package(sigstats_db, card.as_package())
            sdb.replace_themes(sigstats_db, pid, card.themes)
            summary_stats = stats_map[card.name]
            sdb.set_stats(sigstats_db, pid, summary_stats)

        # 3) аналитика поверх БД
        df = analysis.load_packages(sigstats_db)
        assert len(df) == 2
        top = df.sort_values("completion_rate", ascending=False).iloc[0]
        assert top["name"] == "Аниме пак"
        assert top["completion_pct"] == pytest.approx(80.0)

        themes = analysis.theme_table(sigstats_db)
        from sigstats.normalize import normalize_theme
        music = themes[themes["name_norm"] == normalize_theme("Музыка")].iloc[0]
        assert music["n_packages"] == 2          # оба пака свелись к одной теме
        assert music["theme"] == "🎶Музыка"       # показывается вариант с эмодзи

        authors = analysis.author_table(sigstats_db)
        assert set(authors["author"]) == {"Автор 1", "Автор 2"}

        # 4) текстовый дамп для нейросети
        dump = export.build_packages_dump(df)
        assert "Аниме пак" in dump and "Кино пак" in dump
        theme_dump = export.build_theme_dump(themes, min_packages=1)
        assert "🎶Музыка" in theme_dump

    def test_dedup_across_runs(self, sigstats_db):
        """Повторный сбор того же пака не создаёт дубль (UNIQUE name_norm)."""
        from sigstats import sibrowser as sb
        from sigstats import db as sdb

        html = "<html><body>" + self._card_html(
            1, "Дубль", "5 000", 100, "Тема") + "</body></html>"
        for _ in range(2):  # два прогона сбора
            for card in sb.parse_list(html):
                sdb.upsert_package(sigstats_db, card.as_package())
        n = sigstats_db.execute("SELECT COUNT(*) FROM packages").fetchone()[0]
        assert n == 1


# ── .siq (zip) → parse_siq → db → analysis ───────────────────────────────────
class TestSiqToDbPipeline:
    V5 = """<?xml version="1.0" encoding="utf-8"?>
<package name="Пак из архива" version="5">
  <rounds><round name="Р1"><themes>
    <theme name="Тема🎬">
      <questions>
        <question price="100">
          <params><param name="question" type="content">
            <item>Первый вопрос это про кино</item></param></params>
          <right><answer>Ответ 1</answer></right>
        </question>
        <question price="200">
          <params><param name="question" type="content">
            <item type="image" isRef="True">shot.png</item></param></params>
          <right><answer>Ответ 2</answer></right>
        </question>
      </questions>
    </theme>
  </themes></round></rounds>
</package>"""

    def test_download_parse_store(self, sigstats_db, tmp_path, monkeypatch):
        from sigstats import siq, db as sdb, config as scfg
        from conftest import FakeResponse, FakeSession

        monkeypatch.setattr(scfg, "MEDIA_DIR", Path(tmp_path / "media"))
        monkeypatch.setattr(scfg, "PACKAGES_DIR", Path(tmp_path / "packages"))
        monkeypatch.setattr(siq, "_probe_duration", lambda p: 8.0)
        siq._DURATION_CACHE.clear()

        # 1) собираем настоящий .siq-архив и «скачиваем» его фейковой сессией
        raw = tmp_path / "src.siq"
        with zipfile.ZipFile(raw, "w") as zf:
            zf.writestr("content.xml", self.V5)
            zf.writestr("Images/shot.png", b"\x89PNG")
        s = FakeSession(routes=[("direct_download",
                                 FakeResponse(content=raw.read_bytes()))])
        dl = siq.download_siq(s, "77", "Пак из архива")
        assert dl is not None

        # 2) читаем имя и разбираем содержимое
        assert siq.read_package_name(dl) == "Пак из архива"
        themes, questions = siq.parse_siq(dl, package_id=1)
        assert len(themes) == 1 and len(questions) == 2

        # 3) кладём в БД и проверяем, что длительность посчиталась
        pkg = {"name": "Пак из архива", "name_norm": "пак из архива",
               "authors": ["Автор"], "question_count": 2, "length_group": "Короткие"}
        pid = sdb.upsert_package(sigstats_db, pkg)
        sdb.replace_themes(sigstats_db, pid, themes)
        sdb.replace_questions(sigstats_db, pid, questions)

        from sigstats import analysis
        q_df = analysis.package_questions(sigstats_db, pid)
        assert len(q_df) == 2
        # текстовый вопрос + картинка (5 с) + текстовые ответы — сумма > 0
        row = sigstats_db.execute(
            "SELECT duration_sec FROM packages WHERE id=?", (pid,)).fetchone()
        assert row["duration_sec"] and row["duration_sec"] > 0

        t_df = analysis.package_themes(sigstats_db, pid)
        assert t_df.iloc[0]["name"] == "Тема🎬"


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
