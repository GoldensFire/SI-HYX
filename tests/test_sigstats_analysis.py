# -*- coding: utf-8 -*-
"""Тесты sigstats/analysis.py — датафреймы пакетов/тем/авторов."""
import pandas as pd
import pytest

from sigstats import analysis, db as sdb
from sigstats.normalize import normalize_name, normalize_theme

# Ключ группировки пересчитывается кодом из имени темы на лету (со стеммингом),
# поэтому «Музыка» → «музык», а не «музыка». Берём реальный ключ, а не хардкод.
MUSIC_KEY = normalize_theme("Музыка")


def _pkg(name, authors=("Автор",), qcount=100, group="Средние"):
    return {
        "sibrowser_id": "1", "name": name, "name_norm": normalize_name(name),
        "authors": list(authors), "download_count": 100,
        "question_count": qcount, "round_count": 3, "length_group": group,
        "size_mb": 1.0, "date_published": "2026-01-01",
        "tags": [], "categories": [{"name": "Аниме", "pct": 70, "slug": "anime"}],
        "pct_text": 25, "pct_photo": 25, "pct_audio": 25, "pct_video": 25,
    }


def _stats(started, completed, shown=10, answered=5, correct=3, wrong=2):
    return {
        "topLevelStats": {"startedGameCount": started,
                          "completedGameCount": completed},
        "questionStats": {"0:0:0": {"shownCount": shown, "answeredCount": answered,
                                    "correctCount": correct, "wrongCount": wrong}},
    }


@pytest.fixture
def populated(sigstats_db):
    """3 пакета: 2 со статистикой (разной), 1 без."""
    pid1 = sdb.upsert_package(sigstats_db, _pkg("Хороший пак", ("Ася", "Боря")))
    sdb.set_stats(sigstats_db, pid1, _stats(100, 80))
    sdb.replace_themes(sigstats_db, pid1, [
        {"round_index": 0, "round_name": "Р1", "theme_index": 0,
         "name": "🎶Музыка", "name_norm": "музыка"},
        {"round_index": 0, "round_name": "Р1", "theme_index": 1,
         "name": "Кино", "name_norm": "кино"},
    ])
    sdb.replace_questions(sigstats_db, pid1, [
        {"round_index": 0, "theme_index": 0, "question_index": 0,
         "price": 100, "text": "в", "answer": "о", "media": [],
         "duration_sec": 60.0},
    ])

    pid2 = sdb.upsert_package(sigstats_db, _pkg("Средний пак", ("Ася",)))
    sdb.set_stats(sigstats_db, pid2, _stats(100, 30))
    sdb.replace_themes(sigstats_db, pid2, [
        {"round_index": 0, "round_name": "Р1", "theme_index": 0,
         "name": "Музыка", "name_norm": "музыка"},
    ])

    pid3 = sdb.upsert_package(sigstats_db, _pkg("Без статистики", ("Вова",)))
    sdb.set_stats(sigstats_db, pid3, None)
    return sigstats_db, (pid1, pid2, pid3)


class TestLoadPackages:
    def test_empty_db(self, sigstats_db):
        df = analysis.load_packages(sigstats_db)
        assert df.empty

    def test_columns_computed(self, populated):
        conn, _ = populated
        df = analysis.load_packages(conn)
        assert len(df) == 3
        row = df[df["name"] == "Хороший пак"].iloc[0]
        assert row["completion_pct"] == pytest.approx(80.0)
        assert row["authors"] == ["Ася", "Боря"]
        assert row["cat_map"] == {"Аниме": 70}
        assert row["answer_pct"] == pytest.approx(50.0)
        assert row["duration_min"] == pytest.approx(1.0)
        assert row["duration_str"] == "1:00"

    def test_difficulty_label_applied(self, populated):
        conn, _ = populated
        df = analysis.load_packages(conn)
        assert df[df["name"] == "Хороший пак"].iloc[0]["difficulty"] == "средне"


