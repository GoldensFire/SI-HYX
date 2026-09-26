# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_fake_poster. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def _fake_poster(monkeypatch, size: int = 1234):
    """Постер без сети и без ffmpeg: скачивание и кодирование подменены."""
    monkeypatch.setattr(_api.PackUpgrader, "_fetch", lambda self, url: b"raw-bytes")

    def fake(self, raw, out, limit_kb=None):
        with open(out, "wb") as f:
            f.write(b"P" * size)
        return True

    monkeypatch.setattr(_api.PackUpgrader, "_to_avif", fake)

_fake_poster.__module__ = _api.__name__
_api._fake_poster = _fake_poster

def _poster_settings(**kw):
    base = dict(strip_specials=False, compress_images=False)
    base.update(kw)
    return _api.UpgradeSettings(**base)

_poster_settings.__module__ = _api.__name__
_api._poster_settings = _poster_settings

def test_poster_goes_into_the_answer(tmp_path, monkeypatch):
    _api._fake_poster(monkeypatch)
    content = _api._pack(_api._q5(100, answer="Блич"))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    with _api.zipfile.ZipFile(result.path) as zf:
        made = [n for n in zf.namelist() if n.endswith(".avif")]
        assert made == ["Images/shiki_269_poster.avif"]
        assert len(zf.read(made[0])) == 1234
        root, ns = _api.parse_content(zf.read("content.xml"))
    tag = _api.tag_fn(ns)
    answer = [p for p in root.iter(tag("param")) if p.get("name") == "answer"][0]
    item = answer.find(tag("item"))
    assert item.get("type") == "image" and item.get("isRef") == "True"
    assert item.text == "shiki_269_poster.avif"
    assert item.get("duration") is None       # без таймера: висит до ведущего
    assert len(result.posters) == 1 and result.added_bytes == 1234

test_poster_goes_into_the_answer.__module__ = _api.__name__
_api.test_poster_goes_into_the_answer = test_poster_goes_into_the_answer

def test_one_poster_file_per_title(tmp_path, monkeypatch):
    """Тайтл в паке встречается по нескольку раз — файл на него один."""
    _api._fake_poster(monkeypatch)
    content = _api._pack(_api._q5(100, answer="Блич") + _api._q5(200, answer="Bleach"))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    with _api.zipfile.ZipFile(result.path) as zf:
        assert len([n for n in zf.namelist() if n.endswith(".avif")]) == 1
    assert len(result.posters) == 2 and result.added_bytes == 1234

test_one_poster_file_per_title.__module__ = _api.__name__
_api.test_one_poster_file_per_title = test_one_poster_file_per_title

def test_poster_is_not_added_over_existing_picture(tmp_path, monkeypatch):
    """Своя картинка в ответе уже есть — вторая рядом это слайд-шоу."""
    _api._fake_poster(monkeypatch)
    right = "<right><answer>Блич</answer></right>"
    params = ('<param name="answer" type="content">'
              '<item type="image" isRef="True">своя.jpg</item></param>')
    content = _api._pack(_api._q5(100, params=params, right=right))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    assert result.posters == []
    with _api.zipfile.ZipFile(result.path) as zf:
        assert not [n for n in zf.namelist() if n.endswith(".avif")]

test_poster_is_not_added_over_existing_picture.__module__ = _api.__name__
_api.test_poster_is_not_added_over_existing_picture = test_poster_is_not_added_over_existing_picture

@_api.pytest.mark.parametrize("item", [
    '<item type="video" isRef="True">свой.mp4</item>',
    '<item type="audio" isRef="True" placement="background">свой.mp3</item>',
])
def test_poster_is_not_added_over_existing_media(tmp_path, monkeypatch, item):
    """Ролик или дорожка в ответе — тоже готовое зрелище, постер его перебьёт."""
    _api._fake_poster(monkeypatch)
    right = "<right><answer>Блич</answer></right>"
    params = f'<param name="answer" type="content">{item}</param>'
    content = _api._pack(_api._q5(100, params=params, right=right))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    assert result.posters == []
    with _api.zipfile.ZipFile(result.path) as zf:
        assert not [n for n in zf.namelist() if n.endswith(".avif")]

test_poster_is_not_added_over_existing_media.__module__ = _api.__name__
_api.test_poster_is_not_added_over_existing_media = test_poster_is_not_added_over_existing_media

