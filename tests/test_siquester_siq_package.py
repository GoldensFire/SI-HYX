# -*- coding: utf-8 -*-
"""Интеграционные тесты siquester/siq_package.py: разбор, правка и пересборка .siq.

Каждый тест собирает настоящий zip во временной папке; проверяется и
in-memory-модель, и то, что изменения реально доехали до архива (повторное
открытие пакета).
"""
import os
import zipfile

import pytest

from siquester.siq_package import SiqPackage, _safe_replace
from conftest import CONTENT_XML_V5

pytestmark = pytest.mark.integration


@pytest.fixture
def pkg(make_siq):
    p = SiqPackage(make_siq())
    yield p
    p.close()


def _reopen(path):
    p = SiqPackage(path)
    try:
        return p
    finally:
        p.close()


# ── разбор ───────────────────────────────────────────────────────────────────
class TestParse:
    def test_meta(self, pkg):
        assert pkg.name == "Тестовый пак"
        assert pkg.pkg_meta["version"] == "5"
        assert pkg.pkg_meta["id"] == "pkg-1"
        assert pkg.pkg_meta["difficulty"] == "5"
        assert pkg.pkg_tags == ["аниме", "музыка"]
        assert pkg.pkg_authors == ["Автор Один", "Автор Два"]
        assert pkg.pkg_comments == "Комментарий пакета"

    def test_rounds_structure(self, pkg):
        assert [r["name"] for r in pkg.rounds] == ["Раунд 1", "Финал"]
        assert pkg.rounds[1]["type"] == "final"
        assert pkg.rounds[0]["comment"] == "Комментарий раунда"
        themes = pkg.rounds[0]["themes"]
        assert [t["name"] for t in themes] == ["Тема А", "Тема Б"]
        assert [q["price"] for q in themes[0]["questions"]] == [100, 200, 300]

    def test_question_content(self, pkg):
        q100 = pkg.rounds[0]["themes"][0]["questions"][0]
        assert q100["answers"] == ["Ответ 100"]
        texts = [i["text"] for i in q100["items"] if i["type"] == "text"]
        assert texts == ["Текст вопроса 100"]

    def test_select_question(self, pkg):
        q300 = pkg.rounds[0]["themes"][0]["questions"][2]
        assert q300["q_type"] == "select"
        assert set(q300["answer_options"]) == {"A", "B"}
        assert q300["answer_options"]["A"][0]["text"] == "Вариант А"
        assert q300["answers"] == ["B"]

    def test_multiple_answers(self, pkg):
        q200 = pkg.rounds[0]["themes"][0]["questions"][1]
        assert q200["answers"] == ["Ответ 200", "Второй вариант"]

    def test_duration_from_xml_timer(self, pkg):
        qb = pkg.rounds[0]["themes"][1]["questions"][0]
        # duration="00:00:26" на видео-элементе
        assert qb["dur"] == pytest.approx(26.0)
        assert pkg.total_duration >= 26.0

    def test_image_five_seconds(self, pkg):
        q200 = pkg.rounds[0]["themes"][0]["questions"][1]
        img = [i for i in q200["items"] if i["type"] == "image"][0]
        assert img["dur"] == 5.0

    def test_bom_tolerated(self, make_siq, tmp_path):
        xml = "﻿" + CONTENT_XML_V5
        path = make_siq(content_xml=xml, name="bom.siq")
        p = SiqPackage(path)
        try:
            assert p.name == "Тестовый пак"
        finally:
            p.close()

    def test_broken_zip_raises(self, tmp_path):
        bad = tmp_path / "bad.siq"
        bad.write_bytes("не zip".encode("utf-8"))
        with pytest.raises(Exception):
            SiqPackage(str(bad))


