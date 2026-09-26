"""Composition sliders, title batching and canonical SIQ answers."""
import json
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import animepack as ap
import animepack_tab
from si_hyx_parts.animepack.title_questions import generate_titles


@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab()
    yield widget
    widget.cleanup()


def test_only_checked_sliders_and_total(tab):
    tab.chk_manga.setChecked(True)
    tab.chk_anagram.setChecked(True)
    tab.chk_songs.setChecked(False)
    assert tab.mix.keys() == ["manga", "anagram"]
    tab.mix.sliders["manga"].setValue(37)
    assert tab.mix.shares()["anagram"] == 63
    assert sum(tab.mix.shares().values()) == 100
    assert all(row.isHidden() == (key not in ("manga", "anagram"))
               for key, row in tab.mix.rows.items())
    tab.chk_manga.setChecked(False)
    assert tab.mix.shares()["anagram"] == 100
    tab.chk_anagram.setChecked(False)
    assert not any(tab.mix.shares().values())
    assert "Выберите хотя бы одну часть пака." in tab.collect().validate()


def test_title_settings_roundtrip_and_shared_gemini(tab):
    assert not tab.box_text_cps.isVisibleTo(tab)
    tab.chk_synonyms.setChecked(True)
    tab.chk_ukrainian.setChecked(True)
    tab.chk_songs.setChecked(False)
    tab.mix.sliders["synonyms"].setValue(70)
    data = tab.get_settings()
    tab.apply_settings(data)
    assert tab.mix.shares()["synonyms"] == 70
    assert tab.mix.shares()["ukrainian"] == 30
    assert not tab.chk_songs.isChecked()
    assert tab.box_plot.isVisibleTo(tab)
    assert tab.box_text_cps.isVisibleTo(tab)
    tab.chk_plot.setChecked(True)
    tab.chk_plot.setChecked(False)
    assert tab.box_plot.isVisibleTo(tab)


def test_thinking_level_is_saved_with_the_model(tab):
    """Уровень рассуждения выбирается рядом с моделью и переживает сохранение."""
    import gemini_api
    assert tab.cb_gemini_think.currentData() == gemini_api.THINKING_LEVEL
    tab.cb_gemini_think.setCurrentIndex(tab.cb_gemini_think.findData("high"))
    data = tab.get_settings()
    assert data["gemini_thinking"] == "high"
    assert tab.collect().gemini_thinking == "high"
    tab.cb_gemini_think.setCurrentIndex(tab.cb_gemini_think.findData("low"))
    tab.apply_settings(data)
    assert tab.cb_gemini_think.currentData() == "high"
    # Настройки без этого поля (старые) возвращают уровень по умолчанию.
    tab.apply_settings({k: v for k, v in data.items() if k != "gemini_thinking"})
    assert tab.cb_gemini_think.currentData() == gemini_api.THINKING_LEVEL


def test_panel_width_does_not_follow_toggles(tab, qapp):
    tab.resize(1200, 850)
    tab.show()
    qapp.processEvents()
    width = tab.right_col.width()
    for key in tab.mix.KEYS:
        tab.composition_checks[key].setChecked(True)
        qapp.processEvents()
        assert tab.right_col.width() == width


def candidates(count=10):
    # kind у карточки нужен антонимам: их берут только с ТВ и полнометражек.
    return [ap.SongCandidate(song={}, anime={"id": i + 1, "russian": "Тетрадь смерти",
                             "name": "Death Note", "kind": "tv",
                             "related": []},
                             kind="synonyms") for i in range(count)]


def test_ten_titles_one_request_and_original_answers():
    items = candidates()
    client = Mock()
    client.generate_json.return_value = {"items": [
        {"id": i, "text": "Блокнот гибели"} for i in reversed(range(10))]}
    gen = SimpleNamespace(gemini=client, stopped=lambda: False, log=lambda msg: None)
    result = generate_titles(gen, items)
    assert len(result) == 10
    assert client.generate_json.call_count == 1
    assert all(c.plot_question == "Блокнот гибели" for c in result)
    xml = ap.build_content_xml(result, ap.PackSettings()).decode()
    assert "Блокнот гибели" in xml
    assert "Тетрадь смерти" in xml
    assert not any(c.plot_answers for c in result)
    assert len(json.loads(client.generate_json.call_args.args[0].split("\n")[-1])) == 10


