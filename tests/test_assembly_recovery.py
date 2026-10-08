# -*- coding: utf-8 -*-
"""Упавшая упаковка не уничтожает готовые вопросы и медиа."""
import os

import pytest

import animepack as ap
from si_hyx_parts.animepack import assembly_recovery


def _gen(tmp_path, monkeypatch, settings=None):
    gen = ap.AnimePackGenerator(settings or ap.PackSettings(title="Пак"),
                                frames_history_path=str(tmp_path / "f.json"))
    gen.db_cache = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    gen.logs = []
    gen.log = gen.logs.append
    for name in ("mark_list_owners", "save_frames_history"):
        monkeypatch.setattr(gen, name, lambda songs: None)
    monkeypatch.setattr(gen, "log_gemini_spent", lambda: None)
    monkeypatch.setattr(gen, "log_stage_times", lambda elapsed: None)
    monkeypatch.setattr("si_hyx_parts.animepack.author_lookup.enrich_authors",
                        lambda *args: None)
    monkeypatch.setattr("si_hyx_parts.animepack.level_avg.short_pack_average_error",
                        lambda settings, songs: "")
    return gen


def _songs():
    return [ap.SongCandidate(song={}, anime={"malId": 7, "name": "Наруто",
                                             "franchise": "naruto"},
                             kind=ap.PIXEL_KIND, has_video=True)]


def test_failed_packaging_keeps_questions_and_media(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    gen.prepare_dirs()
    media = os.path.join(gen.folder, "Video", "1.mp4")
    with open(media, "wb") as f:
        f.write(b"video")
    gen._fr_parts["naruto"] = [{"malId": 7}]

    def broken(songs, out_path=None):
        raise ap.AnimePackError("средняя 2,4 вместо 2")

    monkeypatch.setattr(gen, "write_package", broken)
    result = ap.PackResult()
    with pytest.raises(ap.AnimePackError, match="Собрать сохранённое"):
        gen._assemble_or_keep(_songs(), None, result)
    assert gen.folder == ""
    attempt = assembly_recovery.latest()
    assert attempt["questions"] == 1 and "средняя 2,4 вместо 2" in attempt["error"]
    with open(os.path.join(attempt["path"], "Video", "1.mp4"), "rb") as f:
        assert f.read() == b"video"
    songs, parts = assembly_recovery.load(attempt["path"])
    assert songs[0].title_ru and parts == {"naruto": [{"malId": 7}]}


def test_saved_attempt_is_rebuilt_from_a_copy_and_kept(tmp_path, monkeypatch):
    first = _gen(tmp_path, monkeypatch)
    first.prepare_dirs()
    monkeypatch.setattr(first, "write_package",
                        lambda songs, out_path=None: (_ for _ in ()).throw(OSError("диск")))
    with pytest.raises(ap.AnimePackError, match="OSError: диск"):
        first._assemble_or_keep(_songs(), None, ap.PackResult())
    path = assembly_recovery.latest()["path"]

    second = _gen(tmp_path, monkeypatch)
    written = []

    def write(songs, out_path=None):
        written.append((second.folder, len(songs)))
        return str(tmp_path / "pack.siq")

    monkeypatch.setattr(second, "write_package", write)
    result = second.rebuild(path)
    # Сборка идёт из временной копии: попытка остаётся, пока её не удалят
    # вручную, — повторная сборка возможна и после удачной.
    assert len(written) == 1 and written[0][1] == 1 and written[0][0] != path
    assert result.path.endswith("pack.siq")
    assert second.folder == "" and not os.path.exists(written[0][0])
    assert assembly_recovery.latest()["path"] == path


def test_failed_rebuild_keeps_the_attempt(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    gen.prepare_dirs()
    monkeypatch.setattr(gen, "write_package",
                        lambda songs, out_path=None: (_ for _ in ()).throw(
                            ap.AnimePackError("снова")))
    with pytest.raises(ap.AnimePackError):
        gen._assemble_or_keep(_songs(), None, ap.PackResult())
    path = assembly_recovery.latest()["path"]
    with pytest.raises(ap.AnimePackError, match="снова"):
        gen.rebuild(path)
    gen.cleanup()
    assert os.path.isdir(path) and assembly_recovery.latest()["path"] == path


def test_a_new_attempt_replaces_the_old_one(tmp_path, monkeypatch):
    for _ in range(2):
        gen = _gen(tmp_path, monkeypatch)
        gen.prepare_dirs()
        monkeypatch.setattr(gen, "write_package",
                            lambda songs, out_path=None: (_ for _ in ()).throw(
                                ap.AnimePackError("нет")))
        with pytest.raises(ap.AnimePackError):
            gen._assemble_or_keep(_songs(), None, ap.PackResult())
        monkeypatch.setattr(assembly_recovery.time, "strftime",
                            lambda fmt, *a: "20990101-000000")
    assert len(os.listdir(assembly_recovery.recovery_dir())) == 1


def test_download_in_progress_does_not_block_saving(tmp_path, monkeypatch):
    import threading
    gen = _gen(tmp_path, monkeypatch)
    gen.prepare_dirs()
    songs = _songs()
    songs[0]._audio_download = threading.Lock()      # не сохраняется pickle
    monkeypatch.setattr(gen, "write_package",
                        lambda songs, out_path=None: (_ for _ in ()).throw(
                            ap.AnimePackError("нет")))
    with pytest.raises(ap.AnimePackError, match="Собрать сохранённое"):
        gen._assemble_or_keep(songs, None, ap.PackResult())
    saved, _parts = assembly_recovery.load(assembly_recovery.latest()["path"])
    assert not hasattr(saved[0], "_audio_download")


def test_rebuild_button_appears_only_with_a_saved_attempt(qapp, tmp_path, monkeypatch):
    import animepack_tab
    from si_hyx_parts.animepack_tab import saved_attempt
    from test_animepack_tab_mix import _FakeMain
    tab = animepack_tab.AnimePackTab(main_window=_FakeMain())
    try:
        assert not tab.btn_rebuild_saved.isVisibleTo(tab)
        gen = _gen(tmp_path, monkeypatch)
        gen.prepare_dirs()
        monkeypatch.setattr(gen, "write_package",
                            lambda songs, out_path=None: (_ for _ in ()).throw(
                                ap.AnimePackError("нет")))
        with pytest.raises(ap.AnimePackError):
            gen._assemble_or_keep(_songs(), None, ap.PackResult())
        saved_attempt.refresh(tab)
        assert tab.btn_rebuild_saved.isVisibleTo(tab) and tab.btn_rebuild_saved.isEnabled()
        launched = []
        monkeypatch.setattr(tab, "_launch_generation",
                            lambda settings, recovery="": launched.append(recovery))
        saved_attempt.rebuild(tab)
        assert launched == [assembly_recovery.latest()["path"]]
    finally:
        tab.cleanup()
