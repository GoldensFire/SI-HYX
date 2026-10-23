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
                "bad_encoder", "nothing_to_render", "probe_failed"}


class _Parser(argparse.ArgumentParser):
    """argparse без печати в stderr и выхода: ошибка вызова — ToolError."""

    def error(self, message):
        raise _api.ToolError("usage", message)


def _emit(obj, stream=None):
    data = (_api.json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    out = stream or _api.sys.stdout
    buf = getattr(out, "buffer", None)
    if buf is not None:
        buf.write(data)
        buf.flush()
    else:
        out.write(data.decode("utf-8"))
        out.flush()


def _cmd_probe(args):
    media = []
    for f in args.files:
        try:
            media.append(_api.media_probe.probe_media(f))
        except _api.media_probe.ProbeError as e:
            raise _api.ToolError("probe_failed", f"{f}: {e}") from e
    return {"media": media}


def _cmd_validate(args):
    p, problems = _api.load_project_file(args.project)
    missing = _api.missing_files(p)
    problems += [{"path": m, "message": "нет файла"} for m in missing]
    return {"valid": not problems, "problems": problems,
            "clips": len(p.clips), "tracks": len(p.tracks),
            "duration": round(p.duration(), 6)}


def _cmd_describe(args):
    p, problems = _api.load_project_file(args.project)
    out = _api.describe_project(p, at=args.at)
    out["problems"] = problems
    return out


def _cmd_dry_run(args):
    p, problems = _api.load_project_file(args.project)
    out = _api.dry_run(p, args.output, encoder=args.encoder)
    out["problems"] = problems
    return out


def _cmd_render(args):
    p, problems = _api.load_project_file(args.project)
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


def build_parser():
    ap = _Parser(prog="montage_tool", description="«Монтаж» SI-HYX без интерфейса.")
    sub = ap.add_subparsers(dest="command", required=True, parser_class=_Parser)
    sp = sub.add_parser("probe", help="свойства медиафайлов")
    sp.add_argument("files", nargs="+")
    sp.set_defaults(fn=_cmd_probe)
    sp = sub.add_parser("validate", help="проверка проекта")
    sp.add_argument("project")
    sp.set_defaults(fn=_cmd_validate)
    sp = sub.add_parser("describe", help="таймлайн проекта")
    sp.add_argument("project")
    sp.add_argument("--at", type=float, default=None, help="время проекта, с")
    sp.set_defaults(fn=_cmd_describe)
    for name, fn in (("dry-run", _cmd_dry_run), ("render", _cmd_render)):
        sp = sub.add_parser(name, help="команда сборки" if fn is _cmd_dry_run else "сборка")
        sp.add_argument("project")
        sp.add_argument("output")
        sp.add_argument("--encoder", choices=sorted(_api.ENCODERS), default="auto")
        if fn is _cmd_render:
            sp.add_argument("--overwrite", action="store_true",
                            help="перезаписать существующий итог")
            sp.add_argument("--progress", action="store_true",
                            help="прогресс строками JSON в stderr")
            sp.add_argument("--cancel-file", default="",
                            help="появился этот файл — сборка отменяется")
        sp.set_defaults(fn=fn)
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
