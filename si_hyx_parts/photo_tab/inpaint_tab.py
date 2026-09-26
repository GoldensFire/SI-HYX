# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintTab. Public namespace: photo_tab."""
import photo_tab as _api


class InpaintTab(_api.QWidget):
    """Подвкладка «Удаление объектов»: закрашиваете кистью водяной знак/надпись —
    нейросеть LaMa аккуратно «дорисовывает» фон под ним."""

    from si_hyx_parts.photo_tab.inpaint_tab___init import __init__, _build_unavailable

    from si_hyx_parts.photo_tab.inpaint_tab__build_ui import _build_ui, _tool_btn, _tool_row

    from si_hyx_parts.photo_tab.inpaint_tab__make_flyout import (
        _make_flyout,
        _build_shape_flyout,
        _build_text_flyout,
        _update_text_color_swatch,
        _update_stroke_color_swatch,
        _active_text_obj,
        _on_text_selected,
        _pick_text_color,
        _pick_stroke_color,
        _update_text_stroke,
        _on_shapes_btn,
        _on_text_btn,
        _pick_shape,
        _show_flyout,
        insert_mode_switch,
        _update_color_swatch,
        _pick_brush_color,
        _update_text_font,
        _on_color_picked,
        _activate_delete_tool,
        _on_stroke_finished,
        _set_tool,
    )

    _VK_Z = 0x5A
    _VK_Y = 0x59

    from si_hyx_parts.photo_tab.inpaint_tab_key_press_event import (
        keyPressEvent,
        _on_brush,
        _on_blur_strength,
        _set_status,
        set_left_width,
        _refresh_enabled,
        _open,
        _ribbon_folder,
        _clear_canvas,
        _load,
        add_paths,
        dragEnterEvent,
        dropEvent,
        _choose_out_dir,
        _output_path,
        _save,
        _show_saved_toast,
        _show_toast,
        showEvent,
        hideEvent,
        set_keep_models,
        _touch,
        eventFilter,
        _models_busy,
        _maybe_unload_models,
        _kick_warmup,
    )

    from si_hyx_parts.photo_tab.inpaint_tab__on_warmed import (
        _on_warmed,
        _on_warm_failed,
        _run_inpaint,
        _show_proc_chip,
        _proc_tick,
        _finish_proc,
        _position_proc_chip,
        _hide_proc_chip,
        _cancel_proc,
        _on_progress,
        _on_done,
        _on_failed,
        _remove_black_bars,
    )

    from si_hyx_parts.photo_tab.inpaint_tab__remove_bg import (
        _remove_bg,
        _on_bg_done,
        _on_bg_failed,
    )

InpaintTab.__module__ = _api.__name__
_api.InpaintTab = InpaintTab

class _PhotoModeSwitch(_api.QWidget):
    """Сегментный переключатель режима вкладки «Редактирование фото»
    (Редактирование фото / Объединить фото). Живёт в ЛЕВОЙ панели каждой
    подвкладки вместо верхней полосы вкладок.

    Обе кнопки имеют ОДИНАКОВУЮ фиксированную ширину (по самой длинной подписи),
    поэтому переключатель выглядит идентично в обоих режимах, а длинные подписи
    видны целиком. Порядок: сперва «Редактирование фото», затем «Объединить фото»."""

    def __init__(self, on_pick):
        super().__init__()
        lay = _api.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        self.btn_inpaint = _api._icon_btn("Редактирование фото", 'fa5s.magic', size=16)
        self.btn_merge = _api._icon_btn("Объединить фото", 'fa5s.object-group', size=16)
        # Одинаковая ширина обеих кнопок = ширина по самой длинной подписи
        # (+значок, отступы, рамка), чтобы текст не обрезался и режимы выглядели
        # одинаково. Меряем ЖИРНЫМ шрифтом: активная кнопка делает текст жирным,
        # и по обычным метрикам ширины не хватало — подпись обрезалась.
        fb = _api.QFont(self.btn_inpaint.font()); fb.setBold(True)
        fmb = _api.QFontMetrics(fb)
        need = max(fmb.horizontalAdvance(self.btn_inpaint.text()),
                   fmb.horizontalAdvance(self.btn_merge.text()))
        # значок(16) + отступ значок-текст + горизонтальные паддинги/рамка + запас.
        # +56 ≈ естественная ширина по sizeHint с поправкой на жирный шрифт (раньше
        # стоял избыточный +78 — панель была шире, чем нужно).
        btn_w = need + 56
        for b in (self.btn_inpaint, self.btn_merge):
            b.setCheckable(True)
            b.setFixedWidth(btn_w)
            b.setSizePolicy(_api.QSizePolicy.Policy.Fixed, _api.QSizePolicy.Policy.Fixed)
            lay.addWidget(b)
        lay.addStretch(1)
        self.btn_inpaint.clicked.connect(lambda: on_pick(1))
        self.btn_merge.clicked.connect(lambda: on_pick(0))
        # Сколько места нужно левой панели, чтобы переключатель влез целиком.
        self.needed_width = btn_w * 2 + 6

    def set_index(self, idx):
        self.btn_merge.setChecked(idx == 0)
        self.btn_inpaint.setChecked(idx == 1)

