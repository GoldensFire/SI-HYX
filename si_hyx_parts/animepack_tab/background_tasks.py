# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Фоновые задачи вкладки: генерация, обновление базы, загрузка жанров. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api
from .percentage_sliders import PercentageSliders


# ─────────────────────────────────────────────────────────────────────────────
# Фоновые задачи
# ─────────────────────────────────────────────────────────────────────────────
class _GenSignals(_api.QObject):
    log = _api.pyqtSignal(str)
    progress = _api.pyqtSignal(int, int, str)
    finished = _api.pyqtSignal(object)      # PackResult
    failed = _api.pyqtSignal(str)

_GenSignals.__module__ = _api.__name__
_api._GenSignals = _GenSignals


class _GenTask(_api.QRunnable):
    """Генерация пака целиком: списки → песни → медиа → .siq."""

    def __init__(self, settings: '_api.PackSettings', recovery: str = ""):
        super().__init__()
        self.setAutoDelete(False)
        self.settings = settings
        # Папка сохранённой попытки: пак собирается из неё без нового отбора.
        self.recovery = recovery
        self.signals = _api._GenSignals()
        self._stop = False
        self._gen = None
        from si_hyx_parts.animepack.generation_runtime import GenerationRuntime
        self._runtime = GenerationRuntime(settings, lambda: self._stop)

    def set_priority(self, value):
        if self._runtime.set_priority(value):
            labels = {"low": "низкий", "normal": "обычный", "high": "высокий"}
            self.signals.log.emit(
                f"Приоритет текущей генерации: {labels.get(value, 'обычный')}; "
                f"лимит кодировщиков AV1 {self._runtime.encoder_limit}.")

    def stop(self):
        self._stop = True
        # Флага мало: самые долгие шаги — это запущенные ffmpeg (обрезка песни и
        # кодирование картинок). Пока их не убить, «Стоп» выглядит залипшим.
        gen = self._gen
        if gen is not None:
            try:
                gen.stop_processes()
            except Exception:
                pass

    def run(self):
        gen = None
        try:
            with self._runtime.worker():
                gen = self._gen = _api.AnimePackGenerator(
                    self.settings,
                    log=self.signals.log.emit,
                    progress=lambda d, t, m: self.signals.progress.emit(d, t, m),
                    should_stop=lambda: self._stop,
                    generation_runtime=self._runtime)
                self.signals.finished.emit(
                    gen.rebuild(self.recovery) if self.recovery else gen.run())
        except _api.AnimePackError as e:
            self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            self._gen = None
            if gen is not None:
                try:
                    gen.cleanup()
                except Exception:
                    pass

_GenTask.__module__ = _api.__name__
_api._GenTask = _GenTask


class _RefreshDbSignals(_api.QObject):
    log = _api.pyqtSignal(str)
    finished = _api.pyqtSignal(int)         # сколько карточек оказалось в кэше
    failed = _api.pyqtSignal(str)

_RefreshDbSignals.__module__ = _api.__name__
_api._RefreshDbSignals = _RefreshDbSignals


class _RefreshDbTask(_api.QRunnable):
    """Панель базы: забыть выбранные части кэша и собрать их заново.

    Работа та же, что делает первая генерация, только вынесенная отдельно —
    чтобы потом паки собирались без похода за каталогом и узнаваемостью
    франшиз."""

    def __init__(self, settings: '_api.PackSettings', parts=None):
        super().__init__()
        self.setAutoDelete(False)
        self.settings = settings
        # Какие части базы собирать (панель базы обновляет их по отдельности);
        # None — всё сразу, как делала прежняя кнопка.
        self.parts = parts
        self.signals = _api._RefreshDbSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            gen = _api.AnimePackGenerator(self.settings,
                                     log=self.signals.log.emit,
                                     should_stop=lambda: self._stop)
            count = gen.refresh_db(self.parts)
            self.report = getattr(gen, "_db_refresh_report", {})
            self.signals.finished.emit(count)
        except _api.AnimePackError as e:
            self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(f"{type(e).__name__}: {e}")

_RefreshDbTask.__module__ = _api.__name__
_api._RefreshDbTask = _RefreshDbTask


class _GenresSignals(_api.QObject):
    finished = _api.pyqtSignal(list)
    failed = _api.pyqtSignal(str)

_GenresSignals.__module__ = _api.__name__
_api._GenresSignals = _GenresSignals


class _GenresTask(_api.QRunnable):
    """Список жанров/тем Shikimori для окна выбора (грузится в фоне)."""

    def __init__(self):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _api._GenresSignals()
        self._stop = False

    def stop(self):
        """Отменяет задачу: прервать запрос нельзя, но результат не понадобится.

        Ответ уже неактуален — вкладку закрывают, — а сигнал полетел бы в
        виджет, который сносят прямо сейчас."""
        self._stop = True

    def run(self):
        if self._stop:
            return
        try:
            genres = _api.ShikimoriApi().genres()
        except Exception as e:  # noqa: BLE001
            if not self._stop:
                self.signals.failed.emit(str(e))
            return
        if not self._stop:
            self.signals.finished.emit(genres)

_GenresTask.__module__ = _api.__name__
_api._GenresTask = _GenresTask
