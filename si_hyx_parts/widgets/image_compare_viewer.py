# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ImageCompareViewer. Public namespace: widgets."""
import widgets as _api


class ImageCompareViewer(_api.QDialog):
    """Полноэкранное сравнение исходника и результата.

    Ориентация выбирается по форме картинок: вертикальные (портрет) ставим
    рядом (слева направо), горизонтальные (пейзаж) — стопкой (сверху вниз),
    чтобы в каждом случае обе картинки оставались максимально крупными.
    Слева/сверху всегда исходник, справа/снизу — перекодированный файл.
    Колесо — зум обеих картинок одновременно; перетаскивание — панорама."""
    def __init__(self, src_path, out_path, parent=None, use_filenames=False):
        super().__init__(parent)
        # use_filenames: True только для кнопки «Сравнить любые 2 файла»
        # (тулбар) — подписи показывают имя файла вместо «Исходник»/«Результат»,
        # т.к. там это не обязательно пара исходник/результат обработки.
        self._use_filenames = use_filenames
        self.setWindowTitle("Сравнение: исходник / результат")
        self.setStyleSheet("QDialog{background:#0e0e16;}")
        self.setAttribute(_api.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # src_path/out_path могут быть None — «Сравнить любые 2 файла» позволяет
        # выбрать сначала только один файл, второй добавляется прямо в окне.
        src_pix = _api.load_pixmap_any(src_path, max_dim=4096) if src_path else None
        out_pix = _api.load_pixmap_any(out_path, max_dim=4096) if out_path else None

        def _aspect(p):
            if p is None or p.isNull() or p.height() <= 0:
                return 1.0
            return p.width() / p.height()
        avg = (_aspect(src_pix) + _aspect(out_pix)) / 2.0
        # Портрет (avg < 1) → рядом; пейзаж/квадрат → стопкой.
        side_by_side = avg < 1.0

        root = _api.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        body = _api.QHBoxLayout() if side_by_side else _api.QVBoxLayout()
        # spacing/margins = 0 → между картинками нет тёмной полосы.
        body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)

        self.view_src = _api._CompareView(
            src_pix, self._caption("Исходник", src_path), owner=self,
            placeholder=None if src_path else "Нажмите на значок папки слева,\nчтобы выбрать файл")
        self.view_out = _api._CompareView(
            out_pix, self._caption("Результат", out_path), owner=self,
            placeholder=None if out_path else "Нажмите на значок папки справа,\nчтобы выбрать файл")
        self._views = [self.view_src, self.view_out]
        self._src_path = src_path
        self._out_path = out_path
        body.addWidget(self.view_src, 1)
        body.addWidget(self.view_out, 1)
        root.addLayout(body, 1)

        # Кнопка выхода — поверх картинок в правом верхнем углу.
        self.btn_close = _api.QPushButton(self)
        self.btn_close.setIcon(_api.get_icon('fa5s.times', '#ffffff'))
        self.btn_close.setIconSize(_api.QSize(18, 18))
        self.btn_close.setFixedSize(38, 38)
        self.btn_close.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("Выход (Esc)")
        self.btn_close.setStyleSheet(
            "QPushButton{background:rgba(24,24,37,190);border:1px solid #45475a;"
            "border-radius:19px;}"
            "QPushButton:hover{background:#f38ba8;border-color:#f38ba8;}")
        self.btn_close.clicked.connect(self.close)
        self.btn_close.raise_()

        # Кнопки «заменить исходник»/«заменить результат» — поверх картинок в
        # левом/правом верхнем углу. Каждая трогает только СВОЮ сторону —
        # позволяет сравнить любые два файла с диска, а не только исходный
        # входной файл и его результат.
        self.btn_change_src = _api.QPushButton(self)
        self.btn_change_src.setIcon(_api.get_icon('fa5s.folder-open', '#ffffff'))
        self.btn_change_src.setIconSize(_api.QSize(18, 18))
        self.btn_change_src.setFixedSize(38, 38)
        self.btn_change_src.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.btn_change_src.setToolTip("Заменить исходник (слева) файлом с диска")
        self.btn_change_src.setStyleSheet(
            "QPushButton{background:rgba(24,24,37,190);border:1px solid #45475a;"
            "border-radius:19px;}"
            "QPushButton:hover{background:#89b4fa;border-color:#89b4fa;}")
        self.btn_change_src.clicked.connect(self._pick_source_image)
        self.btn_change_src.raise_()

        self.btn_change_out = _api.QPushButton(self)
        self.btn_change_out.setIcon(_api.get_icon('fa5s.folder-open', '#ffffff'))
        self.btn_change_out.setIconSize(_api.QSize(18, 18))
        self.btn_change_out.setFixedSize(38, 38)
        self.btn_change_out.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.btn_change_out.setToolTip("Заменить результат (справа) файлом с диска")
        self.btn_change_out.setStyleSheet(
            "QPushButton{background:rgba(24,24,37,190);border:1px solid #45475a;"
            "border-radius:19px;}"
            "QPushButton:hover{background:#89b4fa;border-color:#89b4fa;}")
        self.btn_change_out.clicked.connect(self._pick_source_out_image)
        self.btn_change_out.raise_()

    def _caption(self, title, path):
        if not path:
            return ""
        label = _api.os.path.basename(path) if self._use_filenames else title
        try:
            size_str = _api.human_size(_api.os.path.getsize(path))
        except Exception:
            size_str = ""
        ext = _api.os.path.splitext(path)[1].lstrip('.').upper() or "—"
        if self._use_filenames:
            return f"{label}   ·   {size_str}" if size_str else label
        return f"{label}   ·   {ext}" + (f"   ·   {size_str}" if size_str else "")

    def _pick_source_image(self):
        exts = " ".join(f"*{e}" for e in sorted(_api.ALLOWED_IMG))
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Выбрать изображение для сравнения", "",
            f"Изображения ({exts});;Все файлы (*)")
        if not path:
            return
        pix = _api.load_pixmap_any(path, max_dim=4096)
        if pix is None or pix.isNull():
            return
        self._src_path = path
        self.view_src.set_pixmap_caption(pix, self._caption("Исходник", path))
        self._apply_view(1.0, _api.QPointF(0.0, 0.0))  # новая картинка — сброс зума на оба вида

    def _pick_source_out_image(self):
        exts = " ".join(f"*{e}" for e in sorted(_api.ALLOWED_IMG))
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Выбрать изображение для сравнения", "",
            f"Изображения ({exts});;Все файлы (*)")
        if not path:
            return
        pix = _api.load_pixmap_any(path, max_dim=4096)
        if pix is None or pix.isNull():
            return
        self._out_path = path
        self.view_out.set_pixmap_caption(pix, self._caption("Результат", path))
        self._apply_view(1.0, _api.QPointF(0.0, 0.0))  # новая картинка — сброс зума на оба вида

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
        btn2 = getattr(self, 'btn_change_src', None)
        if btn2 is not None:
            btn2.move(14, 14)
            btn2.raise_()
        btn3 = getattr(self, 'btn_change_out', None)
        if btn3 is not None and btn is not None:
            btn3.move(self.width() - btn.width() - btn3.width() - 14 - 8, 14)
            btn3.raise_()

    def keyPressEvent(self, e):
        if e.key() == _api.Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.close()

