# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Мелкие виджеты плеера: громкость, карточка сведений, индикатор уровня, оверлей субтитров. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api


class VolumeSlider(_api.QSlider):
    """Ползунок громкости: колёсико над ним всегда меняет громкость шагом 5
    (как и над значком динамика), независимо от глобальной опции «колесо меняет
    значения». Помечен свойством wheelAlways, чтобы WheelBlocker его не глушил.

    Клик по шкале ставит громкость РОВНО в точку клика (instant jump, как в
    плеерах), а не двигает ручку в её сторону page-step'ами — та же механика,
    что у полосы воспроизведения (см. slider_value_at)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setProperty("wheelAlways", True)
        self._dragging = False

    def wheelEvent(self, ev):
        step = 5 if ev.angleDelta().y() > 0 else -5
        self.setValue(max(self.minimum(), min(self.maximum(), self.value() + step)))
        ev.accept()

    def mousePressEvent(self, ev):
        if (ev.button() == _api.Qt.MouseButton.LeftButton
                and self.orientation() == _api.Qt.Orientation.Horizontal):
            self._dragging = True
            self.setValue(_api.slider_value_at(self, int(ev.position().x())))
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._dragging and self.orientation() == _api.Qt.Orientation.Horizontal:
            self.setValue(_api.slider_value_at(self, int(ev.position().x())))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._dragging and ev.button() == _api.Qt.MouseButton.LeftButton:
            self._dragging = False
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

VolumeSlider.__module__ = _api.__name__
_api.VolumeSlider = VolumeSlider

class VolumeLabel(_api.QLabel):
    """Значок динамика: клик выключает/включает звук (mute), прокрутка колёсиком
    меняет громкость. slider_getter — функция, возвращающая связанный QSlider
    громкости."""

    clicked = _api.pyqtSignal()

    def __init__(self, slider_getter, parent=None):
        super().__init__(parent)
        self._slider_getter = slider_getter
        self.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Клик — выключить/включить звук, колёсико — громкость")
        self.update_glyph(100)

    def update_glyph(self, vol):
        name = ('fa5s.volume-mute' if vol <= 0
                else ('fa5s.volume-down' if vol < 55 else 'fa5s.volume-up'))
        self.setPixmap(_api.get_icon_pixmap(name, 18))

    def mousePressEvent(self, ev):
        if ev.button() == _api.Qt.MouseButton.LeftButton:
            self.clicked.emit()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def wheelEvent(self, ev):
        sl = self._slider_getter() if self._slider_getter else None
        if sl is None:
            super().wheelEvent(ev)
            return
        step = 5 if ev.angleDelta().y() > 0 else -5
        sl.setValue(max(sl.minimum(), min(sl.maximum(), sl.value() + step)))
        ev.accept()

VolumeLabel.__module__ = _api.__name__
_api.VolumeLabel = VolumeLabel

# ─── Info Card ────────────────────────────────────────────────────────────────
class InfoCard(_api.QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("InfoCard")
        self.setStyleSheet(f"""
            #InfoCard {{
                background: {_api.C['surface2']};
                border: 1px solid {_api.C['border']};
                border-radius: 8px;
            }}
        """)
        layout = _api.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        title_lbl = _api.QLabel(title)
        title_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        # Заголовок не должен распирать карточку/панель по своей длине.
        _sp = title_lbl.sizePolicy(); _sp.setHorizontalPolicy(_api.QSizePolicy.Policy.Ignored)
        title_lbl.setSizePolicy(_sp)
        layout.addWidget(title_lbl)
        self._body = _api.QVBoxLayout()
        self._body.setSpacing(4)
        layout.addLayout(self._body)

    def add_row(self, label, value_attr):
        row = _api.QHBoxLayout()
        lbl = _api.QLabel(label)
        lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
        val = _api.QLabel("—")
        val.setStyleSheet(f"color: {_api.C['text']}; font-size: 12px; font-weight: 500;")
        val.setAlignment(_api.Qt.AlignmentFlag.AlignRight | _api.Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(val)
        self._body.addLayout(row)
        setattr(self, value_attr, val)
        return val

InfoCard.__module__ = _api.__name__
_api.InfoCard = InfoCard

# ─── Audio level meter (VU) ────────────────────────────────────────────────────
class AudioMeter(_api.QWidget):
    """Стерео-индикатор уровня звука: две вертикальные шкалы (зелёный→жёлтый→
    красный) с пик-маркерами и плавным спадом. Уровни 0..1 подаёт плеер во время
    воспроизведения (берутся из аудиоволны на позиции плейхеда)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(56)
        self.setMaximumWidth(96)
        self.setMinimumHeight(120)
        self._l = 0.0
        self._r = 0.0
        self._pk_l = 0.0
        self._pk_r = 0.0
        self._timer = _api.QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._decay)
        self._timer.start()

    def set_levels(self, l, r=None):
        if r is None:
            r = l
        self._l = max(0.0, min(1.0, float(l)))
        self._r = max(0.0, min(1.0, float(r)))
        if self._l > self._pk_l: self._pk_l = self._l
        if self._r > self._pk_r: self._pk_r = self._r
        self.update()

    def reset(self):
        self._l = self._r = self._pk_l = self._pk_r = 0.0
        self.update()

    def _decay(self):
        changed = False
        for a, d in (('_l', 0.08), ('_r', 0.08), ('_pk_l', 0.02), ('_pk_r', 0.02)):
            v = getattr(self, a)
            if v > 0:
                setattr(self, a, max(0.0, v - d)); changed = True
        if changed:
            self.update()

    def paintEvent(self, e):
        p = _api.QPainter(self)
        w = self.width(); h = self.height()
        p.fillRect(0, 0, w, h, _api.QColor(_api.C["bg"]))
        m_top, m_bot = 10, 16
        bar_h = max(1, h - m_top - m_bot)
        gap = 6
        bw = max(6, int((w - gap * 3) / 2))
        data = [(self._l, self._pk_l, "L"), (self._r, self._pk_r, "R")]
        for i, (lvl, pk, label) in enumerate(data):
            x = gap + i * (bw + gap)
            y = m_top
            grad = _api.QLinearGradient(0, y, 0, y + bar_h)
            grad.setColorAt(0.0, _api.QColor(_api.C["red"]))
            grad.setColorAt(0.45, _api.QColor(_api.C["yellow"]))
            grad.setColorAt(1.0, _api.QColor(_api.C["green"]))
            # Тусклый «трек» во всю высоту
            p.setOpacity(0.16); p.fillRect(x, y, bw, bar_h, _api.QBrush(grad)); p.setOpacity(1.0)
            # Яркая заполненная часть снизу до текущего уровня
            fill_h = int(bar_h * lvl)
            if fill_h > 0:
                p.setClipRect(x, y + bar_h - fill_h, bw, fill_h)
                p.fillRect(x, y, bw, bar_h, _api.QBrush(grad))
                p.setClipping(False)
            # Пик-маркер
            if pk > 0:
                py = y + bar_h - int(bar_h * pk)
                p.setPen(_api.QPen(_api.QColor(_api.C["text"]), 1))
                p.drawLine(x, py, x + bw, py)
            # Подпись канала
            p.setPen(_api.QPen(_api.QColor(_api.C["text3"])))
            f = p.font(); f.setPointSize(8); p.setFont(f)
            p.drawText(_api.QRect(x, h - m_bot + 1, bw, m_bot - 1),
                       _api.Qt.AlignmentFlag.AlignCenter, label)
        p.end()

