# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_franchise_key. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def _franchise_key(s: str) -> str:
    """«Ключ франшизы» — базовое название без сезона/части И без подзаголовка:
    «Атака титанов 2» → «атака титанов», «Наруто: Ураганные хроники» → «наруто»,
    «Бездомный бог: Арагото» → «бездомный бог», «Shingeki no Kyojin Season 2» →
    «shingeki no kyojin». Нужен, чтобы схлопывать сезоны/части одной франшизы в
    выдаче и чтобы пак с «Наруто» прятал и «Наруто: Ураганные хроники»."""
    s = _api._SUBTITLE_RX.sub("", _api._norm_title(s)).strip()
    # Финальная зачистка пунктуации: после снятия сезона мог «обнажиться» хвостовой
    # знак, который _norm_title уже срезал у пака — иначе «Этот замечательный мир!»
    # (пак) ≠ «Этот замечательный мир! 2» (выдача) из-за «!».
    return _api._base_title(s).strip(" .!?–—-:;\"'«»()[]")

_franchise_key.__module__ = _api.__name__
_api._franchise_key = _franchise_key

def _title_words(s: str) -> list:
    """Слова названия (дефис = разделитель, как пробел): «девочки-мечтательницы»
    → [«девочки», «мечтательницы»], чтобы дефисные/пробельные варианты одного
    тайтла дробились на слова одинаково."""
    return [w for w in _api.re.split(r"[\s\-–—]+", s) if w]

_title_words.__module__ = _api.__name__
_api._title_words = _title_words

def _same_franchise_prefix(a: str, b: str, min_words: int = 4) -> bool:
    """True, если два «ключа франшизы» — это один длинный тайтл, различающийся
    лишь последним словом. Нужно для франшиз без сезонного маркера и подзаголовка-
    через-двоеточие, где части отличаются только хвостовым словом: «Этот глупый
    свин не понимает мечту девочки зайки» vs «…девочки-мечтательницы». Порог
    min_words=4 защищает короткие названия от ложного слияния."""
    aw, bw = _api._title_words(a), _api._title_words(b)
    if len(aw) < min_words or len(bw) < min_words or abs(len(aw) - len(bw)) > 1:
        return False
    n = 0
    for x, y in zip(aw, bw):
        if x != y:
            break
        n += 1
    # Общий префикс — всё, кроме последнего слова более короткого названия.
    return n >= min(len(aw), len(bw)) - 1

_same_franchise_prefix.__module__ = _api.__name__
_api._same_franchise_prefix = _same_franchise_prefix

# ─── Фоновые задачи ──────────────────────────────────────────────────────────
class _SearchSignals(_api.QObject):
    finished = _api.pyqtSignal(list)      # list[Anime] (полный результат)
    batch = _api.pyqtSignal(list)         # list[Anime] (новые тайтлы страницы)
    failed = _api.pyqtSignal(str)
    progress = _api.pyqtSignal(int, int)  # страница, собрано подходящих

_SearchSignals.__module__ = _api.__name__
_api._SearchSignals = _SearchSignals

class _SearchTask(_api.QRunnable):
    """Фоновый поиск аниме/манги (в пуле потоков). Результат/ошибка — сигналами.
    Поиск идёт «до конца или до Стоп»; результаты приходят потоково (batch)."""

    def __init__(self, criteria: '_api.AnimeFilter'):
        super().__init__()
        self.setAutoDelete(False)  # держим объект живым через ссылку в виджете
        self.criteria = criteria
        self.signals = _api._SearchSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        client = None
        try:
            client = _api._client_factory()
            res = _api.find_anime(
                client, self.criteria, throttle=0.25,
                progress=lambda p, c: self.signals.progress.emit(p, c),
                on_batch=lambda items: self.signals.batch.emit(items),
                should_stop=lambda: self._stop)
            if not self._stop:
                self.signals.finished.emit(res)
        except _api.ShikimoriError as e:
            if not self._stop:
                self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 — любая неожиданная ошибка в GUI
            if not self._stop:
                self.signals.failed.emit(f"Непредвиденная ошибка: {e}")
        finally:
            if client is not None:
                client.close()

_SearchTask.__module__ = _api.__name__
_api._SearchTask = _SearchTask

class _GenresSignals(_api.QObject):
    finished = _api.pyqtSignal(str, list)   # content_type, genres
    failed = _api.pyqtSignal(str)

_GenresSignals.__module__ = _api.__name__
_api._GenresSignals = _GenresSignals

class _GenresTask(_api.QRunnable):
    """Фоновая загрузка списка жанров для выпадающего фильтра."""

    def __init__(self, content_type: str):
        super().__init__()
        self.setAutoDelete(False)
        self.content_type = content_type
        self.signals = _api._GenresSignals()

    def run(self):
        client = None
        try:
            client = _api._client_factory()
            self.signals.finished.emit(self.content_type,
                                       client.genres(self.content_type))
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(str(e))
        finally:
            if client is not None:
                client.close()

_GenresTask.__module__ = _api.__name__
_api._GenresTask = _GenresTask

def _cover_cache_path(anime_id: int) -> str:
    return _api.os.path.join(_api._COVERS_CACHE_DIR, f"{int(anime_id)}.jpg") if _api._COVERS_CACHE_DIR else ""

_cover_cache_path.__module__ = _api.__name__
_api._cover_cache_path = _cover_cache_path

