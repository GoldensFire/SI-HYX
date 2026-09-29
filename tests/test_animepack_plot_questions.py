# -*- coding: utf-8 -*-
"""Вопросы ПО СЮЖЕТУ: что модель прислала и как это легло в пак.

Отделено от test_animepack_new_kinds: тот файл упёрся в предел размера, а
здешние проверки — про один род вопросов. Сети нет: Gemini подменяется
заглушкой, пересказ подаётся строкой.
"""
import random
import xml.etree.ElementTree as ET

import animepack
import animepack_api as api
import animepack_plot as plot
from animepack import (PLOT_KIND, PackSettings, SongCandidate,
                       build_content_xml)

from tests.test_animepack_new_kinds import make_anime


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
    client = FakeGemini({"ok": True, "question": "Что нашёл герой в «Тетради смерти»?",
                         "answer": "Рюк", "alt": ["Ryuk"]})
    text, answers = plot.make_question("Тетрадь смерти", "Пересказ " * 60,
                                       client, mode="detail")
    assert text == "Что нашёл герой в «Тетради смерти»?"
    assert answers == ["Рюк", "Ryuk"]
    # Тайтл в таком вопросе называть можно — его не вычищают.
    assert "Тетрадь смерти" in client.prompts[0]


def test_plot_detail_question_always_names_the_title():
    """Модель нет-нет да и забудет назвать произведение — дописываем сами.

    Без названия вопрос выходит про неизвестно что («что сделает Бог, если на
    небеса попадёт достаточно людей?») — просьба пользователя."""
    client = FakeGemini({"ok": True, "question": "Как зовут синигами?",
                         "answer": "Рюк"})
    text, _answers = plot.make_question("Тетрадь смерти", "Пересказ " * 60,
                                        client, mode="detail")
    assert text == "«Тетрадь смерти»: как зовут синигами?"


def test_plot_detail_question_names_the_season_from_an_alternative_title():
    """Русское имя может не отличать продолжение, хотя ромадзи содержит S2."""
    client = FakeGemini({
        "ok": True,
        "question": ("Куда прибывают Хадзимэ и Каори в аниме "
                     "«Арифурэта: Сильнейший ремесленник в мире»?"),
        "answer": "Грюэн",
    })
    title = plot.season_title(
        "Арифурэта: Сильнейший ремесленник в мире",
        "Arifureta Shokugyou de Sekai Saikyou 2nd Season")
    text, _answers = plot.make_question(title, "Пересказ " * 60, client,
                                        mode="detail")
    assert "«Арифурэта: Сильнейший ремесленник в мире — 2-й сезон»" in text


def test_plot_question_refuses_short_retellings():
    client = FakeGemini({"ok": True, "question": "Что-то"})
    assert plot.make_question("Тайтл", "Две строки.", client) == ("", [])
    assert client.prompts == []          # запрос впустую не тратится


def test_plot_question_honours_model_refusal():
    client = FakeGemini({"ok": False, "question": ""})
    assert plot.make_question("Тайтл", "Пересказ " * 60, client) == ("", [])


def test_gemini_embeds_episode_and_writes_one_answer_sentence():
    client = FakeGemini({
        "ok": True,
        "question": "Что герой обнаруживает в 7-й серии?",
        "explanation": "Герой обнаруживает тайник, который меняет ход расследования.",
    })
    question, answers, explanation = plot.make_question_with_explanation(
        "Тетрадь смерти", "Пересказ " * 60, client, episode="7")
    assert question == "Что герой обнаруживает в 7-й серии?"
    assert answers == []
    assert explanation.endswith(".") and "серии 7" not in explanation
    assert "Номер серии: 7" in client.prompts[0]


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


class LongArticleFandom(FakeFandom):
    """Вики без страниц серий: остаётся одна статья тайтла с длинным «Сюжетом».

    Ровно этот случай и повторялся у пользователя: серий у «Шарлотты» вики не
    отдаёт, хвост поиска был один и тот же, и три пака подряд приходил один и
    тот же вопрос про длительность способности."""

    ARTICLE = "==Plot==\n" + "\n\n".join(
        f"Эпизод {n}. " + "Событие сюжета. " * 12 for n in range(12))

    def episode_pages(self, host):
        return []

    def search(self, host, query, limit=0):
        return ["Charlotte", "Yuu Otosaka", "Список серий"]

    def page_text(self, host, page):
        return self.ARTICLE


def test_a_long_retelling_is_cut_at_a_random_place():
    """Иначе модель раз за разом цепляется за первый же яркий факт."""
    starts = {plot.pick_plot(LongArticleFandom(), ["Charlotte"],
                             random.Random(seed))["text"][:24]
              for seed in range(12)}
    assert len(starts) > 3


def test_the_random_window_stays_a_whole_retelling():
    """Кусок остаётся связным и не короче того, из чего вообще выйдет вопрос."""
    for seed in range(12):
        text = plot.pick_plot(LongArticleFandom(), ["Charlotte"],
                              random.Random(seed))["text"]
        assert len(text) >= plot.MIN_PLOT_CHARS
        assert len(text) <= plot.PLOT_WINDOW + 200
        assert text.startswith("Эпизод")          # начали с целого абзаца


def test_a_short_retelling_is_given_whole():
    got = plot.pick_plot(FakeFandom(), ["Test"], random.Random(0))
    assert got["text"] == plot.plot_window(got["text"], random.Random(1))


def test_the_search_tail_is_shuffled_too():
    """У вики без страниц серий хвост решает всё — значит, и он не по порядку."""
    pages = {plot.pick_plot(LongArticleFandom(), ["Charlotte"],
                            random.Random(seed))["page"]
             for seed in range(12)}
    assert len(pages) > 1


