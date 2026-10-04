"""Pinned model artifacts downloaded atomically only inside an active AI stage."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.request import urlopen
import zipfile

ROOT = Path.home() / ".cache/si-hyx-karaoke/models"
KIM_SHA = "1b8afd7780d8a234527748821dee6bc746d346f2088751c12fd48e8c873f625a"
KIM_URL = "https://github.com/santiquiroz/port-bs-roformer-onnx/releases/download/models-v1.0/mel_band_roformer_kim_T801.onnx"
MEDIUM_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-medium.bin"
MEDIUM_SHA = "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208"
CPP_URL = "https://github.com/jiang1997/whisper.cpp-release/releases/download/v1.8.4.1/whisper-1.8.4-windows-x64.zip"
CPP_SHA = "4b1b36343feb55ec3deace6a7dd18cc217f43a55e4ecce76ccd4ee3595c0b642"


def file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, target, sha):
    target = Path(target)
    if target.is_file() and file_sha(target) == sha:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".download")
    try:
        digest = hashlib.sha256()
        print("Download: " + target.name, flush=True)
        with urlopen(url, timeout=60) as response, temporary.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != sha:
            raise ValueError("Model checksum mismatch: " + target.name)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def kim_model():
    custom = os.environ.get("SI_HYX_KIM_ONNX")
    if custom:
        path = Path(custom)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    return download(KIM_URL, ROOT / "kim-dml-fp32" / "model.onnx", KIM_SHA)


def cpp_binary():
    import shutil
    custom = os.environ.get("SI_HYX_WHISPER_CPP") or shutil.which("whisper-cli")
    if custom:
        return Path(custom)
    if os.name != "nt":
        raise RuntimeError("Install whisper-cli built with GGML_VULKAN, or set SI_HYX_WHISPER_CPP")
    directory = ROOT / "whisper-cpp-1.8.4.1"
    candidates = list(directory.rglob("whisper-cli.exe")) if directory.exists() else []
    ready = directory / ".ready"
    # A cancelled extraction must never turn a partial executable into a hit.
    if not candidates or not ready.is_file():
        archive = download(CPP_URL, ROOT / "whisper-cpp-1.8.4.1.zip", CPP_SHA)
        directory.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                destination = (directory / entry.filename).resolve()
                if not destination.is_relative_to(directory.resolve()):
                    raise ValueError("Invalid whisper.cpp archive member")
            bundle.extractall(directory)
        candidates = list(directory.rglob("whisper-cli.exe"))
        if candidates:
            ready.write_text(CPP_SHA, encoding="ascii")
    if not candidates:
        raise RuntimeError("whisper-cli.exe missing in Vulkan release")
    return candidates[0]


def cpp_model():
    custom = os.environ.get("SI_HYX_WHISPER_MODEL")
    return Path(custom) if custom else download(MEDIUM_URL, ROOT / "ggml-medium.bin", MEDIUM_SHA)