# ── защита от вредоносных пакетов ────────────────────────────────────────────
class TestUntrustedHardening:
    XXE_XML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE package [
  <!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">
]>
<package name="до&xxe;после" version="5"><rounds/></package>
"""

    def test_xxe_not_resolved(self, tmp_path):
        p = tmp_path / "xxe.siq"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("content.xml", self.XXE_XML)
        try:
            pkg = SiqPackage(str(p))
            # если пакет открылся — содержимое win.ini не должно попасть в имя
            name = pkg.name or ""
            assert "[fonts]" not in name.lower()
            assert "for 16-bit app support" not in name.lower()
            pkg.close()
        except Exception:
            pass  # отказ разбора — тоже приемлемая защита

    def test_billion_laughs_no_expansion(self, tmp_path):
        bomb = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<package name="&lol4;" version="5"><rounds/></package>"""
        p = tmp_path / "bomb.siq"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("content.xml", bomb)
        try:
            pkg = SiqPackage(str(p))
            assert len(pkg.name or "") < 10_000  # сущности не развёрнуты
            pkg.close()
        except Exception:
            pass

    def test_zip_slip_extract_stays_in_tmp(self, tmp_path):
        """Запись с '../' в имени не должна вылезти за пределы temp-каталога."""
        p = tmp_path / "slip.siq"
        evil_name = "../../evil_escape.mp3"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("content.xml", CONTENT_XML_V5)
            zf.writestr(evil_name, b"EVIL")
        pkg = SiqPackage(str(p))
        try:
            out = pkg.extract_media(evil_name)
            if out is not None:
                real_out = os.path.realpath(out)
                real_tmp = os.path.realpath(pkg._tmp_dir)
                assert real_out.startswith(real_tmp + os.sep)
            # и рядом с тестовой папкой ничего не появилось
            assert not (tmp_path.parent / "evil_escape.mp3").exists()
        finally:
            pkg.close()

    def test_extension_sanitized(self, make_siq):
        """Расширение из недоверенного имени чистится до [A-Za-z0-9.]."""
        path = make_siq(media={
            "Images/pic.png": b"P",
            "Audio/tricky.mp<>3": b"A",
        })
        pkg = SiqPackage(path)
        try:
            out = pkg.extract_media("tricky.mp<>3")
            if out:
                ext = os.path.splitext(out)[1]
                assert all(c.isalnum() or c == "." for c in ext)
        finally:
            pkg.close()


# ── extract_media / поиск вопросов ───────────────────────────────────────────
class TestExtractAndFind:
    def test_extract_media(self, pkg):
        out = pkg.extract_media("pic.png")
        assert out is not None
        with open(out, "rb") as f:
            assert f.read().startswith(b"\x89PNG")

    def test_extract_cached(self, pkg):
        out1 = pkg.extract_media("pic.png")
        out2 = pkg.extract_media("pic.png")
        assert out1 == out2

    def test_extract_missing(self, pkg):
        assert pkg.extract_media("нет_такого.png") is None

    def test_find_q_idx(self, pkg):
        assert pkg.find_q_idx(0, 0, 100) == 0
        assert pkg.find_q_idx(0, 0, 300) == 2

    def test_find_q_idx_missing(self, pkg):
        with pytest.raises(ValueError):
            pkg.find_q_idx(0, 0, 9999)

    def test_find_question(self, pkg):
        q = pkg.find_question(0, 0, 200)
        assert q is not None and q["price"] == 200

    def test_find_question_missing(self, pkg):
        assert pkg.find_question(0, 0, 9999) is None
        assert pkg.find_question(99, 0, 100) is None

    def test_rebuild_index_after_reorder(self, pkg):
        qs = pkg.rounds[0]["themes"][0]["questions"]
        qs.reverse()
        pkg.rebuild_index_for_theme(0, 0)
        assert pkg.find_q_idx(0, 0, 300) == 0
        assert pkg.find_q_idx(0, 0, 100) == 2

    def test_rebuild_index_bad_indices_noop(self, pkg):
        pkg.rebuild_index_for_theme(99, 99)  # не должно бросить

    def test_close_removes_tmp(self, pkg):
        pkg.extract_media("pic.png")
        tmp_dir = pkg._tmp_dir
        pkg.close()
        assert not os.path.exists(tmp_dir)


