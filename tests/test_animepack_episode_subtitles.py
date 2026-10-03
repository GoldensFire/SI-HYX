"""Episode-specific RU binding, clipping/shift and optional failure behavior."""
from types import SimpleNamespace

import animepack as api
import animepack_tab
from si_hyx_parts.animepack import episode_subtitles as subtitles
from test_animepack_new_kinds import make_anime
from test_animepack_tab_mix import _FakeMain


SRT = ("1\n00:01:38,000 --> 00:01:43,000\nПривет!\n\n"
       "2\n00:01:50,000 --> 00:02:05,000\nКак дела?\n\n"
       "3\n00:03:00,000 --> 00:03:02,000\nПозже.\n").encode("utf-8")


def test_subtitles_are_cropped_and_shifted_at_both_boundaries():
    rows = subtitles.cropped(SRT, "series.srt", 100)
    assert rows == [(0, 3, "Привет!"), (10, 15, "Как дела?")]
    output = subtitles.srt(rows)
    assert "00:00:00,000 --> 00:00:03,000" in output
    assert "00:00:10,000 --> 00:00:15,000" in output
    assert "Позже" not in output


def test_ass_and_cp1251_use_the_existing_parser():
    data = ("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:01:39.00,0:01:44.00,Default,,0,0,0,,Привет!\n").encode("cp1251")
    assert subtitles.cropped(data, "series.ass", 100) == [(0, 4, "Привет!")]


def test_subdl_exact_binding_separates_tvdb_and_local_number():
    info = {"episodes": {"1": {"episodeNumber": 1, "seasonNumber": 4, "tvdbEpisodeNumber": 12},
                         "2": {"episodeNumber": 2, "seasonNumber": 4, "tvdbEpisodeNumber": 13}}}
    assert subtitles.subdl_binding(info, 1) == [{"season": 4, "episode": 12}]
    assert subtitles.subdl_binding(info, 3) == []


def test_subdl_empty_falls_back_to_exact_jimaku_episode():
    import threading
    calls = []
    subdl = SimpleNamespace(episode_files=lambda *a: [], download=lambda _: (b"", ""))
    def files(entry_id, episode):
        calls.append(episode)
        return [{"name": "Title.S01E04.rus.srt"}, {"name": "Title.S01E03.rus.srt"}]
    jimaku = SimpleNamespace(entry=lambda _: {"id": 42}, files=files, download=lambda _: SRT)
    anizip = SimpleNamespace(external_ids=lambda _: {"imdb_id": "tt1"},
                            info=lambda _: {"episodes": {"3": {"episodeNumber": 3, "seasonNumber": 1}}})
    gen = SimpleNamespace(s=api.PackSettings(episode_ru_subtitles=True), stopped=lambda: False,
                          subdl=subdl, jimaku=jimaku, anizip=anizip, gemini=None,
                          _episode_subtitle_lock=threading.Lock(), _log_rare=lambda *a: None)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    assert subtitles.find(gen, candidate, 1, 3, 100) == [(0, 3, "Привет!"), (10, 15, "Как дела?")]
    assert calls == [3]


def test_missing_keys_do_not_require_gemini_or_fail_validation():
    settings = api.PackSettings(pack_episode=True, pct_episode=100, pct_songs=0,
                                episode_ru_subtitles=True)
    assert not settings.validate()


def test_episode_checkbox_shares_and_ru_setting_round_trip(qapp):
    tab = animepack_tab.AnimePackTab(main_window=_FakeMain())
    try:
        assert not tab.chk_episode.isChecked() and not tab.chk_episode_ru.isChecked()
        tab.chk_episode.setChecked(True)
        tab.chk_episode_ru.setChecked(True)
        tab.mix.set_shares({"episode": 100})
        settings = tab.collect()
        assert settings.pack_episode and settings.pct_episode == 100
        assert settings.episode_ru_subtitles
        tab.apply_settings(api.PackSettings.from_dict(settings.to_dict()))
        assert tab.collect().mix_shares[api.EPISODE_KIND] == 100
        assert "Отрывков серий" in tab.lbl_left.text()
        tab.chk_episode.setChecked(False)
        assert tab.collect().mix_shares[api.EPISODE_KIND] == 0
    finally:
        tab.cleanup()
