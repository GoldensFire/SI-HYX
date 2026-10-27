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
                "ml_unavailable", "no_clip", "bad_op", "bad_plan", "no_markers"}


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


def _preview_arg(p, args):
    """--preview: кадр 540p и кодировщик на видеокарте (проект на диске не
    меняется). Отчёт для ответа или None."""
    if not args.preview:
        return None
    w, h = _api.preview_settings(p)
    if args.encoder == "auto":
        args.encoder = "gpu"
    return {"width": w, "height": h, "encoder": args.encoder}


def _cmd_dry_run(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    preview = _preview_arg(p, args)
    out = _api.dry_run(p, args.output, encoder=args.encoder)
    out["problems"] = problems
    if preview:
        out["preview"] = preview
    return out


def _cmd_render(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    preview = _preview_arg(p, args)
    cancel_file = args.cancel_file

    def _stop():
        return bool(cancel_file) and _api.os.path.exists(cancel_file)

    def _progress(frac, sec, total):
        _emit({"event": "progress", "percent": round(frac * 100.0, 2),
               "time": round(sec, 3), "duration": round(total, 3)}, _api.sys.stderr)

    out = _api.render(p, args.output, encoder=args.encoder, overwrite=args.overwrite,
                      on_progress=_progress if args.progress else None, should_stop=_stop)
    out["problems"] = problems
    if preview:
        out["preview"] = preview
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
    lyrics = getattr(args, "lyrics", "")
    if lyrics and not _api.os.path.isfile(lyrics):
        raise _api.ToolError("missing_files", f"нет файла текста: {lyrics}")
    return {"python": args.ml_python, "device": args.device,
            "language": args.language, "model": args.model,
            "beat_model": getattr(args, "beat_model", ""), "ctl": _control(args),
            "lyrics": _api.os.path.abspath(lyrics) if lyrics else "",
            "lyric_lines": _api.parse_lines(getattr(args, "lyric_lines", ""))}


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


def _control(args):
    return _api.Control(cancel_file=getattr(args, "cancel_file", ""),
                        progress=getattr(args, "progress", False))


def _brief_map(m):
    """Карта песни без длинных списков: доли, удары и кандидаты резов —
    числом, места для резов — только рекомендованные."""
    out = {k: v for k, v in m.items() if k not in ("beats", "hits", "slots")}
    out["beats"] = len(m.get("beats", []))
    out["hits"] = {k: len(v) for k, v in m.get("hits", {}).items()}
    out["slots"] = [s for s in m.get("slots", []) if s.get("recommended")]
    out["bars"] = [{k: b[k] for k in ("index", "t", "bpm", "energy", "section")}
                   for b in m.get("bars", [])]
    return out


def _cmd_music(args):
    ctl = _control(args)
    opts = {"model": args.beat_model, "python": args.ml_python, "drums": not args.no_drums,
            "sections": not args.no_sections, "gemini": args.gemini, "ctl": ctl}
    m = _api.music_file(args.media, args.t0, args.t1, args.stream, **opts)
    if args.segment_out and not args.segment:
        raise _api.ToolError("usage", "--segment-out — вместе с --segment N")
    if args.segment:
        m["segment"] = _api.song_segment(m, args.segment)
        if args.segment_out:
            m["segment"]["output"] = _api.cut_segment(args.media, m["segment"], args.segment_out,
                                                      args.stream, args.overwrite)
    fps = args.fps
    if args.write:
        p, problems = _api.load_project_file(args.write, strict=not args.lenient)
        if args.track is None or not 0 <= args.track < len(p.tracks):
            raise _api.ToolError("bad_track", "--write: нужен --track N (дорожка с песней)")
        media = _api.os.path.normcase(_api.os.path.abspath(args.media))
        clips = [c for c in p.clips_on(args.track)
                 if media in (_api.os.path.normcase(_api.os.path.abspath(c.src)),
                              _api.os.path.normcase(_api.os.path.abspath(c.audio_path or c.src)))]
        if not clips:
            raise _api.ToolError("no_clip", f"на дорожке {args.track} нет клипа с этим файлом")
        fps = fps or p.output_format()[2]
        kinds = _kinds_arg(args) or list(_api.MUSIC_WRITE_KINDS)
        bad = [k for k in kinds if k not in _api.MUSIC_KINDS]
        if bad:
            raise _api.ToolError("usage", f"неизвестный вид: {', '.join(bad)} "
                                          f"(есть {', '.join(_api.MUSIC_KINDS)})")
        # Резы — на сетке кадров проекта: время места пересчитывается в
        # проект, затем прилипает к кадру.
        found = _api.map_markers(m, kinds, _api.clip_mapper(clips))
        for mk in found:
            if mk["kind"] == "slot":
                mk["t"] = round(_api.snap_frame(mk["t"], fps, args.lead)[0], 6)
        _api.snap_slots(m, fps, args.lead)
        added = _api.merge_markers(p, found, kinds, 0.0, float("inf"))
        _api.montage_project.save_project(p, args.write)
        m["written"] = {"project": _api.os.path.abspath(args.write), "markers": added,
                        "kinds": kinds, "problems": problems}
    else:
        _api.snap_slots(m, fps, args.lead)
    return _brief_map(m) if args.brief else m


def _cmd_index(args):
    speech = None
    if args.speech:
        speech = {"model": args.speech_model, "language": args.language,
                  "python": args.ml_python}
    return _api.index_library(args.target, args.db or None, _control(args), force=args.force,
                              tagger=args.tagger, gemini=args.gemini,
                              gemini_model=args.gemini_model, speech=speech,
                              captions=args.captions, caption_gpu_layers=args.gpu_layers)


def _cmd_lines(args):
    return _api.find_lines(args.db or None, args.say, args.file, args.limit, args.min_score)


def _list_arg(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _search_found(args, limit=None):
    return _api.search(
        args.db or None, tags_all=_list_arg(args.tags), tags_any=_list_arg(args.any_tags),
        tags_none=_list_arg(args.no_tags), character=args.character,
        motion_min=args.motion_min, motion_max=args.motion_max, min_len=args.min_len,
        max_len=args.max_len, bright_min=args.bright_min, bright_max=args.bright_max,
        scale=_list_arg(args.scale), no_text=args.no_text, include_oped=args.with_oped,
        include_transitions=args.with_transitions, file=args.file, query=args.query,
        static=True if args.static else (False if args.moving else None),
        limit=limit or args.limit, ids=[int(x) for x in _list_arg(args.ids)])


def _cmd_search(args):
    out = _search_found(args)
    if args.brief:
        keep = ("id", "file", "t0", "t1", "length", "scale", "motion", "characters", "tags",
                "character_tags", "accents", "oped", "caption", "score")
        out["shots"] = [{k: s[k] for k in keep if k in s} for s in out["shots"]]
    return out


def _cmd_shot_sheet(args):
    found = _search_found(args, limit=min(args.limit, _api.SHEET_MAX))
    out = _api.shot_sheet(found["shots"], args.output, args.tile_width, args.columns)
    out["total"] = found["total"]
    return out


def _cmd_characters(args):
    con = _api.connect(args.db or None)
    try:
        if args.rename:
            _api.rename_character(con, args.rename[0], args.rename[1])
        if args.recluster:
            _api.recluster_characters(con, _control(args))
        rows = con.execute(
            "SELECT h.id, h.name, h.size, (SELECT MIN(k.shot_id) FROM crops k WHERE k.char_id=h.id) "
            "AS example FROM characters h ORDER BY h.size DESC").fetchall()
        return {"characters": [dict(r) for r in rows]}
    finally:
        con.close()


def _read_json_arg(path, what):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _api.json.load(f)
    except (OSError, ValueError) as e:
        raise _api.ToolError("usage", f"{what} не прочитан: {e}") from e


def _cmd_edit(args):
    ops = _read_json_arg(args.ops, "файл операций")
    if isinstance(ops, dict) and isinstance(ops.get("ops"), list):
        ops = ops["ops"]
    return _api.edit_project(args.project, ops, args.db or None, strict=not args.lenient,
                             dry_run=args.dry_run)


def _cmd_autofill(args):
    return _api.autofill(args.project, args.song, args.library or None, args.plan or None,
                         t0=args.t0, t1=args.t1, duration=args.duration, min_shot=args.min_shot,
                         ctl=_control(args), beat_model=args.beat_model, overwrite=args.overwrite,
                         fx=args.fx, gemini=args.gemini, template=args.template or None,
                         style=args.style or None)


def _cmd_styles(args):
    if args.name:
        return _api.style_report(args.name)
    return {"styles": _api.list_styles(), "folder": _api.styles_dir()}


def _cmd_reference(args):
    return _api.reference(args.video, args.out or None, _control(args), args.beat_model)


def _cmd_check_sync(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    attacks = _api.vocal_attacks(p, _control(args), args.ml_python) if args.vocals else None
    out = _api.check_sync(p, args.db or None, attacks)
    out["load_problems"] = problems
    return out


def _cmd_beat_strip(args):
    p, problems = _api.load_project_file(args.project, strict=not args.lenient)
    out = _api.beat_strip(p, args.t0, args.t1, args.output, args.width, args.db or None)
    out["problems"] = problems
    return out


def _cmd_look(args):
    prompt = args.prompt
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()
    schema = _read_json_arg(args.schema, "файл схемы") if args.schema else None
    return _api.look(args.images, prompt, schema=schema, model=args.model,
                     max_tokens=args.max_tokens, gpu_layers=args.gpu_layers, ctl=_control(args))


def _cmd_guide(args):
    path = _api.os.path.join(_api.os.path.dirname(_api.os.path.abspath(_api.__file__)),
                             "docs", "montage-agent-amv.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise _api.ToolError("usage", f"памятка не прочитана: {e}") from e
    return {"path": path, "guide": text}


def _search_args(sp):
    sp.add_argument("--db", default="", help="база каталога (по умолчанию — в кэше)")
    sp.add_argument("--query", default="", help="текст: теги, надписи, описания (rapidfuzz)")
    sp.add_argument("--tags", default="", help="все эти теги WD (через запятую)")
    sp.add_argument("--any-tags", default="", help="хотя бы один из тегов")
    sp.add_argument("--no-tags", default="", help="ни одного из тегов")
    sp.add_argument("--character", default="", help="id или имя персонажа, или тег персонажа WD")
    sp.add_argument("--motion-min", type=float, default=None,
                    help="движение, доля ширины кадра в секунду")
    sp.add_argument("--motion-max", type=float, default=None)
    sp.add_argument("--min-len", type=float, default=None, help="длина плана, с")
    sp.add_argument("--max-len", type=float, default=None)
    sp.add_argument("--bright-min", type=float, default=None, help="яркость 0…1")
    sp.add_argument("--bright-max", type=float, default=None)
    sp.add_argument("--scale", default="", help="крупность: closeup,medium,wide,none")
    sp.add_argument("--static", action="store_true", help="только статичные планы")
    sp.add_argument("--moving", action="store_true", help="только не статичные")
    sp.add_argument("--no-text", action="store_true", help="без надписей и хардсаба")
    sp.add_argument("--with-oped", action="store_true", help="включая опенинг и эндинг")
    sp.add_argument("--with-transitions", action="store_true", help="включая растворения")
    sp.add_argument("--file", default="", help="часть пути файла")
    sp.add_argument("--ids", default="", help="id планов через запятую")
    sp.add_argument("--limit", type=int, default=50)


def _analysis_args(sp):
    sp.add_argument("--kinds", default="", help="через запятую: " + ",".join(_api.ANALYSIS_KINDS)
                    + " (без --kinds — scene,beat,onset,silence,speech,word)")
    sp.add_argument("--t0", type=float, default=0.0)
    sp.add_argument("--t1", type=float, default=None)
    sp.add_argument("--scene-threshold", type=float, default=_api.SCENE_THRESHOLD)
    sp.add_argument("--vocals", action="store_true",
                    help="слова — по вокалу (отделить HTDemucs; только для песен)")
    sp.add_argument("--lyrics", default="",
                    help="файл текста песни: слова word — из него, время — lyric-align")
    sp.add_argument("--lyric-lines", default="", help="строки файла текста: 9-24,30")
    sp.add_argument("--beat-model", choices=_api.BEAT_MODELS, default=_api.DEFAULT_BEAT_MODEL,
                    help="Beat This! для бита и карты песни")
    sp.add_argument("--progress", action="store_true", help="этапы строками JSON в stderr")
    sp.add_argument("--cancel-file", default="", help="появился этот файл — отмена")
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
        sp.add_argument("--preview", action="store_true",
                        help="превью: кадр 540p (пропорции проекта) и --encoder gpu")
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
    sp = sub.add_parser("music", help="карта песни: доли, такты, части, удары, места резов")
    sp.add_argument("media", help="звук или видео с песней")
    sp.add_argument("--t0", type=float, default=0.0)
    sp.add_argument("--t1", type=float, default=None)
    sp.add_argument("--stream", type=int, default=-1, help="абсолютный индекс звукового потока")
    sp.add_argument("--beat-model", choices=_api.BEAT_MODELS, default=_api.DEFAULT_BEAT_MODEL)
    sp.add_argument("--no-drums", action="store_true", help="без ударов (HTDemucs)")
    sp.add_argument("--no-sections", action="store_true", help="без частей песни")
    sp.add_argument("--fps", type=float, default=0.0,
                    help="места резов на сетке кадров (с --write — fps проекта)")
    sp.add_argument("--lead", type=int, default=0, help="рез раньше доли на N кадров")
    sp.add_argument("--write", default="", help="проект: записать маркеры во время проекта")
    sp.add_argument("--track", type=int, default=None, help="дорожка клипа с этой песней")
    sp.add_argument("--kinds", default="", help="виды маркеров для --write: "
                    + ",".join(_api.MUSIC_KINDS))
    sp.add_argument("--gemini", action="store_true",
                    help="подписи частей — один запрос Gemini по звуку (квота пользователя)")
    sp.add_argument("--brief", action="store_true", help="без длинных списков долей и ударов")
    sp.add_argument("--segment", type=float, default=0.0,
                    help="сплошной кусок ~N с по границам частей (песня ≤ N×1,25 — целиком)")
    sp.add_argument("--segment-out", default="", help="вырезать кусок в WAV (затухание 3 с)")
    sp.add_argument("--overwrite", action="store_true", help="перезаписать --segment-out")
    sp.add_argument("--ml-python", default="", help="Python генератора (torch, demucs)")
    sp.add_argument("--progress", action="store_true", help="этапы строками JSON в stderr")
    sp.add_argument("--cancel-file", default="", help="появился этот файл — отмена")
    _lenient_arg(sp)
    sp.set_defaults(fn=_cmd_music)
    sp = sub.add_parser("index", help="каталог планов файла или папки (SQLite + миниатюры)")
    sp.add_argument("target", help="видеофайл или папка")
    sp.add_argument("--db", default="", help="база каталога (по умолчанию — в кэше)")
    sp.add_argument("--force", action="store_true", help="заново, даже если файл не менялся")
    sp.add_argument("--tagger", choices=("vit", "eva02"), default="vit",
                    help="WD tagger v3: vit (0,7 с/кадр) или eva02 (2,9 с/кадр)")
    sp.add_argument("--gemini", action="store_true",
                    help="описания сцен: серия в File API, один запрос Gemini (квота пользователя)")
    sp.add_argument("--gemini-model", default="", help="модель Gemini (по умолчанию — Flash-Lite)")
    sp.add_argument("--speech", action="store_true",
                    help="реплики серий (Whisper) — для lines и op voice")
    sp.add_argument("--speech-model", default=_api.DEFAULT_SPEECH_MODEL,
                    help="модель faster-whisper (small — быстрее, medium — точнее)")
    sp.add_argument("--language", default="auto", help="язык речи (ru, ja, en…; auto)")
    sp.add_argument("--ml-python", default="", help="Python с faster-whisper")
    sp.add_argument("--captions", action="store_true",
                    help="подписи планов локальной моделью (llama.cpp, Qwen3.5-2B) для --query")
    sp.add_argument("--gpu-layers", type=int, default=_api.CAPTION_GPU_LAYERS,
                    help="слои текста подписей на видеокарте (0 — процессор)")
    sp.add_argument("--progress", action="store_true", help="этапы строками JSON в stderr")
    sp.add_argument("--cancel-file", default="", help="появился этот файл — отмена")
    sp.set_defaults(fn=_cmd_index)
    sp = sub.add_parser("lines", help="реплики каталога по фразе (index --speech)")
    sp.add_argument("--say", required=True, help="фраза (язык — как в сериях)")
    sp.add_argument("--db", default="")
    sp.add_argument("--file", default="", help="часть пути файла")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--min-score", type=float, default=0.6, help="сходство 0…1")
    sp.set_defaults(fn=_cmd_lines)
    sp = sub.add_parser("search", help="поиск планов каталога")
    _search_args(sp)
    sp.add_argument("--brief", action="store_true", help="только главные поля")
    sp.set_defaults(fn=_cmd_search)
    sp = sub.add_parser("shot-sheet", help="лист найденных планов с id (PNG)")
    sp.add_argument("output")
    _search_args(sp)
    sp.add_argument("--tile-width", type=int, default=320)
    sp.add_argument("--columns", type=int, default=0)
    sp.set_defaults(fn=_cmd_shot_sheet, limit=24)
    sp = sub.add_parser("characters", help="персонажи каталога (кластеры CCIP)")
    sp.add_argument("--db", default="")
    sp.add_argument("--rename", nargs=2, metavar=("ID", "ИМЯ"), help="дать кластеру имя")
    sp.add_argument("--recluster", action="store_true", help="пересобрать кластеры")
    sp.set_defaults(fn=_cmd_characters)
    sp = sub.add_parser("edit", help="точечные правки проекта списком операций")
    sp.add_argument("project")
    sp.add_argument("--ops", required=True, help="JSON: список операций (или {\"ops\": […]})")
    sp.add_argument("--db", default="", help="каталог планов для add по shot")
    sp.add_argument("--dry-run", action="store_true", help="не сохранять, только отчёт")
    _lenient_arg(sp)
    sp.set_defaults(fn=_cmd_edit)
    sp = sub.add_parser("autofill", help="черновик AMV: песня + каталог планов")
    sp.add_argument("project", help="новый проект (.json)")
    sp.add_argument("--song", required=True)
    sp.add_argument("--library", default="", help="каталог планов (по умолчанию — в кэше)")
    sp.add_argument("--plan", default="", help="JSON плана: файлы, теги частей, prefer/avoid")
    sp.add_argument("--t0", type=float, default=None, help="начало окна песни, с")
    sp.add_argument("--t1", type=float, default=None)
    sp.add_argument("--duration", type=float, default=None,
                    help="длина окна, с (без t0 — окно выбирается по частям)")
    sp.add_argument("--min-shot", type=float, default=0.35)
    sp.add_argument("--fx", default="", help="эффекты по ударам: amv или soft")
    sp.add_argument("--template", default="",
                    help="скелет эталона (reference --out): резы на его доли, маркеры custom pop/flash")
    sp.add_argument("--style", default="",
                    help="стиль AMV (styles): шаг резов по частям, эффекты и переходы, отделка")
    sp.add_argument("--gemini", action="store_true",
                    help="части песни — запрос Gemini (готовая карта music --gemini берётся из кэша и так)")
    sp.add_argument("--beat-model", choices=_api.BEAT_MODELS, default=_api.DEFAULT_BEAT_MODEL)
    sp.add_argument("--overwrite", action="store_true")
    sp.add_argument("--progress", action="store_true")
    sp.add_argument("--cancel-file", default="")
    sp.set_defaults(fn=_cmd_autofill)
    sp = sub.add_parser("styles", help="стили AMV (docs/amv-styles): список или один с шрифтами ролей")
    sp.add_argument("name", nargs="?", default="", help="имя стиля или путь к .json")
    sp.set_defaults(fn=_cmd_styles)
    sp = sub.add_parser("reference", help="скелет готового AMV: резы и слои в долях песни")
    sp.add_argument("video")
    sp.add_argument("--out", default="", help="записать скелет JSON (для autofill --template)")
    sp.add_argument("--beat-model", choices=_api.BEAT_MODELS, default=_api.DEFAULT_BEAT_MODEL)
    sp.add_argument("--progress", action="store_true")
    sp.add_argument("--cancel-file", default="")
    sp.set_defaults(fn=_cmd_reference)
    sp = sub.add_parser("check-sync", help="отчёт: резы против долей и ударов, плотность, повторы")
    sp.add_argument("project")
    sp.add_argument("--db", default="", help="каталог планов (тёмные кадры, хардсаб, OP/ED)")
    sp.add_argument("--vocals", action="store_true",
                    help="запаздывание текста — по атакам вокала (стем HTDemucs из кэша песни)")
    sp.add_argument("--ml-python", default="", help="Python генератора (demucs)")
    sp.add_argument("--progress", action="store_true", help="этапы строками JSON в stderr")
    sp.add_argument("--cancel-file", default="", help="появился этот файл — отмена")
    _lenient_arg(sp)
    sp.set_defaults(fn=_cmd_check_sync)
    sp = sub.add_parser("beat-strip", help="ритм-лента PNG: волна, доли, части, резы, клипы")
    sp.add_argument("project")
    sp.add_argument("t0", type=float)
    sp.add_argument("t1", type=float)
    sp.add_argument("output")
    sp.add_argument("--width", type=int, default=2000)
    sp.add_argument("--db", default="")
    _lenient_arg(sp)
    sp.set_defaults(fn=_cmd_beat_strip)
    sp = sub.add_parser("look", help="вопрос локальной модели зрения по картинкам (llama.cpp)")
    sp.add_argument("images", nargs="+", help="png, jpg (webp и прочее — перекодируется)")
    sp.add_argument("--prompt", default="")
    sp.add_argument("--prompt-file", default="")
    sp.add_argument("--schema", default="", help="JSON Schema ответа (файл)")
    sp.add_argument("--model", choices=sorted(_api.LOOK_MODELS), default=_api.DEFAULT_LOOK_MODEL)
    sp.add_argument("--max-tokens", type=int, default=512)
    sp.add_argument("--gpu-layers", type=int, default=0,
                    help="слоёв текста на видеокарте (0 — процессор; iGPU с общей памятью так быстрее)")
    sp.add_argument("--progress", action="store_true")
    sp.add_argument("--cancel-file", default="")
    sp.set_defaults(fn=_cmd_look)
    sp = sub.add_parser("guide", help="памятка агента по монтажу AMV")
    sp.set_defaults(fn=_cmd_guide)
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
