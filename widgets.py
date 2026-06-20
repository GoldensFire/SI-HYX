# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# widgets.py — кастомные виджеты, делегаты, превью, info-подсказки
from config import *
from utils import *
from PyQt6.QtWidgets import QSizePolicy


class SmallIconDelegate(QStyledItemDelegate):
    """Делегат для колонок со статус-иконкой. Дерево загрузок выставляет
    крупный iconSize (160×90) для превью в 0-й колонке — без этого делегата
    значок статуса («галочка Готово») наследовал бы тот же размер и раздувался
    на всю строку. Здесь принудительно ограничиваем размер декорации."""
    def __init__(self, size=20, parent=None):
        super().__init__(parent)
        self._sz = QSize(size, size)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.decorationSize = self._sz


class StatusColorDelegate(QStyledItemDelegate):
    """Делегат, рисующий цветной фон строки независимо от стилшита.
    
    Стилшит: ::item:selected и ::item:hover — transparent.
    Все фоны рисуем здесь вручную, чтобы цвет статуса всегда был виден.
    """
    _colors  = {'proc': COLOR_PROC, 'done': COLOR_DONE, 'err': COLOR_ERR}
    _SEL_BG  = QColor(0x45, 0x47, 0x5a)   # обычное выделение (#45475a)
    _HOV_BG  = QColor(0x31, 0x32, 0x44)   # hover (#313244)

    def _paint_bg(self, painter, option, index):
        """Рисует фон строки (статус-цвет / выделение / hover). Вынесено отдельно,
        чтобы наследники (PreviewNameDelegate) рисовали тот же фон под своей
        кастомной разметкой."""
        src = index.sibling(index.row(), 0)
        status = src.data(ITEM_STATUS_ROLE)
        color  = self._colors.get(status)
        is_sel = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hov = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if color:
            # Цветная строка: всегда показываем статус-цвет
            if is_sel:
                # Выделение цветной строки: ЗАТЕМНЯЕМ статус-цвет, а не осветляем.
                # Осветление давало почти белый фон, на котором светлый текст
                # («Готово», «Было/Стало», размеры) «засвечивался» и не читался.
                # Тёмный насыщенный фон + светлый текст = выделение видно, надписи
                # читаются.
                bg = QColor(color).darker(150)
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

        # Выделение цветной строки показано осветлением фона выше — резкую
        # белую рамку не рисуем.


class PreviewNameDelegate(StatusColorDelegate):
    """Колонка «Превью» на странице обработки: миниатюра сверху, имя файла —
    под ней одной строкой с многоточием при нехватке ширины. Полное имя
    остаётся в тултипе ячейки.

    Для обработанных картинок (роль ITEM_COMPARE_ROLE) рисует в правом нижнем
    углу превью значок «сравнить» — по клику открывается сравнение исходника и
    результата (сигнал compare_clicked)."""
    _NAME_COLOR = QColor(0xcd, 0xd6, 0xf4)  # #cdd6f4
    _BADGE = 24                              # сторона значка-сравнения, px

    compare_clicked = pyqtSignal(object)     # QModelIndex обработанной картинки

    def __init__(self, parent=None):
        super().__init__(parent)
        # Анимация наведения на значок «сравнить»: _hover_iid — id строки, чей
        # значок под курсором; _hover_t (0..1) — фаза, гонится таймером к цели.
        self._hover_iid = None
        self._hover_t = 0.0
        self._hover_target = 0.0
        self._anim_timer = QTimer(self)
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
        return QRect(int(bx), int(by), cls._BADGE, cls._BADGE)

    def paint(self, painter, option, index):
        self._paint_bg(painter, option, index)
        painter.save()
        rect = option.rect
        pad  = 4
        fm   = option.fontMetrics
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        text_h = (fm.height() + 2) if name else 0

        icon = index.data(Qt.ItemDataRole.DecorationRole)
        icon_h = max(0, rect.height() - 2 * pad - text_h)
        # Низ картинки — чтобы подпись шла сразу под ней (без большого зазора).
        img_bottom = rect.top() + pad
        if isinstance(icon, QIcon) and not icon.isNull() and icon_h > 0:
            pm = icon.pixmap(QSize(rect.width() - 2 * pad, icon_h))
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
                painter.drawPixmap(QRect(x, y, w, h), pm)
                img_bottom = y + h

        if name:
            # Подпись — сразу под картинкой (не приклеена ко дну ячейки).
            ty = min(img_bottom + 2, rect.bottom() - text_h - pad)
            avail = rect.width() - 2 * pad
            fits = fm.horizontalAdvance(name) <= avail
            painter.setPen(self._NAME_COLOR)
            if fits:
                # Помещается целиком — центрируем.
                tr = QRect(rect.left() + pad, ty, avail, text_h)
                painter.drawText(tr, int(Qt.AlignmentFlag.AlignHCenter
                                         | Qt.AlignmentFlag.AlignVCenter), name)
            else:
                # Длинное имя — от самого левого края, почти без отступа, с «…».
                tr = QRect(rect.left() + 1, ty, rect.width() - 2, text_h)
                elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, tr.width())
                painter.drawText(tr, int(Qt.AlignmentFlag.AlignLeft
                                         | Qt.AlignmentFlag.AlignVCenter), elided)

        # Значок «сравнить» в углу превью обработанной картинки. При наведении
        # на него (см. дерево → set_badge_hover) значок слегка увеличивается и
        # подсвечивается синим акцентом — небольшая анимация интерактивности.
        if index.data(ITEM_COMPARE_ROLE):
            br = self._badge_rect(rect, fm)
            iid = index.data(Qt.ItemDataRole.UserRole)
            t = self._hover_t if (self._hover_iid is not None
                                  and iid == self._hover_iid) else 0.0
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if t > 0.001:
                grow = int(round(2.0 * t))
                br = br.adjusted(-grow, -grow, grow, grow)
            pen_c = QColor(int(0x58 + (0x89 - 0x58) * t),
                           int(0x5b + (0xb4 - 0x5b) * t),
                           int(0x70 + (0xfa - 0x70) * t))
            painter.setPen(QPen(pen_c))
            painter.setBrush(QColor(24, 24, 37, int(215 + 40 * t)))
            painter.drawRoundedRect(br, 5, 5)
            ic = 14 + int(round(3 * t))
            icol = QColor(int(0xcd + (0x89 - 0xcd) * t),
                          int(0xd6 + (0xb4 - 0xd6) * t),
                          int(0xf4 + (0xfa - 0xf4) * t))
            pm = get_icon_pixmap('fa5s.columns', ic, icol.name())
            if not pm.isNull():
                px = br.left() + (br.width() - ic) // 2
                py = br.top() + (br.height() - ic) // 2
                painter.drawPixmap(QRect(px, py, ic, ic), pm)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        # Клик по значку «сравнить» в углу превью → сигнал в MediaTab.
        try:
            if (event.type() == QEvent.Type.MouseButtonRelease
                    and index.data(ITEM_COMPARE_ROLE)
                    and event.button() == Qt.MouseButton.LeftButton):
                pos = event.position().toPoint()
                if self._badge_rect(option.rect, option.fontMetrics).contains(pos):
                    self.compare_clicked.emit(index)
                    return True
        except Exception:
            pass
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        extra = option.fontMetrics.height() + 2 + 8  # строка имени + отступы
        return QSize(s.width(), max(s.height(), 90) + extra)


