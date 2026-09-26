# -*- coding: utf-8 -*-
"""Вкладка «Апгрейд пака»: спецвопросы, варианты названий и картинки.

Сеть не трогается вовсе: вместо ShikimoriApi подставляется FakeApi, считающий
запросы (кэш «один тайтл — один запрос» — часть поведения, а не оптимизация).
ffmpeg тоже не зовётся: кодирование картинки подменяется _fake_avif.
"""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import os
import threading
import xml.etree.ElementTree as ET
import zipfile

import pytest

from animepack_upgrade import (KNOWN_LABELS, LOOSE_THRESHOLD,
                               PackUpgrader, SPECIAL_LABELS,
                               UpgradeError, UpgradeSettings, answer_queries,
                               answer_query, audio_filter_chain, copy_zip_entry,
                               entry_basename, example_lines, is_media_entry,
                               iter_questions, iter_themes, known_labels_in,
                               loudnorm_filter,
                               match_score, media_jobs, nearest_bitrate,
                               nearest_height, normalize_profile,
                               norm_title, parse_content, parse_probe_codec,
                               parse_probe_kbps,
                               pick_card, referenced_names, remove_poster,
                               card_names, character_hit,
                               looks_like_character_name, read_pack_info,
                               is_book_theme, is_typo, matched_by_typo,
                               merge_text_with_audio,
                               recased, retarget_refs, spelling_names,
                               strip_year, synonym_only, tag_fn, title_variants,
                               unused_entries)
from filenames import escape_uri_string

from si_hyx_parts.tests.test_animepack_upgrade.pack import _pack, _q5, _q4, _siq


NARUTO = {
    "id": 20, "malId": 20, "russian": "Наруто", "name": "Naruto",
    "english": "Naruto", "japanese": "ナルト",
    "licenseNameRu": "Наруто. Книга первая",
    "synonyms": ["NARUTO -ナルト-", "Наруто ТВ-1"],
}
BLEACH = {"id": 269, "malId": 269, "russian": "Блич", "name": "Bleach",
          "english": "Bleach", "synonyms": [], "licenseNameRu": ""}

from si_hyx_parts.tests.test_animepack_upgrade.fake_api import (
    FakeApi,
    _run,
    _out_root,
    test_v5_special_types_are_removed,
    test_v5_special_params_are_removed_but_question_survives,
    test_v4_type_element_is_removed,
    test_simple_questions_are_left_alone,
    test_secret_no_question_is_skipped_by_default,
    test_secret_no_question_converted_when_asked,
    test_question_without_content_is_skipped,
    test_specials_untouched_when_function_is_off,
    test_answer_query_strips_song_year_and_quotes,
    test_answer_queries_try_the_title_before_the_dash,
    test_answer_queries_use_other_answers_and_dedupe,
    test_answer_queries_are_capped_and_filtered,
    test_title_found_by_a_later_answer,
    test_other_answers_are_not_searched_when_switched_off,
    test_variants_are_appended_to_answers,
    test_variant_already_written_in_the_pack_is_not_repeated,
    test_year_is_never_written_into_the_answer,
    test_strip_year_leaves_the_name_alone,
    test_cjk_variants_are_never_added,
    test_existing_answers_are_not_duplicated,
    test_all_variant_kinds_are_always_added,
    test_max_variants_caps_the_list,
    test_unknown_answer_is_left_alone,
    test_short_and_numeric_answers_are_not_searched,
    test_same_title_is_queried_once,
    test_titles_untouched_when_function_is_off,
)

from si_hyx_parts.tests.test_animepack_upgrade.test_failed_search_does_not_break_the_run import (
    test_failed_search_does_not_break_the_run,
    test_strict_match_needs_exact_name,
    test_loose_match_accepts_close_names,
)


# Живой случай пользователя: в паке «Gokukoku no Brunhildr», на Shikimori —
# «Brynhildr». Из-за одной буквы пропадали и постер, и все варианты названия.
BRYNHILDR = {"id": 21, "malId": 21, "name": "Gokukoku no Brynhildr",
             "russian": "Тёмная кровь Брунгильды", "english": None,
             "licenseNameRu": "", "synonyms": [], "kind": "tv"}

