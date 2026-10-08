"""Recognize a clip with the already installed local multilingual model."""
import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    model = WhisperModel("medium", device="cpu", compute_type="int8",
                         cpu_threads=4, num_workers=1, local_files_only=True)
    segments, info = model.transcribe(str(args.audio), language=None, beam_size=1,
                                      best_of=1, vad_filter=True,
                                      condition_on_previous_text=False)
    rows = [{"text": segment.text,
             "offsets": {"from": round(segment.start * 1000), "to": round(segment.end * 1000)},
             "avg_logprob": segment.avg_logprob, "no_speech_prob": segment.no_speech_prob}
            for segment in segments if segment.no_speech_prob < .8 and segment.avg_logprob > -1]
    result = {"result": {"language": info.language,
                         "language_probability": info.language_probability},
              "transcription": rows, "backend": "faster-whisper-medium-cpu-int8"}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