class LatinKeySequenceEdit(QKeySequenceEdit):
    """QKeySequenceEdit, который пишет буквы/цифры по ФИЗИЧЕСКОЙ клавише
    (латиница), а не по текущей раскладке: Shift+Y на русской раскладке даёт
    «Shift+Y», а не «Shift+Н». Для остальных клавиш (F-ряд, стрелки и пр.) —
    штатное поведение базового класса."""
    _MODS = (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta)
    _KBD = (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)

    def keyPressEvent(self, ev):
        # Windows VK: 0x30..0x39 = '0'..'9', 0x41..0x5A = 'A'..'Z' — не зависят от
        # раскладки. Берём латинский символ напрямую по физической клавише.
        vk = ev.nativeVirtualKey()
        latin = chr(vk) if (0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39) else None
        if latin is not None and ev.key() not in self._MODS:
            try:
                key_enum = getattr(Qt.Key, f"Key_{latin}")
                mods = ev.modifiers() & self._KBD
                self.setKeySequence(QKeySequence(int(mods.value) | int(key_enum.value)))
                ev.accept()
                return
            except Exception:
                pass
        super().keyPressEvent(ev)


# --- Custom ComboBox для инвертированного скролла битрейта ---
class InvertedWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        idx = self.currentIndex()
        if event.angleDelta().y() > 0:  # Вверх → повысить битрейт
            if idx < self.count() - 1:
                self.setCurrentIndex(idx + 1)
        else:                            # Вниз → понизить битрейт
            if idx > 0:
                self.setCurrentIndex(idx - 1)
        event.accept()


# --- Custom SpinBox для 01, 02... ---
class ZeroSpinBox(QSpinBox):
    def textFromValue(self, val):
        return f"{val:02d}"


# --- Custom SpinBox для Скорости (100, 105, 107, 110) ---
class SpeedSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.allowed_steps = [100, 105, 107, 110]
        self.setRange(1, 500)
    
    def wheelEvent(self, event):
        current_val = self.value()
        angle = event.angleDelta().y()
        
        if angle > 0: 
            next_val = next((x for x in self.allowed_steps if x > current_val), None)
            if next_val:
                self.setValue(next_val)
            else:
                if current_val < 500: self.setValue(current_val + 1)
        else:
            prev_val = next((x for x in reversed(self.allowed_steps) if x < current_val), None)
            if prev_val:
                self.setValue(prev_val)
            else:
                if current_val > 1: self.setValue(current_val - 1)
        
        event.accept()


# --- Информационные подсказки "ⓘ" для пунктов настроек ---
class _InfoTipPopup(QLabel):
    """Единый всплывающий ярлык-подсказка для значков ⓘ.

    Почему не QToolTip: его глобальный менеджер на крошечном виджете реагирует
    на каждое микродвижение мыши, повторно показывая/пряча окно — отсюда
    «мерцание» и «подлагивание» первые 1-2 секунды. Здесь собственный
    фреймлес-попап: прозрачен для мыши и не активируется, показывается строго
    по enter и прячется по leave значка — циклов enter/leave не возникает."""
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = _InfoTipPopup()
        return cls._instance

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWordWrap(True)
        self.setMaximumWidth(360)
        self.setObjectName("infoTip")
        self.setStyleSheet(
            "#infoTip{background:#1e1e2e;color:#cdd6f4;border:1px solid #585b70;"
            "border-radius:6px;padding:6px 8px;font-size:12px;}")

    def show_for(self, badge, text):
        self.setText(text)
        self.adjustSize()
        # Ниже-правее значка — курсор на значке не попадёт на попап (иначе цикл).
        gp = badge.mapToGlobal(badge.rect().bottomLeft())
        x, y = gp.x(), gp.y() + 4
        try:
            scr = badge.screen().availableGeometry()
            if x + self.width() > scr.right(): x = scr.right() - self.width() - 4
            if x < scr.left(): x = scr.left() + 4
        except Exception:
            pass
        self.move(x, y); self.show(); self.raise_()

    def show_at(self, global_point, text):
        """Показывает подсказку у заданной глобальной точки (напр. у курсора над
        ячейкой дерева). Тот же стабильный попап, что и у значков ⓘ."""
        if not text:
            return
        self.setText(text)
        self.adjustSize()
        x, y = global_point.x() + 16, global_point.y() + 18
        try:
            scr = QApplication.screenAt(global_point)
            sg = scr.availableGeometry() if scr else None
            if sg is not None:
                if x + self.width() > sg.right(): x = sg.right() - self.width() - 4
                if x < sg.left(): x = sg.left() + 4
                if y + self.height() > sg.bottom(): y = global_point.y() - self.height() - 6
        except Exception:
            pass
        self.move(x, y); self.show(); self.raise_()


class HoverTipManager(QObject):
    """Глобальный фильтр событий: заменяет системные QToolTip на тот же
    стабильный фирменный попап, что и у значков ⓘ (_InfoTipPopup). QToolTip
    реагирует на каждое микродвижение мыши и потому мерцает/подлагивает; здесь
    же попап показывается один раз по событию ToolTip и прячется по уходу
    курсора — без мерцания. Достаточно установить на QApplication, и ВСЕ
    виджеты с setToolTip(...) автоматически получают стабильную подсказку."""

    def eventFilter(self, obj, ev):
        try:
            et = ev.type()
            if et == QEvent.Type.ToolTip:
                tip = obj.toolTip() if isinstance(obj, QWidget) else ""
                if tip:
                    _InfoTipPopup.instance().show_for(obj, tip)
                    return True  # подавляем системный QToolTip (источник мерцания)
                # Пустая подсказка (напр. значок ⓘ управляет попапом сам) — не трогаем.
                return False
            if et in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress,
                      QEvent.Type.Wheel, QEvent.Type.Hide,
                      QEvent.Type.WindowDeactivate):
                _InfoTipPopup.instance().hide()
        except Exception:
            pass
        return False


def install_hover_tips(app):
    """Ставит HoverTipManager на приложение (один экземпляр живёт с приложением)."""
    try:
        mgr = HoverTipManager(app)
        app._hover_tip_mgr = mgr  # держим ссылку, чтобы не собрался GC
        app.installEventFilter(mgr)
    except Exception:
        pass


class _InfoBadge(QLabel):
    """Маленький значок ⓘ. При наведении показывает подсказку (свой попап).
    Чтобы изменить текст — правьте строку в info_badge()/label_with_info()/
    row_with_info() в файле tabs.py."""
    def __init__(self, tip: str):
        super().__init__()
        self._tip = tip
        self.setObjectName("infoBadge")
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setFixedSize(16, 16)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Векторный значок-подсказка вместо эмодзи «ⓘ»; цвет переключается
        # на наведении (как раньше делал CSS color для текста).
        self._pm_normal = get_icon_pixmap('fa5s.info-circle', 13, '#89b4fa')
        self._pm_hover = get_icon_pixmap('fa5s.info-circle', 13, '#cba6f7')
        self.setPixmap(self._pm_normal)

    def enterEvent(self, e):
        self.setPixmap(self._pm_hover)
        try: _InfoTipPopup.instance().show_for(self, self._tip)
        except Exception: pass
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setPixmap(self._pm_normal)
        try: _InfoTipPopup.instance().hide()
        except Exception: pass
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        try: _InfoTipPopup.instance().show_for(self, self._tip)
        except Exception: pass
        super().mousePressEvent(e)


def info_badge(tip: str) -> QLabel:
    """Возвращает значок-подсказку ⓘ. Текст подсказки = аргумент tip.

    Чтобы УБРАТЬ значок где-то — удалите вызов info_badge(...) в tabs.py
    (а для label_with_info/row_with_info — замените их на обычный QLabel/виджет)."""
    return _InfoBadge(tip)


