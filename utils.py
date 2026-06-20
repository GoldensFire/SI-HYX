# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# utils.py — вспомогательные функции (ffmpeg/ffprobe, cookies, deno, и т.п.)
from config import *


# ── Маскировка JS в HTML под VK ──────────────────────────────────────────────
# VK отклоняет .siq с читаемым JS: ловит тег <script> и литерал function/Function.
# Но JS в атрибуте-обработчике (onload=...) пропускает, ЕСЛИ в нём нет слова
# function — проверенный рабочий приём (файл oden.html) прячет «Function» через
# склейку 'Fun'+'ction' и не содержит ни <script>, ни function.
#
# Стратегия (прирост веса ≈ +33%, одинарный base64):
#   • видимая часть = точный паттерн oden: onload="const launch='Fun'+'ction';
#     window[launch](atob('<LOADER>'))();" — VK видит только это;
#   • <LOADER> (base64) — крошечный фиксированный загрузчик: читает payload из
#     data-si и пересоздаёт <script> (createElement, function, 'script' — внутри
#     base64, VK их не читает). Двойное кодирование тут дёшево: загрузчик мал;
#   • сам код игры лежит в data-si одинарным base64 ("b:<base64>"|"s:<url>",
#     разделитель '|'). Для VK это безопасная base64-каша, БОЛЬШОЙ код повторно
#     НЕ кодируется → нет раздувания вдвое.
# Пересозданные <script> исполняются в ГЛОБАЛЬНОЙ области, поэтому существующие
# инлайн onclick=... работают. Внешние <script src> грузятся по цепочке (onload)
# перед инлайн-кодом — порядок сохраняется.
# Закрывающий тег матчим как </script…> с любыми пробелами/мусором до '>'
# (браузеры принимают </script >, </script foo="bar"> и т.п.) — иначе
# часть скриптов осталась бы незакодированной (CodeQL py/bad-tag-filter).
_B64_SCRIPT_RX = re.compile(r'(?is)<script\b([^>]*)>(.*?)</script\b[^>]*>')
_B64_SRC_RX    = re.compile(r'(?i)src\s*=\s*[\'"]([^\'"]+)[\'"]')
# 1×1 прозрачный gif — носитель onload-триггера
_B64_GIF = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
# Максимум символов в одном непрерывном куске base64. VK режет файл, если
# встречает длинную НЕПРЕРЫВНУЮ base64-строку (порог опытно между 184 и 612).
# 120 — с запасом ниже 184. Дробится и payload (data-si), и сам загрузчик (onload).
_B64_CHUNK = 120


