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


if _read_bool_setting("video_software_render", False):
    # Программный рендер: окно видео не создаёт аппаратный D3D/GL-свопчейн,
    # который перехватывает RivaTuner (оверлей FPS поверх видео). Кадры идут
    # через ЦП. Применяется только если пользователь включил опцию в Настройках.
    os.environ.setdefault("QSG_RHI_BACKEND", "software")
    os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", "")
else:
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from PyQt6.QtCore import (
    Qt, QUrl, QThread, pyqtSignal, QTimer, QEvent, QPoint, QRect, QSize
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSlider, QScrollBar, QFileDialog, QLineEdit, QSpinBox, QComboBox,
    QMessageBox, QProgressBar, QStyle, QStyleOptionSlider, QCheckBox, QToolTip,
    QFrame, QScrollArea, QSizePolicy
)
from PyQt6.QtGui import (
    QKeySequence, QPainter, QColor, QPen, QBrush, QAction, QShortcut,
    QFont, QLinearGradient, QPainterPath, QPixmap, QFontMetrics, QIcon, QImage
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


class ProxyWorker(QThread):
    finished = pyqtSignal(bool, str, str)

    def __init__(self, input_path, output_path, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.output_path = output_path
        self.proc = None
        self._stopped = False

    def run(self):
        # scale filter ensures even dimensions required by libx264
        base = [
            FFMPEG, "-y", "-i", str(self.input_path),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        ]
        cmds = [
            base + ["-c:a", "aac", self.output_path],
            base + ["-an",          self.output_path],
        ]
        last_error = "неизвестная ошибка"
        for cmd in cmds:
            if self._stopped:
                self.finished.emit(False, "Отменено", "")
                return
            try:
                self.proc = subprocess.Popen(
                    cmd, stderr=subprocess.PIPE, text=True,
                    encoding="utf-8", errors="replace",
                    creationflags=CREATE_NO_WINDOW)
                _, err = self.proc.communicate()
                if self._stopped:
                    self.finished.emit(False, "Отменено", "")
                    return
                if self.proc.returncode == 0:
                    self.finished.emit(True, "OK", self.output_path)
                    return
                last_error = (err or "")[-600:] or f"код {self.proc.returncode}"
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
    finished = pyqtSignal(list, float)
    progress = pyqtSignal(str)

    def __init__(self, filepath, audio_index, parent=None):
        super().__init__(parent)
        self.filepath = str(filepath)
        self.audio_index = audio_index
        self.tmp_wav = None
        self.proc = None
        self._stopped = False

    def _run_ffmpeg(self, cmd):
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW)
        self.proc.communicate()
        return self.proc.returncode == 0

    def run(self):
        self.progress.emit("Извлечение аудио...")
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tf.close()
        self.tmp_wav = tf.name

        cmd = [FFMPEG, "-y", "-i", self.filepath, "-vn"]
        if self.audio_index is not None:
            cmd += ["-map", f"0:{self.audio_index}"]
        cmd += ["-af", "aresample=6000,asetpts=PTS-STARTPTS",
                "-ac", "1", "-ar", "6000", "-f", "wav", self.tmp_wav]

        ok = False
        try:
            ok = self._run_ffmpeg(cmd)
        except Exception as e:
            print("Audio extract failed:", e)

        if not ok and not self._stopped:
            try:
                ok = self._run_ffmpeg(
                    [FFMPEG, "-y", "-i", self.filepath, "-vn",
                     "-ac", "1", "-ar", "6000", "-f", "wav", self.tmp_wav])
            except Exception:
                ok = False

        if self._stopped or not ok or not os.path.exists(self.tmp_wav):
            self._cleanup_tmp()
            self.finished.emit([], 0.0)
            return

        self.progress.emit("Генерация волны...")
        try:
            samples, duration = self.read_wav_chunked(self.tmp_wav, target_samples=8000)
        except Exception:
            samples, duration = [], 0.0
        self._cleanup_tmp()
        self.finished.emit(samples, duration)

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
        import array as _array
        try:
            wf = wave.open(wav_path, 'rb')
        except Exception:
            return [], 0.0

        n_frames  = wf.getnframes()
        framerate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        duration  = n_frames / framerate if framerate > 0 else 0.0

        if n_frames == 0:
            wf.close()
            return [], duration

        samples_per_pixel = max(1, n_frames // target_samples)
        chunk_size_frames = 256 * 1024
        downsampled: list[float] = []
        current_max = 0.0
        acc = 0

        if sampwidth == 1:
            typecode = 'B'; scale = 128.0
        elif sampwidth == 2:
            typecode = 'h'; scale = 32768.0
        elif sampwidth == 4:
            typecode = 'i'; scale = 2147483648.0
        else:
            wf.close()
            return [], duration

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
            buf_len = len(buf)
            i = 0
            while i < buf_len:
                take = min(samples_per_pixel - acc, buf_len - i)
                if take <= 0:
                    break
                chunk = buf[i: i + take]
                hi = max(chunk); lo = min(chunk)
                if typecode == 'B':
                    peak = max(abs(hi - 128), abs(lo - 128)) / scale
                else:
                    peak = max(abs(hi), abs(lo)) / scale
                if peak > current_max:
                    current_max = peak
                acc += take
                i += take
                if acc >= samples_per_pixel:
                    downsampled.append(current_max)
                    current_max = 0.0
                    acc = 0
            processed += buf_len

        wf.close()
        return downsampled or [0.0], duration


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
        self.duration = 0.0
        self.in_s = 0.0
        self.out_s = 0.0
        self.playhead_s = 0.0
        self.setMinimumHeight(90)
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

    def set_loading(self, text):
        self.loading_text = text
        self.samples = []
        self._anim_timer.start(400)
        self.update()

    def set_data(self, samples, duration):
        self.loading_text = None
        self._anim_timer.stop()
        self.samples = samples
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

        if self.samples and self.duration > 0:
            n = len(self.samples)
            scale_bg = (h / 2) * 0.75
            for i in range(0, w):
                t = self.view_offset + (i / max(1, w)) * visible_duration
                if t > self.duration:
                    break  # за пределами клипа (при отдалении zoom<1) — пусто
                idx = int((t / self.duration) * n)
                idx = max(0, min(n - 1, idx))
                val = max(0.0, min(1.0, self.samples[idx]))
                v = val * 0.8
                y1 = int(mid - v * scale_bg)
                y2 = int(mid + v * scale_bg)
                alpha = int(80 + val * 60)
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

        if self.samples and self.duration > 0:
            n = len(self.samples)
            scale_sel = (h / 2) * 0.88
            left_i = max(0, x_in); right_i = min(w - 1, x_out)
            for i in range(left_i, right_i + 1):
                t = self.view_offset + (i / max(1, w)) * visible_duration
                idx = int((t / self.duration) * n)
                if idx >= n:
                    break
                val = max(0.0, min(1.0, self.samples[idx]))
                v = val * 1.1
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
        QPushButton:disabled {{ opacity: 0.4; color: {C['text3']}; }}
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._frame_img = None
        self._text = ""
        self._image = None
        self._image_pos = (0, 0)
        self._bg = QColor(C["bg"])
        # Зум/панорама превью (Ctrl+колесо приближает, ЛКМ-перетаскивание двигает).
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self._pan_last = None
        self.setMouseTracking(True)

    def videoSink(self):
        return self._sink

    def setAspectRatioMode(self, *a, **k):   # совместимость с QVideoWidget
        pass

    def clear_frame(self):
        self._frame_img = None
        self.update()

    # ── Зум / панорама ───────────────────────────────────────────────────────
    def reset_view(self):
        """Сброс зума/панорамы (на 100%). Вызывается при загрузке нового файла."""
        changed = (self._zoom != 1.0) or (self._pan != QPoint(0, 0))
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
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
            self.update()
            ev.accept()
            return
        super().wheelEvent(ev)

    def mousePressEvent(self, ev):
        if self._zoom > 1.0 and ev.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_last = ev.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
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
        if self._panning and ev.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self.unsetCursor()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def _on_frame(self, frame):
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
            px = max(15, int(vr.height() * 0.052))
            _paint_subtitle(p, vr, self._text, px, self._image, self._image_pos)
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
            "border-top: 1px solid rgba(255,255,255,0.10); }")
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
        self.btn_save_frame = _fsbtn(QStyle.StandardPixmap.SP_DialogSaveButton,
                                     "Сохранить текущий кадр в PNG",
                                     self.edit.save_frame)

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


# ─── Edit Tab ─────────────────────────────────────────────────────────────────
class EditTab(QWidget):
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
        self.duration = 0.0
        self.current_in = 0.0
        self.current_out = 0.0
        self.fps = None
        self.video_aspect = None          # ширина/высота кадра (для точного 16:9-бокса)
        self.video_stream_index = None
        self.audio_stream_index = None
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
        ])
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
        # дорожкой, но не «вжечь» в изображение.
        self.chk_burn_subs = QCheckBox("Вшить субтитры")
        self.chk_burn_subs.setChecked(False)
        self._relax_width(self.chk_burn_subs)
        self.chk_burn_subs.setToolTip(
            "Жёстко впечатывает выбранную дорожку субтитров в кадр.\n"
            "Требует перекодировки видео (режим обрезки будет проигнорирован).\n"
            "Субтитры выбираются в панели справа от видео.")
        self.chk_burn_subs.setStyleSheet(self.chk_overwrite.styleSheet())
        export_card._body.addWidget(self.chk_burn_subs)

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
        self.btn_cut.setIcon(get_icon('fa5s.cut', color='#11111b'))
        self.btn_cut.setIconSize(QSize(20, 20))
        self.btn_cut.clicked.connect(self.start_cut)
        self.btn_cut.setStyleSheet(f"""
            QPushButton {{
                background: {C['accent']};
                color: #11111b;
                border: none;
                border-radius: 6px;
                padding: 9px 24px;
                font-weight: 700;
                font-size: 13px;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover {{ background: {C['accent2']}; }}
            QPushButton:pressed {{ background: {C['surface3']}; }}
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

        lbl_st = QLabel("Субтитры")
        lbl_st.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        side_l.addWidget(lbl_st)
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

        # Слева — кнопка «сохранить кадр» (одиночная векторная иконка, без текста);
        # справа — узкая колонка с подписью «Уровень звука» прямо над индикатором.
        vu_row = QHBoxLayout(); vu_row.setContentsMargins(0, 0, 0, 0); vu_row.setSpacing(8)
        sf_col = QVBoxLayout(); sf_col.setContentsMargins(0, 0, 0, 0); sf_col.setSpacing(0)
        self.btn_save_frame = make_icon_btn("")
        self.btn_save_frame.setIcon(get_icon('fa5s.save'))
        self.btn_save_frame.setIconSize(QSize(20, 20))
        self._relax_width(self.btn_save_frame)
        self.btn_save_frame.setToolTip("Сохранить текущий кадр в PNG (в папку сохранения)")
        self.btn_save_frame.clicked.connect(self.save_frame)
        self.btn_save_frame.setEnabled(False)   # активна только при загруженном видео
        sf_col.addWidget(self.btn_save_frame)
        sf_col.addStretch()
        vu_row.addLayout(sf_col, 1)

        vu_col = QVBoxLayout(); vu_col.setContentsMargins(0, 0, 0, 0); vu_col.setSpacing(3)
        lbl_vu = QLabel("Уровень звука")
        lbl_vu.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        lbl_vu.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        vu_col.addWidget(lbl_vu, 0)
        self.audio_meter = AudioMeter()
        self.audio_meter.setFixedWidth(54)
        vu_col.addWidget(self.audio_meter, 1, Qt.AlignmentFlag.AlignHCenter)
        vu_row.addLayout(vu_col, 0)
        side_l.addLayout(vu_row, 1)

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

        # IN / OUT — на одной строке с кнопками плеера. Поля компактные (фикс.
        # ширина под таймкод, без растягивания → нет пустоты справа от цифр).
        in_frame = QFrame()
        in_frame.setObjectName("InFrame")
        in_frame.setStyleSheet(f"#InFrame {{ background: {C['surface3']}; border: 1px solid {C['border2']}; border-radius: 6px; }}")
        in_f_layout = QHBoxLayout(in_frame)
        in_f_layout.setContentsMargins(8, 4, 8, 4)
        in_f_layout.setSpacing(6)
        in_dot = QLabel("●"); in_dot.setStyleSheet(f"color: {C['red']}; font-size: 10px;")
        in_lbl = QLabel("IN"); in_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        self.in_time_edit = QLineEdit("00:00:00.000")
        self.in_time_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.in_time_edit.setFixedWidth(112)
        self.in_time_edit.setToolTip("Таймкод начала. Enter — применить (или клавиша I)")
        self.in_time_edit.setStyleSheet(self._input_style())
        self.in_time_edit.returnPressed.connect(self.set_in_point)
        self.in_frame_spin = QSpinBox()
        self.in_frame_spin.setMaximum(100000000)
        self.in_frame_spin.setStyleSheet(self._spin_style())
        self.in_frame_spin.setFixedWidth(64)
        self.in_frame_spin.setSuffix(" к")
        self.in_frame_spin.setToolTip("Кадр начала")
        self.in_frame_spin.valueChanged.connect(self.on_in_frame_changed)
        in_f_layout.addWidget(in_dot); in_f_layout.addWidget(in_lbl)
        in_f_layout.addWidget(self.in_time_edit); in_f_layout.addWidget(self.in_frame_spin)
        pctrl_row.addWidget(in_frame)

        sep = QLabel("→")
        sep.setStyleSheet(f"color: {C['text3']}; font-size: 16px;")
        pctrl_row.addWidget(sep)

        out_frame = QFrame()
        out_frame.setObjectName("OutFrame")
        out_frame.setStyleSheet(f"#OutFrame {{ background: {C['surface3']}; border: 1px solid {C['border2']}; border-radius: 6px; }}")
        out_f_layout = QHBoxLayout(out_frame)
        out_f_layout.setContentsMargins(8, 4, 8, 4)
        out_f_layout.setSpacing(6)
        out_dot = QLabel("●"); out_dot.setStyleSheet(f"color: {C['green']}; font-size: 10px;")
        out_lbl = QLabel("OUT"); out_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        self.out_time_edit = QLineEdit("00:00:05.000")
        self.out_time_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.out_time_edit.setFixedWidth(112)
        self.out_time_edit.setToolTip("Таймкод конца. Enter — применить (или клавиша O)")
        self.out_time_edit.setStyleSheet(self._input_style())
        self.out_time_edit.returnPressed.connect(self.set_out_point)
        self.out_frame_spin = QSpinBox()
        self.out_frame_spin.setMaximum(100000000)
        self.out_frame_spin.setStyleSheet(self._spin_style())
        self.out_frame_spin.setFixedWidth(64)
        self.out_frame_spin.setSuffix(" к")
        self.out_frame_spin.setToolTip("Кадр конца")
        self.out_frame_spin.valueChanged.connect(self.on_out_frame_changed)
        out_f_layout.addWidget(out_dot); out_f_layout.addWidget(out_lbl)
        out_f_layout.addWidget(self.out_time_edit); out_f_layout.addWidget(self.out_frame_spin)
        pctrl_row.addWidget(out_frame)

        pctrl_row.addStretch()

        # Регулятор громкости — у правого края, рядом с полноэкранным режимом.
        # (Кнопка «сохранить кадр» теперь в боковой панели, у индикатора уровня.)
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
        self.btn_fullscreen.setIcon(_fullscreen_icon(expand=True))
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

    def _report_progress(self, pct, text=""):
        """Прогресс вкладки → общий прогрессбар окна (main.pbar). В standalone-
        режиме (без главного окна) обновляет собственный скрытый прогрессбар."""
        pct = int(max(0, min(100, pct)))
        try:
            if self.main is not None and hasattr(self.main, 'update_global_progress'):
                self.main.update_global_progress(
                    pct, text or ("Готово" if pct >= 100 else "Монтаж"))
                return
        except Exception:
            pass
        try:
            self.progress.setValue(pct)
        except Exception:
            pass

    # ── Видеовыход и метод субтитров ─────────────────────────────────────────
    def _read_subs_in_frame_pref(self):
        """Читает метод субтитров из настроек редактора (по умолчанию True —
        рендер в кадр). Читается ДО создания виджета видео в __init__."""
        try:
            if os.path.exists(EDITOR_SETTINGS_PATH):
                with open(EDITOR_SETTINGS_PATH, "r", encoding="utf-8") as f:
                    return bool(json.load(f).get("subs_in_frame", True))
        except Exception:
            pass
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
            raw = ((ainfo or {}).get('tags', {}) or {}).get('BPS')
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
            self.selected_audio_abs_index = self._audio_streams[ref].get('index')
            try:
                self.player.setActiveAudioTrack(ref)
            except Exception:
                pass
        else:
            # Внешний файл озвучки → играет отдельный синхронный плеер.
            self.selected_audio_abs_index = None
            self.selected_audio_ext_path = ref
            self._set_external_audio(ref)

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
            "Медиа файлы (*.mp4 *.mkv *.mov *.avi *.mp3 *.aac *.wav *.flac);;Все файлы (*)")
        if fname:
            self.load_file(fname)

    def clear_file(self):
        """Убирает текущий файл и возвращает редактор в исходное «пустое»
        состояние (как при запуске без файла): останавливает плеер и фоновые
        воркеры, чистит временный proxy, сбрасывает инфо/волну/тайминги."""
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

        self.actual_source_file = Path(path)
        self.filepath = self.actual_source_file

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
            if vinfo.get('codec_name', '').lower() == 'av1':
                self.create_proxy_for_preview(vinfo); return
            self.finish_loading_file(vinfo, ainfo)
        else:
            self.finish_loading_file(None, ainfo)

    def create_proxy_for_preview(self, vinfo):
        self.log_label.setText("Подготовка AV1...")
        self._report_progress(0, "Подготовка AV1…")
        self.btn_play.setEnabled(False); self.btn_cut.setEnabled(False)
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        tf.close(); self.tmp_proxy_file = tf.name
        self.proxy_thread = ProxyWorker(self.actual_source_file, self.tmp_proxy_file)
        self.proxy_thread.finished.connect(lambda s, m, o: self.on_proxy_ready(s, m, o, vinfo))
        self.proxy_thread.start()

    def on_proxy_ready(self, success, msg, output_path, vinfo):
        self.btn_play.setEnabled(True); self.btn_cut.setEnabled(True)
        self._report_progress(100); self.log_label.setText("Готово")

        def _first_audio(meta):
            for s in (meta or {}).get('streams', []):
                if s.get('codec_type') == 'audio':
                    return s
            return None

        if success:
            self.is_proxy_active = True
            self.filepath = Path(output_path)
            self.lbl_proxy.setText(
                icon_html('fa5s.bolt', 13, C['yellow']) + " ПРЕВЬЮ РЕЖИМ (AV1 → H.264)")
            self.lbl_proxy.setVisible(True)
            ainfo = _first_audio(run_ffprobe(self.filepath))
        else:
            if msg != "Отменено":
                QMessageBox.warning(self, "Ошибка прокси", f"Не удалось создать превью: {msg}")
            ainfo = _first_audio(run_ffprobe(self.actual_source_file))
        self.finish_loading_file(vinfo, ainfo)

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
        self.lbl_fps.setText(format_fps(self.fps))

        self.undo_stack.clear(); self.redo_stack.clear()
        self.current_in = 0.0; self.current_out = max(0.001, self.duration)
        self.set_in_out(0.0, self.current_out, skip_undo=True)

        # Новый файл — сбрасываем зум/панораму превью (если активен холст-режим).
        if isinstance(self.video_widget, VideoCanvas):
            self.video_widget.reset_view()

        self.player.setSource(QUrl.fromLocalFile(str(self.filepath)))
        self.player.setPosition(0); self.player.pause()

        self.start_waveform_loading()
        QTimer.singleShot(50, self._adjust_video_aspect_once)
        self.update_selection_label(); self.update_pan_slider_values()
        # После загрузки файла (в т.ч. через drag&drop) забираем фокус клавиатуры
        # на вкладку, чтобы Пробел/I/O/←→ работали сразу — без клика по видео.
        # singleShot(0): после того, как плеер/видеовиджет отработают своё событие.
        QTimer.singleShot(0, self._grab_kbd_focus)

    def _grab_kbd_focus(self):
        """Ставит фокус клавиатуры на вкладку «Монтаж». Хоткеи привязаны к ней с
        контекстом WidgetWithChildren — без фокуса на вкладке (или её потомке)
        Пробел и прочие не срабатывают, пока пользователь не кликнет по видео."""
        try:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass

    def start_waveform_loading(self):
        self.waveform.set_loading("Загрузка волны...")
        a_idx = self.audio_stream_index if not self.is_proxy_active else None
        self.audio_worker = AudioWaveformLoader(self.filepath, a_idx)
        self.audio_worker.finished.connect(self.on_waveform_ready)
        self.audio_worker.progress.connect(self.waveform.set_loading)
        self.audio_worker.start()

    def on_waveform_ready(self, samples, duration):
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
        self.waveform.set_data(samples, use_duration)
        # Восстанавливаем выделение пользователя после загрузки волны
        # (waveform.set_in_out пошлёт selectionChanged → синхронизация полей/кадров).
        self.waveform.set_in_out(self.current_in, self.current_out)
        self.update_pan_slider_values()

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
        if not self.undo_stack:
            return
        self.redo_stack.append((self.current_in, self.current_out))
        prev = self.undo_stack.pop()
        self.set_in_out(prev[0], prev[1], skip_undo=True)

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append((self.current_in, self.current_out))
        nxt = self.redo_stack.pop()
        self.set_in_out(nxt[0], nxt[1], skip_undo=True)

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

    def update_selection_label(self):
        # Показываем только итоговую длительность будущего ролика (без таймкодов
        # начала/конца — они и так есть в полях IN/OUT).
        dur = max(0.0, self.current_out - self.current_in)
        self.lbl_selection.setText(
            f"{icon_html('fa5s.stopwatch', 13, C['text'])}  Итог: {s_to_time(dur)}")

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
        self._fs_sync_position()

    def _update_meter(self, pos_s):
        """Кормит индикатор уровня значением аудиоволны на позиции плейхеда
        (только при воспроизведении; на паузе шкала плавно опадает сама)."""
        meter = getattr(self, "audio_meter", None)
        if meter is None:
            return
        try:
            if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                return
            samples = self.waveform.samples
            dur = self.waveform.duration or self.duration or 0.0
            if samples and dur > 0:
                idx = int(pos_s / dur * len(samples))
                idx = max(0, min(len(samples) - 1, idx))
                # samples[idx] — линейный пик амплитуды (0..1), у типичного
                # контента он низкий, поэтому шкала «прибита» к низу. Поднимаем
                # перцептивной кривой (√) и учитываем громкость микшера, чтобы при
                # полном ползунке индикатор был живым, как в реальном VU-метре.
                amp = max(0.0, min(1.0, float(samples[idx])))
                try:
                    vol = max(0.0, min(1.0, float(self.audio_output.volume())))
                except Exception:
                    vol = 1.0
                lvl = min(1.0, (amp ** 0.5) * 1.7 * (0.2 + 0.8 * vol))
                meter.set_levels(lvl, lvl)
        except Exception:
            pass

    def sync_ui(self):
        if self.duration <= 0.1:
            return
        pos_s = self.player.position() / 1000.0
        self.lbl_current_time.setText(s_to_time(pos_s))
        # Авто-пауза в конце воспроизводимого участка. Если OUT у самого конца
        # клипа — останавливаемся на кадр раньше: иначе плеер доходит до
        # EndOfMedia, и QtMultimedia гасит поверхность в чёрный кадр (в оригинале
        # чёрного кадра нет). Для обрезанного OUT поведение прежнее (баг #9).
        frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
        guard = max(frame_s, 0.05)
        at_end = self.current_out >= (self.duration - 0.02)
        effective_out = (self.duration - guard) if at_end else self.current_out
        if effective_out > self.current_in and pos_s >= effective_out:
            self.player.pause()
            self.player.setPosition(int(effective_out * 1000))
            self.lbl_current_time.setText(s_to_time(effective_out))
            self.waveform.set_playhead(effective_out)
            return
        if self.duration > 0 and not self.slider.is_user_seeking():
            self.slider.blockSignals(True)
            self.slider.setValue(int((pos_s / self.duration) * 1000))
            self.slider.blockSignals(False)
        self.waveform.set_playhead(pos_s)
        self._update_meter(pos_s)
        self._update_subtitle(pos_s)
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
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            pos_s = self.player.position() / 1000.0
            if abs(pos_s - self.current_out) < 0.15 and self.current_out > (self.current_in + 0.5):
                self.seek_to(self.current_in)
            self.player.play()

    def stop_playback(self):
        self.player.pause(); self.seek_to(self.current_in)

    def on_playback_changed(self, state):
        # Во время покадрового скраба play→pause транзиентны — не трогаем кнопку,
        # чтобы иконка/текст не дёргались (меняются только по явному действию).
        if self._scrubbing:
            return
        playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        if playing:
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.sync_timer.start()
        else:
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.sync_timer.stop()
        # Внешняя озвучка следует за состоянием основного плеера.
        self._ext_audio_set_state(playing)
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.update_play_icon(state == QMediaPlayer.PlaybackState.PlayingState)
            except Exception:
                pass

    def on_media_status_changed(self, status):
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
        for name in ("btn_fullscreen", "btn_save_frame"):
            b = getattr(self, name, None)
            if b is not None:
                b.setEnabled(has_video)

    # ── Сохранение текущего кадра ────────────────────────────────────────────
    def save_frame(self):
        """Сохраняет кадр на текущей позиции воспроизведения в PNG (полное
        разрешение, извлекается из исходника через ffmpeg). Без диалога —
        файл сразу кладётся в папку сохранения (или рядом с исходником)."""
        src = self.actual_source_file or self.filepath
        if not src or not os.path.exists(src) or self.duration <= 0:
            return
        pos = max(0.0, self.player.position() / 1000.0)
        base = os.path.splitext(os.path.basename(src))[0]
        stamp = s_to_time(pos).replace(':', '-').replace('.', '_')
        save_dir = (self.export_dir if (self.export_dir and os.path.isdir(self.export_dir))
                    else os.path.dirname(src))
        fname = _unique_output(os.path.join(save_dir, f"{base}_{stamp}.png"))
        # -ss перед -i в современном ffmpeg точен (декодирует до нужного кадра).
        cmd = [FFMPEG, "-y", "-ss", f"{pos:.3f}", "-i", src,
               "-frames:v", "1", "-update", "1", fname]
        kw = {}
        if os.name == 'nt':
            kw['creationflags'] = CREATE_NO_WINDOW
        ok = False
        try:
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=60, **kw)
            ok = (r.returncode == 0 and os.path.exists(fname)
                  and os.path.getsize(fname) > 0)
        except Exception:
            ok = False
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
        ms = self.player.position()
        ms_per_frame = (1000.0 / self.fps) if (self.fps and self.fps > 0) else 40
        new_ms = max(0, min(int(self.duration * 1000), ms + int(step * ms_per_frame)))
        self.player.setPosition(new_ms)
        self._ext_audio_seek(new_ms)

    def step_frame_scrub(self, step):
        self.step_frame(step)
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            # Кратко проигрываем, чтобы отрисовать кадр, затем ставим на паузу.
            # Флаг _scrubbing гасит обновление кнопки на этих транзиентах.
            self._scrubbing = True
            self.player.play()
            QTimer.singleShot(80, self._end_scrub)

    def _end_scrub(self):
        self.player.pause()
        # Сбрасываем флаг после того, как событие паузы будет обработано.
        QTimer.singleShot(40, lambda: setattr(self, "_scrubbing", False))

    # ── Export / Cut ──────────────────────────────────────────────────────
    def _video_encoder_args(self):
        """Подбирает доступный H.264-кодировщик в bundled ffmpeg (детект один раз).
        По умолчанию libx264 (лучшее качество/совместимость); если его в сборке
        нет — мягкий откат на аппаратный кодировщик, иначе на mpeg4."""
        cache = getattr(self, "_venc_cache", None)
        if cache is not None:
            return list(cache)
        encoders = ""
        try:
            p = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", creationflags=CREATE_NO_WINDOW)
            encoders = p.stdout or ""
        except Exception:
            encoders = ""

        def has(name):
            return (" " + name + " ") in encoders or encoders == ""

        if "libx264" in encoders or encoders == "":
            args = ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]
        elif "h264_nvenc" in encoders:
            args = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20"]
        elif "h264_qsv" in encoders:
            args = ["-c:v", "h264_qsv", "-global_quality", "20"]
        elif "h264_amf" in encoders:
            args = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                    "-qp_i", "20", "-qp_p", "20"]
        elif "h264_mf" in encoders:
            args = ["-c:v", "h264_mf", "-rate_control", "quality", "-quality", "70"]
        else:
            args = ["-c:v", "mpeg4", "-q:v", "3"]
        self._venc_cache = list(args)
        return list(args)

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
        self._execute_cut(in_s, out_s, mode, burn_subs)

    def _execute_cut(self, in_s, out_s, mode, burn_subs,
                     src=None, force_overwrite=False):
        """Собирает и запускает ffmpeg-обрезку для диапазона [in_s, out_s].
        `src` позволяет перекодировать из ОРИГИНАЛА (для предложения «перекодировать
        с потерями» после неточной copy-обрезки), `force_overwrite` — перезаписать
        результат принудительно."""
        src = Path(src) if src else self.actual_source_file
        if not src or not src.exists():
            QMessageBox.warning(self, "Внимание", "Файл не загружен.")
            return

        stem = src.stem; suffix = src.suffix
        if self.export_dir and os.path.isdir(self.export_dir):
            out_dir = Path(self.export_dir)
        else:
            out_dir = src.parent

        if mode == 2:
            final_out = str(out_dir / f"{stem}_обрез.mp3")
        else:
            final_out = str(out_dir / f"{stem}_обрез{suffix}")

        replace_original = force_overwrite or self.chk_overwrite.isChecked()
        if os.path.exists(final_out) and not replace_original:
            # Перезапись выключена, а файл уже есть — не прерываемся и не
            # перезаписываем, а сохраняем результат под новым именем с суффиксом
            # (foo_обрез.mp4 → foo_обрез_1.mp4, _2, …).
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
        venc = self._video_encoder_args()

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
            # Если у дорожки нет собственных стилей (SRT/VTT/mov_text) — задаём
            # читабельный стиль по умолчанию: крупный белый жирный шрифт с чёрной
            # обводкой (как на скрине). ASS/SSA несут свои стили — их не трогаем.
            if sub_codec not in ('ass', 'ssa'):
                style = ("FontName=Arial,Fontsize=28,Bold=1,"
                         "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                         "BorderStyle=1,Outline=2,Shadow=1,MarginV=24")
                vf += f":force_style='{style}'"
            fonts_dir = self._extract_subtitle_fonts(src)
            if fonts_dir:
                fesc = self._escape_filter_path(fonts_dir)
                vf += f":fontsdir='{fesc}'"
            if ext_audio:
                # Видео+субтитры из исходника (вход 0), звук — из внешнего файла
                # (вход 1). Выходной seek (-ss/-t как опции вывода) равно режет оба.
                cmd = [FFMPEG, "-y", "-i", str(src), "-i", ext_audio,
                       "-ss", in_str, "-t", dur_str,
                       "-map", "0:v:0", "-map", "1:a:0", "-vf", vf] \
                      + venc + ["-c:a", "aac", "-b:a", "192k", temp_out]
            else:
                # Аудио НЕ перекодируем (контейнер тот же → совместимо).
                cmd = [FFMPEG, "-y", "-i", str(src), "-ss", in_str, "-t", dur_str] \
                      + amap + ["-vf", vf] + venc + ["-c:a", "copy", temp_out]
        elif ext_audio and mode != 2:
            # Внешняя озвучка без вшивания субтитров. Видео берём по режиму
            # (copy/перекодировка), звук — из внешнего файла (перекодируем в AAC,
            # т.к. контейнер/кодек могут не совпадать).
            vargs = ["-c:v", "copy"] if mode == 0 else venc
            cmd = [FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                   "-ss", in_str, "-i", ext_audio, "-t", dur_str,
                   "-map", "0:v:0", "-map", "1:a:0"] \
                  + vargs + ["-c:a", "aac", "-b:a", "192k", temp_out]
        elif mode == 0:
            # Точная обрезка в режиме copy: -ss и -to ДО -i — конец совпадает с
            # запрошенным; начало может прилипнуть к ближайшему keyframe (баг #1).
            cmd = [FFMPEG, "-y", "-ss", in_str, "-to", out_str, "-i", str(src)] \
                  + amap + ["-c", "copy", temp_out]
        elif mode == 1:
            # Перекодировка с КАДРОВОЙ точностью: -ss/-t ПОСЛЕ -i (выходной seek).
            # ffmpeg декодирует с начала и режет ровно по кадру, не «прилипая» к
            # ключевому кадру и не сбиваясь на контейнерах со смещённым start_time
            # (MKV/WEB-DL). Это медленнее входного seek, но точно (как у hardsub).
            # Аудио копируем без перекодировки (тот же контейнер).
            cmd = [FFMPEG, "-y", "-i", str(src), "-ss", in_str, "-t", dur_str] \
                  + amap + venc + ["-c:a", "copy", temp_out]
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
        self.btn_cut.setEnabled(False)

        self.ffmpeg_thread = FfmpegWorker(cmd, duration=dur_cut)
        self.ffmpeg_thread.progress.connect(lambda p: self._report_progress(int(p), "Обрезка…"))

        def _on_finished(success, message, _temp=temp_out, _final=final_out,
                         _exact=exact_copy, _reqdur=dur_cut, _burn=burn_subs,
                         _fonts=fonts_dir, _in=in_s, _out=out_s, _src=src):
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
                        os.remove(_final)
                    if os.path.exists(_final) and not replace_original:
                        if os.path.exists(_temp):
                            os.remove(_temp)
                        self.on_ffmpeg_finished(False, "Файл уже существует (логическая ошибка)")
                        return
                    os.replace(_temp, _final)
                    # Точность обрезки проверяем ДО перезагрузки. Если copy-обрезка
                    # вышла не кадрово-точной и пользователь согласился — сразу
                    # перекодируем ТОТ ЖЕ диапазон из оригинала (с потерями).
                    if self._notify_cut_accuracy(_final, _reqdur, _exact, _burn,
                                                 _in, _out, _src):
                        QTimer.singleShot(0, lambda: self._execute_cut(
                            _in, _out, 1, _burn, src=_src, force_overwrite=True))
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

    def on_ffmpeg_finished(self, success, message):
        if success:
            self.log_label.setText(icon_html('fa5s.check', 12, C['green2']) + " Готово")
            self.log_label.setStyleSheet(f"color: {C['green2']}; font-size: 12px; font-weight: 600;")
            self._report_progress(100, "Готово")
        elif message == "Отменено":
            self.log_label.setText("Отменено")
            self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
            self._report_progress(0, "Отменено")
        else:
            self.log_label.setText(icon_html('fa5s.times', 12, C['red2']) + " Ошибка")
            self.log_label.setStyleSheet(f"color: {C['red2']}; font-size: 12px; font-weight: 600;")
            QMessageBox.critical(self, "Ошибка", f"Обрезка завершилась с ошибкой:\n{message}")
            self._report_progress(0, "Ошибка")

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

    def _notify_cut_accuracy(self, final_path, requested_dur, exact_copy, burn_subs,
                             in_s=None, out_s=None, src=None):
        """Сообщает, удалось ли обрезать БЕЗ перекодировки точно по кадрам.

        В режиме «Быстро (копирование потоков)» начало прилипает к ближайшему
        ключевому кадру, поэтому итоговая длительность может оказаться больше
        запрошенной. Сравниваем фактическую длительность результата с заданной.

        Возвращает True, если пользователь согласился ПЕРЕКОДИРОВАТЬ диапазон
        заново (с потерями, но кадрово-точно) — тогда вызывающий код перезапускает
        обрезку в режиме перекодировки."""
        try:
            if burn_subs:
                QMessageBox.information(
                    self, "Готово",
                    "Субтитры вшиты в видео (с перекодировкой).")
                return False
            if not exact_copy:
                # Режимы перекодировки/MP3 — всегда кадрово-точные, отдельное
                # уведомление не нужно.
                return False
            meta = run_ffprobe(final_path)
            actual = 0.0
            try:
                actual = float((meta or {}).get('format', {}).get('duration', 0.0))
            except Exception:
                actual = 0.0
            # Допуск ~1 кадр (или 0.05 c, если FPS неизвестен).
            tol = (1.5 / self.fps) if (self.fps and self.fps > 0) else 0.05
            diff = abs(actual - requested_dur) if actual > 0 else 0.0
            if actual <= 0 or diff <= tol:
                QMessageBox.information(
                    self, "Готово — точная обрезка",
                    "Обрезано без перекодировки, точно по заданным кадрам.")
                return False
            # Не кадрово-точно → сразу предлагаем перекодировать с потерями.
            ans = QMessageBox.question(
                self, "Не получилось точно без потерь",
                "Обрезка без перекодировки (быстро) НЕ кадрово-точная: начало "
                "сдвинулось к ближайшему ключевому кадру.\n\n"
                f"Запрошено: {s_to_time(requested_dur)}\n"
                f"Получилось: {s_to_time(actual)}\n"
                f"Расхождение: {s_to_time(diff)}\n\n"
                "Перекодировать этот фрагмент заново — точно по кадрам, но "
                "с потерей качества (перекодировка)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if (ans == QMessageBox.StandardButton.Yes
                    and in_s is not None and out_s is not None):
                return True
            return False
        except Exception:
            pass
        return False

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
            add_shortcut("A", lambda: self.move_in(-1))
            add_shortcut("D", lambda: self.move_in(1))
            add_shortcut("W", lambda: self.move_out(1))
            add_shortcut("S", lambda: self.move_out(-1))
            add_shortcut("Ctrl+S", self.start_cut)
            # Обрезка до точки воспроизведения (настраиваемые сочетания) —
            # храним QShortcut, чтобы можно было переназначить в Настройках.
            self._sc_trim_start = QShortcut(QKeySequence(self.trim_start_seq), self)
            self._sc_trim_start.setContext(ctx)
            self._sc_trim_start.activated.connect(self.trim_start_to_playhead)
            self._sc_trim_end = QShortcut(QKeySequence(self.trim_end_seq), self)
            self._sc_trim_end.setContext(ctx)
            self._sc_trim_end.activated.connect(self.trim_end_to_playhead)
            add_shortcut(QKeySequence.StandardKey.Undo, self.undo)
            add_shortcut(QKeySequence.StandardKey.Redo, self.redo)
            add_shortcut("Ctrl+Y", self.redo)
            add_shortcut("Ctrl+Shift+Z", self.redo)
            # Раскладочные дубли (рус. Я = Z, Н = Y) — redo теперь тоже есть (баг #6).
            for seq, handler in (("Ctrl+Я", self.undo), ("Ctrl+Н", self.redo)):
                sc = QShortcut(QKeySequence(seq), self)
                sc.setContext(ctx)
                sc.activated.connect(handler)
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
                'overwrite':  bool(self.chk_overwrite.isChecked()),
                'burn_subs':  bool(self.chk_burn_subs.isChecked()),
                'zoom':       float(self.waveform.zoom),
                'view_offset': float(self.waveform.view_offset),
                'volume':     int(self.vol_slider.value()),   # громкость теперь сохраняется (пункт B)
                'trim_start_seq': self.trim_start_seq,
                'trim_end_seq':   self.trim_end_seq,
                'export_dir':     self.export_dir or "",
                'subs_in_frame':  bool(getattr(self, '_subs_in_frame', True)),
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
            self.cmb_mode.setCurrentIndex(int(settings.get('mode_index', 0)))
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
        # Убиваем все фоновые ffmpeg-процессы, чтобы не остались зомби (баг #3).
        for attr in ('ffmpeg_thread', 'proxy_thread', 'audio_worker'):
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
