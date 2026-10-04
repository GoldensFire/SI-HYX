# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""RealETACalculator. Public namespace: workers."""
import workers as _api
from .download_network import is_network_error, network_hint
from .download_process import stop_process


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

class InfoWorker(_api.QThread):
    # duration, thumbnail, доступные языки субтитров, доступные языки аудиодорожек
    success = _api.pyqtSignal(int, str, list, list)
    error = _api.pyqtSignal(str)

    def __init__(self, url, proxy=""):
        super().__init__()
        self.url = url
        self.proxy = (proxy or "").strip()
        self.cancelled = False
        self._proc = None

    def cancel(self):
        self.cancelled = True
        stop_process(self._proc)

    @staticmethod
    def _parse_sub_langs(raw: str) -> list:
        """Языки РУЧНЫХ субтитров из JSON-поля subtitles (%(subtitles)j).
        Автосубтитры (automatic_captions) намеренно не берём — у YouTube там
        сотни авто-переводов, которые засорили бы список."""
        try:
            data = _api.json.loads(raw)
            if isinstance(data, dict):
                return sorted(k for k in data.keys() if k and k != "live_chat")
        except Exception:
            pass
        return []

    @staticmethod
    def _parse_audio_langs(raw: str) -> list:
        """Различные языки аудиодорожек из JSON-поля formats. Берём форматы с
        аудио (acodec != none) и непустым language."""
        try:
            formats = _api.json.loads(raw)
            if not isinstance(formats, list):
                return []
            langs = []
            for f in formats:
                if not isinstance(f, dict):
                    continue
                if (f.get("acodec") or "none") == "none":
                    continue
                lang = f.get("language")
                if lang and lang not in ("none", "NA") and lang not in langs:
                    langs.append(lang)
            return sorted(langs)
        except Exception:
            return []

    def run(self):
        base = _api.ytdlp_base_cmd()
        if not base:
            self.error.emit("yt-dlp не найден. Положите yt-dlp.exe в папку bin рядом с программой.")
            return
        try:
            cmd = base + [
                "--no-playlist", "--no-warnings", "--skip-download",
                "--socket-timeout", "15", "--no-check-certificate",
                "--extractor-retries", "2", "--retry-sleep", "1",
                # Каждая строка с префиксом-маркером — парсим по нему, не по позиции
                # (JSON-строки могут быть длинными). subtitles/formats нужны, чтобы
                # заполнить списки «Суб.»/«Язык» реально доступными дорожками.
                "--print", "@@DT@@%(duration)s\t%(thumbnail)s",
                "--print", "@@SB@@%(subtitles)j",
                "--print", "@@FM@@%(formats)j",
            ]
            c_path = _api.get_cookies_path(self.url)
            if _api.os.path.exists(c_path):
                cmd += ["--cookies", c_path]
            if self.proxy:
                cmd += ["--proxy", self.proxy]
            if _api.host_matches(self.url, 'youtube.com', 'youtu.be'):
                cmd += ["--extractor-args", "youtube:player_client=default,web_safari"]
            if _api.host_matches(self.url, 'bilibili.com', 'b23.tv'):
                cmd += ["--referer", "https://www.bilibili.com/", "--user-agent", _api.USER_AGENT]
            cmd += [self.url]

            # TikTok отдаёт challenge-страницу без данных в ~50-80% запусков
            # («rehydration» ЛИБО «Unexpected response»), НЕЗАВИСИМО от UA/cookies;
            # сбой не-retryable внутри yt-dlp, но НОВЫЙ процесс снова имеет шанс —
            # перезапускаем процесс до 12 раз (только TikTok). Иначе превью/метаданные
            # так же мигали бы ошибкой.
            is_tt = _api.host_matches(self.url, 'tiktok.com')
            max_tries = 12 if is_tt else 2
            duration, thumb = 0, ""
            sub_langs, audio_langs = [], []
            for attempt in range(max_tries):
                if self.cancelled: return
                self._proc = _api.subprocess.Popen(
                    cmd, stdout=_api.subprocess.PIPE, stderr=_api.subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=_api.CREATE_NO_WINDOW, env=_api.subprocess_env())
                if self.cancelled:
                    stop_process(self._proc)
                    self._proc.communicate(timeout=5)
                    return
                try:
                    out, err = self._proc.communicate(timeout=60)
                except _api.subprocess.TimeoutExpired:
                    stop_process(self._proc)
                    out, err = self._proc.communicate(timeout=5)
                    err = "Таймаут запроса информации (60 сек.).\n" + (err or "")
                if self.cancelled: return

                for line in (out or "").splitlines():
                    if line.startswith("@@DT@@"):
                        payload = line[len("@@DT@@"):]
                        d, _, t = payload.partition("\t")
                        try: duration = int(float(d)) if d and d != "NA" else 0
                        except Exception: duration = 0
                        thumb = "" if t.strip() in ("", "NA") else t.strip()
                    elif line.startswith("@@SB@@"):
                        sub_langs = self._parse_sub_langs(line[len("@@SB@@"):])
                    elif line.startswith("@@FM@@"):
                        audio_langs = self._parse_audio_langs(line[len("@@FM@@"):])
                if duration or thumb or sub_langs or audio_langs:
                    break
                # Пусто. Повторяем на ЛЮБОЙ флапающей ошибке извлечения TikTok
                # (rehydration / universal data / unexpected response).
                low = (err or "").lower()
                flaky_tiktok = is_tt and any(token in low for token in (
                    "rehydration", "universal data", "unexpected response"))
                if not (attempt + 1 < max_tries
                        and (flaky_tiktok or is_network_error(err))):
                    break
                for _ in range(20):
                    if self.cancelled: return
                    _api.time.sleep(0.1)

            if duration or thumb or sub_langs or audio_langs:
                self.success.emit(duration, thumb, sub_langs, audio_langs)
            else:
                detail = (err or "").strip()[-1500:]
                message = "Не удалось извлечь информацию."
                if detail:
                    message += "\n" + detail
                if is_network_error(detail):
                    message += "\n" + network_hint()
                self.error.emit(message)
        except _api.subprocess.TimeoutExpired:
            stop_process(self._proc)
            if not self.cancelled:
                self.error.emit("Таймаут запроса информации. " + network_hint())
        except Exception as e:
            if not self.cancelled:
                self.error.emit(str(e))

InfoWorker.__module__ = _api.__name__
_api.InfoWorker = InfoWorker

class YtdlpWorker(_api.QThread):
    log_sig = _api.pyqtSignal(str)
    progress_sig = _api.pyqtSignal(str, float, str)
    finished_sig = _api.pyqtSignal(str, str, str, str)
    error_sig = _api.pyqtSignal(str, str)
    thumb_sig = _api.pyqtSignal(str, str)

    from si_hyx_parts.workers.ytdlp_worker___init import (
        __init__,
        _enter_download_phase,
        _watchdog,
        stop,
        _sleep_interruptible,
        _iter_stream_lines,
        _exec_ytdlp,
        _inject_tiktok_headers,
        _height_from_fmt,
    )

    from si_hyx_parts.workers.ytdlp_worker_run import run

    from si_hyx_parts.workers.ytdlp_worker__cleanup_partials import (
        _cleanup_partials,
        _parse_progress,
    )

    _MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv",
                   ".ts", ".m4a", ".mp3", ".opus", ".ogg", ".aac", ".wav", ".3gp")

    from si_hyx_parts.workers.ytdlp_worker__find_recent_output import (
        _find_recent_output,
        _emit_hints,
    )

YtdlpWorker.__module__ = _api.__name__
_api.YtdlpWorker = YtdlpWorker
