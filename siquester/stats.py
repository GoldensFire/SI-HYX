"""Stats dataset aggregation helpers."""

from .qt import *

_RE_STATS_PCT = re.compile(r'\((\d+)%\)')


def stats_pct(s): m = _RE_STATS_PCT.search(s); return float(m.group(1)) if m else 0.0


def ds_avgs(ds):
    """Return (avg_tries%, avg_right%) over all questions in ds.
    Uses a single generator pass — no intermediate list allocation."""
    n = t_sum = r_sum = 0
    for rd in ds["rounds"]:
        for th in rd["themes"]:
            for q in th["questions"]:
                n      += 1
                t_sum  += q.get("tries", 0)
                r_sum  += q.get("right", 0)
    if not n: return 0.0, 0.0
    return t_sum / n, r_sum / n


# Правила подсветки пакетов в списке по ключевому слову в названии:
# (ключевое_слово, фон, рамка, цвет_имени). Список пуст специально — раньше тут
# было захардкожено личное имя автора («GoldensFire»), что подсвечивало его
# собственные пакеты. Чтобы в коде не было персональных данных — список пуст
# (get_hl вернёт None, подсветки нет). При желании можно вынести в настройки.
# Правила подсветки пакетов: (ключевое_слово, фон, цвет_рамки, цвет_названия).
# Пакеты, чьё имя содержит ключевое слово, получают цветную рамку/фон в списке
# (как на 3-м скрине). ВНИМАНИЕ: имя автора здесь — личные данные в коде; если
# планируете публиковать репозиторий, вынесите список в настройки/локальный файл.
HIGHLIGHT_RULES: list = []


def get_hl(pkg):
    for kw,bg,bd,nc in HIGHLIGHT_RULES:
        if kw.lower() in pkg.lower(): return bg,bd,nc
    return None

__all__ = [
    'HIGHLIGHT_RULES',
    '_RE_STATS_PCT',
    'ds_avgs',
    'get_hl',
    'stats_pct',
]
