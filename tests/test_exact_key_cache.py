"""Отпечатки прежних паков читаются заново только у новых и изменённых архивов."""
import os

from si_hyx_parts.animepack import exact_key_cache


def test_unchanged_archives_come_from_cache(tmp_path):
    first, second = tmp_path / "a.siq", tmp_path / "b.siq"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    calls = []

    def reader(path):
        calls.append(os.path.basename(path))
        return {("song", os.path.basename(path), "op1"), ("media", "x")}

    paths = [str(first), str(second)]
    got = exact_key_cache.read_all(paths, reader)
    assert calls == ["a.siq", "b.siq"]
    again = exact_key_cache.read_all(paths, reader)
    assert calls == ["a.siq", "b.siq"] and again == got
    second.write_bytes(b"changed")
    exact_key_cache.read_all(paths, reader)
    assert calls == ["a.siq", "b.siq", "b.siq"]


def test_empty_result_is_not_cached_and_skipped_paths_are_not_read(tmp_path):
    pack = tmp_path / "a.siq"
    pack.write_bytes(b"x")
    calls = []
    reader = lambda path: calls.append(path) or set()
    exact_key_cache.read_all([str(pack)], reader)
    exact_key_cache.read_all([str(pack)], reader)
    assert len(calls) == 2
    assert exact_key_cache.read_all([str(pack)], reader, skip=lambda p: True) == {}
    assert len(calls) == 2