def mask_html_js(html: str):
    """Прячет под VK всё «активное» содержимое HTML.

    Возвращает (masked_html, n_inline, n_external):
      masked_html — документ, где всё тело <body> заменено одним триггер-img,
                    а реальное содержимое лежит в data-si одинарным base64;
      n_inline    — сколько инлайн-скриптов закодировано;
      n_external  — сколько внешних <script src> переведено на динамическую загрузку.
    Если кодировать нечего — возвращает исходный html и (…, 0, 0).

    Зачем кодировать весь <body>, а не только <script>: VK отклоняет файл, если
    видит в разметке «активное содержимое» — тег <script>, инлайн <svg> (проверено
    тестом T9), а также, по аналогии, <canvas>/<audio>/<video> и крупные встроенные
    data:-блобы. Поэтому в статике остаётся только безопасная оболочка (как oden):
    исходный <head> + <body …> + скрытый img. Всё тело едет в base64.

    Прирост веса ≈ +33% (одинарный base64). Непрерывные «прогоны» base64 рвутся
    на куски ≤ _B64_CHUNK (VK режет длинный неразрывный base64-блоб).
    """
    def _chunk(b):
        return "\n".join(b[i:i + _B64_CHUNK] for i in range(0, len(b), _B64_CHUNK))

    def _b64(s):
        return _chunk(base64.b64encode(s.encode('utf-8')).decode('ascii'))

    # 1) Вынимаем ВСЕ скрипты документа (в порядке появления): внешние → 's:url',
    #    инлайн → 'b:<base64>'. Тело документа очищается от тегов <script>.
    scripts = []
    def _take(m):
        attrs, inner = m.group(1), m.group(2)
        srcm = _B64_SRC_RX.search(attrs)
        if srcm:
            scripts.append(("s", srcm.group(1)))
        elif inner.strip():
            scripts.append(("b", inner))
        return ""
    no_scripts = _B64_SCRIPT_RX.sub(_take, html)
    n_inline = sum(1 for k, _ in scripts if k == "b")
    n_external = sum(1 for k, _ in scripts if k == "s")

    # 2) Тело <body> (уже без скриптов) — целиком в 'm:<base64>'.
    bm = re.search(r"(?is)<body([^>]*)>(.*?)</body>", no_scripts)

    items = []
    if bm and bm.group(2).strip():
        items.append("m:" + _b64(bm.group(2)))
    for k, v in scripts:
        items.append(("s:" + v) if k == "s" else ("b:" + _b64(v)))

    if not items:
        return html, 0, 0

    # 3) Payload в data-si: элементы через '|' (нет ни в base64, ни в URL CDN).
    payload = "|".join(items)
    payload_attr = (payload.replace("&", "&amp;").replace('"', "&quot;")
                           .replace("<", "&lt;").replace(">", "&gt;"))

    # Загрузчик: читает data-si и по очереди — 'm:' выставляет как innerHTML тела
    # (возвращает svg/canvas/audio/video/разметку; инлайн onclick= работают),
    # 's:' грузит внешний скрипт по onload-цепочке, 'b:' пересоздаёт инлайн-скрипт
    # (исполняется в ГЛОБАЛЬНОЙ области). Перед atob выбрасывает не-base64 символы
    # (наши переносы), а TextDecoder возвращает UTF-8 (иначе кириллица → кракозябры).
    # Целиком уходит в base64 — function/createElement/'script' фильтр VK не видит.
    loader = (r"var im=document.querySelector('img[data-si]');"
              r"var q=im.getAttribute('data-si').split('|');"
              r"var td=new TextDecoder();"
              r"function D(v){return td.decode(Uint8Array.from("
              r"atob(v.replace(/[^A-Za-z0-9+\/=]/g,'')),"
              r"function(c){return c.charCodeAt(0);}));}"
              r"var i=0;function n(){if(i>=q.length)return;"
              r"var it=q[i++],k=it.charAt(0),v=it.slice(2);"
              r"if(k=='m'){document.body.innerHTML=D(v);n();}"
              r"else if(k=='s'){var s=document.createElement('script');"
              r"s.src=v;s.onload=n;document.body.appendChild(s);}"
              r"else{var s=document.createElement('script');"
              r"s.textContent=D(v);document.body.appendChild(s);n();}}n();")
    loader_b64 = base64.b64encode(loader.encode('utf-8')).decode('ascii')
    # base64 загрузчика тоже дробим: склейка строк '...'+'...' разрывает непрерывный
    # «прогон» (кавычка и + не входят в base64), выражение остаётся валидным и в
    # стиле oden ('Fun'+'ction'). Иначе цельный ~600-симв. блоб режется фильтром VK.
    loader_arg = "+".join("'%s'" % loader_b64[i:i + _B64_CHUNK]
                          for i in range(0, len(loader_b64), _B64_CHUNK))
    onload = "const launch='Fun'+'ction';window[launch](atob(%s))();" % loader_arg
    img = ('<img src="%s" data-si="%s" onload="%s" style="display:none;">'
           % (_B64_GIF, payload_attr, onload))

    # 4) Статика: тот же документ, но содержимое <body> заменено на триггер-img.
    if bm:
        result = no_scripts[:bm.start(2)] + "\n" + img + "\n" + no_scripts[bm.end(2):]
    else:
        idx = no_scripts.lower().rfind("</body>")
        result = (no_scripts[:idx] + img + no_scripts[idx:]) if idx >= 0 else (no_scripts + img)
    return result, n_inline, n_external


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
    # Сначала основной файл, затем .bak (на случай, если основной оказался
    # повреждён/обрезан — например, если процесс убили прямо во время записи).
    for path in (SETTINGS_FILE, SETTINGS_FILE + ".bak"):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            continue
    return {}


def save_settings(settings: dict):
    # Атомарная запись: пишем во временный файл (с fsync), сохраняем предыдущую
    # версию в .bak и подменяем основной через os.replace. Иначе жёсткое
    # завершение процесса (апдейтер делает os._exit) могло обрезать settings.json
    # → при следующем запуске load_settings возвращал {} и ВСЕ настройки
    # (включая папки) сбрасывались к значениям по умолчанию.
    # Защита от затирания: пустой/нестрока-словарь НЕ должен перезаписывать уже
    # сохранённые настройки (иначе разовая ошибка сборки настроек сбрасывала бы
    # папки и прочее к значениям по умолчанию). Пишем только осмысленный словарь.
    try:
        if not settings:
            for p in (SETTINGS_FILE, SETTINGS_FILE + ".bak"):
                if os.path.exists(p) and os.path.getsize(p) > 2:
                    return
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        try:
            if os.path.exists(SETTINGS_FILE):
                os.replace(SETTINGS_FILE, SETTINGS_FILE + ".bak")
        except Exception:
            pass
        os.replace(tmp, SETTINGS_FILE)
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


def url_host(url: str) -> str:
    """Возвращает hostname URL в нижнем регистре ('' если не распарсилось).
    Если схема отсутствует — подставляем https://, чтобы netloc распознался."""
    try:
        from urllib.parse import urlparse
        raw = url if '://' in url else 'https://' + url.lstrip('/')
        return (urlparse(raw).hostname or '').lower()
    except Exception:
        return ''


def host_matches(url: str, *domains: str) -> bool:
    """True, если hostname URL равен одному из domains ИЛИ является его
    поддоменом. Безопасная замена проверки `'domain' in url`, которую легко
    обойти (evil.com/youtube.com, youtube.com.evil.com и т.п.) — CWE-20."""
    host = url_host(url)
    if not host:
        return False
    for d in domains:
        d = d.lower().lstrip('.')
        if host == d or host.endswith('.' + d):
            return True
    return False


