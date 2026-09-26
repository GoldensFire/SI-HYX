# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_q5_empty. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def _q5_empty(price: int, answer: str = "Ответ") -> str:
    """Вопрос v5, в котором нет ничего, кроме ответа."""
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content"/></params>'
            f"<right><answer>{answer}</answer></right></question>")

_q5_empty.__module__ = _api.__name__
_api._q5_empty = _q5_empty

def test_empty_question_is_deleted_even_with_an_answer(tmp_path):
    """Просьба пользователя: пустой — значит вон, даже если ответ записан."""
    content = _api._themes("Аниме|" + _api._q5_empty(100, "Наруто")
                      + _api._q5_items(200, _api._shot()))
    result = _api._run(tmp_path, content, _api.ONLY_EMPTY)
    assert len(result.empties) == 1
    assert result.empties[0].price == 100
    assert "Наруто" in result.empties[0].before
    root, ns = _api._out_root(result)
    prices = [q.get("price") for _r, _t, q in _api.iter_questions(root)]
    assert prices == ["200"]

test_empty_question_is_deleted_even_with_an_answer.__module__ = _api.__name__
_api.test_empty_question_is_deleted_even_with_an_answer = test_empty_question_is_deleted_even_with_an_answer

def test_question_without_params_at_all_is_deleted(tmp_path):
    content = _api._themes("Аниме|"
                      + '<question price="100">'
                      "<right><answer>Ответ</answer></right></question>"
                      + _api._q5_items(200, _api._shot()))
    assert len(_api._run(tmp_path, content, _api.ONLY_EMPTY).empties) == 1

test_question_without_params_at_all_is_deleted.__module__ = _api.__name__
_api.test_question_without_params_at_all_is_deleted = test_question_without_params_at_all_is_deleted

def test_v4_question_with_only_the_answer_after_marker_is_deleted(tmp_path):
    """В v4 всё, что после маркера, — уже ответ: вопросом это не считается."""
    content = _api._themes("Аниме|"
                      + '<question price="100"><scenario>'
                      '<atom type="marker"/><atom>@ответ.jpg</atom></scenario>'
                      "<right><answer>Ответ</answer></right></question>"
                      + _api._q5_items(200, _api._shot()))
    result = _api._run(tmp_path, content, _api.ONLY_EMPTY)
    assert len(result.empties) == 1 and result.empties[0].price == 100

test_v4_question_with_only_the_answer_after_marker_is_deleted.__module__ = _api.__name__
_api.test_v4_question_with_only_the_answer_after_marker_is_deleted = test_v4_question_with_only_the_answer_after_marker_is_deleted

def test_question_with_media_only_is_not_empty(tmp_path):
    """Текста нет, но есть кадр — это полноценный вопрос."""
    content = _api._themes("Аниме|" + _api._q5_items(100, _api._shot())
                      + _api._q5_items(200, _api._shot()))
    assert _api._run(tmp_path, content, _api.ONLY_EMPTY).empties == []

test_question_with_media_only_is_not_empty.__module__ = _api.__name__
_api.test_question_with_media_only_is_not_empty = test_question_with_media_only_is_not_empty

def test_theme_left_without_questions_goes_too(tmp_path):
    content = _api._themes("Пустая|" + _api._q5_empty(100),
                      "Аниме|" + _api._q5_items(200, _api._shot()))
    result = _api._run(tmp_path, content, _api.ONLY_EMPTY)
    assert result.dropped_themes == 1
    root, _ns = _api._out_root(result)
    assert [name for _r, name, _qs in _api.iter_themes(root)] == ["Аниме"]

test_theme_left_without_questions_goes_too.__module__ = _api.__name__
_api.test_theme_left_without_questions_goes_too = test_theme_left_without_questions_goes_too

def test_pack_of_only_empty_questions_is_left_alone(tmp_path):
    """Пустыми выглядят все вопросы — значит, содержимое лежит как-то иначе."""
    content = _api._themes("Аниме|" + _api._q5_empty(100) + _api._q5_empty(200))
    result = _api._run(tmp_path, content, _api.ONLY_EMPTY)
    assert result.empties == []
    root, _ns = _api._out_root(result)
    assert len(list(_api.iter_questions(root))) == 2

test_pack_of_only_empty_questions_is_left_alone.__module__ = _api.__name__
_api.test_pack_of_only_empty_questions_is_left_alone = test_pack_of_only_empty_questions_is_left_alone

def test_empty_questions_survive_when_the_function_is_off(tmp_path):
    content = _api._themes("Аниме|" + _api._q5_empty(100) + _api._q5_items(200, _api._shot()))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, add_titles=False,
                                  compress_images=False, compress_audio=False,
                                  drop_empty_questions=False))
    assert result.empties == []
    root, _ns = _api._out_root(result)
    assert len(list(_api.iter_questions(root))) == 2

test_empty_questions_survive_when_the_function_is_off.__module__ = _api.__name__
_api.test_empty_questions_survive_when_the_function_is_off = test_empty_questions_survive_when_the_function_is_off

def test_empty_questions_are_reported(tmp_path):
    content = _api._themes("Аниме|" + _api._q5_empty(100) + _api._q5_items(200, _api._shot()))
    lines = _api.example_lines(_api._run(tmp_path, content, _api.ONLY_EMPTY))
    assert any("Пустых вопросов удалено: 1" in line for line in lines)

test_empty_questions_are_reported.__module__ = _api.__name__
_api.test_empty_questions_are_reported = test_empty_questions_are_reported
