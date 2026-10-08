# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""RealETACalculator. Public namespace: workers."""
import workers as _api


class RealETACalculator:
    """Адаптивный расчёт оставшегося времени кодирования «на лету».

    Не привязан к мощности ЦП и настройкам кодека: скорость измеряется
    скользящим окном последних `window_sec` секунд (collections.deque), поэтому
    оценка реагирует на скачки FPS из-за сложных/простых сцен, смены пресета или
    другого железа без инерции от начала видео.

    Pass 1 (по кадрам):
        fps   = Δкадров / Δвремени   (в окне)
        ETA   = (всего − кадр) / fps
        Если за этим проходом следует ещё один (has_second_pass=True), к остатку
        добавляется прогноз второго прохода: всего / (fps / pass2_weight_coefficient),
        т.к. второй проход обычно тяжелее (по умолчанию ×3.0).

    Pass 2 (адаптивно под контент):
        читает лог первого прохода и строит кумулятивную карту сложности 0..1.
        В окне считается скорость прохождения СЛОЖНОСТИ в секунду, а не кадров:
        ETA = (1.0 − текущая_доля_сложности) / скорость_сложности.

    Потокобезопасен (внутренний Lock). Вся арифметика O(размер окна) —
    выполняется в рабочем потоке ffmpeg, GUI не трогает, микрофризов не даёт.
    """

    # Гибкий парсер веса кадра: ловит tex/texture/complexity/bits/weight = N.
    _WEIGHT_RE = _api._re_eta.compile(
        r"(?:tex|texture|complexity|bits?|wt|weight)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)",
        _api._re_eta.IGNORECASE,
    )

    def __init__(self, total_frames, pass_num=1, pass2_weight_coefficient=3.0,
                 has_second_pass=False, passlog_path=None, window_sec=15.0):
        self.total_frames = max(1, int(total_frames or 0))
        self.pass_num = int(pass_num)
        self.coef = max(1.0, float(pass2_weight_coefficient))
        self.has_second_pass = bool(has_second_pass)
        self.window_sec = float(window_sec)
        self._lock = _api.threading.Lock()
        self._win = _api.deque()          # (t, x): x = кадр (P1) либо доля сложности (P2)
        self._cum = None             # кумулятивная карта сложности 0..1 по кадрам
        if self.pass_num == 2 and passlog_path:
            self._cum = self._load_complexity_map(passlog_path)

    # ── публичный API ───────────────────────────────────────────────────────
    def update(self, frame_idx, now=None):
        """Скормить номер текущего кадра. Возвращает ETA в секундах (float)
        или None, если данных в окне ещё мало для оценки."""
        now = _api.time.time() if now is None else now
        with self._lock:
            if self.pass_num == 2 and self._cum:
                x = self._frame_complexity(frame_idx)
            else:
                x = float(min(int(frame_idx), self.total_frames))
            self._win.append((now, x))
            # Выкидываем сэмплы старше окна, но всегда оставляем минимум два
            # (нужны для разности Δ).
            while len(self._win) > 2 and (now - self._win[0][0]) > self.window_sec:
                self._win.popleft()
            return self._eta(now)

    # ── внутреннее ──────────────────────────────────────────────────────────
    def _eta(self, now):
        if len(self._win) < 2:
            return None
        t0, x0 = self._win[0]
        t1, x1 = self._win[-1]
        dt = t1 - t0
        dx = x1 - x0
        if dt <= 0.0 or dx <= 0.0:
            return None
        if self.pass_num == 2 and self._cum:
            rate = dx / dt                       # доля сложности в секунду
            return max(0.0, (1.0 - x1) / rate)
        fps = dx / dt
        remaining = max(0, self.total_frames - x1)
        eta = remaining / fps
        if self.has_second_pass:
            eta += self.total_frames / (fps / self.coef)
        return eta

    def _load_complexity_map(self, path):
        """Строит кумулятивную (0..1) карту сложности из лога первого прохода.

        Путь определяется динамически: ffmpeg-двухпроходный лог обычно лежит как
        `<passlogfile>-0.log`, поэтому пробуем и сам путь, и типовые суффиксы."""
        candidates = []
        if path and _api.os.path.isfile(path):
            candidates.append(path)
        for suff in ("-0.log", ".log", "-0.log.temp"):
            c = (path or "") + suff
            if _api.os.path.isfile(c):
                candidates.append(c)
        weights = []
        for c in candidates:
            try:
                with open(c, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        m = self._WEIGHT_RE.search(line)
                        if m:
                            weights.append(float(m.group(1)))
            except Exception:
                continue
            if weights:
                break
        if not weights:
            return None
        total = sum(weights) or 1.0
        cum, acc = [], 0.0
        for w in weights:
            acc += w
            cum.append(acc / total)
        return cum

    def _frame_complexity(self, frame_idx):
        """Доля накопленной сложности к данному кадру (0..1). Длина карты может
        не совпадать с total_frames — масштабируем пропорционально."""
        n = len(self._cum)
        if n == 0:
            return 0.0
        i = int(int(frame_idx) / self.total_frames * n) if self.total_frames else 0
        i = min(max(i, 0), n - 1)
        return self._cum[i]

    @staticmethod
    def fmt(eta_sec):
        """Секунды → HH:MM:SS (или '...' если оценки ещё нет)."""
        if eta_sec is None:
            return "..."
        rem = max(0, int(eta_sec))
        return f"{rem // 3600:02}:{(rem % 3600) // 60:02}:{rem % 60:02}"

RealETACalculator.__module__ = _api.__name__
_api.RealETACalculator = RealETACalculator
