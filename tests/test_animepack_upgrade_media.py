"""Апгрейд пака: постеры, сжатие картинок, аудио и видео, неиспользуемые файлы."""
import os
import threading
import xml.etree.ElementTree as ET
import zipfile

import pytest

from animepack_upgrade import (
    KNOWN_LABELS,
    PackUpgrader,
    SPECIAL_LABELS,
    UpgradeSettings,
    audio_filter_chain,
    copy_zip_entry,
    entry_basename,
    example_lines,
    is_media_entry,
    known_labels_in,
    loudnorm_filter,
    media_jobs,
    nearest_bitrate,
    nearest_height,
    normalize_profile,
    parse_content,
    parse_probe_codec,
    parse_probe_kbps,
    referenced_names,
    remove_poster,
    read_pack_info,
    retarget_refs,
    tag_fn,
    unused_entries,
)
from filenames import escape_uri_string
from animepack_upgrade_test_helpers import (
    BIG_AUDIO,
    BIG_VIDEO,
    BLEACH,
    FakeApi,
    HEAVY,
    KNOWN_REPEATS,
    NARUTO,
    ONLY_REPEATS,
    ONLY_UNUSED,
    POSTERED,
    _answers,
    _aud_settings,
    _fake_av1,
    _fake_avif,
    _fake_opus,
    _fake_poster,
    _img_settings,
    _out_root,
    _pack,
    _poster_settings,
    _q4,
    _q5,
    _q5_audio,
    _q5_image,
    _q5_items,
    _q5_video,
    _run,
    _shot,
    _siq,
    _themes,
    _vid_settings,
)


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
