# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# leaderboard_tab.py — экспериментальная вкладка «ЛидербордHYX»: просмотр
# выгрузки рекордов из Firebase Realtime Database (osu-/doodlejump-лидерборд,
# JSON-экспорт вида {"scores": {"<сложность>": {"<id>": {name, score, ...}}}}).
# Показывает ранжированный список никнеймов с их рекордами, даёт убрать ник
# (или конкретную запись) из списка и сохранить «почищенный» JSON обратно.
#
# Вкладка по умолчанию ВЫКЛЮЧЕНА (включается в Настройках, как SiQuesterHYX/
# ShikimoriHYX). Сетевых запросов нет — только локальный JSON.
import datetime
import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QCheckBox, QTreeWidget, QTreeWidgetItem, QFileDialog,
    QMessageBox, QMenu, QAbstractItemView, QHeaderView,
)
from msgbox import msgbox_critical, msgbox_warning, msgbox_information, msgbox_question

try:
    from config import get_icon
except Exception:  # pragma: no cover
    def get_icon(name, color="#cdd6f4"):
        from PyQt6.QtGui import QIcon as _QIcon
        return _QIcon()

# Сложности, которые встречаются во всех известных выгрузках. Реальный набор
# берётся из файла — это лишь подсказка для пустого состояния.
_ALL = "Все"


def _fmt_date(ts):
    """Метка времени Firebase (мс) → 'дд.мм.гггг чч:мм'. Пусто, если нет."""
    try:
        ts = int(ts)
        if ts <= 0:
            return ""
        # > 10^12 — миллисекунды, иначе секунды.
        if ts > 10 ** 12:
            ts /= 1000.0
        return datetime.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return ""


class _ScoreItem(QTreeWidgetItem):
    """Строка лидерборда. Числовая сортировка по «#» и «Рекорд» (а не строковая,
    иначе 1000 встаёт раньше 9)."""
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col in (0, 2):  # «#» и «Рекорд» — числа
            return self._num(col) < other._num(col)
        return super().__lt__(other)

    def _num(self, col):
        try:
            return float(self.data(col, Qt.ItemDataRole.UserRole + 1) or 0)
        except Exception:
            return 0.0


