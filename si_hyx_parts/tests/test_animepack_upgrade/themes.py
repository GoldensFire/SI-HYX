# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_themes. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def _themes(*themes: str, round_name: str = "Раунд 1") -> str:
    """Пак из нескольких тем: [(имя темы, вопросы)] строками."""
    body = "".join(f'<theme name="{name}"><questions>{qs}</questions></theme>'
                   for name, qs in (t.split("|", 1) for t in themes))
    return ('<?xml version="1.0" encoding="utf-8"?>\n<package name="Пак">'
            f'<rounds><round name="{round_name}"><themes>{body}'
            "</themes></round></rounds></package>")

_themes.__module__ = _api.__name__
_api._themes = _themes

def test_repeated_text_is_removed_from_every_question(tmp_path):
    """«Назвать аниме» в каждом вопросе темы — лишние секунды: убираем."""
    qs = "".join(_api._q5_items(p, "<item>Назвать аниме</item>" + _api._shot())
                 for p in (100, 200, 300))
    result = _api._run(tmp_path, _api._themes(f"Аниме|{qs}"), _api.ONLY_REPEATS)
    assert len(result.repeats) == 3
    assert {c.before for c in result.repeats} == {"Назвать аниме"}
    assert [c.price for c in result.repeats] == [100, 200, 300]
    root, ns = _api._out_root(result)
    tag = _api.tag_fn(ns)
    for _r, _t, q in _api.iter_questions(root):
        items = q.find(f'{tag("params")}/{tag("param")}').findall(tag("item"))
        assert [i.get("type") for i in items] == ["image"]

test_repeated_text_is_removed_from_every_question.__module__ = _api.__name__
_api.test_repeated_text_is_removed_from_every_question = test_repeated_text_is_removed_from_every_question

def test_repeated_text_left_alone_if_one_question_lacks_it(tmp_path):
    """Правило — «в КАЖДОМ вопросе»: одного промаха хватает, чтобы не трогать."""
    qs = (_api._q5_items(100, "<item>Назвать аниме</item>" + _api._shot())
          + _api._q5_items(200, "<item>Назвать аниме</item>" + _api._shot())
          + _api._q5_items(300, "<item>Что за тайтл?</item>" + _api._shot()))
    result = _api._run(tmp_path, _api._themes(f"Аниме|{qs}"), _api.ONLY_REPEATS)
    assert result.repeats == []

test_repeated_text_left_alone_if_one_question_lacks_it.__module__ = _api.__name__
_api.test_repeated_text_left_alone_if_one_question_lacks_it = test_repeated_text_left_alone_if_one_question_lacks_it

def test_repeats_are_counted_per_theme(tmp_path):
    """Тема — своя единица счёта: в соседней тот же текст стоит не везде."""
    good = "".join(_api._q5_items(p, "<item>Назвать аниме</item>" + _api._shot())
                   for p in (100, 200))
    bad = (_api._q5_items(100, "<item>Назвать аниме</item>" + _api._shot())
           + _api._q5_items(200, "<item>Назвать песню</item>" + _api._shot()))
    result = _api._run(tmp_path, _api._themes(f"Аниме|{good}", f"Песни|{bad}"),
                  _api.ONLY_REPEATS)
    assert {c.theme_name for c in result.repeats} == {"Аниме"}
    assert len(result.repeats) == 2

test_repeats_are_counted_per_theme.__module__ = _api.__name__
_api.test_repeats_are_counted_per_theme = test_repeats_are_counted_per_theme

def test_theme_of_one_question_is_not_touched(tmp_path):
    """«В каждом» из одного вопроса значит «в единственном» — это не повтор."""
    qs = _api._q5_items(100, "<item>Назвать аниме</item>" + _api._shot())
    result = _api._run(tmp_path, _api._themes(f"Аниме|{qs}"), _api.ONLY_REPEATS)
    assert result.repeats == []

test_theme_of_one_question_is_not_touched.__module__ = _api.__name__
_api.test_theme_of_one_question_is_not_touched = test_theme_of_one_question_is_not_touched

def test_question_is_never_emptied(tmp_path):
    """Убрать пришлось бы всё содержимое — вопрос не трогаем вовсе."""
    qs = "".join(_api._q5_items(p, "<item>Назвать аниме</item>") for p in (100, 200))
    result = _api._run(tmp_path, _api._themes(f"Аниме|{qs}"), _api.ONLY_REPEATS)
    assert result.repeats == []
    root, ns = _api._out_root(result)
    assert len(root.findall(f'.//{_api.tag_fn(ns)("item")}')) == 2