def test_text_speed_applies_to_transformed_title():
    item = candidates(1)[0]
    item.plot_question = "Б" * 31
    root = ET.fromstring(ap.build_content_xml(
        [item], ap.PackSettings(anagram_cps=10)))
    body = root.find(".//{*}param[@name='question']/{*}item")
    assert body.get("duration") == "00:00:04"


def test_bad_batch_cannot_publish_empty_questions():
    client = Mock()
    client.generate_json.return_value = {"items": [{"id": 0, "text": ""}]}
    gen = SimpleNamespace(gemini=client, stopped=lambda: False, log=lambda msg: None)
    with pytest.raises(RuntimeError, match="Пак не сохранён"):
        generate_titles(gen, candidates(1))


def test_title_pack_end_to_end(tmp_path, monkeypatch):
    import zipfile
    settings = ap.PackSettings(rounds=1, themes=1, questions=3,
        pct_songs=0, pack_synonyms=True, pct_synonyms=34,
        pack_antonyms=True, pct_antonyms=33, pack_ukrainian=True, pct_ukrainian=33,
        gemini_key="test-key", out_dir=str(tmp_path))
    client = Mock()

    def respond(prompt, schema):
        rows = json.loads(prompt.split("\n")[-1])
        if "eligible" in schema["properties"]["items"]["items"]["properties"]:
            return {"items": [{"id": row["id"], "eligible": True,
                               "antonyms": True} for row in rows]}
        texts = {"synonyms": "Блокнот гибели", "antonyms": "Тетрадь жизни",
                 "ukrainian": "Зошит смерті"}
        return {"items": [{"id": row["id"], "text": texts[row["kind"]]} for row in rows]}

    client.generate_json.side_effect = respond
    gen = ap.AnimePackGenerator(settings, gemini=client,
                               frames_history_path=str(tmp_path / "frames.json"))
    monkeypatch.setattr(gen, "iter_candidates", lambda: iter(candidates(3)))
    monkeypatch.setattr(gen, "download_images", lambda cand: None)
    result = gen.run()
    assert {c.kind for c in result.songs} == {"synonyms", "antonyms", "ukrainian"}
    assert client.generate_json.call_count == 2
    with zipfile.ZipFile(result.path) as archive:
        xml = archive.read("content.xml").decode()
        for text in ("Блокнот гибели", "Тетрадь жизни", "Зошит смерті", "Тетрадь смерти"):
            assert text in xml
        ns = {"s": ap.SIQ_NS}
        themes = ET.fromstring(xml).findall(".//s:theme", ns)
        assert len(themes) == 1
        assert themes[0].get("name") == settings.theme_title
        questions = themes[0].findall("s:questions/s:question", ns)
        assert len(questions) == 3
        bodies = [q.findall("s:params/s:param[@name='question']/s:item", ns)
                  for q in questions]
        assert all(len(items) == 1 for items in bodies)
        assert {items[0].text for items in bodies} == {
            "Блокнот гибели", "Тетрадь жизни", "Зошит смерті"}
        assert "Назовите аниме по изменённому названию" not in xml


@pytest.mark.parametrize("shuffle", [False, True])
def test_mixed_title_themes_preserve_rounds_and_questions(shuffle):
    settings = ap.PackSettings(rounds=2, themes=2, questions=4,
                               shuffle_questions=shuffle)
    items = candidates(16)
    for i, cand in enumerate(items):
        cand.kind = ("synonyms", "antonyms", "ukrainian", "anagram")[i % 4]
        cand.plot_question = f"Загадка {i}"
    themes = ap.arrange_questions(items, settings)
    assert len(themes) == 4
    assert all(len({c.kind for c in theme}) == 4 for theme in themes)
    root = ET.fromstring(ap.build_content_xml(items, settings))
    ns = {"s": ap.SIQ_NS}
    assert len(root.findall(".//s:question", ns)) == len(items)
    assert len(root.findall(".//s:round", ns)) == settings.rounds
    assert len(root.findall(".//s:theme", ns)) == settings.rounds * settings.themes


def test_usage_is_separate_by_key_model_and_persistent(tmp_path, monkeypatch):
    import gemini_usage as usage
    monkeypatch.setattr(usage, "_path", lambda: tmp_path / "usage.json")
    usage.record_request("private-key", "a")
    usage.record_request("private-key", "a")
    assert usage.requests_today("private-key", "a") == 2
    assert usage.requests_today("other-key", "a") == 0
    assert usage.requests_today("private-key", "b") == 0
    assert "private-key" not in (tmp_path / "usage.json").read_text(encoding="utf-8")


