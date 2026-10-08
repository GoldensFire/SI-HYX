# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""settings.json: чтение, атомарная запись и снимки истории. Public namespace: utils."""
import utils as _api


def _settings_history_paths() -> list:
    """Снимки от самого свежего (.1) к самому старому (.5)."""
    return [f"{_api.SETTINGS_FILE}.{i}" for i in range(1, _api._SETTINGS_HISTORY + 1)]

_settings_history_paths.__module__ = _api.__name__
_api._settings_history_paths = _settings_history_paths

def _settings_candidates() -> list:
    """Все файлы, из которых можно поднять настройки — в порядке свежести."""
    return [_api.SETTINGS_FILE, _api.SETTINGS_FILE + ".bak"] + _api._settings_history_paths()

_settings_candidates.__module__ = _api.__name__
_api._settings_candidates = _settings_candidates

def _read_settings_file(path: str, retries: int = 3):
    """(данные, статус) для ОДНОГО файла настроек.

    Статусы: 'ok' — прочитан непустой словарь; 'missing' — файла нет;
    'corrupt' — открылся, но это не разбираемый непустой JSON-словарь;
    'locked' — файл ЕСТЬ, но открыть не удалось даже после повторов (занят
    другим процессом). Разница принципиальна: 'corrupt' — настройки в этом
    файле потеряны (можно брать копию), 'locked' — они целы и трогать диск
    нельзя."""
    for attempt in range(max(1, retries)):
        if not _api.os.path.exists(path):
            return None, "missing"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _api.json.load(f)
        except OSError:
            # Занятость файла — состояние ВРЕМЕННОЕ: ждём и пробуем ещё раз.
            _api.time.sleep(0.15 * (attempt + 1))
            continue
        except Exception:
            return None, "corrupt"       # битый JSON — повторять бессмысленно
        if isinstance(data, dict) and data:
            return data, "ok"
        return None, "corrupt"
    return None, "locked"

_read_settings_file.__module__ = _api.__name__
_api._read_settings_file = _read_settings_file

def load_settings_ex():
    """(настройки, статус). Статус нужен вызывающему, чтобы решить, можно ли
    вообще сохранять в этом запуске:

    'ok'        — прочитано штатно (settings.json или .bak);
    'recovered' — основной файл и .bak непригодны, подняли снимок из истории;
    'locked'    — файл существует, но занят: данные на диске ЦЕЛЫ, работаем на
                  дефолтах и НИЧЕГО не сохраняем (иначе затрём живые настройки);
    'empty'     — сохранённых настроек нет вообще (первый запуск)."""
    locked = False
    for i, path in enumerate(_api._settings_candidates()):
        # Повторы имеет смысл делать только для двух основных файлов: снимки
        # истории читаются лишь когда те уже признаны потерянными.
        data, status = _api._read_settings_file(path, retries=3 if i < 2 else 1)
        if status == "ok":
            if locked:
                # Более свежий файл существует и просто занят — его настройки
                # живы. Подняться на старой копии значит потом затереть ими
                # свежую версию, поэтому лучше вообще не сохранять этот запуск.
                return {}, "locked"
            return data, ("ok" if i < 2 else "recovered")
        if status == "locked":
            locked = True
    return ({}, "locked") if locked else ({}, "empty")

load_settings_ex.__module__ = _api.__name__
_api.load_settings_ex = load_settings_ex

def load_settings() -> dict:
    return _api.load_settings_ex()[0]

load_settings.__module__ = _api.__name__
_api.load_settings = load_settings

def settings_files_exist() -> bool:
    """Лежат ли на диске НЕПУСТЫЕ сохранённые настройки (основной файл, .bak
    или любой снимок истории).

    Нужна, чтобы отличить два совершенно разных случая пустого результата
    load_settings(): «первый запуск, сохранять ещё нечего» и «настройки есть, но
    прочитать их сейчас не вышло». Во втором случае сохранять поверх НЕЛЬЗЯ —
    см. main.py::_save_settings_now."""
    for path in _api._settings_candidates():
        try:
            if _api.os.path.exists(path) and _api.os.path.getsize(path) > 2:
                return True
        except Exception:
            continue
    return False

settings_files_exist.__module__ = _api.__name__
_api.settings_files_exist = settings_files_exist

def _replace_with_retry(src: str, dst: str, retries: int = 5) -> bool:
    """os.replace, переживающий кратковременную занятость файла (на Windows
    антивирус/индексатор держат только что записанный файл открытым, и замена
    падает с отказом в доступе). Раньше такой отказ молча терял сохранение."""
    for attempt in range(max(1, retries)):
        try:
            _api.os.replace(src, dst)
            return True
        except OSError:
            _api.time.sleep(0.1 * (attempt + 1))
        except Exception:
            return False
    return False

_replace_with_retry.__module__ = _api.__name__
_api._replace_with_retry = _replace_with_retry

