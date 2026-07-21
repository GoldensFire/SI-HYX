# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# photo_tab.py — вкладка «Редактирование фото»: холст с кистью/фигурами/текстом,
# кадрирование, удаление объектов (LaMa) и удаление фона (RMBG-2.0), объединение
# фото. Выделено из tabs.py — тот разросся до ~6,7к строк и мешал в одном файле
# несвязанные фичи (загрузчик, обработка, Base64). Общие мелкие виджеты
# (_icon_btn, _JumpSlider) живут в widgets.py, чтобы tabs.py и photo_tab.py не
# зависели друг от друга.
import os
import random
import time
from config import (
    Image, QByteArray, QCheckBox, QColor, QComboBox, QCursor, QEvent,
    QFileDialog, QFont, QFontMetrics, QFrame, QGroupBox, QHBoxLayout,
    QInputDialog, QKeySequence, QLabel, QPainter, QPen, QPixmap, QPoint,
    QPointF, QProgressBar, QPushButton, QRectF, QScrollArea, QShortcut,
    QSize, QSpinBox, QThread, QTimer, QToolButton, QVBoxLayout, QWidget,
    Qt, QtGuiImage, get_icon, pyqtSignal, qta, status_html
)
from utils import (open_image_any, play_done_sound)
from widgets import (
    PhotoDragList, _JumpSlider, _icon_btn, info_badge, msgbox_warning,
    show_image_fullscreen
)
from PyQt6.QtGui import (QPainterPath)
from PyQt6.QtWidgets import (
    QButtonGroup, QColorDialog, QFontComboBox, QScrollBar, QSizePolicy,
    QTabWidget
)

# ── Опциональные зависимости подвкладки «Удаление объектов» (LaMa/ONNX) ──────
# Нужны numpy + opencv; саму onnxruntime подтягивает lama_inpaint лениво (при
# первом запуске модели). Если чего-то нет — подвкладка покажет понятную
# заглушку, остальное приложение работает как обычно.
import importlib.util as _ilu
try:
    import numpy as _np
    import cv2 as _cv2
    from lama_inpaint import (LaMaInpainter, LaMaProcessInpainter,
                              load_bgr, save_bgr)
    _HAS_INPAINT = True
    _INPAINT_ERR = ""
    _HAS_ORT = _ilu.find_spec("onnxruntime") is not None
except Exception as _e:           # pragma: no cover
    _np = None; _cv2 = None
    LaMaInpainter = LaMaProcessInpainter = load_bgr = save_bgr = None
    _HAS_INPAINT = False
    _INPAINT_ERR = str(_e)
    _HAS_ORT = False

# Удаление фона (RMBG-2.0 / BiRefNet) — отдельная модель models/model_uint8.onnx.
# Доступно только если есть onnxruntime И файл модели на месте.
try:
    from rmbg_bg import RMBGProcessRemover, default_model_path as _rmbg_path
    _HAS_RMBG = _HAS_ORT and _np is not None and os.path.exists(_rmbg_path())
except Exception:                 # pragma: no cover
    RMBGProcessRemover = None
    _HAS_RMBG = False

def np_bgr_to_qimage(arr):
    """BGR uint8 (H, W, 3) → QImage (RGB888). Делает .copy(): иначе QImage держит
    ссылку на буфер numpy, который освободится → висячий указатель и краш."""
    arr = _np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    rgb = _np.ascontiguousarray(_cv2.cvtColor(arr, _cv2.COLOR_BGR2RGB))
    img = QtGuiImage(rgb.data, w, h, 3 * w, QtGuiImage.Format.Format_RGB888)
    return img.copy()


def qimage_to_np_bgr(img):
    """QImage → BGR uint8 (H, W, 3). Учитывает выравнивание строк (bytesPerLine),
    иначе при ширине не кратной 4 картинка «съезжает»."""
    img = img.convertToFormat(QtGuiImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    ptr = img.constBits(); ptr.setsize(bpl * h)
    buf = _np.frombuffer(ptr, _np.uint8).reshape(h, bpl)
    rgb = buf[:, :w * 3].reshape(h, w, 3)
    return _np.ascontiguousarray(_cv2.cvtColor(rgb, _cv2.COLOR_RGB2BGR))


def np_bgra_to_qimage(arr):
    """BGRA uint8 (H, W, 4) → QImage (Format_RGBA8888) с альфа-каналом.
    BGRA → RGBA перестановкой каналов (Format_RGBA8888 — порядок R,G,B,A в памяти)."""
    arr = _np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    rgba = _np.ascontiguousarray(arr[:, :, [2, 1, 0, 3]])  # BGRA → RGBA
    img = QtGuiImage(rgba.data, w, h, 4 * w, QtGuiImage.Format.Format_RGBA8888)
    return img.copy()


def _load_image_alpha(path: str):
    """Загружает изображение сохраняя альфа-канал, если он есть.
    Возвращает BGRA uint8 (H,W,4) при наличии прозрачности, иначе BGR (H,W,3).
    Используется при добавлении overlay, чтобы PNG с прозрачностью не давал серый фон.

    Pillow — ОСНОВНОЙ путь (а не запасной): cv2.IMREAD_UNCHANGED роняет альфу у
    палитровых PNG c tRNS и у grayscale+alpha (декодит как BGR без прозрачности —
    отсюда серый фон у бейджей). Pillow достаёт альфу надёжно во всех вариантах
    (P+transparency, LA, PA, RGBA). Перестановку каналов делаем numpy-индексами,
    чтобы не зависеть от наличия cv2."""
    if _np is None:
        from lama_inpaint import load_bgr as _lb  # noqa — запасной вариант
        return _lb(path)
    try:
        from PIL import Image
        with Image.open(path) as pil:
            pil.load()
            has_alpha = (pil.mode in ('RGBA', 'LA', 'PA', 'La')
                         or (pil.mode in ('P', 'PA') and 'transparency' in pil.info)
                         or 'transparency' in pil.info)
            if has_alpha:
                rgba = _np.asarray(pil.convert('RGBA'), dtype=_np.uint8)
                return _np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]])  # RGBA → BGRA
            rgb = _np.asarray(pil.convert('RGB'), dtype=_np.uint8)
            return _np.ascontiguousarray(rgb[:, :, ::-1])               # RGB → BGR
    except Exception:
        pass
    # Фолбэк через OpenCV (если Pillow недоступен/не осилил формат).
    if _cv2 is not None:
        data = _np.fromfile(path, dtype=_np.uint8)
        img = _cv2.imdecode(data, _cv2.IMREAD_UNCHANGED) if data.size else None
        if img is not None:
            if img.ndim == 2:               # grayscale → BGR
                img = _cv2.cvtColor(img, _cv2.COLOR_GRAY2BGR)
            return _np.ascontiguousarray(img)  # 3ch=BGR, 4ch=BGRA
    from lama_inpaint import load_bgr as _lb
    return _lb(path)


_EYEDROPPER_CURSOR = None


def eyedropper_cursor():
    """Курсор-пипетка (как в Photoshop/Paint): значок «капельницы» с белой
    обводкой, чтобы он был виден на любой картинке. Горячая точка — на кончике
    пипетки (нижний-левый угол глифа). Кэшируется (строим один раз)."""
    global _EYEDROPPER_CURSOR
    if _EYEDROPPER_CURSOR is None:
        try:
            sz = 26
            halo = qta.icon('fa5s.eye-dropper', color='white').pixmap(QSize(sz, sz))
            glyph = qta.icon('fa5s.eye-dropper', color='#1e1e2e').pixmap(QSize(sz, sz))
            canvas = QPixmap(sz + 2, sz + 2)
            canvas.fill(Qt.GlobalColor.transparent)
            p = QPainter(canvas)
            for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2),
                           (0, 0), (2, 2), (0, 2), (2, 0)):
                p.drawPixmap(dx, dy, halo)     # белая обводка
            p.drawPixmap(1, 1, glyph)          # тёмный глиф поверх
            p.end()
            _EYEDROPPER_CURSOR = QCursor(canvas, 2, sz)   # кончик — внизу слева
        except Exception:
            _EYEDROPPER_CURSOR = QCursor(Qt.CursorShape.CrossCursor)
    return _EYEDROPPER_CURSOR


_WASD_VK = {0x57: (0, 1), 0x53: (0, -1), 0x41: (1, 0), 0x44: (-1, 0)}
_ARROW_PAN = {Qt.Key.Key_Left: (1, 0), Qt.Key.Key_Right: (-1, 0),
              Qt.Key.Key_Up: (0, 1), Qt.Key.Key_Down: (0, -1)}
_WASD_KEY = {Qt.Key.Key_A: (1, 0), Qt.Key.Key_D: (-1, 0),
             Qt.Key.Key_W: (0, 1), Qt.Key.Key_S: (0, -1)}


def _pan_dir_from_event(ev):
    """(sx, sy) для пана по WASD/стрелкам или None. Стрелки — по ev.key(), WASD — по
    nativeVirtualKey (любая раскладка), с фолбэком по ev.key() для латиницы."""
    d = _ARROW_PAN.get(ev.key())
    if d is not None:
        return d
    try:
        d = _WASD_VK.get(ev.nativeVirtualKey())
    except Exception:
        d = None
    if d is not None:
        return d
    return _WASD_KEY.get(ev.key())



class PhotoMergerTab(QWidget):
    # Форматы сохранения: (расширение, PIL-формат, параметры сохранения)
    _FMT_MAP = [
        ("tiff", "TIFF",  {"compression": "tiff_deflate"}),
        ("jpg",  "JPEG",  {"quality": 95}),
        ("png",  "PNG",   {}),
        ("webp", "WEBP",  {"quality": 90}),
    ]

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._build_ui()

    def insert_mode_switch(self, widget):
        """PhotoTab вставляет сюда переключатель режимов «Фото» (сверху левой
        панели, вместо верхней полосы вкладок)."""
        if hasattr(self, "_left_layout"):
            self._left_layout.insertWidget(0, widget)

    def set_left_width(self, w):
        """PhotoTab задаёт ширину левой панели под переключатель режима, чтобы
        обе подписи влезали целиком (как и в подвкладке редактирования)."""
        if hasattr(self, "_left_w"):
            self._left_w.setFixedWidth(int(w))

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        # ЛЕВО (1/3) — список файлов + настройки + кнопка объединения.
        # ПРАВО (2/3) — крупный просмотр результата.
        left_w = QWidget(); left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0); left.setSpacing(8)
        left_w.setMinimumWidth(220)
        self._left_w = left_w      # PhotoTab подгонит ширину под переключатель режима
        self._left_layout = left   # сюда PhotoTab вставит переключатель режима
        right_w = QWidget(); right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0); right.setSpacing(8)
        # Пропорция ~1/3 : 2/3.
        root.addWidget(left_w, 1); root.addWidget(right_w, 2)

        # ── Status bar ─────────────────────────────────────
        # Только подсказка статуса; кнопки добавления/удаления вынесены ВНИЗ,
        # под список файлов.
        top = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 13px;")
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.lbl_status, 1)
        left.addLayout(top)

        # ── File list (зона, куда кидать файлы) ──────────────
        self.file_list = PhotoDragList()
        left.addWidget(self.file_list, 1)
        # Клавиша Delete — удалить выделенные фото из списка
        self._sc_delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.file_list)
        self._sc_delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_delete.activated.connect(self._remove_selected)

        # ── Кнопки добавления/удаления (ПОД списком) ─────────
        # Без setFixedWidth — крупный шрифт обрезал подписи («Добави…», «Очистить вс…»).
        # Кнопки берут ширину по содержимому; замыкающий stretch держит их слева.
        btns = QHBoxLayout()
        btn_open = _icon_btn("Добавить", 'fa5s.folder-open')
        btn_open.clicked.connect(self._open_files)

        btn_clear_sel = _icon_btn("Удалить", 'fa5s.times')
        btn_clear_sel.clicked.connect(self._remove_selected)

        btn_clear_all = _icon_btn("Очистить", 'fa5s.trash', color='#1e1e2e')
        btn_clear_all.setObjectName("b_stop")
        btn_clear_all.clicked.connect(self._clear_all)

        btns.addWidget(btn_open)
        btns.addWidget(btn_clear_sel)
        btns.addWidget(btn_clear_all)
        btns.addStretch()
        left.addLayout(btns)

        # ── Настройки объединения (под списком) ──────────────
        grp_set = QGroupBox("Настройки"); set_l = QVBoxLayout(grp_set)
        self.rb_horiz = _icon_btn("Горизонт.", 'fa5s.arrow-right')
        self.rb_vert  = _icon_btn("Вертикал.", 'fa5s.arrow-down')
        self.rb_horiz.setCheckable(True); self.rb_horiz.setChecked(True)
        self.rb_vert.setCheckable(True)
        self.rb_horiz.clicked.connect(lambda: self.rb_vert.setChecked(False))
        self.rb_vert.clicked.connect(lambda: self.rb_horiz.setChecked(False))
        row_mode = QHBoxLayout(); row_mode.addWidget(QLabel("Режим:"))
        row_mode.addWidget(self.rb_horiz); row_mode.addWidget(self.rb_vert)
        row_mode.addWidget(info_badge(
            "Как складывать картинки: «Горизонт.» — в ряд слева направо "
            "(выравниваются по высоте), «Вертикал.» — стопкой сверху вниз "
            "(выравниваются по ширине)."))
        row_mode.addStretch()
        set_l.addLayout(row_mode)

        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItems(["TIFF", "JPEG", "PNG", "WEBP"])
        self.cmb_fmt.setFixedWidth(90)
        row_fmt = QHBoxLayout(); row_fmt.addWidget(QLabel("Формат:"))
        row_fmt.addWidget(self.cmb_fmt)
        row_fmt.addWidget(info_badge(
            "Формат сохранения склейки: TIFF — без потерь (крупный файл); "
            "PNG — без потерь со сжатием; JPEG/WEBP — с потерями, файл меньше."))
        row_fmt.addStretch()
        set_l.addLayout(row_fmt)

        # SVG обычно имеет прозрачный фон — при объединении прозрачность заливается
        # чёрным. Галочка заливает прозрачный фон SVG белым перед склейкой.
        self.ck_svg_white = QCheckBox("SVG: сделать белым фон")
        self.ck_svg_white.setChecked(True)
        row_svg = QHBoxLayout(); row_svg.addWidget(self.ck_svg_white)
        row_svg.addWidget(info_badge(
            "Только для SVG: прозрачный фон вектора заливается белым перед "
            "объединением (иначе прозрачные области становятся чёрными)."))
        row_svg.addStretch()
        set_l.addLayout(row_svg)
        left.addWidget(grp_set)

        # Одна кнопка на всё: объединяет ВСЕ файлы из списка.
        self.btn_merge_new = _icon_btn("Объединить", 'fa5s.object-group', color='#1e1e2e')
        self.btn_merge_new.setObjectName("b_run")
        self.btn_merge_new.clicked.connect(lambda: self._do_merge(force_all=True))
        left.addWidget(self.btn_merge_new)

        # ── ПРАВО: крупный просмотр результата (2/3) ─────────
        # Холст справа одинаков с подвкладкой «Редактирование фото»: тот же тёмный
        # фон (#11111b) без светлой рамки/заголовка, чтобы при переключении
        # режимов правая область не «прыгала» (просьба пользователя). Результат
        # склейки по-прежнему показывается прямо в этом холсте.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea{background-color:#11111b; border:none;} "
            "QScrollArea > QWidget > QWidget{background-color:#11111b;}")
        self.lbl_preview = QLabel("Здесь появится результат")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet(
            "color: #585b70; font-size: 13px; background-color:#11111b;")
        scroll.setWidget(self.lbl_preview)
        right.addWidget(scroll, 1)

        # Плавающая кнопка «на весь экран» в правом нижнем углу превью результата.
        self._preview_scroll = scroll
        self._last_result_path = ""
        self.btn_preview_fs = QToolButton(scroll)
        self.btn_preview_fs.setIcon(get_icon('fa5s.expand'))
        self.btn_preview_fs.setToolTip("Открыть результат на весь экран")
        self.btn_preview_fs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_preview_fs.setFixedSize(34, 34)
        self.btn_preview_fs.setIconSize(QSize(18, 18))
        self.btn_preview_fs.setStyleSheet(
            "QToolButton{background:rgba(24,24,37,210);border:1px solid #45475a;"
            "border-radius:6px;} QToolButton:hover{background:rgba(49,50,68,235);"
            "border:1px solid #585b70;}")
        self.btn_preview_fs.clicked.connect(self._open_result_fullscreen)
        self.btn_preview_fs.hide()
        scroll.installEventFilter(self)

        # ── Accept drops on the whole widget ───────────────
        self.setAcceptDrops(True)

    def eventFilter(self, obj, ev):
        if obj is getattr(self, '_preview_scroll', None) and ev.type() == QEvent.Type.Resize:
            self._reposition_preview_fs()
        return super().eventFilter(obj, ev)

    def _reposition_preview_fs(self):
        """Держит плавающую кнопку в правом нижнем углу области превью."""
        try:
            s = self._preview_scroll
            m = 12
            self.btn_preview_fs.move(s.width() - self.btn_preview_fs.width() - m,
                                     s.height() - self.btn_preview_fs.height() - m)
            self.btn_preview_fs.raise_()
        except Exception:
            pass

    def _open_result_fullscreen(self):
        p = getattr(self, '_last_result_path', "")
        if p and os.path.exists(p):
            show_image_fullscreen(p, self)

    # ── Drag-and-drop forwarding ────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            links = [str(u.toLocalFile()) for u in event.mimeData().urls()]
            self.file_list.add_files(links)

    # ── Helpers ─────────────────────────────────────────────
    def add_paths(self, paths):
        _img = {'.png','.jpg','.jpeg','.bmp','.gif','.tiff','.tif',
                '.webp','.avif','.heic','.heif','.ico','.svg'}
        valid = [p for p in paths if os.path.splitext(p)[1].lower() in _img]
        if valid:
            self.file_list.add_files(valid)

    def _open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выбрать изображения", "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp *.avif *.heic *.heif *.ico *.svg)"
        )
        if files:
            self.file_list.add_files(files)

    def _remove_selected(self):
        for it in self.file_list.selectedItems():
            idx = self.file_list.indexOfTopLevelItem(it)
            if idx >= 0:
                self.file_list.takeTopLevelItem(idx)

    def _clear_all(self):
        self.file_list.clear()
        self.lbl_preview.clear()
        self.lbl_preview.setText("Здесь появится результат")
        self.lbl_status.setText("Список очищен")
        self._last_result_path = ""
        self.btn_preview_fs.hide()

    # ── Core merge ──────────────────────────────────────────
    def _do_merge(self, force_all: bool):
        if not Image:
            self.lbl_status.setText(status_html('fa5s.times-circle', "Pillow не установлен (pip install Pillow)", '#f38ba8'))
            return

        items = self.file_list.get_all_items() if force_all else self.file_list.get_new_items()

        if not items:
            self.lbl_status.setText("Список пуст!")
            return

        try:
            paths = [it.data(0, Qt.ItemDataRole.UserRole) for it in items]
            svg_white = self.ck_svg_white.isChecked()
            imgs = []
            for p in paths:
                im = open_image_any(p)
                # Прозрачный фон SVG по умолчанию станет чёрным при склейке —
                # по галочке заливаем его белым.
                if (svg_white and os.path.splitext(p)[1].lower() == '.svg'
                        and im.mode in ('RGBA', 'LA', 'PA', 'La', 'RGBa')):
                    rgba = im.convert('RGBA')
                    bg = Image.new('RGB', rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.split()[3])
                    im = bg
                imgs.append(im)

            vertical = self.rb_vert.isChecked()

            # Сохраняем прозрачность, если ВЫХОДНОЙ формат её поддерживает
            # (PNG/WEBP/TIFF) и хотя бы у одной картинки есть альфа. Тогда холст —
            # RGBA с прозрачным фоном. Иначе RGB на чёрном фоне (как раньше; JPEG
            # альфу не умеет).
            ext, pil_fmt, save_kwargs = self._FMT_MAP[self.cmb_fmt.currentIndex()]

            def _has_alpha(im):
                return (im.mode in ('RGBA', 'LA', 'PA', 'La', 'RGBa')
                        or (im.mode == 'P' and 'transparency' in im.info))

            keep_alpha = (pil_fmt in ('PNG', 'WEBP', 'TIFF')
                          and any(_has_alpha(im) for im in imgs))
            cmode = 'RGBA' if keep_alpha else 'RGB'
            bg = (0, 0, 0, 0) if keep_alpha else (0, 0, 0)
            # Приводим к режиму холста ДО ресайза (ресайз RGBA сохраняет альфу).
            imgs = [im if im.mode == cmode else im.convert(cmode) for im in imgs]

            if vertical:
                max_w = max(im.width for im in imgs)
                processed = []
                total_h = 0
                for im in imgs:
                    r = max_w / im.width
                    new_h = int(im.height * r)
                    processed.append(im.resize((max_w, new_h), Image.Resampling.LANCZOS))
                    total_h += new_h
                canvas = Image.new(cmode, (max_w, total_h), bg)
                y = 0
                for im in processed:
                    canvas.paste(im, (0, y)); y += im.height
            else:
                max_h = max(im.height for im in imgs)
                processed = []
                total_w = 0
                for im in imgs:
                    r = max_h / im.height
                    new_w = int(im.width * r)
                    processed.append(im.resize((new_w, max_h), Image.Resampling.LANCZOS))
                    total_w += new_w
                canvas = Image.new(cmode, (total_w, max_h), bg)
                x = 0
                for im in processed:
                    canvas.paste(im, (x, 0)); x += im.width

            # ── Output path: всегда рядом с исходными файлами ──
            out_dir = os.path.dirname(paths[0]) or "."

            out_path = os.path.join(out_dir, f"merged_{random.randint(1000, 9999)}.{ext}")
            canvas.save(out_path, format=pil_fmt, **save_kwargs)

            # ── Mark items ─────────────────────────────────
            self.file_list.mark_processed(items)

            # ── Preview ────────────────────────────────────
            pix = QPixmap(out_path)
            prev_w = self.lbl_preview.parent().width() - 30
            if prev_w < 80: prev_w = 80
            self.lbl_preview.setPixmap(
                pix.scaledToWidth(prev_w, Qt.TransformationMode.SmoothTransformation))
            # Запоминаем результат и показываем кнопку «на весь экран».
            self._last_result_path = out_path
            self.btn_preview_fs.show()
            self._reposition_preview_fs()

            self.lbl_status.setText(status_html('fa5s.check-circle',
                f"Готово! {len(imgs)} фото → {os.path.basename(out_path)}", '#a6e3a1'))
            self.main.log(f"[Фото] Объединено {len(imgs)} файлов → {out_path}")

            # ── Отправить результат в очередь первой вкладки ──
            try:
                self.main.tab_media.add_paths([out_path])
                self.main.tabs.setCurrentWidget(self.main.tab_media)
                self.main.log(f"[Фото] Файл добавлен в очередь обработки: {os.path.basename(out_path)}")
            except Exception as send_exc:
                self.main.log(f"[Фото] Не удалось добавить в очередь: {send_exc}")

            try: play_done_sound()
            except Exception: pass

        except Exception as exc:
            try: self.file_list.mark_failed(items)
            except Exception: pass
            self.lbl_status.setText(status_html('fa5s.times-circle', f"Ошибка: {exc}", '#f38ba8'))
            self.main.log(f"[Фото] Ошибка объединения: {exc}")
        finally:
            # Закрываем все PIL-изображения, чтобы избежать утечки памяти
            for im in imgs if 'imgs' in dir() else []:
                try: im.close()
                except Exception: pass


