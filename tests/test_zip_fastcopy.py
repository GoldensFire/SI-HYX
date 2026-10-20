# -*- coding: utf-8 -*-
"""zip_fastcopy.copy_zip_entry — перенос записи из архива в архив без распаковки.

Проверяется главное свойство: запись доезжает БАЙТ В БАЙТ вместе со своим
способом сжатия, а когда по-быстрому не выходит (шифрование, zip64, битый
заголовок), функция честно отказывается и не оставляет мусора в архиве.
"""
import hashlib
import struct
import zipfile

import pytest

from zip_fastcopy import copy_zip_entry

pytestmark = pytest.mark.integration

BLOB = b"mp3-bytes" * 5000


def _raw(path, name):
    """Сжатые байты записи как они лежат в файле (мимо распаковки)."""
    with zipfile.ZipFile(path) as zf, open(path, "rb") as fp:
        info = zf.getinfo(name)
        fp.seek(info.header_offset)
        fields = struct.unpack(zipfile.structFileHeader,
                               fp.read(zipfile.sizeFileHeader))
        fp.seek(fields[zipfile._FH_FILENAME_LENGTH]
                + fields[zipfile._FH_EXTRA_FIELD_LENGTH], 1)
        return fp.read(info.compress_size)


def _src(tmp_path, name="src.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", "<package/>", zipfile.ZIP_DEFLATED)
        zf.writestr("Audio/песня.mp3", BLOB, zipfile.ZIP_DEFLATED)
        zf.writestr("Video/ролик.mp4", BLOB, zipfile.ZIP_STORED)
        zf.writestr("Images/кадр.avif", b"", zipfile.ZIP_DEFLATED)
    return path


def test_entry_arrives_byte_for_byte(tmp_path):
    """Ни один байт не меняется — ни сжатые данные, ни CRC, ни способ сжатия."""
    src, out = _src(tmp_path), tmp_path / "out.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            assert copy_zip_entry(zin, zout, info) is True
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None
        assert zf.namelist() == ["content.xml", "Audio/песня.mp3",
                                 "Video/ролик.mp4", "Images/кадр.avif"]
        assert zf.read("Audio/песня.mp3") == BLOB
        assert zf.read("Video/ролик.mp4") == BLOB
        assert zf.read("Images/кадр.avif") == b""
        assert zf.getinfo("Audio/песня.mp3").compress_type == zipfile.ZIP_DEFLATED
        assert zf.getinfo("Video/ролик.mp4").compress_type == zipfile.ZIP_STORED
    for name in ("Audio/песня.mp3", "Video/ролик.mp4"):
        assert hashlib.sha1(_raw(out, name)).hexdigest() == \
               hashlib.sha1(_raw(src, name)).hexdigest()


def test_entry_keeps_its_date_and_attributes(tmp_path):
    src, out = tmp_path / "a.zip", tmp_path / "b.zip"
    zi = zipfile.ZipInfo("Audio/a.mp3", date_time=(2011, 5, 17, 13, 45, 20))
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    zi.create_system = 3
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr(zi, BLOB)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        assert copy_zip_entry(zin, zout, zin.getinfo("Audio/a.mp3")) is True
    with zipfile.ZipFile(out) as zf:
        got = zf.getinfo("Audio/a.mp3")
        assert got.date_time == (2011, 5, 17, 13, 45, 20)
        assert got.external_attr == 0o644 << 16
        assert got.create_system == 3
        assert got.CRC == zipfile.ZipFile(src).getinfo("Audio/a.mp3").CRC


def test_name_argument_renames_the_entry(tmp_path):
    """Постер пережали в .avif — имя новое, а байты кладём чужие, как есть."""
    src, out = _src(tmp_path), tmp_path / "out.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        info = zin.getinfo("Audio/песня.mp3")
        assert copy_zip_entry(zin, zout, info, name="Audio/другая.mp3") is True
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["Audio/другая.mp3"]
        assert zf.read("Audio/другая.mp3") == BLOB
        assert zf.testzip() is None


