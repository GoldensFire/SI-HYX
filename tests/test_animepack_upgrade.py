"""Вкладка «Апгрейд пака»: спецвопросы, варианты названий и картинки.

Сеть не трогается вовсе: вместо ShikimoriApi подставляется FakeApi, считающий
запросы (кэш «один тайтл — один запрос» — часть поведения, а не оптимизация).
ffmpeg тоже не зовётся: кодирование картинки подменяется _fake_avif.
"""

import pytest

from animepack_upgrade import (
    SPECIAL_LABELS,
    UpgradeSettings,
    answer_queries,
    answer_query,
    example_lines,
    iter_questions,
    match_score,
    pick_card,
    is_typo,
    matched_by_typo,
    strip_year,
    tag_fn,
)
from animepack_upgrade_test_helpers import (
    BRYNHILDR,
    CharApi,
    FakeApi,
    LOOSE_CARD,
    NARUTO,
    TEGAMI,
    UENO,
    _answers,
    _out_root,
    _pack,
    _q4,
    _q5,
    _run,
)


# ── Функция 1: спецвопросы → обычные ─────────────────────────────────────────
def test_v5_special_types_are_removed(tmp_path):
    """Тип вопроса снимается со ВСЕХ спецвопросов формата v5."""
    content = _pack("".join(
        _q5(p, qtype=t) for p, t in ((100, "stake"), (200, "secret"),
                                     (300, "noRisk"), (400, "forAll"),
                                     (500, "stakeAll"))))
    result = _run(tmp_path, content, UpgradeSettings(add_titles=False))
    assert len(result.specials) == 5
    root, _ns = _out_root(result)
    assert all(q.get("type") is None for _r, _t, q in iter_questions(root))

def test_v5_special_params_are_removed_but_question_survives(tmp_path):
    """Убирается ровно то, что делало вопрос особым: тема и цена «кота» и режим
    выбора. Сам вопрос, ответ и цена вопроса остаются на месте."""
    params = ('<param name="theme">Чужая тема</param>'
              '<param name="price" type="numberSet"><numberSet minimum="50"/></param>'
              '<param name="selectionMode">exceptCurrent</param>')
    content = _pack(_q5(400, answer="Блич", qtype="secret", params=params))
    result = _run(tmp_path, content, UpgradeSettings(add_titles=False))
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    q = root.find(f'.//{tag("question")}')
    assert q.get("price") == "400"              # цена вопроса не тронута
    assert q.get("type") is None
    names = {p.get("name") for p in q.findall(f'{tag("params")}/{tag("param")}')}
    assert names == {"question"}
    assert q.find(f'{tag("right")}/{tag("answer")}').text == "Блич"

def test_v4_type_element_is_removed(tmp_path):
    """Формат v4 держит тип дочерним <type name="cat"> — вместе с параметрами."""
    content = _pack(_q4(200, qtype="cat") + _q4(300, qtype="auction"))
    result = _run(tmp_path, content, UpgradeSettings(add_titles=False))
    assert [c.before for c in result.specials] == ["с секретом", "со ставкой"]
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    assert root.find(f'.//{tag("type")}') is None
    assert len(root.findall(f'.//{tag("scenario")}')) == 2

def test_simple_questions_are_left_alone(tmp_path):
    content = _pack(_q5(100) + _q5(200, qtype="simple") + _q4(300))
    result = _run(tmp_path, content, UpgradeSettings(add_titles=False))
    assert result.specials == [] and result.total == 0

def test_secret_no_question_is_skipped_by_default(tmp_path):
    """«С секретом без вопроса» (secretNoQuestion) — это выдача денег сразу:
    самого вопроса в нём нет, обычным его не сделать."""
    content = _pack(_q5(100, qtype="secretNoQuestion"))
    result = _run(tmp_path, content, UpgradeSettings(add_titles=False))
    assert result.specials == []
    assert len(result.skipped_specials) == 1
    assert result.skipped_specials[0].before == SPECIAL_LABELS["secretnoquestion"]
    root, ns = _out_root(result)
    assert root.find(f'.//{tag_fn(ns)("question")}').get("type") == "secretNoQuestion"

