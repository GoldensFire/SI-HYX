# -*- coding: utf-8 -*-
"""YouTube candidate search for one anime song, through the bundled yt-dlp.

Замеренное на живом поиске, из чего выросла здешняя стратегия:

* `ytsearch20 --flat-playlist --dump-json` — 3.0 с и уже даёт длительность,
  канал, просмотры и заголовок. Полный `--dump-json` на каждое видео стоит
  3.6 с и ничего нужного не добавляет, поэтому его здесь нет.
* Запрос обязан опираться на НАЗВАНИЕ ПЕСНИ. «Rokka no Yuusha ending cover»
  вернул каверы ED1, ED2, ED3 и вдобавок кавер ОПЕНИНГА; «Nameless Heart Rokka
  no Yuusha cover» — почти одни нужные. Тип OP/ED в запросе только
  вспомогательный.
* Отдельные запросы piano/guitar/metal/orchestra НЕ нужны: общий запрос со
  словом cover сам вернул piano, fingerstyle, band, acoustic, violin,
  harmonica, 8-bit, Latino и русский кавер. Шесть лишних запросов стоили бы
  18 с и перекосили бы состав типов.

Ни сети напрямую, ни Qt: процессы запускает переданный `run`, как у
chiptune.service.ChiptuneService.
"""
from __future__ import annotations

import json

from cover_meta import normalize, screen

# Сколько результатов просить на каждой ступени. Двадцать против десяти стоят
# одинаково (запрос целиком — 3 с), поэтому на главной ступени берём щедро.
STAGE_LIMITS = (20, 10, 10)
SEARCH_TIMEOUT = 90
# Пауза между запросами внутри одного yt-dlp. Столько же советует он сам, когда
# уже упёрся в стенку («use --sleep-requests to add a delay between video
# requests to avoid exceeding the rate limit»). Замеренная цена — около секунды
# на ролик при извлечении, и она дешевле шести минут отказов: в живом прогоне
# без паузы ~50 загрузок в минуту держались ровно шесть минут, а потом YouTube
# закрылся на весь остаток пака (48 каверов из 96).
SLEEP_REQUESTS = 1.0

# Отказ по частоте запросов. Назван отдельно, потому что лечится не куками, а
# паузой: YouTube пускает снова сам, через несколько минут.
RATE_LIMIT = ("YouTube ограничил частоту запросов — слишком много загрузок "
              "подряд")
# Поломки, которые следующая песня не вылечит. Их нельзя перебирать
# кандидатами: ответ у YouTube на все запросы один и тот же, а каждая попытка
# стоит пользователю тайтла из каталога и полуминуты (см. EffectSlots.release
# и CoverService.audit). Строки — из сообщений самого yt-dlp.
FATAL_MARKS = (
    ("confirm you're not a bot", "YouTube требует подтвердить, что запросы "
                                 "шлёт не робот"),
    ("confirm you’re not a bot", "YouTube требует подтвердить, что запросы "
                                 "шлёт не робот"),
    ("sign in to confirm", "YouTube требует войти в аккаунт"),
    # Приметы стенки по частоте. Стоят ВЫШЕ общего совета про куки нарочно:
    # его («Use --cookies-from-browser or --cookies … how to manually pass
    # cookies») yt-dlp приписывает и к отказу по частоте, и стенка объяснялась
    # бы пользователю как «войдите в аккаунт» — а лечится она паузой.
    # Прозаическую примету («try again later») yt-dlp пишет в начале абзаца,
    # ссылку на вики — в конце; ловим обе, потому что в stderr трёх роликов
    # разом начало первого абзаца бывает уже срезано.
    ("try again later", RATE_LIMIT),
    ("isnt-available-try-again-later", RATE_LIMIT),
    ("exceeding the rate limit", RATE_LIMIT),
    ("http error 429", RATE_LIMIT),
    ("too many requests", RATE_LIMIT),
    # Общий совет про куки — последним: сам по себе он значит лишь «yt-dlp
    # предложил залогиниться», а какая именно стенка, сказано выше.
    ("pass-cookies-to-yt-dlp", "YouTube требует войти в аккаунт"),
    ("--cookies", "YouTube требует войти в аккаунт"),
    ("yt-dlp не найден", "yt-dlp не найден"),
    ("yt-dlp не ответил", "yt-dlp не отвечает"),
)


