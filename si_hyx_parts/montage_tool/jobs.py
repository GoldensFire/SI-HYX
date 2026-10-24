# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Долгие задачи montage_tool: кэш, модели по требованию, обработчики.
Public namespace: montage_tool.

Кэш — ~/.cache/si-hyx-montage (или SI_HYX_MONTAGE_CACHE), не репозиторий.
Модели и бинарники качаются по требованию с закреплённым SHA-256 (ASSETS),
хост адреса проверяется разбором. Обработчики (Python генератора) идут по
одному на машину (chiptune.gate.model_slot — тот же замок, что у генерации)
с пониженным приоритетом: память общая с видеокартой. Отмена — файлом
(--cancel-file), прогресс — строками JSON в stderr (Control)."""
import hashlib
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

import montage_tool as _api

CACHE_ENV = "SI_HYX_MONTAGE_CACHE"
_BELOW_NORMAL = 0x00004000           # BELOW_NORMAL_PRIORITY_CLASS (наследуют дочерние)
_ASSET_HOSTS = ("cloud.cp.jku.at", "huggingface.co", "github.com",
                "objects.githubusercontent.com", "release-assets.githubusercontent.com")
# Закреплённые модели: путь в кэше, адрес, SHA-256, размер, лицензия.
ASSETS = {
    "beat_this/small0.ckpt": {
        "url": "https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/small0.ckpt",
        "sha256": "6074be2c4d490c5f6101fcc374a1ec72ae93456e23bb6019783b849f5dc7d47b",
        "size": 8451101, "license": "MIT (CPJKU Beat This!)"},
    "beat_this/final0.ckpt": {
        "url": "https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt",
        "sha256": "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331",
        "size": 81058141, "license": "MIT (CPJKU Beat This!)"},
}


class Control:
    """Прогресс и отмена долгой команды: stop() — есть файл отмены;
    stage(имя, …) — строка JSON {"event": "stage", …} в stderr (если
    прогресс включён)."""

    def __init__(self, cancel_file="", progress=False):
        self.cancel_file = cancel_file or ""
        self.progress = bool(progress)
        self.started = time.monotonic()

    def stop(self):
        return bool(self.cancel_file) and _api.os.path.exists(self.cancel_file)

    def check(self):
        if self.stop():
            raise _api.ToolError("cancelled", "отменено файлом отмены")

    def stage(self, name, **kw):
        if self.progress:
            from si_hyx_parts.montage_tool.cli import _emit
            _emit(dict({"event": "stage", "stage": name,
                        "elapsed": round(time.monotonic() - self.started, 2)}, **kw),
                  _api.sys.stderr)


NO_CONTROL = Control()


def cache_dir(*parts):
    """Папка кэша montage_tool (создаётся)."""
    root = _api.os.environ.get(CACHE_ENV) or _api.os.path.join(
        _api.os.path.expanduser("~"), ".cache", "si-hyx-montage")
    path = _api.os.path.join(root, *parts)
    _api.os.makedirs(path, exist_ok=True)
    return path


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def asset(name, ctl=NO_CONTROL):
    """Путь модели из ASSETS; нет в кэше — скачивается с проверкой SHA-256
    (проверенный файл помечается .ok, чтобы не считать хэш каждый раз)."""
    spec = ASSETS[name]
    target = _api.os.path.join(cache_dir(), *name.split("/"))
    ok = target + ".ok"
    if _api.os.path.isfile(target) and _api.os.path.isfile(ok):
        with open(ok, "r", encoding="utf-8") as f:
            if f.read().strip() == f"{spec['sha256']} {_api.os.path.getsize(target)}":
                return target
    if _api.os.path.isfile(target) and file_sha256(target) == spec["sha256"]:
        with open(ok, "w", encoding="utf-8") as f:
            f.write(f"{spec['sha256']} {_api.os.path.getsize(target)}")
        return target
    host = urlsplit(spec["url"]).hostname or ""
    if urlsplit(spec["url"]).scheme != "https" or host not in _ASSET_HOSTS:
        raise _api.ToolError("asset_failed", f"недопустимый адрес модели: {host}")
    _api.os.makedirs(_api.os.path.dirname(target), exist_ok=True)
    tmp = target + ".download"
    ctl.stage("download", file=name, size=spec["size"])
    h = hashlib.sha256()
    try:
        with urlopen(spec["url"], timeout=60) as r, open(tmp, "wb") as f:
            while True:
                ctl.check()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
        if h.hexdigest() != spec["sha256"]:
            raise _api.ToolError("asset_failed", f"контрольная сумма не совпала: {name}")
        _api.os.replace(tmp, target)
    except OSError as e:
        raise _api.ToolError("asset_failed", f"модель {name} не скачана: {e}") from e
    finally:
        if _api.os.path.exists(tmp):
            _api.os.remove(tmp)
    with open(ok, "w", encoding="utf-8") as f:
        f.write(f"{spec['sha256']} {_api.os.path.getsize(target)}")
    return target


def ensure_packages(python, imports, packages, ctl=NO_CONTROL):
    """Пакеты в Python генератора (uv, версии закреплены) — как у караоке."""
    from karaoke.ai_runtime import ensure_packages as _ensure
    try:
        _ensure(python, imports, packages, stopped=ctl.stop,
                log=lambda msg: ctl.stage("install", message=msg))
    except RuntimeError as e:
        raise _api.ToolError("ml_unavailable", str(e)) from e


def _kill_tree(proc):
    try:
        _api.subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                            creationflags=_api.CREATE_NO_WINDOW, timeout=15)
    except (OSError, _api.subprocess.SubprocessError):
        pass
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=15)


def run_worker(python, script, args, ctl=NO_CONTROL, timeout=1800, stage=""):
    """Обработчик script в Python python (-I, UTF-8) по одному на машину, с
    пониженным приоритетом и отменой; строки JSON его stdout — этапы
    прогресса. Вывод — в файл (без взаимной блокировки труб)."""
    if not _api.os.path.isfile(python):
        raise _api.ToolError("ml_unavailable", f"нет Python обработчика: {python}")
    from chiptune.gate import model_slot
    from chiptune.notes import QualityError
    ctl.check()
    try:
        with model_slot(ctl.stop), _api.tempfile.TemporaryFile() as log:
            env = dict(_api.os.environ, PYTHONIOENCODING="utf-8")
            try:
                proc = _api.subprocess.Popen(
                    [python, "-I", "-X", "utf8", script] + [str(a) for a in args],
                    stdin=_api.subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                    creationflags=_api.CREATE_NO_WINDOW | _BELOW_NORMAL)
            except OSError as e:
                raise _api.ToolError("ml_unavailable", f"обработчик не запустился: {e}") from e
            deadline = time.monotonic() + timeout
            try:
                while proc.poll() is None:
                    if ctl.stop():
                        _kill_tree(proc)
                        raise _api.ToolError("cancelled", "отменено файлом отмены")
                    if time.monotonic() > deadline:
                        _kill_tree(proc)
                        raise _api.ToolError("ml_timeout", f"обработчик не уложился в {timeout} с")
                    time.sleep(0.2)
            finally:
                if proc.poll() is None:
                    _kill_tree(proc)
            log.seek(0)
            out = log.read().decode("utf-8", "replace")
    except QualityError as e:
        raise _api.ToolError("cancelled", "отменено файлом отмены") from e
    if proc.returncode != 0:
        tail = "\n".join(out.strip().splitlines()[-15:])
        raise _api.ToolError("ml_failed", f"обработчик {stage or script} завершился с кодом "
                                          f"{proc.returncode}", detail=tail)
    return out
