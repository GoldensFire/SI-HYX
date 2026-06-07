# -*- coding: utf-8 -*-
# workers.py — фоновые потоки: загрузка (yt-dlp) и обработка (ffmpeg)
from config import *
from utils import *
from utils import _cookie_matches_domain, _RE_DIGITS


class InfoWorker(QThread):
    success = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.cancelled = False
        self._proc = None

    def run(self):
        base = ytdlp_base_cmd()
        if not base:
            self.error.emit("yt-dlp не найден. Положите yt-dlp.exe в папку bin рядом с программой.")
            return
        try:
            cmd = base + [
                "--no-playlist", "--no-warnings", "--skip-download",
                "--socket-timeout", "15", "--no-check-certificate",
                "--print", "%(duration)s\t%(thumbnail)s",
            ]
            c_path = get_cookies_path(self.url)
            if os.path.exists(c_path):
                cmd += ["--cookies", c_path]
            if 'youtube.com' in self.url.lower() or 'youtu.be' in self.url.lower():
                cmd += ["--extractor-args", "youtube:player_client=tv,web"]
            cmd += [self.url]

            if self.cancelled: return
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW)
            out, _err = self._proc.communicate(timeout=60)
            if self.cancelled: return

            duration, thumb = 0, ""
            for line in (out or "").splitlines():
                if "\t" in line:
                    d, t = line.split("\t", 1)
                    try: duration = int(float(d)) if d and d != "NA" else 0
                    except Exception: duration = 0
                    thumb = "" if t.strip() in ("", "NA") else t.strip()
                    break
            if duration or thumb:
                self.success.emit(duration, thumb)
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

    def stop(self):
        self.is_running = False
        p = self._proc
        if p and p.poll() is None:
            try: p.kill()
            except Exception: pass

    def run(self):
        iid = self.c.get('iid', '')
        self._iid = iid
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

            outtmpl = os.path.join(out_dir, '%(title)s [%(id)s].%(ext)s')

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
                    outtmpl = os.path.join(out_dir, f'%(title)s [{s_tag}-{e_tag}] [%(id)s].%(ext)s')

            cmd = base + [
                "--newline", "--no-playlist", "--no-mtime", "--progress",
                "--socket-timeout", "30", "--no-check-certificate", "--windows-filenames",
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

            if is_audio_only:
                cmd += ["-f", "bestaudio/best", "-x", "--audio-format", "m4a", "--audio-quality", "0"]
            else:
                cmd += ["-f", self.c.get('fmt') or "bestvideo+bestaudio/best",
                        "--merge-output-format", merge]

            if 'tiktok.com' in url.lower():
                self.log_sig.emit("TikTok обнаружен: применяю Mobile API Fix...")
                cmd += ["--extractor-args",
                        "tiktok:api_hostname=api22-normal-c-useast2a.tiktokv.com;app_info=7355728856979392262",
                        "--user-agent",
                        "com.zhiliaoapp.musically/2022600030 (Linux; U; Android 7.1.2; es_ES; SM-G988N; Build/NRD90M; Cronet/58.0.2991.0)"]

            if 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
                self.log_sig.emit("YouTube: клиент tv + web (n-challenge через Deno)...")
                if not shutil.which("deno"):
                    self.log_sig.emit("ВНИМАНИЕ: Deno не найден — YouTube может отдать только превью. Положите deno.exe в bin.")
                cmd += ["--extractor-args", "youtube:player_client=tv,web"]

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

            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW, bufsize=1)

            out_fullpath = ""
            clean_res_str = ""
            tail = deque(maxlen=40)
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
                if "[merger]" in low or "[extractaudio]" in low or "merging formats" in low:
                    self.progress_sig.emit(iid, 100.0, "Обработка...")

            self._proc.wait()
            rc = self._proc.returncode

            if not self.is_running:
                raise Exception("Загрузка остановлена пользователем")

            if not out_fullpath or not os.path.exists(out_fullpath):
                out_fullpath = self._find_recent_output(out_dir)

            if not out_fullpath or not os.path.exists(out_fullpath):
                if rc not in (0, None):
                    raise Exception("\n".join(tail) or f"yt-dlp завершился с кодом {rc}")
                raise Exception("yt-dlp завершил работу, но файл не найден (ошибка скачивания)")

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
            self.progress_sig.emit(self._iid, pct, msg)
        except Exception:
            pass

    def _find_recent_output(self, out_dir):
        try:
            now = time.time()
            cands = [
                os.path.join(out_dir, fn) for fn in os.listdir(out_dir)
                if os.path.isfile(os.path.join(out_dir, fn))
                and not fn.endswith((".part", ".ytdl", ".temp", ".part-Frag"))
                and (now - os.path.getmtime(os.path.join(out_dir, fn))) < 300
            ]
            if cands:
                return max(cands, key=os.path.getmtime)
        except Exception:
            pass
        return ""

    def _emit_hints(self, err_msg):
        if "Sign in to confirm" in err_msg or "not a bot" in err_msg:
            self.log_sig.emit("СОВЕТ: YouTube требует «не бот» — куки без данных входа.")
            self.log_sig.emit("  Экспортируйте куки залогиненного YouTube (нужны LOGIN_INFO, __Secure-1PSID, SID, SAPISID).")
        elif "Forbidden" in err_msg or "403" in err_msg:
            u = self.c.get("url", "").lower()
            if "tiktok.com" in u:
                self.log_sig.emit("СОВЕТ: 403 на TikTok. Удалите/переименуйте cookies_tiktok.txt.")
            elif "fbcdn.net" in u or "instagram.com" in u:
                self.log_sig.emit("СОВЕТ: 403 на Instagram CDN. Ссылка устарела — откройте видео заново.")
            else:
                self.log_sig.emit("СОВЕТ: 403 Forbidden. Возможно, нужны куки или ссылка устарела.")


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


