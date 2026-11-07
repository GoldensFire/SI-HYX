# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Свойства проекта «Монтажа»: клип, текст и весь проект. Public namespace:
edit_tab_dialogs.

Окна правят те же поля модели montage_project, что пишет нейросеть
(montage_tool edit): клип — вписывание, место и размер на кадре,
непрозрачность, режим наложения, переход, звук и эффекты; текст — сам текст,
время, шрифт, цвета, обводка, место, анимации появления и ухода и прочие
ключи стиля text_fx; проект — формат итога, громкость и эффекты всего кадра.
Значения проходят ту же чистку, что и файл проекта (Clip.__post_init__,
sanitize_effects, parse_texts). «Применить» отдаёт правку вкладке, не
закрывая окно: в просмотре с эффектами (FX) результат виден сразу."""
import montage_project as _mp
from si_hyx_parts.montage_project import effects as _efx
from si_hyx_parts.montage_project import text_fx as _tfx

import edit_tab_dialogs as _api

_EFFECT_NAMES = {
    "zoom_punch": "Удар зумом", "push": "Наезд", "shake": "Тряска", "flash": "Вспышка",
    "rgb_shift": "Сдвиг RGB", "glow": "Свечение", "motion_blur": "Размытие движения",
    "vignette": "Виньетка", "color": "Цвет", "grain": "Зерно", "scanlines": "Сканлайны",
    "halftone": "Полутон", "glitch": "Глитч", "invert": "Негатив", "threshold": "Порог",
    "sketch": "Скетч", "hue": "Оттенок", "letterbox": "Кинополосы", "blur": "Размытие",
    "streak": "Смаз", "zoom_blur": "Радиальный смаз", "dust": "Пыль", "strobe": "Мигание",
    "viewfinder": "Видоискатель"}
_PARAM_NAMES = {
    "amount": "Сила", "decay": "Затухание, с", "sigma": "Радиус", "frames": "Кадров",
    "angle": "Угол", "contrast": "Контраст", "brightness": "Яркость",
    "saturation": "Насыщенность", "gamma": "Гамма", "period": "Период", "level": "Уровень",
    "levels": "Ступеней", "degrees": "Градусы", "spin": "Вращение, °/с", "color": "Цвет",
    "tint": "Тон", "colors": "Цвета", "curves": "Кривые", "label": "Надпись"}
_FIT_NAMES = (("", "Как у проекта"), ("fit", "Вписать"), ("fill", "Растянуть"),
              ("crop", "Заполнить с обрезкой"))
_ALIGN_NAMES = ((7, "Вверху слева"), (8, "Вверху"), (9, "Вверху справа"),
                (4, "Слева"), (5, "По центру"), (6, "Справа"),
                (1, "Внизу слева"), (2, "Внизу"), (3, "Внизу справа"))
_INT_PARAMS = ("frames", "period", "levels")


def _spin(lo, hi, value, step=0.01, decimals=3, special=None):
    sb = _api.QDoubleSpinBox()
    sb.setDecimals(decimals)
    sb.setSingleStep(step)
    if special is not None:
        sb.setRange(lo - step, hi)
        sb.setSpecialValueText(special)
    else:
        sb.setRange(lo, hi)
    sb.setValue(lo - step if value is None and special is not None else float(value))
    sb.setKeyboardTracking(False)
    return sb


def _spin_value(sb):
    """Значение спинбокса или None, если стоит особое «не задано»."""
    if sb.specialValueText() and sb.value() <= sb.minimum() + 1e-9:
        return None
    return sb.value()


class _ColorButton(_api.QPushButton):
    """Кнопка-цвет #rrggbb (QColorDialog по клику)."""

    def __init__(self, color="#ffffff", parent=None):
        super().__init__(parent)
        self.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(90)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color):
        c = _api.QColor(color or "#ffffff")
        self._color = c.name() if c.isValid() else "#ffffff"
        fg = "#000000" if _api.QColor(self._color).lightness() > 128 else "#ffffff"
        self.setText(self._color)
        self.setStyleSheet(f"QPushButton {{ background: {self._color}; color: {fg}; "
                           f"border: 1px solid {_api.C['border']}; border-radius: 4px; }}")

    def color(self):
        return self._color

    def _pick(self):
        c = _api.QColorDialog.getColor(_api.QColor(self._color), self, "Цвет")
        if c.isValid():
            self.set_color(c.name())


