"""Standalone cancellable ML worker; optional backends never load at app startup."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

# -I excludes the script directory; publish only this project's package root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from karaoke.hardware import devices


def separate(source, target, device):
    target = Path(target)
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    directory = target.parent / "stems"
    subprocess.run([sys.executable, "-I", "-m", "demucs", "-n", "htdemucs",
                    "--two-stems", "vocals", "--shifts", "0", "-d", device,
                    "-o", str(directory), str(source)], check=True)
    vocals = directory / "htdemucs" / Path(source).stem / "vocals.wav"
    temporary = target.with_suffix(".tmp.wav")
    shutil.copyfile(vocals, temporary)
    temporary.replace(target)


def transcribe(source, target, device, compute, language=None, model_name="medium", backend="faster-whisper"):
    if backend == "whisper.cpp":
        from karaoke.whisper_cpp import transcribe as cpp_transcribe
        rows = cpp_transcribe(source, language, model_name)
    else:
        rows = faster_transcribe(source, device, compute, language, model_name)
    if not rows:
        raise ValueError("Whisper: вокал не распознан")
    target = Path(target)
    temporary = target.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def faster_transcribe(source, device, compute, language, model_name):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device=device, compute_type=compute)
    # Five-beam search and conditioning on prior sung verses can spend minutes
    # repeating hallucinated lyrics. Every resulting line still passes acoustic
    # anchors and the app's mandatory 80% coverage check.
    segments, _ = model.transcribe(str(source), language=language, word_timestamps=True,
                                   vad_filter=False, beam_size=1,
                                   condition_on_previous_text=False)
    rows = []
    for segment in segments:
        rows.append({"start": segment.start, "end": segment.end, "text": segment.text,
                     "words": [{"start": word.start, "end": word.end, "word": word.word}
                               for word in segment.words or []]})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("devices", "separate", "transcribe", "languages"))
    parser.add_argument("source", nargs="?")
    parser.add_argument("target", nargs="?")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute", default="int8")
    parser.add_argument("--backend", default="faster-whisper")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--model", default="medium")
    args = parser.parse_args()
    if args.action == "devices":
        print(json.dumps(devices()))
    elif args.action == "separate":
        if args.backend == "kim-onnx":
            from karaoke.roformer import separate as kim_separate
            kim_separate(args.source, args.target, args.device)
        else:
            separate(args.source, args.target, args.device)
    elif args.action == "languages":
        from karaoke.languages import detect
        original = json.loads(Path(args.source).read_text(encoding="utf-8"))
        Path(args.target).write_text(json.dumps(detect(original)), encoding="utf-8")
    else:
        transcribe(args.source, args.target, args.device, args.compute,
                   None if args.language == "auto" else args.language, args.model, args.backend)


if __name__ == "__main__":
    main()
