# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# Логика генерации портирована с разрешения автора из проекта ASPG (Anime Songs
# SiGame Pack Generator), Copyright (c) Leleath, лицензия MIT —
# https://github.com/Leleath/aspg
#
# animepack_tab.py — вкладка «Генерация аниме-пака». Раскладка как у
# ShikimoriHYX: слева контент (состав пака + лог + прогресс), справа
# прокручиваемая панель настроек. Вся работа идёт в QThreadPool, интерфейс не
# виснет; сеть и сборка живут в animepack_api.py / animepack.py.
from __future__ import annotations

import os
import time
from typing import Optional

from PyQt6.QtCore import (Qt, QObject, QRect, QRunnable, QThreadPool, QSize,
                          QTimer, pyqtSignal)
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QToolButton, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QGroupBox, QScrollArea, QFrame, QSizePolicy, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMenu, QAbstractItemView,
    QDialog, QListWidget, QListWidgetItem,
)

from msgbox import msgbox_critical, msgbox_information, msgbox_warning

try:
    from config import get_icon
except Exception:  # pragma: no cover
    def get_icon(name, color="#cdd6f4"):
        from PyQt6.QtGui import QIcon
        return QIcon()

try:
    from animepack import (ANAGRAM_CHARS_PER_SEC, ANAGRAM_CPS_MAX,
                           ANAGRAM_KIND, ANAGRAM_LANG_LABELS, ANAGRAM_LANGS,
                           ANAGRAM_MAX_CHARS, ANAGRAM_MIN_SECONDS,
                           ANIME_KINDS, ANSWER_IMAGE_MAX, CATEGORY_LABELS,
                           CHAR_KIND, CHAR_ROLES,
                           CHAR_ROLE_LABELS, FRAME_KIND,
                           KIND_LABELS, KIND_TITLES, MANGA_KIND,
                           MANGA_QUESTIONS, MANGA_QUESTION_LABELS,
                           MAX_PACK_MB, PIXEL_BLOCK, PIXEL_FPS, PIXEL_KIND,
                           PIXEL_SECONDS, PIXEL_STEPS, PLOT_KIND, PLOT_MODES,
                           PLOT_MODE_LABELS, SILENT_KINDS, SONG_CATEGORIES,
                           VIDEO_CRF, VIDEO_CUT, VIDEO_KIND, VIDEO_PRESET,
                           AnimePackError,
                           AnimePackGenerator, PackSettings, UserList,
                           arrange_questions, fmt_elapsed)
    from animepack_api import (LIST_SOURCES, LIST_STATUSES,
                               MANGA_KINDS, MANGA_KIND_LABELS, SOURCE_LABELS,
                               STATUS_LABELS, TARGET_LABELS, ShikimoriApi)
    from gemini_api import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
    from gemini_api import MODELS as GEMINI_MODELS
    # Общая с «Апгрейдом аниме-пака» кладовая обложек — вкладке нужны её
    # размер (подпись под галочкой) и кнопка «Очистить».
    import poster_cache
    from poster_cache import POSTER_CACHE_MB
    _HAS_CORE, _IMPORT_ERROR = True, ""
except Exception as e:  # pragma: no cover — нет requests и т.п.
    _HAS_CORE, _IMPORT_ERROR = False, str(e)

# Палитра — та же, что во вкладке ShikimoriHYX (Catppuccin Mocha).
C = {
    "bg": "#1e1e2e", "surface": "#181825", "surface2": "#24273a",
    "surface3": "#313244", "border": "#45475a", "accent": "#89b4fa",
    "accent2": "#b4befe", "text": "#cdd6f4", "text2": "#a6adc8",
    "text3": "#6c7086", "green": "#a6e3a1", "yellow": "#f9e2af", "red": "#f38ba8",
}

# Короткие имена сайтов для карточки списка. Полные («MyAnimeList», «Shikimori»)
# съедали две трети её ширины, и ник в поле не помещался — а сайтов всего три и
# в лицо они узнаются (полные имена остались в подсказке и в окне сохранённых).
SOURCE_SHORT = {"myanimelist": "MAL", "shikimori": "Shiki", "anilist": "AniList"}


def _kind_word(kind: str) -> str:
    """Название типа вопроса для строки-подсказки: «опенинг», «кадр», но OST —
    как есть: аббревиатуру строчными писать нельзя."""
    title = KIND_TITLES.get(kind, kind)
    return title if title.isupper() else title.lower()


def _no_wheel(widget):
    """Отучает поле менять значение колёсиком мыши.

    Панель настроек длинная и прокручивается колесом; стоило курсору проехать
    над счётчиком — и он молча менял число, а прокрутка вставала. Событие
    отдаём дальше по цепочке, чтобы прокручивалась сама панель."""
    def wheelEvent(event, _w=widget):
        event.ignore()
    widget.wheelEvent = wheelEvent
    # Без StrongFocus поле ловило бы колесо и без клика по нему.
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return widget


# ─────────────────────────────────────────────────────────────────────────────
# Ползунок состава пака
# ─────────────────────────────────────────────────────────────────────────────
class _ShareBar(QWidget):
    """Полоса, делящая сотню процентов между несколькими частями.

    Готового многоручкового ползунка в Qt нет, поэтому полоса своя: ручки делят
    её на части, снизу — легенда с процентами. Тянуть можно и за саму границу, и
    просто кликнув по полосе — ближняя ручка приедет туда.

    Части задаются списком (ключ, подпись, цвет) и МЕНЯЮТСЯ на ходу: одна и та
    же полоса делит и состав пака, и типы песен, и списки людей."""

    changed = pyqtSignal()

    BAR_H = 16
    HANDLE_W = 9
    # Цвета частей по кругу — на случай, когда частей сколько угодно (списки).
    PALETTE = ("accent", "accent2", "green", "yellow", "red", "text2")

    def __init__(self, parts=(), parent=None):
        super().__init__(parent)
        self._labels: dict[str, str] = {}
        self._colors: dict[str, str] = {}
        self._vals: dict[str, int] = {}
        self._keys: list[str] = []
        self._drag = -1
        self.setMinimumHeight(self.BAR_H + 20)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        if parts:
            self.set_parts(parts)

    # ── части ─────────────────────────────────────────────────────────────
    def set_parts(self, parts) -> None:
        """Заменяет набор частей. Проценты уже известных сохраняются, новым
        место выделяется поровну из общего котла."""
        keys = []
        for i, part in enumerate(parts):
            key, label = part[0], part[1]
            color = part[2] if len(part) > 2 else self.PALETTE[i % len(self.PALETTE)]
            keys.append(key)
            self._labels[key] = label
            self._colors[key] = color
        if keys == self._keys:
            return
        # Новой части даём ровную долю, а не ноль: иначе добавленный третьим
        # список так и остался бы с 0%, пока его не подвинут руками.
        fair = 100 // max(1, len(keys))
        vals = {k: (self._vals[k] if k in self._vals else fair) for k in keys}
        if not any(vals.values()):
            vals = {k: fair for k in keys}
        self._keys = keys
        self._normalise(vals)
        self.update()

    def keys(self) -> list[str]:
        return list(self._keys)

    def values(self) -> dict:
        """{ключ: процент} по видимым частям (скрытые — ноль)."""
        return {k: (self._vals.get(k, 0) if k in self._keys else 0)
                for k in self._vals}

    def value_of(self, key: str) -> int:
        return int(self._vals.get(key, 0)) if key in self._keys else 0

    def set_values(self, vals: dict) -> None:
        raw = {k: max(0, int(vals.get(k, 0) or 0)) for k in self._keys}
        self._normalise(raw)
        self.update()

    def _normalise(self, vals: dict) -> None:
        """Приводит доли видимых частей к сумме ровно 100."""
        shown = {k: max(0, int(vals.get(k, 0))) for k in self._keys}
        total = sum(shown.values())
        if total <= 0:
            shown = {k: (100 if k == self._keys[0] else 0) for k in self._keys}
        elif total != 100:
            out = {k: v * 100 // total for k, v in shown.items()}
            rest = 100 - sum(out.values())
            for k in sorted(shown, key=lambda k: -(shown[k] * 100 % total)):
                if rest <= 0:
                    break
                out[k] += 1
                rest -= 1
            shown = out
        vals = dict(self._vals)
        vals.update({k: shown.get(k, 0) for k in self._keys})
        for key in list(vals):
            if key not in self._keys and key not in self._labels:
                vals.pop(key)
        self._vals = vals
        # Легенда переехала — под неё могло понадобиться больше места.
        self._sync_height()

    # ── геометрия ─────────────────────────────────────────────────────────
    def _cuts(self) -> list[int]:
        """Границы частей в процентах (их на одну меньше, чем частей)."""
        out, acc = [], 0
        for key in self._keys[:-1]:
            acc += self._vals.get(key, 0)
            out.append(acc)
        return out

    def _apply_cuts(self, cuts: list[int]) -> None:
        prev = 0
        for i, key in enumerate(self._keys[:-1]):
            self._vals[key] = cuts[i] - prev
            prev = cuts[i]
        self._vals[self._keys[-1]] = 100 - prev

    def _bar_rect(self) -> QRect:
        return QRect(0, 0, max(1, self.width()), self.BAR_H)

    def _x_of(self, pct: int) -> int:
        return int(round(self._bar_rect().width() * pct / 100.0))

    def _pct_of(self, x: int) -> int:
        w = max(1, self._bar_rect().width())
        return max(0, min(100, int(round(x * 100.0 / w))))

    # ── мышь ──────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        cuts = self._cuts()
        if not cuts:
            return
        pct = self._pct_of(e.position().x())
        # Какую ручку двигать: ближнюю. При совпавших ручках (нулевая доля)
        # решает сторона, в которую тянут, — иначе доля не разжимается.
        near = min(range(len(cuts)), key=lambda i: (abs(pct - cuts[i]), i))
        while (near + 1 < len(cuts) and cuts[near + 1] == cuts[near]
               and pct > cuts[near]):
            near += 1
        self._drag = near
        self._move_to(pct)

    def mouseMoveEvent(self, e):
        if self._drag >= 0:
            self._move_to(self._pct_of(e.position().x()))

    def mouseReleaseEvent(self, _e):
        self._drag = -1

    def _move_to(self, pct: int) -> None:
        cuts = self._cuts()
        i = self._drag
        if not (0 <= i < len(cuts)):
            return
        new = list(cuts)
        # Соседние границы не перепрыгиваем: они лишь сдвигаются вплотную.
        new[i] = max(0, min(100, pct))
        for j in range(i - 1, -1, -1):
            new[j] = min(new[j], new[j + 1])
        for j in range(i + 1, len(new)):
            new[j] = max(new[j], new[j - 1])
        if new != cuts:
            self._apply_cuts(new)
            self.update()
            self.changed.emit()

    # ── рисование ─────────────────────────────────────────────────────────
    def paintEvent(self, _e):
        if not self._keys:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = self._bar_rect()
        cuts = self._cuts()
        x = 0
        for i, key in enumerate(self._keys):
            right = bar.width() if i == len(self._keys) - 1 else self._x_of(cuts[i])
            w = right - x
            if w > 0:
                p.fillRect(QRect(x, bar.y(), w, bar.height()),
                           QColor(C[self._colors.get(key, "accent")]))
            x = max(x, right)
        p.setPen(QColor(C["border"]))
        p.drawRect(bar.adjusted(0, 0, -1, -1))
        for cut in cuts:
            hx = self._x_of(cut)
            p.fillRect(QRect(hx - self.HANDLE_W // 2, bar.y() - 1,
                             self.HANDLE_W, bar.height() + 2),
                       QColor(C["text"]))
        # Легенда сплошной строкой с переносом: частей может быть и восемь,
        # подписи «слева — по центру — справа» на них уже не разложить.
        p.setPen(QColor(C["text2"]))
        p.setFont(self._legend_font())
        p.drawText(QRect(0, bar.bottom() + 2, bar.width(),
                         max(18, self.height() - bar.bottom() - 2)),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
                   self._legend_text())

    # ── легенда ───────────────────────────────────────────────────────────
    def _legend_text(self) -> str:
        return "  ·  ".join(f"{self._labels.get(k, k)} {self._vals.get(k, 0)}%"
                            for k in self._keys)

    def _legend_font(self):
        font = self.font(); font.setPointSize(8)
        return font

    def _sync_height(self) -> None:
        """Подгоняет высоту под легенду: восемь частей в одну строку не влезают,
        и хвост («Анаграммы 15% · Сюжет 15%») просто пропадал за краем."""
        from PyQt6.QtGui import QFontMetrics
        width = max(1, self.width())
        fm = QFontMetrics(self._legend_font())
        need = fm.boundingRect(
            QRect(0, 0, width, 1000),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
            self._legend_text()).height()
        height = self.BAR_H + 4 + max(14, need)
        if height != self.minimumHeight():
            self.setMinimumHeight(height)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_height()


class _MixSlider(_ShareBar):
    """Состав пака: песни / ролики / кадры / персонажи / манга / пиксели /
    анаграммы / сюжет.

    Доли всего, кроме песен, кадров и персонажей, появляются только со своими
    галочками («Вопрос — ролик», «— манга», «— пиксели», «— анаграмма», «— по
    сюжету»): снятая галочка убирает часть из полосы совсем, а её проценты
    возвращаются песням."""

    KEYS = ("songs", "video", "frames", "chars", "manga", "pixel", "anagram",
            "plot")
    # Первые пять — «историческая» пятёрка percents(): её ждут и сохранённые
    # настройки, и PackSettings.percents.
    LEGACY = KEYS[:5]
    LABELS = {"songs": "Песни", "video": "Ролики", "frames": "Кадры",
              "chars": "Персонажи", "manga": "Манга", "pixel": "Пиксели",
              "anagram": "Анаграммы", "plot": "Сюжет"}
    COLORS = {"songs": "accent", "video": "accent2", "frames": "green",
              "chars": "yellow", "manga": "red", "pixel": "text2",
              "anagram": "accent2", "plot": "green"}
    # Части, которые появляются на полосе только по своей галочке.
    OPTIONAL = ("video", "manga", "pixel", "anagram", "plot")

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._vals = {k: (100 if k == "songs" else 0) for k in self.KEYS}
        self._on = {k: False for k in self.OPTIONAL}
        self._parts()

    def _parts(self) -> None:
        self._keys = [k for k in self.KEYS
                      if k not in self.OPTIONAL or self._on.get(k)]
        self._labels = dict(self.LABELS)
        self._colors = dict(self.COLORS)

    # ── значение ──────────────────────────────────────────────────────────
    def shares(self) -> dict:
        """{ключ: проценты} по ВСЕМ родам вопросов. Скрытая часть — всегда 0."""
        return {k: (self._vals.get(k, 0) if k in self._keys else 0)
                for k in self.KEYS}

    def percents(self) -> tuple[int, int, int, int, int]:
        """(песни, ролики, кадры, персонажи, манга) — первые пять частей.

        Сумма равна сотне, только пока выключены пиксели, анаграммы и сюжет:
        они берут свою долю из той же сотни. Весь состав — в shares()."""
        vals = self.shares()
        return tuple(vals[k] for k in self.LEGACY)

    def set_shares(self, vals: dict) -> None:
        """Ставит доли всех родов сразу; чего нет в словаре — то ноль."""
        raw = {k: max(0, int(vals.get(k, 0) or 0)) for k in self.KEYS}
        # Выключенные части отдают свою долю песням: иначе полоса показывала бы
        # сумму меньше сотни.
        for key in self.OPTIONAL:
            if key not in self._keys:
                raw["songs"] += raw[key]
                raw[key] = 0
        self._normalise(raw)
        self.update()

    def set_percents(self, songs: int, video: int, frames: int,
                     chars: int, manga: int = 0) -> None:
        """Историческая пятёрка. Доли пикселей, анаграмм и сюжета остаются
        прежними — их этот вызов не касается."""
        vals = self.shares()
        vals.update({"songs": songs, "video": video, "frames": frames,
                     "chars": chars, "manga": manga})
        self.set_shares(vals)

    def _set_part(self, key: str, enabled: bool) -> None:
        """Общий переключатель необязательной части полосы."""
        if bool(enabled) == (key in self._keys):
            return
        vals = dict(self._vals)
        self._on[key] = bool(enabled)
        self._parts()
        if enabled:
            # Новой части нужно место: берём его у песен, они же её и отдали.
            share = min(vals["songs"], max(0, vals[key]) or vals["songs"] // 2)
            vals["songs"] -= share
            vals[key] = share
        else:
            vals["songs"] += vals[key]
            vals[key] = 0
        self._normalise(vals)
        self.update()

    def set_video(self, enabled: bool) -> None:
        """Включает/выключает часть «Ролики» в полосе."""
        self._set_part("video", enabled)

    def set_manga(self, enabled: bool) -> None:
        """Включает/выключает часть «Манга» в полосе."""
        self._set_part("manga", enabled)

    def set_pixel(self, enabled: bool) -> None:
        """Включает/выключает часть «Пиксели» (кадр-проявление) в полосе."""
        self._set_part("pixel", enabled)

    def set_anagram(self, enabled: bool) -> None:
        """Включает/выключает часть «Анаграммы» в полосе."""
        self._set_part("anagram", enabled)

    def set_plot(self, enabled: bool) -> None:
        """Включает/выключает часть «Сюжет» в полосе."""
        self._set_part("plot", enabled)


# ─────────────────────────────────────────────────────────────────────────────
# Фоновые задачи
# ─────────────────────────────────────────────────────────────────────────────
class _GenSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)      # PackResult
    failed = pyqtSignal(str)


class _GenTask(QRunnable):
    """Генерация пака целиком: списки → песни → медиа → .siq."""

    def __init__(self, settings: "PackSettings"):
        super().__init__()
        self.setAutoDelete(False)
        self.settings = settings
        self.signals = _GenSignals()
        self._stop = False
        self._gen = None

    def stop(self):
        self._stop = True
        # Флага мало: самые долгие шаги — это запущенные ffmpeg (обрезка песни и
        # кодирование картинок). Пока их не убить, «Стоп» выглядит залипшим.
        gen = self._gen
        if gen is not None:
            try:
                gen.stop_processes()
            except Exception:
                pass

    def run(self):
        gen = None
        try:
            gen = self._gen = AnimePackGenerator(
                self.settings,
                log=self.signals.log.emit,
                progress=lambda d, t, m: self.signals.progress.emit(d, t, m),
                should_stop=lambda: self._stop)
            self.signals.finished.emit(gen.run())
        except AnimePackError as e:
            self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            self._gen = None
            if gen is not None:
                try:
                    gen.cleanup()
                except Exception:
                    pass


class _RefreshDbSignals(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(int)         # сколько карточек оказалось в кэше
    failed = pyqtSignal(str)


class _RefreshDbTask(QRunnable):
    """Кнопка «Обновить базу Shikimori»: забыть кэш каталога и собрать заново.

    Работа та же, что делает первая генерация, только вынесенная отдельно —
    чтобы потом паки собирались без похода за каталогом и узнаваемостью
    франшиз."""

    def __init__(self, settings: "PackSettings"):
        super().__init__()
        self.setAutoDelete(False)
        self.settings = settings
        self.signals = _RefreshDbSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            gen = AnimePackGenerator(self.settings,
                                     log=self.signals.log.emit,
                                     should_stop=lambda: self._stop)
            self.signals.finished.emit(gen.refresh_db())
        except AnimePackError as e:
            self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(f"{type(e).__name__}: {e}")


class _GenresSignals(QObject):
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)


class _GenresTask(QRunnable):
    """Список жанров/тем Shikimori для окна выбора (грузится в фоне)."""

    def __init__(self):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _GenresSignals()
        self._stop = False

    def stop(self):
        """Отменяет задачу: прервать запрос нельзя, но результат не понадобится.

        Ответ уже неактуален — вкладку закрывают, — а сигнал полетел бы в
        виджет, который сносят прямо сейчас."""
        self._stop = True

    def run(self):
        if self._stop:
            return
        try:
            genres = ShikimoriApi().genres()
        except Exception as e:  # noqa: BLE001
            if not self._stop:
                self.signals.failed.emit(str(e))
            return
        if not self._stop:
            self.signals.finished.emit(genres)


class _NumItem(QTableWidgetItem):
    """Ячейка с числом: показывает текст, а сортируется по значению.

    Без этого клик по «Цене» или «Индексу» сортировал бы строки как строки —
    «10» оказывалось бы раньше «2», а «1 200» раньше «800»."""

    def __init__(self, text: str, value: float):
        super().__init__(text)
        try:
            self._value = float(value)
        except (TypeError, ValueError):
            self._value = 0.0

    def __lt__(self, other):
        if isinstance(other, _NumItem):
            return self._value < other._value
        return super().__lt__(other)


# ─────────────────────────────────────────────────────────────────────────────
# Карточка одного пользователя (ник + источник + статусы списков)
# ─────────────────────────────────────────────────────────────────────────────
class _UserCard(QFrame):
    removed = pyqtSignal(object)
    changed = pyqtSignal()
    # Ник дописан (Enter или уход фокуса) — момент, когда его можно запомнить в
    # адресную книгу. По каждому нажатию клавиши этого делать нельзя: в книгу
    # попали бы «m», «m4», «m46…».
    committed = pyqtSignal(object)

    # Высота строки внутри карточки: ник, источник и статусы одинаково низкие.
    ROW_H = 22

    def __init__(self, data: "UserList", parent=None):
        super().__init__(parent)
        self.setObjectName("userCard")
        # Карточка нарочно тесная: ник, источник и статусы — три коротких
        # элемента, а прежние отступы съедали в панели настроек по полсотни
        # пикселей на каждый список.
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 3, 4, 3)
        v.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.ed_name = QLineEdit(data.username)
        self.ed_name.setPlaceholderText("Ник")
        # Ширину ника больше ничем не режем: всё, что осталось от источника и
        # крестика, достаётся ему. Раньше тут стоял потолок в 96 px, и «Лекс
        # Ливень» показывался как «с Ливень» (просьба пользователя).
        self.ed_name.setMinimumWidth(90)
        self.ed_name.textChanged.connect(lambda *_: self.changed.emit())
        self.ed_name.editingFinished.connect(lambda: self.committed.emit(self))
        self.cb_source = QComboBox()
        for src in LIST_SOURCES:
            self.cb_source.addItem(SOURCE_SHORT.get(src, SOURCE_LABELS[src]), src)
        idx = self.cb_source.findData(data.source)
        if idx >= 0:
            self.cb_source.setCurrentIndex(idx)
        self.cb_source.setToolTip("С какого сайта брать список: "
                                  + ", ".join(SOURCE_LABELS[s] for s in LIST_SOURCES))
        self.cb_source.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        # Ключевое: без Maximum по горизонтали QComboBox растягивается на всё
        # свободное место карточки — «Shikimori» занимал две трети её ширины, а
        # нику оставались крохи.
        self.cb_source.setSizePolicy(QSizePolicy.Policy.Maximum,
                                     QSizePolicy.Policy.Fixed)
        self.cb_source.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.cb_source.currentIndexChanged.connect(
            lambda *_: self.committed.emit(self))
        self.btn_del = QToolButton()
        self.btn_del.setIcon(get_icon('fa5s.times'))
        self.btn_del.setToolTip("Убрать этот список")
        self.btn_del.clicked.connect(lambda: self.removed.emit(self))
        top.addWidget(self.ed_name, 1)
        top.addWidget(self.cb_source)
        top.addWidget(self.btn_del)
        v.addLayout(top)

        # Статусы — выпадающее меню с галочками: пять отдельных чекбоксов в
        # узкую панель настроек не влезают.
        self.btn_status = QToolButton()
        self.btn_status.setObjectName("statusBtn")
        self.btn_status.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_status.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        # Во всю ширину карточки: у кнопки-с-меню стрелка рисуется у правого
        # края, и на кнопке по размеру текста она наезжала на сам текст.
        self.btn_status.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Fixed)
        menu = QMenu(self.btn_status)
        self._actions = {}
        for st in LIST_STATUSES:
            act = menu.addAction(STATUS_LABELS[st])
            act.setCheckable(True)
            act.setChecked(st in data.statuses)
            act.toggled.connect(self._on_status_toggled)
            self._actions[st] = act
        self.btn_status.setMenu(menu)

        # Раздел списка (аниме/манга) и пометка «в основном музыка» — кнопками
        # рядом со статусами, чтобы карточка осталась в две строки.
        self.btn_target = QToolButton()
        self.btn_target.setCheckable(True)
        self.btn_target.setChecked(
            str(getattr(data, "target", "anime")) == "manga")
        self.btn_target.setToolTip(
            "Какой раздел списка брать: аниме или мангу/манхву/ранобэ. У всех "
            "трёх сайтов это отдельные списки.\n"
            "Манга идёт в свою долю ползунка состава — песен и кадров у книги "
            "нет, вопросом служит портрет персонажа либо обложка.")
        self.btn_target.toggled.connect(self._on_target_toggled)
        self.btn_music = QToolButton()
        self.btn_music.setObjectName("musicBtn")
        self.btn_music.setCheckable(True)
        self.btn_music.setText("♪")
        self.btn_music.setChecked(bool(getattr(data, "prefer_music", False)))
        self.btn_music.toggled.connect(lambda *_: self.changed.emit())
        self.btn_music.toggled.connect(self._refresh_music_tip)
        self._refresh_music_tip(self.btn_music.isChecked())
        row2 = QHBoxLayout(); row2.setSpacing(4)
        row2.addWidget(self.btn_status, 1)
        row2.addWidget(self.btn_target)
        row2.addWidget(self.btn_music)
        v.addLayout(row2)

        # Высоты фиксируем: без этого поля растут от общих отступов вкладки
        # (padding: 5px 7px у полей и 6px 12px у кнопок) и карточка выходит
        # вдвое выше нужного.
        for w in (self.ed_name, self.cb_source, self.btn_del, self.btn_status,
                  self.btn_target, self.btn_music):
            w.setFixedHeight(self.ROW_H)
        self._on_target_toggled(self.btn_target.isChecked())
        self._share = int(getattr(data, "share", 0) or 0)
        self._refresh_status_text()

    # ── доля списка в паке (её двигает общий ползунок «Доли списков») ─────
    def share(self) -> int:
        return int(self._share)

    def set_share(self, pct: int) -> None:
        self._share = max(0, min(100, int(pct or 0)))

    def _refresh_music_tip(self, on: bool):
        """Подсказка «♪» говорит, включена ли пометка ПРЯМО СЕЙЧАС.

        Нажатое состояние теперь и видно (кнопка заливается акцентом — см.
        _apply_styles): раньше включённая и выключенная выглядели одинаково, и
        понять, помечен ли список, было нельзя вовсе."""
        state = "ВКЛЮЧЕНО" if on else "выключено"
        self.btn_music.setToolTip(
            f"«В основном музыка» — {state}. Нажмите, чтобы переключить.\n"
            "Тайтлы из этого списка по возможности идут в песенные вопросы, а "
            "не в кадры и персонажей.\n"
            "Для списков, где человек угадывает музыку, но сам тайтл в лицо не "
            "узнаёт.")

    def _on_status_toggled(self, *_):
        self._refresh_status_text()
        self.changed.emit()

    def _on_target_toggled(self, manga: bool):
        self.btn_target.setText(TARGET_LABELS["manga" if manga else "anime"])
        self.changed.emit()
        # Раздел входит в ключ списка на полосе долей — значит, это смена
        # «личности» карточки, как ник или источник.
        self.committed.emit(self)

    def target(self) -> str:
        return "manga" if self.btn_target.isChecked() else "anime"

    def _refresh_status_text(self):
        picked = [STATUS_LABELS[s] for s in LIST_STATUSES
                  if self._actions[s].isChecked()]
        # Текст держим коротким: перечисление всех пяти статусов раздувало
        # кнопку шире панели настроек, и её правый край срезало.
        if not picked:
            text = "не выбраны"
        elif len(picked) == len(LIST_STATUSES):
            text = "все"
        elif len(picked) <= 2:
            text = ", ".join(picked)
        else:
            text = f"{len(picked)} из {len(LIST_STATUSES)}"
        self.btn_status.setText(f"Статусы: {text}")
        self.btn_status.setToolTip(
            "Какие списки пользователя брать. Без единого статуса список "
            "игнорируется.")

    def value(self) -> "UserList":
        return UserList(
            username=self.ed_name.text().strip(),
            source=self.cb_source.currentData() or "myanimelist",
            statuses=[s for s in LIST_STATUSES if self._actions[s].isChecked()],
            target=self.target(),
            share=self.share(),
            prefer_music=self.btn_music.isChecked())