class EffectsEditor(_api.QWidget):
    """Список эффектов (клипа или всего кадра) и поля выбранного эффекта."""

    def __init__(self, effects, types, markers=True, parent=None):
        super().__init__(parent)
        self._effects = [dict(e) for e in effects or []]
        self._types = tuple(types)
        self._markers = markers
        self._cur = -1
        lay = _api.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        left = _api.QVBoxLayout()
        self.list = _api.QListWidget()
        self.list.setMinimumWidth(190)
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        row = _api.QHBoxLayout()
        self.btn_add = _api.QPushButton("Добавить")
        menu = _api.QMenu(self.btn_add)
        for t in self._types:
            menu.addAction(_EFFECT_NAMES.get(t, t), lambda t=t: self._add(t))
        self.btn_add.setMenu(menu)
        self.btn_del = _api.QPushButton("Удалить")
        self.btn_del.clicked.connect(self._delete)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_del)
        left.addLayout(row)
        lay.addLayout(left)
        self.form_box = _api.QWidget()
        self.form = _api.QFormLayout(self.form_box)
        lay.addWidget(self.form_box, 1)
        self._fields = {}
        self._refill()

    @staticmethod
    def _label(e):
        name = _EFFECT_NAMES.get(e.get("type"), e.get("type", "?"))
        on = e.get("on")
        if isinstance(on, str):
            name += f" · по «{on}»"
        elif isinstance(on, list):
            name += f" · {len(on)} моментов"
        if e.get("section"):
            name += f" · {e['section']}"
        return name

    def _refill(self):
        self.list.blockSignals(True)
        self.list.clear()
        for e in self._effects:
            self.list.addItem(self._label(e))
        self.list.blockSignals(False)
        row = min(self._cur, len(self._effects) - 1)
        self._cur = -1
        if row >= 0:
            self.list.setCurrentRow(row)
        self._select(row)
        self.btn_del.setEnabled(bool(self._effects))

    def _add(self, t):
        self._store()
        self._effects.append({"type": t})
        self._cur = len(self._effects) - 1
        self._refill()

    def _delete(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._effects):
            self._effects.pop(row)
            self._cur = row
            self._fields = {}
            self._refill()

    def _clear_form(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self._fields = {}

    def _select(self, row):
        self._store()
        self._clear_form()
        self._cur = row
        if not 0 <= row < len(self._effects):
            return
        e = self._effects[row]
        params = _efx.effect_params({"type": e["type"]})
        params.update(e)
        if self._markers:
            on = _api.QComboBox()
            on.addItem("Весь клип", None)
            for k in _mp.MARKER_KINDS:
                on.addItem(f"По маркерам «{k}»", k)
            if isinstance(e.get("on"), list):
                on.addItem(f"Свои моменты ({len(e['on'])})", "__list__")
            idx = on.findData("__list__" if isinstance(e.get("on"), list) else e.get("on"))
            on.setCurrentIndex(max(0, idx))
            self.form.addRow("Когда", on)
            self._fields["on"] = on
            sec = _api.QLineEdit(e.get("section", ""))
            sec.setPlaceholderText("часть песни: chorus, drop… (пусто — везде)")
            self.form.addRow("Часть", sec)
            self._fields["section"] = sec
        for k, v in params.items():
            if k in ("type", "on", "section", "hold", "lut"):
                continue
            if k in ("color", "tint"):
                w = _ColorButton(v)
            elif k == "colors":
                w = (_ColorButton(v[0]), _ColorButton(v[1]))
                box = _api.QWidget()
                hl = _api.QHBoxLayout(box)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.addWidget(w[0])
                hl.addWidget(w[1])
                self.form.addRow(_PARAM_NAMES[k], box)
                self._fields[k] = w
                continue
            elif k == "curves":
                w = _api.QComboBox()
                w.addItems(list(_mp.CURVES_PRESETS))
                w.setCurrentText(str(v))
            elif k == "label":
                w = _api.QLineEdit(str(v or ""))
                w.setPlaceholderText("латиница, цифры, / . -")
                w.setMaxLength(40)
            elif k in _mp.EFFECT_LIMITS:
                lo, hi = _mp.EFFECT_LIMITS[k]
                integer = k in _INT_PARAMS
                w = _spin(lo, hi, v, step=1 if integer else 0.01, decimals=0 if integer else 3)
            else:
                continue
            self.form.addRow(_PARAM_NAMES.get(k, k), w)
            self._fields[k] = w

    def _store(self):
        """Поля формы — в выбранный эффект."""
        if not 0 <= self._cur < len(self._effects) or not self._fields:
            return
        e = {"type": self._effects[self._cur]["type"]}
        old = self._effects[self._cur]
        for k, w in self._fields.items():
            if k == "on":
                data = w.currentData()
                if data == "__list__":
                    e["on"] = old.get("on")
                elif data:
                    e["on"] = data
            elif k == "section":
                if w.text().strip():
                    e["section"] = w.text().strip()
            elif isinstance(w, tuple):
                e[k] = [w[0].color(), w[1].color()]
            elif isinstance(w, _ColorButton):
                e[k] = w.color()
            elif isinstance(w, _api.QComboBox):
                e[k] = w.currentText()
            elif isinstance(w, _api.QLineEdit):
                if w.text().strip():
                    e[k] = w.text().strip()
            else:
                e[k] = int(w.value()) if k in _INT_PARAMS else w.value()
        for k in ("hold", "lut"):
            if k in old:
                e[k] = old[k]
        self._effects[self._cur] = e
        item = self.list.item(self._cur)
        if item is not None:
            item.setText(self._label(e))

    def effects(self):
        self._store()
        return [e for e in (_mp.sanitize_effect(e) for e in self._effects) if e]


class _PropsDialog(_api.QDialog):
    """Окно свойств: вкладки полей и OK / Применить / Отмена. on_apply(values)
    получает собранные значения; OK — применить и закрыть."""

    def __init__(self, title, on_apply, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self._on_apply = on_apply
        lay = _api.QVBoxLayout(self)
        self.tabs = _api.QTabWidget()
        lay.addWidget(self.tabs, 1)
        bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Ok
                                   | _api.QDialogButtonBox.StandardButton.Apply
                                   | _api.QDialogButtonBox.StandardButton.Cancel)
        bb.button(_api.QDialogButtonBox.StandardButton.Apply).setText("Применить")
        bb.button(_api.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        bb.button(_api.QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        lay.addWidget(bb)

    def _page(self, title):
        page = _api.QWidget()
        form = _api.QFormLayout(page)
        self.tabs.addTab(page, title)
        return form

    def values(self):
        raise NotImplementedError

    def _apply(self):
        self._on_apply(self.values())

    def _ok(self):
        self._apply()
        self.accept()


class ClipPropsDialog(_PropsDialog):
    """Свойства клипа: вид, переход, звук, эффекты."""

    def __init__(self, clip, on_main, on_apply, parent=None):
        super().__init__(f"Клип: {clip.name}", on_apply, parent)
        c = clip
        f = self._page("Картинка")
        self.fit = _api.QComboBox()
        for key, name in _FIT_NAMES:
            self.fit.addItem(name, key)
        self.fit.setCurrentIndex(max(0, self.fit.findData(c.fit)))
        f.addRow("Вписывание", self.fit)
        self.pos_x = _spin(-1.0, 2.0, c.pos_x)
        self.pos_y = _spin(-1.0, 2.0, c.pos_y)
        self.scale = _spin(_mp.MIN_SCALE, _mp.MAX_SCALE, c.scale)
        self.opacity = _spin(0.0, 1.0, c.opacity)
        for name, w in (("Центр X (доля кадра)", self.pos_x), ("Центр Y (доля кадра)", self.pos_y),
                        ("Размер (доля кадра)", self.scale), ("Непрозрачность", self.opacity)):
            w.setEnabled(not on_main)
            f.addRow(name, w)
        self.blend = _api.QComboBox()
        self.blend.addItem("Обычный", "")
        for m in _mp.BLEND_MODES:
            if m != "normal":
                self.blend.addItem(m, m)
        self.blend.setCurrentIndex(max(0, self.blend.findData(c.blend)))
        self.blend.setEnabled(not on_main)
        f.addRow("Наложение", self.blend)
        self.reverse = _api.QCheckBox("Задом наперёд")
        self.reverse.setChecked(c.reverse)
        self.reverse.setEnabled(c.has_video and not c.is_image)
        f.addRow("", self.reverse)
        if on_main:
            f.addRow("", _api.QLabel("Место, размер и наложение — у клипов верхних дорожек."))

        f = self._page("Переход")
        self.transition = _api.QComboBox()
        self.transition.addItem("Нет", "")
        for t in _mp.TRANSITIONS:
            self.transition.addItem(t, t)
        self.transition.setCurrentIndex(max(0, self.transition.findData(c.transition)))
        self.transition_s = _spin(0.0, 5.0, c.transition_s)
        for w in (self.transition, self.transition_s):
            w.setEnabled(on_main)
        f.addRow("Переход в этот клип", self.transition)
        f.addRow("Длина, с", self.transition_s)
        if not on_main:
            f.addRow("", _api.QLabel("Переходы — между клипами основной дорожки."))

        f = self._page("Звук")
        self.volume = _spin(0.0, 4.0, c.volume)
        self.muted = _api.QCheckBox("Без звука")
        self.muted.setChecked(c.muted)
        self.fade_in = _spin(0.0, 30.0, c.fade_in)
        self.fade_out = _spin(0.0, 30.0, c.fade_out)
        f.addRow("Громкость (1 — как есть)", self.volume)
        f.addRow("", self.muted)
        f.addRow("Нарастание, с", self.fade_in)
        f.addRow("Затухание, с", self.fade_out)
        for w in (self.volume, self.muted, self.fade_in, self.fade_out):
            w.setEnabled(bool(c.audio_path))

        self.fx = EffectsEditor(c.effects, _mp.EFFECT_TYPES, markers=True)
        self.tabs.addTab(self.fx, "Эффекты")
        self.fx.setEnabled(c.has_video)

    def values(self):
        return {"fit": self.fit.currentData(), "pos_x": self.pos_x.value(),
                "pos_y": self.pos_y.value(), "scale": self.scale.value(),
                "opacity": self.opacity.value(), "blend": self.blend.currentData(),
                "reverse": self.reverse.isChecked(),
                "transition": self.transition.currentData(),
                "transition_s": self.transition_s.value(), "volume": self.volume.value(),
                "muted": self.muted.isChecked(), "fade_in": self.fade_in.value(),
                "fade_out": self.fade_out.value(), "effects": self.fx.effects()}


class TextPropsDialog(_PropsDialog):
    """Свойства текста проекта: текст и время, вид, место, анимация, ещё."""

    def __init__(self, item, on_apply, parent=None):
        super().__init__("Текст проекта", on_apply, parent)
        st = dict(_api.DEFAULT_SUBTITLE_STYLE)
        st.update(item.style or {})
        self._style0 = dict(item.style or {})
        f = self._page("Текст")
        self.text = _api.QPlainTextEdit(item.text)
        self.text.setMinimumHeight(80)
        f.addRow("Текст", self.text)
        self.start = _spin(0.0, 86400.0, item.start)
        self.end = _spin(0.0, 86400.0, item.end)
        f.addRow("Начало, с", self.start)
        f.addRow("Конец, с", self.end)

        f = self._page("Вид")
        self.font = _api.QFontComboBox()
        self.font.setCurrentFont(_api.QFont(str(st.get("font") or "")))
        f.addRow("Шрифт", self.font)
        self.size = _spin(2.0, 400.0, float(st.get("size") or 21), step=1, decimals=1)
        f.addRow("Кегль (кадр 288 в высоту)", self.size)
        self.bold = _api.QCheckBox("Жирный")
        self.bold.setChecked(bool(st.get("bold")))
        self.italic = _api.QCheckBox("Курсив")
        self.italic.setChecked(bool(st.get("italic")))
        row = _api.QHBoxLayout()
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        row.addStretch(1)
        f.addRow("", row)
        self.color = _ColorButton(st.get("color"))
        self.outline_color = _ColorButton(st.get("outline_color"))
        f.addRow("Цвет", self.color)
        f.addRow("Цвет обводки", self.outline_color)
        self.outline = _spin(0.0, 20.0, float(st.get("outline") or 0), step=0.1, decimals=2)
        self.shadow = _spin(0.0, 20.0, float(st.get("shadow") or 0), step=0.1, decimals=2)
        f.addRow("Обводка", self.outline)
        f.addRow("Тень", self.shadow)
        self.spacing = _spin(-20.0, 50.0, float(st.get("spacing") or 0), step=0.5, decimals=1)
        f.addRow("Межбуквенный", self.spacing)

        f = self._page("Место")
        self.align = _api.QComboBox()
        for val, name in _ALIGN_NAMES:
            self.align.addItem(name, val)
        self.align.setCurrentIndex(max(0, self.align.findData(int(st.get("align") or 2))))
        f.addRow("Выравнивание", self.align)
        self.own_pos = _api.QCheckBox("Своя точка в кадре")
        self.own_pos.setChecked(item.pos_x is not None and item.pos_y is not None)
        f.addRow("", self.own_pos)
        self.pos_x = _spin(0.0, 1.0, item.pos_x if item.pos_x is not None else 0.5)
        self.pos_y = _spin(0.0, 1.0, item.pos_y if item.pos_y is not None else 0.85)
        f.addRow("X (доля кадра)", self.pos_x)
        f.addRow("Y (доля кадра)", self.pos_y)
        self.own_pos.toggled.connect(self.pos_x.setEnabled)
        self.own_pos.toggled.connect(self.pos_y.setEnabled)
        self.pos_x.setEnabled(self.own_pos.isChecked())
        self.pos_y.setEnabled(self.own_pos.isChecked())

        f = self._page("Анимация")
        self.anim = _api.QComboBox()
        self.anim.addItems(list(_tfx.ANIMATIONS))
        self.anim.setCurrentText(str(st.get("animation") or "none"))
        f.addRow("Появление", self.anim)
        self.anim_out = _api.QComboBox()
        self.anim_out.addItems(list(_tfx.OUT_ANIMATIONS))
        self.anim_out.setCurrentText(str(st.get("out") or "none"))
        f.addRow("Уход", self.anim_out)

        # Остальные числовые ключи стиля text_fx: «—» — не задано (как в файле).
        f = self._page("Ещё")
        self.extra = {}
        for k, (typ, lo, hi) in _tfx.STYLE_KEYS.items():
            if typ is float:
                step = 0.01 if hi <= 3.0 else 0.5
                w = _spin(lo, hi, st.get(k), step=step, decimals=2, special="—")
                f.addRow(k, w)
                self.extra[k] = w
            elif typ is bool:
                w = _api.QCheckBox()
                w.setChecked(bool(st.get(k)))
                f.addRow(k, w)
                self.extra[k] = w
            elif k in _tfx.COLOR_KEYS:
                w = _ColorButton(st.get(k) or "#ffffff")
                chk = _api.QCheckBox("задать")
                chk.setChecked(bool(st.get(k)))
                row = _api.QHBoxLayout()
                row.addWidget(chk)
                row.addWidget(w)
                row.addStretch(1)
                f.addRow(k, row)
                self.extra[k] = (chk, w)

    def values(self):
        style = dict(self._style0)
        style.update({"font": self.font.currentFont().family(), "size": self.size.value(),
                      "bold": self.bold.isChecked(), "italic": self.italic.isChecked(),
                      "color": self.color.color(), "outline_color": self.outline_color.color(),
                      "outline": self.outline.value(), "shadow": self.shadow.value(),
                      "spacing": self.spacing.value(), "align": int(self.align.currentData()),
                      "animation": self.anim.currentText()})
        if self.anim_out.currentText() != "none":
            style["out"] = self.anim_out.currentText()
        else:
            style.pop("out", None)
        for k, w in self.extra.items():
            if isinstance(w, tuple):
                if w[0].isChecked():
                    style[k] = w[1].color()
                else:
                    style.pop(k, None)
            elif isinstance(w, _api.QCheckBox):
                if w.isChecked():
                    style[k] = True
                else:
                    style.pop(k, None)
            else:
                v = _spin_value(w)
                if v is None:
                    style.pop(k, None)
                else:
                    style[k] = v
        own = self.own_pos.isChecked()
        return {"text": self.text.toPlainText(), "start": self.start.value(),
                "end": self.end.value(), "style": style,
                "pos_x": self.pos_x.value() if own else None,
                "pos_y": self.pos_y.value() if own else None}


class ProjectSettingsDialog(_PropsDialog):
    """Настройки проекта: формат итога, громкость, эффекты всего кадра."""

    def __init__(self, project, on_apply, parent=None):
        super().__init__("Настройки проекта", on_apply, parent)
        s = project.settings
        f = self._page("Формат")
        self.width = _api.QSpinBox()
        self.width.setRange(0, 8192)
        self.width.setSpecialValueText("по первому клипу")
        self.width.setValue(int(s.width))
        self.height = _api.QSpinBox()
        self.height.setRange(0, 8192)
        self.height.setSpecialValueText("по первому клипу")
        self.height.setValue(int(s.height))
        self.fps = _spin(0.0, 240.0, float(s.fps), step=1, decimals=3)
        self.fps.setSpecialValueText("по первому клипу")
        f.addRow("Ширина", self.width)
        f.addRow("Высота", self.height)
        f.addRow("Кадров в секунду", self.fps)
        self.fit = _api.QComboBox()
        for key, name in _FIT_NAMES[1:]:
            self.fit.addItem(name, key)
        self.fit.setCurrentIndex(max(0, self.fit.findData(s.fit)))
        f.addRow("Вписывание", self.fit)
        self.background = _ColorButton(s.background)
        f.addRow("Фон", self.background)

        f = self._page("Звук")
        self.loudness = _spin(-40.0, -5.0, s.loudness, step=1, decimals=1, special="как есть")
        f.addRow("Громкость итога, LUFS", self.loudness)
        self.duck = _spin(0.0, 1.0, float(s.duck), step=0.05, decimals=2)
        f.addRow("Голос приглушает музыку", self.duck)

        self.fx = EffectsEditor(s.finish, _mp.FINISH_TYPES, markers=False)
        self.tabs.addTab(self.fx, "Эффекты кадра")

    def values(self):
        return {"width": self.width.value(), "height": self.height.value(),
                "fps": self.fps.value(), "fit": self.fit.currentData(),
                "background": self.background.color(), "loudness": _spin_value(self.loudness),
                "duck": self.duck.value(), "finish": self.fx.effects()}


ClipPropsDialog.__module__ = _api.__name__
TextPropsDialog.__module__ = _api.__name__
ProjectSettingsDialog.__module__ = _api.__name__
EffectsEditor.__module__ = _api.__name__