def test_secret_no_question_converted_when_asked(tmp_path):
    content = _pack(_q5(100, qtype="secretNoQuestion"))
    result = _run(tmp_path, content,
                  UpgradeSettings(add_titles=False, strip_no_question=True))
    assert len(result.specials) == 1 and not result.skipped_specials

def test_question_without_content_is_skipped(tmp_path):
    """Пустой спецвопрос обычным делать нечем — о нём просто пишется в отчёт."""
    content = _pack('<question price="100" type="secret">'
                    "<right><answer>Ответ</answer></right></question>")
    result = _run(tmp_path, content,
                  UpgradeSettings(add_titles=False, strip_no_question=True))
    assert result.specials == [] and len(result.skipped_specials) == 1
    assert "нет самого вопроса" in result.skipped_specials[0].after

def test_specials_untouched_when_function_is_off(tmp_path):
    content = _pack(_q5(100, answer="Наруто", qtype="secret"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, add_titles=True))
    root, ns = _out_root(result)
    assert root.find(f'.//{tag_fn(ns)("question")}').get("type") == "secret"
    assert result.specials == [] and len(result.titles) == 1

# ── Функция 2: варианты названий ─────────────────────────────────────────────
def test_answer_query_strips_song_year_and_quotes():
    assert answer_query("Наруто OP1 (2002) — 『Go!!!』") == "Наруто"
    assert answer_query("«Блич» (аниме)") == "Блич"
    # Косую черту answer_query не трогает («Fate/Zero» — целое название);
    # разбирает её answer_queries, и только вторым заходом.
    assert answer_query("Наруто / Naruto") == "Наруто / Naruto"
    assert answer_query("  Стальной алхимик  ") == "Стальной алхимик"

def test_answer_queries_try_the_title_before_the_dash():
    """Живые паки пишут «Название - Песня» обычным дефисом: голое название
    получается только вторым заходом."""
    assert answer_queries(["Эхо террора - Trigger"]) == [
        "Эхо террора - Trigger", "Эхо террора"]
    # Тире БЕЗ пробелов — часть названия, резать его нельзя.
    assert answer_queries(["Жожо-2"]) == ["Жожо-2"]

def test_answer_queries_use_other_answers_and_dedupe():
    answers = ["Корона грешника - My Dearest", "Корона грешника",
               "Guilty Crown"]
    assert answer_queries(answers) == [
        "Корона грешника - My Dearest", "Корона грешника", "Guilty Crown"]
    assert answer_queries(answers, use_others=False) == [
        "Корона грешника - My Dearest", "Корона грешника"]

def test_answer_queries_are_capped_and_filtered():
    answers = ["Раз - Два", "Три", "Да", "1945", "Четыре", "Пять"]
    queries = answer_queries(answers)
    assert len(queries) == 4                      # MAX_QUERIES_PER_QUESTION
    assert "Да" not in queries and "1945" not in queries

def test_title_found_by_a_later_answer(tmp_path):
    """Первый ответ — «Название - Песня», второй — голое название: тайтл всё
    равно должен опознаться."""
    api = FakeApi()
    content = _pack(_q5(100, right="<right><answer>Наруто - Go!!!</answer>"
                                   "<answer>Наруто</answer></right>"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False),
                  api=api)
    assert len(result.titles) == 1
    assert "Naruto" in result.titles[0].added
    # Первый вариант ответа в отчёте остаётся тем, что видит ведущий.
    assert result.titles[0].before == "Наруто - Go!!!"

def test_other_answers_are_not_searched_when_switched_off(tmp_path):
    api = FakeApi()
    content = _pack(_q5(100, right="<right><answer>Ерунда какая-то</answer>"
                                   "<answer>Наруто</answer></right>"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False,
                                  use_other_answers=False), api=api)
    assert result.titles == [] and "Наруто" not in api.calls

def test_variants_are_appended_to_answers(tmp_path):
    content = _pack(_q5(100, answer="Наруто (2002)"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False))
    assert len(result.titles) == 1
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    answers = [a.text for a in root.findall(
        f'.//{tag("right")}/{tag("answer")}')]
    assert answers[0] == "Наруто (2002)"        # исходный ответ не тронут
    assert "Naruto" in answers
    assert "Наруто. Книга первая" in answers
    # «Наруто» в паке уже написано (внутри первого ответа) — второй раз не идёт.
    assert "Наруто" not in answers

