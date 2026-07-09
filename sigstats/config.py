"""Пути, константы и группировка пакетов по длине."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

# Флаг для subprocess.run/Popen (ffprobe) — не мигать чёрным окном консоли при
# вызове из GUI на Windows.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0

# ── Пути ──────────────────────────────────────────────────────────────────────
# BASE_DIR по умолчанию — папка проекта (для автономного SiGStats). Хост-приложение
# (например, вкладка «Поиск пакетов» в SI-HYX) переопределяет её переменной
# окружения SIGSTATS_HOME ДО первого импорта этого модуля: там БД/пакеты/медиа не
# могут лежать рядом с исходниками — см. пояснение в sigstats_tab.py, где
# переменная выставляется в %APPDATA%\unified_media_tool\sigstats.
_home_override = os.environ.get("SIGSTATS_HOME")
BASE_DIR = Path(_home_override) if _home_override else Path(__file__).resolve().parent.parent
# путь к БД можно переопределить ещё точнее переменной SIGSTATS_DB (так делают
# тесты — отдельный файл, чтобы не трогать рабочую базу)
DB_PATH = Path(os.environ.get("SIGSTATS_DB", BASE_DIR / "sigstats.db"))
PACKAGES_DIR = BASE_DIR / "packages"                   # скачанные .siq
MEDIA_DIR = BASE_DIR / "media"                         # извлечённый медиаконтент

# Путь к ffprobe — хост-приложение может подставить свой bundled-бинарник
# (см. sigstats_tab.py); по умолчанию ищем в системном PATH (см. siq.py).
FFPROBE_PATH: str | None = None

# Чёрный список авторов: паки этих авторов пропускаются при сборе и не
# показываются в уже собранной таблице. Хранится рядом с БД (см. BASE_DIR).
BLACKLIST_PATH = BASE_DIR / "author_blacklist.json"


def load_author_blacklist() -> list[str]:
    import json
    try:
        if BLACKLIST_PATH.exists():
            return json.loads(BLACKLIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def save_author_blacklist(names: list[str]) -> None:
    import json
    ensure_dirs()
    BLACKLIST_PATH.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")


# Список «уже сыгранных» пакетов (по id в БД) — пользователь убирает их из
# основного списка поиска, не удаляя из БД. Хранится рядом с БД (см. BASE_DIR),
# как и чёрный список авторов.
PLAYED_PATH = BASE_DIR / "played_packages.json"


def load_played_packages() -> list[int]:
    import json
    try:
        if PLAYED_PATH.exists():
            return json.loads(PLAYED_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def save_played_packages(ids: list[int]) -> None:
    import json
    ensure_dirs()
    PLAYED_PATH.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")


# Чёрный список конкретных пакетов (по id в БД) — пользователь просто не хочет
# их видеть (в отличие от «сыгранных», это не про прогресс, а про «не
# интересно/не нужно»). В отличие от чёрного списка АВТОРОВ (author_blacklist,
# который ещё и пропускает паки при сборе), этот список только скрывает уже
# собранные паки из таблицы — на сбор не влияет.
PKG_BLACKLIST_PATH = BASE_DIR / "package_blacklist.json"


def load_package_blacklist() -> list[int]:
    import json
    try:
        if PKG_BLACKLIST_PATH.exists():
            return json.loads(PKG_BLACKLIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def save_package_blacklist(ids: list[int]) -> None:
    import json
    ensure_dirs()
    PKG_BLACKLIST_PATH.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")


# Кэш «докуда долистали» обход каталога — чтобы повторный сбор с теми же
# режимом/темой продолжал со страницы, на которой остановились в прошлый раз,
# а не листал каталог заново с первой страницы.
SEARCH_CACHE_PATH = BASE_DIR / "search_page_cache.json"


def _search_cache_key(mode: str, category_slug: str | None) -> str:
    return f"{mode}:{category_slug or '-'}"


def load_search_cache() -> dict:
    import json
    try:
        if SEARCH_CACHE_PATH.exists():
            return json.loads(SEARCH_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def get_cached_page(mode: str, category_slug: str | None) -> int:
    return int(load_search_cache().get(_search_cache_key(mode, category_slug), 1))


def set_cached_page(mode: str, category_slug: str | None, page: int) -> None:
    import json
    cache = load_search_cache()
    cache[_search_cache_key(mode, category_slug)] = page
    ensure_dirs()
    SEARCH_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


# Настройки UI вкладки (радиокнопки/чекбоксы/слайдеры/комбобоксы фильтров и
# сбора данных) — чтобы после перезапуска приложения не настраивать всё заново.
UI_SETTINGS_PATH = BASE_DIR / "ui_settings.json"


def load_ui_settings() -> dict:
    import json
    try:
        if UI_SETTINGS_PATH.exists():
            return json.loads(UI_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_ui_settings(data: dict) -> None:
    import json
    ensure_dirs()
    UI_SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# Категории sibrowser (отображаемое имя → слаг для /categories/<слаг>).
# Каждая карточка несёт максимум одну категорию с процентом (доминирующая
# тема пака), слаг берётся из ссылки rel="category" при парсинге.
CATEGORY_SLUGS = {
    "Видеоигры": "videogames",
    "Аниме": "anime",
    "Музыка": "music",
    "Кино": "movies",
    "Обществ. н.": "social",
    "Мемы": "meme",
}

# ── Внешние сервисы ───────────────────────────────────────────────────────────
SIBROWSER_BASE = "https://www.sibrowser.ru"
STATS_BASE = "https://vladimirkhil.com/sistatistics/api/v1"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SiGStats/1.0"
REQUEST_TIMEOUT = 60          # сек
SCRAPE_DELAY = 0.7            # пауза между запросами к sibrowser, сек
STATS_DELAY = 0.25           # пауза между запросами к статистике, сек

# ── Группы по количеству вопросов ─────────────────────────────────────────────
# Короткие ≤80 | Средние 81–120 | Полные 121–170 | Большие 171+
LENGTH_GROUPS = ["Короткие", "Средние", "Полные", "Большие", "Неизвестно"]


def length_group(question_count: int | None) -> str:
    if question_count is None or question_count <= 0:
        return "Неизвестно"
    if question_count <= 80:
        return "Короткие"
    if question_count <= 120:
        return "Средние"
    if question_count <= 170:
        return "Полные"
    return "Большие"


# ── Пороги частоты тем (доля пакетов, где встречается тема) ────────────────────
RARE_THEME_MAX = 0.03        # < 3 % пакетов  → редкая
FREQUENT_THEME_MIN = 0.15    # > 15 % пакетов → частая


def ensure_dirs() -> None:
    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
