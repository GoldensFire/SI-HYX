# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_InfoBadge. Public namespace: widgets."""
import widgets as _api


class _InfoBadge(_api.QLabel):
    """Маленький значок ⓘ. При наведении показывает подсказку (свой попап).
    Чтобы изменить текст — правьте строку в info_badge()/label_with_info()/
    row_with_info() в файле tabs.py."""
    def __init__(self, tip: str):
        super().__init__()
        self._tip = tip
        self.setObjectName("infoBadge")
        self.setCursor(_api.Qt.CursorShape.WhatsThisCursor)
        self.setFixedSize(16, 16)
        self.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        # Векторный значок-подсказка вместо эмодзи «ⓘ»; цвет переключается
        # на наведении (как раньше делал CSS color для текста).
        self._pm_normal = _api.get_icon_pixmap('fa5s.info-circle', 13, '#89b4fa')
        self._pm_hover = _api.get_icon_pixmap('fa5s.info-circle', 13, '#cba6f7')
        self.setPixmap(self._pm_normal)

    def enterEvent(self, e):
        self.setPixmap(self._pm_hover)
        try: _api._InfoTipPopup.instance().show_for(self, self._tip)
        except Exception: pass
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setPixmap(self._pm_normal)
        try: _api._InfoTipPopup.instance().hide()
        except Exception: pass
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        try: _api._InfoTipPopup.instance().show_for(self, self._tip)
        except Exception: pass
        super().mousePressEvent(e)

_InfoBadge.__module__ = _api.__name__
_api._InfoBadge = _InfoBadge

def info_badge(tip: str) -> _api.QLabel:
    """Возвращает значок-подсказку ⓘ. Текст подсказки = аргумент tip.

    Чтобы УБРАТЬ значок где-то — удалите вызов info_badge(...) в tabs.py
    (а для label_with_info/row_with_info — замените их на обычный QLabel/виджет)."""
    return _api._InfoBadge(tip)

info_badge.__module__ = _api.__name__
_api.info_badge = info_badge

class WheelBlocker(_api.QObject):
    """Глобальный фильтр событий: прокрутка над полями (спинбоксы, выпадающие
    списки, ползунки) не меняет их значения, а прокручивает ближайшую область
    прокрутки.

    `is_on` — функция без аргументов: True, если настройка «колёсико меняет
    значения в полях» включена.

    Когда настройка ВЫКЛЮЧЕНА — колесо не меняет значения никогда.

    Когда ВКЛЮЧЕНА — меняет, но не отбирая прокрутку у панели: поле должно быть
    сфокусировано, то есть в него кликнули. Иначе получалось так, как жаловался
    пользователь: правая панель настроек длинная, крутишь её колесом, а числа в
    полях, над которыми проехал курсор, молча меняются. Фокус тут надёжный
    признак «работаю именно с этим полем»: колесо фокус НЕ отдаёт (проверено на
    живом окне, см. HoverTipManager), так что сам по себе он не появится.

    Если прокручивать нечего (поле не внутри области прокрутки), колесо меняет
    значение и без фокуса — отнимать у него единственную работу незачем.
    """
    def __init__(self, parent, is_on):
        super().__init__(parent)
        self._is_on = is_on

    def eventFilter(self, obj, ev):
        try:
            if ev.type() == _api.QEvent.Type.Wheel:
                # Поднимаемся к виджету-значению (событие может прийти в дочерний)
                target = None
                p = obj
                depth = 0
                while p is not None and depth < 4:
                    if isinstance(p, (_api.QAbstractSpinBox, _api.QComboBox, _api.QSlider)):
                        target = p
                        break
                    p = p.parent() if hasattr(p, "parent") else None
                    depth += 1
                if target is None:
                    return False
                # Виджеты с пометкой wheelAlways (напр. ползунок громкости) —
                # колесо меняет значение ВСЕГДА, не блокируем.
                if target.property("wheelAlways"):
                    return False
                if self._is_on() and target.hasFocus():
                    return False        # поле выбрано кликом — крутим значение
                sa = target.parent()
                while sa is not None and not isinstance(sa, _api.QScrollArea):
                    sa = sa.parent()
                if isinstance(sa, _api.QScrollArea):
                    _api.QApplication.sendEvent(sa.viewport(), ev)
                    return True         # прокрутка панели важнее значения
                # Прокручивать нечего: при включённой настройке пусть меняет.
                return not self._is_on()
        except Exception:
            pass
        return False

WheelBlocker.__module__ = _api.__name__
_api.WheelBlocker = WheelBlocker

