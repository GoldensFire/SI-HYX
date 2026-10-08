"""The final clip must satisfy the requested mode and contain real dialogue."""
import base64
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import time

import animepack as api
import gemini_api
import pytest
from si_hyx_parts.animepack import episode_scene_check as scene
from si_hyx_parts.animepack import episode_generation as generation
from test_animepack_episode import generator, info, stream
from test_animepack_new_kinds import make_anime


def verdict(**changes):
    value = dict(segment="scene", speech="dialogue", audio_language="ja", spoken_lines=2,
                 dialogue_seconds=7, spoken_example="久しぶりですね。元気でしたか。",
                 subtitle_language="ru", visible_example="Давно не виделись. Как ты?",
                 additional_subtitle_language="none", additional_subtitle_example="",
                 sync="ok", meaning_matches=True, wrong_title=False, reason="подтверждено")
    return dict(value, **changes)


@pytest.mark.parametrize("changes", [
    {"segment": "opening"}, {"segment": "ending"}, {"segment": "credits"},
    {"speech": "song"}, {"audio_language": "other"}, {"wrong_title": True},
    {"subtitle_language": "none", "visible_example": ""},
    {"subtitle_language": "en", "visible_example": "How are you?"},
    {"subtitle_language": "ru", "visible_example": "Seems we have a winner."},
    {"additional_subtitle_language": "en", "additional_subtitle_example": "Seems we have a winner."},
    {"meaning_matches": False}, {"sync": "mismatch"},
    {"spoken_lines": 1, "dialogue_seconds": 1},
    {"spoken_example": "こんにちは", "wrong_title": "false"},
])
def test_required_mode_rejects_audited_failure_classes(changes):
    assert not scene.accepted(verdict(**changes), "required")


def test_modes_and_literal_evidence_not_the_model_boolean_determine_acceptance():
    assert scene.accepted(verdict(), "required")
    assert not scene.accepted(verdict(), "none")
    english = verdict(subtitle_language="en", visible_example="Hello! How have you been?")
    assert scene.accepted(english, "preferred") and scene.accepted(english, "none")
    assert not scene.accepted(dict(english, additional_subtitle_language="ru",
                                   additional_subtitle_example="Привет!"), "none")
    raw = verdict(subtitle_language="none", visible_example="", sync="absent", meaning_matches=False)
    assert scene.accepted(raw, "none") and not scene.accepted(raw, "preferred")
    assert not scene.accepted(dict(raw, dialogue_seconds=float("nan")), "none")


def test_video_is_sent_as_inline_data_and_uses_existing_quota_fallback_client(monkeypatch):
    client = gemini_api.GeminiClient("unit-test-key", thinking="high")
    body = []
    def post(payload):
        body.append(payload)
        return {"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]}
    monkeypatch.setattr(client, "_post", post)
    monkeypatch.setattr(client.board, "unavailable", lambda *_: False)
    monkeypatch.setattr(client.board, "exhausted", lambda *_: False)
    assert client.generate_json([{"type": "video", "data": "YWJj", "mime_type": "video/mp4"},
                                 {"type": "text", "text": "check"}], {"type": "object"}) == {"ok": True}
    assert body[0]["contents"][0]["parts"][0] == {"inlineData": {"mimeType": "video/mp4", "data": "YWJj"}}
    assert "input" not in body[0]


def test_completed_video_is_checked_once_per_exact_clip_and_mode(tmp_path):
    calls = []
    def generate(parts, schema):
        calls.append(parts)
        return verdict()
    gen = SimpleNamespace(s=api.PackSettings(episode_subtitle_mode="required"),
                          gemini=SimpleNamespace(generate_json=generate), stopped=lambda: False,
                          log=lambda *_: None)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"encoded clip")
    source = stream("fixture", "sub", hardsub=False)
    scope = SimpleNamespace(deadline=time.monotonic() + 60)
    assert scene.check(gen, candidate, source, video, scope)
    assert scene.check(gen, candidate, source, video, scope)
    assert len(calls) == 1 and base64.b64decode(calls[0][0]["data"]) == b"encoded clip"
    gen.s.episode_subtitle_mode = "none"
    assert not scene.check(gen, candidate, source, video, scope)
    assert len(calls) == 2


def test_rejected_op_is_replaced_before_successful_finish(generator, monkeypatch):
    generator.s.episode_scene_check = True
    generator.s.episode_subtitle_mode = "none"
    answers = iter([verdict(segment="opening"),
                    verdict(subtitle_language="none", visible_example="", sync="absent")])
    generator.gemini_episode = SimpleNamespace(generate_json=lambda *_: deepcopy(next(answers)))
    scene.initialize(generator)
    calls = []
    def cut(gen, candidate, source, final, **kwargs):
        calls.append(kwargs["start"])
        Path(final).write_bytes(json.dumps(calls).encode())
        return kwargs["start"]
    monkeypatch.setattr(generation, "cut", cut)
    candidate = api.SongCandidate({}, make_anime(), kind=api.EPISODE_KIND)
    source = stream("fixture", "sub", _probe_info=info(duration=1400))
    final = Path(generator.folder) / "Video" / candidate.video_out
    scope = SimpleNamespace(deadline=time.monotonic() + 60)
    start = generation._try_cut(generator, candidate, source, final, scope)
    assert start is not None and len(calls) == 2
    assert generation._finish(generator, candidate, 1, 3, source, start, final, scope)
    assert candidate.episode_clip["scene_check"]["segment"] == "scene"
    assert not candidate.episode_clip["ru_subtitles"]


def test_scene_check_missing_key_fails_before_network_and_can_be_disabled():
    settings = api.PackSettings(pack_episode=True, pct_episode=100, pct_songs=0)
    assert any("проверки сцен" in text for text in settings.validate())
    settings.episode_scene_check = False
    assert not settings.validate()


def test_large_clip_gets_a_temporary_preview_without_changing_the_pack_video(tmp_path, monkeypatch):
    monkeypatch.setattr(scene, "MAX_BYTES", 16)
    video = tmp_path / "large.mp4"
    video.write_bytes(b"original video" * 10)
    commands = []
    def render(command, timeout):
        commands.append(command)
        Path(command[-1]).write_bytes(b"preview")
        return 0, ""
    gen = SimpleNamespace(_run_killable=render)
    assert scene.video_input(gen, video, SimpleNamespace(deadline=time.monotonic() + 60)) == b"preview"
    assert video.read_bytes() == b"original video" * 10
    assert commands and not list(tmp_path.glob("*.scene-check.mp4"))
