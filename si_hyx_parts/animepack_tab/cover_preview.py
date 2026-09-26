# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""«Проверить каверы…»: тот же поиск и та же проверка, что в генераторе.

Оригинал берётся ФАЙЛОМ с диска: в паке эталоном служит запись с CDN AMQ, а до
сборки пака её взять неоткуда — зато у пользователя обычно есть сама песня.
Дальше всё как в генераторе: запросы к YouTube, гейт по заголовку, проверка
звуком и та же рамка схожести, что стоит в настройках.

Находки складываются в общую кладовую под ключом, посчитанным от названия
песни: у пака ключ другой (annSongId), поэтому проверенное здесь генератору не
достаётся — зато повторная проверка той же песни идёт уже даром.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import threading

from PyQt6.QtCore import QThread, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QPushButton, QVBoxLayout)

import cover_match
import cover_meta
from config import FFMPEG, ytdlp_base_cmd
from cover_meta_rules import TYPE_LABELS
from cover_service import CoverService, run_capture, ytdlp_command
from si_hyx_parts.animepack.cover_processing import wanted_cover

AUDIO = "Музыка (*.mp3 *.m4a *.opus *.flac *.wav *.ogg *.webm);;Все файлы (*)"


def preview_key(name: str) -> str:
    """Ключ кладовой для прослушивания: от названия песни, а не от annSongId."""
    digest = hashlib.sha1(str(name or "").strip().lower().encode("utf-8"))
    return f"preview-{digest.hexdigest()[:12]}"


def describe(row) -> str:
    """Строка списка: вид, схожесть, уверенность и сам заголовок."""
    level = cover_match.similarity_percent(row.get("closeness") or 0.0)
    kind = TYPE_LABELS.get(row.get("type"), row.get("type") or "")
    return (f"{kind} · схожесть {level}% · счёт {row.get('norm', 0):.1f} — "
            f"{row.get('title', '')}")


class CoverJob(QThread):
    """Поиск с проверкой или резка выбранного отрезка — в отдельном потоке."""
    status = pyqtSignal(str)
    found = pyqtSignal(list, str)
    ready = pyqtSignal(str, str)

    def __init__(self, settings, source, directory, *, song=None, pick=None,
                 parent=None):
        super().__init__(parent)
        self.settings, self.source = settings, str(source)
        self.directory = Path(directory)
        self.song, self.pick = song, pick
        self.cancel = threading.Event()

    def service(self):
        def run(command, timeout=180):
            return run_capture(command, timeout, stopped=self.cancel.is_set)
        return CoverService(run, FFMPEG, ytdlp_command(ytdlp_base_cmd()),
                            stopped=self.cancel.is_set, log=self.status.emit,
                            workers=4)

    def run(self):
        service = self.service()
        try:
            if self.pick is not None:
                self.status.emit("Качаю и режу выбранное исполнение…")
                length = max(1.0, min(float(self.settings.audio_cut),
                                      float(self.pick.get("length") or 0.0)))
                target = self.directory / "cover.opus"
                service.cut(self.pick["id"], self.pick["at"], length, target,
                            self.directory,
                            ["-c:a", "libopus", "-b:a", "128k"])
                self.ready.emit(str(target), "")
                return
            self.status.emit("Считаю признак оригинала…")
            reference = service.reference(
                self.song["song_id"],
                lambda: Path(self.source).read_bytes(), self.directory)
            self.status.emit("Ищу и слушаю исполнения…")
            rows = service.ensure(
                self.song, reference, self.directory,
                want=max(1, int(self.settings.cover_pool)),
                seconds=max(1.0, float(self.settings.audio_cut)),
                keep=wanted_cover(self.settings))
            self.found.emit(rows, "")
        except Exception as error:  # noqa: BLE001 — окно, а не генерация
            (self.ready if self.pick is not None else self.found).emit(
                [] if self.pick is None else "", str(error))
        finally:
            service.close()


