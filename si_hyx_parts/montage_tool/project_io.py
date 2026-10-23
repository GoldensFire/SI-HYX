# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Проект для headless-команд: чтение файла без молчаливых подмен.
Public namespace: montage_tool.

montage_project.load_project у вкладки мягкий: негодные клипы выбрасываются.
Агенту нужна причина, поэтому по умолчанию проект проверяется строго
(montage_project.validate) и любая проблема — ToolError со списком; lenient
загружает как вкладка, а проблемы только перечисляет."""
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


def project_from_data(data, strict=True, check_files=False):
    """(Project, проблемы). strict — проблемы проверки (montage_project.validate)
    — ToolError('project_invalid'); иначе проект грузится как во вкладке.
    Версия новее программы — ToolError('project_version') в любом режиме."""
    mp = _api.montage_project
    try:
        migrated = mp.migrate_project_data(data)
    except mp.ProjectError as e:
        raise _api.ToolError("project_version", str(e), e.problems) from e
    problems = mp.validate(data, strict=strict, check_files=check_files)
    if strict and problems:
        raise _api.ToolError("project_invalid",
                             f"проект не прошёл проверку: проблем — {len(problems)}", problems)
    return mp.Project.from_dict(migrated), problems


def load_project_file(path, strict=True, check_files=False):
    """(Project, проблемы) из файла проекта; ToolError — файл не читается
    или (strict) проект не прошёл проверку."""
    return project_from_data(read_project_json(path), strict, check_files)
