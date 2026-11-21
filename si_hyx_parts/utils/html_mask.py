# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Маскировка HTML/JS для VK: полная и облегчённая. Public namespace: utils."""
import utils as _api


def _parse_script_attrs(attrs: str) -> list:
    """Разбирает атрибуты открывающего тега <script …> в список [имя, значение]."""
    out = []
    for m in _api._B64_ATTR_RX.finditer(attrs or ""):
        name = m.group(1).lower()
        raw = m.group(2)
        if raw is None:
            raw = m.group(3)
        if raw is None:
            raw = m.group(4)
        val = _api._html.unescape(raw) if raw is not None else ""
        out.append([name, val])
    return out


_parse_script_attrs.__module__ = _api.__name__
_api._parse_script_attrs = _parse_script_attrs


def _is_js_script_type(type_val: str) -> bool:
    """True — браузер исполняет <script> как JS (включая type="module").
    False — блок данных (text/plain, application/json, x-shader/… и т. п.)."""
    mime = (type_val or "").split(";", 1)[0].strip().lower()
    return mime in _api._B64_JS_TYPES


_is_js_script_type.__module__ = _api.__name__
_api._is_js_script_type = _is_js_script_type


def _chunk_b64(b: str) -> str:
    step = _api._B64_CHUNK
    return "\n".join(b[i:i + step] for i in range(0, len(b), step))


def _encode_b64(s: str) -> str:
    return _chunk_b64(_api.base64.b64encode(s.encode("utf-8")).decode("ascii"))


def _encode_attrs(attrs: list) -> str:
    return _encode_b64(_api.json.dumps(attrs, ensure_ascii=False, separators=(",", ":")))


def _is_pure_b64_data(inner: str) -> bool:
    stripped = (inner or "").strip()
    if not stripped or not _api._LITE_PURE_B64_RX.fullmatch(stripped):
        return False
    cleaned = _api._LITE_WS_RX.sub("", stripped)
    return len(cleaned) >= _api._LITE_HOIST_MIN


def _extract_scripts(html: str, hoist_assets: bool):
    """Вынимает все <script> документа, разделяя блоки данных и исполняемые
    скрипты и сохраняя атрибуты (id, type, data-*, crossorigin…)."""
    data_scripts = []
    exec_scripts = []
    assets = []

    def _take(m):
        attrs_raw, inner = m.group(1), m.group(2)
        attrs = _parse_script_attrs(attrs_raw)
        src_val = next((v for k, v in attrs if k == "src" and v), None)
        if src_val is not None:
            extra = [[k, v] for k, v in attrs if k != "src"]
            exec_scripts.append(("s", src_val, extra))
            return ""
        type_val = next((v for k, v in attrs if k == "type"), "")
        if not _is_js_script_type(type_val):
            # Скрипт-данные (text/plain, application/json и т. п.): сохраняем
            # даже пустой, если у него есть атрибуты (напр. id).
            if inner.strip() or attrs:
                data_scripts.append((inner, attrs))
        elif inner.strip():
            body = _api._lite_hoist_assets(inner, assets) if hoist_assets else inner
            exec_scripts.append(("b", body, attrs))
        return ""

    no_scripts = _api._B64_SCRIPT_RX.sub(_take, html)
    n_inline = len(data_scripts) + sum(1 for k, _, _ in exec_scripts if k == "b")
    n_external = sum(1 for k, _, _ in exec_scripts if k == "s")
    return no_scripts, data_scripts, exec_scripts, assets, n_inline, n_external


def _build_masked_html(no_scripts: str, items: list, loader: str) -> str:
    """Упаковывает items в data-si и заменяет содержимое <body> на триггер-img."""
    bm = _api.re.search(r"(?is)<body([^>]*)>(.*?)</body>", no_scripts)
    payload = "|".join(items)
    payload_attr = (payload.replace("&", "&amp;").replace('"', "&quot;")
                           .replace("<", "&lt;").replace(">", "&gt;"))
    loader_b64 = _api.base64.b64encode(loader.encode("utf-8")).decode("ascii")
    # base64 загрузчика дробим склейкой '...'+'...' (как oden) — иначе цельный
    # длинный блоб в onload режется фильтром VK.
    loader_arg = "+".join("'%s'" % loader_b64[i:i + _api._B64_CHUNK]
                          for i in range(0, len(loader_b64), _api._B64_CHUNK))
    onload = "const launch='Fun'+'ction';window[launch](atob(%s))();" % loader_arg
    img = ('<img src="%s" data-si="%s" onload="%s" style="display:none;">'
           % (_api._B64_GIF, payload_attr, onload))
    if bm:
        return no_scripts[:bm.start(2)] + "\n" + img + "\n" + no_scripts[bm.end(2):]
    idx = no_scripts.lower().rfind("</body>")
    return (no_scripts[:idx] + img + no_scripts[idx:]) if idx >= 0 else (no_scripts + img)


