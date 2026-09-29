"""Description translation batching and narration encoding."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import base64
import os

from si_hyx_parts.animepack.description_batch import DescriptionBatcher
from si_hyx_parts.animepack.description_audio_encode import encode
from si_hyx_parts.animepack.description_gemini_tts import synthesize
from si_hyx_parts.animepack.description_tts import DescriptionSpeech

import animepack as ap


def test_concurrent_descriptions_share_one_translation_request():
    calls = []

    class Client:
        def generate_json(self, prompt, schema):
            calls.append((prompt, schema))
            assert "Ukrainian" in prompt and "English" in prompt
            return {"results": [
                {"id": index, "text": f"translated-{index}"}
                for index in reversed(range(4))]}

    batcher = DescriptionBatcher(Client(), max_jobs=4)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda index: batcher.translate(
            f"source-{index}", "uk" if index % 2 else "en"), range(4)))
    assert results == [f"translated-{index}" for index in range(4)]
    assert len(calls) == 1
    assert calls[0][1]["properties"]["results"]["minItems"] == 4


def test_narration_uses_pack_loudness_and_opus(tmp_path):
    commands = []
    output = tmp_path / "question.opus"

    def run(command, timeout):
        commands.append(command)
        assert os.path.exists(command[command.index("-i") + 1])
        output.write_bytes(b"OggSencoded")
        return 0, ""

    encode(SimpleNamespace(_run_killable=run), b"RIFFfakeWAVE", "wav",
           str(output))
    command = commands[0]
    assert "libopus" in command and "loudnorm=I=" in command[command.index("-af") + 1]
    assert "afade" not in command[command.index("-af") + 1]
    assert output.read_bytes() == b"OggSencoded"
    assert not list(tmp_path.glob("_description_*"))


def test_all_tts_providers_request_faster_speech():
    requests = []

    class Session:
        def post(self, url, **kwargs):
            requests.append((url, kwargs["json"]))
            if "interactions" in url:
                return SimpleNamespace(status_code=200, json=lambda: {"steps": [{
                    "content": [{"type": "audio", "data": base64.b64encode(
                        b"RIFFtestWAVE").decode()}]}]})
            if "elevenlabs" in url:
                return SimpleNamespace(status_code=200, content=b"ID3eleven")
            return SimpleNamespace(status_code=200, json=lambda: {
                "audioContent": base64.b64encode(b"ID3google").decode()})

    settings = ap.PackSettings()
    settings.elevenlabs_key = "key"
    settings.elevenlabs_voice = "voice"
    session = Session()
    speech = DescriptionSpeech(settings, session, lambda _: None)
    speech._google_headers = lambda: {}
    speech._elevenlabs("hello")
    speech._google_chirp("hello", "en")
    synthesize(session, "key", "gemini-3.8-flash-lite-tts", "hello")
    assert requests[0][1]["voice_settings"]["speed"] > 1
    assert requests[1][1]["audioConfig"]["speakingRate"] > 1
    annotation = requests[2][1]["input"][0]["content"][0]["annotations"][0]
    assert annotation["style"] == "speaking rapidly"


def test_gemini_quota_rotates_to_another_model():
    models = []

    class Session:
        def post(self, _url, **kwargs):
            model = kwargs["json"]["model"]
            models.append(model)
            if len(models) == 1:
                return SimpleNamespace(status_code=429, headers={}, json=lambda: {
                    "error": {"status": "RESOURCE_EXHAUSTED",
                              "message": "daily quota per day"}})
            return SimpleNamespace(status_code=200, json=lambda: {"steps": [{
                "content": [{"type": "audio", "data": base64.b64encode(
                    b"RIFFtestWAVE").decode()}]}]})

    speech = DescriptionSpeech(ap.PackSettings(gemini_key="key"), Session(),
                               lambda _: None)
    assert speech.synthesize("hello")[1] == "wav"
    assert len(models) == 2 and models[0] != models[1]
    assert speech.synthesize("hello")[1] == "wav"
    assert models == [models[0], models[1], models[1]]


def test_gemini_tts_waits_after_three_requests_per_minute(monkeypatch):
    import si_hyx_parts.animepack.description_tts as module

    now = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(module, "time", SimpleNamespace(
        monotonic=lambda: now[0], sleep=sleep))
    speech = DescriptionSpeech(ap.PackSettings(), None, lambda _: None)
    for _ in range(3):
        speech._wait_for_gemini_slot("model-a")
    assert not sleeps
    speech._wait_for_gemini_slot("model-a")
    assert now[0] >= 160 and sum(sleeps) >= 60
    speech._wait_for_gemini_slot("model-b")
    assert len(speech._gemini_recent["model-b"]) == 1
