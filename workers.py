# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# workers.py — фоновые потоки: загрузка (yt-dlp) и обработка (ffmpeg)
import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from config import (
    COOKIE_PATHS, CREATE_NO_WINDOW, FFMPEG, FFMPEG7_DIR, FFPROBE, IS_WIN,
    Image, ImageOps, QRunnable, QThread, QThreadPool, TEMP_DIR,
    USER_AGENT, cpu_thread_count, deno_available, pyqtSignal,
    subprocess_env, ytdlp_base_cmd
)
from utils import (
    clean_ansi, clean_url, detect_ffmpeg_encoders, download_cdn_direct,
    fmt_bitrate_with_codec, get_cookies_path, get_fps_float,
    get_media_info, get_video_codec, get_video_codec_label, host_matches,
    human_size, is_animego_site, is_direct_cdn_video, is_embed_candidate,
    measure_loudness, require_svt, resolve_kodik
)
from utils import _cookie_matches_domain, _RE_DIGITS
import re as _re_eta
import math


# Регэксп кадра из stderr ffmpeg ("frame=  123 fps= 45 ...").
_RE_FFMPEG_FRAME = _re_eta.compile(r"frame=\s*(\d+)")

# Нормализация раскладки каналов перед libopus: кодер отвергает «боковые»/
# нестандартные раскладки (5.1(side) у AC3-дорожек) с "Invalid channel
# layout … (exit -22)". На stereo/mono — no-op, downmix не делается.
# Ставится последним фильтром КАЖДОГО кодирования в libopus (см. _af_arg).
OPUS_LAYOUT_FIX = "aformat=channel_layouts=mono|stereo|3.0|4.0|quad|5.0|5.1|6.1|7.1"


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
    _WEIGHT_RE = _re_eta.compile(
        r"(?:tex|texture|complexity|bits?|wt|weight)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)",
        _re_eta.IGNORECASE,
    )

    def __init__(self, total_frames, pass_num=1, pass2_weight_coefficient=3.0,
                 has_second_pass=False, passlog_path=None, window_sec=15.0):
        self.total_frames = max(1, int(total_frames or 0))
        self.pass_num = int(pass_num)
        self.coef = max(1.0, float(pass2_weight_coefficient))
        self.has_second_pass = bool(has_second_pass)
        self.window_sec = float(window_sec)
        self._lock = threading.Lock()
        self._win = deque()          # (t, x): x = кадр (P1) либо доля сложности (P2)
        self._cum = None             # кумулятивная карта сложности 0..1 по кадрам
        if self.pass_num == 2 and passlog_path:
            self._cum = self._load_complexity_map(passlog_path)

    # ── публичный API ───────────────────────────────────────────────────────
    def update(self, frame_idx, now=None):
        """Скормить номер текущего кадра. Возвращает ETA в секундах (float)
        или None, если данных в окне ещё мало для оценки."""
        now = time.time() if now is None else now
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
        if path and os.path.isfile(path):
            candidates.append(path)
        for suff in ("-0.log", ".log", "-0.log.temp"):
            c = (path or "") + suff
            if os.path.isfile(c):
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


class InfoWorker(QThread):
    # duration, thumbnail, доступные языки субтитров, доступные языки аудиодорожек
    success = pyqtSignal(int, str, list, list)
    error = pyqtSignal(str)

    def __init__(self, url, proxy=""):
        super().__init__()
        self.url = url
        self.proxy = (proxy or "").strip()
        self.cancelled = False
        self._proc = None

    @staticmethod
    def _parse_sub_langs(raw: str) -> list:
        """Языки РУЧНЫХ субтитров из JSON-поля subtitles (%(subtitles)j).
        Автосубтитры (automatic_captions) намеренно не берём — у YouTube там
        сотни авто-переводов, которые засорили бы список."""
        try:
            data = json.loads(raw)
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
            formats = json.loads(raw)
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
        base = ytdlp_base_cmd()
        if not base:
            self.error.emit("yt-dlp не найден. Положите yt-dlp.exe в папку bin рядом с программой.")
            return
        try:
            cmd = base + [
                "--no-playlist", "--no-warnings", "--skip-download",
                "--socket-timeout", "15", "--no-check-certificate",
                # Каждая строка с префиксом-маркером — парсим по нему, не по позиции
                # (JSON-строки могут быть длинными). subtitles/formats нужны, чтобы
                # заполнить списки «Суб.»/«Язык» реально доступными дорожками.
                "--print", "@@DT@@%(duration)s\t%(thumbnail)s",
                "--print", "@@SB@@%(subtitles)j",
                "--print", "@@FM@@%(formats)j",
            ]
            c_path = get_cookies_path(self.url)
            if os.path.exists(c_path):
                cmd += ["--cookies", c_path]
            if self.proxy:
                cmd += ["--proxy", self.proxy]
            if host_matches(self.url, 'youtube.com', 'youtu.be'):
                cmd += ["--extractor-args", "youtube:player_client=default,web_safari"]
            if host_matches(self.url, 'bilibili.com', 'b23.tv'):
                cmd += ["--referer", "https://www.bilibili.com/", "--user-agent", USER_AGENT]
            cmd += [self.url]

            # TikTok отдаёт challenge-страницу без данных в ~50-80% запусков
            # («rehydration» ЛИБО «Unexpected response»), НЕЗАВИСИМО от UA/cookies;
            # сбой не-retryable внутри yt-dlp, но НОВЫЙ процесс снова имеет шанс —
            # перезапускаем процесс до 12 раз (только TikTok). Иначе превью/метаданные
            # так же мигали бы ошибкой.
            is_tt = host_matches(self.url, 'tiktok.com')
            max_tries = 12 if is_tt else 1
            duration, thumb = 0, ""
            sub_langs, audio_langs = [], []
            for attempt in range(max_tries):
                if self.cancelled: return
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=CREATE_NO_WINDOW, env=subprocess_env())
                out, err = self._proc.communicate(timeout=60)
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
                if not (is_tt and attempt + 1 < max_tries
                        and ("rehydration" in low or "universal data" in low
                             or "unexpected response" in low)):
                    break

            if duration or thumb or sub_langs or audio_langs:
                self.success.emit(duration, thumb, sub_langs, audio_langs)
            else:
                self.error.emit("Не удалось извлечь информацию.")
        except subprocess.TimeoutExpired:
            try: self._proc.kill()
            except Exception: pass
            if not self.cancelled:
                self.error.emit("Таймаут запроса информации.")
        except Exception as e:
            if not self.cancelled:
                self.error.emit(str(e))


