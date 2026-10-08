# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Сравнение видео рядом и ползунок перехода. Public namespace: widgets."""
import widgets as _api


def show_video_compare(src_path, out_path, parent=None, use_filenames=False):
    """Открывает сравнение исходного и перекодированного видео в полноэкранном
    просмотрщике (видео-аналог show_image_compare). use_filenames=True —
    подписи показывают имена файлов вместо «Исходник»/«Результат»."""
    dlg = _api.VideoCompareViewer(src_path, out_path, parent, use_filenames)
    return _api._present_fullscreen(dlg, parent)

show_video_compare.__module__ = _api.__name__
_api.show_video_compare = show_video_compare

class _JumpSlider(_api.QSlider):
    """QSlider, который при клике по дорожке СРАЗУ прыгает в точку клика.
    Стандартный QSlider лишь шагает на pageStep — поэтому при значении 100 и
    клике у отметки 10 ползунок «полз» к 80, а не вставал на 10. Здесь клик и
    протаскивание по дорожке выставляют значение по позиции курсора."""

    def _value_at(self, ev):
        opt = _api.QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            _api.QStyle.ComplexControl.CC_Slider, opt,
            _api.QStyle.SubControl.SC_SliderGroove, self)
        handle = self.style().subControlRect(
            _api.QStyle.ComplexControl.CC_Slider, opt,
            _api.QStyle.SubControl.SC_SliderHandle, self)
        if self.orientation() == _api.Qt.Orientation.Horizontal:
            pos = int(ev.position().x() - groove.x() - handle.width() / 2)
            span = groove.width() - handle.width()
        else:
            pos = int(ev.position().y() - groove.y() - handle.height() / 2)
            span = groove.height() - handle.height()
        return _api.QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), pos, max(1, span), opt.upsideDown)

    def mousePressEvent(self, ev):
        if ev.button() == _api.Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(ev))
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if ev.buttons() & _api.Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(ev))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

_JumpSlider.__module__ = _api.__name__
_api._JumpSlider = _JumpSlider
