# -*- coding: utf-8 -*-
"""Тесты sigstats/sibrowser.py — парсер каталога sibrowser.ru на синтетическом HTML."""
import pytest

from sigstats import sibrowser as sb
from sigstats import config as scfg
from conftest import FakeResponse, FakeSession


def _card_html(pid="123", name="Аниме пак", authors=("Автор",), downloads="1 234",
               questions=150, size="12,5 МБ", date="2026-01-15",
               themes_html=None, category=True):
    authors_html = "".join(
        f'<span itemprop="author"><span itemprop="name">{a}</span></span>'
        for a in authors)
    if themes_html is None:
        themes_html = (
            "<h2>Темы в раундах</h2>"
            "Раунд 1: <span class='text-neutral-500'>🎶Музыка, Кино и сериалы, "
            "Перемотка (ОП, опенинги)</span><br>"
            "Финал: <span class='text-neutral-500'>Финальная тема</span>")
    cat_html = ""
    if category:
        cat_html = ('<a rel="category" href="/categories/anime">'
                    "<span>Аниме</span><span>80%</span></a>")
    return f"""
<article itemprop="itemListElement">
  <a href="/packages/{pid}"><h1>{name}</h1></a>
  {authors_html}
  <time datetime="{date}">15 января</time>
  <span itemprop="contentSize">{size}</span>
  <span data-packages--download_link--component-target="count">{downloads}</span>
  <table>
    <tr><td>Всего</td><td>{questions} вопросов</td></tr>
    <tr><td>Текст</td><td>10%</td></tr>
    <tr><td>Фото</td><td>20%</td></tr>
    <tr><td>Звук</td><td>30%</td></tr>
    <tr><td>Видео</td><td>40%</td></tr>
  </table>
  <a rel="tag" href="/tags/anime">аниме</a>
  <a rel="tag" href="/tags/music">музыка</a>
  {cat_html}
  <div>{themes_html}</div>
</article>
"""


def _page_html(*cards):
    return "<html><body>" + "".join(cards) + "</body></html>"


# ── _parse_size_mb ───────────────────────────────────────────────────────────
class TestParseSize:
    @pytest.mark.parametrize("text,mb", [
        ("12,5 МБ", 12.5),
        ("12.5 MB", 12.5),
        ("512 КБ", 0.5),
        ("512 KB", 0.5),
        ("1 ГБ", 1024.0),
        ("2 GB", 2048.0),
    ])
    def test_units(self, text, mb):
        assert sb._parse_size_mb(text) == pytest.approx(mb)

    def test_no_match(self):
        assert sb._parse_size_mb("нет размера") is None
        assert sb._parse_size_mb("") is None
        assert sb._parse_size_mb(None) is None


# ── _split_themes ────────────────────────────────────────────────────────────
class TestSplitThemes:
    def test_basic(self):
        assert sb._split_themes("Музыка, Кино, Игры") == ["Музыка", "Кино", "Игры"]

    def test_comma_in_parens_kept(self):
        out = sb._split_themes("Опрометчивая перемотка (ОП, опенинги), Кино")
        assert out == ["Опрометчивая перемотка (ОП, опенинги)", "Кино"]

    def test_comma_without_space_kept(self):
        out = sb._split_themes("Числа 4,5 и 6, Другая тема")
        assert out == ["Числа 4,5 и 6", "Другая тема"]

    def test_trailing_comma(self):
        assert sb._split_themes("Одна, ") == ["Одна"]

    def test_empty(self):
        assert sb._split_themes("") == []

    def test_nested_brackets(self):
        out = sb._split_themes("Тема [a, b] и {c, d}, Вторая")
        assert out == ["Тема [a, b] и {c, d}", "Вторая"]