def get_cookies_path(url: str) -> str:
    if host_matches(url, 'tiktok.com'):   return COOKIE_PATHS['tiktok']
    if host_matches(url, 'instagram.com', 'fbcdn.net', 'cdninstagram.com'):
        return COOKIE_PATHS['instagram']
    if host_matches(url, 'youtube.com', 'youtu.be'): return COOKIE_PATHS['youtube']
    if host_matches(url, 'bilibili.com', 'b23.tv'): return COOKIE_PATHS['bilibili']
    return COOKIE_PATHS['default']


def _cookie_matches_domain(cookie_path: str, url: str) -> bool:
    """Проверяет, подходит ли файл куки к домену URL.
    Если имя файла содержит название другого сервиса — не подходит."""
    cp = os.path.basename(cookie_path).lower()
    is_ig = host_matches(url, 'instagram.com', 'fbcdn.net', 'cdninstagram.com')
    is_tt = host_matches(url, 'tiktok.com')
    is_yt = host_matches(url, 'youtube.com', 'youtu.be')
    # Instagram/fbcdn с YouTube-куками → не подходит
    if is_ig and 'youtube' in cp: return False
    if is_tt and ('youtube' in cp or 'instagram' in cp): return False
    if is_yt and 'instagram' in cp: return False
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
        is_cdn_host = host_matches(url, 'fbcdn.net', 'cdninstagram.com', 'cdntiktok.com')
        is_video_ext = path.endswith(('.mp4', '.webm', '.mov', '.m4v', '.ts'))
        return is_cdn_host and is_video_ext
    except Exception:
        return False


