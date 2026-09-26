# -*- coding: utf-8 -*-
"""Диалоги из SubDL: русские субтитры первыми, Jimaku — после квоты."""
from contextlib import nullcontext
import io
import random
import threading
import zipfile

import animepack as ap
import animepack_api as api

RU_SRT = """1
00:01:00,000 --> 00:01:02,000
Почему ты вернулся сюда так поздно?

2
00:01:02,200 --> 00:01:04,000
Потому что я обещал найти правду в старом доме.

3
00:01:04,100 --> 00:01:06,000
Тогда мы откроем старую дверь вместе.
""".encode("cp1251")


class Response:
    def __init__(self, data=None, status=200, content=b""):
        self._data = data
        self.status_code = status
        self.content = content

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buf.getvalue()


class Session:
    def __init__(self, search=None, archive=None, status=200):
        self.calls = []
        self.search = search
        self.archive = archive
        self.status = status

    def get(self, url, params=None, **_kwargs):
        self.calls.append((url, dict(params or {})))
        if self.status != 200:
            return Response(self.search, status=self.status)
        if url.endswith("/subtitles"):
            return Response(self.search)
        return Response(content=self.archive)


SEARCH = {"status": True, "subtitles": [
    {"language": "RU", "season": 3, "episode": 13, "episode_from": 13,
     "episode_end": 13, "full_season": False, "url": "/subtitle/1-2.zip",
     "subtitlePage": "/s/info/abc/ep13", "release_name": "Show S03E13"},
    {"language": "RU", "season": 3, "full_season": True,
     "url": "/subtitle/3-4.zip", "release_name": "Show S03 pack"},
    {"language": "RU", "season": 3, "episode_from": 13, "episode_end": 22,
     "url": "/subtitle/5-6.zip", "release_name": "Show 13-22"},
    {"language": "EN", "season": 3, "episode": 13,
     "url": "/subtitle/7-8.zip", "release_name": "Show S03E13 EN"},
]}


def test_only_russian_single_episode_files_are_kept():
    session = Session(SEARCH)
    client = api.SubdlApi("key", session)
    files = client.episode_files({"imdb_id": "tt2560140"}, 3, 13)
    assert [f["url"] for f in files] == ["/subtitle/1-2.zip"]
    assert files[0]["page"] == "https://subdl.com/s/info/abc/ep13"
    url, params = session.calls[0]
    assert url == "https://api.subdl.com/api/v1/subtitles"
    assert params["imdb_id"] == "tt2560140" and params["languages"] == "RU"
    assert (params["season_number"], params["episode_number"]) == (3, 13)
    assert "key" not in files[0]["page"]


def test_archive_member_of_this_episode_is_taken():
    archive = _zip({"Show - 12.srt": b"x", "Show - 13.srt": RU_SRT,
                    "readme.txt": b"hi"})
    client = api.SubdlApi("key", Session(archive=archive))
    data, name = client.download({"url": "/subtitle/1-2.zip", "episode": 13})
    assert (data, name) == (RU_SRT, "Show - 13.srt")


def test_daily_limit_is_a_quota_error():
    client = api.SubdlApi("key", Session({"error": "daily_limit"}, status=429))
    try:
        client.episode_files({"imdb_id": "tt1"}, 1, 1)
    except api.SubdlQuotaError:
        pass
    else:
        raise AssertionError("квота не распознана")


class AniZip:
    def anilist_id(self, _mal):
        return 99

    def episode_numbers(self, _mal):
        return [13]

    def tv_episodes(self, _mal):
        return [{"season": 3, "episode": 13}]

    def external_ids(self, _mal):
        return {"imdb_id": "tt2560140", "tmdb_id": "1429"}


def _gen(subdl, jimaku=None, gemini=None):
    gen = object.__new__(ap.AnimePackGenerator)
    gen.subdl, gen.jimaku, gen.gemini = subdl, jimaku, gemini
    gen.anizip = AniZip()
    gen.rng = random.Random(0)
    gen._dialogue_lock = threading.Lock()
    gen._dialogue_seen = set()
    gen._timed = lambda _name: nullcontext()
    gen.dropped = []
    gen._drop_kind = gen.dropped.append
    gen._log_rare = lambda *_args: None
    gen.logs = []
    gen.log = gen.logs.append
    return gen


def _anime():
    return {"malId": 1, "name": "Test", "russian": "Тест", "english": "Test",
            "kind": "tv", "score": 8.0, "airedOn": {"year": 2020},
            "synonyms": []}


