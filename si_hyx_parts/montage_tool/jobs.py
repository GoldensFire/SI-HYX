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
import io as _io
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

import montage_tool as _api

CACHE_ENV = "SI_HYX_MONTAGE_CACHE"
_BELOW_NORMAL = 0x00004000           # BELOW_NORMAL_PRIORITY_CLASS (наследуют дочерние)
_ASSET_HOSTS = ("cloud.cp.jku.at", "huggingface.co", "github.com",
                "objects.githubusercontent.com", "release-assets.githubusercontent.com")
# Файлы LFS Hugging Face отдаются редиректом на CDN: us.aws.cdn.hf.co,
# cas-bridge.xethub.hf.co и т.п. — поддомены hf.co.
_ASSET_DOMAINS = ("hf.co",)
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
    # Каталог планов (index): адреса — на закреплённой ревизии репозитория.
    "shots/transnetv2.onnx": {
        "url": "https://huggingface.co/edgetools/transnetv2/resolve/4b2cef0e4f246904228785e9f0a693a2363e0a6b/transnetv2.onnx",
        "sha256": "c4d54a682bace32f25136ef83ca2c9d403e8f8193775efeb995172a0d95a8e0c",
        "size": 31250929, "license": "MIT (TransNetV2, Souček; ONNX edgetools)"},
    "anime/face_detect_v1.4_n.onnx": {
        "url": "https://huggingface.co/deepghs/anime_face_detection/resolve/784dc4c0bb692351ddcdbe6131a050b17d3025d5/face_detect_v1.4_n/model.onnx",
        "sha256": "fd860b650a4377046842c3cd80d01b0b408bdfbdb4acee5759630f82c6ef04a9",
        "size": 12102558, "license": "MIT (deepghs)"},
    "anime/face_detect_v1.4_n.threshold.json": {
        "url": "https://huggingface.co/deepghs/anime_face_detection/resolve/784dc4c0bb692351ddcdbe6131a050b17d3025d5/face_detect_v1.4_n/threshold.json",
        "sha256": "d53e35441fc92c5c8931c855ea2d0d9fe2597ac1ab0183017f8cec9992d0eab8",
        "size": 48, "license": "MIT (deepghs)"},
    "anime/head_detect_v2.0_n.onnx": {
        "url": "https://huggingface.co/deepghs/anime_head_detection/resolve/06604feee81983792a57c21081e539c0ae229833/head_detect_v2.0_n/model.onnx",
        "sha256": "69b069d15c9b97e0d7e6db33ac1c3fd480b1be67b078922c29beacfac81ad9ac",
        "size": 12104715, "license": "MIT (deepghs)"},
    "anime/head_detect_v2.0_n.threshold.json": {
        "url": "https://huggingface.co/deepghs/anime_head_detection/resolve/06604feee81983792a57c21081e539c0ae229833/head_detect_v2.0_n/threshold.json",
        "sha256": "f8d934097606a7b241289703bdeca6d106b23e79c2bad278da966740ef4828ca",
        "size": 48, "license": "MIT (deepghs)"},
    "anime/person_detect_v1.1_n.onnx": {
        "url": "https://huggingface.co/deepghs/anime_person_detection/resolve/e39c744c22432ad01f91dd254fe2b02c8d878b8c/person_detect_v1.1_n/model.onnx",
        "sha256": "6fcdfc6af18b3a26aca62aad0e00faffbeea23413abf868808d2d98d399999c9",
        "size": 12102560, "license": "MIT (deepghs)"},
    "anime/person_detect_v1.1_n.threshold.json": {
        "url": "https://huggingface.co/deepghs/anime_person_detection/resolve/e39c744c22432ad01f91dd254fe2b02c8d878b8c/person_detect_v1.1_n/threshold.json",
        "sha256": "ca4e215f1bddd1fe74fcd73d2a71fc16a221ba6f176c5182f9a45018f495beca",
        "size": 48, "license": "MIT (deepghs)"},
    "anime/ccip_feat.onnx": {
        "url": "https://huggingface.co/deepghs/ccip_onnx/resolve/eb2acdd29af1703388d3d0c04221add322bc9110/ccip-caformer-24-randaug-pruned/model_feat.onnx",
        "sha256": "4ea118d16496274f4f6e08d3afc768cc592389e8f7f32f8732ce2215c228ac5f",
        "size": 150248245, "license": "OpenRAIL (deepghs CCIP)"},
    "anime/ccip_metrics.onnx": {
        "url": "https://huggingface.co/deepghs/ccip_onnx/resolve/eb2acdd29af1703388d3d0c04221add322bc9110/ccip-caformer-24-randaug-pruned/model_metrics.onnx",
        "sha256": "7e4646fdfbe369ad485b227ec47ac4092c98b8deef3af44e19fdbd8ba7bc25c1",
        "size": 1649, "license": "OpenRAIL (deepghs CCIP)"},
    "anime/ccip_metrics.json": {
        "url": "https://huggingface.co/deepghs/ccip_onnx/resolve/eb2acdd29af1703388d3d0c04221add322bc9110/ccip-caformer-24-randaug-pruned/metrics.json",
        "sha256": "b5535577288e22940b853192cd1661e45c7615b7d89b49a8745c2c81685552d4",
        "size": 147, "license": "OpenRAIL (deepghs CCIP)"},
    "anime/ccip_cluster.json": {
        "url": "https://huggingface.co/deepghs/ccip_onnx/resolve/eb2acdd29af1703388d3d0c04221add322bc9110/ccip-caformer-24-randaug-pruned/cluster.json",
        "sha256": "21b9094f1edcd5cec6853b7d86dfed00b377ba5c3c9aa2535488833a84d3dd5a",
        "size": 370, "license": "OpenRAIL (deepghs CCIP)"},
    "tagger/wd-vit-v3.onnx": {
        "url": "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/7f6b584d0bd3f55c4531f14ba3d4761b2bccdc0f/model.onnx",
        "sha256": "35f23693620b668f4d53fd3c62bf65e40af739bc52c7eb0fbc49258b58d065b6",
        "size": 378536310, "license": "Apache-2.0 (SmilingWolf WD tagger v3)"},
    "tagger/wd-v3-tags.csv": {
        "url": "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/7f6b584d0bd3f55c4531f14ba3d4761b2bccdc0f/selected_tags.csv",
        "sha256": "298633d94d0031d2081c0893f29c82eab7f0df00b08483ba8f29d1e979441217",
        "size": 308468, "license": "Apache-2.0 (SmilingWolf WD tagger v3)"},
    "tagger/wd-eva02-large-v3.onnx": {
        "url": "https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/b25b82a03f7282e41aa2f257a52c7583b710bd1c/model.onnx",
        "sha256": "9e768793060c7939b277ccb382783e8670e8a042d29d77aa736be0c8cc898bfc",
        "size": 1260435999, "license": "Apache-2.0 (SmilingWolf WD tagger v3)"},
    "tagger/wd-eva02-v3-tags.csv": {
        "url": "https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/b25b82a03f7282e41aa2f257a52c7583b710bd1c/selected_tags.csv",
        "sha256": "298633d94d0031d2081c0893f29c82eab7f0df00b08483ba8f29d1e979441217",
        "size": 308468, "license": "Apache-2.0 (SmilingWolf WD tagger v3)"},
    # Фаза 5: RIFE — файлы из windows.zip релиза 20250112 (запросами Range), Anime4K.
    "rife/rife-ncnn-vulkan.exe": {
        "zip_url": "https://github.com/TNTwise/rife-ncnn-vulkan/releases/download/20250112/windows.zip",
        "member": "rife-ncnn-vulkan-refs/heads/master-windows/rife-ncnn-vulkan.exe",
        "sha256": "ddee627a5342e6ac4456625921b8d5ff52c2b459102c1c220106623ae358725a",
        "size": 7242752, "license": "MIT (TNTwise rife-ncnn-vulkan; веса hzwer Practical-RIFE)"},
    "rife/vcomp140.dll": {
        "zip_url": "https://github.com/TNTwise/rife-ncnn-vulkan/releases/download/20250112/windows.zip",
        "member": "rife-ncnn-vulkan-refs/heads/master-windows/vcomp140.dll",
        "sha256": "036b9b3f7ece8dfd48aeccd77113721c5305043aaa9c64d1e72812252727aa7c",
        "size": 192104, "license": "MIT (TNTwise rife-ncnn-vulkan; веса hzwer Practical-RIFE)"},
    "rife/LICENSE": {
        "zip_url": "https://github.com/TNTwise/rife-ncnn-vulkan/releases/download/20250112/windows.zip",
        "member": "rife-ncnn-vulkan-refs/heads/master-windows/LICENSE",
        "sha256": "de18cbedb0c3b0d1eeb9ccac3988cdf69c21fa89039cd97dd8846cb68f661f81",
        "size": 1093, "license": "MIT (TNTwise rife-ncnn-vulkan; веса hzwer Practical-RIFE)"},
    "rife/rife-v4.22-lite/flownet.bin": {
        "zip_url": "https://github.com/TNTwise/rife-ncnn-vulkan/releases/download/20250112/windows.zip",
        "member": "rife-ncnn-vulkan-refs/heads/master-windows/rife-v4.22-lite/flownet.bin",
        "sha256": "792da5d62937199886bf8bb781ab8e0eddf663854d57e4a43cd7b32e4e81b29b",
        "size": 9759728, "license": "MIT (TNTwise rife-ncnn-vulkan; веса hzwer Practical-RIFE)"},
    "rife/rife-v4.22-lite/flownet.param": {
        "zip_url": "https://github.com/TNTwise/rife-ncnn-vulkan/releases/download/20250112/windows.zip",
        "member": "rife-ncnn-vulkan-refs/heads/master-windows/rife-v4.22-lite/flownet.param",
        "sha256": "f52fd053ed743123831a611c80900cafdce55680a7953d3de52ac2d9d8be8ca2",
        "size": 29282, "license": "MIT (TNTwise rife-ncnn-vulkan; веса hzwer Practical-RIFE)"},
    "rife/rife-v4.25/flownet.bin": {
        "zip_url": "https://github.com/TNTwise/rife-ncnn-vulkan/releases/download/20250112/windows.zip",
        "member": "rife-ncnn-vulkan-refs/heads/master-windows/rife-v4.25/flownet.bin",
        "sha256": "10de487a095e61cb2971c39e3b5e17005a70fba6201c77fb96e063f4423b583f",
        "size": 11360684, "license": "MIT (TNTwise rife-ncnn-vulkan; веса hzwer Practical-RIFE)"},
    "rife/rife-v4.25/flownet.param": {
        "zip_url": "https://github.com/TNTwise/rife-ncnn-vulkan/releases/download/20250112/windows.zip",
        "member": "rife-ncnn-vulkan-refs/heads/master-windows/rife-v4.25/flownet.param",
        "sha256": "99d0f49866ff06f170c08e570e3e1b67b89019e3d11a87c8f0e7908fa50ab4c1",
        "size": 31669, "license": "MIT (TNTwise rife-ncnn-vulkan; веса hzwer Practical-RIFE)"},
    # Локальное зрение (look): llama.cpp с Vulkan и Qwen3.5-2B (GGUF unsloth).
    "llama/llama-b11838-bin-win-vulkan-x64.zip": {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11838/llama-b11838-bin-win-vulkan-x64.zip",
        "sha256": "d5c28fd61d2d6947d6cae9fe4576c7b9beddda31ab4cee6abd9417561e63b5f9",
        "size": 36882552, "license": "MIT (ggml-org llama.cpp)"},
    "vlm/qwen3.5-2b/Qwen3.5-2B-Q4_K_M.gguf": {
        "url": "https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/f6d5376be1edb4d416d56da11e5397a961aca8ae/Qwen3.5-2B-Q4_K_M.gguf",
        "sha256": "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223",
        "size": 1280835840, "license": "Apache-2.0 (Qwen3.5; GGUF unsloth)"},
    "vlm/qwen3.5-2b/mmproj-F16.gguf": {
        "url": "https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/f6d5376be1edb4d416d56da11e5397a961aca8ae/mmproj-F16.gguf",
        "sha256": "7035e9cb8d7c6a9681d07eef9a364783e86ea4cd73faab2eabb4f43a101830c7",
        "size": 668227264, "license": "Apache-2.0 (Qwen3.5; GGUF unsloth)"},
    "anime4k/Anime4K_v4.0.zip": {
        "url": "https://github.com/bloc97/Anime4K/releases/download/v4.0.1/Anime4K_v4.0.zip",
        "sha256": "139cd282086457c5adc79caf7b75b8b825091d71c9b54958c18745fea62d7ed7",
        "size": 776303, "license": "MIT (bloc97 Anime4K)"},
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
        if getattr(self, "_stop_fn", None) is not None and self._stop_fn():
            return True
        return bool(self.cancel_file) and _api.os.path.exists(self.cancel_file)

    @classmethod
    def from_stop(cls, should_stop):
        """Control поверх функции отмены (render: should_stop)."""
        c = cls()
        c._stop_fn = should_stop
        return c

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


