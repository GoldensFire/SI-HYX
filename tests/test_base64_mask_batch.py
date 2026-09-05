# -*- coding: utf-8 -*-
"""Кнопка «Замаскировать HTML» должна маскировать ВСЕ загруженные HTML, а не
только первый (баг: остальные копировались в encoded\\ как есть)."""
import tabs


class _FakeMain:
    def log(self, *a, **k):
        pass


def _game_html(name):
    return (f"<html><head><title>{name}</title></head><body>"
            f"<div onclick='go()'>{name}</div>"
            f"<script>function go(){{ alert('{name}'); }}</script>"
            "</body></html>")


def _make_games(tmp_path, n):
    srcs = []
    for i in range(n):
        p = tmp_path / f"game{i}.html"
        p.write_text(_game_html(f"game{i}"), encoding="utf-8")
        srcs.append(str(p))
    return srcs


def test_button_masks_all_loaded_html(qapp, tmp_path):
    tab = tabs.Base64Tab(_FakeMain())
    srcs = _make_games(tmp_path, 3)
    tab._route_paths(srcs)                     # «дроп» трёх файлов
    assert len(tab._html_paths) == 3           # запомнены все, не только первый

    tab._mask_html_action()                    # нажатие кнопки

    outs = sorted((tmp_path / "encoded").glob("*.html"))
    assert len(outs) == 3                       # все три обработаны
    for o in outs:
        txt = o.read_text(encoding="utf-8")
        assert "data-si=" in txt                # реально замаскирован (старый режим)
        assert "function go()" not in txt       # исходный JS не виден в открытую


def test_button_lite_masks_all_loaded_html(qapp, tmp_path):
    tab = tabs.Base64Tab(_FakeMain())
    tab.chk_lite_mask.setChecked(True)
    srcs = _make_games(tmp_path, 3)
    tab._route_paths(srcs)
    tab._mask_html_action()

    outs = sorted((tmp_path / "encoded").glob("*.html"))
    assert len(outs) == 3
    for o in outs:
        txt = o.read_text(encoding="utf-8")
        # lite прячет всё в data-si через onload-лаунчер, без <script>/eval
        assert "data-si=" in txt and "window[launch](atob(" in txt
        assert "eval" not in txt
        assert "function go()" not in txt


def test_button_single_file_fallback(qapp, tmp_path):
    tab = tabs.Base64Tab(_FakeMain())
    src = _make_games(tmp_path, 1)[0]
    tab._route_paths([src])                    # одиночный файл
    tab._mask_html_action()

    outs = list((tmp_path / "encoded").glob("*.html"))
    assert len(outs) == 1
    assert "data-si=" in outs[0].read_text(encoding="utf-8")
