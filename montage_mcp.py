# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""MCP-сервер «Монтажа» SI-HYX: команды montage_tool как инструменты агента.

Не входит в сборку (exe собирается от main.py) и не в зависимостях
приложения: запускается Python'ом отдельного окружения с официальным SDK
`mcp` 2.x, транспорт stdio. Каждый инструмент — вызов
`python -I montage_tool.py <команда> …` Python'ом приложения (numpy,
onnxruntime и прочее — там), ответ — JSON montage_tool; PNG (кадр, лист,
ритм-лента) приходят картинкой. Прогресс долгих команд (--progress) идёт
уведомлениями MCP, отмена вызова клиентом — файлом отмены.

Окружение (один раз):

    uv venv --python 3.11 %USERPROFILE%\\.cache\\si-hyx-montage\\mcp-venv
    uv pip install --python %USERPROFILE%\\.cache\\si-hyx-montage\\mcp-venv\\Scripts\\python.exe mcp==2.3.0

Подключение (Claude Code):

    claude mcp add si-hyx-montage -- %USERPROFILE%\\.cache\\si-hyx-montage\\mcp-venv\\Scripts\\python.exe -I C:\\путь\\SI-HYX\\montage_mcp.py --python C:\\путь\\python.exe

Python приложения: --python, иначе переменная SI_HYX_PYTHON, иначе python
из PATH. Подробнее — docs/montage-agent-amv.md, раздел «MCP»."""
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
from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

ROOT = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(ROOT, "montage_tool.py")
GUIDE = os.path.join(ROOT, "docs", "montage-agent-amv.md")
CANCEL_WAIT = 30.0          # с: после файла отмены — потом снимаем процесс
_CREATE_NO_WINDOW = 0x08000000

_python = ""

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
NET = ToolAnnotations(read_only_hint=True, open_world_hint=True)

INSTRUCTIONS = (
    "Монтаж AMV и роликов в SI-HYX. Начните с montage_guide (рецепт и правила хорошего AMV), "
    "формат проекта — montage_schema. Порядок: index (каталог серий, один раз) → music "
    "(карта песни) → autofill (черновик) → check_sync + beat_strip (числа и картинка) → "
    "edit (правки) → снова check_sync → render. Время — секунды; пути лучше абсолютные. "
    "Gemini (--gemini, ask) расходует бесплатную квоту пользователя — только по делу.")

mcp = MCPServer("si-hyx-montage", instructions=INSTRUCTIONS, version="1")


def _out_dir():
    root = os.environ.get("SI_HYX_MONTAGE_CACHE") or os.path.join(
        os.path.expanduser("~"), ".cache", "si-hyx-montage")
    path = os.path.join(root, "mcp")
    os.makedirs(path, exist_ok=True)
    return path


def _out_path(given, stem, ext):
    """Выходной файл: заданный (абсолютный) или новый в кэше сервера."""
    if given:
        return os.path.abspath(given)
    return os.path.join(_out_dir(), f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}"
                                    f"-{os.getpid() % 1000:03d}{ext}")


def _json_file(obj, stem):
    """Аргумент-JSON (операции, план, схема) — во временный файл."""
    fd, path = tempfile.mkstemp(prefix=stem + "-", suffix=".json", dir=_out_dir())
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return path


def _stage_text(ev):
    """Строка этапа montage_tool → сообщение прогресса."""
    skip = {"event", "stage", "elapsed", "percent", "time", "duration"}
    rest = ", ".join(f"{k}={v}" for k, v in ev.items() if k not in skip and not isinstance(v, (dict, list)))
    name = ev.get("stage") or ev.get("event") or ""
    return f"{name}: {rest}" if rest else str(name)


async def _stop(proc, cancel):
    """Остановка montage_tool: сперва файл отмены (он снимет свои
    обработчики и ffmpeg сам), через CANCEL_WAIT — дерево процессов."""
    if proc.returncode is None and cancel:
        with open(cancel, "w", encoding="utf-8") as f:
            f.write("cancel")
        try:
            await asyncio.wait_for(proc.wait(), CANCEL_WAIT)
        except asyncio.TimeoutError:
            pass
    if proc.returncode is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=_CREATE_NO_WINDOW)
        await proc.wait()


async def _run(ctx: Context | None, command, *args, progress=False, timeout=None):
    """montage_tool <command> args → его JSON. ok=false — ToolError с ответом."""
    argv = [_python, "-I", "-X", "utf8", TOOL, command] + [str(a) for a in args]
    cancel = ""
    if progress:
        cancel = os.path.join(_out_dir(), f"cancel-{os.getpid()}-{time.monotonic_ns()}")
        argv += ["--progress", "--cancel-file", cancel]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=_CREATE_NO_WINDOW)
    step = 0

    async def pump_stderr():
        nonlocal step
        tail = []
        while True:
            line = await proc.stderr.readline()
            if not line:
                return tail
            text = line.decode("utf-8", "replace").strip()
            try:
                ev = json.loads(text)
            except ValueError:
                tail = (tail + [text])[-20:]
                continue
            if ctx is None or not isinstance(ev, dict):
                continue
            step += 1
            try:
                if ev.get("event") == "progress" and "percent" in ev:
                    await ctx.report_progress(float(ev["percent"]), 100.0, "render")
                else:
                    await ctx.report_progress(float(step), None, _stage_text(ev))
            except Exception:       # клиент не просил прогресс или ушёл — не мешаем работе
                pass

    err_task = asyncio.ensure_future(pump_stderr())
    try:
        out = await asyncio.wait_for(proc.stdout.read(), timeout)
        await proc.wait()
        tail = await err_task
    except asyncio.TimeoutError:
        with anyio.CancelScope(shield=True):
            await _stop(proc, cancel)
        raise ToolError(json.dumps({"ok": False, "command": command, "error": {
            "code": "ml_timeout", "message": f"не уложилось в {timeout} с"}}, ensure_ascii=False)) from None
    except BaseException:
        # Отмена вызова клиентом. В anyio после отмены любое await снова
        # отменяется — остановка процесса под щитом.
        with anyio.CancelScope(shield=True):
            await _stop(proc, cancel)
        raise
    finally:
        if not err_task.done():
            err_task.cancel()
        if cancel and os.path.exists(cancel):
            os.remove(cancel)
    text = out.decode("utf-8", "replace").strip()
    try:
        res = json.loads(text.splitlines()[-1]) if text else None
    except ValueError:
        res = None
    if not isinstance(res, dict):
        raise ToolError(json.dumps({"ok": False, "command": command, "error": {
            "code": "bad_output", "message": f"montage_tool завершился с кодом {proc.returncode}",
            "detail": ("\n".join(tail) or text)[-1500:]}}, ensure_ascii=False))
    if not res.get("ok"):
        raise ToolError(json.dumps(res, ensure_ascii=False))
    return res


def _text(res):
    return json.dumps(res, ensure_ascii=False, indent=1)


def _with_image(res, path):
    if path and os.path.isfile(path):
        return [_text(res), Image(path=path)]
    return _text(res)


def _opt(flag, value):
    """Необязательный аргумент CLI: пропуск, если значение пустое."""
    if value is None or value == "" or value is False:
        return []
    if value is True:
        return [flag]
    return [flag, value]


Path = Annotated[str, Field(description="путь к файлу (лучше абсолютный)")]
Project = Annotated[str, Field(description="файл проекта .json")]
Seconds = Annotated[float, Field(description="секунды")]


# ---------- справка и проект ----------

@mcp.tool(annotations=READ, structured_output=False)
async def montage_guide() -> str:
    """Памятка агента: рецепт AMV, операции edit, эффекты, plan.json, признаки хорошего AMV.
    Прочитайте один раз перед работой."""
    with open(GUIDE, "r", encoding="utf-8") as f:
        return f.read()


@mcp.tool(annotations=READ, structured_output=False)
async def montage_schema() -> str:
    """Формат файла проекта: поля клипа, дорожек, маркеров, эффектов и их пределы."""
    return _text(await _run(None, "schema"))


@mcp.tool(annotations=READ, structured_output=False)
async def montage_probe(files: Annotated[list[str], Field(description="медиафайлы")]) -> str:
    """Свойства медиафайлов: длительность, кадр, fps, звуковые потоки."""
    return _text(await _run(None, "probe", *files))


@mcp.tool(annotations=READ, structured_output=False)
async def montage_describe(project: Project,
                           at: Annotated[float | None, Field(description="время проекта: что звучит и видно")] = None,
                           lenient: bool = False) -> str:
    """Таймлайн проекта: клипы (main#N), переходы, эффекты, маркеры по видам, части песни."""
    return _text(await _run(None, "describe", project, *_opt("--at", at), *_opt("--lenient", lenient)))


@mcp.tool(annotations=READ, structured_output=False)
async def montage_validate(project: Project, lenient: bool = False) -> str:
    """Строгая проверка проекта: проблемы списком."""
    return _text(await _run(None, "validate", project, *_opt("--lenient", lenient)))


# ---------- песня и каталог ----------

@mcp.tool(annotations=WRITE, structured_output=False)
async def montage_music(
        ctx: Context, media: Path,
        write_project: Annotated[str, Field(description="записать маркеры песни в этот проект")] = "",
        track: Annotated[int | None, Field(description="дорожка клипа с песней (для write_project)")] = None,
        kinds: Annotated[str, Field(description="виды маркеров через запятую (beat,downbeat,phrase,section,kick,snare,hat,slot)")] = "",
        t0: Seconds = 0.0, t1: Annotated[float | None, Field(description="конец отрезка, с")] = None,
        fps: Annotated[float, Field(description="места резов на сетке кадров этой частоты")] = 0.0,
        gemini: Annotated[bool, Field(description="подписи частей — один запрос Gemini (квота пользователя)")] = False,
        segment: Annotated[float, Field(description="сплошной кусок ~N с по границам частей песни")] = 0.0,
        segment_out: Annotated[str, Field(description="вырезать этот кусок в WAV (затухание 3 с)")] = "",
        overwrite: bool = False, no_drums: bool = False, brief: bool = True) -> str:
    """Карта песни: темп, размер, доли, такты, фразы, части (A/B…, verse/chorus), энергия,
    удары бочки/малого/хэта, места резов с приоритетом. Первый раз ~3 мин на песню, потом из кэша.
    segment — выбрать сплошной кусок песни (песня до N×1,25 — целиком), segment_out — вырезать его."""
    args = [media, *_opt("--t0", t0 or None), *_opt("--t1", t1), *_opt("--fps", fps or None),
            *_opt("--write", write_project), *_opt("--track", track), *_opt("--kinds", kinds),
            *_opt("--gemini", gemini), *_opt("--segment", segment or None),
            *_opt("--segment-out", segment_out), *_opt("--overwrite", overwrite),
            *_opt("--no-drums", no_drums), *_opt("--brief", brief)]
    return _text(await _run(ctx, "music", *args, progress=True))


@mcp.tool(annotations=WRITE, structured_output=False)
async def montage_index(
        ctx: Context, target: Annotated[str, Field(description="видеофайл или папка серий")],
        db: str = "", force: bool = False,
        tagger: Annotated[str, Field(description="vit (быстрее) или eva02")] = "vit",
        gemini: Annotated[bool, Field(description="описания сцен Gemini (квота пользователя)")] = False,
        speech: Annotated[bool, Field(description="ещё реплики серий (Whisper) — для montage_lines и op voice")] = False,
        language: Annotated[str, Field(description="язык речи: ru, ja, en… или auto")] = "auto",
        captions: Annotated[bool, Field(description="подписи планов локальной моделью — искать словами (query)")] = False) -> str:
    """Каталог планов: границы, движение, акценты, крупность, персонажи, теги, текст, OP/ED.
    ~15 мин на серию 24 мин 1080p (CPU); уже проиндексированные файлы пропускаются.
    speech — ещё расшифровка речи (несколько минут на серию); captions — подписи планов
    (llama.cpp, без сети; планы без подписи у всех файлов цели)."""
    args = [target, *_opt("--db", db), *_opt("--force", force), "--tagger", tagger,
            *_opt("--gemini", gemini), *_opt("--speech", speech),
            *(["--language", language] if speech else []), *_opt("--captions", captions)]
    return _text(await _run(ctx, "index", *args, progress=True))


@mcp.tool(annotations=READ, structured_output=False)
async def montage_lines(
        say: Annotated[str, Field(description="фраза на языке серий")],
        file: Annotated[str, Field(description="часть пути файла")] = "",
        db: str = "", limit: int = 10) -> str:
    """Реплики каталога (index speech=true), похожие на фразу: файл, время, слова со временем,
    планы под репликой. Вставить голос — montage_edit op voice {src, in, out, at, clean}."""
    return _text(await _run(None, "lines", "--say", say, *_opt("--file", file), *_opt("--db", db),
                            "--limit", limit))


@mcp.tool(annotations=WRITE, structured_output=False)
async def montage_reference(
        ctx: Context, video: Annotated[str, Field(description="готовый AMV-эталон")],
        out: Annotated[str, Field(description="скелет JSON для montage_autofill template")] = "") -> str:
    """Скелет эталона: резы, появления слоёв и вспышки в долях его песни, длина плана в долях,
    доля резов на долях/полудолях. С out — файл для autofill template (ритм «как у них»)."""
    return _text(await _run(ctx, "reference", video, *_opt("--out", out), progress=True))


def _search_argv(query, tags, any_tags, no_tags, character, motion_min, motion_max,
                 min_len, max_len, scale, static, moving, no_text, with_oped, file, ids, db, limit):
    return [*_opt("--query", query), *_opt("--tags", tags), *_opt("--any-tags", any_tags),
            *_opt("--no-tags", no_tags), *_opt("--character", character),
            *_opt("--motion-min", motion_min), *_opt("--motion-max", motion_max),
            *_opt("--min-len", min_len), *_opt("--max-len", max_len), *_opt("--scale", scale),
            *_opt("--static", static), *_opt("--moving", moving), *_opt("--no-text", no_text),
            *_opt("--with-oped", with_oped), *_opt("--file", file), *_opt("--ids", ids),
            *_opt("--db", db), "--limit", limit]


@mcp.tool(annotations=READ, structured_output=False)
async def montage_search(
        query: Annotated[str, Field(description="текст: теги, надписи, описания сцен")] = "",
        tags: Annotated[str, Field(description="все эти теги WD через запятую")] = "",
        any_tags: str = "", no_tags: str = "",
        character: Annotated[str, Field(description="id/имя персонажа или тег персонажа WD")] = "",
        motion_min: Annotated[float | None, Field(description="движение, доля ширины кадра в секунду")] = None,
        motion_max: float | None = None, min_len: float | None = None, max_len: float | None = None,
        scale: Annotated[str, Field(description="closeup,medium,wide,none")] = "",
        static: bool = False, moving: bool = False, no_text: bool = True, with_oped: bool = False,
        file: Annotated[str, Field(description="часть пути файла")] = "",
        ids: Annotated[str, Field(description="id планов через запятую")] = "",
        db: str = "", limit: int = 30, brief: bool = True) -> str:
    """Поиск планов каталога по тегам, персонажам, движению, крупности, длине и тексту."""
    args = _search_argv(query, tags, any_tags, no_tags, character, motion_min, motion_max,
                        min_len, max_len, scale, static, moving, no_text, with_oped, file, ids, db, limit)
    return _text(await _run(None, "search", *args, *_opt("--brief", brief)))


@mcp.tool(annotations=READ, structured_output=False)
async def montage_shot_sheet(
        query: str = "", tags: str = "", any_tags: str = "", no_tags: str = "", character: str = "",
        motion_min: float | None = None, motion_max: float | None = None,
        min_len: float | None = None, max_len: float | None = None, scale: str = "",
        static: bool = False, moving: bool = False, no_text: bool = True, with_oped: bool = False,
        file: str = "", ids: str = "", db: str = "", limit: int = 24,
        output: Annotated[str, Field(description="PNG (по умолчанию — в кэше сервера)")] = "",
        tile_width: int = 320) -> list[Any] | str:
    """Лист кадров найденных планов с их id — посмотреть глазами и выбрать (фильтры как у search)."""
    out = _out_path(output, "shots", ".png")
    args = _search_argv(query, tags, any_tags, no_tags, character, motion_min, motion_max,
                        min_len, max_len, scale, static, moving, no_text, with_oped, file, ids, db, limit)
    res = await _run(None, "shot-sheet", out, *args, "--tile-width", tile_width)
    return _with_image(res, out)


@mcp.tool(annotations=WRITE, structured_output=False)
async def montage_characters(db: str = "",
                             rename_id: Annotated[str, Field(description="id кластера для имени")] = "",
                             rename_to: str = "", recluster: bool = False) -> str:
    """Персонажи каталога (кластеры CCIP): список, имя кластеру, пересборка кластеров."""
    args = [*_opt("--db", db), *_opt("--recluster", recluster)]
    if rename_id:
        args += ["--rename", rename_id, rename_to]
    return _text(await _run(None, "characters", *args))


# ---------- черновик, правки, проверка ----------

@mcp.tool(annotations=WRITE, structured_output=False)
async def montage_autofill(
        ctx: Context, project: Annotated[str, Field(description="новый проект .json")], song: Path,
        duration: Annotated[float | None, Field(description="длина окна песни, с (окно выбирается по частям)")] = None,
        t0: float | None = None, t1: float | None = None,
        plan: Annotated[dict[str, Any] | None, Field(description="план: files, min_shot, exclude_tags, sections{chorus/verse/…: motion, scale, tags_any, characters}, prefer, avoid")] = None,
        fx: Annotated[str, Field(description="эффекты по ударам: amv, soft или пусто")] = "",
        library: str = "", min_shot: float = 0.35, overwrite: bool = False,
        gemini: Annotated[bool, Field(description="части песни — запрос Gemini (карта после montage_music gemini=true берётся из кэша и так)")] = False,
        template: Annotated[str, Field(description="скелет эталона (montage_reference out): резы на его доли, маркеры custom pop/flash")] = "",
        style: Annotated[str, Field(description="стиль AMV (montage_styles): шаг резов по частям, эффекты и переходы частей, отделка кадра")] = "") -> str:
    """Черновик AMV: окно песни, резы на местах резов (или на долях эталона — template,
    или с шагом стиля — style), планы каталога по энергии частей, акцент плана — на удар.
    Маркеры песни пишутся в проект."""
    plan_file = _json_file(plan, "plan") if plan else ""
    try:
        args = [project, "--song", song, *_opt("--duration", duration), *_opt("--t0", t0),
                *_opt("--t1", t1), *_opt("--plan", plan_file), *_opt("--fx", fx),
                *_opt("--library", library), "--min-shot", min_shot, *_opt("--overwrite", overwrite),
                *_opt("--gemini", gemini), *_opt("--template", template), *_opt("--style", style)]
        return _text(await _run(ctx, "autofill", *args, progress=True))
    finally:
        if plan_file:
            os.remove(plan_file)


@mcp.tool(annotations=READ, structured_output=False)
async def montage_styles(
        name: Annotated[str, Field(description="имя стиля (provant…) или пусто — список")] = "") -> str:
    """Стили AMV из docs/amv-styles: ритм, отделка частей, роли текста (edit preset
    «стиль.роль» у text/words/lyrics) и карточки (op card); описание словами — <имя>.md."""
    return _text(await _run(None, "styles", *([name] if name else [])))


@mcp.tool(annotations=WRITE, structured_output=False)
async def montage_edit(
        project: Project,
        ops: Annotated[list[dict[str, Any]], Field(description="операции: add/trim/split/swap/move/set/delete/text/effect/words/lyrics/voice/settings/card/strobe (см. montage_guide); время — число или ссылка на маркер (downbeat#18, section:chorus#2, slot#12.end, custom:pop#3); preset «стиль.роль» — роль текста или карточка стиля (montage_styles)")],
        db: str = "", dry_run: bool = False, lenient: bool = False) -> str:
    """Точечные правки проекта списком операций; ошибка в любой — проект не меняется."""
    ops_file = _json_file(ops, "ops")
    try:
        return _text(await _run(None, "edit", project, "--ops", ops_file, *_opt("--db", db),
                                *_opt("--dry-run", dry_run), *_opt("--lenient", lenient)))
    finally:
        os.remove(ops_file)


@mcp.tool(annotations=READ, structured_output=False)
async def montage_check_sync(ctx: Context, project: Project, db: str = "",
                             vocals: Annotated[bool, Field(description="запаздывание текста — по атакам вокала (стем песни из кэша; первый раз ~2 мин)")] = False) -> str:
    """Отчёт ритма: резы на долях/сильных долях/ударах (±1 кадр), плотность по частям,
    длины планов, повторы, скачки, тёмные кадры, хардсаб, OP/ED; текст песни позже звука
    слова (lyrics, проблемы lyric_late). Звать после каждой правки."""
    return _text(await _run(ctx, "check-sync", project, *_opt("--db", db),
                            *_opt("--vocals", vocals), progress=vocals))


@mcp.tool(annotations=READ, structured_output=False)
async def montage_beat_strip(project: Project, t0: Seconds, t1: Seconds,
                             output: str = "", width: int = 2000, db: str = "") -> list[Any] | str:
    """Ритм-лента PNG отрезка: волна, доли, сильные доли, части, удары, резы, клипы."""
    out = _out_path(output, "strip", ".png")
    res = await _run(None, "beat-strip", project, t0, t1, out, "--width", width, *_opt("--db", db))
    return _with_image(res, out)


@mcp.tool(annotations=READ, structured_output=False)
async def montage_still(project: Project, t: Seconds, output: str = "",
                        width: Annotated[int, Field(description="уменьшить до ширины (0 — как есть)")] = 960) -> list[Any] | str:
    """Кадр проекта в момент t — ровно как в итоговой сборке."""
    out = _out_path(output, "still", ".png")
    res = await _run(None, "still", project, t, out, *_opt("--width", width or None))
    return _with_image(res, out)


@mcp.tool(annotations=READ, structured_output=False)
async def montage_contact_sheet(project: Project, t0: Seconds, t1: Seconds,
                                n: Annotated[int, Field(description="число кадров")] = 16,
                                output: str = "", tile_width: int = 320) -> list[Any] | str:
    """Кадры отрезка проекта сеткой с временем и id клипов."""
    out = _out_path(output, "sheet", ".png")
    res = await _run(None, "contact-sheet", project, t0, t1, n, out, "--tile-width", tile_width)
    return _with_image(res, out)


@mcp.tool(annotations=READ, structured_output=False)
async def montage_preview(project: Project, t0: Seconds, t1: Seconds, output: str = "") -> str:
    """Ролик отрезка (до 15 с, малый размер, время в углу) — для montage_ask."""
    out = _out_path(output, "preview", ".mp4")
    return _text(await _run(None, "preview", project, t0, t1, out))


@mcp.tool(annotations=NET, structured_output=False)
async def montage_ask(media: Annotated[list[str], Field(description="mp4/png/jpg/webp")],
                      schema: Annotated[dict[str, Any], Field(description="JSON Schema ответа")],
                      prompt: str = "", model: str = "") -> str:
    """Вопрос Gemini по превью или кадрам (квота пользователя), ответ — по JSON-схеме."""
    schema_file = _json_file(schema, "schema")
    try:
        return _text(await _run(None, "ask", *media, "--schema", schema_file,
                                *_opt("--prompt", prompt), *_opt("--model", model)))
    finally:
        os.remove(schema_file)


@mcp.tool(annotations=READ, structured_output=False)
async def montage_look(images: Annotated[list[str], Field(description="png/jpg: кадры, листы, ленты")],
                       prompt: str,
                       schema: Annotated[dict[str, Any] | None, Field(description="JSON Schema ответа (грамматика llama.cpp)")] = None,
                       model: Annotated[str, Field(description="qwen3.5-2b (по умолчанию) или другая из montage_tool look --help")] = "",
                       max_tokens: int = 512) -> str:
    """Локальная модель зрения (llama.cpp, Vulkan, без сети и квот): вопрос по картинкам.
    Медленнее и слабее Gemini, зато бесплатно и без лимита — для проверки кадров."""
    schema_file = _json_file(schema, "schema") if schema else ""
    try:
        return _text(await _run(None, "look", *images, "--prompt", prompt,
                                *_opt("--schema", schema_file), *_opt("--model", model),
                                "--max-tokens", max_tokens, timeout=1800))
    finally:
        if schema_file:
            os.remove(schema_file)


# ---------- сборка ----------

@mcp.tool(annotations=READ, structured_output=False)
async def montage_dry_run(project: Project, output: Path, encoder: str = "auto") -> str:
    """Команда сборки без запуска: граф ffmpeg, кодировщик, что готово из RIFE/Anime4K."""
    return _text(await _run(None, "dry-run", project, output, "--encoder", encoder))


@mcp.tool(annotations=WRITE, structured_output=False)
async def montage_render(ctx: Context, project: Project, output: Path, encoder: str = "auto",
                         overwrite: bool = False,
                         preview: Annotated[bool, Field(description="превью: 540p и кодировщик видеокарты")] = False) -> str:
    """Сборка проекта в видео (прогресс — уведомлениями; отмена вызова — отмена сборки).
    preview — быстрое превью 540p на видеокарте, проект на диске не меняется."""
    return _text(await _run(ctx, "render", project, output, "--encoder", encoder,
                            *_opt("--overwrite", overwrite), *_opt("--preview", preview),
                            progress=True))


@mcp.tool(annotations=WRITE, structured_output=False)
async def montage_cli(ctx: Context, args: Annotated[list[str], Field(description="аргументы montage_tool: команда и её ключи")]) -> str:
    """Любая команда montage_tool как есть (analyze, analyze-file, stems и ключи,
    которых нет у отдельных инструментов). Справка: ["<команда>", "--help"] не печатается —
    смотрите montage_guide и montage_schema."""
    if not args:
        raise ToolError("нужна команда")
    return _text(await _run(ctx, args[0], *args[1:]))


@mcp.resource("montage://guide", name="guide", mime_type="text/markdown",
              description="Памятка агента по монтажу AMV")
def guide_resource() -> str:
    with open(GUIDE, "r", encoding="utf-8") as f:
        return f.read()


def _find_python(given):
    """Python приложения: --python, SI_HYX_PYTHON или python из PATH (не этот venv)."""
    for cand in (given, os.environ.get("SI_HYX_PYTHON", "")):
        if cand:
            if not os.path.isfile(cand):
                sys.exit(f"montage_mcp: нет Python приложения: {cand}")
            return cand
    own = os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))
    for d in os.environ.get("PATH", "").split(os.pathsep):
        exe = shutil.which("python", path=d) if d else None
        if exe and os.path.normcase(os.path.dirname(os.path.abspath(exe))) != own:
            return exe
    sys.exit("montage_mcp: укажите --python (Python приложения SI-HYX с numpy и onnxruntime)")


def main(argv=None):
    global _python
    ap = argparse.ArgumentParser(prog="montage_mcp", description="MCP-сервер «Монтажа» SI-HYX (stdio)")
    ap.add_argument("--python", default="", help="Python приложения SI-HYX")
    args = ap.parse_args(argv)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # журнал сервера клиенту
    _python = _find_python(args.python)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
