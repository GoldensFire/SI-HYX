"""Narrated descriptions keep one audio item and survive provider quotas."""
from contextlib import nullcontext
from types import SimpleNamespace
import base64
import zipfile
import xml.etree.ElementTree as ET
import pytest

import animepack as ap
from si_hyx_parts.animepack.description_tts import DescriptionSpeech, SpeechError
from si_hyx_parts.animepack.description_gemini_tts import TTS_MODELS, synthesize


def _settings(**values):
    data = dict(rounds=1, themes=1, questions=1, pct_songs=0,
                pack_description_audio=True, pct_description_audio=100,
                gemini_key="gemini", elevenlabs_key="eleven",
                description_language="en", description_tts_first="elevenlabs",
                elevenlabs_voice="voice", google_tts_credentials="")
    data.update(values)
    return ap.PackSettings(**data)


def _candidate():
    return ap.SongCandidate(song={}, kind=ap.DESCRIPTION_AUDIO_KIND,
                            anime={"id": "1", "malId": "1", "name": "Secret Show",
                                   "russian": "Тайное шоу", "url": "https://shikimori.io/animes/1",
                                   "airedOn": {"year": 2020}}, price=100)


def test_quota_and_xml_have_one_audio_item_only():
    settings = _settings()
    assert settings.question_quotas[ap.DESCRIPTION_AUDIO_KIND] == 1
    cand = _candidate()
    cand.description_audio_ext = "mp3"
    root = ET.fromstring(ap.build_content_xml([cand], settings))
    question = next(p for p in root.iter() if p.tag.endswith("param")
                    and p.attrib.get("name") == "question")
    items = list(question)
    assert len(items) == 1
    assert items[0].attrib["type"] == "audio"
    assert items[0].text == cand.audio_out


def test_package_contains_narration_file(tmp_path):
    settings = _settings()
    cand = _candidate()
    cand.description_audio_ext = "mp3"
    folder = tmp_path / "work"
    (folder / "Audio").mkdir(parents=True)
    (folder / "Audio" / cand.audio_out).write_bytes(b"ID3sample")
    gen = object.__new__(ap.AnimePackGenerator)
    gen.s, gen.folder = settings, str(folder)
    target = gen.write_package([cand], str(tmp_path / "audio.siq"))
    with zipfile.ZipFile(target) as package:
        assert package.read(f"Audio/{cand.audio_out}") == b"ID3sample"
        root = ET.fromstring(package.read("content.xml"))
        question = next(p for p in root.iter() if p.tag.endswith("param")
                        and p.attrib.get("name") == "question")
        assert len(question) == 1 and question[0].attrib["type"] == "audio"


def test_shikimori_description_is_translated_then_saved_as_audio(tmp_path, monkeypatch):
    cand = _candidate()
    calls = []

    class Gemini:
        def generate_json(self, prompt, schema):
            calls.append(prompt)
            assert schema["required"] == ["text"]
            return {"text": "A hidden world opens when a young scholar finds a strange map. "
                            "Her friends must cross the sea before a storm arrives."}

    gen = object.__new__(ap.AnimePackGenerator)
    gen.s = _settings()
    gen.gemini = Gemini()
    gen.shikimori = SimpleNamespace(anime_description=lambda ident:
                                    "[b]Secret Show[/b] follows a young scholar "
                                    "who finds a strange map. Her friends sail "
                                    "across the sea before a storm arrives.")
    gen.description_tts = SimpleNamespace(
        synthesize=lambda text, language: (b"ID3fake", "mp3"))
    monkeypatch.setattr(
        "si_hyx_parts.animepack.description_audio_encode.encode",
        lambda _gen, _data, _ext, path: open(path, "wb").write(b"OggSfake"))
    gen.folder = str(tmp_path)
    gen._timed = lambda _: nullcontext()
    gen._log_rare = lambda *args: (_ for _ in ()).throw(AssertionError(args))
    assert gen.make_description_audio(cand)
    assert cand.audio_out.endswith(".opus")
    assert (tmp_path / "Audio" / cand.audio_out).read_bytes() == b"OggSfake"
    assert "Secret Show" not in calls[0]
    assert cand.source_link == "https://shikimori.io/animes/1"


