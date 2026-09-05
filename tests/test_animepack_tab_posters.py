# -*- coding: utf-8 -*-
"""Настройки обложек во вкладке «Генерация аниме-пака»: галочка кладовой,
ключ TMDB и кнопка «Очистить» — они должны переживать сохранение/загрузку и не
падать на пустой кладовой."""
import poster_cache


class _FakeMain:
    """Ключи API живут в главном окне (Настройки → «Ключи API»)."""

    def __init__(self, **keys):
        self.api_keys = dict(keys)

    def get_api_key(self, name):
        return str(self.api_keys.get(name, "") or "").strip()

    def set_api_key(self, name, value, save=True):
        self.api_keys[name] = str(value or "").strip()

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_poster_settings_survive_a_round_trip(qapp):
    import animepack_tab

    tab = animepack_tab.AnimePackTab(_FakeMain(tmdb="tmdb-key"))
    tab.chk_poster_cache.setChecked(False)
    s = tab.collect()
    assert s.tmdb_key == "tmdb-key" and s.poster_cache is False

    other = animepack_tab.AnimePackTab(_FakeMain())
    other.apply_settings(s.to_dict())
    # Ключ из старых настроек вкладки переезжает в общие настройки программы.
    assert other.main.get_api_key("tmdb") == "tmdb-key"
    assert other.chk_poster_cache.isChecked() is False
    # Подпись и кнопка прячутся вместе с галочкой, кнопка ключа TMDB — нет.
    assert other.lbl_poster_cache.isVisibleTo(other) is False
    assert other.btn_tmdb_key.isVisibleTo(other) is True


def test_clearing_an_empty_shelf_says_so(qapp):
    import animepack_tab

    tab = animepack_tab.AnimePackTab()
    tab.chk_poster_cache.setChecked(True)
    assert "пуста" in tab.lbl_poster_cache.text()
    poster_cache.put(poster_cache.anime_key(1), b"x" * 2048, ".jpg")
    tab._refresh_poster_cache()
    assert "1 шт." in tab.lbl_poster_cache.text()
    tab._clear_poster_cache()
    assert poster_cache.stats() == (0, 0)
    assert "пуста" in tab.lbl_poster_cache.text()