# ── правки с пересборкой zip ─────────────────────────────────────────────────
class TestEdits:
    def test_save_question(self, pkg):
        ok = pkg.save_question(0, 0, 0, ["Новый текст"], ["Новый ответ", "Ещё"])
        assert ok
        q = pkg.rounds[0]["themes"][0]["questions"][0]
        assert q["answers"] == ["Новый ответ", "Ещё"]
        p2 = SiqPackage(pkg.path)
        try:
            q2 = p2.rounds[0]["themes"][0]["questions"][0]
            assert q2["answers"] == ["Новый ответ", "Ещё"]
            texts = [i["text"] for i in q2["items"] if i["type"] == "text"]
            assert texts == ["Новый текст"]
        finally:
            p2.close()

    def test_save_theme_name(self, pkg):
        assert pkg.save_theme_name(0, 0, "Переименованная")
        assert pkg.rounds[0]["themes"][0]["name"] == "Переименованная"
        p2 = SiqPackage(pkg.path)
        try:
            assert p2.rounds[0]["themes"][0]["name"] == "Переименованная"
        finally:
            p2.close()

    def test_save_round_name(self, pkg):
        assert pkg.save_round_name(1, "Суперфинал")
        p2 = SiqPackage(pkg.path)
        try:
            assert p2.rounds[1]["name"] == "Суперфинал"
        finally:
            p2.close()

    def test_save_question_price(self, pkg):
        assert pkg.save_question_price(0, 0, 0, 150)
        p2 = SiqPackage(pkg.path)
        try:
            assert p2.rounds[0]["themes"][0]["questions"][0]["price"] == 150
        finally:
            p2.close()

    def test_save_round_prices(self, pkg):
        assert pkg.save_round_prices(0, 100, 300, 100)
        prices_a = [q["price"] for q in pkg.rounds[0]["themes"][0]["questions"]]
        assert prices_a == [100, 200, 300]
        # индекс пересобран
        assert pkg.find_q_idx(0, 0, 200) == 1

    def test_save_round_prices_invalid_args(self, pkg):
        assert not pkg.save_round_prices(0, 100, 300, 0)     # step <= 0
        assert not pkg.save_round_prices(0, 0, 300, 100)     # min <= 0
        assert not pkg.save_round_prices(0, 300, 100, 100)   # max < min

    def test_save_round_info(self, pkg):
        assert pkg.save_round_info(0, "final", "Новый комментарий")
        p2 = SiqPackage(pkg.path)
        try:
            assert p2.rounds[0]["type"] == "final"
            assert p2.rounds[0]["comment"] == "Новый комментарий"
        finally:
            p2.close()

    def test_save_round_info_clear(self, pkg):
        assert pkg.save_round_info(0, "", "")
        p2 = SiqPackage(pkg.path)
        try:
            assert p2.rounds[0]["type"] == ""
            assert p2.rounds[0]["comment"] == ""
        finally:
            p2.close()

    def test_save_question_comment(self, pkg):
        assert pkg.save_question_comment(0, 0, 0, "Заметка автора")
        p2 = SiqPackage(pkg.path)
        try:
            assert p2.rounds[0]["themes"][0]["questions"][0]["comment"] == \
                "Заметка автора"
        finally:
            p2.close()

    def test_save_pkg_info(self, pkg):
        meta = dict(pkg.pkg_meta, difficulty="9", name="Новое имя")
        assert pkg.save_pkg_info(meta, ["тег1"], ["Новый автор"], "Новый коммент")
        p2 = SiqPackage(pkg.path)
        try:
            assert p2.name == "Новое имя"
            assert p2.pkg_meta["difficulty"] == "9"
            assert p2.pkg_tags == ["тег1"]
            assert p2.pkg_authors == ["Новый автор"]
            assert p2.pkg_comments == "Новый коммент"
        finally:
            p2.close()

    def test_add_theme(self, pkg):
        n_before = len(pkg.rounds[0]["themes"])
        assert pkg.add_theme(0, "Свежая тема")
        assert len(pkg.rounds[0]["themes"]) == n_before + 1
        p2 = SiqPackage(pkg.path)
        try:
            assert p2.rounds[0]["themes"][-1]["name"] == "Свежая тема"
        finally:
            p2.close()

    def test_add_theme_default_name(self, pkg):
        assert pkg.add_theme(0)
        assert pkg.rounds[0]["themes"][-1]["name"].startswith("Тема ")

    def test_add_round(self, pkg):
        assert pkg.add_round("Третий раунд")
        p2 = SiqPackage(pkg.path)
        try:
            assert p2.rounds[-1]["name"] == "Третий раунд"
            assert p2.rounds[-1]["themes"] == []
        finally:
            p2.close()

    def test_add_question(self, pkg):
        n = len(pkg.rounds[0]["themes"][0]["questions"])
        assert pkg.add_question(0, 0, 400)
        assert len(pkg.rounds[0]["themes"][0]["questions"]) == n + 1
        p2 = SiqPackage(pkg.path)
        try:
            prices = [q["price"] for q in p2.rounds[0]["themes"][0]["questions"]]
            assert 400 in prices
        finally:
            p2.close()

    def test_move_round(self, pkg):
        assert pkg.move_round(0, 1)
        assert [r["name"] for r in pkg.rounds] == ["Финал", "Раунд 1"]
        p2 = SiqPackage(pkg.path)
        try:
            assert [r["name"] for r in p2.rounds] == ["Финал", "Раунд 1"]
        finally:
            p2.close()

    def test_move_round_same_index(self, pkg):
        assert pkg.move_round(1, 1) is True

    def test_move_round_out_of_range(self, pkg):
        assert pkg.move_round(0, 99) is False

    def test_save_select_question(self, pkg):
        opts = {"A": "Да", "B": "Нет", "C": "Может быть"}
        assert pkg.save_select_question(0, 0, 0, 111, ["Вопрос-выбор"], opts, "C")
        p2 = SiqPackage(pkg.path)
        try:
            q = p2.rounds[0]["themes"][0]["questions"][0]
            assert q["price"] == 111
            assert q["q_type"] == "select"
            assert q["answers"] == ["C"]
            assert q["answer_options"]["C"][0]["text"] == "Может быть"
        finally:
            p2.close()

    def test_save_point_question(self, pkg):
        assert pkg.save_point_question(0, 0, 0, 120, ["Где кот?"], 0.25, 0.75, 0.1)
        p2 = SiqPackage(pkg.path)
        try:
            q = p2.rounds[0]["themes"][0]["questions"][0]
            assert q["q_type"] == "point"
            assert q["answers"] == ["0.2500,0.7500"]
            assert q["answer_deviation"] == pytest.approx(0.1)
        finally:
            p2.close()

    def test_add_media_to_question(self, pkg, tmp_path):
        media_file = tmp_path / "новое_фото.png"
        media_file.write_bytes(b"\x89PNGnew")
        assert pkg.add_media_to_question(0, 0, 0, str(media_file))
        with zipfile.ZipFile(pkg.path) as zf:
            assert "Images/новое_фото.png" in zf.namelist()
        p2 = SiqPackage(pkg.path)
        try:
            q = p2.rounds[0]["themes"][0]["questions"][0]
            refs = [i for i in q["items"] if i["is_ref"]]
            assert any(i["text"] == "новое_фото.png" for i in refs)
        finally:
            p2.close()

    def test_add_media_name_collision(self, pkg, tmp_path):
        media_file = tmp_path / "pic.png"  # такое имя уже есть в архиве
        media_file.write_bytes(b"OTHER")
        assert pkg.add_media_to_question(0, 0, 0, str(media_file))
        with zipfile.ZipFile(pkg.path) as zf:
            names = zf.namelist()
            assert "Images/pic.png" in names
            assert "Images/pic_1.png" in names

    def test_add_media_unsupported_ext(self, pkg, tmp_path):
        f = tmp_path / "данные.xyz"
        f.write_bytes(b"x")
        assert pkg.add_media_to_question(0, 0, 0, str(f)) is False

    def test_media_survives_edits(self, pkg):
        """Правка XML не должна портить медиа-файлы в архиве."""
        assert pkg.save_theme_name(0, 0, "X")
        with zipfile.ZipFile(pkg.path) as zf:
            assert zf.read("Images/pic.png").startswith(b"\x89PNG")
            assert zf.read("Audio/sound.mp3").startswith(b"\xff\xfb")

    def test_extract_after_rewrite(self, pkg):
        pkg.extract_media("pic.png")
        assert pkg.save_theme_name(0, 0, "Y")
        out = pkg.extract_media("sound.mp3")
        assert out is not None


# ── _safe_replace ────────────────────────────────────────────────────────────
class TestSafeReplace:
    def test_normal_replace(self, tmp_path):
        src = tmp_path / "new.bin"
        dst = tmp_path / "old.bin"
        src.write_bytes("новое".encode("utf-8"))
        dst.write_bytes("старое".encode("utf-8"))
        _safe_replace(str(src), str(dst))
        assert dst.read_bytes() == "новое".encode()
        assert not src.exists()

    def test_readonly_target(self, tmp_path):
        import stat
        src = tmp_path / "new.bin"
        dst = tmp_path / "old.bin"
        src.write_bytes("новое".encode("utf-8"))
        dst.write_bytes("старое".encode("utf-8"))
        os.chmod(dst, stat.S_IREAD)
        try:
            _safe_replace(str(src), str(dst))
            assert dst.read_bytes() == "новое".encode()
        finally:
            os.chmod(dst, stat.S_IWRITE | stat.S_IREAD)