test_question_is_never_emptied.__module__ = _api.__name__
_api.test_question_is_never_emptied = test_question_is_never_emptied

def test_long_text_is_not_a_caption(tmp_path):
    """Длинный текст — это сам вопрос, а не подпись: длину сторожит настройка."""
    long_text = ("Назвать аниме, отрывок из которого сейчас прозвучит в зале "
                 "и будет показан на экране")
    qs = "".join(_api._q5_items(p, f"<item>{long_text}</item>" + _api._shot())
                 for p in (100, 200))
    content = _api._themes(f"Аниме|{qs}")
    assert _api._run(tmp_path, content, _api.ONLY_REPEATS).repeats == []
    loose = _api.UpgradeSettings(strip_specials=False, add_titles=False,
                            compress_images=False, repeat_text_max_len=200)
    assert len(_api._run(tmp_path, content, loose).repeats) == 2

test_long_text_is_not_a_caption.__module__ = _api.__name__
_api.test_long_text_is_not_a_caption = test_long_text_is_not_a_caption

def test_repeat_matching_ignores_case_and_punctuation(tmp_path):
    """«Назвать аниме:» и «назвать аниме» — один и тот же текст."""
    qs = (_api._q5_items(100, "<item>Назвать аниме:</item>" + _api._shot())
          + _api._q5_items(200, "<item>назвать аниме</item>" + _api._shot()))
    result = _api._run(tmp_path, _api._themes(f"Аниме|{qs}"), _api.ONLY_REPEATS)
    assert len(result.repeats) == 2

test_repeat_matching_ignores_case_and_punctuation.__module__ = _api.__name__
_api.test_repeat_matching_ignores_case_and_punctuation = test_repeat_matching_ignores_case_and_punctuation

def test_v4_repeat_is_removed_before_the_marker(tmp_path):
    """В v4 текст лежит атомом сценария, а после маркера идёт уже ответ."""
    def q4(price):
        return (f'<question price="{price}"><scenario>'
                "<atom>Назвать аниме</atom>"
                '<atom type="image">@кадр.jpg</atom>'
                '<atom type="marker"/><atom>Назвать аниме</atom>'
                "</scenario><right><answer>Ответ</answer></right></question>")
    result = _api._run(tmp_path, _api._themes("Аниме|" + q4(100) + q4(200)), _api.ONLY_REPEATS)
    assert len(result.repeats) == 2
    root, ns = _api._out_root(result)
    tag = _api.tag_fn(ns)
    for scenario in root.findall(f'.//{tag("scenario")}'):
        kinds = [a.get("type") for a in scenario.findall(tag("atom"))]
        assert kinds == ["image", "marker", None]      # ответ за маркером цел

test_v4_repeat_is_removed_before_the_marker.__module__ = _api.__name__
_api.test_v4_repeat_is_removed_before_the_marker = test_v4_repeat_is_removed_before_the_marker

def test_repeats_can_be_switched_off(tmp_path):
    qs = "".join(_api._q5_items(p, "<item>Назвать аниме</item>" + _api._shot())
                 for p in (100, 200))
    s = _api.UpgradeSettings(strip_specials=False, add_titles=False,
                        compress_images=False, strip_repeated_text=False,
                        drop_empty_questions=False, compress_audio=False,
                        compress_video=False, merge_text_audio=False,
                        drop_unused=False)
    with _api.pytest.raises(_api.UpgradeError):
        _api._run(tmp_path, _api._themes(f"Аниме|{qs}"), s)

test_repeats_can_be_switched_off.__module__ = _api.__name__
_api.test_repeats_can_be_switched_off = test_repeats_can_be_switched_off

def test_repeats_are_reported(tmp_path):
    qs = "".join(_api._q5_items(p, "<item>Назвать аниме</item>" + _api._shot())
                 for p in (100, 200))
    result = _api._run(tmp_path, _api._themes(f"Аниме|{qs}"), _api.ONLY_REPEATS)
    lines = _api.example_lines(result)
    assert any("Повторяющихся подписей убрано: 2" in l for l in lines)
    assert any("«Назвать аниме»" in l for l in lines)

test_repeats_are_reported.__module__ = _api.__name__
_api.test_repeats_are_reported = test_repeats_are_reported
