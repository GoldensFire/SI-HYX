# -*- coding: utf-8 -*-
"""Поиск в панели базы учитывает все названия карточки Shikimori."""
from si_hyx_parts.animepack_tab.db_table_view import DbTableModel, build_cells


def test_search_by_english_japanese_and_synonym(qapp):
    row = {"card": {
        "russian": "Райка", "name": "Rayca", "english": "Rayca",
        "japanese": "ライカ", "synonyms": ["Laika"],
        "licenseNameRu": "Лайка",
    }}
    texts, sorts, hay = build_cells([row], lambda _: [("Райка", None)])
    model = DbTableModel(("Название",))
    model.set_data([row], texts, sorts, hay)
    for query in ("райка", "rayca", "ライカ", "laika", "лайка"):
        model.set_needle(query)
        assert model.rowCount() == 1
