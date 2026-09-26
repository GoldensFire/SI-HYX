# -*- coding: utf-8 -*-
"""Поиск кандидатов: запросы, разбор вывода yt-dlp, дедуп, ступени.

Сети здесь нет и быть не может (tests/conftest.py её рубит): yt-dlp подменяется
вызываемым объектом, как chiptune подменяет свой раннер.
"""
import json

import cover_search
from cover_meta import song_ref

YTDLP = ["yt-dlp"]


def _song(name="Nameless Heart", anime="Rokka no Yuusha", artist="Aoi Yuki"):
    return song_ref({"annSongId": 14790, "songName": name, "songArtist": artist,
                     "songType": "Ending 3", "animeENName": anime,
                     "animeJPName": anime, "animeAltName": []})


class FakeYtdlp:
    """Возвращает по строке JSON на каждый результат и помнит все вызовы."""

    def __init__(self, per_query):
        self.per_query = per_query
        self.queries = []
        self.commands = []

    def __call__(self, cmd, timeout=90):
        query = next(a for a in cmd if a.startswith("ytsearch"))
        self.queries.append(query)
        self.commands.append([str(part) for part in cmd])
        rows = self.per_query.get(query.split(":", 1)[1], [])
        return 0, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), ""


def _row(vid, title, duration=100, channel="ch", views=5000):
    return {"id": vid, "title": title, "duration": duration, "channel": channel,
            "view_count": views}


# ── запросы ──────────────────────────────────────────────────────────────
def test_queries_are_anchored_on_the_song_name():
    """Запрос по аниме и позиции приносит каверы ДРУГИХ его OP/ED — на живом
    поиске «Rokka no Yuusha ending cover» вернул каверы ED1, ED2, ED3 и ещё
    опенинга. Поэтому во всех запросах якорь — название песни."""
    rows = cover_search.queries(_song())
    assert all("Nameless Heart" in q for q, _limit, _stage in rows)
    assert [stage for _q, _l, stage in rows] == [1, 2, 3]
    assert "Rokka no Yuusha" in rows[0][0]
    assert "Aoi Yuki" in rows[2][0]


def test_no_song_name_means_no_search():
    assert cover_search.queries(_song(name="")) == []


# ── разбор вывода ────────────────────────────────────────────────────────
def test_search_parses_jsonl_and_ignores_noise():
    fake = FakeYtdlp({"q": [_row("a", "первый"), _row("b", "второй")]})
    out = cover_search.search("q", 5, lambda cmd, t: (
        0, "WARNING: что-то\n" + "".join(
            json.dumps(r) + "\n" for r in fake.per_query["q"]) + "не json\n", ""),
        YTDLP)
    assert [r["id"] for r in out] == ["a", "b"]
    assert out[0]["duration"] == 100 and out[0]["channel"] == "ch"


def test_search_reports_a_failure_without_output():
    def broken(cmd, timeout):
        return 1, "", "no such option: --nope"
    try:
        cover_search.search("q", 5, broken, YTDLP)
    except RuntimeError as error:
        assert "no such option" in str(error)
    else:
        raise AssertionError("ошибка yt-dlp должна доходить до вызывающего")


def test_search_needs_a_ytdlp_command():
    assert cover_search.search("q", 5, lambda *a: (0, "", ""), None) == []


# ── дедуп ────────────────────────────────────────────────────────────────
def test_dedup_removes_reuploads_and_live():
    rows = [
        _row("a", "Nameless Heart cover", 100, "one"),
        _row("a", "Nameless Heart cover", 100, "one"),          # тот же id
        _row("b", "NAMELESS HEART - cover!", 100, "one"),       # тот же заголовок
        _row("d", "трансляция", 140, "two"),
    ]
    rows[3]["live_status"] = "is_live"
    out = cover_search.dedup(rows)
    assert [r["id"] for r in out] == ["a"]
    # Тот же заголовок у ДРУГОГО канала — это не перезалив.
    other = cover_search.dedup([_row("a", "Nameless Heart cover", 100, "one"),
                                _row("e", "Nameless Heart cover", 100, "two")])
    assert [r["id"] for r in other] == ["a", "e"]


