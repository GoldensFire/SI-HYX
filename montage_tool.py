# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# montage_tool.py — «Монтаж» без интерфейса: команды и API для внешней
# нейросети (агента), которая собирает проект и рендерит его.
"""«Монтаж» без интерфейса: CLI и API поверх montage_project.

    python -I montage_tool.py <команда> [аргументы]

Команды (ответ — один JSON в stdout, ошибка — JSON с "ok": false и код
выхода ≠ 0; подробности — `python -I montage_tool.py <команда> -h`):
  probe <файл>…              размер как на экране, fps, длина, потоки, HDR;
  validate <проект.json>     загрузка проекта и найденные проблемы;
  describe <проект.json>     таймлайн: время проекта ↔ время исходника,
                             что видно и что слышно;
  dry-run <проект.json> <выход>   команда ffmpeg и граф без запуска;
  render <проект.json> <выход>    сборка: прогресс (-progress), отмена,
                             длинный граф — файлом, +faststart.

Модуль не импортирует PyQt6 (config, utils, edit_tab): ffmpeg ищет
ffmpeg_env, свойства файлов — media_probe, граф — montage_project.build_export,
тот же, что у «Экспорт» вкладки. Реализация — si_hyx_parts/montage_tool/."""
import os
import sys

if __name__ == "__main__":
    # -I не кладёт папку скрипта в sys.path — без неё не найти соседние
    # модули. Части обращаются к модулю по имени montage_tool, поэтому
    # работает импортированный модуль, а не копия __main__.
    _root = os.path.dirname(os.path.abspath(__file__))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import montage_tool
    sys.exit(montage_tool.main())

import json
import subprocess
import tempfile

import ffmpeg_env
import hdr_tonemap
import media_probe
import montage_project
from ffmpeg_env import CREATE_NO_WINDOW, FFMPEG, FFPROBE, escape_filter_path

# Длинная команда ffmpeg: граф фильтров уходит в файл (-/filter_complex) —
# у Windows предел командной строки 32767 символов (как у «Экспорт» вкладки).
INLINE_GRAPH_MAX = 6000
ENCODERS = {"auto": 0, "cpu": 1, "gpu": 2}     # как список «Кодировщик» вкладки


class ToolError(Exception):
    """Ошибка команды: code — короткий машинный код, problems — список
    {'path', 'message'} (проверка проекта), detail — хвост вывода ffmpeg."""

    def __init__(self, code, message, problems=None, detail=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.problems = list(problems or [])
        self.detail = detail

    def to_dict(self):
        out = {"code": self.code, "message": self.message}
        if self.problems:
            out["problems"] = self.problems
        if self.detail:
            out["detail"] = self.detail
        return out


from si_hyx_parts.montage_tool.project_io import (  # noqa: E402,F401
    load_project_file, project_from_data, read_project_json)
from si_hyx_parts.montage_tool.timeline import describe_project  # noqa: E402,F401
from si_hyx_parts.montage_tool.render import (  # noqa: E402,F401
    dry_run, export_command, missing_files, render)
from si_hyx_parts.montage_tool.cli import main  # noqa: E402,F401
