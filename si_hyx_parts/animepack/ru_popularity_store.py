# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Persistent observations and immutable complete distribution snapshots."""
import threading
import time

from .ru_popularity_math import (KINDS, SNAPSHOT_GROUP, OBSERVATION_GROUP,
                                RuPopularityConfig, correction, percentile, number)
from si_hyx_parts.animepack_api.ru_title_matching import (
    match_title, normalized, title_names)


class RuPopularityStore:
    def __init__(self, cache, clients, config=None, clock=time.time, *, persist=True):
        self.cache, self.clients = cache, clients
        self.config = config or RuPopularityConfig()
        self.clock = clock
        self.persist = persist
        self.snapshots = cache.memo_group(SNAPSHOT_GROUP)
        self._disabled = set()
        self._observations = {}
        self._title_indexes = {}
        self._validated_snapshots = {}
        self._lock = threading.Lock()

    def _snapshot(self, source):
        row = self.snapshots.get(source) or {}
        if not isinstance(row, dict):
            return {}
        metric = getattr(self.clients.get(source), "metric", None)
        if metric and row.get("metric") != metric:
            return {}
        timestamp = number(row.get("timestamp"))
        if (not row.get("complete") or row.get("version") != 1
                or timestamp is None
                or self.clock() - timestamp > self.config.snapshot_ttl):
            return {}
        key = (source, timestamp)
        if key not in self._validated_snapshots:
            groups = ("readership", "book_index") if source == "shikimori" else ("distributions",)
            valid = True
            for group in groups:
                distributions = row.get(group)
                if not isinstance(distributions, dict):
                    valid = False
                    break
                for values in distributions.values():
                    if (not isinstance(values, list)
                            or any(number(v) is None or isinstance(v, str) for v in values)
                            or values != sorted(values)):
                        valid = False
                        break
            self._validated_snapshots[key] = valid
        if not self._validated_snapshots[key]:
            return {}
        return row

    def candidates(self, source, card, snapshot):
        stamp = snapshot.get("timestamp")
        cached = self._title_indexes.get(source)
        if cached is None or cached[0] != stamp:
            aliases, direct = {}, {}
            for row in snapshot.get("titles") or []:
                for name in row.get("titles") or []:
                    aliases.setdefault(normalized(name), []).append(row)
                if row.get("shiki_id"):
                    direct.setdefault(str(row["shiki_id"]), []).append(row)
            cached = (stamp, aliases, direct)
            self._title_indexes[source] = cached
        rows = list(cached[2].get(str(card.get("id") or ""), []))
        for name in title_names(card):
            rows.extend(cached[1].get(normalized(name), []))
        return rows

    def observe(self, source, card, network=True):
        ident = str(card.get("id") or "")
        key = source + ":" + ident
        if key in self._observations:
            return self._observations[key]
        previous = self.cache.memo(OBSERVATION_GROUP, key) or {}
        if not isinstance(previous, dict):
            previous = {}
        snapshot = self._snapshot(source)
        metric = snapshot.get("metric") or getattr(self.clients.get(source), "metric", None)
        if metric and previous.get("metric") != metric:
            previous = {}
        elif (metric and previous.get("last_normal")
              and previous["last_normal"].get("metric") != metric):
            previous = {k: v for k, v in previous.items() if k != "last_normal"}
        ttl = (self.config.normal_ttl if previous.get("status") == "NORMAL"
               else self.config.failure_ttl)
        if (previous and self.clock() - previous.get("timestamp", 0) < ttl
                and previous.get("snapshot_timestamp") == snapshot.get("timestamp")):
            self._observations[key] = previous
            return previous
        record = {"source": source, "shikimori_id": ident,
                  "source_title_id": None, "slug": None, "matched_title": None,
                  "raw_metric": None, "metric": metric, "percentile": None,
                  "type": card.get("kind"),
                  "status": "ERROR", "timestamp": self.clock(),
                  "snapshot_timestamp": snapshot.get("timestamp")}
        if previous.get("last_normal"):
            record["last_normal"] = previous["last_normal"]
        try:
            if not snapshot:
                record["reason"] = "missing_or_expired_complete_distribution"
            elif source in self._disabled:
                record["reason"] = "source_failed_this_run"
            else:
                status, row = match_title(card, self.candidates(source, card, snapshot))
                record["status"] = status
                if row is not None:
                    detail = self.clients[source].details(row) if network else row
                    if detail is None:
                        record["status"] = "NOT_FOUND"
                    elif (match_title(card, [detail])[0] != "NORMAL"
                          or detail["id"] != row["id"]):
                        record["status"] = "AMBIGUOUS"
                    else:
                        self._populate(record, detail, snapshot)
        except Exception as exc:
            self._disabled.add(source)
            record.update(status="ERROR", reason=str(exc))
        # Identity changes never inherit licensing history from another title.
        historical = record.get("last_normal") or {}
        if (record.get("source_title_id") and historical.get("source_title_id")
                and historical["source_title_id"] != record["source_title_id"]):
            record.pop("last_normal", None)
        if historical.get("type") and historical["type"] != record["type"]:
            record.pop("last_normal", None)
        if self.persist:
            self.cache.remember_memo(OBSERVATION_GROUP, key, record)
        self._observations[key] = record
        return record

    def _populate(self, record, detail, snapshot):
        if snapshot.get("metric") and detail["metric"] != snapshot["metric"]:
            record.update(status="ERROR", reason="population_metric_mismatch")
            return
        cohort = ("all_types" if snapshot.get("type_fallback") else detail["kind"])
        record.update(source_title_id=detail["id"], slug=detail["slug"],
                      matched_title=(detail["titles"] or [""])[0],
                      raw_metric=detail["raw_metric"], metric=detail["metric"],
                      status=detail["status"], fields=detail["fields"], cohort=cohort,
                      type_fallback=snapshot.get("type_fallback", ""))
        distribution = (snapshot.get("distributions") or {}).get(cohort) or []
        if record["status"] == "NORMAL":
            if (detail["raw_metric"] is None
                    or len(distribution) < self.config.min_samples):
                record.update(status="ERROR", reason="population_metric_or_cohort_missing")
                return
            record["percentile"] = percentile(distribution, detail["raw_metric"])
            record["last_normal"] = {k: record[k] for k in (
                "source_title_id", "slug", "raw_metric", "metric", "percentile",
                "type", "cohort", "timestamp", "snapshot_timestamp")}

    def evaluate(self, candidate, network=True):
        if not candidate.is_manga or candidate.anime.get("kind") not in KINDS:
            return {}
        with self._lock:
            baseline = self._snapshot("shikimori")
            kind = candidate.anime["kind"]
            raw = (baseline.get("readership") or {}).get(kind) or []
            book = (baseline.get("book_index") or {}).get(kind) or []
            p_shiki = (percentile(raw, candidate.own_base)
                       if len(raw) >= self.config.min_samples else None)
            observations = {source: self.observe(source, candidate.anime, network)
                            for source in self.clients}
            return correction(candidate.book_index, p_shiki, observations, book, self.config)


def service(generator):
    current = getattr(generator, "_ru_popularity_service", None)
    if current is None:
        from si_hyx_parts.animepack_api.ru_manga_clients import (
            ReMangaPopulation, MangaLibPopulation)
        settings = getattr(generator.s, "ru_popularity", {})
        allowed = RuPopularityConfig.__dataclass_fields__
        config = RuPopularityConfig(**{k: v for k, v in settings.items() if k in allowed})
        current = RuPopularityStore(generator.db_cache,
                                    {"remanga": ReMangaPopulation(),
                                     "mangalib": MangaLibPopulation()}, config)
        generator._ru_popularity_service = current
    return current


def apply_ru_popularity(generator, candidate):
    if candidate.is_manga:
        # Generation and database previews use the same immutable census;
        # no catalog/title requests in the candidate enumeration loop.
        candidate.ru_popularity = service(generator).evaluate(candidate, network=False)
