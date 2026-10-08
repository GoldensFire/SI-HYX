"""Сбои сети не обрывают пак: паузы, повторы и честный итог."""
from types import SimpleNamespace

import pytest

import animepack as ap
import music_effects
from music_effects import EffectSlots, FAILURES_MIN, TECHNICAL_PAUSES


def _karaoke(percent=50, songs=4):
    return EffectSlots(ap.PackSettings(karaoke_enabled=True, karaoke_percent=percent,
                                       karaoke_ai_fallback=False), songs)


def _song(available, kind="opening"):
    return SimpleNamespace(kind=kind, _authored_available=available)


# ── слоты способов подачи ─────────────────────────────────────────────────────
def test_unknown_timings_take_an_ordinary_slot():
    """«Неизвестно» больше не попадает в караоке, пока свободны обычные слоты."""
    slots = _karaoke()
    for _ in range(2):
        song = _song(None)
        slots.reserve(song)
        assert song.music_effect == "original"
    song = _song(True)
    slots.reserve(song)
    assert song.music_effect == "karaoke"


def test_a_song_without_timings_is_refused_when_only_karaoke_is_left():
    slots = _karaoke(percent=100, songs=2)
    assert slots.refuses(_song(False))
    assert not slots.refuses(_song(None))


def test_temporary_failures_pause_karaoke_instead_of_stopping(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(music_effects.time, "monotonic", lambda: now[0])
    slots = _karaoke(percent=100, songs=2)
    for pause in range(TECHNICAL_PAUSES + 1):
        for _ in range(FAILURES_MIN):
            song = _song(True)
            slots.reserve(song)
            song._music_temporary = True
            slots.release(song)          # раньше на двенадцатом — RuntimeError
        notes = slots.take_notes()
        assert len(notes) == 1
        if pause < TECHNICAL_PAUSES:
            assert slots.paused("karaoke") and "ждут" in notes[0]
            now[0] += music_effects.TECHNICAL_PAUSE_SECONDS + 1
    assert slots.dropped == ["karaoke"] and "оригиналом" in notes[0]
    song = _song(True)
    slots.reserve(song)
    assert song.music_effect == "original"


def test_a_success_resets_the_pause_count(monkeypatch):
    monkeypatch.setattr(music_effects.time, "monotonic", lambda: 0.0)
    slots = _karaoke(percent=100, songs=2)
    for _ in range(FAILURES_MIN - 1):
        song = _song(True)
        slots.reserve(song)
        song._network_temporary = True
        slots.release(song)
    good = _song(True)
    slots.reserve(good)
    slots.succeed(good)
    assert slots.technical["karaoke"] == 0 and not slots.paused("karaoke")


# ── Pixiv: сеть ≠ ключ ────────────────────────────────────────────────────────
def _client(error):
    def auth(refresh_token):
        raise error
    return SimpleNamespace(api=SimpleNamespace(auth=auth), refresh_token="t",
                           stopped=lambda: False)


def test_pixiv_rejected_token_disables_the_kind():
    import pixiv_auth
    from pixiv_art_api import PixivArtUnavailable
    with pytest.raises(PixivArtUnavailable, match="refresh token"):
        pixiv_auth.authenticate(_client(Exception("auth() failed!\nHTTP 400: invalid_grant")))


def test_pixiv_network_failure_skips_only_the_title(monkeypatch):
    import pixiv_auth
    from pixiv_art_api import PixivArtUnavailable
    monkeypatch.setattr(pixiv_auth, "AUTH_PAUSES", (0, 0))
    client = _client(Exception("requests POST error: Read timed out"))
    for _ in range(pixiv_auth.DOWN_AFTER - 1):
        with pytest.raises(pixiv_auth.PixivNetworkError):
            pixiv_auth.authenticate(client)
    with pytest.raises(PixivArtUnavailable, match="подряд"):
        pixiv_auth.authenticate(client)


# ── сбой сети откладывает тайтл, а не сжигает его ─────────────────────────────
def test_paused_host_marks_the_task_as_temporary(tmp_path):
    from si_hyx_parts.animepack import media_transfer
    from si_hyx_parts.animepack.selection_resources import guarded_fetch
    generator = SimpleNamespace(folder=str(tmp_path))

    def fetch(candidate):
        media_transfer.host_state(generator, "https://cdn.example/a.jpg", failed=True)
        media_transfer.host_state(generator, "https://cdn.example/a.jpg", failed=True)
        media_transfer.host_state(generator, "https://cdn.example/a.jpg", failed=True)
        try:
            media_transfer.host_state(generator, "https://cdn.example/a.jpg")
        except ap.AnimePackError:
            return False
        return True

    generator._fetch_media = fetch
    candidate = SimpleNamespace()
    assert guarded_fetch(generator)(candidate) is False
    assert candidate._network_temporary
    generator._fetch_media = lambda candidate: False
    assert guarded_fetch(generator)(candidate) is False
    assert not candidate._network_temporary


# ── план книг не держит поток аниме ───────────────────────────────────────────
def test_streams_skip_a_stream_that_is_still_planning():
    from si_hyx_parts.animepack.manga_plan_prefetch import PENDING

    def books():
        yield PENDING
        yield PENDING
        yield "book"

    merged = ap.AnimePackGenerator._merge_streams(
        [("manga", books(), 1), ("anime", iter(["a1", "a2"]), 1)])
    assert list(merged) == ["a1", "a2", "book"]


# ── аварийный пак — с субтитрами караоке и отрывками ──────────────────────────
def test_emergency_package_keeps_karaoke_subtitles_and_episodes(tmp_path):
    from si_hyx_parts.animepack import emergency_package
    song = ap.SongCandidate({}, {"malId": 5, "name": "Test"}, kind="opening")
    song.music_effect, song.has_video = "karaoke", True
    clip = ap.SongCandidate({}, {"malId": 6, "name": "Clip"}, kind=ap.EPISODE_KIND)
    clip.episode_clip = {"episode": 3, "start": 10.0}
    (tmp_path / "Video").mkdir()
    subtitle = tmp_path / "Video" / (song.video_out.rsplit(".", 1)[0] + ".ass")
    subtitle.write_text("[Script Info]", encoding="utf-8")
    generator = SimpleNamespace(folder=str(tmp_path), s=ap.PackSettings(), log=lambda _: None)
    result = ap.PackResult()
    found = emergency_package._subtitles(generator, [song, clip], result)
    assert found == {"Karaoke/" + subtitle.name: subtitle}
    extras = emergency_package._extras(generator, [clip], result)
    assert '"episode": 3' in extras["episodes.json"]


# ── в исключения — только полный пак ──────────────────────────────────────────
def test_only_a_complete_pack_goes_to_exclusions():
    import animepack_tab  # noqa: F401 — части грузит публичный модуль
    from si_hyx_parts.animepack_tab.anime_pack_tab import _remember_if_complete
    remembered, lines = [], []
    tab = SimpleNamespace(_remember_generated=remembered.append, log=lines.append)
    songs = [object()] * 3
    _remember_if_complete(tab, ap.PackResult(path="a.siq", songs=songs, requested=4), True)
    _remember_if_complete(tab, ap.PackResult(path="b.siq", songs=songs, requested=3,
                                             aborted=True), True)
    _remember_if_complete(tab, ap.PackResult(path="c.siq", songs=songs, requested=3), True)
    assert remembered == ["c.siq"]
    assert len(lines) == 2 and "вручную" in lines[0]


# ── средняя уступает ради полного пака — с предупреждением ───────────────────
def test_unreachable_average_yields_with_a_journal_warning(tmp_path, monkeypatch):
    from test_animepack_mixed_streams import _generator, make_anime
    cards = [make_anime(i, statusesStats=[{"status": "completed", "count": 3}])
             for i in range(1, 9)]
    gen = _generator(tmp_path, monkeypatch, cards, [], questions=6,
                     pct_songs=0, pct_frames=100, level_avg=3)
    lines = []
    gen._log = lines.append
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    assert len(gen.select_songs()) == 6
    assert any(line.startswith("Внимание:") and "полный пак важнее" in line
               for line in lines)


def test_own_song_average_never_yields(monkeypatch):
    from si_hyx_parts.animepack.average_selection import yields
    gen = SimpleNamespace(s=ap.PackSettings(song_level_avg=4, level_avg=5))
    assert not yields(gen, "opening")
    assert yields(gen, ap.FRAME_KIND)
