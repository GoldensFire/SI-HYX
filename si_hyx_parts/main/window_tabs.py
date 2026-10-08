# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Главное окно: вкладки — создание и отключение, порядок, полоса вкладок и перетаскивание файлов на неё."""
import main as _api


class UnifiedWindowTabsMixin:
    """Главное окно: вкладки — создание и отключение, порядок, полоса вкладок и перетаскивание файлов на неё."""

    # ------------------------------------------------------------------
    # Вкладки: подсказки (ⓘ) и сохраняемый порядок (drag-n-drop)
    # ------------------------------------------------------------------
    def _add_tab(self, widget, key):
        """Добавляет вкладку с заголовком и значком ⓘ (тот же info_badge с
        всплывающей подсказкой, что и внутри первых двух вкладок — см. widgets.py).
        objectName вида 'tab::<key>' нужен для сохранения порядка вкладок."""
        icon_name, title, tip = self._tab_info.get(key, (None, key, ""))
        try:
            widget.setObjectName(f"tab::{key}")
        except Exception:
            pass
        if icon_name:
            idx = self.tabs.addTab(widget, _api.get_icon(icon_name), title)
        else:
            idx = self.tabs.addTab(widget, title)
        # Значок ⓘ — отдельным виджетом на самой вкладке (как info_badge в формах),
        # с фирменным попапом-подсказкой вместо системного тултипа.
        try:
            badge = _api.info_badge(tip)
            # За подсказку значка вкладки отвечает фильтр QTabBar. Сам QLabel и
            # общий фильтр приложения не должны показывать её повторно.
            badge.setProperty("tabTipManaged", True)
            badge.setStyleSheet("#infoBadge{color:#89b4fa;}")
            # Бейдж ⓘ (16×16, значок 13px по центру) визуально садится на ~1px
            # ниже центра текста вкладки. Нижний отступ сдвигает значок вверх,
            # чтобы он встал на одну высоту с надписью (и с левым значком вкладки).
            badge.setContentsMargins(0, 0, 0, 2)
            self.tabs.tabBar().setTabButton(
                idx, _api.QTabBar.ButtonPosition.RightSide, badge)
            badge.installEventFilter(self)
        except Exception:
            self.tabs.setTabToolTip(idx, tip)
        return idx

    def _on_tab_moved(self, *args):
        # Пользователь перетащил вкладку — сохраняем порядок (но не во время
        # программной перестановки в _apply_tab_order).
        if getattr(self, "_reordering_tabs", False):
            return
        self._save_tab_order()

    def _save_tab_order(self):
        order = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            on = w.objectName() if w is not None else ""
            if on.startswith("tab::"):
                order.append(on[len("tab::"):])
        self._tab_order = order
        try: self._save_settings_now()
        except Exception: pass

    def _apply_tab_order(self, order):
        """Переставляет вкладки согласно сохранённому порядку ключей. Двигаем
        через tabBar().moveTab (QTabWidget сам синхронизирует страницы по сигналу
        tabMoved), а от рекурсивного сохранения защищаемся флагом."""
        if not order:
            return
        bar = self.tabs.tabBar()
        self._reordering_tabs = True
        try:
            target = 0
            for key in order:
                name = f"tab::{key}"
                for i in range(self.tabs.count()):
                    w = self.tabs.widget(i)
                    if w is not None and w.objectName() == name:
                        if i != target:
                            bar.moveTab(i, target)
                        target += 1
                        break
        finally:
            self._reordering_tabs = False

    # ------------------------------------------------------------------
    # Вкладка «Промпт» (включается/выключается в Настройках, по умолч. ВЫКЛ)
    # ------------------------------------------------------------------
    def _add_prompt_tab(self):
        """Добавляет вкладку «Промпт» в таббар (если ещё не добавлена). Сам
        объект self.tab_prompt создаётся в __init__ — здесь только показ."""
        t = getattr(self, "tab_prompt", None)
        if t is None or self.tabs.indexOf(t) >= 0:
            return
        self._add_tab(t, 'prompt')
        try:
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception:
            pass

    def _remove_prompt_tab(self):
        t = getattr(self, "tab_prompt", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            # removeTab оставляет виджет дочерним к таббару — снова прячем, чтобы
            # он не всплыл в углу окна.
            t.setParent(self)
            t.hide()
        except Exception:
            pass

    def _set_prompt_tab_enabled(self, checked: bool):
        self._prompt_tab_enabled = bool(checked)
        if checked:
            self._add_prompt_tab()
        else:
            self._remove_prompt_tab()
        try: self._save_settings_now()
        except Exception: pass

    # ------------------------------------------------------------------
    # Экспериментальная вкладка SiQuester (просмотр .siq + статистика)
    # ------------------------------------------------------------------
    def _add_siquester_tab(self):
        """Создаёт и добавляет вкладку SiQuester (если ещё не добавлена).
        Импорт ленивый — пакет siquester тянет QtMultimedia и грузится только
        когда вкладка включена."""
        if getattr(self, "tab_siquester", None) is not None:
            return
        try:
            from siquester_tab import SiQuesterTab
            self.tab_siquester = SiQuesterTab(self)
            self._add_tab(self.tab_siquester, 'siquester')
            # Сохранённый порядок мог включать эту вкладку — применяем заново.
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception as e:
            self.tab_siquester = None
            self.log(f"Не удалось добавить вкладку SiQuester: {e}")

    def _remove_siquester_tab(self):
        t = getattr(self, "tab_siquester", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            try: t.cleanup()
            except Exception: pass
            t.deleteLater()
        except Exception: pass
        self.tab_siquester = None

    def _set_siquester_tab_enabled(self, checked: bool):
        self._siquester_tab_enabled = bool(checked)
        if checked:
            self._add_siquester_tab()
        else:
            self._remove_siquester_tab()
        try: self._save_settings_now()
        except Exception: pass

    # ------------------------------------------------------------------
    # Экспериментальная вкладка ShikimoriHYX (поиск аниме через Shikimori API)
    # ------------------------------------------------------------------
    def _add_shikimori_tab(self):
        """Создаёт и добавляет вкладку ShikimoriHYX (если ещё не добавлена).
        Импорт ленивый — модуль тянется только когда вкладка включена."""
        if getattr(self, "tab_shikimori", None) is not None:
            return
        try:
            from shikimori_tab import ShikimoriTab
            self.tab_shikimori = ShikimoriTab(self)
            self._add_tab(self.tab_shikimori, 'shikimori')
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception as e:
            self.tab_shikimori = None
            self.log(f"Не удалось добавить вкладку ShikimoriHYX: {e}")

    def _remove_shikimori_tab(self):
        t = getattr(self, "tab_shikimori", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            try: t.cleanup()
            except Exception: pass
            t.deleteLater()
        except Exception: pass
        self.tab_shikimori = None

    def _set_shikimori_tab_enabled(self, checked: bool):
        self._shikimori_tab_enabled = bool(checked)
        if checked:
            self._add_shikimori_tab()
        else:
            # Перед закрытием запоминаем текущие фильтры вкладки.
            self._shikimori_settings = self._collect_shikimori_settings()
            self._remove_shikimori_tab()
        try: self._save_settings_now()
        except Exception: pass

    def _collect_shikimori_settings(self):
        """Актуальные настройки вкладки ShikimoriHYX (или последние сохранённые,
        если вкладка сейчас не открыта)."""
        t = getattr(self, "tab_shikimori", None)
        if t is not None and hasattr(t, "get_settings"):
            try:
                return t.get_settings()
            except Exception:
                pass
        return dict(getattr(self, "_shikimori_settings", {}) or {})

    # ------------------------------------------------------------------
    # Экспериментальная вкладка ЛидербордHYX (просмотр выгрузки рекордов)
    # ------------------------------------------------------------------
    def _add_leaderboard_tab(self):
        """Создаёт и добавляет вкладку ЛидербордHYX (если ещё не добавлена).
        Импорт ленивый — модуль тянется только когда вкладка включена."""
        if getattr(self, "tab_leaderboard", None) is not None:
            return
        try:
            from leaderboard_tab import LeaderboardTab
            self.tab_leaderboard = LeaderboardTab(self)
            self._add_tab(self.tab_leaderboard, 'leaderboard')
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception as e:
            self.tab_leaderboard = None
            self.log(f"Не удалось добавить вкладку ЛидербордHYX: {e}")

    def _remove_leaderboard_tab(self):
        t = getattr(self, "tab_leaderboard", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            try: t.cleanup()
            except Exception: pass
            t.deleteLater()
        except Exception: pass
        self.tab_leaderboard = None

    def _set_leaderboard_tab_enabled(self, checked: bool):
        self._leaderboard_tab_enabled = bool(checked)
        if checked:
            self._add_leaderboard_tab()
        else:
            self._remove_leaderboard_tab()
        try: self._save_settings_now()
        except Exception: pass

    # ------------------------------------------------------------------
    # Экспериментальная вкладка Collab (совместная работа над .siq)
    # ------------------------------------------------------------------
    def _add_coop_tab(self):
        """Создаёт и добавляет вкладку Collab (если ещё не добавлена).
        Импорт ленивый — модуль тянется только когда вкладка включена."""
        if getattr(self, "tab_coop", None) is not None:
            return
        try:
            from coop_tab import CoopTab
            self.tab_coop = CoopTab(self, dict(getattr(self, "_coop_settings", {}) or {}))
            self._add_tab(self.tab_coop, 'coop')
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception as e:
            self.tab_coop = None
            self.log(f"Не удалось добавить вкладку Collab: {e}")

    def _remove_coop_tab(self):
        t = getattr(self, "tab_coop", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            try: t.cleanup()
            except Exception: pass
            t.deleteLater()
        except Exception: pass
        self.tab_coop = None

    def _set_coop_tab_enabled(self, checked: bool):
        self._coop_tab_enabled = bool(checked)
        if checked:
            self._add_coop_tab()
        else:
            # Перед закрытием запоминаем текущие поля вкладки.
            self._coop_settings = self._collect_coop_settings()
            self._remove_coop_tab()
        try: self._save_settings_now()
        except Exception: pass

    def _collect_coop_settings(self):
        """Актуальные поля вкладки Collab (или последние сохранённые,
        если вкладка сейчас не открыта)."""
        t = getattr(self, "tab_coop", None)
        if t is not None and hasattr(t, "get_settings"):
            try:
                return t.get_settings()
            except Exception:
                pass
        return dict(getattr(self, "_coop_settings", {}) or {})

    # ------------------------------------------------------------------
    # Экспериментальная вкладка Генерация аниме-пака (порт ASPG)
    # ------------------------------------------------------------------
    def _add_animepack_tab(self):
        """Создаёт и добавляет вкладку Генерация аниме-пака (если ещё не
        добавлена). Импорт ленивый — модуль тянется только когда включена."""
        if getattr(self, "tab_animepack", None) is not None:
            return
        try:
            from animepack_tab import AnimePackTab
            self.tab_animepack = AnimePackTab(
                self, dict(getattr(self, "_animepack_settings", {}) or {}))
            self._add_tab(self.tab_animepack, 'animepack')
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception as e:
            self.tab_animepack = None
            self.log(f"Не удалось добавить вкладку Генерация аниме-пака: {e}")

    def _remove_animepack_tab(self):
        t = getattr(self, "tab_animepack", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            try: t.cleanup()
            except Exception: pass
            t.deleteLater()
        except Exception: pass
        self.tab_animepack = None

    def _set_animepack_tab_enabled(self, checked: bool):
        self._animepack_tab_enabled = bool(checked)
        if checked:
            self._add_animepack_tab()
        else:
            # Перед закрытием запоминаем текущие настройки генератора.
            self._animepack_settings = self._collect_animepack_settings()
            self._remove_animepack_tab()
        try: self._save_settings_now()
        except Exception: pass

    def _collect_animepack_settings(self):
        """Актуальные настройки вкладки Генерация аниме-пака (или последние
        сохранённые, если вкладка сейчас не открыта)."""
        t = getattr(self, "tab_animepack", None)
        if t is not None and hasattr(t, "get_settings"):
            try:
                return t.get_settings()
            except Exception:
                pass
        return dict(getattr(self, "_animepack_settings", {}) or {})

    # ------------------------------------------------------------------
    # Экспериментальная вкладка Апгрейд пака
    # ------------------------------------------------------------------
    def _add_animepack_upgrade_tab(self):
        """Создаёт и добавляет вкладку Апгрейд пака (если ещё не
        добавлена). Импорт ленивый — модуль тянется только когда включена."""
        if getattr(self, "tab_animepack_upgrade", None) is not None:
            return
        try:
            from animepack_upgrade_tab import AnimePackUpgradeTab
            self.tab_animepack_upgrade = AnimePackUpgradeTab(
                self, dict(getattr(self, "_animepack_upgrade_settings", {}) or {}))
            self._add_tab(self.tab_animepack_upgrade, 'animepack_upgrade')
            self._apply_tab_order(getattr(self, "_tab_order", []))
        except Exception as e:
            self.tab_animepack_upgrade = None
            self.log(f"Не удалось добавить вкладку Апгрейд пака: {e}")

    def _remove_animepack_upgrade_tab(self):
        t = getattr(self, "tab_animepack_upgrade", None)
        if t is None:
            return
        try:
            idx = self.tabs.indexOf(t)
            if idx >= 0:
                self.tabs.removeTab(idx)
            try: t.cleanup()
            except Exception: pass
            t.deleteLater()
        except Exception: pass
        self.tab_animepack_upgrade = None

    def _set_animepack_upgrade_tab_enabled(self, checked: bool):
        self._animepack_upgrade_tab_enabled = bool(checked)
        if checked:
            self._add_animepack_upgrade_tab()
        else:
            # Перед закрытием запоминаем настройки доводки.
            self._animepack_upgrade_settings = \
                self._collect_animepack_upgrade_settings()
            self._remove_animepack_upgrade_tab()
        try: self._save_settings_now()
        except Exception: pass

    def _collect_animepack_upgrade_settings(self):
        """Актуальные настройки вкладки Апгрейд пака (или последние
        сохранённые, если вкладка сейчас не открыта)."""
        t = getattr(self, "tab_animepack_upgrade", None)
        if t is not None and hasattr(t, "get_settings"):
            try:
                return t.get_settings()
            except Exception:
                pass
        return dict(getattr(self, "_animepack_upgrade_settings", {}) or {})

    def _on_tab_bar_clicked(self, index):
        """Вызывается ДО того, как QTabBar реально переключит страницу.
        Прячем/показываем консоль здесь же, но с отключённой перерисовкой окна —
        иначе старая вкладка (например «Обработка», где консоль видна) успевает
        на мгновение перерисоваться в увеличенной высоте ДО самого переключения
        на «Монтаж» (это отдельный кадр, который тот же currentChanged/showEvent
        уже не поймать), и глаз ловит этот промежуточный прыжок холста."""
        self.setUpdatesEnabled(False)
        try:
            self._sync_console_visibility(index)
        finally:
            _api.QTimer.singleShot(0, lambda: self.setUpdatesEnabled(True))

    def _style_tab_scroll_buttons(self):
        """Стрелки прокрутки вкладок — как в браузере: своя стрелка-иконка
        вместо «пустого квадратика» от глобального стиля QToolButton, левая у
        левого края и только пока слева есть уехавшие вкладки, правая — у
        правого (см. widgets.TabScrollArrows)."""
        from widgets import install_tab_scroll_arrows
        self._tab_arrows = install_tab_scroll_arrows(self.tabs.tabBar())

    def _tab_wheel_scroll(self, event):
        """Крутим вкладки колёсиком мыши, как в браузере — через нативные
        стрелки-прокрутки QTabBar (клика по ним программно)."""
        try:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if not delta:
                return
            arrows = getattr(self, "_tab_arrows", None)
            if arrows is not None:
                left, right = arrows.buttons()
            else:
                bar = self.tabs.tabBar()
                buttons = [b for b in bar.findChildren(_api.QToolButton) if b.isVisible()]
                if not buttons:
                    return
                left, right = buttons[0], buttons[-1]
            if left is None or right is None:
                return
            btn = left if delta > 0 else right
            if btn.isEnabled():
                btn.click()
        except Exception:
            pass

    # ── Перетаскивание файла на заголовок вкладки ────────────────────────────
    @staticmethod
    def _tab_drag_has_files(event):
        try:
            md = event.mimeData()
            return bool(md and md.hasUrls()
                        and any(u.toLocalFile() for u in md.urls()))
        except Exception:
            return False

    def _tab_drag_hover(self, bar, pos):
        """Курсор с файлом завис над заголовком: запускаем таймер автопереключения
        на эту вкладку (как в браузерах при перетаскивании на заголовок)."""
        idx = bar.tabAt(pos)
        if idx < 0:
            self._tab_drag_idx = -1
            self._tab_drag_timer.stop()
            return
        if idx == self.tabs.currentIndex():
            self._tab_drag_idx = -1
            self._tab_drag_timer.stop()
            return
        if idx != self._tab_drag_idx:
            self._tab_drag_idx = idx
            self._tab_drag_timer.start(600)

    def _tab_drag_switch(self):
        if self._tab_drag_idx >= 0:
            self.setUpdatesEnabled(False)
            try:
                self._sync_console_visibility(self._tab_drag_idx)
                self.tabs.setCurrentIndex(self._tab_drag_idx)
            except Exception: pass
            finally:
                _api.QTimer.singleShot(0, lambda: self.setUpdatesEnabled(True))

    def _tab_drag_drop(self, bar, event):
        """Бросок файла прямо на заголовок: открываем вкладку и добавляем в неё
        файл(ы) — тем же путём, что и обычный drop в её содержимое."""
        self._tab_drag_timer.stop()
        self._tab_drag_idx = -1
        idx = bar.tabAt(event.position().toPoint())
        if idx < 0:
            return
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.toLocalFile()]
        if not paths:
            return
        self.setUpdatesEnabled(False)
        self._sync_console_visibility(idx)
        self.tabs.setCurrentIndex(idx)
        _api.QTimer.singleShot(0, lambda: self.setUpdatesEnabled(True))
        page = self.tabs.widget(idx)
        fn = (getattr(page, "accept_dropped_paths", None)
              or getattr(page, "add_paths", None))
        if fn is not None:
            fn(paths)
        try:
            self.raise_(); self.activateWindow()
        except Exception:
            pass

    def _update_tab_tip(self, pos=None):
        """Показывает попап-подсказку, если курсор над значком ⓘ вкладки.

        Текст берём не из значка, а из _tab_info по стабильному ключу вкладки
        (objectName 'tab::<key>'): Qt при tabButton() может вернуть значок как
        обычный QLabel, потеряв питоновский атрибут _tip, поэтому полагаться на
        сам объект значка нельзя."""
        from widgets import _InfoTipPopup
        from PyQt6.QtGui import QCursor
        bar = self.tabs.tabBar()
        cursor = QCursor.pos()
        # Событие может прийти с опозданием, а соседний значок уже под курсором.
        # childAt учитывает перекрытие и обрезку при прокрутке QTabBar, тогда как
        # перебор прямоугольников может выбрать невидимый значок первой вкладки.
        hovered = bar.childAt(bar.mapFromGlobal(cursor))
        for idx in range(bar.count()):
            badge = bar.tabButton(idx, _api.QTabBar.ButtonPosition.RightSide)
            if badge is None or badge is not hovered:
                continue
            page = self.tabs.widget(idx)
            on = page.objectName() if page is not None else ""
            tip = self._tab_info.get(on[5:], ("", "", ""))[2] if on.startswith("tab::") else ""
            if tip:
                _InfoTipPopup.instance().show_for(badge, tip)
                self._tab_tip_idx = idx
                self._tab_tip_badge = badge
                return
        self._hide_tab_tip()

    def _hide_tab_tip(self):
        badge = getattr(self, "_tab_tip_badge", None)
        try:
            from widgets import _InfoTipPopup
            popup = _InfoTipPopup.instance()
            if badge is None:
                bar = self.tabs.tabBar()
                for index in range(bar.count()):
                    candidate = bar.tabButton(index, _api.QTabBar.ButtonPosition.RightSide)
                    if candidate is not None and popup._anchor == id(candidate):
                        badge = candidate
                        break
            if badge is not None:
                popup.hide_for(badge)
        except Exception:
            pass
        self._tab_tip_badge = None
        self._tab_tip_idx = -1
