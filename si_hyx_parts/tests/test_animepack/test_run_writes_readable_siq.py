# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_run_writes_readable_siq. Public namespace: test_animepack."""
import test_animepack as _api


def test_run_writes_readable_siq(tmp_path, monkeypatch):
    """Готовый .siq должен читаться разборщиком самого приложения, и все
    ссылки на медиа — существовать внутри архива."""
    s = _api.PackSettings(rounds=1, themes=1, questions=2, openings=2, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, title="Тест пак",
                     out_dir=str(tmp_path),
                     users=[_api.UserList("morr", "myanimelist", ["completed"])])
    pairs = [_api._pair(i, f"fr{i}") for i in (1, 2)]
    gen = _api._generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": [1, 2]})

    def fake_fetch(cand):
        audio = _api.os.path.join(gen.folder, "Audio", cand.audio_out)
        with open(audio, "wb") as f:
            f.write(b"\x00" * 32)
        poster = _api.os.path.join(gen.folder, "Images", cand.poster_file)
        with open(poster, "wb") as f:
            f.write(b"\x00" * 16)
        cand.has_poster = True
        return True

    monkeypatch.setattr(gen, "_fetch_media", fake_fetch)
    result = gen.run()
    assert result.path.endswith(".siq") and _api.os.path.exists(result.path)
    assert len(result.songs) == 2

    with _api.zipfile.ZipFile(result.path) as zf:
        names = set(zf.namelist())
        assert "content.xml" in names
        xml = zf.read("content.xml")
        root, ns = _api._parse(xml)
        for item in root.findall(".//s:item[@isRef='True']", ns):
            folder = "Audio" if item.get("type") == "audio" else "Images"
            assert f"{folder}/{item.text}" in names

    # Разборщик приложения (SiQuesterHYX) должен понять пакет.
    from siquester.siq_package import SiqPackage
    pkg = SiqPackage(result.path)
    assert sum(len(t.get("questions", ())) for r in pkg.rounds
               for t in r.get("themes", ())) == 2
    assert gen.folder == ""            # временная папка убрана

test_run_writes_readable_siq.__module__ = _api.__name__
_api.test_run_writes_readable_siq = test_run_writes_readable_siq

def test_run_refuses_broken_settings():
    from animepack import AnimePackError
    s = _api.PackSettings(openings=0, endings=0, inserts=0)
    gen = _api.AnimePackGenerator(s, session=object())
    with _api.pytest.raises(AnimePackError):
        gen.run()

test_run_refuses_broken_settings.__module__ = _api.__name__
_api.test_run_refuses_broken_settings = test_run_refuses_broken_settings

# ── Тег песни в ответе («Название OP1 (2010)») ───────────────────────────────
@_api.pytest.mark.parametrize("song_type,tag", [
    ("Opening 1", "OP1"), ("Ending 12", "ED12"), ("Insert Song", "OST"),
    ("Opening", "OP"), ("Что-то", ""), (None, ""),
])
def test_song_tag(song_type, tag):
    assert _api.song_tag(song_type) == tag

test_song_tag.__module__ = _api.__name__
_api.test_song_tag = test_song_tag

def test_answer_tag_goes_before_year():
    """Просьба пользователя: в ответе видно, опенинг это, эндинг или вставка."""
    cand = _api.make_candidate(song={"songType": "Ending 2"})
    assert cand.main_answer == "Тетрадь смерти ED2 (2006) — 『the WORLD』"
    # Год, уже записанный Shikimori в название, не задваивается и остаётся
    # последним — тег встаёт перед ним.
    old = _api.make_candidate(song={"songType": "Insert Song"},
                         anime={"russian": "Могучий Атом (2003)",
                                "airedOn": {"year": 2003}})
    assert old.main_answer == "Могучий Атом OST (2003) — 『the WORLD』"
    # У вопроса-кадра песни нет — нет и тега.
    frame = _api.make_candidate()
    frame.kind = _api.FRAME_KIND
    assert frame.tag == "" and frame.main_answer == "Тетрадь смерти (2006)"

test_answer_tag_goes_before_year.__module__ = _api.__name__
_api.test_answer_tag_goes_before_year = test_answer_tag_goes_before_year