def mask_html_js(html: str):
    """Прячет под VK всё «активное» содержимое HTML.

    Возвращает (masked_html, n_inline, n_external):
      masked_html — документ, где всё тело <body> заменено одним триггер-img,
                    а реальное содержимое лежит в data-si одинарным base64;
      n_inline    — сколько инлайн-скриптов (включая блоки данных) закодировано;
      n_external  — сколько внешних <script src> переведено на динамическую загрузку.
    Если кодировать нечего — возвращает исходный html и (…, 0, 0).

    Атрибуты тегов <script> (id, type, data-*, crossorigin…) сохраняются;
    скрипты-данные (type="text/plain", "application/json" и т. п.) восстанавливаются
    в DOM до запуска исполняемого JS и не исполняются как код.
    """
    no_scripts, data_scripts, exec_scripts, _, n_inline, n_external = _extract_scripts(
        html, hoist_assets=False)

    bm = _api.re.search(r"(?is)<body([^>]*)>(.*?)</body>", no_scripts)
    items = []
    if bm and bm.group(2).strip():
        items.append("m:" + _encode_b64(bm.group(2)))
    for inner, attrs in data_scripts:
        items.append("a:%s:%s" % (_encode_attrs(attrs), _encode_b64(inner)))
    for kind, val, attrs in exec_scripts:
        if kind == "s":
            url = val.replace("|", "%7C")
            items.append(("e:%s:%s" % (_encode_attrs(attrs), url)) if attrs else ("s:" + url))
        else:
            b64 = _encode_b64(val)
            items.append(("a:%s:%s" % (_encode_attrs(attrs), b64)) if attrs else ("b:" + b64))

    if not items:
        return html, 0, 0

    return _build_masked_html(no_scripts, items, _api._FULL_LOADER), n_inline, n_external


mask_html_js.__module__ = _api.__name__
_api.mask_html_js = mask_html_js


def _prev_word(code: str, end_idx: int):
    """Возвращает (word, word_start) идентификатора, кончающегося в end_idx."""
    k = end_idx
    while k >= 0 and (code[k].isalnum() or code[k] in "_$"):
        k -= 1
    return code[k + 1:end_idx + 1], k + 1


def _js_can_start_regex(code: str, pos: int) -> bool:
    """Может ли символ '/' в позиции pos начинать regexp-литерал в JS."""
    k = pos - 1
    while k >= 0 and code[k] in " \t\r\n":
        k -= 1
    if k < 0:
        return True
    ch = code[k]
    if ch in "([{:;,=!?&|^~*%<>":
        return True
    if ch in "+-":
        # После бинарного/унарного + или - идёт выражение (regexp возможен),
        # после постфиксного ++ / -- идёт деление.
        return not (k > 0 and code[k - 1] == ch)
    if ch.isalnum() or ch in "_$":
        word, wstart = _prev_word(code, k)
        if word in _api._LITE_REGEX_PREV_KW:
            p = wstart - 1
            while p >= 0 and code[p] in " \t\r\n":
                p -= 1
            return p < 0 or code[p] != "."
        return False
    return False


def _is_object_key(code: str, start: int, end: int) -> bool:
    """True, если строковый литерал в [start:end] может быть ключом объекта
    ({"...": val} или деструктуризация). Тернарник (cond ? "..." : x) — False."""
    n = len(code)
    j = end
    while j < n and code[j] in " \t\r\n":
        j += 1
    if j < n and code[j] == ":":
        k = start - 1
        while k >= 0 and code[k] in " \t\r\n":
            k -= 1
        if k < 0 or code[k] != "?":
            return True
    return False


def _is_tagged_template(code: str, start: int) -> bool:
    """True, если шаблонной строке в позиции start предшествует тег-функция."""
    k = start - 1
    while k >= 0 and code[k] in " \t\r\n":
        k -= 1
    if k < 0:
        return False
    ch = code[k]
    if ch in ")]}":
        return True
    if ch.isalnum() or ch in "_$":
        word, wstart = _prev_word(code, k)
        if word in _api._LITE_REGEX_PREV_KW:
            p = wstart - 1
            while p >= 0 and code[p] in " \t\r\n":
                p -= 1
            return p >= 0 and code[p] == "."
        return True
    return False


