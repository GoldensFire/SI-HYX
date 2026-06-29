# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# edit_tab.py — вкладка «Монтаж»: видеорезка с волной, превью и экспортом через ffmpeg.
# Адаптировано из standalone-редактора Edit.py (JashaLava) под вкладку SI-HYX.

import os
import sys
import json
import math
import wave
import tempfile
import subprocess
import threading
import time
from pathlib import Path
from functools import partial
from collections import deque

# Бэкенды Qt нужно выбрать ДО создания QMediaPlayer/QVideoWidget. Модуль
# импортируется в main.py до создания QApplication, поэтому setdefault здесь
# срабатывает вовремя и не перетирает значения, заданные пользователем извне.
from config import SETTINGS_FILE as _SETTINGS_FILE


def _read_bool_setting(key, default=False):
    """Читает булев флаг прямо из settings.json (нужно ДО создания QApplication)."""
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as _f:
            return bool(json.load(_f).get(key, default))
    except Exception:
        return default


# Программный рендер видео отключён всегда (настройка убрана из UI): окно видео
# идёт по аппаратному D3D/GL-свопчейну.
os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
# QT_FFMPEG_DECODING_HW_DEVICE_TYPES (HW-декодер H.264/HEVC) задаёт config.py,
# импортируемый выше, — он читает настройку video_hw_decode.
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from PyQt6.QtCore import (
    Qt, QUrl, QThread, pyqtSignal, QTimer, QEvent, QPoint, QRect, QSize,
    QIODevice, QPointF, QRectF
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSlider, QScrollBar, QFileDialog, QLineEdit, QSpinBox, QComboBox,
    QMessageBox, QProgressBar, QStyle, QStyleOptionSlider, QCheckBox, QToolTip,
    QFrame, QScrollArea, QSizePolicy, QMenu, QDialog, QPlainTextEdit,
    QDialogButtonBox
)
from PyQt6.QtGui import (
    QKeySequence, QPainter, QColor, QPen, QBrush, QAction, QShortcut,
    QFont, QLinearGradient, QPainterPath, QPixmap, QFontMetrics, QIcon, QImage,
    QCursor
)

# Нативный рендер ASS/SSA для превью (libass). Если DLL нет/не загрузились —
# LIBASS_AVAILABLE=False, и субтитры показываются обычным текстовым оверлеем.
try:
    import libass_renderer as _libass
    LIBASS_AVAILABLE = bool(_libass.AVAILABLE)
except Exception:
    _libass = None
    LIBASS_AVAILABLE = False

# Мультимедиа PyQt6 поставляется вместе с основным wheel'ом, но на некоторых
# урезанных сборках его может не быть — деградируем мягко (заглушка во вкладке).
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _HAS_MULTIMEDIA = True
except Exception:
    _HAS_MULTIMEDIA = False

# Пути к ffmpeg/ffprobe и флаг скрытия консоли берём из общей конфигурации SI-HYX,
# чтобы редактор работал и в собранном .exe с bundled-ffmpeg.
from config import (FFMPEG, FFPROBE, CREATE_NO_WINDOW, CONFIG_DIR,
                    get_icon, get_icon_pixmap, icon_html)
import qtawesome as qta

EDITOR_SETTINGS_PATH = os.path.join(CONFIG_DIR, "editor_settings.json")


# ─── Color Palette ───────────────────────────────────────────────────────────
# Палитра вкладки приведена к общему стилю приложения (Catppuccin Mocha,
# см. STYLESHEET в config.py), чтобы «Монтаж» не выбивался из остальных вкладок.
C = {
    "bg":        "#1e1e2e",   # base
    "surface":   "#181825",   # mantle
    "surface2":  "#24273a",   # surface0-ish (панели)
    "surface3":  "#313244",   # surface0 (поля/кнопки)
    "border":    "#45475a",   # surface1
    "border2":   "#585b70",   # surface2
    "accent":    "#89b4fa",   # blue
    "accent2":   "#b4befe",   # lavender (hover)
    "green":     "#a6e3a1",   # green
    "green2":    "#94e2d5",   # teal
    "red":       "#f38ba8",   # red
    "red2":      "#eba0ac",   # maroon
    "yellow":    "#f9e2af",   # yellow
    "text":      "#cdd6f4",   # text
    "text2":     "#a6adc8",   # subtext0
    "text3":     "#6c7086",   # overlay0
    "playhead":  "#f9e2af",   # yellow
    "wave_bg":   "#45475a",
    "wave_sel":  "#89b4fa",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────
def run_ffprobe(path):
    cmd = [FFPROBE, "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=True,
                           encoding="utf-8", errors="replace",
                           creationflags=CREATE_NO_WINDOW)
        return json.loads(p.stdout)
    except Exception as e:
        print("ffprobe failed:", e)
        return None


def time_to_s(hms_str: str) -> float:
    parts = [p for p in hms_str.split(':') if p]
    if not parts:
        return 0.0
    try:
        partsf = [float(p) for p in parts]
    except Exception:
        return 0.0
    if len(partsf) == 3:
        h, m, s = partsf
        return h * 3600 + m * 60 + s
    elif len(partsf) == 2:
        m, s = partsf
        return m * 60 + s
    else:
        return partsf[0]


def s_to_time(seconds: float) -> str:
    if seconds is None:
        return "00:00:00.000"
    s = float(seconds)
    if not math.isfinite(s) or s < 0:
        return "00:00:00.000"
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"


def format_fps(fps):
    if fps is None:
        return "—"
    try:
        f = float(fps)
    except Exception:
        return str(fps)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    else:
        txt = f"{f:.3f}"
        txt = txt.rstrip('0').rstrip('.')
        return txt


def _fmt_channels(ainfo):
    """Человекочитаемое описание числа каналов аудио: 1 → «моно», 2 → «стерео»,
    6 → «5.1», 8 → «7.1», иначе «Nch». Берётся channel_layout, если он есть."""
    info = ainfo or {}
    try:
        ch = int(info.get('channels'))
    except Exception:
        ch = None
    layout = (info.get('channel_layout') or '').lower()
    if ch == 1 or layout == 'mono':
        return "моно"
    if ch == 2 or layout == 'stereo':
        return "стерео"
    if ch == 6 or layout.startswith('5.1'):
        return "5.1"
    if ch == 8 or layout.startswith('7.1'):
        return "7.1"
    if ch:
        return f"{ch}ch"
    return "—"


def _unique_output(path: str) -> str:
    """Возвращает путь, которого ещё нет на диске: к имени добавляется _1, _2…
    перед расширением (foo_обрез.mp4 → foo_обрез_1.mp4). Используется, когда
    «Перезаписать» выключено, а файл с целевым именем уже существует —
    результат просто сохраняется под новым именем."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = f"{base}_{i}{ext}"
        if not os.path.exists(cand):
            return cand
        i += 1


class ShareDeleteIODevice(QIODevice):
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
            self._sz = os.path.getsize(self._path)
        except Exception:
            self._sz = 0

    def open(self, mode=QIODevice.OpenModeFlag.ReadOnly):
        if os.name != 'nt':
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
            return super().open(QIODevice.OpenModeFlag.ReadOnly)
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
                import ctypes
                from ctypes import wintypes
                self._k32.CloseHandle(wintypes.HANDLE(self._h))
        except Exception:
            pass
        self._h = None
        try:
            super().close()
        except Exception:
            pass


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
            if os.name == 'nt':
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

    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    return t


# ─── Workers ─────────────────────────────────────────────────────────────────
class FfmpegWorker(QThread):
    progress = pyqtSignal(float)
    finished = pyqtSignal(bool, str)

    def __init__(self, cmd, duration=None, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.duration = duration
        self.proc = None
        self._stopped = False

    def run(self):
        try:
            self.proc = subprocess.Popen(
                self.cmd, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW)
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
                        tsec = time_to_s(tpart)
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


class SmartCutWorker(QThread):
    """Умная обрезка (Smart Cut). Основная часть видео между опорными кадрами
    копируется БЕЗ перекодирования (оригинальное качество и скорость), а
    перекодируются только короткие граничные участки от точек реза до ближайших
    ключевых кадров. Итог склеивается concat-демуксером.

    head: [in, kf_start)  — перекодировка (точное начало реза)
    mid:  [kf_start, kf_end) — copy видео (без потерь), аудио → AAC (для ровной склейки)
    tail: [kf_end, out)   — перекодировка (точный конец реза)

    Если умную обрезку выполнить нельзя (нет опорных кадров внутри отрезка, чужой
    видеокодек, ошибка склейки) — ПРОЗРАЧНЫЙ ОТКАТ на полную перекодировку отрезка,
    чтобы пользователь всегда получил корректный файл."""
    progress = pyqtSignal(float)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, src, in_s, out_s, out_path, venc, audio_index=None,
                 parent=None):
        super().__init__(parent)
        self.src = str(src)
        self.in_s = float(in_s)
        self.out_s = float(out_s)
        self.out_path = out_path
        self.venc = list(venc)
        # Абсолютный индекс выбранной аудиодорожки (None → первая: 0:a:0). Без
        # него Smart Cut всегда брал дорожку по умолчанию, игнорируя выбор.
        self.audio_index = audio_index
        self._stopped = False
        self._procs = []
        self._tmpdir = None

    def stop(self):
        self._stopped = True
        for p in list(self._procs):
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass

    def _run(self, cmd):
        if self._stopped:
            return 1
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 creationflags=CREATE_NO_WINDOW)
        except Exception:
            return 1
        self._procs.append(p)
        rc = p.wait()
        try: self._procs.remove(p)
        except ValueError: pass
        return rc

    def _video_codec(self):
        try:
            r = subprocess.run(
                [FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name", "-of", "csv=p=0", self.src],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", creationflags=CREATE_NO_WINDOW, timeout=30)
            return (r.stdout or "").strip()
        except Exception:
            return ""

    def _keyframes(self):
        """Тайминги ключевых кадров видео в окрестности [in, out] (по флагам
        пакетов, без декодирования — быстро)."""
        cmd = [FFPROBE, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "packet=pts_time,flags",
               "-read_intervals", f"{max(0.0, self.in_s - 2):.3f}%{self.out_s + 2:.3f}",
               "-of", "csv=p=0", self.src]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=CREATE_NO_WINDOW, timeout=60)
        except Exception:
            return []
        kfs = []
        for line in (r.stdout or "").splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and parts[0] not in ("", "N/A") and "K" in parts[1]:
                try:
                    kfs.append(float(parts[0]))
                except Exception:
                    pass
        return sorted(kfs)

    # Общий timescale для всех сегментов: без него re-encode (libx264) и copy
    # имеют разную временную базу, и concat-демуксер вставляет рассинхрон на
    # стыке. 90000 — стандарт для видео.
    _TS = "90000"

    def _media_dur(self, path):
        """Длительность готового файла по контейнеру (для подгонки аудио к видео)."""
        try:
            r = subprocess.run(
                [FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path], capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW, timeout=30)
            return float((r.stdout or "0").strip() or 0.0)
        except Exception:
            return 0.0

    def _max_frame_gap(self, path):
        """(max_gap, median_gap) между соседними видео-пакетами склейки. Щель на
        стыке сегментов (open-GOP роняет хвостовые B-кадры у границы GOP при
        lossless-copy → дырка в 2–3 кадра) даёт max_gap заметно больше медианного
        интервала. Нужен, чтобы поймать НЕровную склейку и честно откатиться на
        полный реэнкод (он всегда кадрово-непрерывен)."""
        try:
            r = subprocess.run(
                [FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "packet=pts_time", "-of", "csv=p=0", path],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", creationflags=CREATE_NO_WINDOW, timeout=60)
        except Exception:
            return (0.0, 0.0)
        ts = sorted(
            float(x.replace(",", "")) for x in (r.stdout or "").split()
            if x.strip() and x.replace(",", "") not in ("", "N/A"))
        if len(ts) < 3:
            return (0.0, 0.0)
        gaps = sorted(ts[i + 1] - ts[i] for i in range(len(ts) - 1))
        return (gaps[-1], gaps[len(gaps) // 2])

    def _encode_seg(self, start, dur, out_file):
        """Перекодирует ВИДЕО граничного участка [start, start+dur) без звука.

        Ключевые моменты (выверены экспериментально на h264/aac):
        • ВХОДНОЙ seek (-ss ДО -i) + -t — первый кадр сегмента встаёт в 0.000;
          двухступенчатый seek (вход к ключевому + выход к точке) оставлял
          смещение ~0.08с и щель на стыке → «зависание первых кадров».
        • `-bf 0` — без B-кадров у границы нет задержки переупорядочивания
          (иначе первый PTS = 2 кадра → щель/смещение при concat).
        • общий `-video_track_timescale` — ровная склейка с copy-серединой.

        Звук НЕ кодируем посегментно: на каждом стыке AAC-кодер добавил бы
        priming/padding → провал звука. Берём звук единым проходом (_encode_audio).

        Тайминги форматируем с точностью .6f: округление до мс смещало срез на доли
        кадра — у copy это вырезало кадр у границы (дырка → щель на стыке)."""
        cmd = [FFMPEG, "-y", "-ss", f"{start:.6f}", "-i", self.src,
               "-t", f"{dur:.6f}"] + self.venc + \
              ["-bf", "0", "-an", "-sn", "-video_track_timescale", self._TS,
               "-avoid_negative_ts", "make_zero", out_file]
        return self._run(cmd) == 0

    def _copy_seg(self, start, end, out_file):
        """Копирует середину [start, end) без перекодирования видео и БЕЗ звука.
        ВХОДНОЙ seek на ключевой кадр `start` + ОГРАНИЧЕНИЕ ДЛИТЕЛЬНОСТЬЮ `-t`.

        КРИТИЧНО: здесь НЕЛЬЗЯ `-avoid_negative_ts make_zero`. Он сдвигает
        таймстемпы в ноль, и тогда `-t`/`-to` перестают резать по длительности —
        copy захватывает ЛИШНИЕ GOP (замерено: с make_zero копия [106.4,127.2) =
        2 GOP давала 31с/749 кадров вместо 21с/498 → склейка длиннее запроса →
        предохранитель всегда откатывал на полный реэнкод; а если overshoot <1.5с,
        он проскакивал → «застывший кадр + лишняя секунда звука в конце»). Без
        make_zero `-t` режет ровно по длительности (498–500 кадров). Нулевой старт
        для стыка обеспечивает уже сам concat (`make_zero` на склейке). Общий
        `-video_track_timescale` оставляем — ровная склейка с re-encode-границами."""
        dur = max(0.0, end - start)
        cmd = [FFMPEG, "-y", "-ss", f"{start:.6f}", "-i", self.src,
               "-t", f"{dur:.6f}", "-c:v", "copy", "-an", "-sn",
               "-video_track_timescale", self._TS, out_file]
        return self._run(cmd) == 0

    def _encode_audio(self, dur, out_file):
        """Кодирует звук ВЫБРАННОЙ дорожки от in_s РОВНО длиной dur (= длине
        склеенного видео) ОДНИМ проходом в AAC. `apad` добивает тишиной до полной
        длины, поэтому звук покрывает и ПОСЛЕДНИЙ кадр (без apad `-shortest` в mux
        обрезал звук по последнему ВИДЕО-пакету и на финальном кадре звука не было
        — «звук обрывается в конце»). Единый поток → нет провалов на стыках.
        Дорожка — self.audio_index (выбор пользователя), иначе первая 0:a:0.
        Возвращает True только если файл создан (источник без звука → False)."""
        amap = f"0:{self.audio_index}" if self.audio_index is not None else "0:a:0"
        cmd = [FFMPEG, "-y", "-ss", f"{self.in_s:.6f}", "-i", self.src,
               "-t", f"{max(0.1, dur):.6f}", "-vn", "-sn",
               "-map", amap, "-af", "apad", "-c:a", "aac", "-b:a", "192k",
               "-avoid_negative_ts", "make_zero", out_file]
        return (self._run(cmd) == 0 and os.path.exists(out_file)
                and os.path.getsize(out_file) > 0)

    def _mux(self, video_file, audio_file, out_file):
        """Сводит готовую видео-дорожку с единой аудио-дорожкой без перекодировки.
        Звук уже точно равен длине видео (apad + -t = video_dur), поэтому БЕЗ
        `-shortest`: и последний кадр озвучен, и нет «застывшего» хвоста видео.
        muxdelay/muxpreload 0 + make_zero убирают начальное смещение контейнера."""
        cmd = [FFMPEG, "-y", "-i", video_file, "-i", audio_file,
               "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
               "-avoid_negative_ts", "make_zero", "-muxpreload", "0",
               "-muxdelay", "0", out_file]
        return self._run(cmd) == 0

    def _full_reencode(self, out_file):
        """Откат: полная перекодировка отрезка одним проходом. ВХОДНОЙ seek
        (-ss ДО -i) + re-encode даёт кадрово-точный старт и не декодирует файл с
        нуля (выходной seek на in_s=100с тормозил бы). Один проход → звук
        непрерывен, провалов на стыках нет.

        КРИТИЧНО — маппим ВЫБРАННУЮ аудиодорожку. Без -map ffmpeg по умолчанию
        берёт дорожку с НАИБОЛЬШИМ числом каналов (напр. 5.1), а не выбранную
        пользователем 2.0 → «после обрезки звук стал другой». apad держит звук до
        последнего кадра (только когда дорожка точно есть)."""
        if self.audio_index is not None:
            amap = ["-map", "0:v:0", "-map", f"0:{self.audio_index}"]
            aenc = ["-c:a", "aac", "-b:a", "192k", "-af", "apad"]
        else:
            # Дорожка не выбрана: optional-map первой аудио (источник без звука не
            # упадёт); apad НЕ ставим — на безаудийном входе фильтр бы ошибся.
            amap = ["-map", "0:v:0", "-map", "0:a:0?"]
            aenc = ["-c:a", "aac", "-b:a", "192k"]
        cmd = [FFMPEG, "-y", "-ss", f"{self.in_s:.6f}", "-i", self.src,
               "-t", f"{self.out_s - self.in_s:.6f}"] + amap + self.venc + \
              aenc + ["-sn", out_file]
        return self._run(cmd) == 0

    def run(self):
        # Промежуточные сегменты ВСЕГДА в .mp4: только mp4-муксер уважает общий
        # -video_track_timescale, без которого re-encode и copy склеиваются со
        # сдвигом (mkv свой timescale игнорирует → щель на стыке mid→tail). В
        # пользовательский контейнер (mkv/…) перекладываем уже готовый результат
        # финальным mux/remux без перекодировки.
        ext = ".mp4"
        try:
            self._tmpdir = tempfile.mkdtemp(prefix="sihyx_smartcut_")
        except Exception:
            self.finished.emit(False, "Не удалось создать временную папку"); return

        def _finish(ok, msg):
            try:
                import shutil
                if self._tmpdir:
                    shutil.rmtree(self._tmpdir, ignore_errors=True)
            except Exception:
                pass
            self.finished.emit(ok and not self._stopped, msg)

        try:
            self.status.emit("Smart Cut: анализ ключевых кадров…")
            self.progress.emit(3.0)
            vcodec = self._video_codec()
            kfs = self._keyframes()
            # Опорные кадры строго ВНУТРИ отрезка (с зазором, чтобы участки не
            # вырождались в ноль).
            inner = [t for t in kfs if self.in_s + 0.10 < t < self.out_s - 0.10]
            kf_before_in = max([t for t in kfs if t <= self.in_s + 0.001], default=0.0)

            # Условия применимости умной обрезки: знаем кодек и есть ХОТЯ БЫ ДВА
            # опорных кадра внутри (нужны старт И конец copy-середины). При одном
            # kf_start==kf_end → copy «-ss X -to X» падает («-to value smaller than
            # -ss») и весь Smart Cut откатывался на реэнкод. Короткий клип (короче
            # ~2 GOP, частый случай: ~15с при GOP ~10с) копировать нечего — сразу
            # честный полный реэнкод (он теперь уважает выбранную аудиодорожку).
            if self._stopped:
                _finish(False, "Отменено"); return
            if vcodec not in ("h264", "hevc", "h265") or len(inner) < 2:
                self.status.emit("Smart Cut недоступен для отрезка — полная перекодировка…")
                self.progress.emit(10.0)
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else "Ошибка перекодировки")
                return

            kf_start, kf_end = inner[0], inner[-1]
            head = os.path.join(self._tmpdir, f"head{ext}")
            mid  = os.path.join(self._tmpdir, f"mid{ext}")
            tail = os.path.join(self._tmpdir, f"tail{ext}")
            segs = []

            # head: [in, kf_start) — только видео (входной seek прямо в in_s)
            self.status.emit("Smart Cut: граница начала…"); self.progress.emit(20.0)
            if kf_start - self.in_s > 0.04:
                if not self._encode_seg(self.in_s, kf_start - self.in_s, head):
                    raise RuntimeError("head encode failed")
                segs.append(head)

            # mid: [kf_start, kf_end) — copy без перекодировки (только видео)
            self.status.emit("Smart Cut: копирование середины…"); self.progress.emit(40.0)
            if not self._copy_seg(kf_start, kf_end, mid):
                raise RuntimeError("mid copy failed")
            segs.append(mid)

            # tail: [kf_end, out) — только видео
            self.status.emit("Smart Cut: граница конца…"); self.progress.emit(60.0)
            if self.out_s - kf_end > 0.04:
                if not self._encode_seg(kf_end, self.out_s - kf_end, tail):
                    raise RuntimeError("tail encode failed")
                segs.append(tail)

            if self._stopped:
                _finish(False, "Отменено"); return

            # Склейка ВИДЕО-сегментов (без звука) в единую дорожку.
            self.status.emit("Smart Cut: склейка…"); self.progress.emit(75.0)
            video_only = os.path.join(self._tmpdir, f"video{ext}")
            listfile = os.path.join(self._tmpdir, "list.txt")
            with open(listfile, "w", encoding="utf-8") as f:
                for s in segs:
                    f.write(f"file '{s.replace(chr(39), chr(92) + chr(39))}'\n")
            rc = self._run([FFMPEG, "-y", "-f", "concat", "-safe", "0",
                            "-i", listfile, "-c", "copy", "-an",
                            "-avoid_negative_ts", "make_zero",
                            "-muxpreload", "0", "-muxdelay", "0", video_only])
            ok = (rc == 0 and os.path.exists(video_only)
                  and os.path.getsize(video_only) > 0)
            if not ok:
                # Склейка не удалась → откат на полную перекодировку.
                self.status.emit("Склейка не удалась — полная перекодировка…")
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else "Ошибка Smart Cut")
                return

            if self._stopped:
                _finish(False, "Отменено"); return

            # ПРЕДОХРАНИТЕЛЬ ДЛИТЕЛЬНОСТИ: head/tail режутся точно по in_s/out_s, а
            # mid ограничен ключевыми кадрами внутри [in,out] — поэтому склейка
            # обязана быть ≈ (out_s−in_s). Если она заметно длиннее/короче (битый
            # индекс/таймстемпы редкого контейнера → copy захватил лишнее: «обрезал
            # 15с, получил 21с»), Smart Cut НЕНАДЁЖЕН для этого файла — честно
            # откатываемся на полную перекодировку (она всегда кадрово-точна).
            requested = self.out_s - self.in_s
            vdur = self._media_dur(video_only) or requested
            if abs(vdur - requested) > 1.5:
                self.status.emit("Smart Cut неточен для файла — полная перекодировка…")
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else "Ошибка Smart Cut")
                return

            # ПРЕДОХРАНИТЕЛЬ СТЫКА: у open-GOP исходника (B-кадры ссылаются на
            # СЛЕДУЮЩИЙ ключевой) lossless-copy роняет 2–3 хвостовых B-кадра на
            # границе GOP → щель на стыке mid→tail (микро-рывок «застывший кадр»).
            # Кадров реально нет — концат её не закроет (проверено: даже filter-
            # concat с реэнкодом оставляет ту же щель). Если на склейке есть
            # аномальный разрыв между видео-пакетами (> 1.8× медианного интервала),
            # склейка неровная → честный откат на полный реэнкод (кадрово-непрерывен).
            # Чистая склейка (быстрый путь) проходит дальше без потерь.
            maxgap, medgap = self._max_frame_gap(video_only)
            if medgap > 0 and maxgap > medgap * 1.8:
                self.status.emit("Smart Cut: неровный стык — полная перекодировка…")
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else "Ошибка Smart Cut")
                return

            # Звук единым проходом → подмешиваем к видео. Так на стыках сегментов
            # нет провалов AAC-priming (баг «звук обрывается и снова идёт»). Длину
            # звука берём РОВНО по длине склеенного видео (apad добьёт тишиной),
            # чтобы озвучить и последний кадр. Источник без звука → видео как есть.
            self.status.emit("Smart Cut: звук…"); self.progress.emit(88.0)
            audio = os.path.join(self._tmpdir, "audio.m4a")
            if self._encode_audio(vdur, audio):
                if not self._mux(video_only, audio, self.out_path):
                    self.status.emit("Сведение не удалось — полная перекодировка…")
                    ok = self._full_reencode(self.out_path)
                    _finish(ok, "Готово (перекодировка)" if ok else "Ошибка Smart Cut")
                    return
            else:
                # Нет аудио-дорожки — перекладываем видео в контейнер результата
                # без перекодировки (intermediate всегда mp4, цель может быть mkv).
                rc = self._run([FFMPEG, "-y", "-i", video_only, "-c", "copy",
                                "-an", "-avoid_negative_ts", "make_zero",
                                "-muxpreload", "0", "-muxdelay", "0",
                                self.out_path])
                if rc != 0 or not os.path.exists(self.out_path):
                    import shutil
                    shutil.copyfile(video_only, self.out_path)
            ok = (os.path.exists(self.out_path)
                  and os.path.getsize(self.out_path) > 0)
            if not ok:
                raise RuntimeError("final output missing")
            self.progress.emit(100.0)
            _finish(True, "Готово (Smart Cut)")
        except Exception as e:
            if self._stopped:
                _finish(False, "Отменено"); return
            # Любая ошибка пайплайна → надёжный откат на полный реэнкод.
            try:
                self.status.emit(f"Smart Cut: откат на перекодировку ({e})")
                ok = self._full_reencode(self.out_path)
                _finish(ok, "Готово (перекодировка)" if ok else f"Ошибка Smart Cut: {e}")
            except Exception as e2:
                _finish(False, f"Ошибка Smart Cut: {e2}")


class VideoInpaintWorker(QThread):
    """Покадровое удаление объекта (водяной знак/эмодзи и т.п.) с ВИДЕО в отдельном
    потоке, чтобы интерфейс не зависал.

    Принципиально НЕ содержит собственной реализации инпейнтинга: для каждого кадра
    вызывается ТОТ ЖЕ движок LaMa (inpainter.inpaint), что и при удалении объекта с
    одиночного изображения в фоторедакторе. Пайплайн целиком на FFmpeg + LaMa:

      1) FFmpeg разбивает видео на PNG-кадры (полное разрешение, дисплейная
         ориентация — autorotate по умолчанию, без потерь);
      2) каждый кадр прогоняется через inpainter.inpaint(frame, mask) — функция
         сама обрабатывает только ROI вокруг маски (см. lama_inpaint.py), поэтому
         для небольшого знака весь кадр через сеть НЕ гоняется и это быстро;
      3) FFmpeg собирает кадры обратно, сохраняя исходные FPS, разрешение,
         ориентацию и аудиодорожку оригинала.

    Маска ОДНА на всё видео (закрашивается на одном кадре в диалоге) — рассчитано
    на статичные объекты, что и нужно для водяных знаков/логотипов/эмодзи.

    Отмена (cancel) прерывает на любом этапе; временная папка удаляется ВСЕГДА —
    и при успехе, и при ошибке, и при отмене.
    """
    progress = pyqtSignal(int, str)      # (процент 0..100; -1 = «busy», текст фазы)
    done = pyqtSignal(str)               # путь готового файла
    failed = pyqtSignal(str)             # текст ошибки ("Отменено" при отмене)

    def __init__(self, inpainter, src, mask, fps, out_path, venc, has_audio):
        super().__init__()
        self._inp = inpainter
        # Абсолютный путь: ffmpeg для разных этапов вызывается в разное время, и
        # относительный путь ненадёжен (рабочий каталог процесса мог измениться).
        self._src = os.path.abspath(str(src))
        self._mask = mask                # numpy (H,W) uint8 {0,255}
        self._fps = float(fps) if fps and fps > 0 else 25.0
        self._out = str(out_path)
        self._venc = list(venc)          # аргументы видеокодировщика (как у «Обрезать»)
        self._has_audio = bool(has_audio)
        self._cancel = False
        self._proc = None                # текущий subprocess ffmpeg (для отмены)
        self._tmp = None

    def cancel(self):
        """Просит прервать обработку (потокобезопасно по флагу) и убивает текущий
        ffmpeg, если он запущен, чтобы отмена была мгновенной."""
        self._cancel = True
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    # Алиас для единообразной остановки в EditTab.shutdown (как у остальных воркеров).
    def stop(self):
        self.cancel()

    def _run_ffmpeg(self, cmd):
        """Запускает ffmpeg и ждёт завершения, периодически проверяя отмену.
        Возвращает returncode (или -1, если прервали по cancel)."""
        kw = {}
        if os.name == 'nt':
            kw['creationflags'] = CREATE_NO_WINDOW
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, **kw)
        try:
            while True:
                try:
                    return self._proc.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    if self._cancel:
                        try:
                            self._proc.terminate()
                        except Exception:
                            pass
                        try:
                            self._proc.wait(timeout=5)
                        except Exception:
                            pass
                        return -1
        finally:
            self._proc = None

    def run(self):
        # Загрузчик/сохранятель кадров — те же, что использует фоторедактор
        # (Unicode-безопасные обёртки над OpenCV). Импорт ленивый: тяжёлые
        # зависимости подтягиваются только при реальном запуске обработки.
        from lama_inpaint import load_bgr, save_bgr
        import shutil
        try:
            self._tmp = tempfile.mkdtemp(prefix="sihyx_vinp_")
            frames_dir = os.path.join(self._tmp, "frames")
            os.makedirs(frames_dir, exist_ok=True)
            patt = os.path.join(frames_dir, "%08d.png")

            # 1) Разбор видео на кадры (полное разрешение, дисплейная ориентация).
            self.progress.emit(-1, "Разбор видео на кадры…")
            if self._run_ffmpeg([FFMPEG, "-y", "-i", self._src, patt]) != 0 or self._cancel:
                raise RuntimeError("Отменено" if self._cancel
                                   else "Не удалось извлечь кадры из видео")

            frames = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
            total = len(frames)
            if total == 0:
                raise RuntimeError("В видео не найдено кадров")

            # 2) Прогрев модели ДО цикла (её загрузка длится ~10–25 c) — чтобы
            #    прогресс по кадрам шёл ровно, а не «застрял» на первом кадре.
            self.progress.emit(-1, "Загрузка модели LaMa…")
            try:
                self._inp.warmup()
            except Exception:
                pass
            if self._cancel:
                raise RuntimeError("Отменено")

            # 3) Покадровый инпейнт ТЕМ ЖЕ движком, что и для фото. Маска одна на
            #    всё видео; inpaint сам работает только по ROI вокруг неё.
            for i, name in enumerate(frames):
                if self._cancel:
                    raise RuntimeError("Отменено")
                fp = os.path.join(frames_dir, name)
                res = self._inp.inpaint(load_bgr(fp), self._mask)
                save_bgr(fp, res)        # перезаписываем кадр результатом (экономит диск)
                pct = 5 + int(88 * (i + 1) / total)
                self.progress.emit(pct, f"Удаление объекта… кадр {i + 1}/{total}")

            if self._cancel:
                raise RuntimeError("Отменено")

            # 4) Сборка обратно: исходные FPS + аудиодорожка из оригинала.
            self.progress.emit(95, "Сборка видео…")
            out_tmp = os.path.join(self._tmp, "out" + os.path.splitext(self._out)[1])

            def _assemble(copy_audio):
                cmd = [FFMPEG, "-y", "-framerate", f"{self._fps:.6f}", "-i", patt]
                if self._has_audio:
                    # Аудио берём из оригинала; copy — без потерь; при несовместимости
                    # контейнера/кодека (редко) ниже откатываемся на перекодировку в AAC.
                    cmd += ["-i", self._src, "-map", "0:v:0", "-map", "1:a?"]
                    cmd += (["-c:a", "copy"] if copy_audio
                            else ["-c:a", "aac", "-b:a", "192k"])
                else:
                    cmd += ["-map", "0:v:0"]
                cmd += self._venc + ["-pix_fmt", "yuv420p",
                                     "-movflags", "+faststart", "-shortest", out_tmp]
                return self._run_ffmpeg(cmd)

            rc = _assemble(copy_audio=True)
            if rc != 0 and not self._cancel and self._has_audio:
                # Аудио не скопировалось (несовместимый кодек для контейнера) —
                # пробуем ещё раз, перекодировав звук в AAC. Дорожка сохраняется.
                rc = _assemble(copy_audio=False)
            if rc != 0 or self._cancel:
                raise RuntimeError("Отменено" if self._cancel
                                   else "Не удалось собрать видео")

            # Переносим результат во финальное имя (терпимо к занятому файлу — как
            # обычная обрезка; см. EditTab._replace_tolerant).
            final = EditTab._replace_tolerant(out_tmp, self._out)
            self.done.emit(final)
        except Exception as e:
            msg = str(e)
            if self._cancel or msg == "Отменено":
                self.failed.emit("Отменено")
            else:
                import traceback
                traceback.print_exc()
                self.failed.emit(msg)
        finally:
            # Уборка временных файлов — безусловная.
            try:
                if self._tmp and os.path.isdir(self._tmp):
                    shutil.rmtree(self._tmp, ignore_errors=True)
            except Exception:
                pass


class _VideoMaskDialog(QDialog):
    """Диалог рисования маски удаления на одном кадре видео. ПЕРЕИСПОЛЬЗУЕТ
    InpaintCanvas из фоторедактора — то же самое рисование маски кистью, что и при
    удалении объекта с изображения (никакой новой логики рисования). Возвращает
    бинарную маску (numpy H×W uint8) через get_mask(); затем она применяется ко
    ВСЕМ кадрам видео в VideoInpaintWorker."""

    def __init__(self, frame_bgr, parent=None):
        super().__init__(parent)
        # Импорт холста ленивый: тянем тяжёлый модуль только при открытии диалога.
        from tabs import InpaintCanvas
        self._InpaintCanvas = InpaintCanvas
        self._mask = None
        self.setWindowTitle("Удаление объекта с видео")
        self.resize(960, 700)

        v = QVBoxLayout(self)
        hint = QLabel(
            "Закрасьте кистью объект (водяной знак, эмодзи, логотип и т.п.), который "
            "нужно убрать со ВСЕГО видео. Маска применяется ко всем кадрам, поэтому "
            "лучше всего подходит для статичных объектов в одном месте экрана.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        v.addWidget(hint)

        self.canvas = InpaintCanvas()
        self.canvas.set_image_bgr(frame_bgr)
        self.canvas.set_tool(InpaintCanvas.TOOL_MASK)
        self.canvas.set_brush(30)
        v.addWidget(self.canvas, 1)

        ctl = QHBoxLayout()
        lbl = QLabel("Размер кисти:")
        lbl.setStyleSheet(f"color:{C['text2']};")
        ctl.addWidget(lbl)
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(4, 160)
        sl.setValue(30)
        sl.setFixedWidth(220)
        sl.valueChanged.connect(self.canvas.set_brush)
        ctl.addWidget(sl)
        btn_clear = make_icon_btn("Очистить", icon='fa5s.eraser')
        btn_clear.clicked.connect(self.canvas.clear_mask)
        ctl.addWidget(btn_clear)
        ctl.addStretch(1)
        v.addLayout(ctl)

        bb = QDialogButtonBox()
        self.btn_ok = bb.addButton("Удалить объект с видео",
                                   QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _accept(self):
        m = self.canvas.get_mask()
        if m is None or int(m.max()) == 0:
            QMessageBox.information(
                self, "Маска пуста",
                "Сначала закрасьте кистью объект, который нужно удалить.")
            return
        self._mask = m
        self.accept()

    def get_mask(self):
        return self._mask


class ProxyWorker(QThread):
    finished = pyqtSignal(bool, str, str)
    progress = pyqtSignal(str)   # текст прогресса для волны: «Создание превью… N%»

    def __init__(self, input_path, output_path, parent=None, scale=1.0,
                 duration=0.0, limit_sec=0.0):
        super().__init__(parent)
        self.input_path = input_path
        self.output_path = output_path
        # scale<1.0 → прокси меньшего разрешения (быстрее воспроизведение/перемотка,
        # как «качество предпросмотра» в Filmora). 1.0 → только смена кодека.
        self.scale = float(scale) if scale else 1.0
        # limit_sec>0 → прокси только для первых N секунд файла (быстрее собрать
        # для тяжёлых/длинных видео; предпросмотр ограничен этим отрезком).
        self.limit_sec = float(limit_sec or 0.0)
        full = float(duration or 0.0)
        # Для процентов: если прокси усечён, ориентируемся на длину отрезка.
        self.total_dur = (min(full, self.limit_sec)
                          if (self.limit_sec > 0 and full > 0) else full)
        self.proc = None
        self._stopped = False

    def _run_with_progress(self, cmd, feed_path=None):
        """Запуск ffmpeg с -progress pipe:1 — по out_time_us показываем проценты
        создания прокси (как при извлечении аудио для H.264).

        stderr читаем ОТДЕЛЬНЫМ потоком, а не через communicate() после цикла по
        stdout. Иначе — взаимная блокировка: уже стартовый баннер ffmpeg (сведения
        о входе, libdav1d/libx264, длинная строка опций x264) больше буфера
        анонимного pipe в Windows (~4 КБ). ffmpeg повисает на записи в stderr →
        не пишет прогресс в stdout → наш `for line in stdout` ждёт строку, которой
        не будет → communicate() (он же дренаж stderr) недостижим. Для AV1 это
        100% дедлок («бесконечное создание превью»): AV1 — единственный путь, что
        вообще идёт через прокси (H.264 играется напрямую)."""
        full = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
        self.proc = subprocess.Popen(
            full, stdin=(subprocess.PIPE if feed_path else None),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW)
        if feed_path:
            start_share_delete_feeder(
                feed_path, self.proc.stdin, stop_flag=lambda: self._stopped)
        # Фоновый слив stderr — держим pipe пустым, чтобы ffmpeg не блокировался.
        err_chunks = []
        def _drain_err(pipe):
            try:
                for line in pipe:
                    err_chunks.append(line)
            except Exception:
                pass
        err_thread = threading.Thread(target=_drain_err, args=(self.proc.stderr,),
                                      daemon=True)
        err_thread.start()
        last_pct = -1
        try:
            for line in self.proc.stdout:
                if self._stopped:
                    break
                line = line.strip()
                if self.total_dur > 0 and line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        pct = max(0, min(99, int(us / (10000.0 * self.total_dur))))
                        if pct != last_pct:
                            last_pct = pct
                            self.progress.emit(f"Создание превью… {pct}%")
                    except Exception:
                        pass
        except Exception:
            pass
        self.proc.wait()
        err_thread.join(timeout=2.0)
        return self.proc.returncode, "".join(err_chunks)

    def run(self):
        # scale filter ensures even dimensions required by libx264. При scale<1
        # дополнительно уменьшаем кадр (превью-прокси).
        if self.scale < 0.999:
            vf = f"scale=trunc(iw*{self.scale}/2)*2:trunc(ih*{self.scale}/2)*2"
        else:
            vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        # Прокси оптимизирован под ПЕРЕМОТКУ (как proxy/optimized media в Filmora),
        # а не под размер:
        #   -g 12 -keyint_min 12 -sc_threshold 0 — ключевой кадр каждые ~0.5 с.
        #     При перемотке декодер стартует с ближайшего ключевого кадра; частые
        #     keyframe'ы = почти мгновенный seek (у исходных аниме-BDRip GOP до
        #     250+ кадров → каждый скраб декодирует секунды видео).
        #   -tune fastdecode — отключает deblock/CABAC ради скорости ДЕКОДИРОВАНИЯ
        #     (для превью-прокси качество вторично, важна лёгкость проигрывания).
        #   -pix_fmt yuv420p — 8-бит 4:2:0: 10-битные/4:4:4 источники иначе тянут
        #     медленный software-путь в QtMultimedia.
        #   +faststart — moov в начало файла: плеер открывает и сикает сразу.
        # -t N (выходная опция, после -i) — кодируем только первые N секунд.
        limit = ["-t", f"{self.limit_sec:.3f}"] if self.limit_sec > 0 else []

        def _base(src):
            return [
                FFMPEG, "-y", "-i", src,
            ] + limit + [
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode",
                "-crf", "23", "-pix_fmt", "yuv420p",
                "-g", "12", "-keyint_min", "12", "-sc_threshold", "0",
                "-vf", vf,
                "-movflags", "+faststart",
            ]

        # -map 0:v:0 + -map 0:a? — берём первое видео и ВСЕ аудиодорожки
        # исходника, чтобы в превью-режиме (когда играет прокси) переключение
        # озвучки работало так же, как на оригинале. Без явного -map ffmpeg клал
        # в прокси только дорожку по умолчанию → выбор другой озвучки в превью
        # не срабатывал (плеер видел всего одну дорожку).
        # Сначала кормим вход через FILE_SHARE_DELETE-пайп (исходник остаётся
        # удаляемым из Проводника, пока строится прокси); при неудаче — прямой вход.
        feed = str(self.input_path) if os.name == 'nt' else None
        cmds = []
        if feed:
            pbase = _base("pipe:0")
            cmds += [(pbase + ["-map", "0:v:0", "-map", "0:a?", "-c:a", "aac",
                               self.output_path], feed),
                     (pbase + ["-map", "0:v:0", "-an", self.output_path], feed)]
        fbase = _base(str(self.input_path))
        cmds += [(fbase + ["-map", "0:v:0", "-map", "0:a?", "-c:a", "aac",
                           self.output_path], None),
                 (fbase + ["-map", "0:v:0", "-an", self.output_path], None)]
        last_error = "неизвестная ошибка"
        for cmd, feed_path in cmds:
            if self._stopped:
                self.finished.emit(False, "Отменено", "")
                return
            try:
                self.progress.emit("Создание превью…")
                rc, err = self._run_with_progress(cmd, feed_path=feed_path)
                if self._stopped:
                    self.finished.emit(False, "Отменено", "")
                    return
                if rc == 0:
                    self.finished.emit(True, "OK", self.output_path)
                    return
                last_error = (err or "")[-600:] or f"код {rc}"
            except Exception as e:
                last_error = str(e)
        self.finished.emit(False, last_error, "")

    def stop(self):
        self._stopped = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass


class AudioWaveformLoader(QThread):
    # samples (combined max L/R для рисовки), duration, left, right (раздельные
    # огибающие каналов — для честного стерео-индикатора уровня).
    finished = pyqtSignal(list, float, list, list)
    progress = pyqtSignal(str)

    def __init__(self, filepath, audio_index, duration=0.0, parent=None):
        super().__init__(parent)
        self.filepath = str(filepath)
        self.audio_index = audio_index
        self.total_dur = float(duration or 0.0)   # для процентов извлечения
        self.tmp_wav = None
        self.proc = None
        self._stopped = False

    def _run_ffmpeg(self, cmd, feed_path=None):
        # -progress pipe:1 даёт машинный прогресс (out_time_us=…) — по нему
        # показываем проценты. -nostats глушит обычный лог в stderr.
        # feed_path задан → вход «pipe:0» кормим файлом через FILE_SHARE_DELETE
        # (исходник остаётся удаляемым из Проводника во время построения волны).
        full = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
        self.proc = subprocess.Popen(
            full, stdin=(subprocess.PIPE if feed_path else None),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW)
        feeder = None
        if feed_path:
            feeder = start_share_delete_feeder(
                feed_path, self.proc.stdin, stop_flag=lambda: self._stopped)
        last_pct = -1
        try:
            for line in self.proc.stdout:
                if self._stopped:
                    break
                line = line.strip()
                if self.total_dur > 0 and line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        pct = max(0, min(99, int(us / (10000.0 * self.total_dur))))
                        if pct != last_pct:
                            last_pct = pct
                            self.progress.emit(f"Извлечение аудио… {pct}%")
                    except Exception:
                        pass
        except Exception:
            pass
        self.proc.wait()
        return self.proc.returncode == 0

    def run(self):
        self.progress.emit("Извлечение аудио...")
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tf.close()
        self.tmp_wav = tf.name

        tail = []
        if self.audio_index is not None:
            tail += ["-map", f"0:{self.audio_index}"]
        # -ac 2: тянем ДВА канала (mono-источник ffmpeg продублирует — L==R, как и
        # положено; 5.1 сведёт в стерео) → у индикатора уровня честные L и R.
        tail += ["-af", "aresample=6000,asetpts=PTS-STARTPTS",
                 "-ac", "2", "-ar", "6000", "-f", "wav", self.tmp_wav]
        cmd_pipe = [FFMPEG, "-y", "-i", "pipe:0", "-vn"] + tail
        cmd_file = [FFMPEG, "-y", "-i", self.filepath, "-vn"] + tail

        ok = False
        # Сначала через FILE_SHARE_DELETE-пайп (исходник остаётся удаляемым во
        # время построения волны). Не для всех контейнеров pipe:0 годится
        # (moov в конце mp4 без faststart), поэтому при неудаче — прямой вход.
        if os.name == 'nt':
            try:
                ok = self._run_ffmpeg(cmd_pipe, feed_path=self.filepath)
            except Exception:
                ok = False
        if not ok and not self._stopped:
            try:
                ok = self._run_ffmpeg(cmd_file)
            except Exception as e:
                print("Audio extract failed:", e)

        if not ok and not self._stopped:
            try:
                ok = self._run_ffmpeg(
                    [FFMPEG, "-y", "-i", self.filepath, "-vn",
                     "-ac", "2", "-ar", "6000", "-f", "wav", self.tmp_wav])
            except Exception:
                ok = False

        if self._stopped or not ok or not os.path.exists(self.tmp_wav):
            self._cleanup_tmp()
            self.finished.emit([], 0.0, [], [])
            return

        self.progress.emit("Генерация волны...")
        try:
            samples, duration, left, right = self.read_wav_chunked(
                self.tmp_wav, target_samples=8000)
        except Exception:
            samples, duration, left, right = [], 0.0, [], []
        self._cleanup_tmp()
        self.finished.emit(samples, duration, left, right)

    def _cleanup_tmp(self):
        try:
            if self.tmp_wav and os.path.exists(self.tmp_wav):
                os.remove(self.tmp_wav)
        except Exception:
            pass

    def stop(self):
        self._stopped = True
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

    def read_wav_chunked(self, wav_path, target_samples=8000):
        """Возвращает (combined, duration, left, right): combined — поканальный
        максимум (для рисовки волны), left/right — раздельные огибающие каналов
        (для честного стерео-индикатора). Кадры деинтерливим (буфер L,R,L,R…)
        и считаем пики L и R в одних и тех же бакетах, чтобы шкалы были выровнены."""
        import array as _array
        try:
            wf = wave.open(wav_path, 'rb')
        except Exception:
            return [], 0.0, [], []

        n_frames  = wf.getnframes()
        framerate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        nchan     = max(1, wf.getnchannels())
        duration  = n_frames / framerate if framerate > 0 else 0.0

        if n_frames == 0:
            wf.close()
            return [], duration, [], []

        samples_per_pixel = max(1, n_frames // target_samples)
        chunk_size_frames = 256 * 1024

        if sampwidth == 1:
            typecode = 'B'; scale = 128.0; bias = 128
        elif sampwidth == 2:
            typecode = 'h'; scale = 32768.0; bias = 0
        elif sampwidth == 4:
            typecode = 'i'; scale = 2147483648.0; bias = 0
        else:
            wf.close()
            return [], duration, [], []

        def _peak(seg):
            if not len(seg):
                return 0.0
            hi = max(seg); lo = min(seg)
            if bias:
                return max(abs(hi - bias), abs(lo - bias)) / scale
            return max(abs(hi), abs(lo)) / scale

        comb: list[float] = []; left: list[float] = []; right: list[float] = []
        cur_l = 0.0; cur_r = 0.0; acc = 0

        processed = 0
        while processed < n_frames:
            if self._stopped:
                break
            raw = wf.readframes(chunk_size_frames)
            if not raw:
                break
            buf = _array.array(typecode, raw)
            if typecode != 'B' and sys.byteorder == 'big':
                buf.byteswap()
            if nchan >= 2:
                lbuf = buf[0::nchan]; rbuf = buf[1::nchan]
            else:
                lbuf = buf; rbuf = buf
            frames_in_chunk = len(lbuf)
            i = 0
            while i < frames_in_chunk:
                take = min(samples_per_pixel - acc, frames_in_chunk - i)
                if take <= 0:
                    break
                pl = _peak(lbuf[i: i + take])
                pr = _peak(rbuf[i: i + take])
                if pl > cur_l: cur_l = pl
                if pr > cur_r: cur_r = pr
                acc += take
                i += take
                if acc >= samples_per_pixel:
                    left.append(cur_l); right.append(cur_r)
                    comb.append(cur_l if cur_l > cur_r else cur_r)
                    cur_l = 0.0; cur_r = 0.0; acc = 0
            processed += frames_in_chunk

        wf.close()
        if not comb:
            return [0.0], duration, [0.0], [0.0]
        return comb, duration, left, right


# ─── Waveform Widget ──────────────────────────────────────────────────────────
class WaveformWidget(QWidget):
    seekRequested       = pyqtSignal(float)
    playSeekRequested   = pyqtSignal(float)
    inSetRequested      = pyqtSignal(float)
    outSetRequested     = pyqtSignal(float)
    selectionChanged    = pyqtSignal(float, float)
    viewChanged         = pyqtSignal(float, float)
    interactionStarted  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = []
        self.disp_samples = []   # нормированные+перцептивные значения для рисовки
        self.l_samples = []      # сырые огибающие каналов (для индикатора уровня)
        self.r_samples = []
        self.disp_l = []         # те же огибающие, нормированные как disp_samples
        self.disp_r = []
        self._norm = 1.0
        self.duration = 0.0
        self.in_s = 0.0
        self.out_s = 0.0
        self.playhead_s = 0.0
        self.setMinimumHeight(90)
        # ClickFocus: при клике/перетаскивании по волне фокус уходит на сам виджет
        # (а не остаётся на нативной видео-поверхности, которая исключена из
        # WidgetWithChildrenShortcut) — иначе Ctrl+Z/Ctrl+Y после работы с волной
        # не доходили до undo/redo.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)
        self.hover_x = None
        self.dragging = None
        self.drag_start_x = None
        self.orig_in = 0.0
        self.orig_out = 0.0
        self.tooltip_visible = False
        self.zoom = 1.0
        self.view_offset = 0.0
        self.loading_text = None
        self._anim_dots = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick_anim)
        self._cache: QPixmap | None = None
        self._cache_key = None

    def _tick_anim(self):
        self._anim_dots = (self._anim_dots + 1) % 4
        self.update()

    def set_loading(self, text, animated=True):
        """Текст по центру полосы вместо волны. animated=True — «бегущие» точки
        (идёт процесс: создание превью/извлечение аудио). animated=False — статичная
        подсказка БЕЗ анимации точек (напр. «включите Пикселизацию» для картинки):
        бегущие точки там выглядят как несуществующий процесс и раздражают."""
        self.loading_text = text
        self.samples = []
        if animated:
            self._anim_timer.start(400)
        else:
            self._anim_timer.stop()
            self._anim_dots = 0
        self.update()

    def _compute_display_samples(self):
        """Готовит значения для рисовки: нормирует амплитуду по 97-му перцентилю
        (устойчиво к одиночным щелчкам) и прогоняет через перцептивную кривую.
        У типичного контента линейный пик низкий, поэтому без этого волна «прибита»
        к центру и кажется, что звука нет — хотя он есть. Так волна заполняет полосу
        там, где звук реально присутствует."""
        s = self.samples
        if not s:
            self.disp_samples = []
            self.disp_l = []
            self.disp_r = []
            self._norm = 1.0
            return
        ordered = sorted(s)
        ref = ordered[min(len(ordered) - 1, int(len(ordered) * 0.97))]
        ref = max(ref, 0.06)   # пол: чтобы тишина/фон не раздувались на всю высоту
        norm = 1.0 / ref
        self._norm = norm
        self.disp_samples = [min(1.0, (v * norm) ** 0.62) for v in s]
        # Каналы нормируем тем же эталоном/кривой, что и общую волну — иначе шкалы
        # L/R «жили» бы в своём масштабе и не сравнивались между собой.
        self.disp_l = [min(1.0, (v * norm) ** 0.62) for v in self.l_samples]
        self.disp_r = [min(1.0, (v * norm) ** 0.62) for v in self.r_samples]

    def level_at(self, t):
        """Перцептивный уровень (0..1) на позиции t — кормит индикатор громкости."""
        ds = self.disp_samples
        if not ds or self.duration <= 0:
            return 0.0
        idx = int(t / self.duration * len(ds))
        idx = max(0, min(len(ds) - 1, idx))
        return ds[idx]

    def level_at_lr(self, t):
        """Перцептивные уровни (L, R) на позиции t — для честного стерео-индикатора.
        Если поканальных данных нет (старый путь/моно) — оба равны общему уровню."""
        if self.duration <= 0:
            return 0.0, 0.0
        dl, dr = self.disp_l, self.disp_r
        if not dl or not dr:
            lvl = self.level_at(t)
            return lvl, lvl
        il = max(0, min(len(dl) - 1, int(t / self.duration * len(dl))))
        ir = max(0, min(len(dr) - 1, int(t / self.duration * len(dr))))
        return dl[il], dr[ir]

    def set_data(self, samples, duration, samples_l=None, samples_r=None):
        self.loading_text = None
        self._anim_timer.stop()
        self.samples = samples
        self.l_samples = samples_l or []
        self.r_samples = samples_r or []
        self._compute_display_samples()
        self.duration = max(0.0, float(duration))
        if self.duration <= 0:
            self.in_s = 0.0; self.out_s = 0.0
        else:
            if not (0.0 <= self.in_s < self.out_s <= self.duration):
                self.in_s = 0.0; self.out_s = max(0.001, self.duration)
        self.zoom = 1.0
        self.view_offset = 0.0
        self.viewChanged.emit(self.view_offset, max(0.001, self.duration / self.zoom))
        self.update()

    def reset_markers(self):
        """Полный сброс волны к «пустому» состоянию при загрузке НОВОГО файла:
        границы IN/OUT (красная/зелёная полоски), плейхед, зум и окно обзора.
        Без этого при добавлении нового файла маркеры предыдущего оставались
        на месте (старые in/out + старая длительность задавали их пиксельную
        позицию), пока не догрузится новая волна — выглядело как «не сбросились»."""
        self.samples = []
        self.disp_samples = []
        self.l_samples = []
        self.r_samples = []
        self.disp_l = []
        self.disp_r = []
        self.duration = 0.0
        self.in_s = 0.0
        self.out_s = 0.0
        self.playhead_s = 0.0
        self.zoom = 1.0
        self.view_offset = 0.0
        self._cache = None
        self._cache_key = None
        self.update()

    def set_in_out(self, in_s, out_s, keep_view=False):
        self.in_s = max(0.0, min(in_s, self.duration))
        self.out_s = max(0.0, min(out_s, self.duration))
        if self.out_s <= self.in_s:
            self.out_s = min(self.duration, self.in_s + 0.001)
        # keep_view=True: не дёргаем окно обзора при ручной обрезке (иначе при
        # зуме виджет каждый раз перецентрируется на выделение).
        if not keep_view:
            self.ensure_view_contains(self.in_s, self.out_s)
        self.selectionChanged.emit(self.in_s, self.out_s)
        self.update()

    def set_playhead(self, t):
        self.playhead_s = max(0.0, min(t, self.duration))
        self.update()

    def ensure_view_contains(self, a, b):
        if self.duration <= 0:
            return
        visible = max(0.001, self.duration / self.zoom)
        sel_center = (a + b) / 2.0
        left = self.view_offset; right = self.view_offset + visible
        if a < left or b > right:
            new_left = sel_center - visible / 2.0
            new_left = max(0.0, min(new_left, max(0.0, self.duration - visible)))
            self.view_offset = new_left
            self.viewChanged.emit(self.view_offset, visible)

    def _draw_static(self, painter, w, h):
        """Draw all static elements (everything except playhead and hover cursor)."""
        mid = h / 2.0

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(30, 30, 46))   # base
        grad.setColorAt(1.0, QColor(24, 24, 37))   # mantle
        painter.fillRect(0, 0, w, h, QBrush(grad))

        painter.setPen(QPen(QColor(69, 71, 90), 1))  # surface1
        painter.drawLine(0, int(mid), w, int(mid))

        if self.loading_text:
            dots = "." * self._anim_dots
            txt = f"{self.loading_text}{dots}"
            painter.setPen(QPen(QColor(137, 180, 250)))  # blue
            font = painter.font()
            font.setPointSize(10)
            font.setFamily("Segoe UI" if os.name == 'nt' else "SF Pro Display")
            painter.setFont(font)
            painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, txt)
            return

        visible_duration = max(0.001, self.duration / self.zoom)

        def time_to_x(t):
            rel = (t - self.view_offset) / visible_duration
            return int(rel * w)

        if self.disp_samples and self.duration > 0:
            n = len(self.disp_samples)
            scale_bg = (h / 2) * 0.86
            for i in range(0, w):
                t = self.view_offset + (i / max(1, w)) * visible_duration
                if t > self.duration:
                    break  # за пределами клипа (при отдалении zoom<1) — пусто
                idx = int((t / self.duration) * n)
                idx = max(0, min(n - 1, idx))
                val = self.disp_samples[idx]
                v = val * 0.92
                y1 = int(mid - v * scale_bg)
                y2 = int(mid + v * scale_bg)
                alpha = int(110 + val * 70)
                painter.setPen(QPen(QColor(108, 117, 161, alpha)))  # muted blue/overlay
                painter.drawLine(i, y1, i, y2)
        else:
            if self.duration > 0:
                painter.setPen(QPen(QColor(C["text3"])))
                font = painter.font(); font.setPointSize(9)
                painter.setFont(font)
                painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "Нет аудио данных")
            else:
                painter.setPen(QPen(QColor(C["text3"])))
                font = painter.font(); font.setPointSize(10)
                painter.setFont(font)
                painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                                 "Перетащите видео или аудио файл сюда")

        painter.setPen(QPen(QColor(C["border"]), 1))
        painter.drawLine(0, 0, w, 0)
        painter.drawLine(0, h - 1, w, h - 1)

        if self.duration <= 0:
            return

        x_in  = time_to_x(self.in_s)
        x_out = time_to_x(self.out_s)
        if x_out < x_in:
            x_in, x_out = x_out, x_in

        sel_w = max(1, x_out - x_in)
        painter.setBrush(QBrush(QColor(137, 180, 250, 28)))  # blue selection wash
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(x_in, 0, sel_w, h)

        if self.disp_samples and self.duration > 0:
            n = len(self.disp_samples)
            scale_sel = (h / 2) * 0.92
            left_i = max(0, x_in); right_i = min(w - 1, x_out)
            for i in range(left_i, right_i + 1):
                t = self.view_offset + (i / max(1, w)) * visible_duration
                idx = int((t / self.duration) * n)
                if idx >= n:
                    break
                val = self.disp_samples[idx]
                v = val * 1.04
                y1 = int(mid - v * scale_sel)
                y2 = int(mid + v * scale_sel)
                alpha = int(180 + val * 60)
                painter.setPen(QPen(QColor(137, 180, 250, alpha)))  # blue
                painter.drawLine(i, y1, i, y2)

        painter.setPen(QPen(QColor(C["red"]), 2))
        painter.drawLine(x_in, 0, x_in, h)
        painter.setPen(QPen(QColor(C["green"]), 2))
        painter.drawLine(x_out, 0, x_out, h)

        handle_r = max(5, int(h * 0.055))
        painter.setBrush(QBrush(QColor(C["red"])))
        painter.setPen(QPen(QColor(C["bg"]), 1))
        painter.drawEllipse(QPoint(x_in, int(mid)), handle_r, handle_r)
        painter.setBrush(QBrush(QColor(C["green"])))
        painter.setPen(QPen(QColor(C["bg"]), 1))
        painter.drawEllipse(QPoint(x_out, int(mid)), handle_r, handle_r)

        painter.setPen(QPen(QColor(C["text"])))
        font = painter.font(); font.setPointSize(6); font.setBold(True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        for label, x_pos, col in [("I", x_in, C["red"]), ("O", x_out, C["green"])]:
            lw = fm.horizontalAdvance(label)
            painter.setPen(QPen(QColor(col)))
            painter.drawText(x_pos - lw // 2, int(mid) + fm.ascent() // 2, label)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width(); h = self.height()

        # Cache key covers everything that affects static drawing.
        # Playhead and hover cursor are drawn dynamically on top.
        cache_key = (w, h, id(self.samples), len(self.samples),
                     self.duration, self.zoom, self.view_offset,
                     self.in_s, self.out_s, self.loading_text, self._anim_dots)
        if self._cache is None or self._cache_key != cache_key:
            self._cache = QPixmap(w, h)
            self._cache_key = cache_key
            cp = QPainter(self._cache)
            cp.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_static(cp, w, h)
            cp.end()

        painter.drawPixmap(0, 0, self._cache)

        if self.loading_text or self.duration <= 0:
            return

        visible_duration = max(0.001, self.duration / self.zoom)

        def time_to_x(t):
            rel = (t - self.view_offset) / visible_duration
            return int(rel * w)

        # Playhead
        if 0.0 <= self.playhead_s <= self.duration:
            vis_end = self.view_offset + visible_duration
            if self.view_offset <= self.playhead_s <= vis_end:
                x_ph = time_to_x(self.playhead_s)
                painter.setPen(QPen(QColor(C["playhead"]), 2, Qt.PenStyle.SolidLine))
                painter.drawLine(x_ph, 0, x_ph, h)
                path = QPainterPath()
                path.moveTo(x_ph - 5, 0)
                path.lineTo(x_ph + 5, 0)
                path.lineTo(x_ph, 8)
                path.closeSubpath()
                painter.setBrush(QBrush(QColor(C["playhead"])))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPath(path)

        # Hover cursor
        if self.hover_x is not None:
            hx = int(self.hover_x)
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.DotLine))
            painter.drawLine(hx, 0, hx, h)

    # ── Mouse events ───────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        # ПКМ — не сик/перетаскивание, а контекстное меню обрезки (его поднимает
        # customContextMenuRequested). Иначе правый клик дёргал бы плейхед.
        if ev.button() == Qt.MouseButton.RightButton:
            ev.ignore(); return
        # Забираем клавиатурный фокус НА СЕБЯ: метод переопределён и не зовёт
        # super().mousePressEvent(), поэтому штатный перехват фокуса по ClickFocus
        # не срабатывает, и фокус оставался на нативной видео-поверхности
        # (исключена из WidgetWithChildrenShortcut) → Ctrl+Z/Ctrl+Y после
        # перетаскивания полоски не доходили до undo/redo.
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        try:
            x = ev.position().x()
        except Exception:
            x = ev.x()
        if self.duration <= 0 or self.loading_text:
            self.seekRequested.emit(0.0); return
        w = max(1, self.width()); x = max(0, min(w, x))

        def time_to_x_local(t):
            visible = max(0.001, self.duration / self.zoom)
            rel = (t - self.view_offset) / visible
            return int(rel * w)

        x_in  = time_to_x_local(self.in_s)
        x_out = time_to_x_local(self.out_s)
        threshold = 8
        modifiers = QApplication.keyboardModifiers()
        if not (modifiers & Qt.KeyboardModifier.ControlModifier):
            if abs(x - x_in) <= threshold:
                self.interactionStarted.emit()
                self.dragging = 'in'; self.drag_start_x = x; self.orig_in = self.in_s
                self.show_tooltip_for_pos(ev); return
            if abs(x - x_out) <= threshold:
                self.interactionStarted.emit()
                self.dragging = 'out'; self.drag_start_x = x; self.orig_out = self.out_s
                self.show_tooltip_for_pos(ev); return
            left = min(x_in, x_out); right = max(x_in, x_out)
            if (right - left) > (threshold * 3) and (left + threshold < x < right - threshold):
                self.interactionStarted.emit()
                self.dragging = 'maybe_move'; self.drag_start_x = x
                self.orig_in = self.in_s; self.orig_out = self.out_s
                self.show_tooltip_for_pos(ev); return
        rel = x / w
        t = self.view_offset + rel * max(0.001, self.duration / self.zoom)
        t = max(0.0, min(self.duration, t))
        self.seekRequested.emit(t)

    def mouseMoveEvent(self, ev):
        try:
            mx = ev.position().x(); gpos = ev.globalPosition()
        except Exception:
            mx = ev.x(); gpos = ev.globalPos()
        self.hover_x = mx
        if self.dragging and self.duration > 0:
            w = max(1, self.width()); mx = max(0, min(w, mx))
            if self.dragging == 'maybe_move':
                if abs(mx - (self.drag_start_x if self.drag_start_x is not None else mx)) < 6:
                    self.show_tooltip_at_global_pos(gpos, self.hover_time_from_x(mx))
                    self.update(); return
                else:
                    self.dragging = 'move'; self.orig_in = self.in_s; self.orig_out = self.out_s
            visible = max(0.001, self.duration / self.zoom)
            if self.dragging == 'in':
                t = self.view_offset + (mx / w) * visible
                new_in = max(0.0, min(t, self.out_s - (1.0 / 1000.0)))
                self.in_s = new_in
                self.inSetRequested.emit(self.in_s); self.selectionChanged.emit(self.in_s, self.out_s)
            elif self.dragging == 'out':
                t = self.view_offset + (mx / w) * visible
                new_out = min(self.duration, max(t, self.in_s + (1.0 / 1000.0)))
                self.out_s = new_out
                self.outSetRequested.emit(self.out_s); self.selectionChanged.emit(self.in_s, self.out_s)
            elif self.dragging == 'move':
                start_t = self.view_offset + ((self.drag_start_x if self.drag_start_x is not None else mx) / w) * visible
                cur_t   = self.view_offset + (mx / w) * visible
                shift = cur_t - start_t
                new_in = self.orig_in + shift; new_out = self.orig_out + shift
                if new_in < 0:
                    shift_c = -new_in; new_in += shift_c; new_out += shift_c
                if new_out > self.duration:
                    shift_c = new_out - self.duration; new_in -= shift_c; new_out -= shift_c
                self.in_s = new_in; self.out_s = new_out
                self.inSetRequested.emit(self.in_s)
                self.outSetRequested.emit(self.out_s)
                self.selectionChanged.emit(self.in_s, self.out_s)
            self.show_tooltip_at_global_pos(gpos, self.hover_time_from_x(mx))
            self.update(); return
        self.update()

    def mouseReleaseEvent(self, ev):
        try:
            rx = ev.position().x()
        except Exception:
            rx = ev.x()
        if self.dragging == 'maybe_move':
            w = max(1, self.width()); rx = max(0, min(w, rx))
            visible = max(0.001, self.duration / self.zoom)
            t = self.view_offset + (rx / w) * visible
            t = max(0.0, min(self.duration, t))
            self.playSeekRequested.emit(t)
        self.dragging = None; self.drag_start_x = None
        self.orig_in = 0.0; self.orig_out = 0.0
        QToolTip.hideText(); self.tooltip_visible = False

    def leaveEvent(self, ev):
        self.hover_x = None; QToolTip.hideText(); self.tooltip_visible = False; self.update()

    def hover_time_from_x(self, x):
        w = max(1, self.width())
        rel = max(0.0, min(1.0, x / w))
        visible = max(0.001, self.duration / self.zoom)
        return self.view_offset + rel * visible

    def show_tooltip_for_pos(self, ev):
        try:
            gpos = ev.globalPosition(); x = ev.position().x()
        except Exception:
            gpos = ev.globalPos(); x = ev.x()
        t = self.hover_time_from_x(x)
        self.show_tooltip_at_global_pos(gpos, t)

    def show_tooltip_at_global_pos(self, gpos, t):
        try:
            if hasattr(gpos, 'toPoint'):
                gp = gpos.toPoint()
            elif hasattr(gpos, 'x'):
                gp = QPoint(int(gpos.x()), int(gpos.y()))
            else:
                gp = gpos
        except Exception:
            gp = None
        txt = s_to_time(t)
        if gp:
            QToolTip.showText(gp, txt, self); self.tooltip_visible = True
        else:
            QToolTip.hideText(); self.tooltip_visible = False

    def wheelEvent(self, event):
        modifiers = QApplication.keyboardModifiers()
        if not (modifiers & Qt.KeyboardModifier.ControlModifier):
            event.ignore(); return
        delta = 0
        try:
            delta = event.angleDelta().y()
        except Exception:
            delta = event.delta()
        if delta == 0:
            return
        try:
            cursor_x = event.position().x()
        except Exception:
            cursor_x = event.x()
        w = max(1, self.width())
        visible_before = max(0.001, self.duration / self.zoom)
        t_at_cursor = self.view_offset + (cursor_x / w) * visible_before
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        # min 0.25 — можно отдалиться так, что клип займёт ~1/4 ширины (как в
        # типичных видеоредакторах), оставив свободное место справа.
        new_zoom = max(0.25, min(self.zoom * factor, 200.0))
        visible_after = max(0.001, self.duration / new_zoom)
        new_view = t_at_cursor - (cursor_x / w) * visible_after
        # Зум у самого края: «5%» считаем ВИЗУАЛЬНЫМИ — 5% от ширины видимого
        # окна, а не от всей длительности клипа. Иначе на длинном клипе порог
        # (5% длительности) огромен в секундах и при зуме где-то у начала окно
        # ни с того ни с сего «прыгало» в 0. Теперь снап срабатывает, только
        # когда край клипа реально близок к краю экрана (≤5% видимой части).
        edge = 0.05 * visible_after
        if t_at_cursor <= edge:
            new_view = 0.0
        elif t_at_cursor >= self.duration - edge:
            new_view = max(0.0, self.duration - visible_after)
        new_view = max(0.0, min(new_view, max(0.0, self.duration - visible_after)))
        self.zoom = new_zoom; self.view_offset = new_view
        self.viewChanged.emit(self.view_offset, visible_after)
        self.update(); event.accept()

    def set_view_offset(self, offset):
        visible = max(0.001, self.duration / self.zoom)
        offset = max(0.0, min(offset, max(0.0, self.duration - visible)))
        self.view_offset = offset
        self._cache = None
        self.viewChanged.emit(self.view_offset, visible)
        self.update()

    def set_zoom(self, zoom):
        self.zoom = max(0.25, min(zoom, 200.0))
        visible = max(0.001, self.duration / self.zoom)
        self.view_offset = max(0.0, min(self.view_offset, max(0.0, self.duration - visible)))
        self._cache = None
        self.viewChanged.emit(self.view_offset, visible)
        self.update()


# ─── Small UI helpers ─────────────────────────────────────────────────────────
def make_divider():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {C['border']}; border: none; border-top: 1px solid {C['border']};")
    line.setFixedHeight(1)
    return line


def make_icon_btn(text, icon_std=None, accent=False, danger=False, w=None, icon=None):
    btn = QPushButton(text)
    # На светлой заливке (accent/danger) — тёмные значок и текст: контраст лучше,
    # чем белый по светло-голубому/розовому (ср. кнопку «НАЧАТЬ» — тёмное по зелёному).
    on_fill = accent or danger
    fg = "#11111b" if on_fill else C["text"]
    if icon:
        # Векторная иконка qtawesome (см. get_icon в config.py).
        btn.setIcon(get_icon(icon, color=fg))
        btn.setIconSize(QSize(20, 20))
    elif icon_std:
        btn.setIcon(QApplication.style().standardIcon(icon_std))
    base_bg = C["accent"] if accent else (C["red"] if danger else C["surface3"])
    hover_bg = C["accent2"] if accent else (C["red2"] if danger else C["border2"])
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {base_bg};
            color: {fg};
            border: 1px solid {C['border2'] if not accent and not danger else 'transparent'};
            border-radius: 6px;
            padding: 7px 14px;
            font-weight: 500;
            font-size: 13px;
        }}
        QPushButton:hover {{ background: {hover_bg}; }}
        QPushButton:pressed {{ background: {C['surface2']}; }}
        QPushButton:disabled {{
            background: {C['surface2']};
            color: {C['text3']};
            border: 1px solid {C['border2']};
        }}
    """)
    if w:
        btn.setFixedWidth(w)
    return btn


def _fullscreen_icon(expand=True, color="#ffffff", size=32):
    """Рисует значок полноэкранного режима «как на YouTube» — четыре уголка.
    expand=True  → уголки в углах рамки (войти в полноэкранный режим);
    expand=False → уголки сдвинуты к центру (выйти из полноэкранного)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(2.0, size * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    m = size * 0.22          # отступ уголков от края рамки
    arm = size * 0.20        # длина «плеча» уголка
    cen = size / 2.0
    if expand:
        # Уголки в четырёх углах, плечи смотрят внутрь.
        corners = [(m, m, 1, 1), (size - m, m, -1, 1),
                   (m, size - m, 1, -1), (size - m, size - m, -1, -1)]
    else:
        # Уголки стянуты к центру, плечи смотрят наружу (к углам экрана).
        g = size * 0.10
        corners = [(cen - g, cen - g, -1, -1), (cen + g, cen - g, 1, -1),
                   (cen - g, cen + g, -1, 1), (cen + g, cen + g, 1, 1)]
    for cx, cy, dx, dy in corners:
        p.drawLine(int(cx), int(cy), int(cx + dx * arm), int(cy))
        p.drawLine(int(cx), int(cy), int(cx), int(cy + dy * arm))
    p.end()
    return QIcon(pm)


class VolumeSlider(QSlider):
    """Ползунок громкости: колёсико над ним всегда меняет громкость шагом 5
    (как и над значком динамика), независимо от глобальной опции «колесо меняет
    значения». Помечен свойством wheelAlways, чтобы WheelBlocker его не глушил."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setProperty("wheelAlways", True)

    def wheelEvent(self, ev):
        step = 5 if ev.angleDelta().y() > 0 else -5
        self.setValue(max(self.minimum(), min(self.maximum(), self.value() + step)))
        ev.accept()


class VolumeLabel(QLabel):
    """Значок динамика: прокрутка колёсиком над ним меняет громкость.
    slider_getter — функция, возвращающая связанный QSlider громкости."""

    def __init__(self, slider_getter, parent=None):
        super().__init__(parent)
        self._slider_getter = slider_getter
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Громкость — прокрутите колёсиком над динамиком")
        self.update_glyph(100)

    def update_glyph(self, vol):
        name = ('fa5s.volume-mute' if vol <= 0
                else ('fa5s.volume-down' if vol < 55 else 'fa5s.volume-up'))
        self.setPixmap(get_icon_pixmap(name, 18))

    def wheelEvent(self, ev):
        sl = self._slider_getter() if self._slider_getter else None
        if sl is None:
            super().wheelEvent(ev)
            return
        step = 5 if ev.angleDelta().y() > 0 else -5
        sl.setValue(max(sl.minimum(), min(sl.maximum(), sl.value() + step)))
        ev.accept()


# ─── Info Card ────────────────────────────────────────────────────────────────
class InfoCard(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("InfoCard")
        self.setStyleSheet(f"""
            #InfoCard {{
                background: {C['surface2']};
                border: 1px solid {C['border']};
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        # Заголовок не должен распирать карточку/панель по своей длине.
        _sp = title_lbl.sizePolicy(); _sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        title_lbl.setSizePolicy(_sp)
        layout.addWidget(title_lbl)
        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        layout.addLayout(self._body)

    def add_row(self, label, value_attr):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        val = QLabel("—")
        val.setStyleSheet(f"color: {C['text']}; font-size: 12px; font-weight: 500;")
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(val)
        self._body.addLayout(row)
        setattr(self, value_attr, val)
        return val


# ─── Audio level meter (VU) ────────────────────────────────────────────────────
class AudioMeter(QWidget):
    """Стерео-индикатор уровня звука: две вертикальные шкалы (зелёный→жёлтый→
    красный) с пик-маркерами и плавным спадом. Уровни 0..1 подаёт плеер во время
    воспроизведения (берутся из аудиоволны на позиции плейхеда)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(56)
        self.setMaximumWidth(96)
        self.setMinimumHeight(120)
        self._l = 0.0
        self._r = 0.0
        self._pk_l = 0.0
        self._pk_r = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._decay)
        self._timer.start()

    def set_levels(self, l, r=None):
        if r is None:
            r = l
        self._l = max(0.0, min(1.0, float(l)))
        self._r = max(0.0, min(1.0, float(r)))
        if self._l > self._pk_l: self._pk_l = self._l
        if self._r > self._pk_r: self._pk_r = self._r
        self.update()

    def reset(self):
        self._l = self._r = self._pk_l = self._pk_r = 0.0
        self.update()

    def _decay(self):
        changed = False
        for a, d in (('_l', 0.08), ('_r', 0.08), ('_pk_l', 0.02), ('_pk_r', 0.02)):
            v = getattr(self, a)
            if v > 0:
                setattr(self, a, max(0.0, v - d)); changed = True
        if changed:
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        w = self.width(); h = self.height()
        p.fillRect(0, 0, w, h, QColor(C["bg"]))
        m_top, m_bot = 10, 16
        bar_h = max(1, h - m_top - m_bot)
        gap = 6
        bw = max(6, int((w - gap * 3) / 2))
        data = [(self._l, self._pk_l, "L"), (self._r, self._pk_r, "R")]
        for i, (lvl, pk, label) in enumerate(data):
            x = gap + i * (bw + gap)
            y = m_top
            grad = QLinearGradient(0, y, 0, y + bar_h)
            grad.setColorAt(0.0, QColor(C["red"]))
            grad.setColorAt(0.45, QColor(C["yellow"]))
            grad.setColorAt(1.0, QColor(C["green"]))
            # Тусклый «трек» во всю высоту
            p.setOpacity(0.16); p.fillRect(x, y, bw, bar_h, QBrush(grad)); p.setOpacity(1.0)
            # Яркая заполненная часть снизу до текущего уровня
            fill_h = int(bar_h * lvl)
            if fill_h > 0:
                p.setClipRect(x, y + bar_h - fill_h, bw, fill_h)
                p.fillRect(x, y, bw, bar_h, QBrush(grad))
                p.setClipping(False)
            # Пик-маркер
            if pk > 0:
                py = y + bar_h - int(bar_h * pk)
                p.setPen(QPen(QColor(C["text"]), 1))
                p.drawLine(x, py, x + bw, py)
            # Подпись канала
            p.setPen(QPen(QColor(C["text3"])))
            f = p.font(); f.setPointSize(8); p.setFont(f)
            p.drawText(QRect(x, h - m_bot + 1, bw, m_bot - 1),
                       Qt.AlignmentFlag.AlignCenter, label)
        p.end()


def _parse_srt(text):
    """Простой парсер SRT → список (start_s, end_s, text). Теги (<...>, {\\...})
    вырезаются — для превью нужен чистый текст в стиле VLC."""
    import re
    cues = []
    if not text:
        return cues

    def _ts(s):
        s = s.replace(',', '.').strip()
        try:
            hh, mm, rest = s.split(':')
            return int(hh) * 3600 + int(mm) * 60 + float(rest)
        except Exception:
            return None

    blocks = re.split(r'\r?\n\r?\n', text.strip())
    tag_re = re.compile(r'<[^>]+>|\{[^}]*\}')
    time_re = re.compile(r'(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})')
    for b in blocks:
        lines = [ln for ln in b.splitlines() if ln.strip() != '']
        if not lines:
            continue
        # Находим строку с таймкодами (может быть после номера-индекса).
        ti = None
        for i, ln in enumerate(lines):
            m = time_re.search(ln)
            if m:
                ti = i; tm = m; break
        if ti is None:
            continue
        start = _ts(tm.group(1)); end = _ts(tm.group(2))
        if start is None or end is None:
            continue
        body = "\n".join(lines[ti + 1:]).strip()
        body = tag_re.sub('', body).strip()
        if body:
            cues.append((start, end, body))
    cues.sort(key=lambda c: c[0])
    return cues


class SubtitleExtractor(QThread):
    """Извлекает выбранную текстовую дорожку субтитров в SRT и парсит её —
    в фоне, чтобы не подвешивать GUI."""
    done = pyqtSignal(int, object)   # (token, cues|None)

    def __init__(self, src, sub_index, token):
        super().__init__()
        self.src = str(src)
        self.sub_index = int(sub_index)
        self.token = int(token)

    def run(self):
        cues = None
        tmp = None
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
            tmp = tf.name; tf.close()
            cmd = [FFMPEG, "-y", "-i", self.src,
                   "-map", f"0:s:{self.sub_index}", tmp]
            kw = {}
            if os.name == 'nt':
                kw['creationflags'] = CREATE_NO_WINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=90, **kw)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                    cues = _parse_srt(f.read())
        except Exception:
            cues = None
        finally:
            if tmp:
                try: os.remove(tmp)
                except Exception: pass
        self.done.emit(self.token, cues)


class AssExtractor(QThread):
    """Извлекает выбранную дорожку субтитров в .ass (для рендера через libass) —
    в фоне. Эмитит (token, путь_к_ass|None)."""
    done = pyqtSignal(int, object)   # (token, ass_path|None)

    def __init__(self, src, sub_index, token):
        super().__init__()
        self.src = str(src)
        self.sub_index = int(sub_index)
        self.token = int(token)

    def run(self):
        out = None
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
            out = tf.name; tf.close()
            cmd = [FFMPEG, "-y", "-i", self.src,
                   "-map", f"0:s:{self.sub_index}", "-c:s", "ass", out]
            kw = {}
            if os.name == 'nt':
                kw['creationflags'] = CREATE_NO_WINDOW
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=120, **kw)
            if not (os.path.exists(out) and os.path.getsize(out) > 0):
                try: os.remove(out)
                except Exception: pass
                out = None
        except Exception:
            if out:
                try: os.remove(out)
                except Exception: pass
            out = None
        self.done.emit(self.token, out)


def _paint_subtitle(painter, rect, text="", px=28, image=None, image_pos=(0, 0)):
    """Рисует субтитры в области rect: либо готовый кадр от libass (image,
    приоритетнее), либо стиль VLC — белый жирный текст с чёрной обводкой снизу
    по центру. Используется и оверлеем-окном, и встроенным рендером в кадр."""
    if image is not None and not image.isNull():
        painter.drawImage(rect.left() + image_pos[0], rect.top() + image_pos[1], image)
        return
    if not text:
        return
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont("Arial"); f.setBold(True); f.setPixelSize(px)
    painter.setFont(f)
    margin_v = max(10, int(rect.height() * 0.05))
    side = int(rect.width() * 0.05)
    area = QRect(rect.left() + side, rect.top(),
                 max(10, rect.width() - 2 * side),
                 max(10, rect.height() - margin_v))
    flags = (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
             | Qt.TextFlag.TextWordWrap)
    o = max(2, px // 11)   # толщина обводки
    painter.setPen(QPen(QColor(0, 0, 0)))
    for dx in (-o, 0, o):
        for dy in (-o, 0, o):
            if dx == 0 and dy == 0:
                continue
            painter.drawText(area.translated(dx, dy), flags, text)
    painter.setPen(QPen(QColor(255, 255, 255)))
    painter.drawText(area, flags, text)


class SubtitleOverlay(QWidget):
    """Оверлей субтитров в стиле VLC/PotPlayer: белый жирный текст с чёрной
    обводкой, без подложки.

    ВАЖНО: QVideoWidget рендерит видео через нативную поверхность (RHI), поэтому
    обычный дочерний/соседний виджет рисуется ПОД видео и не виден. Чтобы текст
    стабильно был поверх кадра, оверлей сделан отдельным БЕСРАМОЧНЫМ полупрозрачным
    окном-«насадкой» со сквозным вводом, которое подгоняется под экранную область
    видео (см. EditTab._position_overlay)."""

    def __init__(self, parent=None):
        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.Tool
                 | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.WindowTransparentForInput)
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._text = ""
        self._px = 28
        self._image = None       # кадр субтитров от libass (QImage) — приоритетнее текста
        self._image_pos = (0, 0) # позиция левого верхнего угла картинки в оверлее

    def place_over(self, widget):
        """Подгоняет окно-оверлей под экранную область целевого виджета (видео)."""
        if widget is None or not widget.isVisible():
            self.hide()
            return
        tl = widget.mapToGlobal(QPoint(0, 0))
        w, h = widget.width(), widget.height()
        if w <= 1 or h <= 1:
            self.hide()
            return
        self.setGeometry(tl.x(), tl.y(), w, h)
        self.set_video_height(h)

    def set_text(self, text):
        text = text or ""
        if text != self._text:
            self._text = text
            self.update()

    def set_image(self, qimg, x=0, y=0):
        """Кадр субтитров от libass (обрезанный QImage) с позицией (x,y) в кадре,
        или None."""
        self._image = qimg
        self._image_pos = (int(x), int(y))
        self.update()

    # Единый API субтитров (совместим с VideoCanvas, см. EditTab._update_subtitle).
    def set_subtitle_image(self, qimg, x=0, y=0):
        self.set_image(qimg, x, y)

    def set_subtitle_text(self, text):
        self.set_image(None)
        self.set_text(text)

    def clear_subtitle(self):
        self._text = ""
        self.set_image(None)

    def subtitle_area_size(self):
        return self.width(), self.height()

    def set_video_height(self, h):
        px = max(15, int(h * 0.052))   # ~5% высоты кадра, как в плеерах
        if px != self._px:
            self._px = px
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        _paint_subtitle(p, self.rect(), self._text, self._px,
                        self._image, self._image_pos)
        p.end()


class VideoCanvas(QWidget):
    """Холст видео: сам рисует кадры (через QVideoSink + QPainter) и накладывает
    субтитры ПРЯМО В КАДР, как VLC. В отличие от QVideoWidget не использует
    нативную RHI-поверхность, поэтому субтитры корректно обрезаются по видео и
    перекрываются любыми панелями/окнами сверху. Кадр вписывается с сохранением
    пропорций (letterbox). Совместим по API субтитров с SubtitleOverlay.

    Чуть дороже QVideoWidget (кадр конвертируется в QImage на ЦП), поэтому в
    настройках можно вернуть старый метод (QVideoWidget + окно-оверлей)."""

    # Кадр пришёл с PTS за границей OUT (см. set_play_bound) — плеер надо ставить
    # на паузу ДО показа этого кадра (защита от проскока правой границы).
    boundaryReached = pyqtSignal()
    # Кадрирование видео завершено кнопкой «Применить»/«Отмена» на холсте (как в
    # «Редактировании фото») — вкладка снимает чек с кнопки «Кадрировать».
    cropApplied = pyqtSignal()
    cropCancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._bound_us = None          # граница OUT (µs) для блокировки кадров
        self._frame_img = None
        self._text = ""
        self._image = None
        self._image_pos = (0, 0)
        self._bg = QColor(C["bg"])
        # Текст-заглушка, когда у файла нет видеоряда (редактируем чистое аудио).
        self._audio_only_msg = ""
        # Зум/панорама превью (Ctrl+колесо приближает, ЛКМ-перетаскивание двигает).
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self._pan_last = None
        # Кадрирование видео — РОВНО как в «Редактировании фото» (InpaintCanvas):
        # рамку с 8 ручками (углы/стороны) и «ручкой-перемещением» правят прямо на
        # холсте, плавающие кнопки «Применить»/«Отмена» всплывают у рамки. При
        # «Обрезать» итоговое видео кадрируется по рамке (и «Сохранить кадр» тоже).
        # Храним нормализованно (QRectF 0..1 от кадра) — не зависит от разрешения
        # (важно для превью-прокси и crop=… через ffmpeg по iw/ih).
        self._crop_mode = False
        self._crop_norm = None          # QRectF 0..1 или None
        self._crop_drag = None          # активная ручка: tl/tr/bl/br/t/b/l/r/move
        self._crop_anchor = None        # позиция мыши (norm) на момент захвата
        self._crop_start_rect = None    # рамка (QRectF) на момент захвата
        self.setMouseTracking(True)
        # Плавающие кнопки «Применить/Отмена» прямо на холсте (как в Photoshop).
        self._crop_apply_btn = make_icon_btn("Применить", icon='fa5s.check', accent=True)
        self._crop_apply_btn.setParent(self)
        self._crop_apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._crop_apply_btn.setToolTip("Применить кадрирование (Enter)")
        self._crop_apply_btn.clicked.connect(self.apply_crop)
        self._crop_cancel_btn = make_icon_btn("Отмена", icon='fa5s.times')
        self._crop_cancel_btn.setParent(self)
        self._crop_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._crop_cancel_btn.setToolTip("Отменить кадрирование (Esc)")
        self._crop_cancel_btn.clicked.connect(self.cancel_crop)
        for _b in (self._crop_apply_btn, self._crop_cancel_btn):
            _b.setVisible(False)

    # ── Кадрирование видео (как в «Редактировании фото») ──────────────────────
    def set_crop_mode(self, on):
        on = bool(on)
        if on == self._crop_mode:
            return
        self._crop_mode = on
        if on:
            # При входе в режим — рамка СРАЗУ на весь кадр (как в InpaintCanvas),
            # если ещё не задана (можно тут же тянуть за ручки). Если рамка уже
            # «вооружена» прошлым применением — продолжаем её правку.
            if self._crop_norm is None:
                self._crop_norm = QRectF(0.0, 0.0, 1.0, 1.0)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setFocus()
        else:
            self._crop_drag = None
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        self._update_crop_buttons()
        self.update()

    def has_crop(self) -> bool:
        return self._crop_norm is not None

    def crop_norm(self):
        """Нормализованная рамка кадрирования (QRectF 0..1) или None. Полный кадр
        (≈ весь экран) трактуем как «без кадрирования»."""
        n = self._crop_norm
        if n is None:
            return None
        if n.width() >= 0.999 and n.height() >= 0.999:
            return None
        return n

    def clear_crop(self):
        if self._crop_norm is not None or self._crop_drag is not None:
            self._crop_norm = None
            self._crop_drag = None
            self._update_crop_buttons()
            self.update()

    def apply_crop(self):
        """«Применить»: фиксируем рамку (её прочитает экспорт/«Сохранить кадр»),
        выходим из режима правки. Полный кадр трактуем как сброс кадрирования."""
        n = self._crop_norm
        if n is not None and n.width() >= 0.999 and n.height() >= 0.999:
            self._crop_norm = None     # рамка = весь кадр → кадрирования нет
        self._crop_mode = False
        self._crop_drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._update_crop_buttons()
        self.update()
        self.cropApplied.emit()

    def cancel_crop(self):
        """«Отмена»: сбрасываем рамку и выходим из режима правки."""
        self._crop_norm = None
        self._crop_mode = False
        self._crop_drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._update_crop_buttons()
        self.update()
        self.cropCancelled.emit()

    def _widget_to_norm(self, wpt, clamp=True):
        vr = self.video_rect()
        if vr.width() <= 0 or vr.height() <= 0:
            return None
        nx = (wpt.x() - vr.left()) / vr.width()
        ny = (wpt.y() - vr.top()) / vr.height()
        if clamp:
            nx = min(1.0, max(0.0, nx)); ny = min(1.0, max(0.0, ny))
        return QPointF(nx, ny)

    def _crop_rect_screen(self):
        """Текущая рамка кадрирования в ЭКРАННЫХ координатах (для ручек/кнопок)."""
        n = self._crop_norm
        vr = self.video_rect()
        if n is None or vr.width() <= 0:
            return QRectF()
        return QRectF(vr.left() + n.left() * vr.width(),
                      vr.top() + n.top() * vr.height(),
                      n.width() * vr.width(), n.height() * vr.height())

    def _crop_handle_at(self, wpt):
        """Какую «ручку» рамки задевает курсор (коорд. виджета): tl/tr/bl/br/t/b/
        l/r/move или None."""
        if not self.has_crop():
            return None
        r = self._crop_rect_screen()
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

    def _drag_crop(self, npt):
        """Двигает активную ручку рамки. npt — позиция мыши в НОРМ. координатах."""
        d = self._crop_drag
        sr = self._crop_start_rect
        if sr is None:
            return
        l, t, r, bo = sr.left(), sr.top(), sr.right(), sr.bottom()
        minsz = 0.02
        if d == 'move':
            bw, bh = r - l, bo - t
            dx = npt.x() - self._crop_anchor.x()
            dy = npt.y() - self._crop_anchor.y()
            nl = min(max(l + dx, 0.0), 1.0 - bw)
            nt = min(max(t + dy, 0.0), 1.0 - bh)
            self._crop_norm = QRectF(nl, nt, bw, bh)
            return
        x = min(max(npt.x(), 0.0), 1.0)
        y = min(max(npt.y(), 0.0), 1.0)
        if 'l' in d: l = min(x, r - minsz)
        if 'r' in d: r = max(x, l + minsz)
        if 't' in d: t = min(y, bo - minsz)
        if 'b' in d: bo = max(y, t + minsz)
        self._crop_norm = QRectF(l, t, r - l, bo - t)

    def _update_crop_buttons(self):
        """Показывает/прячет и позиционирует «Применить/Отмена» у рамки (плавающая
        панель, как в Photoshop). Зовётся при любом изменении рамки/зума/размера."""
        show = (self._crop_mode and self.has_crop()
                and self._frame_img is not None)
        if not show:
            if self._crop_apply_btn.isVisible():
                self._crop_apply_btn.setVisible(False)
                self._crop_cancel_btn.setVisible(False)
            return
        r = self._crop_rect_screen()
        aw = self._crop_apply_btn.sizeHint()
        cw = self._crop_cancel_btn.sizeHint()
        gap = 6
        h = max(aw.height(), cw.height())
        total = aw.width() + cw.width() + gap
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

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_crop_buttons()

    def keyPressEvent(self, ev):
        if self._crop_mode and self.has_crop():
            if ev.key() == Qt.Key.Key_Escape:
                self.cancel_crop(); ev.accept(); return
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.apply_crop(); ev.accept(); return
        super().keyPressEvent(ev)

    def videoSink(self):
        return self._sink

    def setAspectRatioMode(self, *a, **k):   # совместимость с QVideoWidget
        pass

    def clear_frame(self):
        self._frame_img = None
        self.update()

    def set_static_image(self, qimg):
        """Показывает СТАТИЧНУЮ картинку на холсте (режим «картинка → видео»):
        кадр рисуется как обычный видеокадр, но не от плеера, а напрямую. Сбрасывает
        субтитры/зум, чтобы картинка вписалась целиком."""
        self._text = ""
        self._image = None
        self._audio_only_msg = ""
        self._frame_img = qimg if (qimg is not None and not qimg.isNull()) else None
        self.reset_view()
        self.update()

    def current_frame_image(self):
        """Точная копия кадра, который СЕЙЧАС показан на холсте (полное
        разрешение видео, без субтитров — они рисуются отдельно). Нужна для
        «Сохранить кадр»: берём ровно то, что видит пользователь, а не
        пере-извлекаем кадр через ffmpeg по позиции (там seek по HEVC мог
        отдать СЛЕДУЮЩИЙ кадр)."""
        img = self._frame_img
        if img is not None and not img.isNull():
            return img.copy()
        return None

    def set_audio_only_message(self, text):
        """Текст по центру холста, когда видеоряда нет (редактируется аудио).
        Пустая строка — обычный режим (показ кадров)."""
        text = text or ""
        if text == self._audio_only_msg:
            return
        self._audio_only_msg = text
        self.update()

    # ── Зум / панорама ───────────────────────────────────────────────────────
    def reset_view(self):
        """Сброс зума/панорамы (на 100%). Вызывается при загрузке нового файла."""
        changed = (self._zoom != 1.0) or (self._pan != QPoint(0, 0))
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        # Рамку кадрирования сбрасываем, чтобы не переносить её на новый файл
        # (режим кадрирования при этом не выключаем — кнопкой управляет вкладка).
        if self._crop_norm is not None or self._crop_drag is not None:
            self._crop_norm = None
            self._crop_drag = None
            self._update_crop_buttons()
            changed = True
        self.unsetCursor()
        if changed:
            self.update()

    def _base_video_rect(self):
        """Прямоугольник кадра при зуме 100% (letterbox по пропорциям)."""
        w, h = self.width(), self.height()
        img = self._frame_img
        if img is None or w <= 0 or h <= 0 or img.width() <= 0 or img.height() <= 0:
            return QRect(0, 0, max(0, w), max(0, h))
        scale = min(w / img.width(), h / img.height())
        rw = max(1, int(img.width() * scale))
        rh = max(1, int(img.height() * scale))
        return QRect((w - rw) // 2, (h - rh) // 2, rw, rh)

    def _clamp_pan(self):
        """Не даём утащить кадр так, чтобы по краям появился фон (когда кадр
        крупнее окна). По осям, где кадр меньше окна, держим его по центру."""
        base = self._base_video_rect()
        rw = base.width() * self._zoom
        rh = base.height() * self._zoom
        mx = max(0, (rw - self.width()) / 2.0)
        my = max(0, (rh - self.height()) / 2.0)
        x = max(-mx, min(mx, self._pan.x()))
        y = max(-my, min(my, self._pan.y()))
        self._pan = QPoint(int(x), int(y))

    def wheelEvent(self, ev):
        # Зум только с зажатым Ctrl (как в редакторах) и при наличии кадра.
        if (ev.modifiers() & Qt.KeyboardModifier.ControlModifier
                and self._frame_img is not None):
            old = self._zoom
            new = (min(8.0, old * 1.2) if ev.angleDelta().y() > 0
                   else max(1.0, old / 1.2))
            if abs(new - old) < 1e-6:
                ev.accept(); return
            vr = self.video_rect()
            px = ev.position().x(); py = ev.position().y()
            s = new / old
            # Масштабируем текущий прямоугольник относительно точки под курсором,
            # чтобы она оставалась на месте при приближении/отдалении.
            new_left = px - (px - vr.left()) * s
            new_top = py - (py - vr.top()) * s
            new_w = vr.width() * s
            new_h = vr.height() * s
            base = self._base_video_rect()
            self._zoom = new
            if new <= 1.0001:
                self._pan = QPoint(0, 0)
            else:
                cx = new_left + new_w / 2.0
                cy = new_top + new_h / 2.0
                self._pan = QPoint(int(cx - base.center().x()),
                                   int(cy - base.center().y()))
                self._clamp_pan()
            self._update_crop_buttons()   # рамка/кнопки следуют за зумом
            self.update()
            ev.accept()
            return
        super().wheelEvent(ev)

    def mousePressEvent(self, ev):
        if (self._crop_mode and ev.button() == Qt.MouseButton.LeftButton
                and self._frame_img is not None):
            handle = self._crop_handle_at(ev.position())
            if handle is not None:
                # Захватили ручку/тело существующей рамки — тянем её.
                self._crop_drag = handle
                self._crop_anchor = self._widget_to_norm(ev.position(), clamp=False)
                self._crop_start_rect = QRectF(self._crop_norm)
            else:
                # Клик вне рамки — рисуем НОВУЮ рамку от этой точки (тянем угол br).
                n = self._widget_to_norm(ev.position())
                if n is not None:
                    self._crop_norm = QRectF(n.x(), n.y(), 0.0, 0.0)
                    self._crop_drag = 'br'
                    self._crop_anchor = n
                    self._crop_start_rect = QRectF(self._crop_norm)
            self._update_crop_buttons()
            self.update()
            ev.accept()
            return
        if self._zoom > 1.0 and ev.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_last = ev.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._crop_mode and self._frame_img is not None:
            if self._crop_drag and (ev.buttons() & Qt.MouseButton.LeftButton):
                npt = self._widget_to_norm(ev.position(), clamp=False)
                if npt is not None:
                    self._drag_crop(npt)
                    self._update_crop_buttons()
                    self.update()
                ev.accept()
                return
            # Без зажатой кнопки — курсор подсказывает доступную ручку.
            self.setCursor(self._crop_cursor(self._crop_handle_at(ev.position())))
            ev.accept()
            return
        if self._panning and self._pan_last is not None:
            d = ev.position() - self._pan_last
            self._pan_last = ev.position()
            self._pan = QPoint(self._pan.x() + int(d.x()),
                               self._pan.y() + int(d.y()))
            self._clamp_pan()
            self.update()
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if (self._crop_mode and self._crop_drag is not None
                and ev.button() == Qt.MouseButton.LeftButton):
            self._crop_drag = None
            # Совсем крошечная рамка (случайный клик) = весь кадр, чтобы не остаться
            # с пустым выделением (правят дальше ручками или жмут «Применить»).
            n = self._crop_norm
            if n is not None and (n.width() < 0.02 or n.height() < 0.02):
                self._crop_norm = QRectF(0.0, 0.0, 1.0, 1.0)
            else:
                self._crop_norm = QRectF(n).normalized()
            self._update_crop_buttons()
            self.update()
            ev.accept()
            return
        if self._panning and ev.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self.unsetCursor()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def set_play_bound(self, out_seconds):
        """Граница OUT для блокировки кадров при воспроизведении (None — снять)."""
        self._bound_us = (int(out_seconds * 1_000_000)
                          if (out_seconds and out_seconds > 0) else None)

    def _on_frame(self, frame):
        # Граница OUT по PTS кадра — ПРОВЕРЯЕМ ДО конвертации в QImage и показа.
        # Кадр за границей не рисуем и просим плеер на паузу (анти-overshoot).
        if frame is not None and self._bound_us is not None:
            try: pts = frame.startTime()    # µs, -1 если неизвестно
            except Exception: pts = -1
            if pts >= 0 and pts >= self._bound_us:
                self.boundaryReached.emit()
                return
        img = None
        try:
            if frame is not None and frame.isValid():
                img = frame.toImage()
        except Exception:
            img = None
        if img is not None and not img.isNull():
            self._frame_img = img
            if self.isVisible():
                self.update()

    def _paint_crop_overlay(self, p, vr):
        """Затемняет всё вне рамки кадрирования + рисует границу и сетку третей
        (в пределах видимой части кадра). vr — прямоугольник кадра на экране."""
        n = self._crop_norm
        r = QRectF(vr.left() + n.left() * vr.width(),
                   vr.top() + n.top() * vr.height(),
                   n.width() * vr.width(), n.height() * vr.height())
        clip = QRectF(vr).intersected(QRectF(self.rect()))
        r = r.intersected(clip)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRect(QRectF(clip.left(), clip.top(), clip.width(), r.top() - clip.top()))
        p.drawRect(QRectF(clip.left(), r.bottom(), clip.width(), clip.bottom() - r.bottom()))
        p.drawRect(QRectF(clip.left(), r.top(), r.left() - clip.left(), r.height()))
        p.drawRect(QRectF(r.right(), r.top(), clip.right() - r.right(), r.height()))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        for i in (1, 2):
            gx = r.left() + r.width() * i / 3.0
            gy = r.top() + r.height() * i / 3.0
            p.drawLine(QPointF(gx, r.top()), QPointF(gx, r.bottom()))
            p.drawLine(QPointF(r.left(), gy), QPointF(r.right(), gy))
        p.setPen(QPen(QColor("#cdd6f4"), 1.5))
        p.drawRect(r)
        # Ручки по углам и серединам сторон (как в «Редактировании фото»).
        hs = 7.0
        p.setPen(QPen(QColor("#11111b"), 1))
        p.setBrush(QColor("#cdd6f4"))
        cx, cy = (r.left() + r.right()) / 2.0, (r.top() + r.bottom()) / 2.0
        for hx, hy in ((r.left(), r.top()), (r.right(), r.top()),
                       (r.left(), r.bottom()), (r.right(), r.bottom()),
                       (cx, r.top()), (cx, r.bottom()),
                       (r.left(), cy), (r.right(), cy)):
            p.drawRect(QRectF(hx - hs / 2, hy - hs / 2, hs, hs))
        p.restore()

    def _paint_crop_indicator(self, p, vr):
        """Тонкая пунктирная рамка «вооружённого» кадрирования вне режима правки —
        показывает, какую область получит итоговое видео при «Обрезать»."""
        n = self._crop_norm
        r = QRectF(vr.left() + n.left() * vr.width(),
                   vr.top() + n.top() * vr.height(),
                   n.width() * vr.width(), n.height() * vr.height())
        r = r.intersected(QRectF(vr).intersected(QRectF(self.rect())))
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#89b4fa"), 1.5, Qt.PenStyle.DashLine))
        p.drawRect(r)
        p.restore()

    def video_rect(self):
        """Прямоугольник, где реально показан кадр (letterbox + текущий зум/пан)."""
        base = self._base_video_rect()
        if self._frame_img is None or self._zoom == 1.0:
            return base
        rw = max(1, int(base.width() * self._zoom))
        rh = max(1, int(base.height() * self._zoom))
        cx = base.center().x() + self._pan.x()
        cy = base.center().y() + self._pan.y()
        return QRect(int(cx - rw / 2.0), int(cy - rh / 2.0), rw, rh)

    # ── Единый API субтитров (как у SubtitleOverlay) ─────────────────────────
    def subtitle_area_size(self):
        r = self.video_rect()
        return r.width(), r.height()

    def set_subtitle_image(self, qimg, x=0, y=0):
        self._image = qimg
        self._image_pos = (int(x), int(y))
        self.update()

    def set_subtitle_text(self, text):
        text = text or ""
        if self._image is None and text == self._text:
            return
        self._image = None
        self._text = text
        self.update()

    def clear_subtitle(self):
        if self._image is None and not self._text:
            return
        self._image = None
        self._text = ""
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg)
        img = self._frame_img
        if img is not None and not img.isNull():
            vr = self.video_rect()
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(vr, img)
            # Субтитры рисуем в ВИДИМОЙ части кадра (пересечение зумированного vr
            # с областью виджета), а не во всём vr. Иначе при приближении кадра
            # низ vr уходит далеко за нижнюю границу виджета, и субтитры,
            # привязанные к низу кадра, «улетают» за экран (баг с приближением).
            sub_rect = vr.intersected(self.rect())
            if sub_rect.width() < 10 or sub_rect.height() < 10:
                sub_rect = self.rect()
            px = max(15, int(min(sub_rect.height(), self.height()) * 0.052))
            _paint_subtitle(p, sub_rect, self._text, px, self._image, self._image_pos)
            # Рамка кадрирования видео (как в «Редактировании фото»): в режиме
            # правки — затемнение/сетка/ручки, иначе (рамка «вооружена») — тонкая
            # пунктирная подсказка, что экспорт кадрируется по ней.
            if self._crop_mode and self._crop_norm is not None:
                self._paint_crop_overlay(p, vr)
            elif self._crop_norm is not None:
                self._paint_crop_indicator(p, vr)
        elif self._audio_only_msg:
            # Видеоряда нет — рисуем иконку ноты и поясняющий текст по центру.
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            icon_px = max(28, int(min(self.width(), self.height()) * 0.16))
            pm = get_icon_pixmap('fa5s.music', icon_px, C['text3'])
            gap = 14
            font = p.font()
            font.setPointSize(11)
            font.setFamily("Segoe UI" if os.name == 'nt' else "SF Pro Display")
            p.setFont(font)
            fm = QFontMetrics(font)
            text_rect = fm.boundingRect(
                QRect(0, 0, max(60, self.width() - 40), 1000),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
                self._audio_only_msg)
            ih = (icon_px + gap) if (pm is not None and not pm.isNull()) else 0
            total_h = ih + text_rect.height()
            top = (self.height() - total_h) // 2
            if pm is not None and not pm.isNull():
                ix = (self.width() - icon_px) // 2
                p.drawPixmap(QRect(ix, top, icon_px, icon_px), pm)
            p.setPen(QPen(QColor(C['text3'])))
            tr = QRect((self.width() - text_rect.width()) // 2, top + ih,
                       text_rect.width(), text_rect.height())
            p.drawText(tr, int(Qt.AlignmentFlag.AlignHCenter
                               | Qt.TextFlag.TextWordWrap), self._audio_only_msg)
        p.end()


# ─── Полоса воспроизведения с мгновенной перемоткой по клику ────────────────────
class SeekSlider(QSlider):
    """Полоса воспроизведения как в обычных плеерах: клик/перетаскивание мгновенно
    перематывает в точку под курсором (стандартный QSlider лишь «подкрадывается»
    page-step'ами). Пока пользователь держит ползунок, плеер не перебивает его
    значение (см. is_user_seeking)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._seeking = False

    def is_user_seeking(self):
        return self._seeking

    def _value_at(self, x):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self)
        span = (groove.right() - groove.left() - handle.width())
        pos = x - groove.left() - handle.width() // 2
        if span <= 0:
            return self.minimum()
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), pos, span)

    def mousePressEvent(self, ev):
        if (ev.button() == Qt.MouseButton.LeftButton
                and self.orientation() == Qt.Orientation.Horizontal):
            self._seeking = True
            v = self._value_at(int(ev.position().x()))
            self.setValue(v)
            self.sliderMoved.emit(v)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        # Превью обновляем на КАЖДОЕ движение курсора по полосе (а не только при
        # входе) — иначе чтобы увидеть другой кадр, приходилось уводить курсор и
        # наводиться заново.
        try: self._show_preview(ev)
        except Exception: pass
        if (self._seeking
                and self.orientation() == Qt.Orientation.Horizontal):
            v = self._value_at(int(ev.position().x()))
            self.setValue(v)
            self.sliderMoved.emit(v)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._seeking and ev.button() == Qt.MouseButton.LeftButton:
            self._seeking = False
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    # ── Превью кадров при наведении (как на YouTube) ──────────────────────────
    def attach_preview(self, preview):
        """Привязывает общий контроллер превью (SeekPreview). Включает отслеживание
        мыши, чтобы показывать миниатюру кадра под курсором без зажатой кнопки."""
        self._preview = preview
        self.setMouseTracking(True)

    def _show_preview(self, ev):
        pv = getattr(self, "_preview", None)
        if pv is None or self.orientation() != Qt.Orientation.Horizontal:
            return
        x = int(ev.position().x())
        pv.show_at(self, x, self._value_at(x))

    def enterEvent(self, ev):
        # При входе курсора покажем превью сразу (положение возьмём из события).
        try: self._show_preview(ev)
        except Exception: pass
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        pv = getattr(self, "_preview", None)
        if pv is not None:
            try: pv.hide()
            except Exception: pass
        super().leaveEvent(ev)


class _SeekThumbnailer(QThread):
    """Фоновый извлекатель кадров для превью полосы воспроизведения. Держит одну
    «целевую» позицию; пока идёт извлечение, новые запросы лишь обновляют цель
    (промежуточные отбрасываются — на быстром движении мыши не копится очередь)."""
    ready = pyqtSignal(float, object)   # quantized_sec, QImage

    def __init__(self):
        super().__init__()
        self._src = None
        self._pending = None
        self._stop = False
        self._cond = threading.Condition()

    def set_source(self, src):
        with self._cond:
            self._src = str(src) if src else None
            self._pending = None

    def request(self, sec):
        with self._cond:
            self._pending = float(sec)
            self._cond.notify()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify()

    def run(self):
        while True:
            with self._cond:
                while self._pending is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                sec = self._pending; src = self._src
                self._pending = None
            if src is None:
                continue
            img = self._extract(src, sec)
            if img is not None and not img.isNull():
                self.ready.emit(sec, img)

    @staticmethod
    def _extract(src, sec):
        try:
            # Скорость превью важнее точности кадра, поэтому жертвуем качеством:
            #   -noaccurate_seek — прыжок СРАЗУ на ближайший ключевой кадр, без
            #     декодирования от него до точной позиции (главный источник
            #     задержки при наведении);
            #   -probesize/-analyzeduration — короткий анализ входа (не сканируем
            #     весь файл ради одного кадра);
            #   scale=160 + -q:v 8 — мелкий кадр пониженного качества кодируется и
            #     передаётся через pipe быстрее.
            cmd = [FFMPEG, "-nostdin",
                   "-probesize", "2M", "-analyzeduration", "0",
                   "-noaccurate_seek", "-ss", f"{max(0.0, sec):.3f}",
                   "-i", str(src), "-frames:v", "1", "-an", "-sn",
                   "-vf", "scale=160:-2", "-q:v", "8", "-threads", "1",
                   "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
            pr = subprocess.run(cmd, capture_output=True,
                                creationflags=CREATE_NO_WINDOW, timeout=8)
            if pr.returncode == 0 and pr.stdout:
                im = QImage.fromData(pr.stdout, "JPG")
                return im
        except Exception:
            pass
        return None


class SeekPreview:
    """Превью кадра под курсором над полосой воспроизведения (как на YouTube).
    Один экземпляр обслуживает обе полосы — в окне и в полноэкранном режиме.

    Устройство попапа: миниатюра СВЕРХУ, время — отдельным лейблом СНИЗУ (в самой
    картинке цифры не рисуются). Фон попапа прозрачный — никакого серого
    «паспарту»: где нет картинки, остаётся пусто (как превью в проводнике Windows).

    Чтобы не было рывка «сначала цифры, потом кадр»: при переходе на новую
    позицию предыдущая миниатюра остаётся на экране, пока ffmpeg извлекает
    новую; время при этом обновляется мгновенно. Кадры кэшируются."""

    _QUANT = 1.0   # шаг квантования позиции (сек) — ограничивает число кадров

    def __init__(self, get_duration):
        self._get_duration = get_duration
        self._cache = {}
        self._cur_q = None
        self._anchor = None   # (slider, local_x)
        self._popup = QWidget(None, Qt.WindowType.ToolTip
                              | Qt.WindowType.FramelessWindowHint)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self._popup)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._img_lbl = QLabel()
        self._img_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._img_lbl.setStyleSheet("background:transparent;")
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_lbl = QLabel()
        self._time_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_lbl.setStyleSheet(
            "color:#ffffff;background:rgba(11,11,18,0.88);border:1px solid #585b70;"
            "border-radius:5px;padding:2px 10px;font-weight:bold;font-size:13px;")
        lay.addWidget(self._img_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._time_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        self._th = _SeekThumbnailer()
        self._th.ready.connect(self._on_ready)
        self._th.start()

    def set_source(self, src):
        self._cache.clear()
        self._cur_q = None
        self._img_lbl.clear()
        self._img_lbl.setFixedSize(0, 0)
        self._th.set_source(src)
        # Префетч одного кадра, чтобы первое наведение уже имело картинку.
        try:
            dur = float(self._get_duration() or 0.0)
            if dur > 0:
                self._th.request(self._quant(dur / 2.0))
        except Exception:
            pass

    def _quant(self, sec):
        return round(sec / self._QUANT) * self._QUANT

    def show_at(self, slider, local_x, value):
        dur = 0.0
        try: dur = float(self._get_duration() or 0.0)
        except Exception: dur = 0.0
        if dur <= 0:
            self.hide(); return
        sec = max(0.0, min(dur, (value / 1000.0) * dur))
        q = self._quant(sec)
        self._cur_q = q
        self._anchor = (slider, local_x)
        # Время — всегда мгновенно.
        self._time_lbl.setText(self._fmt(sec))
        # Картинку обновляем только из кэша; если её нет — оставляем предыдущую
        # (никаких «сначала цифры, потом кадр») и заказываем извлечение.
        pm = self._cache.get(q)
        if pm is not None and not pm.isNull():
            self._set_image(pm)
        elif q not in self._cache:
            self._th.request(q)
        self._reposition()
        self._popup.show(); self._popup.raise_()

    def _set_image(self, pm):
        self._img_lbl.setFixedSize(pm.width(), pm.height())
        self._img_lbl.setPixmap(pm)

    def _on_ready(self, sec, img):
        try:
            pm = QPixmap.fromImage(img)
            if not pm.isNull():
                self._cache[sec] = pm
                # Если курсор всё ещё на этой позиции — показываем кадр.
                if self._cur_q == sec and self._popup.isVisible() and self._anchor:
                    self._set_image(pm)
                    self._reposition()
        except Exception:
            pass

    def _reposition(self):
        if self._anchor is None:
            return
        slider, local_x = self._anchor
        try:
            self._popup.adjustSize()
            gp = slider.mapToGlobal(QPoint(local_x, 0))
            x = gp.x() - self._popup.width() // 2
            y = gp.y() - self._popup.height() - 10
            scr = slider.screen().availableGeometry()
            if x < scr.left() + 2: x = scr.left() + 2
            if x + self._popup.width() > scr.right(): x = scr.right() - self._popup.width() - 2
            if y < scr.top() + 2:
                y = gp.y() + 18   # не помещается сверху — показываем снизу
            self._popup.move(x, y)
        except Exception:
            pass

    @staticmethod
    def _fmt(sec):
        sec = int(max(0, sec))
        h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

    def hide(self):
        try: self._popup.hide()
        except Exception: pass

    def shutdown(self):
        try: self._th.stop(); self._th.wait(1500)
        except Exception: pass


# ─── Полноэкранное окно видео ──────────────────────────────────────────────────
class FullscreenVideo(QWidget):
    """Отдельное полноэкранное окно для видео вкладки «Монтаж».

    Внизу — панель управления как в обычных видеоплеерах: кнопка play/pause,
    текущее/общее время и полоса воспроизведения. Панель и курсор авто-скрываются
    при бездействии и снова появляются при движении мыши. Esc / F / двойной клик —
    выход из полноэкранного режима."""

    def __init__(self, edit_tab):
        super().__init__()
        self.edit = edit_tab
        self.setWindowTitle("SI-HYX — Полный экран")
        self.setStyleSheet("background:#000;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Видео занимает всё окно; панель управления накладывается поверх снизу.
        # Субтитры рисует общий оверлей EditTab (отдельное окно), он подгоняется
        # под видео этого окна — см. EditTab._position_overlay.
        self._video = None

        # ── Панель управления ────────────────────────────────────────────
        # ВАЖНО: QVideoWidget рисует видео через нативную поверхность и
        # перекрывает обычные дочерние виджеты (та же причина, по которой не было
        # видно субтитров). Поэтому панель — отдельное БЕЗРАМОЧНОЕ окно «поверх
        # всех», но КЛИКАБЕЛЬНОЕ (кнопки/полоса), привязанное к этому окну.
        self.bar = QFrame(self, Qt.WindowType.FramelessWindowHint
                          | Qt.WindowType.Tool
                          | Qt.WindowType.WindowStaysOnTopHint)
        self.bar.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.bar.setObjectName("FsBar")
        self.bar.setStyleSheet(
            "#FsBar { background: rgba(15,15,18,0.88); "
            "border-top: 1px solid rgba(255,255,255,0.10); }"
            # Та же тёмная подсказка, что и во вкладке (см. EditTab.apply_theme) —
            # чтобы штатные tooltip'ы кнопок панели выглядели одинаково.
            f"QToolTip {{ background: {C['surface3']}; color: {C['text']}; "
            f"border: 1px solid {C['border2']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 12px; }}")
        bl = QVBoxLayout(self.bar)
        bl.setContentsMargins(22, 10, 22, 12)
        bl.setSpacing(8)

        # Полоса воспроизведения + тайминги в одной строке (клик по полосе —
        # мгновенная перемотка; SeekSlider это уже умеет).
        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(12)
        _mono = QFont("Courier New" if os.name == 'nt' else "Courier")
        _mono.setBold(True); _mono.setPointSize(12)
        self.lbl_cur = QLabel("00:00:00.000", self.bar)
        self.lbl_cur.setFont(_mono)
        self.lbl_cur.setStyleSheet("color:#a6e3a1; background:transparent;")
        seek_row.addWidget(self.lbl_cur)
        self.slider = SeekSlider(Qt.Orientation.Horizontal, self.bar)
        self.slider.setRange(0, 1000)
        self.slider.setStyleSheet(self._fs_slider_style())
        # Полоса не должна перехватывать фокус — иначе Пробел уходит ей, а не окну.
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        # Тот же контроллер превью кадров, что и у полосы в окне.
        try:
            pv = getattr(self.edit, "seek_preview", None)
            if pv is not None:
                self.slider.attach_preview(pv)
        except Exception:
            pass
        seek_row.addWidget(self.slider, 1)
        self.lbl_tot = QLabel("00:00:00.000", self.bar)
        self.lbl_tot.setFont(_mono)
        self.lbl_tot.setStyleSheet("color:#bac2de; background:transparent;")
        seek_row.addWidget(self.lbl_tot)
        bl.addLayout(seek_row)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        _fsbtn_css = (
            "QPushButton { background: rgba(255,255,255,0.08); border: none;"
            " border-radius: 7px; } "
            "QPushButton:hover { background: rgba(255,255,255,0.18); } "
            "QPushButton:pressed { background: rgba(255,255,255,0.30); }")
        _fsbtn_accent_css = (
            "QPushButton { background: rgba(137,180,250,0.85); border: none;"
            " border-radius: 7px; } "
            "QPushButton:hover { background: rgba(180,190,254,0.95); } "
            "QPushButton:pressed { background: rgba(137,180,250,0.65); }")

        def _fsbtn(icon_std, tip, slot, size=(42, 34), accent=False, icon=None):
            b = QPushButton(self.bar)
            b.setIcon(icon if icon is not None
                      else self.style().standardIcon(icon_std))
            b.setIconSize(QSize(18, 18))
            b.setFixedSize(*size)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            # Подсказка — ШТАТНЫМ механизмом Qt (setToolTip), ровно как у кнопки
            # «Сохранить кадр» на боковой панели. Раньше здесь была самописная
            # подсказка через QToolTip.showText на Enter/Leave (см. eventFilter):
            # она МЕРЦАЛА (повторные show/hide при каждом входе курсора) и рисовала
            # инородную рамку. НЕ ВОЗВРАЩАТЬ — стиль подсказки задаётся через
            # QToolTip в self.bar.setStyleSheet (тёмная тема, как во вкладке).
            b.setToolTip(tip)
            b.setStyleSheet(_fsbtn_accent_css if accent else _fsbtn_css)
            # Кнопки не держат фокус: после клика по «Стоп» Пробел должен идти
            # окну (воспроизведение/пауза), а не повторно жать ту же кнопку.
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        self.btn_stop = _fsbtn(QStyle.StandardPixmap.SP_MediaStop,
                               "Стоп — к началу зоны", self.edit.stop_playback)
        self.btn_step_back = _fsbtn(QStyle.StandardPixmap.SP_MediaSeekBackward,
                                    "Кадр назад (←)",
                                    partial(self.edit.step_frame_scrub, -1))
        self.btn_play = _fsbtn(QStyle.StandardPixmap.SP_MediaPlay,
                               "Воспроизвести / пауза (Пробел)",
                               self.edit.toggle_play, size=(50, 34), accent=True)
        self.btn_step_fwd = _fsbtn(QStyle.StandardPixmap.SP_MediaSeekForward,
                                   "Кадр вперёд (→)",
                                   partial(self.edit.step_frame_scrub, 1))
        self.btn_jump_end = _fsbtn(QStyle.StandardPixmap.SP_MediaSkipForward,
                                   "Перейти к концу зоны (OUT)",
                                   lambda: self.edit.seek_to(self.edit.current_out))

        row.addSpacing(10)
        self.btn_save_frame = _fsbtn(None,
                                     "Сохранить текущий кадр в PNG",
                                     self.edit.save_frame,
                                     icon=get_icon('fa5s.save', color='#ffffff'))

        row.addStretch(1)

        # Громкость — связана с основным ползунком вкладки (он управляет звуком).
        self.vol_lbl = VolumeLabel(lambda: getattr(self, "vol_slider", None), self.bar)
        self.vol_lbl.setStyleSheet("color:#cdd6f4; font-size:15px; background:transparent;")
        row.addWidget(self.vol_lbl)
        self.vol_slider = VolumeSlider(Qt.Orientation.Horizontal, self.bar)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(self.edit.vol_slider.value()))
        self.vol_slider.setFixedWidth(120)
        # Прозрачный жёлоб (а не тёмный surface3) и белый бегунок без чёрной
        # окантовки — чтобы за ползунком громкости не было чёрного прямоугольника.
        self.vol_slider.setStyleSheet(
            "QSlider { background: transparent; }"
            "QSlider::groove:horizontal { background: rgba(255,255,255,0.22);"
            " height: 6px; border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: #cdd6f4; border-radius: 3px; }"
            "QSlider::add-page:horizontal { background: rgba(255,255,255,0.22);"
            " border-radius: 3px; }"
            "QSlider::handle:horizontal { background: #ffffff; width: 13px;"
            " height: 13px; margin: -4px 0; border-radius: 7px; }")
        self.vol_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        row.addWidget(self.vol_slider)

        row.addSpacing(10)
        self.btn_exit = _fsbtn(QStyle.StandardPixmap.SP_TitleBarNormalButton,
                               "Выйти из полноэкранного режима (Esc)",
                               self.edit.exit_fullscreen,
                               icon=_fullscreen_icon(expand=False))

        bl.addLayout(row)

        # Авто-скрытие панели/курсора при бездействии.
        self._hide_timer = QTimer(self)
        self._hide_timer.setInterval(2500)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_bar)
        # Клавиши (Esc/пробел/стрелки), пойманные окном панели, шлём в это окно.
        self.bar.installEventFilter(self)

    @staticmethod
    def _fs_slider_style():
        """Полоса воспроизведения для полноэкранного режима: высокий жёлоб с
        закруглёнными концами, видимая заполненная часть и заметный бегунок."""
        ph = C["playhead"]
        return f"""
            QSlider {{ min-height: 18px; background: transparent; }}
            QSlider::groove:horizontal {{
                background: rgba(255,255,255,0.22);
                border-radius: 4px;
                height: 8px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ph};
                border-radius: 4px;
            }}
            QSlider::add-page:horizontal {{
                background: rgba(255,255,255,0.22);
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: #ffffff;
                border: 2px solid {ph};
                width: 16px; height: 16px;
                margin: -5px 0;
                border-radius: 9px;
            }}
            QSlider::handle:horizontal:hover {{ background: {ph}; }}
        """

    # ── Видео ──────────────────────────────────────────────────────────────
    def attach_video(self, video_widget):
        self._video = video_widget
        video_widget.setParent(self)
        video_widget.show()
        self._relayout()
        self._show_bar()

    def _relayout(self):
        if self._video is not None:
            self._video.setGeometry(0, 0, self.width(), self.height())
        # Субтитры рисует общий оверлей EditTab — переподгоняем под это окно.
        try:
            self.edit._position_overlay()
        except Exception:
            pass
        # Панель — отдельное окно: позиционируем в ГЛОБАЛЬНЫХ координатах внизу.
        bar_h = max(64, self.bar.sizeHint().height())
        tl = self.mapToGlobal(QPoint(0, self.height() - bar_h))
        self.bar.setGeometry(tl.x(), tl.y(), self.width(), bar_h)
        if self.bar.isVisible():
            self.bar.raise_()   # поверх оверлея субтитров

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    # ── Синхронизация со плеером ─────────────────────────────────────────────
    def sync_from_player(self):
        e = self.edit
        dur = e.duration or 0.0
        pos_s = e.player.position() / 1000.0
        self.lbl_cur.setText(s_to_time(pos_s))
        self.lbl_tot.setText(s_to_time(dur))
        if dur > 0 and not self.slider.is_user_seeking():
            # Плеер авто-паузится за кадр до конца, поэтому у самого конца
            # «дотягиваем» полосу до 100%, чтобы она доходила до края.
            frac = 1.0 if pos_s >= (dur - 0.08) else (pos_s / dur)
            self.slider.blockSignals(True)
            self.slider.setValue(int(frac * 1000))
            self.slider.blockSignals(False)

    def update_play_icon(self, playing):
        ic = QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay
        self.btn_play.setIcon(self.style().standardIcon(ic))

    def _on_slider_moved(self, value):
        dur = self.edit.duration or 0.0
        if dur > 0:
            self.edit.seek_to((value / 1000.0) * dur)
        self._show_bar()

    def _on_volume_changed(self, v):
        # Звуком управляет основной ползунок вкладки — отражаем туда значение
        # (он применит его к audio_output и обновит свой значок).
        try:
            self.edit.vol_slider.setValue(int(v))
        except Exception:
            pass
        try:
            self.vol_lbl.update_glyph(int(v))
        except Exception:
            pass
        self._show_bar()

    def sync_volume(self):
        """Подтягивает текущую громкость из основного ползунка вкладки."""
        try:
            v = int(self.edit.vol_slider.value())
            self.vol_slider.blockSignals(True)
            self.vol_slider.setValue(v)
            self.vol_slider.blockSignals(False)
            self.vol_lbl.update_glyph(v)
        except Exception:
            pass

    # ── Авто-скрытие панели/курсора ──────────────────────────────────────────
    def _show_bar(self):
        self._relayout()
        self.bar.show(); self.bar.raise_()
        self.unsetCursor()
        self._hide_timer.start()

    def _hide_bar(self):
        # Не прячем, пока курсор над самой панелью (пользователь ей пользуется).
        # geometry() панели теперь в глобальных координатах (отдельное окно).
        if self.bar.geometry().contains(self.cursor().pos()):
            self._hide_timer.start()
            return
        self.bar.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)

    def mouseMoveEvent(self, ev):
        self._show_bar()
        super().mouseMoveEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        self.edit.exit_fullscreen()

    def eventFilter(self, obj, ev):
        # Esc/стрелки, нажатые когда активно окно панели, перенаправляем сюда.
        if obj is self.bar and ev.type() == QEvent.Type.KeyPress:
            self.keyPressEvent(ev)
            if ev.isAccepted():
                return True
        # ЗАПРЕЩЕНО: показывать подсказки кнопок через QToolTip.showText на
        # Enter/Leave. Этот самописный механизм МЕРЦАЛ и рисовал инородную рамку.
        # Подсказки кнопок теперь штатные (b.setToolTip в _fsbtn) — как у кнопки
        # «Сохранить кадр» вне полноэкранного режима. Не возвращать сюда tip-логику.
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_F):
            self.edit.exit_fullscreen()
        elif k == Qt.Key.Key_Space:
            self.edit.toggle_play()
        elif k == Qt.Key.Key_Left:
            self.edit.step_frame_scrub(-1)
        elif k == Qt.Key.Key_Right:
            self.edit.step_frame_scrub(1)
        else:
            super().keyPressEvent(ev)

    def closeEvent(self, ev):
        # Панель — отдельное окно: прячем явно, чтобы не зависла на экране.
        try: self.bar.hide()
        except Exception: pass
        # Если окно закрыли системно (Alt+F4) — аккуратно вернём видео обратно.
        if getattr(self.edit, "_fs_window", None) is self:
            self.edit.exit_fullscreen()
        super().closeEvent(ev)


class SubtitleEditDialog(QDialog):
    """Простой редактор субтитров в формате SRT. Сохранение НЕ трогает оригинал —
    EditTab записывает результат в отдельный .srt и делает его активной дорожкой,
    так что и превью, и вшивание при обрезке используют отредактированный текст."""

    def __init__(self, srt_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование субтитров")
        self.resize(660, 540)
        self.setStyleSheet(f"""
            QDialog {{ background: {C['bg']}; }}
            QLabel {{ color: {C['text2']}; font-size: 12px; }}
            QPlainTextEdit {{
                background: {C['surface3']}; color: {C['text']};
                border: 1px solid {C['border2']}; border-radius: 6px;
                padding: 6px; selection-background-color: {C['accent']};
            }}
            QPushButton {{
                background: {C['surface3']}; color: {C['text']};
                border: 1px solid {C['border2']}; border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background: {C['border2']}; border-color: {C['accent']}; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(8)
        info = QLabel(
            "Формат SRT: номер реплики, строка тайм-кода "
            "«00:00:01,000 --> 00:00:03,000», затем текст; реплики разделяются "
            "пустой строкой. Оригинальный файл не изменяется.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(srt_text)
        mono = QFont("Consolas" if os.name == 'nt' else "Monospace")
        mono.setPointSize(10)
        self.editor.setFont(mono)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        lay.addWidget(self.editor, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def text(self):
        return self.editor.toPlainText()


# Минимальный размер блока для ПРЕДпоследнего (последнего «блочного») шага.
# Раньше геометрия шла до 1px, и предпоследний шаг выходил ~2px — а 2px визуально
# почти неотличим от чёткого кадра, шаг получался «пустым». Держим пол в 6px:
# последний блочный шаг всегда заметно пикселизирован, потом сразу «чётко».
_PIXELIZE_MIN_BLOCK = 6


def _pixelize_block_sequence(block0, steps):
    """Размеры блока (px) по шагам проявления: геометрически убывают от block0 до
    пола (_PIXELIZE_MIN_BLOCK), а самый последний шаг — «чётко» (1). Каждый
    следующий блок мельче → «пикселей становится больше», пока кадр не прояснится.
    При steps==1 — один статичный уровень (block0) без финального прояснения.
    Предпоследний шаг не опускается ниже пола (5px), чтобы не было «пустого» 2px-
    шага у самой чёткости."""
    block0 = max(2, int(block0)); steps = max(1, int(steps))
    if steps == 1:
        return [max(1, min(1024, block0))]
    floor = min(block0, _PIXELIZE_MIN_BLOCK)   # пол не выше самого block0
    n_block = steps - 1                        # шаги до финального «чётко»
    seq = []
    for i in range(n_block):
        if n_block == 1:
            b = block0
        else:
            # i=0 → block0, i=n_block-1 → floor (геометрически между ними).
            t = i / (n_block - 1)
            b = block0 * (floor / block0) ** t
        seq.append(max(1, min(1024, int(round(b)))))
    seq.append(1)                              # финальный шаг — чётко
    return seq


class _PixelizeDialog(QDialog):
    """Настройка эффекта «проявление из пикселей»: число шагов и стартовый размер
    блока. Превью показывает, как блок мельчает по шагам до чёткой картинки."""

    def __init__(self, steps=6, block=64, parent=None,
                 image_mode=False, duration=5.0, fps=25):
        super().__init__(parent)
        self._image_mode = bool(image_mode)
        self.setWindowTitle("Пикселизация — проявление")
        self.setStyleSheet(f"""
            QDialog {{ background: {C['bg']}; }}
            QLabel {{ color: {C['text2']}; font-size: 12px; }}
            QSpinBox {{
                background: {C['surface3']}; color: {C['text']};
                border: 1px solid {C['border2']}; border-radius: 6px;
                padding: 5px 8px; font-size: 13px; min-width: 64px;
            }}
            QSpinBox:focus {{ border-color: {C['accent']}; }}
            QPushButton {{
                background: {C['surface3']}; color: {C['text']};
                border: 1px solid {C['border2']}; border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background: {C['border2']}; border-color: {C['accent']}; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12); lay.setSpacing(10)
        if self._image_mode:
            info = QLabel(
                "Из картинки получится ВИДЕО: кадр начнётся крупными «пикселями» и за "
                "несколько шагов прояснится. Задай длительность ролика и параметры "
                "проявления. Готовое видео сохранится кнопкой «Обрезать».")
        else:
            info = QLabel(
                "Видео начнётся крупными «пикселями» и с каждым шагом будет становиться "
                "чётче, пока не прояснится полностью. Идеально для угадайки. Эффект "
                "применяется при «Обрезать» и требует перекодировки.")
        info.setWordWrap(True); lay.addWidget(info)

        # Для картинки нужна длительность результата (у изображения её нет) и FPS.
        self.sp_dur = None; self.sp_fps = None
        if self._image_mode:
            rowd = QHBoxLayout(); rowd.setSpacing(8)
            rowd.addWidget(QLabel("Длительность видео, сек"))
            self.sp_dur = QSpinBox(); self.sp_dur.setRange(1, 120)
            self.sp_dur.setValue(max(1, int(round(float(duration)))))
            rowd.addStretch(1); rowd.addWidget(self.sp_dur)
            lay.addLayout(rowd)

            rowf = QHBoxLayout(); rowf.setSpacing(8)
            rowf.addWidget(QLabel("Кадров в секунду (FPS)"))
            self.sp_fps = QSpinBox(); self.sp_fps.setRange(1, 60)
            self.sp_fps.setValue(max(1, int(fps)))
            rowf.addStretch(1); rowf.addWidget(self.sp_fps)
            lay.addLayout(rowf)

        row1 = QHBoxLayout(); row1.setSpacing(8)
        row1.addWidget(QLabel("Число шагов проявления"))
        self.sp_steps = QSpinBox(); self.sp_steps.setRange(1, 20); self.sp_steps.setValue(int(steps))
        row1.addStretch(1); row1.addWidget(self.sp_steps)
        lay.addLayout(row1)

        row2 = QHBoxLayout(); row2.setSpacing(8)
        row2.addWidget(QLabel("Начальный размер блока, px"))
        self.sp_block = QSpinBox(); self.sp_block.setRange(4, 256)
        self.sp_block.setSingleStep(4); self.sp_block.setValue(int(block))
        row2.addStretch(1); row2.addWidget(self.sp_block)
        lay.addLayout(row2)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        lay.addWidget(self.preview)

        self.sp_steps.valueChanged.connect(self._update_preview)
        self.sp_block.valueChanged.connect(self._update_preview)
        self._update_preview()

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _update_preview(self):
        seq = _pixelize_block_sequence(self.sp_block.value(), self.sp_steps.value())
        parts = [f"{b}px" if b > 1 else "чётко" for b in seq]
        self.preview.setText("Блоки по шагам:   " + "   →   ".join(parts))

    def values(self):
        return int(self.sp_steps.value()), int(self.sp_block.value())

    def image_values(self):
        """Длительность (сек) и FPS — только в режиме картинки."""
        dur = int(self.sp_dur.value()) if self.sp_dur is not None else 5
        fps = int(self.sp_fps.value()) if self.sp_fps is not None else 25
        return dur, fps


# ─── Edit Tab ─────────────────────────────────────────────────────────────────
class EditTab(QWidget):
    # Боковая панель монтажа: кнопки масштабируются под ровно столько значков в высоту.
    _MSIDE_COUNT = 8
    _MSIDE_GAP = 6

    def __init__(self, main_window=None):
        super().__init__()
        self.main = main_window
        self._ready = False

        if not _HAS_MULTIMEDIA:
            self._build_unavailable_ui()
            return

        self.filepath = None
        self.actual_source_file = None
        self.is_proxy_active = False
        self._source_is_av1 = False
        self._pending_pb_seek = None   # (pos_ms, was_playing) для swap источника
        self._pb_restore = None
        self.duration = 0.0
        self.current_in = 0.0
        self.current_out = 0.0
        self.fps = None
        self.video_aspect = None          # ширина/высота кадра (для точного 16:9-бокса)
        self.video_stream_index = None
        self.audio_stream_index = None
        # Режим «картинка → видео-проявление»: монтаж загрузил still-картинку
        # (png/jpg/…), плеер/обрезка не применимы, активна только пикселизация
        # (и кадрирование). Экспорт собирает видео из картинки через -loop 1.
        self.is_still_image = False
        self.still_image_path = None
        self._still_w = 0; self._still_h = 0
        self._still_duration = 5.0
        self._still_fps = 25
        self.tmp_proxy_file = None
        # Дорожки контейнера (заполняются из ffprobe при загрузке файла)
        self._audio_streams = []
        self._sub_streams = []
        # Внешние дорожки (отдельные файлы рядом с видео / выбранные кнопкой
        # «найти»). _*_ext — список путей; _*_entries — карта пунктов комбобокса
        # на источник: ('emb', i) встроенная дорожка | ('ext', path) внешний файл.
        self._audio_ext = []
        self._sub_ext = []
        self._audio_entries = []
        self._sub_entries = []
        # Внешняя озвучка: отдельный аудиоплеер, синхронный с основным (звук видео
        # при этом глушится). Создаётся лениво при первом выборе внешнего аудио.
        self._ext_audio_player = None
        self._ext_audio_output = None
        self._ext_audio_active = False
        self.selected_audio_abs_index = None   # абсолютный индекс выбранной аудиодорожки (для экспорта)
        self.selected_audio_ext_path = None    # путь к выбранной внешней озвучке (для экспорта)
        self.selected_sub_ext_path = None      # путь к выбранному внешнему файлу субтитров
        self._loading_tracks = False
        # Субтитры в превью: для текстовых дорожек рисуем свой VLC-стиль оверлеем
        # (QtMultimedia рисует их с плашкой и стиль не настраивается). Битмап-
        # дорожки (PGS/DVD) показываем встроенным рендером.
        self._sub_cues = []
        self._sub_extractor = None
        self._sub_threads = []        # живые QThread'ы извлечения (чтобы не собрал GC)
        self._sub_token = 0           # защита от устаревших результатов извлечения
        self._sub_use_overlay = False
        self.sub_overlay = None       # окно-оверлей субтитров (ленивое)
        self._overlay_win = None      # верхнеуровневое окно, на чьи Move/Resize реагируем
        # ASS/SSA в превью: рендер через libass на оверлей (полный стиль + караоке).
        self._sub_use_ass = False
        self._ass = None              # libass_renderer.AssRenderer (ленивый)
        self._ass_extractor = None
        self._ass_path = None         # временный .ass-файл (удаляем при смене)
        self._ass_timer = None        # таймер перерисовки караоке во время игры
        # Флаг «скраб кадрами»: во время покадрового шага плеер кратко play→pause,
        # чтобы отрисовать кадр; кнопку play/pause при этом НЕ переключаем (иначе
        # она дёргается). См. step_frame_scrub / on_playback_changed.
        self._scrubbing = False
        self._scrub_target = None     # последняя цель покадрового шага (мс)
        # Флаг «прогрев аудио»: после СТОП беззвучно поднимаем аудио-декодер в
        # точке IN, чтобы следующее воспроизведение стартовало без задержки звука
        # (см. _preroll_at / stop_playback). Кнопку/иконку при этом не трогаем.
        self._prerolling = False
        self._preroll_prev_muted = False
        # Скраб-звук: при покадровом шаге (WASD/стрелки) играем короткий звуковой
        # блип в новой позиции — как в Filmora. В painted-режиме основной плеер
        # кадр доставляет setPosition'ом БЕЗ play() (иначе мерцает), поэтому звука
        # не было; даём его ОТДЕЛЬНЫМ лёгким аудиоплеером по оригиналу файла, не
        # трогая видео. Включается/выключается в Настройках → «Монтаж».
        self._scrub_audio_enabled = True
        self._scrub_audio_player = None
        self._scrub_audio_output = None
        self._scrub_audio_dev = None
        self._scrub_audio_src = None
        self._scrub_blip_timer = None
        self._scrub_blip_player = None
        # Папка экспорта обрезки ("" = рядом с исходником)
        self.export_dir = ""
        self.undo_stack: deque = deque(maxlen=50)
        self.redo_stack: deque = deque(maxlen=50)

        # Настраиваемые сочетания обрезки до точки воспроизведения (Монтаж →
        # Настройки). Применяются в register_shortcuts / set_trim_shortcuts.
        self.trim_start_seq = "Shift+C"   # обрезать СТАРТ (IN) до плейхеда
        self.trim_end_seq   = "Shift+V"   # обрезать КОНЕЦ (OUT) до плейхеда

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        # Метод субтитров: True (по умолчанию) — рендер ПРЯМО В КАДР (VideoCanvas,
        # как в VLC: субтитры обрезаются по видео и перекрываются окнами сверху);
        # False — старый метод (QVideoWidget + отдельное окно-оверлей). Значение
        # читаем из настроек редактора ДО создания виджета видео.
        self._subs_in_frame = self._read_subs_in_frame_pref()
        self.video_widget = None
        self._build_video_output()
        # Переключение активных дорожек применяем, когда плеер их обнаружит.
        try:
            self.player.tracksChanged.connect(self._apply_active_tracks)
        except Exception:
            pass

        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(80)
        self.sync_timer.timeout.connect(self.sync_ui)

        self.ffmpeg_thread = None
        self.proxy_thread = None
        self.audio_worker = None

        self.init_ui()
        self.apply_theme()
        self.register_shortcuts()

        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_player_duration_changed)
        self.player.playbackStateChanged.connect(self.on_playback_changed)
        # Конец воспроизведения: не оставляем чёрный кадр (QtMultimedia гасит
        # поверхность на EndOfMedia) — см. on_media_status_changed.
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)

        self.setAcceptDrops(True)
        self.enable_global_drag_drop()
        self.load_settings()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._ready = True

    def _build_unavailable_ui(self):
        lay = QVBoxLayout(self)
        lbl = QLabel(
            "Модуль мультимедиа PyQt6 недоступен.\n\n"
            "Видеоредактор требует QtMultimedia. Установите PyQt6 с поддержкой "
            "мультимедиа, чтобы пользоваться вкладкой «Монтаж».")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#a6adc8; font-size:13px;")
        lay.addStretch()
        lay.addWidget(lbl)
        lay.addStretch()

    # ── UI Construction ────────────────────────────────────────────────────
    def init_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Right sidebar (прокручиваемая) ────────────────────────────────
        # Содержимое (инфо/экспорт) живёт в QScrollArea — если по высоте не
        # умещается, появляется вертикальный скроллбар. Кнопки «Итог» и
        # «Обрезать» закреплены ВНЕ прокрутки, снизу (всегда видны).
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(264)
        sidebar.setStyleSheet(f"""
            #Sidebar {{
                background: {C['surface']};
                border-left: 1px solid {C['border']};
            }}
        """)
        sb_outer = QVBoxLayout(sidebar)
        sb_outer.setContentsMargins(0, 0, 0, 0)
        sb_outer.setSpacing(0)

        sb_scroll = QScrollArea()
        sb_scroll.setObjectName("SidebarScroll")
        sb_scroll.setWidgetResizable(True)
        sb_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Никакого собственного стиля скроллбара — берём общий стиль приложения
        # (config.STYLESHEET), чтобы он совпадал со скроллбарами других вкладок.
        # Фон не задаём (глобальное правило делает контент прозрачным → виден
        # surface самого сайдбара; собственный фон давал серую «подложку»).
        sb_scroll.setStyleSheet("QScrollArea#SidebarScroll { border: none; }")
        sb_content = QWidget()
        sb_layout = QVBoxLayout(sb_content)
        # Правый отступ 14px — «дорожка» для вертикального скроллбара, чтобы он не
        # перекрывал содержимое (панель всегда видна полностью).
        sb_layout.setContentsMargins(16, 16, 14, 16)
        sb_layout.setSpacing(12)

        # File section
        self.lbl_file = QLabel("Нет файла")
        self.lbl_file.setWordWrap(True)
        self.lbl_file.setStyleSheet(f"""
            color: {C['text3']};
            font-size: 11px;
            padding: 8px;
            background: {C['surface2']};
            border: 1px dashed {C['border2']};
            border-radius: 6px;
        """)
        self.lbl_file.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb_layout.addWidget(self.lbl_file)

        # Кнопки работы с файлом в одну строку: «Открыть» занимает половину
        # ширины, рядом — «Очистить» (убирает текущий файл и сбрасывает редактор).
        file_btn_row = QHBoxLayout()
        file_btn_row.setSpacing(8)
        btn_open = make_icon_btn("Открыть", accent=True, icon='fa5s.folder-open')
        self._relax_width(btn_open)  # не заставляем панель расширяться под текст
        btn_open.clicked.connect(self.open_file)
        btn_clear = make_icon_btn("Очистить", icon='fa5s.trash')
        self._relax_width(btn_clear)
        btn_clear.setToolTip("Убрать текущий файл и очистить редактор")
        btn_clear.clicked.connect(self.clear_file)
        file_btn_row.addWidget(btn_open, 1)
        file_btn_row.addWidget(btn_clear, 1)
        sb_layout.addLayout(file_btn_row)

        sb_layout.addWidget(make_divider())

        # Media info card
        info_card = InfoCard("МЕДИА ИНФОРМАЦИЯ")
        self.lbl_duration = info_card.add_row("Длительность", "lbl_duration")
        self.lbl_fps      = info_card.add_row("FPS",          "lbl_fps")
        self.lbl_vstream  = info_card.add_row("Видео",        "lbl_vstream")
        self.lbl_astream  = info_card.add_row("Аудио",        "lbl_astream")
        self.lbl_abitrate = info_card.add_row("Битрейт аудио", "lbl_abitrate")
        sb_layout.addWidget(info_card)

        sb_layout.addWidget(make_divider())

        # Export settings card
        export_card = InfoCard("НАСТРОЙКИ ЭКСПОРТА")

        mode_lbl = QLabel("Режим обрезки")
        mode_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        export_card._body.addWidget(mode_lbl)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([
            "Быстро (без потерь)",
            "Перекодировать",
            "Только аудио (MP3)",
            "Smart Cut (умная)",
        ])
        # По умолчанию — «Перекодировать» (кадрово точная обрезка).
        self.cmb_mode.setCurrentIndex(1)
        self.cmb_mode.setToolTip(
            "Быстро — copy без перекодировки (начало прилипает к ключевому кадру).\n"
            "Перекодировать — кадрово точно, но медленно и с потерями.\n"
            "Smart Cut — точные границы реза перекодируются, середина копируется "
            "без потерь (быстро и с сохранением качества).")
        # Не даём комбобоксу диктовать ширину панели по длине пункта (иначе панель
        # переполняется и обрезается). Закрытый комбо подстраивается под N символов,
        # полный текст пунктов виден в выпадающем списке.
        self.cmb_mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_mode.setMinimumContentsLength(8)
        self._relax_width(self.cmb_mode)
        self.cmb_mode.setStyleSheet(f"""
            QComboBox {{
                background: {C['surface3']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {C['surface3']};
                color: {C['text']};
                selection-background-color: {C['accent']};
                border: 1px solid {C['border2']};
            }}
        """)
        export_card._body.addWidget(self.cmb_mode)

        # Кодировщик для перекодировки (режим «Перекодировать» и границы Smart Cut):
        # CPU (libx264) — лучшее качество/совместимость; GPU — быстрее, грузит
        # видеокарту. На «Быстро (без потерь)» не влияет (там copy без кодека).
        enc_lbl = QLabel("Кодировщик (перекодировка)")
        enc_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        export_card._body.addWidget(enc_lbl)

        self.cmb_encoder = QComboBox()
        self.cmb_encoder.addItems([
            "Авто",
            "Процессор (CPU)",
            "Видеокарта (GPU)",
        ])
        self.cmb_encoder.setToolTip(
            "Чем перекодировать видео при обрезке с перекодировкой и на границах "
            "Smart Cut.\n"
            "Процессор (CPU) — libx264, лучшее качество и совместимость, медленнее.\n"
            "Видеокарта (GPU) — аппаратный кодек (NVENC/QSV/AMF), быстрее, "
            "нагружает видеокарту.\n"
            "Если выбранного варианта нет в сборке — автоматический откат.")
        self.cmb_encoder.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_encoder.setMinimumContentsLength(8)
        self._relax_width(self.cmb_encoder)
        self.cmb_encoder.setStyleSheet(self.cmb_mode.styleSheet())
        export_card._body.addWidget(self.cmb_encoder)

        self.chk_overwrite = QCheckBox("Перезаписать файл")
        self.chk_overwrite.setChecked(True)
        self._relax_width(self.chk_overwrite)
        self.chk_overwrite.setStyleSheet(f"""
            QCheckBox {{
                color: {C['text2']};
                font-size: 12px;
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 15px; height: 15px;
                border: 1px solid {C['border2']};
                border-radius: 3px;
                background: {C['surface3']};
            }}
            QCheckBox::indicator:checked {{
                background: {C['accent']};
                border-color: {C['accent']};
            }}
        """)
        export_card._body.addWidget(self.chk_overwrite)

        # Вшивание (hardsub) выбранных субтитров прямо в картинку. ВНИМАНИЕ:
        # это всегда требует ПЕРЕКОДИРОВКИ видео (пиксели субтитров рисуются на
        # кадрах) — без перекодировки можно лишь встроить субтитры отдельной
        # дорожкой, но не «вжечь» в изображение. Сам чекбокс размещаем НЕ здесь,
        # а в правой панели рядом с кнопками «Сохранить кадр»/«Удалить исходник»
        # (см. сборку side-панели ниже) — создаём заранее, добавим туда.
        self.chk_burn_subs = QCheckBox("Вшить субтитры")
        self.chk_burn_subs.setChecked(False)
        self._relax_width(self.chk_burn_subs)
        self.chk_burn_subs.setToolTip(
            "Жёстко впечатывает выбранную дорожку субтитров в кадр.\n"
            "Требует перекодировки видео (режим обрезки будет проигнорирован).\n"
            "Субтитры выбираются в панели справа от видео.")
        self.chk_burn_subs.setStyleSheet(self.chk_overwrite.styleSheet())

        # Папка сохранения результата ("" = рядом с исходником)
        dst_lbl = QLabel("Папка сохранения")
        dst_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        self._relax_width(dst_lbl)
        export_card._body.addWidget(dst_lbl)
        self.lbl_export_dir = QLabel("Рядом с исходником")
        # Без переноса (длинный путь не разрывается и распирал бы панель) — вместо
        # этого укорачиваем в середине в _update_export_dir_label; min width 0,
        # чтобы метка не диктовала ширину панели.
        self.lbl_export_dir.setWordWrap(False)
        self.lbl_export_dir.setMinimumWidth(0)
        self._relax_width(self.lbl_export_dir)
        self.lbl_export_dir.setStyleSheet(
            f"color: {C['text2']}; font-size: 11px; padding: 4px 6px; "
            f"background: {C['surface3']}; border: 1px solid {C['border2']}; border-radius: 5px;")
        export_card._body.addWidget(self.lbl_export_dir)
        dst_row = QHBoxLayout(); dst_row.setSpacing(6)
        btn_dst = make_icon_btn("Выбрать", icon='fa5s.folder')
        self._relax_width(btn_dst)
        btn_dst.clicked.connect(self._choose_export_dir)
        btn_dst_reset = make_icon_btn("", icon='fa5s.undo')
        # Узкая квадратная кнопка: убираем боковой паддинг make_icon_btn,
        # фиксируем размер.
        btn_dst_reset.setStyleSheet(btn_dst_reset.styleSheet()
                                    + "\nQPushButton { padding: 5px 0; }")
        btn_dst_reset.setFixedSize(34, 32)
        btn_dst_reset.setToolTip("Сбросить — сохранять рядом с исходником")
        btn_dst_reset.clicked.connect(self._reset_export_dir)
        dst_row.addWidget(btn_dst, 1); dst_row.addWidget(btn_dst_reset, 0)
        export_card._body.addLayout(dst_row)

        sb_layout.addWidget(export_card)

        # ── Качество воспроизведения (как в Filmora) ──────────────────────────
        # Понижает разрешение ТОЛЬКО предпросмотра (через прокси), чтобы плеер и
        # перемотка работали шустрее на слабом железе/тяжёлых файлах. На экспорт
        # не влияет — он всегда из оригинала.
        pbq_card = InfoCard("ВОСПРОИЗВЕДЕНИЕ")
        pbq_lbl = QLabel("Качество воспроизведения")
        pbq_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        self.cmb_pb_quality = QComboBox()
        self.cmb_pb_quality.addItems([
            "Полное качество",
            "1/2 — быстрее",
            "1/4 — ещё быстрее",
        ])
        self.cmb_pb_quality.setToolTip(
            "Качество предпросмотра (не влияет на экспорт).\n"
            "Полное — играет оригинал.\n"
            "1/2 и 1/4 — плеер показывает уменьшенную копию (прокси): "
            "воспроизведение и перемотка работают быстрее на тяжёлых файлах.")
        self.cmb_pb_quality.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_pb_quality.setMinimumContentsLength(8)
        self._relax_width(self.cmb_pb_quality)
        self.cmb_pb_quality.setStyleSheet(self.cmb_mode.styleSheet())
        self.cmb_pb_quality.currentIndexChanged.connect(self._on_pb_quality_changed)
        pbq_card._body.addWidget(pbq_lbl)
        pbq_card._body.addWidget(self.cmb_pb_quality)

        # ── Прокси только для части файла ─────────────────────────────────────
        # Сколько МИНУТ исходника превращать в прокси (0 = весь файл). Усечённый
        # прокси собирается быстрее на длинных/тяжёлых видео; предпросмотр тогда
        # ограничен этим отрезком, на экспорт/обрезку не влияет (она из оригинала).
        pmin_lbl = QLabel("Минут для прокси")
        pmin_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        self.spin_proxy_min = QSpinBox()
        self.spin_proxy_min.setRange(0, 600)
        self.spin_proxy_min.setValue(0)
        self.spin_proxy_min.setSpecialValueText("Весь файл")
        self.spin_proxy_min.setSuffix(" мин")
        self.spin_proxy_min.setToolTip(
            "Создавать прокси только для первых N минут видео (0 — весь файл).\n"
            "Усечённый прокси собирается быстрее на длинных/тяжёлых файлах.\n"
            "Предпросмотр ограничится этим отрезком; на экспорт и обрезку не влияет.")
        self._relax_width(self.spin_proxy_min)
        self.spin_proxy_min.valueChanged.connect(lambda *_: self._on_pb_quality_changed())
        pbq_card._body.addWidget(pmin_lbl)
        pbq_card._body.addWidget(self.spin_proxy_min)
        sb_layout.addWidget(pbq_card)

        # Proxy badge
        self.lbl_proxy = QLabel("")
        self.lbl_proxy.setStyleSheet(f"""
            color: {C['yellow']};
            font-size: 11px;
            font-weight: 600;
            padding: 4px 8px;
            background: rgba(245,158,11,0.12);
            border: 1px solid rgba(245,158,11,0.3);
            border-radius: 4px;
        """)
        self.lbl_proxy.setVisible(False)
        sb_layout.addWidget(self.lbl_proxy)

        sb_layout.addStretch()

        # Прокручиваемая часть готова — вставляем её в сайдбар.
        sb_scroll.setWidget(sb_content)
        sb_outer.addWidget(sb_scroll, 1)

        # Колесо мыши над выпадающими списками правой панели прокручивает саму
        # панель, а не меняет значение поля. Иначе при включённой в Настройках
        # опции «колесо меняет значения» скролл «застревал» на блоке режима
        # обрезки — комбобокс съедал событие колеса.
        for _w in sb_content.findChildren(QComboBox):
            self._install_wheel_scroll(_w)

        # ── Итог + кнопка обрезки — закреплены СНИЗУ (вне прокрутки) ───────
        # Высота блока = высоте полосы таймлайна (BAND_H ниже) → «Итог»/«Обрезать»
        # визуально на одной строке с виджетом аудио-визуализации слева.
        sb_bottom = QFrame()
        sb_bottom.setObjectName("SidebarBottom")
        sb_bottom.setFixedHeight(116)
        sb_bottom.setStyleSheet(
            f"#SidebarBottom {{ background: {C['surface']}; border-top: 1px solid {C['border']}; }}")
        bottom_l = QVBoxLayout(sb_bottom)
        bottom_l.setContentsMargins(16, 10, 16, 14)
        bottom_l.setSpacing(10)
        bottom_l.addStretch()

        self.lbl_selection = QLabel("Зона: —")
        self.lbl_selection.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_selection.setStyleSheet(f"""
            color: {C['text']};
            font-size: 13px;
            font-weight: 600;
            padding: 7px 10px;
            background: {C['surface2']};
            border: 1px solid {C['border']};
            border-radius: 6px;
        """)
        bottom_l.addWidget(self.lbl_selection)

        self.btn_cut = QPushButton("Обрезать")
        self.btn_cut.setIcon(get_icon('fa5s.cut', color='#1e1e2e'))
        self.btn_cut.setIconSize(QSize(20, 20))
        self.btn_cut.clicked.connect(self.start_cut)
        # Зелёная, как кнопка «НАЧАТЬ» во вкладке «Обработка» (#b_run в config.py).
        self.btn_cut.setStyleSheet(f"""
            QPushButton {{
                background: #a6e3a1;
                color: #1e1e2e;
                border: none;
                border-radius: 6px;
                padding: 9px 24px;
                font-weight: 700;
                font-size: 13px;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover {{ background: #94e2d5; }}
            QPushButton:pressed {{ background: #74c7ec; }}
            QPushButton:disabled {{ background: {C['surface3']}; color: {C['text3']}; }}
        """)
        bottom_l.addWidget(self.btn_cut)
        bottom_l.addStretch()
        sb_outer.addWidget(sb_bottom, 0)

        # progress/log_label больше не показываются в интерфейсе (прогресс идёт в
        # общий прогрессбар окна). Оставлены скрытыми, чтобы существующий код,
        # дёргающий .setText()/.setValue(), не падал.
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.log_label = QLabel("")
        self.log_label.setVisible(False)

        # Сайдбар добавляется ПОСЛЕ центральной области (root.addWidget ниже),
        # чтобы видео и плеер были слева, а панель информации/экспорта — справа.

        # ── Center area ───────────────────────────────────────────────────
        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)

        # Video player area + правая панель (дорожки/субтитры/индикатор звука).
        # Панель занимает место, где раньше были чёрные поля сбоку от видео.
        video_row = QHBoxLayout()
        video_row.setContentsMargins(0, 0, 0, 0)
        video_row.setSpacing(0)

        self.video_container = QFrame()
        self.video_container.setObjectName("VideoContainer")
        # Фон — цвет интерфейса (а не чёрный): пустота вокруг кадра сливается с UI.
        self.video_container.setStyleSheet(f"#VideoContainer {{ background: {C['bg']}; }}")
        vc_layout = QHBoxLayout(self.video_container)
        self.vc_layout = vc_layout
        vc_layout.setContentsMargins(0, 0, 0, 0)
        # Видео центрировано (по горизонтали и вертикали); точный аспект кадра
        # задаётся в _adjust_video_height → внутри виджета полей нет, а свободное
        # место по бокам — это фон цвета интерфейса.
        vc_layout.addWidget(self.video_widget, 0, Qt.AlignmentFlag.AlignCenter)
        # Оверлей субтитров (VLC-стиль) создаётся лениво как отдельное окно поверх
        # видео — см. _ensure_overlay/_position_overlay (QVideoWidget нативный,
        # обычный дочерний виджет под ним не виден).
        video_row.addWidget(self.video_container, 1)

        # Правая панель
        side = QFrame()
        side.setObjectName("SidePanel")
        side.setFixedWidth(196)
        side.setStyleSheet(f"#SidePanel {{ background: {C['surface']}; border-left: 1px solid {C['border']}; }}")
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(10, 10, 10, 10)
        side_l.setSpacing(6)

        _combo_css = f"""
            QComboBox {{
                background: {C['surface3']}; color: {C['text']};
                border: 1px solid {C['border2']}; border-radius: 5px;
                padding: 5px 8px; font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background: {C['surface3']}; color: {C['text']};
                selection-background-color: {C['accent']};
                border: 1px solid {C['border2']};
            }}
        """
        def _find_btn(tip, slot):
            b = QPushButton()
            b.setIcon(get_icon('fa5s.folder-open'))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedSize(30, 28)
            b.setStyleSheet(f"""
                QPushButton {{ background: {C['surface3']}; color: {C['text']};
                    border: 1px solid {C['border2']}; border-radius: 5px;
                    padding: 0; font-size: 13px; }}
                QPushButton:hover {{ background: {C['border2']};
                    border-color: {C['accent']}; }}
            """)
            b.clicked.connect(slot)
            return b

        lbl_at = QLabel("Аудиодорожка")
        lbl_at.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        side_l.addWidget(lbl_at)
        at_row = QHBoxLayout(); at_row.setContentsMargins(0, 0, 0, 0); at_row.setSpacing(5)
        self.cmb_audio = QComboBox()
        self.cmb_audio.setStyleSheet(_combo_css)
        self.cmb_audio.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_audio.setMinimumContentsLength(6)
        self.cmb_audio.currentIndexChanged.connect(self.on_audio_track_changed)
        at_row.addWidget(self.cmb_audio, 1)
        self.btn_find_audio = _find_btn(
            "Найти внешний аудиофайл (озвучку) на ПК", self.find_external_audio)
        at_row.addWidget(self.btn_find_audio, 0)
        side_l.addLayout(at_row)

        # Заголовок «Субтитры» + кнопка-карандаш (правка текста субтитров прямо тут).
        st_hdr = QHBoxLayout(); st_hdr.setContentsMargins(0, 0, 0, 0); st_hdr.setSpacing(4)
        lbl_st = QLabel("Субтитры")
        lbl_st.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        st_hdr.addWidget(lbl_st)
        st_hdr.addStretch(1)
        self.btn_edit_subs = QPushButton()
        self.btn_edit_subs.setIcon(get_icon('fa5s.edit', color=C['text2']))
        self.btn_edit_subs.setIconSize(QSize(14, 14))
        self.btn_edit_subs.setFixedSize(24, 20)
        self.btn_edit_subs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit_subs.setToolTip("Редактировать текст выбранных субтитров")
        self.btn_edit_subs.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; border-radius: 4px; }}
            QPushButton:hover {{ background: {C['surface3']}; }}
            QPushButton:pressed {{ background: {C['border2']}; }}
        """)
        self.btn_edit_subs.clicked.connect(self.edit_subtitles)
        st_hdr.addWidget(self.btn_edit_subs)
        side_l.addLayout(st_hdr)
        st_row = QHBoxLayout(); st_row.setContentsMargins(0, 0, 0, 0); st_row.setSpacing(5)
        self.cmb_subs = QComboBox()
        self.cmb_subs.setStyleSheet(_combo_css)
        self.cmb_subs.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_subs.setMinimumContentsLength(6)
        self.cmb_subs.currentIndexChanged.connect(self.on_sub_track_changed)
        st_row.addWidget(self.cmb_subs, 1)
        self.btn_find_subs = _find_btn(
            "Найти внешний файл субтитров на ПК", self.find_external_subs)
        st_row.addWidget(self.btn_find_subs, 0)
        side_l.addLayout(st_row)

        # Стиль вшиваемых субтитров (hardsub): как в программе или как в оригинале.
        lbl_ss = QLabel("Стиль вшитых субтитров")
        lbl_ss.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        side_l.addWidget(lbl_ss)
        self.cmb_sub_style = QComboBox()
        self.cmb_sub_style.addItems(["Авто", "Как в программе", "Как в оригинале"])
        # По умолчанию — «Как в оригинале» (стиль из самих субтитров, ничего не навязываем).
        self.cmb_sub_style.setCurrentIndex(2)
        self.cmb_sub_style.setToolTip(
            "Стиль субтитров при вшивании в кадр:\n"
            "Авто — стиль программы для SRT/VTT, у ASS/SSA остаётся собственный.\n"
            "Как в программе — крупный белый шрифт с обводкой даже поверх ASS/SSA.\n"
            "Как в оригинале — ничего не навязывать (стиль из самих субтитров).")
        self.cmb_sub_style.setStyleSheet(_combo_css)
        self.cmb_sub_style.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_sub_style.setMinimumContentsLength(6)
        side_l.addWidget(self.cmb_sub_style)

        # Чекбокс «Вшить субтитры» — НАД индикатором уровня звука (по просьбе
        # пользователя). Кнопки кадра/удаления переехали в самый низ панели.
        side_l.addSpacing(6)
        side_l.addWidget(self.chk_burn_subs)

        # Низ боковой панели: СЛЕВА — кнопки «Сохранить кадр»/«Удалить исходник»
        # (столбиком), СПРАВА — индикатор уровня звука. Прежде кнопки лежали ПОД
        # индикатором и перекрывали подписи каналов L/R (см. скрин); теперь они
        # сбоку, и шкала уровня занимает всю доступную высоту панели.
        # «Кадрировать видео» — значок над «Сохранить кадр»: включаешь, выделяешь
        # область прямо на видео, и при «Обрезать» итоговое ВИДЕО кадрируется по
        # этой рамке (а не только сохраняемый кадр). Повторное нажатие выключает и
        # сбрасывает рамку. Кадрирование требует перекодировки (copy не умеет
        # crop), поэтому при активной рамке быстрый режим переключается на
        # «Перекодировать» автоматически.
        self.btn_crop_frame = make_icon_btn("")
        self.btn_crop_frame.setIcon(get_icon('fa5s.crop-alt'))
        self.btn_crop_frame.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_crop_frame)
        self.btn_crop_frame.setCheckable(True)
        self.btn_crop_frame.setToolTip("Кадрировать видео: выделите область на видео — "
                                       "при «Обрезать» сохранится только она "
                                       "(требует перекодировки)")
        self.btn_crop_frame.toggled.connect(self._toggle_frame_crop)
        self.btn_crop_frame.setEnabled(False)
        # «Пикселизация — проявление»: видео стартует крупными блоками и постепенно
        # проясняется (для угадайки). Параметры задаются в диалоге, эффект
        # применяется при «Обрезать» (требует перекодировки, как и кадрирование).
        self._pixelize_active = False
        self._pixelize_steps = 6
        self._pixelize_block = 64
        self.btn_pixelize = make_icon_btn("")
        self.btn_pixelize.setIcon(get_icon('fa5s.th'))
        self.btn_pixelize.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_pixelize)
        self.btn_pixelize.setCheckable(True)
        self.btn_pixelize.setToolTip("Пикселизация: видео начнётся крупными «пикселями» "
                                     "и постепенно станет чётким (для угадайки). "
                                     "Применяется при «Обрезать» (перекодировка)")
        self.btn_pixelize.toggled.connect(self._toggle_pixelize)
        self.btn_pixelize.setEnabled(False)
        # ВИДИМОЕ состояние «включено»: make_icon_btn не стилизует :checked, и
        # армированная пикселизация выглядела как обычная кнопка (пользователь не
        # видел, что эффект активен). Подсвечиваем активную кнопку акцентом.
        self.btn_pixelize.setStyleSheet(self.btn_pixelize.styleSheet() + f"""
            QPushButton:checked {{
                background: {C['accent']}; color: #11111b;
                border: 1px solid transparent;
            }}
            QPushButton:checked:hover {{ background: {C['accent2']}; }}
        """)
        self.btn_save_frame = make_icon_btn("")
        self.btn_save_frame.setIcon(get_icon('fa5s.save'))
        self.btn_save_frame.setIconSize(QSize(20, 20))
        self._relax_width(self.btn_save_frame)
        self.btn_save_frame.setToolTip("Сохранить текущий кадр в PNG (в папку сохранения)")
        self.btn_save_frame.clicked.connect(self.save_frame)
        self.btn_save_frame.setEnabled(False)   # активна только при загруженном видео
        # «Удалить объект» — покадровое удаление водяного знака/эмодзи с видео тем же
        # движком LaMa, что и в фоторедакторе (см. remove_object_from_video).
        self.btn_remove_object = make_icon_btn("")
        self.btn_remove_object.setIcon(get_icon('fa5s.magic'))
        self.btn_remove_object.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_remove_object)
        self.btn_remove_object.setToolTip(
            "Удалить объект с видео (водяной знак, эмодзи, логотип): закрасьте его "
            "кистью на кадре — нейросеть LaMa уберёт его со всех кадров")
        self.btn_remove_object.clicked.connect(self.remove_object_from_video)
        self.btn_remove_object.setEnabled(False)
        self.btn_delete_source = make_icon_btn("", danger=True)
        self.btn_delete_source.setIcon(get_icon('fa5s.trash-alt', color='#11111b'))
        self.btn_delete_source.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_delete_source)
        self.btn_delete_source.setToolTip("Удалить исходный файл с диска (без возможности отмены)")
        self.btn_delete_source.clicked.connect(self.delete_source_file)
        self.btn_delete_source.setEnabled(False)

        # Левая колонка — кнопки, прижаты к низу (высота — под ровно 8 значков).
        btn_col = QVBoxLayout(); btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.setSpacing(self._MSIDE_GAP)
        btn_col.addStretch(1)
        self._montage_side_btns = [self.btn_crop_frame, self.btn_pixelize,
                                   self.btn_save_frame, self.btn_remove_object,
                                   self.btn_delete_source]
        for _b in self._montage_side_btns:
            btn_col.addWidget(_b)

        # Правая колонка — подпись + шкала, отцентрованная под текстом.
        vu_col = QVBoxLayout(); vu_col.setContentsMargins(0, 0, 0, 0); vu_col.setSpacing(3)
        lbl_vu = QLabel("Уровень звука")
        lbl_vu.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        lbl_vu.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        vu_col.addWidget(lbl_vu, 0)
        self.audio_meter = AudioMeter()
        self.audio_meter.setFixedWidth(54)
        meter_row = QHBoxLayout(); meter_row.setContentsMargins(0, 0, 0, 0)
        meter_row.addStretch(1)
        meter_row.addWidget(self.audio_meter)
        meter_row.addStretch(1)
        vu_col.addLayout(meter_row, 1)
        # Высота шкалы == высоте колонки кнопок → по её ресайзу пересчитываем кнопки.
        self.audio_meter.installEventFilter(self)

        bottom_row = QHBoxLayout(); bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(10)
        bottom_row.addLayout(btn_col, 1)
        bottom_row.addLayout(vu_col, 0)
        side_l.addLayout(bottom_row, 1)

        video_row.addWidget(side, 0)
        center.addLayout(video_row, stretch=1)

        # ── Player bar (прямо под видео) ──────────────────────────────────
        # Компактный плеер как в обычном видеоплеере: полоса воспроизведения,
        # тайминги (текущее/общее), кнопки и громкость — всё под самим видео.
        player_bar = QFrame()
        player_bar.setObjectName("PlayerBar")
        player_bar.setStyleSheet(f"#PlayerBar {{ background: {C['surface']}; border-top: 1px solid {C['border']}; }}")
        pb_layout = QVBoxLayout(player_bar)
        pb_layout.setContentsMargins(12, 6, 12, 7)
        pb_layout.setSpacing(6)

        # Верхняя строка: полоса воспроизведения + тайминги (текущее / общее)
        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(10)

        self.slider = SeekSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self.on_slider_moved)
        self.slider.setStyleSheet(self._slider_style(C["playhead"]))
        # Превью кадров при наведении на полосу (как на YouTube). Один контроллер
        # на обе полосы — в окне и в полноэкранном режиме (см. FullscreenVideo).
        self.seek_preview = SeekPreview(lambda: getattr(self, "duration", 0.0) or 0.0)
        self.slider.attach_preview(self.seek_preview)
        seek_row.addWidget(self.slider, 1)

        time_frame = QFrame()
        time_frame.setStyleSheet(f"""
            background: {C['bg']};
            border: 1px solid {C['border']};
            border-radius: 6px;
        """)
        time_fl = QHBoxLayout(time_frame)
        time_fl.setContentsMargins(8, 3, 8, 3)
        time_fl.setSpacing(3)
        _mono = QFont("Courier New" if os.name == 'nt' else "Courier")
        _mono.setBold(True); _mono.setPointSize(11)
        self.lbl_current_time = QLabel("00:00:00.000")
        self.lbl_current_time.setFont(_mono)
        self.lbl_current_time.setStyleSheet(f"color: {C['green2']}; background: transparent;")
        sep_time = QLabel("/")
        sep_time.setStyleSheet(f"color: {C['text3']}; background: transparent;")
        self.lbl_total_time = QLabel("00:00:00.000")
        self.lbl_total_time.setFont(_mono)
        self.lbl_total_time.setStyleSheet(f"color: {C['text3']}; background: transparent;")
        time_fl.addWidget(self.lbl_current_time)
        time_fl.addWidget(sep_time)
        time_fl.addWidget(self.lbl_total_time)
        seek_row.addWidget(time_frame)
        pb_layout.addLayout(seek_row)

        # Нижняя строка: кнопки управления + громкость
        pctrl_row = QHBoxLayout()
        pctrl_row.setContentsMargins(0, 0, 0, 0)
        pctrl_row.setSpacing(6)

        # Кнопки плеера — только иконки, без подписей (квадратные).
        self.btn_stop = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaStop)
        self.btn_stop.setFixedWidth(40)
        self.btn_stop.setToolTip("Стоп — к началу зоны")
        self.btn_stop.clicked.connect(self.stop_playback)
        pctrl_row.addWidget(self.btn_stop)

        self.btn_step_back = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaSeekBackward)
        self.btn_step_back.setFixedWidth(40)
        self.btn_step_back.setToolTip("Кадр назад (←)")
        self.btn_step_back.clicked.connect(partial(self.step_frame_scrub, -1))
        pctrl_row.addWidget(self.btn_step_back)

        self.btn_play = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaPlay, accent=True)
        self.btn_play.setFixedWidth(48)
        self.btn_play.setToolTip("Воспроизвести / пауза (Пробел)")
        self.btn_play.clicked.connect(self.toggle_play)
        pctrl_row.addWidget(self.btn_play)

        self.btn_step_fwd = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaSeekForward)
        self.btn_step_fwd.setFixedWidth(40)
        self.btn_step_fwd.setToolTip("Кадр вперёд (→)")
        self.btn_step_fwd.clicked.connect(partial(self.step_frame_scrub, 1))
        pctrl_row.addWidget(self.btn_step_fwd)

        self.btn_jump_end = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaSkipForward)
        self.btn_jump_end.setFixedWidth(40)
        self.btn_jump_end.setToolTip("Перейти к концу зоны (OUT)")
        self.btn_jump_end.clicked.connect(lambda: self.seek_to(self.current_out))
        pctrl_row.addWidget(self.btn_jump_end)

        pctrl_row.addSpacing(14)

        # Поля ввода таймкода IN/OUT убраны по запросу — вместо них кнопки
        # «Обрезать старт/конец» (до плейхеда) и длительность выделения. Сами
        # объекты in_time_edit/out_time_edit/in_frame_spin/out_frame_spin остаются
        # СКРЫТЫМИ держателями: на них завязан остальной код (set_in_out и т.п.).
        io_holder = QWidget(player_bar)
        io_h = QHBoxLayout(io_holder); io_h.setContentsMargins(0, 0, 0, 0)
        self.in_time_edit = QLineEdit("00:00:00.000")
        self.in_time_edit.returnPressed.connect(self.set_in_point)
        self.in_frame_spin = QSpinBox(); self.in_frame_spin.setMaximum(100000000)
        self.in_frame_spin.valueChanged.connect(self.on_in_frame_changed)
        self.out_time_edit = QLineEdit("00:00:05.000")
        self.out_time_edit.returnPressed.connect(self.set_out_point)
        self.out_frame_spin = QSpinBox(); self.out_frame_spin.setMaximum(100000000)
        self.out_frame_spin.valueChanged.connect(self.on_out_frame_changed)
        for _w in (self.in_time_edit, self.in_frame_spin,
                   self.out_time_edit, self.out_frame_spin):
            io_h.addWidget(_w)
        io_holder.hide()

        _trim_btn_css = f"""
            QPushButton {{
                background: {C['surface3']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 6px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {C['surface2']}; border-color: {C['accent']}; }}
            QPushButton:pressed {{ background: {C['surface']}; }}
            QPushButton:disabled {{ color: {C['text3']}; }}
        """
        _ss = getattr(self, "trim_start_seq", "Shift+C")
        _es = getattr(self, "trim_end_seq", "Shift+V")
        self.btn_trim_start = QPushButton("Обрезать старт")
        self.btn_trim_start.setToolTip(
            f"Поставить начало (старт) на жёлтую полосу воспроизведения ({_ss})")
        self.btn_trim_start.setStyleSheet(_trim_btn_css)
        # NoFocus: иначе клик мыши уводил клавиатурный фокус на кнопку, и потом
        # Space/Ctrl+Z воспринимались как нажатие кнопки/уходили мимо вкладки
        # (баг «после кнопок Обрезать Ctrl+Z не работает»). Фокус оставляем на
        # вкладке монтажа — там висят все хоткеи (WidgetWithChildrenShortcut).
        self.btn_trim_start.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_trim_start.clicked.connect(self.trim_start_to_playhead)
        pctrl_row.addWidget(self.btn_trim_start)

        self.btn_trim_end = QPushButton("Обрезать конец")
        self.btn_trim_end.setToolTip(
            f"Поставить конец на жёлтую полосу воспроизведения ({_es})")
        self.btn_trim_end.setStyleSheet(_trim_btn_css)
        self.btn_trim_end.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_trim_end.clicked.connect(self.trim_end_to_playhead)
        pctrl_row.addWidget(self.btn_trim_end)

        # Длительность отрезка от старта (IN) до жёлтой полосы воспроизведения.
        seg_frame = QFrame()
        seg_frame.setObjectName("SegFrame")
        seg_frame.setStyleSheet(f"#SegFrame {{ background: {C['surface3']}; border: 1px solid {C['border2']}; border-radius: 6px; }}")
        seg_l = QHBoxLayout(seg_frame)
        seg_l.setContentsMargins(8, 4, 8, 4); seg_l.setSpacing(6)
        seg_cap = QLabel("⏱ старт→плейхед")
        seg_cap.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        self.lbl_seg_dur = QLabel("00:00:00.000")
        self.lbl_seg_dur.setStyleSheet(f"color: {C['text']}; font-size: 12px; font-weight: 700;")
        self.lbl_seg_dur.setToolTip(
            "Длительность от начала (старта) до жёлтой полосы воспроизведения")
        seg_l.addWidget(seg_cap); seg_l.addWidget(self.lbl_seg_dur)
        pctrl_row.addWidget(seg_frame)

        pctrl_row.addStretch()

        # Регулятор громкости — у правого края, рядом с полноэкранным режимом.
        # (Кнопки «Сохранить кадр»/«Удалить исходник» — внизу боковой панели.)
        self.vol_lbl = VolumeLabel(lambda: getattr(self, "vol_slider", None))
        self.vol_lbl.setStyleSheet(f"color: {C['text2']}; font-size: 14px;")
        pctrl_row.addWidget(self.vol_lbl)
        self.vol_slider = VolumeSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(96)
        self.vol_slider.setStyleSheet(self._slider_style(C["text2"], compact=True))
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        pctrl_row.addWidget(self.vol_slider)

        pctrl_row.addSpacing(8)
        self.btn_fullscreen = make_icon_btn("", accent=True)
        # Стартует без видео → disabled и приглушённая иконка (станет белой при
        # загрузке видео в _update_media_buttons).
        self.btn_fullscreen.setIcon(_fullscreen_icon(expand=True, color=C['text3']))
        self.btn_fullscreen.setIconSize(QSize(20, 20))
        self.btn_fullscreen.setToolTip("Полноэкранный режим (F / двойной клик по видео)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        self.btn_fullscreen.setEnabled(False)   # активна только при загруженном видео
        pctrl_row.addWidget(self.btn_fullscreen)

        pb_layout.addLayout(pctrl_row)
        center.addWidget(player_bar)

        # Состояние полноэкранного режима (окно создаётся по запросу).
        self._fs_window = None

        # ── Timeline panel ────────────────────────────────────────────────
        # Высота полосы таймлайна фиксирована и совпадает с нижним блоком правой
        # панели («Итог» + «Обрезать»), чтобы они визуально были одной строкой.
        # Панель ужата почти до высоты самой визуализации (волна + скроллбар +
        # небольшие отступы сверху/снизу) — остальное место отдаётся видео.
        BAND_H = 116
        timeline_panel = QFrame()
        timeline_panel.setObjectName("TimelinePanel")
        timeline_panel.setFixedHeight(BAND_H)
        timeline_panel.setStyleSheet(f"#TimelinePanel {{ background: {C['surface']}; border-top: 1px solid {C['border']}; }}")
        tp_layout = QVBoxLayout(timeline_panel)
        tp_layout.setContentsMargins(12, 6, 12, 6)
        tp_layout.setSpacing(3)

        # Горизонтальная прокрутка волны — над виджетом визуализации аудио.
        # Видна только когда волна увеличена (zoom>1) и есть что прокручивать;
        # двигает «окно обзора» (view_offset) по таймлайну.
        self.wave_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.wave_scroll.setObjectName("WaveScroll")
        self.wave_scroll.setRange(0, 0)
        self.wave_scroll.valueChanged.connect(self.on_wave_scroll)
        self.wave_scroll.setVisible(False)
        self.wave_scroll.setStyleSheet(f"""
            QScrollBar:horizontal {{
                background: {C['surface2']};
                height: 12px;
                border-radius: 6px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {C['border2']};
                border-radius: 5px;
                min-width: 28px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {C['accent']}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
        """)
        tp_layout.addWidget(self.wave_scroll)

        # Waveform — невысокая полоса (амплитуда у обычного звука небольшая, при
        # большой высоте сверху/снизу остаётся пустота). Ограничиваем высоту и
        # оставляем небольшой отступ снизу (margin tp_layout).
        self.waveform = WaveformWidget()
        self.waveform.setMinimumHeight(54)
        self.waveform.setMaximumHeight(104)
        self.waveform.seekRequested.connect(self.on_wave_seek)
        self.waveform.playSeekRequested.connect(self.on_wave_playseek)
        # ВНИМАНИЕ: inSetRequested/outSetRequested НЕ подключаем — selectionChanged
        # уже синхронизирует state/поля/кадры (иначе двойной вызов, баг #10).
        self.waveform.selectionChanged.connect(self.on_wave_selection_changed)
        self.waveform.viewChanged.connect(self.on_wave_view_changed)
        self.waveform.interactionStarted.connect(self.push_undo)
        # ПКМ по аудио-визуализации → меню обрезки старт/конец до плейхеда.
        self.waveform.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.waveform.customContextMenuRequested.connect(self._trim_ctx_menu)
        tp_layout.addWidget(self.waveform, stretch=1)

        # Строка «ПРОКРУТКА» убрана по запросу. pan_slider оставлен как скрытый
        # объект (без родителя, никогда не показывается) — чтобы существующий код
        # update_pan_slider_values не падал; pan_row_w намеренно НЕ создаём
        # (getattr → None → строка панорамирования не отображается).
        self.pan_slider = QSlider(Qt.Orientation.Horizontal)
        self.pan_slider.setRange(0, 1000)
        self.pan_slider.setEnabled(False)
        self.pan_slider.sliderMoved.connect(self.on_pan_moved)

        # Полоса воспроизведения (self.slider) перенесена в player_bar под видео.

        # Таймлайн фиксированной (небольшой) высоты — лишнее место отдаётся видео
        # (video_row = stretch 1). Нижние панели (IN/OUT) тоже stretch=0, поэтому
        # на маленьком окне ужимается именно видео, а не интерфейс под ним.
        center.addWidget(timeline_panel, stretch=0)

        # (IN/OUT перенесены на строку с кнопками плеера в player_bar; отдельной
        #  панели IN/OUT больше нет. Панель управления плеером — в player_bar под
        #  видео; «Итог» и «Обрезать» — в правой панели.)

        root.addLayout(center, stretch=1)
        root.addWidget(sidebar)

    # ── Style helpers ──────────────────────────────────────────────────────
    def _slider_style(self, color, compact=False):
        h = "4px" if compact else "5px"
        return f"""
            QSlider::groove:horizontal {{
                background: {C['surface3']};
                border-radius: 3px;
                height: {h};
            }}
            QSlider::handle:horizontal {{
                background: {color};
                border: 2px solid {C['bg']};
                width: 13px; height: 13px;
                margin: -4px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {color};
                border-radius: 3px;
            }}
        """

    def _input_style(self):
        return f"""
            QLineEdit {{
                background: {C['bg']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 5px;
                padding: 5px 8px;
                font-size: 12px;
                font-family: Courier New, Courier;
            }}
            QLineEdit:focus {{ border-color: {C['accent']}; }}
        """

    def _spin_style(self):
        return f"""
            QSpinBox {{
                background: {C['bg']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 5px;
                padding: 5px 4px;
                font-size: 12px;
            }}
            QSpinBox:focus {{ border-color: {C['accent']}; }}
            QSpinBox::up-button, QSpinBox::down-button {{ width: 14px; }}
        """

    def apply_theme(self):
        # Тёмная тема редактора применяется к этому виджету и его потомкам,
        # переопределяя общий стиль приложения только в пределах вкладки.
        self.setStyleSheet(f"""
            QWidget {{
                background: {C['bg']};
                color: {C['text']};
                font-family: 'Segoe UI', 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif;
                font-size: 13px;
            }}
            QToolTip {{
                background: {C['surface3']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QLabel {{ background: transparent; }}
            QMessageBox {{ background: {C['surface']}; }}
            QFileDialog {{ background: {C['surface']}; }}
        """)

    def _install_wheel_scroll(self, widget):
        """Заставляет виджет (комбобокс и т.п.) НЕ менять значение на колесо
        мыши, а прокручивать ближайшую QScrollArea-родителя — так колесо над
        полем прокручивает панель, как и над пустым местом."""
        def handler(event, _w=widget):
            sa = _w.parent()
            while sa is not None and not isinstance(sa, QScrollArea):
                sa = sa.parent()
            if isinstance(sa, QScrollArea):
                QApplication.sendEvent(sa.viewport(), event)
            else:
                event.ignore()
        widget.wheelEvent = handler

    def _on_cut_progress(self, p):
        self._cut_lastp = float(p)
        self._report_cut(self._cut_lastp)

    def _report_cut(self, p):
        """Строка прогресса обрезки с ETA. Пока ffmpeg не дал реального прогресса
        (p<1 — фаза подготовки/перемотки), показываем счётчик «прошло», чтобы не
        выглядело зависшим. Дублируем статус в крупную метку над кнопкой
        «Обрезать» (lbl_selection) — нижняя полоса окна легко теряется, а здесь
        пользователь смотрит прямо на кнопку (см. _set_cut_status)."""
        try:
            elapsed = time.time() - getattr(self, "_cut_t0", time.time())
            if p >= 1.0:
                eta = max(0.0, elapsed * (100.0 - p) / p)
                txt = f"Обрезка… {int(p)}%  •  ETA {self._fmt_mmss(eta)}"
                self._report_progress(int(p), txt)
                self._set_cut_status(f"Обрезка… {int(p)}%  •  ETA {self._fmt_mmss(eta)}",
                                     icon='fa5s.cut')
            else:
                # Фаза подготовки: при обрезке с перекодированием ffmpeg сначала
                # перематывает декодер до точки реза (выходной seek) и ещё не даёт
                # ни одного out_time — реального процента нет. Включаем пульсирующий
                # («busy») режим полосы, чтобы она не выглядела зависшей на 0%.
                txt = f"Обрезка… подготовка ({self._fmt_mmss(elapsed)})"
                self._report_progress(-1, txt)
                self._set_cut_status(f"Обрезка… подготовка {self._fmt_mmss(elapsed)}",
                                     icon='fa5s.hourglass-half')
        except Exception:
            pass

    def _set_cut_status(self, text, icon='fa5s.cut'):
        """Показывает текст прогресса обрезки в крупной метке над кнопкой
        «Обрезать» (вместо «Итог: …»). Видно прямо на месте действия, в отличие
        от полосы внизу окна. Снимается через _clear_cut_status → восстанавливает
        обычный «Итог: …»."""
        lbl = getattr(self, "lbl_selection", None)
        if lbl is None:
            return
        try:
            lbl.setText(f"{icon_html(icon, 13, C['accent'])}  {text}")
        except Exception:
            pass

    def _clear_cut_status(self):
        """Возвращает метку над кнопкой к обычному виду «Итог: …» после обрезки."""
        try:
            self.update_selection_label()
        except Exception:
            pass

    @staticmethod
    def _replace_tolerant(temp, final):
        """Переносит temp → final атомарным os.replace. Если файл назначения занят
        ДРУГИМ процессом (например, его прямо сейчас читает вкладка «Обработка»,
        перекодируя только что сделанную обрезку) — Windows возвращает
        WinError 32 и os.replace падает. Раньше это роняло всю обрезку с ошибкой
        «не может получить доступ к файлу». Теперь в таком случае сохраняем
        готовый результат под соседним свободным именем (foo_обрез_1.mkv, _2…),
        а не теряем работу. Возвращает фактический путь сохранения."""
        candidate = final
        last_err = None
        for _ in range(128):
            try:
                os.replace(temp, candidate)
                return candidate
            except OSError as e:
                # WinError 32 (sharing violation) приходит как PermissionError или
                # OSError с winerror==32 — цель занята, пробуем соседнее имя.
                busy = isinstance(e, PermissionError) or getattr(e, "winerror", None) == 32
                if not busy:
                    raise
                last_err = e
                candidate = _unique_output(candidate)
        # Крайне маловероятно (128 занятых имён подряд) — пробрасываем ошибку.
        if last_err:
            raise last_err
        return candidate

    def _notify_busy_rename(self, wanted, saved):
        """Сообщает, что целевой файл был занят и обрезка сохранена под другим
        именем (а не потеряна с ошибкой WinError 32)."""
        msg = (f"Файл «{os.path.basename(wanted)}» был занят другим процессом "
               f"(скорее всего, его перекодирует вкладка «Обработка»).\n\n"
               f"Обрезка сохранена под именем «{os.path.basename(saved)}».")
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(msg.replace("\n\n", " "))
        except Exception:
            pass
        try:
            QMessageBox.information(self, "Файл был занят", msg)
        except Exception:
            pass

    @staticmethod
    def _fmt_mmss(sec):
        sec = int(max(0, sec))
        return f"{sec // 60:d}:{sec % 60:02d}"

    def _report_progress(self, pct, text=""):
        """Прогресс вкладки → общий прогрессбар окна (main.pbar). В standalone-
        режиме (без главного окна) обновляет собственный скрытый прогрессбар.
        pct < 0 → неопределённый («busy») режим — полоса пульсирует."""
        busy = (pct is not None and pct < 0)
        if not busy:
            pct = int(max(0, min(100, pct)))
        try:
            if self.main is not None and hasattr(self.main, 'update_global_progress'):
                self.main.update_global_progress(
                    -1 if busy else pct,
                    text or ("Монтаж" if busy else ("Готово" if pct >= 100 else "Монтаж")))
                return
        except Exception:
            pass
        try:
            if busy:
                self.progress.setRange(0, 0)
            else:
                if self.progress.maximum() == 0:
                    self.progress.setRange(0, 100)
                self.progress.setValue(pct)
        except Exception:
            pass

    # ── Видеовыход и метод субтитров ─────────────────────────────────────────
    def _read_subs_in_frame_pref(self):
        """Метод субтитров теперь зафиксирован значением по умолчанию (рендер
        прямо в кадр, как в VLC) — настройка убрана из UI по просьбе пользователя."""
        return True

    def _build_video_output(self):
        """Создаёт виджет видео под текущий метод субтитров и подключает плеер.
        frame-режим: VideoCanvas (рисуем кадр сами + субтитры в кадр).
        overlay-режим: QVideoWidget (нативная поверхность) + окно-оверлей."""
        if self._subs_in_frame:
            self.video_widget = VideoCanvas()
            try:
                self.player.setVideoSink(self.video_widget.videoSink())
            except Exception:
                pass
        else:
            self.video_widget = QVideoWidget()
            try:
                self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            except Exception:
                pass
            self.player.setVideoOutput(self.video_widget)
        self.video_widget.setStyleSheet(f"background: {C['bg']};")
        # Анти-overshoot: VideoCanvas сам ловит кадр за OUT по PTS → просит паузу.
        if isinstance(self.video_widget, VideoCanvas):
            self.video_widget.boundaryReached.connect(self._on_play_boundary)
            # Кадрирование завершено кнопкой на холсте — снимаем чек с «Кадрировать».
            self.video_widget.cropApplied.connect(self._on_crop_applied)
            self.video_widget.cropCancelled.connect(self._on_crop_cancelled)
        try:
            self.video_widget.setAcceptDrops(True)
            self.video_widget.installEventFilter(self)
        except Exception:
            pass

    def set_subs_in_frame(self, in_frame, save=True):
        """Переключает метод субтитров (Монтаж → Настройки). Применяется на лету:
        пересобирает виджет видео в layout, переносит позицию/воспроизведение и
        перенастраивает показ текущей дорожки субтитров."""
        in_frame = bool(in_frame)
        if not getattr(self, "_ready", False):
            self._subs_in_frame = in_frame
            if save:
                try: self.save_settings()
                except Exception: pass
            return
        if in_frame == self._subs_in_frame:
            if save:
                try: self.save_settings()
                except Exception: pass
            return
        if getattr(self, "_fs_window", None) is not None:
            self.exit_fullscreen()
        try:
            pos = self.player.position()
            playing = (self.player.playbackState()
                       == QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            pos, playing = 0, False
        # Гасим текущий показ субтитров и окно-оверлей (если было).
        self._hide_sub_display()
        if self.sub_overlay is not None:
            try: self.sub_overlay.close(); self.sub_overlay.deleteLater()
            except Exception: pass
            self.sub_overlay = None
        # Меняем виджет видео в layout.
        old = self.video_widget
        try: self.vc_layout.removeWidget(old)
        except Exception: pass
        try: self.player.setVideoOutput(None)
        except Exception: pass
        self._subs_in_frame = in_frame
        self._build_video_output()
        try:
            self.vc_layout.insertWidget(0, self.video_widget, 0,
                                        Qt.AlignmentFlag.AlignCenter)
        except Exception:
            pass
        try: old.setParent(None); old.deleteLater()
        except Exception: pass
        self._adjust_video_height()
        try:
            self.player.setPosition(pos)
            if playing: self.player.play()
        except Exception:
            pass
        # Перенастраиваем показ текущей дорожки субтитров.
        if self._sub_use_overlay or self._sub_use_ass:
            self._prepare_sub_display()
            try: self._update_subtitle(pos / 1000.0)
            except Exception: pass
        if save:
            try: self.save_settings()
            except Exception: pass

    def _prepare_sub_display(self):
        """Готовит цель для показа субтитров: окно-оверлей (overlay-режим) либо
        ничего (frame-режим — рисует сам холст)."""
        if self._subs_in_frame:
            return
        self._ensure_overlay()
        self._position_overlay()

    def _hide_sub_display(self):
        """Сбрасывает показанные субтитры в текущей цели."""
        if self._subs_in_frame:
            vw = self.video_widget
            if isinstance(vw, VideoCanvas):
                vw.clear_subtitle()
        else:
            ov = self.sub_overlay
            if ov is not None:
                ov.clear_subtitle(); ov.hide()

    def _adjust_video_height(self):
        """Подгоняет окно видео ровно под аспект кадра (без чёрных полей внутри
        QVideoWidget), вписывая его в доступную область. «Максимум 16:9»: если
        кадр шире 16:9, бокс не растягивается выше этого соотношения по высоте."""
        # В полноэкранном режиме видео живёт в отдельном окне — не навязываем ему
        # фиксированный размер контейнера вкладки.
        if getattr(self, "_fs_window", None) is not None:
            return
        try:
            cont = getattr(self, "video_container", None)
            cw = cont.width() if cont is not None else self.video_widget.width()
            ch = cont.height() if cont is not None else int(self.height() * 0.55)
            if cw <= 0:
                cw = max(320, int(self.width() * 0.55))
            if ch <= 0:
                ch = max(180, int(self.height() * 0.55))
            # Кадр не должен занимать слишком много по высоте на больших окнах.
            ch = min(ch, int(self.height() * 0.62)) or ch
            aspect = self.video_aspect if (self.video_aspect and self.video_aspect > 0) else (16.0 / 9.0)
            # «Не более 16:9»: ограничиваем минимальный аспект (для очень узких
            # вертикалок бокс не становится чрезмерно высоким — режется по ch).
            fit_w = cw
            fit_h = int(round(fit_w / aspect))
            if fit_h > ch:
                fit_h = ch
                fit_w = int(round(fit_h * aspect))
            fit_w = max(80, min(fit_w, cw))
            fit_h = max(60, min(fit_h, ch))
            self.video_widget.setMinimumSize(fit_w, fit_h)
            self.video_widget.setMaximumSize(fit_w, fit_h)
            # Оверлей субтитров подгоняем под экранную область видео.
            self._position_overlay()
        except Exception:
            pass

    # ── Resize ────────────────────────────────────────────────────────────
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._ready:
            self._adjust_video_height()

    def showEvent(self, ev):
        super().showEvent(ev)
        # Вкладку показали (вернулись на «Монтаж») — вернуть оверлей субтитров.
        QTimer.singleShot(0, self._position_overlay)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        # Ушли с вкладки — прячем оверлей-окно, чтобы оно не висело поверх других.
        ov = getattr(self, "sub_overlay", None)
        if ov is not None:
            ov.hide()

    def _adjust_video_aspect_once(self):
        self._adjust_video_height()

    # ── Drag & Drop ───────────────────────────────────────────────────────
    def enable_global_drag_drop(self):
        for w in self.findChildren(QWidget):
            try:
                w.setAcceptDrops(True)
                w.installEventFilter(self)
            except Exception:
                pass
        self.installEventFilter(self)

    def eventFilter(self, watched, event):
        # Колесо мыши НЕ меняет значения полей (спинбоксы кадров, комбобоксы
        # дорожек/режима, ползунки громкости/позиции) — частая причина случайных
        # изменений. Виджет волны (WaveformWidget) не входит в эти типы → его
        # зум колесом сохраняется.
        # Шкала уровня звука изменила высоту → пересчёт размера кнопок (ровно 8).
        if (event.type() == QEvent.Type.Resize
                and watched is getattr(self, "audio_meter", None)):
            self._resize_montage_side_btns(watched.height())
        if event.type() == QEvent.Type.Wheel and isinstance(
                watched, (QSpinBox, QComboBox, QSlider)):
            # Виджеты с пометкой wheelAlways (ползунок громкости) — колесо меняет
            # значение ВСЕГДА: пропускаем событие к их собственному wheelEvent.
            if watched.property("wheelAlways"):
                return False
            return True
        # Двойной клик по видео → переключение полноэкранного режима.
        if (event.type() == QEvent.Type.MouseButtonDblClick
                and watched is self.video_widget):
            self.toggle_fullscreen()
            return True
        # Главное окно подвинули/изменили → ведём за ним оверлей субтитров.
        if (watched is self._overlay_win
                and event.type() in (QEvent.Type.Move, QEvent.Type.Resize,
                                     QEvent.Type.WindowStateChange)):
            self._position_overlay()
        if event.type() == QEvent.Type.DragEnter:
            md = event.mimeData()
            if md.hasUrls() or md.hasText():
                event.acceptProposedAction(); return True
        if event.type() == QEvent.Type.DragMove:
            md = event.mimeData()
            if md.hasUrls() or md.hasText():
                event.acceptProposedAction(); return True
        if event.type() == QEvent.Type.Drop:
            md = event.mimeData(); loaded = False
            try:
                urls = md.urls()
                if urls:
                    local = urls[0].toLocalFile()
                    if local and os.path.exists(local):
                        self.load_file(local); loaded = True
            except Exception:
                pass
            if not loaded:
                try:
                    txt = md.text()
                    if txt:
                        path = txt.strip()
                        if os.path.exists(path):
                            self.load_file(path); loaded = True
                except Exception:
                    pass
            if loaded:
                event.acceptProposedAction()
                return True
        return super().eventFilter(watched, event)

    # ── Папка экспорта ──────────────────────────────────────────────────────
    def _choose_export_dir(self):
        start = self.export_dir or (str(self.actual_source_file.parent)
                                    if self.actual_source_file else "")
        d = QFileDialog.getExistingDirectory(self, "Папка для сохранения обрезки", start)
        if d:
            self.export_dir = d
            self._update_export_dir_label()
            self.save_settings()

    def _reset_export_dir(self):
        self.export_dir = ""
        self._update_export_dir_label()
        self.save_settings()

    def _update_export_dir_label(self):
        lbl = getattr(self, "lbl_export_dir", None)
        if lbl is None:
            return
        if self.export_dir and os.path.isdir(self.export_dir):
            # Укорачиваем путь в середине, чтобы он не распирал панель; полный
            # путь — в подсказке.
            fm = QFontMetrics(lbl.font())
            elided = fm.elidedText(self.export_dir, Qt.TextElideMode.ElideMiddle, 210)
            lbl.setText(elided)
            lbl.setToolTip(self.export_dir)
        else:
            lbl.setText("Рядом с исходником")
            lbl.setToolTip("Файл сохраняется в папке исходника")

    # ── Аудио/субтитры: дорожки ─────────────────────────────────────────────
    @staticmethod
    def _fmt_bitrate(ainfo):
        raw = (ainfo or {}).get('bit_rate')
        if not raw:
            # Контейнеры mkvmerge (MKV) не пишут bit_rate в поток, а кладут его в
            # тег статистики — обычно «BPS-eng» (язык в суффиксе), реже «BPS».
            # Берём первый тег, чьё имя начинается на BPS (без учёта регистра).
            tags = (ainfo or {}).get('tags', {}) or {}
            raw = tags.get('BPS') or tags.get('BPS-eng')
            if not raw:
                for k, v in tags.items():
                    if k.upper().startswith('BPS'):
                        raw = v
                        break
        try:
            return f"{round(int(raw) / 1000)} кбит/с"
        except Exception:
            return "—"

    @staticmethod
    def _track_label(s, i, kind):
        tags = s.get('tags', {}) or {}
        lang = tags.get('language') or tags.get('LANGUAGE') or ''
        title = tags.get('title') or tags.get('TITLE') or ''
        codec = (s.get('codec_name') or '').upper()
        parts = [f"{i + 1}."]
        if lang: parts.append(lang)
        if title: parts.append(title[:18])
        if codec and not title: parts.append(codec)
        return " ".join(parts) or f"Дорожка {i + 1}"

    def _populate_track_combos(self):
        self._loading_tracks = True
        # Новый файл → сбрасываем оверлей субтитров от предыдущего (combo
        # переустанавливается на «Выкл», но on_sub_track_changed под флагом молчит).
        self._stop_sub_extractor()
        self._stop_ass()
        self._sub_cues = []
        self._sub_use_overlay = False
        self._hide_sub_display()
        try:
            # ── Аудио: встроенные дорожки + внешние файлы (озвучка) ──
            self.cmb_audio.clear()
            self._audio_entries = []
            for i, s in enumerate(self._audio_streams):
                self.cmb_audio.addItem(self._track_label(s, i, "Аудио"))
                self._audio_entries.append(('emb', i))
            for p in self._audio_ext:
                self.cmb_audio.addItem(get_icon('fa5s.file'), os.path.basename(p))
                self._audio_entries.append(('ext', p))
            if not self._audio_entries:
                self.cmb_audio.addItem("— нет —")
            self.cmb_audio.setEnabled(len(self._audio_entries) > 1)

            # ── Субтитры: «Выкл» + встроенные + внешние файлы ──
            self.cmb_subs.clear()
            self.cmb_subs.addItem("Выкл")
            self._sub_entries = []
            for i, s in enumerate(self._sub_streams):
                self.cmb_subs.addItem(self._track_label(s, i, "Субтитры"))
                self._sub_entries.append(('emb', i))
            for p in self._sub_ext:
                self.cmb_subs.addItem(get_icon('fa5s.file'), os.path.basename(p))
                self._sub_entries.append(('ext', p))
            self.cmb_subs.setEnabled(len(self._sub_entries) > 0)
        finally:
            self._loading_tracks = False
        self.selected_audio_abs_index = (
            self._audio_streams[0].get('index') if self._audio_streams else None)
        self.selected_audio_ext_path = None
        self.selected_sub_ext_path = None
        self._clear_external_audio()

    def on_audio_track_changed(self, idx):
        if self._loading_tracks or idx < 0 or idx >= len(self._audio_entries):
            return
        kind, ref = self._audio_entries[idx]
        if kind == 'emb':
            # Встроенная дорожка → возвращаем звук видео, гасим внешнюю озвучку.
            self.selected_audio_ext_path = None
            self._clear_external_audio()
            st = self._audio_streams[ref]
            self.selected_audio_abs_index = st.get('index')
            try:
                self.player.setActiveAudioTrack(ref)
            except Exception:
                pass
            # Инфо-метки (кодек/каналы/битрейт) и аудиоволна — под новую дорожку.
            self._update_audio_info_labels(st)
            self._start_waveform(self.actual_source_file, st.get('index'))
        else:
            # Внешний файл озвучки → играет отдельный синхронный плеер.
            self.selected_audio_abs_index = None
            self.selected_audio_ext_path = ref
            self._set_external_audio(ref)
            self._update_audio_info_labels(self._probe_audio_stream(ref))
            # Волну строим из самого файла озвучки (единственная дорожка).
            self._start_waveform(ref, None)

    def _update_audio_info_labels(self, ainfo):
        """Обновляет метки «кодек/каналы» и «битрейт» под выбранную аудиодорожку
        (встроенную или внешний файл озвучки)."""
        if ainfo:
            codec_a = (ainfo.get('codec_name') or '?').upper()
            self.lbl_astream.setText(f"{codec_a} {_fmt_channels(ainfo)}")
            self.lbl_abitrate.setText(self._fmt_bitrate(ainfo))
        else:
            self.lbl_astream.setText("—")
            self.lbl_abitrate.setText("—")

    def _probe_audio_stream(self, path):
        """Возвращает первую аудиодорожку внешнего файла озвучки (для инфо-меток).
        Лёгкий ffprobe; при ошибке — None (метки покажут «—»)."""
        try:
            cmd = [FFPROBE, "-v", "error", "-select_streams", "a:0",
                   "-show_entries", "stream=codec_name,channels,bit_rate,"
                   "channel_layout:stream_tags=BPS,BPS-eng",
                   "-of", "json", str(path)]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=CREATE_NO_WINDOW, timeout=15)
            if r.returncode == 0:
                data = json.loads(r.stdout or "{}")
                streams = data.get('streams') or []
                if streams:
                    return streams[0]
        except Exception:
            pass
        return None

    # ── Внешняя озвучка (отдельный аудиофайл, синхронный с видео) ──────────────
    _SUB_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.sub')
    _AUDIO_EXTS = ('.mp3', '.aac', '.m4a', '.ac3', '.eac3', '.flac', '.wav',
                   '.opus', '.ogg', '.dts', '.mka', '.wma')

    def _ensure_ext_audio_player(self):
        if self._ext_audio_player is None:
            self._ext_audio_player = QMediaPlayer()
            self._ext_audio_output = QAudioOutput()
            self._ext_audio_player.setAudioOutput(self._ext_audio_output)
            self._ext_audio_player.mediaStatusChanged.connect(
                self._on_ext_audio_status)
        return self._ext_audio_player

    def _set_external_audio(self, path):
        if not path or not os.path.exists(path):
            return
        p = self._ensure_ext_audio_player()
        try:
            self.audio_output.setMuted(True)   # глушим звук видео
        except Exception:
            pass
        try:
            self._ext_audio_output.setVolume(self.vol_slider.value() / 100.0)
        except Exception:
            pass
        self._ext_audio_active = True
        p.setSource(QUrl.fromLocalFile(str(path)))
        # Точную синхронизацию делаем по событию загрузки (_on_ext_audio_status).

    def _on_ext_audio_status(self, status):
        if not self._ext_audio_active or self._ext_audio_player is None:
            return
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                      QMediaPlayer.MediaStatus.BufferedMedia):
            try:
                self._ext_audio_player.setPosition(self.player.position())
                if (self.player.playbackState()
                        == QMediaPlayer.PlaybackState.PlayingState):
                    self._ext_audio_player.play()
                else:
                    self._ext_audio_player.pause()
            except Exception:
                pass

    def _ext_audio_seek(self, ms):
        if self._ext_audio_active and self._ext_audio_player is not None:
            try:
                self._ext_audio_player.setPosition(int(max(0, ms)))
            except Exception:
                pass

    def _ext_audio_set_state(self, playing):
        if not self._ext_audio_active or self._ext_audio_player is None:
            return
        try:
            self._ext_audio_player.setPosition(self.player.position())
            if playing:
                self._ext_audio_player.play()
            else:
                self._ext_audio_player.pause()
        except Exception:
            pass

    def _clear_external_audio(self):
        if not getattr(self, "_ext_audio_active", False):
            return
        self._ext_audio_active = False
        p = self._ext_audio_player
        if p is not None:
            try: p.pause()
            except Exception: pass
            try: p.setSource(QUrl())
            except Exception: pass
        try:
            self.audio_output.setMuted(False)
        except Exception:
            pass

    def _scan_external_subs(self, src):
        """Ищет внешние файлы субтитров рядом с видео и в подпапках (до 3 уровней)."""
        found = []
        try:
            base = os.path.dirname(str(src))
            if not base or not os.path.isdir(base):
                return []
            for root, dirs, files in os.walk(base):
                depth = root[len(base):].count(os.sep)
                if depth >= 3:
                    dirs[:] = []
                for fn in files:
                    if os.path.splitext(fn)[1].lower() in self._SUB_EXTS:
                        found.append(os.path.join(root, fn))
                        if len(found) >= 200:
                            return self._sort_external_subs(found, src)
        except Exception:
            pass
        return self._sort_external_subs(found, src)

    @staticmethod
    def _sort_external_subs(paths, src):
        stem = os.path.splitext(os.path.basename(str(src)))[0].lower()

        def key(p):
            name = os.path.splitext(os.path.basename(p))[0].lower()
            match = 0 if (stem and (stem in name or name in stem)) else 1
            return (match, os.path.basename(p).lower())

        return sorted(dict.fromkeys(paths), key=key)

    # ── Кнопки «найти» (внешние аудио/субтитры с ПК) ──────────────────────────
    def find_external_subs(self):
        if not self.actual_source_file:
            return
        start = str(self.actual_source_file.parent)
        fname, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл субтитров", start,
            "Субтитры (*.srt *.ass *.ssa *.vtt *.sub);;Все файлы (*)")
        if fname:
            self._add_external_sub(os.path.normpath(fname))

    def find_external_audio(self):
        if not self.actual_source_file:
            return
        start = str(self.actual_source_file.parent)
        fname, _ = QFileDialog.getOpenFileName(
            self, "Выбрать аудиофайл (озвучку)", start,
            "Аудио (*.mp3 *.aac *.m4a *.ac3 *.eac3 *.flac *.wav *.opus *.ogg "
            "*.dts *.mka *.wma);;Все файлы (*)")
        if fname:
            self._add_external_audio(os.path.normpath(fname))

    def _add_external_sub(self, path):
        target = ('ext', path)
        if path not in self._sub_ext:
            self._sub_ext.append(path)
            self._loading_tracks = True
            self._sub_entries.append(target)
            self.cmb_subs.addItem(get_icon('fa5s.file'), os.path.basename(path))
            self.cmb_subs.setEnabled(True)
            self._loading_tracks = False
        try:
            idx = self._sub_entries.index(target) + 1   # +1: пункт 0 = «Выкл»
        except ValueError:
            return
        if self.cmb_subs.currentIndex() == idx:
            self.on_sub_track_changed(idx)
        else:
            self.cmb_subs.setCurrentIndex(idx)

    # ── Правка текста субтитров ──────────────────────────────────────────────
    @staticmethod
    def _cues_to_srt(cues):
        def _ts(t):
            if t < 0:
                t = 0.0
            h = int(t // 3600); m = int((t % 3600) // 60); s = t - h * 3600 - m * 60
            return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')
        out = []
        for i, (start, end, body) in enumerate(cues, 1):
            out.append(str(i))
            out.append(f"{_ts(start)} --> {_ts(end)}")
            out.append(body)
            out.append("")
        return "\n".join(out)

    def _current_subs_as_srt(self):
        """Текст активной дорожки субтитров в виде SRT для редактора. Если cues уже
        разобраны (текстовая дорожка) — берём их; иначе (ASS/ещё грузится) —
        извлекаем SRT из источника синхронно. None — текст недоступен (битмап)."""
        if getattr(self, "_sub_cues", None):
            return self._cues_to_srt(self._sub_cues)
        src = getattr(self, "_cur_sub_src", None)
        idx = getattr(self, "_cur_sub_index", -1)
        if getattr(self, "selected_sub_ext_path", None):
            src = self.selected_sub_ext_path; idx = 0
        if not src or idx is None or idx < 0:
            return None
        tmp = None
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
            tmp = tf.name; tf.close()
            cmd = [FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{idx}", tmp]
            kw = {'creationflags': CREATE_NO_WINDOW} if os.name == 'nt' else {}
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60, **kw)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
        except Exception:
            return None
        finally:
            if tmp:
                try: os.remove(tmp)
                except Exception: pass
        return None

    def edit_subtitles(self):
        if self.cmb_subs.currentIndex() <= 0:
            QMessageBox.information(self, "Субтитры",
                                    "Сначала выберите дорожку субтитров.")
            return
        srt = self._current_subs_as_srt()
        if not srt or not srt.strip():
            QMessageBox.information(
                self, "Субтитры",
                "Не удалось получить текст субтитров для редактирования "
                "(возможно, это субтитры-картинки).")
            return
        dlg = SubtitleEditDialog(srt, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_text = dlg.text()
        if not _parse_srt(new_text):
            QMessageBox.warning(self, "Субтитры",
                                "После правки не осталось ни одной реплики.")
            return
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            base = self.actual_source_file.stem if self.actual_source_file else "subs"
            path = os.path.join(CONFIG_DIR, f"{base}_edited.srt")
            n = 1
            while os.path.exists(path) and os.path.normpath(path) not in self._sub_ext:
                path = os.path.join(CONFIG_DIR, f"{base}_edited_{n}.srt"); n += 1
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_text if new_text.endswith("\n") else new_text + "\n")
        except Exception as e:
            QMessageBox.warning(self, "Субтитры", f"Не удалось сохранить: {e}")
            return
        path = os.path.normpath(path)
        # Делаем отредактированный файл активной дорожкой (превью + вшивание).
        if path in self._sub_ext:
            self._sub_cues = []
            try:
                idx = self._sub_entries.index(('ext', path)) + 1
            except ValueError:
                self._add_external_sub(path); return
            if self.cmb_subs.currentIndex() == idx:
                self.on_sub_track_changed(idx)
            else:
                self.cmb_subs.setCurrentIndex(idx)
        else:
            self._add_external_sub(path)

    def _add_external_audio(self, path):
        target = ('ext', path)
        if path not in self._audio_ext:
            self._audio_ext.append(path)
            self._loading_tracks = True
            # Убираем плейсхолдер «— нет —», если до этого дорожек не было.
            if not self._audio_entries:
                self.cmb_audio.clear()
            self._audio_entries.append(target)
            self.cmb_audio.addItem(get_icon('fa5s.file'), os.path.basename(path))
            self.cmb_audio.setEnabled(len(self._audio_entries) > 1)
            self._loading_tracks = False
        try:
            idx = self._audio_entries.index(target)
        except ValueError:
            return
        if self.cmb_audio.currentIndex() == idx:
            self.on_audio_track_changed(idx)
        else:
            self.cmb_audio.setCurrentIndex(idx)

    # Битмап-субтитры (картинками) свой оверлей рисовать не умеет — для них
    # оставляем встроенный рендер QtMultimedia.
    _BITMAP_SUB_CODECS = {
        'hdmv_pgs_subtitle', 'pgssub', 'dvd_subtitle', 'dvdsub',
        'dvb_subtitle', 'dvbsub', 'xsub',
    }

    def _ensure_overlay(self):
        """Лениво создаёт окно-оверлей субтитров и подписывается на Move/Resize
        верхнеуровневого окна (чтобы оверлей следовал за видео)."""
        if self.sub_overlay is None:
            self.sub_overlay = SubtitleOverlay(self.window())
            win = self.window()
            if win is not None and win is not self._overlay_win:
                try:
                    win.installEventFilter(self)
                    self._overlay_win = win
                except Exception:
                    pass
            # Подписки на состояние приложения/фокус окна — ОДИН раз за жизнь
            # вкладки (оверлей может пересоздаваться при смене метода субтитров).
            if not getattr(self, "_overlay_signals_connected", False):
                self._overlay_signals_connected = True
                # Окно поверх всех → прячем, когда приложение неактивно, чтобы текст
                # субтитров не висел поверх других программ при Alt+Tab.
                try:
                    QApplication.instance().applicationStateChanged.connect(
                        self._on_app_state_changed)
                except Exception:
                    pass
                # …и когда активно другое окно приложения (диалог настроек/консоль
                # и т.п.) — иначе субтитры висят поверх него.
                try:
                    QApplication.instance().focusWindowChanged.connect(
                        self._on_focus_window_changed)
                except Exception:
                    pass
        return self.sub_overlay

    def _on_focus_window_changed(self, *args):
        self._position_overlay()

    def _on_app_state_changed(self, state):
        if self.sub_overlay is None:
            return
        if state == Qt.ApplicationState.ApplicationActive:
            self._position_overlay()
        else:
            self.sub_overlay.hide()

    def _position_overlay(self):
        """Подгоняет окно-оверлей под текущую область видео (в окне или в
        полноэкранном режиме) и показывает/прячет его.
        В frame-режиме окна-оверлея нет — субтитры рисует сам холст; здесь лишь
        перерисовываем кадр ASS при изменении геометрии."""
        if self._subs_in_frame:
            if self._sub_use_ass and self._ass is not None:
                try: self._update_subtitle(self.player.position() / 1000.0)
                except Exception: pass
            return
        ov = self.sub_overlay
        if ov is None:
            return
        fs = getattr(self, "_fs_window", None)
        if not self._sub_use_overlay or not self.isVisible():
            ov.hide()
            return
        # Если активно другое окно приложения (диалог настроек/консоль и т.п.) —
        # прячем оверлей, чтобы субтитры не висели поверх него.
        try:
            aw = QApplication.activeWindow()
            allowed = {self.window(), fs}
            if aw is not None and aw not in allowed:
                ov.hide()
                return
        except Exception:
            pass
        target = (fs._video if (fs is not None and getattr(fs, "_video", None) is not None)
                  else self.video_widget)
        # Оверлей субтитров — отдельное окно «поверх всех»; его владельцем должно
        # быть то окно, где сейчас видео. Иначе при показе оверлея в полноэкранном
        # режиме Windows вытягивает вперёд окно-владельца (главное окно) и его GUI
        # оказывается поверх видео. Привязываем владельца к текущему окну видео.
        self._reparent_overlay(target.window())
        ov.place_over(target)
        # ASS: подгоняем разрешение рендера под размер оверлея и перерисовываем.
        if self._sub_use_ass and self._ass is not None:
            try:
                self._ass.set_frame_size(ov.width(), ov.height())
                self._update_subtitle(self.player.position() / 1000.0)
            except Exception:
                pass
        if not ov.isVisible():
            ov.show()
        ov.raise_()

    def _reparent_overlay(self, owner):
        ov = self.sub_overlay
        if ov is None or owner is None or ov.parent() is owner:
            return
        try:
            flags = ov.windowFlags()
            vis = ov.isVisible()
            ov.setParent(owner, flags)
            ov.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            ov.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            ov.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            ov.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            if vis:
                ov.show()
        except Exception:
            pass

    def on_sub_track_changed(self, idx):
        if self._loading_tracks:
            return
        self._stop_sub_extractor()
        self._stop_ass()
        self._sub_cues = []
        self._sub_use_overlay = False
        self._hide_sub_display()
        self.selected_sub_ext_path = None

        # Пункт 0 = «Выкл» → субтитры выключены.
        if idx <= 0 or (idx - 1) >= len(self._sub_entries):
            try: self.player.setActiveSubtitleTrack(-1)
            except Exception: pass
            return

        kind, ref = self._sub_entries[idx - 1]
        if kind == 'emb':
            sub_i = ref
            src = self.actual_source_file
            try:
                codec = (self._sub_streams[sub_i].get('codec_name') or '').lower()
            except Exception:
                codec = ''
        else:
            # Внешний файл субтитров: извлекаем/рендерим прямо из него (stream 0).
            self.selected_sub_ext_path = ref
            sub_i = 0
            src = ref
            codec = os.path.splitext(ref)[1].lower().lstrip('.')

        is_bitmap = codec in self._BITMAP_SUB_CODECS
        if is_bitmap or not src:
            # Битмап-дорожка (или нет источника) → встроенный рендер. Для внешних
            # файлов битмап-кодеков нет, поэтому это только встроенные дорожки.
            if kind == 'emb':
                try: self.player.setActiveSubtitleTrack(sub_i)
                except Exception: pass
            return

        # Текстовые субтитры → свой рендер; встроенный (с плашкой) гасим.
        try: self.player.setActiveSubtitleTrack(-1)
        except Exception: pass
        self._sub_use_overlay = True
        self._prepare_sub_display()
        self._sub_token += 1
        tok = self._sub_token
        # Запоминаем источник субтитров (для отката ASS→SRT в _on_ass_extracted).
        self._cur_sub_src = src
        self._cur_sub_index = sub_i

        if LIBASS_AVAILABLE and codec in ('ass', 'ssa'):
            # ASS/SSA → полный стиль и караоке через libass (рендер в фоне после
            # извлечения дорожки в .ass; при неудаче — откат на текстовый SRT).
            ex = AssExtractor(src, sub_i, tok)
            ex.done.connect(self._on_ass_extracted)
            ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                                if e in self._sub_threads else None)
            self._sub_threads.append(ex)
            self._ass_extractor = ex
            ex.start()
            return

        # Прочие текстовые дорожки (srt/mov_text/webvtt) → чистый текст-оверлей.
        ex = SubtitleExtractor(src, sub_i, tok)
        ex.done.connect(self._on_sub_cues)
        ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                            if e in self._sub_threads else None)
        self._sub_threads.append(ex)
        self._sub_extractor = ex
        ex.start()

    def _stop_sub_extractor(self):
        ex = getattr(self, "_sub_extractor", None)
        if ex is not None:
            try:
                ex.done.disconnect()
            except Exception:
                pass
            self._sub_extractor = None

    def _stop_ass(self):
        """Останавливает ASS-рендер: таймер, libass, временный .ass и картинку."""
        self._sub_use_ass = False
        ex = getattr(self, "_ass_extractor", None)
        if ex is not None:
            try: ex.done.disconnect()
            except Exception: pass
            self._ass_extractor = None
        t = getattr(self, "_ass_timer", None)
        if t is not None:
            try: t.stop()
            except Exception: pass
        if getattr(self, "_ass", None) is not None:
            try: self._ass.close()
            except Exception: pass
            self._ass = None
        if getattr(self, "_ass_path", None):
            try: os.remove(self._ass_path)
            except Exception: pass
            self._ass_path = None
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.set_subtitle_image(None)
        ov = getattr(self, "sub_overlay", None)
        if ov is not None:
            ov.set_image(None)

    def _ensure_ass_timer(self):
        if self._ass_timer is None:
            t = QTimer(self)
            t.setInterval(60)   # ~16 к/с — достаточно для плавного караоке
            t.timeout.connect(self._on_ass_tick)
            self._ass_timer = t
        if not self._ass_timer.isActive():
            self._ass_timer.start()

    def _on_ass_tick(self):
        if not self._sub_use_ass or self._ass is None:
            return
        try:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._update_subtitle(self.player.position() / 1000.0)
        except Exception:
            pass

    def _on_ass_extracted(self, token, path):
        if token != self._sub_token:
            if path:
                try: os.remove(path)
                except Exception: pass
            return
        if not path:
            # libass-извлечение не удалось → откат на текстовый SRT-оверлей.
            self._sub_use_ass = False
            src = getattr(self, "_cur_sub_src", None) or self.actual_source_file
            sub_i = getattr(self, "_cur_sub_index", -1)
            if sub_i >= 0 and src:
                ex = SubtitleExtractor(src, sub_i, token)
                ex.done.connect(self._on_sub_cues)
                ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                                    if e in self._sub_threads else None)
                self._sub_threads.append(ex)
                self._sub_extractor = ex
                ex.start()
            return
        try:
            self._ass = _libass.AssRenderer()
            if not self._ass.load_ass_file(path):
                raise RuntimeError("load_ass_file failed")
            self._ass_path = path
            self._sub_use_ass = True
            self._prepare_sub_display()
            self._ensure_ass_timer()
            self._update_subtitle(self.player.position() / 1000.0)
        except Exception:
            self._sub_use_ass = False
            if self._ass is not None:
                try: self._ass.close()
                except Exception: pass
                self._ass = None
            try: os.remove(path)
            except Exception: pass

    def _on_sub_cues(self, token, cues):
        if token != self._sub_token:
            return   # пришёл результат от уже неактуального выбора — игнорируем
        self._sub_cues = cues or []
        try:
            self._update_subtitle(self.player.position() / 1000.0)
        except Exception:
            pass

    def _subtitle_at(self, pos_s):
        for start, end, body in self._sub_cues:
            if start <= pos_s <= end:
                return body
            if start > pos_s:
                break
        return ""

    def _update_subtitle(self, pos_s):
        # Цель показа: сам холст (frame-режим) или окно-оверлей (overlay-режим).
        tgt = self.video_widget if self._subs_in_frame else self.sub_overlay
        if tgt is None or not hasattr(tgt, "set_subtitle_text"):
            return
        if self._sub_use_ass and self._ass is not None:
            try:
                w, h = tgt.subtitle_area_size()
            except Exception:
                return
            if w <= 0 or h <= 0:
                return
            try:
                self._ass.set_frame_size(w, h)
                arr, ax, ay, _changed = self._ass.render(pos_s * 1000.0)
            except Exception:
                arr = None
            if arr is None:
                tgt.clear_subtitle()
            else:
                ih, iw = int(arr.shape[0]), int(arr.shape[1])
                qimg = QImage(arr.data, iw, ih, iw * 4,
                              QImage.Format.Format_RGBA8888_Premultiplied).copy()
                tgt.set_subtitle_image(qimg, ax, ay)
            return
        if self._sub_use_overlay:
            tgt.set_subtitle_text(self._subtitle_at(pos_s))
        # Субтитры выключены — ничего не рисуем (очистка уже сделана при смене
        # дорожки через _hide_sub_display), чтобы не дёргать перерисовку.

    def _apply_active_tracks(self, *args):
        """tracksChanged: применяет выбор из комбобоксов, когда плеер обнаружил дорожки."""
        try:
            ai = self.cmb_audio.currentIndex()
            if ai is not None and ai >= 0:
                self.player.setActiveAudioTrack(ai)
        except Exception:
            pass
        try:
            si = self.cmb_subs.currentIndex()
            self.player.setActiveSubtitleTrack((si - 1) if si is not None else -1)
        except Exception:
            pass

    # ── File loading ──────────────────────────────────────────────────────
    def open_file(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, "Открыть медиа файл", "",
            "Медиа файлы (*.mp4 *.mkv *.mov *.avi *.mp3 *.aac *.wav *.flac "
            "*.png *.jpg *.jpeg *.bmp *.webp *.gif);;Все файлы (*)")
        if fname:
            self.load_file(fname)

    def clear_file(self):
        """Убирает текущий файл и возвращает редактор в исходное «пустое»
        состояние (как при запуске без файла): останавливает плеер и фоновые
        воркеры, чистит временный proxy, сбрасывает инфо/волну/тайминги."""
        # Снимок для отмены «Очистить» через Ctrl+Z: файл + текущая обрезка.
        if self.filepath:
            self._cleared_snapshot = {
                'path': str(self.filepath),
                'in': self.current_in,
                'out': self.current_out,
            }
        # Останавливаем воспроизведение.
        try:
            self.player.stop()
        except Exception:
            pass
        # Воркер волны + его временный wav.
        if self.audio_worker and self.audio_worker.isRunning():
            self.audio_worker.stop(); self.audio_worker.wait()
        if self.audio_worker:
            try:
                if self.audio_worker.tmp_wav and os.path.exists(self.audio_worker.tmp_wav):
                    os.remove(self.audio_worker.tmp_wav)
            except Exception:
                pass
            self.audio_worker = None
        # Proxy-воркер + его временный файл.
        if self.proxy_thread and self.proxy_thread.isRunning():
            self.proxy_thread.stop(); self.proxy_thread.wait()
        self.proxy_thread = None
        if self.tmp_proxy_file and os.path.exists(self.tmp_proxy_file):
            try:
                os.remove(self.tmp_proxy_file)
            except Exception:
                pass
        self.tmp_proxy_file = None
        self.is_proxy_active = False
        # Выгружаем источник из плеера.
        try:
            self.player.setSource(QUrl())
        except Exception:
            pass
        # Очищаем последний кадр на холсте (frame-режим).
        if isinstance(self.video_widget, VideoCanvas):
            self.video_widget.clear_frame()

        # Сбрасываем субтитры.
        self._stop_sub_extractor()
        self._stop_ass()
        self._sub_cues = []
        self._sub_use_overlay = False
        self._hide_sub_display()

        # Сбрасываем состояние.
        self.filepath = None
        self.actual_source_file = None
        self.duration = 0.0
        self.current_in = 0.0
        self.current_out = 0.0
        self.fps = None
        self.video_aspect = None
        self.video_stream_index = None
        self.audio_stream_index = None
        # Сбрасываем режим картинки и возвращаем подпись кнопки экспорта.
        if getattr(self, "is_still_image", False):
            try:
                self.btn_cut.setText("Обрезать")
                self.btn_cut.setIcon(get_icon('fa5s.cut', color='#1e1e2e'))
            except Exception:
                pass
        self.is_still_image = False
        self.still_image_path = None
        # Снимаем пикселизацию вместе с очисткой файла.
        self._pixelize_active = False
        _pb = getattr(self, "btn_pixelize", None)
        if _pb is not None and _pb.isChecked():
            _pb.blockSignals(True); _pb.setChecked(False); _pb.blockSignals(False)
        self._sync_pixelize_icon()
        self.selected_audio_abs_index = None
        self._clear_external_audio()
        self._audio_streams = []
        self._sub_streams = []
        self._audio_ext = []
        self._sub_ext = []
        self.selected_audio_ext_path = None
        self.selected_sub_ext_path = None
        self.undo_stack.clear(); self.redo_stack.clear()

        # Инфо-карточка → прочерки.
        for lbl in (self.lbl_duration, self.lbl_fps, self.lbl_vstream,
                    self.lbl_astream, self.lbl_abitrate):
            lbl.setText("—")

        # Подпись файла → исходный «пустой» вид (пунктирная рамка).
        self.lbl_file.setText("Нет файла")
        self.lbl_file.setToolTip("")
        self.lbl_file.setStyleSheet(f"""
            color: {C['text3']};
            font-size: 11px;
            padding: 8px;
            background: {C['surface2']};
            border: 1px dashed {C['border2']};
            border-radius: 6px;
        """)

        # Плашка proxy / строка лога.
        self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
        try:
            self.log_label.setText(""); self.log_label.setVisible(False)
        except Exception:
            pass

        # Дорожки (с пустыми списками → «— нет —» / «Выкл»).
        self._populate_track_combos()
        self._update_media_buttons()
        self._update_audio_only_placeholder()

        # Поля IN/OUT + кадры + позиция плеера.
        self.in_time_edit.setText(s_to_time(0.0))
        self.out_time_edit.setText(s_to_time(0.0))
        self._set_frame_spins(0.0, 0.0)
        lbl_cur = getattr(self, "lbl_current_time", None)
        if lbl_cur is not None:
            lbl_cur.setText(s_to_time(0.0))
        try:
            self.slider.blockSignals(True); self.slider.setValue(0); self.slider.blockSignals(False)
        except Exception:
            pass

        # Волна → пустое состояние с подсказкой «Перетащите видео…».
        self.waveform.set_data([], 0.0)
        self._update_total_time()
        self.update_selection_label()

    def accept_dropped_paths(self, paths):
        """Бросок файла на заголовок вкладки «Монтаж» (см. main.eventFilter):
        грузим первый существующий файл в редактор, как обычный drop в окно."""
        for p in (paths or []):
            if p and os.path.exists(p):
                self.load_file(p)
                break

    def load_file(self, path):
        # Останавливаем воркер волны и подчищаем его временный wav (баг #7).
        if self.audio_worker and self.audio_worker.isRunning():
            self.audio_worker.stop(); self.audio_worker.wait()
        if self.audio_worker:
            try:
                if self.audio_worker.tmp_wav and os.path.exists(self.audio_worker.tmp_wav):
                    os.remove(self.audio_worker.tmp_wav)
            except Exception:
                pass
            self.audio_worker = None

        # Останавливаем фоновый proxy-воркер ДО удаления его файла (баг #2).
        if self.proxy_thread and self.proxy_thread.isRunning():
            self.proxy_thread.stop(); self.proxy_thread.wait()
        self.proxy_thread = None

        if self.tmp_proxy_file and os.path.exists(self.tmp_proxy_file):
            try:
                os.remove(self.tmp_proxy_file)
            except Exception:
                pass
        self.tmp_proxy_file = None
        self.is_proxy_active = False
        self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)

        # Сбрасываем визуальные границы/обзор волны СРАЗУ при загрузке нового
        # файла — иначе красная/зелёная полоски (и окно обзора) оставались от
        # предыдущего файла, пока не догрузится новая волна.
        self.current_in = 0.0
        self.current_out = 0.0
        if getattr(self, "is_still_image", False):
            # Возврат к обычному медиа — восстанавливаем подпись кнопки экспорта.
            try:
                self.btn_cut.setText("Обрезать")
                self.btn_cut.setIcon(get_icon('fa5s.cut', color='#1e1e2e'))
            except Exception:
                pass
        self.is_still_image = False   # сбрасываем; _load_still_image выставит заново
        # Сбрасываем пикселизацию при загрузке ЛЮБОГО файла — эффект НЕ должен
        # тянуться с прошлого клипа (иначе следующий экспорт молча пикселит, хотя
        # на этом файле его «не включали»). Каждый файл начинается чистым.
        self._pixelize_active = False
        _pb = getattr(self, "btn_pixelize", None)
        if _pb is not None and _pb.isChecked():
            _pb.blockSignals(True); _pb.setChecked(False); _pb.blockSignals(False)
        self._sync_pixelize_icon()
        self.waveform.reset_markers()

        self.actual_source_file = Path(path)
        self.filepath = self.actual_source_file

        # Источник кадров для превью полосы воспроизведения (берём из исходника).
        try:
            if getattr(self, "seek_preview", None) is not None:
                self.seek_preview.set_source(self.actual_source_file)
        except Exception:
            pass

        # Сбрасываем внешнюю озвучку и пере-сканируем внешние субтитры рядом
        # с новым файлом (в т.ч. в подпапках). Списки используются при построении
        # комбобоксов в finish_loading_file → _populate_track_combos.
        self._clear_external_audio()
        self._audio_ext = []
        self._sub_ext = self._scan_external_subs(self.actual_source_file)

        name = self.actual_source_file.name
        if len(name) > 30:
            name = "…" + name[-27:]
        self.lbl_file.setText(f"{icon_html('fa5s.file', 14, C['text'])}  {name}")
        self.lbl_file.setToolTip(str(self.actual_source_file))
        self.lbl_file.setStyleSheet(f"""
            color: {C['text']};
            font-size: 11px;
            padding: 8px;
            background: {C['surface3']};
            border: 1px solid {C['border2']};
            border-radius: 6px;
        """)

        self.undo_stack = deque(maxlen=50); self.redo_stack = deque(maxlen=50)

        # Still-картинка (png/jpg/…) — отдельный лёгкий режим «картинка → видео»:
        # ни плеер, ни прокси, ни обрезка не применимы. Показываем кадр статично и
        # включаем только пикселизацию/кадрирование. Экспорт собирает видео из
        # картинки (-loop 1) при «Обрезать».
        _ext = os.path.splitext(str(path))[1].lower()
        if _ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"):
            self._load_still_image()
            return

        self.waveform.set_loading("Ожидание метаданных...")

        metadata = run_ffprobe(self.actual_source_file)
        if not metadata:
            QMessageBox.critical(self, "Ошибка", "Не удалось получить метаданные (ffprobe недоступен).")
            self.waveform.set_data([], 0.0)
            return

        try:
            self.duration = float(metadata.get('format', {}).get('duration', 0.0))
            self.lbl_duration.setText(s_to_time(self.duration))
        except Exception:
            self.duration = 0.0; self.lbl_duration.setText("—")
        self._update_total_time()

        vinfo = None; ainfo = None
        for s in metadata.get('streams', []):
            if s.get('codec_type') == 'video' and vinfo is None:
                vinfo = s
            if s.get('codec_type') == 'audio' and ainfo is None:
                ainfo = s

        # Все аудио- и субтитровые дорожки контейнера (для выбора в боковой панели)
        self._audio_streams = [s for s in metadata.get('streams', [])
                               if s.get('codec_type') == 'audio']
        self._sub_streams = [s for s in metadata.get('streams', [])
                             if s.get('codec_type') == 'subtitle']

        if vinfo:
            self.video_stream_index = vinfo.get('index')
            is_av1 = vinfo.get('codec_name', '').lower() == 'av1'
            self._source_is_av1 = is_av1
            scale = self._pb_quality_scale()
            # Прокси нужен если: исходник AV1 (QtMultimedia его не тянет плавно)
            # ИЛИ выбрано пониженное качество воспроизведения.
            if is_av1 or scale < 0.999:
                self.create_proxy_for_preview(vinfo, scale=scale, is_av1=is_av1); return
            self.finish_loading_file(vinfo, ainfo)
        else:
            self.finish_loading_file(None, ainfo)

    def _load_still_image(self):
        """Лёгкий режим «картинка → видео»: грузим still-картинку, показываем её
        статично на холсте и включаем только пикселизацию/кадрирование. Плеер,
        прокси, волна и обрезка видео не задействованы — экспорт собирает ролик из
        картинки (-loop 1) в _export_still_pixelize."""
        path = self.actual_source_file
        # Останавливаем плеер и снимаем источник, чтобы он не держал прошлый файл.
        try: self.player.stop()
        except Exception: pass
        try: self.player.setSource(QUrl())
        except Exception: pass

        img = QImage(str(path))
        if img.isNull():
            QMessageBox.critical(self, "Ошибка", "Не удалось открыть картинку.")
            return
        self.is_still_image = True
        self.still_image_path = Path(path)
        self._still_w, self._still_h = img.width(), img.height()
        self.video_stream_index = None     # видеопотока-для-плеера нет
        self.audio_stream_index = None
        self._audio_streams = []; self._sub_streams = []
        self._source_is_av1 = False

        # Синтетическая длительность будущего ролика (правится в диалоге пикселизации).
        self.duration = float(self._still_duration)
        self.current_in = 0.0
        self.current_out = self.duration
        try:
            self.lbl_duration.setText(s_to_time(self.duration))
            self._update_total_time()
        except Exception:
            pass

        # Показываем картинку статично; волну заменяем подсказкой.
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.set_static_image(img)
        try:
            self.waveform.set_data([], 0.0)
            self.waveform.set_loading(
                f"Картинка {self._still_w}×{self._still_h} — включите «Пикселизацию» "
                f"и нажмите «Обрезать», чтобы сделать видео-проявление",
                animated=False)
        except Exception:
            pass

        # Плеер для картинки не нужен — играть нечего.
        try: self.btn_play.setEnabled(False)
        except Exception: pass
        try:
            self.btn_cut.setEnabled(True)
            self.btn_cut.setText("Создать видео")
            self.btn_cut.setIcon(get_icon('fa5s.film', color='#1e1e2e'))
        except Exception:
            pass
        self._report_progress(0, "")
        self.log_label.setText(
            icon_html('fa5s.image', 12, C['text2'])
            + " Картинка загружена — включите «Пикселизацию»")
        self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
        self._update_media_buttons()

    def _pb_quality_scale(self):
        """Коэффициент масштаба прокси для текущего «качества воспроизведения».
        0 → Полное (без прокси по этой причине), 1 → 1/2, 2 → 1/4."""
        try:
            return {0: 1.0, 1: 0.5, 2: 0.25}.get(self.cmb_pb_quality.currentIndex(), 1.0)
        except Exception:
            return 1.0

    def _proxy_limit_sec(self):
        """Сколько секунд исходника класть в прокси (0 = весь файл).
        Берётся из спина «Минут для прокси» в правой панели."""
        try:
            return float(self.spin_proxy_min.value()) * 60.0
        except Exception:
            return 0.0

    def create_proxy_for_preview(self, vinfo, scale=1.0, is_av1=False):
        if scale < 0.999 and is_av1:
            self.log_label.setText("Подготовка превью (AV1, пониженное качество)...")
        elif scale < 0.999:
            self.log_label.setText("Подготовка превью (пониженное качество)...")
        else:
            self.log_label.setText("Подготовка AV1...")
        self._report_progress(0, "Подготовка превью…")
        self.btn_play.setEnabled(False); self.btn_cut.setEnabled(False)
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        tf.close(); self.tmp_proxy_file = tf.name
        self.proxy_thread = ProxyWorker(self.actual_source_file, self.tmp_proxy_file,
                                        scale=scale, duration=getattr(self, 'duration', 0.0),
                                        limit_sec=self._proxy_limit_sec())
        self._proxy_is_av1 = is_av1; self._proxy_scale = scale
        self._proxy_partial = self._proxy_limit_sec() > 0
        # Проценты создания прокси — в волну, рядом с «Ожидание метаданных…»
        # (так же, как «Извлечение аудио… N%» для H.264).
        self.proxy_thread.progress.connect(self.waveform.set_loading)
        self.proxy_thread.finished.connect(lambda s, m, o: self.on_proxy_ready(s, m, o, vinfo))
        self.proxy_thread.start()

    def on_proxy_ready(self, success, msg, output_path, vinfo):
        self.btn_play.setEnabled(True); self.btn_cut.setEnabled(True)
        self._report_progress(100); self.log_label.setText("Готово")
        # Файл очистили, пока строился прокси — не оживляем UI удалённым файлом.
        if self.actual_source_file is None:
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            return

        def _first_audio(meta):
            for s in (meta or {}).get('streams', []):
                if s.get('codec_type') == 'audio':
                    return s
            return None

        if success:
            self.is_proxy_active = True
            self.filepath = Path(output_path)
            scale = getattr(self, '_proxy_scale', 1.0)
            is_av1 = getattr(self, '_proxy_is_av1', False)
            q_txt = {0.5: " 1/2", 0.25: " 1/4"}.get(scale, "")
            if is_av1 and q_txt:
                badge = f" ПРЕВЬЮ РЕЖИМ (AV1 → H.264,{q_txt.strip()})"
            elif is_av1:
                badge = " ПРЕВЬЮ РЕЖИМ (AV1 → H.264)"
            else:
                badge = f" ПРЕВЬЮ РЕЖИМ (качество{q_txt})"
            lim = self._proxy_limit_sec()
            if lim > 0:
                badge += f" · первые {int(round(lim / 60))} мин"
            self.lbl_proxy.setText(icon_html('fa5s.bolt', 13, C['yellow']) + badge)
            self.lbl_proxy.setVisible(True)
            ainfo = _first_audio(run_ffprobe(self.filepath))
        else:
            if msg != "Отменено":
                QMessageBox.warning(self, "Ошибка прокси", f"Не удалось создать превью: {msg}")
            ainfo = _first_audio(run_ffprobe(self.actual_source_file))
        self.finish_loading_file(vinfo, ainfo)

    def _on_pb_quality_changed(self, _idx=None):
        """Смена «качества воспроизведения» на лету: пересобираем прокси (или
        возвращаемся к оригиналу), сохраняя позицию и состояние плеера. На экспорт
        не влияет — он всегда из self.actual_source_file."""
        src = self.actual_source_file
        if not src or not os.path.exists(str(src)):
            return
        if getattr(self, 'video_stream_index', None) is None:
            return  # без видеодорожки качество воспроизведения не применимо
        # Если прокси уже строится — отменяем, начнём заново с новым качеством.
        if self.proxy_thread and self.proxy_thread.isRunning():
            self.proxy_thread.stop(); self.proxy_thread.wait()
        try: pos = int(self.player.position())
        except Exception: pos = 0
        try:
            was_playing = (self.player.playbackState()
                           == QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            was_playing = False
        self._pb_restore = (pos, was_playing)

        scale = self._pb_quality_scale()
        is_av1 = bool(getattr(self, '_source_is_av1', False))
        need_proxy = is_av1 or scale < 0.999

        # Освобождаем плеер от старого прокси-файла (иначе Windows его не отдаст),
        # затем удаляем временный файл.
        try: self.player.stop()
        except Exception: pass
        try: self.player.setSource(QUrl())
        except Exception: pass
        old_proxy = self.tmp_proxy_file
        self.tmp_proxy_file = None
        self.is_proxy_active = False
        if old_proxy and os.path.exists(old_proxy):
            try: os.remove(old_proxy)
            except Exception: pass

        if need_proxy:
            self.log_label.setText("Смена качества предпросмотра…")
            self._report_progress(0, "Качество предпросмотра…")
            self.btn_play.setEnabled(False); self.btn_cut.setEnabled(False)
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4"); tf.close()
            self.tmp_proxy_file = tf.name
            self._proxy_is_av1 = is_av1; self._proxy_scale = scale
            self.proxy_thread = ProxyWorker(src, self.tmp_proxy_file, scale=scale,
                                            duration=getattr(self, 'duration', 0.0),
                                            limit_sec=self._proxy_limit_sec())
            self._proxy_partial = self._proxy_limit_sec() > 0
            # Здесь волна уже заполнена — set_loading её стёр бы; показываем
            # прогресс создания прокси в строке лога И в общем прогрессбаре окна.
            self.proxy_thread.progress.connect(self._on_pb_proxy_progress)
            self.proxy_thread.finished.connect(self._on_pb_proxy_ready)
            self.proxy_thread.start()
        else:
            # Полное качество и не-AV1 → играем оригинал.
            self._proxy_partial = False
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            self._swap_player_source(src)

    def _on_pb_proxy_progress(self, text):
        """Прогресс пересборки прокси при смене версии качества: пишем и в строку
        лога, и в общий прогрессбар окна (вытаскиваем проценты из «…N%»)."""
        self.log_label.setText(text)
        pct = None
        if '%' in text:
            try:
                pct = int(text.rsplit('%', 1)[0].split()[-1])
            except Exception:
                pct = None
        self._report_progress(pct if pct is not None else -1,
                              text or "Создание превью…")

    def _on_pb_proxy_ready(self, success, msg, output_path):
        self.btn_play.setEnabled(True); self.btn_cut.setEnabled(True)
        self._report_progress(100); self.log_label.setText("Готово")
        # Источник могли очистить, пока строился прокси (его finished-слот в этом
        # случае приходит уже после очистки) — показывать/переключать нечего.
        if self.actual_source_file is None:
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            return
        if success and output_path and os.path.exists(output_path):
            self.is_proxy_active = True
            scale = getattr(self, '_proxy_scale', 1.0)
            is_av1 = getattr(self, '_proxy_is_av1', False)
            q_txt = {0.5: "1/2", 0.25: "1/4"}.get(scale, "")
            if is_av1 and q_txt:
                badge = f" ПРЕВЬЮ РЕЖИМ (AV1 → H.264, {q_txt})"
            elif is_av1:
                badge = " ПРЕВЬЮ РЕЖИМ (AV1 → H.264)"
            else:
                badge = f" ПРЕВЬЮ РЕЖИМ (качество {q_txt})"
            lim = self._proxy_limit_sec()
            if lim > 0:
                badge += f" · первые {int(round(lim / 60))} мин"
            self.lbl_proxy.setText(icon_html('fa5s.bolt', 13, C['yellow']) + badge)
            self.lbl_proxy.setVisible(True)
            self._swap_player_source(output_path)
        else:
            if msg != "Отменено":
                QMessageBox.warning(self, "Ошибка прокси",
                                    f"Не удалось создать превью: {msg}")
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            self._swap_player_source(self.actual_source_file)

    def _swap_player_source(self, path):
        """Переключает источник плеера, сохраняя позицию/состояние из _pb_restore
        (применяются после загрузки медиа в on_media_status_changed)."""
        if path is None:
            return  # файл очистили — переключать нечего
        self.filepath = Path(path)
        self._pending_pb_seek = getattr(self, '_pb_restore', None)
        self._set_player_file(path)

    def _set_player_file(self, path):
        """Грузит файл в плеер через девайс с FILE_SHARE_DELETE — тогда исходник
        можно удалить из Проводника прямо во время монтажа (плеер его не держит
        намертво). Если девайс открыть не удалось — обычная загрузка по URL."""
        path = str(path)
        old = getattr(self, '_play_device', None)
        dev = ShareDeleteIODevice(path)
        opened = False
        try:
            opened = dev.open()
        except Exception:
            opened = False
        try:
            if opened:
                self._play_device = dev
                self.player.setSourceDevice(dev, QUrl.fromLocalFile(path))
            else:
                self._play_device = None
                self.player.setSource(QUrl.fromLocalFile(path))
        except Exception:
            self._play_device = None
            try:
                self.player.setSource(QUrl.fromLocalFile(path))
            except Exception:
                pass
        # Старый девайс закрываем чуть позже — плеер уже переключился на новый.
        if old is not None and old is not dev:
            QTimer.singleShot(0, lambda d=old: self._close_play_device(d))

    def _close_play_device(self, dev):
        try:
            dev.close()
        except Exception:
            pass

    def finish_loading_file(self, vinfo, ainfo):
        if vinfo:
            r = vinfo.get('r_frame_rate') or vinfo.get('avg_frame_rate') or "0/1"
            try:
                num, den = r.split('/')
                fps = float(num) / float(den) if float(den) != 0 else 0.0
                self.fps = fps if fps > 0 else None
            except Exception:
                self.fps = None
            w = vinfo.get('width', '?'); h = vinfo.get('height', '?')
            codec = vinfo.get('codec_name', '?').upper()
            self.lbl_vstream.setText(f"{codec} {w}×{h}")
            try:
                wv = int(vinfo.get('width') or 0); hv = int(vinfo.get('height') or 0)
                self.video_aspect = (wv / hv) if (wv > 0 and hv > 0) else None
            except Exception:
                self.video_aspect = None
        else:
            self.video_stream_index = None; self.fps = None
            self.video_aspect = None
            self.lbl_vstream.setText("—")

        if ainfo:
            self.audio_stream_index = ainfo.get('index')
            codec_a = ainfo.get('codec_name', '?').upper()
            self.lbl_astream.setText(f"{codec_a} {_fmt_channels(ainfo)}")
            self.lbl_abitrate.setText(self._fmt_bitrate(ainfo))
        else:
            self.audio_stream_index = None
            self.lbl_astream.setText("—")
            self.lbl_abitrate.setText("—")

        self._populate_track_combos()
        self._update_media_buttons()
        self._update_audio_only_placeholder()
        self.lbl_fps.setText(format_fps(self.fps))

        self.undo_stack.clear(); self.redo_stack.clear()
        self.current_in = 0.0; self.current_out = max(0.001, self.duration)
        self.set_in_out(0.0, self.current_out, skip_undo=True)

        # Новый файл — сбрасываем зум/панораму превью (если активен холст-режим).
        if isinstance(self.video_widget, VideoCanvas):
            self.video_widget.reset_view()

        self._set_player_file(self.filepath)
        self.player.setPosition(0); self.player.pause()

        self.start_waveform_loading()
        QTimer.singleShot(50, self._adjust_video_aspect_once)
        self.update_selection_label(); self.update_pan_slider_values()
        # После загрузки файла (в т.ч. через drag&drop) забираем фокус клавиатуры
        # на вкладку, чтобы Пробел/I/O/←→ работали сразу — без клика по видео.
        # singleShot(0): после того, как плеер/видеовиджет отработают своё событие.
        QTimer.singleShot(0, self._grab_kbd_focus)
        # Прогреваем отдельный плеер скраб-звука заранее (источник — оригинал).
        # Без прогрева ПЕРВЫЕ покадровые шаги часто шли без звука: плеер ещё
        # догружал медиа (а у AV1+Opus оригинала открытие/перемотка не мгновенны)
        # — отсюда баг «при av1 прокси звук при шаге по кадру появляется не всегда».
        QTimer.singleShot(0, self._prime_scrub_audio)

    def _prime_scrub_audio(self):
        """Заранее создаёт и подгружает плеер скраб-звука, чтобы первые блипы при
        покадровом шаге уже звучали (AV1+Opus оригинал открывается не мгновенно).
        Только подгрузка медиа — без воспроизведения (тишина при загрузке файла)."""
        if not getattr(self, "_scrub_audio_enabled", True):
            return
        try:
            self._ensure_scrub_audio_player()
        except Exception:
            pass

    def _grab_kbd_focus(self):
        """Ставит фокус клавиатуры на вкладку «Монтаж». Хоткеи привязаны к ней с
        контекстом WidgetWithChildren — без фокуса на вкладке (или её потомке)
        Пробел и прочие не срабатывают, пока пользователь не кликнет по видео."""
        try:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass

    def start_waveform_loading(self):
        a_idx = self.audio_stream_index if not self.is_proxy_active else None
        self._start_waveform(self.filepath, a_idx)

    def _start_waveform(self, filepath, audio_index):
        """Запускает (или перезапускает) построение аудиоволны для конкретного
        файла и индекса дорожки. Используется и при загрузке файла, и при смене
        озвучки — тогда волна перестраивается под новую дорожку."""
        if not filepath:
            return
        # Снимаем предыдущий воркер, чтобы две волны не гонялись наперегонки
        # (иначе в виджет прилетела бы волна старой дорожки последней).
        if self.audio_worker and self.audio_worker.isRunning():
            try:
                self.audio_worker.stop(); self.audio_worker.wait()
            except Exception:
                pass
        self.waveform.set_loading("Загрузка волны...")
        self.audio_worker = AudioWaveformLoader(str(filepath), audio_index,
                                                self.duration)
        self.audio_worker.finished.connect(self.on_waveform_ready)
        self.audio_worker.progress.connect(self.waveform.set_loading)
        self.audio_worker.start()

    def on_waveform_ready(self, samples, duration, left=None, right=None):
        use_duration = self.duration if (self.duration and self.duration > 0) else duration
        if duration > 0 and use_duration < (duration - 0.05):
            use_duration = duration
        # Длительность из контейнера могла не определиться (format.duration пуст) —
        # тогда current_out осталась ~0.001, зона воспроизведения вырождена: плеер
        # сразу упирается в OUT (видео «не играется»), а в начале таймлайна слипаются
        # маркеры IN/OUT. Берём длительность из аудиоволны и раскрываем зону на всё.
        if use_duration > 0 and (self.duration <= 0 or self.current_out <= 0.002
                                 or (self.current_out - self.current_in) < 0.003):
            self.duration = use_duration
            self.lbl_duration.setText(s_to_time(self.duration))
            self.current_in = 0.0
            self.current_out = use_duration
        self._update_total_time()
        self.waveform.set_data(samples, use_duration, left, right)
        # Восстанавливаем выделение пользователя после загрузки волны
        # (waveform.set_in_out пошлёт selectionChanged → синхронизация полей/кадров).
        self.waveform.set_in_out(self.current_in, self.current_out)
        self.update_pan_slider_values()
        # Восстановление обрезки после отмены «Очистить» (Ctrl+Z) — применяем
        # ПОСЛЕ того, как длительность/волна устаканились (иначе перезатёрлась бы).
        pend = getattr(self, "_pending_restore_in_out", None)
        if pend is not None:
            self._pending_restore_in_out = None
            self.set_in_out(pend[0], pend[1], skip_undo=True)

    # ── Undo / Redo ───────────────────────────────────────────────────────
    def push_undo(self):
        state = (self.current_in, self.current_out)
        if self.undo_stack:
            li, lo = self.undo_stack[-1]
            if abs(li - state[0]) < 0.001 and abs(lo - state[1]) < 0.001:
                return
        self.undo_stack.append(state)   # deque auto-trims at maxlen=50
        self.redo_stack.clear()

    def undo(self):
        # Отмена «Очистить»: восстанавливаем выгруженный файл и его обрезку
        # (свой undo-стек был очищен вместе с файлом).
        snap = getattr(self, "_cleared_snapshot", None)
        if snap and not self.filepath:
            self._cleared_snapshot = None
            if os.path.exists(snap['path']):
                self.load_file(snap['path'])
                self._pending_restore_in_out = (snap['in'], snap['out'])
            return
        # Пропускаем «пустые» снимки, равные текущему состоянию: они появлялись,
        # когда действие не меняло in/out (напр. «Обрезать старт/конец» по кнопке,
        # когда плейхед уже стоит на границе) — push_undo всё равно клал снимок, и
        # из-за этого первый Ctrl+Z «не срабатывал» (отменял в то же состояние,
        # визуально ничего не происходило). Откатываемся до ПЕРВОГО отличающегося.
        cur = (self.current_in, self.current_out)
        while self.undo_stack:
            prev = self.undo_stack.pop()
            if abs(prev[0] - cur[0]) > 1e-4 or abs(prev[1] - cur[1]) > 1e-4:
                self.redo_stack.append(cur)
                self.set_in_out(prev[0], prev[1], skip_undo=True)
                return
            # prev == cur — это пустой снимок, отбрасываем и ищем дальше.

    def redo(self):
        cur = (self.current_in, self.current_out)
        while self.redo_stack:
            nxt = self.redo_stack.pop()
            if abs(nxt[0] - cur[0]) > 1e-4 or abs(nxt[1] - cur[1]) > 1e-4:
                self.undo_stack.append(cur)
                self.set_in_out(nxt[0], nxt[1], skip_undo=True)
                return

    # ── In / Out ──────────────────────────────────────────────────────────
    def _set_frame_spins(self, in_s, out_s):
        """Обновляет спинбоксы кадров, не вызывая valueChanged (защита от рекурсии)."""
        self.in_frame_spin.blockSignals(True)
        self.out_frame_spin.blockSignals(True)
        if self.fps and self.fps > 0:
            self.in_frame_spin.setValue(int(round(in_s * self.fps)))
            self.out_frame_spin.setValue(int(round(out_s * self.fps)))
        else:
            self.in_frame_spin.setValue(0); self.out_frame_spin.setValue(0)
        self.in_frame_spin.blockSignals(False)
        self.out_frame_spin.blockSignals(False)

    def set_in_out(self, in_s, out_s, skip_undo=False, keep_view=True):
        self.current_in  = max(0.0, min(in_s,  self.duration))
        self.current_out = max(0.0, min(out_s, self.duration))
        if self.current_out <= self.current_in:
            self.current_out = min(self.duration, self.current_in + 0.001)
        self.in_time_edit.setText(s_to_time(self.current_in))
        self.out_time_edit.setText(s_to_time(self.current_out))
        self._set_frame_spins(self.current_in, self.current_out)
        # keep_view=True по умолчанию: обрезка не перематывает окно таймлайна.
        self.waveform.set_in_out(self.current_in, self.current_out, keep_view=keep_view)
        self.update_selection_label(); self.update_pan_slider_values()
        self._update_seg_duration()

    def set_in_point(self):
        self.push_undo()
        try:
            t = time_to_s(self.in_time_edit.text())
        except Exception:
            t = self.player.position() / 1000.0
        new_in = max(0.0, min(t, self.duration))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - 0.04)
        self.set_in_out(new_in, self.current_out)

    def set_out_point(self):
        self.push_undo()
        try:
            t = time_to_s(self.out_time_edit.text())
        except Exception:
            t = self.player.position() / 1000.0
        new_out = max(0.0, min(t, self.duration))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + 0.04)
        self.set_in_out(self.current_in, new_out)

    def on_in_frame_changed(self, frame):
        if not (self.fps and self.fps > 0) or self.duration <= 0:
            return
        self.push_undo()
        t = frame / self.fps
        new_in = max(0.0, min(t, self.duration))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - (1.0 / self.fps))
        self.set_in_out(new_in, self.current_out)

    def on_out_frame_changed(self, frame):
        if not (self.fps and self.fps > 0) or self.duration <= 0:
            return
        self.push_undo()
        t = frame / self.fps
        new_out = max(0.0, min(t, self.duration))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + (1.0 / self.fps))
        self.set_in_out(self.current_in, new_out)

    def on_wave_seek(self, t):     self.seek_to(t)
    def on_wave_playseek(self, t): self.seek_to(t)

    def on_wave_selection_changed(self, new_in, new_out):
        self.current_in = new_in; self.current_out = new_out
        self.in_time_edit.setText(s_to_time(new_in))
        self.out_time_edit.setText(s_to_time(new_out))
        self._set_frame_spins(new_in, new_out)
        self.update_selection_label()
        # Двигаем красную/зелёную полоску ВО ВРЕМЯ воспроизведения → обновляем
        # границу авто-паузы painted-режима. Иначе VideoCanvas держит СТАРЫЙ OUT
        # и стопит/телепортит плеер на прежнем месте зелёной полоски (баг).
        try:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._set_play_bound(True)
        except Exception:
            pass

    def update_selection_label(self):
        # Показываем только итоговую длительность будущего ролика (без таймкодов
        # начала/конца — они и так есть в полях IN/OUT).
        dur = max(0.0, self.current_out - self.current_in)
        self.lbl_selection.setText(
            f"{icon_html('fa5s.stopwatch', 13, C['text'])}  Итог: {s_to_time(dur)}")

    def _resize_montage_side_btns(self, col_h):
        """Высота кнопок боковой панели монтажа = высота колонки на ровно 8 значков."""
        btns = getattr(self, "_montage_side_btns", None)
        if not btns or col_h <= 0:
            return
        avail = max(0, int(col_h) - self._MSIDE_GAP * (self._MSIDE_COUNT - 1))
        bh = max(24, min(40, avail // self._MSIDE_COUNT))
        isz = max(14, min(22, bh - 12))
        for b in btns:
            b.setFixedHeight(bh)
            b.setIconSize(QSize(isz, isz))

    @staticmethod
    def _relax_width(wdg):
        """Снимает минимальную «требуемую» ширину виджета (горизонтальная политика
        Ignored): он не распирает правую панель по длине своего текста, а тянется
        по доступному месту (текст при нехватке укорачивается). НЕ применять к
        меткам в строках инфо-карточек (там есть stretch — схлопнутся в 0)."""
        sp = wdg.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        wdg.setSizePolicy(sp)

    def _update_total_time(self):
        """Обновляет общее время в плеере (00:00 / ОБЩЕЕ под видео)."""
        lbl = getattr(self, "lbl_total_time", None)
        if lbl is not None:
            lbl.setText(s_to_time(self.duration if self.duration and self.duration > 0 else 0.0))

    # ── Playback ──────────────────────────────────────────────────────────
    def on_player_duration_changed(self, dur_ms):
        if dur_ms <= 0:
            return
        # Усечённый прокси (первые N минут) короче оригинала — НЕ даём его
        # длительности перетереть настоящую, иначе таймлайн/обрезка схлопнутся
        # до длины прокси (а резать-то надо весь файл). Истинную длительность
        # держим из ffprobe (load_file).
        if getattr(self, 'is_proxy_active', False) and getattr(self, '_proxy_partial', False):
            return
        new_dur = dur_ms / 1000.0
        # Выделение покрывало весь клип? Тогда тянем OUT к настоящей длительности.
        was_full = (self.current_out <= 0.001) or abs(self.current_out - self.duration) < 0.05
        self.duration = new_dur
        self.lbl_duration.setText(s_to_time(self.duration))
        self._update_total_time()
        # Синхронизируем current_out / waveform.out_s с новой длительностью (баг #4).
        new_out = new_dur if was_full else min(self.current_out, new_dur)
        new_in  = min(self.current_in, max(0.0, new_out - 0.001))
        if abs(new_out - self.current_out) > 1e-4 or abs(new_in - self.current_in) > 1e-4:
            self.set_in_out(new_in, new_out, skip_undo=True)

    def _update_seg_duration(self, pos_s=None):
        """Обновляет метку «старт→плейхед»: длительность от IN до жёлтой полосы
        воспроизведения. Зовётся отовсюду, где двигается плейхед или меняется IN."""
        lbl = getattr(self, "lbl_seg_dur", None)
        if lbl is None:
            return
        try:
            if pos_s is None:
                pos_s = self.player.position() / 1000.0
            lbl.setText(s_to_time(max(0.0, pos_s - self.current_in)))
        except Exception:
            pass

    def on_position_changed(self, pos_ms):
        pos_s = pos_ms / 1000.0
        self.lbl_current_time.setText(s_to_time(pos_s))
        if self.duration and self.duration > 0 and not self.slider.is_user_seeking():
            self.slider.blockSignals(True)
            self.slider.setValue(int((pos_s / self.duration) * 1000))
            self.slider.blockSignals(False)
        self.waveform.set_playhead(pos_s)
        self._update_meter(pos_s)
        self._update_subtitle(pos_s)
        self._update_seg_duration(pos_s)
        self._fs_sync_position()

    def _update_meter(self, pos_s, force=False):
        """Кормит индикатор уровня значением аудиоволны на позиции плейхеда.
        При воспроизведении вызывается из sync_ui; `force=True` — при покадровой
        перемотке (скрабе), чтобы шкала «оживала» и на шаге, а не только на play.
        На паузе без force шкала плавно опадает сама."""
        meter = getattr(self, "audio_meter", None)
        if meter is None:
            return
        try:
            playing = (self.player.playbackState()
                       == QMediaPlayer.PlaybackState.PlayingState)
            if not playing and not force:
                return
            # level_at_lr уже нормирован по пику и перцептивен (см. WaveformWidget),
            # поэтому шкала живая и отражает реальное присутствие звука. L и R —
            # честно раздельные каналы (для моно совпадут).
            lvl_l, lvl_r = self.waveform.level_at_lr(pos_s)
            try:
                vol = max(0.0, min(1.0, float(self.audio_output.volume())))
            except Exception:
                vol = 1.0
            k = 0.25 + 0.75 * vol
            meter.set_levels(min(1.0, lvl_l * k), min(1.0, lvl_r * k))
        except Exception:
            pass

    def _effective_out_s(self):
        """Граница авто-паузы воспроизведения. Если OUT у самого конца клипа —
        останавливаемся на кадр раньше: иначе плеер доходит до EndOfMedia и
        QtMultimedia гасит поверхность в чёрный кадр (баг #9)."""
        frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
        guard = max(frame_s, 0.05)
        at_end = self.current_out >= (self.duration - 0.02)
        return (self.duration - guard) if at_end else self.current_out

    def _set_play_bound(self, active):
        """Вкл/выкл блокировку кадров за OUT в painted-режиме (анти-overshoot)."""
        vw = self.video_widget
        if not isinstance(vw, VideoCanvas):
            return
        if active and self.duration > 0:
            frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
            # граница = effective_out + полкадра: кадр НА границе ещё показываем,
            # а следующий (за ней) — блокируем и встаём на паузу.
            vw.set_play_bound(self._effective_out_s() + frame_s * 0.5)
        else:
            vw.set_play_bound(None)

    def _on_play_boundary(self):
        """Пришёл кадр за OUT (по PTS) — мгновенная пауза и снап на границу ДО
        показа кадра. Убирает проскок-и-отскок правой границы."""
        try:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            out_s = self._effective_out_s()
            self.player.setPosition(int(out_s * 1000))
            self.lbl_current_time.setText(s_to_time(out_s))
            self.waveform.set_playhead(out_s)
            self._ext_audio_seek(int(out_s * 1000))
        except Exception:
            pass

    def sync_ui(self):
        if self.duration <= 0.1:
            return
        pos_s = self.player.position() / 1000.0
        self.lbl_current_time.setText(s_to_time(pos_s))
        # Авто-пауза в конце воспроизводимого участка (резерв к покадровому
        # блоку VideoCanvas: ловит границу в overlay-режиме и как страховка).
        effective_out = self._effective_out_s()
        if effective_out > self.current_in and pos_s >= effective_out:
            self.player.pause()
            self.player.setPosition(int(effective_out * 1000))
            self.lbl_current_time.setText(s_to_time(effective_out))
            self.waveform.set_playhead(effective_out)
            self._update_seg_duration(effective_out)
            return
        if self.duration > 0 and not self.slider.is_user_seeking():
            self.slider.blockSignals(True)
            self.slider.setValue(int((pos_s / self.duration) * 1000))
            self.slider.blockSignals(False)
        self.waveform.set_playhead(pos_s)
        self._update_meter(pos_s)
        self._update_subtitle(pos_s)
        self._update_seg_duration(pos_s)
        self._fs_sync_position()
        # Корректируем рассинхрон внешней озвучки (только если ушла заметно).
        if self._ext_audio_active and self._ext_audio_player is not None:
            try:
                if (self._ext_audio_player.playbackState()
                        == QMediaPlayer.PlaybackState.PlayingState):
                    drift = self._ext_audio_player.position() - self.player.position()
                    if abs(drift) > 220:
                        self._ext_audio_player.setPosition(self.player.position())
            except Exception:
                pass

    def on_slider_moved(self, value):
        if self.duration > 0:
            self.seek_to((value / 1000.0) * self.duration)

    def seek_to(self, t_s):
        try:
            ms = int(max(0.0, min(t_s, max(0.0, self.duration))) * 1000)
            self.player.setPosition(ms)
            self.waveform.set_playhead(t_s)
            self._ext_audio_seek(ms)
        except Exception as e:
            print("seek_to error:", e)

    def toggle_play(self):
        self._scrubbing = False   # явное play/pause не должно гаситься скрабом
        # Пользователь нажал Play в окне беззвучного прогрева: отменяем прогрев,
        # возвращаем mute и продолжаем уже как обычный запуск (плеер уже играет
        # под mute с точки IN — достаточно снять mute, не дёргая позицию).
        if getattr(self, "_prerolling", False):
            self._prerolling = False
            try:
                self.audio_output.setMuted(self._preroll_prev_muted)
            except Exception:
                pass
            self.on_playback_changed(self.player.playbackState())
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            pos_s = self.player.position() / 1000.0
            if abs(pos_s - self.current_out) < 0.15 and self.current_out > (self.current_in + 0.5):
                self.seek_to(self.current_in)
            self.player.play()

    def stop_playback(self):
        self.player.pause(); self.seek_to(self.current_in)
        # «Камера» идёт за плейхедом: если зум стоит не на начале зоны, докручиваем
        # окно обзора так, чтобы точка, куда прыгнула жёлтая полоска, была видна.
        try:
            self.waveform.ensure_view_contains(self.current_in, self.current_in)
            self.waveform.update()
        except Exception:
            pass
        # Прогреваем аудио-конвейер в точке IN — следующее «Воспроизвести»
        # стартует без задержки звука (см. _preroll_at).
        self._preroll_at(self.current_in)

    def _preroll_at(self, t_s):
        """Беззвучный микро-прогрев в точке t_s: QtMultimedia после перемотки
        поднимает аудио-декодер «холодно» только на play() — отсюда задержка
        звука при СТОП→Воспроизвести. Делаем очень короткий play под mute и сразу
        ставим паузу, вернув позицию ровно на t_s. Слышимого щелчка нет, кадр не
        уезжает, а декодер уже «тёплый» — реальный запуск идёт мгновенно."""
        if self.duration <= 0.1 or not self.filepath:
            return
        if getattr(self, "_prerolling", False):
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return
        try:
            ms = int(max(0.0, t_s) * 1000)
            # prev_muted держим на self — если пользователь нажмёт «Воспроизвести»
            # прямо в окне прогрева, toggle_play восстановит mute и отменит прогрев.
            self._preroll_prev_muted = self.audio_output.isMuted()
            self._prerolling = True
            self.audio_output.setMuted(True)
            self.player.play()

            def _finish():
                if not self._prerolling:
                    return  # прогрев отменён (пользователь нажал Play) — не трогаем
                try:
                    self.player.pause()
                    self.player.setPosition(ms)
                    # Восстанавливаем прежнее состояние mute (могло быть включено
                    # внешней озвучкой — тогда звук видео должен остаться немым).
                    self.audio_output.setMuted(self._preroll_prev_muted)
                    self.waveform.set_playhead(t_s)
                    self.lbl_current_time.setText(s_to_time(t_s))
                except Exception:
                    pass
                self._prerolling = False

            QTimer.singleShot(45, _finish)
        except Exception:
            self._prerolling = False
            try:
                self.audio_output.setMuted(False)
            except Exception:
                pass

    def on_playback_changed(self, state):
        # Во время покадрового скраба play→pause транзиентны — не трогаем кнопку,
        # чтобы иконка/текст не дёргались (меняются только по явному действию).
        # То же во время беззвучного прогрева аудио (_preroll_at): кнопка/иконка
        # и внешняя озвучка не должны мигать на транзиентный play→pause.
        if self._scrubbing or getattr(self, "_prerolling", False):
            return
        playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        if playing:
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.sync_timer.start()
        else:
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.sync_timer.stop()
        self._set_play_bound(playing)   # painted-режим: блокировка кадров за OUT
        # Внешняя озвучка следует за состоянием основного плеера.
        self._ext_audio_set_state(playing)
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.update_play_icon(state == QMediaPlayer.PlaybackState.PlayingState)
            except Exception:
                pass

    def on_media_status_changed(self, status):
        # После смены качества воспроизведения (swap источника) восстанавливаем
        # позицию и состояние, как только медиа загрузилось.
        if (status in (QMediaPlayer.MediaStatus.LoadedMedia,
                       QMediaPlayer.MediaStatus.BufferedMedia)
                and getattr(self, '_pending_pb_seek', None) is not None):
            pos, was_playing = self._pending_pb_seek
            self._pending_pb_seek = None
            try:
                self.player.setPosition(int(max(0, pos)))
                if was_playing:
                    self.player.play()
                else:
                    self.player.pause()
            except Exception:
                pass
        # Подстраховка от чёрного кадра в конце: если воспроизведение всё же
        # дошло до EndOfMedia (таймер sync_ui не успел поставить паузу на кадр
        # раньше), возвращаемся на последний реальный кадр и держим паузу.
        try:
            if status == QMediaPlayer.MediaStatus.EndOfMedia and self.duration > 0:
                frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
                last = max(self.current_in, self.duration - max(frame_s, 0.05))
                self.player.pause()
                self.player.setPosition(int(last * 1000))
                self.waveform.set_playhead(last)
                self.lbl_current_time.setText(s_to_time(last))
        except Exception:
            pass

    def _on_volume_changed(self, v):
        try:
            self.audio_output.setVolume(v / 100.0)
        except Exception:
            pass
        # Та же громкость — для внешней озвучки (отдельный аудиовыход).
        if self._ext_audio_output is not None:
            try:
                self._ext_audio_output.setVolume(v / 100.0)
            except Exception:
                pass
        # …и для скраб-звука покадровой перемотки.
        if getattr(self, "_scrub_audio_output", None) is not None:
            try:
                self._scrub_audio_output.setVolume(v / 100.0)
            except Exception:
                pass
        try:
            self.vol_lbl.update_glyph(v)
        except Exception:
            pass
        # Полноэкранный ползунок громкости держим в курсе.
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.sync_volume()
            except Exception:
                pass

    def _update_media_buttons(self):
        """Кнопки «полноэкранный режим» и «сохранить кадр» активны только когда
        загружено видео (есть видеопоток и длительность)."""
        has_video = (getattr(self, "video_stream_index", None) is not None
                     and getattr(self, "duration", 0) > 0.1)
        is_image = bool(getattr(self, "is_still_image", False))
        # Для still-картинки доступны кадрирование/пикселизация/сохранение кадра
        # (полноэкранный режим — нет, он завязан на плеер).
        has_visual = has_video or is_image
        _fsb = getattr(self, "btn_fullscreen", None)
        if _fsb is not None:
            _fsb.setEnabled(has_video)
        for name in ("btn_save_frame", "btn_crop_frame", "btn_pixelize"):
            b = getattr(self, name, None)
            if b is not None:
                b.setEnabled(has_visual)
        # «Удалить объект» — только для видео (для одиночной картинки есть
        # фоторедактор) и только если не идёт уже обработка.
        b = getattr(self, "btn_remove_object", None)
        if b is not None and not getattr(self, "_vinp_running", False):
            b.setEnabled(has_video)
        # Нет визуала (ни видео, ни картинки) — выходим из режима кадрирования рамки.
        if not has_visual:
            b = getattr(self, "btn_crop_frame", None)
            if b is not None and b.isChecked():
                b.setChecked(False)
            # …и сбрасываем пикселизацию.
            if getattr(self, "_pixelize_active", False) or (
                    getattr(self, "btn_pixelize", None) is not None
                    and self.btn_pixelize.isChecked()):
                self._pixelize_active = False
                b = getattr(self, "btn_pixelize", None)
                if b is not None and b.isChecked():
                    b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
                self._sync_pixelize_icon()
        # «Удалить исходник» активна при любом загруженном файле (видео/аудио).
        try:
            src = getattr(self, "actual_source_file", None)
            b = getattr(self, "btn_delete_source", None)
            if b is not None:
                b.setEnabled(bool(src) and os.path.exists(str(src)))
        except Exception:
            pass
        # Режимы обрезки, неприменимые к аудио, отключаем (см. ниже).
        self._update_mode_combo_for_media(has_video)
        # Иконка полноэкранного режима белая поверх accent-заливки; на сером
        # disabled-фоне белый значок «не выглядел» выключенным. Перекрашиваем его
        # в приглушённый цвет, когда видео нет, и обратно в белый, когда есть.
        try:
            if getattr(self, "btn_fullscreen", None) is not None \
                    and getattr(self, "_fs_window", None) is None:
                self.btn_fullscreen.setIcon(_fullscreen_icon(
                    expand=True, color="#ffffff" if has_video else C['text3']))
        except Exception:
            pass

    def _update_audio_only_placeholder(self):
        """В области видео показываем поясняющий текст, когда у загруженного файла
        нет видеоряда (редактируется чистое аудио). При наличии видео или без файла
        — обычный режим (показ кадров)."""
        vw = getattr(self, "video_widget", None)
        if vw is None or not hasattr(vw, "set_audio_only_message"):
            return
        src = getattr(self, "actual_source_file", None)
        # Still-картинка показывается на холсте как кадр — это НЕ «аудио без видео».
        audio_only = (bool(src)
                      and not getattr(self, "is_still_image", False)
                      and getattr(self, "video_stream_index", None) is None
                      and getattr(self, "duration", 0) > 0.1)
        vw.set_audio_only_message(
            "Вы редактируете аудиофайл — видеоряд отсутствует" if audio_only else "")

    def _update_mode_combo_for_media(self, has_video):
        """Для аудиофайла оставляем только применимые режимы обрезки: «Быстро
        (без потерь)» (0) и «Только аудио (MP3)» (2). «Перекодировать» (1, гонит
        видеокодек) и «Smart Cut» (3, работает по ключевым кадрам ВИДЕО) к аудио
        неприменимы — гасим их в списке, чтобы их нельзя было выбрать. Индексы
        режимов фиксированы (их читает start_cut), поэтому пункты не удаляем, а
        отключаем через модель комбобокса."""
        cmb = getattr(self, "cmb_mode", None)
        if cmb is None:
            return
        try:
            # Гасим режимы только когда РЕАЛЬНО загружено аудио без видео; без
            # файла (или с видео) — все режимы доступны.
            src = getattr(self, "actual_source_file", None)
            audio_only = (bool(src) and not has_video
                          and getattr(self, "duration", 0) > 0.1)
            model = cmb.model()
            audio_invalid = (1, 3)   # «Перекодировать», «Smart Cut»
            for i in range(cmb.count()):
                item = model.item(i)
                if item is None:
                    continue
                item.setEnabled((not audio_only) or i not in audio_invalid)
            # Если для аудио выбран теперь недоступный режим — переводим на
            # «Быстро (без потерь)» (точная lossless-обрезка по времени).
            if audio_only and cmb.currentIndex() in audio_invalid:
                cmb.setCurrentIndex(0)
        except Exception:
            pass

    def _toggle_frame_crop(self, on):
        """Вкл/выкл режим правки рамки кадрирования на холсте (как в «Редактировании
        фото»): появляется рамка с ручками и кнопки «Применить/Отмена»."""
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.set_crop_mode(bool(on))
        if on:
            try:
                if self.main is not None and hasattr(self.main, "log"):
                    self.main.log("Кадрирование видео: правьте рамку ручками "
                                  "(углы/стороны), затем «Применить» (Enter) или "
                                  "«Отмена» (Esc). Применится при «Обрезать» "
                                  "(перекодирование).")
            except Exception:
                pass

    def _toggle_pixelize(self, on):
        """Вкл/выкл эффект «проявление из пикселей». При включении открывается
        диалог с параметрами (число шагов, стартовый блок); отмена снимает чек.
        Эффект применяется при «Обрезать» и виден только в итоговом файле (живого
        превью нет — мозаика считается при перекодировке)."""
        if on:
            is_image = bool(getattr(self, "is_still_image", False))
            dlg = _PixelizeDialog(self._pixelize_steps, self._pixelize_block, self,
                                  image_mode=is_image, duration=self._still_duration,
                                  fps=self._still_fps)
            if dlg.exec():
                self._pixelize_steps, self._pixelize_block = dlg.values()
                self._pixelize_active = True
                if is_image:
                    self._still_duration, self._still_fps = dlg.image_values()
                    # Длительность ролика обновилась — отражаем в таймингах.
                    self.duration = float(self._still_duration)
                    self.current_out = self.duration
                    try:
                        self.lbl_duration.setText(s_to_time(self.duration))
                        self._update_total_time()
                    except Exception:
                        pass
                try:
                    if self.main is not None and hasattr(self.main, "log"):
                        seq = _pixelize_block_sequence(self._pixelize_block, self._pixelize_steps)
                        extra = (f", {self._still_duration}с @ {self._still_fps}fps"
                                 if is_image else "")
                        self.main.log(
                            f"Пикселизация задана ({self._pixelize_steps} шаг(ов), "
                            f"старт {self._pixelize_block}px{extra}) — применится при "
                            f"«Обрезать». Блоки: "
                            + " → ".join(f"{b}px" if b > 1 else "чётко" for b in seq))
                except Exception:
                    pass
            else:
                # Отмена диалога — снимаем чек, не трогая прежнее состояние.
                self._pixelize_active = False
                b = self.btn_pixelize
                b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        else:
            self._pixelize_active = False
            try:
                if self.main is not None and hasattr(self.main, "log"):
                    self.main.log("Пикселизация отключена.")
            except Exception:
                pass
        self._sync_pixelize_icon()

    def _sync_pixelize_icon(self):
        """Цвет значка кнопки пикселизации по состоянию: тёмный на акцентной
        заливке (включено), обычный — выключено. Иначе светлый значок на светло-
        голубом фоне «included» сливался."""
        b = getattr(self, "btn_pixelize", None)
        if b is None:
            return
        try:
            b.setIcon(get_icon('fa5s.th', color='#11111b' if b.isChecked() else C['text']))
        except Exception:
            pass

    def _video_pixelize_filter(self, dur, offset=0.0):
        """Цепочка ffmpeg-фильтров «проявление из пикселей» для клипа длительностью
        `dur` секунд, либо None если эффект выключен/нечего применять. Делит клип на
        N равных окон; в каждом окне `pixelize` с уменьшающимся блоком (через
        enable='between(t,…)'), пока картинка не станет чёткой.

        ВАЖНО про `offset`: фильтрграф видит ВРЕМЯ ИСХОДНИКА, а не время обрезанного
        клипа (setpts на таймлайн `enable` не влияет — проверено). Поэтому окна
        смещаются на `offset` — время фильтрграфа, на котором начинается клип:
          • выходной seek (-ss после -i): offset = начало реза in_s;
          • входной seek (-ss до -i):       offset = 0;
          • входной pre-seek + выходной -ss: offset = величина выходного -ss.
        """
        if not getattr(self, "_pixelize_active", False) or dur is None or dur <= 0:
            return None
        steps = max(1, int(getattr(self, "_pixelize_steps", 6)))
        block0 = max(2, int(getattr(self, "_pixelize_block", 64)))
        seq = _pixelize_block_sequence(block0, steps)
        win = dur / steps
        off = max(0.0, float(offset))
        parts = []
        for i, b in enumerate(seq):
            if b <= 1:
                continue  # блок 1 = без изменений (чётко) — фильтр не нужен
            t0 = off + i * win
            t1 = off + (i + 1) * win
            parts.append(f"pixelize=w={b}:h={b}:enable='between(t,{t0:.3f},{t1:.3f})'")
        if not parts:
            return None  # всё чётко — пикселить нечего
        return ",".join(parts)

    def _on_crop_applied(self):
        """Холст: нажата «Применить» — снимаем чек с кнопки (режим правки закрыт),
        рамка остаётся «вооружённой» для «Обрезать»."""
        b = getattr(self, "btn_crop_frame", None)
        if b is not None and b.isChecked():
            b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        armed = self._video_crop_filter() is not None
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log("Кадрирование задано — применится при «Обрезать»."
                              if armed else "Кадрирование снято (рамка = весь кадр).")
        except Exception:
            pass

    def _on_crop_cancelled(self):
        """Холст: нажата «Отмена»/Esc — снимаем чек с кнопки, рамка сброшена."""
        b = getattr(self, "btn_crop_frame", None)
        if b is not None and b.isChecked():
            b.blockSignals(True); b.setChecked(False); b.blockSignals(False)

    def _video_crop_filter(self):
        """ffmpeg-фильтр crop=… по рамке кадрирования на холсте, либо None, если
        рамка не задана/слишком мелкая. Координаты — выражения от iw/ih (не
        зависят от прокси-превью), размеры/смещения чётные (требование кодеков)."""
        vw = getattr(self, "video_widget", None)
        if not isinstance(vw, VideoCanvas):
            return None
        n = vw.crop_norm()
        if n is None:
            return None
        x = max(0.0, min(1.0, n.left()))
        y = max(0.0, min(1.0, n.top()))
        w = max(0.0, min(1.0 - x, n.width()))
        h = max(0.0, min(1.0 - y, n.height()))
        if w < 0.02 or h < 0.02:
            return None
        return (f"crop=trunc(iw*{w:.6f}/2)*2:trunc(ih*{h:.6f}/2)*2:"
                f"trunc(iw*{x:.6f}/2)*2:trunc(ih*{y:.6f}/2)*2")

    @staticmethod
    def _apply_frame_crop(img, n):
        """Обрезает QImage по нормализованной рамке n (QRectF 0..1). Координаты
        зажимаются в границы изображения."""
        if img is None or img.isNull() or n is None:
            return img
        w, h = img.width(), img.height()
        x = max(0, min(w - 1, int(round(n.left() * w))))
        y = max(0, min(h - 1, int(round(n.top() * h))))
        cw = max(1, min(w - x, int(round(n.width() * w))))
        ch = max(1, min(h - y, int(round(n.height() * h))))
        return img.copy(x, y, cw, ch)

    # ── Сохранение текущего кадра ────────────────────────────────────────────
    def save_frame(self):
        """Сохраняет кадр на текущей позиции воспроизведения в PNG (полное
        разрешение, извлекается из исходника через ffmpeg). Без диалога —
        файл сразу кладётся в папку сохранения (или рядом с исходником)."""
        src = self.actual_source_file or self.filepath
        if not src or not os.path.exists(src) or self.duration <= 0:
            return
        # Рамка кадрирования (если задана на холсте) — сохраняем только её.
        crop_n = None
        _vw = getattr(self, "video_widget", None)
        if isinstance(_vw, VideoCanvas):
            crop_n = _vw.crop_norm()
        pos = max(0.0, self.player.position() / 1000.0)
        base = os.path.splitext(os.path.basename(src))[0]
        stamp = s_to_time(pos).replace(':', '-').replace('.', '_')
        save_dir = (self.export_dir if (self.export_dir and os.path.isdir(self.export_dir))
                    else os.path.dirname(src))
        fname = _unique_output(os.path.join(save_dir, f"{base}_{stamp}.png"))
        ok = False
        # 1) В painted-режиме (VideoCanvas) сохраняем РОВНО тот кадр, что показан
        #    на холсте — без пере-извлечения через ffmpeg. Иначе seek по позиции
        #    на HEVC отдавал следующий кадр (out_time приходился между кадрами →
        #    ffmpeg брал первый PTS ≥ позиции = следующий).
        # (Если активен превью-прокси, кадр на холсте уменьшён — тогда лучше
        #  полноразмерный кадр из оригинала через ffmpeg, см. ниже.)
        if isinstance(self.video_widget, VideoCanvas) and not self.is_proxy_active:
            try:
                img = self.video_widget.current_frame_image()
                if img is not None and not img.isNull():
                    if crop_n is not None:
                        img = self._apply_frame_crop(img, crop_n)
                    ok = bool(img.save(fname, "PNG"))
            except Exception:
                ok = False
        # 2) Резерв (overlay-режим / нет кадра на холсте): извлекаем через ffmpeg.
        #    -ss перед -i точен, но позиция может прийтись между кадрами; вычитаем
        #    половину интервала кадра, чтобы попасть в текущий, а не следующий.
        if not ok:
            eps = (0.5 / self.fps) if getattr(self, "fps", None) else 0.02
            seek = max(0.0, pos - eps)
            cmd = [FFMPEG, "-y", "-ss", f"{seek:.3f}", "-i", src,
                   "-frames:v", "1", "-update", "1", fname]
            kw = {}
            if os.name == 'nt':
                kw['creationflags'] = CREATE_NO_WINDOW
            try:
                r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=60, **kw)
                ok = (r.returncode == 0 and os.path.exists(fname)
                      and os.path.getsize(fname) > 0)
            except Exception:
                ok = False
            # Полноразмерный кадр из ffmpeg обрезаем под рамку кадрирования.
            if ok and crop_n is not None:
                try:
                    _qi = QImage(fname)
                    if not _qi.isNull():
                        self._apply_frame_crop(_qi, crop_n).save(fname, "PNG")
                except Exception:
                    pass
        msg = (f"🖼 Кадр сохранён: {os.path.basename(fname)}" if ok
               else "Не удалось сохранить кадр")
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(msg)
        except Exception:
            pass
        try:
            gp = self.btn_save_frame.mapToGlobal(
                QPoint(0, -self.btn_save_frame.height()))
            QToolTip.showText(gp, msg, self.btn_save_frame)
        except Exception:
            pass

    # ── Удаление объекта с видео (LaMa, покадрово) ───────────────────────────
    def _ensure_inpainter(self):
        """Лениво создаёт движок LaMa (ТОТ ЖЕ, что в фоторедакторе) и
        переиспользует его между запусками. Сессия живёт в дочернем процессе
        (см. lama_inpaint.py), поэтому загрузка 200-МБ модели не морозит UI."""
        inp = getattr(self, "_inpainter", None)
        if inp is not None:
            return inp
        try:
            from lama_inpaint import LaMaProcessInpainter
        except Exception:
            return None
        self._inpainter = LaMaProcessInpainter()
        return self._inpainter

    def _grab_source_frame_bgr(self, src):
        """Извлекает кадр оригинала на текущей позиции воспроизведения в ПОЛНОМ
        разрешении (через ffmpeg) и возвращает numpy BGR. Способ совпадает с тем,
        как VideoInpaintWorker позже извлечёт все кадры, поэтому нарисованная маска
        попадает в кадры попиксельно (то же разрешение и дисплейная ориентация)."""
        pos = max(0.0, self.player.position() / 1000.0)
        # -ss перед -i точен, но позиция может прийтись между кадрами — вычитаем
        # половину интервала кадра, чтобы попасть в текущий, а не следующий.
        eps = (0.5 / self.fps) if getattr(self, "fps", None) else 0.02
        seek = max(0.0, pos - eps)
        tmp = os.path.join(tempfile.gettempdir(),
                           f"sihyx_vmask_{os.getpid()}_{int(time.time() * 1000)}.png")
        cmd = [FFMPEG, "-y", "-ss", f"{seek:.3f}", "-i", src,
               "-frames:v", "1", "-update", "1", tmp]
        kw = {}
        if os.name == 'nt':
            kw['creationflags'] = CREATE_NO_WINDOW
        try:
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=60, **kw)
            if r.returncode != 0 or not os.path.exists(tmp):
                return None
            from lama_inpaint import load_bgr
            return load_bgr(tmp)
        except Exception:
            return None
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def remove_object_from_video(self):
        """Удаляет объект (водяной знак/эмодзи/логотип) со ВСЕГО видео: пользователь
        закрашивает объект кистью на текущем кадре, затем ТЕМ ЖЕ движком LaMa, что и
        в фоторедакторе, объект убирается с каждого кадра, и видео собирается
        обратно с исходными FPS/разрешением/ориентацией/аудио. Тяжёлая работа — в
        отдельном потоке (VideoInpaintWorker) с возможностью отмены.

        Поведение для одиночного изображения НЕ меняется: эта кнопка активна только
        при загруженном видео (см. _update_media_buttons)."""
        # Пока идёт обработка — кнопка работает как «Отмена».
        if getattr(self, "_vinp_running", False):
            self._cancel_video_inpaint()
            return

        src = self.actual_source_file or self.filepath
        if not src or not os.path.exists(str(src)) or self.duration <= 0:
            return
        if getattr(self, "video_stream_index", None) is None:
            QMessageBox.information(
                self, "Только для видео",
                "Удаление объекта доступно для видео. Для одиночного изображения "
                "используйте вкладку «Фото».")
            return
        src = str(src)

        # Доступность движка LaMa (numpy/opencv/модель).
        inp = self._ensure_inpainter()
        if inp is None or not inp.is_available():
            QMessageBox.warning(
                self, "Удаление объекта недоступно",
                "Не найдены необходимые компоненты (numpy/opencv или файл модели "
                "LaMa). Удаление объекта с видео недоступно в этой сборке.")
            return

        # Кадр для рисования маски — из оригинала на текущей позиции, полный размер.
        frame = self._grab_source_frame_bgr(src)
        if frame is None:
            QMessageBox.warning(
                self, "Ошибка",
                "Не удалось получить кадр видео для рисования маски.")
            return

        dlg = _VideoMaskDialog(frame, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mask = dlg.get_mask()
        if mask is None or int(mask.max()) == 0:
            return

        # Имя результата — в папке сохранения/рядом с исходником; контейнер
        # исходника, если он поддерживает H.264, иначе .mp4 (h264 в webm недопустим).
        base = Path(src)
        out_dir = (Path(self.export_dir)
                   if (self.export_dir and os.path.isdir(self.export_dir))
                   else base.parent)
        suffix = base.suffix.lower()
        if suffix not in (".mp4", ".mkv", ".mov", ".m4v"):
            suffix = ".mp4"
        out_path = str(out_dir / f"{base.stem}_без_объекта{suffix}")
        if os.path.exists(out_path):
            out_path = _unique_output(out_path)

        has_audio = getattr(self, "audio_stream_index", None) is not None
        venc = self._video_encoder_args(hardsub=False)

        # Запуск фоновой обработки + перевод кнопки в режим «Отмена».
        self._vinp_running = True
        self.btn_cut.setEnabled(False)
        self._set_remove_btn_cancel(True)
        self._report_progress(-1, "Удаление объекта…")
        self._set_cut_status("Удаление объекта… подготовка",
                             icon='fa5s.hourglass-half')
        self.log_label.setText("Удаление объекта с видео…")

        self._vinp_worker = VideoInpaintWorker(
            inp, src, mask, self.fps, out_path, venc, has_audio)
        self._vinp_worker.progress.connect(self._on_vinp_progress)
        self._vinp_worker.done.connect(self._on_vinp_done)
        self._vinp_worker.failed.connect(self._on_vinp_failed)
        self._vinp_worker.start()

    def _set_remove_btn_cancel(self, cancel_mode):
        """Переключает кнопку «Удалить объект» между обычным видом и «Отмена» на
        время обработки видео."""
        b = getattr(self, "btn_remove_object", None)
        if b is None:
            return
        if cancel_mode:
            b.setIcon(get_icon('fa5s.times'))
            b.setToolTip("Отменить удаление объекта")
            b.setEnabled(True)
        else:
            b.setIcon(get_icon('fa5s.magic'))
            b.setToolTip(
                "Удалить объект с видео (водяной знак, эмодзи, логотип): закрасьте "
                "его кистью на кадре — нейросеть LaMa уберёт его со всех кадров")

    def _cancel_video_inpaint(self):
        """Просит фоновый воркер прерваться (временные файлы он уберёт сам)."""
        w = getattr(self, "_vinp_worker", None)
        if w is not None and w.isRunning():
            self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
            if getattr(self, "btn_remove_object", None) is not None:
                self.btn_remove_object.setEnabled(False)
            w.cancel()

    def _on_vinp_progress(self, pct, text):
        self._report_progress(pct, text)
        self._set_cut_status(text, icon='fa5s.magic' if pct >= 0
                             else 'fa5s.hourglass-half')

    def _finish_video_inpaint(self):
        """Общая уборка состояния UI после завершения/отмены/ошибки обработки."""
        self._vinp_running = False
        self._vinp_worker = None
        self._set_remove_btn_cancel(False)
        self.btn_cut.setEnabled(True)
        self._update_media_buttons()

    def _on_vinp_done(self, final_path):
        self._finish_video_inpaint()
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"Объект удалён с видео: {final_path}")
        except Exception:
            pass
        # Переиспользуем стандартное завершение «Монтажа» (статус «Готово»,
        # обновление верхней ленты файлов и т.п.).
        self.on_ffmpeg_finished(True, "Готово")

    def _on_vinp_failed(self, message):
        self._finish_video_inpaint()
        self.on_ffmpeg_finished(False, message)

    # ── Удаление исходного файла ─────────────────────────────────────────────
    def delete_source_file(self):
        """Удаляет загруженный исходный файл с диска (с подтверждением). Перед
        удалением освобождает файл (останавливает плеер и снимает источник),
        иначе Windows не даст удалить открытый файл."""
        src = self.actual_source_file or self.filepath
        if not src or not os.path.exists(str(src)):
            return
        src = str(src)
        name = os.path.basename(src)
        reply = QMessageBox.question(
            self, "Удалить исходный файл?",
            "Файл будет удалён с диска без возможности восстановления:\n\n"
            f"{name}\n\nПродолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Останавливаем фоновую сборку прокси (если идёт): иначе её ffmpeg будет
        # держать temp-файл, а finished-слот выстрелит уже после очистки. Сам слот
        # дополнительно защищён проверкой actual_source_file is None.
        try:
            if self.proxy_thread and self.proxy_thread.isRunning():
                self.proxy_thread.stop(); self.proxy_thread.wait()
        except Exception: pass
        self.proxy_thread = None
        # Освобождаем файл: останавливаем воспроизведение и снимаем источник.
        try: self.player.stop()
        except Exception: pass
        try: self.player.setSource(QUrl())
        except Exception: pass
        try:
            if getattr(self, "seek_preview", None) is not None:
                self.seek_preview.set_source(None)
        except Exception: pass
        try: QApplication.processEvents()
        except Exception: pass
        try:
            os.remove(src)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл:\n{e}")
            return
        # Сбрасываем состояние редактора (файл больше не загружен).
        self.actual_source_file = None
        self.filepath = None
        self.duration = 0.0
        try:
            if hasattr(self.video_widget, "clear_frame"):
                self.video_widget.clear_frame()
        except Exception: pass
        try: self.waveform.set_data([], 0.0)
        except Exception: pass
        try: self._update_media_buttons()
        except Exception: pass
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"🗑 Исходный файл удалён: {name}")
        except Exception: pass

    # ── Полноэкранный режим ─────────────────────────────────────────────────
    def toggle_fullscreen(self):
        if getattr(self, "_fs_window", None) is not None:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        if getattr(self, "_fs_window", None) is not None:
            return
        if self.duration <= 0.1:   # нет загруженного видео
            return
        try:
            fs = FullscreenVideo(self)
            # Снимаем фиксированные размеры с видео и переносим его в окно.
            self.video_widget.setMinimumSize(0, 0)
            self.video_widget.setMaximumSize(16777215, 16777215)
            fs.attach_video(self.video_widget)
            self._fs_window = fs
            self.btn_fullscreen.setIcon(_fullscreen_icon(expand=False))
            self.btn_fullscreen.setToolTip("Свернуть (Esc / двойной клик по видео)")
            fs.showFullScreen()
            fs.sync_from_player()
            fs.sync_volume()
            fs.update_play_icon(
                self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
            try:
                self._update_subtitle(self.player.position() / 1000.0)
                QTimer.singleShot(0, self._position_overlay)
            except Exception:
                pass
        except Exception as e:
            print("enter_fullscreen error:", e)
            self._fs_window = None

    def exit_fullscreen(self):
        fs = getattr(self, "_fs_window", None)
        if fs is None:
            return
        self._fs_window = None
        try:
            # Возвращаем видео обратно в контейнер вкладки.
            self.vc_layout.insertWidget(0, self.video_widget, 0, Qt.AlignmentFlag.AlignCenter)
            self.video_widget.show()
        except Exception:
            pass
        # Оверлей субтитров мог стать дочерним к окну fs — вернём его главному
        # окну ДО удаления fs, иначе Qt удалит оверлей вместе с fs.
        try:
            if self.sub_overlay is not None:
                self._reparent_overlay(self.window())
        except Exception:
            pass
        try:
            fs.close(); fs.deleteLater()
        except Exception:
            pass
        try:
            self.btn_fullscreen.setIcon(_fullscreen_icon(expand=True))
            self.btn_fullscreen.setToolTip("Полноэкранный режим (F / двойной клик по видео)")
            self._adjust_video_height()
            QTimer.singleShot(0, self._position_overlay)
        except Exception:
            pass

    def _fs_sync_position(self):
        """Обновляет полосу/тайминги в полноэкранном окне (вызывается из sync_ui
        и on_position_changed, когда оно открыто)."""
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.sync_from_player()
            except Exception:
                pass

    def step_frame(self, step):
        if not self.duration:
            return
        # База шага — последняя ЦЕЛЬ скраба, а не «живая» позиция: во время
        # play→pause-скраба позиция уезжает вперёд, и шаг назад от неё фактически
        # уходил вперёд/вправо. От цели шаги детерминированы (особенно при
        # удержании ←/→ с автоповтором).
        if getattr(self, "_scrubbing", False) and self._scrub_target is not None:
            ms = self._scrub_target
        else:
            ms = self.player.position()
        ms_per_frame = (1000.0 / self.fps) if (self.fps and self.fps > 0) else 40
        new_ms = max(0, min(int(self.duration * 1000), ms + int(step * ms_per_frame)))
        self._scrub_target = new_ms
        self.player.setPosition(new_ms)
        self._ext_audio_seek(new_ms)

    def step_frame_scrub(self, step):
        playing = (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        painted = isinstance(self.video_widget, VideoCanvas)
        # Серия шагов: при удержании ←/→ считаем от _scrub_target (детерминизм),
        # а на ПЕРВОМ шаге серии — от живой позиции плеера.
        if not playing and not getattr(self, "_scrubbing", False):
            self._scrub_target = None
        if not playing:
            self._scrubbing = True
        self.step_frame(step)
        if playing:
            return
        # Скраб-звук (как в Filmora): короткий звуковой блип в новой позиции.
        # В painted-режиме видео уже доставлено setPosition'ом — звук добавляем,
        # не трогая кадр (см. _scrub_audio_blip).
        self._scrub_audio_blip(painted)
        # Оживляем индикатор уровня и на покадровом шаге (на паузе он иначе молчит,
        # из-за чего казалось, что звука нет).
        tgt_ms = self._scrub_target if self._scrub_target is not None else self.player.position()
        self._update_meter((tgt_ms or 0) / 1000.0, force=True)
        if painted:
            # painted-режим (VideoCanvas + QVideoSink): пауза + setPosition сама
            # доставляет новый кадр в сink — короткий play() НЕ нужен (именно он
            # давал мерцание/скачок назад-вперёд). Флаг скраба снимаем таймером,
            # перезапускаемым на каждом шаге (серия удержания не рвётся).
            if not hasattr(self, "_scrub_reset_timer"):
                self._scrub_reset_timer = QTimer(self)
                self._scrub_reset_timer.setSingleShot(True)
                self._scrub_reset_timer.timeout.connect(self._end_scrub_painted)
            self._scrub_reset_timer.start(160)
            return
        # overlay-режим (QVideoWidget): нативная поверхность без play() кадр не
        # перерисовывает — прежний приём с коротким play() и возвратом на цель.
        self._scrubbing = True
        self.player.play()
        QTimer.singleShot(60, self._end_scrub)

    def _end_scrub_painted(self):
        self._scrubbing = False

    # ── Скраб-звук при покадровой перемотке ─────────────────────────────────
    def _ensure_scrub_audio_player(self):
        """Лениво создаёт/перепривязывает отдельный аудиоплеер для скраб-звука.
        Источник — ОРИГИНАЛ файла (а не прокси: у прокси звук может быть хуже или
        отсутствовать), открыт через ShareDeleteIODevice, чтобы исходник всё так
        же можно было удалить из Проводника во время монтажа."""
        src = getattr(self, "actual_source_file", None)
        if not src:
            return None
        src = str(src)
        if self._scrub_audio_player is None:
            self._scrub_audio_player = QMediaPlayer()
            self._scrub_audio_output = QAudioOutput()
            self._scrub_audio_player.setAudioOutput(self._scrub_audio_output)
            try:
                self._scrub_audio_output.setVolume(self.vol_slider.value() / 100.0)
            except Exception:
                pass
        if self._scrub_audio_src != src:
            old = self._scrub_audio_dev
            dev = ShareDeleteIODevice(src)
            opened = False
            try:
                opened = dev.open()
            except Exception:
                opened = False
            try:
                if opened:
                    self._scrub_audio_dev = dev
                    self._scrub_audio_player.setSourceDevice(dev, QUrl.fromLocalFile(src))
                else:
                    self._scrub_audio_dev = None
                    self._scrub_audio_player.setSource(QUrl.fromLocalFile(src))
                self._scrub_audio_src = src
            except Exception:
                self._scrub_audio_src = None
                return None
            if old is not None and old is not dev:
                QTimer.singleShot(0, lambda d=old: self._close_play_device(d))
        return self._scrub_audio_player

    def _scrub_audio_blip(self, painted):
        """Короткий звуковой блип (~150 мс) в текущей целевой позиции шага. Видео
        не трогаем. Источник звука:
          • выбрана внешняя озвучка → её отдельный плеер (звук видео заглушён);
          • painted-режим → отдельный скраб-плеер по оригиналу;
          • overlay-режим → ничего (там звук даст основной player.play() ниже)."""
        if not getattr(self, "_scrub_audio_enabled", True):
            return
        tgt = self._scrub_target
        if tgt is None:
            try:
                tgt = self.player.position()
            except Exception:
                return
        if getattr(self, "_ext_audio_active", False) and self._ext_audio_player is not None:
            player = self._ext_audio_player
        elif painted:
            player = self._ensure_scrub_audio_player()
        else:
            return
        if player is None:
            return
        try:
            player.setPosition(int(max(0, tgt)))
            player.play()
        except Exception:
            return
        self._scrub_blip_player = player
        # Один таймер, перезапускаемый на каждом шаге: при удержании ←/→ звук
        # идёт непрерывно, а после отпускания глохнет.
        if self._scrub_blip_timer is None:
            self._scrub_blip_timer = QTimer(self)
            self._scrub_blip_timer.setSingleShot(True)
            self._scrub_blip_timer.timeout.connect(self._stop_scrub_audio_blip)
        self._scrub_blip_timer.start(150)

    def _stop_scrub_audio_blip(self):
        p = getattr(self, "_scrub_blip_player", None)
        if p is not None:
            try:
                p.pause()
            except Exception:
                pass

    def set_scrub_audio(self, enabled, save=True):
        """Вкл/выкл скраб-звук при покадровой перемотке (из Настроек)."""
        self._scrub_audio_enabled = bool(enabled)
        if not enabled:
            self._stop_scrub_audio_blip()
        if save:
            try:
                self.save_settings()
            except Exception:
                pass

    def _end_scrub(self):
        self.player.pause()
        # play() ушёл вперёд на ~2 кадра — возвращаем плеер РОВНО на целевой кадр,
        # иначе шаг назад визуально «отскакивал» вперёд (баг).
        tgt = getattr(self, "_scrub_target", None)
        if tgt is not None:
            self.player.setPosition(int(tgt))
            self._ext_audio_seek(int(tgt))
        # Сбрасываем флаг после того, как событие паузы будет обработано.
        QTimer.singleShot(40, lambda: setattr(self, "_scrubbing", False))

    # ── Export / Cut ──────────────────────────────────────────────────────
    def _available_encoders(self):
        """Строка `ffmpeg -encoders` (детект один раз, кэшируется). Пустая строка
        трактуется как «всё доступно» (не смогли опросить сборку)."""
        cache = getattr(self, "_encoders_str", None)
        if cache is not None:
            return cache
        encoders = ""
        try:
            p = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", creationflags=CREATE_NO_WINDOW)
            encoders = p.stdout or ""
        except Exception:
            encoders = ""
        self._encoders_str = encoders
        return encoders

    def _gpu_encoder_args(self, encoders, hardsub=False):
        """Первый доступный аппаратный (GPU) H.264-кодировщик, иначе None.
        При hardsub (вшивание субтитров) поджимаем качество, чтобы края текста
        не мылились."""
        q = 18 if hardsub else 20
        if "h264_nvenc" in encoders:
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(q)]
        if "h264_qsv" in encoders:
            return ["-c:v", "h264_qsv", "-global_quality", str(q)]
        if "h264_amf" in encoders:
            return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                    "-qp_i", str(q), "-qp_p", str(q)]
        if "h264_mf" in encoders:
            qual = 80 if hardsub else 70
            return ["-c:v", "h264_mf", "-rate_control", "quality", "-quality", str(qual)]
        return None

    def _video_encoder_args(self, hardsub=False):
        """Подбирает H.264-кодировщик в bundled ffmpeg с учётом выбора
        пользователя (combo «Кодировщик»): «Видеокарта (GPU)» — аппаратный
        кодек; «Процессор (CPU)» / «Авто» — libx264. Если выбранного варианта в
        сборке нет — мягкий откат (GPU↔CPU↔mpeg4), чтобы перекодировка всегда
        состоялась.

        hardsub=True (вшивание субтитров): берём чуть более качественный профиль —
        у текста резкие края, и на «fast»/высоком CRF они мылятся. CPU: preset
        medium + crf 17; добавляем -pix_fmt yuv420p для чёткого 8-битного вывода и
        совместимости. Аппаратные кодеки тоже поджимаем по качеству."""
        encoders = self._available_encoders()
        # 0 = Авто, 1 = Процессор (CPU), 2 = Видеокарта (GPU)
        try:
            choice = int(self.cmb_encoder.currentIndex())
        except Exception:
            choice = 0

        cpu_args = (["-c:v", "libx264", "-preset", "medium", "-crf", "17"]
                    if hardsub else ["-c:v", "libx264", "-preset", "fast", "-crf", "18"])
        cpu = cpu_args if ("libx264" in encoders or encoders == "") else None
        gpu = self._gpu_encoder_args(encoders, hardsub=hardsub)

        if choice == 2:                      # GPU — с откатом на CPU
            args = gpu or cpu
        elif choice == 1:                    # CPU — с откатом на GPU
            args = cpu or gpu
        else:                                # Авто: CPU (качество/совместимость)
            args = cpu or gpu
        if args is None:
            args = ["-c:v", "mpeg4", "-q:v", "3"]
        args = list(args)
        if hardsub and "-pix_fmt" not in args:
            args += ["-pix_fmt", "yuv420p"]
        return args

    def _subs_present_in_range(self, src, ext_sub, rel_idx, in_s, out_s):
        """True, если хотя бы одно событие субтитров видно в диапазоне [in_s, out_s].

        Через ffprobe читаем тайминги пакетов выбранной дорожки субтитров и
        проверяем пересечение [start, start+duration] с [in_s, out_s]. Если в
        отрезке субтитров нет, вшивать нечего → можно резать без перекодировки.
        При ошибке probe (или неизвестной длительности событий) возвращаем True —
        безопасный путь: вшиваем как обычно, чтобы не потерять субтитры."""
        if ext_sub:
            target, sel = str(ext_sub), "s:0"
        else:
            target, sel = str(src), f"s:{rel_idx}"
        cmd = [FFPROBE, "-v", "error", "-select_streams", sel,
               "-show_entries", "packet=pts_time,duration_time",
               "-of", "csv=p=0", target]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=CREATE_NO_WINDOW, timeout=30)
        except Exception:
            return True
        if r.returncode != 0:
            return True
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            try:
                start = float(parts[0])
            except Exception:
                continue
            # Неизвестная длительность (N/A — напр. у битмап-субтитров) → берём
            # запас 10 с, чтобы скорее «оставить вшивание», чем ошибочно пропустить.
            try:
                dur = float(parts[1]) if len(parts) > 1 and parts[1] not in ("", "N/A") else 10.0
            except Exception:
                dur = 10.0
            if (start + dur) >= in_s and start <= out_s:
                return True
        return False

    def start_cut(self):
        if not self.actual_source_file or not self.actual_source_file.exists():
            QMessageBox.warning(self, "Внимание", "Файл не загружен.")
            return
        # Не запускаем вторую обрезку поверх уже идущей: иначе ссылка на прежний
        # рабочий поток терялась бы (его перетирал новый), и поток мог «висеть» —
        # отсюда баг «следующая обрезка не работает, надо перезапускать». Кнопка
        # на время обрезки и так выключена, но Ctrl+S мог обойти эту блокировку.
        # И быстрая обрезка (FfmpegWorker), и Smart Cut (SmartCutWorker) кладутся
        # в self.ffmpeg_thread — одной проверки достаточно.
        th = getattr(self, "ffmpeg_thread", None)
        if th is not None and th.isRunning():
            return

        # Режим картинки: «Обрезать» = собрать видео-проявление из картинки.
        if getattr(self, "is_still_image", False):
            self._export_still_pixelize()
            return

        in_s  = self.current_in
        out_s = self.current_out
        try:
            manual_in  = time_to_s(self.in_time_edit.text())
            manual_out = time_to_s(self.out_time_edit.text())
            in_s  = max(0.0, min(manual_in,  self.duration))
            out_s = max(0.0, min(manual_out, self.duration))
        except Exception:
            pass

        if out_s <= in_s:
            QMessageBox.warning(self, "Внимание", "Конечная точка должна быть позже начальной.")
            return

        mode = self.cmb_mode.currentIndex()
        # Субтитры можно вшить, если выбрана любая дорожка (встроенная или внешний
        # файл) — пункт 0 = «Выкл».
        burn_subs = (self.chk_burn_subs.isChecked() and mode != 2
                     and self.cmb_subs.currentIndex() > 0)
        # Оптимизация: если субтитры просят вшить, но в выбранном отрезке по факту
        # нет ни одного события субтитров — вшивать нечего. Отключаем hardsub, и
        # тогда в режиме «Быстро» обрезка пойдёт без перекодировки (lossless).
        if burn_subs and not self._subs_present_in_range(
                self.actual_source_file, self.selected_sub_ext_path,
                self.cmb_subs.currentIndex() - 1, in_s, out_s):
            burn_subs = False
            self.log_label.setText(
                icon_html('fa5s.info-circle', 12, C['text2'])
                + " В отрезке нет субтитров — вшивание пропущено")
            self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log("Монтаж: в выбранном отрезке нет субтитров — "
                              "вшивание пропущено, обрезка без перекодировки.")
        # Кадрирование видео несовместимо с copy-путями (Smart Cut копирует
        # середину, «Быстро» копирует поток целиком) — crop требует перекодировки.
        # При активной рамке принудительно переходим на полную перекодировку.
        crop_active = self._video_crop_filter() is not None
        # Пикселизация (эффект -vf) тоже несовместима с copy/Smart Cut — требует
        # перекодировки, как и кадрирование.
        pix_active = getattr(self, "_pixelize_active", False)
        # Smart Cut несовместим с вшиванием субтитров (середина копируется): при
        # запросе hardsub откатываемся на полную перекодировку (mode 1).
        if mode == 3:
            if burn_subs or crop_active or pix_active:
                self._execute_cut(in_s, out_s, 1, burn_subs)
            else:
                self._execute_smartcut(in_s, out_s)
            return
        if (crop_active or pix_active) and mode == 0:
            mode = 1  # быстрый copy не умеет crop/pixelize → перекодируем
        self._execute_cut(in_s, out_s, mode, burn_subs)

    def _export_still_pixelize(self):
        """Собирает ВИДЕО-проявление из загруженной картинки: кадр зацикливается
        (-loop 1) на заданную длительность, по нему идёт цепочка пикселизации
        (offset=0 — фильтрграф стартует с нуля) и, при наличии, кадрирование.
        Требует включённой пикселизации — в этом весь смысл режима картинки."""
        src = self.still_image_path or self.actual_source_file
        if not src or not os.path.exists(str(src)):
            QMessageBox.warning(self, "Внимание", "Картинка не загружена.")
            return
        if not getattr(self, "_pixelize_active", False):
            QMessageBox.information(
                self, "Пикселизация",
                "Включите «Пикселизацию» (кнопка с сеткой) — для картинки именно она "
                "и создаёт видео-проявление.")
            return
        src = Path(src)
        dur = max(1.0, float(self._still_duration))
        fps = max(1, int(self._still_fps))
        # Цепочка: кадрирование (если есть) → пикселизация (offset=0) → чётные
        # размеры под yuv420p/h264.
        crop_vf = self._video_crop_filter()
        pix_vf = self._video_pixelize_filter(dur, 0.0)
        chain = [p for p in (crop_vf, pix_vf) if p]
        chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        vf = ",".join(chain)

        out_dir = (Path(self.export_dir) if (self.export_dir and os.path.isdir(self.export_dir))
                   else src.parent)
        final_out = str(out_dir / f"{src.stem}_пиксель.mp4")
        if os.path.exists(final_out):
            final_out = _unique_output(final_out)

        venc = self._video_encoder_args(hardsub=False)
        cmd = [FFMPEG, "-y", "-loop", "1", "-framerate", str(fps), "-i", str(src),
               "-t", s_to_time(dur), "-vf", vf] + venc \
              + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", final_out]

        self._report_progress(0, "Создание видео…")
        self.log_label.setText("Создание видео из картинки…")
        self._set_cut_status("Пикселизация… подготовка", icon='fa5s.hourglass-half')
        self.btn_cut.setEnabled(False)
        self._cut_t0 = time.time(); self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = QTimer(self); self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        self.ffmpeg_thread = FfmpegWorker(cmd, duration=dur)
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)

        def _on_finished(success, message, _final=final_out):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self.btn_cut.setEnabled(True)
            if success and os.path.exists(_final):
                try:
                    if self.main is not None and hasattr(self.main, "log"):
                        self.main.log(f"Видео-проявление из картинки готово: {_final}")
                except Exception:
                    pass
                self.on_ffmpeg_finished(True, message)
            else:
                if _final and os.path.exists(_final) and not success:
                    try: os.remove(_final)
                    except Exception: pass
                self.on_ffmpeg_finished(success, message)

        self.ffmpeg_thread.finished.connect(_on_finished)
        self.ffmpeg_thread.start()

    def _execute_cut(self, in_s, out_s, mode, burn_subs,
                     src=None, force_overwrite=False, out_path=None):
        """Собирает и запускает ffmpeg-обрезку для диапазона [in_s, out_s].
        `src` позволяет перекодировать из ОРИГИНАЛА (для предложения «перекодировать
        с потерями» после неточной copy-обрезки), `force_overwrite` — перезаписать
        результат принудительно. `out_path` — точный путь вывода: пере-рез после
        неточной быстрой обрезки переиспользует имя ИМЕННО того файла, который он
        заменяет (его уже удалил _discard_temp_cut), а не пересобирает базовое имя
        `{stem}_обрез` — иначе перекодировка затёрла бы ДРУГУЮ, более раннюю обрезку
        того же исходника, занявшую это базовое имя."""
        src = Path(src) if src else self.actual_source_file
        if not src or not src.exists():
            QMessageBox.warning(self, "Внимание", "Файл не загружен.")
            return

        stem = src.stem; suffix = src.suffix
        if self.export_dir and os.path.isdir(self.export_dir):
            out_dir = Path(self.export_dir)
        else:
            out_dir = src.parent

        if out_path:
            final_out = str(out_path)
        elif mode == 2:
            final_out = str(out_dir / f"{stem}_обрез.mp3")
        else:
            final_out = str(out_dir / f"{stem}_обрез{suffix}")

        replace_original = force_overwrite or self.chk_overwrite.isChecked()
        # Повторная обрезка того же исходника НЕ затирает предыдущий клип: 2-й
        # файл сохраняется под именем с суффиксом (foo_обрез.mp4 → foo_обрез_1.mp4,
        # _2, …). Перезапись остаётся только для внутренней пере-обрезки
        # (force_overwrite / явный out_path) и правки «на месте» (цель == открытый файл).
        if os.path.exists(final_out) and not force_overwrite and not out_path:
            loaded = str(self.actual_source_file) if self.actual_source_file else ""
            in_place = bool(loaded) and os.path.normpath(loaded) == os.path.normpath(final_out)
            if not (self.chk_overwrite.isChecked() and in_place):
                final_out = _unique_output(final_out)

        tf = tempfile.NamedTemporaryFile(delete=False, suffix=Path(final_out).suffix)
        tf.close(); temp_out = tf.name

        dur_cut = out_s - in_s
        in_str  = s_to_time(in_s)
        out_str = s_to_time(out_s)
        dur_str = s_to_time(dur_cut)

        # Внешняя озвучка (отдельный аудиофайл): подмешиваем её вторым входом и
        # берём звук из него. Применяется только если она выбрана и существует.
        ext_audio = self.selected_audio_ext_path
        if ext_audio and not os.path.exists(ext_audio):
            ext_audio = None

        # Если в контейнере несколько аудиодорожек и выбрана конкретная —
        # сохраняем именно её (видео + выбранная аудиодорожка). Иначе поведение
        # по умолчанию (ffmpeg сам берёт по одной дорожке каждого типа).
        sel_a = self.selected_audio_abs_index
        pick_audio = (sel_a is not None and len(self._audio_streams) > 1)
        amap = ["-map", "0:v:0", "-map", f"0:{sel_a}"] if pick_audio else []

        # Внешняя дорожка субтитров (файл рядом) — отдельный путь, иначе индекс
        # встроенной дорожки.
        ext_sub = self.selected_sub_ext_path
        burn_idx = self.cmb_subs.currentIndex() - 1
        # Кадрово-точной осталась только перекодировка; в режиме copy отслеживаем,
        # удалось ли обрезать без потерь по кадрам (для уведомления пользователю).
        exact_copy = (mode == 0 and not burn_subs and not ext_audio)
        venc = self._video_encoder_args(hardsub=burn_subs)
        # Кадрирование видео (рамка на холсте). crop умеет только перекодировка,
        # поэтому при активной рамке start_cut уже перевёл mode на 1. Здесь
        # фильтр добавляется к видеоцепочке (отдельным -vf либо в начало цепочки
        # субтитров, если идёт вшивание).
        crop_vf = self._video_crop_filter()
        # Пикселизация-проявление (эффект по времени клипа). Требует перекодировки;
        # если внутренний пере-рез вызвал _execute_cut с mode 0 при активном
        # эффекте — поднимаем до перекодировки. `pix_on` — будет ли эффект вообще
        # добавлять фильтр (от offset это не зависит), а сам фильтр строится с
        # правильным смещением времени отдельно в каждой ветке (см. _vf_args ниже).
        pix_on = self._video_pixelize_filter(dur_cut, 0.0) is not None
        if pix_on and mode == 0:
            mode = 1
        # Любой видеофильтр (crop/pixelize) — это перекодировка, а не lossless-copy:
        # не вводим в заблуждение уведомитель точности реза.
        if crop_vf or pix_on:
            exact_copy = False

        def _vf_args(offset):
            """Аргументы -vf для текущей ветки: crop (без времени) + пикселизация со
            смещением `offset` (время фильтрграфа в начале клипа — зависит от способа
            seek в ветке). Пустой список, если фильтровать нечего."""
            chain = [p for p in (crop_vf, self._video_pixelize_filter(dur_cut, offset)) if p]
            return ["-vf", ",".join(chain)] if chain else []

        fonts_dir = None
        if burn_subs:
            # Hardsub всегда требует перекодировки. Используем ВЫХОДНОЙ seek
            # (-ss после -i), чтобы субтитры не разъехались по времени с кадрами.
            # libass рендерит ASS со всеми стилями; для родных ШРИФТОВ извлекаем
            # вложенные attachments контейнера и отдаём их через :fontsdir.
            if ext_sub:
                esc = self._escape_filter_path(ext_sub)
                vf = f"subtitles='{esc}'"
                sub_codec = os.path.splitext(ext_sub)[1].lower().lstrip('.')
            else:
                esc = self._escape_filter_path(src)
                vf = f"subtitles='{esc}':si={burn_idx}"
                try:
                    sub_codec = (self._sub_streams[burn_idx].get('codec_name') or '').lower()
                except Exception:
                    sub_codec = ''
            # Стиль вшиваемых субтитров — по выбору пользователя (cmb_sub_style):
            #   0 Авто      — стиль программы для SRT/VTT/mov_text, у ASS/SSA свой;
            #   1 Программа — насильно стиль программы даже поверх ASS/SSA;
            #   2 Оригинал  — ничего не навязываем (ASS/SSA — свой стиль, SRT/VTT —
            #                 стиль libass по умолчанию).
            try:
                style_choice = int(self.cmb_sub_style.currentIndex())
            except Exception:
                style_choice = 0
            native_styled = sub_codec in ('ass', 'ssa')
            if style_choice == 1:
                apply_prog_style = True
            elif style_choice == 2:
                apply_prog_style = False
            else:
                apply_prog_style = not native_styled
            if apply_prog_style:
                # Белый жирный шрифт с чёрной обводкой — РОВНО как в превью монтажа.
                # Превью рисует текст высотой 5.2% кадра (см. VideoCanvas.paintEvent
                # px=...*0.052). Текстовые субтитры libass рендерит в скрипте 384×288
                # (дефолт libav) и масштабирует до кадра, поэтому Fontsize=15 даёт
                # 15/288 ≈ 5.2% высоты кадра НА ЛЮБОМ разрешении. Прежний Fontsize=28
                # давал ~2× (на FullHD субтитры «огромные» — это и был баг).
                style = ("FontName=Arial,Fontsize=15,Bold=1,"
                         "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                         "BorderStyle=1,Outline=1,Shadow=0,MarginV=14")
                vf += f":force_style='{style}'"
            fonts_dir = self._extract_subtitle_fonts(src)
            if fonts_dir:
                fesc = self._escape_filter_path(fonts_dir)
                vf += f":fontsdir='{fesc}'"
            # Кадрируем ДО субтитров: libass рисует на уже обрезанном кадре, и
            # текст не уезжает за пределы кадрированной области.
            if crop_vf:
                vf = f"{crop_vf},{vf}"
            # Пикселизацию применяем ПОСЛЕ субтитров — иначе текст тоже размоется
            # в мозаику и станет нечитаемым. Обе ветки вшивания используют ВЫХОДНОЙ
            # seek, поэтому смещение времени = in_s.
            _pix = self._video_pixelize_filter(dur_cut, in_s)
            if _pix:
                vf = f"{vf},{_pix}"
            if ext_audio:
                # Видео+субтитры из исходника (вход 0), звук — из внешнего файла
                # (вход 1). Выходной seek (-ss/-t как опции вывода) равно режет оба.
                # -sn: субтитры ВШИТЫ в кадр (-vf subtitles), отдельная мягкая
                # дорожка не нужна — и, что важнее, при выходном seek её копия
                # тащит длительность всего эпизода (см. -sn ниже).
                cmd = [FFMPEG, "-y", "-i", str(src), "-i", ext_audio,
                       "-ss", in_str, "-t", dur_str,
                       "-map", "0:v:0", "-map", "1:a:0", "-vf", vf] \
                      + venc + ["-c:a", "aac", "-b:a", "192k", "-sn", temp_out]
            else:
                # Аудио НЕ перекодируем (контейнер тот же → совместимо).
                # -sn ОБЯЗАТЕЛЕН: без явного -map ffmpeg авто-включает в вывод и
                # субтитровый поток исходника; при выходном seek его копия не
                # режется и сообщает длительность ВСЕГО эпизода (~11 мин вместо
                # 7 сек) — отсюда баг «обрезка с сабами даёт 11 минут». Субтитры
                # уже вшиты в кадр (-vf subtitles), мягкая дорожка не нужна.
                cmd = [FFMPEG, "-y", "-i", str(src), "-ss", in_str, "-t", dur_str] \
                      + amap + ["-vf", vf] + venc + ["-c:a", "copy", "-sn", temp_out]
        elif ext_audio and mode != 2:
            # Внешняя озвучка без вшивания субтитров. Видео берём по режиму
            # (copy/перекодировка), звук — из внешнего файла (перекодируем в AAC,
            # т.к. контейнер/кодек могут не совпадать).
            vargs = ["-c:v", "copy"] if (mode == 0 and not crop_vf and not pix_on) else venc
            # ВХОДНОЙ seek по видео (-ss до -i src) → фильтрграф стартует с 0.
            cmd = [FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                   "-ss", in_str, "-i", ext_audio, "-t", dur_str,
                   "-map", "0:v:0", "-map", "1:a:0"] \
                  + _vf_args(0.0) + vargs + ["-c:a", "aac", "-b:a", "192k", temp_out]
        elif mode == 0:
            # Быстрая обрезка (copy) — ВХОДНОЙ seek к точке реза (-ss ДО -i).
            #
            # РАНЬШЕ резали ВЫХОДНЫМ seek (-ss ПОСЛЕ -i): он давал верную
            # длительность, НО видео при copy «прилипало» к СЛЕДУЮЩЕМУ ключевому
            # кадру (за точкой реза), и его PTS оставался > 0, тогда как звук
            # стартовал с 0. На AV1/MP4 это давало баг «первый кадр застывает на
            # несколько секунд в начале» (video start_time 5.7с против audio 0):
            # плеер держал первый кадр, пока звук играл в пустоту до прихода видео.
            #
            # Входной seek встаёт на ближайший ключевой кадр ≤ in_s, поэтому видео
            # И звук стартуют с НУЛЯ (выровнены) — дырки/застывания нет. На MP4
            # ffmpeg к тому же пишет edit-list и кадрово-точно показывает с in_s;
            # на MKV (edit-list нет) начало прилипает к ключевому кадру — это
            # нормальное поведение lossless-copy, его ловит _notify_cut_accuracy и
            # предлагает Smart Cut.
            #   • -fflags +genpts — демуксер генерит недостающие PTS (без него
            #     mpeg4/DivX в MKV падали с -22 «unknown timestamp», ошибка
            #     4294967274). Это и был реальный фикс -22, а не выходной seek.
            #   • рез по ДЛИТЕЛЬНОСТИ -t (НЕ входной -to: тот на mpeg4 давал 12с
            #     вместо 7с; -t считается от точки seek и надёжен).
            cmd = [FFMPEG, "-y", "-fflags", "+genpts",
                   "-ss", in_str, "-i", str(src), "-t", dur_str] \
                  + amap + ["-c", "copy", temp_out]
        elif mode == 1:
            # Перекодировка с КАДРОВОЙ точностью. Точность реза целиком даёт
            # ВЫХОДНОЙ seek (-ss/-t ПОСЛЕ -i): ffmpeg режет ровно по кадру, не
            # «прилипая» к ключевому кадру и не сбиваясь на контейнерах со
            # смещённым start_time (MKV/WEB-DL); копируемый звук режется тем же
            # выходным -ss ровно до in_s.
            #
            # Раньше выходной seek шёл ОТ НАЧАЛА файла (-i src -ss in): чтобы
            # вырезать 6 c у конца 23-мин эпизода, ffmpeg сперва ~23 мин
            # декодировал «вхолостую» — медленно, и прогресс всё это время висел
            # в фазе «подготовка» (ffmpeg не шлёт time=, пока не дойдёт до реза).
            #
            # Ускорение: добавляем БЫСТРЫЙ входной pre-seek к точке за PRESEEK
            # секунд до реза — ffmpeg сам встаёт на ближайший ключевой кадр
            # ≤ pre_ss и декодирует только оттуда (секунды вместо минут, прогресс
            # сразу идёт 0→100%). ТОЧНЫЙ рез по-прежнему делает выходной -ss.
            # Проверено покадрово (framemd5 видео + md5 аудио идентичны старому
            # пути на mp4/mkv/WEB-DL +10c/edit-list, h264/hevc, у границ и в конце):
            #   • выходной -ss отсчитывается от ЗАПРОШЕННОГО pre_ss (а не от того,
            #     куда «прилип» seek) → подстройка по кадру не зависит от GOP,
            #     детектировать ключевые кадры не нужно;
            #   • выходной -ss режет и КОПИРУЕМЫЙ звук ровно до in_s — без него
            #     (чистый входной seek) звук «съезжает» на ~PRESEEK раньше видео;
            #   • входной -ss задаётся в контентной шкале (ffmpeg прибавляет
            #     start_time) → смещённый start_time рез не ломает.
            # out_ss считаем от фактической (округлённой до мс) точки pre-seek,
            # чтобы итоговая точка реза совпала с round_ms(in_s) старого пути.
            # При in_s ≤ 2*PRESEEK старый путь и так быстр (декод ≤ пары секунд) и
            # обходит особенность входного seek к самому нулю на контейнерах со
            # смещением — оставляем выходной seek от начала.
            # -sn ОБЯЗАТЕЛЕН: без явного -map ffmpeg авто-включает субтитровый
            # поток, который при выходном seek не режется и сообщает длительность
            # всего эпизода (~11 мин). Этот режим запускается в т.ч. как fallback
            # после неточной copy-обрезки (_notify_cut_accuracy) — поэтому баг
            # «11 минут» всплывал и без явного вшивания субтитров.
            PRESEEK = 3.0
            if in_s > 2 * PRESEEK:
                pre_str = s_to_time(in_s - PRESEEK)
                out_ss = s_to_time(in_s - time_to_s(pre_str))
                # ВХОДНОЙ pre-seek (pre_str) + ВЫХОДНОЙ -ss (out_ss): клип в шкале
                # фильтрграфа начинается на t = out_ss.
                cmd = [FFMPEG, "-y", "-ss", pre_str, "-i", str(src),
                       "-ss", out_ss, "-t", dur_str] \
                      + amap + _vf_args(time_to_s(out_ss)) + venc + ["-c:a", "copy", "-sn", temp_out]
            else:
                # Чистый ВЫХОДНОЙ seek → фильтрграф видит исходное время, offset = in_s.
                cmd = [FFMPEG, "-y", "-i", str(src), "-ss", in_str, "-t", dur_str] \
                      + amap + _vf_args(in_s) + venc + ["-c:a", "copy", "-sn", temp_out]
        elif ext_audio:
            # Только аудио (MP3) из внешней озвучки.
            cmd = [FFMPEG, "-y", "-ss", in_str, "-i", ext_audio,
                   "-t", dur_str, "-map", "0:a:0",
                   "-c:a", "libmp3lame", "-q:a", "2", temp_out]
        else:
            astream = sel_a if sel_a is not None else self.audio_stream_index
            if astream is not None:
                cmd = [FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                       "-t", dur_str, "-map", f"0:{astream}",
                       "-c:a", "libmp3lame", "-q:a", "2", temp_out]
            else:
                cmd = [FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                       "-t", dur_str, "-vn", "-c:a", "libmp3lame", "-q:a", "2", temp_out]

        self._report_progress(0, "Обрезка…")
        self.log_label.setText("Обрезка...")
        self._set_cut_status("Обрезка… подготовка", icon='fa5s.hourglass-half')
        self.btn_cut.setEnabled(False)

        # Прогресс с ETA. Тикер раз в 0.5с обновляет «прошло/ETA», чтобы строка
        # не выглядела зависшей, даже если ffmpeg редко шлёт time= (короткие
        # отрезки или фаза перемотки декодером до точки реза).
        self._cut_t0 = time.time()
        self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = QTimer(self)
            self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        self.ffmpeg_thread = FfmpegWorker(cmd, duration=dur_cut)
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)

        def _on_finished(success, message, _temp=temp_out, _final=final_out,
                         _exact=exact_copy, _reqdur=dur_cut, _burn=burn_subs,
                         _fonts=fonts_dir, _in=in_s, _out=out_s, _src=src):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self.btn_cut.setEnabled(True)
            # Чистим временную папку извлечённых шрифтов (если была).
            if _fonts:
                try:
                    import shutil
                    shutil.rmtree(_fonts, ignore_errors=True)
                except Exception:
                    pass
            if success and _temp:
                try:
                    is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                                 os.path.normpath(_final))
                    if replace_original and os.path.exists(_final):
                        try:
                            os.remove(_final)
                        except OSError:
                            # Цель занята другим процессом (её читает «Обработка») —
                            # не падаем: _replace_tolerant ниже уведёт результат на
                            # свободное имя.
                            pass
                    if os.path.exists(_final) and not replace_original:
                        if os.path.exists(_temp):
                            os.remove(_temp)
                        self.on_ffmpeg_finished(False, "Файл уже существует (логическая ошибка)")
                        return
                    saved_final = self._replace_tolerant(_temp, _final)
                    if os.path.normpath(saved_final) != os.path.normpath(_final):
                        # Имя сменилось: целевой файл был занят (его читала другая
                        # вкладка). Сообщаем и дальше работаем с фактическим путём.
                        self._notify_busy_rename(_final, saved_final)
                        _final = saved_final
                        is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                                     os.path.normpath(_final))
                    # Точность обрезки проверяем ДО перезагрузки. Если copy-обрезка
                    # вышла не кадрово-точной — спрашиваем, что делать с фрагментом.
                    action = self._notify_cut_accuracy(_final, _reqdur, _exact, _burn,
                                                       _in, _out, _src)
                    if action == 'encode':
                        # Пользователь выбрал переделать перекодировкой — неточный
                        # файл быстрой обрезки больше не нужен, удаляем его (иначе
                        # при выключенной перезаписи останется осиротевший дубль,
                        # а результат уедет в «…_обрез_1»).
                        self._discard_temp_cut(_final, is_loaded)
                        QTimer.singleShot(0, lambda: self._execute_cut(
                            _in, _out, 1, _burn, src=_src,
                            force_overwrite=True, out_path=_final))
                        return
                    if action == 'smartcut':
                        # То же и для Smart Cut: создаст точный файл под тем же
                        # именем — неточный результат быстрой обрезки удаляем.
                        self._discard_temp_cut(_final, is_loaded)
                        QTimer.singleShot(0, lambda: self._execute_smartcut(
                            _in, _out, out_path=_final))
                        return
                    if action == 'delete':
                        # Удаляем созданный неточный файл по просьбе пользователя.
                        # Если он сейчас открыт в плеере — сперва освобождаем источник.
                        try:
                            if is_loaded:
                                # Освобождаем файл: останавливаем плеер и снимаем источник.
                                try: self.player.stop()
                                except Exception: pass
                                try: self.player.setSource(QUrl())
                                except Exception: pass
                            if os.path.exists(_final):
                                os.remove(_final)
                            self.log_label.setText(
                                icon_html('fa5s.trash', 12, C['text2']) + " Файл удалён")
                            self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
                            self._report_progress(0, "Файл удалён")
                        except Exception as e:
                            QMessageBox.warning(self, "Не удалось удалить",
                                                f"Не удалось удалить файл:\n{e}")
                        return
                    if is_loaded:
                        self.load_file(_final)
                    self.on_ffmpeg_finished(True, message)
                except Exception as e:
                    try:
                        if os.path.exists(_temp):
                            os.remove(_temp)
                    except Exception:
                        pass
                    self.on_ffmpeg_finished(False, f"Ошибка при сохранении: {e}")
            else:
                if _temp and os.path.exists(_temp):
                    try:
                        os.remove(_temp)
                    except Exception:
                        pass
                self.on_ffmpeg_finished(success, message)

        self.ffmpeg_thread.finished.connect(_on_finished)
        self.ffmpeg_thread.start()

    def _smartcut_status(self, s):
        try:
            self.log_label.setText(s)
            self._set_cut_status(s, icon='fa5s.cut')
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(s)
        except Exception:
            pass

    def _execute_smartcut(self, in_s, out_s, out_path=None):
        """Запускает умную обрезку (SmartCutWorker): граничные участки от точек
        реза до ближайших ключевых кадров перекодируются, середина копируется без
        потерь. Контейнер вывода = контейнер исходника (нужно для copy-склейки).
        `out_path` — точный путь вывода (пере-рез после неточной быстрой обрезки
        переиспользует имя заменяемого файла, а не пересобирает `{stem}_обрез`;
        см. _execute_cut)."""
        src = self.actual_source_file
        if not src or not src.exists():
            QMessageBox.warning(self, "Внимание", "Файл не загружен.")
            return
        stem = src.stem; suffix = src.suffix
        out_dir = (Path(self.export_dir)
                   if (self.export_dir and os.path.isdir(self.export_dir)) else src.parent)
        final_out = str(out_path) if out_path else str(out_dir / f"{stem}_обрез{suffix}")
        replace_original = self.chk_overwrite.isChecked() or bool(out_path)
        # Как и в _execute_cut: повторная Smart Cut обрезка того же файла не
        # затирает прошлый клип, а уходит под именем с суффиксом. Явный out_path
        # (пере-рез) указывает на уже освобождённый файл — его не переименовываем.
        if os.path.exists(final_out) and not out_path:
            loaded = str(self.actual_source_file) if self.actual_source_file else ""
            in_place = bool(loaded) and os.path.normpath(loaded) == os.path.normpath(final_out)
            if not (replace_original and in_place):
                final_out = _unique_output(final_out)
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tf.close(); temp_out = tf.name

        self._report_progress(0, "Smart Cut…")
        self.log_label.setText("Smart Cut…")
        self._set_cut_status("Smart Cut… подготовка", icon='fa5s.hourglass-half')
        self.btn_cut.setEnabled(False)
        self._cut_t0 = time.time(); self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = QTimer(self); self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        venc = self._video_encoder_args()
        # Выбранная аудиодорожка (если в контейнере их несколько). None → первая.
        sc_audio = (self.selected_audio_abs_index
                    if (self.selected_audio_abs_index is not None
                        and len(self._audio_streams) > 1) else None)
        self.ffmpeg_thread = SmartCutWorker(src, in_s, out_s, temp_out, venc,
                                            audio_index=sc_audio)
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)
        self.ffmpeg_thread.status.connect(self._smartcut_status)

        def _on_finished(success, message, _temp=temp_out, _final=final_out):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self.btn_cut.setEnabled(True)
            if success and _temp and os.path.exists(_temp) and os.path.getsize(_temp) > 0:
                try:
                    is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                                 os.path.normpath(_final))
                    if replace_original and os.path.exists(_final):
                        try:
                            os.remove(_final)
                        except OSError:
                            pass  # занят другим процессом — уйдём на свободное имя
                    if os.path.exists(_final) and not replace_original:
                        if os.path.exists(_temp):
                            os.remove(_temp)
                        self.on_ffmpeg_finished(False, "Файл уже существует (логическая ошибка)")
                        return
                    saved_final = self._replace_tolerant(_temp, _final)
                    if os.path.normpath(saved_final) != os.path.normpath(_final):
                        self._notify_busy_rename(_final, saved_final)
                        _final = saved_final
                        is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                                     os.path.normpath(_final))
                    if is_loaded:
                        self.load_file(_final)
                    self.on_ffmpeg_finished(True, message)
                except Exception as e:
                    try:
                        if os.path.exists(_temp):
                            os.remove(_temp)
                    except Exception:
                        pass
                    self.on_ffmpeg_finished(False, f"Ошибка при сохранении: {e}")
            else:
                if _temp and os.path.exists(_temp):
                    try:
                        os.remove(_temp)
                    except Exception:
                        pass
                self.on_ffmpeg_finished(success, message)

        self.ffmpeg_thread.finished.connect(_on_finished)
        self.ffmpeg_thread.start()

    def on_ffmpeg_finished(self, success, message):
        if success:
            self.log_label.setText(icon_html('fa5s.check', 12, C['green2']) + " Готово")
            self.log_label.setStyleSheet(f"color: {C['green2']}; font-size: 12px; font-weight: 600;")
            self._report_progress(100, "Готово")
            # Кратко показываем «Готово» над кнопкой, затем возвращаем «Итог: …».
            self._set_cut_status("Готово", icon='fa5s.check')
            QTimer.singleShot(1800, self._clear_cut_status)
            # Сразу обновляем верхнюю ленту файлов: если результат перезаписал файл
            # по тому же пути (напр. «…_обрез.mp4» переэкспортирован перекодировкой
            # и стал короче/легче), карточка иначе висела бы со старым превью.
            try:
                strip = getattr(self.main, "recent_strip", None)
                if strip is not None:
                    strip.force_refresh()
            except Exception:
                pass
        elif message == "Отменено":
            self.log_label.setText("Отменено")
            self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
            self._report_progress(0, "Отменено")
            self._clear_cut_status()
        else:
            self.log_label.setText(icon_html('fa5s.times', 12, C['red2']) + " Ошибка")
            self.log_label.setStyleSheet(f"color: {C['red2']}; font-size: 12px; font-weight: 600;")
            try:
                from error_report import ErrorReportDialog
                ErrorReportDialog(
                    "Ошибка", "Обрезка завершилась с ошибкой.",
                    detail=str(message), where="Монтаж: обрезка", parent=self).exec()
            except Exception:
                QMessageBox.critical(self, "Ошибка", f"Обрезка завершилась с ошибкой:\n{message}")
            self._report_progress(0, "Ошибка")
            self._clear_cut_status()

    @staticmethod
    def _escape_filter_path(p):
        """Экранирует путь для libavfilter (subtitles/fontsdir): прямые слэши +
        экранированное двоеточие диска (`C\\:`) + экранированная кавычка. Без
        экранирования двоеточия на Windows фильтр не инициализируется."""
        return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    def _extract_subtitle_fonts(self, src):
        """Извлекает вложенные шрифты (font attachments) контейнера во временную
        папку, чтобы при вшивании субтитров libass рендерил их РОДНЫМИ шрифтами
        (полная поддержка ASS-стилей). Возвращает путь к папке или None."""
        try:
            d = tempfile.mkdtemp(prefix="sihyx_fonts_")
            # -dump_attachment:t "" выгружает все attachments в текущую папку.
            # ffmpeg при этом завершается с ненулевым кодом (нет выходного файла) —
            # это ожидаемо, нас интересуют только извлечённые файлы.
            subprocess.run([FFMPEG, "-y", "-dump_attachment:t", "", "-i", str(src)],
                           cwd=d, capture_output=True, creationflags=CREATE_NO_WINDOW)
            if os.listdir(d):
                return d
            os.rmdir(d)
        except Exception:
            pass
        return None

    def _discard_temp_cut(self, path, is_loaded):
        """Удаляет неточный файл быстрой обрезки, когда пользователь решил
        переделать его (перекодировкой или Smart Cut). Если файл открыт в плеере —
        сперва освобождаем источник, иначе на Windows он залочен и не удалится.
        Ошибки глушим: переделка обрезки важнее уборки дубля."""
        try:
            if is_loaded:
                try: self.player.stop()
                except Exception: pass
                try: self.player.setSource(QUrl())
                except Exception: pass
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _notify_cut_accuracy(self, final_path, requested_dur, exact_copy, burn_subs,
                             in_s=None, out_s=None, src=None):
        """Сообщает, удалось ли обрезать БЕЗ перекодировки точно по кадрам.

        В режиме «Быстро (копирование потоков)» начало прилипает к ближайшему
        ключевому кадру, поэтому итоговая длительность может оказаться больше
        запрошенной. Сравниваем фактическую длительность результата с заданной.

        Возвращает строку с выбором пользователя:
          'encode'   — перекодировать диапазон заново (точно, с потерями);
          'smartcut' — умная обрезка (точные границы + lossless-середина);
          'delete'   — удалить созданный неточный файл;
          None       — оставить файл как есть."""
        try:
            if burn_subs:
                QMessageBox.information(
                    self, "Готово",
                    "Субтитры вшиты в видео (с перекодировкой).")
                return None
            if not exact_copy:
                # Режимы перекодировки/MP3 — всегда кадрово-точные, отдельное
                # уведомление не нужно.
                return None
            meta = run_ffprobe(final_path)
            actual = 0.0
            try:
                actual = float((meta or {}).get('format', {}).get('duration', 0.0))
            except Exception:
                actual = 0.0
            # У аудиофайла кадров нет — точность меряем/формулируем по времени.
            audio_only = (self.video_stream_index is None)
            # Допуск ~1 кадр (или 0.05 c, если FPS неизвестен / это аудио).
            tol = (1.5 / self.fps) if (self.fps and self.fps > 0
                                       and not audio_only) else 0.05
            diff = abs(actual - requested_dur) if actual > 0 else 0.0
            if actual <= 0 or diff <= tol:
                QMessageBox.information(
                    self, "Готово — точная обрезка",
                    "Обрезано без перекодировки, точно по заданным меткам времени."
                    if audio_only else
                    "Обрезано без перекодировки, точно по заданным кадрам.")
                return None
            if audio_only:
                # Для аудио Smart Cut неприменим (он про ключевые кадры видео).
                # Предлагаем только перекодировку, удаление или «оставить как есть».
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle("Не получилось точно без потерь")
                box.setText(
                    "Быстрая обрезка (копирование) НЕ попала точно по времени: "
                    "начало сдвинулось к ближайшей границе аудиокадра.\n\n"
                    f"Запрошено: {s_to_time(requested_dur)}\n"
                    f"Получилось: {s_to_time(actual)}\n"
                    f"Расхождение: {s_to_time(diff)}\n\n"
                    "Что сделать с фрагментом?")
                a_enc = a_del = None
                if in_s is not None and out_s is not None:
                    a_enc = box.addButton("Перекодировать (точно)",
                                          QMessageBox.ButtonRole.AcceptRole)
                a_del = box.addButton("Удалить файл",
                                      QMessageBox.ButtonRole.DestructiveRole)
                a_keep = box.addButton("Оставить как есть",
                                       QMessageBox.ButtonRole.RejectRole)
                box.setDefaultButton(a_keep)
                box.exec()
                clicked = box.clickedButton()
                if clicked is a_enc:
                    return 'encode'
                if clicked is a_del:
                    return 'delete'
                return None
            # Не кадрово-точно → предлагаем варианты: Smart Cut (точно + почти без
            # потерь), полную перекодировку (точно, с потерями), удалить файл или
            # оставить как есть.
            can_retry = (in_s is not None and out_s is not None)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Не получилось точно без потерь")
            box.setText(
                "Обрезка без перекодировки (быстро) НЕ кадрово-точная: начало "
                "сдвинулось к ближайшему ключевому кадру.\n\n"
                f"Запрошено: {s_to_time(requested_dur)}\n"
                f"Получилось: {s_to_time(actual)}\n"
                f"Расхождение: {s_to_time(diff)}\n\n"
                "Что сделать с фрагментом?")
            btn_smart = btn_enc = btn_del = None
            if can_retry:
                btn_smart = box.addButton("Smart Cut (точно, почти без потерь)",
                                          QMessageBox.ButtonRole.AcceptRole)
                btn_enc = box.addButton("Перекодировать (точно, с потерями)",
                                        QMessageBox.ButtonRole.AcceptRole)
            btn_del = box.addButton("Удалить файл", QMessageBox.ButtonRole.DestructiveRole)
            btn_keep = box.addButton("Оставить как есть", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_smart if btn_smart is not None else btn_keep)
            box.exec()
            clicked = box.clickedButton()
            if clicked is btn_smart:
                return 'smartcut'
            if clicked is btn_enc:
                return 'encode'
            if clicked is btn_del:
                return 'delete'
            return None
        except Exception:
            pass
        return None

    # ── Shortcuts ─────────────────────────────────────────────────────────
    def register_shortcuts(self):
        # Контекст WidgetWithChildren: хоткеи работают только когда вкладка
        # «Монтаж» в фокусе — не перехватывают Space/I/O на других вкладках.
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut

        def add_shortcut(seq, handler):
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.setShortcutContext(ctx)
            act.triggered.connect(handler)
            self.addAction(act)

        try:
            add_shortcut(Qt.Key.Key_Space, self.toggle_play)
            add_shortcut("F", self.toggle_fullscreen)
            add_shortcut("I", self.set_in_point)
            add_shortcut("O", self.set_out_point)
            add_shortcut(Qt.Key.Key_Left,  partial(self.step_frame_scrub, -1))
            add_shortcut(Qt.Key.Key_Right, partial(self.step_frame_scrub,  1))
            # WASD дублируют стрелки покадрового шага: A/S — кадр назад, D/W — вперёд.
            add_shortcut("A", partial(self.step_frame_scrub, -1))
            add_shortcut("S", partial(self.step_frame_scrub, -1))
            add_shortcut("D", partial(self.step_frame_scrub,  1))
            add_shortcut("W", partial(self.step_frame_scrub,  1))
            add_shortcut("Ctrl+S", self.start_cut)
            # Обрезка до точки воспроизведения (настраиваемые сочетания) —
            # храним QShortcut, чтобы можно было переназначить в Настройках.
            self._sc_trim_start = QShortcut(QKeySequence(self.trim_start_seq), self)
            self._sc_trim_start.setContext(ctx)
            self._sc_trim_start.activated.connect(self.trim_start_to_playhead)
            self._sc_trim_end = QShortcut(QKeySequence(self.trim_end_seq), self)
            self._sc_trim_end.setContext(ctx)
            self._sc_trim_end.activated.connect(self.trim_end_to_playhead)
            # Undo/redo: ВСЕ сочетания вешаем на ОДНО действие каждого типа через
            # setShortcuts([...]). Раньше StandardKey.Redo и явный "Ctrl+Y" были
            # ДВУМЯ разными QAction с одинаковым сочетанием (на Windows
            # StandardKey.Redo == Ctrl+Y) — Qt считал это «неоднозначным
            # сочетанием» и не срабатывал НИ ОДИН из них: Ctrl+Z работал, а
            # Ctrl+Y — нет. Один QAction с несколькими сочетаниями неоднозначности
            # не создаёт. Раскладочные дубли (рус. Я = Z, Н = Y) — тут же.
            act_undo = QAction(self)
            act_undo.setShortcuts([QKeySequence(QKeySequence.StandardKey.Undo),
                                   QKeySequence("Ctrl+Z"), QKeySequence("Ctrl+Я")])
            act_undo.setShortcutContext(ctx)
            act_undo.triggered.connect(self.undo)
            self.addAction(act_undo)
            act_redo = QAction(self)
            act_redo.setShortcuts([QKeySequence(QKeySequence.StandardKey.Redo),
                                   QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z"),
                                   QKeySequence("Ctrl+Н")])
            act_redo.setShortcutContext(ctx)
            act_redo.triggered.connect(self.redo)
            self.addAction(act_redo)
        except Exception as e:
            print("shortcuts error:", e)

    def compute_step(self, fast=False):
        step = 1.0 / self.fps if (self.fps and self.fps > 0) else 0.04
        return step * (5 if fast else 1)

    def move_in(self, dir_sign=1):
        self.push_undo()
        fast = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = self.compute_step(fast)
        new_in = max(0.0, min(self.duration, self.current_in + dir_sign * step))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - step)
        self.set_in_out(new_in, self.current_out)

    def move_out(self, dir_sign=1):
        self.push_undo()
        fast = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = self.compute_step(fast)
        new_out = max(0.0, min(self.duration, self.current_out + dir_sign * step))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + step)
        self.set_in_out(self.current_in, new_out)

    # ── Обрезка до точки воспроизведения (плейхеда) ─────────────────────────
    def trim_start_to_playhead(self):
        """Ставит точку IN на текущую позицию воспроизведения (обрезает старт)."""
        if self.duration <= 0:
            return
        self.push_undo()
        t = self.player.position() / 1000.0
        new_in = max(0.0, min(t, self.duration))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - 0.04)
        self.set_in_out(new_in, self.current_out)
        # Возвращаем фокус на вкладку: если он был на нативной видео-поверхности
        # (overlay-режим, исключена из WidgetWithChildrenShortcut), Ctrl+Z после
        # обрезки иначе не доходил до undo. Кнопка с NoFocus фокус не перехватит.
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def trim_end_to_playhead(self):
        """Ставит точку OUT на текущую позицию воспроизведения (обрезает конец)."""
        if self.duration <= 0:
            return
        self.push_undo()
        t = self.player.position() / 1000.0
        new_out = max(0.0, min(t, self.duration))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + 0.04)
        self.set_in_out(self.current_in, new_out)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _trim_ctx_menu(self, pos=None):
        """Контекстное меню аудио-визуализации (ПКМ): обрезка старт/конец до
        плейхеда. Сочетания показываются справа как подсказка (через \\t), но НЕ
        регистрируются повторно — настоящие хоткеи висят на QShortcut."""
        if self.duration <= 0:
            return
        menu = QMenu(self)
        a_start = menu.addAction(
            f"Обрезать старт до точки воспроизведения\t{self.trim_start_seq}")
        a_start.triggered.connect(self.trim_start_to_playhead)
        a_end = menu.addAction(
            f"Обрезать конец до точки воспроизведения\t{self.trim_end_seq}")
        a_end.triggered.connect(self.trim_end_to_playhead)
        menu.exec(QCursor.pos())

    def get_trim_shortcuts(self):
        """(start_seq, end_seq) — для отображения/редактирования в Настройках."""
        return (self.trim_start_seq, self.trim_end_seq)

    def set_trim_shortcuts(self, start_seq, end_seq, save=True):
        """Переназначает сочетания обрезки. Пустое значение → дефолт."""
        self.trim_start_seq = (start_seq or "Shift+C").strip() or "Shift+C"
        self.trim_end_seq   = (end_seq or "Shift+V").strip() or "Shift+V"
        try:
            if getattr(self, "_sc_trim_start", None) is not None:
                self._sc_trim_start.setKey(QKeySequence(self.trim_start_seq))
            if getattr(self, "_sc_trim_end", None) is not None:
                self._sc_trim_end.setKey(QKeySequence(self.trim_end_seq))
        except Exception:
            pass
        if save:
            self.save_settings()

    # ── Pan slider ────────────────────────────────────────────────────────
    def on_wave_view_changed(self, view_offset, visible_duration):
        self.update_pan_slider_values()
        self.update_wave_scroll()

    # ── Horizontal scrollbar over the waveform ─────────────────────────────
    def on_wave_scroll(self, value):
        """Пользователь двигает горизонтальную прокрутку → смещаем окно обзора волны."""
        duration = self.waveform.duration or self.duration or 0.0
        if duration <= 0:
            return
        self.waveform.set_view_offset(value / 1000.0)

    def update_wave_scroll(self):
        """Синхронизирует горизонтальную прокрутку с масштабом/положением волны.
        Прячется, когда прокручивать нечего (волна целиком помещается)."""
        sb = getattr(self, "wave_scroll", None)
        if sb is None:
            return
        duration = self.waveform.duration or self.duration or 0.0
        visible = max(0.001, duration / self.waveform.zoom)
        pan_range = max(0.0, duration - visible)
        if duration <= 0 or pan_range <= 1e-6:
            sb.setVisible(False)
            return
        sb.setVisible(True)
        sb.blockSignals(True)
        sb.setMinimum(0)
        sb.setMaximum(int(pan_range * 1000))
        sb.setPageStep(max(1, int(visible * 1000)))
        sb.setSingleStep(max(1, int(visible * 100)))
        sb.setValue(int(self.waveform.view_offset * 1000))
        sb.blockSignals(False)

    def update_pan_slider_values(self):
        pan_row = getattr(self, 'pan_row_w', None)
        duration = self.waveform.duration or self.duration or 0.0
        if duration <= 0:
            self.pan_slider.setEnabled(False)
            if pan_row is not None:
                pan_row.setVisible(False)
            return
        visible = max(0.001, duration / self.waveform.zoom)
        pan_range = max(0.0, duration - visible)
        if pan_range <= 0.0:
            self.pan_slider.setEnabled(False); self.pan_slider.setValue(0)
            if pan_row is not None:
                pan_row.setVisible(False)
            return
        self.pan_slider.setEnabled(True)
        if pan_row is not None:
            pan_row.setVisible(True)
        val = int((self.waveform.view_offset / pan_range) * 1000) if pan_range > 0 else 0
        self.pan_slider.blockSignals(True)
        self.pan_slider.setValue(max(0, min(1000, val)))
        self.pan_slider.blockSignals(False)

    def on_pan_moved(self, value):
        duration = self.waveform.duration or self.duration or 0.0
        if duration <= 0:
            return
        visible = max(0.001, duration / self.waveform.zoom)
        pan_range = max(0.0, duration - visible)
        offset = (value / 1000.0) * pan_range if pan_range > 0 else 0.0
        self.waveform.set_view_offset(offset)

    # ── Settings ──────────────────────────────────────────────────────────
    def save_settings(self):
        try:
            settings = {
                'mode_index': int(self.cmb_mode.currentIndex()),
                'encoder_index': int(self.cmb_encoder.currentIndex()),
                'sub_style_index': int(self.cmb_sub_style.currentIndex()),
                'overwrite':  bool(self.chk_overwrite.isChecked()),
                'burn_subs':  bool(self.chk_burn_subs.isChecked()),
                'zoom':       float(self.waveform.zoom),
                'view_offset': float(self.waveform.view_offset),
                'volume':     int(self.vol_slider.value()),   # громкость теперь сохраняется (пункт B)
                'trim_start_seq': self.trim_start_seq,
                'trim_end_seq':   self.trim_end_seq,
                'export_dir':     self.export_dir or "",
                'subs_in_frame':  bool(getattr(self, '_subs_in_frame', True)),
                'scrub_audio':    bool(getattr(self, '_scrub_audio_enabled', True)),
                'pb_quality_index': int(self.cmb_pb_quality.currentIndex())
                    if hasattr(self, 'cmb_pb_quality') else 0,
                'proxy_min': int(self.spin_proxy_min.value())
                    if hasattr(self, 'spin_proxy_min') else 0,
            }
            with open(EDITOR_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_settings(self):
        if not os.path.exists(EDITOR_SETTINGS_PATH):
            return
        try:
            with open(EDITOR_SETTINGS_PATH, "r", encoding="utf-8") as f:
                settings = json.load(f)
            self.cmb_mode.setCurrentIndex(int(settings.get('mode_index', 1)))
            self.cmb_encoder.setCurrentIndex(int(settings.get('encoder_index', 0)))
            if hasattr(self, 'cmb_pb_quality'):
                # Без сигнала: файла ещё нет, применится при загрузке.
                self.cmb_pb_quality.blockSignals(True)
                self.cmb_pb_quality.setCurrentIndex(int(settings.get('pb_quality_index', 0)))
                self.cmb_pb_quality.blockSignals(False)
            if hasattr(self, 'spin_proxy_min'):
                self.spin_proxy_min.blockSignals(True)
                self.spin_proxy_min.setValue(int(settings.get('proxy_min', 0)))
                self.spin_proxy_min.blockSignals(False)
            self.cmb_sub_style.setCurrentIndex(int(settings.get('sub_style_index', 2)))
            self.chk_overwrite.setChecked(bool(settings.get('overwrite', True)))
            self.chk_burn_subs.setChecked(bool(settings.get('burn_subs', False)))
            self.waveform.zoom        = max(0.25, min(200.0, float(settings.get('zoom', 1.0))))
            self.waveform.view_offset = max(0.0, float(settings.get('view_offset', 0.0)))
            vol = max(0, min(100, int(settings.get('volume', 100))))
            self.vol_slider.setValue(vol)
            self.audio_output.setVolume(vol / 100.0)
            self.set_trim_shortcuts(
                settings.get('trim_start_seq', self.trim_start_seq),
                settings.get('trim_end_seq', self.trim_end_seq),
                save=False)
            self.export_dir = settings.get('export_dir', "") or ""
            self._update_export_dir_label()
            # Покадровый скраб-звук теперь всегда включён (настройка убрана из UI).
            self._scrub_audio_enabled = True
        except Exception:
            pass

    # ── Cleanup (вызывается из главного окна при закрытии) ──────────────────
    def shutdown(self):
        if not self._ready:
            return
        try:
            self.save_settings()
        except Exception:
            pass
        try:
            self.sync_timer.stop()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        # Останавливаем скраб-плеер покадровой перемотки и отпускаем его файл.
        try:
            if self._scrub_blip_timer is not None:
                self._scrub_blip_timer.stop()
        except Exception:
            pass
        try:
            if self._scrub_audio_player is not None:
                self._scrub_audio_player.stop()
                self._scrub_audio_player.setSource(QUrl())
        except Exception:
            pass
        try:
            if self._scrub_audio_dev is not None:
                self._close_play_device(self._scrub_audio_dev)
                self._scrub_audio_dev = None
        except Exception:
            pass
        # Останавливаем фоновый поток превью кадров полосы воспроизведения.
        try:
            if getattr(self, 'seek_preview', None) is not None:
                self.seek_preview.shutdown()
        except Exception:
            pass
        # Убиваем все фоновые ffmpeg-процессы, чтобы не остались зомби (баг #3).
        for attr in ('ffmpeg_thread', 'proxy_thread', 'audio_worker', '_vinp_worker'):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if hasattr(w, 'stop'):
                    w.stop()
                if w.isRunning():
                    if not w.wait(2000):
                        w.terminate(); w.wait()
            except Exception:
                pass
        try:
            if getattr(self, 'audio_worker', None) and self.audio_worker.tmp_wav \
                    and os.path.exists(self.audio_worker.tmp_wav):
                os.remove(self.audio_worker.tmp_wav)
        except Exception:
            pass
        try:
            if self.tmp_proxy_file and os.path.exists(self.tmp_proxy_file):
                os.remove(self.tmp_proxy_file)
        except Exception:
            pass
        # Дожидаемся фоновых извлечений субтитров.
        for ex in list(getattr(self, '_sub_threads', [])):
            try:
                if ex.isRunning():
                    if not ex.wait(2000):
                        ex.terminate(); ex.wait()
            except Exception:
                pass
        # Останавливаем ASS-рендер (таймер + libass + временный файл).
        try:
            self._stop_ass()
        except Exception:
            pass
        # Закрываем полноэкранное окно, если открыто.
        try:
            if getattr(self, '_fs_window', None) is not None:
                self.exit_fullscreen()
        except Exception:
            pass
        # Закрываем окно-оверлей субтитров.
        try:
            if self.sub_overlay is not None:
                self.sub_overlay.close()
                self.sub_overlay.deleteLater()
                self.sub_overlay = None
        except Exception:
            pass

    def closeEvent(self, ev):
        # На случай использования вкладки как самостоятельного окна.
        self.shutdown()
        super().closeEvent(ev)


# ─── Standalone test entry point ───────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SI-HYX — Монтаж")
    app.setStyle("Fusion")
    w = EditTab()
    w.resize(1400, 900)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