from si_hyx_parts.tests.test_animepack_upgrade.test_typo_in_the_answer_still_finds_the_title import (
    test_typo_in_the_answer_still_finds_the_title,
    test_typo_is_the_same_title,
    test_typo_does_not_swallow_other_titles,
    test_typo_titles_are_counted_and_reported,
)


# «Tegami bachi» в паке — «Tegamibachi» на Shikimori: то же слово, разбитое на
# слоги по вкусу писавшего.
TEGAMI = {"id": 22, "malId": 22, "name": "Tegamibachi",
          "russian": "Почтовая пчела", "english": None, "licenseNameRu": "",
          "synonyms": [], "kind": "tv"}

from si_hyx_parts.tests.test_animepack_upgrade.test_extra_space_in_the_answer_is_the_same_title import (
    test_extra_space_in_the_answer_is_the_same_title,
    test_short_names_are_not_glued_together,
)


# Ответ «Shelter»: так зовут и знаменитый клип Porter Robinson, и никому не
# известный фильм 2015 года — в пак вставлялась обложка фильма.
SHELTER_CLIP = {"id": 31, "malId": 31, "name": "Shelter (Music)",
                "russian": "Убежище", "english": "Shelter",
                "licenseNameRu": "", "synonyms": [], "kind": "music",
                "popularity": 221562.0}
SHELTER_MOVIE = {"id": 32, "malId": 32, "name": "Shelter", "russian": None,
                 "english": None, "licenseNameRu": "", "synonyms": [],
                 "kind": "movie", "popularity": 832.0}

from si_hyx_parts.tests.test_animepack_upgrade.test_famous_clip_beats_an_unknown_namesake import (
    test_famous_clip_beats_an_unknown_namesake,
    test_clip_without_a_namesake_is_still_not_an_answer,
    test_clip_takes_the_answer_only_with_a_huge_edge,
    test_clip_matched_by_a_synonym_is_ignored_as_before,
    test_match_score_is_one_for_any_of_the_names,
    test_title_variants_keep_generator_order,
    test_source_pack_is_never_modified,
    test_media_entries_are_copied_as_is,
    test_namespace_survives_the_rewrite,
    test_out_dir_setting_is_honoured,
    test_second_run_does_not_overwrite_the_first,
    test_capitalized_content_xml_is_found,
    test_broken_archive_is_reported,
    test_archive_without_content_xml_is_reported,
    test_pack_without_questions_is_reported,
    test_all_functions_off_is_rejected,
    test_image_limit_above_threshold_is_rejected,
    test_entity_declarations_are_refused,
    test_stop_writes_nothing,
    _fake_avif,
    _img_settings,
)


HEAVY = b"J" * 200_000                  # «тяжёлая» картинка для тестов
HEAVY_KB = len(HEAVY)

from si_hyx_parts.tests.test_animepack_upgrade.q5_image import (
    _q5_image,
    test_heavy_image_becomes_avif_and_ref_follows,
    test_light_images_and_other_media_are_left_alone,
    test_image_that_got_heavier_is_kept_as_is,
    test_percent_encoded_v4_reference_is_retargeted,
    test_brackets_in_name_survive_reencoding,
    test_brackets_survive_even_when_the_name_is_taken,
    test_escape_uri_string_matches_dotnet,
    test_taken_avif_name_does_not_clobber_the_neighbour,
    test_retarget_refs_touches_only_media_elements,
    test_images_untouched_when_function_is_off,
    test_source_pack_survives_image_compression,
    test_examples_show_three_of_each,
    test_examples_say_so_when_nothing_changed,
    test_examples_show_compressed_images,
    test_changes_are_reported_in_pack_order,
    _answers,
    test_case_is_fixed_to_shikimori_spelling,
    test_case_fix_handles_shouting_and_keeps_song_after_dash,
    test_case_fix_changes_only_letters_case,
    test_case_fix_can_be_switched_off,
    test_case_fix_needs_exact_match,
)


# ── Постер тайтла в ответе ───────────────────────────────────────────────────
POSTERED = dict(BLEACH, poster={"originalUrl": "https://shikimori/x.jpg"})