def test_poster_still_goes_next_to_answer_text(tmp_path, monkeypatch):
    """Текст в ответе (реплика ведущего) медиа не считается — постер ставим."""
    _api._fake_poster(monkeypatch)
    right = "<right><answer>Блич</answer></right>"
    params = ('<param name="answer" type="content">'
              '<item placement="replic">Отличная вещь</item></param>')
    content = _api._pack(_api._q5(100, params=params, right=right))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    assert len(result.posters) == 1

test_poster_still_goes_next_to_answer_text.__module__ = _api.__name__
_api.test_poster_still_goes_next_to_answer_text = test_poster_still_goes_next_to_answer_text

def test_poster_is_not_added_over_v4_media_after_marker(tmp_path, monkeypatch):
    """В v4 ответ — хвост сценария за маркером; ролик там значит то же самое."""
    _api._fake_poster(monkeypatch)
    content = _api._pack('<question price="100"><scenario><atom>Текст</atom>'
                    '<atom type="marker"/><atom type="video">@свой.mp4</atom>'
                    "</scenario><right><answer>Блич</answer></right></question>")
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    assert result.posters == []

test_poster_is_not_added_over_v4_media_after_marker.__module__ = _api.__name__
_api.test_poster_is_not_added_over_v4_media_after_marker = test_poster_is_not_added_over_v4_media_after_marker

def test_poster_can_be_switched_off(tmp_path, monkeypatch):
    _api._fake_poster(monkeypatch)
    content = _api._pack(_api._q5(100, answer="Блич"))
    result = _api._run(tmp_path, content, _api._poster_settings(add_poster=False),
                  api=_api.FakeApi([_api.POSTERED]))
    assert result.posters == [] and result.added_bytes == 0

test_poster_can_be_switched_off.__module__ = _api.__name__
_api.test_poster_can_be_switched_off = test_poster_can_be_switched_off

def test_poster_needs_exact_match(tmp_path, monkeypatch):
    _api._fake_poster(monkeypatch)
    content = _api._pack(_api._q5(100, answer="bleachh"))
    result = _api._run(tmp_path, content, _api._poster_settings(strict_match=False),
                  api=_api.FakeApi([_api.POSTERED]))
    assert result.posters == []

test_poster_needs_exact_match.__module__ = _api.__name__
_api.test_poster_needs_exact_match = test_poster_needs_exact_match

def test_title_without_poster_is_skipped(tmp_path, monkeypatch):
    _api._fake_poster(monkeypatch)
    content = _api._pack(_api._q5(100, answer="Блич"))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.BLEACH]))
    assert result.posters == [] and result.exact_titles == 1

test_title_without_poster_is_skipped.__module__ = _api.__name__
_api.test_title_without_poster_is_skipped = test_title_without_poster_is_skipped

def test_poster_in_v4_goes_after_the_marker(tmp_path, monkeypatch):
    """В v4 ответ живёт в сценарии за <atom type="marker"/>."""
    _api._fake_poster(monkeypatch)
    content = _api._pack(_api._q4(100, answer="Блич"))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    root, ns = _api._out_root(result)
    tag = _api.tag_fn(ns)
    atoms = root.find(f'.//{tag("scenario")}').findall(tag("atom"))
    assert [a.get("type") for a in atoms] == [None, "marker", "image"]
    assert atoms[-1].text == "@shiki_269_poster.avif"

test_poster_in_v4_goes_after_the_marker.__module__ = _api.__name__
_api.test_poster_in_v4_goes_after_the_marker = test_poster_in_v4_goes_after_the_marker

def test_poster_name_does_not_overwrite_existing_file(tmp_path, monkeypatch):
    _api._fake_poster(monkeypatch)
    content = _api._pack(_api._q5(100, answer="Блич"))
    src = _api._siq(tmp_path, content,
               media={"Images/shiki_269_poster.avif": "чужой файл".encode()})
    result = _api.PackUpgrader(src, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED])).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Images/shiki_269_poster.avif") == "чужой файл".encode()
        assert "Images/shiki_269_poster (2).avif" in zf.namelist()

test_poster_name_does_not_overwrite_existing_file.__module__ = _api.__name__
_api.test_poster_name_does_not_overwrite_existing_file = test_poster_name_does_not_overwrite_existing_file

