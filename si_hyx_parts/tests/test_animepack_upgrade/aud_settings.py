# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_aud_settings. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


def _aud_settings(**kw):
    base = dict(strip_specials=False, add_titles=False, compress_images=False,
                strip_repeated_text=False, drop_empty_questions=False,
                compress_audio=True, audio_min_mb=0.1, audio_kbps=192,
                drop_unused=False)
    base.update(kw)
    return _api.UpgradeSettings(**base)

_aud_settings.__module__ = _api.__name__
_api._aud_settings = _aud_settings

def _fake_opus(monkeypatch, size: int = 5000, kbps: int = 320):
    """ffmpeg и ffprobe в тестах не зовём: важно поведение вокруг них."""
    def fake_encode(self, raw, out):
        with open(out, "wb") as f:
            f.write(b"O" * size)
        return True

    monkeypatch.setattr(_api.PackUpgrader, "_to_opus", fake_encode)
    monkeypatch.setattr(_api.PackUpgrader, "_audio_kbps",
                        lambda self, raw, size=0: kbps)

_fake_opus.__module__ = _api.__name__
_api._fake_opus = _fake_opus

def _q5_audio(price: int, name: str) -> str:
    return (f'<question price="{price}"><params>'
            '<param name="question" type="content">'
            f'<item type="audio" isRef="True">{name}</item></param>'
            "</params><right><answer>Ответ</answer></right></question>")

_q5_audio.__module__ = _api.__name__
_api._q5_audio = _q5_audio

