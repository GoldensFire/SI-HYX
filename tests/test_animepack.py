# -*- coding: utf-8 -*-
"""Вкладка «Генерация аниме-пака»: фильтры, сборка content.xml и сеть.

Сеть везде подменяется FakeSession из conftest — ни один тест наружу не ходит.
Отдельно закреплены места, где оригинальный ASPG ошибался: snake_case в теле
запроса к AnisongDB, булевы isDub/isRebroadcast, пагинация списков, замена
песни с несостоявшейся загрузкой, формат длительности, дедуп по аниме.
"""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import json
import os
import xml.etree.ElementTree as ET
import zipfile

import pytest

from conftest import FakeResponse, FakeSession

import animepack
import animepack_api as api
from animepack import (CHAR_KIND, FRAME_KIND, MEDIA_NAME_PREFIX, VIDEO_KIND,
                       AnimePackGenerator, PackSettings,
                       SongCandidate, UserList, arrange_questions,
                       build_content_xml, clear_user_list_cache,
                       filter_anime, filter_song,
                       fmt_duration, fmt_elapsed, franchise_key, index_level,
                       load_frame_history, price_for_difficulty,
                       save_frame_history, song_kind,
                       song_difficulty_bonus, song_tag, title_root,
                       answer_title, siq_answer_roots)

from si_hyx_parts.tests.test_animepack.forget_user_lists import (
    _forget_user_lists,
    make_song,
    make_anime,
    make_candidate,
    test_price_for_difficulty,
    test_fmt_duration_pads_and_clamps,
    test_song_kind,
    test_filter_song_defaults_pass,
    test_filter_song_bool_dub_and_rebroadcast,
    test_filter_song_category_and_difficulty,
    test_filter_song_requires_media_fields,
    test_filter_anime_ranges,
    test_filter_anime_screenshots_only_when_images_needed,
    test_filter_anime_genres_include_exclude,
    test_franchise_key_unique_for_empty,
    test_song_kinds_are_a_ratio_not_a_count,
    test_validate_images_longer_than_cut,
    test_settings_roundtrip,
    _parse,
    test_build_content_xml_structure,
    test_build_content_xml_images_and_hint,
    test_build_content_xml_skips_missing_media,
    test_build_content_xml_answer_text,
    test_answer_replic_is_artist_without_lists,
    test_answer_year_not_doubled,
    test_answer_without_song_is_just_title,
    test_answer_content_has_no_text_block,
)

from si_hyx_parts.tests.test_animepack.test_answer_bare_russian_title_goes_last import (
    test_answer_bare_russian_title_goes_last,
    test_shuffle_questions_keeps_given_order,
    test_package_author,
    test_answer_poster_is_not_simultaneous,
    test_kind_price_step_is_fixed,
    test_kind_price_step_opening_cheaper_than_insert,
    test_audio_filters_match_processing_tab,
    test_frames_only_question_is_image_and_answer_has_no_song,
    test_frames_only_takes_titles_without_shikimori_screenshots,
    test_frames_only_candidates_skip_anisong_for_lists,
    test_mixed_quotas_split_frames_and_songs,
    test_mixed_select_songs_makes_both_kinds,
    test_mixed_pack_xml_has_image_and_audio_questions,
    test_frame_question_works_without_shikimori_screenshots,
    test_index_level,
    test_title_root,
    test_sequel_inherits_franchise_index,
    test_level_filter_skips_too_easy,
    test_dedup_by_title_root_when_franchise_missing,
    test_compression_off_copies_source_stream,
    test_compression_off_keeps_source_extensions,
    test_url_ext_ignores_query,
)

from si_hyx_parts.tests.test_animepack.test_fmt_elapsed import (
    test_fmt_elapsed,
    test_similar_count_one_is_allowed,
    test_sort_by_index_orders_pack_and_prices,
    test_build_content_xml_stops_when_songs_run_out,
    test_anisong_uses_snake_case_body,
    test_anisong_empty_ids_makes_no_request,
    test_mal_paginates_and_filters_statuses,
    test_mal_unknown_user_message,
    test_shikimori_exact_nickname_lookup,
    test_shikimori_ignores_paging_and_stops,
    test_shikimori_missing_user_raises,
    test_amq_library_uses_cache,
    _generator,
    _pair,
    test_iter_candidates_dedups_anime_and_franchise,
    test_similar_requires_several_users,
    test_select_songs_replaces_failed_downloads,
    test_select_songs_respects_type_quotas,
)

from si_hyx_parts.tests.test_animepack.test_run_writes_readable_siq import (
    test_run_writes_readable_siq,
    test_run_refuses_broken_settings,
    test_song_tag,
    test_answer_tag_goes_before_year,
    _frame_cand,
    test_frame_pick_is_random_and_unique_within_pack,
    test_frame_pick_never_repeats_within_pack,
    test_frames_no_repeat_skips_history,
    test_frames_no_repeat_drops_title_without_fresh_frames,
    test_save_frames_history_appends_used_only,
    test_song_kind_checkboxes_filter_songs_and_quotas,
    test_only_endings_pack_takes_endings,
    test_common_base_means_no_lists_are_requested,
    test_user_lists_are_asked_once_per_run_of_the_program,
    test_characters_api_keeps_all_names,
    test_character_answer_and_price_multiplier,
    test_supporting_character_costs_more_than_main,
)

from si_hyx_parts.tests.test_animepack.test_character_answers_do_not_accept_bare_title import (
    test_character_answers_do_not_accept_bare_title,
    test_character_answers_list_every_name_of_the_character,
    test_chars_only_quotas_and_xml,
    test_mixed_quotas_split_frames_chars_and_songs,
    test_hint_plays_together_with_song,
    test_hint_over_a_video_is_spoken_not_written,
    test_video_hint_obeys_its_checkbox,
    test_hint_calls_insert_song_ost,
    test_media_files_named_after_title,
    test_answer_title_strips_song_year_and_tag,
    test_siq_exclusion_skips_same_franchise,
    test_pack_stops_when_budget_is_spent,
    test_pack_stops_before_it_grows_too_heavy,
    test_budget_warmup_does_not_stop_a_normal_pack,
    test_amq_base_is_only_for_song_packs,
    test_shikimori_is_the_default_base,
    test_animethemes_maps_tags_to_video_links,
    test_video_question_replaces_audio_in_xml,
    test_video_falls_back_to_audio,
    test_video_start_is_random_like_a_song,
)

from si_hyx_parts.tests.test_animepack.test_video_start_falls_back_when_length_unknown import (
    test_video_start_falls_back_when_length_unknown,
    test_video_download_seeks_to_the_random_start,
    test_video_seconds_asks_ffprobe_once,
    test_video_encode_args_follow_settings,
    test_video_defaults_are_fifteen_seconds_crf45_fastest,
    test_video_share_lives_in_the_mix_slider,
    test_video_share_only_counts_with_the_checkbox,
    test_legacy_song_video_becomes_a_full_video_share,
    test_video_question_answer_is_the_same_as_a_song,
    test_video_price_follows_its_song_type,
    test_video_audio_is_opus_like_every_other_track,
    test_song_difficulty_bonus,
    test_difficulty_bonus_only_for_songs,
    test_percents_normalise_and_split_all_questions,
    test_legacy_mix_settings_become_percents,
)
