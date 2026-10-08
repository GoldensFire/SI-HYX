"""Back up the JSON catalog and its transactional SQLite memo store together."""
from pathlib import Path
import shutil
import sqlite3


def backup_database(cache, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    catalog = Path(cache.path)
    if catalog.exists():
        shutil.copy2(catalog, destination / "database-before.json.bak")
    memo = Path(str(catalog) + ".memo.sqlite")
    if memo.exists():
        with sqlite3.connect("file:" + memo.as_posix() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(str(destination / "memo-before.sqlite")) as target:
                source.backup(target)
    return destination
