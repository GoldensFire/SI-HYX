# -*- coding: utf-8 -*-
"""Тесты sigstats/config.py (пути, группы длины, json-хранилища)
и sigstats/db.py (SQLite-хранилище)."""
import json
import sqlite3

import pytest

from sigstats import config as scfg
from sigstats import db as sdb


# ── length_group ─────────────────────────────────────────────────────────────
class TestLengthGroup:
    @pytest.mark.parametrize("n,expected", [
        (None, "Неизвестно"),
        (0, "Неизвестно"),
        (-5, "Неизвестно"),
        (1, "Короткие"),
        (80, "Короткие"),
        (81, "Средние"),
        (120, "Средние"),
        (121, "Полные"),
        (170, "Полные"),
        (171, "Большие"),
        (1000, "Большие"),
    ])
    def test_groups(self, n, expected):
        assert scfg.length_group(n) == expected

    def test_groups_listed(self):
        for n in (None, 10, 100, 150, 200):
            assert scfg.length_group(n) in scfg.LENGTH_GROUPS


# ── json-хранилища (пути подменены фикстурой sigstats_db) ────────────────────
class TestJsonStores:
    def test_blacklist_roundtrip(self, sigstats_db):
        assert scfg.load_author_blacklist() == []
        scfg.save_author_blacklist(["Автор1", "Автор2"])
        assert scfg.load_author_blacklist() == ["Автор1", "Автор2"]

    def test_blacklist_corrupted(self, sigstats_db):
        scfg.ensure_dirs()
        scfg.BLACKLIST_PATH.write_text("не json", encoding="utf-8")
        assert scfg.load_author_blacklist() == []

    def test_played_roundtrip(self, sigstats_db):
        assert scfg.load_played_packages() == []
        scfg.save_played_packages([1, 5, 9])
        assert scfg.load_played_packages() == [1, 5, 9]

    def test_package_blacklist_roundtrip(self, sigstats_db):
        assert scfg.load_package_blacklist() == []
        scfg.save_package_blacklist([2, 4, 8])
        assert scfg.load_package_blacklist() == [2, 4, 8]

    def test_package_blacklist_corrupted(self, sigstats_db):
        scfg.ensure_dirs()
        scfg.PKG_BLACKLIST_PATH.write_text("не json", encoding="utf-8")
        assert scfg.load_package_blacklist() == []

    def test_ui_settings_roundtrip(self, sigstats_db):
        assert scfg.load_ui_settings() == {}
        scfg.save_ui_settings({"фильтр": "аниме", "порог": 50})
        assert scfg.load_ui_settings() == {"фильтр": "аниме", "порог": 50}

    def test_search_cache(self, sigstats_db):
        assert scfg.get_cached_page("downloads", None) == 1
        scfg.set_cached_page("downloads", None, 7)
        scfg.set_cached_page("date", "anime", 3)
        assert scfg.get_cached_page("downloads", None) == 7
        assert scfg.get_cached_page("date", "anime") == 3
        assert scfg.get_cached_page("date", "music") == 1

    def test_search_cache_key(self):
        assert scfg._search_cache_key("downloads", None) == "downloads:-"
        assert scfg._search_cache_key("date", "anime") == "date:anime"

    def test_ensure_dirs(self, sigstats_db):
        scfg.ensure_dirs()
        assert scfg.PACKAGES_DIR.is_dir()
        assert scfg.MEDIA_DIR.is_dir()


# ── db.py ────────────────────────────────────────────────────────────────────
def _pkg(name="Тестовый пак", **kw):
    from sigstats.normalize import normalize_name
    base = {
        "sibrowser_id": "123",
        "name": name,
        "name_norm": normalize_name(name),
        "authors": ["Автор"],
        "download_count": 500,
        "question_count": 100,
        "round_count": 3,
        "length_group": "Средние",
        "size_mb": 42.5,
        "date_published": "2026-01-01",
        "tags": ["аниме"],
        "categories": [{"name": "Аниме", "pct": 80, "slug": "anime"}],
        "pct_text": 20, "pct_photo": 30, "pct_audio": 25, "pct_video": 25,
    }
    base.update(kw)
    return base


STATS = {
    "topLevelStats": {"startedGameCount": 100, "completedGameCount": 40},
    "questionStats": {
        "0:0:0": {"shownCount": 10, "answeredCount": 8,
                  "correctCount": 6, "wrongCount": 2},
        "0:0:1": {"shownCount": 10, "answeredCount": 2,
                  "correctCount": 1, "wrongCount": 3},
        # ключ не в формате r:t:q — пропускается при per-question апдейте.
        # Пустой словарь, чтобы не искажать агрегатные суммы shown/answered.
        "мусорный ключ": {},
    },
}


