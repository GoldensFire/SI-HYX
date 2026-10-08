"""Compare CPU thread counts on identical audio with a fresh model process each time."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import FFMPEG
from music_effects import runtime_python
from karaoke.recognition import WORKER


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--threads', type=int, nargs='+', default=[4, 12, 4])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / 'source.wav'
    subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-i', str(args.source),
                    '-t', str(args.seconds), '-ac', '2', '-ar', '44100', str(source)],
                   check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    results = []
    for number, threads in enumerate(args.threads, 1):
        target = args.output / f'trial-{number}-threads-{threads}.wav'
        if target.exists():
            raise ValueError('The benchmark needs fresh output targets')
        started = time.monotonic()
        process = subprocess.run([str(runtime_python()), '-I', '-X', 'utf8', str(WORKER),
            'separate', str(source), str(target), '--backend', 'htdemucs', '--device', 'cpu'],
            env={**os.environ, 'SI_HYX_ML_THREADS': str(threads)},
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        seconds = time.monotonic() - started
        target.with_suffix('.log').write_text(process.stdout + process.stderr, encoding='utf-8')
        row = {'threads': threads, 'seconds': seconds, 'exit_code': process.returncode,
               'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'audio_seconds': args.seconds}
        results.append(row)
        (args.output / 'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(row), flush=True)
        if process.returncode:
            raise RuntimeError(process.stderr[-500:])


if __name__ == '__main__':
    main()