def _snapshot_settings_history(current_text: str):
    """Сдвигает историю снимков и кладёт текущий (уже проверенный) файл в .1.
    Не чаще раза в _SETTINGS_SNAPSHOT_INTERVAL — сохранение дёргается на каждое
    изменение любого поля, копировать файл каждый раз незачем."""
    try:
        first = _api._settings_history_paths()[0]
        if _api.os.path.exists(first):
            if _api.time.time() - _api.os.path.getmtime(first) < _api._SETTINGS_SNAPSHOT_INTERVAL:
                return
            with open(first, "r", encoding="utf-8") as f:
                if f.read() == current_text:
                    return          # снимок уже такой же — не плодим копии
        paths = _api._settings_history_paths()
        for older, newer in zip(reversed(paths[1:]), reversed(paths[:-1])):
            if _api.os.path.exists(newer):
                _api._replace_with_retry(newer, older, retries=1)
        with open(first, "w", encoding="utf-8") as f:
            f.write(current_text)
    except Exception:
        pass

_snapshot_settings_history.__module__ = _api.__name__
_api._snapshot_settings_history = _snapshot_settings_history

def save_settings(settings: dict) -> bool:
    # Атомарная запись: пишем во временный файл (с fsync), проверяем, что он
    # читается обратно, сохраняем предыдущую версию в .bak и только тогда
    # подменяем основной через os.replace. Иначе жёсткое завершение процесса
    # (апдейтер делает os._exit) могло обрезать settings.json → при следующем
    # запуске load_settings возвращал {} и ВСЕ настройки сбрасывались.
    # Защита от затирания: не-словарь и пустой словарь НЕ должны перезаписывать
    # уже сохранённые настройки (иначе разовая ошибка сборки настроек сбрасывала
    # бы папки и прочее к значениям по умолчанию).
    if not isinstance(settings, dict):
        return False
    if not settings and _api.settings_files_exist():
        return False

    # Что лежит на диске сейчас. Читаем ДО записи: если ничего не изменилось,
    # диск вообще не трогаем (сохранение висит на каждом поле — при протяжке
    # ползунка это были десятки лишних перезаписей подряд).
    current, current_status = _api._read_settings_file(_api.SETTINGS_FILE, retries=2)
    if current_status == "ok" and current == settings:
        return True

    # Временный файл — СВОЙ у каждого процесса. Общее имя settings.json.tmp
    # означало, что два одновременно запущенных экземпляра программы пишут в
    # один и тот же файл и один может опубликовать обрывок другого.
    tmp = f"{_api.SETTINGS_FILE}.{_api.os.getpid()}.tmp"
    try:
        _api.os.makedirs(_api.os.path.dirname(_api.SETTINGS_FILE), exist_ok=True)
        text = _api.json.dumps(settings, ensure_ascii=False, indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                _api.os.fsync(f.fileno())
            except Exception:
                pass
        # Перечитываем то, что РЕАЛЬНО легло на диск: обрезанный/битый файл не
        # должен попасть на место рабочих настроек.
        with open(tmp, "r", encoding="utf-8") as f:
            written = _api.json.load(f)
        if not isinstance(written, dict) or written != settings:
            raise ValueError("проверка записанных настроек не прошла")
    except Exception:
        try:
            _api.os.remove(tmp)
        except Exception:
            pass
        return False

    if current_status == "ok":
        # В .bak (и в историю) уходит только валидный прежний файл.
        _api._snapshot_settings_history(_api.json.dumps(current, ensure_ascii=False, indent=2))
        _api._replace_with_retry(_api.SETTINGS_FILE, _api.SETTINGS_FILE + ".bak")
    # current_status == 'corrupt'/'locked' → .bak НЕ трогаем: там лежит
    # последняя заведомо рабочая версия, и затирать её мусором нельзя.

    if not _api._replace_with_retry(tmp, _api.SETTINGS_FILE):
        try:
            _api.os.remove(tmp)          # не оставляем мусор рядом с настройками
        except Exception:
            pass
        return False
    return True

save_settings.__module__ = _api.__name__
_api.save_settings = save_settings

def save_json_atomic(path: str, data) -> bool:
    """Атомарная запись небольшого JSON-файла (настройки отдельных вкладок).

    Прямой `open(path, "w")` + json.dump обрезает файл ДО записи нового
    содержимого: жёсткое завершение процесса в этот момент (а его делает
    апдейтер, см. os._exit) оставляло пустой огрызок, и настройки вкладки
    пропадали. Здесь — временный файл, fsync, проверка чтением и подмена."""
    tmp = f"{path}.{_api.os.getpid()}.tmp"
    try:
        _api.os.makedirs(_api.os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            _api.json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                _api.os.fsync(f.fileno())
            except Exception:
                pass
        with open(tmp, "r", encoding="utf-8") as f:
            _api.json.load(f)            # записанное должно читаться обратно
    except Exception:
        try:
            _api.os.remove(tmp)
        except Exception:
            pass
        return False
    if _api._replace_with_retry(tmp, path):
        return True
    try:
        _api.os.remove(tmp)
    except Exception:
        pass
    return False

save_json_atomic.__module__ = _api.__name__
_api.save_json_atomic = save_json_atomic
