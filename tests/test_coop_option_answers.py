# -*- coding: utf-8 -*-
"""Вопросы с выбором варианта не дают ложных дублей.

Живой случай: в паке несколько вопросов «что из перечисленного…» с вариантами
на картинке, правильный ответ записан одной буквой «B». Вкладка сравнивала
ответы как текст и красила их «⚠ дубль», хотя вопросы совершенно разные.
"""
import pytest

from coop_tab import _is_option_answer, _q_summary


@pytest.mark.parametrize("ans", [
    "B", "b", "б", "А", "3", "A)", "б.", "«В»", "вариант Б", "Ответ: A",
    "А и В", "A, C", "б/в",
])
def test_option_labels_are_not_answers(ans):
    assert _is_option_answer({"a": ans}) is True


@pytest.mark.parametrize("ans", [
    "Христофор Колумб", "Да", "Нет", "1240", "Al dente (аль денте)",
    "Bakugan", "Мексика", "Перун", "defense of the ancients (защита древних)",
    "Кот Гром и заколдованный дом",
])
def test_real_answers_still_compared(ans):
    assert _is_option_answer({"a": ans}) is False


def test_empty_answer_is_not_option():
    assert _is_option_answer({"a": ""}) is False
    assert _is_option_answer({}) is False


def test_answer_options_flag_wins_over_text():
    """Если в паке у вопроса есть answerOptions, ответ — метка варианта, каким
    бы текстом он ни был записан."""
    assert _is_option_answer({"a": "Красный шар", "opt": True}) is True


def test_summary_marks_questions_with_answer_options():
    q = {"price": 100, "items": [], "answers": ["B"],
         "answer_options": {"A": [], "B": []}}
    assert _q_summary(q).get("opt") is True
    # ...и не таскает лишний ключ по сети для обычных вопросов
    assert "opt" not in _q_summary({"price": 100, "items": [], "answers": ["Мексика"]})


def _outline(theme, questions):
    return {"name": "p", "rounds": [{"name": "1", "themes": [
        {"name": theme, "questions": questions}]}]}


@pytest.fixture
def tab(qapp, monkeypatch):
    import coop_tab
    monkeypatch.setattr(coop_tab._CoopSync, "start", lambda self, u, r, a: None)
    t = coop_tab.CoopTab(None, {"author": "Я"})
    yield t
    t.cleanup()


def _flatten(tree):
    rows = []
    for i in range(tree.topLevelItemCount()):
        th = tree.topLevelItem(i)
        for j in range(th.childCount()):
            c = th.child(j)
            rows.append((c.text(0), c.text(4)))
    return rows


def test_letter_answers_not_flagged_as_duplicates(tab):
    """Два разных вопроса с ответом «B» у разных авторов — не дубль."""
    tab._my_outline = _outline("Случайные вопросы", [
        {"price": 200, "q": "Что из перечисленного не имеет резьбы?", "a": "B",
         "qm": [], "am": ["image"]}])
    tab._remote = {"Ofuuse": {"outline": _outline("Логика", [
        {"price": 400, "q": "Какая профессия изучает насекомых?", "a": "B",
         "qm": [], "am": ["image"]}]), "updated": 1}}
    tab._rebuild()
    assert all("дубль" not in a for _, a in _flatten(tab.tree))
    assert "совпавших ответов" not in tab.lbl_count.text()


def test_real_duplicate_still_flagged(tab):
    """Настоящее совпадение ответа обязано остаться красным."""
    tab._my_outline = _outline("Путешествия", [
        {"price": 100, "q": "Кто на фото?", "a": "Христофор Колумб",
         "qm": ["image"], "am": []}])
    tab._remote = {"Ofuuse": {"outline": _outline("История", [
        {"price": 300, "q": "Кто открыл Америку?", "a": "Христофор Колумб",
         "qm": [], "am": []}]), "updated": 1}}
    tab._rebuild()
    assert sum("дубль" in a for _, a in _flatten(tab.tree)) == 2
    assert "совпавших ответов: 2" in tab.lbl_count.text()
