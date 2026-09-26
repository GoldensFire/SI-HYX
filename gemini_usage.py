"""Persistent local request count; never presented as project-wide quota.

Считаем ТОЛЬКО те запросы, которые Google действительно обслужил: 429 и 5xx он
отклоняет, и в суточный лимит они не идут (см. gemini_api._post). Рядом с
счётчиком живёт память о том, что модель на сегодня исчерпана: без неё каждый
следующий прогон заново выяснял это ценой десятков отброшенных запросов.
"""
import hashlib
import json
import threading
import time
from datetime import datetime
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


def _digest(api_key):
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


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
        return _read().get(_key(api_key, model), 0)


def record_request(api_key, model):
    with _lock:
        data = _read()
        key = _key(api_key, model)
        data[key] = data.get(key, 0) + 1
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
        row = _read().get(_out_key(api_key, model))
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
