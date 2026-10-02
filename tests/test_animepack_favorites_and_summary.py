# -*- coding: utf-8 -*-
"""«В избранном» в индексе, разбивка цены, номер пака и состав в комментариях."""
import collections
import re
from types import SimpleNamespace
import threading

import pytest

import animepack as ap
import animepack_api as api
import animepack_tab
import shikimori_api as shiki
from si_hyx_parts.animepack import pack_summary
from si_hyx_parts.animepack_tab import index_tooltip, table_dialog
from test_animepack_tab_mix import _FakeMain

CARD = {"id": 1, "malId": 1, "russian": "Тест", "name": "Test",
        "airedOn": {"year": 2020}, "score": 8.1,
        "statusesStats": [{"status": "completed", "count": 100000}]}
SONG = {"songType": "Opening 1", "songName": "x", "songArtist": "y",
        "songDifficulty": 85.0, "audio": "a.mp3", "songLength": 90,
        "songCategory": "standard", "animeType": "TV",
        "linked_ids": {"myanimelist": 1}}


@pytest.fixture
def tab(qapp):
    widget = animepack_tab.AnimePackTab(main_window=_FakeMain())
    yield widget
    widget.cleanup()


class _Resp:
    """Ответ requests ровно в том объёме, в каком его читает ShikimoriApi."""

    def __init__(self, text="", status=200, payload=None):
        self.text, self.status_code, self.payload = text, status, payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


# ── «в избранном» ─────────────────────────────────────────────────────
def test_favorites_factor_is_neutral_at_the_usual_share():
    """Средний тайтл индекс не двигает — иначе поехала бы вся лесенка цен."""
    base = 1_000_000.0
    usual = base * shiki._INDEX_FAVORITES_PIVOT
    assert shiki.index_favorites_factor(base, usual) == pytest.approx(1.0)


def test_favorites_lift_a_title_everyone_knows_and_few_watched():
    """«Детектив Конан»: зрителей на Shikimori мало (база 74 тыс.), а в
    избранном втрое чаще среднего — индекс обязан это заметить."""
    assert shiki.index_favorites_factor(74_480, 523) > 1.3


def test_favorites_never_lower_the_index():
    """Мера умеет доказать известность, но не безвестность: у «Покемона» и у
    любого сиквела избранного мало, а знают их всё равно."""
    assert shiki.index_favorites_factor(226_938, 231) == 1.0      # Покемон
    assert shiki.index_favorites_factor(1_820_858, 950) == 1.0    # сиквел
    assert shiki.index_favorites_factor(1_000_000, 0) == 1.0


def test_unknown_favorites_leave_the_index_exactly_as_it_was():
    """−1 значит «не спрашивали»: индекс считается по-старому, без поправки."""
    cand = ap.SongCandidate(song=SONG, anime=CARD)
    assert cand.favorites == -1
    assert cand.favorites_factor == 1.0
    assert cand.index == cand.own_index


def test_favorites_raise_the_index_of_a_candidate():
    plain = ap.SongCandidate(song=SONG, anime=CARD)
    loved = ap.SongCandidate(song=SONG, anime=CARD,
                             favorites=int(plain.own_base * 0.02))
    assert loved.index > plain.index


def test_title_favorites_are_read_from_the_shikimori_page():
    """Число берётся с канонической страницы, включая нестандартный префикс."""
    page = ('<div class="b-favoured"><div class="subheadline">'
            '<div class="linkeable">В избранном<div class="count">6951'
            '</div></div></div></div>')
    asked = []

    def _get(url, **_kw):
        asked.append(url)
        return _Resp(page)

    shikimori = api.ShikimoriApi()
    shikimori._get = _get
    assert shikimori.title_favorites(
        28851, page_url="/animes/y28851-koe-no-katachi") == 6951
    assert shikimori.title_favorites(
        2, "manga", "/mangas/x2-test") == 6951
    assert asked == ["https://shikimori.io/animes/y28851-koe-no-katachi",
                     "https://shikimori.io/mangas/x2-test"]


def test_title_favorites_resolve_the_url_for_an_old_cached_card():
    page = ('<body class="p-animes-show"><div class="b-favoured">'
            '<div class="count">4603</div></div></body>')
    asked = []

    def _get(url, **_kw):
        asked.append(url)
        if "/api/animes/28851" in url:
            return _Resp(payload={"url": "/animes/y28851-koe-no-katachi"})
        return _Resp(page)

    shikimori = api.ShikimoriApi()
    shikimori._get = _get
    assert shikimori.title_favorites(28851) == 4603
    assert asked[-1].endswith("/animes/y28851-koe-no-katachi")


