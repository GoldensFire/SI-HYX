# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_MixSlider. Public namespace: animepack_tab."""
from __future__ import annotations
import animepack_tab as _api


from .percentage_sliders import PercentageSliders
from si_hyx_parts.animepack.title_kinds import TITLE_KINDS, TITLE_LABELS


class _MixSlider(PercentageSliders, _api._ShareBar):
    """Individual sliders sharing 100%, with the historical public API."""

    KEYS = ("songs", "video", "frames", "chars", "manga", "pixel", "anagram",
            "dialogue", "plot", "description_audio", "ai_art", "pixiv_art", "sakuga",
            "studio") + TITLE_KINDS
    # Первые пять — «историческая» пятёрка percents(): её ждут и сохранённые
    # настройки, и PackSettings.percents.
    LEGACY = KEYS[:5]
    LABELS = {"songs": "Песни", "video": "Ролики", "frames": "Кадры",
              "chars": "Персонажи", "manga": "Манга", "pixel": "Кадры с эффектами",
              "anagram": "Анаграммы", "dialogue": "Диалоги",
              "plot": "Сюжет", "description_audio": "Описание",
              "ai_art": "ИИ-арты",
              "pixiv_art": "Арты Pixiv",
              "sakuga": "Сакуга", "studio": "Студия",
              "synonyms": "Синонимы",
              "antonyms": "Антонимы", "ukrainian": "Название на украинском"}
    COLORS = {"songs": "accent", "video": "accent2", "frames": "green",
              "chars": "yellow", "manga": "red", "pixel": "text2",
              "anagram": "accent2", "dialogue": "yellow", "plot": "green",
              "description_audio": "accent2",
              "ai_art": "accent2",
              "pixiv_art": "yellow", "sakuga": "red",
              "studio": "accent"}
    LABELS.update(TITLE_LABELS)
    # Части, которые появляются на полосе только по своей галочке.
    OPTIONAL = KEYS

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._vals = {k: (100 if k == "songs" else 0) for k in self.KEYS}
        self._on = {k: k in ("songs", "frames", "chars") for k in self.OPTIONAL}
        self._parts()
        self.build_rows()

    def _parts(self) -> None:
        self._keys = [k for k in self.KEYS
                      if k not in self.OPTIONAL or self._on.get(k)]
        self._labels = dict(self.LABELS)
        self._colors = dict(self.COLORS)

    # ── значение ──────────────────────────────────────────────────────────
    def shares(self) -> dict:
        """{ключ: проценты} по ВСЕМ родам вопросов. Скрытая часть — всегда 0."""
        return {k: (self._vals.get(k, 0) if k in self._keys else 0)
                for k in self.KEYS}

    def percents(self) -> tuple[int, int, int, int, int]:
        """(песни, ролики, кадры, персонажи, манга) — первые пять частей.

        Сумма равна сотне, только пока выключены пиксели, анаграммы и сюжет:
        они берут свою долю из той же сотни. Весь состав — в shares()."""
        vals = self.shares()
        return tuple(vals[k] for k in self.LEGACY)

    def set_shares(self, vals: dict) -> None:
        """Ставит доли всех родов сразу; чего нет в словаре — то ноль."""
        raw = {k: max(0, int(vals.get(k, 0) or 0)) for k in self.KEYS}
        self._normalise(raw)
        self.update()

    def set_percents(self, songs: int, video: int, frames: int,
                     chars: int, manga: int = 0) -> None:
        """Историческая пятёрка. Доли пикселей, анаграмм и сюжета остаются
        прежними — их этот вызов не касается."""
        for key, value in (("songs", songs), ("frames", frames), ("chars", chars)):
            if value > 0:
                self._on[key] = True
        self._parts()
        vals = self.shares()
        vals.update({"songs": songs, "video": video, "frames": frames,
                     "chars": chars, "manga": manga})
        self.set_shares(vals)

    def _set_part(self, key: str, enabled: bool) -> None:
        """Общий переключатель необязательной части полосы."""
        if bool(enabled) == (key in self._keys):
            return
        vals = dict(self._vals)
        self._on[key] = bool(enabled)
        self._parts()
        if enabled:
            vals[key] = max(1, sum(vals.get(k, 0) for k in self._keys if k != key) // max(1, len(self._keys)))
        else:
            vals[key] = 0
        self._normalise(vals)
        self.update()

    def set_video(self, enabled: bool) -> None:
        """Включает/выключает часть «Ролики» в полосе."""
        self._set_part("video", enabled)

    def set_manga(self, enabled: bool) -> None:
        """Включает/выключает часть «Манга» в полосе."""
        self._set_part("manga", enabled)

    def set_pixel(self, enabled: bool) -> None:
        """Включает часть «Кадры с эффектами», сохраняя прежний ключ pixel."""
        self._set_part("pixel", enabled)

    def set_anagram(self, enabled: bool) -> None:
        """Включает/выключает часть «Анаграммы» в полосе."""
        self._set_part("anagram", enabled)

    def set_plot(self, enabled: bool) -> None:
        """Включает/выключает часть «Сюжет» в полосе."""
        self._set_part("plot", enabled)

    def set_dialogue(self, enabled: bool) -> None:
        self._set_part("dialogue", enabled)

    def set_studio(self, enabled: bool) -> None:
        """Включает/выключает часть «Студия» в полосе."""
        self._set_part("studio", enabled)

    def set_ai_art(self, enabled: bool) -> None:
        self._set_part("ai_art", enabled)

    def set_pixiv_art(self, enabled: bool) -> None:
        self._set_part("pixiv_art", enabled)

    def set_sakuga(self, enabled: bool) -> None:
        """Включает/выключает часть «Сакуга» в полосе."""
        self._set_part("sakuga", enabled)

_MixSlider.__module__ = _api.__name__
_api._MixSlider = _MixSlider

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

    def __init__(self, settings: '_api.PackSettings'):
        super().__init__()
        self.setAutoDelete(False)
        self.settings = settings
        self.signals = _api._GenSignals()
        self._stop = False
        self._gen = None

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
            from si_hyx_parts.animepack.generation_priority import apply_thread_priority
            apply_thread_priority(self.settings)
            gen = self._gen = _api.AnimePackGenerator(
                self.settings,
                log=self.signals.log.emit,
                progress=lambda d, t, m: self.signals.progress.emit(d, t, m),
                should_stop=lambda: self._stop)
            self.signals.finished.emit(gen.run())
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
            self.signals.finished.emit(gen.refresh_db(self.parts))
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

class _NumItem(_api.QTableWidgetItem):
    """Ячейка с числом: показывает текст, а сортируется по значению.

    Без этого клик по «Цене» или «Индексу» сортировал бы строки как строки —
    «10» оказывалось бы раньше «2», а «1 200» раньше «800»."""

    def __init__(self, text: str, value: float):
        super().__init__(text)
        try:
            self._value = float(value)
        except (TypeError, ValueError):
            self._value = 0.0

    def __lt__(self, other):
        if isinstance(other, _api._NumItem):
            return self._value < other._value
        return super().__lt__(other)

    def clone(self):
        """Копия ячейки, которая ОСТАЁТСЯ числовой.

        Родной QTableWidgetItem.clone() делает копию базового класса, и в
        отдельном окне состава пака «Цена» и «Индекс» сортировались как
        строки: 1, 10, 11, 12 вместо 1, 2, 3, 4 (просьба пользователя).
        Заодно переносим роли, в которых лежат наши подсказки."""
        item = _NumItem(self.text(), self._value)
        item.setTextAlignment(self.textAlignment())
        for role in _CLONE_ROLES:
            value = self.data(role)
            if value is not None:
                item.setData(role, value)
        return item

# Роли, которые обязан унести с собой clone(): наши подсказки «из чего
# сложился индекс» и «из чего сложилась цена» (см. index_tooltip.py).
_CLONE_ROLES = (
    _api.Qt.ItemDataRole.ToolTipRole,
    _api.Qt.ItemDataRole.UserRole,
    _api.Qt.ItemDataRole.UserRole + 7,
    _api.Qt.ItemDataRole.UserRole + 8,
)

_NumItem.__module__ = _api.__name__
_api._NumItem = _NumItem
