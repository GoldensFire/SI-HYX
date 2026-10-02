# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_ViewsBadgeDelegate. Public namespace: shikimori_tab."""
import shikimori_tab as _api
from si_hyx_parts.widgets.info_tip_frame import source_is_current


class _ViewsBadgeDelegate(_api.QStyledItemDelegate):
    """Дорисовывает к строке тайтла настоящий SVG-значок «глаз» (qtawesome
    fa5s.eye) и число просмотров у правого края, а также кнопку «копировать»
    название (fa5s.copy) сразу справа от самого названия. «Глаз» — вместо emoji 👁
    (одинаково на всех ОС/темах); число берётся из кеша просмотров вкладки (тот же,
    что и для сортировки) и рисуется, когда дозагружено. Клик по «копировать»
    (editorEvent) кладёт название в буфер обмена и на 1.5 с показывает «галочку»."""

    def __init__(self, tab: '_api.ShikimoriTab'):
        super().__init__(tab)
        self._tab = tab
        self._icon = _api.get_icon('fa5s.eye', color=_api.C['text2'])
        self._index_icon = _api.get_icon('fa5s.fire', color=_api.C.get('peach', '#fab387'))
        self._copy_icon = _api.get_icon('fa5s.copy', color=_api.C['text2'])
        self._ok_icon = _api.get_icon('fa5s.check', color=_api.C.get('green', '#a6e3a1'))
        self._copy_orig_icon = _api.get_icon('fa5s.copy', color=_api.C['text2'])
        self._ok_orig_icon = _api.get_icon('fa5s.check', color=_api.C.get('green', '#a6e3a1'))
        self._copied_id = None          # id строки с активной «галочкой» (рус. название)
        self._copied_orig_id = None     # id строки с активной «галочкой» (ориг. название)
        self._index_rects = {}          # aid -> QRect значка индекса (для подсказки)
        # aid -> ТОЧНЫЙ нарисованный прямоугольник кнопки «копировать» (рус./ориг.).
        # Считаем их в paint() реальной опцией Qt и переиспользуем в hover-фильтре:
        # ручная реконструкция опции (initFrom) теряет фичи декорации → X иконки
        # уезжал и курсор-«рука» не появлялся над реально видимым значком.
        self._copy_rects = {}
        self._copy_orig_rects = {}
        self._reset_timer = _api.QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._clear_copied)
        self._reset_orig_timer = _api.QTimer(self)
        self._reset_orig_timer.setSingleShot(True)
        self._reset_orig_timer.timeout.connect(self._clear_copied_orig)

    def _clear_copied(self):
        self._copied_id = None
        self._tab.list.viewport().update()

    def _clear_copied_orig(self):
        self._copied_orig_id = None
        self._tab.list.viewport().update()

    def _copy_rect(self, option, index) -> _api.QRect:
        """Прямоугольник кнопки «копировать» — строго справа от текста названия
        (первая строка) и по центру ИМЕННО этой строки. По правому краю обрезается,
        чтобы не залезть за границу/под счётчик просмотров."""
        opt = _api.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget else _api.QApplication.style()
        tr = style.subElementRect(
            _api.QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        fm = opt.fontMetrics
        title = (index.data(_api.Qt.ItemDataRole.UserRole + 2) or "").split("\n")[0]
        tw = fm.horizontalAdvance(title)
        # X — сразу за концом названия, но не за правым краем строки.
        x = tr.left() + tw + _api._COPY_TITLE_GAP
        x = min(x, option.rect.right() - 8 - _api._COPY_ICON_SZ)
        x = max(x, tr.left())
        # Y — по центру ПЕРВОЙ строки названия. Текст в ячейке выровнен по вертикали
        # по центру (Qt.AlignVCenter), т.е. блок из нескольких строк начинается не от
        # tr.top(), а ниже на половину свободного места. Раньше Y брался от tr.top(),
        # и значок «уезжал» к верхнему краю карточки вместо строки с названием.
        full = index.data(_api.Qt.ItemDataRole.DisplayRole) or title
        block_h = fm.boundingRect(
            _api.QRect(0, 0, max(1, tr.width()), 1 << 22),
            int(_api.Qt.TextFlag.TextWordWrap | _api.Qt.AlignmentFlag.AlignTop), full).height()
        block_top = tr.top() + max(0, (tr.height() - block_h) // 2)
        y = block_top + max(0, (fm.lineSpacing() - _api._COPY_ICON_SZ) // 2)
        return _api.QRect(int(x), int(y), _api._COPY_ICON_SZ, _api._COPY_ICON_SZ)

    def _copy_orig_rect(self, option, index) -> _api.QRect:
        """Прямоугольник кнопки «копировать» для ОРИГИНАЛЬНОГО названия (вторая строка).
        Возвращает null QRect(), если оригинального названия нет или оно совпадает с
        отображаемым (тогда кнопка не рисуется и не кликабельна)."""
        orig = index.data(_api.Qt.ItemDataRole.UserRole + 3) or ""
        title = index.data(_api.Qt.ItemDataRole.UserRole + 2) or ""
        if not orig or orig == title:
            return _api.QRect()
        opt = _api.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget else _api.QApplication.style()
        tr = style.subElementRect(
            _api.QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        fm = opt.fontMetrics
        tw = fm.horizontalAdvance(orig)
        x = tr.left() + tw + _api._COPY_TITLE_GAP
        x = min(x, option.rect.right() - 8 - _api._COPY_ICON_SZ)
        x = max(x, tr.left())
        full = index.data(_api.Qt.ItemDataRole.DisplayRole) or ""
        block_h = fm.boundingRect(
            _api.QRect(0, 0, max(1, tr.width()), 1 << 22),
            int(_api.Qt.TextFlag.TextWordWrap | _api.Qt.AlignmentFlag.AlignTop), full).height()
        block_top = tr.top() + max(0, (tr.height() - block_h) // 2)
        # Вторая строка начинается через lineSpacing() от начала блока.
        y = block_top + fm.lineSpacing() + max(0, (fm.lineSpacing() - _api._COPY_ICON_SZ) // 2)
        return _api.QRect(int(x), int(y), _api._COPY_ICON_SZ, _api._COPY_ICON_SZ)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        # Номер места тайтла в списке — слева от постера (в зарезервированном
        # левом отступе строки, см. padding-left у QListWidget::item).
        rank = index.row() + 1
        painter.save()
        f = _api.QFont(option.font)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(_api.QColor(_api.C['text2']))
        painter.drawText(
            _api.QRect(option.rect.left() + 2, option.rect.top(),
                  _api._RANK_W - 4, option.rect.height()),
            int(_api.Qt.AlignmentFlag.AlignVCenter | _api.Qt.AlignmentFlag.AlignHCenter),
            str(rank))
        painter.restore()
        aid = index.data(_api.Qt.ItemDataRole.UserRole + 1)
        icon = self._ok_icon if aid == self._copied_id else self._copy_icon
        painter.save()
        main_rect = self._copy_rect(option, index)
        self._copy_rects[aid] = _api.QRect(main_rect)   # запоминаем точную область для hover
        painter.drawPixmap(main_rect,
                           icon.pixmap(_api._COPY_ICON_SZ, _api._COPY_ICON_SZ))
        painter.restore()
        # Кнопка «копировать» для ОРИГИНАЛЬНОГО названия (вторая строка, если есть).
        orig_rect = self._copy_orig_rect(option, index)
        self._copy_orig_rects[aid] = (_api.QRect(orig_rect) if not orig_rect.isNull()
                                      else _api.QRect())
        if not orig_rect.isNull():
            icon_orig = (self._ok_orig_icon if aid == self._copied_orig_id
                         else self._copy_orig_icon)
            painter.save()
            painter.drawPixmap(orig_rect, icon_orig.pixmap(_api._COPY_ICON_SZ, _api._COPY_ICON_SZ))
            painter.restore()
        try:
            views = self._tab._views_cache.get(aid)
        except Exception:
            views = None
        if views is None or views < 0:
            return
        text = f"{views:,}".replace(",", " ")
        icon_sz, pad, gap = 14, 8, 5
        rect = option.rect
        fm = option.fontMetrics
        tw = fm.horizontalAdvance(text)
        x_text = rect.right() - pad - tw
        x_icon = x_text - gap - icon_sz
        y_icon = rect.center().y() - icon_sz // 2
        painter.save()
        painter.drawPixmap(int(x_icon), int(y_icon),
                           self._icon.pixmap(icon_sz, icon_sz))
        painter.setPen(_api.QColor(_api.C['text2']))
        painter.drawText(
            _api.QRect(int(x_text), rect.top(), tw + 2, rect.height()),
            int(_api.Qt.AlignmentFlag.AlignVCenter | _api.Qt.AlignmentFlag.AlignLeft),
            text)
        painter.restore()

        # «Индекс популярности» (значок-огонёк + число) — слева от просмотров.
        # Это та же величина, по которой сортирует режим «По индексу
        # популярности»: просмотры, взвешенные на свежесть выхода.
        try:
            a = self._tab._anime_by_id.get(aid)
            idx_when = (a.air_date or a.year) if a else None
            base = self._tab._index_base_cache.get(aid, 0.0)
            idx_val = _api._popularity_index(base, idx_when, a.score if a else 0.0)
        except Exception:
            idx_val = 0
        if idx_val and idx_val > 0:
            itext = f"{int(round(idx_val)):,}".replace(",", " ")
            itw = fm.horizontalAdvance(itext)
            ix_text = x_icon - 14 - itw
            ix_icon = ix_text - gap - icon_sz
            painter.save()
            painter.drawPixmap(int(ix_icon), int(y_icon),
                               self._index_icon.pixmap(icon_sz, icon_sz))
            painter.setPen(_api.QColor(_api.C.get('peach', '#fab387')))
            painter.drawText(
                _api.QRect(int(ix_text), rect.top(), itw + 2, rect.height()),
                int(_api.Qt.AlignmentFlag.AlignVCenter | _api.Qt.AlignmentFlag.AlignLeft),
                itext)
            painter.restore()
            # Запоминаем область значка индекса (огонёк + число) — по ней
            # показываем подсказку с разбивкой (см. helpEvent).
            self._index_rects[aid] = _api.QRect(
                int(ix_icon), rect.top(),
                int(x_icon - ix_icon), rect.height())

    def helpEvent(self, event, view, option, index):
        """Подсказка к «индексу популярности» при наведении на его значок —
        показываем ФИРМЕННЫЙ тёмный попап (_InfoTipPopup, как у «Схлопывать
        франшизы»), а НЕ системный QToolTip с синей рамкой. Возврат True гасит
        системную подсказку списка."""
        if event.type() == _api.QEvent.Type.ToolTip and _api._InfoTipPopup is not None:
            if not source_is_current(view.viewport(), event.globalPos()):
                return True
            aid = index.data(_api.Qt.ItemDataRole.UserRole + 1)
            rect = self._index_rects.get(aid)
            try:
                pos = event.pos()
            except Exception:
                pos = None
            if rect is not None and pos is not None and rect.contains(pos):
                tip = self._tab._index_tooltip_for(aid)
                if tip:
                    _api._InfoTipPopup.instance().show_at(
                        event.globalPos(), tip, owner=view.viewport())
                    return True
            _api._InfoTipPopup.instance().hide_for(view.viewport())
            return False
        return super().helpEvent(event, view, option, index)

    def editorEvent(self, event, model, option, index):
        if event.type() == _api.QEvent.Type.MouseButtonRelease:
            try:
                pos = event.position().toPoint()
            except AttributeError:  # старые сборки Qt
                pos = event.pos()
            if self._copy_rect(option, index).contains(pos):
                title = index.data(_api.Qt.ItemDataRole.UserRole + 2) or ""
                if title:
                    _api.QApplication.clipboard().setText(title)
                    self._copied_id = index.data(_api.Qt.ItemDataRole.UserRole + 1)
                    self._reset_timer.start(_api._COPY_FEEDBACK_MS)
                    self._tab.list.viewport().update()
                return True  # клик по кнопке — не выделяем/не открываем строку
            # Кнопка оригинального названия.
            orig_rect = self._copy_orig_rect(option, index)
            if not orig_rect.isNull() and orig_rect.contains(pos):
                orig = index.data(_api.Qt.ItemDataRole.UserRole + 3) or ""
                if orig:
                    _api.QApplication.clipboard().setText(orig)
                    self._copied_orig_id = index.data(_api.Qt.ItemDataRole.UserRole + 1)
                    self._reset_orig_timer.start(_api._COPY_FEEDBACK_MS)
                    self._tab.list.viewport().update()
                return True
        return super().editorEvent(event, model, option, index)

_ViewsBadgeDelegate.__module__ = _api.__name__
_api._ViewsBadgeDelegate = _ViewsBadgeDelegate

# ─── Диалог выбора жанров/тем ────────────────────────────────────────────────
class _TriStateGenre(_api.QFrame):
    """Один жанр/тема как трёхпозиционный переключатель (один квадрат вместо двух
    колонок «вкл»/«искл»). Клик по строке циклически меняет состояние:
        0 — выкл (пустой квадрат, не влияет на поиск);
        1 — включить (зелёный квадрат с «✓» — показывать только с этим);
        2 — исключить (красный квадрат с «✕» — убрать из результатов).
    Третий клик возвращает в «выкл»."""

    OFF, INC, EXC = 0, 1, 2

    def __init__(self, gid, label, state=0, parent=None):
        super().__init__(parent)
        self.gid = gid
        self._label = label
        self._state = state
        self.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        h = _api.QHBoxLayout(self)
        h.setContentsMargins(6, 3, 6, 3); h.setSpacing(8)
        self._sq = _api.QLabel()
        self._sq.setFixedSize(18, 18)
        self._sq.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self._txt = _api.QLabel(label)
        h.addWidget(self._sq)
        h.addWidget(self._txt, 1)
        self._refresh()

    def state(self):
        return self._state

    def set_state(self, st):
        self._state = st % 3
        self._refresh()

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self.set_state(self._state + 1)
            e.accept()
        else:
            super().mousePressEvent(e)

    def _refresh(self):
        green = _api.C.get('green', '#a6e3a1')
        red = _api.C.get('red', '#f38ba8')
        if self._state == self.INC:
            self._sq.setText("✓")
            self._sq.setStyleSheet(
                f"background:{green}; color:#11111b; border:1px solid {green};"
                "border-radius:3px; font-weight:bold;")
            self.setToolTip(f"«{self._label}»: показывать ТОЛЬКО с этим "
                            "(клик — исключить)")
        elif self._state == self.EXC:
            self._sq.setText("✕")
            self._sq.setStyleSheet(
                f"background:{red}; color:#11111b; border:1px solid {red};"
                "border-radius:3px; font-weight:bold;")
            self.setToolTip(f"«{self._label}»: ИСКЛЮЧИТЬ из результатов "
                            "(клик — сбросить)")
        else:
            self._sq.setText("")
            self._sq.setStyleSheet(
                f"background:transparent; border:1px solid {_api.C.get('text2', '#888')};"
                "border-radius:3px;")
            self.setToolTip(f"«{self._label}»: не учитывается (клик — включить)")

_TriStateGenre.__module__ = _api.__name__
_api._TriStateGenre = _TriStateGenre
