# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_famous_clip_beats_an_unknown_namesake. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_famous_clip_beats_an_unknown_namesake():
    """Обложка чужого фильма в ответе хуже, чем обложка того самого клипа."""
    assert _api.pick_card("Shelter", [_api.SHELTER_CLIP, _api.SHELTER_MOVIE],
                     strict=True) is _api.SHELTER_CLIP

test_famous_clip_beats_an_unknown_namesake.__module__ = _api.__name__
_api.test_famous_clip_beats_an_unknown_namesake = test_famous_clip_beats_an_unknown_namesake

def test_clip_without_a_namesake_is_still_not_an_answer():
    """Правило «клип — не тайтл» в силе: отбирать ответ клипу не у кого."""
    assert _api.pick_card("Shelter", [_api.SHELTER_CLIP], strict=True) is None

test_clip_without_a_namesake_is_still_not_an_answer.__module__ = _api.__name__
_api.test_clip_without_a_namesake_is_still_not_an_answer = test_clip_without_a_namesake_is_still_not_an_answer

def test_clip_takes_the_answer_only_with_a_huge_edge():
    """Клип чуть известнее — по-прежнему не ответ: перевес нужен кратный."""
    known = dict(_api.SHELTER_MOVIE, popularity=100000.0)
    assert _api.pick_card("Shelter", [_api.SHELTER_CLIP, known], strict=True) is known

test_clip_takes_the_answer_only_with_a_huge_edge.__module__ = _api.__name__
_api.test_clip_takes_the_answer_only_with_a_huge_edge = test_clip_takes_the_answer_only_with_a_huge_edge

def test_clip_matched_by_a_synonym_is_ignored_as_before():
    """«Teto Kasane» — синоним клипа «Yababaina»: имя героя ответа не отдаёт."""
    clip = {"id": 33, "malId": 33, "name": "Yababaina", "russian": None,
            "english": None, "licenseNameRu": "",
            "synonyms": ["Teto Kasane"], "kind": "music",
            "popularity": 900000.0}
    other = dict(_api.SHELTER_MOVIE, name="Teto Kasane", popularity=10.0)
    assert _api.pick_card("Teto Kasane", [clip, other], strict=True) is other

test_clip_matched_by_a_synonym_is_ignored_as_before.__module__ = _api.__name__
_api.test_clip_matched_by_a_synonym_is_ignored_as_before = test_clip_matched_by_a_synonym_is_ignored_as_before

def test_match_score_is_one_for_any_of_the_names():
    assert _api.match_score("Naruto", _api.NARUTO) == 1.0
    assert _api.match_score("Наруто. Книга первая", _api.NARUTO) == 1.0
    assert _api.match_score("совсем другое", _api.NARUTO) < _api.LOOSE_THRESHOLD

test_match_score_is_one_for_any_of_the_names.__module__ = _api.__name__
_api.test_match_score_is_one_for_any_of_the_names = test_match_score_is_one_for_any_of_the_names

def test_title_variants_keep_generator_order():
    assert _api.title_variants(_api.NARUTO)[:3] == [
        "Naruto", "Наруто. Книга первая", "Наруто ТВ-1"]

test_title_variants_keep_generator_order.__module__ = _api.__name__
_api.test_title_variants_keep_generator_order = test_title_variants_keep_generator_order

# ── Файл на выходе ───────────────────────────────────────────────────────────
def test_source_pack_is_never_modified(tmp_path):
    content = _api._pack(_api._q5(100, answer="Наруто", qtype="secret"))
    src = _api._siq(tmp_path, content)
    before = open(src, "rb").read()
    up = _api.PackUpgrader(src, _api.UpgradeSettings(), api=_api.FakeApi())
    result = up.run()
    assert result.path != src
    assert open(src, "rb").read() == before

test_source_pack_is_never_modified.__module__ = _api.__name__
_api.test_source_pack_is_never_modified = test_source_pack_is_never_modified

