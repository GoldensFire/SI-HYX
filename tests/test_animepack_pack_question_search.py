# -*- coding: utf-8 -*-
"""Поиск по содержимому паков, добавленных в запрет повторов."""
from si_hyx_parts.animepack_tab.pack_question_search import search_questions


def test_search_finds_anime_in_answers_and_reports_used_media(make_siq):
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <package name="Старый пак"><rounds><round name="Раунд 2"><themes>
      <theme name="Экстрасенсы"><questions><question price="500"><params>
        <param name="question" type="content">
          <item type="image" isRef="True">mob-frame.avif</item>
        </param></params><right>
          <answer>Моб Психо 100</answer><answer>Mob Psycho 100</answer>
        </right></question></questions></theme>
    </themes></round></rounds></package>"""
    path = make_siq(content_xml=xml)
    rows = search_questions([path], "Моб Психо")
    assert len(rows) == 1
    row = rows[0]
    assert row["pack"] == "Старый пак"
    assert row["round"] == "Раунд 2" and row["theme"] == "Экстрасенсы"
    assert row["answers"] == ["Моб Психо 100", "Mob Psycho 100"]
    assert row["used"] == ["Изображение: mob-frame.avif"]
