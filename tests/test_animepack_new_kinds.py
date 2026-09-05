# -*- coding: utf-8 -*-
"""Три новых рода вопросов аниме-пака: анаграммы, пиксели и сюжет с Fandom.

Сети тут нет вовсе: вики и Gemini подменяются заглушками, ffmpeg не зовётся.
Проверяется то, что ломается молча, — доли в ползунке и квотах, содержимое
content.xml, чистка разметки вики и то, что эффект пикселизации у пака и у
вкладки «Монтаж» считается ОДНОЙ функцией (а не двумя разъехавшимися копиями).
"""
import os
import random
import xml.etree.ElementTree as ET

import pytest

import animepack
import animepack_api as api
import animepack_plot as plot
from animepack import (ANAGRAM_KIND, FRAME_KIND, PIXEL_KIND, PLOT_KIND,
                       PackSettings, SongCandidate, anagram_source,
                       build_content_xml, make_anagram)


def make_anime(**over):
    anime = {
        "id": 1535, "malId": 1535, "name": "Death Note",
        "russian": "Тетрадь смерти", "english": "Death Note",
        "japanese": "デスノート", "synonyms": ["DN"],
        "franchise": "death_note", "score": 8.6, "kind": "tv",
        "poster": {"originalUrl": "https://shiki/poster.jpg"},
        "screenshots": [{"originalUrl": f"https://shiki/{i}.jpg"} for i in range(6)],
        "airedOn": {"year": 2006},
        "statusesStats": [{"status": "completed", "count": 1000}],
    }
    anime.update(over)
    return anime


# ── Анаграммы ────────────────────────────────────────────────────────────────
def test_anagram_keeps_letters_and_word_shape():
    """Те же буквы и та же форма слов — меняется только порядок."""
    title = "Тетрадь смерти"
    out = make_anagram(title, random.Random(1))
    assert out != title.upper()
    assert sorted(out) == sorted(title.upper())          # буквы все и те же
    assert [len(w) for w in out.split()] == [len(w) for w in title.split()]


def test_anagram_shuffles_each_word_within_itself():
    """Буквы не переезжают из слова в слово: в каждом слове ровно его набор.

    Раньше мешалось всё название разом, и «Охотник х Охотник» давал «ОКИТИХХ Х
    ОТНКОНО» — второе слово из чужих букв."""
    title = "Мастера меча онлайн"
    out = make_anagram(title, random.Random(1))
    assert out != title.upper()
    for src, got in zip(title.upper().split(), out.split()):
        assert sorted(got) == sorted(src)


def test_anagram_gives_up_when_there_is_nothing_to_shuffle():
    """Слова из одной буквы и из одинаковых букв переставлять некуда."""
    assert make_anagram("А Б В Г Д Е", random.Random(1)) == ""
    assert make_anagram("ААА БББ", random.Random(1)) == ""


def test_anagram_is_uppercase_and_keeps_punctuation_in_place():
    out = make_anagram("Steins;Gate 0", random.Random(3))
    assert out == out.upper()
    # Знаки и цифры остаются на своих местах: перемешиваются только буквы.
    assert out[6] == ";" and out.endswith(" 0")


def test_anagram_refuses_short_titles():
    """Из четырёх букв анаграмма — не загадка, а лотерея."""
    assert make_anagram("Кадо", random.Random(1)) == ""
    assert make_anagram("", random.Random(1)) == ""


def test_anagram_source_sticks_to_the_asked_language():
    """Язык строгий: подмены на соседний больше нет."""
    anime = make_anime()
    assert anagram_source(anime, "russian") == "Тетрадь смерти"
    assert anagram_source(anime, "english") == "Death Note"
    assert anagram_source(anime, "romaji") == "Death Note"
    # Просимого названия нет — вопроса нет, а не тихая латиница в русском паке.
    assert anagram_source(make_anime(english="", name=""), "english") == ""
    # Иероглифы игроку не набрать: японское название в анаграмму не годится.
    assert anagram_source({"russian": "", "english": "", "name": "デスノート"},
                          "romaji") == ""


