# -*- coding: utf-8 -*-
"""Панель базы Shikimori: блоки частей, обновление по частям и переносы.

Кнопок про базу было две — «Обновить базу Shikimori» и «Что в базе…», — и
обновлялась база одним куском на десятки минут. Теперь кнопка одна: она
открывает панель, где видно, из чего база состоит, и где каждая часть
обновляется отдельно (просьба пользователя).
"""
import pytest

import animepack as ap

animepack_tab = pytest.importorskip("animepack_tab")

from si_hyx_parts.animepack_tab import db_rows              # noqa: E402
from si_hyx_parts.animepack_tab.db_table_dialog import DbTableDialog  # noqa: E402
from si_hyx_parts.animepack_tab.db_table_view import TEXT_COL_WIDTH  # noqa: E402
from si_hyx_parts.animepack_tab.db_title_delegate import (  # noqa: E402
    TitleActionsDelegate, character_url, shikimori_url,
)
from si_hyx_parts.animepack_tab.db_title_tree import group_title_rows   # noqa: E402

LONG = ("Очень длинное название тайтла, которое ни в какую колонку целиком "
        "не влезет и обязано перенестись на вторую строку")


def _card(mal=1, name=LONG, franchise="fr", people=100_000):
    return {"id": mal, "malId": mal, "russian": name, "name": name,
            "kind": "tv", "franchise": franchise, "airedOn": {"year": 2020},
            "score": 8.1,
            "statusesStats": [{"status": "completed", "count": people}]}


@pytest.fixture
def cache(tmp_path):
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    db.add_cards("anime", "sig", [_card()])
    db.add_cards("manga", "sig", [_card(mal=2, name="Книга", franchise="bk")])
    db.add_franchises({"fr": [_card(people=300_000)]})
    db.remember_memo("anime_favorites", 1, 4000)
    db.remember_memo("characters", "anime:1",
                     [{"id": 7, "name": "Герой", "main": True}])
    db.remember_memo("character_favorites", 7, 1200)
    db.save()
    return db


# ── кэш: части забываются порознь ───────────────────────────────────────────
def test_clear_part_touches_only_its_own_part(cache):
    """Обновить каталог аниме, не потеряв мангу, франшизы и «в избранном»."""
    assert cache.clear_part("anime") == 1
    counts = cache.part_counts()
    assert counts["anime"]["count"] == 0
    assert counts["manga"]["count"] == 1
    assert counts["franchises"]["count"] == 1
    assert counts["favorites"]["count"] == 1
    assert counts["extras"]["count"] == 2


def test_clear_part_extras_forgets_only_the_asked_by_one_answers(cache):
    assert cache.clear_part("extras") == 2
    counts = cache.part_counts()
    assert counts["extras"]["count"] == 0
    assert counts["anime"]["count"] == 1 and counts["manga"]["count"] == 1


def test_favorites_are_their_own_part_and_survive_forgetting_the_tails(cache):
    """«В избранном» собирается часами по запросу на тайтл — «Забыть хвосты»
    не имеет права уносить это вместе с персонажами и кадрами."""
    assert cache.clear_part("extras") == 2
    assert cache.part_counts()["favorites"]["count"] == 1
    assert cache.clear_part("favorites") == 1
    assert cache.part_counts()["favorites"]["count"] == 0


def test_default_parts_are_the_old_whole_base_without_the_tails():
    """None — прежнее «Обновить базу»: каталоги и франшизы, но не хвосты.

    Каждое число хвостов стоит отдельного запроса и копится генерациями —
    терять их при каждом обновлении каталога незачем."""
    songs = ap.PackSettings(rounds=1, themes=1, questions=5)
    assert ap.db_refresh_parts(None, songs) == ("anime", "franchises")
    with_manga = ap.PackSettings(rounds=1, themes=1, questions=5,
                                 pct_songs=50, pct_manga=50, pack_manga=True)
    assert ap.db_refresh_parts(None, with_manga) == ("anime", "manga", "remanga",
                                                     "mangalib", "franchises")
    assert ap.db_refresh_parts(("manga",)) == ("manga",)
    assert ap.db_refresh_parts("extras") == ("extras",)