class TestDb:
    def test_schema_created(self, sigstats_db):
        tables = {r[0] for r in sigstats_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"packages", "themes", "questions"} <= tables

    def test_migration_columns(self, sigstats_db):
        cols = {r[1] for r in sigstats_db.execute("PRAGMA table_info(packages)")}
        assert {"answer_rate", "correct_rate", "duration_sec",
                "modern_codec_share"} <= cols
        qcols = {r[1] for r in sigstats_db.execute("PRAGMA table_info(questions)")}
        assert {"duration_sec", "answer_media_json"} <= qcols

    def test_upsert_insert(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        assert pid > 0
        row = sigstats_db.execute("SELECT * FROM packages WHERE id=?", (pid,)).fetchone()
        assert row["name"] == "Тестовый пак"
        assert json.loads(row["authors_json"]) == ["Автор"]
        assert row["authors_display"] == "Автор"
        assert row["length_group"] == "Средние"

    def test_upsert_dedup_by_name_norm(self, sigstats_db):
        pid1 = sdb.upsert_package(sigstats_db, _pkg())
        pid2 = sdb.upsert_package(sigstats_db, _pkg(download_count=999))
        assert pid1 == pid2
        row = sigstats_db.execute("SELECT download_count FROM packages").fetchone()
        assert row[0] == 999
        n = sigstats_db.execute("SELECT COUNT(*) FROM packages").fetchone()[0]
        assert n == 1

    def test_package_exists(self, sigstats_db):
        assert not sdb.package_exists(sigstats_db, "тестовый пак")
        sdb.upsert_package(sigstats_db, _pkg())
        assert sdb.package_exists(sigstats_db, "тестовый пак")

    def test_existing_name_norms(self, sigstats_db):
        sdb.upsert_package(sigstats_db, _pkg("Пак 1"))
        sdb.upsert_package(sigstats_db, _pkg("Пак 2"))
        assert sdb.existing_name_norms(sigstats_db) == {"пак 1", "пак 2"}

    def test_set_stats_none(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.set_stats(sigstats_db, pid, None)
        row = sigstats_db.execute(
            "SELECT stats_checked, has_stats, completion_rate FROM packages").fetchone()
        assert row["stats_checked"] == 1
        assert row["has_stats"] == 0
        assert row["completion_rate"] is None

    def test_set_stats_values(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.set_stats(sigstats_db, pid, STATS)
        row = sigstats_db.execute("SELECT * FROM packages").fetchone()
        assert row["started_games"] == 100
        assert row["completed_games"] == 40
        assert row["completion_rate"] == pytest.approx(0.4)
        # answer_rate = (8+2)/(10+10) = 0.5
        assert row["answer_rate"] == pytest.approx(0.5)
        # correct_rate = (6+1)/(6+2+1+3) — формула sionline
        assert row["correct_rate"] == pytest.approx(7 / 12)

    def test_set_stats_zero_started(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.set_stats(sigstats_db, pid, {"topLevelStats": {"startedGameCount": 0}})
        row = sigstats_db.execute("SELECT completion_rate, has_stats FROM packages").fetchone()
        assert row["completion_rate"] is None
        assert row["has_stats"] == 1

    def test_set_stats_updates_questions(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.replace_questions(sigstats_db, pid, [
            {"round_index": 0, "theme_index": 0, "question_index": 0,
             "price": 100, "text": "в1", "answer": "о1", "media": []},
            {"round_index": 0, "theme_index": 0, "question_index": 1,
             "price": 200, "text": "в2", "answer": "о2", "media": []},
        ])
        sdb.set_stats(sigstats_db, pid, STATS)
        rows = sigstats_db.execute(
            "SELECT question_index, shown_count, correct_count FROM questions "
            "ORDER BY question_index").fetchall()
        assert rows[0]["shown_count"] == 10 and rows[0]["correct_count"] == 6
        assert rows[1]["shown_count"] == 10 and rows[1]["correct_count"] == 1

    def test_replace_themes(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.replace_themes(sigstats_db, pid, [
            {"round_index": 0, "round_name": "Р1", "theme_index": 0,
             "name": "Тема", "name_norm": "тема"},
        ])
        sdb.replace_themes(sigstats_db, pid, [
            {"round_index": 0, "round_name": "Р1", "theme_index": 0,
             "name": "Новая", "name_norm": "новая", "source": "siq"},
        ])
        rows = sigstats_db.execute("SELECT name, source FROM themes").fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "Новая" and rows[0]["source"] == "siq"

    def test_replace_questions_duration_sum(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.replace_questions(sigstats_db, pid, [
            {"round_index": 0, "theme_index": 0, "question_index": 0,
             "price": 100, "text": "", "answer": "", "media": [],
             "duration_sec": 10.5, "video_modern": True},
            {"round_index": 0, "theme_index": 0, "question_index": 1,
             "price": 200, "text": "", "answer": "", "media": [],
             "duration_sec": 4.5},
        ])
        row = sigstats_db.execute(
            "SELECT duration_sec, modern_codec_share FROM packages").fetchone()
        assert row["duration_sec"] == pytest.approx(15.0)
        assert row["modern_codec_share"] == pytest.approx(0.5)

    def test_replace_questions_no_durations(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.replace_questions(sigstats_db, pid, [
            {"round_index": 0, "theme_index": 0, "question_index": 0,
             "price": 100, "text": "", "answer": "", "media": []},
        ])
        row = sigstats_db.execute("SELECT duration_sec FROM packages").fetchone()
        assert row["duration_sec"] is None

    def test_modern_codec_share_empty(self):
        assert sdb._modern_codec_share([]) is None

    def test_modern_codec_share_counts(self):
        qs = [{"video_modern": True}, {}, {"video_modern": False}, {"video_modern": True}]
        assert sdb._modern_codec_share(qs) == pytest.approx(0.5)

    def test_set_durations_preserves_stats(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.replace_questions(sigstats_db, pid, [
            {"round_index": 0, "theme_index": 0, "question_index": 0,
             "price": 100, "text": "в", "answer": "о", "media": []},
        ])
        sdb.set_stats(sigstats_db, pid, STATS)
        sdb.set_durations(sigstats_db, pid, [
            {"round_index": 0, "theme_index": 0, "question_index": 0,
             "duration_sec": 33.0, "media": [{"type": "image"}]},
        ])
        row = sigstats_db.execute(
            "SELECT duration_sec, shown_count FROM questions").fetchone()
        assert row["duration_sec"] == 33.0
        assert row["shown_count"] == 10  # статистика не потёрта
        prow = sigstats_db.execute("SELECT duration_sec FROM packages").fetchone()
        assert prow["duration_sec"] == 33.0

    def test_mark_siq(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.mark_siq(sigstats_db, pid, "C:/packs/a.siq")
        row = sigstats_db.execute(
            "SELECT siq_downloaded, siq_path FROM packages").fetchone()
        assert row["siq_downloaded"] == 1 and row["siq_path"] == "C:/packs/a.siq"
        sdb.mark_siq(sigstats_db, pid, None)
        row = sigstats_db.execute("SELECT siq_downloaded FROM packages").fetchone()
        assert row["siq_downloaded"] == 0

    def test_stats_summary(self, sigstats_db):
        pid1 = sdb.upsert_package(sigstats_db, _pkg("Пак 1"))
        pid2 = sdb.upsert_package(sigstats_db, _pkg("Пак 2"))
        sdb.set_stats(sigstats_db, pid1, STATS)
        sdb.mark_siq(sigstats_db, pid2, "x.siq")
        sdb.replace_themes(sigstats_db, pid1, [
            {"round_index": 0, "round_name": "Р", "theme_index": 0,
             "name": "Тема", "name_norm": "тема"},
            {"round_index": 0, "round_name": "Р", "theme_index": 1,
             "name": "Тема2", "name_norm": "тема"},  # тот же норм-ключ
        ])
        s = sdb.stats(sigstats_db)
        assert s["packages"] == 2
        assert s["with_stats"] == 1
        assert s["with_siq"] == 1
        assert s["themes"] == 1  # DISTINCT name_norm
        assert s["questions"] == 0

    def test_foreign_key_cascade(self, sigstats_db):
        pid = sdb.upsert_package(sigstats_db, _pkg())
        sdb.replace_themes(sigstats_db, pid, [
            {"round_index": 0, "round_name": "Р", "theme_index": 0,
             "name": "Т", "name_norm": "т"}])
        sigstats_db.execute("DELETE FROM packages WHERE id=?", (pid,))
        n = sigstats_db.execute("SELECT COUNT(*) FROM themes").fetchone()[0]
        assert n == 0