def test_anagram_source_checks_the_script_of_the_title():
    """В поле russian у Shikimori нередко лежит латиница («Ao Ashi»)."""
    latin_ru = make_anime(russian="Ao Ashi", english="Ao Ashi", name="Ao Ashi")
    assert anagram_source(latin_ru, "russian") == ""
    assert anagram_source(latin_ru, "english") == "Ao Ashi"
    # И наоборот: кириллица там, где ждут латиницу.
    assert anagram_source(make_anime(english="Тетрадь смерти"), "english") == ""


def test_anagram_source_skips_sequels_and_subtitles():
    """Загадывать надо тайтл, а не его третий сезон с приставкой."""
    assert anagram_source(make_anime(russian="Мастера меча онлайн")) == \
        "Мастера меча онлайн"
    for tail in ("Мастера меча онлайн: Порядковый ранг", "Второй Мэйджор 2",
                 "Трусливый велосипедист: Новое поколение",
                 "Атака титанов. Часть 3"):
        assert anagram_source(make_anime(russian=tail)) == ""


def test_anagram_source_obeys_the_length_limit():
    """Названия-простыни в анаграмму не годятся: каша нерешаема."""
    long_ru = ("Я переродился торговым автоматом и брожу по лабиринту")
    anime = make_anime(russian=long_ru, english="Reborn as a Vending Machine",
                       name="Jidou Hanbaiki")
    # Потолка нет — берётся просимое название, каким бы длинным оно ни было.
    assert anagram_source(anime, "russian") == long_ru
    # С потолком длинное название пропускается целиком: на соседний язык
    # вопрос больше не уезжает.
    assert anagram_source(anime, "russian", max_chars=30) == ""
    assert anagram_source(anime, "english", max_chars=30) == \
        "Reborn as a Vending Machine"
    assert anagram_source(anime, "english", max_chars=12) == ""


def test_anagram_length_limit_is_clamped_to_the_minimum():
    """Потолок ниже самой короткой анаграммы убил бы весь род вопросов."""
    s = PackSettings.from_dict({"anagram_max_chars": 3})
    assert s.anagram_max_chars == animepack.ANAGRAM_MIN_LETTERS
    assert PackSettings.from_dict({"anagram_max_chars": 0}).anagram_max_chars == 0
    assert PackSettings.from_dict({"anagram_max_chars": 55}).anagram_max_chars == 55


def test_anagram_seconds_counts_every_character():
    """Время показа = длина текста, делённая на символы в секунду."""
    assert animepack.anagram_seconds("x" * 30, 10) == 3
    assert animepack.anagram_seconds("x" * 31, 10) == 4       # округление ВВЕРХ
    assert animepack.anagram_seconds("x" * 60, 20) == 3
    # Короткому тексту достаётся пол: мелькнувшую анаграмму никто не прочтёт.
    assert animepack.anagram_seconds("x" * 12, 10) == animepack.ANAGRAM_MIN_SECONDS
    # Ноль — таймера нет вовсе.
    assert animepack.anagram_seconds("x" * 30, 0) == 0
    assert animepack.anagram_seconds("", 10) == 0


def test_anagram_cps_is_clamped_on_load():
    assert PackSettings.from_dict({"anagram_cps": 0}).anagram_cps == 0
    assert PackSettings.from_dict({"anagram_cps": 0.2}).anagram_cps == 1.0
    assert PackSettings.from_dict({"anagram_cps": 999}).anagram_cps == \
        animepack.ANAGRAM_CPS_MAX
    assert PackSettings.from_dict({}).anagram_cps == animepack.ANAGRAM_CHARS_PER_SEC


