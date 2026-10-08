# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Фоновые задачи: поиск, жанры, обложки и просмотры. Public namespace: shikimori_tab."""
import shikimori_tab as _api


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
    # anime_id, просмотры (-1 — тайтла нет в базе), индекс генератора пака,
    # строка базы генератора (для подсказки) или None
    item = _api.pyqtSignal(int, int, float, object)
    progress = _api.pyqtSignal(int, int)    # обработано, всего
    finished = _api.pyqtSignal()

_ViewsSignals.__module__ = _api.__name__
_api._ViewsSignals = _ViewsSignals


class _ViewsTask(_api.QRunnable):
    """Просмотры и индекс популярности из базы генератора аниме-паков.

    Карточки берутся из той же базы Shikimori, что у генерации пака; чего там
    нет (только из fetch_ids и только при network), дозапрашивается пачками
    GraphQL по 50 и сохраняется в неё же (см. pack_index)."""

    def __init__(self, ids, content_type: str = "anime", *, fetch_ids=None,
                 network: bool = True):
        super().__init__()
        self.setAutoDelete(False)
        self.ids = list(ids)
        self.fetch_ids = set(self.ids if fetch_ids is None else fetch_ids)
        self.content_type = content_type
        self.network = bool(network)
        self.signals = _api._ViewsSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        from .pack_index import compute, views_from_stats
        try:
            known = {}
            try:
                # Сначала то, что уже в базе, — без сети; затем дозапрос.
                known = compute(self.ids, self.content_type, network=False,
                                stopped=lambda: self._stop,
                                progress=self.signals.progress.emit)
                ask = [i for i in self.ids if i not in known and i in self.fetch_ids]
                self._emit(known, [i for i in self.ids if i in known], views_from_stats)
                if self.network and ask and not self._stop:
                    fresh = compute(ask, self.content_type, network=True,
                                    stopped=lambda: self._stop,
                                    progress=self.signals.progress.emit)
                    self._emit(fresh, ask, views_from_stats)
            except Exception:  # noqa: BLE001 — без базы просто нет индекса
                pass
        finally:
            self.signals.finished.emit()

    def _emit(self, rows, ids, views_from_stats):
        for aid in ids:
            if self._stop:
                return
            row = rows.get(aid)
            if row is None:
                self.signals.item.emit(aid, -1, 0.0, None)
                continue
            self.signals.item.emit(aid, views_from_stats(row.get("card")),
                                   float(row.get("index") or 0.0), row)

_ViewsTask.__module__ = _api.__name__
_api._ViewsTask = _ViewsTask
