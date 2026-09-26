# -*- coding: utf-8 -*-
"""Вопрос по сюжету в режиме «ответ — деталь сюжета».

Сети тут нет: Gemini подменяется заглушкой. Проверяется то, о чём просил
пользователь: подписи «Назвать аниме по сюжету» у такого вопроса быть не
должно, ответ идёт с заглавной буквы, а имена персонажей в ответах не нужны —
нужны детали сюжета.
"""
import animepack_plot as plot


class FakeGemini:
    """Модель, которая всегда отвечает одним и тем же."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def generate_json(self, prompt, schema, temperature=0.0):
        self.prompts.append(prompt)
        return self.answer


def _ask(answer, **kw):
    client = FakeGemini(answer)
    text, answers = plot.make_question("Клинок", "Пересказ " * 60, client,
                                       mode="detail", **kw)
    return client, text, answers


def test_answers_start_with_a_capital_letter():
    """Модель пишет ответ строчными — в паке он должен быть с заглавной."""
    _client, _text, answers = _ask(
        {"ok": True, "question": "Чем герой рассекает демонов?",
         "answer": "меч ничирин", "alt": ["ничиринский клинок"]})
    assert answers == ["Меч ничирин", "Ничиринский клинок"]


def test_capitalising_does_not_touch_the_rest_of_the_answer():
    """Аббревиатуры и вторые слова с заглавной остаются как были."""
    _client, _text, answers = _ask(
        {"ok": True, "question": "Что?", "answer": "отряд SOS",
         "alt": ["Бригада SOS"]})
    assert answers == ["Отряд SOS", "Бригада SOS"]


def test_the_prompt_forbids_character_names():
    """Просьба пользователя: нужны детали сюжета, а не имена персонажей."""
    client, _text, _answers = _ask(
        {"ok": True, "question": "Что?", "answer": "меч"})
    prompt = client.prompts[0]
    assert "ИМЯ ПЕРСОНАЖА" in prompt and "как зовут" in prompt
    # Название произведения в таком вопросе, наоборот, нужно.
    assert "Произведение: Клинок" in prompt


def test_an_empty_answer_still_means_no_question():
    """Пустой ответ — вопроса нет: он достанется следующему тайтлу."""
    _client, text, answers = _ask({"ok": True, "question": "Что?",
                                   "answer": "", "alt": []})
    assert (text, answers) == ("", [])


def test_organization_answers_are_rejected():
    """Названия организаций и группировок больше не попадают в пак."""
    _client, text, answers = _ask({
        "ok": True,
        "question": "Как называется организация охотников?",
        "answer": "Корпус истребителей демонов",
        "answer_kind": "organization",
        "alt": [],
    })
    assert (text, answers) == ("", [])


def test_one_request_brings_several_variants_and_the_first_good_wins():
    """Отказ одного варианта не стоит нового запроса: у Flash их 20 в сутки."""
    client, text, answers = _ask({"items": [
        {"ok": False, "question": "", "answer": ""},
        {"ok": True, "question": "Что?", "answer": "Отряд",
         "answer_kind": "organization"},
        {"ok": True, "question": "Чем герой рассекает демонов?",
         "answer": "меч ничирин"}]})
    assert len(client.prompts) == 1
    assert "до 3 РАЗНЫХ вопросов" in client.prompts[0]
    assert answers == ["Меч ничирин"]
    assert "демонов" in text


def test_no_good_variant_means_no_question():
    _client, text, answers = _ask({"items": [
        {"ok": False, "question": "", "answer": ""}]})
    assert (text, answers) == ("", [])


def test_a_number_that_is_part_of_the_name_is_not_a_season():
    """«Samurai 7» — это «7 самураев», а не седьмой сезон."""
    assert plot.season_number("7 самураев", "Samurai 7") == 1
    assert plot.season_title("7 самураев", "Samurai 7") == "7 самураев"
    # Обычный номер продолжения в ромадзи по-прежнему виден.
    assert plot.season_title("Атака титанов", "Shingeki no Kyojin 2") == \
        "Атака титанов — 2-й сезон"
