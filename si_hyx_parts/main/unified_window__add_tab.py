# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: _add_tab. Public namespace: main."""
import main as _api


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
