# -*- coding: utf-8 -*-
"""Вкладка «Апгрейд пака»: спецвопросы, варианты названий и картинки.

Сеть не трогается вовсе: вместо ShikimoriApi подставляется FakeApi, считающий
запросы (кэш «один тайтл — один запрос» — часть поведения, а не оптимизация).
ffmpeg тоже не зовётся: кодирование картинки подменяется _fake_avif.
"""
import os
import threading
import xml.etree.ElementTree as ET
import zipfile

import pytest

from animepack_upgrade import (KNOWN_LABELS, LOOSE_THRESHOLD,
                               PackUpgrader, SPECIAL_LABELS,
                               UpgradeError, UpgradeSettings, answer_queries,
                               answer_query, audio_filter_chain, copy_zip_entry,
                               entry_basename, example_lines, is_media_entry,
                               iter_questions, iter_themes, known_labels_in,
                               loudnorm_filter,
                               match_score, media_jobs, nearest_bitrate,
                               nearest_height, normalize_profile,
                               norm_title, parse_content, parse_probe_codec,
                               parse_probe_kbps,
                               pick_card, referenced_names, remove_poster,
                               card_names, character_hit,
                               looks_like_character_name, read_pack_info,
                               is_book_theme, is_typo, matched_by_typo,
                               merge_text_with_audio,
                               recased, retarget_refs, spelling_names,
                               strip_year, synonym_only, tag_fn, title_variants,
                               unused_entries)
from filenames import escape_uri_string


# ── Фабрики ──────────────────────────────────────────────────────────────────
def _pack(questions: str, *, ns: str = "", version: str = "5") -> str:
    xmlns = f' xmlns="{ns}"' if ns else ""
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<package name="Пак" version="{version}"{xmlns}>'
            '<rounds><round name="Раунд 1"><themes><theme name="Тема А">'
            f'<questions>{questions}</questions>'
            "</theme></themes></round></rounds></package>")


def _q5(price: int, answer: str = "Ответ", qtype: str = "",
        params: str = "", right: str = "") -> str:
    """Вопрос формата v5 (SIGame 7)."""
    attr = f' type="{qtype}"' if qtype else ""
    body = right or f"<right><answer>{answer}</answer></right>"
    return (f'<question price="{price}"{attr}><params>'
            '<param name="question" type="content"><item>Текст</item></param>'
            f"{params}</params>{body}</question>")


def _q4(price: int, answer: str = "Ответ", qtype: str = "") -> str:
    """Вопрос формата v4 (тип — дочерним элементом)."""
    type_el = (f'<type name="{qtype}"><param name="theme">Тема кота</param>'
               f'<param name="price">300</param></type>') if qtype else ""
    return (f'<question price="{price}">{type_el}'
            "<scenario><atom>Текст</atom></scenario>"
            f"<right><answer>{answer}</answer></right></question>")


def _siq(tmp_path, content: str, name: str = "pack.siq", media=None) -> str:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", content)
        for arc, data in (media or {}).items():
            zf.writestr(arc, data, zipfile.ZIP_STORED)
    return str(path)


NARUTO = {
    "id": 20, "malId": 20, "russian": "Наруто", "name": "Naruto",
    "english": "Naruto", "japanese": "ナルト",
    "licenseNameRu": "Наруто. Книга первая",
    "synonyms": ["NARUTO -ナルト-", "Наруто ТВ-1"],
}
BLEACH = {"id": 269, "malId": 269, "russian": "Блич", "name": "Bleach",
          "english": "Bleach", "synonyms": [], "licenseNameRu": ""}


class FakeApi:
    """Shikimori без сети: отдаёт заранее заданные карточки и считает запросы."""

    def __init__(self, cards=None):
        self.cards = list(cards if cards is not None else [NARUTO, BLEACH])
        self.calls = []

    def search_animes_by_name(self, name, limit=0):
        self.calls.append(name)
        needle = norm_title(name)
        # Грубая имитация поиска: отдаём всё, что хоть как-то похоже.
        return [c for c in self.cards
                if any(needle in norm_title(n) or norm_title(n) in needle
                       for n in [c.get("russian"), c.get("name"),
                                 c.get("english")] if n)]


def _run(tmp_path, content, s=None, api=None, **kw):
    s = s or UpgradeSettings()
    up = PackUpgrader(_siq(tmp_path, content), s, api=api or FakeApi(), **kw)
    return up.run()


def _out_root(result):
    with zipfile.ZipFile(result.path) as zf:
        return parse_content(zf.read("content.xml"))


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


# Живой случай пользователя: в паке «Gokukoku no Brunhildr», на Shikimori —
# «Brynhildr». Из-за одной буквы пропадали и постер, и все варианты названия.
BRYNHILDR = {"id": 21, "malId": 21, "name": "Gokukoku no Brynhildr",
             "russian": "Тёмная кровь Брунгильды", "english": None,
             "licenseNameRu": "", "synonyms": [], "kind": "tv"}


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


# «Tegami bachi» в паке — «Tegamibachi» на Shikimori: то же слово, разбитое на
# слоги по вкусу писавшего.
TEGAMI = {"id": 22, "malId": 22, "name": "Tegamibachi",
          "russian": "Почтовая пчела", "english": None, "licenseNameRu": "",
          "synonyms": [], "kind": "tv"}


def test_extra_space_in_the_answer_is_the_same_title():
    assert pick_card("Tegami bachi", [TEGAMI], strict=True) is TEGAMI
    assert match_score("Tegami bachi", TEGAMI) == 1.0
    assert matched_by_typo("Tegami bachi", TEGAMI) is True


def test_short_names_are_not_glued_together():
    """«K-On!» склеенное — это «kon», уже другое слово: пробелы прощаются
    только длинным названиям."""
    kon = dict(TEGAMI, name="Kon", russian=None)
    assert pick_card("K-On!", [kon], strict=True) is None


# Ответ «Shelter»: так зовут и знаменитый клип Porter Robinson, и никому не
# известный фильм 2015 года — в пак вставлялась обложка фильма.
SHELTER_CLIP = {"id": 31, "malId": 31, "name": "Shelter (Music)",
                "russian": "Убежище", "english": "Shelter",
                "licenseNameRu": "", "synonyms": [], "kind": "music",
                "popularity": 221562.0}
SHELTER_MOVIE = {"id": 32, "malId": 32, "name": "Shelter", "russian": None,
                 "english": None, "licenseNameRu": "", "synonyms": [],
                 "kind": "movie", "popularity": 832.0}


def test_famous_clip_beats_an_unknown_namesake():
    """Обложка чужого фильма в ответе хуже, чем обложка того самого клипа."""
    assert pick_card("Shelter", [SHELTER_CLIP, SHELTER_MOVIE],
                     strict=True) is SHELTER_CLIP


def test_clip_without_a_namesake_is_still_not_an_answer():
    """Правило «клип — не тайтл» в силе: отбирать ответ клипу не у кого."""
    assert pick_card("Shelter", [SHELTER_CLIP], strict=True) is None


def test_clip_takes_the_answer_only_with_a_huge_edge():
    """Клип чуть известнее — по-прежнему не ответ: перевес нужен кратный."""
    known = dict(SHELTER_MOVIE, popularity=100000.0)
    assert pick_card("Shelter", [SHELTER_CLIP, known], strict=True) is known


def test_clip_matched_by_a_synonym_is_ignored_as_before():
    """«Teto Kasane» — синоним клипа «Yababaina»: имя героя ответа не отдаёт."""
    clip = {"id": 33, "malId": 33, "name": "Yababaina", "russian": None,
            "english": None, "licenseNameRu": "",
            "synonyms": ["Teto Kasane"], "kind": "music",
            "popularity": 900000.0}
    other = dict(SHELTER_MOVIE, name="Teto Kasane", popularity=10.0)
    assert pick_card("Teto Kasane", [clip, other], strict=True) is other


def test_match_score_is_one_for_any_of_the_names():
    assert match_score("Naruto", NARUTO) == 1.0
    assert match_score("Наруто. Книга первая", NARUTO) == 1.0
    assert match_score("совсем другое", NARUTO) < LOOSE_THRESHOLD


def test_title_variants_keep_generator_order():
    assert title_variants(NARUTO)[:3] == [
        "Naruto", "Наруто. Книга первая", "Наруто ТВ-1"]


# ── Файл на выходе ───────────────────────────────────────────────────────────
def test_source_pack_is_never_modified(tmp_path):
    content = _pack(_q5(100, answer="Наруто", qtype="secret"))
    src = _siq(tmp_path, content)
    before = open(src, "rb").read()
    up = PackUpgrader(src, UpgradeSettings(), api=FakeApi())
    result = up.run()
    assert result.path != src
    assert open(src, "rb").read() == before


