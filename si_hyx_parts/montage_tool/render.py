# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Сборка проекта без интерфейса: команда как у «Экспорт» вкладки,
прогресс через -progress, отмена, длинный граф — файлом.
Public namespace: montage_tool."""
import collections
import threading
import time

from ffmpeg_faststart import with_faststart

import montage_tool as _api


def missing_files(p):
    """Файлы проекта (картинка и звук клипов), которых нет на диске."""
    srcs = {c.src for c in p.clips} | {c.audio_path for c in p.clips if c.audio_path}
    return sorted(s for s in srcs if not _api.os.path.isfile(s))


def _encoder_args(encoder, encoders=None):
    if encoder not in _api.ENCODERS:
        raise _api.ToolError("bad_encoder", f"кодировщик: {', '.join(_api.ENCODERS)}")
    if encoders is None:
        encoders = _api.ffmpeg_env.available_encoders(_api.FFMPEG)
    return _api.ffmpeg_env.h264_encoder_args(encoders, _api.ENCODERS[encoder])


def export_command(p, out_path, encoder="auto", encoders=None, subs=None):
    """(cmd, graph, duration) — та же сборка, что у «Экспорт» вкладки
    (EditTab.project_export): HDR-куски сводятся в SDR так, как их видно в
    просмотре, граф — montage_project.build_export. ToolError, если
    собирать нечего. encoders — вывод `ffmpeg -encoders` (None — опросить)."""
    tonemap = _api.hdr_tonemap.tonemap_filters(
        (c.src for c in p.clips if c.has_video and not c.is_image), _api.escape_filter_path)
    built = _api.montage_project.build_export(
        p, str(out_path), _api.FFMPEG, _encoder_args(encoder, encoders),
        subs=subs, tonemap=tonemap)
    if built is None:
        raise _api.ToolError("nothing_to_render", "в проекте нечего собирать")
    return built


def _graph_to_file(cmd, graph):
    """Длинная команда → граф в файл (-/filter_complex), как у вкладки.
    Возвращает путь файла или None (команда короткая)."""
    if len(" ".join(cmd)) <= _api.INLINE_GRAPH_MAX:
        return None
    tf = _api.tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False,
                                          suffix=".txt", prefix="sihyx_graph_")
    with tf:
        tf.write(graph)
    i = cmd.index("-filter_complex")
    cmd[i:i + 2] = ["-/filter_complex", tf.name]
    return tf.name


def dry_run(p, out_path, encoder="auto", encoders=None, subs=None):
    """Что запустит render, без запуска: команда (итог — сразу out_path,
    без временного файла), граф, уйдёт ли граф в файл, длина итога."""
    cmd, graph, dur = export_command(p, out_path, encoder, encoders, subs)
    cmd = with_faststart(cmd)
    cmd[1:1] = ["-nostdin", "-nostats", "-progress", "pipe:1"]
    w, h, fps = p.output_format()
    return {"command": cmd, "graph": graph,
            "graph_in_file": len(" ".join(cmd)) > _api.INLINE_GRAPH_MAX,
            "duration": round(dur, 6), "width": w, "height": h, "fps": round(fps, 6),
            "missing_files": missing_files(p)}


def _check_output(p, out_path, overwrite):
    out = _api.os.path.abspath(str(out_path))
    folder = _api.os.path.dirname(out)
    if not _api.os.path.isdir(folder):
        raise _api.ToolError("bad_output", f"нет папки для итога: {folder}")
    if _api.os.path.isdir(out):
        raise _api.ToolError("bad_output", f"итог — это папка: {out}")
    keys = {_api.montage_project.source_key(c.src) for c in p.clips}
    keys |= {_api.montage_project.source_key(c.audio_path) for c in p.clips if c.audio_path}
    if _api.montage_project.source_key(out) in keys:
        raise _api.ToolError("bad_output", "итог совпадает с исходником проекта")
    if _api.os.path.exists(out) and not overwrite:
        raise _api.ToolError("output_exists", f"файл уже есть (нужен --overwrite): {out}")
    return out


def _remove(path):
    if path:
        try:
            _api.os.remove(path)
        except OSError:
            pass


def render(p, out_path, encoder="auto", overwrite=False, on_progress=None,
           should_stop=None, encoders=None, subs=None):
    """Собирает проект в out_path. Пишет во временный файл рядом и переносит
    его на место только при успехе. on_progress(доля 0..1, секунды, длина
    итога);
    should_stop() → True — отмена: ffmpeg убивается, временные файлы
    удаляются, ToolError('cancelled'). Возвращает словарь итога."""
    missing = missing_files(p)
    if missing:
        raise _api.ToolError("missing_files", "не найдены файлы проекта",
                             problems=[{"path": m, "message": "нет файла"} for m in missing])
    out = _check_output(p, out_path, overwrite)
    stem, ext = _api.os.path.splitext(out)
    tmp = f"{stem}.sihyx_part{ext}"
    cmd, graph, dur = export_command(p, tmp, encoder, encoders, subs)
    cmd = with_faststart(cmd)
    # -progress — ключ=значение в stdout раз в полсекунды; stdin закрыт.
    cmd[1:1] = ["-nostdin", "-nostats", "-progress", "pipe:1"]
    graph_file = _graph_to_file(cmd, graph)
    t_start = time.monotonic()
    tail = collections.deque(maxlen=20)
    try:
        proc = _api.subprocess.Popen(
            cmd, stdin=_api.subprocess.DEVNULL, stdout=_api.subprocess.PIPE,
            stderr=_api.subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            creationflags=_api.CREATE_NO_WINDOW)
    except OSError as e:
        _remove(graph_file)
        raise _api.ToolError("ffmpeg_not_started", f"не удалось запустить ffmpeg: {e}") from e

    def _drain():
        # stderr читается своим потоком: иначе полный канал остановит ffmpeg.
        for line in proc.stderr:
            if line.strip():
                tail.append(line.rstrip())

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    cancelled = False
    try:
        for line in proc.stdout:
            if should_stop is not None and should_stop():
                cancelled = True
                break
            key, _, val = line.strip().partition("=")
            if key == "out_time_us" and on_progress is not None and dur > 0:
                try:
                    sec = max(0.0, int(val) / 1e6)
                except ValueError:
                    continue
                on_progress(min(1.0, sec / dur), min(sec, dur), dur)
    except KeyboardInterrupt:
        cancelled = True
    finally:
        if cancelled and proc.poll() is None:
            proc.kill()
        rc = proc.wait()
        reader.join(timeout=5)
        _remove(graph_file)
    if cancelled:
        _remove(tmp)
        raise _api.ToolError("cancelled", "сборка отменена")
    if rc != 0:
        _remove(tmp)
        raise _api.ToolError("ffmpeg_failed", f"ffmpeg завершился с кодом {rc}",
                             detail="\n".join(tail))
    try:
        _api.os.replace(tmp, out)
    except OSError as e:
        _remove(tmp)
        raise _api.ToolError("output_write_failed", f"итог не сохранён: {e}") from e
    if on_progress is not None:
        on_progress(1.0, dur, dur)
    return {"output": out, "duration": round(dur, 6),
            "size": _api.os.path.getsize(out),
            "elapsed": round(time.monotonic() - t_start, 3),
            "graph_in_file": graph_file is not None}