class ProcessWorker(QThread):
    progress = pyqtSignal(str, int)
    status = pyqtSignal(str, str, str)
    log = pyqtSignal(str)
    global_progress = pyqtSignal(int, str)
    finished_all = pyqtSignal()
    update_item_sig = pyqtSignal(str, str, str)
    update_lufs_sig = pyqtSignal(str, object, object)

    def __init__(self, queue_ref, settings):
        super().__init__()
        self.queue = queue_ref
        self.settings = settings
        self.stop_flag = False
        self.svt_available = require_svt()

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
    def _choose_pix_fmt(has_alpha: bool, ten_bit: bool = False) -> str:
        """Возвращает pix_fmt с учётом альфа-канала."""
        if has_alpha:
            return "yuva420p10le" if ten_bit else "yuva420p"
        return "yuv420p10le" if ten_bit else "yuv420p"

    @staticmethod
    def _avif_encoder_for_alpha() -> str:
        """Для AVIF с альфой нужен libaom-av1 — libsvtav1 alpha не поддерживает."""
        encs = detect_ffmpeg_encoders()
        if 'libaom-av1' in encs:
            return 'libaom-av1'
        return 'libsvtav1'  # fallback — альфа потеряется, но хоть не упадёт

    def run_ffmpeg_capture(self, cmd, total_est_sec, percent_callback, label=None):
        si = subprocess.STARTUPINFO() if IS_WIN else None
        if IS_WIN and si is not None: si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        buf = deque(maxlen=8000)
        try:
            p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW, startupinfo=si)
        except Exception as e:
            raise Exception(f"Не удалось запустить ffmpeg: {e}")
        start = time.time()
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
                _, _, _, a_br_str = get_media_info(path)
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
        out_dir = os.path.dirname(path) or "."
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
            tgt_i = float(sa.get('tgt', -16.0))
            lra = float(sa.get('lra', 20.0))
            tp = float(sa.get('tp', -1.5))
            audio_filters.append(f"loudnorm=I={tgt_i}:LRA={lra}:TP={tp}")
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
            is_hevc = (vcodec and ('hevc' in vcodec or 'h265' in vcodec))
            step1_needed = is_hevc or bool(audio_filters) or (is_video and abs(speed_factor - 1.0) > 0.01)

            if step1_needed:
                temp_ext = ".mp4" if is_video else ".opus"
                temp_intermediate = os.path.join(TEMP_DIR, f"inter_{uuid.uuid4().hex}{temp_ext}")
                temp_files.append(temp_intermediate)

                cmd_step1 = [FFMPEG, "-y", "-i", current_input, "-map", "0"]
                if audio_filters: cmd_step1 += ["-af", ",".join(audio_filters)]
                
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
                cmd_step2 = [FFMPEG, "-y", "-i", current_input, "-map", "0"]

                res_sel = sv.get('res', 'Исходное') or 'Исходное'
                vf_list = []

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
                    # Профиль «Тёмные сцены»: 10-бит, tune=ssim, 2-pass AV1
                    has_alpha = self._source_has_alpha(current_input)
                    pix_fmt = self._choose_pix_fmt(has_alpha, ten_bit=True)
                    svt_params = "tune=2"   # tune=ssim в SVT-AV1
                    preset_val = str(max(0, min(13, sv.get('pre', 0))))
                    est = max(1, int(os.path.getsize(current_input)/400000)) if os.path.exists(current_input) else 10

                    stats_file = os.path.join(TEMP_DIR, f"svtav1stats_{uuid.uuid4().hex}")
                    temp_files.append(stats_file + "-0.log")
                    temp_files.append(stats_file + "-0.log.mbtree")

                    # Pass 1
                    cmd_pass1 = [
                        FFMPEG, "-y", "-i", current_input, "-map", "0:v:0",
                        "-c:v", "libsvtav1", "-crf", str(crf), "-preset", preset_val,
                        "-svtav1-params", svt_params,
                        "-pix_fmt", pix_fmt,
                        "-pass", "1", "-passlogfile", stats_file,
                        "-an", "-f", "null",
                        "NUL" if IS_WIN else "/dev/null"
                    ]
                    if vf_list:
                        cmd_pass1 = cmd_pass1[:4] + ["-vf", ",".join(vf_list)] + cmd_pass1[4:]

                    self.log.emit("🌑 Тёмные сцены: Pass 1/2 (анализ)...")
                    self.run_ffmpeg_capture(cmd_pass1, est, cb, label="Pass 1 (AV1 анализ)")

                    # Pass 2
                    cmd_pass2 = [
                        FFMPEG, "-y", "-i", current_input, "-map", "0",
                        "-c:v", "libsvtav1", "-crf", str(crf), "-preset", preset_val,
                        "-svtav1-params", svt_params,
                        "-pix_fmt", pix_fmt,
                        "-pass", "2", "-passlogfile", stats_file,
                    ]
                    if vf_list:
                        cmd_pass2 += ["-vf", ",".join(vf_list)]
                    cmd_pass2 += ["-threads", "0", "-c:a", "copy", attempted_out]

                    self.log.emit("🌑 Тёмные сцены: Pass 2/2 (кодирование)...")
                    self.run_ffmpeg_capture(cmd_pass2, est, cb, label="Pass 2 (AV1 кодирование)")

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
                    cmd_step2 += ["-threads", "0", "-c:a", "copy", attempted_out]

                    est = max(1, int(os.path.getsize(current_input)/400000)) if os.path.exists(current_input) else 10
                    self.run_ffmpeg_capture(cmd_step2, est, cb, label="Pass 2 (Video)")

            else:
                if current_input != path:
                    inter_ext = os.path.splitext(current_input)[1].lower()
                    if inter_ext == out_ext:
                        if os.path.exists(out): os.remove(out)
                        shutil.move(current_input, out)  # step1 уже применил libopus, просто переносим
                else:
                    cmd_direct = [FFMPEG, "-y", "-i", path, "-map", "0"]
                    if audio_filters: cmd_direct += ["-af", ",".join(audio_filters)]
                    cmd_direct += ["-c:a", audio_codec, "-b:a", audio_bitrate]
                    if is_video: cmd_direct += ["-c:v", "copy"]
                    else: cmd_direct += ["-vn"]
                    cmd_direct += [out]
                    self.run_ffmpeg_capture(cmd_direct, max(1, int(os.path.getsize(path)/1000000)), cb, label=None)

            if os.path.exists(out):
                size_new = os.path.getsize(out)
                _, br_str, _, a_br = get_media_info(out)
                self.update_item_sig.emit(item['iid'], human_size(size_new), a_br or br_str or "-")
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

    def _convert_simple_image(self, item, src_path, out_dir, sanitized, adim, av, fmt, cb):
        """Конвертация изображения в png / jpg / ico через Pillow (без ffmpeg).
        Учитывает лимит разрешения (adim) и для jpg — лимит размера файла.
        """
        if not Image:
            raise Exception("Pillow (PIL) не установлен — конвертация в этот формат недоступна.")
        fmt = fmt.lower()
        ext = {'jpeg': 'jpg', 'jpg': 'jpg', 'png': 'png', 'ico': 'ico'}.get(fmt, fmt)
        out_path = os.path.join(out_dir, f"{sanitized}_Сжатый.{ext}")
        cb(10, ext.upper())

        with Image.open(src_path) as im:
            if ImageOps:
                im = ImageOps.exif_transpose(im)
            # JPEG не поддерживает альфу
            if ext == 'jpg':
                im = im.convert('RGB')
            elif ext == 'ico':
                im = im.convert('RGBA')
            else:  # png
                im = im.convert('RGBA') if im.mode in ('RGBA', 'LA', 'P', 'PA') else im.convert('RGB')

            # Лимит разрешения; для ICO жёсткий потолок 256px
            cap = adim if (adim and adim > 0) else None
            if ext == 'ico':
                cap = min(256, cap) if cap else 256
            if cap and max(im.width, im.height) > cap:
                sc = cap / max(im.width, im.height)
                im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.LANCZOS)

            cb(55, ext.upper())
            limit_kb = int(av.get('limit', 0) or 0) if av.get('limit_on', True) else 0

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
                    chosen = 30
                    for q in (95, 90, 85, 80, 70, 60, 50, 40, 30):
                        tmp = os.path.join(TEMP_DIR, f"jpg_{uuid.uuid4().hex}.jpg")
                        try:
                            im.save(tmp, format='JPEG', quality=q, optimize=True)
                            fits = os.path.getsize(tmp) // 1024 <= limit_kb
                        finally:
                            try: os.remove(tmp)
                            except Exception: pass
                        chosen = q
                        if fits:
                            break
                    im.save(out_path, format='JPEG', quality=chosen, optimize=True)
                else:
                    im.save(out_path, format='JPEG', quality=92, optimize=True)
            else:  # png
                im.save(out_path, format='PNG', optimize=True)

        cb(100, ext.upper())
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
        out_dir = os.path.dirname(path) or "."
        av = self.settings.get('avif', {})
        adim = av.get('adim', 0) or 0
        aspd = av.get('aspd', 0)
        raw_name = os.path.basename(base)
        sanitized = self._sanitize_name(raw_name)
        if sanitized != raw_name:
            self.log.emit(f"Имя переименовано (AI-бренд): «{raw_name}» → «{sanitized}»")
        out_name = sanitized + "_Сжатый.avif"
        out = os.path.join(out_dir, out_name)

        # Выбранный пользователем формат: png/jpg/ico обрабатываем через Pillow
        # (без ffmpeg), avif/webp — основной конвейер ниже.
        img_fmt = (av.get('img_fmt') or 'avif').lower()
        if img_fmt in ('png', 'jpg', 'jpeg', 'ico'):
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

        # Альфа-канал → только WebP с прозрачностью, лимит в KB соблюдается
        if has_alpha and Image:
            try:
                self.log.emit("Альфа-канал → WebP (RGBA)")
                cb(10, "WebP (alpha)")

                with Image.open(path) as im:
                    if ImageOps: im = ImageOps.exif_transpose(im)
                    im = im.convert('RGBA')
                    if adim and adim > 0 and max(im.width, im.height) > adim:
                        scale = adim / max(im.width, im.height)
                        im = im.resize(
                            (max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                            Image.LANCZOS)

                    cb(50, "WebP (alpha)")
                    out_webp = os.path.splitext(out)[0] + ".webp"
                    limit_kb = int(av.get('limit', 0) or 0)

                    if limit_kb > 0:
                        chosen_quality = 10  # минимум на случай если ничего не подошло
                        for q in (85, 70, 55, 40, 25, 10):
                            tmp_w = os.path.join(TEMP_DIR, f"wp_{uuid.uuid4().hex}.webp")
                            tried_tmp_files.append(tmp_w)
                            im.save(tmp_w, format="WEBP", quality=q, lossless=False)
                            fits = os.path.getsize(tmp_w) // 1024 <= limit_kb
                            try: os.remove(tmp_w); tried_tmp_files.remove(tmp_w)
                            except Exception: pass
                            if fits:
                                chosen_quality = q
                                break
                        im.save(out_webp, format="WEBP", quality=chosen_quality, lossless=False)
                    else:
                        im.save(out_webp, format="WEBP", quality=85, lossless=False)

                cb(100, "WebP (alpha)")
                size_new = os.path.getsize(out_webp)
                self.update_item_sig.emit(item['iid'], human_size(size_new), "-")
                _cleanup(tried_tmp_files)
                # Удаляем старый .avif если он остался от предыдущего запуска
                if os.path.exists(out) and out != out_webp:
                    try: os.remove(out)
                    except Exception: pass
                return out_webp   # ← выходим, AVIF не создаётся
            except Exception as e:
                self.log.emit(f"WebP alpha failed ({e}) — пробуем FFmpeg")

        if not self.svt_available:
            if not has_alpha or 'libaom-av1' not in detect_ffmpeg_encoders():
                raise Exception("libsvtav1 не доступен — AVIF конвертация поддерживается только через SVT.")
        limit_kb = int(av.get('limit', 0) or 0)

        if has_alpha:
            avif_enc = self._avif_encoder_for_alpha()
            self.log.emit(f"Альфа-канал обнаружен → используется энкодер: {avif_enc}")
        else:
            avif_enc = 'libsvtav1'

        def _encode_to(tmp_out, crf_val, vf_override=None):
            cmd = [FFMPEG, "-y", "-i", path]
            if vf_override: cmd += ["-vf", vf_override]
            elif vf: cmd += ["-vf", vf]
            if avif_enc == 'libaom-av1':
                cmd += ["-frames:v", "1", "-c:v", "libaom-av1",
                        "-crf", str(crf_val), "-cpu-used", str(max(0, min(8, aspd))),
                        "-pix_fmt", pix_fmt_avif,
                        "-threads", "0", tmp_out]
            else:
                cmd += ["-frames:v", "1", "-c:v", "libsvtav1",
                        "-crf", str(crf_val), "-preset", str(max(0, min(8, aspd))),
                        "-pix_fmt", pix_fmt_avif, "-threads", "0", tmp_out]
            try:
                orig_size = os.path.getsize(path) if os.path.exists(path) else 1
                est_seconds = max(1, int(orig_size / 400_000))
                self.run_ffmpeg_capture(cmd, est_seconds, cb, label="AVIF")
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
            max_iterations = 8
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
            raise Exception(f"AVIF conversion failed: {stderr_tail[:4000]}")
        except Exception as e:
            _cleanup(tried_tmp_files)
            if os.path.exists(out):
                try:
                    os.remove(out)
                    self.log.emit(f"Удалён повреждённый AVIF: {out}")
                except Exception: pass
            raise

    def run(self):
        start = time.time()
        idx = 0
        cur_total = max(1, len(self.queue))
        
        while not self.stop_flag:
            if idx >= len(self.queue):
                break 
            
            item = self.queue[idx]
            iid = item['iid']
            path = item['path']

            if item.get('is_done', False):
                idx += 1
                continue

            self.status.emit(iid, "Обработка.", "proc")
            
            max_frac_seen = [0.0]
            def item_prog(pct, pass_label=None):
                try:
                    # Маппинг прогресса для видео: Pass 1 → 0-50%, Pass 2 → 50-100%
                    if pass_label and "Pass 1" in pass_label:
                        display_pct = int(pct * 0.5)
                    elif pass_label and "Pass 2" in pass_label:
                        display_pct = int(50 + pct * 0.5)
                    else:
                        display_pct = pct

                    self.progress.emit(iid, display_pct)
                    fraction = ((idx) + (display_pct / 100.0)) / cur_total
                    # Монотонно возрастающая fraction — ETA не скачет при итерациях AVIF
                    fraction = max(fraction, max_frac_seen[0])
                    max_frac_seen[0] = fraction
                    if fraction <= 0.0001: fraction = 0.0001
                    
                    gl_pct = int(min(100, fraction * 100))
                    elapsed = time.time() - start
                    
                    if gl_pct >= 100 or (idx == cur_total - 1 and pct >= 100):
                        eta = "00:00:00"
                    elif elapsed < 1.0:
                        eta = "..."
                    elif fraction > 0:
                        rem = max(0, elapsed * (1.0 / fraction - 1.0))
                        rh = int(rem // 3600); rm = int((rem % 3600) // 60); rs = int(rem % 60)
                        eta = f"{rh:02}:{rm:02}:{rs:02}"
                    else:
                        eta = "--:--"
                    
                    label = pass_label if pass_label else "Processing"
                    if pass_label and pct < 100:
                        self.status.emit(iid, pass_label, "proc")
                    self.global_progress.emit(gl_pct, f"{label} ETA: {eta}")
                except Exception:
                    try: self.global_progress.emit(0, "ETA: --:--")
                    except Exception: pass
            try:
                if item.get('type') == 'MEDIA': self.process_media(item, item_prog)
                elif item.get('type') == 'IMG': self.process_avif(item, item_prog)
                else: self.process_media(item, item_prog)
                
                item['is_done'] = True
                # Сохраняем путь к выходному файлу — нужен для кнопки "Открыть"
                try:
                    sv2 = self.settings.get('video', {})
                    sa2 = self.settings.get('audio', {})
                    crf2 = sv2.get('crf', 35); spd2 = sv2.get('speed', 100)
                    ve2 = sv2.get('enabled', True)
                    base2, ext2 = os.path.splitext(path)
                    out_dir2 = os.path.dirname(path) or "."
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
                self.status.emit(iid, "Готово", "done")
                self.progress.emit(iid, 100)
                item_prog(100, "Готово")
            except Exception as e:
                tb = str(e)
                if "StoppedByUser" in tb:
                     self.log.emit(f"Остановка {os.path.basename(path)} выполнена.")
                     self.status.emit(iid, "Остановлено", "err")
                else:
                     self.log.emit(f"Ошибка {os.path.basename(path)}: {tb}")
                     self.status.emit(iid, "Ошибка", "err")
                item['is_done'] = True
            
            idx += 1
            
        self.finished_all.emit()
        self.global_progress.emit(100, "Готово")