class TestDifficultyLabel:
    @pytest.mark.parametrize("pct,label", [
        (80, "лёгкий"), (66, "лёгкий"),
        (65, "средне"), (45, "средне"),
        (44, "сложно"), (30, "сложно"),
        (29, "оч. сложно"), (0, "оч. сложно"),
    ])
    def test_labels(self, pct, label):
        assert analysis._difficulty_label(pct) == label

    def test_none(self):
        assert analysis._difficulty_label(None) is None
        assert analysis._difficulty_label(float("nan")) is None


class TestFmtDuration:
    def test_minutes(self):
        assert analysis._fmt_duration(125) == "2:05"

    def test_hours(self):
        assert analysis._fmt_duration(3725) == "1:02:05"

    def test_none_nan(self):
        assert analysis._fmt_duration(None) == "—"
        assert analysis._fmt_duration(float("nan")) == "—"

    def test_zero(self):
        assert analysis._fmt_duration(0) == "0:00"


class TestThemeTable:
    def test_empty_db(self, sigstats_db):
        assert analysis.theme_table(sigstats_db).empty

    def test_aggregation(self, populated):
        conn, _ = populated
        t = analysis.theme_table(conn)
        music = t[t["name_norm"] == MUSIC_KEY].iloc[0]
        assert music["n_packages"] == 2
        assert music["theme"] == "🎶Музыка"  # вариант с эмодзи предпочтён
        assert music["share"] == pytest.approx(2 / 3)
        assert music["avg_completion"] == pytest.approx((0.8 + 0.3) / 2)
        assert music["rarity"] == "частая"
        kino = t[t["name_norm"] == normalize_theme("Кино")].iloc[0]
        assert kino["n_packages"] == 1

    def test_sorted_by_popularity(self, populated):
        conn, _ = populated
        t = analysis.theme_table(conn)
        assert t.iloc[0]["n_packages"] >= t.iloc[-1]["n_packages"]


class TestPackagesWithTheme:
    def test_found(self, populated):
        conn, _ = populated
        df = analysis.packages_with_theme(conn, MUSIC_KEY)
        assert len(df) == 2
        assert set(df["Название"]) == {"Хороший пак", "Средний пак"}
        # сортировка по завершённости
        assert df.iloc[0]["Название"] == "Хороший пак"

    def test_not_found(self, populated):
        conn, _ = populated
        df = analysis.packages_with_theme(conn, "несуществующая тема")
        assert df.empty

    def test_empty_db(self, sigstats_db):
        assert analysis.packages_with_theme(sigstats_db, "музыка").empty


class TestAuthorTable:
    def test_empty(self, sigstats_db):
        assert analysis.author_table(sigstats_db).empty

    def test_aggregation(self, populated):
        conn, _ = populated
        a = analysis.author_table(conn)
        asya = a[a["author"] == "Ася"].iloc[0]
        assert asya["packages"] == 2
        assert asya["with_stats"] == 2
        assert asya["avg_completion"] == pytest.approx(0.55)
        borya = a[a["author"] == "Боря"].iloc[0]
        assert borya["packages"] == 1
        vova = a[a["author"] == "Вова"].iloc[0]
        assert vova["with_stats"] == 0


class TestPackageQuestionsThemes:
    def test_questions(self, populated):
        conn, (pid1, *_ ) = populated
        q = analysis.package_questions(conn, pid1)
        assert len(q) == 1
        assert q.iloc[0]["price"] == 100
        assert q.iloc[0]["duration_sec"] == 60.0

    def test_questions_empty(self, populated):
        conn, (_, _, pid3) = populated
        assert analysis.package_questions(conn, pid3).empty

    def test_themes_ordered(self, populated):
        conn, (pid1, *_ ) = populated
        t = analysis.package_themes(conn, pid1)
        assert list(t["theme_index"]) == [0, 1]
        assert list(t["name"]) == ["🎶Музыка", "Кино"]


class TestCategoryNames:
    def test_names(self, populated):
        conn, _ = populated
        df = analysis.load_packages(conn)
        assert analysis.category_names(df) == ["Аниме"]

    def test_empty_df(self):
        assert analysis.category_names(pd.DataFrame()) == []
