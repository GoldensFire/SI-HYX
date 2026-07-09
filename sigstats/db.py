"""SQLite-хранилище: пакеты, темы, вопросы. Кэш + дедупликация по названию."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS packages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sibrowser_id    TEXT,
    name            TEXT NOT NULL,
    name_norm       TEXT NOT NULL UNIQUE,         -- ключ дедупликации (по названию)
    authors_json    TEXT,
    authors_display TEXT,
    download_count  INTEGER,
    question_count  INTEGER,
    round_count     INTEGER,
    length_group    TEXT,
    size_mb         REAL,
    date_published  TEXT,
    tags_json       TEXT,
    categories_json TEXT,
    pct_text        INTEGER,
    pct_photo       INTEGER,
    pct_audio       INTEGER,
    pct_video       INTEGER,
    -- статистика игр
    stats_checked   INTEGER DEFAULT 0,
    has_stats       INTEGER DEFAULT 0,
    started_games   INTEGER,
    completed_games INTEGER,
    completion_rate REAL,                         -- completed / started
    -- .siq
    siq_downloaded  INTEGER DEFAULT 0,
    siq_path        TEXT,
    collected_at    TEXT
);

CREATE TABLE IF NOT EXISTS themes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id   INTEGER NOT NULL,
    round_index  INTEGER,
    round_name   TEXT,
    theme_index  INTEGER,
    name         TEXT,        -- оригинал (с эмодзи)
    name_norm    TEXT,        -- ключ группировки
    source       TEXT,        -- 'sibrowser' | 'siq'
    FOREIGN KEY (package_id) REFERENCES packages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS questions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id     INTEGER NOT NULL,
    round_index    INTEGER,
    theme_index    INTEGER,
    question_index INTEGER,
    price          INTEGER,
    text           TEXT,
    answer         TEXT,
    media_json     TEXT,      -- [{type, ref, embedded, path}]
    shown_count    INTEGER,
    answered_count INTEGER,
    correct_count  INTEGER,
    wrong_count    INTEGER,
    FOREIGN KEY (package_id) REFERENCES packages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_themes_pkg   ON themes(package_id);
CREATE INDEX IF NOT EXISTS idx_themes_norm  ON themes(name_norm);
CREATE INDEX IF NOT EXISTS idx_q_pkg        ON questions(package_id);
"""


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Лёгкая миграция: добавляет недостающие колонки в существующую БД."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(packages)")}
    for col, decl in (("answer_rate", "REAL"), ("correct_rate", "REAL"),
                      ("duration_sec", "REAL"), ("modern_codec_share", "REAL")):
        if col not in cols:
            conn.execute(f"ALTER TABLE packages ADD COLUMN {col} {decl}")
    qcols = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    if "duration_sec" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN duration_sec REAL")
    if "answer_media_json" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN answer_media_json TEXT")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _ensure_columns(conn)


def package_exists(conn: sqlite3.Connection, name_norm: str) -> bool:
    cur = conn.execute("SELECT 1 FROM packages WHERE name_norm = ? LIMIT 1", (name_norm,))
    return cur.fetchone() is not None


