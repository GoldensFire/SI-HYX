# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackUpgradeTab, фоновая задача апгрейда и _no_wheel. Public namespace: animepack_upgrade_tab."""
from __future__ import annotations
import animepack_upgrade_tab as _api


def _no_wheel(widget):
    """Отучает поле менять значение колёсиком: панель настроек прокручивается
    тем же колесом, и проехавший над счётчиком курсор молча менял число."""
    def wheelEvent(event, _w=widget):
        event.ignore()
    widget.wheelEvent = wheelEvent
    widget.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
    return widget

_no_wheel.__module__ = _api.__name__
_api._no_wheel = _no_wheel

# ─────────────────────────────────────────────────────────────────────────────
# Фоновая задача
# ─────────────────────────────────────────────────────────────────────────────
class _UpgradeSignals(_api.QObject):
    log = _api.pyqtSignal(str)
    progress = _api.pyqtSignal(int, int, str)
    finished = _api.pyqtSignal(object)      # UpgradeResult
    failed = _api.pyqtSignal(str)

_UpgradeSignals.__module__ = _api.__name__
_api._UpgradeSignals = _UpgradeSignals

class _UpgradeTask(_api.QRunnable):
    """Апгрейд одного пака: правка content.xml → новый .siq рядом."""

    def __init__(self, path: str, settings: '_api.UpgradeSettings'):
        super().__init__()
        self.setAutoDelete(False)
        self.path = path
        self.settings = settings
        self.signals = _api._UpgradeSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            upgrader = _api.PackUpgrader(
                self.path, self.settings,
                log=self.signals.log.emit,
                progress=lambda d, t, m: self.signals.progress.emit(d, t, m),
                should_stop=lambda: self._stop)
            self.signals.finished.emit(upgrader.run())
        except _api.UpgradeError as e:
            self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(f"{type(e).__name__}: {e}")

_UpgradeTask.__module__ = _api.__name__
_api._UpgradeTask = _UpgradeTask

# ─────────────────────────────────────────────────────────────────────────────
# Вкладка: обёртка вокруг единственной страницы
# ─────────────────────────────────────────────────────────────────────────────
class AnimePackUpgradeTab(_api.QWidget):
    """Вкладка «Апгрейд пака»: доводка готового .siq, названия — с Shikimori.

    Сама она почти ничего не делает — держит единственную _UpgradePage и
    раздаёт ей вызовы снаружи (set_siq, get_settings, cleanup). Раньше здесь
    было два профиля отдельными подвкладками («Аниме-пак» и «Кино-пак» на
    Wikidata) — кино-пак убрали вместе с подвкладками, и видимой полосы
    вкладок над формой больше нет.

    Настройки по-прежнему лежат в settings.json по словарю на профиль (ключ
    «profiles», в нём одна запись — «anime»): так старый формат из версий с
    двумя подвкладками читается без потери настроек, а совсем старый плоский
    словарь — как есть, тоже настройки этой страницы."""

    def __init__(self, main_window=None, settings: _api.Optional[dict] = None):
        super().__init__()
        self.main = main_window
        self._initial = dict(settings or {})
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        page = _api._UpgradePage(main_window, self._split(self._initial),
                            _api.PROFILE_ANIME)
        self.pages = {_api.PROFILE_ANIME: page}
        lay.addWidget(page)

    # ── настройки ─────────────────────────────────────────────────────────
    @staticmethod
    def _split(data: dict) -> dict:
        """Настройки единственной страницы из того, что лежало в
        settings.json.

        Вид с подвкладками — {"profiles": {"anime": {...}, "movie": {...}}}
        (movie теперь просто не читается); совсем старый, до появления
        профилей вовсе, — плоский словарь настроек: он и есть эта страница."""
        if not isinstance(data, dict):
            return {}
        saved = data.get("profiles")
        if isinstance(saved, dict):
            return dict(saved.get(_api.PROFILE_ANIME) or {})
        return {k: v for k, v in data.items() if k != "current"}

    def get_settings(self) -> dict:
        """Настройки вкладки для settings.json."""
        if not _api._HAS_CORE:
            return dict(self._initial)
        return {"profiles": {_api.PROFILE_ANIME: self.current_page.get_settings()}}

    def apply_settings(self, data: dict):
        if not _api._HAS_CORE or not isinstance(data, dict):
            return
        self.current_page.apply_settings(self._split(data))

    # ── что снаружи ───────────────────────────────────────────────────────

    @property
    def current_page(self):
        return self.pages[_api.PROFILE_ANIME]

    def set_siq(self, path: str) -> bool:
        """Подставить пак снаружи — тем же путём, что и перетаскивание мышью
        на саму страницу."""
        return self.current_page.set_siq(path)

    def cleanup(self):
        try:
            self.current_page.cleanup()
        except Exception:  # pragma: no cover — уборка не должна ронять выход
            pass

AnimePackUpgradeTab.__module__ = _api.__name__
_api.AnimePackUpgradeTab = AnimePackUpgradeTab
