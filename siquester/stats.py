"""Statistics HTML parsing and dataset aggregation helpers."""

from .qt import *

_RE_STATS_PCT = re.compile(r'\((\d+)%\)')


_RE_PKG_VIEW  = re.compile(r'<div class="packageView">')


_RE_PKG_TITLE = re.compile(r'packageView__package[^>]*title="([^"]+)"')


_RE_STATS_BAR = re.compile(r'packageView__statsBar[^>]*>([^<]+)<')


_RE_PKG_SIZE  = re.compile(r'(\d+[\.,]\d+\s*[МмMmKkКк][Бб][Бб]?)')


_RE_RND_SEL   = re.compile(r'packageView__round selected[^>]*title="([^"]+)"')


_RE_THEME_DIV = re.compile(r'<div class="packageView__theme">')


_RE_TH_NAME   = re.compile(r'packageView__theme__name[^>]*>([^<]+)</div>')


_RE_Q_SPLIT = re.compile(r'<div class="packageView__question')


_RE_Q_PRICE = re.compile(r'packageView__question__price">([^<]+)</span>')


_RE_Q_TRIES = re.compile(r'class="tries"[^>]*>(\d+)%')


_RE_Q_RIGHT = re.compile(r'class="right"[^>]*>(\d+)%')


def parse_html(text):
    page_starts = [m.start() for m in _RE_PKG_VIEW.finditer(text)]
    if not page_starts: page_starts = [0]
    pkg_name, stats_str, pkg_size, rounds = "", "", "", []
    for i, start in enumerate(page_starts):
        end = page_starts[i+1] if i+1 < len(page_starts) else len(text)
        chunk = text[start:end]
        m = _RE_PKG_TITLE.search(chunk)
        if m: pkg_name = m.group(1).strip()
        m = _RE_STATS_BAR.search(chunk)
        if m: stats_str = m.group(1).strip()
        sm = _RE_PKG_SIZE.search(chunk)
        if sm and not pkg_size: pkg_size = sm.group(1).strip()
        sel = _RE_RND_SEL.search(chunk)
        round_name = sel.group(1).strip("「」").strip() if sel else f"Раунд {i+1}"
        themes = []
        for part in _RE_THEME_DIV.split(chunk)[1:]:
            nm = _RE_TH_NAME.search(part)
            name = nm.group(1).strip() if nm else "???"
            questions = []
            for q_html in _RE_Q_SPLIT.split(part)[1:]:
                pm = _RE_Q_PRICE.search(q_html)
                tm = _RE_Q_TRIES.search(q_html)
                rm = _RE_Q_RIGHT.search(q_html)
                if pm and tm and rm:
                    p_str = pm.group(1).strip()
                    price = int(p_str) if p_str.isdigit() else 0
                    questions.append({"price": price, "tries": int(tm.group(1)), "right": int(rm.group(1))})
            if questions: themes.append({"name": name, "questions": questions})
        if themes: rounds.append({"round_name": round_name, "themes": themes})
    return ({"pkg_name": pkg_name or "Неизвестный пакет", "stats": stats_str,
             "pkg_size": pkg_size, "rounds": rounds, "tab_id": 0,
             "total_duration_sec": 0} if rounds else None)


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
    '_RE_PKG_SIZE',
    '_RE_PKG_TITLE',
    '_RE_PKG_VIEW',
    '_RE_Q_PRICE',
    '_RE_Q_RIGHT',
    '_RE_Q_SPLIT',
    '_RE_Q_TRIES',
    '_RE_RND_SEL',
    '_RE_STATS_BAR',
    '_RE_STATS_PCT',
    '_RE_THEME_DIV',
    '_RE_TH_NAME',
    'ds_avgs',
    'get_hl',
    'parse_html',
    'stats_pct',
]