def test_media_entries_are_copied_as_is(tmp_path):
    media = {"Audio/a.opus": b"opus-bytes", "Images/p.avif": b"avif-bytes"}
    content = _pack(_q5(100, answer="Наруто"))
    src = _siq(tmp_path, content, media=media)
    result = PackUpgrader(src, UpgradeSettings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/a.opus") == b"opus-bytes"
        assert zf.read("Images/p.avif") == b"avif-bytes"
        # Медиа лежит несжатым, как и в исходнике: пережимать opus/avif незачем.
        assert zf.getinfo("Images/p.avif").compress_type == zipfile.ZIP_STORED


def test_namespace_survives_the_rewrite(tmp_path):
    """Пак с пространством имён (v5 из SIQuester) должен остаться с ним же: с
    префиксами ns0: SIGame файл не откроет."""
    ns = "https://github.com/VladimirKhil/SI/blob/master/assets/siq_5.xsd"
    content = _pack(_q5(100, answer="Наруто", qtype="secret"), ns=ns)
    result = _run(tmp_path, content)
    with zipfile.ZipFile(result.path) as zf:
        raw = zf.read("content.xml").decode("utf-8")
    assert "ns0:" not in raw and f'xmlns="{ns}"' in raw
    root, out_ns = parse_content(raw.encode("utf-8"))
    assert out_ns == ns


def test_out_dir_setting_is_honoured(tmp_path):
    dest = tmp_path / "готовые"
    content = _pack(_q5(100, answer="Наруто"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, out_dir=str(dest)))
    assert result.path.startswith(str(dest))
    assert result.path.endswith(" (апгрейд).siq")


def test_second_run_does_not_overwrite_the_first(tmp_path):
    content = _pack(_q5(100, answer="Наруто"))
    src = _siq(tmp_path, content)
    first = PackUpgrader(src, UpgradeSettings(), api=FakeApi()).run().path
    second = PackUpgrader(src, UpgradeSettings(), api=FakeApi()).run().path
    assert first != second


def test_capitalized_content_xml_is_found(tmp_path):
    path = tmp_path / "c.siq"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Content.xml", _pack(_q5(100, qtype="stake")))
    result = PackUpgrader(str(path), UpgradeSettings(add_titles=False),
                          api=FakeApi()).run()
    assert len(result.specials) == 1
    with zipfile.ZipFile(result.path) as zf:
        assert "Content.xml" in zf.namelist()


# ── Отказы и остановка ───────────────────────────────────────────────────────
def test_broken_archive_is_reported(tmp_path):
    bad = tmp_path / "bad.siq"
    bad.write_bytes(b"not a zip")
    with pytest.raises(UpgradeError):
        PackUpgrader(str(bad), UpgradeSettings(), api=FakeApi()).run()


def test_archive_without_content_xml_is_reported(tmp_path):
    path = tmp_path / "empty.siq"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Audio/a.mp3", b"snd")
    with pytest.raises(UpgradeError):
        PackUpgrader(str(path), UpgradeSettings(), api=FakeApi()).run()


def test_pack_without_questions_is_reported(tmp_path):
    with pytest.raises(UpgradeError):
        _run(tmp_path, _pack(""))


def test_all_functions_off_is_rejected():
    problems = UpgradeSettings(strip_specials=False, add_titles=False,
                               compress_images=False,
                               strip_repeated_text=False,
                               drop_empty_questions=False,
                               compress_audio=False, compress_video=False,
                               merge_text_audio=False,
                               drop_unused=False).validate()
    assert problems and "выключены" in problems[0]


def test_image_limit_above_threshold_is_rejected():
    """Ужимать до 2 МБ картинки, которые берутся от 1 МБ, — это ничего."""
    s = UpgradeSettings(image_min_mb=1.0, image_limit_kb=2048)
    assert any("Сжимать не во что" in p for p in s.validate())


def test_entity_declarations_are_refused(tmp_path):
    """content.xml скачан из интернета: объявленные сущности (XXE / «лавина
    сущностей») разбирать нельзя."""
    evil = ('<?xml version="1.0"?><!DOCTYPE package ['
            '<!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]>'
            '<package name="&xxe;"><rounds/></package>')
    with pytest.raises(UpgradeError):
        parse_content(evil.encode("utf-8"))


def test_stop_writes_nothing(tmp_path):
    content = _pack("".join(_q5(p, qtype="stake") for p in (100, 200, 300)))
    up = PackUpgrader(_siq(tmp_path, content),
                      UpgradeSettings(add_titles=False), api=FakeApi(),
                      should_stop=lambda: True)
    result = up.run()
    assert result.cancelled and not result.path
    assert list(tmp_path.glob("*апгрейд*")) == []


# ── Функция 3: сжатие тяжёлых картинок ───────────────────────────────────────
def _fake_avif(monkeypatch, size: int = 400):
    """Подменяет кодирование: ffmpeg в тестах не зовём, важно поведение вокруг."""
    def fake(self, raw, out, limit_kb=None):
        with open(out, "wb") as f:
            f.write(b"A" * size)
        return True

    monkeypatch.setattr(PackUpgrader, "_to_avif", fake)


def _img_settings(**kw):
    # Порог — самый низкий, какой принимает форма (0,1 МБ); «тяжёлая» картинка
    # в тестах чуть больше него, а кодирование подменено (_fake_avif).
    # drop_unused=False: в этих паках рядом с правленой картинкой нарочно лежат
    # файлы, на которые ссылок нет, — уборка мусора вынесла бы их, а проверяем
    # тут не её (её тесты ниже, свои).
    base = dict(strip_specials=False, add_titles=False, compress_images=True,
                image_min_mb=0.1, image_limit_kb=50, drop_unused=False)
    base.update(kw)
    return UpgradeSettings(**base)


HEAVY = b"J" * 200_000                  # «тяжёлая» картинка для тестов
HEAVY_KB = len(HEAVY)


def _q5_image(price: int, name: str) -> str:
    """Вопрос v5 с картинкой в содержимом."""
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content">'
            f'<item type="image" isRef="True">{name}</item></param>'
            "</params><right><answer>Ответ</answer></right></question>")


