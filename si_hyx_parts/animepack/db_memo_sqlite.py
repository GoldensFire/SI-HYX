"""Lazy memo groups stored separately from the title catalog."""
import json
from pathlib import Path
import sqlite3
import threading

UPSERT = ("INSERT INTO memo VALUES (?,?,?,?) ON CONFLICT(category,key) "
          "DO UPDATE SET fetched=excluded.fetched,payload=excluded.payload")
# Ключей на один запрос IN (...): с запасом ниже предела переменных SQLite.
KEYS_PER_QUERY = 500


class MemoStore:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        self.changed = False
        self.connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False,
                                          isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS memo ("
                                "category TEXT NOT NULL, key TEXT NOT NULL, "
                                "fetched REAL NOT NULL, payload TEXT NOT NULL, "
                                "PRIMARY KEY(category,key))")

    def import_groups(self, groups):
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                for category, rows in groups.items():
                    if isinstance(rows, MemoGroup):
                        continue
                    values = ((str(category), str(key), float(row.get("fetched") or 0),
                               json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                              for key, row in rows.items() if isinstance(row, dict))
                    self.connection.executemany(
                        "INSERT INTO memo VALUES (?,?,?,?) ON CONFLICT(category,key) "
                        "DO UPDATE SET fetched=excluded.fetched,payload=excluded.payload "
                        "WHERE excluded.fetched >= memo.fetched", values)
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise

    def group(self, category):
        return MemoGroup(self, str(category))

    def categories(self):
        with self.lock:
            return [row[0] for row in self.connection.execute("SELECT DISTINCT category FROM memo")]

    def clear_category(self, category):
        with self.lock:
            self.connection.execute("DELETE FROM memo WHERE category=?", (category,))
            self.changed = True

    def remove_groups_except(self, categories):
        with self.lock:
            known = [row[0] for row in self.connection.execute("SELECT DISTINCT category FROM memo")]
            for category in set(known) - set(categories):
                self.connection.execute("DELETE FROM memo WHERE category=?", (category,))

    def clear(self):
        with self.lock:
            self.connection.execute("DELETE FROM memo")
        self.changed = True


class MemoGroup(dict):
    """Dict-compatible row access for existing cache and maintenance methods."""
    def __init__(self, store, category):
        self.store, self.category = store, category

    def __len__(self):
        with self.store.lock:
            return self.store.connection.execute(
                "SELECT COUNT(*) FROM memo WHERE category=?", (self.category,)).fetchone()[0]

    def __bool__(self):
        # Cache lookups use ``group or {}``; COUNT would scan a whole cohort.
        with self.store.lock:
            return self.store.connection.execute(
                "SELECT 1 FROM memo WHERE category=? LIMIT 1", (self.category,)).fetchone() is not None

    def __iter__(self):
        return iter(self.keys())

    def keys(self):
        with self.store.lock:
            return [row[0] for row in self.store.connection.execute(
                "SELECT key FROM memo WHERE category=?", (self.category,))]

    def items(self):
        with self.store.lock:
            return [(key, json.loads(payload)) for key, payload in self.store.connection.execute(
                "SELECT key,payload FROM memo WHERE category=?", (self.category,))]

    def values(self):
        return [value for _, value in self.items()]

    def __getitem__(self, key):
        with self.store.lock:
            row = self.store.connection.execute(
                "SELECT payload FROM memo WHERE category=? AND key=?",
                (self.category, str(key))).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        return self.get(key) is not None

    def __setitem__(self, key, value):
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self.store.lock:
            self.store.connection.execute(
                UPSERT, (self.category, str(key), float(value.get("fetched") or 0), payload))
            self.store.changed = True

    def many(self, keys) -> dict:
        """{ключ: строка} для найденных ключей — запрос на пачку, а не на ключ."""
        keys = [str(key) for key in keys]
        found = []
        with self.store.lock:
            for at in range(0, len(keys), KEYS_PER_QUERY):
                chunk = keys[at:at + KEYS_PER_QUERY]
                marks = ",".join("?" * len(chunk))
                found.extend(self.store.connection.execute(
                    f"SELECT key,payload FROM memo WHERE category=? AND key IN ({marks})",
                    (self.category, *chunk)))
        return {key: json.loads(payload) for key, payload in found}

    def update_many(self, rows: dict) -> None:
        """Много строк одной транзакцией.

        По одной каждая запись — своя транзакция с fsync (synchronous=FULL):
        2,4 мс на строку, и 107 тысяч наблюдений RU-популярности, устаревших
        за шесть часов, переписывались четыре с половиной минуты."""
        values = [(self.category, str(key), float(row.get("fetched") or 0),
                   json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                  for key, row in rows.items()]
        if not values:
            return
        with self.store.lock:
            self.store.connection.execute("BEGIN IMMEDIATE")
            try:
                self.store.connection.executemany(UPSERT, values)
                self.store.connection.execute("COMMIT")
            except Exception:
                self.store.connection.execute("ROLLBACK")
                raise
            self.store.changed = True


def open_store(cache, create=False):
    path = Path(str(cache.path) + ".memo.sqlite")
    existing = cache._shared.get("memo_store")
    if existing is None:
        if not create and not path.is_file():
            raise RuntimeError(f"Не найдено хранилище служебных данных базы: {path}")
        existing = MemoStore(path)
        cache._shared["memo_store"] = existing
    return existing