# ─────────────────────────────────────────────────────────────────────────────
# Окно выбора сохранённых ников
# ─────────────────────────────────────────────────────────────────────────────
class _SavedUsersDialog(QDialog):
    """Небольшое окно со списком запомненных людей: галочками отмечаются те,
    чьи списки надо добавить в пак. Лишние ники убираются кнопкой «Забыть»."""

    def __init__(self, saved: list, parent=None, used: Optional[set] = None):
        super().__init__(parent)
        self.setWindowTitle("Сохранённые списки")
        self.setMinimumWidth(360)
        # Те, чьи списки уже добавлены, идут первыми и сразу с галочкой: окно
        # показывает текущий набор, а не пустой лист (просьба пользователя).
        used = used or set()

        def key(user):
            return (user.username.strip().casefold(), user.source)

        self._saved = sorted(saved, key=lambda u: key(u) not in used)
        self._used = used

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        lbl = QLabel("Отметьте, чьи списки добавить:")
        lbl.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        v.addWidget(lbl)

        # Поиск: ников за годы копится много, и листать их глазами — мучение.
        # Фильтр только ПРЯЧЕТ строки, галочки со скрытых не снимаются, так что
        # отметить можно нескольких по очереди, набирая разные куски ников.
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Поиск по нику…")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self._apply_filter)
        v.addWidget(self.ed_search)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        # Правой кнопкой строку можно забыть, не расставляя галочек (просьба
        # пользователя): ПКМ по нику → «Забыть».
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._row_menu)
        for user in self._saved:
            item = QListWidgetItem(
                f"{user.username} — {SOURCE_LABELS.get(user.source, user.source)}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            here = (user.username.strip().casefold(), user.source) in self._used
            item.setCheckState(Qt.CheckState.Checked if here
                               else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        v.addWidget(self.list, 1)
        self.lbl_empty = QLabel("Пока пусто: ники запоминаются сами, как только "
                                "вы их вписали.")
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setStyleSheet(f"color:{C['text3']}; font-size:11px;")
        self.lbl_empty.setVisible(not self._saved)
        v.addWidget(self.lbl_empty)

        row = QHBoxLayout(); row.setSpacing(6)
        self.btn_forget = QPushButton("Забыть отмеченных")
        self.btn_forget.clicked.connect(self._forget_checked)
        btn_add = QPushButton("Добавить")
        btn_add.setObjectName("b_primary")
        btn_add.clicked.connect(self.accept)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_forget)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(btn_add)
        v.addLayout(row)

    def _apply_filter(self, text: str):
        """Прячет строки, не подходящие под поиск. Ищем и по нику, и по
        названию источника — «anilist» находит всех оттуда."""
        needle = (text or "").strip().casefold()
        shown = 0
        for i in range(self.list.count()):
            item = self.list.item(i)
            hit = not needle or needle in item.text().casefold()
            item.setHidden(not hit)
            shown += int(hit)
        if not self._saved:
            return
        self.lbl_empty.setVisible(shown == 0)
        if shown == 0:
            self.lbl_empty.setText(f"По «{text}» ничего не нашлось.")

    def _checked_rows(self) -> list[int]:
        return [i for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def _forget_checked(self):
        self._forget_rows(self._checked_rows())

    def _forget_rows(self, rows) -> None:
        for i in sorted(set(rows), reverse=True):
            if 0 <= i < len(self._saved):
                self.list.takeItem(i)
                del self._saved[i]

    def _row_menu(self, pos):
        """ПКМ по строке: забыть её (или все отмеченные, если строка отмечена)."""
        item = self.list.itemAt(pos)
        if item is None:
            return
        row = self.list.row(item)
        checked = self._checked_rows()
        rows = checked if (row in checked and len(checked) > 1) else [row]
        menu = QMenu(self)
        if len(rows) > 1:
            act_del = menu.addAction(f"Забыть отмеченных ({len(rows)})")
        else:
            act_del = menu.addAction(f"Забыть «{self._saved[row].username}»")
        act_copy = menu.addAction("Скопировать ник")
        picked = menu.exec(self.list.mapToGlobal(pos))
        if picked is act_del:
            self._forget_rows(rows)
        elif picked is act_copy:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(self._saved[row].username)

    def picked(self) -> list:
        return [self._saved[i] for i in self._checked_rows()]

    def remaining(self) -> list:
        """Что осталось в адресной книге после кнопки «Забыть»."""
        return list(self._saved)


# ─────────────────────────────────────────────────────────────────────────────
# Вкладка
# ─────────────────────────────────────────────────────────────────────────────
class AnimePackTab(QWidget):
    """Генератор аниме-паков для «Своей игры» (порт ASPG)."""

    def __init__(self, main_window=None, settings: Optional[dict] = None):
        super().__init__()
        self.main = main_window
        self._pool = QThreadPool.globalInstance()
        self._task = None
        self._genres_task = None
        self._genres_timer = None          # отложенная загрузка списка жанров
        self._db_task = None               # обновление базы Shikimori
        self._genres_items: list = []      # (id, подпись, группа) для окна выбора
        self._sel_genres: list = []
        self._excl_genres: list = []
        self._pending_genres: list = []
        self._pending_excl: list = []
        self._user_cards: list = []
        self._saved_users: list = []       # адресная книга ников
        self._exclude_siq: list = []       # паки, чьи франшизы не повторяем
        self._out_dir = ""
        self._last_pack = ""
        self._started_at = 0.0             # для оценки времени на прогресс-баре
        self._closing = False              # после cleanup() новых задач не заводим
        self._initial = dict(settings or {})

        if not _HAS_CORE:
            self._build_unavailable()
            return
        self._build_ui()
        if self._initial:
            try:
                self.apply_settings(self._initial)
            except Exception:
                pass
        self._recount()
        self._update_table_hint()
        # Жанры нужны только при открытии окна выбора — тянем их с задержкой,
        # чтобы не толкаться с остальным стартом приложения. Таймер именно свой,
        # а не QTimer.singleShot: статический уходит жить сам по себе, и его уже
        # ничем не отменить — cleanup() закрывал вкладку, а через полторы секунды
        # всё равно уходил сетевой запрос.
        self._genres_timer = QTimer(self)
        self._genres_timer.setSingleShot(True)
        self._genres_timer.timeout.connect(self._load_genres_async)
        self._genres_timer.start(1500)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_unavailable(self):
        lay = QVBoxLayout(self)
        lbl = QLabel("Не удалось загрузить вкладку «Генерация аниме-пака».\n\n"
                     f"{_IMPORT_ERROR}")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
        lay.addStretch(); lay.addWidget(lbl); lay.addStretch()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        body = QHBoxLayout(); body.setSpacing(12)
        root.addLayout(body, 1)

        # ── Слева: состав пака, лог, прогресс ─────────────────────────────
        left = QVBoxLayout(); left.setSpacing(6)
        self.table = QTableWidget(0, len(self.TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(list(self.TABLE_HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(False)
        # Клик по заголовку сортирует таблицу; «№» возвращает порядок пака.
        self.table.setSortingEnabled(True)
        hh = self.table.horizontalHeader()
        # Родная стрелка сортировки ВЫКЛЮЧЕНА нарочно: место под неё Qt
        # резервирует в каждой секции (замерено — ровно 28 px на колонку), из-за
        # чего «Раунд», «Цена» и «Ур.» были вчетверо шире своих цифр. Стрелку
        # рисуем сами — стрелочкой в подписи сортируемой колонки.
        hh.setSortIndicatorShown(False)
        hh.sortIndicatorChanged.connect(self._on_sort_changed)
        hh.setSectionsClickable(True)
        # Ширина колонки — по её содержимому: длинные названия аниме не режутся,
        # а короткие «Ур.» и «Цена» не занимают полтаблицы. Растягивать колонки
        # на всю ширину (Stretch) больше не нужно — пусть будут по значениям.
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setStretchLastSection(False)
        # Узкие колонки не должны раздуваться из-за заголовка: у «Раунда» и
        # «Цены» содержимое — одна-две цифры, а секция выходила вчетверо шире
        # (просьба пользователя). Стрелку сортировки рисуем маленькой и поверх
        # текста — место под неё Qt резервирует в КАЖДОЙ секции.
        hh.setMinimumSectionSize(24)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        # Таблица занимает всю высоту вкладки: строки состояния над ней больше
        # нет — «Готово за столько-то» пишется прямо на общей полосе прогресса
        # (просьба пользователя), а освободившееся место отдано таблице.
        # Пока таблица пустая (пак ещё не сгенерирован), вместо неё показываем
        # предупреждение про запрет выкладывать сгенерированное в сеть.
        left.addWidget(self.table, 1)
        # Предупреждение рисуется НАКЛАДКОЙ прямо на таблицу (родитель — сама
        # таблица, а не общий layout): скрывать/показывать саму QTableWidget
        # здесь нельзя — hide()/show() на ней плодит крэши в тестах на этой
        # связке PyQt6/Qt. Накладка перекрывает пустую таблицу целиком, пока
        # пак не собран, а прячется — сама, table остаётся видимой всегда.
        self.lbl_table_hint = QLabel(
            "Сгенерированные паки/вопросы запрещено выкладывать в сеть.",
            self.table)
        self.lbl_table_hint.setWordWrap(True)
        self.lbl_table_hint.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_table_hint.setStyleSheet(
            f"background:{C['bg']}; color:{C['text2']}; font-size:13px; "
            "padding: 0 12px;")
        self.lbl_table_hint.setGeometry(self.table.rect())

        # Ни своей консоли, ни своего прогресс-бара у вкладки нет: и то, и
        # другое идёт в общую полосу внизу окна, как у остальных вкладок.
        body.addLayout(left, 1)

        self._build_settings_panel(body)
        self._apply_styles()
        # Стили меняют размеры полей — ширину панели считаем уже по ним.
        self._fit_settings_width()
        self._on_song_kinds_toggled()

    # Подписи колонок таблицы состава пака. «Ур.» — сложность тайтла, «Перс.» —
    # своя сложность вопроса-персонажа (тайтл + «в избранном» на Shikimori); у
    # остальных вопросов она пустая.
    TABLE_HEADERS = ("№", "Раунд", "Тема", "Цена", "Аниме", "Песня", "Тип",
                     "Сложн.", "Индекс", "Ур.", "Перс.")
    # Колонки с числами — их выравниваем по центру.
    TABLE_NUM_COLS = (0, 1, 2, 3, 7, 8, 9, 10)

    def _update_table_hint(self):
        """Показывает предупреждение НАКЛАДКОЙ на таблицу, пока пак ещё не
        собран (строк нет), и прячет её, как только строки появились. Саму
        таблицу видимость не трогает — только накладку поверх неё."""
        hint = getattr(self, "lbl_table_hint", None)
        if hint is None:
            return
        hint.setGeometry(self.table.rect())
        hint.setVisible(self.table.rowCount() == 0)

    def _on_sort_changed(self, section: int, order):
        """Своя стрелка сортировки — в подписи колонки (родную мы выключили,
        чтобы она не резервировала место во всех секциях сразу)."""
        arrow = "↑" if order == Qt.SortOrder.AscendingOrder else "↓"
        for col, name in enumerate(self.TABLE_HEADERS):
            item = self.table.horizontalHeaderItem(col)
            if item is not None:
                item.setText(f"{name} {arrow}" if col == section else name)

    def _lab(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        l.setWordWrap(True)
        return l

    def _hint(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{C['text3']}; font-size:11px;")
        l.setWordWrap(True)
        return l

    # ── Ключи внешних API (единое место — Настройки программы) ────────────
    def _api_key(self, name: str) -> str:
        fn = getattr(getattr(self, "main", None), "get_api_key", None)
        if fn is None:
            return ""
        try:
            return str(fn(name) or "").strip()
        except Exception:
            return ""

    def _migrate_api_key(self, name: str, old_value):
        """Ключ, сохранённый ещё в настройках самой вкладки, один раз
        переезжает в общие настройки программы (Настройки → «Ключи API»)."""
        val = str(old_value or "").strip()
        setter = getattr(getattr(self, "main", None), "set_api_key", None)
        if val and setter is not None and not self._api_key(name):
            try:
                setter(name, val)
            except Exception:
                pass
        self._refresh_api_key_buttons()

    def _open_api_settings(self):
        fn = getattr(getattr(self, "main", None), "_open_settings_dialog", None)
        if fn is not None:
            try:
                fn()
            except Exception:
                pass
        self._refresh_api_key_buttons()

    def _api_key_button(self, name: str, title: str) -> QPushButton:
        """Вместо поля ввода — кнопка «задан / не задан», открывающая Настройки:
        один и тот же ключ нужен нескольким вкладкам, и место у него одно."""
        btn = QPushButton()
        btn.setToolTip(f"{title} — открыть Настройки программы, раздел «Ключи API»")
        btn.clicked.connect(self._open_api_settings)
        if not hasattr(self, "_api_key_buttons"):
            self._api_key_buttons = []
        self._api_key_buttons.append((btn, name, title))
        self._refresh_api_key_buttons()
        return btn

    def _refresh_api_key_buttons(self):
        for btn, name, title in getattr(self, "_api_key_buttons", []):
            has = bool(self._api_key(name))
            btn.setText("задан" if has else "не задан — ввести")

    def _build_settings_panel(self, body):
        # Правая колонка = прокручиваемые настройки + НЕподвижная полоса кнопок
        # под ними. Кнопки лежат вне QScrollArea нарочно: прокрутка настроек не
        # должна их уносить (просьба пользователя).
        self.right_col = QWidget()
        col = QVBoxLayout(self.right_col)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        self.scroll_settings = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # Горизонтальная полоса — на самый крайний случай (окно уже, чем панель
        # вообще может сжаться). Раньше она была выключена наглухо, и правый
        # край настроек просто срезало.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(2, 2, 8, 2)
        pv.setSpacing(12)

        pv.addWidget(self._group_pack())
        pv.addWidget(self._group_lists())
        pv.addWidget(self._group_songs())
        pv.addWidget(self._group_anime())
        pv.addWidget(self._group_other())

        self.btn_reset = QPushButton("Сбросить настройки")
        self.btn_reset.setIcon(get_icon('fa5s.undo'))
        self.btn_reset.clicked.connect(self.reset_settings)
        pv.addWidget(self.btn_reset)
        pv.addStretch(1)

        scroll.setWidget(panel)
        self._disable_wheel(panel)
        col.addWidget(scroll, 1)
        col.addWidget(self._build_actions())
        body.addWidget(self.right_col)
        self._fit_settings_width()

    def _build_actions(self) -> QWidget:
        """Полоса запуска под настройками: «Сгенерировать пак», «Стоп»,
        «Открыть папку» и строчка про автора идеи."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self.btn_start = QPushButton("Сгенерировать пак")
        self.btn_start.setIcon(get_icon('fa5s.magic', color='#11111b'))
        self.btn_start.setIconSize(QSize(16, 16))
        self.btn_start.setObjectName("b_primary")
        self.btn_start.clicked.connect(self.start)
        self.btn_stop = QPushButton("Стоп")
        self.btn_stop.setIcon(get_icon('fa5s.stop'))
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("Остановить генерацию (скачанное будет удалено)")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_open = QPushButton("Открыть папку")
        self.btn_open.setIcon(get_icon('fa5s.folder-open'))
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_result)
        v.addWidget(self.btn_start)
        row = QHBoxLayout(); row.setSpacing(6)
        row.addWidget(self.btn_stop, 1)
        row.addWidget(self.btn_open, 1)
        v.addLayout(row)

        # Ссылка на автора идеи. Открывается в браузере
        # (setOpenExternalLinks), кликабельно только само слово «Leleath».
        self.lbl_credit = QLabel(
            'Идея взята у уважаемого <a href="https://github.com/Leleath/aspg"'
            f' style="color:{C["accent"]}; text-decoration:none;">Leleath</a>')
        self.lbl_credit.setOpenExternalLinks(True)
        self.lbl_credit.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        self.lbl_credit.setToolTip("https://github.com/Leleath/aspg")
        self.lbl_credit.setStyleSheet(f"color:{C['text3']}; font-size:11px;")
        v.addWidget(self.lbl_credit, 0, Qt.AlignmentFlag.AlignHCenter)
        return box

    @staticmethod
    def _disable_wheel(root) -> None:
        """Колесо мыши не должно менять значения счётчиков и списков — оно
        прокручивает панель (просьба пользователя)."""
        for cls in (QSpinBox, QDoubleSpinBox, QComboBox):
            for widget in root.findChildren(cls):
                _no_wheel(widget)

    # Уже этого панель настроек не сжимается: дальше подписи начинают резаться.
    SETTINGS_MIN_W = 300
    # Столько ширины оставляем таблице состава пака, пока есть из чего.
    TABLE_MIN_W = 260

    def _fit_settings_width(self):
        """Ширина панели настроек — ровно та, что нужна её содержимому, но не
        больше, чем позволяет окно.

        Ширина считалась ОДИН раз при сборке и намертво фиксировалась, причём
        ДО _apply_styles(): стили добавляют полям отступы (padding: 5px 7px),
        поля становятся шире посчитанного, и правый край панели срезало. Теперь
        ширина пересчитывается после стилей и на каждом изменении размера, а
        если окно совсем узкое — включается горизонтальная полоса, и до правого
        края всё равно можно добраться."""
        scroll = getattr(self, "scroll_settings", None)
        panel = scroll.widget() if scroll is not None else None
        if panel is None:
            return
        need = max(panel.sizeHint().width(), panel.minimumSizeHint().width(),
                   self.SETTINGS_MIN_W)
        # Панель не даём сжимать ниже её собственной ширины: тогда в совсем
        # узком окне появляется горизонтальная полоса и до правого края всё
        # равно можно доехать, вместо того чтобы поля молча резались.
        if panel.minimumWidth() != need:
            panel.setMinimumWidth(need)
        sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
        want = need + sb + 2 * scroll.frameWidth() + 4
        avail = self.width() - 24 - self.TABLE_MIN_W    # поля root-раскладки
        if avail > 0:
            want = min(want, max(self.SETTINGS_MIN_W, avail))
        # Ширину задаём всей правой колонке (настройки + полоса кнопок), чтобы
        # кнопки были ровно под настройками и не растягивали колонку сами.
        col = getattr(self, "right_col", None) or scroll
        if want != col.width() or col.maximumWidth() != want:
            col.setFixedWidth(want)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_settings_width()
        self._update_table_hint()

    def showEvent(self, event):
        super().showEvent(event)
        # Первый показ — единственный момент, когда размеры полей уже настоящие
        # (стили применены, шрифты подобраны).
        self._fit_settings_width()
        self._update_table_hint()

    # ── группа «Пак» ──────────────────────────────────────────────────────
    def _group_pack(self) -> QGroupBox:
        grp = QGroupBox("Пак")
        g = QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        self.ed_title = QLineEdit("Сгенерировано в SI-HYX")
        self.ed_theme = QLineEdit("SI-HYX")
        self.sp_rounds = QSpinBox(); self.sp_rounds.setRange(1, 20); self.sp_rounds.setValue(3)
        self.sp_themes = QSpinBox(); self.sp_themes.setRange(1, 20); self.sp_themes.setValue(5)
        self.sp_quest = QSpinBox(); self.sp_quest.setRange(1, 20); self.sp_quest.setValue(6)
        for sp in (self.sp_rounds, self.sp_themes, self.sp_quest):
            sp.setMinimumWidth(44)
            sp.valueChanged.connect(self._recount)
        r = 0
        g.addWidget(self._lab("Название"), r, 0); g.addWidget(self.ed_title, r, 1, 1, 3)
        r += 1
        g.addWidget(self._lab("Раунды"), r, 0); g.addWidget(self.sp_rounds, r, 1)
        g.addWidget(self._lab("Темы"), r, 2); g.addWidget(self.sp_themes, r, 3)
        r += 1
        g.addWidget(self._lab("Вопросов в теме"), r, 0)
        g.addWidget(self.sp_quest, r, 1, 1, 3)
        r += 1
        g.addWidget(self._lab("Название тем"), r, 0); g.addWidget(self.ed_theme, r, 1, 1, 3)
        r += 1
        self.lbl_total = self._hint("")
        g.addWidget(self.lbl_total, r, 0, 1, 4)
        for col in (1, 3):
            g.setColumnStretch(col, 1)
        return grp

    # ── группа «Списки» ───────────────────────────────────────────────────
    def _group_lists(self) -> QGroupBox:
        grp = QGroupBox("Списки")
        v = QVBoxLayout(grp); v.setSpacing(6)
        self.chk_random = QCheckBox("Случайные из базы AMQ")
        self.chk_random.setToolTip(
            "Аниме берутся из мастер-листа AnimeMusicQuiz. Он знает только те "
            "тайтлы, у которых есть песни в AMQ, поэтому годится лишь песенным "
            "пакам: без песен база всё равно берётся с Shikimori.")
        self.chk_random.toggled.connect(self._on_random_toggled)
        v.addWidget(self.chk_random)
        # База по умолчанию. С ней фильтры (год, тип, оценка) уходят прямо на
        # сервер Shikimori, поэтому кандидаты приезжают уже подходящие, а не
        # отсеиваются на нашей стороне, как с 16-мегабайтным листом AMQ.
        self.chk_random_shiki = QCheckBox("Случайные из базы Shikimori")
        self.chk_random_shiki.setChecked(True)
        self.chk_random_shiki.setToolTip(
            "Аниме берутся случайной выборкой из каталога Shikimori "
            "(order: random), а не из базы AnimeMusicQuiz. Год, тип, оценка и "
            "исключённые жанры при этом фильтруются самим Shikimori — мусора "
            "приезжает меньше, а для паков из кадров и персонажей это вообще "
            "единственный источник, где база не ограничена песнями AMQ.")
        self.chk_random_shiki.toggled.connect(self._on_random_shiki_toggled)
        v.addWidget(self.chk_random_shiki)
        # Каталог Shikimori кэшируется на диск и живёт там, пока его не обновят
        # этой кнопкой (просьба пользователя: «один раз собрал — и хранится»).
        self.btn_refresh_db = QPushButton("Обновить базу Shikimori")
        self.btn_refresh_db.setIcon(get_icon('fa5s.sync'))
        self.btn_refresh_db.setToolTip(
            "Каталог Shikimori (карточки тайтлов и узнаваемость франшиз) "
            "сохраняется рядом с настройками и переживает перезапуск программы: "
            "следующая генерация не тратит на него ни одного запроса.\n"
            "Эта кнопка забывает сохранённое и собирает базу заново — под "
            "текущие фильтры (год, типы, оценка, исключённые жанры). Каталог "
            "берётся ЦЕЛИКОМ, сколько бы тайтлов в нём под эти фильтры ни было, "
            "поэтому идти может долго — минуты и десятки минут.\n"
            "Пока идёт сбор, эта же кнопка останавливает его: всё, что успело "
            "приехать, остаётся в кэше и годится для паков. Следующее нажатие "
            "снова забывает сохранённое и начинает каталог сначала.")
        self.btn_refresh_db.clicked.connect(self._refresh_db)
        v.addWidget(self.btn_refresh_db)
        # Общая база + списки людей разом: тайтлы случайные, но чей-то ник в
        # ответе появляется, если тайтл нашёлся в его списке.
        self.chk_mark_owners = QCheckBox("Отмечать, у кого из списков есть")
        self.chk_mark_owners.setToolTip(
            "Аниме берутся из общей базы, но КОГДА ВОПРОСЫ УЖЕ ОТОБРАНЫ, "
            "программа проверяет списки добавленных ниже людей: если выпавший "
            "тайтл есть у кого-то из них, его ник пишется в реплике ведущего в "
            "ответе.\n"
            "Отбор тайтлов от этого не меняется — списки только подписывают "
            "готовое.")
        self.chk_mark_owners.toggled.connect(self._on_mark_owners_toggled)
        v.addWidget(self.chk_mark_owners)
        v.addWidget(self._hint("Снимите обе галочки — и аниме возьмутся из "
                               "списков людей на MyAnimeList / Shikimori / "
                               "AniList."))

        self.box_users = QWidget()
        uv = QVBoxLayout(self.box_users)
        uv.setContentsMargins(0, 0, 0, 0); uv.setSpacing(6)
        # Строка «Аниме есть хотя бы у N чел.» живёт в своём контейнере: в
        # режиме «общая база + отметки» списки видны, а совпадение не при чём.
        self.box_similar = QWidget()
        sim_row = QHBoxLayout(self.box_similar); sim_row.setSpacing(6)
        sim_row.setContentsMargins(0, 0, 0, 0)
        # Отдельной галочки «Похожие» больше нет: сняты обе общие базы — значит
        # пак и так собирается по спискам, других вариантов не остаётся.
        lab_sim = self._lab("Аниме есть хотя бы у")
        self.sp_similar = QSpinBox(); self.sp_similar.setRange(1, 20)
        self.sp_similar.setValue(2); self.sp_similar.setMinimumWidth(44)
        self.sp_similar.setToolTip(
            "«1» — годится всё, что есть хотя бы у одного человека; «2» и "
            "больше — только тайтлы, которые есть у стольких сразу.")
        sim_row.addWidget(lab_sim, 1)
        sim_row.addWidget(self.sp_similar)
        sim_row.addWidget(self._lab("чел."))
        uv.addWidget(self.box_similar)
        self.box_cards = QWidget()
        self.cards_layout = QVBoxLayout(self.box_cards)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(6)
        uv.addWidget(self.box_cards)

        # Доли списков: сколько вопросов пака даёт каждый человек. Без них пак
        # заполнял тот, у кого список длиннее (просьба пользователя).
        self.box_shares = QWidget()
        sh = QVBoxLayout(self.box_shares)
        sh.setContentsMargins(0, 0, 0, 0); sh.setSpacing(2)
        self.chk_shares = QCheckBox("Делить пак между списками")
        self.chk_shares.setToolTip(
            "Включено — каждый список даёт свою долю вопросов, как на полосе "
            "ниже. У кого 1500 тайтлов, а у кого 300 — неважно: доли считаются "
            "по проценту, а не по длине списка.\n"
            "Выключено — все списки просто складываются, и длинный список "
            "перевешивает остальные.")
        self.chk_shares.toggled.connect(self._on_shares_toggled)
        sh.addWidget(self.chk_shares)
        self.share_bar = _ShareBar()
        self.share_bar.setToolTip("Доля вопросов пака у каждого списка.")
        self.share_bar.changed.connect(self._on_share_bar_changed)
        sh.addWidget(self.share_bar)
        uv.addWidget(self.box_shares)
        self.box_shares.setVisible(False)

        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        self.btn_add_user = QPushButton("Добавить список")
        self.btn_add_user.setIcon(get_icon('fa5s.plus'))
        self.btn_add_user.clicked.connect(lambda: self._add_user_card())
        self.btn_saved_users = QPushButton("Из сохранённых")
        self.btn_saved_users.setIcon(get_icon('fa5s.address-book'))
        self.btn_saved_users.setToolTip(
            "Ники, которые уже участвовали в генерации, запоминаются. Здесь их "
            "можно выбрать галочками и добавить сразу пачкой.")
        self.btn_saved_users.clicked.connect(self._open_saved_users)
        self.btn_clear_users = QPushButton("Очистить")
        self.btn_clear_users.setIcon(get_icon('fa5s.trash'))
        self.btn_clear_users.setToolTip(
            "Убрать все списки разом. Сами ники останутся в сохранённых.")
        self.btn_clear_users.clicked.connect(self._clear_user_cards)
        btn_row.addWidget(self.btn_add_user, 1)
        btn_row.addWidget(self.btn_saved_users)
        btn_row.addWidget(self.btn_clear_users)
        uv.addLayout(btn_row)
        v.addWidget(self.box_users)
        self.box_users.setVisible(False)
        return grp

    # ── доли списков ──────────────────────────────────────────────────────
    def _on_shares_toggled(self, checked: bool):
        self.share_bar.setVisible(bool(checked))
        if not checked:
            for card in self._user_cards:
                card.set_share(0)
        else:
            self._refresh_share_bar()
            # Включили дележ — раздаём поровну, дальше двигайте руками.
            keys = self.share_bar.keys()
            if keys:
                self.share_bar.set_values({k: 1 for k in keys})
                self._on_share_bar_changed()
        self._fit_settings_width()

    def _on_share_bar_changed(self):
        """Полосу подвинули — разложили проценты обратно по карточкам."""
        for card in self._user_cards:
            card.set_share(self.share_bar.value_of(self._card_key(card)))

    @staticmethod
    def _share_key(user) -> str:
        """Ключ списка на полосе долей: ник + источник + раздел (у одного
        человека могут быть и аниме-список, и манга-список)."""
        return f"{user.username.strip().casefold()}|{user.source}|{user.target}"

    def _card_key(self, card) -> str:
        return self._share_key(card.value())

    def _refresh_share_bar(self):
        """Пересобирает полосу под текущий набор карточек.

        Хозяин долей — сама полоса: она их и раздаёт карточкам. Обратно, из
        карточек, значения не читаем — иначе доля только что добавленного
        списка (ноль) тут же затирала бы честный дележ из set_parts."""
        bar = getattr(self, "share_bar", None)
        if bar is None:
            return
        parts, seen = [], set()
        for card in self._user_cards:
            key = self._card_key(card)
            if not card.value().username.strip() or key in seen:
                continue
            seen.add(key)
            parts.append((key, card.value().username.strip()))
        random_mode = (self.chk_random.isChecked()
                       or self.chk_random_shiki.isChecked())
        self.box_shares.setVisible(len(parts) > 1 and not random_mode)
        if not parts:
            return
        bar.set_parts(parts)
        self._on_share_bar_changed()
        self.share_bar.setVisible(self.chk_shares.isChecked())

    # ── кнопка «Обновить базу Shikimori» ──────────────────────────────────
    def _refresh_db(self):
        # Та же кнопка работает и на остановку: каталог теперь берётся целиком,
        # а это долго — бросить на середине можно в любой момент, набранное всё
        # равно сохранится (просьба пользователя).
        if self._db_task is not None:
            self._db_task.stop()
            self.btn_refresh_db.setEnabled(False)
            self.btn_refresh_db.setText("Останавливаю…")
            self.log("Останавливаю обновление базы — набранное сохранится.")
            return
        if self._task is not None:
            return
        task = _RefreshDbTask(self.collect())
        task.signals.log.connect(self.log)
        task.signals.finished.connect(self._on_db_refreshed)
        task.signals.failed.connect(self._on_db_failed)
        self._db_task = task
        self.btn_refresh_db.setIcon(get_icon('fa5s.stop'))
        self.btn_refresh_db.setText("Остановить обновление базы")
        self.log("Обновляю базу Shikimori: каталог берётся целиком, это долго. "
                 "Той же кнопкой можно остановить — набранное сохранится.")
        self._pool.start(task)

    def _on_db_refreshed(self, count: int):
        self._finish_db_ui()
        msgbox_information(self, "База обновлена",
                           f"В кэше {count} карточек Shikimori. Следующие паки "
                           "соберутся быстрее: за каталогом ходить больше не "
                           "придётся.")

    def _on_db_failed(self, err: str):
        self._finish_db_ui()
        self.log(f"База Shikimori не обновилась: {err}")
        msgbox_critical(self, "База не обновилась", err)

    def _finish_db_ui(self):
        self._db_task = None
        self.btn_refresh_db.setEnabled(True)
        self.btn_refresh_db.setIcon(get_icon('fa5s.sync'))
        self.btn_refresh_db.setText("Обновить базу Shikimori")

    def _on_random_toggled(self, checked: bool):
        if checked and self.chk_random_shiki.isChecked():
            # Две общие базы разом не бывает — включаем последнюю выбранную.
            self.chk_random_shiki.blockSignals(True)
            self.chk_random_shiki.setChecked(False)
            self.chk_random_shiki.blockSignals(False)
        self._refresh_lists_visibility()

    def _on_random_shiki_toggled(self, checked: bool):
        if checked and self.chk_random.isChecked():
            self.chk_random.blockSignals(True)
            self.chk_random.setChecked(False)
            self.chk_random.blockSignals(False)
        self._refresh_lists_visibility()

    def _on_mark_owners_toggled(self, _checked: bool):
        """Отметки берутся из тех же карточек списков — значит их надо показать
        даже в режиме общей базы."""
        self._refresh_lists_visibility()

    def _refresh_lists_visibility(self):
        """Карточки людей нужны, когда пак собирается по чьим-то спискам — а
        также когда включены отметки «у кого из списков есть» (тогда списки не
        отбирают тайтлы, а лишь подписывают готовые вопросы)."""
        random_mode = (self.chk_random.isChecked()
                       or self.chk_random_shiki.isChecked())
        marking = random_mode and self.chk_mark_owners.isChecked()
        self.box_users.setVisible(not random_mode or marking)
        # Совпадение и доли — про отбор по спискам; при отметках их нет.
        self.box_similar.setVisible(not random_mode)
        self.box_shares.setVisible(not random_mode
                                   and len(self.share_bar.keys()) > 1)
        self.chk_mark_owners.setVisible(random_mode)
        self.btn_refresh_db.setVisible(self.chk_random_shiki.isChecked())
        self._refresh_amq_available()
        self._fit_settings_width()

    def _refresh_amq_available(self):
        """Мастер-лист AMQ — это перечень тайтлов с песнями, поэтому без песен
        он бесполезен. Не выбираем базу молча за пользователя: галочка гаснет и
        сама объясняет, почему."""
        pcts = self.mix.percents() if getattr(self, "mix", None) else (0, 0, 0, 0)
        songs = bool(pcts[0] or pcts[1])
        songs = songs and any(c.isChecked() for c in
                              (self.chk_op, self.chk_ed, self.chk_in))
        self.chk_random.setEnabled(songs)
        if not songs and self.chk_random.isChecked():
            self.chk_random.blockSignals(True)
            self.chk_random.setChecked(False)
            self.chk_random.blockSignals(False)
            self.chk_random_shiki.blockSignals(True)
            self.chk_random_shiki.setChecked(True)
            self.chk_random_shiki.blockSignals(False)
        if songs:
            self.chk_random.setToolTip(
                "Аниме берутся из мастер-листа AnimeMusicQuiz. Он знает только "
                "те тайтлы, у которых есть песни в AMQ, поэтому годится лишь "
                "песенным пакам: без песен база всё равно берётся с Shikimori.")
        else:
            self.chk_random.setToolTip(
                "Песен в этом паке нет, а мастер-лист AMQ — это перечень "
                "тайтлов С ПЕСНЯМИ и больше ничего. Для кадров и персонажей "
                "база берётся с Shikimori.")

    def _add_user_card(self, data: Optional["UserList"] = None):
        card = _UserCard(data or UserList(), self.box_cards)
        card.removed.connect(self._remove_user_card)
        # Ник уходит в адресную книгу сразу, как только дописан, — не дожидаясь
        # запуска генерации: «в сохранённых должно числиться всё, что я вообще
        # добавлял».
        card.committed.connect(lambda c: self._remember_users([c.value()]))
        card.committed.connect(lambda *_: self._refresh_share_bar())
        card.changed.connect(self._on_card_changed)
        self._disable_wheel(card)
        self.cards_layout.addWidget(card)
        self._user_cards.append(card)
        self._refresh_share_bar()
        self._fit_settings_width()
        return card

    def _on_card_changed(self):
        """Карточку правили — подсказка состава могла устареть.

        Полосу долей отсюда НЕ трогаем: этот сигнал приходит на каждую букву
        ника, и доли перетасовывались бы прямо во время набора. Её пересобирает
        committed — когда ник дописан, а источник или раздел переключён."""
        self._recount()

    def _remove_user_card(self, card):
        try:
            self._user_cards.remove(card)
        except ValueError:
            pass
        card.setParent(None)
        card.deleteLater()
        self._refresh_share_bar()
        self._fit_settings_width()

    def _clear_user_cards(self):
        # Сначала в книгу, потом с глаз долой: кнопка «Очистить» убирает списки
        # из пака, а не забывает ники (для этого есть «Забыть отмеченных»).
        self._remember_users([c.value() for c in self._user_cards])
        for card in list(self._user_cards):
            self._remove_user_card(card)

    # ── адресная книга ников ──────────────────────────────────────────────
    @staticmethod
    def _user_key(user) -> tuple:
        return (user.username.strip().casefold(), user.source)

    def _remember_users(self, users) -> None:
        """Пополняет адресную книгу: любой ник, который вы вписали, потом
        добавляется одной кнопкой, а не набирается заново.

        Статусы тут не требуются нарочно: раньше ник запоминался только при
        запуске генерации и только со статусами, из-за чего «всё, что я вообще
        добавлял» в книге не оказывалось."""
        known = {self._user_key(u) for u in self._saved_users}
        for user in users:
            if not user.username.strip():
                continue
            key = self._user_key(user)
            if key in known:
                continue
            known.add(key)
            self._saved_users.append(UserList(username=user.username.strip(),
                                              source=user.source,
                                              statuses=list(user.statuses)))

    def _open_saved_users(self):
        # В книгу заодно попадает всё, что набрано прямо сейчас: иначе окно
        # открылось бы без только что вписанного ника.
        self._remember_users([c.value() for c in self._user_cards])
        have = {self._user_key(c.value()) for c in self._user_cards}
        dlg = _SavedUsersDialog(self._saved_users, self, used=have)
        ok = dlg.exec()
        # «Забыть» действует независимо от того, чем закрыли окно.
        self._saved_users = dlg.remaining()
        if not ok:
            return
        # Галочки — это и есть итоговый набор списков: снятая убирает карточку,
        # поставленная добавляет.
        picked = {self._user_key(u): u for u in dlg.picked()}
        for card in list(self._user_cards):
            if self._user_key(card.value()) not in picked:
                self._remove_user_card(card)
        have = {self._user_key(c.value()) for c in self._user_cards}
        for key, user in picked.items():
            if key in have:
                continue
            self._add_user_card(UserList(username=user.username,
                                         source=user.source,
                                         statuses=list(user.statuses),
                                         target=getattr(user, "target", "anime"),
                                         share=int(getattr(user, "share", 0) or 0),
                                         prefer_music=bool(
                                             getattr(user, "prefer_music", False))))

    # ── группа «Состав пака» ──────────────────────────────────────────────
    def _group_songs(self) -> QGroupBox:
        grp = QGroupBox("Состав пака")
        g = QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        # Ползунок вместо прежних галочек «только кадры» / «только персонажи» /
        # «ещё и кадры по N на песню»: одной полосой видно и что в паке есть, и
        # в какой пропорции.
        self.mix = _MixSlider()
        self.mix.setToolTip(
            "Из чего собирать пак: доли вопросов-песен, роликов, кадров, "
            "персонажей и манги. Утащите границу до края — и вопросов такого "
            "рода не будет вовсе (100% кадров — это прежний режим «только "
            "кадры»).\n"
            "Доля роликов появляется в полосе только с галочкой «Вопрос — "
            "ролик».\n"
            "Манга (а также манхва, манхуа и ранобэ) берётся из списков, "
            "переключённых на «Манга/ранобэ», либо из каталога Shikimori; "
            "спрашивается портретом персонажа или обложкой.\n"
            "Как только в паке появляется картинка, цены считаются по индексу "
            "популярности: у кадра нет сложности угадывания из AMQ, а две "
            "шкалы цен в одном паке несравнимы.")
        self.mix.changed.connect(self._on_mix_changed)
        # Что и в каком количестве получится — первой строкой группы, чтобы это
        # было видно сразу, не листая до конца (просьба пользователя).
        self.lbl_left = self._hint("")
        self.lbl_left.setWordWrap(True)
        # Соотношение типов песен — такой же полосой, как состав пака: раньше
        # это были три счётчика «сколько штук», и их приходилось складывать до
        # числа вопросов вручную (просьба пользователя).
        self.kind_bar = _ShareBar()
        self.kind_bar.setToolTip(
            "В какой пропорции делить песенные вопросы между опенингами, "
            "эндингами и OST. Снятая галочка убирает тип из полосы совсем.")
        self.kind_bar.changed.connect(lambda: self._recount())
        self.kind_bar.set_parts([("opening", "Опенинги"), ("ending", "Эндинги"),
                                 ("insert", "OST")])
        # Дефолт тот же, что был у счётчиков: 54 опенинга, 20 эндингов, 16 OST.
        self.kind_bar.set_values({"opening": 54, "ending": 20, "insert": 16})
        # Галочка у каждого типа: снятая — типа в паке нет вовсе.
        self.chk_op = QCheckBox("Опенинги")
        self.chk_ed = QCheckBox("Эндинги")
        self.chk_in = QCheckBox("OST")
        for chk in (self.chk_op, self.chk_ed, self.chk_in):
            chk.setChecked(True)
            chk.setToolTip("Брать песни этого типа. Снимите — в паке их не "
                           "будет совсем.")
            chk.toggled.connect(self._on_song_kinds_toggled)
        self.sp_diff_min = QSpinBox(); self.sp_diff_min.setRange(0, 100)
        self.sp_diff_max = QSpinBox(); self.sp_diff_max.setRange(0, 100)
        self.sp_diff_max.setValue(100)
        for sp in (self.sp_diff_min, self.sp_diff_max):
            sp.setMinimumWidth(44)
        self.sp_diff_min.setToolTip("Сложность угадывания по данным AMQ: 0 — "
                                    "почти никто не угадывает, 100 — угадывают все.")
        self.sp_diff_max.setToolTip(self.sp_diff_min.toolTip())

        # Кадр всегда случайный и всегда собирается из всех источников сразу
        # (скриншоты Shikimori + превью серий AniList и Kitsu) — отдельных
        # настроек для этого больше нет, выключать их было незачем.
        self.chk_frames_new = QCheckBox("Не повторять прошлые кадры")
        self.chk_frames_new.setToolTip(
            "Программа запоминает кадры собранных паков и больше их не берёт. "
            "Если у тайтла свободных кадров не осталось, в пак пойдёт другой "
            "тайтл.\n"
            "Память общая для всех паков и живёт рядом с настройками "
            "(animepack_frames_used.json).")

        self.cb_char_roles = QComboBox()
        for role in CHAR_ROLES:
            self.cb_char_roles.addItem(CHAR_ROLE_LABELS[role], role)
        self.cb_char_roles.setCurrentIndex(self.cb_char_roles.findData("both"))
        self.cb_char_roles.setToolTip(
            "Кого спрашивать в вопросах-персонажах: главных героев (их узнают "
            "почти все), второстепенных (сильно сложнее) или и тех, и других.\n"
            "Портрет берётся с Shikimori, ответ пишется как «Название аниме "
            "(2020) — 『Имя персонажа』» и засчитывает ВСЕ имена персонажа, в "
            "том числе «Прочие» с его страницы.\n"
            "Цена — как за сам тайтл, умноженная на полтора за главного героя "
            "и на 1,8 за второстепенного.")

        # ── Вопрос роликом (AnimeThemes) ─────────────────────────────────
        # Галочка живёт в составе пака: она включает в ползунке долю роликов,
        # а не превращает в видео все песни разом.
        self.chk_video = QCheckBox("Опенинги с видео")
        self.chk_video.setToolTip(
            "Добавляет в ползунок состава долю вопросов-РОЛИКОВ: вместо "
            "отрезка песни играет ВИДЕО опенинга или эндинга с "
            "animethemes.moe. Ролики там без кредитов — то есть без названия "
            "прямо в кадре, что для угадайки и нужно.\n"
            "Ключей и регистрации не требуется. Если ролика для этой песни нет "
            "(OST там не лежат вовсе), вопрос всё равно состоится — просто "
            "обычным отрезком звука.\n"
            "Ответ у ролика точно такой же, как у песни: название с тегом, "
            "год, песня, исполнитель и постер.\n"
            "Ролик перекодируется в 720p тем же libsvtav1, что и во вкладке "
            "«Обработка», звук — в opus, как все дорожки пака.")
        self.chk_video.toggled.connect(self._on_video_toggled)
        self.sp_video_cut = QSpinBox(); self.sp_video_cut.setRange(3, 90)
        self.sp_video_cut.setValue(VIDEO_CUT); self.sp_video_cut.setSuffix(" с")
        self.sp_video_cut.setMinimumWidth(64)
        self.sp_video_cut.setToolTip("Длина ролика в вопросе.")
        self.sp_video_crf = QSpinBox(); self.sp_video_crf.setRange(0, 63)
        self.sp_video_crf.setValue(VIDEO_CRF); self.sp_video_crf.setMinimumWidth(44)
        self.sp_video_crf.setToolTip(
            "CRF libsvtav1: меньше — качественнее и тяжелее. 45 — заметно "
            "сжато, зато пак не раздувается.")
        self.sp_video_preset = QSpinBox(); self.sp_video_preset.setRange(0, 13)
        self.sp_video_preset.setValue(VIDEO_PRESET)
        self.sp_video_preset.setMinimumWidth(44)
        self.sp_video_preset.setToolTip(
            "Пресет libsvtav1: 13 — самый быстрый, 0 — самый медленный и "
            "качественный.")
        self.box_video_opts = QWidget()
        vg = QGridLayout(self.box_video_opts)
        vg.setContentsMargins(16, 0, 0, 0)
        vg.setHorizontalSpacing(8); vg.setVerticalSpacing(6)
        vg.addWidget(self._lab("Длина ролика"), 0, 0)
        vg.addWidget(self.sp_video_cut, 0, 1)
        vg.addWidget(self._lab("CRF"), 1, 0); vg.addWidget(self.sp_video_crf, 1, 1)
        vg.addWidget(self._lab("Пресет"), 2, 0)
        vg.addWidget(self.sp_video_preset, 2, 1)
        vg.setColumnStretch(1, 1)
        self.box_video_opts.setVisible(False)

        # ── Манга/манхва/ранобэ ──────────────────────────────────────────
        # Галочка, как у роликов: без неё доли манги на ползунке нет вовсе
        # (просьба пользователя).
        self.chk_manga = QCheckBox("Манга")
        self.chk_manga.setToolTip(
            "Добавляет в ползунок состава долю вопросов по МАНГЕ (а также "
            "манхве, манхуа и ранобэ). Песен и кадров у книги нет, поэтому "
            "спрашивается она портретом персонажа либо обложкой.\n"
            "Тайтлы берутся из списков, переключённых на «Манга/ранобэ», либо "
            "из каталога Shikimori.\n"
            "Снятая галочка убирает мангу с ползунка целиком.")
        self.chk_manga.toggled.connect(self._on_manga_toggled)
        self.cb_manga_q = QComboBox()
        for key in MANGA_QUESTIONS:
            self.cb_manga_q.addItem(MANGA_QUESTION_LABELS[key], key)
        self.cb_manga_q.setToolTip(
            "Чем спрашивать мангу.\n"
            "Портрет персонажа — как у аниме-персонажей: ответ «Название (год) "
            "— 『Имя』», засчитываются все имена персонажа.\n"
            "Обложка — проще и быстрее, но на обложках обычно напечатано само "
            "название, так что угадайка выходит слабее.")
        # ── Вопрос-пиксели (кадр, который проявляется) ────────────────────
        # Тот же эффект, что у кнопки «Пикселизация» во вкладке «Монтаж»: и
        # размеры блоков, и цепочка фильтров считаются общим модулем pixelize.
        self.chk_pixel = QCheckBox("Пикселизированые кадры")
        self.chk_pixel.setToolTip(
            "Добавляет в ползунок состава долю вопросов-ПИКСЕЛЕЙ: случайный "
            "кадр аниме показывается не картинкой, а роликом — он начинается "
            "крупными «пикселями» и за несколько шагов проясняется.\n"
            "Эффект тот же самый, что у кнопки «Пикселизация» во вкладке "
            "«Монтаж» (одна и та же функция на обе вкладки), а кадр берётся "
            "там же, где у обычного вопроса-кадра, — со скриншотов Shikimori и "
            "превью серий AniList/Kitsu.\n"
            "Ролик кодируется тем же libsvtav1 и с теми же CRF и пресетом, что "
            "вопрос-ролик.")
        self.chk_pixel.toggled.connect(self._on_pixel_toggled)
        self.sp_pixel_sec = QSpinBox(); self.sp_pixel_sec.setRange(2, 60)
        self.sp_pixel_sec.setValue(PIXEL_SECONDS); self.sp_pixel_sec.setSuffix(" с")
        self.sp_pixel_sec.setMinimumWidth(64)
        self.sp_pixel_sec.setToolTip("Сколько длится проявление целиком.")
        self.sp_pixel_steps = QSpinBox(); self.sp_pixel_steps.setRange(1, 20)
        self.sp_pixel_steps.setValue(PIXEL_STEPS)
        self.sp_pixel_steps.setMinimumWidth(44)
        self.sp_pixel_steps.setToolTip(
            "На сколько ступеней делится проявление: на каждой блок мельчает, "
            "последняя — уже чёткий кадр.")
        self.sp_pixel_block = QSpinBox(); self.sp_pixel_block.setRange(4, 256)
        self.sp_pixel_block.setSingleStep(4)
        self.sp_pixel_block.setValue(PIXEL_BLOCK)
        self.sp_pixel_block.setMinimumWidth(54)
        self.sp_pixel_block.setToolTip(
            "Размер блока на первой ступени: чем больше, тем неразборчивее "
            "начало.")
        self.sp_pixel_fps = QSpinBox(); self.sp_pixel_fps.setRange(1, 60)
        self.sp_pixel_fps.setValue(PIXEL_FPS); self.sp_pixel_fps.setMinimumWidth(44)
        self.sp_pixel_fps.setToolTip(
            "Кадров в секунду. Картинка статична, так что больше десяти "
            "смысла не имеет — это только вес пака.")
        self.lbl_pixel_steps = self._hint("")
        self.lbl_pixel_steps.setWordWrap(True)
        for sp in (self.sp_pixel_steps, self.sp_pixel_block):
            sp.valueChanged.connect(self._refresh_pixel_hint)
        self.box_pixel = QWidget()
        pg = QGridLayout(self.box_pixel)
        pg.setContentsMargins(16, 0, 0, 0)
        pg.setHorizontalSpacing(8); pg.setVerticalSpacing(6)
        pg.addWidget(self._lab("Длительность"), 0, 0)
        pg.addWidget(self.sp_pixel_sec, 0, 1)
        pg.addWidget(self._lab("Кадров/с"), 0, 2)
        pg.addWidget(self.sp_pixel_fps, 0, 3)
        pg.addWidget(self._lab("Ступеней"), 1, 0)
        pg.addWidget(self.sp_pixel_steps, 1, 1)
        pg.addWidget(self._lab("Блок, px"), 1, 2)
        pg.addWidget(self.sp_pixel_block, 1, 3)
        pg.addWidget(self.lbl_pixel_steps, 2, 0, 1, 4)
        pg.setColumnStretch(1, 1); pg.setColumnStretch(3, 1)
        self.box_pixel.setVisible(False)
        self._refresh_pixel_hint()

        # ── Вопрос-анаграмма ──────────────────────────────────────────────
        self.chk_anagram = QCheckBox("Анаграммы")
        self.chk_anagram.setToolTip(
            "Добавляет в ползунок состава долю вопросов-АНАГРАММ: буквы "
            "названия тайтла перемешаны, ответ — само название.\n"
            "Каждое слово перемешивается САМО В СЕБЕ: буквы не переезжают из "
            "слова в слово, а форма названия сохраняется — сколько слов и "
            "какой длины было, столько и останется. Написано прописными.\n"
            "Продолжения с приписками («…: Порядковый ранг», «… 2») под "
            "анаграмму не берутся: загадывается сам тайтл.\n"
            "Ни сети, ни медиа такому вопросу не нужно: название уже есть в "
            "карточке Shikimori, поэтому анаграммы — самый быстрый и самый "
            "лёгкий по весу род вопросов.")
        self.chk_anagram.toggled.connect(self._on_anagram_toggled)
        self.cb_anagram_lang = QComboBox()
        for lang in ANAGRAM_LANGS:
            self.cb_anagram_lang.addItem(ANAGRAM_LANG_LABELS[lang], lang)
        self.cb_anagram_lang.setToolTip(
            "Какое название перемешивать. Русское — с Shikimori, английское — "
            "поле english, ромадзи — латинская запись японского названия.\n"
            "Язык строгий: на другой анаграмма НЕ подменяется. Нет у тайтла "
            "названия на выбранном языке (или оно записано чужой "
            "письменностью — в поле russian у Shikimori попадается латиница) — "
            "вопрос достаётся следующему тайтлу.\n"
            "Правильными в ответе считаются ВСЕ написания тайтла.")
        # Потолок длины названия: у ранобэ они бывают в целое предложение, и
        # перемешанные буквы такой длины не разбирает никто (просьба
        # пользователя). 0 — потолка нет вовсе.
        self.sp_anagram_max = QSpinBox()
        self.sp_anagram_max.setRange(0, 200)
        self.sp_anagram_max.setValue(ANAGRAM_MAX_CHARS)
        self.sp_anagram_max.setMinimumWidth(64)
        self.sp_anagram_max.setSpecialValueText("без предела")
        self.sp_anagram_max.setSuffix(" симв.")
        self.sp_anagram_max.setToolTip(
            "Названия длиннее этого под анаграмму не берутся: у ранобэ и "
            "новинок они бывают в целое предложение, а перемешанные буквы такой "
            "длины не разбирает никто.\n"
            "Считаются все символы названия — вместе с пробелами и знаками, "
            "ровно как их видно на экране.\n"
            "Не уложилось название на выбранном языке — вопрос достанется "
            "следующему тайтлу: на другой язык анаграмма не подменяется.\n"
            "«без предела» (0) снимает ограничение совсем.")
        # Время показа анаграммы — символов в секунду (просьба пользователя).
        # 0 — таймера нет вовсе.
        self.sp_anagram_cps = QDoubleSpinBox()
        self.sp_anagram_cps.setRange(0.0, ANAGRAM_CPS_MAX)
        self.sp_anagram_cps.setDecimals(1)
        self.sp_anagram_cps.setSingleStep(1.0)
        self.sp_anagram_cps.setValue(ANAGRAM_CHARS_PER_SEC)
        self.sp_anagram_cps.setMinimumWidth(96)
        self.sp_anagram_cps.setSpecialValueText("без таймера")
        self.sp_anagram_cps.setSuffix(" симв./сек")
        self.sp_anagram_cps.setToolTip(
            "Сколько времени анаграмма висит на экране: её длина делится на это "
            "число. При 10 симв./сек анаграмма из 30 символов показывается 3 "
            "секунды.\n"
            "Без этой настройки время берёт сам SIGame — из «скорости чтения» в "
            "настройках ИГРОКА, а она рассчитана на чтение вопроса вслух, а не "
            "на разгадывание, и текст улетает вдвое быстрее.\n"
            f"Меньше {ANAGRAM_MIN_SECONDS} с не бывает: короткая анаграмма "
            "иначе мелькнула бы, и прочитать её не успел бы никто.\n"
            "«без таймера» (0) — анаграмма остаётся на экране, пока ведущий не "
            "откроет ответ.")
        self.lab_anagram_cps = self._lab("Показ")
        self.box_anagram = QWidget()
        ang = QGridLayout(self.box_anagram)
        ang.setContentsMargins(16, 0, 0, 0)
        ang.setHorizontalSpacing(8); ang.setVerticalSpacing(6)
        ang.addWidget(self._lab("Язык названия"), 0, 0)
        ang.addWidget(self.cb_anagram_lang, 0, 1)
        ang.addWidget(self._lab("Не длиннее"), 0, 2)
        ang.addWidget(self.sp_anagram_max, 0, 3)
        ang.addWidget(self.lab_anagram_cps, 1, 0)
        ang.addWidget(self.sp_anagram_cps, 1, 1)
        ang.setColumnStretch(1, 1)
        self.box_anagram.setVisible(False)

        # ── Вопрос по сюжету (Fandom + Gemini) ────────────────────────────
        self.chk_plot = QCheckBox("Сюжетные вопросы")
        self.chk_plot.setToolTip(
            "Добавляет в ползунок состава долю вопросов ПО СЮЖЕТУ: программа "
            "находит вики тайтла на fandom.com, берёт со страницы случайной "
            "серии раздел с пересказом и просит Gemini сделать из него вопрос.\n"
            "Fandom работает без ключей, а вот для Gemini нужен ВАШ ключ — "
            "бесплатного тарифа хватает, но запросов в минуту там немного, и "
            "пак с большой долей сюжета собирается заметно дольше обычного.\n"
            "Вики есть не у всякого тайтла: если пересказа не нашлось, вопрос "
            "просто достанется следующему тайтлу.")
        self.chk_plot.toggled.connect(self._on_plot_toggled)
        self.cb_plot_mode = QComboBox()
        for mode in PLOT_MODES:
            self.cb_plot_mode.addItem(PLOT_MODE_LABELS[mode], mode)
        self.cb_plot_mode.setToolTip(
            "Что именно спрашивать.\n"
            "«Ответ — название аниме»: ведущий читает эпизод сюжета, игроки "
            "называют тайтл. Название и имена героев из вопроса вычищаются, "
            "иначе он решается с первого слова. Ответ и цена считаются как у "
            "любого другого вопроса пака — на слово модели тут ничего не "
            "принимается.\n"
            "«Ответ — деталь сюжета»: вопрос про сам сюжет («что герой сделал, "
            "когда…»), тайтл в вопросе назван прямо, а короткий ответ "
            "придумывает модель по пересказу. Проверяйте такие вопросы глазами "
            "перед игрой.")
        self.btn_gemini_key = self._api_key_button("gemini", "Ключ Gemini")
        self.cb_gemini_model = QComboBox()
        for model in GEMINI_MODELS:
            self.cb_gemini_model.addItem(model, model)
        self.cb_gemini_model.setCurrentText(GEMINI_DEFAULT_MODEL)
        self.cb_gemini_model.setToolTip(
            "Flash-Lite — рабочая лошадка с самой высокой бесплатной квотой. "
            "Flash думает лучше, но запросов в сутки у него вчетверо меньше.")
        self.box_plot = QWidget()
        plg = QGridLayout(self.box_plot)
        plg.setContentsMargins(16, 0, 0, 0)
        plg.setHorizontalSpacing(8); plg.setVerticalSpacing(6)
        plg.addWidget(self._lab("Спрашивать"), 0, 0)
        plg.addWidget(self.cb_plot_mode, 0, 1)
        plg.addWidget(self._lab("Ключ Gemini"), 1, 0)
        plg.addWidget(self.btn_gemini_key, 1, 1)
        plg.addWidget(self._lab("Модель"), 2, 0)
        plg.addWidget(self.cb_gemini_model, 2, 1)
        plg.setColumnStretch(1, 1)
        self.box_plot.setVisible(False)

        self.chk_manga_kinds = {}
        self.box_manga = QWidget()
        mg = QGridLayout(self.box_manga)
        mg.setContentsMargins(16, 0, 0, 0)
        mg.setHorizontalSpacing(8); mg.setVerticalSpacing(4)
        mg.addWidget(self._lab("Вопрос"), 0, 0)
        mg.addWidget(self.cb_manga_q, 0, 1, 1, 3)
        for i, kind in enumerate(MANGA_KINDS):
            chk = QCheckBox(MANGA_KIND_LABELS[kind])
            chk.setChecked(kind in ("manga", "manhwa", "manhua", "light_novel"))
            self.chk_manga_kinds[kind] = chk
            mg.addWidget(chk, 1 + i // 2, (i % 2) * 2, 1, 2)
        mg.setColumnStretch(1, 1)
        self.box_manga.setVisible(False)

        r = 0
        g.addWidget(self.lbl_left, r, 0, 1, 4)
        r += 1
        g.addWidget(self.mix, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_video, r, 0, 1, 4)
        r += 1
        g.addWidget(self.box_video_opts, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_frames_new, r, 0, 1, 4)
        r += 1
        g.addWidget(self._lab("Персонажи"), r, 0)
        g.addWidget(self.cb_char_roles, r, 1, 1, 3)
        r += 1
        g.addWidget(self.chk_manga, r, 0, 1, 4)
        r += 1
        g.addWidget(self.box_manga, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_pixel, r, 0, 1, 4)
        r += 1
        g.addWidget(self.box_pixel, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_anagram, r, 0, 1, 4)
        r += 1
        g.addWidget(self.box_anagram, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_plot, r, 0, 1, 4)
        r += 1
        g.addWidget(self.box_plot, r, 0, 1, 4)
        r += 1
        self.box_song_opts = QWidget()
        sg = QGridLayout(self.box_song_opts)
        sg.setContentsMargins(0, 0, 0, 0)
        sg.setHorizontalSpacing(8); sg.setVerticalSpacing(8)
        g.addWidget(self.box_song_opts, r, 0, 1, 4)
        g, r = sg, 0                      # дальше всё кладём в подпанель песен
        g.addWidget(self.chk_op, r, 0)
        g.addWidget(self.chk_ed, r, 1)
        g.addWidget(self.chk_in, r, 2, 1, 2)
        r += 1
        g.addWidget(self.kind_bar, r, 0, 1, 4)
        r += 1
        g.addWidget(self._lab("Сложность от"), r, 0)
        g.addWidget(self.sp_diff_min, r, 1)
        g.addWidget(self._lab("до"), r, 2); g.addWidget(self.sp_diff_max, r, 3)
        r += 1
        self.chk_rebroadcast = QCheckBox("Повторные показы")
        self.chk_rebroadcast.setChecked(True)
        self.chk_rebroadcast.setToolTip("Песни из повторных трансляций (rebroadcast).")
        self.chk_dub = QCheckBox("Дубляж (dub)")
        g.addWidget(self.chk_rebroadcast, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_dub, r, 0, 1, 4)
        r += 1
        g.addWidget(self._lab("Категории"), r, 0, 1, 4)
        r += 1
        self.chk_categories = {}
        for i, cat in enumerate(SONG_CATEGORIES):
            chk = QCheckBox(CATEGORY_LABELS[cat])
            chk.setChecked(True)
            self.chk_categories[cat] = chk
            g.addWidget(chk, r + i // 2, (i % 2) * 2, 1, 2)
        for col in (1, 3):
            g.setColumnStretch(col, 1)
        return grp

    def _on_mix_changed(self):
        """Ползунок состава сдвинули: настройки песен нужны, только если доля
        песен не нулевая."""
        self._refresh_song_opts()

    def _refresh_song_opts(self):
        """Настройки песен видны, только если песни в паке вообще будут.

        Ролику песня нужна ровно так же, как обычному вопросу (он и есть песня,
        только видео), поэтому доля роликов держит эти настройки на экране."""
        pcts = self.mix.percents()
        songs = bool(pcts[0] or pcts[1])
        self.box_song_opts.setVisible(songs)
        if getattr(self, "box_audio_opts", None) is not None:
            self.box_audio_opts.setVisible(songs)
        if getattr(self, "cb_char_roles", None) is not None:
            self.cb_char_roles.setEnabled(bool(pcts[3]))
        if getattr(self, "box_manga", None) is not None:
            # Настройки манги живут при её галочке, а не при доле: ползунок
            # можно увести в ноль и вернуть, не теряя их из виду.
            self.box_manga.setVisible(self.chk_manga.isChecked())
        self._refresh_amq_available()
        self._fit_settings_width()
        self._recount()

    def _on_song_kinds_toggled(self, *_):
        """Снятый тип песни убираем из полосы соотношения совсем."""
        parts = [(k, label) for k, label, chk in
                 (("opening", "Опенинги", self.chk_op),
                  ("ending", "Эндинги", self.chk_ed),
                  ("insert", "OST", self.chk_in)) if chk.isChecked()]
        self.kind_bar.setVisible(bool(parts))
        if parts:
            self.kind_bar.set_parts(parts)
        self._refresh_amq_available()
        self._recount()

    def _on_compress_images_toggled(self, checked: bool):
        if getattr(self, "box_img_opts", None) is not None:
            self.box_img_opts.setVisible(checked)

    # ── общая кладовая обложек ────────────────────────────────────────────
    def _on_poster_cache_toggled(self, checked: bool):
        if getattr(self, "lbl_poster_cache", None) is not None:
            self.lbl_poster_cache.setVisible(checked)
        if getattr(self, "btn_poster_clear", None) is not None:
            self.btn_poster_clear.setVisible(checked)
        if checked:
            self._refresh_poster_cache()

    def _refresh_poster_cache(self):
        """Подпись «сколько обложек лежит в кладовой»."""
        if getattr(self, "lbl_poster_cache", None) is None:
            return
        try:
            num, size = poster_cache.stats()
        except Exception:  # noqa: BLE001 — подпись не повод падать
            num, size = 0, 0
        if not num:
            self.lbl_poster_cache.setText("Кладовая пуста — обложки лягут в "
                                          "неё при первой же генерации.")
            return
        # Запятая — только в дробном числе: «шт.» с точкой (иначе выходило
        # «1 шт,, 0,0 МБ»).
        mb = f"{size / (1024.0 * 1024.0):.1f}".replace(".", ",")
        self.lbl_poster_cache.setText(
            f"В кладовой обложек: {num} шт., {mb} МБ "
            f"(потолок {POSTER_CACHE_MB} МБ)")

    def _clear_poster_cache(self):
        try:
            gone = poster_cache.clear()
        except Exception as e:  # noqa: BLE001
            msgbox_warning(self, "Обложки", f"Не вышло очистить: {e}")
            return
        self._refresh_poster_cache()
        self.log(f"Кладовая обложек очищена: удалено {gone} картинок.")

    def _on_video_toggled(self, checked: bool):
        """Галочка роликов добавляет/убирает их долю в ползунке состава."""
        if getattr(self, "box_video_opts", None) is not None:
            self.box_video_opts.setVisible(checked)
        if getattr(self, "mix", None) is not None:
            self.mix.set_video(checked)
            self._refresh_song_opts()
        self._fit_settings_width()

    def _on_manga_toggled(self, checked: bool):
        """То же для манги: без галочки её доли на ползунке нет."""
        if getattr(self, "box_manga", None) is not None:
            self.box_manga.setVisible(checked)
        if getattr(self, "mix", None) is not None:
            self.mix.set_manga(checked)
            self._refresh_song_opts()
        self._fit_settings_width()

    def _on_pixel_toggled(self, checked: bool):
        """Галочка пикселей добавляет/убирает их долю в ползунке состава."""
        if getattr(self, "box_pixel", None) is not None:
            self.box_pixel.setVisible(checked)
        if getattr(self, "mix", None) is not None:
            self.mix.set_pixel(checked)
            self._refresh_song_opts()
        self._fit_settings_width()

    def _on_anagram_toggled(self, checked: bool):
        """То же для анаграмм."""
        if getattr(self, "box_anagram", None) is not None:
            self.box_anagram.setVisible(checked)
        if getattr(self, "mix", None) is not None:
            self.mix.set_anagram(checked)
            self._refresh_song_opts()
        self._fit_settings_width()

    def _on_plot_toggled(self, checked: bool):
        """То же для вопросов по сюжету (им нужен ещё и ключ Gemini)."""
        if getattr(self, "box_plot", None) is not None:
            self.box_plot.setVisible(checked)
        if getattr(self, "mix", None) is not None:
            self.mix.set_plot(checked)
            self._refresh_song_opts()
        self._fit_settings_width()

    def _refresh_pixel_hint(self, *_):
        """Показывает, какими блоками пойдёт проявление: «64px → 35px → … →
        чётко». Считает та же функция, что и сам эффект (pixelize), поэтому
        подсказка не расходится с тем, что получится в паке."""
        lbl = getattr(self, "lbl_pixel_steps", None)
        if lbl is None:
            return
        try:
            from pixelize import block_sequence
            seq = block_sequence(self.sp_pixel_block.value(),
                                 self.sp_pixel_steps.value())
        except Exception:  # noqa: BLE001 — подсказка не обязана работать
            return
        lbl.setText("Блоки по ступеням:   "
                    + "   →   ".join(f"{b}px" if b > 1 else "чётко"
                                     for b in seq))

    # ── группа «Аниме» ────────────────────────────────────────────────────
    def _group_anime(self) -> QGroupBox:
        grp = QGroupBox("Аниме")
        g = QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        self.sp_score_from = QDoubleSpinBox(); self.sp_score_from.setRange(0, 10)
        self.sp_score_from.setSingleStep(0.5); self.sp_score_from.setDecimals(1)
        self.sp_score_to = QDoubleSpinBox(); self.sp_score_to.setRange(0, 10)
        self.sp_score_to.setSingleStep(0.5); self.sp_score_to.setDecimals(1)
        self.sp_score_to.setValue(10.0)
        from datetime import date as _date
        self.sp_year_from = QSpinBox(); self.sp_year_from.setRange(1900, 2100)
        self.sp_year_from.setValue(1944)
        self.sp_year_to = QSpinBox(); self.sp_year_to.setRange(1900, 2100)
        self.sp_year_to.setValue(_date.today().year)
        for sp in (self.sp_score_from, self.sp_score_to,
                   self.sp_year_from, self.sp_year_to):
            sp.setMinimumWidth(50)

        self.sp_level_from = QSpinBox(); self.sp_level_from.setRange(1, 10)
        self.sp_level_from.setValue(1); self.sp_level_from.setMinimumWidth(50)
        self.sp_level_to = QSpinBox(); self.sp_level_to.setRange(1, 10)
        self.sp_level_to.setValue(10); self.sp_level_to.setMinimumWidth(50)
        tip = ("Насколько узнаваемы тайтлы в паке: 1 — то, что смотрели все "
               "(«Атака титанов», «Клинок, рассекающий демонов»), 10 — то, о "
               "чём почти никто не слышал. Считается по индексу популярности "
               "Shikimori, поэтому работает и без песен — по кадрам тоже.\n"
               "Поставьте «от 2», чтобы самые заезженные тайтлы в пак не "
               "попадали.\n"
               "Часть серии наследует узнаваемость всей франшизы: «Доктор "
               "Стоун: Научное будущее. Часть 3» считается настолько же "
               "известным, как «Доктор Стоун».")
        self.sp_level_from.setToolTip(tip)
        self.sp_level_to.setToolTip(tip)
        # Средняя сложность — поверх рамок «от … до»: они говорят, что вообще
        # пускать, а это — на что должна выйти середина пака.
        self.sp_level_avg = QSpinBox(); self.sp_level_avg.setRange(0, 10)
        self.sp_level_avg.setValue(0); self.sp_level_avg.setMinimumWidth(50)
        self.sp_level_avg.setSpecialValueText("любая")
        self.sp_level_avg.setToolTip(
            "Куда должна выйти СРЕДНЯЯ сложность пака (просьба пользователя): "
            "«от 1 до 10, в среднем 4» — это пак, где крайности редки, а "
            "середина около четвёрки.\n"
            "«любая» (ноль) — не следить за средней вовсе, как было раньше.\n"
            "Пока набранная средняя выше цели, генератор берёт только тайтлы "
            "полегче, и наоборот. Если подходящих не находится, он всё же "
            "берёт что есть — иначе пак остался бы недобранным (о таком пишет "
            "в лог).")
        self.sp_level_avg.valueChanged.connect(self._recount)
        # Своя средняя для вопросов-ПЕРСОНАЖЕЙ: их сложность считается не только
        # по узнаваемости тайтла, но и по числу добавивших персонажа в избранное
        # на Shikimori (просьба пользователя).
        self.sp_char_avg = QSpinBox(); self.sp_char_avg.setRange(0, 10)
        self.sp_char_avg.setValue(0); self.sp_char_avg.setMinimumWidth(50)
        self.sp_char_avg.setSpecialValueText("любая")
        self.sp_char_avg.setToolTip(
            "Куда должна выйти средняя сложность вопросов-ПЕРСОНАЖЕЙ. Считается "
            "по двум мерам сразу: узнаваемость тайтла и «в избранном» на "
            "Shikimori — чем большему числу людей персонаж попал в избранное, "
            "тем он легче (у главных героев хитов это тысячи, у проходного "
            "второстепенного — единицы).\n"
            "«любая» (ноль) — не следить за ней вовсе.\n"
            "Известность персонажа влияет и на цену: за популярного вопрос чуть "
            "дешевеет, за редкого — дорожает.")

        r = 0
        g.addWidget(self._lab("Сложность от"), r, 0)
        g.addWidget(self.sp_level_from, r, 1)
        g.addWidget(self._lab("до"), r, 2); g.addWidget(self.sp_level_to, r, 3)
        r += 1
        g.addWidget(self._lab("В среднем"), r, 0)
        g.addWidget(self.sp_level_avg, r, 1)
        g.addWidget(self._lab("Персонажи"), r, 2)
        g.addWidget(self.sp_char_avg, r, 3)
        r += 1
        g.addWidget(self._hint("1 — знают все, 10 — не знает никто."), r, 0, 1, 4)
        r += 1
        g.addWidget(self._lab("Оценка от"), r, 0); g.addWidget(self.sp_score_from, r, 1)
        g.addWidget(self._lab("до"), r, 2); g.addWidget(self.sp_score_to, r, 3)
        r += 1
        g.addWidget(self._lab("Год с"), r, 0); g.addWidget(self.sp_year_from, r, 1)
        g.addWidget(self._lab("по"), r, 2); g.addWidget(self.sp_year_to, r, 3)
        r += 1
        g.addWidget(self._lab("Типы"), r, 0, 1, 4)
        r += 1
        self.chk_kinds = {}
        for i, kind in enumerate(ANIME_KINDS):
            chk = QCheckBox(KIND_LABELS[kind])
            chk.setChecked(True)
            self.chk_kinds[kind] = chk
            g.addWidget(chk, r + i // 2, (i % 2) * 2, 1, 2)
        r += (len(ANIME_KINDS) + 1) // 2
        self.btn_genres = QPushButton("Жанры: любые")
        self.btn_genres.setToolTip("Жанры и темы Shikimori: зелёный ✓ — только с "
                                   "ним, красный ✕ — исключить.")
        self.btn_genres.clicked.connect(self._open_genre_picker)
        g.addWidget(self.btn_genres, r, 0, 1, 4)
        r += 1
        self.chk_genres_partial = QCheckBox("Достаточно одного жанра")
        self.chk_genres_partial.setChecked(True)
        self.chk_genres_partial.setToolTip(
            "Включено — аниме подходит, если у него есть ХОТЯ БЫ один из "
            "выбранных жанров. Выключено — нужны все сразу.")
        g.addWidget(self.chk_genres_partial, r, 0, 1, 4)
        for col in (1, 3):
            g.setColumnStretch(col, 1)
        return grp

    # ── группа «Прочее» ───────────────────────────────────────────────────
    def _group_other(self) -> QGroupBox:
        grp = QGroupBox("Прочее")
        g = QGridLayout(grp); g.setHorizontalSpacing(6); g.setVerticalSpacing(8)
        # Подписи нарочно короткие: длинный текст в QCheckBox не переносится и
        # задаёт минимальную ширину всей панели. Подробности — в подсказках.
        # Галочек «Дубли аниме» и «Дубли франшиз» больше нет: и то, и другое
        # выключено навсегда (просьба пользователя). Один тайтл — один вопрос,
        # одна франшиза — один тайтл.
        self.chk_sort_index = QCheckBox("По индексу популярности")
        self.chk_sort_index.setToolTip(
            "Порядок вопросов и их цены берутся из «индекса популярности» — той "
            "же величины, по которой сортирует вкладка ShikimoriHYX (списки "
            "пользователей, взвешенные на свежесть выхода и слегка на оценку). "
            "Пак идёт от самых узнаваемых тайтлов к самым безвестным: самый "
            "узнаваемый вопрос стоит 2, самый редкий — 20.\n"
            "Выключено — цены считаются по сложности угадывания из AMQ.")
        self.chk_hint = QCheckBox("Подсказка: тип песни")
        self.chk_hint.setChecked(True)
        self.chk_hint.setToolTip(
            "Пока играет песня, на экране висит «Опенинг», «Эндинг» или «OST» — "
            "текст выводится ОДНОВРЕМЕННО с отрезком, а не после него.")
        self.sp_cut = QSpinBox(); self.sp_cut.setRange(5, 60); self.sp_cut.setValue(20)
        self.sp_cut.setSuffix(" с"); self.sp_cut.setMinimumWidth(64)
        self.chk_images = QCheckBox("Скриншоты в вопросе за")
        self.chk_images.setToolTip(
            "Коллаж 2×2 из случайных кадров аниме появляется поверх играющей "
            "песни за указанное число секунд до конца.")
        self.sp_images_time = QSpinBox(); self.sp_images_time.setRange(1, 30)
        self.sp_images_time.setValue(7); self.sp_images_time.setSuffix(" с")
        self.sp_images_time.setMinimumWidth(64)
        # Сколько висит постер в ответе. Раньше это были зашитые три секунды.
        self.sp_answer_img = QSpinBox()
        self.sp_answer_img.setRange(0, ANSWER_IMAGE_MAX)
        self.sp_answer_img.setValue(3); self.sp_answer_img.setSuffix(" с")
        self.sp_answer_img.setMinimumWidth(74)
        self.sp_answer_img.setSpecialValueText("без ограничения")
        self.sp_answer_img.setToolTip(
            "Сколько секунд показывается постер тайтла в ОТВЕТЕ на вопрос.\n"
            f"Больше {ANSWER_IMAGE_MAX} с не ставится: всё нужное с постера "
            "считывается за пару секунд, а игра тем временем стоит.\n"
            "«без ограничения» (ноль) — картинка остаётся на экране, пока "
            "ведущий не перейдёт дальше.")
        # ── Обложки: общая кладовая и запасной источник ───────────────────
        self.chk_poster_cache = QCheckBox("Хранить обложки на диске")
        self.chk_poster_cache.setChecked(True)
        self.chk_poster_cache.setToolTip(
            "Скачанные постеры складываются в общую папку рядом с настройками "
            "и в следующий раз берутся оттуда, а не качаются заново. Папка "
            "общая с вкладкой «Апгрейд пака»: обложку, скачанную там, "
            "здесь качать уже не придётся (и наоборот).\n"
            "Хранятся ИСХОДНЫЕ картинки — под лимит пака их всё равно ужимает "
            "кодировщик, так что настройки сжатия на кладовую не влияют.\n"
            f"Больше {POSTER_CACHE_MB} МБ папка не занимает: лишнее "
            "выбрасывается, начиная с самых давно не нужных обложек.")
        self.chk_poster_cache.toggled.connect(self._on_poster_cache_toggled)
        self.btn_poster_clear = QPushButton("Очистить")
        self.btn_poster_clear.setToolTip("Удалить все сохранённые обложки.")
        self.btn_poster_clear.clicked.connect(self._clear_poster_cache)
        self.lbl_poster_cache = QLabel("")
        self.btn_tmdb_key = self._api_key_button("tmdb", "Ключ TMDB")
        self.sp_parallel = QSpinBox(); self.sp_parallel.setRange(1, 16)
        self.sp_parallel.setValue(8); self.sp_parallel.setMinimumWidth(44)
        self.sp_parallel.setToolTip("Сколько вопросов качается одновременно.")
        self.sp_max_mb = QSpinBox(); self.sp_max_mb.setRange(5, 2000)
        self.sp_max_mb.setValue(MAX_PACK_MB); self.sp_max_mb.setSuffix(" МБ")
        self.sp_max_mb.setSingleStep(10); self.sp_max_mb.setMinimumWidth(78)
        self.sp_max_mb.setToolTip(
            "Потолок веса готового .siq. Программа держит его двумя способами: "
            "заранее подбирает битрейт звука (и, если совсем не лезет, лимит "
            "картинки) под число вопросов, а по ходу считает набранное и "
            "останавливается, когда бюджет исчерпан.\n"
            "Со снятыми галочками сжатия размер задаём не мы — тогда потолок "
            "держится только вторым способом, и пак может выйти короче.")
        self.chk_compress_audio = QCheckBox("Сжимать аудио")
        self.chk_compress_audio.setChecked(True)
        self.chk_compress_audio.setToolTip(
            "Включено — отрезок песни кодируется как во вкладке «Обработка»: "
            "opus 192 кбит, нормализация громкости (−20 LUFS, LRA 11, TP −1.5) "
            "и затухание за секунду до конца.\n"
            "Выключено — отрезок просто вырезается из скачанного файла без "
            "перекодирования: качество ровно то, что отдал сервер AMQ, но "
            "громкость у вопросов будет разная и пак весит больше.")
        self.chk_compress_images = QCheckBox("Сжимать картинки")
        self.chk_compress_images.setChecked(True)
        self.chk_compress_images.setToolTip(
            "Включено — постеры и кадры пережимаются в AVIF тем же кодером, что "
            "и во вкладке «Обработка», с низким приоритетом процесса (работать "
            "за компьютером не мешает).\n"
            "Выключено — картинка кладётся в пак как есть, оригиналом с "
            "Shikimori: быстро, но пак тяжелее в разы.")
        self.chk_compress_images.toggled.connect(self._on_compress_images_toggled)
        self.sp_img_kb = QSpinBox(); self.sp_img_kb.setRange(20, 2000)
        self.sp_img_kb.setValue(150); self.sp_img_kb.setSuffix(" КБ")
        self.sp_img_kb.setSingleStep(10); self.sp_img_kb.setMinimumWidth(74)
        self.sp_img_kb.setToolTip("До скольки ужимать каждую картинку.")
        self.sp_img_speed = QSpinBox(); self.sp_img_speed.setRange(0, 8)
        self.sp_img_speed.setValue(8); self.sp_img_speed.setMinimumWidth(44)
        self.sp_img_speed.setToolTip(
            "Скорость кодирования AVIF (-cpu-used): 8 — самая быстрая, 0 — "
            "самая медленная и качественная. На 8 картинка считается меньше "
            "секунды, на 5 — секунд пять.")

        r = 0
        # Всё, что про песню, живёт в одной подпанели — её прячет режим кадров.
        self.box_audio_opts = QWidget()
        ag = QGridLayout(self.box_audio_opts)
        ag.setContentsMargins(0, 0, 0, 0)
        ag.setHorizontalSpacing(8); ag.setVerticalSpacing(8)
        ag.addWidget(self._lab("Отрезок песни"), 0, 0); ag.addWidget(self.sp_cut, 0, 1, 1, 3)
        ag.addWidget(self.chk_images, 1, 0, 1, 3)
        ag.addWidget(self.sp_images_time, 1, 3)
        ag.addWidget(self.chk_hint, 2, 0, 1, 4)
        ag.addWidget(self.chk_compress_audio, 3, 0, 1, 4)
        for col in (1, 3):
            ag.setColumnStretch(col, 1)
        g.addWidget(self.box_audio_opts, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_compress_images, r, 0, 1, 4)
        r += 1
        # Настройки сжатия картинок видны, только когда оно включено.
        self.box_img_opts = QWidget()
        ig = QGridLayout(self.box_img_opts)
        ig.setContentsMargins(16, 0, 0, 0)
        ig.setHorizontalSpacing(8); ig.setVerticalSpacing(6)
        ig.addWidget(self._lab("Сжимать до"), 0, 0)
        ig.addWidget(self.sp_img_kb, 0, 1)
        ig.addWidget(self._lab("Скорость"), 1, 0)
        ig.addWidget(self.sp_img_speed, 1, 1)
        ig.setColumnStretch(1, 1)
        g.addWidget(self.box_img_opts, r, 0, 1, 4)
        r += 1
        self.chk_shuffle = QCheckBox("Вопросы в разнобой")
        self.chk_shuffle.setToolTip(
            "Включено — вопросы в теме идут случайно, а не от дешёвых к "
            "дорогим: цена по теме скачет, как в живых паках.")
        g.addWidget(self.chk_shuffle, r, 0, 1, 4)
        r += 1
        g.addWidget(self.chk_sort_index, r, 0, 1, 4)
        r += 1
        g.addWidget(self._lab("Картинка в ответе"), r, 0, 1, 2)
        g.addWidget(self.sp_answer_img, r, 2, 1, 2)
        r += 1
        g.addWidget(self.chk_poster_cache, r, 0, 1, 3)
        g.addWidget(self.btn_poster_clear, r, 3)
        r += 1
        # Подпись «сколько обложек лежит» прячется вместе с галочкой, а ключ
        # TMDB — нет: запасной источник работает и без кладовой.
        g.addWidget(self.lbl_poster_cache, r, 0, 1, 4)
        # Подпись «сколько обложек лежит» нужна и без сохранённых настроек:
        # свежая вкладка иначе показывала бы пустую строку.
        self._refresh_poster_cache()
        r += 1
        g.addWidget(self._lab("Ключ TMDB"), r, 0, 1, 2)
        g.addWidget(self.btn_tmdb_key, r, 2, 1, 2)
        r += 1
        g.addWidget(self._lab("Параллельных загрузок"), r, 0, 1, 3)
        g.addWidget(self.sp_parallel, r, 3)
        r += 1
        g.addWidget(self._lab("Пак не больше"), r, 0, 1, 2)
        g.addWidget(self.sp_max_mb, r, 2, 1, 2)
        r += 1
        # Готовые паки, чьи франшизы повторять не надо.
        excl_row = QHBoxLayout(); excl_row.setSpacing(6)
        self.btn_excl_siq = QPushButton("Не повторять из паков…")
        self.btn_excl_siq.setIcon(get_icon('fa5s.file-import'))
        self.btn_excl_siq.setToolTip(
            "Выберите готовые .siq — программа прочитает их правильные ответы и "
            "не станет спрашивать те же франшизы снова. «Наруто» из старого "
            "пака закроет и «Наруто: Ураганные хроники» в новом.\n"
            "Читается только content.xml, медиа из архива не достаётся — это "
            "доли секунды на файл.")
        self.btn_excl_siq.clicked.connect(self._choose_exclude_siq)
        self.btn_excl_clear = QPushButton("Очистить")
        self.btn_excl_clear.setToolTip("Убрать все паки из списка исключений.")
        self.btn_excl_clear.clicked.connect(self._clear_exclude_siq)
        excl_row.addWidget(self.btn_excl_siq, 1)
        excl_row.addWidget(self.btn_excl_clear)
        g.addLayout(excl_row, r, 0, 1, 4)
        r += 1
        self.lbl_excl_siq = self._hint("")
        g.addWidget(self.lbl_excl_siq, r, 0, 1, 4)
        r += 1
        self.btn_out_dir = QPushButton("Папка для пака…")
        self.btn_out_dir.setIcon(get_icon('fa5s.folder'))
        self.btn_out_dir.clicked.connect(self._choose_out_dir)
        g.addWidget(self.btn_out_dir, r, 0, 1, 4)
        r += 1
        self.lbl_out_dir = self._hint("")
        g.addWidget(self.lbl_out_dir, r, 0, 1, 4)
        for col in (1, 3):
            g.setColumnStretch(col, 1)
        self._refresh_out_dir_label()
        self._refresh_exclude_label()
        return grp

    # ── исключение франшиз по чужим пакам ─────────────────────────────────
    def _choose_exclude_siq(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Паки, франшизы из которых не повторять",
            self._out_dir or os.path.expanduser("~"),
            "Пакеты SIGame (*.siq);;Все файлы (*)")
        if not paths:
            return
        have = {os.path.normcase(p) for p in self._exclude_siq}
        for path in paths:
            if os.path.normcase(path) not in have:
                self._exclude_siq.append(path)
                have.add(os.path.normcase(path))
        self._refresh_exclude_label()

    def _clear_exclude_siq(self):
        self._exclude_siq = []
        self._refresh_exclude_label()

    def _refresh_exclude_label(self):
        n = len(self._exclude_siq)
        if not n:
            self.lbl_excl_siq.setText("Исключений нет: пак собирается без "
                                      "оглядки на другие.")
            self.btn_excl_clear.setEnabled(False)
            return
        names = ", ".join(os.path.basename(p) for p in self._exclude_siq[:3])
        if n > 3:
            names += f" и ещё {n - 3}"
        self.lbl_excl_siq.setText(f"Не повторяю франшизы из {n} пак(ов): {names}")
        self.lbl_excl_siq.setToolTip("\n".join(self._exclude_siq))
        self.btn_excl_clear.setEnabled(True)

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
            QPushButton, QToolButton {{
                background: {C['surface3']}; border: 1px solid {C['border']};
                border-radius: 5px; padding: 6px 12px; color: {C['text']};
            }}
            QPushButton:hover, QToolButton:hover {{ background: {C['surface2']}; }}
            QPushButton:disabled {{ color: {C['text3']}; }}
            QPushButton#b_primary {{
                background: {C['accent']}; color: #11111b; border: none; font-weight: 700;
            }}
            QPushButton#b_primary:hover {{ background: {C['accent2']}; }}
            QPushButton#b_primary:disabled {{
                background: {C['surface3']}; color: {C['text3']};
            }}
            QGroupBox {{
                border: 1px solid {C['border']}; border-radius: 6px;
                margin-top: 10px; padding-top: 8px; font-weight: bold;
                color: {C['accent']};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
            QFrame#userCard {{
                border: 1px solid {C['border']}; border-radius: 6px;
                background: {C['surface2']};
            }}
            /* Внутри карточки списка всё тесное: общие отступы полей и кнопок
               раздували её на треть панели настроек. */
            QFrame#userCard QLineEdit, QFrame#userCard QComboBox {{
                padding: 1px 5px; font-size: 11px;
            }}
            QFrame#userCard QToolButton {{
                padding: 1px 4px; font-size: 11px;
            }}
            /* «♪» — переключатель, и нажатое состояние должно быть ВИДНО:
               без этого правила включённая пометка «в основном музыка» выглядела
               ровно как выключенная, и понять, стоит она или нет, было нельзя. */
            QFrame#userCard QToolButton#musicBtn {{ color: {C['text3']}; }}
            QFrame#userCard QToolButton#musicBtn:checked {{
                background: {C['accent']}; border-color: {C['accent']};
                color: #11111b; font-weight: 700;
            }}
            QFrame#userCard QToolButton#musicBtn:checked:hover {{
                background: {C['accent2']};
            }}
            /* Справа оставляем место под стрелку меню. */
            QFrame#userCard QToolButton#statusBtn {{ padding: 1px 16px 1px 6px; }}
            QTableWidget {{
                background: {C['surface']}; border: 1px solid {C['border']};
                border-radius: 6px; outline: none;
            }}
            QHeaderView::section {{
                background: {C['surface2']}; color: {C['text2']};
                border: none; padding: 3px 3px; font-size: 11px;
            }}
            /* Стрелка сортировки — маленькая и без своего места: иначе Qt
               резервирует под неё ~20 px в КАЖДОЙ колонке, и «Раунд» с «Ценой»
               выходили вчетверо шире содержимого. */
            QHeaderView::up-arrow, QHeaderView::down-arrow {{
                width: 7px; height: 7px; subcontrol-position: top center;
            }}
            QTableWidget::item:selected {{ background: {C['surface3']}; color: {C['text']}; }}
            QProgressBar {{
                background: {C['surface']}; border: 1px solid {C['border']};
                border-radius: 5px; text-align: center; color: {C['text']};
            }}
            QProgressBar::chunk {{ background: {C['accent']}; border-radius: 4px; }}
        """)

    # ── мелкая логика формы ───────────────────────────────────────────────
    # В каком порядке перечислять вопросы в итоговой строке состава.
    COUNT_ORDER = (FRAME_KIND, "opening", "ending", "insert", CHAR_KIND,
                   VIDEO_KIND, MANGA_KIND, PIXEL_KIND, ANAGRAM_KIND, PLOT_KIND)
    COUNT_LABELS = {FRAME_KIND: "Кадров", "opening": "Опенингов",
                    "ending": "Эндингов", "insert": "OST",
                    CHAR_KIND: "Персонажей", VIDEO_KIND: "Видео",
                    MANGA_KIND: "Манги", PIXEL_KIND: "Пикселей",
                    ANAGRAM_KIND: "Анаграмм", PLOT_KIND: "По сюжету"}

    def _recount(self, *_):
        total = self.sp_rounds.value() * self.sp_themes.value() * self.sp_quest.value()
        self.lbl_total.setText(f"Вопросов в паке: {total}")
        if getattr(self, "cb_char_roles", None) is None:
            return                       # панель ещё строится
        settings = self.collect()
        if (settings.songs_percent
                and not any(chk.isChecked() for chk in
                            (self.chk_op, self.chk_ed, self.chk_in))):
            self.lbl_left.setText("Не выбран ни один тип песни — включите "
                                  "опенинги, эндинги или OST.")
            self.lbl_left.setStyleSheet(f"color:{C['yellow']}; font-size:11px;")
            return
        # Ровно по одной строке на всё, что будет в паке (просьба пользователя):
        # «Кадров N, Опенингов N, Эндингов N, OST N, Персонажей N, Видео N».
        # Считает те же question_quotas, что и генератор, — цифры на вкладке и
        # в паке не расходятся.
        quotas = settings.question_quotas
        parts = ", ".join(f"{self.COUNT_LABELS[k]} — {quotas.get(k, 0)}"
                          for k in self.COUNT_ORDER)
        silent = sum(quotas.get(k, 0) for k in SILENT_KINDS)
        tail = (" Цены — по индексу популярности." if silent else "")
        self.lbl_left.setText(parts + "." + tail)
        self.lbl_left.setStyleSheet(f"color:{C['green']}; font-size:11px;")

    def _refresh_out_dir_label(self):
        if self._out_dir:
            self.lbl_out_dir.setText(f"Пак сохранится в: {self._out_dir}")
        else:
            try:
                from utils import default_download_dir
                where = default_download_dir()
            except Exception:
                where = "папка загрузок"
            self.lbl_out_dir.setText(f"Пак сохранится в: {where}")

    def _choose_out_dir(self):
        start = self._out_dir or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Куда сохранять пак", start)
        if path:
            self._out_dir = path
            self._refresh_out_dir_label()

    # ── жанры ─────────────────────────────────────────────────────────────
    def _load_genres_async(self):
        if self._closing or self._genres_task is not None or self._genres_items:
            return
        task = _GenresTask()
        task.signals.finished.connect(self._on_genres_loaded)
        task.signals.failed.connect(self._on_genres_failed)
        self._genres_task = task
        self._pool.start(task)

    def _on_genres_loaded(self, genres: list):
        self._genres_task = None
        try:
            from shikimori_api import genre_group
        except Exception:
            def genre_group(_g):
                return "genre"
        items = []
        for g in genres:
            gid = g.get("id")
            if gid is None:
                continue
            items.append((int(gid), g.get("russian") or g.get("name") or str(gid),
                          genre_group(g)))
        items.sort(key=lambda x: x[1].lower())
        self._genres_items = items
        self._apply_pending_genres()

    def _apply_pending_genres(self):
        """Восстановленные из настроек id жанров применяем только после того,
        как пришёл их список — иначе нечем проверить, что такой жанр есть."""
        if not self._genres_items:
            return
        valid = {gid for gid, _, _ in self._genres_items}
        if self._pending_genres:
            self._sel_genres = [g for g in self._pending_genres if g in valid]
            self._pending_genres = []
        if self._pending_excl:
            self._excl_genres = [g for g in self._pending_excl if g in valid]
            self._pending_excl = []
        self._update_genres_btn()

    def _on_genres_failed(self, err: str):
        self._genres_task = None
        self.log(f"Список жанров не загрузился: {err}")

    def _open_genre_picker(self):
        if not self._genres_items:
            self._load_genres_async()
            msgbox_information(self, "Жанры и темы",
                               "Список жанров ещё загружается — повторите через "
                               "секунду.")
            return
        from shikimori_tab import _GenrePickerDialog
        dlg = _GenrePickerDialog(self._genres_items, self._sel_genres,
                                 self._excl_genres, self)
        if dlg.exec():
            self._sel_genres = dlg.selected_ids()
            self._excl_genres = dlg.excluded_ids()
            self._update_genres_btn()

    def _update_genres_btn(self):
        names = {gid: label for gid, label, _ in self._genres_items}
        inc = [names.get(g, str(g)) for g in self._sel_genres]
        exc = [names.get(g, str(g)) for g in self._excl_genres]
        if not inc and not exc:
            self.btn_genres.setText("Жанры: любые")
            return
        parts = []
        if inc:
            parts.append("✓ " + ", ".join(inc[:2]) + ("…" if len(inc) > 2 else ""))
        if exc:
            parts.append("✕ " + ", ".join(exc[:2]) + ("…" if len(exc) > 2 else ""))
        self.btn_genres.setText("Жанры: " + "; ".join(parts))

    # ── настройки ─────────────────────────────────────────────────────────
    def collect(self) -> "PackSettings":
        s = PackSettings()
        s.title = self.ed_title.text().strip() or "Сгенерировано в SI-HYX"
        s.rounds = self.sp_rounds.value()
        s.themes = self.sp_themes.value()
        s.questions = self.sp_quest.value()
        s.theme_title = self.ed_theme.text().strip()
        s.random_mode = (self.chk_random.isChecked()
                         or self.chk_random_shiki.isChecked())
        s.random_source = ("shikimori" if self.chk_random_shiki.isChecked()
                           else "amq")
        s.users = [c.value() for c in self._user_cards]
        # Заодно пополняем книгу: collect() зовётся и при сохранении настроек,
        # так что ник не потеряется, даже если генерацию ни разу не запускали.
        self._remember_users(s.users)
        s.saved_users = list(self._saved_users)
        s.exclude_siq = list(self._exclude_siq)
        s.similar_count = self.sp_similar.value()
        shares = self.mix.shares()
        (s.pct_songs, s.pct_videos, s.pct_frames,
         s.pct_chars, s.pct_manga) = self.mix.percents()
        s.pct_pixel = shares["pixel"]
        s.pct_anagram = shares["anagram"]
        s.pct_plot = shares["plot"]
        s.pack_pixel = self.chk_pixel.isChecked()
        s.pixel_seconds = self.sp_pixel_sec.value()
        s.pixel_fps = self.sp_pixel_fps.value()
        s.pixel_steps = self.sp_pixel_steps.value()
        s.pixel_block = self.sp_pixel_block.value()
        s.pack_anagram = self.chk_anagram.isChecked()
        s.anagram_lang = self.cb_anagram_lang.currentData() or "russian"
        s.anagram_max_chars = self.sp_anagram_max.value()
        s.anagram_cps = self.sp_anagram_cps.value()
        s.pack_plot = self.chk_plot.isChecked()
        s.plot_mode = self.cb_plot_mode.currentData() or "title"
        s.gemini_key = self._api_key("gemini")
        s.gemini_model = self.cb_gemini_model.currentText().strip()
        s.tmdb_key = self._api_key("tmdb")
        s.poster_cache = self.chk_poster_cache.isChecked()
        s.mark_owners = self.chk_mark_owners.isChecked()
        s.frames_no_repeat = self.chk_frames_new.isChecked()
        s.char_roles = self.cb_char_roles.currentData() or "both"
        s.pack_manga = self.chk_manga.isChecked()
        s.manga_question = self.cb_manga_q.currentData() or "character"
        s.manga_kinds = {k: chk.isChecked()
                         for k, chk in self.chk_manga_kinds.items()}
        s.song_video = self.chk_video.isChecked()
        s.video_cut = self.sp_video_cut.value()
        s.video_crf = self.sp_video_crf.value()
        s.video_preset = self.sp_video_preset.value()
        s.pick_openings = self.chk_op.isChecked()
        s.pick_endings = self.chk_ed.isChecked()
        s.pick_inserts = self.chk_in.isChecked()
        # Опенинги/эндинги/OST — это ДОЛИ песенных вопросов (полоса), а не
        # штуки: генератор всё равно ужимает их под число песен в паке.
        s.openings = self.kind_bar.value_of("opening")
        s.endings = self.kind_bar.value_of("ending")
        s.inserts = self.kind_bar.value_of("insert")
        s.difficulty_min = self.sp_diff_min.value()
        s.difficulty_max = self.sp_diff_max.value()
        s.categories = {c: chk.isChecked() for c, chk in self.chk_categories.items()}
        s.allow_rebroadcast = self.chk_rebroadcast.isChecked()
        s.allow_dub = self.chk_dub.isChecked()
        s.level_min = self.sp_level_from.value()
        s.level_max = self.sp_level_to.value()
        s.level_avg = self.sp_level_avg.value()
        s.char_level_avg = self.sp_char_avg.value()
        s.score_from = self.sp_score_from.value()
        s.score_to = self.sp_score_to.value()
        s.kinds = {k: chk.isChecked() for k, chk in self.chk_kinds.items()}
        s.year_from = self.sp_year_from.value()
        s.year_to = self.sp_year_to.value()
        s.genres_include = list(self._sel_genres)
        s.genres_exclude = list(self._excl_genres)
        s.genres_partial = self.chk_genres_partial.isChecked()
        # dup_anime/dup_franchise не трогаем: они выключены навсегда.
        s.sort_by_index = self.chk_sort_index.isChecked()
        s.images = self.chk_images.isChecked()
        s.images_time = self.sp_images_time.value()
        s.answer_image_time = self.sp_answer_img.value()
        s.hint = self.chk_hint.isChecked()
        s.compress_audio = self.chk_compress_audio.isChecked()
        s.compress_images = self.chk_compress_images.isChecked()
        s.image_limit_kb = self.sp_img_kb.value()
        s.image_speed = self.sp_img_speed.value()
        s.shuffle_questions = self.chk_shuffle.isChecked()
        s.audio_cut = self.sp_cut.value()
        s.parallel = self.sp_parallel.value()
        s.max_pack_mb = self.sp_max_mb.value()
        s.out_dir = self._out_dir
        return s

    def get_settings(self) -> dict:
        """Настройки вкладки для settings.json."""
        if not _HAS_CORE:
            return dict(self._initial)
        data = self.collect().to_dict()
        # Ключи API хранятся в общих настройках программы (Настройки → «Ключи
        # API»), а не здесь: иначе стёртый там ключ возвращался бы из этой
        # копии при следующем запуске.
        for k in ("gemini_key", "tmdb_key"):
            data.pop(k, None)
        return data

    def apply_settings(self, data: dict):
        if not _HAS_CORE or not isinstance(data, dict):
            return
        s = PackSettings.from_dict(data)
        self.ed_title.setText(s.title)
        self.ed_theme.setText(s.theme_title)
        self.sp_rounds.setValue(s.rounds)
        self.sp_themes.setValue(s.themes)
        self.sp_quest.setValue(s.questions)
        shiki_random = bool(s.random_mode and s.random_source == "shikimori")
        for chk, value in ((self.chk_random, s.random_mode and not shiki_random),
                           (self.chk_random_shiki, shiki_random)):
            chk.blockSignals(True)
            chk.setChecked(value)
            chk.blockSignals(False)
        self._clear_user_cards()
        for u in s.users:
            self._add_user_card(u)
        self._saved_users = list(s.saved_users)
        self._exclude_siq = list(s.exclude_siq)
        self._refresh_exclude_label()
        self.sp_similar.setValue(max(1, int(s.similar_count)))
        self.chk_mark_owners.blockSignals(True)
        self.chk_mark_owners.setChecked(bool(s.mark_owners))
        self.chk_mark_owners.blockSignals(False)
        # Галочки необязательных частей — ДО долей: они решают, есть ли в полосе
        # такие части (иначе сохранённые проценты уехали бы в песни).
        self.chk_video.setChecked(s.song_video)
        self.mix.set_video(s.song_video)
        self.chk_manga.setChecked(s.pack_manga)
        self.mix.set_manga(s.pack_manga)
        self.chk_pixel.setChecked(s.pack_pixel)
        self.mix.set_pixel(s.pack_pixel)
        self.chk_anagram.setChecked(s.pack_anagram)
        self.mix.set_anagram(s.pack_anagram)
        self.chk_plot.setChecked(s.pack_plot)
        self.mix.set_plot(s.pack_plot)
        shares = s.mix_shares
        self.mix.set_shares({
            "songs": shares.get("songs", 0), "video": shares.get(VIDEO_KIND, 0),
            "frames": shares.get(FRAME_KIND, 0),
            "chars": shares.get(CHAR_KIND, 0),
            "manga": shares.get(MANGA_KIND, 0),
            "pixel": shares.get(PIXEL_KIND, 0),
            "anagram": shares.get(ANAGRAM_KIND, 0),
            "plot": shares.get(PLOT_KIND, 0)})
        self.sp_pixel_sec.setValue(max(2, int(s.pixel_seconds or PIXEL_SECONDS)))
        self.sp_pixel_fps.setValue(max(1, min(60, int(s.pixel_fps or PIXEL_FPS))))
        self.sp_pixel_steps.setValue(max(1, min(20, int(s.pixel_steps or PIXEL_STEPS))))
        self.sp_pixel_block.setValue(max(4, min(256, int(s.pixel_block or PIXEL_BLOCK))))
        idx = self.cb_anagram_lang.findData(s.anagram_lang)
        self.cb_anagram_lang.setCurrentIndex(idx if idx >= 0 else 0)
        self.sp_anagram_max.setValue(
            max(0, min(200, int(getattr(s, "anagram_max_chars", ANAGRAM_MAX_CHARS)
                                or 0))))
        try:
            cps = float(getattr(s, "anagram_cps", ANAGRAM_CHARS_PER_SEC) or 0.0)
        except (TypeError, ValueError):
            cps = ANAGRAM_CHARS_PER_SEC
        self.sp_anagram_cps.setValue(max(0.0, min(ANAGRAM_CPS_MAX, cps)))
        idx = self.cb_plot_mode.findData(s.plot_mode)
        self.cb_plot_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self._migrate_api_key("gemini", s.gemini_key)
        if s.gemini_model:
            self.cb_gemini_model.setCurrentText(s.gemini_model)
        self._migrate_api_key("tmdb", getattr(s, "tmdb_key", ""))
        self.chk_poster_cache.setChecked(bool(getattr(s, "poster_cache", True)))
        self._on_poster_cache_toggled(self.chk_poster_cache.isChecked())
        self.chk_frames_new.setChecked(s.frames_no_repeat)
        self.sp_video_cut.setValue(max(3, int(s.video_cut)))
        self.sp_video_crf.setValue(max(0, min(63, int(s.video_crf))))
        self.sp_video_preset.setValue(max(0, min(13, int(s.video_preset))))
        idx = self.cb_char_roles.findData(s.char_roles)
        self.cb_char_roles.setCurrentIndex(idx if idx >= 0 else
                                           self.cb_char_roles.findData("both"))
        idx = self.cb_manga_q.findData(s.manga_question)
        self.cb_manga_q.setCurrentIndex(idx if idx >= 0 else 0)
        for kind, chk in self.chk_manga_kinds.items():
            chk.setChecked(bool(s.manga_kinds.get(kind, False)))
        self.chk_op.setChecked(s.pick_openings)
        self.chk_ed.setChecked(s.pick_endings)
        self.chk_in.setChecked(s.pick_inserts)
        # Галочки уже переставили набор частей полосы — теперь её значения.
        self._on_song_kinds_toggled()
        self.kind_bar.set_values({"opening": s.openings, "ending": s.endings,
                                  "insert": s.inserts})
        self.sp_diff_min.setValue(int(s.difficulty_min))
        self.sp_diff_max.setValue(int(s.difficulty_max))
        for cat, chk in self.chk_categories.items():
            chk.setChecked(bool(s.categories.get(cat, True)))
        self.chk_rebroadcast.setChecked(s.allow_rebroadcast)
        self.chk_dub.setChecked(s.allow_dub)
        self.sp_level_from.setValue(max(1, min(10, int(s.level_min))))
        self.sp_level_to.setValue(max(1, min(10, int(s.level_max))))
        self.sp_level_avg.setValue(max(0, min(10, int(s.level_avg))))
        self.sp_char_avg.setValue(max(0, min(10, int(s.char_level_avg))))
        self.sp_score_from.setValue(float(s.score_from))
        self.sp_score_to.setValue(float(s.score_to))
        for kind, chk in self.chk_kinds.items():
            chk.setChecked(bool(s.kinds.get(kind, True)))
        self.sp_year_from.setValue(int(s.year_from))
        self.sp_year_to.setValue(int(s.year_to))
        # Жанры подставим, когда придёт их список (id проверяются по нему).
        self._pending_genres = list(s.genres_include)
        self._pending_excl = list(s.genres_exclude)
        self._apply_pending_genres()
        self.chk_genres_partial.setChecked(s.genres_partial)
        self.chk_sort_index.setChecked(s.sort_by_index)
        self.chk_images.setChecked(s.images)
        self.sp_images_time.setValue(int(s.images_time))
        self.sp_answer_img.setValue(
            max(0, min(ANSWER_IMAGE_MAX, int(s.answer_image_time))))
        self.chk_hint.setChecked(s.hint)
        self.chk_compress_audio.setChecked(s.compress_audio)
        self.chk_compress_images.setChecked(s.compress_images)
        self.sp_img_kb.setValue(max(20, int(s.image_limit_kb)))
        self.sp_img_speed.setValue(max(0, min(8, int(s.image_speed))))
        self.chk_shuffle.setChecked(s.shuffle_questions)
        self.sp_cut.setValue(int(s.audio_cut))
        self.sp_parallel.setValue(int(s.parallel))
        self.sp_max_mb.setValue(max(5, int(s.max_pack_mb or MAX_PACK_MB)))
        self._out_dir = s.out_dir or ""
        self._refresh_out_dir_label()
        # Доли списков: галочка включается сама, если в настройках они заданы.
        # Значения ставим на полосу из ФАЙЛА, а не из карточек: пока карточки
        # добавлялись по одной, полоса успела раздать им свои доли.
        saved_shares = {self._share_key(u): int(u.share or 0) for u in s.users}
        self.chk_shares.blockSignals(True)
        self.chk_shares.setChecked(any(saved_shares.values()))
        self.chk_shares.blockSignals(False)
        self.share_bar.setVisible(self.chk_shares.isChecked())
        self._refresh_share_bar()
        if any(saved_shares.values()):
            self.share_bar.set_values(saved_shares)
            self._on_share_bar_changed()
        self._refresh_lists_visibility()
        self._refresh_song_opts()
        self._on_compress_images_toggled(s.compress_images)
        self._on_video_toggled(s.song_video)
        self._on_manga_toggled(s.pack_manga)
        self._on_pixel_toggled(s.pack_pixel)
        self._on_anagram_toggled(s.pack_anagram)
        self._on_plot_toggled(s.pack_plot)
        self._on_song_kinds_toggled()
        self._refresh_pixel_hint()
        self._recount()

    def reset_settings(self):
        self._sel_genres = []
        self._excl_genres = []
        # Адресную книгу сброс настроек не трогает: ники копятся годами, а
        # кнопка обещает вернуть настройки, а не стереть накопленное.
        saved = list(self._saved_users)
        self.apply_settings(PackSettings().to_dict())
        self._saved_users = saved
        self._update_genres_btn()

    # ── генерация ─────────────────────────────────────────────────────────
    def log(self, msg: str):
        """Всё пишем в общую консоль внизу окна — своей у вкладки нет."""
        if self.main is not None and hasattr(self.main, "log"):
            try:
                self.main.log(f"[Аниме-пак] {msg}")
            except Exception:
                pass

    def start(self):
        if self._task is not None:
            return
        if self._db_task is not None:
            msgbox_information(self, "Секунду",
                               "Сейчас обновляется база Shikimori — дождитесь "
                               "конца или остановите сбор той же кнопкой, иначе "
                               "пак соберётся по полупустому каталогу.")
            return
        settings = self.collect()
        problems = settings.validate()
        if problems:
            msgbox_warning(self, "Так не получится", "\n\n".join(problems))
            return
        self._remember_users(settings.users)
        self.table.setRowCount(0)
        self._update_table_hint()
        self._last_pack = ""
        self.btn_open.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._started_at = time.monotonic()
        self._progress(0, "Подготовка…")
        self.log(f"Собираю пак «{settings.title}»: {settings.total_questions} "
                 "вопросов.")

        task = _GenTask(settings)
        task.signals.log.connect(self.log)
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_finished)
        task.signals.failed.connect(self._on_failed)
        self._task = task
        self._pool.start(task)

    def stop(self):
        if self._task is not None:
            self._task.stop()
            self._progress(0, "Останавливаюсь…")
            self.btn_stop.setEnabled(False)

    def _progress(self, pct: int, text: str) -> None:
        """Своей полосы у вкладки нет — пишем в общую, внизу окна. Она же и
        строка состояния вкладки: отдельной подписи над таблицей больше нет."""
        if self.main is None or not hasattr(self.main, "update_global_progress"):
            return
        try:
            self.main.update_global_progress(max(0, min(100, int(pct))), text)
        except Exception:
            pass

    def _on_progress(self, done: int, total: int, msg: str):
        """На полосе только счётчик и оставшееся время (просьба пользователя):
        названия тайтлов мелькали слишком быстро, чтобы их прочитать, а в лог
        они и так идут."""
        total = max(1, total)
        if done <= 0:
            self._progress(0, msg or f"0/{total}")
            return
        text = f"{done}/{total}"
        eta = self._eta(done, total)
        if eta:
            text += f" — осталось {eta}"
        self._progress(int(done * 100 / total), text)

    def _eta(self, done: int, total: int) -> str:
        """Оценка остатка по средней скорости с начала генерации. Первые
        несколько вопросов не в счёт: пока качается база и разгоняется пул
        загрузок, средняя скорость врёт в разы."""
        if not self._started_at or done < 3 or done >= total:
            return ""
        spent = time.monotonic() - self._started_at
        if spent <= 0:
            return ""
        return fmt_elapsed(spent / done * (total - done))

    def _finish_ui(self):
        self._task = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _on_failed(self, err: str):
        self._finish_ui()
        self._progress(0, "Не получилось")
        self.log(f"Ошибка: {err}")
        msgbox_critical(self, "Генерация не удалась", err)

    def _on_finished(self, result):
        self._finish_ui()
        self._fill_table(result.songs)
        spent = fmt_elapsed(getattr(result, "elapsed", 0.0))
        if result.cancelled:
            self._progress(0, "Остановлено")
            self.log("Генерация остановлена, временные файлы убраны.")
            return
        self._last_pack = result.path
        self.btn_open.setEnabled(bool(result.path))
        # Итог пишем прямо на полосу вместо голого «Готово»: своей строки
        # состояния у вкладки больше нет (просьба пользователя).
        self._progress(100, f"Готово за {spent}: "
                            f"{os.path.basename(result.path)}")
        self.log(f"Пак собран за {spent}: {result.path}")
        if len(result.songs) < result.requested:
            self.log(f"Вопросов получилось {len(result.songs)} из "
                     f"{result.requested} — кандидатов не хватило.")

    def _fill_table(self, songs: list):
        settings = self.collect()
        per_round = max(1, settings.themes)
        # Пока идёт заполнение, сортировку выключаем: иначе строки едут
        # прямо под руками и ячейки попадают не в свои ряды.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        # Раскладку (темы, порядок и цены) считает сам генератор — таблица и пак
        # обязаны совпадать до вопроса.
        row = 0
        for theme_no, theme in enumerate(arrange_questions(songs, settings)):
            round_no = theme_no // per_round
            for cand in theme:
                self.table.insertRow(row)
                title_text = cand.title_ru
                if cand.is_character:
                    # Имя персонажа — часть ОТВЕТА, а не название песни: в
                    # колонке «Песня» ему было не место.
                    song_text, difficulty = "—", ""
                    if cand.char_name:
                        title_text = f"{cand.title_ru} — 『{cand.char_name}』"
                elif cand.is_silent:
                    # Кадр, пиксели, анаграмма, сюжет — песни в вопросе нет,
                    # даже если карточка песни осталась от отбора.
                    song_text, difficulty = "—", ""
                else:
                    song_text = (f"{cand.song.get('songArtist') or ''} — "
                                 f"{cand.song.get('songName') or ''}")
                    difficulty = f"{cand.difficulty:.0f}"
                kind_text = KIND_TITLES.get(cand.kind, cand.kind)
                if cand.kind == VIDEO_KIND and not cand.has_video:
                    # Ролика для этой песни не нашлось — вопрос вышел обычным.
                    kind_text = KIND_TITLES.get(cand.base_kind, kind_text)
                cells = [
                    _NumItem(str(row + 1), row + 1),
                    _NumItem(str(round_no + 1), round_no + 1),
                    _NumItem(str(theme_no % per_round + 1), theme_no % per_round + 1),
                    _NumItem(str(cand.price), cand.price),
                    QTableWidgetItem(title_text),
                    QTableWidgetItem(song_text),
                    QTableWidgetItem(kind_text),
                    _NumItem(difficulty, cand.difficulty),
                    _NumItem(f"{cand.index:,.0f}".replace(",", " "), cand.index),
                    _NumItem(str(cand.level), cand.level),
                    self._char_level_cell(cand),
                ]
                for col, item in enumerate(cells):
                    if col in self.TABLE_NUM_COLS:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row, col, item)
                row += 1
        # Заново показываем пак в его собственном порядке: сортировка «по №»
        # и есть порядок вопросов в файле.
        self.table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        # setSortingEnabled(True) сам включает родную стрелку — гасим её снова
        # (иначе колонки опять раздуются на 28 px каждая).
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self._update_table_hint()

    @staticmethod
    def _char_level_cell(cand) -> "_NumItem":
        """Ячейка «Перс.»: своя сложность вопроса-персонажа и, в скобках,
        сколько человек добавили его в избранное на Shikimori.

        Подсказку на ячейку не вешаем нарочно — системная синяя всплывашка тут
        не нужна, число и так помещается в колонку. У остальных вопросов
        персонажа нет: ячейка пустая и в сортировке идёт последней."""
        if not cand.is_character:
            return _NumItem("", 0)
        try:
            fav = int(getattr(cand, "char_favorites", -1))
        except (TypeError, ValueError):
            fav = -1
        text = f"{cand.char_level} ({fav})" if fav >= 0 else str(cand.char_level)
        return _NumItem(text, cand.char_level)

    def _open_result(self):
        if not self._last_pack:
            return
        try:
            from utils import reveal_in_explorer
            reveal_in_explorer(self._last_pack)
        except Exception as e:  # noqa: BLE001
            msgbox_critical(self, "Не открылось", str(e))

    # ── завершение работы вкладки ─────────────────────────────────────────
    @staticmethod
    def _detach(task):
        """Просит задачу остановиться и отвязывает её сигналы от вкладки.

        Дождаться QRunnable мы не можем: генерация пака идёт минутами, а
        cleanup() зовут при закрытии окна. Зато можно сделать так, чтобы поток
        доработал молча — иначе сигнал прилетает в виджет, которого уже нет."""
        if task is None:
            return
        try:
            task.stop()
        except Exception:
            pass
        for name in ("log", "progress", "finished", "failed"):
            sig = getattr(task.signals, name, None)
            if sig is None:
                continue
            try:
                sig.disconnect()
            except TypeError:
                pass               # к этому сигналу никто и не подключался

    def cleanup(self):
        self._closing = True
        # Отложенная загрузка жанров: таймер мог ещё не сработать.
        if self._genres_timer is not None:
            self._genres_timer.stop()
        self._detach(self._task)
        self._task = None
        self._detach(self._db_task)
        self._db_task = None
        self._detach(self._genres_task)
        self._genres_task = None
