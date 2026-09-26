# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_no_wheel. Public namespace: animepack_upgrade_tab."""
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
# Страница профиля (сама вкладка — AnimePackUpgradeTab ниже)
# ─────────────────────────────────────────────────────────────────────────────
class _UpgradePage(_api.QWidget):
    """Доводка готового .siq: спецвопросы → обычные, ответы → с вариантами
    названий тайтла с Shikimori."""

    from si_hyx_parts.animepack_upgrade_tab.upgrade_page___init import (
        __init__,
        source_name,
        what,
        _build_unavailable,
    )

    # Подписи колонок таблицы изменений.
    TABLE_HEADERS = ("№", "Раунд", "Тема", "Цена", "Функция", "Было", "Стало")
    TABLE_NUM_COLS = (0, 3)

    from si_hyx_parts.animepack_upgrade_tab.upgrade_page__build_ui import (
        _build_ui,
        _build_pack_card,
        _esc,
        _show_pack_card,
        _themes_html,
        _lab,
        _hint,
        _build_settings_panel,
        _group_pack,
        _group_specials,
    )

    from si_hyx_parts.animepack_upgrade_tab.upgrade_page__group_titles import (
        _group_titles,
        _group_repeats,
        _group_merge,
        _group_empty,
        _group_images,
    )

    from si_hyx_parts.animepack_upgrade_tab.upgrade_page__group_audio import (
        _group_audio,
        _refresh_norm_enabled,
        _group_video,
        _group_unused,
        _build_actions,
        _disable_wheel,
    )

    # Уже этого панель настроек не сжимается: дальше подписи начинают резаться.
    SETTINGS_MIN_W = 300
    TABLE_MIN_W = 260

    from si_hyx_parts.animepack_upgrade_tab.upgrade_page__fit_settings_width import (
        _fit_settings_width,
        resizeEvent,
        showEvent,
        _dropped_siq,
        dragEnterEvent,
        dropEvent,
        set_siq,
        _apply_styles,
        _choose_siq,
        _refresh_siq_label,
        _choose_out_dir,
        _refresh_out_dir_label,
        collect,
        get_settings,
        apply_settings,
        reset_settings,
        log,
    )

    from si_hyx_parts.animepack_upgrade_tab.upgrade_page_start import (
        start,
        _what_for,
        stop,
        _progress,
        _on_progress,
        _finish_ui,
        _on_failed,
        _on_finished,
    )

    # Правки, у которых места в раундах нет вовсе: это не вопрос, а файл в
    # архиве. Ни раунда, ни цены у них не бывает, и имя файла занимает все три
    # колонки разом — иначе оно жалось в «Тему» между двумя пустыми клетками.
    FILE_KINDS = ("image", "audio", "video", "unused")

    from si_hyx_parts.animepack_upgrade_tab.upgrade_page__fill_table import (
        _fill_table,
        _fit_round_column,
        _open_result,
        cleanup,
    )

_UpgradePage.__module__ = _api.__name__
_api._UpgradePage = _UpgradePage

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