class WheelBlocker(QObject):
    """Глобальный фильтр событий: когда колёсико «выключено», прокрутка над
    полями (спинбоксы, выпадающие списки, ползунки) НЕ меняет их значения,
    а прокручивает ближайшую область прокрутки. Когда «включено» — обычное
    поведение (колесо меняет значение).
    `is_on` — функция без аргументов, возвращающая True, если колесо разрешено."""
    def __init__(self, parent, is_on):
        super().__init__(parent)
        self._is_on = is_on

    def eventFilter(self, obj, ev):
        try:
            if ev.type() == QEvent.Type.Wheel and not self._is_on():
                # Поднимаемся к виджету-значению (событие может прийти в дочерний)
                target = None
                p = obj
                depth = 0
                while p is not None and depth < 4:
                    if isinstance(p, (QAbstractSpinBox, QComboBox, QSlider)):
                        target = p
                        break
                    p = p.parent() if hasattr(p, "parent") else None
                    depth += 1
                # Виджеты с пометкой wheelAlways (напр. ползунок громкости) —
                # колесо меняет значение ВСЕГДА, не блокируем.
                if target is not None and target.property("wheelAlways"):
                    return False
                if target is not None:
                    sa = target.parent()
                    while sa is not None and not isinstance(sa, QScrollArea):
                        sa = sa.parent()
                    if isinstance(sa, QScrollArea):
                        QApplication.sendEvent(sa.viewport(), ev)
                    return True  # блокируем изменение значения колесом
        except Exception:
            pass
        return False


def combo_set_value(combo, value):
    """Выбирает в QComboBox пункт по «чистому» значению, даже если в списке
    он помечен как ' (по умолчанию)'. Используется при загрузке настроек."""
    try:
        idx = combo.findText(value)
        if idx < 0:
            idx = combo.findText(value + DEFAULT_TAG)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setCurrentText(value)
    except Exception:
        pass


def label_with_info(text: str, tip: str) -> QWidget:
    """Лейбл для QFormLayout.addRow с приклеенным значком ⓘ."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    lay.addWidget(QLabel(text))
    lay.addWidget(info_badge(tip))
    lay.addStretch()
    return w


def row_with_info(widget, tip: str) -> QWidget:
    """Оборачивает виджет (например, QCheckBox) + значок ⓘ в одну строку."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    lay.addWidget(widget)
    lay.addWidget(info_badge(tip))
    lay.addStretch()
    return w


class LocalThumbnailRunnable(QRunnable):
    def __init__(self, path, iid, signal):
        super().__init__(); self.path = path; self.iid = iid; self.signal = signal
    def run(self):
        try:
            ext = Path(self.path).suffix.lower()
            if ext in ALLOWED_IMG and Image:
                try:
                    with Image.open(self.path) as im:
                        if ImageOps: im = ImageOps.exif_transpose(im)
                        im.thumbnail((320, 180), Image.LANCZOS)
                        icon = pil_to_qicon(im)
                        if not icon.isNull():
                            self.signal.emit(self.iid, icon)
                            return
                except Exception: pass
            out = os.path.join(TEMP_DIR, f"thumb_{self.iid}.png")
            # Сначала пробуем кадр на 1с, если файл короче — берём первый кадр
            cmd = [FFMPEG, "-y", "-ss", "00:00:01", "-i", self.path, "-vframes", "1", "-vf", "scale=320:-1", "-q:v", "4", out]
            try: subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, check=False, timeout=8)
            except Exception: pass
            if not os.path.exists(out) or os.path.getsize(out) < 100:
                # Fallback: первый доступный кадр
                cmd = [FFMPEG, "-y", "-i", self.path, "-vframes", "1", "-vf", "scale=320:-1", "-q:v", "4", out]
            try: subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, check=False)
            except Exception: pass
            if os.path.exists(out):
                try:
                    if Image:
                        with Image.open(out) as im:
                            im.thumbnail((160, 90))
                            icon = pil_to_qicon(im)
                            if not icon.isNull(): self.signal.emit(self.iid, icon)
                    else:
                        with open(out, "rb") as f:
                            data = f.read()
                        pix = QPixmap()
                        if pix.loadFromData(data): self.signal.emit(self.iid, QIcon(pix))
                except Exception: pass
                try: os.remove(out)
                except Exception: pass
        except Exception: pass


class RemoteThumbnailRunnable(QRunnable):
    def __init__(self, url, iid, signal):
        super().__init__(); self.url = url; self.iid = iid; self.signal = signal
    def run(self):
        if not self.url: return
        try:
            tmp = os.path.join(TEMP_DIR, f"yt_thumb_{self.iid}.tmp")
            with http_get(self.url, headers={'User-Agent': USER_AGENT}, timeout=20) as r, open(tmp, 'wb') as f:
                f.write(r.read())

            if Image:
                with Image.open(tmp) as im:
                    im.thumbnail((160, 90))
                    icon = pil_to_qicon(im)
                    if not icon.isNull(): self.signal.emit(self.iid, icon)
            else:
                with open(tmp, 'rb') as f:
                    data = f.read()
                pix = QPixmap()
                if pix.loadFromData(data): self.signal.emit(self.iid, QIcon(pix))
            try: os.remove(tmp)
            except Exception: pass
        except Exception: pass