from si_hyx_parts.tests.test_animepack_upgrade.fake_poster import (
    _fake_poster,
    _poster_settings,
    test_poster_goes_into_the_answer,
    test_one_poster_file_per_title,
    test_poster_is_not_added_over_existing_picture,
    test_poster_is_not_added_over_existing_media,
    test_poster_still_goes_next_to_answer_text,
    test_poster_is_not_added_over_v4_media_after_marker,
    test_poster_can_be_switched_off,
    test_poster_needs_exact_match,
    test_title_without_poster_is_skipped,
    test_poster_in_v4_goes_after_the_marker,
    test_poster_name_does_not_overwrite_existing_file,
    test_poster_temp_files_are_cleaned_up,
    test_read_pack_info_returns_name_author_and_themes,
    test_read_pack_info_survives_a_pack_without_info,
    test_special_labels_match_siquester_wording,
    test_examples_show_recased_and_posters,
)


# ── Клипы и промо — не тайтлы ────────────────────────────────────────────────
# Живой случай: ответ «Mumei» (имя героя) находил вокалоид-клип «Mumei», а
# «Teto Kasane» — клип «Yababaina», у которого это лежит в синонимах.
CLIP_MUMEI = {"id": 56886, "malId": 56886, "name": "Mumei", "russian": "Мумэй",
              "english": None, "japanese": "mumei", "licenseNameRu": None,
              "synonyms": [], "kind": "music",
              "poster": {"originalUrl": "https://shikimori/m.jpg"}}
CLIP_YABA = {"id": 58640, "malId": 58640, "name": "Yababaina", "russian": None,
             "english": None, "licenseNameRu": None, "kind": "music",
             "synonyms": ["YABABAINA - Satapan P feat.Miku Hatsune",
                          "Teto Kasane", "Zundamon"]}

from si_hyx_parts.tests.test_animepack_upgrade.test_music_and_promo_are_not_titles import (
    test_music_and_promo_are_not_titles,
    test_every_clip_kind_is_refused,
    test_real_kinds_and_unknown_ones_pass,
    test_synonym_only_match_is_refused,
    test_synonym_match_counts_when_the_title_is_in_the_answer,
    test_case_is_not_taken_from_the_japanese_field,
    test_leading_capital_is_never_lowered,
    test_which_answers_are_worth_a_character_query,
    test_character_hit_compares_latin_names_only,
    CharApi,
)


# Тайтл, который сам по себе на ответ не похож: совпадение приходит близостью
# строк, и вот тут мнение базы персонажей уже что-то значит.
LOOSE_CARD = {"id": 7, "malId": 7, "russian": None, "name": "Teto Kasanee",
              "english": None, "licenseNameRu": "", "synonyms": [], "kind": "tv"}

from si_hyx_parts.tests.test_animepack_upgrade.test_character_answer_is_left_alone import (
    test_character_answer_is_left_alone,
    test_exact_title_is_not_second_guessed,
    test_character_check_can_be_switched_off,
    test_same_character_is_asked_once,
    test_skipped_characters_are_reported,
    _q5_items,
    _shot,
)


# Известные подписи тут выключены нарочно: ниже проверяется ОБЩЕЕ правило
# («текст стоит в каждом вопросе темы»), и «Назвать аниме» взято как обычный
# короткий текст. Списочные подписи проверяются отдельно, см. KNOWN_REPEATS.
ONLY_REPEATS = UpgradeSettings(strip_specials=False, add_titles=False,
                               compress_images=False,
                               strip_known_labels=False)
KNOWN_REPEATS = UpgradeSettings(strip_specials=False, add_titles=False,
                                compress_images=False)

from si_hyx_parts.tests.test_animepack_upgrade.themes import (
    _themes,
    test_repeated_text_is_removed_from_every_question,
    test_repeated_text_left_alone_if_one_question_lacks_it,
    test_repeats_are_counted_per_theme,
    test_theme_of_one_question_is_not_touched,
    test_question_is_never_emptied,
    test_long_text_is_not_a_caption,
    test_repeat_matching_ignores_case_and_punctuation,
    test_v4_repeat_is_removed_before_the_marker,
    test_repeats_can_be_switched_off,
    test_repeats_are_reported,
)


# ── Ответ, записанный двумя названиями через косую черту ─────────────────────
UENO = {"id": 37920, "malId": 37920, "russian": "Неуклюжая Уэно",
        "name": "Ueno-san wa Bukiyou", "english": "How Clumsy you are, Miss Ueno",
        "synonyms": ["Уэно-сан, какая же Вы неуклюжая"], "licenseNameRu": ""}

