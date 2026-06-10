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
    if 'bilibili.com' in u or 'b23.tv' in u: return COOKIE_PATHS['bilibili']
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
    from urllib.parse import urlparse
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
        subprocess.run([FFMPEG, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW)
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
