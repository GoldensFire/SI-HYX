# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Делегаты таблиц: цвет статуса и имя предпросмотра. Public namespace: widgets."""
import widgets as _api


class StatusColorDelegate(_api.QStyledItemDelegate):
    """Делегат, рисующий цветной фон строки независимо от стилшита.
    
    Стилшит: ::item:selected и ::item:hover — transparent.
    Все фоны рисуем здесь вручную, чтобы цвет статуса всегда был виден.
    """
    _colors  = {'proc': _api.COLOR_PROC, 'done': _api.COLOR_DONE, 'err': _api.COLOR_ERR}
    _SEL_BG  = _api.QColor(0x45, 0x47, 0x5a)   # обычное выделение (#45475a)
    _HOV_BG  = _api.QColor(0x31, 0x32, 0x44)   # hover (#313244)

    def _paint_bg(self, painter, option, index):
        """Рисует фон строки (статус-цвет / выделение / hover). Вынесено отдельно,
        чтобы наследники (PreviewNameDelegate) рисовали тот же фон под своей
        кастомной разметкой."""
        src = index.sibling(index.row(), 0)
        status = src.data(_api.ITEM_STATUS_ROLE)
        color  = self._colors.get(status)
        is_sel = bool(option.state & _api.QStyle.StateFlag.State_Selected)
        is_hov = bool(option.state & _api.QStyle.StateFlag.State_MouseOver)

        if color:
            # Цветная строка: всегда показываем статус-цвет
            if is_sel:
                # Выделение цветной строки: ЗАТЕМНЯЕМ статус-цвет, а не осветляем.
                # Осветление давало почти белый фон, на котором светлый текст
                # («Готово», «Было/Стало», размеры) «засвечивался» и не читался.
                # Тёмный насыщенный фон + светлый текст = выделение видно, надписи
                # читаются.
                bg = _api.QColor(color).darker(150)
                bg.setAlpha(255)
            else:
                bg = color  # переиспользуем объект из словаря без копирования
            painter.save()
            painter.fillRect(option.rect, bg)
            painter.restore()
        else:
            # Обычная строка: имитируем стандартное поведение
            if is_sel:
                painter.save()
                painter.fillRect(option.rect, self._SEL_BG)
                painter.restore()
            elif is_hov:
                painter.save()
                painter.fillRect(option.rect, self._HOV_BG)
                painter.restore()

    def paint(self, painter, option, index):
        self._paint_bg(painter, option, index)

        # Рисуем текст / иконку поверх нашего фона
        super().paint(painter, option, index)

StatusColorDelegate.__module__ = _api.__name__
_api.StatusColorDelegate = StatusColorDelegate

        # Выделение цветной строки показано осветлением фона выше — резкую
        # белую рамку не рисуем.