from si_hyx_parts.tests.test_animepack_upgrade.test_slash_answer_is_split_into_both_names import (
    test_slash_answer_is_split_into_both_names,
    test_whole_answer_is_tried_before_its_parts,
    test_slash_answer_finds_the_title,
    test_slash_answer_counts_as_an_exact_match,
    _stats,
)


KYOUKAI = {"id": 18153, "malId": 18153, "russian": "По ту сторону границы",
           "name": "Kyoukai no Kanata", "english": "Beyond the Boundary",
           "synonyms": ["За гранью", "Beyond the Horizon"], "licenseNameRu": "",
           "kind": "tv", "statusesStats": _stats(1264006)}
SWEAT = {"id": 1072, "malId": 1072, "russian": "За гранью", "name": "Sweat Punch",
         "english": "Sweat Punch", "synonyms": ["Комедия", "Kigeki"],
         "licenseNameRu": "", "kind": "ova", "statusesStats": _stats(52878)}

from si_hyx_parts.tests.test_animepack_upgrade.test_popular_synonym_beats_an_obscure_own_name import (
    test_popular_synonym_beats_an_obscure_own_name,
    test_close_popularity_still_prefers_the_own_name,
    test_synonym_only_match_without_popularity_is_still_refused,
    test_the_more_popular_of_two_own_names_wins,
    RawApi,
    test_kyoukai_no_kanata_is_found_in_a_pack,
    test_book_themes_are_recognised,
    test_other_themes_are_not_book_themes,
)


AKAME_MANGA = {"id": 25132, "malId": 25132, "russian": "Убийца Акамэ!",
               "name": "Akame ga Kill!", "english": "Akame ga Kill!",
               "synonyms": ["Akame ga Kiru!"], "licenseNameRu": "",
               "kind": "manga", "poster": {"originalUrl": "http://x/m.jpg"}}
AKAME_ANIME = {"id": 22199, "malId": 22199, "russian": "Убийца Акамэ!",
               "name": "Akame ga Kill!", "english": "Akame ga Kill!",
               "synonyms": ["Красноглазый убийца"], "licenseNameRu": "",
               "kind": "tv", "poster": {"originalUrl": "http://x/a.jpg"}}

from si_hyx_parts.tests.test_animepack_upgrade.book_api import (
    BookApi,
    _book_pack,
    test_book_theme_asks_shikimori_for_the_manga,
    test_ordinary_theme_still_asks_for_the_anime,
    test_book_theme_falls_back_to_the_anime_for_names,
    test_book_theme_takes_no_poster_from_the_anime,
    test_book_theme_can_be_switched_off,
)


# ── Функция «Текст под звук» ─────────────────────────────────────────────────
ONLY_MERGE = UpgradeSettings(strip_specials=False, add_titles=False,
                             compress_images=False, strip_repeated_text=False,
                             drop_empty_questions=False, compress_audio=False,
                             drop_unused=False)

from si_hyx_parts.tests.test_animepack_upgrade.sound import (
    _sound,
    _items_of,
    test_text_before_audio_plays_together,
    test_text_before_a_picture_is_left_alone,
    test_already_merged_text_is_not_touched,
    test_merge_can_be_switched_off,
    test_v4_text_before_audio_gets_time_minus_one,
    test_merge_is_reported_in_the_table,
    test_merge_leaves_the_text_in_place,
    test_merge_helper_needs_the_audio_right_after,
)


# ── Функция «Удалить пустые вопросы» ─────────────────────────────────────────
ONLY_EMPTY = UpgradeSettings(strip_specials=False, add_titles=False,
                             compress_images=False, strip_repeated_text=False,
                             compress_audio=False)

from si_hyx_parts.tests.test_animepack_upgrade.q5_empty import (
    _q5_empty,
    test_empty_question_is_deleted_even_with_an_answer,
    test_question_without_params_at_all_is_deleted,
    test_v4_question_with_only_the_answer_after_marker_is_deleted,
    test_question_with_media_only_is_not_empty,
    test_theme_left_without_questions_goes_too,
    test_pack_of_only_empty_questions_is_left_alone,
    test_empty_questions_survive_when_the_function_is_off,
    test_empty_questions_are_reported,
)


# ── Функция «Сжать тяжёлое аудио» ────────────────────────────────────────────
BIG_AUDIO = b"S" * 300_000              # «тяжёлая» дорожка для тестов

