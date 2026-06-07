# -*- coding: utf-8 -*-
# widgets.py — кастомные виджеты, делегаты, превью, info-подсказки
from config import *
from utils import *


class StatusColorDelegate(QStyledItemDelegate):
    """Делегат, рисующий цветной фон строки независимо от стилшита.
    
    Стилшит: ::item:selected и ::item:hover — transparent.
    Все фоны рисуем здесь вручную, чтобы цвет статуса всегда был виден.
    """
    _colors  = {'proc': COLOR_PROC, 'done': COLOR_DONE, 'err': COLOR_ERR}
    _SEL_BG  = QColor(0x45, 0x47, 0x5a)   # обычное выделение (#45475a)
    _HOV_BG  = QColor(0x31, 0x32, 0x44)   # hover (#313244)

    def paint(self, painter, option, index):
        src = index.sibling(index.row(), 0)
        status = src.data(ITEM_STATUS_ROLE)
        color  = self._colors.get(status)
        is_sel = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hov = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if color:
            # Цветная строка: всегда показываем статус-цвет
            if is_sel:
                # Полная непрозрачность при выделении — делаем копию только тогда
                bg = QColor(color)
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

        # Рисуем текст / иконку поверх нашего фона
        super().paint(painter, option, index)

        # Белая рамка = индикатор выделения для цветных строк
        if color and is_sel:
            painter.save()
            pen = QPen(QColor(255, 255, 255, 210))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()


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
class _InfoBadge(QLabel):
    """Маленький значок ⓘ. При наведении показывает описание (tooltip).

    Стандартный QToolTip иногда не успевает показаться на крошечном виджете,
    поэтому при входе курсора и по клику принудительно вызываем QToolTip.showText —
    подсказка появляется мгновенно и стабильно.
    Чтобы изменить текст подсказки — правьте строку, передаваемую в info_badge()
    (или label_with_info / row_with_info) в файле tabs.py.
    """
    def __init__(self, tip: str):
        super().__init__("ⓘ")
        self._tip = tip
        self.setObjectName("infoBadge")
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setFixedSize(20, 20)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def enterEvent(self, e):
        try: QToolTip.showText(QCursor.pos(), self._tip, self)
        except Exception: pass
        super().enterEvent(e)

    def mousePressEvent(self, e):
        try: QToolTip.showText(QCursor.pos(), self._tip, self)
        except Exception: pass
        super().mousePressEvent(e)


def info_badge(tip: str) -> QLabel:
    """Возвращает значок-подсказку ⓘ. Текст подсказки = аргумент tip.

    Чтобы УБРАТЬ значок где-то — удалите вызов info_badge(...) в tabs.py
    (а для label_with_info/row_with_info — замените их на обычный QLabel/виджет)."""
    return _InfoBadge(tip)


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
            req = urllib.request.Request(self.url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req) as r, open(tmp, 'wb') as f:
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
    в GUI-поток через сигнал. QPixmap нельзя создавать вне主-потока, поэтому
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
            if ext in ALLOWED_IMG and Image:
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
                for extra in ([], ["-vcodec", "libaom-av1"], ["-vcodec", "av1"]):
                    cmd = [FFMPEG, "-y", "-ss", "00:00:02"] + extra + [
                        "-i", self.path, "-vframes", "1", "-vf", "scale=96:-1", tmp]
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

    _ICON_VIDEO = "🎬"
    _ICON_IMAGE = "🖼"
    _ICON_AUDIO = "🎵"

    _thumb_ready = pyqtSignal(object, str)  # (bytes|None, dur_str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setFixedSize(108, 108)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(path)
        self._drag_start = None

        ext = os.path.splitext(path)[1].lower()
        is_img   = ext in ALLOWED_IMG
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

        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedSize(96, 72)
        self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_lbl.setStyleSheet("background:#1e1e1e;border-radius:3px;font-size:28px;")
        self._thumb_lbl.setText(self._type_icon)  # пока миниатюра не загружена
        tc_layout.addWidget(self._thumb_lbl)

        # Имя файла
        name = os.path.basename(path)
        short = (name[:15] + "…") if len(name) > 15 else name
        name_lbl = QLabel(f"{self._type_icon} {short}")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(False)
        name_lbl.setStyleSheet("color:#ccc;font-size:8px;")
        name_lbl.setToolTip(name)

        layout.addWidget(thumb_container)
        layout.addWidget(name_lbl)

        self.setStyleSheet("RecentFileThumb{background:#2a2a2a;border-radius:5px;}"
                           "RecentFileThumb:hover{background:#363636;border:1px solid #555;}")

        # Загрузка миниатюры в фоне (через QThreadPool — НЕ блокирует GUI при старте)
        self._thumb_ready.connect(self._apply_thumb)
        QThreadPool.globalInstance().start(_RecentThumbWorker(self.path, self._thumb_ready))

    def _apply_thumb(self, data, dur_str):
        """Слот в GUI-потоке: строит QPixmap из байтов и рисует длительность."""
        try:
            if not data:
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
            self._thumb_lbl.setText("")
            self._thumb_lbl.setPixmap(pix)
        except Exception:
            pass

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.pos()

    def mouseMoveEvent(self, e):
        if self._drag_start and (e.pos() - self._drag_start).manhattanLength() > 8:
            from PyQt6.QtCore import QMimeData, QUrl
            from PyQt6.QtGui import QDrag
            drag = QDrag(self)
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(self.path)])
            drag.setMimeData(md)
            drag.exec(Qt.DropAction.CopyAction)
            self._drag_start = None

    def mouseDoubleClickEvent(self, e):
        try:
            p = self
            while p and not hasattr(p, 'add_paths'):
                p = p.parent()
            if p: p.add_paths([self.path])
        except Exception: pass


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

        self._lbl_empty = QLabel("Нет медиафайлов в папке загрузок")
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setStyleSheet("color:#666;font-size:10px;")
        self._row.insertWidget(0, self._lbl_empty)

        # Таймер автообновления
        self._timer = QTimer(self)
        self._timer.setInterval(5000)  # каждые 5 секунд
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def wheelEvent(self, event):
        """Колесо мыши — горизонтальная прокрутка стрипа."""
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y() // 2)
        event.accept()

    @classmethod
    def _get_all_ext(cls):
        if cls._ALL_EXT is None:
            cls._ALL_EXT = ALLOWED_MEDIA | ALLOWED_IMG
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

    def refresh(self, folder: str):
        """Вызывается вручную при смене папки."""
        self._folder = folder
        new_paths = self._scan()
        self._apply(new_paths)

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
    """QTreeWidget с поддержкой drag-and-drop файлов наружу (по tooltip = полный путь)."""

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


# ─────────────────────────────────────────────────────────────
#  Photo Merger Tab  (вкладка объединения фотографий)
# ─────────────────────────────────────────────────────────────
class PhotoDragList(QTreeWidget):
    """Список с drag-and-drop файлов извне + перестановка внутри."""

    VALID_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff',
                  '.webp', '.avif', '.heic', '.heif', '.ico'}

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
            QTreeWidget::item:selected { background-color: #45475a; }
            QTreeWidget::item:hover    { background-color: #313244; }
        """)

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

                # thumbnail
                pix = QPixmap(p)
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

    def mark_processed(self, items, color: QColor):
        for it in items:
            it.setData(0, Qt.ItemDataRole.UserRole + 1, "processed")
            it.setText(2, "✓ готово")
            for col in range(3):
                it.setBackground(col, QBrush(color))