ImageCompareViewer.__module__ = _api.__name__
_api.ImageCompareViewer = ImageCompareViewer

def _add_close_hint(dlg, layout):
    """Подсказка-полоска «Esc — закрыть» снизу полноэкранного просмотрщика."""
    hint = _api.QLabel("Esc или двойной клик — закрыть")
    hint.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    hint.setStyleSheet("color:#7f849c;font-size:11px;padding:2px;")
    layout.addWidget(hint, 0)

_add_close_hint.__module__ = _api.__name__
_api._add_close_hint = _add_close_hint

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
        scr = _api.QApplication.primaryScreen()
    dlg.setWindowFlags(dlg.windowFlags()
                       | _api.Qt.WindowType.FramelessWindowHint
                       | _api.Qt.WindowType.WindowStaysOnTopHint)
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

_present_fullscreen.__module__ = _api.__name__
_api._present_fullscreen = _present_fullscreen

def show_image_fullscreen(path, parent=None):
    """Открывает одно изображение в полноэкранном просмотрщике."""
    dlg = _api.ImageFullscreenViewer(path, parent)
    return _api._present_fullscreen(dlg, parent)

show_image_fullscreen.__module__ = _api.__name__
_api.show_image_fullscreen = show_image_fullscreen

def show_image_compare(src_path, out_path, parent=None, use_filenames=False):
    """Открывает сравнение исходника и результата в полноэкранном просмотрщике.
    use_filenames=True — подписи показывают имена файлов вместо «Исходник»/
    «Результат» (используется кнопкой «Сравнить любые 2 файла»)."""
    dlg = _api.ImageCompareViewer(src_path, out_path, parent, use_filenames)
    return _api._present_fullscreen(dlg, parent)

show_image_compare.__module__ = _api.__name__
_api.show_image_compare = show_image_compare