class _RecentThumbWorker(QRunnable):
    """Готовит миниатюру в фоне (ffmpeg/ffprobe/PIL) и отдаёт БАЙТЫ изображения
    в GUI-поток через сигнал. QPixmap нельзя создавать вне главного потока, поэтому
    из воркера возвращаются именно байты, а пиксмап строится в слоте."""
    def __init__(self, path, signal):
        super().__init__()
        self.path = path
        self.signal = signal

    def run(self):
        data = None
        dur_str = ""
        try:
            ext = os.path.splitext(self.path)[1].lower()
            if ext == '.svg':
                # PIL не умеет SVG — растеризуем вектор через QtSvg (QImage, не
                # QPixmap — допустимо вне GUI-потока) и отдаём байты PNG.
                try:
                    im = rasterize_svg(self.path, max_dim=256)
                    if im is not None:
                        im.thumbnail((96, 72))
                        bio = io.BytesIO()
                        im.convert("RGBA").save(bio, "PNG")
                        data = bio.getvalue()
                except Exception:
                    pass
            elif ext in ALLOWED_IMG and Image:
                try:
                    with Image.open(self.path) as im:
                        im.thumbnail((96, 72))
                        bio = io.BytesIO()
                        im.convert("RGBA").save(bio, "PNG")
                        data = bio.getvalue()
                except Exception:
                    pass
            if data is None:
                tmp = os.path.join(TEMP_DIR, f"rft_{uuid.uuid4().hex}.jpg")
                # Пробуем несколько позиций: 1с → 0с (для коротких клипов)
                for seek in ("00:00:01", "00:00:00"):
                    cmd = [FFMPEG, "-y", "-ss", seek, "-i", self.path,
                           "-vframes", "1", "-vf", "scale=96:-2", "-q:v", "3", tmp]
                    try:
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=CREATE_NO_WINDOW, timeout=8)
                    except Exception:
                        pass
                    if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                        try:
                            with open(tmp, "rb") as f:
                                data = f.read()
                        except Exception:
                            pass
                        try: os.remove(tmp)
                        except Exception: pass
                        if data:
                            break
                    else:
                        try:
                            if os.path.exists(tmp): os.remove(tmp)
                        except Exception: pass
                try:
                    probe = subprocess.run(
                        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", self.path],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, creationflags=CREATE_NO_WINDOW, timeout=4)
                    d = float(probe.stdout.strip() or 0)
                    if d > 0:
                        h = int(d // 3600); m = int((d % 3600) // 60); s = int(d % 60)
                        dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.signal.emit(data, dur_str)
        except Exception:
            pass


class RecentFileThumb(QWidget):
    """Карточка в стрипе: миниатюра + тип-значок + имя файла."""

    _ICON_VIDEO = "fa5s.film"
    _ICON_IMAGE = "fa5s.image"
    _ICON_AUDIO = "fa5s.music"

    _thumb_ready = pyqtSignal(object, str)  # (bytes|None, dur_str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setFixedSize(108, 108)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(path)
        self._drag_start = None
        self._thumb_attempts = 0
        self._last_seen_size = -1   # для дозаписываемых файлов (Filmora и пр.)
        self._has_thumb = False     # получена ли настоящая миниатюра

        ext = os.path.splitext(path)[1].lower()
        is_img   = ext in RIBBON_IMG
        is_video = not is_img and ext in {'.mp4', '.mkv', '.avi', '.mov', '.webm',
                                           '.flv', '.wmv', '.m4v', '.ts', '.mts',
                                           '.m2ts', '.vob', '.ogv', '.3gp'}
        self._type_icon = self._ICON_IMAGE if is_img else (self._ICON_VIDEO if is_video else self._ICON_AUDIO)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        # Контейнер миниатюры с бейджем типа
        thumb_container = QWidget()
        thumb_container.setFixedHeight(72)
        tc_layout = QHBoxLayout(thumb_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)

        ext_disp = os.path.splitext(path)[1].lstrip('.').upper() or '—'
        self._ext_txt = ext_disp
        try: self._size_str = human_size(os.path.getsize(path))
        except Exception: self._size_str = ""
        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedSize(96, 72)
        self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_lbl.setTextFormat(Qt.TextFormat.RichText)
        # Прозрачный фон: у миниатюр с «неподходящим» соотношением сторон (не 4:3)
        # пиксмап масштабируется с сохранением пропорций и не заполняет 96×72 —
        # раньше по бокам/сверху проступал серый прямоугольник #1e1e1e. Теперь
        # незаполненная область прозрачна и сливается с карточкой.
        self._thumb_lbl.setStyleSheet("background:transparent;border-radius:3px;")
        self._thumb_lbl.setText(self._placeholder_html())  # значок типа + расширение, пока нет превью
        tc_layout.addWidget(self._thumb_lbl)

        # Имя файла
        name = os.path.basename(path)
        short = (name[:15] + "…") if len(name) > 15 else name
        name_lbl = QLabel(f"{icon_html(self._type_icon, 10, '#cccccc')} {short}")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(False)
        name_lbl.setStyleSheet("color:#ccc;font-size:8px;")
        name_lbl.setToolTip(name)

        layout.addWidget(thumb_container)
        layout.addWidget(name_lbl)

        # Дочерние элементы прозрачны для мыши — чтобы перетаскивание (drag) в очередь
        # и клики ловила сама карточка, а не QLabel внутри (иначе drag не стартует).
        for _w in (thumb_container, self._thumb_lbl, name_lbl):
            _w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Прозрачная рамка 1px уже в обычном состоянии: при наведении меняется
        # только ЦВЕТ рамки, а не геометрия. Иначе добавление рамки на :hover
        # сдвигало содержимое на 1px → переразметка → мерцание/лаг (как было у ⓘ).
        self.setStyleSheet("RecentFileThumb{background:#2a2a2a;border-radius:5px;"
                           "border:1px solid transparent;}"
                           "RecentFileThumb:hover{background:#363636;border:1px solid #555;}")

        # Загрузка миниатюры в фоне (через QThreadPool — НЕ блокирует GUI при старте)
        self._thumb_ready.connect(self._apply_thumb)
        QThreadPool.globalInstance().start(_RecentThumbWorker(self.path, self._thumb_ready))

    def _placeholder_html(self):
        """HTML-заглушка превью: крупный значок типа + расширение файла снизу."""
        return (f"<div style='line-height:25px;'>{icon_html(self._type_icon, 24, '#cdd6f4')}</div>"
                f"<div style='font-size:9px; color:#9399b2;'>{self._ext_txt}</div>"
                f"<div style='font-size:9px; color:#7f849c;'>{self._size_str}</div>")

    def _refresh_size(self):
        """Перечитать размер файла (мог вырасти, пока шла генерация миниатюры)."""
        try:
            self._size_str = human_size(os.path.getsize(self.path))
        except Exception:
            pass

    def _apply_thumb(self, data, dur_str):
        """Слот в GUI-потоке: строит QPixmap из байтов и рисует длительность."""
        try:
            # Размер мог измениться с момента создания карточки (Filmora и др.
            # пишут файл постепенно) — всегда показываем актуальный.
            self._refresh_size()
            if not data:
                self._thumb_lbl.setText(self._placeholder_html())
                try: cur = os.path.getsize(self.path)
                except Exception: cur = -1
                if cur != self._last_seen_size:
                    # Файл ещё дозаписывается (размер растёт) — сбрасываем счётчик
                    # и продолжаем ждать готовности, сколько бы ни длилась запись.
                    self._last_seen_size = cur
                    self._thumb_attempts = 0
                    QTimer.singleShot(1500, self._retry_thumb)
                elif self._thumb_attempts < 8:
                    # Размер стабилен, но превью пока нет (файл занят) — ещё попытки.
                    self._thumb_attempts += 1
                    QTimer.singleShot(1500, self._retry_thumb)
                return
            pix = QPixmap()
            if not pix.loadFromData(QByteArray(data)):
                return
            pix = pix.scaled(96, 72, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            if dur_str:
                painter = QPainter(pix)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                font = QFont(); font.setPointSize(7); font.setBold(True)
                painter.setFont(font)
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(dur_str) + 6
                th = fm.height() + 2
                tx = pix.width() - tw - 2
                ty = pix.height() - th - 2
                painter.fillRect(tx, ty, tw, th, QColor(0, 0, 0, 160))
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.drawText(tx + 3, ty + th - 3, dur_str)
                painter.end()
            # Бейдж размера файла — верхний левый угол (минимум в КБ)
            if self._size_str:
                p2 = QPainter(pix)
                p2.setRenderHint(QPainter.RenderHint.Antialiasing)
                f2 = QFont(); f2.setPointSize(7); f2.setBold(True); p2.setFont(f2)
                fm2 = p2.fontMetrics()
                sw = fm2.horizontalAdvance(self._size_str) + 6
                sh = fm2.height() + 1
                p2.fillRect(2, 2, sw, sh, QColor(0, 0, 0, 160))
                p2.setPen(QPen(QColor(255, 255, 255)))
                p2.drawText(2 + 3, 2 + sh - 3, self._size_str)
                p2.end()
            self._thumb_lbl.setText("")
            self._thumb_lbl.setPixmap(pix)
            self._has_thumb = True
        except Exception:
            pass

    def recheck_pending(self):
        """Периодический пинг от стрипа (раз в 5 c): если миниатюры ещё нет,
        а размер файла изменился — значит файл дописали (ffmpeg пишет moov-атом
        mp4 только в конце, до этого файл «висит» крошечным). Обновляем размер и
        пробуем снова. ffmpeg-воркер запускаем только при изменении размера —
        для готовых/безвидеошных файлов лишних запусков нет."""
        if self._has_thumb:
            return
        try:
            cur = os.path.getsize(self.path)
        except Exception:
            return
        if cur != self._last_seen_size:
            self._last_seen_size = cur
            self._refresh_size()
            self._thumb_lbl.setText(self._placeholder_html())  # показать актуальный размер
            self._thumb_attempts = 0
            self._retry_thumb()

    def _retry_thumb(self):
        """Повторная попытка сделать миниатюру (файл мог быть занят/недописан)."""
        try:
            if os.path.exists(self.path):
                QThreadPool.globalInstance().start(_RecentThumbWorker(self.path, self._thumb_ready))
        except Exception:
            pass

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.pos()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_start = None
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_start is not None and (e.pos() - self._drag_start).manhattanLength() > 6:
            self._drag_start = None
            from PyQt6.QtCore import QMimeData, QUrl
            from PyQt6.QtGui import QDrag
            drag = QDrag(self)
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(self.path)])
            drag.setMimeData(md)
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
        super().mouseMoveEvent(e)

    def mouseDoubleClickEvent(self, e):
        try:
            p = self
            while p and not hasattr(p, 'add_paths'):
                p = p.parent()
            if p: p.add_paths([self.path])
        except Exception: pass

    # ── Контекстное меню (ПКМ) с действиями над файлом ──────────────────────
    def contextMenuEvent(self, e):
        m = QMenu(self)
        a_add = m.addAction(get_icon('fa5s.plus'), "Добавить в активную вкладку")
        a_open = m.addAction(get_icon('fa5s.play'), "Открыть в системе")
        a_folder = m.addAction(get_icon('fa5s.folder-open'), "Показать в папке")
        m.addSeparator()
        a_copy_path = m.addAction(get_icon('fa5s.clipboard'), "Копировать путь")
        a_copy_file = m.addAction(get_icon('fa5s.copy'), "Копировать файл (в буфер)")
        a_rename = m.addAction(get_icon('fa5s.pen'), "Переименовать…")
        m.addSeparator()
        a_delete = m.addAction(get_icon('fa5s.trash'), "Удалить файл")
        chosen = m.exec(e.globalPos())
        if chosen is None:
            return
        if chosen is a_add:
            self.mouseDoubleClickEvent(None)
        elif chosen is a_open:
            self._action_open()
        elif chosen is a_folder:
            self._action_show_in_folder()
        elif chosen is a_copy_path:
            QApplication.clipboard().setText(self.path)
        elif chosen is a_copy_file:
            self._action_copy_file()
        elif chosen is a_rename:
            self._action_rename()
        elif chosen is a_delete:
            self._action_delete()

    def _action_open(self):
        try:
            if os.name == 'nt':
                os.startfile(self.path)  # noqa
            else:
                subprocess.Popen(["xdg-open", self.path])
        except Exception:
            pass

    def _action_show_in_folder(self):
        try:
            if os.name == 'nt':
                subprocess.Popen(["explorer", "/select,", os.path.normpath(self.path)])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(self.path)])
        except Exception:
            pass

    def _action_copy_file(self):
        """Кладёт сам файл (как URL) в буфер обмена — можно вставить в проводник."""
        try:
            from PyQt6.QtCore import QMimeData, QUrl
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(self.path)])
            QApplication.clipboard().setMimeData(md)
        except Exception:
            pass

    def _action_rename(self):
        try:
            old = os.path.basename(self.path)
            new, ok = QInputDialog.getText(self, "Переименовать", "Новое имя файла:", text=old)
            if not ok or not new.strip() or new == old:
                return
            new = new.strip()
            dst = os.path.join(os.path.dirname(self.path), new)
            if os.path.exists(dst):
                QMessageBox.warning(self, "Переименование", "Файл с таким именем уже существует.")
                return
            os.rename(self.path, dst)
            self.path = dst
            self.setToolTip(dst)
        except Exception as ex:
            QMessageBox.warning(self, "Переименование", f"Не удалось переименовать:\n{ex}")

    def _action_delete(self):
        # Без подтверждения: файл уходит в Корзину (откуда его можно вернуть),
        # поэтому диалог «вы уверены?» не нужен.
        try:
            if move_to_trash(self.path):
                # Карточку уберёт автообновление стрипа (poll), а саму скрываем сразу.
                self.hide()
            else:
                QMessageBox.warning(self, "Удаление",
                                    f"Не удалось отправить файл в Корзину:\n"
                                    f"{os.path.basename(self.path)}")
        except Exception as ex:
            QMessageBox.warning(self, "Удаление", f"Не удалось удалить:\n{ex}")