# ── parse_list / _parse_card ─────────────────────────────────────────────────
class TestParseCard:
    def test_full_card(self):
        cards = sb.parse_list(_page_html(_card_html()))
        assert len(cards) == 1
        c = cards[0]
        assert c.sibrowser_id == "123"
        assert c.name == "Аниме пак"
        assert c.name_norm == "аниме пак"
        assert c.authors == ["Автор"]
        assert c.download_count == 1234
        assert c.question_count == 150
        assert c.size_mb == pytest.approx(12.5)
        assert c.date_published == "2026-01-15"
        assert c.tags == ["аниме", "музыка"]
        assert c.pct_text == 10 and c.pct_photo == 20
        assert c.pct_audio == 30 and c.pct_video == 40

    def test_categories(self):
        c = sb.parse_list(_page_html(_card_html()))[0]
        assert c.categories == [{"name": "Аниме", "pct": 80, "slug": "anime"}]

    def test_themes_parsed(self):
        c = sb.parse_list(_page_html(_card_html()))[0]
        names = [t["name"] for t in c.themes]
        assert "🎶Музыка" in names
        assert "Перемотка (ОП, опенинги)" in names  # запятая в скобках не делит
        rounds = {t["round_index"] for t in c.themes}
        assert rounds == {0, 1}
        assert c.round_count == 2
        final = [t for t in c.themes if t["round_index"] == 1][0]
        assert final["round_name"] == "Финал"
        assert all(t["source"] == "sibrowser" for t in c.themes)

    def test_card_without_name_skipped(self):
        html = '<article itemprop="itemListElement"><p>без имени</p></article>'
        assert sb.parse_list(_page_html(html)) == []

    def test_multiple_cards(self):
        page = _page_html(_card_html(pid="1", name="Пак 1"),
                          _card_html(pid="2", name="Пак 2"))
        cards = sb.parse_list(page)
        assert [c.name for c in cards] == ["Пак 1", "Пак 2"]

    def test_empty_page(self):
        assert sb.parse_list("<html></html>") == []

    def test_as_package_adds_length_group(self):
        c = sb.parse_list(_page_html(_card_html(questions=150)))[0]
        assert c.as_package()["length_group"] == "Полные"

    def test_missing_optional_fields(self):
        html = """
<article itemprop="itemListElement">
  <a href="/packages/9"><h1>Минимальный</h1></a>
</article>"""
        c = sb.parse_list(_page_html(html))[0]
        assert c.sibrowser_id == "9"
        assert c.download_count is None
        assert c.question_count is None
        assert c.size_mb is None
        assert c.themes == []
        assert c.round_count is None


# ── _category_pct ────────────────────────────────────────────────────────────
class TestCategoryPct:
    def _card(self, cats):
        c = sb.parse_list(_page_html(_card_html()))[0]
        c.categories = cats
        return c

    def test_match_slug(self):
        c = self._card([{"name": "Аниме", "pct": 70, "slug": "anime"}])
        assert sb._category_pct(c, "anime") == 70

    def test_no_slug_takes_first(self):
        c = self._card([{"name": "Аниме", "pct": 70, "slug": "anime"}])
        assert sb._category_pct(c, None) == 70

    def test_wrong_slug(self):
        c = self._card([{"name": "Аниме", "pct": 70, "slug": "anime"}])
        assert sb._category_pct(c, "music") is None

    def test_pct_none_skipped(self):
        c = self._card([{"name": "Аниме", "pct": None, "slug": "anime"}])
        assert sb._category_pct(c, "anime") is None


# ── iter_cards ───────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def fast_scrape(monkeypatch):
    monkeypatch.setattr(scfg, "SCRAPE_DELAY", 0)


class TestIterCards:
    def _patch_pages(self, monkeypatch, pages):
        """pages: {номер: html}. Отсутствующая страница → пустой список карточек."""
        def fake_fetch(session, page, sort=None, category_slug=None):
            return pages.get(page, "<html></html>")
        monkeypatch.setattr(sb, "fetch_list_html", fake_fetch)

    def test_downloads_mode_stops_below_threshold(self, monkeypatch):
        pages = {1: _page_html(
            _card_html(pid="1", name="Большой", downloads="1000"),
            _card_html(pid="2", name="Маленький", downloads="10"),
            _card_html(pid="3", name="Не должен попасть", downloads="9999"),
        )}
        self._patch_pages(monkeypatch, pages)
        out = list(sb.iter_cards(FakeSession(), min_downloads=100, skip_norms=set()))
        assert [c.name for c in out] == ["Большой"]

    def test_skip_norms_dedup(self, monkeypatch):
        pages = {1: _page_html(_card_html(pid="1", name="Пак", downloads="500"),
                               _card_html(pid="2", name="ПАК", downloads="400"))}
        self._patch_pages(monkeypatch, pages)
        skip = set()
        out = list(sb.iter_cards(FakeSession(), min_downloads=1, skip_norms=skip))
        assert len(out) == 1
        assert "пак" in skip

    def test_preseeded_skip_norms(self, monkeypatch):
        pages = {1: _page_html(_card_html(name="Старый пак", downloads="500"))}
        self._patch_pages(monkeypatch, pages)
        out = list(sb.iter_cards(FakeSession(), min_downloads=1,
                                 skip_norms={"старый пак"}))
        assert out == []

    def test_date_mode_cutoff(self, monkeypatch):
        pages = {1: _page_html(
            _card_html(pid="1", name="Новый", date="2026-06-01", downloads="50"),
            _card_html(pid="2", name="Старый", date="2020-01-01", downloads="500"),
            _card_html(pid="3", name="После отсечки", date="2026-07-01"),
        )}
        self._patch_pages(monkeypatch, pages)
        out = list(sb.iter_cards(FakeSession(), min_downloads=1, skip_norms=set(),
                                 mode="date", cutoff_date="2025-01-01"))
        assert [c.name for c in out] == ["Новый"]

    def test_date_mode_low_downloads_skipped_not_stopped(self, monkeypatch):
        pages = {1: _page_html(
            _card_html(pid="1", name="Мало скачиваний", date="2026-06-01",
                       downloads="5"),
            _card_html(pid="2", name="Достаточно", date="2026-05-01",
                       downloads="500"),
        )}
        self._patch_pages(monkeypatch, pages)
        out = list(sb.iter_cards(FakeSession(), min_downloads=100, skip_norms=set(),
                                 mode="date", cutoff_date="2020-01-01"))
        assert [c.name for c in out] == ["Достаточно"]

    def test_category_min_pct(self, monkeypatch):
        pages = {1: _page_html(_card_html(name="Аниме 80", downloads="500"))}
        self._patch_pages(monkeypatch, pages)
        out = list(sb.iter_cards(FakeSession(), min_downloads=1, skip_norms=set(),
                                 category_slug="anime", category_min_pct=90))
        assert out == []
        out = list(sb.iter_cards(FakeSession(), min_downloads=1, skip_norms=set(),
                                 category_slug="anime", category_min_pct=50))
        assert len(out) == 1

    def test_state_tracked(self, monkeypatch):
        pages = {1: _page_html(_card_html(name="Пак", downloads="500"))}
        self._patch_pages(monkeypatch, pages)
        state = {}
        list(sb.iter_cards(FakeSession(), min_downloads=1, skip_norms=set(),
                           state=state))
        assert state["last_page"] == 1
        assert state["last_card"].name == "Пак"

    def test_should_stop(self, monkeypatch):
        pages = {i: _page_html(*[_card_html(pid=str(i * 10 + j),
                                            name=f"Пак {i}-{j}", downloads="500")
                                 for j in range(3)]) for i in range(1, 5)}
        self._patch_pages(monkeypatch, pages)
        out = list(sb.iter_cards(FakeSession(), min_downloads=1, skip_norms=set(),
                                 should_stop=lambda: True))
        assert out == []

    def test_start_page(self, monkeypatch):
        fetched = []

        def fake_fetch(session, page, sort=None, category_slug=None):
            fetched.append(page)
            return "<html></html>"
        monkeypatch.setattr(sb, "fetch_list_html", fake_fetch)
        list(sb.iter_cards(FakeSession(), min_downloads=1, skip_norms=set(),
                           start_page=5))
        assert fetched == [5]

    def test_fetch_error_stops(self, monkeypatch):
        def fake_fetch(session, page, sort=None, category_slug=None):
            raise OSError("сеть")
        monkeypatch.setattr(sb, "fetch_list_html", fake_fetch)
        msgs = []
        out = list(sb.iter_cards(FakeSession(), min_downloads=1, skip_norms=set(),
                                 progress_cb=msgs.append))
        assert out == []
        assert any("Ошибка" in m for m in msgs)