# ── генератор: обновляется только запрошенная часть ─────────────────────────
def test_refresh_db_of_one_part_leaves_the_other_alone(tmp_path):
    asked = []

    class Shiki:
        def random_animes(self, page, **_kw):
            asked.append(("anime", page))
            return [_card(mal=7000 + i) for i in range(50)] if page == 1 else []

        def random_mangas(self, page, **_kw):
            asked.append(("manga", page))
            return []

        def franchise_parts(self, keys):
            return {}

    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    db.add_cards("manga", "старая", [_card(mal=42, name="Книга")])
    db.remember_memo("anime_favorites", 1, 4000)
    settings = ap.PackSettings(rounds=1, themes=1, questions=5, pct_songs=0,
                               pct_frames=100)
    gen = ap.AnimePackGenerator(settings, shikimori=Shiki(), db_cache=db)
    # Только аниме: за мангой не ходим, её карточки и хвосты остаются.
    assert gen.refresh_db(("anime",)) == 51
    assert {what for what, _ in asked} == {"anime"}
    counts = db.part_counts()
    assert counts["manga"]["count"] == 1
    assert counts["favorites"]["count"] == 1


def test_refresh_db_of_the_tails_asks_nobody(tmp_path):
    """«Забыть» — не поход в сеть: числа спросятся сами при генерации."""
    class Shiki:
        def random_animes(self, page, **_kw):
            raise AssertionError("хвосты каталог не трогают")

        def franchise_parts(self, keys):
            raise AssertionError("хвосты франшизы не трогают")

    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    db.add_cards("anime", "sig", [_card()])
    db.remember_memo("character_favorites", 7, 1200)
    settings = ap.PackSettings(rounds=1, themes=1, questions=5)
    gen = ap.AnimePackGenerator(settings, shikimori=Shiki(), db_cache=db)
    assert gen.refresh_db(("extras",)) == 1
    assert db.part_counts()["extras"]["count"] == 0
    assert db.part_counts()["anime"]["count"] == 1


# ── панель ──────────────────────────────────────────────────────────────────
def test_panel_shows_a_block_per_part_with_its_own_button(qapp, cache):
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        assert set(dialog.blocks) == {"anime", "manga", "favorites",
                                      "franchises", "extras"}
        assert dialog.blocks["anime"].count.text() == "1 карточка"
        assert dialog.blocks["extras"].count.text() == "2 ответа"
        assert dialog.blocks["extras"].button.text() == "Забыть"
        # «В избранном» собирается, а не только забывается.
        assert dialog.blocks["favorites"].count.text() == "1 тайтл"
        assert dialog.blocks["favorites"].button.text() == "Обновить"
        # Каждый блок рассказывает, как он собирался.
        assert "постранично" in dialog.blocks["anime"].toolTip()
        assert "взвешенные по статусу" in dialog.blocks["anime"].toolTip()
        assert "часть" in dialog.blocks["franchises"].toolTip()
        assert "избранн" in dialog.blocks["favorites"].toolTip()
        assert "персонаж" in dialog.blocks["extras"].toolTip()
    finally:
        dialog.deleteLater()


def test_panel_block_asks_the_tab_for_just_that_part(qapp, cache):
    calls = []

    class _FakeTab:
        _db_task = None
        _db_parts = ()

        def _refresh_db(self, parts=None):
            calls.append(parts)

    dialog = DbTableDialog(cache, _FakeTab())
    try:
        dialog.flush()
        dialog.blocks["manga"].button.click()
        dialog.btn_all.click()
        assert calls == [("manga",), ("anime", "manga", "remanga", "mangalib", "franchises")]
    finally:
        dialog.deleteLater()