_PhotoModeSwitch.__module__ = _api.__name__
_api._PhotoModeSwitch = _PhotoModeSwitch

class PhotoTab(_api.QWidget):
    """Контейнер вкладки «Фото» с подвкладками: объединение фото и удаление
    объектов (LaMa). Переключение между ними — не верхней полосой вкладок, а
    сегментным переключателем в ЛЕВОЙ панели каждой подвкладки. По умолчанию
    открывается «Удаление объектов». Сохраняет старое поведение: add_paths/
    file routing идут в подвкладку объединения."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        lay = _api.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.inner = _api.QTabWidget()
        self.merger = _api.PhotoMergerTab(main_window)
        self.inpaint = _api.InpaintTab(main_window)
        # Индексы: 0 — объединение, 1 — редактирование фото (LaMa/кадрирование).
        self.inner.addTab(self.merger, _api.get_icon('fa5s.object-group'), "Объединить фото")
        self.inner.addTab(self.inpaint, _api.get_icon('fa5s.magic'), "Редактирование фото")
        self.inner.tabBar().hide()           # переключаем из левой панели, не сверху
        lay.addWidget(self.inner)

        # Переключатель режима — в левой панели каждой подвкладки.
        self._switches = []
        sw_merge = _api._PhotoModeSwitch(self._set_mode)
        self.merger.insert_mode_switch(sw_merge); self._switches.append(sw_merge)
        if hasattr(self.inpaint, "insert_mode_switch"):
            sw_inp = _api._PhotoModeSwitch(self._set_mode)
            self.inpaint.insert_mode_switch(sw_inp); self._switches.append(sw_inp)

        # Левые панели обеих подвкладок — одинаковой ширины, достаточной, чтобы
        # переключатель режима помещался целиком (обе подписи видны).
        panel_w = max((s.needed_width for s in self._switches), default=540) + 10
        if hasattr(self.merger, "set_left_width"):
            self.merger.set_left_width(panel_w)
        if hasattr(self.inpaint, "set_left_width"):
            self.inpaint.set_left_width(panel_w)

        # По умолчанию — «Редактирование фото».
        self._set_mode(1)

        # Прозрачная пересылка к подвкладке объединения — на случай внешних
        # вызовов tab_photo.add_paths / .file_list (drag-n-drop, недавние файлы).
        self.file_list = self.merger.file_list

    def _set_mode(self, idx):
        self.inner.setCurrentIndex(idx)
        for s in self._switches:
            s.set_index(idx)

    def add_paths(self, paths):
        # Файлы — это объединение фото: переключаемся на него и показываем.
        self._set_mode(0)
        self.merger.add_paths(paths)

    def accept_dropped_paths(self, paths):
        """Бросок файла на заголовок вкладки «Редактирование фото»: добавляем в
        АКТИВНУЮ подвкладку (редактор фото / объединение), а не насильно в
        объединение — иначе drop на режиме редактора уводил бы в другой режим."""
        if self.inner.currentIndex() == 1 and hasattr(self.inpaint, "add_paths"):
            self.inpaint.add_paths(paths)
        else:
            self.add_paths(paths)

PhotoTab.__module__ = _api.__name__
_api.PhotoTab = PhotoTab
