# -*- coding: utf-8 -*-
"""Prepared questions survive failures before selection returns."""
import os
import threading
import zipfile
from types import SimpleNamespace

import pytest
import requests

import animepack as ap
from si_hyx_parts.animepack import assembly_recovery
from test_animepack_mixed_streams import _generator, make_anime
from test_assembly_recovery import _gen, _songs


def test_catalog_failure_keeps_already_accepted_media(tmp_path, monkeypatch):
    gen = _generator(tmp_path, monkeypatch, [], [], questions=2,
                     pct_songs=0, pct_frames=100)
    gen.s.validate = lambda: []
    monkeypatch.setattr(gen, "load_exclusions", lambda: None)
    accepted = threading.Event()
    gen._progress = lambda done, *_: accepted.set() if done == 1 else None
    candidate = ap.SongCandidate({}, make_anime(1), kind=ap.FRAME_KIND)
    candidate.frame_name = "frame.jpg"
    candidate.has_frame = True

    def candidates():
        yield candidate
        assert accepted.wait(5), "The first question was never accepted"
        raise RuntimeError("catalog failed after one question")

    def fetch(cand):
        with open(os.path.join(gen.folder, "Images", cand.frame_file), "wb") as f:
            f.write(b"frame")
        return True

    monkeypatch.setattr(gen, "iter_candidates", candidates)
    monkeypatch.setattr(gen, "_fetch_media", fetch)
    # Продолжать нельзя — готовый вопрос сохраняется паком сразу (иначе было
    # бы «Не получилось»), и пак помечен аварийным.
    result = gen.run(str(tmp_path / "pack.siq"))
    assert result.aborted and result.path
    assert [c.mal_id for c in result.songs] == [1]
    assert any("catalog failed after one question" in w for w in result.warnings)
    with zipfile.ZipFile(result.path) as package:
        assert package.read("Images/frame.jpg") == b"frame"
    assert gen.folder == ""


def test_strict_karaoke_failure_keeps_prepared_questions(tmp_path, monkeypatch):
    from music_effects import EffectSlots
    gen = _gen(tmp_path, monkeypatch)
    gen.s.validate = lambda: []
    monkeypatch.setattr(gen, "load_exclusions", lambda: None)

    def selected():
        gen._selected_songs.extend(_songs())
        with open(os.path.join(gen.folder, "Video", "1.mp4"), "wb") as f:
            f.write(b"karaoke")
        EffectSlots(gen.s, 1).quit("karaoke", "неудач набралось 44")

    monkeypatch.setattr(gen, "select_songs", selected)
    with pytest.raises(ap.AnimePackError, match="Караоке.*не хватает"):
        gen.run()
    attempt = assembly_recovery.latest()
    assert attempt["questions"] == 1
    assert os.path.isfile(os.path.join(attempt["path"], "Video", "1.mp4"))


def test_error_writing_cancelled_pack_also_keeps_media(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    gen.s.validate = lambda: []
    monkeypatch.setattr(gen, "load_exclusions", lambda: None)
    state = []
    gen._should_stop = lambda: bool(state)

    def selected():
        state.append(True)
        return _songs()

    monkeypatch.setattr(gen, "select_songs", selected)
    monkeypatch.setattr(gen, "write_package",
                        lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(ap.AnimePackError, match="Собрать сохранённое"):
        gen.run()
    assert assembly_recovery.latest()["questions"] == 1


@pytest.mark.parametrize("operation", ["move", "mkdir", "snapshot", "publish"])
def test_failed_recovery_never_deletes_source_media(tmp_path, monkeypatch, operation):
    gen = _gen(tmp_path, monkeypatch)
    gen.prepare_dirs()
    folder = gen.folder
    media = os.path.join(folder, "Video", "1.mp4")
    with open(media, "wb") as f:
        f.write(b"ready")

    def fail(*args, **kwargs):
        raise OSError("storage unavailable")

    if operation == "move":
        monkeypatch.setattr(assembly_recovery.shutil, "move", fail)
    elif operation == "mkdir":
        monkeypatch.setattr(assembly_recovery.os, "makedirs", fail)
    elif operation == "snapshot":
        monkeypatch.setattr(assembly_recovery.pickle, "dumps", fail)
    else:
        monkeypatch.setattr(assembly_recovery.os, "replace", fail)
    with pytest.raises(ap.AnimePackError, match="Исходные данные сохранены"):
        assembly_recovery.keep_or_raise(gen, _songs(), RuntimeError("failed"))
    kept = gen.folder
    gen.cleanup()
    assert os.path.isfile(os.path.join(kept, "Video", "1.mp4"))
    assert os.path.isdir(kept)


def test_real_generator_retries_transient_image_download(monkeypatch, tmp_path):
    gen = _gen(tmp_path, monkeypatch)
    attempts = []
    response = SimpleNamespace(content=b"image", headers={},
                               raise_for_status=lambda: None, close=lambda: None)

    def get(url, **kwargs):
        attempts.append(url)
        if len(attempts) == 1:
            raise requests.ConnectTimeout("temporary failure")
        return response

    gen.session = SimpleNamespace(get=get)
    pause = gen._download_retry_pause
    monkeypatch.setattr(gen, "_download_retry_pause", lambda seconds: pause(0))
    assert gen._get_bytes("https://cdn.test/frame.jpg") == b"image"
    assert len(attempts) == 2


def test_rebuild_finishes_only_unprepared_title_riddles(tmp_path, monkeypatch):
    gen = _gen(tmp_path, monkeypatch)
    gen.prepare_dirs()
    ready = ap.SongCandidate({}, make_anime(1), kind="synonyms",
                             plot_question="Готовая загадка")
    pending = ap.SongCandidate({}, make_anime(2), kind="synonyms")
    path = assembly_recovery.save(gen, [ready, pending], "selection failed")
    second = _gen(tmp_path, monkeypatch)
    requests = []

    def finish(generator, candidates):
        requests.extend(c.mal_id for c in candidates)
        for c in candidates:
            c.plot_question = "Новая загадка"
        return candidates

    monkeypatch.setattr("si_hyx_parts.animepack.title_questions.generate_titles", finish)
    monkeypatch.setattr(second, "write_package", lambda *a: str(tmp_path / "pack.siq"))
    result = second.rebuild(path)
    assert requests == [2]
    assert [c.plot_question for c in result.songs] == ["Готовая загадка", "Новая загадка"]
