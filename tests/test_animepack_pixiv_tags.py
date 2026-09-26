# -*- coding: utf-8 -*-
"""Списки меток-исключений: правки пользователя, минусы в запрос, окно."""
from types import SimpleNamespace

import pixiv_art_tags as tags
from pixiv_art_api import PixivArtClient
from pixiv_tag_rules import TagRules
from si_hyx_parts.animepack_tab.pixiv_tag_dialog import PixivTagDialog
from test_animepack_pixiv_pool import PopularPixivApi, _row


def _settings(**kw):
    base = dict(pixiv_groups_off=[], pixiv_tags_off=[], pixiv_tags_extra=[])
    base.update(kw)
    return SimpleNamespace(**base)


def test_built_in_lists_block_by_default():
    rules = TagRules.from_settings(_settings())
    assert rules.hits({"guro"}) and rules.hits({"mmd"}) and rules.hits({"落書き"})


def test_a_switched_off_group_stops_blocking_but_shock_never_does():
    """Группу можно выключить целиком — кроме шок-контента (он locked)."""
    rules = TagRules.from_settings(
        _settings(pixiv_groups_off=["three_d", "rough", "shock"]))
    assert not rules.hits({"mmd"}) and not rules.hits({"落書き"})
    assert rules.hits({"guro"})          # шок не выключается ничем


def test_a_single_term_can_be_taken_off_the_list():
    rules = TagRules.from_settings(_settings(pixiv_tags_off=["mmd"]))
    assert not rules.hits({"mmd"})
    assert rules.hits({"koikatsu"})      # соседи по группе остались


def test_own_terms_block_and_go_first_into_the_query():
    """Свои метки пользователя идут в запрос раньше встроенных.

    Мест в запросе всего 256 символов, и просил их именно он."""
    rules = TagRules.from_settings(_settings(pixiv_tags_extra=["ふともも"]))
    assert rules.hits({"ふともも"})
    assert rules.query_tail("鬼滅の刃").startswith("-ふともも ")


def test_the_query_never_outgrows_the_pixiv_limit():
    """Длиннее 256 символов Pixiv отдаёт ноль работ (проверено на живом API)."""
    rules = TagRules.from_settings(_settings())
    for word in ("鬼滅の刃", "PSYCHO-PASS サイコパス", "x" * 200):
        tail = rules.query_tail(word)
        assert len(f"{word} {tail}".strip()) <= tags.QUERY_LIMIT


def test_terms_with_a_space_inside_never_become_a_minus():
    """«-girls love» Pixiv поймёт как «минус girls И обязательное love»."""
    rules = TagRules.from_settings(_settings(pixiv_tags_extra=["girls love"]))
    assert "girls" not in rules.query_tail("鬼滅の刃")
    assert rules.hits({"girls love"})    # у себя такая метка всё равно режется


def test_r18_goes_into_the_query_as_a_minus_when_excluded():
    """Взрослых работ в верхушке тега больше, чем всего остального вместе."""
    client = PixivArtClient("token", api=PopularPixivApi([]))
    rows = []

    def remember(method, url, params=None, headers=None):
        rows.append(params["word"])
        return SimpleNamespace(illusts=[])

    client.api.no_auth_requests_call = remember
    client._minus_rows("鬼滅の刃", lambda _row: True, {})
    assert rows and rows[0].startswith("鬼滅の刃 -R-18 ")


class MinusPixivApi(PopularPixivApi):
    """Отвечает на «по части тега» работой ЧУЖОГО тайтла — как живой Pixiv."""

    def __init__(self, exact, partial):
        super().__init__(exact)
        self.partial = list(partial)
        self.targets = []

    def no_auth_requests_call(self, method, url, params=None, headers=None):
        self.targets.append(params["search_target"])
        rows = (self.partial if params["search_target"] == "partial_match_for_tags"
                else self.popular)
        return SimpleNamespace(illusts=list(rows))


def _tagged(name, *names, **kw):
    row = _row(name, **kw)
    row.tags = [SimpleNamespace(name=n, translated_name="") for n in names]
    return row


def test_partial_search_keeps_only_works_with_the_exact_tag():
    """«По части тега» по запросу «Air» приносит работы с меткой «Fairy».

    Точной метки у них нет вовсе, и такой арт ответом быть не может."""
    mine = _tagged("mine", "Air", marks=900)
    alien = _tagged("alien", "Fairy", marks=9000)
    api = MinusPixivApi([], [alien, mine])
    client = PixivArtClient("token", api=api)
    rows = client._minus_rows("Air", lambda _row: True, {})
    assert [r.image_urls.original for r in rows] == [mine.image_urls.original]
    assert api.targets[-1] == "partial_match_for_tags"


def test_comics_are_let_in_only_by_the_setting():
    """Записи типа «манга» — комиксы; по умолчанию мимо, галочкой можно пустить."""
    comic = _tagged("comic", "鬼滅の刃", type="manga")
    assert not PixivArtClient("token", api=PopularPixivApi([]))._safe(comic)
    loose = PixivArtClient("token", api=PopularPixivApi([]),
                           settings=_settings(pixiv_allow_manga=True))
    assert loose._safe(comic)


def test_the_dialog_returns_what_was_ticked(qapp):
    """Окно отдаёт ровно три списка, которые ждут настройки пака."""
    from PyQt6.QtCore import Qt
    dialog = PixivTagDialog(None, groups_off=["three_d"], tags_off=["落書き"],
                            extra=["ふともも"])
    assert dialog.result_lists() == (["three_d"], ["落書き"], ["ふともも"])
    for i in range(dialog.tree.topLevelItemCount()):
        node = dialog.tree.topLevelItem(i)
        if node.data(0, Qt.ItemDataRole.UserRole) == "rough":
            node.setCheckState(0, Qt.CheckState.Unchecked)
    dialog.ed_new.setText("チラシの裏")
    dialog._add()
    groups_off, off_terms, extra = dialog.result_lists()
    assert "rough" in groups_off and extra == ["ふともも", "チラシの裏"]
    # Метка выключенной группы по одной уже не считается — вся группа off.
    assert "落書き" not in off_terms
    dialog._reset()
    assert dialog.result_lists() == ([], [], [])
