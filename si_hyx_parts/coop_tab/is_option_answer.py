# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_is_option_answer. Public namespace: coop_tab."""
import coop_tab as _api


def _is_option_answer(q: dict) -> bool:
    """Ответ — это метка варианта («B», «а)», «1»), а не содержательный текст.

    Такие ответы совпадают у разных авторов постоянно и к дублям отношения не
    имеют: «B» в вопросе про резьбу и «B» в вопросе про энтомологию — разные
    ответы. Признаём вариантом по двум признакам: в паке у вопроса есть
    answerOptions (надёжно), либо весь ответ состоит из односимвольных меток
    (для паков, где варианты нарисованы прямо на картинке, а в ответе стоит
    просто буква — а также для соавторов на старой сборке, которая флаг
    answerOptions ещё не присылает)."""
    if q.get("opt"):
        return True
    ans = (q.get("a") or "").strip().lower()
    if not ans or len(ans) > 24:
        return False
    for w in _api._OPT_PREFIXES:
        if ans.startswith(w):
            ans = ans[len(w):]
            break
    tokens = [t.strip(_api._OPT_STRIP) for t in _api._OPT_SPLIT.split(ans)]
    tokens = [t for t in tokens if t]
    return bool(tokens) and all(len(t) == 1 and t.isalnum() for t in tokens)

_is_option_answer.__module__ = _api.__name__
_api._is_option_answer = _is_option_answer

def _q_is_filled(q: dict) -> bool:
    """Вопрос заполнен, если в нём есть хоть какое-то содержимое — текст вопроса,
    ответ или медиа (в вопросе/ответе). Пустой ценовой «слот» (только цена, без
    содержимого) заполненным не считается."""
    return bool(q.get("q") or q.get("a") or q.get("qm") or q.get("am"))

_q_is_filled.__module__ = _api.__name__
_api._q_is_filled = _q_is_filled

def pack_to_outline(pkg) -> dict:
    """SiqPackage → лёгкий текстовый обзор (раунды → темы → вопросы)."""
    rounds = []
    for rnd in getattr(pkg, "rounds", []) or []:
        themes = []
        for th in rnd.get("themes", []) or []:
            qs = [_api._q_summary(q) for q in th.get("questions", []) or []]
            themes.append({"name": (th.get("name", "") or "").strip(), "questions": qs})
        rounds.append({"name": (rnd.get("name", "") or "").strip(), "themes": themes})
    return {"name": getattr(pkg, "name", "") or "", "rounds": rounds}

pack_to_outline.__module__ = _api.__name__
_api.pack_to_outline = pack_to_outline

def normalize_room(room: str) -> str:
    """Привести код комнаты к единому виду.

    На сервере комната — это просто ключ KV, поэтому «Collab» и «collab» были
    РАЗНЫМИ комнатами: соавторы подключались «в одну и ту же» комнату и не
    видели друг друга вообще. Схлопываем регистр и пробелы, чтобы совпадало у
    всех. Ровно та же нормализация продублирована в coop_worker.js — тогда
    старые сборки, где её ещё нет, попадают в ту же комнату, что и новые."""
    return " ".join((room or "").split()).lower()

normalize_room.__module__ = _api.__name__
_api.normalize_room = normalize_room

def normalize_url(url: str) -> str:
    """Привести адрес сервера к валидному виду: добавить https:// если схемы нет
    (иначе urllib падает с 'unknown url type') и убрать хвостовой слэш."""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u.lstrip("/")
    return u.rstrip("/")

normalize_url.__module__ = _api.__name__
_api.normalize_url = normalize_url

def outline_from_siq(path: str) -> dict:
    """Открыть .siq, распарсить и вернуть обзор. Хэндл зип-файла сразу
    закрываем — чтобы не мешать SIQuester сохранять пак."""
    from siquester.siq_package import SiqPackage
    pkg = SiqPackage(path)
    try:
        return _api.pack_to_outline(pkg)
    finally:
        try:
            pkg.close()
        except Exception:
            pass

outline_from_siq.__module__ = _api.__name__
_api.outline_from_siq = outline_from_siq

