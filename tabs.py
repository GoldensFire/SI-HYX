# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# tabs.py — вкладки интерфейса
import time
from config import *
from utils import *
from widgets import *
from workers import *
from PyQt6.QtWidgets import (QSizePolicy, QButtonGroup, QTabWidget,
                             QColorDialog, QStyleOptionSlider, QScrollBar,
                             QFontComboBox)
from PyQt6.QtGui import QPainterPath

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


def _icon_btn(text, icon, size=20, color=None):
    """QPushButton с векторной иконкой qtawesome (см. get_icon в config.py).
    color=None → мягкий светлый значок (для тёмных кнопок). На светлой заливке
    (b_run/b_stop) передавайте тёмный цвет (#1e1e2e), чтобы значок не «выцветал»."""
    b = QPushButton(text)
    b.setIcon(get_icon(icon) if color is None else get_icon(icon, color))
    b.setIconSize(QSize(size, size))
    return b


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


class YtdlpTab(QWidget):
    thumb_sig = pyqtSignal(str, QIcon)
    kodik_info_sig = pyqtSignal(object, int, str, int)  # (озвучки, число серий, тек.озвучка, тек.серия)
    def __init__(self, main_win):
        super().__init__()
        self.main = main_win
        self.items = {}
        self.pool = QThreadPool()
        self.active_workers: dict = {}  # iid → YtdlpWorker, O(1) поиск
        self._dl_pct: dict = {}         # iid → последний % загрузки (для прогресса в таскбаре)
        self._kodik_last_url = ""       # для какой ссылки уже подгружены списки

        self.fetch_timer = QTimer()
        self.fetch_timer.setSingleShot(True)
        self.fetch_timer.setInterval(800)
        self.fetch_timer.timeout.connect(self._start_fetch)
        self.info_worker = None
        self._url_start_s = None    # тайминг из ?t=/&t= ссылки (None — не задан)
        self.setup_ui()
        self.kodik_info_sig.connect(self._populate_kodik)

    def setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6); root.setSpacing(8)
        # ЛЕВО — добавление ссылки + список результатов (как очередь в 1-й вкладке)
        left_w = QWidget(); left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0); left.setSpacing(6)
        # ПРАВО — все настройки в прокручиваемой панели
        right_scroll = QScrollArea(); right_scroll.setWidgetResizable(True)
        right_scroll.setFixedWidth(460)                       # всегда полноразмерно, как в 1-й вкладке
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # AsNeeded (не Off) — страховка: если контент чуть шире, он остаётся
        # доступным прокруткой, а не обрезается. После ужатия строк ниже
        # полоса в норме не появляется.
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_w.setMinimumWidth(140)
        right_w = QWidget(); layout = QVBoxLayout(right_w)
        layout.setContentsMargins(6, 4, 6, 4); layout.setSpacing(8)
        right_scroll.setWidget(right_w)
        root.addWidget(left_w, 1); root.addWidget(right_scroll, 0)
        grp = QGroupBox("Источник"); fl = QFormLayout()
        fl.setSpacing(6)
        
        self.url_edit = QLineEdit(); self.url_edit.setPlaceholderText("Вставьте ссылку.")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.url_edit.customContextMenuRequested.connect(self.on_url_ctx)
        
        # Отдельной кнопки «Проверить ссылку» нет — длительность/инфо и списки
        # Kodik подтягиваются автоматически при вставке/изменении ссылки.
        self.url_edit.textChanged.connect(self._on_url_edited)

        h = QHBoxLayout()
        btn_v = _icon_btn("Скачать", 'fa5s.download'); btn_v.clicked.connect(lambda: self.add_dl(False))
        btn_a = _icon_btn("Скачать (аудио)", 'fa5s.music'); btn_a.clicked.connect(lambda: self.add_dl(True))
        self.btn_stop = _icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e'); self.btn_stop.setObjectName("b_stop")
        self.btn_stop.clicked.connect(self.stop_all_dl)
        self.btn_stop.setEnabled(False)   # активна только при активных загрузках
        
        h.addWidget(self.url_edit); h.addWidget(btn_v); h.addWidget(btn_a); h.addWidget(self.btn_stop)
        
        self.out = QLineEdit(default_download_dir())
        btn_p = _icon_btn("", 'fa5s.folder-open'); btn_p.clicked.connect(self.ch_dir); btn_p.setFixedWidth(36)
        ho = QHBoxLayout(); ho.addWidget(self.out); ho.addWidget(btn_p)

        self.cookie_edit = QLineEdit(); self.cookie_edit.setPlaceholderText("Путь к файлу cookies.txt (необязательно)")
        self.cookie_edit.setClearButtonEnabled(True)
        btn_ck = _icon_btn("", 'fa5s.folder-open'); btn_ck.setFixedWidth(36)
        btn_ck.clicked.connect(self._choose_cookie)
        ho_ck = QHBoxLayout(); ho_ck.addWidget(self.cookie_edit); ho_ck.addWidget(btn_ck)

        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("http://host:port")
        self.proxy_edit.setClearButtonEnabled(True)
        ho_px = QHBoxLayout(); ho_px.addWidget(self.proxy_edit)

        # Аниме-сайты с плеером Kodik (animego и т.п.): выбор серии и озвучки.
        # Списки заполняются автоматически после вставки ссылки. Только выбор.
        self.kodik_ep = QComboBox()
        self.kodik_ep.addItem("—")              # пока ссылка не вставлена
        self.kodik_ep.setFixedWidth(64)
        self.kodik_trans = QComboBox()
        self.kodik_trans.addItem("—")
        # узкие min/max + короткие подписи — длинные названия озвучек не
        # распирают правую панель (в выпадающем списке текст эллипсизируется).
        self.kodik_trans.setMinimumWidth(90)
        self.kodik_trans.setMaximumWidth(128)
        # та же высота, что у строк выше — иначе ряд Kodik «выпадает» из ритма
        # и отступ от Прокси выглядит неровным.
        self.kodik_ep.setFixedHeight(26); self.kodik_trans.setFixedHeight(26)
        ho_kd = QHBoxLayout(); ho_kd.setSpacing(4)
        ho_kd.addWidget(QLabel("Сер.:")); ho_kd.addWidget(self.kodik_ep)
        ho_kd.addWidget(QLabel("Озв.:")); ho_kd.addWidget(self.kodik_trans)
        ho_kd.addStretch()

        # URL + кнопки скачивания — слева (это «добавление»)
        left.addWidget(QLabel("Ссылка для скачивания:"))
        left.addLayout(h)
        fl.addRow(label_with_info("Папка:", "Папка, куда сохраняются скачанные видео и аудио. "
                                  ), ho)
        fl.addRow(label_with_info("Cookies:", "Файл cookies.txt для приватных/возрастных видео. Получите файл cookies через любое расширение браузера и выберите к нему путь. В ином случае, половина видео может не скачиваться"), ho_ck)
        fl.addRow(label_with_info("Прокси:", "Прокси для скачивания (yt-dlp). Помогает при блокировке YouTube провайдером. "
                                  "Браузерный VPN тут не работает — нужен именно прокси. Примеры: http://127.0.0.1:8080, socks5://127.0.0.1:1080"), ho_px)
        fl.addRow(label_with_info("Kodik:", "Для сайтов с плеером Kodik (animego и т.п.): номер серии и название озвучки. "
                                  "После вставки ссылки списки заполняются автоматически, в лог выводится число серий и доступные озвучки. "
                                  "Примечание: 1080p на таких сайтах обычно апскейл, реальный максимум — 720p."), ho_kd)
        # Поля Папка/Cookies/Прокси — компактнее по высоте
        for _w in (self.out, btn_p, self.cookie_edit, btn_ck, self.proxy_edit):
            _w.setFixedHeight(26)
        fl.setVerticalSpacing(4)
        grp.setLayout(fl); layout.addWidget(grp)

        opt = QGroupBox("Опции"); ho = QHBoxLayout()
        self.c_q = QComboBox(); self.c_q.addItems(list(FORMAT_OPTIONS.keys())); self.c_q.setCurrentText("1080p")
        self.c_c = QComboBox(); self.c_c.addItems(MERGE_OPTIONS)
        # Списки субтитров/языка пусты, пока не добавлено видео. Заполняются
        # реально доступными дорожками после пробы метаданных (см.
        # _on_info_success/_populate_lang_combos). Так в них не висят ru/en/…,
        # когда видео ещё не добавлено или других дорожек у него нет.
        self.c_s = QComboBox()
        self.c_a = QComboBox()
        # компактные комбобоксы опций — чтобы ряд Кач./Конт. не распирал панель
        self.c_q.setMaximumWidth(96); self.c_c.setMaximumWidth(72)
        self.c_s.setMaximumWidth(84); self.c_a.setMaximumWidth(120)
        self.chk_k = QCheckBox("Force KF")
        ho.addWidget(QLabel("Кач.:")); ho.addWidget(self.c_q)
        ho.addWidget(info_badge("Максимальная высота видео. Качается лучшее видео до выбранной высоты + лучшее аудио, затем склейка."))
        ho.addWidget(QLabel("Конт.:")); ho.addWidget(self.c_c)
        ho.addWidget(info_badge("Контейнер для склейки: mp4 — макс. совместимость, mkv — SiQuester не поддерживает, webm — для VP9/Opus."))
        ho.addStretch()
        # Субтитры и язык — отдельной строкой
        ho_sl = QHBoxLayout()
        ho_sl.addWidget(QLabel("Суб.:")); ho_sl.addWidget(self.c_s)
        ho_sl.addWidget(info_badge("Скачивать субтитры выбранного языка. all — все доступные дорожки субтитров."))
        ho_sl.addWidget(QLabel("Язык:")); ho_sl.addWidget(self.c_a)
        ho_sl.addWidget(info_badge("Предпочитаемая аудиодорожка — для видео с несколькими озвучками."))
        ho_sl.addStretch()
        # Force KF — отдельной строкой (в ряд с Кач-во/Конт. не помещается).
        ho_kf = QHBoxLayout()
        ho_kf.addWidget(self.chk_k)
        ho_kf.addWidget(info_badge("Force KF — точная нарезка по таймингам: вставляет ключевые кадры в точках реза. Точнее, но медленнее(понятия не имею, зачем оно)"))
        ho_kf.addStretch()
        v = QVBoxLayout(); v.addLayout(ho); v.addLayout(ho_sl); v.addLayout(ho_kf)

        ht = QVBoxLayout()
        start_box = QHBoxLayout(); start_box.setSpacing(2)
        self.ts = [ZeroSpinBox() for _ in range(3)]
        for s in self.ts:
            s.setRange(0,59); s.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons); s.setFixedWidth(34)
            s.valueChanged.connect(self._spin_to_sliders)
        start_box.addWidget(QLabel("С:"))
        for w in self.ts: start_box.addWidget(w)

        end_box = QHBoxLayout(); end_box.setSpacing(2)
        self.te = [ZeroSpinBox() for _ in range(3)]
        for s in self.te:
            s.setRange(0,59); s.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons); s.setFixedWidth(34)
            s.valueChanged.connect(self._spin_to_sliders)
        end_box.addWidget(QLabel("По:"))
        for w in self.te: end_box.addWidget(w)

        btn_clear_time = _icon_btn("", 'fa5s.times')
        # Равная высота с полями-циферками слева (С: / По:), чтобы стоять с ними в одну строку
        btn_clear_time.setFixedHeight(self.ts[0].sizeHint().height())
        btn_clear_time.setFixedWidth(40)
        btn_clear_time.setToolTip("Сбросить тайминги")
        btn_clear_time.clicked.connect(self._clear_timings)

        sliders_box = QVBoxLayout()
        # _JumpSlider — клик по дорожке сразу ставит ползунок в точку клика
        # (а не «ползёт» на pageStep). Двигать можно и кликом, и протаскиванием.
        self.slider_start = _JumpSlider(Qt.Orientation.Horizontal)
        self.slider_end = _JumpSlider(Qt.Orientation.Horizontal)
        self.slider_start.setRange(0, 36000); self.slider_end.setRange(0, 36000)
        self.slider_start.valueChanged.connect(self._slider_to_spins)
        self.slider_end.valueChanged.connect(self._slider_to_spins)

        _time_lbl = QHBoxLayout()
        _time_lbl.addWidget(QLabel("Обрезка:"))
        _time_lbl.addWidget(info_badge("Обрезка: качается только отрезок от Start до End. Пусто = всё видео. Точность нарезки зависит от Force KF."))
        _time_lbl.addStretch()
        sliders_box.addLayout(_time_lbl)
        sliders_box.addWidget(self.slider_start); sliders_box.addWidget(self.slider_end)

        # Быстрые кнопки длины отрезка: ставят ползунок «По» на +N от ползунка «С».
        # Удобно, когда нужен ровный кусок фиксированной длины от выбранной точки.
        dur_box = QHBoxLayout(); dur_box.setSpacing(4)
        dur_box.addWidget(QLabel("Длина:"))
        for _lbl, _sec in (("+30с", 30), ("+1 мин", 60), ("+3 мин", 180), ("+5 мин", 300)):
            _b = QPushButton(_lbl)
            _b.setToolTip(f"Поставить «По» на +{_lbl.lstrip('+')} от ползунка «С»")
            _b.clicked.connect(lambda _=False, s=_sec: self._add_duration(s))
            dur_box.addWidget(_b)
        dur_box.addStretch()
        sliders_box.addLayout(dur_box)

        # Спинбоксы С:/По: + Сбросить — одной строкой; ползунки — ниже (чтобы
        # всё влезало в фиксированную ширину правой панели, как в 1-й вкладке).
        ht_top = QHBoxLayout()
        ht_top.addLayout(start_box); ht_top.addSpacing(8); ht_top.addLayout(end_box); ht_top.addSpacing(8)
        ht_top.addWidget(btn_clear_time, 0, Qt.AlignmentFlag.AlignVCenter); ht_top.addStretch()
        ht.addLayout(ht_top); ht.addLayout(sliders_box)
        v.setSpacing(10)
        v.addLayout(ht); opt.setLayout(v); layout.addWidget(opt)
        layout.addStretch()

        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["URL", "Размер", "Инфо", "Статус"])
        self.tree.setColumnWidth(0, 380); self.tree.setColumnWidth(3, 100)
        self.tree.setIconSize(QSize(160,90)); self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # Список плоский (вложенности нет) — убираем отступ-«ветку» и стрелку
        # раскрытия слева, из-за которых у строк появлялась пустая область слева.
        self.tree.setIndentation(0); self.tree.setRootIsDecorated(False)
        # Цветовая подсветка строк по статусу (синий — качается, зелёный — готово,
        # красный — ошибка) + видимое выделение при клике — как на странице обработки.
        self.tree.setItemDelegate(StatusColorDelegate(self.tree))
        self.tree.customContextMenuRequested.connect(self.ctx)
        left.addWidget(self.tree, 1)
        # Клавиша Delete — удалить выделенные загрузки из списка
        self._sc_delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree)
        self._sc_delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_delete.activated.connect(self.delete_sel)

        hb = QHBoxLayout()
        b_del = _icon_btn("Удалить", 'fa5s.times'); b_del.clicked.connect(self.delete_sel)
        b_clr = _icon_btn("Очистить", 'fa5s.trash'); b_clr.clicked.connect(self.tree.clear)
        hb.addWidget(b_del); hb.addWidget(b_clr); hb.addStretch(); left.addLayout(hb)

    def _spin_to_sliders(self):
        try:
            start_s = self.ts[0].value()*3600 + self.ts[1].value()*60 + self.ts[2].value()
            end_s = self.te[0].value()*3600 + self.te[1].value()*60 + self.te[2].value()
            maxv = max(self.slider_start.maximum(), 1)
            start_s = max(0, min(start_s, maxv))
            end_s = max(0, min(end_s, self.slider_end.maximum()))
            if end_s < start_s: end_s = start_s
            self.slider_start.blockSignals(True); self.slider_end.blockSignals(True)
            self.slider_start.setValue(start_s); self.slider_end.setValue(end_s)
            self.slider_start.blockSignals(False); self.slider_end.blockSignals(False)
        except Exception: pass

    def _add_duration(self, seconds):
        """Ставит ползунок «По» на +seconds от текущего ползунка «С»
        (кнопки быстрой длины отрезка). Спинбоксы обновятся через сигнал."""
        try:
            start_s = self.slider_start.value()
            end_s = min(start_s + seconds, self.slider_end.maximum())
            self.slider_end.setValue(end_s)
        except Exception: pass

    def _fill_time_boxes(self, sec, boxes):
        """Заполняет три спинбокса (ч, м, с) из значения в секундах."""
        h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
        for box in boxes: box.blockSignals(True)
        boxes[0].setValue(h); boxes[1].setValue(m); boxes[2].setValue(s)
        for box in boxes: box.blockSignals(False)

    def _slider_to_spins(self):
        try:
            start_s = self.slider_start.value()
            end_s = self.slider_end.value()
            if end_s < start_s:
                end_s = start_s
                self.slider_end.blockSignals(True); self.slider_end.setValue(end_s); self.slider_end.blockSignals(False)
            self._fill_time_boxes(start_s, self.ts)
            self._fill_time_boxes(end_s, self.te)
        except Exception: pass

    def _on_url_edited(self):
        self.fetch_timer.start()
        # Ссылка вида youtu.be/xxx?t=9182 — сразу выставляем «С:» на этот тайминг
        # (не дожидаясь ответа InfoWorker с длительностью).
        url = self.url_edit.text().strip()
        ts = parse_youtube_start_seconds(url) if url else None
        self._url_start_s = ts
        if ts is not None:
            if ts > self.slider_start.maximum():
                self.slider_start.setRange(0, ts)
                if self.slider_end.maximum() < ts:
                    self.slider_end.setRange(0, ts)
            self.slider_start.setValue(ts)
            if self.slider_end.value() < ts:
                self.slider_end.setValue(self.slider_end.maximum())
            self.main.log(f"Ссылка содержит тайминг: качаю с {ts} сек.")

    def _start_fetch(self):
        url = self.url_edit.text().strip()
        if not url: return
        self.main.log(f"Запрос метаданных для: {url[:30]}...")

        # Для Kodik-сайтов (animego и т.п.) — подгружаем списки озвучек и серий
        # в выпадашки (один раз на ссылку).
        if is_embed_candidate(url) and url != self._kodik_last_url:
            self._kodik_last_url = url
            def _kinfo(u=url, px=self.proxy_edit.text().strip()):
                try:
                    info = kodik_get_info(u, proxy=px)
                    tr = info.get("translations") or []
                    if tr:
                        self.kodik_info_sig.emit(
                            tr, int(info.get("episodes", 0)),
                            info.get("cur_translation", "") or "",
                            int(info.get("cur_episode", 0) or 0))
                except Exception:
                    pass
            threading.Thread(target=_kinfo, daemon=True).start()
        # Отменяем предыдущий воркер через флаг — НЕ terminate(), он вызывает сегфолт в PyQt6
        if self.info_worker and self.info_worker.isRunning():
            self.info_worker.cancelled = True
            # Отключаем сигналы старого воркера чтобы не получить stale callback
            try: self.info_worker.success.disconnect()
            except Exception: pass
            try: self.info_worker.error.disconnect()
            except Exception: pass
            # Не ждём завершения — пусть доработает в фоне и тихо умрёт
        self.info_worker = InfoWorker(url, proxy=self.proxy_edit.text().strip())
        self.info_worker.success.connect(self._on_info_success)
        self.info_worker.error.connect(self._on_info_error)
        self.info_worker.start()

    def _kodik_episode_value(self):
        """Номер выбранной серии (int) или None, если список ещё не заполнен."""
        txt = self.kodik_ep.currentText().strip()
        return int(txt) if txt.isdigit() else None

    def _populate_kodik(self, translations, episodes, cur_translation, cur_episode):
        """Заполняет выпадашки серий и озвучек (только выбор, не ввод).
        По умолчанию выбирает то, что отмечено в плеере; иначе — первый пункт."""
        try:
            self.kodik_trans.blockSignals(True)
            self.kodik_trans.clear()
            for t in translations:
                self.kodik_trans.addItem(t)
            idx = self.kodik_trans.findText(cur_translation) if cur_translation else -1
            self.kodik_trans.setCurrentIndex(idx if idx >= 0 else 0)
            self.kodik_trans.blockSignals(False)

            self.kodik_ep.blockSignals(True)
            self.kodik_ep.clear()
            for i in range(1, int(episodes) + 1):
                self.kodik_ep.addItem(str(i))
            if episodes <= 0:
                self.kodik_ep.addItem("—")
            ep_idx = self.kodik_ep.findText(str(cur_episode)) if cur_episode else -1
            self.kodik_ep.setCurrentIndex(ep_idx if ep_idx >= 0 else 0)
            self.kodik_ep.blockSignals(False)

            self.main.log(f"Kodik: озвучек {len(translations)}, серий {episodes}. "
                          f"Выбрано: серия {self.kodik_ep.currentText()}, "
                          f"озвучка «{self.kodik_trans.currentText()}».")
        except Exception as e:
            self.main.log(f"_populate_kodik error: {e}")

    def _on_info_success(self, duration, thumb_url, sub_langs=None, audio_langs=None):
        self.main.log(f"Длительность получена: {duration} сек.")
        try:
            if duration > 0:
                self.slider_start.setRange(0, duration); self.slider_end.setRange(0, duration)
                start_val = min(self._url_start_s, duration) if self._url_start_s else 0
                self.slider_start.setValue(start_val); self.slider_end.setValue(duration)
                self._slider_to_spins()
        except Exception: pass
        try:
            self._populate_lang_combos(sub_langs or [], audio_langs or [])
        except Exception: pass

    def _populate_lang_combos(self, sub_langs, audio_langs):
        """Заполняет «Суб.» и «Язык» реально доступными дорожками видео.
        Субтитры показываем, только если они есть; «Язык» — только если у видео
        больше одной аудиодорожки (иначе выбирать нечего → список пуст)."""
        # Субтитры
        cur_s = self.c_s.currentText()
        self.c_s.blockSignals(True); self.c_s.clear()
        if sub_langs:
            items = ["Выкл", "all"] + list(sub_langs)
            self.c_s.addItems(items)
            if cur_s in items:
                self.c_s.setCurrentText(cur_s)
        self.c_s.blockSignals(False)
        # Язык (аудиодорожка)
        cur_a = self.c_a.currentText()
        self.c_a.blockSignals(True); self.c_a.clear()
        if len(audio_langs) > 1:
            items = ["Original"] + list(audio_langs)
            self.c_a.addItems(items)
            if cur_a in items:
                self.c_a.setCurrentText(cur_a)
        self.c_a.blockSignals(False)

    def _on_info_error(self, err_msg):
        self.main.log(f"[Ошибка метаданных] {err_msg}")

    def _clear_timings(self):
        self._url_start_s = None
        for box in self.ts + self.te:
            box.blockSignals(True); box.setValue(0); box.blockSignals(False)
        self.slider_start.blockSignals(True); self.slider_start.setValue(0); self.slider_start.blockSignals(False)
        self.slider_end.blockSignals(True);   self.slider_end.setValue(self.slider_end.maximum()); self.slider_end.blockSignals(False)

    def on_url_ctx(self, pos):
        m = QMenu()
        try: cb = QApplication.clipboard().text().strip()
        except Exception: cb = ""
        if cb and cb.startswith("http"):
            a = QAction("Скачать из буфера", self)
            a.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(False)))
            a2 = QAction("Скачать аудио из буфера", self)
            a2.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(True)))
            m.addAction(a); m.addAction(a2); m.addSeparator()
        m.addAction(QAction("Вставить", self, triggered=self.url_edit.paste))
        m.exec(self.url_edit.mapToGlobal(pos))

    def stop_all_dl(self):
        for w in list(self.active_workers.values()):
            try: w.stop()
            except Exception: pass

    def stop_sel_dl(self):
        for it in self.tree.selectedItems():
            iid = it.data(0, Qt.ItemDataRole.UserRole)
            w = self.active_workers.get(iid)
            if w:
                try: w.stop()
                except Exception: pass

    def ctx(self, pos):
        m = QMenu()
        sel = self.tree.itemAt(pos)
        if sel:
            m.addAction(QAction("Перейти к URL (копировать в буфер)", self, triggered=lambda checked=False, it=sel: QApplication.clipboard().setText(it.text(0))))
            m.addAction(QAction(get_icon('fa5s.redo'), "Скачать заново", self, triggered=self.redownload_sel))
            m.addAction(QAction("Остановить загрузку", self, triggered=self.stop_sel_dl))
            m.addSeparator()
        try: cb = QApplication.clipboard().text().strip()
        except Exception: cb = ""
        if cb and cb.startswith('http'):
            a_cb = QAction('Скачать из буфера', self); 
            a_cb.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(False)))
            a_cba = QAction('Скачать аудио из буфера', self); 
            a_cba.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.add_dl(True)))
            m.addAction(a_cb); m.addAction(a_cba); m.addSeparator()
        m.addAction(QAction('Удалить', self, triggered=self.delete_sel))
        m.addAction(QAction('Очистить', self, triggered=self.tree.clear))
        m.exec(self.tree.mapToGlobal(pos))

    def _choose_cookie(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл cookies", "", "Text files (*.txt);;All files (*)")
        if path:
            self.cookie_edit.setText(path)

    def ch_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка", self.out.text())
        if d:
            self.out.setText(d)
            try: self.main.recent_strip.refresh(d)
            except Exception: pass

    def get_sec(self, arr):
        return arr[0].value()*3600 + arr[1].value()*60 + arr[2].value()

    def _connect_worker_signals(self, w: 'YtdlpWorker', iid: str):
        """Подключает стандартные сигналы воркера к обработчикам дерева."""
        def on_prog(iid_, p, t):
            # Опоздавший тик уже завершённого воркера (его watchdog мог эмитнуть
            # «Скачивание…» в момент гибели процесса) не должен воскрешать строку
            # и индикатор в панели задач после ошибки/остановки.
            if iid_ not in self.active_workers:
                return
            item = self.items.get(iid_, {}).get('item')
            if item:
                # p <= 0 — индикатор активности без реального % (подготовка/повторы
                # извлечения/тихий ffmpeg); реальный процент показываем от >0.
                item.setText(1, "…" if p <= 0 else f"{p:.1f}%"); item.setText(3, t)
            self._dl_pct[iid_] = p
            self._update_dl_taskbar()

        def on_done(iid_, status, clean_info, file_path):
            self._dl_pct.pop(iid_, None); self._update_dl_taskbar()
            item = self.items.get(iid_, {}).get('item')
            if item:
                item.setText(3, status)
                # Зелёная подсветка строки — как на странице обработки (делегат
                # StatusColorDelegate рисует фон по статусу из 0-й колонки).
                item.setData(0, ITEM_STATUS_ROLE, 'done')
                self.tree.viewport().update()
                if file_path and os.path.exists(file_path):
                    try:
                        dur, br_str, size, a_br, _a_codec = get_media_info(file_path)
                        item.setText(1, human_size(size))
                        item.setText(2, clean_info if clean_info and clean_info != "Unknown" else br_str)
                        self.main.log(f"Загружено: {file_path} ({human_size(size)}, {a_br})")
                    except Exception: pass

        def on_err(iid_, msg):
            self._dl_pct.pop(iid_, None); self._update_dl_taskbar()
            try:
                item = self.items.get(iid_, {}).get('item')
                if not item: return
                item.setText(3, "Ошибка"); item.setToolTip(3, msg)
                # Красная подсветка строки — как на странице обработки.
                item.setData(0, ITEM_STATUS_ROLE, 'err')
                self.tree.viewport().update()
            except RuntimeError:
                pass  # QTreeWidgetItem уже удалён пользователем

        def on_thumb(iid_, thumb_url):
            if thumb_url:
                self.pool.start(RemoteThumbnailRunnable(thumb_url, iid_, self.thumb_sig))

        w.progress_sig.connect(on_prog); w.finished_sig.connect(on_done)
        w.error_sig.connect(on_err); w.thumb_sig.connect(on_thumb)
        w.log_sig.connect(lambda m: self.main.log(str(m)))

    def add_dl_direct(self, url: str, audio_only: bool = False, outdir: str = ""):
        """Запускает загрузку с готовым URL — не читает поля UI.
        Используется при скачивании с вкладки MediaTab, чтобы элемент
        с прогрессом и миниатюрой появлялся именно здесь.
        """
        try:
            if not url: return
            if not outdir:
                outdir = self.out.text()
            if not outdir or not os.path.exists(outdir):
                outdir = default_download_dir()

            iid = uuid.uuid4().hex
            it = QTreeWidgetItem(self.tree)
            it.setText(0, url); it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
            it.setData(0, Qt.ItemDataRole.UserRole, iid)
            it.setData(0, ITEM_STATUS_ROLE, 'proc')  # синяя подсветка «в работе»
            self.items[iid] = {'item': it, 'url': url, 'audio_only': bool(audio_only)}

            config = {
                'iid': iid, 'url': url,
                'fmt': FORMAT_OPTIONS.get("1080p", 'bestvideo[height<=1080]+bestaudio/best'),
                'outdir': outdir, 'merge': 'mp4', 'sub_lang': 'Выкл',
                'audio': 'Original', 'force_kf': True,
                'audio_only': bool(audio_only),
                'cookie_path': self.cookie_edit.text().strip() if hasattr(self, 'cookie_edit') else '',
                'proxy': self.proxy_edit.text().strip() if hasattr(self, 'proxy_edit') else '',
            }
            w = YtdlpWorker(config)
            self.active_workers[iid] = w
            w.finished.connect(lambda _=None, i=iid: self._remove_worker(i))
            self._connect_worker_signals(w, iid)
            w.start()
            self._update_stop_btn()
            self.main.log(f"Загрузка добавлена: {url}")
        except Exception as e:
            self.main.log(f"add_dl_direct error: {e}")

    def add_dl(self, audio_only=False):
        self.fetch_timer.stop()
        try:
            url = self.url_edit.text().strip()
            self.url_edit.clear()
            if not url: return
            iid = uuid.uuid4().hex
            it = QTreeWidgetItem(self.tree)
            it.setText(0, url); it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
            it.setData(0, Qt.ItemDataRole.UserRole, iid)
            it.setData(0, ITEM_STATUS_ROLE, 'proc')  # синяя подсветка «в работе»
            self.items[iid] = {'item': it, 'url': url, 'audio_only': bool(audio_only)}
            config = self._dl_config(iid, url, audio_only)
            w = YtdlpWorker(config)
            self.active_workers[iid] = w
            w.finished.connect(lambda _=None, i=iid: self._remove_worker(i))
            self._connect_worker_signals(w, iid)
            w.start()
            self._update_stop_btn()
        except Exception as e:
            self.main.log(f"add_dl error: {e}")

    def _update_stop_btn(self):
        """Кнопка СТОП активна только когда есть хотя бы одна активная загрузка."""
        active = bool(self.active_workers)
        try: self.btn_stop.setEnabled(active)
        except Exception: pass
        # Зеркалим состояние на кнопку СТОП в строке «Быстрая загрузка»
        # вкладки «Обработка» — быстрые загрузки идут через этот же пул.
        try: self.main.tab_media.btn_qdl_stop.setEnabled(active)
        except Exception: pass

    def _update_dl_taskbar(self):
        """Сводный прогресс загрузок на иконке в панели задач:
          • есть реальный % (v>0) — средний % (обычный режим);
          • идёт загрузка, но % неизвестен (тихий ffmpeg, v==-1) — бегущая полоса;
          • только подготовка/извлечение (v==0) или активных нет — снять индикатор,
            чтобы падающее извлечение не выглядело как «что-то грузится»."""
        try:
            vals = [v for v in self._dl_pct.values() if v is not None]
            real = [v for v in vals if v > 0]
            if real:
                self.main.set_taskbar_progress(int(sum(real) / len(real)), 100)
            elif any(v < 0 for v in vals):
                self.main.set_taskbar_progress(0, 100)  # 0 → неопределённый режим
            else:
                self.main.clear_taskbar_progress()
        except Exception:
            pass

    def _remove_worker(self, iid):
        self.active_workers.pop(iid, None)
        # Сигнал finished у потока срабатывает ВСЕГДА при его завершении — даже если
        # загрузка упала, не отправив error_sig/finished_sig (тогда в _dl_pct оставался
        # бы «-1», и на иконке в панели задач навсегда зависала «бегущая полоса»
        # загрузки, хотя по факту ошибка). Снимаем элемент из прогресса здесь —
        # это гарантированно убирает индикатор после ошибочной/прерванной загрузки.
        self._dl_pct.pop(iid, None)
        self._update_dl_taskbar()
        self._update_stop_btn()

    def _dl_config(self, iid, url, audio_only):
        """Конфиг загрузки из текущих настроек вкладки. Общий для add_dl и
        перезапуска (redownload), чтобы режимы не расходились."""
        return {
            'iid': iid, 'url': url, 'fmt': FORMAT_OPTIONS.get(self.c_q.currentText(), 'best'),
            'outdir': self.out.text(), 'merge': self.c_c.currentText(), 'sub_lang': self.c_s.currentText(),
            'audio': self.c_a.currentText(), 'force_kf': self.chk_k.isChecked(),
            'start_s': self.get_sec(self.ts) if any(x.value() for x in self.ts) else None,
            'end_s': self.get_sec(self.te) if any(x.value() for x in self.te) else None,
            'audio_only': bool(audio_only),
            'cookie_path': self.cookie_edit.text().strip(),
            'proxy': self.proxy_edit.text().strip(),
            'kodik_episode': self._kodik_episode_value(),
            'kodik_translation': (lambda t: "" if t in ("", "—") else t)(self.kodik_trans.currentText().strip()),
        }

    def redownload_sel(self):
        """Скачать выбранные заново В ТОЙ ЖЕ строке — без дубля в списке.
        Если по элементу ещё идёт воркер, СНАЧАЛА останавливаем его: иначе два
        процесса пишут один и тот же выходной файл и падают с WinError 32
        («файл занят другим процессом», 'X.m4a'->'X.m4a')."""
        for it in list(self.tree.selectedItems()):
            try:
                iid = it.data(0, Qt.ItemDataRole.UserRole)
                entry = self.items.get(iid, {}) if iid else {}
                url = (entry.get('url') if isinstance(entry, dict) else "") or it.text(0)
                if not (url and url.strip().startswith('http')):
                    continue
                url = url.strip()
                audio_only = bool(entry.get('audio_only', False)) if isinstance(entry, dict) else False
                # Гасим прежний воркер этого же элемента (если ещё активен) —
                # не плодим второй процесс на тот же файл.
                old = self.active_workers.pop(iid, None)
                if old:
                    try: old.stop()
                    except Exception: pass
                # Сброс строки в исходное состояние «в очереди»
                it.setText(1, "-"); it.setText(2, "-"); it.setText(3, "В очереди")
                it.setToolTip(3, "")
                it.setData(0, ITEM_STATUS_ROLE, 'proc')
                self.tree.viewport().update()
                self.items[iid] = {'item': it, 'url': url, 'audio_only': audio_only}
                w = YtdlpWorker(self._dl_config(iid, url, audio_only))
                self.active_workers[iid] = w
                w.finished.connect(lambda _=None, i=iid: self._remove_worker(i))
                self._connect_worker_signals(w, iid)
                w.start()
                self._update_stop_btn()
                self.main.log(f"Повторная загрузка: {url}")
            except Exception as e:
                self.main.log(f"redownload error: {e}")

    def delete_sel(self):
        try:
            for it in list(self.tree.selectedItems()):
                iid = it.data(0, Qt.ItemDataRole.UserRole)
                if iid:
                    self.active_workers.pop(iid, None)
                    self.items.pop(iid, None)
                self.tree.invisibleRootItem().removeChild(it)
            self._update_stop_btn()
        except Exception: pass

    def set_thumb(self, iid, icon):
        try:
            entry = self.items.get(iid)
            if entry and isinstance(entry, dict):
                it = entry.get('item')
                if it and isinstance(it, QTreeWidgetItem):
                    it.setIcon(0, icon)
        except Exception: pass


class MediaTab(QWidget):
    thumb_sig = pyqtSignal(str, QIcon)
    media_info_sig = pyqtSignal(str, str, str, float)  # iid, размер, битрейт, длительность(с)
    media_lufs_sig = pyqtSignal(str, object)           # iid, LUFS до (или None)
    def __init__(self, main_win):
        super().__init__()
        self.main = main_win
        self.items = []
        self._item_map: dict = {}
        self._item_data_map: dict = {}
        # iid'ы, удалённые из очереди пользователем — та же живая ссылка
        # передаётся ProcessWorker'у, чтобы он мог прервать УЖЕ идущую обработку
        # конкретного файла, а не только не начинать ещё не стартовавшие.
        self._removed_ids: set = set()
        self.pool = QThreadPool()
        self.export_dir = ""  # пусто = экспортировать рядом с исходником
        self.setAcceptDrops(True)
        # Колонка «Время» (7): сколько длится перекодирование каждого файла.
        # _proc_started: iid → момент старта (time.monotonic); _proc_running —
        # iid'ы, которые сейчас кодируются (таймер тикает их время вверх).
        self._proc_started: dict = {}
        self._proc_running: set = set()
        self._item_pass: dict = {}   # iid → «N/total» текущего прохода подбора картинки
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(500)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        # Пока воркер работает, каждые 500мс подсовываем ему АКТУАЛЬНЫЕ настройки
        # с виджетов (см. _settings_sync_tick) — иначе файл, добавленный в очередь
        # уже во время обработки, кодировался бы с настройками, замороженными в
        # момент нажатия «НАЧАТЬ» (та же проблема, что и с CRF/скоростью/etc.,
        # изменёнными на лету).
        self._settings_sync_timer = QTimer(self)
        self._settings_sync_timer.setInterval(500)
        self._settings_sync_timer.timeout.connect(self._settings_sync_tick)
        self.setup_ui()
        self.thumb_sig.connect(self.set_thumb)
        self.media_info_sig.connect(self._apply_media_info)
        self.media_lufs_sig.connect(self._apply_media_lufs)
        self.worker = None

    def _find_item(self, iid) -> 'QTreeWidgetItem | None':
        """Возвращает QTreeWidgetItem по iid за O(1)."""
        return self._item_map.get(iid)

    def setup_ui(self):
        l = QHBoxLayout(self)
        l.setContentsMargins(6, 6, 6, 6); l.setSpacing(8)
        lw = QWidget(); lv = QVBoxLayout(lw)
        lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(6)

        # Строка быстрой загрузки сделана 1-в-1 как на вкладке «Загрузчик»
        # (YtdlpTab): подпись «Ссылка для скачивания:» над строкой + поле и три
        # кнопки в один ряд, без обрамляющего блока «Быстрая загрузка».
        lv.addWidget(QLabel("Ссылка для скачивания:"))
        qdl_h = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Вставьте ссылку.")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.url_edit.customContextMenuRequested.connect(self.on_url_ctx)

        btn_qdl_video = _icon_btn("Скачать", 'fa5s.download'); btn_qdl_video.clicked.connect(lambda: self.download_url(False))
        btn_qdl_audio = _icon_btn("Скачать (аудио)", 'fa5s.music'); btn_qdl_audio.clicked.connect(lambda: self.download_url(True))
        # Кнопка СТОП — как в строке загрузки на вкладке «Загрузчик» (YtdlpTab):
        # быстрые загрузки идут через тот же воркер-пул вкладки «Загрузчик», поэтому
        # СТОП останавливает их там же. Активна только при активных загрузках —
        # состояние ведёт YtdlpTab._update_stop_btn.
        self.btn_qdl_stop = _icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e')
        self.btn_qdl_stop.setObjectName("b_stop")
        self.btn_qdl_stop.clicked.connect(self._quick_dl_stop)
        self.btn_qdl_stop.setEnabled(False)

        qdl_h.addWidget(self.url_edit); qdl_h.addWidget(btn_qdl_video); qdl_h.addWidget(btn_qdl_audio); qdl_h.addWidget(self.btn_qdl_stop)
        lv.addLayout(qdl_h)

        self.tree = DraggableTreeWidget()
        self.tree.setAcceptDrops(True)
        self.tree.setPlaceholderText(
            "Добавляйте файлы сюда\n\n"
            "Перетащите видео, аудио или изображения в это окно\n"
            "или нажмите «Добавить файлы»")
        self.tree.setHeaderLabels(["Превью", "", "Размер", "Битрейт", "LUFS", "Длительность", "Статус", "Время", "Оценка XPSNR"])
        self.tree.setRootIsDecorated(False)
        self.tree.setItemDelegate(StatusColorDelegate(self.tree))  # цветовая подсветка строк
        # 0-я колонка: миниатюра + имя файла под ней (одной строкой, с многоточием).
        self._preview_delegate = PreviewNameDelegate(self.tree)
        self._preview_delegate.compare_clicked.connect(self._on_compare_clicked)
        self.tree.setItemDelegateForColumn(0, self._preview_delegate)
        self.tree.setIconSize(QSize(160,90)); self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.ctx)
        self.tree.setWordWrap(True)
        # Плавная прокрутка: по умолчанию список «прыгает» на целую строку (а строки
        # тут высокие — с превью 160×90), отчего колесо/скроллбар двигаются рывками.
        # Попиксельный режим прокручивает гладко, а шаг колеса задаём вручную (иначе
        # в попиксельном режиме одно деление колеса = 1 px, и крутить пришлось бы вечно).
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.verticalScrollBar().setSingleStep(24)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(0, 180)
        for i in range(1, 9): self.tree.header().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        # Колонка 1 — только метки «Было/Стало» (имя файла переехало под превью),
        # поэтому ширину отдаём по содержимому (ResizeToContents выше).
        # «Длительность» (5) и «Время» (7) — при ResizeToContents ширину диктует
        # длинное слово в заголовке, а не сам текст ячейки («22.75 с», «01:38»),
        # из-за чего колонки заметно шире содержимого. Фиксируем уже (но оставляем
        # Interactive — можно растянуть руками при необходимости).
        self.tree.header().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(5, 90)
        self.tree.header().setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(7, 78)

        h = QHBoxLayout()
        b1 = _icon_btn("Добавить файлы", 'fa5s.plus'); b1.clicked.connect(self.add)
        b2 = _icon_btn("Удалить", 'fa5s.times'); b2.clicked.connect(self.rem)
        b3 = _icon_btn("Очистить", 'fa5s.trash'); b3.clicked.connect(self.clear)
        for b in (b1, b2, b3): b.setMaximumWidth(120)
        b4 = _icon_btn("", 'fa5s.columns')
        b4.setFixedWidth(36)
        b4.setToolTip("Сравнить любые два файла с диска (картинки или видео)")
        b4.clicked.connect(self._compare_any_files)
        self.btn_export_dir = _icon_btn("", 'fa5s.folder-open')  # выбор папки экспорта
        self.btn_export_dir.setFixedWidth(36)
        self.btn_export_dir.setToolTip("Выбрать папку экспорта. По умолчанию — рядом с исходным файлом.")
        self.btn_export_dir.clicked.connect(self._choose_export_dir)
        self.btn_export_reset = _icon_btn("", 'fa5s.undo')
        self.btn_export_reset.setFixedWidth(36)
        self.btn_export_reset.setToolTip("Сбросить — экспортировать в папку исходника")
        self.btn_export_reset.clicked.connect(self._reset_export_dir)
        self.btn_export_reset.setEnabled(False)
        self.lbl_export_dir = QLabel("По умолчанию экспорт в папку исходника")
        self.lbl_export_dir.setStyleSheet("color:#a6adc8; font-size:11px;")
        h.addWidget(b1); h.addWidget(b2); h.addWidget(b3); h.addWidget(b4); h.addWidget(self.btn_export_dir); h.addWidget(self.btn_export_reset); h.addWidget(self.lbl_export_dir)
        h.addStretch()

        # Левая часть может ужиматься (растяжимая, маленький минимум),
        # чтобы правая панель всегда полностью помещалась по горизонтали.
        lw.setMinimumWidth(140)
        lv.addWidget(self.tree); lv.addLayout(h)
        l.addWidget(lw, 1)

        RIGHT_W = 460  # фиксированная ширина правой панели — всегда видна целиком
        right_container = QWidget(); right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0); right_layout.setSpacing(6)
        right_container.setFixedWidth(RIGHT_W)
        rw = QScrollArea(); rw.setWidgetResizable(True)
        rw.setFrameShape(QFrame.Shape.NoFrame)
        # Горизонтальная скрыта (панель фикс. ширины), вертикальная — по необходимости
        rw.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rw.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        w = QWidget(); rv_inner = QVBoxLayout(w)
        rv_inner.setContentsMargins(6, 4, 6, 4); rv_inner.setSpacing(8)

        ga = QGroupBox("Аудио эффекты"); fa = QFormLayout()
        self.ck_norm = QCheckBox("Loudnorm"); self.ck_norm.setChecked(True)
        self.s_tgt = QDoubleSpinBox(); self.s_tgt.setValue(-20.0); self.s_tgt.setRange(-60.0, 20.0); self.s_tgt.setSingleStep(0.1)
        self.s_lra = QDoubleSpinBox(); self.s_lra.setValue(11.0); self.s_lra.setRange(0.0, 50.0); self.s_lra.setSingleStep(0.1)
        self.s_tp = QDoubleSpinBox(); self.s_tp.setValue(-1.5); self.s_tp.setRange(-60.0, 10.0); self.s_tp.setSingleStep(0.1)
        self.ck_fade = QCheckBox("Затухание (Fade Out)"); self.ck_fade.setChecked(False)
        self.s_fade = QDoubleSpinBox(); self.s_fade.setValue(1.0); self.s_fade.setRange(0.0, 60.0); self.s_fade.setSingleStep(0.1)
        self.s_fade.setMaximumWidth(110)
        self.ck_fade_in = QCheckBox("Нарастание (Fade In)"); self.ck_fade_in.setChecked(False)
        self.s_fade_in = QDoubleSpinBox(); self.s_fade_in.setValue(1.0); self.s_fade_in.setRange(0.0, 60.0); self.s_fade_in.setSingleStep(0.1)
        self.s_fade_in.setMaximumWidth(110)
        self.ck_deg = QCheckBox("Ухудшить звук (Degrade)")
        self.s_hz = QSpinBox(); self.s_hz.setValue(8000); self.s_hz.setRange(1000, 48000)
        self.ck_u8 = QCheckBox("8-bit")
        self.s_lp = QSpinBox(); self.s_lp.setRange(0, 24000); self.s_lp.setValue(3000)
        self.s_hp = QSpinBox(); self.s_hp.setRange(0, 24000); self.s_hp.setValue(200)
        self.s_deg_gain = QDoubleSpinBox(); self.s_deg_gain.setRange(-60, 0); self.s_deg_gain.setValue(0.0)
        for _sb in (self.s_tgt, self.s_lra, self.s_tp):
            _sb.setMaximumWidth(70)
        fa.addRow(row_with_info(self.ck_norm, "Нормализация уровня громкости, рекомендуется все видео/аудио кодировать с этой опцией"))
        hn = QHBoxLayout()
        hn.addWidget(QLabel("LUFS:")); hn.addWidget(self.s_tgt)
        hn.addWidget(QLabel("LRA:")); hn.addWidget(self.s_lra)
        hn.addWidget(QLabel("TP:")); hn.addWidget(self.s_tp)
        hn.addStretch()
        fa.addRow(hn)
        fa.addRow(row_with_info(self.ck_fade_in, "Плавное нарастание звука в начале ролика (секунды)"), self.s_fade_in)
        fa.addRow(row_with_info(self.ck_fade, "Плавное затухание звука в конце ролика в секундах"), self.s_fade)

        # Битрейт аудио — ПЕРЕД секцией degrade
        hbr = QHBoxLayout(); hbr.addWidget(QLabel("Битрейт аудио:"))
        self.c_abitrate = InvertedWheelComboBox(); self.c_abitrate.addItems(AUDIO_BITRATES); self.c_abitrate.setCurrentText("128")
        hbr.addWidget(self.c_abitrate)
        hbr.addWidget(info_badge("Кодируется в OPUS. 128 кбит - стандартное качество аудио в Youtube"))
        hbr.addStretch()
        fa.addRow(hbr)

        fa.addRow(row_with_info(self.ck_deg, "Намеренное ухудшение звука (эффект «телефон/радио»). Открывает дополнительные параметры ниже."))

        # Degrade-виджеты: скрываются/показываются по галочке
        for _sb in (self.s_hz, self.s_lp, self.s_hp):
            _sb.setMaximumWidth(95)
        self._lbl_samplebit = QLabel("Sample/Bit:")
        hd = QHBoxLayout(); hd.addWidget(QLabel("Hz:")); hd.addWidget(self.s_hz)
        hd.addWidget(info_badge("Частота дискретизации (Гц). Ниже = грубее звук. 8000 Гц ≈ телефонное качество."))
        hd.addWidget(self.ck_u8)
        hd.addWidget(info_badge("8-битный звук (u8) — сильное огрубление, шумный ретро-эффект."))
        hd.addStretch()
        fa.addRow(self._lbl_samplebit, hd)

        # Lowpass и Highpass — отдельными строками, чтобы умещались на узких экранах
        hlp = QHBoxLayout(); hlp.addWidget(QLabel("Lowpass:")); hlp.addWidget(self.s_lp)
        hlp.addWidget(info_badge("Срезает частоты ВЫШЕ указанной (Гц) — убирает «верха», звук становится глуше."))
        hlp.addStretch()
        self._lbl_lowpass = QLabel("")
        fa.addRow(self._lbl_lowpass, hlp)

        hhp = QHBoxLayout(); hhp.addWidget(QLabel("Highpass:")); hhp.addWidget(self.s_hp)
        hhp.addWidget(info_badge("Срезает частоты НИЖЕ указанной (Гц) — убирает «низы»/гул."))
        hhp.addStretch()
        self._lbl_highpass = QLabel("")
        fa.addRow(self._lbl_highpass, hhp)

        self._lbl_degvol = QLabel("Degrade vol (dB):")
        hdv = QHBoxLayout(); hdv.addWidget(self.s_deg_gain)
        self._badge_degvol = info_badge("Громкость degrade-звука в дБ. 0 = без изменений, отрицательное значение = тише.")
        hdv.addWidget(self._badge_degvol); hdv.addStretch()
        fa.addRow(self._lbl_degvol, hdv)

        self.ck_no_audio = QCheckBox("Удалить аудио"); self.ck_no_audio.setChecked(False)
        fa.addRow(row_with_info(self.ck_no_audio, "Полностью вырезает звуковую дорожку из видео (-an). Остальные настройки звука выше становятся неактуальны."))

        self._deg_group = [self._lbl_samplebit, self.s_hz, self.ck_u8,
                           self._lbl_lowpass, self.s_lp,
                           self._lbl_highpass, self.s_hp,
                           self._lbl_degvol, self.s_deg_gain, self._badge_degvol]

        def _update_deg_vis(checked):
            for w in self._deg_group:
                w.setVisible(checked)
            # Скрываем layout-строки полностью через содержимое
            for layout_item in [hd, hlp, hhp]:
                for i in range(layout_item.count()):
                    wi = layout_item.itemAt(i).widget()
                    if wi: wi.setVisible(checked)
        self.ck_deg.toggled.connect(_update_deg_vis)
        _update_deg_vis(self.ck_deg.isChecked())

        # «Удалить аудио» гасит остальные настройки звука (они бы всё равно
        # игнорировались в process_media, но серым фоном честнее показать это в UI).
        self._audio_effect_widgets = [self.ck_norm, self.s_tgt, self.s_lra, self.s_tp,
                                      self.ck_fade_in, self.s_fade_in, self.ck_fade, self.s_fade,
                                      self.c_abitrate, self.ck_deg] + self._deg_group

        def _update_no_audio_vis(checked):
            for wdg in self._audio_effect_widgets:
                wdg.setEnabled(not checked)
            if checked:
                _update_deg_vis(False)   # скрыть под-настройки degrade, если были открыты
            else:
                _update_deg_vis(self.ck_deg.isChecked())
        self.ck_no_audio.toggled.connect(_update_no_audio_vis)
        _update_no_audio_vis(self.ck_no_audio.isChecked())

        ga.setLayout(fa); rv_inner.addWidget(ga)

        # --- Скорость: отдельный блок между аудио и видео (без названия группы) ---
        self.s_spd = SpeedSpinBox(); self.s_spd.setValue(100); self.s_spd.setSuffix("%")
        self.s_spd.setMaximumWidth(110)
        speed_w = QWidget(); speed_h = QHBoxLayout(speed_w)
        speed_h.setContentsMargins(8, 2, 8, 2); speed_h.setSpacing(6)
        speed_h.addWidget(QLabel("Скорость:"))
        speed_h.addWidget(self.s_spd)
        speed_h.addWidget(info_badge("Изменение скорости видео и звука. 100% = без изменений"))
        speed_h.addStretch()
        rv_inner.addWidget(speed_w)

        gv = QGroupBox("Перекодирование видео"); fv = QFormLayout()
        self.chk_enable_video = QCheckBox("Включить перекодирование"); self.chk_enable_video.setChecked(True)

        # --- Переключатель профиля: две кнопки-тогглы ---
        self.btn_mode_std  = QPushButton("Стандарт");       self.btn_mode_std.setCheckable(True);  self.btn_mode_std.setChecked(True)
        self.btn_mode_dark = _icon_btn("Тёмные сцены", 'fa5s.moon'); self.btn_mode_dark.setCheckable(True); self.btn_mode_dark.setChecked(False)
        self.btn_mode_std.setToolTip("yuv420p, 1-pass")
        self.btn_mode_dark.setToolTip("10-бит (yuv420p10le), tune=0, 2-pass AV1\nCRF, preset и разрешение — без изменений")
        self.btn_mode_std.clicked.connect(lambda: self._set_preset_mode("std"))
        self.btn_mode_dark.clicked.connect(lambda: self._set_preset_mode("dark"))
        mode_h = QHBoxLayout(); mode_h.addWidget(self.btn_mode_std); mode_h.addWidget(self.btn_mode_dark)
        mode_h.addStretch(1)
        # Ширину тоглов профиля резервируем под ЖИРНЫЙ текст: глобальный QSS
        # (QPushButton:checked → font-weight:bold) делает активную кнопку жирной,
        # из-за чего «Тёмные сцены» обрезалось до «…сцень». sizeHint() у Qt НЕ
        # учитывает font-weight, заданный CSS-псевдо-состоянием (:checked) —
        # только реальный .font() виджета — так что заранее посчитать нужную
        # ширину числом (как раньше) не выйдет, ЛЮБАЯ константа была подогнана
        # под неверный шрифт (при setMinimumWidth в __init__ кнопка ещё не
        # «располирована» глобальным QSS — .font() отдаёт временный дефолтный
        # шрифт, а не итоговый Segoe UI/13px). Меряем НАСТОЯЩИЙ размер: временно
        # выставляем жирный шрифт САМОМУ виджету (после ensurePolished — это уже
        # правильный шрифт), берём sizeHint() и возвращаем шрифт обратно —
        # bold остаётся исключительно на совести CSS :checked, как и было.
        QTimer.singleShot(0, self._size_profile_toggle_buttons)

        # ── Метрика качества (AV1, всегда SVT-AV1) ────────────────────────────
        # Выкл — ручной CRF как есть, кодировщик просто тюнится под tune=0
        # (как и раньше). XPSNR — CRF на каждый файл подбирается
        # самостоятельно (_metric_crf_search в workers.py, без внешних
        # инструментов: короткий пробный сэмпл + бинарный поиск + встроенный
        # ffmpeg-фильтр xpsnr) так, чтобы результат достигал заданного
        # значения в дБ (см. s_target_metric ниже); сам кодировщик всё равно
        # тюнится под tune=0 — метрика здесь означает цель ПОДБОРА CRF, а не
        # тюнинг энкодера.
        self.ck_metric_xpsnr = QCheckBox("XPSNR")
        self.ck_metric_xpsnr.setChecked(False)

        self.s_crf = QSpinBox(); self.s_crf.setRange(0, 63); self.s_crf.setValue(45)
        self.s_pre = QSpinBox(); self.s_pre.setRange(0, 13); self.s_pre.setValue(2)
        self.c_res = QComboBox(); self.c_res.addItems(["Исходное", "1920x1080", "1280x720" + DEFAULT_TAG, "854x480", "144x72"])
        self.c_res.setCurrentText("1280x720" + DEFAULT_TAG)
        self.c_res.setMinimumWidth(210); self.c_res.setMaximumWidth(240)
        self.c_res.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.c_fps = InvertedWheelComboBox(); self.c_fps.addItems(["Исходный", "Исходный (max 30)", "5", "12", "23.976", "24", "30", "60"])
        self.c_fps.setCurrentText("Исходный (max 30)")
        self.c_fps.setEditable(True)   # можно вводить своё число FPS, а пресеты — из выпадашки
        self.c_fps.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        try: self.c_fps.lineEdit().setPlaceholderText("напр. 48")
        except Exception: pass
        self.c_fps.setMinimumWidth(150); self.c_fps.setMaximumWidth(200)
        fv.addRow(row_with_info(self.chk_enable_video, "Если выключено — видео не трогается, меняется только звук. Включено — перекодирование в AV1 (SVT-AV1)."))
        fv.addRow(label_with_info("Профиль:", "Стандарт: Использовать по умолчанию. Тёмные сцены: Только в темных сценах."), mode_h)
        henc = QHBoxLayout(); henc.addWidget(self.s_crf); henc.addWidget(self.s_pre)
        self._badge_crf = info_badge("Preset — скорость кодирования (0 медленно и качественно … 13 быстро, но страдает качество (Рекомендуется 1, если позволяет процессор)).")
        henc.addWidget(self._badge_crf)
        henc.addStretch()
        fv.addRow(label_with_info("CRF / Preset:", "CRF — качество (меньше = качественнее, но больше файл. Рекомендуется 40-45. Может принимать значения от 0 до 63)"), henc)

        # ── Тюнинг SVT-AV1 (--tune) — под какую метрику оптимизирует энкодер ──
        # Реально поддерживаемые SVT-AV1 режимы тюнинга (проверено на бандленном
        # ffmpeg/SVT-AV1): 0=VQ, 1=PSNR, 2=SSIM, 4=MS-SSIM, 5=VMAF. tune=3 (IQ)
        # сознательно пропущен — он поддерживает только all-intra/low-delay
        # предсказание и падает с ошибкой на нашей random-access GOP-структуре
        # (keyint=-1:scd=1, см. _av1_encoder_args в workers.py).
        self.c_tune = InvertedWheelComboBox()
        self.c_tune.addItem("VQ (0)" + DEFAULT_TAG, 0)
        self.c_tune.addItem("PSNR (1)", 1)
        self.c_tune.addItem("SSIM (2)", 2)
        self.c_tune.addItem("MS-SSIM (4)", 4)
        self.c_tune.addItem("VMAF (5)", 5)
        self.c_tune.setMinimumWidth(150); self.c_tune.setMaximumWidth(180)
        fv.addRow(label_with_info(
            "Тюнинг:",
            "Под какую метрику качества оптимизирует SVT-AV1 при кодировании.\n"
            "VQ — субъективное визуальное качество (по умолчанию).\n"
            "PSNR / SSIM / MS-SSIM / VMAF — оптимизация под соответствующую объективную метрику."),
            self.c_tune)

        # ── Метрика: Выкл (ручной CRF) / XPSNR (авто-подбор CRF) ───────────
        self.s_target_metric = QSlider(Qt.Orientation.Horizontal)
        self.s_target_metric.setRange(15, 60); self.s_target_metric.setValue(40)
        self.s_target_metric.setSingleStep(1); self.s_target_metric.setPageStep(1)
        self.s_target_metric.setEnabled(False)
        self.s_target_metric.setMaximumWidth(140)

        self.lbl_target_metric = QLabel("40 дБ")
        self.lbl_target_metric.setMinimumWidth(55)
        self.lbl_target_metric.setEnabled(False)

        def _on_metric_toggled(checked):
            self.s_target_metric.setEnabled(checked)
            self.lbl_target_metric.setEnabled(checked)
            try: self.main._save_settings_now()
            except Exception: pass
        def _on_target_changed(v):
            self.lbl_target_metric.setText(f"{v} дБ")
            try: self.main._save_settings_now()
            except Exception: pass
        self.ck_metric_xpsnr.toggled.connect(_on_metric_toggled)
        self.s_target_metric.valueChanged.connect(_on_target_changed)

        metric_h = QHBoxLayout()
        metric_h.addWidget(self.ck_metric_xpsnr)
        metric_h.addWidget(self.s_target_metric)
        metric_h.addWidget(self.lbl_target_metric)
        self._badge_metric = info_badge(
            "Выкл — CRF задаётся вручную выше, кодировщик просто кодирует с ним как есть.\n"
            "XPSNR — перед кодированием на коротком сэмпле подбирается CRF под каждый файл так, "
            "чтобы результат достигал указанного значения в дБ (выше — качественнее и крупнее файл). "
            "Ручной CRF выше остаётся резервным значением, если подбор не удался. "
            "Дольше по времени — на каждый файл делается до 6 пробных кодирований.")
        metric_h.addWidget(self._badge_metric)
        metric_h.addStretch()
        fv.addRow(label_with_info("Метрика:", "Выкл — ручной CRF (по умолчанию). XPSNR — CRF подбирается автоматически под целевое значение в дБ."), metric_h)

        fv.addRow(label_with_info("Разрешение:", "Масштаб выходного видео. «Исходное» — без изменений. Уменьшение сохраняет пропорции (без растяжения)."), self.c_res)
        fv.addRow(label_with_info("FPS:", "Частота кадров на выходе. «Исходный (max 30)» — снижает только если выше 30."), self.c_fps)

        # Видео fade in / fade out (через чёрный экран)
        self.ck_vfade_in = QCheckBox("Fade In (из чёрного)"); self.ck_vfade_in.setChecked(False)
        self.s_vfade_in = QDoubleSpinBox(); self.s_vfade_in.setValue(1.0); self.s_vfade_in.setRange(0.0, 60.0); self.s_vfade_in.setSingleStep(0.1)
        self.s_vfade_in.setMaximumWidth(110)
        self.ck_vfade_out = QCheckBox("Fade Out (в чёрный)"); self.ck_vfade_out.setChecked(False)
        self.s_vfade_out = QDoubleSpinBox(); self.s_vfade_out.setValue(1.0); self.s_vfade_out.setRange(0.0, 60.0); self.s_vfade_out.setSingleStep(0.1)
        self.s_vfade_out.setMaximumWidth(110)
        fv.addRow(row_with_info(self.ck_vfade_in, "Плавное появление картинки из чёрного экрана в начале (секунды)"), self.s_vfade_in)
        fv.addRow(row_with_info(self.ck_vfade_out, "Плавный уход картинки в чёрный экран в конце (секунды)"), self.s_vfade_out)

        # Обрезка чёрных полос (cropdetect) — убирает letterbox/pillarbox при перекоде
        self.ck_crop_black = QCheckBox("Обрезать чёрные полосы"); self.ck_crop_black.setChecked(False)
        self._crop_black_row = row_with_info(self.ck_crop_black, "Автоматически определяет и вырезает чёрные поля (letterbox/pillarbox) при перекодировании. Рамка определяется по началу видео через cropdetect.")
        fv.addRow(self._crop_black_row)

        self._fv_form = fv
        gv.setLayout(fv); rv_inner.addWidget(gv)
        # Скрываем строки видео если перекодирование выключено
        self._video_enc_rows = [self.btn_mode_std, self.btn_mode_dark,
                                 self.ck_metric_xpsnr,
                                 self.s_crf, self.s_pre, self.c_tune, self.c_res, self.c_fps,
                                 self._badge_crf,
                                 self.s_target_metric, self.lbl_target_metric, self._badge_metric,
                                 self.s_vfade_in, self.s_vfade_out, self._crop_black_row]
        def _update_video_enc(checked):
            for w in self._video_enc_rows:
                w.setVisible(checked)
            # Скрываем лейблы через FormLayout
            for row_idx in range(fv.rowCount()):
                lbl = fv.itemAt(row_idx, QFormLayout.ItemRole.LabelRole)
                fld = fv.itemAt(row_idx, QFormLayout.ItemRole.FieldRole)
                if fld:
                    wgt = fld.widget()
                    if wgt is None and fld.layout():
                        # layout-строка: проверяем первый виджет
                        wgt = fld.layout().itemAt(0).widget() if fld.layout().count() else None
                    if wgt in self._video_enc_rows or (
                        fld.layout() and any(
                            fld.layout().itemAt(i).widget() in self._video_enc_rows
                            for i in range(fld.layout().count())
                            if fld.layout().itemAt(i).widget()
                        )
                    ):
                        if lbl and lbl.widget(): lbl.widget().setVisible(checked)
        self.chk_enable_video.toggled.connect(_update_video_enc)
        _update_video_enc(self.chk_enable_video.isChecked())

        gavi = QGroupBox("Изображения"); favi = QFormLayout()
        # Выбор выходного формата
        self.c_img_fmt = InvertedWheelComboBox()
        self.c_img_fmt.addItems(["avif" + DEFAULT_TAG, "webp", "png", "jpg", "ico"])
        self.c_img_fmt.setCurrentText("avif" + DEFAULT_TAG)
        self.c_img_fmt.setMinimumWidth(190); self.c_img_fmt.setMaximumWidth(220)
        self.c_img_fmt.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        favi.addRow(label_with_info("Формат:", "Выходной формат изображений. avif — лучшее сжатие, на остальные форматы можно забить"), self.c_img_fmt)

        # Цветовая субдискретизация AVIF (только для avif; при альфе всегда 4:2:0)
        self.c_chroma = InvertedWheelComboBox()
        self.c_chroma.addItems(["4:2:0" + DEFAULT_TAG, "4:2:2", "4:4:4"])
        self.c_chroma.setCurrentText("4:2:0" + DEFAULT_TAG)
        self.c_chroma.setMinimumWidth(140); self.c_chroma.setMaximumWidth(180)
        favi.addRow(label_with_info(
            "Субдискретизация:",
            "Цветовая субдискретизация AVIF. 4:2:0 — минимальный размер файла (хватает для фото). "
            "4:4:4 — максимум цветовой чёткости (текст, графика, скриншоты), но файл крупнее. "
            "Для изображений с прозрачностью всегда 4:2:0."), self.c_chroma)

        # ── Лимит размера файла ──────────────────────────────────────────────
        hlim = QHBoxLayout()
        self.ck_lim = QCheckBox("Сжать до")
        self.ck_lim.setChecked(True)
        self.s_lim = QSpinBox()
        self.s_lim.setRange(0, 50000); self.s_lim.setSuffix(" КБ")
        self.s_lim.setSingleStep(50); self.s_lim.setValue(100)
        hlim.addWidget(self.ck_lim); hlim.addWidget(self.s_lim)
        hlim.addWidget(info_badge("Подбирает качество так, чтобы файл не превышал указанный размер (КБ). 100 для AVIF - достаточное для SiGame"))
        hlim.addStretch()
        # Привязка: спинбокс активен только если галочка включена
        self.ck_lim.toggled.connect(self.s_lim.setEnabled)
        favi.addRow(hlim)

        # ── Проходы подбора под лимит размера ────────────────────────────────
        hpass = QHBoxLayout()
        self.s_passes = QSpinBox()
        self.s_passes.setRange(1, 8); self.s_passes.setValue(4)
        hpass.addWidget(QLabel("Проходы подбора:")); hpass.addWidget(self.s_passes)
        hpass.addWidget(info_badge("Сколько проб качества делать при подборе под лимит размера (бинарный поиск). Больше — точнее под лимит, но дольше. Работает для avif / webp / jpg. По умолчанию 4, максимум 8."))
        hpass.addStretch()
        self.ck_lim.toggled.connect(self.s_passes.setEnabled)
        self.s_passes.setEnabled(self.ck_lim.isChecked())
        favi.addRow(hpass)

        # ── CQ-level: фиксированное качество AVIF (используется, когда лимит
        # размера выше выключен — при включённом лимите качество подбирается
        # автоматически бинарным поиском независимо от этого значения, поэтому
        # при включённом «Сжать до» поле визуально отключается) ─────────────
        self.s_cq = QSpinBox()
        self.s_cq.setRange(0, 63); self.s_cq.setValue(30)
        self.s_cq.setMaximumWidth(80)
        self._lbl_cq = label_with_info(
            "--cq-level:",
            "Уровень качества AVIF (libaom-av1, CQ-level: 0 — максимальное качество, 63 — максимальное сжатие). "
            "Применяется только когда выключен лимит «Сжать до» — при включённом лимите качество подбирается "
            "автоматически под нужный размер файла.")
        favi.addRow(self._lbl_cq, self.s_cq)
        # При включённом лимите размера CQ-level не участвует в кодировании —
        # отключаем визуально (темнее), чтобы не создавать видимость выбора.
        self.ck_lim.toggled.connect(lambda on: self.s_cq.setEnabled(not on))
        self.ck_lim.toggled.connect(lambda on: self._lbl_cq.setEnabled(not on))
        self.s_cq.setEnabled(not self.ck_lim.isChecked())
        self._lbl_cq.setEnabled(not self.ck_lim.isChecked())

        # ── Лимит разрешения ─────────────────────────────────────────────────
        hdim = QHBoxLayout()
        self.ck_dim = QCheckBox("Снизить до")
        self.ck_dim.setChecked(False)
        self.s_dim = QSpinBox()
        self.s_dim.setRange(16, 8000); self.s_dim.setSuffix(" px")
        self.s_dim.setValue(1280); self.s_dim.setEnabled(False)
        hdim.addWidget(self.ck_dim); hdim.addWidget(self.s_dim)
        hdim.addWidget(QLabel("(макс. сторона)"))
        hdim.addWidget(info_badge("Ограничивает максимальную сторону изображения (px) с сохранением пропорций."))
        hdim.addStretch()
        self.ck_dim.toggled.connect(self.s_dim.setEnabled)
        favi.addRow(hdim)

        # ── Отдельные лимиты ширины / высоты (независимо от макс. стороны) ────
        # Применяются вместе с «макс. стороной»: итог — самый строгий предел,
        # пропорции сохраняются, увеличение никогда не делается.
        hwid = QHBoxLayout()
        self.ck_width = QCheckBox("Ширина до"); self.ck_width.setChecked(False)
        self.s_width = QSpinBox(); self.s_width.setRange(16, 8000); self.s_width.setSuffix(" px")
        self.s_width.setValue(1280); self.s_width.setEnabled(False)
        hwid.addWidget(self.ck_width); hwid.addWidget(self.s_width)
        hwid.addWidget(QLabel("(ширина)"))
        hwid.addWidget(info_badge("Ограничивает ШИРИНУ изображения (px), высота подстраивается пропорционально. Работает независимо и вместе с «макс. стороной»."))
        hwid.addStretch()
        self.ck_width.toggled.connect(self.s_width.setEnabled)
        favi.addRow(hwid)

        hhei = QHBoxLayout()
        self.ck_height = QCheckBox("Высота до"); self.ck_height.setChecked(False)
        self.s_height = QSpinBox(); self.s_height.setRange(16, 8000); self.s_height.setSuffix(" px")
        self.s_height.setValue(720); self.s_height.setEnabled(False)
        hhei.addWidget(self.ck_height); hhei.addWidget(self.s_height)
        hhei.addWidget(QLabel("(высота)"))
        hhei.addWidget(info_badge("Ограничивает ВЫСОТУ изображения (px), ширина подстраивается пропорционально. Работает независимо и вместе с «макс. стороной»."))
        hhei.addStretch()
        self.ck_height.toggled.connect(self.s_height.setEnabled)
        favi.addRow(hhei)

        self.sl_aspd = _JumpSlider(Qt.Orientation.Horizontal); self.sl_aspd.setRange(0, 8); self.sl_aspd.setValue(2)
        # Перезаписывать ИСХОДНИК: результат сохраняется под именем оригинала
        # (без суффикса «_Сжатый»), а сам исходный файл удаляется. По умолчанию
        # ВЫКЛ — операция необратима (оригинал не восстановить).
        self.ck_overwrite_src = QCheckBox("Перезаписывать исходник")
        self.ck_overwrite_src.setChecked(False)
        favi.addRow(label_with_info("Скорость:", "левее — медленнее и компактнее файл, правее — быстрее, но больше"), self.sl_aspd)
        favi.addRow(row_with_info(self.ck_overwrite_src, "ОПАСНО: удаляет исходное изображение и оставляет только сжатую версию (с именем оригинала, без «_Сжатый»). Оригинал не восстановить. По умолчанию выключено."))
        self._favi_form = favi
        gavi.setLayout(favi); rv_inner.addWidget(gavi)

        # ── Продвинутые настройки кодирования (Тюнинг / Метрика-XPSNR / CQ-level) ─
        # Редко нужны и путают в базовом сценарии — скрыты по умолчанию, включаются
        # ОДНИМ переключателем в Настройках (см. set_advanced_encode_visible).
        self._adv_encode_widgets_fv = [self.c_tune, self.ck_metric_xpsnr,
                                        self.s_target_metric, self.lbl_target_metric,
                                        self._badge_metric]
        self._adv_encode_widgets_favi = [self.s_cq, self._lbl_cq]
        self._show_advanced_encode = False
        self.chk_enable_video.toggled.connect(lambda _c: self._apply_advanced_encode_visibility())
        self._apply_advanced_encode_visibility()

        rv_inner.addStretch(); w.setLayout(rv_inner); rw.setWidget(w); right_layout.addWidget(rw)

        # ── Низ правой панели: приоритет процесса + счётчик задействованных потоков ──
        foot = QWidget(); foot_l = QHBoxLayout(foot); foot_l.setContentsMargins(6, 0, 6, 2)
        foot_l.addWidget(QLabel("Приоритет:"))
        self.c_priority = InvertedWheelComboBox()
        self.c_priority.addItems(["Низкий", "Обычный", "Высокий"])
        self.c_priority.setCurrentText("Обычный")
        self.c_priority.setMaximumWidth(150)
        # Приоритет сохраняем СВОИМ изолированным write (read-modify-write только
        # ключа 'priority'), а не только общим _save_settings_now: тот собирает
        # ВЕСЬ словарь настроек и при любой ошибке сборки молча НИЧЕГО не пишет
        # (см. _collect_settings → {}), из-за чего смена приоритета терялась.
        self.c_priority.currentTextChanged.connect(self._persist_priority)
        foot_l.addWidget(self.c_priority)
        foot_l.addWidget(info_badge("Приоритет процессов кодирования (ffmpeg) в системе. Высокий — кодирует быстрее; на Низком ПК отзывчивее."))
        foot_l.addStretch()
        # Всего логических потоков ЦП на этой машине — показываем сразу (0/N),
        # а не 0/0, чтобы было видно потенциал ещё до запуска обработки.
        self._cpu_threads = max(1, cpu_thread_count())
        self.lbl_threads = QLabel(f"Параллельных задач: 0/{self._cpu_threads}")
        self.lbl_threads.setToolTip(
            "Занятые логические потоки ЦП. Видео/аудио кодируются по одному файлу, "
            "но SVT-AV1 нагружает все ядра — поэтому показывается полное число потоков. "
            "Изображения обрабатываются параллельно (по числу ядер).")
        foot_l.addWidget(self.lbl_threads)
        right_layout.addWidget(foot)

        btn_box = QWidget(); btn_layout = QHBoxLayout(btn_box)
        btn_layout.setContentsMargins(0, 6, 0, 6)
        self.b_run = _icon_btn("НАЧАТЬ", 'fa5s.play', color='#1e1e2e'); self.b_run.setObjectName("b_run")
        self.b_stop = _icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e'); self.b_stop.setObjectName("b_stop"); self.b_stop.setEnabled(False)
        self.b_run.clicked.connect(self.run); self.b_stop.clicked.connect(self.stop)
        btn_layout.addWidget(self.b_run); btn_layout.addWidget(self.b_stop)

        right_layout.addWidget(btn_box); right_container.setLayout(right_layout); l.addWidget(right_container, 0)

        self.shortcut_paste = QShortcut(QKeySequence("Ctrl+V"), self.tree)
        self.shortcut_paste.activated.connect(self.paste_files)
        # Клавиша Delete — удалить выделенные файлы из очереди
        self.shortcut_delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree)
        self.shortcut_delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.shortcut_delete.activated.connect(self.rem)
        self.tree.itemDoubleClicked.connect(self.on_double_click)

    def _persist_priority(self, text):
        """Изолированно пишет ТОЛЬКО ключ 'priority' (read-modify-write), не трогая
        остальные настройки. Нужен потому, что общий _save_settings_now собирает
        весь словарь разом и при любой ошибке сборки молча не сохраняет ничего —
        тогда смена приоритета не доживала до следующего запуска."""
        try:
            s = load_settings()
            if isinstance(s, dict) and s:
                # Загрузили существующий словарь — дописываем только приоритет.
                s['priority'] = text
                save_settings(s)
            else:
                # Файл пуст/нечитаем: НЕ пишем одинокий ключ (затёр бы остальное),
                # а просим общий сборщик собрать полный словарь.
                self.main._save_settings_now()
        except Exception:
            pass

    def _size_profile_toggle_buttons(self):
        """Резервирует под кнопки «Стандарт»/«Тёмные сцены» ширину, достаточную
        для их ЖИРНОГО (:checked, см. глобальный QSS) начертания — см. пояснение
        в __init__. Меряет реальный полированный шрифт виджета, а не константу."""
        for _b in (self.btn_mode_std, self.btn_mode_dark):
            _b.ensurePolished()
            _orig_font = _b.font()
            _bold_font = QFont(_orig_font); _bold_font.setBold(True)
            _b.setFont(_bold_font)
            _bold_w = _b.sizeHint().width()
            _b.setFont(_orig_font)
            if _b.minimumWidth() < _bold_w:
                _b.setMinimumWidth(_bold_w)

    def _set_preset_mode(self, mode):
        """Переключает профиль кодирования без изменения preset и битрейта аудио."""
        is_dark = (mode == "dark")
        self.btn_mode_std.blockSignals(True);  self.btn_mode_dark.blockSignals(True)
        self.btn_mode_std.setChecked(not is_dark); self.btn_mode_dark.setChecked(is_dark)
        self.btn_mode_std.blockSignals(False); self.btn_mode_dark.blockSignals(False)
        try: self.main._save_settings_now()
        except Exception: pass

    def _video_metric_value(self):
        """'none' | 'xpsnr' — цель авто-подбора CRF (_metric_crf_search
        в workers.py). 'none' — ручной CRF без подбора."""
        return 'xpsnr' if self.ck_metric_xpsnr.isChecked() else 'none'

    @staticmethod
    def _set_form_row_visible(form, widgets, visible):
        """Показывает/скрывает виджеты формы И их лейбл (QFormLayout не двигает
        лейбл сам по себе — ищем строку, где поле — один из widgets или их
        layout-обёртка, см. _update_video_enc)."""
        for w in widgets:
            w.setVisible(visible)
        for row_idx in range(form.rowCount()):
            lbl = form.itemAt(row_idx, QFormLayout.ItemRole.LabelRole)
            fld = form.itemAt(row_idx, QFormLayout.ItemRole.FieldRole)
            if not fld:
                continue
            wgt = fld.widget()
            if wgt is None and fld.layout():
                wgt = fld.layout().itemAt(0).widget() if fld.layout().count() else None
            matches = wgt in widgets or (
                fld.layout() and any(
                    fld.layout().itemAt(i).widget() in widgets
                    for i in range(fld.layout().count())
                    if fld.layout().itemAt(i).widget()
                )
            )
            if matches and lbl and lbl.widget():
                lbl.widget().setVisible(visible)

    def set_advanced_encode_visible(self, on: bool):
        """Настройки → единый переключатель «Тюнинг / Метрика (XPSNR) / CQ-level».
        Втроём скрыты по умолчанию (редко нужны, путают в базовом сценарии) —
        включаются/выключаются ОДНИМ чекбоксом в Настройках."""
        self._show_advanced_encode = bool(on)
        self._apply_advanced_encode_visibility()

    def _apply_advanced_encode_visibility(self):
        show = bool(getattr(self, '_show_advanced_encode', False))
        # Тюнинг/Метрика имеют смысл только пока включено само перекодирование видео.
        self._set_form_row_visible(self._fv_form, self._adv_encode_widgets_fv,
                                    show and self.chk_enable_video.isChecked())
        self._set_form_row_visible(self._favi_form, self._adv_encode_widgets_favi, show)
        # Колонка "Оценка XPSNR" в таблице файлов заполняется только когда метрика
        # включена — без неё это всегда пустой прочерк, прячем саму колонку.
        self.tree.setColumnHidden(8, not show)

    def _video_tune_value(self):
        """Числовое значение SVT-AV1 --tune (0/1/2/4/5, см. c_tune в __init__)
        для финального кодирования (_av1_encoder_args в workers.py)."""
        data = self.c_tune.currentData()
        return int(data) if data is not None else 0

    def _set_tune_value(self, value):
        """Выставляет c_tune по числовому значению tune (обратная операция
        к _video_tune_value) — используется при загрузке сохранённых настроек."""
        idx = self.c_tune.findData(int(value))
        self.c_tune.setCurrentIndex(idx if idx >= 0 else 0)

    def on_url_ctx(self, pos):
        m = QMenu()
        try: cb = QApplication.clipboard().text().strip()
        except Exception: cb = ""
        if cb and cb.startswith("http"):
            a = QAction("Скачать из буфера", self)
            a.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.download_url(False)))
            a2 = QAction("Скачать аудио из буфера", self)
            a2.triggered.connect(lambda checked=False, cbv=cb: (self.url_edit.setText(cbv), self.download_url(True)))
            m.addAction(a); m.addAction(a2); m.addSeparator()
        m.addAction(QAction("Вставить", self, triggered=self.url_edit.paste))
        m.exec(self.url_edit.mapToGlobal(pos))

    def on_double_click(self, item, column):
        """Двойной клик: по готовому файлу — открыть результат в плеере;
        по ещё не обработанному (только добавленному) — запустить
        перекодирование ТОЛЬКО этого файла."""
        try:
            iid = item.data(0, Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if not entry:
                return
            if entry.get('is_done'):
                out_path = entry.get('out_path')
                if out_path and os.path.exists(out_path):
                    self.open_output_file(out_path)
                else:
                    self.open_file_location(item)
            else:
                # Файл ещё в очереди — перекодируем только его
                self._run_items([entry])
        except Exception: pass

    def open_output_file(self, path):
        """Открывает файл в ассоциированном приложении (плеер, просмотрщик)."""
        try:
            if IS_WIN:
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            self.main.log(f"Не удалось открыть файл: {e}")

    def _choose_export_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка экспорта", self.export_dir or default_download_dir())
        if d:
            self.export_dir = d
            self._update_export_label()
            try: self.main._save_settings_now()
            except Exception: pass

    def _reset_export_dir(self):
        self.export_dir = ""
        self._update_export_label()
        try: self.main._save_settings_now()
        except Exception: pass

    def _update_export_label(self):
        """Обновляет подпись пути экспорта и видимость кнопки сброса."""
        try:
            if self.export_dir and os.path.isdir(self.export_dir):
                self.lbl_export_dir.setText(self.export_dir)
                self.lbl_export_dir.setToolTip(self.export_dir)
                self.btn_export_reset.setEnabled(True)
            else:
                self.lbl_export_dir.setText("По умолчанию экспорт в папку исходника")
                self.lbl_export_dir.setToolTip("")
                self.btn_export_reset.setEnabled(False)
        except Exception: pass

    def download_url(self, audio_only=False):
        url = self.url_edit.text().strip()
        if not url: return
        self.url_edit.clear()

        try:
            dl_path = self.main.tab_ytdlp.out.text()
            if not dl_path or not os.path.exists(dl_path): dl_path = default_download_dir()
        except Exception: dl_path = default_download_dir()

        self.main.tab_ytdlp.add_dl_direct(url, audio_only=audio_only, outdir=dl_path)

    def _quick_dl_stop(self):
        """СТОП в строке «Быстрая загрузка» — останавливает активные загрузки.
        Быстрые загрузки выполняются воркер-пулом вкладки «Скачать» (YtdlpTab),
        поэтому останавливаем их там же — как кнопкой СТОП на той вкладке."""
        try:
            self.main.tab_ytdlp.stop_all_dl()
        except Exception as e:
            self.main.log(f"quick stop error: {e}")

    def reset_status(self):
        for i in self.tree.selectedItems():
            iid = i.data(0, Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if entry:
                entry['is_done'] = False
            i.setText(6, "Ожидание")
            i.setText(7, "—")                  # Время перекодирования
            self._proc_started.pop(iid, None)
            self._proc_running.discard(iid)
            # Сброс «новых» данных — оставляем только исходные (верхняя строка «было»)
            self._set_pair(i, 2, bottom="—")   # Размер: стало
            self._set_pair(i, 3, bottom="—")   # Битрейт: итог
            self._set_pair(i, 4, bottom="—")   # LUFS: после
            i.setData(0, ITEM_STATUS_ROLE, None)
            i.setData(0, ITEM_COMPARE_ROLE, None)   # снять значок «сравнить»
        self.tree.viewport().update()

    def dragEnterEvent(self, event):
        try:
            mime = event.mimeData()
            if mime and mime.hasUrls(): event.acceptProposedAction()
            else: event.ignore()
        except Exception: event.ignore()

    def dropEvent(self, event):
        try:
            self.window().raise_(); self.window().activateWindow()
            mime = event.mimeData()
            if not mime: return
            if mime.hasUrls():
                paths = [u.toLocalFile() for u in mime.urls() if u.toLocalFile()]
                if paths: self.add_paths(paths)
                event.acceptProposedAction()
            else: event.ignore()
        except Exception as e:
            self.main.log(f"dropEvent error: {e}")
            event.ignore()

    def ctx(self, pos):
        m = QMenu()
        sel = self.tree.itemAt(pos)
        if sel:
            iid = sel.data(0, Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid, {})
            out_path = entry.get('out_path', '')
            if out_path and os.path.exists(out_path):
                m.addAction(get_icon('fa5s.play'), "Открыть файл", lambda checked=False, p=out_path: self.open_output_file(p))
            m.addAction(get_icon('fa5s.folder-open'), "Перейти к файлу", lambda checked=False, it=sel: self.open_file_location(it))
            m.addAction(get_icon('fa5s.undo'), "Сбросить статус", lambda checked=False: self.reset_status())
            m.addSeparator()
            m.addAction(get_icon('fa5s.times'), "Удалить", lambda checked=False: self.rem())
        m.addAction(get_icon('fa5s.paste'), "Вставить файлы", lambda checked=False: self.paste_files())
        m.addAction(get_icon('fa5s.trash'), "Очистить всё", lambda checked=False: self.clear())
        m.exec(self.tree.mapToGlobal(pos))

    def open_file_location(self, item):
        try:
            path = item.toolTip(0) or item.data(0, Qt.ItemDataRole.ToolTipRole)
            if not path: return
            path = os.path.abspath(path)
            if IS_WIN: subprocess.Popen(['explorer', '/select,', path])
            elif sys.platform == 'darwin': subprocess.Popen(['open', '-R', path])
            else: subprocess.Popen(['xdg-open', os.path.dirname(path)])
        except Exception as e:
            self.main.log(f"open_file_location error: {e}")

    def paste_files(self):
        try:
            mime = QApplication.clipboard().mimeData()
            if mime.hasUrls():
                self.add_paths([u.toLocalFile() for u in mime.urls() if u.toLocalFile()])
        except Exception as e:
            self.main.log(f"paste_files error: {e}")

    def add(self):
        p, _ = QFileDialog.getOpenFileNames(self, "Файлы")
        if p: self.add_paths(p)

    def add_paths(self, paths):
        for p in paths:
            try:
                if not os.path.exists(p): continue

                # Не добавляем файлы, которые сами являются результатом обработки
                stem = Path(p).stem
                if stem.endswith("_Сжатый") or stem.endswith("_Compressed"):
                    continue

                ext = Path(p).suffix.lower()
                if ext in ALLOWED_MEDIA: ft = "MEDIA"
                elif ext in ALLOWED_IMG: ft = "IMG"
                else: continue

                iid = uuid.uuid4().hex
                # Только быстрый getsize — ffprobe уйдёт в фоновый поток
                try: size = os.path.getsize(p)
                except Exception: size = 0

                item_data = {'iid': iid, 'path': p, 'type': ft, 'dur': 0, 'is_done': False}
                self.items.append(item_data)
                self._item_data_map[iid] = item_data

                it = QTreeWidgetItem(self.tree)
                name = os.path.basename(p)
                # Колонка 0 (Превью): миниатюра + имя файла под ней (рисует
                # PreviewNameDelegate, длинное имя обрезается многоточием).
                # Полное имя — в тултипе.
                it.setText(0, name)
                # Тултип превью — только путь; полное имя показывается при
                # наведении на строку имени под превью (см. DraggableTreeWidget).
                it.setToolTip(0, p)
                # Колонка 1: метки Было/Стало. 2 строки [было, стало] —
                # центрируются по высоте строки как имя файла и статус (пустая
                # 1-я строка раньше сдвигала пару вниз от центра).
                it.setText(1, "Было\nСтало")
                it.setText(2, f"{human_size(size)}\n—")     # Размер: было(исх) / стало
                it.setText(3, "—\n—")                       # Битрейт: исх / итог
                it.setText(4, "—\n—")                       # LUFS: до / после
                it.setText(5, "—\n—")                       # Длительность: исх / итог
                it.setText(6, "Ожидание")                   # Статус (одна строка)
                it.setText(7, "—")                          # Время перекодирования (мм:сс)
                it.setToolTip(7, "Время, потраченное на перекодирование")
                it.setText(8, "—")                          # Оценка XPSNR (заполняется после видео-кодирования)
                it.setToolTip(8, "Оценка качества результата (XPSNR, дБ) — выше значит ближе к оригиналу.\n"
                                 "Только для перекодированного видео (AV1); при копировании/аудио — «—».")
                it.setData(0, Qt.ItemDataRole.UserRole, iid)
                # Аудио (без видеоряда) → компактная строка без места под превью.
                if ext in ALLOWED_AUDIO:
                    it.setData(0, ITEM_AUDIO_ROLE, True)
                self._item_map[iid] = it
                self.tree.scrollToItem(it)
                self.pool.start(LocalThumbnailRunnable(p, iid, self.thumb_sig))

                if ft == "MEDIA":
                    def _bg(path_local, iid_local):
                        # ffprobe + loudness — всё в фоне, UI не блокируем.
                        # Результат отдаём в GUI-поток через сигналы: QTimer.singleShot
                        # из обычного threading.Thread (без Qt event loop) НЕ
                        # срабатывает — из-за этого битрейт и длительность не
                        # появлялись при добавлении файла.
                        try:
                            dur_r, br_r, size_r, a_br_r, a_codec_r = get_media_info(path_local)
                            v_r = get_video_codec_label(path_local)
                            size_label_r = f"{v_r} {human_size(size_r)}" if v_r else human_size(size_r)
                            self.media_info_sig.emit(
                                iid_local, size_label_r,
                                fmt_bitrate_with_codec(a_codec_r, a_br_r or br_r),
                                float(dur_r or 0.0))
                        except Exception: pass
                        try:
                            val = measure_loudness(path_local)
                        except Exception: val = None
                        self.media_lufs_sig.emit(iid_local, val)
                    threading.Thread(target=_bg, args=(p, iid), daemon=True).start()

            except Exception as e:
                self.main.log(f"add_paths error: {e}")

    def set_thumb(self, iid, icon):
        try:
            item = self._find_item(iid)
            if item:
                item.setIcon(0, icon)
        except Exception: pass

    def _apply_media_info(self, iid, size_str, bitrate, dur):
        """GUI-поток: исходные размер/битрейт/длительность из ffprobe (верхняя
        строка «Было»). Вызывается через media_info_sig из фонового потока."""
        try:
            d = self._item_data_map.get(iid)
            if d: d['dur'] = dur
            item = self._find_item(iid)
            if item:
                if size_str:
                    self._set_pair(item, 2, top=size_str)
                self._set_pair(item, 3, top=(bitrate if bitrate and bitrate != "-" else "—"))
                self._set_pair(item, 5, top=self._fmt_dur(dur))
        except Exception: pass

    def _apply_media_lufs(self, iid, val):
        """GUI-поток: исходный LUFS (через media_lufs_sig из фонового потока)."""
        self.update_lufs_columns(iid, val, None)

    @staticmethod
    def _set_pair(item, col, top=None, bottom=None):
        """Ячейка из 2 строк: [было, стало]. Меняет только было/стало
        (top/bottom), сохраняя другую строку. Пара центрируется по высоте
        строки (как имя файла и статус)."""
        cur = (item.text(col) or "").split("\n")
        # Легаси-формат из 3 строк ([пусто, было, стало]) — отбрасываем пустую.
        if len(cur) >= 3:
            cur = cur[1:]
        t = cur[0] if len(cur) > 0 and cur[0] else "—"
        b = cur[1] if len(cur) > 1 and cur[1] else "—"
        if top is not None: t = top
        if bottom is not None: b = bottom
        item.setText(col, f"{t}\n{b}")

    @staticmethod
    def _fmt_dur(sec):
        """Длительность для колонки: «5.72 с» (<1 мин) или «M:SS.ss»."""
        try: sec = float(sec)
        except Exception: return "—"
        if sec <= 0: return "—"
        if sec < 60: return f"{sec:.2f} с"
        m = int(sec // 60); s = sec - m * 60
        return f"{m}:{s:05.2f}"

    def update_item_info(self, iid, size_new, bitrate_result):
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 2, bottom=size_new)          # Размер: стало
                self._set_pair(item, 3, bottom=bitrate_result)    # Битрейт: итог
                item.setData(0, ITEM_STATUS_ROLE, 'done')
                # Для обработанной картинки/видео включаем значок «сравнить» на превью
                # (аудио без видеоряда сравнивать нечем — там значок не нужен).
                entry = self._item_data_map.get(iid)
                is_video = entry and entry.get('type') == 'MEDIA' and Path(entry.get('path', '')).suffix.lower() not in ALLOWED_AUDIO
                if entry and (entry.get('type') == 'IMG' or is_video):
                    item.setData(0, ITEM_COMPARE_ROLE, True)
                    item.setToolTip(0, (item.toolTip(0) or "")
                                    + "\n\nЗначок в углу превью — сравнить исходник и результат.")
                self.tree.viewport().update()
        except Exception: pass

    def _on_compare_clicked(self, index):
        """Клик по значку «сравнить» на превью обработанного файла: открывает
        полноэкранное сравнение исходника и результата (картинка — по форме,
        видео — плеер слева/справа с синхронной перемоткой). Если оригинал/
        результат недоступны — показывает то, что есть."""
        try:
            iid = index.data(Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if not entry:
                return
            src = entry.get('path', '')
            out = entry.get('out_path', '')
            src_ok = bool(src) and os.path.exists(src)
            out_ok = bool(out) and os.path.exists(out)
            is_video = entry.get('type') == 'MEDIA' and Path(src or out).suffix.lower() not in ALLOWED_AUDIO
            if src_ok and out_ok and os.path.abspath(src) != os.path.abspath(out):
                if is_video:
                    show_video_compare(src, out, self)
                else:
                    show_image_compare(src, out, self)
            elif out_ok:
                if is_video:
                    show_video_compare(out, out, self)
                else:
                    show_image_fullscreen(out, self)
            elif src_ok:
                if is_video:
                    show_video_compare(src, src, self)
                else:
                    show_image_fullscreen(src, self)
        except Exception as e:
            self.main.log(f"Сравнение: {e}")

    def _compare_any_files(self):
        """Кнопка «Сравнить» в тулбаре списка — сравнение ЛЮБЫХ двух файлов с
        диска, а не только пары исходник/результат из очереди обработки. Тип
        (картинка или видео) определяется по расширению первого файла. Можно
        выбрать всего один файл — окно сравнения откроется сразу с ним (слева),
        а второй добавляется прямо в окне значком папки (тот же интерфейс,
        что и при обычном сравнении)."""
        try:
            video_exts = ALLOWED_MEDIA - ALLOWED_AUDIO
            exts = " ".join(f"*{e}" for e in sorted(ALLOWED_IMG | video_exts))
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Выберите файл(ы) для сравнения (можно один — второй добавите в окне)", "",
                f"Изображения и видео ({exts});;Все файлы (*)")
            if not paths:
                return
            a = paths[0]
            b = paths[1] if len(paths) > 1 else None
            ext_a = Path(a).suffix.lower()
            if ext_a in ALLOWED_IMG:
                show_image_compare(a, b, self, use_filenames=True)
            elif ext_a in video_exts:
                show_video_compare(a, b, self, use_filenames=True)
            else:
                self.main.log(f"Сравнение: неподдерживаемый тип файла «{ext_a}»")
        except Exception as e:
            self.main.log(f"Сравнение: {e}")

    def update_item_dur(self, iid, dur_str):
        """Длительность итогового файла (после перекодирования) — нижняя строка."""
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 5, bottom=self._fmt_dur(dur_str))
        except Exception: pass

    def update_item_xpsnr(self, iid, score):
        """Оценка качества результата (XPSNR, дБ) — заполняется после видео-
        кодирования (см. xpsnr_sig в workers.py). score=None — не измерялась
        (не видео, копия без перекодирования, или замер не удался)."""
        try:
            item = self._find_item(iid)
            if item:
                item.setText(8, "—" if score is None else f"{score:.1f} дБ")
        except Exception: pass

    def update_lufs_columns(self, iid, before, after):
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 4, top=("—" if before is None else f"{before:.2f}"))
                self._set_pair(item, 4, bottom=("—" if after is None else f"{after:.2f}"))
        except Exception: pass

    def rem(self):
        try:
            for i in self.tree.selectedItems():
                iid = i.data(0, Qt.ItemDataRole.UserRole)
                # Мутируем СПИСОК НА МЕСТЕ (не self.items = [...]) — ProcessWorker
                # держит ссылку на этот же объект-список как «живую» очередь
                # (см. queue_ref в _run_items); переприсваивание отвязывало бы
                # воркер от изменений, и удалённый файл всё равно обрабатывался
                # бы до конца, а не только до нажатия «СТОП».
                self.items[:] = [x for x in self.items if x['iid'] != iid]
                self._item_map.pop(iid, None)
                self._item_data_map.pop(iid, None)
                self._removed_ids.add(iid)
                self.tree.invisibleRootItem().removeChild(i)
        except Exception: pass

    def clear(self):
        try:
            self.items.clear()
            self._item_map.clear()
            self._item_data_map.clear()
            self.tree.clear()
        except Exception: pass

    def run(self):
        """Кнопка «НАЧАТЬ» — обрабатывает всю очередь."""
        self._run_items(self.items)

    def _collect_settings(self):
        """Собирает АКТУАЛЬНОЕ состояние всех настроек «Обработки» с виджетов —
        единственное место сборки, чтобы кнопка «НАЧАТЬ» и фоновая пере-синхронизация
        настроек уже идущего воркера (_settings_sync_tick) всегда читали одно и то же
        и любая новая настройка, добавленная сюда в будущем, подхватывалась обоими
        путями сама собой."""
        try: ab = self.c_abitrate.currentText() or "128"
        except Exception: ab = "128"
        try: spd = self.s_spd.value()
        except Exception: spd = 100
        return {
            'audio': {
                'remove': bool(self.ck_no_audio.isChecked()),
                'norm': bool(self.ck_norm.isChecked()),
                'tgt': float(self.s_tgt.value()), 'lra': float(self.s_lra.value()), 'tp': float(self.s_tp.value()),
                'fade': bool(self.ck_fade.isChecked()), 'fade_d': float(self.s_fade.value()),
                'fade_in': bool(self.ck_fade_in.isChecked()), 'fade_in_d': float(self.s_fade_in.value()),
                'deg': bool(self.ck_deg.isChecked()), 'hz': int(self.s_hz.value()), 'u8': bool(self.ck_u8.isChecked()),
                'lp': int(self.s_lp.value()), 'hp': int(self.s_hp.value()), 'deg_gain_db': float(self.s_deg_gain.value()),
                'bitrate': ab
            },
            'video': {
                'enabled': bool(self.chk_enable_video.isChecked()), 'speed': int(spd), 'crf': int(self.s_crf.value()),
                'pre': int(self.s_pre.value()), 'res': strip_default_tag(self.c_res.currentText()), 'fps': self.c_fps.currentText().strip().replace(',', '.'),
                'preset_mode': 'dark' if self.btn_mode_dark.isChecked() else 'std',
                'tune': self._video_tune_value(),
                'metric': self._video_metric_value(), 'target_metric': float(self.s_target_metric.value()),
                'vfade_in': bool(self.ck_vfade_in.isChecked()), 'vfade_in_d': float(self.s_vfade_in.value()),
                'vfade_out': bool(self.ck_vfade_out.isChecked()), 'vfade_out_d': float(self.s_vfade_out.value()),
                'crop_black': bool(self.ck_crop_black.isChecked())
            },
            'avif': {
                'limit': int(self.s_lim.value()) if self.ck_lim.isChecked() else 0,
                'adim': int(self.s_dim.value()) if self.ck_dim.isChecked() else 0,
                'awidth': int(self.s_width.value()) if self.ck_width.isChecked() else 0,
                'aheight': int(self.s_height.value()) if self.ck_height.isChecked() else 0,
                'aspd': int(self.sl_aspd.value()),
                'cq': int(self.s_cq.value()),
                'overwrite_src': bool(self.ck_overwrite_src.isChecked()),
                'fit_passes': int(self.s_passes.value()),
                'img_fmt': strip_default_tag(self.c_img_fmt.currentText()),
                'chroma': strip_default_tag(self.c_chroma.currentText()).replace(':', '')
            },
            'export_dir': self.export_dir or '',
            'priority': {'Низкий': 'low', 'Обычный': 'normal', 'Высокий': 'high'}.get(
                self.c_priority.currentText(), 'normal')
        }

    def _settings_sync_tick(self):
        """Пока воркер работает — подсовывает ему свежий словарь настроек (см.
        _collect_settings). ProcessWorker читает self.settings заново для КАЖДОГО
        файла (self.settings.get(...) внутри process_media), поэтому уже начатый
        файл фоновым перезапросом не затрагивается — досрочно подхватывают
        изменение только ещё не стартовавшие (в т.ч. добавленные во время работы)."""
        w = getattr(self, 'worker', None)
        if w is None or not w.isRunning():
            self._settings_sync_timer.stop()
            return
        try:
            w.settings = self._collect_settings()
        except Exception:
            pass

    def _run_items(self, target):
        if not target: return
        # Не запускаем второй воркер поверх активного (двойной клик во время работы)
        if getattr(self, 'worker', None) is not None:
            try:
                if self.worker.isRunning():
                    self.main.log("Дождитесь завершения текущей обработки.")
                    return
            except Exception: pass
        s = self._collect_settings()
        self.worker = ProcessWorker(target, s, removed_ids=self._removed_ids)
        self.worker.status.connect(self.on_stat); self.worker.progress.connect(self.on_prog)
        self.worker.log.connect(self.main.log); self.worker.finished_all.connect(self.done)
        self.worker.global_progress.connect(self.main.update_global_progress)
        self.worker.update_item_sig.connect(self.update_item_info); self.worker.update_lufs_sig.connect(self.update_lufs_columns)
        self.worker.update_dur_sig.connect(self.update_item_dur)
        self.worker.xpsnr_sig.connect(self.update_item_xpsnr)
        self.worker.active_threads.connect(self._on_active_threads)

        try:
            for itdata in target:
                if itdata.get('is_done'): continue
                iid = itdata.get('iid')
                item = self._find_item(iid)
                if item:
                    item.setData(0, ITEM_STATUS_ROLE, 'proc')
                    item.setText(6, "Ожидание")   # сброс прошлого «Готово»/«Ошибка»
                    item.setText(7, "—")
                # Сбрасываем прошлый замер времени — новый запуск считает с нуля.
                self._proc_started.pop(iid, None)
                self._proc_running.discard(iid)
            self.tree.viewport().update()
        except Exception: pass

        self.b_run.setEnabled(False); self.b_stop.setEnabled(True)
        self.worker.start()
        self._settings_sync_timer.start()

    def stop(self):
        if self.worker:
            try: self.worker.stop()
            except Exception: pass

    _RE_IMG_PASS = re.compile(r"картинки (\d+)/(\d+)")

    def on_stat(self, iid, txt, code):
        try:
            i = self._find_item(iid)
            if i:
                i.setData(0, ITEM_STATUS_ROLE, code)
                # Не показываем промежуточные подписи «Обработка.»/«Конвертация
                # картинки» — в колонке «Статус» сразу идут проценты (on_prog)
                # и финальные «Готово»/«Ошибка»/«Остановлено».
                if code != 'proc':
                    i.setText(6, txt)
                self.tree.viewport().update()
            # Подбор AVIF/WebP под лимит размера идёт несколькими проходами —
            # текст вида «Конвертация картинки N/total» несёт номер прохода,
            # который показываем рядом с временем (колонка «Время»).
            if code == 'proc':
                m = self._RE_IMG_PASS.search(txt or "")
                if m:
                    self._item_pass[iid] = f"{m.group(1)}/{m.group(2)}"
                    self._update_elapsed_text(iid)
            # Учёт времени перекодирования (колонка «Время»):
            #   proc      → засекаем старт (единожды) и запускаем тик-таймер;
            #   done/err  → фиксируем итог и больше не тикаем этот файл.
            if code == 'proc':
                self._start_elapsed(iid)
            elif code in ('done', 'err'):
                self._item_pass.pop(iid, None)
                self._freeze_elapsed(iid)
        except Exception: pass

    def on_prog(self, iid, val):
        try:
            i = self._find_item(iid)
            if i:
                i.setText(6, "Готово" if val >= 100 else f"{val}%")
            if val >= 100:
                self._freeze_elapsed(iid)
        except Exception: pass

    # ── Время перекодирования (колонка 7) ──────────────────────────────────────
    @staticmethod
    def _fmt_elapsed(sec) -> str:
        """Секунды → «мм:сс» (минуты и секунды через двоеточие)."""
        sec = max(0, int(sec))
        m, s = divmod(sec, 60)
        return f"{m:02d}:{s:02d}"

    def _elapsed_text_for(self, iid, elapsed_sec) -> str:
        """мм:сс + «(x/y)» прохода подбора картинки, если он сейчас идёт."""
        txt = self._fmt_elapsed(elapsed_sec)
        p = self._item_pass.get(iid)
        return f"{txt} ({p})" if p else txt

    def _update_elapsed_text(self, iid):
        """Перерисовывает колонку «Время» текущего файла (напр. когда сменился
        номер прохода, а не только тик таймера)."""
        start = self._proc_started.get(iid)
        if start is None:
            return
        i = self._find_item(iid)
        if i:
            i.setText(7, self._elapsed_text_for(iid, time.monotonic() - start))

    def _start_elapsed(self, iid):
        """Засекает старт перекодирования файла (если ещё не засечён) и
        включает таймер, который тикает время вверх до завершения."""
        if iid not in self._proc_started:
            self._proc_started[iid] = time.monotonic()
        self._proc_running.add(iid)
        i = self._find_item(iid)
        if i:
            i.setText(7, self._elapsed_text_for(iid, time.monotonic() - self._proc_started[iid]))
        if not self._elapsed_timer.isActive():
            self._elapsed_timer.start()

    def _tick_elapsed(self):
        """Раз в 0.5 с обновляет время у всех кодирующихся сейчас файлов."""
        now = time.monotonic()
        for iid in list(self._proc_running):
            i = self._find_item(iid)
            if i is None:
                self._proc_running.discard(iid)
                continue
            start = self._proc_started.get(iid)
            if start is not None:
                i.setText(7, self._elapsed_text_for(iid, now - start))
        if not self._proc_running:
            self._elapsed_timer.stop()

    def _freeze_elapsed(self, iid):
        """Фиксирует итоговое время файла и снимает его с тиканья (идемпотентно —
        повторные сигналы done/100% не пересчитывают и не сдвигают итог)."""
        self._proc_running.discard(iid)
        self._item_pass.pop(iid, None)
        start = self._proc_started.pop(iid, None)
        if start is not None:
            i = self._find_item(iid)
            if i:
                i.setText(7, self._fmt_elapsed(time.monotonic() - start))
        if not self._proc_running:
            self._elapsed_timer.stop()

    def _on_active_threads(self, n, m):
        try:
            # В простое показываем 0 из всех потоков ЦП машины (а не 0/0).
            total = m if m > 0 else self._cpu_threads
            self.lbl_threads.setText(f"Параллельных задач: {n}/{total}")
        except Exception: pass

    def done(self):
        self.b_run.setEnabled(True); self.b_stop.setEnabled(False)
        self._removed_ids.clear()
        # Страховка: фиксируем итоговое время по всем ещё «тикающим» файлам и
        # останавливаем таймер (на случай, если кто-то не прислал done/err).
        for iid in list(self._proc_running):
            self._freeze_elapsed(iid)
        self._elapsed_timer.stop()
        try: self.lbl_threads.setText(f"Параллельных задач: 0/{self._cpu_threads}")
        except Exception: pass
        self.main.log("Готово")
        try: play_done_sound()
        except Exception: pass

    def restart_gui(self):
        try:
            python = sys.executable; script = os.path.abspath(sys.argv[0])
            subprocess.Popen([python, script], cwd=os.getcwd())
        except Exception as e:
            self.main.log(f"Не удалось запустить новый процесс: {e}")
            return
        try:
            self.main.close()
            QTimer.singleShot(200, QApplication.quit)
        except Exception:
            try:
                QApplication.quit()
            except Exception:
                os._exit(0)


