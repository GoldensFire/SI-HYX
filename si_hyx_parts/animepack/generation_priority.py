# -*- coding: utf-8 -*-
"""Нагрузка генератора: число одновременных задач и приоритет Windows."""
from __future__ import annotations

import os
import subprocess


def parallel_limit(settings):
    requested = max(1, min(16, int(settings.parallel)))
    return min(requested, 2) if getattr(settings, "generation_priority", "normal") == "low" else requested


def creation_flags(settings):
    if os.name != "nt":
        return 0
    classes = {"low": "IDLE_PRIORITY_CLASS", "high": "HIGH_PRIORITY_CLASS"}
    return getattr(subprocess, classes.get(getattr(settings, "generation_priority", "normal"), "NORMAL_PRIORITY_CLASS"), 0)


def apply_thread_priority(settings):
    """Меняем приоритет только рабочего потока, не интерфейса Qt."""
    if os.name != "nt":
        return
    import ctypes
    level = {"low": -15, "normal": 0, "high": 1}.get(
        getattr(settings, "generation_priority", "normal"), 0)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentThread.restype = ctypes.c_void_p
    kernel.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
    kernel.SetThreadPriority.restype = ctypes.c_int
    return bool(kernel.SetThreadPriority(kernel.GetCurrentThread(), level))
