# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Разметка AMV: очередь видео для каталога планов (montage_tool index).

Каждый файл — отдельный процесс `python -I montage_tool.py index <файл>
--progress`: этапы приходят строками JSON в stderr, итог — JSON в stdout.
Приоритет процесса и его дочерних (ffmpeg, обработчик DirectML) задаётся
из интерфейса и меняется на ходу: index сам ставит себе «ниже обычного»,
поэтому выбранный класс переставляется таймером по всему дереву.

Низкий приоритет — ещё и без iGPU (index --no-gpu): видеокарта общая с
экраном, класс процесса её не касается, а команда модели DirectML держит
её по 0,6 с без вытеснения — дёргается всё, от курсора до видео. Выбран
на ходу — обработчик DirectML снимается, и index досчитывает на CPU.

Персонажи (кластеры по всей библиотеке) пересчитываются не после каждого
файла, а один раз в конце очереди — `characters --recluster`."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout)

from config import get_icon
from msgbox import msgbox_warning

# Как VIDEO_EXT в montage_tool library: тот модуль тянет numpy и модели.
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".ts", ".m2ts", ".wmv", ".flv")
TOOL = Path(__file__).resolve().parents[2] / "montage_tool.py"

# Ключ, подпись, класс приоритета Windows, доля ядер, видеокарта.
PRIORITIES = (
    ("low", "Низкий — не мешает работать", 0x00000040, 0.5, False),
    ("below", "Ниже обычного", 0x00004000, 1.0, True),
    ("normal", "Обычный — быстрее", 0x00000020, 1.0, True),
)
_DML_WORKER = "dml_worker.py"
DEFAULT_PRIORITY = "low"

# Этап index → (подпись, процент начала этапа без подписей планов). Декод
# идёт по кадрам до 45 %. Текст, детекторы и теги идут параллельно (на iGPU
# детекторы, затем теги), процент берётся наибольший.
STAGES = {
    "file": ("Ожидание очереди моделей", 0),
    "download": ("Загрузка модели", 0),
    "install": ("Установка обработчика", 0),
    "fingerprint": ("Отпечаток звука", 0),
    "decode": ("Декод и поиск резов", 0),
    "shots": ("Резы планов", 45),
    "ocr": ("Текст в кадре", 48),
    "detect": ("Лица и фигуры", 50),
    "tags": ("Теги кадров", 58),
    "characters": ("Персонажи", 62),
    "speech": ("Речь", 95),
    "oped": ("Опенинги и эндинги", 97),
    "gemini": ("Описания Gemini", 98),
    "unpack": ("Распаковка llama.cpp", 98),
    "look": ("Подписи планов", 98),
    "captions": ("Подписи планов", 98),
}
DECODE_SHARE = 45
# С подписями планов разметка файла — первые 60 %, подписи — остальное
# (замер Арслан: разметка ~7 мин, подписи ~400 планов по ~1 с).
CAPTIONS_FROM = 60

# Состояния строки очереди.
QUEUED, RUNNING, DONE, UNCHANGED, FAILED, CANCELLED = (
    "queued", "running", "done", "unchanged", "failed", "cancelled")
_STATE_TEXT = {QUEUED: "В очереди", DONE: "Готово", UNCHANGED: "Уже размечено",
               FAILED: "Ошибка", CANCELLED: "Отменено"}
_ROLE_PATH = Qt.ItemDataRole.UserRole
_ROLE_STATE = Qt.ItemDataRole.UserRole + 1


def tool_command():
    """Python и montage_tool.py для разметки или None (сборка без исходников)."""
    if getattr(sys, "frozen", False) or not TOOL.is_file():
        return None
    return sys.executable, ["-I", str(TOOL)]


def list_videos(paths):
    """Видеофайлы из списка файлов и папок (папки — со вложенными)."""
    out = []
    for p in paths:
        p = os.path.abspath(str(p))
        if os.path.isfile(p):
            if p.lower().endswith(VIDEO_EXT):
                out.append(p)
        elif os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                out.extend(os.path.join(root, n) for n in sorted(names)
                           if n.lower().endswith(VIDEO_EXT))
    return out


