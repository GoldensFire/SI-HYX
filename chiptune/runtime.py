"""Cancellable local process runner and explicit isolated-runtime installation."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from music_effects import runtime_python
from .service import worker_path
from .gate import model_slot
from .launcher import isolated_command


def run_process(command, timeout=900, *, stopped=lambda: False):
    if stopped():
        return 1, "Остановлено."
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    # File output avoids pipe deadlocks and keeps progress noise out of the UI.
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(command, stdout=output, stderr=output, creationflags=flags)
        except OSError as error:
            return 1, str(error)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if stopped() or time.monotonic() >= deadline:
                    if flags:
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=flags, timeout=15)
                    else:
                        process.kill()
                    process.wait(timeout=15)
                    return 1, "Остановлено или истекло время ожидания обработчика."
                time.sleep(.2)
            output.seek(0)
            return process.returncode, output.read().decode("utf-8", "replace")[-5000:]
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)


def install_runtime(run=run_process, log=lambda message: None, stopped=lambda: False):
    log("Ожидание свободного обработчика для установки…")
    with model_slot(stopped):
        return _install_runtime(run, log)


def _install_runtime(run, log):
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Не найден uv. Установите uv с docs.astral.sh/uv/getting-started/installation/ "
                           "и перезапустите SI-HYX. Затем повторите установку моделей.")
    python = runtime_python()
    commands = []
    if not python.is_file():
        commands.append(("Установка отдельного Python 3.11…",
                         [uv, "venv", "--python", "3.11", str(python.parent.parent)]))
    commands.extend([
        ("Установка PyTorch CPU (около 200 МБ)…", [uv, "pip", "install", "--python", str(python),
         "torch==2.5.1", "torchaudio==2.5.1", "--index-url", "https://download.pytorch.org/whl/cpu"]),
        ("Установка распознавания и разделения…", [uv, "pip", "install", "--python", str(python),
         "demucs==4.0.1", "torchcrepe==0.0.23", "numpy==1.26.4", "librosa==0.10.2.post1",
         "soundfile==0.13.1", "onnxruntime==1.23.2"]),
    ])
    for label, command in commands:
        log(label)
        code, error = run(command, timeout=3600)
        if code:
            raise RuntimeError(error)
    log("Загрузка и проверка моделей Demucs / RMVPE / CREPE…")
    with tempfile.TemporaryDirectory(prefix="sihyx_chip_install_") as directory:
        with isolated_command(python, worker_path()) as command:
            code, error = run([*command, "install", "--target",
                               str(Path(directory) / "ready.json")], timeout=1800)
        if code:
            raise RuntimeError(error)
    return str(python)
