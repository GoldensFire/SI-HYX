# -*- coding: utf-8 -*-
"""Франшизы в панели базы: склейка сезонов, ПКМ «Обновить всю франшизу».

«Монолог фармацевта» лежал в панели тремя отдельными «франшизами» — по одной
на сезон: ключ ветки брался из самого длинного корня названия САМОЙ
карточки, а у сезонов он разный («kusuriya no hitorigoto 2nd», «…3rd»).
"""
import pytest

import animepack as ap

pytest.importorskip("animepack_tab")

from si_hyx_parts.animepack_tab.db_table_dialog import DbTableDialog  # noqa: E402


def _part(ident, russian):
    return {"id": str(ident), "malId": str(ident), "russian": russian,
            "kind": "tv", "airedOn": {"year": 2023}}


def _full(ident, russian, name, english):
    return dict(_part(ident, russian), name=name, english=english,
                franchise="maomao_no_hitorigoto")


PARTS = [
    _part(54492, "Монолог фармацевта"),
    _part(58514, "Монолог фармацевта 2"),
    _part(61987, "Монолог фармацевта 3"),
    _part(56975, "Монолог Маомао"),
    _part(60749, "Монолог Маомао 2"),
]


def test_all_seasons_share_one_branch_key():
    cards = [
        _full(54492, "Монолог фармацевта", "Kusuriya no Hitorigoto",
              "The Apothecary Diaries"),
        _full(58514, "Монолог фармацевта 2",
              "Kusuriya no Hitorigoto 2nd Season",
              "The Apothecary Diaries Season 2"),
        _full(61987, "Монолог фармацевта 3",
              "Kusuriya no Hitorigoto 3rd Season",
              "The Apothecary Diaries Season 3"),
    ]
    keys = {ap.franchise_branch_key(card, PARTS) for card in cards}
    assert keys == {"монолог фармацевта"}
    shorts = ap.franchise_branch_key(_full(56975, "Монолог Маомао",
                                           "Maomao no Hitorigoto", ""), PARTS)
    assert shorts not in keys


def _card(mal, name, franchise="fr"):
    return {"id": mal, "malId": mal, "russian": name, "name": name,
            "kind": "tv", "franchise": franchise, "airedOn": {"year": 2020},
            "score": 8.1,
            "statusesStats": [{"status": "completed", "count": 1000 * mal}]}


@pytest.fixture
def cache(tmp_path):
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    db.add_cards("anime", "sig", [_card(1, "Первый"), _card(2, "Второй"),
                                  _card(3, "Чужой", franchise="other")])
    db.add_franchises({"fr": [_card(1, "Первый"), _card(2, "Второй")]})
    db.save()
    return db


def test_franchise_refresh_rereads_every_part(qapp, cache, monkeypatch):
    import animepack_api

    asked = []

    class Shiki:
        def animes_by_ids(self, ids):
            asked.append(list(ids))
            return [dict(_card(i, f"Новое {i}")) for i in ids]

        def title_favorites(self, ident, target, page_url):
            return 100 + ident

        def franchise_parts(self, keys):
            return {"fr": [_card(1, "Новое 1"), _card(2, "Новое 2")]}

    monkeypatch.setattr(animepack_api, "ShikimoriApi", Shiki)
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        from si_hyx_parts.animepack_tab.db_refresh import read_franchise
        assert read_franchise(cache, "anime", "fr") == 2
        assert asked == [[1, 2]]
        names = {row["russian"] for row in cache.all_cards("anime")}
        assert names == {"Новое 1", "Новое 2", "Чужой"}
        assert cache.memo("anime_favorites", 2) == 102
        assert [p["russian"] for p in cache.franchise("fr")] == [
            "Новое 1", "Новое 2"]
    finally:
        dialog.deleteLater()


def test_menu_offers_franchise_refresh_on_header_and_parts(qapp, cache):
    dialog = DbTableDialog(cache, None)
    try:
        page = dialog.anime
        header = {"_franchise_header": True, "franchise": "fr",
                  "media": "anime"}
        assert [label for label, _ in page.row_actions(header)] == [
            "Обновить всю франшизу"]
        part = {"id": 1, "franchise": "fr", "media": "anime"}
        assert [label for label, _ in page.row_actions(part)] == [
            "Обновить данные", "Обновить всю франшизу"]
        lone = {"id": 3, "franchise": "", "media": "anime"}
        assert [label for label, _ in page.row_actions(lone)] == [
            "Обновить данные"]
    finally:
        dialog.deleteLater()


def test_row_tip_follows_the_mouse_without_waiting_for_a_pause(qapp, cache):
    """Пока подсказка показана, переход на соседнюю строку сразу меняет её
    текст: раньше чужой разбор висел до следующей паузы курсора (~0,7 с)."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QCursor, QHelpEvent, QMouseEvent
    from PyQt6.QtWidgets import QApplication
    from widgets import _InfoTipPopup

    dialog = DbTableDialog(cache, None)
    try:
        dialog.resize(900, 500)
        dialog.show()
        dialog.flush()
        qapp.processEvents()
        page = dialog.anime
        calls = []
        explain = page._explain
        page._explain = lambda row, *a: calls.append(row["title"]) or \
            f"разбор {row['title']}"
        viewport = page.table.viewport()
        first = page.row_rect(0).center()
        second = page.row_rect(1).center()
        QCursor.setPos(viewport.mapToGlobal(first))
        QApplication.sendEvent(viewport, QHelpEvent(
            QEvent.Type.ToolTip, first, viewport.mapToGlobal(first)))
        popup = _InfoTipPopup.instance()
        assert popup.isVisible()
        shown = popup.text()
        QCursor.setPos(viewport.mapToGlobal(second))
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(second),
                           QPointF(viewport.mapToGlobal(second)),
                           Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                           Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(viewport, move)
        assert popup.isVisible() and popup.text() != shown
        # Возврат на первую строку берёт разбор из памяти, а не считает заново.
        QCursor.setPos(viewport.mapToGlobal(first))
        back = QMouseEvent(QEvent.Type.MouseMove, QPointF(first),
                           QPointF(viewport.mapToGlobal(first)),
                           Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                           Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(viewport, back)
        assert popup.text() == shown
        assert len(calls) == 2
        page._explain = explain
    finally:
        _InfoTipPopup.instance().hide()
        dialog.deleteLater()