AudioMeter.__module__ = _api.__name__
_api.AudioMeter = AudioMeter

class SubtitleOverlay(_api.QWidget):
    """Оверлей субтитров в стиле VLC/PotPlayer: белый жирный текст с чёрной
    обводкой, без подложки.

    ВАЖНО: QVideoWidget рендерит видео через нативную поверхность (RHI), поэтому
    обычный дочерний/соседний виджет рисуется ПОД видео и не виден. Чтобы текст
    стабильно был поверх кадра, оверлей сделан отдельным БЕСРАМОЧНЫМ полупрозрачным
    окном-«насадкой» со сквозным вводом, которое подгоняется под экранную область
    видео (см. EditTab._position_overlay)."""

    def __init__(self, parent=None):
        flags = (_api.Qt.WindowType.FramelessWindowHint
                 | _api.Qt.WindowType.Tool
                 | _api.Qt.WindowType.WindowStaysOnTopHint
                 | _api.Qt.WindowType.WindowTransparentForInput)
        super().__init__(parent, flags)
        self.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(_api.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(_api.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(_api.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._text = ""
        self._px = 28
        self._image = None       # кадр субтитров от libass (QImage) — приоритетнее текста
        self._image_pos = (0, 0) # позиция левого верхнего угла картинки в оверлее

    def place_over(self, widget):
        """Подгоняет окно-оверлей под экранную область целевого виджета (видео)."""
        if widget is None or not widget.isVisible():
            self.hide()
            return
        tl = widget.mapToGlobal(_api.QPoint(0, 0))
        w, h = widget.width(), widget.height()
        if w <= 1 or h <= 1:
            self.hide()
            return
        self.setGeometry(tl.x(), tl.y(), w, h)
        self.set_video_height(h)

    def set_text(self, text):
        text = text or ""
        if text != self._text:
            self._text = text
            self.update()

    def set_image(self, qimg, x=0, y=0):
        """Кадр субтитров от libass (обрезанный QImage) с позицией (x,y) в кадре,
        или None."""
        self._image = qimg
        self._image_pos = (int(x), int(y))
        self.update()

    # Единый API субтитров (совместим с VideoCanvas, см. EditTab._update_subtitle).
    def set_subtitle_image(self, qimg, x=0, y=0):
        self.set_image(qimg, x, y)

    def set_subtitle_text(self, text):
        self.set_image(None)
        self.set_text(text)

    def clear_subtitle(self):
        self._text = ""
        self.set_image(None)

    def subtitle_area_size(self):
        return self.width(), self.height()

    def set_video_height(self, h):
        px = max(15, int(h * 0.052))   # ~5% высоты кадра, как в плеерах
        if px != self._px:
            self._px = px
            self.update()

    def paintEvent(self, ev):
        p = _api.QPainter(self)
        _api._paint_subtitle(p, self.rect(), self._text, self._px,
                        self._image, self._image_pos)
        p.end()

SubtitleOverlay.__module__ = _api.__name__
_api.SubtitleOverlay = SubtitleOverlay