def test_missing_shikimori_id_never_uses_mal_id(tmp_path):
    cand = _candidate()
    cand.anime.pop("id")
    gen = object.__new__(ap.AnimePackGenerator)
    gen.gemini = object()
    gen.shikimori = SimpleNamespace(anime_description=lambda _ident:
                                    (_ for _ in ()).throw(AssertionError("wrong title")))
    gen._log_rare = lambda *_args: None
    assert not gen.make_description_audio(cand)


def test_translated_synonym_cannot_reveal_answer(tmp_path):
    cand = _candidate()
    cand.anime["synonyms"] = ["Hidden Wonder"]
    gen = object.__new__(ap.AnimePackGenerator)
    gen.s = _settings()
    gen.gemini = SimpleNamespace(generate_json=lambda *_: {"text":
        "Hidden Wonder follows a scholar who finds a strange map. "
        "Her friends cross the sea before a terrible storm arrives."})
    gen.shikimori = SimpleNamespace(anime_description=lambda _:
                                    "A young scholar finds an ancient map, "
                                    "and her friends must cross a distant sea.")
    gen.description_tts = SimpleNamespace(synthesize=lambda _:
                                          (_ for _ in ()).throw(AssertionError("leak")))
    gen._log_rare = lambda *_: None
    assert not gen.make_description_audio(cand)
    assert not (tmp_path / "Audio").exists()


def test_eleven_quota_switches_to_google_for_rest_of_run():
    class Response:
        def __init__(self, code, body):
            self.status_code, self.body = code, body
            self.content = b""

        def json(self):
            return self.body

    class Session:
        def __init__(self):
            self.urls = []

        def post(self, url, **kwargs):
            self.urls.append(url)
            if "elevenlabs" in url:
                return Response(401, {"detail": {"status": "quota_exceeded"}})
            return Response(200, {"audioContent": base64.b64encode(b"ID3google").decode()})

    session = Session()
    speech = DescriptionSpeech(_settings(), session, lambda _: None)
    speech._google_headers = lambda: {}
    assert speech.synthesize("narration") == (b"ID3google", "mp3")
    assert speech.synthesize("narration") == (b"ID3google", "mp3")
    assert sum("elevenlabs" in url for url in session.urls) == 1


def test_google_quota_switches_back_to_eleven():
    class Session:
        def __init__(self):
            self.urls = []

        def post(self, url, **kwargs):
            self.urls.append(url)
            if "googleapis" in url:
                return SimpleNamespace(status_code=429,
                                       json=lambda: {"error": {
                                           "status": "RESOURCE_EXHAUSTED",
                                           "message": "Quota exceeded"}})
            return SimpleNamespace(status_code=200, content=b"ID3eleven")

    session = Session()
    speech = DescriptionSpeech(_settings(description_tts_first="google"),
                               session, lambda _: None)
    speech._google_headers = lambda: {}
    assert speech.synthesize("narration") == (b"ID3eleven", "mp3")
    assert speech.synthesize("narration") == (b"ID3eleven", "mp3")
    assert sum("texttospeech.googleapis.com" in url for url in session.urls) == 1


def test_google_failure_tries_gemini_before_eleven():
    calls = []

    class Session:
        def post(self, url, **kwargs):
            calls.append(url)
            assert "generativelanguage.googleapis.com" in url
            return SimpleNamespace(status_code=200, json=lambda: {
                "steps": [{"content": [{"type": "audio", "data":
                    base64.b64encode(b"RIFFtestWAVE").decode()}]}]})

    speech = DescriptionSpeech(_settings(description_tts_first="google"),
                               Session(), lambda _: None)
    speech._google_headers = lambda: (_ for _ in ()).throw(
        SpeechError("нет учётных данных Google Cloud", exhausted=True))
    assert speech.synthesize("narration") == (b"RIFFtestWAVE", "wav")
    assert len(calls) == 1
    assert ap.PackSettings().description_tts_first == "gemini"


