# -*- coding: utf-8 -*-
"""Имена скачиваемых файлов: берём имя с сайта и режем только то, что не
разрешает файловая система (filenames.safe_filename/unique_path)."""
import pytest

from filenames import safe_filename, unique_path


@pytest.mark.parametrize("name", [
    "Аниме пак(изи)",           # скобки — из-за них имя и портилось
    "Логово анимешника №1",
    "Re Zero. Жизнь с нуля",
    "СульПак 3.33 ты (не) доделаешь",
    "FULL ANIME PACK 3",
    "Аниме, аниме и еще больше аниме",
])
def test_normal_names_are_kept_as_is(name):
    assert safe_filename(name) == name


def test_forbidden_chars_become_spaces():
    """Запрещённое меняем на пробел, а не выкидываем: «Пак: начало» не должно
    склеиться в «Пакначало»."""
    assert safe_filename('Пак: начало') == "Пак начало"
    assert safe_filename('a<b>c:d"e/f\\g|h?i*j') == "a b c d e f g h i j"


def test_control_chars_removed():
    assert safe_filename("Пак\x01\nтест") == "Пак тест"


def test_trailing_dots_and_spaces_stripped():
    """Windows молча срезает их сам — лучше сделать это осознанно."""
    assert safe_filename("Пак...  ") == "Пак"
    assert safe_filename("  .Пак.") == "Пак"


def test_dot_inside_name_is_legal():
    assert safe_filename("2.43 Волейбольный клуб") == "2.43 Волейбольный клуб"


def test_reserved_device_name_gets_suffix():
    assert safe_filename("CON") == "CON_"
    assert safe_filename("com1") == "com1_"
    assert safe_filename("Контра") == "Контра"      # не устройство


def test_empty_falls_back():
    assert safe_filename("///", "42") == "42"
    assert safe_filename("", "") == "файл"


def test_length_capped():
    out = safe_filename("Пак " * 100)
    assert len(out) <= 120
    assert not out.endswith(" ")


def test_unique_path_free_name_unchanged(tmp_path):
    p = tmp_path / "Пак.siq"
    assert unique_path(p) == p


def test_unique_path_adds_number(tmp_path):
    (tmp_path / "Пак.siq").write_bytes(b"x")
    assert unique_path(tmp_path / "Пак.siq").name == "Пак (2).siq"
    (tmp_path / "Пак (2).siq").write_bytes(b"x")
    assert unique_path(tmp_path / "Пак.siq").name == "Пак (3).siq"
