"""Recoverable conversion of large legacy catalogs to a separate memo store."""
from pathlib import Path
import shutil

from .db_memo_sqlite import MemoGroup, open_store

THRESHOLD = 64 * 1024 * 1024
MARKER = "memo_storage"


def attach(cache, data):
    metadata = data.get(MARKER)
    if not metadata:
        return
    if metadata.get("version") != 1:
        raise ValueError("Неизвестная версия хранилища служебных данных")
    store = open_store(cache)
    categories = set(metadata["categories"]) | set(store.categories())
    data["memo"] = {name: store.group(name) for name in categories}


def prepare(cache):
    data = cache._data
    if not data.get(MARKER):
        original = Path(cache.path)
        if not original.is_file() or original.stat().st_size < THRESHOLD:
            return data
        # Preserve a readable source before the catalog starts referencing SQLite.
        backup = Path(str(original) + ".before-memo-split")
        if not backup.exists():
            from storage_guard import require_space, WORK_RESERVE
            require_space(original.parent, original.stat().st_size * 2 + WORK_RESERVE)
            shutil.copy2(original, backup)
        store = open_store(cache, create=True)
    else:
        store = open_store(cache)
    memo = data.get("memo") or {}
    store.import_groups(memo)
    categories = sorted(set(memo) | set(store.categories()))
    data["memo"] = {name: store.group(name) for name in categories}
    data[MARKER] = {"version": 1, "categories": categories}
    # The caller still owns the catalog lock; all original rows are committed.
    return {**data, "memo": {}}


def remember_group(cache, groups, name):
    if cache._data.get(MARKER):
        if not isinstance(groups.get(name), MemoGroup):
            groups[name] = open_store(cache).group(name)
            cache._dirty = True  # New category must enter the catalog manifest.
    return groups.setdefault(name, {})


def memo_saved(cache):
    store = cache._shared.get("memo_store")
    if store is not None and store.changed:
        store.changed = False
        return True
    return False
