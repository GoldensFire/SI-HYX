"""Развёрнутый ответ объясняет сюжет без названия аниме в обоих режимах."""
import xml.etree.ElementTree as ET

import pytest

import animepack as ap
import animepack_plot as plot
from si_hyx_parts.animepack.plot_explanation import without_titles


@pytest.mark.parametrize("explanation, titles, expected", [
    ('В аниме «Несчастная» Ханако уходит мыть посуду.', ["Несчастная"],
     'В этом аниме Ханако уходит мыть посуду.'),
    ('В «Несчастной» Ханако уходит мыть посуду.', ["Несчастная"],
     'В этом аниме Ханако уходит мыть посуду.'),
    ('В «Тетради смерти» герой записывает имя.', ["Тетрадь смерти"],
     'В этом аниме герой записывает имя.'),
    ('В Death Note герой записывает имя.', ["Death Note"],
     'В этом аниме герой записывает имя.'),
    ('Врата Штейна — Герой отправляет сообщение в прошлое.', ["Врата Штейна"],
     'Герой отправляет сообщение в прошлое.'),
    ('В аниме „Нулевой Эдем 2“ Хомура получает клинки.', ["Нулевой Эдем 2"],
     'В этом аниме Хомура получает клинки.'),
    ('Рюк появляется из тетради.', ["Death Note", "Тетрадь смерти"],
     'Рюк появляется из тетради.'),
])
def test_known_titles_are_removed_without_losing_the_fact(explanation, titles,
                                                        expected):
    assert without_titles(explanation, titles) == expected


@pytest.mark.parametrize("mode", ["title", "detail"])
def test_prompt_and_parsed_explanation_forbid_titles(mode):
    class Model:
        prompt = ""

        def generate_json(self, prompt, schema, temperature=0):
            self.prompt = prompt
            return {"ok": True, "question": "Что делает Ханако после обеда?",
                    "answer": "Мыть посуду", "answer_kind": "action",
                    "explanation": 'В аниме «Несчастная» Ханако уходит мыть посуду.'}

    model = Model()
    question, answers, explanation = plot.make_question_with_explanation(
        "Несчастная", "Пересказ " * 60, model, mode=mode)
    assert question
    assert "Несчастная" not in explanation
    assert "Ханако уходит мыть посуду" in explanation
    assert "НИКОГДА не называй аниме в explanation" in model.prompt
    if mode == "detail":
        assert "Несчастная" in question and answers == ["Мыть посуду"]


@pytest.mark.parametrize("mode", ["title", "detail"])
def test_xml_expanded_answer_does_not_reintroduce_titles(mode):
    anime = {"id": "1", "name": "Death Note", "english": "Death Note",
             "russian": "Тетрадь смерти", "kind": "tv",
             "airedOn": {"year": 2006}}
    cand = ap.SongCandidate({}, anime, kind=ap.PLOT_KIND)
    cand.plot_question = "Что обнаруживает герой?"
    cand.plot_explanation = 'В аниме «Тетрадь смерти» герой обнаруживает тайник.'
    if mode == "detail":
        cand.plot_answers = ["Тайник"]
    settings = ap.PackSettings(pct_songs=0, pack_plot=True, pct_plot=100,
                              plot_mode=mode, gemini_key="k",
                              rounds=1, themes=1, questions=1)
    root = ET.fromstring(ap.build_content_xml([cand], settings))
    answers = [node.text for node in root.findall(
        ".//s:right/s:answer", {"s": ap.SIQ_NS})]
    assert "Тетрадь смерти" not in answers[0]
    assert "Death Note" not in answers[0]
    assert "герой обнаруживает тайник" in answers[0]
    if mode == "title":
        assert cand.main_answer in answers
    else:
        assert "Тайник" in answers
