# -*- coding: utf-8 -*-
"""Обновлённые снимки популярности должны менять уровни открытой таблицы."""
import time

import animepack as ap
from si_hyx_parts.animepack_tab import db_rows
from si_hyx_parts.animepack_tab.db_table_dialog import DbTableDialog
from test_manga_ru_cache import populate
from test_manga_ru_popularity import manga


def test_reread_discards_rows_published_by_an_obsolete_calculation(
        qapp, tmp_path, monkeypatch):
    path = str(tmp_path / "db.json")
    cache = ap.ShikimoriDbCache(path)
    cache.add_cards("manga", "all", [manga()])
    cache.save()
    dialog = DbTableDialog(cache)
    try:
        dialog.flush()
        old_rows = dialog._rows_for("manga", None)
        old_level = old_rows[0]["level"]
        # Другой экземпляр сохраняет источники, пока панель ещё открыта.
        writer = ap.ShikimoriDbCache(path)
        populate(writer, now=time.time())
        writer.save()
        queued = []
        monkeypatch.setattr(dialog, "_start", queued.append)

        def finish_old_calculation(*args):
            # Перечитывание запрошено до завершения прежнего расчёта.
            dialog.refresh()
            return old_rows

        dialog._title_rows = {}
        with monkeypatch.context() as patch:
            patch.setattr(db_rows, "title_rows", finish_old_calculation)
            dialog._rows_for("manga", None)
        assert dialog._title_rows["manga"] is old_rows
        assert queued[0][0] == "counts"
        dialog._work(dialog._age, queued[0])
        fresh = dialog._rows_for("manga", None)[0]
        assert fresh["level"] < old_level
        candidate = fresh["candidate"]
        assert candidate.effective_book_index > candidate.book_index
        assert fresh["level"] == candidate.level
    finally:
        dialog.close()
        dialog.deleteLater()
