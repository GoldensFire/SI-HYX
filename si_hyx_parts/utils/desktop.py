# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Рабочий стол и картинки: QIcon из PIL, проводник, корзина, звук, SVG. Public namespace: utils."""
import utils as _api


def pil_to_qicon(img):
    if not _api.Image or img is None: return _api.QIcon()
    try:
        bio = _api.io.BytesIO()
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        img.save(bio, format="PNG")
        data = bio.getvalue()
        pix = _api.QPixmap()
        if pix.loadFromData(_api.QByteArray(data)): return _api.QIcon(pix)
        else:
            qimg = _api.QtGuiImage.fromData(data)
            return _api.QIcon(_api.QPixmap.fromImage(qimg))
    except Exception:
        return _api.QIcon()

pil_to_qicon.__module__ = _api.__name__
_api.pil_to_qicon = pil_to_qicon

def reveal_in_explorer(path) -> bool:
    """Открывает файловый менеджер на файле и выделяет его. True — получилось.

    Аргументы списком тут не работают: subprocess склеивает командную строку по
    правилам Windows и берёт в кавычки токен ЦЕЛИКОМ —
    `"/select,C:\\путь с пробелами\\пак.siq"`. Explorer такое не разбирает и
    молча открывает папку по умолчанию («Документы»). Кавычки нужны только
    вокруг пути: `/select,"C:\\..."`. Отдельным аргументом «/select,» тоже
    нельзя — цель окажется пустой, и результат тот же.
    """
    try:
        target = _api.os.path.normpath(_api.os.path.abspath(str(path)))
    except Exception:
        return False
    if not _api.os.path.exists(target):
        return False
    try:
        if _api.os.name == 'nt':
            _api.subprocess.Popen(f'explorer /select,"{target}"')
        elif _api.sys.platform == 'darwin':
            _api.subprocess.Popen(['open', '-R', target])
        else:
            _api.subprocess.Popen(['xdg-open', _api.os.path.dirname(target)])
    except Exception:
        return False
    return True

reveal_in_explorer.__module__ = _api.__name__
_api.reveal_in_explorer = reveal_in_explorer

def move_to_trash(path, hwnd=None):
    """Отправляет файл в Корзину (Windows) БЕЗ системного диалога подтверждения.
    Возвращает True при успехе. Реализовано через WinAPI SHFileOperationW с
    флагом FOF_ALLOWUNDO — это кладёт файл в Корзину (откуда его можно вернуть),
    а не удаляет безвозвратно; стороннюю зависимость (send2trash) не тянем.

    hwnd — HWND ОКНА-ВЛАДЕЛЬЦА операции (целое). Передавать обязательно
    top-level окно: если оставить NULL, SHFileOperation берёт активное окно
    потока, а им может оказаться дочернее нативное окно Qt (когда виджет был
    промоутнут в нативный, например ради drag&drop). Тогда Windows пытается
    сделать НЕ-top-level окно владельцем — Qt пишет «must be a top level window»,
    а сама операция срывается. Явный top-level HWND это устраняет."""
    try:
        path = _api.os.path.abspath(path)
    except Exception:
        return False
    if not _api.os.path.exists(path):
        return True
    if _api.os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes

            class _SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_uint16),          # FILEOP_FLAGS = WORD
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", wintypes.LPCWSTR),
                ]

            FO_DELETE = 0x0003
            FOF_SILENT = 0x0004           # без индикатора прогресса
            FOF_NOCONFIRMATION = 0x0010   # без вопросов «вы уверены?»
            FOF_ALLOWUNDO = 0x0040        # → Корзина, а не безвозвратно
            FOF_NOERRORUI = 0x0400        # без окон об ошибках

            op = _SHFILEOPSTRUCTW()
            # Владелец операции — только валидный top-level HWND (см. docstring).
            try:
                op.hwnd = int(hwnd) if hwnd else None
            except Exception:
                op.hwnd = None
            op.wFunc = FO_DELETE
            # pFrom — список путей, оканчивающийся ДВОЙНЫМ NUL.
            op.pFrom = path + '\x00\x00'
            op.pTo = None
            op.fFlags = (FOF_ALLOWUNDO | FOF_NOCONFIRMATION
                         | FOF_SILENT | FOF_NOERRORUI)
            shell32 = ctypes.windll.shell32
            shell32.SHFileOperationW.argtypes = [ctypes.c_void_p]
            shell32.SHFileOperationW.restype = ctypes.c_int
            res = shell32.SHFileOperationW(ctypes.byref(op))
            return res == 0 and not op.fAnyOperationsAborted
        except Exception:
            return False
    # Не-Windows: системной Корзины под рукой нет — обычное удаление.
    try:
        _api.os.remove(path)
        return True
    except Exception:
        return False

move_to_trash.__module__ = _api.__name__
_api.move_to_trash = move_to_trash


def play_done_sound():
    try:
        if _api.IS_WIN:
            import winsound
            try: winsound.MessageBeep(winsound.MB_ICONEXCLAMATION); return
            except Exception: winsound.Beep(750, 300); return
    except Exception: pass
    try: print('\a', end='', flush=True)
    except Exception: pass

play_done_sound.__module__ = _api.__name__
_api.play_done_sound = play_done_sound