def test_panel_marks_the_part_that_is_being_collected(qapp, cache):
    class _FakeTab:
        _db_task = object()
        _db_parts = ("anime",)

        def _refresh_db(self, parts=None):
            pass

    dialog = DbTableDialog(cache, _FakeTab())
    try:
        dialog.flush()
        assert dialog.blocks["anime"].button.text() == "Остановить"
        assert dialog.blocks["anime"].when.text() == "идёт сбор…"
        # Пока база занята, остальные части трогать нельзя.
        assert not dialog.blocks["manga"].button.isEnabled()
        assert not dialog.btn_all.isEnabled()
    finally:
        dialog.deleteLater()


def test_long_title_wraps_instead_of_stretching_the_table(qapp, cache):
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        table = dialog.anime.table
        assert table.columnWidth(0) <= TEXT_COL_WIDTH
        assert table.wordWrap()
        # Перенос настоящий: строка с длинным названием выше однострочной.
        one_line = table.fontMetrics().height() + 8
        assert table.rowHeight(dialog.anime.model.index(0, 0)) > one_line
    finally:
        dialog.deleteLater()


def test_row_hover_explains_the_index_and_the_level(qapp, cache):
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        text = dialog.anime.explain_at(dialog.anime.row_rect(0).center())
        assert "База: просмотрено" in text
        assert "Свой индекс:" in text
        assert "Уровень:" in text
        # Вкладки наполняются по открытию: на шестидесяти тысячах строк
        # собирать все три разом — десяток секунд на каждое открытие панели.
        dialog.tabs.setCurrentWidget(dialog.chars)
        dialog.flush()
        point = dialog.chars.row_rect(0).center()
        explanation = dialog.chars.explain_at(point)
        # Отдельного «уровня вопроса» у персонажа больше нет — только уровень
        # тайтла; избранное даёт скидку к цене (просьба пользователя).
        assert "Уровень его тайтла" in explanation
        assert "Уровень вопроса" not in explanation
        assert "к цене вопроса" in explanation
    finally:
        dialog.deleteLater()


def test_all_tables_show_place_price_and_price_breakdown(qapp, cache):
    dialog = DbTableDialog(cache, None)
    try:
        for page in (dialog.anime, dialog.manga, dialog.chars):
            dialog.tabs.setCurrentWidget(page)
            dialog.flush()
            headers = [page.model.headerData(
                col, animepack_tab.Qt.Orientation.Horizontal)
                for col in range(page.model.columnCount())]
            assert "Место" in headers and "Цена" in headers
            source = page.model.source(page.model.index(0, 0))
            assert source["place"] >= 1 and source["price"] >= 1
            price_col = headers.index("Цена")
            point = page.table.visualRect(page.model.index(0, price_col)).center()
            tip = page.explain_at(point)
            assert "Цена вопроса" in tip
            assert "Итого:" in tip
            assert "Место в текущей сортировке на цену не влияет" in tip
            assert headers[0] == "Место"
    finally:
        dialog.deleteLater()


def test_title_rows_take_the_franchise_index_from_the_cache(cache):
    """У сиквела узнаваемость франшизы и решает уровень — как в паке."""
    row = db_rows.title_rows(cache, "anime")[0]
    assert row["franchise_index"] > 0
    assert row["index"] >= row["franchise_index"]


def test_franchise_tree_puts_the_most_popular_title_on_top(qapp, cache):
    cache.add_cards("anime", "sig", [
        _card(mal=3, name="Продолжение", people=20_000),
        _card(mal=4, name="Главный тайтл", people=900_000),
    ])
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        model = dialog.anime.model
        assert model.rowCount() == 1
        root = model.index(0, 0)
        assert model.source(root)["title"] == "Главный тайтл"
        assert model.rowCount(root) == 2
        assert dialog.anime.table.isExpanded(root) is False
        dialog.anime.table.setExpanded(root, True)
        assert dialog.anime.table.isExpanded(root) is True
    finally:
        dialog.deleteLater()


