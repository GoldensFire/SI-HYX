"""Апгрейд пака: пустые вопросы, повторы в темах и склейка текста со звуком."""
import xml.etree.ElementTree as ET

import pytest

from animepack_upgrade import (
    UpgradeError,
    UpgradeSettings,
    example_lines,
    iter_questions,
    iter_themes,
    merge_text_with_audio,
    tag_fn,
)
from animepack_upgrade_test_helpers import (
    ONLY_EMPTY,
    ONLY_MERGE,
    ONLY_REPEATS,
    _items_of,
    _out_root,
    _q5_empty,
    _q5_items,
    _run,
    _shot,
    _sound,
    _themes,
)


def test_repeated_text_is_removed_from_every_question(tmp_path):
    """«Назвать аниме» в каждом вопросе темы — лишние секунды: убираем."""
    qs = "".join(_q5_items(p, "<item>Назвать аниме</item>" + _shot())
                 for p in (100, 200, 300))
    result = _run(tmp_path, _themes(f"Аниме|{qs}"), ONLY_REPEATS)
    assert len(result.repeats) == 3
    assert {c.before for c in result.repeats} == {"Назвать аниме"}
    assert [c.price for c in result.repeats] == [100, 200, 300]
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    for _r, _t, q in iter_questions(root):
        items = q.find(f'{tag("params")}/{tag("param")}').findall(tag("item"))
        assert [i.get("type") for i in items] == ["image"]

def test_repeated_text_left_alone_if_one_question_lacks_it(tmp_path):
    """Правило — «в КАЖДОМ вопросе»: одного промаха хватает, чтобы не трогать."""
    qs = (_q5_items(100, "<item>Назвать аниме</item>" + _shot())
          + _q5_items(200, "<item>Назвать аниме</item>" + _shot())
          + _q5_items(300, "<item>Что за тайтл?</item>" + _shot()))
    result = _run(tmp_path, _themes(f"Аниме|{qs}"), ONLY_REPEATS)
    assert result.repeats == []

def test_repeats_are_counted_per_theme(tmp_path):
    """Тема — своя единица счёта: в соседней тот же текст стоит не везде."""
    good = "".join(_q5_items(p, "<item>Назвать аниме</item>" + _shot())
                   for p in (100, 200))
    bad = (_q5_items(100, "<item>Назвать аниме</item>" + _shot())
           + _q5_items(200, "<item>Назвать песню</item>" + _shot()))
    result = _run(tmp_path, _themes(f"Аниме|{good}", f"Песни|{bad}"),
                  ONLY_REPEATS)
    assert {c.theme_name for c in result.repeats} == {"Аниме"}
    assert len(result.repeats) == 2

def test_theme_of_one_question_is_not_touched(tmp_path):
    """«В каждом» из одного вопроса значит «в единственном» — это не повтор."""
    qs = _q5_items(100, "<item>Назвать аниме</item>" + _shot())
    result = _run(tmp_path, _themes(f"Аниме|{qs}"), ONLY_REPEATS)
    assert result.repeats == []

def test_question_is_never_emptied(tmp_path):
    """Убрать пришлось бы всё содержимое — вопрос не трогаем вовсе."""
    qs = "".join(_q5_items(p, "<item>Назвать аниме</item>") for p in (100, 200))
    result = _run(tmp_path, _themes(f"Аниме|{qs}"), ONLY_REPEATS)
    assert result.repeats == []
    root, ns = _out_root(result)
    assert len(root.findall(f'.//{tag_fn(ns)("item")}')) == 2

def test_long_text_is_not_a_caption(tmp_path):
    """Длинный текст — это сам вопрос, а не подпись: длину сторожит настройка."""
    long_text = ("Назвать аниме, отрывок из которого сейчас прозвучит в зале "
                 "и будет показан на экране")
    qs = "".join(_q5_items(p, f"<item>{long_text}</item>" + _shot())
                 for p in (100, 200))
    content = _themes(f"Аниме|{qs}")
    assert _run(tmp_path, content, ONLY_REPEATS).repeats == []
    loose = UpgradeSettings(strip_specials=False, add_titles=False,
                            compress_images=False, repeat_text_max_len=200)
    assert len(_run(tmp_path, content, loose).repeats) == 2

def test_repeat_matching_ignores_case_and_punctuation(tmp_path):
    """«Назвать аниме:» и «назвать аниме» — один и тот же текст."""
    qs = (_q5_items(100, "<item>Назвать аниме:</item>" + _shot())
          + _q5_items(200, "<item>назвать аниме</item>" + _shot()))
    result = _run(tmp_path, _themes(f"Аниме|{qs}"), ONLY_REPEATS)
    assert len(result.repeats) == 2

