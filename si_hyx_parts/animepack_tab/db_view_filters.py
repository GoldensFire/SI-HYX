"""Read-only predicates for database rows, with no generation settings."""

RANGES = (("year", "Год", 9999), ("score", "Оценка", 10),
          ("level", "Уровень", 100))


def defaults():
    return {"anime": None, "manga": None,
            **{f"{field}_{side}": None for field, _, _ in RANGES
               for side in ("from", "to")}, "favorites_status": None}


def active(filters):
    return any(value is not None for value in filters.values())


def title_rows(rows, filters):
    if not filters:
        return list(rows)
    result = []
    for row in rows:
        kinds = filters.get(row.get("media", "anime"))
        if kinds is not None and row.get("kind") not in kinds:
            continue
        if any((filters.get(f"{field}_from") is not None
                and row.get(field, 0) < filters[f"{field}_from"])
               or (filters.get(f"{field}_to") is not None
                   and row.get(field, 0) > filters[f"{field}_to"])
               for field, _, _ in RANGES):
            continue
        status = filters.get("favorites_status")
        actual = row.get("favorites_status", "NORMAL" if row.get("favorites", -1) >= 0
                         else "UNKNOWN")
        if status == "UNKNOWN" and actual == "NORMAL":
            continue
        if status and status != "UNKNOWN" and status != actual:
            continue
        result.append(row)
    return result
