# -*- coding: utf-8 -*-
"""GUI-обёртка над build.bat: правит версию и флаг «необязательного обновления»
(SILENT_UPDATE) в config.py, синхронизирует version_info.txt, затем запускает
build.bat и показывает лог/прогресс сборки в реальном времени.

Инструмент для разработчика (используется вручную перед релизом) — часть
самой программы SI-HYX не задействует. Запуск: `python build_gui.py`.

Что нового по сравнению с первой версией:
  • версию можно вписать любую (0.7.3, 1.0, 0.8.0-beta.1, уже собранную) —
    проверяются только символы, допустимые в имени папки/архива;
  • прогресс дублируется на иконку в панели задач Windows (taskbar.py);
  • прогресс внутри PyInstaller и архивов, а не только на границах шагов;
  • ETA подстраивается под реальные длительности шагов прошлой сборки;
  • лог буферизуется, чтобы тысячи строк PyInstaller не подвешивали окно.
"""
import codecs
import json
import os
import re
import subprocess
import sys
import time

from PyQt6.QtCore import QProcess, QProcessEnvironment, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from config import STYLESHEET, get_icon
from taskbar import TaskbarProgress

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PY = os.path.join(ROOT, "config.py")
VERSION_INFO_TXT = os.path.join(ROOT, "version_info.txt")
BUILD_BAT = os.path.join(ROOT, "build.bat")
DIST_DIR = os.path.join(ROOT, "dist")
# Сюда build_gui.py складывает длительности шагов последней удачной сборки.
# build/ в .gitignore, поэтому файл не попадает в репозиторий.
TIMINGS_FILE = os.path.join(ROOT, "build", "build_gui_timings.json")

# Версия попадает в имя папки dist и имена zip, поэтому только безопасные для
# Windows-имени символы. Точки/дефисы/плюсы — обычный semver-хвост
# (0.8.0-beta.1, 1.0.0+build.7). Пробелы и \ / : * ? " < > | запрещены.
VERSION_RE = re.compile(r"^[0-9A-Za-z](?:[0-9A-Za-z._+-]{0,38}[0-9A-Za-z])?$")
STEP_RE = re.compile(r"^\[STEP (\d+)/(\d+)\]")
PROGRESS_RE = re.compile(r"^\[PROGRESS (\d+) (\d+)\]")

STEP_NAMES = {
    1: "PyInstaller (проверка)",
    2: "сверка requirements.txt",
    3: "PyInstaller",
    4: "переименование dist",
    5: "update-архив",
    6: "копирование bin/models",
    7: "хеш bin/models",
    8: "full-архив",
    9: "manifest.json",
}

# Стартовые веса, пока нет замеров. По логам прошлых сборок архивы (шаги 5 и
# 8) занимают больше времени, чем сам PyInstaller; после первой удачной
# сборки веса заменяются фактическими (см. _save_timings).
STEP_WEIGHTS = {1: 2, 2: 1, 3: 18, 4: 1, 5: 30, 6: 3, 7: 2, 8: 40, 9: 3}


def _cumulative(weights):
    result = {}
    acc = 0.0
    for n in range(1, 10):
        result[n] = acc
        acc += float(weights.get(n, 0.0))
    return result


CUM_BEFORE = _cumulative(STEP_WEIGHTS)

# PyInstaller печатает стадии в INFO-логе. Проценты — внутри шага 3.
_PYI_STAGES = (
    ("analyzing base_library.zip", 3),
    ("analyzing ", 8),
    ("processing standard module hook", 12),
    ("analyzing hidden import", 30),
    ("looking for dynamic libraries", 45),
    ("warnings written", 52),
    ("graph cross-reference", 55),
    ("building pyz", 60),
    ("building pkg", 68),
    ("building exe", 74),
    ("copying icons", 78),
    ("embedding manifest", 82),
    ("appending pkg archive", 86),
    ("fixing exe headers", 89),
    ("building collect", 92),
    ("completed successfully", 97),
)