class YtdlpWorker(QThread):
    log_sig = pyqtSignal(str)
    progress_sig = pyqtSignal(str, float, str)
    finished_sig = pyqtSignal(str, str, str, str)
    error_sig = pyqtSignal(str, str)
    thumb_sig = pyqtSignal(str, str)

    def __init__(self, config):
        super().__init__()
        self.c = config
        self.is_running = True
        self._proc = None
        self._iid = self.c.get('iid', '')
        self._dl_start_ts = None
        self._last_real_progress = 0.0
        self._last_pct = 0.0
        # Реальная загрузка началась (виден before_dl/@@META@@ или кадр прогресса).
        # До этого идёт ИЗВЛЕЧЕНИЕ — оно может падать (нестабильный TikTok-challenge),
        # и его нельзя выдавать за «Скачивание…».
        self._download_phase = False
        self._dl_phase_ts = None

    def _enter_download_phase(self):
        """Отмечаем переход «извлечение → реальная загрузка». До этого момента
        watchdog не тикает «Скачивание…», а в панели задач нет индикатора — чтобы
        провалившееся извлечение не выглядело как идущая загрузка."""
        if not self._download_phase:
            self._download_phase = True
            self._dl_phase_ts = time.time()

    def _watchdog(self, proc):
        """Пока РЕАЛЬНО идёт скачивание, а yt-dlp молчит (например download-sections
        через ffmpeg даёт 0% и тишину на минуты) — тикаем «Скачивание… mm:ss», чтобы
        строка не висела на «Подготовка…»/0%. Настоящий прогресс имеет приоритет.

        ВАЖНО:
          • тикаем ТОЛЬКО после начала загрузки (self._download_phase). На этапе
            извлечения (которое у TikTok нестабильно и часто падает) «Скачивание…»
            выдавать нельзя — иначе провалившаяся попытка выглядит как загрузка;
          • следим за СВОИМ процессом (proc) и перепроверяем его ПОСЛЕ сна. Иначе
            «опоздавший» тик мог прилететь уже после ошибки и навсегда повесить
            строку на «Скачивание…», а иконку в панели задач — на «бегущую полосу»
            (воркер уже завершён, снять их некому). Каждая повторная попытка
            запускает свой watchdog — проверка `proc is self._proc` гасит чужие."""
        while self.is_running and proc.poll() is None:
            time.sleep(1.0)
            # Перепроверяем после сна: процесс мог завершиться (ошибкой/успехом),
            # могла стартовать новая попытка (proc != self._proc) или прийти стоп.
            if (not self.is_running or proc.poll() is not None
                    or proc is not self._proc):
                return
            if not self._download_phase or not self._dl_phase_ts:
                continue
            now = time.time()
            if (now - self._last_real_progress) > 2.0:
                el = int(now - self._dl_phase_ts)
                # pct=-1 → UI покажет «…» вместо ложного «0.0%»
                self.progress_sig.emit(self._iid, -1.0,
                                       f"Скачивание… {el // 60}:{el % 60:02d}")

    def stop(self):
        self.is_running = False
        p = self._proc
        if p and p.poll() is None:
            try: p.kill()
            except Exception: pass

    def _sleep_interruptible(self, seconds):
        """Пауза, прерываемая кнопкой СТОП: спим мелкими квантами и выходим, как
        только is_running сброшен."""
        end = time.time() + max(0.0, seconds)
        while self.is_running and time.time() < end:
            time.sleep(0.1)

    # ─── ДОБАВИТЬ В YtdlpWorker ───────────────────────────────────────────────────

    @staticmethod
    def _iter_stream_lines(stream):
        """Итерирует поток, разбивая строки И по '\\n', И по '\\r'.

        Обычный `for line in stream` режет только по '\\n'. Но ffmpeg (которым
        yt-dlp качает отрезок через --download-sections) печатает прогресс
        «frame=… time=… speed=…» через ВОЗВРАТ КАРЕТКИ '\\r' без перевода строки.
        При построчной итерации такие обновления копятся в одном буфере и не
        доставляются до конца процесса — из-за чего % нарезки не показывался, а
        строка висела на watchdog-тикере «Скачивание… mm:ss». Читаем посимвольно
        (объём вывода загрузки небольшой) и отдаём кусок на каждом '\\r'/'\\n'."""
        buf = []
        while True:
            ch = stream.read(1)
            if not ch:
                if buf:
                    yield "".join(buf)
                return
            if ch in ("\r", "\n"):
                if buf:
                    yield "".join(buf)
                    buf = []
            else:
                buf.append(ch)

    def _exec_ytdlp(self, cmd: list, iid: str, is_audio_only: bool):
        """
        Запускает yt-dlp, читает stdout построчно.
        Возвращает (returncode, out_fullpath, clean_res_str, tail_lines).
        Вынесено из run() для поддержки fallback-retry без дублирования кода.
        """
        out_fullpath = ""
        clean_res_str = ""
        tail = deque(maxlen=40)

        self._dl_start_ts = time.time()
        self._last_real_progress = time.time()
        self._last_pct = 0.0  # новая попытка качает с нуля — не тянуть % с прошлой
        # Новая попытка снова начинается с извлечения — сбрасываем фазу загрузки.
        self._download_phase = False
        self._dl_phase_ts = None

        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW, bufsize=1, env=subprocess_env())
        threading.Thread(target=self._watchdog, args=(self._proc,), daemon=True).start()

        for raw in self._iter_stream_lines(self._proc.stdout):
            if not self.is_running:
                break
            line = clean_ansi(raw.rstrip("\r\n"))
            if not line:
                continue
            if line.startswith("@@@"):
                self._parse_progress(line[3:])
                continue
            if "@@META@@" in line:
                # before_dl: извлечение прошло, начинается реальная загрузка.
                self._enter_download_phase()
                try:
                    th, w, h, abr = (line.split("@@META@@", 1)[1].split("\t") + ["", "", "", ""])[:4]
                    if th and th != "NA":
                        self.thumb_sig.emit(iid, th)
                    if not clean_res_str:
                        if is_audio_only and abr and abr != "NA":
                            clean_res_str = f"{int(float(abr))} кбит/с"
                        elif w not in ("", "NA") and h not in ("", "NA"):
                            clean_res_str = f"{w}x{h}"
                except Exception:
                    pass
                continue
            if "@@PATH@@" in line:
                out_fullpath = line.split("@@PATH@@", 1)[1].strip()
                continue
            # Прогресс НАРЕЗКИ: при --download-sections качает ffmpeg (не нативный
            # загрузчик yt-dlp), поэтому строк @@@ нет — реальный процент берём из
            # ffmpeg-строк «frame=… time=HH:MM:SS… speed=Nx» относительно длины
            # отрезка. Отрицательный time (стартовый префрейм) regex не ловит —
            # пропускаем. Эти строки НЕ льём в лог, чтобы не спамить консоль.
            if (getattr(self, "_section_dur", None) and "time=" in line
                    and ("frame=" in line or "size=" in line)):
                m = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
                if m:
                    t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    pct = max(0.0, min(99.9, t / self._section_dur * 100.0))
                    sp = re.search(r"speed=\s*([\d.]+x)", line)
                    self._enter_download_phase()
                    self._last_real_progress = time.time()
                    self._last_pct = pct
                    self.progress_sig.emit(
                        self._iid, pct,
                        f"Нарезка {sp.group(1)}" if sp else "Нарезка…")
                continue
            tail.append(line)
            self.log_sig.emit(line)
            low = line.lower()
            if not out_fullpath and "has already been downloaded" in low:
                # Файл уже на месте — yt-dlp пропускает скачивание и НЕ печатает
                # after_move (@@PATH@@). Достаём путь из самой строки, иначе
                # «успех без файла» → ложное «файл не найден».
                m = re.search(r"\[download\]\s+(.+?)\s+has already been downloaded", line)
                if m and os.path.exists(m.group(1).strip()):
                    out_fullpath = m.group(1).strip()
            if "[merger]" in low or "[extractaudio]" in low or "merging formats" in low:
                self.progress_sig.emit(iid, 100.0, "Обработка...")

        self._proc.wait()
        return self._proc.returncode, out_fullpath, clean_res_str, list(tail)


    @staticmethod
    def _inject_tiktok_headers(cmd: list, ua: str, header_values) -> list:
        """Копия cmd с добавленным Desktop-UA (Chrome 125) и браузерными
        заголовками TikTok, вставленными ПЕРЕД URL (последний элемент cmd).

        Это ЗАПАСНОЙ режим: первый проход идёт НАТИВНЫМ экстрактором yt-dlp (его
        JS challenge-solver сам ставит правильный UA). Навязывать Chrome-UA на
        первом проходе нельзя — он ломает challenge и yt-dlp падает с «Unable to
        extract universal data for rehydration». UA нужен только если нативный
        путь упёрся в TLS-фингерпринт (пустой ответ → status 0 / JSONDecodeError)."""
        extra = ["--user-agent", ua]
        for h in header_values:
            extra += ["--add-header", h]
        if not cmd:
            return list(extra)
        return list(cmd[:-1]) + extra + [cmd[-1]]


    @staticmethod
    def _height_from_fmt(fmt: str) -> int:
        """Желаемая высота из строки формата yt-dlp (height<=1080 → 1080)."""
        m = re.search(r"height<=?(\d+)", fmt or "")
        return int(m.group(1)) if m else 720

    def run(self):
        iid = self.c.get('iid', '')
        self._iid = iid
        # Старт ВСЕГО задания (а не отдельной попытки): по нему ищем итоговый файл,
        # чтобы найти его, даже если он скачался на ранней попытке, а @@PATH@@ не
        # пришёл (mtime-порог переживает повторы).
        self._job_start_ts = time.time()
        self.progress_sig.emit(iid, 0.0, "Подготовка...")
        try:
            raw_url = self.c.get('url', '')

            # Прямые CDN-ссылки (Instagram fbcdn.net и др.) — по RAW URL, до clean_url
            if is_direct_cdn_video(raw_url):
                out_dir = self.c.get('outdir', '.') or '.'
                self.log_sig.emit("Определена прямая CDN-ссылка, скачиваю без yt-dlp...")
                self.progress_sig.emit(iid, 1.0, "Загрузка CDN...")
                out_path = download_cdn_direct(raw_url, out_dir, log_fn=self.log_sig.emit)
                self.progress_sig.emit(iid, 100.0, "Готово")
                self.finished_sig.emit(iid, "Готово", "", out_path)
                return

            base = ytdlp_base_cmd()
            if not base:
                raise Exception("yt-dlp не найден. Положите yt-dlp.exe в папку bin рядом с программой.")

            url = clean_url(raw_url)
            if url != raw_url: self.log_sig.emit(f"Ссылка очищена: {raw_url} -> {url}")

            out_dir = self.c.get('outdir', '.') or '.'
            is_audio_only = self.c.get('audio_only', False)
            merge = self.c.get('merge') or 'mp4'
            proxy = (self.c.get('proxy') or '').strip()

            # Встроенный плеер Kodik (animego и др. — yt-dlp их не поддерживает):
            # резолвим страницу в прямой m3u8 и качаем уже его.
            kodik = {}
            if not is_audio_only and is_embed_candidate(url):
                want_h = self._height_from_fmt(self.c.get('fmt', ''))
                ep = self.c.get('kodik_episode')
                ep = int(ep) if ep else None
                tr = self.c.get('kodik_translation', '')
                # Резолв Kodik/animego бывает флапающим (AJAX-плеер или сам
                # Kodik временно не отвечает) — как и с TikTok, повтор почти
                # всегда лечит: до 3 попыток с короткой паузой перед сдачей.
                KODIK_MAX = 3
                for kodik_try in range(1, KODIK_MAX + 1):
                    try:
                        kodik = resolve_kodik(url, want_height=want_h, proxy=proxy,
                                              episode=ep, translation=tr,
                                              log_fn=self.log_sig.emit)
                    except Exception as e:
                        self.log_sig.emit(f"Kodik resolve error: {e}")
                        kodik = {}
                    if kodik or not self.is_running:
                        break
                    if kodik_try < KODIK_MAX:
                        self.log_sig.emit(
                            f"Kodik: пустой ответ — повтор {kodik_try}/{KODIK_MAX}…")
                        self._sleep_interruptible(1.5)
            if kodik:
                self.log_sig.emit(f"Встроенный плеер Kodik → качаю {kodik['height']}p (m3u8)")
                url = kodik['url']
            elif is_animego_site(url):
                # Аниме-сайт без полученного Kodik-плеера: yt-dlp его не качает.
                # Не имитируем «скачивание» (раньше падало в generic → Unsupported
                # URL), а сразу честно сообщаем об ошибке.
                raise Exception("Не удалось получить видео с аниме-сайта: Kodik-плеер не отдал ссылку. "
                                "Проверьте выбор серии/озвучки или повторите позже.")

            outtmpl = os.path.join(out_dir, '%(title)s.%(ext)s')

            # download-sections — уникальное имя на каждый отрезок
            section_arg = None
            self._section_dur = None   # длительность отрезка → % прогресса ffmpeg
            start_s = self.c.get('start_s')
            end_s = self.c.get('end_s')
            if start_s is not None or end_s is not None:
                s_val = int(start_s) if start_s else 0
                e_val = int(end_s) if (end_s and end_s > s_val) else None
                if (s_val and s_val > 0) or e_val:
                    section_arg = f"*{s_val}-{e_val if e_val else 'inf'}"
                    if e_val:
                        self._section_dur = float(e_val - s_val)
                    s_tag = f"{s_val}s"
                    e_tag = f"{e_val}s" if e_val else "end"
                    outtmpl = os.path.join(out_dir, f'%(title)s [{s_tag}-{e_tag}].%(ext)s')

            # Для Kodik имя из URL-страницы (иначе yt-dlp возьмёт «720.mp4:hls:manifest»).
            # raw_url — это страница АНИМЕ, одна на все серии, поэтому без номера
            # серии в имени все серии тайтла бьются в один файл: первая скачивается,
            # а любая следующая видит «уже скачано» и молча выходит без файла
            # (rc=0, файла нет — выглядело как случайный сбой скачивания).
            if kodik:
                from urllib.parse import urlparse as _urlparse
                slug = os.path.splitext(os.path.basename(_urlparse(raw_url).path))[0] or "video"
                ep_tag = f" - {ep} серия" if ep else ""
                outtmpl = os.path.join(out_dir, f"{slug}{ep_tag} [{kodik['height']}p].%(ext)s")

            cmd = base + [
                "--newline", "--no-playlist", "--no-mtime", "--progress",
                "--socket-timeout", "30", "--no-check-certificate", "--windows-filenames",
                # Устойчивость к обрывам соединения (DPI/блокировки провайдера, ошибка 10054)
                "--retries", "10", "--fragment-retries", "20",
                "--extractor-retries", "5", "--retry-sleep", "3",
                "-o", outtmpl,
                "--progress-template",
                "download:@@@%(progress._percent_str)s|%(progress._speed_str)s|"
                "%(progress._eta_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes_estimate)s",
                "--no-simulate",
                "--print", "before_dl:@@META@@%(thumbnail)s\t%(width)s\t%(height)s\t%(abr)s",
                "--print", "after_move:@@PATH@@%(filepath)s",
            ]

            # Указываем yt-dlp на наш ffmpeg (bundled в bin/) — иначе отдельный
            # процесс yt-dlp не найдёт ffmpeg для склейки/извлечения аудио.
            # ВАЖНО: для нарезки отрезка (--download-sections) подсовываем ОТДЕЛЬНЫЙ
            # ffmpeg 7.x (bin/ffmpeg7) — основной 8.x ломает нарезку (см. FFMPEG7_DIR
            # в config.py и yt-dlp #16546: битый/audio-only отрезок). Для обычных
            # загрузок остаётся основной ffmpeg.
            ffloc = None
            if section_arg and FFMPEG7_DIR:
                ffloc = FFMPEG7_DIR
            elif os.path.isabs(FFMPEG) and os.path.isfile(FFMPEG):
                ffloc = os.path.dirname(FFMPEG)
            if ffloc:
                cmd += ["--ffmpeg-location", ffloc]
                if section_arg and FFMPEG7_DIR:
                    self.log_sig.emit("Отрезок: использую ffmpeg 7.x для нарезки (bin/ffmpeg7).")
                elif section_arg:
                    self.log_sig.emit("ВНИМАНИЕ: ffmpeg 7.x (bin/ffmpeg7) не найден — "
                                      "нарезка отрезка на ffmpeg 8.x может дать битый файл.")

            # Прокси (если задан в настройках вкладки загрузок)
            if proxy:
                cmd += ["--proxy", proxy]

            # Kodik m3u8 требует Referer на домен плеера
            if kodik and kodik.get('referer'):
                cmd += ["--add-header", f"Referer:{kodik['referer']}"]
                # CDN Kodik троттлит КАЖДОЕ соединение (одиночный поток даёт
                # десятки KiB/s) — сегменты HLS качаем параллельно, а не по
                # одному, иначе загрузка ползёт часами. Прошлый сбой на 32
                # был из-за коллизии имён файлов (см. outtmpl ниже), не из-за
                # числа потоков.
                cmd += ["--concurrent-fragments", "32"]

            if is_audio_only:
                # ТОЛЬКО аудио: берём ЧИСТЫЙ аудиопоток (vcodec=none) — иначе на сайтах
                # без отдельной аудиодорожки fallback `best` тащит ВИДЕО. `--audio-format
                # best` сохраняет исходный кодек (m4a→m4a, opus→opus идут БЕЗ
                # перекодирования: быстрее, без потерь, меньше размер) и не упирается в
                # баг самоперемещения 'X.m4a'->'X.m4a' при совпадении форматов.
                cmd += ["-f", "bestaudio[vcodec=none]/bestaudio/best",
                        "-x", "--audio-format", "best", "--audio-quality", "0"]
            elif kodik:
                # одиночный m3u8 — берём лучшее из манифеста (качество уже выбрано)
                cmd += ["-f", "best", "--merge-output-format", merge]
            else:
                cmd += ["-f", self.c.get('fmt') or "bestvideo+bestaudio/best",
                        "--merge-output-format", merge]

            # Константы заданы здесь, чтобы _inject_tiktok_headers знал, какой UA и
            # какие заголовки добавлять в запасном Desktop-режиме (см. ниже).
            _is_tiktok = host_matches(url, 'tiktok.com')
            _TIKTOK_UA = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
            _TIKTOK_EXTRA_HEADERS = {
                "Accept-Language:en-US,en;q=0.9",
                "Referer:https://www.tiktok.com/",
                "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                'sec-ch-ua:"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile:?0",
                'sec-ch-ua-platform:"Windows"',
            }

            if _is_tiktok:
                # TikTok качаем НАТИВНЫМ экстрактором yt-dlp: его JS challenge-solver
                # сам выставляет нужный UA/заголовки и решает challenge. Навязанный
                # Chrome-UA ЛОМАЛ этот путь → «Unable to extract universal data for
                # rehydration» (воспроизведено: с нашим UA — ошибка, без него — успех).
                # Поэтому Desktop-UA здесь НЕ добавляем — он остаётся ЗАПАСНЫМ
                # вариантом ниже (если нативный путь упрётся в TLS-фингерпринт:
                # пустой ответ → status 0 / JSONDecodeError). api_hostname (Mobile
                # API) тоже не трогаем — без подписей X-Gorgon/X-Khronos он даёт RST.
                self.log_sig.emit("TikTok обнаружен: нативный экстрактор yt-dlp (JS challenge-solver)...")

            if host_matches(url, 'youtube.com', 'youtu.be'):
                self.log_sig.emit("YouTube: клиенты default + web_safari (n-challenge через Deno)...")
                if not deno_available():
                    self.log_sig.emit("ВНИМАНИЕ: Deno не найден — YouTube может отдать только 360p. Положите deno.exe в bin.")
                cmd += ["--extractor-args", "youtube:player_client=default,web_safari"]

            if host_matches(url, 'bilibili.com', 'b23.tv'):
                self.log_sig.emit("BiliBili обнаружен: добавляю Referer + User-Agent (фикс HTTP 412 Precondition Failed).")
                cmd += ["--referer", "https://www.bilibili.com/", "--user-agent", USER_AGENT]

            # Куки: domain-specific имеет приоритет над общим UI-полем
            ui_cookie = self.c.get('cookie_path', '').strip()
            c_path = get_cookies_path(url)
            chosen_cookie = None
            if os.path.exists(c_path) and c_path != COOKIE_PATHS['default']:
                chosen_cookie = c_path
                self.log_sig.emit(f"OK: Cookies для {url[:40]}... -> {c_path}")
            elif ui_cookie and os.path.exists(ui_cookie) and _cookie_matches_domain(ui_cookie, url):
                chosen_cookie = ui_cookie
                self.log_sig.emit(f"OK: Cookies из настроек: {ui_cookie}")
            elif ui_cookie and os.path.exists(ui_cookie) and not _cookie_matches_domain(ui_cookie, url):
                self.log_sig.emit(f"Предупреждение: куки из настроек не подходят для {url[:40]} (пропущены)")
                if os.path.exists(COOKIE_PATHS['default']):
                    chosen_cookie = COOKIE_PATHS['default']
                    self.log_sig.emit(f"OK: Используем общие cookies: {COOKIE_PATHS['default']}")
            elif os.path.exists(COOKIE_PATHS['default']):
                chosen_cookie = COOKIE_PATHS['default']
                self.log_sig.emit(f"OK: Используем общие cookies: {COOKIE_PATHS['default']}")
            if chosen_cookie:
                cmd += ["--cookies", chosen_cookie]

            if self.c.get('sub_lang') and self.c['sub_lang'] != 'Выкл':
                cmd += ["--write-subs", "--sub-langs",
                        "all" if self.c['sub_lang'] == 'all' else self.c['sub_lang']]

            if section_arg:
                cmd += ["--download-sections", section_arg]
                # Force KF → точный рез с перекодированием в точках; иначе быстрый
                # рез копированием (по ближайшим ключевым кадрам).
                if not is_audio_only and self.c.get('force_kf'):
                    cmd += ["--force-keyframes-at-cuts"]

            cmd += [url]

            rc, out_fullpath, clean_res_str, tail = self._exec_ytdlp(cmd, iid, is_audio_only)

            # ── TikTok: ДОБИВАЕМСЯ файла повторами процесса ─────────────────────
            # JS-challenge у TikTok НЕСТАБИЛЕН: каждый запуск НЕЗАВИСИМО от UA и
            # cookies (замеры: успех ~50%, в плохие минуты ~17%) либо отдаёт данные,
            # либо страницу-заглушку → «Unable to extract universal data for
            # rehydration» ЛИБО «Unexpected response from webpage request». Внутри
            # одного yt-dlp это НЕ-retryable (--extractor-retries не помогает: сбой
            # «липнет» к процессу — подтверждено), но КАЖДЫЙ НОВЫЙ процесс снова
            # имеет шанс. Встречается и «успех без файла» (rc=0, но after_move/@@PATH@@
            # не пришёл или CDN отдал пусто) — его тоже лечит новый процесс. Поэтому
            # крутим до 20 раз, ПОКА не получим реальный файл. Сбой — на ЭКСТРАКЦИИ
            # (до загрузки): попытки быстрые (~3с) и без .part-файлов.
            def _tt_flaky(lines):
                j = " ".join(lines or []).lower()
                return ("rehydration" in j or "universal data" in j
                        or "unexpected response" in j)
            # Пустой ответ из-за TLS-фингерпринта (status 0 / JSONDecodeError) — это
            # НЕ флапающий challenge; его лечит ТОЛЬКО Desktop-режим (ниже).
            def _tt_tls_block(lines):
                j = " ".join(lines or []).lower()
                return ("status code 0" in j or "failed to parse json" in j
                        or "jsondecodeerror" in j or "expecting value" in j)

            def _resolved():
                """Готовый файл этой загрузки: путь из @@PATH@@, иначе свежий
                медиафайл задания (если @@PATH@@ не пришёл, но файл реально скачан).
                Поиск скоупится по mtime ≥ старта задания — чужой .siq не подхватится."""
                if out_fullpath and os.path.exists(out_fullpath):
                    return out_fullpath
                if rc in (0, None):
                    return self._find_recent_output(out_dir)
                return ""

            TT_MAX = 20
            tt_try = 0
            # Повторяем, ПОКА нет готового файла И сбой лечится повтором: флапающий
            # challenge ЛИБО «успех без файла» (rc=0/None, но файла нет).
            while (_is_tiktok and self.is_running and not _resolved()
                   and (_tt_flaky(tail) or rc in (0, None)) and tt_try < TT_MAX):
                tt_try += 1
                self.log_sig.emit(
                    f"TikTok: нестабильный ответ сервера — повтор {tt_try}/{TT_MAX}…")
                # pct=0 → строка показывает прогресс повторов, но размер/таскбар не
                # выглядят как идущая загрузка (это всё ещё извлечение).
                self.progress_sig.emit(iid, 0.0, f"Повтор {tt_try}/{TT_MAX}…")
                # Бэкофф: первые попытки — без пауз (обычную флапу ловим быстро),
                # дальше короткая пауза. Учащённый долбёж только продлевает
                # троттлинг TikTok; пауза даёт ограничению «остыть».
                if tt_try > 3:
                    self._sleep_interruptible(2.0)
                    if not self.is_running:
                        break
                rc, out_fullpath, clean_res_str, tail = self._exec_ytdlp(
                    cmd, iid, is_audio_only)

            # Desktop Browser (Chrome 125 UA + браузерные заголовки) — ТОЛЬКО для
            # TLS-блокировки. Для флапающего challenge он ВРЕДЕН: навязанный Chrome-UA
            # ломает challenge и даёт HTTP 403 (воспроизведено), поэтому на _tt_flaky
            # его НЕ запускаем.
            if (_is_tiktok and self.is_running and not _resolved()
                    and _tt_tls_block(tail) and not _tt_flaky(tail)):
                self.log_sig.emit(
                    "TikTok fallback: режим Desktop Browser (Chrome 125 / Windows 11)…")
                cmd_fallback = self._inject_tiktok_headers(
                    cmd, _TIKTOK_UA, _TIKTOK_EXTRA_HEADERS)
                rc, out_fullpath, clean_res_str, tail = self._exec_ytdlp(
                    cmd_fallback, iid, is_audio_only)

            if not self.is_running:
                raise Exception("Загрузка остановлена пользователем")

            final_path = _resolved()
            if not final_path or not os.path.exists(final_path):
                if rc not in (0, None):
                    raise Exception("\n".join(tail) or f"yt-dlp завершился с кодом {rc}")
                # rc==0, но файла нет — раньше причина терялась молча. Тянем
                # хвост вывода (может быть пуст, если процесс оборвался ДО
                # первой текстовой строки — тогда явно указываем и это).
                detail = "\n".join(tail).strip()
                raise Exception(
                    "yt-dlp завершил работу (код 0), но файл не найден"
                    + (f":\n{detail}" if detail
                       else " (вывод пуст — процесс оборвался без единой строки лога)."))
            out_fullpath = final_path

            # На некоторых роликах yt-dlp завершается с rc=0, но молча скатывается
            # на audio-only формат (обычно сбой nsig-расшифровки видеоформатов) —
            # раньше такой результат репортился как «Готово» с битым файлом без
            # картинки. Проверяем видеодорожку, если запрос был не аудио-only.
            if not is_audio_only:
                try:
                    vp = subprocess.run(
                        [FFPROBE, "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=codec_type",
                         "-of", "csv=p=0", out_fullpath],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, creationflags=CREATE_NO_WINDOW,
                    )
                    has_video = bool(vp.stdout.strip())
                except Exception:
                    has_video = True  # ffprobe недоступен — проверку не блокируем
                if not has_video:
                    raise Exception(
                        "yt-dlp скачал файл без видеодорожки (только аудио) — "
                        "вероятно, сбой получения видеоформатов (nsig/Deno). "
                        "Попробуйте скачать заново.")

            try: self._cleanup_partials(out_dir, out_fullpath)
            except Exception: pass
            self.progress_sig.emit(iid, 100.0, "Готово")
            self.finished_sig.emit(iid, "Готово", clean_res_str or "", out_fullpath)

        except Exception as e:
            err_msg = str(e)
            if "остановлена пользователем" in err_msg:
                self.error_sig.emit(iid, "Остановлено")
                self.log_sig.emit("Загрузка отменена.")
            else:
                self.error_sig.emit(iid, err_msg[:200])
                self.log_sig.emit(f"Ошибка: {err_msg}")
            self._emit_hints(err_msg)

    def _cleanup_partials(self, out_dir, final_path):
        """Удаляет осиротевшие промежуточные файлы (.part/.ytdl/.fdash/.fhls) от
        неудачных попыток формата (напр. DASH-таймаут на VK), чтобы рядом с
        итоговым видео не оставался .part. Скоупится по префиксу имени файла."""
        try:
            final = os.path.basename(final_path)
            prefix = (final.split(" [")[0] or final)[:24]
            if not prefix:
                return
            for name in os.listdir(out_dir):
                if name == final:
                    continue
                low = name.lower()
                is_partial = (low.endswith(".part") or low.endswith(".ytdl")
                              or ".fdash" in low or ".fhls" in low)
                if is_partial and name.startswith(prefix):
                    try: os.remove(os.path.join(out_dir, name))
                    except Exception: pass
        except Exception:
            pass

    def _parse_progress(self, payload):
        try:
            parts = payload.split("|")
            pct_str = parts[0].strip().rstrip("%")
            pct = float(pct_str) if pct_str and pct_str != "NA" else 0.0
            speed = parts[1].strip() if len(parts) > 1 else ""
            eta = parts[2].strip() if len(parts) > 2 else ""
            downloaded = parts[3].strip() if len(parts) > 3 else ""
            total = parts[4].strip() if len(parts) > 4 else ""
            if (not total or total == "NA") and downloaded not in ("", "NA"):
                try: msg = f"{speed} (Скачано: {human_size(int(downloaded))})"
                except Exception: msg = speed
            else:
                msg = f"{speed} ETA: {eta}"
            # С параллельными фрагментами (--concurrent-fragments) yt-dlp
            # периодически пересчитывает total_bytes_estimate по среднему
            # размеру уже скачанных сегментов — процент от этого может
            # временно проседать, хотя реально скачанные байты не уменьшаются.
            # Не даём прогресс-бару идти назад.
            pct = max(pct, self._last_pct)
            self._enter_download_phase()  # реальный кадр прогресса = загрузка идёт
            self._last_real_progress = time.time()
            self._last_pct = pct
            self.progress_sig.emit(self._iid, pct, msg)
        except Exception:
            pass

    _MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv",
                   ".ts", ".m4a", ".mp3", ".opus", ".ogg", ".aac", ".wav", ".3gp")

    def _find_recent_output(self, out_dir):
        """Фолбэк, когда yt-dlp не напечатал итоговый путь. Берём ТОЛЬКО
        медиафайл, изменённый в ходе ЭТОГО задания (mtime ≥ старта задания, не
        отдельной попытки — иначе файл с ранней попытки «пропадает» при повторах),
        чтобы не подхватить чужой файл из папки (напр. .siq)."""
        try:
            floor = getattr(self, "_job_start_ts", None)
            if floor is None:
                floor = getattr(self, "_dl_start_ts", 0)
            floor -= 2
            cands = [
                os.path.join(out_dir, fn) for fn in os.listdir(out_dir)
                if os.path.isfile(os.path.join(out_dir, fn))
                and fn.lower().endswith(self._MEDIA_EXTS)
                and os.path.getmtime(os.path.join(out_dir, fn)) >= floor
            ]
            if cands:
                return max(cands, key=os.path.getmtime)
        except Exception:
            pass
        return ""

    def _emit_hints(self, err_msg):
        low = err_msg.lower()
        if ("10054" in err_msg or "connection aborted" in low
                or "connection reset" in low or "connectionreseterror" in low):
            self.log_sig.emit("СОВЕТ: Соединение принудительно разорвано (10054). Обычно это "
                              "блокировка/замедление YouTube провайдером.")
            self.log_sig.emit("  Попробуйте: включить VPN, либо повторить позже. Ретраи уже "
                              "увеличены, но против DPI-блокировки помогает только VPN/прокси.")
            return
        if "Sign in to confirm" in err_msg or "not a bot" in err_msg:
            self.log_sig.emit("СОВЕТ: YouTube требует «не бот» — куки без данных входа.")
            self.log_sig.emit("  Экспортируйте куки залогиненного YouTube (нужны LOGIN_INFO, __Secure-1PSID, SID, SAPISID).")

