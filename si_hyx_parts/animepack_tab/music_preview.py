"""Preview the very same conversion used by the generator, before creating SIQ."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import threading

from PyQt6.QtCore import QThread, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from chiptune.runtime import install_runtime, run_process
from chiptune.service import ChiptuneService
from config import FFMPEG


class PreviewJob(QThread):
    status = pyqtSignal(str)
    result = pyqtSignal(str, bool)

    def __init__(self, settings, source, start, directory, install=False, parent=None):
        super().__init__(parent)
        self.settings, self.source, self.start_at = settings, source, start
        self.directory, self.install = Path(directory), install
        self.cancel = threading.Event()

    def run(self):
        def run(command, timeout=900):
            return run_process(command, timeout, stopped=self.cancel.is_set)
        try:
            if self.install:
                result = install_runtime(run, self.status.emit, self.cancel.is_set)
            else:
                original = self.directory / "original.wav"
                self.status.emit("Подготовка исходного фрагмента…")
                code, error = run([FFMPEG, "-y", "-v", "error", "-ss", str(self.start_at),
                                   "-i", self.source, "-t", str(self.settings.audio_cut),
                                   "-vn", "-ac", "2", "-ar", "44100", str(original)])
                if code:
                    raise RuntimeError(error)
                service = ChiptuneService(self.settings, run, FFMPEG,
                                          stopped=self.cancel.is_set, log=self.status.emit)
                metadata = service.convert(self.source, self.directory / "chiptune.wav",
                                            self.start_at, self.settings.audio_cut)
                (self.directory / "processing.json").write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                result = (f"Готово: {metadata['note_metrics']['notes']} нот. "
                          "Сравните узнаваемость на слух; уверенность модели её не гарантирует.")
            self.result.emit(result, True)
        except Exception as error:
            self.result.emit(str(error), False)


class MusicPreview(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Chiptune: проверка до сборки пака")
        self.resize(650, 300)
        self.settings, self.source, self.job = settings, "", None
        self.installed_python = ""
        self.storage = tempfile.TemporaryDirectory(prefix="sihyx_chip_preview_")
        self.directory = Path(self.storage.name)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(.7)
        layout = QVBoxLayout(self)
        self.label = QLabel("Выберите исходную песню. Модели и кеш хранятся в ~/.cache/si-hyx-chiptune.")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.choose = QPushButton("Выбрать музыкальный файл…")
        self.choose.clicked.connect(self.pick_file)
        layout.addWidget(self.choose)
        row = QHBoxLayout()
        row.addWidget(QLabel(f"Начало фрагмента, секунд (длина {settings.audio_cut} с):"))
        self.start = QSpinBox()
        self.start.setRange(0, 36000)
        row.addWidget(self.start)
        layout.addLayout(row)
        self.convert = QPushButton("Создать Chiptune")
        self.convert.clicked.connect(lambda: self.launch(False))
        layout.addWidget(self.convert)
        self.install = QPushButton("Установить модели (Python 3.11, CPU, загрузка около 1 ГБ)")
        self.install.clicked.connect(lambda: self.launch(True))
        layout.addWidget(self.install)
        self.stop = QPushButton("Остановить")
        self.stop.clicked.connect(self.cancel)
        layout.addWidget(self.stop)
        self.play_buttons = []
        row = QHBoxLayout()
        for name, label in (("original", "Оригинал"), ("chiptune", "Chiptune")):
            button = QPushButton(f"▶ {label}")
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, key=name: self.play(key))
            row.addWidget(button)
            self.play_buttons.append(button)
        self.save = QPushButton("Сохранить пару…")
        self.save.setEnabled(False)
        self.save.clicked.connect(self.save_pair)
        row.addWidget(self.save)
        layout.addLayout(row)

    def pick_file(self):
        source, _ = QFileDialog.getOpenFileName(self, "Исходная песня", "",
                                              "Аудио (*.mp3 *.wav *.flac *.ogg *.opus *.m4a);;Все файлы (*)")
        if source:
            self.source = source
            self.label.setText(source)

    def launch(self, install):
        if self.job and self.job.isRunning():
            return
        if not install and not self.source:
            self.label.setText("Сначала выберите музыкальный файл.")
            return
        self.player.stop()
        self.player.setSource(QUrl())
        for widget in (self.convert, self.install, self.choose, self.start, self.save, *self.play_buttons):
            widget.setEnabled(False)
        self.job = PreviewJob(self.settings, self.source, self.start.value(),
                              self.directory, install, self)
        self.job.status.connect(self.label.setText)
        self.job.result.connect(self.completed)
        self.job.start()

    def completed(self, message, success):
        if success and self.job.install:
            self.installed_python = message
            self.settings.chiptune_python = message
            message = "Модели установлены. Выберите файл и создайте Chiptune."
        self.label.setText(message)
        for widget in (self.convert, self.install, self.choose, self.start):
            widget.setEnabled(True)
        for widget in (*self.play_buttons, self.save):
            widget.setEnabled(success and not self.job.install)

    def cancel(self):
        self.player.stop()
        if self.job:
            self.job.cancel.set()

    def play(self, name):
        self.player.setSource(QUrl.fromLocalFile(str(self.directory / f"{name}.wav")))
        self.player.play()

    def save_pair(self):
        target = QFileDialog.getExistingDirectory(self, "Папка для новой пары примеров")
        if target:
            destination = Path(tempfile.mkdtemp(prefix="chiptune-", dir=target))
            for name in ("original.wav", "chiptune.wav", "processing.json"):
                shutil.copyfile(self.directory / name, destination / name)
            self.label.setText(f"Пара сохранена: {destination}")

    def reject(self):
        self.cancel()
        if self.job and self.job.isRunning():
            self.label.setText("Останавливаю обработчик; закройте окно после остановки.")
            return
        self.player.setSource(QUrl())
        self.storage.cleanup()
        super().reject()
