# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_InfoTipPopup. Public namespace: widgets."""
import widgets as _api


# --- Информационные подсказки "ⓘ" для пунктов настроек ---
class _InfoTipPopup(_api.QLabel):
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
            cls._instance = _api._InfoTipPopup()
        return cls._instance

    def __init__(self):
        super().__init__(None)
        # WindowTransparentForInput — прозрачность для мыши на уровне САМОЙ
        # Windows. Одного WA_TransparentForMouseEvents у окна верхнего уровня
        # мало: курсор, заехавший на попап (он стоит справа-снизу от курсора,
        # а таблицы читают сверху вниз), уводил Leave у таблицы — попап
        # прятался, курсор снова над таблицей, и подсказка появлялась заново
        # только после паузы. Выглядело это как «лагающая» подсказка.
        self.setWindowFlags(_api.Qt.WindowType.ToolTip
                            | _api.Qt.WindowType.FramelessWindowHint
                            | _api.Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(_api.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(_api.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWordWrap(True)
        self.setMaximumWidth(360)
        self.setObjectName("infoTip")
        self.setStyleSheet(
            "#infoTip{background:#1e1e2e;color:#cdd6f4;border:1px solid #585b70;"
            "border-radius:6px;padding:6px 8px;font-size:12px;}")

    def _fit_size(self, text):
        """Ставит текст и приводит попап к его настоящему размеру.

        adjustSize() у QLabel со словопереносом даёт высоту для ЭВРИСТИЧЕСКОЙ
        ширины, а не для той, до которой попап реально ужат maximumWidth: у
        длинных подсказок (кнопки с абзацем пояснения) высота получалась
        заниженной в разы. По ней же считался вылет за край экрана — поэтому
        подсказка «не помещалась» и уезжала под панель задач, хотя сдвиг
        рассчитывался. Досчитываем высоту через heightForWidth."""
        self.setText(text)
        self.adjustSize()
        w = min(self.width(), self.maximumWidth())
        h = self.height()
        if self.wordWrap():
            h = max(h, self.heightForWidth(w) or 0)
        self.resize(w, h)

    def _place(self, x, y, flip_top, screen_geo):
        """Двигает попап в (x, y), не выпуская его за пределы экрана.

        Не влезает снизу — уходит НАД точкой привязки (flip_top), а не просто
        прижимается к нижнему краю: иначе попап накрыл бы то, к чему относится."""
        try:
            sg = screen_geo
            if sg is not None:
                if x + self.width() > sg.right(): x = sg.right() - self.width() - 4
                if x < sg.left(): x = sg.left() + 4
                if y + self.height() > sg.bottom():
                    y = flip_top - self.height() - 4
                if y < sg.top(): y = sg.top() + 4
        except Exception:
            pass
        self.move(x, y); self.show(); self.raise_()

    def show_for(self, badge, text):
        # Уже показываем ровно эту подсказку — не дёргаем show()/move() повторно.
        # При перестроении виджетов под курсором (списки/плитки) ToolTip-события
        # повторяются с тем же текстом; без этой проверки попап моргал.
        if self.isVisible() and self.text() == text:
            return
        self._fit_size(text)
        # Ниже-правее значка — курсор на значке не попадёт на попап (иначе цикл).
        gp = badge.mapToGlobal(badge.rect().bottomLeft())
        try:
            scr = badge.screen()
            sg = scr.availableGeometry() if scr else None
        except Exception:
            sg = None
        # Не влезло снизу — показываем над самим виджетом (его верхний край).
        top = badge.mapToGlobal(badge.rect().topLeft()).y()
        self._place(gp.x(), gp.y() + 4, top, sg)

    def show_at(self, global_point, text):
        """Показывает подсказку у заданной глобальной точки (напр. у курсора над
        ячейкой дерева). Тот же стабильный попап, что и у значков ⓘ."""
        if not text:
            return
        self._fit_size(text)
        try:
            scr = _api.QApplication.screenAt(global_point)
            sg = scr.availableGeometry() if scr else None
        except Exception:
            sg = None
        self._place(global_point.x() + 16, global_point.y() + 18,
                    global_point.y() - 2, sg)

_InfoTipPopup.__module__ = _api.__name__
_api._InfoTipPopup = _InfoTipPopup

def _enable_clear_button(ed) -> None:
    """Включает крестик «очистить» у поля ввода, если он там уместен.

    Не трогаем: поля только для чтения (стирать нечего), пароли (крестик выдаёт
    длину), внутренние строки счётчиков/выпадающих списков (там свои кнопки, и
    крестик влезал бы в стрелку) и редакторы ячеек в таблицах (правку и так
    завершают Enter/Esc).
    """
    try:
        if ed.isReadOnly() or ed.echoMode() != _api.QLineEdit.EchoMode.Normal:
            return
        parent = ed.parentWidget()
        if isinstance(parent, (_api.QAbstractSpinBox, _api.QComboBox)):
            return
        # редактор ячейки живёт на viewport'е таблицы/списка
        if parent is not None and isinstance(parent.parentWidget(), _api.QAbstractItemView):
            return
        ed.setClearButtonEnabled(True)
    except Exception:
        pass

_enable_clear_button.__module__ = _api.__name__
_api._enable_clear_button = _enable_clear_button

class HoverTipManager(_api.QObject):
    """Глобальный фильтр событий: заменяет системные QToolTip на тот же
    стабильный фирменный попап, что и у значков ⓘ (_InfoTipPopup). QToolTip
    реагирует на каждое микродвижение мыши и потому мерцает/подлагивает; здесь
    же попап показывается один раз по событию ToolTip и прячется по уходу
    курсора — без мерцания. Достаточно установить на QApplication, и ВСЕ
    виджеты с setToolTip(...) автоматически получают стабильную подсказку."""

    def eventFilter(self, obj, ev):
        try:
            et = ev.type()
            # Курсор-«рука» на ЛЮБОЙ кнопке при наведении (как в вебе): большинство
            # кнопок в проге не задавали курсор явно и оставались со стрелкой — теперь
            # везде единообразно. Ставим только если у кнопки ДЕФОЛТНЫЙ курсор-стрелка
            # (не перетираем кастомные SizeAll/OpenHand у drag-кнопок) и она активна.
            if et == _api.QEvent.Type.Enter and isinstance(obj, _api.QAbstractButton):
                if (obj.isEnabled()
                        and obj.cursor().shape() == _api.Qt.CursorShape.ArrowCursor):
                    obj.setCursor(_api.Qt.CursorShape.PointingHandCursor)
                return False
            # Крестик «очистить» в КАЖДОМ поле ввода: раньше его ставили руками
            # и только части полей, из-за чего в одних текст стирался одним
            # кликом, а в других приходилось выделять и удалять. Ставим по
            # Polish — он приходит один раз, ещё до показа виджета.
            if et == _api.QEvent.Type.Polish and isinstance(obj, _api.QLineEdit):
                _api._enable_clear_button(obj)
                return False
            # Шаг значения у спинбокса выделяет весь его текст (Qt делает
            # selectAll в stepBy) — и это выделение остаётся висеть синим, будто
            # в поле что-то редактируют, хотя фокус там даже не побывал: колесо
            # фокус спинбоксу НЕ отдаёт (проверено на живом окне — после колеса
            # hasFocus=False, фокус остаётся на QScrollArea панели). Значит и
            # снимать выделение надо не по уходу фокуса, а сразу: покрутили
            # колесом над НЕсфокусированным полем — выделять там нечего.
            if et == _api.QEvent.Type.Wheel:
                # Alt + колесо в Qt прокручивает область ПО ГОРИЗОНТАЛИ — и
                # список/таблица уезжали вбок от случайно зажатого Alt. По всей
                # программе такую прокрутку выключаем: событие съедаем, до
                # области прокрутки оно не доходит (просьба пользователя).
                # modifiers() есть у QWheelEvent, но не у голого QEvent — фильтр
                # обязан пережить и такой (его шлют, например, тесты).
                mods = (ev.modifiers() if hasattr(ev, "modifiers")
                        else _api.Qt.KeyboardModifier.NoModifier)
                if (mods & _api.Qt.KeyboardModifier.AltModifier
                        and self._is_scroll_area(obj)):
                    _api._InfoTipPopup.instance().hide()
                    ev.accept()
                    return True
                self._drop_wheel_selection(obj)
            # Второй случай: в поле реально работали (кликнули внутрь, набрали/
            # покрутили) и оно сфокусировано. Клик по «пустому» месту окна фокус
            # не забирает — под курсором нефокусируемый виджет (лейбл, фон
            # формы), — и выделение опять залипает. Снимаем фокус: QLineEdit по
            # focusOut сам убирает выделение, а спинбокс заодно дочитывает
            # набранное (editingFinished), как при обычном уходе.
            if et == _api.QEvent.Type.MouseButtonPress:
                self._release_spinbox_focus(obj)
            if et == _api.QEvent.Type.ToolTip:
                tip = obj.toolTip() if isinstance(obj, _api.QWidget) else ""
                if tip:
                    _api._InfoTipPopup.instance().show_for(obj, tip)
                    return True  # подавляем системный QToolTip (источник мерцания)
                # Подсказки ЯЧЕЕК списков и таблиц (item.setToolTip,
                # ToolTipRole) живут не в toolTip() виджета, и Qt показывал их
                # системным синим QToolTip — тем самым, что пользователь
                # запретил (путь файла в списке паков). Ловим их здесь, для
                # всей программы разом.
                cell = self._item_tip(obj, ev)
                if cell:
                    _api._InfoTipPopup.instance().show_at(ev.globalPos(), cell)
                    return True
                # Пустая подсказка (напр. значок ⓘ управляет попапом сам) — не трогаем.
                return False
            # ВАЖНО: НЕ прячем попап по QEvent.Hide любого виджета. Этот фильтр
            # стоит на ВСЁМ приложении, и Hide прилетает от каждого скрывающегося
            # виджета — при активной перестройке UI (напр. вкладка SiQuesterHYX
            # пересобирает списки/плитки) Hide сыпется пачками, попап моргал:
            # show(ToolTip)→hide(Hide)→show(ToolTip)→… — это и есть «мерцающее
            # окошко, которое появляется и исчезает». Скрытие виджета под курсором
            # и так доставляет Leave, поэтому подсказка корректно убирается и без
            # реакции на Hide.
            if et in (_api.QEvent.Type.Leave, _api.QEvent.Type.MouseButtonPress,
                      _api.QEvent.Type.Wheel, _api.QEvent.Type.WindowDeactivate):
                _api._InfoTipPopup.instance().hide()
        except Exception:
            pass
        return False

    @staticmethod
    def _item_tip(obj, ev) -> str:
        """Текст ToolTipRole ячейки (или заголовка) под курсором, либо «».

        Делегат со своим helpEvent (значки индекса в Shikimori, подсказки
        таблицы состава) сам решает, что и где показать, — его не трогаем."""
        view = obj.parentWidget() if isinstance(obj, _api.QWidget) else None
        if isinstance(obj, _api.QHeaderView):
            view = obj
        if not isinstance(view, _api.QAbstractItemView):
            return ""
        if view is not obj and view.viewport() is not obj:
            return ""
        model = view.model()
        if model is None:
            return ""
        role = _api.Qt.ItemDataRole.ToolTipRole
        pos = ev.pos()
        if isinstance(view, _api.QHeaderView):
            section = view.logicalIndexAt(pos)
            if section < 0:
                return ""
            text = model.headerData(section, view.orientation(), role)
            return str(text) if text else ""
        index = view.indexAt(pos)
        if not index.isValid():
            return ""
        delegate = view.itemDelegateForIndex(index)
        if any("helpEvent" in vars(cls) for cls in type(delegate).__mro__
               if not cls.__module__.startswith("PyQt")):
            return ""
        text = index.data(role)
        return str(text) if text else ""

    @staticmethod
    def _is_scroll_area(obj) -> bool:
        """Прокручиваемая область, её viewport или сама полоса прокрутки —
        то есть всё, что Qt двигает по Alt + колесо. Обычные виджеты со своей
        обработкой колеса (холст с зумом) сюда не попадают."""
        if isinstance(obj, (_api.QScrollBar, _api.QAbstractScrollArea)):
            return True
        parent = obj.parentWidget() if isinstance(obj, _api.QWidget) else None
        return (isinstance(parent, _api.QAbstractScrollArea)
                and parent.viewport() is obj)

    @staticmethod
    def _spinbox_under(obj):
        """Спинбокс, которому адресовано событие: колесо/нажатие приходит и его
        потомкам (поле ввода, стрелки), поэтому поднимаемся по родителям."""
        node = obj if isinstance(obj, _api.QWidget) else None
        while node is not None:
            if isinstance(node, _api.QAbstractSpinBox):
                return node
            node = node.parentWidget()
        return None

    @classmethod
    def _drop_wheel_selection(cls, obj):
        """Снимает выделение, которое шаг колеса ставит в НЕсфокусированном
        спинбоксе (см. вызов). Отложенно (singleShot 0): фильтр приложения видит
        колесо ДО того, как спинбокс его обработает, — сначала пусть шагнёт
        значение и выделит текст, потом убираем выделение. Сфокусированное поле
        не трогаем: там выделение осмысленно (набор заменит значение)."""
        spin = cls._spinbox_under(obj)
        if spin is None or spin.hasFocus():
            return

        def _deselect():
            try:
                if not spin.hasFocus():
                    ed = spin.lineEdit()
                    if ed is not None:
                        ed.deselect()
            except RuntimeError:
                pass    # виджет успели удалить, пока ждали таймер
        _api.QTimer.singleShot(0, _deselect)

    @staticmethod
    def _release_spinbox_focus(obj):
        """Снимает фокус со спинбокса, если кликнули ВНЕ него (см. вызов).
        Клик по самому спинбоксу или его потомку (поле ввода, стрелки) не
        трогаем — иначе поле теряло бы фокус ровно в момент клика по нему."""
        app = _api.QApplication.instance()
        fw = app.focusWidget() if app is not None else None
        if not isinstance(fw, _api.QAbstractSpinBox):
            return
        node = obj if isinstance(obj, _api.QWidget) else None
        while node is not None:
            if node is fw:
                return
            node = node.parentWidget()
        fw.clearFocus()

HoverTipManager.__module__ = _api.__name__
_api.HoverTipManager = HoverTipManager

def install_hover_tips(app):
    """Ставит HoverTipManager на приложение (один экземпляр живёт с приложением)."""
    try:
        mgr = _api.HoverTipManager(app)
        app._hover_tip_mgr = mgr  # держим ссылку, чтобы не собрался GC
        app.installEventFilter(mgr)
    except Exception:
        pass

install_hover_tips.__module__ = _api.__name__
_api.install_hover_tips = install_hover_tips