class PreviewNameDelegate(_api.StatusColorDelegate):
    """Колонка «Превью» на странице обработки: миниатюра сверху, имя файла —
    под ней одной строкой с многоточием при нехватке ширины. Полное имя
    остаётся в тултипе ячейки.

    Для обработанных картинок (роль ITEM_COMPARE_ROLE) рисует в правом нижнем
    углу превью значок «сравнить» — по клику открывается сравнение исходника и
    результата (сигнал compare_clicked)."""
    _NAME_COLOR = _api.QColor(0xcd, 0xd6, 0xf4)  # #cdd6f4
    _BADGE = 24                              # сторона значка-сравнения, px

    compare_clicked = _api.pyqtSignal(object)     # QModelIndex обработанной картинки

    def __init__(self, parent=None):
        super().__init__(parent)
        # Анимация наведения на значок «сравнить»: _hover_iid — id строки, чей
        # значок под курсором; _hover_t (0..1) — фаза, гонится таймером к цели.
        self._hover_iid = None
        self._hover_t = 0.0
        self._hover_target = 0.0
        self._anim_timer = _api.QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_hover)

    def set_badge_hover(self, iid):
        """Дерево сообщает, над чьим значком сравнения курсор (или None)."""
        if iid == self._hover_iid:
            return
        self._hover_iid = iid
        self._hover_target = 1.0 if iid is not None else 0.0
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _tick_hover(self):
        step = 0.16
        if self._hover_t < self._hover_target:
            self._hover_t = min(self._hover_target, self._hover_t + step)
        elif self._hover_t > self._hover_target:
            self._hover_t = max(self._hover_target, self._hover_t - step)
        else:
            self._anim_timer.stop()
        v = self.parent()
        if v is not None and hasattr(v, 'viewport'):
            v.viewport().update()

    @classmethod
    def _badge_rect(cls, rect, fm):
        """Квадрат значка «сравнить» в правом нижнем углу области превью.
        Считается так же, как геометрия картинки в paint(), чтобы клик попадал
        ровно по нарисованному значку."""
        pad = 4
        text_h = (fm.height() + 2)
        icon_h = max(0, rect.height() - 2 * pad - text_h)
        bx = rect.left() + rect.width() - pad - cls._BADGE - 2
        by = rect.top() + pad + icon_h - cls._BADGE - 2
        return _api.QRect(int(bx), int(by), cls._BADGE, cls._BADGE)

    def paint(self, painter, option, index):
        self._paint_bg(painter, option, index)
        painter.save()
        rect = option.rect
        pad  = 4
        fm   = option.fontMetrics
        name = index.data(_api.Qt.ItemDataRole.DisplayRole) or ""
        text_h = (fm.height() + 2) if name else 0

        icon = index.data(_api.Qt.ItemDataRole.DecorationRole)
        # Аудио (нет видеоряда → нет превью): не резервируем место под картинку,
        # имя рисуем по центру компактной строки.
        audio_only = bool(index.data(_api.ITEM_AUDIO_ROLE))
        has_icon = isinstance(icon, _api.QIcon) and not icon.isNull()
        icon_h = max(0, rect.height() - 2 * pad - text_h)
        # Низ картинки — чтобы подпись шла сразу под ней (без большого зазора).
        img_bottom = rect.top() + pad
        icon_w = max(0, rect.width() - 2 * pad)
        if isinstance(icon, _api.QIcon) and not icon.isNull() and icon_h > 0 and icon_w > 0:
            pm = icon.pixmap(_api.QSize(icon_w, icon_h))
            if not pm.isNull():
                # ВАЖНО: pm.width()/height() — в ФИЗИЧЕСКИХ пикселях (на HiDPI
                # экране в devicePixelRatio раз больше логических), а painter
                # рисует в ЛОГИЧЕСКИХ. Раньше центрирование считалось по
                # физическому размеру → картинка съезжала влево/вверх и
                # «налезала» на соседнюю строку. Берём логический размер.
                dpr = pm.devicePixelRatio() or 1.0
                w = int(round(pm.width() / dpr))
                h = int(round(pm.height() / dpr))
                x = rect.left() + (rect.width() - w) // 2
                y = rect.top() + pad + (icon_h - h) // 2
                painter.drawPixmap(_api.QRect(x, y, w, h), pm)
                img_bottom = y + h

        if name:
            # Аудио без превью — имя по центру строки; иначе сразу под картинкой.
            if audio_only and not has_icon:
                ty = rect.top() + (rect.height() - text_h) // 2
            else:
                # Подпись — сразу под картинкой (не приклеена ко дну ячейки).
                ty = min(img_bottom + 2, rect.bottom() - text_h - pad)
            avail = rect.width() - 2 * pad
            fits = fm.horizontalAdvance(name) <= avail
            painter.setPen(self._NAME_COLOR)
            if fits:
                # Помещается целиком — центрируем.
                tr = _api.QRect(rect.left() + pad, ty, avail, text_h)
                painter.drawText(tr, int(_api.Qt.AlignmentFlag.AlignHCenter
                                         | _api.Qt.AlignmentFlag.AlignVCenter), name)
            else:
                # Длинное имя — от самого левого края, почти без отступа, с «…».
                tr = _api.QRect(rect.left() + 1, ty, rect.width() - 2, text_h)
                elided = fm.elidedText(name, _api.Qt.TextElideMode.ElideRight, tr.width())
                painter.drawText(tr, int(_api.Qt.AlignmentFlag.AlignLeft
                                         | _api.Qt.AlignmentFlag.AlignVCenter), elided)

        # Значок «сравнить» в углу превью обработанной картинки. При наведении
        # на него (см. дерево → set_badge_hover) значок слегка увеличивается и
        # подсвечивается синим акцентом — небольшая анимация интерактивности.
        if index.data(_api.ITEM_COMPARE_ROLE):
            br = self._badge_rect(rect, fm)
            iid = index.data(_api.Qt.ItemDataRole.UserRole)
            t = self._hover_t if (self._hover_iid is not None
                                  and iid == self._hover_iid) else 0.0
            painter.setRenderHint(_api.QPainter.RenderHint.Antialiasing, True)
            if t > 0.001:
                grow = int(round(2.0 * t))
                br = br.adjusted(-grow, -grow, grow, grow)
            pen_c = _api.QColor(int(0x58 + (0x89 - 0x58) * t),
                           int(0x5b + (0xb4 - 0x5b) * t),
                           int(0x70 + (0xfa - 0x70) * t))
            painter.setPen(_api.QPen(pen_c))
            painter.setBrush(_api.QColor(24, 24, 37, int(215 + 40 * t)))
            painter.drawRoundedRect(br, 5, 5)
            ic = 14 + int(round(3 * t))
            icol = _api.QColor(int(0xcd + (0x89 - 0xcd) * t),
                          int(0xd6 + (0xb4 - 0xd6) * t),
                          int(0xf4 + (0xfa - 0xf4) * t))
            pm = _api.get_icon_pixmap('fa5s.columns', ic, icol.name())
            if not pm.isNull():
                px = br.left() + (br.width() - ic) // 2
                py = br.top() + (br.height() - ic) // 2
                painter.drawPixmap(_api.QRect(px, py, ic, ic), pm)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        # Клик по значку «сравнить» в углу превью → сигнал в MediaTab.
        try:
            if (event.type() == _api.QEvent.Type.MouseButtonRelease
                    and index.data(_api.ITEM_COMPARE_ROLE)
                    and event.button() == _api.Qt.MouseButton.LeftButton):
                pos = event.position().toPoint()
                if self._badge_rect(option.rect, option.fontMetrics).contains(pos):
                    self.compare_clicked.emit(index)
                    return True
        except Exception:
            pass
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        line = option.fontMetrics.height() + 2
        # Аудио без превью — компактная строка (только имя + отступы), без
        # резерва 90px под миниатюру: «зелёная полоса» результата не раздувается.
        if bool(index.data(_api.ITEM_AUDIO_ROLE)):
            return _api.QSize(s.width(), line + 10)
        extra = line + 8  # строка имени + отступы
        return _api.QSize(s.width(), max(s.height(), 90) + extra)

PreviewNameDelegate.__module__ = _api.__name__
_api.PreviewNameDelegate = PreviewNameDelegate
