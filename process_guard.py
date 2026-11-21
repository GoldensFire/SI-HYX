# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Страховка дочерних процессов ffmpeg и уборка осиротевших временных файлов.

Windows Job Object с JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE гарантирует, что при
падении приложения (включая os._exit(1) из sys.excepthook или снятие процесса)
ОС закроет дескриптор Job и немедленно завершит все привязанные дочерние
процессы ffmpeg, не давая им дописывать гигабайты в .sihyx_tmp_*.

При старте фоновый поток удаляет .sihyx_tmp_* и sihyx_graph_*.txt старше суток
в системном TEMP и в папке экспорта."""
import ctypes
from ctypes import wintypes
import os
import sys
import tempfile
import threading
import time

_JOB_LOCK = threading.Lock()
_JOB_HANDLE = None
_JOB_INIT_FAILED = False

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


if sys.platform == "win32":
    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


def _ensure_job():
    global _JOB_HANDLE, _JOB_INIT_FAILED
    if sys.platform != "win32" or _JOB_INIT_FAILED:
        return None
    if _JOB_HANDLE is not None:
        return _JOB_HANDLE
    with _JOB_LOCK:
        if _JOB_HANDLE is not None or _JOB_INIT_FAILED:
            return _JOB_HANDLE
        try:
            k32 = ctypes.windll.kernel32
            k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.SetInformationJobObject.argtypes = [
                wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
            ]
            k32.SetInformationJobObject.restype = wintypes.BOOL
            k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            k32.AssignProcessToJobObject.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.CloseHandle.restype = wintypes.BOOL

            job = k32.CreateJobObjectW(None, None)
            if not job:
                _JOB_INIT_FAILED = True
                return None
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = k32.SetInformationJobObject(
                job,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ok:
                k32.CloseHandle(job)
                _JOB_INIT_FAILED = True
                return None
            _JOB_HANDLE = job
        except Exception:
            _JOB_INIT_FAILED = True
            return None
    return _JOB_HANDLE


def assign_to_job(proc):
    """Привязывает дочерний subprocess.Popen (или PID) к Job Object с
    KILL_ON_JOB_CLOSE. Безопасно ничего не делает вне Windows или при ошибке."""
    if sys.platform != "win32" or proc is None:
        return False
    job = _ensure_job()
    if not job:
        return False
    k32 = ctypes.windll.kernel32
    handle = getattr(proc, "_handle", None)
    opened = None
    try:
        if handle is not None:
            return bool(k32.AssignProcessToJobObject(job, wintypes.HANDLE(int(handle))))
        pid = int(proc.pid) if hasattr(proc, "pid") else int(proc)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        opened = k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not opened:
            return False
        return bool(k32.AssignProcessToJobObject(job, opened))
    except Exception:
        return False
    finally:
        if opened:
            try:
                k32.CloseHandle(opened)
            except Exception:
                pass


def cleanup_stale_temp_files(dirs=None, max_age_s=86400):
    """Удаляет осиротевшие .sihyx_tmp_* (в TEMP и указанных папках экспорта)
    и sihyx_graph_*.txt (в TEMP), если они старше max_age_s секунд."""
    now = time.time()
    cutoff = now - max(0.0, float(max_age_s))
    tmp_dir = tempfile.gettempdir()
    seen = set()
    targets = []

    def _add(d, include_graph):
        if not d:
            return
        try:
            norm = os.path.normcase(os.path.abspath(str(d)))
        except (OSError, ValueError):
            return
        if norm in seen or not os.path.isdir(norm):
            return
        seen.add(norm)
        targets.append((norm, include_graph))

    _add(tmp_dir, True)
    for d in (dirs or ()):
        _add(d, False)

    removed = 0
    for folder, include_graph in targets:
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    name = entry.name
                    match = name.startswith(".sihyx_tmp_") or (
                        include_graph and name.startswith("sihyx_graph_") and name.endswith(".txt")
                    )
                    if not match:
                        continue
                    try:
                        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                            continue
                        st = entry.stat(follow_symlinks=False)
                        if st.st_mtime <= cutoff:
                            os.remove(entry.path)
                            removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return removed


def start_stale_temp_cleanup(dirs=None, max_age_s=86400):
    """Запускает cleanup_stale_temp_files в фоновом daemon-потоке."""
    dir_list = tuple(dirs) if dirs else ()
    th = threading.Thread(
        target=cleanup_stale_temp_files,
        args=(dir_list, max_age_s),
        name="sihyx-temp-cleanup",
        daemon=True,
    )
    th.start()
    return th
