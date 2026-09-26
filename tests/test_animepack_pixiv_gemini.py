# -*- coding: utf-8 -*-
import base64

from si_hyx_parts.animepack.pixiv_visual_check import check


class _Cache:
    def __init__(self):
        self.rows = {}

    def memo(self, group, key, _age=0):
        return self.rows.get((group, key))

    def remember_memo(self, group, key, value):
        self.rows[(group, key)] = value


class _Gemini:
    model = "gemini-test"

    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []

    def generate_json(self, prompt, schema, temperature=0):
        self.calls.append((prompt, schema, temperature))
        return self.verdict


class _Generator:
    def __init__(self, verdict):
        self.gemini_pixiv = _Gemini(verdict)
        self.db_cache = _Cache()


class _Candidate:
    anime = {"russian": "Клинок, рассекающий демонов",
             "name": "Kimetsu no Yaiba", "english": "Demon Slayer",
             "synonyms": ["Blade of Demon Destruction"]}


def test_gemini_receives_the_image_and_pixiv_tags():
    gen = _Generator({"accept": True, "has_title_text": False,
                      "mixed_anime": False, "reason": "один тайтл"})
    data = b"image bytes"
    ok, _reason = check(gen, _Candidate(), data, ".png", {
        "tags": [{"name": "鬼滅の刃"}, {"name": "竈門炭治郎"}]})
    assert ok
    prompt = gen.gemini_pixiv.calls[0][0]
    assert prompt[0]["type"] == "text"
    assert "Kimetsu no Yaiba" in prompt[0]["text"]
    assert "竈門炭治郎" in prompt[0]["text"]
    assert prompt[1] == {"type": "image", "mime_type": "image/png",
                         "data": base64.b64encode(data).decode("ascii")}


def test_title_text_or_another_anime_rejects_and_is_cached():
    gen = _Generator({"accept": True, "has_title_text": True,
                      "mixed_anime": True, "reason": "виден логотип"})
    assert check(gen, _Candidate(), b"same", ".jpg")[0] is False
    assert check(gen, _Candidate(), b"same", ".jpg")[0] is False
    assert len(gen.gemini_pixiv.calls) == 1


# ── Отказ Gemini — повод взять другой арт того же тайтла ─────────────────────
class _SeqPixiv:
    """Отдаёт арты по очереди и помнит, какие адреса ему запретили."""
    r18_mode = ai_mode = "exclude"
    last_card = last_illust = None
    last_link = ""

    def __init__(self, count):
        self.left = [(f"art{i}".encode(), ".png",
                      f"https://i.pximg.net/art{i}.png") for i in range(count)]
        self.excluded = []

    def fetch(self, anime, excluded=(), also=(), skip_links=()):
        self.excluded.append(set(excluded))
        return self.left.pop(0)


class _Verdicts:
    model = "gemini-test"

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = 0

    def generate_json(self, prompt, schema, temperature=0):
        self.calls += 1
        ok = self.verdicts.pop(0)
        return {"accept": ok, "has_title_text": not ok,
                "mixed_anime": False, "reason": "видна надпись"}


def _pixiv_gen(tmp_path, monkeypatch, pixiv, verdicts):
    import animepack
    from animepack import PackSettings
    settings = PackSettings(
        pct_songs=0, pack_pixiv_art=True, pct_pixiv_art=100,
        pixiv_refresh_token="refresh-secret", pixiv_gemini_check=True,
        out_dir=str(tmp_path))
    gen = animepack.AnimePackGenerator(
        settings, session=object(), amq=object(), anisong=object(),
        shikimori=object(), mal=object(), tmdb=object(), pixiv=pixiv)
    gen.prepare_dirs()
    gen.gemini_pixiv = _Verdicts(verdicts)
    monkeypatch.setattr(gen, "_poster_bytes", lambda *args: (b"", ""))
    monkeypatch.setattr(gen, "_to_avif", lambda data, name, ext: True)
    return gen


def test_a_rejected_art_is_replaced_by_another_of_the_same_title(
        tmp_path, monkeypatch):
    from animepack import PIXIV_ART_KIND, SongCandidate
    from test_animepack_new_kinds import make_anime
    pixiv = _SeqPixiv(3)
    gen = _pixiv_gen(tmp_path, monkeypatch, pixiv, [False, True])
    anime = make_anime()
    cand = SongCandidate({}, anime, kind=PIXIV_ART_KIND)
    assert gen._fetch_media(cand)
    assert cand.anime is anime                      # тайтл тот же
    assert cand.frame_url.endswith("art1.png")      # а арт — следующий
    assert any("art0" in url for url in pixiv.excluded[1])
    assert gen.gemini_pixiv.calls == 2


def test_rejections_stop_after_a_few_tries(tmp_path, monkeypatch):
    from animepack import PIXIV_ART_KIND, SongCandidate
    from si_hyx_parts.animepack.pixiv_art_generation import VISUAL_TRIES
    from test_animepack_new_kinds import make_anime
    pixiv = _SeqPixiv(VISUAL_TRIES + 2)
    gen = _pixiv_gen(tmp_path, monkeypatch, pixiv,
                     [False] * (VISUAL_TRIES + 2))
    cand = SongCandidate({}, make_anime(), kind=PIXIV_ART_KIND)
    assert not gen._fetch_media(cand)
    assert gen.gemini_pixiv.calls == VISUAL_TRIES