def _load_cover_from_disk(anime_id: int) -> '_api.Optional[_api.QPixmap]':
    """Синхронно читает обложку из дискового кеша (маленький файл, уже
    уменьшенный до _THUMB_W×_THUMB_H — читать быстро, сети не требует)."""
    path = _api._cover_cache_path(anime_id)
    if not path or not _api.os.path.isfile(path):
        return None
    pm = _api.QPixmap(path)
    return pm if not pm.isNull() else None

_load_cover_from_disk.__module__ = _api.__name__
_api._load_cover_from_disk = _load_cover_from_disk

def _save_cover_to_disk(anime_id: int, pm: '_api.QPixmap'):
    """Атомарно сохраняет уже уменьшенную обложку на диск (JPEG — постеры без
    альфы, компактнее PNG)."""
    if not _api._COVERS_CACHE_DIR:
        return
    try:
        _api.os.makedirs(_api._COVERS_CACHE_DIR, exist_ok=True)
        path = _api._cover_cache_path(anime_id)
        tmp = path + ".tmp"
        if not pm.save(tmp, "JPG", 85):
            return
        _api.os.replace(tmp, path)
    except Exception:
        pass

_save_cover_to_disk.__module__ = _api.__name__
_api._save_cover_to_disk = _save_cover_to_disk

def _prune_covers_cache():
    """Если файлов накопилось больше _COVERS_CACHE_MAX — удаляет самые старые
    (по времени изменения), чтобы кеш обложек не рос бесконечно."""
    if not _api._COVERS_CACHE_DIR or not _api.os.path.isdir(_api._COVERS_CACHE_DIR):
        return
    try:
        names = [f for f in _api.os.listdir(_api._COVERS_CACHE_DIR) if f.endswith(".jpg")]
        if len(names) <= _api._COVERS_CACHE_MAX:
            return
        paths = [_api.os.path.join(_api._COVERS_CACHE_DIR, n) for n in names]
        paths.sort(key=lambda p: _api.os.path.getmtime(p))
        for p in paths[:len(paths) - _api._COVERS_CACHE_MAX]:
            try:
                _api.os.remove(p)
            except OSError:
                pass
    except Exception:
        pass

_prune_covers_cache.__module__ = _api.__name__
_api._prune_covers_cache = _prune_covers_cache

class _ThumbSignals(_api.QObject):
    done = _api.pyqtSignal(int, bytes)   # anime_id, image bytes

_ThumbSignals.__module__ = _api.__name__
_api._ThumbSignals = _ThumbSignals

class _ThumbTask(_api.QRunnable):
    """Фоновая загрузка одной обложки (постера) по URL."""

    def __init__(self, anime_id: int, url: str):
        super().__init__()
        self.anime_id = anime_id
        self.url = url
        self.signals = _api._ThumbSignals()

    def run(self):
        try:
            from config import http_get
            # Shikimori отдаёт картинки только с осмысленным User-Agent (без него
            # — 403, постеры не грузятся). Реферер с того же домена для надёжности.
            headers = {"User-Agent": _api._user_agent(),
                       "Referer": _api.DEFAULT_BASE_URL + "/"}
            with http_get(self.url, headers=headers, timeout=15) as r:
                data = r.read()
            if data:
                self.signals.done.emit(self.anime_id, data)
        except Exception:
            pass

_ThumbTask.__module__ = _api.__name__
_api._ThumbTask = _ThumbTask

class _ViewsSignals(_api.QObject):
    # anime_id, просмотры (-1 при ошибке), взвешенная база индекса, разбивка по
    # статусам (список (подпись, взвешенный_вклад, число_людей) или [])
    item = _api.pyqtSignal(int, int, float, object)
    progress = _api.pyqtSignal(int, int)    # обработано, всего
    finished = _api.pyqtSignal()

_ViewsSignals.__module__ = _api.__name__
_api._ViewsSignals = _ViewsSignals

class _ViewsTask(_api.QRunnable):
    """Дозагрузка «просмотров» для сортировки по ним. Тянет карточки тайтлов
    ПОСЛЕДОВАТЕЛЬНО одним клиентом — мягче к лимитам Shikimori, чем веер
    параллельных запросов (списочный ответ /api/animes просмотров не содержит)."""

    def __init__(self, ids):
        super().__init__()
        self.setAutoDelete(False)
        self.ids = list(ids)
        self.signals = _api._ViewsSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        client = None
        try:
            client = _api._client_factory(max_retries=5)
            total = len(self.ids)
            for i, aid in enumerate(self.ids, 1):
                if self._stop:
                    break
                views, base, comps = -1, 0.0, []
                try:
                    card = client.get_anime(aid)
                    views = _api.views_from_card(card)
                    base = _api.index_base_from_card(card)
                    comps = _api.index_components_from_card(card)
                except Exception:
                    views, base, comps = -1, 0.0, []
                self.signals.item.emit(aid, views, base, comps)
                self.signals.progress.emit(i, total)
                # Троттлинг под лимит Shikimori (~90 req/min): пауза между
                # карточками, дробим её, чтобы «Стоп» срабатывал мгновенно.
                if i < total:
                    slept = 0.0
                    while slept < _api._VIEWS_THROTTLE and not self._stop:
                        _api.time.sleep(0.1)
                        slept += 0.1
        finally:
            if client is not None:
                client.close()
            self.signals.finished.emit()

_ViewsTask.__module__ = _api.__name__
_api._ViewsTask = _ViewsTask
