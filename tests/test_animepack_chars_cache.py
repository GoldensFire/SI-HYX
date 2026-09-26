# -*- coding: utf-8 -*-
"""Генерация аниме-пака: сложность персонажей, кэш каталога и отметки списков.

Здесь всё, что появилось вокруг узнаваемости: «в избранном» у персонажа как
вторая мера сложности, узнаваемость франшизы по её частям, кэш каталога
Shikimori на диске, отметки «у кого из списков есть тайтл» и длительность
картинки в ответе.
"""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import xml.etree.ElementTree as ET

import pytest

from animepack import (CHAR_KIND, AnimePackGenerator, PackSettings,
                       ShikimoriDbCache, arrange_questions, build_content_xml,
                       char_fav_level, char_fav_price_shift,
                       char_question_level, shiki_cache_signature)
from shikimori_api import franchise_parts_index
from test_animepack import make_anime, make_candidate

from si_hyx_parts.tests.test_animepack_chars_cache.gen import (
    _gen,
    _part,
    test_franchise_index_rises_with_live_seasons,
    test_franchise_index_softens_the_age_penalty_for_sequels,
    test_franchise_index_ignores_unpopular_parts,
    test_franchise_index_of_nothing_is_zero,
    test_franchise_index_does_not_age_the_newest_top_part,
    test_char_fav_level,
    test_char_question_level_mixes_title_and_favorites,
    _char_cand,
    test_char_price_follows_the_favorites,
    test_char_level_avg_pulls_characters_to_the_middle,
    test_char_reach_is_bounded_by_the_title,
    _seven,
    _warm_up,
    test_unreachable_char_level_moves_to_the_nearest_one,
    test_char_level_returns_when_easier_characters_show_up,
    test_reachable_char_level_still_gives_up_out_loud,
    test_first_title_swap_is_silent,
    test_rejected_character_costs_no_extra_requests,
    test_repeated_complaints_are_hushed,
    _Clock,
)

from si_hyx_parts.tests.test_animepack_chars_cache.test_rate_limiter_honors_the_minute_budget import (
    test_rate_limiter_honors_the_minute_budget,
    test_rate_limiter_penalty_slows_every_thread,
    test_shikimori_api_asks_no_more_than_ninety_a_minute,
    test_shikimori_get_penalizes_on_429,
    test_shikimori_get_penalizes_adapter_retry_error,
    test_db_cache_survives_a_reload,
    test_db_cache_keeps_only_a_few_filter_sets,
    test_cache_signature_follows_the_filters,
    test_catalog_is_asked_once_and_then_taken_from_cache,
    test_refresh_db_forgets_the_old_catalog,
    test_refresh_db_takes_the_whole_catalog_not_just_a_packs_worth,
    test_refresh_db_keeps_what_it_managed_to_take_when_stopped,
    test_mark_owners_signs_random_titles_with_nicknames,
    test_mark_owners_does_nothing_without_the_checkbox,
    _poster_item,
    test_answer_image_time_is_a_setting,
    test_answer_image_time_never_exceeds_the_ceiling,
)


# ── Сетевой слой: «в избранном» и части франшизы ────────────────────────────
_CHAR_PAGE = ('<body class="p-characters p-characters-show">'
              '<div class="b-favoured"><div class="subheadline">'
              '<div class="linkeable" data-href="/characters/417/favoured">'
              'В избранном<div class="count">10740</div></div></div>'
              '<div class="cc">…</div></div></body>')

from si_hyx_parts.tests.test_animepack_chars_cache.test_character_favorites_are_read_from_the_page import (
    test_character_favorites_are_read_from_the_page,
    test_character_without_favorites_is_zero_not_unknown,
    test_franchise_parts_returns_every_season,
    test_franchise_parts_keep_quiet_about_a_broken_batch,
    test_franchise_parts_stay_below_graphql_complexity_limit,
    test_franchise_parts_preserve_bracketed_cache_key,
    _replic,
    test_artist_comes_first_and_nicks_are_bare,
    test_nicks_alone_when_the_question_is_not_a_song,
)