def _check_host(url):
    """Адрес модели — только https на известных хостах (и после редиректа)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    known = host in _ASSET_HOSTS or any(host.endswith("." + d) for d in _ASSET_DOMAINS)
    if parts.scheme != "https" or not known:
        raise _api.ToolError("asset_failed", f"недопустимый адрес модели: {parts.hostname}")


class _RangeFile(_io.RawIOBase):
    """Файл по HTTP с произвольным доступом (Range) — для zipfile."""

    def __init__(self, url, ctl):
        from urllib.request import Request
        self._req = Request
        self.ctl = ctl
        with urlopen(Request(url, method="HEAD"), timeout=60) as r:
            self.url = r.geturl()
            self.size = int(r.headers["Content-Length"])
        _check_host(self.url)
        self.pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        self.ctl.check()
        req = self._req(self.url, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}"})
        with urlopen(req, timeout=60) as r:
            data = r.read()
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


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
    url = spec.get("zip_url") or spec["url"]
    _check_host(url)
    _api.os.makedirs(_api.os.path.dirname(target), exist_ok=True)
    tmp = target + ".download"
    ctl.stage("download", file=name, size=spec["size"])
    h = hashlib.sha256()
    try:
        if "member" in spec:
            # Файл из большого zip (RIFE: 827 МБ со всеми моделями) — только
            # его байты, запросами Range по оглавлению архива.
            import zipfile
            with zipfile.ZipFile(_io.BufferedReader(_RangeFile(url, ctl), 1 << 20)) as z, \
                    open(tmp, "wb") as f:
                data = z.read(spec["member"])
                f.write(data)
                h.update(data)
        else:
            with urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                _check_host(r.geturl())
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
    except (OSError, KeyError) as e:
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
