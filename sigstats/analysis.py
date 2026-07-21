"""Аналитика поверх БД: датафреймы пакетов и тем с поправкой на длину пакета."""
from __future__ import annotations
import json
import sqlite3

import pandas as pd

from . import config
from .normalize import pick_display_variant, normalize_theme


def load_packages(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM packages", conn)
    if df.empty:
        return df
    df["completion_pct"] = df["completion_rate"] * 100
    df["authors"] = df["authors_json"].apply(
        lambda s: json.loads(s) if s else [])
    df["tags"] = df["tags_json"].apply(lambda s: json.loads(s) if s else [])
    # категории: список [{name,pct}] и быстрый словарь name->pct
    df["categories"] = df["categories_json"].apply(
        lambda s: json.loads(s) if s else [])
    df["cat_map"] = df["categories"].apply(
        lambda lst: {c["name"]: (c.get("pct") or 0) for c in lst})
    # проценты попыток ответа и правильных ответов
    df["answer_pct"] = df["answer_rate"] * 100
    df["correct_pct"] = df["correct_rate"] * 100
    # сложность пака по доле попыток ответа: чем реже пытаются отвечать, тем
    # вопросы воспринимаются сложнее (готовы поставить сложность правильных
    # ответов на второй план — «сложно» тут значит «не рискуют отвечать»).
    df["difficulty"] = df["answer_pct"].apply(_difficulty_label)
    # длительность пакета (если посчитана из .siq): в минутах и в виде мм:сс
    if "duration_sec" not in df.columns:
        df["duration_sec"] = pd.NA
    df["duration_min"] = pd.to_numeric(df["duration_sec"], errors="coerce") / 60
    df["duration_str"] = df["duration_sec"].apply(_fmt_duration)
    if "modern_codec_share" not in df.columns:
        df["modern_codec_share"] = pd.NA
    return df


def _difficulty_label(answer_pct) -> str | None:
    if answer_pct is None or pd.isna(answer_pct):
        return None
    if answer_pct > 65:
        return "лёгкий"
    if answer_pct >= 45:
        return "средне"
    if answer_pct >= 30:
        return "сложно"
    return "оч. сложно"


def _fmt_duration(sec) -> str:
    if sec is None or (isinstance(sec, float) and pd.isna(sec)) or pd.isna(sec):
        return "—"
    sec = int(round(float(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def category_names(df: pd.DataFrame) -> list[str]:
    """Все встречающиеся названия категорий (для фильтра)."""
    names: set[str] = set()
    for lst in df.get("categories", []):
        for c in lst:
            if c.get("name"):
                names.add(c["name"])
    return sorted(names)


def packages_with_theme(conn: sqlite3.Connection, name_norm: str) -> pd.DataFrame:
    """Пакеты, содержащие тему (по пересчитанному на лету ключу нормализации).

    Ключ пересчитывается из t.name, чтобы отражать актуальную логику группировки
    (в БД name_norm может быть устаревшим).
    """
    df = pd.read_sql_query(
        """
        SELECT p.id AS pid, p.name AS "Название", p.authors_display AS "Авторы",
               p.question_count AS "Вопр.", p.length_group AS "Группа",
               p.completion_rate*100 AS "% завершения",
               t.name AS "Тема в паке"
        FROM themes t JOIN packages p ON p.id = t.package_id
        """,
        conn,
    )
    if df.empty:
        return df.drop(columns=["pid"], errors="ignore")
    df["_norm"] = df["Тема в паке"].map(normalize_theme)
    df = df[df["_norm"] == name_norm]
    df = (df.sort_values("% завершения", ascending=False, na_position="last")
            .drop_duplicates("pid")
            .drop(columns=["pid", "_norm"]))
    return df.reset_index(drop=True)


def theme_table(conn: sqlite3.Connection) -> pd.DataFrame:
    """Сводка по темам (по нормализованному ключу).

    Колонки: тема (для показа), в скольких пакетах, доля, средняя завершённость,
    редкость.
    """
    total_packages = conn.execute("SELECT COUNT(*) FROM packages").fetchone()[0]
    if not total_packages:
        return pd.DataFrame()

    # одна строка на (пакет, тема) — без дублей тем внутри пакета.
    rows = pd.read_sql_query(
        """
        SELECT t.name        AS variant,
               t.package_id,
               p.completion_rate,
               p.has_stats,
               p.length_group,
               p.completion_rate IS NOT NULL AS has_rate
        FROM themes t
        JOIN packages p ON p.id = t.package_id
        """,
        conn,
    )
    if rows.empty:
        return pd.DataFrame()
    # ключ группировки пересчитываем из имени — отражает актуальную нормализацию
    rows["name_norm"] = rows["variant"].map(normalize_theme)

    # уникальные пары (тема, пакет)
    uniq = rows.drop_duplicates(["name_norm", "package_id"])

    agg = uniq.groupby("name_norm").agg(
        n_packages=("package_id", "nunique"),
        n_with_stats=("has_stats", "sum"),
        avg_completion=("completion_rate", "mean"),
    ).reset_index()

    # отображаемое написание темы: вариант с эмодзи / самый длинный
    variants = (uniq.groupby("name_norm")["variant"]
                .apply(lambda s: pick_display_variant(list(s))))
    agg = agg.merge(variants.rename("theme").reset_index(), on="name_norm")

    agg["share"] = agg["n_packages"] / total_packages
    agg["share_pct"] = agg["share"] * 100          # доля в процентах (для показа)
    agg["avg_completion_pct"] = agg["avg_completion"] * 100

    def rarity(share: float) -> str:
        if share < config.RARE_THEME_MAX:
            return "редкая"
        if share > config.FREQUENT_THEME_MIN:
            return "частая"
        return "средняя"

    agg["rarity"] = agg["share"].apply(rarity)
    agg = agg.sort_values(["n_packages", "avg_completion_pct"],
                          ascending=[False, False]).reset_index(drop=True)
    return agg


def author_table(conn: sqlite3.Connection) -> pd.DataFrame:
    """Топ авторов по средней завершённости их паков.

    Учитываются только паки со статистикой.
    """
    df = pd.read_sql_query(
        "SELECT id, authors_json, completion_rate, has_stats, length_group, "
        "started_games FROM packages", conn)
    if df.empty:
        return pd.DataFrame()

    rows = []
    for _, r in df.iterrows():
        for a in (json.loads(r["authors_json"]) if r["authors_json"] else []):
            rows.append({
                "author": a,
                "completion_rate": r["completion_rate"],
                "has_stats": r["has_stats"],
                "started": r["started_games"] or 0,
            })
    a = pd.DataFrame(rows)
    if a.empty:
        return a

    g = a.groupby("author").agg(
        packages=("author", "size"),
        with_stats=("has_stats", "sum"),
        avg_completion=("completion_rate", "mean"),
        total_started=("started", "sum"),
    ).reset_index()
    g["avg_completion_pct"] = g["avg_completion"] * 100
    g = g.sort_values(["avg_completion_pct", "packages"],
                      ascending=[False, False], na_position="last").reset_index(drop=True)
    return g


def package_questions(conn: sqlite3.Connection, package_id: int) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT round_index, theme_index, question_index, price, text, answer,
                  media_json, answer_media_json, shown_count, answered_count,
                  correct_count, wrong_count, duration_sec
           FROM questions WHERE package_id=?
           ORDER BY round_index, theme_index, question_index""",
        conn, params=(package_id,),
    )


def package_themes(conn: sqlite3.Connection, package_id: int) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT round_index, round_name, theme_index, name
           FROM themes WHERE package_id=?
           ORDER BY round_index, theme_index""",
        conn, params=(package_id,),
    )
