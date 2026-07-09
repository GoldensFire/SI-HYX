# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# coop_tab.py — экспериментальная вкладка «Collab»: совместная работа над
# одним .siq-паком SIGame. Показывает список тем, текстовых вопросов и ответов
# (медиа — только маркером «[фото]/[видео]/[аудио]», сам файл не передаётся),
# синхронизируясь в near-realtime с напарником через общую «комнату» на
# Cloudflare Worker. Видно, кто какую тему/вопрос уже сделал — и где вы
# пересеклись (дубли), чтобы не делать одно и то же дважды.
#
# Вкладка по умолчанию ВЫКЛЮЧЕНА (включается в Настройках). Из зависимостей —
# только стандартная библиотека (urllib) + уже парсящий .siq SiqPackage.

import datetime
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QFileSystemWatcher, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QCheckBox, QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox,
    QHeaderView, QAbstractItemView,
)
from msgbox import msgbox_critical, msgbox_warning, msgbox_information, msgbox_question

try:
    from config import get_icon, APP_VERSION, COOP_SYNC_URL
except Exception:  # pragma: no cover — на случай частичной сборки
    APP_VERSION = "?"
    COOP_SYNC_URL = ""

    def get_icon(name, color="#cdd6f4"):
        from PyQt6.QtGui import QIcon as _QIcon
        return _QIcon()

# ── Цвета (в тон общему catppuccin-стилю приложения) ──────────────────────────
_C_MINE   = "#a6e3a1"   # зелёный — есть только у меня
_C_OTHER  = "#89b4fa"   # синий — есть только у напарника
_C_DUP    = "#f9e2af"   # жёлтый — есть у обоих (пересечение / возможный дубль)
_C_WARN   = "#f38ba8"   # красный — точный дубль (совпал ответ)
_C_MUTED  = "#a6adc8"
_C_TEXT   = "#cdd6f4"

# Палитра для >2 авторов (мой цвет всегда зелёный, остальным раздаём по кругу).
_AUTHOR_PALETTE = ["#89b4fa", "#fab387", "#cba6f7", "#94e2d5", "#f5c2e7", "#f9e2af"]

_MEDIA_KINDS = ("image", "audio", "video")
_MEDIA_LABEL = {"image": "фото", "audio": "аудио", "video": "видео"}


# ══════════════════════════════════════════════════════════════════════════════
# Извлечение текстового «обзора» пака (slepok) из распарсенного SiqPackage
# ══════════════════════════════════════════════════════════════════════════════
def _q_summary(q: dict) -> dict:
    """Свести один вопрос к: цена, текст вопроса, ответ, маркеры медиа.

    Сам медиаконтент НЕ трогаем — фиксируем лишь наличие файла (фото/аудио/видео)
    в вопросе (`qm`) и в ответе (`am`)."""
    price = int(q.get("price", 0) or 0)
    qtext_parts, qmedia, amedia = [], set(), set()
    for it in q.get("items", []):
        param = it.get("param", "") or ""
        typ = it.get("type", "text") or "text"
        is_ref = bool(it.get("is_ref", False))
        placement = it.get("placement", "") or ""
        text = (it.get("text") or "").strip()
        is_answer = (param == "answer")
        if typ in _MEDIA_KINDS and is_ref:
            (amedia if is_answer else qmedia).add(typ)
        elif typ == "text" and not is_ref and placement != "replic":
            # Контент вопроса: param 'question'/'' (старый формат) или фон.
            if param in ("question", "", "background") and text:
                qtext_parts.append(text)
    answers = [a.strip() for a in q.get("answers", []) if a and a.strip()]
    return {
        "price": price,
        "q": " ".join(qtext_parts).strip(),
        "a": " / ".join(answers),
        "qm": sorted(qmedia),
        "am": sorted(amedia),
    }


