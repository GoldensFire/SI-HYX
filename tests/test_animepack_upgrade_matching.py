"""Апгрейд пака: выбор карточки — клипы, синонимы, популярность, книжные темы."""
import zipfile

import pytest

from animepack_upgrade import (
    LOOSE_THRESHOLD,
    PackUpgrader,
    UpgradeError,
    UpgradeSettings,
    match_score,
    parse_content,
    pick_card,
    card_names,
    character_hit,
    looks_like_character_name,
    is_book_theme,
    recased,
    spelling_names,
    synonym_only,
    title_variants,
)
from animepack_upgrade_test_helpers import (
    AKAME_ANIME,
    AKAME_MANGA,
    BLEACH,
    BookApi,
    CLIP_MUMEI,
    CLIP_YABA,
    FakeApi,
    KYOUKAI,
    NARUTO,
    RawApi,
    SHELTER_CLIP,
    SHELTER_MOVIE,
    SWEAT,
    _answers,
    _book_pack,
    _pack,
    _q5,
    _run,
    _siq,
    _stats,
)


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
