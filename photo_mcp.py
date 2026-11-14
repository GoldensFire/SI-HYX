# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""MCP-сервер «Редактирования фото» SI-HYX: команды photo_tool как инструменты.

Как montage_mcp.py: не входит в сборку, запускается Python'ом окружения с
официальным SDK `mcp` 2.x (можно то же, что у montage_mcp), транспорт stdio.
Каждый инструмент — `python -I photo_tool.py <команда> …` Python'ом
приложения (numpy, opencv, onnxruntime — там); картинки (просмотр, итог
правки) приходят изображением.

Подключение (Claude Code):

    claude mcp add si-hyx-photo -- %USERPROFILE%\\.cache\\si-hyx-montage\\mcp-venv\\Scripts\\python.exe -I C:\\путь\\SI-HYX\\photo_mcp.py --python C:\\путь\\python.exe

Python приложения: --python, иначе переменная SI_HYX_PYTHON, иначе python
из PATH."""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

ROOT = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(ROOT, "photo_tool.py")
_CREATE_NO_WINDOW = 0x08000000
TIMEOUT = 1800.0            # с: LaMa/RMBG на CPU и подбор AVIF на больших фото

_python = ""

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "Редактирование фото в SI-HYX: те же инструменты, что во вкладке «Редактирование "
    "фото» (кадрирование, кисть, размытие/пикселизация, фигуры, текст, наложение картинки, "
    "удаление объекта LaMa, фона RMBG, чёрных полос и вотермарок Gemini/Meta AI, поворот, "
    "масштаб), склейка как «Объединить фото» и сжатие настройками вкладки «Обработка» "
    "(AVIF под лимит размера). Начните с photo_guide (формат операций). Порядок: "
    "photo_info → photo_preview (сетка с координатами в пикселях исходника) → photo_edit "
    "(список операций; результат приходит картинкой) → photo_export или export='process' "
    "для сжатия → photo_open_in_app, чтобы пользователь доправил вручную. Исходник не "
    "перезаписывайте: выход — отдельным файлом. Пути лучше абсолютные.")

mcp = MCPServer("si-hyx-photo", instructions=INSTRUCTIONS, version="1")


def _out_dir():
    path = os.path.join(os.path.expanduser("~"), ".cache", "si-hyx-photo", "mcp")
    os.makedirs(path, exist_ok=True)
    return path


def _tmp_png(stem):
    return os.path.join(_out_dir(), f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}-"
                                    f"{time.monotonic_ns() % 100000:05d}.png")


def _json_file(obj, stem):
    fd, path = tempfile.mkstemp(prefix=stem + "-", suffix=".json", dir=_out_dir())
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return path


async def _kill(proc):
    if proc.returncode is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=_CREATE_NO_WINDOW)
        await proc.wait()


async def _run(command, *args, timeout=TIMEOUT):
    """photo_tool <command> args → его JSON. ok=false — ToolError с ответом."""
    argv = [_python, "-I", "-X", "utf8", TOOL, command] + [str(a) for a in args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=_CREATE_NO_WINDOW)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        with anyio.CancelScope(shield=True):
            await _kill(proc)
        raise ToolError(json.dumps({"ok": False, "command": command, "error": {
            "code": "timeout", "message": f"не уложилось в {timeout} с"}},
            ensure_ascii=False)) from None
    except BaseException:
        with anyio.CancelScope(shield=True):
            await _kill(proc)
        raise
    text = out.decode("utf-8", "replace").strip()
    try:
        res = json.loads(text.splitlines()[-1]) if text else None
    except ValueError:
        res = None
    if not isinstance(res, dict):
        raise ToolError(json.dumps({"ok": False, "command": command, "error": {
            "code": "bad_output", "message": f"photo_tool завершился с кодом {proc.returncode}",
            "detail": (err.decode("utf-8", "replace") or text)[-1500:]}}, ensure_ascii=False))
    if not res.get("ok"):
        raise ToolError(json.dumps(res, ensure_ascii=False))
    return res


def _text(res):
    return json.dumps(res, ensure_ascii=False, indent=1)


def _sets(settings):
    args = []
    for k, v in (settings or {}).items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        args += ["--set", f"{k}={v}"]
    return args


async def _with_preview(res, path, max_side=1280, grid=0):
    """Ответ + картинка результата (уменьшенная копия: модели хватает)."""
    if not path or not os.path.isfile(path):
        return _text(res)
    prev = _tmp_png("result")
    try:
        await _run("preview", path, prev, "--max", max_side, "--grid", grid, timeout=120)
    except ToolError:
        return _text(res)
    return [_text(res), Image(path=prev)]


Path = Annotated[str, Field(description="путь к файлу (лучше абсолютный)")]
Settings = Annotated[dict[str, Any] | None, Field(
    description="настройки «Обработки» для сжатия: img_fmt (avif/webp/png/jpg/ico), "
                "limit (КБ, 0 — без лимита), cq, adim (макс. сторона), awidth, aheight, "
                "aspd (0–8), fit_passes, chroma (420/422/444), gemini_wm; пусто — как во вкладке")]


@mcp.tool(annotations=READ, structured_output=False)
async def photo_guide() -> str:
    """Памятка: операции photo_edit (поля, координаты, цвета) и порядок работы."""
    return (await _run("guide", timeout=60))["guide"]


@mcp.tool(annotations=READ, structured_output=False)
async def photo_info(image: Path) -> str:
    """Размер, прозрачность, формат и вес картинки."""
    return _text(await _run("info", image, timeout=60))


@mcp.tool(annotations=READ, structured_output=False)
async def photo_preview(
        image: Path,
        max_side: Annotated[int, Field(description="длинная сторона просмотра, px")] = 1280,
        grid: Annotated[str, Field(description="шаг сетки в px исходника; auto — сам, 0 — без сетки")] = "auto"):
    """Картинка для просмотра: уменьшенная копия с сеткой и подписями координат в пикселях
    ИСХОДНИКА (по ним задавайте rect/points в photo_edit). Прозрачное — на шахматке."""
    out = _tmp_png("preview")
    res = await _run("preview", image, out, "--max", max_side, "--grid", grid, timeout=120)
    return [_text(res), Image(path=out)]


@mcp.tool(annotations=WRITE, structured_output=False)
async def photo_edit(
        input: Path,
        output: Annotated[str, Field(description="куда сохранить (png/tif/bmp/webp/jpg); "
                                                 "при export=process — имя, расширение даст формат")],
        ops: Annotated[list[dict[str, Any]], Field(description="операции по порядку, см. photo_guide")],
        export: Annotated[str, Field(description="lossless — как есть по расширению; "
                                                 "process — сжать настройками «Обработки»")] = "lossless",
        settings: Settings = None,
        open_in_app: Annotated[bool, Field(description="открыть итог во вкладке «Редактирование фото»")] = False):
    """Правка фото списком операций: crop, black_bars, rotate, flip, resize, brush, rect, ellipse,
    line, arrow, text, blur (gaussian/pixelate), overlay, remove_object (LaMa), remove_bg (RMBG),
    remove_watermarks. Ответ — отчёт по операциям и картинка результата."""
    ops_file = _json_file(ops, "ops")
    try:
        args = [input, output, "--ops", ops_file, "--export", export, *_sets(settings)]
        if open_in_app:
            args.append("--open")
        res = await _run("edit", *args)
    finally:
        try:
            os.remove(ops_file)
        except OSError:
            pass
    return await _with_preview(res, res.get("path"))


@mcp.tool(annotations=WRITE, structured_output=False)
async def photo_merge(
        output: Annotated[str, Field(description="итог (png/webp/jpg/tif)")],
        images: Annotated[list[str], Field(description="картинки по порядку")],
        vertical: Annotated[bool, Field(description="столбиком (по ширине), иначе в ряд (по высоте)")] = False,
        svg_white: Annotated[bool, Field(description="прозрачный фон SVG залить белым")] = False):
    """Склейка картинок, как «Объединить фото»: в ряд по высоте самой высокой или столбиком."""
    args = [output, *images, *(["--vertical"] if vertical else []),
            *(["--svg-white"] if svg_white else [])]
    res = await _run("merge", *args)
    return await _with_preview(res, res.get("path"))


@mcp.tool(annotations=WRITE, structured_output=False)
async def photo_export(
        image: Path,
        out_dir: Annotated[str, Field(description="папка результата")],
        stem: Annotated[str, Field(description="имя без расширения; пусто — <имя>_photo")] = "",
        settings: Settings = None) -> str:
    """Сжать картинку тем же кодом, что вкладка «Обработка» (AVIF под лимит размера и др.).
    Ответ — путь, размер в КБ и применённые настройки."""
    args = [image, out_dir, *(["--stem", stem] if stem else []), *_sets(settings)]
    return _text(await _run("export", *args))


@mcp.tool(annotations=WRITE, structured_output=False)
async def photo_open_in_app(image: Path, note: str = "") -> str:
    """Открыть картинку на холсте вкладки «Редактирование фото» запущенного SI-HYX —
    чтобы пользователь посмотрел и доправил её сам."""
    return _text(await _run("open", image, *(["--note", note] if note else []), timeout=60))


def _find_python(given):
    """Python приложения: --python, SI_HYX_PYTHON или python из PATH (не этот venv)."""
    for cand in (given, os.environ.get("SI_HYX_PYTHON", "")):
        if cand:
            if not os.path.isfile(cand):
                sys.exit(f"photo_mcp: нет Python приложения: {cand}")
            return cand
    own = os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))
    for d in os.environ.get("PATH", "").split(os.pathsep):
        exe = shutil.which("python", path=d) if d else None
        if exe and os.path.normcase(os.path.dirname(os.path.abspath(exe))) != own:
            return exe
    sys.exit("photo_mcp: укажите --python (Python приложения SI-HYX с numpy и opencv)")


def main():
    global _python
    ap = argparse.ArgumentParser(prog="photo_mcp", description="MCP-сервер «Редактирования фото» SI-HYX")
    ap.add_argument("--python", default="", help="Python приложения SI-HYX")
    args = ap.parse_args()
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # журнал сервера клиенту
    _python = _find_python(args.python)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