def test_copied_entries_mix_with_the_usual_ones(tmp_path):
    """Перенесённые и записанные обычным путём записи живут в одном архиве:
    центральный каталог обязан знать и о тех, и о других."""
    src, out = _src(tmp_path), tmp_path / "out.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        zout.writestr("content.xml", b"<package>new</package>")
        assert copy_zip_entry(zin, zout, zin.getinfo("Audio/песня.mp3"))
        zout.writestr("Images/новый.avif", b"avif")
        assert copy_zip_entry(zin, zout, zin.getinfo("Video/ролик.mp4"))
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None
        assert zf.namelist() == ["content.xml", "Audio/песня.mp3",
                                 "Images/новый.avif", "Video/ролик.mp4"]
        assert zf.read("content.xml") == b"<package>new</package>"
        assert zf.read("Audio/песня.mp3") == BLOB
        assert zf.read("Images/новый.avif") == b"avif"


def test_broken_crc_entry_is_carried_over_as_is(tmp_path):
    """Битую запись (CRC не сходится) перенос отдаёт как есть.

    Обычный путь на ней падает BadZipFile — и пак с одним испорченным роликом
    вообще переставал сохраняться. Такие паки в Загрузках реально есть."""
    src, out = tmp_path / "a.zip", tmp_path / "b.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("Video/v.mp4", BLOB, zipfile.ZIP_STORED)
    raw = src.read_bytes()
    src.write_bytes(raw.replace(BLOB[:9], b"broken!!!", 1))   # CRC теперь врёт
    with zipfile.ZipFile(src) as zin:
        with pytest.raises(zipfile.BadZipFile):     # старый путь
            zin.read("Video/v.mp4")
        with zipfile.ZipFile(out, "w") as zout:
            assert copy_zip_entry(zin, zout, zin.getinfo("Video/v.mp4")) is True
    assert _raw(out, "Video/v.mp4") == _raw(src, "Video/v.mp4")


def test_gives_up_on_an_encrypted_entry(tmp_path):
    src = _src(tmp_path)
    with zipfile.ZipFile(src) as zin, \
            zipfile.ZipFile(tmp_path / "out.zip", "w") as zout:
        info = zin.getinfo("Audio/песня.mp3")
        info.flag_bits |= 0x01                      # «запись зашифрована»
        assert copy_zip_entry(zin, zout, info) is False


def test_gives_up_on_a_zip64_sized_entry(tmp_path):
    src = _src(tmp_path)
    with zipfile.ZipFile(src) as zin, \
            zipfile.ZipFile(tmp_path / "out.zip", "w") as zout:
        info = zin.getinfo("Audio/песня.mp3")
        info.file_size = zipfile.ZIP64_LIMIT + 1
        assert copy_zip_entry(zin, zout, info) is False


def test_gives_up_on_a_broken_local_header(tmp_path):
    src = _src(tmp_path)
    with zipfile.ZipFile(src) as zin, \
            zipfile.ZipFile(tmp_path / "out.zip", "w") as zout:
        info = zin.getinfo("Audio/песня.mp3")
        info.header_offset += 3                     # сигнатуры там уже нет
        assert copy_zip_entry(zin, zout, info) is False


def test_leaves_no_garbage_when_it_gives_up(tmp_path):
    """Оборвавшийся перенос откатывается: недописанные байты не должны остаться
    в архиве, поверх них сразу пишет обычный путь."""
    src, out = _src(tmp_path), tmp_path / "out.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        info = zin.getinfo("Audio/песня.mp3")
        info.compress_size = 10_000_000             # запись «оборвётся»
        assert copy_zip_entry(zin, zout, info) is False
        zout.writestr("Audio/песня.mp3", BLOB)
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["Audio/песня.mp3"]
        assert zf.read("Audio/песня.mp3") == BLOB
        assert zf.testzip() is None
