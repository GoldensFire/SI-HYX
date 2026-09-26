# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_set_taskbar_identity. Public namespace: main."""
import main as _api


def _set_taskbar_identity(hwnd):
    """Прописывает окну иконку и имя для КНОПКИ НА ПАНЕЛИ ЗАДАЧ.

    Панель задач группирует окна по AppUserModelID (см. main()), а иконку для
    группы берёт НЕ из окна, а из ярлыка Пуска с тем же AppUserModelID. Ярлыка
    у нас нет (программа портативная, из папки), поэтому кнопка на панели задач
    получала стандартную «пустую» иконку — при том что в заголовке окна и в
    Alt+Tab иконка своя, правильная. Отсюда и «прога запускается без иконки».

    Лечение по документации — свойства окна System.AppUserModel.*: Relaunch-
    IconResource говорит панели задач, откуда брать иконку, когда ярлыка нет.
    Ставим до первого показа окна: после показа панель уже нарисовала кнопку.

    Тихо ничего не делает не на Windows и при любой ошибке COM — иконка в
    заголовке от этого не зависит.
    """
    if not _api.IS_WIN or not _api.APP_ICON:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                        ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

        class _PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]

        class _PROPVARIANT(ctypes.Structure):
            # Строку кладём руками (vt = VT_LPWSTR, дальше указатель): штатной
            # InitPropVariantFromString в propsys.dll нет — она инлайновая, по
            # имени не экспортируется, и обращение к ней роняло всю функцию на
            # первом же свойстве (иконка так и не выставлялась).
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                        ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                        ("pwsz", ctypes.c_wchar_p),
                        ("pad", ctypes.c_ubyte * 8)]

        _VT_LPWSTR = 31

        ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32

        def _guid(text):
            g = _GUID()
            ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
            return g

        store = ctypes.c_void_p()
        iid = _guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")   # IPropertyStore
        if shell32.SHGetPropertyStoreForWindow(
                wintypes.HWND(int(hwnd)), ctypes.byref(iid),
                ctypes.byref(store)) or not store:
            return
        vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        SetValue = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY),
            ctypes.POINTER(_PROPVARIANT))(vtbl[6])
        Commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
        Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])

        fmtid = _guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")  # PKEY_AppUserModel_*
        # 5 — ID, 3 — RelaunchIconResource, 4 — RelaunchDisplayNameResource.
        # RelaunchCommand (2) сознательно не ставим: панель задач подставила бы
        # его в «Закрепить», а для запуска из папки правильной команды нет.
        values = ((5, _api._AUMID), (3, f"{_api.APP_ICON},0"), (4, _api.APP_NAME))
        # Держим PROPVARIANT'ы живыми до Commit: строки принадлежат нам, а не
        # CoTaskMem, и освобождать их через PropVariantClear нельзя.
        alive = []
        try:
            for pid, value in values:
                pv = _PROPVARIANT()
                pv.vt = _VT_LPWSTR
                pv.pwsz = str(value)
                alive.append(pv)
                key = _PROPERTYKEY(fmtid, pid)
                SetValue(store, ctypes.byref(key), ctypes.byref(pv))
            Commit(store)
        finally:
            Release(store)
    except Exception:
        pass

_set_taskbar_identity.__module__ = _api.__name__
_api._set_taskbar_identity = _set_taskbar_identity

def main():
    # AppUserModelID задаём до QApplication и первого окна. Проверено запуском:
    # БЕЗ него панель задач группирует окно под python.exe и рисует иконку
    # питона; С ним, но без свойств окна из _set_taskbar_identity, — пустую
    # (ярлыка Пуска с таким AUMID у портативной программы нет). Правильная
    # иконка получается только парой AUMID + _set_taskbar_identity, поэтому
    # выкидывать что-то одно нельзя — вернётся «иконка пропала при main.py».
    # Порядок вызова сам по себе ни на что не влияет (в v0.4.0 его двигали сюда
    # как «фикс» — не помогло).
    if _api.IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_api._AUMID)
        except Exception:
            pass

    # Парсим аргументы один раз
    cli_files = [f for f in _api.sys.argv[1:] if _api.os.path.exists(f)]

    # Если запущен с аргументами (через ПКМ) — пробуем передать файлы уже открытому окну
    if cli_files:
        try:
            sock = _api.QLocalSocket()
            sock.connectToServer("YasperMoglotIPC")
            if sock.waitForConnected(800):
                sock.write(('\n'.join(cli_files) + '\n').encode('utf-8'))
                sock.flush()
                sock.waitForBytesWritten(1000)
                sock.disconnectFromServer()
                return  # Файл передан — новое окно не открываем
        except Exception: pass
        # Сервер не найден — запускаем нормально и загружаем файлы

    _api.qInstallMessageHandler(_api._qt_message_filter)
    _api._install_crash_handler()

    app = _api.QApplication(_api.sys.argv)
    app.setStyle("Fusion")
    # Русификация стандартных кнопок диалогов Qt (QMessageBox и др.): без
    # переводчика «Да/Нет/ОК/Отмена» рисуются по-английски (Yes/No/OK/Cancel),
    # из-за чего окна подтверждения в «Монтаже» были на английском.
    try:
        _qt_translator = _api.QTranslator(app)
        _tr_path = _api.QLibraryInfo.path(_api.QLibraryInfo.LibraryPath.TranslationsPath)
        if _qt_translator.load(_api.QLocale("ru"), "qtbase", "_", _tr_path) or \
           _qt_translator.load("qtbase_ru", _tr_path):
            app.installTranslator(_qt_translator)
            app._qt_translator = _qt_translator  # держим ссылку от сборщика мусора
    except Exception:
        pass
    app.setStyleSheet(_api.STYLESHEET)
    # Стабильные подсказки без мерцания (тот же попап, что у значков ⓘ) для всех
    # виджетов с setToolTip — заменяет системный QToolTip (см. widgets.py).
    _api.install_hover_tips(app)
    if _api.APP_ICON:
        app.setWindowIcon(_api.QIcon(_api.APP_ICON))

    w = _api.UnifiedWindow()

    # Если файлы переданы аргументами и IPC не сработал — добавляем напрямую
    if cli_files:
        _api.QTimer.singleShot(300, lambda: (
            w.tabs.setCurrentWidget(w.tab_media),
            w.tab_media.add_paths(cli_files)
        ))

    # До show(): панель задач рисует кнопку в момент первого показа окна и
    # свойства после этого уже не перечитывает (см. _set_taskbar_identity).
    _api._set_taskbar_identity(int(w.winId()))
    w.show()
    _api.sys.exit(app.exec())

main.__module__ = _api.__name__
_api.main = main
