# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""pil_to_qicon. Public namespace: utils."""
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

@_api.functools.lru_cache(maxsize=None)
def detect_ffmpeg_encoders():
    """Определяет доступные кодеки FFmpeg. Результат кешируется — ffmpeg запускается только один раз."""
    try:
        p = _api.subprocess.run([_api.FFMPEG, "-hide_banner", "-encoders"], stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=_api.CREATE_NO_WINDOW)
        encs = set()
        for line in (p.stdout or "").splitlines():
            m = _api.re.match(r'^\s*[A-Z\.]+\s+([a-z0-9_\-]+)\s+', line, _api.re.I)
            if m: encs.add(m.group(1).strip().lower())
        return frozenset(encs)  # frozenset совместим с lru_cache (хешируемый)
    except Exception:
        return frozenset()

detect_ffmpeg_encoders.__module__ = _api.__name__
_api.detect_ffmpeg_encoders = detect_ffmpeg_encoders

def require_svt():
    return 'libsvtav1' in _api.detect_ffmpeg_encoders()

require_svt.__module__ = _api.__name__
_api.require_svt = require_svt
