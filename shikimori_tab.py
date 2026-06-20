# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# shikimori_tab.py — экспериментальная вкладка «ShikimoriHYX»: поиск аниме/манги
# через Shikimori API с фильтрами по оценке/типу/статусу/году/эпизодам/жанру и
# экспортом результата в JSON/CSV. Сетевые запросы идут в фоне (QThreadPool +
# QRunnable), GUI обновляется только через сигналы/слоты — интерфейс не виснет.
#
# Раскладка: СЛЕВА — список найденных тайтлов с обложками; СПРАВА — панель
# настроек (фильтры, исключение паков SiQuesterHYX, экспорт). Обложки грузятся
# асинхронно и кешируются. Нижние прогрессбар/консоль главного окна на этой
# вкладке скрыты (см. _sync_console_visibility в main.py).
#
# Слой API/фильтрации вынесен в shikimori_api.py (без Qt). Здесь — только GUI и
# оркестровка фоновых задач. Вкладка по умолчанию ВЫКЛЮЧЕНА (включается в
# Настройках, как SiQuesterHYX).
import csv
import json
import os
import re
import webbrowser

from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QScrollArea, QGroupBox,
    QDialog, QCheckBox, QDialogButtonBox, QFrame,
)

try:
    from config import get_icon, APP_NAME, APP_VERSION
except Exception:  # pragma: no cover
    APP_NAME, APP_VERSION = "SI-HYX", "0.0"

    def get_icon(name, color="#cdd6f4"):  # минимальная заглушка
        from PyQt6.QtGui import QIcon as _QIcon
        return _QIcon()

# Слой API/фильтрации. Если requests недоступен — вкладка покажет заглушку.
_IMPORT_ERROR = ""
try:
    from shikimori_api import (
        ShikimoriApiClient, AnimeFilter, Anime, ShikimoriError, find_anime,
        ORDERS, DEFAULT_BASE_URL, CONTENT_ANIME, CONTENT_MANGA,
        kinds_for, statuses_for, kind_label, status_label, views_from_card,
    )
    _HAS_API = True
except Exception as _e:  # pragma: no cover
    _HAS_API = False
    _IMPORT_ERROR = str(_e)


# Палитра (Catppuccin Mocha) — локальная копия, чтобы не тянуть QtMultimedia из
# edit_tab. Совпадает с темой остального приложения.
C = {
    "bg": "#1e1e2e", "surface": "#181825", "surface2": "#24273a",
    "surface3": "#313244", "border": "#45475a", "accent": "#89b4fa",
    "accent2": "#b4befe", "text": "#cdd6f4", "text2": "#a6adc8",
    "text3": "#6c7086", "green": "#a6e3a1", "yellow": "#f9e2af", "red": "#f38ba8",
}

# Локальная (не серверная) сортировка по «просмотрам» — completed+watching+dropped
# из карточки каждого тайтла. По умолчанию выбрана именно она (просьба пользователя).
ORDER_VIEWS = "views"

ORDER_LABELS = {
    ORDER_VIEWS: "По просмотрам",
    "ranked": "По рейтингу", "popularity": "По популярности", "name": "По имени",
    "aired_on": "По дате выхода", "episodes": "По эпизодам", "kind": "По типу",
    "id": "По id", "random": "Случайно",
}

# Размер обложки в списке (постер 7:10).
_THUMB_W, _THUMB_H = 56, 80

# Сортировка по просмотрам тянет по карточке на тайтл — при широком поиске их
# могут быть тысячи. Ограничиваем дозагрузку верхушкой выдачи (она и так идёт в
# серверном порядке релевантности); остальное остаётся в найденном порядке.
_VIEWS_SORT_MAX = 200


def _user_agent() -> str:
    return f"{APP_NAME}/{APP_VERSION} (+https://github.com)"


def _client_factory() -> "ShikimoriApiClient":
    """Создаёт клиент. OAuth-токен (если задан) берём из переменной окружения
    SHIKIMORI_TOKEN — безопасно, без хранения в коде/настройках."""
    token = os.environ.get("SHIKIMORI_TOKEN") or None
    return ShikimoriApiClient(base_url=DEFAULT_BASE_URL,
                              user_agent=_user_agent(), token=token)


def _norm_title(s: str) -> str:
    """Нормализация названия для сравнения с ответами паков: нижний регистр,
    схлопнутые пробелы, без хвостовой пунктуации/скобок-сезонов по краям."""
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" .!?–—-:;\"'«»()[]")
    return s


# Хвостовой «сезонный» маркер: отдельный токен в конце названия — число (1–2
# цифры), римская цифра, либо слово «сезон/season/часть/part/tv/тв/cour» с/без
# числа, либо «финальный сезон». ОБЯЗАТЕЛЬНО с разделителем перед собой ([\s:.\-]+),
# чтобы не отрезать буквы у обычных названий («matrix» → не «matri», «86» цел,
# «mob psycho 100» цел — 3 цифры не матчатся). Нужно, чтобы пак с «Ванпанчмен»
# скрывал из выдачи и «Ванпанчмен 2/3», и наоборот (все сезоны одного тайтла).
_SEASON_TAIL_RX = re.compile(
    r"[\s:.\-–—]+(?:"
    r"(?:the\s+)?(?:final\s+)?(?:season|сезон[а-я]*|часть|части|part|cour|кор|tv|тв)"
    r"\s*-?\s*\d{0,2}"
    r"|\d{1,2}(?:\s*-?\s*(?:nd|rd|th|st|й|ый|ой|ая|я)?\s*"
    r"(?:season|сезон[а-я]*|часть|part|cour))?"
    r"|i{1,3}|iv|vi{0,3}|ix|xi{0,2}|x"
    r")$",
    re.IGNORECASE,
)


