# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""test_unused_media_is_dropped_and_referenced_survives. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def test_unused_media_is_dropped_and_referenced_survives(tmp_path):
    content = _api._pack(_api._q5_image(100, "нужная.jpg"))
    media = {"Images/нужная.jpg": b"J" * 10, "Images/лишняя.jpg": b"J" * 500,
             "Audio/забытая.mp3": b"S" * 700}
    result = _api.PackUpgrader(_api._siq(tmp_path, content, media=media),
                          _api.ONLY_UNUSED, api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
    assert "Images/нужная.jpg" in names
    assert "Images/лишняя.jpg" not in names and "Audio/забытая.mp3" not in names
    assert {c.theme_name for c in result.unused} == {"лишняя.jpg",
                                                     "забытая.mp3"}
    assert result.saved_unused_bytes == 1200

test_unused_media_is_dropped_and_referenced_survives.__module__ = _api.__name__
_api.test_unused_media_is_dropped_and_referenced_survives = test_unused_media_is_dropped_and_referenced_survives

def test_pack_logo_is_not_garbage(tmp_path):
    """Логотип пака записан атрибутом, а не ссылкой в вопросе: ссылок «из
    вопросов» на него нет, но выкидывать его нельзя."""
    content = ('<?xml version="1.0" encoding="utf-8"?>\n'
               '<package name="Пак" version="5" logo="@лого.png">'
               '<rounds><round name="Р"><themes><theme name="Т"><questions>'
               + _api._q5_image(100, "нужная.jpg") +
               "</questions></theme></themes></round></rounds></package>")
    media = {"Images/нужная.jpg": b"J" * 10, "Images/лого.png": b"L" * 10}
    result = _api.PackUpgrader(_api._siq(tmp_path, content, media=media),
                          _api.ONLY_UNUSED, api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert "Images/лого.png" in zf.namelist()
    assert result.unused == []

test_pack_logo_is_not_garbage.__module__ = _api.__name__
_api.test_pack_logo_is_not_garbage = test_pack_logo_is_not_garbage

def test_service_files_are_never_garbage(tmp_path):
    media = {"Texts/authors.xml": b"<authors/>",
             "[Content_Types].xml": b"<Types/>"}
    result = _api.PackUpgrader(_api._siq(tmp_path, _api._pack(_api._q5(100)), media=media),
                          _api.ONLY_UNUSED, api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
    assert "Texts/authors.xml" in names and "[Content_Types].xml" in names
    assert result.unused == []

test_service_files_are_never_garbage.__module__ = _api.__name__
_api.test_service_files_are_never_garbage = test_service_files_are_never_garbage

def test_all_media_unused_touches_nothing(tmp_path):
    """Ни одной ссылки на весь пак — значит ссылки записаны как-то иначе, а не
    пак из одного мусора: не трогаем ничего."""
    media = {"Images/a.jpg": b"J", "Images/b.jpg": b"J"}
    result = _api.PackUpgrader(_api._siq(tmp_path, _api._pack(_api._q5(100)), media=media),
                          _api.ONLY_UNUSED, api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert {"Images/a.jpg", "Images/b.jpg"} <= set(zf.namelist())
    assert result.unused == [] and result.saved_unused_bytes == 0

test_all_media_unused_touches_nothing.__module__ = _api.__name__
_api.test_all_media_unused_touches_nothing = test_all_media_unused_touches_nothing

def test_recoded_image_is_not_counted_as_garbage(tmp_path, monkeypatch):
    """Пережатая картинка лежит уже под новым именем — по старому её не зовут,
    но мусором она от этого не становится."""
    _api._fake_avif(monkeypatch)
    content = _api._pack(_api._q5_image(100, "кадр.jpg"))
    src = _api._siq(tmp_path, content, media={"Images/кадр.jpg": _api.HEAVY})
    result = _api.PackUpgrader(src, _api._img_settings(drop_unused=True),
                          api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert "Images/кадр.avif" in zf.namelist()
    assert result.unused == []

test_recoded_image_is_not_counted_as_garbage.__module__ = _api.__name__
_api.test_recoded_image_is_not_counted_as_garbage = test_recoded_image_is_not_counted_as_garbage

def test_percent_encoded_name_is_matched_to_its_reference(tmp_path):
    content = _api._pack(_api._q5_image(100, "кадр.jpg"))
    src = _api._siq(tmp_path, content,
               media={"Images/" + _api.escape_uri_string("кадр.jpg"): b"J" * 10})
    result = _api.PackUpgrader(src, _api.ONLY_UNUSED, api=_api.FakeApi()).run()
    assert result.unused == []

test_percent_encoded_name_is_matched_to_its_reference.__module__ = _api.__name__
_api.test_percent_encoded_name_is_matched_to_its_reference = test_percent_encoded_name_is_matched_to_its_reference

def test_unused_helpers_are_pure():
    assert _api.entry_basename("Images/%D0%BA.jpg") == "к.jpg"
    assert _api.entry_basename("Images\\a.jpg") == "a.jpg"
    assert _api.is_media_entry("Images/a.JPG") and _api.is_media_entry("Video/v.mp4")
    assert not _api.is_media_entry("content.xml")
    assert not _api.is_media_entry("Texts/authors.xml")
    root = _api.ET.fromstring('<package logo="@a.png"><item>b.jpg</item>'
                         "<atom>@c.mp3</atom></package>")
    refs = _api.referenced_names(root)
    assert {"a.png", "b.jpg", "c.mp3"} <= refs
    names = ["Images/a.png", "Images/b.jpg", "Audio/c.mp3", "Video/d.mp4",
             "Images/e.jpg", "content.xml"]
    assert _api.unused_entries(names, refs) == ["Video/d.mp4", "Images/e.jpg"]
    assert _api.unused_entries(names, refs, keep=["Video/d.mp4"]) == ["Images/e.jpg"]

test_unused_helpers_are_pure.__module__ = _api.__name__
_api.test_unused_helpers_are_pure = test_unused_helpers_are_pure

def test_unused_is_reported(tmp_path):
    content = _api._pack(_api._q5_image(100, "нужная.jpg"))
    media = {"Images/нужная.jpg": b"J", "Images/лишняя.jpg": b"J" * 2048}
    result = _api.PackUpgrader(_api._siq(tmp_path, content, media=media),
                          _api.ONLY_UNUSED, api=_api.FakeApi()).run()
    lines = _api.example_lines(result)
    assert any("Неиспользуемых файлов удалено: 1" in l for l in lines)
    assert any("лишняя.jpg" in l for l in lines)

test_unused_is_reported.__module__ = _api.__name__
_api.test_unused_is_reported = test_unused_is_reported

# ── Нормализация громкости ───────────────────────────────────────────────────
def test_loudnorm_is_off_unless_asked():
    s = _api.UpgradeSettings()
    assert s.audio_norm is False
    assert _api.loudnorm_filter(s) == ""
    # Фикс раскладки каналов идёт всегда: libopus не берёт «боковые» раскладки.
    assert _api.audio_filter_chain(s).startswith("aformat=")

test_loudnorm_is_off_unless_asked.__module__ = _api.__name__
_api.test_loudnorm_is_off_unless_asked = test_loudnorm_is_off_unless_asked

def test_loudnorm_string_is_the_one_from_the_process_tab():
    s = _api.UpgradeSettings(audio_norm=True)
    assert _api.loudnorm_filter(s) == "loudnorm=I=-20:LRA=11:TP=-1.5"
    assert _api.audio_filter_chain(s).startswith("loudnorm=I=-20:LRA=11:TP=-1.5,")
    tuned = _api.UpgradeSettings(audio_norm=True, audio_norm_i=-16.0,
                            audio_norm_lra=7.0, audio_norm_tp=-2.0)
    assert _api.loudnorm_filter(tuned) == "loudnorm=I=-16:LRA=7:TP=-2"

test_loudnorm_string_is_the_one_from_the_process_tab.__module__ = _api.__name__
_api.test_loudnorm_string_is_the_one_from_the_process_tab = test_loudnorm_string_is_the_one_from_the_process_tab

def test_norm_recodes_even_a_track_that_is_quiet_enough(tmp_path, monkeypatch):
    """Пропущенная дорожка осталась бы с прежней громкостью — то есть громче
    или тише всех соседних: с нормализацией оговорка «и так N кбит» снимается."""
    _api._fake_opus(monkeypatch, kbps=128)
    content = _api._pack(_api._q5_audio(100, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.mp3": _api.BIG_AUDIO})
    result = _api.PackUpgrader(src, _api._aud_settings(audio_kbps=192, audio_norm=True),
                          api=_api.FakeApi()).run()
    assert len(result.audios) == 1
    with _api.zipfile.ZipFile(result.path) as zf:
        assert "Audio/песня.opus" in zf.namelist()

test_norm_recodes_even_a_track_that_is_quiet_enough.__module__ = _api.__name__
_api.test_norm_recodes_even_a_track_that_is_quiet_enough = test_norm_recodes_even_a_track_that_is_quiet_enough

def test_norm_keeps_the_track_even_if_it_got_heavier(tmp_path, monkeypatch):
    _api._fake_opus(monkeypatch, size=len(_api.BIG_AUDIO) + 10, kbps=320)
    content = _api._pack(_api._q5_audio(100, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.mp3": _api.BIG_AUDIO})
    result = _api.PackUpgrader(src, _api._aud_settings(audio_norm=True),
                          api=_api.FakeApi()).run()
    assert len(result.audios) == 1
    # Без нормализации та же дорожка осталась бы исходной.
    plain = _api.PackUpgrader(src, _api._aud_settings(), api=_api.FakeApi()).run()
    assert plain.audios == []

test_norm_keeps_the_track_even_if_it_got_heavier.__module__ = _api.__name__
_api.test_norm_keeps_the_track_even_if_it_got_heavier = test_norm_keeps_the_track_even_if_it_got_heavier

def test_norm_goes_into_the_ffmpeg_line(tmp_path, monkeypatch):
    seen = []

    def fake_run(cmd, should_stop=None, timeout=0, capture=False):
        seen.append(list(cmd))
        with open(cmd[-1], "wb") as f:
            f.write(b"O" * 100)
        return 0, ""

    monkeypatch.setattr("animepack_upgrade.run_hidden", fake_run)
    monkeypatch.setattr(_api.PackUpgrader, "_audio_kbps", lambda self, r, size=0: 320)
    content = _api._pack(_api._q5_audio(100, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.mp3": _api.BIG_AUDIO})
    _api.PackUpgrader(src, _api._aud_settings(audio_norm=True), api=_api.FakeApi()).run()
    line = " ".join(seen[-1])
    assert "loudnorm=I=-20:LRA=11:TP=-1.5" in line and "libopus" in line

test_norm_goes_into_the_ffmpeg_line.__module__ = _api.__name__
_api.test_norm_goes_into_the_ffmpeg_line = test_norm_goes_into_the_ffmpeg_line