def test_anagram_question_is_bare_text_with_its_own_timer(tmp_path):
    s = PackSettings(pct_songs=0, pack_anagram=True, pct_anagram=100,
                     rounds=1, themes=1, questions=1, anagram_cps=10)
    cand = SongCandidate(song={}, anime=make_anime(), kind=ANAGRAM_KIND)
    cand.anagram = "ТЕДТРАЬ СИМТРЕ"
    root = ET.fromstring(build_content_xml([cand], s))
    ns = {"s": animepack.SIQ_NS}
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    # Никакой подписи сверху: весь вопрос — сама анаграмма.
    assert [i.text for i in items] == ["ТЕДТРАЬ СИМТРЕ"]
    # Время показа своё, а не «скорость чтения» из настроек игрока.
    assert items[0].get("duration") == "00:00:03"
    # Ответ — обычный: название тайтла со всеми написаниями.
    answers = [a.text for a in root.findall(".//s:right/s:answer", ns)]
    assert answers[0].startswith("Тетрадь смерти") and "Death Note" in answers


def test_anagram_without_timer_has_no_duration(tmp_path):
    """«без таймера» (0) — анаграмма висит, пока ведущий не откроет ответ."""
    s = PackSettings(pct_songs=0, pack_anagram=True, pct_anagram=100,
                     rounds=1, themes=1, questions=1, anagram_cps=0)
    cand = SongCandidate(song={}, anime=make_anime(), kind=ANAGRAM_KIND)
    cand.anagram = "ТЕДТРАЬ СИМТРЕ"
    root = ET.fromstring(build_content_xml([cand], s))
    ns = {"s": animepack.SIQ_NS}
    item = root.find(".//s:param[@name='question']/s:item", ns)
    assert item.get("duration") is None


# ── Пиксели ──────────────────────────────────────────────────────────────────
def test_pixelize_is_the_same_function_as_in_montage():
    """Эффект у пака и у вкладки «Монтаж» — одна функция, а не две копии."""
    import pixelize
    from edit_tab_base import _pixelize_block_sequence
    assert _pixelize_block_sequence is pixelize.block_sequence
    assert pixelize.block_sequence(64, 6) == [64, 35, 20, 11, 6, 1]


def test_pixel_filter_walks_blocks_down_over_the_clip():
    s = PackSettings(pct_songs=0, pack_pixel=True, pct_pixel=100,
                     pixel_seconds=6, pixel_steps=3, pixel_block=32)
    gen = animepack.AnimePackGenerator(s, session=object(), amq=object(),
                                       anisong=object(), mal=object(),
                                       shikimori=object())
    vf = gen.pixel_filter()
    assert vf.startswith(f"scale=-2:{animepack.PIXEL_HEIGHT},")
    # Три ступени: два блочных окна по две секунды и «чётко» в конце.
    assert "pixelize=w=32:h=32:enable='between(t,0.000,2.000)'" in vf
    assert "pixelize=w=6:h=6:enable='between(t,2.000,4.000)'" in vf
    assert "between(t,4.000,6.000)" not in vf


def test_pixel_question_is_a_video_item():
    s = PackSettings(pct_songs=0, pack_pixel=True, pct_pixel=100,
                     pixel_seconds=8, rounds=1, themes=1, questions=1)
    cand = SongCandidate(song={}, anime=make_anime(), kind=PIXEL_KIND,
                         media_base="Пак(Тетрадь смерти)")
    cand.has_video = True
    root = ET.fromstring(build_content_xml([cand], s))
    ns = {"s": animepack.SIQ_NS}
    item = root.find(".//s:param[@name='question']/s:item", ns)
    assert item.get("type") == "video" and item.get("isRef") == "True"
    assert item.get("duration") == "00:00:08"
    assert item.text == cand.video_out


def test_pixel_frames_go_to_history_by_the_video(tmp_path):
    """Кадр вопроса-пикселей помнится так же, как обычный кадр, — но «дошёл до
    пака» у него значит собранный ролик, а не картинку в Images/."""
    path = str(tmp_path / "frames.json")
    s = PackSettings(pct_songs=0, pack_pixel=True, pct_pixel=100,
                     frames_no_repeat=True)
    gen = animepack.AnimePackGenerator(s, session=object(), amq=object(),
                                       anisong=object(), mal=object(),
                                       shikimori=object(),
                                       frames_history_path=path)
    used = SongCandidate(song={}, anime=make_anime(), kind=PIXEL_KIND)
    used.frame_url, used.has_video = "https://shiki/2.jpg", True
    lost = SongCandidate(song={}, anime=make_anime(), kind=PIXEL_KIND)
    lost.frame_url = "https://shiki/5.jpg"        # ролик не собрался
    gen.save_frames_history([used, lost])
    assert animepack.load_frame_history(path) == ["https://shiki/2.jpg"]


