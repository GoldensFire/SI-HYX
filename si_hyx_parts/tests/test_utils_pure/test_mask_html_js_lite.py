# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""TestMaskHtmlJsLite. Public namespace: test_utils_pure."""
import test_utils_pure as _api


class TestMaskHtmlJsLite:
    # Реалистичный «сырой» документ: разметка + конфиг-данные + движок.
    HTML = (
        '<html><head><title>t</title></head><body>\n'
        '<canvas id="c"></canvas><svg><rect/></svg>\n'
        '<div onclick="go()">привет</div>\n'
        '<script>const CFG={name:"Тест",answer:"кот"};'
        'const IMG="data:image/png;base64,AAAA";</script>\n'
        '<script>\n'
        'function go(){ if (CFG.answer==="кот") render(CFG.name); }\n'
        'const helper = (x) => x*2;\n'
        'function render(n){ document.title = n + helper(2); }\n'
        '</script>\n'
        '</body></html>')

    def test_counts_scripts(self):
        masked, n_inline, n_ext = _api.utils.mask_html_js_lite(self.HTML)
        assert (n_inline, n_ext) == (2, 0)          # оба инлайн-скрипта спрятаны

    def test_no_executable_literals_in_open_html(self):
        # ГЛАВНОЕ: в открытом HTML нет <script>/eval/function — иначе VK режет
        masked, *_ = _api.utils.mask_html_js_lite(self.HTML)
        assert _api._no_executable_literals(masked)

    def test_uses_onload_launcher_not_eval(self):
        masked, *_ = _api.utils.mask_html_js_lite(self.HTML)
        assert "eval" not in masked                 # никакого eval вообще
        assert "data-si=" in masked
        assert "const launch='Fun'+'ction';window[launch](atob(" in masked

    def test_markup_and_scripts_hidden(self):
        masked, *_ = _api.utils.mask_html_js_lite(self.HTML)
        # ни разметка, ни логика движка не видны в открытую
        assert "<canvas" not in masked and "<svg>" not in masked
        assert "function go()" not in masked and "function render(" not in masked
        assert 'const CFG={name:"Тест"' not in masked
        # но всё это лежит в data-si: движок в 'b', разметка в 'm'
        code = _api._lite_scripts(masked)
        assert "function go()" in code and "function render(" in code
        assert "=> x*2" in code and 'const CFG={name:"Тест"' in code

    def test_nothing_to_hide_returns_original(self):
        html = '<body><div>x</div></body>'         # скриптов нет вовсе
        assert _api.utils.mask_html_js_lite(html) == (html, 0, 0)

    def test_external_src_becomes_dynamic(self):
        html = ('<body><script src="https://cdn/x.js"></script>'
                '<script>function q(){go()}</script></body>')
        masked, n_inline, n_ext = _api.utils.mask_html_js_lite(html)
        assert (n_inline, n_ext) == (1, 1)
        assert _api._no_executable_literals(masked)
        assert "s:https://cdn/x.js" in "|".join(_api._lite_items(masked))

    def test_large_asset_single_encoded_as_raw_item(self):
        # крупный ассет НЕ должен кодироваться base64 повторно: он выносится в
        # отдельный 'r'-элемент (сам base64, без второго слоя), а в скрипте —
        # ссылка __SI_A0. Так lite меньше старого метода на размер этого ассета.
        asset = "T2dnUw" + "A" * 2000
        html = ('<body>\n'
                "<script>\nconst AUDIO_B64='%s';\n"
                'function play(){ return new Audio(AUDIO_B64); }\n'
                '</script>\n</body>' % asset)
        masked, n_inline, _ = _api.utils.mask_html_js_lite(html)
        assert n_inline == 1
        assert _api._no_executable_literals(masked)
        # ассет лежит сырым в 'r:0' и равен исходному (единожды закодирован)
        assert _api._lite_raw_assets(masked) == {0: asset}
        # в скрипте на его месте — глобальная ссылка, самого ассета там нет
        code = _api._lite_scripts(masked)
        assert "const AUDIO_B64=__SI_A0" in code
        assert "function play()" in code
        assert asset not in code

    def test_asset_array_elements_hoisted(self):
        # ассеты как ЭЛЕМЕНТЫ массива (кейс «Найди Mambo»: const IMGS=[...])
        a1 = "iVBORw" + "A" * 900
        a2 = "iVBORw" + "B" * 900
        html = ('<body><script>\n'
                "const IMGS=['%s','%s'];\n"
                'function draw(){ return IMGS.length; }\n'
                '</script></body>' % (a1, a2))
        masked, *_ = _api.utils.mask_html_js_lite(html)
        assert _api._lite_raw_assets(masked) == {0: a1, 1: a2}
        code = _api._lite_scripts(masked)
        assert "const IMGS=[__SI_A0,__SI_A1]" in code
        assert a1 not in code and a2 not in code
        assert "function draw()" in code

    def test_small_base64_string_not_hoisted(self):
        # короткий base64 — обычная строка кода, в 'r' не выносится
        html = ("<body><script>const K='YWJj';function f(){return atob(K);}"
                "</script></body>")
        masked, *_ = _api.utils.mask_html_js_lite(html)
        assert _api._lite_raw_assets(masked) == {}       # нечего выносить
        assert "const K='YWJj'" in _api._lite_scripts(masked)   # осталось в скрипте

    def test_data_prefixed_asset_hoisted_verbatim(self):
        # ассет, УЖЕ являющийся data:-URL, выносится как есть и восстанавливается
        # ровно тем же значением (движок ждёт data:-URL).
        asset = "data:image/webp;base64,UklGR" + "A" * 1000
        html = ('<body><script>\n'
                "const BG='%s';\n"
                'function paint(){ document.body.style.background="url("+BG+")"; }\n'
                '</script></body>' % asset)
        masked, *_ = _api.utils.mask_html_js_lite(html)
        assert _api._lite_raw_assets(masked) == {0: asset}      # вербатим, с префиксом
        assert "const BG=__SI_A0" in _api._lite_scripts(masked)

    def test_data_script_also_hidden(self):
        # даже чистый скрипт-данные (без function) прячется целиком — VK не
        # должен видеть НИ ОДНОГО <script>. Его глобальные const восстанавливает
        # loader (createElement script → global), движок их читает.
        html = ('<body><script>const SECRET=atob("a29t");</script>'
                '<script>function chk(g){return g===SECRET;}</script></body>')
        masked, n_inline, _ = _api.utils.mask_html_js_lite(html)
        assert n_inline == 2
        assert _api._no_executable_literals(masked)
        code = _api._lite_scripts(masked)
        assert 'const SECRET=atob("a29t");' in code and "function chk" in code

TestMaskHtmlJsLite.__module__ = _api.__name__
_api.TestMaskHtmlJsLite = TestMaskHtmlJsLite

# ── default_download_dir ─────────────────────────────────────────────────────
class TestDefaultDownloadDir:
    def test_returns_existing_dir(self):
        d = _api.utils.default_download_dir()
        import os
        assert os.path.isdir(d)

    def test_fallback_home(self, monkeypatch):
        import os
        monkeypatch.setattr(_api.utils.os.path, "isdir", lambda p: False)
        d = _api.utils.default_download_dir()
        assert d == os.path.expanduser("~")

TestDefaultDownloadDir.__module__ = _api.__name__
_api.TestDefaultDownloadDir = TestDefaultDownloadDir