def test_poster_temp_files_are_cleaned_up(tmp_path, monkeypatch):
    _api._fake_poster(monkeypatch)
    content = _api._pack(_api._q5(100, answer="Блич"))
    up = _api.PackUpgrader(_api._siq(tmp_path, content), _api._poster_settings(),
                      api=_api.FakeApi([_api.POSTERED]))
    up.run()
    assert not any(_api.os.path.exists(p) for p in up._extra.values())

test_poster_temp_files_are_cleaned_up.__module__ = _api.__name__
_api.test_poster_temp_files_are_cleaned_up = test_poster_temp_files_are_cleaned_up

# ── Карточка выбранного пака ─────────────────────────────────────────────────
def test_read_pack_info_returns_name_author_and_themes(tmp_path):
    content = ('<?xml version="1.0" encoding="utf-8"?>'
               '<package name="Солянка № 2" version="5" date="17.07.2025">'
               "<info><authors><author>GoldensFire</author></authors></info>"
               '<rounds><round name="Раунд 1"><themes>'
               '<theme name="Опенинги"><questions>'
               + _api._q5(100) + _api._q5(200, qtype="secret") +
               "</questions></theme>"
               '<theme name="Эндинги"><questions>' + _api._q5(300) +
               "</questions></theme></themes></round>"
               '<round name="Финал"><themes><theme name="Аниме"><questions>'
               + _api._q5(0) + "</questions></theme></themes></round>"
               "</rounds></package>")
    info = _api.read_pack_info(_api._siq(tmp_path, content))
    assert info.name == "Солянка № 2" and info.author == "GoldensFire"
    assert info.date == "17.07.2025" and info.version == "5"
    assert info.questions == 4 and info.specials == 1
    assert info.themes == ["Опенинги", "Эндинги", "Аниме"]
    assert [r for r, _t in info.rounds] == ["Раунд 1", "Финал"]

test_read_pack_info_returns_name_author_and_themes.__module__ = _api.__name__
_api.test_read_pack_info_returns_name_author_and_themes = test_read_pack_info_returns_name_author_and_themes

def test_read_pack_info_survives_a_pack_without_info(tmp_path):
    info = _api.read_pack_info(_api._siq(tmp_path, _api._pack(_api._q5(100))))
    assert info.name == "Пак" and info.authors == [] and info.author == ""
    assert info.themes == ["Тема А"]

test_read_pack_info_survives_a_pack_without_info.__module__ = _api.__name__
_api.test_read_pack_info_survives_a_pack_without_info = test_read_pack_info_survives_a_pack_without_info

# ── Названия типов вопросов — как в самой игре ───────────────────────────────
def test_special_labels_match_siquester_wording():
    """Подписи взяты у SIQuester (QuestionTypesNamesNew + Resources.ru-RU),
    а не выдуманы: «кот в мешке» — прозвище, в игре тип зовётся иначе."""
    assert _api.SPECIAL_LABELS["secret"] == "с секретом"
    assert _api.SPECIAL_LABELS["secretnoquestion"] == "с секретом без вопроса"
    assert _api.SPECIAL_LABELS["norisk"] == "для себя"
    assert _api.SPECIAL_LABELS["stakeall"] == "для всех со ставкой"

test_special_labels_match_siquester_wording.__module__ = _api.__name__
_api.test_special_labels_match_siquester_wording = test_special_labels_match_siquester_wording

# ── Отчёт про новые функции ──────────────────────────────────────────────────
def test_examples_show_recased_and_posters(tmp_path, monkeypatch):
    _api._fake_poster(monkeypatch)
    content = _api._pack(_api._q5(100, answer="блич") + _api._q5(200, answer="наруто"))
    result = _api._run(tmp_path, content, _api._poster_settings(),
                  api=_api.FakeApi([_api.POSTERED, _api.NARUTO]))
    lines = _api.example_lines(result, limit=3)
    head = next(l for l in lines if l.startswith("Названий переписано"))
    assert head == "Названий переписано как на Shikimori: 2."
    head = next(l for l in lines if l.startswith("Постеров поставлено"))
    assert head.startswith("Постеров поставлено в ответ: 1 (пак тяжелее на ")

test_examples_show_recased_and_posters.__module__ = _api.__name__
_api.test_examples_show_recased_and_posters = test_examples_show_recased_and_posters