def stage_percent(name, event, captions=False):
    """Процент файла по строке этапа index; captions — в очереди есть
    подписи планов, и разметке остаются первые CAPTIONS_FROM %."""
    if name in ("captions", "look", "unpack") and captions:
        if name == "captions" and event.get("total"):
            return CAPTIONS_FROM + (99 - CAPTIONS_FROM) * min(1.0, (event.get("shot") or 0)
                                                                / event["total"])
        return CAPTIONS_FROM
    if name == "decode":
        frames = event.get("frames") or 0
        frame = event.get("frame") or 0
        pct = DECODE_SHARE * min(1.0, frame / frames) if frames else 0
    elif name == "detect" and event.get("model") in ("face", "head", "person"):
        pct = STAGES["detect"][1] + 2 * ("face", "head", "person").index(event["model"])
    elif name == "tags" and event.get("helper"):
        pct = 85
    else:
        pct = STAGES.get(name, ("", None))[1]
    if pct is None or not captions:
        return pct
    return pct * CAPTIONS_FROM / 100


def priority_spec(key):
    return next((p for p in PRIORITIES if p[0] == key), PRIORITIES[0])


def apply_priority(pid, key):
    """Класс приоритета и ядра процесса index и всех его дочерних; без
    видеокарты — ещё и снять обработчики DirectML (index уйдёт на CPU)."""
    try:
        import psutil
    except ImportError:
        return
    spec = priority_spec(key)
    try:
        root = psutil.Process(pid)
        procs = [root] + root.children(recursive=True)
    except psutil.Error:
        return
    cpus = list(range(psutil.cpu_count() or 1))
    cpus = cpus[:max(1, int(len(cpus) * spec[3]))]
    for proc in procs:
        try:
            if not spec[4] and proc is not root and any(
                    os.path.basename(a) == _DML_WORKER for a in proc.cmdline()):
                kill_tree(proc.pid)
                continue
            if os.name == "nt":
                proc.nice(spec[2])
            if proc.cpu_affinity() != cpus:
                proc.cpu_affinity(cpus)
        except (psutil.Error, OSError, ValueError):
            pass


def kill_tree(pid):
    try:
        import psutil
        root = psutil.Process(pid)
        procs = root.children(recursive=True) + [root]
    except Exception:
        return
    for proc in procs:
        try:
            proc.kill()
        except Exception:
            pass


