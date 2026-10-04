"""On-demand dependencies in the existing music worker's isolated Python."""
from pathlib import Path
import shutil

from chiptune.runtime import run_process
from music_effects import runtime_python


def ensure_packages(python, imports, packages, *, stopped, log):
    probe = [str(python), "-I", "-X", "utf8", "-c", "import " + ", ".join(imports)]
    code, _ = run_process(probe, 30, stopped=stopped)
    if not code:
        return
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Караоке: нужен uv или готовый Python обработчика.")
    log("Караоке: установка по необходимости: " + ", ".join(packages))
    code, output = run_process([uv, "pip", "install", "--python", str(python), *packages],
                               1800, stopped=stopped)
    if code:
        raise RuntimeError("Караоке: установка обработчика: " + output[-500:])


def ensure_runtime(settings, log, stopped):
    python = Path(settings.karaoke_python or runtime_python())
    if not python.is_file():
        uv = shutil.which("uv")
        if not uv:
            raise RuntimeError("Караоке: нужен uv для отдельного Python 3.11.")
        code, output = run_process([uv, "venv", "--python", "3.11", str(python.parent.parent)],
                                   600, stopped=stopped)
        if code:
            raise RuntimeError(output[-500:])
    ensure_packages(python, ["lyric_align", "faster_whisper", "pykakasi"],
                    ["lyric-align[asr]==0.4.1", "pykakasi==2.3.0"], stopped=stopped, log=log)
    return python


def ensure_separator(python, provider, *, stopped, log):
    package = {"directml": "onnxruntime-directml==1.24.4",
               "cuda": "onnxruntime-gpu==1.24.4", "cpu": "onnxruntime==1.24.4"}[provider]
    # ORT wheels share a namespace. Remove other variants only in this worker
    # environment, never in the app's environment; do not touch Torch/CTranslate2.
    expected = {"directml": "DmlExecutionProvider", "cuda": "CUDAExecutionProvider",
                "cpu": "CPUExecutionProvider"}[provider]
    code, _ = run_process([str(python), "-I", "-c", "import onnxruntime as o; "
                           f"assert {expected!r} in o.get_available_providers()"], 30, stopped=stopped)
    if code:
        uv = shutil.which("uv")
        if not uv:
            raise RuntimeError("Караоке: нужен uv для ONNX Runtime.")
        code, output = run_process([uv, "pip", "uninstall", "--python", str(python),
                                   "onnxruntime", "onnxruntime-gpu", "onnxruntime-directml"],
                                  60, stopped=stopped)
        if code:
            raise RuntimeError(output[-500:])
        ensure_packages(python, ["onnxruntime"], [package], stopped=stopped, log=log)
    ensure_packages(python, ["soundfile", "scipy"], ["soundfile==0.13.1", "scipy==1.15.3"],
                    stopped=stopped, log=log)