# Добавить ПЕРЕД блоком: elif "Forbidden" in err_msg or "403" in err_msg:
        elif ("tiktok" in low and (
                "status code 0" in low or
                "failed to parse json" in low or
                "video not available" in low)):
            self.log_sig.emit(
                "СОВЕТ (TikTok status 0 / JSONDecodeError): сервер TikTok оборвал соединение "
                "до отправки ответа — это TLS-fingerprint или rate-limit блокировка."
            )
            self.log_sig.emit(
                "  Варианты решения:\n"
                "  1) Обновите cookies_tiktok.txt — авторизованные куки снижают агрессивность "
                "rate-limit (нужны sessionid, tt_csrf_token, ttwid).\n"
                "  2) Включите VPN/прокси — смена IP часто снимает бан по rate-limit.\n"
                "  3) Обновите yt-dlp: pip install -U yt-dlp  (экстрактор TikTok меняется часто)."
            )

        elif ("tiktok" in low and ("unexpected response" in low
                                   or "rehydration" in low or "universal data" in low)):
            self.log_sig.emit(
                "СОВЕТ: TikTok временно ограничил запросы (anti-bot/throttling) — это НЕ "
                "ошибка программы, а защита сайта после частых обращений.")
            self.log_sig.emit(
                "  Подождите 2–5 минут и повторите — после паузы обычно качается с "
                "1–2 попытки. Ускорить помогает VPN/смена IP. Долбить подряд не нужно: "
                "это только продлевает ограничение.")
        elif "Forbidden" in err_msg or "403" in err_msg:
            u = self.c.get("url", "")
            if host_matches(u, "tiktok.com"):
                self.log_sig.emit("СОВЕТ: 403 на TikTok. Удалите/переименуйте cookies_tiktok.txt.")
            elif host_matches(u, "fbcdn.net", "instagram.com", "cdninstagram.com"):
                self.log_sig.emit("СОВЕТ: 403 на Instagram CDN. Ссылка устарела — откройте видео заново.")
            else:
                self.log_sig.emit("СОВЕТ: 403 Forbidden. Возможно, нужны куки или ссылка устарела.")
        elif "412" in err_msg or "Precondition Failed" in err_msg:
            u = self.c.get("url", "")
            if host_matches(u, "bilibili.com", "b23.tv"):
                self.log_sig.emit("СОВЕТ: 412 на BiliBili — их анти-бот (риск-контроль) режет playurl для гостей.")
                self.log_sig.emit("  Нужны cookies залогиненного аккаунта (SESSDATA). Войдите на bilibili.com в браузере, "
                                  "экспортируйте cookies.txt и укажите его в поле «Cookies» (или положите cookies_bilibili.txt в папку настроек).")
            else:
                self.log_sig.emit("СОВЕТ: 412 Precondition Failed — сайт отклонил запрос. Часто помогают cookies залогиненного аккаунта.")


def _build_atempo_chain(speed_factor: float) -> list:
    """Строит цепочку atempo-фильтров для FFmpeg.
    FFmpeg ограничивает atempo диапазоном [0.5, 2.0], поэтому
    большие/малые значения разбиваются на несколько звеньев.
    """
    chain = []
    t = speed_factor
    while t > 2.0:
        chain.append("atempo=2.0")
        t /= 2.0
    while t < 0.5:
        chain.append("atempo=0.5")
        t *= 2.0
    if abs(t - 1.0) > 0.001:
        chain.append(f"atempo={t:.6f}")
    return chain


class _ImgRunnable(QRunnable):
    """Обёртка для параллельной обработки одного изображения в QThreadPool.
    Потоки QThreadPool — настоящие потоки Qt: эмит сигналов из них безопасен,
    а очистка корректна (в отличие от обычных threading.Thread)."""
    def __init__(self, worker, item, start):
        super().__init__()
        self.worker = worker
        self.item = item
        self.start = start

    def run(self):
        try:
            self.worker._process_item(self.item, False, self.start)
        except Exception:
            pass


