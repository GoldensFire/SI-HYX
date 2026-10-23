# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Схема файла проекта: версии и проверка. Public namespace: montage_project.

Проект от внешнего агента — недоверенные данные: строгая проверка называет
каждое неизвестное поле, неверный тип и несогласованность (клип не той
дорожки, выход за длину исходника, наложение на свободной дорожке), а не
выбрасывает их молча, как мягкая загрузка вкладки."""
import math
import os
import re

import montage_project as _api

_TOP_FIELDS = ("version", "tracks", "clips", "settings")
_TRACK_FIELDS = {"kind": str, "enabled": bool, "muted": bool}
_CLIP_FIELDS = {
    "src": str, "in_s": float, "out_s": float, "track": int, "start": float, "id": str,
    "has_video": bool, "is_image": bool, "audio_path": str, "audio_stream": int,
    "volume": float, "muted": bool, "speed": float, "audio_detached": bool,
    "width": int, "height": int, "fps": float, "src_duration": float,
}
_CLIP_REQUIRED = ("src", "in_s", "out_s", "track")
_SETTINGS_FIELDS = {"width": int, "height": int, "fps": float, "fit": str,
                    "background": str, "loudness": float}
_COLOR_RX = re.compile(r"#[0-9A-Fa-f]{6}")
_MAX_SIDE = 8192
_MAX_FPS = 240.0
_LOUDNESS_RANGE = (-70.0, -5.0)
_EPS = 1e-6


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _type_ok(v, kind):
    if kind is float:
        return _is_num(v)
    if kind is int:
        return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, kind)


def _type_name(kind):
    return {float: "число", int: "целое", bool: "true/false", str: "строка"}[kind]


def migrate_project_data(data):
    """Словарь проекта в схеме PROJECT_VERSION. v1 (без настроек формата)
    становится v2 с форматом «по первому клипу». ProjectError — версия не
    целое число или новее программы: такой файл не загружается молча."""
    if not isinstance(data, dict):
        raise _api.ProjectError("проект должен быть JSON-объектом")
    version = data.get("version", 1)
    if not _type_ok(version, int):
        raise _api.ProjectError("версия проекта должна быть целым числом",
                                [{"path": "version", "message": "не целое число"}])
    if version > _api.PROJECT_VERSION:
        raise _api.ProjectError(
            f"проект версии {version} новее программы (знает до {_api.PROJECT_VERSION})",
            [{"path": "version", "message": f"неизвестная версия {version}"}])
    if version < 1:
        raise _api.ProjectError(f"неверная версия проекта {version}",
                                [{"path": "version", "message": "версия меньше 1"}])
    out = dict(data)
    if version < 2:
        # v1: формат итога — по первому клипу (как в v2 без настроек).
        out.setdefault("settings", {})
    out["version"] = _api.PROJECT_VERSION
    return out


def _num_or(v, default):
    """Число из v (и из строки с числом — так приводит мягкая загрузка) или
    default."""
    if isinstance(v, bool):
        return float(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _check_fields(obj, spec, path, strict, problems, required=(), nullable=()):
    """Неизвестные поля (только strict), обязательные и типы."""
    for name in required:
        if name not in obj:
            problems.append({"path": f"{path}.{name}", "message": "обязательное поле"})
    for name, value in obj.items():
        kind = spec.get(name)
        if kind is None:
            if strict:
                problems.append({"path": f"{path}.{name}", "message": "неизвестное поле"})
            continue
        if value is None and name in nullable:
            continue
        if strict:
            ok = _type_ok(value, kind)
        elif kind in (float, int):
            f = _num_or(value, None)
            ok = f is not None and (kind is float or f.is_integer())
        else:
            ok = True                    # мягкая загрузка приводит строки и флаги сама
        if not ok:
            problems.append({"path": f"{path}.{name}",
                             "message": f"ожидается {_type_name(kind)}"})


def parse_settings(raw):
    """ProjectSettings из словаря настроек; неверные значения — по умолчанию
    (мягкая загрузка). Строгая проверка — validate."""
    s = _api.ProjectSettings()
    if not isinstance(raw, dict):
        return s
    w, h = raw.get("width"), raw.get("height")
    if _is_num(w) and _is_num(h) and 16 <= w <= _MAX_SIDE and 16 <= h <= _MAX_SIDE:
        s.width, s.height = int(w), int(h)
    fps = raw.get("fps")
    if _is_num(fps) and 1.0 <= fps <= _MAX_FPS:
        s.fps = float(fps)
    if raw.get("fit") in _api.FIT_MODES:
        s.fit = raw["fit"]
    bg = raw.get("background")
    if isinstance(bg, str) and _COLOR_RX.fullmatch(bg):
        s.background = bg.lower()
    loud = raw.get("loudness")
    if _is_num(loud) and _LOUDNESS_RANGE[0] <= loud <= _LOUDNESS_RANGE[1]:
        s.loudness = float(loud)
    return s


def _check_settings(raw, strict, problems):
    if not isinstance(raw, dict):
        problems.append({"path": "settings", "message": "должен быть объектом"})
        return
    _check_fields(raw, _SETTINGS_FIELDS, "settings", strict, problems,
                  nullable=("loudness",))
    w, h = raw.get("width", 0), raw.get("height", 0)
    if _is_num(w) and _is_num(h):
        if (w > 0) != (h > 0):
            problems.append({"path": "settings", "message": "ширина и высота задаются вместе"})
        for name, v in (("width", w), ("height", h)):
            if v and not 16 <= v <= _MAX_SIDE:
                problems.append({"path": f"settings.{name}",
                                 "message": f"0 (по первому клипу) или 16…{_MAX_SIDE}"})
    fps = raw.get("fps", 0)
    if _is_num(fps) and fps and not 1.0 <= fps <= _MAX_FPS:
        problems.append({"path": "settings.fps", "message": f"0 (по первому клипу) или 1…{_MAX_FPS:g}"})
    fit = raw.get("fit", "fit")
    if isinstance(fit, str) and fit not in _api.FIT_MODES:
        problems.append({"path": "settings.fit", "message": f"одно из {', '.join(_api.FIT_MODES)}"})
    bg = raw.get("background", "#000000")
    if isinstance(bg, str) and not _COLOR_RX.fullmatch(bg):
        problems.append({"path": "settings.background", "message": "цвет вида #RRGGBB"})
    loud = raw.get("loudness")
    if loud is not None and _is_num(loud) and not _LOUDNESS_RANGE[0] <= loud <= _LOUDNESS_RANGE[1]:
        problems.append({"path": "settings.loudness",
                         "message": f"LUFS от {_LOUDNESS_RANGE[0]:g} до {_LOUDNESS_RANGE[1]:g} или null"})


def _check_tracks(raw, strict, problems):
    """Список видов дорожек (None — дорожки не заданы: будут стандартные)."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        problems.append({"path": "tracks", "message": "должен быть списком"})
        return None
    kinds = []
    for i, t in enumerate(raw):
        path = f"tracks[{i}]"
        if not isinstance(t, dict):
            problems.append({"path": path, "message": "должен быть объектом"})
            kinds.append(None)
            continue
        _check_fields(t, _TRACK_FIELDS, path, strict, problems, required=("kind",))
        kind = t.get("kind")
        if kind not in ("video", "audio"):
            problems.append({"path": f"{path}.kind", "message": "video или audio"})
            kind = None
        kinds.append(kind)
    if "video" not in kinds:
        problems.append({"path": "tracks", "message": "нужна хотя бы одна видеодорожка"})
        return None
    return kinds


