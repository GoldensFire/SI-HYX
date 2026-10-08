"""Verify one newly generated clip with local speech recognition and caption OCR."""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading
from types import SimpleNamespace

import animepack as api
from music_effects import runtime_python
from tools.episode_pack_audit import caption_check


class LocalSceneCheck:
    def __init__(self, generator, folder):
        self.generator = generator
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.gate = threading.BoundedSemaphore(1)
        self.reader = SimpleNamespace(stopped=generator.stopped, log=generator.log, _ocr_models=None,
            db_cache=SimpleNamespace(memo=lambda *args: None, remember_memo=lambda *args: None))
        self.python = Path(runtime_python())
        if not self.python.is_file():
            raise RuntimeError("The local speech runtime must already be installed")

    def check(self, candidate):
        while not self.generator.stopped():
            if self.gate.acquire(timeout=.2):
                try:
                    return self._check(candidate)
                finally:
                    self.gate.release()
        return False

    def _check(self, candidate):
        generator = self.generator
        folder = self.folder / str(candidate.mal_id)
        folder.mkdir(exist_ok=True)
        video = Path(generator.folder) / "Video" / candidate.video_out
        wav = folder / "audio.wav"
        result = {"mal_id": candidate.mal_id, "title": candidate.title_ru,
                  "method": "faster-whisper-medium-auto-language-and-caption-ocr", "passed": False}
        try:
            code, _out, error = generator._run_capture([
                api.FFMPEG, "-v", "error", "-y", "-i", str(video), "-vn", "-ar", "16000", "-ac", "1", str(wav)], timeout=45)
            if code:
                raise ValueError("Cannot read audio: " + error[-200:])
            code, out, error = generator._run_capture([
                str(self.python), "-I", "-X", "utf8", str(Path(__file__).with_name("episode_speech_worker.py")),
                str(wav), str(folder / "speech.json")], timeout=120)
            (folder / "speech.log").write_text(out + error, encoding="utf-8")
            if code:
                raise ValueError("Local speech recognition failed: " + error[-200:])
            speech = json.loads((folder / "speech.json").read_text(encoding="utf-8", errors="replace"))
            language = (speech.get("result") or {}).get("language")
            segments = [row for row in speech.get("transcription", []) if row.get("text", "").strip()]
            text = " ".join(row["text"].strip() for row in segments)
            seconds = sum(max(0, row["offsets"]["to"] - row["offsets"]["from"]) / 1000 for row in segments)
            result.update(audio_language=language, transcript=text, speech_seconds=round(seconds, 3))
            if language != "ja" or len(re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]", text)) < 4 or seconds < 3:
                raise ValueError("Japanese dialogue was not confirmed")
            captions = caption_check(self.reader, video, candidate.episode_clip, folder)
            result.update(captions=captions, passed=True)
            candidate.episode_clip["local_check"] = {
                "audio_language": language, "speech_seconds": round(seconds, 3),
                "russian_captions_visible": True, "transcript": text}
            generator.log(f"Локальная проверка «{candidate.title_ru}»: японская речь и видимые RU-сабы подтверждены.")
        except Exception as error:
            result["error"] = str(error)
            generator.log(f"Локальная проверка «{candidate.title_ru}»: отклонено — {error}")
            video.unlink(missing_ok=True)
        finally:
            (folder / "check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            with (self.folder / "checks.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(result, ensure_ascii=False) + "\n")
        return result["passed"]
