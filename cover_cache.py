# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
"""Что уже известно про каверы одной композиции: находки, вердикты, история.

Ключ — annSongId, то есть КОМПОЗИЦИЯ, а не аниме: один и тот же опенинг стоит
в двух сезонах, и каверы у него общие.

Решения формата — из замеров, а не из вкуса:

* Файл НА КАЖДУЮ ПЕСНЮ, а не один общий. Список годных 20-секундных окон
  занимает 16.6 КиБ на песню (замер на стенде: 113 подтверждённых каверов по 15
  песням, медиана 69 окон на кавер). Общий файл на 200 песен весил бы 3.3 МБ и
  переписывался бы целиком на каждый вердикт — а вердиктов за один пак
  двести. Здесь запись стоит ровно свою песню.
* Окна хранятся ПОЛНОСТЬЮ, хотя прореживание до 3 с ужало бы файл до 6.0 КиБ.
  Шаг перебора окон — 1 с, и ровно на столько же рассчитан допуск, с которым
  cover_match.choose подбирает окно под trim_start оригинала. Прореженный
  список промахивался бы мимо этого допуска, и у кавера звучала бы не та часть
  песни, что у оригинала, — ради 10 КиБ на песню такое не меняют.
* Хранится СЫРОЙ счёт (norm), а решение «подходит» пересчитывается при чтении
  по текущему порогу cover_match. Иначе правка порога стоила бы повторной
  загрузки и разбора всех кандидатов (1.3 с ЦПУ и ~1.2 с сети на каждого).
  Сам признак обесценивает только смена способа СЧИТАТЬ хрому — на это есть
  AUDIO_VERSION.
* Гейт по заголовку тоже не хранится: он пересчитывается из сохранённых
  заголовков (cover_meta.screen — чистый текст, микросекунды), поэтому
  улучшение словаря правил действует на уже собранный кэш сразу.

Qt здесь нет нарочно: модуль зовут и генератор, и вкладка, и тесты.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import cover_match as match
from cover_meta import WEAK_LIMIT, screen

try:
    from config import CONFIG_DIR
except Exception:  # pragma: no cover — модуль должен жить и без приложения
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".si-hyx")

# Папка рядом с настройками — там же, где кладовая обложек и память о кадрах.
CACHE_DIR = os.path.join(CONFIG_DIR, "animepack_covers")

DAY = 86400.0
# Через сколько дней ищем заново. На YouTube каверы появляются, а не исчезают:
# месяц — это компромисс между «пак не повторяется» и шестью секундами поиска.
SEARCH_TTL_DAYS = 30
# Потолок кладовой. Песня весит 16.6 КиБ вместе с окнами, хрома эталона — ещё
# около 20 КиБ (.npy 90-секундного эталона), так что 256 МБ хватает на тысячи
# композиций; вылезли — выбрасываем самые давние по времени обращения.
CACHE_MB = 256
# Чем считалась хрома. Меняется ВМЕСТЕ со способом её считать (cover_audio):
# вердикты прошлой версии просто перестают засчитываться и считаются заново.
AUDIO_VERSION = "chroma-2"
# Сколько использованных окон помним на ролик и сколько раз прощаем неудачную
# загрузку, прежде чем перестать её пробовать.
USED_LIMIT = 64
FAIL_LIMIT = 3
# Через сколько дней осечки загрузки забываются. Срок нужен потому, что причина
# у них чаще временная, чем ролика: YouTube режет по частоте запросов и отвечает
# «Video unavailable» живым роликам тоже. Без срока один такой прогон вычёркивал
# кандидата НАВСЕГДА — а поле `last` писалось и не читалось никем. Двое суток
# переживают и стенку по частоте (снимается за минуты), и суточный бан по IP.
FAIL_TTL_DAYS = 2

_LOCK = threading.Lock()
_SAFE = re.compile(r"[^a-z0-9_-]+")


# ── файлы ────────────────────────────────────────────────────────────────
def _name(song_id) -> str:
    return _SAFE.sub("_", str(song_id or "").strip().lower()).strip("_")


def path(song_id) -> str:
    """Файл композиции («» — ключа нет)."""
    name = _name(song_id)
    return os.path.join(CACHE_DIR, f"{name}.json") if name else ""


def chroma_path(song_id) -> str:
    """Файл с хромой эталона («» — ключа нет)."""
    name = _name(song_id)
    return os.path.join(CACHE_DIR, f"{name}.npy") if name else ""


def marks_path(song_id) -> str:
    """Файл с созвездием пиков эталона («» — ключа нет)."""
    name = _name(song_id)
    return os.path.join(CACHE_DIR, f"{name}.marks.npy") if name else ""


def load(song_id) -> dict:
    """Всё, что известно про каверы этой композиции ({} — ничего)."""
    file = path(song_id)
    if not file:
        return {}
    try:
        with open(file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    try:
        os.utime(file, None)
    except OSError:  # pragma: no cover — файл мог исчезнуть между делом
        pass
    return data


def save(song_id, entry) -> bool:
    """Перезаписывает файл композиции. Не вышло — не беда: кэш только ускоряет
    работу, и генератор соберёт пак без него."""
    file = path(song_id)
    if not file:
        return False
    body = dict(entry, updated=int(time.time()))
    tmp = f"{file}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
        os.replace(tmp, file)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _part(entry, name) -> dict:
    value = entry.get(name)
    return dict(value) if isinstance(value, dict) else {}


def _expired(when, ttl_days: float = FAIL_TTL_DAYS) -> bool:
    """Осечка загрузки просрочена (и её пора забыть)."""
    when = float(when or 0.0)
    if not when:
        return True
    return (time.time() - when) > max(0.0, float(ttl_days)) * DAY


def stale(entry, ttl_days: float = SEARCH_TTL_DAYS) -> bool:
    """Пора ли искать заново (пустой кэш — конечно, пора)."""
    searched = float(entry.get("searched") or 0.0)
    if not searched or not entry.get("videos"):
        return True
    return (time.time() - searched) > max(0.0, float(ttl_days)) * DAY


# ── запись ───────────────────────────────────────────────────────────────
def remember_search(song_id, rows, *, queries=(), found=0, song="") -> dict:
    """Кладёт СЫРЫЕ находки поиска (гейт пересчитается при чтении)."""
    with _LOCK:
        entry = load(song_id)
        videos = _part(entry, "videos")
        for row in rows or ():
            vid = str(row.get("id") or "")
            if not vid:
                continue
            videos[vid] = {"title": str(row.get("title") or ""),
                           "channel": str(row.get("channel") or ""),
                           "duration": int(row.get("duration") or 0),
                           "views": int(row.get("views") or 0),
                           "likes": int(row.get("likes") or 0)}
        entry.update(song_id=str(song_id), videos=videos,
                     song=str(song or entry.get("song") or ""),
                     queries=[str(q) for q in queries],
                     found=int(found or len(videos)),
                     searched=int(time.time()))
        save(song_id, entry)
        return entry


def remember_audio(song_id, video_id, verdict, good=(), want=None) -> dict:
    """Вердикт звука по одному ролику вместе со списком годных окон.

    `want` — на какую ДЛИНУ отрезка эти окна посчитаны. Хранится потому, что
    длину задаёт пользователь (audio_cut), а окна под неё и подобраны: под
    более короткий отрезок годится и длинное окно (берём его начало), а под
    более длинный — нет, и такого кандидата придётся послушать заново."""
    vid = str(video_id or "")
    if not vid:
        return {}
    with _LOCK:
        entry = load(song_id)
        audio = _part(entry, "audio")
        audio[vid] = {
            "version": AUDIO_VERSION, "checked": int(time.time()),
            "score": round(float(verdict.get("score") or 0.0), 2),
            "norm": round(float(verdict.get("norm") or 0.0), 3),
            "shift": int(verdict.get("shift") or 0),
            "tempo": round(float(verdict.get("tempo") or 0.0), 3),
            "closeness": round(float(verdict.get("closeness") or 0.0), 3),
            # Сколько пар отпечатка совпало с эталоном на одном сдвиге: это
            # «внутри играет сам оригинал», и хранится оно СЫРЫМ числом — как
            # и norm, чтобы правка порога не стоила повторной загрузки.
            "inside": round(float(verdict.get("inside") or 0.0), 3),
            "reason": str(verdict.get("reason") or ""),
            "want": round(float(want if want is not None
                                else match.WANT_SECONDS), 2),
            "windows": [[w["at"], w["density"], w["cover"][0], w["cover"][1]]
                        for w in (good or ())],
        }
        entry["audio"] = audio
        save(song_id, entry)
        return entry


def remember_use(song_id, video_id, window_at=None, when=None) -> dict:
    """Ролик ушёл в пак: считаем использование и помним занятое окно."""
    vid = str(video_id or "")
    if not vid:
        return {}
    with _LOCK:
        entry = load(song_id)
        use = _part(entry, "use")
        row = dict(use.get(vid) or {})
        spots = [float(x) for x in (row.get("at") or [])]
        if window_at is not None:
            spots.append(round(float(window_at), 2))
        use[vid] = {"n": int(row.get("n") or 0) + 1,
                    "last": int(when if when is not None else time.time()),
                    "at": spots[-USED_LIMIT:]}
        entry["use"] = use
        entry["last"] = vid
        save(song_id, entry)
        return entry


def remember_failure(song_id, video_id, reason="") -> dict:
    """Ролик не скачался или не разобрался: после FAIL_LIMIT перестаём брать."""
    vid = str(video_id or "")
    if not vid:
        return {}
    with _LOCK:
        entry = load(song_id)
        fail = _part(entry, "fail")
        row = dict(fail.get(vid) or {})
        # Прошлые осечки, просроченные по FAIL_TTL_DAYS, в счёт не идут: три
        # штуки должны означать «ролик не даётся раз за разом», а не «не дался
        # однажды в марте, однажды в мае и однажды сегодня».
        before = 0 if _expired(row.get("last")) else int(row.get("n") or 0)
        fail[vid] = {"n": before + 1,
                     "last": int(time.time()), "reason": str(reason or "")[:200]}
        entry["fail"] = fail
        save(song_id, entry)
        return entry


# ── чтение ───────────────────────────────────────────────────────────────
def _merge(entry, row) -> dict:
    """Строка поиска + вердикт звука + история использования."""
    vid = str(row.get("id") or "")
    audio = dict(_part(entry, "audio").get(vid) or {})
    use = dict(_part(entry, "use").get(vid) or {})
    fail = dict(_part(entry, "fail").get(vid) or {})
    windows = [{"at": float(w[0]), "density": float(w[1]),
                "cover": (float(w[2]), float(w[3]))}
               for w in (audio.get("windows") or ()) if len(w) >= 4]
    return dict(row, checked=audio.get("version") == AUDIO_VERSION,
                norm=float(audio.get("norm") or 0.0),
                score=float(audio.get("score") or 0.0),
                shift=int(audio.get("shift") or 0),
                tempo=float(audio.get("tempo") or 0.0),
                closeness=float(audio.get("closeness") or 0.0),
                inside=float(audio.get("inside") or 0.0),
                audio_reason=str(audio.get("reason") or ""),
                want=float(audio.get("want") or match.WANT_SECONDS),
                windows=windows, used=[float(x) for x in (use.get("at") or ())],
                uses=int(use.get("n") or 0),
                last_used=float(use.get("last") or 0.0),
                fails=0 if _expired(fail.get("last")) else int(fail.get("n") or 0),
                failed_at=float(fail.get("last") or 0.0))


def screened(entry, song, *, limit: int = 12,
             weak_limit: int = WEAK_LIMIT) -> tuple[list, list]:
    """(пул с приклеенной историей, отвергнутые гейтом).

    Гейт считается ЗАНОВО из сохранённых заголовков: он ничего не стоит, а
    правки словаря правил так действуют на уже собранный кэш."""
    rows = [dict(meta, id=vid)
            for vid, meta in sorted(_part(entry, "videos").items())]
    pool, rejected = screen(rows, song, limit=limit, weak_limit=weak_limit)
    return [_merge(entry, row) for row in pool], rejected


def confirmed(rows, want=None) -> list[dict]:
    """Кого звук признал той же композицией — по ТЕКУЩЕМУ порогу.

    `want` — нужная длина отрезка: окна, посчитанные на более КОРОТКИЙ кусок,
    не годятся (за их концом выравнивания уже никто не проверял)."""
    out = []
    for row in rows:
        if not (row.get("checked") and row.get("windows")):
            continue
        if float(row.get("norm") or 0.0) < match.floor_for(row.get("strength")):
            continue
        # Внутри записи играет сам оригинал (игра под минусовку, гитара поверх
        # мастера). Решение пересчитывается здесь, а не замораживается при
        # проверке: порог в cover_fingerprint может поменяться.
        if match.original_inside(row.get("inside")):
            continue
        if want and float(row.get("want") or 0.0) + 1e-6 < float(want):
            continue
        out.append(row)
    return out


def unchecked(rows, fail_limit: int = FAIL_LIMIT, want=None) -> list[dict]:
    """Кого стоит послушать: кого не слушали вовсе — и кого слушали под отрезок
    короче нужного. Отвергнутых звуком не переслушиваем: их вердикт от длины
    отрезка не зависит вовсе.

    Осечки загрузки считаются только свежие (FAIL_TTL_DAYS): просроченные
    _merge уже обнулил, и ролик снова попадает в очередь на прослушивание."""
    out = []
    for row in rows:
        if int(row.get("fails") or 0) >= fail_limit:
            continue
        if not row.get("checked"):
            out.append(row)
        elif (want and row.get("windows")
              and float(row.get("want") or 0.0) + 1e-6 < float(want)):
            out.append(row)
    return out


def last_used(entry) -> str:
    """Ролик, ушедший в пак последним: его подряд не повторяем."""
    return str(entry.get("last") or "")


# ── хрома эталона ────────────────────────────────────────────────────────
def ref_chroma(song_id):
    """Хрома эталона из кладовой (None — не считали). 0.8 с и не меняется."""
    file = chroma_path(song_id)
    if not file or not os.path.isfile(file):
        return None
    try:
        import numpy as np
        data = np.load(file)
    except (OSError, ValueError, ImportError):
        return None
    if getattr(data, "ndim", 0) != 2 or data.shape[1] != 12:
        return None
    try:
        os.utime(file, None)
    except OSError:  # pragma: no cover
        pass
    return data


def ref_marks(song_id):
    """Созвездие пиков эталона (None — не считали).

    Нужно, чтобы отличить чужое исполнение от записи, в которую подмешан сам
    оригинал (см. cover_fingerprint). Хранится рядом с хромой и стареет вместе
    с ней."""
    file = marks_path(song_id)
    if not file or not os.path.isfile(file):
        return None
    try:
        import numpy as np
        data = np.load(file)
    except (OSError, ValueError, ImportError):
        return None
    if getattr(data, "ndim", 0) != 2 or data.shape[1] != 2:
        return None
    try:
        os.utime(file, None)
    except OSError:  # pragma: no cover
        pass
    return data


def put_ref_marks(song_id, points) -> bool:
    """Кладёт созвездие пиков эталона рядом с хромой."""
    return _put_array(marks_path(song_id), points)


def put_ref_chroma(song_id, chroma) -> bool:
    """Кладёт хрому эталона рядом с находками."""
    return _put_array(chroma_path(song_id), chroma)


def _put_array(file, values) -> bool:
    """Массив в файл кладовой, целиком или никак."""
    if not file or values is None or not len(values):
        return False
    tmp = f"{file}.{os.getpid()}.{threading.get_ident()}.npy"
    try:
        import numpy as np
        os.makedirs(CACHE_DIR, exist_ok=True)
        np.save(tmp, values)
        os.replace(tmp, file)
        return True
    except (OSError, ValueError, ImportError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


# ── обслуживание кладовой ────────────────────────────────────────────────
_EXTS = (".json", ".npy")


def _rows() -> list[tuple[str, int, float]]:
    out = []
    try:
        entries = list(os.scandir(CACHE_DIR))
    except OSError:
        return out
    for item in entries:
        if not item.is_file():
            continue
        if os.path.splitext(item.name)[1].lower() not in _EXTS:
            continue
        try:
            st = item.stat()
        except OSError:  # pragma: no cover
            continue
        out.append((item.path, int(st.st_size),
                    float(st.st_atime or st.st_mtime)))
    return out


def prune(limit_mb=None) -> int:
    """Выбрасывает самые давние файлы, пока кладовая не влезет в потолок."""
    limit = int(limit_mb if limit_mb is not None else CACHE_MB)
    if limit <= 0:
        return 0
    rows = _rows()
    total = sum(size for _p, size, _t in rows)
    cap = limit * 1024 * 1024
    gone = 0
    for file, size, _t in sorted(rows, key=lambda r: r[2]):
        if total <= cap:
            break
        try:
            os.remove(file)
        except OSError:  # pragma: no cover — файл мог быть занят
            continue
        total -= size
        gone += 1
    return gone


def clear() -> int:
    """Забыть все каверы (кнопка в настройках)."""
    gone = 0
    for file, _size, _t in _rows():
        try:
            os.remove(file)
            gone += 1
        except OSError:  # pragma: no cover
            continue
    return gone


def stats() -> tuple[int, int]:
    """(сколько композиций, сколько байт) — для подписи в настройках."""
    rows = _rows()
    songs = sum(1 for file, _s, _t in rows if file.lower().endswith(".json"))
    return songs, sum(size for _p, size, _t in rows)
