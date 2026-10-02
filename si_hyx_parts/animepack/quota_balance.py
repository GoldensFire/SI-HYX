# -*- coding: utf-8 -*-
"""Перенос пустых мест по реальным оставшимся кандидатам.

    Сначала сохраняем исходные доли через паросочетание: один тайтл нельзя
    посчитать одновременно запасом персонажей и кадров. Только места без
    подходящего кандидата отдаются другому включённому роду вопросов.
"""
from collections import Counter


def rebalance(options, quotas, counts):
    """Возвращает новые квоты, сохраняя сумму и уже принятые вопросы."""
    stock = Counter(kind for kinds in options for kind in kinds)
    slots = [kind for kind, quota in quotas.items()
             for _ in range(max(0, quota - counts[kind]))]
    owners = {}
    assigned = {}

    def assign(slot, visited):
        kind = slots[slot]
        for group, kinds in enumerate(options):
            if kind not in kinds or group in visited:
                continue
            visited.add(group)
            previous = owners.get(group)
            if previous is None or assign(previous, visited):
                owners[group] = slot
                assigned[slot] = group
                return True
        return False

    for slot in sorted(range(len(slots)), key=lambda i: stock[slots[i]]):
        assign(slot, set())
    result = dict(quotas)
    for slot, donor in enumerate(slots):
        if slot in assigned:
            continue
        # Свободные тайтлы не подошли пустому месту, но могут заполнить
        # дополнительное место в уже набранной категории.
        choices = [(kind, group) for group, kinds in enumerate(options)
                   if group not in owners for kind in kinds]
        if not choices:
            break
        kind, group = min(choices, key=lambda item: (
            result[item[0]] / max(1, quotas[item[0]]), item[0], item[1]))
        result[donor] -= 1
        result[kind] += 1
        owners[group] = slot
    return result