def test_filtered_franchise_still_has_an_explicit_family_root(qapp, tmp_path):
    """ONA-оригинал может не пройти фильтр TV, но TV-мини всё ещё часть серии."""
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    mini = _card(mal=55977, name="Мини-аниме",
                 franchise="record_of_ragnarok", people=300)
    original = _card(mal=44942, name="Повесть о конце света",
                     franchise="record_of_ragnarok", people=30_000)
    db.add_cards("anime", "tv-only", [mini])
    db.add_franchises({"record_of_ragnarok": [original, mini]})
    dialog = DbTableDialog(db, None)
    try:
        dialog.flush()
        model = dialog.anime.model
        root = model.index(0, 0)
        assert model.source(root)["_franchise_header"] is True
        assert "Повесть о конце света" in model.source(root)["title"]
        values = [model.index(0, column).data()
                  for column in range(model.columnCount())]
        assert values[dialog.anime._headers.index("Тип")] == "франшиза"
        assert all(value not in (None, "") for value in values)
        assert model.rowCount(root) == 1
        assert model.source(model.index(0, 0, root))["id"] == 55977
        assert model.total() == 1       # служебный корень не становится тайтлом
    finally:
        dialog.deleteLater()


def test_title_action_links_use_the_shikimori_id():
    assert shikimori_url({
        "id": 28851, "media": "anime",
        "url": "/animes/y28851-koe-no-katachi",
    }) == "https://shikimori.io/animes/y28851-koe-no-katachi"
    assert shikimori_url({"id": 42, "media": "anime"}).endswith(
        "/animes/z42")
    assert shikimori_url({"id": 77, "media": "manga"}).endswith(
        "/mangas/z77")
    assert character_url({"id": 417}).endswith("/characters/417")
    assert shikimori_url({
        "id": 42, "media": "anime", "_franchise_header": True,
    }).endswith("/animes/z42/franchise")


def test_selected_title_highlight_covers_the_svg_button_area(qapp):
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QImage, QPainter, QStandardItemModel
    from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem

    model = QStandardItemModel(1, 1)
    model.setData(model.index(0, 0), "Тайтл")
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 220, 40)
    option.palette = qapp.palette()
    option.state |= QStyle.StateFlag.State_Selected
    image = QImage(220, 40, QImage.Format.Format_RGB32)
    image.fill(option.palette.base().color())
    painter = QPainter(image)
    TitleActionsDelegate().paint(painter, option, model.index(0, 0))
    painter.end()
    # Самый правый отступ не занят иконкой: там обязан продолжаться голубой
    # фон выделенной строки, а не прежний тёмный прямоугольник.
    assert image.pixelColor(218, 20) == option.palette.highlight().color()


def test_copy_svg_shows_a_check_and_resets_it(qapp, cache):
    from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
    from PyQt6.QtWidgets import QStyleOptionViewItem

    class Click:
        def type(self):
            return QEvent.Type.MouseButtonRelease

        def button(self):
            return Qt.MouseButton.LeftButton

        def position(self):
            return QPointF(copy_rect.center())

    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        model = dialog.anime.model
        index = model.index(0, dialog.anime._headers.index("Название"))
        row = model.source(index)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 300, 40)
        copy_rect, _open_rect = dialog.anime._title_delegate._rects(option)
        assert dialog.anime._title_delegate.editorEvent(
            Click(), model, option, index)
        assert qapp.clipboard().text() == row["title"]
        assert dialog.anime._title_delegate._copied_id == (
            dialog.anime._title_delegate._row_id(row))
        assert dialog.anime._title_delegate._reset_timer.isActive()
        dialog.anime._title_delegate._clear_copied()
        assert dialog.anime._title_delegate._copied_id is None
    finally:
        dialog.deleteLater()