def _lite_hoist_assets(code: str, assets: list) -> str:
    """Выносит крупные ассет-литералы из инлайн-скрипта в общий список assets,
    заменяя каждый на глобальную ссылку __SI_Ak (k = индекс в assets).

    Сканирует JS с учётом комментариев, строк, шаблонных строк (включая ${…})
    и regexp-литералов (/…/), а также пропускает ключи объектов и tagged
    templates, чтобы не сломать валидный код."""
    n = len(code)
    out = []
    scan = _api._LITE_SCAN_RX
    regex_rx = _api._LITE_REGEX_RX
    tpl_rx = _api._LITE_TPL_CHUNK_RX
    asset_rx = _api._LITE_ASSET_INNER_RX
    min_len = _api._LITE_HOIST_MIN

    def _try_hoist(start: int, end: int, inner: str, is_tpl: bool) -> bool:
        if len(inner) < min_len or not asset_rx.fullmatch(inner):
            return False
        if _is_object_key(code, start, end):
            return False
        if is_tpl and _is_tagged_template(code, start):
            return False
        idx = len(assets)
        assets.append(inner)
        out.append("__SI_A%d" % idx)
        return True

    def _scan_expr_until_rbrace(pos: int) -> int:
        """Сканирует JS внутри ${…} до закрывающей '}', корректно проходя
        вложенные блоки, строки, регулярки и шаблоны."""
        depth = 1
        while pos < n and depth > 0:
            m = scan.search(code, pos)
            next_special = m.start() if m else n
            # Просматриваем фигурные скобки в «чистом» коде до следующего токена.
            seg_pos = pos
            while seg_pos < next_special:
                ch = code[seg_pos]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        out.append(code[pos:seg_pos + 1])
                        return seg_pos + 1
                seg_pos += 1
            if not m:
                out.append(code[pos:n])
                return n
            out.append(code[pos:next_special])
            pos = _handle_token(m)
        return pos

    def _handle_token(m) -> int:
        tok = m.group(0)
        start, end = m.start(), m.end()
        ch = tok[0]
        if ch in "\"'":
            if not _try_hoist(start, end, tok[1:-1], is_tpl=False):
                out.append(tok)
            return end
        if ch == "/":
            if len(tok) > 1:  # комментарий // или /* */
                out.append(tok)
                return end
            if _js_can_start_regex(code, start):
                rm = regex_rx.match(code, start)
                if rm:
                    out.append(rm.group(0))
                    return rm.end()
            out.append("/")
            return end
        # Шаблонная строка `…`
        cm = tpl_rx.match(code, end)
        c_end = cm.end() if cm else end
        if c_end < n and code[c_end] == "`":
            tpl_end = c_end + 1
            if not _try_hoist(start, tpl_end, code[end:c_end], is_tpl=True):
                out.append(code[start:tpl_end])
            return tpl_end
        # Шаблон с интерполяцией ${…} — проходим части и вложенные выражения.
        out.append(code[start:c_end])
        pos = c_end
        while pos < n:
            if code[pos] == "`":
                out.append("`")
                return pos + 1
            if code[pos:pos + 2] == "${":
                out.append("${")
                pos = _scan_expr_until_rbrace(pos + 2)
                cm2 = tpl_rx.match(code, pos)
                c2_end = cm2.end() if cm2 else pos
                out.append(code[pos:c2_end])
                pos = c2_end
            else:
                out.append(code[pos])
                pos += 1
        return pos

    pos = 0
    while pos < n:
        m = scan.search(code, pos)
        if not m:
            out.append(code[pos:])
            break
        out.append(code[pos:m.start()])
        pos = _handle_token(m)
    return "".join(out)


_lite_hoist_assets.__module__ = _api.__name__
_api._lite_hoist_assets = _lite_hoist_assets


def mask_html_js_lite(html: str):
    """Лёгкая маскировка под VK: тот же скрытный envelope, что mask_html_js
    (в открытом HTML НЕТ <script>/eval/function — всё в data-si, запуск через
    onload+'Fun'+'ction'), но крупные base64-ассеты в скриптах и data-скриптах
    кодируются ОДИН раз, а не дважды — отсюда меньший размер.

    Возвращает (masked_html, n_inline, n_external) — как mask_html_js. Если
    прятать нечего — (html, 0, 0).
    """
    no_scripts, data_scripts, exec_scripts, assets, n_inline, n_external = _extract_scripts(
        html, hoist_assets=True)
    if not data_scripts and not exec_scripts:
        return html, 0, 0            # нет скриптов — прятать нечего, VK и так примет

    bm = _api.re.search(r"(?is)<body([^>]*)>(.*?)</body>", no_scripts)
    items = []
    if bm and bm.group(2).strip():
        items.append("m:" + _encode_b64(bm.group(2)))
    for inner, attrs in data_scripts:
        if _is_pure_b64_data(inner):
            raw_b64 = _api._LITE_WS_RX.sub("", inner)
            items.append("d:%s:%s" % (_encode_attrs(attrs), _chunk_b64(raw_b64)))
        else:
            items.append("a:%s:%s" % (_encode_attrs(attrs), _encode_b64(inner)))
    for idx, a in enumerate(assets):
        items.append("r:%d:%s" % (idx, _chunk_b64(a)))
    for kind, val, attrs in exec_scripts:
        if kind == "s":
            url = val.replace("|", "%7C")
            items.append(("e:%s:%s" % (_encode_attrs(attrs), url)) if attrs else ("s:" + url))
        else:
            b64 = _encode_b64(val)
            items.append(("a:%s:%s" % (_encode_attrs(attrs), b64)) if attrs else ("b:" + b64))
    if not items:
        return html, 0, 0

    return _build_masked_html(no_scripts, items, _api._LITE_LOADER), n_inline, n_external


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