def _base_title(s: str) -> str:
    """«Базовое» название без хвостовых сезонных маркеров (для сопоставления
    разных сезонов одного тайтла). Применяет _SEASON_TAIL_RX многократно:
    «ванпанчмен 3» → «ванпанчмен», «attack on titan final season» → «attack on
    titan». Пустой результат не отдаём (возвращаем последнюю непустую форму)."""
    s = _norm_title(s)
    prev = None
    while s and s != prev:
        prev = s
        stripped = _SEASON_TAIL_RX.sub("", s).strip(" :.-–—")
        if not stripped:
            break
        s = stripped
    return s


# ─── Фоновые задачи ──────────────────────────────────────────────────────────
class _SearchSignals(QObject):
    finished = pyqtSignal(list)      # list[Anime] (полный результат)
    batch = pyqtSignal(list)         # list[Anime] (новые тайтлы страницы)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # страница, собрано подходящих


class _SearchTask(QRunnable):
    """Фоновый поиск аниме/манги (в пуле потоков). Результат/ошибка — сигналами.
    Поиск идёт «до конца или до Стоп»; результаты приходят потоково (batch)."""

    def __init__(self, criteria: "AnimeFilter"):
        super().__init__()
        self.setAutoDelete(False)  # держим объект живым через ссылку в виджете
        self.criteria = criteria
        self.signals = _SearchSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        client = None
        try:
            client = _client_factory()
            res = find_anime(
                client, self.criteria,
                progress=lambda p, c: self.signals.progress.emit(p, c),
                on_batch=lambda items: self.signals.batch.emit(items),
                should_stop=lambda: self._stop)
            if not self._stop:
                self.signals.finished.emit(res)
        except ShikimoriError as e:
            if not self._stop:
                self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 — любая неожиданная ошибка в GUI
            if not self._stop:
                self.signals.failed.emit(f"Непредвиденная ошибка: {e}")
        finally:
            if client is not None:
                client.close()


class _GenresSignals(QObject):
    finished = pyqtSignal(str, list)   # content_type, genres
    failed = pyqtSignal(str)


class _GenresTask(QRunnable):
    """Фоновая загрузка списка жанров для выпадающего фильтра."""

    def __init__(self, content_type: str):
        super().__init__()
        self.setAutoDelete(False)
        self.content_type = content_type
        self.signals = _GenresSignals()

    def run(self):
        client = None
        try:
            client = _client_factory()
            self.signals.finished.emit(self.content_type,
                                       client.genres(self.content_type))
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(str(e))
        finally:
            if client is not None:
                client.close()


class _ThumbSignals(QObject):
    done = pyqtSignal(int, bytes)   # anime_id, image bytes


class _ThumbTask(QRunnable):
    """Фоновая загрузка одной обложки (постера) по URL."""

    def __init__(self, anime_id: int, url: str):
        super().__init__()
        self.anime_id = anime_id
        self.url = url
        self.signals = _ThumbSignals()

    def run(self):
        try:
            from config import http_get
            # Shikimori отдаёт картинки только с осмысленным User-Agent (без него
            # — 403, постеры не грузятся). Реферер с того же домена для надёжности.
            headers = {"User-Agent": _user_agent(),
                       "Referer": DEFAULT_BASE_URL + "/"}
            with http_get(self.url, headers=headers, timeout=15) as r:
                data = r.read()
            if data:
                self.signals.done.emit(self.anime_id, data)
        except Exception:
            pass


class _ViewsSignals(QObject):
    item = pyqtSignal(int, int)        # anime_id, просмотры (-1 при ошибке)
    progress = pyqtSignal(int, int)    # обработано, всего
    finished = pyqtSignal()


class _ViewsTask(QRunnable):
    """Дозагрузка «просмотров» для сортировки по ним. Тянет карточки тайтлов
    ПОСЛЕДОВАТЕЛЬНО одним клиентом — мягче к лимитам Shikimori, чем веер
    параллельных запросов (списочный ответ /api/animes просмотров не содержит)."""

    def __init__(self, ids):
        super().__init__()
        self.setAutoDelete(False)
        self.ids = list(ids)
        self.signals = _ViewsSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        client = None
        try:
            client = _client_factory()
            total = len(self.ids)
            for i, aid in enumerate(self.ids, 1):
                if self._stop:
                    break
                views = -1
                try:
                    views = views_from_card(client.get_anime(aid))
                except Exception:
                    views = -1
                self.signals.item.emit(aid, views)
                self.signals.progress.emit(i, total)
        finally:
            if client is not None:
                client.close()
            self.signals.finished.emit()