def test_place_is_first_and_follows_the_current_sort(qapp, cache):
    cache.add_cards("anime", "more", [
        _card(mal=11, name="Альфа", franchise="", people=10),
        _card(mal=12, name="Ямато", franchise="", people=900_000),
    ])
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        model = dialog.anime.model
        assert dialog.anime._headers[0] == "Место"
        title_col = dialog.anime._headers.index("Название")
        before = [model.index(row, title_col).data()
                  for row in range(model.rowCount())]
        model.sort(title_col, animepack_tab.Qt.SortOrder.AscendingOrder)
        after = [model.index(row, title_col).data()
                 for row in range(model.rowCount())]
        assert after != before
        assert [model.index(row, 0).data()
                for row in range(model.rowCount())] == [
                    str(i) for i in range(1, model.rowCount() + 1)]
    finally:
        dialog.deleteLater()


def test_character_tab_uses_svg_actions_on_character_name(qapp, cache):
    dialog = DbTableDialog(cache, None)
    try:
        dialog.tabs.setCurrentWidget(dialog.chars)
        dialog.flush()
        assert dialog.chars._main_col == dialog.chars._headers.index("Персонаж")
        assert dialog.chars.table.itemDelegateForColumn(
            dialog.chars._main_col) is dialog.chars._title_delegate
    finally:
        dialog.deleteLater()


def test_one_title_can_be_replaced_in_every_catalog_bucket(tmp_path):
    db = ap.ShikimoriDbCache(str(tmp_path / "db.json"))
    old = _card(mal=9, name="Старое")
    db.add_cards("anime", "first", [old])
    db.add_cards("anime", "second", [old])
    fresh = dict(old, russian="Новое", name="Новое", score=9.5)
    assert db.replace_title_card("anime", fresh)
    assert {row["russian"] for row in db.all_cards("anime")} == {"Новое"}


def test_point_refresh_reloads_the_card_favorites_and_franchise(
        qapp, cache, monkeypatch):
    import animepack_api

    fresh = _card(name="Обновлённое", franchise="fresh", people=222_000)
    fresh["url"] = "/animes/y1-obnovlyonnoe"

    class Shiki:
        def animes_by_ids(self, ids):
            assert ids == [1]
            return [fresh]

        def title_favorites(self, ident, target, page_url):
            assert (ident, target) == (1, "anime")
            assert page_url == "/animes/y1-obnovlyonnoe"
            return 9876

        def franchise_parts(self, keys):
            assert keys == ["fresh"]
            return {"fresh": [fresh]}

    monkeypatch.setattr(animepack_api, "ShikimoriApi", Shiki)
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        assert dialog._read_title("anime", 1) == "Обновлённое"
        assert cache.all_cards("anime")[0]["russian"] == "Обновлённое"
        assert cache.memo("anime_favorites", 1) == 9876
        assert cache.franchise("fresh") == [fresh]
    finally:
        dialog.deleteLater()


def test_point_refresh_reloads_character_data(qapp, cache, monkeypatch):
    import animepack_api

    class Shiki:
        def characters_by_anime_ids(self, ids, target="anime"):
            assert ids == [1] and target == "anime"
            return {1: [{"id": 7, "name": "Герой обновлён",
                         "main": False}]}

        def character_favorites(self, ident):
            assert ident == 7
            return 4321

    monkeypatch.setattr(animepack_api, "ShikimoriApi", Shiki)
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        assert dialog._read_character(7, "anime", 1, 1) == 4321
        assert cache.memo("character_favorites", 7) == 4321
        people = cache.memo("characters", "anime:1")
        assert people[0]["name"] == "Герой обновлён"
        assert people[0]["main"] is False
    finally:
        dialog.deleteLater()


