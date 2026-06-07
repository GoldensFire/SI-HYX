# -*- coding: utf-8 -*-
# utils.py — вспомогательные функции (ffmpeg/ffprobe, cookies, deno, и т.п.)
from config import *


def ensure_deno_on_path():
    """yt-dlp использует Deno для решения YouTube n-challenge. Без него
    YouTube отдаёт только превью ('Only images are available').
    Приоритет поиска: bundled (рядом с программой / bin) → системный PATH →
    стандартные места установки (winget / .deno). Найденный каталог
    добавляется в PATH, чтобы yt-dlp его нашёл."""
    exe_name = "deno.exe" if IS_WIN else "deno"

    def _use(d):
        if d and os.path.isfile(os.path.join(d, exe_name)):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            return True
        return False

    try:
        # 1) Рядом с программой (для сборки .exe с bundled-deno): _MEIPASS,
        #    папка exe/скрипта и их подпапка bin — в приоритете над системным.
        roots = []
        base = getattr(sys, "_MEIPASS", None)
        if base:
            roots.append(base)
        roots.append(os.path.dirname(os.path.abspath(sys.argv[0] or ".")))
        roots.append(os.path.dirname(os.path.abspath(__file__)))
        for r in roots:
            if _use(r) or _use(os.path.join(r, "bin")):
                return True

        # 2) Уже доступен в системном PATH
        if shutil.which("deno"):
            return True

        # 3) Стандартные места установки (winget / .deno)
        sys_cands = []
        la = os.getenv("LOCALAPPDATA")
        home = os.path.expanduser("~")
        if la:
            sys_cands.append(os.path.join(la, "Microsoft", "WinGet", "Links"))
            try:
                import glob as _glob
                sys_cands += [
                    os.path.dirname(p) for p in
                    _glob.glob(os.path.join(la, "Microsoft", "WinGet", "Packages",
                                            "DenoLand.Deno_*", "deno.exe"))
                ]
            except Exception:
                pass
        sys_cands.append(os.path.join(home, ".deno", "bin"))
        for d in sys_cands:
            if _use(d):
                return True
    except Exception:
        pass
    return False


# Включаем Deno в PATH при старте — нужно для скачивания с YouTube
ensure_deno_on_path()


# Helpers
# Предкомпилированные регулярные выражения — не пересоздаются при каждом вызове
_RE_ANSI    = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


_RE_LUFS    = re.compile(r'\{[\s\S]*?\}')  # нежадный — не захватывает лишние блоки


_RE_DIGITS  = re.compile(r'(\d+)')


def clean_ansi(text: str) -> str:
    return _RE_ANSI.sub('', text)