def _fmt_seconds(sec: float) -> str:
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m}м {s:02d}с" if m else f"{s}с"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path: str, text: str) -> None:
    """Атомарная запись: оборванная запись не оставит полупустой config.py."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def normalize_version(text: str):
    """Версия из поля ввода или None. Ведущая «v» убирается (v0.7.2 → 0.7.2)."""
    version = (text or "").strip()
    if len(version) > 1 and version[0] in "vV" and version[1].isdigit():
        version = version[1:]
    if not VERSION_RE.fullmatch(version) or not any(ch.isdigit() for ch in version):
        return None
    return version


def version_numbers(version: str):
    """1–4 числовых компонента для Windows-метаданных .exe.

    Хвост после -/+ (beta, build) в filevers не влезает: Windows хранит там
    только четыре числа. Для 0.8.0-beta.1 получится (0, 8, 0, 0), а полная
    строка останется в APP_VERSION и именах архивов.
    """
    core = re.split(r"[-+]", version, maxsplit=1)[0]
    nums = [int(n) for n in re.findall(r"\d+", core)]
    if not nums:                       # версия вида release-1.2
        nums = [int(n) for n in re.findall(r"\d+", version)]
    if not nums:
        raise ValueError("в версии нет ни одного числа")
    return tuple((nums + [0, 0, 0, 0])[:4])


def read_current():
    """Текущие версия и флаг SILENT_UPDATE из config.py (единственный источник правды)."""
    text = _read(CONFIG_PY)
    m = re.search(r'^APP_VERSION = "([^"\n]+)"', text, re.M)
    version = m.group(1) if m else "0.0.0"
    m = re.search(r"^SILENT_UPDATE = (True|False)", text, re.M)
    silent = (m.group(1) == "True") if m else False
    return version, silent


def apply_settings(version: str, silent: bool) -> None:
    """Пишет версию + флаг во все файлы, где они должны совпадать
    (см. main.py:_check_updates / make_manifest.py про SILENT_UPDATE)."""
    version = normalize_version(version)
    if version is None:
        raise ValueError("некорректная версия")
    nums = version_numbers(version)
    file_version = ".".join(str(n) for n in nums)

    config_text = _read(CONFIG_PY)
    config_text, n = re.subn(r'^APP_VERSION = "[^"\n]*"',
                             lambda _m: f'APP_VERSION = "{version}"',
                             config_text, count=1, flags=re.M)
    if n != 1:
        raise ValueError("в config.py не найдена строка APP_VERSION")
    config_text, n = re.subn(r"^SILENT_UPDATE = (True|False)",
                             lambda _m: f"SILENT_UPDATE = {silent}",
                             config_text, count=1, flags=re.M)
    if n != 1:
        raise ValueError("в config.py не найдена строка SILENT_UPDATE")

    info_text = _read(VERSION_INFO_TXT)
    replacements = (
        (r"filevers=\([^)]*\)",
         f"filevers=({nums[0]}, {nums[1]}, {nums[2]}, {nums[3]})"),
        (r"prodvers=\([^)]*\)",
         f"prodvers=({nums[0]}, {nums[1]}, {nums[2]}, {nums[3]})"),
        (r"(StringStruct\('FileVersion', ')[^']*(')",
         lambda m: m.group(1) + file_version + m.group(2)),
        (r"(StringStruct\('ProductVersion', ')[^']*(')",
         lambda m: m.group(1) + file_version + m.group(2)),
    )
    for pattern, replacement in replacements:
        info_text, n = re.subn(pattern, replacement, info_text, count=1)
        if n != 1:
            raise ValueError(f"в version_info.txt не найдено поле {pattern!r}")

    # Сначала готовим оба текста, потом пишем: ошибка разбора не оставит
    # config.py с одной версией, а version_info.txt — с другой.
    _write(CONFIG_PY, config_text)
    _write(VERSION_INFO_TXT, info_text)
    # README версию не упоминает: актуальная всегда видна во вкладке Releases.


def discover_dist_versions():
    """Версии, для которых в dist уже лежит папка/архив."""
    found = set()
    try:
        entries = list(os.scandir(DIST_DIR))
    except OSError:
        return []
    for entry in entries:
        name = entry.name
        match = None
        if entry.is_dir():
            match = re.fullmatch(r"SI-HYX v(.+)", name)
        elif entry.is_file():
            match = (re.fullmatch(r"SI-HYX-v(.+)-full\.zip", name)
                     or re.fullmatch(r"UpdateHYX-v(.+)\.zip", name))
        if match and VERSION_RE.fullmatch(match.group(1)):
            found.add(match.group(1))
    return sorted(found, key=_version_sort_key, reverse=True)


def _version_sort_key(version: str):
    # Числовые компоненты — основной порядок, строка — тай-брейк для
    # 0.8.0-beta/0.8.0. Не претендует на полный semver, но список в combo
    # выглядит предсказуемо.
    nums = tuple(int(n) for n in re.findall(r"\d+", version)) or (0,)
    return nums, version


def existing_artifacts(version: str):
    paths = (
        os.path.join(DIST_DIR, f"SI-HYX v{version}"),
        os.path.join(DIST_DIR, f"UpdateHYX-v{version}.zip"),
        os.path.join(DIST_DIR, f"SI-HYX-v{version}-full.zip"),
    )
    return [p for p in paths if os.path.exists(p)]


class BuildWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SI-HYX — сборка")
        self.setWindowIcon(get_icon("fa5s.hammer"))
        self.resize(920, 700)

        self._current_version, _saved_silent = read_current()
        self._taskbar = TaskbarProgress()
        self._taskbar_hwnd = 0
        self._last_tb_pct = None
        self._weights = {n: float(w) for n, w in STEP_WEIGHTS.items()}
        self._cum_before = _cumulative(self._weights)
        self._load_timings()

        self._building = False
        self._stopped = False
        self._build_seq = 0
        self._progress = 0.0
        self._build_start_ts = 0.0
        self._step_start_ts = 0.0
        self._current_step = None
        self._sub_progress = 0.0
        self._step_times = {}
        self._build_version = ""
        self.proc = None

        c = QWidget()
        self.setCentralWidget(c)
        root = QVBoxLayout(c)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Версия:"))
        self.version_combo = QComboBox()
        self.version_combo.setEditable(True)
        self.version_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.version_combo.setMaxCount(100)
        self.version_combo.setFixedWidth(190)
        self.version_combo.setToolTip(
            "Любая версия: 0.7.3, 1.0, 0.8.0-beta.1, уже собранная — тоже.\n"
            "Ведущая «v» убирается автоматически.")
        self.version_combo.currentTextChanged.connect(self._update_version_hint)
        if self.version_combo.lineEdit() is not None:
            self.version_combo.lineEdit().setPlaceholderText("например, 0.7.3")
        row.addWidget(self.version_combo)
        row.addSpacing(16)
        self.silent_chk = QCheckBox(
            "Необязательное обновление (silent) — без авто-плашки, только вручную")
        row.addWidget(self.silent_chk)
        row.addStretch()
        root.addLayout(row)

        self.version_hint = QLabel("")
        self.version_hint.setWordWrap(True)
        root.addWidget(self.version_hint)

        hint = QLabel(
            "Релиз на GitHub остаётся обычным (не draft/pre-release) — новые скачивания "
            "получают именно его.\nФлаг влияет только на то, всплывает ли авто-плашка "
            "у уже установленных пользователей.")
        hint.setStyleSheet("color:#6c7086;")
        root.addWidget(hint)

        opts = QHBoxLayout()
        self.update_pyinstaller_chk = QCheckBox("Обновлять PyInstaller перед сборкой (медленнее)")
        self.update_pyinstaller_chk.setToolTip(
            "По умолчанию PyInstaller только проверяется. pip --upgrade каждый раз "
            "ходит в сеть и добавляет к сборке десятки секунд.")
        opts.addWidget(self.update_pyinstaller_chk)
        opts.addSpacing(16)
        self.fast_zip_chk = QCheckBox("Быстрые архивы (level 1, zip крупнее)")
        self.fast_zip_chk.setToolTip(
            "Уровень deflate 1 вместо 4: архивы собираются заметно быстрее, "
            "но примерно на четверть больше по размеру.")
        opts.addWidget(self.fast_zip_chk)
        opts.addSpacing(16)
        self.reuse_assets_chk = QCheckBox("Переиспользовать неизменные bin/models")
        self.reuse_assets_chk.setChecked(True)
        self.reuse_assets_chk.setToolTip(
            "Если SHA256 в bin/.binver совпал с прошлым full-архивом, bin/ и models/ "
            "переносятся из него без повторного сжатия. Не совпало — сжимаются заново.")
        opts.addWidget(self.reuse_assets_chk)
        opts.addStretch()
        root.addLayout(opts)

        btn_row = QHBoxLayout()
        self.build_btn = QPushButton("Собрать")
        self.build_btn.setObjectName("b_run")
        self.build_btn.setIcon(get_icon('fa5s.hammer', color='#1e1e2e'))
        self.build_btn.clicked.connect(self._on_build)
        btn_row.addWidget(self.build_btn)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setIcon(get_icon('fa5s.stop'))
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn)
        self.open_dist_btn = QPushButton("Открыть dist")
        self.open_dist_btn.setIcon(get_icon('fa5s.folder-open'))
        self.open_dist_btn.clicked.connect(self._open_dist)
        btn_row.addWidget(self.open_dist_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        prog_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        prog_row.addWidget(self.progress_bar, stretch=1)
        self.eta_lbl = QLabel("")
        self.eta_lbl.setStyleSheet("color:#6c7086;")
        prog_row.addWidget(self.eta_lbl)
        root.addLayout(prog_row)

        self.status_lbl = QLabel("")
        root.addWidget(self.status_lbl)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(40000)
        root.addWidget(self.log, stretch=1)

        self._populate_versions(self._current_version)
        self.silent_chk.setChecked(False)  # всегда выключен по умолчанию — не унаследовать True с прошлого раза
        self._update_version_hint()

        self._eta_timer = QTimer(self)
        self._eta_timer.setInterval(1000)
        self._eta_timer.timeout.connect(self._update_eta)

        # Вывод PyInstaller — тысячи строк; appendPlainText на каждую строку
        # заметно подвешивает окно. Копим и вставляем пачкой.
        self._log_buffer = []
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(120)
        self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.start()
        self._pending_output = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")

        if not self._taskbar.available:
            self._queue_log("[GUI] Прогресс в панели задач недоступен "
                            "(не Windows или панель задач не принимает COM-прогресс).")

    # -- версии ---------------------------------------------------------
    def _populate_versions(self, selected: str = "") -> None:
        selected = selected or self.version_combo.currentText()
        versions = discover_dist_versions()
        if selected and selected not in versions:
            versions.insert(0, selected)
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for version in versions:
            self.version_combo.addItem(version)
        self.version_combo.setEditText(selected)
        self.version_combo.blockSignals(False)

    def _update_version_hint(self) -> None:
        raw = self.version_combo.currentText().strip()
        version = normalize_version(raw)
        if not raw:
            self.version_hint.setText(
                "Можно вписать любую версию — новую или уже собранную. "
                "Например: 0.7.3, 1.0, 0.8.0-beta.1.")
            self.version_hint.setStyleSheet("color:#6c7086;")
            return
        if version is None:
            self.version_hint.setText(
                "Некорректная версия. Разрешены латиница, цифры и . _ + -; "
                "пробелы и \\ / : * ? \" < > | нельзя — они попадут в имя папки и архивов.")
            self.version_hint.setStyleSheet("color:#f38ba8;")
            return

        artifacts = existing_artifacts(version)
        if version == self._current_version:
            extra = (" Файлы в dist будут перезаписаны." if artifacts else "")
            self.version_hint.setText(
                f"Текущая версия из config.py — пересборка разрешена.{extra}")
            self.version_hint.setStyleSheet(
                "color:#f9e2af;" if artifacts else "color:#a6e3a1;")
        elif artifacts:
            self.version_hint.setText(
                f"Версия {version} уже есть в dist — папка/архивы будут перезаписаны.")
            self.version_hint.setStyleSheet("color:#f9e2af;")
        else:
            self.version_hint.setText(
                f"Новая версия {version}. Существующие сборки в dist не трогаются.")
            self.version_hint.setStyleSheet("color:#a6e3a1;")

    # -- прогресс и панель задач ----------------------------------------
    def _tb_hwnd(self) -> int:
        if not self._taskbar_hwnd:
            try:
                self._taskbar_hwnd = int(self.winId())
            except (RuntimeError, TypeError, ValueError):
                self._taskbar_hwnd = 0
        return self._taskbar_hwnd

    def _set_taskbar_state(self, state: int) -> None:
        if self._taskbar.available:
            self._taskbar.set_state(self._tb_hwnd(), state)

    def _set_taskbar_value(self, pct: int) -> None:
        if self._taskbar.available:
            self._taskbar.set_value(self._tb_hwnd(), pct, 100)

    def _clear_taskbar(self) -> None:
        if self._taskbar.available:
            self._taskbar.clear(self._tb_hwnd())
        self._last_tb_pct = None

    def _apply_progress(self, pct: float, force_taskbar: bool = False) -> None:
        pct = max(float(self._progress), min(100.0, float(pct)))
        self._progress = pct
        shown = int(round(pct))
        self.progress_bar.setValue(shown)
        if pct <= 0:
            self._set_taskbar_state(TaskbarProgress.INDETERMINATE)
            self._last_tb_pct = None
            return
        if force_taskbar or shown != self._last_tb_pct:
            self._set_taskbar_value(shown)
            self._last_tb_pct = shown

    def _overall_progress(self, step: int, sub_pct: float) -> float:
        base = self._cum_before.get(step, 0.0)
        weight = self._weights.get(step, 0.0)
        return base + weight * max(0.0, min(100.0, sub_pct)) / 100.0

    def _set_sub_progress(self, step: int, pct: float) -> None:
        if self._current_step != step:
            return
        pct = max(self._sub_progress, min(100.0, float(pct)))
        self._sub_progress = pct
        self._apply_progress(self._overall_progress(step, pct))

    def _on_step_marker(self, step: int) -> None:
        if not 1 <= step <= 9:
            return
        now = time.monotonic()
        if self._current_step is not None:
            self._step_times[self._current_step] = max(0.0, now - self._step_start_ts)
        self._current_step = step
        self._step_start_ts = now
        self._sub_progress = 0.0
        self._apply_progress(self._cum_before.get(step, self._progress))
        self.status_lbl.setText(
            f"Сборка {self._build_version} · шаг {step}/9: {STEP_NAMES.get(step, '')}")

    # -- веса ETA --------------------------------------------------------
    def _load_timings(self) -> None:
        try:
            with open(TIMINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            seconds = data.get("step_seconds", {})
            values = {}
            for key, value in seconds.items():
                step = int(key)
                seconds_value = float(value)
                if 1 <= step <= 9 and seconds_value > 0:
                    values[step] = seconds_value
            if len(values) == 9:
                self._set_weights_from_times(values)
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _set_weights_from_times(self, seconds) -> None:
        total = sum(seconds.values())
        if total <= 0:
            return
        # Минимум 0.5% на шаг: шаг, который в этот раз был мгновенным, не
        # должен «схлопывать» прогресс в ноль на будущих сборках.
        self._weights = {
            n: max(0.5, float(seconds.get(n, 0.0)) / total * 100.0)
            for n in range(1, 10)
        }
        norm = sum(self._weights.values())
        self._weights = {n: w / norm * 100.0 for n, w in self._weights.items()}
        self._cum_before = _cumulative(self._weights)

    def _save_timings(self, total_sec: float) -> None:
        if len(self._step_times) != 9:
            return
        data = {
            "version": self._build_version,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_seconds": round(total_sec, 3),
            "step_seconds": {str(n): round(self._step_times[n], 3)
                             for n in range(1, 10)},
        }
        try:
            os.makedirs(os.path.dirname(TIMINGS_FILE), exist_ok=True)
            tmp = TIMINGS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, TIMINGS_FILE)
        except OSError:
            pass
        self._set_weights_from_times(self._step_times)

    # -- логирование ----------------------------------------------------
    def _queue_log(self, line: str) -> None:
        self._log_buffer.append(line)
        if len(self._log_buffer) >= 2000:
            self._flush_log()

    def _flush_log(self) -> None:
        if not self._log_buffer:
            return
        text = "\n".join(self._log_buffer)
        self._log_buffer.clear()
        self.log.appendPlainText(text)

    def _parse_line(self, line: str) -> None:
        line = line.rstrip("\r")
        if not line:
            return
        match = PROGRESS_RE.match(line)
        if match:
            self._set_sub_progress(int(match.group(1)), int(match.group(2)))
            return
        match = STEP_RE.match(line)
        if match:
            self._on_step_marker(int(match.group(1)))
            self._queue_log(line)
            return
        if self._current_step == 3 and line.startswith(("INFO:", "WARNING:")):
            low = line.lower()
            frac = 0
            for needle, percent in _PYI_STAGES:
                if needle in low:
                    frac = max(frac, percent)
            if frac:
                self._set_sub_progress(3, frac)
        self._queue_log(line)

    def _on_proc_output(self) -> None:
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput())
        text = self._decoder.decode(data)
        self._pending_output += text
        lines = self._pending_output.split("\n")
        self._pending_output = lines.pop()
        for line in lines:
            self._parse_line(line)

    def _flush_pending_output(self) -> None:
        text = self._pending_output + self._decoder.decode(b"", final=True)
        self._pending_output = ""
        for line in text.split("\n"):
            self._parse_line(line)
        self._flush_log()

    # -- сборка ---------------------------------------------------------
    def _on_build(self):
        if self._building:
            return
        version = normalize_version(self.version_combo.currentText())
        if version is None:
            QMessageBox.critical(
                self, "SI-HYX",
                "Некорректная версия.\n\n"
                "Разрешены латиница, цифры и символы . _ + -.\n"
                "Примеры: 0.7.3, 1.0, 0.8.0-beta.1, 0.7.2 (уже собранная).\n\n"
                "Пробелы и \\ / : * ? \" < > | использовать нельзя — версия "
                "попадает в имена папки и архивов.")
            return
        self.version_combo.setEditText(version)

        silent = self.silent_chk.isChecked()
        try:
            apply_settings(version, silent)
        except Exception as e:  # noqa: BLE001 — показать причину в диалоге
            QMessageBox.critical(self, "SI-HYX", f"Не удалось обновить файлы версии: {e}")
            return

        self._current_version = version
        self._build_version = version
        self._update_version_hint()

        self._stopped = False
        self._building = True
        self._build_seq += 1
        self._progress = 0.0
        self._build_start_ts = time.monotonic()
        self._step_start_ts = self._build_start_ts
        self._current_step = None
        self._sub_progress = 0.0
        self._step_times = {}
        self._pending_output = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._log_buffer.clear()
        self.log.clear()

        self.progress_bar.setValue(0)
        self.eta_lbl.setText("Прошло 0с · запуск…")
        self.status_lbl.setText(
            f"Сборка {version}{' (необязательное обновление)' if silent else ''}…")
        self._set_taskbar_state(TaskbarProgress.INDETERMINATE)
        self._last_tb_pct = None
        self._eta_timer.start()
        self.build_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        for widget in (self.version_combo, self.silent_chk,
                       self.update_pyinstaller_chk, self.fast_zip_chk,
                       self.reuse_assets_chk):
            widget.setEnabled(False)

        self._queue_log(
            f"[GUI] Сборка {version}; zip level="
            f"{1 if self.fast_zip_chk.isChecked() else 4}; "
            f"PyInstaller update="
            f"{'yes' if self.update_pyinstaller_chk.isChecked() else 'no'}; "
            f"assets reuse={'yes' if self.reuse_assets_chk.isChecked() else 'no'}")
        self._flush_log()

        env = QProcessEnvironment.systemEnvironment()
        env.insert("NONINTERACTIVE", "1")
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("UPDATE_PYINSTALLER",
                   "1" if self.update_pyinstaller_chk.isChecked() else "0")
        env.insert("SIHYX_ZIP_LEVEL", "1" if self.fast_zip_chk.isChecked() else "4")
        env.insert("SIHYX_REUSE_ASSETS",
                   "1" if self.reuse_assets_chk.isChecked() else "0")

        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(ROOT)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._on_proc_output)
        self.proc.finished.connect(self._on_build_done)
        self.proc.errorOccurred.connect(self._on_proc_error)
        # call + отдельный аргумент: Qt сам закавычит путь с пробелами, а
        # `cmd /s /c "<путь>"` ломается, если в пути есть пробел.
        self.proc.start("cmd", ["/d", "/c", "call", BUILD_BAT])

    def _on_proc_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            message = self.proc.errorString() if self.proc is not None else "unknown error"
            self._queue_log(f"[GUI] Не удалось запустить build.bat: {message}")
            self._flush_log()
            self._on_build_done(-1, QProcess.ExitStatus.CrashExit)

    def _update_eta(self):
        if not self._building:
            return
        elapsed = time.monotonic() - self._build_start_ts
        step = self._current_step or 1
        if self._progress <= 0.5:
            self.eta_lbl.setText(
                f"Прошло {_fmt_seconds(elapsed)} · шаг {step}/9: "
                f"{STEP_NAMES.get(step, '')}…")
            return
        total_est = elapsed / (self._progress / 100.0)
        remaining = max(0.0, total_est - elapsed)
        self.eta_lbl.setText(
            f"Прошло {_fmt_seconds(elapsed)} · осталось ~{_fmt_seconds(remaining)}")

    def _on_stop(self):
        if self.proc is None or self.proc.state() == QProcess.ProcessState.NotRunning:
            return
        self._stopped = True
        self._queue_log("[СТОП] Останавливаю сборку…")
        self._flush_log()
        self.status_lbl.setText("Останавливаю сборку…")
        self._set_taskbar_state(TaskbarProgress.PAUSED)
        # cmd /c + дочерние pyinstaller/powershell — обычный proc.kill() убивает
        # только cmd.exe, а не всё дерево процессов. taskkill /T добивает дерево.
        pid = self.proc.processId()
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True,
            )
        except Exception:  # noqa: BLE001 — taskkill нет/не запустился
            self.proc.kill()

    def _on_build_done(self, exit_code: int, _exit_status):
        if not self._building:
            return
        self._building = False
        self._eta_timer.stop()
        self._flush_pending_output()
        now = time.monotonic()
        if self._current_step is not None:
            self._step_times[self._current_step] = max(0.0, now - self._step_start_ts)
            self._current_step = None
        total_sec = now - self._build_start_ts

        self.build_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        for widget in (self.version_combo, self.silent_chk,
                       self.update_pyinstaller_chk, self.fast_zip_chk,
                       self.reuse_assets_chk):
            widget.setEnabled(True)

        proc, self.proc = self.proc, None
        if proc is not None:
            proc.deleteLater()

        if self._stopped:
            self.status_lbl.setText("Остановлено.")
            self.eta_lbl.setText("")
            self._clear_taskbar()
            self._queue_log("[GUI] Сборка остановлена пользователем.")
            self._flush_log()
            return

        if exit_code == 0:
            self._progress = 100.0
            self.progress_bar.setValue(100)
            self._set_taskbar_value(100)
            self._last_tb_pct = 100
            self.eta_lbl.setText(f"Готово за {_fmt_seconds(total_sec)}")
            self.status_lbl.setText("Готово.")
            self._save_timings(total_sec)
            self._log_summary(total_sec)
            self._populate_versions(self._build_version)
            self._update_version_hint()
            seq = self._build_seq
            QTimer.singleShot(15000, lambda: self._clear_taskbar_if_idle(seq))
            QMessageBox.information(
                self, "SI-HYX",
                f"Сборка завершена за {_fmt_seconds(total_sec)}.\n"
                "Архивы и manifest.json — в dist\\ "
                "(список файлов для релиза — в конце лога).")
        else:
            self.eta_lbl.setText("")
            self.status_lbl.setText(f"Сборка упала (код {exit_code}).")
            self._set_taskbar_state(TaskbarProgress.ERROR)
            self._queue_log(f"[GUI] Сборка завершилась с ошибкой (код {exit_code}).")
            self._flush_log()
            QMessageBox.critical(
                self, "SI-HYX",
                f"Сборка завершилась с ошибкой (код {exit_code}). Смотри лог.")

    def _clear_taskbar_if_idle(self, seq: int) -> None:
        if seq == self._build_seq and not self._building:
            self._clear_taskbar()

    def _log_summary(self, total_sec: float) -> None:
        parts = []
        for n in range(1, 10):
            seconds = self._step_times.get(n)
            if seconds is not None:
                parts.append(f"{n} — {_fmt_seconds(seconds)}")
        self._queue_log(f"[GUI] Готово за {_fmt_seconds(total_sec)}.")
        if parts:
            self._queue_log("[GUI] Шаги: " + ", ".join(parts))
        version = self._build_version
        self._queue_log(
            "[GUI] Файлы релиза: "
            f"dist\\UpdateHYX-v{version}.zip, "
            f"dist\\SI-HYX-v{version}-full.zip, dist\\manifest.json")
        self._flush_log()

    def _open_dist(self):
        try:
            os.makedirs(DIST_DIR, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "SI-HYX", f"Не удалось создать папку dist: {e}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(DIST_DIR)):
            QMessageBox.warning(self, "SI-HYX", f"Не удалось открыть папку:\n{DIST_DIR}")

    def closeEvent(self, event):
        if self._building:
            if QMessageBox.question(
                self, "SI-HYX", "Сборка ещё идёт. Всё равно закрыть окно?"
            ) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._on_stop()
            # Окно закрывается: не показываем диалоги из пришедшего позже
            # finished, но прогресс с панели задач всё равно убираем.
            self._building = False
            self._eta_timer.stop()
        self._clear_taskbar()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    win = BuildWindow()
    win.show()
    sys.exit(app.exec())
