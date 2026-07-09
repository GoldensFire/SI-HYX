"""Автоматическое получение статистики пакета с SIStatistics — без ручной
вставки HTML со страницы SIGame (см. main_window._open_siq_file/_auto_fetch_stats).

Использует тот же сервис и логику сопоставления имя+авторы, что и вкладка
«Поиск пакетов» (sigstats/stats_api.py) — переиспользуем её напрямую, а не
дублируем.
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sigstats import stats_api as _stats_api


def fetch(name: str, authors: list[str]):
    """Возвращает (summary, per_question) или None, если пакет не найден в
    статистике (не залит на SIStatistics/сыгран 0 раз).

    summary — как sigstats.stats_api.summarize(): started/completed/rate.
    per_question — {(round_idx, theme_idx, question_idx): {"tries": 0..100, "right": 0..100}}.
    Индексы — порядковые (как в XML пакета), НЕ цена — сопоставление с
    round_name/theme_name/price делает вызывающий код (main_window.py), т.к.
    там же есть исходный siq.rounds для построения карты индексов.

    Формулы — точь-в-точь как в официальном клиенте SIOnline
    (PackageView.tsx: getQuestionStats): tries% = answeredCount/shownCount,
    right% = correctCount/(correctCount+wrongCount) — доля правильных СРЕДИ
    ОТВЕЧЕННЫХ попыток, а не среди всех показов (в отличие от sigstats/db.py,
    где для агрегата по списку пакетов сознательно взят более стабильный
    знаменатель shownCount — см. комментарий там; здесь цель — совпасть с
    sionline, а не с тем агрегатом).
    """
    session = _stats_api.requests.Session()
    stats = _stats_api.get_package_stats(session, name, authors)
    if not stats:
        return None
    summary = _stats_api.summarize(stats)
    qstats = stats.get("questionStats", {}) or {}
    per_question: dict[tuple[int, int, int], dict] = {}
    for key, qs in qstats.items():
        try:
            r, t, q = (int(x) for x in key.split(":"))
        except ValueError:
            continue
        shown = qs.get("shownCount") or 0
        correct = qs.get("correctCount") or 0
        wrong = qs.get("wrongCount") or 0
        total_tries = correct + wrong
        tries = round((qs.get("answeredCount") or 0) / shown * 100) if shown else 0
        right = round(correct / total_tries * 100) if total_tries else 0
        per_question[(r, t, q)] = {"tries": tries, "right": right}
    return summary, per_question