def existing_name_norms(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name_norm FROM packages")}


def upsert_package(conn: sqlite3.Connection, pkg: dict[str, Any]) -> int:
    """Вставляет пакет (или возвращает id существующего по name_norm)."""
    cur = conn.execute(
        "SELECT id FROM packages WHERE name_norm = ?", (pkg["name_norm"],)
    )
    row = cur.fetchone()
    fields = dict(
        sibrowser_id=pkg.get("sibrowser_id"),
        name=pkg.get("name"),
        name_norm=pkg.get("name_norm"),
        authors_json=json.dumps(pkg.get("authors", []), ensure_ascii=False),
        authors_display=", ".join(pkg.get("authors", []) or []),
        download_count=pkg.get("download_count"),
        question_count=pkg.get("question_count"),
        round_count=pkg.get("round_count"),
        length_group=pkg.get("length_group"),
        size_mb=pkg.get("size_mb"),
        date_published=pkg.get("date_published"),
        tags_json=json.dumps(pkg.get("tags", []), ensure_ascii=False),
        categories_json=json.dumps(pkg.get("categories", []), ensure_ascii=False),
        pct_text=pkg.get("pct_text"),
        pct_photo=pkg.get("pct_photo"),
        pct_audio=pkg.get("pct_audio"),
        pct_video=pkg.get("pct_video"),
        collected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    if row:
        pid = row[0]
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        conn.execute(f"UPDATE packages SET {sets} WHERE id = :id", {**fields, "id": pid})
        return pid
    cols = ", ".join(fields)
    ph = ", ".join(f":{k}" for k in fields)
    cur = conn.execute(f"INSERT INTO packages ({cols}) VALUES ({ph})", fields)
    return cur.lastrowid


def set_stats(conn: sqlite3.Connection, package_id: int, stats: dict | None) -> None:
    """Сохраняет результат запроса статистики (или отметку «нет данных»)."""
    if stats is None:
        conn.execute(
            "UPDATE packages SET stats_checked=1, has_stats=0, started_games=NULL, "
            "completed_games=NULL, completion_rate=NULL, answer_rate=NULL, "
            "correct_rate=NULL WHERE id=?",
            (package_id,),
        )
        return
    top = stats.get("topLevelStats", {}) or {}
    started = top.get("startedGameCount") or 0
    completed = top.get("completedGameCount") or 0
    rate = (completed / started) if started else None

    # агрегаты по вопросам — доступны прямо из ответа API, без .siq
    qstats = stats.get("questionStats", {}) or {}
    tot_shown = tot_ans = tot_cor = tot_wrong = 0
    for qs in qstats.values():
        tot_shown += qs.get("shownCount") or 0
        tot_ans += qs.get("answeredCount") or 0
        tot_cor += qs.get("correctCount") or 0
        tot_wrong += qs.get("wrongCount") or 0
    answer_rate = (tot_ans / tot_shown) if tot_shown else None      # % попыток ответа
    # Деноминатор — (correctCount+wrongCount), НЕ shownCount — та же формула,
    # что использует официальный клиент SIOnline (PackageView.tsx:
    # getQuestionStats) и теперь auto_stats.py (siquester): доля правильных
    # СРЕДИ ОТВЕЧЕННЫХ попыток, а не среди всех показов. Раньше здесь
    # сознательно был shownCount как более стабильная база (в SIGame на один
    # вопрос бывает несколько попыток), но по просьбе — привести к формуле
    # sionline везде.
    tot_tries = tot_cor + tot_wrong
    correct_rate = (tot_cor / tot_tries) if tot_tries else None

    conn.execute(
        "UPDATE packages SET stats_checked=1, has_stats=1, started_games=?, "
        "completed_games=?, completion_rate=?, answer_rate=?, correct_rate=? WHERE id=?",
        (started, completed, rate, answer_rate, correct_rate, package_id),
    )
    # обновляем per-question статистику, если вопросы уже загружены из .siq
    qstats = stats.get("questionStats", {}) or {}
    for key, qs in qstats.items():
        try:
            r, t, q = (int(x) for x in key.split(":"))
        except ValueError:
            continue
        conn.execute(
            "UPDATE questions SET shown_count=?, answered_count=?, correct_count=?, "
            "wrong_count=? WHERE package_id=? AND round_index=? AND theme_index=? "
            "AND question_index=?",
            (qs.get("shownCount"), qs.get("answeredCount"), qs.get("correctCount"),
             qs.get("wrongCount"), package_id, r, t, q),
        )


def replace_themes(conn: sqlite3.Connection, package_id: int, themes: Iterable[dict]) -> None:
    conn.execute("DELETE FROM themes WHERE package_id=?", (package_id,))
    conn.executemany(
        "INSERT INTO themes (package_id, round_index, round_name, theme_index, "
        "name, name_norm, source) VALUES (?,?,?,?,?,?,?)",
        [(package_id, t.get("round_index"), t.get("round_name"), t.get("theme_index"),
          t.get("name"), t.get("name_norm"), t.get("source", "sibrowser")) for t in themes],
    )


def replace_questions(conn: sqlite3.Connection, package_id: int, questions: Iterable[dict]) -> None:
    questions = list(questions)
    conn.execute("DELETE FROM questions WHERE package_id=?", (package_id,))
    conn.executemany(
        "INSERT INTO questions (package_id, round_index, theme_index, question_index, "
        "price, text, answer, media_json, duration_sec, answer_media_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(package_id, q.get("round_index"), q.get("theme_index"), q.get("question_index"),
          q.get("price"), q.get("text"), q.get("answer"),
          json.dumps(q.get("media", []), ensure_ascii=False),
          q.get("duration_sec"),
          json.dumps(q.get("answer_media", []), ensure_ascii=False)) for q in questions],
    )
    # длительность пакета = сумма длительностей вопросов (если посчитаны)
    durs = [q.get("duration_sec") for q in questions if q.get("duration_sec") is not None]
    total = round(sum(durs), 1) if durs else None
    share = _modern_codec_share(questions)
    conn.execute("UPDATE packages SET duration_sec=?, modern_codec_share=? WHERE id=?",
                 (total, share, package_id))


def _modern_codec_share(questions: list[dict]) -> float | None:
    """Доля вопросов с видео в современном кодеке (hevc/av1/vvc) от всех вопросов."""
    if not questions:
        return None
    return round(sum(1 for q in questions if q.get("video_modern")) / len(questions), 4)


def set_durations(conn: sqlite3.Connection, package_id: int,
                  questions: Iterable[dict]) -> None:
    """Обновляет только длительности (не трогая статистику вопросов).

    Используется при пересчёте длительности уже скачанных паков из локальных
    .siq, чтобы не потерять shown/answered/correct из статистики.
    """
    questions = list(questions)
    for q in questions:
        conn.execute(
            "UPDATE questions SET duration_sec=?, media_json=?, answer_media_json=? "
            "WHERE package_id=? AND round_index=? AND theme_index=? AND "
            "question_index=?",
            (q.get("duration_sec"),
             json.dumps(q.get("media", []), ensure_ascii=False),
             json.dumps(q.get("answer_media", []), ensure_ascii=False),
             package_id, q.get("round_index"),
             q.get("theme_index"), q.get("question_index")),
        )
    durs = [q.get("duration_sec") for q in questions if q.get("duration_sec") is not None]
    total = round(sum(durs), 1) if durs else None
    share = _modern_codec_share(questions)
    conn.execute("UPDATE packages SET duration_sec=?, modern_codec_share=? WHERE id=?",
                 (total, share, package_id))


def mark_siq(conn: sqlite3.Connection, package_id: int, path: str | None) -> None:
    conn.execute(
        "UPDATE packages SET siq_downloaded=?, siq_path=? WHERE id=?",
        (1 if path else 0, path, package_id),
    )


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Сводка по содержимому БД для шапки интерфейса."""
    one = lambda q: conn.execute(q).fetchone()[0]
    return {
        "packages": one("SELECT COUNT(*) FROM packages"),
        "with_stats": one("SELECT COUNT(*) FROM packages WHERE has_stats=1"),
        "with_siq": one("SELECT COUNT(*) FROM packages WHERE siq_downloaded=1"),
        "themes": one("SELECT COUNT(DISTINCT name_norm) FROM themes"),
        "questions": one("SELECT COUNT(*) FROM questions"),
    }
