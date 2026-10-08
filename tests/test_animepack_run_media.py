"""Генерация аниме-пака: полный прогон, кадры, видео и выбор песен."""
import os
import zipfile

import pytest

from conftest import FakeSession

import animepack
import animepack_api as api
from animepack import (
    CHAR_KIND,
    FRAME_KIND,
    VIDEO_KIND,
    AnimePackGenerator,
    PackSettings,
    UserList,
    arrange_questions,
    build_content_xml,
    clear_user_list_cache,
    filter_song,
    load_frame_history,
    save_frame_history,
    song_difficulty_bonus,
    song_tag,
)
from animepack_test_helpers import _forget_user_lists  # noqa: F401 — autouse-фикстура
from animepack_test_helpers import (
    _frame_cand,
    _generator,
    _pair,
    _parse,
    make_candidate,
    make_song,
)


def test_run_writes_readable_siq(tmp_path, monkeypatch):
    """Готовый .siq должен читаться разборщиком самого приложения, и все
    ссылки на медиа — существовать внутри архива."""
    s = PackSettings(rounds=1, themes=1, questions=2, openings=2, endings=0,
                     inserts=0, parallel=1, random_mode=False,
                     similar_count=1, title="Тест пак",
                     out_dir=str(tmp_path),
                     users=[UserList("morr", "myanimelist", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in (1, 2)]
    gen = _generator(s, [p[0] for p in pairs], [p[1] for p in pairs],
                     user_ids={"morr": [1, 2]})

    def fake_fetch(cand):
        audio = os.path.join(gen.folder, "Audio", cand.audio_out)
        with open(audio, "wb") as f:
            f.write(b"\x00" * 32)
        poster = os.path.join(gen.folder, "Images", cand.poster_file)
        with open(poster, "wb") as f:
            f.write(b"\x00" * 16)
        cand.has_poster = True
        return True

    monkeypatch.setattr(gen, "_fetch_media", fake_fetch)
    result = gen.run()
    assert result.path.endswith(".siq") and os.path.exists(result.path)
    assert len(result.songs) == 2

    with zipfile.ZipFile(result.path) as zf:
        names = set(zf.namelist())
        assert "content.xml" in names
        xml = zf.read("content.xml")
        root, ns = _parse(xml)
        for item in root.findall(".//s:item[@isRef='True']", ns):
            folder = "Audio" if item.get("type") == "audio" else "Images"
            assert f"{folder}/{item.text}" in names

    # Разборщик приложения (SiQuesterHYX) должен понять пакет.
    from siquester.siq_package import SiqPackage
    pkg = SiqPackage(result.path)
    assert sum(len(t.get("questions", ())) for r in pkg.rounds
               for t in r.get("themes", ())) == 2
    assert gen.folder == ""            # временная папка убрана

def test_run_refuses_broken_settings():
    from animepack import AnimePackError
    s = PackSettings(openings=0, endings=0, inserts=0)
    gen = AnimePackGenerator(s, session=object())
    with pytest.raises(AnimePackError):
        gen.run()

# ── Тег песни в ответе («Название OP1 (2010)») ───────────────────────────────
@pytest.mark.parametrize("song_type,tag", [
    ("Opening 1", "OP1"), ("Ending 12", "ED12"), ("Insert Song", "OST"),
    ("Opening", "OP"), ("Что-то", ""), (None, ""),
])
def test_song_tag(song_type, tag):
    assert song_tag(song_type) == tag

def test_answer_tag_goes_before_year():
    """Просьба пользователя: в ответе видно, опенинг это, эндинг или вставка."""
    cand = make_candidate(song={"songType": "Ending 2"})
    assert cand.main_answer == "Тетрадь смерти ED2 (2006) — 『the WORLD』"
    # Год, уже записанный Shikimori в название, не задваивается и остаётся
    # последним — тег встаёт перед ним.
    old = make_candidate(song={"songType": "Insert Song"},
                         anime={"russian": "Могучий Атом (2003)",
                                "airedOn": {"year": 2003}})
    assert old.main_answer == "Могучий Атом OST (2003) — 『the WORLD』"
    # У вопроса-кадра песни нет — нет и тега.
    frame = make_candidate()
    frame.kind = FRAME_KIND
    assert frame.tag == "" and frame.main_answer == "Тетрадь смерти (2006)"

def test_frame_pick_is_random_and_unique_within_pack():
    s = PackSettings(pct_songs=0, pct_frames=100)
    gen = _generator(s, [], [])
    cand = _frame_cand()
    picked = [gen._pick_frame_url(cand) for _ in range(6)]
    assert len(set(picked)) == 6          # шесть скриншотов — шесть разных
    # Использованные кадры не идут по кругу даже при нехватке материала.
    assert gen._pick_frame_url(cand) == ""

def test_frame_pick_never_repeats_within_pack():
    """Кадр всегда случайный (настройки «первый кадр» больше нет), но дважды
    один и тот же в паке не берётся."""
    s = PackSettings(pct_songs=0, pct_frames=100)
    gen = _generator(s, [], [])
    cand = _frame_cand()
    seen = {gen._pick_frame_url(cand) for _ in range(6)}
    assert len(seen) == 6

def test_frames_no_repeat_skips_history(tmp_path):
    path = str(tmp_path / "frames.json")
    save_frame_history(["https://shiki/0.jpg", "https://shiki/1.jpg"], path)
    s = PackSettings(pct_songs=0, pct_frames=100, frames_no_repeat=True)
    gen = _generator(s, [], [], frames_history_path=path)
    # Кадр случайный, но из тех, что в истории ещё не были.
    assert gen._pick_frame_url(_frame_cand()) in {
        f"https://shiki/{i}.jpg" for i in range(2, 6)}

def test_frames_no_repeat_drops_title_without_fresh_frames(tmp_path):
    path = str(tmp_path / "frames.json")
    save_frame_history([f"https://shiki/{i}.jpg" for i in range(6)], path)
    s = PackSettings(pct_songs=0, pct_frames=100, frames_no_repeat=True)
    gen = _generator(s, [], [], frames_history_path=path)
    # Свободных кадров нет — вопроса не будет, пак возьмёт другой тайтл.
    assert gen._pick_frame_url(_frame_cand()) == ""

def test_save_frames_history_appends_used_only(tmp_path):
    path = str(tmp_path / "frames.json")
    s = PackSettings(pct_songs=0, pct_frames=100, frames_no_repeat=True)
    gen = _generator(s, [], [], frames_history_path=path)
    used = _frame_cand()
    used.frame_url, used.has_frame = "https://shiki/3.jpg?ts=1", True
    lost = _frame_cand()
    lost.frame_url = "https://shiki/4.jpg"      # кадр не скачался
    gen.save_frames_history([used, lost])
    assert load_frame_history(path) == ["https://shiki/3.jpg"]  # ?query отброшен

    # Без галочки история не пишется вовсе.
    s2 = PackSettings(pct_songs=0, pct_frames=100,
                           frames_no_repeat=False)
    gen2 = _generator(s2, [], [], frames_history_path=str(tmp_path / "no.json"))
    gen2.save_frames_history([used])
    assert load_frame_history(str(tmp_path / "no.json")) == []

# ── Галочки типов песен ──────────────────────────────────────────────────────
def test_song_kind_checkboxes_filter_songs_and_quotas():
    s = PackSettings(pick_openings=False)
    assert filter_song(make_song(songType="Opening 1"), s) is False
    assert filter_song(make_song(songType="Ending 1"), s) is True
    assert s.quotas["opening"] == 0
    assert s.quotas["ending"] == s.endings
    # Ни одного типа — генерацию запускать бессмысленно.
    s = PackSettings(pick_openings=False, pick_endings=False, pick_inserts=False)
    assert any("тип песни" in p for p in s.validate())

def test_only_endings_pack_takes_endings(monkeypatch):
    """Оставили одни эндинги — опенингов в паке нет вовсе."""
    s = PackSettings(rounds=1, themes=1, questions=2, parallel=1,
                     pick_openings=False, pick_inserts=False,
                     openings=54, endings=20, inserts=16, random_mode=False,
                     similar_count=1,
                     users=[UserList("morr", "shikimori", ["completed"])])
    pairs = [_pair(i, f"fr{i}") for i in range(1, 5)]
    songs = []
    for n, (song, _anime) in enumerate(pairs):
        songs.append(dict(song, songType="Opening 1"))
        songs.append(dict(song, songType="Ending 1", annSongId=song["annSongId"] + 1))
    gen = _generator(s, songs, [p[1] for p in pairs],
                     user_ids={"morr": [1, 2, 3, 4]})
    monkeypatch.setattr(gen, "_fetch_media", lambda cand: True)
    picked = gen.select_songs()
    assert len(picked) == 2
    assert all(c.kind == "ending" for c in picked)
    assert all("ED" in c.main_answer for c in picked)

# ── «Похожие» = переключатель «собирать по спискам» ──────────────────────────
def test_common_base_means_no_lists_are_requested():
    """Общая база включена — ни один список не спрашивается. Отдельной галочки
    «Похожие» больше нет: снятые обе базы и означают сборку по спискам."""
    s = PackSettings(random_mode=True, random_source="amq",
                     users=[UserList("morr", "shikimori", ["completed"])])
    assert s.random_pool is True
    # Списка нет — и он не нужен: жалобы на «добавьте пользователя» быть не должно.
    assert not any("пользовател" in p for p in PackSettings().validate())

    class Boom:
        def user_anime_ids(self, *_a, **_kw):
            raise AssertionError("с общей базой списки спрашивать нельзя")

    class FakeAmq:
        def library(self, progress_cb=None, should_stop=None):
            return {11: 2015, 22: 2016}

    gen = _generator(s, [], [])
    gen.amq, gen.shikimori.user_anime_ids, gen.mal = FakeAmq(), Boom().user_anime_ids, Boom()
    assert {aid for aid, _users in gen.collect_anime_ids()} == {11, 22}

    # Обе базы сняты — наоборот, идут списки, а база AMQ не трогается.
    s.random_mode, s.similar_count = False, 1
    assert s.random_pool is False
    gen = _generator(s, [], [], user_ids={"morr": [5, 7]})
    gen.amq = object()
    assert {aid for aid, _users in gen.collect_anime_ids()} == {5, 7}

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

    s = PackSettings(random_mode=False, similar_count=1,
                     users=[UserList("morr", "shikimori", ["completed"])])
    for _ in range(3):
        gen = _generator(s, [], [])
        gen.shikimori = CountingShiki()
        assert {aid for aid, _u in gen.collect_anime_ids()} == {1, 2, 3}
    assert calls == ["morr"]

    # Другие статусы — другой список, его спрашиваем заново.
    s.users = [UserList("morr", "shikimori", ["watching"])]
    gen = _generator(s, [], [])
    gen.shikimori = CountingShiki()
    gen.collect_anime_ids()
    assert calls == ["morr", "morr"]

    # Перезапуск программы (очистка кэша) — список спрашивается снова.
    clear_user_list_cache()
    gen = _generator(s, [], [])
    gen.shikimori = CountingShiki()
    gen.collect_anime_ids()
    assert calls == ["morr", "morr", "morr"]

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

    rows = api.ShikimoriApi(session=object(),
                            client=FakeClient()).characters_by_anime_ids([1535])
    row = rows[1535][0]
    assert row["name"] == "Рюк" and row["main"] is False
    # «Прочие» приезжают одной строкой через запятую — её разбиваем, иначе
    # целиком такое прозвище никто не назовёт.
    assert row["names"] == ["Рюк", "Ryuk", "Shinigami", "Рюук"]

# ── Персонажи, подсказка, имена файлов, исключения по чужим пакам ────────────
def test_character_answer_and_price_multiplier():
    """Ответ «Название (год) — 『Имя』», цена главного героя — тайтл +4."""
    s = PackSettings(rounds=1, themes=1, questions=2, pct_songs=0, pct_chars=100)
    hero = make_candidate(anime={"malId": 1})
    hero.kind = CHAR_KIND
    hero.character = {"id": 7, "name": "Лайт Ягами", "main": True}
    plain = make_candidate(song={"annSongId": 2}, anime={"malId": 2})
    plain.kind = FRAME_KIND
    arrange_questions([hero, plain], s)
    assert hero.main_answer == "Тетрадь смерти (2006) — 『Лайт Ягами』"
    assert hero.price == plain.price + 4

def test_supporting_character_costs_more_than_main():
    """Второстепенный герой стоит тайтл +6, главный — тайтл +4."""
    s = PackSettings(rounds=1, themes=1, questions=3, pct_songs=0, pct_chars=100)
    main = make_candidate(anime={"malId": 1})
    main.kind = CHAR_KIND
    main.character = {"id": 1, "name": "Лайт Ягами", "main": True}
    side = make_candidate(song={"annSongId": 2}, anime={"malId": 2})
    side.kind = CHAR_KIND
    side.character = {"id": 2, "name": "Рюк", "main": False}
    plain = make_candidate(song={"annSongId": 3}, anime={"malId": 3})
    plain.kind = FRAME_KIND
    arrange_questions([main, side, plain], s)
    assert main.price == plain.price + 4
    assert side.price == plain.price + 6


def test_video_start_falls_back_when_length_unknown(monkeypatch):
    """ffprobe не ответил — начало прежнее: 5 с у опенинга, 0 у эндинга."""
    gen = AnimePackGenerator(PackSettings(video_cut=15), session=FakeSession({}))
    monkeypatch.setattr(gen, "_video_seconds", lambda url: 0.0)
    op = make_candidate()
    ed = make_candidate(song={"songType": "Ending 1"})
    assert gen._video_start(op, "u", 15) == 5
    assert gen._video_start(ed, "u", 15) == 0
    # Ролик короче отрезка — берём его с самого начала, иначе выйдет пустышка.
    monkeypatch.setattr(gen, "_video_seconds", lambda url: 12.0)
    assert gen._video_start(op, "u", 15) == 0

def test_video_download_seeks_to_the_random_start(monkeypatch, tmp_path):
    """Случайное начало уходит в -ss ffmpeg, а повтор после неудачи режет
    ролик с нуля — вдруг длительность мы угадали неверно."""
    gen = AnimePackGenerator(PackSettings(video_cut=15), session=FakeSession({}))
    from si_hyx_parts.animepack import theme_video
    monkeypatch.setattr(theme_video, "remote_encode", lambda *a: (False, "unsupported"))
    monkeypatch.setattr(theme_video, "source_file", lambda *a: None)
    monkeypatch.setattr(gen, "_video_seconds", lambda *a: 90)
    os.makedirs(tmp_path / "Video", exist_ok=True)
    gen.folder = str(tmp_path)
    cand = make_candidate()
    cand.media_base = "base"
    monkeypatch.setattr(gen, "_theme_video", lambda c: "https://v/op.webm")
    monkeypatch.setattr(gen, "_video_start", lambda c, u, d: 37)
    monkeypatch.setattr(animepack.time, "sleep", lambda *_: None)
    seeks = []

    def fake_run(cmd, timeout=180.0):
        seeks.append(cmd[cmd.index("-ss") + 1])
        return 1, "нет"

    monkeypatch.setattr(gen, "_run_killable", fake_run)
    assert gen.download_video(cand) is False
    assert seeks[0] == "37" and set(seeks[1:]) == {"0"}

def test_video_seconds_asks_ffprobe_once(monkeypatch):
    """Длительность спрашивается у ffprobe и кэшируется по ссылке."""
    gen = AnimePackGenerator(PackSettings(), session=FakeSession({}))
    calls = []

    def fake_run(cmd, timeout=180.0):
        calls.append(cmd)
        return 0, "89.567\n", ""

    monkeypatch.setattr(gen, "_run_capture", fake_run)
    assert gen._video_seconds("https://v/op.webm") == pytest.approx(89.567)
    assert gen._video_seconds("https://v/op.webm") == pytest.approx(89.567)
    assert len(calls) == 1
    assert "format=duration" in calls[0]

def test_video_encode_args_follow_settings():
    gen = AnimePackGenerator(PackSettings(video_crf=40, video_preset=6),
                             session=FakeSession({}))
    args = gen.video_encode_args()
    assert "libsvtav1" in args                      # тот же кодер, что в «Обработке»
    assert args[args.index("-crf") + 1] == "40"
    assert args[args.index("-preset") + 1] == "6"
    assert any("scale=-2:720" in a for a in args)

def test_video_defaults_are_fifteen_seconds_crf45_fastest():
    s = PackSettings()
    assert (s.video_cut, s.video_crf, s.video_preset) == (15, 45, 13)

def test_video_share_lives_in_the_mix_slider():
    """Ролики — такая же доля ползунка, как кадры: своя квота вопросов."""
    s = PackSettings(rounds=1, themes=1, questions=10, song_video=True,
                     pct_songs=50, pct_videos=30, pct_frames=20, pct_chars=0)
    assert s.percents == (50, 30, 20, 0, 0)
    q = s.question_quotas
    assert q[VIDEO_KIND] == 3 and q[FRAME_KIND] == 2
    assert sum(q[k] for k in ("opening", "ending", "insert")) == 5
    assert sum(q.values()) == 10

def test_video_share_only_counts_with_the_checkbox():
    """Снятая галочка «Вопрос — ролик» убирает долю роликов совсем."""
    s = PackSettings(rounds=1, themes=1, questions=10, song_video=False,
                     pct_songs=50, pct_videos=50)
    assert s.percents == (100, 0, 0, 0, 0)
    assert s.question_quotas[VIDEO_KIND] == 0
    # А роликам нужна песня ровно так же, как обычному вопросу.
    s.song_video, s.pct_songs, s.pct_videos = True, 0, 100
    assert s.has_songs is True and s.only_kind is None

def test_legacy_song_video_becomes_a_full_video_share():
    """Старая галочка делала роликами ВСЕ песни — читаем её как 100% роликов."""
    s = PackSettings.from_dict({"song_video": True, "pct_songs": 100})
    assert s.percents == (0, 100, 0, 0, 0)
    # Явно сохранённая доля старую галочку не переписывает.
    s = PackSettings.from_dict({"song_video": True, "pct_songs": 70,
                                "pct_videos": 30})
    assert s.percents == (70, 30, 0, 0, 0)

def test_video_question_answer_is_the_same_as_a_song():
    """Просьба пользователя: ролик отличается от песни только самим вопросом —
    ответ (тег, год, песня, исполнитель, постер) у них общий."""
    s = PackSettings(rounds=1, themes=1, questions=2, song_video=True,
                     pct_songs=50, pct_videos=50, hint=True)
    song = make_candidate(anime={"malId": 1})
    video = make_candidate(song={"annSongId": 9}, anime={"malId": 1})
    video.kind, video.has_video = VIDEO_KIND, True
    song.has_poster = video.has_poster = True
    root, ns = _parse(build_content_xml([song, video], s))
    answers = [[a.text for a in q.findall("s:right/s:answer", ns)]
               for q in root.findall(".//s:question", ns)]
    assert answers[0] == answers[1]
    assert video.main_answer == song.main_answer
    # «Опенинг» звучит у обоих, но по-разному: у песни это подпись на экране, у
    # ролика — устный текст ведущего (просьба пользователя).
    hints = root.findall(
        ".//s:param[@name='question']/s:item[@waitForFinish='False']", ns)
    assert [i.text for i in hints] == ["Опенинг", "Опенинг"]
    for q in root.findall(".//s:question", ns):
        items = q.findall("s:params/s:param[@name='question']/s:item", ns)
        expected = "replic" if items[1].get("type") == "video" else None
        assert items[0].get("placement") == expected
    # В ответе обоих — реплика с исполнителем и постер.
    for q in root.findall(".//s:question", ns):
        items = q.findall("s:params/s:param[@name='answer']/s:item", ns)
        assert items[0].text == (
            "Исполнитель — 『Nightmare』 · Сложность AMQ — 85 · Рейтинг MAL — 『8.60⭐』")
        assert items[1].get("type") == "image"

def test_video_price_follows_its_song_type():
    """Тип песни не меняет цену вопроса с видеорядом: она как у кадра."""
    s = PackSettings(rounds=1, themes=1, questions=2)
    op = make_candidate(anime={"malId": 1})
    ed = make_candidate(song={"songType": "Ending 1", "annSongId": 2},
                        anime={"malId": 2})
    op.kind = ed.kind = VIDEO_KIND
    arrange_questions([op, ed], s)
    assert ed.price == op.price == animepack.price_for_level(op.level)

def test_video_audio_is_opus_like_every_other_track(monkeypatch):
    """Звук ролика кодируется тем же opus с нормализацией, что и песни."""
    s = PackSettings(song_video=True, video_cut=15)
    gen = AnimePackGenerator(s, session=FakeSession({}))
    from si_hyx_parts.animepack import theme_video
    monkeypatch.setattr(theme_video, "remote_encode", lambda *a: (False, "unsupported"))
    monkeypatch.setattr(theme_video, "source_file", lambda *a: None)
    monkeypatch.setattr(gen, "_video_seconds", lambda *a: 90)
    gen.folder = "."
    cand = make_candidate()
    cand.kind = VIDEO_KIND
    seen = []
    monkeypatch.setattr("animepack.time.sleep", lambda *_a: None)
    monkeypatch.setattr(gen, "_theme_video", lambda c: "https://v/op.webm")
    monkeypatch.setattr(gen, "_run_killable",
                        lambda cmd, timeout=0: seen.append(cmd) or (1, "нет"))
    gen.download_video(cand)
    cmd = seen[0]
    assert cmd[cmd.index("-c:a") + 1] == "libopus"
    assert cmd[cmd.index("-b:a") + 1] == "192k"
    af = cmd[cmd.index("-af") + 1]
    assert af == gen.audio_filters(15)
    assert "loudnorm=I=-20.0" in af and "afade=t=out" in af

# ── Цена за сложность песни ──────────────────────────────────────────────────
# Сложность 80 даёт ровно +2 (просьба пользователя), а дальше линейно: сотня —
# ничего, ноль — все десять. Нулевая и пустая сложность значат «не знаем» и
# надбавки не дают вовсе.
@pytest.mark.parametrize("difficulty,bonus", [
    (100, 0), (90, 1), (80, 2), (50, 5), (5, 10), (0, 0), (None, 0),
])
def test_song_difficulty_bonus(difficulty, bonus):
    assert song_difficulty_bonus(difficulty) == bonus

def test_difficulty_bonus_only_for_songs():
    """Надбавка за сложность песни картинок не касается — у них её нет.

    База у обоих вопросов одна и та же (узнаваемость тайтла), поэтому разница
    в цене — ровно надбавка за сложность AMQ."""
    s = PackSettings(rounds=1, themes=1, questions=2, sort_by_index=True)
    song = make_candidate(song={"annSongId": 1, "songDifficulty": 5.0},
                          anime={"malId": 1})
    frame = make_candidate(song={"annSongId": 2, "songDifficulty": 5.0},
                           anime={"malId": 2})
    frame.kind = FRAME_KIND
    arrange_questions([song, frame], s)
    assert song.price - frame.price == 10

# ── Ползунок состава ─────────────────────────────────────────────────────────
def test_percents_normalise_and_split_all_questions():
    s = PackSettings(rounds=1, themes=1, questions=20,
                     pct_songs=60, pct_frames=25, pct_chars=15)
    assert s.percents == (60, 0, 25, 15, 0)
    q = s.question_quotas
    assert q[FRAME_KIND] == 5 and q[CHAR_KIND] == 3
    assert sum(q.values()) == 20
    # Доли, не дающие сотни, приводятся к ней.
    assert PackSettings(pct_songs=1, pct_frames=1,
                        pct_chars=2).percents == (25, 0, 25, 50, 0)

def test_legacy_mix_settings_become_percents():
    """Настройки, сохранённые до ползунка, читаются как доли."""
    assert PackSettings.from_dict({"frames_only": True}).percents == (0, 0, 100, 0, 0)
    assert PackSettings.from_dict({"chars_only": True}).percents == (0, 0, 0, 100, 0)
    assert PackSettings.from_dict(
        {"mix_frames": True, "mix_frames_per": 1}).percents == (50, 0, 50, 0, 0)
    # Новые настройки старые ключи не перебивают.
    assert PackSettings.from_dict(
        {"frames_only": True, "pct_songs": 100,
         "pct_frames": 0}).percents == (100, 0, 0, 0, 0)