def combo_set_value(combo, value):
    """Выбирает в QComboBox пункт по «чистому» значению, даже если в списке
    он помечен как ' (по умолчанию)'. Используется при загрузке настроек."""
    try:
        idx = combo.findText(value)
        if idx < 0:
            idx = combo.findText(value + _api.DEFAULT_TAG)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setCurrentText(value)
    except Exception:
        pass

combo_set_value.__module__ = _api.__name__
_api.combo_set_value = combo_set_value

def label_with_info(text: str, tip: str) -> _api.QWidget:
    """Лейбл для QFormLayout.addRow с приклеенным значком ⓘ."""
    w = _api.QWidget()
    lay = _api.QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    lay.addWidget(_api.QLabel(text))
    lay.addWidget(_api.info_badge(tip))
    lay.addStretch()
    return w

label_with_info.__module__ = _api.__name__
_api.label_with_info = label_with_info

def row_with_info(widget, tip: str) -> _api.QWidget:
    """Оборачивает виджет (например, QCheckBox) + значок ⓘ в одну строку."""
    w = _api.QWidget()
    lay = _api.QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    lay.addWidget(widget)
    lay.addWidget(_api.info_badge(tip))
    lay.addStretch()
    return w

row_with_info.__module__ = _api.__name__
_api.row_with_info = row_with_info

class LocalThumbnailRunnable(_api.QRunnable):
    def __init__(self, path, iid, signal):
        super().__init__(); self.path = path; self.iid = iid; self.signal = signal
    def run(self):
        try:
            ext = _api.Path(self.path).suffix.lower()
            if ext in _api.ALLOWED_IMG and _api.Image:
                try:
                    with _api.Image.open(self.path) as im:
                        if _api.ImageOps: im = _api.ImageOps.exif_transpose(im)
                        im.thumbnail((320, 180), _api.Image.LANCZOS)
                        icon = _api.pil_to_qicon(im)
                        if not icon.isNull():
                            self.signal.emit(self.iid, icon)
                            return
                except Exception: pass
            out = _api.os.path.join(_api.TEMP_DIR, f"thumb_{self.iid}.png")
            # Сначала пробуем кадр на 1с, если файл короче — берём первый кадр
            cmd = [_api.FFMPEG, "-y", "-ss", "00:00:01", "-i", self.path, "-vframes", "1", "-vf", "scale=320:-1", "-q:v", "4", out]
            try: _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL, creationflags=_api.CREATE_NO_WINDOW, check=False, timeout=8)
            except Exception: pass
            if not _api.os.path.exists(out) or _api.os.path.getsize(out) < 100:
                # Fallback: первый доступный кадр
                cmd = [_api.FFMPEG, "-y", "-i", self.path, "-vframes", "1", "-vf", "scale=320:-1", "-q:v", "4", out]
            try: _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL, creationflags=_api.CREATE_NO_WINDOW, check=False)
            except Exception: pass
            if _api.os.path.exists(out):
                try:
                    if _api.Image:
                        with _api.Image.open(out) as im:
                            im.thumbnail((160, 90))
                            icon = _api.pil_to_qicon(im)
                            if not icon.isNull(): self.signal.emit(self.iid, icon)
                    else:
                        with open(out, "rb") as f:
                            data = f.read()
                        pix = _api.QPixmap()
                        if pix.loadFromData(data): self.signal.emit(self.iid, _api.QIcon(pix))
                except Exception: pass
                try: _api.os.remove(out)
                except Exception: pass
        except Exception: pass

LocalThumbnailRunnable.__module__ = _api.__name__
_api.LocalThumbnailRunnable = LocalThumbnailRunnable

class RemoteThumbnailRunnable(_api.QRunnable):
    def __init__(self, url, iid, signal):
        super().__init__(); self.url = url; self.iid = iid; self.signal = signal
    def run(self):
        if not self.url: return
        try:
            tmp = _api.os.path.join(_api.TEMP_DIR, f"yt_thumb_{self.iid}.tmp")
            with _api.http_get(self.url, headers={'User-Agent': _api.USER_AGENT}, timeout=20) as r, open(tmp, 'wb') as f:
                f.write(r.read())

            if _api.Image:
                with _api.Image.open(tmp) as im:
                    im.thumbnail((160, 90))
                    icon = _api.pil_to_qicon(im)
                    if not icon.isNull(): self.signal.emit(self.iid, icon)
            else:
                with open(tmp, 'rb') as f:
                    data = f.read()
                pix = _api.QPixmap()
                if pix.loadFromData(data): self.signal.emit(self.iid, _api.QIcon(pix))
            try: _api.os.remove(tmp)
            except Exception: pass
        except Exception: pass

RemoteThumbnailRunnable.__module__ = _api.__name__
_api.RemoteThumbnailRunnable = RemoteThumbnailRunnable
