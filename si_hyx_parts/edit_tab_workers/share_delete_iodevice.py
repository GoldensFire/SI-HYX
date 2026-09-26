# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShareDeleteIODevice. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class ShareDeleteIODevice(_api.QIODevice):
    """QIODevice поверх файла, открытого с FILE_SHARE_DELETE (Windows).

    Зачем: QMediaPlayer, играя файл напрямую (setSource(file://…)), держит его
    так, что Проводник не даёт файл удалить («занят другим процессом»). Если же
    скормить плееру этот девайс (setSourceDevice), файл открыт с правом общего
    удаления — пользователь спокойно удаляет исходник прямо во время монтажа
    (Windows физически уберёт его, когда плеер отпустит хэндл). Перемотка
    работает: девайс произвольного доступа (isSequential=False, есть seek)."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._h = None
        try:
            self._sz = _api.os.path.getsize(self._path)
        except Exception:
            self._sz = 0

    def open(self, mode=_api.QIODevice.OpenModeFlag.ReadOnly):
        if _api.os.name != 'nt':
            return False
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            k32.CreateFileW.restype = wintypes.HANDLE
            k32.CreateFileW.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            GENERIC_READ = 0x80000000
            SHARE_ALL = 0x1 | 0x2 | 0x4          # READ | WRITE | DELETE
            OPEN_EXISTING = 3
            NORMAL = 0x80
            INVALID = ctypes.c_void_p(-1).value
            h = k32.CreateFileW(self._path, GENERIC_READ, SHARE_ALL, None,
                                OPEN_EXISTING, NORMAL, None)
            if not h or h == INVALID:
                return False
            self._h = h
            self._k32 = k32
            return super().open(_api.QIODevice.OpenModeFlag.ReadOnly)
        except Exception:
            return False

    def isSequential(self):
        return False

    def size(self):
        return self._sz

    def seek(self, pos):
        try:
            import ctypes
            from ctypes import wintypes
            self._k32.SetFilePointerEx.argtypes = [
                wintypes.HANDLE, ctypes.c_longlong,
                ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
            self._k32.SetFilePointerEx(wintypes.HANDLE(self._h),
                                       ctypes.c_longlong(int(pos)), None, 0)
        except Exception:
            return False
        return super().seek(pos)

    def readData(self, maxlen):
        if not self._h:
            return b''
        try:
            import ctypes
            from ctypes import wintypes
            n = int(maxlen)
            if n <= 0:
                return b''
            buf = ctypes.create_string_buffer(n)
            rd = wintypes.DWORD(0)
            ok = self._k32.ReadFile(wintypes.HANDLE(self._h), buf, n,
                                    ctypes.byref(rd), None)
            if not ok:
                return b''
            return bytes(buf.raw[:rd.value])
        except Exception:
            return b''

    def close(self):
        try:
            if self._h:
                from ctypes import wintypes
                self._k32.CloseHandle(wintypes.HANDLE(self._h))
        except Exception:
            pass
        self._h = None
        try:
            super().close()
        except Exception:
            pass

ShareDeleteIODevice.__module__ = _api.__name__
_api.ShareDeleteIODevice = ShareDeleteIODevice

def start_share_delete_feeder(path, stdin, stop_flag=None):
    """Фоновый поток: читает файл с FILE_SHARE_DELETE и пишет его байты в stdin
    запущенного ffmpeg (вход «pipe:0»). Зачем: ffmpeg, открывая файл напрямую,
    держит его без права удаления, и Проводник не даёт удалить исходник (а тем
    более папку с ним), пока крутится фоновый воркер (волна/прокси). Если же
    кормить ffmpeg через этот поток, файл открыт нами с FILE_SHARE_DELETE —
    пользователь спокойно удаляет исходник прямо во время монтажа.

    stop_flag — необязательный callable → True для досрочной остановки. Возвращает
    запущенный поток-демон. stdin закрывается по достижении конца файла."""
    out = getattr(stdin, "buffer", stdin)   # бинарный канал даже при text=True

    def _pump():
        h = None
        k32 = None
        f = None
        try:
            if _api.os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                k32 = ctypes.windll.kernel32
                k32.CreateFileW.restype = wintypes.HANDLE
                k32.CreateFileW.argtypes = [
                    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
                GENERIC_READ = 0x80000000
                SHARE_ALL = 0x1 | 0x2 | 0x4          # READ | WRITE | DELETE
                OPEN_EXISTING = 3
                NORMAL = 0x80
                INVALID = ctypes.c_void_p(-1).value
                hh = k32.CreateFileW(str(path), GENERIC_READ, SHARE_ALL, None,
                                     OPEN_EXISTING, NORMAL, None)
                if hh and hh != INVALID:
                    h = hh
                if h is not None:
                    buf = ctypes.create_string_buffer(1 << 20)
                    rd = wintypes.DWORD(0)
                    while stop_flag is None or not stop_flag():
                        ok = k32.ReadFile(wintypes.HANDLE(h), buf, len(buf),
                                          ctypes.byref(rd), None)
                        if not ok or rd.value == 0:
                            break
                        try:
                            out.write(buf.raw[:rd.value])
                        except Exception:
                            break
            else:
                f = open(str(path), 'rb')
                while stop_flag is None or not stop_flag():
                    data = f.read(1 << 20)
                    if not data:
                        break
                    try:
                        out.write(data)
                    except Exception:
                        break
        except Exception:
            pass
        finally:
            if h is not None:
                try:
                    import ctypes
                    from ctypes import wintypes
                    ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(h))
                except Exception:
                    pass
            if f is not None:
                try: f.close()
                except Exception: pass
            try: stdin.close()
            except Exception: pass

    t = _api.threading.Thread(target=_pump, daemon=True)
    t.start()
    return t

start_share_delete_feeder.__module__ = _api.__name__
_api.start_share_delete_feeder = start_share_delete_feeder

# ─── Workers ─────────────────────────────────────────────────────────────────
class FfmpegWorker(_api.QThread):
    progress = _api.pyqtSignal(float)
    finished = _api.pyqtSignal(bool, str)

    def __init__(self, cmd, duration=None, parent=None):
        super().__init__(parent)
        from ffmpeg_faststart import with_faststart
        self.cmd = with_faststart(cmd)
        self.duration = duration
        self.proc = None
        self._stopped = False

    def run(self):
        try:
            self.proc = _api.subprocess.Popen(
                self.cmd, stderr=_api.subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace",
                creationflags=_api.CREATE_NO_WINDOW)
        except Exception as e:
            self.finished.emit(False, f"Не удалось запустить ffmpeg: {e}")
            return

        proc = self.proc
        if self.duration is None:
            rc = proc.wait()
            self.finished.emit(rc == 0 and not self._stopped, f"Код: {rc}")
            return

        try:
            for line in proc.stderr:
                if self._stopped:
                    break
                if 'time=' in line:
                    try:
                        idx = line.index('time=')
                        tpart = line[idx + 5:].split()[0]
                        tsec = _api.time_to_s(tpart)
                        perc = min(100.0, max(0.0, (tsec / self.duration) * 100.0)) if self.duration > 0 else 0.0
                        self.progress.emit(perc)
                    except Exception:
                        pass
            rc = proc.wait()
            if self._stopped:
                self.finished.emit(False, "Отменено")
            else:
                self.finished.emit(rc == 0, f"Код: {rc}")
        except Exception as e:
            try:
                proc.kill()
            except Exception:
                pass
            self.finished.emit(False, f"Ошибка ffmpeg: {e}")

    def stop(self):
        """Помечает воркер отменённым и убивает ffmpeg-процесс (без зомби)."""
        self._stopped = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

FfmpegWorker.__module__ = _api.__name__
_api.FfmpegWorker = FfmpegWorker