class ProcessWorker(QThread):
    progress = pyqtSignal(str, int)
    status = pyqtSignal(str, str, str)
    log = pyqtSignal(str)
    global_progress = pyqtSignal(int, str)
    finished_all = pyqtSignal()
    update_item_sig = pyqtSignal(str, str, str)
    update_lufs_sig = pyqtSignal(str, object, object)
    update_dur_sig = pyqtSignal(str, str)   # iid, длительность итогового файла (сек, строкой)
    active_threads = pyqtSignal(int, int)  # (активных воркеров, максимум) — счётчик в UI
    xpsnr_sig = pyqtSignal(str, object)     # iid, оценка XPSNR в дБ (float) | None

    # Нижняя граница preset для пробных кодирований в _metric_crf_search —
    # не даём поиску унаследовать очень медленный (0-4) preset финального
    # кодирования, иначе один пробный энкод 1080p может идти минутами.
    _SEARCH_PRESET_FLOOR = 6

    def __init__(self, queue_ref, settings, removed_ids=None):
        super().__init__()
        self.queue = queue_ref
        self.settings = settings
        self.stop_flag = False
        # Живой набор iid'ов, удалённых пользователем из очереди во время
        # обработки (тот же объект-множество, что и у MediaTab._removed_ids) —
        # позволяет прервать УЖЕ идущий ffmpeg для конкретного файла, а не
        # только не начинать ещё не стартовавшие (см. cancel_check в
        # run_ffmpeg_capture).
        self.removed_ids = removed_ids if removed_ids is not None else set()
        self.svt_available = require_svt()
        self._img_pool = None  # QThreadPool для параллельной обработки изображений
        self._active_count = 0
        self._active_lock = threading.Lock()
        self._max_threads = 1
        self._priority_flag = self._priority_creationflag(settings.get('priority', 'normal'))

    _AI_BRANDS = ('gemini', 'chatgpt')
    _RAND_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789'

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Если имя содержит AI-бренд — заменяет на 6 случайных символов."""
        if any(b in name.lower() for b in ProcessWorker._AI_BRANDS):
            return ''.join(random.choices(ProcessWorker._RAND_CHARS, k=6))
        return name

    def stop(self): self.stop_flag = True
    def measure_loudness(self, path, start=None, dur=None):
        return measure_loudness(path, should_stop=lambda: self.stop_flag, start=start, dur=dur)

    @staticmethod
    def _priority_creationflag(priority):
        """Windows priority-class флаг для creationflags по выбору пользователя.
        Низкий = Low (IDLE), Обычный = Normal, Высокий = High — как в Диспетчере задач.
        На не-Windows возвращает 0."""
        if not IS_WIN:
            return 0
        p = (priority or 'normal').lower()
        if p in ('low', 'низкий', 'idle'):
            return getattr(subprocess, 'IDLE_PRIORITY_CLASS', 0)
        if p in ('high', 'высокий'):
            return getattr(subprocess, 'HIGH_PRIORITY_CLASS', 0)
        return getattr(subprocess, 'NORMAL_PRIORITY_CLASS', 0)

    def _inc_active(self, weight=1):
        with self._active_lock:
            self._active_count += weight
            n = self._active_count
        self.active_threads.emit(n, max(1, self._max_threads))

    def _dec_active(self, weight=1):
        with self._active_lock:
            self._active_count = max(0, self._active_count - weight)
            n = self._active_count
        self.active_threads.emit(n, max(1, self._max_threads))

    def _out_dir_for(self, path):
        """Каталог экспорта: выбранная пользователем папка (если задана и
        существует), иначе — рядом с исходным файлом."""
        d = self.settings.get('export_dir') or ''
        if d and os.path.isdir(d):
            return d
        return os.path.dirname(path) or "."

    @staticmethod
    def _source_has_alpha(path: str) -> bool:
        """True только если в изображении есть пиксели с реальной прозрачностью."""
        ext = os.path.splitext(path)[1].lower()
        if ext in {'.png', '.gif', '.tiff', '.tif', '.webp', '.bmp',
                   '.ico', '.avif', '.heic', '.heif'}:
            if Image:
                try:
                    with Image.open(path) as im:
                        # Палитра с tRNS — есть прозрачность
                        if im.mode == 'P' and 'transparency' in im.info:
                            return True
                        # LA / RGBa — всегда с альфой
                        if im.mode in ('LA', 'RGBa'):
                            return True
                        # RGBA — проверяем реальные пиксели
                        if im.mode == 'RGBA':
                            r, g, b, a = im.split()
                            return a.getextrema()[0] < 255  # есть хоть один непрозрачный пиксель
                        return False
                except Exception:
                    pass
        # Видео — ffprobe
        try:
            p = subprocess.run(
                [FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=pix_fmt",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, creationflags=CREATE_NO_WINDOW,
            )
            fmt = p.stdout.strip().lower()
            _NO_ALPHA = {'gray', 'grayf32le', 'grayf32be', 'rgb24', 'bgr24',
                         'rgb48le', 'rgb48be', 'bgr48le', 'bgr48be'}
            return 'a' in fmt and fmt not in _NO_ALPHA
        except Exception:
            return False

    @staticmethod
    def _bt709_color_args(path: str) -> list:
        """-color_primaries/-color_trc/-colorspace bt709 — тегирует поток BT.709,
        чтобы плееры не гадали и не показывали SDR-видео «вымытым»/пересвеченным
        из-за неизвестного цветового пространства. Не меняет пиксели — только
        метаданные контейнера.

        БЕЗОПАСНО только для обычных SDR-источников: у настоящего HDR (PQ/HLG,
        BT.2020) эти теги были бы НЕВЕРНЫМИ и испортили бы цвет при просмотре —
        поэтому сперва читаем теги исходника через ffprobe и тегируем BT.709
        лишь когда он сам уже BT.709 или вообще без тегов (частый случай для
        обычных SDR-рипов) — то есть только ДОБАВЛЯЕМ то, что и так верно, а не
        переопределяем реально другое цветовое пространство."""
        try:
            p = subprocess.run(
                [FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=color_primaries,color_transfer,color_space",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, creationflags=CREATE_NO_WINDOW, timeout=15,
            )
            vals = [v.strip().lower() for v in (p.stdout or "").splitlines()]
        except Exception:
            return []
        _SAFE = {"", "unknown", "unspecified", "n/a", "bt709", "bt470bg", "smpte170m"}
        _HDR_MARKERS = ("bt2020", "smpte2084", "arib-std-b67")
        if any(any(m in v for m in _HDR_MARKERS) for v in vals):
            return []  # настоящий HDR/BT.2020 — не трогаем
        if any(v not in _SAFE for v in vals):
            return []  # что-то нестандартное — на всякий случай не тегируем
        return ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]

    @staticmethod
    def _detect_crop(path: str, dur: float = 0.0, start: float = 0.0):
        """Определяет рамку видео без чёрных полос через ffmpeg cropdetect.
        Возвращает строку 'w:h:x:y' для фильтра crop или None, если полос нет
        (детектированная рамка совпадает с исходным кадром).

        Пропускаем первые ~10% (интро/логотипы часто на чёрном фоне дают ложный
        full-frame), анализируем ограниченный отрезок — детект быстрый и не читает
        весь файл. round=2 — чётные размеры (требование SVT-AV1).

        start — смещение начала анализируемого отрезка (обрезка: сэмплить нужно
        внутри [in_s,out_s), а не с начала всего файла)."""
        try:
            ss = ["-ss", f"{start + dur * 0.1:.2f}"] if dur and dur > 12 else (
                ["-ss", f"{start:.2f}"] if start else [])
            cmd = [FFMPEG, "-hide_banner"] + ss + [
                "-i", path, "-t", "12",
                "-vf", "cropdetect=limit=24:round=2:reset=0",
                "-an", "-sn", "-f", "null", "-",
            ]
            p = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
            import re as _re
            matches = _re.findall(r"crop=(\d+):(\d+):(-?\d+):(-?\d+)", p.stderr or "")
            if not matches:
                return None
            w, h, x, y = matches[-1]
            w, h, x, y = int(w), int(h), int(x), int(y)
            if w <= 0 or h <= 0:
                return None
            # Исходные размеры — чтобы не применять crop-«пустышку» (рамка == кадр)
            try:
                pr = subprocess.run(
                    [FFPROBE, "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height",
                     "-of", "csv=p=0:s=x", path],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, creationflags=CREATE_NO_WINDOW,
                )
                iw, ih = (int(v) for v in pr.stdout.strip().split("x")[:2])
                # Полосы реально есть только если рамка заметно меньше кадра
                if w >= iw - 2 and h >= ih - 2:
                    return None
            except Exception:
                pass
            return f"{w}:{h}:{x}:{y}"
        except Exception:
            return None

    @staticmethod
    def _choose_pix_fmt(has_alpha: bool) -> str:
        """Возвращает pix_fmt с учётом альфа-канала. Всегда 10-бит
        (yuv420p10le/yuva420p10le) — выбора 8-бит в настройках больше нет."""
        return "yuva420p10le" if has_alpha else "yuv420p10le"

    @staticmethod
    def _target_dims(ow, oh, adim=0, wlim=0, hlim=0):
        """Целевой размер картинки с учётом всех активных пределов сразу:
        макс. сторона (adim), макс. ширина (wlim), макс. высота (hlim). Пропорции
        сохраняются, применяется самый строгий предел, увеличение не делается.
        Возвращает (w, h) чётные, либо None если ужимать не нужно / размер неизвестен."""
        try:
            ow, oh = int(ow), int(oh)
        except Exception:
            return None
        if ow <= 0 or oh <= 0:
            return None
        factor = 1.0
        if adim and adim > 0: factor = min(factor, adim / max(ow, oh))
        if wlim and wlim > 0: factor = min(factor, wlim / ow)
        if hlim and hlim > 0: factor = min(factor, hlim / oh)
        if factor >= 1.0:
            return None  # уже вписывается во все пределы — не трогаем
        tw = max(2, int(round(ow * factor)))
        th = max(2, int(round(oh * factor)))
        tw -= tw % 2; th -= th % 2  # чётные стороны — безопасно для 4:2:0/4:2:2
        return (max(2, tw), max(2, th))

    @staticmethod
    def _avif_pix_fmt(has_alpha, chroma='420'):
        """pix_fmt для AVIF по выбранной цветовой субдискретизации. Всегда
        10-бит — выбора 8-бит в настройках больше нет.
        420 — минимальный размер, 444 — максимум цветовой чёткости (крупнее файл).
        При альфе цвет всегда идёт как yuva420p10le (альфа выносится
        alphaextract'ом отдельным потоком), поэтому субдискретизация тут
        неприменима."""
        if has_alpha:
            return "yuva420p10le"
        return {'420': 'yuv420p10le', '422': 'yuv422p10le', '444': 'yuv444p10le'}.get(str(chroma), 'yuv420p10le')

    @staticmethod
    def _av1_encoder_args(crf, preset, pix_fmt, tune=0):
        """Аргументы кодировщика SVT-AV1 (единственный используемый кодек).
        tune — режим тюнинга SVT-AV1, выбирается в настройках (c_tune в
        tabs.py): 0=VQ (по умолчанию), 1=PSNR, 2=SSIM, 4=MS-SSIM, 5=VMAF.
        tune=3 (IQ) намеренно не предлагается — работает только в
        all-intra/low-delay предсказании и падает с ошибкой на нашей
        random-access GOP-структуре (keyint=-1:scd=1 ниже). Выбор целевой
        метрики подбора CRF в настройках (Выкл/XPSNR) с этим тюнингом не
        связан — тот влияет только на то, ОТКУДА берётся crf, см.
        _metric_crf_search (самостоятельный подбор CRF под целевую метрику,
        без внешних инструментов).
        GOP: keyint=-1 (без принудительного периода) + scd=1 (детектор смены
        сцены) — ключевые кадры ставятся ТОЛЬКО на реальных сменах сцены.
        Принудительные периодические keyframe — самая дорогая по битам часть
        потока, поэтому это даёт максимальную оптимизацию под размер файла."""
        return ["-c:v", "libsvtav1", "-crf", str(crf),
                "-preset", str(max(0, min(13, int(preset)))),
                "-svtav1-params", f"tune={int(tune)}:keyint=-1:scd=1",
                "-pix_fmt", pix_fmt]

    def _measure_metric(self, orig_path, enc_path, metric):
        """Сравнивает enc_path с orig_path через встроенный ffmpeg-фильтр
        xpsnr, возвращает единое число (XPSNR в дБ) или None при ошибке.
        scale2ref подстраивает оригинал под размер закодированного кадра —
        иначе фильтр падает при несовпадении разрешений (когда в vf_list
        есть scale/crop)."""
        cmd = [FFMPEG, "-i", enc_path, "-i", orig_path,
               "-filter_complex",
               f"[1:v][0:v]scale2ref=flags=bicubic[ref][enc];[enc][ref]{metric}",
               "-f", "null", "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", creationflags=CREATE_NO_WINDOW, timeout=300)
        except Exception:
            return None
        out = (r.stderr or "") + (r.stdout or "")
        if metric == 'xpsnr':
            m = re.search(r'XPSNR\s+y:\s*([\d.]+)\s+u:\s*([\d.]+)\s+v:\s*([\d.]+)', out)
            if not m:
                return None
            y, u, v = float(m.group(1)), float(m.group(2)), float(m.group(3))
            # Взвешенное усреднение в линейной (MSE) области с весами 4:1:1
            # (яркость:цветность при 4:2:0) — стандартная формула сведения
            # XPSNR к одному числу, а не наивное среднее в дБ.
            lin = (4 * (10 ** (-y / 10)) + (10 ** (-u / 10)) + (10 ** (-v / 10))) / 6
            return -10 * math.log10(lin) if lin > 0 else 99.0
        return None

    def _measure_at_crf(self, sample_path, crf, preset, pix_fmt, tune, vf_list,
                        metric='xpsnr', cancel_check=None):
        """Кодирует sample_path (короткий сэмпл, см. metric_sample_input в
        _process_one) заданным CRF и меряет метрику против него же — разовый
        замер (без бинарного поиска _metric_crf_search) для колонки «Оценка
        XPSNR», когда CRF ручной (вместо цели по метрике) или подбор не удался.
        Возвращает float | None."""
        tmp_out = os.path.join(TEMP_DIR, f"xpsnrscore_{uuid.uuid4().hex}.mkv")
        try:
            if self.stop_flag or (cancel_check is not None and cancel_check()):
                return None
            cmd = ([FFMPEG, "-y", "-i", sample_path] +
                   self._av1_encoder_args(crf, preset, pix_fmt, tune) + ["-an"])
            if vf_list: cmd += ["-vf", ",".join(vf_list)]
            cmd += ["-threads", "0", tmp_out]
            ok = self._run_killable(cmd, cancel_check=cancel_check)
            if not ok or not os.path.exists(tmp_out):
                return None
            return self._measure_metric(sample_path, tmp_out, metric)
        except Exception:
            return None
        finally:
            try:
                if os.path.exists(tmp_out): os.remove(tmp_out)
            except Exception: pass

    def _run_killable(self, cmd, cancel_check=None, on_tick=None, t_start=None, poll=0.4):
        """Popen + периодический опрос вместо блокирующего subprocess.run —
        stop_flag/cancel_check подхватываются в пределах poll секунд, а не
        только когда сам процесс (может идти минутами на медленном preset)
        завершится сам. Возвращает True при успешном (returncode 0) завершении,
        False при ошибке/отмене."""
        si = subprocess.STARTUPINFO() if IS_WIN else None
        if IS_WIN and si is not None: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=CREATE_NO_WINDOW | getattr(self, '_priority_flag', 0),
                                 startupinfo=si)
        except Exception:
            return False
        last_tick = time.time()
        while True:
            if self.stop_flag or (cancel_check is not None and cancel_check()):
                try: p.kill()
                except Exception: pass
                try: p.wait(timeout=3)
                except Exception: pass
                return False
            try:
                p.wait(timeout=poll)
                return p.returncode == 0
            except subprocess.TimeoutExpired:
                now = time.time()
                if on_tick is not None and t_start is not None and now - last_tick >= 1.0:
                    last_tick = now
                    try: on_tick(now - t_start)
                    except Exception: pass
                continue

    def _metric_crf_search(self, path, preset, pix_fmt, metric, target,
                            vf_list, cancel_check=None, on_tick=None, tune=0):
        """Подбирает CRF (0-63) без внешних инструментов: вырезает из середины
        файла короткий (~15с) сэмпл и бинарным поиском находит максимальный
        CRF (= минимальный размер), при котором SVT-AV1 (tune — тот же
        тюнинг, что и в финальном кодировании, см. _av1_encoder_args) всё ещё
        даёт метрику (xpsnr, встроенный фильтр ffmpeg) не хуже target.

        Сперва проверяется CRF=0 (лучшее возможное качество) — если даже он не
        дотягивает до target, цель физически недостижима на этом материале
        (типично для шумного/зернистого видео), и нет смысла тратить время на
        полный бинарный поиск (было — до 6 пробных кодирований вслепую, минуты
        на медленных preset'ах; стало — 1 пробa и мгновенный честный отказ).

        preset для проб ограничен снизу (не медленнее _SEARCH_PRESET_FLOOR),
        независимо от того, насколько медленный preset выбран для финального
        кодирования — иначе один пробный энкод 1080p на preset=0-2 может идти
        по несколько минут, и Стоп ждал бы своего часа между попытками. Более
        быстрый preset для поиска — общепринятый компромисс (напр. в ab-av1):
        качество при том же CRF на быстром preset обычно НЕ выше, чем на
        медленном, поэтому финальный (медленный) preset с подобранным CRF
        будет не хуже, а обычно даже с запасом.

        Возвращает (crf:int|None, info:str) — при успехе info — достигнутое
        значение метрики пробы, при неудаче — причина отказа."""
        t_start = time.time()
        search_preset = max(int(preset), self._SEARCH_PRESET_FLOOR)
        try:
            dur, *_ = get_media_info(path)
        except Exception:
            dur = 0.0
        sample_path = path
        sample_tmp = None
        if dur and dur > 20:
            sample_len = min(15.0, dur * 0.3)
            start = max(0.0, dur / 2 - sample_len / 2)
            sample_tmp = os.path.join(TEMP_DIR, f"metricsample_{uuid.uuid4().hex}"
                                                 f"{os.path.splitext(path)[1] or '.mkv'}")
            try:
                cmd_cut = [FFMPEG, "-y", "-ss", f"{start:.3f}", "-i", path,
                           "-t", f"{sample_len:.3f}", "-c", "copy", sample_tmp]
                subprocess.run(cmd_cut, capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)
                if os.path.exists(sample_tmp) and os.path.getsize(sample_tmp) > 0:
                    sample_path = sample_tmp
                else:
                    sample_tmp = None
            except Exception:
                sample_tmp = None

        def _cleanup_sample():
            if sample_tmp:
                try:
                    if os.path.exists(sample_tmp): os.remove(sample_tmp)
                except Exception: pass

        def _cancelled():
            return self.stop_flag or (cancel_check is not None and cancel_check())

        def _trial(crf):
            """Кодирует сэмпл с данным CRF и измеряет метрику. Возвращает
            (score:float|None, err:str|None); err='отменено' при остановке."""
            if _cancelled():
                return None, "отменено"
            tmp_out = os.path.join(TEMP_DIR, f"metrictrial_{uuid.uuid4().hex}.mkv")
            cmd = ([FFMPEG, "-y", "-i", sample_path] +
                   self._av1_encoder_args(crf, search_preset, pix_fmt, tune) + ["-an"])
            if vf_list: cmd += ["-vf", ",".join(vf_list)]
            cmd += ["-threads", "0", tmp_out]
            ok = self._run_killable(cmd, cancel_check=cancel_check, on_tick=on_tick, t_start=t_start)
            if not ok:
                try:
                    if os.path.exists(tmp_out): os.remove(tmp_out)
                except Exception: pass
                return None, ("отменено" if _cancelled() else "ошибка пробного кодирования")
            score = self._measure_metric(sample_path, tmp_out, metric) if os.path.exists(tmp_out) else None
            try:
                if os.path.exists(tmp_out): os.remove(tmp_out)
            except Exception: pass
            if on_tick is not None:
                try: on_tick(time.time() - t_start)
                except Exception: pass
            return score, (None if score is not None else "не удалось измерить метрику")

        # Проверка достижимости: лучший возможный случай — CRF=0.
        score0, err0 = _trial(0)
        if err0 is not None:
            _cleanup_sample()
            return None, err0
        if score0 < target:
            _cleanup_sample()
            return None, (f"даже CRF 0 (лучшее качество) даёт {metric.upper()} ≈{score0:.2f} "
                          f"< цели {target:.2f} — недостижимо на этом материале")

        lo, hi = 0, 63
        best_crf, best_info = 0, f"{score0:.2f}"
        tries, max_tries = 0, 5
        while lo < hi and tries < max_tries:
            mid = (lo + hi + 1) // 2
            score, err = _trial(mid)
            tries += 1
            if err is not None:
                break
            if score >= target:
                best_crf, best_info = mid, f"{score:.2f}"
                lo = mid
            else:
                hi = mid - 1
        _cleanup_sample()
        return best_crf, best_info

    def run_ffmpeg_capture(self, cmd, total_est_sec, percent_callback, label=None, eta_calc=None, cancel_check=None):
        si = subprocess.STARTUPINFO() if IS_WIN else None
        if IS_WIN and si is not None: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        buf = deque(maxlen=8000)
        try:
            p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW | getattr(self, '_priority_flag', 0), startupinfo=si)
        except Exception as e:
            raise Exception(f"Не удалось запустить ffmpeg: {e}")
        start = time.time()
        last_pct = -1
        last_eta = None          # последнее посчитанное ETA (с)
        last_emit_t = 0.0        # когда последний раз слали колбэк
        last_frame = None        # последний разобранный номер кадра ffmpeg
        total_frames = getattr(eta_calc, 'total_frames', 0) if eta_calc is not None else 0
        try:
            while True:
                # cancel_check: файл убрали из очереди во время обработки (см.
                # MediaTab.rem) — прерываем ТОЛЬКО этот процесс, не весь stop_flag.
                if self.stop_flag or (cancel_check is not None and cancel_check()):
                    try: p.kill()
                    except Exception: pass
                    try:
                        tail = p.stderr.read() or ""
                        for L in tail.splitlines(): buf.append(L + "\n")
                    except Exception: pass
                    raise Exception("StoppedByUser")
                line = p.stderr.readline()
                if line: buf.append(line)
                now = time.time()
                elapsed = now - start
                # ── Реальное ETA + кадр: вытаскиваем текущий кадр из строки ffmpeg
                #    и скармливаем адаптивному калькулятору (если он передан). Вся
                #    математика — здесь, в потоке ffmpeg; GUI не трогаем. ───────
                if eta_calc is not None and line:
                    m = _RE_FFMPEG_FRAME.search(line)
                    if m:
                        last_frame = int(m.group(1))
                        try:
                            val = eta_calc.update(last_frame)
                            if val is not None:
                                last_eta = val
                        except Exception:
                            pass
                # ── Прогресс-бар ──────────────────────────────────────────────
                # Временная формула (fallback): чисто по времени. Точна ровно
                # настолько, насколько точен est, — для медленных пресетов упирается
                # в 99% почти мгновенно.
                pct_time = int(min(99, (elapsed / total_est_sec) * 99)) if total_est_sec and total_est_sec > 0 else int(min(98, elapsed * 15))
                if total_frames > 0:
                    # Калькулятор активен → ведём полосу по РЕАЛЬНОМУ прогрессу
                    # кадров (frame/всего). Честно отражает медленные пресеты.
                    if last_frame is not None:
                        pct = int(min(99, last_frame / total_frames * 99))
                    else:
                        # Кадров ещё нет (SVT-AV1 буферизует look-ahead) — лёгкий
                        # «прогрев», но НЕ даём временной формуле улететь в 99 и
                        # потом прыгнуть вниз при первом кадре.
                        pct = min(2, pct_time)
                else:
                    pct = pct_time
                # Монотонность: полоса не едет назад (на стыке прогрев→кадры и при
                # буферизации SVT-AV1, когда frame замирает).
                if pct < last_pct and last_pct >= 0:
                    pct = last_pct
                # Колбэк шлём: (а) при смене целого процента ИЛИ (б) раз в ~1 с,
                # пока есть реальное ETA. Без (б) ETA «замерзал», когда бар упирался
                # в 99% (заниженный est) и pct переставал меняться. Это развязывает
                # обновление ETA от движения полосы прогресса.
                pct_changed = (pct != last_pct)
                eta_tick = (eta_calc is not None and last_eta is not None
                            and (now - last_emit_t) >= 1.0)
                if pct_changed or eta_tick:
                    if pct_changed: last_pct = pct
                    last_emit_t = now
                    eta_sec = last_eta if eta_calc is not None else None
                    try:
                        percent_callback(pct, label, eta_sec)
                    except TypeError:
                        # Обратная совместимость со старыми колбэками (без eta_sec).
                        try:
                            percent_callback(pct, label)
                        except Exception:
                            try:
                                percent_callback(pct)
                            except Exception:
                                pass
                    except Exception:
                        pass
                if not line and p.poll() is not None: break
        except Exception:
            try: p.kill()
            except Exception: pass
            raise
        if p.returncode != 0:
            stderr_tail = ''.join(buf)
            raise subprocess.CalledProcessError(p.returncode, cmd, output=None, stderr=stderr_tail)

    def _estimate_total_frames(self, src_path, speed_factor, cmd, dur_override=None):
        """Оценка числа ВЫХОДНЫХ кадров видео для знаменателя ETA.
        Учитывает изменение скорости (setpts) и принудительный -r из cmd.
        Возвращает 0, если оценить не удалось (тогда ETA-калькулятор не создаётся
        и работает старая оценка по доле прогресса).

        dur_override — длительность ВХОДА в секундах, если она уже известна и НЕ
        равна полной длительности src_path (обрезка: кодируем не весь файл, а
        отрезок [in_s,out_s) — иначе ETA считало бы кадры на весь исходник)."""
        try:
            dur = float(dur_override) if dur_override and dur_override > 0 else 0.0
            if not dur:
                try: dur, *_ = get_media_info(src_path)
                except Exception: dur = 0.0
            if not dur or dur <= 0:
                return 0
            sf = speed_factor if speed_factor and speed_factor > 0 else 1.0
            out_dur = dur / sf
            # Принудительный fps (-r N) перекрывает исходный.
            out_fps = 0.0
            try:
                if "-r" in cmd:
                    out_fps = float(cmd[cmd.index("-r") + 1])
            except Exception:
                out_fps = 0.0
            if out_fps <= 0:
                out_fps = get_fps_float(src_path) or 0.0
            if out_fps <= 0:
                return 0
            return max(1, int(out_dur * out_fps))
        except Exception:
            return 0

    def get_target_bitrate_str(self, path, sel_val):
        if str(sel_val).lower() == 'auto':
            try:
                _, _, _, a_br_str, _ = get_media_info(path)
                if a_br_str and a_br_str != "-":
                    m = _RE_DIGITS.findall(a_br_str)
                    if m:
                        val = int(m[0])
                        if val > 512: val = 512
                        return f"{val}k"
            except Exception: pass
            return "128k"
        return f"{sel_val}k"

    @staticmethod
    def _trim_seek_args(in_s, out_s, speed_factor=1.0):
        """Тот же приём, что EditTab._execute_cut (edit_tab.py:8841-8876): быстрый
        ВХОДНОЙ pre-seek (до ближайшей секунды перед резом) экономит декодирование
        на длинных файлах, а частичный ВЫХОДНОЙ -ss/-t после него остаётся
        кадрово-точным (секунды передаём как есть, без округления до HH:MM:SS —
        погрешности форматирования нет, поэтому pre-seek компенсировать не нужно).

        `-ss` тут ВЫХОДНОЙ (после -i, без второго -i дальше) — ffmpeg декодирует
        и отбрасывает кадры до точки, PTS не обнуляются, а `-t` считает
        длительность уже В ВЫХОДНОЙ (постфильтровой) шкале. Если включена смена
        скорости — setpts потом делит PTS на speed_factor, поэтому сам `-t`
        обязан быть уже поделен на speed_factor: иначе он ограничит ВЫХОД
        нетронутыми «сырыми» секундами и декодер прочитает far больше входа,
        чем нужно (проверено: без деления вместо 5с/1.5x=3.33с выходило
        ровно 5с — «-t» душил по немасштабированному времени).

        Возвращает (pre_args, post_args, t0): pre_args/post_args — куски cmd
        (pre_args ДО `-i`, post_args ПОСЛЕ), t0 — время начала клипа в шкале
        фильтрграфа, нужное чтобы сдвинуть st= у фейдов на правильную величину
        (t0_video ниже уже сам делит на скорость там, где это нужно).

        ВАЖНО про t0: шкалу времени фильтрграфа задаёт именно ВЫХОДНОЙ `-ss`
        (значение после -i), а НЕ абсолютная позиция in_s. Когда есть входной
        pre-seek (`-ss (in_s-PRESEEK)` до -i), он обнуляет тайминги в точке
        pre-seek, и последующий выходной `-ss PRESEEK` выводит клип, начинающийся
        в шкале фильтров с PRESEEK — а не с in_s. Поэтому t0 = значение выходного
        `-ss`: PRESEEK в ветке с pre-seek, in_s — без него. Раньше здесь всегда
        возвращалось in_s, из-за чего при in_s>6с (ветка pre-seek) afade/vfade
        ставились на st ≈ in_s+dur (за пределами клипа) и фейды НЕ применялись,
        хотя суффикс _fade в имени присутствовал (баг «пишет fade, а его нет»).
        При in_s≤6с (без pre-seek) t0=in_s был и остаётся верным."""
        PRESEEK = 3.0
        dur = max(0.0, out_s - in_s)
        sf = speed_factor if speed_factor else 1.0
        out_dur = dur / sf
        # ВЫХОДНОЙ `-ss` применяется к ПОСТфильтровой шкале — а видео там уже
        # сжато setpts=(1/speed)*PTS (и звук atempo), поэтому seek обязан быть
        # ПОДЕЛЁН на speed_factor РОВНО КАК `-t`. Раньше делили только `-t`, а
        # `-ss` слали как есть (PRESEEK/in_s) — при speed≠100% старт уезжал вправо
        # на seek*(speed−1) (напр. PRESEEK=3с ×0.07 = 0.21с ≈ 5 кадров при 107%:
        # баг «обрезка сдвигает начало, первое слово срезается»). Проверено
        # покадрово (SSIM) на реальном 25fps h264: с делением старт встаёт ровно
        # на in_s, без — на in_s + PRESEEK*(speed−1). При speed=100% sf=1 → как было.
        # t0 (шкала фильтрграфа для st= фейдов) остаётся в ИСХОДНОЙ до-setpts шкале
        # (PRESEEK / in_s) — фейды считаются до atempo/после setpts по сырому t0.
        if in_s > 2 * PRESEEK:
            return (["-ss", f"{in_s - PRESEEK:.6f}"],
                    ["-ss", f"{PRESEEK / sf:.6f}", "-t", f"{out_dur:.6f}"],
                    PRESEEK)
        return ([], ["-ss", f"{in_s / sf:.6f}", "-t", f"{out_dur:.6f}"], in_s)

    @staticmethod
    def _out_suffix(is_video, video_enabled, metric, crf, speed_percent,
                    remove_audio, norm, fade):
        """Суффикс имени выходного файла (напр. «_crf45_speed100_norm_fade»).

        Чистая функция (вынесена из process_media для читаемости/тестируемости).
        При авто-подборе CRF (metric=='xpsnr') пишет 'autocrf' вместо числа —
        реальный CRF на этот момент ещё неизвестен, подбирается для каждого файла
        свой, и врать цифрой, взятой ДО подбора, нельзя. Порядок частей сохранён
        1:1 с прежним инлайн-кодом."""
        suffix = ""
        if is_video and video_enabled:
            crf_tag = "autocrf" if metric == 'xpsnr' else f"crf{crf}"
            suffix += f"_{crf_tag}_speed{speed_percent}"
        if remove_audio:
            suffix += "_noaudio"
        elif norm:
            suffix += "_norm"
        if not remove_audio and fade:
            suffix += "_fade"
        return suffix

    @staticmethod
    def _build_audio_filters(sa, t0, fade_out_dur, speed_factor):
        """Цепочка аудиофильтров для ffmpeg `-af` из настроек звука.

        Порядок (сохранён 1:1 с прежним инлайн-кодом process_media): loudnorm →
        fade-in → fade-out → «деградация» (lowpass/highpass/u8/volume) → atempo
        (смена скорости, через _build_atempo_chain). Чистая функция: t0 (начало
        клипа в шкале фильтров) и fade_out_dur (длительность отрезка/файла, нужна
        только ветке fade-out) передаются уже вычисленными — ffprobe тут не
        вызывается, поэтому логику легко покрыть тестами. Вызывать только когда
        звук сохраняется (не remove_audio) — как и раньше."""
        filters = []
        if sa.get('norm'):
            tgt_i = float(sa.get('tgt', -20.0))
            lra = float(sa.get('lra', 11.0))
            tp = float(sa.get('tp', -1.5))
            filters.append(f"loudnorm=I={tgt_i}:LRA={lra}:TP={tp}")
        if sa.get('fade_in'):
            fade_in_d = sa.get('fade_in_d', 1.0)
            # st=t0: при обрезке (trim) seek не обнуляет PTS — фильтр видит
            # исходное время клипа, поэтому фейд-ин начинается от t0, а не 0.
            filters.append(f"afade=t=in:st={t0:.3f}:d={fade_in_d}")
        if sa.get('fade'):
            fade_d = sa.get('fade_d', 1.0)
            filters.append(
                f"afade=t=out:st={max(0.0, t0 + (fade_out_dur or 0.0) - fade_d):.3f}:d={fade_d}")
        if sa.get('deg'):
            filters.append(f"lowpass=f={sa.get('lp', 3000)}")
            filters.append(f"highpass=f={sa.get('hp', 200)}")
            hz = int(sa.get('hz', 44100))
            if sa.get('u8'):
                filters.append(f"aformat=sample_fmts=u8:sample_rates={hz}")
            gain_db = float(sa.get('deg_gain_db', 0.0))
            if abs(gain_db) > 0.01:
                filters.append(f"volume={gain_db}dB")
        if abs(speed_factor - 1.0) > 0.01:
            filters.extend(_build_atempo_chain(speed_factor))
        return filters

    @staticmethod
    def _scale_vf(res_sel):
        """Фильтр `scale` по выбранному разрешению или None (исходное/не задано).

        '1280x720' → вписать в рамку без искажения пропорций
        (force_original_aspect_ratio=decrease), стороны чётные (SVT-AV1 требует).
        Некорректная строка «WxH» откатывается на прямой `scale=<res>`. Чистая
        функция — строит ровно ту же строку, что раньше инлайн в process_media."""
        if not (isinstance(res_sel, str) and res_sel and res_sel != "Исходное"):
            return None
        if 'x' in res_sel:
            try:
                w_str, h_str = res_sel.split('x', 1)
                w = int(w_str); h = int(h_str)
                return (f"scale=w='min(iw,{w})':h='min(ih,{h})'"
                        f":force_original_aspect_ratio=decrease"
                        f":force_divisible_by=2")
            except Exception:
                return f"scale={res_sel}:force_divisible_by=2"
        return f"scale={res_sel}:force_divisible_by=2"

    @staticmethod
    def _af_arg(filters, trim_tail=False):
        """Готовая строка для ffmpeg `-af`: фильтры + фикс раскладки под libopus.

        OPUS_LAYOUT_FIX добавляется ВСЕГДА (в т.ч. когда своих фильтров нет) —
        libopus отвергает «боковые»/нестандартные раскладки каналов (5.1(side)
        у AC3-дорожек) с "Invalid channel layout … (exit -22)"; на stereo/mono
        это no-op и downmix не делается.

        trim_tail=True добавляет aresample=async=1 ПЕРЕД фиксом раскладки —
        выравнивает длину аудио к входной дорожке, срезая «хвост» от latency
        loudnorm и добивки opus-кадров (иначе контейнер длиннее источника).
        Включать только при нормальной скорости: при смене скорости длину
        задаёт atempo, и async лишь помешал бы.

        Чистая функция (вынесена из process_media — раньше эти же две цепочки
        собирались инлайн в четырёх местах)."""
        chain = list(filters)
        if trim_tail:
            chain.append("aresample=async=1")
        chain.append(OPUS_LAYOUT_FIX)
        return ",".join(chain)

    @staticmethod
    def _map_av_args(remove_audio, a_map_sel):
        """`-map`-аргументы: только настоящее видео + (опционально) аудио.

        0:V? исключает обложки/attached_pic. Субтитры/вложения/данные не
        маппим сознательно: их кодеки несовместимы с целевым контейнером →
        ffmpeg падает. a_map_sel — либо конкретная дорожка, выбранная в
        Монтаже ("0:3"), либо "0:a?". Чистая функция."""
        if remove_audio:
            return ["-map", "0:V?"]
        return ["-map", "0:V?", "-map", a_map_sel]

    @staticmethod
    def _fps_args(fps_sel, src_path):
        """`-r`-аргументы по выбранному в настройках fps (или [] — не менять).

        «Исходный (max 30)» ставит -r 30 только если источник реально быстрее
        (иначе кодер бессмысленно растянул бы VFR до CFR). Нечисловые значения
        игнорируются. Единственная нечистота — чтение fps источника."""
        if fps_sel == "Исходный (max 30)":
            try:
                if get_fps_float(src_path) > 30.5:
                    return ["-r", "30"]
            except Exception:
                pass
            return []
        if isinstance(fps_sel, str) and fps_sel != "Исходный":
            try:
                float(fps_sel)
                return ["-r", fps_sel]
            except Exception:
                pass
        return []

    def _build_video_filters(self, sv, item, current_input, trim, t0, t0_video,
                             speed_factor):
        """Цепочка видеофильтров для `-vf` (порядок сохранён 1:1 с прежним
        инлайн-кодом process_media): crop чёрных полос → setpts (скорость) →
        scale → fade-in → fade-out.

        Порядок значим: crop идёт ПЕРВЫМ, чтобы масштаб и фейды считались уже
        от обрезанного кадра, а setpts — ДО fade, поэтому к моменту fade PTS
        уже поделены на speed_factor.

        Не чистая: определение чёрных полос и длительность/fps источника
        требуют чтения файла."""
        vf_list = []

        if sv.get('crop_black'):
            crop = self._detect_crop(current_input, item.get('dur') or 0.0,
                                      start=(trim[0] if trim else 0.0))
            if crop:
                vf_list.append(f"crop={crop}")
                self.log.emit(f"✂ Обрезка чёрных полос: crop={crop}")
            else:
                self.log.emit("✂ Чёрные полосы не обнаружены — обрезка пропущена")

        if abs(speed_factor - 1.0) > 0.01:
            vf_list.append(f"setpts={1.0/speed_factor}*PTS")

        scale_vf = self._scale_vf(sv.get('res', 'Исходное') or 'Исходное')
        if scale_vf:
            vf_list.append(scale_vf)

        # Видео fade in / out (через чёрный).
        # st фейд-ИНА берём в ИСХОДНОЙ (до-setpts) шкале — сырой t0, НЕ
        # поделённый на скорость. Проверено эмпирически: fade-фильтр
        # сопоставляет st по времени кадров ДО setpts, поэтому при обрезке
        # со сменой скорости fade-in ловится ровно на st=t0 (=значение
        # output-seek), а t0_video (t0/speed) промахивается и первый кадр
        # остаётся не затемнённым. При нормальной скорости t0==t0_video,
        # так что обычный (частый) случай не меняется.
        if sv.get('vfade_in'):
            vfi = float(sv.get('vfade_in_d', 1.0))
            if vfi > 0:
                vf_list.append(f"fade=t=in:st={t0:.3f}:d={vfi}")
        if sv.get('vfade_out'):
            vfo = float(sv.get('vfade_out_d', 1.0))
            if vfo > 0:
                src_dur = item.get('dur') or 0.0
                if src_dur <= 0.0:
                    try: src_dur, *_ = get_media_info(current_input)
                    except Exception: src_dur = 0.0
                out_dur = (src_dur / speed_factor) if speed_factor else src_dur
                out_dur += t0_video
                # Фейд должен ЗАВЕРШИТЬСЯ до последнего кадра, иначе кадр
                # окажется на ~96% затемнения, а не на 100%. Сдвигаем фейд
                # на запас (≥1.5 кадра) — фильтр держит чёрный после конца.
                try: _fps = get_fps_float(current_input) or 25.0
                except Exception: _fps = 25.0
                if _fps <= 0: _fps = 25.0
                margin = max(0.08, 1.5 / _fps)
                st = max(0.0, out_dur - vfo - margin)
                vf_list.append(f"fade=t=out:st={st:.3f}:d={vfo}")

        return vf_list

    def _make_metric_sample(self, current_input, trim_pre, trim_post):
        """Вход для пробных замеров качества → (путь, временный_файл_или_None).

        При обрезке (trim) вырезает copy-копию ровно того диапазона, который
        пойдёт в финальный энкод: без этого замер (подбор CRF ИЛИ разовая
        оценка XPSNR) мог бы попасть на кадры вне отрезка. Без trim и при
        любой ошибке нарезки возвращает исходный вход и None — замер просто
        идёт по всему файлу, как раньше. Удаление временного файла — на
        вызывающем (он переживает и подбор CRF, и последующую оценку)."""
        if not trim_pre and not trim_post:
            return current_input, None
        tmp = os.path.join(
            TEMP_DIR, f"metricsample_{uuid.uuid4().hex}"
                      f"{os.path.splitext(current_input)[1] or '.mkv'}")
        try:
            cmd_cut = [FFMPEG, "-y"] + trim_pre + ["-i", current_input] + trim_post + ["-c", "copy", tmp]
            subprocess.run(cmd_cut, capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=120)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                return tmp, tmp
        except Exception:
            pass
        return current_input, tmp

    def _resolve_crf(self, item, sv, crf, sample_input, preset_for_search,
                     search_pix_fmt, video_tune, vf_list, cb):
        """Итоговый CRF для этого файла + эмит оценки XPSNR в таблицу.

        metric=='xpsnr' → CRF подбирается под целевую метрику (_metric_crf_search,
        без внешних инструментов); ручной CRF из настроек остаётся фолбэком,
        если подбор не удался. Когда подбора не было (или он не удался),
        оценку даёт одно пробное кодирование сэмпла на итоговом CRF — это
        дешевле полного повторного прохода."""
        xpsnr_score = None
        vmetric = sv.get('metric', 'none')
        if vmetric == 'xpsnr':
            target_metric = float(sv.get('target_metric', 40.0))
            metric_label = vmetric.upper()
            self.log.emit(f"🔍 подбор CRF под {metric_label} ≥{target_metric:.2f}…")
            cb(2, f"Подбор CRF под {metric_label} {target_metric:.2f}")
            found_crf, info = self._metric_crf_search(
                sample_input, preset_for_search, search_pix_fmt,
                vmetric, target_metric, vf_list, tune=video_tune,
                cancel_check=lambda: item["iid"] in self.removed_ids,
                on_tick=lambda el: cb(min(9, 2 + int(el // 3)),
                                      f"Подбор CRF под {metric_label} {target_metric:.2f} ({int(el)}с)"))
            if found_crf is not None:
                crf = found_crf
                self.log.emit(f"✅ подобран CRF {crf} ({metric_label} ≈{info})")
                # info — уже измеренная оценка НА ЭТОМ ЖЕ crf (подбор
                # останавливается на первом подходящем значении), повторно
                # мерить не нужно.
                try: xpsnr_score = float(info)
                except (TypeError, ValueError): xpsnr_score = None
            else:
                self.log.emit(f"⚠ подбор CRF не удался: {info} → использован ручной CRF {crf}")

        if xpsnr_score is None:
            xpsnr_score = self._measure_at_crf(
                sample_input, crf, preset_for_search, search_pix_fmt,
                video_tune, vf_list, cancel_check=lambda: item["iid"] in self.removed_ids)
        self.xpsnr_sig.emit(item['iid'], xpsnr_score)
        return crf

    def process_media(self, item, cb):
        path = item['path']
        base, ext = os.path.splitext(path)
        out_dir = self._out_dir_for(path)
        sv = self.settings.get('video', {})
        sa = self.settings.get('audio', {})
        crf = sv.get('crf', 35)

        speed_percent = sv.get('speed', 100)
        speed_factor = float(speed_percent) / 100.0
        video_enabled = sv.get('enabled', True)

        # Обрезка + «Обработка» одним проходом (кнопка «Обрезать и обработать» в
        # Монтаже после неточной copy-обрезки): item['trim'] = (in_s, out_s) —
        # режем диапазон исходника ПРЯМО в этом же кодировании, без отдельного
        # x264-реэнкода перед «Обработкой» (которое раньше давало двойное
        # поколение потерь). trim_pre/trim_post вставляются туда, где команда
        # ПЕРВЫЙ раз читает оригинальный `path` (Pass-1, если он есть, иначе
        # Pass-2/прямой проход) — при video_enabled=True Pass-1 архитектурно не
        # запускается (см. step1_needed ниже), так что почти всегда это Pass-2.
        trim = item.get('trim')
        if trim:
            trim_pre, trim_post, t0 = self._trim_seek_args(trim[0], trim[1], speed_factor)
        else:
            trim_pre, trim_post, t0 = [], [], 0.0
        # Выбранная в Монтаже аудиодорожка (кнопка «Обрезать и обработать» на
        # многодорожечном источнике) — иначе -map "0:a?" всегда брал первую
        # дорожку контейнера, игнорируя выбор пользователя.
        audio_index = item.get('audio_index')
        a_map_sel = f"0:{audio_index}" if audio_index is not None else "0:a?"
        # t0 сдвинут видеофильтрам через setpts (он стоит РАНЬШЕ fade в vf_list —
        # к моменту fade PTS уже поделены на speed_factor), а аудиофильтрам —
        # БЕЗ деления (atempo в audio_filters добавляется В КОНЦЕ списка, после
        # fade-фильтров, так что на момент afade PTS ещё исходные).
        t0_video = (t0 / speed_factor) if speed_factor else t0

        vcodec = get_video_codec(path)
        is_video = (vcodec is not None)

        out_ext = ".mp4" if is_video else ".opus"
        out_name = os.path.basename(base)
        sanitized = self._sanitize_name(out_name)
        if sanitized != out_name:
            self.log.emit(f"Имя переименовано (AI-бренд): «{out_name}» → «{sanitized}»")
            out_name = sanitized

        # Удалить аудио — при видео полностью вырезаем звуковую дорожку (-an),
        # остальные аудио-настройки (loudnorm/fade/degrade/битрейт) тогда не
        # имеют смысла. Для аудио-файлов (is_video=False) галочка игнорируется —
        # вырезать звук из чистого аудио значило бы получить пустой файл.
        remove_audio = bool(sa.get('remove')) and is_video

        suffix = self._out_suffix(is_video, video_enabled, sv.get('metric'), crf,
                                  speed_percent, remove_audio,
                                  sa.get('norm'), sa.get('fade'))
        out_name = out_name + suffix + out_ext
        out = os.path.join(out_dir, out_name)

        sel_br = self.settings.get('audio', {}).get('bitrate', '128')
        audio_bitrate = self.get_target_bitrate_str(path, sel_br)

        before_lufs = None
        if not remove_audio:
            try:
                before_lufs = (self.measure_loudness(path, start=trim[0], dur=item.get('dur'))
                                if trim else self.measure_loudness(path))
            except Exception: pass
        # Замер громкости делается всегда (для «Было LUFS») и для длинных файлов
        # длится минуты — если за это время нажали «Стоп», прерываемся здесь же.
        if self.stop_flag:
            raise Exception("StoppedByUser")

        if is_video and video_enabled and not self.svt_available:
            raise Exception("libsvtav1 не доступен в вашей сборке ffmpeg — скрипт настроен работать ТОЛЬКО с svt (libsvtav1).")

        audio_filters = []
        if not remove_audio:
            # Длительность нужна только ветке fade-out — считаем её лениво (и
            # только когда fade включён), чтобы не дёргать ffprobe зря. dur мог не
            # посчитаться при добавлении (кириллица в пути, ffprobe упал) — тогда
            # читаем сейчас, когда файл точно доступен.
            fade_out_dur = 0.0
            if sa.get('fade'):
                fade_out_dur = item.get('dur') or 0.0
                if fade_out_dur <= 0.0:
                    try:
                        fade_out_dur, *_ = get_media_info(path)
                    except Exception:
                        fade_out_dur = 0.0
            audio_filters = self._build_audio_filters(sa, t0, fade_out_dur, speed_factor)

        temp_files = []
        attempted_out = out

        try:
            current_input = path
            audio_codec = "libopus"  # opus в mp4
            is_hevc = (vcodec and ('hevc' in vcodec or 'h265' in vcodec))
            # Когда видео ВСЁ РАВНО перекодируется (step2), отдельный Pass-1 (аудио +
            # copy видео в .mkv) ВРЕДЕН: круговой проход через .mkv ломает тайминги —
            # видео становится CFR-30 (длиннее исходника), а задержка loudnorm/opus
            # превращается в стартовый сдвиг аудио (баг «итог длиннее исходника»).
            # Поэтому при перекодировании видео делаем ОДИН проход (аудиофильтры — в
            # step2). Pass-1 нужен только для аудио-онли/копии видео (вывод формирует
            # ветка else ниже).
            single_pass_video = bool(is_video and video_enabled)
            # Видео-КОПИЯ (перекодирование ВЫКЛ) с аудиофильтрами тоже обязана идти
            # ОДНИМ прямым проходом в .mp4. Прогон через .mkv-посредник ретаймит
            # видео в CFR-30 (177к×1/30=5.900 вместо VFR 5.702 → итог длиннее) и
            # навешивает opus CodecDelay на старт аудио (start_time=0.194 →
            # контейнер 6.02). Прямой `-c:v copy` mp4→mp4 сохраняет исходные PTS
            # пакетов, а aresample=async=1 подрезает хвост loudnorm до длины
            # источника. Только при нормальной скорости: смена скорости требует
            # setpts и несовместима с копией видео.
            single_pass_copy = bool(is_video and not video_enabled
                                    and abs(speed_factor - 1.0) <= 0.01)
            step1_needed = (not single_pass_video) and (not single_pass_copy) and (
                is_hevc or bool(audio_filters) or (is_video and abs(speed_factor - 1.0) > 0.01))
            # Сохранять исходный тайминг кадров: VFR-источники (TikTok, записи экрана)
            # иначе растягиваются кодером до CFR-30 и итог становится длиннее. Только
            # при нормальной скорости и без принудительного fps.
            keep_timing = ((single_pass_video or single_pass_copy)
                           and abs(speed_factor - 1.0) <= 0.01
                           and str(sv.get('fps', 'Исходный')) == 'Исходный')

            # Кап длительности вывода = длине источника. Звук после loudnorm +
            # добивки Opus-кадров оказывается на ~50–70 мс длиннее видеодорожки
            # (audio.start_time 0.014 + dur 12.606 = 12.62 при video 12.554), и
            # контейнер (max по дорожкам) растёт. `-t` обрезает только лишний
            # аудиохвост: последний видеокадр PTS < длительности, поэтому видео не
            # теряется. Применяем, когда тайминг сохраняем и звук реально
            # перекодируется с фильтрами (без фильтров аудио копируется — роста нет).
            # Гейтим по СКОРОСТИ (не keep_timing): при изменённой скорости длина
            # вывода = src/speed ≠ src, поэтому -t src_dur был бы неверным. При
            # нормальной скорости итог обязан равняться источнику — даже если сменили
            # fps. Это вторая линия обороны к aresample=async=1 (тот даёт точную
            # длину, -t лишь срезает грубый выброс на кванте opus-кадра).
            normal_speed = abs(speed_factor - 1.0) <= 0.01
            src_dur_cap = item.get('dur') or 0.0
            if src_dur_cap <= 0.0:
                try: src_dur_cap, *_ = get_media_info(path)
                except Exception: src_dur_cap = 0.0
            # dur_cap дублировал бы наш собственный -t из trim_post тем же числом
            # (src_dur_cap уже = item['dur'] = длине отрезка) — пропускаем, чтобы
            # не слать ffmpeg два -t подряд.
            dur_cap = (["-t", f"{float(src_dur_cap):.3f}"]
                       if (normal_speed and audio_filters and src_dur_cap > 0 and not trim) else [])

            if step1_needed:
                # Промежуточный контейнер для видео — Matroska: он принимает копию
                # ЛЮБОГО видеокодека + libopus. .mp4 же отвергает копию ряда
                # кодеков/потоков (легаси-видео, обложки) → "Invalid argument"
                # (exit -22). Финал всё равно делает step2 (AV1→mp4) или ремукс.
                temp_ext = ".mkv" if is_video else ".opus"
                temp_intermediate = os.path.join(TEMP_DIR, f"inter_{uuid.uuid4().hex}{temp_ext}")
                temp_files.append(temp_intermediate)

                # current_input здесь всегда == path (Pass-1 — первый читатель
                # оригинала), поэтому trim_pre/trim_post режут именно исходник.
                cmd_step1 = [FFMPEG, "-y"] + trim_pre + ["-i", current_input] + trim_post \
                            + self._map_av_args(remove_audio, a_map_sel) \
                            + ["-map_metadata", "-1"]
                if remove_audio:
                    cmd_step1 += ["-an"]
                else:
                    # Аудио-онли: этот Pass-1 И ЕСТЬ финальный файл (ветка else
                    # ниже просто переносит .opus-посредник в вывод). Значит хвост
                    # от latency loudnorm надо срезать ЗДЕСЬ, иначе итог длиннее
                    # источника (без -t → 16.47→16.92). aresample=async=1 правит
                    # старт/склейку, реальный кап длины даёт -t (ниже).
                    cmd_step1 += ["-af", self._af_arg(
                        audio_filters,
                        trim_tail=bool((not is_video) and normal_speed and audio_filters))]
                    cmd_step1 += ["-c:a", audio_codec, "-b:a", audio_bitrate]
                if is_video: cmd_step1 += ["-c:v", "copy"]
                else:
                    cmd_step1 += ["-vn"]
                    # Аудио-онли opus: контейнерная длительность = длине аудио-
                    # дорожки. libopus ВСЕГДА добавляет фиксированную задержку
                    # кодера (pre-skip 312 сэмплов = 6.5 мс @48кГц): эмпирически
                    # итог = (-t) + 0.0065 РОВНО, независимо от длины/битрейта.
                    # Поэтому -t компенсируем на pre-skip, чтобы длительность
                    # совпала с источником точь-в-точь (иначе 16.470→16.4765,
                    # округляется до 16.48). Срезаемые 6.5 мс — в самом конце, на
                    # затухании, неслышны. Гейт как у dur_cap: нормальная скорость,
                    # есть аудиофильтры, нет trim (при trim длину задаёт trim_post).
                    if (not remove_audio and normal_speed and audio_filters
                            and src_dur_cap > 0 and not trim):
                        cmd_step1 += ["-t", f"{max(0.0, float(src_dur_cap) - 0.0065):.4f}"]
                cmd_step1 += [temp_intermediate]

                orig_size = os.path.getsize(path) if os.path.exists(path) else 1
                self.run_ffmpeg_capture(cmd_step1, max(1, int(orig_size/1000000)), cb, label="Pass 1 (Audio)", cancel_check=lambda: item["iid"] in self.removed_ids)
                current_input = temp_intermediate

                if not remove_audio:
                    try:
                        after_norm = self.measure_loudness(temp_intermediate)
                        self.update_lufs_sig.emit(item['iid'], before_lufs, after_norm)
                    except Exception: pass

            if is_video and video_enabled:
                if not self.svt_available: raise Exception("libsvtav1 отсутствует — отмена перекодирования.")
                # Аудио в одно-проходном режиме (Pass-1 пропущен): применяем
                # фильтры и кодируем opus прямо здесь. aresample=async=1 + отсутствие
                # .mkv-кругового прохода убирают сдвиг/удлинение аудио. Без фильтров —
                # копируем исходную дорожку без потерь.
                if remove_audio:
                    step2_audio = ["-an"]
                elif single_pass_video and audio_filters:
                    # trim_tail завязан ТОЛЬКО на скорость, не на keep_timing/fps:
                    # подрезка хвоста нужна и когда сменили fps (см. _af_arg).
                    step2_audio = ["-af", self._af_arg(audio_filters, trim_tail=normal_speed),
                                   "-c:a", audio_codec, "-b:a", audio_bitrate]
                else:
                    step2_audio = ["-c:a", "copy"]
                timing_args = ["-fps_mode", "passthrough"] if keep_timing else []
                # current_input здесь всегда == path: step1_needed исключает
                # single_pass_video (см. выше), поэтому trim ещё не применён.
                cmd_step2 = [FFMPEG, "-y"] + trim_pre + ["-i", current_input] + trim_post \
                            + self._map_av_args(remove_audio, a_map_sel) + timing_args \
                            + ["-map_metadata", "-1", "-map_chapters", "-1"]

                vf_list = self._build_video_filters(sv, item, current_input, trim,
                                                    t0, t0_video, speed_factor)

                cmd_step2 += self._fps_args(sv.get('fps', 'Исходный') or 'Исходный',
                                            current_input)

                preset_mode = sv.get('preset_mode', 'std')
                is_dark_scenes = (preset_mode == "dark")
                # tune SVT-AV1 (0=VQ/1=PSNR/2=SSIM/4=MS-SSIM/5=VMAF), выбирается
                # в настройках (c_tune в tabs.py) — см. _av1_encoder_args.
                video_tune = int(sv.get('tune', 0))

                # Метрика: 'none' — ручной CRF как есть; 'xpsnr' — CRF на этот
                # файл подбирается самостоятельно (_metric_crf_search, без
                # внешних инструментов) под целевое значение метрики (кодек
                # всегда SVT-AV1, тюнинг энкодера — video_tune выше, тот же,
                # что и в финальном кодировании — см. _av1_encoder_args).

                # preset/pix_fmt для пробных кодирований (поиск CRF и/или разовый
                # замер итоговой оценки XPSNR) — те же, что пойдут в реальный
                # финальный энкод этого профиля (см. is_dark_scenes/else дальше).
                preset_for_search = sv.get('pre', 0) if is_dark_scenes else sv.get('pre', 8)
                search_pix_fmt = self._choose_pix_fmt(self._source_has_alpha(current_input))
                # Сэмпл строится ОДИН раз и переживает и подбор CRF, и
                # последующий разовый замер оценки — поэтому убираем его здесь.
                metric_sample_input, metric_sample_tmp = self._make_metric_sample(
                    current_input, trim_pre, trim_post)
                try:
                    crf = self._resolve_crf(item, sv, crf, metric_sample_input,
                                            preset_for_search, search_pix_fmt,
                                            video_tune, vf_list, cb)
                finally:
                    if metric_sample_tmp:
                        try:
                            if os.path.exists(metric_sample_tmp): os.remove(metric_sample_tmp)
                        except Exception: pass

                if is_dark_scenes:
                    # Профиль «Тёмные сцены»: 10-бит, одно-проходный CRF AV1.
                    # SVT-AV1 НЕ поддерживает multi-pass в режиме CRF
                    # ("CRF does not support multi-pass. Use single pass."),
                    # поэтому используем один проход. Для CRF (постоянное качество)
                    # 2-pass всё равно не даёт выигрыша. crf — либо ручной, либо
                    # уже подобран _metric_crf_search под целевую метрику (см. блок выше).
                    has_alpha = self._source_has_alpha(current_input)
                    pix_fmt = self._choose_pix_fmt(has_alpha)
                    preset_val = max(0, min(13, sv.get('pre', 0)))
                    est = max(1, int(os.path.getsize(current_input)/400000)) if os.path.exists(current_input) else 10

                    cmd_dark = [
                        FFMPEG, "-y",
                    ] + trim_pre + ["-i", current_input] + trim_post \
                      + self._map_av_args(remove_audio, a_map_sel) + timing_args + ["-map_metadata", "-1", "-map_chapters", "-1"] \
                      + self._bt709_color_args(current_input) \
                      + self._av1_encoder_args(crf, preset_val, pix_fmt, video_tune)
                    if vf_list:
                        cmd_dark += ["-vf", ",".join(vf_list)]
                    cmd_dark += ["-threads", "0"] + step2_audio + dur_cap
                    if os.path.splitext(attempted_out)[1].lower() == ".mp4":
                        cmd_dark += ["-movflags", "+faststart"]
                    cmd_dark += [attempted_out]

                    self.log.emit("🌑 Тёмные сцены: кодирование (AV1 10-бит, CRF)...")
                    # Адаптивное ETA по окну FPS (один проход CRF → has_second_pass=False).
                    _tf = self._estimate_total_frames(current_input, speed_factor, cmd_dark,
                                                       dur_override=(item.get('dur') if trim else None))
                    _calc = RealETACalculator(_tf, pass_num=1, has_second_pass=False) if _tf > 0 else None
                    self.run_ffmpeg_capture(cmd_dark, est, cb, label="AV1 кодирование (тёмные сцены)", eta_calc=_calc, cancel_check=lambda: item["iid"] in self.removed_ids)

                else:
                    # Стандартный профиль
                    has_alpha = self._source_has_alpha(current_input)
                    pix_fmt = self._choose_pix_fmt(has_alpha)

                    if has_alpha and 'libvpx-vp9' in detect_ffmpeg_encoders():
                        # libsvtav1 не поддерживает yuva420p → переключаемся на VP9+WebM.
                        # 10-бит альфа (yuva420p10le) в libvpx-vp9 — экспериментальный
                        # и «не широко поддерживаемый» формат (ffmpeg сам предупреждает
                        # и требует -strict experimental), поэтому здесь принудительно
                        # 8-бит yuva420p — единственный надёжно совместимый вариант для
                        # прозрачного WebM.
                        self.log.emit("Альфа-канал → выход: VP9 WebM (SVT-AV1 alpha не поддерживает)")
                        attempted_out = os.path.splitext(attempted_out)[0] + ".webm"
                        out = attempted_out
                        cmd_step2 += ["-c:v", "libvpx-vp9",
                                      "-crf", str(crf), "-b:v", "0",
                                      "-pix_fmt", "yuva420p"]
                    elif has_alpha:
                        self.log.emit("⚠ libvpx-vp9 недоступен — альфа будет потеряна (SVT-AV1 alpha не поддерживает)")
                        cmd_step2 += self._bt709_color_args(current_input)
                        cmd_step2 += self._av1_encoder_args(crf, max(0, min(8, sv.get('pre', 8))), self._choose_pix_fmt(False), video_tune)
                    else:
                        cmd_step2 += self._bt709_color_args(current_input)
                        cmd_step2 += self._av1_encoder_args(crf, max(0, min(8, sv.get('pre', 8))), pix_fmt, video_tune)

                    if vf_list: cmd_step2 += ["-vf", ",".join(vf_list)]
                    cmd_step2 += ["-threads", "0"] + step2_audio + dur_cap
                    if os.path.splitext(attempted_out)[1].lower() == ".mp4":
                        cmd_step2 += ["-movflags", "+faststart"]
                    cmd_step2 += [attempted_out]

                    est = max(1, int(os.path.getsize(current_input)/400000)) if os.path.exists(current_input) else 10
                    # Адаптивное ETA по скользящему окну FPS (одно-проходный CRF).
                    _tf = self._estimate_total_frames(current_input, speed_factor, cmd_step2,
                                                       dur_override=(item.get('dur') if trim else None))
                    _calc = RealETACalculator(_tf, pass_num=1, has_second_pass=False) if _tf > 0 else None
                    self.run_ffmpeg_capture(cmd_step2, est, cb, label="Pass 2 (Video)", eta_calc=_calc, cancel_check=lambda: item["iid"] in self.removed_ids)

            else:
                if current_input != path:
                    inter_ext = os.path.splitext(current_input)[1].lower()
                    if inter_ext == out_ext:
                        if os.path.exists(out): os.remove(out)
                        shutil.move(current_input, out)  # step1 уже применил libopus, просто переносим
                    else:
                        # Контейнер промежуточного (.mkv) ≠ выходной → ремукс копией
                        # (видео уже в нужном кодеке, аудио — libopus из step1).
                        cmd_remux = [FFMPEG, "-y", "-i", current_input,
                                     "-map", "0:V?", "-map", "0:a?",
                                     "-c", "copy", out]
                        self.run_ffmpeg_capture(
                            cmd_remux,
                            max(1, int(os.path.getsize(current_input) / 1000000)),
                            cb, label=None, cancel_check=lambda: item["iid"] in self.removed_ids)
                else:
                    # Один прямой проход (видео-копия с аудиофильтрами или аудио-онли).
                    # Для видео-копии (single_pass_copy): passthrough сохраняет VFR-
                    # тайминг при `-c:v copy`, а aresample=async=1 убирает хвост
                    # loudnorm/опус-сдвиг — итог точно равен длине источника.
                    af_direct = self._af_arg(
                        audio_filters,
                        trim_tail=bool(is_video and normal_speed and audio_filters))
                    # Видео тут НЕ перекодируется (-c:v copy) — при заданном trim
                    # рез всё равно останется привязан к ближайшему ключевому
                    # кадру (как обычная copy-обрезка), кадровая точность здесь
                    # принципиально недостижима без реэнкода видео.
                    cmd_direct = [FFMPEG, "-y"] + trim_pre + ["-i", path] + trim_post \
                                 + self._map_av_args(remove_audio, a_map_sel)
                    if is_video and keep_timing:
                        cmd_direct += ["-fps_mode", "passthrough"]
                    if remove_audio:
                        cmd_direct += ["-an"]
                    else:
                        cmd_direct += ["-af", af_direct]
                        cmd_direct += ["-c:a", audio_codec, "-b:a", audio_bitrate]
                    if is_video: cmd_direct += ["-c:v", "copy"]
                    else: cmd_direct += ["-vn"]
                    # Видео-КОПИЯ + аудиофильтры: loudnorm/opus добавляют «хвост»,
                    # из-за которого итог длиннее источника. dur_cap (-t = длине
                    # источника) обрезает лишний аудиохвост — см. определение выше.
                    cmd_direct += dur_cap
                    cmd_direct += [out]
                    self.run_ffmpeg_capture(cmd_direct, max(1, int(os.path.getsize(path)/1000000)), cb, label=None, cancel_check=lambda: item["iid"] in self.removed_ids)

            if os.path.exists(out):
                # «После» LUFS: в одно-проходном режиме Pass-1 (где раньше мерили)
                # пропущен — меряем по готовому файлу.
                if not remove_audio and (single_pass_video or single_pass_copy) and sa.get('norm'):
                    try:
                        after_norm = self.measure_loudness(out)
                        self.update_lufs_sig.emit(item['iid'], before_lufs, after_norm)
                    except Exception: pass
                size_new = os.path.getsize(out)
                dur_new, br_str, _, a_br, a_codec = get_media_info(out)
                vcodec_new = get_video_codec_label(out) if is_video else None
                size_label = f"{vcodec_new} {human_size(size_new)}" if vcodec_new else human_size(size_new)
                self.update_item_sig.emit(item['iid'], size_label,
                                          fmt_bitrate_with_codec(a_codec, a_br or br_str))
                self.update_dur_sig.emit(item['iid'], str(dur_new or 0.0))
                return out
            else:
                raise Exception("Output file не найден после ffmpeg (возможная ошибка записи).")

        except Exception as e:
            errstr = str(e)
            self.log.emit(f"Ошибка при обработке {os.path.basename(path)}: {errstr}")
            try:
                if os.path.exists(attempted_out) and os.path.abspath(attempted_out) != os.path.abspath(path):
                    try:
                        os.remove(attempted_out)
                        self.log.emit(f"Удалён повреждённый/недозаписанный выход: {attempted_out}")
                    except Exception: pass
            except Exception: pass
            for t in temp_files:
                if os.path.exists(t):
                    try:
                        os.remove(t)
                        self.log.emit(f"Удалён временный файл: {t}")
                    except Exception: pass
            raise
        finally:
            for t in temp_files:
                if os.path.exists(t):
                    try: os.remove(t)
                    except Exception: pass

    def _search_quality_under_limit(self, save_to_tmp, limit_kb, passes, q_lo=10, q_hi=95,
                                    on_pass=None):
        """Бинарный поиск макс. quality (q_lo..q_hi), при котором размер файла ≤ limit_kb.
        save_to_tmp(q) -> путь к временному файлу (удаляется здесь же).
        passes — число проб (1..8). on_pass(n, total) — колбэк прогресса подбора
        (n — номер текущей пробы 1..total). Возвращает выбранное quality:
        максимальное влезающее, а если ничего не влезло — q_lo (минимальный размер)."""
        passes = max(1, min(8, int(passes or 4)))
        lo, hi = int(q_lo), int(q_hi)
        chosen, found, n = q_lo, False, 0
        while lo <= hi and n < passes:
            n += 1
            if on_pass:
                try: on_pass(n, passes)
                except Exception: pass
            mid = (lo + hi) // 2
            tmp = save_to_tmp(mid)
            try:
                fits = (os.path.getsize(tmp) // 1024) <= limit_kb
            finally:
                try: os.remove(tmp)
                except Exception: pass
            if fits:
                chosen, found, lo = mid, True, mid + 1
            else:
                hi = mid - 1
        return chosen if found else q_lo

    def _convert_simple_image(self, item, src_path, out_dir, sanitized, adim, av, fmt, cb):
        """Конвертация изображения в png / jpg / ico / webp через Pillow (без ffmpeg).
        Учитывает лимит разрешения (adim) и для jpg/webp — лимит размера файла.
        """
        if not Image:
            raise Exception("Pillow (PIL) не установлен — конвертация в этот формат недоступна.")
        fmt = fmt.lower()
        ext = {'jpeg': 'jpg', 'jpg': 'jpg', 'png': 'png', 'ico': 'ico', 'webp': 'webp'}.get(fmt, fmt)
        suffix = "" if av.get('overwrite_src') else "_Сжатый"
        out_path = os.path.join(out_dir, f"{sanitized}{suffix}.{ext}")

        # Прогресс подбора качества под лимит: во время прохода n из total процент
        # не превышает n/total*100 (реалистично отражает, что подбор ещё не закончен).
        def _on_pass(n, total):
            cb(int((n - 1) / total * 100), f"Конвертация картинки {n}/{total}")

        cb(0, "Конвертация картинки")

        with Image.open(src_path) as im:
            if ImageOps:
                im = ImageOps.exif_transpose(im)
            had_alpha = im.mode in ('RGBA', 'LA', 'PA', 'La', 'RGBa') or \
                        (im.mode == 'P' and 'transparency' in im.info)
            # JPEG не поддерживает альфу
            if ext == 'jpg':
                im = im.convert('RGB')
            elif ext == 'ico':
                im = im.convert('RGBA')
            elif ext == 'webp':  # WebP умеет прозрачность — сохраняем альфу, если была
                im = im.convert('RGBA') if had_alpha else im.convert('RGB')
            else:  # png
                im = im.convert('RGBA') if im.mode in ('RGBA', 'LA', 'P', 'PA') else im.convert('RGB')

            # Лимит разрешения; для ICO жёсткий потолок 256px
            awidth = av.get('awidth', 0) or 0
            aheight = av.get('aheight', 0) or 0
            if ext == 'ico':
                cap = min(256, adim) if (adim and adim > 0) else 256
                if max(im.width, im.height) > cap:
                    sc = cap / max(im.width, im.height)
                    im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.LANCZOS)
            else:
                tgt = self._target_dims(im.width, im.height, adim, awidth, aheight)
                if tgt:
                    im = im.resize(tgt, Image.LANCZOS)

            limit_kb = int(av.get('limit', 0) or 0) if av.get('limit_on', True) else 0
            if limit_kb <= 0:
                cb(55, "Конвертация картинки")

            if ext == 'ico':
                # Иконки квадратные — добавляем прозрачные поля, если нужно
                side = max(im.width, im.height)
                if im.width != im.height:
                    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
                    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
                    im = canvas
                cand = [16, 24, 32, 48, 64, 128, 256]
                sizes = [(s, s) for s in cand if s <= side] or [(side, side)]
                im.save(out_path, format='ICO', sizes=sizes)
            elif ext == 'jpg':
                if limit_kb > 0:
                    def _save_jpg(q):
                        t = os.path.join(TEMP_DIR, f"jpg_{uuid.uuid4().hex}.jpg")
                        im.save(t, format='JPEG', quality=q, optimize=True)
                        return t
                    chosen = self._search_quality_under_limit(
                        _save_jpg, limit_kb, av.get('fit_passes', 4), q_lo=10, q_hi=95,
                        on_pass=_on_pass)
                    im.save(out_path, format='JPEG', quality=chosen, optimize=True)
                else:
                    im.save(out_path, format='JPEG', quality=92, optimize=True)
            elif ext == 'webp':
                # method=6 обязателен: с method по умолчанию libwebp нестабилен
                # при сохранении RGBA из рабочего потока.
                if limit_kb > 0:
                    def _save_webp(q):
                        t = os.path.join(TEMP_DIR, f"webp_{uuid.uuid4().hex}.webp")
                        im.save(t, format='WEBP', quality=q, method=6)
                        return t
                    chosen = self._search_quality_under_limit(
                        _save_webp, limit_kb, av.get('fit_passes', 4), q_lo=10, q_hi=95,
                        on_pass=_on_pass)
                    im.save(out_path, format='WEBP', quality=chosen, method=6)
                else:
                    im.save(out_path, format='WEBP', quality=90, method=6)
            else:  # png
                im.save(out_path, format='PNG', optimize=True)

        cb(100, "Конвертация картинки")
        try:
            self.update_item_sig.emit(item['iid'], human_size(os.path.getsize(out_path)), "-")
        except Exception:
            pass
        return out_path

    @staticmethod
    def _avif_encode_cmd(src, tmp_out, crf_val, scale_vf, has_alpha, pix_fmt, aspd):
        """Команда ffmpeg для одного кодирования картинки в AVIF (libaom-av1).

        tune=iq («Image Quality») — режим тюнинга libaom именно под неподвижные
        изображения; передаётся через -aom-params, т.к. ffmpeg-обёртка -tune
        знает только psnr/ssim. Проверено: -aom-params валидирует ключи по-
        настоящему (bogus-значение роняет открытие энкодера), так что принятый
        tune=iq — реально применяемый режим, не тихая заглушка.

        has_alpha=True: цвет (yuva420p10le) и извлечённая альфа (gray10le) идут
        двумя av1-потоками, avif-муксер сшивает их в файл с прозрачностью.
        ВАЖНО: split ДО scale — если масштабировать перед split, ffmpeg при
        согласовании форматов роняет альфу (alphaextract «could not choose
        format»). Поэтому делим из yuva420p10le, затем масштабируем каждую
        ветку отдельно (цвет и альфа одного размера).

        Чистая функция (вынесена из process_avif для тестируемости)."""
        aom_common = ["-cpu-used", str(max(0, min(8, aspd))),
                      "-aom-params", "tune=iq",
                      "-tile-columns", "1", "-tile-rows", "1", "-row-mt", "1"]
        if has_alpha:
            if scale_vf:
                fc = (f"[0:v]format=yuva420p10le,split[c][a];"
                      f"[c]{scale_vf}[main];[a]alphaextract,{scale_vf}[alf]")
            else:
                fc = "[0:v]format=yuva420p10le,split[main][a];[a]alphaextract[alf]"
            return [FFMPEG, "-y", "-i", src, "-filter_complex", fc,
                    "-map", "[main]", "-map", "[alf]", "-map_metadata", "-1",
                    "-c:v", "libaom-av1", "-crf", str(crf_val)] + aom_common + \
                   ["-still-picture", "1", "-threads", "0", tmp_out]
        cmd = [FFMPEG, "-y", "-i", src]
        if scale_vf:
            cmd += ["-vf", scale_vf]
        return cmd + ["-frames:v", "1", "-map_metadata", "-1", "-c:v", "libaom-av1",
                      "-crf", str(crf_val)] + aom_common + \
                     ["-pix_fmt", pix_fmt, "-threads", "0", tmp_out]

    def _avif_prepare_input(self, path):
        """Готовит вход для AVIF-конвейера → (path, rot_tmp_file, ширина, высота).

        Авто-поворот по EXIF делается ЗАРАНЕЕ, отдельным .png: ffmpeg сам EXIF-
        ориентацию картинок не применяет, и без этого повёрнутые снимки с
        телефона выходили боком. rot_tmp_file (или None) — временный файл,
        который вызывающий обязан удалить, но только когда ffmpeg уже точно не
        будет читать path. Размеры нужны для расчёта ужимания; если Pillow не
        справился — добираем их ffprobe, а если и это не вышло, вернутся нули
        (вызывающий тогда падает на scale-выражение по макс. стороне)."""
        rot_tmp_file = None
        orig_w, orig_h = 0, 0
        try:
            if Image and ImageOps:
                with Image.open(path) as im:
                    im_t = ImageOps.exif_transpose(im)
                    orig_w, orig_h = im_t.size
                    if im_t is not im:
                        tmp_rot = os.path.join(TEMP_DIR, f"rot_{uuid.uuid4().hex}.png")
                        im_t.save(tmp_rot)
                        path = tmp_rot
                        rot_tmp_file = tmp_rot
        except Exception as e:
            self.log.emit(f"EXIF rotation notice: {e}")

        if not orig_w:
            try:
                p = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=CREATE_NO_WINDOW)
                parts = p.stdout.strip().split('x')
                if len(parts) == 2: orig_w, orig_h = int(parts[0]), int(parts[1])
            except Exception: pass

        return path, rot_tmp_file, orig_w, orig_h

    @staticmethod
    def _avif_downscale_side(orig_w, orig_h, baseline_kb, limit_kb):
        """Макс. сторона для первой попытки даунскейла, когда ни один CQ не влез.

        Оценка от известной точки (размер на CQ=63): считаем, что размер файла
        примерно пропорционален числу пикселей, берём нужную долю площади и
        переводим её в сторону (корень), с запасом 2% вниз. Клампим долю к 1.0
        и дополнительно требуем реального уменьшения (иначе следующая проба
        была бы точной копией предыдущей и проход терялся бы впустую).

        Чистая функция (вынесена из process_avif — арифметику легко покрыть
        тестами, а раньше её нельзя было проверить без запуска ffmpeg)."""
        baseline_bytes = baseline_kb * 1024
        target_bytes = limit_kb * 1024
        orig_pixels = orig_w * orig_h
        approx_ratio = float(target_bytes) / float(baseline_bytes) if baseline_bytes > 0 else 0.5
        approx_ratio = max(0.01, min(1.0, approx_ratio))
        target_pixels = max(1, int(orig_pixels * approx_ratio * 0.98))
        scale_factor = (target_pixels / orig_pixels) ** 0.5
        new_max_side = max(1, int(max(orig_w, orig_h) * scale_factor))
        if new_max_side >= max(orig_w, orig_h):
            new_max_side = max(1, int(max(orig_w, orig_h) * 0.9))
        return new_max_side

    def process_avif(self, item, cb):
        path = item['path']
        base, ext = os.path.splitext(path)

        # Пропускаем файлы, которые сами являются результатом предыдущей конвертации
        if os.path.basename(base).endswith("_Сжатый"):
            self.log.emit(f"Пропущен уже обработанный файл: {os.path.basename(path)}")
            cb(100, "Пропущен")
            return path
        out_dir = self._out_dir_for(path)
        av = self.settings.get('avif', {})
        adim = av.get('adim', 0) or 0
        aspd = av.get('aspd', 0)
        raw_name = os.path.basename(base)
        sanitized = self._sanitize_name(raw_name)
        if sanitized != raw_name:
            self.log.emit(f"Имя переименовано (AI-бренд): «{raw_name}» → «{sanitized}»")
        suffix = "" if av.get('overwrite_src') else "_Сжатый"
        out_name = sanitized + suffix + ".avif"
        out = os.path.join(out_dir, out_name)

        # Выбранный пользователем формат: png/jpg/ico обрабатываем через Pillow
        # (без ffmpeg), avif/webp — основной конвейер ниже.
        img_fmt = (av.get('img_fmt') or 'avif').lower()
        if img_fmt in ('png', 'jpg', 'jpeg', 'ico', 'webp'):
            self.log.emit(f"Формат изображения: {img_fmt.upper()}")
            return self._convert_simple_image(item, path, out_dir, sanitized, adim, av, img_fmt, cb)

        tried_tmp_files = []
        # rot_tmp_file — входной файл после EXIF-поворота, не проба: чистится
        # только когда он точно больше не понадобится как -i для ffmpeg.
        path, rot_tmp_file, orig_w, orig_h = self._avif_prepare_input(path)

        if orig_w * orig_h > 8500000:
            if aspd < 6: aspd = 6

        # Ужимание: макс. сторона + отдельные лимиты ширины/высоты (самый строгий).
        awidth = av.get('awidth', 0) or 0
        aheight = av.get('aheight', 0) or 0
        vf = None
        _tgt = self._target_dims(orig_w, orig_h, adim, awidth, aheight)
        if _tgt:
            vf = f"scale={_tgt[0]}:{_tgt[1]}"
        elif (adim and adim > 0) and not (orig_w and orig_h):
            # Размер исходника не удалось определить — падаем на выражение по макс. стороне.
            vf = f"scale=if(gt(iw\\,ih)\\,{adim}\\,-2):if(gt(ih\\,iw)\\,{adim}\\,-2)"

        has_alpha = self._source_has_alpha(path)
        pix_fmt_avif = self._avif_pix_fmt(has_alpha, av.get('chroma', '420'))

        # Если есть альфа — удаляем старый .avif чтобы не оставалось двух файлов
        if has_alpha and os.path.exists(out):
            try: os.remove(out)
            except Exception: pass

        def _cleanup(files):
            """Удаляет временные файлы; безопасно игнорирует ошибки."""
            for t in list(files):
                try:
                    if os.path.exists(t): os.remove(t)
                except Exception: pass

        def _cleanup_final(files):
            """Как _cleanup, но также удаляет входной rot_*.png — вызывать
            только там, где ffmpeg больше не будет читать path (конец функции)."""
            _cleanup(files)
            if rot_tmp_file:
                try:
                    if os.path.exists(rot_tmp_file): os.remove(rot_tmp_file)
                except Exception: pass

        # Прозрачность теперь идёт в AVIF (а не принудительно в WebP, как раньше):
        # альфу выносим в отдельный gray-поток (alphaextract) и муксим avif-
        # муксером — прямой `-pix_fmt yuva420p` libaom в этой сборке альфу молча
        # теряет. Команду собирает _encode_to при has_alpha=True. WebP оставлен
        # как РЕЗЕРВ — на случай, если конкретная сборка ffmpeg альфу не закодирует.
        def _alpha_webp_fallback():
            self.log.emit("AVIF с альфой не удался → резерв: WebP (RGBA)")
            cb(0, "Конвертация картинки")

            def _on_pass_a(n, total):
                cb(int((n - 1) / total * 100), f"Конвертация картинки {n}/{total}")

            with Image.open(path) as im:
                if ImageOps: im = ImageOps.exif_transpose(im)
                im = im.convert('RGBA')
                _tgt_a = self._target_dims(im.width, im.height, adim,
                                           av.get('awidth', 0) or 0, av.get('aheight', 0) or 0)
                if _tgt_a:
                    im = im.resize(_tgt_a, Image.LANCZOS)

                out_webp = os.path.splitext(out)[0] + ".webp"
                limit_kb_l = int(av.get('limit', 0) or 0)

                if limit_kb_l > 0:
                    def _save_webp_a(q):
                        t = os.path.join(TEMP_DIR, f"wp_{uuid.uuid4().hex}.webp")
                        im.save(t, format="WEBP", quality=q, lossless=False)
                        return t
                    chosen_quality = self._search_quality_under_limit(
                        _save_webp_a, limit_kb_l, av.get('fit_passes', 4), q_lo=10, q_hi=85,
                        on_pass=_on_pass_a)
                    im.save(out_webp, format="WEBP", quality=chosen_quality, lossless=False)
                else:
                    cb(50, "Конвертация картинки")
                    im.save(out_webp, format="WEBP", quality=85, lossless=False)

            cb(100, "Конвертация картинки")
            size_new = os.path.getsize(out_webp)
            self.update_item_sig.emit(item['iid'], human_size(size_new), "-")
            _cleanup_final(tried_tmp_files)
            if os.path.exists(out) and out != out_webp:
                try: os.remove(out)
                except Exception: pass
            return out_webp

        if 'libaom-av1' not in detect_ffmpeg_encoders():
            raise Exception("libaom-av1 не доступен в вашей сборке ffmpeg — AVIF перекодирование настроено работать ТОЛЬКО через libaom (libaom-av1).")
        limit_kb = int(av.get('limit', 0) or 0)

        if has_alpha:
            self.log.emit("Альфа-канал обнаружен → AVIF с прозрачностью (alphaextract, libaom-av1, tune=IQ)")
        else:
            self.log.emit("AVIF: libaom-av1, tune=IQ, 10-бит")

        # Подбор под лимит — несколько проб (подборов). Прогресс масштабируем в
        # долю текущей пробы: во время пробы n из total процент не превышает
        # n/total*100, статус — «Конвертация картинки n/total».
        _limit_on = bool(limit_kb and limit_kb > 0)
        total_passes = max(1, min(8, int(av.get('fit_passes', 4)))) if _limit_on else 1
        pass_state = {'n': 0}

        def _pass_cb(pct, _label=None):
            total = total_passes
            nn = min(pass_state['n'], total) or 1
            overall = int(((nn - 1) + pct / 100.0) / total * 100) if total > 0 else pct
            overall = max(0, min(100, overall))
            if total > 1:
                cb(overall, f"Конвертация картинки {nn}/{total}")
            else:
                cb(overall, "Конвертация картинки")

        def _encode_to(tmp_out, crf_val, vf_override=None):
            pass_state['n'] += 1
            cmd = self._avif_encode_cmd(
                path, tmp_out, crf_val,
                vf_override if vf_override is not None else vf,
                has_alpha, pix_fmt_avif, aspd)
            try:
                orig_size = os.path.getsize(path) if os.path.exists(path) else 1
                est_seconds = max(1, int(orig_size / 400_000))
                self.run_ffmpeg_capture(cmd, est_seconds, _pass_cb, cancel_check=lambda: item["iid"] in self.removed_ids)
                return True, None
            except subprocess.CalledProcessError as e: return False, (e.stderr[:4000] if hasattr(e, 'stderr') else str(e))
            except Exception as e: return False, str(e)

        if not limit_kb or limit_kb <= 0:
            tmp = os.path.join(TEMP_DIR, f"avif_{uuid.uuid4().hex}.avif")
            try:
                ok, err = _encode_to(tmp, int(av.get('cq', 30)))
                if not ok:
                    if os.path.exists(tmp):
                        try: os.remove(tmp)
                        except Exception: pass
                    if has_alpha and Image:
                        return _alpha_webp_fallback()
                    raise Exception(f"AVIF conversion failed: {err}")
                if os.path.exists(out):
                    try: os.remove(out)
                    except Exception: pass
                shutil.move(tmp, out)
                size_new = os.path.getsize(out)
                self.update_item_sig.emit(item['iid'], human_size(size_new), "-")
                return out
            finally:
                if os.path.exists(tmp):
                    try: os.remove(tmp)
                    except Exception: pass
                _cleanup_final(tried_tmp_files)

        best_tmp = None
        best_size_kb = -1
        size63_kb = None  # база для оценки даунскейла, если ни один CQ не влезет

        try:
            iterations = 0
            max_iterations = max(1, min(8, int(av.get('fit_passes', 4))))

            def _probe(crf_val):
                t = os.path.join(TEMP_DIR, f"avif_{uuid.uuid4().hex}_{crf_val}.avif")
                tried_tmp_files.append(t)
                ok, err = _encode_to(t, crf_val)
                if not ok:
                    if os.path.exists(t):
                        try: os.remove(t)
                        except Exception: pass
                    raise Exception(f"AVIF conversion failed: {err}")
                return t, max(1, os.path.getsize(t) // 1024)

            def _discard(t):
                try:
                    if os.path.exists(t):
                        os.remove(t)
                        tried_tmp_files.remove(t)
                except Exception: pass

            def _consider(t, s):
                nonlocal best_tmp, best_size_kb
                if s > best_size_kb:
                    if best_tmp and best_tmp != t and os.path.exists(best_tmp):
                        try: os.remove(best_tmp)
                        except Exception: pass
                    best_tmp, best_size_kb = t, s
                else:
                    _discard(t)

            # Разведка: сразу пробуем оба полюса диапазона — CQ=0 (макс.
            # качество) и CQ=63 (мин.) — вместо удвоения шага от 0. Обрыв
            # размера у AV1 (tune=iq) не всегда у самых низких CQ (для
            # мультяшных/плоских картинок — да, но для детальных фото может
            # лежать и в середине-верху диапазона, см. в памяти
            # avif-fit-passes-binary-search-depth) — раньше удвоение шага
            # (0→1→3→7→…) в таких случаях за отведённый бюджет ни разу не
            # приближалось к реальному обрыву и скатывалось на CQ=63 почти
            # без разбора. Зная оба конца сразу, дальше сужаем вилку
            # log-интерполяцией (log(size) у AV1 примерно линеен по CQ) с
            # небольшим смещением цели НИЖЕ реального лимита — на гладкой
            # кривой (без резкого обрыва) интерполяция к самому лимиту почти
            # всегда чуть промахивается ВЫШЕ него, и проход теряется впустую;
            # смещение забирает этот запас заранее.
            tmp0, size0_kb = _probe(0)
            iterations += 1
            if size0_kb <= limit_kb:
                _consider(tmp0, size0_kb)
            else:
                bad_crf, bad_size = 0, size0_kb
                good_crf, good_size = None, None
                if iterations < max_iterations:
                    t63, s63 = _probe(63)
                    iterations += 1
                    size63_kb = s63
                    if s63 <= limit_kb:
                        good_crf, good_size = 63, s63
                        _consider(t63, s63)
                    else:
                        _discard(t63)
                        bad_crf, bad_size = 63, s63

                if good_crf is not None:
                    _TARGET_BIAS = 0.9
                    while good_crf - bad_crf > 1 and iterations < max_iterations:
                        if bad_size == good_size:
                            mid = (bad_crf + good_crf) // 2
                        else:
                            lt = math.log(max(1, limit_kb * _TARGET_BIAS))
                            lo, hi = math.log(bad_size), math.log(good_size)
                            frac = max(0.0, min(1.0, (lo - lt) / (lo - hi)))
                            mid = int(round(bad_crf + frac * (good_crf - bad_crf)))
                            mid = max(bad_crf + 1, min(good_crf - 1, mid))
                        t, s = _probe(mid)
                        iterations += 1
                        if s <= limit_kb:
                            good_crf, good_size = mid, s
                            _consider(t, s)
                        else:
                            _discard(t)
                            bad_crf, bad_size = mid, s

            if best_tmp and os.path.exists(best_tmp):
                if os.path.exists(out):
                    try: os.remove(out)
                    except Exception: pass
                shutil.move(best_tmp, out)
                size_new = os.path.getsize(out)
                _cleanup_final(tried_tmp_files)
                self.update_item_sig.emit(item['iid'], human_size(size_new), "-")
                return out

            if not orig_w or not orig_h:
                try:
                    if Image:
                        with Image.open(path) as im: orig_w, orig_h = im.size
                except Exception: pass

            if size63_kb is None:
                # Разведка не успела дойти до CQ=63 в рамках бюджета проходов
                # (шаг удвоения обогнал бюджет) — добираем эту пробу отдельно.
                # Если CQ=63 САМ укладывается в лимит — это и есть готовый
                # ответ в полном разрешении: раньше этот результат выбрасывали
                # и всё равно шли на даунскейл (который не был нужен и терял
                # разрешение без причины — approx_ratio клампится к 1.0, но
                # target_pixels всё равно * 0.98 срезает ~1% стороны).
                t63, size63_kb = _probe(63)
                if size63_kb <= limit_kb:
                    _consider(t63, size63_kb)
                else:
                    _discard(t63)

            if best_tmp and os.path.exists(best_tmp):
                if os.path.exists(out):
                    try: os.remove(out)
                    except Exception: pass
                shutil.move(best_tmp, out)
                size_new = os.path.getsize(out)
                _cleanup_final(tried_tmp_files)
                self.update_item_sig.emit(item['iid'], human_size(size_new), "-")
                return out

            if not orig_w or not orig_h:
                _cleanup(tried_tmp_files)
                raise Exception("Не удалось получить размеры изображения для downscale.")

            new_max_side = self._avif_downscale_side(orig_w, orig_h, size63_kb, limit_kb)

            down_attempt = 0
            max_down_attempts = 5
            current_side = new_max_side
            while down_attempt < max_down_attempts:
                vf_down = f"scale=if(gt(iw\\,ih)\\,{current_side}\\,-2):if(gt(ih\\,iw)\\,{current_side}\\,-2)"
                tmp_down = os.path.join(TEMP_DIR, f"avif_{uuid.uuid4().hex}_down{down_attempt}.avif")
                tried_tmp_files.append(tmp_down)
                ok, err = _encode_to(tmp_down, 63, vf_override=vf_down)
                if not ok:
                    if os.path.exists(tmp_down):
                        try: os.remove(tmp_down)
                        except Exception: pass
                    raise Exception(f"AVIF conversion failed during downscale attempt: {err}")
                size_kb = max(1, os.path.getsize(tmp_down) // 1024)
                if size_kb <= limit_kb:
                    if os.path.exists(out):
                        try: os.remove(out)
                        except Exception: pass
                    shutil.move(tmp_down, out)
                    size_new = os.path.getsize(out)
                    _cleanup_final(tried_tmp_files)
                    self.update_item_sig.emit(item['iid'], human_size(size_new), "-")
                    return out
                else:
                    try:
                        if os.path.exists(tmp_down):
                            os.remove(tmp_down)
                            tried_tmp_files.remove(tmp_down)
                    except Exception: pass
                    current_side = max(16, int(current_side * 0.85))
                    down_attempt += 1

            _cleanup(tried_tmp_files)
            raise Exception("Не удалось достичь указанного лимита AVIF.")

        except subprocess.CalledProcessError as e:
            stderr_tail = e.stderr if hasattr(e, 'stderr') else ''
            _cleanup(tried_tmp_files)
            if os.path.exists(out):
                try:
                    os.remove(out)
                    self.log.emit(f"Удалён повреждённый AVIF: {out}")
                except Exception: pass
            if has_alpha and Image:
                return _alpha_webp_fallback()
            if rot_tmp_file:
                try:
                    if os.path.exists(rot_tmp_file): os.remove(rot_tmp_file)
                except Exception: pass
            raise Exception(f"AVIF conversion failed: {stderr_tail[:4000]}")
        except Exception:
            _cleanup(tried_tmp_files)
            if os.path.exists(out):
                try:
                    os.remove(out)
                    self.log.emit(f"Удалён повреждённый AVIF: {out}")
                except Exception: pass
            if has_alpha and Image:
                return _alpha_webp_fallback()
            if rot_tmp_file:
                try:
                    if os.path.exists(rot_tmp_file): os.remove(rot_tmp_file)
                except Exception: pass
            raise

    def _fmt_eta(self, fraction, start):
        """Строка ETA по доле выполнения (0..1) и времени старта."""
        fraction = min(1.0, max(0.0, fraction))
        elapsed = time.time() - start
        if fraction >= 1.0:
            return "00:00:00"
        if elapsed < 1.0 or fraction <= 0.0:
            return "..."
        rem = max(0, elapsed * (1.0 / fraction - 1.0))
        rh = int(rem // 3600); rm = int((rem % 3600) // 60); rs = int(rem % 60)
        return f"{rh:02}:{rm:02}:{rs:02}"

    def _fmt_eta_rate(self, fraction, anchor_t, anchor_frac):
        """ETA по скорости в ОКНЕ [anchor_t, anchor_frac] → сейчас. В отличие от
        _fmt_eta, не привязана к общему старту: при двухпроходном кодировании
        Pass 1 (анализ) проходит почти мгновенно и доводит долю до ~50% за
        секунды; линейная оценка от старта принимала бы это за «всё быстро» и
        затем во время медленного Pass 2 ETA постоянно росла. Переякоривая окно
        на начало текущего прохода, оцениваем остаток по реальной скорости
        именно этого прохода. При anchor_frac=0 и anchor_t=start идентична
        _fmt_eta (обратная совместимость для однопроходных задач)."""
        fraction = min(1.0, max(0.0, fraction))
        if fraction >= 1.0:
            return "00:00:00"
        dt = time.time() - anchor_t
        df = fraction - anchor_frac
        if dt < 1.0 or df <= 1e-6:
            return "..."
        rem = max(0, (1.0 - fraction) * dt / df)
        rh = int(rem // 3600); rm = int((rem % 3600) // 60); rs = int(rem % 60)
        return f"{rh:02}:{rm:02}:{rs:02}"

    def _guess_out_path(self, item, path):
        """Восстанавливает путь к выходному файлу (для кнопки «Открыть»)."""
        try:
            sv2 = self.settings.get('video', {})
            sa2 = self.settings.get('audio', {})
            crf2 = sv2.get('crf', 35); spd2 = sv2.get('speed', 100)
            ve2 = sv2.get('enabled', True)
            base2, ext2 = os.path.splitext(path)
            out_dir2 = self._out_dir_for(path)
            vcodec2 = get_video_codec(path)
            is_vid2 = (vcodec2 is not None)
            out_ext2 = ".mp4" if is_vid2 else ".opus"
            sfx2 = ""
            if is_vid2 and ve2: sfx2 += f"_crf{crf2}_speed{spd2}"
            if sa2.get('norm'): sfx2 += "_norm"
            if sa2.get('fade'): sfx2 += "_fade"
            out_name2 = self._sanitize_name(os.path.basename(base2))
            guessed = os.path.join(out_dir2, out_name2 + sfx2 + out_ext2)
            if os.path.exists(guessed): item['out_path'] = guessed
        except Exception: pass

    def _overwrite_source_if_needed(self, item, out_path):
        """Если включено «Перезаписывать исходник» — удаляет оригинальный файл,
        оставляя только сжатую версию. При совпадении путей (тот же формат)
        файл уже перезаписан на месте — удалять нечего."""
        av = self.settings.get('avif', {})
        if not av.get('overwrite_src'):
            return
        src = item.get('path')
        if not (out_path and src):
            return
        try:
            if (os.path.exists(out_path) and os.path.exists(src)
                    and os.path.abspath(out_path) != os.path.abspath(src)):
                os.remove(src)
                self.log.emit(f"Исходник удалён (перезапись): {os.path.basename(src)}")
        except Exception as e:
            self.log.emit(f"Не удалось удалить исходник: {e}")

    def _total_now(self) -> int:
        """Текущее известное число файлов: уже завершённые + ещё не
        завершённые в очереди. self.queue — живой список MediaTab.items,
        поэтому файлы, доброшенные во время обработки, автоматически
        увеличивают знаменатель прогресса."""
        with self._prog_lock:
            done = self._done_count
        pending = sum(1 for it in list(self.queue) if not it.get('is_done', False))
        return max(1, done + pending)

    def _process_item(self, item, smooth, start, weight=1):
        """Обрабатывает один элемент очереди.
        smooth=True — глобальный прогресс плавно отражает прогресс файла
        (видео/аудио идут по одному). smooth=False — прогресс по факту
        завершения (изображения идут параллельно через QThreadPool).
        weight — вклад в счётчик «занятых потоков ЦП»: видео = все ядра
        (один ffmpeg/SVT-AV1 грузит весь ЦП), изображение = 1."""
        if self.stop_flag:
            return
        iid = item['iid']; path = item['path']
        self.status.emit(iid, "Обработка.", "proc")
        self._inc_active(weight)
        max_frac_seen = [0.0]
        last_label = [None]
        # Окно для ETA по скорости текущего прохода: [время, доля]. По умолчанию
        # совпадает с общим стартом (тогда оценка идентична старой _fmt_eta), но
        # при смене прохода (Pass 1 → Pass 2) переякоривается на текущий момент,
        # чтобы быстрый Pass 1 не занижал оценку и ETA во время Pass 2 не «росла».
        eta_anchor = [start, 0.0]

        def item_prog(pct, pass_label=None, eta_sec=None):
            try:
                if not smooth:
                    # Параллельная обработка изображений: НЕ шлём частые % -сигналы
                    # из множества потоков, но статус («Конвертация картинки N/X»)
                    # обновляем при смене подписи — это редкое событие (раз в проход),
                    # потоки/сигналы Qt безопасны.
                    if pass_label and pass_label != last_label[0]:
                        last_label[0] = pass_label
                        self.status.emit(iid, pass_label, "proc")
                    return
                if pass_label and "Pass 1" in pass_label:
                    display_pct = int(pct * 0.5)
                elif pass_label and "Pass 2" in pass_label:
                    display_pct = int(50 + pct * 0.5)
                else:
                    display_pct = pct
                self.progress.emit(iid, display_pct)
                label_changed = bool(pass_label) and pass_label != last_label[0]
                if label_changed and pct < 100:
                    last_label[0] = pass_label
                    self.status.emit(iid, pass_label, "proc")
                with self._prog_lock:
                    base = self._done_count
                fraction = (base + display_pct / 100.0) / self._total_now()
                fraction = max(min(1.0, fraction), max_frac_seen[0])
                max_frac_seen[0] = fraction
                # Новый проход → переякориваем окно ETA на «здесь и сейчас».
                if label_changed:
                    eta_anchor[0] = time.time()
                    eta_anchor[1] = fraction
                gl_pct = int(min(100, fraction * 100))
                label = pass_label if pass_label else "Processing"
                # Если активный шаг дал реальное ETA (адаптивный калькулятор по
                # кадрам/сложности) — показываем его; иначе старая оценка по доле
                # глобального прогресса (для шагов без покадрового парсинга).
                if eta_sec is not None:
                    eta_str = RealETACalculator.fmt(eta_sec)
                else:
                    eta_str = self._fmt_eta_rate(fraction, eta_anchor[0], eta_anchor[1])
                self.global_progress.emit(gl_pct, f"{label} ETA: {eta_str}")
            except Exception:
                pass

        try:
            out_path = None
            if item.get('type') == 'IMG':
                out_path = self.process_avif(item, item_prog)
                self._overwrite_source_if_needed(item, out_path)
            else:
                self.process_media(item, item_prog)
            item['is_done'] = True
            if out_path:
                item['out_path'] = out_path
            else:
                self._guess_out_path(item, path)
            self.status.emit(iid, "Готово", "done")
            self.progress.emit(iid, 100)
        except Exception as e:
            tb = str(e)
            if "StoppedByUser" in tb:
                self.log.emit(f"Остановка {os.path.basename(path)} выполнена.")
                self.status.emit(iid, "Остановлено", "err")
            else:
                self.log.emit(f"Ошибка {os.path.basename(path)}: {tb}")
                self.status.emit(iid, "Ошибка", "err")
            item['is_done'] = True
        finally:
            self._dec_active(weight)
            with self._prog_lock:
                self._done_count += 1
                done = self._done_count
            total = self._total_now()
            frac = done / total
            self.global_progress.emit(int(min(100, frac * 100)),
                                      f"Готово {done}/{total} ETA: {self._fmt_eta(frac, start)}")

    def run(self):
        start = time.time()
        self._done_count = 0
        self._prog_lock = threading.Lock()
        self._processed_ids = set()   # iid'ы, уже отправленные в работу за этот запуск
        self._logged_cpu_msg = False

        cpu = max(1, cpu_thread_count())

        # Обрабатываем очередь по схеме «продюсер-потребитель»: постоянно
        # заглядываем в живой список self.queue, поэтому файлы, доброшенные во
        # время обработки, тут же уходят в работу. Картинки кодируются параллельно
        # в ОБЩЕМ пуле (cpu потоков) и НЕ блокируют диспетчеризацию через
        # waitForDone — доброшенные картинки сразу занимают свободные потоки
        # (просьба пользователя), не дожидаясь конца текущей пачки.
        while not self.stop_flag:
            pending = [it for it in list(self.queue)
                       if not it.get('is_done', False)
                       and it.get('iid') not in self._processed_ids]
            images = [it for it in pending if it.get('type') == 'IMG']
            others = [it for it in pending if it.get('type') != 'IMG']

            # Видео/аудио идут по одному файлу, но кодировщик SVT-AV1 сам нагружает
            # ВСЕ логические ядра ЦП → счётчик показывает занятые потоки ЦП. Перед
            # видео дожидаемся ранее запущенных картинок, иначе они дрались бы за ЦП.
            if others:
                if (self._img_pool is not None
                        and self._img_pool.activeThreadCount() > 0):
                    self._img_pool.waitForDone()
                self._max_threads = cpu
                if not self._logged_cpu_msg:
                    self.log.emit("Кодирование видео/аудио: SVT-AV1.")
                    self._logged_cpu_msg = True
                for it in others:
                    if self.stop_flag:
                        break
                    self._processed_ids.add(it.get('iid'))
                    self._process_item(it, True, start, weight=cpu)
                continue

            if images:
                # Одиночный кадр CPU не насыщает → шлём картинки в общий пул на cpu
                # потоков. Знаменатель счётчика — всегда ВСЕ логические потоки ЦП
                # машины (cpu), чтобы «занято/всего» не скакало по ходу обработки.
                if self._img_pool is None:
                    self._img_pool = QThreadPool()
                    self._img_pool.setMaxThreadCount(cpu)
                    if cpu > 1:
                        self.log.emit(
                            f"Параллельная обработка изображений: до {cpu} потоков")
                self._max_threads = cpu
                for itm in images:
                    if self.stop_flag:
                        break
                    self._processed_ids.add(itm.get('iid'))
                    self._img_pool.start(_ImgRunnable(self, itm, start))
                # НЕ ждём waitForDone — короткая пауза, чтобы подхватить доброшенные
                # файлы и занять ими свободные потоки, не крутя цикл вхолостую.
                time.sleep(0.08)
                continue

            # Новых задач нет. Если картинки ещё кодируются — ждём и снова
            # перечитываем очередь (вдруг доросли новые); иначе очередь пуста.
            if (self._img_pool is not None
                    and self._img_pool.activeThreadCount() > 0):
                time.sleep(0.1)
                continue
            break

        if self._img_pool is not None:
            self._img_pool.waitForDone()

        self.active_threads.emit(0, 0)
        self.finished_all.emit()
        self.global_progress.emit(100, "Готово")