# ── Выбор кадра: случайный и без повторов ────────────────────────────────────
def _frame_cand(anime=None):
    return _api.SongCandidate(song={}, anime=anime or _api.make_anime(), kind=_api.FRAME_KIND)

_frame_cand.__module__ = _api.__name__
_api._frame_cand = _frame_cand

def test_frame_pick_is_random_and_unique_within_pack():
    s = _api.PackSettings(pct_songs=0, pct_frames=100)
    gen = _api._generator(s, [], [])
    cand = _api._frame_cand()
    picked = [gen._pick_frame_url(cand) for _ in range(6)]
    assert len(set(picked)) == 6          # шесть скриншотов — шесть разных
    # Кадры кончились, но памяти о прошлых паках нет — берём по кругу.
    assert gen._pick_frame_url(cand)

test_frame_pick_is_random_and_unique_within_pack.__module__ = _api.__name__
_api.test_frame_pick_is_random_and_unique_within_pack = test_frame_pick_is_random_and_unique_within_pack

def test_frame_pick_never_repeats_within_pack():
    """Кадр всегда случайный (настройки «первый кадр» больше нет), но дважды
    один и тот же в паке не берётся."""
    s = _api.PackSettings(pct_songs=0, pct_frames=100)
    gen = _api._generator(s, [], [])
    cand = _api._frame_cand()
    seen = {gen._pick_frame_url(cand) for _ in range(6)}
    assert len(seen) == 6

test_frame_pick_never_repeats_within_pack.__module__ = _api.__name__
_api.test_frame_pick_never_repeats_within_pack = test_frame_pick_never_repeats_within_pack

def test_frames_no_repeat_skips_history(tmp_path):
    path = str(tmp_path / "frames.json")
    _api.save_frame_history(["https://shiki/0.jpg", "https://shiki/1.jpg"], path)
    s = _api.PackSettings(pct_songs=0, pct_frames=100, frames_no_repeat=True)
    gen = _api._generator(s, [], [], frames_history_path=path)
    # Кадр случайный, но из тех, что в истории ещё не были.
    assert gen._pick_frame_url(_api._frame_cand()) in {
        f"https://shiki/{i}.jpg" for i in range(2, 6)}

test_frames_no_repeat_skips_history.__module__ = _api.__name__
_api.test_frames_no_repeat_skips_history = test_frames_no_repeat_skips_history

def test_frames_no_repeat_drops_title_without_fresh_frames(tmp_path):
    path = str(tmp_path / "frames.json")
    _api.save_frame_history([f"https://shiki/{i}.jpg" for i in range(6)], path)
    s = _api.PackSettings(pct_songs=0, pct_frames=100, frames_no_repeat=True)
    gen = _api._generator(s, [], [], frames_history_path=path)
    # Свободных кадров нет — вопроса не будет, пак возьмёт другой тайтл.
    assert gen._pick_frame_url(_api._frame_cand()) == ""

test_frames_no_repeat_drops_title_without_fresh_frames.__module__ = _api.__name__
_api.test_frames_no_repeat_drops_title_without_fresh_frames = test_frames_no_repeat_drops_title_without_fresh_frames

def test_save_frames_history_appends_used_only(tmp_path):
    path = str(tmp_path / "frames.json")
    s = _api.PackSettings(pct_songs=0, pct_frames=100, frames_no_repeat=True)
    gen = _api._generator(s, [], [], frames_history_path=path)
    used = _api._frame_cand()
    used.frame_url, used.has_frame = "https://shiki/3.jpg?ts=1", True
    lost = _api._frame_cand()
    lost.frame_url = "https://shiki/4.jpg"      # кадр не скачался
    gen.save_frames_history([used, lost])
    assert _api.load_frame_history(path) == ["https://shiki/3.jpg"]  # ?query отброшен

    # Без галочки история не пишется вовсе.
    s2 = _api.PackSettings(pct_songs=0, pct_frames=100)
    gen2 = _api._generator(s2, [], [], frames_history_path=str(tmp_path / "no.json"))
    gen2.save_frames_history([used])
    assert _api.load_frame_history(str(tmp_path / "no.json")) == []

test_save_frames_history_appends_used_only.__module__ = _api.__name__
_api.test_save_frames_history_appends_used_only = test_save_frames_history_appends_used_only