def test_variant_already_written_in_the_pack_is_not_repeated(tmp_path):
    """Живой пак пишет «Название - Песня»: голое название там уже есть, и
    дописывать его отдельной строкой незачем (просьба пользователя)."""
    content = _pack(_q5(100, answer="Наруто - Go!!!"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False))
    added = result.titles[0].added
    assert "Наруто" not in added and "Naruto" in added

def test_year_is_never_written_into_the_answer(tmp_path):
    """Год Shikimori держит прямо в названии у части тайтлов — в ответ он не
    идёт ни в каком виде."""
    atom = dict(NARUTO, russian="Могучий Атом (2003)", name="Tetsuwan Atom",
                english="Astro Boy (2003)", licenseNameRu="",
                synonyms=["Астробой [2003]"])
    content = _pack(_q5(100, answer="Могучий Атом"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False),
                  api=FakeApi([atom]))
    added = result.titles[0].added
    assert added == ["Tetsuwan Atom", "Astro Boy", "Астробой"]

def test_strip_year_leaves_the_name_alone():
    assert strip_year("Могучий Атом (2003)") == "Могучий Атом"
    assert strip_year("Астробой [2003]") == "Астробой"
    assert strip_year("Ковбой Бибоп") == "Ковбой Бибоп"
    # Год не в хвосте — часть названия, резать нельзя.
    assert strip_year("2001 год: Космическая одиссея") == \
        "2001 год: Космическая одиссея"

def test_cjk_variants_are_never_added(tmp_path):
    """Японское название и иероглифические синонимы в ответ не идут: ведущему
    их не прочитать, игроку не набрать."""
    content = _pack(_q5(100, answer="Наруто"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False))
    assert all("ナルト" not in v for v in result.titles[0].added)

def test_existing_answers_are_not_duplicated(tmp_path):
    content = _pack(_q5(100, right="<right><answer>Наруто</answer>"
                                   "<answer>Naruto</answer></right>"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False))
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    answers = [a.text for a in root.findall(f'.//{tag("right")}/{tag("answer")}')]
    assert answers.count("Naruto") == 1

def test_all_variant_kinds_are_always_added(tmp_path):
    """Выбора видов названий больше нет: дописываются все сразу (просьба
    пользователя), а иероглифика не берётся вовсе."""
    content = _pack(_q5(100, answer="Наруто"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False))
    added = result.titles[0].added
    assert added == ["Naruto", "Наруто. Книга первая", "Наруто ТВ-1"]
    assert not any("ナ" in v for v in added)

def test_max_variants_caps_the_list(tmp_path):
    content = _pack(_q5(100, answer="Наруто"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, max_variants=1))
    assert len(result.titles[0].added) == 1

def test_unknown_answer_is_left_alone(tmp_path):
    content = _pack(_q5(100, answer="Столица Франции"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False))
    assert result.titles == [] and result.not_found == 1
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    assert len(root.findall(f'.//{tag("right")}/{tag("answer")}')) == 1

def test_short_and_numeric_answers_are_not_searched(tmp_path):
    """Ответы вроде «Да» и «1945» на Shikimori не ищутся вовсе."""
    api = FakeApi()
    content = _pack(_q5(100, answer="Да") + _q5(200, answer="1945"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False),
                  api=api)
    assert api.calls == [] and result.checked_answers == 0

def test_same_title_is_queried_once(tmp_path):
    """Один тайтл на пак — один запрос: Shikimori держит 5 запросов в секунду."""
    api = FakeApi()
    content = _pack(_q5(100, answer="Наруто (2002)")
                    + _q5(200, answer="наруто")
                    + _q5(300, answer="Блич"))
    _run(tmp_path, content, UpgradeSettings(strip_specials=False), api=api)
    assert len(api.calls) == 2

def test_titles_untouched_when_function_is_off(tmp_path):
    api = FakeApi()
    content = _pack(_q5(100, answer="Наруто", qtype="stake"))
    result = _run(tmp_path, content,
                  UpgradeSettings(add_titles=False), api=api)
    assert api.calls == [] and result.titles == []
    assert len(result.specials) == 1