class _DropList(QTreeWidget):
    """Очередь, в которую перетаскивают видео и папки."""
    dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setRootIsDecorated(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setHeaderLabels(["Файл", "Состояние", "%"])
        head = self.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.setColumnWidth(1, 230)

    def _urls(self, event):
        md = event.mimeData()
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []

    def dragEnterEvent(self, event):
        if self._urls(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._urls(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self._urls(event)
        if paths:
            event.acceptProposedAction()
            self.dropped.emit(paths)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.topLevelItemCount():
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor("#7f849c"))
        painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                         "Перетащите сюда видео или папки с сериями")
        painter.end()


class AmvMarkupDialog(QDialog):
    """Очередь разметки AMV. Окно можно закрыть — разметка идёт дальше."""
    progressChanged = pyqtSignal(str)

    def __init__(self, tab):
        # Без родителя: окно с владельцем Windows держит над главным окном
        # всегда, а разметку идёт часами — её убирают на задний план и
        # сворачивают. Своя кнопка на панели задач, кнопки «свернуть/развернуть».
        super().__init__(None)
        self.tab = tab
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.WindowMinimizeButtonHint
                            | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle("Разметка AMV")
        # Значок кнопки на панели задач — как у главного окна (до первого показа).
        main_mod = sys.modules.get("main")
        set_identity = getattr(main_mod, "_set_taskbar_identity", None)
        if set_identity is not None:
            try:
                set_identity(int(self.winId()))
            except Exception:  # noqa: BLE001 — без свойств значок просто общий
                pass
        self.resize(760, 480)
        self._proc = None
        self._item = None
        self._cancel_file = ""
        self._stopping = False
        self._stderr_buf = b""
        self._stdout = b""
        self._last_lines = []
        self._started = 0.0             # начало текущего файла
        self._queue_started = 0.0       # начало запуска очереди
        self._queue_ended = 0.0
        self._percent = 0.0
        self._stage_text = ""
        self._totals = {"files": 0, "shots": 0}
        self._recluster = False         # в этом запуске размечен файл — персонажей пересчитать
        self._characters_note = ""
        self._run_captions = False

        layout = QVBoxLayout(self)
        hint = QLabel("Разметка находит планы, резы, персонажей, теги и текст в кадре — "
                      "по ней AMV собирается из нужных кусков. Окно можно закрыть, "
                      "разметка продолжится; уже размеченные файлы пропускаются.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.queue = _DropList(self)
        self.queue.dropped.connect(self.add_paths)
        layout.addWidget(self.queue, 1)

        row = QHBoxLayout()
        self.btn_add_files = QPushButton(get_icon("fa5s.file-video"), "Видео…")
        self.btn_add_files.clicked.connect(self._pick_files)
        self.btn_add_dir = QPushButton(get_icon("fa5s.folder-open"), "Папка…")
        self.btn_add_dir.clicked.connect(self._pick_dir)
        self.btn_add_current = QPushButton(get_icon("fa5s.film"), "Открытое видео")
        self.btn_add_current.setToolTip("Добавить видео, открытое в «Монтаже»")
        self.btn_add_current.clicked.connect(self._add_current)
        self.btn_remove = QPushButton(get_icon("fa5s.times"), "Убрать")
        self.btn_remove.setToolTip("Убрать выбранные файлы из очереди")
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear_done = QPushButton(get_icon("fa5s.broom"), "Убрать готовые")
        self.btn_clear_done.clicked.connect(self._clear_finished)
        for b in (self.btn_add_files, self.btn_add_dir, self.btn_add_current):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear_done)
        layout.addLayout(row)

        prefs = dict(getattr(tab, "_amv_markup_prefs", None) or {})
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Приоритет:"))
        self.cmb_priority = QComboBox()
        for key, text, _cls, _share, _gpu in PRIORITIES:
            self.cmb_priority.addItem(text, key)
        self.cmb_priority.setToolTip(
            "Низкий — разметка берёт половину ядер, уступает процессор всему остальному "
            "и не трогает видеокарту: можно смотреть и монтировать, пока она идёт.\n"
            "Ниже обычного — модели считаются и на видеокарте: вдвое быстрее, "
            "но экран может подёргиваться.\n"
            "Обычный — все ядра наравне с программой, быстрее, но компьютер может подтормаживать.\n"
            "Меняется и во время разметки.")
        idx = self.cmb_priority.findData(prefs.get("priority", DEFAULT_PRIORITY))
        self.cmb_priority.setCurrentIndex(max(0, idx))
        self.cmb_priority.currentIndexChanged.connect(self._on_priority_changed)
        opts.addWidget(self.cmb_priority)
        opts.addSpacing(12)
        self.chk_speech = QCheckBox("Реплики (Whisper)")
        self.chk_speech.setToolTip("Распознать речь серий — для поиска реплик и op voice. Дольше.")
        self.chk_speech.setChecked(bool(prefs.get("speech", False)))
        self.chk_captions = QCheckBox("Подписи планов")
        self.chk_captions.setToolTip("Описать каждый план локальной моделью (llama.cpp) — "
                                     "поиск планов словами. Опенинг и эндинг не подписываются.")
        self.chk_captions.setChecked(bool(prefs.get("captions", False)))
        for chk in (self.chk_speech, self.chk_captions):
            chk.toggled.connect(self._save_prefs)
            opts.addWidget(chk)
        opts.addStretch(1)
        layout.addLayout(opts)

        self.status = QLabel("Очередь пуста")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_start = QPushButton(get_icon("fa5s.play"), "Начать")
        self.btn_start.clicked.connect(self._start_or_stop)
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.hide)
        bottom.addWidget(self.btn_start)
        bottom.addWidget(self.btn_close)
        layout.addLayout(bottom)

        self._priority_timer = QTimer(self)
        self._priority_timer.setInterval(2000)
        self._priority_timer.timeout.connect(self._apply_priority)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._refresh_status)
        self._refresh_buttons()

    # ── Очередь ───────────────────────────────────────────────────────────
    def running(self):
        return self._proc is not None

    def _items(self):
        return [self.queue.topLevelItem(i) for i in range(self.queue.topLevelItemCount())]

    def add_paths(self, paths):
        known = {os.path.normcase(it.data(0, _ROLE_PATH)) for it in self._items()}
        added = 0
        for path in list_videos(paths):
            if os.path.normcase(path) in known:
                continue
            known.add(os.path.normcase(path))
            it = QTreeWidgetItem([os.path.basename(path), _STATE_TEXT[QUEUED], ""])
            it.setToolTip(0, path)
            it.setData(0, _ROLE_PATH, path)
            it.setData(0, _ROLE_STATE, QUEUED)
            self.queue.addTopLevelItem(it)
            added += 1
        if paths and not added and not self.running():
            self.status.setText("Новых видео нет: файлы уже в очереди или это не видео")
        self._refresh_buttons()
        self._refresh_status()
        return added

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Видео для разметки", "",
            "Видео (" + " ".join("*" + e for e in VIDEO_EXT) + ");;Все файлы (*)")
        if files:
            self.add_paths(files)

    def _pick_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка с сериями")
        if folder:
            self.add_paths([folder])

    def _current_video(self):
        tab = self.tab
        src = getattr(tab, "actual_source_file", None) or getattr(tab, "filepath", None)
        if not src or getattr(tab, "is_still_image", False):
            return ""
        return str(src) if os.path.isfile(str(src)) else ""

    def _add_current(self):
        src = self._current_video()
        if src:
            self.add_paths([src])

    def _remove_selected(self):
        for it in self.queue.selectedItems():
            if it is not self._item:
                self.queue.takeTopLevelItem(self.queue.indexOfTopLevelItem(it))
        self._refresh_buttons()
        self._refresh_status()

    def _clear_finished(self):
        for it in self._items():
            if it.data(0, _ROLE_STATE) in (DONE, UNCHANGED):
                self.queue.takeTopLevelItem(self.queue.indexOfTopLevelItem(it))
        self._refresh_buttons()
        self._refresh_status()

    def _set_state(self, it, state, text=None, percent=None):
        it.setData(0, _ROLE_STATE, state)
        it.setText(1, text or _STATE_TEXT.get(state, ""))
        if percent is not None:
            it.setText(2, f"{percent:.0f}")
        color = {FAILED: "#f38ba8", DONE: "#a6e3a1", UNCHANGED: "#a6e3a1"}.get(state)
        for col in range(3):
            it.setForeground(col, QColor(color) if color else self.queue.palette().text())

    # ── Запуск ────────────────────────────────────────────────────────────
    def _start_or_stop(self):
        if self.running():
            self.stop()
            return
        if tool_command() is None:
            msgbox_warning(self, "Разметка AMV",
                           "Разметка работает при запуске программы из исходников "
                           "(нужен montage_tool.py рядом с main.py).")
            return
        for it in self._items():
            if it.data(0, _ROLE_STATE) in (FAILED, CANCELLED):
                self._set_state(it, QUEUED, percent=None)
                it.setText(2, "")
        self._totals = {"files": 0, "shots": 0}
        self._stopping = False
        self._recluster = False
        self._characters_note = ""
        self._queue_started = time.monotonic()
        self._next()

    def _next(self):
        it = next((x for x in self._items() if x.data(0, _ROLE_STATE) == QUEUED), None)
        if it is None and self._recluster and not self._stopping:
            self._recluster = False
            self._start(None, ["characters", "--recluster"])
            return
        if it is None or self._stopping:
            self._finish_queue()
            return
        args = ["index", it.data(0, _ROLE_PATH), "--no-recluster"]
        if self.chk_speech.isChecked():
            args.append("--speech")
        self._run_captions = self.chk_captions.isChecked()
        if self._run_captions:
            args.append("--captions")
        if not priority_spec(self.cmb_priority.currentData())[4]:
            args.append("--no-gpu")
        self._start(it, args)

    def _start(self, it, command):
        """Процесс montage_tool: разметка файла it или (it=None) пересчёт персонажей."""
        exe, base = tool_command()
        fd, self._cancel_file = tempfile.mkstemp(prefix="si-hyx-amv-", suffix=".cancel")
        os.close(fd)
        os.remove(self._cancel_file)
        args = base + command + ["--progress", "--cancel-file", self._cancel_file]
        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardError.connect(self._read_stderr)
        proc.readyReadStandardOutput.connect(self._read_stdout)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc, self._item = proc, it
        self._stderr_buf, self._stdout, self._last_lines = b"", b"", []
        self._started = time.monotonic()
        self._percent = 0.0
        self._stage_text = "Запуск"
        if it is not None:
            self._set_state(it, RUNNING, "Запуск…", 0)
            self.queue.scrollToItem(it)
        proc.start(exe, args)
        self._priority_timer.start()
        self._clock.start()
        QTimer.singleShot(300, self._apply_priority)
        self._refresh_buttons()
        self._refresh_status()

    def stop(self):
        """Отмена: файл отмены, а через 10 с — снять процесс вместе с дочерними."""
        self._stopping = True
        if self._proc is None:
            return
        try:
            with open(self._cancel_file, "w", encoding="utf-8") as f:
                f.write("cancel")
        except OSError:
            pass
        self._stage_text = "Отмена…"
        self._refresh_status()
        proc = self._proc
        QTimer.singleShot(10000, lambda: self._kill_if_alive(proc))

    def _kill_if_alive(self, proc):
        if proc is self._proc and proc.state() != QProcess.ProcessState.NotRunning:
            kill_tree(int(proc.processId()))

    def shutdown(self):
        """Выход из программы: процесс разметки не должен пережить окно."""
        self._stopping = True
        # Окно без родителя: открытое, оно держало бы приложение после
        # закрытия главного окна (последнее видимое окно).
        self.hide()
        proc = self._proc
        if proc is None:
            return
        try:
            proc.finished.disconnect()
        except TypeError:
            pass
        kill_tree(int(proc.processId()))
        proc.waitForFinished(3000)
        self._cleanup_cancel_file()
        self._proc = None

    def _apply_priority(self):
        if self._proc is not None and self._proc.processId():
            apply_priority(int(self._proc.processId()), self.cmb_priority.currentData())

    def _on_priority_changed(self):
        self._apply_priority()
        self._save_prefs()

    def _save_prefs(self):
        self.tab._amv_markup_prefs = {"priority": self.cmb_priority.currentData(),
                                      "speech": self.chk_speech.isChecked(),
                                      "captions": self.chk_captions.isChecked()}
        try:
            self.tab.save_settings()
        except Exception:
            pass

    # ── Вывод процесса ────────────────────────────────────────────────────
    def _read_stdout(self):
        if self._proc is not None:
            self._stdout += bytes(self._proc.readAllStandardOutput())

    def _read_stderr(self):
        if self._proc is None:
            return
        self._stderr_buf += bytes(self._proc.readAllStandardError())
        *lines, self._stderr_buf = self._stderr_buf.split(b"\n")
        for raw in lines:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            event = None
            if line.startswith("{"):
                try:
                    event = json.loads(line)
                except ValueError:
                    event = None
            if not isinstance(event, dict) or event.get("event") != "stage":
                self._last_lines = (self._last_lines + [line])[-8:]
                continue
            self._on_stage(event)

    def _on_stage(self, event):
        name = str(event.get("stage", ""))
        text = STAGES.get(name, (name, None))[0]
        if name == "decode" and event.get("frames"):
            text += f" — кадр {event.get('frame') or 0} из {event['frames']}"
        elif name == "captions" and event.get("total"):
            text += f" — {event.get('shot') or 0} из {event['total']}"
        elif name == "download" and event.get("file"):
            text += f" — {event['file']}"
        pct = stage_percent(name, event, self._run_captions)
        if pct is not None:
            self._percent = max(self._percent, float(pct))
        self._stage_text = text
        self._refresh_status()

    def _on_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self._proc is not None:
            self._last_lines.append("Не удалось запустить Python для montage_tool")
            self._on_finished(-1, QProcess.ExitStatus.CrashExit)

    def _on_finished(self, code, _status):
        proc, it = self._proc, self._item
        if proc is None:
            return
        # Время файла целиком: запуск, ожидание и загрузка моделей, разметка.
        took = _fmt_time(time.monotonic() - self._started)
        self._read_stdout()
        self._priority_timer.stop()
        self._proc = self._item = None
        self._cleanup_cancel_file()
        result = None
        for raw in reversed(self._stdout.splitlines()):
            try:
                result = json.loads(raw.decode("utf-8", "replace"))
                break
            except ValueError:
                continue
        proc.deleteLater()
        if it is None:                       # пересчёт персонажей в конце очереди
            if not (isinstance(result, dict) and result.get("ok")) and not self._stopping:
                err = (result or {}).get("error") if isinstance(result, dict) else None
                self._characters_note = "персонажи не пересчитаны: " + (
                    (err or {}).get("message") or f"код выхода {code}").splitlines()[0][:120]
            self._next()
            return
        if isinstance(result, dict) and result.get("ok"):
            files = result.get("files") or [{}]
            status = files[0].get("status")
            if status in ("unchanged", "moved"):
                self._set_state(it, UNCHANGED, f"Уже размечено — {took}", 100)
            else:
                shots = int(files[0].get("shots") or 0)
                self._set_state(it, DONE, f"Готово за {took}: {shots} планов", 100)
                self._totals["files"] += 1
                self._totals["shots"] += shots
                self._recluster = True
        elif self._stopping or (isinstance(result, dict)
                                and (result.get("error") or {}).get("code") == "cancelled"):
            self._set_state(it, CANCELLED, f"Отменено через {took}")
            it.setText(2, "")
        else:
            err = (result or {}).get("error") if isinstance(result, dict) else None
            message = (err or {}).get("message") or "\n".join(self._last_lines[-3:]) \
                or f"код выхода {code}"
            self._set_state(it, FAILED, f"Ошибка через {took}: " + message.splitlines()[0][:120])
            it.setToolTip(1, message)
        self._next()

    def _cleanup_cancel_file(self):
        if self._cancel_file:
            try:
                os.remove(self._cancel_file)
            except OSError:
                pass
            self._cancel_file = ""

    def _finish_queue(self):
        self._queue_ended = time.monotonic()
        self._clock.stop()
        self._priority_timer.stop()
        self._stopping = False
        self._refresh_buttons()
        self._refresh_status()

    # ── Отображение ───────────────────────────────────────────────────────
    def _counts(self):
        states = [it.data(0, _ROLE_STATE) for it in self._items()]
        return {s: states.count(s) for s in (QUEUED, RUNNING, DONE, UNCHANGED, FAILED, CANCELLED)}

    def overall(self):
        """Доля 0…1 и подпись для «Монтажа»: файлы этого запуска."""
        c = self._counts()
        total = c[QUEUED] + c[RUNNING] + c[DONE] + c[UNCHANGED]
        if not total:
            return 0.0, ""
        done = c[DONE] + c[UNCHANGED] + (self._percent / 100 if c[RUNNING] else 0)
        return done / total, f"{c[DONE] + c[UNCHANGED] + c[RUNNING]} из {total}"

    def _refresh_status(self):
        c = self._counts()
        frac, files = self.overall()
        self.bar.setValue(int(frac * 1000))
        if self.running():
            elapsed = _fmt_time(time.monotonic() - self._started)
            total = _fmt_time(time.monotonic() - self._queue_started)
            if self._item is not None:
                self._set_state(self._item, RUNNING, f"{self._stage_text} — {elapsed}",
                                self._percent)
                text = (f"Файл {files}: {self._item.text(0)} — {self._stage_text}, "
                        f"{self._percent:.0f} % ({elapsed}, всего {total})")
            else:
                text = f"Персонажи по всей библиотеке — {self._stage_text} ({elapsed}, всего {total})"
            short = f"{frac * 100:.0f} %"
        else:
            parts = []
            if c[QUEUED]:
                parts.append(f"в очереди {c[QUEUED]}")
            if self._totals["files"]:
                parts.append(f"размечено {self._totals['files']} (планов {self._totals['shots']})")
            if c[UNCHANGED]:
                parts.append(f"уже размечено {c[UNCHANGED]}")
            if c[FAILED]:
                parts.append(f"ошибок {c[FAILED]}")
            if c[CANCELLED]:
                parts.append(f"отменено {c[CANCELLED]}")
            if self._characters_note:
                parts.append(self._characters_note)
            if parts and self._queue_started:
                parts.append(f"за {_fmt_time(self._queue_ended - self._queue_started)}")
            text = ("Разметка: " + ", ".join(parts)) if parts else "Очередь пуста"
            short = ""
        self.status.setText(text)
        self.progressChanged.emit(short)

    def _refresh_buttons(self):
        run = self.running()
        has_queue = any(it.data(0, _ROLE_STATE) in (QUEUED, FAILED, CANCELLED)
                        for it in self._items())
        self.btn_start.setText("Остановить" if run else "Начать")
        self.btn_start.setIcon(get_icon("fa5s.stop" if run else "fa5s.play"))
        self.btn_start.setEnabled(run or has_queue)
        self.btn_add_current.setEnabled(bool(self._current_video()))

    def showEvent(self, event):
        self._refresh_buttons()
        super().showEvent(event)

    def closeEvent(self, event):
        # Закрытие только прячет окно: очередь и процесс живут дальше.
        event.ignore()
        self.hide()

    def reject(self):
        self.hide()


def _fmt_time(seconds):
    s = int(seconds or 0)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"