# ── Сюжет: разбор вики ───────────────────────────────────────────────────────
def test_wiki_slugs_are_both_fandom_spellings():
    assert api.wiki_slugs("Attack on Titan") == ["attackontitan",
                                                 "attack-on-titan"]
    # Самое длинное слово — последняя надежда: «Neon Genesis Evangelion»
    # живёт на evangelion.fandom.com.
    assert "evangelion" in api.wiki_slugs("Neon Genesis Evangelion")
    # Короткие слова в запас не берутся: «attack» — это чужая вики.
    assert "attack" not in api.wiki_slugs("Attack on Titan")
    # Кириллице в адресе взяться неоткуда.
    assert api.wiki_slugs("Тетрадь смерти") == []


def test_plot_section_takes_the_longest_matching_section():
    text = ("==Short Summary==\nКоротко.\n\n"
            "==Long Summary==\nДлинный пересказ серии на много слов.\n\n"
            "==Trivia==\nМелочи.")
    got = api.plot_section(text, api.FandomApi.PLOT_HEADINGS)
    assert got == "Длинный пересказ серии на много слов."


def test_plot_section_stops_at_the_next_heading_of_the_same_level():
    text = "==Plot==\nСюжет.\n===Часть 2===\nПродолжение.\n==Cast==\nАктёры."
    got = api.plot_section(text, api.FandomApi.PLOT_HEADINGS)
    assert "Продолжение." in got and "Актёры" not in got


def test_strip_wikitext_leaves_sentences_and_headings():
    raw = ("{{Infobox|name=Тест|image={{Файл|a.png}}}}\n"
           "==Summary==\n"
           "[[Наруто|Герой]] встречает '''врага'''<ref>ссылка</ref>.\n"
           "[[File:Boom.png|thumb]]\n"
           "* Список")
    out = api.strip_wikitext(raw)
    assert "Infobox" not in out and "ref" not in out and "File:" not in out
    assert "==Summary==" in out
    assert "Герой встречает врага." in out


