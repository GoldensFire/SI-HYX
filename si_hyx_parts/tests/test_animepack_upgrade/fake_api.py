# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""FakeApi. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


class FakeApi:
    """Shikimori без сети: отдаёт заранее заданные карточки и считает запросы."""

    def __init__(self, cards=None):
        self.cards = list(cards if cards is not None else [_api.NARUTO, _api.BLEACH])
        self.calls = []

    def search_animes_by_name(self, name, limit=0):
        self.calls.append(name)
        needle = _api.norm_title(name)
        # Грубая имитация поиска: отдаём всё, что хоть как-то похоже.
        return [c for c in self.cards
                if any(needle in _api.norm_title(n) or _api.norm_title(n) in needle
                       for n in [c.get("russian"), c.get("name"),
                                 c.get("english")] if n)]

FakeApi.__module__ = _api.__name__
_api.FakeApi = FakeApi

def _run(tmp_path, content, s=None, api=None, **kw):
    s = s or _api.UpgradeSettings()
    up = _api.PackUpgrader(_api._siq(tmp_path, content), s, api=api or _api.FakeApi(), **kw)
    return up.run()

_run.__module__ = _api.__name__
_api._run = _run

def _out_root(result):
    with _api.zipfile.ZipFile(result.path) as zf:
        return _api.parse_content(zf.read("content.xml"))

_out_root.__module__ = _api.__name__
_api._out_root = _out_root

# ── Функция 1: спецвопросы → обычные ─────────────────────────────────────────
def test_v5_special_types_are_removed(tmp_path):
    """Тип вопроса снимается со ВСЕХ спецвопросов формата v5."""
    content = _api._pack("".join(
        _api._q5(p, qtype=t) for p, t in ((100, "stake"), (200, "secret"),
                                     (300, "noRisk"), (400, "forAll"),
                                     (500, "stakeAll"))))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(add_titles=False))
    assert len(result.specials) == 5
    root, _ns = _api._out_root(result)
    assert all(q.get("type") is None for _r, _t, q in _api.iter_questions(root))

test_v5_special_types_are_removed.__module__ = _api.__name__
_api.test_v5_special_types_are_removed = test_v5_special_types_are_removed

def test_v5_special_params_are_removed_but_question_survives(tmp_path):
    """Убирается ровно то, что делало вопрос особым: тема и цена «кота» и режим
    выбора. Сам вопрос, ответ и цена вопроса остаются на месте."""
    params = ('<param name="theme">Чужая тема</param>'
              '<param name="price" type="numberSet"><numberSet minimum="50"/></param>'
              '<param name="selectionMode">exceptCurrent</param>')
    content = _api._pack(_api._q5(400, answer="Блич", qtype="secret", params=params))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(add_titles=False))
    root, ns = _api._out_root(result)
    tag = _api.tag_fn(ns)
    q = root.find(f'.//{tag("question")}')
    assert q.get("price") == "400"              # цена вопроса не тронута
    assert q.get("type") is None
    names = {p.get("name") for p in q.findall(f'{tag("params")}/{tag("param")}')}
    assert names == {"question"}
    assert q.find(f'{tag("right")}/{tag("answer")}').text == "Блич"

test_v5_special_params_are_removed_but_question_survives.__module__ = _api.__name__
_api.test_v5_special_params_are_removed_but_question_survives = test_v5_special_params_are_removed_but_question_survives

def test_v4_type_element_is_removed(tmp_path):
    """Формат v4 держит тип дочерним <type name="cat"> — вместе с параметрами."""
    content = _api._pack(_api._q4(200, qtype="cat") + _api._q4(300, qtype="auction"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(add_titles=False))
    assert [c.before for c in result.specials] == ["с секретом", "со ставкой"]
    root, ns = _api._out_root(result)
    tag = _api.tag_fn(ns)
    assert root.find(f'.//{tag("type")}') is None
    assert len(root.findall(f'.//{tag("scenario")}')) == 2

test_v4_type_element_is_removed.__module__ = _api.__name__
_api.test_v4_type_element_is_removed = test_v4_type_element_is_removed

def test_simple_questions_are_left_alone(tmp_path):
    content = _api._pack(_api._q5(100) + _api._q5(200, qtype="simple") + _api._q4(300))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(add_titles=False))
    assert result.specials == [] and result.total == 0

test_simple_questions_are_left_alone.__module__ = _api.__name__
_api.test_simple_questions_are_left_alone = test_simple_questions_are_left_alone

