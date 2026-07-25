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
                          QTimer, QEvent, QDate, QRect, QSize, QPoint)
from PyQt6.QtGui import QDesktopServices, QColor, QFontMetrics, QPalette, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QGroupBox,
    QRadioButton, QButtonGroup, QLabel, QLineEdit, QPushButton, QComboBox,
    QCheckBox, QSlider, QSpinBox, QDateEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSplitter, QTextBrowser, QDialog,
    QProgressBar, QFileDialog, QMessageBox, QScrollArea, QTextEdit,
    QDialogButtonBox, QFrame, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyle, QStyleOptionViewItem, QApplication, QMenu,
    QSizePolicy, QLayout,
)
from msgbox import msgbox_critical, msgbox_warning, msgbox_information, msgbox_question

try:
    from widgets import _present_fullscreen
except Exception:  # pragma: no cover
    _present_fullscreen = None

try:
    from config import get_icon, icon_html, CONFIG_DIR, FFPROBE
except Exception:  # pragma: no cover
    CONFIG_DIR = None
    FFPROBE = None

    def get_icon(name, color="#cdd6f4", **_kw):
        from PyQt6.QtGui import QIcon as _QIcon
        return _QIcon()

    def icon_html(name, size=16, color="#cdd6f4"):
        return ""

try:
    from config import TIER_LIST_PUBLISH_URL, APP_VERSION
except Exception:  # pragma: no cover
    TIER_LIST_PUBLISH_URL = ""
    APP_VERSION = "?"

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
    from sigstats import steam_workshop as sg_steam_workshop
    from sigstats import sibrowser as sg_sibrowser
    if FFPROBE:
        sg_config.FFPROBE_PATH = FFPROBE  # используем bundled ffprobe SI-HYX
except Exception as e:  # pragma: no cover
    _HAS_BACKEND = False
    _IMPORT_ERROR = str(e)

_ANY_TOPIC = "— любая —"
# «Неизвестно» — сюда попадают паки без известного числа вопросов; Steam
# Workshop (Steam Web API не отдаёт содержимое .siq) ВСЕГДА в этой группе —
# без неё паки, импортированные из Steam, были бы не видны по умолчанию.
_LEN_GROUPS = ["Короткие", "Средние", "Полные", "Большие", "Неизвестно"]
_PERIODS = {"Неделя": 7, "Месяц": 30, "3 месяца": 90, "Полгода": 182, "Год": 365}
_DIFF_LEVELS = ["лёгкий", "средне", "сложно", "оч. сложно"]
_DIFF_COLORS = {"лёгкий": "#a6e3a1", "средне": "#f9e2af", "сложно": "#f38ba8", "оч. сложно": "#8839ef"}
_RARITY_COLORS = {"редкая": "#f38ba8", "средняя": "#f9e2af", "частая": "#a6e3a1"}
# Цветная вертикальная полоска слева от строки для паков с преобладающей темой
# (красная — аниме, фиолетовая — музыка); красит не весь фон строки, а только
# узкую полосу у левого края (см. _AccentBarDelegate) — так заметнее, но не
# мешает читать текст остальных колонок.
_CATEGORY_ACCENT = {"Аниме": "#f38ba8", "Музыка": "#cba6f7"}

# Лёгкая подсветка всей строки (не полоски, а фона — на разницу с
# _CATEGORY_ACCENT) для паков, которые в списке ТОЛЬКО благодаря включённому
# «игнорировать» чекбоксу справа (иначе были бы отфильтрованы): у каждой из
# трёх причин свой чуть отличающийся оттенок, чтобы сразу было видно, почему
# пак обычно скрыт. Порядок приоритета при нескольких причинах сразу —
# чёрный список пакета > чёрный список автора > уже сыграно.
_ROW_STATUS_TINT = {
    "pkg_bl": QColor(243, 139, 168, 55),      # красноватый — чёрный список пакетов
    "author_bl": QColor(249, 226, 175, 55),   # желтоватый — чёрный список авторов
    "played": QColor(137, 180, 250, 50),      # голубоватый — уже сыграно
}


def _fmt_pct(v, digits=0) -> str:
    try:
        import math
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "—"
        return f"{v:.{digits}f}%"
    except Exception:
        return "—"


def _fmt_int(v) -> str:
    try:
        import math
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "—"
        return str(int(v))
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


class _RowTintDelegate(QStyledItemDelegate):
    """Базовый делегат таблицы паков: поверх штатной отрисовки ячейки кладёт
    лёгкую заливку (см. _ROW_STATUS_TINT) — ею помечаются паки, попавшие в
    список только из-за включённого «игнорировать» чекбокса.

    Почему делегат, а не QTableWidgetItem.setBackground: в глобальном
    STYLESHEET есть правило `QTableWidget::item` — при его наличии
    QStyleSheetStyle рисует фон ячейки сам и Qt.BackgroundRole из модели
    ПОЛНОСТЬЮ игнорирует, так что setBackground не давал вообще никакого
    эффекта (проверено замером пикселей отрисованной таблицы)."""

    TintRole = Qt.ItemDataRole.UserRole + 25

    def _paint_tint(self, painter, option, index):
        tint = index.data(self.TintRole)
        if not tint:
            return
        painter.save()
        painter.fillRect(option.rect, QColor(tint))
        painter.restore()

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        self._paint_tint(painter, option, index)


