# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Стрелки прокрутки полосы вкладок. Public namespace: widgets."""
import widgets as _api


# ─── Общие мелкие виджеты, используемые несколькими вкладками ────────────────
# Раньше жили в tabs.py, но нужны и «Обработке»/«Загрузчику», и «Редактированию
# фото» (photo_tab.py). Держим здесь, чтобы tabs.py и photo_tab.py не зависели
# друг от друга (иначе получался бы циклический импорт).

class TabScrollArrows(_api.QObject):
    """Стрелки прокрутки вкладок «как в браузере».

    Родной QTabBar рисует ОБЕ стрелки-прокрутки в одном блоке у правого края и
    держит их там всегда (неактивную просто гасит). В браузере иначе: стрелка
    «влево» стоит у ЛЕВОГО края и появляется, только если слева есть уехавшие
    вкладки; стрелка «вправо» — у правого и исчезает, когда справа всё влезло.

    Своей прокрутки у QTabBar нет (scrollOffset приватный), поэтому родные
    кнопки остаются рабочим механизмом — мы только переставляем их: активную
    кладём к нужному краю, неактивную уводим ЗА границу таббара (дети виджета
    обрезаются его прямоугольником, поэтому она просто не видна). Прятать
    через setVisible нельзя: QTabBar на каждой перекладке зовёт им show(), и
    получается мигание.
    """

    OFF = 400   # насколько увести неактивную кнопку за край (лишь бы обрезалась)

    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.left = bar.findChild(_api.QToolButton, "ScrollLeftButton")
        self.right = bar.findChild(_api.QToolButton, "ScrollRightButton")
        if self.left is None or self.right is None:
            # Порядок создания у Qt стабилен (сначала левая), но objectName —
            # то, на что можно опереться; запасной путь на случай смены имён.
            btns = bar.findChildren(_api.QToolButton)
            if len(btns) < 2:
                self.left = self.right = None
                return
            self.left, self.right = btns[0], btns[-1]
        self._busy = False
        self._style_buttons()
        for b in (self.left, self.right):
            b.installEventFilter(self)
        bar.installEventFilter(self)
        self.apply()

    def _style_buttons(self):
        """QTabBar рисует прокрутку обычными QToolButton, а те у нас
        стилизованы глобально (config.STYLESHEET) под целую кнопку с фоном и
        рамкой — родная стрелка при этом не рисуется и получаются «два пустых
        квадратика». Ставим свою стрелку-иконку и снимаем фон/рамку только у
        этих двух кнопок. Фон непрозрачный НАРОЧНО: кнопки лежат ПОВЕРХ
        вкладок, и сквозь прозрачную было бы видно вкладку под низом."""
        flat = ("QToolButton{background:#1e1e2e;border:none;border-radius:0px;"
                "padding:0px;margin:0px;min-width:18px;min-height:0px;}"
                "QToolButton:hover{background:#313244;}"
                "QToolButton:disabled{background:#1e1e2e;}")
        for b, icon in ((self.left, 'fa5s.chevron-left'),
                        (self.right, 'fa5s.chevron-right')):
            try:
                b.setIcon(_api.get_icon(icon))
                b.setText("")
                b.setIconSize(_api.QSize(11, 11))
                b.setStyleSheet(flat)
            except Exception:
                pass

    def buttons(self):
        return (self.left, self.right)

    def eventFilter(self, obj, ev):
        if self._busy:
            return False
        if obj is self.bar:
            if ev.type() == _api.QEvent.Type.Resize:
                self.apply()
            return False
        if obj not in (self.left, self.right):
            return False
        if ev.type() in (_api.QEvent.Type.Move, _api.QEvent.Type.Resize,
                         _api.QEvent.Type.Show, _api.QEvent.Type.EnabledChange):
            self.apply()
        return False

    def apply(self):
        """Ставит каждую кнопку на своё место: активную — к краю, неактивную —
        за границу таббара."""
        if self.left is None or self.right is None:
            return
        self._busy = True
        try:
            bw = self.bar.width()
            for b, active_x in ((self.left, 0),
                                (self.right, bw - self.right.width())):
                x = active_x if b.isEnabled() else -self.OFF
                if b.x() != x:
                    b.move(x, b.y())
        except Exception:
            pass
        finally:
            self._busy = False

TabScrollArrows.__module__ = _api.__name__
_api.TabScrollArrows = TabScrollArrows


def install_tab_scroll_arrows(bar):
    """Включает браузерное поведение стрелок прокрутки у QTabBar.
    Возвращает объект-контроллер (его же можно спросить кнопки для колеса)."""
    try:
        return _api.TabScrollArrows(bar)
    except Exception:
        return None

install_tab_scroll_arrows.__module__ = _api.__name__
_api.install_tab_scroll_arrows = install_tab_scroll_arrows


def _icon_btn(text, icon, size=20, color=None):
    """QPushButton с векторной иконкой qtawesome (см. get_icon в config.py).
    color=None → мягкий светлый значок (для тёмных кнопок). На светлой заливке
    (b_run/b_stop) передавайте тёмный цвет (#1e1e2e), чтобы значок не «выцветал»."""
    b = _api.QPushButton(text)
    b.setIcon(_api.get_icon(icon) if color is None else _api.get_icon(icon, color))
    b.setIconSize(_api.QSize(size, size))
    return b

_icon_btn.__module__ = _api.__name__
_api._icon_btn = _icon_btn