# ── Сюжет: вопрос от модели ──────────────────────────────────────────────────
class FakeGemini:
    """Заглушка GeminiClient: отдаёт заранее заданный ответ."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def generate_json(self, prompt, schema, temperature=0.0):
        self.prompts.append(prompt)
        return self.answer


def test_plot_question_hides_the_title_from_the_text():
    client = FakeGemini({"ok": True,
                         "question": "В «Death Note» герой находит тетрадь, "
                                     "убивающую любого, чьё имя в неё вписано"})
    text, answers = plot.make_question(
        "Тетрадь смерти", "Пересказ серии " * 30, client,
        names=["Death Note", "Тетрадь смерти"])
    assert "Death Note" not in text and "Тетрадь" not in text
    assert "герой находит" in text
    assert answers == []          # отвечают названием тайтла


def test_plot_detail_mode_returns_its_own_answers():
    client = FakeGemini({"ok": True, "question": "Как зовут синигами?",
                         "answer": "Рюк", "alt": ["Ryuk"]})
    text, answers = plot.make_question("Тетрадь смерти", "Пересказ " * 60,
                                       client, mode="detail")
    assert text == "Как зовут синигами?" and answers == ["Рюк", "Ryuk"]
    # Тайтл в таком вопросе называть можно — его не вычищают.
    assert "Тетрадь смерти" in client.prompts[0]


def test_plot_question_refuses_short_retellings():
    client = FakeGemini({"ok": True, "question": "Что-то"})
    assert plot.make_question("Тайтл", "Две строки.", client) == ("", [])
    assert client.prompts == []          # запрос впустую не тратится


def test_plot_question_honours_model_refusal():
    client = FakeGemini({"ok": False, "question": ""})
    assert plot.make_question("Тайтл", "Пересказ " * 60, client) == ("", [])


class FakeFandom:
    """Вики, у которой одна серия с пересказом и одна пустая заготовка."""

    PAGES = {"Серия 1": "==Summary==\n" + "Герой идёт в поход. " * 20,
             "Серия 2": "==Trivia==\nМелочь."}

    def __init__(self):
        self.asked = []

    def find_wiki(self, names):
        self.asked.append(list(names))
        return "test.fandom.com"

    def episode_pages(self, host):
        return ["Серия 2", "Серия 1"]

    def search(self, host, query, limit=0):
        return []

    def page_text(self, host, page):
        return self.PAGES.get(page, "")

    def plot_section(self, text):
        return api.plot_section(text, api.FandomApi.PLOT_HEADINGS)


def test_pick_plot_skips_pages_without_a_retelling():
    got = plot.pick_plot(FakeFandom(), ["Test"], random.Random(0))
    assert got["page"] == "Серия 1" and got["wiki"] == "test.fandom.com"
    assert "Герой идёт в поход." in got["text"]


def test_plot_question_lands_in_xml_without_a_spoken_answer():
    """У вопроса по сюжету в ответе НЕТ устного текста (просьба пользователя):
    ни адреса вики, ни названия тайтла ведущий не зачитывает."""
    s = PackSettings(pct_songs=0, pack_plot=True, pct_plot=100,
                     gemini_key="k", rounds=1, themes=1, questions=1)
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    cand.plot_question = "Герой находит тетрадь"
    cand.plot_source = "deathnote.fandom.com, Episode 1"
    root = ET.fromstring(build_content_xml([cand], s))
    ns = {"s": animepack.SIQ_NS}
    items = root.findall(".//s:param[@name='question']/s:item", ns)
    assert [i.text for i in items] == [animepack.PLOT_TASK_TEXT,
                                       "Герой находит тетрадь"]
    spoken = [i.text or "" for i in
              root.findall(".//s:param[@name='answer']/s:item", ns)
              if i.get("placement") == "replic"]
    assert spoken == []


def test_plot_detail_answers_replace_the_title_in_xml():
    s = PackSettings(pct_songs=0, pack_plot=True, pct_plot=100,
                     plot_mode="detail", gemini_key="k",
                     rounds=1, themes=1, questions=1)
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    cand.plot_question = "Как зовут синигами?"
    cand.plot_answers = ["Рюк", "Ryuk"]
    root = ET.fromstring(build_content_xml([cand], s))
    ns = {"s": animepack.SIQ_NS}
    assert [a.text for a in root.findall(".//s:right/s:answer", ns)] == ["Рюк",
                                                                        "Ryuk"]
    # Устного текста в ответе у вопросов по сюжету нет вовсе — ни названия
    # тайтла, ни ссылки на вики (просьба пользователя).
    spoken = [i.text or "" for i in
              root.findall(".//s:param[@name='answer']/s:item", ns)
              if i.get("placement") == "replic"]
    assert spoken == []


# ── Доли, квоты и проверки настроек ──────────────────────────────────────────
def test_new_kinds_take_their_share_of_the_pack():
    s = PackSettings(rounds=1, themes=1, questions=100,
                     pct_songs=40, pack_pixel=True, pct_pixel=20,
                     pack_anagram=True, pct_anagram=20,
                     pack_plot=True, pct_plot=20, gemini_key="k")
    shares = s.mix_shares
    assert (shares[PIXEL_KIND], shares[ANAGRAM_KIND], shares[PLOT_KIND]) == \
        (20, 20, 20)
    quotas = s.question_quotas
    assert quotas[PIXEL_KIND] == 20 and quotas[ANAGRAM_KIND] == 20
    assert quotas[PLOT_KIND] == 20
    # Песенные квоты ужались до оставшихся сорока вопросов.
    assert sum(quotas[k] for k in ("opening", "ending", "insert")) == 40


def test_share_needs_its_checkbox():
    """Без галочки доля нового рода вопросов не работает вовсе — как у роликов
    и манги."""
    s = PackSettings(pct_songs=50, pct_anagram=50)
    assert s.mix_shares[ANAGRAM_KIND] == 0
    assert s.mix_shares["songs"] == 100


def test_only_kind_knows_the_new_kinds():
    s = PackSettings(pct_songs=0, pack_anagram=True, pct_anagram=100)
    assert s.only_kind == ANAGRAM_KIND
    assert s.has_songs is False
    # Пак без песен не ругается на песенные настройки.
    assert PackSettings(pct_songs=0, pack_anagram=True, pct_anagram=100,
                        categories={}).validate() == []


def test_plot_share_demands_a_gemini_key():
    s = PackSettings(pct_songs=0, pack_plot=True, pct_plot=100)
    assert any("ключ Gemini" in p for p in s.validate())
    s.gemini_key = "abc"
    assert s.validate() == []


def test_settings_survive_save_and_load():
    s = PackSettings(pack_pixel=True, pct_pixel=15, pixel_seconds=12,
                     pixel_steps=8, pixel_block=96, pixel_fps=12,
                     pack_anagram=True, pct_anagram=15, anagram_lang="romaji",
                     pack_plot=True, pct_plot=10, plot_mode="detail",
                     gemini_key="key", pct_songs=60)
    back = PackSettings.from_dict(s.to_dict())
    assert back.mix_shares == s.mix_shares
    assert (back.pixel_seconds, back.pixel_steps, back.pixel_block,
            back.pixel_fps) == (12, 8, 96, 12)
    assert back.anagram_lang == "romaji" and back.plot_mode == "detail"
    assert back.gemini_key == "key"


def test_a_song_candidate_can_become_an_anagram():
    """В смешанном паке кандидат с песней уходит в недобранную квоту — в том
    числе в анаграммы: карточка тайтла у него уже есть."""
    from collections import Counter
    s = PackSettings(rounds=1, themes=1, questions=10, pct_songs=50,
                     pack_anagram=True, pct_anagram=50)
    gen = animepack.AnimePackGenerator(s, session=object(), amq=object(),
                                       anisong=object(), mal=object(),
                                       shikimori=object())
    cand = SongCandidate(song={"songType": "Opening 1"}, anime=make_anime(),
                         kind="opening")
    quotas = s.question_quotas
    counts, inflight = Counter(), Counter()
    counts["opening"] = quotas["opening"]        # песенные места заняты
    assert gen._pick_kind(cand, counts, inflight, quotas) == ANAGRAM_KIND


def test_silent_kinds_have_no_song_left_on_them():
    """Кандидат пришёл с песней, а стал анаграммой — песня в ответе и в цене
    участвовать больше не должна."""
    cand = SongCandidate(song={"songName": "the WORLD", "songArtist": "Nightmare",
                               "songType": "Opening 1", "songDifficulty": 85.0},
                         anime=make_anime(), kind=ANAGRAM_KIND)
    assert cand.song_name == "" and cand.artist == "" and cand.tag == ""
    assert cand.main_answer == "Тетрадь смерти (2006)"


@pytest.mark.parametrize("kind", [ANAGRAM_KIND, PLOT_KIND])
def test_text_questions_need_no_media(kind):
    cand = SongCandidate(song={}, anime=make_anime(), kind=kind)
    assert cand.is_text and cand.is_silent and not cand.is_picture


def test_pixel_counts_as_a_frame_but_not_as_a_picture_file():
    cand = SongCandidate(song={}, anime=make_anime(), kind=PIXEL_KIND)
    assert cand.is_frame and cand.is_pixel and cand.is_silent
    # Картинка вопроса у него всё же есть — но в паке она лежит роликом.
    assert cand.is_picture


# ── Пак целиком ──────────────────────────────────────────────────────────────
def _pack_generator(settings, animes, tmp_path):
    """Генератор с подменёнными источниками: сети нет, ffmpeg не зовётся."""
    class FakeShiki:
        def animes_by_ids(self, ids):
            ids = {int(i) for i in ids}
            return [a for a in animes if int(a["malId"]) in ids]

        def user_anime_ids(self, nick, statuses, **_kw):
            return [int(a["malId"]) for a in animes]

        def franchise_parts(self, keys):
            return {}

    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        mal=FakeShiki(), shikimori=FakeShiki(),
        frames_history_path=str(tmp_path / "frames.json"))
    gen._get_bytes = lambda url, timeout=None: b"\x00" * 64

    def save_image(data, base, src_ext=".jpg"):
        """Вместо AVIF-кодера — те же байты файлом: имена и ссылки настоящие."""
        name = f"{base}.jpg"
        with open(os.path.join(gen.folder, "Images", name), "wb") as f:
            f.write(data)
        return name

    gen._save_image = save_image
    return gen


def test_anagram_and_pixel_pack_end_to_end(tmp_path, monkeypatch):
    """Пак из анаграмм и пикселей собирается целиком: у анаграммы нет ни одного
    медиафайла, у пикселей вопрос лежит в Video/, и обе ссылки в content.xml
    указывают на то, что реально есть в архиве."""
    import zipfile
    s = PackSettings(rounds=1, themes=1, questions=2, parallel=1,
                     pct_songs=0, pack_anagram=True, pct_anagram=50,
                     pack_pixel=True, pct_pixel=50, random_mode=False,
                     similar_count=1, title="Тест новых вопросов",
                     out_dir=str(tmp_path),
                     users=[animepack.UserList("morr", "shikimori",
                                               ["completed"])])
    # Названия нарочно РАЗНЫЕ: тайтлы с общим корнем имени генератор считает
    # частями одной серии и в один пак не пускает.
    animes = [make_anime(malId=i, id=i, franchise=f"fr{i}", russian=title,
                         english=title, name=title)
              for i, title in ((1, "Тетрадь смерти"), (2, "Стальной алхимик"))]
    gen = _pack_generator(s, animes, tmp_path)

    def fake_pixel(cand):
        """Вместо ffmpeg — файл нужного имени: сам эффект проверен отдельно."""
        cand.frame_url = "https://shiki/1.jpg"
        with open(os.path.join(gen.folder, "Video", cand.video_out), "wb") as f:
            f.write(b"\x00" * 128)
        cand.has_video = True
        return True

    monkeypatch.setattr(gen, "download_pixel", fake_pixel)
    result = gen.run()
    kinds = {c.kind for c in result.songs}
    assert kinds == {ANAGRAM_KIND, PIXEL_KIND}
    anagram = next(c for c in result.songs if c.kind == ANAGRAM_KIND)
    assert anagram.anagram and anagram.anagram == anagram.anagram.upper()

    with zipfile.ZipFile(result.path) as zf:
        names = set(zf.namelist())
        root = ET.fromstring(zf.read("content.xml"))
        ns = {"s": animepack.SIQ_NS}
        refs = root.findall(".//s:item[@isRef='True']", ns)
        assert refs, "в паке должен быть хотя бы ролик-проявление"
        for item in refs:
            folder = {"video": "Video", "audio": "Audio"}.get(
                item.get("type"), "Images")
            assert f"{folder}/{item.text}" in names
        # Анаграмма — чистый текст, без единой ссылки на медиа.
        texts = [i.text for i in root.findall(".//s:item", ns) if not i.get("type")]
        assert anagram.anagram in texts
    assert not any(n.startswith("Audio/") for n in names)


def test_text_questions_download_only_the_poster(tmp_path):
    """У анаграммы и сюжета вопрос — текст: коллаж поверх песни им не нужен, а
    качать его — впустую тратить и время, и бюджет веса пака."""
    s = PackSettings(pct_songs=0, pack_anagram=True, pct_anagram=100,
                     images=True)
    gen = _pack_generator(s, [], tmp_path)
    gen.folder = str(tmp_path)
    os.makedirs(tmp_path / "Images", exist_ok=True)
    cand = SongCandidate(song={}, anime=make_anime(), kind=ANAGRAM_KIND,
                         media_base="Пак(Тетрадь смерти)")
    gen.download_images(cand)
    assert cand.has_poster and not cand.has_collage and not cand.has_frame
    # Скачан ровно один файл — постер для ответа.
    assert len(os.listdir(tmp_path / "Images")) == 1