def load_settings() -> dict:
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_settings(settings: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def human_size(n):
    if not n:
        return "-"
    try:
        n = float(n)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if n < 1024.0:
                return f"{n:.1f}{unit}"
            n /= 1024.0
    except Exception:
        return "-"
    return f"{n * 1024:.1f}TB"  # fallback для экстремально больших значений


def get_cookies_path(url: str) -> str:
    u = url.lower()
    if 'tiktok.com' in u:   return COOKIE_PATHS['tiktok']
    if 'instagram.com' in u or 'fbcdn.net' in u or 'cdninstagram.com' in u:
        return COOKIE_PATHS['instagram']
    if 'youtube.com' in u or 'youtu.be' in u: return COOKIE_PATHS['youtube']
    return COOKIE_PATHS['default']


def _cookie_matches_domain(cookie_path: str, url: str) -> bool:
    """Проверяет, подходит ли файл куки к домену URL.
    Если имя файла содержит название другого сервиса — не подходит."""
    cp = os.path.basename(cookie_path).lower()
    u  = url.lower()
    # Instagram/fbcdn с YouTube-куками → не подходит
    if ('instagram' in u or 'fbcdn.net' in u) and 'youtube' in cp: return False
    if 'tiktok' in u and ('youtube' in cp or 'instagram' in cp): return False
    if ('youtube' in u or 'youtu.be' in u) and 'instagram' in cp: return False
    return True


def is_direct_cdn_video(url: str) -> bool:
    """True если URL — прямая CDN-ссылка на видеофайл (не страница сервиса).
    Такие ссылки нельзя передавать yt-dlp — он не может извлечь метаданные
    и падает с 403 или создаёт имя файла из URL.
    """
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        path = p.path.lower()
        cdn_hosts = ('fbcdn.net', 'cdninstagram.com', 'cdntiktok.com')
        is_cdn_host = any(h in p.netloc.lower() for h in cdn_hosts)
        is_video_ext = path.endswith(('.mp4', '.webm', '.mov', '.m4v', '.ts'))
        return is_cdn_host and is_video_ext
    except Exception:
        return False


def download_cdn_direct(url: str, out_dir: str, log_fn=None) -> str:
    """Скачивает прямую CDN-ссылку через urllib с нужными заголовками.
    Возвращает путь к сохранённому файлу или бросает исключение.
    """
    from urllib.parse import urlparse, unquote
    import re

    # Имя файла берём из пути URL (без query-параметров)
    path_part = urlparse(url).path
    raw_name  = os.path.basename(path_part) or "video.mp4"
    # Оставляем только безопасные символы
    safe_name = re.sub(r'[^\w\-\.]', '_', unquote(raw_name))[:80] or "video.mp4"
    if not safe_name.endswith(('.mp4', '.webm', '.mov', '.m4v')):
        safe_name += '.mp4'

    out_path = os.path.join(out_dir, safe_name)
    if os.path.exists(out_path):
        base_n, ext_n = os.path.splitext(safe_name)
        out_path = os.path.join(out_dir, f"{base_n}_{int(time.time())}{ext_n}")

    headers = {
        "User-Agent": USER_AGENT,
        "Referer":    "https://www.instagram.com/",
        "Accept":     "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if log_fn: log_fn(f"Прямое скачивание CDN: {url[:60]}...")
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(out_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if log_fn and total:
                    pct = downloaded * 100 // total
                    log_fn(f"CDN загрузка: {pct}%")
    if log_fn: log_fn(f"CDN загрузка завершена: {out_path}")
    return out_path


def clean_url(url: str) -> str:
    if 'tiktok.com' in url and '?' in url:
        return url.split('?')[0]
    # Прямые CDN-ссылки на видеофайлы (Instagram, Facebook и др.):
    # yt-dlp не может извлечь title/id из CDN URL → имя файла содержит
    # недопустимые символы Windows (?&=). Стрипаем query-параметры.
    if '?' in url:
        path = url.split('?')[0]
        if path.lower().endswith(('.mp4', '.webm', '.mov', '.m4v', '.avi', '.mkv')):
            return path
    return url


def check_ffmpeg():
    try:
        subprocess.run([FFMPEG, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def get_media_info(path):
    """Возвращает (duration, bitrate_str, size, audio_bitrate_str).
    Один вызов ffprobe с JSON-выводом — поля именованные, порядок не важен.
    """
    dur = 0.0
    size = 0
    br_str = "-"
    a_br = "-"
    try:
        size = os.path.getsize(path)
    except Exception:
        size = 0
    try:
        p = subprocess.run(
            [FFPROBE, "-v", "error",
             "-show_entries",
             "format=duration,bit_rate:stream=bit_rate,sample_rate,channels,bits_per_sample",
             "-select_streams", "a:0",
             "-of", "json",
             path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        data = json.loads(p.stdout or "{}")

        fmt = data.get("format", {})
        try:
            dur = float(fmt.get("duration", 0) or 0)
        except Exception:
            dur = 0.0
        try:
            fmt_br = int(fmt.get("bit_rate", 0) or 0)
            if fmt_br > 0:
                br_str = f"{fmt_br // 1000} кбит/с"
        except Exception:
            pass

        streams = data.get("streams", [])
        if streams:
            s0 = streams[0]
            try:
                abr = int(s0.get("bit_rate", 0) or 0)
                if abr > 0:
                    a_br = f"{abr // 1000} кбит/с"
                    br_str = a_br
            except Exception:
                pass
            # WAV / PCM / FLAC не хранят bit_rate в stream — вычисляем вручную
            if a_br == "-":
                try:
                    sr   = int(s0.get("sample_rate", 0) or 0)
                    ch   = int(s0.get("channels", 0) or 0)
                    bps  = int(s0.get("bits_per_sample", 0) or 0)
                    if sr > 0 and ch > 0 and bps > 0:
                        calc = sr * ch * bps
                        a_br = f"{calc // 1000} кбит/с"
                        br_str = a_br
                except Exception:
                    pass
            # Последний резерв: format.bit_rate (работает для opus, mp3, m4a…)
            if a_br == "-" and fmt_br > 0:
                a_br = f"{fmt_br // 1000} кбит/с"
                br_str = a_br

    except Exception:
        pass
    try:
        if br_str == "-" and dur and size:
            est = int(size * 8 / dur)
            br_str = f"{est // 1000} кбит/с"
            if a_br == "-":
                a_br = br_str
    except Exception:
        pass
    return dur, br_str, size, a_br


def get_fps_float(path):
    try:
        cmd = [FFPROBE, "-v", "0", "-of", "csv=p=0", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", path]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=CREATE_NO_WINDOW)
        val = p.stdout.strip()
        if '/' in val:
            num, den = val.split('/', 1)
            return float(num) / float(den)
        return float(val)
    except Exception:
        return 0.0


def get_video_codec(path):
    try:
        p = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", path],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=CREATE_NO_WINDOW)
        return p.stdout.strip().lower() or None
    except Exception:
        return None


def measure_loudness(path):
    try:
        cmd = [FFMPEG, "-hide_banner", "-nostats", "-i", path, "-af", "loudnorm=I=-16:LRA=20:TP=-1.5:print_format=json", "-f", "null", "-"]
        p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
        stderr = p.communicate()[1] or ""
        m = _RE_LUFS.search(stderr)
        if m:
            data = json.loads(m.group(0))
            if 'input_i' in data:
                return float(data.get('input_i'))
    except Exception:
        pass
    return None


def play_done_sound():
    try:
        if IS_WIN:
            import winsound
            try: winsound.MessageBeep(winsound.MB_ICONEXCLAMATION); return
            except Exception: winsound.Beep(750, 300); return
    except Exception: pass
    try: print('\a', end='', flush=True)
    except Exception: pass


def pil_to_qicon(img):
    if not Image or img is None: return QIcon()
    try:
        bio = io.BytesIO()
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        img.save(bio, format="PNG")
        data = bio.getvalue()
        pix = QPixmap()
        if pix.loadFromData(QByteArray(data)): return QIcon(pix)
        else:
            qimg = QtGuiImage.fromData(data)
            return QIcon(QPixmap.fromImage(qimg))
    except Exception:
        return QIcon()


@functools.lru_cache(maxsize=None)
def detect_ffmpeg_encoders():
    """Определяет доступные кодеки FFmpeg. Результат кешируется — ffmpeg запускается только один раз."""
    try:
        p = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=CREATE_NO_WINDOW)
        encs = set()
        for line in (p.stdout or "").splitlines():
            m = re.match(r'^\s*[A-Z\.]+\s+([a-z0-9_\-]+)\s+', line, re.I)
            if m: encs.add(m.group(1).strip().lower())
        return frozenset(encs)  # frozenset совместим с lru_cache (хешируемый)
    except Exception:
        return frozenset()


def require_svt():
    return 'libsvtav1' in detect_ffmpeg_encoders()
