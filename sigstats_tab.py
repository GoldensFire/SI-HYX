# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# sigstats_tab.py — экспериментальная вкладка «Поиск пакетов»: нативный порт
# отдельного проекта SiGStats (был на Streamlit) внутрь SI-HYX. Логика сбора
# (sibrowser.ru + SIStatistics) и хранения (SQLite) не переписывалась — это
# модули пакета sigstats/ (скопированы как есть, без Streamlit-зависимостей).
# Здесь — только Qt-интерфейс поверх них: сбор новых паков (по скачиваниям/
# дате, по теме с процентным порогом, по автору), таблица/фильтры уже
# собранных паков, карта тем, топ авторов, экспорт для нейросети.
#
# БД/скачанные .siq/медиа живут НЕ в папке проекта, а в
# %APPDATA%\unified_media_tool\sigstats — см. CONFIG_DIR ниже: папка с
# исходниками — это код, который переустанавливается/обновляется, а не место
# для пользовательских данных (то же самое CONFIG_DIR уже хранит settings.json
# и кэш ShikimoriHYX).
#
# Сетевые запросы (scraping sibrowser.ru + запросы статистики) идут в фоне
# через QThreadPool/QRunnable, как в ShikimoriHYX — интерфейс не виснет.
#
# Вкладка по умолчанию ВЫКЛЮЧЕНА (включается в Настройках, как остальные
# экспериментальные вкладки).
from __future__ import annotations
import os
import webbrowser
import datetime as _dt

from PyQt6.QtCore import (Qt, QObject, QRunnable, QThreadPool, pyqtSignal, QUrl,
                          QTimer, QEvent, QDate, QRect, QSize)
from PyQt6.QtGui import QDesktopServices, QColor, QFontMetrics, QPalette
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QGroupBox,
    QRadioButton, QButtonGroup, QLabel, QLineEdit, QPushButton, QComboBox,
    QCheckBox, QSlider, QSpinBox, QDateEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSplitter, QTextBrowser, QDialog,
    QProgressBar, QFileDialog, QMessageBox, QScrollArea, QTextEdit,
    QDialogButtonBox, QFrame, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyle, QStyleOptionViewItem, QApplication, QMenu,
)
from msgbox import msgbox_critical, msgbox_warning, msgbox_information, msgbox_question

try:
    from config import get_icon, icon_html, CONFIG_DIR, FFPROBE
except Exception:  # pragma: no cover
    CONFIG_DIR = None
    FFPROBE = None

    def get_icon(name, color="#cdd6f4"):
        from PyQt6.QtGui import QIcon as _QIcon
        return _QIcon()

    def icon_html(name, size=16, color="#cdd6f4"):
        return ""

# Переменная окружения ДОЛЖНА быть выставлена ДО первого импорта sigstats.config
# (он читает её один раз при импорте) — поэтому это идёт перед `from sigstats
# import ...`. Без неё БД/пакеты/медиа легли бы рядом с исходниками sigstats/
# внутри репозитория SI-HYX, чего мы как раз избегаем.
if CONFIG_DIR:
    os.environ.setdefault("SIGSTATS_HOME", os.path.join(CONFIG_DIR, "sigstats"))

_HAS_BACKEND = True
_IMPORT_ERROR = ""
try:
    from sigstats import config as sg_config, db as sg_db, collector as sg_collector
    from sigstats import analysis as sg_analysis, export as sg_export
    if FFPROBE:
        sg_config.FFPROBE_PATH = FFPROBE  # используем bundled ffprobe SI-HYX
except Exception as e:  # pragma: no cover
    _HAS_BACKEND = False
    _IMPORT_ERROR = str(e)

_ANY_TOPIC = "— любая —"
_LEN_GROUPS = ["Короткие", "Средние", "Полные", "Большие"]
_PERIODS = {"Неделя": 7, "Месяц": 30, "3 месяца": 90, "Полгода": 182, "Год": 365}
_DIFF_LEVELS = ["лёгкий", "средне", "сложно", "оч. сложно"]
_DIFF_COLORS = {"лёгкий": "#a6e3a1", "средне": "#f9e2af", "сложно": "#f38ba8", "оч. сложно": "#8839ef"}
_RARITY_COLORS = {"редкая": "#f38ba8", "средняя": "#f9e2af", "частая": "#a6e3a1"}
# Цветная вертикальная полоска слева от строки для паков с преобладающей темой
# (красная — аниме, фиолетовая — музыка); красит не весь фон строки, а только
# узкую полосу у левого края (см. _AccentBarDelegate) — так заметнее, но не
# мешает читать текст остальных колонок.
_CATEGORY_ACCENT = {"Аниме": "#f38ba8", "Музыка": "#cba6f7"}


def _fmt_pct(v, digits=0) -> str:
    try:
        import math
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "—"
        return f"{v:.{digits}f}%"
    except Exception:
        return "—"


def _top_category(categories):
    """Категория с наибольшим процентом (доминирующая тема пака) или None."""
    if not categories:
        return None
    try:
        return max(categories, key=lambda c: (c.get("pct") or 0))
    except Exception:
        return categories[0]


def _dominant_category(categories) -> str:
    # Доминирующая = с наибольшим процентом (та же, по которой строка красится в
    # красный, если это «Аниме») — чтобы колонка «Тема» и цвет строки совпадали.
    c = _top_category(categories)
    if not c:
        return "—"
    name = c.get("name") or "—"
    pct = c.get("pct")
    return f"{name} {pct}%" if pct is not None else name


def _fmt_date(v) -> str:
    """Дата публикации пака на sibrowser (ISO-строка вида 2021-05-14T…) → дд.мм.гггг."""
    import math
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = str(v)[:10]
    try:
        y, m, d = s.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return s or "—"


