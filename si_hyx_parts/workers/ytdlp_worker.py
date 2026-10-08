# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpWorker. Public namespace: workers."""
import workers as _api
from .download_network import is_network_error, network_hint
from .download_process import stop_process
from si_hyx_parts.workers.download_network import terminal_ffmpeg_error
from si_hyx_parts.workers.download_validation import positive_seconds
from si_hyx_parts.workers.download_result import verified_download


class YtdlpWorker(_api.QThread):
    log_sig = _api.pyqtSignal(str)
    progress_sig = _api.pyqtSignal(str, float, str)
    finished_sig = _api.pyqtSignal(str, str, str, str)
    error_sig = _api.pyqtSignal(str, str)
    thumb_sig = _api.pyqtSignal(str, str)

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
        self._download_failure = ""
        self._source_duration = None
        self._expected_audio = None

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
        stop_process(self._proc)

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
        self._download_failure = ""
        self._source_duration = None
        self._expected_audio = True if is_audio_only else None

        if not self.is_running:
            return None, "", "", []
        self._proc = _api.subprocess.Popen(
            cmd, stdout=_api.subprocess.PIPE, stderr=_api.subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=_api.CREATE_NO_WINDOW, bufsize=1, env=_api.subprocess_env())
        if not self.is_running:
            stop_process(self._proc)
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
            if "@@CHECK@@" in line:
                fields = (line.split("@@CHECK@@", 1)[1].split("\t") + ["", "", ""])[:3]
                self._source_duration = positive_seconds(fields[0])
                if fields[2] not in ("", "NA"):
                    self._expected_audio = fields[2] != "none"
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
            failure = terminal_ffmpeg_error(line)
            if failure and not self._download_failure:
                self._download_failure = failure
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

    def run(self):
        iid = self.c.get('iid', '')
        self._iid = iid
        # Старт ВСЕГО задания (а не отдельной попытки): по нему ищем итоговый файл,
        # чтобы найти его, даже если он скачался на ранней попытке, а @@PATH@@ не
        # пришёл (mtime-порог переживает повторы).
        self._job_start_ts = _api.time.time()
        self.progress_sig.emit(iid, 0.0, "Подготовка...")
        try:
            raw_url = self.c.get('url', '')

            # Прямые CDN-ссылки (Instagram fbcdn.net и др.) — по RAW URL, до clean_url
            if _api.is_direct_cdn_video(raw_url):
                out_dir = self.c.get('outdir', '.') or '.'
                self.log_sig.emit("Определена прямая CDN-ссылка, скачиваю без yt-dlp...")
                self.progress_sig.emit(iid, 1.0, "Загрузка CDN...")
                out_path = _api.download_cdn_direct(raw_url, out_dir, log_fn=self.log_sig.emit)
                self.progress_sig.emit(iid, 100.0, "Готово")
                self.finished_sig.emit(iid, "Готово", "", out_path)
                return

            base = _api.ytdlp_base_cmd()
            if not base:
                raise Exception("yt-dlp не найден. Положите yt-dlp.exe в папку bin рядом с программой.")

            url = _api.clean_url(raw_url)
            if url != raw_url: self.log_sig.emit(f"Ссылка очищена: {raw_url} -> {url}")

            out_dir = self.c.get('outdir', '.') or '.'
            is_audio_only = self.c.get('audio_only', False)
            merge = self.c.get('merge') or 'mp4'
            proxy = (self.c.get('proxy') or '').strip()

            # Встроенный плеер Kodik (animego и др. — yt-dlp их не поддерживает):
            # резолвим страницу в прямой m3u8 и качаем уже его.
            kodik = {}
            if not is_audio_only and _api.is_embed_candidate(url):
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
                        kodik = _api.resolve_kodik(url, want_height=want_h, proxy=proxy,
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
            elif _api.is_animego_site(url):
                # Аниме-сайт без полученного Kodik-плеера: yt-dlp его не качает.
                # Не имитируем «скачивание» (раньше падало в generic → Unsupported
                # URL), а сразу честно сообщаем об ошибке.
                raise Exception("Не удалось получить видео с аниме-сайта: Kodik-плеер не отдал ссылку. "
                                "Проверьте выбор серии/озвучки или повторите позже.")

            outtmpl = _api.os.path.join(out_dir, '%(title)s.%(ext)s')

            # download-sections — уникальное имя на каждый отрезок
            section_arg = None
            self._section_dur = None   # длительность отрезка → % прогресса ffmpeg
            start_s = self.c.get('start_s')
            end_s = self.c.get('end_s')
            source_duration = self.c.get('source_duration')
            if source_duration and not start_s and end_s and end_s >= source_duration:
                end_s = None
                self.c['end_s'] = None
            if start_s is not None or end_s is not None:
                s_val = int(start_s) if start_s else 0
                e_val = int(end_s) if (end_s and end_s > s_val) else None
                if (s_val and s_val > 0) or e_val:
                    section_arg = f"*{s_val}-{e_val if e_val else 'inf'}"
                    if e_val:
                        self._section_dur = float(e_val - s_val)
                    s_tag = f"{s_val}s"
                    e_tag = f"{e_val}s" if e_val else "end"
                    outtmpl = _api.os.path.join(out_dir, f'%(title)s [{s_tag}-{e_tag}].%(ext)s')

            # Для Kodik имя из URL-страницы (иначе yt-dlp возьмёт «720.mp4:hls:manifest»).
            # raw_url — это страница АНИМЕ, одна на все серии, поэтому без номера
            # серии в имени все серии тайтла бьются в один файл: первая скачивается,
            # а любая следующая видит «уже скачано» и молча выходит без файла
            # (rc=0, файла нет — выглядело как случайный сбой скачивания).
            if kodik:
                from urllib.parse import urlparse as _urlparse
                slug = _api.os.path.splitext(_api.os.path.basename(_urlparse(raw_url).path))[0] or "video"
                ep_tag = f" - {ep} серия" if ep else ""
                outtmpl = _api.os.path.join(out_dir, f"{slug}{ep_tag} [{kodik['height']}p].%(ext)s")

            cmd = base + [
                # Вывод в PIPE читаем как UTF-8; без этого yt-dlp.exe пишет в
                # cp1251 и путь из @@PATH@@ приходит кракозябрами.
                "--encoding", "utf-8",
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
                # ВАЖНО: --print НЕЯВНО включает --quiet. Из-за этого yt-dlp молчал
                # обо всём, кроме наших @@-строк: ни «[youtube] Extracting URL», ни
                # «[download] Destination», ни WARNING, ни «has already been
                # downloaded». Когда загрузка срывалась без ошибки (rc=0, но файла
                # нет), в лог уходило «вывод пуст — процесс оборвался без единой
                # строки лога» — причина терялась целиком. --no-quiet возвращает
                # обычный вывод; строки прогресса им НЕ дублируются (их формат
                # задан --progress-template).
                "--no-quiet",
                "--print", "before_dl:@@META@@%(thumbnail)s\t%(width)s\t%(height)s\t%(abr)s",
                "--print", "before_dl:@@CHECK@@%(duration)s\t%(vcodec)s\t%(acodec)s",
                "--print", "after_move:@@PATH@@%(filepath)s",
            ]
            if self.c.get('overwrite'):
                cmd += ["--force-overwrites"]

            # Указываем yt-dlp на наш ffmpeg (bundled в bin/) — иначе отдельный
            # процесс yt-dlp не найдёт ffmpeg для склейки/извлечения аудио.
            # ВАЖНО: для нарезки отрезка (--download-sections) подсовываем ОТДЕЛЬНЫЙ
            # ffmpeg 7.x (bin/ffmpeg7) — основной 8.x ломает нарезку (см. FFMPEG7_DIR
            # в config.py и yt-dlp #16546: битый/audio-only отрезок). Для обычных
            # загрузок остаётся основной ffmpeg.
            ffloc = None
            if section_arg and _api.FFMPEG7_DIR:
                ffloc = _api.FFMPEG7_DIR
            elif _api.os.path.isabs(_api.FFMPEG) and _api.os.path.isfile(_api.FFMPEG):
                ffloc = _api.os.path.dirname(_api.FFMPEG)
            if ffloc:
                cmd += ["--ffmpeg-location", ffloc]
                if section_arg and _api.FFMPEG7_DIR:
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
            _is_tiktok = _api.host_matches(url, 'tiktok.com')
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

            if _api.host_matches(url, 'youtube.com', 'youtu.be'):
                self.log_sig.emit("YouTube: клиенты default + web_safari (n-challenge через Deno)...")
                if not _api.deno_available():
                    self.log_sig.emit("ВНИМАНИЕ: Deno не найден — YouTube может отдать только 360p. Положите deno.exe в bin.")
                cmd += ["--extractor-args", "youtube:player_client=default,web_safari"]

            if _api.host_matches(url, 'bilibili.com', 'b23.tv'):
                self.log_sig.emit("BiliBili обнаружен: добавляю Referer + User-Agent (фикс HTTP 412 Precondition Failed).")
                cmd += ["--referer", "https://www.bilibili.com/", "--user-agent", _api.USER_AGENT]

            # Куки: domain-specific имеет приоритет над общим UI-полем
            ui_cookie = self.c.get('cookie_path', '').strip()
            c_path = _api.get_cookies_path(url)
            chosen_cookie = None
            if _api.os.path.exists(c_path) and c_path != _api.COOKIE_PATHS['default']:
                chosen_cookie = c_path
                self.log_sig.emit(f"OK: Cookies для {url[:40]}... -> {c_path}")
            elif ui_cookie and _api.os.path.exists(ui_cookie) and _api._cookie_matches_domain(ui_cookie, url):
                chosen_cookie = ui_cookie
                self.log_sig.emit(f"OK: Cookies из настроек: {ui_cookie}")
            elif ui_cookie and _api.os.path.exists(ui_cookie) and not _api._cookie_matches_domain(ui_cookie, url):
                self.log_sig.emit(f"Предупреждение: куки из настроек не подходят для {url[:40]} (пропущены)")
                if _api.os.path.exists(_api.COOKIE_PATHS['default']):
                    chosen_cookie = _api.COOKIE_PATHS['default']
                    self.log_sig.emit(f"OK: Используем общие cookies: {_api.COOKIE_PATHS['default']}")
            elif _api.os.path.exists(_api.COOKIE_PATHS['default']):
                chosen_cookie = _api.COOKIE_PATHS['default']
                self.log_sig.emit(f"OK: Используем общие cookies: {_api.COOKIE_PATHS['default']}")
            if chosen_cookie:
                cmd += ["--cookies", chosen_cookie]

            if self.c.get('sub_lang') and self.c['sub_lang'] != 'Выкл':
                cmd += ["--write-subs", "--sub-langs",
                        "all" if self.c['sub_lang'] == 'all' else self.c['sub_lang']]

            if section_arg:
                cmd += ["--download-sections", section_arg]
                # _i applies to BOTH remote inputs. EOF reconnection is deliberately
                # omitted: a normally completed finite video must stop at EOF.
                cmd += ["--downloader-args", "ffmpeg_i:-reconnect 1 -reconnect_streamed 1 "
                        "-reconnect_on_network_error 1 -reconnect_delay_max 5 "
                        "-reconnect_on_http_error 408,429,500,502,503,504 -rw_timeout 30000000",
                        "--downloader-args", "ffmpeg_o:-xerror"]
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
                if rc not in (0, None):
                    return ""
                if out_fullpath and _api.os.path.exists(out_fullpath):
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

            out_fullpath, clean_res_str = verified_download(
                self, cmd, iid, is_audio_only,
                (rc, out_fullpath, clean_res_str, tail))

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
            final = _api.os.path.basename(final_path)
            prefix = (final.split(" [")[0] or final)[:24]
            if not prefix:
                return
            for name in _api.os.listdir(out_dir):
                if name == final:
                    continue
                low = name.lower()
                is_partial = (low.endswith(".part") or low.endswith(".ytdl")
                              or ".fdash" in low or ".fhls" in low)
                if is_partial and name.startswith(prefix):
                    try: _api.os.remove(_api.os.path.join(out_dir, name))
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
                try: msg = f"{speed} (Скачано: {_api.human_size(int(downloaded))})"
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
            self._last_real_progress = _api.time.time()
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
                _api.os.path.join(out_dir, fn) for fn in _api.os.listdir(out_dir)
                if _api.os.path.isfile(_api.os.path.join(out_dir, fn))
                and fn.lower().endswith(self._MEDIA_EXTS)
                and _api.os.path.getmtime(_api.os.path.join(out_dir, fn)) >= floor
            ]
            if cands:
                return max(cands, key=_api.os.path.getmtime)
        except Exception:
            pass
        return ""

    def _emit_hints(self, err_msg):
        low = err_msg.lower()
        if is_network_error(err_msg):
            self.log_sig.emit("СОВЕТ: Сетевое соединение оборвалось или сервер не ответил.")
            self.log_sig.emit(network_hint())
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
            if _api.host_matches(u, "tiktok.com"):
                self.log_sig.emit("СОВЕТ: 403 на TikTok. Удалите/переименуйте cookies_tiktok.txt.")
            elif _api.host_matches(u, "fbcdn.net", "instagram.com", "cdninstagram.com"):
                self.log_sig.emit("СОВЕТ: 403 на Instagram CDN. Ссылка устарела — откройте видео заново.")
            else:
                self.log_sig.emit("СОВЕТ: 403 Forbidden. Возможно, нужны куки или ссылка устарела.")
        elif "412" in err_msg or "Precondition Failed" in err_msg:
            u = self.c.get("url", "")
            if _api.host_matches(u, "bilibili.com", "b23.tv"):
                self.log_sig.emit("СОВЕТ: 412 на BiliBili — их анти-бот (риск-контроль) режет playurl для гостей.")
                self.log_sig.emit("  Нужны cookies залогиненного аккаунта (SESSDATA). Войдите на bilibili.com в браузере, "
                                  "экспортируйте cookies.txt и укажите его в поле «Cookies» (или положите cookies_bilibili.txt в папку настроек).")
            else:
                self.log_sig.emit("СОВЕТ: 412 Precondition Failed — сайт отклонил запрос. Часто помогают cookies залогиненного аккаунта.")


YtdlpWorker.__module__ = _api.__name__
_api.YtdlpWorker = YtdlpWorker
