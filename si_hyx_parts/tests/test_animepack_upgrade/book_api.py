# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""BookApi. Public namespace: test_animepack_upgrade."""
import test_animepack_upgrade as _api


class BookApi(_api.FakeApi):
    """Shikimori с двумя базами: аниме и книги (поиск по ним раздельный)."""

    def __init__(self, animes=None, mangas=None):
        super().__init__(animes if animes is not None else [])
        self.books = list(mangas or [])
        self.manga_calls = []

    def search_mangas_by_name(self, name, limit=0):
        self.manga_calls.append(name)
        needle = _api.norm_title(name)
        return [c for c in self.books
                if any(needle in _api.norm_title(n) or _api.norm_title(n) in needle
                       for n in [c.get("russian"), c.get("name"),
                                 c.get("english")] if n)]

BookApi.__module__ = _api.__name__
_api.BookApi = BookApi

def _book_pack(theme: str, answer: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<package name="Пак">'
            f'<rounds><round name="Раунд 1"><themes><theme name="{theme}">'
            f"<questions>{_api._q5(100, answer=answer)}</questions>"
            "</theme></themes></round></rounds></package>")

_book_pack.__module__ = _api.__name__
_api._book_pack = _book_pack

def test_book_theme_asks_shikimori_for_the_manga(tmp_path):
    api = _api.BookApi([_api.AKAME_ANIME], [_api.AKAME_MANGA])
    result = _api._run(tmp_path, _api._book_pack("Manga(для читающих)", "Убийца Акамэ!"),
                  _api.UpgradeSettings(strip_specials=False, add_poster=False),
                  api=api)
    assert api.manga_calls == ["Убийца Акамэ!"] and api.calls == []
    assert "Akame ga Kiru!" in _api._answers(result)            # синоним манги
    assert "Красноглазый убийца" not in _api._answers(result)   # это уже аниме

test_book_theme_asks_shikimori_for_the_manga.__module__ = _api.__name__
_api.test_book_theme_asks_shikimori_for_the_manga = test_book_theme_asks_shikimori_for_the_manga

def test_ordinary_theme_still_asks_for_the_anime(tmp_path):
    api = _api.BookApi([_api.AKAME_ANIME], [_api.AKAME_MANGA])
    result = _api._run(tmp_path, _api._book_pack("Аниме-опенинги", "Убийца Акамэ!"),
                  _api.UpgradeSettings(strip_specials=False, add_poster=False),
                  api=api)
    assert api.manga_calls == [] and api.calls == ["Убийца Акамэ!"]
    assert "Красноглазый убийца" in _api._answers(result)

test_ordinary_theme_still_asks_for_the_anime.__module__ = _api.__name__
_api.test_ordinary_theme_still_asks_for_the_anime = test_ordinary_theme_still_asks_for_the_anime

def test_book_theme_falls_back_to_the_anime_for_names(tmp_path):
    """Книги нет — названия всё равно доищем, это лучше, чем ничего."""
    api = _api.BookApi([_api.AKAME_ANIME], [])
    result = _api._run(tmp_path, _api._book_pack("Манга", "Убийца Акамэ!"),
                  _api.UpgradeSettings(strip_specials=False, add_poster=False),
                  api=api)
    assert api.manga_calls and api.calls
    assert "Красноглазый убийца" in _api._answers(result)

test_book_theme_falls_back_to_the_anime_for_names.__module__ = _api.__name__
_api.test_book_theme_falls_back_to_the_anime_for_names = test_book_theme_falls_back_to_the_anime_for_names

def test_book_theme_takes_no_poster_from_the_anime(tmp_path, monkeypatch):
    """Главное про книжные темы: обложку из аниме не тянем вовсе."""
    api = _api.BookApi([_api.AKAME_ANIME], [])
    result = _api._run(tmp_path, _api._book_pack("Манга", "Убийца Акамэ!"),
                  _api.UpgradeSettings(strip_specials=False), api=api)
    assert result.posters == []

test_book_theme_takes_no_poster_from_the_anime.__module__ = _api.__name__
_api.test_book_theme_takes_no_poster_from_the_anime = test_book_theme_takes_no_poster_from_the_anime

def test_book_theme_can_be_switched_off(tmp_path):
    api = _api.BookApi([_api.AKAME_ANIME], [_api.AKAME_MANGA])
    _api._run(tmp_path, _api._book_pack("Манга", "Убийца Акамэ!"),
         _api.UpgradeSettings(strip_specials=False, add_poster=False,
                         book_themes=False), api=api)
    assert api.manga_calls == [] and api.calls == ["Убийца Акамэ!"]

test_book_theme_can_be_switched_off.__module__ = _api.__name__
_api.test_book_theme_can_be_switched_off = test_book_theme_can_be_switched_off