def test_secret_no_question_is_skipped_by_default(tmp_path):
    """«С секретом без вопроса» (secretNoQuestion) — это выдача денег сразу:
    самого вопроса в нём нет, обычным его не сделать."""
    content = _api._pack(_api._q5(100, qtype="secretNoQuestion"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(add_titles=False))
    assert result.specials == []
    assert len(result.skipped_specials) == 1
    assert result.skipped_specials[0].before == _api.SPECIAL_LABELS["secretnoquestion"]
    root, ns = _api._out_root(result)
    assert root.find(f'.//{_api.tag_fn(ns)("question")}').get("type") == "secretNoQuestion"

test_secret_no_question_is_skipped_by_default.__module__ = _api.__name__
_api.test_secret_no_question_is_skipped_by_default = test_secret_no_question_is_skipped_by_default

def test_secret_no_question_converted_when_asked(tmp_path):
    content = _api._pack(_api._q5(100, qtype="secretNoQuestion"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(add_titles=False, strip_no_question=True))
    assert len(result.specials) == 1 and not result.skipped_specials

test_secret_no_question_converted_when_asked.__module__ = _api.__name__
_api.test_secret_no_question_converted_when_asked = test_secret_no_question_converted_when_asked

def test_question_without_content_is_skipped(tmp_path):
    """Пустой спецвопрос обычным делать нечем — о нём просто пишется в отчёт."""
    content = _api._pack('<question price="100" type="secret">'
                    "<right><answer>Ответ</answer></right></question>")
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(add_titles=False, strip_no_question=True))
    assert result.specials == [] and len(result.skipped_specials) == 1
    assert "нет самого вопроса" in result.skipped_specials[0].after

test_question_without_content_is_skipped.__module__ = _api.__name__
_api.test_question_without_content_is_skipped = test_question_without_content_is_skipped

def test_specials_untouched_when_function_is_off(tmp_path):
    content = _api._pack(_api._q5(100, answer="Наруто", qtype="secret"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, add_titles=True))
    root, ns = _api._out_root(result)
    assert root.find(f'.//{_api.tag_fn(ns)("question")}').get("type") == "secret"
    assert result.specials == [] and len(result.titles) == 1

test_specials_untouched_when_function_is_off.__module__ = _api.__name__
_api.test_specials_untouched_when_function_is_off = test_specials_untouched_when_function_is_off

# ── Функция 2: варианты названий ─────────────────────────────────────────────
def test_answer_query_strips_song_year_and_quotes():
    assert _api.answer_query("Наруто OP1 (2002) — 『Go!!!』") == "Наруто"
    assert _api.answer_query("«Блич» (аниме)") == "Блич"
    # Косую черту answer_query не трогает («Fate/Zero» — целое название);
    # разбирает её answer_queries, и только вторым заходом.
    assert _api.answer_query("Наруто / Naruto") == "Наруто / Naruto"
    assert _api.answer_query("  Стальной алхимик  ") == "Стальной алхимик"

test_answer_query_strips_song_year_and_quotes.__module__ = _api.__name__
_api.test_answer_query_strips_song_year_and_quotes = test_answer_query_strips_song_year_and_quotes

def test_answer_queries_try_the_title_before_the_dash():
    """Живые паки пишут «Название - Песня» обычным дефисом: голое название
    получается только вторым заходом."""
    assert _api.answer_queries(["Эхо террора - Trigger"]) == [
        "Эхо террора - Trigger", "Эхо террора"]
    # Тире БЕЗ пробелов — часть названия, резать его нельзя.
    assert _api.answer_queries(["Жожо-2"]) == ["Жожо-2"]

test_answer_queries_try_the_title_before_the_dash.__module__ = _api.__name__
_api.test_answer_queries_try_the_title_before_the_dash = test_answer_queries_try_the_title_before_the_dash

def test_answer_queries_use_other_answers_and_dedupe():
    answers = ["Корона грешника - My Dearest", "Корона грешника",
               "Guilty Crown"]
    assert _api.answer_queries(answers) == [
        "Корона грешника - My Dearest", "Корона грешника", "Guilty Crown"]
    assert _api.answer_queries(answers, use_others=False) == [
        "Корона грешника - My Dearest", "Корона грешника"]

test_answer_queries_use_other_answers_and_dedupe.__module__ = _api.__name__
_api.test_answer_queries_use_other_answers_and_dedupe = test_answer_queries_use_other_answers_and_dedupe

def test_answer_queries_are_capped_and_filtered():
    answers = ["Раз - Два", "Три", "Да", "1945", "Четыре", "Пять"]
    queries = _api.answer_queries(answers)
    assert len(queries) == 4                      # MAX_QUERIES_PER_QUESTION
    assert "Да" not in queries and "1945" not in queries

test_answer_queries_are_capped_and_filtered.__module__ = _api.__name__
_api.test_answer_queries_are_capped_and_filtered = test_answer_queries_are_capped_and_filtered

def test_title_found_by_a_later_answer(tmp_path):
    """Первый ответ — «Название - Песня», второй — голое название: тайтл всё
    равно должен опознаться."""
    api = _api.FakeApi()
    content = _api._pack(_api._q5(100, right="<right><answer>Наруто - Go!!!</answer>"
                                   "<answer>Наруто</answer></right>"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False),
                  api=api)
    assert len(result.titles) == 1
    assert "Naruto" in result.titles[0].added
    # Первый вариант ответа в отчёте остаётся тем, что видит ведущий.
    assert result.titles[0].before == "Наруто - Go!!!"

test_title_found_by_a_later_answer.__module__ = _api.__name__
_api.test_title_found_by_a_later_answer = test_title_found_by_a_later_answer

def test_other_answers_are_not_searched_when_switched_off(tmp_path):
    api = _api.FakeApi()
    content = _api._pack(_api._q5(100, right="<right><answer>Ерунда какая-то</answer>"
                                   "<answer>Наруто</answer></right>"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False,
                                  use_other_answers=False), api=api)
    assert result.titles == [] and "Наруто" not in api.calls

test_other_answers_are_not_searched_when_switched_off.__module__ = _api.__name__
_api.test_other_answers_are_not_searched_when_switched_off = test_other_answers_are_not_searched_when_switched_off

def test_variants_are_appended_to_answers(tmp_path):
    content = _api._pack(_api._q5(100, answer="Наруто (2002)"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False))
    assert len(result.titles) == 1
    root, ns = _api._out_root(result)
    tag = _api.tag_fn(ns)
    answers = [a.text for a in root.findall(
        f'.//{tag("right")}/{tag("answer")}')]
    assert answers[0] == "Наруто (2002)"        # исходный ответ не тронут
    assert "Naruto" in answers
    assert "Наруто. Книга первая" in answers
    # «Наруто» в паке уже написано (внутри первого ответа) — второй раз не идёт.
    assert "Наруто" not in answers

test_variants_are_appended_to_answers.__module__ = _api.__name__
_api.test_variants_are_appended_to_answers = test_variants_are_appended_to_answers

def test_variant_already_written_in_the_pack_is_not_repeated(tmp_path):
    """Живой пак пишет «Название - Песня»: голое название там уже есть, и
    дописывать его отдельной строкой незачем (просьба пользователя)."""
    content = _api._pack(_api._q5(100, answer="Наруто - Go!!!"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False))
    added = result.titles[0].added
    assert "Наруто" not in added and "Naruto" in added

test_variant_already_written_in_the_pack_is_not_repeated.__module__ = _api.__name__
_api.test_variant_already_written_in_the_pack_is_not_repeated = test_variant_already_written_in_the_pack_is_not_repeated

def test_year_is_never_written_into_the_answer(tmp_path):
    """Год Shikimori держит прямо в названии у части тайтлов — в ответ он не
    идёт ни в каком виде."""
    atom = dict(_api.NARUTO, russian="Могучий Атом (2003)", name="Tetsuwan Atom",
                english="Astro Boy (2003)", licenseNameRu="",
                synonyms=["Астробой [2003]"])
    content = _api._pack(_api._q5(100, answer="Могучий Атом"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False),
                  api=_api.FakeApi([atom]))
    added = result.titles[0].added
    assert added == ["Tetsuwan Atom", "Astro Boy", "Астробой"]

test_year_is_never_written_into_the_answer.__module__ = _api.__name__
_api.test_year_is_never_written_into_the_answer = test_year_is_never_written_into_the_answer

def test_strip_year_leaves_the_name_alone():
    assert _api.strip_year("Могучий Атом (2003)") == "Могучий Атом"
    assert _api.strip_year("Астробой [2003]") == "Астробой"
    assert _api.strip_year("Ковбой Бибоп") == "Ковбой Бибоп"
    # Год не в хвосте — часть названия, резать нельзя.
    assert _api.strip_year("2001 год: Космическая одиссея") == \
        "2001 год: Космическая одиссея"

test_strip_year_leaves_the_name_alone.__module__ = _api.__name__
_api.test_strip_year_leaves_the_name_alone = test_strip_year_leaves_the_name_alone

def test_cjk_variants_are_never_added(tmp_path):
    """Японское название и иероглифические синонимы в ответ не идут: ведущему
    их не прочитать, игроку не набрать."""
    content = _api._pack(_api._q5(100, answer="Наруто"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False))
    assert all("ナルト" not in v for v in result.titles[0].added)

test_cjk_variants_are_never_added.__module__ = _api.__name__
_api.test_cjk_variants_are_never_added = test_cjk_variants_are_never_added

def test_existing_answers_are_not_duplicated(tmp_path):
    content = _api._pack(_api._q5(100, right="<right><answer>Наруто</answer>"
                                   "<answer>Naruto</answer></right>"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False))
    root, ns = _api._out_root(result)
    tag = _api.tag_fn(ns)
    answers = [a.text for a in root.findall(f'.//{tag("right")}/{tag("answer")}')]
    assert answers.count("Naruto") == 1

test_existing_answers_are_not_duplicated.__module__ = _api.__name__
_api.test_existing_answers_are_not_duplicated = test_existing_answers_are_not_duplicated

def test_all_variant_kinds_are_always_added(tmp_path):
    """Выбора видов названий больше нет: дописываются все сразу (просьба
    пользователя), а иероглифика не берётся вовсе."""
    content = _api._pack(_api._q5(100, answer="Наруто"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False))
    added = result.titles[0].added
    assert added == ["Naruto", "Наруто. Книга первая", "Наруто ТВ-1"]
    assert not any("ナ" in v for v in added)

test_all_variant_kinds_are_always_added.__module__ = _api.__name__
_api.test_all_variant_kinds_are_always_added = test_all_variant_kinds_are_always_added

def test_max_variants_caps_the_list(tmp_path):
    content = _api._pack(_api._q5(100, answer="Наруто"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, max_variants=1))
    assert len(result.titles[0].added) == 1

test_max_variants_caps_the_list.__module__ = _api.__name__
_api.test_max_variants_caps_the_list = test_max_variants_caps_the_list

def test_unknown_answer_is_left_alone(tmp_path):
    content = _api._pack(_api._q5(100, answer="Столица Франции"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False))
    assert result.titles == [] and result.not_found == 1
    root, ns = _api._out_root(result)
    tag = _api.tag_fn(ns)
    assert len(root.findall(f'.//{tag("right")}/{tag("answer")}')) == 1

test_unknown_answer_is_left_alone.__module__ = _api.__name__
_api.test_unknown_answer_is_left_alone = test_unknown_answer_is_left_alone

def test_short_and_numeric_answers_are_not_searched(tmp_path):
    """Ответы вроде «Да» и «1945» на Shikimori не ищутся вовсе."""
    api = _api.FakeApi()
    content = _api._pack(_api._q5(100, answer="Да") + _api._q5(200, answer="1945"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False),
                  api=api)
    assert api.calls == [] and result.checked_answers == 0

test_short_and_numeric_answers_are_not_searched.__module__ = _api.__name__
_api.test_short_and_numeric_answers_are_not_searched = test_short_and_numeric_answers_are_not_searched

def test_same_title_is_queried_once(tmp_path):
    """Один тайтл на пак — один запрос: Shikimori держит 5 запросов в секунду."""
    api = _api.FakeApi()
    content = _api._pack(_api._q5(100, answer="Наруто (2002)")
                    + _api._q5(200, answer="наруто")
                    + _api._q5(300, answer="Блич"))
    _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False), api=api)
    assert len(api.calls) == 2

test_same_title_is_queried_once.__module__ = _api.__name__
_api.test_same_title_is_queried_once = test_same_title_is_queried_once

def test_titles_untouched_when_function_is_off(tmp_path):
    api = _api.FakeApi()
    content = _api._pack(_api._q5(100, answer="Наруто", qtype="stake"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(add_titles=False), api=api)
    assert api.calls == [] and result.titles == []
    assert len(result.specials) == 1

test_titles_untouched_when_function_is_off.__module__ = _api.__name__
_api.test_titles_untouched_when_function_is_off = test_titles_untouched_when_function_is_off
