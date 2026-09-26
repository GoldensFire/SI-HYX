# -*- coding: utf-8 -*-
"""Имена файлов в кладовой медиа: раздел, настоящее расширение и переезд.

В окне «Файлы кэша» было два раздела на всё — «Постеры» и «Медиа», — и понять,
кто положил файл, было нельзя; половина кладовой к тому же звалась «.bin» и
ничем не открывалась (жалоба пользователя). Раздел теперь стоит в имени файла,
расширение берётся у самих байтов, а записи со старыми именами подбираются на
месте: скачивать их заново из-за переименования нельзя.
"""
import os

import pytest

import media_cache


JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    folder = tmp_path / "animepack_media"
    folder.mkdir()
    monkeypatch.setattr(media_cache, "MEDIA_CACHE_DIR", str(folder))
    monkeypatch.setattr(media_cache, "_SIZE", None)
    return folder


def test_file_name_carries_the_section_and_the_real_extension(cache_dir):
    path = media_cache.put("anime-frame", "http://a/b", JPEG)
    name = os.path.basename(path)
    assert name.startswith("anime-frame__")
    assert name.endswith(".jpg")          # а не «.bin», который не открыть
    assert media_cache.namespace_of(path) == "anime-frame"
    assert media_cache.entries()[0]["namespace"] == "anime-frame"
    # Найдётся и тогда, когда звавший про расширение ничего не знает.
    assert media_cache.find_path("anime-frame", "http://a/b") == path
    assert media_cache.read("anime-frame", "http://a/b") == JPEG


def test_the_asked_suffix_wins_when_the_caller_knows_it(cache_dir):
    path = media_cache.put("avif", "key", b"\x00\x00\x00 ftypavif", ".avif")
    assert os.path.basename(path).startswith("avif__")
    assert path.endswith(".avif")
    assert media_cache.find_path("avif", "key", ".avif") == path


def test_an_entry_saved_under_the_old_name_is_adopted_not_redownloaded(cache_dir):
    """Переименование имён не имеет права стоить пользователю скачиваний."""
    digest = media_cache._digest("cover-audio", "vid|fmt")
    legacy = cache_dir / f"{digest}.bin"
    legacy.write_bytes(b"ID3" + b"0" * 64)
    found = media_cache.find_path("cover-audio", "vid|fmt")
    assert found and os.path.basename(found) == f"cover-audio__{digest}.mp3"
    assert not legacy.exists()
    assert media_cache.read("cover-audio", "vid|fmt").startswith(b"ID3")


def test_old_bin_files_get_their_real_extension_and_stay_findable(cache_dir):
    digest = media_cache._digest("anime-frame", "u")
    (cache_dir / f"{digest}.bin").write_bytes(PNG)
    assert media_cache.migrate_names() == 1
    assert (cache_dir / f"{digest}.png").exists()
    # Переименованный файл всё ещё та же запись кладовой.
    found = media_cache.find_path("anime-frame", "u")
    assert found.endswith(f"anime-frame__{digest}.png")


def test_migration_leaves_files_it_cannot_recognise_alone(cache_dir):
    (cache_dir / "deadbeef.bin").write_bytes(b"\x01\x02\x03\x04")
    assert media_cache.migrate_names() == 0
    assert (cache_dir / "deadbeef.bin").exists()


def test_rewriting_an_entry_does_not_leave_the_old_file_behind(cache_dir):
    digest = media_cache._digest("anime-frame", "u")
    (cache_dir / f"{digest}.bin").write_bytes(b"old" * 8)
    media_cache.put("anime-frame", "u", PNG)
    left = sorted(p.name for p in cache_dir.iterdir())
    assert left == [f"anime-frame__{digest}.png"]


def test_sniff_knows_the_usual_suspects():
    assert media_cache.sniff_ext(JPEG) == ".jpg"
    assert media_cache.sniff_ext(PNG) == ".png"
    assert media_cache.sniff_ext(b"RIFF1234WEBPxxxx") == ".webp"
    assert media_cache.sniff_ext(b"\x00\x00\x00 ftypavif") == ".avif"
    assert media_cache.sniff_ext(b"\x00\x00\x00 ftypM4A ") == ".m4a"
    assert media_cache.sniff_ext(b"\x1a\x45\xdf\xa3....") == ".webm"
    assert media_cache.sniff_ext(b"nonsense") == ".bin"