class Refusing:
    def generate_json(self, *_args, **_kwargs):
        raise AssertionError("сюда Gemini звать не должны")


class Choosing:
    """Gemini, выбирающий реплики 1–2 серии: текст эхом, без имён."""

    def __init__(self, found=True):
        self.found = found
        self.prompts = []

    def generate_json(self, prompt, _schema, temperature=0.0):
        self.prompts.append(prompt)
        return {"found": self.found, "start": 1, "count": 2, "clue": "дом",
                "lines": [{"translation": "как есть", "contains_name": False},
                          {"translation": "как есть", "contains_name": False}]}


def test_subdl_dialogue_is_chosen_by_gemini_from_the_whole_episode():
    class Subdl:
        def episode_files(self, ids, season, episode):
            assert ids["imdb_id"] == "tt2560140" and (season, episode) == (3, 13)
            return [{"url": "/subtitle/1-2.zip", "episode": 13,
                     "page": "https://subdl.com/s/info/abc/ep13"}]

        def download(self, _file):
            return RU_SRT, "Show - 13.srt"

    gemini = Choosing()
    gen = _gen(Subdl(), gemini=gemini)
    cand = ap.SongCandidate({}, _anime(), kind=ap.DIALOGUE_KIND)
    assert ap.AnimePackGenerator.make_dialogue_question(gen, cand)
    assert cand.dialogue_episode == 13
    # Модель видела ВСЮ серию, а текст взят из субтитров по её номерам —
    # «как есть» из её ответа в вопрос не попадает.
    prompt = gemini.prompts[0]
    assert "0: Почему ты вернулся" in prompt and "2: Тогда мы откроем" in prompt
    assert cand.dialogue_text == (
        "— Потому что я обещал найти правду в старом доме.\n"
        "— Тогда мы откроем старую дверь вместе.")
    assert cand.source_link == "https://subdl.com/s/info/abc/ep13"


def test_episode_without_a_recognisable_excerpt_gives_no_question():
    class Subdl:
        def episode_files(self, *_args):
            return [{"url": "/subtitle/1-2.zip", "episode": 13, "page": ""}]

        def download(self, _file):
            return RU_SRT, "Show - 13.srt"

    gemini = Choosing(found=False)
    gen = _gen(Subdl(), gemini=gemini)
    cand = ap.SongCandidate({}, _anime(), kind=ap.DIALOGUE_KIND)
    assert not ap.AnimePackGenerator.make_dialogue_question(gen, cand)
    assert len(gemini.prompts) == 1


def test_dialogues_without_gemini_are_dropped():
    gen = _gen(object())
    cand = ap.SongCandidate({}, _anime(), kind=ap.DIALOGUE_KIND)
    assert not ap.AnimePackGenerator.make_dialogue_question(gen, cand)
    assert gen.dropped == [ap.DIALOGUE_KIND]


def test_after_the_quota_jimaku_takes_over():
    class Spent:
        def episode_files(self, *_args):
            raise api.SubdlQuotaError("суточная квота ключа SubDL исчерпана")

    class Jimaku:
        asked = False

        def entry(self, _aid):
            Jimaku.asked = True
            return {}

    gen = _gen(Spent(), jimaku=Jimaku(), gemini=Refusing())
    cand = ap.SongCandidate({}, _anime(), kind=ap.DIALOGUE_KIND)
    assert not ap.AnimePackGenerator.make_dialogue_question(gen, cand)
    assert gen.subdl is None and Jimaku.asked
    assert any("Jimaku" in line for line in gen.logs)
    assert not gen.dropped


def test_quota_without_jimaku_drops_dialogues():
    class Spent:
        def episode_files(self, *_args):
            raise api.SubdlQuotaError("квота")

    gen = _gen(Spent())
    cand = ap.SongCandidate({}, _anime(), kind=ap.DIALOGUE_KIND)
    assert not ap.AnimePackGenerator.make_dialogue_question(gen, cand)
    assert gen.dropped == [ap.DIALOGUE_KIND]


def test_subdl_dialogues_need_gemini_to_choose_the_excerpt():
    settings = ap.PackSettings(pct_songs=0, pack_dialogue=True,
                               pct_dialogue=100, subdl_key="s")
    problems = " ".join(settings.validate())
    assert "Gemini" in problems and "Jimaku" not in problems
    settings.gemini_key = "g"
    assert "Gemini" not in " ".join(settings.validate())
    settings.subdl_key = ""
    problems = " ".join(settings.validate())
    assert "SubDL" in problems and "Jimaku" in problems