def test_failed_search_does_not_break_the_run(tmp_path):
    class Broken(FakeApi):
        def search_animes_by_name(self, name, limit=0):
            raise RuntimeError("Shikimori лёг")

    content = _pack(_q5(100, answer="Наруто"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False),
                  api=Broken())
    assert result.titles == [] and result.path        # пак всё равно записан

# ── Опознание тайтла ─────────────────────────────────────────────────────────
def test_strict_match_needs_exact_name():
    cards = [NARUTO]
    assert pick_card("наруто!", cards, strict=True) is NARUTO   # знаки не в счёт
    assert pick_card("Наруто: Ураганные хроники", cards, strict=True) is None

def test_loose_match_accepts_close_names():
    """С выключенной строгостью засчитывается опечатка, но не другой тайтл."""
    assert pick_card("Нарутоо", [NARUTO], strict=False) is NARUTO
    assert pick_card("Блич", [NARUTO], strict=False) is None


def test_typo_in_the_answer_still_finds_the_title():
    """Опечатка в букву — тот же тайтл, и строгость этому не мешает."""
    assert pick_card("Gokukoku no Brunhildr", [BRYNHILDR], strict=True) is BRYNHILDR
    assert match_score("Gokukoku no Brunhildr", BRYNHILDR) == 1.0
    assert matched_by_typo("Gokukoku no Brunhildr", BRYNHILDR) is True
    assert matched_by_typo("Gokukoku no Brynhildr", BRYNHILDR) is False

@pytest.mark.parametrize("a, b", [
    ("gokukoku no brunhildr", "gokukoku no brynhildr"),   # та самая буква
    ("overlord", "overload"),
    ("gochuumon wa usagi desu ka", "gochuumon wa usagi des ka"),  # длинное: две
])
def test_typo_is_the_same_title(a, b):
    assert is_typo(a, b) is True

@pytest.mark.parametrize("a, b", [
    ("air", "aria"),                        # короткие — только слово в слово
    ("naruto", "naruto ураганные хроники"),  # слов не поровну
    ("hellsing", "hellsing ultimate"),
    ("sword art online ii", "sword art online iii"),   # номер сезона
    ("yuru camp 2", "yuru camp 3"),
    ("bakemonogatari", "nisemonogatari"),   # разница в три буквы
])
def test_typo_does_not_swallow_other_titles(a, b):
    assert is_typo(a, b) is False

def test_typo_titles_are_counted_and_reported(tmp_path):
    class Fuzzy(FakeApi):
        """Shikimori опечатку в запросе переживает и тайтл всё-таки отдаёт
        (проверено живым запросом) — подстрочный поиск FakeApi так не умеет."""

        def search_animes_by_name(self, name, limit=0):
            self.calls.append(name)
            return list(self.cards)

    api = Fuzzy([BRYNHILDR])
    content = _pack(_q5(100, answer="Gokukoku no Brunhildr"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, add_poster=False,
                                  check_characters=False), api=api)
    assert result.typo_titles == 1 and len(result.titles) == 1
    assert "Gokukoku no Brynhildr" in result.titles[0].added
    assert any("опечаткой" in line for line in example_lines(result))


def test_extra_space_in_the_answer_is_the_same_title():
    assert pick_card("Tegami bachi", [TEGAMI], strict=True) is TEGAMI
    assert match_score("Tegami bachi", TEGAMI) == 1.0
    assert matched_by_typo("Tegami bachi", TEGAMI) is True

def test_short_names_are_not_glued_together():
    """«K-On!» склеенное — это «kon», уже другое слово: пробелы прощаются
    только длинным названиям."""
    kon = dict(TEGAMI, name="Kon", russian=None)
    assert pick_card("K-On!", [kon], strict=True) is None


def test_character_answer_is_left_alone(tmp_path):
    api = CharApi([LOOSE_CARD], chars=[{"name": "Teto Kasane", "russian": "Тето Касанэ"}])
    content = _pack(_q5(100, answer="Teto Kasane"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, strict_match=False),
                  api=api)
    assert api.char_calls == ["Teto Kasane"]
    assert result.titles == [] and result.posters == []
    assert len(result.skipped_titles) == 1
    assert result.skipped_titles[0].kind == "character"
    assert _answers(result) == ["Teto Kasane"]