from si_hyx_parts.tests.test_animepack_upgrade.aud_settings import (
    _aud_settings,
    _fake_opus,
    _q5_audio,
    test_heavy_audio_becomes_opus_and_ref_follows,
    test_audio_that_is_already_quiet_enough_is_left_alone,
    test_unknown_bitrate_is_recoded_anyway,
    test_light_audio_and_video_are_left_alone,
    test_audio_that_got_heavier_is_kept_as_is,
    test_taken_opus_name_does_not_clobber_the_neighbour,
    test_audio_untouched_when_function_is_off,
    test_audio_and_images_do_not_fight_for_names,
    test_audio_is_reported,
    test_probe_kbps_takes_the_stream_bitrate_first,
    test_probe_kbps_falls_back_to_size_and_duration,
    test_probe_kbps_gives_up_quietly,
    test_nearest_bitrate_snaps_to_the_list,
    test_media_keeps_its_compression_and_bytes,
    test_media_survives_when_the_fast_copy_gives_up,
    test_fast_copy_leaves_no_garbage_when_it_gives_up,
    test_encrypted_entry_is_not_touched_by_the_fast_copy,
    test_media_jobs_never_exceeds_the_cores,
    test_images_keep_pack_order_when_encoded_in_parallel,
    test_tracks_keep_pack_order_when_encoded_in_parallel,
    test_a_track_that_failed_does_not_shift_the_others,
    test_poster_size_reaches_the_report,
)

from si_hyx_parts.tests.test_animepack_upgrade.test_poster_that_never_arrives_leaves_no_dangling_ref import (
    test_poster_that_never_arrives_leaves_no_dangling_ref,
    test_failed_poster_is_taken_out_of_a_v4_question,
    test_failed_download_does_not_break_the_run,
    test_remove_poster_takes_the_picture_out_of_both_formats,
    test_poster_threads_do_not_outlive_the_run,
    test_stop_in_the_middle_of_media_leaves_nothing_behind,
    test_stop_during_posters_closes_the_threads,
    test_no_temp_files_are_left_behind,
    test_known_label_goes_even_if_one_question_lacks_it,
    test_known_label_can_be_switched_off,
    test_known_label_never_empties_a_question,
    test_known_labels_are_matched_without_case_and_punctuation,
    test_known_label_and_repeated_text_live_together,
)


# ── Неиспользуемые файлы ─────────────────────────────────────────────────────
ONLY_UNUSED = UpgradeSettings(strip_specials=False, add_titles=False,
                              compress_images=False, strip_repeated_text=False,
                              drop_empty_questions=False, compress_audio=False,
                              drop_unused=True)

from si_hyx_parts.tests.test_animepack_upgrade.test_unused_media_is_dropped_and_referenced_survives import (
    test_unused_media_is_dropped_and_referenced_survives,
    test_pack_logo_is_not_garbage,
    test_service_files_are_never_garbage,
    test_all_media_unused_touches_nothing,
    test_recoded_image_is_not_counted_as_garbage,
    test_percent_encoded_name_is_matched_to_its_reference,
    test_unused_helpers_are_pure,
    test_unused_is_reported,
    test_loudnorm_is_off_unless_asked,
    test_loudnorm_string_is_the_one_from_the_process_tab,
    test_norm_recodes_even_a_track_that_is_quiet_enough,
    test_norm_keeps_the_track_even_if_it_got_heavier,
    test_norm_goes_into_the_ffmpeg_line,
)


# ── Сжатие видео ─────────────────────────────────────────────────────────────
BIG_VIDEO = b"V" * 400_000              # «тяжёлый» ролик для тестов

from si_hyx_parts.tests.test_animepack_upgrade.vid_settings import (
    _vid_settings,
    _fake_av1,
    _q5_video,
    test_heavy_video_becomes_av1_and_ref_follows,
    test_light_non_av1_video_is_recoded_only_with_the_checkbox,
    test_light_av1_video_is_left_alone,
    test_heavy_av1_video_is_recoded_anyway,
    test_video_that_got_heavier_stays_as_it_was,
    test_images_and_audio_are_not_video,
    test_video_ffmpeg_line_is_the_one_from_the_process_tab,
    test_video_report_and_helpers,
    test_video_is_reported,
    test_profile_name_is_sanitised,
)