# ─── Вкладка ─────────────────────────────────────────────────────────────────
class ShikimoriTab(QWidget):
    """Экспериментальная вкладка поиска аниме/манги через Shikimori API.

    Включается/выключается в Настройках (по умолчанию выключена). Не зависит от
    QtMultimedia и тяжёлых модулей — грузится быстро.
    """

    def __init__(self, main_window=None):
        super().__init__()
        self.main = main_window
        self._pool = QThreadPool.globalInstance()
        self._task = None          # текущая поисковая задача (ссылка, чтобы жила)
        self._genres_task = None
        self._results: list = []   # последние найденные Anime (после исключений)
        self._raw_results: list = []   # до применения исключения паков
        self._genres_cache: dict = {}  # content_type -> [(label, id)]
        self._thumb_cache: dict = {}   # anime_id -> QIcon
        self._placeholder = None       # серая заглушка-обложка
        self._excluded: set = set()    # нормализованные названия из паков
        self._excluded_bases: set = set()  # их «базовые» формы (без сезонов)
        self._excluded_packs: list = []  # имена выбранных паков
        self._views_cache: dict = {}   # anime_id -> просмотры (для сортировки)
        self._views_task = None        # текущая задача дозагрузки просмотров
        self._pending_genre = 0        # жанр для восстановления после загрузки
        self._initial_settings = dict(getattr(main_window, "_shikimori_settings", {}) or {})

        if not _HAS_API:
            self._build_unavailable()
            return
        self._build_ui()
        # Восстанавливаем сохранённые настройки (если есть) ДО загрузки жанров,
        # чтобы корректно подтянуть жанры под нужный тип контента.
        if self._initial_settings:
            try:
                self.apply_settings(self._initial_settings)
            except Exception:
                pass
        self._load_genres_async(self._content_type())

    # ── Построение UI ───────────────────────────────────────────────────────
    def _build_unavailable(self):
        lay = QVBoxLayout(self)
        msg = ("Не удалось загрузить вкладку «ShikimoriHYX».\n\n"
               "Нужен пакет «requests» (pip install requests).")
        if _IMPORT_ERROR:
            msg += f"\n\n{_IMPORT_ERROR}"
        lbl = QLabel(msg)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
        lay.addStretch(); lay.addWidget(lbl); lay.addStretch()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Строка поиска: тип контента + запрос + кнопки ─────────────────
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.cb_content = QComboBox()
        self.cb_content.addItem("Аниме", CONTENT_ANIME)
        self.cb_content.addItem("Манга", CONTENT_MANGA)
        self.cb_content.setFixedWidth(110)
        self.cb_content.currentIndexChanged.connect(self._on_content_changed)
        self.ed_query = QLineEdit()
        self.ed_query.setPlaceholderText("Название (можно пусто — тогда фильтры)…")
        self.ed_query.setClearButtonEnabled(True)
        self.ed_query.returnPressed.connect(self.start_search)
        self.ed_query.addAction(get_icon('fa5s.search'),
                                QLineEdit.ActionPosition.LeadingPosition)
        self.btn_search = QPushButton("Найти")
        self.btn_search.setIcon(get_icon('fa5s.search', color='#11111b'))
        self.btn_search.setIconSize(QSize(16, 16))
        self.btn_search.setObjectName("b_primary")
        self.btn_search.clicked.connect(self.start_search)
        self.btn_cancel = QPushButton("Стоп")
        self.btn_cancel.setIcon(get_icon('fa5s.stop'))
        self.btn_cancel.setToolTip("Остановить поиск (накопленные результаты останутся)")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_search)
        search_row.addWidget(self.cb_content)
        search_row.addWidget(self.ed_query, 1)
        search_row.addWidget(self.btn_search)
        search_row.addWidget(self.btn_cancel)
        root.addLayout(search_row)

        # ── Тело: слева список с обложками, справа панель настроек ─────────
        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # Левая колонка — список результатов.
        left = QVBoxLayout(); left.setSpacing(6)
        self.list = QListWidget()
        self.list.setIconSize(QSize(_THUMB_W, _THUMB_H))
        self.list.setSpacing(2)
        self.list.setUniformItemSizes(False)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self._open_selected_in_browser)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        left.addWidget(self.list, 1)
        self.lbl_status = QLabel("Готово к поиску.")
        self.lbl_status.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        left.addWidget(self.lbl_status)
        body.addLayout(left, 1)

        # Правая колонка — прокручиваемая панель настроек.
        self._build_settings_panel(body)

        self._apply_styles()
        self._rebuild_kind_status()

    def _build_settings_panel(self, body):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(330)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(2, 2, 8, 2)
        pv.setSpacing(12)

        def lab(text):
            l = QLabel(text)
            l.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
            return l

        # ── Группа «Фильтры» ──────────────────────────────────────────────
        grp = QGroupBox("Фильтры")
        filt = QGridLayout(grp)
        filt.setHorizontalSpacing(8)
        filt.setVerticalSpacing(8)

        self.sp_score_min = QDoubleSpinBox()
        self.sp_score_min.setRange(0.0, 10.0); self.sp_score_min.setSingleStep(0.5)
        self.sp_score_min.setDecimals(1)
        self.sp_score_min.setSpecialValueText("любая")
        self.sp_score_max = QDoubleSpinBox()
        self.sp_score_max.setRange(0.0, 10.0); self.sp_score_max.setSingleStep(0.5)
        self.sp_score_max.setDecimals(1); self.sp_score_max.setValue(10.0)

        self.cb_kind = QComboBox()
        self.cb_status = QComboBox()
        self.cb_order = QComboBox()
        # «По просмотрам» — локальная сортировка, по умолчанию (первый пункт).
        self.cb_order.addItem(ORDER_LABELS[ORDER_VIEWS], ORDER_VIEWS)
        for o in ORDERS:
            self.cb_order.addItem(ORDER_LABELS.get(o, o), o)

        self.sp_year_from = QSpinBox(); self.sp_year_from.setRange(0, 2099)
        self.sp_year_from.setSpecialValueText("—")
        self.sp_year_to = QSpinBox(); self.sp_year_to.setRange(0, 2099)
        self.sp_year_to.setSpecialValueText("—")

        self.sp_ep_min = QSpinBox(); self.sp_ep_min.setRange(0, 10000)
        self.sp_ep_min.setSpecialValueText("—")
        self.sp_ep_max = QSpinBox(); self.sp_ep_max.setRange(0, 10000)
        self.sp_ep_max.setSpecialValueText("—")

        self.cb_genre = QComboBox(); self.cb_genre.addItem("Любой", 0)

        r = 0
        filt.addWidget(lab("Оценка от"), r, 0); filt.addWidget(self.sp_score_min, r, 1)
        filt.addWidget(lab("до"), r, 2); filt.addWidget(self.sp_score_max, r, 3)
        r += 1
        filt.addWidget(lab("Сортировка"), r, 0)
        filt.addWidget(self.cb_order, r, 1, 1, 3)
        r += 1
        filt.addWidget(lab("Тип"), r, 0)
        filt.addWidget(self.cb_kind, r, 1, 1, 3)
        r += 1
        filt.addWidget(lab("Статус"), r, 0)
        filt.addWidget(self.cb_status, r, 1, 1, 3)
        r += 1
        filt.addWidget(lab("Жанр"), r, 0)
        filt.addWidget(self.cb_genre, r, 1, 1, 3)
        r += 1
        self.lbl_eps = lab("Эпизоды от")
        filt.addWidget(self.lbl_eps, r, 0); filt.addWidget(self.sp_ep_min, r, 1)
        filt.addWidget(lab("до"), r, 2); filt.addWidget(self.sp_ep_max, r, 3)
        r += 1
        filt.addWidget(lab("Год с"), r, 0); filt.addWidget(self.sp_year_from, r, 1)
        filt.addWidget(lab("по"), r, 2); filt.addWidget(self.sp_year_to, r, 3)
        for col in (1, 3):
            filt.setColumnStretch(col, 1)
        pv.addWidget(grp)

        self.btn_reset = QPushButton("Сбросить настройки")
        self.btn_reset.setIcon(get_icon('fa5s.undo'))
        self.btn_reset.setToolTip("Сбросить все фильтры и выбранные паки к значениям по умолчанию")
        self.btn_reset.clicked.connect(self.reset_settings)
        pv.addWidget(self.btn_reset)

        # ── Группа «Исключить паки SiQuesterHYX» ──────────────────────────
        grp_packs = QGroupBox("Исключить паки SiQuesterHYX")
        pl = QVBoxLayout(grp_packs)
        pl.setSpacing(6)
        info = QLabel("Спрятать из выдачи тайтлы, которые уже есть в ответах "
                      "выбранных .siq-паков.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{C['text3']}; font-size:11px;")
        pl.addWidget(info)
        self.btn_packs = QPushButton("Выбрать паки…")
        self.btn_packs.setIcon(get_icon('fa5s.layer-group'))
        self.btn_packs.clicked.connect(self._choose_packs)
        pl.addWidget(self.btn_packs)
        self.lbl_packs = QLabel("Паки не выбраны.")
        self.lbl_packs.setWordWrap(True)
        self.lbl_packs.setStyleSheet(f"color:{C['text2']}; font-size:11px;")
        pl.addWidget(self.lbl_packs)
        pv.addWidget(grp_packs)

        # ── Действия (открыть/экспорт) ────────────────────────────────────
        grp_act = QGroupBox("Результат")
        al = QVBoxLayout(grp_act)
        al.setSpacing(6)
        self.btn_open = QPushButton("Открыть на Shikimori")
        self.btn_open.setIcon(get_icon('fa5s.external-link-alt'))
        self.btn_open.clicked.connect(self._open_selected_in_browser)
        self.btn_export_json = QPushButton("Экспорт JSON")
        self.btn_export_json.setIcon(get_icon('fa5s.file-code'))
        self.btn_export_json.clicked.connect(lambda: self._export("json"))
        self.btn_export_csv = QPushButton("Экспорт CSV")
        self.btn_export_csv.setIcon(get_icon('fa5s.file-csv'))
        self.btn_export_csv.clicked.connect(lambda: self._export("csv"))
        for b in (self.btn_open, self.btn_export_json, self.btn_export_csv):
            b.setEnabled(False)
            al.addWidget(b)
        pv.addWidget(grp_act)

        pv.addStretch(1)
        scroll.setWidget(panel)
        body.addWidget(scroll)

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QWidget {{ color: {C['text']}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {C['surface3']}; border: 1px solid {C['border']};
                border-radius: 5px; padding: 5px 7px; color: {C['text']};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {C['accent']};
            }}
            QPushButton {{
                background: {C['surface3']}; border: 1px solid {C['border']};
                border-radius: 5px; padding: 6px 12px; color: {C['text']};
            }}
            QPushButton:hover {{ background: {C['surface2']}; }}
            QPushButton:disabled {{ color: {C['text3']}; }}
            QPushButton#b_primary {{
                background: {C['accent']}; color: #11111b; border: none; font-weight: 700;
            }}
            QPushButton#b_primary:hover {{ background: {C['accent2']}; }}
            QGroupBox {{
                border: 1px solid {C['border']}; border-radius: 6px;
                margin-top: 10px; padding-top: 8px; font-weight: bold;
                color: {C['accent']};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
            QListWidget {{
                background: {C['surface']}; border: 1px solid {C['border']};
                border-radius: 6px; outline: none;
            }}
            QListWidget::item {{
                padding: 4px; border-radius: 5px; color: {C['text']};
            }}
            QListWidget::item:selected {{ background: {C['surface3']}; color: {C['text']}; }}
            QListWidget::item:hover:!selected {{ background: {C['surface2']}; }}
        """)

    # ── Тип контента (Аниме/Манга) ────────────────────────────────────────────
    def _content_type(self) -> str:
        return self.cb_content.currentData() or CONTENT_ANIME

    def _on_content_changed(self, *_):
        ct = self._content_type()
        self._rebuild_kind_status()
        # Эпизоды → главы для манги (подпись поля).
        self.lbl_eps.setText("Главы от" if ct == CONTENT_MANGA else "Эпизоды от")
        # Жанры различаются — перезагружаем под выбранный тип.
        self.cb_genre.blockSignals(True)
        self.cb_genre.clear(); self.cb_genre.addItem("Любой", 0)
        self.cb_genre.blockSignals(False)
        if ct in self._genres_cache:
            self._fill_genres(self._genres_cache[ct])
        else:
            self._load_genres_async(ct)
        # Старые результаты больше не релевантны.
        self.list.clear()
        self._raw_results = []; self._results = []
        self._set_actions_enabled(False)
        self.lbl_status.setText("Готово к поиску.")

    def _rebuild_kind_status(self):
        """Перезаполняет «Тип» и «Статус» под выбранный тип контента."""
        ct = self._content_type()
        self.cb_kind.blockSignals(True); self.cb_status.blockSignals(True)
        self.cb_kind.clear(); self.cb_kind.addItem("Любой", "")
        for k in kinds_for(ct):
            self.cb_kind.addItem(kind_label(ct, k), k)
        self.cb_status.clear(); self.cb_status.addItem("Любой", "")
        for s in statuses_for(ct):
            self.cb_status.addItem(status_label(ct, s), s)
        self.cb_kind.blockSignals(False); self.cb_status.blockSignals(False)

    # ── Поиск ────────────────────────────────────────────────────────────────
    def _collect_filter(self) -> "AnimeFilter":
        smin = self.sp_score_min.value()
        smax = self.sp_score_max.value()
        yf = self.sp_year_from.value()
        yt = self.sp_year_to.value()
        epmin = self.sp_ep_min.value()
        epmax = self.sp_ep_max.value()
        return AnimeFilter(
            query=self.ed_query.text().strip(),
            kind=self.cb_kind.currentData() or "",
            status=self.cb_status.currentData() or "",
            order=self.cb_order.currentData() or ORDER_VIEWS,
            score_min=(smin if smin > 0 else None),
            score_max=(smax if smax < 10.0 else None),
            year_from=(yf if yf > 0 else None),
            year_to=(yt if yt > 0 else None),
            episodes_min=(epmin if epmin > 0 else None),
            episodes_max=(epmax if epmax > 0 else None),
            genres=([int(self.cb_genre.currentData())]
                    if self.cb_genre.currentData() else []),
            content_type=self._content_type(),
        )

    def start_search(self):
        if self._task is not None:
            return  # уже идёт поиск
        criteria = self._collect_filter()
        err = criteria.validate()
        if err:
            QMessageBox.warning(self, "Проверьте фильтры", err)
            return
        # Новый поиск — чистим список и потоково наполняем его по мере страниц.
        self._stop_views_task()
        self.list.clear()
        self._raw_results = []
        self._results = []
        self._set_actions_enabled(False)
        self._set_busy(True)
        self.lbl_status.setText("Поиск… (нажмите «Стоп», чтобы остановить)")
        task = _SearchTask(criteria)
        task.signals.batch.connect(self._on_search_batch)
        task.signals.finished.connect(self._on_search_finished)
        task.signals.failed.connect(self._on_search_failed)
        task.signals.progress.connect(self._on_search_progress)
        self._task = task
        self._pool.start(task)

    def cancel_search(self):
        if self._task is not None:
            self._task.stop()
        self._set_busy(False)
        self._task = None
        # Накопленное оставляем — финализируем статус и кнопки.
        n = len(self._results)
        self._set_actions_enabled(n > 0)
        self.lbl_status.setText(f"Остановлено. Найдено: {n}" if n
                                else "Остановлено.")
        # Сортировка по просмотрам — досортируем то, что успели набрать.
        if n and self._views_sort_active():
            self._begin_views_sort()

    def _on_search_progress(self, page: int, matched: int):
        if self._task is not None:
            self.lbl_status.setText(
                f"Поиск… страница {page}, найдено {matched} (можно «Стоп»)")

    def _on_search_batch(self, items: list):
        """Потоково добавляет новые тайтлы страницы (с учётом исключения паков)."""
        if self._task is None:
            return
        for a in items:
            self._raw_results.append(a)
            if self._is_excluded(a):
                continue
            self._results.append(a)
            self._append_anime(a)
        self._set_actions_enabled(bool(self._results))

    def _on_search_finished(self, results: list):
        self._task = None
        self._set_busy(False)
        # Полный результат — авторитетный; пересобираем список начисто (на случай
        # дублей/исключений), даём финальный статус.
        self._raw_results = results
        self._apply_exclusions()
        # Если выбрана сортировка по просмотрам — дозагрузим их и пересортируем.
        if self._results and self._views_sort_active():
            self._begin_views_sort()

    def _on_search_failed(self, message: str):
        self._task = None
        self._set_busy(False)
        self.lbl_status.setText("Ошибка запроса.")
        QMessageBox.critical(self, "Shikimori", f"Не удалось выполнить поиск:\n{message}")

    def _set_busy(self, busy: bool):
        self.btn_search.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    def _set_actions_enabled(self, on: bool):
        self.btn_open.setEnabled(on)
        self.btn_export_json.setEnabled(on)
        self.btn_export_csv.setEnabled(on)

    # ── Применение исключения паков и заполнение списка ────────────────────────
    def _is_excluded(self, a: "Anime") -> bool:
        if not self._excluded:
            return False
        nt, nn = _norm_title(a.title), _norm_title(a.name)
        if nt in self._excluded or nn in self._excluded:
            return True
        # Сезонные варианты: пак с «Ванпанчмен» прячет и «Ванпанчмен 3» (и наоборот)
        # — сравниваем «базовые» формы без хвостового номера/«сезон N».
        if self._excluded_bases:
            if _base_title(nt) in self._excluded_bases:
                return True
            if nn and _base_title(nn) in self._excluded_bases:
                return True
        return False

    def _rebuild_excluded_bases(self):
        """Пересобирает множество «базовых» форм исключённых названий."""
        self._excluded_bases = {b for b in (_base_title(x) for x in self._excluded) if b}

    def _apply_exclusions(self):
        """Фильтрует «сырые» результаты по выбранным пакам и обновляет список."""
        raw = self._raw_results
        kept, excluded_n = [], 0
        for a in raw:
            if self._is_excluded(a):
                excluded_n += 1
            else:
                kept.append(a)
        self._results = kept
        self._display_results()
        n = len(self._results)
        self._set_actions_enabled(n > 0)
        if n:
            msg = f"Найдено: {n}"
            if excluded_n:
                msg += f"  (скрыто паками: {excluded_n})"
            self.lbl_status.setText(msg)
        elif raw and excluded_n:
            self.lbl_status.setText("Всё найденное уже есть в выбранных паках.")
        else:
            self.lbl_status.setText("Ничего не найдено под заданные фильтры.")

    # ── Сортировка по просмотрам (локально, с дозагрузкой карточек) ────────────
    def _views_sort_active(self) -> bool:
        return self.cb_order.currentData() == ORDER_VIEWS

    def _display_results(self):
        """Заполняет список результатами. При сортировке по просмотрам сначала
        упорядочивает их по кешу просмотров (неизвестные — в конец)."""
        if self._views_sort_active():
            self._results.sort(
                key=lambda a: self._views_cache.get(a.id, -1), reverse=True)
        self._fill_list(self._results)

    def _stop_views_task(self):
        if self._views_task is not None:
            try:
                self._views_task.stop()
            except Exception:
                pass
            self._views_task = None

    def _begin_views_sort(self):
        """Дозагружает просмотры для результатов, у которых их ещё нет, и затем
        пересортировывает список. Уже известные берём из кеша (не перезапрашиваем)."""
        self._stop_views_task()
        ids = [a.id for a in self._results[:_VIEWS_SORT_MAX]
               if a.id not in self._views_cache]
        if not ids:
            self._resort_by_views(done=True)
            return
        self.lbl_status.setText(f"Сортировка по просмотрам… 0/{len(ids)}")
        task = _ViewsTask(ids)
        task.signals.item.connect(self._on_views_item)
        task.signals.progress.connect(self._on_views_progress)
        task.signals.finished.connect(self._on_views_finished)
        self._views_task = task
        self._pool.start(task)

    def _on_views_item(self, anime_id: int, views: int):
        self._views_cache[anime_id] = views

    def _on_views_progress(self, done: int, total: int):
        if self._views_task is not None:
            self.lbl_status.setText(f"Сортировка по просмотрам… {done}/{total}")

    def _on_views_finished(self):
        self._views_task = None
        self._resort_by_views(done=True)

    def _resort_by_views(self, done: bool = False):
        """Пересобирает список в порядке убывания просмотров (по кешу)."""
        if not self._views_sort_active():
            return
        self._results.sort(
            key=lambda a: self._views_cache.get(a.id, -1), reverse=True)
        self._fill_list(self._results)
        if done:
            n = len(self._results)
            self.lbl_status.setText(f"Найдено: {n} (по просмотрам)" if n
                                    else "Ничего не найдено.")

    def _fill_list(self, results: list):
        self.list.clear()
        for a in results:
            self._append_anime(a)

    def _append_anime(self, a: "Anime"):
        """Добавляет один тайтл в список (обложка + название + краткая инфа)."""
        ct = self._content_type()
        unit = "гл." if ct == CONTENT_MANGA else "эп."
        parts = []
        if a.score:
            parts.append(f"★ {a.score:.2f}")
        parts.append(kind_label(ct, a.kind))
        if a.year:
            parts.append(str(a.year))
        if a.episodes:
            parts.append(f"{a.episodes} {unit}")
        # Просмотры (если уже дозагружены для сортировки) — с пробелами в тысячах.
        v = self._views_cache.get(a.id)
        if v is not None and v >= 0:
            parts.append(f"👁 {v:,}".replace(",", " "))
        sub = "  ·  ".join(parts)
        text = a.title
        if a.name and a.name != a.title:
            text += f"\n{a.name}"
        text += f"\n{sub}"
        it = QListWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, a.url)
        it.setData(Qt.ItemDataRole.UserRole + 1, a.id)
        it.setIcon(self._icon_for(a))
        it.setSizeHint(QSize(0, _THUMB_H + 12))
        self.list.addItem(it)

    # ── Обложки (асинхронно, с кешем) ──────────────────────────────────────────
    def _placeholder_icon(self) -> QIcon:
        if self._placeholder is None:
            pm = QPixmap(_THUMB_W, _THUMB_H)
            pm.fill(QColor(C["surface3"]))
            self._placeholder = QIcon(pm)
        return self._placeholder

    def _icon_for(self, a: "Anime") -> QIcon:
        if a.id in self._thumb_cache:
            return self._thumb_cache[a.id]
        if a.image_url:
            task = _ThumbTask(a.id, a.image_url)
            task.signals.done.connect(self._on_thumb_loaded)
            self._pool.start(task)
        return self._placeholder_icon()

    def _on_thumb_loaded(self, anime_id: int, data: bytes):
        pm = QPixmap()
        if not pm.loadFromData(data):
            return
        pm = pm.scaled(_THUMB_W, _THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        icon = QIcon(pm)
        self._thumb_cache[anime_id] = icon
        # Находим строку с этим id и ставим иконку (список мог быть перестроен).
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole + 1) == anime_id:
                it.setIcon(icon)
                break

    def _on_selection_changed(self):
        has_sel = self.list.currentItem() is not None
        self.btn_open.setEnabled(has_sel and bool(self._results))

    def _open_selected_in_browser(self, *_):
        it = self.list.currentItem()
        if it is None:
            return
        url = it.data(Qt.ItemDataRole.UserRole)
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    # ── Исключение паков SiQuesterHYX ──────────────────────────────────────────
    def _siq_datasets(self):
        """Список загруженных в SiQuesterHYX датасетов или [] если вкладки нет."""
        tsq = getattr(self.main, "tab_siquester", None) if self.main else None
        inner = getattr(tsq, "inner", None) if tsq else None
        return list(getattr(inner, "datasets", []) or []) if inner else []

    @staticmethod
    def _pack_answers(ds) -> set:
        """Собирает нормализованные ответы из одного .siq-пака."""
        out = set()
        w = ds.get("widget")
        siq = getattr(w, "_siq", None) if w else None
        rounds = getattr(siq, "rounds", []) if siq else []
        for rd in rounds:
            for th in rd.get("themes", []):
                for q in th.get("questions", []):
                    answers = list(q.get("answers", []) or [])
                    for it in q.get("items", []):
                        if (it.get("param") == "answer"
                                and it.get("type") == "text"
                                and not it.get("is_ref")):
                            answers.append(it.get("text", ""))
                    for ans in answers:
                        n = _norm_title(ans)
                        if n:
                            out.add(n)
        return out

    def _choose_packs(self):
        datasets = self._siq_datasets()
        if not datasets:
            QMessageBox.information(
                self, "Паки SiQuesterHYX",
                "Нет загруженных паков.\n\nВключите вкладку «SiQuesterHYX» в "
                "Настройках и откройте в ней .siq-пак(и), затем повторите.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Выбор паков для исключения")
        dlg.setMinimumWidth(380)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Тайтлы из ответов отмеченных паков будут скрыты "
                             "из выдачи поиска:"))
        checks = []
        for idx, ds in enumerate(datasets):
            name = ds.get("pkg_name") or f"Пак {idx + 1}"
            cb = QCheckBox(name)
            cb.setChecked(name in self._excluded_packs)
            lay.addWidget(cb)
            checks.append((cb, ds, name))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{C['border']};")
        lay.addWidget(line)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        excluded = set()
        chosen_names = []
        for cb, ds, name in checks:
            if cb.isChecked():
                chosen_names.append(name)
                excluded |= self._pack_answers(ds)
        self._excluded = excluded
        self._rebuild_excluded_bases()
        self._excluded_packs = chosen_names
        if chosen_names:
            self.lbl_packs.setText(
                f"Выбрано паков: {len(chosen_names)} "
                f"({len(excluded)} ответов).\n" + ", ".join(chosen_names))
        else:
            self.lbl_packs.setText("Паки не выбраны.")
        # Переприменяем к уже найденному (без нового запроса).
        if self._raw_results:
            self._apply_exclusions()

    # ── Жанры (асинхронно) ───────────────────────────────────────────────────
    def _load_genres_async(self, content_type: str):
        if self._genres_task is not None:
            return
        task = _GenresTask(content_type)
        task.signals.finished.connect(self._on_genres_loaded)
        task.signals.failed.connect(lambda *_: setattr(self, "_genres_task", None))
        self._genres_task = task
        self._pool.start(task)

    def _on_genres_loaded(self, content_type: str, genres: list):
        self._genres_task = None
        items = []
        for g in genres:
            gid = g.get("id")
            label = g.get("russian") or g.get("name") or str(gid)
            if gid is not None:
                items.append((label, int(gid)))
        items.sort(key=lambda x: x[0].lower())
        self._genres_cache[content_type] = items
        # Заполняем, только если пользователь всё ещё на этом типе.
        if content_type == self._content_type():
            self._fill_genres(items)

    def _fill_genres(self, items: list):
        # Сохраняем текущий или отложенный (восстановленный из настроек) жанр.
        cur = self.cb_genre.currentData() or self._pending_genre
        self.cb_genre.blockSignals(True)
        self.cb_genre.clear()
        self.cb_genre.addItem("Любой", 0)
        for label, gid in items:
            self.cb_genre.addItem(label, gid)
        if cur:
            idx = self.cb_genre.findData(cur)
            if idx >= 0:
                self.cb_genre.setCurrentIndex(idx)
                self._pending_genre = 0
        self.cb_genre.blockSignals(False)

    # ── Сохранение / восстановление / сброс настроек ───────────────────────────
    def get_settings(self) -> dict:
        """Текущие настройки вкладки (для сохранения в settings.json)."""
        if not _HAS_API:
            return dict(self._initial_settings)
        return {
            "content_type": self._content_type(),
            "query": self.ed_query.text().strip(),
            "score_min": self.sp_score_min.value(),
            "score_max": self.sp_score_max.value(),
            "order": self.cb_order.currentData() or "ranked",
            "kind": self.cb_kind.currentData() or "",
            "status": self.cb_status.currentData() or "",
            "genre": int(self.cb_genre.currentData() or 0),
            "year_from": self.sp_year_from.value(),
            "year_to": self.sp_year_to.value(),
            "ep_min": self.sp_ep_min.value(),
            "ep_max": self.sp_ep_max.value(),
            "excluded_packs": list(self._excluded_packs),
        }

    def apply_settings(self, s: dict):
        """Восстанавливает настройки из словаря (вызывается при создании вкладки)."""
        if not _HAS_API or not isinstance(s, dict):
            return
        ct = s.get("content_type", CONTENT_ANIME)
        idx = self.cb_content.findData(ct)
        if idx >= 0:
            self.cb_content.blockSignals(True)
            self.cb_content.setCurrentIndex(idx)
            self.cb_content.blockSignals(False)
            self._rebuild_kind_status()
            self.lbl_eps.setText("Главы от" if ct == CONTENT_MANGA else "Эпизоды от")
        self.ed_query.setText(str(s.get("query", "")))
        self.sp_score_min.setValue(float(s.get("score_min", 0.0) or 0.0))
        self.sp_score_max.setValue(float(s.get("score_max", 10.0) or 10.0))
        oi = self.cb_order.findData(s.get("order", ORDER_VIEWS))
        if oi >= 0:
            self.cb_order.setCurrentIndex(oi)
        ki = self.cb_kind.findData(s.get("kind", ""))
        if ki >= 0:
            self.cb_kind.setCurrentIndex(ki)
        si = self.cb_status.findData(s.get("status", ""))
        if si >= 0:
            self.cb_status.setCurrentIndex(si)
        self.sp_year_from.setValue(int(s.get("year_from", 0) or 0))
        self.sp_year_to.setValue(int(s.get("year_to", 0) or 0))
        self.sp_ep_min.setValue(int(s.get("ep_min", 0) or 0))
        self.sp_ep_max.setValue(int(s.get("ep_max", 0) or 0))
        # Жанр подтянется после загрузки списка жанров (см. _fill_genres).
        self._pending_genre = int(s.get("genre", 0) or 0)
        gi = self.cb_genre.findData(self._pending_genre)
        if gi >= 0:
            self.cb_genre.setCurrentIndex(gi)
            self._pending_genre = 0
        # Выбранные паки восстанавливаем (если SiQuesterHYX уже загрузил их).
        names = list(s.get("excluded_packs", []) or [])
        if names:
            self._restore_packs(names)

    def _restore_packs(self, names: list):
        """Восстанавливает исключаемые паки по именам (если они уже загружены)."""
        wanted = set(names)
        excluded = set()
        found = []
        for idx, ds in enumerate(self._siq_datasets()):
            name = ds.get("pkg_name") or f"Пак {idx + 1}"
            if name in wanted:
                found.append(name)
                excluded |= self._pack_answers(ds)
        # Имена помним даже если паки ещё не открыты — попадут при следующем выборе.
        self._excluded_packs = found or list(names)
        self._excluded = excluded
        self._rebuild_excluded_bases()
        if found:
            self.lbl_packs.setText(
                f"Выбрано паков: {len(found)} ({len(excluded)} ответов).\n"
                + ", ".join(found))
        elif names:
            self.lbl_packs.setText(
                "Сохранённые паки не загружены в SiQuesterHYX — откройте их там.")

    def reset_settings(self):
        """Сбрасывает все фильтры и выбранные паки к значениям по умолчанию."""
        if not _HAS_API:
            return
        self.cb_content.setCurrentIndex(0)   # Аниме (вызовет _on_content_changed)
        self.ed_query.clear()
        self.sp_score_min.setValue(0.0)
        self.sp_score_max.setValue(10.0)
        self.cb_order.setCurrentIndex(0)
        self.cb_kind.setCurrentIndex(0)
        self.cb_status.setCurrentIndex(0)
        self.cb_genre.setCurrentIndex(0)
        self._pending_genre = 0
        self.sp_year_from.setValue(0)
        self.sp_year_to.setValue(0)
        self.sp_ep_min.setValue(0)
        self.sp_ep_max.setValue(0)
        self._excluded = set()
        self._excluded_bases = set()
        self._excluded_packs = []
        self.lbl_packs.setText("Паки не выбраны.")
        self.lbl_status.setText("Настройки сброшены.")

    # ── Экспорт ──────────────────────────────────────────────────────────────
    def _export(self, fmt: str):
        if not self._results:
            return
        if fmt == "json":
            path, _ = QFileDialog.getSaveFileName(
                self, "Сохранить как JSON", "shikimori.json", "JSON (*.json)")
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Сохранить как CSV", "shikimori.csv", "CSV (*.csv)")
        if not path:
            return
        rows = [a.as_row() for a in self._results]
        try:
            if fmt == "json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(rows, f, ensure_ascii=False, indent=2)
            else:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
        except Exception as e:
            QMessageBox.critical(self, "Экспорт", f"Не удалось сохранить файл:\n{e}")
            return
        self.lbl_status.setText(f"Сохранено: {os.path.basename(path)} ({len(rows)})")
        if self.main is not None and hasattr(self.main, "log"):
            try:
                self.main.log(f"ShikimoriHYX: экспортировано {len(rows)} → {path}")
            except Exception:
                pass

    # ── Очистка (вызывается главным окном при закрытии/выключении вкладки) ────
    def cleanup(self):
        if self._task is not None:
            try:
                self._task.stop()
            except Exception:
                pass
            self._task = None
        self._stop_views_task()
        if self._genres_task is not None:
            try:
                self._genres_task.signals.finished.disconnect()
            except Exception:
                pass
            self._genres_task = None
