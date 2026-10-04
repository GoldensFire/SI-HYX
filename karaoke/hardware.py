"""Cheap adapter inventory; ML libraries are probed only by the isolated worker."""
from __future__ import annotations

import os
from pathlib import Path


def adapters():
    if os.name == "nt":
        import winreg
        names = []
        path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    name = winreg.EnumKey(root, index)
                    if not name.isdecimal():
                        continue
                    with winreg.OpenKey(root, name) as key:
                        names.append(str(winreg.QueryValueEx(key, "DriverDesc")[0]))
        except OSError:
            pass
        return names
    names = []
    for device in Path("/sys/class/drm").glob("card[0-9]*/device/vendor"):
        try:
            names.append({"0x1002": "AMD", "0x8086": "Intel", "0x10de": "NVIDIA"}
                         .get(device.read_text(encoding="ascii").strip(), ""))
        except OSError:
            pass
    return names


def select(names, cuda=False, compute="float16", demucs_cuda=False):
    non_nvidia = any(any(v in name.casefold() for v in ("amd", "radeon", "intel"))
                     for name in names)
    return {"backend": "faster-whisper" if cuda or not non_nvidia else "whisper.cpp",
            "asr": "cuda" if cuda else "vulkan" if non_nvidia else "cpu",
            "compute": compute if cuda else "float32" if non_nvidia else "int8",
            "separator": "directml" if non_nvidia and os.name == "nt" else
                         "cuda" if cuda else "cpu",
            "demucs": "cuda" if demucs_cuda else "cpu"}


def devices():
    cuda, compute, demucs_cuda = False, "float16", False
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count():
            supported = ctranslate2.get_supported_compute_types("cuda")
            cuda, compute = True, "float16" if "float16" in supported else "float32"
    except (ImportError, RuntimeError, OSError):
        pass
    try:
        import torch
        demucs_cuda = torch.cuda.is_available()
    except (ImportError, RuntimeError, OSError):
        pass
    return select(adapters(), cuda, compute, demucs_cuda)