# ── Раскладка настроек ───────────────────────────────────────────────────────
def _cell(widget):
    """Строка и столбец виджета в его сетке."""
    layout = widget.parent().layout()
    row, col, _rs, _cs = layout.getItemPosition(layout.indexOf(widget))
    return row, col


def test_thinking_level_has_its_own_row(tab):
    """Уровень рассуждения стоит своей строкой и ни с чем клетку не делит.

    Строки «Лимит Gemini / сутки» на панели больше нет вовсе (просьба
    пользователя) — остался только расход запросов самого приложения."""
    assert not hasattr(tab, "sp_gemini_daily")
    assert _cell(tab.cb_gemini_think) != _cell(tab.cb_gemini_model)
    assert _cell(tab.cb_gemini_model)[0] < _cell(tab.cb_gemini_think)[0]
    assert _cell(tab.cb_gemini_think)[0] < _cell(tab.lbl_gemini_quota)[0]


def test_options_of_a_kind_sit_right_under_its_checkbox(tab):
    """Настройки рода вопросов идут сразу под его галочкой, а не внизу панели."""
    from si_hyx_parts.animepack_tab.composition_controls import _OPTIONS
    grid = tab.composition_checks["manga"].parent().layout()

    def row_of(widget):
        return grid.getItemPosition(grid.indexOf(widget))[0]

    for key, boxes in _OPTIONS.items():
        chk_row = row_of(tab.composition_checks[key])
        for offset, name in enumerate(boxes, start=1):
            assert row_of(getattr(tab, name)) == chk_row + offset, key
    # И ни одна чужая галочка между ними не затесалась.
    rows = {row_of(chk) for chk in tab.composition_checks.values()}
    assert row_of(tab.box_plot) not in rows


def test_flash_models_lose_the_minimal_thinking_level(tab):
    """У обычного Flash «минимального» уровня нет — не показываем его вовсе."""
    levels = lambda: [tab.cb_gemini_think.itemData(i)
                      for i in range(tab.cb_gemini_think.count())]
    tab.cb_gemini_model.setCurrentText("gemini-3.5-flash-lite")
    assert "minimal" in levels()
    tab.cb_gemini_model.setCurrentText("gemini-3.6-flash")
    assert "minimal" not in levels()
    assert tab.cb_gemini_think.currentData() == "low"
    assert tab.collect().gemini_thinking == "low"
    # Выбранный уровень переживает возврат к Lite.
    tab.cb_gemini_think.setCurrentIndex(tab.cb_gemini_think.findData("high"))
    tab.cb_gemini_model.setCurrentText("gemini-3.5-flash-lite")
    assert tab.cb_gemini_think.currentData() == "high"


def test_saved_minimal_level_survives_a_flash_only_settings_file(tab):
    """Старые настройки с «минимальным» не должны обнулять выбор модели."""
    tab.cb_gemini_model.setCurrentText("gemini-3.6-flash")
    data = tab.get_settings()
    data["gemini_thinking"] = "minimal"
    tab.apply_settings(data)
    assert tab.cb_gemini_think.currentData() == "low"


def test_plot_has_its_own_difficulty_range(tab):
    """Сложность вопросов по сюжету настраивается отдельно от пака."""
    import animepack as ap

    assert not tab.plot_level_range.isVisibleTo(tab)
    tab.chk_plot.setChecked(True)
    assert tab.plot_level_range.isVisibleTo(tab)
    tab.sp_plot_level_from.setValue(2)
    tab.sp_plot_level_to.setValue(5)
    tab.sp_plot_level_avg.setValue(3)
    settings = tab.collect()
    assert settings.level_range(ap.PLOT_KIND) == (2, 5)
    assert settings.level_range(ap.FRAME_KIND) == (settings.level_min,
                                                   settings.level_max)
    assert ap.level_avg_target(settings, ap.level_bucket(ap.PLOT_KIND)) == 3
    data = tab.get_settings()
    tab.sp_plot_level_to.setValue(9)
    tab.apply_settings(data)
    assert tab.sp_plot_level_to.value() == 5
