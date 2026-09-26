# -*- coding: utf-8 -*-
"""Кавер вместо отрезка с CDN: слоты, сервис и загрузчик звука генератора.

Ни сети, ни ffmpeg, ни yt-dlp: процессы подменяются тем же `run`, через который
их зовёт генератор, а звук — настоящий синтезированный WAV (тот же приём, что в
test_cover_audio). Проверяется поведение, а не строки команд.
"""
import json
import threading
import time
import wave
import zipfile

import numpy as np
import pytest

import animepack as ap
import cover_cache as cache
import cover_service
from cover_service import CoverService
from music_effects import EffectSlots
from test_cover_audio import ROOTS, _played, _tune


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / "covers"))


def settings(**kwargs):
    return ap.PackSettings(cover_enabled=True, audio_cut=5, rounds=1, themes=1,
                           questions=1, **kwargs)


def candidate(**kwargs):
    song = {"audio": "source.mp3", "annSongId": 7, "songType": 1,
            "songName": "unravel", "songArtist": "TK",
            "animeENName": "Tokyo Ghoul", "animeJPName": "東京喰種"}
    return ap.SongCandidate(song=song, anime={"malId": 1, "name": "Tokyo Ghoul"},
                            kind="opening", music_effect="cover", **kwargs)


def test_covers_use_cookie_selected_on_download_tab(tmp_path, monkeypatch):
    import config

    selected = tmp_path / "YouTubecookies.txt"
    selected.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "ytdlp": {"cookie_path": str(selected)},
    }), encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_FILE", str(settings))
    monkeypatch.setattr(config, "COOKIE_PATHS", {
        "youtube": str(tmp_path / "cookies_youtube.txt"),
        "default": str(tmp_path / "cookies.txt"),
    })

    assert cover_service.youtube_cookie_file() == str(selected)
    assert cover_service.ytdlp_command(["yt-dlp"])[-2:] == [
        "--cookies", str(selected),
    ]


def write_wav(path, samples):
    """Моно s16 22 050 Гц — ровно то, что читает cover_audio.read_wav."""
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(cover_service.audio.SR)
        stream.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def fake_run(work, *, tune=ROOTS, downloads=None, missing=(), same_record=False):
    """Подмена процессов: yt-dlp кладёт «звук», ffmpeg — настоящий WAV.

    Эталон и кандидаты звучат по-разному: имя входного файла говорит, что
    именно сейчас разбирают (ref_… — эталон с CDN, cand_…/pick_… — ролик).

    Кандидат — ИСПОЛНЕНИЕ той же последовательности (_played): те же аккорды,
    но сыгранные, с затуханием у каждой ноты. Ровный синтезатор дал бы ровно
    тот же отпечаток записи, что и эталон, и кандидат отвергался бы как игра
    под оригинал — что и проверяет `same_record=True`."""
    def run(command, timeout=120):
        command = [str(part) for part in command]
        urls = [part for part in command if "youtube.com/watch" in part]
        if urls:
            # yt-dlp качает ВСЮ волну одним процессом (см. fetch_many), поэтому
            # ссылок в команде бывает несколько, а шаблон имени — с %(id)s.
            template = command[command.index("-o") + 1].replace(".%(ext)s", "")
            saved = 0
            for url in urls:
                video = url.rsplit("=", 1)[-1]
                if downloads is not None:
                    downloads.append(video)
                if video in missing:
                    continue
                stem = template.replace("%(id)s", video)
                with open(f"{stem}.m4a", "wb") as f:
                    f.write(b"audio")
                saved += 1
            return (0 if saved else 1), "", ("" if saved else "Video unavailable")
        source = command[command.index("-i") + 1] if "-i" in command else ""
        target = command[-1]
        if target.endswith(".wav"):
            reference = "ref_" in source.replace("\\", "/").rsplit("/", 1)[-1]
            write_wav(target, _tune(ROOTS) if reference or same_record
                      else _played(tune))
        else:
            with open(target, "wb") as f:
                f.write(b"cut")
        return 0, "", ""
    return run


