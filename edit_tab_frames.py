# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_frames.py — покадровый слой вкладки «Монтаж»: сетка кадров (время ↔
# номер кадра) и предекодирование соседних кадров вокруг плейхеда.
#
# Зачем отдельный слой. Плеер вкладки — QMediaPlayer (QtMultimedia, ffmpeg-
# бэкенд): он умеет играть, но НЕ умеет ни «встань ровно на кадр N», ни «дай
# кадр N прямо сейчас» — setPosition принимает миллисекунды, а какой кадр он в
# итоге покажет, зависит от округления и от того, докрутил ли декодер цепочку от
# ключевого кадра. Отсюда все три жалобы на монтаж: шаг стрелкой показывает не
# тот кадр, старт с произвольного места «думает» пару секунд, метка на таймлайне
# живёт своей жизнью относительно картинки.
#
# Решение — как в настоящих монтажках: арифметика ведётся в НОМЕРАХ КАДРОВ
# (FrameGrid), а точная картинка кадра N приходит не от плеера, а собственным
# декодером (FramePrefetcher, тот же bundled ffmpeg.exe, что и везде в проекте —
# никаких новых зависимостей, см. SI-HYX.spec: PyAV намеренно исключён).
# Плеер остаётся ровно тем, чем он хорош: непрерывным воспроизведением.

import ctypes
import os
import subprocess
import threading
from collections import OrderedDict

import hdr_tonemap
from config import (CREATE_NO_WINDOW, FFMPEG, FFPROBE, QThread, pyqtSignal)
# Пробы ffprobe живут в media_probe (без Qt): их берут и headless-инструменты.
from media_probe import (probe_mastering_nits, probe_video_props,  # noqa: F401
                         qt_pq_max_luminance)
from PyQt6.QtCore import (QSize)
from PyQt6.QtGui import (QImage)
from PyQt6.QtMultimedia import (QVideoFrame, QVideoFrameFormat)


# ── Сетка кадров ─────────────────────────────────────────────────────────────
class FrameGrid:
    """Перевод «время ↔ номер кадра» для одного клипа. Чистая арифметика (ни
    Qt, ни ffmpeg) — вся покадровая точность держится на ней.

    Почему не «позиция ± 1000/fps», как было раньше: при дробном fps (23.976,
    29.97) шаг в миллисекундах приходится округлять, и ошибка копится — примерно
    каждый 60-й шаг «съедал» кадр (шаг 41 мс вместо 41.708). Плюс попадание
    РОВНО на границу кадра неоднозначно: плеер отдаёт кадр с pts ≤ позиции,
    ffmpeg — первый кадр с pts ≥ -ss, и на границе это РАЗНЫЕ кадры.

    Поэтому:
      • шаг считается по номерам кадров, а не по времени;
      • плееру отдаётся СЕРЕДИНА кадра (center_of) — она заведомо дальше
        полукадра от любой границы, и никакое округление до миллисекунд не
        перекинет её на соседний кадр;
      • ffmpeg отдаётся четверть кадра ДО начала (seek_of) — он берёт первый
        кадр с pts ≥ ss, то есть ровно наш.
    """

    # Допуск при переводе позиции плеера (миллисекунды!) в номер кадра: pts
    # кадра при дробном fps в целые миллисекунды не ложится, и позиция 41 мс —
    # это уже кадр 1 при 23.976 (его pts 41.708), а не кадр 0.
    TOL_S = 0.0015

    def __init__(self, fps=0.0, duration=0.0):
        try:
            self.fps = float(fps or 0.0)
        except Exception:
            self.fps = 0.0
        try:
            self.duration = max(0.0, float(duration or 0.0))
        except Exception:
            self.duration = 0.0
        self.valid = self.fps > 0.0

    @property
    def last(self):
        """Номер последнего кадра клипа (0, если длительность неизвестна)."""
        if not self.valid or self.duration <= 0:
            return 0
        return max(0, int(self.duration * self.fps + FrameGrid.TOL_S * self.fps) - 1)

    def clamp(self, idx):
        idx = int(idx)
        if idx < 0:
            return 0
        top = self.last
        return min(idx, top) if top > 0 else max(0, idx)

    def index_at(self, t_s):
        """Номер кадра, который ВИДЕН в момент t (кадр, чей интервал показа
        накрывает t). Для позиции плеера — с допуском на округление до мс."""
        if not self.valid:
            return 0
        return self.clamp(int((max(0.0, float(t_s)) + self.TOL_S) * self.fps))

    def index_of_pts(self, pts_s):
        """Номер кадра по ТОЧНОМУ pts кадра (из самого кадра плеера): pts — это
        начало показа, поэтому округляем к ближайшему узлу сетки."""
        if not self.valid:
            return 0
        return self.clamp(int(round(max(0.0, float(pts_s)) * self.fps)))

    def start_of(self, idx):
        """Момент появления кадра на экране (его pts), с."""
        if not self.valid:
            return 0.0
        return max(0, int(idx)) / self.fps

    def center_of(self, idx):
        """Середина показа кадра — цель для player.setPosition (см. докстроку)."""
        if not self.valid:
            return 0.0
        return (max(0, int(idx)) + 0.5) / self.fps

    def seek_of(self, idx):
        """Аргумент `-ss` для ffmpeg, чтобы получить именно кадр idx: четверть
        кадра НИЖЕ его pts (тот же приём, что в EditTab.start_cut)."""
        if not self.valid:
            return 0.0
        return max(0.0, (max(0, int(idx)) - 0.25) / self.fps)

    def pts_span_us(self, idx):
        """Диапазон pts (мкс), который считается «этим же кадром» — половина
        кадра в каждую сторону. Нужен холсту, чтобы отличить кадр N от чужого."""
        if not self.valid:
            return (0, 0)
        lo = (max(0, int(idx)) - 0.5) / self.fps
        hi = (max(0, int(idx)) + 0.5) / self.fps
        return (int(max(0.0, lo) * 1_000_000), int(hi * 1_000_000))

    def ms_of(self, idx):
        """Целевая позиция плеера (мс) для кадра idx."""
        return int(round(self.center_of(idx) * 1000.0))