def test_v4_repeat_is_removed_before_the_marker(tmp_path):
    """В v4 текст лежит атомом сценария, а после маркера идёт уже ответ."""
    def q4(price):
        return (f'<question price="{price}"><scenario>'
                "<atom>Назвать аниме</atom>"
                '<atom type="image">@кадр.jpg</atom>'
                '<atom type="marker"/><atom>Назвать аниме</atom>'
                "</scenario><right><answer>Ответ</answer></right></question>")
    result = _run(tmp_path, _themes("Аниме|" + q4(100) + q4(200)), ONLY_REPEATS)
    assert len(result.repeats) == 2
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    for scenario in root.findall(f'.//{tag("scenario")}'):
        kinds = [a.get("type") for a in scenario.findall(tag("atom"))]
        assert kinds == ["image", "marker", None]      # ответ за маркером цел

def test_repeats_can_be_switched_off(tmp_path):
    qs = "".join(_q5_items(p, "<item>Назвать аниме</item>" + _shot())
                 for p in (100, 200))
    s = UpgradeSettings(strip_specials=False, add_titles=False,
                        compress_images=False, strip_repeated_text=False,
                        drop_empty_questions=False, compress_audio=False,
                        compress_video=False, merge_text_audio=False,
                        drop_unused=False)
    with pytest.raises(UpgradeError):
        _run(tmp_path, _themes(f"Аниме|{qs}"), s)

def test_repeats_are_reported(tmp_path):
    qs = "".join(_q5_items(p, "<item>Назвать аниме</item>" + _shot())
                 for p in (100, 200))
    result = _run(tmp_path, _themes(f"Аниме|{qs}"), ONLY_REPEATS)
    lines = example_lines(result)
    assert any("Повторяющихся подписей убрано: 2" in l for l in lines)
    assert any("«Назвать аниме»" in l for l in lines)

def test_text_before_audio_plays_together(tmp_path):
    """Текст, за которым сразу идёт отрывок, включается вместе с ним."""
    content = _themes("Аниме|" + _q5_items(100, "<item>Назвать аниме</item>"
                                           + _sound()))
    result = _run(tmp_path, content, ONLY_MERGE)
    assert [c.before for c in result.merged] == ["Назвать аниме"]
    root, ns = _out_root(result)
    _r, _t, q = next(iter_questions(root))
    assert [i.get("waitForFinish") for i in _items_of(q, ns)] == ["False", None]

def test_text_before_a_picture_is_left_alone(tmp_path):
    """Правило только про звук: картинку текст по-прежнему ждёт."""
    content = _themes("Аниме|" + _q5_items(100, "<item>Назвать аниме</item>"
                                           + _shot()))
    result = _run(tmp_path, content, ONLY_MERGE)
    assert result.merged == []
    root, ns = _out_root(result)
    _r, _t, q = next(iter_questions(root))
    assert all(i.get("waitForFinish") is None for i in _items_of(q, ns))

def test_already_merged_text_is_not_touched(tmp_path):
    """Автор уже включил одновременное — правкой это не считается."""
    items = ('<item waitForFinish="False">Назвать аниме</item>' + _sound())
    result = _run(tmp_path, _themes("Аниме|" + _q5_items(100, items)),
                  ONLY_MERGE)
    assert result.merged == []

def test_merge_can_be_switched_off(tmp_path):
    s = UpgradeSettings(strip_specials=False, add_titles=False,
                        compress_images=False, strip_repeated_text=False,
                        drop_empty_questions=False, compress_audio=False,
                        merge_text_audio=False)
    content = _themes("Аниме|" + _q5_items(100, "<item>Назвать аниме</item>"
                                           + _sound()))
    result = _run(tmp_path, content, s)
    assert result.merged == []
    root, ns = _out_root(result)
    _r, _t, q = next(iter_questions(root))
    assert all(i.get("waitForFinish") is None for i in _items_of(q, ns))

def test_v4_text_before_audio_gets_time_minus_one(tmp_path):
    """В v4 «играть одновременно» — это time="-1" у атома (Question.cs)."""
    q4 = ('<question price="100"><scenario><atom>Назвать аниме</atom>'
          '<atom type="voice">@опенинг.mp3</atom></scenario>'
          "<right><answer>Ответ</answer></right></question>")
    result = _run(tmp_path, _themes(f"Аниме|{q4}"), ONLY_MERGE)
    assert [c.before for c in result.merged] == ["Назвать аниме"]
    root, ns = _out_root(result)
    _r, _t, q = next(iter_questions(root))
    atoms = q.find(tag_fn(ns)("scenario")).findall(tag_fn(ns)("atom"))
    assert [a.get("time") for a in atoms] == ["-1", None]

