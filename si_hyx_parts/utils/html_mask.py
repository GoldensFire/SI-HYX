# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Маскировка HTML/JS для VK: полная и облегчённая. Public namespace: utils."""
import utils as _api


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
        return "\n".join(b[i:i + _api._B64_CHUNK] for i in range(0, len(b), _api._B64_CHUNK))

    def _b64(s):
        return _chunk(_api.base64.b64encode(s.encode('utf-8')).decode('ascii'))

    # 1) Вынимаем ВСЕ скрипты документа (в порядке появления): внешние → 's:url',
    #    инлайн → 'b:<base64>'. Тело документа очищается от тегов <script>.
    scripts = []
    def _take(m):
        attrs, inner = m.group(1), m.group(2)
        srcm = _api._B64_SRC_RX.search(attrs)
        if srcm:
            scripts.append(("s", srcm.group(1)))
        elif inner.strip():
            scripts.append(("b", inner))
        return ""
    no_scripts = _api._B64_SCRIPT_RX.sub(_take, html)
    n_inline = sum(1 for k, _ in scripts if k == "b")
    n_external = sum(1 for k, _ in scripts if k == "s")

    # 2) Тело <body> (уже без скриптов) — целиком в 'm:<base64>'.
    bm = _api.re.search(r"(?is)<body([^>]*)>(.*?)</body>", no_scripts)

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
    loader_b64 = _api.base64.b64encode(loader.encode('utf-8')).decode('ascii')
    # base64 загрузчика тоже дробим: склейка строк '...'+'...' разрывает непрерывный
    # «прогон» (кавычка и + не входят в base64), выражение остаётся валидным и в
    # стиле oden ('Fun'+'ction'). Иначе цельный ~600-симв. блоб режется фильтром VK.
    loader_arg = "+".join("'%s'" % loader_b64[i:i + _api._B64_CHUNK]
                          for i in range(0, len(loader_b64), _api._B64_CHUNK))
    onload = "const launch='Fun'+'ction';window[launch](atob(%s))();" % loader_arg
    img = ('<img src="%s" data-si="%s" onload="%s" style="display:none;">'
           % (_api._B64_GIF, payload_attr, onload))

    # 4) Статика: тот же документ, но содержимое <body> заменено на триггер-img.
    if bm:
        result = no_scripts[:bm.start(2)] + "\n" + img + "\n" + no_scripts[bm.end(2):]
    else:
        idx = no_scripts.lower().rfind("</body>")
        result = (no_scripts[:idx] + img + no_scripts[idx:]) if idx >= 0 else (no_scripts + img)
    return result, n_inline, n_external

mask_html_js.__module__ = _api.__name__
_api.mask_html_js = mask_html_js


def _lite_hoist_assets(code: str, assets: list) -> str:
    """Выносит крупные ассет-литералы из инлайн-скрипта в общий список assets,
    заменяя каждый на глобальную ссылку __SI_Ak (k = индекс в assets). Возвращает
    slimmed-код скрипта. Сами ассеты кладутся в data-si один раз (без повторного
    base64), а loader объявляет их как window.__SI_Ak до запуска скриптов."""
    def _repl(m):
        tok = m.group(0)
        if tok[0] in "\"'":                          # строковый литерал (не комментарий)
            inner = tok[1:-1]
            if len(inner) >= _api._LITE_HOIST_MIN and _api._LITE_ASSET_INNER_RX.fullmatch(inner):
                idx = len(assets)
                assets.append(inner)                 # исходное значение (сырой b64 / data:)
                return "__SI_A%d" % idx
        return tok                                   # комментарии и обычные строки — как есть
    # _LITE_STRIP_RX матчит комментарии и строковые литералы целиком, поэтому не
    # заденем base64 внутри комментария или вложенные кавычки.
    return _api._LITE_STRIP_RX.sub(_repl, code)

_lite_hoist_assets.__module__ = _api.__name__
_api._lite_hoist_assets = _lite_hoist_assets


