# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""mask_html_js. Public namespace: utils."""
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