def download_cdn_direct(url: str, out_dir: str, log_fn=None) -> str:
    """Скачивает прямую CDN-ссылку через requests с нужными заголовками.
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
    with http_get(url, headers=headers, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
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


# ──────────────────────────────────────────────────────────────────────────
#  Kodik resolver — извлечение прямого m3u8 из встроенного плеера Kodik.
#  Работает для animego.online и других сайтов, использующих Kodik
#  (yt-dlp его не поддерживает напрямую).
# ──────────────────────────────────────────────────────────────────────────

# Сайты, которые yt-dlp и так качает напрямую — для них Kodik-резолвер не нужен.
KNOWN_DIRECT_SITES = (
    "youtube.com", "youtu.be", "tiktok.com", "instagram.com", "vk.com", "vk.ru",
    "vkvideo.ru", "vimeo.com", "twitch.tv", "twitter.com", "x.com", "dailymotion.com",
    "reddit.com", "soundcloud.com", "facebook.com", "fb.watch", "ok.ru", "rutube.ru",
    "bilibili.com", "coub.com", "yandex.ru", "pinterest.",
)

# Домены плеера Kodik (меняются со временем — список основных)
_KODIK_HOST_RE = re.compile(
    r'(?:https?:)?//[\w.-]*(?:kodik|aniqit|anivod|kodikplayer)[\w.-]*'
    r'/(?:seria|serial|video|episode)/[^\s"\'<>\\]+', re.I)


def _kodik_decode(src: str) -> str:
    """Декодирует src ссылки Kodik: шифр ROT18 по буквам + base64."""
    out = []
    for ch in src:
        c = ord(ch)
        if 65 <= c <= 90:          # A-Z
            c += 18; c = c if c <= 90 else c - 26
            out.append(chr(c))
        elif 97 <= c <= 122:       # a-z
            c += 18; c = c if c <= 122 else c - 26
            out.append(chr(c))
        else:
            out.append(ch)
    b = "".join(out)
    b += "=" * (-len(b) % 4)       # дополняем паддинг base64
    return base64.b64decode(b).decode("utf-8", "replace")


def is_embed_candidate(url: str) -> bool:
    """True, если для URL имеет смысл пробовать Kodik-резолвер
    (это http(s)-страница не из списка напрямую поддерживаемых сайтов)."""
    u = (url or "").lower()
    return u.startswith("http") and not any(d in u for d in KNOWN_DIRECT_SITES)


def _find_kodik_iframe(page_url: str, session) -> str:
    """Ищет URL Kodik-iframe на странице: прямой iframe/ссылка либо через
    DLE-контроллер (data-params=mod=kodik-player...). Возвращает URL или ''."""
    from urllib.parse import urlparse
    try:
        html = session.get(page_url, timeout=30).text
    except Exception:
        return ""

    # 1) Прямая ссылка/iframe на kodik
    m = _KODIK_HOST_RE.search(html.replace("&amp;", "&"))
    if m:
        u = m.group(0)
        return ("https:" + u) if u.startswith("//") else u

    # 2) DLE XFPlayer: data-params="mod=kodik-player&...&id=N" → controller.php
    m = re.search(r'data-params=["\']([^"\']*mod=kodik-player[^"\']*)["\']', html, re.I)
    if m:
        params = m.group(1).replace("&amp;", "&")
        pu = urlparse(page_url)
        ctl = f"{pu.scheme}://{pu.netloc}/engine/ajax/controller.php?{params}"
        try:
            d = session.get(ctl, headers={"Referer": page_url,
                                          "X-Requested-With": "XMLHttpRequest"},
                            timeout=30).json()
            data = (d.get("data") or "").replace("&amp;", "&")
            if data:
                return ("https:" + data) if data.startswith("//") else data
        except Exception:
            pass
    return ""


def _attr(s: str, name: str) -> str:
    m = re.search(name + r'="([^"]*)"', s)
    return m.group(1) if m else ""


def _parse_kodik_selects(html: str):
    """Разбирает <select>-блоки сериального плеера Kodik.
    Возвращает (translations, episodes):
      translations = [(media_id, media_hash, title), ...]  — озвучки
      episodes     = [(value, data_id, data_hash, title), ...] — серии
    """
    translations, episodes = [], []
    for block in re.findall(r"<select\b[^>]*>(.*?)</select>", html, re.S):
        if "data-media-id" in block:               # озвучки
            for o in re.findall(r"<option\b([^>]*)>", block):
                mid, mh = _attr(o, "data-media-id"), _attr(o, "data-media-hash")
                if mid and mh:
                    # data-media-type (season/serial/video) нужен для корректной
                    # перезагрузки страницы озвучки — раньше был жёстко /serial/.
                    translations.append((mid, mh, _attr(o, "data-title"),
                                         _attr(o, "data-media-type") or "serial"))
        elif "data-serial-id" in block:            # сезоны — пропускаем
            continue
        else:                                       # серии
            for o in re.findall(r"<option\b([^>]*)>", block):
                did, dh = _attr(o, "data-id"), _attr(o, "data-hash")
                if did and dh:
                    episodes.append((_attr(o, "value"), did, dh, _attr(o, "data-title")))
    return translations, episodes


def _selected_option(html: str, kind: str):
    """Возвращает атрибуты выбранного (<option ... selected>) в нужном <select>.
    kind: 'translation' (data-media-id), 'episode' (серии)."""
    for block in re.findall(r"<select\b[^>]*>(.*?)</select>", html, re.S):
        is_tr = "data-media-id" in block
        is_season = (not is_tr) and ("data-serial-id" in block)
        if is_season:
            continue
        if (kind == "translation") != is_tr:
            continue
        m = re.search(r"<option\b([^>]*\bselected\b[^>]*)>", block)
        if m:
            return m.group(1)
    return ""


# ──────────────────────────────────────────────────────────────────────────
#  animego.* — плеер грузится отдельным AJAX (/player/{id} и
#  /player/videos/{episode_id}), статический Kodik-резолвер его не видит.
#  Берём Kodik-провайдера для выбранной серии/озвучки и отдаём в resolve_kodik.
# ──────────────────────────────────────────────────────────────────────────
def _is_animego(url: str) -> bool:
    """True для animego.* (animego.me/.org/.online/.one и т.п.)."""
    return 'animego.' in (url or '').lower()


def is_animego_site(url: str) -> bool:
    """Публичная обёртка над _is_animego (для `from utils import *` в workers)."""
    return _is_animego(url)


def _animego_base(page_url: str) -> str:
    from urllib.parse import urlparse
    pu = urlparse(page_url)
    return f"{pu.scheme}://{pu.netloc}"


def _animego_anime_id(page_url: str, session) -> str:
    """ID аниме для AJAX: из data-ajax-url='/player/N' на странице либо из слага '-N'."""
    try:
        page = session.get(page_url, timeout=30).text
    except Exception:
        page = ""
    m = re.search(r'data-ajax-url="/player/(\d+)"', page)
    if m:
        return m.group(1)
    m = re.search(r'-(\d+)/?(?:[?#].*)?$', page_url)
    return m.group(1) if m else ""


def _animego_player_content(session, base: str, anime_id: str, ref: str,
                            episode_dataid: str = "") -> str:
    """HTML плеера (озвучки×провайдеры). episode_dataid='' = текущая/первая серия."""
    url = (f"{base}/player/videos/{episode_dataid}" if episode_dataid
           else f"{base}/player/{anime_id}")
    try:
        j = session.get(url, headers={"Referer": ref,
                                      "X-Requested-With": "XMLHttpRequest"},
                        timeout=30).json()
        return (j.get("data") or {}).get("content", "") or ""
    except Exception:
        return ""


def _animego_parse(content: str):
    """(episodes, players): episodes={номер: data-episode-id},
    players=[(provider_title, translation_title, player_url), ...]."""
    eps = {}
    for m in re.finditer(r'data-episode-number="(\d+)"[\s\S]*?data-episode="(\d+)"', content):
        eps.setdefault(int(m.group(1)), m.group(2))
    players = []
    for tag in re.findall(r'<button[^>]*data-player="[^"]*"[^>]*>', content):
        u = _attr(tag, "data-player")
        if u:
            players.append((_attr(tag, "data-provider-title"),
                            _attr(tag, "data-translation-title"),
                            u.replace("&amp;", "&")))
    return eps, players


def _animego_kodik_players(players):
    """Только Kodik-провайдеры — их умеет resolve_kodik (AniBoom и пр. не поддержаны)."""
    return [p for p in players if 'kodik' in (p[0] + p[2]).lower()]


def animego_get_info(page_url: str, proxy: str = "") -> dict:
    """Списки озвучек и число серий для animego.* — формат как у kodik_get_info."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    aid = _animego_anime_id(page_url, s)
    if not aid:
        return {}
    content = _animego_player_content(s, _animego_base(page_url), aid, page_url)
    if not content:
        return {}
    eps, players = _animego_parse(content)
    dubs = []
    for p in _animego_kodik_players(players):
        if p[1] and p[1] not in dubs:
            dubs.append(p[1])
    return {"translations": dubs,
            "episodes": (max(eps) if eps else 0),
            "cur_translation": (dubs[0] if dubs else ""),
            "cur_episode": (min(eps) if eps else 1)}