def test_point_refresh_keeps_the_tables_and_tree_position(qapp, cache,
                                                           monkeypatch):
    """ПКМ не очищает все вкладки и не сворачивает открытую франшизу."""
    cache.add_cards("anime", "sig", [
        _card(mal=3, name="Продолжение", people=20_000),
    ])
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        dialog.tabs.setCurrentWidget(dialog.manga)
        dialog.flush()
        assert dialog.manga.total() == 1
        dialog.tabs.setCurrentWidget(dialog.anime)

        model = dialog.anime.model
        root = model.index(0, 0)
        dialog.anime.table.setExpanded(root, True)
        child = model.index(0, 0, root)
        dialog.anime.table.setCurrentIndex(child)
        selected_id = model.source(child)["id"]

        # Глобальный refresh здесь был прежней причиной очистки трёх вкладок.
        monkeypatch.setattr(
            dialog, "refresh",
            lambda: pytest.fail("точечное обновление вызвало полный refresh"))
        dialog._job_done(dialog._age, ("title", "anime", 1), "Обновлено")
        dialog.flush()

        root = dialog.anime.model.index(0, 0)
        assert dialog.anime.table.isExpanded(root)
        current = dialog.anime.model.source(dialog.anime.table.currentIndex())
        assert current["id"] == selected_id
        assert dialog.manga.total() == 1
    finally:
        dialog.deleteLater()


def test_grouping_leaves_unrelated_titles_as_separate_roots():
    first = {"id": 1, "franchise": "", "index": 10}
    second = {"id": 2, "franchise": "", "index": 20}
    rows, parents = group_title_rows([first, second])
    assert [row["id"] for row in rows] == [2, 1]
    assert parents == [-1, -1]


# ── вкладка ─────────────────────────────────────────────────────────────────
def test_tab_has_one_database_button_that_opens_the_panel(qapp, monkeypatch):
    from test_animepack_tab_mix import _FakeMain

    tab = animepack_tab.AnimePackTab(main_window=_FakeMain())
    try:
        assert not hasattr(tab, "btn_db_table")   # две кнопки стали одной
        assert tab.btn_refresh_db.text() == "Обновить базу"
        opened = []
        monkeypatch.setattr(tab, "_open_db_table", lambda: opened.append(True))
        tab.btn_refresh_db.clicked.disconnect()
        tab.btn_refresh_db.clicked.connect(tab._open_db_table)
        tab.btn_refresh_db.click()
        assert opened == [True]
    finally:
        tab.cleanup()

def test_tabs_are_filled_only_when_opened(qapp, cache):
    """Панель открывается на «Аниме»: каталог манги — под пятьдесят тысяч
    строк, и собирать его ради одного взгляда на аниме незачем."""
    dialog = DbTableDialog(cache, None)
    try:
        dialog.flush()
        assert dialog.anime.total() == 1
        assert dialog.manga.total() == 0
        dialog.tabs.setCurrentWidget(dialog.manga)
        dialog.flush()
        assert dialog.manga.total() == 1
    finally:
        dialog.deleteLater()


def test_tab_sends_the_asked_parts_into_the_task(qapp, monkeypatch):
    """Блок панели просит одну часть — задача собирает ровно её."""
    from test_animepack_tab_mix import _FakeMain

    started = []

    class _FakeTask:
        def __init__(self, settings, parts=None):
            self.settings, self.parts = settings, parts
            self.signals = animepack_tab._RefreshDbSignals()

    tab = animepack_tab.AnimePackTab(main_window=_FakeMain())
    try:
        monkeypatch.setattr(animepack_tab, "_RefreshDbTask", _FakeTask)
        monkeypatch.setattr(tab._pool, "start", started.append)
        tab._refresh_db(("manga",))
        assert started and started[0].parts == ("manga",)
        assert tab._db_parts == ("manga",)
        assert tab.btn_refresh_db.text() == "База обновляется…"
        tab._finish_db_ui()
        assert tab.btn_refresh_db.text() == "Обновить базу"
    finally:
        tab.cleanup()