def test_plot_question_lands_in_xml_with_rating_as_spoken_answer():
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
    assert spoken == ["Рейтинг MAL — 『8.60⭐』 · "
                      "Индекс популярности — 1277 (Ур. 10)"]
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
    # Ссылка на вики не читается вслух; рейтинг заполняет пустую реплику.
    spoken = [i.text or "" for i in
              root.findall(".//s:param[@name='answer']/s:item", ns)
              if i.get("placement") == "replic"]
    assert spoken == ["Рейтинг MAL — 『8.60⭐』 · "
                      "Индекс популярности — 1277 (Ур. 10)"]
    # И подписи «Назвать аниме по сюжету» тут быть не должно: тайтл в таком
    # вопросе назван прямо, угадывают саму деталь (просьба пользователя).
    items = [i.text for i in
             root.findall(".//s:param[@name='question']/s:item", ns)]
    assert items == ["Как зовут синигами?"]


def test_plot_explanation_is_first_and_names_the_short_answer():
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    cand.plot_answers = ["Тайник"]
    cand.plot_explanation = "В тайнике лежала улика, изменившая расследование."
    cand.source_link = "https://example.fandom.com/wiki/Episode_7"
    answers = cand.answer_variants()
    assert answers[0].startswith("Тайник — ")
    assert cand.plot_explanation in answers[0]
    assert answers[1:] == ["Тайник", cand.source_link]


def test_answer_does_not_say_the_plot_episode_out_loud():
    """Номер серии живёт в вопросе и не повторяется в устном ответе."""
    s = PackSettings(pct_songs=0, pack_plot=True, pct_plot=100,
                     gemini_key="k", rounds=1, themes=1, questions=1)
    cand = SongCandidate(song={}, anime=make_anime(), kind=PLOT_KIND)
    cand.plot_question = "Герой находит тетрадь"
    cand.plot_episode = "1"
    cand.plot_source = "deathnote.fandom.com, Episode 1"
    root = ET.fromstring(build_content_xml([cand], s))
    ns = {"s": animepack.SIQ_NS}
    spoken = [i for i in root.findall(".//s:param[@name='answer']/s:item", ns)
              if i.get("placement") == "replic"]
    assert [i.text for i in spoken] == [
        "Рейтинг MAL — 『8.60⭐』 · "
        "Индекс популярности — 1277 (Ур. 10)"]
    # Одновременно с ответом, а не до него.
    assert spoken[0].get("waitForFinish") == "False"
    # Адрес вики ведущему по-прежнему не зачитывается.
    assert "fandom.com" not in (spoken[0].text or "")


def test_plot_question_costs_half_again_as_much_as_a_frame():
    """Сюжет стоит в полтора раза дороже кадра по тому же тайтлу."""
    s = PackSettings(pct_songs=0, pack_plot=True, pct_plot=100,
                     gemini_key="k", rounds=1, themes=1, questions=2)
    anime = make_anime()
    frame = SongCandidate(song={}, anime=anime, kind=animepack.FRAME_KIND)
    story = SongCandidate(song={}, anime=anime, kind=PLOT_KIND)
    story.plot_question = "Что случилось в финале?"
    animepack.assign_prices([frame, story], s)
    assert story.price == round(frame.price * animepack.PLOT_PRICE_MULT)


class RecordingFandom(api.FandomApi):
    """FandomApi с подменёнными сетевыми шагами: что спросили — то и видно."""

    def __init__(self, live=(), pages=()):
        super().__init__(session=object())
        self.live = set(live)
        self.pages = list(pages)
        self.searched = []

    def wiki_at(self, slug):
        return f"{slug}.fandom.com" if slug in self.live else ""

    def search(self, host, query, limit=0):
        self.searched.append((host, query))
        return list(self.pages)


def test_a_wiki_found_by_one_word_must_prove_itself():
    """Адрес из одного слова названия проверяется поиском по вики.

    На этом и ломалось: у «Mushoku Tensei: Jobless Reincarnation» самое длинное
    слово — «reincarnation», и reincarnation.fandom.com оказалась вики про
    чужую игру. Вопрос уезжал в её сюжет (просьба пользователя)."""
    name = "Mushoku Tensei: Jobless Reincarnation"
    stranger = RecordingFandom(live={"reincarnation"},
                               pages=["A Demon's Day Out", "Gameplay"])
    assert stranger.find_wiki([name]) == ""
    assert stranger.searched == [("reincarnation.fandom.com", name)]
    # Своя вики ту же проверку проходит: название стоит в заголовке статьи.
    own = RecordingFandom(live={"reincarnation"},
                          pages=["Mushoku Tensei: Jobless Reincarnation"])
    assert own.find_wiki([name]) == "reincarnation.fandom.com"


def test_a_wiki_named_by_the_whole_title_needs_no_search():
    """Полное название в адресе говорит само за себя — лишнего запроса нет."""
    fandom = RecordingFandom(live={"attackontitan"})
    assert fandom.find_wiki(["Attack on Titan"]) == "attackontitan.fandom.com"
    assert fandom.searched == []


def test_grisaia_uses_the_franchise_wiki():
    """Grisaia no Rakuen живёт не на полном slug, а на grisaia.fandom.com."""
    fandom = RecordingFandom(
        live={"grisaia"}, pages=["The Eden of Grisaia", "Episode list"])
    assert fandom.find_wiki(["Grisaia no Rakuen"]) == "grisaia.fandom.com"
    assert fandom.searched == [
        ("grisaia.fandom.com", "Grisaia no Rakuen")]
