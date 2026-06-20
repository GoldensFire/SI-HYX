# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# workers.py — фоновые потоки: загрузка (yt-dlp) и обработка (ffmpeg)
from config import *
from utils import *
from utils import _cookie_matches_domain, _RE_DIGITS


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
        # Новая попытка снова начинается с извлечения — сбрасываем фазу загрузки.
        self._download_phase = False
        self._dl_phase_ts = None

        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW, bufsize=1, env=subprocess_env())
        threading.Thread(target=self._watchdog, args=(self._proc,), daemon=True).start()

        for raw in self._proc.stdout:
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
            force_kf = False if (is_audio_only or not self.c.get('force_kf', True)) else True
            merge = self.c.get('merge') or 'mp4'
            proxy = (self.c.get('proxy') or '').strip()

            # Встроенный плеер Kodik (animego и др. — yt-dlp их не поддерживает):
            # резолвим страницу в прямой m3u8 и качаем уже его.
            kodik = {}
            if not is_audio_only and is_embed_candidate(url):
                try:
                    want_h = self._height_from_fmt(self.c.get('fmt', ''))
                    ep = self.c.get('kodik_episode')
                    ep = int(ep) if ep else None
                    kodik = resolve_kodik(url, want_height=want_h, proxy=proxy,
                                          episode=ep,
                                          translation=self.c.get('kodik_translation', ''),
                                          log_fn=self.log_sig.emit)
                except Exception as e:
                    self.log_sig.emit(f"Kodik resolve error: {e}")
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
            start_s = self.c.get('start_s')
            end_s = self.c.get('end_s')
            if start_s is not None or end_s is not None:
                s_val = int(start_s) if start_s else 0
                e_val = int(end_s) if (end_s and end_s > s_val) else None
                if (s_val and s_val > 0) or e_val:
                    section_arg = f"*{s_val}-{e_val if e_val else 'inf'}"
                    s_tag = f"{s_val}s"
                    e_tag = f"{e_val}s" if e_val else "end"
                    outtmpl = os.path.join(out_dir, f'%(title)s [{s_tag}-{e_tag}].%(ext)s')

            # Для Kodik имя из URL-страницы (иначе yt-dlp возьмёт «720.mp4:hls:manifest»)
            if kodik:
                from urllib.parse import urlparse as _urlparse
                slug = os.path.splitext(os.path.basename(_urlparse(raw_url).path))[0] or "video"
                outtmpl = os.path.join(out_dir, f"{slug} [{kodik['height']}p].%(ext)s")

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
            if os.path.isabs(FFMPEG) and os.path.isfile(FFMPEG):
                cmd += ["--ffmpeg-location", os.path.dirname(FFMPEG)]

            # Прокси (если задан в настройках вкладки загрузок)
            if proxy:
                cmd += ["--proxy", proxy]

            # Kodik m3u8 требует Referer на домен плеера
            if kodik and kodik.get('referer'):
                cmd += ["--add-header", f"Referer:{kodik['referer']}"]

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
                if force_kf:
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
                raise Exception("yt-dlp завершил работу, но файл не найден (ошибка скачивания)")
            out_fullpath = final_path

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

    def __init__(self, queue_ref, settings):
        super().__init__()
        self.queue = queue_ref
        self.settings = settings
        self.stop_flag = False
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
    def measure_loudness(self, path): return measure_loudness(path)

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
    def _detect_crop(path: str, dur: float = 0.0):
        """Определяет рамку видео без чёрных полос через ffmpeg cropdetect.
        Возвращает строку 'w:h:x:y' для фильтра crop или None, если полос нет
        (детектированная рамка совпадает с исходным кадром).

        Пропускаем первые ~10% (интро/логотипы часто на чёрном фоне дают ложный
        full-frame), анализируем ограниченный отрезок — детект быстрый и не читает
        весь файл. round=2 — чётные размеры (требование SVT-AV1)."""
        try:
            ss = ["-ss", f"{dur * 0.1:.2f}"] if dur and dur > 12 else []
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
    def _choose_pix_fmt(has_alpha: bool, ten_bit: bool = False) -> str:
        """Возвращает pix_fmt с учётом альфа-канала."""
        if has_alpha:
            return "yuva420p10le" if ten_bit else "yuva420p"
        return "yuv420p10le" if ten_bit else "yuv420p"

    def run_ffmpeg_capture(self, cmd, total_est_sec, percent_callback, label=None):
        si = subprocess.STARTUPINFO() if IS_WIN else None
        if IS_WIN and si is not None: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        buf = deque(maxlen=8000)
        try:
            p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW | getattr(self, '_priority_flag', 0), startupinfo=si)
        except Exception as e:
            raise Exception(f"Не удалось запустить ffmpeg: {e}")
        start = time.time()
        last_pct = -1
        try:
            while True:
                if self.stop_flag:
                    try: p.kill()
                    except Exception: pass
                    try:
                        tail = p.stderr.read() or ""
                        for L in tail.splitlines(): buf.append(L + "\n")
                    except Exception: pass
                    raise Exception("StoppedByUser")
                line = p.stderr.readline()
                if line: buf.append(line)
                elapsed = time.time() - start
                pct = int(min(99, (elapsed / total_est_sec) * 99)) if total_est_sec and total_est_sec > 0 else int(min(98, elapsed * 15))
                # Шлём колбэк только при смене целого процента — не флудим сигналами
                if pct != last_pct:
                    last_pct = pct
                    try:
                        percent_callback(pct, label)
                    except Exception:
                        try:
                            percent_callback(pct)
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

        vcodec = get_video_codec(path)
        is_video = (vcodec is not None)

        out_ext = ".mp4" if is_video else ".opus"
        out_name = os.path.basename(base)
        sanitized = self._sanitize_name(out_name)
        if sanitized != out_name:
            self.log.emit(f"Имя переименовано (AI-бренд): «{out_name}» → «{sanitized}»")
            out_name = sanitized

        suffix = ""
        if is_video and video_enabled: suffix += f"_crf{crf}_speed{speed_percent}"
        if sa.get('norm'): suffix += "_norm"
        if sa.get('fade'): suffix += "_fade"
        out_name = out_name + suffix + out_ext
        out = os.path.join(out_dir, out_name)

        sel_br = self.settings.get('audio', {}).get('bitrate', '128')
        audio_bitrate = self.get_target_bitrate_str(path, sel_br)

        before_lufs = None
        try: before_lufs = self.measure_loudness(path)
        except Exception: pass

        if is_video and video_enabled and not self.svt_available:
            raise Exception("libsvtav1 не доступен в вашей сборке ffmpeg — скрипт настроен работать ТОЛЬКО с svt (libsvtav1).")

        audio_filters = []
        if sa.get('norm'):
            tgt_i = float(sa.get('tgt', -20.0))
            lra = float(sa.get('lra', 20.0))
            tp = float(sa.get('tp', -1.5))
            audio_filters.append(f"loudnorm=I={tgt_i}:LRA={lra}:TP={tp}")
        if sa.get('fade_in'):
            fade_in_d = sa.get('fade_in_d', 1.0)
            audio_filters.append(f"afade=t=in:st=0:d={fade_in_d}")
        if sa.get('fade'):
            fade_d = sa.get('fade_d', 1.0)
            item_dur = item.get('dur') or 0.0
            if item_dur <= 0.0:
                # dur мог не считаться при добавлении (кириллика в пути, ffprobe упал) —
                # читаем прямо сейчас, когда файл точно доступен
                try:
                    item_dur, *_ = get_media_info(path)
                except Exception:
                    item_dur = 0.0
            audio_filters.append(f"afade=t=out:st={max(0.0, item_dur - fade_d):.3f}:d={fade_d}")
        if sa.get('deg'):
            audio_filters.append(f"lowpass=f={sa.get('lp', 3000)}")
            audio_filters.append(f"highpass=f={sa.get('hp', 200)}")
            hz = int(sa.get('hz', 44100))
            if sa.get('u8'):
                audio_filters.append(f"aformat=sample_fmts=u8:sample_rates={hz}")
            gain_db = float(sa.get('deg_gain_db', 0.0))
            if abs(gain_db) > 0.01:
                audio_filters.append(f"volume={gain_db}dB")
        
        if abs(speed_factor - 1.0) > 0.01:
            audio_filters.extend(_build_atempo_chain(speed_factor))

        temp_files = []
        attempted_out = out

        try:
            current_input = path
            audio_codec = "libopus"  # opus в mp4
            # libopus отвергает «боковые»/нестандартные раскладки каналов
            # (например 5.1(side) у AC3-дорожек) с mapping family по умолчанию →
            # "Invalid channel layout … (exit -22)". Нормализуем раскладку к
            # стандартной (5.1(side)→5.1) фильтром aformat перед кодером: на
            # stereo/mono это no-op, downmix не делается. Применяем на КАЖДОМ
            # кодировании в libopus (в т.ч. когда других аудиофильтров нет).
            opus_layout_fix = "aformat=channel_layouts=mono|stereo|3.0|4.0|quad|5.0|5.1|6.1|7.1"
            def _opus_af(filters):
                return ",".join(list(filters) + [opus_layout_fix])
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
            dur_cap = (["-t", f"{float(src_dur_cap):.3f}"]
                       if (normal_speed and audio_filters and src_dur_cap > 0) else [])

            if step1_needed:
                # Промежуточный контейнер для видео — Matroska: он принимает копию
                # ЛЮБОГО видеокодека + libopus. .mp4 же отвергает копию ряда
                # кодеков/потоков (легаси-видео, обложки) → "Invalid argument"
                # (exit -22). Финал всё равно делает step2 (AV1→mp4) или ремукс.
                temp_ext = ".mkv" if is_video else ".opus"
                temp_intermediate = os.path.join(TEMP_DIR, f"inter_{uuid.uuid4().hex}{temp_ext}")
                temp_files.append(temp_intermediate)

                # Берём только НАСТОЯЩЕЕ видео+аудио (0:V? исключает обложки/
                # attached_pic, 0:a? — аудио). Субтитры/вложения/данные не маппим:
                # их кодеки несовместимы с контейнером → иначе ffmpeg падает.
                cmd_step1 = [FFMPEG, "-y", "-i", current_input, "-map", "0:V?", "-map", "0:a?"]
                cmd_step1 += ["-af", _opus_af(audio_filters)]
                cmd_step1 += ["-c:a", audio_codec, "-b:a", audio_bitrate]
                if is_video: cmd_step1 += ["-c:v", "copy"]
                else: cmd_step1 += ["-vn"]
                cmd_step1 += [temp_intermediate]

                orig_size = os.path.getsize(path) if os.path.exists(path) else 1
                self.run_ffmpeg_capture(cmd_step1, max(1, int(orig_size/1000000)), cb, label="Pass 1 (Audio)")
                current_input = temp_intermediate

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
                if single_pass_video and audio_filters:
                    af_chain = list(audio_filters)
                    if abs(speed_factor - 1.0) <= 0.01:
                        # Выравниваем длину аудио к длине входной дорожки — убирает
                        # «хвост» от latency loudnorm + добивки opus-кадров (иначе
                        # audio.end > video.end и контейнер растёт: 12.55→12.62).
                        # ВАЖНО: завязка только на скорость, НЕ на keep_timing/fps —
                        # тримминг хвоста нужен и когда сменили fps. При смене скорости
                        # НЕ трогаем: длину задаёт atempo, async лишь помешал бы.
                        af_chain.append("aresample=async=1")
                    af_chain.append(opus_layout_fix)
                    step2_audio = ["-af", ",".join(af_chain),
                                   "-c:a", audio_codec, "-b:a", audio_bitrate]
                else:
                    step2_audio = ["-c:a", "copy"]
                timing_args = ["-fps_mode", "passthrough"] if keep_timing else []
                # Только видео+аудио (см. step1): субтитры/вложения не маппим,
                # чтобы не падать на контейнерах, которые их не поддерживают.
                cmd_step2 = [FFMPEG, "-y", "-i", current_input, "-map", "0:V?", "-map", "0:a?"] + timing_args

                res_sel = sv.get('res', 'Исходное') or 'Исходное'
                vf_list = []

                # Обрезка чёрных полос — ПЕРВЫМ фильтром (до scale/fade), чтобы
                # масштаб и фейды считались уже от обрезанного кадра.
                if sv.get('crop_black'):
                    crop = self._detect_crop(current_input, item.get('dur') or 0.0)
                    if crop:
                        vf_list.append(f"crop={crop}")
                        self.log.emit(f"✂ Обрезка чёрных полос: crop={crop}")
                    else:
                        self.log.emit("✂ Чёрные полосы не обнаружены — обрезка пропущена")

                if abs(speed_factor - 1.0) > 0.01:
                    vf_list.append(f"setpts={1.0/speed_factor}*PTS")

                if isinstance(res_sel, str) and res_sel != "Исходное":
                    if 'x' in res_sel:
                        try:
                            w_str, h_str = res_sel.split('x', 1)
                            w = int(w_str); h = int(h_str)
                            vf_list.append(
                                f"scale=w='min(iw,{w})':h='min(ih,{h})'"
                                f":force_original_aspect_ratio=decrease"
                                f":force_divisible_by=2"   # SVT-AV1 требует чётные размеры
                            )
                        except Exception:
                            vf_list.append(f"scale={res_sel}:force_divisible_by=2")
                    else: vf_list.append(f"scale={res_sel}:force_divisible_by=2")

                # Видео fade in / out (через чёрный). Тайминги — в выходной
                # шкале времени (с учётом изменения скорости).
                if sv.get('vfade_in'):
                    vfi = float(sv.get('vfade_in_d', 1.0))
                    if vfi > 0:
                        vf_list.append(f"fade=t=in:st=0:d={vfi}")
                if sv.get('vfade_out'):
                    vfo = float(sv.get('vfade_out_d', 1.0))
                    if vfo > 0:
                        src_dur = item.get('dur') or 0.0
                        if src_dur <= 0.0:
                            try: src_dur, *_ = get_media_info(current_input)
                            except Exception: src_dur = 0.0
                        out_dur = (src_dur / speed_factor) if speed_factor else src_dur
                        # Фейд должен ЗАВЕРШИТЬСЯ до последнего кадра, иначе кадр
                        # окажется на ~96% затемнения, а не на 100%. Сдвигаем фейд
                        # на запас (≥1.5 кадра) — фильтр держит чёрный после конца.
                        try: _fps = get_fps_float(current_input) or 25.0
                        except Exception: _fps = 25.0
                        if _fps <= 0: _fps = 25.0
                        margin = max(0.08, 1.5 / _fps)
                        st = max(0.0, out_dur - vfo - margin)
                        vf_list.append(f"fade=t=out:st={st:.3f}:d={vfo}")

                fps_sel = sv.get('fps', 'Исходный') or 'Исходный'
                if fps_sel == "Исходный (max 30)":
                    try:
                        src_fps = get_fps_float(current_input)
                        if src_fps > 30.5: cmd_step2 += ["-r", "30"]
                    except Exception: pass
                elif isinstance(fps_sel, str) and fps_sel != "Исходный":
                    try:
                        float(fps_sel)
                        cmd_step2 += ["-r", fps_sel]
                    except Exception: pass

                preset_mode = sv.get('preset_mode', 'std')
                is_dark_scenes = (preset_mode == "dark")

                if is_dark_scenes:
                    # Профиль «Тёмные сцены»: 10-бит, tune=ssim, одно-проходный CRF AV1.
                    # SVT-AV1 НЕ поддерживает multi-pass в режиме CRF
                    # ("CRF does not support multi-pass. Use single pass."),
                    # поэтому используем один проход. Для CRF (постоянное качество)
                    # 2-pass всё равно не даёт выигрыша.
                    has_alpha = self._source_has_alpha(current_input)
                    pix_fmt = self._choose_pix_fmt(has_alpha, ten_bit=True)
                    svt_params = "tune=2"   # tune=ssim в SVT-AV1
                    preset_val = str(max(0, min(13, sv.get('pre', 0))))
                    est = max(1, int(os.path.getsize(current_input)/400000)) if os.path.exists(current_input) else 10

                    cmd_dark = [
                        FFMPEG, "-y", "-i", current_input, "-map", "0:V?", "-map", "0:a?",
                    ] + timing_args + [
                        "-c:v", "libsvtav1", "-crf", str(crf), "-preset", preset_val,
                        "-svtav1-params", svt_params,
                        "-pix_fmt", pix_fmt,
                    ]
                    if vf_list:
                        cmd_dark += ["-vf", ",".join(vf_list)]
                    cmd_dark += ["-threads", "0"] + step2_audio + dur_cap + [attempted_out]

                    self.log.emit("🌑 Тёмные сцены: кодирование (AV1 10-бит, CRF)...")
                    self.run_ffmpeg_capture(cmd_dark, est, cb, label="AV1 кодирование (тёмные сцены)")

                else:
                    # Стандартный профиль
                    has_alpha = self._source_has_alpha(current_input)
                    pix_fmt = self._choose_pix_fmt(has_alpha)

                    if has_alpha and 'libvpx-vp9' in detect_ffmpeg_encoders():
                        # libsvtav1 не поддерживает yuva420p → переключаемся на VP9+WebM
                        self.log.emit("Альфа-канал → выход: VP9 WebM (SVT-AV1 alpha не поддерживает)")
                        attempted_out = os.path.splitext(attempted_out)[0] + ".webm"
                        out = attempted_out
                        cmd_step2 += ["-c:v", "libvpx-vp9",
                                      "-crf", str(crf), "-b:v", "0",
                                      "-pix_fmt", pix_fmt]
                    elif has_alpha:
                        self.log.emit("⚠ libvpx-vp9 недоступен — альфа будет потеряна (используется SVT-AV1)")
                        cmd_step2 += ["-c:v", "libsvtav1",
                                      "-crf", str(crf), "-preset", str(max(0, min(8, sv.get('pre', 8)))),
                                      "-pix_fmt", "yuv420p"]
                    else:
                        cmd_step2 += ["-c:v", "libsvtav1",
                                      "-crf", str(crf), "-preset", str(max(0, min(8, sv.get('pre', 8)))),
                                      "-pix_fmt", pix_fmt]

                    if vf_list: cmd_step2 += ["-vf", ",".join(vf_list)]
                    cmd_step2 += ["-threads", "0"] + step2_audio + dur_cap + [attempted_out]

                    est = max(1, int(os.path.getsize(current_input)/400000)) if os.path.exists(current_input) else 10
                    self.run_ffmpeg_capture(cmd_step2, est, cb, label="Pass 2 (Video)")

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
                            cb, label=None)
                else:
                    # Один прямой проход (видео-копия с аудиофильтрами или аудио-онли).
                    # Для видео-копии (single_pass_copy): passthrough сохраняет VFR-
                    # тайминг при `-c:v copy`, а aresample=async=1 убирает хвост
                    # loudnorm/опус-сдвиг — итог точно равен длине источника.
                    if is_video and normal_speed and audio_filters:
                        af_direct = ",".join(list(audio_filters)
                                             + ["aresample=async=1", opus_layout_fix])
                    else:
                        af_direct = _opus_af(audio_filters)
                    cmd_direct = [FFMPEG, "-y", "-i", path, "-map", "0:V?", "-map", "0:a?"]
                    if is_video and keep_timing:
                        cmd_direct += ["-fps_mode", "passthrough"]
                    cmd_direct += ["-af", af_direct]
                    cmd_direct += ["-c:a", audio_codec, "-b:a", audio_bitrate]
                    if is_video: cmd_direct += ["-c:v", "copy"]
                    else: cmd_direct += ["-vn"]
                    # Видео-КОПИЯ + аудиофильтры: loudnorm/opus добавляют «хвост»,
                    # из-за которого итог длиннее источника. dur_cap (-t = длине
                    # источника) обрезает лишний аудиохвост — см. определение выше.
                    cmd_direct += dur_cap
                    cmd_direct += [out]
                    self.run_ffmpeg_capture(cmd_direct, max(1, int(os.path.getsize(path)/1000000)), cb, label=None)

            if os.path.exists(out):
                # «После» LUFS: в одно-проходном режиме Pass-1 (где раньше мерили)
                # пропущен — меряем по готовому файлу.
                if (single_pass_video or single_pass_copy) and sa.get('norm'):
                    try:
                        after_norm = self.measure_loudness(out)
                        self.update_lufs_sig.emit(item['iid'], before_lufs, after_norm)
                    except Exception: pass
                size_new = os.path.getsize(out)
                dur_new, br_str, _, a_br, a_codec = get_media_info(out)
                self.update_item_sig.emit(item['iid'], human_size(size_new),
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
            cap = adim if (adim and adim > 0) else None
            if ext == 'ico':
                cap = min(256, cap) if cap else 256
            if cap and max(im.width, im.height) > cap:
                sc = cap / max(im.width, im.height)
                im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.LANCZOS)

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

        orig_w, orig_h = 0, 0
        tried_tmp_files = []

        # Фикс: Авто-поворот изображения согласно EXIF-метаданным перед отправкой в FFmpeg
        try:
            if Image and ImageOps:
                with Image.open(path) as im:
                    im_t = ImageOps.exif_transpose(im)
                    orig_w, orig_h = im_t.size
                    if im_t is not im:
                        tmp_rot = os.path.join(TEMP_DIR, f"rot_{uuid.uuid4().hex}.png")
                        im_t.save(tmp_rot)
                        path = tmp_rot
                        tried_tmp_files.append(tmp_rot)
        except Exception as e:
            self.log.emit(f"EXIF rotation notice: {e}")
            
        if not orig_w:
            try:
                p = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=CREATE_NO_WINDOW)
                parts = p.stdout.strip().split('x')
                if len(parts) == 2: orig_w, orig_h = int(parts[0]), int(parts[1])
            except Exception: pass

        if orig_w * orig_h > 8500000:
            if aspd < 6: aspd = 6

        vf = None
        if adim and adim > 0: vf = f"scale=if(gt(iw\\,ih)\\,{adim}\\,-2):if(gt(ih\\,iw)\\,{adim}\\,-2)"

        has_alpha = self._source_has_alpha(path)
        pix_fmt_avif = self._choose_pix_fmt(has_alpha)

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
                if adim and adim > 0 and max(im.width, im.height) > adim:
                    scale = adim / max(im.width, im.height)
                    im = im.resize(
                        (max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                        Image.LANCZOS)

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
            _cleanup(tried_tmp_files)
            if os.path.exists(out) and out != out_webp:
                try: os.remove(out)
                except Exception: pass
            return out_webp

        if 'libaom-av1' not in detect_ffmpeg_encoders():
            raise Exception("libaom-av1 не доступен в вашей сборке ffmpeg — AVIF перекодирование настроено работать ТОЛЬКО через libaom (libaom-av1).")
        limit_kb = int(av.get('limit', 0) or 0)

        avif_enc = 'libaom-av1'
        if has_alpha:
            self.log.emit("Альфа-канал обнаружен → AVIF с прозрачностью (alphaextract, libaom-av1)")

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
            scale_vf = vf_override if vf_override is not None else vf
            if has_alpha:
                # AVIF с альфой: цвет (yuva420p) и извлечённая альфа (gray) — два
                # av1-потока, avif-муксер сшивает их в файл с прозрачностью.
                # ВАЖНО: split ДО scale — если масштабировать перед split, ffmpeg
                # при согласовании форматов роняет альфу (alphaextract «could not
                # choose format»). Поэтому делим из yuva420p, затем масштабируем
                # каждую ветку отдельно (цвет и альфа имеют одинаковые размеры).
                if scale_vf:
                    fc = (f"[0:v]format=yuva420p,split[c][a];"
                          f"[c]{scale_vf}[main];[a]alphaextract,{scale_vf}[alf]")
                else:
                    fc = "[0:v]format=yuva420p,split[main][a];[a]alphaextract[alf]"
                cmd = [FFMPEG, "-y", "-i", path, "-filter_complex", fc,
                       "-map", "[main]", "-map", "[alf]",
                       "-c:v", "libaom-av1", "-crf", str(crf_val),
                       "-cpu-used", str(max(0, min(8, aspd))),
                       "-still-picture", "1", "-threads", "0", tmp_out]
            else:
                cmd = [FFMPEG, "-y", "-i", path]
                if scale_vf: cmd += ["-vf", scale_vf]
                cmd += ["-frames:v", "1", "-c:v", "libaom-av1",
                        "-crf", str(crf_val), "-cpu-used", str(max(0, min(8, aspd))),
                        "-pix_fmt", pix_fmt_avif,
                        "-threads", "0", tmp_out]
            try:
                orig_size = os.path.getsize(path) if os.path.exists(path) else 1
                est_seconds = max(1, int(orig_size / 400_000))
                self.run_ffmpeg_capture(cmd, est_seconds, _pass_cb)
                return True, None
            except subprocess.CalledProcessError as e: return False, (e.stderr[:4000] if hasattr(e, 'stderr') else str(e))
            except Exception as e: return False, str(e)

        if not limit_kb or limit_kb <= 0:
            tmp = os.path.join(TEMP_DIR, f"avif_{uuid.uuid4().hex}.avif")
            try:
                ok, err = _encode_to(tmp, 35)
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
                for t in tried_tmp_files:
                    try:
                        if os.path.exists(t): os.remove(t)
                    except Exception: pass

        low_crf = 0
        high_crf = 63
        best_tmp = None
        best_size_kb = -1

        try:
            iterations = 0
            max_iterations = max(1, min(8, int(av.get('fit_passes', 4))))
            tmp63 = os.path.join(TEMP_DIR, f"avif_{uuid.uuid4().hex}_63.avif")
            tried_tmp_files.append(tmp63)
            ok, err = _encode_to(tmp63, 63)
            if not ok:
                if os.path.exists(tmp63):
                    try: os.remove(tmp63)
                    except Exception: pass
                raise Exception(f"AVIF conversion failed: {err}")
            size63_kb = max(1, os.path.getsize(tmp63) // 1024)
            if size63_kb <= limit_kb:
                best_tmp = tmp63
                best_size_kb = size63_kb
                low_crf = 0
                high_crf = 62

            while low_crf <= high_crf and iterations < max_iterations:
                mid = (low_crf + high_crf) // 2
                tmpf = os.path.join(TEMP_DIR, f"avif_{uuid.uuid4().hex}_{mid}.avif")
                tried_tmp_files.append(tmpf)
                ok, err = _encode_to(tmpf, mid)
                if not ok:
                    if os.path.exists(tmpf):
                        try: os.remove(tmpf)
                        except Exception: pass
                    raise Exception(f"AVIF conversion failed: {err}")
                size_kb = max(1, os.path.getsize(tmpf) // 1024)
                if size_kb <= limit_kb:
                    if size_kb > best_size_kb:
                        if best_tmp and best_tmp != tmpf and os.path.exists(best_tmp):
                            try: os.remove(best_tmp)
                            except Exception: pass
                        best_tmp = tmpf
                        best_size_kb = size_kb
                    else:
                        try:
                            if os.path.exists(tmpf):
                                os.remove(tmpf)
                                tried_tmp_files.remove(tmpf)
                        except Exception: pass
                    high_crf = mid - 1
                else:
                    try:
                        if os.path.exists(tmpf):
                            os.remove(tmpf)
                            tried_tmp_files.remove(tmpf)
                    except Exception: pass
                    low_crf = mid + 1
                iterations += 1

            if best_tmp and os.path.exists(best_tmp):
                if os.path.exists(out):
                    try: os.remove(out)
                    except Exception: pass
                shutil.move(best_tmp, out)
                size_new = os.path.getsize(out)
                _cleanup(tried_tmp_files)
                self.update_item_sig.emit(item['iid'], human_size(size_new), "-")
                return out

            if not orig_w or not orig_h:
                try:
                    if Image:
                        with Image.open(path) as im: orig_w, orig_h = im.size
                except Exception: pass

            if not os.path.exists(tmp63): raise Exception("Не удалось получить базовый AVIF.")

            baseline_bytes = os.path.getsize(tmp63)
            target_bytes = limit_kb * 1024

            if not orig_w or not orig_h:
                _cleanup(tried_tmp_files)
                raise Exception("Не удалось получить размеры изображения для downscale.")

            orig_pixels = orig_w * orig_h
            approx_ratio = float(target_bytes) / float(baseline_bytes) if baseline_bytes > 0 else 0.5
            approx_ratio = max(0.01, min(1.0, approx_ratio))
            target_pixels = max(1, int(orig_pixels * approx_ratio * 0.98))
            scale_factor = (target_pixels / orig_pixels) ** 0.5
            new_max_side = max(1, int(max(orig_w, orig_h) * scale_factor))

            if new_max_side >= max(orig_w, orig_h):
                new_max_side = max(1, int(max(orig_w, orig_h) * 0.9))

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
                    _cleanup(tried_tmp_files)
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

        def item_prog(pct, pass_label=None):
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
                self.global_progress.emit(
                    gl_pct,
                    f"{label} ETA: {self._fmt_eta_rate(fraction, eta_anchor[0], eta_anchor[1])}")
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

        # Обрабатываем очередь проходами: после каждого снова заглядываем в живой
        # список self.queue. Файлы, доброшенные во время обработки, подхватываются
        # следующим проходом — кодируем, пока очередь не опустеет.
        while not self.stop_flag:
            batch = [it for it in list(self.queue)
                     if not it.get('is_done', False)
                     and it.get('iid') not in self._processed_ids]
            if not batch:
                break
            for it in batch:
                self._processed_ids.add(it.get('iid'))

            # Видео/аудио — по одному: каждый файл сам грузит все ядра кодеком (SVT-AV1).
            # Изображения — параллельно по числу ядер через QThreadPool: одиночный кадр
            # CPU не насыщает, а потоки Qt безопасны для сигналов и корректно очищаются.
            images = [it for it in batch if it.get('type') == 'IMG']
            others = [it for it in batch if it.get('type') != 'IMG']

            # Видео/аудио идут по одному файлу, но кодировщик SVT-AV1 сам нагружает
            # ВСЕ логические ядра ЦП. Поэтому счётчик показывает занятые потоки ЦП
            # (а не «1 файл»), иначе создаётся ложное впечатление загрузки в 1 поток.
            if others:
                self._max_threads = cpu
                if not self._logged_cpu_msg:
                    self.log.emit("Кодирование видео/аудио: SVT-AV1.")
                    self._logged_cpu_msg = True
                for it in others:
                    if self.stop_flag:
                        break
                    self._process_item(it, True, start, weight=cpu)

            if images and not self.stop_flag:
                nworkers = min(len(images), cpu)
                # Знаменатель счётчика — всегда ВСЕ логические потоки ЦП машины (cpu),
                # а не число воркеров. Иначе при 6 картинках показывалось «2/6» (хотя
                # потоков 12), а в конце — «0/12»: знаменатель менялся и сбивал с толку.
                # Теперь это честно «занято/всего», напр. 6 картинок = до «6/12».
                self._max_threads = cpu
                if nworkers > 1:
                    self.log.emit(f"Параллельная обработка изображений: {nworkers} потоков")
                    self._img_pool = QThreadPool()
                    self._img_pool.setMaxThreadCount(nworkers)
                    for itm in images:
                        if self.stop_flag:
                            break
                        self._img_pool.start(_ImgRunnable(self, itm, start))
                    self._img_pool.waitForDone()
                else:
                    for it in images:
                        if self.stop_flag:
                            break
                        self._process_item(it, True, start)

        self.active_threads.emit(0, 0)
        self.finished_all.emit()
        self.global_progress.emit(100, "Готово")