class _PkgNameDelegate(QStyledItemDelegate):
    """Ячейка «Название»: текст с переносом по словам + индикатор скачивания
    справа — зелёная галочка (пак скачан) или «NN%» во время скачивания. Заменяет
    прежнюю отдельную колонку «.siq». Данные берёт из ролей элемента:
    DownloadedRole (bool) и ProgressRole (int 0..99 | None)."""

    DownloadedRole = Qt.ItemDataRole.UserRole + 21
    ProgressRole = Qt.ItemDataRole.UserRole + 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self._check = get_icon('fa5s.check', color='#a6e3a1')

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        # Фон / выделение / чередование / рамку фокуса рисует штатный стиль.
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        prog = index.data(self.ProgressRole)
        downloaded = bool(index.data(self.DownloadedRole))
        rect = opt.rect.adjusted(6, 2, -6, -2)
        status_w = 0
        painter.save()
        if prog is not None:
            s = f"{int(prog)}%"
            status_w = painter.fontMetrics().horizontalAdvance(s) + 8
            painter.setPen(QColor('#89b4fa'))
            painter.drawText(
                QRect(rect.right() - status_w, rect.top(), status_w, rect.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), s)
        elif downloaded:
            isz = 15
            self._check.paint(painter, QRect(
                rect.right() - isz, rect.top() + (rect.height() - isz) // 2, isz, isz))
            status_w = isz + 6

        if opt.state & QStyle.StateFlag.State_Selected:
            painter.setPen(opt.palette.color(QPalette.ColorRole.HighlightedText))
        else:
            painter.setPen(opt.palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            QRect(rect.left(), rect.top(), rect.width() - status_w, rect.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap), text)
        painter.restore()

    def sizeHint(self, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        w = opt.rect.width()
        if w <= 0 and isinstance(self.parent(), QTableWidget):
            w = self.parent().columnWidth(index.column())
        avail = max(w - 40, 60)
        br = QFontMetrics(opt.font).boundingRect(
            QRect(0, 0, avail, 100000), int(Qt.TextFlag.TextWordWrap), opt.text)
        return QSize(w if w > 0 else 200, max(br.height() + 8, 26))


class _AccentBarDelegate(QStyledItemDelegate):
    """Ячейка чекбокса (колонка 0): рисует обычный чекбокс + узкую цветную
    полоску у самого левого края строки (см. _CATEGORY_ACCENT) — для паков с
    преобладающей темой. Полоска вместо покраски всего фона строки: заметно,
    но не мешает читать текст остальных колонок."""

    AccentRole = Qt.ItemDataRole.UserRole + 23
    _BAR_W = 4

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        color = index.data(self.AccentRole)
        if not color:
            return
        painter.save()
        bar = QRect(option.rect.left(), option.rect.top(), self._BAR_W, option.rect.height())
        painter.fillRect(bar, QColor(color))
        painter.restore()


class _NumItem(QTableWidgetItem):
    """Ячейка таблицы с числовой сортировкой (сортирует по UserRole, не по тексту)."""

    def __init__(self, text: str, value):
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole, value)

    def __lt__(self, other):
        a = self.data(Qt.ItemDataRole.UserRole)
        b = other.data(Qt.ItemDataRole.UserRole) if isinstance(other, QTableWidgetItem) else None
        try:
            if a is None:
                return True
            if b is None:
                return False
            return a < b
        except Exception:
            return super().__lt__(other)


# ──────────────────────────────────────────────────────────────────────────
# Фоновые задачи (QThreadPool) — сбор/обновление статистики не блокируют GUI
# ──────────────────────────────────────────────────────────────────────────
class _JobSignals(QObject):
    progress = pyqtSignal(int, int, str)
    package_added = pyqtSignal(int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class _JobTask(QRunnable):
    """Обёртка над collector.collect/collect_author/refresh_stats/
    recompute_durations — все они принимают progress_cb и should_stop.
    collect/collect_author дополнительно принимают on_new_package — сюда
    передаётся, только если функция его поддерживает (см. _accepts_on_new)."""

    def __init__(self, func, **kwargs):
        super().__init__()
        self.setAutoDelete(False)
        self.func = func
        self.kwargs = kwargs
        self.signals = _JobSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            import inspect
            kwargs = dict(self.kwargs)
            if "on_new_package" in inspect.signature(self.func).parameters:
                kwargs["on_new_package"] = lambda pid: self.signals.package_added.emit(pid)
            result = self.func(
                progress_cb=lambda done, total, msg: self.signals.progress.emit(done, total, msg),
                should_stop=lambda: self._stop,
                **kwargs)
            self.signals.finished.emit(result)
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(str(e))


class _DownloadSignals(QObject):
    progress = pyqtSignal(int, int, str)
    item_progress = pyqtSignal(int, int)   # (package_id, процент 0..100)
    finished = pyqtSignal(int)   # сколько успешно скачано


class _BulkDownloadTask(QRunnable):
    """Скачивает .siq нескольких отмеченных паков последовательно, отдавая
    прогресс скачивания КАЖДОГО пака (item_progress) — чтобы у его строки в
    таблице бежал процент, а по завершении встала галочка."""

    def __init__(self, items):
        super().__init__()
        self.setAutoDelete(False)
        self.items = items   # [(package_id, sibrowser_id, name)]
        self.signals = _DownloadSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        ok = 0
        total = len(self.items)
        for i, (pid, sib_id, name) in enumerate(self.items, 1):
            if self._stop:
                break
            self.signals.progress.emit(i, total, name)
            self.signals.item_progress.emit(pid, 0)

            def _pcb(done, tot, _pid=pid):
                pct = int(done / tot * 100) if tot else 0
                self.signals.item_progress.emit(_pid, min(99, max(0, pct)))
            try:
                if sg_collector.download_one(pid, sib_id, name, progress_cb=_pcb):
                    ok += 1
                    self.signals.item_progress.emit(pid, 100)
            except Exception:
                pass
        self.signals.finished.emit(ok)


class SigstatsTab(QWidget):
    """Вкладка «Поиск пакетов»: сбор и анализ статистики паков «Своя игра»."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self._pool = QThreadPool.globalInstance()
        self._active_job = None
        self._loaded = False

        self._pkgs_df = None
        self._themes_df = None
        self._authors_df = None
        self._pkg_view_df = None
        self._theme_view_df = None
        # cmb_cat_filter заполняется реальными категориями только после первой
        # загрузки БД (showEvent → _reload_data) — до этого момента там только
        # пункт "любая". Сохранённое значение фильтра держим тут и подставляем
        # в _refresh_packages_table при первом же реальном заполнении списка.
        self._pending_cat_filter = None
        # Пока открыта карточка пака, ставим фильтр событий на всё приложение,
        # чтобы клик по ЛЮБОЙ области вне панели закрывал её (см. eventFilter).
        self._app_click_filter_on = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        if not _HAS_BACKEND:
            root.addWidget(QLabel(
                f"Не удалось загрузить модуль sigstats: {_IMPORT_ERROR}\n"
                "Проверьте, что установлены pandas, beautifulsoup4, lxml, emoji."))
            return

        self._author_blacklist = sg_config.load_author_blacklist()
        self._played_ids: set[int] = set(sg_config.load_played_packages())
        self._pkg_blacklist: set[int] = set(sg_config.load_package_blacklist())
        self._last_collect_key = None
        self._live_refresh_timer = QTimer(self)
        self._live_refresh_timer.setSingleShot(True)
        self._live_refresh_timer.timeout.connect(self._live_refresh_now)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet("color:#a6adc8;")
        root.addWidget(self.lbl_summary)

        self.subtabs = QTabWidget()
        root.addWidget(self.subtabs, 1)

        self._build_packages_page()
        self._build_themes_page()
        self._build_authors_page()
        self._build_export_page()

        self._load_ui_settings()
        self._wire_settings_persistence()

    # ──────────────────────────────────────────────────────────────────────
    # Ленивая загрузка БД — только при первом реальном показе вкладки
    # ──────────────────────────────────────────────────────────────────────
    def showEvent(self, e):
        super().showEvent(e)
        if not self._loaded and _HAS_BACKEND:
            self._loaded = True
            self._reload_data()
        # Карточка была открыта до ухода со вкладки — возвращаем фильтр «клик вне
        # панели закрывает её» (на скрытой вкладке он не нужен, см. hideEvent).
        if getattr(self, "pkg_detail", None) is not None and self.pkg_detail.isVisible():
            self._set_app_click_filter(True)

    def hideEvent(self, e):
        super().hideEvent(e)
        # Незачем держать фильтр событий на всём приложении, пока вкладка скрыта.
        try:
            self._set_app_click_filter(False)
        except Exception:
            pass

    def _reload_data(self):
        try:
            sg_db.init_db()
            with sg_db.connect() as conn:
                self._pkgs_df = sg_analysis.load_packages(conn)
                self._themes_df = sg_analysis.theme_table(conn)
                self._authors_df = sg_analysis.author_table(conn)
                summary = sg_db.stats(conn)
            self.lbl_summary.setText(
                f"Пакетов: {summary['packages']} · со статистикой: {summary['with_stats']} · "
                f"скачано .siq: {summary['with_siq']} · уник. тем: {summary['themes']} · "
                f"вопросов: {summary['questions']}")
        except Exception as e:
            self._pkgs_df = self._pkgs_df if self._pkgs_df is not None else __import__("pandas").DataFrame()
            self._themes_df = self._themes_df if self._themes_df is not None else __import__("pandas").DataFrame()
            self._authors_df = self._authors_df if self._authors_df is not None else __import__("pandas").DataFrame()
            self._log(f"Поиск пакетов: ошибка загрузки БД: {e}")
        self._refresh_played_list()
        self._refresh_pkg_blacklist_list()
        self._refresh_packages_table()
        self._refresh_themes_table()
        self._refresh_authors_table()

    def _log(self, msg):
        try:
            self.main.log(msg)
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────
    # Настройки UI (фильтры/сбор данных) — переживают перезапуск приложения.
    # ──────────────────────────────────────────────────────────────────────
    def _persisted_widgets(self) -> dict:
        d = {
            "mode_dl": self.rb_mode_dl, "mode_date": self.rb_mode_date,
            "min_dl": self.sp_min_dl, "max_new": self.sp_max_new,
            "min_started_collect": self.sp_min_started_collect,
            "start_page": self.sp_start_page,
            "do_siq": self.chk_do_siq, "period": self.cmb_period,
            "custom_date": self.de_custom, "topic": self.cmb_topic,
            "topic_min": self.sl_topic_min,
            "only_siq": self.chk_only_siq, "min_comp": self.sl_min_comp,
            "min_started_filter": self.sp_min_started,
            "cat_min": self.sl_cat_min, "search": self.ed_search,
            "show_played": self.chk_show_played,
            "min_pkgs_theme": self.sp_min_pkgs, "min_pk_author": self.sp_min_pk,
            "min_started_author": self.sp_min_started_a,
            "auth_stats_only": self.chk_auth_stats,
            "export_n": self.sp_export_n, "export_themes": self.chk_export_themes,
        }
        for g, chk in self._len_checks.items():
            d[f"len_{g}"] = chk
        for lvl, chk in self._diff_checks.items():
            d[f"diff_{lvl}"] = chk
        return d

    @staticmethod
    def _get_widget_value(w):
        if isinstance(w, (QCheckBox, QRadioButton)):
            return w.isChecked()
        if isinstance(w, (QSpinBox, QSlider)):
            return w.value()
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QLineEdit):
            return w.text()
        if isinstance(w, QDateEdit):
            return w.date().toString("yyyy-MM-dd")
        return None

    @staticmethod
    def _set_widget_value(w, v):
        if v is None:
            return
        if isinstance(w, (QCheckBox, QRadioButton)):
            w.setChecked(bool(v))
        elif isinstance(w, (QSpinBox, QSlider)):
            w.setValue(int(v))
        elif isinstance(w, QComboBox):
            idx = w.findText(str(v))
            if idx >= 0:
                w.setCurrentIndex(idx)
        elif isinstance(w, QLineEdit):
            w.setText(str(v))
        elif isinstance(w, QDateEdit):
            try:
                y, m, dd = (int(x) for x in str(v).split("-"))
                w.setDate(QDate(y, m, dd))
            except Exception:
                pass

    def _load_ui_settings(self):
        data = sg_config.load_ui_settings()
        if not data:
            return
        for key, w in self._persisted_widgets().items():
            if key in data:
                w.blockSignals(True)
                try:
                    self._set_widget_value(w, data[key])
                finally:
                    w.blockSignals(False)
        # cmb_cat_filter восстанавливается отдельно — см. _pending_cat_filter
        # (в момент загрузки настроек список категорий ещё пустой).
        if "cat_filter" in data:
            self._pending_cat_filter = data["cat_filter"]
        self._sync_date_visibility()

    def _save_ui_settings(self, *args):
        data = {key: self._get_widget_value(w) for key, w in self._persisted_widgets().items()}
        data["cat_filter"] = self.cmb_cat_filter.currentText()
        sg_config.save_ui_settings(data)

    def _wire_settings_persistence(self):
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.timeout.connect(self._save_ui_settings)

        def _schedule(*_a):
            self._settings_save_timer.start(600)

        widgets = dict(self._persisted_widgets())
        widgets["cat_filter"] = self.cmb_cat_filter
        for w in widgets.values():
            if isinstance(w, (QCheckBox, QRadioButton)):
                w.toggled.connect(_schedule)
            elif isinstance(w, (QSpinBox, QSlider)):
                w.valueChanged.connect(_schedule)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(_schedule)
            elif isinstance(w, QLineEdit):
                w.textChanged.connect(_schedule)
            elif isinstance(w, QDateEdit):
                w.dateChanged.connect(_schedule)

    # ══════════════════════════════════════════════════════════════════════
    # Вкладка «Пакеты»: сбор данных + фильтры + таблица + карточка
    # ══════════════════════════════════════════════════════════════════════
    def _build_packages_page(self):
        page = QWidget()
        root = QVBoxLayout(page)

        # Как в ShikimoriHYX: слева гибкий список/таблица, справа — узкая
        # прокручиваемая колонка настроек фиксированной ширины (см.
        # ShikimoriTab._build_ui/_build_settings_panel). Раньше «Сбор данных» и
        # «Фильтры» лежали НАД таблицей и вместе с ней не помещались по высоте —
        # QVBoxLayout сжимал все строки разом, наезжая текстом друг на друга.
        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # ── Левая колонка: список пакетов + карточка + действия ─────────────
        left = QVBoxLayout()
        left.setSpacing(6)

        self.lbl_pkg_count = QLabel("")
        self.lbl_pkg_count.setStyleSheet("color:#a6adc8;")
        left.addWidget(self.lbl_pkg_count)

        split = QSplitter(Qt.Orientation.Horizontal)
        # Колонки: чек · Название (с индикатором скачивания) · Авторы · Дата
        # выхода · Вопр. · Сложность · Длит. · Скач. · % завершения · Перцентиль ·
        # Баланс · % попыток · % правильных · Игр начато · Тема · Группа.
        # «Тема» перенесена в предпоследнее место, «.siq» убрана (её роль —
        # галочка/процент прямо в колонке «Название», см. _PkgNameDelegate).
        self.tbl_pkgs = QTableWidget(0, 16)
        self.tbl_pkgs.setHorizontalHeaderLabels([
            "", "Название", "Авторы", "Дата выхода", "Вопр.", "Сложность", "Длит.",
            "Скач.", "% завершения", "Перцентиль", "Баланс", "% попыток",
            "% правильных", "Игр начато", "Тема", "Группа",
        ])
        self._COL_NAME = 1
        self._COL_THEME = 14
        self.tbl_pkgs.horizontalHeaderItem(0).setIcon(get_icon('fa5s.check-square'))
        self.tbl_pkgs.setSortingEnabled(True)
        self.tbl_pkgs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_pkgs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_pkgs.setAlternatingRowColors(True)
        self.tbl_pkgs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Перенос по словам делает ТОЛЬКО делегат «Название»; остальные колонки
        # остаются в одну строку (длинное — сокращается «…»), чтобы строки не
        # разрастались по высоте из-за длинных авторов/тем.
        self.tbl_pkgs.setWordWrap(False)
        self.tbl_pkgs.verticalHeader().setVisible(False)
        # Название рисует свой делегат: перенос длинного имени по словам +
        # индикатор скачивания (процент/галочка) справа.
        self._name_delegate = _PkgNameDelegate(self.tbl_pkgs)
        self.tbl_pkgs.setItemDelegateForColumn(self._COL_NAME, self._name_delegate)
        # Колонка 0 (чекбокс) заодно рисует цветную полоску слева от строки —
        # см. _AccentBarDelegate/_CATEGORY_ACCENT.
        self._accent_delegate = _AccentBarDelegate(self.tbl_pkgs)
        self.tbl_pkgs.setItemDelegateForColumn(0, self._accent_delegate)
        # Ширины столбцов подгоняются под содержимое (без лишней пустоты справа):
        # короткие числовые/датовые — ResizeToContents, «Авторы»/«Тема» тянутся
        # руками, а «Название» растягивается на остаток (там перенос по словам).
        hdr = self.tbl_pkgs.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(self._COL_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)         # Авторы
        hdr.setSectionResizeMode(self._COL_THEME, QHeaderView.ResizeMode.Interactive)  # Тема
        hdr.setStretchLastSection(False)
        self.tbl_pkgs.setColumnWidth(0, 28)
        self.tbl_pkgs.setColumnWidth(2, 140)
        self.tbl_pkgs.setColumnWidth(self._COL_THEME, 150)
        # Перенос имени зависит от текущей ширины «Название» → пересчитываем высоту
        # строк при её изменении (в т.ч. при растяжении окна). Дебаунс, чтобы не
        # дёргать на каждый пиксель во время перетаскивания.
        self._rowfit_timer = QTimer(self)
        self._rowfit_timer.setSingleShot(True)
        self._rowfit_timer.timeout.connect(self.tbl_pkgs.resizeRowsToContents)
        hdr.sectionResized.connect(self._on_name_section_resized)
        self.tbl_pkgs.itemSelectionChanged.connect(self._on_pkg_selection_changed)
        # Клик в пустую область (ниже последней строки) снимает выделение —
        # без этого детальная карточка справа так и оставалась висеть.
        self.tbl_pkgs.viewport().installEventFilter(self)
        # ПКМ на строке пака — чёрный список (пак целиком / всех его авторов).
        self.tbl_pkgs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_pkgs.customContextMenuRequested.connect(self._on_pkg_context_menu)
        split.addWidget(self.tbl_pkgs)

        # QTextBrowser (не QLabel) — чтобы текст карточки можно было выделять
        # мышью и копировать как обычно (Ctrl+C / контекстное меню «Копировать»);
        # у него уже есть собственный скролл, отдельная QScrollArea не нужна.
        # Пусто, пока ничего не выбрано — никакой подсказки-заглушки тут не
        # должно быть (см. _on_pkg_selection_changed).
        self.pkg_detail = QTextBrowser()
        self.pkg_detail.setOpenExternalLinks(False)
        self.pkg_detail.setFrameShape(QFrame.Shape.NoFrame)
        # Клик по пустому месту НИЖЕ текста карточки снимает выделение пака
        # (закрывает карточку) — так же, как клик по пустой области таблицы.
        self.pkg_detail.viewport().installEventFilter(self)
        split.addWidget(self.pkg_detail)
        split.setSizes([700, 400])
        self._pkg_split = split
        self._pkg_det_wrap = self.pkg_detail
        # Пока ничего не выбрано, карточке нечего показывать — прячем панель
        # целиком, чтобы таблица заняла всю ширину (не оставлять пустое место).
        self.pkg_detail.setVisible(False)
        left.addWidget(split, 1)

        det_btns = QHBoxLayout()
        self.btn_open_link = QPushButton("Открыть на sibrowser.ru")
        self.btn_open_link.setIcon(get_icon('fa5s.external-link-alt'))
        self.btn_open_link.clicked.connect(self._open_selected_link)
        self.btn_open_link.setEnabled(False)
        det_btns.addWidget(self.btn_open_link)
        self.btn_show_questions = QPushButton("Показать вопросы и ответы")
        self.btn_show_questions.setIcon(get_icon('fa5s.book-open'))
        self.btn_show_questions.clicked.connect(self._show_selected_questions)
        self.btn_show_questions.setEnabled(False)
        det_btns.addWidget(self.btn_show_questions)
        self.btn_mark_played = QPushButton("Уже сыграно — убрать из списка")
        self.btn_mark_played.setIcon(get_icon('fa5s.check-circle'))
        self.btn_mark_played.setToolTip(
            "Скрыть пак из основного списка — он попадёт в «Сыгранные пакеты» "
            "в фильтрах справа, откуда его можно вернуть обратно.")
        self.btn_mark_played.clicked.connect(self._mark_selected_played)
        self.btn_mark_played.setEnabled(False)
        det_btns.addWidget(self.btn_mark_played)
        det_btns.addStretch(1)
        # «Удалить пак» — активна только когда выбран УЖЕ скачанный пак; удаляет
        # его .siq и медиа с диска (см. _delete_selected_siq). Рядом с ней —
        # уменьшенная кнопка скачивания отмеченных.
        self.btn_delete_siq = QPushButton("Удалить пак")
        self.btn_delete_siq.setIcon(get_icon('fa5s.trash', color='#f38ba8'))
        self.btn_delete_siq.setToolTip(
            "Удалить скачанный .siq выбранного пака и его медиа с диска "
            "(статистика в базе останется). Доступно для скачанных паков.")
        self.btn_delete_siq.clicked.connect(self._delete_selected_siq)
        self.btn_delete_siq.setEnabled(False)
        det_btns.addWidget(self.btn_delete_siq)
        self.btn_bulk_dl = QPushButton("Скачать .siq")
        self.btn_bulk_dl.setIcon(get_icon('fa5s.download'))
        self.btn_bulk_dl.setToolTip("Скачать .siq всех отмеченных галочками паков.")
        self.btn_bulk_dl.clicked.connect(self._bulk_download)
        det_btns.addWidget(self.btn_bulk_dl)
        left.addLayout(det_btns)

        body.addLayout(left, 1)

        # ── Правая колонка: сбор данных + фильтры (фикс. ширина, скролл) ────
        self._build_packages_settings_panel(body)

        self.subtabs.addTab(page, "Пакеты")

    def _build_packages_settings_panel(self, body):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(2, 2, 8, 2)
        pv.setSpacing(12)

        pv.addWidget(self._build_collect_group())

        # ── Фильтры отображения уже собранных паков ─────────────────────────
        filt_box = QGroupBox("Фильтры")
        fl = QGridLayout(filt_box)

        # Чекбоксы группами по 2 в ряд — при узкой панели справа один длинный
        # ряд из 3-4 чекбоксов не помещается по ширине.
        self._len_checks = {}
        fl.addWidget(QLabel("Группа по длине:"), 0, 0, 1, 4)
        len_grid = QGridLayout()
        for i, g in enumerate(_LEN_GROUPS):
            chk = QCheckBox(g)
            chk.setChecked(g in ("Полные", "Большие"))
            chk.toggled.connect(self._refresh_packages_table)
            self._len_checks[g] = chk
            len_grid.addWidget(chk, i // 2, i % 2)
        fl.addLayout(len_grid, 1, 0, 1, 4)

        self._diff_checks = {}
        fl.addWidget(QLabel("Сложность:"), 2, 0, 1, 4)
        diff_grid = QGridLayout()
        for i, d in enumerate(_DIFF_LEVELS):
            chk = QCheckBox(d)
            chk.setChecked(True)
            chk.setIcon(get_icon('fa5s.circle', color=_DIFF_COLORS[d]))
            chk.toggled.connect(self._refresh_packages_table)
            self._diff_checks[d] = chk
            diff_grid.addWidget(chk, i // 2, i % 2)
        fl.addLayout(diff_grid, 3, 0, 1, 4)

        self.chk_only_siq = QCheckBox("Только скачанные (.siq)")
        self.chk_only_siq.toggled.connect(self._refresh_packages_table)
        fl.addWidget(self.chk_only_siq, 4, 0, 1, 4)

        fl.addWidget(QLabel("Мин. % завершения:"), 5, 0, 1, 4)
        self.sl_min_comp = QSlider(Qt.Orientation.Horizontal)
        self.sl_min_comp.setRange(0, 100)
        self.sl_min_comp.valueChanged.connect(self._refresh_packages_table)
        fl.addWidget(self.sl_min_comp, 6, 0, 1, 4)

        fl.addWidget(QLabel("Мин. игр начато:"), 7, 0, 1, 4)
        self.sp_min_started = QSpinBox()
        self.sp_min_started.setRange(0, 1_000_000)
        self.sp_min_started.setValue(100)
        self.sp_min_started.setSingleStep(10)
        self.sp_min_started.valueChanged.connect(self._refresh_packages_table)
        fl.addWidget(self.sp_min_started, 8, 0, 1, 4)

        fl.addWidget(QLabel("Категория:"), 9, 0, 1, 4)
        self.cmb_cat_filter = QComboBox()
        self.cmb_cat_filter.addItem(_ANY_TOPIC)
        self.cmb_cat_filter.currentIndexChanged.connect(self._refresh_packages_table)
        fl.addWidget(self.cmb_cat_filter, 10, 0, 1, 4)
        fl.addWidget(QLabel("Мин. % категории:"), 11, 0, 1, 4)
        self.sl_cat_min = QSlider(Qt.Orientation.Horizontal)
        self.sl_cat_min.setRange(0, 100)
        self.sl_cat_min.setValue(50)
        self.sl_cat_min.valueChanged.connect(self._refresh_packages_table)
        fl.addWidget(self.sl_cat_min, 12, 0, 1, 4)

        fl.addWidget(QLabel("Поиск (название/автор/тема):"), 13, 0, 1, 4)
        self.ed_search = QLineEdit()
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self._refresh_packages_table)
        fl.addWidget(self.ed_search, 14, 0, 1, 4)

        self.chk_show_played = QCheckBox("Показывать сыгранные")
        self.chk_show_played.setToolTip(
            "Паки, отмеченные как «уже сыграно», по умолчанию скрыты из списка — "
            "включите, чтобы снова их увидеть.")
        self.chk_show_played.toggled.connect(self._refresh_packages_table)
        fl.addWidget(self.chk_show_played, 15, 0, 1, 4)

        pv.addWidget(filt_box)
        pv.addWidget(self._build_blacklist_group())
        pv.addWidget(self._build_pkg_blacklist_group())
        pv.addWidget(self._build_played_group())
        pv.addStretch(1)

        scroll.setWidget(panel)
        # Раньше тут были широкие ряды в несколько виджетов — весь блок
        # занимал чуть ли не половину окна. Теперь всё в один узкий столбец
        # (метка над полем), поэтому и фиксированную ширину держим вдвое уже.
        _need = max(panel.minimumSizeHint().width(), 220)
        _sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
        scroll.setFixedWidth(_need + _sb + 12)
        body.addWidget(scroll)

    def _build_blacklist_group(self) -> QGroupBox:
        box = QGroupBox("Чёрный список авторов")
        v = QVBoxLayout(box)
        lbl = QLabel("Паки этих авторов пропускаются при сборе и не "
                     "показываются в таблице.")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.lst_blacklist = QListWidget()
        self.lst_blacklist.addItems(self._author_blacklist)
        self.lst_blacklist.setMaximumHeight(110)
        v.addWidget(self.lst_blacklist)

        self.ed_blacklist = QLineEdit()
        self.ed_blacklist.setPlaceholderText("Никнейм автора…")
        self.ed_blacklist.returnPressed.connect(self._add_blacklist_author)
        v.addWidget(self.ed_blacklist)

        row = QHBoxLayout()
        btn_add = QPushButton("Добавить")
        btn_add.setIcon(get_icon('fa5s.plus'))
        btn_add.clicked.connect(self._add_blacklist_author)
        row.addWidget(btn_add)
        btn_del = QPushButton("Удалить")
        btn_del.setIcon(get_icon('fa5s.trash'))
        btn_del.clicked.connect(self._remove_blacklist_author)
        row.addWidget(btn_del)
        v.addLayout(row)
        return box

    def _add_blacklist_author(self):
        name = self.ed_blacklist.text().strip()
        if not name:
            return
        self._blacklist_author_by_name(name)
        self.ed_blacklist.clear()

    def _blacklist_author_by_name(self, name: str):
        """Общая логика добавления автора в чёрный список — используется и
        полем ввода в панели фильтров, и пунктом контекстного меню на строке
        пака (см. _on_pkg_context_menu)."""
        name = (name or "").strip()
        if not name or any(a.lower() == name.lower() for a in self._author_blacklist):
            return
        self._author_blacklist.append(name)
        self.lst_blacklist.addItem(name)
        sg_config.save_author_blacklist(self._author_blacklist)
        self._refresh_packages_table()

    def _remove_blacklist_author(self):
        for item in self.lst_blacklist.selectedItems():
            name = item.text()
            self._author_blacklist = [a for a in self._author_blacklist if a != name]
            self.lst_blacklist.takeItem(self.lst_blacklist.row(item))
        sg_config.save_author_blacklist(self._author_blacklist)
        self._refresh_packages_table()

    def _build_played_group(self) -> QGroupBox:
        box = QGroupBox("Сыгранные пакеты")
        v = QVBoxLayout(box)
        lbl = QLabel("Паки, отмеченные кнопкой «Уже сыграно» у выбранного пака, "
                     "скрыты из основного списка (см. чекбокс «Показывать "
                     "сыгранные» в фильтрах).")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.lst_played = QListWidget()
        self.lst_played.setMaximumHeight(110)
        v.addWidget(self.lst_played)
        btn_unplay = QPushButton("Вернуть в список")
        btn_unplay.setIcon(get_icon('fa5s.undo'))
        btn_unplay.clicked.connect(self._unmark_played)
        v.addWidget(btn_unplay)
        return box

    def _refresh_played_list(self):
        self.lst_played.clear()
        if self._pkgs_df is None or self._pkgs_df.empty or not self._played_ids:
            return
        names = self._pkgs_df.set_index("id")["name"]
        for pid in sorted(self._played_ids):
            name = names.get(pid, f"#{pid}")
            item = QListWidgetItem(str(name))
            item.setData(Qt.ItemDataRole.UserRole, int(pid))
            self.lst_played.addItem(item)

    def _mark_selected_played(self):
        r = self._selected_pkg_row()
        if r is None:
            return
        self._played_ids.add(int(r["id"]))
        sg_config.save_played_packages(sorted(self._played_ids))
        self._refresh_played_list()
        self._refresh_packages_table()

    def _unmark_played(self):
        changed = False
        for item in self.lst_played.selectedItems():
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid in self._played_ids:
                self._played_ids.discard(pid)
                changed = True
        if changed:
            sg_config.save_played_packages(sorted(self._played_ids))
            self._refresh_played_list()
            self._refresh_packages_table()

    def _build_pkg_blacklist_group(self) -> QGroupBox:
        box = QGroupBox("Чёрный список пакетов")
        v = QVBoxLayout(box)
        lbl = QLabel("Паки, добавленные сюда через ПКМ на строке пака "
                     "(«Добавить пак в чёрный список»), больше не показываются "
                     "в списке слева.")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.lst_pkg_blacklist = QListWidget()
        self.lst_pkg_blacklist.setMaximumHeight(110)
        v.addWidget(self.lst_pkg_blacklist)
        btn_unblacklist = QPushButton("Убрать из чёрного списка")
        btn_unblacklist.setIcon(get_icon('fa5s.undo'))
        btn_unblacklist.clicked.connect(self._unblacklist_selected_packages)
        v.addWidget(btn_unblacklist)
        return box

    def _refresh_pkg_blacklist_list(self):
        self.lst_pkg_blacklist.clear()
        if self._pkgs_df is None or self._pkgs_df.empty or not self._pkg_blacklist:
            return
        names = self._pkgs_df.set_index("id")["name"]
        for pid in sorted(self._pkg_blacklist):
            name = names.get(pid, f"#{pid}")
            item = QListWidgetItem(str(name))
            item.setData(Qt.ItemDataRole.UserRole, int(pid))
            self.lst_pkg_blacklist.addItem(item)

    def _blacklist_package(self, package_id: int):
        self._pkg_blacklist.add(int(package_id))
        sg_config.save_package_blacklist(sorted(self._pkg_blacklist))
        self._refresh_pkg_blacklist_list()
        self._refresh_packages_table()

    def _unblacklist_selected_packages(self):
        changed = False
        for item in self.lst_pkg_blacklist.selectedItems():
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid in self._pkg_blacklist:
                self._pkg_blacklist.discard(pid)
                changed = True
        if changed:
            sg_config.save_package_blacklist(sorted(self._pkg_blacklist))
            self._refresh_pkg_blacklist_list()
            self._refresh_packages_table()

    def _build_collect_group(self) -> QGroupBox:
        # Всё в один узкий столбец (метка над полем) — панель справа теперь
        # вдвое уже, широкие ряды из нескольких виджетов сюда не помещаются.
        box = QGroupBox("Сбор данных")
        v = QVBoxLayout(box)
        lbl_hint = QLabel("Уже собранные пакеты (по названию) пропускаются автоматически.")
        lbl_hint.setWordWrap(True)
        v.addWidget(lbl_hint)

        self.rb_mode_dl = QRadioButton("По скачиваниям")
        self.rb_mode_dl.setIcon(get_icon('fa5s.chart-line'))
        self.rb_mode_dl.setChecked(True)
        v.addWidget(self.rb_mode_dl)
        self.rb_mode_date = QRadioButton("По дате публикации")
        self.rb_mode_date.setIcon(get_icon('fa5s.calendar-alt'))
        v.addWidget(self.rb_mode_date)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.rb_mode_dl)
        self._mode_group.addButton(self.rb_mode_date)

        v.addWidget(QLabel("Минимум скачиваний:"))
        self.sp_min_dl = QSpinBox(); self.sp_min_dl.setRange(0, 1_000_000)
        self.sp_min_dl.setValue(150); self.sp_min_dl.setSingleStep(50)
        v.addWidget(self.sp_min_dl)

        v.addWidget(QLabel("Максимум новых паков за раз:"))
        self.sp_max_new = QSpinBox(); self.sp_max_new.setRange(5, 1000)
        self.sp_max_new.setValue(50); self.sp_max_new.setSingleStep(5)
        v.addWidget(self.sp_max_new)

        lbl_min_started = QLabel("Минимум начатых игр:")
        lbl_min_started.setToolTip(
            "Паки, в которые сыграли меньше N раз, пропускаются. Скачивания на "
            "сайте легко накрутить, а начатые игры — нет.")
        v.addWidget(lbl_min_started)
        self.sp_min_started_collect = QSpinBox(); self.sp_min_started_collect.setRange(0, 1_000_000)
        self.sp_min_started_collect.setValue(100); self.sp_min_started_collect.setSingleStep(10)
        v.addWidget(self.sp_min_started_collect)

        lbl_start_page = QLabel("Начать со страницы (0 — продолжить с прошлого раза):")
        lbl_start_page.setWordWrap(True)
        lbl_start_page.setToolTip(
            "По умолчанию сбор продолжается со страницы каталога, на которой "
            "остановился прошлый сбор с теми же режимом и темой. Поставьте здесь "
            "свою страницу, чтобы начать именно с неё, или нажмите «Сбросить "
            "прогресс», чтобы в следующий раз начать заново с первой страницы.")
        v.addWidget(lbl_start_page)
        row_start_page = QHBoxLayout()
        self.sp_start_page = QSpinBox()
        self.sp_start_page.setRange(0, 100_000)
        self.sp_start_page.setSpecialValueText("авто")
        row_start_page.addWidget(self.sp_start_page, 1)
        self.btn_reset_progress = QPushButton("Сбросить прогресс")
        self.btn_reset_progress.setIcon(get_icon('fa5s.undo'))
        self.btn_reset_progress.setToolTip(
            "Забыть, докуда долистали каталог для текущих режима/темы — следующий "
            "сбор начнётся с первой страницы.")
        self.btn_reset_progress.clicked.connect(self._reset_collect_progress)
        row_start_page.addWidget(self.btn_reset_progress)
        v.addLayout(row_start_page)

        self.chk_do_siq = QCheckBox("Скачивать .siq и разбирать вопросы/ответы/медиа")
        self.chk_do_siq.setToolTip(
            "Без этого собираются только темы и статистика (быстро). С этим — "
            "качаются файлы, извлекаются вопросы, ответы и медиаконтент.")
        v.addWidget(self.chk_do_siq)

        # период (только режим «по дате»)
        v.addWidget(QLabel("Период:"))
        self.cmb_period = QComboBox()
        self.cmb_period.addItems(list(_PERIODS) + ["Своя дата"])
        self.cmb_period.setCurrentText("Месяц")
        v.addWidget(self.cmb_period)
        self.de_custom = QDateEdit()
        self.de_custom.setCalendarPopup(True)
        self.de_custom.setDisplayFormat("dd.MM.yyyy")
        self.de_custom.setDate(_dt.date.today())
        v.addWidget(self.de_custom)

        def _sync_date_visibility():
            is_date_mode = self.rb_mode_date.isChecked()
            for w in (self.cmb_period, self.de_custom):
                w.setVisible(is_date_mode)
            self.de_custom.setVisible(is_date_mode and self.cmb_period.currentText() == "Своя дата")
        self._sync_date_visibility = _sync_date_visibility   # re-called after restoring settings
        self.rb_mode_dl.toggled.connect(_sync_date_visibility)
        self.cmb_period.currentTextChanged.connect(_sync_date_visibility)
        _sync_date_visibility()

        # фильтр по теме
        lbl_topic = QLabel("Фильтр по теме (необязательно):")
        lbl_topic.setWordWrap(True)
        v.addWidget(lbl_topic)
        self.cmb_topic = QComboBox()
        self.cmb_topic.addItem(_ANY_TOPIC)
        self.cmb_topic.addItems(list(sg_config.CATEGORY_SLUGS.keys()))
        self.cmb_topic.setToolTip(
            "Например «Аниме» — сбор пойдёт по странице этой темы на sibrowser и "
            "оставит только паки, где её доля не меньше порога снизу.")
        v.addWidget(self.cmb_topic)

        topic_min_row = QHBoxLayout()
        topic_min_row.addWidget(QLabel("Мин. % темы:"))
        self.sl_topic_min = QSlider(Qt.Orientation.Horizontal)
        self.sl_topic_min.setRange(5, 100)
        self.sl_topic_min.setValue(50)
        self.lbl_topic_min = QLabel("50")
        self.sl_topic_min.valueChanged.connect(lambda v: self.lbl_topic_min.setText(str(v)))
        topic_min_row.addWidget(self.sl_topic_min, 1)
        topic_min_row.addWidget(self.lbl_topic_min)
        v.addLayout(topic_min_row)

        self.btn_start_collect = QPushButton("Начать сбор")
        self.btn_start_collect.setIcon(get_icon('fa5s.play', color='#11111b'))
        self.btn_start_collect.setObjectName("b_run")
        self.btn_start_collect.clicked.connect(self._start_collect)
        v.addWidget(self.btn_start_collect)
        self.btn_stop = QPushButton("Стоп")
        self.btn_stop.setIcon(get_icon('fa5s.stop'))
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_job)
        v.addWidget(self.btn_stop)

        self.progress = QProgressBar()
        self.progress.setFormat("Ожидание")
        v.addWidget(self.progress)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color:#a6adc8;")
        v.addWidget(self.lbl_status)

        v.addWidget(_hline())

        # автор
        v.addWidget(QLabel("Собрать все паки автора:"))
        self.ed_author = QLineEdit()
        v.addWidget(self.ed_author)
        self.btn_collect_author = QPushButton("Собрать паки автора")
        self.btn_collect_author.setIcon(get_icon('fa5s.star'))
        self.btn_collect_author.clicked.connect(self._start_collect_author)
        v.addWidget(self.btn_collect_author)

        v.addWidget(_hline())

        self.chk_only_missing = QCheckBox("Только где метрик ещё нет")
        self.chk_only_missing.setChecked(True)
        v.addWidget(self.chk_only_missing)
        self.btn_refresh_stats = QPushButton("Обновить статистику")
        self.btn_refresh_stats.setIcon(get_icon('fa5s.sync'))
        self.btn_refresh_stats.clicked.connect(self._start_refresh_stats)
        v.addWidget(self.btn_refresh_stats)
        self.btn_recompute_dur = QPushButton("Пересчитать длительность")
        self.btn_recompute_dur.setIcon(get_icon('fa5s.film'))
        self.btn_recompute_dur.clicked.connect(self._start_recompute_durations)
        v.addWidget(self.btn_recompute_dur)

        return box

    # ── Запуск фоновых задач сбора ───────────────────────────────────────────
    def _job_running(self) -> bool:
        return self._active_job is not None

    def _begin_job(self, task):
        self._active_job = task
        self.btn_stop.setEnabled(True)
        self.btn_start_collect.setEnabled(False)
        self.btn_collect_author.setEnabled(False)
        self.btn_refresh_stats.setEnabled(False)
        self.btn_recompute_dur.setEnabled(False)
        self.progress.setValue(0)
        self._pool.start(task)

    def _end_job(self):
        self._active_job = None
        self.btn_stop.setEnabled(False)
        self.btn_start_collect.setEnabled(True)
        self.btn_collect_author.setEnabled(True)
        self.btn_refresh_stats.setEnabled(True)
        self.btn_recompute_dur.setEnabled(True)

    def _stop_job(self):
        if self._active_job is not None:
            self._active_job.stop()
            self.lbl_status.setText("Останавливаю…")

    def _reset_collect_progress(self):
        mode = "downloads" if self.rb_mode_dl.isChecked() else "date"
        topic = self.cmb_topic.currentText()
        category_slug = sg_config.CATEGORY_SLUGS.get(topic) if topic != _ANY_TOPIC else None
        sg_config.set_cached_page(mode, category_slug, 1)
        self.sp_start_page.setValue(0)
        self.lbl_status.setText(
            "Прогресс сброшен — следующий сбор (для текущих режима/темы) начнётся с первой страницы.")

    def _on_job_progress(self, done, total, msg):
        frac = int(min(done / total, 1.0) * 100) if total else 0
        self.progress.setValue(frac)
        self.progress.setFormat(f"Найдено: {done}")
        self.lbl_status.setText(msg)
        self._log(f"Поиск пакетов: {msg}")

    def _blacklist_set(self) -> set:
        return {a.strip().lower() for a in self._author_blacklist if a.strip()}

    def _on_package_added(self, pid: int):
        """Пакет только что сохранён в БД фоновой задачей сбора — подхватываем
        его в таблицу сразу, не дожидаясь конца всего сбора. Перечитывание
        всей БД дебаунсится (см. _live_refresh_now), чтобы не дёргать таблицу
        на каждый отдельный пакет при быстром сборе."""
        if not self._live_refresh_timer.isActive():
            self._live_refresh_timer.start(500)

    def _live_refresh_now(self):
        try:
            with sg_db.connect() as conn:
                self._pkgs_df = sg_analysis.load_packages(conn)
        except Exception:
            return
        self._refresh_packages_table()

    def _start_collect(self):
        if self._job_running():
            return
        mode = "downloads" if self.rb_mode_dl.isChecked() else "date"
        cutoff_date = None
        if mode == "date":
            period = self.cmb_period.currentText()
            if period == "Своя дата":
                cutoff_date = self.de_custom.date().toString("yyyy-MM-dd")
            else:
                import datetime as _dt
                cd = _dt.date.today() - _dt.timedelta(days=_PERIODS[period])
                cutoff_date = cd.isoformat()
        topic = self.cmb_topic.currentText()
        category_slug = sg_config.CATEGORY_SLUGS.get(topic) if topic != _ANY_TOPIC else None
        category_min_pct = self.sl_topic_min.value() if category_slug else 0
        start_page = self.sp_start_page.value() or sg_config.get_cached_page(mode, category_slug)
        self._last_collect_key = (mode, category_slug)

        task = _JobTask(
            sg_collector.collect,
            min_downloads=int(self.sp_min_dl.value()),
            max_new=int(self.sp_max_new.value()),
            download_siq=self.chk_do_siq.isChecked(),
            mode=mode, cutoff_date=cutoff_date,
            min_started=int(self.sp_min_started_collect.value()),
            category_slug=category_slug, category_min_pct=category_min_pct,
            author_blacklist=self._blacklist_set(),
            start_page=start_page,
        )
        task.signals.progress.connect(self._on_job_progress)
        task.signals.package_added.connect(self._on_package_added)
        task.signals.finished.connect(self._on_collect_finished)
        task.signals.failed.connect(self._on_job_failed)
        if start_page > 1:
            self.lbl_status.setText(f"Продолжаю с ранее сохранённой страницы {start_page}…")
        self._begin_job(task)

    def _on_collect_finished(self, result):
        self._end_job()
        key = getattr(self, "_last_collect_key", None)
        if key is not None:
            sg_config.set_cached_page(key[0], key[1], result.get("last_page", 1))
        extra = (f" · отсеяно по мин. играм: {result['skipped_low_games']}"
                 if result.get("skipped_low_games") else "")
        extra += (f" · отсеяно по чёрному списку: {result['skipped_blacklisted']}"
                  if result.get("skipped_blacklisted") else "")
        last_bit = ""
        if result.get("last_name"):
            date_bit = f" от {result['last_date']}" if result.get("last_date") else ""
            last_bit = f" · последний просмотренный пак: «{result['last_name']}»{date_bit}"
        msg = (f"Сбор завершён — новых: {result['new']} · со статистикой: "
               f"{result['with_stats']} · без статистики: {result['no_stats']} · "
               f".siq: {result['with_siq']}{extra}{last_bit}")
        self.progress.setValue(100)
        self.lbl_status.setText(msg)
        self._log(f"Поиск пакетов: {msg}")
        self._reload_data()

    def _on_job_failed(self, err):
        self._end_job()
        self.lbl_status.setText(f"Ошибка: {err}")
        self._log(f"Поиск пакетов: ошибка сбора: {err}")

    def _start_collect_author(self):
        if self._job_running():
            return
        author = self.ed_author.text().strip()
        if not author:
            return
        self._last_collect_key = None  # у collect_author нет страничного кэша
        task = _JobTask(sg_collector.collect_author, author=author,
                        download_siq=self.chk_do_siq.isChecked(),
                        author_blacklist=self._blacklist_set())
        task.signals.progress.connect(self._on_job_progress)
        task.signals.package_added.connect(self._on_package_added)
        task.signals.finished.connect(self._on_collect_finished)
        task.signals.failed.connect(self._on_job_failed)
        self._begin_job(task)

    def _start_refresh_stats(self):
        if self._job_running():
            return
        task = _JobTask(sg_collector.refresh_stats,
                        only_missing=self.chk_only_missing.isChecked())
        task.signals.progress.connect(self._on_job_progress)

        def _done(result):
            self._end_job()
            msg = f"Обновление статистики: проверено {result['checked']} · со статистикой {result['updated']}"
            self.lbl_status.setText(msg)
            self._log(f"Поиск пакетов: {msg}")
            self._reload_data()
        task.signals.finished.connect(_done)
        task.signals.failed.connect(self._on_job_failed)
        self._begin_job(task)

    def _start_recompute_durations(self):
        if self._job_running():
            return
        task = _JobTask(sg_collector.recompute_durations)
        task.signals.progress.connect(self._on_job_progress)

        def _done(result):
            self._end_job()
            msg = f"Длительность: проверено {result['checked']} · посчитано {result['updated']}"
            self.lbl_status.setText(msg)
            self._log(f"Поиск пакетов: {msg}")
            self._reload_data()
        task.signals.finished.connect(_done)
        task.signals.failed.connect(self._on_job_failed)
        self._begin_job(task)

    # ── Фильтрация и таблица паков ───────────────────────────────────────────
    def _filtered_packages_df(self):
        import pandas as pd
        df = self._pkgs_df
        if df is None or df.empty:
            return df if df is not None else pd.DataFrame()

        view = df[df["has_stats"] == 1].copy()
        if self._played_ids and not self.chk_show_played.isChecked():
            view = view[~view["id"].isin(self._played_ids)]
        if self._pkg_blacklist:
            view = view[~view["id"].isin(self._pkg_blacklist)]
        groups = [g for g, chk in self._len_checks.items() if chk.isChecked()]
        if groups:
            view = view[view["length_group"].isin(groups)]
        diffs = [d for d, chk in self._diff_checks.items() if chk.isChecked()]
        if diffs:
            view = view[view["difficulty"].isin(diffs)]
        if self.chk_only_siq.isChecked():
            view = view[view["siq_downloaded"] == 1]
        if self._author_blacklist:
            needles = [a.lower() for a in self._author_blacklist]
            view = view[~view["authors_display"].fillna("").str.lower().apply(
                lambda s: any(n in s for n in needles))]
        if self.sl_min_comp.value() > 0:
            view = view[view["completion_pct"].fillna(-1) >= self.sl_min_comp.value()]
        if self.sp_min_started.value() > 0:
            view = view[view["started_games"].fillna(0) >= self.sp_min_started.value()]

        cat_sel = self.cmb_cat_filter.currentText()
        cat_min = self.sl_cat_min.value()
        if cat_sel != _ANY_TOPIC:
            view = view[view["cat_map"].apply(lambda m: m.get(cat_sel, 0) >= cat_min)]

        needle = self.ed_search.text().strip().lower()
        if needle:
            mask = (view["name"].str.lower().str.contains(needle, na=False)
                    | view["authors_display"].str.lower().str.contains(needle, na=False))
            try:
                with sg_db.connect() as conn:
                    ids = pd.read_sql_query(
                        "SELECT DISTINCT package_id FROM themes WHERE lower(name) LIKE ?",
                        conn, params=(f"%{needle}%",))["package_id"].tolist()
            except Exception:
                ids = []
            view = view[mask | view["id"].isin(ids)]

        return view.sort_values("completion_rate", ascending=False, na_position="last")

    def _refresh_packages_table(self, *args):
        if self._pkgs_df is None:
            return
        # категории для комбобокса фильтра (динамически из уже собранных паков)
        if self._pending_cat_filter is not None:
            # Восстановленное после перезапуска значение — список категорий на тот
            # момент ещё не заполнен реальными данными (см. _pending_cat_filter).
            cur_cat = self._pending_cat_filter
            self._pending_cat_filter = None
        else:
            cur_cat = self.cmb_cat_filter.currentText()
        cats = sg_analysis.category_names(self._pkgs_df) if not self._pkgs_df.empty else []
        self.cmb_cat_filter.blockSignals(True)
        self.cmb_cat_filter.clear()
        self.cmb_cat_filter.addItem(_ANY_TOPIC)
        self.cmb_cat_filter.addItems(cats)
        idx = self.cmb_cat_filter.findText(cur_cat)
        self.cmb_cat_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_cat_filter.blockSignals(False)

        view = self._filtered_packages_df()
        self._pkg_view_df = view
        t = self.tbl_pkgs
        t.setSortingEnabled(False)
        t.setRowCount(0)
        for _, r in view.iterrows():
            row = t.rowCount()
            t.insertRow(row)

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            chk_item.setData(Qt.ItemDataRole.UserRole, int(r["id"]))
            t.setItem(row, 0, chk_item)

            name_item = QTableWidgetItem(str(r["name"]))
            # Галочка «скачан» / бегущий процент рисует _PkgNameDelegate; своего
            # tooltip у ячейки НЕТ (иначе всплывает синее системное окно, которое
            # запрещено в проекте — имя и так переносится по словам целиком).
            name_item.setData(_PkgNameDelegate.DownloadedRole, r.get("siq_downloaded") == 1)
            t.setItem(row, 1, name_item)
            t.setItem(row, 2, QTableWidgetItem(str(r.get("authors_display") or "")))
            dp = r.get("date_published")
            dp_key = str(dp)[:10] if (dp is not None and dp == dp) else None
            t.setItem(row, 3, _NumItem(_fmt_date(dp), dp_key))
            qc = r.get("question_count")
            t.setItem(row, 4, _NumItem("—" if qc != qc or qc is None else str(int(qc)), qc or 0))
            ap = r.get("answer_pct")
            diff = r.get("difficulty")
            diff_item = _NumItem(diff if isinstance(diff, str) else "—", ap if ap == ap else -1)
            if diff in _DIFF_COLORS:
                diff_item.setForeground(QColor(_DIFF_COLORS[diff]))
            t.setItem(row, 5, diff_item)
            t.setItem(row, 6, QTableWidgetItem(str(r.get("duration_str") or "—")))
            dl = r.get("download_count")
            t.setItem(row, 7, _NumItem("—" if dl != dl or dl is None else str(int(dl)), dl or 0))
            comp = r.get("completion_pct")
            t.setItem(row, 8, _NumItem(_fmt_pct(comp, 1), comp if comp == comp else -1))
            rank = r.get("completion_rank_in_group")
            t.setItem(row, 9, _NumItem("—" if rank != rank else f"{rank:.0f}", rank if rank == rank else -1))
            bal = r.get("balance_index")
            t.setItem(row, 10, _NumItem("—" if bal != bal else f"{bal:.0f}", bal if bal == bal else -1))
            t.setItem(row, 11, _NumItem(_fmt_pct(ap, 0), ap if ap == ap else -1))
            cp = r.get("correct_pct")
            t.setItem(row, 12, _NumItem(_fmt_pct(cp, 0), cp if cp == cp else -1))
            sg_ = r.get("started_games")
            t.setItem(row, 13, _NumItem("—" if sg_ != sg_ or sg_ is None else str(int(sg_)), sg_ or 0))
            t.setItem(row, 14, QTableWidgetItem(_dominant_category(r.get("categories"))))
            t.setItem(row, 15, QTableWidgetItem(str(r.get("length_group") or "")))

            # Доминирующая тема пака → цветная полоска слева от строки (см.
            # _AccentBarDelegate/_CATEGORY_ACCENT): красная у аниме, фиолетовая
            # у музыки. Роль лежит на чек-ячейке (колонка 0, там же id пака).
            cats = r.get("categories") if isinstance(r.get("categories"), list) else []
            top_cat = _top_category(cats)
            accent = _CATEGORY_ACCENT.get((top_cat or {}).get("name"))
            if accent:
                chk_item.setData(_AccentBarDelegate.AccentRole, accent)
        t.setSortingEnabled(True)
        t.resizeRowsToContents()
        self.lbl_pkg_count.setText(f"Найдено пакетов: {len(view)}")

    def _on_name_section_resized(self, index, _old, _new):
        # Перенос имени по словам зависит от ширины колонки «Название» — при её
        # изменении пересчитываем высоту строк (дебаунс через _rowfit_timer).
        if index == self._COL_NAME:
            self._rowfit_timer.start(60)

    def _on_pkg_context_menu(self, pos):
        """ПКМ на строке пака: добавить пак и/или его авторов в чёрный список."""
        index = self.tbl_pkgs.indexAt(pos)
        if not index.isValid():
            return
        # Выделяем кликнутую строку (не обязательно совпадает с уже выбранной) —
        # даёт и корректный _selected_pkg_row() ниже, и открывает карточку пака,
        # как при обычном ЛКМ-клике.
        self.tbl_pkgs.selectRow(index.row())
        r = self._selected_pkg_row()
        if r is None:
            return
        pid = int(r["id"])
        name = str(r["name"])
        authors = r["authors"] if isinstance(r.get("authors"), list) else []

        menu = QMenu(self)
        act_pkg = menu.addAction(get_icon('fa5s.ban'), f"Добавить «{name}» в чёрный список")
        act_pkg.triggered.connect(lambda: self._blacklist_package(pid))

        if authors:
            menu.addSeparator()
            if len(authors) == 1:
                act_auth = menu.addAction(
                    get_icon('fa5s.user-slash'), f"Добавить автора «{authors[0]}» в чёрный список")
                act_auth.triggered.connect(lambda a=authors[0]: self._blacklist_author_by_name(a))
            else:
                for a in authors:
                    act_auth = menu.addAction(
                        get_icon('fa5s.user-slash'), f"Добавить автора «{a}» в чёрный список")
                    act_auth.triggered.connect(lambda checked=False, a=a: self._blacklist_author_by_name(a))
        menu.exec(self.tbl_pkgs.viewport().mapToGlobal(pos))

    def _selected_pkg_row(self):
        """Строка выбранного пакета из _pkg_view_df по его id (а не по позиции
        строки в таблице) — таблица сортируется (setSortingEnabled), а порядок
        строк в _pkg_view_df при этом не меняется, так что искать по iloc[row]
        нельзя (после сортировки это была бы карточка совсем другого пакета)."""
        rows = self.tbl_pkgs.selectionModel().selectedRows() if self.tbl_pkgs.selectionModel() else []
        if not rows or self._pkg_view_df is None:
            return None
        row = rows[0].row()
        chk = self.tbl_pkgs.item(row, 0)
        if chk is None:
            return None
        pid = chk.data(Qt.ItemDataRole.UserRole)
        match = self._pkg_view_df[self._pkg_view_df["id"] == pid]
        if match.empty:
            return None
        return match.iloc[0]

    def eventFilter(self, obj, event):
        # Раздельные if (не один общий "obj is X and type == press" с elif) —
        # иначе НЕ-press событие (paint/resize/...) на первом viewport'е даёт
        # False у всего условия и проваливается в elif, где на раннем этапе
        # построения виджета (до создания pkg_detail) обращение к
        # self.pkg_detail упадёт AttributeError.
        if obj is self.tbl_pkgs.viewport():
            if (event.type() == QEvent.Type.MouseButtonPress
                    and not self.tbl_pkgs.indexAt(event.pos()).isValid()):
                self.tbl_pkgs.clearSelection()
        elif obj is self.pkg_detail.viewport():
            # Карточка часто длиннее видимой области (текст со скроллом), так
            # что "пустой области ниже текста" может вообще не быть видно —
            # сравнение с высотой документа тут не работает. Вместо этого
            # смотрим на ОТПУСКАНИЕ кнопки мыши: обычный клик (без протаскивания)
            # не оставляет выделения текста — значит, это не попытка что-то
            # скопировать, и карточку можно закрыть. Клик-перетаскивание, после
            # которого текст остался выделен (для копирования), не трогаем.
            if event.type() == QEvent.Type.MouseButtonRelease:
                if not self.pkg_detail.textCursor().hasSelection():
                    self.tbl_pkgs.clearSelection()
        elif (event.type() == QEvent.Type.MouseButtonPress
              and self.pkg_detail.isVisible()
              and isinstance(obj, QWidget)
              and obj.window() is self.window()
              and not self._click_in_panel(obj)):
            # Пока карточка открыта, фильтр стоит на всём приложении: клик по
            # ЛЮБОЙ области вне самой панели (и вне кнопок действий над паком)
            # закрывает карточку. Клик по строке таблицы уходит выше (там просто
            # переключается выбранный пак, а не закрывается).
            self.tbl_pkgs.clearSelection()
        return super().eventFilter(obj, event)

    def _click_in_panel(self, w) -> bool:
        """True, если клик пришёлся по самой карточке пака или по кнопкам действий
        над выбранным паком — их нажатие не должно закрывать карточку."""
        protected = (self.pkg_detail, self.btn_open_link, self.btn_show_questions,
                     self.btn_mark_played, self.btn_delete_siq, self.btn_bulk_dl)
        node = w
        while node is not None:
            if node in protected:
                return True
            node = node.parentWidget()
        return False

    def _set_app_click_filter(self, on: bool):
        """Ставит/снимает фильтр событий приложения (закрытие карточки кликом вне
        панели) — только пока карточка реально видна, чтобы зря не фильтровать
        всё приложение."""
        app = QApplication.instance()
        if app is None:
            return
        if on and not self._app_click_filter_on:
            app.installEventFilter(self)
            self._app_click_filter_on = True
        elif not on and self._app_click_filter_on:
            app.removeEventFilter(self)
            self._app_click_filter_on = False

    def _on_pkg_selection_changed(self):
        r = self._selected_pkg_row()
        has = r is not None
        self.btn_open_link.setEnabled(has)
        self.btn_show_questions.setEnabled(has)
        self.btn_mark_played.setEnabled(has)
        # «Удалить пак» — только когда выбран реально скачанный .siq.
        self.btn_delete_siq.setEnabled(bool(has and r.get("siq_downloaded") == 1))
        if not has:
            self.pkg_detail.setHtml("")
            self._pkg_det_wrap.setVisible(False)  # таблица занимает всю ширину
            self._set_app_click_filter(False)
            return
        self._pkg_det_wrap.setVisible(True)
        if self._pkg_split.sizes()[1] == 0:
            self._pkg_split.setSizes([700, 400])
        self.pkg_detail.setHtml(self._render_package_detail_html(r))
        self._set_app_click_filter(True)

    def _render_package_detail_html(self, r) -> str:
        import pandas as pd
        parts = [f"<h3>{icon_html('fa5s.box', color='#cdd6f4')} {_esc(r['name'])}</h3>"]
        if pd.notna(r.get("sibrowser_id")):
            parts.append(f"<p><b>sibrowser id:</b> {int(r['sibrowser_id'])}</p>")
        qc = r.get("question_count")
        diff = r.get("difficulty")
        diff_html = ""
        if isinstance(diff, str) and diff in _DIFF_COLORS:
            diff_html = (f" &nbsp; <b>Сложность:</b> "
                        f"{icon_html('fa5s.circle', size=10, color=_DIFF_COLORS[diff])} {_esc(diff)}")
        parts.append(
            f"<p><b>Вопросов:</b> {int(qc) if pd.notna(qc) else '—'} &nbsp; "
            f"<b>Группа:</b> {_esc(r['length_group'])} &nbsp; "
            f"<b>Длительность:</b> {_esc(r.get('duration_str') or '—')}{diff_html}</p>")
        comp = _fmt_pct(r.get("completion_pct"), 1)
        dlc = r.get("download_count")
        parts.append(
            f"<p><b>% завершения:</b> {comp} &nbsp; "
            f"<b>Скачиваний:</b> {int(dlc) if pd.notna(dlc) else '—'}</p>")
        if pd.notna(r.get("started_games")):
            rank = r.get("completion_rank_in_group")
            rank_txt = f" · перцентиль в группе: {rank:.0f}/100" if pd.notna(rank) else ""
            parts.append(
                f"<p>Игр начато: {int(r['started_games'])} · завершено: "
                f"{int(r['completed_games'])}{rank_txt}</p>")
            ap, cp, bi = r.get("answer_pct"), r.get("correct_pct"), r.get("balance_index")
            # Каждый показатель — отдельной строкой (по просьбе).
            parts.append(f"<p>Средний % попыток: {_fmt_pct(ap, 0)}</p>")
            parts.append(f"<p>Средний % правильных: {_fmt_pct(cp, 0)}</p>")
            parts.append(f"<p>Индекс баланса: {f'{bi:.0f}' if pd.notna(bi) else '—'}/100</p>")
        authors = r["authors"] if isinstance(r.get("authors"), list) else []
        if authors:
            parts.append(f"<p><b>Авторы:</b> {_esc(', '.join(authors))}</p>")
        cats = r.get("categories") if isinstance(r.get("categories"), list) else []
        if cats:
            parts.append("<p><b>Категории:</b> " +
                         ", ".join(f"{_esc(c['name'])} {c.get('pct', 0)}%" for c in cats) + "</p>")
        tags = r["tags"] if isinstance(r.get("tags"), list) else []
        if tags:
            parts.append("<p>" + " ".join(
                f"<span style='background:#222838;border:1px solid #313a52;border-radius:8px;"
                f"padding:2px 9px;margin:2px;'>{_esc(t)}</span>" for t in tags) + "</p>")

        try:
            with sg_db.connect() as conn:
                themes = sg_analysis.package_themes(conn, int(r["id"]))
        except Exception:
            themes = pd.DataFrame()
        if not themes.empty:
            parts.append("<h4>Темы по раундам</h4>")
            for rname, grp in themes.groupby("round_name", sort=False):
                # Каждая тема — с новой строки (по просьбе), а не «таблетками» в ряд.
                lines = "<br>".join(_esc(n) for n in grp["name"])
                parts.append(f"<p><b>{_esc(rname)}</b><br>{lines}</p>")
        return "".join(parts)

    def _open_selected_link(self):
        r = self._selected_pkg_row()
        if r is None:
            return
        import pandas as pd
        if pd.notna(r.get("sibrowser_id")):
            url = f"{sg_config.SIBROWSER_BASE}/packages/{int(r['sibrowser_id'])}"
            webbrowser.open(url)

    def _show_selected_questions(self):
        r = self._selected_pkg_row()
        if r is None:
            return
        try:
            with sg_db.connect() as conn:
                questions = sg_analysis.package_questions(conn, int(r["id"]))
                themes = sg_analysis.package_themes(conn, int(r["id"]))
        except Exception as e:
            msgbox_warning(self, "Ошибка", f"Не удалось прочитать вопросы: {e}")
            return
        if questions.empty:
            if msgbox_question(
                    self, "Скачать .siq",
                    "Вопросы ещё не скачаны. Скачать и разобрать .siq сейчас?"
            ) == QMessageBox.StandardButton.Yes:
                ok = sg_collector.download_one(int(r["id"]), str(r["sibrowser_id"]), r["name"])
                if ok:
                    self._reload_data()
                    self._show_selected_questions()
                else:
                    msgbox_warning(self, "Ошибка", "Не удалось скачать/разобрать .siq.")
            return
        html = _render_questions_html(questions, themes)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Вопросы — {r['name']}")
        dlg.resize(760, 640)
        v = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setOpenLinks(False)
        browser.setHtml(html)
        browser.anchorClicked.connect(_open_media_link)
        v.addWidget(browser)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        bb.button(QDialogButtonBox.StandardButton.Close).clicked.connect(dlg.accept)
        v.addWidget(bb)
        dlg.exec()

    def _bulk_download(self):
        import pandas as pd
        t = self.tbl_pkgs
        items = []
        for row in range(t.rowCount()):
            chk = t.item(row, 0)
            if chk is None or chk.checkState() != Qt.CheckState.Checked:
                continue
            pid = chk.data(Qt.ItemDataRole.UserRole)
            match = self._pkg_view_df[self._pkg_view_df["id"] == pid]
            if match.empty:
                continue
            r = match.iloc[0]
            if r.get("siq_downloaded") == 1 or pd.isna(r.get("sibrowser_id")):
                continue
            items.append((int(pid), str(r["sibrowser_id"]), r["name"]))
        if not items:
            msgbox_information(self, "Нечего скачивать",
                                    "Отметьте паки галочками в первой колонке — уже "
                                    "скачанные паки пропускаются автоматически.")
            return
        task = _BulkDownloadTask(items)
        task.signals.progress.connect(
            lambda i, total, name: (self.progress.setValue(int(i / total * 100)),
                                    self.lbl_status.setText(f"[{i}/{total}] {name}")))
        task.signals.item_progress.connect(self._on_item_download_progress)

        def _done(ok):
            self._end_job()
            self.lbl_status.setText(f"Скачано и разобрано: {ok} из {len(items)}.")
            self._reload_data()
        task.signals.finished.connect(_done)
        self._begin_job(task)

    def _row_for_pid(self, pid):
        """Номер строки таблицы по id пакета (id лежит в UserRole чек-ячейки)."""
        t = self.tbl_pkgs
        for row in range(t.rowCount()):
            chk = t.item(row, 0)
            if chk is not None and chk.data(Qt.ItemDataRole.UserRole) == pid:
                return row
        return None

    def _on_item_download_progress(self, pid, pct):
        """Бегущий процент скачивания у строки пака: пишем в роль ячейки имени,
        по достижении 100% ставим галочку (её отрисует _PkgNameDelegate)."""
        row = self._row_for_pid(pid)
        if row is None:
            return
        name_item = self.tbl_pkgs.item(row, self._COL_NAME)
        if name_item is None:
            return
        if pct >= 100:
            name_item.setData(_PkgNameDelegate.ProgressRole, None)
            name_item.setData(_PkgNameDelegate.DownloadedRole, True)
        else:
            name_item.setData(_PkgNameDelegate.ProgressRole, int(pct))
        self.tbl_pkgs.viewport().update()

    def _delete_selected_siq(self):
        r = self._selected_pkg_row()
        if r is None or r.get("siq_downloaded") != 1:
            return
        if msgbox_question(
                self, "Удалить пак",
                f"Удалить скачанный .siq пакета «{r['name']}» и его медиа с диска?\n"
                "Статистика в базе останется — пак не пропадёт из списка."
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            sg_collector.delete_siq(int(r["id"]))
        except Exception as e:
            msgbox_warning(self, "Ошибка", f"Не удалось удалить пак: {e}")
            return
        self.lbl_status.setText(f"Пак «{r['name']}» удалён с диска (статистика сохранена).")
        self._reload_data()

    # ══════════════════════════════════════════════════════════════════════
    # Вкладка «Темы»
    # ══════════════════════════════════════════════════════════════════════
    def _build_themes_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel(
            "Темы сгруппированы без учёта эмодзи. Перцентиль завершённости — с "
            "поправкой на длину пакета."))

        filt = QHBoxLayout()
        filt.addWidget(QLabel("Мин. пакетов с темой:"))
        self.sp_min_pkgs = QSpinBox(); self.sp_min_pkgs.setRange(1, 200); self.sp_min_pkgs.setValue(1)
        self.sp_min_pkgs.valueChanged.connect(self._refresh_themes_table)
        filt.addWidget(self.sp_min_pkgs)

        self.chk_rarity = {}
        for r, color in _RARITY_COLORS.items():
            c = QCheckBox(r); c.setChecked(True)
            c.setIcon(get_icon('fa5s.circle', color=color))
            c.toggled.connect(self._refresh_themes_table)
            self.chk_rarity[r] = c
            filt.addWidget(c)

        filt.addWidget(QLabel("Поиск темы:"))
        self.ed_theme_search = QLineEdit()
        self.ed_theme_search.setClearButtonEnabled(True)
        self.ed_theme_search.textChanged.connect(self._refresh_themes_table)
        filt.addWidget(self.ed_theme_search, 1)
        lay.addLayout(filt)

        self.lbl_theme_count = QLabel("")
        self.lbl_theme_count.setStyleSheet("color:#a6adc8;")
        lay.addWidget(self.lbl_theme_count)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.tbl_themes = QTableWidget(0, 5)
        self.tbl_themes.setHorizontalHeaderLabels(
            ["Тема", "Частота", "Пакетов", "Доля", "Ср. % зав."])
        self.tbl_themes.setSortingEnabled(True)
        self.tbl_themes.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_themes.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_themes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_themes.setAlternatingRowColors(True)
        self.tbl_themes.verticalHeader().setVisible(False)
        self.tbl_themes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_themes.itemSelectionChanged.connect(self._on_theme_selected)
        split.addWidget(self.tbl_themes)

        self.tbl_theme_pkgs = QTableWidget(0, 4)
        self.tbl_theme_pkgs.setHorizontalHeaderLabels(["Название", "Авторы", "Вопр.", "% завершения"])
        self.tbl_theme_pkgs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_theme_pkgs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_theme_pkgs.verticalHeader().setVisible(False)
        split.addWidget(self.tbl_theme_pkgs)
        split.setSizes([500, 500])
        lay.addWidget(split, 1)

        self.subtabs.addTab(page, "Темы")

    def _refresh_themes_table(self, *args):
        if self._themes_df is None or self._themes_df.empty:
            self.tbl_themes.setRowCount(0)
            self.lbl_theme_count.setText("")
            return
        tv = self._themes_df.copy()
        tv = tv[tv["n_packages"] >= self.sp_min_pkgs.value()]
        rarity_on = [r for r, c in self.chk_rarity.items() if c.isChecked()]
        if rarity_on:
            tv = tv[tv["rarity"].isin(rarity_on)]
        needle = self.ed_theme_search.text().strip().lower()
        if needle:
            tv = tv[tv["theme"].str.lower().str.contains(needle, na=False)]
        tv = tv.sort_values(["n_packages", "avg_completion_pct"], ascending=[False, False]).reset_index(drop=True)
        self._theme_view_df = tv

        t = self.tbl_themes
        t.setSortingEnabled(False)
        t.setRowCount(0)
        for _, r in tv.iterrows():
            row = t.rowCount()
            t.insertRow(row)
            theme_item = QTableWidgetItem(str(r["theme"]))
            theme_item.setData(Qt.ItemDataRole.UserRole, r["name_norm"])
            t.setItem(row, 0, theme_item)
            rarity_item = QTableWidgetItem(str(r["rarity"]))
            color = _RARITY_COLORS.get(r["rarity"])
            if color:
                rarity_item.setIcon(get_icon('fa5s.circle', color=color))
            t.setItem(row, 1, rarity_item)
            t.setItem(row, 2, _NumItem(str(int(r["n_packages"])), int(r["n_packages"])))
            t.setItem(row, 3, _NumItem(f"{r['share_pct']:.1f}%", r["share_pct"]))
            comp = r.get("avg_completion_pct")
            t.setItem(row, 4, _NumItem(_fmt_pct(comp, 0), comp if comp == comp else -1))
        t.setSortingEnabled(True)
        self.lbl_theme_count.setText(f"Тем: {len(tv)} · выберите тему — справа паки с ней.")

    def _on_theme_selected(self):
        rows = self.tbl_themes.selectionModel().selectedRows() if self.tbl_themes.selectionModel() else []
        self.tbl_theme_pkgs.setRowCount(0)
        if not rows:
            return
        row = rows[0].row()
        item = self.tbl_themes.item(row, 0)
        if item is None:
            return
        name_norm = item.data(Qt.ItemDataRole.UserRole)
        try:
            with sg_db.connect() as conn:
                pdf = sg_analysis.packages_with_theme(conn, name_norm)
        except Exception:
            return
        t = self.tbl_theme_pkgs
        for _, r in pdf.iterrows():
            row_i = t.rowCount()
            t.insertRow(row_i)
            t.setItem(row_i, 0, QTableWidgetItem(str(r["Название"])))
            t.setItem(row_i, 1, QTableWidgetItem(str(r.get("Авторы") or "")))
            t.setItem(row_i, 2, QTableWidgetItem(str(r.get("Вопр.") or "")))
            comp = r.get("% завершения")
            import pandas as pd
            t.setItem(row_i, 3, QTableWidgetItem(_fmt_pct(comp, 1) if pd.notna(comp) else "—"))

    # ══════════════════════════════════════════════════════════════════════
    # Вкладка «Авторы»
    # ══════════════════════════════════════════════════════════════════════
    def _build_authors_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel(
            "Рейтинг по среднему перцентилю завершённости паков (с поправкой на "
            "длину): чьи паки доигрывают до конца чаще, чем похожие по размеру."))

        filt = QHBoxLayout()
        filt.addWidget(QLabel("Мин. паков у автора (со статистикой):"))
        self.sp_min_pk = QSpinBox(); self.sp_min_pk.setRange(1, 100); self.sp_min_pk.setValue(1)
        self.sp_min_pk.valueChanged.connect(self._refresh_authors_table)
        filt.addWidget(self.sp_min_pk)
        filt.addWidget(QLabel("Мин. игр начато (сумма):"))
        self.sp_min_started_a = QSpinBox(); self.sp_min_started_a.setRange(0, 1_000_000)
        self.sp_min_started_a.setValue(200); self.sp_min_started_a.setSingleStep(50)
        self.sp_min_started_a.valueChanged.connect(self._refresh_authors_table)
        filt.addWidget(self.sp_min_started_a)
        self.chk_auth_stats = QCheckBox("Только авторы со статистикой")
        self.chk_auth_stats.setChecked(True)
        self.chk_auth_stats.toggled.connect(self._refresh_authors_table)
        filt.addWidget(self.chk_auth_stats)
        filt.addStretch(1)
        lay.addLayout(filt)

        self.tbl_authors = QTableWidget(0, 6)
        self.tbl_authors.setHorizontalHeaderLabels(
            ["Автор", "Паков", "Со стат.", "Ср. % завершения", "Ср. перцентиль (качество)", "Всего игр начато"])
        self.tbl_authors.setSortingEnabled(True)
        self.tbl_authors.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_authors.setAlternatingRowColors(True)
        self.tbl_authors.verticalHeader().setVisible(False)
        self.tbl_authors.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tbl_authors, 1)
        lay.addWidget(QLabel("«Качество» = средний перцентиль: 100 = паки автора заходят "
                            "лучше всех похожих по длине, 0 = хуже всех."))

        self.subtabs.addTab(page, "Авторы")

    def _refresh_authors_table(self, *args):
        if self._authors_df is None or self._authors_df.empty:
            self.tbl_authors.setRowCount(0)
            return
        av = self._authors_df.copy()
        av = av[av["with_stats"] >= self.sp_min_pk.value()]
        if self.sp_min_started_a.value() > 0:
            av = av[av["total_started"].fillna(0) >= self.sp_min_started_a.value()]
        if self.chk_auth_stats.isChecked():
            av = av[av["with_stats"] > 0]

        t = self.tbl_authors
        t.setSortingEnabled(False)
        t.setRowCount(0)
        for _, r in av.iterrows():
            row = t.rowCount()
            t.insertRow(row)
            t.setItem(row, 0, QTableWidgetItem(str(r["author"])))
            t.setItem(row, 1, _NumItem(str(int(r["packages"])), int(r["packages"])))
            t.setItem(row, 2, _NumItem(str(int(r["with_stats"])), int(r["with_stats"])))
            comp = r.get("avg_completion_pct")
            t.setItem(row, 3, _NumItem(_fmt_pct(comp, 0), comp if comp == comp else -1))
            rank = r.get("avg_pct_in_group")
            t.setItem(row, 4, _NumItem("—" if rank != rank else f"{rank:.0f}", rank if rank == rank else -1))
            started = r.get("total_started")
            t.setItem(row, 5, _NumItem(str(int(started)) if started == started else "0", started or 0))
        t.setSortingEnabled(True)

    # ══════════════════════════════════════════════════════════════════════
    # Вкладка «Экспорт»
    # ══════════════════════════════════════════════════════════════════════
    def _build_export_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel(
            "Собери компактный текст и вставь в ChatGPT/Claude с вопросом «какие "
            "темы и какая длина паков заходят лучше»."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Сколько пакетов:"))
        self.sp_export_n = QSpinBox(); self.sp_export_n.setRange(10, 2000); self.sp_export_n.setValue(100)
        row.addWidget(self.sp_export_n)
        self.chk_export_themes = QCheckBox("Добавить сводку по темам")
        self.chk_export_themes.setChecked(True)
        row.addWidget(self.chk_export_themes)
        row.addStretch(1)
        lay.addLayout(row)

        grp_row = QHBoxLayout()
        grp_row.addWidget(QLabel("Группы по длине:"))
        self._export_len_checks = {}
        for g in _LEN_GROUPS:
            c = QCheckBox(g); c.setChecked(True)
            self._export_len_checks[g] = c
            grp_row.addWidget(c)
        grp_row.addStretch(1)
        lay.addLayout(grp_row)

        btn_row = QHBoxLayout()
        btn_build = QPushButton("Собрать текст")
        btn_build.setIcon(get_icon('fa5s.robot'))
        btn_build.clicked.connect(self._build_export_dump)
        btn_row.addWidget(btn_build)
        btn_copy = QPushButton("Копировать")
        btn_copy.setIcon(get_icon('fa5s.copy'))
        btn_copy.clicked.connect(self._copy_export_dump)
        btn_row.addWidget(btn_copy)
        btn_save = QPushButton("Скачать как .txt")
        btn_save.setIcon(get_icon('fa5s.download'))
        btn_save.clicked.connect(self._save_export_dump)
        btn_row.addWidget(btn_save)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.txt_export = QTextEdit()
        self.txt_export.setReadOnly(True)
        self.txt_export.setFontFamily("Consolas")
        lay.addWidget(self.txt_export, 1)
        self.lbl_export_len = QLabel("")
        self.lbl_export_len.setStyleSheet("color:#a6adc8;")
        lay.addWidget(self.lbl_export_len)

        self.subtabs.addTab(page, "Экспорт")

    def _build_export_dump(self):
        if self._pkgs_df is None or self._pkgs_df.empty:
            msgbox_information(self, "Нет данных", "Пока нет собранных паков.")
            return
        d = self._pkgs_df[self._pkgs_df["has_stats"] == 1].copy()
        groups = [g for g, c in self._export_len_checks.items() if c.isChecked()]
        if groups:
            d = d[d["length_group"].isin(groups)]
        dump = sg_export.build_packages_dump(d, top_n=self.sp_export_n.value(), only_with_stats=True)
        if self.chk_export_themes.isChecked() and self._themes_df is not None and not self._themes_df.empty:
            dump += "\n\n" + sg_export.build_theme_dump(self._themes_df)
        self.txt_export.setPlainText(dump)
        self.lbl_export_len.setText(f"Символов: {len(dump)}")

    def _copy_export_dump(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.txt_export.toPlainText())

    def _save_export_dump(self):
        text = self.txt_export.toPlainText()
        if not text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить выгрузку", "sigstats_export.txt", "Текст (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            msgbox_warning(self, "Ошибка сохранения", str(e))

    # ──────────────────────────────────────────────────────────────────────
    # Прочее (симметрично ShikimoriHYX/ЛидербордHYX)
    # ──────────────────────────────────────────────────────────────────────
    def get_settings(self) -> dict:
        return {}

    def cleanup(self):
        self._set_app_click_filter(False)
        if self._active_job is not None:
            self._active_job.stop()


def _hline():
    from PyQt6.QtWidgets import QFrame
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def _esc(s) -> str:
    import html as _html
    return _html.escape(str(s or ""))


def _render_questions_html(questions, themes) -> str:
    """HTML-дамп всех вопросов/ответов пакета (упрощённая версия навигации по
    темам из Streamlit — без интерактивного выбора тем, зато сразу всё видно и
    прокручивается)."""
    import pandas as pd
    tnames = {}
    if not themes.empty:
        for _, r in themes.iterrows():
            tnames[(int(r["round_index"]), int(r["theme_index"]))] = r["name"]

    parts = ["<html><body style='font-family:Segoe UI,Arial;font-size:13px;'>"]
    has_dur = "duration_sec" in questions.columns
    for ridx, rgrp in questions.groupby("round_index"):
        for tidx, tgrp in rgrp.groupby("theme_index"):
            nm = tnames.get((int(ridx), int(tidx)), f"тема {int(tidx) + 1}")
            parts.append(f"<h3>Раунд {int(ridx) + 1} · {_esc(nm)}</h3>")
            for _, q in tgrp.iterrows():
                price = f"{int(q['price'])}" if pd.notna(q["price"]) else "—"
                qd = q.get("duration_sec") if has_dur else None
                qd_lbl = (f" · {icon_html('fa5s.stopwatch', size=12)} {qd:.0f}с"
                         if qd is not None and pd.notna(qd) and qd > 0 else "")
                parts.append(f"<p><b>{price}.</b> {_esc(q['text']) or '<i>(вопрос только в медиа)</i>'}{qd_lbl}</p>")
                parts.append(_render_media_html(q.get("media_json")))
                parts.append(f"<p><b>Ответ:</b> {_esc(q['answer']) or '—'}</p>")
                parts.append(_render_media_html(q.get("answer_media_json")))
                if q.get("shown_count"):
                    shown = int(q["shown_count"])
                    ans = int(q["answered_count"] or 0)
                    cor = int(q["correct_count"] or 0)
                    wr = int(q["wrong_count"] or 0)
                    # Знаменатель — shownCount для ОБОИХ процентов (та же база,
                    # что в siquester/auto_stats.py и на самом сайте статистики).
                    # cor+wr НЕ равен answered — в SIGame один вопрос допускает
                    # несколько попыток ответа, поэтому делить на (cor+wr) нельзя:
                    # знаменатель "плавает" и завышает % правильных.
                    tries = (ans / shown * 100) if shown else 0
                    right = (cor / shown * 100) if shown else 0
                    ok_ic = icon_html('fa5s.check', size=11, color='#a6e3a1')
                    bad_ic = icon_html('fa5s.times', size=11, color='#f38ba8')
                    parts.append(
                        f"<p style='color:#888;'>{icon_html('fa5s.eye', size=12)} показан {shown}× · "
                        f"ответили {tries:.0f}% · верно {right:.0f}% "
                        f"({cor}{ok_ic} / {wr}{bad_ic})</p>")
                parts.append("<hr>")
    parts.append("</body></html>")
    return "".join(parts)


def _render_media_html(media_json) -> str:
    import json
    try:
        media = json.loads(media_json) if media_json else []
    except (TypeError, ValueError):
        media = []
    out = []
    for m in media:
        ref = m.get("path") or m.get("ref")
        if not ref:
            continue
        mtype = m.get("type")
        if mtype == "image" and m.get("path"):
            url = QUrl.fromLocalFile(m["path"]).toString()
            out.append(f"<p><img src='{url}' width='320'></p>")
        elif mtype in ("voice", "audio", "video") and m.get("path"):
            url = QUrl.fromLocalFile(m["path"]).toString()
            if mtype in ("voice", "audio"):
                icon, label = "fa5s.music", "Открыть аудио"
            else:
                icon, label = "fa5s.play", "Открыть видео"
            out.append(f"<p><a href='{url}'>{icon_html(icon, size=13)} {label}</a></p>")
        else:
            out.append(f"<p><i>медиа: {_esc(ref)}</i></p>")
    return "".join(out)


def _open_media_link(url: QUrl):
    QDesktopServices.openUrl(url)
