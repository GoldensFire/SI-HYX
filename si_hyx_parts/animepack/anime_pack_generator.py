# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""AnimePackGenerator. Public namespace: animepack."""
from __future__ import annotations
import animepack as _api


# ─────────────────────────────────────────────────────────────────────────────
# Генератор
# ─────────────────────────────────────────────────────────────────────────────
class AnimePackGenerator:
    """Полный цикл: списки аниме → песни → медиа → .siq.

    Все длительные шаги зовут log()/progress() и проверяют should_stop(), чтобы
    вкладка могла показывать ход дела и останавливать генерацию.
    """

    from si_hyx_parts.animepack.anime_pack_generator___init import __init__, log
    from si_hyx_parts.animepack.ai_art_generation import generate_ai_art
    from si_hyx_parts.animepack.pixiv_art_generation import (
        download_pixiv_art,
        _first_season_card,
    )
    from si_hyx_parts.animepack.manga_panel import download_manga_panel
    from si_hyx_parts.animepack.sakuga_generation import download_sakuga
    from si_hyx_parts.animepack.dialogue_generation import make_dialogue_question

    # Сколько раз подряд можно повторить в логе одну и ту же жалобу.
    WARN_REPEATS = 3

    from si_hyx_parts.animepack.anime_pack_generator__log_rare import (
        _log_rare,
        _log_warn_totals,
        stopped,
        _timed,
        _merge_spans,
        log_stage_times,
        log_gemini_spent,
        _over_budget,
        _media_size,
        load_exclusions,
        _root_excluded,
        _user_lists,
        _fetch_user_list,
        _order_by_shares,
        collect_manga_ids,
        collect_anime_ids,
    )

    # Сколько карточек тянем из каталога Shikimori на один вопрос пака: часть
    # отсеют фильтры (оценка, жанры, дубли франшиз), часть не переживёт загрузку
    # медиа, так что запас нужен изрядный.
    RANDOM_OVERSHOOT = 8
    # Песенному паку запас нужен куда больше: песня в AnisongDB нашлась лишь у
    # 59 случайных тайтлов Shikimori из 150 (у ТВ-сериалов — у 31 из 52), а
    # мастер-лист AMQ по определению состоит из одних только «песенных».
    RANDOM_OVERSHOOT_SONGS = 20
    # У манги отсев самый длинный, и запаса «как у аниме» ей мало. Случайная
    # манга из каталога — это почти всегда безвестный тайтл: из 100 карточек,
    # набранных прежним запасом, рамку сложности не прошла НИ ОДНА сама по себе
    # (проходят только те, у кого есть популярная аниме-экранизация), а из
    # прошедших ещё часть не находится на MangaDex. Сотня карточек на пак
    # оставляла долю манги пустой ещё до первого запроса к MangaDex.
    RANDOM_OVERSHOOT_MANGA = 40
    RANDOM_MAX_PAGES = 60

    from si_hyx_parts.animepack.anime_pack_generator__random_shikimori_ids import (
        _random_shikimori_ids,
        _fetch_random_cards,
    )

    # Обход каталога ЦЕЛИКОМ (кнопка «Обновить базу»). Порядок тут нужен
    # устойчивый: при order: random сервер тасует выборку на каждый запрос,
    # страницы накладываются друг на друга, и обход упирался в «страницу без
    # новых id» на первых же сотнях карточек, сколько бы их ни было в каталоге
    # на самом деле. С order: id каждая страница отдаёт свой кусок ровно один
    # раз, и каталог по-настоящему кончается.
    FULL_ORDER = "id"
    # Предохранитель от бесконечного цикла, если сервер вдруг перестанет
    # слушаться page: 50 карточек на страницу — это четверть миллиона тайтлов,
    # больше всего каталога Shikimori.
    FULL_MAX_PAGES = 5000

    from si_hyx_parts.animepack.anime_pack_generator_fetch_full_catalog import (
        fetch_full_catalog,
        _animes_by_ids,
        _mangas_by_ids,
        _anime_feed,
        _silent_kind,
        iter_candidates,
        _merge_streams,
        _iter_manga_candidates,
        _iter_anime_candidates,
        _iter_silent_candidates,
        _random_source,
        _ids_are_ann,
    )

    from si_hyx_parts.animepack.anime_pack_generator__iter_picture_candidates import (
        _iter_picture_candidates,
        _load_franchise_indexes,
        _franchise_index,
        _accept_anime,
        _release_candidate,
        _trim_start,
        prepare_dirs,
        _get_bytes,
        _cached_bytes,
        audio_filters,
        opus_args,
        audio_encode_args,
        _run_killable,
        _run_capture,
        _kill,
        stop_processes,
    )

    from si_hyx_parts.animepack.anime_pack_generator_download_audio import (
        download_audio,
        _url_ext,
        _save_image,
        _save_reusable_image,
        _to_avif,
        _pick_character,
        _title_favorites,
        _download_character,
        _frame_urls,
        _pick_frame_url,
        save_frames_history,
    )

    from si_hyx_parts.animepack.anime_pack_generator__poster_bytes import (
        _poster_bytes,
        _tmdb_poster,
        download_images,
        _theme_video,
        video_encode_args,
        _video_seconds,
        _video_start,
        download_video,
    )

    from si_hyx_parts.animepack.anime_pack_generator_encode_reveal import encode_reveal
    from si_hyx_parts.animepack.anime_pack_generator_encode_dvd import encode_dvd

    from si_hyx_parts.animepack.anime_pack_generator_pixel_encode_args import (
        pixel_encode_args,
        pixel_filter,
        download_pixel,
        build_anagram,
        make_plot_question,
        _fetch_media,
        _use_first_title,
    )

    from si_hyx_parts.animepack.anime_pack_generator__media_base import (
        _media_base,
        _prefers_music,
        _pick_kind,
        _level_fits,
        _remember_level,
        _bench_candidate,
        _take_level_bench,
        _rebook_candidate,
    )

    # Сколько книг просматриваем ради книжных долей, прежде чем перейти на
    # отложенные. Каталог книг вчетверо больше каталога аниме, а подходящих по
    # долям (экранизованные, манхва, маньхуа) в нём немного: перебирать его до
    # конца — только время, отложенных на скамейке к тому моменту с запасом.
    BOOK_SCAN_PER_SLOT = 100
    BOOK_SCAN_MIN = 200

    # Столько кандидатов подряд можно отвергнуть ради средней сложности.
    LEVEL_AVG_GIVE_UP = 60
    # То же для персонажей. Порог ниже: каждый отвергнутый персонаж — это уже
    # сделанный запрос к Shikimori, и полсотни таких подряд заняли бы минуту.
    CHAR_LEVEL_GIVE_UP = 20

    # «В избранном у всех на свете»: с таким числом char_question_level даёт
    # самый лёгкий уровень, какой у персонажа этого тайтла вообще возможен.
    _FAV_ALL = 10 ** 9
    # Со стольких увиденных персонажей верим границам достижимого. Раньше
    # недостижимость вскрывалась только после двух десятков впустую перебранных
    # кандидатов — а каждый из них это ещё и запрос к Shikimori. Меньше десятка
    # брать не стоит: границы ещё гуляют, и генератор объявляет о переезде
    # несколько раз подряд.
    CHAR_REACH_SAMPLE = 10

    from si_hyx_parts.animepack.anime_pack_generator__char_reach import (
        _char_reach,
        _char_level_fits,
        _remember_char_level,
        _drop_kind,
        _spend_kind,
        _close_spent_streams,
        _share_out_dead,
    )

    # Отчёт «почему кандидатов не хватило» и совет по делу.
    from si_hyx_parts.animepack.shortage_report import _log_shortage

    from si_hyx_parts.animepack.anime_pack_generator_select_songs import (
        select_songs,
        mark_list_owners,
        write_package,
        cleanup,
    )

    # Обновление базы по частям: каталог аниме, каталог манги, узнаваемость
    # франшиз и «хвосты» кэша обновляются порознь (панель «Что в базе»).
    from si_hyx_parts.animepack.anime_pack_generator_refresh_db import refresh_db

    from si_hyx_parts.animepack.anime_pack_generator_run import run

AnimePackGenerator.__module__ = _api.__name__
_api.AnimePackGenerator = AnimePackGenerator
