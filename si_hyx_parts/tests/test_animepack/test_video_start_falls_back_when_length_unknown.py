# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_video_start_falls_back_when_length_unknown. Public namespace: test_animepack."""
import test_animepack as _api


def test_video_start_falls_back_when_length_unknown(monkeypatch):
    """ffprobe не ответил — начало прежнее: 5 с у опенинга, 0 у эндинга."""
    gen = _api.AnimePackGenerator(_api.PackSettings(video_cut=15), session=_api.FakeSession({}))
    monkeypatch.setattr(gen, "_video_seconds", lambda url: 0.0)
    op = _api.make_candidate()
    ed = _api.make_candidate(song={"songType": "Ending 1"})
    assert gen._video_start(op, "u", 15) == 5
    assert gen._video_start(ed, "u", 15) == 0
    # Ролик короче отрезка — берём его с самого начала, иначе выйдет пустышка.
    monkeypatch.setattr(gen, "_video_seconds", lambda url: 12.0)
    assert gen._video_start(op, "u", 15) == 0

test_video_start_falls_back_when_length_unknown.__module__ = _api.__name__
_api.test_video_start_falls_back_when_length_unknown = test_video_start_falls_back_when_length_unknown

def test_video_download_seeks_to_the_random_start(monkeypatch, tmp_path):
    """Случайное начало уходит в -ss ffmpeg, а повтор после неудачи режет
    ролик с нуля — вдруг длительность мы угадали неверно."""
    gen = _api.AnimePackGenerator(_api.PackSettings(video_cut=15), session=_api.FakeSession({}))
    _api.os.makedirs(tmp_path / "Video", exist_ok=True)
    gen.folder = str(tmp_path)
    cand = _api.make_candidate()
    cand.media_base = "base"
    monkeypatch.setattr(gen, "_theme_video", lambda c: "https://v/op.webm")
    monkeypatch.setattr(gen, "_video_start", lambda c, u, d: 37)
    monkeypatch.setattr(_api.animepack.time, "sleep", lambda *_: None)
    seeks = []

    def fake_run(cmd, timeout=180.0):
        seeks.append(cmd[cmd.index("-ss") + 1])
        return 1, "нет"

    monkeypatch.setattr(gen, "_run_killable", fake_run)
    assert gen.download_video(cand) is False
    assert seeks[0] == "37" and set(seeks[1:]) == {"0"}

test_video_download_seeks_to_the_random_start.__module__ = _api.__name__
_api.test_video_download_seeks_to_the_random_start = test_video_download_seeks_to_the_random_start

def test_video_seconds_asks_ffprobe_once(monkeypatch):
    """Длительность спрашивается у ffprobe и кэшируется по ссылке."""
    gen = _api.AnimePackGenerator(_api.PackSettings(), session=_api.FakeSession({}))
    calls = []

    def fake_run(cmd, timeout=180.0):
        calls.append(cmd)
        return 0, "89.567\n", ""

    monkeypatch.setattr(gen, "_run_capture", fake_run)
    assert gen._video_seconds("https://v/op.webm") == _api.pytest.approx(89.567)
    assert gen._video_seconds("https://v/op.webm") == _api.pytest.approx(89.567)
    assert len(calls) == 1
    assert "format=duration" in calls[0]

test_video_seconds_asks_ffprobe_once.__module__ = _api.__name__
_api.test_video_seconds_asks_ffprobe_once = test_video_seconds_asks_ffprobe_once

def test_video_encode_args_follow_settings():
    gen = _api.AnimePackGenerator(_api.PackSettings(video_crf=40, video_preset=6),
                             session=_api.FakeSession({}))
    args = gen.video_encode_args()
    assert "libsvtav1" in args                      # тот же кодер, что в «Обработке»
    assert args[args.index("-crf") + 1] == "40"
    assert args[args.index("-preset") + 1] == "6"
    assert any("scale=-2:720" in a for a in args)

test_video_encode_args_follow_settings.__module__ = _api.__name__
_api.test_video_encode_args_follow_settings = test_video_encode_args_follow_settings

def test_video_defaults_are_fifteen_seconds_crf45_fastest():
    s = _api.PackSettings()
    assert (s.video_cut, s.video_crf, s.video_preset) == (15, 45, 13)

test_video_defaults_are_fifteen_seconds_crf45_fastest.__module__ = _api.__name__
_api.test_video_defaults_are_fifteen_seconds_crf45_fastest = test_video_defaults_are_fifteen_seconds_crf45_fastest