class RecentFilesStrip(QWidget):
    """Горизонтальный стрип последних файлов из папки.
    Автоматически обновляется каждые 5 секунд — показывает только новые файлы.
    mode='media'  — только ALLOWED_MEDIA | ALLOWED_IMG (по умолчанию, первая вкладка)
    mode='all'    — все файлы кроме .txt (вкладка Base64)
    """
    _ALL_EXT = None  # заполняется лениво

    # Расширения, которые ВСЕГДА исключаются в режиме 'all'
    _EXCLUDE_EXT = {'.txt', '.log', '.lnk', '.ini', '.cfg', '.tmp', '.db', '.desktop'}

    def __init__(self, media_tab, parent=None, mode='media'):
        super().__init__(parent)
        self.media_tab = media_tab
        self._mode = mode
        self._folder = ""
        self._default_folder = ""   # папка загрузки (из вкладки «Загрузчик»)
        self._custom_folder = ""    # выбранная пользователем папка-источник (приоритет)
        try:
            self._custom_folder = (load_settings().get('recent_folders', {}) or {}).get(mode, "") or ""
        except Exception:
            self._custom_folder = ""
        self._known_paths: list = []  # текущий список путей (актуальный снимок)
        self.setFixedHeight(128)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        self._inner = QWidget()
        self._row = QHBoxLayout(self._inner)
        self._row.setContentsMargins(4, 4, 4, 4); self._row.setSpacing(6)
        self._row.addStretch()
        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll)

        # Правая колонка (сверху справа): выбор папки-источника ленты.
        ctl = QVBoxLayout(); ctl.setContentsMargins(2, 2, 4, 2); ctl.setSpacing(2)
        self._btn_folder = QToolButton(); self._btn_folder.setAutoRaise(True)
        self._btn_folder.setIcon(get_icon('fa5s.folder-open'))
        self._btn_folder.clicked.connect(self._choose_folder)
        self._btn_folder_reset = QToolButton(); self._btn_folder_reset.setAutoRaise(True)
        self._btn_folder_reset.setIcon(get_icon('fa5s.undo'))
        self._btn_folder_reset.setToolTip("Сбросить — брать из папки загрузки")
        self._btn_folder_reset.clicked.connect(self._reset_folder)
        ctl.addWidget(self._btn_folder, 0, Qt.AlignmentFlag.AlignTop)
        ctl.addWidget(self._btn_folder_reset, 0, Qt.AlignmentFlag.AlignTop)
        ctl.addStretch()
        outer.addLayout(ctl)

        self._lbl_empty = QLabel("Нет медиафайлов в папке")
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setStyleSheet("color:#666;font-size:10px;")
        self._row.insertWidget(0, self._lbl_empty)

        # Таймер автообновления
        self._timer = QTimer(self)
        self._timer.setInterval(5000)  # каждые 5 секунд
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        self._update_folder_btn()
        if self._custom_folder:        # своя папка задана — показываем сразу, до refresh()
            self._folder = self._effective_folder()
            self._apply(self._scan())

    def wheelEvent(self, event):
        """Колесо мыши — горизонтальная прокрутка стрипа."""
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y() // 2)
        event.accept()

    @classmethod
    def _get_all_ext(cls):
        if cls._ALL_EXT is None:
            cls._ALL_EXT = ALLOWED_MEDIA | RIBBON_IMG
        return cls._ALL_EXT

    def _scan(self) -> list:
        """Возвращает список путей из _folder, сортированных по mtime DESC, макс. 30.
        Устойчив к гонке: файл может исчезнуть между listdir и getmtime.
        """
        if not self._folder or not os.path.isdir(self._folder):
            return []
        result = []
        try:
            entries = os.listdir(self._folder)
        except Exception:
            return []
        for f in entries:
            try:
                fp = os.path.join(self._folder, f)
                if not os.path.isfile(fp):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if self._mode == 'all':
                    if ext in self._EXCLUDE_EXT:
                        continue
                    result.append(fp)
                else:
                    if ext in self._get_all_ext():
                        result.append(fp)
            except Exception:
                continue

        def _safe_mtime(p):
            try:
                return os.path.getmtime(p)
            except Exception:
                return 0.0

        result.sort(key=_safe_mtime, reverse=True)
        return result[:30]

    def _poll(self):
        """Вызывается таймером — обновляет стрип если список файлов изменился."""
        if not self._folder:
            return
        new_paths = self._scan()
        if new_paths != self._known_paths:
            self._apply(new_paths)
        # Пингуем карточки без миниатюры: файл мог дозаписаться (mp4 при
        # перекодировании весь процесс висит ~48 Б, moov пишется в конце).
        for i in range(self._row.count()):
            it = self._row.itemAt(i)
            w = it.widget() if it else None
            if isinstance(w, RecentFileThumb):
                w.recheck_pending()

    def refresh(self, folder: str):
        """Папка загрузки сменилась (вкладка «Загрузчик»). Если своя папка не
        задана — лента берёт её; иначе остаётся на пользовательской."""
        self._default_folder = folder or ""
        self._folder = self._effective_folder()
        self._apply(self._scan())

    def _effective_folder(self) -> str:
        """Своя папка пользователя приоритетнее; иначе — папка загрузки."""
        if self._custom_folder and os.path.isdir(self._custom_folder):
            return self._custom_folder
        return self._default_folder

    def _choose_folder(self):
        start = self._effective_folder() or default_download_dir()
        d = QFileDialog.getExistingDirectory(self, "Папка-источник ленты", start)
        if not d:
            return
        self._custom_folder = d
        self._persist_folder()
        self._folder = self._effective_folder()
        self._apply(self._scan())
        self._update_folder_btn()

    def _reset_folder(self):
        self._custom_folder = ""
        self._persist_folder()
        self._folder = self._effective_folder()
        self._apply(self._scan())
        self._update_folder_btn()

    def _persist_folder(self):
        """Сохраняем выбор папки в настройках (по режиму ленты)."""
        try:
            s = load_settings()
            folders = dict(s.get('recent_folders', {}) or {})
            if self._custom_folder:
                folders[self._mode] = self._custom_folder
            else:
                folders.pop(self._mode, None)
            s['recent_folders'] = folders
            save_settings(s)
        except Exception:
            pass

    def _update_folder_btn(self):
        custom = bool(self._custom_folder)
        self._btn_folder_reset.setVisible(custom)
        if custom:
            self._btn_folder.setToolTip(
                f"Папка-источник ленты:\n{self._custom_folder}\n(нажмите, чтобы сменить)")
        else:
            self._btn_folder.setToolTip(
                "Выбрать папку-источник ленты.\n"
                "По умолчанию — папка загрузки из вкладки «Загрузчик».")

    def _apply(self, paths: list):
        """Обновляет виджеты: добавляет только новые, удаляет исчезнувшие."""
        old_paths = self._known_paths
        self._known_paths = paths

        # Удаляем карточки файлов которых больше нет
        removed = set(old_paths) - set(paths)
        if removed:
            for i in range(self._row.count() - 1, -1, -1):
                item = self._row.itemAt(i)
                w = item.widget() if item else None
                if isinstance(w, RecentFileThumb) and w.path in removed:
                    self._row.takeAt(i)
                    w.deleteLater()

        # Собираем существующие карточки
        existing = {
            self._row.itemAt(i).widget().path
            for i in range(self._row.count())
            if isinstance(self._row.itemAt(i).widget() if self._row.itemAt(i) else None, RecentFileThumb)
        }
        added = [p for p in paths if p not in existing]

        if not paths:
            if not self._has_empty_label():
                lbl = QLabel("Нет медиафайлов в папке загрузок")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet("color:#666;font-size:10px;")
                self._row.insertWidget(0, lbl)
            return

        self._remove_empty_label()

        for path in reversed(added):
            card = RecentFileThumb(path, self._inner)
            self._row.insertWidget(0, card)

        # Переупорядочиваем только если что-то реально изменилось по сравнению с
        # предыдущим снимком (не только добавились новые в начало)
        need_reorder = bool(removed) or (
            added and old_paths and paths[:len(old_paths)] != old_paths
        )
        if need_reorder:
            self._reorder(paths)

    def _reorder(self, ordered_paths: list):
        """Переставляет карточки в соответствии с порядком ordered_paths."""
        path_to_widget = {}
        for i in range(self._row.count()):
            item = self._row.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, RecentFileThumb):
                path_to_widget[w.path] = w

        # Переставляем по желаемому порядку
        for idx, path in enumerate(ordered_paths):
            w = path_to_widget.get(path)
            if w:
                self._row.removeWidget(w)
                self._row.insertWidget(idx, w)

    def _has_empty_label(self) -> bool:
        for i in range(self._row.count()):
            item = self._row.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, QLabel) and not isinstance(w, RecentFileThumb):
                return True
        return False

    def _remove_empty_label(self):
        for i in range(self._row.count() - 1, -1, -1):
            item = self._row.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, QLabel) and not isinstance(w, RecentFileThumb):
                self._row.takeAt(i)
                w.deleteLater()


