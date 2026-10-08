"""Read compressed song containers before loading the separator model."""
from pathlib import Path
import subprocess
import tempfile
from storage_guard import require_space, raise_if_full, WORK_RESERVE

MAX_SECONDS = 1200
DECODE_RATE = 48000


def _read_bounded(source, sf):
    with sf.SoundFile(str(source)) as audio:
        if audio.frames > audio.samplerate * MAX_SECONDS:
            raise ValueError("Исходная песня длиннее 20 минут: проверьте версию записи.")
        return audio.read(dtype="float32", always_2d=True), audio.samplerate


def read(source, ffmpeg="ffmpeg"):
    import soundfile as sf

    try:
        return _read_bounded(source, sf)
    except sf.LibsndfileError:
        # AMQ can serve AAC/WebM under the generic source.audio filename.
        # FFmpeg detects the container; libsndfile does not support all of them.
        # Keep scratch audio on the generation volume, rather than filling an
        # unrelated system temp volume; stereo float WAV has a bounded size.
        require_space(Path(source).parent, WORK_RESERVE + (MAX_SECONDS + 1) * DECODE_RATE * 8)
        with tempfile.TemporaryDirectory(prefix="karaoke-input-", dir=Path(source).parent) as directory:
            target = Path(directory) / "decoded.wav"
            result = subprocess.run(
                [str(ffmpeg), "-y", "-v", "error", "-i", str(source), "-vn",
                 "-t", str(MAX_SECONDS + 1), "-ar", str(DECODE_RATE), "-ac", "2",
                 "-c:a", "pcm_f32le", str(target)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                detail = result.stderr.decode("utf-8", "replace")[-300:]
                raise_if_full(detail, directory)
                raise ValueError("Не удалось прочитать аудио: "
                                 + detail)
            return _read_bounded(target, sf)
