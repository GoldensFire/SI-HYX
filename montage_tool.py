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
  schema                     формат файла проекта: поля, виды, пределы;
  probe <файл>…              размер как на экране, fps, длина, потоки, HDR;
  validate <проект.json>     загрузка проекта и найденные проблемы;
  describe <проект.json>     таймлайн: время проекта ↔ время исходника,
                             что видно и что слышно;
  dry-run <проект.json> <выход>   команда ffmpeg и граф без запуска;
  render <проект.json> <выход>    сборка: прогресс (-progress), отмена,
                             длинный граф — файлом, +faststart;
  still <проект.json> <t> <кадр.png>        кадр проекта на времени t;
  contact-sheet <проект.json> <t0> <t1> <n> <лист.png>   n кадров сеткой
                             с временем проекта и id клипа под каждым;
  preview <проект.json> <t0> <t1> <ролик.mp4>   до 15 с, 480p, 12 fps,
                             до 8 МБ — для модели (Gemini);
  ask <файл>… --schema <схема.json> --prompt …  превью/кадры и вопрос в
                             GeminiClient.generate_json (тратит квоту);
  analyze <проект.json> [--kinds scene,beat,…] [--track N] [--write]
                             маркеры во времени проекта (--write — в проект);
  analyze-file <файл> [--kinds …]   маркеры во времени файла;
  stems <файл> <папка>       вокал и музыка (HTDemucs, Python генератора);
  music <звук|видео> [--write <проект> --track N] [--gemini] [--brief]
                             карта песни: темп, размер, доли с номером в такте,
                             такты, фразы, части, энергия, удары барабанов,
                             места для резов (Beat This!, HTDemucs, librosa).

Долгие команды (music, analyze с видами карты песни) пишут этапы строками
JSON в stderr (--progress) и отменяются файлом (--cancel-file). Кэш, модели
по требованию с SHA-256 и обработчики — si_hyx_parts/montage_tool/jobs.py.

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

import dataclasses
import json
import shutil
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
    check_output, dry_run, export_command, missing_files, render)
from si_hyx_parts.montage_tool.inspection import (  # noqa: E402,F401
    ask_model, contact_sheet, gemini_key, preview, sheet_times, still)
from si_hyx_parts.montage_tool.jobs import (  # noqa: E402,F401
    ASSETS, NO_CONTROL, Control, asset, cache_dir, ensure_packages, run_worker)
from si_hyx_parts.montage_tool.analysis import (  # noqa: E402,F401
    ANALYSIS_KINDS, SCENE_THRESHOLD, analyze_file, analyze_project, file_audio,
    merge_markers, project_audio, stems)
from si_hyx_parts.montage_tool.music import (  # noqa: E402,F401
    BEAT_MODELS, DEFAULT_BEAT_MODEL, MUSIC_KINDS, MUSIC_WRITE_KINDS, SECTION_LABELS,
    clip_mapper, drum_hits, map_markers, music_file, music_project, shift_map, snap_frame,
    snap_slots, song_map)
from si_hyx_parts.montage_tool.cli import main  # noqa: E402,F401