def mask_html_js_lite(html: str):
    """Лёгкая маскировка под VK: тот же скрытный envelope, что mask_html_js
    (в открытом HTML НЕТ <script>/eval/function — всё в data-si, запуск через
    onload+'Fun'+'ction'), но крупные ассеты кодируются ОДИН раз, а не дважды
    (выносятся из скриптов в отдельные data-si элементы) — отсюда меньший размер.

    Возвращает (masked_html, n_inline, n_external) — как mask_html_js. Если
    прятать нечего — (html, 0, 0).
    """
    def _chunk(b):
        return "\n".join(b[i:i + _api._B64_CHUNK] for i in range(0, len(b), _api._B64_CHUNK))

    def _b64(s):
        return _chunk(_api.base64.b64encode(s.encode('utf-8')).decode('ascii'))

    # 1) Скрипты вынимаем как в старом методе, но из инлайновых сначала выносим
    #    крупные ассет-литералы (в общий assets → отдельные 'r'-элементы).
    assets = []
    scripts = []
    def _take(m):
        attrs, inner = m.group(1), m.group(2)
        srcm = _api._B64_SRC_RX.search(attrs)
        if srcm:
            scripts.append(("s", srcm.group(1)))
        elif inner.strip():
            scripts.append(("b", _api._lite_hoist_assets(inner, assets)))
        return ""
    no_scripts = _api._B64_SCRIPT_RX.sub(_take, html)
    n_inline = sum(1 for k, _ in scripts if k == "b")
    n_external = sum(1 for k, _ in scripts if k == "s")
    if not scripts:
        return html, 0, 0            # нет скриптов — прятать нечего, VK и так примет

    # 2) Тело <body> без скриптов → 'm'; ассеты → 'r' (по разу, БЕЗ повторного
    #    base64) ДО скриптов; скрипты → 'b'/'s'.
    bm = _api.re.search(r"(?is)<body([^>]*)>(.*?)</body>", no_scripts)
    items = []
    if bm and bm.group(2).strip():
        items.append("m:" + _b64(bm.group(2)))
    for idx, a in enumerate(assets):
        items.append("r:%d:%s" % (idx, _chunk(a)))
    for k, v in scripts:
        items.append(("s:" + v) if k == "s" else ("b:" + _b64(v)))
    if not items:
        return html, 0, 0

    # 3) Payload в data-si (элементы через '|', которого нет ни в base64, ни в URL).
    payload = "|".join(items)
    payload_attr = (payload.replace("&", "&amp;").replace('"', "&quot;")
                           .replace("<", "&lt;").replace(">", "&gt;"))

    loader_b64 = _api.base64.b64encode(_api._LITE_LOADER.encode('utf-8')).decode('ascii')
    # base64 загрузчика дробим склейкой '...'+'...' (как oden) — иначе цельный
    # ~700-симв. блоб в onload режется фильтром VK.
    loader_arg = "+".join("'%s'" % loader_b64[i:i + _api._B64_CHUNK]
                          for i in range(0, len(loader_b64), _api._B64_CHUNK))
    onload = "const launch='Fun'+'ction';window[launch](atob(%s))();" % loader_arg
    img = ('<img src="%s" data-si="%s" onload="%s" style="display:none;">'
           % (_api._B64_GIF, payload_attr, onload))

    # 4) Статика: тело <body> заменяется на скрытый триггер-img.
    if bm:
        result = no_scripts[:bm.start(2)] + "\n" + img + "\n" + no_scripts[bm.end(2):]
    else:
        idx = no_scripts.lower().rfind("</body>")
        result = (no_scripts[:idx] + img + no_scripts[idx:]) if idx >= 0 else (no_scripts + img)
    return result, n_inline, n_external

mask_html_js_lite.__module__ = _api.__name__
_api.mask_html_js_lite = mask_html_js_lite


def ensure_deno_on_path():
    """yt-dlp использует Deno для решения YouTube n-challenge. Без него
    YouTube отдаёт только превью ('Only images are available').
    Приоритет поиска: bundled (рядом с программой / bin) → системный PATH →
    стандартные места установки (winget / .deno). Найденный каталог
    добавляется в PATH, чтобы yt-dlp его нашёл."""
    exe_name = "deno.exe" if _api.IS_WIN else "deno"

    def _use(d):
        if d and _api.os.path.isfile(_api.os.path.join(d, exe_name)):
            _api.os.environ["PATH"] = d + _api.os.pathsep + _api.os.environ.get("PATH", "")
            return True
        return False

    try:
        # 1) Рядом с программой (для сборки .exe с bundled-deno): _MEIPASS,
        #    папка exe/скрипта и их подпапка bin — в приоритете над системным.
        roots = []
        base = getattr(_api.sys, "_MEIPASS", None)
        if base:
            roots.append(base)
        roots.append(_api.os.path.dirname(_api.os.path.abspath(_api.sys.argv[0] or ".")))
        roots.append(_api.os.path.dirname(_api.os.path.abspath(_api.__file__)))
        for r in roots:
            if _use(r) or _use(_api.os.path.join(r, "bin")):
                return True

        # 2) Уже доступен в системном PATH
        if _api.shutil.which("deno"):
            return True

        # 3) Стандартные места установки (winget / .deno)
        sys_cands = []
        la = _api.os.getenv("LOCALAPPDATA")
        home = _api.os.path.expanduser("~")
        if la:
            sys_cands.append(_api.os.path.join(la, "Microsoft", "WinGet", "Links"))
            try:
                import glob as _glob
                sys_cands += [
                    _api.os.path.dirname(p) for p in
                    _glob.glob(_api.os.path.join(la, "Microsoft", "WinGet", "Packages",
                                            "DenoLand.Deno_*", "deno.exe"))
                ]
            except Exception:
                pass
        sys_cands.append(_api.os.path.join(home, ".deno", "bin"))
        for d in sys_cands:
            if _use(d):
                return True
    except Exception:
        pass
    return False

ensure_deno_on_path.__module__ = _api.__name__
_api.ensure_deno_on_path = ensure_deno_on_path