def test_heavy_audio_becomes_opus_and_ref_follows(tmp_path, monkeypatch):
    _api._fake_opus(monkeypatch)
    content = _api._pack(_api._q5_audio(100, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.mp3": _api.BIG_AUDIO})
    result = _api.PackUpgrader(src, _api._aud_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        assert "Audio/песня.opus" in names and "Audio/песня.mp3" not in names
        root, ns = _api.parse_content(zf.read("content.xml"))
    assert root.find(f'.//{_api.tag_fn(ns)("item")}').text == "песня.opus"
    assert len(result.audios) == 1 and result.heavy_audio == 1
    assert result.saved_audio_bytes == len(_api.BIG_AUDIO) - 5000
    assert "320 кбит" in result.audios[0].before
    assert "opus 192 кбит" in result.audios[0].after

test_heavy_audio_becomes_opus_and_ref_follows.__module__ = _api.__name__
_api.test_heavy_audio_becomes_opus_and_ref_follows = test_heavy_audio_becomes_opus_and_ref_follows

def test_audio_that_is_already_quiet_enough_is_left_alone(tmp_path, monkeypatch):
    """Битрейт исходника не выше целевого — перекод только испортил бы звук."""
    _api._fake_opus(monkeypatch, kbps=128)
    content = _api._pack(_api._q5_audio(100, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.mp3": _api.BIG_AUDIO})
    result = _api.PackUpgrader(src, _api._aud_settings(audio_kbps=192),
                          api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/песня.mp3") == _api.BIG_AUDIO
    assert result.audios == [] and result.heavy_audio == 1

test_audio_that_is_already_quiet_enough_is_left_alone.__module__ = _api.__name__
_api.test_audio_that_is_already_quiet_enough_is_left_alone = test_audio_that_is_already_quiet_enough_is_left_alone

def test_unknown_bitrate_is_recoded_anyway(tmp_path, monkeypatch):
    _api._fake_opus(monkeypatch, kbps=0)
    content = _api._pack(_api._q5_audio(100, "песня.wav"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.wav": _api.BIG_AUDIO})
    result = _api.PackUpgrader(src, _api._aud_settings(), api=_api.FakeApi()).run()
    assert len(result.audios) == 1
    assert "кбит," not in result.audios[0].before      # неизвестного не пишем

test_unknown_bitrate_is_recoded_anyway.__module__ = _api.__name__
_api.test_unknown_bitrate_is_recoded_anyway = test_unknown_bitrate_is_recoded_anyway

def test_light_audio_and_video_are_left_alone(tmp_path, monkeypatch):
    _api._fake_opus(monkeypatch)
    media = {"Audio/тихая.mp3": b"S" * 100, "Video/ролик.mp4": _api.BIG_AUDIO}
    src = _api._siq(tmp_path, _api._pack(_api._q5(100)), media=media)
    result = _api.PackUpgrader(src, _api._aud_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/тихая.mp3") == b"S" * 100
        assert zf.read("Video/ролик.mp4") == _api.BIG_AUDIO   # ролик не трогаем
    assert result.audios == [] and result.heavy_audio == 0

test_light_audio_and_video_are_left_alone.__module__ = _api.__name__
_api.test_light_audio_and_video_are_left_alone = test_light_audio_and_video_are_left_alone

def test_audio_that_got_heavier_is_kept_as_is(tmp_path, monkeypatch):
    _api._fake_opus(monkeypatch, size=len(_api.BIG_AUDIO) + 1)
    content = _api._pack(_api._q5_audio(100, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.mp3": _api.BIG_AUDIO})
    result = _api.PackUpgrader(src, _api._aud_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/песня.mp3") == _api.BIG_AUDIO
    assert result.audios == [] and result.heavy_audio == 1

test_audio_that_got_heavier_is_kept_as_is.__module__ = _api.__name__
_api.test_audio_that_got_heavier_is_kept_as_is = test_audio_that_got_heavier_is_kept_as_is

def test_taken_opus_name_does_not_clobber_the_neighbour(tmp_path, monkeypatch):
    _api._fake_opus(monkeypatch)
    content = _api._pack(_api._q5_audio(100, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.mp3": _api.BIG_AUDIO,
                                         "Audio/песня.opus": b"OLD"})
    result = _api.PackUpgrader(src, _api._aud_settings(), api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/песня.opus") == b"OLD"
        assert "Audio/песня (2).opus" in zf.namelist()
        root, ns = _api.parse_content(zf.read("content.xml"))
    assert root.find(f'.//{_api.tag_fn(ns)("item")}').text == "песня (2).opus"

test_taken_opus_name_does_not_clobber_the_neighbour.__module__ = _api.__name__
_api.test_taken_opus_name_does_not_clobber_the_neighbour = test_taken_opus_name_does_not_clobber_the_neighbour

def test_audio_untouched_when_function_is_off(tmp_path, monkeypatch):
    _api._fake_opus(monkeypatch)
    content = _api._pack(_api._q5_audio(100, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.mp3": _api.BIG_AUDIO})
    result = _api.PackUpgrader(src, _api._aud_settings(compress_audio=False,
                                             strip_specials=True),
                          api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/песня.mp3") == _api.BIG_AUDIO
    assert result.audios == [] and result.heavy_audio == 0

test_audio_untouched_when_function_is_off.__module__ = _api.__name__
_api.test_audio_untouched_when_function_is_off = test_audio_untouched_when_function_is_off

def test_audio_and_images_do_not_fight_for_names(tmp_path, monkeypatch):
    """Обе функции разом: и картинка, и дорожка меняют имя, ссылки идут следом."""
    _api._fake_opus(monkeypatch)
    _api._fake_avif(monkeypatch)
    content = _api._pack(_api._q5_image(100, "кадр.jpg") + _api._q5_audio(200, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Images/кадр.jpg": _api.HEAVY,
                                         "Audio/песня.mp3": _api.BIG_AUDIO})
    result = _api.PackUpgrader(src, _api._aud_settings(compress_images=True,
                                             image_min_mb=0.1,
                                             image_limit_kb=50),
                          api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
        assert "Images/кадр.avif" in names and "Audio/песня.opus" in names
        root, ns = _api.parse_content(zf.read("content.xml"))
    refs = [i.text for i in root.findall(f'.//{_api.tag_fn(ns)("item")}')]
    assert refs == ["кадр.avif", "песня.opus"]

test_audio_and_images_do_not_fight_for_names.__module__ = _api.__name__
_api.test_audio_and_images_do_not_fight_for_names = test_audio_and_images_do_not_fight_for_names

def test_audio_is_reported(tmp_path, monkeypatch):
    _api._fake_opus(monkeypatch)
    content = _api._pack(_api._q5_audio(100, "песня.mp3"))
    src = _api._siq(tmp_path, content, media={"Audio/песня.mp3": _api.BIG_AUDIO})
    lines = _api.example_lines(_api.PackUpgrader(src, _api._aud_settings(),
                                       api=_api.FakeApi()).run())
    assert any("Дорожек перекодировано в opus: 1" in line for line in lines)

test_audio_is_reported.__module__ = _api.__name__
_api.test_audio_is_reported = test_audio_is_reported

# ── Разбор ответа ffprobe ────────────────────────────────────────────────────
def test_probe_kbps_takes_the_stream_bitrate_first():
    text = "bit_rate=320000\nbit_rate=321000\nduration=100.0\n"
    assert _api.parse_probe_kbps(text) == 320

test_probe_kbps_takes_the_stream_bitrate_first.__module__ = _api.__name__
_api.test_probe_kbps_takes_the_stream_bitrate_first = test_probe_kbps_takes_the_stream_bitrate_first

def test_probe_kbps_falls_back_to_size_and_duration():
    """wav и часть ogg битрейта не отдают — считаем сами."""
    text = "bit_rate=N/A\nduration=10.0\n"
    assert _api.parse_probe_kbps(text, size=1_411_000 // 8 * 10) == 1411

test_probe_kbps_falls_back_to_size_and_duration.__module__ = _api.__name__
_api.test_probe_kbps_falls_back_to_size_and_duration = test_probe_kbps_falls_back_to_size_and_duration

def test_probe_kbps_gives_up_quietly():
    assert _api.parse_probe_kbps("", size=0) == 0
    assert _api.parse_probe_kbps("bit_rate=N/A\nduration=N/A\n", size=100) == 0

test_probe_kbps_gives_up_quietly.__module__ = _api.__name__
_api.test_probe_kbps_gives_up_quietly = test_probe_kbps_gives_up_quietly

def test_nearest_bitrate_snaps_to_the_list():
    assert _api.nearest_bitrate(192) == 192
    assert _api.nearest_bitrate(200) == 192
    assert _api.nearest_bitrate(1000) == 256
    assert _api.nearest_bitrate(1) == 8
    assert _api.nearest_bitrate("нет") == 192

test_nearest_bitrate_snaps_to_the_list.__module__ = _api.__name__
_api.test_nearest_bitrate_snaps_to_the_list = test_nearest_bitrate_snaps_to_the_list

# ── Скорость: перенос записей, потоки, фоновые постеры ───────────────────────
def test_media_keeps_its_compression_and_bytes(tmp_path):
    """Записи переносятся В ТОМ ЖЕ ВИДЕ, не распаковываясь: и способ сжатия, и
    байты те же. На этом стоит вся скорость сборки — распаковать сотню
    мегабайт mp3 и тут же сжать обратно дороже всей остальной работы."""
    path = tmp_path / "d.siq"
    blob = b"mp3-bytes" * 5000
    with _api.zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", _api._pack(_api._q5(100)))
        zf.writestr("Audio/a.mp3", blob, _api.zipfile.ZIP_DEFLATED)
        zf.writestr("Video/v.mp4", blob, _api.zipfile.ZIP_STORED)
    result = _api.PackUpgrader(str(path), _api.UpgradeSettings(add_titles=False),
                          api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.testzip() is None
        assert zf.read("Audio/a.mp3") == blob
        assert zf.read("Video/v.mp4") == blob
        assert zf.getinfo("Audio/a.mp3").compress_type == _api.zipfile.ZIP_DEFLATED
        assert zf.getinfo("Video/v.mp4").compress_type == _api.zipfile.ZIP_STORED

test_media_keeps_its_compression_and_bytes.__module__ = _api.__name__
_api.test_media_keeps_its_compression_and_bytes = test_media_keeps_its_compression_and_bytes

def test_media_survives_when_the_fast_copy_gives_up(tmp_path, monkeypatch):
    """Быстрый перенос сдался (шифрование, битый заголовок) — запись кладётся
    обычным путём, а не теряется."""
    import animepack_upgrade as U
    monkeypatch.setattr(U, "copy_zip_entry", lambda *a, **kw: False)
    content = _api._pack(_api._q5(100))
    src = _api._siq(tmp_path, content, media={"Audio/a.opus": b"opus-bytes"})
    result = _api.PackUpgrader(src, _api.UpgradeSettings(add_titles=False),
                          api=_api.FakeApi()).run()
    with _api.zipfile.ZipFile(result.path) as zf:
        assert zf.read("Audio/a.opus") == b"opus-bytes"

test_media_survives_when_the_fast_copy_gives_up.__module__ = _api.__name__
_api.test_media_survives_when_the_fast_copy_gives_up = test_media_survives_when_the_fast_copy_gives_up

def test_fast_copy_leaves_no_garbage_when_it_gives_up(tmp_path):
    """Оборвавшийся перенос откатывается: недописанные байты не должны остаться
    в архиве, поверх них сразу пишет обычный путь."""
    src_path = tmp_path / "a.zip"
    with _api.zipfile.ZipFile(src_path, "w") as zf:
        zf.writestr("a.bin", b"x" * 100, _api.zipfile.ZIP_STORED)
    out = tmp_path / "b.zip"
    with _api.zipfile.ZipFile(src_path) as src, _api.zipfile.ZipFile(out, "w") as dst:
        info = src.getinfo("a.bin")
        info.compress_size = 10_000          # запись «оборвётся» на середине
        assert _api.copy_zip_entry(src, dst, info) is False
        dst.writestr("a.bin", b"x" * 100)
    with _api.zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["a.bin"]
        assert zf.read("a.bin") == b"x" * 100
        assert zf.testzip() is None

test_fast_copy_leaves_no_garbage_when_it_gives_up.__module__ = _api.__name__
_api.test_fast_copy_leaves_no_garbage_when_it_gives_up = test_fast_copy_leaves_no_garbage_when_it_gives_up

def test_encrypted_entry_is_not_touched_by_the_fast_copy(tmp_path):
    src_path = tmp_path / "a.zip"
    with _api.zipfile.ZipFile(src_path, "w") as zf:
        zf.writestr("a.bin", b"x" * 100)
    with _api.zipfile.ZipFile(src_path) as src, \
            _api.zipfile.ZipFile(tmp_path / "b.zip", "w") as dst:
        info = src.getinfo("a.bin")
        info.flag_bits |= 0x01               # «запись зашифрована»
        assert _api.copy_zip_entry(src, dst, info) is False

test_encrypted_entry_is_not_touched_by_the_fast_copy.__module__ = _api.__name__
_api.test_encrypted_entry_is_not_touched_by_the_fast_copy = test_encrypted_entry_is_not_touched_by_the_fast_copy

def test_media_jobs_never_exceeds_the_cores():
    """На двухъядерном ноутбуке шесть ffmpeg сразу только толкались бы."""
    assert _api.media_jobs(6) <= (_api.os.cpu_count() or 1)
    assert _api.media_jobs(6) >= 1 and _api.media_jobs(0) == 1

test_media_jobs_never_exceeds_the_cores.__module__ = _api.__name__
_api.test_media_jobs_never_exceeds_the_cores = test_media_jobs_never_exceeds_the_cores

def test_images_keep_pack_order_when_encoded_in_parallel(tmp_path, monkeypatch):
    """Кодируются картинки в несколько потоков, а имена и порядок в отчёте — те
    же, что в паке: чья кодировка кончилась первой, значения не имеет."""
    _api._fake_avif(monkeypatch)
    names = [f"кадр{i}.jpg" for i in range(6)]
    media = {f"Images/{n}": _api.HEAVY for n in names}
    content = _api._pack("".join(_api._q5_image(100 * (i + 1), n)
                            for i, n in enumerate(names)))
    result = _api.PackUpgrader(_api._siq(tmp_path, content, media=media),
                          _api._img_settings(), api=_api.FakeApi()).run()
    assert [c.theme_name for c in result.images] == names
    assert [c.title for c in result.images] == [f"кадр{i}.avif" for i in range(6)]
    assert [c.order for c in result.images] == list(range(6, 12))
    with _api.zipfile.ZipFile(result.path) as zf:
        assert all(f"Images/кадр{i}.avif" in zf.namelist() for i in range(6))

test_images_keep_pack_order_when_encoded_in_parallel.__module__ = _api.__name__
_api.test_images_keep_pack_order_when_encoded_in_parallel = test_images_keep_pack_order_when_encoded_in_parallel

def test_tracks_keep_pack_order_when_encoded_in_parallel(tmp_path, monkeypatch):
    _api._fake_opus(monkeypatch)
    names = [f"песня{i}.mp3" for i in range(6)]
    media = {f"Audio/{n}": _api.BIG_AUDIO for n in names}
    content = _api._pack("".join(_api._q5_audio(100 * (i + 1), n)
                            for i, n in enumerate(names)))
    result = _api.PackUpgrader(_api._siq(tmp_path, content, media=media),
                          _api._aud_settings(), api=_api.FakeApi()).run()
    assert [c.theme_name for c in result.audios] == names
    assert [c.title for c in result.audios] == [f"песня{i}.opus"
                                                for i in range(6)]
    with _api.zipfile.ZipFile(result.path) as zf:
        root, ns = _api.parse_content(zf.read("content.xml"))
    assert [i.text for i in root.iter(_api.tag_fn(ns)("item"))] == \
        [f"песня{i}.opus" for i in range(6)]

test_tracks_keep_pack_order_when_encoded_in_parallel.__module__ = _api.__name__
_api.test_tracks_keep_pack_order_when_encoded_in_parallel = test_tracks_keep_pack_order_when_encoded_in_parallel

def test_a_track_that_failed_does_not_shift_the_others(tmp_path, monkeypatch):
    """Одна кодировка сорвалась — соседние всё равно на своих местах."""
    _api._fake_opus(monkeypatch)
    real = _api.PackUpgrader._to_opus

    def flaky(self, raw, out):
        if _api.os.path.getsize(raw) == len(_api.BIG_AUDIO) + 1:   # вторая дорожка
            return False
        return real(self, raw, out)

    monkeypatch.setattr(_api.PackUpgrader, "_to_opus", flaky)
    media = {"Audio/a.mp3": _api.BIG_AUDIO, "Audio/b.mp3": _api.BIG_AUDIO + b"S",
             "Audio/c.mp3": _api.BIG_AUDIO}
    content = _api._pack(_api._q5_audio(100, "a.mp3") + _api._q5_audio(200, "b.mp3")
                    + _api._q5_audio(300, "c.mp3"))
    result = _api.PackUpgrader(_api._siq(tmp_path, content, media=media),
                          _api._aud_settings(), api=_api.FakeApi()).run()
    assert [c.theme_name for c in result.audios] == ["a.mp3", "c.mp3"]
    with _api.zipfile.ZipFile(result.path) as zf:
        assert "Audio/b.mp3" in zf.namelist()      # осталась как была
        assert "Audio/b.opus" not in zf.namelist()

test_a_track_that_failed_does_not_shift_the_others.__module__ = _api.__name__
_api.test_a_track_that_failed_does_not_shift_the_others = test_a_track_that_failed_does_not_shift_the_others

# ── Постер готовится в фоне, пока идёт опрос Shikimori ───────────────────────
def test_poster_size_reaches_the_report(tmp_path, monkeypatch):
    """Ссылка в вопрос пишется раньше, чем постер скачан, — но размер в отчёте
    всё равно настоящий."""
    _api._fake_poster(monkeypatch, size=2048)
    content = _api._pack(_api._q5(100, answer="Блич") + _api._q5(200, answer="Bleach"))
    result = _api._run(tmp_path, content, _api._poster_settings(), api=_api.FakeApi([_api.POSTERED]))
    assert [c.after for c in result.posters] == ["постер, 2 КБ"] * 2

test_poster_size_reaches_the_report.__module__ = _api.__name__
_api.test_poster_size_reaches_the_report = test_poster_size_reaches_the_report