def rasterize_svg(path, max_dim=2048):
    """Растеризует SVG-файл в PIL.Image (RGBA) через QtSvg. PIL не умеет SVG,
    поэтому рисуем вектор в QImage и переводим в PIL. Возвращает None при ошибке
    или если QtSvg/PIL недоступны."""
    if not _api.Image:
        return None
    try:
        from PyQt6.QtSvg import QSvgRenderer
        from PyQt6.QtCore import QBuffer
    except Exception:
        return None
    try:
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            return None
        size = renderer.defaultSize()
        w, h = size.width(), size.height()
        if w <= 0 or h <= 0:
            w = h = 1024
        # Векторную картинку растеризуем покрупнее, чтобы при объединении она
        # была чёткой (но не больше max_dim по большей стороне).
        scale = max(1.0, 1024 / max(w, h))
        w2, h2 = int(round(w * scale)), int(round(h * scale))
        if max(w2, h2) > max_dim:
            k = max_dim / max(w2, h2)
            w2, h2 = int(round(w2 * k)), int(round(h2 * k))
        qimg = _api.QtGuiImage(w2, h2, _api.QtGuiImage.Format.Format_ARGB32)
        qimg.fill(0)  # прозрачный фон
        p = _api.QPainter(qimg)
        renderer.render(p)
        p.end()
        ba = _api.QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        qimg.save(buf, 'PNG')
        buf.close()
        return _api.Image.open(_api.io.BytesIO(bytes(ba))).convert('RGBA')
    except Exception:
        return None

rasterize_svg.__module__ = _api.__name__
_api.rasterize_svg = rasterize_svg


def open_image_any(path):
    """Открывает изображение как PIL.Image, поддерживая в т.ч. SVG (через
    растеризацию QtSvg). Возвращает PIL.Image. Бросает исключение, как Image.open,
    если формат не распознан."""
    if _api.os.path.splitext(path)[1].lower() == '.svg':
        im = _api.rasterize_svg(path)
        if im is None:
            raise ValueError(f"Не удалось растеризовать SVG: {path}")
        return im
    return _api.Image.open(path)

open_image_any.__module__ = _api.__name__
_api.open_image_any = open_image_any


def load_pixmap_any(path, max_dim=1024):
    """QPixmap из любого файла, включая SVG (растеризуется через QtSvg).
    Пустой QPixmap при ошибке."""
    if _api.os.path.splitext(path)[1].lower() == '.svg':
        try:
            from PyQt6.QtSvg import QSvgRenderer
            renderer = QSvgRenderer(path)
            if renderer.isValid():
                size = renderer.defaultSize()
                w, h = size.width(), size.height()
                if w <= 0 or h <= 0:
                    w = h = max_dim
                scale = min(1.0, max_dim / max(w, h))
                qimg = _api.QtGuiImage(int(w * scale) or 1, int(h * scale) or 1,
                                  _api.QtGuiImage.Format.Format_ARGB32)
                qimg.fill(0)
                p = _api.QPainter(qimg)
                renderer.render(p)
                p.end()
                return _api.QPixmap.fromImage(qimg)
        except Exception:
            pass
        return _api.QPixmap()
    # Сначала пробуем штатный загрузчик Qt.
    pix = _api.QPixmap(path)
    if not pix.isNull():
        return pix
    # Qt не открыл (нет плагина — частый случай для avif/heic): пробуем через
    # Pillow (avif/heic регистрируются pillow-heif) и переводим в QPixmap.
    if _api.Image:
        try:
            with _api.Image.open(path) as im:
                if _api.ImageOps:
                    im = _api.ImageOps.exif_transpose(im)
                im = im.convert("RGBA")
                bio = _api.io.BytesIO(); im.save(bio, format="PNG")
                p2 = _api.QPixmap()
                if p2.loadFromData(_api.QByteArray(bio.getvalue())):
                    return p2
        except Exception:
            pass
    # Последний резерв — bundled ffmpeg. Критично для сравнения «исходник/
    # результат»: результат у нас обычно AVIF, а в собранном .exe ни Qt, ни
    # Pillow могут не уметь его декодировать (нет плагина/кодека). ffmpeg с
    # libaom в комплекте точно открывает AVIF/HEIC (он же их и создаёт), поэтому
    # рендерим один кадр в PNG и грузим его — иначе панель «Результат» пустая.
    try:
        tmp = _api.os.path.join(_api.TEMP_DIR, f"ym_pix_{_api.uuid.uuid4().hex}.png")
        cmd = [_api.FFMPEG, "-y", "-i", path, "-frames:v", "1"]
        if max_dim:
            cmd += ["-vf", f"scale='min({int(max_dim)},iw)':-1"]
        cmd.append(tmp)
        _api.subprocess.run(cmd, stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                       creationflags=_api.CREATE_NO_WINDOW, timeout=20)
        if _api.os.path.exists(tmp):
            p3 = _api.QPixmap(tmp)
            try: _api.os.remove(tmp)
            except Exception: pass
            if not p3.isNull():
                return p3
    except Exception:
        pass
    return pix

load_pixmap_any.__module__ = _api.__name__
_api.load_pixmap_any = load_pixmap_any