def test_video_share_lives_in_the_mix_slider():
    """Ролики — такая же доля ползунка, как кадры: своя квота вопросов."""
    s = _api.PackSettings(rounds=1, themes=1, questions=10, song_video=True,
                     pct_songs=50, pct_videos=30, pct_frames=20, pct_chars=0)
    assert s.percents == (50, 30, 20, 0, 0)
    q = s.question_quotas
    assert q[_api.VIDEO_KIND] == 3 and q[_api.FRAME_KIND] == 2
    assert sum(q[k] for k in ("opening", "ending", "insert")) == 5
    assert sum(q.values()) == 10

test_video_share_lives_in_the_mix_slider.__module__ = _api.__name__
_api.test_video_share_lives_in_the_mix_slider = test_video_share_lives_in_the_mix_slider

def test_video_share_only_counts_with_the_checkbox():
    """Снятая галочка «Вопрос — ролик» убирает долю роликов совсем."""
    s = _api.PackSettings(rounds=1, themes=1, questions=10, song_video=False,
                     pct_songs=50, pct_videos=50)
    assert s.percents == (100, 0, 0, 0, 0)
    assert s.question_quotas[_api.VIDEO_KIND] == 0
    # А роликам нужна песня ровно так же, как обычному вопросу.
    s.song_video, s.pct_songs, s.pct_videos = True, 0, 100
    assert s.has_songs is True and s.only_kind is None

test_video_share_only_counts_with_the_checkbox.__module__ = _api.__name__
_api.test_video_share_only_counts_with_the_checkbox = test_video_share_only_counts_with_the_checkbox

def test_legacy_song_video_becomes_a_full_video_share():
    """Старая галочка делала роликами ВСЕ песни — читаем её как 100% роликов."""
    s = _api.PackSettings.from_dict({"song_video": True, "pct_songs": 100})
    assert s.percents == (0, 100, 0, 0, 0)
    # Явно сохранённая доля старую галочку не переписывает.
    s = _api.PackSettings.from_dict({"song_video": True, "pct_songs": 70,
                                "pct_videos": 30})
    assert s.percents == (70, 30, 0, 0, 0)

test_legacy_song_video_becomes_a_full_video_share.__module__ = _api.__name__
_api.test_legacy_song_video_becomes_a_full_video_share = test_legacy_song_video_becomes_a_full_video_share

def test_video_question_answer_is_the_same_as_a_song():
    """Просьба пользователя: ролик отличается от песни только самим вопросом —
    ответ (тег, год, песня, исполнитель, постер) у них общий."""
    s = _api.PackSettings(rounds=1, themes=1, questions=2, song_video=True,
                     pct_songs=50, pct_videos=50, hint=True)
    song = _api.make_candidate(anime={"malId": 1})
    video = _api.make_candidate(song={"annSongId": 9}, anime={"malId": 1})
    video.kind, video.has_video = _api.VIDEO_KIND, True
    song.has_poster = video.has_poster = True
    root, ns = _api._parse(_api.build_content_xml([song, video], s))
    answers = [[a.text for a in q.findall("s:right/s:answer", ns)]
               for q in root.findall(".//s:question", ns)]
    assert answers[0] == answers[1]
    assert video.main_answer == song.main_answer
    # «Опенинг» звучит у обоих, но по-разному: у песни это подпись на экране, у
    # ролика — устный текст ведущего (просьба пользователя).
    hints = root.findall(
        ".//s:param[@name='question']/s:item[@waitForFinish='False']", ns)
    assert [i.text for i in hints] == ["Опенинг", "Опенинг"]
    assert [i.get("placement") for i in hints] == [None, "replic"]
    # В ответе обоих — реплика с исполнителем и постер.
    for q in root.findall(".//s:question", ns):
        items = q.findall("s:params/s:param[@name='answer']/s:item", ns)
        assert items[0].text == (
            "Исполнитель — 『Nightmare』 · Сложность AMQ — 85 · Рейтинг MAL — 『8.60⭐』")
        assert items[1].get("type") == "image"

test_video_question_answer_is_the_same_as_a_song.__module__ = _api.__name__
_api.test_video_question_answer_is_the_same_as_a_song = test_video_question_answer_is_the_same_as_a_song

