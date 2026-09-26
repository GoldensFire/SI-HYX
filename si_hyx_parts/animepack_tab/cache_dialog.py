# -*- coding: utf-8 -*-
"""Просмотр и точечная очистка файлов медиа-кэша аниме-паков.

Разделов было два — «Постеры» и «Медиа», — и понять, что именно лежит перед
тобой, было нельзя: постеры попадались в обоих, а половина файлов звалась
«.bin» и ничем не открывалась (жалоба пользователя). Теперь раздел у каждого
файла свой и говорит, кто его положил, рядом стоит «что это», а «.bin»
открывается — тип берётся у самих байтов.
"""
from __future__ import annotations

from datetime import datetime
import os
import shutil
import subprocess
import sys
import tempfile

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

import media_cache
import poster_cache
from msgbox import msgbox_question, msgbox_warning
from utils import reveal_in_explorer

# Кто положил файл в кладовую: подпись раздела и рассказ по наведению.
POSTER_SECTION = (
    "Обложки",
    "Обложки тайтлов и портреты персонажей, скачанные КАК ЕСТЬ (jpg/png/webp).\n"
    "Общие для генератора и «Апгрейда пака»: обложка тайтла не меняется "
    "годами, и качать её второй раз незачем.\n"
    "Ужатая под настройки пака копия того же постера — уже в разделе «Готовые "
    "картинки»: это разные файлы и разные кладовые.")
SECTIONS = {
    "avif": (
        "Готовые картинки",
        "Картинки, уже ужатые в AVIF ровно под нынешние настройки пака: "
        "постеры в ответах, кадры и коллажи.\n"
        "Отсюда и берутся «постеры в медиа»: исходная обложка лежит в разделе "
        "«Обложки», а здесь — результат её кодирования, чтобы не кодировать "
        "одно и то же по второму разу."),
    "anime-frame": (
        "Кадры и скриншоты",
        "Исходные кадры и скриншоты с Shikimori — то, из чего собираются "
        "вопрос-кадр и коллаж."),
    "amq-audio": (
        "Отрывки песен",
        "Исходные записи опенингов и эндингов, скачанные для вопросов-песен."),
    "cover-audio": (
        "Каверы (звук)",
        "Звук кавера с YouTube. Выпадет тот же кавер в следующем паке — "
        "качать заново не придётся (у YouTube на это есть суточная стенка)."),
}
UNSORTED_SECTION = (
    "Медиа (без раздела)",
    "Файлы, попавшие в кладовую до того, как у неё появились разделы. Каждый "
    "разойдётся по своему разделу сам, как только понадобится снова.")

# «Что это» — по расширению файла.
TYPES = {
    ".jpg": "Картинка JPEG", ".jpeg": "Картинка JPEG",
    ".png": "Картинка PNG", ".webp": "Картинка WebP",
    ".gif": "Картинка GIF", ".avif": "Картинка AVIF",
    ".m4a": "Звук M4A", ".mp3": "Звук MP3", ".ogg": "Звук OGG",
    ".flac": "Звук FLAC", ".opus": "Звук Opus",
    ".mp4": "MP4", ".webm": "WebM", ".pdf": "PDF",
}


def _human_size(size: int) -> str:
    value = float(max(0, size))
    for suffix in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024.0 or suffix == "ГБ":
            return (f"{value:.1f}" if suffix != "Б" else f"{value:.0f}") + f" {suffix}"
        value /= 1024.0
    return f"{value:.1f} ГБ"


def _type_label(path: str) -> str:
    ext = os.path.splitext(str(path or ""))[1].lower()
    known = TYPES.get(ext)
    if known:
        return known
    guess = media_cache.sniff_file(path)
    return TYPES.get(guess, "Неизвестно") if guess != ".bin" else "Неизвестно"