class DraggableTreeWidget(QTreeWidget):
    """QTreeWidget с поддержкой drag-and-drop файлов наружу (по tooltip = полный
    путь) и текстом-подсказкой по центру, когда список пуст."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # Нужно для наведения на значок «сравнить» без зажатой кнопки.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def setPlaceholderText(self, text: str):
        self._placeholder = text or ""
        self.viewport().update()

    def _badge_iid_at(self, pos):
        """Если pos (в координатах viewport) попадает в значок «сравнить»
        обработанной картинки — возвращает id строки, иначе None."""
        if pos is None:
            return None
        deleg = self.itemDelegateForColumn(0)
        if deleg is None or not hasattr(deleg, '_badge_rect'):
            return None
        idx = self.indexAt(pos)
        if not idx.isValid():
            return None
        idx = idx.sibling(idx.row(), 0)
        if not idx.data(ITEM_COMPARE_ROLE):
            return None
        br = deleg._badge_rect(self.visualRect(idx), self.fontMetrics())
        if br.contains(pos):
            return idx.data(Qt.ItemDataRole.UserRole)
        return None

    def _update_badge_hover(self, pos):
        deleg = self.itemDelegateForColumn(0)
        if deleg is None or not hasattr(deleg, 'set_badge_hover'):
            return
        iid = self._badge_iid_at(pos)
        deleg.set_badge_hover(iid)

    def viewportEvent(self, e):
        # Тултип ячейки (полное имя/путь) показываем тем же стабильным попапом,
        # что и значки ⓘ. Системный QToolTip на ячейках дерева мерцает —
        # перехватываем событие и рисуем свой попап, не дёргающийся при
        # микродвижениях мыши.
        try:
            et = e.type()
            if et == QEvent.Type.ToolTip:
                item = self.itemAt(e.pos())
                # Над значком «сравнить» — подсказка о значке (БЕЗ имени файла);
                # имя файла остаётся только при наведении на саму картинку.
                if self._badge_iid_at(e.pos()) is not None:
                    tip = "Сравнить исходник и результат"
                else:
                    tip = item.toolTip(0) if item else ""
                if tip:
                    _InfoTipPopup.instance().show_at(e.globalPos(), tip)
                else:
                    _InfoTipPopup.instance().hide()
                e.accept()
                return True
            if et == QEvent.Type.MouseMove:
                self._update_badge_hover(e.pos())
            if et in (QEvent.Type.Leave, QEvent.Type.Wheel):
                _InfoTipPopup.instance().hide()
                self._update_badge_hover(None)
        except Exception:
            pass
        return super().viewportEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        text = getattr(self, "_placeholder", "")
        if text and self.topLevelItemCount() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(150, 150, 150))
            rect = self.viewport().rect().adjusted(24, 24, -24, -24)
            painter.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                text)
            painter.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = e.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not (e.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(e)
        if not hasattr(self, '_drag_start_pos'):
            return super().mouseMoveEvent(e)
        if (e.pos() - self._drag_start_pos).manhattanLength() < 10:
            return super().mouseMoveEvent(e)

        items = self.selectedItems()
        if not items:
            return super().mouseMoveEvent(e)

        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QDrag

        urls = []
        for item in items:
            path = item.toolTip(0)  # tooltip хранит полный путь
            if path and os.path.isfile(path):
                urls.append(QUrl.fromLocalFile(path))

        if not urls:
            return super().mouseMoveEvent(e)

        drag = QDrag(self)
        md = QMimeData()
        md.setUrls(urls)
        drag.setMimeData(md)
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
            if paths:
                p = self.parent()
                while p and not hasattr(p, 'add_paths'):
                    p = p.parent()
                if p:
                    p.add_paths(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


# ─────────────────────────────────────────────────────────────
#  Photo Merger Tab  (вкладка объединения фотографий)
# ─────────────────────────────────────────────────────────────
class PhotoDragList(QTreeWidget):
    """Список с drag-and-drop файлов извне + перестановка внутри."""

    VALID_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff',
                  '.webp', '.avif', '.heic', '.heif', '.ico', '.svg'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["Превью", "Файл", "Статус"])
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 90)
        self.setColumnWidth(2, 100)
        self.setIconSize(QSize(80, 68))
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setStyleSheet("""
            QTreeWidget {
                background-color: #181825;
                alternate-background-color: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 6px;
            }
            QTreeWidget::item { padding: 4px 2px; min-height: 72px; }
            QTreeWidget::item:selected { background-color: transparent; }
            QTreeWidget::item:hover    { background-color: transparent; }
        """)
        # Фон строки по статусу (зелёный — объединено, красный — ошибка) + видимое
        # выделение/hover тем же делегатом, что в Обработке и Загрузчике.
        self.setItemDelegate(StatusColorDelegate(self))

    # ── External drag-and-drop ──────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            links = [str(url.toLocalFile()) for url in event.mimeData().urls()]
            self.add_files(links)
        else:
            super().dropEvent(event)

    # ── Add files ──────────────────────────────────────────
    def add_files(self, paths):
        added = False
        for p in paths:
            if os.path.isfile(p) and os.path.splitext(p)[1].lower() in self.VALID_EXTS:
                item = QTreeWidgetItem(["", os.path.basename(p), "новый"])
                item.setData(0, Qt.ItemDataRole.UserRole, p)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, "new")  # state

                # thumbnail (SVG растеризуется через QtSvg)
                pix = load_pixmap_any(p)
                if not pix.isNull():
                    item.setIcon(0, QIcon(pix.scaled(80, 68, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)))
                self.addTopLevelItem(item)
                added = True
        if added:
            self.scrollToBottom()

    def get_all_items(self):
        return [self.topLevelItem(i) for i in range(self.topLevelItemCount())]

    def get_new_items(self):
        return [it for it in self.get_all_items()
                if it.data(0, Qt.ItemDataRole.UserRole + 1) == "new"]

    def mark_processed(self, items):
        """Успех: строка зелёная (как в Обработке), без значка-галочки."""
        for it in items:
            it.setData(0, Qt.ItemDataRole.UserRole + 1, "processed")
            it.setIcon(2, QIcon())          # убираем прежний значок «готово»
            it.setText(2, "Готово")
            it.setData(0, ITEM_STATUS_ROLE, 'done')
            for col in range(3):            # снимаем старый произвольный фон
                it.setBackground(col, QBrush())

    def mark_failed(self, items):
        """Ошибка объединения: строка красная. Файлы остаются «новыми» —
        их можно объединить повторно."""
        for it in items:
            it.setIcon(2, QIcon())
            it.setText(2, "Ошибка")
            it.setData(0, ITEM_STATUS_ROLE, 'err')
            for col in range(3):
                it.setBackground(col, QBrush())


# ─────────────────────────────────────────────────────────────
#  Полноэкранный просмотр изображений (одиночный + сравнение)
# ─────────────────────────────────────────────────────────────
def _paint_checkerboard(painter, rect, cell=11):
    """Рисует «шахматку» в прямоугольнике rect — фон под картинкой с
    прозрачностью, чтобы прозрачные области были ВИДНЫ (как в Photoshop/GIMP),
    а не сливались с тёмным фоном окна (иначе кажется, что прозрачность
    потеряна). Под непрозрачной картинкой шахматка полностью скрыта — для них
    визуально ничего не меняется."""
    r = rect.toRect() if hasattr(rect, 'toRect') else rect
    painter.save()
    painter.setClipRect(r)
    painter.fillRect(r, QColor(0x53, 0x55, 0x60))   # светлая клетка
    dark = QColor(0x3a, 0x3c, 0x46)                  # тёмная клетка
    x0, y0 = r.left(), r.top()
    rows = (r.height() // cell) + 2
    cols = (r.width() // cell) + 2
    for iy in range(rows):
        for ix in range(cols):
            if (ix + iy) & 1:
                painter.fillRect(x0 + ix * cell, y0 + iy * cell, cell, cell, dark)
    painter.restore()


class _ZoomImageLabel(QLabel):
    """QLabel, который рисует QPixmap, вписанный в свой размер с сохранением
    пропорций. Сам перерисовывается при изменении размера — так картинка
    масштабируется под окно без растяжения. Под прозрачными картинками рисует
    шахматку, чтобы прозрачность была видна."""
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self._src = pixmap if (pixmap is not None and not pixmap.isNull()) else None
        self._has_alpha = bool(self._src is not None and self._src.hasAlphaChannel())
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:transparent;")
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if self._src is None:
            self.setText("Не удалось загрузить изображение")
            self.setStyleSheet("background:transparent;color:#a6adc8;font-size:14px;")

    def _scaled(self):
        if self._src is None:
            return None
        return self._src.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)

    def paintEvent(self, e):
        if self._src is None:
            super().paintEvent(e)
            return
        pm = self._scaled()
        if pm is None or pm.isNull():
            super().paintEvent(e)
            return
        dpr = pm.devicePixelRatio() or 1.0
        w = int(round(pm.width() / dpr)); h = int(round(pm.height() / dpr))
        x = (self.width() - w) // 2; y = (self.height() - h) // 2
        p = QPainter(self)
        if self._has_alpha:
            _paint_checkerboard(p, QRect(x, y, w, h))
        p.drawPixmap(QRect(x, y, w, h), pm)
        p.end()

    def resizeEvent(self, e):
        self.update()
        super().resizeEvent(e)


class ImageFullscreenViewer(QDialog):
    """Полноэкранный просмотр одного изображения. Esc или двойной клик — закрыть."""
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(path))
        self.setStyleSheet("QDialog{background:#0e0e16;}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        pix = load_pixmap_any(path, max_dim=4096)
        lay.addWidget(_ZoomImageLabel(pix, self), 1)
        _add_close_hint(self, lay)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.close()


class _CompareView(QWidget):
    """Картинка с синхронным зумом (колесо) и панорамированием. Подпись
    (исходник/результат · формат · размер) рисуется ПОВЕРХ изображения в углу,
    а не отдельной строкой — так картинки занимают всю площадь панели. Зум/панораму
    маршрутизируем через owner (диалог), чтобы ОБА вида всегда двигались вместе."""

    def __init__(self, pixmap, caption, owner=None, parent=None):
        super().__init__(parent)
        self._src = pixmap if (pixmap is not None and not pixmap.isNull()) else None
        self._has_alpha = bool(self._src is not None and self._src.hasAlphaChannel())
        self._caption = caption
        self._owner = owner             # ImageCompareViewer — синхронизирует виды
        self._zoom = 1.0
        self._off = QPointF(0.0, 0.0)   # смещение центра картинки в пикселях экрана
        self._drag_last = None
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#0e0e16;")

    def _fit_scale(self):
        if self._src is None:
            return 1.0
        w = self._src.width(); h = self._src.height()
        if w <= 0 or h <= 0:
            return 1.0
        return min(self.width() / w, self.height() / h)

    def set_view(self, zoom, off):
        self._zoom = zoom
        self._off = QPointF(off)
        self._clamp()
        self.update()

    def _clamp(self):
        if self._src is None or self._zoom <= 1.0:
            self._off = QPointF(0.0, 0.0)
            return
        scale = self._fit_scale() * self._zoom
        dw = self._src.width() * scale
        dh = self._src.height() * scale
        max_x = max(0.0, (dw - self.width()) / 2.0)
        max_y = max(0.0, (dh - self.height()) / 2.0)
        self._off = QPointF(
            max(-max_x, min(max_x, self._off.x())),
            max(-max_y, min(max_y, self._off.y())))

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(14, 14, 22))
        if self._src is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            scale = self._fit_scale() * self._zoom
            dw = self._src.width() * scale
            dh = self._src.height() * scale
            x = (self.width() - dw) / 2.0 + self._off.x()
            y = (self.height() - dh) / 2.0 + self._off.y()
            # Под прозрачной картинкой — шахматка, чтобы было видно, что
            # прозрачность сохранена (а не «потеряна» на тёмном фоне окна).
            if self._has_alpha:
                _paint_checkerboard(p, QRectF(x, y, dw, dh).toRect())
            p.drawPixmap(QRectF(x, y, dw, dh), self._src, QRectF(self._src.rect()))
        else:
            p.setPen(QColor("#a6adc8"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Не удалось загрузить изображение")
        self._paint_caption(p)

    def _paint_caption(self, p):
        if not self._caption:
            return
        f = p.font(); f.setPointSize(11); f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(self._caption)
        th = fm.height()
        pad = 7
        rect = QRectF(10, 10, tw + pad * 2, th + pad)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 160))
        p.drawRoundedRect(rect, 5, 5)
        p.setPen(QColor("#ffffff"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._caption)

    def _broadcast(self, zoom, off):
        """Применяет зум/смещение к ОБОИМ видам через owner. Если owner нет —
        двигаем только себя (запасной вариант)."""
        if self._owner is not None and hasattr(self._owner, "_apply_view"):
            self._owner._apply_view(zoom, off)
        else:
            self.set_view(zoom, off)

    def wheelEvent(self, e):
        # Колесо (без модификаторов) зумит ОБА вида одновременно — синхронизацию
        # делает owner._apply_view. Ctrl не требуется: в полноэкранном сравнении
        # прокручивать нечего, поэтому колесо = зум.
        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = 1.2 if delta > 0 else (1.0 / 1.2)
        new_zoom = max(1.0, min(8.0, self._zoom * factor))
        new_off = self._off
        if self._zoom > 0:
            r = new_zoom / self._zoom            # зум от центра — масштабируем смещение
            new_off = QPointF(self._off.x() * r, self._off.y() * r)
        self._broadcast(new_zoom, new_off)
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._zoom > 1.0:
            self._drag_last = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            e.ignore()   # без зума — отдаём клик диалогу (двойной клик закрывает)

    def mouseMoveEvent(self, e):
        if self._drag_last is not None:
            d = e.position() - self._drag_last
            self._drag_last = e.position()
            new_off = QPointF(self._off.x() + d.x(), self._off.y() + d.y())
            self._broadcast(self._zoom, new_off)   # панорама — тоже на оба вида

    def mouseReleaseEvent(self, e):
        self._drag_last = None
        self.unsetCursor()


class ImageCompareViewer(QDialog):
    """Полноэкранное сравнение исходника и результата.

    Ориентация выбирается по форме картинок: вертикальные (портрет) ставим
    рядом (слева направо), горизонтальные (пейзаж) — стопкой (сверху вниз),
    чтобы в каждом случае обе картинки оставались максимально крупными.
    Слева/сверху всегда исходник, справа/снизу — перекодированный файл.
    Колесо — зум обеих картинок одновременно; перетаскивание — панорама."""
    def __init__(self, src_path, out_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Сравнение: исходник / результат")
        self.setStyleSheet("QDialog{background:#0e0e16;}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        src_pix = load_pixmap_any(src_path, max_dim=4096)
        out_pix = load_pixmap_any(out_path, max_dim=4096)

        def _aspect(p):
            if p is None or p.isNull() or p.height() <= 0:
                return 1.0
            return p.width() / p.height()
        avg = (_aspect(src_pix) + _aspect(out_pix)) / 2.0
        # Портрет (avg < 1) → рядом; пейзаж/квадрат → стопкой.
        side_by_side = avg < 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        body = QHBoxLayout() if side_by_side else QVBoxLayout()
        # spacing/margins = 0 → между картинками нет тёмной полосы.
        body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)

        v_src = _CompareView(src_pix, self._caption("Исходник", src_path), owner=self)
        v_out = _CompareView(out_pix, self._caption("Результат", out_path), owner=self)
        self._views = [v_src, v_out]
        body.addWidget(v_src, 1)
        body.addWidget(v_out, 1)
        root.addLayout(body, 1)

        # Кнопка выхода — поверх картинок в правом верхнем углу.
        self.btn_close = QPushButton(self)
        self.btn_close.setIcon(get_icon('fa5s.times', '#ffffff'))
        self.btn_close.setIconSize(QSize(18, 18))
        self.btn_close.setFixedSize(38, 38)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("Выход (Esc)")
        self.btn_close.setStyleSheet(
            "QPushButton{background:rgba(24,24,37,190);border:1px solid #45475a;"
            "border-radius:19px;}"
            "QPushButton:hover{background:#f38ba8;border-color:#f38ba8;}")
        self.btn_close.clicked.connect(self.close)
        self.btn_close.raise_()

    @staticmethod
    def _caption(title, path):
        try:
            size_str = human_size(os.path.getsize(path))
        except Exception:
            size_str = ""
        ext = os.path.splitext(path)[1].lstrip('.').upper() or "—"
        return f"{title}   ·   {ext}" + (f"   ·   {size_str}" if size_str else "")

    def _apply_view(self, zoom, off):
        """Единая точка зума/панорамы: применяет одни и те же zoom/off к ОБОИМ
        видам — поэтому зум одной картинки всегда зумит и вторую. Виды одного
        размера, поэтому общий off корректен для обоих (set_view сам клампит)."""
        for v in self._views:
            v.set_view(zoom, off)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        btn = getattr(self, 'btn_close', None)
        if btn is not None:
            btn.move(self.width() - btn.width() - 14, 14)
            btn.raise_()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.close()


def _add_close_hint(dlg, layout):
    """Подсказка-полоска «Esc — закрыть» снизу полноэкранного просмотрщика."""
    hint = QLabel("Esc или двойной клик — закрыть")
    hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hint.setStyleSheet("color:#7f849c;font-size:11px;padding:2px;")
    layout.addWidget(hint, 0)


def _present_fullscreen(dlg, parent=None):
    """Показывает диалог НА ВЕСЬ экран, перекрывая в том числе панель задач.

    Обычный showFullScreen() у дочернего (parented) QDialog на Windows иногда
    разворачивается лишь до рабочей области — панель задач остаётся видна, а у
    правого/нижнего края появляется незакрытая полоса. Поэтому делаем окно
    безрамочным «поверх всех» и явно выставляем геометрию во весь экран того
    монитора, где находится родитель."""
    scr = None
    try:
        host = parent.window() if parent is not None else None
        if host is not None:
            scr = host.screen()
    except Exception:
        scr = None
    if scr is None:
        scr = QApplication.primaryScreen()
    dlg.setWindowFlags(dlg.windowFlags()
                       | Qt.WindowType.FramelessWindowHint
                       | Qt.WindowType.WindowStaysOnTopHint)
    geo = scr.geometry() if scr is not None else None
    if geo is not None:
        dlg.setGeometry(geo)
    dlg.show()
    if geo is not None:
        # После show некоторые WM сбрасывают геометрию — выставляем повторно.
        dlg.setGeometry(geo)
    dlg.raise_()
    dlg.activateWindow()
    return dlg


def show_image_fullscreen(path, parent=None):
    """Открывает одно изображение в полноэкранном просмотрщике."""
    dlg = ImageFullscreenViewer(path, parent)
    return _present_fullscreen(dlg, parent)


def show_image_compare(src_path, out_path, parent=None):
    """Открывает сравнение исходника и результата в полноэкранном просмотрщике."""
    dlg = ImageCompareViewer(src_path, out_path, parent)
    return _present_fullscreen(dlg, parent)