def test_exact_title_is_not_second_guessed(tmp_path):
    """«Shiki», «Monster», «Goblin Slayer» — настоящие аниме, у которых герой
    зовётся так же, и точный персонаж там находится всегда. Раз собственное
    название совпало точь-в-точь, спрашивать про персонажа незачем."""
    card = {"id": 8, "malId": 8, "russian": "Усопшие", "name": "Shiki",
            "english": "Corpse Demon", "licenseNameRu": "", "synonyms": [],
            "kind": "tv"}
    api = CharApi([card], chars=[{"name": "Shiki", "russian": "Сики"}])
    content = _pack(_q5(100, answer="Shiki"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False),
                  api=api)
    assert api.char_calls == []                 # лишнего запроса не было
    assert result.titles and result.skipped_titles == []
    assert "Усопшие" in _answers(result)

def test_character_check_can_be_switched_off(tmp_path):
    api = CharApi([LOOSE_CARD], chars=[{"name": "Teto Kasane", "russian": "Тето Касанэ"}])
    content = _pack(_q5(100, answer="Teto Kasane"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, strict_match=False,
                                  check_characters=False), api=api)
    assert api.char_calls == [] and result.skipped_titles == []
    assert result.titles

def test_same_character_is_asked_once(tmp_path):
    api = CharApi([LOOSE_CARD], chars=[{"name": "Teto Kasane", "russian": "Тето Касанэ"}])
    content = _pack(_q5(100, answer="Teto Kasane") + _q5(200, answer="Teto Kasane"))
    _run(tmp_path, content,
         UpgradeSettings(strip_specials=False, strict_match=False), api=api)
    assert api.char_calls == ["Teto Kasane"]

def test_skipped_characters_are_reported(tmp_path):
    api = CharApi([LOOSE_CARD], chars=[{"name": "Teto Kasane", "russian": "Тето Касанэ"}])
    content = _pack(_q5(100, answer="Teto Kasane"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, strict_match=False),
                  api=api)
    lines = example_lines(result)
    assert any("пропущено как имена персонажей: 1" in l for l in lines)


def test_slash_answer_is_split_into_both_names():
    """«Ueno-san wa Bukiyou/ Неуклюжая Уэно» — это одно и то же название двумя
    строками: Shikimori и сам показывает тайтл так."""
    assert answer_queries(["Ueno-san wa Bukiyou/ Неуклюжая Уэно"]) == [
        "Ueno-san wa Bukiyou/ Неуклюжая Уэно", "Ueno-san wa Bukiyou",
        "Неуклюжая Уэно"]

def test_whole_answer_is_tried_before_its_parts():
    """«Fate/Zero» — цельное название, и находится оно раньше, чем дело дойдёт
    до разбиения по черте."""
    assert answer_queries(["Fate/Zero"])[0] == "Fate/Zero"

def test_slash_answer_finds_the_title(tmp_path):
    """Строкой целиком тайтл не опознаётся, а каждой частью — да."""
    api = FakeApi([UENO])
    content = _pack(_q5(100, answer="Ueno-san wa Bukiyou/ Неуклюжая Уэно"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False),
                  api=api)
    assert len(result.titles) == 1
    assert "Уэно-сан, какая же Вы неуклюжая" in _answers(result)
    assert "How Clumsy you are, Miss Ueno" in _answers(result)

def test_slash_answer_counts_as_an_exact_match(tmp_path):
    """Совпала часть — значит, совпало точно: постер и написание тут уместны."""
    kokoro = dict(UENO, id=11887, malId=11887, russian="Связь сердец",
                  name="Kokoro Connect", english="Kokoro Connect",
                  synonyms=["Kokoroco"])
    content = _pack(_q5(100, answer="Kokoro Connect/Связь сердец"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, add_poster=False),
                  api=FakeApi([kokoro]))
    assert result.exact_titles == 1
    assert "Kokoroco" in _answers(result)