# ── Галочки типов песен ──────────────────────────────────────────────────────
def test_song_kind_checkboxes_filter_songs_and_quotas():
    s = _api.PackSettings(pick_openings=False)
    assert _api.filter_song(_api.make_song(songType="Opening 1"), s) is False
    assert _api.filter_song(_api.make_song(songType="Ending 1"), s) is True
    assert s.quotas["opening"] == 0
    assert s.quotas["ending"] == s.endings
    # Ни одного типа — генерацию запускать бессмысленно.
    s = _api.PackSettings(pick_openings=False, pick_endings=False, pick_inserts=False)
    assert any("тип песни" in p for p in s.validate())

test_song_kind_checkboxes_filter_songs_and_quotas.__module__ = _api.__name__
_api.test_song_kind_checkboxes_filter_songs_and_quotas = test_song_kind_checkboxes_filter_songs_and_quotas

def test_only_endings_pack_takes_endings(monkeypatch):
    """Оставили одни эндинги — опенингов в паке нет вовсе."""
    s = _api.PackSettings(rounds=1, themes=1, questions=2, parallel=1,
                     pick_openings=False, pick_inserts=False,
                     openings=54, endings=20, inserts=16, random_mode=False,
                     similar_count=1,
                     users=[_api.UserList("morr", "shikimori", ["completed"])])
    pairs = [_api._pair(i, f"fr{i}") for i in range(1, 5)]
    songs = []
    for n, (song, _anime) in enumerate(pairs):
        songs.append(dict(song, songType="Opening 1"))
        songs.append(dict(song, songType="Ending 1", annSongId=song["annSongId"] + 1))
    gen = _api._generator(s, songs, [p[1] for p in pairs],
                     user_ids={"morr": [1, 2, 3, 4]})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    assert len(picked) == 2
    assert all(c.kind == "ending" for c in picked)
    assert all("ED" in c.main_answer for c in picked)

test_only_endings_pack_takes_endings.__module__ = _api.__name__
_api.test_only_endings_pack_takes_endings = test_only_endings_pack_takes_endings

# ── «Похожие» = переключатель «собирать по спискам» ──────────────────────────
def test_common_base_means_no_lists_are_requested():
    """Общая база включена — ни один список не спрашивается. Отдельной галочки
    «Похожие» больше нет: снятые обе базы и означают сборку по спискам."""
    s = _api.PackSettings(random_mode=True, random_source="amq",
                     users=[_api.UserList("morr", "shikimori", ["completed"])])
    assert s.random_pool is True
    # Списка нет — и он не нужен: жалобы на «добавьте пользователя» быть не должно.
    assert not any("пользовател" in p for p in _api.PackSettings().validate())

    class Boom:
        def user_anime_ids(self, *_a, **_kw):
            raise AssertionError("с общей базой списки спрашивать нельзя")

    class FakeAmq:
        def library(self, progress_cb=None, should_stop=None):
            return {11: 2015, 22: 2016}

    gen = _api._generator(s, [], [])
    gen.amq, gen.shikimori.user_anime_ids, gen.mal = FakeAmq(), Boom().user_anime_ids, Boom()
    assert {aid for aid, _users in gen.collect_anime_ids()} == {11, 22}

    # Обе базы сняты — наоборот, идут списки, а база AMQ не трогается.
    s.random_mode, s.similar_count = False, 1
    assert s.random_pool is False
    gen = _api._generator(s, [], [], user_ids={"morr": [5, 7]})
    gen.amq = object()
    assert {aid for aid, _users in gen.collect_anime_ids()} == {5, 7}

test_common_base_means_no_lists_are_requested.__module__ = _api.__name__
_api.test_common_base_means_no_lists_are_requested = test_common_base_means_no_lists_are_requested

