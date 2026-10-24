# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Локальное зрение (look): вопрос модели по картинкам без сети и квот.
Public namespace: montage_tool.

llama-server из llama.cpp (сборка Vulkan, ASSETS) с Qwen3.5-2B GGUF на
127.0.0.1 со случайным портом: один вызов — один запуск сервера (загрузка
~7–10 с), картинки — data URL, ответ по JSON-схеме — грамматикой
llama.cpp. Рассуждение модели выключено (--reasoning off): иначе Qwen3.5
сначала пишет <think> на сотни токенов.

Где считать: кодировщик картинки (mmproj) — на видеокарте, текстовая часть
по умолчанию на процессоре (gpu_layers=0): на iGPU Vega 7 с общей памятью
генерация 2B медленнее (~7 т/с), чем на 6 ядрах (~10 т/с); на дискретной
карте — gpu_layers=99. Сервер — по одному на машину (model_slot, как у
обработчиков), приоритет пониженный."""
import base64
import io
import socket
import threading
import time
import zipfile

import montage_tool as _api

LLAMA_BUILD = "b11838"
_LLAMA_ZIP = "llama/llama-b11838-bin-win-vulkan-x64.zip"
LOOK_MODELS = {
    "qwen3.5-2b": ("vlm/qwen3.5-2b/Qwen3.5-2B-Q4_K_M.gguf", "vlm/qwen3.5-2b/mmproj-F16.gguf"),
}
DEFAULT_LOOK_MODEL = "qwen3.5-2b"
_IMAGE_EXT = (".png", ".jpg", ".jpeg")
_READY_TIMEOUT = 180.0
_BELOW_NORMAL = 0x00004000


def llama_dir(ctl=None):
    """Папка распакованной сборки llama.cpp (из zip ASSETS, с проверкой
    имён: архив плоский, путей и «..» в нём быть не должно)."""
    ctl = ctl or _api.NO_CONTROL
    spec = _api.ASSETS[_LLAMA_ZIP]
    root = _api.cache_dir("llama", LLAMA_BUILD)
    ok = _api.os.path.join(root, ".ok")
    exe = _api.os.path.join(root, "llama-server.exe")
    if _api.os.path.isfile(exe) and _api.os.path.isfile(ok):
        with open(ok, "r", encoding="utf-8") as f:
            if f.read().strip() == spec["sha256"]:
                return root
    archive = _api.asset(_LLAMA_ZIP, ctl)
    ctl.stage("unpack", file=_LLAMA_ZIP)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = info.filename
            if info.is_dir():
                continue
            if ("/" in name or "\\" in name or ":" in name or name.startswith(".")
                    or _api.os.path.basename(name) != name):
                raise _api.ToolError("asset_failed", f"неожиданный путь в архиве llama.cpp: {name}")
            target = _api.os.path.join(root, name)
            tmp = target + ".tmp"
            with z.open(info) as src, open(tmp, "wb") as dst:
                _api.shutil.copyfileobj(src, dst, 1 << 20)
            _api.os.replace(tmp, target)
    with open(ok, "w", encoding="utf-8") as f:
        f.write(spec["sha256"])
    return root


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _image_url(path):
    """data URL картинки; не PNG/JPEG (webp…) — перекодируется в PNG."""
    ext = _api.os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXT:
        with open(path, "rb") as f:
            data = f.read()
        mime = "image/png" if ext == ".png" else "image/jpeg"
    else:
        from PIL import Image
        buf = io.BytesIO()
        try:
            Image.open(path).convert("RGB").save(buf, "PNG")
        except OSError as e:
            raise _api.ToolError("bad_media", f"картинка не прочитана: {path}: {e}") from e
        data, mime = buf.getvalue(), "image/png"
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def _kill(proc):
    if proc.poll() is None:
        _api.subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                            creationflags=_api.CREATE_NO_WINDOW, timeout=15)
    try:
        proc.wait(timeout=15)
    except _api.subprocess.TimeoutExpired:
        proc.kill()


def _log_tail(log):
    log.seek(0)
    text = log.read().decode("utf-8", "replace")
    return "\n".join(line for line in text.splitlines() if line.strip())[-1500:]


def _http(url, body=None, timeout=10.0):
    from urllib.request import Request, urlopen
    data = None if body is None else _api.json.dumps(body).encode("utf-8")
    req = Request(url, data, {"Content-Type": "application/json"} if data else {})
    with urlopen(req, timeout=timeout) as r:
        return _api.json.loads(r.read().decode("utf-8"))


def look(images, prompt, schema=None, model=DEFAULT_LOOK_MODEL, max_tokens=512,
         gpu_layers=0, ctl=None):
    """Вопрос prompt по картинкам images локальной модели. schema — JSON
    Schema ответа (тогда в ответе и разобранный json). Ответ: answer,
    json?, timing (загрузка, картинки+подсказка, токены/с генерации)."""
    ctl = ctl or _api.NO_CONTROL
    if model not in LOOK_MODELS:
        raise _api.ToolError("usage", f"модель: {', '.join(LOOK_MODELS)}")
    if not images:
        raise _api.ToolError("usage", "нужна хотя бы одна картинка")
    if not (prompt or "").strip():
        raise _api.ToolError("usage", "нужен вопрос (--prompt)")
    for p in images:
        if not _api.os.path.isfile(p):
            raise _api.ToolError("bad_media", f"нет файла: {p}")
    content = [{"type": "image_url", "image_url": {"url": _image_url(p)}} for p in images]
    content.append({"type": "text", "text": prompt})
    body = {"messages": [{"role": "user", "content": content}],
            "max_tokens": int(max_tokens), "temperature": 0}
    if schema:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "answer", "schema": schema}}
    root = llama_dir(ctl)
    weights, mmproj = (_api.asset(name, ctl) for name in LOOK_MODELS[model])
    from chiptune.gate import model_slot
    from chiptune.notes import QualityError
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    cmd = [_api.os.path.join(root, "llama-server.exe"), "-m", weights, "--mmproj", mmproj,
           "--host", "127.0.0.1", "--port", str(port), "-ngl", str(int(gpu_layers)),
           "-c", "8192", "-np", "1", "--reasoning", "off", "--no-webui"]
    try:
        with model_slot(ctl.stop), _api.tempfile.TemporaryFile() as log:
            t0 = time.monotonic()
            ctl.stage("look", what="load", model=model)
            proc = _api.subprocess.Popen(cmd, stdin=_api.subprocess.DEVNULL, stdout=log, stderr=log,
                                         cwd=root, creationflags=_api.CREATE_NO_WINDOW | _BELOW_NORMAL)
            try:
                while True:
                    if proc.poll() is not None:
                        raise _api.ToolError("ml_failed", f"llama-server завершился: код {proc.returncode}",
                                             detail=_log_tail(log))
                    ctl.check()
                    try:
                        if _http(base + "/health", timeout=2).get("status") == "ok":
                            break
                    except (OSError, ValueError):
                        pass
                    if time.monotonic() - t0 > _READY_TIMEOUT:
                        raise _api.ToolError("ml_timeout", "llama-server не запустился",
                                             detail=_log_tail(log))
                    time.sleep(0.3)
                load_s = time.monotonic() - t0
                ctl.stage("look", what="answer", images=len(images))
                box = {}

                def _ask():
                    try:
                        box["res"] = _http(base + "/v1/chat/completions", body, timeout=1800)
                    except (OSError, ValueError) as e:
                        box["err"] = e
                th = threading.Thread(target=_ask, daemon=True)
                th.start()
                while th.is_alive():
                    th.join(0.5)
                    if ctl.stop():
                        _kill(proc)
                        raise _api.ToolError("cancelled", "отменено файлом отмены")
                if "err" in box:
                    raise _api.ToolError("ml_failed", f"llama-server: {box['err']}",
                                         detail=_log_tail(log))
            finally:
                _kill(proc)
    except QualityError as e:
        raise _api.ToolError("cancelled", str(e)) from e
    res = box["res"]
    msg = ((res.get("choices") or [{}])[0].get("message") or {})
    answer = (msg.get("content") or "").strip()
    tm = res.get("timings") or {}
    out = {"model": model, "engine": f"llama.cpp {LLAMA_BUILD} vulkan", "images": list(images),
           "answer": answer,
           "timing": {"load_s": round(load_s, 2),
                      "prompt_s": round(tm.get("prompt_ms", 0.0) / 1000.0, 2),
                      "prompt_tokens": tm.get("prompt_n"),
                      "prompt_per_s": round(tm.get("prompt_per_second", 0.0), 1),
                      "tokens": tm.get("predicted_n"),
                      "tokens_per_s": round(tm.get("predicted_per_second", 0.0), 2),
                      "total_s": round(time.monotonic() - t0, 2),
                      "gpu_layers": int(gpu_layers)}}
    if schema:
        try:
            out["json"] = _api.json.loads(answer)
        except ValueError:
            out["json"] = None
    return out
