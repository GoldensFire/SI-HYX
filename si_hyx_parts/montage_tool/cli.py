# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Командная строка montage_tool: разбор аргументов и ответ JSON.
Public namespace: montage_tool.

Ответ — один JSON-объект в stdout (UTF-8): {"ok": true, "command": …, …}.
Ошибка — {"ok": false, "command": …, "error": {"code", "message",
"problems"?, "detail"?}} и код выхода: 2 — неверный вызов или проект,
1 — сбой сборки, 130 — отмена. Прогресс render (--progress) — строки JSON в
stderr: {"event": "progress", "percent", "time", "duration"}."""
import argparse
import traceback

import montage_tool as _api

EXIT_FAIL, EXIT_USAGE, EXIT_CANCEL = 1, 2, 130
# Коды ошибок, которые говорят о вызове или данных, а не о сбое сборки.
_USAGE_CODES = {"usage", "project_not_found", "project_too_large", "project_invalid_json",
                "project_invalid", "missing_files", "bad_output", "output_exists",
                "bad_encoder", "nothing_to_render", "probe_failed", "project_version",
                "bad_range", "bad_media", "bad_schema", "gemini_no_key", "bad_track",
                "ml_unavailable"}


class _Parser(argparse.ArgumentParser):
    """argparse без печати в stderr и выхода: ошибка вызова — ToolError."""

    def error(self, message):
        raise _api.ToolError("usage", message)


def _json_default(o):
    """numpy-числа и прочее, чего не знает json, — числом или строкой."""
    item = getattr(o, "item", None)
    return item() if callable(item) else str(o)


def _emit(obj, stream=None):
    data = (_api.json.dumps(obj, ensure_ascii=False, default=_json_default)
            + "\n").encode("utf-8")
    out = stream or _api.sys.stdout
    buf = getattr(out, "buffer", None)
    if buf is not None:
        buf.write(data)
        buf.flush()
    else:
        out.write(data.decode("utf-8"))
        out.flush()


def _cmd_schema(args):
    return {"schema": _api.montage_project.describe_schema()}


def _cmd_probe(args):
    media = []
    for f in args.files:
        try:
            media.append(_api.media_probe.probe_media(f))
        except _api.media_probe.ProbeError as e:
            raise _api.ToolError("probe_failed", f"{f}: {e}") from e
    return {"media": media}


def _cmd_validate(args):
    # Проблемы — ответ команды, а не ошибка: проект грузится мягко, а
    # проверяется в выбранном режиме и с файлами на диске.
    data = _api.read_project_json(args.project)
    p, _soft = _api.project_from_data(data, strict=False)
    problems = _api.montage_project.validate(data, strict=not args.lenient, check_files=True)
    return {"valid": not problems, "strict": not args.lenient, "problems": problems,
            "version": _api.montage_project.PROJECT_VERSION,
            "clips": len(p.clips), "tracks": len(p.tracks),
            "duration": round(p.duration(), 6)}


def _cmd_describe(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    out = _api.describe_project(p, at=args.at)
    out["problems"] = problems
    return out


def _cmd_dry_run(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    out = _api.dry_run(p, args.output, encoder=args.encoder)
    out["problems"] = problems
    return out


def _cmd_render(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    cancel_file = args.cancel_file

    def _stop():
        return bool(cancel_file) and _api.os.path.exists(cancel_file)

    def _progress(frac, sec, total):
        _emit({"event": "progress", "percent": round(frac * 100.0, 2),
               "time": round(sec, 3), "duration": round(total, 3)}, _api.sys.stderr)

    out = _api.render(p, args.output, encoder=args.encoder, overwrite=args.overwrite,
                      on_progress=_progress if args.progress else None, should_stop=_stop)
    out["problems"] = problems
    return out


def _cmd_still(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    return dict(_api.still(p, args.t, args.output, width=args.width), problems=problems)


def _cmd_contact_sheet(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    out = _api.contact_sheet(p, args.t0, args.t1, args.n, args.output,
                             tile_width=args.tile_width, columns=args.columns)
    out["problems"] = problems
    return out


def _cmd_preview(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    out = _api.preview(p, args.t0, args.t1, args.output, timecode=not args.no_timecode)
    out["problems"] = problems
    return out


def _cmd_ask(args):
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()
    else:
        prompt = args.prompt or ""
    if not prompt.strip():
        raise _api.ToolError("usage", "нужен --prompt или --prompt-file")
    try:
        with open(args.schema, "r", encoding="utf-8") as f:
            schema = _api.json.load(f)
    except (OSError, ValueError) as e:
        raise _api.ToolError("bad_schema", f"схема ответа не прочитана: {e}") from e
    if not isinstance(schema, dict):
        raise _api.ToolError("bad_schema", "схема ответа — JSON-объект (JSON Schema)")
    return {"answer": _api.ask_model(args.media, prompt, schema, model=args.model or None)}


def _ml_opts(args):
    return {"python": args.ml_python, "device": args.device,
            "language": args.language, "model": args.model}


def _kinds_arg(args):
    return [k for k in (args.kinds or "").split(",") if k.strip()] or None


def _cmd_analyze(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    out = _api.analyze_project(p, _kinds_arg(args), args.t0, args.t1, args.track,
                               args.scene_threshold, args.vocals, _ml_opts(args))
    if args.write:
        added = _api.merge_markers(p, out["markers"], out["kinds"], out["t0"], out["t1"])
        _api.montage_project.save_project(p, args.project)
        out["written"] = added
    out["problems"] = problems
    return out


def _cmd_analyze_file(args):
    return _api.analyze_file(args.media, _kinds_arg(args), args.t0, args.t1, args.stream,
                             args.scene_threshold, args.vocals, _ml_opts(args))


def _cmd_stems(args):
    rate = 44100
    audio = _api.file_audio(args.media, args.t0 or 0.0, args.t1, args.stream,
                            rate=rate, channels=2)
    if not len(audio):
        raise _api.ToolError("nothing_to_render", "в файле нет звука")
    files = _api.stems(audio, rate, args.out_dir, args.ml_python, args.device)
    return {"stems": files, "t0": args.t0 or 0.0, "t1": args.t1}


def _analysis_args(sp):
    sp.add_argument("--kinds", default="", help="через запятую: " + ",".join(_api.ANALYSIS_KINDS))
    sp.add_argument("--t0", type=float, default=0.0)
    sp.add_argument("--t1", type=float, default=None)
    sp.add_argument("--scene-threshold", type=float, default=_api.SCENE_THRESHOLD)
    sp.add_argument("--vocals", action="store_true",
                    help="слова — по вокалу (отделить HTDemucs; только для песен)")
    _ml_args(sp)


def _ml_args(sp):
    sp.add_argument("--language", default="auto")
    sp.add_argument("--model", default="medium")
    sp.add_argument("--device", default="cpu")
    sp.add_argument("--ml-python", default="", help="Python с faster-whisper и demucs")


def _lenient_arg(sp):
    sp.add_argument("--lenient", action="store_true",
                    help="загружать как вкладка: негодные клипы выбрасываются")


def build_parser():
    ap = _Parser(prog="montage_tool", description="«Монтаж» SI-HYX без интерфейса.")
    sub = ap.add_subparsers(dest="command", required=True, parser_class=_Parser)
    sp = sub.add_parser("schema", help="формат файла проекта")
    sp.set_defaults(fn=_cmd_schema)
    sp = sub.add_parser("probe", help="свойства медиафайлов")
    sp.add_argument("files", nargs="+")
    sp.set_defaults(fn=_cmd_probe)
    sp = sub.add_parser("validate", help="проверка проекта")
    sp.add_argument("project")
    _lenient_arg(sp)
    sp.set_defaults(fn=_cmd_validate)
    sp = sub.add_parser("describe", help="таймлайн проекта")
    sp.add_argument("project")
    _lenient_arg(sp)
    sp.add_argument("--at", type=float, default=None, help="время проекта, с")
    sp.set_defaults(fn=_cmd_describe)
    for name, fn in (("dry-run", _cmd_dry_run), ("render", _cmd_render)):
        sp = sub.add_parser(name, help="команда сборки" if fn is _cmd_dry_run else "сборка")
        sp.add_argument("project")
        sp.add_argument("output")
        _lenient_arg(sp)
        sp.add_argument("--encoder", choices=sorted(_api.ENCODERS), default="auto")
        if fn is _cmd_render:
            sp.add_argument("--overwrite", action="store_true",
                            help="перезаписать существующий итог")
            sp.add_argument("--progress", action="store_true",
                            help="прогресс строками JSON в stderr")
            sp.add_argument("--cancel-file", default="",
                            help="появился этот файл — сборка отменяется")
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("still", help="кадр проекта")
    sp.add_argument("project")
    sp.add_argument("t", type=float)
    sp.add_argument("output")
    sp.add_argument("--width", type=int, default=0, help="уменьшить до ширины")
    _lenient_arg(sp)
    sp.set_defaults(fn=_cmd_still)
    sp = sub.add_parser("contact-sheet", help="кадры отрезка сеткой")
    sp.add_argument("project")
    sp.add_argument("t0", type=float)
    sp.add_argument("t1", type=float)
    sp.add_argument("n", type=int)
    sp.add_argument("output")
    sp.add_argument("--tile-width", type=int, default=320)
    sp.add_argument("--columns", type=int, default=0)
    _lenient_arg(sp)
    sp.set_defaults(fn=_cmd_contact_sheet)
    sp = sub.add_parser("preview", help="ролик отрезка для модели")
    sp.add_argument("project")
    sp.add_argument("t0", type=float)
    sp.add_argument("t1", type=float)
    sp.add_argument("output")
    sp.add_argument("--no-timecode", action="store_true", help="без времени проекта в углу")
    _lenient_arg(sp)
    sp.set_defaults(fn=_cmd_preview)
    sp = sub.add_parser("analyze", help="маркеры проекта (время проекта)")
    sp.add_argument("project")
    sp.add_argument("--track", type=int, default=None, help="звук только этой дорожки")
    sp.add_argument("--write", action="store_true", help="записать маркеры в проект")
    _analysis_args(sp)
    _lenient_arg(sp)
    sp.set_defaults(fn=_cmd_analyze)
    sp = sub.add_parser("analyze-file", help="маркеры файла (время файла)")
    sp.add_argument("media")
    sp.add_argument("--stream", type=int, default=-1, help="абсолютный индекс звукового потока")
    _analysis_args(sp)
    sp.set_defaults(fn=_cmd_analyze_file)
    sp = sub.add_parser("stems", help="вокал и музыка звука файла (HTDemucs)")
    sp.add_argument("media")
    sp.add_argument("out_dir")
    sp.add_argument("--t0", type=float, default=0.0)
    sp.add_argument("--t1", type=float, default=None)
    sp.add_argument("--stream", type=int, default=-1)
    _ml_args(sp)
    sp.set_defaults(fn=_cmd_stems)
    sp = sub.add_parser("ask", help="вопрос модели Gemini по превью или кадрам")
    sp.add_argument("media", nargs="+", help="mp4, png, jpg, webp")
    sp.add_argument("--schema", required=True, help="JSON Schema ответа")
    sp.add_argument("--prompt", default="")
    sp.add_argument("--prompt-file", default="")
    sp.add_argument("--model", default="")
    sp.set_defaults(fn=_cmd_ask)
    return ap


def main(argv=None):
    """Точка входа CLI; возвращает код выхода."""
    argv = list(_api.sys.argv[1:] if argv is None else argv)
    command = next((a for a in argv if not a.startswith("-")), "")
    try:
        try:
            args = build_parser().parse_args(argv)
        except SystemExit:               # -h / --help: argparse уже напечатал справку
            return 0
        command = args.command
        out = args.fn(args)
    except _api.ToolError as e:
        _emit({"ok": False, "command": command, "error": e.to_dict()})
        if e.code == "cancelled":
            return EXIT_CANCEL
        return EXIT_USAGE if e.code in _USAGE_CODES else EXIT_FAIL
    except KeyboardInterrupt:
        _emit({"ok": False, "command": command,
               "error": {"code": "cancelled", "message": "прервано"}})
        return EXIT_CANCEL
    except Exception as e:               # сбой самой команды — тоже ответом JSON
        _emit({"ok": False, "command": command,
               "error": {"code": "internal", "message": f"{type(e).__name__}: {e}",
                         "detail": traceback.format_exc()[-2000:]}})
        return EXIT_FAIL
    _emit(dict({"ok": True, "command": command}, **out))
    return 0