def service(work, **kwargs):
    return CoverService(fake_run(work, **kwargs), "ffmpeg", ["yt-dlp"],
                        workers=2)


def song_ref():
    import cover_meta
    return cover_meta.song_ref({"annSongId": 7, "songName": "unravel",
                                "songArtist": "TK", "songType": "Opening 1",
                                "animeENName": "Tokyo Ghoul"}, [])


def found(*ids):
    return [{"id": vid, "title": f"unravel cover {n}", "channel": "Кто-то",
             "duration": 200, "views": 5000} for n, vid in enumerate(ids)]


# ── слоты способов подачи ────────────────────────────────────────────────
def test_two_effects_share_the_audio_questions():
    slots = EffectSlots(settings(cover_percent=30, chiptune_enabled=True,
                                 chiptune_percent=20), 10)
    assert slots.slots.count("cover") == 3
    assert slots.slots.count("chiptune") == 2
    assert slots.slots.count("original") == 5


def test_chiptune_alone_keeps_its_old_split():
    """Существующее поведение chiptune правка долей менять не должна."""
    slots = EffectSlots(ap.PackSettings(chiptune_enabled=True,
                                        chiptune_percent=40, chiptune_seed=12), 10)
    assert slots.slots.count("chiptune") == 4
    slots.expand(ap.PackSettings(chiptune_enabled=True, chiptune_percent=40,
                                 chiptune_seed=12), 15)
    assert slots.slots.count("chiptune") == 6


def test_covers_give_up_instead_of_stopping_the_pack():
    """У песни может не быть ни одного кавера — это не повод рушить генерацию."""
    current = settings(cover_percent=100)
    slots = EffectSlots(current, 4)
    for _ in range(slots.limits["cover"]):
        cand = candidate()
        slots.reserve(cand)
        slots.release(cand)
    assert slots.dropped == ["cover"]
    fresh = candidate()
    slots.reserve(fresh)
    assert fresh.music_effect == "original"


def test_a_failing_chiptune_still_raises():
    slots = EffectSlots(ap.PackSettings(chiptune_enabled=True,
                                        chiptune_percent=100), 1)
    cand = candidate()
    cand.music_effect = "chiptune"
    for _ in range(slots.limits["chiptune"] - 1):
        slots.reserve(cand)
        slots.release(cand)
    slots.reserve(cand)
    with pytest.raises(RuntimeError, match="неудачных"):
        slots.release(cand)


def test_cover_audio_file_name_says_it_is_a_cover():
    cand = candidate()
    assert cand.audio_out.endswith("_cover.opus")
    cand.compress_audio = False
    assert cand.audio_out.endswith("_cover.mp3")