class LeaderboardTab(QWidget):
    """Вкладка просмотра/чистки выгрузки рекордов из Firebase RTDB."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        # Полный загруженный JSON (мутируется при удалении ников/записей).
        self._data = {}
        self._path = ""
        self._dirty = False          # есть несохранённые изменения
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Верхняя панель: загрузка файла + путь ───────────────────────────
        top = QHBoxLayout()
        self.btn_load = QPushButton("Загрузить файл")
        self.btn_load.setIcon(get_icon('fa5s.folder-open'))
        self.btn_load.setToolTip("Открыть JSON-выгрузку лидерборда из Firebase")
        self.btn_load.clicked.connect(self._pick_file)
        top.addWidget(self.btn_load)

        self.lbl_path = QLabel("Файл не загружен — выберите JSON или перетащите его сюда.")
        self.lbl_path.setStyleSheet("color:#a6adc8;")
        top.addWidget(self.lbl_path, 1)
        root.addLayout(top)

        # ── Панель фильтров ─────────────────────────────────────────────────
        flt = QHBoxLayout()
        flt.addWidget(QLabel("Сложность:"))
        self.cmb_diff = QComboBox()
        self.cmb_diff.addItem(_ALL)
        self.cmb_diff.currentIndexChanged.connect(self._rebuild)
        flt.addWidget(self.cmb_diff)

        self.chk_best = QCheckBox("Только лучший результат на ник")
        self.chk_best.setChecked(True)
        self.chk_best.setToolTip(
            "Свернуть несколько заездов одного ника до одной строки с лучшим рекордом")
        self.chk_best.toggled.connect(self._rebuild)
        flt.addWidget(self.chk_best)

        flt.addStretch(1)
        flt.addWidget(QLabel("Поиск ника:"))
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("часть никнейма…")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.setFixedWidth(180)
        self.ed_search.textChanged.connect(self._rebuild)
        flt.addWidget(self.ed_search)
        root.addLayout(flt)

        # ── Таблица рекордов ────────────────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["#", "Никнейм", "Рекорд", "Сложность", "Дата"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # В глобальном стиле приложения выделение строк сделано прозрачным
        # (QTreeWidget::item:selected → transparent), из-за чего клик по нику не
        # подсвечивается. Возвращаем заметную подсветку только этому дереву.
        self.tree.setStyleSheet(
            "QTreeWidget::item:selected{background-color:#45475a; color:#cdd6f4;}"
            "QTreeWidget::item:selected:active{background-color:#585b70;}"
            "QTreeWidget::item:hover{background-color:#313244;}")
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.tree, 1)

        # Delete — убрать выделенные строки из списка.
        sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree)
        sc.activated.connect(self._remove_selected)

        # ── Нижняя панель: счётчик + действия ───────────────────────────────
        bot = QHBoxLayout()
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet("color:#a6adc8;")
        bot.addWidget(self.lbl_count)
        bot.addStretch(1)

        self.btn_remove = QPushButton("Убрать из списка")
        self.btn_remove.setIcon(get_icon('fa5s.user-slash'))
        self.btn_remove.setToolTip("Удалить выделенные записи (клавиша Delete)")
        self.btn_remove.clicked.connect(self._remove_selected)
        bot.addWidget(self.btn_remove)

        self.btn_save = QPushButton("Сохранить изменения")
        self.btn_save.setObjectName("b_run")
        self.btn_save.setIcon(get_icon('fa5s.save', '#11111b'))
        self.btn_save.setToolTip("Записать почищенный лидерборд в JSON-файл")
        self.btn_save.clicked.connect(self._save)
        bot.addWidget(self.btn_save)
        root.addLayout(bot)

        self._refresh_enabled()

    # ──────────────────────────────────────────────────────────────────────
    # Загрузка
    # ──────────────────────────────────────────────────────────────────────
    def _pick_file(self):
        start = os.path.dirname(self._path) if self._path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите JSON-выгрузку лидерборда", start,
            "JSON (*.json);;Все файлы (*.*)")
        if path:
            self.load_file(path)

    def load_file(self, path):
        """Загружает и парсит JSON. Терпим к двум формам: с корнем 'scores' и
        без него (когда сам узел scores выгружен в корень файла)."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            msgbox_warning(self, "Не удалось открыть файл",
                                f"Не получилось прочитать JSON:\n{e}")
            return
        if not isinstance(data, dict):
            msgbox_warning(self, "Неверный формат",
                                "Ожидался JSON-объект с лидербордом.")
            return
        # Нормализуем к виду {"scores": {...}, ...}. Если корня 'scores' нет, но
        # значения сами похожи на словари записей — считаем весь файл за scores.
        if "scores" not in data:
            looks_like_scores = all(isinstance(v, dict) for v in data.values()) and data
            data = {"scores": data} if looks_like_scores else {"scores": {}}
        if not isinstance(data.get("scores"), dict):
            data["scores"] = {}

        self._data = data
        self._path = path
        self._dirty = False
        self.lbl_path.setText(path)
        self.lbl_path.setStyleSheet("color:#cdd6f4;")

        # Заполняем список сложностей из данных.
        self.cmb_diff.blockSignals(True)
        self.cmb_diff.clear()
        self.cmb_diff.addItem(_ALL)
        diffs = sorted(self._data["scores"].keys())
        for diff in diffs:
            self.cmb_diff.addItem(diff)
        # По умолчанию показываем ОДНУ сложность (первую из файла), а не «Все» —
        # лидерборды у разных сложностей раздельные. «Все» остаётся как опция.
        self.cmb_diff.setCurrentIndex(1 if diffs else 0)
        self.cmb_diff.blockSignals(False)

        self._rebuild()
        self._log(f"Загружен лидерборд: {os.path.basename(path)}")

    # ──────────────────────────────────────────────────────────────────────
    # Построение таблицы
    # ──────────────────────────────────────────────────────────────────────
    def _iter_records(self, diff_filter):
        """Отдаёт (diff, rec_id, rec) по выбранной сложности (или всем)."""
        scores = self._data.get("scores", {})
        diffs = scores.keys() if diff_filter == _ALL else [diff_filter]
        for diff in diffs:
            block = scores.get(diff)
            if not isinstance(block, dict):
                continue
            for rec_id, rec in block.items():
                if isinstance(rec, dict):
                    yield diff, rec_id, rec

    def _rebuild(self, *args):
        if not self._data:
            self.tree.clear()
            self.lbl_count.setText("")
            self._refresh_enabled()
            return

        diff = self.cmb_diff.currentText() or _ALL
        needle = (self.ed_search.text() or "").strip().lower()
        best_only = self.chk_best.isChecked()

        rows = []  # (name, score, diff, ts, [(diff, rec_id), ...])
        if best_only:
            # Сворачиваем по нику: храним лучший результат + ВСЕ его записи
            # (чтобы при удалении убрать ник целиком из текущей выборки).
            agg = {}
            for d, rid, rec in self._iter_records(diff):
                name = str(rec.get("name", "")).strip() or "—"
                score = self._score(rec)
                key = name.lower()
                cur = agg.get(key)
                if cur is None:
                    agg[key] = [name, score, d, rec.get("ts", 0), [(d, rid)]]
                else:
                    cur[4].append((d, rid))
                    if score > cur[1]:
                        cur[1], cur[2], cur[3] = score, d, rec.get("ts", 0)
            rows = list(agg.values())
        else:
            for d, rid, rec in self._iter_records(diff):
                name = str(rec.get("name", "")).strip() or "—"
                rows.append([name, self._score(rec), d, rec.get("ts", 0), [(d, rid)]])

        if needle:
            rows = [r for r in rows if needle in r[0].lower()]
        rows.sort(key=lambda r: r[1], reverse=True)

        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for i, (name, score, d, ts, refs) in enumerate(rows, 1):
            it = _ScoreItem([
                str(i), name, f"{int(score):,}".replace(",", " "),
                d, _fmt_date(ts),
            ])
            it.setData(0, Qt.ItemDataRole.UserRole + 1, i)
            it.setData(2, Qt.ItemDataRole.UserRole + 1, score)
            # Ссылки на исходные записи (diff, rec_id) — для удаления.
            it.setData(0, Qt.ItemDataRole.UserRole, refs)
            it.setTextAlignment(0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if i == 1:
                it.setForeground(2, QColor("#f9e2af"))
                f = it.font(1); f.setBold(True); it.setFont(1, f)
            self.tree.addTopLevelItem(it)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(2, Qt.SortOrder.DescendingOrder)

        n = len(rows)
        suffix = " (есть несохранённые изменения)" if self._dirty else ""
        self.lbl_count.setText(f"Записей: {n}{suffix}")
        self._refresh_enabled()

    @staticmethod
    def _score(rec):
        for k in ("score", "tok", "play"):
            v = rec.get(k)
            if isinstance(v, (int, float)):
                return float(v)
        return 0.0

    # ──────────────────────────────────────────────────────────────────────
    # Удаление
    # ──────────────────────────────────────────────────────────────────────
    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        sel = len(self.tree.selectedItems())
        if sel > 1:
            act_del = menu.addAction(get_icon('fa5s.user-slash'),
                                     f"Убрать выделенные ({sel})")
        else:
            name = item.text(1)
            act_del = menu.addAction(get_icon('fa5s.user-slash'),
                                     f"Убрать «{name}» из списка")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is act_del:
            self._remove_selected()

    def _remove_selected(self):
        items = self.tree.selectedItems()
        if not items:
            return
        # Собираем все исходные записи под удаление.
        refs = []
        names = []
        for it in items:
            r = it.data(0, Qt.ItemDataRole.UserRole) or []
            refs.extend(r)
            names.append(it.text(1))
        if not refs:
            return

        if len(items) == 1:
            msg = f"Убрать «{names[0]}» из лидерборда?"
        else:
            msg = f"Убрать {len(items)} ник(а/ов) из лидерборда?"
        if self.chk_best.isChecked():
            msg += "\n(удаляются все заезды этих ников в текущей выборке)"
        if msgbox_question(self, "Удаление", msg) != QMessageBox.StandardButton.Yes:
            return

        scores = self._data.get("scores", {})
        removed = 0
        for diff, rec_id in refs:
            block = scores.get(diff)
            if isinstance(block, dict) and rec_id in block:
                del block[rec_id]
                removed += 1
        if removed:
            self._dirty = True
            self._log(f"Убрано записей: {removed}")
            self._rebuild()

    # ──────────────────────────────────────────────────────────────────────
    # Сохранение
    # ──────────────────────────────────────────────────────────────────────
    def _save(self):
        if not self._data:
            return
        base = self._path or "leaderboard.json"
        root, ext = os.path.splitext(base)
        suggest = f"{root}_cleaned{ext or '.json'}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить лидерборд", suggest, "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            msgbox_warning(self, "Не удалось сохранить",
                                f"Ошибка записи файла:\n{e}")
            return
        self._dirty = False
        self._path = path
        self.lbl_path.setText(path)
        self._log(f"Сохранено: {os.path.basename(path)}")
        self._rebuild()

    # ──────────────────────────────────────────────────────────────────────
    # Перетаскивание файла на вкладку
    # ──────────────────────────────────────────────────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith(".json"):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(".json"):
                self.load_file(p)
                e.acceptProposedAction()
                return
        e.ignore()

    # ──────────────────────────────────────────────────────────────────────
    # Прочее
    # ──────────────────────────────────────────────────────────────────────
    def _refresh_enabled(self):
        has = bool(self._data)
        self.cmb_diff.setEnabled(has)
        self.chk_best.setEnabled(has)
        self.ed_search.setEnabled(has)
        self.btn_remove.setEnabled(has and bool(self.tree.topLevelItemCount()))
        self.btn_save.setEnabled(has)

    def _log(self, msg):
        try:
            self.main.log(msg)
        except Exception:
            pass

    # Симметрично ShikimoriHYX/SiQuesterHYX (вызывается при выключении вкладки).
    def get_settings(self) -> dict:
        return {}

    def cleanup(self):
        pass
