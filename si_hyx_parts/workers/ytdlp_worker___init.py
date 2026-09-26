# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpWorker: __init__. Public namespace: workers."""
import workers as _api


def __init__(self, config):
    super(_api.YtdlpWorker, self).__init__()
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
        self._dl_phase_ts = _api.time.time()

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
        _api.time.sleep(1.0)
        # Перепроверяем после сна: процесс мог завершиться (ошибкой/успехом),
        # могла стартовать новая попытка (proc != self._proc) или прийти стоп.
        if (not self.is_running or proc.poll() is not None
                or proc is not self._proc):
            return
        if not self._download_phase or not self._dl_phase_ts:
            continue
        now = _api.time.time()
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
    end = _api.time.time() + max(0.0, seconds)
    while self.is_running and _api.time.time() < end:
        _api.time.sleep(0.1)

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
    tail = _api.deque(maxlen=40)

    self._dl_start_ts = _api.time.time()
    self._last_real_progress = _api.time.time()
    self._last_pct = 0.0  # новая попытка качает с нуля — не тянуть % с прошлой
    # Новая попытка снова начинается с извлечения — сбрасываем фазу загрузки.
    self._download_phase = False
    self._dl_phase_ts = None

    self._proc = _api.subprocess.Popen(
        cmd, stdout=_api.subprocess.PIPE, stderr=_api.subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=_api.CREATE_NO_WINDOW, bufsize=1, env=_api.subprocess_env())
    _api.threading.Thread(target=self._watchdog, args=(self._proc,), daemon=True).start()

    for raw in self._iter_stream_lines(self._proc.stdout):
        if not self.is_running:
            break
        line = _api.clean_ansi(raw.rstrip("\r\n"))
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
            m = _api.re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
            if m:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                pct = max(0.0, min(99.9, t / self._section_dur * 100.0))
                sp = _api.re.search(r"speed=\s*([\d.]+x)", line)
                self._enter_download_phase()
                self._last_real_progress = _api.time.time()
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
            m = _api.re.search(r"\[download\]\s+(.+?)\s+has already been downloaded", line)
            if m and _api.os.path.exists(m.group(1).strip()):
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
    m = _api.re.search(r"height<=?(\d+)", fmt or "")
    return int(m.group(1)) if m else 720