def trim_error(text, limit: int = 200) -> str:
    """Короткое сообщение об ошибке, в котором ОСТАЁТСЯ примета поломки.

    Хвост в 200 символов её терял: yt-dlp пишет «Sign in to confirm you’re not
    a bot» в начале абзаца, а дальше идут две ссылки на вики, и в кладовую
    попадало «w-do-i-pass-cookies-to-yt-dlp …» — то есть поломка всего поиска
    записывалась как неудача конкретного ролика и переставала его лечить.
    """
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    low = text.casefold()
    for mark, _reason in FATAL_MARKS:
        at = low.find(mark.casefold())
        if at >= 0:
            return text[at:at + limit]
    return text[-limit:]


def fatal_reason(error) -> str:
    """Почему сломан ВЕСЬ поиск каверов («» — обычная неудача одной песни)."""
    text = str(error or "").casefold()
    for mark, reason in FATAL_MARKS:
        if mark.casefold() in text:
            return reason
    return ""


def queries(song: dict) -> list[tuple[str, int, int]]:
    """[(строка поиска, сколько результатов, номер ступени)].

    Ступень 3 запускается только если после гейта пул оказался мал (см. gather):
    большинству песен хватает первых двух."""
    name = song.get("song") or ""
    if not name:
        # Без названия песни искать нечего: запрос по одному аниме приносит
        # каверы других его OP/ED, и отличить их можно только звуком — а
        # тратить на это загрузки незачем.
        return []
    anime = (song.get("anime") or [""])[0]
    artist = song.get("artist") or ""
    out = [(f"{name} {anime} cover".strip(), STAGE_LIMITS[0], 1),
           (f"{name} 歌ってみた".strip(), STAGE_LIMITS[1], 2)]
    if artist:
        out.append((f"{name} {artist} cover".strip(), STAGE_LIMITS[2], 3))
    return out