def test_dedup_keeps_different_covers_of_one_channel():
    """Плодовитый канал выкладывает десятки РАЗНЫХ каверов, и длительности у них
    сплошь близкие. На 722 собранных строках правило «канал + длительность» не
    убрало ничего, зато здесь отняло бы семь настоящих кандидатов."""
    rows = [_row(f"v{n}", f"Nameless Heart piano cover part {n}", 100 + n, "one")
            for n in range(8)]
    assert len(cover_search.dedup(rows)) == 8


# ── ступени ──────────────────────────────────────────────────────────────
def test_third_stage_runs_only_when_the_pool_is_small():
    song = _song()
    first, second, third = (q for q, _l, _s in cover_search.queries(song))
    many = [_row(f"v{n}", f"Nameless Heart piano cover {n}", 100 + n)
            for n in range(8)]
    def asked(fake, query):
        return any(query in recorded for recorded in fake.queries)

    fat = FakeYtdlp({first: many, second: [], third: [_row("z", "ещё")]})
    result = cover_search.gather(song, fat, YTDLP)
    assert result["queries"] == [first, second] and not asked(fat, third)
    assert len(result["pool"]) == 8

    thin = FakeYtdlp({first: many[:2], second: [],
                      third: [_row("z", "Nameless Heart guitar cover", 150)]})
    result = cover_search.gather(song, thin, YTDLP)
    assert asked(thin, third)
    assert "z" in [r["id"] for r in result["pool"]]


def test_gather_separates_rejected_and_counts_found():
    song = _song()
    first = cover_search.queries(song)[0][0]
    fake = FakeYtdlp({first: [_row("a", "Nameless Heart piano cover"),
                              _row("b", "Nameless Heart REACTION", 300),
                              _row("c", "Nameless Heart", 223,
                                   channel="Aoi Yuki - Topic")]})
    result = cover_search.gather(song, fake, YTDLP)
    assert [r["id"] for r in result["pool"]] == ["a"]
    assert {r["reason"] for r in result["rejected"]} == {"reaction",
                                                        "official_channel"}
    assert result["found"] == 3


def test_stop_flag_breaks_out_before_the_first_query():
    fake = FakeYtdlp({})
    result = cover_search.gather(_song(), fake, YTDLP, stopped=lambda: True)
    assert fake.queries == [] and result["pool"] == []


# ── отказ по частоте запросов ────────────────────────────────────────────
RATE_LIMITED = (
    "ERROR: [youtube] mncV_lY-8LU: This content isn't available, try again "
    "later. Use --cookies-from-browser or --cookies for the authentication. "
    "Use `--sleep-requests 1.25` to add a delay between video requests to "
    "avoid exceeding the rate limit. For more information, refer to "
    "https://github.com/yt-dlp/yt-dlp/wiki/Extractors"
    "#this-content-isnt-available-try-again-later")


def test_rate_limit_is_a_broken_search_not_a_bad_video():
    """Живой прогон: шесть минут ровных загрузок, потом стенка и 48 каверов
    из 96. Отказ по частоте следующая песня не вылечит, и перебирать его
    кандидатами нельзя — это сотни сожжённых тайтлов."""
    assert cover_search.fatal_reason(RATE_LIMITED) == cover_search.RATE_LIMIT
    assert cover_search.fatal_reason("ERROR: HTTP Error 429: Too Many Requests")
    assert cover_search.fatal_reason("ERROR: Video unavailable") == ""


def test_trimming_keeps_the_rate_limit_mark():
    """Прежний хвост в 200 символов оставлял «…delay between video requests…»
    — примету, которой fatal_reason не видел, и стенка попадала в кладовую как
    неудача конкретного ролика."""
    short = cover_search.trim_error(RATE_LIMITED)
    assert len(short) <= 200
    assert cover_search.fatal_reason(short) == cover_search.RATE_LIMIT


def test_a_failed_search_keeps_the_mark_too():
    """Ошибку поиска тоже нельзя резать с хвоста: она приходит той же стенкой."""
    def wall(cmd, timeout=90):
        return 1, "", RATE_LIMITED

    try:
        cover_search.search_many([("unravel cover", 20)], wall, YTDLP)
    except RuntimeError as error:
        assert cover_search.fatal_reason(error) == cover_search.RATE_LIMIT
    else:
        raise AssertionError("поломка поиска должна долетать исключением")


def test_search_asks_yt_dlp_to_pace_itself():
    fake = FakeYtdlp({})
    cover_search.search_many([("unravel cover", 20)], fake, YTDLP)
    assert fake.commands[-1].count("--sleep-requests") == 1
