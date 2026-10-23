# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Проект для headless-команд: чтение файла без молчаливых подмен.
Public namespace: montage_tool.

montage_project.load_project на любой ошибке отдаёт пустой проект — вкладке
так удобнее, а агенту нужна причина: битый JSON, не тот тип, выпавшие
клипы. Здесь ошибка — ToolError, а потери — в списке проблем."""
import montage_tool as _api

# Больше не читаем: проект — это дорожки и клипы, а не медиа.
_MAX_PROJECT_BYTES = 32 * 1024 * 1024


def read_project_json(path):
    """dict из файла проекта или ToolError (нет файла, не JSON, не объект)."""
    path = str(path)
    try:
        size = _api.os.path.getsize(path)
    except OSError as e:
        raise _api.ToolError("project_not_found", f"проект не прочитан: {e}") from e
    if size > _MAX_PROJECT_BYTES:
        raise _api.ToolError("project_too_large", f"проект больше {_MAX_PROJECT_BYTES} байт")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _api.json.load(f)
    except (OSError, ValueError) as e:
        raise _api.ToolError("project_invalid_json", f"проект — не JSON: {e}") from e
    if not isinstance(data, dict):
        raise _api.ToolError("project_invalid", "проект должен быть JSON-объектом")
    return data


def project_from_data(data):
    """(Project, проблемы) из словаря проекта. Проблемы — клипы и дорожки,
    которые загрузка выбросила (путь поля и причина)."""
    if not isinstance(data, dict):
        raise _api.ToolError("project_invalid", "проект должен быть JSON-объектом")
    p = _api.montage_project.Project.from_dict(data)
    problems = []
    raw_clips = data.get("clips")
    if raw_clips is not None and not isinstance(raw_clips, list):
        problems.append({"path": "clips", "message": "должен быть списком — клипы не загружены"})
    elif raw_clips:
        kept = {c.id for c in p.clips}
        for i, raw in enumerate(raw_clips):
            cid = str(raw.get("id")) if isinstance(raw, dict) and raw.get("id") else ""
            if not cid or cid not in kept:
                problems.append({"path": f"clips[{i}]", "message": "клип не загружен"})
    raw_tracks = data.get("tracks")
    if raw_tracks is not None and (not isinstance(raw_tracks, list)
                                   or len(p.tracks) != len(raw_tracks)):
        problems.append({"path": "tracks", "message": "дорожки не загружены — взяты стандартные"})
    return p, problems


def load_project_file(path):
    """(Project, проблемы) из файла проекта; ToolError — файл не читается."""
    return project_from_data(read_project_json(path))
