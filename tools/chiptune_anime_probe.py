"""Real anime excerpts through the same service and SIQ writer as the UI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animepack as ap
from chiptune.runtime import run_process
from chiptune.service import ChiptuneService

CASES = [
    ("evangelion-v2", "NeonGenesisEvangelion-OP1", "Zankoku na Tenshi no Thesis", 0, 30, "opening"),
    ("evangelion-ed", "NeonGenesisEvangelion-ED1", "Fly Me to the Moon", 15, 30, "ending"),
    ("kimiuso-op", "KimiUso-OP1", "Hikarunara", 20, 23273, "opening"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=[row[0] for row in CASES])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ap.FFMPEG = shutil.which("ffmpeg") or ap.FFMPEG
    results = []
    for name, slug, song, start, mal, kind in CASES:
        if args.case and name != args.case:
            continue
        directory = args.output / name
        directory.mkdir(exist_ok=True)
        original = directory / "original.wav"
        url = f"https://v.animethemes.moe/{slug}.webm"
        result = {"case": name, "source": url, "song": song, "start": start, "duration": 15}
        started = time.monotonic()
        try:
            if not original.exists():
                previous = args.output / "evangelion-op/original.wav"
                if name == "evangelion-v2" and previous.exists():
                    shutil.copyfile(previous, original)
                else:
                    with tempfile.TemporaryDirectory(prefix="source-", dir=directory) as work:
                        source = Path(work) / "source.webm"
                        urllib.request.urlretrieve(url, source)
                        code, error = run_process([ap.FFMPEG, "-y", "-v", "error", "-ss", str(start),
                                                   "-i", str(source), "-t", "15", "-ar", "44100",
                                                   "-ac", "2", "-c:a", "pcm_s16le", str(original)])
                        if code:
                            raise RuntimeError(error)
            settings = ap.PackSettings(chiptune_enabled=True, chiptune_percent=100,
                                       chiptune_seed=19, chiptune_lead="vocals", audio_cut=15,
                                       rounds=1, themes=1, questions=1)
            service = ChiptuneService(settings, run_process, ap.FFMPEG,
                                      log=lambda message: print(message, flush=True))
            metadata = service.convert(original, directory / "chiptune.wav", 0, 15)
            (directory / "processing.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            # Exercise the public downloader as well. The fetched source bytes
            # are replayed locally; transcription and audio encoding stay real.
            with tempfile.TemporaryDirectory(prefix="pack-", dir=directory) as work:
                generator = ap.AnimePackGenerator(settings)
                generator.folder = work
                generator._music_service = service
                generator._get_bytes = lambda url: original.read_bytes()
                Path(work, "Audio").mkdir()
                candidate = ap.SongCandidate(
                    song={"audio": slug + ".wav", "songType": 1 if kind == "opening" else 2,
                          "songName": song, "annSongId": mal},
                    anime={"malId": mal, "name": slug.split("-")[0]},
                    kind=kind, music_effect="chiptune")
                candidate.compress_audio = True
                if not generator.download_audio(candidate):
                    raise RuntimeError("The public audio downloader rejected the synthesized clip.")
                generator.write_package([candidate], str(directory / "chiptune-example.siq"))
            result["metrics"] = metadata["note_metrics"]
        except Exception as error:
            result["rejected"] = str(error)
        result["seconds"] = round(time.monotonic() - started, 2)
        results.append(result)
        (directory / "probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