def _q_is_filled(q: dict) -> bool:
    """Вопрос заполнен, если в нём есть хоть какое-то содержимое — текст вопроса,
    ответ или медиа (в вопросе/ответе). Пустой ценовой «слот» (только цена, без
    содержимого) заполненным не считается."""
    return bool(q.get("q") or q.get("a") or q.get("qm") or q.get("am"))


def pack_to_outline(pkg) -> dict:
    """SiqPackage → лёгкий текстовый обзор (раунды → темы → вопросы)."""
    rounds = []
    for rnd in getattr(pkg, "rounds", []) or []:
        themes = []
        for th in rnd.get("themes", []) or []:
            qs = [_q_summary(q) for q in th.get("questions", []) or []]
            themes.append({"name": (th.get("name", "") or "").strip(), "questions": qs})
        rounds.append({"name": (rnd.get("name", "") or "").strip(), "themes": themes})
    return {"name": getattr(pkg, "name", "") or "", "rounds": rounds}


def normalize_url(url: str) -> str:
    """Привести адрес сервера к валидному виду: добавить https:// если схемы нет
    (иначе urllib падает с 'unknown url type') и убрать хвостовой слэш."""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u.lstrip("/")
    return u.rstrip("/")


def outline_from_siq(path: str) -> dict:
    """Открыть .siq, распарсить и вернуть обзор. Хэндл зип-файла сразу
    закрываем — чтобы не мешать SIQuester сохранять пак."""
    from siquester.siq_package import SiqPackage
    pkg = SiqPackage(path)
    try:
        return pack_to_outline(pkg)
    finally:
        try:
            pkg.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Сетевой слой: публикация своего обзора и опрос комнаты (фоновый поток)
