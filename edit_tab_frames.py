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

import subprocess
import threading
from collections import OrderedDict

from config import (CREATE_NO_WINDOW, FFMPEG, FFPROBE, QThread, pyqtSignal)
from PyQt6.QtGui import (QImage)


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
def probe_frame_size(path):
    """(ширина, высота) первого видеопотока через ffprobe. (0, 0) — не вышло.

    Нужны РЕАЛЬНЫЕ размеры декодированного кадра: сырой поток (`-f rawvideo`)
    приходит без заголовков, и разобрать его можно, только зная размер кадра."""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
             str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW, timeout=15)
        lines = (out.stdout or "").strip().splitlines()
        if lines:
            # ffprobe ставит разделитель И В КОНЦЕ строки: «960x540x» (сборки
            # 2026 года; раньше было «960x540»). Прежний partition("x") давал
            # int("540x") → исключение → (0, 0) → предекодер молча не декодировал
            # НИ ОДНОГО кадра, и вся покадровая точность держалась на одном
            # плеере. Поэтому разбираем терпимо: берём непустые поля.
            nums = [p for p in lines[0].split("x") if p.strip()]
            if len(nums) >= 2:
                return (int(nums[0]), int(nums[1]))
    except Exception:
        pass
    return (0, 0)


class FramePrefetcher(QThread):
    """Фоновый декодер точных кадров вокруг плейхеда (буфер, как в монтажках).

    Одним запуском ffmpeg вытаскивает ЦЕПОЧКУ подряд идущих кадров начиная с
    нужного: декодер всё равно раскручивает GOP от ключевого кадра, поэтому
    соседние кадры достаются почти бесплатно — зато следующий шаг стрелкой
    берётся из кэша мгновенно, без нового seek'а.

    Кадры отдаются сырым RGB (`-f rawvideo -pix_fmt rgb24`), без промежуточного
    JPEG: он бы портил и «Сохранить кадр», и сам стоп-кадр.
    """

    ready = pyqtSignal(int, object)      # номер кадра, QImage

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
        self._cache = OrderedDict()      # idx -> QImage
        self._cache_lock = threading.Lock()
        self._center = 0
        self._running = None             # (first, end) — окно, которое декодируется СЕЙЧАС

    # ── публичный API (главный поток) ────────────────────────────────────────
    def set_source(self, path, fps=0.0):
        """Новый источник кадров (оригинал или превью-прокси — тот же файл, что
        играет плеер, иначе стоп-кадр отличался бы от воспроизведения)."""
        with self._cache_lock:
            self._cache.clear()
        with self._cond:
            self._src = str(path) if path else None
            self._fps = float(fps or 0.0)
            self._size = (0, 0)
            self._queue = []
            self._running = None
            self._gen += 1
        self._kill_proc()

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
        """Заказать окно кадров вокруг center. Первым декодируется САМ center
        (его ждёт экран), следом — кадры перед ним."""
        center = max(0, int(center))
        self._center = center
        ahead = max(1, min(self.MAX_WINDOW, int(ahead)))
        behind = max(0, min(self.MAX_WINDOW, int(behind)))
        with self._cond:
            run = self._running
        # Нужный кадр уже декодируется текущим запуском — НЕ перебиваем его.
        # Иначе удержание стрелки (автоповтор ОС — десятки шагов в секунду)
        # убивало бы ffmpeg на каждом шаге, и ни одно окно не доезжало бы до
        # конца: буфер вечно пустой, а процессор занят перезапусками.
        if run is not None and run[0] <= center < run[1]:
            return
        need_fwd = [i for i in range(center, center + ahead) if not self.has(i)]
        first_back = max(0, center - behind)
        need_back = [i for i in range(first_back, center) if not self.has(i)]
        jobs = []
        if need_fwd:
            jobs.append((center, ahead))
        if need_back:
            jobs.append((first_back, center - first_back))
        if not jobs:
            return
        with self._cond:
            if self._src is None:
                return
            self._queue = jobs
            self._gen += 1
            self._cond.notify()

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
        """Выкидывает кадры, самые далёкие от текущего центра, пока кэш не
        влезет в бюджет памяти."""
        if frame_bytes <= 0:
            return
        limit = max(3, int(self.BUDGET_BYTES // frame_bytes))
        with self._cache_lock:
            while len(self._cache) > limit:
                far = max(self._cache, key=lambda i: abs(i - self._center))
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
                size = self._size
            if not src:
                continue
            if size == (0, 0):
                size = probe_frame_size(src)
                with self._cond:
                    if gen == self._gen:
                        self._size = size
            w, h = size
            if w <= 0 or h <= 0:
                continue                 # без размеров сырой поток не разобрать
            for first, count in jobs:
                if self._stop or gen != self._gen:
                    break
                self._decode_run(src, first, count, w, h, gen)

    def _decode_run(self, src, first, count, w, h, gen):
        """Один запуск ffmpeg: count подряд идущих кадров начиная с first."""
        fps = self._fps
        if fps <= 0:
            return
        # Больше, чем влезает в бюджет памяти, декодировать бессмысленно —
        # хвост окна вытеснил бы его же начало.
        budget = max(3, self.BUDGET_BYTES // max(1, w * h * 3))
        count = max(1, min(int(count), budget))
        # Процесс запускаем с ЗАПАСОМ по кадрам, а останавливаем по делу (см.
        # цикл ниже): пока пользователь держит стрелку вправо, тот же ffmpeg
        # продолжает отдавать следующие кадры — без нового seek'а и без новой
        # раскрутки GOP, которая на длинных GOP (аниме-BDRip, 250+ кадров
        # между ключевыми) и стоила всю задержку.
        run_cap = max(count, min(self.MAX_RUN, budget + self.RUN_LEAD))
        ss = max(0.0, (first - 0.25) / fps)
        cmd = [FFMPEG, "-nostdin", "-loglevel", "error",
               "-probesize", "8M", "-analyzeduration", "2M",
               "-ss", f"{ss:.4f}", "-i", str(src),
               "-frames:v", str(int(run_cap)), "-an", "-sn",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        frame_bytes = w * h * 3
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW)
        except Exception:
            return
        self._proc = proc
        end = first + count
        with self._cond:
            self._running = (first, end)
        try:
            idx = first
            while not self._stop and gen == self._gen:
                if idx >= end:
                    # Заказ выполнен. Если плейхед всё это время ШЁЛ ВПЕРЁД
                    # (ушёл от начала окна) и уже подобрался к его концу — не
                    # бросаем процесс, а продлеваем: следующие кадры достаются
                    # даром. Если плейхед стоит на месте (одиночный шаг) —
                    # заканчиваем, лишнего не декодируем.
                    center = self._center
                    if not (first < center < idx + self.RUN_LEAD
                            and idx - center < self.RUN_LEAD
                            and idx < first + run_cap):
                        break
                    end = min(first + run_cap, center + self.RUN_LEAD)
                    with self._cond:
                        # Пока окно живёт, request() не должен его перебивать
                        # (см. проверку _running там же).
                        self._running = (first, end)
                    if idx >= end:
                        break
                buf = proc.stdout.read(frame_bytes)
                if not buf or len(buf) < frame_bytes:
                    break
                img = QImage(buf, w, h, w * 3, QImage.Format.Format_RGB888).copy()
                if not img.isNull():
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
                if self._running is not None and self._running[0] == first:
                    self._running = None

# Звук покадрового шага живёт отдельным файлом (см. edit_tab_audio_scrub.py);
# здесь он только реэкспортируется, чтобы прежние импорты не менялись.
from edit_tab_audio_scrub import AudioScrubber      # noqa: E402,F401