def test_video_price_follows_its_song_type():
    """Ролик-эндинг стоит как эндинг: надбавка берётся от песни."""
    s = _api.PackSettings(rounds=1, themes=1, questions=2)
    op = _api.make_candidate(anime={"malId": 1})
    ed = _api.make_candidate(song={"songType": "Ending 1", "annSongId": 2},
                        anime={"malId": 2})
    op.kind = ed.kind = _api.VIDEO_KIND
    _api.arrange_questions([op, ed], s)
    assert ed.price - op.price == 2

test_video_price_follows_its_song_type.__module__ = _api.__name__
_api.test_video_price_follows_its_song_type = test_video_price_follows_its_song_type

def test_video_audio_is_opus_like_every_other_track(monkeypatch):
    """Звук ролика кодируется тем же opus с нормализацией, что и песни."""
    s = _api.PackSettings(song_video=True, video_cut=15)
    gen = _api.AnimePackGenerator(s, session=_api.FakeSession({}))
    gen.folder = "."
    cand = _api.make_candidate()
    cand.kind = _api.VIDEO_KIND
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

test_video_audio_is_opus_like_every_other_track.__module__ = _api.__name__
_api.test_video_audio_is_opus_like_every_other_track = test_video_audio_is_opus_like_every_other_track

# ── Цена за сложность песни ──────────────────────────────────────────────────
# Сложность 80 даёт ровно +2 (просьба пользователя), а дальше линейно: сотня —
# ничего, ноль — все десять. Нулевая и пустая сложность значат «не знаем» и
# надбавки не дают вовсе.
@_api.pytest.mark.parametrize("difficulty,bonus", [
    (100, 0), (90, 1), (80, 2), (50, 5), (5, 10), (0, 0), (None, 0),
])
def test_song_difficulty_bonus(difficulty, bonus):
    assert _api.song_difficulty_bonus(difficulty) == bonus

test_song_difficulty_bonus.__module__ = _api.__name__
_api.test_song_difficulty_bonus = test_song_difficulty_bonus

def test_difficulty_bonus_only_for_songs():
    """Надбавка за сложность песни картинок не касается — у них её нет.

    База у обоих вопросов одна и та же (узнаваемость тайтла), поэтому разница
    в цене — ровно надбавка за сложность AMQ."""
    s = _api.PackSettings(rounds=1, themes=1, questions=2, sort_by_index=True)
    song = _api.make_candidate(song={"annSongId": 1, "songDifficulty": 5.0},
                          anime={"malId": 1})
    frame = _api.make_candidate(song={"annSongId": 2, "songDifficulty": 5.0},
                           anime={"malId": 2})
    frame.kind = _api.FRAME_KIND
    _api.arrange_questions([song, frame], s)
    assert song.price - frame.price == 10

test_difficulty_bonus_only_for_songs.__module__ = _api.__name__
_api.test_difficulty_bonus_only_for_songs = test_difficulty_bonus_only_for_songs

# ── Ползунок состава ─────────────────────────────────────────────────────────
def test_percents_normalise_and_split_all_questions():
    s = _api.PackSettings(rounds=1, themes=1, questions=20,
                     pct_songs=60, pct_frames=25, pct_chars=15)
    assert s.percents == (60, 0, 25, 15, 0)
    q = s.question_quotas
    assert q[_api.FRAME_KIND] == 5 and q[_api.CHAR_KIND] == 3
    assert sum(q.values()) == 20
    # Доли, не дающие сотни, приводятся к ней.
    assert _api.PackSettings(pct_songs=1, pct_frames=1,
                        pct_chars=2).percents == (25, 0, 25, 50, 0)

test_percents_normalise_and_split_all_questions.__module__ = _api.__name__
_api.test_percents_normalise_and_split_all_questions = test_percents_normalise_and_split_all_questions

def test_legacy_mix_settings_become_percents():
    """Настройки, сохранённые до ползунка, читаются как доли."""
    assert _api.PackSettings.from_dict({"frames_only": True}).percents == (0, 0, 100, 0, 0)
    assert _api.PackSettings.from_dict({"chars_only": True}).percents == (0, 0, 0, 100, 0)
    assert _api.PackSettings.from_dict(
        {"mix_frames": True, "mix_frames_per": 1}).percents == (50, 0, 50, 0, 0)
    # Новые настройки старые ключи не перебивают.
    assert _api.PackSettings.from_dict(
        {"frames_only": True, "pct_songs": 100,
         "pct_frames": 0}).percents == (100, 0, 0, 0, 0)

test_legacy_mix_settings_become_percents.__module__ = _api.__name__
_api.test_legacy_mix_settings_become_percents = test_legacy_mix_settings_become_percents