# ── Предекодирование кадров вокруг плейхеда ──────────────────────────────────
def qt_frame_size(w, h, sar):
    """Размер кадра так, как его отдаёт плеер Qt (ffmpeg-бэкенд) у файла с
    неквадратным пикселем: qCalculateFrameSize растягивает ОДНУ сторону —
    ширину, если пиксель шире квадрата, иначе высоту (целочисленно, как в C++).
    Анаморфный DVD 712x472 с SAR 472:519 плеер показывает как 712x519; кадр
    паузы из ffmpeg шёл сырым 712x472, и картинка на паузе сплющивалась."""
    num, den = sar if sar else (1, 1)
    if num == den or num < 1 or den < 1:
        return (w, h)
    if num > den:
        return (w * num // den, h)
    return (w, h * den // num)


def probe_frame_size(path):
    """(ширина, высота) кадра, КАК ЕГО ОТДАЁТ ffmpeg (-f rawvideo), — с
    учётом поворота: ffmpeg по умолчанию разворачивает кадр по метаданным, и
    у вертикального видео с телефона (поток 1920x1080, поворот 90°) кадр
    приходит 1080x1920. Прежде брался размер потока — байты те же, а картинка
    выходила кашей. (0, 0) — не вышло.

    Нужны РЕАЛЬНЫЕ размеры декодированного кадра: сырой поток приходит без
    заголовков, и разобрать его можно, только зная размер кадра."""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
             str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW, timeout=15)
        lines = (out.stdout or "").strip().splitlines()
        # ffprobe ставит разделитель И В КОНЦЕ строки: «960x540x» (сборки
        # 2026 года; раньше было «960x540»). Прежний partition("x") давал
        # int("540x") → исключение → (0, 0) → предекодер молча не декодировал
        # НИ ОДНОГО кадра. Поэтому разбираем терпимо: берём непустые поля.
        nums = [p for p in lines[0].split("x") if p.strip()] if lines else []
        if len(nums) < 2:
            return (0, 0)
        w, h = int(nums[0]), int(nums[1])
    except Exception:
        return (0, 0)
    if abs(probe_video_props(path).get("rotation", 0)) % 180 == 90:
        w, h = h, w
    return (w, h)


# ── Кадр в формате плеера (HDR) ──────────────────────────────────────────────
# HDR-кадр (PQ/HLG) плеер (QtMultimedia, ffmpeg-бэкенд) рисует СВОИМ шейдером:
# при аппаратном декодировании кадр приходит P010, и шейдер nv12_bt2020_pq
# сводит его в SDR (тонмаппинг BT.2390 по яркости мастеринга, PQ → линейный
# свет, BT.2020 → sRGB). Кадр, который ffmpeg отдаёт в rgb24, ничего этого не
# знает: на паузе картинка выходила белёсой и серой, а при игре — сочной.
# Повторить шейдер на ЦП один в один нельзя (у Qt свои особенности: яркость
# мастеринга он берёт ×10000, отрицательные R'G'B' уходят в чёрный), поэтому
# точный кадр для HDR отдаётся НЕ картинкой, а QVideoFrame в формате кадров
# самого плеера — и сцена холста рисует его тем же шейдером с теми же
# параметрами (сверено: разница 0 по всем пикселям).
_HDR_TRANSFERS = {"smpte2084": QVideoFrameFormat.ColorTransfer.ColorTransfer_ST2084,
                  "arib-std-b67": QVideoFrameFormat.ColorTransfer.ColorTransfer_STD_B67}

# Пиксельный формат кадров плеера → сырой вывод ffmpeg и его плоскости:
# (делитель ширины, делитель высоты, байт на точку плоскости).
_PF = QVideoFrameFormat.PixelFormat
_RAW_LAYOUTS = {
    _PF.Format_P010: ("p010le", ((1, 1, 2), (2, 2, 4))),
    _PF.Format_P016: ("p016le", ((1, 1, 2), (2, 2, 4))),
    _PF.Format_YUV420P10: ("yuv420p10le", ((1, 1, 2), (2, 2, 2), (2, 2, 2))),
}


def _raw_planes(layout, w, h):
    """[(байт в строке, строк)] плоскостей сырого кадра ffmpeg."""
    return [(-(-w // wd) * bpp, -(-h // hd)) for wd, hd, bpp in layout]


_QT_MAX_LUM = None


def _qt_max_luminance_api():
    """(установить, прочитать) яркость мастеринга у QVideoFrameFormat.

    PyQt6 этих методов не оборачивает, а Qt по ним выбирает тонмаппинг HDR.
    Они экспортируются из Qt6Multimedia.dll — зовём напрямую. Нет библиотеки
    или символов (другая сборка Qt) — (None, None), и формат остаётся без
    яркости: кадр всё равно HDR-шейдером, но тонмаппинг чуть другой."""
    global _QT_MAX_LUM
    if _QT_MAX_LUM is not None:
        return _QT_MAX_LUM
    _QT_MAX_LUM = (None, None)
    if os.name != "nt":
        return _QT_MAX_LUM
    try:
        import PyQt6
        dll = ctypes.WinDLL(os.path.join(os.path.dirname(PyQt6.__file__),
                                         "Qt6", "bin", "Qt6Multimedia.dll"))
        setter = dll["?setMaxLuminance@QVideoFrameFormat@@QEAAXM@Z"]
        getter = dll["?maxLuminance@QVideoFrameFormat@@QEBAMXZ"]
        setter.argtypes, setter.restype = [ctypes.c_void_p, ctypes.c_float], None
        getter.argtypes, getter.restype = [ctypes.c_void_p], ctypes.c_float
        _QT_MAX_LUM = (setter, getter)
    except Exception:
        pass
    return _QT_MAX_LUM


def _max_luminance(fmt):
    getter = _qt_max_luminance_api()[1]
    if getter is None:
        return None
    try:
        from PyQt6 import sip
        return round(float(getter(sip.unwrapinstance(fmt))), 3)
    except Exception:
        return None


def guess_player_format(props, nits, hw_decode):
    """Формат, в котором плеер отдаст HDR-кадр, пока он не показал ни одного
    (сразу после открытия файла точный кадр приходит раньше кадров плеера):
    аппаратный декодер даёт P010, программный — YUV420P10. None — не HDR."""
    trc = _HDR_TRANSFERS.get(props.get("transfer") or "")
    w, h = qt_frame_size(props.get("width", 0), props.get("height", 0),
                         props.get("sar"))
    if trc is None or w <= 0 or h <= 0 or props.get("rotation", 0) % 360:
        # С поворотом ждём настоящий формат кадра плеера: поворот в нём
        # записан так, как его применит сцена.
        return None
    pf = _PF.Format_P010 if hw_decode else _PF.Format_YUV420P10
    fmt = QVideoFrameFormat(QSize(w, h), pf)
    fmt.setColorTransfer(trc)
    if (props.get("space") or "").startswith("bt2020"):
        fmt.setColorSpace(QVideoFrameFormat.ColorSpace.ColorSpace_BT2020)
    fmt.setColorRange(QVideoFrameFormat.ColorRange.ColorRange_Full
                      if props.get("range") == "pc"
                      else QVideoFrameFormat.ColorRange.ColorRange_Video)
    if nits and nits > 0:
        # Qt умножает яркость мастеринга на 10000 (QFFmpegVideoBuffer::maxNits)
        # — повторяем, иначе тонмаппинг выйдет другим, чем у кадров плеера.
        setter = _qt_max_luminance_api()[0]
        if setter is not None:
            try:
                from PyQt6 import sip
                setter(sip.unwrapinstance(fmt), float(nits) * 10000.0)
            except Exception:
                pass
    return fmt


def qt_pq_image(yuv16, max_luminance, max_nits=100.0):
    """Картинка (QImage RGB888) из PQ-кадра BT.2020 ровно так, как его рисует
    шейдер Qt nv12_bt2020_pq — для мелких картинок (полоса кадров таймлайна),
    где отдать QVideoFrame сцене нельзя. yuv16 — плоскости yuv444p16le
    (3, h, w) uint16. Сверено с QVideoFrame.toImage(): ±1 уровень."""
    import numpy as np

    yuv = yuv16.astype(np.float32) * np.float32(1023.0 * 64.0 / 65535.0 / 65535.0)
    Y, U, V = yuv[0], yuv[1], yuv[2]
    rgb = (1.1644 * Y + 1.6787 * V - 0.9157,
           1.1644 * Y - 0.1874 * U - 0.6504 * V + 0.3475,
           1.1644 * Y + 2.1418 * U - 1.1483)
    y = (Y - np.float32(0.0625)) * np.float32(256 / 219)
    # Сама формула — общая с экспортом (таблица lut3d в hdr_tonemap).
    out = hdr_tonemap.qt_pq_to_srgb(y, rgb, max_luminance, max_nits)
    rgb8 =np.ascontiguousarray((np.stack(out, axis=-1) * 255.0 + 0.5).astype(np.uint8))
    h, w = rgb8.shape[:2]
    return QImage(rgb8.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888).copy()


def _video_frame(buf, fmt, planes):
    """QVideoFrame формата fmt из сырого кадра ffmpeg (плоскости подряд)."""
    vf = QVideoFrame(fmt)
    if not vf.isValid() or not vf.map(QVideoFrame.MapMode.WriteOnly):
        return None
    try:
        src = memoryview(buf)
        off = 0
        for i, (row, rows) in enumerate(planes):
            bpl = vf.bytesPerLine(i)
            ptr = vf.bits(i)
            if ptr is None or bpl < row:
                return None
            ptr.setsize(vf.mappedBytes(i))
            dst = memoryview(ptr).cast("B")
            if bpl == row:
                dst[:row * rows] = src[off:off + row * rows]
            else:
                for r in range(rows):
                    dst[r * bpl:r * bpl + row] = src[off + r * row:off + (r + 1) * row]
            off += row * rows
    except Exception:
        return None
    finally:
        vf.unmap()
    return vf


def _format_key(fmt):
    """Всё, от чего зависит вид кадра на сцене: пиксельный формат, размер,
    цвет, поворот и яркость мастеринга."""
    try:
        rot = fmt.rotation()
        rot = int(getattr(rot, "value", rot))
    except Exception:
        rot = 0
    return (fmt.pixelFormat(), fmt.frameWidth(), fmt.frameHeight(),
            fmt.colorSpace(), fmt.colorTransfer(), fmt.colorRange(),
            rot, _max_luminance(fmt))


class FramePrefetcher(QThread):
    """Фоновый декодер точных кадров вокруг плейхеда (буфер, как в монтажках).

    Одним запуском ffmpeg вытаскивает ЦЕПОЧКУ подряд идущих кадров начиная с
    нужного: декодер всё равно раскручивает GOP от ключевого кадра, поэтому
    соседние кадры достаются почти бесплатно — зато следующий шаг стрелкой
    берётся из кэша мгновенно, без нового seek'а.

    Кадры отдаются сырым RGB (`-f rawvideo -pix_fmt rgb24`), без промежуточного
    JPEG: он бы портил и «Сохранить кадр», и сам стоп-кадр. У HDR-источника —
    QVideoFrame в формате кадров плеера (см. «Кадр в формате плеера» выше):
    плеер рисует такой кадр своим тонмаппингом, и rgb24 с ним не совпадает.
    """

    ready = pyqtSignal(int, object)      # номер кадра, QImage или QVideoFrame (HDR)

    # Сколько памяти отдаём под кэш кадров. 1080p RGB — ~6 МБ на кадр, так что
    # это ~20 кадров FullHD или ~5 кадров 4K.
    BUDGET_BYTES = 128 * 1024 * 1024
    MAX_WINDOW = 24                      # кадров за один ЗАКАЗ (см. request)
    # Верхний предел одного запуска ffmpeg. Запуск не заканчивается на окне
    # заказа: пока пользователь идёт кадрами ВПЕРЁД, тот же процесс просто
    # продолжает отдавать следующие кадры (см. _decode_run) — один seek и одна
    # раскрутка GOP на всю серию удержания вместо новых каждые MAX_WINDOW
    # кадров. Предел нужен, чтобы забытый процесс не декодировал весь фильм.
    MAX_RUN = 600
    # Насколько далеко впереди плейхеда держим декодированный запас. Больше
    # этого убегать незачем: кадры всё равно вытеснит _trim_cache.
    RUN_LEAD = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cond = threading.Condition()
        self._src = None
        self._size = (0, 0)
        self._fps = 0.0
        self._queue = []                 # [(first_idx, count), …] — новое вытесняет старое
        self._gen = 0                    # поколение запроса (старые результаты не нужны)
        self._stop = False
        self._proc = None
        self._cache = OrderedDict()      # idx -> QImage | QVideoFrame
        self._cache_lock = threading.Lock()
        self._center = 0
        # Середина заказанного окна: вокруг неё буфер и держится (_trim_cache).
        # При шаге назад окно лежит позади плейхеда — кадры впереди него уже
        # пройдены, и вытеснять первыми надо их, а не кадры следующих шагов.
        self._focus = 0.0
        self._budget = 0                 # кадров в бюджете памяти (0 — размер ещё не известен)
        # (first, end) — окно задания, которое декодируется сейчас или ждёт
        # своей очереди (заказ ставит его сразу, см. request).
        self._running = None
        # Вид кадра: None — ещё не выяснен (первый заказ проверит файл),
        # (None, None) — rgb24; (формат QVideoFrameFormat, раскладка) — кадр в
        # формате плеера. _player_fmt — формат, который показал сам плеер.
        self._out = None
        self._props = None
        self._player_fmt = None
        self._hw_decode = True

    # ── публичный API (главный поток) ────────────────────────────────────────
    def set_source(self, path, fps=0.0, hw_decode=True):
        """Новый источник кадров (оригинал или превью-прокси — тот же файл, что
        играет плеер, иначе стоп-кадр отличался бы от воспроизведения).
        hw_decode — включено ли аппаратное декодирование у плеера: от него
        зависит формат HDR-кадров плеера, пока он не показал ни одного."""
        with self._cache_lock:
            self._cache.clear()
        with self._cond:
            self._src = str(path) if path else None
            self._fps = float(fps or 0.0)
            self._size = (0, 0)
            self._budget = 0
            self._queue = []
            self._running = None
            self._out = None
            self._props = None
            self._player_fmt = None
            self._hw_decode = bool(hw_decode)
            self._gen += 1
        self._kill_proc()

    def set_frame_format(self, fmt):
        """Плеер показал первый кадр этого источника — его формат и есть
        правда о том, как сцена рисует кадр. True — вид точных кадров
        поменялся (буфер сброшен, показанный кадр надо заказать заново)."""
        if fmt is None:
            return False
        try:
            fmt = QVideoFrameFormat(fmt)
            key = _format_key(fmt)
        except Exception:
            return False
        with self._cond:
            if self._src is None:
                return False
            old = self._player_fmt
            self._player_fmt = (fmt, key)
            if old is not None and old[1] == key:
                return False
            if self._out is None:
                return False            # вид ещё не выбран — выберет с этим форматом
            props = self._props or {}
            out = self._pick_out(props, self._player_fmt, self._hw_decode)
            if self._same_out(out, self._out):
                return False
            self._out = out
            self._size = (0, 0)
            self._budget = 0
            self._queue = []
            self._running = None
            self._gen += 1
        with self._cache_lock:
            self._cache.clear()
        self._kill_proc()
        return True

    @staticmethod
    def _pick_out(props, player_fmt, hw_decode):
        """Вид точных кадров: (формат, раскладка) или (None, None) — rgb24.

        Формат плеера — если это HDR и его кадр ffmpeg умеет отдать в той же
        раскладке и того же размера; без него — догадка по настройке
        аппаратного декодирования. SDR рисуется без тонмаппинга, и rgb24 с ним
        совпадает (сверено: ±1 уровень)."""
        w, h = qt_frame_size(props.get("width", 0), props.get("height", 0),
                             props.get("sar"))
        if player_fmt is not None:
            fmt = player_fmt[0]
            layout = _RAW_LAYOUTS.get(fmt.pixelFormat())
            hdr = fmt.colorTransfer() in _HDR_TRANSFERS.values()
            if hdr and layout is not None and (fmt.frameWidth(), fmt.frameHeight()) == (w, h):
                return (fmt, layout)
            return (None, None)
        if (props.get("transfer") or "") not in _HDR_TRANSFERS:
            return (None, None)
        return None                      # HDR: догадку строит _decide_out

    @staticmethod
    def _same_out(a, b):
        if a is None or b is None:
            return a is b
        if a[0] is None or b[0] is None:
            return a[0] is b[0]
        return _format_key(a[0]) == _format_key(b[0])

    def clear(self):
        with self._cache_lock:
            self._cache.clear()

    def frame(self, idx):
        """Готовый кадр из кэша (или None). Дёшево — можно звать на каждый шаг."""
        with self._cache_lock:
            img = self._cache.get(int(idx))
            if img is not None:
                self._cache.move_to_end(int(idx))
            return img

    def has(self, idx):
        with self._cache_lock:
            return int(idx) in self._cache

    def request(self, center, ahead=6, behind=4):
        """Заказать окно кадров [center - behind, center + ahead).

        Вперёд (ahead >= behind): первым декодируется САМ center (его ждёт
        экран), следом — кадры перед ним; пока плейхед идёт вперёд, тот же
        запуск продолжает отдавать кадры (_decode_run).

        Назад (behind > ahead) так нельзя: ffmpeg идёт только вперёд, и каждый
        запуск — это раскрутка GOP от ключевого кадра (на длинных GOP — сотни
        кадров). Раньше шаг влево ставил два запуска (center, затем окно
        позади), окно позади на каждом шаге сдвигалось на кадр, и следующий шаг
        перебивал недоделанный запуск — раскрутка начиналась заново на каждый
        шаг, и чем чаще жали стрелку, тем сильнее кадр опаздывал. Теперь окно
        без center декодируется одним запуском вместе с кадрами позади, а пока
        center в буфере, запуск не перебивается, и следующая пачка кадров
        позади заказывается, только когда их недостаёт половины окна."""
        center = max(0, int(center))
        self._center = center
        ahead = max(1, min(self.MAX_WINDOW, int(ahead)))
        behind = max(0, min(self.MAX_WINDOW, int(behind)))
        first_back = max(0, center - behind)
        backward = behind > ahead
        lo, n = self._fit_window(first_back, center + ahead - first_back, center, self._budget)
        self._focus = lo + (n - 1) / 2.0
        with self._cond:
            run = self._running
        have_center = self.has(center)
        # Нужный кадр уже декодируется текущим запуском — НЕ перебиваем его.
        # Иначе удержание стрелки (автоповтор ОС — десятки шагов в секунду)
        # убивало бы ffmpeg на каждом шаге, и ни одно окно не доезжало бы до
        # конца: буфер вечно пустой, а процессор занят перезапусками.
        if run is not None and (run[0] <= center < run[1] or (backward and have_center)):
            return
        need_fwd = [i for i in range(center, center + ahead) if not self.has(i)]
        need_back = [i for i in range(first_back, center) if not self.has(i)]
        jobs = []
        if not backward:
            if need_fwd:
                jobs.append((center, ahead))
            if need_back:
                jobs.append((first_back, center - first_back))
        elif not have_center:
            start = need_back[0] if need_back else center
            jobs.append((start, need_fwd[-1] + 1 - start))
        elif len(need_back) >= max(1, behind // 2):
            jobs.append((need_back[0], need_back[-1] + 1 - need_back[0]))
        if not jobs:
            return
        jobs = [self._fit_window(first, count, center, self._budget) + (center,)
                for first, count in jobs]
        with self._cond:
            if self._src is None:
                return
            self._queue = jobs
            self._gen += 1
            self._running = (jobs[0][0], jobs[0][0] + jobs[0][1])
            # Прежний запуск больше не нужен: он не везёт кадр экрана. Сам он
            # заметил бы это лишь после следующего кадра — а до него может быть
            # вся раскрутка GOP, которую новый запуск ждал бы впустую. Процесс
            # берём под замком: новое задание поток ещё не мог забрать.
            stale = self._proc
            self._cond.notify()
        if stale is not None:
            try:
                stale.kill()
            except Exception:
                pass

    @staticmethod
    def _fit_window(first, count, anchor, budget):
        """Окно [first, first + count) не длиннее budget кадров (0 — бюджет ещё
        не известен): срезается дальний от anchor край — хвост окна вытеснил
        бы из буфера его же начало. (first, count)."""
        count = max(1, int(count))
        if budget > 0 and count > budget:
            first = max(first, min(anchor, first + count - budget))
            count = budget
        return first, count

    def cancel(self):
        """Снять текущее задание (пользователь нажал «играть» — кадры не нужны,
        а ffmpeg зря ест процессор, который сейчас нужен декодеру плеера)."""
        with self._cond:
            self._queue = []
            self._running = None
            self._gen += 1
        self._kill_proc()

    def stop(self):
        with self._cond:
            self._stop = True
            self._queue = []
            self._cond.notify()
        self._kill_proc()

    # ── рабочий поток ────────────────────────────────────────────────────────
    def _kill_proc(self):
        p = self._proc
        if p is not None:
            try:
                p.kill()
            except Exception:
                pass

    def _trim_cache(self, frame_bytes):
        """Выкидывает кадры, самые далёкие от середины заказанного окна, пока
        кэш не влезет в бюджет памяти."""
        if frame_bytes <= 0:
            return
        limit = max(3, int(self.BUDGET_BYTES // frame_bytes))
        with self._cache_lock:
            while len(self._cache) > limit:
                far = max(self._cache, key=lambda i: abs(i - self._focus))
                self._cache.pop(far, None)

    def run(self):
        while True:
            with self._cond:
                while not self._queue and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                jobs = list(self._queue)
                self._queue = []
                src = self._src
                gen = self._gen
            out = self._decide_out(src, gen) if src else None
            if out is not None:          # без размеров сырой поток не разобрать
                for first, count, anchor in jobs:
                    if self._stop or gen != self._gen:
                        break
                    self._decode_run(src, first, count, anchor, out, gen)
            with self._cond:
                if gen == self._gen:
                    self._running = None  # задание кончилось (или не началось)

    def _decide_out(self, src, gen):
        """(ширина, высота, формат, раскладка) кадров источника — выясняется
        один раз на источник. None — размеров нет (сырой поток не разобрать)."""
        with self._cond:
            size, out, props = self._size, self._out, self._props
            player_fmt, hw = self._player_fmt, self._hw_decode
        if size != (0, 0) and out is not None:
            return (size[0], size[1]) + tuple(out)
        if props is None:
            props = probe_video_props(src)
        if out is None:
            out = self._pick_out(props, player_fmt, hw)
        if out is None:
            fmt = guess_player_format(props, probe_mastering_nits(src), hw)
            layout = _RAW_LAYOUTS.get(fmt.pixelFormat()) if fmt is not None else None
            out = (fmt, layout) if layout is not None else (None, None)
        with self._cond:
            if gen != self._gen:
                return None
            if self._player_fmt is not player_fmt:
                # Пока проверяли файл, плеер показал свой первый кадр.
                out = self._pick_out(props, self._player_fmt, hw)
            self._props = props
            self._out = out
            # Размер — как у кадров плеера (с поправкой на SAR), иначе на
            # паузе кадр ляжет в другой letterbox, чем при воспроизведении.
            w, h = qt_frame_size(props.get("width", 0), props.get("height", 0),
                                 props.get("sar"))
            if out[0] is None and abs(props.get("rotation", 0)) % 180 == 90:
                w, h = h, w              # rgb24: ffmpeg разворачивает кадр сам
            self._size = (w, h)
        if w <= 0 or h <= 0:
            return None
        return (w, h) + tuple(out)

    def _decode_run(self, src, first, count, anchor, out, gen):
        """Один запуск ffmpeg: count подряд идущих кадров начиная с first.
        anchor — кадр плейхеда, у которого окно заказано (см. request)."""
        fps = self._fps
        if fps <= 0:
            return
        w, h, fmt, layout = out
        if fmt is None:
            pix_fmt, planes = "rgb24", [(w * 3, h)]
        else:
            pix_fmt, planes = layout[0], _raw_planes(layout[1], w, h)
        frame_bytes = sum(row * rows for row, rows in planes)
        # Больше, чем влезает в бюджет памяти, декодировать бессмысленно —
        # хвост окна вытеснил бы его же начало.
        budget = max(3, self.BUDGET_BYTES // max(1, frame_bytes))
        self._budget = budget
        first, count = self._fit_window(first, count, anchor, budget)
        # Процесс запускаем с ЗАПАСОМ по кадрам, а останавливаем по делу (см.
        # цикл ниже): пока пользователь держит стрелку вправо, тот же ffmpeg
        # продолжает отдавать следующие кадры — без нового seek'а и без новой
        # раскрутки GOP, которая на длинных GOP (аниме-BDRip, 250+ кадров
        # между ключевыми) и стоила всю задержку.
        run_cap = max(count, min(self.MAX_RUN, budget + self.RUN_LEAD))
        ss = max(0.0, (first - 0.25) / fps)
        cmd = [FFMPEG, "-nostdin", "-loglevel", "error",
               "-probesize", "8M", "-analyzeduration", "2M"]
        if fmt is not None:
            # Поворот применит сцена (он записан в формате, как у кадров
            # плеера) — кадр нужен в том виде, в каком он лежит в потоке.
            cmd += ["-noautorotate"]
        cmd += ["-ss", f"{ss:.4f}", "-i", str(src),
                "-frames:v", str(int(run_cap)), "-an", "-sn"]
        props = self._props or {}
        if (props.get("width"), props.get("height")) not in ((w, h), (h, w)):
            # Неквадратный пиксель: растягиваем, как плеер (см. qt_frame_size).
            # Автоповорот ffmpeg стоит в графе раньше -vf, так что w/h здесь
            # уже в осях повёрнутого кадра.
            cmd += ["-vf", f"scale={w}:{h}:flags=bicubic,setsar=1"]
        cmd += ["-f", "rawvideo", "-pix_fmt", pix_fmt, "-"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW)
        except Exception:
            return
        self._proc = proc
        end = first + count
        with self._cond:
            if gen == self._gen:
                self._running = (first, end)
        try:
            idx = first
            while not self._stop and gen == self._gen:
                if idx >= end:
                    # Заказ выполнен. Если плейхед всё это время ШЁЛ ВПЕРЁД
                    # (ушёл от кадра, у которого заказали окно) и уже подобрался
                    # к его концу — не бросаем процесс, а продлеваем: следующие
                    # кадры достаются даром. Если плейхед стоит на месте
                    # (одиночный шаг) или идёт назад — заканчиваем, лишнего не
                    # декодируем: кадры впереди при шаге назад уже пройдены.
                    center = self._center
                    if not (anchor < center < idx + self.RUN_LEAD
                            and idx - center < self.RUN_LEAD
                            and idx < first + run_cap):
                        break
                    end = min(first + run_cap, center + self.RUN_LEAD)
                    with self._cond:
                        # Пока окно живёт, request() не должен его перебивать
                        # (см. проверку _running там же).
                        if gen == self._gen:
                            self._running = (first, end)
                    if idx >= end:
                        break
                buf = proc.stdout.read(frame_bytes)
                if not buf or len(buf) < frame_bytes:
                    break
                if fmt is None:
                    img = QImage(buf, w, h, w * 3, QImage.Format.Format_RGB888).copy()
                    if img.isNull():
                        img = None
                else:
                    img = _video_frame(buf, fmt, planes)
                if img is not None:
                    with self._cache_lock:
                        self._cache[idx] = img
                        self._cache.move_to_end(idx)
                    # Бюджет держим НА ХОДУ: у 4K кадр весит ~25 МБ, и окно
                    # целиком (до 12 кадров) сначала распухло бы на 300 МБ,
                    # и только потом ужалось.
                    self._trim_cache(frame_bytes)
                    self.ready.emit(idx, img)
                idx += 1
        except Exception:
            pass
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
            if self._proc is proc:
                self._proc = None
            with self._cond:
                # Новый заказ уже поставил своё окно — его не трогаем.
                if (gen == self._gen and self._running is not None
                        and self._running[0] == first):
                    self._running = None

# Звук покадрового шага живёт отдельным файлом (см. edit_tab_audio_scrub.py);
# здесь он только реэкспортируется, чтобы прежние импорты не менялись.
from edit_tab_audio_scrub import AudioScrubber      # noqa: E402,F401