def _animego_resolve_kodik_url(page_url: str, episode=None, translation: str = "",
                               proxy: str = "", log_fn=None) -> str:
    """Kodik-embed для выбранной серии и озвучки на animego.* (или '' если нет)."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    aid = _animego_anime_id(page_url, s)
    if not aid:
        return ""
    base = _animego_base(page_url)
    eps, players = _animego_parse(_animego_player_content(s, base, aid, page_url))
    if episode and eps:
        try:
            epn = int(episode)
        except Exception:
            epn = None
        if epn and epn in eps:
            c2 = _animego_player_content(s, base, aid, page_url, episode_dataid=eps[epn])
            if c2:
                _, players = _animego_parse(c2)
                if log_fn: log_fn(f"animego: серия {epn}")
    kod = _animego_kodik_players(players)
    if not kod:
        if log_fn: log_fn("animego: для этой серии нет Kodik-плеера (доступен только AniBoom/др. — они не поддержаны).")
        return ""
    if translation:
        match = [p for p in kod if translation.lower() in (p[1] or "").lower()]
        if match:
            kod = match
        elif log_fn:
            log_fn(f"animego: озвучка «{translation}» не найдена, беру «{kod[0][1]}».")
    if log_fn: log_fn(f"animego: озвучка «{kod[0][1]}» через Kodik.")
    u = kod[0][2]
    return ("https:" + u) if u.startswith("//") else u


def kodik_get_info(page_url: str, proxy: str = "") -> dict:
    """Возвращает данные Kodik-страницы для выпадашек:
    {'translations': [названия], 'episodes': N,
     'cur_translation': название, 'cur_episode': номер}."""
    if _is_animego(page_url):
        info = animego_get_info(page_url, proxy)
        if info:
            return info
        # AJAX-плеер не отдал данные (другой клон, напр. DLE-сайт animego.online)
        # — проваливаемся в общий Kodik-путь ниже (_find_kodik_iframe видит DLE).
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    iframe = _find_kodik_iframe(page_url, s)
    if not iframe:
        return {}
    try:
        html = s.get(iframe, headers={"Referer": page_url}, timeout=30).text
    except Exception:
        return {}
    translations, episodes = _parse_kodik_selects(html)
    cur_tr = _attr(_selected_option(html, "translation"), "data-title")
    cur_ep_str = _attr(_selected_option(html, "episode"), "value")
    try: cur_ep = int(cur_ep_str)
    except Exception: cur_ep = 0
    return {"translations": [t[2] for t in translations if t[2]],
            "episodes": len(episodes),
            "cur_translation": cur_tr,
            "cur_episode": cur_ep}


def resolve_kodik(page_url: str, want_height: int = 720, proxy: str = "",
                  episode=None, translation: str = "", log_fn=None) -> dict:
    """Полный резолв страницы с плеером Kodik в прямой m3u8.
    episode — номер серии (int) или None = серия по умолчанию.
    translation — подстрока названия озвучки или '' = озвучка по умолчанию.
    Возвращает {'url','referer','height'} или {} если Kodik не найден.
    """
    if _is_animego(page_url):
        ku = _animego_resolve_kodik_url(page_url, episode=episode,
                                        translation=translation, proxy=proxy, log_fn=log_fn)
        if ku:
            return resolve_kodik(ku, want_height=want_height, proxy=proxy, log_fn=log_fn)
        # AJAX-плеер не найден (DLE-клон, напр. animego.online) — не сдаёмся,
        # пробуем универсальный Kodik-резолвер по самой странице (ниже).
        if log_fn: log_fn("animego: AJAX-плеер не найден — пробую обычный Kodik-резолвер страницы.")
    from urllib.parse import urlparse
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}

    iframe = _find_kodik_iframe(page_url, s)
    if not iframe:
        return {}
    if log_fn: log_fn(f"Kodik iframe: {iframe[:80]}")

    base = "https://" + urlparse(iframe).netloc
    referer = base + "/"
    try:
        h = s.get(iframe, headers={"Referer": page_url}, timeout=30).text
    except Exception as e:
        if log_fn: log_fn(f"Kodik: не удалось открыть iframe ({e})")
        return {}

    translations, episodes = _parse_kodik_selects(h)

    # Выбор озвучки: перезагружаем сериал нужного перевода
    if translation and translations:
        tl = translation.strip().lower()
        match = next((t for t in translations if tl in (t[2] or "").lower()), None)
        if match:
            if log_fn: log_fn(f"Kodik: озвучка «{match[2]}»")
            # тип медиа из самой опции (season/serial/video), а не жёстко /serial/
            mtype = (match[3] if len(match) > 3 and match[3] else "serial")
            iframe = f"{base}/{mtype}/{match[0]}/{match[1]}/720p"
            try:
                h = s.get(iframe, headers={"Referer": page_url}, timeout=30).text
                _, episodes = _parse_kodik_selects(h)
            except Exception:
                pass
        elif log_fn:
            avail = ", ".join(t[2] for t in translations if t[2])
            log_fn(f"Kodik: озвучка «{translation}» не найдена. Доступны: {avail}")

    def _post_params():
        """Параметры подписи для POST /ftor. Современный Kodik держит их в
        urlParams = '{json}' (d/d_sign/pd/pd_sign/ref/ref_sign). ВАЖНО: ref в
        этом JSON URL-кодирован — раскодируем, иначе requests закодирует его
        повторно и подпись ref_sign не сойдётся → /ftor 500."""
        from urllib.parse import unquote
        m = re.search(r"urlParams\s*=\s*'([^']+)'", h)
        if m:
            try:
                d = json.loads(m.group(1))
                if d.get("ref"):
                    d["ref"] = unquote(d["ref"])
                return {k: d.get(k, "") for k in
                        ("d", "d_sign", "pd", "pd_sign", "ref", "ref_sign")}
            except Exception:
                pass
        # старый формат: var domain="..."; var d_sign="..."; ...
        def _v(v):
            mm = re.search(r'var\s+' + v + r'\s*=\s*"([^"]*)"', h)
            return mm.group(1) if mm else ""
        return {"d": _v("domain"), "d_sign": _v("d_sign"),
                "pd": _v("pd"), "pd_sign": _v("pd_sign"),
                "ref": _v("ref"), "ref_sign": _v("ref_sign")}

    def _vinfo(k):
        # старый формат: vInfo.type = '...'
        m = re.search(r"vInfo\." + k + r"\s*=\s*'([^']+)'", h)
        if m: return m.group(1)
        # новые форматы Kodik: videoInfo.type = "..."  |  "type":"..."
        for pat in (r"videoInfo\." + k + r"\s*=\s*['\"]([^'\"]+)['\"]",
                    r'[\'"]' + k + r'[\'"]\s*:\s*[\'"]([^\'"]+)[\'"]'):
            m = re.search(pat, h)
            if m: return m.group(1)
        return ""

    vtype, vhash, vid = _vinfo("type"), _vinfo("hash"), _vinfo("id")

    # Выбор серии
    if episode is not None and episodes:
        want = str(int(episode))
        m = (next((e for e in episodes if e[0] == want), None) or
             next((e for e in episodes if (e[3] or "").strip().startswith(want + " ")), None))
        if m:
            vtype, vid, vhash = "seria", m[1], m[2]
            if log_fn: log_fn(f"Kodik: серия {want}")
        elif log_fn:
            log_fn(f"Kodik: серия {want} не найдена (всего {len(episodes)})")

    if not (vtype and vhash and vid):
        if log_fn: log_fn("Kodik: не найдены параметры видео (type/hash/id)")
        return {}

    post = dict(_post_params())
    post.update({"bad_user": "true", "cdn_is_working": "true",
                 "type": vtype, "hash": vhash, "id": vid})
    try:
        j = s.post(base + "/ftor", data=post,
                   headers={"Referer": iframe, "Origin": base,
                            "X-Requested-With": "XMLHttpRequest"},
                   timeout=30).json()
    except Exception as e:
        if log_fn: log_fn(f"Kodik: запрос ссылок не удался ({e})")
        return {}

    qmap = {}
    for q, arr in (j.get("links") or {}).items():
        try:
            src = arr[0]["src"]
            u = src if "//" in src else _kodik_decode(src)
            if u.startswith("//"): u = "https:" + u
            qmap[int(re.sub(r"\D", "", str(q)) or 0)] = u
        except Exception:
            pass
    if not qmap:
        if log_fn: log_fn("Kodik: ссылки не получены")
        return {}

    heights = sorted(qmap)
    fitting = [hh for hh in heights if hh <= want_height]
    chosen = max(fitting) if fitting else max(heights)
    if log_fn:
        log_fn(f"Kodik: качества {heights}, выбрано {chosen}p")
    return {"url": qmap[chosen], "referer": referer, "height": chosen}


def parse_version(s):
    """Извлекает кортеж чисел из строки версии/тега для сравнения.
    'v0.2-beta' → (0, 2);  '0.10 BETA' → (0, 10);  '' → (0,)."""
    nums = re.findall(r'\d+', s or '')
    return tuple(int(n) for n in nums) if nums else (0,)


def default_download_dir() -> str:
    """Папка загрузок пользователя по умолчанию (… \\Downloads).
    Если её нет — домашняя папка."""
    try:
        d = os.path.join(os.path.expanduser("~"), "Downloads")
        if os.path.isdir(d):
            return d
    except Exception:
        pass
    return os.path.expanduser("~")


def clean_url(url: str) -> str:
    if host_matches(url, 'tiktok.com') and '?' in url:
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
        subprocess.run([FFMPEG, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW)
        return True
    except Exception:
        return False


def pretty_audio_codec(name):
    """Человекочитаемое имя аудиокодека для колонки «Битрейт» (слева от цифр).
    ffprobe отдаёт codec_name в нижнем регистре (aac/opus/mp3…) — приводим к
    привычным меткам, незнакомые просто капсим."""
    if not name:
        return ""
    n = str(name).strip().lower()
    table = {
        'aac': 'AAC', 'opus': 'Opus', 'libopus': 'Opus', 'mp3': 'MP3',
        'mp2': 'MP2', 'vorbis': 'Vorbis', 'libvorbis': 'Vorbis',
        'flac': 'FLAC', 'alac': 'ALAC', 'ac3': 'AC3', 'eac3': 'E-AC3',
        'dts': 'DTS', 'wmav1': 'WMA', 'wmav2': 'WMA', 'amr_nb': 'AMR',
        'truehd': 'TrueHD',
    }
    if n in table:
        return table[n]
    if n.startswith('pcm'):
        return 'PCM'
    return n.upper()


def fmt_bitrate_with_codec(codec, br):
    """«AAC 153 кбит/с». Кодек слева от цифр; если кодек неизвестен — только битрейт,
    если битрейт неизвестен — только кодек (или «—»)."""
    c = pretty_audio_codec(codec)
    has_br = bool(br) and br not in ("-", "—")
    if c and has_br:
        return f"{c} {br}"
    if has_br:
        return br
    return c or "—"


def get_media_info(path):
    """Возвращает (duration, bitrate_str, size, audio_bitrate_str, audio_codec).
    Один вызов ffprobe с JSON-выводом — поля именованные, порядок не важен.
    """
    dur = 0.0
    size = 0
    br_str = "-"
    a_br = "-"
    a_codec = None
    try:
        size = os.path.getsize(path)
    except Exception:
        size = 0
    try:
        p = subprocess.run(
            [FFPROBE, "-v", "error",
             "-show_entries",
             "format=duration,bit_rate:stream=bit_rate,sample_rate,channels,bits_per_sample,codec_name",
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
            a_codec = s0.get("codec_name") or None
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
            # Нет тега bit_rate (частый случай для opus и ряда mp4) — считаем по
            # сумме размеров аудиопакетов за длительность: точнее format.bit_rate
            # (тот включает видео) и ВСЕГДА даёт значение, а не прочерк.
            if a_br == "-" and dur > 0:
                try:
                    pk = subprocess.run(
                        [FFPROBE, "-v", "error", "-select_streams", "a:0",
                         "-show_entries", "packet=size", "-of", "csv=p=0", path],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", errors="replace",
                        creationflags=CREATE_NO_WINDOW)
                    total = sum(int(x) for x in pk.stdout.replace(",", " ").split() if x.isdigit())
                    if total > 0:
                        kbps = int(round(total * 8 / dur / 1000))
                        if kbps > 0:
                            a_br = f"{kbps} кбит/с"
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
    return dur, br_str, size, a_br, a_codec


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


def measure_loudness(path, should_stop=None):
    """Сканирует громкость файла. should_stop — необязательный callable: если он
    начинает возвращать True во время сканирования (пользователь нажал «Стоп»),
    процесс ffmpeg убивается и функция возвращает None. Без него — как раньше,
    блокирующий проход. Для длинных файлов (часы) без этого «Стоп» не срабатывал,
    пока полный проход loudnorm не закончится (см. process_media)."""
    try:
        cmd = [FFMPEG, "-hide_banner", "-nostats", "-i", path, "-af", "loudnorm=I=-16:LRA=20:TP=-1.5:print_format=json", "-f", "null", "-"]
        p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
        if should_stop is None:
            stderr = p.communicate()[1] or ""
        else:
            # communicate(timeout=…) короткими тиками: фоновые потоки чтения
            # сами осушают pipe (нет дедлока на длинном файле), а мы между
            # тиками проверяем should_stop() и убиваем ffmpeg при «Стоп».
            stderr = ""
            while True:
                if should_stop():
                    try: p.kill()
                    except Exception: pass
                    try: p.communicate(timeout=2)
                    except Exception: pass
                    return None
                try:
                    stderr = p.communicate(timeout=0.2)[1] or ""
                    break
                except subprocess.TimeoutExpired:
                    continue
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


def rasterize_svg(path, max_dim=2048):
    """Растеризует SVG-файл в PIL.Image (RGBA) через QtSvg. PIL не умеет SVG,
    поэтому рисуем вектор в QImage и переводим в PIL. Возвращает None при ошибке
    или если QtSvg/PIL недоступны."""
    if not Image:
        return None
    try:
        from PyQt6.QtSvg import QSvgRenderer
        from PyQt6.QtCore import QBuffer
    except Exception:
        return None
    try:
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            return None
        size = renderer.defaultSize()
        w, h = size.width(), size.height()
        if w <= 0 or h <= 0:
            w = h = 1024
        # Векторную картинку растеризуем покрупнее, чтобы при объединении она
        # была чёткой (но не больше max_dim по большей стороне).
        scale = max(1.0, 1024 / max(w, h))
        w2, h2 = int(round(w * scale)), int(round(h * scale))
        if max(w2, h2) > max_dim:
            k = max_dim / max(w2, h2)
            w2, h2 = int(round(w2 * k)), int(round(h2 * k))
        qimg = QtGuiImage(w2, h2, QtGuiImage.Format.Format_ARGB32)
        qimg.fill(0)  # прозрачный фон
        p = QPainter(qimg)
        renderer.render(p)
        p.end()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        qimg.save(buf, 'PNG')
        buf.close()
        return Image.open(io.BytesIO(bytes(ba))).convert('RGBA')
    except Exception:
        return None


def open_image_any(path):
    """Открывает изображение как PIL.Image, поддерживая в т.ч. SVG (через
    растеризацию QtSvg). Возвращает PIL.Image. Бросает исключение, как Image.open,
    если формат не распознан."""
    if os.path.splitext(path)[1].lower() == '.svg':
        im = rasterize_svg(path)
        if im is None:
            raise ValueError(f"Не удалось растеризовать SVG: {path}")
        return im
    return Image.open(path)


def load_pixmap_any(path, max_dim=1024):
    """QPixmap из любого файла, включая SVG (растеризуется через QtSvg).
    Пустой QPixmap при ошибке."""
    if os.path.splitext(path)[1].lower() == '.svg':
        try:
            from PyQt6.QtSvg import QSvgRenderer
            renderer = QSvgRenderer(path)
            if renderer.isValid():
                size = renderer.defaultSize()
                w, h = size.width(), size.height()
                if w <= 0 or h <= 0:
                    w = h = max_dim
                scale = min(1.0, max_dim / max(w, h))
                qimg = QtGuiImage(int(w * scale) or 1, int(h * scale) or 1,
                                  QtGuiImage.Format.Format_ARGB32)
                qimg.fill(0)
                p = QPainter(qimg)
                renderer.render(p)
                p.end()
                return QPixmap.fromImage(qimg)
        except Exception:
            pass
        return QPixmap()
    # Сначала пробуем штатный загрузчик Qt.
    pix = QPixmap(path)
    if not pix.isNull():
        return pix
    # Qt не открыл (нет плагина — частый случай для avif/heic): пробуем через
    # Pillow (avif/heic регистрируются pillow-heif) и переводим в QPixmap.
    if Image:
        try:
            with Image.open(path) as im:
                if ImageOps:
                    im = ImageOps.exif_transpose(im)
                im = im.convert("RGBA")
                bio = io.BytesIO(); im.save(bio, format="PNG")
                p2 = QPixmap()
                if p2.loadFromData(QByteArray(bio.getvalue())):
                    return p2
        except Exception:
            pass
    # Последний резерв — bundled ffmpeg. Критично для сравнения «исходник/
    # результат»: результат у нас обычно AVIF, а в собранном .exe ни Qt, ни
    # Pillow могут не уметь его декодировать (нет плагина/кодека). ffmpeg с
    # libaom в комплекте точно открывает AVIF/HEIC (он же их и создаёт), поэтому
    # рендерим один кадр в PNG и грузим его — иначе панель «Результат» пустая.
    try:
        tmp = os.path.join(TEMP_DIR, f"ym_pix_{uuid.uuid4().hex}.png")
        cmd = [FFMPEG, "-y", "-i", path, "-frames:v", "1"]
        if max_dim:
            cmd += ["-vf", f"scale='min({int(max_dim)},iw)':-1"]
        cmd.append(tmp)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW, timeout=20)
        if os.path.exists(tmp):
            p3 = QPixmap(tmp)
            try: os.remove(tmp)
            except Exception: pass
            if not p3.isNull():
                return p3
    except Exception:
        pass
    return pix


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


def move_to_trash(path):
    """Отправляет файл в Корзину (Windows) БЕЗ системного диалога подтверждения.
    Возвращает True при успехе. Реализовано через WinAPI SHFileOperationW с
    флагом FOF_ALLOWUNDO — это кладёт файл в Корзину (откуда его можно вернуть),
    а не удаляет безвозвратно; стороннюю зависимость (send2trash) не тянем."""
    try:
        path = os.path.abspath(path)
    except Exception:
        return False
    if not os.path.exists(path):
        return True
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes

            class _SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_uint16),          # FILEOP_FLAGS = WORD
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", wintypes.LPCWSTR),
                ]

            FO_DELETE = 0x0003
            FOF_SILENT = 0x0004           # без индикатора прогресса
            FOF_NOCONFIRMATION = 0x0010   # без вопросов «вы уверены?»
            FOF_ALLOWUNDO = 0x0040        # → Корзина, а не безвозвратно
            FOF_NOERRORUI = 0x0400        # без окон об ошибках

            op = _SHFILEOPSTRUCTW()
            op.hwnd = None
            op.wFunc = FO_DELETE
            # pFrom — список путей, оканчивающийся ДВОЙНЫМ NUL.
            op.pFrom = path + '\x00\x00'
            op.pTo = None
            op.fFlags = (FOF_ALLOWUNDO | FOF_NOCONFIRMATION
                         | FOF_SILENT | FOF_NOERRORUI)
            shell32 = ctypes.windll.shell32
            shell32.SHFileOperationW.argtypes = [ctypes.c_void_p]
            shell32.SHFileOperationW.restype = ctypes.c_int
            res = shell32.SHFileOperationW(ctypes.byref(op))
            return res == 0 and not op.fAnyOperationsAborted
        except Exception:
            return False
    # Не-Windows: системной Корзины под рукой нет — обычное удаление.
    try:
        os.remove(path)
        return True
    except Exception:
        return False


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