class Base64Tab(QWidget):
    """Вкладка кодирования любого файла в Base64."""
    _sig_done     = pyqtSignal(str, str, str)   # b64, size_str, txt_path
    _sig_error    = pyqtSignal(str)
    _sig_progress = pyqtSignal(int)             # 0-100, только из фонового потока

    # Расширения и их иконки — имена значков qtawesome (см. get_icon в config.py).
    _ICON_MAP = {
        # Видео
        '.mp4': 'fa5s.film', '.mkv': 'fa5s.film', '.avi': 'fa5s.film', '.mov': 'fa5s.film', '.webm': 'fa5s.film',
        '.flv': 'fa5s.film', '.wmv': 'fa5s.film', '.m4v': 'fa5s.film', '.ts': 'fa5s.film', '.mts': 'fa5s.film',
        '.m2ts': 'fa5s.film', '.vob': 'fa5s.film', '.ogv': 'fa5s.film', '.3gp': 'fa5s.film', '.3g2': 'fa5s.film',
        '.divx': 'fa5s.film', '.f4v': 'fa5s.film', '.mxf': 'fa5s.film', '.rm': 'fa5s.film', '.rmvb': 'fa5s.film',
        # Аудио
        '.mp3': 'fa5s.music', '.opus': 'fa5s.music', '.wav': 'fa5s.music', '.flac': 'fa5s.music', '.ogg': 'fa5s.music',
        '.aac': 'fa5s.music', '.m4a': 'fa5s.music', '.wma': 'fa5s.music', '.aiff': 'fa5s.music', '.aif': 'fa5s.music',
        '.ape': 'fa5s.music', '.mka': 'fa5s.music', '.mid': 'fa5s.music', '.midi': 'fa5s.music', '.amr': 'fa5s.music',
        '.ac3': 'fa5s.music', '.dts': 'fa5s.music', '.ra': 'fa5s.music', '.au': 'fa5s.music',
        # 3D / Игровые ассеты
        '.glb': 'fa5s.cube', '.gltf': 'fa5s.cube', '.obj': 'fa5s.cube', '.fbx': 'fa5s.cube', '.dae': 'fa5s.cube',
        '.3ds': 'fa5s.cube', '.stl': 'fa5s.cube', '.ply': 'fa5s.cube', '.blend': 'fa5s.cube', '.usdz': 'fa5s.cube',
        '.usd': 'fa5s.cube', '.abc': 'fa5s.cube', '.x3d': 'fa5s.cube', '.vrml': 'fa5s.cube', '.wrl': 'fa5s.cube',
        # Изображения (будут показываться как превью)
        '.jpg': None, '.jpeg': None, '.png': None, '.gif': None, '.webp': None,
        '.bmp': None, '.tiff': None, '.tif': None, '.avif': None, '.heic': None,
        '.heif': None, '.ico': None, '.svg': 'fa5s.image',
        # Документы
        '.pdf': 'fa5s.file-alt', '.doc': 'fa5s.file-alt', '.docx': 'fa5s.file-alt', '.xls': 'fa5s.file-alt', '.xlsx': 'fa5s.file-alt',
        '.ppt': 'fa5s.file-alt', '.pptx': 'fa5s.file-alt', '.txt': 'fa5s.file-alt', '.rtf': 'fa5s.file-alt', '.odt': 'fa5s.file-alt',
        '.ods': 'fa5s.file-alt', '.odp': 'fa5s.file-alt', '.csv': 'fa5s.file-alt', '.md': 'fa5s.file-alt',
        # Архивы
        '.zip': 'fa5s.file-archive', '.rar': 'fa5s.file-archive', '.7z': 'fa5s.file-archive', '.tar': 'fa5s.file-archive', '.gz': 'fa5s.file-archive',
        '.bz2': 'fa5s.file-archive', '.xz': 'fa5s.file-archive', '.zst': 'fa5s.file-archive', '.lz4': 'fa5s.file-archive',
        # Шрифты
        '.ttf': 'fa5s.font', '.otf': 'fa5s.font', '.woff': 'fa5s.font', '.woff2': 'fa5s.font', '.eot': 'fa5s.font',
        # Код / данные
        '.json': 'fa5s.database', '.xml': 'fa5s.database', '.yaml': 'fa5s.database', '.yml': 'fa5s.database', '.toml': 'fa5s.database',
        '.bin': 'fa5s.database', '.dat': 'fa5s.database', '.db': 'fa5s.database', '.sqlite': 'fa5s.database', '.proto': 'fa5s.database',
        # Игровые / движковые форматы
        '.pak': 'fa5s.gamepad', '.vpk': 'fa5s.gamepad', '.bsp': 'fa5s.gamepad', '.mdl': 'fa5s.gamepad', '.vtf': 'fa5s.gamepad',
        '.vmt': 'fa5s.gamepad', '.prefab': 'fa5s.gamepad', '.asset': 'fa5s.gamepad', '.unity': 'fa5s.gamepad',
        # Прочее
        '.iso': 'fa5s.compact-disc', '.img': 'fa5s.compact-disc', '.dmg': 'fa5s.compact-disc',
    }

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._stop_flag = threading.Event()
        self._sig_done.connect(self._on_done)
        self._sig_error.connect(self._on_error)
        self._sig_progress.connect(self.progress_update)
        self._current_path = ""
        self._build_ui()

    def progress_update(self, pct: int):
        self.progress.setValue(pct)

    def add_paths(self, paths):
        """Принимает один или несколько файлов. Если передано несколько и среди
        них есть HTML — маскирует все HTML-файлы сразу; иначе берёт первый файл."""
        self._route_paths(paths)

    def _route_paths(self, paths):
        paths = [p for p in (paths or []) if p]
        if not paths:
            return
        html = [p for p in paths
                if os.path.splitext(p)[1].lower() in (".html", ".htm")]
        if len(paths) > 1 and html:
            # Показываем первый HTML для превью и сразу маскируем все HTML-файлы.
            self._set_path(html[0])
            self._mask_paths(html)
        else:
            self._set_path(paths[0])

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Верхний блок: миниатюра + кнопки ────────────────────────────────
        top = QHBoxLayout()

        # Миниатюра — принимает дроп
        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(120, 90)
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thumb.setStyleSheet(
            "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; color:#6c7086; font-size:11px;")
        self.lbl_thumb.setText("нет\nфайла")
        top.addWidget(self.lbl_thumb)

        top.addSpacing(12)

        # Правая колонка: имя файла + кнопки
        right = QVBoxLayout()
        self.lbl_fname = QLabel("Файл не выбран")
        self.lbl_fname.setStyleSheet("color:#cdd6f4; font-size:12px;")
        self.lbl_fname.setWordWrap(True)
        right.addWidget(self.lbl_fname)

        self.lbl_hint = QLabel(status_html('fa5s.lightbulb',
            "Перетащите файл (или сразу несколько HTML) из любой "
            "вкладки или с рабочего стола", '#6c7086', 11))
        self.lbl_hint.setStyleSheet("color:#6c7086; font-size:10px;")
        right.addWidget(self.lbl_hint)
        right.addStretch()

        btn_row = QHBoxLayout()
        btn_browse = _icon_btn("Выбрать файл", 'fa5s.folder-open')
        btn_browse.clicked.connect(self._browse)

        # Кнопка «Кодировать» убрана: файлы кодируются автоматически при
        # добавлении (drag&drop / «Выбрать файл»).
        self.btn_stop = _icon_btn("Очистить", 'fa5s.trash')
        self.btn_stop.setFixedHeight(32)
        self.btn_stop.setEnabled(True)
        self.btn_stop.clicked.connect(self._clear_result)

        btn_row.addWidget(btn_browse)
        btn_row.addWidget(self.btn_stop)
        right.addLayout(btn_row)

        # ── Маскировка HTML под VK (скрытие JS) ─────────────────────────────
        mask_row = QHBoxLayout()
        self.btn_mask_file = _icon_btn("Замаскировать HTML (JavaScript) для VK", 'fa5s.mask')
        self.btn_mask_file.setFixedHeight(32)
        self.btn_mask_file.setToolTip("Прячет JavaScript, чтобы обойти запрет VK")
        self.btn_mask_file.clicked.connect(self._mask_current_html)

        self.btn_mask_folder = _icon_btn("Замаскировать все HTML (JavaScript) в папке для VK", 'fa5s.mask')
        self.btn_mask_folder.setFixedHeight(32)
        self.btn_mask_folder.setToolTip(
            "Пакетно обрабатывает все .html в выбранной папке.\n"
            "Оригиналы не трогаются — результат в подпапке encoded\\")
        self.btn_mask_folder.clicked.connect(self._mask_folder_html)

        mask_row.addWidget(self.btn_mask_file)
        mask_row.addWidget(self.btn_mask_folder)
        right.addLayout(mask_row)

        # Галочка: переименовывать ли выходной HTML (добавлять суффикс _base).
        # Включена — поведение как раньше (<имя>_base.html).
        # Выключена — файл на выходе сохраняет оригинальное имя (<имя>.html).
        self.chk_rename_html = QCheckBox("Переименовывать выходной HTML (суффикс _base)")
        self.chk_rename_html.setChecked(True)
        self.chk_rename_html.setToolTip(
            "Включено: результат маскировки называется <имя>_base.html.\n"
            "Выключено: выходной HTML сохраняет оригинальное имя <имя>.html.")
        right.addWidget(self.chk_rename_html)

        top.addLayout(right, 1)
        root.addLayout(top)

        # ── Прогресс-бар ─────────────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        self.progress.hide()
        root.addWidget(self.progress)

        # ── Результат ─────────────────────────────────────────────────────────
        grp_out = QGroupBox("Результат (Base64)")
        vl = QVBoxLayout(grp_out)

        self.txt_out = QPlainTextEdit()
        self.txt_out.setReadOnly(True)
        self.txt_out.setPlaceholderText("Здесь появится Base64-строка после кодирования…")
        self.txt_out.setFont(QFont("Courier New", 9))
        self.txt_out.setMinimumHeight(80)
        self.txt_out.setMaximumHeight(260)
        vl.addWidget(self.txt_out)

        # Сохранять ли результат в <имя>_base64.txt рядом с файлом.
        # По умолчанию ВЫКЛ — base64 копируется в буфер и показан в поле,
        # лишний .txt на диск не пишется.
        self.chk_make_txt = QCheckBox("Создавать .txt файл")
        self.chk_make_txt.setChecked(False)
        self.chk_make_txt.setToolTip(
            "Включено: рядом с файлом сохраняется <имя>_base64.txt.\n"
            "Выключено: результат только в этом поле и в буфере обмена.")
        vl.addWidget(self.chk_make_txt)

        h_btns = QHBoxLayout()
        self.lbl_size = QLabel("")
        self.lbl_size.setStyleSheet("color:#6c7086; font-size:11px;")
        btn_copy = _icon_btn("Копировать", 'fa5s.copy')
        btn_copy.setFixedWidth(130)
        btn_copy.clicked.connect(self._copy)
        h_btns.addWidget(self.lbl_size)
        h_btns.addStretch()
        h_btns.addWidget(btn_copy)
        vl.addLayout(h_btns)

        root.addWidget(grp_out, 1)
        self.setAcceptDrops(True)

    # ── Drag & drop ───────────────────────────────────────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls: self._route_paths(urls)

    # ── Вспомогательные ──────────────────────────────────────────────────────
    def _browse(self):
        # Строим фильтры: популярные группы + «Все файлы»
        media   = "Медиафайлы (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv *.m4v *.ts *.3gp *.mp3 *.opus *.wav *.flac *.ogg *.aac *.m4a *.wma *.aiff)"
        images  = "Изображения (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.tiff *.avif *.heic *.heif *.ico *.svg)"
        model3d = "3D / Игровые ассеты (*.glb *.gltf *.obj *.fbx *.dae *.3ds *.stl *.ply *.blend *.usdz *.usd *.abc *.pak *.vpk *.bsp *.mdl *.vtf *.prefab *.asset)"
        docs    = "Документы (*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.txt *.rtf *.odt *.csv *.md *.json *.xml *.yaml *.yml *.toml)"
        fonts   = "Шрифты (*.ttf *.otf *.woff *.woff2 *.eot)"
        archives= "Архивы (*.zip *.rar *.7z *.tar *.gz *.bz2 *.xz *.zst)"
        other   = "Прочее (*.bin *.dat *.db *.sqlite *.iso *.img *.dmg)"
        html    = "HTML (*.html *.htm)"
        all_f   = "Все файлы (*)"
        flt = ";;".join([media, images, model3d, docs, fonts, archives, html, other, all_f])
        # Можно выбрать несколько файлов: несколько HTML маскируются разом.
        paths, _ = QFileDialog.getOpenFileNames(self, "Выбрать файл(ы) для кодирования в Base64", "", flt)
        if paths: self._route_paths(paths)

    def _set_path(self, path):
        self._current_path = path
        self.lbl_fname.setText(os.path.basename(path))
        self.lbl_hint.hide()
        self.txt_out.clear()
        self.lbl_size.setText("")
        self._load_thumb(path)
        # HTML-файлы предназначены для маскировки под VK, а не для обычного
        # base64: НЕ запускаем авто-кодирование (никаких .txt и дампа base64 в
        # GUI) — пользователь жмёт «🎭 Замаскировать HTML (JavaScript) для VK».
        if os.path.splitext(path)[1].lower() in (".html", ".htm"):
            self.lbl_size.setText("HTML готов — нажмите «Замаскировать HTML (JavaScript) для VK»")
        else:
            # Для прочих файлов — авто-кодирование сразу после выбора
            QTimer.singleShot(80, self._start_encode)

    def _load_thumb(self, path):
        ext = os.path.splitext(path)[1].lower()
        icon_val = self._ICON_MAP.get(ext, 'fa5s.box')  # fa5s.box — для неизвестных

        # Изображения — показываем превью
        img_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
                    '.tiff', '.tif', '.avif', '.heic', '.heif', '.ico'}
        if ext in img_exts:
            pix = QPixmap()
            if Image:
                try:
                    with Image.open(path) as im:
                        if ImageOps: im = ImageOps.exif_transpose(im)
                        im.thumbnail((240, 180))
                        bio = io.BytesIO()
                        im.convert("RGBA").save(bio, "PNG")
                        pix.loadFromData(QByteArray(bio.getvalue()))
                except Exception:
                    pass
            if pix.isNull():
                pix = QPixmap(path)
            if not pix.isNull():
                self.lbl_thumb.setPixmap(
                    pix.scaled(120, 90, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
                return

        # Видео — пытаемся вытащить кадр через ffmpeg
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv',
                      '.m4v', '.ts', '.mts', '.m2ts', '.vob', '.ogv', '.3gp',
                      '.3g2', '.divx', '.f4v', '.mxf', '.rm', '.rmvb'}
        if ext in video_exts:
            pix = QPixmap()
            try:
                tmp = os.path.join(tempfile.gettempdir(), f"ym_b64_thumb_{uuid.uuid4().hex}.jpg")
                subprocess.run([FFMPEG, "-y", "-i", path, "-vframes", "1", "-q:v", "5", tmp],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=CREATE_NO_WINDOW, timeout=8)
                if os.path.exists(tmp):
                    pix = QPixmap(tmp)
                    try: os.remove(tmp)
                    except Exception: pass
            except Exception:
                pass
            if not pix.isNull():
                self.lbl_thumb.setPixmap(
                    pix.scaled(120, 90, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
                return

        # Для всего остального — большой векторный значок типа файла + расширение.
        icon_name = icon_val if icon_val else 'fa5s.box'
        ext_upper = ext.upper().lstrip('.') if ext else '??'
        self.lbl_thumb.setText(
            f"{icon_html(icon_name, 30, '#89b4fa')}<br>{ext_upper}")
        self.lbl_thumb.setStyleSheet(
            "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; "
            "color:#89b4fa; font-size:18px; qproperty-alignment: AlignCenter;")

    def _copy(self):
        text = self.txt_out.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.main.log("Base64 скопирован в буфер обмена")

    # ── Маскировка HTML под VK ───────────────────────────────────────────────
    @staticmethod
    def _read_html(path):
        # utf-8-sig снимает возможный BOM; ошибки декодирования не роняют процесс
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read()

    def _mask_one(self, src):
        """Маскирует один HTML-файл → encoded\\<имя>[_base].html.
        Возвращает (out_path, n_in, n_ext)."""
        masked, n_in, n_ext = mask_html_js(self._read_html(src))
        base, ext = os.path.splitext(os.path.basename(src))
        out_dir = os.path.join(os.path.dirname(src), "encoded")
        os.makedirs(out_dir, exist_ok=True)
        suffix = "_base" if self.chk_rename_html.isChecked() else ""
        out_path = os.path.join(out_dir, base + suffix + ext)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(masked)
        return out_path, n_in, n_ext

    def _mask_paths(self, paths):
        """Пакетно маскирует переданный список HTML-файлов (из разных папок)."""
        files = [p for p in paths
                 if os.path.isfile(p)
                 and os.path.splitext(p)[1].lower() in (".html", ".htm")]
        if not files:
            self.lbl_size.setText(status_html('fa5s.exclamation-triangle', "Среди файлов нет .html", '#f9e2af'))
            return
        if len(files) == 1:
            # Один файл — показываем подробный отчёт как для одиночной маскировки.
            self._set_path(files[0])
            self._mask_current_html()
            return
        done = skipped = errors = 0
        report = [f"🎭 Маскировка HTML-файлов: {len(files)} шт.", ""]
        for src in files:
            try:
                out_path, n_in, n_ext = self._mask_one(src)
                if n_in or n_ext:
                    done += 1
                    report.append(f"✅ {os.path.basename(src)} — инлайн {n_in}, внешних {n_ext}")
                    self.main.log(f"HTML→VK: {os.path.basename(src)} (инлайн {n_in}, внешних {n_ext})")
                else:
                    skipped += 1
                    report.append(f"➖ {os.path.basename(src)} — нет <script>, копия")
                    self.main.log(f"HTML→VK: {os.path.basename(src)} — нет <script>, копия")
            except Exception as ex:
                errors += 1
                report.append(f"❌ {os.path.basename(src)} — {ex}")
                self.main.log(f"HTML→VK: {os.path.basename(src)} — ошибка: {ex}")
        self.txt_out.setPlainText("\n".join(report))
        self.lbl_size.setText(
            status_html('fa5s.check-circle', f"Готово: замаскировано {done}, без скриптов {skipped}, ошибок {errors} → encoded\\", '#a6e3a1'))
        self.main.log(f"HTML→VK: пакет из {len(files)} файлов — {done} замаскировано, "
                      f"{skipped} без скриптов, {errors} ошибок.")

    def _mask_current_html(self):
        """Маскирует текущий выбранный HTML-файл → encoded\\<имя>_base.html."""
        path = self._current_path
        if not path or not os.path.isfile(path):
            self.lbl_size.setText(status_html('fa5s.times-circle', "Сначала выберите .html файл", '#f38ba8'))
            self.main.log("HTML→VK: файл не выбран")
            return
        if os.path.splitext(path)[1].lower() not in (".html", ".htm"):
            self.lbl_size.setText(status_html('fa5s.times-circle', "Это не HTML-файл (нужен .html / .htm)", '#f38ba8'))
            self.main.log("HTML→VK: выбран не HTML-файл")
            return
        try:
            out_path, n_in, n_ext = self._mask_one(path)
            if n_in == 0 and n_ext == 0:
                self.lbl_size.setText(status_html('fa5s.exclamation-triangle', "В файле нет <script> — скопировано как есть", '#f9e2af'))
                self.main.log("HTML→VK: тегов <script> не найдено")
                return
            self.txt_out.setPlainText(
                "✅ HTML замаскирован под VK\n"
                f"Исходник:  {os.path.basename(path)}\n"
                f"Результат: encoded\\{os.path.basename(out_path)}\n\n"
                f"Закодировано инлайн-скриптов: {n_in}\n"
                f"Внешних <script src> → динамическая загрузка: {n_ext}\n\n"
                "Что сделано:\n"
                "• теги <script> удалены из разметки;\n"
                "• тело JS закодировано в base64;\n"
                "• запуск повешен на onload скрытой картинки;\n"
                "• инлайн onclick=… сохранены (код исполняется в глобале).")
            self.lbl_size.setText(
                status_html('fa5s.check-circle', f"encoded\\{os.path.basename(out_path)}  •  инлайн: {n_in}, внешних: {n_ext}", '#a6e3a1'))
            self.main.log(f"HTML→VK: {os.path.basename(path)} → {out_path} "
                          f"(инлайн {n_in}, внешних {n_ext})")
        except Exception as ex:
            self.lbl_size.setText(status_html('fa5s.times-circle', f"{ex}", '#f38ba8'))
            self.main.log(f"HTML→VK error: {ex}")

    def _mask_folder_html(self):
        """Пакетно маскирует все .html в выбранной папке → подпапка encoded\\."""
        folder = QFileDialog.getExistingDirectory(self, "Папка с HTML-файлами для маскировки", "")
        if not folder:
            return
        try:
            files = [f for f in os.listdir(folder)
                     if f.lower().endswith((".html", ".htm"))]
        except Exception as ex:
            self.lbl_size.setText(status_html('fa5s.times-circle', f"{ex}", '#f38ba8'))
            self.main.log(f"HTML→VK error: {ex}")
            return
        if not files:
            self.lbl_size.setText(status_html('fa5s.exclamation-triangle', "В папке нет .html файлов", '#f9e2af'))
            self.main.log("HTML→VK: в папке нет .html")
            return

        out_dir = os.path.join(folder, "encoded")
        os.makedirs(out_dir, exist_ok=True)
        done = skipped = errors = 0
        report = [f"📁 {folder}", f"→ {out_dir}", ""]
        for name in files:
            src = os.path.join(folder, name)
            try:
                masked, n_in, n_ext = mask_html_js(self._read_html(src))
                stem, ext = os.path.splitext(name)
                suffix = "_base" if self.chk_rename_html.isChecked() else ""
                with open(os.path.join(out_dir, stem + suffix + ext), "w", encoding="utf-8") as f:
                    f.write(masked)
                if n_in or n_ext:
                    done += 1
                    report.append(f"✅ {name} — инлайн {n_in}, внешних {n_ext}")
                    self.main.log(f"HTML→VK: {name} (инлайн {n_in}, внешних {n_ext})")
                else:
                    skipped += 1
                    report.append(f"➖ {name} — нет <script>, скопировано как есть")
                    self.main.log(f"HTML→VK: {name} — нет <script>, копия")
            except Exception as ex:
                errors += 1
                report.append(f"❌ {name} — {ex}")
                self.main.log(f"HTML→VK: {name} — ошибка: {ex}")

        self.txt_out.setPlainText("\n".join(report))
        self.lbl_size.setText(status_html('fa5s.check-circle',
            f"Готово: замаскировано {done}, без скриптов {skipped}, ошибок {errors} → encoded\\", '#a6e3a1'))
        self.main.log(f"HTML→VK: папка обработана — {done} замаскировано, "
                      f"{skipped} без скриптов, {errors} ошибок. Результат: {out_dir}")

    # ── Кодирование ──────────────────────────────────────────────────────────
    def _start_encode(self):
        path = self._current_path
        if not path or not os.path.isfile(path):
            self.main.log("Base64: файл не выбран или не существует")
            return
        self._stop_flag.clear()
        self.txt_out.clear()
        self.lbl_size.setText("Чтение файла…")
        self.progress.setValue(0)
        self.progress.show()
        make_txt = self.chk_make_txt.isChecked()  # читаем до старта потока

        def _worker():
            try:
                total = os.path.getsize(path)
                CHUNK = 256 * 1024  # 256 КБ
                chunks = []
                read = 0
                with open(path, "rb") as f:
                    while True:
                        if self._stop_flag.is_set():
                            self._sig_error.emit("Отменено пользователем")
                            return
                        chunk = f.read(CHUNK)
                        if not chunk: break
                        chunks.append(chunk)
                        read += len(chunk)
                        pct = int(read * 100 / total) if total else 0
                        self._sig_progress.emit(pct)

                raw = b"".join(chunks)
                if self._stop_flag.is_set():
                    self._sig_error.emit("Отменено пользователем")
                    return

                b64 = base64.b64encode(raw).decode("ascii")

                txt_path = ""
                if make_txt:
                    base_name = os.path.splitext(os.path.basename(path))[0]
                    txt_path = os.path.join(os.path.dirname(path), base_name + "_base64.txt")
                    with open(txt_path, "w", encoding="ascii") as f:
                        f.write(b64)

                size_kb = len(b64) / 1024
                size_str = (f"{size_kb/1024:.2f} МБ" if size_kb >= 1024 else f"{size_kb:.1f} КБ")
                self._sig_done.emit(b64, size_str, txt_path)
            except Exception as ex:
                self._sig_error.emit(str(ex))

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_encode(self):
        self._stop_flag.set()

    def _clear_result(self):
        """Очищает поле результата, сбрасывает превью и прогресс."""
        self._stop_flag.set()  # останавливает фоновый поток если идёт кодирование
        self.txt_out.clear()
        self.lbl_size.setText("")
        self.lbl_fname.setText("Файл не выбран")
        self.lbl_thumb.setPixmap(QPixmap())
        self.lbl_thumb.setText("нет\nфайла")
        self.lbl_thumb.setStyleSheet(
            "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; color:#6c7086; font-size:11px;")
        self.lbl_hint.show()
        self.progress.hide()
        self.progress.setValue(0)
        self._current_path = ""

    def _on_done(self, b64: str, size_str: str, txt_path: str):
        self.txt_out.setPlainText(b64)
        self.progress.setValue(100)
        self.progress.hide()
        # Автокопирование в буфер обмена
        QApplication.clipboard().setText(b64)
        if txt_path:
            self.lbl_size.setText(status_html('fa5s.check-circle', f"Скопировано! Размер: {size_str}  •  {os.path.basename(txt_path)}", '#a6e3a1'))
            self.main.log(f"Base64 готов ({size_str}), скопирован в буфер, сохранён: {txt_path}")
        else:
            self.lbl_size.setText(status_html('fa5s.check-circle', f"Скопировано! Размер: {size_str}", '#a6e3a1'))
            self.main.log(f"Base64 готов ({size_str}), скопирован в буфер")

    def _on_error(self, msg: str):
        self.lbl_size.setText(status_html('fa5s.times-circle', f"{msg}", '#f38ba8'))
        self.progress.hide()
        self.main.log(f"Base64: {msg}")


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


class _JumpSlider(QSlider):
    """QSlider, который при клике по дорожке СРАЗУ прыгает в точку клика.
    Стандартный QSlider лишь шагает на pageStep — поэтому при значении 100 и
    клике у отметки 10 ползунок «полз» к 80, а не вставал на 10. Здесь клик и
    протаскивание по дорожке выставляют значение по позиции курсора."""

    def _value_at(self, ev):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self)
        if self.orientation() == Qt.Orientation.Horizontal:
            pos = int(ev.position().x() - groove.x() - handle.width() / 2)
            span = groove.width() - handle.width()
        else:
            pos = int(ev.position().y() - groove.y() - handle.height() / 2)
            span = groove.height() - handle.height()
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), pos, max(1, span), opt.upsideDown)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(ev))
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(ev))
            ev.accept()
            return
        super().mouseMoveEvent(ev)



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

    def keyPressEvent(self, ev):
        # Резерв: WASD/стрелки панорамируют, даже если фокус не на холсте (клавиши
        # всплывают сюда от кнопок панели). Ctrl не трогаем (Ctrl+Z/Y и пр.).
        mods = ev.modifiers()
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


