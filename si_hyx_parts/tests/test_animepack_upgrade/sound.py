# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_sound. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def _sound(name: str = "опенинг.mp3") -> str:
    return f'<item type="audio" isRef="True">{name}</item>'

_sound.__module__ = _api.__name__
_api._sound = _sound

def _items_of(q, ns):
    tag = _api.tag_fn(ns)
    return q.find(f'{tag("params")}/{tag("param")}').findall(tag("item"))

_items_of.__module__ = _api.__name__
_api._items_of = _items_of

def test_text_before_audio_plays_together(tmp_path):
    """Текст, за которым сразу идёт отрывок, включается вместе с ним."""
    content = _api._themes("Аниме|" + _api._q5_items(100, "<item>Назвать аниме</item>"
                                           + _api._sound()))
    result = _api._run(tmp_path, content, _api.ONLY_MERGE)
    assert [c.before for c in result.merged] == ["Назвать аниме"]
    root, ns = _api._out_root(result)
    _r, _t, q = next(_api.iter_questions(root))
    assert [i.get("waitForFinish") for i in _api._items_of(q, ns)] == ["False", None]

test_text_before_audio_plays_together.__module__ = _api.__name__
_api.test_text_before_audio_plays_together = test_text_before_audio_plays_together

def test_text_before_a_picture_is_left_alone(tmp_path):
    """Правило только про звук: картинку текст по-прежнему ждёт."""
    content = _api._themes("Аниме|" + _api._q5_items(100, "<item>Назвать аниме</item>"
                                           + _api._shot()))
    result = _api._run(tmp_path, content, _api.ONLY_MERGE)
    assert result.merged == []
    root, ns = _api._out_root(result)
    _r, _t, q = next(_api.iter_questions(root))
    assert all(i.get("waitForFinish") is None for i in _api._items_of(q, ns))

test_text_before_a_picture_is_left_alone.__module__ = _api.__name__
_api.test_text_before_a_picture_is_left_alone = test_text_before_a_picture_is_left_alone

def test_already_merged_text_is_not_touched(tmp_path):
    """Автор уже включил одновременное — правкой это не считается."""
    items = ('<item waitForFinish="False">Назвать аниме</item>' + _api._sound())
    result = _api._run(tmp_path, _api._themes("Аниме|" + _api._q5_items(100, items)),
                  _api.ONLY_MERGE)
    assert result.merged == []

test_already_merged_text_is_not_touched.__module__ = _api.__name__
_api.test_already_merged_text_is_not_touched = test_already_merged_text_is_not_touched

def test_merge_can_be_switched_off(tmp_path):
    s = _api.UpgradeSettings(strip_specials=False, add_titles=False,
                        compress_images=False, strip_repeated_text=False,
                        drop_empty_questions=False, compress_audio=False,
                        merge_text_audio=False)
    content = _api._themes("Аниме|" + _api._q5_items(100, "<item>Назвать аниме</item>"
                                           + _api._sound()))
    result = _api._run(tmp_path, content, s)
    assert result.merged == []
    root, ns = _api._out_root(result)
    _r, _t, q = next(_api.iter_questions(root))
    assert all(i.get("waitForFinish") is None for i in _api._items_of(q, ns))

test_merge_can_be_switched_off.__module__ = _api.__name__
_api.test_merge_can_be_switched_off = test_merge_can_be_switched_off

def test_v4_text_before_audio_gets_time_minus_one(tmp_path):
    """В v4 «играть одновременно» — это time="-1" у атома (Question.cs)."""
    q4 = ('<question price="100"><scenario><atom>Назвать аниме</atom>'
          '<atom type="voice">@опенинг.mp3</atom></scenario>'
          "<right><answer>Ответ</answer></right></question>")
    result = _api._run(tmp_path, _api._themes(f"Аниме|{q4}"), _api.ONLY_MERGE)
    assert [c.before for c in result.merged] == ["Назвать аниме"]
    root, ns = _api._out_root(result)
    _r, _t, q = next(_api.iter_questions(root))
    atoms = q.find(_api.tag_fn(ns)("scenario")).findall(_api.tag_fn(ns)("atom"))
    assert [a.get("time") for a in atoms] == ["-1", None]

test_v4_text_before_audio_gets_time_minus_one.__module__ = _api.__name__
_api.test_v4_text_before_audio_gets_time_minus_one = test_v4_text_before_audio_gets_time_minus_one

def test_merge_is_reported_in_the_table(tmp_path):
    content = _api._themes("Аниме|" + _api._q5_items(100, "<item>Назвать аниме</item>"
                                           + _api._sound()))
    result = _api._run(tmp_path, content, _api.ONLY_MERGE)
    change = result.merged[0]
    assert change.kind == "merge" and change.price == 100
    assert change in result.changes
    assert any("вместе со звуком" in line for line in _api.example_lines(result))

test_merge_is_reported_in_the_table.__module__ = _api.__name__
_api.test_merge_is_reported_in_the_table = test_merge_is_reported_in_the_table

def test_merge_leaves_the_text_in_place(tmp_path):
    """Ничего не удаляется и не заводится — правится только атрибут."""
    content = _api._themes("Аниме|" + _api._q5_items(100, "<item>Назвать аниме</item>"
                                           + _api._sound()))
    result = _api._run(tmp_path, content, _api.ONLY_MERGE)
    root, ns = _api._out_root(result)
    _r, _t, q = next(_api.iter_questions(root))
    items = _api._items_of(q, ns)
    assert [i.text for i in items] == ["Назвать аниме", "опенинг.mp3"]

test_merge_leaves_the_text_in_place.__module__ = _api.__name__
_api.test_merge_leaves_the_text_in_place = test_merge_leaves_the_text_in_place

def test_merge_helper_needs_the_audio_right_after(tmp_path):
    """Между текстом и звуком стоит картинка — трогать нечего."""
    root = _api.ET.fromstring(_api._q5_items(100, "<item>Текст</item>" + _api._shot()
                                   + _api._sound()))
    assert _api.merge_text_with_audio(root) == []

test_merge_helper_needs_the_audio_right_after.__module__ = _api.__name__
_api.test_merge_helper_needs_the_audio_right_after = test_merge_helper_needs_the_audio_right_after