def test_media_entries_are_copied_as_is(tmp_path):
    media = {"Audio/a.opus": b"opus-bytes", "Images/p.avif": b"avif-bytes"}
    content = _api._pack(_api._q5(100, answer="Наруто"))
    src = _api._siq(tmp_path, content, media=media)
    result = _api.PackUpgrader(src, _api.UpgradeSettings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/a.opus") == b"opus-bytes"
        assert zf.read("Images/p.avif") == b"avif-bytes"
        # Медиа лежит несжатым, как и в исходнике: пережимать opus/avif незачем.
        assert zf.getinfo("Images/p.avif").compress_type == _api.zipfile.ZIP_STORED

test_media_entries_are_copied_as_is.__module__ = _api.__name__
_api.test_media_entries_are_copied_as_is = test_media_entries_are_copied_as_is

def test_namespace_survives_the_rewrite(tmp_path):
    """Пак с пространством имён (v5 из SIQuester) должен остаться с ним же: с
    префиксами ns0: SIGame файл не откроет."""
    ns = "https://github.com/VladimirKhil/SI/blob/master/assets/siq_5.xsd"
    content = _api._pack(_api._q5(100, answer="Наруто", qtype="secret"), ns=ns)
    result = _api._run(tmp_path, content)
    with _api.zipfile.ZipFile(result.path) as zf:
        raw = zf.read("content.xml").decode("utf-8")
    assert "ns0:" not in raw and f'xmlns="{ns}"' in raw
    root, out_ns = _api.parse_content(raw.encode("utf-8"))
    assert out_ns == ns

test_namespace_survives_the_rewrite.__module__ = _api.__name__
_api.test_namespace_survives_the_rewrite = test_namespace_survives_the_rewrite

def test_out_dir_setting_is_honoured(tmp_path):
    dest = tmp_path / "готовые"
    content = _api._pack(_api._q5(100, answer="Наруто"))
    result = _api._run(tmp_path, content,
                  _api.UpgradeSettings(strip_specials=False, out_dir=str(dest)))
    assert result.path.startswith(str(dest))
    assert result.path.endswith(" (апгрейд).siq")

test_out_dir_setting_is_honoured.__module__ = _api.__name__
_api.test_out_dir_setting_is_honoured = test_out_dir_setting_is_honoured

def test_second_run_does_not_overwrite_the_first(tmp_path):
    content = _api._pack(_api._q5(100, answer="Наруто"))
    src = _api._siq(tmp_path, content)
    first = _api.PackUpgrader(src, _api.UpgradeSettings(), api=_api.FakeApi()).run().path
    second = _api.PackUpgrader(src, _api.UpgradeSettings(), api=_api.FakeApi()).run().path
    assert first != second

test_second_run_does_not_overwrite_the_first.__module__ = _api.__name__
_api.test_second_run_does_not_overwrite_the_first = test_second_run_does_not_overwrite_the_first

def test_capitalized_content_xml_is_found(tmp_path):
    path = tmp_path / "c.siq"
    with _api.zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Content.xml", _api._pack(_api._q5(100, qtype="stake")))
    result = _api.PackUpgrader(str(path), _api.UpgradeSettings(add_titles=False),
                          api=_api.FakeApi()).run()
    assert len(result.specials) == 1
    with _api.zipfile.ZipFile(result.path) as zf:
        assert "Content.xml" in zf.namelist()

test_capitalized_content_xml_is_found.__module__ = _api.__name__
_api.test_capitalized_content_xml_is_found = test_capitalized_content_xml_is_found

# ── Отказы и остановка ───────────────────────────────────────────────────────
def test_broken_archive_is_reported(tmp_path):
    bad = tmp_path / "bad.siq"
    bad.write_bytes(b"not a zip")
    with _api.pytest.raises(_api.UpgradeError):
        _api.PackUpgrader(str(bad), _api.UpgradeSettings(), api=_api.FakeApi()).run()

test_broken_archive_is_reported.__module__ = _api.__name__
_api.test_broken_archive_is_reported = test_broken_archive_is_reported

def test_archive_without_content_xml_is_reported(tmp_path):
    path = tmp_path / "empty.siq"
    with _api.zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Audio/a.mp3", b"snd")
    with _api.pytest.raises(_api.UpgradeError):
        _api.PackUpgrader(str(path), _api.UpgradeSettings(), api=_api.FakeApi()).run()

test_archive_without_content_xml_is_reported.__module__ = _api.__name__
_api.test_archive_without_content_xml_is_reported = test_archive_without_content_xml_is_reported

def test_pack_without_questions_is_reported(tmp_path):
    with _api.pytest.raises(_api.UpgradeError):
        _api._run(tmp_path, _api._pack(""))

test_pack_without_questions_is_reported.__module__ = _api.__name__
_api.test_pack_without_questions_is_reported = test_pack_without_questions_is_reported

def test_all_functions_off_is_rejected():
    problems = _api.UpgradeSettings(strip_specials=False, add_titles=False,
                               compress_images=False,
                               strip_repeated_text=False,
                               drop_empty_questions=False,
                               compress_audio=False, compress_video=False,
                               merge_text_audio=False,
                               drop_unused=False).validate()
    assert problems and "выключены" in problems[0]

test_all_functions_off_is_rejected.__module__ = _api.__name__
_api.test_all_functions_off_is_rejected = test_all_functions_off_is_rejected

def test_image_limit_above_threshold_is_rejected():
    """Ужимать до 2 МБ картинки, которые берутся от 1 МБ, — это ничего."""
    s = _api.UpgradeSettings(image_min_mb=1.0, image_limit_kb=2048)
    assert any("Сжимать не во что" in p for p in s.validate())

test_image_limit_above_threshold_is_rejected.__module__ = _api.__name__
_api.test_image_limit_above_threshold_is_rejected = test_image_limit_above_threshold_is_rejected

def test_entity_declarations_are_refused(tmp_path):
    """content.xml скачан из интернета: объявленные сущности (XXE / «лавина
    сущностей») разбирать нельзя."""
    evil = ('<?xml version="1.0"?><!DOCTYPE package ['
            '<!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]>'
            '<package name="&xxe;"><rounds/></package>')
    with _api.pytest.raises(_api.UpgradeError):
        _api.parse_content(evil.encode("utf-8"))

test_entity_declarations_are_refused.__module__ = _api.__name__
_api.test_entity_declarations_are_refused = test_entity_declarations_are_refused

def test_stop_writes_nothing(tmp_path):
    content = _api._pack("".join(_api._q5(p, qtype="stake") for p in (100, 200, 300)))
    up = _api.PackUpgrader(_api._siq(tmp_path, content),
                      _api.UpgradeSettings(add_titles=False), api=_api.FakeApi(),
                      should_stop=lambda: True)
    result = up.run()
    assert result.cancelled and not result.path
    assert list(tmp_path.glob("*апгрейд*")) == []

test_stop_writes_nothing.__module__ = _api.__name__
_api.test_stop_writes_nothing = test_stop_writes_nothing

# ── Функция 3: сжатие тяжёлых картинок ───────────────────────────────────────
def _fake_avif(monkeypatch, size: int = 400):
    """Подменяет кодирование: ffmpeg в тестах не зовём, важно поведение вокруг."""
    def fake(self, raw, out, limit_kb=None):
        with open(out, "wb") as f:
            f.write(b"A" * size)
        return True

    monkeypatch.setattr(_api.PackUpgrader, "_to_avif", fake)

_fake_avif.__module__ = _api.__name__
_api._fake_avif = _fake_avif

def _img_settings(**kw):
    # Порог — самый низкий, какой принимает форма (0,1 МБ); «тяжёлая» картинка
    # в тестах чуть больше него, а кодирование подменено (_fake_avif).
    # drop_unused=False: в этих паках рядом с правленой картинкой нарочно лежат
    # файлы, на которые ссылок нет, — уборка мусора вынесла бы их, а проверяем
    # тут не её (её тесты ниже, свои).
    base = dict(strip_specials=False, add_titles=False, compress_images=True,
                image_min_mb=0.1, image_limit_kb=50, drop_unused=False)
    base.update(kw)
    return _api.UpgradeSettings(**base)

_img_settings.__module__ = _api.__name__
_api._img_settings = _img_settings