def _check_clip(raw, i, kinds, main, strict, check_files, problems):
    """Проблемы одного клипа; (дорожка, начало, конец) для проверки наложений
    или None."""
    path = f"clips[{i}]"
    if not isinstance(raw, dict):
        problems.append({"path": path, "message": "должен быть объектом"})
        return None
    before = len(problems)
    _check_fields(raw, _CLIP_FIELDS, path, strict, problems, required=_CLIP_REQUIRED)
    if len(problems) > before:
        bad = {p["path"] for p in problems[before:]}
        if any(f"{path}.{n}" in bad for n in _CLIP_REQUIRED):
            return None
    in_s, out_s = _num_or(raw.get("in_s"), 0.0), _num_or(raw.get("out_s"), 0.0)
    image = bool(raw.get("is_image", False))
    has_video = bool(raw.get("has_video", True))
    speed = 1.0 if image else _num_or(raw.get("speed", 1.0), 1.0)
    if not image and not _api.MIN_SPEED <= speed <= _api.MAX_SPEED:
        problems.append({"path": f"{path}.speed",
                         "message": f"от {_api.MIN_SPEED:g} до {_api.MAX_SPEED:g}"})
        speed = max(_api.MIN_SPEED, min(_api.MAX_SPEED, speed))
    if in_s < 0:
        problems.append({"path": f"{path}.in_s", "message": "отрицательное время исходника"})
    length = (out_s - in_s) / speed
    if length < _api.MIN_CLIP_S - _EPS:
        problems.append({"path": f"{path}.out_s",
                         "message": f"клип короче {_api.MIN_CLIP_S:g} с (out_s ≤ in_s?)"})
    src_dur = _num_or(raw.get("src_duration", 0.0), 0.0)
    if src_dur > 0 and not image and out_s > src_dur + 1e-3:
        problems.append({"path": f"{path}.out_s",
                         "message": f"за концом исходника ({src_dur:g} с)"})
    if _num_or(raw.get("volume", 1.0), 1.0) < 0:
        problems.append({"path": f"{path}.volume", "message": "отрицательная громкость"})
    stream = _num_or(raw.get("audio_stream", -1), -1)
    if stream < -1:
        problems.append({"path": f"{path}.audio_stream", "message": "-1 или индекс потока"})
    if image and not has_video:
        problems.append({"path": f"{path}.is_image", "message": "картинка без видео"})
    audio_path = raw.get("audio_path") or ""
    if not has_video and not audio_path:
        problems.append({"path": f"{path}.audio_path", "message": "звуковой клип без звука"})
    track = _num_or(raw.get("track"), None)
    if track is None or not track.is_integer():
        return None
    track = int(track)
    if kinds is not None:
        if not 0 <= track < len(kinds):
            problems.append({"path": f"{path}.track", "message": "нет такой дорожки"})
            return None
        want = "video" if has_video else "audio"
        if kinds[track] is not None and kinds[track] != want:
            problems.append({"path": f"{path}.track",
                             "message": f"{'видеоклип' if has_video else 'звуковой клип'} "
                                        f"на дорожке {kinds[track]}"})
    for name in ("src", "audio_path"):
        p = raw.get(name)
        if not isinstance(p, str) or not p:
            continue
        if strict and not os.path.isabs(p):
            problems.append({"path": f"{path}.{name}", "message": "нужен абсолютный путь"})
        elif check_files and not os.path.isfile(p):
            problems.append({"path": f"{path}.{name}", "message": "нет файла"})
    if track == main:
        return None                      # основная дорожка магнитная — место задаёт порядок
    start = _num_or(raw.get("start", 0.0), 0.0)
    if start < 0:
        problems.append({"path": f"{path}.start", "message": "отрицательное место на шкале"})
    return track, start, start + max(0.0, length)


