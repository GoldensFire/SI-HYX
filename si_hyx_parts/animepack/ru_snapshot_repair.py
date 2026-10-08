"""Repair legacy cohorts without pretending their remote catalog is newer."""
from types import SimpleNamespace


def repair_snapshot(row, source, config, clock):
    if (not isinstance(row, dict) or not row.get("complete") or row.get("version") != 1
            or row.get("calculation_revision") == "eligible_types_v2"
            or not row.get("type_fallback") or not row.get("titles")):
        return row
    titles = row["titles"]
    if any(not item.get("kind") for item in titles
           if item.get("status") == "NORMAL" and item.get("raw_metric") is not None):
        return row
    from .ru_catalog_snapshot import _snapshot
    try:
        repaired = _snapshot(SimpleNamespace(source=source, metric=row.get("metric")), config, titles)
    except (ValueError, TypeError, KeyError):
        return row
    return {**row, **repaired, "timestamp": clock(),
            "catalog_timestamp": row.get("catalog_timestamp", row.get("timestamp")),
            "calculation_revision": "eligible_types_v2"}