# ── сервис ───────────────────────────────────────────────────────────────
def test_reference_chroma_is_computed_once_and_kept(tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return b"amq-mp3"

    first = service(tmp_path).reference("7", fetch, tmp_path)
    again = service(tmp_path).reference("7", fetch, tmp_path)
    assert calls == [1] and np.array_equal(first, again)
    assert cache.ref_chroma("7") is not None


def test_a_candidate_that_does_not_download_is_remembered_as_failed(tmp_path):
    ref = service(tmp_path).reference("7", lambda: b"amq", tmp_path)
    cache.remember_search("7", found("bad"))
    row = cache.screened(cache.load("7"), song_ref())[0][0]
    assert service(tmp_path, missing={"bad"}).audit("7", ref, row, tmp_path) is False
    again = cache.screened(cache.load("7"), song_ref())[0][0]
    assert again["fails"] == 1 and again["checked"] is False


def test_only_the_missing_candidates_are_listened_to(tmp_path):
    """Волна ровно на недостающих: лишний кандидат — это секунды впустую."""
    downloads = []
    ref = service(tmp_path).reference("7", lambda: b"amq", tmp_path)
    cache.remember_search("7", found(*(f"v{n}" for n in range(8))))
    ready = service(tmp_path, downloads=downloads).ensure(
        song_ref(), ref, tmp_path, want=2, seconds=5)
    assert len(ready) >= 2
    assert len(downloads) == 2               # восемь кандидатов не качались


def test_a_narrow_band_keeps_listening_instead_of_settling(tmp_path):
    """Рамка сложности считается ВНУТРИ набора: иначе мы набирали бы три
    подтверждённых кавера и все три выбрасывали как неподходящие."""
    downloads = []
    ref = service(tmp_path).reference("7", lambda: b"amq", tmp_path)
    cache.remember_search("7", found("v0", "v1", "v2"))
    rows = service(tmp_path, downloads=downloads).ensure(
        song_ref(), ref, tmp_path, want=1, seconds=5, keep=lambda row: False)
    assert rows == [] and len(downloads) == 3


def test_a_recording_with_the_original_inside_is_not_confirmed(tmp_path):
    """Игра ПОД ОРИГИНАЛ: гитара или барабаны поверх самого мастера.

    Хрома такую запись пропускает — композиция и правда та же, — а отличить
    её от очень точного кавера может только отпечаток самой записи
    (cover_fingerprint). Сырое число остаётся в кладовой, чтобы правка порога
    не стоила повторной загрузки."""
    ref = service(tmp_path).reference("7", lambda: b"amq", tmp_path)
    cache.remember_search("7", found("v0"))
    rows = service(tmp_path, same_record=True).ensure(
        song_ref(), ref, tmp_path, want=1, seconds=5)
    assert rows == []
    pool, _bad = cache.screened(cache.load("7"), song_ref())
    row = pool[0]
    assert row["checked"] and row["norm"] >= 3.0      # звук: та же композиция
    assert row["audio_reason"] == "original_inside"
    assert row["inside"] > 1.5


def test_a_verdict_survives_the_next_pack_without_a_single_download(tmp_path):
    ref = service(tmp_path).reference("7", lambda: b"amq", tmp_path)
    cache.remember_search("7", found("v0", "v1"))
    service(tmp_path).ensure(song_ref(), ref, tmp_path, want=1, seconds=5)
    downloads = []
    again = service(tmp_path, downloads=downloads).ensure(
        song_ref(), ref, tmp_path, want=1, seconds=5)
    assert again and downloads == []


def test_a_longer_cut_makes_the_windows_be_recounted(tmp_path):
    """Окна считаны под отрезок пака; вырос отрезок — прежние уже не годятся."""
    ref = service(tmp_path).reference("7", lambda: b"amq", tmp_path)
    cache.remember_search("7", found("v0"))
    service(tmp_path).ensure(song_ref(), ref, tmp_path, want=1, seconds=5)
    pool, _bad = cache.screened(cache.load("7"), song_ref())
    assert cache.confirmed(pool, want=5) and not cache.confirmed(pool, want=15)
    assert cache.unchecked(pool, want=15)


# ── загрузчик генератора ─────────────────────────────────────────────────
def generator(tmp_path, **kwargs):
    gen = ap.AnimePackGenerator(settings(**kwargs))
    gen.folder = str(tmp_path)
    (tmp_path / "Audio").mkdir(exist_ok=True)
    gen._get_bytes = lambda url: b"amq-mp3-bytes"
    gen._cover_service = service(tmp_path)
    return gen


def test_download_audio_routes_a_cover_slot_to_the_cover_pipeline(tmp_path):
    cache.remember_search("7", found("v0", "v1"))
    gen = generator(tmp_path)
    cand = candidate()
    assert gen.download_audio(cand) is True
    assert (tmp_path / "Audio" / cand.audio_out).is_file()
    used = cand.music_processing
    assert used["video"] in ("v0", "v1") and used["length"] <= 5
    assert used["url"].endswith(used["video"])
    assert cache.last_used(cache.load("7")) == used["video"]
    assert not list(tmp_path.glob("cover-*"))


def test_a_song_without_a_confirmed_cover_yields_no_file(tmp_path):
    cache.remember_search("7", found("v0"))
    gen = generator(tmp_path)
    gen._cover_service = CoverService(
        fake_run(tmp_path, tune=[61, 63, 66, 70]), "ffmpeg", ["yt-dlp"], workers=2)
    assert gen.download_audio(candidate()) is False
    assert list((tmp_path / "Audio").iterdir()) == []
    assert not list(tmp_path.glob("cover-*"))


def test_the_cover_starts_where_the_original_would_have(tmp_path):
    """prefer = trim_start: у кавера и у оригинала звучит одна часть песни."""
    cache.remember_search("7", found("v0"))
    gen = generator(tmp_path)
    cand = candidate(trim_start=4)
    assert gen.download_audio(cand) is True
    assert abs(cand.music_processing["ref_at"] - 4) <= 1.0


def test_the_pack_says_which_recording_played(tmp_path):
    cache.remember_search("7", found("v0"))
    gen = generator(tmp_path)
    cand = candidate()
    assert gen.download_audio(cand) is True
    packed = gen.write_package([cand], str(tmp_path / "pack.siq"))
    with zipfile.ZipFile(packed) as archive:
        manifest = json.loads(archive.read("covers.json"))
        names = archive.namelist()
        xml = archive.read("content.xml").decode("utf-8")
    row = manifest["questions"][0]
    assert row["file"] == cand.audio_out and row["song"] == "unravel"
    assert row["cover"]["video"] == "v0" and manifest["cut"] == 5
    assert manifest["identity_check"] is True
    assert manifest["similarity_filter"] is True
    # Сам отрезок обязан лежать в паке и быть назван в вопросе.
    assert f"Audio/{cand.audio_out}" in names and cand.audio_out in xml


def test_covers_json_is_absent_when_no_question_used_one(tmp_path):
    gen = generator(tmp_path)
    cand = candidate()
    cand.music_effect = "original"
    gen._get_bytes = lambda url: b"x" * 20000
    gen.download_audio(cand)
    packed = gen.write_package([cand], str(tmp_path / "pack.siq"))
    with zipfile.ZipFile(packed) as archive:
        assert "covers.json" not in archive.namelist()


# ── эффект сдаётся быстро, когда сломан целиком ──────────────────────────
def test_streak_of_failures_drops_the_effect_before_the_whole_budget():
    """384 неудачи на паке в 96 вопросов — это часы перебора каталога.

    Череда неудач подряд не зависит от размера пака: если каверы вообще
    находятся, тридцать промахов подряд без единой удачи не выпадают."""
    from music_effects import FAILURES_STREAK
    slots = EffectSlots(settings(cover_percent=100), 96)
    assert slots.limits["cover"] > FAILURES_STREAK
    for _ in range(FAILURES_STREAK):
        cand = candidate()
        slots.reserve(cand)
        slots.release(cand)
    assert slots.dropped == ["cover"]
    assert slots.failed["cover"] == FAILURES_STREAK


def test_one_success_resets_the_streak():
    from music_effects import FAILURES_STREAK
    slots = EffectSlots(settings(cover_percent=100), 96)
    for _ in range(FAILURES_STREAK * 2):
        cand = candidate()
        slots.reserve(cand)
        slots.succeed(cand)          # вопрос дошёл до пака
        other = candidate()
        slots.reserve(other)
        slots.release(other)
    assert slots.dropped == []


def test_a_broken_youtube_drops_covers_after_a_few_strikes():
    """«Подтвердите, что вы не робот» следующая песня не вылечит.

    Но и одна такая жалоба ещё не приговор: YouTube отвечает так на всплеск
    запросов, и в живом прогоне отвалилась ровно первая песня из восьми."""
    from music_effects import FATAL_STRIKES
    slots = EffectSlots(settings(cover_percent=100), 96)
    for number in range(FATAL_STRIKES):
        cand = candidate()
        slots.reserve(cand)
        cand.music_failure = "YouTube требует войти в аккаунт"
        assert slots.dropped == []
        slots.release(cand)
    assert slots.dropped == ["cover"]
    assert "аккаунт" in slots.reasons["cover"]


def test_a_working_song_resets_the_broken_youtube_strikes():
    """Между жалобами каверы находились — значит, дело было в минуте."""
    from music_effects import FATAL_STRIKES
    slots = EffectSlots(settings(cover_percent=100), 96)
    for _ in range(FATAL_STRIKES * 3):
        cand = candidate()
        slots.reserve(cand)
        cand.music_failure = "YouTube требует войти в аккаунт"
        slots.release(cand)
        good = candidate()
        slots.reserve(good)
        slots.succeed(good)
    assert slots.dropped == []


def test_slots_returned_after_the_effect_gave_up_play_the_original():
    """Слот, качавшийся в момент отказа, не должен вернуться кавером.

    Живой прогон: восемь занятых слотов крутились кавером до конца каталога —
    860 годных тайтлов сгорело, вопросов вышло 63 из 96."""
    slots = EffectSlots(settings(cover_percent=100), 96)
    busy = [candidate() for _ in range(8)]
    for cand in busy:
        slots.reserve(cand)
    for cand in busy:
        cand.music_failure = "YouTube требует войти в аккаунт"
        slots.release(cand)
    assert slots.dropped == ["cover"]
    assert slots.slots.count("cover") == 0
    fresh = candidate()
    slots.reserve(fresh)
    assert fresh.music_effect == "original"


def test_a_taken_place_returns_the_slot_without_a_failure():
    """Вопрос готов, а квоту заняли другие: слот вернуть, неудачу не считать."""
    slots = EffectSlots(settings(cover_percent=100), 4)
    cand = candidate()
    slots.reserve(cand)
    slots.give_back(cand)
    assert len(slots.free) == 4
    assert slots.failed == {}


def test_fatal_reason_tells_a_broken_youtube_from_a_songless_one():
    from cover_search import fatal_reason
    assert fatal_reason("Sign in to confirm you're not a bot. See "
                        "how-do-i-pass-cookies-to-yt-dlp")
    assert fatal_reason("yt-dlp не найден — каверы качать нечем.")
    assert not fatal_reason("ffmpeg не разобрал звук")
    assert not fatal_reason("")


def test_a_blocked_youtube_does_not_poison_the_cache(tmp_path):
    """Иначе один заблокированный прогон пометил бы негодными всех кандидатов."""
    def run(command, timeout=120):
        return 1, "", "ERROR: Sign in to confirm you're not a bot"

    service = CoverService(run, "ffmpeg", ["yt-dlp"])
    row = {"id": "vid1", "title": "unravel cover", "strength": "strong"}
    with pytest.raises(RuntimeError):
        service.audit("song-1", np.zeros((12, 10)), row, tmp_path, 5.0)
    assert not cache.load("song-1").get("fail")


# ── стенка YouTube против осечки ролика ──────────────────────────────────
RATE_LIMITED = (
    "ERROR: [youtube] v0: This content isn't available, try again later. "
    "Use --cookies-from-browser or --cookies for the authentication.")


def test_a_wave_that_falls_whole_does_not_blame_the_videos(tmp_path):
    """Ни один ролик волны не скачался — про ролики это не говорит ничего.

    Режущий по частоте YouTube отвечает «Video unavailable» и живому ролику:
    живой прогон так пометил 362 кандидата, у 18 песен — все двенадцать разом,
    и те отчитались «подходящих исполнений не нашлось»."""
    ref = service(tmp_path).reference("7", lambda: b"amq", tmp_path)
    ids = [f"v{n}" for n in range(4)]
    cache.remember_search("7", found(*ids))
    ready = service(tmp_path, missing=set(ids)).ensure(
        song_ref(), ref, tmp_path, want=2, seconds=5)
    assert ready == []
    assert not (cache.load("7").get("fail") or {})


def test_a_video_that_falls_while_its_neighbours_arrive_is_blamed(tmp_path):
    """Осечка ролика видна только тогда, когда соседи по волне скачались."""
    ref = service(tmp_path).reference("7", lambda: b"amq", tmp_path)
    cache.remember_search("7", found("v0", "v1"))
    service(tmp_path, missing={"v1"}).ensure(song_ref(), ref, tmp_path,
                                             want=2, seconds=5)
    rows = {row["id"]: row for row in cache.screened(cache.load("7"),
                                                     song_ref())[0]}
    assert rows["v1"]["fails"] == 1
    assert rows["v0"]["fails"] == 0


def test_a_rate_limited_wave_gives_up_at_once(tmp_path):
    """Стенку по частоте нельзя перебирать кандидатами: ответ у YouTube на все
    запросы один и тот же, а каждая попытка стоит тайтла из каталога."""
    import cover_search

    ref = service(tmp_path).reference("7", lambda: b"amq", tmp_path)
    cache.remember_search("7", found("v0", "v1", "v2"))

    def wall(command, timeout=120):
        return 1, "", RATE_LIMITED

    covers = CoverService(wall, "ffmpeg", ["yt-dlp"], workers=2,
                          rate_limit_retries=0)
    with pytest.raises(RuntimeError) as caught:
        covers.ensure(song_ref(), ref, tmp_path, want=2, seconds=5)
    assert cover_search.fatal_reason(caught.value) == cover_search.RATE_LIMIT
    assert not (cache.load("7").get("fail") or {})


# ── частота запросов ─────────────────────────────────────────────────────
def test_probe_downloads_ask_yt_dlp_to_pace_itself(tmp_path):
    commands = []

    def run(command, timeout=120):
        commands.append([str(part) for part in command])
        return 1, "", "Video unavailable"

    covers = CoverService(run, "ffmpeg", ["yt-dlp"], workers=2)
    with pytest.raises(RuntimeError):
        covers.fetch_many(["v0"], tmp_path)
    assert commands[-1].count("--sleep-requests") == 1


def test_only_a_few_yt_dlp_go_to_youtube_at_once(tmp_path):
    """Ограничитель сети.

    Потоков у генератора столько же, сколько вопросов качается разом
    (parallel, обычно 8), и раньше все восемь ломились на YouTube — с такого
    напора и начался живой отказ по частоте. Пауза внутри процесса тут не
    помогает: она держит частоту ОДНОГО yt-dlp."""
    live, peak, guard = [0], [0], threading.Lock()

    def run(command, timeout=120):
        with guard:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with guard:
            live[0] -= 1
        return 1, "", "Video unavailable"

    covers = CoverService(run, "ffmpeg", ["yt-dlp"], workers=16)

    def probe(number):
        try:
            covers.fetch_many([f"v{number}"], tmp_path)
        except RuntimeError:
            pass

    jobs = [threading.Thread(target=probe, args=(n,)) for n in range(12)]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join()
    assert peak[0] == cover_service.NET_LIMIT


def test_rate_limit_waits_and_retries_inside_the_network_slot(tmp_path):
    attempts = []

    def run(command, timeout=120):
        attempts.append(command)
        if len(attempts) == 1:
            return 1, "", RATE_LIMITED
        return 0, "ready", ""

    covers = CoverService(run, "ffmpeg", ["yt-dlp"], workers=8,
                          rate_limit_cooldown=0, rate_limit_retries=2)
    assert covers.net_run(["yt-dlp"], 120) == (0, "ready", "")
    assert len(attempts) == 2


def test_the_limiter_never_outgrows_the_pool(tmp_path):
    """Одному потоку — один yt-dlp: во вкладке прослушивания сервис живёт с
    workers=1, и ограничитель не должен обещать ему больше."""
    covers = CoverService(lambda *a: (0, "", ""), "ffmpeg", ["yt-dlp"],
                          workers=1)
    assert covers._net._value == 1


def test_the_limiter_can_be_relaxed_for_metadata_only_mode():
    covers = CoverService(lambda *a: (0, "", ""), "ffmpeg", ["yt-dlp"],
                          workers=8, net_limit=4)
    assert covers.net_limit == 4