# ── fetch_list_html / download_url / iter_author_cards ───────────────────────
class TestFetchers:
    def test_fetch_list_url_with_sort(self):
        s = FakeSession(routes=[("sibrowser", FakeResponse(text="<html>ok</html>"))])
        html = sb.fetch_list_html(s, 3)
        assert html == "<html>ok</html>"
        assert "page=3" in s.calls[0][1] and "sort=download_count" in s.calls[0][1]

    def test_fetch_list_url_category(self):
        s = FakeSession(routes=[("sibrowser", FakeResponse(text="x"))])
        sb.fetch_list_html(s, 1, sort=None, category_slug="anime")
        url = s.calls[0][1]
        assert "/categories/anime" in url and "sort" not in url

    def test_fetch_list_http_error(self):
        s = FakeSession(routes=[("sibrowser", FakeResponse(status_code=500))])
        import requests as req
        with pytest.raises(req.HTTPError):
            sb.fetch_list_html(s, 1)

    def test_download_url(self):
        assert sb.download_url("42") == \
            f"{scfg.SIBROWSER_BASE}/packages/42/direct_download"

    def test_make_session_headers(self):
        s = sb.make_session()
        try:
            assert s.headers["User-Agent"] == scfg.USER_AGENT
            assert "ru" in s.headers["Accept-Language"]
        finally:
            s.close()

    def test_iter_author_cards_filters_by_author(self, monkeypatch):
        page1 = _page_html(
            _card_html(pid="1", name="Свой пак", authors=("Ася",)),
            _card_html(pid="2", name="Чужой пак", authors=("Боря",)))

        def fake_fetch(session, author, page=1):
            return page1 if page == 1 else "<html></html>"
        monkeypatch.setattr(sb, "fetch_author_html", fake_fetch)
        out = list(sb.iter_author_cards(FakeSession(), "ася"))
        assert [c.name for c in out] == ["Свой пак"]

    def test_iter_author_cards_stops_on_repeat(self, monkeypatch):
        page = _page_html(_card_html(pid="1", name="Пак", authors=("Ася",)))
        calls = []

        def fake_fetch(session, author, page=1):
            calls.append(page)
            return page and _page_html(
                _card_html(pid="1", name="Пак", authors=("Ася",)))
        monkeypatch.setattr(sb, "fetch_author_html", fake_fetch)
        out = list(sb.iter_author_cards(FakeSession(), "Ася", max_pages=10))
        assert len(out) == 1
        assert len(calls) == 2  # вторая страница с теми же паками остановила обход
