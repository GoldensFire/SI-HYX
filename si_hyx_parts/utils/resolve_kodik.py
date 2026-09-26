# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""resolve_kodik. Public namespace: utils."""
import utils as _api


def resolve_kodik(page_url: str, want_height: int = 720, proxy: str = "",
                  episode=None, translation: str = "", log_fn=None) -> dict:
    """Полный резолв страницы с плеером Kodik в прямой m3u8.
    episode — номер серии (int) или None = серия по умолчанию.
    translation — подстрока названия озвучки или '' = озвучка по умолчанию.
    Возвращает {'url','referer','height'} или {} если Kodik не найден.
    """
    if _api._is_animego(page_url):
        ku = _api._animego_resolve_kodik_url(page_url, episode=episode,
                                        translation=translation, proxy=proxy, log_fn=log_fn)
        if ku:
            return _api.resolve_kodik(ku, want_height=want_height, proxy=proxy, log_fn=log_fn)
        # AJAX-плеер не найден (DLE-клон, напр. animego.online) — не сдаёмся,
        # пробуем универсальный Kodik-резолвер по самой странице (ниже).
        if log_fn: log_fn("animego: AJAX-плеер не найден — пробую обычный Kodik-резолвер страницы.")
    from urllib.parse import urlparse
    s = _api._requests().Session()
    s.headers.update({"User-Agent": _api.USER_AGENT})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}

    iframe = _api._find_kodik_iframe(page_url, s)
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

    translations, episodes = _api._parse_kodik_selects(h)

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
                _, episodes = _api._parse_kodik_selects(h)
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
        m = _api.re.search(r"urlParams\s*=\s*'([^']+)'", h)
        if m:
            try:
                d = _api.json.loads(m.group(1))
                if d.get("ref"):
                    d["ref"] = unquote(d["ref"])
                return {k: d.get(k, "") for k in
                        ("d", "d_sign", "pd", "pd_sign", "ref", "ref_sign")}
            except Exception:
                pass
        # старый формат: var domain="..."; var d_sign="..."; ...
        def _v(v):
            mm = _api.re.search(r'var\s+' + v + r'\s*=\s*"([^"]*)"', h)
            return mm.group(1) if mm else ""
        return {"d": _v("domain"), "d_sign": _v("d_sign"),
                "pd": _v("pd"), "pd_sign": _v("pd_sign"),
                "ref": _v("ref"), "ref_sign": _v("ref_sign")}

    def _vinfo(k):
        # старый формат: vInfo.type = '...'
        m = _api.re.search(r"vInfo\." + k + r"\s*=\s*'([^']+)'", h)
        if m: return m.group(1)
        # новые форматы Kodik: videoInfo.type = "..."  |  "type":"..."
        for pat in (r"videoInfo\." + k + r"\s*=\s*['\"]([^'\"]+)['\"]",
                    r'[\'"]' + k + r'[\'"]\s*:\s*[\'"]([^\'"]+)[\'"]'):
            m = _api.re.search(pat, h)
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
            u = src if "//" in src else _api._kodik_decode(src)
            if u.startswith("//"): u = "https:" + u
            qmap[int(_api.re.sub(r"\D", "", str(q)) or 0)] = u
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

resolve_kodik.__module__ = _api.__name__
_api.resolve_kodik = resolve_kodik

def parse_version(s):
    """Извлекает кортеж чисел из строки версии/тега для сравнения.
    'v0.2-beta' → (0, 2);  '0.10 BETA' → (0, 10);  '' → (0,)."""
    nums = _api.re.findall(r'\d+', s or '')
    return tuple(int(n) for n in nums) if nums else (0,)

parse_version.__module__ = _api.__name__
_api.parse_version = parse_version

def default_download_dir() -> str:
    """Папка загрузок пользователя по умолчанию (… \\Downloads).
    Если её нет — домашняя папка."""
    try:
        d = _api.os.path.join(_api.os.path.expanduser("~"), "Downloads")
        if _api.os.path.isdir(d):
            return d
    except Exception:
        pass
    return _api.os.path.expanduser("~")

default_download_dir.__module__ = _api.__name__
_api.default_download_dir = default_download_dir

def clean_url(url: str) -> str:
    if _api.host_matches(url, 'tiktok.com') and '?' in url:
        return url.split('?')[0]
    # Прямые CDN-ссылки на видеофайлы (Instagram, Facebook и др.):
    # yt-dlp не может извлечь title/id из CDN URL → имя файла содержит
    # недопустимые символы Windows (?&=). Стрипаем query-параметры.
    if '?' in url:
        path = url.split('?')[0]
        if path.lower().endswith(('.mp4', '.webm', '.mov', '.m4v', '.avi', '.mkv')):
            return path
    return url

clean_url.__module__ = _api.__name__
_api.clean_url = clean_url

def check_ffmpeg():
    try:
        _api.subprocess.run([_api.FFMPEG, "-version"], stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                       creationflags=_api.CREATE_NO_WINDOW)
        return True
    except Exception:
        return False

check_ffmpeg.__module__ = _api.__name__
_api.check_ffmpeg = check_ffmpeg

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

pretty_audio_codec.__module__ = _api.__name__
_api.pretty_audio_codec = pretty_audio_codec

def fmt_bitrate_with_codec(codec, br):
    """«AAC 153 кбит/с». Кодек слева от цифр; если кодек неизвестен — только битрейт,
    если битрейт неизвестен — только кодек (или «—»)."""
    c = _api.pretty_audio_codec(codec)
    has_br = bool(br) and br not in ("-", "—")
    if c and has_br:
        return f"{c} {br}"
    if has_br:
        return br
    return c or "—"

fmt_bitrate_with_codec.__module__ = _api.__name__
_api.fmt_bitrate_with_codec = fmt_bitrate_with_codec