def test_temporary_429_retries_first_provider_after_cooldown(monkeypatch):
    import si_hyx_parts.animepack.description_tts as tts

    clock = [100.0]
    monkeypatch.setattr(tts, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    class Session:
        def __init__(self):
            self.eleven_calls = 0

        def post(self, url, **_kwargs):
            if "elevenlabs" in url:
                self.eleven_calls += 1
                if self.eleven_calls == 1:
                    return SimpleNamespace(status_code=429, headers={"Retry-After": "5"},
                                           json=lambda: {"detail": {
                                               "status": "rate_limit_exceeded"}})
                return SimpleNamespace(status_code=200, content=b"ID3eleven")
            return SimpleNamespace(status_code=200, json=lambda: {
                "audioContent": base64.b64encode(b"ID3google").decode()})

    session = Session()
    speech = DescriptionSpeech(_settings(), session, lambda _: None)
    speech._google_headers = lambda: {}
    assert speech.synthesize("one") == (b"ID3google", "mp3")
    assert speech.synthesize("two") == (b"ID3google", "mp3")
    assert session.eleven_calls == 1
    clock[0] += 6
    assert speech.synthesize("three") == (b"ID3eleven", "mp3")
    assert session.eleven_calls == 2
    assert not speech.unavailable


def test_invalid_eleven_voice_is_not_retried_for_each_title():
    class Session:
        def __init__(self):
            self.eleven_calls = 0

        def post(self, url, **_kwargs):
            if "elevenlabs" in url:
                self.eleven_calls += 1
                return SimpleNamespace(status_code=400, headers={},
                                       json=lambda: {"detail": {
                                           "status": "voice_not_found"}})
            return SimpleNamespace(status_code=200, json=lambda: {
                "audioContent": base64.b64encode(b"ID3google").decode()})

    session = Session()
    speech = DescriptionSpeech(_settings(), session, lambda _: None)
    speech._google_headers = lambda: {}
    assert speech.synthesize("one") == (b"ID3google", "mp3")
    assert speech.synthesize("two") == (b"ID3google", "mp3")
    assert session.eleven_calls == 1


def test_kazakh_google_fallback_uses_gemini_tts():
    class Session:
        def post(self, url, **kwargs):
            assert url.endswith("/v1beta/interactions")
            return SimpleNamespace(status_code=200, json=lambda: {
                "steps": [{"content": [{"type": "audio", "data":
                    base64.b64encode(b"RIFFtestWAVE").decode()}]}]})

    speech = DescriptionSpeech(_settings(description_language="kk",
                                         description_tts_first="google"),
                               Session(), lambda _: None)
    assert speech.synthesize("Қазақша сипаттама") == (b"RIFFtestWAVE", "wav")


def test_both_services_unavailable_drop_kind_without_audio(tmp_path):
    settings = _settings(elevenlabs_key="")
    speech = DescriptionSpeech(settings, SimpleNamespace(post=lambda *_args, **_kw:
        (_ for _ in ()).throw(AssertionError("network must not be called"))),
        lambda _: None)
    speech._google_headers = lambda: (_ for _ in ()).throw(
        SpeechError("нет учётных данных Google Cloud", exhausted=True))
    speech._gemini_tts = lambda _text, _model: (_ for _ in ()).throw(
        SpeechError("нет доступа к Gemini TTS", exhausted=True))
    gen = object.__new__(ap.AnimePackGenerator)
    gen.s, gen.folder = settings, str(tmp_path)
    gen.gemini = SimpleNamespace(generate_json=lambda *_: {"text":
        "A young scholar discovers a mysterious map and gathers her friends. "
        "Together they cross the sea before a violent storm arrives."})
    gen.shikimori = SimpleNamespace(anime_description=lambda _:
                                    "A young scholar discovers a mysterious "
                                    "map and gathers her friends to cross the sea.")
    gen.description_tts = speech
    gen._timed = lambda _: nullcontext()
    gen._log_rare = lambda *_: None
    dropped = []
    gen._drop_kind = dropped.append
    cand = _candidate()
    assert not gen.make_description_audio(cand)
    assert dropped == [ap.DESCRIPTION_AUDIO_KIND]
    assert cand.rejected and not (tmp_path / "Audio").exists()


def test_description_controls_round_trip(qapp):
    from animepack_tab import AnimePackTab
    tab = AnimePackTab()
    try:
        tab.chk_description_audio.setChecked(True)
        tab.description_language_checks["kk"].setChecked(True)
        tab.description_language_checks["uk"].setChecked(True)
        tab.description_language_checks["en"].setChecked(False)
        tab.mix.set_shares({"description_audio": 100})
        saved = tab.get_settings()
        assert saved["pct_description_audio"] == 100
        assert saved["description_languages"] == ["uk", "kk"]
        tab.apply_settings(saved)
        assert tab.chk_description_audio.isChecked()
        assert (tab.collect().question_quotas[ap.DESCRIPTION_AUDIO_KIND]
                == tab.collect().total_questions)
    finally:
        tab.cleanup()
        tab.close()
        tab.deleteLater()
        qapp.processEvents()


def test_removed_paid_tts_model_is_migrated_and_rejected():
    removed = "gemini-2.5-pro-preview-tts"
    assert removed not in TTS_MODELS
    settings = ap.PackSettings.from_dict({"description_gemini_tts_model": removed})
    assert settings.description_gemini_tts_model == TTS_MODELS[0]
    with pytest.raises(SpeechError, match="неизвестная модель"):
        synthesize(None, "key", removed, "text")


def test_description_can_be_text_only(tmp_path):
    settings = _settings(description_voice_enabled=False)
    gen = object.__new__(ap.AnimePackGenerator)
    gen.s, gen.folder = settings, str(tmp_path)
    gen.gemini = SimpleNamespace(generate_json=lambda *_: {"text":
        "A young scholar discovers a mysterious map and gathers her friends. "
        "Together they cross the sea before a violent storm arrives."})
    gen.shikimori = SimpleNamespace(anime_description=lambda _:
        "A young scholar discovers a mysterious map and gathers her friends "
        "to cross the sea before a violent storm arrives.")
    gen.description_tts = SimpleNamespace(synthesize=lambda _:
        (_ for _ in ()).throw(AssertionError("voice is disabled")))
    gen._log_rare = lambda *_: None
    cand = _candidate()
    assert gen.make_description_audio(cand)
    assert cand.description_audio_ext == ""
    root = ET.fromstring(ap.build_content_xml([cand], settings))
    question = next(p for p in root.iter() if p.tag.endswith("param")
                    and p.attrib.get("name") == "question")
    assert len(question) == 1 and question[0].text == cand.description_text
    assert question[0].attrib.get("type") != "audio"


@pytest.mark.parametrize("model", TTS_MODELS)
def test_each_gemini_tts_model_accepts_audio_response(model):
    pcm = b"\x00\x00" * 100
    wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + pcm
    output = wav if model.startswith("gemini-3.8") else pcm

    class Session:
        def post(self, _url, **kwargs):
            assert kwargs["json"]["model"] == model
            return SimpleNamespace(status_code=200, json=lambda: {"steps": [
                {"content": [{"type": "audio", "data":
                 base64.b64encode(output).decode()}]}]})

    data, ext = synthesize(Session(), "key", model, "Short narration")
    assert ext == "wav" and data.startswith(b"RIFF")