def test_title_favorites_tell_zero_from_unknown():
    """Ноль («ни у кого») и −1 («не узнали») различаются: иначе сложность
    считалась бы по случайности сети."""
    shikimori = api.ShikimoriApi()
    shikimori._get = lambda url, **kw: _Resp('<body class="p-animes-show">')
    assert shikimori.title_favorites(21, page_url="/animes/x21-test") == 0
    shikimori._get = lambda url, **kw: _Resp("<html>Cloudflare</html>")
    assert shikimori.title_favorites(21, page_url="/animes/x21-test") == -1
    shikimori._get = lambda url, **kw: _Resp("", 404)
    assert shikimori.title_favorites(21, page_url="/animes/x21-test") == -1


def test_the_generator_asks_for_favorites_once_and_remembers_them():
    """Страница стоит запроса, поэтому ответ оседает в кэше навсегда."""
    gen = object.__new__(ap.AnimePackGenerator)
    gen.log = lambda *_a: None
    gen._media_cache_lock = threading.Lock()
    gen._media_cache_hits = collections.Counter()
    calls = []
    stored = {}

    class _Shikimori:
        def title_favorites(self, tid, target="anime"):
            calls.append((tid, target))
            return 777

    class _Cache:
        def memo(self, category, key, _ttl=0):
            return stored.get((category, str(key)))

        def remember_memo(self, category, key, value):
            stored[(category, str(key))] = value

    gen.shikimori, gen.db_cache = _Shikimori(), _Cache()
    cand = ap.SongCandidate(song=SONG, anime=CARD)
    assert gen._title_favorites(cand) == 777
    assert gen._title_favorites(cand) == 777      # второй раз — из кэша
    assert calls == [(1, "anime")]
    assert stored[("anime_favorites", "1")] == 777


def test_the_index_tooltip_explains_the_favorites_share():
    cand = ap.SongCandidate(song=SONG, anime=CARD, favorites=20_000)
    text = index_tooltip.build_text(cand)
    assert "Избранное: 20 000 → ×1,5" in text


def test_the_index_tooltip_says_when_there_is_no_bonus():
    cand = ap.SongCandidate(song=SONG, anime=CARD, favorites=10)
    text = index_tooltip.build_text(cand)
    assert "Избранное: 10 → ×1" in text
    assert "Надбавки нет" not in text


def test_the_franchise_index_is_taken_from_the_most_popular_part():
    """Не первый сезон, а самая популярная часть задаёт узнаваемость серии."""
    first = {"statusesStats": [{"status": "completed", "count": 1000}],
             "airedOn": {"year": 2002}, "score": 7.0}
    hit = {"statusesStats": [{"status": "completed", "count": 300000}],
           "airedOn": {"year": 2002}, "score": 7.0}
    assert (shiki.franchise_parts_index([first, hit])
            == shiki.franchise_parts_index([hit, first]))
    assert (shiki.franchise_parts_index([first, hit])
            > shiki.franchise_parts_index([first]))


# ── разбивка цены ─────────────────────────────────────────────────────
def test_price_breakdown_names_every_step():
    songs = [ap.SongCandidate(song=SONG, anime=CARD, kind="ending"),
             ap.SongCandidate(song=SONG, anime=CARD, kind="opening")]
    ap.assign_prices(songs, ap.PackSettings())
    lines = songs[0].price_parts
    assert any("Уровень тайтла" in line for line in lines)
    assert any(line.startswith("Эндинг: +") for line in lines)
    assert lines[-1] == f"Итого: {songs[0].price}"


def test_the_price_cell_carries_its_breakdown(tab):
    cand = ap.SongCandidate(song=SONG, anime=CARD, kind="opening")
    tab._fill_table([cand])
    item = tab.table.item(0, 3)
    assert "Цена вопроса" in str(item.data(index_tooltip.PRICE_ROLE))
    # Окно состава пака копирует ячейки через clone() — подсказка едет с ними.
    assert item.clone().data(index_tooltip.PRICE_ROLE) == item.data(
        index_tooltip.PRICE_ROLE)


