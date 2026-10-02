"""Persistent local request count; never presented as project-wide quota.

Локальная оценка расхода включает ошибки 400/5xx и таймауты чтения:
отсутствие ответа не гарантирует сохранение квоты. Отклонённые 429 и ошибки
авторизации исключаются. Фактический расход всего проекта показывает Google.
Рядом хранится память об исчерпанной квоте; перегрузка туда не записывается.
"""
import hashlib
import json
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

_lock = threading.Lock()
# Квота бесплатного тарифа считается по тихоокеанскому дню — так её показывает
# и сам AI Studio.
_TZ = ZoneInfo("America/Los_Angeles")
# Метку «исчерпано», у которой не было явного суточного признака (а значит, это
# мог быть минутный лимит), перепроверяем через час: цена ошибки иначе — целый
# день без модели.
SOFT_RECHECK = 3600.0


def _path():
    import config
    return Path(config.SETTINGS_FILE).with_name("gemini_usage.json")


@lru_cache(maxsize=32)
def _digest(api_key):
    # Это идентификатор счётчика, не пароль для входа. PBKDF2 защищает
    # сохранённый отпечаток и при коротком ключе; постоянная соль отделяет
    # его от других назначений. Дорогой расчёт делаем один раз на ключ.
    value = hashlib.pbkdf2_hmac(
        "sha256", api_key.encode(), b"SI-HYX/Gemini/request-counter/v2",
        600_000, dklen=16)
    return "v2-" + value.hex()


def _stored(data, key, default=0):
    """При смене отпечатка не забываем уже потраченную суточную квоту.

    Старые отпечатки необратимы. До конца текущего дня учитываем их
    консервативно: суммарный расход модели и любую действующую блокировку.
    После первой записи новый счётчик уже включает этот расход.
    """
    if key in data:
        return data[key]
    parts = key.split(":")
    legacy = []
    for old_key, value in data.items():
        old = old_key.split(":")
        if len(old) != len(parts) or old[:-2] != parts[:-2] or old[-1] != parts[-1]:
            continue
        digest = old[-2]
        if len(digest) == 16 and all(c in "0123456789abcdef" for c in digest):
            legacy.append(value)
    if key.startswith("out:"):
        if any(row for row in legacy if not isinstance(row, dict)):
            return True
        rows = [row for row in legacy if isinstance(row, dict)]
        return {"hard": any(row.get("hard") for row in rows),
                "at": max((row.get("at", 0) for row in rows
                           if isinstance(row.get("at", 0), (int, float))),
                          default=0)} if rows else default
    return sum(value for value in legacy if type(value) is int) or default


def _key(api_key, model):
    day = datetime.now(_TZ).date().isoformat()
    return f"{day}:{_digest(api_key)}:{model}"


def _out_key(api_key, model):
    return "out:" + _key(api_key, model)


def _cap_key(api_key, model):
    """Узнанный суточный потолок модели — он же и завтра тот же."""
    return f"cap:{_digest(api_key)}:{model}"


def _read():
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data):
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass


def requests_today(api_key, model):
    with _lock:
        return _stored(_read(), _key(api_key, model))


def record_request(api_key, model):
    with _lock:
        data = _read()
        key = _key(api_key, model)
        data[key] = _stored(data, key) + 1
        _write(data)


def mark_exhausted(api_key, model, hard=True, cap=0):
    """Запоминает, что модель на сегодня кончилась.

    hard — в ответе сервера был явный суточный признак («per day»). Неявную
    метку (мог быть и минутный лимит) через час снимаем сами."""
    with _lock:
        data = _read()
        data[_out_key(api_key, model)] = {"at": time.time(), "hard": bool(hard)}
        if int(cap or 0) > 0:
            data[_cap_key(api_key, model)] = int(cap)
        _write(data)


def exhausted_today(api_key, model):
    """Известно ли уже, что на сегодня эта модель кончилась."""
    with _lock:
        row = _stored(_read(), _out_key(api_key, model))
    if not isinstance(row, dict):
        return bool(row)
    if row.get("hard"):
        return True
    try:
        return time.time() - float(row.get("at") or 0) < SOFT_RECHECK
    except (TypeError, ValueError):
        return False


def daily_cap(api_key, model):
    """Суточный потолок, названный самим сервером (0 — неизвестен)."""
    with _lock:
        try:
            return int(_read().get(_cap_key(api_key, model), 0) or 0)
        except (TypeError, ValueError):
            return 0