class CoverPreview(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Каверы: проверка до сборки пака")
        self.resize(760, 420)
        self.settings, self.source, self.job = settings, "", None
        self.rows = []
        self.storage = tempfile.TemporaryDirectory(prefix="sihyx_cover_preview_")
        self.directory = Path(self.storage.name)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(.7)

        layout = QVBoxLayout(self)
        self.label = QLabel("Выберите файл с ОРИГИНАЛОМ песни и назовите её "
                            "так, как её знают: по этим словам и ищутся "
                            "исполнения.")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.choose = QPushButton("Выбрать оригинал…")
        self.choose.clicked.connect(self.pick_file)
        layout.addWidget(self.choose)
        self.song = QLineEdit()
        self.song.setPlaceholderText("Название песни (например, unravel)")
        self.anime = QLineEdit()
        self.anime.setPlaceholderText("Аниме (например, Tokyo Ghoul)")
        self.artist = QLineEdit()
        self.artist.setPlaceholderText("Исполнитель оригинала — необязательно")
        for field in (self.song, self.anime, self.artist):
            layout.addWidget(field)
        self.search = QPushButton("Найти и проверить")
        self.search.clicked.connect(self.launch)
        layout.addWidget(self.search)
        self.list = QListWidget()
        layout.addWidget(self.list)
        row = QHBoxLayout()
        self.listen = QPushButton("Прослушать отрезок")
        self.listen.clicked.connect(self.play)
        row.addWidget(self.listen)
        self.stop = QPushButton("Остановить")
        self.stop.clicked.connect(self.halt)
        row.addWidget(self.stop)
        layout.addLayout(row)

    # ── ход дела ─────────────────────────────────────────────────────────
    def pick_file(self):
        name, _filter = QFileDialog.getOpenFileName(
            self, "Оригинал песни", "", AUDIO)
        if name:
            self.source = name
            self.label.setText(f"Оригинал: {Path(name).name}")

    def song_ref(self):
        name = self.song.text().strip()
        return cover_meta.song_ref(
            {"annSongId": preview_key(name), "songName": name,
             "songArtist": self.artist.text().strip(),
             "animeENName": self.anime.text().strip(), "songType": ""}, [])

    def busy(self, running):
        for widget in (self.choose, self.search, self.listen):
            widget.setEnabled(not running)

    def launch(self):
        if not self.source or not self.song.text().strip():
            self.label.setText("Нужны файл с оригиналом и название песни.")
            return
        self.list.clear()
        self.rows = []
        self.start(CoverJob(self.settings, self.source, self.directory,
                            song=self.song_ref(), parent=self))

    def play(self):
        number = self.list.currentRow()
        if not (0 <= number < len(self.rows)):
            self.label.setText("Выберите исполнение в списке.")
            return
        self.player.stop()
        self.start(CoverJob(self.settings, self.source, self.directory,
                            pick=self.rows[number], parent=self))

    def start(self, job):
        self.job = job
        job.status.connect(self.label.setText)
        job.found.connect(self.show_rows)
        job.ready.connect(self.play_file)
        job.finished.connect(lambda: self.busy(False))
        self.busy(True)
        job.start()

    def show_rows(self, rows, error):
        if error:
            self.label.setText(error)
            return
        self.rows = list(rows)
        for row in self.rows:
            self.list.addItem(describe(row))
        self.label.setText(
            f"Подтверждено исполнений: {len(self.rows)}. Отвергнутые звуком "
            "здесь не показываются — это записи ДРУГОЙ композиции."
            if self.rows else
            "Подходящих исполнений не нашлось. Проверьте название песни или "
            "расширьте рамку схожести.")

    def play_file(self, path, error):
        if error or not path:
            self.label.setText(error or "Отрезок не получился.")
            return
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def halt(self):
        self.player.stop()
        if self.job is not None:
            self.job.cancel.set()

    def closeEvent(self, event):
        self.halt()
        if self.job is not None:
            self.job.wait(5000)
        self.player.setSource(QUrl())
        super().closeEvent(event)