# ══════════════════════════════════════════════════════════════════════════════
class _CoopSync(QObject):
    """Держит фоновый поток: публикует мой обзор в комнату и опрашивает её,
    отдавая в GUI объединённое состояние {author: {outline, updated}}."""

    remoteUpdated = pyqtSignal(dict)       # {author: {"outline":..., "updated":int}}
    statusChanged = pyqtSignal(str, str)   # (текст, цвет)

    POLL_INTERVAL = 6.0

    def __init__(self):
        super().__init__()
        self._url = ""
        self._room = ""
        self._author = ""
        self._thread = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._pending = None            # обзор, ожидающий публикации
        self._last_published = None     # чтобы не слать одно и то же
        # Опрашиваем комнату только когда вкладка на экране — иначе десятки
        # пользователей молотили бы сервер в фоне (важно при раздаче незнакомым).
        # Публикация СВОИХ правок продолжается и в фоне (она редкая — только при
        # сохранении пака), чтобы напарники видели твою работу сразу.
        self._active = True

    # ── управление ──────────────────────────────────────────────────────────
    def start(self, url: str, room: str, author: str):
        self.stop()
        self._url = normalize_url(url)
        self._room = room or ""
        self._author = author or "Аноним"
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._last_published = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        t = self._thread
        if t is not None:
            self._stop.set()
            self._wake.set()
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    def publish(self, outline: dict):
        """Поставить обзор в очередь на отправку (немедленно будит поток)."""
        with self._lock:
            self._pending = outline
        self._wake.set()

    def set_active(self, active: bool):
        """Вкладка на экране / скрыта. В скрытом состоянии не опрашиваем сервер."""
        self._active = bool(active)
        if active:
            self._wake.set()   # вернулись на вкладку — опросить немедленно

    # ── рабочий цикл ─────────────────────────────────────────────────────────
    def _run(self):
        self.statusChanged.emit("Подключение…", _C_MUTED)
        while not self._stop.is_set():
            with self._lock:
                pending = self._pending
                self._pending = None
            if pending is not None and pending != self._last_published:
                if self._do_publish(pending):
                    self._last_published = pending
            if self._active:
                self._do_poll()
            self._wake.wait(self.POLL_INTERVAL)
            self._wake.clear()

    def _endpoint(self) -> str:
        return f"{self._url}/coop/{urllib.parse.quote(self._room, safe='')}"

    def _do_publish(self, outline: dict) -> bool:
        try:
            payload = json.dumps(
                {"author": self._author, "outline": outline,
                 "updated": int(time.time())},
                ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self._endpoint(), data=payload, method="POST",
                headers={"Content-Type": "application/json",
                         "User-Agent": f"SI-HYX/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except Exception as e:
            self.statusChanged.emit(f"Не удалось опубликовать: {e}", _C_WARN)
            return False

    def _do_poll(self):
        try:
            req = urllib.request.Request(
                self._endpoint(), method="GET",
                headers={"User-Agent": f"SI-HYX/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            authors = data.get("authors", {}) if isinstance(data, dict) else {}
            if not isinstance(authors, dict):
                authors = {}
            self.remoteUpdated.emit(authors)
            now = datetime.datetime.now().strftime("%H:%M:%S")
            self.statusChanged.emit(f"В сети • обновлено {now}", _C_MINE)
        except Exception as e:
            self.statusChanged.emit(f"Нет связи с комнатой: {e}", _C_WARN)


# ══════════════════════════════════════════════════════════════════════════════
# Вкладка
# ══════════════════════════════════════════════════════════════════════════════
class CoopTab(QWidget):
    """Совместная работа над .siq: обзор тем/вопросов/ответов с подсветкой,
    кто что сделал, и пересечений между соавторами."""

    def __init__(self, main, settings: dict | None = None):
        super().__init__()
        self.main = main
        s = settings or {}

        self._my_path = ""                 # путь к моему .siq
        self._my_outline = None            # обзор моего пака
        self._remote = {}                  # {author: {outline, updated}} с сервера

        self.sync = _CoopSync()
        self.sync.remoteUpdated.connect(self._on_remote)
        self.sync.statusChanged.connect(self._set_status)

        # Слежение за моим файлом: SIGame сохранил пак → перечитываем и публикуем.
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._reload_timer = QTimer(self)   # дебаунс: SIGame пишет файл рывками
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(700)
        self._reload_timer.timeout.connect(self._reload_my_pack)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Строка 1: мой файл ───────────────────────────────────────────────
        row_file = QHBoxLayout()
        self.btn_file = QPushButton("Мой .siq…")
        self.btn_file.setIcon(get_icon('fa5s.folder-open'))
        self.btn_file.setToolTip("Выбрать свою рабочую копию пака (.siq)")
        self.btn_file.clicked.connect(self._pick_file)
        row_file.addWidget(self.btn_file)

        self.lbl_file = QLabel("Файл не выбран — укажите свою рабочую копию пака.")
        self.lbl_file.setStyleSheet(f"color:{_C_MUTED};")
        row_file.addWidget(self.lbl_file, 1)
        root.addLayout(row_file)
        # Публикация полностью автоматическая: при подключении и при каждом
        # сохранении пака (за файлом следит QFileSystemWatcher). Кнопки нет.

        # ── Строка 2: подключение к комнате ──────────────────────────────────
        row_conn = QHBoxLayout()
        # Сервер у каждой группы соавторов свой (см. coop_worker.js / DEPLOY_COOP.md).
        # Адрес вводится один раз и хранится ЛОКАЛЬНО в настройках этого ПК — в
        # раздаваемую сборку он не попадает (COOP_SYNC_URL в config.py пуст).
        row_conn.addWidget(QLabel("Сервер:"))
        self.ed_url = QLineEdit(s.get("url", "") or COOP_SYNC_URL)
        self.ed_url.setPlaceholderText("https://…workers.dev — свой на всю группу")
        self.ed_url.setToolTip(
            "Адрес вашего сервера синхронизации (один на всех соавторов пака).\n"
            "Как поднять за пару минут — см. DEPLOY_COOP.md.")
        row_conn.addWidget(self.ed_url, 2)

        row_conn.addWidget(QLabel("Комната:"))
        self.ed_room = QLineEdit(s.get("room", "") or "")
        self.ed_room.setPlaceholderText("код пака, напр. solevaya-volevaya")
        self.ed_room.setToolTip("Общий код комнаты — одинаковый у всех соавторов пака")
        self.ed_room.setFixedWidth(200)
        row_conn.addWidget(self.ed_room)

        row_conn.addWidget(QLabel("Имя:"))
        self.ed_author = QLineEdit(s.get("author", "") or "")
        self.ed_author.setPlaceholderText("ваш ник")
        self.ed_author.setFixedWidth(140)
        row_conn.addWidget(self.ed_author)

        self.btn_conn = QPushButton("Подключиться")
        self.btn_conn.setObjectName("b_run")
        self.btn_conn.setIcon(get_icon('fa5s.plug', '#11111b'))
        self.btn_conn.clicked.connect(self._toggle_connect)
        row_conn.addWidget(self.btn_conn)
        root.addLayout(row_conn)

        # ── Строка 3: фильтры + статус ───────────────────────────────────────
        row_flt = QHBoxLayout()
        self.chk_dup_only = QCheckBox("Только пересечения")
        self.chk_dup_only.setToolTip(
            "Показать лишь темы/вопросы, которые есть больше чем у одного соавтора "
            "(потенциальные дубли)")
        self.chk_dup_only.toggled.connect(self._rebuild)
        row_flt.addWidget(self.chk_dup_only)

        row_flt.addStretch(1)
        row_flt.addWidget(QLabel("Поиск:"))
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("тема / вопрос / ответ…")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.setFixedWidth(220)
        self.ed_search.textChanged.connect(self._rebuild)
        row_flt.addWidget(self.ed_search)
        root.addLayout(row_flt)

        self.lbl_status = QLabel("Не подключено.")
        self.lbl_status.setStyleSheet(f"color:{_C_MUTED};")
        root.addWidget(self.lbl_status)

        # ── Легенда ──────────────────────────────────────────────────────────
        legend = QLabel(
            f"<span style='color:{_C_MINE};'>■</span> только у меня &nbsp;&nbsp;"
            f"<span style='color:{_C_OTHER};'>■</span> только у других &nbsp;&nbsp;"
            f"<span style='color:{_C_DUP};'>■</span> тема у нескольких &nbsp;&nbsp;"
            f"<span style='color:{_C_WARN};'>■</span> совпал ответ (дубль)")
        legend.setStyleSheet("font-size:11px;")
        root.addWidget(legend)

        # ── Дерево ───────────────────────────────────────────────────────────
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        # Порядок колонок: Автор · Тема/Вопрос · Сложный ответ · Цена · Ответ.
        self.tree.setHeaderLabels(
            ["Автор", "Тема / Вопрос", "Сложный ответ", "Цена", "Ответ"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Общий стиль приложения делает выделение прозрачным — возвращаем подсветку.
        self.tree.setStyleSheet(
            "QTreeWidget::item:selected{background-color:#45475a; color:#cdd6f4;}"
            "QTreeWidget::item:hover{background-color:#313244;}")
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # Автор
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)          # Тема/Вопрос
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Сложный ответ
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Цена
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)          # Ответ
        root.addWidget(self.tree, 1)

        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet(f"color:{_C_MUTED};")
        root.addWidget(self.lbl_count)

        # Автозагрузка последнего файла (если сохранён и ещё существует).
        last = s.get("file", "") or ""
        if last and os.path.exists(last):
            self._set_my_file(last, publish=False)

        self._refresh_enabled()

        # Автоподключение: если раньше уже подключались (сервер/комната/имя
        # сохранены с прошлого раза) — подключаемся сразу, без ручного клика.
        auto_url = (s.get("url", "") or COOP_SYNC_URL).strip()
        auto_room = (s.get("room", "") or "").strip()
        auto_author = (s.get("author", "") or "").strip()
        if auto_url and auto_room and auto_author:
            self._connect(auto_url, auto_room, auto_author)

    # ──────────────────────────────────────────────────────────────────────
    # Мой файл
    # ──────────────────────────────────────────────────────────────────────
    def _pick_file(self):
        start = os.path.dirname(self._my_path) if self._my_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите свою рабочую копию пака", start,
            "Пакеты SIGame (*.siq);;Все файлы (*.*)")
        if path:
            self._set_my_file(path, publish=True)

    def _set_my_file(self, path: str, publish: bool):
        # Снимаем слежение со старого файла, ставим на новый.
        try:
            if self._watcher.files():
                self._watcher.removePaths(self._watcher.files())
        except Exception:
            pass
        self._my_path = path
        self.lbl_file.setText(path)
        self.lbl_file.setStyleSheet(f"color:{_C_TEXT};")
        try:
            self._watcher.addPath(path)
        except Exception:
            pass
        self._reload_my_pack(publish=publish)

    def _on_file_changed(self, _path):
        # SIGame при сохранении часто заменяет файл (remove+create) — путь может
        # слететь со слежения. Перевешиваем и перечитываем с дебаунсом.
        self._reload_timer.start()

    def _reload_my_pack(self, publish: bool = True):
        if not self._my_path:
            return
        if not os.path.exists(self._my_path):
            self._set_status("Мой файл недоступен (перемещён или занят).", _C_WARN)
            return
        try:
            self._my_outline = outline_from_siq(self._my_path)
        except Exception as e:
            self._set_status(f"Не удалось прочитать .siq: {e}", _C_WARN)
            return
        # Файл мог быть пересоздан — гарантируем, что слежение активно.
        try:
            if self._my_path not in self._watcher.files():
                self._watcher.addPath(self._my_path)
        except Exception:
            pass
        if publish and self.sync.running:
            self.sync.publish(self._my_outline)
        self._rebuild()

    # ──────────────────────────────────────────────────────────────────────
    # Подключение к комнате
    # ──────────────────────────────────────────────────────────────────────
    def _toggle_connect(self):
        if self.sync.running:
            self.sync.stop()
            self.btn_conn.setText("Подключиться")
            self.btn_conn.setIcon(get_icon('fa5s.plug', '#11111b'))
            self._set_status("Отключено.", _C_MUTED)
            self._refresh_enabled()
            return
        url = normalize_url(self.ed_url.text())
        room = self.ed_room.text().strip()
        author = self.ed_author.text().strip()
        if not url or not room or not author:
            msgbox_information(
                self, "Заполните поля",
                "Укажите адрес сервера, код комнаты и своё имя.")
            return
        self._connect(url, room, author)

    def _connect(self, url: str, room: str, author: str):
        """Общая точка подключения — используется и кнопкой, и автоподключением
        при запуске (если раньше уже было успешно заполнено все три поля)."""
        url = normalize_url(url)
        # Показать пользователю уже исправленный адрес (с https://, без слэша).
        self.ed_url.setText(url)
        self.sync.start(url, room, author)
        # Сразу опубликуем текущий обзор (если файл уже загружен).
        if self._my_outline is not None:
            self.sync.publish(self._my_outline)
        self.btn_conn.setText("Отключиться")
        self.btn_conn.setIcon(get_icon('fa5s.plug', '#11111b'))
        self._refresh_enabled()

    def _on_remote(self, authors: dict):
        self._remote = authors or {}
        self._rebuild()

    def _my_author(self) -> str:
        return (self.ed_author.text().strip() or "Я")

    # ──────────────────────────────────────────────────────────────────────
    # Слияние и отрисовка
    # ──────────────────────────────────────────────────────────────────────
    def _collect_by_author(self) -> dict:
        """Собрать {author: outline} из моего локального обзора + удалённых.
        Мой локальный обзор приоритетнее эха с сервера."""
        combined = {}
        for author, blob in (self._remote or {}).items():
            if isinstance(blob, dict) and isinstance(blob.get("outline"), dict):
                combined[author] = blob["outline"]
        if self._my_outline is not None:
            combined[self._my_author()] = self._my_outline
        return combined

    def _author_color(self, author: str, my_author: str, order: list) -> str:
        if author == my_author:
            return _C_MINE
        try:
            i = [a for a in order if a != my_author].index(author)
        except ValueError:
            i = 0
        return _AUTHOR_PALETTE[i % len(_AUTHOR_PALETTE)]

    def _rebuild(self, *_):
        self.tree.clear()
        combined = self._collect_by_author()
        if not combined:
            self.lbl_count.setText("")
            self._refresh_enabled()
            return

        my_author = self._my_author()
        authors_order = sorted(combined.keys(), key=lambda a: (a != my_author, a.lower()))

        needle = (self.ed_search.text() or "").strip().lower()
        dup_only = self.chk_dup_only.isChecked()

        # theme_key -> {"name", "qs":[(author, q, round)], "authors":set(объявивших)}
        themes: dict[str, dict] = {}
        # нормализованный ответ -> множество авторов (для метки «совпал ответ»)
        answer_authors: dict[str, set] = {}
        # Прогресс по паку: сколько вопросов реально заполнено из общего числа
        # (по всем соавторам — считаем «сколько работы уже сделано»).
        n_total_all = n_filled_all = 0
        for author in authors_order:
            outline = combined[author]
            for rnd in outline.get("rounds", []):
                rname = rnd.get("name", "")
                for th in rnd.get("themes", []):
                    raw_name = (th.get("name", "") or "").strip()
                    unnamed = not raw_name
                    tname = raw_name or "(без названия)"
                    key = tname.lower()
                    bucket = themes.setdefault(
                        key, {"name": tname, "qs": [], "authors": set(),
                              "unnamed": unnamed})
                    # Автор «объявил» тему — даже если вопросов в ней пока нет.
                    bucket["authors"].add(author)
                    for q in th.get("questions", []):
                        bucket["qs"].append((author, q, rname))
                        n_total_all += 1
                        if _q_is_filled(q):
                            n_filled_all += 1
                        ans = (q.get("a", "") or "").strip().lower()
                        if ans:
                            answer_authors.setdefault(ans, set()).add(author)

        # Порядок тем: сперва непустые (по алфавиту), затем пустые названные,
        # и в самом конце — «(без названия)» (независимо от наличия вопросов).
        ordered_keys = sorted(
            themes.keys(),
            key=lambda k: (themes[k]["unnamed"], not bool(themes[k]["qs"]),
                           themes[k]["name"].lower()))

        n_themes = n_q = n_dup = 0
        for key in ordered_keys:
            info = themes[key]
            qs = info["qs"]
            theme_authors = info["authors"]
            shared_theme = len(theme_authors) > 1
            has_q = bool(qs)
            authors_str = ", ".join(
                sorted(theme_authors, key=lambda a: (a != my_author, a.lower())))

            # Поиск/фильтр применяем на уровне вопросов; тему показываем, если
            # под фильтр попал хоть один её вопрос.
            visible_rows = []
            for author, q, rname in qs:
                ans = (q.get("a", "") or "").strip().lower()
                answer_dup = len(answer_authors.get(ans, set())) > 1 if ans else False
                if dup_only and not (shared_theme or answer_dup):
                    continue
                if needle:
                    hay = " ".join([
                        info["name"], q.get("q", ""), q.get("a", ""), author,
                    ]).lower()
                    if needle not in hay:
                        continue
                visible_rows.append((author, q, rname, answer_dup))

            # Пустую тему (без вопросов) тоже показываем — но её саму фильтруем
            # по названию и по «только пересечения».
            if has_q:
                if not visible_rows:
                    continue
            else:
                if dup_only and not shared_theme:
                    continue
                if needle and needle not in info["name"].lower():
                    continue

            n_themes += 1
            # Колонки: 0=Автор 1=Тема 2=Сложный ответ 3=Цена 4=Ответ
            th_item = QTreeWidgetItem([authors_str, info["name"], "", "", ""])
            f = th_item.font(1); f.setBold(True); th_item.setFont(1, f)
            th_color = _C_DUP if shared_theme else (
                _C_MINE if theme_authors == {my_author} else _C_OTHER)
            th_item.setForeground(0, QColor(th_color))
            th_item.setForeground(1, QColor(th_color))
            note = ""
            if shared_theme:
                note = "  ⚠ у нескольких"
            elif not has_q:
                note = "  · пусто"
            if note:
                th_item.setText(1, info["name"] + note)
            self.tree.addTopLevelItem(th_item)

            # Вопросы сортируем по цене, затем по автору.
            visible_rows.sort(key=lambda r: (r[1].get("price", 0),
                                             r[0] != my_author, r[0].lower()))
            for author, q, rname, answer_dup in visible_rows:
                n_q += 1
                qm, am = q.get("qm", []), q.get("am", [])
                # Показываем ВСЁ, что есть в вопросе: и текст, и маркеры медиа
                # (если в теме одновременно фото + текст — видно и то, и другое).
                qtext_bits = []
                if q.get("q"):
                    qtext_bits.append(q["q"])
                if qm:
                    qtext_bits.append(
                        "[" + ", ".join(_MEDIA_LABEL.get(k, k).capitalize() for k in qm) + "]")
                qtext = " ".join(qtext_bits) or "—"
                # «Сложный ответ» — медиа именно в ответе (без «В:»/«О:» — колонка
                # уже про ответ; наличие медиа в вопросе видно по тексту выше).
                complex_ans = ", ".join(_MEDIA_LABEL.get(k, k) for k in am)
                # Колонки: 0=Автор 1=Вопрос 2=Сложный ответ 3=Цена 4=Ответ
                child = QTreeWidgetItem([
                    author, qtext, complex_ans, str(q.get("price", 0)), q.get("a", "")])
                child.setForeground(0, QColor(self._author_color(
                    author, my_author, authors_order)))
                child.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if answer_dup:
                    n_dup += 1
                    child.setForeground(4, QColor(_C_WARN))
                    child.setText(4, (q.get("a", "") or "") + "  ⚠ дубль")
                th_item.addChild(child)
            th_item.setExpanded(True)

        self.tree.expandAll()
        parts = [f"Тем: {n_themes}", f"вопросов: {n_q}"]
        if n_total_all:
            pct = round(n_filled_all / n_total_all * 100)
            parts.append(f"заполнено: {n_filled_all}/{n_total_all} ({pct}%)")
        if n_dup:
            parts.append(f"совпавших ответов: {n_dup}")
        parts.append(f"соавторов: {len(authors_order)}")
        self.lbl_count.setText(" • ".join(parts))
        self._refresh_enabled()

    # ──────────────────────────────────────────────────────────────────────
    # Прочее
    # ──────────────────────────────────────────────────────────────────────
    def _set_status(self, text: str, color: str = _C_MUTED):
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color:{color};")

    def _refresh_enabled(self):
        # Поля НЕ блокируем даже при подключении — иначе кажется, что интерфейс
        # завис. Чтобы сменить сервер/комнату: «Отключиться» → правка → снова
        # «Подключиться». Правки применяются при следующем подключении.
        pass

    # Опрос комнаты активен только пока вкладка на экране — экономит сервер.
    def showEvent(self, e):
        super().showEvent(e)
        try:
            self.sync.set_active(True)
        except Exception:
            pass

    def hideEvent(self, e):
        super().hideEvent(e)
        try:
            self.sync.set_active(False)
        except Exception:
            pass

    def _log(self, msg):
        try:
            self.main.log(msg)
        except Exception:
            pass

    # Симметрично прочим доп-вкладкам — вызывается из main при сохранении настроек.
    def get_settings(self) -> dict:
        return {
            "url": self.ed_url.text().strip(),
            "room": self.ed_room.text().strip(),
            "author": self.ed_author.text().strip(),
            "file": self._my_path,
        }

    def cleanup(self):
        try:
            self.sync.stop()
        except Exception:
            pass