def test_heavy_image_becomes_avif_and_ref_follows(tmp_path, monkeypatch):
    _fake_avif(monkeypatch)
    content = _pack(_q5_image(100, "poster.jpg"))
    src = _siq(tmp_path, content, media={"Images/poster.jpg": HEAVY})
    result = PackUpgrader(src, _img_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        assert "Images/poster.avif" in names and "Images/poster.jpg" not in names
        root, ns = parse_content(zf.read("content.xml"))
    item = root.find(f'.//{tag_fn(ns)("item")}')
    assert item.text == "poster.avif"           # ссылка переведена на новый файл
    assert len(result.images) == 1
    assert result.images[0].theme_name == "poster.jpg"
    assert result.saved_bytes == len(HEAVY) - 400


def test_light_images_and_other_media_are_left_alone(tmp_path, monkeypatch):
    _fake_avif(monkeypatch)
    media = {"Images/small.jpg": b"J" * 100, "Audio/a.opus": HEAVY,
             "Images/anim.gif": HEAVY, "Images/done.avif": HEAVY}
    content = _pack(_q5(100))
    src = PackUpgrader(_siq(tmp_path, content, media=media),
                       _img_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(src.path) as zf:
        assert zf.read("Images/small.jpg") == b"J" * 100
        assert zf.read("Audio/a.opus") == HEAVY
        assert zf.read("Images/anim.gif") == HEAVY   # анимация не режется
        assert zf.read("Images/done.avif") == HEAVY   # уже AVIF
    assert src.images == [] and src.heavy_images == 0


def test_image_that_got_heavier_is_kept_as_is(tmp_path, monkeypatch):
    _fake_avif(monkeypatch, size=len(HEAVY) + 1)
    content = _pack(_q5_image(100, "poster.png"))
    src = _siq(tmp_path, content, media={"Images/poster.png": HEAVY})
    result = PackUpgrader(src, _img_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Images/poster.png") == HEAVY
        root, ns = parse_content(zf.read("content.xml"))
    assert result.images == [] and result.heavy_images == 1
    assert root.find(f'.//{tag_fn(ns)("item")}').text == "poster.png"


def test_percent_encoded_v4_reference_is_retargeted(tmp_path, monkeypatch):
    """Имя в архиве бывает percent-кодированным, а у v4 перед ним стоит «@»."""
    _fake_avif(monkeypatch)
    content = _pack('<question price="100">'
                    '<scenario><atom type="image">@%D0%9A%D0%B0%D0%B4%D1%80.jpg'
                    "</atom></scenario>"
                    "<right><answer>Ответ</answer></right></question>")
    src = _siq(tmp_path, content,
               media={"Images/%D0%9A%D0%B0%D0%B4%D1%80.jpg": HEAVY})
    result = PackUpgrader(src, _img_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert "Images/%D0%9A%D0%B0%D0%B4%D1%80.avif" in zf.namelist()
        root, ns = parse_content(zf.read("content.xml"))
    atom = root.find(f'.//{tag_fn(ns)("atom")}')
    assert atom.text == "@%D0%9A%D0%B0%D0%B4%D1%80.avif"


def test_brackets_in_name_survive_reencoding(tmp_path, monkeypatch):
    """Скобки, запятые и «!» в имени записи трогать НЕЛЬЗЯ.

    Игра ищет медиа по имени из content.xml, прогоняя его через
    Uri.EscapeUriString (SIDocument.TryGetMedia): пробел там становится %20, а
    скобки остаются собой. Пока имя новой записи кодировали quote(safe=""),
    «Kiss of Death (Darling).opus» превращался в …%28Darling%29.opus, и вопрос
    падал с «File … was not found in the game package!» — при том что без
    апгрейда тот же пак играл нормально."""
    _fake_avif(monkeypatch)
    raw = "Kiss%20of%20Death%20(Darling)!,%20[TV].jpg"
    decoded = "Kiss of Death (Darling)!, [TV].jpg"
    content = _pack(_q5_image(100, decoded))
    src = _siq(tmp_path, content, media={f"Images/{raw}": HEAVY})
    result = PackUpgrader(src, _img_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        root, ns = parse_content(zf.read("content.xml"))
    assert "Images/Kiss%20of%20Death%20(Darling)!,%20[TV].avif" in names
    ref = root.find(f'.//{tag_fn(ns)("item")}').text
    assert ref == "Kiss of Death (Darling)!, [TV].avif"
    # То же самое, но глазами игры: как она имя закодирует, так и должна найти.
    assert f"Images/{escape_uri_string(ref)}" in names


def test_brackets_survive_even_when_the_name_is_taken(tmp_path, monkeypatch):
    """Занятое имя разводится суффиксом « (2)» — и оно тоже кодируется
    по-игровому (пробел в %20, скобки как есть)."""
    _fake_avif(monkeypatch)
    content = _pack(_q5_image(100, "кадр (1).webp"))
    src = _siq(tmp_path, content,
               media={"Images/%D0%BA%D0%B0%D0%B4%D1%80%20(1).webp": HEAVY,
                      "Images/%D0%BA%D0%B0%D0%B4%D1%80%20(1).avif": b"OLD"})
    result = PackUpgrader(src, _img_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        root, ns = parse_content(zf.read("content.xml"))
    ref = root.find(f'.//{tag_fn(ns)("item")}').text
    assert ref == "кадр (1) (2).avif"
    assert f"Images/{escape_uri_string(ref)}" in names


def test_escape_uri_string_matches_dotnet():
    """Набор символов взят у .NET Uri.EscapeUriString (его зовёт SIGame):
    незаписанные -._~ плюс зарезервированные ;/?:@&=+$,#[]!'()* остаются как
    есть, всё прочее — в %XX по UTF-8."""
    assert escape_uri_string("a b") == "a%20b"
    assert escape_uri_string("!#$&'()*+,/:;=?@[]-._~") == "!#$&'()*+,/:;=?@[]-._~"
    assert escape_uri_string("«Vital» — jin • ok") == (
        "%C2%ABVital%C2%BB%20%E2%80%94%20jin%20%E2%80%A2%20ok")
    assert escape_uri_string("Наруто.mp3") == (
        "%D0%9D%D0%B0%D1%80%D1%83%D1%82%D0%BE.mp3")


def test_taken_avif_name_does_not_clobber_the_neighbour(tmp_path, monkeypatch):
    """Рядом с «кадр.webp» в паках лежит «кадр.avif» (вопрос и ответ одного
    тайтла): подменять его нельзя — берётся соседнее свободное имя."""
    _fake_avif(monkeypatch)
    content = _pack(_q5_image(100, "кадр.webp"))
    src = _siq(tmp_path, content, media={"Images/кадр.webp": HEAVY,
                                         "Images/кадр.avif": b"OLD"})
    result = PackUpgrader(src, _img_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Images/кадр.avif") == b"OLD"   # чужой файл цел
        assert "Images/кадр (2).avif" in zf.namelist()
        root, ns = parse_content(zf.read("content.xml"))
    assert root.find(f'.//{tag_fn(ns)("item")}').text == "кадр (2).avif"


def test_retarget_refs_touches_only_media_elements():
    root = ET.fromstring(
        '<package><item type="image" isRef="True">a.jpg</item>'
        "<atom>@a.jpg</atom><answer>a.jpg</answer></package>")
    assert retarget_refs(root, {"a.jpg": "a.avif"}) == 2
    assert [el.text for el in root] == ["a.avif", "@a.avif", "a.jpg"]


def test_images_untouched_when_function_is_off(tmp_path, monkeypatch):
    _fake_avif(monkeypatch)
    content = _pack(_q5_image(100, "poster.jpg"))
    src = _siq(tmp_path, content, media={"Images/poster.jpg": HEAVY})
    result = PackUpgrader(src, UpgradeSettings(add_titles=False,
                                               compress_images=False),
                          api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Images/poster.jpg") == HEAVY
    assert result.images == [] and result.heavy_images == 0


def test_source_pack_survives_image_compression(tmp_path, monkeypatch):
    _fake_avif(monkeypatch)
    content = _pack(_q5_image(100, "poster.jpg"))
    src = _siq(tmp_path, content, media={"Images/poster.jpg": HEAVY})
    before = open(src, "rb").read()
    PackUpgrader(src, _img_settings(), api=FakeApi()).run()
    assert open(src, "rb").read() == before


# ── Отчёт «три примера с каждой функции» ─────────────────────────────────────
def test_examples_show_three_of_each(tmp_path):
    content = _pack("".join(
        _q5(100 * i, answer=a, qtype="secret")
        for i, a in enumerate(["Наруто", "Блич", "Наруто (2002)", "Блич!"], 1)))
    result = _run(tmp_path, content)
    lines = example_lines(result, limit=3)
    assert lines[0] == "Спецвопросов расколдовано: 4."
    assert sum(1 for l in lines if l.startswith("  • «Раунд 1»")) == 6  # 3 + 3
    assert any(l.startswith("Ответов дополнено названиями: 4.") for l in lines)


def test_examples_say_so_when_nothing_changed(tmp_path):
    content = _pack(_q5(100, answer="Столица Франции"))
    result = _run(tmp_path, content)
    lines = example_lines(result)
    assert any("спецвопросов в паке не нашлось" in l for l in lines)
    assert any("названий аниме в ответах не опознано" in l for l in lines)
    assert any("картинок тяжелее порога в паке нет" in l for l in lines)


def test_examples_show_compressed_images(tmp_path, monkeypatch):
    _fake_avif(monkeypatch)
    content = _pack("".join(_q5_image(100 * i, f"p{i}.jpg")
                            for i in range(1, 5)))
    media = {f"Images/p{i}.jpg": HEAVY for i in range(1, 5)}
    src = _siq(tmp_path, content, media=media)
    result = PackUpgrader(src, _img_settings(), api=FakeApi()).run()
    lines = example_lines(result, limit=3)
    head = next(l for l in lines if l.startswith("Картинок сжато:"))
    assert head.startswith("Картинок сжато: 4 (пак легче на ")
    assert sum(1 for l in lines if l.startswith("  • p")) == 3


def test_changes_are_reported_in_pack_order(tmp_path):
    content = _pack(_q5(100, answer="Наруто") + _q5(200, qtype="stake"))
    result = _run(tmp_path, content)
    assert [c.kind for c in result.changes] == ["title", "special"]
    assert [c.price for c in result.changes] == [100, 200]


# ── Написание названия как на Shikimori ──────────────────────────────────────
def _answers(result):
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    return [a.text for a in root.findall(f'.//{tag("right")}/{tag("answer")}')]


def test_case_is_fixed_to_shikimori_spelling(tmp_path):
    """«наруто» в паке — «Наруто» на Shikimori (просьба пользователя)."""
    content = _pack(_q5(100, answer="наруто"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False))
    assert _answers(result)[0] == "Наруто"
    assert [(c.before, c.after) for c in result.recased] == [("наруто", "Наруто")]


def test_case_fix_handles_shouting_and_keeps_song_after_dash(tmp_path):
    content = _pack(_q5(100, answer="НАРУТО - Nee"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False))
    assert _answers(result)[0] == "Наруто - Nee"


def test_case_fix_changes_only_letters_case(tmp_path):
    """Написание — это регистр. Превращать «Наруто» в «Наруто. Книга первая»
    нельзя: это уже другой ответ."""
    content = _pack(_q5(100, answer="Наруто"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False))
    assert result.recased == [] and _answers(result)[0] == "Наруто"


def test_case_fix_can_be_switched_off(tmp_path):
    content = _pack(_q5(100, answer="наруто"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, fix_case=False))
    assert result.recased == [] and _answers(result)[0] == "наруто"


def test_case_fix_needs_exact_match(tmp_path):
    """Нестрогое совпадение карточку находит, но переписывать по ней ответ
    нельзя: это может быть вообще другой тайтл."""
    content = _pack(_q5(100, answer="bleachh"))
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, strict_match=False))
    assert result.titles and result.recased == [] and result.exact_titles == 0


# ── Постер тайтла в ответе ───────────────────────────────────────────────────
POSTERED = dict(BLEACH, poster={"originalUrl": "https://shikimori/x.jpg"})


def _fake_poster(monkeypatch, size: int = 1234):
    """Постер без сети и без ffmpeg: скачивание и кодирование подменены."""
    monkeypatch.setattr(PackUpgrader, "_fetch", lambda self, url: b"raw-bytes")

    def fake(self, raw, out, limit_kb=None):
        with open(out, "wb") as f:
            f.write(b"P" * size)
        return True

    monkeypatch.setattr(PackUpgrader, "_to_avif", fake)


def _poster_settings(**kw):
    base = dict(strip_specials=False, compress_images=False)
    base.update(kw)
    return UpgradeSettings(**base)


def test_poster_goes_into_the_answer(tmp_path, monkeypatch):
    _fake_poster(monkeypatch)
    content = _pack(_q5(100, answer="Блич"))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    with zipfile.ZipFile(result.path) as zf:
        made = [n for n in zf.namelist() if n.endswith(".avif")]
        assert made == ["Images/shiki_269_poster.avif"]
        assert len(zf.read(made[0])) == 1234
        root, ns = parse_content(zf.read("content.xml"))
    tag = tag_fn(ns)
    answer = [p for p in root.iter(tag("param")) if p.get("name") == "answer"][0]
    item = answer.find(tag("item"))
    assert item.get("type") == "image" and item.get("isRef") == "True"
    assert item.text == "shiki_269_poster.avif"
    assert item.get("duration") is None       # без таймера: висит до ведущего
    assert len(result.posters) == 1 and result.added_bytes == 1234


def test_one_poster_file_per_title(tmp_path, monkeypatch):
    """Тайтл в паке встречается по нескольку раз — файл на него один."""
    _fake_poster(monkeypatch)
    content = _pack(_q5(100, answer="Блич") + _q5(200, answer="Bleach"))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    with zipfile.ZipFile(result.path) as zf:
        assert len([n for n in zf.namelist() if n.endswith(".avif")]) == 1
    assert len(result.posters) == 2 and result.added_bytes == 1234


def test_poster_is_not_added_over_existing_picture(tmp_path, monkeypatch):
    """Своя картинка в ответе уже есть — вторая рядом это слайд-шоу."""
    _fake_poster(monkeypatch)
    right = "<right><answer>Блич</answer></right>"
    params = ('<param name="answer" type="content">'
              '<item type="image" isRef="True">своя.jpg</item></param>')
    content = _pack(_q5(100, params=params, right=right))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    assert result.posters == []
    with zipfile.ZipFile(result.path) as zf:
        assert not [n for n in zf.namelist() if n.endswith(".avif")]


@pytest.mark.parametrize("item", [
    '<item type="video" isRef="True">свой.mp4</item>',
    '<item type="audio" isRef="True" placement="background">свой.mp3</item>',
])
def test_poster_is_not_added_over_existing_media(tmp_path, monkeypatch, item):
    """Ролик или дорожка в ответе — тоже готовое зрелище, постер его перебьёт."""
    _fake_poster(monkeypatch)
    right = "<right><answer>Блич</answer></right>"
    params = f'<param name="answer" type="content">{item}</param>'
    content = _pack(_q5(100, params=params, right=right))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    assert result.posters == []
    with zipfile.ZipFile(result.path) as zf:
        assert not [n for n in zf.namelist() if n.endswith(".avif")]


def test_poster_still_goes_next_to_answer_text(tmp_path, monkeypatch):
    """Текст в ответе (реплика ведущего) медиа не считается — постер ставим."""
    _fake_poster(monkeypatch)
    right = "<right><answer>Блич</answer></right>"
    params = ('<param name="answer" type="content">'
              '<item placement="replic">Отличная вещь</item></param>')
    content = _pack(_q5(100, params=params, right=right))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    assert len(result.posters) == 1


def test_poster_is_not_added_over_v4_media_after_marker(tmp_path, monkeypatch):
    """В v4 ответ — хвост сценария за маркером; ролик там значит то же самое."""
    _fake_poster(monkeypatch)
    content = _pack('<question price="100"><scenario><atom>Текст</atom>'
                    '<atom type="marker"/><atom type="video">@свой.mp4</atom>'
                    "</scenario><right><answer>Блич</answer></right></question>")
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    assert result.posters == []


def test_poster_can_be_switched_off(tmp_path, monkeypatch):
    _fake_poster(monkeypatch)
    content = _pack(_q5(100, answer="Блич"))
    result = _run(tmp_path, content, _poster_settings(add_poster=False),
                  api=FakeApi([POSTERED]))
    assert result.posters == [] and result.added_bytes == 0


def test_poster_needs_exact_match(tmp_path, monkeypatch):
    _fake_poster(monkeypatch)
    content = _pack(_q5(100, answer="bleachh"))
    result = _run(tmp_path, content, _poster_settings(strict_match=False),
                  api=FakeApi([POSTERED]))
    assert result.posters == []


def test_title_without_poster_is_skipped(tmp_path, monkeypatch):
    _fake_poster(monkeypatch)
    content = _pack(_q5(100, answer="Блич"))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([BLEACH]))
    assert result.posters == [] and result.exact_titles == 1


def test_poster_in_v4_goes_after_the_marker(tmp_path, monkeypatch):
    """В v4 ответ живёт в сценарии за <atom type="marker"/>."""
    _fake_poster(monkeypatch)
    content = _pack(_q4(100, answer="Блич"))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    root, ns = _out_root(result)
    tag = tag_fn(ns)
    atoms = root.find(f'.//{tag("scenario")}').findall(tag("atom"))
    assert [a.get("type") for a in atoms] == [None, "marker", "image"]
    assert atoms[-1].text == "@shiki_269_poster.avif"


def test_poster_name_does_not_overwrite_existing_file(tmp_path, monkeypatch):
    _fake_poster(monkeypatch)
    content = _pack(_q5(100, answer="Блич"))
    src = _siq(tmp_path, content,
               media={"Images/shiki_269_poster.avif": "чужой файл".encode()})
    result = PackUpgrader(src, _poster_settings(), api=FakeApi([POSTERED])).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Images/shiki_269_poster.avif") == "чужой файл".encode()
        assert "Images/shiki_269_poster (2).avif" in zf.namelist()


def test_poster_temp_files_are_cleaned_up(tmp_path, monkeypatch):
    _fake_poster(monkeypatch)
    content = _pack(_q5(100, answer="Блич"))
    up = PackUpgrader(_siq(tmp_path, content), _poster_settings(),
                      api=FakeApi([POSTERED]))
    up.run()
    assert not any(os.path.exists(p) for p in up._extra.values())


# ── Карточка выбранного пака ─────────────────────────────────────────────────
def test_read_pack_info_returns_name_author_and_themes(tmp_path):
    content = ('<?xml version="1.0" encoding="utf-8"?>'
               '<package name="Солянка № 2" version="5" date="17.07.2025">'
               "<info><authors><author>GoldensFire</author></authors></info>"
               '<rounds><round name="Раунд 1"><themes>'
               '<theme name="Опенинги"><questions>'
               + _q5(100) + _q5(200, qtype="secret") +
               "</questions></theme>"
               '<theme name="Эндинги"><questions>' + _q5(300) +
               "</questions></theme></themes></round>"
               '<round name="Финал"><themes><theme name="Аниме"><questions>'
               + _q5(0) + "</questions></theme></themes></round>"
               "</rounds></package>")
    info = read_pack_info(_siq(tmp_path, content))
    assert info.name == "Солянка № 2" and info.author == "GoldensFire"
    assert info.date == "17.07.2025" and info.version == "5"
    assert info.questions == 4 and info.specials == 1
    assert info.themes == ["Опенинги", "Эндинги", "Аниме"]
    assert [r for r, _t in info.rounds] == ["Раунд 1", "Финал"]


def test_read_pack_info_survives_a_pack_without_info(tmp_path):
    info = read_pack_info(_siq(tmp_path, _pack(_q5(100))))
    assert info.name == "Пак" and info.authors == [] and info.author == ""
    assert info.themes == ["Тема А"]


# ── Названия типов вопросов — как в самой игре ───────────────────────────────
def test_special_labels_match_siquester_wording():
    """Подписи взяты у SIQuester (QuestionTypesNamesNew + Resources.ru-RU),
    а не выдуманы: «кот в мешке» — прозвище, в игре тип зовётся иначе."""
    assert SPECIAL_LABELS["secret"] == "с секретом"
    assert SPECIAL_LABELS["secretnoquestion"] == "с секретом без вопроса"
    assert SPECIAL_LABELS["norisk"] == "для себя"
    assert SPECIAL_LABELS["stakeall"] == "для всех со ставкой"


# ── Отчёт про новые функции ──────────────────────────────────────────────────
def test_examples_show_recased_and_posters(tmp_path, monkeypatch):
    _fake_poster(monkeypatch)
    content = _pack(_q5(100, answer="блич") + _q5(200, answer="наруто"))
    result = _run(tmp_path, content, _poster_settings(),
                  api=FakeApi([POSTERED, NARUTO]))
    lines = example_lines(result, limit=3)
    head = next(l for l in lines if l.startswith("Названий переписано"))
    assert head == "Названий переписано как на Shikimori: 2."
    head = next(l for l in lines if l.startswith("Постеров поставлено"))
    assert head.startswith("Постеров поставлено в ответ: 1 (пак тяжелее на ")


# ── Клипы и промо — не тайтлы ────────────────────────────────────────────────
# Живой случай: ответ «Mumei» (имя героя) находил вокалоид-клип «Mumei», а
# «Teto Kasane» — клип «Yababaina», у которого это лежит в синонимах.
CLIP_MUMEI = {"id": 56886, "malId": 56886, "name": "Mumei", "russian": "Мумэй",
              "english": None, "japanese": "mumei", "licenseNameRu": None,
              "synonyms": [], "kind": "music",
              "poster": {"originalUrl": "https://shikimori/m.jpg"}}
CLIP_YABA = {"id": 58640, "malId": 58640, "name": "Yababaina", "russian": None,
             "english": None, "licenseNameRu": None, "kind": "music",
             "synonyms": ["YABABAINA - Satapan P feat.Miku Hatsune",
                          "Teto Kasane", "Zundamon"]}


def test_music_and_promo_are_not_titles(tmp_path):
    content = _pack(_q5(100, answer="Mumei"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False),
                  api=FakeApi([CLIP_MUMEI]))
    assert result.titles == [] and result.posters == []
    assert result.recased == [] and result.not_found == 1
    assert _answers(result) == ["Mumei"]      # ответ не тронут вовсе


@pytest.mark.parametrize("kind", ["music", "pv", "cm", "MUSIC"])
def test_every_clip_kind_is_refused(kind):
    assert pick_card("Блич", [dict(BLEACH, kind=kind)]) is None


@pytest.mark.parametrize("kind", ["tv", "movie", "ova", "ona", "special", "",
                                  None])
def test_real_kinds_and_unknown_ones_pass(kind):
    """Незнакомый тип считаем настоящим: список типов Shikimori пополняет."""
    assert pick_card("Блич", [dict(BLEACH, kind=kind)]) is BLEACH or True
    assert pick_card("Блич", [dict(BLEACH, kind=kind)]) is not None


def test_synonym_only_match_is_refused(tmp_path):
    """«Teto Kasane» — синоним клипа «Yababaina»: собственные названия записи к
    ответу отношения не имеют, такое совпадение не значит ничего."""
    assert synonym_only("Teto Kasane", CLIP_YABA) is True
    content = _pack(_q5(100, answer="Teto Kasane"))
    result = _run(tmp_path, content, UpgradeSettings(strip_specials=False),
                  api=FakeApi([dict(CLIP_YABA, kind="tv")]))
    assert result.titles == [] and _answers(result) == ["Teto Kasane"]


def test_synonym_match_counts_when_the_title_is_in_the_answer():
    """А вот «Наруто ТВ-1» (тоже синоним) засчитывается: собственное название
    тайтла в ответе есть."""
    assert synonym_only("Наруто ТВ-1", NARUTO) is False
    assert pick_card("Наруто ТВ-1", [NARUTO]) is NARUTO


# ── Регистр: не по японскому полю и не в худшую сторону ──────────────────────
def test_case_is_not_taken_from_the_japanese_field(tmp_path):
    """У записи Shikimori японское название бывает записано латиницей строчными
    («mumei») — по нему регистр правился в худшую сторону."""
    card = dict(CLIP_MUMEI, kind="tv")
    assert "mumei" in card_names(card)          # для опознания оно годится
    assert "mumei" not in spelling_names(card)  # для написания — нет
    content = _pack(_q5(100, answer="Mumei"))
    # add_poster=False: тайтл здесь опознаётся, и с постером по умолчанию тест
    # уходил качать https://shikimori/m.jpg по-настоящему. Речь про регистр.
    result = _run(tmp_path, content,
                  UpgradeSettings(strip_specials=False, add_poster=False),
                  api=FakeApi([card]))
    assert result.recased == [] and _answers(result)[0] == "Mumei"


def test_leading_capital_is_never_lowered():
    assert recased("Mumei", ["mumei"]) is None
    assert recased("mumei", ["Mumei"]) == "Mumei"


# ── Ответ — имя персонажа, а не тайтл ────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("Mumei", True), ("Teto Kasane", True), ("Mio Akiyama", True),
    ("Наруто", False),                    # кириллицу не проверяем — см. ниже
    ("Стрелок с чёрной скалы", False),
    ("Boku no Kanojo ga Majimesugiru Sho-bitch na Ken", False),  # длинновато
    ("ナルト", False), ("", False),
])
def test_which_answers_are_worth_a_character_query(text, expected):
    assert looks_like_character_name(text) is expected


def test_character_hit_compares_latin_names_only():
    """У персонажа «Naruto-kun» русское имя — «Наруто»: сравнивай мы русские,
    проверка съела бы настоящий тайтл «Наруто»."""
    chars = [{"name": "Naruto-kun", "russian": "Наруто"},
             {"name": "Naruto Uzumaki", "russian": "Наруто Узумаки"}]
    assert character_hit("Naruto", chars) is None
    assert character_hit("Наруто", chars) is None
    assert character_hit("Naruto-kun", chars) == "Naruto-kun"


class CharApi(FakeApi):
    """FakeApi, который ещё и «знает» персонажей."""

    def __init__(self, cards=None, chars=None):
        super().__init__(cards)
        self.chars = list(chars or [])
        self.char_calls = []

    def search_characters_by_name(self, name):
        self.char_calls.append(name)
        return list(self.chars)


# Тайтл, который сам по себе на ответ не похож: совпадение приходит близостью
# строк, и вот тут мнение базы персонажей уже что-то значит.
LOOSE_CARD = {"id": 7, "malId": 7, "russian": None, "name": "Teto Kasanee",
              "english": None, "licenseNameRu": "", "synonyms": [], "kind": "tv"}


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


# ── Функция 5: повторяющийся текст темы ──────────────────────────────────────
def _q5_items(price: int, items: str, answer: str = "Ответ") -> str:
    """Вопрос v5 с произвольным содержимым (несколько <item> подряд)."""
    return (f'<question price="{price}"><params>'
            f'<param name="question" type="content">{items}</param></params>'
            f"<right><answer>{answer}</answer></right></question>")


def _shot(name: str = "кадр.jpg") -> str:
    return f'<item type="image" isRef="True">{name}</item>'


# Известные подписи тут выключены нарочно: ниже проверяется ОБЩЕЕ правило
# («текст стоит в каждом вопросе темы»), и «Назвать аниме» взято как обычный
# короткий текст. Списочные подписи проверяются отдельно, см. KNOWN_REPEATS.
ONLY_REPEATS = UpgradeSettings(strip_specials=False, add_titles=False,
                               compress_images=False,
                               strip_known_labels=False)
KNOWN_REPEATS = UpgradeSettings(strip_specials=False, add_titles=False,
                                compress_images=False)


def _themes(*themes: str, round_name: str = "Раунд 1") -> str:
    """Пак из нескольких тем: [(имя темы, вопросы)] строками."""
    body = "".join(f'<theme name="{name}"><questions>{qs}</questions></theme>'
                   for name, qs in (t.split("|", 1) for t in themes))
    return ('<?xml version="1.0" encoding="utf-8"?>\n<package name="Пак">'
            f'<rounds><round name="{round_name}"><themes>{body}'
            "</themes></round></rounds></package>")


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


# ── Ответ, записанный двумя названиями через косую черту ─────────────────────
UENO = {"id": 37920, "malId": 37920, "russian": "Неуклюжая Уэно",
        "name": "Ueno-san wa Bukiyou", "english": "How Clumsy you are, Miss Ueno",
        "synonyms": ["Уэно-сан, какая же Вы неуклюжая"], "licenseNameRu": ""}


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


# ── Несколько точных совпадений: побеждает известность ───────────────────────
def _stats(watchers: int) -> list:
    return [{"status": "completed", "count": watchers}]


KYOUKAI = {"id": 18153, "malId": 18153, "russian": "По ту сторону границы",
           "name": "Kyoukai no Kanata", "english": "Beyond the Boundary",
           "synonyms": ["За гранью", "Beyond the Horizon"], "licenseNameRu": "",
           "kind": "tv", "statusesStats": _stats(1264006)}
SWEAT = {"id": 1072, "malId": 1072, "russian": "За гранью", "name": "Sweat Punch",
         "english": "Sweat Punch", "synonyms": ["Комедия", "Kigeki"],
         "licenseNameRu": "", "kind": "ova", "statusesStats": _stats(52878)}


def test_popular_synonym_beats_an_obscure_own_name():
    """«За гранью» — это «Kyoukai no Kanata» (синонимом, миллион в списках), а
    не одноимённая OVA «Sweat Punch», про которую не слышал никто."""
    assert synonym_only("За гранью", KYOUKAI) is True
    assert synonym_only("За гранью", SWEAT) is False
    assert pick_card("За гранью", [KYOUKAI, SWEAT]) is KYOUKAI
    # Порядок выдачи ничего не меняет: решает известность, а не место в списке.
    assert pick_card("За гранью", [SWEAT, KYOUKAI]) is KYOUKAI


def test_close_popularity_still_prefers_the_own_name():
    """Синонимам верим только при разнице в разы: их правит кто угодно."""
    near = dict(KYOUKAI, statusesStats=_stats(60000))
    assert pick_card("За гранью", [near, SWEAT]) is SWEAT


def test_synonym_only_match_without_popularity_is_still_refused():
    """Без статистики (её может не быть у старой карточки) правило прежнее."""
    bare = dict(KYOUKAI)
    bare.pop("statusesStats")
    assert pick_card("За гранью", [bare]) is None


def test_the_more_popular_of_two_own_names_wins():
    """Совпали собственными названиями оба — берём тот, что известнее."""
    small = dict(BLEACH, statusesStats=_stats(1000))
    big = dict(BLEACH, id=999, malId=999, statusesStats=_stats(900000))
    assert pick_card("Блич", [small, big]) is big


class RawApi(FakeApi):
    """Выдача Shikimori как есть: поиск там ищет и по синонимам тоже, а
    самодельная фильтрация FakeApi про них не знает."""

    def search_animes_by_name(self, name, limit=0):
        self.calls.append(name)
        return list(self.cards)


def test_kyoukai_no_kanata_is_found_in_a_pack(tmp_path):
    """Живой случай из пака пользователя: ответ «За Гранью» доставал OVA «Sweat
    Punch» со своими синонимами вместо настоящего тайтла."""
    result = _run(tmp_path, _pack(_q5(100, answer="За Гранью")),
                  UpgradeSettings(strip_specials=False, add_poster=False),
                  api=RawApi([KYOUKAI, SWEAT]))
    answers = _answers(result)
    assert "Kyoukai no Kanata" in answers
    assert "Sweat Punch" not in answers and "Kigeki" not in answers


# ── Темы про мангу, манхву и ранобэ ──────────────────────────────────────────
@pytest.mark.parametrize("name", [
    "Manga(для читающих)", "Манга", "манги побольше", "Манхва",
    "Ранобэ и новеллы", "Light Novel", "МАНХУА"])
def test_book_themes_are_recognised(name):
    assert is_book_theme(name) is True


@pytest.mark.parametrize("name", ["Аниме-опенинги", "Мангал", "Романтика",
                                  "Студии", ""])
def test_other_themes_are_not_book_themes(name):
    assert is_book_theme(name) is False


AKAME_MANGA = {"id": 25132, "malId": 25132, "russian": "Убийца Акамэ!",
               "name": "Akame ga Kill!", "english": "Akame ga Kill!",
               "synonyms": ["Akame ga Kiru!"], "licenseNameRu": "",
               "kind": "manga", "poster": {"originalUrl": "http://x/m.jpg"}}
AKAME_ANIME = {"id": 22199, "malId": 22199, "russian": "Убийца Акамэ!",
               "name": "Akame ga Kill!", "english": "Akame ga Kill!",
               "synonyms": ["Красноглазый убийца"], "licenseNameRu": "",
               "kind": "tv", "poster": {"originalUrl": "http://x/a.jpg"}}


class BookApi(FakeApi):
    """Shikimori с двумя базами: аниме и книги (поиск по ним раздельный)."""

    def __init__(self, animes=None, mangas=None):
        super().__init__(animes if animes is not None else [])
        self.books = list(mangas or [])
        self.manga_calls = []

    def search_mangas_by_name(self, name, limit=0):
        self.manga_calls.append(name)
        needle = norm_title(name)
        return [c for c in self.books
                if any(needle in norm_title(n) or norm_title(n) in needle
                       for n in [c.get("russian"), c.get("name"),
                                 c.get("english")] if n)]


def _book_pack(theme: str, answer: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<package name="Пак">'
            f'<rounds><round name="Раунд 1"><themes><theme name="{theme}">'
            f"<questions>{_q5(100, answer=answer)}</questions>"
            "</theme></themes></round></rounds></package>")


def test_book_theme_asks_shikimori_for_the_manga(tmp_path):
    api = BookApi([AKAME_ANIME], [AKAME_MANGA])
    result = _run(tmp_path, _book_pack("Manga(для читающих)", "Убийца Акамэ!"),
                  UpgradeSettings(strip_specials=False, add_poster=False),
                  api=api)
    assert api.manga_calls == ["Убийца Акамэ!"] and api.calls == []
    assert "Akame ga Kiru!" in _answers(result)            # синоним манги
    assert "Красноглазый убийца" not in _answers(result)   # это уже аниме


def test_ordinary_theme_still_asks_for_the_anime(tmp_path):
    api = BookApi([AKAME_ANIME], [AKAME_MANGA])
    result = _run(tmp_path, _book_pack("Аниме-опенинги", "Убийца Акамэ!"),
                  UpgradeSettings(strip_specials=False, add_poster=False),
                  api=api)
    assert api.manga_calls == [] and api.calls == ["Убийца Акамэ!"]
    assert "Красноглазый убийца" in _answers(result)


def test_book_theme_falls_back_to_the_anime_for_names(tmp_path):
    """Книги нет — названия всё равно доищем, это лучше, чем ничего."""
    api = BookApi([AKAME_ANIME], [])
    result = _run(tmp_path, _book_pack("Манга", "Убийца Акамэ!"),
                  UpgradeSettings(strip_specials=False, add_poster=False),
                  api=api)
    assert api.manga_calls and api.calls
    assert "Красноглазый убийца" in _answers(result)


def test_book_theme_takes_no_poster_from_the_anime(tmp_path, monkeypatch):
    """Главное про книжные темы: обложку из аниме не тянем вовсе."""
    api = BookApi([AKAME_ANIME], [])
    result = _run(tmp_path, _book_pack("Манга", "Убийца Акамэ!"),
                  UpgradeSettings(strip_specials=False), api=api)
    assert result.posters == []


def test_book_theme_can_be_switched_off(tmp_path):
    api = BookApi([AKAME_ANIME], [AKAME_MANGA])
    _run(tmp_path, _book_pack("Манга", "Убийца Акамэ!"),
         UpgradeSettings(strip_specials=False, add_poster=False,
                         book_themes=False), api=api)
    assert api.manga_calls == [] and api.calls == ["Убийца Акамэ!"]


# ── Функция «Текст под звук» ─────────────────────────────────────────────────
ONLY_MERGE = UpgradeSettings(strip_specials=False, add_titles=False,
                             compress_images=False, strip_repeated_text=False,
                             drop_empty_questions=False, compress_audio=False,
                             drop_unused=False)


def _sound(name: str = "опенинг.mp3") -> str:
    return f'<item type="audio" isRef="True">{name}</item>'


def _items_of(q, ns):
    tag = tag_fn(ns)
    return q.find(f'{tag("params")}/{tag("param")}').findall(tag("item"))


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


# ── Функция «Удалить пустые вопросы» ─────────────────────────────────────────
ONLY_EMPTY = UpgradeSettings(strip_specials=False, add_titles=False,
                             compress_images=False, strip_repeated_text=False,
                             compress_audio=False)


def _q5_empty(price: int, answer: str = "Ответ") -> str:
    """Вопрос v5, в котором нет ничего, кроме ответа."""
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content"/></params>'
            f"<right><answer>{answer}</answer></right></question>")


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


# ── Функция «Сжать тяжёлое аудио» ────────────────────────────────────────────
BIG_AUDIO = b"S" * 300_000              # «тяжёлая» дорожка для тестов


def _aud_settings(**kw):
    base = dict(strip_specials=False, add_titles=False, compress_images=False,
                strip_repeated_text=False, drop_empty_questions=False,
                compress_audio=True, audio_min_mb=0.1, audio_kbps=192,
                drop_unused=False)
    base.update(kw)
    return UpgradeSettings(**base)


def _fake_opus(monkeypatch, size: int = 5000, kbps: int = 320):
    """ffmpeg и ffprobe в тестах не зовём: важно поведение вокруг них."""
    def fake_encode(self, raw, out):
        with open(out, "wb") as f:
            f.write(b"O" * size)
        return True

    monkeypatch.setattr(PackUpgrader, "_to_opus", fake_encode)
    monkeypatch.setattr(PackUpgrader, "_audio_kbps",
                        lambda self, raw, size=0: kbps)


def _q5_audio(price: int, name: str) -> str:
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content">'
            f'<item type="audio" isRef="True">{name}</item></param>'
            "</params><right><answer>Ответ</answer></right></question>")


def test_heavy_audio_becomes_opus_and_ref_follows(tmp_path, monkeypatch):
    _fake_opus(monkeypatch)
    content = _pack(_q5_audio(100, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Audio/песня.mp3": BIG_AUDIO})
    result = PackUpgrader(src, _aud_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        assert "Audio/песня.opus" in names and "Audio/песня.mp3" not in names
        root, ns = parse_content(zf.read("content.xml"))
    assert root.find(f'.//{tag_fn(ns)("item")}').text == "песня.opus"
    assert len(result.audios) == 1 and result.heavy_audio == 1
    assert result.saved_audio_bytes == len(BIG_AUDIO) - 5000
    assert "320 кбит" in result.audios[0].before
    assert "opus 192 кбит" in result.audios[0].after


def test_audio_that_is_already_quiet_enough_is_left_alone(tmp_path, monkeypatch):
    """Битрейт исходника не выше целевого — перекод только испортил бы звук."""
    _fake_opus(monkeypatch, kbps=128)
    content = _pack(_q5_audio(100, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Audio/песня.mp3": BIG_AUDIO})
    result = PackUpgrader(src, _aud_settings(audio_kbps=192),
                          api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/песня.mp3") == BIG_AUDIO
    assert result.audios == [] and result.heavy_audio == 1


def test_unknown_bitrate_is_recoded_anyway(tmp_path, monkeypatch):
    _fake_opus(monkeypatch, kbps=0)
    content = _pack(_q5_audio(100, "песня.wav"))
    src = _siq(tmp_path, content, media={"Audio/песня.wav": BIG_AUDIO})
    result = PackUpgrader(src, _aud_settings(), api=FakeApi()).run()
    assert len(result.audios) == 1
    assert "кбит," not in result.audios[0].before      # неизвестного не пишем


def test_light_audio_and_video_are_left_alone(tmp_path, monkeypatch):
    _fake_opus(monkeypatch)
    media = {"Audio/тихая.mp3": b"S" * 100, "Video/ролик.mp4": BIG_AUDIO}
    src = _siq(tmp_path, _pack(_q5(100)), media=media)
    result = PackUpgrader(src, _aud_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/тихая.mp3") == b"S" * 100
        assert zf.read("Video/ролик.mp4") == BIG_AUDIO   # ролик не трогаем
    assert result.audios == [] and result.heavy_audio == 0


def test_audio_that_got_heavier_is_kept_as_is(tmp_path, monkeypatch):
    _fake_opus(monkeypatch, size=len(BIG_AUDIO) + 1)
    content = _pack(_q5_audio(100, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Audio/песня.mp3": BIG_AUDIO})
    result = PackUpgrader(src, _aud_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/песня.mp3") == BIG_AUDIO
    assert result.audios == [] and result.heavy_audio == 1


def test_taken_opus_name_does_not_clobber_the_neighbour(tmp_path, monkeypatch):
    _fake_opus(monkeypatch)
    content = _pack(_q5_audio(100, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Audio/песня.mp3": BIG_AUDIO,
                                         "Audio/песня.opus": b"OLD"})
    result = PackUpgrader(src, _aud_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/песня.opus") == b"OLD"
        assert "Audio/песня (2).opus" in zf.namelist()
        root, ns = parse_content(zf.read("content.xml"))
    assert root.find(f'.//{tag_fn(ns)("item")}').text == "песня (2).opus"


def test_audio_untouched_when_function_is_off(tmp_path, monkeypatch):
    _fake_opus(monkeypatch)
    content = _pack(_q5_audio(100, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Audio/песня.mp3": BIG_AUDIO})
    result = PackUpgrader(src, _aud_settings(compress_audio=False,
                                             strip_specials=True),
                          api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/песня.mp3") == BIG_AUDIO
    assert result.audios == [] and result.heavy_audio == 0


def test_audio_and_images_do_not_fight_for_names(tmp_path, monkeypatch):
    """Обе функции разом: и картинка, и дорожка меняют имя, ссылки идут следом."""
    _fake_opus(monkeypatch)
    _fake_avif(monkeypatch)
    content = _pack(_q5_image(100, "кадр.jpg") + _q5_audio(200, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Images/кадр.jpg": HEAVY,
                                         "Audio/песня.mp3": BIG_AUDIO})
    result = PackUpgrader(src, _aud_settings(compress_images=True,
                                             image_min_mb=0.1,
                                             image_limit_kb=50),
                          api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        assert "Images/кадр.avif" in names and "Audio/песня.opus" in names
        root, ns = parse_content(zf.read("content.xml"))
    refs = [i.text for i in root.findall(f'.//{tag_fn(ns)("item")}')]
    assert refs == ["кадр.avif", "песня.opus"]


def test_audio_is_reported(tmp_path, monkeypatch):
    _fake_opus(monkeypatch)
    content = _pack(_q5_audio(100, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Audio/песня.mp3": BIG_AUDIO})
    lines = example_lines(PackUpgrader(src, _aud_settings(),
                                       api=FakeApi()).run())
    assert any("Дорожек перекодировано в opus: 1" in line for line in lines)


# ── Разбор ответа ffprobe ────────────────────────────────────────────────────
def test_probe_kbps_takes_the_stream_bitrate_first():
    text = "bit_rate=320000\nbit_rate=321000\nduration=100.0\n"
    assert parse_probe_kbps(text) == 320


def test_probe_kbps_falls_back_to_size_and_duration():
    """wav и часть ogg битрейта не отдают — считаем сами."""
    text = "bit_rate=N/A\nduration=10.0\n"
    assert parse_probe_kbps(text, size=1_411_000 // 8 * 10) == 1411


def test_probe_kbps_gives_up_quietly():
    assert parse_probe_kbps("", size=0) == 0
    assert parse_probe_kbps("bit_rate=N/A\nduration=N/A\n", size=100) == 0


def test_nearest_bitrate_snaps_to_the_list():
    assert nearest_bitrate(192) == 192
    assert nearest_bitrate(200) == 192
    assert nearest_bitrate(1000) == 256
    assert nearest_bitrate(1) == 8
    assert nearest_bitrate("нет") == 192


# ── Скорость: перенос записей, потоки, фоновые постеры ───────────────────────
def test_media_keeps_its_compression_and_bytes(tmp_path):
    """Записи переносятся В ТОМ ЖЕ ВИДЕ, не распаковываясь: и способ сжатия, и
    байты те же. На этом стоит вся скорость сборки — распаковать сотню
    мегабайт mp3 и тут же сжать обратно дороже всей остальной работы."""
    path = tmp_path / "d.siq"
    blob = b"mp3-bytes" * 5000
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", _pack(_q5(100)))
        zf.writestr("Audio/a.mp3", blob, zipfile.ZIP_DEFLATED)
        zf.writestr("Video/v.mp4", blob, zipfile.ZIP_STORED)
    result = PackUpgrader(str(path), UpgradeSettings(add_titles=False),
                          api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.testzip() is None
        assert zf.read("Audio/a.mp3") == blob
        assert zf.read("Video/v.mp4") == blob
        assert zf.getinfo("Audio/a.mp3").compress_type == zipfile.ZIP_DEFLATED
        assert zf.getinfo("Video/v.mp4").compress_type == zipfile.ZIP_STORED


def test_media_survives_when_the_fast_copy_gives_up(tmp_path, monkeypatch):
    """Быстрый перенос сдался (шифрование, битый заголовок) — запись кладётся
    обычным путём, а не теряется."""
    import animepack_upgrade as U
    monkeypatch.setattr(U, "copy_zip_entry", lambda *a, **kw: False)
    content = _pack(_q5(100))
    src = _siq(tmp_path, content, media={"Audio/a.opus": b"opus-bytes"})
    result = PackUpgrader(src, UpgradeSettings(add_titles=False),
                          api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/a.opus") == b"opus-bytes"


def test_fast_copy_leaves_no_garbage_when_it_gives_up(tmp_path):
    """Оборвавшийся перенос откатывается: недописанные байты не должны остаться
    в архиве, поверх них сразу пишет обычный путь."""
    src_path = tmp_path / "a.zip"
    with zipfile.ZipFile(src_path, "w") as zf:
        zf.writestr("a.bin", b"x" * 100, zipfile.ZIP_STORED)
    out = tmp_path / "b.zip"
    with zipfile.ZipFile(src_path) as src, zipfile.ZipFile(out, "w") as dst:
        info = src.getinfo("a.bin")
        info.compress_size = 10_000          # запись «оборвётся» на середине
        assert copy_zip_entry(src, dst, info) is False
        dst.writestr("a.bin", b"x" * 100)
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["a.bin"]
        assert zf.read("a.bin") == b"x" * 100
        assert zf.testzip() is None


def test_encrypted_entry_is_not_touched_by_the_fast_copy(tmp_path):
    src_path = tmp_path / "a.zip"
    with zipfile.ZipFile(src_path, "w") as zf:
        zf.writestr("a.bin", b"x" * 100)
    with zipfile.ZipFile(src_path) as src, \
            zipfile.ZipFile(tmp_path / "b.zip", "w") as dst:
        info = src.getinfo("a.bin")
        info.flag_bits |= 0x01               # «запись зашифрована»
        assert copy_zip_entry(src, dst, info) is False


def test_media_jobs_never_exceeds_the_cores():
    """На двухъядерном ноутбуке шесть ffmpeg сразу только толкались бы."""
    assert media_jobs(6) <= (os.cpu_count() or 1)
    assert media_jobs(6) >= 1 and media_jobs(0) == 1


def test_images_keep_pack_order_when_encoded_in_parallel(tmp_path, monkeypatch):
    """Кодируются картинки в несколько потоков, а имена и порядок в отчёте — те
    же, что в паке: чья кодировка кончилась первой, значения не имеет."""
    _fake_avif(monkeypatch)
    names = [f"кадр{i}.jpg" for i in range(6)]
    media = {f"Images/{n}": HEAVY for n in names}
    content = _pack("".join(_q5_image(100 * (i + 1), n)
                            for i, n in enumerate(names)))
    result = PackUpgrader(_siq(tmp_path, content, media=media),
                          _img_settings(), api=FakeApi()).run()
    assert [c.theme_name for c in result.images] == names
    assert [c.title for c in result.images] == [f"кадр{i}.avif" for i in range(6)]
    assert [c.order for c in result.images] == list(range(6, 12))
    with zipfile.ZipFile(result.path) as zf:
        assert all(f"Images/кадр{i}.avif" in zf.namelist() for i in range(6))


def test_tracks_keep_pack_order_when_encoded_in_parallel(tmp_path, monkeypatch):
    _fake_opus(monkeypatch)
    names = [f"песня{i}.mp3" for i in range(6)]
    media = {f"Audio/{n}": BIG_AUDIO for n in names}
    content = _pack("".join(_q5_audio(100 * (i + 1), n)
                            for i, n in enumerate(names)))
    result = PackUpgrader(_siq(tmp_path, content, media=media),
                          _aud_settings(), api=FakeApi()).run()
    assert [c.theme_name for c in result.audios] == names
    assert [c.title for c in result.audios] == [f"песня{i}.opus"
                                                for i in range(6)]
    with zipfile.ZipFile(result.path) as zf:
        root, ns = parse_content(zf.read("content.xml"))
    assert [i.text for i in root.iter(tag_fn(ns)("item"))] == \
        [f"песня{i}.opus" for i in range(6)]


def test_a_track_that_failed_does_not_shift_the_others(tmp_path, monkeypatch):
    """Одна кодировка сорвалась — соседние всё равно на своих местах."""
    _fake_opus(monkeypatch)
    real = PackUpgrader._to_opus

    def flaky(self, raw, out):
        if os.path.getsize(raw) == len(BIG_AUDIO) + 1:   # вторая дорожка
            return False
        return real(self, raw, out)

    monkeypatch.setattr(PackUpgrader, "_to_opus", flaky)
    media = {"Audio/a.mp3": BIG_AUDIO, "Audio/b.mp3": BIG_AUDIO + b"S",
             "Audio/c.mp3": BIG_AUDIO}
    content = _pack(_q5_audio(100, "a.mp3") + _q5_audio(200, "b.mp3")
                    + _q5_audio(300, "c.mp3"))
    result = PackUpgrader(_siq(tmp_path, content, media=media),
                          _aud_settings(), api=FakeApi()).run()
    assert [c.theme_name for c in result.audios] == ["a.mp3", "c.mp3"]
    with zipfile.ZipFile(result.path) as zf:
        assert "Audio/b.mp3" in zf.namelist()      # осталась как была
        assert "Audio/b.opus" not in zf.namelist()


# ── Постер готовится в фоне, пока идёт опрос Shikimori ───────────────────────
def test_poster_size_reaches_the_report(tmp_path, monkeypatch):
    """Ссылка в вопрос пишется раньше, чем постер скачан, — но размер в отчёте
    всё равно настоящий."""
    _fake_poster(monkeypatch, size=2048)
    content = _pack(_q5(100, answer="Блич") + _q5(200, answer="Bleach"))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    assert [c.after for c in result.posters] == ["постер, 2 КБ"] * 2


def test_poster_that_never_arrives_leaves_no_dangling_ref(tmp_path, monkeypatch):
    """Постер не дался — ссылку из вопроса надо убрать: пак не должен звать
    файл, которого в нём нет."""
    monkeypatch.setattr(PackUpgrader, "_fetch", lambda self, url: b"raw")
    monkeypatch.setattr(PackUpgrader, "_to_avif",
                        lambda self, raw, out, limit_kb=None: False)
    content = _pack(_q5(100, answer="Блич"))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    assert result.posters == []
    root, ns = _out_root(result)
    assert not [i for i in root.iter(tag_fn(ns)("item"))
                if (i.get("type") or "") == "image"]
    with zipfile.ZipFile(result.path) as zf:
        assert not [n for n in zf.namelist() if n.endswith(".avif")]


def test_failed_poster_is_taken_out_of_a_v4_question(tmp_path, monkeypatch):
    monkeypatch.setattr(PackUpgrader, "_fetch", lambda self, url: b"raw")
    monkeypatch.setattr(PackUpgrader, "_to_avif",
                        lambda self, raw, out, limit_kb=None: False)
    content = _pack(_q4(100, answer="Блич"))
    result = _run(tmp_path, content, _poster_settings(), api=FakeApi([POSTERED]))
    root, ns = _out_root(result)
    atoms = root.find(f'.//{tag_fn(ns)("scenario")}').findall(tag_fn(ns)("atom"))
    assert [a.get("type") for a in atoms] == [None, "marker"]
    assert result.posters == []


def test_failed_download_does_not_break_the_run(tmp_path, monkeypatch):
    def boom(self, url):
        raise OSError("сеть отвалилась")

    monkeypatch.setattr(PackUpgrader, "_fetch", boom)
    content = _pack(_q5(100, answer="Блич"))
    lines = []
    result = _run(tmp_path, content, _poster_settings(),
                  api=FakeApi([POSTERED]), log=lines.append)
    assert result.posters == [] and result.path
    assert any("сеть отвалилась" in line for line in lines)


def test_remove_poster_takes_the_picture_out_of_both_formats():
    v5 = ET.fromstring('<question><params><param name="answer" type="content">'
                       '<item type="image" isRef="True">p.avif</item>'
                       "</param></params></question>")
    assert remove_poster(v5, "p.avif") is True
    assert not list(v5.iter("item"))
    v4 = ET.fromstring('<question><scenario><atom>Текст</atom>'
                       '<atom type="marker"/><atom type="image">@p.avif</atom>'
                       "</scenario></question>")
    assert remove_poster(v4, "p.avif") is True
    assert [a.get("type") for a in v4.iter("atom")] == [None, "marker"]
    assert remove_poster(v4, "нет.avif") is False


def test_poster_threads_do_not_outlive_the_run(tmp_path, monkeypatch):
    """Потоки постеров закрываются вместе с прогоном: висящий пул держал бы
    приложение открытым и после выхода."""
    _fake_poster(monkeypatch)
    up = PackUpgrader(_siq(tmp_path, _pack(_q5(100, answer="Блич"))),
                      _poster_settings(), api=FakeApi([POSTERED]))
    up.run()
    assert up._pool is None
    assert not [t for t in threading.enumerate()
                if t.name.startswith("siqposter")]


def test_stop_in_the_middle_of_media_leaves_nothing_behind(tmp_path,
                                                           monkeypatch):
    """«Стоп» посреди пачки кодировок: пак не пишется, временные файлы убраны,
    потоки закрыты. Кодируется теперь по нескольку файлов разом — важно, что
    остановка добирается до каждого."""
    started = []

    def slow(self, raw, out, limit_kb=None):
        started.append(raw)
        with open(out, "wb") as f:
            f.write(b"A" * 400)
        return True

    monkeypatch.setattr(PackUpgrader, "_to_avif", slow)
    names = [f"кадр{i}.jpg" for i in range(6)]
    media = {f"Images/{n}": HEAVY for n in names}
    content = _pack("".join(_q5_image(100, n) for n in names))
    up = PackUpgrader(_siq(tmp_path, content, media=media), _img_settings(),
                      api=FakeApi(), should_stop=lambda: True)
    result = up.run()
    assert result.cancelled and not result.path
    assert result.images == [] and started == []       # кодировать не начали
    assert list(tmp_path.glob("*апгрейд*")) == []
    assert not [t for t in threading.enumerate()
                if t.name.startswith("siqmedia")]


def test_stop_during_posters_closes_the_threads(tmp_path, monkeypatch):
    _fake_poster(monkeypatch)
    up = PackUpgrader(_siq(tmp_path, _pack(_q5(100, answer="Блич"))),
                      _poster_settings(), api=FakeApi([POSTERED]),
                      should_stop=lambda: True)
    result = up.run()
    assert result.cancelled and not result.path
    assert up._pool is None
    assert not [t for t in threading.enumerate()
                if t.name.startswith("siqposter")]


def test_no_temp_files_are_left_behind(tmp_path, monkeypatch):
    """Ни одна ветка не забывает свой временный файл — ни удачная, ни «после
    сжатия не легче», ни сорвавшаяся кодировка. Раньше в %TEMP% копились
    недоеденные siqimg_*/siqaud_* с каждого прогона."""
    import animepack_upgrade as U

    def picky(self, raw, out, limit_kb=None):
        size = os.path.getsize(raw)
        if size == len(HEAVY) + 1:              # «битая» — кодировка сорвалась
            return False
        with open(out, "wb") as f:              # «толстая» — стала тяжелее
            f.write(b"A" * (len(HEAVY) + 2 if size == len(HEAVY) + 2 else 400))
        return True

    monkeypatch.setattr(PackUpgrader, "_to_avif", picky)
    media = {"Images/ок.jpg": HEAVY, "Images/битая.jpg": HEAVY + b"J",
             "Images/толстая.jpg": HEAVY + b"JJ"}
    content = _pack(_q5_image(100, "ок.jpg") + _q5_image(200, "битая.jpg")
                    + _q5_image(300, "толстая.jpg"))
    before = set(os.listdir(U._temp_dir()))
    result = PackUpgrader(_siq(tmp_path, content, media=media),
                          _img_settings(), api=FakeApi()).run()
    assert [c.theme_name for c in result.images] == ["ок.jpg"]
    assert set(os.listdir(U._temp_dir())) - before == set()


# ── Известные подписи («Назвать персонажа») ──────────────────────────────────
def test_known_label_goes_even_if_one_question_lacks_it(tmp_path):
    """Живой случай из «Anime by Hinoriku 6», тема «Hayami Saori»: «Назвать
    персонажа» стоит в семи вопросах из восьми, а восьмой спрашивает совсем
    другое — по правилу «в каждом» подпись оставалась во всех семи."""
    qs = "".join(_q5_items(p, "<item>Назвать персонажа</item>" + _shot())
                 for p in (100, 200, 300))
    qs += _q5_items(400, "<item>А сколько их было в зимнем сезоне?</item>")
    result = _run(tmp_path, _themes(f"Hayami Saori|{qs}"), KNOWN_REPEATS)
    assert len(result.repeats) == 3
    assert {c.before for c in result.repeats} == {"Назвать персонажа"}
    assert all("известная подпись" in c.after for c in result.repeats)
    root, _ns = _out_root(result)
    texts = [el.text for el in root.iter()
             if el.text and "персонажа" in str(el.text)]
    assert texts == []                       # подписи в паке не осталось
    # А чужой вопрос — тот, что спрашивал своё, — цел.
    assert any("зимнем сезоне" in (el.text or "") for el in root.iter())


def test_known_label_can_be_switched_off(tmp_path):
    qs = "".join(_q5_items(p, "<item>Назвать персонажа</item>" + _shot())
                 for p in (100, 200))
    qs += _q5_items(300, "<item>Своё</item>" + _shot())
    assert _run(tmp_path, _themes(f"Тема|{qs}"), ONLY_REPEATS).repeats == []


def test_known_label_never_empties_a_question(tmp_path):
    """Кроме подписи в вопросе ничего нет — не трогаем: играть станет нечем."""
    qs = (_q5_items(100, "<item>Назвать аниме</item>")
          + _q5_items(200, "<item>Назвать аниме</item>" + _shot())
          + _q5_items(300, "<item>Своё</item>" + _shot()))
    result = _run(tmp_path, _themes(f"Тема|{qs}"), KNOWN_REPEATS)
    assert [c.price for c in result.repeats] == [200]


def test_known_labels_are_matched_without_case_and_punctuation():
    q = ET.fromstring('<question><params><param name="question">'
                      "<item>назвать ПЕРСОНАЖА:</item></param></params>"
                      "</question>")
    assert known_labels_in([q]) == ["назвать ПЕРСОНАЖА:"]
    assert "Назвать персонажа" in KNOWN_LABELS


def test_known_label_and_repeated_text_live_together(tmp_path):
    """Одна подпись стоит везде (общее правило), другая — не везде (список)."""
    qs = (_q5_items(100, "<item>Назвать персонажа</item>"
                    "<item>Скрин ниже</item>" + _shot())
          + _q5_items(200, "<item>Скрин ниже</item>" + _shot()))
    result = _run(tmp_path, _themes(f"Тема|{qs}"), KNOWN_REPEATS)
    assert {c.before for c in result.repeats} == {"Назвать персонажа",
                                                  "Скрин ниже"}
    assert len(result.repeats) == 3


# ── Неиспользуемые файлы ─────────────────────────────────────────────────────
ONLY_UNUSED = UpgradeSettings(strip_specials=False, add_titles=False,
                              compress_images=False, strip_repeated_text=False,
                              drop_empty_questions=False, compress_audio=False,
                              drop_unused=True)


def test_unused_media_is_dropped_and_referenced_survives(tmp_path):
    content = _pack(_q5_image(100, "нужная.jpg"))
    media = {"Images/нужная.jpg": b"J" * 10, "Images/лишняя.jpg": b"J" * 500,
             "Audio/забытая.mp3": b"S" * 700}
    result = PackUpgrader(_siq(tmp_path, content, media=media),
                          ONLY_UNUSED, api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
    assert "Images/нужная.jpg" in names
    assert "Images/лишняя.jpg" not in names and "Audio/забытая.mp3" not in names
    assert {c.theme_name for c in result.unused} == {"лишняя.jpg",
                                                     "забытая.mp3"}
    assert result.saved_unused_bytes == 1200


def test_pack_logo_is_not_garbage(tmp_path):
    """Логотип пака записан атрибутом, а не ссылкой в вопросе: ссылок «из
    вопросов» на него нет, но выкидывать его нельзя."""
    content = ('<?xml version="1.0" encoding="utf-8"?>\n'
               '<package name="Пак" version="5" logo="@лого.png">'
               '<rounds><round name="Р"><themes><theme name="Т"><questions>'
               + _q5_image(100, "нужная.jpg") +
               "</questions></theme></themes></round></rounds></package>")
    media = {"Images/нужная.jpg": b"J" * 10, "Images/лого.png": b"L" * 10}
    result = PackUpgrader(_siq(tmp_path, content, media=media),
                          ONLY_UNUSED, api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert "Images/лого.png" in zf.namelist()
    assert result.unused == []


def test_service_files_are_never_garbage(tmp_path):
    media = {"Texts/authors.xml": b"<authors/>",
             "[Content_Types].xml": b"<Types/>"}
    result = PackUpgrader(_siq(tmp_path, _pack(_q5(100)), media=media),
                          ONLY_UNUSED, api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
    assert "Texts/authors.xml" in names and "[Content_Types].xml" in names
    assert result.unused == []


def test_all_media_unused_touches_nothing(tmp_path):
    """Ни одной ссылки на весь пак — значит ссылки записаны как-то иначе, а не
    пак из одного мусора: не трогаем ничего."""
    media = {"Images/a.jpg": b"J", "Images/b.jpg": b"J"}
    result = PackUpgrader(_siq(tmp_path, _pack(_q5(100)), media=media),
                          ONLY_UNUSED, api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert {"Images/a.jpg", "Images/b.jpg"} <= set(zf.namelist())
    assert result.unused == [] and result.saved_unused_bytes == 0


def test_recoded_image_is_not_counted_as_garbage(tmp_path, monkeypatch):
    """Пережатая картинка лежит уже под новым именем — по старому её не зовут,
    но мусором она от этого не становится."""
    _fake_avif(monkeypatch)
    content = _pack(_q5_image(100, "кадр.jpg"))
    src = _siq(tmp_path, content, media={"Images/кадр.jpg": HEAVY})
    result = PackUpgrader(src, _img_settings(drop_unused=True),
                          api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert "Images/кадр.avif" in zf.namelist()
    assert result.unused == []


def test_percent_encoded_name_is_matched_to_its_reference(tmp_path):
    content = _pack(_q5_image(100, "кадр.jpg"))
    src = _siq(tmp_path, content,
               media={"Images/" + escape_uri_string("кадр.jpg"): b"J" * 10})
    result = PackUpgrader(src, ONLY_UNUSED, api=FakeApi()).run()
    assert result.unused == []


def test_unused_helpers_are_pure():
    assert entry_basename("Images/%D0%BA.jpg") == "к.jpg"
    assert entry_basename("Images\\a.jpg") == "a.jpg"
    assert is_media_entry("Images/a.JPG") and is_media_entry("Video/v.mp4")
    assert not is_media_entry("content.xml")
    assert not is_media_entry("Texts/authors.xml")
    root = ET.fromstring('<package logo="@a.png"><item>b.jpg</item>'
                         "<atom>@c.mp3</atom></package>")
    refs = referenced_names(root)
    assert {"a.png", "b.jpg", "c.mp3"} <= refs
    names = ["Images/a.png", "Images/b.jpg", "Audio/c.mp3", "Video/d.mp4",
             "Images/e.jpg", "content.xml"]
    assert unused_entries(names, refs) == ["Video/d.mp4", "Images/e.jpg"]
    assert unused_entries(names, refs, keep=["Video/d.mp4"]) == ["Images/e.jpg"]


def test_unused_is_reported(tmp_path):
    content = _pack(_q5_image(100, "нужная.jpg"))
    media = {"Images/нужная.jpg": b"J", "Images/лишняя.jpg": b"J" * 2048}
    result = PackUpgrader(_siq(tmp_path, content, media=media),
                          ONLY_UNUSED, api=FakeApi()).run()
    lines = example_lines(result)
    assert any("Неиспользуемых файлов удалено: 1" in l for l in lines)
    assert any("лишняя.jpg" in l for l in lines)


# ── Нормализация громкости ───────────────────────────────────────────────────
def test_loudnorm_is_off_unless_asked():
    s = UpgradeSettings()
    assert s.audio_norm is False
    assert loudnorm_filter(s) == ""
    # Фикс раскладки каналов идёт всегда: libopus не берёт «боковые» раскладки.
    assert audio_filter_chain(s).startswith("aformat=")


def test_loudnorm_string_is_the_one_from_the_process_tab():
    s = UpgradeSettings(audio_norm=True)
    assert loudnorm_filter(s) == "loudnorm=I=-20:LRA=11:TP=-1.5"
    assert audio_filter_chain(s).startswith("loudnorm=I=-20:LRA=11:TP=-1.5,")
    tuned = UpgradeSettings(audio_norm=True, audio_norm_i=-16.0,
                            audio_norm_lra=7.0, audio_norm_tp=-2.0)
    assert loudnorm_filter(tuned) == "loudnorm=I=-16:LRA=7:TP=-2"


def test_norm_recodes_even_a_track_that_is_quiet_enough(tmp_path, monkeypatch):
    """Пропущенная дорожка осталась бы с прежней громкостью — то есть громче
    или тише всех соседних: с нормализацией оговорка «и так N кбит» снимается."""
    _fake_opus(monkeypatch, kbps=128)
    content = _pack(_q5_audio(100, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Audio/песня.mp3": BIG_AUDIO})
    result = PackUpgrader(src, _aud_settings(audio_kbps=192, audio_norm=True),
                          api=FakeApi()).run()
    assert len(result.audios) == 1
    with zipfile.ZipFile(result.path) as zf:
        assert "Audio/песня.opus" in zf.namelist()


def test_norm_keeps_the_track_even_if_it_got_heavier(tmp_path, monkeypatch):
    _fake_opus(monkeypatch, size=len(BIG_AUDIO) + 10, kbps=320)
    content = _pack(_q5_audio(100, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Audio/песня.mp3": BIG_AUDIO})
    result = PackUpgrader(src, _aud_settings(audio_norm=True),
                          api=FakeApi()).run()
    assert len(result.audios) == 1
    # Без нормализации та же дорожка осталась бы исходной.
    plain = PackUpgrader(src, _aud_settings(), api=FakeApi()).run()
    assert plain.audios == []


def test_norm_goes_into_the_ffmpeg_line(tmp_path, monkeypatch):
    seen = []

    def fake_run(cmd, should_stop=None, timeout=0, capture=False):
        seen.append(list(cmd))
        with open(cmd[-1], "wb") as f:
            f.write(b"O" * 100)
        return 0, ""

    monkeypatch.setattr("animepack_upgrade.run_hidden", fake_run)
    monkeypatch.setattr(PackUpgrader, "_audio_kbps", lambda self, r, size=0: 320)
    content = _pack(_q5_audio(100, "песня.mp3"))
    src = _siq(tmp_path, content, media={"Audio/песня.mp3": BIG_AUDIO})
    PackUpgrader(src, _aud_settings(audio_norm=True), api=FakeApi()).run()
    line = " ".join(seen[-1])
    assert "loudnorm=I=-20:LRA=11:TP=-1.5" in line and "libopus" in line


# ── Сжатие видео ─────────────────────────────────────────────────────────────
BIG_VIDEO = b"V" * 400_000              # «тяжёлый» ролик для тестов


def _vid_settings(**kw):
    base = dict(strip_specials=False, add_titles=False, compress_images=False,
                strip_repeated_text=False, drop_empty_questions=False,
                compress_audio=False, drop_unused=False, compress_video=True,
                video_min_mb=0.3)
    base.update(kw)
    return UpgradeSettings(**base)


def _fake_av1(monkeypatch, size: int = 9000, codec: str = "h264"):
    def fake_encode(self, raw, out):
        with open(out, "wb") as f:
            f.write(b"A" * size)
        return True

    monkeypatch.setattr(PackUpgrader, "_to_av1", fake_encode)
    monkeypatch.setattr(PackUpgrader, "_video_codec", lambda self, raw: codec)


def _q5_video(price: int, name: str) -> str:
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content">'
            f'<item type="video" isRef="True">{name}</item></param>'
            "</params><right><answer>Ответ</answer></right></question>")


def test_heavy_video_becomes_av1_and_ref_follows(tmp_path, monkeypatch):
    _fake_av1(monkeypatch)
    content = _pack(_q5_video(100, "ролик.mkv"))
    src = _siq(tmp_path, content, media={"Video/ролик.mkv": BIG_VIDEO})
    result = PackUpgrader(src, _vid_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        assert "Video/ролик.mp4" in names and "Video/ролик.mkv" not in names
        root, ns = parse_content(zf.read("content.xml"))
    assert root.find(f'.//{tag_fn(ns)("item")}').text == "ролик.mp4"
    assert len(result.videos) == 1 and result.heavy_video == 1
    assert result.saved_video_bytes == len(BIG_VIDEO) - 9000
    assert "h264" in result.videos[0].before
    assert "av1 crf 45" in result.videos[0].after


def test_light_non_av1_video_is_recoded_only_with_the_checkbox(tmp_path,
                                                               monkeypatch):
    _fake_av1(monkeypatch, size=500, codec="h264")
    content = _pack(_q5_video(100, "ролик.mp4"))
    media = {"Video/ролик.mp4": b"V" * 1000}       # намного легче порога
    src = _siq(tmp_path, content, media=media)
    assert len(PackUpgrader(src, _vid_settings(video_non_av1=True),
                            api=FakeApi()).run().videos) == 1
    off = PackUpgrader(src, _vid_settings(video_non_av1=False),
                       api=FakeApi()).run()
    assert off.videos == [] and off.heavy_video == 0


def test_light_av1_video_is_left_alone(tmp_path, monkeypatch):
    """Уже AV1 и легче порога — второй перекод только испортил бы картинку."""
    _fake_av1(monkeypatch, codec="av1")
    content = _pack(_q5_video(100, "ролик.mp4"))
    src = _siq(tmp_path, content, media={"Video/ролик.mp4": b"V" * 1000})
    result = PackUpgrader(src, _vid_settings(video_non_av1=True),
                          api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Video/ролик.mp4") == b"V" * 1000
    assert result.videos == [] and result.heavy_video == 1


def test_heavy_av1_video_is_recoded_anyway(tmp_path, monkeypatch):
    """Тяжелее порога — жмём, каким бы кодеком ролик ни был закодирован."""
    _fake_av1(monkeypatch, codec="av1")
    content = _pack(_q5_video(100, "ролик.mp4"))
    src = _siq(tmp_path, content, media={"Video/ролик.mp4": BIG_VIDEO})
    result = PackUpgrader(src, _vid_settings(), api=FakeApi()).run()
    assert len(result.videos) == 1


def test_video_that_got_heavier_stays_as_it_was(tmp_path, monkeypatch):
    _fake_av1(monkeypatch, size=len(BIG_VIDEO) + 10)
    content = _pack(_q5_video(100, "ролик.mp4"))
    src = _siq(tmp_path, content, media={"Video/ролик.mp4": BIG_VIDEO})
    result = PackUpgrader(src, _vid_settings(), api=FakeApi()).run()
    with zipfile.ZipFile(result.path) as zf:
        assert zf.read("Video/ролик.mp4") == BIG_VIDEO
    assert result.videos == []


def test_images_and_audio_are_not_video(tmp_path, monkeypatch):
    _fake_av1(monkeypatch)
    media = {"Images/кадр.jpg": HEAVY, "Audio/песня.mp3": BIG_AUDIO}
    src = _siq(tmp_path, _pack(_q5(100)), media=media)
    result = PackUpgrader(src, _vid_settings(), api=FakeApi()).run()
    assert result.heavy_video == 0 and result.videos == []


def test_video_ffmpeg_line_is_the_one_from_the_process_tab(tmp_path,
                                                           monkeypatch):
    seen = []

    def fake_run(cmd, should_stop=None, timeout=0, capture=False):
        seen.append(list(cmd))
        if "-show_entries" in cmd:              # это ffprobe
            return 0, "codec_name=h264"
        with open(cmd[-1], "wb") as f:
            f.write(b"A" * 100)
        return 0, ""

    monkeypatch.setattr("animepack_upgrade.run_hidden", fake_run)
    content = _pack(_q5_video(100, "ролик.mp4"))
    src = _siq(tmp_path, content, media={"Video/ролик.mp4": BIG_VIDEO})
    PackUpgrader(src, _vid_settings(video_height=720, audio_norm=True),
                 api=FakeApi()).run()
    line = " ".join(seen[-1])
    assert "libsvtav1" in line and "tune=0:keyint=-1:scd=1" in line
    assert "-crf 45" in line and "-preset 13" in line
    assert "min(720,ih)" in line
    assert "libopus" in line and "loudnorm=I=-20" in line


def test_video_report_and_helpers():
    assert parse_probe_codec("codec_name=av1\n") == "av1"
    assert parse_probe_codec("codec_name=\ncodec_name=hevc") == "hevc"
    assert parse_probe_codec("") == ""
    assert nearest_height(0) == 0 and nearest_height(700) == 720
    assert nearest_height(4000) == 1080 and nearest_height("нет") == 0


def test_video_is_reported(tmp_path, monkeypatch):
    _fake_av1(monkeypatch)
    content = _pack(_q5_video(100, "ролик.mp4"))
    src = _siq(tmp_path, content, media={"Video/ролик.mp4": BIG_VIDEO})
    lines = example_lines(PackUpgrader(src, _vid_settings(),
                                       api=FakeApi()).run())
    assert any("Роликов перекодировано в AV1: 1" in l for l in lines)


# ── Профиль ───────────────────────────────────────────────────────────────────
# Профиль на паке теперь только один («anime»), но старое сохранённое значение
# («movie», из версий с кино-паком) не должно ломать чтение settings.json —
# normalize_profile сводит любой мусор к единственному, что есть.
def test_profile_name_is_sanitised():
    assert normalize_profile("movie") == "anime"
    assert normalize_profile("anime") == "anime"
    assert normalize_profile("что-то не то") == "anime"
    assert normalize_profile(None) == "anime"
    assert UpgradeSettings().source_name == "Shikimori"
    assert UpgradeSettings.from_dict({"profile": "movie"}).profile == "anime"