# ══════════════════════════════════════════════════════════════════════════════
# Сетевой слой: публикация своего обзора и опрос комнаты (фоновый поток)
# ══════════════════════════════════════════════════════════════════════════════
class _CoopSync(_api.QObject):
    """Держит фоновый поток: публикует мой обзор в комнату и опрашивает её,
    отдавая в GUI объединённое состояние {author: {outline, updated}}."""

    remoteUpdated = _api.pyqtSignal(dict)       # {author: {"outline":..., "updated":int}}
    statusChanged = _api.pyqtSignal(str, str)   # (текст, цвет)

    POLL_INTERVAL = 6.0

    def __init__(self):
        super().__init__()
        self._url = ""
        self._room = ""
        self._author = ""
        self._thread = None
        self._stop = _api.threading.Event()
        self._wake = _api.threading.Event()
        self._lock = _api.threading.Lock()
        self._pending = None            # обзор, ожидающий публикации
        self._last_published = None     # чтобы не слать одно и то же
        # Опрашиваем комнату только когда вкладка на экране — иначе десятки
        # пользователей молотили бы сервер в фоне (важно при раздаче незнакомым).
        # Публикация СВОИХ правок продолжается и в фоне (она редкая — только при
        # сохранении пака), чтобы напарники видели твою работу сразу.
        self._active = True

    # ── управление ──────────────────────────────────────────────────────────
    def start(self, url: str, room: str, author: str):
        self.stop()
        self._url = _api.normalize_url(url)
        self._room = _api.normalize_room(room)
        self._author = author or "Аноним"
        self._stop = _api.threading.Event()
        self._wake = _api.threading.Event()
        self._last_published = None
        # События отдаём потоку АРГУМЕНТАМИ, а не через self: при переподключении
        # start() заводит новые, и старый поток, читая self._stop, видел бы уже
        # новое (несведённое) событие и крутился бы вечно вторым опросчиком.
        self._thread = _api.threading.Thread(
            target=self._run, args=(self._stop, self._wake), daemon=True)
        self._thread.start()

    def stop(self):
        t = self._thread
        if t is not None:
            self._stop.set()
            self._wake.set()
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None

    def publish(self, outline: dict):
        """Поставить обзор в очередь на отправку (немедленно будит поток)."""
        with self._lock:
            self._pending = outline
        self._wake.set()

    def set_active(self, active: bool):
        """Вкладка на экране / скрыта. В скрытом состоянии не опрашиваем сервер."""
        self._active = bool(active)
        if active:
            self._wake.set()   # вернулись на вкладку — опросить немедленно

    # ── рабочий цикл ─────────────────────────────────────────────────────────
    def _run(self, stop_ev: _api.threading.Event, wake_ev: _api.threading.Event):
        self.statusChanged.emit("Подключение…", _api._C_MUTED)
        while not stop_ev.is_set():
            with self._lock:
                pending = self._pending
                self._pending = None
            if pending is not None and pending != self._last_published:
                if self._do_publish(pending):
                    self._last_published = pending
            if stop_ev.is_set():
                return
            if self._active:
                self._do_poll()
            wake_ev.wait(self.POLL_INTERVAL)
            wake_ev.clear()

    def _endpoint(self) -> str:
        return f"{self._url}/coop/{_api.urllib.parse.quote(self._room, safe='')}"

    def _do_publish(self, outline: dict) -> bool:
        try:
            payload = _api.json.dumps(
                {"author": self._author, "outline": outline,
                 "updated": int(_api.time.time())},
                ensure_ascii=False).encode("utf-8")
            req = _api.urllib.request.Request(
                self._endpoint(), data=payload, method="POST",
                headers={"Content-Type": "application/json",
                         "User-Agent": f"SI-HYX/{_api.APP_VERSION}"})
            with _api.urllib.request.urlopen(req, timeout=20) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except Exception as e:
            self.statusChanged.emit(f"Не удалось опубликовать: {e}", _api._C_WARN)
            return False

    def _do_poll(self):
        try:
            req = _api.urllib.request.Request(
                self._endpoint(), method="GET",
                headers={"User-Agent": f"SI-HYX/{_api.APP_VERSION}"})
            with _api.urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
            data = _api.json.loads(raw) if raw else {}
            authors = data.get("authors", {}) if isinstance(data, dict) else {}
            if not isinstance(authors, dict):
                authors = {}
            self.remoteUpdated.emit(authors)
            now = _api.datetime.datetime.now().strftime("%H:%M:%S")
            # Если в комнате никого, кроме нас, — почти всегда это разошедшийся
            # код комнаты (или разные адреса сервера). Говорим об этом прямо,
            # иначе «подключено, но пусто» выглядит как молчащий напарник.
            others = [a for a in authors if a != self._author]
            if others:
                self.statusChanged.emit(
                    f"В сети • соавторов: {len(others) + 1} • обновлено {now}", _api._C_MINE)
            else:
                self.statusChanged.emit(
                    f"В комнате «{self._room}» пока только вы — проверьте, что код "
                    f"комнаты и адрес сервера у всех одинаковые • {now}", _api._C_DUP)
        except Exception as e:
            self.statusChanged.emit(f"Нет связи с комнатой: {e}", _api._C_WARN)

_CoopSync.__module__ = _api.__name__
_api._CoopSync = _CoopSync