def test_user_lists_are_asked_once_per_run_of_the_program():
    """Просьба пользователя: уже спрошенный список берётся из памяти, пока
    программу не перезапустили, — следующий пак собирается быстрее."""
    calls = []

    class CountingShiki:
        def user_anime_ids(self, nick, statuses, **_kw):
            calls.append(nick)
            return [1, 2, 3]

        def animes_by_ids(self, ids):
            return []

        def franchise_parts(self, keys):
            return {}

    s = _api.PackSettings(random_mode=False, similar_count=1,
                     users=[_api.UserList("morr", "shikimori", ["completed"])])
    for _ in range(3):
        gen = _api._generator(s, [], [])
        gen.shikimori = CountingShiki()
        assert {aid for aid, _u in gen.collect_anime_ids()} == {1, 2, 3}
    assert calls == ["morr"]

    # Другие статусы — другой список, его спрашиваем заново.
    s.users = [_api.UserList("morr", "shikimori", ["watching"])]
    gen = _api._generator(s, [], [])
    gen.shikimori = CountingShiki()
    gen.collect_anime_ids()
    assert calls == ["morr", "morr"]

    # Перезапуск программы (очистка кэша) — список спрашивается снова.
    _api.clear_user_list_cache()
    gen = _api._generator(s, [], [])
    gen.shikimori = CountingShiki()
    gen.collect_anime_ids()
    assert calls == ["morr", "morr", "morr"]

test_user_lists_are_asked_once_per_run_of_the_program.__module__ = _api.__name__
_api.test_user_lists_are_asked_once_per_run_of_the_program = test_user_lists_are_asked_once_per_run_of_the_program

def test_characters_api_keeps_all_names():
    """Раздел «Прочие» со страницы персонажа приезжает вместе с именем."""
    payload = {"data": {"animes": [{
        "id": "1535", "malId": "1535",
        "characterRoles": [{
            "rolesEn": ["Supporting"],
            "character": {"id": "3", "name": "Ryuk", "russian": "Рюк",
                          "synonyms": ["Shinigami, Рюук"],
                          "poster": {"originalUrl": "https://shiki/r.jpg"}}}]}]}}

    class FakeClient:
        base_url = "https://shikimori.io"

        def _graphql(self, query, variables):
            assert "synonyms" in query
            return payload["data"]

    rows = _api.api.ShikimoriApi(session=object(),
                            client=FakeClient()).characters_by_anime_ids([1535])
    row = rows[1535][0]
    assert row["name"] == "Рюк" and row["main"] is False
    # «Прочие» приезжают одной строкой через запятую — её разбиваем, иначе
    # целиком такое прозвище никто не назовёт.
    assert row["names"] == ["Рюк", "Ryuk", "Shinigami", "Рюук"]

test_characters_api_keeps_all_names.__module__ = _api.__name__
_api.test_characters_api_keeps_all_names = test_characters_api_keeps_all_names

# ── Персонажи, подсказка, имена файлов, исключения по чужим пакам ────────────
def test_character_answer_and_price_multiplier():
    """Ответ «Название (год) — 『Имя』», цена главного героя — тайтл +4."""
    s = _api.PackSettings(rounds=1, themes=1, questions=2, pct_songs=0, pct_chars=100)
    hero = _api.make_candidate(anime={"malId": 1})
    hero.kind = _api.CHAR_KIND
    hero.character = {"id": 7, "name": "Лайт Ягами", "main": True}
    plain = _api.make_candidate(song={"annSongId": 2}, anime={"malId": 2})
    plain.kind = _api.FRAME_KIND
    _api.arrange_questions([hero, plain], s)
    assert hero.main_answer == "Тетрадь смерти (2006) — 『Лайт Ягами』"
    assert hero.price == plain.price + 4

test_character_answer_and_price_multiplier.__module__ = _api.__name__
_api.test_character_answer_and_price_multiplier = test_character_answer_and_price_multiplier

def test_supporting_character_costs_more_than_main():
    """Второстепенный герой стоит тайтл +6, главный — тайтл +4."""
    s = _api.PackSettings(rounds=1, themes=1, questions=3, pct_songs=0, pct_chars=100)
    main = _api.make_candidate(anime={"malId": 1})
    main.kind = _api.CHAR_KIND
    main.character = {"id": 1, "name": "Лайт Ягами", "main": True}
    side = _api.make_candidate(song={"annSongId": 2}, anime={"malId": 2})
    side.kind = _api.CHAR_KIND
    side.character = {"id": 2, "name": "Рюк", "main": False}
    plain = _api.make_candidate(song={"annSongId": 3}, anime={"malId": 3})
    plain.kind = _api.FRAME_KIND
    _api.arrange_questions([main, side, plain], s)
    assert main.price == plain.price + 4
    assert side.price == plain.price + 6

test_supporting_character_costs_more_than_main.__module__ = _api.__name__
_api.test_supporting_character_costs_more_than_main = test_supporting_character_costs_more_than_main