class PromptTab(QWidget):
    """Вкладка с промптами из произвольного .txt файла, выбранного пользователем.
    Последний выбранный файл запоминается в настройках и подгружается при старте."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checkboxes = []  # list of QCheckBox, each has ._full_text attribute
        # Последний выбранный файл (любой .txt) — из настроек; по умолчанию пусто.
        try:
            self._prompt_path = load_settings().get("prompt_file", "") or ""
        except Exception:
            self._prompt_path = ""
        self._build_ui()
        self._load_prompts()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        lbl = QLabel("Промпты для SiGame-игр:")
        lbl.setStyleSheet("font-weight:bold; color:#89b4fa; font-size:14px;")
        top.addWidget(lbl)
        top.addStretch()

        btn_all = _icon_btn("Все", 'fa5s.check')
        btn_all.setFixedWidth(72)
        btn_all.clicked.connect(self._select_all)
        btn_none = _icon_btn("Снять", 'fa5s.times')
        btn_none.setFixedWidth(72)
        btn_none.clicked.connect(self._select_none)
        self.btn_copy_sel = _icon_btn("Копировать выбранные", 'fa5s.copy')
        self.btn_copy_sel.clicked.connect(self._copy_selected)
        btn_pick = _icon_btn("Выбрать файл", 'fa5s.folder-open')
        btn_pick.setToolTip("Загрузить промпты из любого .txt файла")
        btn_pick.clicked.connect(self._choose_prompt_file)
        btn_reload = _icon_btn("Обновить", 'fa5s.sync-alt')
        btn_reload.clicked.connect(self._load_prompts)

        top.addWidget(btn_all)
        top.addWidget(btn_none)
        top.addWidget(self.btn_copy_sel)
        top.addWidget(btn_pick)
        top.addWidget(btn_reload)
        root.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cb_widget = QWidget()
        self._cb_layout = QVBoxLayout(self._cb_widget)
        self._cb_layout.setContentsMargins(4, 4, 4, 4)
        self._cb_layout.setSpacing(2)

        # Подсказка на пустом поле — как пользоваться вкладкой.
        self._empty_hint = QLabel(
            "Как это работает\n\n"
            "• Нажмите «Выбрать файл» и укажите любой .txt с промптами.\n"
            "   Выбранный файл запоминается и подгружается при следующем запуске.\n"
            "• Каждый пункт, начинающийся с «1)», «2)», «3)» … — отдельный промпт.\n"
            "   Файл без такой нумерации показывается одним цельным промптом.\n"
            "• Отметьте нужные галочками и нажмите «Копировать выбранные» —\n"
            "   они скопируются в буфер обмена (через пустую строку между собой).\n"
            "• «Обновить» — перечитать файл, если вы его изменили.\n\n"
            "Сейчас файл не выбран — нажмите «Выбрать файл».")
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet("color:#9399b2; font-size:12px; padding:8px 4px;")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._cb_layout.addWidget(self._empty_hint)

        self._cb_layout.addStretch()
        scroll.setWidget(self._cb_widget)
        root.addWidget(scroll)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#585b70; font-size:11px;")
        root.addWidget(self._status)

    def _load_prompts(self):
        # Удаляем только сами чекбоксы — подсказка _empty_hint и stretch остаются.
        for cb in self._checkboxes:
            self._cb_layout.removeWidget(cb)
            cb.deleteLater()
        self._checkboxes.clear()

        if not self._prompt_path:
            self._status.setText("Файл не выбран — нажмите «Выбрать файл»")
            self._empty_hint.setVisible(True)
            return
        if not os.path.exists(self._prompt_path):
            self._status.setText(f"Файл не найден: {self._prompt_path}")
            self._empty_hint.setVisible(True)
            return
        try:
            with open(self._prompt_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self._status.setText(f"Ошибка чтения: {e}")
            self._empty_hint.setVisible(True)
            return

        sections = self._parse_sections(content)
        # Файл без нумерованных секций (N)) — показываем как один цельный промпт
        if not sections and content.strip():
            sections = [(os.path.basename(self._prompt_path), content.strip())]

        # Чекбоксы вставляем перед stretch (последний элемент), но после подсказки.
        for title, body in sections:
            cb = QCheckBox(title)
            cb.setStyleSheet("font-size:13px; padding:5px 2px;")
            cb._full_text = title + "\n" + body  # type: ignore[attr-defined]
            self._checkboxes.append(cb)
            self._cb_layout.insertWidget(self._cb_layout.count() - 1, cb)

        # Подсказку показываем, только когда промптов нет.
        self._empty_hint.setVisible(not self._checkboxes)
        self._status.setText(f"{len(self._checkboxes)} промптов  ·  {os.path.basename(self._prompt_path)}")

    def _choose_prompt_file(self):
        start_dir = os.path.dirname(self._prompt_path) if self._prompt_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл с промптами", start_dir,
            "Текстовые файлы (*.txt);;Все файлы (*.*)")
        if path:
            self._prompt_path = path
            # Запоминаем выбор в общих настройках (merge, чтобы не затереть прочее).
            try:
                s = load_settings(); s["prompt_file"] = path; save_settings(s)
            except Exception:
                pass
            self._load_prompts()

    def _parse_sections(self, text):
        sections = []
        current_title = None
        current_lines = []
        for line in text.splitlines():
            if re.match(r'^\d+\)', line.strip()):
                if current_title is not None:
                    sections.append((current_title, "\n".join(current_lines).strip()))
                current_title = line.strip()
                current_lines = []
            else:
                if current_title is not None:
                    current_lines.append(line)
        if current_title is not None:
            sections.append((current_title, "\n".join(current_lines).strip()))
        return sections

    def _select_all(self):
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _select_none(self):
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _copy_selected(self):
        parts = [cb._full_text for cb in self._checkboxes if cb.isChecked()]  # type: ignore[attr-defined]
        if not parts:
            self._status.setText("Ничего не выбрано")
            return
        QApplication.clipboard().setText("\n\n".join(parts))
        n = len(parts)
        suffix = "а" if n in (2, 3, 4) else "ов" if n != 1 else ""
        orig = self.btn_copy_sel.text()
        self.btn_copy_sel.setText(f"Скопировано {n} пункт{suffix}!")
        QTimer.singleShot(2000, lambda: self.btn_copy_sel.setText(orig))
        self._status.setText(f"Скопировано {n} пункт{suffix} в буфер")
