# -*- coding: utf-8 -*-
"""Пак носит список спрошенного при себе — иначе франшизы утекают в следующий.

Живой случай: «Моя геройская академия» из пака № 1 приехала в пак № 4, хотя
первый стоял в списке «не повторять». Вопрос там был «деталью сюжета», а у неё
правильный ответ — сама деталь («партия в сёги»), и разбор ответов про тайтл
не узнавал ничего. То же и с вопросом-персонажем: в ответе стоит имя героя.
"""
import zipfile

import animepack as ap
from animepack import PackSettings, SongCandidate
from si_hyx_parts.animepack import pack_manifest

from test_animepack_new_kinds import make_anime


def _hero():
    return make_anime(malId=31964, id=31964, russian="Моя геройская академия",
                      name="Boku no Hero Academia",
                      english="My Hero Academia",
                      franchise="boku_no_hero_academia")


def _detail_question(anime):
    """Вопрос по сюжету с ответом-деталью: тайтла в ответе нет вовсе."""
    cand = SongCandidate(song={}, anime=anime, kind=ap.PLOT_KIND)
    cand.plot_question = "Во что играют герои?"
    cand.plot_answers = ["сёги"]
    return cand


def _pack(path, songs):
    settings = PackSettings(rounds=1, themes=1, questions=len(songs))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", ap.build_content_xml(songs, settings))
        spent = pack_manifest.build(songs)
        if spent:
            archive.writestr(pack_manifest.MANIFEST_NAME, spent)
    return str(path)


def test_the_answer_alone_does_not_reveal_the_title():
    """Ровно та дыра, из-за которой франшиза и повторялась."""
    cand = _detail_question(_hero())
    assert "геройская" not in " ".join(cand.answer_variants()).casefold()


def test_the_manifest_tells_the_franchise_of_a_detail_question(tmp_path):
    old = _pack(tmp_path / "пак1.siq", [_detail_question(_hero())])
    assert not any("геройск" in root for root in ap.siq_answer_roots(old))
    spent = pack_manifest.read(old)
    assert "boku_no_hero_academia" in spent["franchises"]
    assert "моя геройская академия" in spent["roots"]


def test_a_pack_with_a_detail_question_closes_its_franchise(tmp_path):
    hero = _hero()
    old = _pack(tmp_path / "пак1.siq", [_detail_question(hero)])
    settings = PackSettings(exclude_siq=[old])
    gen = ap.AnimePackGenerator(settings,
                                frames_history_path=str(tmp_path / "f.json"))
    gen.load_exclusions()
    assert not gen._accept_anime(hero, 31964, set(), set())
    other = make_anime(malId=9, id=9, russian="Стальной алхимик",
                       name="Fullmetal Alchemist", franchise="fma")
    assert gen._accept_anime(other, 9, set(), set())


def test_an_old_pack_without_a_manifest_is_read_by_media_names(tmp_path):
    """Паки, собранные до манифеста, узнаются по подписям медиафайлов."""
    path = tmp_path / "старый.siq"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", "<package/>")
        archive.writestr(
            f"Images/{ap.MEDIA_NAME_PREFIX}(Моя геройская академия)_poster.avif",
            b"x")
    spent = pack_manifest.read(str(path))
    assert spent["roots"] == {"моя геройская академия"}
    assert spent["franchises"] == set()


def test_a_foreign_pack_is_not_an_error(tmp_path):
    path = tmp_path / "чужой.siq"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", "<package/>")
    assert pack_manifest.read(str(path)) == {"roots": set(),
                                             "franchises": set()}
    assert pack_manifest.read(str(tmp_path / "нет.siq")) == {
        "roots": set(), "franchises": set()}
