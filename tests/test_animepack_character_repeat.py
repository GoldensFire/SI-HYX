"""A character remains the same question across titles and image encodings."""
import json
import zipfile
from types import SimpleNamespace

import pytest

import animepack as ap
from si_hyx_parts.animepack import early_repeat, pack_manifest
from si_hyx_parts.animepack.exact_repeat import candidate_keys, known_keys, read_exact_keys
from test_animepack_early_repeat import _generator


def _character(title="First title", number=17, name="Hero", **kwargs):
    return ap.SongCandidate({}, {"id": 20, "malId": 20, "name": title},
                            kind=ap.CHAR_KIND,
                            character={"id": number, "name": name,
                                       "russian": "Герой"}, **kwargs)


@pytest.mark.parametrize("manifest", [False, True])
@pytest.mark.parametrize("entrance", [False, True])
def test_old_character_is_blocked_after_title_and_media_change(
        tmp_path, monkeypatch, manifest, entrance):
    old = _character(has_frame=True, frame_name="old.png")
    if entrance:
        old.entrance_video = "old.mp4"
    settings = ap.PackSettings(rounds=1, themes=1, questions=1)
    path = tmp_path / "old.siq"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", ap.build_content_xml([old], settings))
        archive.writestr("Images/old.png", b"old encoding")
        if manifest:
            archive.writestr(pack_manifest.MANIFEST_NAME, pack_manifest.build([old]))
    gen = _generator(tmp_path, monkeypatch)
    gen._exact_keys = read_exact_keys(str(path))
    fresh = _character(title="Sequel", frame_name="new.avif", has_frame=True)
    assert not early_repeat.reserve(gen, fresh)
    assert fresh._exact_duplicate
    if manifest:
        assert ("character-id", "17") in gen._exact_keys


def test_legacy_answer_without_caption_ignores_its_season(tmp_path):
    path = tmp_path / "legacy.siq"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", """<package><question><right>
            <answer>Поздний сезон (2020) — 『Hero』</answer>
            <answer>Герой</answer></right></question></package>""")
    assert known_keys(_character()) & read_exact_keys(str(path))


def test_song_with_the_same_quoted_name_is_not_a_character(tmp_path):
    path = tmp_path / "song.siq"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", """<package><question><right>
            <answer>Series OP1 (2020) — 『Hero』</answer>
            </right></question></package>""")
    assert not known_keys(_character()) & read_exact_keys(str(path))


def test_manifest_keeps_id_and_aliases_and_selection_chooses_another_hero(
        tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch)
    old = _character()
    data = json.loads(pack_manifest.build([old]))
    assert data["characters"] == [{"id": 17, "names": ["Hero", "Герой"]}]
    gen._exact_keys = known_keys(old)
    gen.shikimori = SimpleNamespace(characters_by_anime_ids=lambda *a, **kw: {
        20: [{"id": 17, "name": "Hero", "main": True},
             {"id": 18, "name": "Other hero", "main": True}]})
    gen.db_cache = SimpleNamespace(memo=lambda *a: None,
                                   remember_memo=lambda *a: None)
    candidate = _character(title="Sequel")
    candidate.character = None
    gen._pick_character(candidate)
    assert candidate.character["id"] == 18


def test_debut_is_a_movie_even_if_later_role_is_main(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch)
    gen.s.char_roles = "main"
    gen.shikimori = SimpleNamespace(character_titles=lambda *a: {
        "animes": [{"id": 1, "kind": "movie", "aired_on": "1999-01-01",
                    "roles": ["Supporting"]},
                   {"id": 20, "kind": "tv", "aired_on": "2005-01-01",
                    "roles": ["Main"]}]})
    first = {"id": 1, "malId": 999, "name": "Debut movie"}
    gen._animes_by_ids = lambda ids: [first]
    candidate = _character()
    gen._use_first_title(candidate)
    assert candidate.anime is first
    assert candidate.main_answer == "Debut movie — 『Hero』"
    assert not candidate.rejected


def test_unverifiable_debut_is_rejected_instead_of_using_a_sequel(
        tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch)
    gen.shikimori = SimpleNamespace(character_titles=lambda *a: {})
    candidate = _character(title="Random sequel")
    gen._use_first_title(candidate)
    assert candidate.rejected


def test_foreign_pack_without_character_metadata_keeps_media_fallback(tmp_path):
    path = tmp_path / "foreign.siq"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", """<package><question><params>
            <param name="question"><item type="image" isRef="True">hero.png</item>
            </param></params><right><answer>Unknown alias</answer></right>
            </question></package>""")
        archive.writestr("Images/hero.png", b"same portrait")
    candidate = _character(frame_name="hero.png", has_frame=True)
    (tmp_path / "Images").mkdir()
    (tmp_path / "Images" / "hero.png").write_bytes(b"same portrait")
    assert candidate_keys(candidate, str(tmp_path)) & read_exact_keys(str(path))


def test_characters_sharing_a_name_are_distinguished_by_id(tmp_path, monkeypatch):
    old = _character(number=17, name="Sakura")
    path = tmp_path / "old.siq"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", ap.build_content_xml(
            [old], ap.PackSettings(rounds=1, themes=1, questions=1)))
        archive.writestr(pack_manifest.MANIFEST_NAME, pack_manifest.build([old]))
    gen = _generator(tmp_path, monkeypatch)
    gen._exact_keys = read_exact_keys(str(path))
    first, second = _character(number=18, name="Sakura"), _character(number=19, name="Sakura")
    assert early_repeat.reserve(gen, first)
    assert early_repeat.reserve(gen, second)
    assert early_repeat.accept(gen, first)
    assert early_repeat.reserve(gen, second)
    assert not early_repeat.reserve(gen, _character(number=17, name="Renamed hero"))