def _rows(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("id"):
            out.append(row)
    return out


def _clean(row: dict) -> dict:
    try:
        duration = int(float(row.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    try:
        views = int(row.get("view_count") or 0)
    except (TypeError, ValueError):
        views = 0
    # Лайки в плоской выдаче поиска бывают не всегда (YouTube отдаёт их не для
    # каждого ролика). Ноль здесь значит «неизвестно», а не «их нет»: отбор по
    # порогу такие записи не трогает (см. cover_meta.classify).
    try:
        likes = int(row.get("like_count") or 0)
    except (TypeError, ValueError):
        likes = 0
    return {"id": str(row.get("id") or ""),
            "title": str(row.get("title") or ""),
            "channel": str(row.get("channel") or row.get("uploader") or ""),
            "duration": duration, "views": views, "likes": likes,
            "live": str(row.get("live_status") or "") in ("is_live", "is_upcoming")}


def search(query: str, limit: int, run, ytdlp_cmd,
           timeout: float = SEARCH_TIMEOUT) -> list[dict]:
    """Один поисковый запрос. `run(cmd, timeout) -> (код, stdout, stderr)`."""
    return search_many([(query, limit)], run, ytdlp_cmd, timeout=timeout)


def search_many(specs, run, ytdlp_cmd,
                timeout: float = SEARCH_TIMEOUT) -> list[dict]:
    """Несколько запросов ОДНИМ процессом yt-dlp.

    Замер на живом поиске (bin/yt-dlp.exe, Windows): пустой запуск — 1.6 с,
    один `ytsearch20` — 2.7 с, два запроса в одном процессе — 3.3 с, три — 4.0 с.
    Порознь те же два стоили бы 4.9 с, три — 7.1 с: самозапуск exe-шника
    пересиливает саму сеть, и платить его на каждую ступень незачем. Выдача
    построчная, ступени в ней перемешаны — и не надо: gather сливает находки
    в один пул.
    """
    pairs = [(str(q).strip(), max(1, int(n))) for q, n in specs
             if str(q).strip()]
    if not pairs or not ytdlp_cmd:
        return []
    cmd = list(ytdlp_cmd) + [f"ytsearch{n}:{q}" for q, n in pairs]
    cmd += ["--flat-playlist", "--dump-json", "--no-warnings",
            "--sleep-requests", str(SLEEP_REQUESTS),
            "--socket-timeout", "20", "--retries", "3"]
    code, out, err = run(cmd, float(timeout) * len(pairs))
    if code and not out:
        raise RuntimeError(trim_error(err or "yt-dlp не ответил"))
    return [_clean(r) for r in _rows(out)]


def dedup(rows) -> list[dict]:
    """Убирает перезаливы и трансляции.

    Одного id мало: тот же кавер лежит у канала в нескольких копиях («… [HD]»,
    «… reupload»), а нормализованный заголовок у них совпадает.

    Правила «тот же канал плюс близкая длительность» здесь НЕТ нарочно: на 722
    собранных результатах оно не убрало ни одной строки, зато схлопывало бы
    разные каверы плодовитого канала — а такие каналы нам и нужны."""
    seen_id, seen_title = set(), set()
    out = []
    for row in rows:
        vid = row.get("id")
        live = row.get("live") or str(row.get("live_status") or "") in (
            "is_live", "is_upcoming")
        if not vid or vid in seen_id or live:
            continue
        key_title = (normalize(row.get("title")), normalize(row.get("channel")))
        if key_title in seen_title:
            continue
        seen_id.add(vid)
        seen_title.add(key_title)
        out.append(row)
    return out


def gather(song: dict, run, ytdlp_cmd, *, limit: int = 12, min_pool: int = 5,
           stopped=lambda: False, log=lambda message: None) -> dict:
    """Поиск + метаданный гейт.

    {"pool": принятые, "rejected": отклонённые, "queries": запросы,
     "rows": ВСЕ находки без дублей, "found": сколько их}. Третья ступень
     поиска идёт в дело только когда пула не хватает: обычно это лишние 3 с на
     ровном месте.

    "rows" отдаётся целиком ради кладовой (cover_cache): она хранит сырые
    заголовки и пересчитывает гейт при чтении, поэтому правка словаря правил
    действует на уже собранные находки — а pool с rejected обрезаны лимитом."""
    raw: list[dict] = []
    used: list[str] = []
    pool: list[dict] = []
    rejected: list[dict] = []
    plan = queries(song)
    # Ступени 1 и 2 идут ВМЕСТЕ одним процессом: обе выполнялись всегда, а
    # порознь платили лишний самозапуск yt-dlp (см. search_many). Ступень 3
    # по-прежнему запускается только при пустом пуле, поэтому её отделяем.
    for batch in ([plan[:2], plan[2:]] if len(plan) > 2 else [plan]):
        if not batch or stopped():
            break
        if batch[0][2] == 3 and len(pool) >= min_pool:
            break
        raw.extend(search_many([(q, n) for q, n, _s in batch], run, ytdlp_cmd))
        used.extend(q for q, _n, _s in batch)
        pool, rejected = screen(dedup(raw), song, limit=limit)
        log(f"Поиск каверов «{song.get('song')}»: {len(raw)} результатов, "
            f"годных {len(pool)}")
    rows = dedup(raw)
    return {"pool": pool, "rejected": rejected, "queries": used,
            "rows": rows, "found": len(rows)}
