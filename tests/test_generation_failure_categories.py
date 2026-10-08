"""Infrastructure failures retain questions and do not spend lyric rejection budgets."""
from collections import Counter
import errno
from pathlib import Path
import ssl
from types import SimpleNamespace
import zipfile

import pytest
import requests
import animepack as ap
from music_effects import EffectSlots
from karaoke.availability import temporary
from si_hyx_parts.animepack.candidate_reserve import CandidateReserve
from si_hyx_parts.animepack.package_transaction import archive
from si_hyx_parts.animepack.selection_resources import guarded_fetch, capacity
from si_hyx_parts.kuhi.provider_health import ProviderHealth
import storage_guard


def test_host_pause_and_network_errors_are_temporary():
    assert temporary(ap.AnimePackError("Источник CDN временно на паузе после сетевых сбоев"))
    wrapped = ap.AnimePackError("Не удалось скачать")
    wrapped.__cause__ = requests.Timeout("read")
    assert temporary(wrapped)
    assert not temporary(ValueError("В выбранном отрезке нет вокала с таймингами"))


def test_temporary_karaoke_failure_returns_slot_without_semantic_strike():
    slots = EffectSlots(ap.PackSettings(karaoke_enabled=True, karaoke_percent=100), 1)
    candidate = SimpleNamespace(_music_temporary=True)
    slots.reserve(candidate)
    for _ in range(4):
        slots.release(candidate)
        assert slots.failures == 0 and not slots.failed and not slots.streak
        slots.reserve(candidate)


def test_deferred_retry_retains_same_song_and_waits_for_cooldown(monkeypatch):
    from test_animepack_mixed_streams import make_anime
    from si_hyx_parts.animepack import candidate_reserve
    # A lightweight reserve still exercises the production clean-copy path.
    candidate = ap.SongCandidate({"songName": "Song", "audio": "file.mp3"}, make_anime(7), kind="opening")
    generator = SimpleNamespace(s=ap.PackSettings(dup_anime=True, dup_franchise=True),
                                _pick_kind=lambda *args: "opening")
    monkeypatch.setattr(candidate_reserve, "available_kinds", lambda *args: ["opening"])
    now = [10.0]
    monkeypatch.setattr(candidate_reserve.time, "monotonic", lambda: now[0])
    candidate._retry_after = 70
    candidate._technical_retries = 1
    reserve = CandidateReserve(generator, {"opening": 1})
    reserve.park(candidate)
    assert reserve.take(Counter(), Counter(), {"opening": 1}) is None
    assert reserve.retry_wait() == 60
    now[0] = 71
    retried = reserve.take(Counter(), Counter(), {"opening": 1})
    assert retried.audio_file == "file.mp3" and retried._technical_retries == 1
    assert "opening" not in retried._tried_kinds


def test_low_disk_stops_before_media_function(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_guard.shutil, "disk_usage", lambda _: SimpleNamespace(free=128 * storage_guard.MIB))
    calls = []
    generator = SimpleNamespace(folder=str(tmp_path), _fetch_media=lambda _: calls.append(1))
    with pytest.raises(storage_guard.StorageError, match="Освободите место"):
        guarded_fetch(generator)(object())
    assert not calls


def test_ffmpeg_enospc_is_an_environment_error(tmp_path):
    with pytest.raises(storage_guard.StorageError) as failure:
        storage_guard.raise_if_full("av_interleaved_write_frame(): No space left on device", tmp_path)
    assert failure.value.errno == errno.ENOSPC


def test_failed_archive_never_publishes_broken_siq(tmp_path):
    target = tmp_path / "pack.siq"
    with pytest.raises(OSError, match="disk full"):
        with archive(target, zipfile) as package:
            package.writestr("content.xml", b"<package/>")
            raise OSError("disk full")
    assert not target.exists() and not list(tmp_path.glob("*.partial"))
    with archive(target, zipfile) as package:
        package.writestr("content.xml", b"<package/>")
    with zipfile.ZipFile(target) as package:
        assert package.testzip() is None and package.read("content.xml") == b"<package/>"


def test_bad_certificate_pauses_immediately_without_disabling_tls_checks():
    health = ProviderHealth()
    assert health.allow("animegg", "episodes")
    assert health.result("animegg", "episodes", error=ssl.SSLCertVerificationError("certificate has expired"))
    assert not health.allow("animegg", "episodes")
    assert health.allow("another", "episodes")


def test_heavy_sources_leave_room_for_other_questions():
    assert capacity(ap.MANGA_KIND, 8) == 8
    assert capacity(ap.EPISODE_KIND, 8) == 4
    assert capacity(ap.FRAME_KIND, 8) == 16


def test_mixed_quota_average_is_checked_before_downloads():
    from si_hyx_parts.animepack.generation_preflight import average_problems
    settings = SimpleNamespace(question_quotas={ap.FRAME_KIND: 1, ap.PIXIV_ART_KIND: 1},
        level_avg=4, art_level_avg=0,
        level_range=lambda kind: (12, 15) if kind == ap.PIXIV_ART_KIND else (1, 15))
    assert "недостижима" in average_problems(settings)[0]


def test_invalid_gemini_schema_does_not_disable_the_key_or_retry(fake_session, fake_response):
    import json
    from gemini_api import GeminiAuthError, GeminiError
    from test_gemini_api import _client, _ok_body, SCHEMA
    response = json.dumps({"error": {"code": 400, "message": "Invalid response_format schema"}})
    answers = iter([fake_response(400, text=response), fake_response(json_data=_ok_body({"ok": True}))])
    session = fake_session([("interactions", lambda *args, **kwargs: next(answers))])
    client = _client(session)
    with pytest.raises(GeminiError) as error:
        client.generate_json("picture", SCHEMA)
    assert not isinstance(error.value, GeminiAuthError) and len(session.calls) == 1
    assert client.generate_json("next job", SCHEMA) == {"ok": True}
