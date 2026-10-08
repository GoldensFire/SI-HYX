"""Validate final comic composition, difficulty, answers and title identities."""
from collections import Counter
from types import SimpleNamespace

import animepack as ap
from si_hyx_parts.animepack.manga_targets import final_error


def audit(settings, rows, questions, namespace):
    candidates = [SimpleNamespace(is_manga=True, kind=ap.MANGA_KIND,
                  anime={"kind": row["kind"]}, level=row["level"]) for row in rows]
    problem = final_error(settings, candidates)
    if problem:
        raise RuntimeError(problem)
    low, high = settings.level_range(ap.MANGA_KIND)
    if any(not low <= row["level"] <= high for row in rows):
        raise RuntimeError("Вопрос вне разрешённой рамки сложности")
    titles = Counter(row["title"].strip().casefold() for row in rows)
    duplicates = [title for title, count in titles.items() if count > 1]
    if duplicates:
        raise RuntimeError(f"Повторены названия: {duplicates}")
    identities = [str(row["mal"]) for row in rows]
    if len(set(identities)) != len(identities):
        raise RuntimeError("Повторены идентификаторы произведений")
    seen = set()
    for row in rows:
        marks = set(row.get("franchise_keys") or [])
        if not settings.dup_franchise and marks & seen:
            raise RuntimeError(f"Повторена франшиза: {row['title']}")
        seen.update(marks)
        if not row.get("page", "").startswith(("https://", "http://")):
            raise RuntimeError(f"Не сохранён источник страницы: {row['title']}")
    for question in questions:
        answers = question.findall(".//s:right/s:answer", namespace)
        if not answers or not any((answer.text or "").strip() for answer in answers):
            raise RuntimeError("У вопроса отсутствует правильный ответ")
    return {"exact_composition": True, "average_within_tolerance": True,
            "duplicate_titles": 0, "duplicate_identities": 0, "duplicate_franchises": 0,
            "answers_present": True, "source_pages_present": True}