# ── окно состава пака: сортировка и поиск ─────────────────────────────
def test_the_pack_window_sorts_prices_as_numbers(tab):
    """Раньше копии ячеек теряли числовой тип и шли 1, 10, 11, 12."""
    from PyQt6.QtCore import Qt
    tab._fill_table([ap.SongCandidate(song=SONG, anime=CARD, kind="opening")
                     for _ in range(4)])
    # Цены у одинаковых карточек совпадают — расставляем их руками, иначе
    # сортировать нечего.
    for row, price in enumerate((2, 10, 11, 20)):
        tab.table.setItem(row, 3, animepack_tab._NumItem(str(price), price))
    dialog = table_dialog.PackTableDialog(tab.table, tab.TABLE_HEADERS, tab)
    dialog.table.sortItems(3, Qt.SortOrder.AscendingOrder)
    assert [dialog.table.item(row, 3).text() for row in range(4)] == \
        ["2", "10", "11", "20"]
    dialog.close()


def test_the_pack_window_search_hides_other_rows(tab):
    other = dict(CARD, id=2, malId=2, russian="Другое")
    tab._fill_table([ap.SongCandidate(song=SONG, anime=CARD),
                     ap.SongCandidate(song=SONG, anime=other)])
    dialog = table_dialog.PackTableDialog(tab.table, tab.TABLE_HEADERS, tab)
    dialog.search.setText("другое")
    hidden = [dialog.table.isRowHidden(row)
              for row in range(dialog.table.rowCount())]
    assert hidden.count(False) == 1
    assert "Найдено: 1 из 2" in dialog.found.text()
    dialog.close()


# ── номер пака и состав в комментариях ────────────────────────────────
def test_the_pack_name_gets_its_number():
    assert pack_summary.numbered_title("Пак", 3) == "Пак № 3"
    assert pack_summary.numbered_title("Пак № 3", 3) == "Пак № 3"
    assert pack_summary.numbered_title("Пак", 0) == "Пак"


def test_the_pack_name_ends_with_its_average_level():
    rows = [SimpleNamespace(level=3), SimpleNamespace(level=5),
            SimpleNamespace(level=5)]
    assert pack_summary.pack_title("Пак", 56, rows) == "Пак № 56 (Ур. 4.3)"
    # Пересборка не копит приписки — ни прежние целые, ни с десятыми.
    assert pack_summary.pack_title("Пак № 56 (Ур. 7)", 56, rows) ==         "Пак № 56 (Ур. 4.3)"
    assert pack_summary.pack_title("Пак № 56 (Ур. 6.9)", 56, rows) ==         "Пак № 56 (Ур. 4.3)"
    assert pack_summary.pack_title("Пак", 2, []) == "Пак № 2"


def test_composition_lines_show_only_the_average_level():
    rows = [SimpleNamespace(kind="manga", level=3, has_video=False),
            SimpleNamespace(kind="manga", level=6, has_video=False)]
    text = pack_summary.composition_text(rows, None, {"manga": "Манга"})
    assert text.splitlines()[0] == "Манга: 2 (4.5🎯в ср.)"


def test_content_xml_numbers_the_pack_and_describes_its_parts():
    songs = [ap.SongCandidate(song=SONG, anime=CARD, kind="opening"),
             ap.SongCandidate(song={}, anime=CARD, kind=ap.FRAME_KIND)]
    settings = ap.PackSettings()
    settings.pack_number = 7
    xml = ap.build_content_xml(songs, settings).decode("utf-8")
    level = pack_summary.average_level(songs)
    assert f'name="Сгенерировано в SI-HYX № 7 (Ур. {level:.1f})"' in xml
    comments = re.search(r"<comments>(.*?)</comments>", xml, re.S).group(1)
    assert "Из чего состоит" not in comments
    assert "Опенинг: 1" in comments
    assert "Кадр: 1" in comments
    assert "🎯в ср." in comments and "Сложность от" not in comments
    assert "AMQ - от" in comments
    assert "Сложность (Ур.)" in comments
    # Ни числа раундов, ни разброса цен, ни предупреждения «собрано
    # автоматически» в комментарии больше нет (просьба пользователя).
    assert "раундов" not in comments
    assert "Цены:" not in comments
    assert "автоматически" not in comments
    assert "Узнаваемость" not in comments


def test_each_run_takes_the_next_number(tab, monkeypatch):
    """Номер растёт на каждом запуске и переживает перезапуск программы."""
    tab.apply_settings({"pack_number": 4})
    assert tab.collect().pack_number == 4
    started = []
    monkeypatch.setattr(tab._pool, "start", lambda task: started.append(task))
    tab.start()
    assert tab._pack_number == 5
    assert tab.collect().pack_number == 5
    if started:
        started[0].stop()