# ════════════════════════════════════════════════════════════════════════════
#  Удаление объектов / водяных знаков (LaMa, ONNX)
# ════════════════════════════════════════════════════════════════════════════
# WASD-пан, независимый от раскладки: на кириллице ev.key() физической W даёт Key_Ц,
# поэтому WASD читаем по nativeVirtualKey (Windows VK W=0x57/A=0x41/S=0x53/D=0x44).

class InpaintCanvas(QWidget):
    """Холст редактора: показ изображения с зумом/панорамированием, рисование
    маски кистью/ластиком (полупрозрачным красным), инструмент кадрирования.

    Источник истины — numpy-массив BGR (self.img_bgr). Маска хранится как ARGB
    QImage-оверлей в РАЗРЕШЕНИИ изображения (а не экрана), поэтому точность не
    зависит от зума. Для инференса маска вынимается из альфа-канала оверлея."""

    TOOL_BRUSH = "brush"   # рисующая кисть ПО фото (мазок вживается в img_bgr)
    TOOL_MASK = "mask"     # кисть-маска: красным помечает область для удаления (LaMa)
    TOOL_ERASE = "erase"
    TOOL_CROP = "crop"
    TOOL_MOVE = "move"   # перемещение наложенного (второго) изображения-слоя
    # Фигуры и текст (как в Paint) — рисуются прямо в изображение (self.img_bgr),
    # а не в маску-оверлей.
    TOOL_RECT = "rect"
    TOOL_ELLIPSE = "ellipse"
    TOOL_LINE = "line"
    TOOL_ARROW = "arrow"
    TOOL_TEXT = "text"
    _SHAPE_TOOLS = (TOOL_RECT, TOOL_ELLIPSE, TOOL_LINE, TOOL_ARROW)

    # Толщина скроллбаров, всплывающих при сильном приближении.
    _SB_THICK = 12

    statusChanged = pyqtSignal(str)
    colorPicked = pyqtSignal(QColor)     # Alt-пипетка взяла цвет из изображения
    strokeFinished = pyqtSignal()        # завершён штрих кистью (для авто-удаления)
    clearRequested = pyqtSignal()        # нажата кнопка «Очистить» в углу холста
    imageChanged = pyqtSignal()          # появилось/исчезло изображение (undo/redo) — пере-включить инструменты
    textSelected = pyqtSignal()          # плавающий текст создан/выделен — открыть панель его свойств

    def __init__(self, parent=None):
        super().__init__(parent)
        self.img_bgr = None             # numpy (H,W,3) BGR — рабочее изображение
        self._overlay = None            # QImage ARGB32_Premult (H,W) — маска удаления (красная)
        # Слой краски «Кисти»: непрозрачные мазки поверх фото, НЕ вживляются сразу
        # (как в Photoshop), чтобы их можно было стирать Ластиком. Вживляются в
        # img_bgr только перед удалением объекта / кадрированием / сохранением.
        self._paint_layer = None        # QImage ARGB32_Premult (H,W) — мазки кисти
        self._has_paint = False
        # Маска прозрачности после «Удалить фон» (RMBG): numpy (H,W) uint8 [0..255],
        # 255 = объект (видимый), 0 = фон (прозрачный). None — фон не удалён.
        # Хранится ОТДЕЛЬНО от img_bgr (он всегда 3-канальный BGR); прозрачность
        # показываем шахматкой в _rebuild_base, а при сохранении склеиваем в BGRA.
        self._alpha = None
        self._base_pix = None           # QPixmap кэш изображения для отрисовки
        self._overlay_btns_state = None  # memo-ключ _sync_overlay_buttons (см. там)
        self._scale = 1.0
        self._off = QPointF(0, 0)
        self._user_zoomed = False
        self._tool = self.TOOL_MOVE
        self._brush = 30                # диаметр кисти в ЭКРАННЫХ px
        self._brush_color = QColor(235, 45, 45)   # цвет рисующей кисти (по фото)
        self._painting = False
        self._panning = False
        self._last_img_pt = None        # последняя точка штриха (коорд. изображения)
        self._pan_start = None
        self._off_start = None
        self._mouse_w = None            # позиция мыши (виджет) для кольца-курсора
        self._alt = False               # зажат ли Alt (кисть → временная пипетка)
        self._has_strokes = False
        # Фигуры (Paint): тянем от _shape_start до _shape_cur (коорд. изображения),
        # коммитим в картинку на отпускании ЛКМ. _shape_fill — заливать ли фигуру.
        self._shape_start = None
        self._shape_cur = None
        self._shape_drawing = False
        self._shape_fill = False
        # Шрифт инструмента «Текст» (по умолчанию — системный, 48 px высотой).
        self._text_font = QFont()
        self._text_font.setPixelSize(48)
        self._text_color = QColor(255, 255, 255)     # цвет НОВОГО текста (не влияет на уже созданный)
        self._text_stroke_width = 0.0
        self._text_stroke_color = QColor(0, 0, 0)
        self._crop_a = None             # верх-лев угол рамки кадрирования (коорд. изобр.)
        self._crop_b = None             # ниж-прав угол рамки кадрирования
        self._crop_drag = None          # активная «ручка»: tl/tr/bl/br/t/b/l/r/move
        self._crop_anchor = None        # точка-якорь (коорд. изобр.) при перетаскивании
        self._crop_start = None         # (a, b) на момент начала перетаскивания
        self._crop_aspect = None        # пропорция w/h рамки (None = свободно)
        self._history = []              # [(img_bgr, overlay QImage)] для отмены
        self._redo = []                 # стек возврата (Ctrl+Y)
        self._HISTORY_MAX = 8
        # Кэш PNG-кодирования img_bgr для _snapshot(): само фото не меняется во
        # время штриха кистью/ластиком (мазки идут в _paint_layer), а перекодировать
        # его целиком на КАЖДОЕ нажатие ЛКМ (_push_history) — это заметный фриз
        # на крупных фото (счёт на сотни мс). img_bgr всегда переприсваивается
        # новым массивом при реальном изменении (поворот/кроп/bake) — сравнение
        # по identity безопасно.
        self._bgr_snap_src = None
        self._bgr_snap_enc = None
        # Незакреплённый («плавающий») объект — фигура или текст, который только
        # что положили: его можно ПЕРЕТАСКИВАТЬ (как в Photoshop), пока не вжали в
        # картинку. Вжигается при клике вне него / смене инструмента / Enter / сейве.
        #   shape: {'kind':'shape','tool',a,b,'color','thickness','fill'}
        #   text:  {'kind':'text','pos','text','font','color'}
        self._pending = None
        self._pending_move = False      # тащим ли сейчас плавающий объект
        self._pending_anchor = None     # точка-якорь (коорд. изобр.) при перетаскивании
        self._pending_resize = None     # имя тянущейся ручки ('tl'..'r') или None
        self._pending_rs_rect0 = None   # bbox объекта на начало resize (коорд. изобр.)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 280)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Кнопки «Применить/Отмена» кадрирования живут ПРЯМО на холсте (как в
        # Photoshop): всплывают у рамки кадрирования, когда активен инструмент.
        self._crop_apply_btn = _icon_btn("Применить", 'fa5s.check', size=16)
        self._crop_apply_btn.setParent(self)
        self._crop_apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._crop_apply_btn.setToolTip("Применить кадрирование (Enter)")
        self._crop_apply_btn.clicked.connect(self.apply_crop)
        self._crop_apply_btn.setStyleSheet(
            "QPushButton{background:#a6e3a1;color:#1e1e2e;border:none;"
            "border-radius:5px;padding:5px 10px;font-weight:600;}"
            "QPushButton:hover{background:#b9f0b4;}")
        self._crop_cancel_btn = _icon_btn("Отмена", 'fa5s.times', size=16)
        self._crop_cancel_btn.setParent(self)
        self._crop_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._crop_cancel_btn.setToolTip("Отменить кадрирование (Esc)")
        self._crop_cancel_btn.clicked.connect(self.cancel_crop)
        self._crop_cancel_btn.setStyleSheet(
            "QPushButton{background:#313244;color:#cdd6f4;border:1px solid #45475a;"
            "border-radius:5px;padding:5px 10px;}"
            "QPushButton:hover{background:#45475a;}")
        for _b in (self._crop_apply_btn, self._crop_cancel_btn):
            _b.setVisible(False)

        # Выбор пропорций кадрирования ПРЯМО на холсте (как в Photoshop): свободно
        # или фиксированное соотношение (1:1, 4:3, 16:9 …). Всплывает над рамкой.
        self._crop_aspect_combo = QComboBox(self)
        self._crop_aspect_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._crop_aspect_combo.setToolTip("Пропорции рамки кадрирования")
        # (подпись, w/h или None=свободно). «Исходное» считается от размера картинки.
        self._crop_aspect_items = [
            ("Свободно", None), ("Исходное", 'orig'), ("1:1", 1.0),
            ("4:3", 4 / 3), ("3:4", 3 / 4), ("3:2", 3 / 2), ("2:3", 2 / 3),
            ("16:9", 16 / 9), ("9:16", 9 / 16), ("5:4", 5 / 4)]
        for name, _v in self._crop_aspect_items:
            self._crop_aspect_combo.addItem(name)
        self._crop_aspect_combo.setStyleSheet(
            "QComboBox{background:#1e1e2e;color:#cdd6f4;border:1px solid #45475a;"
            "border-radius:5px;padding:3px 8px;font-weight:600;}"
            "QComboBox:hover{border:1px solid #89b4fa;}"
            "QComboBox QAbstractItemView{background:#1e1e2e;color:#cdd6f4;"
            "selection-background-color:#45475a;}")
        self._crop_aspect_combo.currentIndexChanged.connect(self._on_crop_aspect_changed)
        self._crop_aspect_combo.setVisible(False)

        # Отмена/возврат — компактные значки в левом верхнем углу холста (как в
        # фоторедакторах), без подписей. Прямые стрелки влево/вправо, как кнопки
        # «назад/вперёд» в браузере (а не закруглённые fa5s.undo/redo). Доступны,
        # пока есть изображение.
        self._undo_btn = QPushButton(self)
        self._undo_btn.setIcon(get_icon('fa5s.arrow-left'))
        self._undo_btn.setToolTip("Отменить (Ctrl+Z)")
        self._undo_btn.clicked.connect(self.undo)
        self._redo_btn = QPushButton(self)
        self._redo_btn.setIcon(get_icon('fa5s.arrow-right'))
        self._redo_btn.setToolTip("Вернуть (Ctrl+Y)")
        self._redo_btn.clicked.connect(self.redo)
        for _b in (self._undo_btn, self._redo_btn):
            _b.setParent(self)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setFixedSize(34, 30)
            _b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _b.setStyleSheet(
                "QPushButton{background:rgba(30,30,46,0.82);color:#cdd6f4;"
                "border:1px solid #45475a;border-radius:6px;}"
                "QPushButton:hover{background:rgba(69,71,90,0.95);}"
                "QPushButton:disabled{color:#585b70;border-color:#313244;}")
            _b.setVisible(False)

        # «Очистить» — значок в ПРАВОМ верхнем углу холста (как кнопка закрытия
        # документа в фоторедакторах). Сам сброс делает вкладка (clearRequested).
        self._clear_btn = QPushButton(self)
        self._clear_btn.setIcon(get_icon('fa5s.trash'))
        self._clear_btn.setToolTip("Очистить холст — убрать изображение и все мазки")
        self._clear_btn.setParent(self)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setFixedSize(34, 30)
        self._clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._clear_btn.setStyleSheet(
            "QPushButton{background:rgba(30,30,46,0.82);color:#f38ba8;"
            "border:1px solid #45475a;border-radius:6px;}"
            "QPushButton:hover{background:rgba(243,139,168,0.22);border-color:#f38ba8;}")
        self._clear_btn.clicked.connect(self.clearRequested.emit)
        self._clear_btn.setVisible(False)

        # Поворот/отражение — значки по центру сверху холста (видны при наличии
        # картинки; каждое действие в историю — см. rotate_image/flip_image).
        self._rotl_btn = QPushButton(self)
        self._rotl_btn.setIcon(get_icon('mdi6.rotate-left'))
        self._rotl_btn.setToolTip("Повернуть против часовой стрелки")
        self._rotl_btn.clicked.connect(lambda: self.rotate_image(False))
        self._rotr_btn = QPushButton(self)
        self._rotr_btn.setIcon(get_icon('mdi6.rotate-right'))
        self._rotr_btn.setToolTip("Повернуть по часовой стрелке")
        self._rotr_btn.clicked.connect(lambda: self.rotate_image(True))
        self._fliph_btn = QPushButton(self)
        self._fliph_btn.setIcon(get_icon('mdi6.flip-horizontal'))
        self._fliph_btn.setToolTip("Отразить по горизонтали (зеркально)")
        self._fliph_btn.clicked.connect(lambda: self.flip_image(True))
        self._flipv_btn = QPushButton(self)
        self._flipv_btn.setIcon(get_icon('mdi6.flip-vertical'))
        self._flipv_btn.setToolTip("Отразить по вертикали")
        self._flipv_btn.clicked.connect(lambda: self.flip_image(False))
        self._orient_btns = [self._rotl_btn, self._rotr_btn,
                             self._fliph_btn, self._flipv_btn]
        for _b in self._orient_btns:
            _b.setParent(self)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setFixedSize(34, 30)
            _b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _b.setStyleSheet(
                "QPushButton{background:rgba(30,30,46,0.82);color:#cdd6f4;"
                "border:1px solid #45475a;border-radius:6px;}"
                "QPushButton:hover{background:rgba(69,71,90,0.95);}"
                "QPushButton:disabled{color:#585b70;border-color:#313244;}")
            _b.setVisible(False)

        # Скроллбары всплывают при сильном приближении (когда картинка не влезает
        # в холст) — как в Photoshop/Paint. Перетаскивание ползунка двигает кадр.
        self._syncing_bars = False
        self._hbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self._vbar = QScrollBar(Qt.Orientation.Vertical, self)
        for _sb in (self._hbar, self._vbar):
            _sb.setCursor(Qt.CursorShape.ArrowCursor)
            _sb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _sb.setVisible(False)
        self._hbar.valueChanged.connect(self._on_hbar)
        self._vbar.valueChanged.connect(self._on_vbar)

    def _sync_overlay_buttons(self):
        """Показ/позиция/доступность значков отмены-возврата (слева сверху) и
        кнопки «Очистить» (справа сверху) на холсте.
        Вызывается из paintEvent на КАЖДЫЙ репейнт (в т.ч. на каждый мазок кисти
        при рисовании) — но фактическая раскладка зависит только от небольшого
        набора значений; если ни один не изменился с прошлого вызова, репозиция
        виджетов (десяток .move()/.setEnabled() на кадр) не нужна."""
        has = self.img_bgr is not None
        state = (has, self.width(),
                 bool(self._history), bool(self._redo),
                 self._vbar.isVisible() if has else False)
        if state == self._overlay_btns_state:
            return
        self._overlay_btns_state = state
        all_btns = [self._undo_btn, self._redo_btn, self._clear_btn] + self._orient_btns
        for b in all_btns:
            b.setVisible(has)
        if not has:
            return
        x, y, gap = 8, 8, 6
        self._undo_btn.move(x, y)
        self._redo_btn.move(x + self._undo_btn.width() + gap, y)
        self._undo_btn.setEnabled(bool(self._history))
        self._redo_btn.setEnabled(bool(self._redo))
        # «Очистить» — у правого края холста (с учётом возможного скроллбара).
        sb = self._SB_THICK if self._vbar.isVisible() else 0
        self._clear_btn.move(self.width() - self._clear_btn.width() - 8 - sb, y)
        # Поворот/отражение — по центру верхней кромки холста, в ряд.
        ob = self._orient_btns
        bw = ob[0].width()
        total = bw * len(ob) + gap * (len(ob) - 1)
        ox = max(0, (self.width() - total) // 2)
        for i, b in enumerate(ob):
            b.move(ox + i * (bw + gap), y)
        for b in all_btns:
            b.raise_()

    # ── Состояние / загрузка ────────────────────────────────────────────────
    def has_image(self) -> bool:
        return self.img_bgr is not None

    def has_mask(self) -> bool:
        return self._has_strokes

    def set_image_bgr(self, arr):
        self.img_bgr = _np.ascontiguousarray(arr)
        h, w = self.img_bgr.shape[:2]
        self._overlay = QtGuiImage(w, h, QtGuiImage.Format.Format_ARGB32_Premultiplied)
        self._overlay.fill(0)
        self._paint_layer = QtGuiImage(w, h, QtGuiImage.Format.Format_ARGB32_Premultiplied)
        self._paint_layer.fill(0)
        self._has_paint = False
        self._alpha = None          # новая картинка — прозрачности нет
        self._has_strokes = False
        self._history.clear()
        self._redo.clear()
        self._pending = None
        self._pending_move = False
        self._crop_a = self._crop_b = None
        self._rebuild_base()
        self._user_zoomed = False
        self._fit()
        self._update_crop_buttons()
        self.update()

    def load_path(self, path):
        # _load_image_alpha (не load_bgr) — иначе прозрачность PNG/WEBP/AVIF
        # терялась бы уже при открытии (cv2.IMREAD_COLOR альфу отбрасывает).
        arr = _load_image_alpha(path)
        if arr.ndim == 3 and arr.shape[2] == 4:
            self.set_image_bgr(arr[:, :, :3])
            self.apply_cutout(arr[:, :, 3])
        else:
            self.set_image_bgr(arr)

    def add_overlay_image(self, arr):
        """Кладёт изображение arr (BGR H×W×3 или BGRA H×W×4) как плавающий слой
        поверх текущего — центрированно. Прозрачность PNG/WEBP сохраняется.
        Пользователь перетаскивает его мышью до вжигания (Enter, клик вне, смена
        инструмента). Предыдущий незакреплённый объект вжигается."""
        if self.img_bgr is None or arr is None:
            return
        self._commit_pending()
        arr = _np.ascontiguousarray(arr)
        has_alpha = (arr.ndim == 3 and arr.shape[2] == 4)
        if has_alpha:
            qimg = np_bgra_to_qimage(arr)
        else:
            qimg = np_bgr_to_qimage(arr)
        h, w = arr.shape[:2]
        bh, bw = self.img_bgr.shape[:2]
        pix = QPixmap.fromImage(qimg)
        # Если картинка крупнее холста — вписываем её в ~85% кадра (иначе слой
        # вылезал бы за границы и его углы-ручки были бы недосягаемы).
        dw, dh = float(w), float(h)
        fit = min(1.0, 0.85 * bw / dw, 0.85 * bh / dh)
        dw *= fit; dh *= fit
        cx = (bw - dw) / 2.0
        cy = (bh - dh) / 2.0
        self._pending = {'kind': 'image', 'pix': pix,
                         'pos': QPointF(cx, cy), 'w': dw, 'h': dh}
        self._pending_move = False
        self._pending_resize = None
        self.update()
        self.statusChanged.emit(
            "Курсор: тяните за уголки — размер, внутри — перенос. "
            "Enter/клик вне — вжать, Esc — убрать.")

    def _rebuild_base(self):
        if self.img_bgr is None:
            self._base_pix = None
            return
        # После «Удалить фон» — рисуем объект на шахматке (как в Photoshop), чтобы
        # прозрачные области были видны. Иначе — обычное непрозрачное изображение.
        if self._alpha is not None:
            h, w = self.img_bgr.shape[:2]
            bgra = _np.dstack([self.img_bgr, self._alpha])
            rgba = np_bgra_to_qimage(_np.ascontiguousarray(bgra))
            pm = QPixmap(w, h)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            self._draw_checker(p, w, h)
            p.drawImage(0, 0, rgba)
            p.end()
            self._base_pix = pm
        else:
            self._base_pix = QPixmap.fromImage(np_bgr_to_qimage(self.img_bgr))

    @staticmethod
    def _draw_checker(painter, w, h, cell=16):
        """Шахматка прозрачности (два серых тона) — фон под вырезанным объектом."""
        painter.fillRect(0, 0, w, h, QColor(120, 120, 128))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(150, 150, 158))
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                if ((x // cell) + (y // cell)) % 2 == 0:
                    painter.drawRect(x, y, cell, cell)

    def has_alpha(self) -> bool:
        return self._alpha is not None

    def apply_cutout(self, alpha):
        """Применяет маску переднего плана (RMBG): фон становится прозрачным.
        alpha — numpy (H,W) uint8 [0..255]. Историю НЕ трогаем (её снял вызывающий)."""
        if self.img_bgr is None or alpha is None:
            return
        h, w = self.img_bgr.shape[:2]
        alpha = _np.ascontiguousarray(alpha)
        if alpha.shape[:2] != (h, w):
            alpha = _cv2.resize(alpha, (w, h), interpolation=_cv2.INTER_LINEAR)
        self._alpha = alpha.astype(_np.uint8)
        self._rebuild_base()
        self.update()

    def composited_bgra(self):
        """Картинка для СОХРАНЕНИЯ: вжатые мазки кисти + альфа прозрачности.
        Возвращает BGRA (H,W,4), если фон удалён, иначе BGR (H,W,3)."""
        if self.img_bgr is None:
            return None
        bgr = self.composited_bgr()
        if self._alpha is None:
            return bgr
        alpha = self._alpha.copy()
        # Мазки «Кисти» поверх прозрачного фона должны быть видимы → делаем их
        # непрозрачными в альфе (иначе пользователь рисует «в пустоту»).
        if self._paint_layer is not None:
            pa = self._layer_alpha(self._paint_layer)
            alpha = _np.maximum(alpha, (pa > 10).astype(_np.uint8) * 255)
        return _np.ascontiguousarray(_np.dstack([bgr, alpha]))

    # ── История / отмена / возврат ──────────────────────────────────────────
    @staticmethod
    def _encode_layer(obj):
        """Сжимает слой истории в PNG (lossless) вместо хранения сырого буфера —
        маски/слой кисти по большей части прозрачны/однородны и жмутся в разы
        (при _HISTORY_MAX=8 и 4 слоях на шаг сырые копии на 4K-фото легко уходят
        в сотни МБ)."""
        if obj is None:
            return None
        if isinstance(obj, _np.ndarray):
            ok, buf = _cv2.imencode('.png', obj)
            return ('np', buf.tobytes()) if ok else ('raw', obj)
        from PyQt6.QtCore import QBuffer
        ba = QByteArray()
        qbuf = QBuffer(ba)
        qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
        obj.save(qbuf, 'PNG')
        qbuf.close()
        return ('qimg', bytes(ba))

    @staticmethod
    def _decode_layer(enc):
        if enc is None:
            return None
        kind, raw = enc
        if kind == 'raw':
            return raw
        if kind == 'np':
            return _cv2.imdecode(_np.frombuffer(raw, _np.uint8), _cv2.IMREAD_UNCHANGED)
        img = QtGuiImage.fromData(raw, 'PNG')
        if img.format() != QtGuiImage.Format.Format_ARGB32_Premultiplied:
            img = img.convertToFormat(QtGuiImage.Format.Format_ARGB32_Premultiplied)
        return img

    def _snapshot(self):
        """Текущее состояние для истории: картинка + маска удаления + слой краски.
        Хранится в сжатом (PNG) виде — см. _encode_layer; любой слой может быть
        None (напр. после очистки)."""
        ov = self._encode_layer(self._overlay)
        pl = self._encode_layer(self._paint_layer)
        al = self._encode_layer(self._alpha)
        if self.img_bgr is self._bgr_snap_src:
            bgr = self._bgr_snap_enc
        else:
            bgr = self._encode_layer(self.img_bgr)
            self._bgr_snap_src = self.img_bgr
            self._bgr_snap_enc = bgr
        return (bgr, ov, pl, al)

    def _push_history(self):
        if self.img_bgr is None:
            return
        self._history.append(self._snapshot())
        if len(self._history) > self._HISTORY_MAX:
            self._history.pop(0)
        # Любое новое действие обнуляет «возврат» — классическое поведение undo/redo.
        self._redo.clear()

    def _restore_state(self, snap, msg):
        img_enc, ov_enc, pl_enc, al_enc = snap
        img = self._decode_layer(img_enc)
        ov = self._decode_layer(ov_enc)
        pl = self._decode_layer(pl_enc)
        al = self._decode_layer(al_enc)
        # Восстановление в «очищенный» холст (img is None) — напр. отмена «Очистить».
        if img is None:
            self.img_bgr = None
            self._overlay = None
            self._paint_layer = None
            self._alpha = None
            self._base_pix = None
            self._has_strokes = False
            self._has_paint = False
            self._crop_a = self._crop_b = None
            self._update_crop_buttons()
            self.update()
            self.statusChanged.emit(msg)
            self.imageChanged.emit()
            return
        same_size = (self.img_bgr is not None
                     and img.shape[:2] == self.img_bgr.shape[:2])
        self.img_bgr = img
        self._overlay = ov
        self._paint_layer = pl
        self._alpha = al
        self._recompute_strokes_flag()
        self._recompute_paint_flag()
        self._rebuild_base()
        if not same_size:
            self._user_zoomed = False
            self._fit()
        self._update_crop_buttons()
        self.update()
        self.statusChanged.emit(msg)
        self.imageChanged.emit()

    def undo(self):
        # Незакреплённый объект сперва вжигаем, чтобы история была согласованной.
        self._commit_pending()
        if not self._history:
            return
        self._redo.append(self._snapshot())
        if len(self._redo) > self._HISTORY_MAX:
            self._redo.pop(0)
        self._restore_state(self._history.pop(), "Отменено.")

    def redo(self):
        self._commit_pending()
        if not self._redo:
            return
        self._history.append(self._snapshot())
        if len(self._history) > self._HISTORY_MAX:
            self._history.pop(0)
        self._restore_state(self._redo.pop(), "Возвращено.")

    # ── Поворот / отражение ─────────────────────────────────────────────────
    def _transform_qimage(self, img, transform):
        """Применяет QTransform к ARGB-слою (маска удаления / краска), сохраняя
        формат premultiplied и точные новые размеры. None → None."""
        if img is None:
            return None
        out = img.transformed(transform, Qt.TransformationMode.FastTransformation)
        if out.format() != QtGuiImage.Format.Format_ARGB32_Premultiplied:
            out = out.convertToFormat(QtGuiImage.Format.Format_ARGB32_Premultiplied)
        return out

    def _after_orient_change(self, msg):
        """Общий хвост поворота/отражения: рамка кадрирования сбрасывается,
        флаги/база/масштаб пересчитываются, история уже снята вызывающим."""
        self._crop_a = self._crop_b = None
        self._recompute_strokes_flag()
        self._recompute_paint_flag()
        self._rebuild_base()
        self._user_zoomed = False
        self._fit()
        self._update_crop_buttons()
        self.update()
        self.statusChanged.emit(msg)
        self.imageChanged.emit()

    def rotate_image(self, clockwise=True):
        """Поворот картинки на 90° (меняет местами ширину/высоту). Согласованно
        поворачивает альфу (numpy) и ARGB-слои (через QTransform)."""
        if self.img_bgr is None:
            return
        self._commit_pending()
        if self.has_crop():
            self.cancel_crop()
        self._push_history()
        from PyQt6.QtGui import QTransform
        # np.rot90: k=-1 = по часовой; QTransform.rotate(+90) тоже по часовой —
        # оба слоя поворачиваются в одну сторону и остаются пиксель-в-пиксель.
        k = -1 if clockwise else 1
        self.img_bgr = _np.ascontiguousarray(_np.rot90(self.img_bgr, k))
        if self._alpha is not None:
            self._alpha = _np.ascontiguousarray(_np.rot90(self._alpha, k))
        t = QTransform().rotate(90 if clockwise else -90)
        self._overlay = self._transform_qimage(self._overlay, t)
        self._paint_layer = self._transform_qimage(self._paint_layer, t)
        self._after_orient_change("Повёрнуто.")

    def flip_image(self, horizontal=True):
        """Зеркальное отражение по горизонтали (horizontal=True) или вертикали."""
        if self.img_bgr is None:
            return
        self._commit_pending()
        if self.has_crop():
            self.cancel_crop()
        self._push_history()
        from PyQt6.QtGui import QTransform
        if horizontal:
            self.img_bgr = _np.ascontiguousarray(self.img_bgr[:, ::-1])
            if self._alpha is not None:
                self._alpha = _np.ascontiguousarray(self._alpha[:, ::-1])
            t = QTransform().scale(-1, 1)
        else:
            self.img_bgr = _np.ascontiguousarray(self.img_bgr[::-1])
            if self._alpha is not None:
                self._alpha = _np.ascontiguousarray(self._alpha[::-1])
            t = QTransform().scale(1, -1)
        self._overlay = self._transform_qimage(self._overlay, t)
        self._paint_layer = self._transform_qimage(self._paint_layer, t)
        self._after_orient_change("Отражено.")

    def _recompute_strokes_flag(self):
        try:
            self._has_strokes = self._mask_alpha().max() > 10
        except Exception:
            self._has_strokes = False

    def _layer_alpha(self, img):
        """Альфа-канал произвольного ARGB-оверлея как numpy (H,W) uint8."""
        a = img.convertToFormat(QtGuiImage.Format.Format_ARGB32)
        w, h = a.width(), a.height()
        bpl = a.bytesPerLine()
        ptr = a.constBits(); ptr.setsize(bpl * h)
        buf = _np.frombuffer(ptr, _np.uint8).reshape(h, bpl)
        return _np.ascontiguousarray(buf[:, :w * 4].reshape(h, w, 4)[..., 3])

    def _recompute_paint_flag(self):
        try:
            self._has_paint = (self._paint_layer is not None
                               and self._layer_alpha(self._paint_layer).max() > 10)
        except Exception:
            self._has_paint = False

    # ── Инструменты / параметры ─────────────────────────────────────────────
    def set_tool(self, tool):
        # Смена инструмента закрепляет ещё не вжатый плавающий объект (как в
        # Photoshop: переключился на другой инструмент — текущий слой «лёг»).
        # Исключение: TOOL_MOVE специально нужен, чтобы двигать этот слой, —
        # коммитить при переключении на него нельзя.
        if tool != self.TOOL_MOVE:
            self._commit_pending()
        self._tool = tool
        self._crop_drag = None
        # При входе в режим кадрирования сразу показываем рамку на ВЕСЬ кадр —
        # как в Paint/Photoshop: тяните за стороны/углы, чтобы обрезать.
        if tool == self.TOOL_CROP and self.img_bgr is not None:
            h, w = self.img_bgr.shape[:2]
            self._crop_a = QPointF(0, 0)
            self._crop_b = QPointF(w, h)
            if self._crop_aspect:           # учитываем ранее выбранную пропорцию
                self._reshape_crop_to_aspect()
        else:
            self._crop_a = self._crop_b = None
        # Смена инструмента прерывает незавершённую фигуру.
        self._shape_drawing = False
        self._shape_start = self._shape_cur = None
        self.setCursor(Qt.CursorShape.ArrowCursor if tool == self.TOOL_MOVE
                       else Qt.CursorShape.CrossCursor)
        self._update_crop_buttons()
        self.update()

    def set_brush(self, diameter):
        self._brush = max(2, int(diameter))
        self.update()

    def set_brush_color(self, color):
        if color is not None and color.isValid():
            self._brush_color = QColor(color.red(), color.green(), color.blue())
            self.update()

    def brush_color(self):
        return QColor(self._brush_color)

    def set_shape_fill(self, on):
        self._shape_fill = bool(on)

    def set_text_font(self, font):
        if font is not None:
            self._text_font = QFont(font)
            # Размер задаём в пикселях изображения (см. _draw_text_at); если у
            # шрифта только pointSize — переносим в pixelSize по текущему DPI.
            if self._text_font.pixelSize() <= 0:
                ps = self._text_font.pointSizeF()
                self._text_font.setPixelSize(max(6, int(round(ps * 1.6))))

    def set_text_color(self, color):
        if color is not None and color.isValid():
            self._text_color = QColor(color.red(), color.green(), color.blue())

    def set_text_stroke(self, width, color=None):
        self._text_stroke_width = max(0.0, float(width))
        if color is not None and color.isValid():
            self._text_stroke_color = QColor(color.red(), color.green(), color.blue())

    # ── Фигуры и текст (рисуются прямо в изображение) ────────────────────────
    def _shape_pen(self):
        c = self._brush_color
        pen = QPen(QColor(c.red(), c.green(), c.blue()))
        pen.setWidthF(max(1.0, float(self._brush)))   # толщина = размер кисти (px изобр.)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _draw_shape(self, painter, a, b, tool):
        """Рисует фигуру tool из точки a в точку b (коорд. изображения) на
        переданном QPainter. Цвет/толщина — из кисти; заливка — _shape_fill."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = self._shape_pen()
        painter.setPen(pen)
        c = self._brush_color
        if self._shape_fill and tool in (self.TOOL_RECT, self.TOOL_ELLIPSE):
            painter.setBrush(QColor(c.red(), c.green(), c.blue()))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(a, b).normalized()
        if tool == self.TOOL_RECT:
            painter.drawRect(rect)
        elif tool == self.TOOL_ELLIPSE:
            painter.drawEllipse(rect)
        elif tool == self.TOOL_LINE:
            painter.drawLine(a, b)
        elif tool == self.TOOL_ARROW:
            painter.drawLine(a, b)
            self._draw_arrow_head(painter, a, b, pen.widthF())

    def _draw_arrow_head(self, painter, a, b, width):
        import math
        dx = b.x() - a.x(); dy = b.y() - a.y()
        length = math.hypot(dx, dy)
        if length < 1e-3:
            return
        ux, uy = dx / length, dy / length
        size = max(8.0, width * 3.2)        # длина «крыльев» наконечника
        ang = math.radians(26)
        ca, sa = math.cos(ang), math.sin(ang)
        # Два крыла, повёрнутые на ±ang от обратного направления стрелки.
        for s in (1, -1):
            rx = -ux * ca + s * (-uy) * sa
            ry = -uy * ca + s * (ux) * sa
            tip = QPointF(b.x() + rx * size, b.y() + ry * size)
            painter.drawLine(b, tip)

    def _make_pending_shape(self, a, b):
        """Делает из только что протянутой фигуры ПЛАВАЮЩИЙ объект (его можно
        перетащить мышью, пока не вжали — клик вне/смена инструмента/Enter)."""
        if self.img_bgr is None or a is None or b is None:
            return
        # Клик без движения фигуры не оставляет (как и раньше у _commit_shape).
        if (abs(a.x() - b.x()) + abs(a.y() - b.y())) < 1.5:
            return
        c = self._brush_color
        self._pending = {'kind': 'shape', 'tool': self._tool,
                         'a': QPointF(a), 'b': QPointF(b),
                         'color': QColor(c.red(), c.green(), c.blue()),
                         'thickness': float(self._brush), 'fill': self._shape_fill}
        self._pending_move = False
        self.statusChanged.emit("Фигура добавлена — перетащите, чтобы сдвинуть.")

    def _draw_text_at(self, ipt):
        """Спрашивает строку и кладёт её как ПЛАВАЮЩИЙ объект (можно перетащить),
        начиная от точки ipt (верх-левый угол текста, коорд. изображения). Текст
        вжигается позже — при клике вне него / смене инструмента / Enter / сейве."""
        if self.img_bgr is None:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Текст", "Введите текст (системный шрифт выбирается в панели):", "")
        if not ok or not text.strip():
            return
        c = self._text_color
        self._pending = {'kind': 'text', 'pos': QPointF(ipt), 'text': text,
                         'font': QFont(self._text_font),
                         'color': QColor(c.red(), c.green(), c.blue()),
                         'stroke_width': float(self._text_stroke_width),
                         'stroke_color': QColor(self._text_stroke_color)}
        self._pending_move = False
        self.update()
        self.textSelected.emit()
        self.statusChanged.emit("Текст добавлен — перетащите, чтобы сдвинуть, "
                                "или настройте цвет/шрифт/обводку в панели слева.")

    def edit_pending_text(self, ipt):
        """Двойной клик по плавающему тексту — меняем саму строку (остальные
        параметры: шрифт/цвет/обводка — остаются, редактируются в панели)."""
        if self._pending is None or self._pending.get('kind') != 'text':
            return
        if not self._object_bbox(self._pending).contains(ipt):
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Текст", "Измените текст:", self._pending['text'])
        if ok and text.strip():
            self._pending['text'] = text
            self.update()

    # ── Плавающие объекты (фигура/текст): перетаскивание и вжигание ──────────
    def _draw_object(self, painter, obj):
        """Рисует плавающий объект obj (фигура/текст/картинка) на painter, коорд. изобр.,
        своими сохранёнными параметрами."""
        if obj['kind'] == 'image':
            pix = obj['pix']
            w = float(obj.get('w', pix.width()))
            h = float(obj.get('h', pix.height()))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(
                QRectF(obj['pos'].x(), obj['pos'].y(), w, h), pix,
                QRectF(0, 0, pix.width(), pix.height()))
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if obj['kind'] == 'text':
            fm = QFontMetrics(obj['font'])
            x = obj['pos'].x()
            y = obj['pos'].y() + fm.ascent()
            stroke_w = float(obj.get('stroke_width', 0) or 0)
            if stroke_w > 0:
                # Обводка (как в Photoshop): путь текста, обвод + заливка —
                # даёт чёткий контур в любой толщине (в отличие от много-теневого трюка).
                path = QPainterPath()
                for i, line in enumerate(obj['text'].split("\n")):
                    path.addText(QPointF(x, y + i * fm.lineSpacing()), obj['font'], line)
                pen = QPen(obj.get('stroke_color', QColor(0, 0, 0)))
                pen.setWidthF(stroke_w)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.setBrush(obj['color'])
                painter.drawPath(path)
            else:
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                painter.setFont(obj['font'])
                painter.setPen(obj['color'])
                for i, line in enumerate(obj['text'].split("\n")):
                    painter.drawText(QPointF(x, y + i * fm.lineSpacing()), line)
            return
        c = obj['color']
        pen = QPen(c)
        pen.setWidthF(max(1.0, float(obj['thickness'])))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        tool = obj['tool']
        if obj.get('fill') and tool in (self.TOOL_RECT, self.TOOL_ELLIPSE):
            painter.setBrush(c)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        a, b = obj['a'], obj['b']
        rect = QRectF(a, b).normalized()
        if tool == self.TOOL_RECT:
            painter.drawRect(rect)
        elif tool == self.TOOL_ELLIPSE:
            painter.drawEllipse(rect)
        elif tool == self.TOOL_LINE:
            painter.drawLine(a, b)
        elif tool == self.TOOL_ARROW:
            painter.drawLine(a, b)
            self._draw_arrow_head(painter, a, b, pen.widthF())

    def _object_bbox(self, obj):
        """Габаритный прямоугольник объекта в коорд. изображения (для хит-теста и
        рамки выделения)."""
        if obj['kind'] == 'image':
            p = obj['pos']
            w = float(obj.get('w', obj['pix'].width()))
            h = float(obj.get('h', obj['pix'].height()))
            return QRectF(p.x(), p.y(), w, h)
        if obj['kind'] == 'text':
            fm = QFontMetrics(obj['font'])
            lines = obj['text'].split("\n")
            w = max((fm.horizontalAdvance(l) for l in lines), default=1)
            h = fm.lineSpacing() * max(1, len(lines))
            r = QRectF(obj['pos'].x(), obj['pos'].y(), max(1, w), max(1, h))
            sw = float(obj.get('stroke_width', 0) or 0) / 2.0
            return r.adjusted(-sw, -sw, sw, sw) if sw else r
        r = QRectF(obj['a'], obj['b']).normalized()
        t = float(obj.get('thickness', 1)) / 2.0 + 4.0   # запас под толщину/наконечник
        return r.adjusted(-t, -t, t, t)

    def _translate_pending(self, d):
        """Сдвигает плавающий объект на вектор d (коорд. изображения)."""
        if self._pending is None:
            return
        if self._pending['kind'] in ('text', 'image'):
            self._pending['pos'] = self._pending['pos'] + d
        else:
            self._pending['a'] = self._pending['a'] + d
            self._pending['b'] = self._pending['b'] + d

    def _pending_resizable(self) -> bool:
        """Можно ли менять размер плавающего объекта тяганием ручек (только картинка)."""
        return self._pending is not None and self._pending.get('kind') == 'image'

    def _pending_handle_at(self, wpt):
        """Какую ручку рамки выделения наложенного изображения задевает курсор
        (коорд. виджета). Возвращает 'tl','tr','bl','br','t','b','l','r','move' или
        None (мимо). Ручки рисуются/ловятся только для картинки."""
        if not self._pending_resizable():
            return None
        bb = self._object_bbox(self._pending)
        tl = self._i2w(bb.topLeft()); br = self._i2w(bb.bottomRight())
        r = QRectF(tl, br).normalized()
        tol = 9.0
        mx, my = wpt.x(), wpt.y()
        if not (r.left() - tol <= mx <= r.right() + tol
                and r.top() - tol <= my <= r.bottom() + tol):
            return None
        near_l = abs(mx - r.left()) <= tol
        near_r = abs(mx - r.right()) <= tol
        near_t = abs(my - r.top()) <= tol
        near_b = abs(my - r.bottom()) <= tol
        if near_t and near_l: return 'tl'
        if near_t and near_r: return 'tr'
        if near_b and near_l: return 'bl'
        if near_b and near_r: return 'br'
        if near_t: return 't'
        if near_b: return 'b'
        if near_l: return 'l'
        if near_r: return 'r'
        if r.left() < mx < r.right() and r.top() < my < r.bottom():
            return 'move'
        return None

    def _resize_pending(self, ipt, keep_aspect=False):
        """Меняет размер наложенного изображения тяганием ручки self._pending_resize.
        ipt — позиция мыши в коорд. изображения. keep_aspect (Shift) — сохранять
        пропорции (для угловых ручек)."""
        if (self._pending is None or self._pending_resize is None
                or self._pending_rs_rect0 is None):
            return
        d = self._pending_resize
        r0 = self._pending_rs_rect0
        l, t, r, b = r0.left(), r0.top(), r0.right(), r0.bottom()
        minsz = 12.0
        x, y = ipt.x(), ipt.y()
        if 'l' in d: l = min(x, r - minsz)
        if 'r' in d: r = max(x, l + minsz)
        if 't' in d: t = min(y, b - minsz)
        if 'b' in d: b = max(y, t + minsz)
        new_w = r - l; new_h = b - t
        # Пропорции (Shift) для угловых ручек: подгоняем по доминирующей оси,
        # удерживая противоположный угол на месте.
        if keep_aspect and d in ('tl', 'tr', 'bl', 'br') and r0.width() > 0 and r0.height() > 0:
            ar = r0.width() / r0.height()
            if new_w / max(1e-6, new_h) > ar:
                new_w = new_h * ar
            else:
                new_h = new_w / ar
            if 'l' in d: l = r - new_w
            else: r = l + new_w
            if 't' in d: t = b - new_h
            else: b = t + new_h
        self._pending['pos'] = QPointF(l, t)
        self._pending['w'] = max(minsz, new_w)
        self._pending['h'] = max(minsz, new_h)

    def _bake_object(self, obj):
        """Вжигает объект в изображение (с записью в историю отмены)."""
        if self.img_bgr is None:
            return
        self._push_history()
        img = np_bgr_to_qimage(self.img_bgr).convertToFormat(
            QtGuiImage.Format.Format_RGB888)
        p = QPainter(img)
        self._draw_object(p, obj)
        p.end()
        self.img_bgr = qimage_to_np_bgr(img)
        self._rebuild_base()

    def _commit_pending(self):
        """Закрепляет (вжигает) плавающий объект в картинку, если он есть."""
        if self._pending is None:
            return
        obj = self._pending
        self._pending = None
        self._pending_move = False
        self._pending_resize = None
        self._pending_rs_rect0 = None
        # Вырожденную линию/стрелку (клик без движения) не вжигаем.
        if obj['kind'] == 'shape' and obj['tool'] in (self.TOOL_LINE, self.TOOL_ARROW):
            a, b = obj['a'], obj['b']
            if (abs(a.x() - b.x()) + abs(a.y() - b.y())) < 1.5:
                self.update()
                return
        self._bake_object(obj)
        if obj['kind'] == 'text':
            msg = "Текст вжат."
        elif obj['kind'] == 'image':
            msg = "Изображение вжато."
        else:
            msg = "Фигура вжата."
        self.statusChanged.emit(msg)
        self.update()

    def commit_pending(self):
        """Публичный вызов: вкладка вжигает плавающий объект перед сохранением/
        запуском нейросети, чтобы он попал в результат."""
        self._commit_pending()

    def cancel_pending(self):
        """Убирает плавающий объект без вжигания (Esc)."""
        if self._pending is None:
            return
        self._pending = None
        self._pending_move = False
        self._pending_resize = None
        self._pending_rs_rect0 = None
        self.update()
        self.statusChanged.emit("Объект отменён.")

    def _set_alt(self, on):
        """Включает/выключает режим «временной пипетки» (Alt при активной кисти):
        курсор и подсказка меняются, кольцо-курсор кисти не рисуется."""
        on = bool(on) and self._tool == self.TOOL_BRUSH and self.img_bgr is not None
        if on != self._alt:
            self._alt = on
            self.setCursor(eyedropper_cursor() if on
                           else Qt.CursorShape.CrossCursor)
            self.update()

    def _pick_color_at(self, ipt):
        """Берёт цвет пикселя изображения под точкой ipt (коорд. изображения) —
        Alt-пипетка как в Photoshop: цвет кисти становится взятым."""
        if self.img_bgr is None:
            return
        h, w = self.img_bgr.shape[:2]
        x = int(min(max(ipt.x(), 0), w - 1))
        y = int(min(max(ipt.y(), 0), h - 1))
        px = self.img_bgr[y, x]
        col = QColor(int(px[2]), int(px[1]), int(px[0]))   # BGR → RGB
        self.set_brush_color(col)
        self.colorPicked.emit(col)
        self.statusChanged.emit(f"Цвет взят пипеткой: {col.name().upper()}")

    def clear_mask(self):
        self._commit_pending()
        if self._overlay is None:
            return
        self._push_history()
        self._overlay.fill(0)
        self._has_strokes = False
        self.update()
        self.statusChanged.emit("Маска очищена.")

    def clear_canvas(self):
        """Полностью очищает холст. Состояние «до» кладём в историю, чтобы Ctrl+Z
        вернул очищенную картинку (раньше история стиралась — вернуть было нельзя)."""
        self._commit_pending()
        had_image = self.img_bgr is not None
        if had_image:
            self._push_history()        # снимок «до очистки» для Ctrl+Z
        self.img_bgr = None
        self._overlay = None
        self._paint_layer = None
        self._alpha = None
        self._has_paint = False
        self._base_pix = None
        self._has_strokes = False
        self._pending = None
        self._pending_move = False
        self._crop_a = self._crop_b = None
        self._crop_drag = None
        self._user_zoomed = False
        self._update_crop_buttons()
        self.update()
        self.statusChanged.emit("Холст очищен." +
                                (" Ctrl+Z — вернуть." if had_image else ""))

    def composited_bgr(self):
        """То, что видит пользователь: фото с вжатыми мазками «Кисти» (слой краски).
        Маску удаления (красную) НЕ вжигаем — это служебное выделение. Без краски
        возвращает само изображение. Не мутирует состояние (для сохранения)."""
        if self.img_bgr is None:
            return None
        if not self._has_paint or self._paint_layer is None:
            return self.img_bgr
        img = np_bgr_to_qimage(self.img_bgr).convertToFormat(
            QtGuiImage.Format.Format_RGB888)
        p = QPainter(img)
        p.drawImage(0, 0, self._paint_layer)
        p.end()
        return qimage_to_np_bgr(img)

    def bake_paint(self):
        """Вжигает слой краски в img_bgr и очищает слой. Зовём перед удалением
        объекта/кадрированием, чтобы мазки попали в результат. Историю НЕ трогаем —
        её снимает вызывающий код (apply_crop/_run_inpaint)."""
        if self.img_bgr is None or self._paint_layer is None or not self._has_paint:
            return
        # Если фон удалён — закрашенные кистью пиксели становятся непрозрачными
        # (рисуем «поверх пустоты»), иначе мазок не был бы виден.
        if self._alpha is not None:
            pa = self._layer_alpha(self._paint_layer)
            self._alpha = _np.maximum(self._alpha,
                                      (pa > 10).astype(_np.uint8) * 255)
        self.img_bgr = self.composited_bgr()
        self._paint_layer.fill(0)
        self._has_paint = False
        self._rebuild_base()

    def fit(self):
        self._user_zoomed = False
        self._fit()
        self._update_crop_buttons()
        self.update()

    # ── Кадрирование ────────────────────────────────────────────────────────
    def has_crop(self) -> bool:
        return self._crop_a is not None and self._crop_b is not None

    def _update_crop_buttons(self):
        """Показывает/прячет и позиционирует кнопки «Применить/Отмена» у рамки
        кадрирования (как плавающая панель Photoshop). Зовётся при любом
        изменении рамки/зума/размера холста."""
        show = (self._tool == self.TOOL_CROP and self.has_crop()
                and self.img_bgr is not None)
        if not show:
            if self._crop_apply_btn.isVisible():
                self._crop_apply_btn.setVisible(False)
                self._crop_cancel_btn.setVisible(False)
            if self._crop_aspect_combo.isVisible():
                self._crop_aspect_combo.setVisible(False)
            return
        r = self._crop_rect_w()
        # Селектор пропорций — над верх-левым углом рамки (как панель кадрирования
        # в Photoshop); если сверху не влезает — внутрь рамки у верхнего края.
        ac = self._crop_aspect_combo
        ach = ac.sizeHint().height()
        acw = max(ac.sizeHint().width(), 96)
        ax = int(max(2, min(r.left(), self.width() - acw - 2)))
        ay = int(r.top() - ach - 6)
        if ay < 2:
            ay = int(r.top() + 6)
        ay = max(2, min(ay, self.height() - ach - 2))
        ac.setGeometry(ax, ay, acw, ach)
        ac.setVisible(True)
        ac.raise_()
        aw = self._crop_apply_btn.sizeHint()
        cw = self._crop_cancel_btn.sizeHint()
        gap = 6
        h = max(aw.height(), cw.height())
        total = aw.width() + cw.width() + gap
        # Прижимаем к правому-нижнему углу рамки, под ней; если снизу не влезает —
        # переносим внутрь рамки над её нижним краем. Затем зажимаем в холст.
        x = int(r.right() - total)
        y = int(r.bottom() + gap)
        if y + h > self.height():
            y = int(r.bottom() - h - gap)
        x = max(2, min(x, self.width() - total - 2))
        y = max(2, min(y, self.height() - h - 2))
        self._crop_apply_btn.setGeometry(x, y, aw.width(), h)
        self._crop_cancel_btn.setGeometry(x + aw.width() + gap, y, cw.width(), h)
        self._crop_apply_btn.setVisible(True)
        self._crop_cancel_btn.setVisible(True)
        self._crop_apply_btn.raise_()
        self._crop_cancel_btn.raise_()

    def apply_crop(self):
        self._commit_pending()
        if not self.has_crop() or self.img_bgr is None:
            return False
        h, w = self.img_bgr.shape[:2]
        x0 = int(max(0, min(self._crop_a.x(), self._crop_b.x())))
        y0 = int(max(0, min(self._crop_a.y(), self._crop_b.y())))
        x1 = int(min(w, max(self._crop_a.x(), self._crop_b.x())))
        y1 = int(min(h, max(self._crop_a.y(), self._crop_b.y())))
        if x1 - x0 < 4 or y1 - y0 < 4:
            self.statusChanged.emit("Слишком маленькая область кадрирования.")
            return False
        self._push_history()
        # Вжигаем мазки кисти перед обрезкой, чтобы они попали в результат.
        self.bake_paint()
        self.img_bgr = _np.ascontiguousarray(self.img_bgr[y0:y1, x0:x1])
        if self._alpha is not None:                  # кадрируем и маску прозрачности
            self._alpha = _np.ascontiguousarray(self._alpha[y0:y1, x0:x1])
        new_ov = QtGuiImage(x1 - x0, y1 - y0,
                            QtGuiImage.Format.Format_ARGB32_Premultiplied)
        new_ov.fill(0)
        p = QPainter(new_ov)
        p.drawImage(0, 0, self._overlay, x0, y0, x1 - x0, y1 - y0)
        p.end()
        self._overlay = new_ov
        # Слой краски уже вжат → пересоздаём пустым под новый размер.
        self._paint_layer = QtGuiImage(x1 - x0, y1 - y0,
                                       QtGuiImage.Format.Format_ARGB32_Premultiplied)
        self._paint_layer.fill(0)
        self._has_paint = False
        self._recompute_strokes_flag()
        self._crop_a = self._crop_b = None
        self._rebuild_base()
        self._user_zoomed = False
        self._fit()
        self._update_crop_buttons()
        self.update()
        self.statusChanged.emit(f"Кадрировано → {x1 - x0}×{y1 - y0}.")
        return True

    def cancel_crop(self):
        self._crop_a = self._crop_b = None
        self._crop_drag = None
        self._update_crop_buttons()
        self.update()

    def _crop_rect_w(self):
        """Текущая рамка кадрирования в ЭКРАННЫХ координатах (нормализованная)."""
        a = self._i2w(self._crop_a)
        b = self._i2w(self._crop_b)
        return QRectF(a, b).normalized()

    def _crop_handle_at(self, wpt):
        """Какую «ручку» рамки задевает курсор (коорд. виджета). Возвращает один
        из 'tl','tr','bl','br','t','b','l','r','move' или None."""
        if not self.has_crop():
            return None
        r = self._crop_rect_w()
        tol = 10.0
        mx, my = wpt.x(), wpt.y()
        if not (r.left() - tol <= mx <= r.right() + tol
                and r.top() - tol <= my <= r.bottom() + tol):
            return None
        near_l = abs(mx - r.left()) <= tol
        near_r = abs(mx - r.right()) <= tol
        near_t = abs(my - r.top()) <= tol
        near_b = abs(my - r.bottom()) <= tol
        if near_t and near_l: return 'tl'
        if near_t and near_r: return 'tr'
        if near_b and near_l: return 'bl'
        if near_b and near_r: return 'br'
        if near_t: return 't'
        if near_b: return 'b'
        if near_l: return 'l'
        if near_r: return 'r'
        if r.left() < mx < r.right() and r.top() < my < r.bottom():
            return 'move'
        return None

    @staticmethod
    def _crop_cursor(handle):
        cur = {
            'tl': Qt.CursorShape.SizeFDiagCursor, 'br': Qt.CursorShape.SizeFDiagCursor,
            'tr': Qt.CursorShape.SizeBDiagCursor, 'bl': Qt.CursorShape.SizeBDiagCursor,
            't': Qt.CursorShape.SizeVerCursor,  'b': Qt.CursorShape.SizeVerCursor,
            'l': Qt.CursorShape.SizeHorCursor,  'r': Qt.CursorShape.SizeHorCursor,
            'move': Qt.CursorShape.SizeAllCursor,
        }
        return cur.get(handle, Qt.CursorShape.CrossCursor)

    def _drag_crop(self, ipt):
        """Двигает активную ручку рамки. ipt — позиция мыши в коорд. изображения."""
        h, w = self.img_bgr.shape[:2]
        d = self._crop_drag
        a, b = self._crop_start
        l, t = min(a.x(), b.x()), min(a.y(), b.y())
        r, bo = max(a.x(), b.x()), max(a.y(), b.y())
        minsz = 8.0
        if d == 'move':
            bw, bh = r - l, bo - t
            dx = ipt.x() - self._crop_anchor.x()
            dy = ipt.y() - self._crop_anchor.y()
            nl = min(max(l + dx, 0.0), w - bw)
            nt = min(max(t + dy, 0.0), h - bh)
            self._crop_a = QPointF(nl, nt)
            self._crop_b = QPointF(nl + bw, nt + bh)
            return
        x = min(max(ipt.x(), 0.0), float(w))
        y = min(max(ipt.y(), 0.0), float(h))
        if 'l' in d: l = min(x, r - minsz)
        if 'r' in d: r = max(x, l + minsz)
        if 't' in d: t = min(y, bo - minsz)
        if 'b' in d: bo = max(y, t + minsz)
        if self._crop_aspect:
            l, t, r, bo = self._apply_aspect(d, l, t, r, bo, w, h)
        self._crop_a = QPointF(l, t)
        self._crop_b = QPointF(r, bo)

    # ── Пропорции рамки кадрирования (1:1 / 4:3 / 16:9 … на холсте) ───────────
    def _on_crop_aspect_changed(self, idx):
        if idx < 0 or idx >= len(self._crop_aspect_items):
            return
        _, val = self._crop_aspect_items[idx]
        if val is None:
            self._crop_aspect = None
        elif val == 'orig':
            if self.img_bgr is not None:
                h, w = self.img_bgr.shape[:2]
                self._crop_aspect = (w / h) if h else None
            else:
                self._crop_aspect = None
        else:
            self._crop_aspect = float(val)
        # Сразу подгоняем текущую рамку под выбранную пропорцию.
        if self._crop_aspect and self.has_crop():
            self._reshape_crop_to_aspect()
        self._update_crop_buttons()
        self.update()

    def _reshape_crop_to_aspect(self):
        """Подгоняет текущую рамку под self._crop_aspect, сохраняя центр и вписывая
        в границы изображения."""
        if self.img_bgr is None or not self.has_crop():
            return
        h, w = self.img_bgr.shape[:2]
        ratio = self._crop_aspect
        l = min(self._crop_a.x(), self._crop_b.x())
        r = max(self._crop_a.x(), self._crop_b.x())
        t = min(self._crop_a.y(), self._crop_b.y())
        bo = max(self._crop_a.y(), self._crop_b.y())
        cw, ch = r - l, bo - t
        cx, cy = (l + r) / 2.0, (t + bo) / 2.0
        if cw / max(ch, 1e-6) > ratio:
            cw = ch * ratio
        else:
            ch = cw / ratio
        if cw > w:
            cw = w; ch = cw / ratio
        if ch > h:
            ch = h; cw = ch * ratio
        l, r = cx - cw / 2.0, cx + cw / 2.0
        t, bo = cy - ch / 2.0, cy + ch / 2.0
        if l < 0: r -= l; l = 0.0
        if t < 0: bo -= t; t = 0.0
        if r > w: l -= (r - w); r = float(w)
        if bo > h: t -= (bo - h); bo = float(h)
        self._crop_a = QPointF(l, t)
        self._crop_b = QPointF(r, bo)

    def _apply_aspect(self, d, l, t, r, bo, w, h):
        """Возвращает рамку с зафиксированной пропорцией self._crop_aspect под
        активную ручку d (угол — якорь в противоположном углу; сторона — растим
        перпендикуляр симметрично от центра)."""
        ratio = self._crop_aspect
        minsz = 8.0
        if d in ('tl', 'tr', 'bl', 'br'):
            ax = r if 'l' in d else l            # якорь — противоположная сторона
            ay = bo if 't' in d else t
            sx = -1.0 if 'l' in d else 1.0       # направление растяжения от якоря
            sy = -1.0 if 't' in d else 1.0
            width = max(minsz, abs((l if 'l' in d else r) - ax))
            height = max(minsz, abs((t if 't' in d else bo) - ay))
            if width / height > ratio:
                height = width / ratio
            else:
                width = height * ratio
            avail_w = ax if sx < 0 else (w - ax)
            avail_h = ay if sy < 0 else (h - ay)
            if width > avail_w:
                width = avail_w; height = width / ratio
            if height > avail_h:
                height = avail_h; width = height * ratio
            nx = ax + sx * width
            ny = ay + sy * height
            l, r = sorted((ax, nx))
            t, bo = sorted((ay, ny))
        elif 'l' in d or 'r' in d:
            width = max(minsz, r - l)
            height = min(float(h), width / ratio)
            width = height * ratio
            cy = (t + bo) / 2.0
            t, bo = cy - height / 2.0, cy + height / 2.0
            if t < 0: bo -= t; t = 0.0
            if bo > h: t -= (bo - h); bo = float(h)
        else:
            height = max(minsz, bo - t)
            width = min(float(w), height * ratio)
            height = width / ratio
            cx = (l + r) / 2.0
            l, r = cx - width / 2.0, cx + width / 2.0
            if l < 0: r -= l; l = 0.0
            if r > w: l -= (r - w); r = float(w)
        return l, t, r, bo

    # ── Маска для инференса / применение результата ──────────────────────────
    def _mask_alpha(self):
        """Альфа-канал оверлея как numpy (H,W) uint8."""
        a = self._overlay.convertToFormat(QtGuiImage.Format.Format_ARGB32)
        w, h = a.width(), a.height()
        bpl = a.bytesPerLine()
        ptr = a.constBits(); ptr.setsize(bpl * h)
        buf = _np.frombuffer(ptr, _np.uint8).reshape(h, bpl)
        bgra = buf[:, :w * 4].reshape(h, w, 4)
        return _np.ascontiguousarray(bgra[..., 3])

    def get_mask(self):
        """Бинарная маска (H,W) uint8 {0,255}: 255 — где закрашено пользователем."""
        return (self._mask_alpha() > 10).astype(_np.uint8) * 255

    def apply_result(self, img_bgr):
        """Подставляет результат инференса и сбрасывает маску."""
        self._push_history()
        self.img_bgr = _np.ascontiguousarray(img_bgr)
        self._overlay.fill(0)
        self._has_strokes = False
        self._rebuild_base()
        self.update()

    # ── Преобразования координат ─────────────────────────────────────────────
    def _fit(self):
        if self.img_bgr is None:
            return
        aw, ah = self.width(), self.height()
        ih, iw = self.img_bgr.shape[:2]
        if iw <= 0 or ih <= 0:
            return
        s = min(aw / iw, ah / ih)
        self._scale = s if s > 0 else 1.0
        self._off = QPointF((aw - iw * self._scale) / 2.0,
                            (ah - ih * self._scale) / 2.0)

    def _w2i(self, pt):
        return QPointF((pt.x() - self._off.x()) / self._scale,
                       (pt.y() - self._off.y()) / self._scale)

    def _i2w(self, pt):
        return QPointF(self._off.x() + pt.x() * self._scale,
                       self._off.y() + pt.y() * self._scale)

    def _img_rect_w(self):
        ih, iw = self.img_bgr.shape[:2]
        return QRectF(self._off.x(), self._off.y(), iw * self._scale, ih * self._scale)

    # ── Скроллбары при сильном приближении ───────────────────────────────────
    def _content_size(self):
        ih, iw = self.img_bgr.shape[:2]
        return iw * self._scale, ih * self._scale

    def _clamp_off(self):
        """Зажимает смещение по той оси, где картинка больше холста, чтобы её
        нельзя было увести за край (как при прокрутке). Где картинка меньше —
        смещение не трогаем (свободное панорамирование/центрирование)."""
        if self.img_bgr is None:
            return
        cw, ch = self._content_size()
        W, H = self.width(), self.height()
        if cw > W:
            self._off.setX(min(0.0, max(self._off.x(), W - cw)))
        if ch > H:
            self._off.setY(min(0.0, max(self._off.y(), H - ch)))

    def _sync_scrollbars(self):
        """Показывает/прячет и настраивает скроллбары под текущий зум/смещение."""
        if self.img_bgr is None:
            self._hbar.setVisible(False)
            self._vbar.setVisible(False)
            return
        self._syncing_bars = True
        try:
            cw, ch = self._content_size()
            W, H = self.width(), self.height()
            t = self._SB_THICK
            # Бар по одной оси «съедает» место у встречной — учитываем взаимно.
            need_h = cw > W
            need_v = ch > H
            need_h = cw > (W - (t if need_v else 0))
            need_v = ch > (H - (t if need_h else 0))
            vw = W - (t if need_v else 0)
            vh = H - (t if need_h else 0)
            self._clamp_off()
            if need_h:
                self._hbar.setGeometry(0, H - t, vw, t)
                self._hbar.setPageStep(max(1, int(vw)))
                self._hbar.setSingleStep(max(1, int(vw * 0.1)))
                self._hbar.setRange(0, max(0, int(round(cw - vw))))
                self._hbar.setValue(int(round(-self._off.x())))
                self._hbar.setVisible(True)
                self._hbar.raise_()
            else:
                self._hbar.setVisible(False)
            if need_v:
                self._vbar.setGeometry(W - t, 0, t, vh)
                self._vbar.setPageStep(max(1, int(vh)))
                self._vbar.setSingleStep(max(1, int(vh * 0.1)))
                self._vbar.setRange(0, max(0, int(round(ch - vh))))
                self._vbar.setValue(int(round(-self._off.y())))
                self._vbar.setVisible(True)
                self._vbar.raise_()
            else:
                self._vbar.setVisible(False)
        finally:
            self._syncing_bars = False

    def _on_hbar(self, v):
        if self._syncing_bars or self.img_bgr is None:
            return
        self._off.setX(-float(v))
        self._update_crop_buttons()
        self.update()

    def _on_vbar(self, v):
        if self._syncing_bars or self.img_bgr is None:
            return
        self._off.setY(-float(v))
        self._update_crop_buttons()
        self.update()

    # ── Рисование штриха ─────────────────────────────────────────────────────
    def _paint_to(self, img_pt):
        # «Кисть» рисует по слою краски (поверх фото), «Ластик» стирает ИМЕННО
        # этот слой (мазки кисти), а не маску удаления. TOOL_MASK — красная маска
        # удаления в отдельном оверлее.
        if self._tool == self.TOOL_BRUSH:
            self._paint_image_to(img_pt, erase=False)
            return
        if self._tool == self.TOOL_ERASE:
            self._paint_image_to(img_pt, erase=True)
            return
        # TOOL_MASK — красная маска удаления (вход для нейросети).
        p = QPainter(self._overlay)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = max(1.0, self._brush / self._scale)
        col = QColor(235, 45, 45, 150)
        a = self._last_img_pt if self._last_img_pt is not None else img_pt
        if a == img_pt:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(img_pt, width / 2.0, width / 2.0)
        else:
            pen = QPen(col)
            pen.setWidthF(width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(a, img_pt)
        p.end()
        self._last_img_pt = img_pt
        self._has_strokes = True

    def _paint_image_to(self, img_pt, erase=False):
        """«Кисть» (erase=False) кладёт непрозрачные мазки в слой краски
        _paint_layer поверх фото; «Ластик» (erase=True) стирает их из этого слоя
        (CompositionMode_Clear). Слой НЕ вживается в img_bgr сразу — только перед
        удалением объекта/кадрированием/сохранением (bake_paint), поэтому мазки
        можно свободно стирать, как в Photoshop."""
        if self._paint_layer is None:
            return
        p = QPainter(self._paint_layer)
        if erase:
            # Жёсткий край без сглаживания и чуть шире штриха — иначе остаётся
            # полупрозрачная «бахрома» и кажется, что ластик не дотирает.
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            width = max(1.0, (self._brush + 2) / self._scale)
            col = QColor(0, 0, 0, 255)
        else:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            width = max(1.0, self._brush / self._scale)
            c = self._brush_color
            col = QColor(c.red(), c.green(), c.blue())   # непрозрачная краска
        a = self._last_img_pt if self._last_img_pt is not None else img_pt
        if a == img_pt:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            r = width / 2.0 + (1.5 if erase else 0.0)
            p.drawEllipse(img_pt, r, r)
        else:
            pen = QPen(col)
            pen.setWidthF(width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(a, img_pt)
        p.end()
        self._last_img_pt = img_pt
        if not erase:
            self._has_paint = True

    # ── События мыши/колеса/клавиатуры ───────────────────────────────────────
    def mousePressEvent(self, ev):
        if self.img_bgr is None:
            return
        if ev.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = ev.position()
            self._off_start = QPointF(self._off)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ipt = self._w2i(ev.position())
        # Плавающий объект (фигура/текст/картинка, ещё не вжатый): сначала ручки
        # размера (как free-transform в Photoshop), затем клик ВНУТРИ — перенос,
        # клик ВНЕ — закрепить (вжать). Геометрия от вжигания не меняется.
        if self._pending is not None:
            handle = self._pending_handle_at(ev.position())
            if handle in ('tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'):
                self._pending_resize = handle
                self._pending_rs_rect0 = self._object_bbox(self._pending)
                self.setCursor(self._crop_cursor(handle))
                return
            if self._object_bbox(self._pending).contains(ipt):
                self._pending_move = True
                self._pending_anchor = ipt
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                if self._pending.get('kind') == 'text':
                    self.textSelected.emit()
                return
            # Клик ВНЕ рамки — закрепляем слой (снимает выделение, как клик мимо
            # рамки free-transform в Photoshop). Дальше клик НЕ продолжаем в кисть
            # и т.п., чтобы не рисовать тем же кликом, которым «применили» слой.
            self._commit_pending()
            return
        if self._tool == self.TOOL_MOVE:
            # Нет плавающего объекта под курсором → «Курсор» работает как рука в
            # Photoshop: тянем — двигаем «камеру». Только при приближении (когда
            # картинка больше холста), иначе на вписанной картинке не сдвигаем.
            cw, ch = self._content_size()
            if cw > self.width() or ch > self.height():
                self._panning = True
                self._pan_start = ev.position()
                self._off_start = QPointF(self._off)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        # Alt + кисть = пипетка: берём цвет из изображения, не рисуя мазок.
        if (self._tool == self.TOOL_BRUSH
                and (ev.modifiers() & Qt.KeyboardModifier.AltModifier)):
            self._pick_color_at(ipt)
            return
        if self._tool == self.TOOL_CROP:
            if not self.has_crop():
                h, w = self.img_bgr.shape[:2]
                self._crop_a = QPointF(0, 0); self._crop_b = QPointF(w, h)
                if self._crop_aspect:
                    self._reshape_crop_to_aspect()
            handle = self._crop_handle_at(ev.position())
            # Клик мимо рамки — игнорируем (рамка остаётся как есть).
            self._crop_drag = handle
            self._crop_anchor = ipt
            self._crop_start = (QPointF(self._crop_a), QPointF(self._crop_b))
            self.update()
            return
        if self._tool == self.TOOL_TEXT:
            # Текст: клик задаёт верх-левый угол, далее спрашиваем строку.
            self._draw_text_at(ipt)
            return
        if self._tool in self._SHAPE_TOOLS:
            # Фигура: начинаем тянуть от точки клика.
            self._shape_start = ipt
            self._shape_cur = ipt
            self._shape_drawing = True
            self.update()
            return
        # Кисть/ластик — новый штрих: фиксируем состояние для отмены.
        self._push_history()
        self._painting = True
        self._last_img_pt = None
        self._paint_to(ipt)
        self.update()

    def mouseMoveEvent(self, ev):
        self._mouse_w = ev.position()
        if self._panning and self._pan_start is not None:
            d = ev.position() - self._pan_start
            self._off = self._off_start + d
            self._clamp_off()
            self._update_crop_buttons()
            self.update()
            return
        if self.img_bgr is None:
            self.update()
            return
        # Изменение размера наложенного изображения тяганием ручки.
        if self._pending_resize and (ev.buttons() & Qt.MouseButton.LeftButton):
            keep = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._resize_pending(self._w2i(ev.position()), keep_aspect=keep)
            self.update()
            return
        # Перетаскивание плавающего объекта (фигура/текст/картинка).
        if self._pending_move and (ev.buttons() & Qt.MouseButton.LeftButton):
            ipt = self._w2i(ev.position())
            if self._pending_anchor is not None:
                self._translate_pending(ipt - self._pending_anchor)
            self._pending_anchor = ipt
            self.update()
            return
        if self._shape_drawing:
            self._shape_cur = self._w2i(ev.position())
            self.update()
            return
        # Наведение на плавающий объект: курсор-стрелки на ручках размера, «лапа»
        # внутри. Работает в любом инструменте, пока есть незакреплённый объект
        # (а в TOOL_MOVE — ещё и стрелка вне объекта).
        if self._pending is not None and not self._pending_move:
            handle = self._pending_handle_at(ev.position())
            if handle in ('tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'):
                self.setCursor(self._crop_cursor(handle))
                self.update()
                return
            if handle == 'move':
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                self.update()
                return
            if self._tool == self.TOOL_MOVE:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                self.update()
                return
        if self._tool == self.TOOL_MOVE:
            # Пустое место под «Курсором» — рука (готов панорамировать, как в Photoshop).
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()
            return
        # Пока не рисуем — отслеживаем Alt для подсказки «пипетка» у кисти.
        if not self._painting:
            self._set_alt(bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier))
        if self._painting:
            self._paint_to(self._w2i(ev.position()))
            self.update()
            return
        if self._tool == self.TOOL_CROP:
            if self._crop_drag and (ev.buttons() & Qt.MouseButton.LeftButton):
                self._drag_crop(self._w2i(ev.position()))
                self._update_crop_buttons()
            else:
                # Подсказка курсором: над какой ручкой находимся.
                self.setCursor(self._crop_cursor(
                    self._crop_handle_at(ev.position())))
        self.update()

    def mouseDoubleClickEvent(self, ev):
        if (ev.button() == Qt.MouseButton.LeftButton and self._pending is not None
                and self._pending.get('kind') == 'text'):
            self.edit_pending_text(self._w2i(ev.position()))
            return
        super().mouseDoubleClickEvent(ev)

    def mouseReleaseEvent(self, ev):
        _default_cursor = (Qt.CursorShape.OpenHandCursor if self._tool == self.TOOL_MOVE
                           else Qt.CursorShape.CrossCursor)
        # Любое панорамирование (средняя кнопка ИЛИ «Курсор»-рука) завершаем здесь.
        if self._panning:
            self._panning = False
            self.setCursor(_default_cursor)
            return
        # Завершили изменение размера наложенного изображения.
        if self._pending_resize and ev.button() == Qt.MouseButton.LeftButton:
            self._pending_resize = None
            self._pending_rs_rect0 = None
            self.setCursor(_default_cursor)
            self.update()
            return
        # Завершили перетаскивание плавающего объекта — он остаётся выделенным.
        if self._pending_move and ev.button() == Qt.MouseButton.LeftButton:
            self._pending_move = False
            self._pending_anchor = None
            self.setCursor(_default_cursor)
            self.update()
            return
        if self._shape_drawing and ev.button() == Qt.MouseButton.LeftButton:
            self._shape_cur = self._w2i(ev.position())
            a, b = self._shape_start, self._shape_cur
            self._shape_drawing = False
            self._shape_start = self._shape_cur = None
            self._make_pending_shape(a, b)
            self.update()
            return
        if self._painting:
            self._painting = False
            self._last_img_pt = None
            was_mask = self._tool == self.TOOL_MASK
            # Ластик стирает мазки кисти (слой краски) — пересчитываем флаг краски.
            if self._tool == self.TOOL_ERASE:
                self._recompute_paint_flag()
            # Кисть/ластик могли изменить _has_paint — сигналим вкладке пере-включить
            # кнопки (кнопка «Ластик» неактивна, пока нечего стирать, см. _refresh_enabled).
            if self._tool in (self.TOOL_BRUSH, self.TOOL_ERASE):
                self.imageChanged.emit()
            # Завершено выделение для удаления — сигналим вкладке: убрать закрашенное
            # (как Photoshop Spot Healing Brush: пометил — сразу убралось).
            if was_mask and self._has_strokes:
                self.strokeFinished.emit()
        if self._crop_drag:
            self._crop_drag = None

    def leaveEvent(self, ev):
        self._mouse_w = None
        self.update()
        super().leaveEvent(ev)

    def wheelEvent(self, ev):
        if self.img_bgr is None:
            return
        # Зум мышью — забираем фокус холсту, чтобы WASD/стрелки сразу панорамировали.
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        dy = ev.angleDelta().y()
        if dy == 0:
            return
        factor = 1.2 if dy > 0 else 1 / 1.2
        old = self._scale
        new = max(0.02, min(40.0, old * factor))
        if new == old:
            return
        cur = ev.position()
        # Зум вокруг курсора: точка под курсором остаётся на месте.
        self._off = QPointF(cur.x() - (cur.x() - self._off.x()) * (new / old),
                            cur.y() - (cur.y() - self._off.y()) * (new / old))
        self._scale = new
        self._user_zoomed = True
        self._clamp_off()
        self._update_crop_buttons()
        self.update()

    def _pan_by(self, dx, dy):
        """Сдвигает «камеру» (видимую область) на dx,dy экранных px. Двигаем только
        по оси, где картинка больше холста (при приближении), иначе не даём ей
        бесцельно ездить по пустому полю."""
        if self.img_bgr is None:
            return
        cw, ch = self._content_size()
        if dx and cw <= self.width():
            dx = 0
        if dy and ch <= self.height():
            dy = 0
        if not dx and not dy:
            return
        self._off = QPointF(self._off.x() + dx, self._off.y() + dy)
        self._user_zoomed = True
        self._clamp_off()
        self._update_crop_buttons()
        self.update()

    def keyPressEvent(self, ev):
        k = ev.key()
        mods = ev.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        # WASD/стрелки — панорамирование при приближении (без Ctrl, чтобы не
        # конфликтовать с Ctrl+Z/Y). Шаг крупнее с Shift. WASD читаются по физической
        # клавише → работают на любой раскладке (см. _pan_dir_from_event).
        pan_dir = _pan_dir_from_event(ev)
        if not ctrl and pan_dir is not None and self.img_bgr is not None:
            step = 120 if shift else 50
            sx, sy = pan_dir
            self._pan_by(sx * step, sy * step)
            return
        if k == Qt.Key.Key_Alt:
            self._set_alt(True)
        if k == Qt.Key.Key_Escape and self._pending is not None:
            # Esc убирает незакреплённый объект (фигуру/текст) без вжигания.
            self.cancel_pending()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._pending is not None:
            # Enter закрепляет плавающий объект.
            self._commit_pending()
        elif k == Qt.Key.Key_Escape and self._tool == self.TOOL_CROP:
            self.cancel_crop()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.has_crop():
            self.apply_crop()
        elif k == Qt.Key.Key_Y and ctrl:
            self.redo()
        elif k == Qt.Key.Key_Z and ctrl and shift:
            self.redo()
        elif k == Qt.Key.Key_Z and ctrl:
            self.undo()
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key.Key_Alt:
            self._set_alt(False)
        super().keyReleaseEvent(ev)

    def resizeEvent(self, ev):
        if self.img_bgr is not None and not self._user_zoomed:
            self._fit()
        self._update_crop_buttons()
        super().resizeEvent(ev)

    # ── Отрисовка ────────────────────────────────────────────────────────────
    def paintEvent(self, ev):
        self._sync_overlay_buttons()
        self._sync_scrollbars()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#11111b"))
        if self.img_bgr is None or self._base_pix is None:
            painter.setPen(QColor("#585b70"))
            f = painter.font(); f.setPointSize(11); painter.setFont(f)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Откройте изображение для удаления объектов\n"
                             "(кнопка «Открыть» сверху или перетащите файл)")
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        ih, iw = self.img_bgr.shape[:2]
        target = self._img_rect_w()
        src = QRectF(0, 0, iw, ih)
        painter.drawPixmap(target, self._base_pix, src)
        # Слой краски «Кисти» поверх фото (ещё не вжатый — чтобы Ластик мог стирать).
        if self._paint_layer is not None:
            painter.drawImage(target, self._paint_layer, src)
        painter.drawImage(target, self._overlay, src)

        # Рамка кадрирования (стиль Paint/Photoshop): затемняем всё ВНЕ рамки,
        # рисуем границу, сетку третей и квадратные ручки на углах/серединах сторон.
        if self._tool == self.TOOL_CROP and self.has_crop():
            r = self._crop_rect_w().intersected(target)
            # 4 затемняющих полосы вокруг рамки (в пределах изображения).
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 120))
            painter.drawRect(QRectF(target.left(), target.top(),
                                    target.width(), r.top() - target.top()))
            painter.drawRect(QRectF(target.left(), r.bottom(),
                                    target.width(), target.bottom() - r.bottom()))
            painter.drawRect(QRectF(target.left(), r.top(),
                                    r.left() - target.left(), r.height()))
            painter.drawRect(QRectF(r.right(), r.top(),
                                    target.right() - r.right(), r.height()))
            # Сетка третей.
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
            for i in (1, 2):
                gx = r.left() + r.width() * i / 3.0
                gy = r.top() + r.height() * i / 3.0
                painter.drawLine(QPointF(gx, r.top()), QPointF(gx, r.bottom()))
                painter.drawLine(QPointF(r.left(), gy), QPointF(r.right(), gy))
            # Граница рамки.
            painter.setPen(QPen(QColor("#cdd6f4"), 1.5))
            painter.drawRect(r)
            # Квадратные ручки.
            painter.setPen(QPen(QColor("#1e1e2e"), 1))
            painter.setBrush(QColor("#cdd6f4"))
            hs = 4.0
            cx, cy = r.center().x(), r.center().y()
            for p in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight(),
                      QPointF(cx, r.top()), QPointF(cx, r.bottom()),
                      QPointF(r.left(), cy), QPointF(r.right(), cy)):
                painter.drawRect(QRectF(p.x() - hs, p.y() - hs, 2 * hs, 2 * hs))

        # Предпросмотр тянущейся фигуры (в экранных координатах поверх картинки).
        if (self._shape_drawing and self._shape_start is not None
                and self._shape_cur is not None):
            painter.save()
            painter.setClipRect(target)
            painter.translate(self._off)
            painter.scale(self._scale, self._scale)
            self._draw_shape(painter, self._shape_start, self._shape_cur, self._tool)
            painter.restore()

        # Плавающий объект (фигура/текст) + пунктирная рамка выделения вокруг него —
        # видно, что его ещё можно перетащить (как выделенный слой в Photoshop).
        if self._pending is not None:
            painter.save()
            painter.setClipRect(target)
            painter.translate(self._off)
            painter.scale(self._scale, self._scale)
            self._draw_object(painter, self._pending)
            painter.restore()
            bb = self._object_bbox(self._pending)
            sel = QRectF(self._i2w(bb.topLeft()), self._i2w(bb.bottomRight())).normalized()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 160), 2, Qt.PenStyle.DashLine))
            painter.drawRect(sel)
            painter.setPen(QPen(QColor("#89b4fa"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(sel)
            # Квадратные ручки размера (только у картинки — её можно ресайзить).
            if self._pending_resizable():
                painter.setPen(QPen(QColor("#1e1e2e"), 1))
                painter.setBrush(QColor("#89b4fa"))
                hs = 4.0
                cx, cy = sel.center().x(), sel.center().y()
                for p in (sel.topLeft(), sel.topRight(), sel.bottomLeft(),
                          sel.bottomRight(), QPointF(cx, sel.top()),
                          QPointF(cx, sel.bottom()), QPointF(sel.left(), cy),
                          QPointF(sel.right(), cy)):
                    painter.drawRect(QRectF(p.x() - hs, p.y() - hs, 2 * hs, 2 * hs))

        # Кольцо-курсор кисти/ластика (не показываем под Alt-пипеткой).
        if (self._mouse_w is not None and not self._panning and not self._alt
                and self._tool in (self.TOOL_BRUSH, self.TOOL_MASK, self.TOOL_ERASE)):
            rad = self._brush / 2.0
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 160), 2))
            painter.drawEllipse(self._mouse_w, rad, rad)
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
            painter.drawEllipse(self._mouse_w, rad, rad)



class _WarmupWorker(QThread):
    """Фоновый прогрев сессии ONNX (загрузка 200-МБ модели ~10 с), чтобы первый
    клик «Удалить» не ждал инициализацию."""
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, inpainter):
        super().__init__()
        self._inp = inpainter

    def run(self):
        try:
            self.done.emit(self._inp.warmup())
        except Exception as e:        # pragma: no cover
            import traceback; traceback.print_exc()
            self.failed.emit(str(e))


class InpaintWorker(QThread):
    """Фоновый инференс LaMa — UI не виснет на время обработки."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, inpainter, img_bgr, mask):
        super().__init__()
        self._inp = inpainter
        self._img = img_bgr
        self._mask = mask

    def run(self):
        try:
            res = self._inp.inpaint(
                self._img, self._mask,
                progress=lambda d, t: self.progress.emit(int(d), int(t)))
            self.done.emit(res)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.failed.emit(str(e))


class BgRemoveWorker(QThread):
    """Фоновое удаление фона (RMBG-2.0) — UI не виснет на инференсе/загрузке модели."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, remover, img_bgr):
        super().__init__()
        self._rem = remover
        self._img = img_bgr

    def run(self):
        try:
            alpha = self._rem.remove(
                self._img,
                progress=lambda d, t: self.progress.emit(int(d), int(t)))
            self.done.emit(alpha)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.failed.emit(str(e))



class InpaintTab(QWidget):
    """Подвкладка «Удаление объектов»: закрашиваете кистью водяной знак/надпись —
    нейросеть LaMa аккуратно «дорисовывает» фон под ним."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        # Сессию держим в дочернем процессе: её создание удерживает GIL ~10–25 c
        # и в обычном QThread заморозило бы весь UI (см. lama_inpaint.py).
        self._inpainter = LaMaProcessInpainter() if _HAS_INPAINT else None
        # Удаление фона (RMBG-2.0) — отдельная модель/процесс, грузится лениво при
        # первом нажатии «Удалить фон» (модель ~360 МБ — не держим зря в памяти).
        self._remover = RMBGProcessRemover() if _HAS_RMBG else None
        self._worker = None
        self._bg_worker = None
        self._cancelling = False
        self._warmup = None
        # Длительность инференса нейросети заранее НЕ известна (один проход модели
        # не даёт сигнала прогресса), поэтому НЕ выдумываем «осталось N секунд» и не
        # рисуем фейковый бар. Показываем ЧЕСТНО: бесконечный индикатор занятости +
        # реально прошедшее время (счётчик вверх). У LaMa с НЕСКОЛЬКИМИ областями
        # прогресс настоящий (готово/всего) — там бар детерминированный.
        self._proc_start = 0.0          # time.monotonic() старта (для счётчика времени)
        self._proc_region_mode = False  # LaMa: прогресс ведут реальные области
        self._proc_timer = None
        self._warmed = False
        self._device = "—"
        self._src_path = None       # путь исходника (для имени и папки сохранения)
        self._out_dir = None        # выбранная папка сохранения (None → рядом с исходником)
        # Выгрузка моделей из ОЗУ при простое. Настройка «Не выгружать…» (по умолч.
        # выкл) держит их всегда. Иначе — таймер на минуту, сбрасывается при любом
        # взаимодействии; по срабатыванию убивает процессы LaMa/RMBG.
        self._keep_models = False
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(60_000)
        self._idle_timer.timeout.connect(self._maybe_unload_models)
        if not _HAS_INPAINT:
            self._build_unavailable()
        else:
            self._build_ui()
            self.setAcceptDrops(True)
            self.canvas.installEventFilter(self)   # взаимодействие → сброс таймера

    # ── Заглушка при отсутствии зависимостей ─────────────────────────────────
    def _build_unavailable(self):
        lay = QVBoxLayout(self)
        msg = ("Подвкладка «Удаление объектов» недоступна.\n\n"
               "Нужны пакеты: opencv-python, numpy, onnxruntime.\n"
               "Установка:  pip install opencv-python onnxruntime")
        if _INPAINT_ERR:
            msg += f"\n\n{_INPAINT_ERR}"
        lbl = QLabel(msg)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#a6adc8; font-size:13px;")
        lay.addStretch(); lay.addWidget(lbl); lay.addStretch()

    # ── Построение интерфейса ────────────────────────────────────────────────
    def _build_ui(self):
        # СЛЕВА — все инструменты и кнопки; СПРАВА — холст.
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Левая колонка: ЗАКРЕПЛЁННЫЙ сверху переключатель режима (его вставляет
        # PhotoTab) + ПРОКРУЧИВАЕМАЯ панель инструментов под ним (раньше нижние
        # кнопки «Сохранение» не помещались — теперь появляется скроллбар).
        left_col = QWidget(); left_col.setFixedWidth(264)
        self._left_col = left_col   # PhotoTab подгонит ширину под переключатель режима
        left_col_l = QVBoxLayout(left_col)
        left_col_l.setContentsMargins(0, 0, 0, 0); left_col_l.setSpacing(8)
        self._switch_holder = QVBoxLayout()
        self._switch_holder.setContentsMargins(0, 0, 0, 0)
        left_col_l.addLayout(self._switch_holder)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 6, 0); left.setSpacing(8)

        self.btn_open = _icon_btn("Открыть изображение", 'fa5s.folder-open')
        self.btn_open.clicked.connect(self._open)
        left.addWidget(self.btn_open)

        # ── Инструменты ──────────────────────────────────────────────────────
        grp_tools = QGroupBox("Инструменты")
        tl = QVBoxLayout(grp_tools); tl.setSpacing(6)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.btn_move = self._tool_btn("Курсор", 'fa5s.mouse-pointer',
                                       "Выделять и перемещать наложенное изображение (второй слой); "
                                       "тяните за уголки/стороны — меняется размер. Esc или клик вне — "
                                       "снять выделение, Enter — вжать слой. Инструмент по умолчанию.")
        self.btn_brush = self._tool_btn("Кисть", 'fa5s.paint-brush',
                                        "Рисуйте прямо по фото выбранным цветом — мазок вживается в "
                                        "картинку (обычная кисть, как в Paint). Цвет — в блоке «Кисть» "
                                        "ниже, Alt+клик — пипетка цвета. Это НЕ удаление объектов.")
        self.btn_erase = self._tool_btn("Ластик", 'fa5s.eraser',
                                        "Стирает мазки «Кисти» (то, что вы нарисовали поверх фото). "
                                        "Размер — ползунком «Кисть».")
        self.btn_crop = self._tool_btn("Кадрировать", 'fa5s.crop-alt',
                                       "Выделите прямоугольник и нажмите «Применить» прямо на холсте (или Enter)")
        # «Удалить объект» — это инструмент-кисть удаления (как Spot Healing Brush в
        # Photoshop): выбрал → закрашиваешь красным объект/водяной знак → он сразу
        # стирается, а фон дорисовывает нейросеть. Отдельной кнопки «выделить»
        # больше нет — выделение и есть нажатие этой кнопки.
        self.btn_run = self._tool_btn("Удалить объект", 'fa5s.magic',
                                      "Кисть удаления (как в Photoshop): выберите и закрасьте объект/"
                                      "водяной знак — он сотрётся, а фон дорисует нейросеть.")
        # «Удалить фон» — одноразовое действие (НЕ инструмент-кисть): нейросеть
        # RMBG-2.0 отделяет объект от фона, фон становится прозрачным (как «Удалить
        # фон» в Photoshop). Поэтому НЕ кладём её в tool_group (не залипает).
        self.btn_bg = _icon_btn("Удалить фон", 'fa5s.cut')
        self.btn_bg.setToolTip("Удалить фон автоматически (нейросеть RMBG-2.0): объект "
                               "остаётся, фон становится прозрачным. Сохраняйте в PNG.")
        # Фигуры и текст переехали в отдельный блок «Фигуры и текст» ниже (кнопки
        # «Фигуры»/«Текст» с всплывающими панелями, как flyout в Photoshop).
        # «Курсор» — инструмент по умолчанию и первый в списке.
        self.btn_move.setChecked(True)
        for b in (self.btn_move, self.btn_brush, self.btn_erase, self.btn_crop):
            self.tool_group.addButton(b); tl.addWidget(b)
        self.tool_group.addButton(self.btn_run)
        # «Удалить объект» и «Удалить фон» — со значком ⓘ и кратким описанием рядом
        # (по просьбе: что именно делает каждая кнопка).
        tl.addLayout(self._tool_row(
            self.btn_run,
            "«Удалить объект» — кисть удаления (как Spot Healing Brush в Photoshop). "
            "Выберите её и закрасьте красным лишний объект/водяной знак/надпись — на "
            "отпускании кнопки мыши закрашенное стирается, а фон под ним дорисовывает "
            "Используется нейросеть LaMa OnnX. Может медленно работать на слабом процессоре"))
        tl.addLayout(self._tool_row(
            self.btn_bg,
            "Нейросеть RMBG-2.0 находит "
            "главный объект и делает весь фон прозрачным. Первый запуск дольше — грузится модель (~360 МБ). "
            ))
        self.btn_move.clicked.connect(lambda: self._set_tool(InpaintCanvas.TOOL_MOVE))
        self.btn_brush.clicked.connect(lambda: self._set_tool(InpaintCanvas.TOOL_BRUSH))
        self.btn_erase.clicked.connect(lambda: self._set_tool(InpaintCanvas.TOOL_ERASE))
        self.btn_crop.clicked.connect(lambda: self._set_tool(InpaintCanvas.TOOL_CROP))
        self.btn_run.clicked.connect(self._activate_delete_tool)
        self.btn_bg.clicked.connect(self._remove_bg)
        # «Применить кадрирование» теперь живёт ПРЯМО на холсте (как в Photoshop) —
        # см. InpaintCanvas._crop_apply_btn. Отдельной кнопки в панели больше нет.
        left.addWidget(grp_tools)

        # ── Фигуры и текст ───────────────────────────────────────────────────
        # Одна кнопка «Фигуры» прячет прямоугольник/эллипс/линию/стрелку во
        # всплывающей панели (flyout, как в Photoshop). Рядом — кнопка «Текст».
        # Параметры (заливка/шрифт/размер) и экранная пипетка живут ВНУТРИ
        # всплывающих панелей, открывающихся по клику на кнопку.
        grp_shape = QGroupBox("Фигуры и текст")
        shl = QVBoxLayout(grp_shape); shl.setSpacing(6)
        self._cur_shape_tool = InpaintCanvas.TOOL_RECT
        self.btn_shapes = self._tool_btn(
            "Фигуры", 'fa5s.shapes',
            "Прямоугольник, эллипс, линия, стрелка — выбор во всплывающей панели. "
            "Толщина = размер кисти, цвет = цвет кисти. Нарисованную фигуру можно "
            "перетащить, пока не выбран другой инструмент.")
        self.btn_text = self._tool_btn(
            "Текст", 'fa5s.font',
            "Кликните по холсту и введите текст. Шрифт/размер — во всплывающей "
            "панели; размещённый текст можно перетащить мышью.")
        self.tool_group.addButton(self.btn_shapes)
        self.tool_group.addButton(self.btn_text)
        self.btn_shapes.clicked.connect(self._on_shapes_btn)
        self.btn_text.clicked.connect(self._on_text_btn)
        shl.addWidget(self.btn_shapes)
        shl.addWidget(self.btn_text)
        left.addWidget(grp_shape)
        # Всплывающие панели (создаём один раз, переиспользуем). Внутри —
        # self.chk_fill / self.cmb_font / self.spin_font (нужны коду ниже).
        self._build_shape_flyout()
        self._build_text_flyout()

        # ── Кисть: размер + цвет ─────────────────────────────────────────────
        grp_brush = QGroupBox("Кисть")
        gb = QVBoxLayout(grp_brush); gb.setSpacing(6)
        bl = QHBoxLayout()
        # _JumpSlider: клик по дорожке СРАЗУ ставит значение в точку клика
        # (обычный QSlider лишь «полз» шагами — см. класс выше).
        self.sld_brush = _JumpSlider(Qt.Orientation.Horizontal)
        self.sld_brush.setRange(4, 200); self.sld_brush.setValue(30)
        self.sld_brush.valueChanged.connect(self._on_brush)
        bl.addWidget(self.sld_brush, 1)
        self.lbl_brush = QLabel("30"); self.lbl_brush.setFixedWidth(30)
        bl.addWidget(self.lbl_brush)
        gb.addLayout(bl)
        row_col = QHBoxLayout()
        row_col.addWidget(QLabel("Цвет:"))
        self.btn_brush_color = QPushButton()
        self.btn_brush_color.setFixedSize(40, 22)
        self.btn_brush_color.setToolTip("Цвет мазка кисти — клик откроет окно выбора "
                                        "цвета (Alt+клик по картинке берёт цвет пипеткой).")
        self.btn_brush_color.clicked.connect(self._pick_brush_color)
        self._update_color_swatch(QColor(235, 45, 45))
        row_col.addWidget(self.btn_brush_color)
        # Пипетка «взять цвет с экрана» убрана из постоянной панели — теперь она
        # живёт во всплывающих панелях «Фигуры»/«Текст». Цвет с картинки — Alt+клик.
        row_col.addStretch()
        gb.addLayout(row_col)
        left.addWidget(grp_brush)

        # ── Вид ──────────────────────────────────────────────────────────────
        # Кнопку «Сбросить маску» убрали: маска удаления теперь временная (стирается
        # сразу после удаления), отдельно сбрасывать нечего.
        grp_edit = QGroupBox("Вид")
        el = QVBoxLayout(grp_edit); el.setSpacing(6)
        self.btn_fit = _icon_btn("Вписать в окно", 'fa5s.expand-arrows-alt')
        self.btn_fit.setToolTip("Колесо мыши — зум; средняя кнопка, «Курсор» или "
                                "WASD/стрелки — двигать картинку при приближении")
        self.btn_fit.clicked.connect(lambda: self.canvas.fit())
        # «Очистить» (полностью очистить холст) — значком в ПРАВОМ верхнем углу
        # холста (canvas.clearRequested → self._clear_canvas). Отмена/возврат
        # (Ctrl+Z / Ctrl+Y) — значками в ЛЕВОМ верхнем углу холста.
        el.addWidget(self.btn_fit)
        left.addWidget(grp_edit)

        # ── Сохранение ───────────────────────────────────────────────────────
        # Эта группа НЕ добавляется в прокручиваемую область — она закрепляется
        # внизу панели (см. ниже, после scroll), чтобы «Выбрать папку» и
        # «Сохранить» всегда были видны рядом со скроллбаром.
        grp_save = QGroupBox("Сохранение")
        sl = QVBoxLayout(grp_save); sl.setSpacing(6)
        self.lbl_outdir = QLabel("Папка: рядом с исходником")
        self.lbl_outdir.setWordWrap(True)
        self.lbl_outdir.setStyleSheet("color:#7f849c; font-size:11px;")
        sl.addWidget(self.lbl_outdir)
        self.btn_outdir = _icon_btn("Выбрать папку…", 'fa5s.folder')
        self.btn_outdir.setToolTip("Куда сохранять. Если не выбрано — рядом с исходником.")
        self.btn_outdir.clicked.connect(self._choose_out_dir)
        sl.addWidget(self.btn_outdir)
        # Зелёная, как кнопка «НАЧАТЬ» во вкладке «Обработка» (#b_run в config.py).
        self.btn_save = _icon_btn("Сохранить", 'fa5s.save', color='#1e1e2e')
        self.btn_save.setObjectName("b_run")
        self.btn_save.setToolTip("Сохранить <имя>_photo рядом с исходником (или в выбранную папку), без потерь")
        self.btn_save.clicked.connect(self._save)
        sl.addWidget(self.btn_save)

        # ── Статус ───────────────────────────────────────────────────────────
        # Подпись-инструкция убрана из панели (visible=False), но объект остаётся:
        # на него по-прежнему пишут _set_status/_save/_run_inpaint (без крэшей),
        # просто текст больше не занимает место в панели.
        self.lbl_status = QLabel("")
        self.lbl_status.setVisible(False)
        self.lbl_device = QLabel("Устройство: —")
        self.lbl_device.setStyleSheet("color:#7f849c; font-size:11px;")
        self.lbl_device.setToolTip(
            "На каком железе считает нейросеть. GPU (CUDA) — если есть видеокарта "
            "NVIDIA с драйверами CUDA, иначе автоматически CPU.")
        left.addWidget(self.lbl_device)
        left.addStretch(1)
        scroll.setWidget(left_w)
        left_col_l.addWidget(scroll, 1)
        # «Сохранение» закреплено внизу панели (вне прокрутки): «Выбрать папку»
        # и «Сохранить» всегда видны рядом со скроллбаром.
        left_col_l.addWidget(grp_save, 0)
        root.addWidget(left_col, 0)

        # СПРАВА — холст.
        self.canvas = InpaintCanvas(self)
        self.canvas.statusChanged.connect(self._set_status)
        # Alt-пипетка из холста обновляет образец цвета в панели.
        self.canvas.colorPicked.connect(self._on_color_picked)
        # Завершён мазок кистью удаления → сразу убираем закрашенное (как в Photoshop).
        self.canvas.strokeFinished.connect(self._on_stroke_finished)
        # Кнопка «Очистить» в правом верхнем углу холста.
        self.canvas.clearRequested.connect(self._clear_canvas)
        # Undo/redo может вернуть/убрать картинку (напр. отмена «Очистить») —
        # пере-включаем инструменты и холст, иначе картинка видна, но «мёртвая».
        self.canvas.imageChanged.connect(self._refresh_enabled)
        # Текст создан/выделен кликом — открываем панель его свойств (цвет/шрифт/
        # размер/обводка), как выделение текстового слоя в Photoshop.
        self.canvas.textSelected.connect(self._on_text_selected)
        root.addWidget(self.canvas, 1)
        # Передаём холсту стартовый шрифт текста (из комбобокса + размера).
        self._update_text_font()
        self.canvas.set_shape_fill(self.chk_fill.isChecked())

        # Отмена/возврат на уровне вкладки (а не только холста) — чтобы Ctrl+Z/
        # Ctrl+Y работали даже когда фокус ушёл на кнопку (например, после клика
        # по «Применить кадрирование» или инструментам).
        self._sc_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._sc_undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_undo.activated.connect(lambda: self.canvas.undo())
        self._sc_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._sc_redo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_redo.activated.connect(lambda: self.canvas.redo())
        self._sc_redo2 = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self._sc_redo2.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_redo2.activated.connect(lambda: self.canvas.redo())

        self._refresh_enabled()

    def _tool_btn(self, text, icon, tip):
        b = _icon_btn(text, icon)
        b.setCheckable(True)
        b.setToolTip(tip)
        return b

    def _tool_row(self, btn, tip):
        """Строка «кнопка-инструмент (растягивается) + значок ⓘ». Значок ⓘ — тот же
        `info_badge` (widgets.py), что у заголовков вкладок сверху: fa5s.info-circle
        #89b4fa, свой попап без синего системного тултипа."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0); row.setSpacing(5)
        row.addWidget(btn, 1)
        row.addWidget(info_badge(tip), 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    # ── Всплывающие панели «Фигуры»/«Текст» (flyout, как в Photoshop) ─────────
    def _make_flyout(self):
        """Создаёт пустую всплывающую панель, пристыкованную к вкладке. НЕ Qt.Popup —
        тот грэбит мышь и съедает самый первый клик (клик вне панели, например по
        холсту, тратился на её закрытие, а не доходил до холста), из-за чего нельзя
        было сразу же перетащить текст под панелью. Плавающее Tool-окно без грэба
        не мешает кликам по холсту; закрывается явно при смене инструмента
        (см. _set_tool)."""
        f = QFrame(self, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        f.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        f.setObjectName("toolFlyout")
        f.setStyleSheet(
            "QFrame#toolFlyout{background:#181825;border:1px solid #45475a;"
            "border-radius:8px;} QLabel{color:#cdd6f4;}")
        return f

    def _build_shape_flyout(self):
        self._shape_flyout = self._make_flyout()
        v = QVBoxLayout(self._shape_flyout)
        v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
        self._shape_btn_group = QButtonGroup(self._shape_flyout)
        self._shape_btn_group.setExclusive(True)
        self._shape_tool_btns = {}
        defs = [("Прямоугольник", 'fa5s.square', InpaintCanvas.TOOL_RECT),
                ("Эллипс", 'fa5s.circle', InpaintCanvas.TOOL_ELLIPSE),
                ("Линия", 'fa5s.minus', InpaintCanvas.TOOL_LINE),
                ("Стрелка", 'fa5s.long-arrow-alt-right', InpaintCanvas.TOOL_ARROW)]
        for text, icon, tool in defs:
            b = _icon_btn(text, icon); b.setCheckable(True)
            self._shape_btn_group.addButton(b)
            self._shape_tool_btns[tool] = b
            b.clicked.connect(lambda _=False, t=tool: self._pick_shape(t))
            v.addWidget(b)
        self._shape_tool_btns[self._cur_shape_tool].setChecked(True)
        self.chk_fill = QCheckBox("Заливка фигур")
        self.chk_fill.setToolTip("Заливать прямоугольник/эллипс цветом кисти "
                                 "(иначе только контур).")
        self.chk_fill.toggled.connect(lambda val: self.canvas.set_shape_fill(val))
        v.addWidget(self.chk_fill)

    def _build_text_flyout(self):
        self._text_flyout = self._make_flyout()
        v = QVBoxLayout(self._text_flyout)
        v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
        frow = QHBoxLayout(); frow.addWidget(QLabel("Шрифт:"))
        self.cmb_font = QFontComboBox()
        self.cmb_font.setToolTip("Системный шрифт для инструмента «Текст».")
        frow.addWidget(self.cmb_font, 1); v.addLayout(frow)
        srow = QHBoxLayout(); srow.addWidget(QLabel("Размер:"))
        self.spin_font = QSpinBox()
        self.spin_font.setRange(6, 1000); self.spin_font.setValue(48)
        self.spin_font.setSuffix(" px")
        self.spin_font.setToolTip("Высота текста в пикселях изображения.")
        srow.addWidget(self.spin_font, 1); v.addLayout(srow)
        crow = QHBoxLayout(); crow.addWidget(QLabel("Цвет:"))
        self.btn_text_color = QPushButton()
        self.btn_text_color.setFixedSize(28, 22)
        self.btn_text_color.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_text_color.setToolTip("Цвет текста. Клик по уже написанному тексту "
                                       "выделяет его — можно поменять цвет/шрифт/обводку.")
        self.btn_text_color.clicked.connect(self._pick_text_color)
        crow.addWidget(self.btn_text_color); crow.addStretch(1)
        v.addLayout(crow)
        self._text_color = QColor(255, 255, 255)
        self._update_text_color_swatch(self._text_color)

        _sep = QFrame(); _sep.setFrameShape(QFrame.Shape.HLine)
        _sep.setStyleSheet("color:#45475a;")
        v.addWidget(_sep)
        self.chk_text_stroke = QCheckBox("Обводка")
        self.chk_text_stroke.setToolTip("Контур текста (как в Photoshop).")
        v.addWidget(self.chk_text_stroke)
        strow = QHBoxLayout(); strow.addWidget(QLabel("Толщина:"))
        self.spin_stroke_w = QSpinBox()
        self.spin_stroke_w.setRange(1, 60); self.spin_stroke_w.setValue(4)
        self.spin_stroke_w.setSuffix(" px")
        strow.addWidget(self.spin_stroke_w, 1); v.addLayout(strow)
        scrow = QHBoxLayout(); scrow.addWidget(QLabel("Цвет обводки:"))
        self.btn_stroke_color = QPushButton()
        self.btn_stroke_color.setFixedSize(28, 22)
        self.btn_stroke_color.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stroke_color.clicked.connect(self._pick_stroke_color)
        scrow.addWidget(self.btn_stroke_color); scrow.addStretch(1)
        v.addLayout(scrow)
        self._stroke_color = QColor(0, 0, 0)
        self._update_stroke_color_swatch(self._stroke_color)

        self.cmb_font.currentFontChanged.connect(lambda *_: self._update_text_font())
        self.spin_font.valueChanged.connect(lambda *_: self._update_text_font())
        self.chk_text_stroke.toggled.connect(lambda *_: self._update_text_stroke())
        self.spin_stroke_w.valueChanged.connect(lambda *_: self._update_text_stroke())

    def _update_text_color_swatch(self, color):
        self.btn_text_color.setStyleSheet(
            f"background-color: {color.name()}; border:1px solid #585b70; border-radius:3px;")

    def _update_stroke_color_swatch(self, color):
        self.btn_stroke_color.setStyleSheet(
            f"background-color: {color.name()}; border:1px solid #585b70; border-radius:3px;")

    def _active_text_obj(self):
        """Плавающий (ещё не вжатый) текстовый объект, если он сейчас выделен."""
        p = getattr(self.canvas, "_pending", None)
        return p if (p is not None and p.get('kind') == 'text') else None

    def _on_text_selected(self):
        """Текст создан/выбран кликом — подтягиваем его текущие параметры в
        панель (иначе она показывала бы значения по умолчанию для СЛЕДУЮЩЕГО
        текста, а не выделенного) и открываем панель."""
        obj = self._active_text_obj()
        if obj is not None:
            f = obj['font']
            self.cmb_font.blockSignals(True); self.spin_font.blockSignals(True)
            self.cmb_font.setCurrentFont(f)
            self.spin_font.setValue(max(6, f.pixelSize() if f.pixelSize() > 0 else 48))
            self.cmb_font.blockSignals(False); self.spin_font.blockSignals(False)
            self._text_color = QColor(obj['color'])
            self._update_text_color_swatch(self._text_color)
            sw = float(obj.get('stroke_width', 0) or 0)
            self._stroke_color = QColor(obj.get('stroke_color', QColor(0, 0, 0)))
            self.chk_text_stroke.blockSignals(True); self.spin_stroke_w.blockSignals(True)
            self.chk_text_stroke.setChecked(sw > 0)
            if sw > 0:
                self.spin_stroke_w.setValue(int(round(sw)))
            self.chk_text_stroke.blockSignals(False); self.spin_stroke_w.blockSignals(False)
            self._update_stroke_color_swatch(self._stroke_color)
        self.btn_text.setChecked(True)
        # Popup сам делает mouse-grab при show() — если он уже открыт, повторный
        # show() посреди перетаскивания текста срывает драг (грэб перехватывает
        # move/release у холста). Не переоткрываем, если панель и так на экране.
        if not self._text_flyout.isVisible():
            self._show_flyout(self._text_flyout, self.btn_text)

    def _pick_text_color(self):
        col = QColorDialog.getColor(self._text_color, self, "Цвет текста")
        if not col.isValid():
            return
        self._text_color = col
        self._update_text_color_swatch(col)
        self.canvas.set_text_color(col)
        obj = self._active_text_obj()
        if obj is not None:
            obj['color'] = QColor(col)
            self.canvas.update()

    def _pick_stroke_color(self):
        col = QColorDialog.getColor(self._stroke_color, self, "Цвет обводки")
        if not col.isValid():
            return
        self._stroke_color = col
        self._update_stroke_color_swatch(col)
        self.canvas.set_text_stroke(self.canvas._text_stroke_width, col)
        obj = self._active_text_obj()
        if obj is not None and obj.get('stroke_width', 0):
            obj['stroke_color'] = QColor(col)
            self.canvas.update()

    def _update_text_stroke(self):
        width = float(self.spin_stroke_w.value()) if self.chk_text_stroke.isChecked() else 0.0
        self.canvas.set_text_stroke(width, self._stroke_color)
        obj = self._active_text_obj()
        if obj is not None:
            obj['stroke_width'] = width
            obj['stroke_color'] = QColor(self._stroke_color)
            self.canvas.update()

    def _on_shapes_btn(self):
        """Клик по «Фигуры»: активируем текущую фигуру и открываем выбор."""
        if hasattr(self, "_text_flyout"):
            self._text_flyout.hide()
        self._set_tool(self._cur_shape_tool)
        self.btn_shapes.setChecked(True)
        self._show_flyout(self._shape_flyout, self.btn_shapes)

    def _on_text_btn(self):
        if hasattr(self, "_shape_flyout"):
            self._shape_flyout.hide()
        self._set_tool(InpaintCanvas.TOOL_TEXT)
        self.btn_text.setChecked(True)
        self._show_flyout(self._text_flyout, self.btn_text)

    def _pick_shape(self, tool):
        """Выбор конкретной фигуры во всплывающей панели."""
        self._cur_shape_tool = tool
        icons = {InpaintCanvas.TOOL_RECT: 'fa5s.square',
                 InpaintCanvas.TOOL_ELLIPSE: 'fa5s.circle',
                 InpaintCanvas.TOOL_LINE: 'fa5s.minus',
                 InpaintCanvas.TOOL_ARROW: 'fa5s.long-arrow-alt-right'}
        self.btn_shapes.setIcon(get_icon(icons.get(tool, 'fa5s.shapes')))
        self.btn_shapes.setChecked(True)
        self._set_tool(tool)
        if hasattr(self, "_shape_flyout"):
            self._shape_flyout.hide()

    def _show_flyout(self, flyout, anchor):
        flyout.adjustSize()
        gpos = anchor.mapToGlobal(QPoint(anchor.width() + 6, 0))
        scr = anchor.screen().availableGeometry() if anchor.screen() else None
        if scr is not None and gpos.x() + flyout.width() > scr.right():
            gpos = anchor.mapToGlobal(QPoint(-flyout.width() - 6, 0))
        if scr is not None and gpos.y() + flyout.height() > scr.bottom():
            gpos.setY(scr.bottom() - flyout.height() - 2)
        flyout.move(gpos)
        flyout.show()
        flyout.raise_()

    def insert_mode_switch(self, widget):
        """PhotoTab вставляет сюда переключатель режимов «Фото» (закреплён сверху
        левой панели, вместо верхней полосы вкладок)."""
        if hasattr(self, "_switch_holder"):
            self._switch_holder.addWidget(widget)

    # ── Цвет кисти ────────────────────────────────────────────────────────────
    def _update_color_swatch(self, color):
        self.btn_brush_color.setStyleSheet(
            f"background-color: {color.name()}; border:1px solid #585b70; "
            f"border-radius:3px;")

    def _pick_brush_color(self):
        # Клик по образцу цвета открывает обычное окно выбора цвета (как в
        # Photoshop). Взять цвет прямо с картинки можно Alt+клик по холсту.
        col = QColorDialog.getColor(self.canvas.brush_color(), self,
                                    "Цвет кисти")
        if col.isValid():
            self.canvas.set_brush_color(col)
            self._update_color_swatch(col)

    def _update_text_font(self):
        """Собирает QFont из выбранного системного шрифта + размера (px) и отдаёт
        холсту для инструмента «Текст» (по умолчанию для НОВОГО текста; если сейчас
        выделен плавающий текст — меняет и его, живьём, как в Photoshop)."""
        if not hasattr(self, "canvas"):
            return
        f = QFont(self.cmb_font.currentFont())
        f.setPixelSize(int(self.spin_font.value()))
        self.canvas.set_text_font(f)
        obj = self._active_text_obj()
        if obj is not None:
            obj['font'] = QFont(self.canvas._text_font)
            self.canvas.update()

    def _on_color_picked(self, col):
        # Цвет, взятый Alt-пипеткой из холста: только обновляем образец (сам
        # цвет кисти холст уже выставил).
        if col.isValid():
            self._update_color_swatch(col)

    def _activate_delete_tool(self):
        """«Удалить объект» — это кисть удаления (как Spot Healing Brush в
        Photoshop): просто включаем красную кисть-маску. Дальше закрашенное
        стирается автоматически на отпускании ЛКМ (см. _on_stroke_finished)."""
        if not self.canvas.has_image():
            return
        if not _HAS_ORT:
            # Без onnxruntime удаление не сработает — предупреждаем сразу при выборе
            # инструмента (раньше предупреждал клик по кнопке).
            msgbox_warning(self, "Нет onnxruntime",
                                "Для удаления объектов установите onnxruntime:\n\n"
                                "pip install onnxruntime")
            self.btn_run.setChecked(False)
            return
        self._set_tool(InpaintCanvas.TOOL_MASK)

    def _on_stroke_finished(self):
        # Кисть удаления как в Photoshop: закрасил объект — сразу убираем закрашенное.
        # Без onnxruntime или во время уже идущей обработки молча ничего не делаем.
        if not _HAS_ORT:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._run_inpaint()

    # ── Реакции UI ───────────────────────────────────────────────────────────
    def _set_tool(self, tool):
        # Панели «Фигуры»/«Текст» больше не Qt.Popup (не закрываются сами при клике
        # мимо) — закрываем их явно при смене инструмента, кроме случая, когда сам
        # инструмент — фигура/текст (тогда панель переоткрывает вызвавший метод).
        _flyout_tools = (InpaintCanvas.TOOL_RECT, InpaintCanvas.TOOL_ELLIPSE,
                         InpaintCanvas.TOOL_LINE, InpaintCanvas.TOOL_ARROW,
                         InpaintCanvas.TOOL_TEXT)
        if tool not in _flyout_tools:
            for fly in (getattr(self, "_shape_flyout", None), getattr(self, "_text_flyout", None)):
                if fly is not None:
                    fly.hide()
        self.canvas.set_tool(tool)
        # Возвращаем фокус холсту, чтобы WASD/стрелки (панорамирование) работали
        # сразу после клика по кнопке инструмента, а не уходили в кнопку.
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    _VK_Z = 0x5A
    _VK_Y = 0x59

    def keyPressEvent(self, ev):
        mods = ev.modifiers()
        # Резерв Ctrl+Z/Ctrl+Y для кириллической раскладки: физическая Z/Y там
        # шлёт Qt-код кириллической буквы, и QShortcut("Ctrl+Z"/"Ctrl+Y") выше
        # (см. self._sc_undo/_sc_redo) на ней молча не срабатывает (та же
        # природа бага, что и с WASD — см. _pan_dir_from_event). Событие сюда
        # доходит, только если QShortcut его не поймал — для латиницы там уже
        # сработало, тут лишь докрывается случай перевода раскладкой.
        if mods & Qt.KeyboardModifier.ControlModifier:
            try:
                vk = ev.nativeVirtualKey()
            except Exception:
                vk = 0
            if vk == self._VK_Z:
                (self.canvas.redo() if (mods & Qt.KeyboardModifier.ShiftModifier)
                 else self.canvas.undo())
                ev.accept()
                return
            if vk == self._VK_Y:
                self.canvas.redo()
                ev.accept()
                return
        # Резерв: WASD/стрелки панорамируют, даже если фокус не на холсте (клавиши
        # всплывают сюда от кнопок панели). Ctrl не трогаем (Ctrl+Z/Y и пр.).
        pan_dir = _pan_dir_from_event(ev)
        if (not (mods & Qt.KeyboardModifier.ControlModifier)
                and pan_dir is not None and hasattr(self, "canvas")
                and self.canvas.has_image()):
            step = 120 if (mods & Qt.KeyboardModifier.ShiftModifier) else 50
            sx, sy = pan_dir
            self.canvas._pan_by(sx * step, sy * step)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _on_brush(self, v):
        self.lbl_brush.setText(str(v))
        self.canvas.set_brush(v)

    def _set_status(self, text):
        self.lbl_status.setText(text)

    def set_left_width(self, w):
        """PhotoTab задаёт ширину левой панели под переключатель режима, чтобы
        обе подписи («Редактирование фото» / «Объединить фото») влезали целиком."""
        if hasattr(self, "_left_col"):
            self._left_col.setFixedWidth(int(w))

    def _refresh_enabled(self):
        has = self.canvas.has_image() if hasattr(self, "canvas") else False
        busy = ((self._worker is not None and self._worker.isRunning())
                or (self._bg_worker is not None and self._bg_worker.isRunning()))
        for b in (self.btn_run, self.btn_bg, self.btn_save, self.btn_fit):
            b.setEnabled(has and not busy)
        self.btn_open.setEnabled(not busy)
        self.btn_outdir.setEnabled(not busy)
        # «Ластик» стирает ТОЛЬКО ещё не вжатые мазки «Кисти» (см. _paint_image_to) —
        # пока их нет, стирать нечего, кнопка неактивна.
        self.btn_erase.setEnabled(has and not busy and bool(getattr(self.canvas, "_has_paint", False)))
        # Во время обработки холст не трогаем (мазки кистью всё равно сбросятся
        # результатом) — блокируем ввод, оставляя картинку видимой.
        self.canvas.setEnabled(has and not busy)

    # ── Открытие / сохранение / drag-n-drop ──────────────────────────────────
    def _open(self):
        # По умолчанию открываем папку, которую сейчас показывает общая лента
        # файлов сверху (RecentFilesStrip), иначе — папку прошлого исходника.
        start = self._ribbon_folder() or \
            (os.path.dirname(self._src_path) if self._src_path else "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть изображение", start,
            "Изображения (*.png *.jpg *.jpeg *.bmp *.webp *.tiff *.tif *.avif *.heic *.heif)")
        if path:
            self._load(path)

    def _ribbon_folder(self) -> str:
        """Папка, которую показывает общая лента файлов сверху (если задана)."""
        try:
            strip = getattr(self.main, "recent_strip", None)
            folder = strip._effective_folder() if strip is not None else ""
            return folder if folder and os.path.isdir(folder) else ""
        except Exception:
            return ""

    def _clear_canvas(self):
        self.canvas.clear_canvas()
        self._src_path = None
        self._refresh_enabled()

    def _load(self, path):
        try:
            if self.canvas.has_image():
                # Overlay-режим: загружаем с сохранением альфа-канала (PNG-прозрачность).
                arr = _load_image_alpha(path)
                self.canvas.add_overlay_image(arr)
                self._set_status(
                    f"Поверх — {os.path.basename(path)}. "
                    "Перетащите на нужное место; Enter или клик вне — вжать.")
            else:
                # Сохраняем альфа-канал при первом открытии — иначе прозрачность
                # PNG/WEBP/AVIF терялась бы уже на этом шаге (cv2.IMREAD_COLOR
                # альфу отбрасывает), а «Удалить фон» потом рисовал бы поверх
                # чужого фона, оставшегося от исходника.
                arr = _load_image_alpha(path)
                if arr.ndim == 3 and arr.shape[2] == 4:
                    self.canvas.set_image_bgr(arr[:, :, :3])
                    self.canvas.apply_cutout(arr[:, :, 3])
                else:
                    self.canvas.set_image_bgr(arr)
                self._src_path = path
                self._set_status(f"Загружено: {os.path.basename(path)}. "
                                 "Закрасьте объект кистью и нажмите «Удалить объект».")
                self._kick_warmup()
            self._refresh_enabled()
        except Exception as exc:
            msgbox_warning(self, "Ошибка", f"Не удалось открыть изображение:\n{exc}")

    def add_paths(self, paths):
        imgs = [p for p in paths if os.path.splitext(p)[1].lower() in
                {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tiff', '.tif',
                 '.avif', '.heic', '.heif'}]
        if imgs:
            self._load(imgs[0])

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.accept()
        else: e.ignore()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            e.accept()
            self.add_paths([u.toLocalFile() for u in e.mimeData().urls()])

    def _choose_out_dir(self):
        start = self._out_dir or (os.path.dirname(self._src_path) if self._src_path else "")
        d = QFileDialog.getExistingDirectory(self, "Папка для сохранения", start)
        if d:
            self._out_dir = d
            self.lbl_outdir.setText(f"Папка: {d}")
            self.lbl_outdir.setToolTip(d)

    def _output_path(self, has_alpha=False):
        """Путь сохранения: <имя_исходника>_photo.<ext> в выбранной папке (или
        рядом с исходником). Расширение — БЕЗ ПОТЕРЬ: исходные png/bmp/tiff
        сохраняем как есть, остальное (jpg/webp/avif/heic…) → png, чтобы не было
        повторного сжатия и потери качества. Если удалён фон (есть прозрачность) —
        формат обязан её хранить (png/webp/tiff), иначе принудительно png."""
        if self._src_path:
            base = os.path.splitext(os.path.basename(self._src_path))[0]
            src_ext = os.path.splitext(self._src_path)[1].lower().lstrip('.')
            src_dir = os.path.dirname(self._src_path)
        else:
            base, src_ext, src_dir = "image", "png", os.getcwd()
        if has_alpha:
            ext = src_ext if src_ext in ("png", "webp", "tif", "tiff") else "png"
        else:
            ext = src_ext if src_ext in ("png", "bmp", "tif", "tiff") else "png"
        out_dir = self._out_dir or src_dir or os.getcwd()
        stem = f"{base}_photo"
        path = os.path.join(out_dir, f"{stem}.{ext}")
        if not os.path.exists(path):
            return path
        n = 1
        while True:
            path = os.path.join(out_dir, f"{stem}_{n}.{ext}")
            if not os.path.exists(path):
                return path
            n += 1

    def _save(self):
        if not self.canvas.has_image():
            return
        # Вжигаем незакреплённый плавающий объект (фигуру/текст) в картинку, чтобы
        # он попал в сохранённый файл.
        self.canvas.commit_pending()
        # composited_bgra: BGRA, если фон удалён (прозрачность), иначе BGR.
        arr = self.canvas.composited_bgra()
        has_alpha = arr is not None and arr.ndim == 3 and arr.shape[2] == 4
        out = self._output_path(has_alpha)
        try:
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            # Сохраняем фото с вжатыми мазками «Кисти» (и альфой прозрачности, если
            # удалён фон). Красная маска удаления — служебная, в файл не попадает.
            save_bgr(out, arr)                            # png/webp/tiff — без потерь
            self._set_status(status_html('fa5s.check-circle',
                             f"Сохранено: {os.path.basename(out)}", '#a6e3a1'))
            self.lbl_status.setToolTip(out)
            # Всплывающее уведомление об успешном сохранении (по просьбе
            # пользователя) — показываем ТОЛЬКО если файл реально записан.
            if os.path.exists(out):
                self._show_saved_toast(os.path.basename(out))
        except Exception as exc:
            msgbox_warning(self, "Ошибка", f"Не удалось сохранить:\n{exc}")

    def _show_saved_toast(self, name: str):
        """Зелёный плавающий баннер «Файл сохранён» по центру сверху вкладки,
        автоскрытие через 3 с (как в SiQuesterHYX). Создаётся лениво."""
        lbl = getattr(self, "_saved_toast", None)
        if lbl is None:
            lbl = QLabel(self)
            lbl.setStyleSheet(
                "background:rgba(166,227,161,0.94);color:#181825;font-size:13px;"
                "font-weight:700;border-radius:8px;padding:8px 24px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._saved_toast = lbl
            self._saved_toast_timer = QTimer(self)
            self._saved_toast_timer.setSingleShot(True)
            self._saved_toast_timer.timeout.connect(lbl.hide)
        lbl.setText(f"✅  Файл сохранён: {name}")
        lbl.adjustSize()
        lbl.move(max(0, (self.width() - lbl.width()) // 2), 12)
        lbl.raise_(); lbl.show()
        self._saved_toast_timer.start(3000)

    # ── Прогрев модели ───────────────────────────────────────────────────────
    def showEvent(self, ev):
        super().showEvent(ev)
        # Грузим модель в фоне при первом показе вкладки (а не при старте приложения).
        if _HAS_INPAINT and not self._warmed:
            self._kick_warmup()
        self._touch()

    def hideEvent(self, ev):
        # Уход со вкладки = простой: запускаем отсчёт выгрузки (минута).
        super().hideEvent(ev)
        if _HAS_INPAINT and not self._keep_models:
            self._idle_timer.start()

    # ── Выгрузка моделей из ОЗУ при простое ──────────────────────────────────
    def set_keep_models(self, keep: bool):
        """Настройка «Не выгружать модели из ОЗУ»: True — держать всегда (таймер
        стоп), False — выгружать после минуты простоя."""
        self._keep_models = bool(keep)
        if self._keep_models:
            self._idle_timer.stop()
        elif self.isVisible():
            self._touch()
        else:
            self._idle_timer.start()

    def _touch(self):
        """Взаимодействие со вкладкой → сбрасываем отсчёт выгрузки. Модель тут НЕ
        подгружаем: загрузка только при открытии вкладки (showEvent) и при самом
        удалении объекта/фона. Клики/рисование лишь не дают выгрузить загруженную."""
        if not _HAS_INPAINT or self._keep_models:
            return
        self._idle_timer.start()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                         QEvent.Type.KeyPress, QEvent.Type.Wheel):
            self._touch()
        return super().eventFilter(obj, ev)

    def _models_busy(self) -> bool:
        return ((self._worker is not None and self._worker.isRunning())
                or (self._bg_worker is not None and self._bg_worker.isRunning())
                or self._warmup is not None)

    def _maybe_unload_models(self):
        if self._keep_models:
            return
        if self._models_busy():
            self._idle_timer.start()     # занят — отложим проверку
            return
        was_loaded = self._warmed
        for m in (self._inpainter, self._remover):
            if m is not None and hasattr(m, "unload"):
                try: m.unload()
                except Exception: pass
        self._warmed = False
        self._device = "—"
        if was_loaded and hasattr(self, "lbl_device"):
            self.lbl_device.setText("Устройство: модель выгружена из ОЗУ")

    def _kick_warmup(self):
        if not _HAS_INPAINT or self._warmed or self._warmup is not None:
            return
        if not _HAS_ORT:
            self.lbl_device.setText("Устройство: нет onnxruntime")
            return
        self.lbl_device.setText("Устройство: загрузка модели…")
        self._warmup = _WarmupWorker(self._inpainter)
        self._warmup.done.connect(self._on_warmed)
        self._warmup.failed.connect(self._on_warm_failed)
        self._warmup.start()

    def _on_warmed(self, device):
        self._warmed = True
        self._device = device
        self.lbl_device.setText(f"Устройство: {device}")
        self._warmup = None

    def _on_warm_failed(self, err):
        self.lbl_device.setText("Устройство: ошибка загрузки модели")
        self._set_status(status_html('fa5s.exclamation-triangle',
                         f"Модель не загрузилась: {err}", '#f9e2af'))
        self._warmup = None

    # ── Запуск инференса ─────────────────────────────────────────────────────
    def _run_inpaint(self):
        self._touch()
        if not self.canvas.has_image():
            return
        # Закрепляем плавающий объект, чтобы нейросеть видела финальную картинку.
        self.canvas.commit_pending()
        # Незавершённое кадрирование применяем (иначе нарисованная рамка пропадала,
        # а нейросеть работала по полному изображению — «убирала кадрирование»).
        if self.canvas.has_crop():
            self.canvas.apply_crop()
        if not _HAS_ORT:
            msgbox_warning(self, "Нет onnxruntime",
                                "Для удаления объектов установите onnxruntime:\n\n"
                                "pip install onnxruntime")
            return
        if not self.canvas.has_mask():
            # Сюда попадаем только при пустом выделении (кисть удаления не оставила
            # мазка) — тихо выходим: сама кнопка «Удалить объект» уже включает кисть.
            self._set_status("Закрасьте кистью удаления то, что нужно стереть.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._cancelling = False        # новый запуск — снимаем возможный флаг отмены
        # Снимок «до» (с отдельным слоем краски и маской) — для Ctrl+Z, затем
        # вживляем мазки кисти, чтобы нейросеть видела финальную картинку.
        self.canvas._push_history()
        self.canvas.bake_paint()
        mask = self.canvas.get_mask()
        img = self.canvas.img_bgr
        self._set_status(status_html('fa5s.spinner',
                         "Обработка нейросетью… (первый запуск дольше — грузится модель)",
                         '#89b4fa'))
        self.setCursor(Qt.CursorShape.WaitCursor)
        self._show_proc_chip(mask)          # мини-прогресс возле выделения/курсора
        self._worker = InpaintWorker(self._inpainter, img, mask)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.progress.connect(self._on_progress)
        self._worker.start()
        self._refresh_enabled()

    # ── Мини-прогресс «удаляю…» возле курсора/выделения ──────────────────────
    def _show_proc_chip(self, mask=None, label="Удаляю…", icon='fa5s.magic'):
        chip = getattr(self, "_proc_chip", None)
        if chip is None:
            chip = QFrame(self)
            chip.setObjectName("procChip")
            chip.setStyleSheet(
                "QFrame#procChip{background:rgba(30,30,46,235);"
                "border:1px solid #89b4fa;border-radius:9px;}"
                "QLabel{color:#cdd6f4;font-size:12px;font-weight:600;background:transparent;}"
                "QProgressBar{background:#11111b;border:1px solid #45475a;"
                "border-radius:5px;max-height:8px;min-height:8px;}"
                "QProgressBar::chunk{background:#89b4fa;border-radius:5px;}")
            lay = QHBoxLayout(chip)
            lay.setContentsMargins(10, 7, 8, 7); lay.setSpacing(8)
            self._proc_ic = QLabel()
            self._proc_ic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(self._proc_ic)
            self._proc_lbl = QLabel(label)
            self._proc_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(self._proc_lbl)
            self._proc_bar = QProgressBar()
            self._proc_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._proc_bar.setTextVisible(False)
            self._proc_bar.setFixedWidth(80)
            lay.addWidget(self._proc_bar)
            self._proc_cancel_btn = QPushButton("Отменить")
            self._proc_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._proc_cancel_btn.setToolTip("Отменить обработку")
            self._proc_cancel_btn.setStyleSheet(
                "QPushButton{background:#313244;border:1px solid #45475a;"
                "border-radius:5px;color:#f38ba8;font-size:11px;font-weight:600;"
                "padding:3px 8px;}"
                "QPushButton:hover{background:#45475a;border-color:#f38ba8;}")
            self._proc_cancel_btn.clicked.connect(self._cancel_proc)
            lay.addWidget(self._proc_cancel_btn)
            self._proc_chip = chip
        # Честный индикатор: бесконечный «бегунок» занятости. Длительность одного
        # прохода нейросети заранее неизвестна, поэтому НЕ выдумываем проценты и
        # «осталось N секунд» — подпись показывает реально ПРОШЕДШЕЕ время (счётчик
        # вверх). У LaMa с несколькими областями прогресс настоящий (готово/всего) —
        # там бар становится детерминированным (см. _on_progress).
        self._proc_base_label = label
        self._proc_status_text = label
        self._proc_mask = mask
        self._proc_region_mode = False
        self._proc_start = time.monotonic()
        self._proc_ic.setPixmap(get_icon(icon, color='#89b4fa').pixmap(14, 14))
        self._proc_lbl.setText(label)
        self._proc_bar.setRange(0, 0)        # 0,0 -> бесконечный индикатор занятости
        if self._proc_timer is None:
            self._proc_timer = QTimer(self)
            self._proc_timer.setInterval(500)
            self._proc_timer.timeout.connect(self._proc_tick)
        self._proc_timer.start()
        self._proc_anchor = None        # пересчитать якорь под новое выделение/курсор
        self._proc_chip.adjustSize()
        self._position_proc_chip(mask)
        self._proc_chip.show(); self._proc_chip.raise_()

    def _proc_tick(self):
        """Тик: подпись = реально ПРОШЕДШЕЕ время (честный счётчик вверх). Бар —
        бесконечный индикатор занятости, кроме режима реальных областей LaMa."""
        chip = getattr(self, "_proc_chip", None)
        if chip is None or not chip.isVisible():
            return
        elapsed = int(max(0.0, time.monotonic() - self._proc_start))
        if self._proc_region_mode:
            self._proc_lbl.setText(f"{self._proc_status_text} · {elapsed} с")
        else:
            self._proc_lbl.setText(f"{self._proc_base_label} {elapsed} с")
        # Чип подгоняем под подпись и пере-центрируем (якорь стабилен), чтобы текст
        # не обрезался по мере роста счётчика.
        self._proc_chip.adjustSize()
        self._position_proc_chip(self._proc_mask)

    def _finish_proc(self):
        """Завершение: останавливаем счётчик времени (чип прячется следом)."""
        if self._proc_timer is not None:
            self._proc_timer.stop()

    def _position_proc_chip(self, mask=None):
        # Якорь (центр привязки) вычисляем ОДИН раз при показе чипа и кэшируем —
        # иначе при обновлении подписи (счётчик времени растит ширину) чип бы прыгал
        # за курсором (для фона mask=None фолбэк брал бы текущую позицию мыши).
        gp = getattr(self, "_proc_anchor", None)
        if gp is None:
            canvas = self.canvas
            pt = None
            try:
                if mask is not None:
                    ys, xs = _np.where(mask > 0)
                    if len(xs):
                        pt = canvas._i2w(QPointF(float(xs.mean()), float(ys.mean())))
            except Exception:
                pt = None
            if pt is None:
                pt = canvas._mouse_w
            if pt is None:
                pt = QPointF(canvas.width() / 2.0, canvas.height() / 2.0)
            gp = canvas.mapTo(self, QPoint(int(pt.x()), int(pt.y())))
            self._proc_anchor = gp
        w, h = self._proc_chip.width(), self._proc_chip.height()
        x = max(4, min(gp.x() - w // 2, self.width() - w - 4))
        y = max(4, min(gp.y() - h - 14, self.height() - h - 4))
        self._proc_chip.move(x, y)

    def _hide_proc_chip(self):
        if self._proc_timer is not None:
            self._proc_timer.stop()
        chip = getattr(self, "_proc_chip", None)
        if chip is not None:
            chip.hide()

    def _cancel_proc(self):
        """Отмена текущей обработки (LaMa/RMBG). В процессном режиме kill дочернего
        процесса прерывает инференс за миллисекунды (воркер ловит обрыв пайпа и
        завершается сам). НО интерфейс приводим в «Отменено» СРАЗУ, не дожидаясь
        сигнала воркера: в редком in-process фолбэке одиночный sess.run() прервать
        нельзя, и иначе чип «Удаляю…» и курсор-«ожидание» висели бы до конца прохода
        («не останавливает / с задержкой»). Поздний результат осиротевшего воркера
        отбрасывается по флагу _cancelling (см. _on_done/_on_bg_done)."""
        running = ((self._worker is not None and self._worker.isRunning())
                   or (self._bg_worker is not None and self._bg_worker.isRunning()))
        if not running:
            return
        self._cancelling = True
        if self._worker is not None and self._worker.isRunning() and self._inpainter is not None:
            try: self._inpainter.cancel()
            except Exception: pass
        if self._bg_worker is not None and self._bg_worker.isRunning() and self._remover is not None:
            try: self._remover.cancel()
            except Exception: pass
        # Мгновенная реакция UI — не ждём, пока воркер domотает/разблокируется.
        self._finish_proc()
        self._hide_proc_chip()
        self.unsetCursor()
        self._set_status(status_html('fa5s.ban', "Отменено пользователем.", '#f9e2af'))
        self._refresh_enabled()

    def _on_progress(self, done, total):
        # Отменено — чип уже скрыт в _cancel_proc, поздний прогресс игнорируем.
        if getattr(self, "_cancelling", False):
            return
        # LaMa с НЕСКОЛЬКИМИ областями: показываем РЕАЛЬНЫЙ прогресс по областям —
        # переключаем чип в детерминированный «режим областей».
        chip = getattr(self, "_proc_chip", None)
        if total > 1:
            self._proc_region_mode = True
            if chip is not None and chip.isVisible():
                self._proc_bar.setRange(0, 1000)
                self._proc_bar.setValue(int(min(done + 1, total) / total * 1000))
                self._proc_status_text = f"Удаляю {min(done + 1, total)}/{total}"
                elapsed = int(max(0.0, time.monotonic() - self._proc_start))
                self._proc_lbl.setText(f"{self._proc_status_text} · {elapsed} с")
            self._set_status(status_html('fa5s.spinner',
                             f"Обработка области {min(done + 1, total)} из {total}…",
                             '#89b4fa'))

    def _on_done(self, result):
        # Пользователь отменил, пока шёл инференс, — результат уже не нужен (UI
        # приведён в «Отменено» в _cancel_proc). Прибираемся и выходим, НЕ применяя
        # результат (иначе объект «удалялся» вопреки отмене — «не останавливает»).
        if getattr(self, "_cancelling", False):
            self._cancelling = False
            self._worker = None
            self._hide_proc_chip()
            self.unsetCursor()
            self._refresh_enabled()
            return
        # apply_result сам пушит историю; мы уже сохранили состояние до запуска,
        # поэтому применяем без повторного пуша.
        self.canvas.img_bgr = _np.ascontiguousarray(result)
        self.canvas._overlay.fill(0)
        self.canvas._has_strokes = False
        self.canvas._rebuild_base()
        self.canvas.update()
        self._finish_proc()
        self._hide_proc_chip()
        self.unsetCursor()
        self._device = self._inpainter.device_label
        self.lbl_device.setText(f"Устройство: {self._device}")
        self._set_status(status_html('fa5s.check-circle',
                         "Готово! Объект удалён.", '#a6e3a1'))
        self._worker = None
        self._refresh_enabled()
        try: play_done_sound()
        except Exception: pass

    def _on_failed(self, err):
        self._hide_proc_chip()
        self.unsetCursor()
        self._worker = None
        self._refresh_enabled()
        if getattr(self, "_cancelling", False):
            self._cancelling = False
            self._set_status(status_html('fa5s.ban', "Отменено пользователем.", '#f9e2af'))
            return
        self._set_status(status_html('fa5s.times-circle', f"Ошибка: {err}", '#f38ba8'))
        msgbox_warning(self, "Ошибка обработки", str(err))

    # ── Удаление фона (RMBG-2.0) ─────────────────────────────────────────────
    def _remove_bg(self):
        self._touch()
        if not self.canvas.has_image():
            return
        if not _HAS_RMBG or self._remover is None:
            msgbox_warning(
                self, "Удаление фона недоступно",
                "Нужна модель models/model_uint8.onnx и пакет onnxruntime.\n\n"
                "Установка onnxruntime:  pip install onnxruntime")
            return
        if (self._worker is not None and self._worker.isRunning()) or \
           (self._bg_worker is not None and self._bg_worker.isRunning()):
            return
        self._cancelling = False        # новый запуск — снимаем возможный флаг отмены
        # Вжигаем плавающий слой и мазки кисти, снимок «до» — для Ctrl+Z.
        self.canvas.commit_pending()
        # Незавершённое кадрирование применяем перед удалением фона (иначе рамка
        # кадрирования пропадала, а фон убирался с полного изображения).
        if self.canvas.has_crop():
            self.canvas.apply_crop()
        self.canvas._push_history()
        self.canvas.bake_paint()
        img = self.canvas.img_bgr
        self._set_status(status_html(
            'fa5s.spinner',
            "Удаляю фон нейросетью… (первый запуск дольше — грузится модель ~360 МБ)",
            '#89b4fa'))
        self.setCursor(Qt.CursorShape.WaitCursor)
        self._show_proc_chip(None, label="Удаляю фон…", icon='fa5s.cut')
        self._bg_worker = BgRemoveWorker(self._remover, img)
        self._bg_worker.done.connect(self._on_bg_done)
        self._bg_worker.failed.connect(self._on_bg_failed)
        self._bg_worker.start()
        self._refresh_enabled()

    def _on_bg_done(self, alpha):
        # Отменено во время инференса — фон уже не убираем (UI в «Отменено»).
        if getattr(self, "_cancelling", False):
            self._cancelling = False
            self._bg_worker = None
            self._hide_proc_chip()
            self.unsetCursor()
            self._refresh_enabled()
            return
        # Историю уже сохранили перед запуском — применяем без повторного пуша.
        self.canvas.apply_cutout(alpha)
        self._finish_proc()
        self._hide_proc_chip()
        self.unsetCursor()
        try:
            self._device = self._remover.device_label
            self.lbl_device.setText(f"Устройство: {self._device}")
        except Exception:
            pass
        self._set_status(status_html('fa5s.check-circle',
                         "Готово! Фон удалён — сохраняйте в PNG.", '#a6e3a1'))
        self._bg_worker = None
        self._refresh_enabled()
        try: play_done_sound()
        except Exception: pass

    def _on_bg_failed(self, err):
        self._hide_proc_chip()
        self.unsetCursor()
        self._bg_worker = None
        self._refresh_enabled()
        if getattr(self, "_cancelling", False):
            self._cancelling = False
            self._set_status(status_html('fa5s.ban', "Отменено пользователем.", '#f9e2af'))
            return
        self._set_status(status_html('fa5s.times-circle', f"Ошибка: {err}", '#f38ba8'))
        msgbox_warning(self, "Ошибка удаления фона", str(err))



class _PhotoModeSwitch(QWidget):
    """Сегментный переключатель режима вкладки «Редактирование фото»
    (Редактирование фото / Объединить фото). Живёт в ЛЕВОЙ панели каждой
    подвкладки вместо верхней полосы вкладок.

    Обе кнопки имеют ОДИНАКОВУЮ фиксированную ширину (по самой длинной подписи),
    поэтому переключатель выглядит идентично в обоих режимах, а длинные подписи
    видны целиком. Порядок: сперва «Редактирование фото», затем «Объединить фото»."""

    def __init__(self, on_pick):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        self.btn_inpaint = _icon_btn("Редактирование фото", 'fa5s.magic', size=16)
        self.btn_merge = _icon_btn("Объединить фото", 'fa5s.object-group', size=16)
        # Одинаковая ширина обеих кнопок = ширина по самой длинной подписи
        # (+значок, отступы, рамка), чтобы текст не обрезался и режимы выглядели
        # одинаково. Меряем ЖИРНЫМ шрифтом: активная кнопка делает текст жирным,
        # и по обычным метрикам ширины не хватало — подпись обрезалась.
        fb = QFont(self.btn_inpaint.font()); fb.setBold(True)
        fmb = QFontMetrics(fb)
        need = max(fmb.horizontalAdvance(self.btn_inpaint.text()),
                   fmb.horizontalAdvance(self.btn_merge.text()))
        # значок(16) + отступ значок-текст + горизонтальные паддинги/рамка + запас.
        # +56 ≈ естественная ширина по sizeHint с поправкой на жирный шрифт (раньше
        # стоял избыточный +78 — панель была шире, чем нужно).
        btn_w = need + 56
        for b in (self.btn_inpaint, self.btn_merge):
            b.setCheckable(True)
            b.setFixedWidth(btn_w)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            lay.addWidget(b)
        lay.addStretch(1)
        self.btn_inpaint.clicked.connect(lambda: on_pick(1))
        self.btn_merge.clicked.connect(lambda: on_pick(0))
        # Сколько места нужно левой панели, чтобы переключатель влез целиком.
        self.needed_width = btn_w * 2 + 6

    def set_index(self, idx):
        self.btn_merge.setChecked(idx == 0)
        self.btn_inpaint.setChecked(idx == 1)



class PhotoTab(QWidget):
    """Контейнер вкладки «Фото» с подвкладками: объединение фото и удаление
    объектов (LaMa). Переключение между ними — не верхней полосой вкладок, а
    сегментным переключателем в ЛЕВОЙ панели каждой подвкладки. По умолчанию
    открывается «Удаление объектов». Сохраняет старое поведение: add_paths/
    file routing идут в подвкладку объединения."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.inner = QTabWidget()
        self.merger = PhotoMergerTab(main_window)
        self.inpaint = InpaintTab(main_window)
        # Индексы: 0 — объединение, 1 — редактирование фото (LaMa/кадрирование).
        self.inner.addTab(self.merger, get_icon('fa5s.object-group'), "Объединить фото")
        self.inner.addTab(self.inpaint, get_icon('fa5s.magic'), "Редактирование фото")
        self.inner.tabBar().hide()           # переключаем из левой панели, не сверху
        lay.addWidget(self.inner)

        # Переключатель режима — в левой панели каждой подвкладки.
        self._switches = []
        sw_merge = _PhotoModeSwitch(self._set_mode)
        self.merger.insert_mode_switch(sw_merge); self._switches.append(sw_merge)
        if hasattr(self.inpaint, "insert_mode_switch"):
            sw_inp = _PhotoModeSwitch(self._set_mode)
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

    def show_inpaint(self):
        self._set_mode(1)


