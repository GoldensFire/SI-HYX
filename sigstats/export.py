"""Сборка текстового дампа для скармливания нейросети."""
from __future__ import annotations
import pandas as pd


def build_packages_dump(df: pd.DataFrame, top_n: int = 100,
                        only_with_stats: bool = True) -> str:
    """Готовит компактный текст по пакетам для анализа нейросетью."""
    d = df.copy()
    if only_with_stats:
        d = d[d["has_stats"] == 1]
    d = d.sort_values("completion_rate", ascending=False, na_position="last")
    d = d.head(top_n)

    lines = [
        "СТАТИСТИКА ПАКЕТОВ «СВОЯ ИГРА» (sibrowser.ru + SIStatistics)",
        "Метрика качества = % завершённых игр (completed/started): насколько пак "
        "«дожимают» до конца.",
        "ВАЖНО: короткие паки завершают чаще. Для честного сравнения указан "
        "перцентиль завершённости ВНУТРИ группы длины (0–100, выше = лучше "
        "своих по размеру).",
        f"Пакетов в выборке: {len(d)}",
        "=" * 70,
    ]
    for i, (_, r) in enumerate(d.iterrows(), 1):
        authors = ", ".join(r["authors"]) if isinstance(r["authors"], list) else ""
        comp = f"{r['completion_pct']:.1f}%" if pd.notna(r["completion_pct"]) else "—"
        pct = (f"{r['completion_rank_in_group']:.0f}"
               if pd.notna(r["completion_rank_in_group"]) else "—")
        started = int(r["started_games"]) if pd.notna(r["started_games"]) else 0
        completed = int(r["completed_games"]) if pd.notna(r["completed_games"]) else 0
        lines.append(
            f"\n[{i}] «{r['name']}» | Автор: {authors or '—'}\n"
            f"    Вопросов: {r['question_count']} (группа: {r['length_group']}) | "
            f"Скачиваний: {r['download_count']}\n"
            f"    Игр: {started} начато / {completed} завершено = {comp} "
            f"(перцентиль в группе: {pct})"
        )
    return "\n".join(lines)


def build_theme_dump(themes: pd.DataFrame, top_n: int = 60,
                     min_packages: int = 2) -> str:
    """Текст по темам: где какие темы встречаются и как они «заходят»."""
    d = themes[themes["n_packages"] >= min_packages].copy()
    d = d.sort_values("avg_pct_in_group", ascending=False, na_position="last")
    d = d.head(top_n)
    lines = [
        "ТЕМЫ И ИХ КАЧЕСТВО (агрегировано по всем пакетам)",
        "avg_pct_in_group = средний перцентиль завершённости пакетов с этой темой "
        "(с поправкой на длину).",
        "Чем выше и чем чаще встречается — тем «надёжнее» тема.",
        "=" * 70,
    ]
    for _, r in d.iterrows():
        comp = (f"{r['avg_completion_pct']:.0f}%"
                if pd.notna(r["avg_completion_pct"]) else "—")
        pct = (f"{r['avg_pct_in_group']:.0f}"
               if pd.notna(r["avg_pct_in_group"]) else "—")
        lines.append(
            f"• {r['theme']} — пакетов: {r['n_packages']} ({r['rarity']}), "
            f"ср. завершённость: {comp}, перцентиль: {pct}"
        )
    return "\n".join(lines)