class _PkgNameDelegate(_RowTintDelegate):
    """Ячейка «Название»: текст с переносом по словам + индикатор скачивания
    справа — зелёная галочка (пак скачан) или «NN%» во время скачивания. Заменяет
    прежнюю отдельную колонку «.siq». Данные берёт из ролей элемента:
    DownloadedRole (bool) и ProgressRole (int 0..99 | None). Паки из Steam
    Workshop (SteamRole=True) получают значок Steam слева от названия."""

    DownloadedRole = Qt.ItemDataRole.UserRole + 21
    ProgressRole = Qt.ItemDataRole.UserRole + 22
    SteamRole = Qt.ItemDataRole.UserRole + 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self._check = get_icon('fa5s.check', color='#a6e3a1')
        self._steam = get_icon('fa5b.steam', color='#66c0f4')

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        # Фон / выделение / чередование / рамку фокуса рисует штатный стиль.
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        # Тут этот делегат сам рисует текст ниже, поэтому заливку статуса
        # кладём сразу после фона — так она не «моет» название пака.
        self._paint_tint(painter, option, index)

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

        text_left = rect.left()
        if bool(index.data(self.SteamRole)):
            isz = 14
            self._steam.paint(painter, QRect(
                text_left, rect.top() + (rect.height() - isz) // 2, isz, isz))
            text_left += isz + 5

        if opt.state & QStyle.StateFlag.State_Selected:
            painter.setPen(opt.palette.color(QPalette.ColorRole.HighlightedText))
        else:
            painter.setPen(opt.palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            QRect(text_left, rect.top(), rect.right() - text_left - status_w, rect.height()),
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


class _AccentBarDelegate(_RowTintDelegate):
    """Ячейка «места» (колонка 0): рисует номер строки + узкую цветную
    полоску у самого левого края строки (см. _CATEGORY_ACCENT) — для паков с
    преобладающей темой. Полоска вместо покраски всего фона строки: заметно,
    но не мешает читать текст остальных колонок."""

    AccentRole = Qt.ItemDataRole.UserRole + 23
    _BAR_W = 4

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        painter.save()
        # Номер места берём из index.row(), а НЕ из текста ячейки: QTableWidget
        # при сортировке физически переставляет строки модели, так что
        # index.row() — это и есть текущее «место» пака сверху вниз, и оно
        # автоматически верно после любой сортировки по заголовку. Хранить
        # номер в самой ячейке нельзя: setText при включённой сортировке
        # заставляет таблицу пересортироваться прямо во время пересчёта.
        rect = QRect(option.rect)
        rect.setLeft(rect.left() + self._BAR_W + 2)
        rect.setRight(rect.right() - 3)
        painter.setPen(QColor("#7f849c"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter),
                         str(index.row() + 1))
        color = index.data(self.AccentRole)
        if color:
            bar = QRect(option.rect.left(), option.rect.top(), self._BAR_W, option.rect.height())
            painter.fillRect(bar, QColor(color))
        painter.restore()


def _num_or_zero(value):
    """NaN/None → 0 для сортировочного ключа _NumItem.

    `value or 0` ломается на pandas NaN: float('nan') truthy в Python, поэтому
    `or` его не заменяет — ключом сортировки оставался сам NaN, а сравнение
    NaN с чем угодно всегда False, из-за чего строки с пропусками не вставали
    на своё место при клике по заголовку (напр. «Игр начато»)."""
    if value is None or value != value:
        return 0
    return value


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


class _NoHScrollTable(QTableWidget):
    """Таблица, автопрокрутка которой работает ТОЛЬКО по вертикали.

    Qt при выборе ячейки зовёт scrollTo(index) — и если кликнуть по значению в
    правой колонке широкой таблицы, вся таблица уезжает вправо («прыгает»).
    Выключать autoScroll целиком нельзя: тогда потеряется вертикальная
    доводка (стрелки клавиатуры, восстановление выделения после
    перефильтровки), поэтому просто возвращаем горизонтальную позицию на
    место после базовой реализации."""

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible):
        h = self.horizontalScrollBar().value()
        super().scrollTo(index, hint)
        self.horizontalScrollBar().setValue(h)


class _FullscreenHost(QWidget):
    """Контейнер для полноэкранного показа таблицы пакетов: держит репарентнутый
    сплиттер (tbl_pkgs + pkg_detail) и закрывается по Esc — как остальные
    полноэкранные просмотрщики в проекте (см. widgets.py::ImageFullscreenViewer).

    Кнопка выхода в правом верхнем углу — окно безрамочное и WindowStaysOnTopHint
    (см. _present_fullscreen), поэтому исходная кнопка-переключатель на вкладке
    остаётся ПОД ним и недоступна для клика; без своей кнопки выйти можно было
    только по Esc."""

    def __init__(self, on_close):
        super().__init__()
        self._on_close = on_close
        self.btn_close = QPushButton(self)
        self.btn_close.setIcon(get_icon('fa5s.times', '#ffffff'))
        self.btn_close.setIconSize(QSize(18, 18))
        self.btn_close.setFixedSize(38, 38)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("Выйти из полноэкранного режима (Esc)")
        self.btn_close.setStyleSheet(
            "QPushButton{background:rgba(24,24,37,190);border:1px solid #45475a;"
            "border-radius:19px;}"
            "QPushButton:hover{background:#f38ba8;border-color:#f38ba8;}")
        self.btn_close.clicked.connect(self._on_close)
        self.btn_close.raise_()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._on_close()
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.btn_close.move(self.width() - self.btn_close.width() - 14, 14)
        self.btn_close.raise_()


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


# Сколько паков качаются ОДНОВРЕМЕННО из общей очереди (см. _BulkDownloadTask).
# Небольшое число — не DDOS-ить sibrowser.ru, но и не качать строго по одному.
_MAX_PARALLEL_DOWNLOADS = 3


class _BulkDownloadTask(QRunnable):
    """Скачивает .siq нескольких отмеченных паков — до _MAX_PARALLEL_DOWNLOADS
    одновременно (несколько потоков разбирают общую очередь), отдавая прогресс
    скачивания КАЖДОГО пака (item_progress) — чтобы у его строки в таблице (и у
    карточки в тир-листе, см. SigstatsTab.download_progress) бежал процент, а
    по завершении встала галочка.

    Очередь (queue.Queue), а не статичный список: пока пакеты качаются, можно
    дозаписать в неё ещё паков через add_items — раньше выбор нового пака для
    скачивания, пока идёт другое, либо блокировался, либо (кнопка временно
    превращена в «Отмена») реально отменял уже идущее скачивание вместо того
    чтобы поставить новое в очередь."""

    def __init__(self, items):
        super().__init__()
        self.setAutoDelete(False)
        import queue
        import threading
        self._queue = queue.Queue()
        self._total = 0
        self._done_count = 0
        self._ok_count = 0
        self._lock = threading.Lock()
        self.signals = _DownloadSignals()
        self._stop = False
        self.add_items(items)

    def add_items(self, items):
        for it in items:
            self._queue.put(it)
            self._total += 1

    def stop(self):
        self._stop = True

    def _worker(self):
        import queue
        while not self._stop:
            try:
                pid, sib_id, name = self._queue.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                self._done_count += 1
                done_snap, total_snap = self._done_count, self._total
            self.signals.progress.emit(done_snap, total_snap, name)
            self.signals.item_progress.emit(pid, 0)

            def _pcb(done, tot, _pid=pid):
                pct = int(done / tot * 100) if tot else 0
                self.signals.item_progress.emit(_pid, min(99, max(0, pct)))
            try:
                if sg_collector.download_one(pid, sib_id, name, progress_cb=_pcb,
                                             should_stop=lambda: self._stop):
                    with self._lock:
                        self._ok_count += 1
                    self.signals.item_progress.emit(pid, 100)
            except Exception:
                pass

    def run(self):
        import threading
        helpers = [threading.Thread(target=self._worker, daemon=True)
                   for _ in range(_MAX_PARALLEL_DOWNLOADS - 1)]
        for w in helpers:
            w.start()
        self._worker()   # пуловый поток тоже качает, а не только раздаёт работу
        for w in helpers:
            w.join()
        self.signals.finished.emit(self._ok_count)


class _DeleteSiqSignals(QObject):
    finished = pyqtSignal(int, bool, str)   # package_id, ok, ошибка (если есть)


class _DeleteSiqTask(QRunnable):
    """Удаление скачанного .siq + медиа пака (sg_collector.delete_siq) в фоне —
    shutil.rmtree на папке медиа может занять заметное время (много мелких
    файлов картинок/аудио/видео), а раньше вызывалось прямо в UI-потоке и
    подвешивало интерфейс на это время."""

    def __init__(self, package_id: int):
        super().__init__()
        self.setAutoDelete(True)
        self.package_id = package_id
        self.signals = _DeleteSiqSignals()

    def run(self):
        try:
            sg_collector.delete_siq(self.package_id)
            self.signals.finished.emit(self.package_id, True, "")
        except Exception as e:
            self.signals.finished.emit(self.package_id, False, str(e))


class _DescFetchSignals(QObject):
    finished = pyqtSignal(int, str)   # package_id, полный текст
    failed = pyqtSignal(int)          # package_id


class _DescFetchTask(QRunnable):
    """Одиночный запрос страницы пака за полным (неурезанным) описанием — см.
    sibrowser.fetch_full_description. Отдельный раннер на каждый пак, а не
    очередь через _JobTask: запрос ровно один и должен не мешать остальным
    фоновым задачам (сбору/обновлению статистики)."""

    def __init__(self, package_id: int, sibrowser_id: str):
        super().__init__()
        self.setAutoDelete(True)
        self.package_id = package_id
        self.sibrowser_id = sibrowser_id
        self.signals = _DescFetchSignals()

    def run(self):
        try:
            session = sg_sibrowser.make_session()
            try:
                text = sg_sibrowser.fetch_full_description(session, self.sibrowser_id)
            finally:
                session.close()
        except Exception:
            self.signals.failed.emit(self.package_id)
            return
        if text:
            self.signals.finished.emit(self.package_id, text)
        else:
            self.signals.failed.emit(self.package_id)


class _SteamOneSignals(QObject):
    finished = pyqtSignal(dict)   # см. sg_collector.collect_steam_one


class _SteamOneTask(QRunnable):
    """Точечное добавление ОДНОГО пака Steam Workshop по прямой ссылке/id —
    ровно один сетевой запрос, поэтому отдельный лёгкий раннер, а не очередь
    через _JobTask (та рассчитана на постраничный обход каталога)."""

    def __init__(self, id_or_url: str, api_key: str, author_blacklist):
        super().__init__()
        self.setAutoDelete(True)
        self.id_or_url = id_or_url
        self.api_key = api_key
        self.author_blacklist = author_blacklist
        self.signals = _SteamOneSignals()

    def run(self):
        result = sg_collector.collect_steam_one(
            self.id_or_url, self.api_key, author_blacklist=self.author_blacklist)
        self.signals.finished.emit(result)


class SigstatsTab(QWidget):
    """Вкладка «Поиск пакетов»: сбор и анализ статистики паков «Своя игра»."""

    # Первая загрузка БД идёт в фоновом потоке (иначе окно вкладки виснет на
    # несколько секунд). Поток эмитит этот сигнал с результатом; применение
    # данных в таблицы — уже в GUI-потоке (см. _on_db_loaded).
    _db_loaded_sig = pyqtSignal(object)

    # (package_id, процент 0..100) скачивания .siq — эмитится независимо от
    # того, ОТКУДА запущено скачивание (таблица паков или тир-лист), чтобы
    # открытое окно тир-листа тоже могло показать бегущий процент у карточки
    # (см. _TierListDialog._on_download_progress).
    download_progress = pyqtSignal(int, int)

    # Датафрейм паков перезагружен (скачивание завершилось, .siq удалён и
    # т.п.) — эмитится из _apply_db_data. Открытый тир-лист по нему
    # перерисовывает галочки «скачан» у карточек в «Не распределено» (см.
    # _TierListDialog._refresh_all_card_icons); без этого сигнала галочка
    # оставалась висеть даже после удаления .siq через основную таблицу.
    library_changed = pyqtSignal()

    def __init__(self, main):
        super().__init__()
        self.main = main
        self._pool = QThreadPool.globalInstance()
        self._active_job = None
        self._loaded = False
        self._loading_db = False
        self._db_loaded_sig.connect(self._on_db_loaded)

        self._pkgs_df = None
        self._themes_df = None
        self._authors_df = None
        self._pkg_view_df = None
        self._theme_view_df = None
        # id пака, чья карточка сейчас открыта справа — используется, чтобы 1)
        # повторный ЛКМ по той же строке закрывал карточку (см. _on_pkg_clicked)
        # и 2) пережить перестройку таблицы при новом поиске/фильтре (см.
        # _refresh_packages_table), которая иначе сбрасывала выделение и
        # закрывала карточку при каждой печати в поиске.
        self._current_detail_pid = None
        # True, если itemSelectionChanged уже отработал в рамках текущего клика
        # (ЛКМ на строке сначала меняет выделение, потом стреляет `clicked`) —
        # без этого флага _on_pkg_clicked видел уже обновлённый _current_detail_pid
        # и решал, что кликнули по уже открытому паку, закрывая карточку сразу
        # после её открытия (см. _on_pkg_clicked/_on_pkg_selection_changed).
        self._pkg_selection_just_changed = False
        # id паков, для которых уже запрошено/получено полное описание в этом
        # запуске — не долбим sibrowser повторным запросом при каждом повторном
        # открытии одной и той же карточки (см. _maybe_fetch_full_description).
        self._desc_full_pending: set[int] = set()
        self._desc_full_done: set[int] = set()
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

        # Списки ниже — списки (не set), т.к. порядок в них значим: новые
        # записи вставляются в НАЧАЛО (см. _blacklist_author_by_name/
        # _mark_selected_played/_blacklist_package), поэтому порядок = порядок
        # добавления, новые сверху. *_added_at — момент добавления каждого id
        # (для отображения даты рядом с паком в списках played/pkg_blacklist;
        # авторам дата не нужна — там просто важен порядок).
        self._author_blacklist = sg_config.load_author_blacklist()
        self._played_ids: list[int] = list(sg_config.load_played_packages())
        self._played_added_at: dict[int, str] = sg_config.load_played_added_at()
        self._pkg_blacklist: list[int] = list(sg_config.load_package_blacklist())
        self._pkg_blacklist_added_at: dict[int, str] = sg_config.load_package_blacklist_added_at()
        self._last_collect_key = None
        self._live_refresh_timer = QTimer(self)
        self._live_refresh_timer.setSingleShot(True)
        self._live_refresh_timer.timeout.connect(self._live_refresh_now)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet("color:#a6adc8;")
        self.lbl_summary.setContentsMargins(0, 0, 6, 0)

        self.subtabs = QTabWidget()
        # Строка со сводной статистикой ("Пакетов: … · со статистикой: …") — в
        # углу справа от рядка подвкладок Пакеты/Темы/Авторы/Экспорт, а не
        # отдельной строкой над ними (по просьбе).
        self.subtabs.setCornerWidget(self.lbl_summary, Qt.Corner.TopRightCorner)
        root.addWidget(self.subtabs, 1)

        self._build_packages_page()
        self._build_themes_page()
        self._build_authors_page()
        self._build_export_page()

        # Колесо мыши НЕ меняет значения спинбоксов/комбобоксов/ползунков на
        # этой вкладке (как в Монтаже) — частая причина случайных изменений
        # фильтров при простом прокручивании списка/страницы. См. eventFilter.
        for w in self.findChildren((QSpinBox, QComboBox, QSlider)):
            w.installEventFilter(self)

        self._load_ui_settings()
        self._wire_settings_persistence()

    # ──────────────────────────────────────────────────────────────────────
    # Ленивая загрузка БД — только при первом реальном показе вкладки
    # ──────────────────────────────────────────────────────────────────────
    def showEvent(self, e):
        super().showEvent(e)
        if not self._loaded and _HAS_BACKEND:
            self._loaded = True
            self._reload_data_async()   # первая загрузка — в фоне, без фриза
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

    @staticmethod
    def _load_db_data():
        """Тяжёлая часть загрузки БД (init_db + чтение датафреймов + summary).
        Не трогает GUI — можно звать из фонового потока. Возвращает dict или
        бросает исключение при ошибке."""
        sg_db.init_db()
        with sg_db.connect() as conn:
            pkgs = sg_analysis.load_packages(conn)
            themes = sg_analysis.theme_table(conn)
            authors = sg_analysis.author_table(conn)
            summary = sg_db.stats(conn)
        return {"pkgs": pkgs, "themes": themes, "authors": authors, "summary": summary}

    def _apply_db_data(self, result):
        """Ставит загруженные датафреймы и обновляет таблицы (GUI-поток).
        result=None → загрузка упала, оставляем прежние/пустые данные."""
        import pandas as pd
        if result is not None:
            self._pkgs_df = result["pkgs"]
            self._themes_df = result["themes"]
            self._authors_df = result["authors"]
            summary = result["summary"]
            self.lbl_summary.setText(
                f"Пакетов: {summary['packages']} · со статистикой: {summary['with_stats']} · "
                f"скачано .siq: {summary['with_siq']} · уник. тем: {summary['themes']} · "
                f"вопросов: {summary['questions']}")
        else:
            self._pkgs_df = self._pkgs_df if self._pkgs_df is not None else pd.DataFrame()
            self._themes_df = self._themes_df if self._themes_df is not None else pd.DataFrame()
            self._authors_df = self._authors_df if self._authors_df is not None else pd.DataFrame()
        self._refresh_played_list()
        self._refresh_pkg_blacklist_list()
        self._refresh_packages_table()
        self._refresh_themes_table()
        self._refresh_authors_table()
        self.library_changed.emit()

    def _reload_data(self):
        """Синхронная перезагрузка (используется после действий пользователя —
        пометка «сыграно», ЧС и т.п., где данные нужны сразу)."""
        try:
            result = self._load_db_data()
        except Exception as e:
            result = None
            self._log(f"Поиск пакетов: ошибка загрузки БД: {e}")
        self._apply_db_data(result)

    def _reload_data_async(self):
        """Первая загрузка — в фоновом потоке, чтобы не морозить окно вкладки.
        Пока идёт — показываем «Загрузка…». Результат применяем в GUI-потоке
        через сигнал _db_loaded_sig."""
        if self._loading_db:
            return
        self._loading_db = True
        try:
            self.lbl_summary.setText("Загрузка базы пакетов…")
        except Exception:
            pass
        import threading

        def _work():
            # В фоновом потоке НЕ трогаем GUI (в т.ч. _log) — только считаем.
            # Успех → dict, ошибка → строка с текстом (обработаем в GUI-потоке).
            try:
                res = self._load_db_data()
            except Exception as e:
                res = f"__error__:{e}"
            self._db_loaded_sig.emit(res)

        threading.Thread(target=_work, daemon=True).start()

    def _on_db_loaded(self, result):
        self._loading_db = False
        if isinstance(result, str) and result.startswith("__error__:"):
            self._log(f"Поиск пакетов: ошибка загрузки БД: {result[len('__error__:'):]}")
            result = None
        self._apply_db_data(result)

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
            "period": self.cmb_period,
            "steam_api_key": self.ed_steam_api_key,
            "steam_min_subs": self.sp_steam_min_subs, "steam_max_new": self.sp_steam_max_new,
            "custom_date": self.de_custom, "topic": self.cmb_topic,
            "topic_min": self.sl_topic_min,
            "only_siq": self.chk_only_siq, "min_comp": self.sl_min_comp,
            "min_started_filter": self.sp_min_started,
            "cat_min": self.sl_cat_min, "search": self.ed_search,
            "show_played": self.chk_show_played,
            "show_pkg_blacklist": self.chk_show_pkg_blacklist,
            "show_author_blacklist": self.chk_show_author_blacklist,
            "only_with_stats": self.chk_only_with_stats,
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
        # Ползунки выше восстановлены с blockSignals(True) (см. цикл выше) —
        # valueChanged не сработал, а значит и подписанные под ним лейблы с
        # текущим числом (lbl_cat_min/lbl_topic_min) остались на исходном
        # захардкоженном "50", даже когда сам ползунок сдвинут на другое
        # восстановленное значение. Синхронизируем их вручную.
        self.lbl_cat_min.setText(str(self.sl_cat_min.value()))
        self.lbl_topic_min.setText(str(self.sl_topic_min.value()))

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

        count_row = QHBoxLayout()
        # Поиск раньше жил в правой панели фильтров, отдельно от таблицы и
        # счётчика найденного — перенесён сюда, в ту же строку, что и «Найдено
        # пакетов» (по просьбе, ближе к тому, что он фильтрует).
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Поиск (название/автор/тема)…")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self._refresh_packages_table)
        count_row.addWidget(self.ed_search, 2)
        self.lbl_pkg_count = QLabel("")
        self.lbl_pkg_count.setStyleSheet("color:#a6adc8;")
        count_row.addWidget(self.lbl_pkg_count, 1)
        self.btn_pkgs_fullscreen = QPushButton()
        self.btn_pkgs_fullscreen.setIcon(get_icon('fa5s.expand'))
        self.btn_pkgs_fullscreen.setToolTip("Полноэкранный режим таблицы (Esc — выйти)")
        self.btn_pkgs_fullscreen.setFixedWidth(32)
        self.btn_pkgs_fullscreen.clicked.connect(self._toggle_pkgs_fullscreen)
        count_row.addWidget(self.btn_pkgs_fullscreen)
        left.addLayout(count_row)
        self._pkg_left_layout = left
        self._pkg_fullscreen_host = None

        split = QSplitter(Qt.Orientation.Horizontal)
        # Колонки: № (место в текущем порядке) · Название (с индикатором
        # скачивания) · Авторы · Дата выхода · Вопр. · Вес · Сложность · Скач. ·
        # % завершения · % попыток · % правильных · Игр начато · Тема · Длит. ·
        # Группа.
        # «.siq» убрана (её роль — галочка/процент прямо в колонке «Название»,
        # см. _PkgNameDelegate). «Длит.» — предпоследняя колонка (перед «Группа»).
        # «Вес» — отдельная колонка (раньше дописывался в скобках к «Вопр.»).
        self.tbl_pkgs = _NoHScrollTable(0, 15)
        self.tbl_pkgs.setHorizontalHeaderLabels([
            "№", "Название", "Авторы", "Дата", "Вопр.", "Вес", "Сложность",
            "Скач.", "% завершения", "% попыток", "% правильных", "Игр начато",
            "Тема", "Длит.", "Группа",
        ])
        self._COL_NAME = 1
        self._COL_THEME = 12
        self.tbl_pkgs.setSortingEnabled(True)
        self.tbl_pkgs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # ExtendedSelection — Ctrl+ЛКМ точечно, Shift+ЛКМ диапазоном (как в
        # проводнике). Раньше был SingleSelection и «скачать несколько» делалось
        # галочками в колонке 0; галочки заменены на номер места, а массовые
        # действия (скачать/сыграно/чёрный список) работают по выделению.
        self.tbl_pkgs.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl_pkgs.setAlternatingRowColors(True)
        self.tbl_pkgs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Перенос по словам делает ТОЛЬКО делегат «Название»; остальные колонки
        # остаются в одну строку (длинное — сокращается «…»), чтобы строки не
        # разрастались по высоте из-за длинных авторов/тем.
        self.tbl_pkgs.setWordWrap(False)
        self.tbl_pkgs.verticalHeader().setVisible(False)
        # Делегат по умолчанию (все «обычные» колонки) — только заливка статуса
        # строки; у «Названия» и «№» она встроена в их собственные делегаты.
        self.tbl_pkgs.setItemDelegate(_RowTintDelegate(self.tbl_pkgs))
        # Название рисует свой делегат: перенос длинного имени по словам +
        # индикатор скачивания (процент/галочка) справа.
        self._name_delegate = _PkgNameDelegate(self.tbl_pkgs)
        self.tbl_pkgs.setItemDelegateForColumn(self._COL_NAME, self._name_delegate)
        # Колонка 0 (номер места) заодно рисует цветную полоску слева от строки —
        # см. _AccentBarDelegate/_CATEGORY_ACCENT.
        self._accent_delegate = _AccentBarDelegate(self.tbl_pkgs)
        self.tbl_pkgs.setItemDelegateForColumn(0, self._accent_delegate)
        # Ширины столбцов подгоняются под содержимое (без лишней пустоты справа):
        # короткие числовые/датовые — ResizeToContents, «Авторы»/«Тема»/«Название»
        # тянутся руками. «Название» раньше было Stretch и при большом числе
        # ResizeToContents-колонок схлопывалось почти до нуля (перенос по букве);
        # теперь у него фиксированная стартовая ширина, а лишнее место (если
        # есть) уходит в горизонтальный скролл таблицы, а не в сжатие имени.
        hdr = self.tbl_pkgs.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(self._COL_NAME, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)         # Авторы
        hdr.setSectionResizeMode(self._COL_THEME, QHeaderView.ResizeMode.Interactive)  # Тема
        hdr.setStretchLastSection(False)
        self.tbl_pkgs.setColumnWidth(0, 42)   # место: до 4 цифр + полоска темы
        self.tbl_pkgs.setColumnWidth(self._COL_NAME, 320)
        self.tbl_pkgs.setColumnWidth(2, 140)
        self.tbl_pkgs.setColumnWidth(self._COL_THEME, 90)
        # Перенос имени зависит от текущей ширины «Название» → пересчитываем высоту
        # строк при её изменении (в т.ч. при растяжении окна). Дебаунс, чтобы не
        # дёргать на каждый пиксель во время перетаскивания.
        self._rowfit_timer = QTimer(self)
        self._rowfit_timer.setSingleShot(True)
        self._rowfit_timer.timeout.connect(self.tbl_pkgs.resizeRowsToContents)
        hdr.sectionResized.connect(self._on_name_section_resized)
        self.tbl_pkgs.itemSelectionChanged.connect(self._on_pkg_selection_changed)
        # ЛКМ по уже открытому паку повторно — закрывает карточку (см.
        # _on_pkg_clicked). itemSelectionChanged тут не годится: клик по уже
        # выбранной строке не меняет выделение и сигнал не переиспускается.
        self.tbl_pkgs.clicked.connect(self._on_pkg_clicked)
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
        self.pkg_detail.setOpenLinks(False)
        self.pkg_detail.setFrameShape(QFrame.Shape.NoFrame)
        # «Копировать название» — не отдельная кнопка сбоку (занимала лишнюю
        # строку), а маленький кликабельный значок ПРЯМО в строке заголовка
        # (см. _render_package_detail_html: <a href="sigstats-copy-name">
        # внутри того же <h3>, что и название) — ловим клик через anchorClicked.
        self.pkg_detail.anchorClicked.connect(self._on_pkg_detail_anchor_clicked)

        # Клик внутри карточки НЕ закрывает её (только клик снаружи, через
        # app-wide фильтр ниже — _click_in_panel считает pkg_detail «защищённым»).
        split.addWidget(self.pkg_detail)
        split.setSizes([700, 400])
        self._pkg_split = split
        self._pkg_det_wrap = self.pkg_detail
        # Пока ничего не выбрано, карточке нечего показывать — прячем панель
        # целиком, чтобы таблица заняла всю ширину (не оставлять пустое место).
        self.pkg_detail.setVisible(False)
        left.addWidget(split, 1)

        det_btns = QHBoxLayout()
        # Все кнопки над карточкой — только значком (без подписи, по просьбе),
        # подсказка остаётся в tooltip (см. также btn_delete_siq/btn_bulk_dl
        # ниже, у них так было и раньше).
        self.btn_open_link = QPushButton()
        self.btn_open_link.setIcon(get_icon('fa5s.external-link-alt'))
        self.btn_open_link.setFixedWidth(36)
        self.btn_open_link.setToolTip("Открыть на sibrowser.ru")
        self.btn_open_link.clicked.connect(self._open_selected_link)
        self.btn_open_link.setEnabled(False)
        det_btns.addWidget(self.btn_open_link)
        self.btn_show_questions = QPushButton()
        self.btn_show_questions.setIcon(get_icon('fa5s.book-open'))
        self.btn_show_questions.setFixedWidth(36)
        self.btn_show_questions.setToolTip("Показать вопросы и ответы")
        self.btn_show_questions.clicked.connect(self._show_selected_questions)
        self.btn_show_questions.setEnabled(False)
        det_btns.addWidget(self.btn_show_questions)
        self.btn_mark_played = QPushButton()
        self.btn_mark_played.setIcon(get_icon('fa5s.check-circle'))
        self.btn_mark_played.setFixedWidth(36)
        self.btn_mark_played.setToolTip(
            "Добавить в сыграно\n\n"
            "Скрыть пак из основного списка — он попадёт в «Сыгранные пакеты» "
            "в фильтрах справа, откуда его можно вернуть обратно. Работает "
            "сразу для всех выделенных паков (Ctrl/Shift+ЛКМ).")
        self.btn_mark_played.clicked.connect(self._mark_selected_played)
        self.btn_mark_played.setEnabled(False)
        det_btns.addWidget(self.btn_mark_played)
        self.btn_add_pkg_blacklist = QPushButton()
        self.btn_add_pkg_blacklist.setIcon(get_icon('fa5s.ban', color='#f38ba8'))
        self.btn_add_pkg_blacklist.setFixedWidth(36)
        self.btn_add_pkg_blacklist.setToolTip(
            "Добавить в чёрный список\n\n"
            "Скрыть пак из списка совсем (в отличие от «Добавить в сыграно» — попадает "
            "в «Чёрный список пакетов» в фильтрах справа, откуда его можно "
            "вернуть обратно). Работает сразу для всех выделенных паков "
            "(Ctrl/Shift+ЛКМ).")
        self.btn_add_pkg_blacklist.clicked.connect(self._blacklist_selected_package)
        self.btn_add_pkg_blacklist.setEnabled(False)
        det_btns.addWidget(self.btn_add_pkg_blacklist)
        det_btns.addStretch(1)
        # «Играть» — открыть пак сразу в SIGame без скачивания .siq, как кнопка
        # «Играть» на sibrowser.ru (см. sg_sibrowser.play_url). Доступна только
        # для паков с sibrowser_id (Steam-паки так открыть нельзя — там нет
        # прямой ссылки на .siq).
        self.btn_play = QPushButton()
        self.btn_play.setIcon(get_icon('fa5s.play-circle', color='#a6e3a1'))
        self.btn_play.setFixedWidth(36)
        self.btn_play.setToolTip(
            "Играть\n\n"
            "Открыть пак сразу в SIGame (sigame.vladimirkhil.com), без "
            "скачивания .siq — так же, как кнопка «Играть» на sibrowser.ru.")
        self.btn_play.clicked.connect(self._play_selected_package)
        self.btn_play.setEnabled(False)
        det_btns.addWidget(self.btn_play)
        # «Удалить пак» — активна только когда выбран УЖЕ скачанный пак; удаляет
        # его .siq и медиа с диска (см. _delete_selected_siq). Рядом с ней —
        # уменьшенная кнопка скачивания отмеченных. Обе — только значком (без
        # подписи, по просьбе), подсказка остаётся в tooltip.
        self.btn_delete_siq = QPushButton()
        self.btn_delete_siq.setIcon(get_icon('fa5s.trash', color='#f38ba8'))
        self.btn_delete_siq.setFixedWidth(36)
        self.btn_delete_siq.setToolTip(
            "Удалить пак\n\n"
            "Удалить скачанный .siq выбранного пака и его медиа с диска "
            "(статистика в базе останется). Доступно для скачанных паков.")
        self.btn_delete_siq.clicked.connect(self._delete_selected_siq)
        self.btn_delete_siq.setEnabled(False)
        det_btns.addWidget(self.btn_delete_siq)
        # Открыть в Проводнике скачанный .siq (файл выделяется) или, если
        # скачано только медиа без самого .siq, папку медиа. Активна только для
        # реально скачанных паков — как «Удалить пак» рядом.
        self.btn_open_folder = QPushButton()
        self.btn_open_folder.setIcon(get_icon('fa5s.folder-open', color='#f9e2af'))
        self.btn_open_folder.setFixedWidth(36)
        self.btn_open_folder.setToolTip(
            "Открыть в проводнике\n\n"
            "Открыть Проводник на скачанном .siq (файл выделится) выбранного "
            "пака. Доступно для скачанных паков.")
        self.btn_open_folder.clicked.connect(self._open_selected_folder)
        self.btn_open_folder.setEnabled(False)
        det_btns.addWidget(self.btn_open_folder)
        self.btn_bulk_dl = QPushButton()
        self.btn_bulk_dl.setIcon(get_icon('fa5s.download'))
        self.btn_bulk_dl.setFixedWidth(36)
        self.btn_bulk_dl.setToolTip(
            "Скачать .siq\n\n"
            "Скачать .siq всех выделенных паков. Несколько сразу выделяются "
            "как в проводнике: Ctrl+ЛКМ — по одному, Shift+ЛКМ — диапазоном.")
        self.btn_bulk_dl.clicked.connect(self._bulk_download)
        det_btns.addWidget(self.btn_bulk_dl)
        # Папка, куда сохраняются скачиваемые .siq — по умолчанию обычная папка
        # загрузок (см. sigstats.config.load_packages_dir); эта кнопка позволяет
        # выбрать другую, не трогая исходники.
        self.btn_pkg_dir = QPushButton()
        self.btn_pkg_dir.setIcon(get_icon('fa5s.folder-open'))
        self.btn_pkg_dir.setFixedWidth(36)
        self.btn_pkg_dir.clicked.connect(self._choose_packages_dir)
        det_btns.addWidget(self.btn_pkg_dir)
        self._update_pkg_dir_tooltip()
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
            chk.setChecked(g in ("Полные", "Большие", "Неизвестно"))
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
        self.lbl_cat_min = QLabel("50")
        self.sl_cat_min.valueChanged.connect(lambda v: self.lbl_cat_min.setText(str(v)))
        self.sl_cat_min.valueChanged.connect(self._refresh_packages_table)
        cat_min_row = QHBoxLayout()
        cat_min_row.addWidget(self.sl_cat_min, 1)
        cat_min_row.addWidget(self.lbl_cat_min)
        fl.addLayout(cat_min_row, 12, 0, 1, 4)

        self.chk_show_played = QCheckBox("Показывать сыгранные")
        self.chk_show_played.setToolTip(
            "Паки, отмеченные как «уже сыграно», по умолчанию скрыты из списка — "
            "включите, чтобы снова их увидеть. Вернувшиеся в список паки "
            "подсвечиваются лёгким оттенком строки.")
        self.chk_show_played.toggled.connect(self._refresh_packages_table)
        fl.addWidget(self.chk_show_played, 13, 0, 1, 4)

        self.chk_show_pkg_blacklist = QCheckBox("Игнорировать чёрный список пакетов")
        self.chk_show_pkg_blacklist.setToolTip(
            "Паки из «Чёрного списка пакетов» по умолчанию скрыты из списка — "
            "включите, чтобы снова их увидеть. Подсвечиваются лёгким оттенком строки.")
        self.chk_show_pkg_blacklist.toggled.connect(self._refresh_packages_table)
        fl.addWidget(self.chk_show_pkg_blacklist, 14, 0, 1, 4)

        self.chk_show_author_blacklist = QCheckBox("Игнорировать чёрный список авторов")
        self.chk_show_author_blacklist.setToolTip(
            "Паки авторов из «Чёрного списка авторов» по умолчанию скрыты из "
            "списка — включите, чтобы снова их увидеть. Подсвечиваются лёгким "
            "оттенком строки.")
        self.chk_show_author_blacklist.toggled.connect(self._refresh_packages_table)
        fl.addWidget(self.chk_show_author_blacklist, 15, 0, 1, 4)

        self.chk_only_with_stats = QCheckBox("Только паки со статистикой")
        self.chk_only_with_stats.setToolTip(
            "Ограничить список только паками, для которых на SIStatistics уже "
            "есть данные (кто-то играл онлайн). ВЫКЛЮЧЕНО по умолчанию — "
            "свежесобранные паки (особенно через «Собрать паки автора») часто "
            "ещё без статистики: раньше они не попадали в список вообще без "
            "единого видимого/отключаемого фильтра.")
        self.chk_only_with_stats.toggled.connect(self._refresh_packages_table)
        fl.addWidget(self.chk_only_with_stats, 16, 0, 1, 4)

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
        self._box_author_blacklist = QGroupBox()
        box = self._box_author_blacklist
        v = QVBoxLayout(box)
        lbl = QLabel("Паки этих авторов пропускаются при сборе и не "
                     "показываются в таблице.")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.lst_blacklist = QListWidget()
        self.lst_blacklist.addItems(self._author_blacklist)
        self.lst_blacklist.setMaximumHeight(110)
        self.lst_blacklist.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lst_blacklist.customContextMenuRequested.connect(self._on_author_blacklist_context_menu)
        v.addWidget(self.lst_blacklist)
        self._update_author_blacklist_title()

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

    def _update_author_blacklist_title(self):
        self._box_author_blacklist.setTitle(
            f"Чёрный список авторов ({len(self._author_blacklist)})")

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
        # В начало — список сортирован по моменту добавления, новые сверху.
        self._author_blacklist.insert(0, name)
        self.lst_blacklist.insertItem(0, name)
        self._update_author_blacklist_title()
        sg_config.save_author_blacklist(self._author_blacklist)
        self._refresh_packages_table()

    def _remove_blacklist_author(self):
        for item in self.lst_blacklist.selectedItems():
            name = item.text()
            self._author_blacklist = [a for a in self._author_blacklist if a != name]
            self.lst_blacklist.takeItem(self.lst_blacklist.row(item))
        self._update_author_blacklist_title()
        sg_config.save_author_blacklist(self._author_blacklist)
        self._refresh_packages_table()

    def _build_played_group(self) -> QGroupBox:
        self._box_played = QGroupBox()
        box = self._box_played
        v = QVBoxLayout(box)
        lbl = QLabel("Паки, отмеченные кнопкой «Добавить в сыграно» у выбранного пака, "
                     "скрыты из основного списка (см. чекбокс «Показывать "
                     "сыгранные» в фильтрах).")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.lst_played = QListWidget()
        self.lst_played.setMaximumHeight(110)
        self.lst_played.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lst_played.customContextMenuRequested.connect(self._on_played_context_menu)
        v.addWidget(self.lst_played)
        row = QHBoxLayout()
        btn_unplay = QPushButton("Вернуть в список")
        btn_unplay.setIcon(get_icon('fa5s.undo'))
        btn_unplay.clicked.connect(self._unmark_played)
        row.addWidget(btn_unplay)
        btn_tier = QPushButton("Тир-лист")
        btn_tier.setIcon(get_icon('fa5s.trophy', color='#f9e2af'))
        btn_tier.setToolTip("Открыть тир-лист: разложить сыгранные паки по "
                            "уровням, добавить комментарии и свои теги.")
        btn_tier.clicked.connect(self._open_tier_list)
        row.addWidget(btn_tier)
        v.addLayout(row)
        self._update_played_title()
        return box

    def _update_played_title(self):
        self._box_played.setTitle(f"Сыгранные пакеты ({len(self._played_ids)})")

    def _refresh_played_list(self):
        self.lst_played.clear()
        self._update_played_title()
        if self._pkgs_df is None or self._pkgs_df.empty or not self._played_ids:
            return
        names = self._pkgs_df.set_index("id")["name"]
        # self._played_ids уже в порядке добавления (новые первыми) — см.
        # _mark_selected_played, тут просто идём по нему как есть.
        for pid in self._played_ids:
            name = names.get(pid, f"#{pid}")
            added = self._played_added_at.get(pid)
            label = f"{name}  ·  добавлен {_fmt_date(added)}" if added else str(name)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, int(pid))
            self.lst_played.addItem(item)

    def _mark_selected_played(self):
        """Кнопка «Добавить в сыграно» — сразу для ВСЕХ выделенных паков
        (Ctrl/Shift+ЛКМ)."""
        self._mark_played_ids([int(r["id"]) for r in self._selected_pkg_rows()])

    def _mark_played_for_row(self, r):
        if r is None:
            return
        self._mark_played_ids([int(r["id"])])

    def _mark_played_ids(self, pids):
        """Один общий save+refresh на всю пачку — при пометке десятка паков
        по одному перезапись файлов и перестроение таблицы на каждый id заметно
        подтормаживали."""
        if not pids:
            return
        now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        for pid in pids:
            if pid not in self._played_ids:
                self._played_ids.insert(0, pid)
            self._played_added_at[pid] = now
        sg_config.save_played_packages(self._played_ids)
        sg_config.save_played_added_at(self._played_added_at)
        self._refresh_played_list()
        self._refresh_packages_table()

    def _unmark_played_ids(self, pids):
        changed = False
        for pid in pids:
            if pid in self._played_ids:
                self._played_ids.remove(pid)
                self._played_added_at.pop(pid, None)
                changed = True
        if changed:
            sg_config.save_played_packages(self._played_ids)
            sg_config.save_played_added_at(self._played_added_at)
            self._refresh_played_list()
            self._refresh_packages_table()
        return changed

    def _unmark_played(self):
        pids = [item.data(Qt.ItemDataRole.UserRole) for item in self.lst_played.selectedItems()]
        self._unmark_played_ids(pids)

    def _unmark_played_for_row(self, r):
        if r is None:
            return
        self._unmark_played_ids([int(r["id"])])

    def _open_tier_list(self):
        """Отдельное окно тир-листа: разложить сыгранные паки по уровням, у
        каждого — комментарий и пользовательские теги (см. _TierListDialog).
        Окно одно на приложение — повторный клик поднимает уже открытое, а не
        плодит вторую копию (закрытие крестиком только прячет окно, см.
        QDialog.closeEvent по умолчанию, поэтому isVisible() тут надёжен)."""
        existing = getattr(self, "_tier_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        import pandas as pd
        state = sg_config.load_tier_list()
        placed = [int(k) for k in state.get("placements", {})]
        # Паки для тир-листа: все сыгранные + уже размещённые ранее (даже если
        # их успели убрать из «сыгранных») — порядок сохраняем, дубли убираем.
        pids = list(dict.fromkeys(list(self._played_ids) + placed))
        if not pids:
            msgbox_information(
                self, "Тир-лист",
                "Пока нечего раскладывать: отметьте паки кнопкой «Добавить в сыграно» — "
                "они появятся здесь.")
            return
        names = None
        if self._pkgs_df is not None and not self._pkgs_df.empty:
            names = self._pkgs_df.set_index("id")["name"]
        pkg_info = {}
        for pid in pids:
            nm = names.get(pid) if names is not None else None
            pkg_info[int(pid)] = str(nm) if (nm is not None and not pd.isna(nm)) else f"#{pid}"
        # Немодально (show, не exec) + ссылка на себя, чтобы окно не удалилось
        # сборщиком мусора. Иначе (модальный exec) у окна нет своей кнопки в
        # панели задач и клик по иконке проги его не сворачивает.
        self._tier_dialog = _TierListDialog(pkg_info, self)
        self._tier_dialog.show()
        self._tier_dialog.raise_()
        self._tier_dialog.activateWindow()

    def _build_pkg_blacklist_group(self) -> QGroupBox:
        self._box_pkg_blacklist = QGroupBox()
        box = self._box_pkg_blacklist
        v = QVBoxLayout(box)
        lbl = QLabel("Паки, добавленные сюда через ПКМ на строке пака "
                     "(«Добавить пак в чёрный список»), больше не показываются "
                     "в списке слева.")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.lst_pkg_blacklist = QListWidget()
        self.lst_pkg_blacklist.setMaximumHeight(110)
        self.lst_pkg_blacklist.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lst_pkg_blacklist.customContextMenuRequested.connect(self._on_pkg_blacklist_context_menu)
        v.addWidget(self.lst_pkg_blacklist)
        btn_unblacklist = QPushButton("Убрать из чёрного списка")
        btn_unblacklist.setIcon(get_icon('fa5s.undo'))
        btn_unblacklist.clicked.connect(self._unblacklist_selected_packages)
        v.addWidget(btn_unblacklist)
        self._update_pkg_blacklist_title()
        return box

    def _update_pkg_blacklist_title(self):
        self._box_pkg_blacklist.setTitle(
            f"Чёрный список пакетов ({len(self._pkg_blacklist)})")

    def _refresh_pkg_blacklist_list(self):
        self.lst_pkg_blacklist.clear()
        self._update_pkg_blacklist_title()
        if self._pkgs_df is None or self._pkgs_df.empty or not self._pkg_blacklist:
            return
        names = self._pkgs_df.set_index("id")["name"]
        # self._pkg_blacklist уже в порядке добавления (новые первыми) — см.
        # _blacklist_package, тут просто идём по нему как есть.
        for pid in self._pkg_blacklist:
            name = names.get(pid, f"#{pid}")
            added = self._pkg_blacklist_added_at.get(pid)
            label = f"{name}  ·  добавлен {_fmt_date(added)}" if added else str(name)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, int(pid))
            self.lst_pkg_blacklist.addItem(item)

    def _blacklist_package(self, package_id: int):
        self._blacklist_packages([int(package_id)])

    def _blacklist_packages(self, pids):
        """Пачкой — один save+refresh на всё выделение (см. _mark_played_ids)."""
        if not pids:
            return
        now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        for pid in pids:
            pid = int(pid)
            if pid not in self._pkg_blacklist:
                self._pkg_blacklist.insert(0, pid)
            self._pkg_blacklist_added_at[pid] = now
        sg_config.save_package_blacklist(self._pkg_blacklist)
        sg_config.save_package_blacklist_added_at(self._pkg_blacklist_added_at)
        self._refresh_pkg_blacklist_list()
        self._refresh_packages_table()

    def _blacklist_selected_package(self):
        """Кнопка «Добавить в чёрный список» рядом с «Добавить в сыграно» — та же
        логика, что и пункт ПКМ-меню (_on_pkg_context_menu), сразу для ВСЕХ
        выделенных паков (Ctrl/Shift+ЛКМ)."""
        self._blacklist_packages([int(r["id"]) for r in self._selected_pkg_rows()])

    def _unblacklist_selected_packages(self):
        changed = False
        for item in self.lst_pkg_blacklist.selectedItems():
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid in self._pkg_blacklist:
                self._pkg_blacklist.remove(pid)
                self._pkg_blacklist_added_at.pop(pid, None)
                changed = True
        if changed:
            sg_config.save_package_blacklist(self._pkg_blacklist)
            sg_config.save_package_blacklist_added_at(self._pkg_blacklist_added_at)
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

        lbl_min_started = QLabel("Минимум начатых игр:")
        lbl_min_started.setToolTip(
            "Паки, в которые сыграли меньше N раз, пропускаются. Скачивания на "
            "сайте легко накрутить, а начатые игры — нет.")
        v.addWidget(lbl_min_started)
        self.sp_min_started_collect = QSpinBox(); self.sp_min_started_collect.setRange(0, 1_000_000)
        self.sp_min_started_collect.setValue(100); self.sp_min_started_collect.setSingleStep(10)
        v.addWidget(self.sp_min_started_collect)

        v.addWidget(QLabel("Максимум новых паков за раз:"))
        self.sp_max_new = QSpinBox(); self.sp_max_new.setRange(5, 1000)
        self.sp_max_new.setValue(50); self.sp_max_new.setSingleStep(5)
        v.addWidget(self.sp_max_new)

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

        # период (только режим «по дате»)
        self.lbl_period = QLabel("Период:")
        v.addWidget(self.lbl_period)
        self.cmb_period = QComboBox()
        self.cmb_period.addItems(list(_PERIODS) + ["За всё время", "Своя дата"])
        self.cmb_period.setCurrentText("Месяц")
        v.addWidget(self.cmb_period)
        self.de_custom = QDateEdit()
        self.de_custom.setCalendarPopup(True)
        self.de_custom.setDisplayFormat("dd.MM.yyyy")
        self.de_custom.setDate(_dt.date.today())
        v.addWidget(self.de_custom)

        def _sync_date_visibility():
            is_date_mode = self.rb_mode_date.isChecked()
            for w in (self.lbl_period, self.cmb_period, self.de_custom):
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
        self.btn_collect_author.clicked.connect(lambda: self._start_collect_author())
        v.addWidget(self.btn_collect_author)

        v.addWidget(_hline())

        # ── Steam Workshop (SIGame, app 3553500) ─────────────────────────────
        # Только метаданные через Steam Web API — сами файлы воркшопа не
        # скачиваются (нужен SteamCMD, депо-скачивание вместо обычного GET,
        # отдельная задача). Импортированные паки помечены source='steam' и
        # показаны в таблице значком Steam слева от названия.
        lbl_steam = QLabel(
            "Импорт метаданных из Steam Workshop SIGame (только название/автор/"
            "описание/подписки — без скачивания файлов). Нужен бесплатный ключ: "
            '<a href="https://steamcommunity.com/dev/apikey" '
            'style="color:#89b4fa;">steamcommunity.com/dev/apikey</a>')
        lbl_steam.setOpenExternalLinks(True)
        lbl_steam.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lbl_steam.setWordWrap(True)
        v.addWidget(lbl_steam)
        self.ed_steam_api_key = QLineEdit()
        self.ed_steam_api_key.setPlaceholderText("Ключ Steam Web API")
        self.ed_steam_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        v.addWidget(self.ed_steam_api_key)
        v.addWidget(QLabel("Минимум подписок:"))
        self.sp_steam_min_subs = QSpinBox(); self.sp_steam_min_subs.setRange(0, 1_000_000)
        self.sp_steam_min_subs.setSingleStep(10)
        v.addWidget(self.sp_steam_min_subs)
        v.addWidget(QLabel("Максимум новых паков за раз:"))
        self.sp_steam_max_new = QSpinBox(); self.sp_steam_max_new.setRange(5, 1000)
        self.sp_steam_max_new.setValue(50); self.sp_steam_max_new.setSingleStep(5)
        v.addWidget(self.sp_steam_max_new)
        self.btn_collect_steam = QPushButton("Импортировать из Steam Workshop")
        self.btn_collect_steam.setIcon(get_icon('fa5b.steam', color='#66c0f4'))
        self.btn_collect_steam.clicked.connect(self._start_collect_steam)
        v.addWidget(self.btn_collect_steam)

        # Точечное добавление ОДНОГО пака по прямой ссылке/id — без обхода
        # всего каталога (по просьбе; использует тот же ключ выше).
        v.addWidget(QLabel("Добавить один пак по ссылке/id:"))
        steam_link_row = QHBoxLayout()
        self.ed_steam_link = QLineEdit()
        self.ed_steam_link.setPlaceholderText(
            "https://steamcommunity.com/sharedfiles/filedetails/?id=... или голый id")
        self.ed_steam_link.returnPressed.connect(self._add_steam_by_link)
        steam_link_row.addWidget(self.ed_steam_link, 1)
        self.btn_add_steam_link = QPushButton("Добавить")
        self.btn_add_steam_link.setIcon(get_icon('fa5s.plus', color='#66c0f4'))
        self.btn_add_steam_link.clicked.connect(self._add_steam_by_link)
        steam_link_row.addWidget(self.btn_add_steam_link)
        v.addLayout(steam_link_row)

        return box

    # ── Запуск фоновых задач сбора ───────────────────────────────────────────
    def _job_running(self) -> bool:
        return self._active_job is not None

    def _begin_job(self, task):
        self._active_job = task
        self.btn_stop.setEnabled(True)
        self.btn_start_collect.setEnabled(False)
        self.btn_collect_author.setEnabled(False)
        self.btn_collect_steam.setEnabled(False)
        # Кнопка «Собрать статистику» во вкладке «Авторы» — тот же сбор
        # по автору, что и на «Пакеты», просто запускается прямо отсюда.
        btn_here = getattr(self, "btn_collect_author_here", None)
        if btn_here is not None:
            btn_here.setEnabled(False)
        self.progress.setValue(0)
        self._pool.start(task)

    def _end_job(self):
        self._active_job = None
        self.btn_stop.setEnabled(False)
        self.btn_start_collect.setEnabled(True)
        self.btn_collect_author.setEnabled(True)
        self.btn_collect_steam.setEnabled(True)
        btn_here = getattr(self, "btn_collect_author_here", None)
        if btn_here is not None:
            btn_here.setEnabled(True)

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
        self._mirror_collect_status(msg)
        self._log(f"Поиск пакетов: {msg}")

    def _mirror_collect_status(self, text: str):
        """Прогресс/статус сбора живёт физически на вкладке «Пакеты»
        (self.lbl_status) — если сбор запущен кнопкой «Собрать статистику» на
        «Авторы» (см. _start_collect_author_from_authors_tab), дублируем текст
        туда же, чтобы не заставлять переключать вкладку ради прогресса."""
        lbl = getattr(self, "lbl_authors_collect_status", None)
        if lbl is not None:
            lbl.setText(text)

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
            elif period == "За всё время":
                cutoff_date = None
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
        self._mirror_collect_status(msg)
        self._log(f"Поиск пакетов: {msg}")
        self._reload_data()

    def _on_job_failed(self, err):
        self._end_job()
        msg = f"Ошибка: {err}"
        self.lbl_status.setText(msg)
        self._mirror_collect_status(msg)
        self._log(f"Поиск пакетов: ошибка сбора: {err}")

    def _start_collect_author_from_authors_tab(self):
        """Кнопка «Собрать статистику» на вкладке «Авторы» — тот же сбор по
        автору, что и «Собрать паки автора» на «Пакеты», только ник берётся из
        поля поиска этой вкладки и запускать можно не переключаясь."""
        if self._job_running():
            msgbox_information(
                self, "Сбор уже идёт",
                "Дождитесь окончания текущего сбора (прогресс — ниже поля поиска).")
            return
        name = self.ed_author_search.text().strip()
        if not name:
            msgbox_information(
                self, "Укажите автора",
                "Впишите ник автора в поле поиска слева, потом нажмите «Собрать статистику».")
            return
        self._mirror_collect_status(f"Собираю паки автора «{name}»…")
        self._start_collect_author(author=name)

    def _start_collect_author(self, author: str | None = None):
        if self._job_running():
            return
        if author is None:
            author = self.ed_author.text().strip()
        else:
            author = author.strip()
        if not author:
            return
        self._last_collect_key = None  # у collect_author нет страничного кэша
        # БЕЗ author_blacklist=... — это явный целевой сбор ОДНОГО автора, ЧС
        # тут не участвует (см. docstring collect_author в sigstats/collector.py).
        task = _JobTask(sg_collector.collect_author, author=author)
        task.signals.progress.connect(self._on_job_progress)
        task.signals.package_added.connect(self._on_package_added)
        task.signals.finished.connect(self._on_collect_finished)
        task.signals.failed.connect(self._on_job_failed)
        self._begin_job(task)

    def _start_collect_steam(self):
        if self._job_running():
            return
        api_key = self.ed_steam_api_key.text().strip()
        if not api_key:
            msgbox_warning(
                self, "Нужен ключ Steam Web API",
                "Получите бесплатный ключ на steamcommunity.com/dev/apikey и "
                "вставьте его в поле выше.")
            return
        self._last_collect_key = None  # у Steam Workshop нет страничного кэша
        task = _JobTask(
            sg_collector.collect_steam_workshop,
            api_key=api_key,
            max_new=int(self.sp_steam_max_new.value()),
            min_subscriptions=int(self.sp_steam_min_subs.value()),
            author_blacklist=self._blacklist_set(),
        )
        task.signals.progress.connect(self._on_job_progress)
        task.signals.package_added.connect(self._on_package_added)
        task.signals.finished.connect(self._on_collect_steam_finished)
        task.signals.failed.connect(self._on_job_failed)
        self._begin_job(task)

    def _on_collect_steam_finished(self, result):
        self._end_job()
        extra = (f" · отсеяно по подпискам: {result['skipped_low_subs']}"
                 if result.get("skipped_low_subs") else "")
        extra += (f" · отсеяно по чёрному списку: {result['skipped_blacklisted']}"
                  if result.get("skipped_blacklisted") else "")
        msg = (f"Steam Workshop: новых {result['new']} · со статистикой: "
               f"{result['with_stats']} · без статистики: {result['no_stats']}{extra}")
        self.progress.setValue(100)
        self.lbl_status.setText(msg)
        self._log(f"Поиск пакетов: {msg}")
        self._reload_data()

    def _add_steam_by_link(self):
        """Точечно добавляет один Steam-пак по прямой ссылке/id — без обхода
        всего каталога, как «Импортировать из Steam Workshop» выше (по
        просьбе: не всегда нужного пака дожидаешься массовым импортом)."""
        if self._job_running():
            return
        api_key = self.ed_steam_api_key.text().strip()
        if not api_key:
            msgbox_warning(
                self, "Нужен ключ Steam Web API",
                "Получите бесплатный ключ на steamcommunity.com/dev/apikey и "
                "вставьте его в поле выше.")
            return
        link = self.ed_steam_link.text().strip()
        if not link:
            return
        self.btn_add_steam_link.setEnabled(False)
        self.ed_steam_link.setEnabled(False)
        self.lbl_status.setText("Добавляю пак Steam Workshop по ссылке…")
        task = _SteamOneTask(link, api_key, self._blacklist_set())

        def _done(result):
            self.btn_add_steam_link.setEnabled(True)
            self.ed_steam_link.setEnabled(True)
            if result.get("ok"):
                self.ed_steam_link.clear()
                self.lbl_status.setText(f"Добавлен пак «{result['name']}».")
                self._log(f"Поиск пакетов: добавлен по ссылке пак Steam «{result['name']}»")
                self._reload_data()
            else:
                self.lbl_status.setText("Не удалось добавить пак по ссылке.")
                msgbox_warning(self, "Не удалось добавить пак",
                               result.get("error") or "Неизвестная ошибка.")
        task.signals.finished.connect(_done)
        self._pool.start(task)

    # ── Фильтрация и таблица паков ───────────────────────────────────────────
    def _filtered_packages_df(self):
        import pandas as pd
        df = self._pkgs_df
        if df is None or df.empty:
            return df if df is not None else pd.DataFrame()

        # has_stats==1 раньше отсекался ЖЁСТКО, безо всякого чекбокса — пак,
        # для которого SIStatistics ещё не набрала данных (например только что
        # собранный «Собрать паки автора»), был невидим в списке без единой
        # видимой причины. Теперь это обычный опциональный фильтр (выключен по
        # умолчанию, см. chk_only_with_stats) — по умолчанию список показывает
        # ВСЕ паки, включая ещё без статистики.
        view = df.copy()
        if self.chk_only_with_stats.isChecked():
            view = view[view["has_stats"] == 1]
        if self._played_ids and not self.chk_show_played.isChecked():
            view = view[~view["id"].isin(self._played_ids)]
        if self._pkg_blacklist and not self.chk_show_pkg_blacklist.isChecked():
            view = view[~view["id"].isin(self._pkg_blacklist)]
        groups = [g for g, chk in self._len_checks.items() if chk.isChecked()]
        if groups:
            view = view[view["length_group"].isin(groups)]
        diffs = [d for d, chk in self._diff_checks.items() if chk.isChecked()]
        if diffs:
            view = view[view["difficulty"].isin(diffs)]
        if self.chk_only_siq.isChecked():
            view = view[view["siq_downloaded"] == 1]
        if self._author_blacklist and not self.chk_show_author_blacklist.isChecked():
            needles = [a.lower() for a in self._author_blacklist]
            view = view[~view["authors_display"].fillna("").str.lower().apply(
                lambda s: any(n in s for n in needles)).astype(bool)]
        if self.sl_min_comp.value() > 0:
            view = view[view["completion_pct"].fillna(-1) >= self.sl_min_comp.value()]
        if self.sp_min_started.value() > 0:
            view = view[view["started_games"].fillna(0) >= self.sp_min_started.value()]

        cat_sel = self.cmb_cat_filter.currentText()
        cat_min = self.sl_cat_min.value()
        if cat_sel != _ANY_TOPIC:
            # .astype(bool) — на уже пустом view .apply() возвращает маску
            # dtype=object, и view[mask] тогда трактуется как выбор КОЛОНОК
            # (список labels), а не строк, обнуляя все столбцы (включая
            # completion_rate → KeyError в sort_values ниже).
            view = view[view["cat_map"].apply(
                lambda m: m.get(cat_sel, 0) >= cat_min).astype(bool)]

        needle = self.ed_search.text().strip().lower()
        if needle:
            mask = (view["name"].str.lower().str.contains(needle, na=False)
                    | view["authors_display"].str.lower().str.contains(needle, na=False))
            try:
                # SQLite'шный lower()/LIKE регистронезависимы ТОЛЬКО для ASCII —
                # для кириллицы lower('Музыка') возвращает строку без изменений,
                # так что WHERE lower(name) LIKE ? никогда не совпадал ни с одной
                # темой, где есть заглавная буква (то есть почти никогда).
                # Фильтруем в Python — str.lower() тут корректно работает с юникодом.
                with sg_db.connect() as conn:
                    themes_df = pd.read_sql_query(
                        "SELECT DISTINCT package_id, name FROM themes", conn)
                ids = themes_df.loc[
                    themes_df["name"].fillna("").str.lower().str.contains(needle, na=False),
                    "package_id"].tolist()
            except Exception:
                ids = []
            view = view[mask | view["id"].isin(ids)]

        # Свежесобранные паки — сверху по умолчанию (collected_at проставляется
        # при первом сохранении пака в БД, см. sigstats/db.py::upsert_package;
        # обновление уже известных метрик его не трогает). Любую другую
        # сортировку пользователь всегда может включить кликом по заголовку
        # столбца — таблица ниже setSortingEnabled(True).
        return view.sort_values("collected_at", ascending=False, na_position="last")

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

        # Таблица ниже полностью перестраивается (setRowCount(0) + заново
        # insertRow) — это сбрасывает выделение и закрывало карточку пака при
        # каждом изменении поиска/фильтра, даже если сам пак остаётся в
        # результатах. Запоминаем его id, чтобы вернуть выделение после
        # перестройки (см. конец метода).
        prev_detail_pid = self._current_detail_pid

        view = self._filtered_packages_df()
        self._pkg_view_df = view
        t = self.tbl_pkgs
        t.setSortingEnabled(False)
        t.setRowCount(0)
        for _, r in view.iterrows():
            row = t.rowCount()
            t.insertRow(row)

            # Колонка 0 — «место» пака в текущем порядке. Сам номер рисует
            # _AccentBarDelegate по index.row(), в ячейке его нет (иначе setText
            # при включённой сортировке пересортировывал бы таблицу). Раньше тут
            # был чекбокс для массового скачивания — его роль перешла к обычному
            # выделению строк (Ctrl/Shift+ЛКМ, см. ExtendedSelection).
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setData(Qt.ItemDataRole.UserRole, int(r["id"]))
            t.setItem(row, 0, chk_item)

            name_item = QTableWidgetItem(str(r["name"]))
            # Галочка «скачан» / бегущий процент рисует _PkgNameDelegate; своего
            # tooltip у ячейки НЕТ (иначе всплывает синее системное окно, которое
            # запрещено в проекте — имя и так переносится по словам целиком).
            name_item.setData(_PkgNameDelegate.DownloadedRole, r.get("siq_downloaded") == 1)
            name_item.setData(_PkgNameDelegate.SteamRole, r.get("source") == "steam")
            t.setItem(row, 1, name_item)
            t.setItem(row, 2, QTableWidgetItem(str(r.get("authors_display") or "")))
            dp = r.get("date_published")
            dp_key = str(dp)[:10] if (dp is not None and dp == dp) else None
            t.setItem(row, 3, _NumItem(_fmt_date(dp), dp_key))
            qc = r.get("question_count")
            qc_text = "—" if qc != qc or qc is None else str(int(qc))
            t.setItem(row, 4, _NumItem(qc_text, _num_or_zero(qc)))
            size_mb = r.get("size_mb")
            has_size = size_mb == size_mb and size_mb is not None
            t.setItem(row, 5, _NumItem(f"{size_mb:.1f} МБ" if has_size else "—",
                                        size_mb if has_size else -1))
            ap = r.get("answer_pct")
            diff = r.get("difficulty")
            diff_item = _NumItem(diff if isinstance(diff, str) else "—", ap if ap == ap else -1)
            if diff in _DIFF_COLORS:
                diff_item.setForeground(QColor(_DIFF_COLORS[diff]))
            t.setItem(row, 6, diff_item)
            dl = r.get("download_count")
            t.setItem(row, 7, _NumItem("—" if dl != dl or dl is None else str(int(dl)), _num_or_zero(dl)))
            comp = r.get("completion_pct")
            t.setItem(row, 8, _NumItem(_fmt_pct(comp, 1), comp if comp == comp else -1))
            # % попыток — жёлтым, % правильных — зелёным (по просьбе).
            ap_item = _NumItem(_fmt_pct(ap, 0), ap if ap == ap else -1)
            ap_item.setForeground(QColor("#f9e2af"))
            t.setItem(row, 9, ap_item)
            cp = r.get("correct_pct")
            cp_item = _NumItem(_fmt_pct(cp, 0), cp if cp == cp else -1)
            cp_item.setForeground(QColor("#a6e3a1"))
            t.setItem(row, 10, cp_item)
            sg_ = r.get("started_games")
            t.setItem(row, 11, _NumItem("—" if sg_ != sg_ or sg_ is None else str(int(sg_)), _num_or_zero(sg_)))
            t.setItem(row, 12, QTableWidgetItem(_dominant_category(r.get("categories"))))
            t.setItem(row, 13, QTableWidgetItem(str(r.get("duration_str") or "—")))
            t.setItem(row, 14, QTableWidgetItem(str(r.get("length_group") or "")))

            # Доминирующая тема пака → цветная полоска слева от строки (см.
            # _AccentBarDelegate/_CATEGORY_ACCENT): красная у аниме, фиолетовая
            # у музыки. Роль лежит на чек-ячейке (колонка 0, там же id пака).
            cats = r.get("categories") if isinstance(r.get("categories"), list) else []
            top_cat = _top_category(cats)
            accent = _CATEGORY_ACCENT.get((top_cat or {}).get("name"))
            if accent:
                chk_item.setData(_AccentBarDelegate.AccentRole, accent)

            # Пак попал в список ТОЛЬКО благодаря «игнорировать» чекбоксу справа
            # (иначе он был бы отфильтрован _filtered_packages_df) — подсвечиваем
            # фон строки лёгким оттенком, чтобы было видно, почему пак обычно
            # скрыт (см. _ROW_STATUS_TINT). Несколько причин сразу — приоритет
            # чёрный список пакета > чёрный список автора > уже сыграно.
            pid = int(r["id"])
            tint = None
            if pid in self._pkg_blacklist:
                tint = _ROW_STATUS_TINT["pkg_bl"]
            elif self._author_blacklist and any(
                    a.lower() in str(r.get("authors_display") or "").lower()
                    for a in self._author_blacklist):
                tint = _ROW_STATUS_TINT["author_bl"]
            elif pid in self._played_ids:
                tint = _ROW_STATUS_TINT["played"]
            if tint is not None:
                # Роль, а НЕ setBackground: фон ячейки в этой таблице рисует
                # QStyleSheetStyle (правило QTableWidget::item в глобальном
                # STYLESHEET) и BackgroundRole из модели не смотрит — заливку
                # кладёт делегат, см. _RowTintDelegate.
                for col in range(t.columnCount()):
                    cell = t.item(row, col)
                    if cell is not None:
                        cell.setData(_RowTintDelegate.TintRole, tint)
        t.setSortingEnabled(True)
        t.resizeRowsToContents()
        self.lbl_pkg_count.setText(f"Найдено пакетов: {len(view)}")

        if prev_detail_pid is not None:
            # Если пака больше нет в отфильтрованном списке — карточка остаётся
            # закрытой (setRowCount(0) выше уже сбросил выделение и закрыл её).
            for row in range(t.rowCount()):
                chk = t.item(row, 0)
                if chk is not None and chk.data(Qt.ItemDataRole.UserRole) == prev_detail_pid:
                    t.selectRow(row)
                    break

    def _on_name_section_resized(self, index, _old, _new):
        # Перенос имени по словам зависит от ширины колонки «Название» — при её
        # изменении пересчитываем высоту строк (дебаунс через _rowfit_timer).
        if index == self._COL_NAME:
            self._rowfit_timer.start(60)

    # ── Полноэкранный режим таблицы пакетов ──────────────────────────────────
    def _toggle_pkgs_fullscreen(self):
        if self._pkg_fullscreen_host is not None:
            self._exit_pkgs_fullscreen()
        else:
            self._enter_pkgs_fullscreen()

    def _enter_pkgs_fullscreen(self):
        if self._pkg_fullscreen_host is not None or _present_fullscreen is None:
            return
        # removeWidget ДО репарентинга — иначе старый layout продолжает держать
        # QLayoutItem на этот виджет, и повторный toggle зарегистрирует его там
        # дважды (Qt.addWidget/insertWidget не убирает виджет из его прежнего
        # layout сам по себе, только меняет parent()).
        self._pkg_left_layout.removeWidget(self._pkg_split)
        host = _FullscreenHost(self._exit_pkgs_fullscreen)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self._pkg_split, 1)
        self._pkg_fullscreen_host = host
        self.btn_pkgs_fullscreen.setIcon(get_icon('fa5s.compress'))
        self.btn_pkgs_fullscreen.setToolTip("Свернуть (Esc)")
        _present_fullscreen(host, self)
        host.setFocus(Qt.FocusReason.OtherFocusReason)

    def _exit_pkgs_fullscreen(self):
        host = self._pkg_fullscreen_host
        if host is None:
            return
        self._pkg_fullscreen_host = None
        host.layout().removeWidget(self._pkg_split)
        # Возвращаем сплиттер обратно в исходный layout — сразу после строки
        # со счётчиком найденных пакетов (индекс 1).
        self._pkg_left_layout.insertWidget(1, self._pkg_split, 1)
        self._pkg_split.show()
        try:
            host.close()
            host.deleteLater()
        except Exception:
            pass
        self.btn_pkgs_fullscreen.setIcon(get_icon('fa5s.expand'))
        self.btn_pkgs_fullscreen.setToolTip("Полноэкранный режим таблицы (Esc — выйти)")

    def _on_pkg_context_menu(self, pos):
        """ПКМ на строке пака: те же действия, что и кнопки под таблицей
        (открыть/вопросы/играть/сыграно/скачать/удалить), плюс чёрный список
        пака и/или его авторов."""
        index = self.tbl_pkgs.indexAt(pos)
        if not index.isValid():
            return
        # ПКМ по строке ВНЕ текущего выделения работает как обычный клик —
        # выделяет её одну. ПКМ по строке, которая уже входит в выделение,
        # выделение НЕ сбрасывает (иначе Ctrl/Shift-набор из нескольких паков
        # разваливался бы ровно в тот момент, когда по нему хотят вызвать меню).
        sel_rows = {i.row() for i in self.tbl_pkgs.selectionModel().selectedRows()}
        if index.row() not in sel_rows:
            self.tbl_pkgs.selectRow(index.row())
        rows = self._selected_pkg_rows()
        if len(rows) > 1:
            self._pkg_multi_menu(rows, pos)
            return
        r = self._selected_pkg_row()
        if r is None:
            return
        pid = int(r["id"])
        name = str(r["name"])
        authors = r["authors"] if isinstance(r.get("authors"), list) else []

        menu = QMenu(self)
        # Первые действия (открыть/вопросы/играть/сыграно/скачать/удалить) —
        # общие с контекстными меню списков справа (см. _add_pkg_context_actions).
        self._add_pkg_context_actions(menu, r)

        menu.addSeparator()
        act_pkg = menu.addAction(get_icon('fa5s.ban'), f"Добавить «{name}» в чёрный список")
        act_pkg.triggered.connect(lambda: self._blacklist_package(pid))

        if authors:
            menu.addSeparator()
            if len(authors) == 1:
                act_auth = menu.addAction(
                    get_icon('fa5s.user-slash'), f"Добавить автора «{authors[0]}» в чёрный список")
                # triggered шлёт checked (bool) первым позиционным аргументом — без
                # ловушки checked=False он бы попал в "a" вместо имени автора (баг:
                # пункт меню молча не работал).
                act_auth.triggered.connect(lambda checked=False, a=authors[0]: self._blacklist_author_by_name(a))
            else:
                for a in authors:
                    act_auth = menu.addAction(
                        get_icon('fa5s.user-slash'), f"Добавить автора «{a}» в чёрный список")
                    act_auth.triggered.connect(lambda checked=False, a=a: self._blacklist_author_by_name(a))

        menu.addSeparator()
        act_pkg_dir = menu.addAction(get_icon('fa5s.folder-open'), "Папка для скачиваемых .siq…")
        act_pkg_dir.triggered.connect(self._choose_packages_dir)
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

    def _pkg_multi_menu(self, rows, pos):
        """ПКМ, когда в таблице выделено НЕСКОЛЬКО паков (Ctrl/Shift+ЛКМ):
        действия применяются сразу ко всему выделению. Меню на один пак — в
        _on_pkg_context_menu/_add_pkg_context_actions."""
        import pandas as pd
        pids = [int(r["id"]) for r in rows]
        names = [str(r["name"]) for r in rows]
        menu = QMenu(self)
        act_copy = menu.addAction(get_icon('fa5s.copy'), f"Скопировать названия ({len(names)})")
        act_copy.triggered.connect(lambda checked=False, ns=names:
                                   QApplication.clipboard().setText("\n".join(ns)))

        dl_rows = [r for r in rows
                   if pd.notna(r.get("sibrowser_id")) and r.get("siq_downloaded") != 1]
        if dl_rows:
            menu.addSeparator()
            act_dl = menu.addAction(get_icon('fa5s.download'), f"Скачать .siq ({len(dl_rows)})")
            act_dl.triggered.connect(lambda checked=False, rs=dl_rows: self._download_for_rows(rs))

        menu.addSeparator()
        not_played = [p for p in pids if p not in self._played_ids]
        if not_played:
            act_played = menu.addAction(get_icon('fa5s.check-circle'),
                                        f"Добавить в сыграно ({len(not_played)})")
            act_played.triggered.connect(lambda checked=False, ps=not_played: self._mark_played_ids(ps))
        played = [p for p in pids if p in self._played_ids]
        if played:
            act_unplayed = menu.addAction(get_icon('fa5s.undo'),
                                          f"Убрать из сыгранных ({len(played)})")
            act_unplayed.triggered.connect(lambda checked=False, ps=played: self._unmark_played_ids(ps))
        not_bl = [p for p in pids if p not in self._pkg_blacklist]
        if not_bl:
            act_bl = menu.addAction(get_icon('fa5s.ban', color='#f38ba8'),
                                    f"Добавить в чёрный список ({len(not_bl)})")
            act_bl.triggered.connect(lambda checked=False, ps=not_bl: self._blacklist_packages(ps))
        menu.exec(self.tbl_pkgs.viewport().mapToGlobal(pos))

    def _selected_pkg_rows(self):
        """ВСЕ выделенные строки (Ctrl/Shift+ЛКМ) как список pandas Series — в
        порядке, в котором они идут в таблице. Массовые действия (скачать,
        «уже сыграно», чёрный список) работают именно по этому списку: раньше
        для этого была колонка галочек, теперь — обычное выделение."""
        sel = self.tbl_pkgs.selectionModel()
        if sel is None or self._pkg_view_df is None:
            return []
        out = []
        for idx in sorted(sel.selectedRows(), key=lambda i: i.row()):
            item = self.tbl_pkgs.item(idx.row(), 0)
            if item is None:
                continue
            match = self._pkg_view_df[self._pkg_view_df["id"] == item.data(Qt.ItemDataRole.UserRole)]
            if not match.empty:
                out.append(match.iloc[0])
        return out

    def _pkg_row_by_id(self, pid):
        """Строка пакета по id из ПОЛНОГО _pkgs_df (а не _pkg_view_df) — нужна
        для контекстных меню списков «Сыгранные»/«Чёрные списки», где пак может
        быть отфильтрован из видимой таблицы, но действия над ним всё равно
        должны работать."""
        if pid is None or self._pkgs_df is None or self._pkgs_df.empty:
            return None
        match = self._pkgs_df[self._pkgs_df["id"] == int(pid)]
        if match.empty:
            return None
        return match.iloc[0]

    def _add_pkg_context_actions(self, menu, r):
        """Добавляет в меню те же действия над паком, что и ПКМ на строке
        таблицы, КРОМЕ последних трёх (ЧС пака / ЧС авторов / выбор папки).
        Используется и самим ПКМ таблицы (_on_pkg_context_menu), и контекстными
        меню списков «Сыгранные»/«Чёрный список пакетов». `r` — строка пака
        (pandas Series)."""
        import pandas as pd
        is_steam = r.get("source") == "steam"
        act_open = menu.addAction(
            get_icon('fa5b.steam', color='#66c0f4') if is_steam else get_icon('fa5s.external-link-alt'),
            "Открыть в Steam Workshop" if is_steam else "Открыть на sibrowser.ru")
        act_open.triggered.connect(lambda checked=False, r=r: self._open_link_for_row(r))
        act_questions = menu.addAction(get_icon('fa5s.book-open'), "Показать вопросы и ответы")
        act_questions.triggered.connect(lambda checked=False, r=r: self._show_questions_for_row(r))
        if pd.notna(r.get("sibrowser_id")):
            act_play = menu.addAction(get_icon('fa5s.play-circle', color='#a6e3a1'), "Играть")
            act_play.triggered.connect(lambda checked=False, r=r: self._play_package_for_row(r))
        if int(r["id"]) in self._played_ids:
            act_played = menu.addAction(get_icon('fa5s.undo'), "Убрать из сыгранных")
            act_played.triggered.connect(lambda checked=False, r=r: self._unmark_played_for_row(r))
        else:
            act_played = menu.addAction(get_icon('fa5s.check-circle'), "Добавить в сыграно")
            act_played.triggered.connect(lambda checked=False, r=r: self._mark_played_for_row(r))
        if pd.notna(r.get("sibrowser_id")) and r.get("siq_downloaded") != 1:
            # Без sibrowser_id (например, Steam-пак) .siq скачать нечем — раньше
            # пункт всё равно показывался и молча ничего не делал по клику
            # (выглядело как «скачивание не работает»). Уже скачанные тоже не
            # показываем — для них ниже есть «Удалить пак».
            act_dl = menu.addAction(get_icon('fa5s.download'), "Скачать .siq")
            act_dl.triggered.connect(lambda checked=False, r=r: self._download_for_row(r))
        if r.get("siq_downloaded") == 1:
            act_folder = menu.addAction(get_icon('fa5s.folder-open', color='#f9e2af'), "Открыть в проводнике")
            act_folder.triggered.connect(lambda checked=False, r=r: self._open_folder_for_row(r))
            act_del = menu.addAction(get_icon('fa5s.trash', color='#f38ba8'), "Удалить пак")
            act_del.triggered.connect(lambda checked=False, r=r: self._delete_siq_for_row(r))

    def _pkg_list_context_menu(self, lst, pos):
        """Общее ПКМ-меню для списков «Сыгранные»/«Чёрный список пакетов» (в
        обоих id пака лежит в UserRole элемента): скопировать название + те же
        действия над паком, что и ПКМ на строке таблицы (кроме ЧС/папки)."""
        item = lst.itemAt(pos)
        if item is None:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        r = self._pkg_row_by_id(pid)
        if r is None:
            return
        name = str(r["name"])
        menu = QMenu(self)
        act_copy = menu.addAction(get_icon('fa5s.copy'), "Скопировать название")
        act_copy.triggered.connect(lambda checked=False, n=name: QApplication.clipboard().setText(n))
        menu.addSeparator()
        self._add_pkg_context_actions(menu, r)
        menu.exec(lst.viewport().mapToGlobal(pos))

    def _on_played_context_menu(self, pos):
        self._pkg_list_context_menu(self.lst_played, pos)

    def _on_pkg_blacklist_context_menu(self, pos):
        self._pkg_list_context_menu(self.lst_pkg_blacklist, pos)

    def _on_author_blacklist_context_menu(self, pos):
        """ПКМ в списке чёрного списка авторов: скопировать ник и открыть
        страницу автора на sibrowser.ru."""
        item = self.lst_blacklist.itemAt(pos)
        if item is None:
            return
        author = item.text()
        menu = QMenu(self)
        act_copy = menu.addAction(get_icon('fa5s.copy'), "Скопировать имя автора")
        act_copy.triggered.connect(lambda checked=False, a=author: QApplication.clipboard().setText(a))
        act_open = menu.addAction(get_icon('fa5s.external-link-alt'), "Открыть страницу автора на sibrowser.ru")
        act_open.triggered.connect(lambda checked=False, a=author: self._open_author_page(a))
        menu.exec(self.lst_blacklist.viewport().mapToGlobal(pos))

    def _open_author_page(self, author: str):
        import urllib.parse
        author = (author or "").strip()
        if not author:
            return
        url = f"{sg_config.SIBROWSER_BASE}/authors/{urllib.parse.quote(author, safe='')}"
        webbrowser.open(url)

    def eventFilter(self, obj, event):
        # Колесо мыши не должно менять значения спинбоксов/комбобоксов/
        # ползунков этой вкладки (см. установку фильтра в __init__). Просто
        # проглотить событие (return True) было ошибкой: эти виджеты лежат
        # внутри QScrollArea панели «Фильтры» — стоило курсору оказаться над
        # спинбоксом/комбобоксом, и скролл всей панели «залипал» намертво,
        # потому что событие не доходило до QScrollArea. Вместо проглатывания
        # пробрасываем колесо дальше — в ближайший QScrollArea-предок — и
        # только после этого блокируем эту же обработку у самого виджета.
        if event.type() == QEvent.Type.Wheel and isinstance(
                obj, (QSpinBox, QComboBox, QSlider)):
            parent = obj.parentWidget()
            while parent is not None and not isinstance(parent, QScrollArea):
                parent = parent.parentWidget()
            if parent is not None:
                QApplication.sendEvent(parent.viewport(), event)
            return True
        # Раздельные if (не один общий "obj is X and type == press" с elif) —
        # иначе НЕ-press событие (paint/resize/...) на первом viewport'е даёт
        # False у всего условия и проваливается в elif, где на раннем этапе
        # построения виджета (до создания pkg_detail) обращение к
        # self.pkg_detail упадёт AttributeError.
        if obj is self.tbl_pkgs.viewport():
            if (event.type() == QEvent.Type.MouseButtonPress
                    and not self.tbl_pkgs.indexAt(event.pos()).isValid()):
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
                     self.btn_mark_played, self.btn_add_pkg_blacklist,
                     self.btn_play, self.btn_delete_siq, self.btn_open_folder,
                     self.btn_bulk_dl, self.btn_pkgs_fullscreen)
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
        import pandas as pd
        self._pkg_selection_just_changed = True
        # Открытие карточки справа сужает таблицу (setSizes ниже) — Qt при этом
        # автоскроллит по горизонтали к текущей (последней кликнутой) ячейке,
        # из-за чего вся таблица иногда «прыгала» вправо, если кликнули по
        # правой колонке. Запоминаем позицию горизонтального скролла и
        # возвращаем её после того, как layout пересчитается.
        _hbar = self.tbl_pkgs.horizontalScrollBar()
        _prev_h = _hbar.value()
        r = self._selected_pkg_row()
        has = r is not None
        if has:
            is_steam = r.get("source") == "steam"
            self.btn_open_link.setToolTip(
                "Открыть в Steam Workshop" if is_steam else "Открыть на sibrowser.ru")
            self.btn_open_link.setIcon(
                get_icon('fa5b.steam', color='#66c0f4') if is_steam
                else get_icon('fa5s.external-link-alt'))
        self.btn_open_link.setEnabled(has)
        self.btn_show_questions.setEnabled(has)
        self.btn_mark_played.setEnabled(has)
        self.btn_add_pkg_blacklist.setEnabled(has)
        self.btn_play.setEnabled(bool(has and pd.notna(r.get("sibrowser_id"))))
        # «Удалить пак»/«Открыть в проводнике» — только когда выбран реально
        # скачанный .siq.
        self.btn_delete_siq.setEnabled(bool(has and r.get("siq_downloaded") == 1))
        self.btn_open_folder.setEnabled(bool(has and r.get("siq_downloaded") == 1))
        if not has:
            self._current_detail_pid = None
            self.pkg_detail.setHtml("")
            self._pkg_det_wrap.setVisible(False)  # таблица занимает всю ширину
            self._set_app_click_filter(False)
            return
        self._current_detail_pid = int(r["id"])
        self._pkg_det_wrap.setVisible(True)
        if self._pkg_split.sizes()[1] == 0:
            self._pkg_split.setSizes([700, 400])
        self.pkg_detail.setHtml(self._render_package_detail_html(r))
        self._set_app_click_filter(True)
        self._maybe_fetch_full_description(r)
        QTimer.singleShot(0, lambda h=_prev_h: _hbar.setValue(h))

    def _maybe_fetch_full_description(self, r):
        """Полное описание пака урезано на карточке списка (см. sibrowser.
        fetch_full_description) — подтягиваем его отдельным фоновым запросом
        только при открытии карточки, не во время массового сбора."""
        import pandas as pd
        if r.get("source") == "steam":
            return  # у Steam описание и так полное (приходит из API)
        pid = int(r["id"])
        if pid in self._desc_full_pending or pid in self._desc_full_done:
            return
        existing = r.get("description_full")
        if isinstance(existing, str) and existing.strip():
            self._desc_full_done.add(pid)
            return
        sib_id = r.get("sibrowser_id")
        if not pd.notna(sib_id):
            return
        self._desc_full_pending.add(pid)
        task = _DescFetchTask(pid, str(sib_id))
        task.signals.finished.connect(self._on_full_description_fetched)
        task.signals.failed.connect(self._on_full_description_failed)
        self._pool.start(task)

    def _on_full_description_failed(self, package_id: int):
        self._desc_full_pending.discard(package_id)
        self._desc_full_done.add(package_id)  # не повторяем неудачный запрос

    def _on_full_description_fetched(self, package_id: int, text: str):
        self._desc_full_pending.discard(package_id)
        self._desc_full_done.add(package_id)
        try:
            with sg_db.connect() as conn:
                sg_db.set_description_full(conn, package_id, text)
        except Exception:
            pass
        for df in (self._pkgs_df, self._pkg_view_df):
            if df is not None and not df.empty and "id" in df.columns:
                df.loc[df["id"] == package_id, "description_full"] = text
        # Карточка могла быть закрыта/переключена, пока шёл запрос — обновляем
        # только если пользователь всё ещё смотрит именно этот пак.
        if self._current_detail_pid == package_id:
            r = self._selected_pkg_row()
            if r is not None:
                self.pkg_detail.setHtml(self._render_package_detail_html(r))

    def _on_pkg_clicked(self, index):
        """Повторный ЛКМ по строке, чья карточка уже открыта справа — закрывает
        карточку. QAbstractItemView не меняет выделение при клике по уже
        выбранной строке, поэтому itemSelectionChanged тут не переиспускается —
        обрабатываем именно `clicked`, который стреляет при любом клике."""
        if not index.isValid():
            return
        chk = self.tbl_pkgs.item(index.row(), 0)
        if chk is None:
            return
        pid = chk.data(Qt.ItemDataRole.UserRole)
        just_changed = self._pkg_selection_just_changed
        self._pkg_selection_just_changed = False
        if pid is not None and pid == self._current_detail_pid and not just_changed:
            self.tbl_pkgs.clearSelection()

    @staticmethod
    def _copy_link_html(field: str, what: str, copied: bool) -> str:
        """Маленький значок «копировать» прямо в строке текста (не отдельной
        кнопкой на всю ширину панели, см. _on_pkg_detail_anchor_clicked).
        Текст ссылки внутри <a> — не реальный URL, а внутренний маркер, который
        отлавливает anchorClicked. После клика значок на 1.5 с превращается в
        зелёную галочку (copied=True) — визуальное подтверждение копирования
        (см. _show_copy_feedback)."""
        if copied:
            return (f'<a href="sigstats-copy-{field}" style="text-decoration:none;" '
                    'title="Скопировано">'
                    f'{icon_html("fa5s.check", size=13, color="#a6e3a1")}</a>')
        return (f'<a href="sigstats-copy-{field}" style="text-decoration:none;" '
                f'title="Копировать {what}">'
                f'{icon_html("fa5s.copy", size=13, color="#a6adc8")}</a>')

    def _render_package_detail_html(self, r, copied: str | None = None) -> str:
        """`copied` — какая именно строка только что скопирована ("name" или
        "authors"): у неё вместо значка копирования на 1.5 с показывается
        зелёная галочка."""
        import pandas as pd
        is_steam = r.get("source") == "steam"
        parts = [f"<h3>{_esc(r['name'])} "
                 f"{self._copy_link_html('name', 'название', copied == 'name')}</h3>"]
        # Авторы — сразу под названием (по просьбе), а не в середине карточки
        # среди статистики: это второе, что о паке хотят знать, и такая же
        # кнопка копирования, как у названия.
        authors = r["authors"] if isinstance(r.get("authors"), list) else []
        if authors:
            parts.append(
                f"<p><b>Авторы:</b> {_esc(', '.join(authors))} "
                f"{self._copy_link_html('authors', 'авторов', copied == 'authors')}</p>")
        if is_steam and pd.notna(r.get("steam_id")):
            parts.append(f"<p><b>Steam Workshop id:</b> {_esc(str(r['steam_id']))}</p>")
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
        # Состав контента (% текста/фото/звука/видео) — как в таблице
        # распределения на sibrowser.ru, см. sigstats/sibrowser.py::_CONTENT_LABELS.
        pct_fields = (("Текст", r.get("pct_text")), ("Фото", r.get("pct_photo")),
                      ("Звук", r.get("pct_audio")), ("Видео", r.get("pct_video")))
        if any(pd.notna(v) for _, v in pct_fields):
            parts.append("<p>" + " &nbsp; ".join(
                f"<b>{lbl}:</b> {int(v)}%" for lbl, v in pct_fields if pd.notna(v)) + "</p>")
        comp = _fmt_pct(r.get("completion_pct"), 1)
        dlc = r.get("download_count")
        parts.append(
            f"<p><b>% завершения:</b> {comp} &nbsp; "
            f"<b>Скачиваний:</b> {int(dlc) if pd.notna(dlc) else '—'}</p>")
        if pd.notna(r.get("started_games")):
            parts.append(
                f"<p>Игр начато: {int(r['started_games'])} · завершено: "
                f"{int(r['completed_games'])}</p>")
            ap, cp = r.get("answer_pct"), r.get("correct_pct")
            # Каждый показатель — отдельной строкой (по просьбе).
            parts.append(f"<p>Средний % попыток: {_fmt_pct(ap, 0)}</p>")
            parts.append(f"<p>Средний % правильных: {_fmt_pct(cp, 0)}</p>")
        cats = r.get("categories") if isinstance(r.get("categories"), list) else []
        if cats:
            parts.append("<p><b>Категории:</b> " +
                         ", ".join(f"{_esc(c['name'])} {c.get('pct', 0)}%" for c in cats) + "</p>")
        tags = r["tags"] if isinstance(r.get("tags"), list) else []
        if tags:
            parts.append("<p>" + " ".join(
                f"<span style='background:#222838;border:1px solid #313a52;border-radius:8px;"
                f"padding:2px 9px;margin:2px;'>{_esc(t)}</span>" for t in tags) + "</p>")
        # Полное описание (description_full) подтягивается лениво отдельным
        # запросом при открытии карточки (см. _maybe_fetch_full_description) —
        # description из карточки списка урезан автором сайта многоточием.
        desc = r.get("description_full")
        if not (isinstance(desc, str) and desc.strip()):
            desc = r.get("description")
        if isinstance(desc, str) and desc.strip():
            parts.append(
                f"<h4>Описание</h4><p style='color:#bac2de;'>{_esc(desc.strip())}</p>")

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

    def _update_pkg_dir_tooltip(self):
        self.btn_pkg_dir.setToolTip(
            "Папка для скачиваемых .siq\n\n"
            f"Сейчас: {sg_config.PACKAGES_DIR}\n"
            "Нажмите, чтобы выбрать другую.")

    def _choose_packages_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Папка для скачиваемых .siq", str(sg_config.PACKAGES_DIR))
        if d:
            sg_config.set_packages_dir(d)
            self._update_pkg_dir_tooltip()

    def _on_pkg_detail_anchor_clicked(self, url: QUrl):
        """Псевдо-ссылки в карточке пака — значки «копировать» у названия и у
        строки авторов (см. _render_package_detail_html)."""
        field = {"sigstats-copy-name": "name",
                 "sigstats-copy-authors": "authors"}.get(url.toString())
        if field is None:
            return
        r = self._selected_pkg_row()
        if r is None:
            return
        if field == "name":
            text = str(r["name"])
        else:
            authors = r["authors"] if isinstance(r.get("authors"), list) else []
            text = ", ".join(authors)
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._show_copy_feedback(int(r["id"]), field)

    def _show_copy_feedback(self, pid: int, field: str):
        """Значок «копировать» у нужной строки → зелёная галочка на 1.5 с, затем
        обратно. Перерисовываем карточку с сохранением позиции скролла (setHtml
        иначе сбросил бы её в начало)."""
        def _render(copied):
            if self._current_detail_pid != pid:
                return
            r = self._selected_pkg_row()
            if r is None or int(r["id"]) != pid:
                return
            sb = self.pkg_detail.verticalScrollBar()
            pos = sb.value()
            self.pkg_detail.setHtml(self._render_package_detail_html(r, copied=copied))
            sb.setValue(pos)
        _render(field)
        QTimer.singleShot(1500, lambda: _render(None))

    def _open_selected_link(self):
        self._open_link_for_row(self._selected_pkg_row())

    def _open_link_for_row(self, r):
        if r is None:
            return
        import pandas as pd
        if r.get("source") == "steam" and pd.notna(r.get("steam_id")):
            webbrowser.open(sg_steam_workshop.workshop_url(str(r["steam_id"])))
        elif pd.notna(r.get("sibrowser_id")):
            url = f"{sg_config.SIBROWSER_BASE}/packages/{int(r['sibrowser_id'])}"
            webbrowser.open(url)

    def _play_selected_package(self):
        self._play_package_for_row(self._selected_pkg_row())

    def _play_package_for_row(self, r):
        """Открывает пак сразу в SIGame, без скачивания .siq — как кнопка
        «Играть» на sibrowser.ru. Штатный способ передать пак в SIGame — это
        параметр packageUri в URL самого sigame.vladimirkhil.com (см.
        sg_sibrowser.play_url); открываем его через системный браузер
        (webbrowser.open), т.к. это единственный поддерживаемый способ передать
        URL внешнему браузеру — надёжно «подставить» пак в уже открытую вкладку
        SIGame конкретного пользовательского браузера отсюда нельзя (нет
        стандартного API для адресации конкретной вкладки чужого браузера без
        remote-debugging протокола), новая вкладка/переиспользование окна
        браузера — уже поведение самой ОС/браузера по умолчанию."""
        if r is None:
            return
        import pandas as pd
        if not pd.notna(r.get("sibrowser_id")):
            return
        url = sg_sibrowser.play_url(str(int(r["sibrowser_id"])), str(r["name"]))
        webbrowser.open(url)

    def _open_selected_folder(self):
        self._open_folder_for_row(self._selected_pkg_row())

    def _open_folder_for_row(self, r):
        """Открывает Проводник на скачанном .siq пака (файл выделяется); если
        .siq нет на диске, но есть распакованная папка медиа — открывает её."""
        if r is None:
            return
        from pathlib import Path
        import subprocess
        siq_path = r.get("siq_path")
        if isinstance(siq_path, str) and siq_path and Path(siq_path).exists():
            subprocess.Popen(["explorer", "/select," + str(Path(siq_path))])
            return
        media_dir = sg_config.MEDIA_DIR / str(int(r["id"]))
        if media_dir.exists():
            os.startfile(str(media_dir))
            return
        msgbox_information(self, "Открыть в проводнике",
                           "Пак ещё не скачан локально — открывать нечего.")

    def _show_selected_questions(self):
        self._show_questions_for_row(self._selected_pkg_row())

    def _show_questions_for_row(self, r):
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
            if r.get("source") == "steam":
                msgbox_information(
                    self, "Нет вопросов",
                    "Пак импортирован из Steam Workshop — доступны только "
                    "метаданные, .siq не скачивался (см. «Открыть в Steam Workshop»).")
                return
            if msgbox_question(
                    self, "Скачать .siq",
                    "Вопросы ещё не скачаны. Скачать и разобрать .siq сейчас?"
            ) == QMessageBox.StandardButton.Yes:
                pid = int(r["id"])
                ok = sg_collector.download_one(pid, str(r["sibrowser_id"]), r["name"])
                if ok:
                    self._reload_data()
                    self._show_questions_for_row(self._pkg_row_by_id(pid))
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
        """Скачать .siq всех ВЫДЕЛЕННЫХ паков (Ctrl/Shift+ЛКМ в таблице).
        Раньше набор задавался галочками в первой колонке — их заменил номер
        места, а массовый выбор делается обычным выделением строк."""
        import pandas as pd
        items = []
        for r in self._selected_pkg_rows():
            if r.get("siq_downloaded") == 1 or pd.isna(r.get("sibrowser_id")):
                continue
            items.append((int(r["id"]), str(r["sibrowser_id"]), r["name"]))
        if not items:
            msgbox_information(self, "Нечего скачивать",
                                    "Выделите паки в таблице (Ctrl+ЛКМ — по одному, "
                                    "Shift+ЛКМ — диапазоном) — уже скачанные паки и "
                                    "паки без ссылки на .siq пропускаются автоматически.")
            return
        self._enqueue_downloads(items)

    def _download_for_row(self, r):
        """Скачать .siq одного конкретного пака (из контекстного меню списков
        «Сыгранные»/«Чёрный список пакетов», где пак не обязательно есть в
        видимой таблице). Уже скачанные / без sibrowser_id молча пропускаются."""
        import pandas as pd
        if r is None or r.get("siq_downloaded") == 1 or not pd.notna(r.get("sibrowser_id")):
            return
        self._enqueue_downloads([(int(r["id"]), str(r["sibrowser_id"]), r["name"])])

    def _download_for_rows(self, rows):
        """Пакетная версия _download_for_row — для мультивыбора карточек в
        тир-листе (см. _TierListDialog._card_multi_menu). Качаются параллельно
        (см. _MAX_PARALLEL_DOWNLOADS), не по одному."""
        import pandas as pd
        items = []
        for r in rows:
            if r is None or r.get("siq_downloaded") == 1 or not pd.notna(r.get("sibrowser_id")):
                continue
            items.append((int(r["id"]), str(r["sibrowser_id"]), r["name"]))
        if not items:
            return
        self._enqueue_downloads(items)

    def _enqueue_downloads(self, items):
        if not items:
            return
        if isinstance(self._active_job, _BulkDownloadTask):
            # Скачивание уже идёт — дозаписываем в его очередь вместо того чтобы
            # блокировать выбор нового пака (кнопка временно в режиме «Отмена» —
            # раньше клик по ней при выборе другого пака только отменял уже
            # идущее скачивание, будто «предлагая отменить» вместо начать новое).
            self._active_job.add_items(items)
            self.lbl_status.setText(f"Добавлено в очередь скачивания: {len(items)}.")
            return
        if self._job_running():
            return

        task = _BulkDownloadTask(items)
        task.signals.progress.connect(
            lambda i, total, name: (self.progress.setValue(int(i / total * 100)),
                                    self.lbl_status.setText(f"[{i}/{total}] {name}")))
        task.signals.item_progress.connect(self._on_item_download_progress)

        def _done(ok):
            self._end_job()
            self._set_bulk_dl_btn_cancel(False)
            self.lbl_status.setText(f"Скачано и разобрано: {ok} из {task._total}.")
            self._reload_data()
        task.signals.finished.connect(_done)
        self._set_bulk_dl_btn_cancel(True)
        self._begin_job(task)

    def _set_bulk_dl_btn_cancel(self, cancel_mode: bool):
        """Переключает btn_bulk_dl («Скачать .siq») между обычным видом и
        «Отмена» на время скачивания — тот же приём, что _set_cut_btn_cancel
        в edit_tab.py для кнопки «Обрезать»."""
        b = self.btn_bulk_dl
        try:
            b.clicked.disconnect()
        except Exception:
            pass
        if cancel_mode:
            self._bulk_dl_btn_saved = (b.text(), b.icon(), b.toolTip())
            b.setText("Отмена")
            b.setIcon(get_icon('fa5s.times', color='#f38ba8'))
            b.setToolTip("Остановить скачивание отмеченных паков.")
            b.clicked.connect(self._cancel_bulk_download)
        else:
            saved = getattr(self, "_bulk_dl_btn_saved", None)
            if saved:
                b.setText(saved[0])
                b.setIcon(saved[1])
                b.setToolTip(saved[2])
            b.clicked.connect(self._bulk_download)

    def _cancel_bulk_download(self):
        if self._active_job is not None:
            self._active_job.stop()
            self.lbl_status.setText("Останавливаю скачивание…")

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
        по достижении 100% ставим галочку (её отрисует _PkgNameDelegate).
        Пак может не быть в видимой таблице (отфильтрован, либо скачивание
        запущено из тир-листа) — в этом случае просто отдаём сигнал дальше,
        его подхватит открытое окно тир-листа (см. download_progress)."""
        row = self._row_for_pid(pid)
        if row is not None:
            name_item = self.tbl_pkgs.item(row, self._COL_NAME)
            if name_item is not None:
                if pct >= 100:
                    name_item.setData(_PkgNameDelegate.ProgressRole, None)
                    name_item.setData(_PkgNameDelegate.DownloadedRole, True)
                else:
                    name_item.setData(_PkgNameDelegate.ProgressRole, int(pct))
                self.tbl_pkgs.viewport().update()
        self.download_progress.emit(pid, pct)

    def _delete_selected_siq(self):
        self._delete_siq_for_row(self._selected_pkg_row())

    def _delete_siq_for_row(self, r):
        if r is None or r.get("siq_downloaded") != 1:
            return
        if msgbox_question(
                self, "Удалить пак",
                f"Удалить скачанный .siq пакета «{r['name']}» и его медиа с диска?\n"
                "Статистика в базе останется — пак не пропадёт из списка."
        ) != QMessageBox.StandardButton.Yes:
            return
        name = r["name"]
        pid = int(r["id"])
        # В фоне — shutil.rmtree медиапапки может занять заметное время и
        # раньше вызывалось прямо в UI-потоке, подвешивая интерфейс (см.
        # _DeleteSiqTask).
        self.btn_delete_siq.setEnabled(False)
        self.lbl_status.setText(f"Удаляю пак «{name}»…")
        task = _DeleteSiqTask(pid)

        def _done(_pid, ok, err):
            if not ok:
                msgbox_warning(self, "Ошибка", f"Не удалось удалить пак: {err}")
            else:
                self.lbl_status.setText(f"Пак «{name}» удалён с диска (статистика сохранена).")
            self._reload_data()
        task.signals.finished.connect(_done)
        self._pool.start(task)

    # ══════════════════════════════════════════════════════════════════════
    # Вкладка «Темы»
    # ══════════════════════════════════════════════════════════════════════
    def _build_themes_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Темы сгруппированы без учёта эмодзи."))

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
        root = QVBoxLayout(page)

        # Как в «Пакеты»: слева — таблица на всю высоту, справа — узкая
        # прокручиваемая колонка с фильтрами/поиском фиксированной ширины
        # (см. _build_packages_page/_build_packages_settings_panel).
        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        left = QVBoxLayout()

        # «№» — место в рейтинге (по умолчанию сортированном по ср. %
        # завершения — см. _refresh_authors_table); сама таблица остаётся
        # сортируемой кликом по любому заголовку, номер места при этом не
        # пересчитывается.
        self.tbl_authors = QTableWidget(0, 6)
        self.tbl_authors.setHorizontalHeaderLabels(
            ["№", "Автор", "Паков", "Со стат.", "Ср. % завершения", "Всего игр начато"])
        self.tbl_authors.setSortingEnabled(True)
        self.tbl_authors.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_authors.setAlternatingRowColors(True)
        self.tbl_authors.verticalHeader().setVisible(False)
        # Колонки шириной под фактическое содержимое (без растяжения «Автора»
        # на весь остаток — по просьбе).
        self.tbl_authors.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_authors.horizontalHeader().setStretchLastSection(False)
        # Qt по умолчанию показывает столбец 0 отсортированным по убыванию, даже
        # без явного клика пользователя — без этой строки места оказывались
        # перевёрнуты (23, 22, 21, … вместо 1, 2, 3, …) при самом первом показе.
        self.tbl_authors.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        # «№» — динамическое место в ТЕКУЩЕМ визуальном порядке (по просьбе):
        # клик по любому другому заголовку меняет порядок строк, и «№»
        # пересчитывается под него (1 — верхняя строка сейчас, а не место в
        # каком-то одном фиксированном рейтинге). sortIndicatorChanged стреляет
        # ДО того, как Qt физически переставит строки, поэтому пересчёт — через
        # QTimer.singleShot(0, …), на следующей итерации цикла событий.
        self.tbl_authors.horizontalHeader().sortIndicatorChanged.connect(
            lambda *_a: QTimer.singleShot(0, self._renumber_authors_rank))
        left.addWidget(self.tbl_authors, 1)
        body.addLayout(left, 1)

        self._build_authors_settings_panel(body)

        self.subtabs.addTab(page, "Авторы")

    def _build_authors_settings_panel(self, body):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(2, 2, 8, 2)
        pv.setSpacing(12)

        filt_box = QGroupBox("Фильтры")
        fl = QVBoxLayout(filt_box)

        fl.addWidget(QLabel("Мин. паков у автора (со статистикой):"))
        self.sp_min_pk = QSpinBox(); self.sp_min_pk.setRange(1, 100); self.sp_min_pk.setValue(1)
        self.sp_min_pk.valueChanged.connect(self._refresh_authors_table)
        fl.addWidget(self.sp_min_pk)

        fl.addWidget(QLabel("Мин. игр начато (сумма):"))
        self.sp_min_started_a = QSpinBox(); self.sp_min_started_a.setRange(0, 1_000_000)
        self.sp_min_started_a.setValue(200); self.sp_min_started_a.setSingleStep(50)
        self.sp_min_started_a.valueChanged.connect(self._refresh_authors_table)
        fl.addWidget(self.sp_min_started_a)

        self.chk_auth_stats = QCheckBox("Только авторы со статистикой")
        self.chk_auth_stats.setChecked(True)
        self.chk_auth_stats.toggled.connect(self._refresh_authors_table)
        fl.addWidget(self.chk_auth_stats)

        fl.addWidget(QLabel("Поиск (никнейм автора / название пака):"))
        self.ed_author_search = QLineEdit()
        self.ed_author_search.setClearButtonEnabled(True)
        self.ed_author_search.setToolTip(
            "Ищет и по нику автора, и по названию его пака — вне зависимости "
            "от того, в чёрном списке пак/автор или нет.")
        self.ed_author_search.textChanged.connect(self._refresh_authors_table)
        fl.addWidget(self.ed_author_search)

        # Собрать НОВУЮ статистику по автору прямо отсюда — не переключаясь на
        # «Пакеты» (тот же сбор, что там кнопкой «Собрать паки автора», просто
        # ник берётся из поля поиска выше).
        self.btn_collect_author_here = QPushButton("Собрать статистику")
        self.btn_collect_author_here.setIcon(get_icon('fa5s.sync'))
        self.btn_collect_author_here.setToolTip(
            "Запускает сбор всех паков автора из поля поиска выше (тот же сбор, "
            "что «Собрать паки автора» на вкладке «Пакеты») — рейтинг обновится "
            "здесь же по окончании.")
        self.btn_collect_author_here.clicked.connect(self._start_collect_author_from_authors_tab)
        fl.addWidget(self.btn_collect_author_here)

        self.lbl_authors_collect_status = QLabel("")
        self.lbl_authors_collect_status.setWordWrap(True)
        self.lbl_authors_collect_status.setStyleSheet("color:#a6adc8;")
        fl.addWidget(self.lbl_authors_collect_status)

        pv.addWidget(filt_box)
        pv.addStretch(1)

        scroll.setWidget(panel)
        _need = max(panel.minimumSizeHint().width(), 220)
        _sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
        scroll.setFixedWidth(_need + _sb + 12)
        body.addWidget(scroll)

    def _renumber_authors_rank(self):
        """Перезаписывает колонку «№» номерами 1..N по текущему визуальному
        порядку строк — вызывается и после клика по заголовку (см. connect в
        _build_authors_page), и сразу после перестройки таблицы в
        _refresh_authors_table."""
        t = self.tbl_authors
        t.setSortingEnabled(False)
        for row in range(t.rowCount()):
            item = t.item(row, 0)
            if item is None:
                continue
            place = row + 1
            item.setText(str(place))
            item.setData(Qt.ItemDataRole.UserRole, place)
        t.setSortingEnabled(True)

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
        needle = self.ed_author_search.text().strip().lower()
        if needle:
            matched = set(av[av["author"].str.lower().str.contains(needle, na=False)]["author"])
            # Кроме ника автора — ищем и по НАЗВАНИЮ ПАКА: находим его авторов и
            # добавляем их в рейтинг. Берём _pkgs_df (полный, ДО фильтрации в
            # _filtered_packages_df), а не _pkg_view_df — поэтому находится и
            # пак, у которого сам пак/автор сейчас в чёрном списке (по просьбе,
            # это отдельный список от «Пакеты» — см. коммент в analysis.author_table).
            if self._pkgs_df is not None and not self._pkgs_df.empty:
                pkg_hits = self._pkgs_df[self._pkgs_df["name"].str.lower().str.contains(needle, na=False)]
                for authors in pkg_hits["authors"]:
                    if isinstance(authors, list):
                        matched.update(authors)
            av = av[av["author"].isin(matched)]
        av = av.sort_values("avg_completion_pct", ascending=False, na_position="last").reset_index(drop=True)

        t = self.tbl_authors
        # Таблица перестраивается целиком ниже — запоминаем текущую сортировку
        # (могла быть выставлена кликом по любому заголовку), чтобы вернуть её
        # после перестройки, а не откатывать на дефолтную.
        hdr = t.horizontalHeader()
        sort_col, sort_order = hdr.sortIndicatorSection(), hdr.sortIndicatorOrder()
        t.setSortingEnabled(False)
        t.setRowCount(0)
        for i, r in av.iterrows():
            row = t.rowCount()
            t.insertRow(row)
            place = i + 1
            t.setItem(row, 0, _NumItem(str(place), place))
            t.setItem(row, 1, QTableWidgetItem(str(r["author"])))
            t.setItem(row, 2, _NumItem(str(int(r["packages"])), int(r["packages"])))
            t.setItem(row, 3, _NumItem(str(int(r["with_stats"])), int(r["with_stats"])))
            comp = r.get("avg_completion_pct")
            t.setItem(row, 4, _NumItem(_fmt_pct(comp, 0), comp if comp == comp else -1))
            started = r.get("total_started")
            t.setItem(row, 5, _NumItem(str(int(started)) if started == started else "0", _num_or_zero(started)))
        t.setSortingEnabled(True)
        t.sortByColumn(sort_col if sort_col >= 0 else 0, sort_order)
        # sortByColumn выше синхронный — переставленные строки уже на месте,
        # поэтому пересчитать «№» можно сразу (без singleShot, в отличие от
        # клика по заголовку — см. connect в _build_authors_page).
        self._renumber_authors_rank()

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
        if self._pkg_fullscreen_host is not None:
            self._exit_pkgs_fullscreen()
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


# ══════════════════════════════════════════════════════════════════════════════
# Тир-лист сыгранных паков (окно из группы «Сыгранные пакеты»)
# ══════════════════════════════════════════════════════════════════════════════
# Цвет названия уровня (S/A/B/C/D и любых пользовательских) — по позиции, с
# зацикливанием (catppuccin, как остальная вкладка). Это только цвет ТЕКСТА
# заголовка, никакой цветной вертикальной полосы у строки нет (по просьбе).
_TIER_COLORS = ["#f38ba8", "#fab387", "#f9e2af", "#a6e3a1", "#89b4fa", "#cba6f7", "#94e2d5"]

# Полярность тега (хороший/нейтральный/плохой) задаётся вручную пользователем
# (ПКМ на чипе тега) и хранится per-tag в tier_list.json → tag_kinds. Новый тег
# по умолчанию «хороший». См. _TierListDialog._tag_kind / ._set_tag_kind.
_TAG_GOOD = "#a6e3a1"
_TAG_BAD = "#f38ba8"
_TAG_NEUTRAL = "#ffffff"
_TAG_KIND_COLORS = {"good": _TAG_GOOD, "neutral": _TAG_NEUTRAL, "bad": _TAG_BAD}
# Порядок для сортировки редактора тегов: хорошие сверху, плохие снизу (по просьбе).
_TAG_KIND_ORDER = {"good": 0, "neutral": 1, "bad": 2}

# Карточка пака = видимый блок с рамкой и полным названием (по просьбе — не
# обрезанное имя, а «блок названия»). Общий стиль для всех списков тир-листа.
_CARD_QSS = """
QListWidget { background: transparent; border: 1px solid #313244; border-radius: 6px; }
QListWidget::item {
    border: 1px solid #45475a;
    border-radius: 6px;
    background: #313244;
    color: #cdd6f4;
    padding: 6px 10px;
    margin: 3px;
}
QListWidget::item:selected {
    border: 1px solid #89b4fa;
    background: #45475a;
    color: #ffffff;
}
"""


class _TagChip(QLabel):
    """Чип тега: кликабельный «бейджик» с переносом текста по словам (в отличие
    от QPushButton, который не переносит и вылезал бы за окно). Клик переключает
    (toggled), ПКМ отдаётся наружу через customContextMenuRequested. Цвет — по
    полярности тега (good/bad); заливка — если тег присвоен текущему паку."""
    toggled = pyqtSignal(bool)

    def __init__(self, text: str, color: str, checked: bool, parent=None):
        super().__init__(parent)
        self._color = color
        self._checked = checked
        self._text = text
        self.setWordWrap(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._apply()

    def set_color(self, color: str):
        self._color = color
        self._apply()

    def set_checked(self, checked: bool):
        self._checked = checked
        self._apply()

    def _apply(self):
        self.setText(("✓ " if self._checked else "") + self._text)
        if self._checked:
            self.setStyleSheet(
                f"QLabel{{background:{self._color};color:#11111b;"
                f"border:1px solid {self._color};border-radius:11px;"
                f"padding:4px 12px;font-weight:bold;}}")
        else:
            self.setStyleSheet(
                f"QLabel{{background:transparent;color:{self._color};"
                f"border:1px solid {self._color};border-radius:11px;"
                f"padding:4px 12px;}}")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self._apply()
            self.toggled.emit(self._checked)
        super().mousePressEvent(e)


class _FlowLayout(QLayout):
    """Раскладка чипов тегов слева направо с переносом на новую строку, когда
    не хватает ширины (как обычный текст) — вместо одного тега на всю ширину
    в ряд (по просьбе: теги должны умещаться по горизонтали, а не съедать
    вертикаль по одному в ряд). Чип не может быть шире доступной ширины —
    длинный текст переносится внутри чипа (никакого горизонтального скролла)."""

    def __init__(self, parent=None, margin=0, h_spacing=6, v_spacing=6):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    def _do_layout(self, rect, test_only):
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        avail = max(1, effective.width())
        x, y = effective.x(), effective.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            w = min(hint.width(), avail)   # чип не шире области → без гор. скролла
            wid = item.widget()
            if wid is not None and wid.hasHeightForWidth():
                h = wid.heightForWidth(w)   # длинный текст переносится → выше
            else:
                h = hint.height()
            next_x = x + w + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + w + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(x, y, w, h))
            x = next_x
            line_height = max(line_height, h)
        return y + line_height - rect.y() + bottom


class _TierPublishEmitter(QObject):
    """Мостик из фонового потока публикации тир-листа обратно в GUI-поток
    (как error_report._Emitter). done(ok, url_или_ошибка)."""
    done = pyqtSignal(bool, str)


def _post_tier(url: str, payload: dict, token: str, emitter: "_TierPublishEmitter"):
    """Шлёт модель тир-листа POST-ом на worker (см. tier_worker.js) в фоновом
    потоке. При успехе возвращает постоянную ссылку на страницу, иначе — текст
    ошибки. Запускается только из _TierListDialog._publish_online."""
    import json
    import urllib.request
    import urllib.error
    ok, result = False, ""
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "X-Edit-Token": token,
                     "User-Agent": f"SI-HYX/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = resp.read().decode("utf-8", "replace")
            ok = 200 <= getattr(resp, "status", 200) < 300
            if ok:
                try:
                    result = json.loads(body).get("url", "")
                except Exception:
                    result = ""
    except urllib.error.HTTPError as e:
        result = f"HTTP {e.code}"
    except Exception as e:
        result = str(e)
    emitter.done.emit(ok, result)


class _TierCardList(QListWidget):
    """Список карточек-паков с drag&drop между уровнями и «пулом». Карточки
    переносятся на следующую строку, когда кончается ширина (setWrapping), а не
    уходят бесконечно вправо. Перетаскивание между разными QListWidget работает
    «из коробки» через стандартный mime-формат Qt (роли элемента, в т.ч. id пака
    в UserRole, переносятся). Эмитит `dropped` после перемещения.

    auto_height=True (полосы уровней): виджет сам подгоняет высоту под
    содержимое (сколько получилось перенесённых строк) — без внутреннего
    скролла. auto_height=False (пул «Не распределено»): фиксированной высоты со
    своим вертикальным скроллом. Эмитит `emptyClicked` при клике мимо карточек,
    чтобы диалог мог снять «текущий» пак (свою переменную, не только Qt-выделение)."""
    dropped = pyqtSignal()
    emptyClicked = pyqtSignal()

    def __init__(self, auto_height: bool, parent=None):
        super().__init__(parent)
        self._auto_height = auto_height
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setSpacing(3)
        self.setUniformItemSizes(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        # ExtendedSelection — можно выделить сразу несколько карточек (Ctrl/Shift,
        # как в проводнике) и применить действие сразу ко всем (см. _on_card_menu/
        # _card_multi_menu), а заодно перетащить всю группу между уровнями разом.
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(_CARD_QSS)
        self._empty_h = 46
        if auto_height:
            # Полосы уровней: карточки текут слева направо с переносом строк.
            self.setFlow(QListWidget.Flow.LeftToRight)
            self.setWrapping(True)
            self.setWordWrap(False)
            self.setTextElideMode(Qt.TextElideMode.ElideNone)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.setFixedHeight(self._empty_h)
        else:
            # Пул «Не распределено» — узкий, поэтому карточки идут вертикально
            # (одна под другой) на всю ширину, а длинные названия ПЕРЕНОСЯТСЯ
            # по словам (без горизонтального скролла, текст виден целиком).
            self.setFlow(QListWidget.Flow.TopToBottom)
            self.setWrapping(False)
            self.setWordWrap(True)
            self.setTextElideMode(Qt.TextElideMode.ElideNone)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setMinimumHeight(120)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if self.itemAt(e.pos()) is None:
            self.emptyClicked.emit()

    def startDrag(self, supportedActions):
        # Держа Alt (иногда и Ctrl) во время перетаскивания, Qt/Windows может
        # предложить CopyAction вместо MoveAction — карточка пака при этом
        # дублировалась (оставалась в источнике И появлялась в цели). Разрешаем
        # ТОЛЬКО перемещение, вне зависимости от того, какой модификатор зажат.
        super().startDrag(Qt.DropAction.MoveAction)
        # super().startDrag() блокируется на время всего D&D (внутренний
        # nested event loop QDrag.exec) и возвращается ТОЛЬКО ПОСЛЕ того, как
        # исходный список уже лишился перетащенной карточки (Qt удаляет её из
        # источника сама, если результат — MoveAction). А вот dropEvent() ЦЕЛИ
        # срабатывает РАНЬШЕ этого — ещё ВНУТРИ nested loop, когда карточка уже
        # добавлена в цель, но ещё не убрана из источника. Раньше сохранение
        # состояния (_on_drop → _save_state) шло только по dropEvent цели —
        # ловило этот промежуточный момент, когда карточка сидела сразу в ДВУХ
        # списках, и _sync_placements_from_widgets записывала пак ещё и в
        # старый уровень. При закрытии/открытии тир-листа пак «возвращался»
        # туда же. Эмит здесь (после реального завершения перемещения)
        # гарантированно перезаписывает состояние уже корректными данными.
        self.dropped.emit()

    def dropEvent(self, e):
        super().dropEvent(e)
        self.dropped.emit()
        if self._auto_height:
            QTimer.singleShot(0, self.update_height)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._auto_height:
            self.update_height()

    def update_height(self):
        """Подгоняет высоту под фактически разложенные (с переносом) карточки —
        по нижней границе самой нижней карточки."""
        if not self._auto_height:
            return
        if self.count() == 0:
            self.setFixedHeight(self._empty_h)
            return
        bottom = 0
        for i in range(self.count()):
            bottom = max(bottom, self.visualItemRect(self.item(i)).bottom())
        self.setFixedHeight(max(self._empty_h, bottom + self.spacing() + 2 * self.frameWidth() + 4))


class _TierListDialog(QDialog):
    """Окно тир-листа: сыгранные паки раскладываются по уровням (drag&drop), у
    каждого пака — свой комментарий и пользовательские теги (хорошие/плохие).
    Всё сохраняется в tier_list.json (см. sg_config.load/save_tier_list) при
    каждом изменении. Отдельной кнопки «Закрыть» нет — окно закрывается крестиком
    (данные и так сохранены)."""

    def __init__(self, pkg_info: dict, parent=None):
        # Без Qt-родителя: на Windows top-level окно с реальным родителем
        # (даже вложенным Window-флагом) получает нативного "owner", из-за
        # чего сворачивание анимируется не в панель задач, а в левый нижний
        # угол экрана (Windows не может для него посчитать iconic-позицию).
        # `parent` всё равно нужен для _tab/размера — держим отдельно.
        super().__init__(None)
        self.setWindowTitle("Тир-лист сыгранных паков")
        # Полноценное окно с кнопкой сворачивания и своей кнопкой в панели задач
        # (иначе клик по иконке проги не сворачивал тир-лист).
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.WindowMinimizeButtonHint
                            | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowCloseButtonHint)
        # Окно должно быть чуть меньше основного окна SI-HYX (по просьбе), а не
        # фиксированного размера — подгоняем под текущий размер главного окна.
        top = parent.window() if parent is not None else None
        if top is not None and top.width() > 200 and top.height() > 200:
            self.resize(max(900, top.width() - 60), max(600, top.height() - 60))
        else:
            self.resize(1200, 820)
        self._tab = parent   # SigstatsTab — для ПКМ-действий над паком
        if self._tab is not None:
            # Бегущий процент скачивания у карточки — независимо от того, где
            # запущено скачивание (эта кнопка или таблица на вкладке); см.
            # SigstatsTab.download_progress / _on_download_progress ниже.
            self._tab.download_progress.connect(self._on_download_progress)
            # Библиотека паков перечиталась (скачивание завершилось, .siq
            # удалён и т.п.) — перерисовываем галочки «скачан» в пуле.
            self._tab.library_changed.connect(self._refresh_all_card_icons)
        self._info = {int(k): str(v) for k, v in pkg_info.items()}

        st = sg_config.load_tier_list()
        self._tiers = list(st["tiers"])
        self._placements = {int(k): v for k, v in st["placements"].items()}
        self._comments = {int(k): v for k, v in st["comments"].items()}
        self._tags = {int(k): list(v) for k, v in st["tags"].items()}
        self._all_tags = list(st["all_tags"])
        # Полярность тега (good/bad) — задаётся вручную (ПКМ на чипе тега),
        # хранится per-tag; тегов без записи (например, только что созданных
        # в старом файле) считаем «хорошими» — см. _tag_kind.
        self._tag_kinds = dict(st.get("tag_kinds", {}))
        # Оценка сложности пака самим пользователем (pid -> уровень из _DIFF_LEVELS).
        self._difficulty = {int(k): v for k, v in st.get("difficulty", {}).items()}
        # Постоянная ссылка публикации: id страницы + секретный токен на её
        # перезапись. Заводятся при первой публикации (см. _publish_online).
        self._publish_id = st.get("publish_id", "")
        self._edit_token = st.get("edit_token", "")
        # Адрес личного воркера пользователя: приоритет — сохранённый в его
        # tier_list.json; иначе то, что зашито в config (обычно пусто).
        self._publish_url = st.get("publish_url", "") or (TIER_LIST_PUBLISH_URL or "")

        self._current_pid = None
        self._loading_editor = False
        self._publishing = False
        self._tier_lists = []   # список (header_edit, _TierCardList) в текущем порядке

        outer = QVBoxLayout(self)

        split = QSplitter(Qt.Orientation.Horizontal)

        # ── Левая часть: уровни (в вертикальном скролле) + кнопка публикации
        # снизу. Кнопка живёт именно тут (а не в общей нижней строке на всю
        # ширину окна) — иначе под правой колонкой оставалась пустая полоса
        # той строки (та самая «пустота под Добавить тег»).
        left_col = QWidget()
        left_col_v = QVBoxLayout(left_col)
        left_col_v.setContentsMargins(0, 0, 0, 0)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_host = QWidget()
        self._board = QVBoxLayout(left_host)
        self._board.setContentsMargins(4, 4, 4, 4)
        self._tiers_host = QVBoxLayout()
        self._board.addLayout(self._tiers_host)
        self._board.addStretch(1)
        left_scroll.setWidget(left_host)
        left_col_v.addWidget(left_scroll, 1)
        split.addWidget(left_col)

        # ── Правая часть: «Не распределено» сверху + редактор снизу ──────────
        # Обычный QVBoxLayout, а не QSplitter — растяжение через stretch-
        # фактор тут надёжно применяется всегда (и на первом лэйауте, и при
        # изменении размера), без сюрпризов от тем/шрифтов, в отличие от
        # QSplitter (по факту ловили там пустоту, несмотря на maximumHeight).
        right = QWidget()
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(0, 0, 0, 0)

        pool_box = QGroupBox("Не распределено")
        pv = QVBoxLayout(pool_box)
        self._pool_list = _TierCardList(auto_height=False)
        self._pool_list.dropped.connect(self._on_drop)
        self._pool_list.itemClicked.connect(self._on_card_clicked)
        self._pool_list.emptyClicked.connect(self._on_empty_clicked)
        self._pool_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._pool_list.customContextMenuRequested.connect(
            lambda pos: self._on_card_menu(self._pool_list, pos))
        pv.addWidget(self._pool_list)
        # «Не распределено» получает МАЛЕНЬКУЮ долю (1), редактор с тегами ниже —
        # всё остальное (4). Раньше было 2:3 — пул занимал вдвое больше высоты,
        # чем сейчас, и освободившееся место ушло области тегов (по просьбе).
        right_v.addWidget(pool_box, 1)

        editor = QWidget()
        ev = QVBoxLayout(editor)
        self._ed_name = QLabel("Выберите пак")
        self._ed_name.setWordWrap(True)
        self._ed_name.setStyleSheet("font-weight:bold;")
        ev.addWidget(self._ed_name)
        ev.addWidget(QLabel("Комментарий:"))
        self._ed_comment = QTextEdit()
        self._ed_comment.setPlaceholderText("Заметки об этом паке…")
        self._ed_comment.setFixedHeight(50)
        self._ed_comment.textChanged.connect(self._on_comment_changed)
        ev.addWidget(self._ed_comment)

        # ── Блок «Сложность пакета» ──────────────────────────────────────────
        diff_box = QGroupBox("Сложность пакета")
        dv = QVBoxLayout(diff_box)
        # Статистика из данных пакета (с сайта): кол-во законченных игр,
        # % попыток и % правильных.
        self._lbl_finished_games = QLabel("Законченных игр: —")
        self._lbl_answer_pct = QLabel("% попыток ответа: —")
        self._lbl_correct_pct = QLabel("% правильных ответов: —")
        dv.addWidget(self._lbl_finished_games)
        dv.addWidget(self._lbl_answer_pct)
        dv.addWidget(self._lbl_correct_pct)
        # Своя оценка сложности — одна из 4 (как на странице поиска паков).
        dv.addWidget(QLabel("Моя оценка:"))
        diff_row = QHBoxLayout()
        diff_row.setSpacing(6)
        self._diff_buttons = {}
        for lvl in _DIFF_LEVELS:
            b = QPushButton(lvl)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, l=lvl: self._set_difficulty(l))
            diff_row.addWidget(b)
            self._diff_buttons[lvl] = b
        dv.addLayout(diff_row)
        ev.addWidget(diff_box)

        ev.addWidget(QLabel("Теги (зелёный — хороший, красный — плохой; "
                            "ПКМ на теге — сменить цвет/переименовать):"))
        tags_scroll = QScrollArea()
        tags_scroll.setWidgetResizable(True)
        tags_scroll.setMinimumHeight(120)
        # По горизонтали скролла быть не должно — чипы всегда умещаются в ширину
        # (длинные переносятся внутри чипа, см. _FlowLayout/_TagChip).
        tags_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Область тегов растягивается на всю доступную высоту редактора (без
        # потолка) — теги должны получать максимум места (по просьбе).
        tags_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._tags_scroll = tags_scroll
        self._tag_chips = {}   # tag -> _TagChip (для точечного обновления вида)
        self._tags_host_w = QWidget()
        self._tags_host = _FlowLayout(self._tags_host_w, margin=0, h_spacing=6, v_spacing=6)
        tags_scroll.setWidget(self._tags_host_w)
        ev.addWidget(tags_scroll, 1)

        new_tag_row = QHBoxLayout()
        self._ed_new_tag = QLineEdit()
        self._ed_new_tag.setPlaceholderText("Новый тег…")
        self._ed_new_tag.returnPressed.connect(self._create_tag)
        new_tag_row.addWidget(self._ed_new_tag, 1)
        btn_add_tag = QPushButton("Добавить тег")
        btn_add_tag.setIcon(get_icon('fa5s.tag'))
        btn_add_tag.setToolTip("Добавить тег — по умолчанию хороший (зелёный), "
                               "поменять цвет можно ПКМ на теге")
        btn_add_tag.clicked.connect(self._create_tag)
        new_tag_row.addWidget(btn_add_tag)
        ev.addLayout(new_tag_row)

        editor.setMinimumWidth(300)
        # Редактор с тегами растягивается и получает БОЛЬШУЮ долю (4 против 1 у
        # пула) — всё лишнее место внутри забирает область тегов.
        right_v.addWidget(editor, 4)
        split.addWidget(right)
        split.setSizes([920, 380])
        # Правая панель автономна от левого тир-листа: при изменении размера
        # окна левая часть держит свою ширину, а вся свободная ширина уходит
        # правой панели (по просьбе).
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)

        # Кнопки внизу левой колонки: «Добавить уровень» слева, «Опубликовать»
        # правее (обе — в левом нижнем углу, а не в строке на всю ширину окна).
        bottom_bar = QHBoxLayout()
        btn_add_tier = QPushButton("Добавить уровень")
        btn_add_tier.setIcon(get_icon('fa5s.plus', color='#a6e3a1'))
        btn_add_tier.setToolTip("Добавить новый уровень (строку) в конец тир-листа")
        btn_add_tier.clicked.connect(self._add_tier)
        bottom_bar.addWidget(btn_add_tier)
        self._btn_publish = QPushButton("Опубликовать")
        self._btn_publish.setIcon(get_icon('fa5s.globe', color='#89b4fa'))
        self._btn_publish.setToolTip("Опубликовать тир-лист как страницу-сайт по "
                                     "постоянной ссылке (адрес воркера спросим "
                                     "при первой публикации).")
        self._btn_publish.clicked.connect(self._publish_online)
        bottom_bar.addWidget(self._btn_publish)
        bottom_bar.addStretch(1)
        left_col_v.addLayout(bottom_bar)

        self._rebuild_tiers()
        self._populate_cards()
        self._refresh_tags_editor()
        self._set_editor_enabled(False)
        self._refresh_difficulty()

    def showEvent(self, e):
        super().showEvent(e)
        # Ширины финализированы только после показа — пересчитываем высоту полос
        # уровней (перенос карточек зависит от доступной ширины).
        QTimer.singleShot(0, self._update_all_heights)

    def _update_all_heights(self):
        for _, lst in self._tier_lists:
            lst.update_height()

    # ── Построение уровней ────────────────────────────────────────────────────
    def _rebuild_tiers(self):
        """Пересобирает строки уровней из self._tiers (имена/порядок).
        Раскладку паков не трогает — её восстанавливает _populate_cards."""
        while self._tiers_host.count():
            item = self._tiers_host.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._tier_lists = []
        for idx, tname in enumerate(self._tiers):
            self._tiers_host.addWidget(self._make_tier_row(idx, tname))

    def _make_tier_row(self, idx: int, tname: str) -> QWidget:
        color = _TIER_COLORS[idx % len(_TIER_COLORS)]
        row = QFrame()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)

        head = QWidget()
        head.setFixedWidth(110)
        hv = QVBoxLayout(head)
        hv.setContentsMargins(2, 2, 4, 2)
        name_edit = QLineEdit(tname)
        name_edit.setToolTip("Название уровня")
        name_edit.setStyleSheet(f"font-weight:bold;color:{color};")
        name_edit.editingFinished.connect(self._save_state)
        hv.addWidget(name_edit)
        ctl = QHBoxLayout()
        ctl.setContentsMargins(0, 0, 0, 0)
        btn_up = QPushButton()
        btn_up.setIcon(get_icon('fa5s.arrow-up'))
        btn_up.setFixedWidth(30)
        btn_up.setToolTip("Поднять уровень выше")
        btn_up.clicked.connect(lambda _=False, i=idx: self._move_tier(i, -1))
        ctl.addWidget(btn_up)
        btn_down = QPushButton()
        btn_down.setIcon(get_icon('fa5s.arrow-down'))
        btn_down.setFixedWidth(30)
        btn_down.setToolTip("Опустить уровень ниже")
        btn_down.clicked.connect(lambda _=False, i=idx: self._move_tier(i, 1))
        ctl.addWidget(btn_down)
        btn_del = QPushButton()
        btn_del.setIcon(get_icon('fa5s.trash', color='#f38ba8'))
        btn_del.setFixedWidth(30)
        btn_del.setToolTip("Удалить уровень (паки вернутся в «Не распределено»)")
        btn_del.clicked.connect(lambda _=False, i=idx: self._delete_tier(i))
        ctl.addWidget(btn_del)
        hv.addLayout(ctl)
        hv.addStretch(1)
        h.addWidget(head)

        lst = _TierCardList(auto_height=True)
        lst.dropped.connect(self._on_drop)
        lst.itemClicked.connect(self._on_card_clicked)
        lst.emptyClicked.connect(self._on_empty_clicked)
        lst.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lst.customContextMenuRequested.connect(
            lambda pos, l=lst: self._on_card_menu(l, pos))
        h.addWidget(lst, 1)

        self._tier_lists.append((name_edit, lst))
        return row

    def _iter_tier_lists(self):
        """(текущее имя уровня, его список) в порядке отображения."""
        for name_edit, lst in self._tier_lists:
            yield name_edit.text().strip() or "—", lst

    def _all_lists(self):
        return [self._pool_list] + [l for _, l in self._tier_lists]

    def _make_card(self, pid: int, in_pool: bool = False) -> QListWidgetItem:
        it = QListWidgetItem(self._card_label(pid))
        it.setData(Qt.ItemDataRole.UserRole, int(pid))
        it.setFlags((it.flags() | Qt.ItemFlag.ItemIsDragEnabled
                     | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    & ~Qt.ItemFlag.ItemIsDropEnabled)
        self._set_card_icon(it, pid, in_pool)
        return it

    def _pkg_downloaded(self, pid: int) -> bool:
        if self._tab is None:
            return False
        r = self._tab._pkg_row_by_id(pid)
        return r is not None and r.get("siq_downloaded") == 1

    def _set_card_icon(self, it: QListWidgetItem, pid: int, in_pool: bool):
        """Значок карточки: галочка (пак уже скачан) — только в «Не распределено»
        (по просьбе, в остальных списках не нужна — там паки уже разложены по
        уровням), плюс иконка комментария. Обе сразу — составной иконкой
        (см. get_icon(overlay=...))."""
        has_comment = bool((self._comments.get(pid) or "").strip())
        downloaded = in_pool and self._pkg_downloaded(pid)
        if has_comment and downloaded:
            it.setIcon(get_icon('fa5s.comment-dots', color='#89b4fa',
                                 overlay='fa5s.check', overlay_color='#a6e3a1'))
        elif downloaded:
            it.setIcon(get_icon('fa5s.check', color='#a6e3a1'))
        elif has_comment:
            it.setIcon(get_icon('fa5s.comment-dots', color='#89b4fa'))
        else:
            it.setIcon(QIcon())

    def _refresh_all_card_icons(self):
        """Перестраивает значки во ВСЕХ списках — вызывается после любого
        перемещения карточки (drag&drop/контекстное меню), т.к. галочка
        «скачан» зависит от того, в пуле карточка сейчас или нет."""
        for i in range(self._pool_list.count()):
            it = self._pool_list.item(i)
            pid = it.data(Qt.ItemDataRole.UserRole)
            if pid is not None:
                self._set_card_icon(it, int(pid), True)
        for _, lst in self._tier_lists:
            for i in range(lst.count()):
                it = lst.item(i)
                pid = it.data(Qt.ItemDataRole.UserRole)
                if pid is not None:
                    self._set_card_icon(it, int(pid), False)

    def _card_label(self, pid: int) -> str:
        # Теги пака сознательно не выводятся рядом с названием в самом тир-листе
        # (по просьбе) — они видны только в редакторе справа.
        return self._info.get(pid, f"#{pid}")

    def _populate_cards(self):
        """Раскладывает карточки паков по уровням из self._placements; всё, что
        не размещено (или чей уровень удалён), — в «Не распределено»."""
        valid_tiers = {name for name, _ in self._iter_tier_lists()}
        self._pool_list.clear()
        lists_by_name = {name: lst for name, lst in self._iter_tier_lists()}
        for name, lst in self._iter_tier_lists():
            lst.clear()
        for pid in self._info:
            tier = self._placements.get(pid)
            if tier in valid_tiers and tier in lists_by_name:
                lists_by_name[tier].addItem(self._make_card(pid, in_pool=False))
            else:
                self._pool_list.addItem(self._make_card(pid, in_pool=True))
        self._update_all_heights()

    def _sync_placements_from_widgets(self):
        placements = {}
        for name, lst in self._iter_tier_lists():
            for i in range(lst.count()):
                pid = lst.item(i).data(Qt.ItemDataRole.UserRole)
                if pid is not None:
                    placements[int(pid)] = name
        self._placements = placements

    # ── Реакции ────────────────────────────────────────────────────────────
    def _on_drop(self):
        # Карточка переехала между списками — пересохраняем раскладку. Пул мог
        # опустеть/пополниться, но сами элементы уже на месте, полный ребилд не
        # нужен (он сбросил бы выделение/позиции). Высоты полос пересчитаем на
        # следующей итерации event loop (элементы уже вставлены).
        self._save_state()
        # Галочка «скачан» зависит от того, в пуле карточка или нет —
        # перестраиваем значки после любого перемещения.
        self._refresh_all_card_icons()
        QTimer.singleShot(0, self._update_all_heights)

    def _on_card_clicked(self, item):
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid is None:
            return
        pid = int(pid)
        # Снимаем выделение во всех остальных списках, чтобы «текущий» пак был
        # ровно один (QListWidget-ы независимы, общего выделения нет).
        for lst in self._all_lists():
            if lst is not item.listWidget():
                lst.clearSelection()
        self._current_pid = pid
        self._load_editor(pid)

    def _on_empty_clicked(self):
        """Клик мимо карточек — снимаем «текущий» пак (по просьбе)."""
        if self._current_pid is None:
            return
        for lst in self._all_lists():
            lst.clearSelection()
        self._current_pid = None
        self._ed_name.setText("Выберите пак")
        self._loading_editor = True
        self._ed_comment.setPlainText("")
        self._loading_editor = False
        self._set_editor_enabled(False)
        self._refresh_difficulty()
        self._refresh_tags_editor()

    def _on_card_menu(self, lst, pos):
        """ПКМ на карточке пака: скопировать название + те же действия, что и в
        основном окне (см. SigstatsTab._add_pkg_context_actions). Если выделено
        сразу НЕСКОЛЬКО карточек (см. ExtendedSelection в _TierCardList) — меню
        с батч-действиями над всем выделением (см. _card_multi_menu)."""
        item = lst.itemAt(pos)
        if item is None:
            return
        selected = lst.selectedItems()
        if item not in selected:
            # ПКМ по невыделенной карточке — переносим выделение на неё одну,
            # как в проводнике, а не действуем над старым набором.
            lst.setCurrentItem(item)
            selected = [item]
        if len(selected) > 1:
            self._card_multi_menu(lst, pos, selected)
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid is None:
            return
        pid = int(pid)
        name = self._info.get(pid, f"#{pid}")
        menu = QMenu(self)
        act_copy = menu.addAction(get_icon('fa5s.copy'), "Скопировать название")
        act_copy.triggered.connect(lambda checked=False, n=name: QApplication.clipboard().setText(n))
        if lst is not self._pool_list:
            # Явная альтернатива drag&drop — перетаскивать карточку через весь
            # сплиттер в узкий пул неудобно, особенно если уровень далеко внизу
            # прокрутки (по просьбе).
            act_unassign = menu.addAction(get_icon('fa5s.reply'), "Вернуть в «Не распределено»")
            act_unassign.triggered.connect(lambda checked=False, p=pid: self._return_to_pool(p))
        r = self._tab._pkg_row_by_id(pid) if self._tab is not None else None
        if r is not None:
            menu.addSeparator()
            self._tab._add_pkg_context_actions(menu, r)
        menu.exec(lst.viewport().mapToGlobal(pos))

    def _card_multi_menu(self, lst, pos, items):
        """Батч-меню для нескольких выделенных карточек разом: скачать .siq
        (параллельно, см. SigstatsTab._download_for_rows) и скопировать все
        названия списком."""
        pids = [int(it.data(Qt.ItemDataRole.UserRole)) for it in items
                if it.data(Qt.ItemDataRole.UserRole) is not None]
        if not pids:
            return
        names = [self._info.get(pid, f"#{pid}") for pid in pids]
        menu = QMenu(self)
        act_copy = menu.addAction(get_icon('fa5s.copy'), f"Скопировать названия ({len(names)})")
        act_copy.triggered.connect(lambda checked=False, ns=names:
                                    QApplication.clipboard().setText("\n".join(ns)))
        if lst is not self._pool_list:
            act_unassign = menu.addAction(get_icon('fa5s.reply'), f"Вернуть в «Не распределено» ({len(pids)})")
            act_unassign.triggered.connect(lambda checked=False, ps=pids: self._return_to_pool_many(ps))
        if self._tab is not None:
            import pandas as pd
            rows = [self._tab._pkg_row_by_id(pid) for pid in pids]
            rows = [r for r in rows if r is not None]
            # Только реально скачиваемые (есть sibrowser_id, ещё не скачан) — иначе
            # счётчик в пункте меню обещал бы больше, чем реально скачается.
            rows = [r for r in rows if pd.notna(r.get("sibrowser_id")) and r.get("siq_downloaded") != 1]
            if rows:
                menu.addSeparator()
                act_dl = menu.addAction(get_icon('fa5s.download'), f"Скачать .siq ({len(rows)})")
                act_dl.triggered.connect(lambda checked=False, rs=rows: self._tab._download_for_rows(rs))
        menu.exec(lst.viewport().mapToGlobal(pos))

    def _on_download_progress(self, pid, pct):
        """Бегущий процент скачивания у карточки пака (если он есть на этом
        тир-листе, в любом из уровней/пуле) — ширина текста держится постоянной
        (нулями слева), чтобы карточка не «прыгала» на каждый тик прогресса."""
        base = self._card_label(pid)
        suffix = f"  ·  {pct:02d}%" if 0 <= pct < 100 else ""
        for lst in self._all_lists():
            for i in range(lst.count()):
                it = lst.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == pid:
                    it.setText(base + suffix)
                    return

    def _move_tier(self, idx: int, delta: int):
        self._sync_placements_from_widgets()
        names = [n for n, _ in self._iter_tier_lists()]
        j = idx + delta
        if idx < 0 or idx >= len(names) or j < 0 or j >= len(names):
            return
        names[idx], names[j] = names[j], names[idx]
        self._tiers = names
        self._rebuild_tiers()
        self._populate_cards()
        self._save_state()

    def _delete_tier(self, idx: int):
        self._sync_placements_from_widgets()
        names = [n for n, _ in self._iter_tier_lists()]
        if idx < 0 or idx >= len(names):
            return
        removed = names[idx]
        # Паки удаляемого уровня «разразмещаем» — уйдут в пул при _populate_cards.
        self._placements = {p: t for p, t in self._placements.items() if t != removed}
        del names[idx]
        self._tiers = names
        self._rebuild_tiers()
        self._populate_cards()
        self._save_state()

    def _add_tier(self):
        """Добавляет новый пустой уровень в конец тир-листа. Имя подбираем
        уникальным («Новый», «Новый 2», …), чтобы не совпало с существующим."""
        self._sync_placements_from_widgets()
        names = [n for n, _ in self._iter_tier_lists()]
        base = "Новый"
        name = base
        i = 2
        while name in names:
            name = f"{base} {i}"
            i += 1
        self._tiers = names + [name]
        self._rebuild_tiers()
        self._populate_cards()
        self._save_state()
        QTimer.singleShot(0, self._update_all_heights)

    # ── Редактор комментария/тегов ────────────────────────────────────────────
    def _set_editor_enabled(self, on: bool):
        # Комментарий привязан к конкретному паку — без выбора недоступен.
        # Палитра тегов (создание/удаление/хороший-плохой) — общая для всех
        # паков, поэтому остаётся доступной даже без выбора (по просьбе).
        self._ed_comment.setEnabled(on)
        for b in self._diff_buttons.values():
            b.setEnabled(on)

    def _load_editor(self, pid: int):
        self._loading_editor = True
        self._ed_name.setText(self._info.get(pid, f"#{pid}"))
        self._ed_comment.setPlainText(self._comments.get(pid, ""))
        self._loading_editor = False
        self._set_editor_enabled(True)
        self._refresh_difficulty()
        self._refresh_tags_editor()

    # ── Блок сложности ────────────────────────────────────────────────────────
    def _refresh_difficulty(self):
        """Обновляет статистику (% попыток/правильных из данных пакета) и
        подсветку кнопки выбранной оценки под текущий пак."""
        pid = self._current_pid
        ap = cp = finished = None
        if pid is not None and self._tab is not None:
            r = self._tab._pkg_row_by_id(pid)
            if r is not None:
                ap, cp = r.get("answer_pct"), r.get("correct_pct")
                finished = r.get("completed_games")
        self._lbl_finished_games.setText(f"Законченных игр: {_fmt_int(finished)}")
        self._lbl_answer_pct.setText(f"% попыток ответа: {_fmt_pct(ap, 0)}")
        self._lbl_correct_pct.setText(f"% правильных ответов: {_fmt_pct(cp, 0)}")
        chosen = self._difficulty.get(pid) if pid is not None else None
        for lvl, b in self._diff_buttons.items():
            on = (lvl == chosen)
            b.setChecked(on)
            color = _DIFF_COLORS[lvl]
            if on:
                b.setStyleSheet(f"QPushButton{{background:{color};color:#11111b;"
                                f"border:1px solid {color};border-radius:6px;"
                                f"padding:4px 6px;font-weight:bold;}}")
            else:
                b.setStyleSheet(f"QPushButton{{background:transparent;color:{color};"
                                f"border:1px solid {color};border-radius:6px;"
                                f"padding:4px 6px;}}")

    def _set_difficulty(self, lvl: str):
        if self._current_pid is None:
            self._refresh_difficulty()
            return
        # Повторный клик по выбранному уровню — снимает оценку.
        if self._difficulty.get(self._current_pid) == lvl:
            self._difficulty.pop(self._current_pid, None)
        else:
            self._difficulty[self._current_pid] = lvl
        self._refresh_difficulty()
        self._save_state()

    def _on_comment_changed(self):
        if self._loading_editor or self._current_pid is None:
            return
        self._comments[self._current_pid] = self._ed_comment.toPlainText()
        self._refresh_card(self._current_pid)
        self._save_state()

    def _tag_kind(self, tag: str) -> str:
        kind = self._tag_kinds.get(tag)
        return kind if kind in _TAG_KIND_COLORS else "good"

    def _set_tag_kind(self, tag: str, kind: str):
        self._tag_kinds[tag] = kind if kind in _TAG_KIND_COLORS else "good"
        # Полярность меняет порядок (хорошие сверху/плохие снизу) — приходится
        # пересобрать список целиком, точечной перекраски тут недостаточно.
        self._refresh_tags_editor()
        self._save_state()

    def _refresh_tags_editor(self):
        # Очищаем прежние чипы.
        self._tag_chips = {}
        while self._tags_host.count():
            item = self._tags_host.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not self._all_tags:
            hint = QLabel("Тегов пока нет — создайте первый ниже.")
            hint.setStyleSheet("color:#6c7086;")
            hint.setWordWrap(True)
            self._tags_host.addWidget(hint)
            return
        assigned = set(self._tags.get(self._current_pid, [])) if self._current_pid is not None else set()
        # Хорошие сверху, нейтральные посередине, плохие снизу (по просьбе);
        # порядок внутри группы — стабильный (как были созданы).
        tags_sorted = sorted(self._all_tags, key=lambda t: _TAG_KIND_ORDER.get(self._tag_kind(t), 0))
        for tag in tags_sorted:
            color = _TAG_KIND_COLORS[self._tag_kind(tag)]
            checked = tag in assigned
            chip = _TagChip(tag, color, checked)
            chip.toggled.connect(lambda on, t=tag: self._toggle_tag(t, on))
            chip.customContextMenuRequested.connect(
                lambda pos, t=tag: self._tag_context_menu(t))
            self._tags_host.addWidget(chip)
            self._tag_chips[tag] = chip

    def _toggle_tag(self, tag: str, on: bool):
        # Чип уже сам обновил свой вид (галочку/заливку) — список НЕ пересобираем,
        # поэтому позиция скролла не прыгает (по просьбе).
        if self._current_pid is None:
            # Тег без выбранного пака нечему присваивать — откатываем галочку.
            chip = self._tag_chips.get(tag)
            if chip is not None:
                chip.set_checked(False)
            return
        cur = list(self._tags.get(self._current_pid, []))
        if on and tag not in cur:
            cur.append(tag)
        elif not on and tag in cur:
            cur.remove(tag)
        self._tags[self._current_pid] = cur
        self._refresh_card(self._current_pid)
        self._save_state()

    def _create_tag(self):
        tag = self._ed_new_tag.text().strip()
        if not tag:
            return
        if tag not in self._all_tags:
            self._all_tags.append(tag)
        self._tag_kinds.setdefault(tag, "good")
        # Новый тег сразу присваиваем текущему паку (если он выбран).
        if self._current_pid is not None:
            cur = list(self._tags.get(self._current_pid, []))
            if tag not in cur:
                cur.append(tag)
            self._tags[self._current_pid] = cur
            self._refresh_card(self._current_pid)
        self._ed_new_tag.clear()
        self._refresh_tags_editor()
        self._save_state()

    def _tag_context_menu(self, tag: str):
        from PyQt6.QtGui import QCursor
        menu = QMenu(self)
        current = self._tag_kind(tag)
        labels = {"good": "хорошим (зелёный)", "neutral": "нейтральным (белый)", "bad": "плохим (красный)"}
        for kind in ("good", "neutral", "bad"):
            if kind == current:
                continue
            act = menu.addAction(get_icon('fa5s.circle', color=_TAG_KIND_COLORS[kind]),
                                 f"Сделать «{tag}» {labels[kind]}")
            act.triggered.connect(lambda checked=False, t=tag, k=kind: self._set_tag_kind(t, k))
        act_rename = menu.addAction(get_icon('fa5s.pen'), f"Переименовать тег «{tag}»")
        act_rename.triggered.connect(lambda checked=False, t=tag: self._rename_tag(t))
        act_del = menu.addAction(get_icon('fa5s.trash', color='#f38ba8'),
                                 f"Удалить тег «{tag}» из палитры")
        act_del.triggered.connect(lambda checked=False, t=tag: self._delete_tag(t))
        menu.exec(QCursor.pos())

    def _rename_tag(self, tag: str):
        from PyQt6.QtWidgets import QInputDialog
        new, ok = QInputDialog.getText(self, "Переименовать тег",
                                       "Новое название тега:", text=tag)
        if not ok:
            return
        new = new.strip()
        if not new or new == tag:
            return
        if new in self._all_tags:
            msgbox_information(self, "Переименовать тег",
                              f"Тег «{new}» уже есть в палитре.")
            return
        # Переносим название в палитре (сохраняя порядок), полярность и все
        # присвоения по пакам.
        self._all_tags = [new if t == tag else t for t in self._all_tags]
        if tag in self._tag_kinds:
            self._tag_kinds[new] = self._tag_kinds.pop(tag)
        for pid in list(self._tags):
            if tag in self._tags[pid]:
                self._tags[pid] = [new if t == tag else t for t in self._tags[pid]]
        self._refresh_tags_editor()
        self._save_state()

    def _delete_tag(self, tag: str):
        if msgbox_question(
                self, "Удалить тег",
                f"Удалить тег «{tag}» из палитры и снять его со всех паков?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._all_tags = [t for t in self._all_tags if t != tag]
        self._tag_kinds.pop(tag, None)
        for pid in list(self._tags):
            if tag in self._tags[pid]:
                self._tags[pid] = [t for t in self._tags[pid] if t != tag]
                self._refresh_card(pid)
        self._refresh_tags_editor()
        self._save_state()

    def _refresh_card(self, pid: int):
        it = self._find_item(pid)
        if it is None:
            return
        it.setText(self._card_label(pid))
        self._set_card_icon(it, pid, it.listWidget() is self._pool_list)
        self._update_all_heights()

    def _return_to_pool(self, pid: int):
        """Явный перенос карточки пака из уровня в «Не распределено» — то же,
        что перетащить её мышью, но через контекстное меню (по просьбе)."""
        it = self._find_item(pid)
        if it is None:
            return
        lst = it.listWidget()
        if lst is None or lst is self._pool_list:
            return
        self._pool_list.addItem(lst.takeItem(lst.row(it)))
        self._set_card_icon(it, pid, True)
        self._placements.pop(pid, None)
        self._update_all_heights()
        self._save_state()

    def _return_to_pool_many(self, pids):
        for pid in pids:
            self._return_to_pool(pid)

    def _find_item(self, pid: int):
        for lst in self._all_lists():
            for i in range(lst.count()):
                it = lst.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == pid:
                    return it
        return None

    # ── Ссылка на пак (для публикации) ──────────────────────────────────────
    def _pkg_url(self, pid: int):
        """Ссылка на пак (sibrowser.ru или Steam Workshop) для публикации — та же
        логика, что и у SigstatsTab._open_link_for_row, но возвращает URL, а не
        открывает браузер. None, если строка пака не нашлась (например, БД
        сейчас пуста) или у пака нет ни sibrowser_id, ни steam_id."""
        if self._tab is None:
            return None
        r = self._tab._pkg_row_by_id(pid)
        if r is None:
            return None
        import pandas as pd
        if r.get("source") == "steam" and pd.notna(r.get("steam_id")):
            return sg_steam_workshop.workshop_url(str(r["steam_id"]))
        if pd.notna(r.get("sibrowser_id")):
            return f"{sg_config.SIBROWSER_BASE}/packages/{int(r['sibrowser_id'])}"
        return None

    def _pkg_author(self, pid: int) -> str:
        """Автор(ы) пака для публикации — несколько через запятую. Пусто, если
        строка пака не нашлась или авторов нет."""
        if self._tab is None:
            return ""
        r = self._tab._pkg_row_by_id(pid)
        if r is None:
            return ""
        authors = r.get("authors")
        if isinstance(authors, list) and authors:
            return ", ".join(str(a) for a in authors)
        return ""

    def _pkg_is_steam(self, pid: int) -> bool:
        """Пак пришёл из Steam Workshop — на сайте у такого рисуется значок Steam
        (см. tier_worker.js renderPack)."""
        if self._tab is None:
            return False
        r = self._tab._pkg_row_by_id(pid)
        return r is not None and r.get("source") == "steam"

    # ── Публикация онлайн (Cloudflare Worker, см. tier_worker.js) ──────────────
    def _build_publish_model(self) -> dict:
        """Модель тир-листа для отправки на worker: уровни в порядке отображения
        (с цветом), в каждом — паки с готовой ссылкой, автором, сложностью,
        комментарием и тегами (с полярностью good/neutral/bad). «Не распределено»
        не публикуется — оно не в _iter_tier_lists. Пустые уровни оставляем (на
        странице рисуются «пусто»)."""
        self._sync_placements_from_widgets()
        tiers = []
        for idx, (name, lst) in enumerate(self._iter_tier_lists()):
            color = _TIER_COLORS[idx % len(_TIER_COLORS)]
            packs = []
            for i in range(lst.count()):
                pid = lst.item(i).data(Qt.ItemDataRole.UserRole)
                if pid is None:
                    continue
                pid = int(pid)
                packs.append({
                    "id": pid,
                    "name": self._info.get(pid, f"#{pid}"),
                    "url": self._pkg_url(pid) or "",
                    "author": self._pkg_author(pid),
                    "steam": self._pkg_is_steam(pid),
                    "difficulty": self._difficulty.get(pid) or "",
                    "comment": (self._comments.get(pid) or "").strip(),
                    "tags": [{"text": t, "kind": self._tag_kind(t)}
                             for t in (self._tags.get(pid) or [])],
                })
            tiers.append({"name": name, "color": color, "packs": packs})
        return {"title": "Тир-лист от GoldensFire по аниме-пакам", "tiers": tiers}

    def _configure_publish_url(self) -> bool:
        """Спрашивает у пользователя адрес ЕГО Cloudflare Worker + даёт ссылку на
        гайд. Возвращает True, если адрес задан (сохранён в self._publish_url)."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Настройка публикации")
        v = QVBoxLayout(dlg)
        info = QLabel(
            "Публикация выкладывает тир-лист веб-страницей на <b>вашем личном</b> "
            "бесплатном сервере Cloudflare Worker (поднимается один раз за ~5 минут)."
            "<br><br>Вставьте адрес своего воркера:")
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(info)
        ed = QLineEdit(self._publish_url)
        ed.setPlaceholderText("https://<имя>.<аккаунт>.workers.dev")
        v.addWidget(ed)
        guide = QLabel('<a href="guide">Открыть пошаговый гайд (DEPLOY_TIER.md)</a>')
        guide.setTextFormat(Qt.TextFormat.RichText)

        def _open_guide(_=None):
            import os
            for base in (CONFIG_DIR, os.path.dirname(os.path.abspath(__file__))):
                if not base:
                    continue
                p = os.path.join(base, "DEPLOY_TIER.md")
                if os.path.exists(p):
                    webbrowser.open("file:///" + p.replace("\\", "/"))
                    return
            webbrowser.open("https://dash.cloudflare.com/")
        guide.linkActivated.connect(_open_guide)
        v.addWidget(guide)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        url = ed.text().strip()
        if not url:
            return False
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._publish_url = url
        self._save_state()
        return True

    def _publish_online(self):
        if self._publishing:
            return
        # Адрес воркера ещё не задан — просим ввести его (с ссылкой на гайд).
        if not self._publish_url:
            if not self._configure_publish_url():
                return
        model = self._build_publish_model()
        if not any(t["packs"] for t in model["tiers"]):
            msgbox_information(self, "Публикация",
                               "Тир-лист пуст — разложите паки по уровням и попробуйте снова.")
            return
        import secrets
        # id/токен заводим один раз и переиспользуем, чтобы ссылка не менялась.
        if not self._publish_id:
            self._publish_id = secrets.token_urlsafe(9)
        if not self._edit_token:
            self._edit_token = secrets.token_urlsafe(24)
        base = self._publish_url.rstrip("/")
        url = f"{base}/tier/{self._publish_id}"
        payload = {
            "title": model["title"],
            "tiers": model["tiers"],
            "updated": int(_dt.datetime.now().timestamp()),
        }
        self._publishing = True
        self._btn_publish.setEnabled(False)
        self._btn_publish.setText("Публикую…")
        self._pub_emitter = _TierPublishEmitter()
        self._pub_emitter.done.connect(self._on_published)
        import threading
        threading.Thread(
            target=_post_tier, args=(url, payload, self._edit_token, self._pub_emitter),
            daemon=True).start()

    def _on_published(self, ok: bool, result: str):
        self._publishing = False
        self._btn_publish.setEnabled(True)
        self._btn_publish.setText("Опубликовать")
        if not ok:
            hint = ""
            if result == "HTTP 403":
                hint = ("\n\nЭта ссылка занята другим токеном. Такое бывает, если "
                        "tier_list.json переносили между устройствами. Можно сбросить "
                        "ссылку кнопкой «Опубликовать» ещё раз после удаления полей "
                        "publish_id/edit_token из tier_list.json.")
            msgbox_warning(self, "Публикация",
                           "Не удалось опубликовать тир-лист"
                           + (f": {result}" if result else "")
                           + ".\nПроверьте интернет и адрес вашего воркера." + hint)
            return
        page_url = result or f"{self._publish_url.rstrip('/')}/tier/{self._publish_id}"
        # Ссылка теперь постоянная — сохраняем id/токен, чтобы переиспользовать.
        self._save_state()
        QApplication.clipboard().setText(page_url)
        if msgbox_question(
                self, "Опубликовано",
                f"Тир-лист опубликован и ссылка скопирована в буфер обмена:\n\n{page_url}\n\n"
                "Её можно вставить в Дискорд — страница откроется у любого. При "
                "следующей публикации ссылка останется той же (обновится содержимое).\n\n"
                "Открыть страницу в браузере сейчас?"
        ) == QMessageBox.StandardButton.Yes:
            webbrowser.open(page_url)

    # ── Сохранение ────────────────────────────────────────────────────────────
    def _save_state(self):
        self._sync_placements_from_widgets()
        data = {
            "tiers": [n for n, _ in self._iter_tier_lists()],
            "placements": {str(k): v for k, v in self._placements.items()},
            "comments": {str(k): v for k, v in self._comments.items() if (v or "").strip()},
            "tags": {str(k): v for k, v in self._tags.items() if v},
            "all_tags": self._all_tags,
            "tag_kinds": {t: self._tag_kind(t) for t in self._all_tags},
            "difficulty": {str(k): v for k, v in self._difficulty.items() if v},
            "publish_id": self._publish_id,
            "edit_token": self._edit_token,
            "publish_url": self._publish_url,
        }
        try:
            sg_config.save_tier_list(data)
        except Exception:
            pass
