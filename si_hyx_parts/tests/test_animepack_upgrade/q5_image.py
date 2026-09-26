# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_q5_image. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def _q5_image(price: int, name: str) -> str:
    """Вопрос v5 с картинкой в содержимом."""
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content">'
            f'<item type="image" isRef="True">{name}</item></param>'
            "</params><right><answer>Ответ</answer></right></question>")

_q5_image.__module__ = _api.__name__
_api._q5_image = _q5_image

def test_heavy_image_becomes_avif_and_ref_follows(tmp_path, monkeypatch):
    _api._fake_avif(monkeypatch)
    content = _api._pack(_api._q5_image(100, "poster.jpg"))
    src = _api._siq(tmp_path, content, media={"Images/poster.jpg": _api.HEAVY})
    result = _api.PackUpgrader(src, _api._img_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        assert "Images/poster.avif" in names and "Images/poster.jpg" not in names
        root, ns = _api.parse_content(zf.read("content.xml"))
    item = root.find(f'.//{_api.tag_fn(ns)("item")}')
    assert item.text == "poster.avif"           # ссылка переведена на новый файл
    assert len(result.images) == 1
    assert result.images[0].theme_name == "poster.jpg"
    assert result.saved_bytes == len(_api.HEAVY) - 400

test_heavy_image_becomes_avif_and_ref_follows.__module__ = _api.__name__
_api.test_heavy_image_becomes_avif_and_ref_follows = test_heavy_image_becomes_avif_and_ref_follows

def test_light_images_and_other_media_are_left_alone(tmp_path, monkeypatch):
    _api._fake_avif(monkeypatch)
    media = {"Images/small.jpg": b"J" * 100, "Audio/a.opus": _api.HEAVY,
             "Images/anim.gif": _api.HEAVY, "Images/done.avif": _api.HEAVY}
    content = _api._pack(_api._q5(100))
    src = _api.PackUpgrader(_api._siq(tmp_path, content, media=media),
                       _api._img_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(src.path) as zf:
        assert zf.read("Images/small.jpg") == b"J" * 100
        assert zf.read("Audio/a.opus") == _api.HEAVY
        assert zf.read("Images/anim.gif") == _api.HEAVY   # анимация не режется
        assert zf.read("Images/done.avif") == _api.HEAVY   # уже AVIF
    assert src.images == [] and src.heavy_images == 0

test_light_images_and_other_media_are_left_alone.__module__ = _api.__name__
_api.test_light_images_and_other_media_are_left_alone = test_light_images_and_other_media_are_left_alone

def test_image_that_got_heavier_is_kept_as_is(tmp_path, monkeypatch):
    _api._fake_avif(monkeypatch, size=len(_api.HEAVY) + 1)
    content = _api._pack(_api._q5_image(100, "poster.png"))
    src = _api._siq(tmp_path, content, media={"Images/poster.png": _api.HEAVY})
    result = _api.PackUpgrader(src, _api._img_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Images/poster.png") == _api.HEAVY
        root, ns = _api.parse_content(zf.read("content.xml"))
    assert result.images == [] and result.heavy_images == 1
    assert root.find(f'.//{_api.tag_fn(ns)("item")}').text == "poster.png"

test_image_that_got_heavier_is_kept_as_is.__module__ = _api.__name__
_api.test_image_that_got_heavier_is_kept_as_is = test_image_that_got_heavier_is_kept_as_is

def test_percent_encoded_v4_reference_is_retargeted(tmp_path, monkeypatch):
    """Имя в архиве бывает percent-кодированным, а у v4 перед ним стоит «@»."""
    _api._fake_avif(monkeypatch)
    content = _api._pack('<question price="100">'
                    '<scenario><atom type="image">@%D0%9A%D0%B0%D0%B4%D1%80.jpg'
                    "</atom></scenario>"
                    "<right><answer>Ответ</answer></right></question>")
    src = _api._siq(tmp_path, content,
               media={"Images/%D0%9A%D0%B0%D0%B4%D1%80.jpg": _api.HEAVY})
    result = _api.PackUpgrader(src, _api._img_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert "Images/%D0%9A%D0%B0%D0%B4%D1%80.avif" in zf.namelist()
        root, ns = _api.parse_content(zf.read("content.xml"))
    atom = root.find(f'.//{_api.tag_fn(ns)("atom")}')
    assert atom.text == "@%D0%9A%D0%B0%D0%B4%D1%80.avif"

test_percent_encoded_v4_reference_is_retargeted.__module__ = _api.__name__
_api.test_percent_encoded_v4_reference_is_retargeted = test_percent_encoded_v4_reference_is_retargeted

def test_brackets_in_name_survive_reencoding(tmp_path, monkeypatch):
    """Скобки, запятые и «!» в имени записи трогать НЕЛЬЗЯ.

    Игра ищет медиа по имени из content.xml, прогоняя его через
    Uri.EscapeUriString (SIDocument.TryGetMedia): пробел там становится %20, а
    скобки остаются собой. Пока имя новой записи кодировали quote(safe=""),
    «Kiss of Death (Darling).opus» превращался в …%28Darling%29.opus, и вопрос
    падал с «File … was not found in the game package!» — при том что без
    апгрейда тот же пак играл нормально."""
    _api._fake_avif(monkeypatch)
    raw = "Kiss%20of%20Death%20(Darling)!,%20[TV].jpg"
    decoded = "Kiss of Death (Darling)!, [TV].jpg"
    content = _api._pack(_api._q5_image(100, decoded))
    src = _api._siq(tmp_path, content, media={f"Images/{raw}": _api.HEAVY})
    result = _api.PackUpgrader(src, _api._img_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        root, ns = _api.parse_content(zf.read("content.xml"))
    assert "Images/Kiss%20of%20Death%20(Darling)!,%20[TV].avif" in names
    ref = root.find(f'.//{_api.tag_fn(ns)("item")}').text
    assert ref == "Kiss of Death (Darling)!, [TV].avif"
    # То же самое, но глазами игры: как она имя закодирует, так и должна найти.
    assert f"Images/{_api.escape_uri_string(ref)}" in names

test_brackets_in_name_survive_reencoding.__module__ = _api.__name__
_api.test_brackets_in_name_survive_reencoding = test_brackets_in_name_survive_reencoding

def test_brackets_survive_even_when_the_name_is_taken(tmp_path, monkeypatch):
    """Занятое имя разводится суффиксом « (2)» — и оно тоже кодируется
    по-игровому (пробел в %20, скобки как есть)."""
    _api._fake_avif(monkeypatch)
    content = _api._pack(_api._q5_image(100, "кадр (1).webp"))
    src = _api._siq(tmp_path, content,
               media={"Images/%D0%BA%D0%B0%D0%B4%D1%80%20(1).webp": _api.HEAVY,
                      "Images/%D0%BA%D0%B0%D0%B4%D1%80%20(1).avif": b"OLD"})
    result = _api.PackUpgrader(src, _api._img_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        root, ns = _api.parse_content(zf.read("content.xml"))
    ref = root.find(f'.//{_api.tag_fn(ns)("item")}').text
    assert ref == "кадр (1) (2).avif"
    assert f"Images/{_api.escape_uri_string(ref)}" in names

test_brackets_survive_even_when_the_name_is_taken.__module__ = _api.__name__
_api.test_brackets_survive_even_when_the_name_is_taken = test_brackets_survive_even_when_the_name_is_taken

def test_escape_uri_string_matches_dotnet():
    """Набор символов взят у .NET Uri.EscapeUriString (его зовёт SIGame):
    незаписанные -._~ плюс зарезервированные ;/?:@&=+$,#[]!'()* остаются как
    есть, всё прочее — в %XX по UTF-8."""
    assert _api.escape_uri_string("a b") == "a%20b"
    assert _api.escape_uri_string("!#$&'()*+,/:;=?@[]-._~") == "!#$&'()*+,/:;=?@[]-._~"
    assert _api.escape_uri_string("«Vital» — jin • ok") == (
        "%C2%ABVital%C2%BB%20%E2%80%94%20jin%20%E2%80%A2%20ok")
    assert _api.escape_uri_string("Наруто.mp3") == (
        "%D0%9D%D0%B0%D1%80%D1%83%D1%82%D0%BE.mp3")

test_escape_uri_string_matches_dotnet.__module__ = _api.__name__
_api.test_escape_uri_string_matches_dotnet = test_escape_uri_string_matches_dotnet

def test_taken_avif_name_does_not_clobber_the_neighbour(tmp_path, monkeypatch):
    """Рядом с «кадр.webp» в паках лежит «кадр.avif» (вопрос и ответ одного
    тайтла): подменять его нельзя — берётся соседнее свободное имя."""
    _api._fake_avif(monkeypatch)
    content = _api._pack(_api._q5_image(100, "кадр.webp"))
    src = _api._siq(tmp_path, content, media={"Images/кадр.webp": _api.HEAVY,
                                         "Images/кадр.avif": b"OLD"})
    result = _api.PackUpgrader(src, _api._img_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Images/кадр.avif") == b"OLD"   # чужой файл цел
        assert "Images/кадр (2).avif" in zf.namelist()
        root, ns = _api.parse_content(zf.read("content.xml"))
    assert root.find(f'.//{_api.tag_fn(ns)("item")}').text == "кадр (2).avif"

test_taken_avif_name_does_not_clobber_the_neighbour.__module__ = _api.__name__
_api.test_taken_avif_name_does_not_clobber_the_neighbour = test_taken_avif_name_does_not_clobber_the_neighbour

def test_retarget_refs_touches_only_media_elements():
    root = _api.ET.fromstring(
        '<package><item type="image" isRef="True">a.jpg</item>'
        "<atom>@a.jpg</atom><answer>a.jpg</answer></package>")
    assert _api.retarget_refs(root, {"a.jpg": "a.avif"}) == 2
    assert [el.text for el in root] == ["a.avif", "@a.avif", "a.jpg"]

test_retarget_refs_touches_only_media_elements.__module__ = _api.__name__
_api.test_retarget_refs_touches_only_media_elements = test_retarget_refs_touches_only_media_elements

def test_images_untouched_when_function_is_off(tmp_path, monkeypatch):
    _api._fake_avif(monkeypatch)
    content = _api._pack(_api._q5_image(100, "poster.jpg"))
    src = _api._siq(tmp_path, content, media={"Images/poster.jpg": _api.HEAVY})
    result = _api.PackUpgrader(src, _api.UpgradeSettings(add_titles=False,
                                               compress_images=False),
                          api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Images/poster.jpg") == _api.HEAVY
    assert result.images == [] and result.heavy_images == 0

test_images_untouched_when_function_is_off.__module__ = _api.__name__
_api.test_images_untouched_when_function_is_off = test_images_untouched_when_function_is_off

def test_source_pack_survives_image_compression(tmp_path, monkeypatch):
    _api._fake_avif(monkeypatch)
    content = _api._pack(_api._q5_image(100, "poster.jpg"))
    src = _api._siq(tmp_path, content, media={"Images/poster.jpg": _api.HEAVY})
    before = open(src, "rb").read()
    _api.PackUpgrader(src, _api._img_settings(), api=_api.FakeApi()).run()
    assert open(src, "rb").read() == before

test_source_pack_survives_image_compression.__module__ = _api.__name__
_api.test_source_pack_survives_image_compression = test_source_pack_survives_image_compression

# ── Отчёт «три примера с каждой функции» ─────────────────────────────────────
def test_examples_show_three_of_each(tmp_path):
    content = _api._pack("".join(
        _api._q5(100 * i, answer=a, qtype="secret")
        for i, a in enumerate(["Наруто", "Блич", "Наруто (2002)", "Блич!"], 1)))
    result = _api._run(tmp_path, content)
    lines = _api.example_lines(result, limit=3)
    assert lines[0] == "Спецвопросов расколдовано: 4."
    assert sum(1 for l in lines if l.startswith("  • «Раунд 1»")) == 6  # 3 + 3
    assert any(l.startswith("Ответов дополнено названиями: 4.") for l in lines)

test_examples_show_three_of_each.__module__ = _api.__name__
_api.test_examples_show_three_of_each = test_examples_show_three_of_each

def test_examples_say_so_when_nothing_changed(tmp_path):
    content = _api._pack(_api._q5(100, answer="Столица Франции"))
    result = _api._run(tmp_path, content)
    lines = _api.example_lines(result)
    assert any("спецвопросов в паке не нашлось" in l for l in lines)
    assert any("названий аниме в ответах не опознано" in l for l in lines)
    assert any("картинок тяжелее порога в паке нет" in l for l in lines)

test_examples_say_so_when_nothing_changed.__module__ = _api.__name__
_api.test_examples_say_so_when_nothing_changed = test_examples_say_so_when_nothing_changed

def test_examples_show_compressed_images(tmp_path, monkeypatch):
    _api._fake_avif(monkeypatch)
    content = _api._pack("".join(_api._q5_image(100 * i, f"p{i}.jpg")
                            for i in range(1, 5)))
    media = {f"Images/p{i}.jpg": _api.HEAVY for i in range(1, 5)}
    src = _api._siq(tmp_path, content, media=media)
    result = _api.PackUpgrader(src, _api._img_settings(), api=_api.FakeApi()).run()
    lines = _api.example_lines(result, limit=3)
    head = next(l for l in lines if l.startswith("Картинок сжато:"))
    assert head.startswith("Картинок сжато: 4 (пак легче на ")
    assert sum(1 for l in lines if l.startswith("  • p")) == 3

test_examples_show_compressed_images.__module__ = _api.__name__
_api.test_examples_show_compressed_images = test_examples_show_compressed_images

def test_changes_are_reported_in_pack_order(tmp_path):
    content = _api._pack(_api._q5(100, answer="Наруто") + _api._q5(200, qtype="stake"))
    result = _api._run(tmp_path, content)
    assert [c.kind for c in result.changes] == ["title", "special"]
    assert [c.price for c in result.changes] == [100, 200]

test_changes_are_reported_in_pack_order.__module__ = _api.__name__
_api.test_changes_are_reported_in_pack_order = test_changes_are_reported_in_pack_order

# ── Написание названия как на Shikimori ──────────────────────────────────────
def _answers(result):
    root, ns = _api._out_root(result)
    tag = _api.tag_fn(ns)
    return [a.text for a in root.findall(f'.//{tag("right")}/{tag("answer")}')]

_answers.__module__ = _api.__name__
_api._answers = _answers

def test_case_is_fixed_to_shikimori_spelling(tmp_path):
    """«наруто» в паке — «Наруто» на Shikimori (просьба пользователя)."""
    content = _api._pack(_api._q5(100, answer="наруто"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False))
    assert _api._answers(result)[0] == "Наруто"
    assert [(c.before, c.after) for c in result.recased] == [("наруто", "Наруто")]

test_case_is_fixed_to_shikimori_spelling.__module__ = _api.__name__
_api.test_case_is_fixed_to_shikimori_spelling = test_case_is_fixed_to_shikimori_spelling

def test_case_fix_handles_shouting_and_keeps_song_after_dash(tmp_path):
    content = _api._pack(_api._q5(100, answer="НАРУТО - Nee"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False))
    assert _api._answers(result)[0] == "Наруто - Nee"

test_case_fix_handles_shouting_and_keeps_song_after_dash.__module__ = _api.__name__
_api.test_case_fix_handles_shouting_and_keeps_song_after_dash = test_case_fix_handles_shouting_and_keeps_song_after_dash

def test_case_fix_changes_only_letters_case(tmp_path):
    """Написание — это регистр. Превращать «Наруто» в «Наруто. Книга первая»
    нельзя: это уже другой ответ."""
    content = _api._pack(_api._q5(100, answer="Наруто"))
    result = _api._run(tmp_path, content, _api.UpgradeSettings(strip_specials=False))
    assert result.recased == [] and _api._answers(result)[0] == "Наруто"

test_case_fix_changes_only_letters_case.__module__ = _api.__name__
_api.test_case_fix_changes_only_letters_case = test_case_fix_changes_only_letters_case

def test_case_fix_can_be_switched_off(tmp_path):
    content = _api._pack(_api._q5(100, answer="наруто"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, fix_case=False))
    assert result.recased == [] and _api._answers(result)[0] == "наруто"

test_case_fix_can_be_switched_off.__module__ = _api.__name__
_api.test_case_fix_can_be_switched_off = test_case_fix_can_be_switched_off

def test_case_fix_needs_exact_match(tmp_path):
    """Нестрогое совпадение карточку находит, но переписывать по ней ответ
    нельзя: это может быть вообще другой тайтл."""
    content = _api._pack(_api._q5(100, answer="bleachh"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, strict_match=False))
    assert result.titles and result.recased == [] and result.exact_titles == 0

test_case_fix_needs_exact_match.__module__ = _api.__name__
_api.test_case_fix_needs_exact_match = test_case_fix_needs_exact_match
