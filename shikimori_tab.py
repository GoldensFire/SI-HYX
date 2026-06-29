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
import datetime
import json
import os
import re
import time
import webbrowser

from PyQt6.QtCore import (
    Qt, QObject, QRunnable, QThreadPool, pyqtSignal, QSize, QRect, QEvent, QTimer,
)
from PyQt6.QtGui import QColor, QIcon, QPixmap, QValidator, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QScrollArea, QGroupBox,
    QDialog, QCheckBox, QDialogButtonBox, QFrame, QStyledItemDelegate,
    QStyleOptionViewItem, QStyle, QApplication,
)

try:
    from config import get_icon, APP_NAME, APP_VERSION
except Exception:  # pragma: no cover
    APP_NAME, APP_VERSION = "SI-HYX", "0.0"

    def get_icon(name, color="#cdd6f4"):  # минимальная заглушка
        from PyQt6.QtGui import QIcon as _QIcon
        return _QIcon()

# Фирменный тёмный попап-подсказка (тот же, что у значков ⓘ и подсказки
# «Схлопывать франшизы» через HoverTipManager). НЕ системный QToolTip с синей
# рамкой: его и просил пользователь для подсказки индекса.
try:
    from widgets import _InfoTipPopup
except Exception:  # pragma: no cover
    _InfoTipPopup = None

# Постоянный кеш «индекса популярности»: просмотры/взвешенная база/разбивка по
# статусам тайтлов сохраняются в файл (CONFIG_DIR), чтобы не дозапрашивать
# карточки Shikimori заново при каждом запуске (по просьбе пользователя). Файл
# отдельный от settings.json — большой и обновляется часто.
try:
    from config import CONFIG_DIR
    _INDEX_CACHE_FILE = os.path.join(CONFIG_DIR, "shikimori_index_cache.json")
except Exception:  # pragma: no cover
    _INDEX_CACHE_FILE = ""
# Просмотры/база медленно растут со временем — запись живёт 30 дней, потом
# перезапрашивается. Ограничение числа записей бережёт размер файла.
_INDEX_CACHE_TTL = 30 * 24 * 3600
_INDEX_CACHE_MAX = 20000

# Слой API/фильтрации. Если requests недоступен — вкладка покажет заглушку.
_IMPORT_ERROR = ""
try:
    from shikimori_api import (
        ShikimoriApiClient, AnimeFilter, Anime, ShikimoriError, find_anime,
        ORDERS, DEFAULT_BASE_URL, CONTENT_ANIME, CONTENT_MANGA,
        kinds_for, statuses_for, kind_label, status_label, views_from_card,
        index_base_from_card, index_components_from_card,
        genre_group, GENRE_GROUP_LABELS, GENRE_GROUP_ORDER,
    )
    _HAS_API = True
except Exception as _e:  # pragma: no cover
    _HAS_API = False
    _IMPORT_ERROR = str(_e)


class ClearableDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox, который МОЖНО очистить с клавиатуры (Backspace/Delete).

    Обычный QDoubleSpinBox при стирании всего текста считает пустую строку
    «промежуточной» (Intermediate) и при потере фокуса откатывается к прежнему
    значению — поэтому очистить поле не получается. Здесь пустой ввод трактуется
    как минимум диапазона: при заданном setSpecialValueText() поле показывает
    спецтекст (например «любая»), то есть фильтр сбрасывается.
    """

    def validate(self, text, pos):  # type: ignore[override]
        if text.strip() == "":
            return (QValidator.State.Acceptable, text, pos)
        return super().validate(text, pos)

    def valueFromText(self, text):  # type: ignore[override]
        if text.strip() == "":
            return self.minimum()
        return super().valueFromText(text)


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
# «Индекс популярности» — те же просмотры, но взвешенные на свежесть выхода:
# свежий тайтл с меньшими просмотрами часто узнаваемее старого «миллионника»
# (см. _popularity_index). Тоже локальная сортировка, тянет те же карточки.
ORDER_INDEX = "popindex"

ORDER_LABELS = {
    ORDER_VIEWS: "По просмотрам",
    ORDER_INDEX: "По индексу популярности",
    "ranked": "По рейтингу", "popularity": "По популярности", "name": "По имени",
    "aired_on": "По дате выхода", "episodes": "По эпизодам", "kind": "По типу",
    "id": "По id", "random": "Случайно",
}

# Параметры «индекса популярности». Половина узнаваемости теряется примерно за
# 5 лет — подобрано так, чтобы свежий тайтл с заметно меньшими просмотрами
# обходил старый «миллионник» (пример пользователя: тайтл 2025 г. с 8k узнают
# лучше, чем 2012 г. с 41k). Пол (floor) не даёт классике обнулиться совсем.
_INDEX_HALF_LIFE_YEARS = 5.0
_INDEX_RECENCY_FLOOR = 0.12
# Очень слабое влияние оценки тайтла на индекс (просьба «прям незначительно»):
# отклонение оценки от ~7 баллов меняет индекс лишь на проценты.
_INDEX_SCORE_INFLUENCE = 0.04
_INDEX_SCORE_PIVOT = 7.0


def _age_years(when) -> "Optional[float]":
    """Возраст тайтла в годах (дробных) на сегодня. when — datetime.date (точно по
    дню/месяцу), int-год (грубо по году) или None. None/ошибка → None («возраст
    неизвестен»)."""
    if when is None:
        return None
    try:
        if isinstance(when, datetime.date):
            return max(0.0, (datetime.date.today() - when).days / 365.25)
        return max(0.0, float(datetime.date.today().year - int(when)))
    except (TypeError, ValueError):
        return None


def _index_factors(when, score: float = 0.0) -> tuple[float, float]:
    """Множители индекса: (свежесть выхода, оценка). recency ∈ [floor, 1.0],
    score_factor ∈ [0.6, 1.4]. when — дата выхода (точно по дню/месяцу) или год.
    Вынесено, чтобы и считать индекс, и показывать в подсказке влияние года/оценки."""
    age = _age_years(when)
    if age is None:
        recency = _INDEX_RECENCY_FLOOR   # дата неизвестна — считаем «старым»
    else:
        recency = max(_INDEX_RECENCY_FLOOR,
                      0.5 ** (age / _INDEX_HALF_LIFE_YEARS))
    score_factor = 1.0 + _INDEX_SCORE_INFLUENCE * (float(score or 0.0) - _INDEX_SCORE_PIVOT)
    score_factor = max(0.6, min(1.4, score_factor))
    return recency, score_factor


def _popularity_index(base: float, when, score: float = 0.0) -> float:
    """«Индекс популярности»: взвешенная по статусам база (index_base_from_card —
    просмотрено=10, смотрю=8, брошено/отложено=6, запланировано=2), домноженная
    на свежесть выхода тайтла (точно по дате) и СЛАБО — на его оценку. Чем свежее
    тайтл и выше оценка, тем выше индекс при той же базе."""
    if base <= 0:
        return 0.0
    recency, score_factor = _index_factors(when, score)
    return base * recency * score_factor

# Размер обложки в списке (постер 7:10). Покрупнее — постеры хорошо видно.
_THUMB_W, _THUMB_H = 96, 136


# Сортировка по просмотрам тянет по карточке на тайтл — при широком поиске их
# могут быть тысячи. Поэтому: (1) поиск идёт по ПОПУЛЯРНОСТИ (вверху — известные
# тайтлы, а не мусор), (2) просмотры дозагружаем только для верхушки выдачи,
# (3) между запросами держим паузу — Shikimori лимитирует ~90 запросов/мин и без
# троттлинга на длинной дозагрузке сыпал 429. Остальное остаётся в найденном
# (популярном) порядке.
_VIEWS_SORT_MAX = 100
_VIEWS_THROTTLE = 0.7   # сек между карточками (≈85 запросов/мин < лимита 90)


def _user_agent() -> str:
    return f"{APP_NAME}/{APP_VERSION} (+https://github.com)"


def _client_factory(max_retries: int = 3) -> "ShikimoriApiClient":
    """Создаёт клиент. OAuth-токен (если задан) берём из переменной окружения
    SHIKIMORI_TOKEN — безопасно, без хранения в коде/настройках. max_retries
    повышаем для дозагрузки просмотров (там длинная серия запросов)."""
    token = os.environ.get("SHIKIMORI_TOKEN") or None
    return ShikimoriApiClient(base_url=DEFAULT_BASE_URL,
                              user_agent=_user_agent(), token=token,
                              max_retries=max_retries)


# Расхождения систем транслитерации (Хепбёрн ↔ Поливанов) дробят один тайтл на
# два разных написания: «Кобаяши» (shi) и «Кобаяси» (си) — это одно имя. Сводим
# обе формы к одной канонической, чтобы пак с «Кобаяши» прятал из выдачи
# «Кобаяси». Берём только дифтонги, которые в русском почти не встречаются вне
# японской транслитерации (низкий риск ложного слияния): «дж»→«дз», «ши»→«си».
_TRANSLIT_FOLDS = (
    ("дж", "дз"),   # ji/ja/jo… по Хепбёрну: «Фуджи»→«Фудзи», «Джоджо»→«Дзодзо»
    ("ши", "си"),   # shi по Хепбёрну: «Кобаяши»→«Кобаяси», «Аниме»? — нет, «ши»
)


def _translit_fold(s: str) -> str:
    for a, b in _TRANSLIT_FOLDS:
        s = s.replace(a, b)
    return s


def _norm_title(s: str) -> str:
    """Нормализация названия для сравнения с ответами паков: нижний регистр,
    схлопнутые пробелы, без хвостовой пунктуации/скобок-сезонов по краям.

    Хвостовой год-уточнитель в скобках убираем («hunter x hunter (1999)» →
    «hunter x hunter»): на Shikimori разные экранизации различаются годом
    («(1999)» и «(2011)»), и без снятия года исключение пака с одной версией
    не скрывало бы из выдачи другую (это и есть кейс «Охотник х Охотник»).

    Хвостовой маркер версии «√…» убираем («Токийский гуль √A» → «Токийский
    гуль»): √A/√R — это пометки сезонов, которых в названии пака обычно нет."""
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]\s*$", "", s)
    s = re.sub(r"\s*√\s*\S*$", "", s)
    s = _translit_fold(s)
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
    r"(?:the\s+)?(?:final\s+)?(?:season|сезон[а-я]*|часть|части|part|cour|кор|tv|тв"
    r"|фильм|movie|спэшл|спешл|special|ova|ona|oad|ова|она)"
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


# Подзаголовок после двоеточия/«!»/«?»/«…» С ПРОБЕЛОМ («Наруто: Ураганные
# хроники» → «Наруто», «Этот замечательный мир! Багровая легенда» → «Этот
# замечательный мир»). Разделитель без пробела НЕ режем, чтобы не ломать
# «Re:Zero», «Steins;Gate» и т.п. После «!/?» обязателен непробельный символ —
# чтобы голый хвостовой «!» (его _norm_title уже срезал) ничего не отрезал.
_SUBTITLE_RX = re.compile(r"\s*[:：!?…]+\s+\S.*$")


def _franchise_key(s: str) -> str:
    """«Ключ франшизы» — базовое название без сезона/части И без подзаголовка:
    «Атака титанов 2» → «атака титанов», «Наруто: Ураганные хроники» → «наруто»,
    «Бездомный бог: Арагото» → «бездомный бог», «Shingeki no Kyojin Season 2» →
    «shingeki no kyojin». Нужен, чтобы схлопывать сезоны/части одной франшизы в
    выдаче и чтобы пак с «Наруто» прятал и «Наруто: Ураганные хроники»."""
    s = _SUBTITLE_RX.sub("", _norm_title(s)).strip()
    # Финальная зачистка пунктуации: после снятия сезона мог «обнажиться» хвостовой
    # знак, который _norm_title уже срезал у пака — иначе «Этот замечательный мир!»
    # (пак) ≠ «Этот замечательный мир! 2» (выдача) из-за «!».
    return _base_title(s).strip(" .!?–—-:;\"'«»()[]")


def _title_words(s: str) -> list:
    """Слова названия (дефис = разделитель, как пробел): «девочки-мечтательницы»
    → [«девочки», «мечтательницы»], чтобы дефисные/пробельные варианты одного
    тайтла дробились на слова одинаково."""
    return [w for w in re.split(r"[\s\-–—]+", s) if w]


def _same_franchise_prefix(a: str, b: str, min_words: int = 4) -> bool:
    """True, если два «ключа франшизы» — это один длинный тайтл, различающийся
    лишь последним словом. Нужно для франшиз без сезонного маркера и подзаголовка-
    через-двоеточие, где части отличаются только хвостовым словом: «Этот глупый
    свин не понимает мечту девочки зайки» vs «…девочки-мечтательницы». Порог
    min_words=4 защищает короткие названия от ложного слияния."""
    aw, bw = _title_words(a), _title_words(b)
    if len(aw) < min_words or len(bw) < min_words or abs(len(aw) - len(bw)) > 1:
        return False
    n = 0
    for x, y in zip(aw, bw):
        if x != y:
            break
        n += 1
    # Общий префикс — всё, кроме последнего слова более короткого названия.
    return n >= min(len(aw), len(bw)) - 1


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
                client, self.criteria, throttle=0.25,
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
    # anime_id, просмотры (-1 при ошибке), взвешенная база индекса, разбивка по
    # статусам (список (подпись, взвешенный_вклад, число_людей) или [])
    item = pyqtSignal(int, int, float, object)
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
            client = _client_factory(max_retries=5)
            total = len(self.ids)
            for i, aid in enumerate(self.ids, 1):
                if self._stop:
                    break
                views, base, comps = -1, 0.0, []
                try:
                    card = client.get_anime(aid)
                    views = views_from_card(card)
                    base = index_base_from_card(card)
                    comps = index_components_from_card(card)
                except Exception:
                    views, base, comps = -1, 0.0, []
                self.signals.item.emit(aid, views, base, comps)
                self.signals.progress.emit(i, total)
                # Троттлинг под лимит Shikimori (~90 req/min): пауза между
                # карточками, дробим её, чтобы «Стоп» срабатывал мгновенно.
                if i < total:
                    slept = 0.0
                    while slept < _VIEWS_THROTTLE and not self._stop:
                        time.sleep(0.1)
                        slept += 0.1
        finally:
            if client is not None:
                client.close()
            self.signals.finished.emit()


# ─── Делегат: значок «глаз» с числом просмотров ──────────────────────────────
_COPY_ICON_SZ = 16       # размер кнопки «копировать»
_COPY_TITLE_GAP = 6      # отступ кнопки от конца названия
_COPY_FEEDBACK_MS = 1500  # сколько держать «галочку» после копирования
_RANK_W = 30             # ширина левого отступа строки под номер места тайтла


class _ViewsBadgeDelegate(QStyledItemDelegate):
    """Дорисовывает к строке тайтла настоящий SVG-значок «глаз» (qtawesome
    fa5s.eye) и число просмотров у правого края, а также кнопку «копировать»
    название (fa5s.copy) сразу справа от самого названия. «Глаз» — вместо emoji 👁
    (одинаково на всех ОС/темах); число берётся из кеша просмотров вкладки (тот же,
    что и для сортировки) и рисуется, когда дозагружено. Клик по «копировать»
    (editorEvent) кладёт название в буфер обмена и на 1.5 с показывает «галочку»."""

    def __init__(self, tab: "ShikimoriTab"):
        super().__init__(tab)
        self._tab = tab
        self._icon = get_icon('fa5s.eye', color=C['text2'])
        self._index_icon = get_icon('fa5s.fire', color=C.get('peach', '#fab387'))
        self._copy_icon = get_icon('fa5s.copy', color=C['text2'])
        self._ok_icon = get_icon('fa5s.check', color=C.get('green', '#a6e3a1'))
        self._copy_orig_icon = get_icon('fa5s.copy', color=C['text2'])
        self._ok_orig_icon = get_icon('fa5s.check', color=C.get('green', '#a6e3a1'))
        self._copied_id = None          # id строки с активной «галочкой» (рус. название)
        self._copied_orig_id = None     # id строки с активной «галочкой» (ориг. название)
        self._index_rects = {}          # aid -> QRect значка индекса (для подсказки)
        # aid -> ТОЧНЫЙ нарисованный прямоугольник кнопки «копировать» (рус./ориг.).
        # Считаем их в paint() реальной опцией Qt и переиспользуем в hover-фильтре:
        # ручная реконструкция опции (initFrom) теряет фичи декорации → X иконки
        # уезжал и курсор-«рука» не появлялся над реально видимым значком.
        self._copy_rects = {}
        self._copy_orig_rects = {}
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._clear_copied)
        self._reset_orig_timer = QTimer(self)
        self._reset_orig_timer.setSingleShot(True)
        self._reset_orig_timer.timeout.connect(self._clear_copied_orig)

    def _clear_copied(self):
        self._copied_id = None
        self._tab.list.viewport().update()

    def _clear_copied_orig(self):
        self._copied_orig_id = None
        self._tab.list.viewport().update()

    def _copy_rect(self, option, index) -> QRect:
        """Прямоугольник кнопки «копировать» — строго справа от текста названия
        (первая строка) и по центру ИМЕННО этой строки. По правому краю обрезается,
        чтобы не залезть за границу/под счётчик просмотров."""
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        tr = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        fm = opt.fontMetrics
        title = (index.data(Qt.ItemDataRole.UserRole + 2) or "").split("\n")[0]
        tw = fm.horizontalAdvance(title)
        # X — сразу за концом названия, но не за правым краем строки.
        x = tr.left() + tw + _COPY_TITLE_GAP
        x = min(x, option.rect.right() - 8 - _COPY_ICON_SZ)
        x = max(x, tr.left())
        # Y — по центру ПЕРВОЙ строки названия. Текст в ячейке выровнен по вертикали
        # по центру (Qt.AlignVCenter), т.е. блок из нескольких строк начинается не от
        # tr.top(), а ниже на половину свободного места. Раньше Y брался от tr.top(),
        # и значок «уезжал» к верхнему краю карточки вместо строки с названием.
        full = index.data(Qt.ItemDataRole.DisplayRole) or title
        block_h = fm.boundingRect(
            QRect(0, 0, max(1, tr.width()), 1 << 22),
            int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop), full).height()
        block_top = tr.top() + max(0, (tr.height() - block_h) // 2)
        y = block_top + max(0, (fm.lineSpacing() - _COPY_ICON_SZ) // 2)
        return QRect(int(x), int(y), _COPY_ICON_SZ, _COPY_ICON_SZ)

    def _copy_orig_rect(self, option, index) -> QRect:
        """Прямоугольник кнопки «копировать» для ОРИГИНАЛЬНОГО названия (вторая строка).
        Возвращает null QRect(), если оригинального названия нет или оно совпадает с
        отображаемым (тогда кнопка не рисуется и не кликабельна)."""
        orig = index.data(Qt.ItemDataRole.UserRole + 3) or ""
        title = index.data(Qt.ItemDataRole.UserRole + 2) or ""
        if not orig or orig == title:
            return QRect()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        tr = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        fm = opt.fontMetrics
        tw = fm.horizontalAdvance(orig)
        x = tr.left() + tw + _COPY_TITLE_GAP
        x = min(x, option.rect.right() - 8 - _COPY_ICON_SZ)
        x = max(x, tr.left())
        full = index.data(Qt.ItemDataRole.DisplayRole) or ""
        block_h = fm.boundingRect(
            QRect(0, 0, max(1, tr.width()), 1 << 22),
            int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop), full).height()
        block_top = tr.top() + max(0, (tr.height() - block_h) // 2)
        # Вторая строка начинается через lineSpacing() от начала блока.
        y = block_top + fm.lineSpacing() + max(0, (fm.lineSpacing() - _COPY_ICON_SZ) // 2)
        return QRect(int(x), int(y), _COPY_ICON_SZ, _COPY_ICON_SZ)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        # Номер места тайтла в списке — слева от постера (в зарезервированном
        # левом отступе строки, см. padding-left у QListWidget::item).
        rank = index.row() + 1
        painter.save()
        f = QFont(option.font)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(C['text2']))
        painter.drawText(
            QRect(option.rect.left() + 2, option.rect.top(),
                  _RANK_W - 4, option.rect.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter),
            str(rank))
        painter.restore()
        aid = index.data(Qt.ItemDataRole.UserRole + 1)
        icon = self._ok_icon if aid == self._copied_id else self._copy_icon
        painter.save()
        main_rect = self._copy_rect(option, index)
        self._copy_rects[aid] = QRect(main_rect)   # запоминаем точную область для hover
        painter.drawPixmap(main_rect,
                           icon.pixmap(_COPY_ICON_SZ, _COPY_ICON_SZ))
        painter.restore()
        # Кнопка «копировать» для ОРИГИНАЛЬНОГО названия (вторая строка, если есть).
        orig_rect = self._copy_orig_rect(option, index)
        self._copy_orig_rects[aid] = (QRect(orig_rect) if not orig_rect.isNull()
                                      else QRect())
        if not orig_rect.isNull():
            icon_orig = (self._ok_orig_icon if aid == self._copied_orig_id
                         else self._copy_orig_icon)
            painter.save()
            painter.drawPixmap(orig_rect, icon_orig.pixmap(_COPY_ICON_SZ, _COPY_ICON_SZ))
            painter.restore()
        try:
            views = self._tab._views_cache.get(aid)
        except Exception:
            views = None
        if views is None or views < 0:
            return
        text = f"{views:,}".replace(",", " ")
        icon_sz, pad, gap = 14, 8, 5
        rect = option.rect
        fm = option.fontMetrics
        tw = fm.horizontalAdvance(text)
        x_text = rect.right() - pad - tw
        x_icon = x_text - gap - icon_sz
        y_icon = rect.center().y() - icon_sz // 2
        painter.save()
        painter.drawPixmap(int(x_icon), int(y_icon),
                           self._icon.pixmap(icon_sz, icon_sz))
        painter.setPen(QColor(C['text2']))
        painter.drawText(
            QRect(int(x_text), rect.top(), tw + 2, rect.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            text)
        painter.restore()

        # «Индекс популярности» (значок-огонёк + число) — слева от просмотров.
        # Это та же величина, по которой сортирует режим «По индексу
        # популярности»: просмотры, взвешенные на свежесть выхода.
        try:
            a = self._tab._anime_by_id.get(aid)
            idx_when = (a.air_date or a.year) if a else None
            base = self._tab._index_base_cache.get(aid, 0.0)
            idx_val = _popularity_index(base, idx_when, a.score if a else 0.0)
        except Exception:
            idx_val = 0
        if idx_val and idx_val > 0:
            itext = f"{int(round(idx_val)):,}".replace(",", " ")
            itw = fm.horizontalAdvance(itext)
            ix_text = x_icon - 14 - itw
            ix_icon = ix_text - gap - icon_sz
            painter.save()
            painter.drawPixmap(int(ix_icon), int(y_icon),
                               self._index_icon.pixmap(icon_sz, icon_sz))
            painter.setPen(QColor(C.get('peach', '#fab387')))
            painter.drawText(
                QRect(int(ix_text), rect.top(), itw + 2, rect.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                itext)
            painter.restore()
            # Запоминаем область значка индекса (огонёк + число) — по ней
            # показываем подсказку с разбивкой (см. helpEvent).
            self._index_rects[aid] = QRect(
                int(ix_icon), rect.top(),
                int(x_icon - ix_icon), rect.height())

    def helpEvent(self, event, view, option, index):
        """Подсказка к «индексу популярности» при наведении на его значок —
        показываем ФИРМЕННЫЙ тёмный попап (_InfoTipPopup, как у «Схлопывать
        франшизы»), а НЕ системный QToolTip с синей рамкой. Возврат True гасит
        системную подсказку списка."""
        if event.type() == QEvent.Type.ToolTip and _InfoTipPopup is not None:
            aid = index.data(Qt.ItemDataRole.UserRole + 1)
            rect = self._index_rects.get(aid)
            try:
                pos = event.pos()
            except Exception:
                pos = None
            if rect is not None and pos is not None and rect.contains(pos):
                tip = self._tab._index_tooltip_for(aid)
                if tip:
                    _InfoTipPopup.instance().show_at(event.globalPos(), tip)
                    return True
            _InfoTipPopup.instance().hide()
            return False
        return super().helpEvent(event, view, option, index)

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease:
            try:
                pos = event.position().toPoint()
            except AttributeError:  # старые сборки Qt
                pos = event.pos()
            if self._copy_rect(option, index).contains(pos):
                title = index.data(Qt.ItemDataRole.UserRole + 2) or ""
                if title:
                    QApplication.clipboard().setText(title)
                    self._copied_id = index.data(Qt.ItemDataRole.UserRole + 1)
                    self._reset_timer.start(_COPY_FEEDBACK_MS)
                    self._tab.list.viewport().update()
                return True  # клик по кнопке — не выделяем/не открываем строку
            # Кнопка оригинального названия.
            orig_rect = self._copy_orig_rect(option, index)
            if not orig_rect.isNull() and orig_rect.contains(pos):
                orig = index.data(Qt.ItemDataRole.UserRole + 3) or ""
                if orig:
                    QApplication.clipboard().setText(orig)
                    self._copied_orig_id = index.data(Qt.ItemDataRole.UserRole + 1)
                    self._reset_orig_timer.start(_COPY_FEEDBACK_MS)
                    self._tab.list.viewport().update()
                return True
        return super().editorEvent(event, model, option, index)


# ─── Диалог выбора жанров/тем ────────────────────────────────────────────────
class _TriStateGenre(QFrame):
    """Один жанр/тема как трёхпозиционный переключатель (один квадрат вместо двух
    колонок «вкл»/«искл»). Клик по строке циклически меняет состояние:
        0 — выкл (пустой квадрат, не влияет на поиск);
        1 — включить (зелёный квадрат с «✓» — показывать только с этим);
        2 — исключить (красный квадрат с «✕» — убрать из результатов).
    Третий клик возвращает в «выкл»."""

    OFF, INC, EXC = 0, 1, 2

    def __init__(self, gid, label, state=0, parent=None):
        super().__init__(parent)
        self.gid = gid
        self._label = label
        self._state = state
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 3, 6, 3); h.setSpacing(8)
        self._sq = QLabel()
        self._sq.setFixedSize(18, 18)
        self._sq.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._txt = QLabel(label)
        h.addWidget(self._sq)
        h.addWidget(self._txt, 1)
        self._refresh()

    def state(self):
        return self._state

    def set_state(self, st):
        self._state = st % 3
        self._refresh()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.set_state(self._state + 1)
            e.accept()
        else:
            super().mousePressEvent(e)

    def _refresh(self):
        green = C.get('green', '#a6e3a1')
        red = C.get('red', '#f38ba8')
        if self._state == self.INC:
            self._sq.setText("✓")
            self._sq.setStyleSheet(
                f"background:{green}; color:#11111b; border:1px solid {green};"
                "border-radius:3px; font-weight:bold;")
            self.setToolTip(f"«{self._label}»: показывать ТОЛЬКО с этим "
                            "(клик — исключить)")
        elif self._state == self.EXC:
            self._sq.setText("✕")
            self._sq.setStyleSheet(
                f"background:{red}; color:#11111b; border:1px solid {red};"
                "border-radius:3px; font-weight:bold;")
            self.setToolTip(f"«{self._label}»: ИСКЛЮЧИТЬ из результатов "
                            "(клик — сбросить)")
        else:
            self._sq.setText("")
            self._sq.setStyleSheet(
                f"background:transparent; border:1px solid {C.get('text2', '#888')};"
                "border-radius:3px;")
            self.setToolTip(f"«{self._label}»: не учитывается (клик — включить)")


class _GenrePickerDialog(QDialog):
    """Выбор жанров и тем (как в фильтрах Shikimori). У каждого пункта ОДИН
    трёхпозиционный квадрат (см. _TriStateGenre): клик циклически переключает
    «выкл → включить (зелёный) → исключить (красный) → выкл». items — кортежи
    (id, подпись, группа); selected/excluded — заранее отмеченные id."""

    def __init__(self, items, selected, excluded=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Жанры и темы")
        self._items = {}                       # id -> _TriStateGenre
        sel = set(selected or [])
        exc = set(excluded or [])

        root = QVBoxLayout(self)
        root.setSpacing(8)
        hint = QLabel("Клик по пункту переключает: 1× — показывать только с ним "
                      "(зелёный ✓), 2× — исключить (красный ✕), 3× — сбросить.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        root.addWidget(hint)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        host = QWidget(); hv = QVBoxLayout(host); hv.setSpacing(10)
        groups = {g: [] for g in GENRE_GROUP_ORDER}
        for gid, label, group in items:
            groups.setdefault(group, []).append((gid, label))
        for group, lst in groups.items():
            if not lst:
                continue
            box = QGroupBox(GENRE_GROUP_LABELS.get(group, group))
            grid = QGridLayout(box)
            grid.setHorizontalSpacing(10); grid.setVerticalSpacing(2)
            lst.sort(key=lambda x: x[1].lower())
            # Раскладываем пункты в 2 колонки для компактности (сам пункт — один
            # переключатель, без отдельных столбцов «вкл»/«искл»).
            cols = 2
            for i, (gid, label) in enumerate(lst):
                st = (_TriStateGenre.INC if gid in sel
                      else _TriStateGenre.EXC if gid in exc
                      else _TriStateGenre.OFF)
                w = _TriStateGenre(gid, label, st)
                self._items[gid] = w
                grid.addWidget(w, i // cols, i % cols)
            for c in range(cols):
                grid.setColumnStretch(c, 1)
            hv.addWidget(box)
        hv.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        bb = QDialogButtonBox()
        btn_clear = bb.addButton("Сбросить", QDialogButtonBox.ButtonRole.ResetRole)
        bb.addButton(QDialogButtonBox.StandardButton.Ok)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        btn_clear.clicked.connect(self._clear_all)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.resize(560, 580)

    def _clear_all(self):
        for w in self._items.values():
            w.set_state(_TriStateGenre.OFF)

    def selected_ids(self):
        return [gid for gid, w in self._items.items()
                if w.state() == _TriStateGenre.INC]

    def excluded_ids(self):
        return [gid for gid, w in self._items.items()
                if w.state() == _TriStateGenre.EXC]


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
        self._genres_cache: dict = {}  # content_type -> [(id, label, group)]
        self._thumb_cache: dict = {}   # anime_id -> QIcon
        self._thumb_pending: set = set()  # anime_id с уже запущенной загрузкой обложки
        self._placeholder = None       # серая заглушка-обложка
        self._excluded: set = set()    # нормализованные названия из паков
        self._excluded_bases: set = set()  # их «базовые» формы (без сезонов)
        self._excluded_franchises: set = set()  # их «ключи франшиз» (без подзаголовков)
        self._excluded_packs: list = []  # имена выбранных паков
        self._collapse_franchise = True   # схлопывать сезоны/части одной франшизы
        self._seen_franchises: set = set()  # уже показанные франшизы (для схлопывания)
        self._views_cache: dict = {}   # anime_id -> просмотры (для сортировки)
        self._index_base_cache: dict = {}  # anime_id -> взвешенная база индекса
        self._index_breakdown_cache: dict = {}  # anime_id -> разбивка индекса по статусам
        self._index_cache_ts: dict = {}  # anime_id -> когда запись попала в кеш (для TTL)
        # Отложенное (дебаунс) сохранение кеша индекса на диск, чтобы не писать файл
        # на каждый дозагруженный тайтл во время живой сортировки.
        self._index_cache_save_timer = QTimer(self)
        self._index_cache_save_timer.setSingleShot(True)
        self._index_cache_save_timer.timeout.connect(self._save_index_cache)
        self._load_index_cache()
        self._views_task = None        # текущая задача дозагрузки просмотров
        self._anime_by_id: dict = {}   # anime_id -> Anime (для live-обновления строк)
        self._sel_genres: list = []    # выбранные id жанров/тем (текущий тип контента)
        self._pending_genres: list = []  # id для восстановления после async-загрузки
        self._excl_genres: list = []   # исключаемые id жанров/тем
        self._pending_excl: list = []  # исключаемые id для восстановления после async
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
        self.btn_clear = QPushButton("Очистить")
        self.btn_clear.setIcon(get_icon('fa5s.trash'))
        self.btn_clear.setToolTip("Очистить список результатов")
        self.btn_clear.clicked.connect(self.clear_results)
        search_row.addWidget(self.cb_content)
        search_row.addWidget(self.ed_query, 1)
        search_row.addWidget(self.btn_search)
        search_row.addWidget(self.btn_cancel)
        search_row.addWidget(self.btn_clear)
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
        # Значок «глаз» + просмотры рисует делегат (qtawesome SVG, не emoji).
        self._views_delegate = _ViewsBadgeDelegate(self)
        self.list.setItemDelegate(self._views_delegate)
        # Курсор-«рука» при наведении на кнопку «копировать» (видно, что кликабельно).
        self.list.setMouseTracking(True)
        self.list.viewport().setMouseTracking(True)
        self.list.viewport().installEventFilter(self)
        self._copy_hover = False
        # Обложки грузим ЛЕНИВО — только для видимых строк (иначе при широком
        # поиске сотни параллельных запросов к Shikimori упираются в лимит → 429).
        self.list.verticalScrollBar().valueChanged.connect(
            lambda *_: self._load_visible_thumbs())
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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Фиксированную ширину задаём в КОНЦЕ метода — по реальной потребности
        # содержимого + место под вертикальный скроллбар, чтобы панель ВСЕГДА была
        # видна по горизонтали целиком (см. ниже scroll.setFixedWidth).
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(2, 2, 8, 2)
        pv.setSpacing(12)

        def lab(text):
            l = QLabel(text)
            l.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
            # Перенос по словам: длинные подписи (напр. «Проверять просмотров у»)
            # иначе задают огромную ширину 0-й колонки сетки и раздувают панель.
            l.setWordWrap(True)
            return l

        # ── Группа «Фильтры» ──────────────────────────────────────────────
        grp = QGroupBox("Фильтры")
        filt = QGridLayout(grp)
        filt.setHorizontalSpacing(8)
        filt.setVerticalSpacing(8)

        self.sp_score_min = ClearableDoubleSpinBox()
        self.sp_score_min.setRange(0.0, 10.0); self.sp_score_min.setSingleStep(0.5)
        self.sp_score_min.setDecimals(1)
        self.sp_score_min.setSpecialValueText("любая")
        self.sp_score_max = ClearableDoubleSpinBox()
        self.sp_score_max.setRange(0.0, 10.0); self.sp_score_max.setSingleStep(0.5)
        self.sp_score_max.setDecimals(1)
        # Минимум (0) показываем как «любая» = без верхней границы; так очистка
        # поля Backspace'ом осмысленна (сброс фильтра, а не «оценка ≤ 0»).
        self.sp_score_max.setSpecialValueText("любая")
        self.sp_score_max.setValue(10.0)

        self.cb_kind = QComboBox()
        self.cb_status = QComboBox()
        self.cb_order = QComboBox()
        # «По просмотрам» — локальная сортировка, по умолчанию (первый пункт).
        # «По индексу популярности» — тоже локальная (просмотры × свежесть).
        self.cb_order.addItem(ORDER_LABELS[ORDER_VIEWS], ORDER_VIEWS)
        self.cb_order.addItem(ORDER_LABELS[ORDER_INDEX], ORDER_INDEX)
        for o in ORDERS:
            self.cb_order.addItem(ORDER_LABELS.get(o, o), o)
        # Сколько верхних тайтлов проверять на число просмотров при сортировке
        # «По просмотрам» (раньше было жёстко зашито _VIEWS_SORT_MAX=100).
        self.sp_views_max = QSpinBox()
        self.sp_views_max.setRange(10, 2000)
        self.sp_views_max.setSingleStep(10)
        self.sp_views_max.setValue(_VIEWS_SORT_MAX)
        self.sp_views_max.setToolTip(
            "Сколько верхних тайтлов проверять на число просмотров при сортировке "
            "«По просмотрам». Больше — точнее порядок, но дольше дозагрузка "
            "(≈0.7 с на тайтл; лимит Shikimori ~90 запросов/мин).")
        self.cb_order.currentIndexChanged.connect(self._update_views_max_enabled)

        self.sp_year_from = QSpinBox(); self.sp_year_from.setRange(0, 2099)
        self.sp_year_from.setSpecialValueText("—")
        self.sp_year_to = QSpinBox(); self.sp_year_to.setRange(0, 2099)
        self.sp_year_to.setSpecialValueText("—")

        self.sp_ep_min = QSpinBox(); self.sp_ep_min.setRange(0, 10000)
        self.sp_ep_min.setSpecialValueText("—")
        self.sp_ep_max = QSpinBox(); self.sp_ep_max.setRange(0, 10000)
        self.sp_ep_max.setSpecialValueText("—")

        # Жанры/темы — множественный выбор через диалог (как фильтры Shikimori),
        # потому что одиночный список не давал комбинировать жанр+тему. Кнопка
        # показывает, что выбрано; сам список грузится асинхронно.
        self.btn_genres = QPushButton("Любые")
        self.btn_genres.setToolTip("Выбрать жанры и темы (можно несколько)")
        self.btn_genres.clicked.connect(self._open_genre_picker)

        # Комбобоксы по умолчанию растягиваются под самый длинный пункт (напр.
        # «По просмотрам», длинные жанры) и раздували панель так, что её правый
        # край обрезался. Ограничиваем ширину: ~12 символов минимум, длиннее —
        # эллипсис. Колонки 1/3 имеют stretch, поэтому в доступной ширине панели
        # комбобоксы всё равно растянутся и обычные подписи видны полностью.
        for _c in (self.cb_kind, self.cb_status, self.cb_order):
            _c.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            _c.setMinimumContentsLength(10)
        # Спинбоксы тоже ограничиваем по минимуму, иначе их «минимальная» ширина
        # (под спецтекст «любая» + стрелки) держит панель широкой. С stretch колонок
        # 1/3 в доступной ширине они всё равно растянутся.
        for _s in (self.sp_score_min, self.sp_score_max, self.sp_views_max,
                   self.sp_year_from, self.sp_year_to, self.sp_ep_min, self.sp_ep_max):
            _s.setMinimumWidth(58)

        r = 0
        filt.addWidget(lab("Оценка от"), r, 0); filt.addWidget(self.sp_score_min, r, 1)
        filt.addWidget(lab("до"), r, 2); filt.addWidget(self.sp_score_max, r, 3)
        r += 1
        filt.addWidget(lab("Сортировка"), r, 0)
        filt.addWidget(self.cb_order, r, 1, 1, 3)
        r += 1
        self.lbl_views_max = lab("Проверять просмотров у")
        filt.addWidget(self.lbl_views_max, r, 0)
        filt.addWidget(self.sp_views_max, r, 1, 1, 3)
        r += 1
        filt.addWidget(lab("Тип"), r, 0)
        filt.addWidget(self.cb_kind, r, 1, 1, 3)
        r += 1
        filt.addWidget(lab("Статус"), r, 0)
        filt.addWidget(self.cb_status, r, 1, 1, 3)
        r += 1
        filt.addWidget(lab("Жанры/темы"), r, 0)
        filt.addWidget(self.btn_genres, r, 1, 1, 3)
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

        # ── Схлопывание франшиз (сезоны/части → один тайтл) ───────────────
        # Текст короткий (без «(один сезон/часть)») — иначе чекбокс не переносится
        # и задаёт минимальную ширину панели ~460 px. Подробности — в подсказке.
        self.chk_collapse_fr = QCheckBox("Схлопывать франшизы")
        self.chk_collapse_fr.setChecked(self._collapse_franchise)
        self.chk_collapse_fr.setToolTip(
            "Скрывать из выдачи прочие сезоны/части той же франшизы — достаточно "
            "одного тайтла.\nНапр. «Атака титанов 2», «Бездомный бог: Арагото», "
            "«Наруто: Ураганные хроники» прячутся, если уже показан первый.\n"
            "Также пак с «Наруто» спрячет и «Наруто: Ураганные хроники».")
        self.chk_collapse_fr.toggled.connect(self._on_collapse_toggled)
        pv.addWidget(self.chk_collapse_fr)

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
        # Ширина = реальная потребность содержимого + место под вертикальный
        # скроллбар. Комбобоксы выше ограничены по ширине, поэтому асинхронная
        # загрузка длинных жанров/типов панель НЕ раздувает → она всегда видна
        # по горизонтали целиком при любом размере окна.
        # По МИНИМАЛЬНОЙ потребности (не preferred — иначе панель неоправданно
        # широкая) + запас и место под скроллбар. Колонки 1/3 со stretch растянут
        # комбобоксы/спинбоксы в этой ширине, поэтому подписи видны полностью.
        _need = max(panel.minimumSizeHint().width(), 320)
        _sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
        scroll.setFixedWidth(_need + _sb + 12)
        body.addWidget(scroll)

    def eventFilter(self, obj, ev):
        # Над кнопкой «копировать» в строке списка показываем курсор-«руку».
        if obj is self.list.viewport() and ev.type() == QEvent.Type.MouseMove:
            try:
                pos = ev.position().toPoint()
            except AttributeError:           # старые сборки Qt
                pos = ev.pos()
            over = False
            idx = self.list.indexAt(pos)
            if idx.isValid():
                # Берём ТОЧНЫЕ прямоугольники, сохранённые делегатом в paint()
                # (реальной опцией Qt). Ручная реконструкция опции теряла фичи
                # декорации → зона «руки» уезжала от видимой иконки.
                try:
                    aid = idx.data(Qt.ItemDataRole.UserRole + 1)
                    main_r = self._views_delegate._copy_rects.get(aid)
                    orig_r = self._views_delegate._copy_orig_rects.get(aid)
                    over = (bool(main_r) and main_r.contains(pos)) or (
                        bool(orig_r) and not orig_r.isNull() and orig_r.contains(pos))
                except Exception:
                    over = False
            if over != self._copy_hover:
                self._copy_hover = over
                self.list.viewport().setCursor(
                    Qt.CursorShape.PointingHandCursor if over
                    else Qt.CursorShape.ArrowCursor)
        return super().eventFilter(obj, ev)

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
                padding: 4px 4px 4px {_RANK_W}px; border-radius: 5px; color: {C['text']};
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
        # Жанры/темы различаются между аниме и мангой — сбрасываем выбор и (при
        # необходимости) подгружаем список под новый тип.
        self._sel_genres = []
        self._pending_genres = []
        self._excl_genres = []
        self._pending_excl = []
        self._update_genres_btn()
        if ct not in self._genres_cache:
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
        ui_order = self.cb_order.currentData() or ORDER_VIEWS
        # «По просмотрам»/«По индексу» — локальные сортировки: на СЕРВЕРЕ берём
        # популярные (чтобы вверху были известные тайтлы, а не безвестный мусор),
        # а уже их пересортировываем локально (см. _begin_views_sort).
        server_order = ("popularity"
                        if ui_order in (ORDER_VIEWS, ORDER_INDEX) else ui_order)
        return AnimeFilter(
            query=self.ed_query.text().strip(),
            kind=self.cb_kind.currentData() or "",
            status=self.cb_status.currentData() or "",
            order=server_order,
            score_min=(smin if smin > 0 else None),
            score_max=(smax if 0 < smax < 10.0 else None),
            year_from=(yf if yf > 0 else None),
            year_to=(yt if yt > 0 else None),
            episodes_min=(epmin if epmin > 0 else None),
            episodes_max=(epmax if epmax > 0 else None),
            genres=list(self._sel_genres),
            exclude_genres=list(self._excl_genres),
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
        self._anime_by_id.clear()
        self._raw_results = []
        self._results = []
        self._seen_franchises = set()
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
        """«Стоп» работает на ОБОИХ этапах: и во время поиска, и во время
        дозагрузки просмотров (сортировки). Накопленное всегда оставляем."""
        # 1) Идёт дозагрузка просмотров (сортировка) — прерываем именно её и
        #    оставляем уже расставленный порядок, БЕЗ перезапуска.
        if self._views_task is not None:
            self._stop_views_task()
            self._set_busy(False)
            self._resort_by_views(done=False)
            n = len(self._results)
            self._set_actions_enabled(n > 0)
            self.lbl_status.setText(
                f"Сортировка остановлена. Найдено: {len(self._raw_results)}, "
                f"после фильтра: {n}")
            return
        # 2) Идёт поиск — останавливаем его.
        if self._task is not None:
            self._task.stop()
        self._set_busy(False)
        self._task = None
        n = len(self._results)
        self._set_actions_enabled(n > 0)
        # Сортировка по просмотрам — досортируем то, что успели набрать (её тоже
        # можно прервать «Стопом» — см. ветку выше).
        if n and self._views_sort_active():
            self.lbl_status.setText(f"Остановлено, сортирую {self._sort_phrase()}…")
            self._begin_views_sort()
        else:
            self.lbl_status.setText(
                f"Остановлено. Найдено: {len(self._raw_results)}, "
                f"после фильтра: {n}" if n else "Остановлено.")

    def clear_results(self):
        """Очищает список результатов (кнопка «Очистить»). Идущий поиск/дозагрузку
        просмотров останавливает; кеш просмотров сохраняем — пригодится повторно."""
        if self._task is not None:
            self._task.stop()
            self._task = None
        self._stop_views_task()
        self._set_busy(False)
        self.list.clear()
        self._anime_by_id.clear()
        self._raw_results = []
        self._results = []
        self._set_actions_enabled(False)
        self.lbl_status.setText("Список очищен.")

    def _on_search_progress(self, page: int, matched: int):
        if self._task is not None:
            self.lbl_status.setText(
                f"Поиск… страница {page}: найдено {len(self._raw_results)}, "
                f"после фильтра {len(self._results)} (можно «Стоп»)")

    def _on_search_batch(self, items: list):
        """Потоково добавляет новые тайтлы страницы (с учётом исключения паков)."""
        if self._task is None:
            return
        for a in items:
            self._raw_results.append(a)
            if self._is_excluded(a):
                continue
            if self._collapse_franchise and self._franchise_seen(a):
                continue
            self._results.append(a)
            self._append_anime(a)
        self._load_visible_thumbs()
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
        # Франшиза целиком: пак с «Наруто» прячет «Наруто: Ураганные хроники».
        if self._collapse_franchise and self._excluded_franchises:
            keys = [k for k in (_franchise_key(a.title),
                                _franchise_key(a.name)) if k]
            for k in keys:
                if k in self._excluded_franchises:
                    return True
            # Длинные тайтлы одной франшизы, отличающиеся лишь последним словом
            # («…мечту девочки зайки» vs «…девочки-мечтательницы»).
            for k in keys:
                if any(_same_franchise_prefix(k, ex)
                       for ex in self._excluded_franchises):
                    return True
        return False

    def _franchise_seen(self, a) -> bool:
        """True (и запоминает), если франшиза этого тайтла уже показана в выдаче —
        для схлопывания сезонов/частей. Ключи берём и по русскому, и по ромадзи."""
        keys = {k for k in (_franchise_key(a.title), _franchise_key(a.name)) if k}
        if not keys:
            return False
        if keys & self._seen_franchises:
            return True
        self._seen_franchises |= keys
        return False

    def _on_collapse_toggled(self, on: bool):
        self._collapse_franchise = bool(on)
        # Переприменяем к уже найденному (без нового запроса к Shikimori).
        if self._raw_results:
            self._apply_exclusions()

    def _rebuild_excluded_bases(self):
        """Пересобирает «базовые» формы и «ключи франшиз» исключённых названий."""
        self._excluded_bases = {b for b in (_base_title(x) for x in self._excluded) if b}
        self._excluded_franchises = {f for f in (_franchise_key(x) for x in self._excluded) if f}

    def _apply_exclusions(self):
        """Фильтрует «сырые» результаты по выбранным пакам и схлопывает франшизы."""
        raw = self._raw_results
        self._seen_franchises = set()   # пересобираем «показанные франшизы» с нуля
        kept, excluded_n = [], 0
        for a in raw:
            if self._is_excluded(a):
                excluded_n += 1
            elif self._collapse_franchise and self._franchise_seen(a):
                excluded_n += 1
            else:
                kept.append(a)
        self._results = kept
        self._display_results()
        n = len(self._results)
        self._set_actions_enabled(n > 0)
        if n:
            # Показываем и сколько НАШЛИ всего, и сколько осталось после фильтрации.
            msg = f"Найдено: {len(raw)}, после фильтра: {n}"
            if excluded_n:
                msg += f" (скрыто: {excluded_n})"
            self.lbl_status.setText(msg)
        elif raw and excluded_n:
            self.lbl_status.setText("Всё найденное уже есть в выбранных паках.")
        else:
            self.lbl_status.setText("Ничего не найдено под заданные фильтры.")

    # ── Сортировка по просмотрам (локально, с дозагрузкой карточек) ────────────
    def _views_sort_active(self) -> bool:
        """True для локальных сортировок, которым нужны числа просмотров: и «по
        просмотрам», и «по индексу популярности» (обе тянут карточки тайтлов)."""
        return self.cb_order.currentData() in (ORDER_VIEWS, ORDER_INDEX)

    def _index_sort_active(self) -> bool:
        return self.cb_order.currentData() == ORDER_INDEX

    def _sort_key(self, a) -> float:
        """Ключ локальной сортировки. Неизвестные просмотры (-1) — в конец.
        Для «индекса» взвешиваем просмотры на свежесть выхода тайтла."""
        views = self._views_cache.get(a.id, -1)
        if views < 0:
            return -1.0
        if self._index_sort_active():
            base = self._index_base_cache.get(a.id, 0.0)
            return _popularity_index(base, a.air_date or a.year, a.score)
        return float(views)

    def _sort_phrase(self) -> str:
        return "по индексу" if self._index_sort_active() else "по просмотрам"

    def _update_views_max_enabled(self, *_):
        """Поле «Проверять просмотров у …» активно только при сортировке
        «По просмотрам» — для прочих сортировок оно ни на что не влияет."""
        active = self._views_sort_active()
        sp = getattr(self, "sp_views_max", None)
        lbl = getattr(self, "lbl_views_max", None)
        if sp is not None:
            sp.setEnabled(active)
        if lbl is not None:
            lbl.setEnabled(active)

    def _views_sort_limit(self) -> int:
        """Сколько верхних тайтлов проверять на просмотры (из поля настроек)."""
        try:
            return max(1, int(self.sp_views_max.value()))
        except Exception:
            return _VIEWS_SORT_MAX

    def _display_results(self):
        """Заполняет список результатами. При сортировке по просмотрам сначала
        упорядочивает их по кешу просмотров (неизвестные — в конец)."""
        if self._views_sort_active():
            self._results.sort(key=self._sort_key, reverse=True)
        self._fill_list(self._results)

    def _stop_views_task(self):
        if self._views_task is not None:
            try:
                self._views_task.stop()
            except Exception:
                pass
            # Отписываемся от сигналов: задача в пуле ещё доживёт цикл, но её
            # поздние сигналы не должны трогать UI после «Очистить»/нового поиска.
            for sig in (self._views_task.signals.item,
                        self._views_task.signals.progress,
                        self._views_task.signals.finished):
                try:
                    sig.disconnect()
                except Exception:
                    pass
            self._views_task = None

    def _begin_views_sort(self):
        """Дозагружает просмотры для результатов, у которых их ещё нет, и затем
        пересортировывает список. Уже известные берём из кеша (не перезапрашиваем)."""
        self._stop_views_task()
        limit = self._views_sort_limit()
        ids = [a.id for a in self._results[:limit]
               if a.id not in self._views_cache]
        if not ids:
            self._resort_by_views(done=True)
            return
        self.lbl_status.setText(
            f"Сортировка {self._sort_phrase()}… 0/{len(ids)} (можно «Стоп»)")
        # «Стоп» активен и во время сортировки — её тоже можно прервать.
        self.btn_cancel.setEnabled(True)
        self.btn_search.setEnabled(False)
        task = _ViewsTask(ids)
        task.signals.item.connect(self._on_views_item)
        task.signals.progress.connect(self._on_views_progress)
        task.signals.finished.connect(self._on_views_finished)
        self._views_task = task
        self._pool.start(task)

    def _on_views_item(self, anime_id: int, views: int, base: float, comps=None):
        self._views_cache[anime_id] = views
        self._index_base_cache[anime_id] = base
        self._index_breakdown_cache[anime_id] = list(comps or [])
        # Свежая запись — фиксируем время и планируем отложенную запись на диск.
        self._index_cache_ts[anime_id] = time.time()
        self._schedule_index_cache_save()
        # Подсказка с разбивкой индекса показывается делегатом по наведению на
        # значок индекса (см. _ViewsBadgeDelegate.helpEvent) — здесь только кешируем.
        # Расставляем тайтлы ПАРАЛЛЕЛЬНО, по мере поступления просмотров: как только
        # узнали число у тайтла, сразу ставим его на своё место (не ждём конца
        # дозагрузки). Порядок строк и номера мест обновляются вживую.
        if self._views_sort_active():
            self._resort_by_views(done=False)

    def _index_tooltip_for(self, aid) -> str:
        """Текст подсказки к «индексу популярности». Показываем ПОЛНУЮ цепочку,
        чтобы было видно, что свежесть/оценка реально применяются:
        база (люди × вес статуса) → множители за дату выхода и оценку → итог."""
        comps = self._index_breakdown_cache.get(aid)
        base = self._index_base_cache.get(aid, 0.0)
        if not comps or base <= 0:
            return ""
        a = self._anime_by_id.get(aid)
        when = (a.air_date or a.year) if a else None
        score = a.score if a else 0.0
        recency, score_factor = _index_factors(when, score)
        idx_val = _popularity_index(base, when, score)
        if idx_val <= 0:
            return ""
        def _fmt(n):
            return f"{int(round(n)):,}".replace(",", " ")
        lines = [f"Индекс популярности — {_fmt(idx_val)}",
                 f"База (люди × вес статуса): {_fmt(base)}"]
        for label, weighted, cnt in comps:
            pct = weighted / base * 100.0
            lines.append(f"  • {label}: {_fmt(weighted)}  "
                         f"({_fmt(cnt)} чел., {pct:.0f}%)")
        lines.append("")
        lines.append("Множители за свежесть и оценку:")
        date_lbl = (a.date_label if a else "") or "дата неизвестна"
        lines.append(f"  • Свежесть выхода ({date_lbl}): "
                     f"×{recency:.2f} ({(recency - 1.0) * 100:+.0f}%)")
        score_lbl = f"{float(score):.2f}" if score else "нет оценки"
        lines.append(f"  • Оценка ({score_lbl}): "
                     f"×{score_factor:.2f} ({(score_factor - 1.0) * 100:+.0f}%)")
        lines.append(f"Итог: {_fmt(base)} × {recency:.2f} × {score_factor:.2f}"
                     f" ≈ {_fmt(idx_val)}")
        lines.append("")
        lines.append("По этому индексу сортирует режим «По индексу популярности».")
        return "\n".join(lines)

    def _on_views_progress(self, done: int, total: int):
        if self._views_task is not None:
            self.lbl_status.setText(
                f"Сортировка {self._sort_phrase()}… {done}/{total} (можно «Стоп»)")

    def _on_views_finished(self):
        self._views_task = None
        # Сортировка завершилась сама — возвращаем кнопки в обычное состояние.
        self.btn_cancel.setEnabled(False)
        self.btn_search.setEnabled(True)
        self._resort_by_views(done=True)
        # Дозагрузка карточек закончилась — сразу сохраняем кеш индекса на диск.
        self._save_index_cache()

    # ── Постоянный кеш «индекса популярности» (просмотры/база/разбивка) ───────
    def _load_index_cache(self):
        """Подтягивает сохранённые ранее просмотры/базу индекса из файла, чтобы
        не дозапрашивать карточки заново при каждом запуске. Просроченные записи
        (старше _INDEX_CACHE_TTL) пропускаем — просмотры медленно растут."""
        if not _INDEX_CACHE_FILE:
            return
        try:
            with open(_INDEX_CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        now = time.time()
        for k, e in (data.get("entries") or {}).items():
            try:
                aid = int(k)
                ts = float(e.get("t", 0))
                if now - ts > _INDEX_CACHE_TTL:
                    continue
                self._views_cache[aid] = int(e.get("v", -1))
                self._index_base_cache[aid] = float(e.get("b", 0.0))
                comps = e.get("c") or []
                self._index_breakdown_cache[aid] = [
                    (str(c[0]), float(c[1]), int(c[2]))
                    for c in comps
                    if isinstance(c, (list, tuple)) and len(c) >= 3
                ]
                self._index_cache_ts[aid] = ts
            except (TypeError, ValueError):
                continue

    def _schedule_index_cache_save(self):
        try:
            self._index_cache_save_timer.start(1500)
        except Exception:
            pass

    def _save_index_cache(self):
        """Атомарно (через .tmp + os.replace) пишет кеш индекса на диск. Время
        записи (t) сохраняем исходное — иначе записи никогда не протухали бы."""
        if not _INDEX_CACHE_FILE:
            return
        now = time.time()
        entries = {}
        for aid, views in self._views_cache.items():
            comps = self._index_breakdown_cache.get(aid, [])
            entries[str(aid)] = {
                "v": int(views),
                "b": float(self._index_base_cache.get(aid, 0.0)),
                "c": [[lbl, wv, cnt] for (lbl, wv, cnt) in comps],
                "t": self._index_cache_ts.get(aid, now),
            }
            if len(entries) >= _INDEX_CACHE_MAX:
                break
        try:
            tmp = _INDEX_CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "entries": entries}, f,
                          ensure_ascii=False)
            os.replace(tmp, _INDEX_CACHE_FILE)
        except Exception:
            pass

    def _resort_by_views(self, done: bool = False):
        """Пересобирает список в порядке убывания просмотров (по кешу). Сохраняет
        позицию прокрутки и выделение, чтобы живая пересортировка не «дёргала»
        список к началу на каждом новом тайтле."""
        if not self._views_sort_active():
            return
        sb = self.list.verticalScrollBar()
        pos = sb.value()
        cur = self.list.currentItem()
        cur_id = cur.data(Qt.ItemDataRole.UserRole + 1) if cur else None
        self._results.sort(key=self._sort_key, reverse=True)
        self._fill_list(self._results)
        if cur_id is not None:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.ItemDataRole.UserRole + 1) == cur_id:
                    self.list.setCurrentItem(it)
                    break
        sb.setValue(min(pos, sb.maximum()))
        if done:
            n = len(self._results)
            self.lbl_status.setText(
                f"Найдено: {len(self._raw_results)}, после фильтра: {n} "
                f"({self._sort_phrase()})" if n else "Ничего не найдено.")

    def _fill_list(self, results: list):
        self.list.clear()
        self._anime_by_id = {a.id: a for a in results}
        for a in results:
            self._append_anime(a)
        self._load_visible_thumbs()

    def _row_text(self, a: "Anime") -> str:
        """Текст строки тайтла: название + краткая инфа. Просмотры (значок «глаз»
        + число) рисует _ViewsBadgeDelegate справа — в текст они не входят."""
        ct = self._content_type()
        unit = "гл." if ct == CONTENT_MANGA else "эп."
        parts = []
        if a.score:
            parts.append(f"★ {a.score:.2f}")
        parts.append(kind_label(ct, a.kind))
        # Дата выхода: по возможности с днём/месяцем или сезоном, иначе год.
        date_lbl = a.date_label or (str(a.year) if a.year else "")
        if date_lbl:
            parts.append(date_lbl)
        if a.episodes:
            parts.append(f"{a.episodes} {unit}")
        sub = "  ·  ".join(parts)
        text = a.title
        if a.name and a.name != a.title:
            text += f"\n{a.name}"
        text += f"\n{sub}"
        return text

    def _append_anime(self, a: "Anime"):
        """Добавляет один тайтл в список (обложка + название + краткая инфа).
        Обложку НЕ запрашиваем здесь — она грузится лениво для видимых строк
        (см. _load_visible_thumbs), иначе сотни параллельных запросов → 429."""
        self._anime_by_id[a.id] = a
        it = QListWidgetItem(self._row_text(a))
        it.setData(Qt.ItemDataRole.UserRole, a.url)
        it.setData(Qt.ItemDataRole.UserRole + 1, a.id)
        it.setData(Qt.ItemDataRole.UserRole + 2, a.title)  # для кнопки «копировать» (рус.)
        it.setData(Qt.ItemDataRole.UserRole + 3, a.name)   # для кнопки «копировать» (ориг.)
        it.setIcon(self._thumb_cache.get(a.id) or self._placeholder_icon())
        it.setSizeHint(QSize(0, _THUMB_H + 12))
        self.list.addItem(it)

    # ── Обложки (ленивая загрузка только видимых, с кешем) ──────────────────────
    def _placeholder_icon(self) -> QIcon:
        if self._placeholder is None:
            pm = QPixmap(_THUMB_W, _THUMB_H)
            pm.fill(QColor(C["surface3"]))
            self._placeholder = QIcon(pm)
        return self._placeholder

    def _load_visible_thumbs(self):
        """Запускает загрузку обложек ТОЛЬКО для строк, попадающих в видимую
        область списка. Уже загруженные (кеш) и уже запрошенные (pending) —
        пропускаем. Вызывается при наполнении списка и при прокрутке."""
        n = self.list.count()
        if not n:
            return
        vp = self.list.viewport().rect()
        for i in range(n):
            it = self.list.item(i)
            if it is None:
                continue
            r = self.list.visualItemRect(it)
            if r.bottom() < vp.top() or r.top() > vp.bottom():
                continue
            aid = it.data(Qt.ItemDataRole.UserRole + 1)
            if aid in self._thumb_cache or aid in self._thumb_pending:
                continue
            a = self._anime_by_id.get(aid)
            if a is None or not a.image_url:
                continue
            self._thumb_pending.add(aid)
            task = _ThumbTask(aid, a.image_url)
            task.signals.done.connect(self._on_thumb_loaded)
            self._pool.start(task)

    def _on_thumb_loaded(self, anime_id: int, data: bytes):
        self._thumb_pending.discard(anime_id)
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
                        # Один ответ нередко содержит несколько вариантов тайтла
                        # через « / » или « | » («Охотник x Охотник / Hunter x
                        # Hunter (1999)») — разбиваем, чтобы в исключения попал и
                        # русский, и ромадзи-вариант по отдельности. Делим только
                        # по разделителю С ПРОБЕЛАМИ, чтобы не рвать «Fate/stay».
                        for part in re.split(r"\s+[/|]\s+", ans or ""):
                            n = _norm_title(part)
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
            if gid is None:
                continue
            label = g.get("russian") or g.get("name") or str(gid)
            items.append((int(gid), label, genre_group(g)))
        items.sort(key=lambda x: x[1].lower())
        self._genres_cache[content_type] = items
        # Применяем отложенный (восстановленный из настроек) выбор — только те id,
        # что реально есть в списке этого типа контента.
        if content_type == self._content_type():
            valid = {gid for gid, _, _ in items}
            if self._pending_genres:
                self._sel_genres = [g for g in self._pending_genres if g in valid]
                self._pending_genres = []
            if self._pending_excl:
                self._excl_genres = [g for g in self._pending_excl if g in valid]
                self._pending_excl = []
            self._update_genres_btn()

    def _open_genre_picker(self):
        ct = self._content_type()
        items = self._genres_cache.get(ct)
        if not items:
            # Список ещё не пришёл — подгрузим и попросим повторить чуть позже.
            self._load_genres_async(ct)
            QMessageBox.information(
                self, "Жанры и темы",
                "Список жанров ещё загружается — повторите через секунду.")
            return
        dlg = _GenrePickerDialog(items, self._sel_genres, self._excl_genres, self)
        if dlg.exec():
            self._sel_genres = dlg.selected_ids()
            self._excl_genres = dlg.excluded_ids()
            self._update_genres_btn()

    def _update_genres_btn(self):
        """Подпись кнопки выбора жанров/тем: «Любые», сами названия (если выбран/
        исключён 1–2) или «Выбрано: N, исключено: M»."""
        inc = len(self._sel_genres)
        exc = len(self._excl_genres)
        if inc == 0 and exc == 0:
            self.btn_genres.setText("Любые")
            return
        lookup = {gid: label
                  for gid, label, _ in self._genres_cache.get(
                      self._content_type(), [])}
        if inc + exc <= 2:
            parts = [lookup.get(g, str(g)) for g in self._sel_genres]
            parts += [f"−{lookup.get(g, str(g))}" for g in self._excl_genres]
            self.btn_genres.setText(", ".join(parts))
        else:
            bits = []
            if inc:
                bits.append(f"выбрано: {inc}")
            if exc:
                bits.append(f"искл.: {exc}")
            self.btn_genres.setText(", ".join(bits))

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
            "views_max": int(self.sp_views_max.value()),
            "kind": self.cb_kind.currentData() or "",
            "status": self.cb_status.currentData() or "",
            "genres": list(self._sel_genres),
            "excl_genres": list(self._excl_genres),
            "year_from": self.sp_year_from.value(),
            "year_to": self.sp_year_to.value(),
            "ep_min": self.sp_ep_min.value(),
            "ep_max": self.sp_ep_max.value(),
            "excluded_packs": list(self._excluded_packs),
            "collapse_franchise": bool(self._collapse_franchise),
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
        self._collapse_franchise = bool(s.get("collapse_franchise", True))
        self.chk_collapse_fr.blockSignals(True)
        self.chk_collapse_fr.setChecked(self._collapse_franchise)
        self.chk_collapse_fr.blockSignals(False)
        self.sp_score_min.setValue(float(s.get("score_min", 0.0) or 0.0))
        self.sp_score_max.setValue(float(s.get("score_max", 10.0) or 10.0))
        oi = self.cb_order.findData(s.get("order", ORDER_VIEWS))
        if oi >= 0:
            self.cb_order.setCurrentIndex(oi)
        self.sp_views_max.setValue(
            int(s.get("views_max", _VIEWS_SORT_MAX) or _VIEWS_SORT_MAX))
        self._update_views_max_enabled()
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
        # Жанры/темы подтянутся после загрузки списка (см. _on_genres_loaded).
        # Поддерживаем и старый формат настроек (один «genre»: int).
        gids = s.get("genres")
        if gids is None:
            one = int(s.get("genre", 0) or 0)
            gids = [one] if one else []
        self._pending_genres = [int(x) for x in gids if x]
        self._pending_excl = [int(x) for x in (s.get("excl_genres") or []) if x]
        ct = self._content_type()
        if ct in self._genres_cache:
            valid = {gid for gid, _, _ in self._genres_cache[ct]}
            self._sel_genres = [g for g in self._pending_genres if g in valid]
            self._pending_genres = []
            self._excl_genres = [g for g in self._pending_excl if g in valid]
            self._pending_excl = []
        self._update_genres_btn()
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
        self.sp_views_max.setValue(_VIEWS_SORT_MAX)
        self._update_views_max_enabled()
        self.cb_kind.setCurrentIndex(0)
        self.cb_status.setCurrentIndex(0)
        self._sel_genres = []
        self._pending_genres = []
        self._excl_genres = []
        self._pending_excl = []
        self._update_genres_btn()
        self.sp_year_from.setValue(0)
        self.sp_year_to.setValue(0)
        self.sp_ep_min.setValue(0)
        self.sp_ep_max.setValue(0)
        self._excluded = set()
        self._excluded_bases = set()
        self._excluded_franchises = set()
        self._excluded_packs = []
        self._collapse_franchise = True
        self.chk_collapse_fr.blockSignals(True)
        self.chk_collapse_fr.setChecked(True)
        self.chk_collapse_fr.blockSignals(False)
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