def validate(data, strict=True, check_files=True):
    """Проблемы проекта: [{'path': путь поля, 'message': что не так}], пусто —
    проект годен. strict — для внешних агентов: неизвестные поля, точные
    типы, абсолютные пути, повторы id и наложения на свободных дорожках;
    мягкий режим — то, что вкладка при загрузке выбросит или исправит.
    check_files — проверять, что файлы клипов есть на диске."""
    problems = []
    if strict and isinstance(data, dict) and "version" not in data:
        problems.append({"path": "version", "message": "обязательное поле"})
    try:
        data = migrate_project_data(data)
    except _api.ProjectError as e:
        return problems + (e.problems or [{"path": "", "message": str(e)}])
    if strict:
        for name in data:
            if name not in _TOP_FIELDS:
                problems.append({"path": name, "message": "неизвестное поле"})
    _check_settings(data.get("settings", {}), strict, problems)
    kinds = _check_tracks(data.get("tracks"), strict, problems)
    if kinds is None and data.get("tracks") is None:
        kinds = [t.kind for t in _api.Project().tracks]
    main = kinds.index("video") if kinds else 0
    clips = data.get("clips", [])
    if not isinstance(clips, list):
        problems.append({"path": "clips", "message": "должен быть списком"})
        return problems
    spans, ids = [], {}
    for i, raw in enumerate(clips):
        spans.append(_check_clip(raw, i, kinds, main, strict, check_files, problems))
        cid = raw.get("id") if isinstance(raw, dict) else None
        if strict and isinstance(cid, str) and cid:
            if cid in ids:
                problems.append({"path": f"clips[{i}].id",
                                 "message": f"повтор id клипа clips[{ids[cid]}]"})
            ids.setdefault(cid, i)
    if strict:
        by_track = {}
        for i, sp in enumerate(spans):
            if sp is not None:
                by_track.setdefault(sp[0], []).append((sp[1], sp[2], i))
        for items in by_track.values():
            items.sort()
            for (a0, a1, ai), (b0, _b1, bi) in zip(items, items[1:]):
                if b0 < a1 - 1e-4:
                    problems.append({"path": f"clips[{bi}].start",
                                     "message": f"налезает на clips[{ai}] на той же дорожке"})
    return problems