def test_merge_is_reported_in_the_table(tmp_path):
    content = _themes("Аниме|" + _q5_items(100, "<item>Назвать аниме</item>"
                                           + _sound()))
    result = _run(tmp_path, content, ONLY_MERGE)
    change = result.merged[0]
    assert change.kind == "merge" and change.price == 100
    assert change in result.changes
    assert any("вместе со звуком" in line for line in example_lines(result))

def test_merge_leaves_the_text_in_place(tmp_path):
    """Ничего не удаляется и не заводится — правится только атрибут."""
    content = _themes("Аниме|" + _q5_items(100, "<item>Назвать аниме</item>"
                                           + _sound()))
    result = _run(tmp_path, content, ONLY_MERGE)
    root, ns = _out_root(result)
    _r, _t, q = next(iter_questions(root))
    items = _items_of(q, ns)
    assert [i.text for i in items] == ["Назвать аниме", "опенинг.mp3"]

def test_merge_helper_needs_the_audio_right_after(tmp_path):
    """Между текстом и звуком стоит картинка — трогать нечего."""
    root = ET.fromstring(_q5_items(100, "<item>Текст</item>" + _shot()
                                   + _sound()))
    assert merge_text_with_audio(root) == []

def test_empty_question_is_deleted_even_with_an_answer(tmp_path):
    """Просьба пользователя: пустой — значит вон, даже если ответ записан."""
    content = _themes("Аниме|" + _q5_empty(100, "Наруто")
                      + _q5_items(200, _shot()))
    result = _run(tmp_path, content, ONLY_EMPTY)
    assert len(result.empties) == 1
    assert result.empties[0].price == 100
    assert "Наруто" in result.empties[0].before
    root, ns = _out_root(result)
    prices = [q.get("price") for _r, _t, q in iter_questions(root)]
    assert prices == ["200"]

def test_question_without_params_at_all_is_deleted(tmp_path):
    content = _themes("Аниме|"
                      + '<question price="100">'
                      "<right><answer>Ответ</answer></right></question>"
                      + _q5_items(200, _shot()))
    assert len(_run(tmp_path, content, ONLY_EMPTY).empties) == 1

def test_v4_question_with_only_the_answer_after_marker_is_deleted(tmp_path):
    """В v4 всё, что после маркера, — уже ответ: вопросом это не считается."""
    content = _themes("Аниме|"
                      + '<question price="100"><scenario>'
                      '<atom type="marker"/><atom>@ответ.jpg</atom></scenario>'
                      "<right><answer>Ответ</answer></right></question>"
                      + _q5_items(200, _shot()))
    result = _run(tmp_path, content, ONLY_EMPTY)
    assert len(result.empties) == 1 and result.empties[0].price == 100

def test_question_with_media_only_is_not_empty(tmp_path):
    """Текста нет, но есть кадр — это полноценный вопрос."""
    content = _themes("Аниме|" + _q5_items(100, _shot())
                      + _q5_items(200, _shot()))
    assert _run(tmp_path, content, ONLY_EMPTY).empties == []

def test_theme_left_without_questions_goes_too(tmp_path):
    content = _themes("Пустая|" + _q5_empty(100),
                      "Аниме|" + _q5_items(200, _shot()))
    result = _run(tmp_path, content, ONLY_EMPTY)
    assert result.dropped_themes == 1
    root, _ns = _out_root(result)
    assert [name for _r, name, _qs in iter_themes(root)] == ["Аниме"]

def test_pack_of_only_empty_questions_is_left_alone(tmp_path):
    """Пустыми выглядят все вопросы — значит, содержимое лежит как-то иначе."""
    content = _themes("Аниме|" + _q5_empty(100) + _q5_empty(200))
    result = _run(tmp_path, content, ONLY_EMPTY)
    assert result.empties == []
    root, _ns = _out_root(result)
    assert len(list(iter_questions(root))) == 2

def test_empty_questions_survive_when_the_function_is_off(tmp_path):
    content = _themes("Аниме|" + _q5_empty(100) + _q5_items(200, _shot()))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, add_titles=False,
                                  compress_images=False, compress_audio=False,
                                  drop_empty_questions=False))
    assert result.empties == []
    root, _ns = _out_root(result)
    assert len(list(iter_questions(root))) == 2

def test_empty_questions_are_reported(tmp_path):
    content = _themes("Аниме|" + _q5_empty(100) + _q5_items(200, _shot()))
    lines = example_lines(_run(tmp_path, content, ONLY_EMPTY))
    assert any("Пустых вопросов удалено: 1" in line for line in lines)