def _openable(path: str) -> str:
    """Путь, который примет система. «.bin» она открыть не умеет, поэтому
    кладём рядом копию с настоящим расширением — тип виден по байтам."""
    ext = os.path.splitext(path)[1].lower()
    if ext and ext != ".bin":
        return path
    guess = media_cache.sniff_file(path)
    if guess == ".bin":
        return path
    folder = os.path.join(tempfile.gettempdir(), "si-hyx-cache")
    os.makedirs(folder, exist_ok=True)
    copy = os.path.join(folder, os.path.basename(path) + guess)
    shutil.copyfile(path, copy)
    return copy


def _open_file(path: str):
    path = _openable(path)
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class CacheDialog(QDialog):
    HEADERS = ("Раздел", "Что это", "Файл", "Размер", "Изменён", "Путь")

    def __init__(self, parent=None, changed=None):
        super().__init__(parent)
        self._changed = changed
        self.setWindowTitle("Файлы кэша аниме-паков")
        self.resize(1000, 600)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(list(self.HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self.open_selected())
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.open_btn = QPushButton("Открыть файл")
        self.open_btn.clicked.connect(self.open_selected)
        self.reveal_btn = QPushButton("Показать в папке")
        self.reveal_btn.clicked.connect(self.reveal_selected)
        self.delete_btn = QPushButton("Удалить выбранные")
        self.delete_btn.clicked.connect(self.delete_selected)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.refresh)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        for button in (self.open_btn, self.reveal_btn, self.delete_btn):
            button.setEnabled(False)
        row.addWidget(self.open_btn)
        row.addWidget(self.reveal_btn)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        row.addWidget(refresh)
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    def _paths(self) -> list[str]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return [str(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) or "")
                for row in rows]

    def _selection_changed(self):
        count = len(self._paths())
        self.open_btn.setEnabled(count == 1)
        self.reveal_btn.setEnabled(count == 1)
        self.delete_btn.setEnabled(count > 0)

    def _rows(self) -> list[tuple[tuple[str, str], dict]]:
        """(раздел, файл) по обеим кладовым — обложки и всё остальное."""
        rows = [(POSTER_SECTION, row) for row in poster_cache.entries()]
        for row in media_cache.entries():
            rows.append((SECTIONS.get(row.get("namespace") or "",
                                      UNSORTED_SECTION), row))
        return rows

    def refresh(self):
        # Файлы «.bin» лежат тут с тех пор, когда скачанное клали без
        # расширения: назовём их по содержимому, тогда они и в проводнике
        # откроются. Поиск записи в кладовой это переживает.
        try:
            media_cache.migrate_names()
        except Exception:  # noqa: BLE001 — окно не повод падать
            pass
        rows = self._rows()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        total = 0
        for index, ((section, tip), row) in enumerate(rows):
            total += row["size"]
            values = (
                section, _type_label(row["path"]), row["name"],
                _human_size(row["size"]),
                datetime.fromtimestamp(row["modified"]).strftime("%d.%m.%Y %H:%M"),
                row["path"],
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(tip if col == 0 else row["path"])
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row["path"])
                self.table.setItem(index, col, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self.summary.setText(
            f"Файлов: {len(rows)} · занято: {_human_size(total)} · "
            "наведите на раздел — он расскажет, кто и зачем положил туда файл."
            if rows else "Кэш пуст.")
        self._selection_changed()

    def open_selected(self):
        paths = self._paths()
        if len(paths) != 1:
            return
        try:
            _open_file(paths[0])
        except Exception as exc:
            msgbox_warning(self, "Файл не открылся", str(exc))

    def reveal_selected(self):
        paths = self._paths()
        if len(paths) == 1:
            reveal_in_explorer(paths[0])

    def delete_selected(self):
        paths = self._paths()
        if not paths:
            return
        reply = msgbox_question(
            self, "Удалить файлы кэша?",
            f"Удалить выбранные файлы ({len(paths)} шт.)? Они будут скачаны "
            "или созданы заново, если снова понадобятся.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = sum(bool(poster_cache.remove(path) or media_cache.remove(path))
                      for path in paths)
        self.refresh()
        if self._changed is not None:
            self._changed()
        self.summary.setText(self.summary.text() + f" · удалено: {removed}")
